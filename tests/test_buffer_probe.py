"""Testes unitários para BufferProbe.

Valida a coleta de buffer, classificação de status e
registro de eventos waiting/stalled.

Requirements: 8.1, 8.2, 8.3, 8.4
"""

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.player_discovery.models import BufferStatus, BufferTelemetry
from src.player_discovery.probes.buffer_probe import (
    BufferProbe,
    WaitingEvent,
)


class TestBufferProbeClassification:
    """Testes de classificação de status do buffer."""

    def test_ok_when_buffer_adequate_and_playing(self) -> None:
        """Buffer adequado (>= 2s) com playing → OK."""
        probe = BufferProbe()
        status = probe.classify_status(
            buffer_ahead=5.0, playing=True, waiting_events=[]
        )
        assert status == BufferStatus.OK

    def test_ok_when_not_playing(self) -> None:
        """Buffer baixo mas não playing → OK (não é problema)."""
        probe = BufferProbe()
        status = probe.classify_status(
            buffer_ahead=1.0, playing=False, waiting_events=[]
        )
        assert status == BufferStatus.OK

    def test_buffer_low_when_below_threshold_and_playing(
        self,
    ) -> None:
        """Buffer abaixo de 2s com playing=True → BUFFER_LOW."""
        probe = BufferProbe()
        status = probe.classify_status(
            buffer_ahead=1.5, playing=True, waiting_events=[]
        )
        assert status == BufferStatus.BUFFER_LOW

    def test_buffer_low_at_zero(self) -> None:
        """Buffer em zero com playing → BUFFER_LOW."""
        probe = BufferProbe()
        status = probe.classify_status(
            buffer_ahead=0.0, playing=True, waiting_events=[]
        )
        assert status == BufferStatus.BUFFER_LOW

    def test_buffering_frequent_more_than_3_in_window(
        self,
    ) -> None:
        """Mais de 3 eventos waiting em 60s → BUFFERING_FREQUENT."""
        probe = BufferProbe()
        now_ms = time.time() * 1000
        # 4 eventos recentes (dentro da janela de 60s)
        events = [
            WaitingEvent(
                timestamp_ms=now_ms - 50000 + i * 10000,
                duration_ms=500.0,
            )
            for i in range(4)
        ]
        status = probe.classify_status(
            buffer_ahead=5.0, playing=True, waiting_events=events
        )
        assert status == BufferStatus.BUFFERING_FREQUENT

    def test_not_frequent_with_3_or_fewer_events(self) -> None:
        """Exatamente 3 eventos waiting → OK (threshold é >3)."""
        probe = BufferProbe()
        now_ms = time.time() * 1000
        events = [
            WaitingEvent(
                timestamp_ms=now_ms - 30000 + i * 10000,
                duration_ms=500.0,
            )
            for i in range(3)
        ]
        status = probe.classify_status(
            buffer_ahead=5.0, playing=True, waiting_events=events
        )
        assert status == BufferStatus.OK

    def test_frequent_takes_precedence_over_buffer_low(
        self,
    ) -> None:
        """BUFFERING_FREQUENT tem precedência sobre BUFFER_LOW."""
        probe = BufferProbe()
        now_ms = time.time() * 1000
        events = [
            WaitingEvent(
                timestamp_ms=now_ms - 40000 + i * 8000,
                duration_ms=1000.0,
            )
            for i in range(5)
        ]
        status = probe.classify_status(
            buffer_ahead=1.0, playing=True, waiting_events=events
        )
        assert status == BufferStatus.BUFFERING_FREQUENT

    def test_old_events_outside_window_not_counted(self) -> None:
        """Eventos fora da janela de 60s não contam."""
        probe = BufferProbe()
        now_ms = time.time() * 1000
        # Eventos antigos (fora da janela de 60s)
        events = [
            WaitingEvent(
                timestamp_ms=now_ms - 120000 + i * 5000,
                duration_ms=500.0,
            )
            for i in range(5)
        ]
        status = probe.classify_status(
            buffer_ahead=5.0, playing=True, waiting_events=events
        )
        assert status == BufferStatus.OK


