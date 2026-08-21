# Feature: player-discovery, Property 14: Registro de eventos contém campos obrigatórios
"""Property-based test para campos obrigatórios de eventos do EventProbe.

Valida que para qualquer evento capturado do HTMLMediaElement,
o registro (PlayerEvent) deve conter:
- event_type: string não-vazia
- timestamp: formato ISO 8601 com milissegundos
- current_time: float no momento do evento

**Validates: Requirements 9.2**
"""
import asyncio
import re
from datetime import datetime, timezone

from hypothesis import given, settings
from hypothesis import strategies as st

from src.player_discovery.models import PlayerEvent
from src.player_discovery.probes.event_probe import (
    EventProbe,
    MEDIA_EVENTS,
)

# Regex para validação de ISO 8601 com milissegundos
# Aceita formatos como: 2024-01-15T10:30:45.123Z
#                       2024-01-15T10:30:45.123+00:00
ISO_8601_MS_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}"
)


def _generate_iso_timestamp(dt: datetime) -> str:
    """Gera timestamp ISO 8601 com milissegundos a partir de datetime.

    Args:
        dt: Objeto datetime com timezone.

    Returns:
        String no formato ISO 8601 com milissegundos.
    """
    return dt.isoformat(timespec="milliseconds")


# Estratégia para gerar datetimes UTC válidos
datetime_strategy = st.datetimes(
    min_value=datetime(2020, 1, 1),
    max_value=datetime(2030, 12, 31),
    timezones=st.just(timezone.utc),
)

# Estratégia para current_time: valores float não-negativos
current_time_strategy = st.floats(
    min_value=0.0,
    max_value=86400.0,  # até 24h de vídeo
    allow_nan=False,
    allow_infinity=False,
)

# Estratégia para additional_data: dicionários simples
additional_data_strategy = st.fixed_dictionaries(
    {},
    optional={
        "error_code": st.integers(min_value=1, max_value=4),
        "error_message": st.text(
            min_size=0, max_size=50
        ),
        "buffered_seconds": st.floats(
            min_value=0.0,
            max_value=300.0,
            allow_nan=False,
            allow_infinity=False,
        ),
    },
)


class TestEventProbeRequiredFields:
    """Testes de propriedade para campos obrigatórios de eventos."""

    @settings(max_examples=100, deadline=None)
    @given(
        event_type=st.sampled_from(MEDIA_EVENTS),
        dt=datetime_strategy,
        current_time=current_time_strategy,
        additional_data=additional_data_strategy,
    )
    def test_player_event_has_non_empty_event_type(
        self,
        event_type: str,
        dt: datetime,
        current_time: float,
        additional_data: dict,
    ) -> None:
        """event_type é sempre uma string não-vazia.

        Para qualquer evento do MEDIA_EVENTS processado pelo
        EventProbe._handle_event, o PlayerEvent resultante deve
        ter event_type como string não-vazia.

        **Validates: Requirements 9.2**
        """
        probe = EventProbe()
        timestamp = _generate_iso_timestamp(dt)

        # Executar _handle_event de forma síncrona via asyncio
        asyncio.get_event_loop().run_until_complete(
            probe._handle_event(
                event_type, timestamp, current_time, additional_data
            )
        )

        assert len(probe._events) == 1
        event = probe._events[0]

        assert isinstance(event.event_type, str), (
            f"event_type deveria ser str, obteve "
            f"{type(event.event_type)}"
        )
        assert len(event.event_type) > 0, (
            "event_type não pode ser string vazia"
        )

    @settings(max_examples=100, deadline=None)
    @given(
        event_type=st.sampled_from(MEDIA_EVENTS),
        dt=datetime_strategy,
        current_time=current_time_strategy,
        additional_data=additional_data_strategy,
    )
    def test_player_event_has_valid_iso8601_timestamp(
        self,
        event_type: str,
        dt: datetime,
        current_time: float,
        additional_data: dict,
    ) -> None:
        """timestamp é sempre ISO 8601 com milissegundos.

        Para qualquer evento processado pelo EventProbe, o timestamp
        resultante deve estar no formato ISO 8601 incluindo
        milissegundos (ex: 2024-01-15T10:30:45.123+00:00).

        **Validates: Requirements 9.2**
        """
        probe = EventProbe()
        timestamp = _generate_iso_timestamp(dt)

        asyncio.get_event_loop().run_until_complete(
            probe._handle_event(
                event_type, timestamp, current_time, additional_data
            )
        )

        assert len(probe._events) == 1
        event = probe._events[0]

        assert isinstance(event.timestamp, str), (
            f"timestamp deveria ser str, obteve "
            f"{type(event.timestamp)}"
        )
        assert ISO_8601_MS_PATTERN.match(event.timestamp), (
            f"timestamp '{event.timestamp}' não está no formato "
            f"ISO 8601 com milissegundos"
        )

    @settings(max_examples=100, deadline=None)
    @given(
        event_type=st.sampled_from(MEDIA_EVENTS),
        dt=datetime_strategy,
        current_time=current_time_strategy,
        additional_data=additional_data_strategy,
    )
    def test_player_event_has_float_current_time(
        self,
        event_type: str,
        dt: datetime,
        current_time: float,
        additional_data: dict,
    ) -> None:
        """current_time é sempre float.

        Para qualquer evento processado pelo EventProbe, o
        current_time resultante deve ser um float representando
        a posição de reprodução no momento do evento.

        **Validates: Requirements 9.2**
        """
        probe = EventProbe()
        timestamp = _generate_iso_timestamp(dt)

        asyncio.get_event_loop().run_until_complete(
            probe._handle_event(
                event_type, timestamp, current_time, additional_data
            )
        )

        assert len(probe._events) == 1
        event = probe._events[0]

        assert isinstance(event.current_time, float), (
            f"current_time deveria ser float, obteve "
            f"{type(event.current_time)}"
        )

    @settings(max_examples=100, deadline=None)
    @given(
        event_type=st.sampled_from(MEDIA_EVENTS),
        dt=datetime_strategy,
        current_time=current_time_strategy,
        additional_data=additional_data_strategy,
    )
    def test_player_event_all_required_fields_present(
        self,
        event_type: str,
        dt: datetime,
        current_time: float,
        additional_data: dict,
    ) -> None:
        """Todos os campos obrigatórios estão presentes simultaneamente.

        Para qualquer combinação válida de event_type, timestamp e
        current_time, o PlayerEvent criado por _handle_event deve
        conter todos os três campos com valores válidos.

        **Validates: Requirements 9.2**
        """
        probe = EventProbe()
        timestamp = _generate_iso_timestamp(dt)

        asyncio.get_event_loop().run_until_complete(
            probe._handle_event(
                event_type, timestamp, current_time, additional_data
            )
        )

        assert len(probe._events) == 1
        event = probe._events[0]

        # event_type: string não-vazia
        assert isinstance(event.event_type, str)
        assert len(event.event_type) > 0

        # timestamp: ISO 8601 com milissegundos
        assert isinstance(event.timestamp, str)
        assert ISO_8601_MS_PATTERN.match(event.timestamp)

        # current_time: float
        assert isinstance(event.current_time, float)
