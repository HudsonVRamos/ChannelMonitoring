"""SubtitleTrackTester — testa todos os subtitle tracks de um canal.

Wrapper sobre SubtitleMonitor e SettingsDialogManager existentes,
adicionando integração com VideoTelemetryCollector para anotações
de contexto durante track switches.

Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from src.audio_subtitle_monitor.config import AudioSubtitleConfig
from src.audio_subtitle_monitor.settings_dialog_manager import (
    SUBTITLE_SECTION_TITLE,
    SettingsDialogManager,
)
from src.audio_subtitle_monitor.subtitle_monitor import SubtitleMonitor
from src.unified_channel_monitor.config import UnifiedMonitorConfig
from src.unified_channel_monitor.models import SubtitleTrackResult

if TYPE_CHECKING:
    from playwright.async_api import Page

    from src.player_discovery.models.capability_map import CapabilityMap
    from src.unified_channel_monitor.video_telemetry import (
        VideoTelemetryCollector,
    )

logger = logging.getLogger(__name__)


class SubtitleTrackTester:
    """Testa todos os subtitle tracks durante uma Channel Session.

    Wrapper que coordena SettingsDialogManager (abertura do dialog,
    descoberta de opções, seleção) com SubtitleMonitor (validação
    via Shaka API e monitoramento de cues via TextTrack API).

    Integra com VideoTelemetryCollector para anotar amostras de
    telemetria com contexto de track switch.
    """

    def __init__(
        self,
        page: Page,
        capability_map: CapabilityMap,
        config: UnifiedMonitorConfig,
        telemetry_collector: VideoTelemetryCollector,
    ) -> None:
        """Inicializa o SubtitleTrackTester.

        Args:
            page: Instância do Playwright Page compartilhada.
            capability_map: Mapa de capabilities do player para
                estratégias de interação com o Settings Dialog.
            config: Configuração unificada com timeouts e intervalos.
            telemetry_collector: Coletor de telemetria para anotações
                de contexto durante switches de tracks.
        """
        self._page = page
        self._capability_map = capability_map
        self._config = config
        self._telemetry_collector = telemetry_collector

        # Cria AudioSubtitleConfig compatível com os componentes existentes
        self._legacy_config = AudioSubtitleConfig(
            subtitle_cue_timeout_s=config.subtitle_cue_timeout_s,
            subtitle_poll_interval_s=config.subtitle_poll_interval_s,
            track_switch_timeout_s=config.track_switch_timeout_s,
        )

        # Componentes existentes reutilizados
        self._dialog_manager = SettingsDialogManager(
            page=page,
            capability_map=capability_map,
            config=self._legacy_config,
        )
        self._subtitle_monitor = SubtitleMonitor(
            page=page,
            config=self._legacy_config,
        )

    async def test_all_tracks(self) -> list[SubtitleTrackResult]:
        """Descobre e testa todos os subtitle tracks disponíveis.

        Fluxo:
        1. Tenta abrir o Settings Dialog
        2. Se falhar → retorna todos os tracks como SKIP
           (reason="dialog_unavailable")
        3. Descobre opções na seção "LEGENDAS"
        4. Armazena track original para restauração
        5. Para cada track: seleciona, valida switch, monitora cue
        6. Restaura track original
        7. Fecha o dialog

        Returns:
            Lista de SubtitleTrackResult com status de cada track.
        """
        # Passo 1: Tentar abrir o Settings Dialog
        try:
            dialog_opened = await self._dialog_manager.open_dialog()
        except Exception as exc:
            logger.error(
                "Exceção ao abrir Settings Dialog: %s", exc
            )
            dialog_opened = False

        # Passo 2: Se dialog falhou → SKIP todos os tracks
        if not dialog_opened:
            logger.warning(
                "Settings Dialog indisponível. "
                "Marcando todos os subtitle tracks como SKIP."
            )
            return self._mark_all_skip_dialog_unavailable()

        # Passo 3: Descobrir opções de legendas
        try:
            options = (
                await self._dialog_manager.discover_subtitle_options()
            )
        except Exception as exc:
            logger.error(
                "Erro ao descobrir opções de legendas: %s", exc
            )
            await self._safe_close_dialog()
            return self._mark_all_skip_dialog_unavailable()

        if not options:
            logger.info(
                "Nenhuma opção de legenda encontrada."
            )
            await self._safe_close_dialog()
            return []

        # Passo 4: Armazenar track original
        original_track_name: str | None = None
        for opt in options:
            if opt.is_selected:
                original_track_name = opt.text
                break

        logger.info(
            "Tracks de legenda encontrados: %d. "
            "Track original: '%s'.",
            len(options),
            original_track_name,
        )

        # Passo 5: Testar cada track
        results: list[SubtitleTrackResult] = []
        for option in options:
            result = await self._test_single_track(option.text)
            results.append(result)

        # Passo 6: Restaurar track original
        if original_track_name:
            await self._restore_original_track(original_track_name)

        # Passo 7: Fechar dialog
        await self._safe_close_dialog()

        return results

    async def _test_single_track(
        self, track_name: str
    ) -> SubtitleTrackResult:
        """Testa um único subtitle track.

        Fluxo por track:
        1. Selecionar o track na UI
        2. Anotar telemetria com contexto do switch
        3. Validar switch via Shaka API (getTextTracks)
        4. Se switch timeout → FAIL com reason "switch_timeout"
        5. Se validado → monitorar cue via TextTrack API
        6. Se no cue → FAIL com reason "no_cue_received"
        7. Se cue recebida → PASS

        Args:
            track_name: Nome do track a ser testado.

        Returns:
            SubtitleTrackResult com status e métricas.
        """
        start_time = time.monotonic()
        logger.info(
            "Testando subtitle track: '%s'...", track_name
        )

        # 1. Selecionar o track na UI
        try:
            selected = await self._dialog_manager.select_option(
                SUBTITLE_SECTION_TITLE, track_name
            )
        except Exception as exc:
            logger.error(
                "Erro ao selecionar track '%s': %s",
                track_name,
                exc,
            )
            duration_ms = int(
                (time.monotonic() - start_time) * 1000
            )
            return SubtitleTrackResult(
                track_name=track_name,
                status="FAIL",
                fail_reason="switch_timeout",
                cue_received=False,
                time_to_first_cue_ms=None,
                switch_validated=False,
                duration_ms=duration_ms,
            )

        if not selected:
            duration_ms = int(
                (time.monotonic() - start_time) * 1000
            )
            logger.warning(
                "Falha ao selecionar track '%s' na UI.",
                track_name,
            )
            return SubtitleTrackResult(
                track_name=track_name,
                status="FAIL",
                fail_reason="switch_timeout",
                cue_received=False,
                time_to_first_cue_ms=None,
                switch_validated=False,
                duration_ms=duration_ms,
            )

        # 2. Anotar telemetria com contexto do switch
        switch_timestamp = datetime.now(timezone.utc).isoformat()
        self._telemetry_collector.annotate_current_sample({
            "track_name": track_name,
            "track_type": "subtitle",
            "switch_timestamp": switch_timestamp,
        })

        # 3. Validar switch via Shaka API
        switch_validated = await self._validate_track_switch(
            track_name
        )

        if not switch_validated:
            duration_ms = int(
                (time.monotonic() - start_time) * 1000
            )
            logger.warning(
                "Switch do track '%s' não confirmado via API.",
                track_name,
            )
            return SubtitleTrackResult(
                track_name=track_name,
                status="FAIL",
                fail_reason="switch_timeout",
                cue_received=False,
                time_to_first_cue_ms=None,
                switch_validated=False,
                duration_ms=duration_ms,
            )

        # 4. Monitorar cue via TextTrack API
        cue_result = await self._subtitle_monitor.wait_for_active_cue(
            timeout_s=self._config.subtitle_cue_timeout_s,
            poll_interval_s=self._config.subtitle_poll_interval_s,
        )

        duration_ms = int(
            (time.monotonic() - start_time) * 1000
        )

        if not cue_result.found:
            logger.warning(
                "Nenhuma cue recebida para track '%s' "
                "dentro do timeout.",
                track_name,
            )
            return SubtitleTrackResult(
                track_name=track_name,
                status="FAIL",
                fail_reason="no_cue_received",
                cue_received=False,
                time_to_first_cue_ms=None,
                switch_validated=True,
                duration_ms=duration_ms,
            )

        # 5. Cue recebida → PASS
        logger.info(
            "Track '%s' PASS — cue recebida em %dms.",
            track_name,
            cue_result.time_to_first_cue_ms or 0,
        )
        return SubtitleTrackResult(
            track_name=track_name,
            status="PASS",
            fail_reason=None,
            cue_received=True,
            time_to_first_cue_ms=cue_result.time_to_first_cue_ms,
            switch_validated=True,
            duration_ms=duration_ms,
        )

    async def _validate_track_switch(
        self, track_name: str
    ) -> bool:
        """Valida switch de subtitle via Shaka API com polling.

        Faz polling de player.getTextTracks() procurando um track
        ativo cujo label contenha o nome do track selecionado.

        Args:
            track_name: Nome do track esperado como ativo.

        Returns:
            True se o switch foi confirmado, False se timeout.
        """
        timeout_s = self._config.track_switch_timeout_s
        poll_interval = 0.5
        start = time.monotonic()

        while (time.monotonic() - start) < timeout_s:
            try:
                tracks = await self._page.evaluate(
                    "() => window.player.getTextTracks()"
                )
            except Exception as exc:
                logger.warning(
                    "Erro ao consultar getTextTracks(): %s", exc
                )
                tracks = []

            if tracks is None:
                tracks = []

            # Verificar se algum track ativo corresponde ao esperado
            for track in tracks:
                if not track.get("active"):
                    continue
                # Comparar por label ou language
                label = track.get("label", "") or ""
                language = track.get("language", "") or ""
                if (
                    track_name.lower() in label.lower()
                    or track_name.lower() in language.lower()
                    or label.lower() in track_name.lower()
                    or language.lower() in track_name.lower()
                ):
                    return True

            await asyncio.sleep(poll_interval)

        return False

    async def _restore_original_track(
        self, original_track_name: str
    ) -> None:
        """Restaura o subtitle track original após os testes.

        Args:
            original_track_name: Nome do track original a restaurar.
        """
        logger.info(
            "Restaurando track original: '%s'...",
            original_track_name,
        )
        try:
            await self._dialog_manager.select_option(
                SUBTITLE_SECTION_TITLE, original_track_name
            )
        except Exception as exc:
            logger.warning(
                "Erro ao restaurar track original '%s': %s",
                original_track_name,
                exc,
            )

    async def _safe_close_dialog(self) -> None:
        """Fecha o Settings Dialog de forma segura (best effort)."""
        try:
            await self._dialog_manager.close_dialog()
        except Exception as exc:
            logger.warning(
                "Erro ao fechar Settings Dialog: %s", exc
            )

    def _mark_all_skip_dialog_unavailable(
        self,
    ) -> list[SubtitleTrackResult]:
        """Marca todos os tracks como SKIP por dialog indisponível.

        Retorna lista vazia se nenhum track é conhecido (não foi
        possível descobrir tracks antes do dialog falhar).

        Returns:
            Lista de SubtitleTrackResult com status=SKIP e
            fail_reason="dialog_unavailable". Lista vazia se
            nenhum track era conhecido.
        """
        # Não temos informação sobre tracks disponíveis se o dialog
        # não abriu — retornamos lista vazia conforme design:
        # "return list of SubtitleTrackResult for all known tracks
        # (or empty list if none known)"
        return []
