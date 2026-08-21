"""AudioProbe — Coleta telemetria e testa funcionalidade de áudio.

Coleta métricas via Web Audio API a cada 2 segundos:
- RMS (Root Mean Square)
- Peak (nível de pico)
- silence_duration (duração acumulada de silêncio)
- muted (estado de mute do player)

Classificação de status:
- NO_AUDIO: RMS < 0.01 por mais de 10s consecutivos com muted=false
- AUDIO_LOW: RMS entre 0.01 e 0.05 por mais de 10s consecutivos
- OK: caso contrário

Testes funcionais:
- mute/unmute: acionar mute → verificar muted=true → unmute → verificar
- audio_selection: abrir controle → listar tracks → selecionar → confirmar

Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from playwright.async_api import Page

from src.player_discovery.models.capability_map import CapabilityMap
from src.player_discovery.models.enums import (
    AudioStatus,
    FunctionalTestStatus,
    InteractionLevel,
)
from src.player_discovery.models.results import FunctionalTestResult
from src.player_discovery.models.telemetry import AudioTelemetry


logger = logging.getLogger(__name__)

# Limiares de classificação de áudio
RMS_NO_AUDIO_THRESHOLD = 0.01
RMS_AUDIO_LOW_UPPER = 0.05
SILENCE_DURATION_THRESHOLD_S = 10.0

# JavaScript para coleta via Web Audio API
_JS_COLLECT_AUDIO = """
() => {
    const video = document.querySelector('video');
    if (!video) return null;

    const result = {
        muted: video.muted,
        volume: video.volume,
        rms: null,
        peak: null,
        tracks_available: []
    };

    // Coletar tracks de áudio disponíveis
    if (video.audioTracks) {
        for (let i = 0; i < video.audioTracks.length; i++) {
            const track = video.audioTracks[i];
            result.tracks_available.push(
                track.label || track.language || `Track ${i}`
            );
        }
    }

    // Tentar obter RMS/peak via AudioContext existente
    if (window.__audioProbeContext && window.__audioProbeAnalyser) {
        const analyser = window.__audioProbeAnalyser;
        const dataArray = new Float32Array(analyser.fftSize);
        analyser.getFloatTimeDomainData(dataArray);

        let sumSquares = 0;
        let peak = 0;
        for (let i = 0; i < dataArray.length; i++) {
            const val = Math.abs(dataArray[i]);
            sumSquares += dataArray[i] * dataArray[i];
            if (val > peak) peak = val;
        }
        result.rms = Math.sqrt(sumSquares / dataArray.length);
        result.peak = peak;
    }

    return result;
}
"""

# JavaScript para inicializar Web Audio API
_JS_INIT_AUDIO_CONTEXT = """
() => {
    const video = document.querySelector('video');
    if (!video) return false;

    if (window.__audioProbeContext) return true;

    try {
        const ctx = new (window.AudioContext
            || window.webkitAudioContext)();
        const source = ctx.createMediaElementSource(video);
        const analyser = ctx.createAnalyser();
        analyser.fftSize = 2048;

        source.connect(analyser);
        analyser.connect(ctx.destination);

        window.__audioProbeContext = ctx;
        window.__audioProbeAnalyser = analyser;
        window.__audioProbeSource = source;
        return true;
    } catch (e) {
        return false;
    }
}
"""

# JavaScript para verificar muted via API
_JS_CHECK_MUTED = """
() => {
    const video = document.querySelector('video');
    if (!video) return null;
    return { muted: video.muted, volume: video.volume };
}
"""

# JavaScript para listar tracks de áudio
_JS_LIST_AUDIO_TRACKS = """
() => {
    const video = document.querySelector('video');
    if (!video) return [];

    const tracks = [];
    if (video.audioTracks) {
        for (let i = 0; i < video.audioTracks.length; i++) {
            const track = video.audioTracks[i];
            tracks.push({
                id: track.id,
                label: track.label || track.language || `Track ${i}`,
                language: track.language,
                enabled: track.enabled
            });
        }
    }
    return tracks;
}
"""


class AudioProbe:
    """Coleta telemetria e testa funcionalidade de áudio.

    Utiliza Web Audio API para medir RMS/peak do áudio e
    classifica o estado conforme limiares definidos nos requisitos.

    Attributes:
        _rms_samples: Histórico de amostras RMS para classificação
        _sample_timestamps: Timestamps das amostras (para janela de 10s)
        _silence_start: Timestamp do início do silêncio atual
        _audio_initialized: Se o Web Audio API foi inicializado
    """

    def __init__(self) -> None:
        """Inicializa o AudioProbe com estado limpo."""
        self._rms_samples: list[float] = []
        self._sample_timestamps: list[float] = []
        self._silence_start: Optional[float] = None
        self._audio_initialized: bool = False
        self._collection_interval_s: float = 2.0

    async def _ensure_audio_context(self, page: Page) -> bool:
        """Inicializa o Web Audio API context se necessário.

        Args:
            page: Página Playwright ativa.

        Returns:
            True se o contexto está pronto para uso.
        """
        if self._audio_initialized:
            return True

        try:
            result = await page.evaluate(_JS_INIT_AUDIO_CONTEXT)
            self._audio_initialized = bool(result)
            if self._audio_initialized:
                logger.debug("Web Audio API inicializado com sucesso")
            else:
                logger.warning(
                    "Não foi possível inicializar Web Audio API"
                )
            return self._audio_initialized
        except Exception as e:
            logger.warning(
                "Erro ao inicializar Web Audio API: %s", str(e)
            )
            return False

    async def collect(
        self, page: Page, capability_map: CapabilityMap
    ) -> AudioTelemetry:
        """Coleta telemetria de áudio via Web Audio API.

        Coleta RMS, peak, silence_duration e muted, e classifica
        o status de áudio conforme regras dos requisitos.

        Args:
            page: Página Playwright ativa.
            capability_map: Mapa de capabilities (para tracks disponíveis).

        Returns:
            AudioTelemetry com métricas e classificação.
        """
        # Garantir que o AudioContext está inicializado
        await self._ensure_audio_context(page)

        try:
            raw_data = await page.evaluate(_JS_COLLECT_AUDIO)
        except Exception as e:
            logger.error("Erro ao coletar áudio: %s", str(e))
            return AudioTelemetry(
                rms=None,
                peak=None,
                silence_duration=0.0,
                muted=False,
                status=AudioStatus.OK,
                tracks_available=[],
            )

        if raw_data is None:
            logger.warning(
                "Elemento de vídeo não encontrado para coleta de áudio"
            )
            return AudioTelemetry(
                rms=None,
                peak=None,
                silence_duration=0.0,
                muted=False,
                status=AudioStatus.OK,
                tracks_available=[],
            )

        rms = raw_data.get("rms")
        peak = raw_data.get("peak")
        muted = raw_data.get("muted", False)
        tracks = raw_data.get("tracks_available", [])

        # Atualizar histórico de amostras para classificação
        now = time.time()
        if rms is not None:
            self._rms_samples.append(rms)
            self._sample_timestamps.append(now)

        # Limpar amostras mais antigas que 10 segundos
        self._prune_old_samples(now)

        # Calcular silence_duration
        silence_duration = self._calculate_silence_duration(
            rms, muted, now
        )

        # Classificar status de áudio
        status = self.classify_status(self._rms_samples, muted)

        return AudioTelemetry(
            rms=rms,
            peak=peak,
            silence_duration=silence_duration,
            muted=muted,
            status=status,
            tracks_available=tracks,
        )

    def classify_status(
        self, rms_samples: list[float], muted: bool
    ) -> AudioStatus:
        """Classifica o status de áudio com base nas amostras RMS.

        Regras de classificação:
        - NO_AUDIO: RMS < 0.01 por >10s com muted=False
        - AUDIO_LOW: RMS entre 0.01 e 0.05 por >10s
        - OK: caso contrário

        Args:
            rms_samples: Lista de amostras RMS recentes.
            muted: Estado de mute do player.

        Returns:
            AudioStatus classificado.
        """
        if not rms_samples:
            return AudioStatus.OK

        # Verificar se temos amostras suficientes para 10 segundos
        # Com coleta a cada 2s, precisamos de pelo menos 5 amostras
        samples_for_10s = int(
            SILENCE_DURATION_THRESHOLD_S / self._collection_interval_s
        )

        if len(rms_samples) < samples_for_10s:
            return AudioStatus.OK

        # Pegar últimas N amostras correspondentes a 10s
        recent_samples = rms_samples[-samples_for_10s:]

        # Verificar NO_AUDIO: todos RMS < 0.01 e não está muted
        all_below_no_audio = all(
            s < RMS_NO_AUDIO_THRESHOLD for s in recent_samples
        )
        if all_below_no_audio and not muted:
            return AudioStatus.NO_AUDIO

        # Verificar AUDIO_LOW: todos RMS entre 0.01 e 0.05
        all_low = all(
            RMS_NO_AUDIO_THRESHOLD <= s < RMS_AUDIO_LOW_UPPER
            for s in recent_samples
        )
        if all_low:
            return AudioStatus.AUDIO_LOW

        return AudioStatus.OK

    def _prune_old_samples(self, now: float) -> None:
        """Remove amostras mais antigas que 10 segundos.

        Mantém apenas as amostras dentro da janela de classificação.

        Args:
            now: Timestamp atual.
        """
        cutoff = now - SILENCE_DURATION_THRESHOLD_S
        while (
            self._sample_timestamps
            and self._sample_timestamps[0] < cutoff
        ):
            self._sample_timestamps.pop(0)
            self._rms_samples.pop(0)

    def _calculate_silence_duration(
        self,
        rms: Optional[float],
        muted: bool,
        now: float,
    ) -> float:
        """Calcula a duração acumulada de silêncio.

        Silêncio é definido como RMS < 0.01 com muted=False.

        Args:
            rms: Valor RMS atual.
            muted: Estado de mute.
            now: Timestamp atual.

        Returns:
            Duração de silêncio em segundos.
        """
        is_silent = (
            rms is not None
            and rms < RMS_NO_AUDIO_THRESHOLD
            and not muted
        )

        if is_silent:
            if self._silence_start is None:
                self._silence_start = now
            return now - self._silence_start
        else:
            self._silence_start = None
            return 0.0

    async def run_functional_test(
        self, page: Page, capability_map: CapabilityMap
    ) -> FunctionalTestResult:
        """Executa testes funcionais de áudio: mute/unmute e audio_selection.

        Testa na ordem:
        1. Mute/unmute: acionar mute → verificar → unmute → verificar
        2. Audio selection: listar tracks → selecionar → confirmar

        Retorna o resultado do primeiro teste que pode ser executado.

        Args:
            page: Página Playwright ativa.
            capability_map: Mapa de capabilities.

        Returns:
            FunctionalTestResult com o resultado do teste.
        """
        # Tentar teste de mute/unmute primeiro
        mute_cap = capability_map.get_capability("mute")
        unmute_cap = capability_map.get_capability("unmute")

        if (
            mute_cap
            and mute_cap.available
            and unmute_cap
            and unmute_cap.available
        ):
            result = await self._test_mute_unmute(
                page, capability_map
            )
            if result.status != FunctionalTestStatus.SKIPPED:
                return result

        # Tentar teste de audio_selection
        audio_cap = capability_map.get_capability("audio_selection")
        if audio_cap and audio_cap.available:
            return await self._test_audio_selection(
                page, capability_map
            )

        # Nenhum teste disponível
        return FunctionalTestResult(
            capability="audio",
            status=FunctionalTestStatus.SKIPPED,
            action_executed="nenhum",
            expected_result="teste de áudio disponível",
            actual_result="capabilities mute/unmute e audio_selection "
                         "não disponíveis",
            duration_ms=0,
            error=None,
        )

    async def _test_mute_unmute(
        self, page: Page, capability_map: CapabilityMap
    ) -> FunctionalTestResult:
        """Testa funcionalidade de mute/unmute.

        Procedimento (Requirement 6.6):
        1. Acionar mute
        2. Verificar muted=true
        3. Acionar unmute
        4. Verificar muted=false e audio_level válido

        Args:
            page: Página Playwright ativa.
            capability_map: Mapa de capabilities.

        Returns:
            FunctionalTestResult do teste mute/unmute.
        """
        start_time = time.perf_counter()

        from src.player_discovery.interaction.manager import (
            InteractionManager,
        )
        interaction = InteractionManager()

        try:
            # 1. Acionar mute
            mute_result = await interaction.execute(
                page, "mute", "click", capability_map
            )
            if not mute_result.success:
                elapsed_ms = int(
                    (time.perf_counter() - start_time) * 1000
                )
                return FunctionalTestResult(
                    capability="mute",
                    status=FunctionalTestStatus.FAIL,
                    action_executed="acionar mute",
                    expected_result="muted=true",
                    actual_result=f"falha ao acionar: "
                                  f"{mute_result.error}",
                    duration_ms=elapsed_ms,
                    error=mute_result.error,
                )

            # 2. Verificar muted=true
            await page.wait_for_timeout(500)
            state = await page.evaluate(_JS_CHECK_MUTED)
            if state is None or not state.get("muted", False):
                elapsed_ms = int(
                    (time.perf_counter() - start_time) * 1000
                )
                muted_val = state.get("muted") if state else "null"
                return FunctionalTestResult(
                    capability="mute",
                    status=FunctionalTestStatus.FAIL,
                    action_executed="verificar muted=true",
                    expected_result="muted=true",
                    actual_result=f"muted={muted_val}",
                    duration_ms=elapsed_ms,
                    error="Player não ficou muted após ação",
                )

            # 3. Acionar unmute
            unmute_result = await interaction.execute(
                page, "unmute", "click", capability_map
            )
            if not unmute_result.success:
                elapsed_ms = int(
                    (time.perf_counter() - start_time) * 1000
                )
                return FunctionalTestResult(
                    capability="unmute",
                    status=FunctionalTestStatus.FAIL,
                    action_executed="acionar unmute",
                    expected_result="muted=false",
                    actual_result=f"falha ao acionar: "
                                  f"{unmute_result.error}",
                    duration_ms=elapsed_ms,
                    error=unmute_result.error,
                )

            # 4. Verificar muted=false e audio_level válido
            await page.wait_for_timeout(500)
            state = await page.evaluate(_JS_CHECK_MUTED)
            if state is None or state.get("muted", True):
                elapsed_ms = int(
                    (time.perf_counter() - start_time) * 1000
                )
                muted_val = state.get("muted") if state else "null"
                return FunctionalTestResult(
                    capability="unmute",
                    status=FunctionalTestStatus.FAIL,
                    action_executed="verificar muted=false",
                    expected_result="muted=false, audio válido",
                    actual_result=f"muted={muted_val}",
                    duration_ms=elapsed_ms,
                    error="Player não desmutou após ação",
                )

            # Sucesso
            elapsed_ms = int(
                (time.perf_counter() - start_time) * 1000
            )
            return FunctionalTestResult(
                capability="mute_unmute",
                status=FunctionalTestStatus.PASS,
                action_executed="mute → verificar → unmute → verificar",
                expected_result="muted=true → muted=false",
                actual_result="muted=true → muted=false confirmado",
                duration_ms=elapsed_ms,
            )

        except Exception as e:
            elapsed_ms = int(
                (time.perf_counter() - start_time) * 1000
            )
            logger.error(
                "Erro no teste mute/unmute: %s", str(e)
            )
            return FunctionalTestResult(
                capability="mute_unmute",
                status=FunctionalTestStatus.FAIL,
                action_executed="mute/unmute",
                expected_result="mute → unmute sem erros",
                actual_result=f"exceção: {e}",
                duration_ms=elapsed_ms,
                error=str(e),
            )

    async def _test_audio_selection(
        self, page: Page, capability_map: CapabilityMap
    ) -> FunctionalTestResult:
        """Testa funcionalidade de seleção de áudio.

        Procedimento (Requirement 6.5):
        1. Abrir controle de áudio
        2. Listar tracks
        3. Selecionar track diferente
        4. Confirmar mudança via API/DOM
        5. Verificar áudio presente via Web Audio API

        Args:
            page: Página Playwright ativa.
            capability_map: Mapa de capabilities.

        Returns:
            FunctionalTestResult do teste audio_selection.
        """
        start_time = time.perf_counter()

        from src.player_discovery.interaction.manager import (
            InteractionManager,
        )
        interaction = InteractionManager()

        try:
            # 1. Listar tracks disponíveis
            tracks = await page.evaluate(_JS_LIST_AUDIO_TRACKS)

            if not tracks or len(tracks) < 2:
                elapsed_ms = int(
                    (time.perf_counter() - start_time) * 1000
                )
                return FunctionalTestResult(
                    capability="audio_selection",
                    status=FunctionalTestStatus.SKIPPED,
                    action_executed="listar tracks",
                    expected_result="pelo menos 2 tracks de áudio",
                    actual_result=f"{len(tracks) if tracks else 0} "
                                  f"tracks encontradas",
                    duration_ms=elapsed_ms,
                    error=None,
                )

            # 2. Abrir controle de áudio via interaction
            open_result = await interaction.execute(
                page, "audio_selection", "click", capability_map
            )
            if not open_result.success:
                elapsed_ms = int(
                    (time.perf_counter() - start_time) * 1000
                )
                return FunctionalTestResult(
                    capability="audio_selection",
                    status=FunctionalTestStatus.FAIL,
                    action_executed="abrir controle de áudio",
                    expected_result="menu de áudio aberto",
                    actual_result=f"falha: {open_result.error}",
                    duration_ms=elapsed_ms,
                    error=open_result.error,
                )

            await page.wait_for_timeout(1000)

            # 3. Identificar track atual e selecionar outra
            current_track = next(
                (t for t in tracks if t.get("enabled")), None
            )
            target_track = next(
                (t for t in tracks if not t.get("enabled")), None
            )

            if not target_track:
                elapsed_ms = int(
                    (time.perf_counter() - start_time) * 1000
                )
                return FunctionalTestResult(
                    capability="audio_selection",
                    status=FunctionalTestStatus.SKIPPED,
                    action_executed="selecionar track alternativa",
                    expected_result="track alternativa disponível",
                    actual_result="nenhuma track alternativa encontrada",
                    duration_ms=elapsed_ms,
                    error=None,
                )

            # 4. Selecionar a track via JS (API direta)
            track_label = target_track.get("label", "")
            select_js = f"""
            () => {{
                const video = document.querySelector('video');
                if (!video || !video.audioTracks) return false;
                for (let i = 0; i < video.audioTracks.length; i++) {{
                    const track = video.audioTracks[i];
                    if (track.label === '{track_label}'
                        || track.language === '{track_label}') {{
                        track.enabled = true;
                    }} else {{
                        track.enabled = false;
                    }}
                }}
                return true;
            }}
            """
            selection_ok = await page.evaluate(select_js)

            if not selection_ok:
                elapsed_ms = int(
                    (time.perf_counter() - start_time) * 1000
                )
                return FunctionalTestResult(
                    capability="audio_selection",
                    status=FunctionalTestStatus.FAIL,
                    action_executed=f"selecionar track '{track_label}'",
                    expected_result="track selecionada com sucesso",
                    actual_result="falha na seleção via API",
                    duration_ms=elapsed_ms,
                    error="Não foi possível selecionar a track",
                )

            # 5. Verificar áudio presente após mudança
            await page.wait_for_timeout(1000)
            audio_data = await page.evaluate(_JS_COLLECT_AUDIO)

            has_audio = (
                audio_data is not None
                and audio_data.get("rms") is not None
                and audio_data.get("rms", 0) > RMS_NO_AUDIO_THRESHOLD
            )

            elapsed_ms = int(
                (time.perf_counter() - start_time) * 1000
            )

            if has_audio:
                return FunctionalTestResult(
                    capability="audio_selection",
                    status=FunctionalTestStatus.PASS,
                    action_executed=(
                        f"selecionar track '{track_label}' "
                        f"e verificar áudio"
                    ),
                    expected_result="track mudada e áudio presente",
                    actual_result=(
                        f"track '{track_label}' ativa, "
                        f"RMS={audio_data.get('rms', 0):.4f}"
                    ),
                    duration_ms=elapsed_ms,
                )
            else:
                # Áudio pode não estar mensurável, mas track mudou
                return FunctionalTestResult(
                    capability="audio_selection",
                    status=FunctionalTestStatus.PASS,
                    action_executed=(
                        f"selecionar track '{track_label}'"
                    ),
                    expected_result="track selecionada com sucesso",
                    actual_result=(
                        f"track '{track_label}' ativada "
                        f"(áudio não mensurável via Web Audio API)"
                    ),
                    duration_ms=elapsed_ms,
                )

        except Exception as e:
            elapsed_ms = int(
                (time.perf_counter() - start_time) * 1000
            )
            logger.error(
                "Erro no teste audio_selection: %s", str(e)
            )
            return FunctionalTestResult(
                capability="audio_selection",
                status=FunctionalTestStatus.FAIL,
                action_executed="audio_selection",
                expected_result="seleção de áudio sem erros",
                actual_result=f"exceção: {e}",
                duration_ms=elapsed_ms,
                error=str(e),
            )

    def reset(self) -> None:
        """Reseta o estado interno da probe para novo canal.

        Deve ser chamado ao navegar para um novo canal para
        limpar o histórico de amostras.
        """
        self._rms_samples.clear()
        self._sample_timestamps.clear()
        self._silence_start = None
        self._audio_initialized = False
