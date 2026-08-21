"""SubtitleProbe — Coleta telemetria e testa legendas via TextTrack API.

Responsável por:
- Coletar informações de tracks de legenda (language, label, kind, mode)
- Monitorar activeCues em tracks ativas
- Executar teste funcional de seleção de legenda
- Classificar SUBTITLE_UNAVAILABLE quando nenhuma track encontrada

Requirements: 7.1, 7.2, 7.3, 7.4, 7.5
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from src.player_discovery.models.enums import FunctionalTestStatus
from src.player_discovery.models.results import FunctionalTestResult
from src.player_discovery.models.telemetry import SubtitleTelemetry

if TYPE_CHECKING:
    from src.player_discovery.models.capability_map import CapabilityMap

logger = logging.getLogger(__name__)

# JavaScript para coletar informações de tracks via TextTrack API
JS_COLLECT_SUBTITLE_TELEMETRY = """
() => {
    const video = document.querySelector('video');
    if (!video || !video.textTracks) {
        return null;
    }

    const tracks = [];
    let activeTrack = null;
    let hasActiveCues = false;

    for (let i = 0; i < video.textTracks.length; i++) {
        const track = video.textTracks[i];
        const trackInfo = {
            language: track.language || '',
            label: track.label || '',
            kind: track.kind || '',
            mode: track.mode || 'disabled'
        };
        tracks.push(trackInfo);

        if (track.mode === 'showing') {
            activeTrack = track.label || track.language || `track_${i}`;
            if (track.activeCues && track.activeCues.length > 0) {
                hasActiveCues = true;
            }
        }
    }

    return {
        tracks_available: tracks.length,
        tracks: tracks,
        active_track: activeTrack,
        has_active_cues: hasActiveCues
    };
}
"""

# JavaScript para ativar uma track de legenda por índice
JS_SELECT_SUBTITLE_TRACK = """
(trackIndex) => {
    const video = document.querySelector('video');
    if (!video || !video.textTracks) {
        return { success: false, error: 'video ou textTracks não encontrado' };
    }

    if (trackIndex < 0 || trackIndex >= video.textTracks.length) {
        return { success: false, error: 'índice de track inválido' };
    }

    // Desativar todas as tracks
    for (let i = 0; i < video.textTracks.length; i++) {
        video.textTracks[i].mode = 'disabled';
    }

    // Ativar a track selecionada
    video.textTracks[trackIndex].mode = 'showing';

    return {
        success: true,
        mode: video.textTracks[trackIndex].mode,
        label: video.textTracks[trackIndex].label,
        language: video.textTracks[trackIndex].language
    };
}
"""

# JavaScript para verificar se há cues ativas na track selecionada
JS_CHECK_ACTIVE_CUES = """
() => {
    const video = document.querySelector('video');
    if (!video || !video.textTracks) {
        return { has_cues: false, error: 'video não encontrado' };
    }

    for (let i = 0; i < video.textTracks.length; i++) {
        const track = video.textTracks[i];
        if (track.mode === 'showing') {
            return {
                has_cues: track.activeCues && track.activeCues.length > 0,
                cue_count: track.activeCues ? track.activeCues.length : 0
            };
        }
    }

    return { has_cues: false, error: 'nenhuma track ativa' };
}
"""


class SubtitleProbe:
    """Coleta telemetria e testa funcionalidade de legendas.

    Utiliza a TextTrack API para coletar informações sobre tracks
    de legenda disponíveis, monitorar cues ativas e executar
    testes funcionais de seleção de legenda.

    O probe consulta o Capability Map para determinar a estratégia
    de interação ao executar testes funcionais.
    """

    def __init__(self) -> None:
        """Inicializa o SubtitleProbe."""
        self._last_telemetry: SubtitleTelemetry | None = None

    async def collect(
        self, page, capability_map: CapabilityMap
    ) -> SubtitleTelemetry:
        """Coleta telemetria de legendas via TextTrack API.

        Coleta: tracks_available, language, label, kind, mode
        de cada track, active_track e has_active_cues.

        Classifica SUBTITLE_UNAVAILABLE se nenhuma track encontrada.

        Args:
            page: Instância de Page do Playwright.
            capability_map: Capability Map com informações do player.

        Returns:
            SubtitleTelemetry com dados coletados.
        """
        try:
            result = await page.evaluate(JS_COLLECT_SUBTITLE_TELEMETRY)
        except Exception as e:
            logger.error(
                "Erro ao coletar telemetria de legendas: %s", e
            )
            return SubtitleTelemetry(
                tracks_available=0,
                tracks=[],
                active_track=None,
                has_active_cues=False,
                status="SUBTITLE_UNAVAILABLE",
            )

        if result is None:
            logger.warning(
                "TextTrack API indisponível ou vídeo não encontrado"
            )
            return SubtitleTelemetry(
                tracks_available=0,
                tracks=[],
                active_track=None,
                has_active_cues=False,
                status="SUBTITLE_UNAVAILABLE",
            )

        tracks_available = result.get("tracks_available", 0)

        # Requirement 7.5: classificar SUBTITLE_UNAVAILABLE
        if tracks_available == 0:
            status = "SUBTITLE_UNAVAILABLE"
        else:
            status = "OK"

        telemetry = SubtitleTelemetry(
            tracks_available=tracks_available,
            tracks=result.get("tracks", []),
            active_track=result.get("active_track"),
            has_active_cues=result.get("has_active_cues", False),
            status=status,
        )

        self._last_telemetry = telemetry
        return telemetry

    async def run_functional_test(
        self, page, capability_map: CapabilityMap
    ) -> FunctionalTestResult:
        """Executa teste funcional de seleção de legenda.

        Fluxo (Requirement 7.4):
        1. Abrir controle de legenda (via Capability Map)
        2. Listar idiomas disponíveis
        3. Selecionar idioma
        4. Verificar mode=showing
        5. Aguardar cue ativa (timeout 15 segundos)
        6. Classificar como PASS ou FAIL

        Se nenhuma track disponível (Requirement 7.5), retorna SKIPPED.

        Args:
            page: Instância de Page do Playwright.
            capability_map: Capability Map com informações do player.

        Returns:
            FunctionalTestResult com resultado do teste.
        """
        start_time = time.perf_counter()

        # Verificar se há tracks disponíveis
        telemetry = await self.collect(page, capability_map)

        if telemetry.status == "SUBTITLE_UNAVAILABLE":
            duration_ms = int(
                (time.perf_counter() - start_time) * 1000
            )
            return FunctionalTestResult(
                capability="subtitle_selection",
                status=FunctionalTestStatus.SKIPPED,
                action_executed="verificar tracks disponíveis",
                expected_result="pelo menos 1 track disponível",
                actual_result="nenhuma track encontrada",
                duration_ms=duration_ms,
                error="SUBTITLE_UNAVAILABLE - sem tracks de legenda",
            )

        # Verificar se capability está disponível no mapa
        subtitle_cap = capability_map.get_capability(
            "subtitle_selection"
        )
        if subtitle_cap is None or not subtitle_cap.available:
            duration_ms = int(
                (time.perf_counter() - start_time) * 1000
            )
            return FunctionalTestResult(
                capability="subtitle_selection",
                status=FunctionalTestStatus.SKIPPED,
                action_executed="verificar capability no mapa",
                expected_result="subtitle_selection available=true",
                actual_result="capability não disponível no mapa",
                duration_ms=duration_ms,
                error="subtitle_selection não disponível",
            )

        # Selecionar uma track de legenda (primeira disponível)
        try:
            select_result = await page.evaluate(
                JS_SELECT_SUBTITLE_TRACK, 0
            )
        except Exception as e:
            duration_ms = int(
                (time.perf_counter() - start_time) * 1000
            )
            return FunctionalTestResult(
                capability="subtitle_selection",
                status=FunctionalTestStatus.FAIL,
                action_executed="selecionar track de legenda",
                expected_result="track selecionada com mode=showing",
                actual_result=f"erro ao selecionar: {e}",
                duration_ms=duration_ms,
                error=str(e),
            )

        if not select_result or not select_result.get("success"):
            error_msg = (
                select_result.get("error", "erro desconhecido")
                if select_result
                else "resultado nulo"
            )
            duration_ms = int(
                (time.perf_counter() - start_time) * 1000
            )
            return FunctionalTestResult(
                capability="subtitle_selection",
                status=FunctionalTestStatus.FAIL,
                action_executed="selecionar track de legenda",
                expected_result="track selecionada com mode=showing",
                actual_result=f"falha: {error_msg}",
                duration_ms=duration_ms,
                error=error_msg,
            )

        # Verificar mode=showing
        if select_result.get("mode") != "showing":
            duration_ms = int(
                (time.perf_counter() - start_time) * 1000
            )
            return FunctionalTestResult(
                capability="subtitle_selection",
                status=FunctionalTestStatus.FAIL,
                action_executed="verificar mode=showing",
                expected_result="mode=showing",
                actual_result=f"mode={select_result.get('mode')}",
                duration_ms=duration_ms,
                error="track não ativou corretamente",
            )

        # Aguardar cue ativa (timeout 15 segundos)
        cue_found = await self._wait_for_active_cue(
            page, timeout_seconds=15
        )

        duration_ms = int(
            (time.perf_counter() - start_time) * 1000
        )

        if cue_found:
            return FunctionalTestResult(
                capability="subtitle_selection",
                status=FunctionalTestStatus.PASS,
                action_executed=(
                    "selecionar legenda e aguardar cue ativa"
                ),
                expected_result="mode=showing e cue ativa",
                actual_result="legenda ativa com cues presentes",
                duration_ms=duration_ms,
            )
        else:
            return FunctionalTestResult(
                capability="subtitle_selection",
                status=FunctionalTestStatus.FAIL,
                action_executed=(
                    "selecionar legenda e aguardar cue ativa"
                ),
                expected_result="cue ativa dentro de 15 segundos",
                actual_result="timeout - nenhuma cue ativa detectada",
                duration_ms=duration_ms,
                error="timeout aguardando cue ativa (15s)",
            )

    async def _wait_for_active_cue(
        self, page, timeout_seconds: int = 15
    ) -> bool:
        """Aguarda uma cue ativa aparecer na track selecionada.

        Verifica a cada 500ms se há cues ativas na track
        com mode=showing.

        Args:
            page: Instância de Page do Playwright.
            timeout_seconds: Tempo máximo de espera.

        Returns:
            True se cue ativa foi detectada, False se timeout.
        """
        import asyncio

        start = time.perf_counter()
        while (time.perf_counter() - start) < timeout_seconds:
            try:
                result = await page.evaluate(JS_CHECK_ACTIVE_CUES)
                if result and result.get("has_cues"):
                    return True
            except Exception as e:
                logger.debug(
                    "Erro ao verificar cues: %s", e
                )
            await asyncio.sleep(0.5)

        return False
