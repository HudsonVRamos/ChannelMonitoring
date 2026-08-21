"""BufferProbe — Coleta telemetria detalhada de buffer do player.

Monitora o estado de buffer do HTMLMediaElement, registra eventos
waiting/stalled e classifica o estado do buffer como OK, BUFFER_LOW
ou BUFFERING_FREQUENT.

Requirements: 8.1, 8.2, 8.3, 8.4
"""

import logging
import time
from dataclasses import dataclass

from src.player_discovery.models import BufferStatus, BufferTelemetry

logger = logging.getLogger(__name__)


@dataclass
class WaitingEvent:
    """Representa um evento waiting/stalled registrado.

    Attributes:
        timestamp_ms: Timestamp em milissegundos do evento
        duration_ms: Duração do evento em milissegundos
    """

    timestamp_ms: float
    duration_ms: float


class BufferProbe:
    """Coleta telemetria detalhada de buffer do player.

    Responsável por:
    - Coletar buffered_start, buffered_end, buffer_ahead a cada 2s
    - Registrar eventos waiting/stalled com timestamps e durações
    - Classificar status do buffer (OK, BUFFER_LOW, BUFFERING_FREQUENT)

    Attributes:
        _waiting_events: Lista de eventos waiting registrados
        _window_seconds: Janela de tempo para avaliação (60s)
        _buffer_low_threshold: Limiar de buffer_ahead para BUFFER_LOW
        _frequent_threshold: Nº de waitings para BUFFERING_FREQUENT
    """

    def __init__(
        self,
        window_seconds: float = 60.0,
        buffer_low_threshold: float = 2.0,
        frequent_threshold: int = 3,
    ) -> None:
        """Inicializa o BufferProbe.

        Args:
            window_seconds: Janela de tempo em segundos para
                avaliação de eventos waiting (padrão: 60s).
            buffer_low_threshold: Limiar de buffer_ahead em
                segundos para classificar BUFFER_LOW (padrão: 2.0s).
            frequent_threshold: Número de eventos waiting na
                janela para classificar BUFFERING_FREQUENT
                (padrão: 3).
        """
        self._waiting_events: list[WaitingEvent] = []
        self._window_seconds = window_seconds
        self._buffer_low_threshold = buffer_low_threshold
        self._frequent_threshold = frequent_threshold

    async def collect(
        self, page, capability_map=None
    ) -> BufferTelemetry:
        """Coleta estado de buffer via page.evaluate().

        Executa JavaScript no browser para obter os ranges de buffer
        do HTMLMediaElement e calcula buffer_ahead.

        Args:
            page: Playwright Page para execução de JS.
            capability_map: CapabilityMap (opcional, para futuro uso).

        Returns:
            BufferTelemetry com os dados coletados e status classificado.
        """
        try:
            data = await page.evaluate("""() => {
                const video = document.querySelector('video');
                if (!video) return null;

                const buffered = video.buffered;
                let bufferedStart = 0;
                let bufferedEnd = 0;

                if (buffered && buffered.length > 0) {
                    // Pega o range que contém o currentTime
                    for (let i = 0; i < buffered.length; i++) {
                        if (buffered.start(i) <= video.currentTime
                            && video.currentTime <= buffered.end(i)) {
                            bufferedStart = buffered.start(i);
                            bufferedEnd = buffered.end(i);
                            break;
                        }
                    }
                    // Se não encontrou, pega o último range
                    if (bufferedEnd === 0 && buffered.length > 0) {
                        const last = buffered.length - 1;
                        bufferedStart = buffered.start(last);
                        bufferedEnd = buffered.end(last);
                    }
                }

                const currentTime = video.currentTime || 0;
                const bufferAhead = Math.max(
                    0, bufferedEnd - currentTime
                );
                const playing = !video.paused && !video.ended
                    && video.readyState > 2;

                return {
                    buffered_start: bufferedStart,
                    buffered_end: bufferedEnd,
                    buffer_ahead: bufferAhead,
                    playing: playing
                };
            }""")

            if data is None:
                logger.warning(
                    "BufferProbe: elemento video não encontrado"
                )
                return BufferTelemetry()

            buffered_start = data.get("buffered_start", 0.0)
            buffered_end = data.get("buffered_end", 0.0)
            buffer_ahead = data.get("buffer_ahead", 0.0)
            playing = data.get("playing", False)

            # Calcular métricas de waiting
            metrics = self.calculate_waiting_metrics(
                self._waiting_events
            )

            # Classificar status do buffer
            status = self.classify_status(
                buffer_ahead, playing, self._waiting_events
            )

            # Calcular time_since_last_wait
            time_since_last = None
            if self._waiting_events:
                last_event = self._waiting_events[-1]
                now_ms = time.time() * 1000
                elapsed = (
                    now_ms - last_event.timestamp_ms
                    - last_event.duration_ms
                )
                time_since_last = max(0.0, elapsed / 1000.0)

            return BufferTelemetry(
                buffered_start=buffered_start,
                buffered_end=buffered_end,
                buffer_ahead=buffer_ahead,
                waiting_count=metrics["waiting_count"],
                waiting_total_ms=metrics["waiting_total_ms"],
                longest_wait_ms=metrics["longest_wait_ms"],
                time_since_last_wait=time_since_last,
                status=status,
            )

        except Exception as e:
            logger.error(f"BufferProbe.collect() falhou: {e}")
            return BufferTelemetry()

    def classify_status(
        self,
        buffer_ahead: float,
        playing: bool,
        waiting_events: list[WaitingEvent],
    ) -> BufferStatus:
        """Classifica o status do buffer.

        Regras de classificação:
        - buffer_ahead < 2s com playing=True → BUFFER_LOW
        - >3 waiting events em janela de 60s → BUFFERING_FREQUENT
        - Caso contrário → OK

        BUFFERING_FREQUENT tem precedência sobre BUFFER_LOW quando
        ambas condições se aplicam.

        Args:
            buffer_ahead: Segundos de buffer à frente do currentTime.
            playing: Se o player está em estado playing.
            waiting_events: Lista de eventos waiting registrados.

        Returns:
            BufferStatus classificado.
        """
        # Verificar BUFFERING_FREQUENT (precedência maior)
        now_ms = time.time() * 1000
        window_ms = self._window_seconds * 1000
        events_in_window = [
            e for e in waiting_events
            if (now_ms - e.timestamp_ms) <= window_ms
        ]

        if len(events_in_window) > self._frequent_threshold:
            return BufferStatus.BUFFERING_FREQUENT

        # Verificar BUFFER_LOW
        if playing and buffer_ahead < self._buffer_low_threshold:
            return BufferStatus.BUFFER_LOW

        return BufferStatus.OK

    def record_waiting_event(
        self, timestamp_ms: float, duration_ms: float
    ) -> None:
        """Registra um evento waiting/stalled.

        Args:
            timestamp_ms: Timestamp em milissegundos do evento.
            duration_ms: Duração do evento em milissegundos.
        """
        event = WaitingEvent(
            timestamp_ms=timestamp_ms,
            duration_ms=duration_ms,
        )
        self._waiting_events.append(event)
        logger.debug(
            f"BufferProbe: evento waiting registrado "
            f"(ts={timestamp_ms:.0f}, dur={duration_ms:.0f}ms)"
        )

    def calculate_waiting_metrics(
        self, events: list[WaitingEvent]
    ) -> dict:
        """Calcula métricas agregadas de eventos waiting.

        Args:
            events: Lista de eventos waiting para calcular.

        Returns:
            Dict com waiting_count, waiting_total_ms, longest_wait_ms.
        """
        if not events:
            return {
                "waiting_count": 0,
                "waiting_total_ms": 0.0,
                "longest_wait_ms": 0.0,
            }

        waiting_count = len(events)
        waiting_total_ms = sum(e.duration_ms for e in events)
        longest_wait_ms = max(e.duration_ms for e in events)

        return {
            "waiting_count": waiting_count,
            "waiting_total_ms": waiting_total_ms,
            "longest_wait_ms": longest_wait_ms,
        }

    def clear_events(self) -> None:
        """Limpa todos os eventos waiting registrados."""
        self._waiting_events.clear()

    @property
    def waiting_events(self) -> list[WaitingEvent]:
        """Retorna a lista de eventos waiting (somente leitura)."""
        return list(self._waiting_events)
