# Feature: player-discovery, Property 11: Classificação de status de buffer
"""Property-based test para classificação de status de buffer do BufferProbe.

Valida que para qualquer estado de buffer:
- Se buffer_ahead < 2 segundos com player em estado playing,
  o status deve ser BUFFER_LOW.
- Se mais de 3 eventos waiting ocorrem em janela de 60 segundos,
  o status deve ser BUFFERING_FREQUENT.
- BUFFERING_FREQUENT tem precedência sobre BUFFER_LOW.
- Caso contrário, o status deve ser OK.

**Validates: Requirements 8.3, 8.4**
"""
import time

from hypothesis import given, settings
from hypothesis import strategies as st

from src.player_discovery.models import BufferStatus
from src.player_discovery.probes.buffer_probe import BufferProbe, WaitingEvent


def _make_recent_events(count: int, window_ms: float = 60_000.0) -> list[WaitingEvent]:
    """Cria eventos waiting com timestamps dentro da janela de 60s.

    Args:
        count: Número de eventos a criar.
        window_ms: Janela em ms (padrão 60000).

    Returns:
        Lista de WaitingEvent com timestamps recentes.
    """
    now_ms = time.time() * 1000
    events = []
    # Distribui eventos uniformemente dentro da janela
    for i in range(count):
        offset = (window_ms / (count + 1)) * (i + 1)
        ts = now_ms - window_ms + offset
        events.append(WaitingEvent(timestamp_ms=ts, duration_ms=100.0))
    return events


def _make_old_events(count: int) -> list[WaitingEvent]:
    """Cria eventos waiting com timestamps fora da janela de 60s.

    Args:
        count: Número de eventos a criar.

    Returns:
        Lista de WaitingEvent com timestamps antigos (>60s atrás).
    """
    now_ms = time.time() * 1000
    events = []
    for i in range(count):
        # 120s atrás + offset
        ts = now_ms - 120_000 - (i * 1000)
        events.append(WaitingEvent(timestamp_ms=ts, duration_ms=100.0))
    return events