class TestBufferProbeWaitingMetrics:
    """Testes de cálculo de métricas de waiting events."""

    def test_empty_events_returns_zeros(self) -> None:
        """Sem eventos → todas métricas zeradas."""
        probe = BufferProbe()
        metrics = probe.calculate_waiting_metrics([])
        assert metrics["waiting_count"] == 0
        assert metrics["waiting_total_ms"] == 0.0
        assert metrics["longest_wait_ms"] == 0.0

    def test_single_event_metrics(self) -> None:
        """Um evento → count=1, total=duration, longest=duration."""
        probe = BufferProbe()
        events = [WaitingEvent(timestamp_ms=1000.0, duration_ms=500.0)]
        metrics = probe.calculate_waiting_metrics(events)
        assert metrics["waiting_count"] == 1
        assert metrics["waiting_total_ms"] == 500.0
        assert metrics["longest_wait_ms"] == 500.0

    def test_multiple_events_metrics(self) -> None:
        """Múltiplos eventos → soma e máximo corretos."""
        probe = BufferProbe()
        events = [
            WaitingEvent(timestamp_ms=1000.0, duration_ms=200.0),
            WaitingEvent(timestamp_ms=2000.0, duration_ms=800.0),
            WaitingEvent(timestamp_ms=3000.0, duration_ms=300.0),
        ]
        metrics = probe.calculate_waiting_metrics(events)
        assert metrics["waiting_count"] == 3
        assert metrics["waiting_total_ms"] == 1300.0
        assert metrics["longest_wait_ms"] == 800.0

    def test_record_waiting_event_adds_to_list(self) -> None:
        """record_waiting_event adiciona evento à lista interna."""
        probe = BufferProbe()
        probe.record_waiting_event(
            timestamp_ms=5000.0, duration_ms=750.0
        )
        assert len(probe.waiting_events) == 1
        assert probe.waiting_events[0].timestamp_ms == 5000.0
        assert probe.waiting_events[0].duration_ms == 750.0

    def test_clear_events_empties_list(self) -> None:
        """clear_events remove todos os eventos."""
        probe = BufferProbe()
        probe.record_waiting_event(1000.0, 500.0)
        probe.record_waiting_event(2000.0, 600.0)
        assert len(probe.waiting_events) == 2
        probe.clear_events()
        assert len(probe.waiting_events) == 0


