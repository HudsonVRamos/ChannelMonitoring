"""Property-Based Tests para VideoProbe — Classificação de freeze.

Feature: player-discovery, Property 8: Classificação de freeze por stalled currentTime

Para qualquer sequência de amostras de telemetria onde currentTime não avança
por mais de 5 segundos consecutivos com paused=false, o VideoProbe deve
classificar como possível freeze.

**Validates: Requirements 5.5**
"""

from hypothesis import given, settings, strategies as st

from src.player_discovery.models.telemetry import VideoTelemetry
from src.player_discovery.probes.video_probe import VideoProbe


# --- Helpers ---

def _make_sample(current_time: float, paused: bool = False) -> VideoTelemetry:
    """Cria uma amostra de VideoTelemetry com valores padrão razoáveis.

    Args:
        current_time: Posição de reprodução simulada.
        paused: Se o player está pausado.

    Returns:
        VideoTelemetry com os campos obrigatórios preenchidos.
    """
    return VideoTelemetry(
        current_time=current_time,
        duration=3600.0,
        ready_state=4,
        paused=paused,
        playing=not paused,
        ended=False,
        seeking=False,
        playback_rate=1.0,
        network_state=2,
        buffered_seconds=30.0,
        video_width=1920,
        video_height=1080,
    )


# --- Estratégias de geração ---

# currentTime fixo (para simular stall)
fixed_current_time = st.floats(
    min_value=0.0, max_value=7200.0,
    allow_nan=False, allow_infinity=False,
)

# Número de amostras stalled (com coleta a cada 2s, precisamos >5s estagnado)
# 4 amostras idênticas = 3 intervalos x 2s = 6s > 5s → freeze
stall_sample_count = st.integers(min_value=4, max_value=30)

# Número de amostras que NÃO configuram freeze (máx 3 amostras = 4s ≤ 5s)
no_freeze_sample_count = st.integers(min_value=2, max_value=3)

# Incremento de currentTime (sempre positivo para simular avanço)
time_increment = st.floats(
    min_value=0.1, max_value=5.0,
    allow_nan=False, allow_infinity=False,
)


