"""VideoTelemetryCollector — coleta contínua de telemetria de vídeo.

Coleta métricas de vídeo em background via asyncio.Task usando
page.evaluate() (JavaScript puro) sem interação com DOM.
Detecta freezes, gera escalações deferidas e produz TelemetrySummary.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from src.unified_channel_monitor.config import UnifiedMonitorConfig
from src.unified_channel_monitor.models import (
    DeferredEscalation,
    FreezeEvent,
    TelemetrySample,
    TelemetrySummary,
)

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = logging.getLogger(__name__)

# JavaScript executado via page.evaluate() para coletar métricas do vídeo.
_VIDEO_METRICS_JS = """() => {
    const v = document.querySelector('video');
    if (!v) return null;
    const b = v.buffered;
    return {
        currentTime: v.currentTime,
        totalFramesDecoded: (
            v.getVideoPlaybackQuality?.()?.totalVideoFrames ?? 0
        ),
        framesDropped: (
            v.getVideoPlaybackQuality?.()?.droppedVideoFrames ?? 0
        ),
        bufferAhead: (
            b.length > 0 ? b.end(b.length - 1) - v.currentTime : 0
        ),
        readyState: v.readyState
    };
}"""


class VideoTelemetryCollector:
    """Coleta contínua de telemetria de vídeo em background.

    Utiliza asyncio.Task para coletar amostras de métricas de vídeo
    a cada intervalo configurado, detectando freezes e gerando
    escalações deferidas quando a saúde do vídeo degrada.
    """

    def __init__(self, config: UnifiedMonitorConfig | None = None) -> None:
        """Inicializa o coletor de telemetria.

        Args:
            config: Configuração unificada. Se None, usa defaults.
        """
        self._config = config or UnifiedMonitorConfig()
        self._samples: list[TelemetrySample] = []
        self._freeze_events: list[FreezeEvent] = []
        self._deferred_escalations: list[DeferredEscalation] = []
        self._task: asyncio.Task | None = None
        self._page: Page | None = None
        self._running: bool = False
        self._current_annotation: dict | None = None
        self._start_time: str = ""
        self._freeze_threshold: int = (
            self._config.freeze_consecutive_samples
        )

    @property
    def is_running(self) -> bool:
        """Indica se a coleta está em andamento."""
        return self._running

    @property
    def samples(self) -> list[TelemetrySample]:
        """Retorna a lista de amostras coletadas."""
        return self._samples

    async def start(self, page: Page, interval_s: float = 2.0) -> None:
        """Inicia coleta de telemetria em background via asyncio.Task.

        Cria uma task que coleta amostras de métricas de vídeo
        a cada interval_s segundos usando page.evaluate().

        Args:
            page: Instância do Playwright Page para avaliação JS.
            interval_s: Intervalo entre coletas em segundos.

        Raises:
            RuntimeError: Se a coleta já estiver em andamento.
        """
        if self._running:
            raise RuntimeError(
                "Coleta já está em andamento. "
                "Chame stop() antes de iniciar novamente."
            )

        self._page = page
        self._samples = []
        self._freeze_events = []
        self._deferred_escalations = []
        self._running = True
        self._start_time = (
            datetime.now(timezone.utc).isoformat()
        )

        self._task = asyncio.create_task(
            self._collection_loop(interval_s)
        )
        logger.info(
            "Coleta de telemetria iniciada (intervalo=%.1fs)",
            interval_s,
        )

    async def stop(self) -> TelemetrySummary:
        """Para a coleta e retorna o sumário de telemetria.

        Cancela a asyncio.Task de coleta e computa o TelemetrySummary
        a partir das amostras coletadas.

        Returns:
            TelemetrySummary com métricas agregadas e classificação
            de saúde.
        """
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        self._running = False
        self._task = None

        summary = self._compute_summary()
        logger.info(
            "Coleta de telemetria finalizada. "
            "Amostras=%d, Freezes=%d, Saúde=%s",
            summary.total_samples,
            len(summary.freeze_events),
            summary.health_classification,
        )
        return summary

    def annotate_current_sample(self, context: dict) -> None:
        """Anota a próxima amostra com contexto de track switch.

        O contexto será anexado à próxima amostra coletada e
        então limpo automaticamente.

        Args:
            context: Dicionário com informações do track switch
                (ex: track_name, track_type, switch_timestamp).
        """
        self._current_annotation = context
        logger.debug(
            "Anotação definida para próxima amostra: %s",
            context,
        )

    def get_deferred_escalations(self) -> list[DeferredEscalation]:
        """Retorna escalações pendentes detectadas durante a coleta.

        Escalações são geradas quando a saúde do vídeo degrada para
        SUSPECT ou pior enquanto testes de track estão em andamento.

        Returns:
            Lista de DeferredEscalation pendentes.
        """
        return list(self._deferred_escalations)

    async def _collection_loop(self, interval_s: float) -> None:
        """Loop principal de coleta de telemetria.

        Executa page.evaluate() a cada intervalo para obter métricas
        de vídeo, calcula FPS estimado e detecta freezes.

        Args:
            interval_s: Intervalo entre coletas em segundos.
        """
        while self._running:
            try:
                await self._collect_sample()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "Erro ao coletar amostra de telemetria: %s",
                    exc,
                )

            try:
                await asyncio.sleep(interval_s)
            except asyncio.CancelledError:
                raise

    async def _collect_sample(self) -> None:
        """Coleta uma única amostra de telemetria via page.evaluate()."""
        if not self._page:
            return

        metrics = await self._page.evaluate(_VIDEO_METRICS_JS)

        if metrics is None:
            logger.warning(
                "Elemento <video> não encontrado na página."
            )
            return

        timestamp = datetime.now(timezone.utc).isoformat()

        # Calcula FPS estimado a partir da diferença de frames
        estimated_fps = self._calculate_fps(metrics)

        # Detecta freeze
        is_freeze = self._detect_freeze(
            metrics["totalFramesDecoded"]
        )

        # Consome anotação pendente
        annotation = self._current_annotation
        self._current_annotation = None

        sample = TelemetrySample(
            timestamp=timestamp,
            current_time=metrics["currentTime"],
            total_frames_decoded=metrics["totalFramesDecoded"],
            frames_dropped=metrics["framesDropped"],
            estimated_fps=estimated_fps,
            buffer_ahead_s=metrics["bufferAhead"],
            ready_state=metrics["readyState"],
            is_freeze=is_freeze,
            annotation=annotation,
        )

        self._samples.append(sample)

        # Se freeze ou buffer underrun detectado com anotação,
        # marca a amostra (anotação já está no sample)
        if is_freeze or metrics["bufferAhead"] < 0.5:
            self._maybe_create_deferred_escalation(sample)

    def _calculate_fps(self, metrics: dict) -> float | None:
        """Calcula FPS estimado entre amostras consecutivas.

        Args:
            metrics: Métricas coletadas via page.evaluate().

        Returns:
            FPS estimado ou None se for a primeira amostra.
        """
        if not self._samples:
            return None

        prev = self._samples[-1]
        frame_delta = (
            metrics["totalFramesDecoded"] - prev.total_frames_decoded
        )
        time_delta = (
            metrics["currentTime"] - prev.current_time
        )

        if time_delta <= 0:
            return None

        return frame_delta / time_delta

    def _detect_freeze(self, total_frames_decoded: int) -> bool:
        """Detecta freeze por amostras consecutivas sem avanço de frames.

        Se as últimas N amostras (threshold configurável, default 3)
        tiverem o mesmo total_frames_decoded, um FreezeEvent é criado.

        Args:
            total_frames_decoded: Total de frames decodificados atual.

        Returns:
            True se esta amostra faz parte de um freeze ativo.
        """
        threshold = self._freeze_threshold

        # Precisamos de pelo menos threshold-1 amostras anteriores
        # para detectar um freeze na amostra atual
        if len(self._samples) < threshold - 1:
            return False

        # Verifica se as últimas (threshold - 1) amostras + valor atual
        # têm o mesmo total_frames_decoded
        recent_frames = [
            s.total_frames_decoded
            for s in self._samples[-(threshold - 1):]
        ]
        recent_frames.append(total_frames_decoded)

        all_same = all(f == recent_frames[0] for f in recent_frames)

        if all_same:
            # Cria FreezeEvent se este é o início de um novo freeze
            # (a amostra anterior não era freeze)
            is_new_freeze = (
                len(self._samples) < threshold
                or not self._samples[-1].is_freeze
            )

            if is_new_freeze:
                freeze_event = FreezeEvent(
                    timestamp=(
                        self._samples[-(threshold - 1)].timestamp
                    ),
                    duration_samples=threshold,
                    current_time_stalled=(
                        self._samples[-1].current_time
                    ),
                    annotation=self._current_annotation,
                )
                self._freeze_events.append(freeze_event)
                logger.warning(
                    "Freeze detectado: frames=%d estagnados "
                    "por %d amostras consecutivas",
                    total_frames_decoded,
                    threshold,
                )
            else:
                # Freeze em andamento — incrementa duração
                if self._freeze_events:
                    self._freeze_events[-1].duration_samples += 1

            return True

        return False

    def _maybe_create_deferred_escalation(
        self, sample: TelemetrySample
    ) -> None:
        """Cria escalação deferida se saúde degradou.

        Gera DeferredEscalation quando freeze ou buffer underrun
        é detectado, para processamento posterior pelo
        EscalationManager.

        Args:
            sample: Amostra que disparou a condição de escalação.
        """
        health = self._classify_health_current()

        if health in ("SUSPECT", "DEGRADED", "CRITICAL"):
            escalation = DeferredEscalation(
                trigger_timestamp=sample.timestamp,
                health_classification=health,
                telemetry_sample=sample,
                track_switch_context=sample.annotation,
            )
            self._deferred_escalations.append(escalation)
            logger.info(
                "Escalação deferida criada: saúde=%s, "
                "timestamp=%s",
                health,
                sample.timestamp,
            )

    def _classify_health_current(self) -> str:
        """Classifica a saúde atual com base nos freezes detectados.

        Returns:
            Classificação: HEALTHY | SUSPECT | DEGRADED | CRITICAL.
        """
        num_freezes = len(self._freeze_events)

        if num_freezes == 0:
            return "HEALTHY"
        elif num_freezes == 1:
            return "SUSPECT"
        elif num_freezes >= 2:
            # Verifica se é freeze contínuo (última amostra ainda frozen)
            if (
                self._samples
                and self._samples[-1].is_freeze
                and self._freeze_events
                and self._freeze_events[-1].duration_samples
                >= self._freeze_threshold * 2
            ):
                return "CRITICAL"
            return "DEGRADED"

        return "HEALTHY"

    def _compute_summary(self) -> TelemetrySummary:
        """Computa o TelemetrySummary a partir das amostras coletadas.

        Calcula average FPS, average buffer, classifica saúde
        e coleta anotações.

        Returns:
            TelemetrySummary com métricas agregadas.
        """
        total_samples = len(self._samples)

        if total_samples == 0:
            return TelemetrySummary(
                total_samples=0,
                freeze_events=[],
                average_buffer_ahead_s=0.0,
                average_fps=None,
                health_classification="HEALTHY",
                annotations=[],
                start_time=self._start_time,
                end_time=self._start_time,
                duration_s=0.0,
            )

        # Average FPS (apenas amostras com valor não-None)
        fps_values = [
            s.estimated_fps
            for s in self._samples
            if s.estimated_fps is not None
        ]
        average_fps = (
            sum(fps_values) / len(fps_values)
            if fps_values
            else None
        )

        # Average buffer
        buffer_values = [s.buffer_ahead_s for s in self._samples]
        average_buffer = (
            sum(buffer_values) / len(buffer_values)
            if buffer_values
            else 0.0
        )

        # Classificação de saúde final
        health = self._classify_health_final(average_buffer)

        # Coleta anotações
        annotations = [
            s.annotation
            for s in self._samples
            if s.annotation is not None
        ]

        # Timestamps
        start_time = self._start_time
        end_time = self._samples[-1].timestamp

        # Duração
        try:
            start_dt = datetime.fromisoformat(start_time)
            end_dt = datetime.fromisoformat(end_time)
            duration_s = (end_dt - start_dt).total_seconds()
        except (ValueError, TypeError):
            duration_s = 0.0

        return TelemetrySummary(
            total_samples=total_samples,
            freeze_events=list(self._freeze_events),
            average_buffer_ahead_s=average_buffer,
            average_fps=average_fps,
            health_classification=health,
            annotations=annotations,
            start_time=start_time,
            end_time=end_time,
            duration_s=duration_s,
        )

    def _classify_health_final(
        self, average_buffer: float
    ) -> str:
        """Classifica a saúde final do vídeo para o sumário.

        Regras:
        - HEALTHY: sem freezes e buffer adequado
        - SUSPECT: 1 freeze ou buffer baixo (< 2s)
        - DEGRADED: 2+ freezes
        - CRITICAL: freeze contínuo (última amostra ainda frozen)

        Args:
            average_buffer: Buffer médio em segundos.

        Returns:
            Classificação: HEALTHY | SUSPECT | DEGRADED | CRITICAL.
        """
        num_freezes = len(self._freeze_events)
        low_buffer = average_buffer < 2.0

        if num_freezes == 0 and not low_buffer:
            return "HEALTHY"
        elif num_freezes == 1 or (num_freezes == 0 and low_buffer):
            return "SUSPECT"
        elif num_freezes >= 2:
            # Verifica se o freeze persiste até o final
            if (
                self._samples
                and self._samples[-1].is_freeze
                and self._freeze_events
                and self._freeze_events[-1].duration_samples
                >= self._freeze_threshold * 2
            ):
                return "CRITICAL"
            return "DEGRADED"

        return "HEALTHY"