class TestBufferProbeCollect:
    """Testes do método collect (com mock de page)."""

    @pytest.mark.asyncio
    async def test_collect_returns_telemetry(self) -> None:
        """collect() retorna BufferTelemetry com dados do browser."""
        page = AsyncMock()
        page.evaluate = AsyncMock(return_value={
            "buffered_start": 10.0,
            "buffered_end": 25.0,
            "buffer_ahead": 15.0,
            "playing": True,
        })

        probe = BufferProbe()
        result = await probe.collect(page)

        assert isinstance(result, BufferTelemetry)
        assert result.buffered_start == 10.0
        assert result.buffered_end == 25.0
        assert result.buffer_ahead == 15.0
        assert result.status == BufferStatus.OK

    @pytest.mark.asyncio
    async def test_collect_with_low_buffer(self) -> None:
        """collect() classifica BUFFER_LOW quando buffer < 2s."""
        page = AsyncMock()
        page.evaluate = AsyncMock(return_value={
            "buffered_start": 50.0,
            "buffered_end": 51.0,
            "buffer_ahead": 1.0,
            "playing": True,
        })

        probe = BufferProbe()
        result = await probe.collect(page)

        assert result.status == BufferStatus.BUFFER_LOW

    @pytest.mark.asyncio
    async def test_collect_with_frequent_waiting(self) -> None:
        """collect() classifica BUFFERING_FREQUENT com muitos waitings."""
        page = AsyncMock()
        page.evaluate = AsyncMock(return_value={
            "buffered_start": 50.0,
            "buffered_end": 60.0,
            "buffer_ahead": 10.0,
            "playing": True,
        })

        probe = BufferProbe()
        now_ms = time.time() * 1000
        # Registrar 4 eventos recentes
        for i in range(4):
            probe.record_waiting_event(
                timestamp_ms=now_ms - 30000 + i * 5000,
                duration_ms=1000.0,
            )

        result = await probe.collect(page)

        assert result.status == BufferStatus.BUFFERING_FREQUENT
        assert result.waiting_count == 4
        assert result.waiting_total_ms == 4000.0
        assert result.longest_wait_ms == 1000.0

    @pytest.mark.asyncio
    async def test_collect_with_no_video_element(self) -> None:
        """collect() retorna telemetria vazia quando video ausente."""
        page = AsyncMock()
        page.evaluate = AsyncMock(return_value=None)

        probe = BufferProbe()
        result = await probe.collect(page)

        assert isinstance(result, BufferTelemetry)
        assert result.buffered_start == 0.0
        assert result.buffered_end == 0.0
        assert result.buffer_ahead == 0.0
        assert result.status == BufferStatus.OK

    @pytest.mark.asyncio
    async def test_collect_handles_exception(self) -> None:
        """collect() retorna telemetria vazia em caso de exceção."""
        page = AsyncMock()
        page.evaluate = AsyncMock(
            side_effect=Exception("Browser crash")
        )

        probe = BufferProbe()
        result = await probe.collect(page)

        assert isinstance(result, BufferTelemetry)
        assert result.status == BufferStatus.OK

    @pytest.mark.asyncio
    async def test_collect_includes_time_since_last_wait(
        self,
    ) -> None:
        """collect() calcula time_since_last_wait corretamente."""
        page = AsyncMock()
        page.evaluate = AsyncMock(return_value={
            "buffered_start": 10.0,
            "buffered_end": 20.0,
            "buffer_ahead": 10.0,
            "playing": True,
        })

        probe = BufferProbe()
        # Registrar evento 5 segundos atrás
        now_ms = time.time() * 1000
        probe.record_waiting_event(
            timestamp_ms=now_ms - 5000,
            duration_ms=200.0,
        )

        result = await probe.collect(page)

        assert result.time_since_last_wait is not None
        # Deve ser aproximadamente 4.8s (5s - 0.2s de duração)
        assert result.time_since_last_wait >= 4.0
        assert result.time_since_last_wait <= 6.0


class TestBufferProbeCustomConfig:
    """Testes com configuração customizada do BufferProbe."""

    def test_custom_buffer_low_threshold(self) -> None:
        """Limiar customizado para BUFFER_LOW."""
        probe = BufferProbe(buffer_low_threshold=5.0)
        status = probe.classify_status(
            buffer_ahead=3.0, playing=True, waiting_events=[]
        )
        assert status == BufferStatus.BUFFER_LOW

    def test_custom_frequent_threshold(self) -> None:
        """Threshold customizado para BUFFERING_FREQUENT."""
        probe = BufferProbe(frequent_threshold=1)
        now_ms = time.time() * 1000
        events = [
            WaitingEvent(
                timestamp_ms=now_ms - 10000,
                duration_ms=500.0,
            ),
            WaitingEvent(
                timestamp_ms=now_ms - 5000,
                duration_ms=500.0,
            ),
        ]
        status = probe.classify_status(
            buffer_ahead=5.0, playing=True, waiting_events=events
        )
        assert status == BufferStatus.BUFFERING_FREQUENT

    def test_custom_window_seconds(self) -> None:
        """Janela customizada para avaliação de eventos."""
        # Janela de 10 segundos
        probe = BufferProbe(window_seconds=10.0)
        now_ms = time.time() * 1000
        # Eventos antigos (fora da janela de 10s)
        events = [
            WaitingEvent(
                timestamp_ms=now_ms - 30000 + i * 5000,
                duration_ms=500.0,
            )
            for i in range(5)
        ]
        status = probe.classify_status(
            buffer_ahead=5.0, playing=True, waiting_events=events
        )
        # Com janela de 10s, apenas 2 dos 5 eventos devem estar
        # dentro da janela, insuficiente para BUFFERING_FREQUENT
        assert status == BufferStatus.OK