class TestVideoProbeFreeze:
    """Testes de propriedade para classificação de freeze por stalled currentTime."""

    @settings(max_examples=100)
    @given(
        current_time=fixed_current_time,
        num_samples=stall_sample_count,
    )
    def test_stalled_current_time_unpaused_detects_freeze(
        self,
        current_time: float,
        num_samples: int,
    ) -> None:
        """Sequência com currentTime estagnado e paused=false por >5s → freeze.

        Para qualquer currentTime fixo e número de amostras suficientes
        (4+ amostras com coleta a cada 2s = 6s+ de estagnação), com
        paused=false em todas, detect_freeze SHALL retornar True.

        **Validates: Requirements 5.5**
        """
        samples = [_make_sample(current_time, paused=False) for _ in range(num_samples)]

        result = VideoProbe.detect_freeze(samples)

        assert result is True, (
            f"currentTime={current_time} estagnado por {num_samples} amostras "
            f"({(num_samples - 1) * 2}s) com paused=false deveria detectar freeze"
        )

    @settings(max_examples=100)
    @given(
        start_time=fixed_current_time,
        increment=time_increment,
        num_samples=st.integers(min_value=2, max_value=20),
    )
    def test_advancing_current_time_no_freeze(
        self,
        start_time: float,
        increment: float,
        num_samples: int,
    ) -> None:
        """Sequência com currentTime avançando → nunca freeze.

        Para qualquer sequência onde currentTime avança a cada amostra
        (incremento positivo), detect_freeze SHALL retornar False,
        independentemente do número de amostras.

        **Validates: Requirements 5.5**
        """
        samples = [
            _make_sample(start_time + i * increment, paused=False)
            for i in range(num_samples)
        ]

        result = VideoProbe.detect_freeze(samples)

        assert result is False, (
            f"currentTime avançando de {start_time} com incremento={increment} "
            f"por {num_samples} amostras NÃO deveria detectar freeze"
        )

    @settings(max_examples=100)
    @given(
        current_time=fixed_current_time,
        num_samples=stall_sample_count,
    )
    def test_stalled_current_time_paused_no_freeze(
        self,
        current_time: float,
        num_samples: int,
    ) -> None:
        """Sequência com currentTime estagnado mas paused=true → sem freeze.

        Para qualquer sequência onde currentTime não avança mas o player
        está pausado (paused=true), detect_freeze SHALL retornar False.
        Paused=true justifica a estagnação do currentTime.

        **Validates: Requirements 5.5**
        """
        samples = [_make_sample(current_time, paused=True) for _ in range(num_samples)]

        result = VideoProbe.detect_freeze(samples)

        assert result is False, (
            f"currentTime={current_time} estagnado por {num_samples} amostras "
            f"com paused=true NÃO deveria detectar freeze"
        )

    @settings(max_examples=100)
    @given(
        current_time=fixed_current_time,
        num_stalled=stall_sample_count,
        pause_position=st.integers(min_value=1, max_value=3),
    )
    def test_pause_in_middle_resets_stall_counter(
        self,
        current_time: float,
        num_stalled: int,
        pause_position: int,
    ) -> None:
        """Paused=true no meio da sequência reseta a contagem de stall.

        Se uma amostra com paused=true aparece no meio de amostras
        com currentTime estagnado, ela reseta a contagem. As amostras
        após o pause precisam acumular >5s novamente para detectar freeze.

        **Validates: Requirements 5.5**
        """
        # Garante que pause_position é válido no range
        pause_pos = min(pause_position, num_stalled - 1)

        # Cria sequência onde pause aparece no meio
        samples: list[VideoTelemetry] = []
        for i in range(num_stalled):
            if i == pause_pos:
                samples.append(_make_sample(current_time, paused=True))
            else:
                samples.append(_make_sample(current_time, paused=False))

        # Amostras antes do pause: max 3 (pause_pos no max = 3)
        # Amostras depois do pause: num_stalled - pause_pos - 1
        # Para detectar freeze após o pause, precisamos de 4+ amostras
        # consecutivas sem pause com currentTime estagnado
        samples_after_pause = num_stalled - pause_pos - 1

        result = VideoProbe.detect_freeze(samples)

        if samples_after_pause >= 4:
            # Amostras suficientes após o pause para detectar freeze
            assert result is True, (
                f"Após pause na posição {pause_pos}, temos {samples_after_pause} "
                f"amostras stalled, que deveria detectar freeze"
            )
        else:
            # Não há amostras suficientes após o pause
            # E antes do pause: pause_pos amostras (max 3, que é < 4)
            assert result is False, (
                f"Após pause na posição {pause_pos}, temos {samples_after_pause} "
                f"amostras stalled, insuficiente para detectar freeze"
            )

    @settings(max_examples=100)
    @given(
        current_time=fixed_current_time,
        num_samples=no_freeze_sample_count,
    )
    def test_stalled_below_threshold_no_freeze(
        self,
        current_time: float,
        num_samples: int,
    ) -> None:
        """Sequência stalled com duração ≤ 5s → sem freeze.

        Com coleta a cada 2s, 2-3 amostras idênticas correspondem a
        2-4 segundos de estagnação (≤ 5s), que NÃO deve disparar
        detecção de freeze.

        **Validates: Requirements 5.5**
        """
        samples = [_make_sample(current_time, paused=False) for _ in range(num_samples)]

        result = VideoProbe.detect_freeze(samples)

        assert result is False, (
            f"currentTime={current_time} estagnado por {num_samples} amostras "
            f"({(num_samples - 1) * 2}s ≤ 5s) NÃO deveria detectar freeze"
        )
