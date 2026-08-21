"""VideoProbe — Coleta de telemetria de vídeo do HTMLMediaElement.

Coleta métricas de reprodução via page.evaluate() a cada 2 segundos:
- Propriedades básicas: currentTime, duration, readyState, paused, playing,
  ended, seeking, playbackRate, networkState, buffered, videoWidth, videoHeight, error
- Qualidade de playback (getVideoPlaybackQuality): totalVideoFrames,
  droppedVideoFrames, drop_rate, FPS
- Detecção de freeze: currentTime não avança por 5s com paused=false

Requirements: 5.1, 5.2, 5.3, 5.4, 5.5
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from ..models.telemetry import VideoTelemetry

logger = logging.getLogger(__name__)


# JavaScript para coletar todas as métricas do HTMLMediaElement
_JS_COLLECT_VIDEO_TELEMETRY = """
() => {
    const video = document.querySelector('video');
    if (!video) {
        return null;
    }

    // Buffered seconds (último range de buffer)
    let bufferedSeconds = 0;
    if (video.buffered && video.buffered.length > 0) {
        const lastIndex = video.buffered.length - 1;
        bufferedSeconds = video.buffered.end(lastIndex) - video.currentTime;
        if (bufferedSeconds < 0) bufferedSeconds = 0;
    }

    // Error info
    let errorMsg = null;
    if (video.error) {
        errorMsg = `code=${video.error.code}: ${video.error.message || 'unknown'}`;
    }

    // Playback quality (se disponível)
    let totalFrames = null;
    let droppedFrames = null;
    if (typeof video.getVideoPlaybackQuality === 'function') {
        const quality = video.getVideoPlaybackQuality();
        totalFrames = quality.totalVideoFrames || 0;
        droppedFrames = quality.droppedVideoFrames || 0;
    }

    return {
        current_time: video.currentTime || 0,
        duration: video.duration || 0,
        ready_state: video.readyState || 0,
        paused: video.paused,
        playing: !video.paused && !video.ended && video.readyState > 2,
        ended: video.ended,
        seeking: video.seeking,
        playback_rate: video.playbackRate || 1.0,
        network_state: video.networkState || 0,
        buffered_seconds: bufferedSeconds,
        video_width: video.videoWidth || 0,
        video_height: video.videoHeight || 0,
        error: errorMsg,
        total_frames: totalFrames,
        dropped_frames: droppedFrames
    };
}
"""


class VideoProbe:
    """Coleta telemetria de vídeo do HTMLMediaElement via Playwright.

    Utiliza page.evaluate() para acessar propriedades do <video> e
    a API getVideoPlaybackQuality() quando disponível.

    Detecta freeze quando currentTime não avança por mais de 5 segundos
    consecutivos com paused=false.

    Attributes:
        _previous_frames: Frames da coleta anterior (para cálculo de FPS)
        _previous_time: Timestamp da coleta anterior
    """

    def __init__(self) -> None:
        """Inicializa o VideoProbe com estado limpo."""
        self._previous_frames: Optional[int] = None
        self._previous_time: Optional[float] = None

    async def collect(self, page: object, capability_map: object) -> VideoTelemetry:
        """Coleta telemetria de vídeo via page.evaluate().

        Executa JavaScript no contexto do browser para ler propriedades
        do HTMLMediaElement e getVideoPlaybackQuality().

        Args:
            page: Instância de Playwright Page.
            capability_map: CapabilityMap para consulta (reservado para uso futuro).

        Returns:
            VideoTelemetry com todas as métricas coletadas.

        Raises:
            RuntimeError: Se não houver elemento <video> na página.
        """
        try:
            raw = await page.evaluate(_JS_COLLECT_VIDEO_TELEMETRY)  # type: ignore[union-attr]
        except Exception as e:
            logger.error("Falha ao coletar telemetria de vídeo: %s", e)
            raise RuntimeError(f"Falha ao coletar telemetria de vídeo: {e}") from e

        if raw is None:
            logger.warning("Nenhum elemento <video> encontrado na página")
            raise RuntimeError("Nenhum elemento <video> encontrado na página")

        # Calcular drop_rate
        drop_rate = self.calculate_drop_rate(
            raw.get("total_frames"),
            raw.get("dropped_frames"),
        )

        # Calcular FPS baseado no delta de frames entre coletas
        fps_avg: Optional[float] = None
        fps_min: Optional[float] = None
        fps_max: Optional[float] = None

        current_time_now = time.monotonic()
        total_frames = raw.get("total_frames")

        if total_frames is not None and self._previous_frames is not None:
            time_delta = current_time_now - self._previous_time  # type: ignore[operator]
            if time_delta > 0:
                frame_delta = total_frames - self._previous_frames
                fps_avg = frame_delta / time_delta
                # Para uma única amostra, min e max são iguais ao avg
                fps_min = fps_avg
                fps_max = fps_avg

        # Atualizar estado para próxima coleta
        if total_frames is not None:
            self._previous_frames = total_frames
            self._previous_time = current_time_now

        return VideoTelemetry(
            current_time=raw["current_time"],
            duration=raw["duration"],
            ready_state=raw["ready_state"],
            paused=raw["paused"],
            playing=raw["playing"],
            ended=raw["ended"],
            seeking=raw["seeking"],
            playback_rate=raw["playback_rate"],
            network_state=raw["network_state"],
            buffered_seconds=raw["buffered_seconds"],
            video_width=raw["video_width"],
            video_height=raw["video_height"],
            error=raw.get("error"),
            total_frames=total_frames,
            dropped_frames=raw.get("dropped_frames"),
            drop_rate=drop_rate,
            fps_avg=fps_avg,
            fps_min=fps_min,
            fps_max=fps_max,
        )

    @staticmethod
    def detect_freeze(samples: list[VideoTelemetry]) -> bool:
        """Detecta freeze: currentTime não avança por >5s com paused=false.

        Analisa uma lista de amostras de telemetria para determinar se
        o vídeo está congelado (currentTime estagnado enquanto não pausado).

        A detecção considera a janela temporal implícita pelo número de
        amostras. Com coleta a cada 2 segundos, 3 amostras = 4 segundos,
        e requer que o currentTime não avance em amostras que cubram >5s.

        Args:
            samples: Lista de VideoTelemetry ordenada cronologicamente.
                     Deve conter pelo menos 2 amostras para detecção.

        Returns:
            True se freeze detectado (currentTime estagnado por >5s com
            paused=false), False caso contrário.
        """
        if len(samples) < 2:
            return False

        # Percorre as amostras buscando sequências onde currentTime não avança
        # e o player não está pausado
        # Com coleta a cada 2s, precisamos de pelo menos 4 amostras idênticas
        # para cobrir >5s (3 intervalos de 2s = 6s > 5s)
        COLLECTION_INTERVAL_S = 2.0
        FREEZE_THRESHOLD_S = 5.0

        # Precisamos encontrar uma sequência contígua onde:
        # 1. paused=false em todas as amostras
        # 2. currentTime não muda
        # 3. A duração total da sequência > 5s

        stall_start_index = 0
        reference_time = samples[0].current_time

        for i in range(1, len(samples)):
            sample = samples[i]

            # Se pausado, reseta a contagem
            if sample.paused:
                stall_start_index = i
                reference_time = sample.current_time
                continue

            # Se a amostra anterior estava pausada, reseta
            if samples[i - 1].paused:
                stall_start_index = i
                reference_time = sample.current_time
                continue

            # Se currentTime mudou, reseta
            if sample.current_time != reference_time:
                stall_start_index = i
                reference_time = sample.current_time
                continue

            # currentTime não mudou e não está pausado
            # Calcula tempo decorrido desde o início do stall
            elapsed = (i - stall_start_index) * COLLECTION_INTERVAL_S
            if elapsed > FREEZE_THRESHOLD_S:
                return True

        return False

    @staticmethod
    def calculate_drop_rate(
        total_frames: Optional[int],
        dropped_frames: Optional[int],
    ) -> Optional[float]:
        """Calcula a taxa de descarte de frames.

        drop_rate = droppedVideoFrames / totalVideoFrames, bounded em [0.0, 1.0].

        Args:
            total_frames: Total de frames renderizados.
            dropped_frames: Frames descartados.

        Returns:
            Taxa de descarte entre 0.0 e 1.0, ou None se dados indisponíveis.
        """
        if total_frames is None or dropped_frames is None:
            return None

        if total_frames <= 0:
            return 0.0

        rate = dropped_frames / total_frames
        # Bound no intervalo [0.0, 1.0]
        return max(0.0, min(1.0, rate))
