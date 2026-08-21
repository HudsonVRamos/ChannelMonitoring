"""AudioTrackTester — testa todos os audio tracks durante uma Channel Session.

Wrapper sobre AudioMonitor e SettingsDialogManager existentes, adicionando
integração com VideoTelemetryCollector para anotações de correlação
entre track switches e telemetria de vídeo.

Fluxo principal:
1. Abre Settings Dialog via CapabilityMap
2. Descobre tracks disponíveis na seção "IDIOMA ALTERNATIVO"
3. Para cada track: seleciona, valida via Shaka API, coleta RMS
4. Restaura track original ao final
5. Fecha Settings Dialog

Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from src.unified_channel_monitor.config import UnifiedMonitorConfig
from src.unified_channel_monitor.models import AudioTrackResult

if TYPE_CHECKING:
    from playwright.async_api import Page

    from src.unified_channel_monitor.video_telemetry import (
        VideoTelemetryCollector,
    )

logger = logging.getLogger(__name__)

# Seção do Settings Dialog onde ficam as opções de áudio
_AUDIO_SECTION_TITLE = "IDIOMA ALTERNATIVO"

# JavaScript para consultar tracks de áudio via Shaka Player API
_JS_GET_AUDIO_TRACKS = """
() => {
    if (!window.player || !window.player.getAudioTracks) return null;
    return window.player.getAudioTracks();
}
"""

# JavaScript para coletar amostra RMS via Web Audio API
_JS_COLLECT_RMS = """
() => {
    const analyser = window.__audioMonitorAnalyser;
    if (!analyser) return null;
    const data = new Float32Array(analyser.fftSize);
    analyser.getFloatTimeDomainData(data);
    let sum = 0;
    for (let i = 0; i < data.length; i++) {
        sum += data[i] * data[i];
    }
    return Math.sqrt(sum / data.length);
}
"""

# JavaScript para inicializar AudioContext (caso não exista)
_JS_INIT_AUDIO_CONTEXT = """
() => {
    if (window.__audioMonitorCtx) return true;
    const video = document.querySelector('video');
    if (!video) return false;
    const ctx = new AudioContext();
    const source = ctx.createMediaElementSource(video);
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 2048;
    source.connect(analyser);
    analyser.connect(ctx.destination);
    window.__audioMonitorCtx = ctx;
    window.__audioMonitorAnalyser = analyser;
    return true;
}
"""


class AudioTrackTester:
    """Testa todos os audio tracks durante uma Channel Session.

    Descobre tracks disponíveis no Settings Dialog, seleciona cada um,
    valida a troca via Shaka Player API e coleta telemetria RMS via
    Web Audio API. Integra-se com o VideoTelemetryCollector para anotar
    amostras de telemetria com o contexto do track switch em andamento.

    Attributes:
        _page: Instância do Playwright Page compartilhada.
        _capability_map: CapabilityMap com estratégias de interação.
        _config: Configuração unificada com timeouts e janelas.
        _telemetry_collector: Coletor de telemetria de vídeo em background.
    """

    def __init__(
        self,
        page: Page,
        capability_map: dict,
        config: UnifiedMonitorConfig,
        telemetry_collector: VideoTelemetryCollector,
    ) -> None:
        """Inicializa o AudioTrackTester.

        Args:
            page: Instância do Playwright Page para interação.
            capability_map: Mapa de capabilities do player.
            config: Configuração unificada com timeouts.
            telemetry_collector: Coletor de telemetria para anotações.
        """
        self._page = page
        self._capability_map = capability_map
        self._config = config
        self._telemetry_collector = telemetry_collector

    async def test_all_tracks(self) -> list[AudioTrackResult]:
        """Descobre e testa todos os audio tracks disponíveis.

        Fluxo:
        1. Abre Settings Dialog usando estratégia do CapabilityMap
        2. Descobre tracks na seção "IDIOMA ALTERNATIVO"
        3. Armazena track original para restauração posterior
        4. Para cada track:
           - Seleciona via UI (clique na opção)
           - Anota telemetria com contexto do switch
           - Valida switch via Shaka API (polling com timeout)
           - Se validado: coleta RMS durante janela configurada
           - Se timeout: marca FAIL com reason "switch_timeout"
        5. Restaura track original
        6. Fecha Settings Dialog

        Returns:
            Lista de AudioTrackResult com resultado de cada track.

        Req 5.1: Abre Settings Dialog usando estratégia do CapabilityMap.
        Req 5.2: Identifica todos os tracks na seção "IDIOMA ALTERNATIVO".
        Req 5.3: Valida switch via Shaka API getAudioTracks() em 5s.
        Req 5.4: Coleta RMS durante janela configurada (default 30s).
        Req 5.5: Marca FAIL com "switch_timeout" se não validar.
        Req 5.6: Restaura track original ao final.
        """
        results: list[AudioTrackResult] = []

        # 1. Abrir Settings Dialog (Req 5.1)
        dialog_opened = await self._open_settings_dialog()
        if not dialog_opened:
            logger.error(
                "Não foi possível abrir o Settings Dialog. "
                "Nenhum track de áudio será testado."
            )
            return results

        # 2. Descobrir tracks disponíveis (Req 5.2)
        tracks = await self._discover_audio_tracks()
        if not tracks:
            logger.warning(
                "Nenhum track de áudio encontrado na seção "
                f"'{_AUDIO_SECTION_TITLE}'."
            )
            await self._close_settings_dialog()
            return results

        logger.info(
            f"Encontrados {len(tracks)} tracks de áudio: "
            f"{[t['text'] for t in tracks]}"
        )

        # 3. Identificar track original (Req 5.6)
        original_track = self._find_selected_track(tracks)
        logger.info(
            f"Track original: '{original_track}'"
        )

        # 4. Testar cada track
        for track in tracks:
            track_name = track["text"]
            result = await self._test_single_track(track_name)
            results.append(result)

        # 5. Restaurar track original (Req 5.6)
        if original_track:
            await self._restore_original_track(original_track)

        # 6. Fechar Settings Dialog
        await self._close_settings_dialog()

        logger.info(
            f"Teste de áudio concluído: {len(results)} tracks, "
            f"{sum(1 for r in results if r.status == 'PASS')} PASS, "
            f"{sum(1 for r in results if r.status == 'FAIL')} FAIL."
        )

        return results

    async def _test_single_track(
        self, track_name: str
    ) -> AudioTrackResult:
        """Testa um único track de áudio.

        Seleciona o track via UI, valida via Shaka API e coleta
        telemetria RMS se a validação for bem-sucedida.

        Args:
            track_name: Nome do track a ser testado.

        Returns:
            AudioTrackResult com o resultado do teste.
        """
        start_time = time.time()

        try:
            # Selecionar track via UI
            logger.info(f"Testando track de áudio: '{track_name}'")
            selected = await self._select_track(track_name)
            if not selected:
                duration_ms = int(
                    (time.time() - start_time) * 1000
                )
                return AudioTrackResult(
                    track_name=track_name,
                    status="FAIL",
                    fail_reason="switch_timeout",
                    switch_validated=False,
                    duration_ms=duration_ms,
                )

            # Anotar telemetria com contexto do switch
            switch_context = {
                "track_name": track_name,
                "track_type": "audio",
                "switch_timestamp": datetime.now(
                    timezone.utc
                ).isoformat(),
            }
            self._telemetry_collector.annotate_current_sample(
                switch_context
            )

            # Validar switch via Shaka API (Req 5.3)
            validated = await self._validate_switch_shaka(
                track_name
            )

            if not validated:
                # Timeout — marcar FAIL (Req 5.5)
                duration_ms = int(
                    (time.time() - start_time) * 1000
                )
                logger.warning(
                    f"Track '{track_name}': switch não validado "
                    f"via Shaka API dentro do timeout."
                )
                return AudioTrackResult(
                    track_name=track_name,
                    status="FAIL",
                    fail_reason="switch_timeout",
                    switch_validated=False,
                    duration_ms=duration_ms,
                )

            # Coleta RMS (Req 5.4)
            rms_avg, audio_present_ratio = (
                await self._collect_rms_telemetry()
            )

            duration_ms = int(
                (time.time() - start_time) * 1000
            )

            # Classificar resultado
            status = "PASS" if (
                audio_present_ratio
                >= self._config.audio_pass_threshold
            ) else "FAIL"

            return AudioTrackResult(
                track_name=track_name,
                status=status,
                fail_reason=None,
                rms_avg=rms_avg,
                audio_present_ratio=audio_present_ratio,
                switch_validated=True,
                duration_ms=duration_ms,
            )

        except Exception as exc:
            # Erro inesperado — registrar e marcar FAIL
            duration_ms = int(
                (time.time() - start_time) * 1000
            )
            logger.error(
                f"Erro inesperado ao testar track '{track_name}': "
                f"{exc}",
                exc_info=True,
            )
            return AudioTrackResult(
                track_name=track_name,
                status="FAIL",
                fail_reason=str(exc),
                switch_validated=False,
                duration_ms=duration_ms,
            )

    async def _open_settings_dialog(self) -> bool:
        """Abre o Settings Dialog via hover + clique no ícone.

        Utiliza seletores do player para exibir controles via hover
        e então clica no ícone de configurações.

        Returns:
            True se o dialog foi aberto com sucesso.
        """
        try:
            # Hover no player para exibir controles
            await self._page.hover("video")
            await asyncio.sleep(0.3)

            # Localizar e clicar no settings icon
            settings_selector = self._get_settings_selector()
            await self._page.click(settings_selector)
            await asyncio.sleep(0.5)

            logger.info("Settings Dialog aberto para teste de áudio.")
            return True

        except Exception as exc:
            logger.error(
                f"Falha ao abrir Settings Dialog: {exc}"
            )
            return False

    async def _close_settings_dialog(self) -> None:
        """Fecha o Settings Dialog pressionando Escape."""
        try:
            await self._page.keyboard.press("Escape")
            await asyncio.sleep(0.3)
            logger.debug("Settings Dialog fechado.")
        except Exception as exc:
            logger.warning(
                f"Erro ao fechar Settings Dialog: {exc}"
            )

    async def _discover_audio_tracks(self) -> list[dict]:
        """Descobre tracks de áudio na seção 'IDIOMA ALTERNATIVO'.

        Executa JavaScript no DOM para localizar a seção e extrair
        as opções disponíveis com seu estado de seleção.

        Returns:
            Lista de dicts com 'text' e 'is_selected' por track.
        """
        js_discover = """
        (sectionTitle) => {
            const allElements = document.querySelectorAll('*');
            let sectionHeader = null;

            for (const el of allElements) {
                const text = el.textContent?.trim();
                if (text === sectionTitle
                    && el.children.length === 0) {
                    sectionHeader = el;
                    break;
                }
                if (el.innerText?.trim() === sectionTitle
                    && el.children.length <= 1) {
                    sectionHeader = el;
                    break;
                }
            }

            if (!sectionHeader) return [];

            let sectionContainer = sectionHeader.parentElement;
            for (let i = 0; i < 3; i++) {
                if (!sectionContainer) break;
                const items = sectionContainer.querySelectorAll(
                    'li, [role="option"], [role="menuitemradio"], '
                    + '[role="menuitem"], button'
                );
                if (items.length > 0) break;
                sectionContainer = sectionContainer.parentElement;
            }

            if (!sectionContainer) return [];

            const optionItems = sectionContainer.querySelectorAll(
                'li, [role="option"], [role="menuitemradio"], '
                + '[role="menuitem"]'
            );

            let items = optionItems.length > 0
                ? optionItems
                : sectionContainer.querySelectorAll(
                    'button, div[class*="option"], '
                    + 'div[class*="item"]'
                );

            const results = [];
            for (const item of items) {
                const itemText = item.textContent?.trim();
                if (!itemText || itemText === sectionTitle) continue;
                if (results.some(r => r.text === itemText)) continue;

                const classList = item.className || '';
                const ariaSelected =
                    item.getAttribute('aria-selected');
                const ariaChecked =
                    item.getAttribute('aria-checked');
                const isSelected = (
                    classList.includes('active') ||
                    classList.includes('selected') ||
                    classList.includes('checked') ||
                    classList.includes('current') ||
                    ariaSelected === 'true' ||
                    ariaChecked === 'true' ||
                    item.hasAttribute('data-selected') ||
                    item.hasAttribute('data-active')
                );

                results.push({
                    text: itemText,
                    is_selected: isSelected
                });
            }

            return results;
        }
        """

        try:
            result = await self._page.evaluate(
                js_discover, _AUDIO_SECTION_TITLE
            )
            if isinstance(result, list):
                return result
            return []
        except Exception as exc:
            logger.error(
                f"Erro ao descobrir tracks de áudio: {exc}"
            )
            return []

    async def _select_track(self, track_name: str) -> bool:
        """Seleciona um track via clique na UI do Settings Dialog.

        Garante que o dialog está aberto e clica na opção
        correspondente ao track_name.

        Args:
            track_name: Nome do track a selecionar.

        Returns:
            True se o clique foi executado com sucesso.
        """
        js_click = """
        ([sectionTitle, optionText]) => {
            const allElements = document.querySelectorAll('*');
            let sectionHeader = null;

            for (const el of allElements) {
                const text = el.textContent?.trim();
                if (text === sectionTitle
                    && el.children.length === 0) {
                    sectionHeader = el;
                    break;
                }
                if (el.innerText?.trim() === sectionTitle
                    && el.children.length <= 1) {
                    sectionHeader = el;
                    break;
                }
            }

            if (!sectionHeader) return false;

            let sectionContainer = sectionHeader.parentElement;
            for (let i = 0; i < 3; i++) {
                if (!sectionContainer) break;
                const items = sectionContainer.querySelectorAll(
                    'li, [role="option"], [role="menuitemradio"], '
                    + '[role="menuitem"], button'
                );
                if (items.length > 0) break;
                sectionContainer = sectionContainer.parentElement;
            }

            if (!sectionContainer) return false;

            const optionItems = sectionContainer.querySelectorAll(
                'li, [role="option"], [role="menuitemradio"], '
                + '[role="menuitem"], button, '
                + 'div[class*="option"], div[class*="item"]'
            );

            for (const item of optionItems) {
                const itemText = item.textContent?.trim();
                if (itemText === optionText) {
                    item.click();
                    return true;
                }
            }

            return false;
        }
        """

        try:
            # Garantir dialog aberto antes de clicar
            await self._ensure_dialog_open()

            result = await self._page.evaluate(
                js_click, [_AUDIO_SECTION_TITLE, track_name]
            )
            if result:
                logger.debug(
                    f"Track '{track_name}' selecionado via UI."
                )
                await asyncio.sleep(0.3)
            return bool(result)
        except Exception as exc:
            logger.error(
                f"Erro ao selecionar track '{track_name}': {exc}"
            )
            return False

    async def _validate_switch_shaka(
        self, track_name: str
    ) -> bool:
        """Valida switch de áudio via Shaka Player API.

        Realiza polling em getAudioTracks() até que o track ativo
        contenha o nome esperado ou até o timeout configurado.

        Args:
            track_name: Nome do track que deveria estar ativo.

        Returns:
            True se o track ativo corresponde ao esperado.

        Req 5.3: Validar via getAudioTracks() dentro de 5 segundos.
        """
        timeout = self._config.track_switch_timeout_s
        poll_interval = 0.5
        deadline = time.time() + timeout

        while time.time() < deadline:
            try:
                tracks = await self._page.evaluate(
                    _JS_GET_AUDIO_TRACKS
                )
                if tracks is None:
                    await asyncio.sleep(poll_interval)
                    continue

                for track in tracks:
                    if track.get("active"):
                        # Comparar por label ou language
                        label = track.get("label", "")
                        language = track.get("language", "")
                        if (
                            track_name in label
                            or track_name in language
                            or label in track_name
                            or language in track_name
                        ):
                            logger.info(
                                f"Switch validado via Shaka: "
                                f"'{track_name}' ativo."
                            )
                            return True
            except Exception as exc:
                logger.warning(
                    f"Erro ao consultar Shaka API: {exc}"
                )

            await asyncio.sleep(poll_interval)

        return False

    async def _collect_rms_telemetry(
        self,
    ) -> tuple[float | None, float | None]:
        """Coleta telemetria RMS via Web Audio API.

        Inicializa AudioContext se necessário e coleta amostras RMS
        durante a janela configurada (audio_telemetry_window_s),
        com intervalo audio_sample_interval_s entre amostras.

        Returns:
            Tupla (rms_avg, audio_present_ratio) ou (None, None) se falhar.

        Req 5.4: Coleta RMS durante janela configurada (default 30s).
        """
        # Inicializar AudioContext se necessário
        try:
            init_ok = await self._page.evaluate(
                _JS_INIT_AUDIO_CONTEXT
            )
            if not init_ok:
                logger.warning(
                    "Não foi possível inicializar AudioContext. "
                    "Coleta RMS indisponível."
                )
                return None, None
        except Exception as exc:
            logger.warning(
                f"Erro ao inicializar AudioContext: {exc}"
            )
            return None, None

        # Coletar amostras durante a janela
        window_s = self._config.audio_telemetry_window_s
        interval_s = self._config.audio_sample_interval_s
        threshold = self._config.audio_rms_threshold

        rms_samples: list[float] = []
        start = time.time()

        while (time.time() - start) < window_s:
            try:
                rms = await self._page.evaluate(_JS_COLLECT_RMS)
                if rms is not None:
                    rms_samples.append(rms)
            except Exception as exc:
                logger.warning(
                    f"Erro ao coletar amostra RMS: {exc}"
                )

            remaining = window_s - (time.time() - start)
            if remaining > 0:
                wait = min(interval_s, remaining)
                await asyncio.sleep(wait)

        if not rms_samples:
            return None, None

        rms_avg = sum(rms_samples) / len(rms_samples)
        audio_present = sum(
            1 for r in rms_samples if r > threshold
        )
        audio_present_ratio = audio_present / len(rms_samples)

        logger.info(
            f"Telemetria RMS: avg={rms_avg:.4f}, "
            f"ratio={audio_present_ratio:.2f} "
            f"({len(rms_samples)} amostras)"
        )

        return rms_avg, audio_present_ratio

    async def _restore_original_track(
        self, original_track: str
    ) -> None:
        """Restaura o track de áudio original.

        Reabre o dialog se necessário e seleciona o track original.

        Args:
            original_track: Nome do track a restaurar.

        Req 5.6: Restaurar track original ao final dos testes.
        """
        logger.info(
            f"Restaurando track original: '{original_track}'"
        )
        await self._ensure_dialog_open()
        await self._select_track(original_track)
        await asyncio.sleep(0.5)

    async def _ensure_dialog_open(self) -> None:
        """Garante que o Settings Dialog está aberto.

        Se o dialog fechou automaticamente após uma seleção,
        reabre via hover + clique.
        """
        try:
            # Verificar se dialog está visível
            dialog_selectors = [
                ".settings-panel",
                '[role="dialog"]',
                '[aria-label*="settings"]',
            ]
            for selector in dialog_selectors:
                locator = self._page.locator(selector)
                if await locator.is_visible():
                    return  # Dialog já está aberto

            # Dialog não visível — reabrir
            await self._open_settings_dialog()
        except Exception:
            # Best effort — tentar reabrir
            await self._open_settings_dialog()

    def _get_settings_selector(self) -> str:
        """Obtém o seletor do ícone de settings do CapabilityMap.

        Consulta o capability_map para estratégia de interação com
        o ícone de configurações. Retorna seletor CSS adequado.

        Returns:
            Seletor CSS para o ícone de configurações.
        """
        # Tentar extrair do capability_map
        if isinstance(self._capability_map, dict):
            settings_info = self._capability_map.get("settings")
            if settings_info and isinstance(settings_info, dict):
                selector = settings_info.get("selector")
                if selector:
                    return selector

        # Fallback: seletores comuns para botão de settings
        return (
            'button[aria-label*="settings"], '
            'button[aria-label*="configurações"], '
            '.settings-button, '
            '[data-testid="settings"]'
        )

    @staticmethod
    def _find_selected_track(
        tracks: list[dict],
    ) -> str | None:
        """Encontra o track atualmente selecionado na lista.

        Args:
            tracks: Lista de dicts com 'text' e 'is_selected'.

        Returns:
            Nome do track selecionado ou None se nenhum marcado.
        """
        for track in tracks:
            if track.get("is_selected"):
                return track["text"]
        # Se nenhum marcado como selecionado, usar o primeiro
        if tracks:
            return tracks[0]["text"]
        return None