class TestBufferStatusClassification:
    """Testes de propriedade para classificação de status de buffer."""

    @settings(max_examples=100)
    @given(
        buffer_ahead=st.floats(
            min_value=0.0, max_value=1.999, allow_nan=False, allow_infinity=False
        ),
    )
    def test_buffer_low_when_ahead_below_threshold_and_playing(
        self,
        buffer_ahead: float,
    ) -> None:
        """BUFFER_LOW quando buffer_ahead < 2s e playing=True sem waiting frequente.

        Para qualquer buffer_ahead < 2.0 com player em estado playing
        e sem eventos waiting frequentes na janela, o status deve
        ser BUFFER_LOW.

        **Validates: Requirements 8.3**
        """
        probe = BufferProbe()
        # Sem eventos na janela ou com poucos eventos (<=3)
        no_events: list[WaitingEvent] = []

        status = probe.classify_status(buffer_ahead, True, no_events)

        assert status == BufferStatus.BUFFER_LOW, (
            f"Status deveria ser BUFFER_LOW para buffer_ahead={buffer_ahead} "
            f"com playing=True, mas obteve {status}"
        )

    @settings(max_examples=100)
    @given(
        num_events=st.integers(min_value=4, max_value=20),
    )
    def test_buffering_frequent_when_many_waiting_events(
        self,
        num_events: int,
    ) -> None:
        """BUFFERING_FREQUENT quando >3 eventos waiting em janela de 60s.

        Para qualquer quantidade de eventos waiting > 3 dentro
        da janela de 60 segundos, o status deve ser
        BUFFERING_FREQUENT independente do buffer_ahead.

        **Validates: Requirements 8.4**
        """
        probe = BufferProbe()
        events = _make_recent_events(num_events)

        # Testar com buffer adequado (>= 2s)
        status = probe.classify_status(5.0, True, events)

        assert status == BufferStatus.BUFFERING_FREQUENT, (
            f"Status deveria ser BUFFERING_FREQUENT com "
            f"{num_events} eventos na janela, mas obteve {status}"
        )

    @settings(max_examples=100)
    @given(
        buffer_ahead=st.floats(
            min_value=0.0, max_value=1.999, allow_nan=False, allow_infinity=False
        ),
        num_events=st.integers(min_value=4, max_value=20),
    )
    def test_buffering_frequent_has_precedence_over_buffer_low(
        self,
        buffer_ahead: float,
        num_events: int,
    ) -> None:
        """BUFFERING_FREQUENT tem precedência sobre BUFFER_LOW.

        Quando ambas condições são verdadeiras (buffer_ahead < 2s
        com playing=True E >3 eventos na janela), o resultado
        deve ser BUFFERING_FREQUENT.

        **Validates: Requirements 8.3, 8.4**
        """
        probe = BufferProbe()
        events = _make_recent_events(num_events)

        status = probe.classify_status(buffer_ahead, True, events)

        assert status == BufferStatus.BUFFERING_FREQUENT, (
            f"BUFFERING_FREQUENT deveria ter precedência sobre BUFFER_LOW "
            f"(buffer_ahead={buffer_ahead}, events={num_events}), "
            f"mas obteve {status}"
        )

    @settings(max_examples=100)
    @given(
        buffer_ahead=st.floats(
            min_value=2.0, max_value=60.0, allow_nan=False, allow_infinity=False
        ),
        num_events=st.integers(min_value=0, max_value=3),
    )
    def test_ok_when_buffer_adequate_and_few_waiting(
        self,
        buffer_ahead: float,
        num_events: int,
    ) -> None:
        """OK quando buffer_ahead >= 2s e sem waiting frequente.

        Para qualquer buffer_ahead >= 2.0 e no máximo 3 eventos
        waiting na janela, o status deve ser OK.

        **Validates: Requirements 8.3, 8.4**
        """
        probe = BufferProbe()
        events = _make_recent_events(num_events) if num_events > 0 else []

        status = probe.classify_status(buffer_ahead, True, events)

        assert status == BufferStatus.OK, (
            f"Status deveria ser OK para buffer_ahead={buffer_ahead} "
            f"com {num_events} eventos, mas obteve {status}"
        )

    @settings(max_examples=100)
    @given(
        buffer_ahead=st.floats(
            min_value=0.0, max_value=1.999, allow_nan=False, allow_infinity=False
        ),
    )
    def test_ok_when_not_playing_even_with_low_buffer(
        self,
        buffer_ahead: float,
    ) -> None:
        """OK quando playing=False mesmo com buffer_ahead < 2s.

        BUFFER_LOW só se aplica quando o player está em estado
        playing. Se playing=False, status deve ser OK
        (assumindo sem waiting frequente).

        **Validates: Requirements 8.3**
        """
        probe = BufferProbe()
        no_events: list[WaitingEvent] = []

        status = probe.classify_status(buffer_ahead, False, no_events)

        assert status == BufferStatus.OK, (
            f"Status deveria ser OK quando playing=False, "
            f"mas obteve {status} para buffer_ahead={buffer_ahead}"
        )

    @settings(max_examples=100)
    @given(
        num_events=st.integers(min_value=4, max_value=20),
    )
    def test_old_events_do_not_trigger_buffering_frequent(
        self,
        num_events: int,
    ) -> None:
        """Eventos antigos (>60s) não contam para BUFFERING_FREQUENT.

        Eventos waiting com timestamps fora da janela de 60 segundos
        não devem contribuir para a classificação BUFFERING_FREQUENT.

        **Validates: Requirements 8.4**
        """
        probe = BufferProbe()
        old_events = _make_old_events(num_events)

        status = probe.classify_status(5.0, True, old_events)

        assert status == BufferStatus.OK, (
            f"Eventos antigos não deveriam causar BUFFERING_FREQUENT, "
            f"mas obteve {status} com {num_events} eventos antigos"
        )
