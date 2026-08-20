# Feature: widevine-poc, Property 10: Classificação de buffering
"""Property-based test para classificação de buffering.

Valida que o BufferingDetector classifica corretamente o estado
de buffering com base nas transições do player:
- Buffering resolvido dentro do threshold → BUFFERING_NORMAL
- Player reproduzindo normalmente → NO_BUFFERING
- Após reset() → NO_BUFFERING
- is_persistent() retorna False quando não há buffering ativo

**Validates: Requirements 7.1, 7.2, 7.3**
"""
from typing import Optional
from unittest.mock import patch

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from src.buffering_detector import BufferingDetector
from src.models import (
    AudioMetrics,
    BufferingClassification,
    PlayerMetrics,
    SubtitleMetrics,
    TelemetrySample,
    VideoMetrics,
)


# =============================================================================
# Strategies para geração de TelemetrySamples
# =============================================================================


@st.composite
def telemetry_sample_strategy(
    draw,
    current_time: Optional[st.SearchStrategy] = None,
    ready_state: Optional[st.SearchStrategy] = None,
    playing: Optional[st.SearchStrategy] = None,
    buffering: Optional[st.SearchStrategy] = None,
    paused: Optional[st.SearchStrategy] = None,
) -> TelemetrySample:
    """Gera TelemetrySamples com parâmetros configuráveis."""
    ct = draw(
        current_time
        if current_time is not None
        else st.floats(min_value=0, max_value=10000, allow_nan=False, allow_infinity=False)
    )
    rs = draw(
        ready_state if ready_state is not None else st.integers(0, 4)
    )
    pl = draw(playing if playing is not None else st.booleans())
    buf = draw(buffering if buffering is not None else st.booleans())
    pa = draw(paused if paused is not None else st.booleans())

    return TelemetrySample(
        timestamp="2024-01-15T10:00:00.000Z",
        channel_id="test-channel",
        video=VideoMetrics(
            current_time=ct,
            video_width=1920,
            video_height=1080,
            ready_state=rs,
            paused=pa,
            error=None,
            buffered_seconds=30.0,
        ),
        audio=AudioMetrics(
            average_level=50.0,
            peak_level=75.0,
            is_muted=False,
        ),
        subtitles=SubtitleMetrics(
            tracks_available=1,
            active_track="Português",
            has_active_cues=True,
        ),
        player=PlayerMetrics(
            playing=pl,
            buffering=buf,
            drm_ok=True,
        ),
    )


def _make_buffering_sample(current_time: float = 10.0) -> TelemetrySample:
    """Cria amostra em estado de buffering."""
    return TelemetrySample(
        timestamp="2024-01-15T10:00:00.000Z",
        channel_id="test-channel",
        video=VideoMetrics(
            current_time=current_time,
            video_width=1920,
            video_height=1080,
            ready_state=2,
            paused=False,
            error=None,
            buffered_seconds=5.0,
        ),
        audio=AudioMetrics(
            average_level=50.0,
            peak_level=75.0,
            is_muted=False,
        ),
        subtitles=SubtitleMetrics(
            tracks_available=1,
            active_track="Português",
            has_active_cues=True,
        ),
        player=PlayerMetrics(
            playing=False,
            buffering=True,
            drm_ok=True,
        ),
    )


def _make_playing_sample(current_time: float = 11.0) -> TelemetrySample:
    """Cria amostra em estado de reprodução normal."""
    return TelemetrySample(
        timestamp="2024-01-15T10:00:01.000Z",
        channel_id="test-channel",
        video=VideoMetrics(
            current_time=current_time,
            video_width=1920,
            video_height=1080,
            ready_state=4,
            paused=False,
            error=None,
            buffered_seconds=30.0,
        ),
        audio=AudioMetrics(
            average_level=50.0,
            peak_level=75.0,
            is_muted=False,
        ),
        subtitles=SubtitleMetrics(
            tracks_available=1,
            active_track="Português",
            has_active_cues=True,
        ),
        player=PlayerMetrics(
            playing=True,
            buffering=False,
            drm_ok=True,
        ),
    )


# =============================================================================
# Property Tests
# =============================================================================


class TestBufferingClassificationProperty:
    """Property tests para classificação de buffering do BufferingDetector.

    **Validates: Requirements 7.1, 7.2, 7.3**
    """

    @settings(max_examples=100)
    @given(
        initial_time=st.floats(
            min_value=0.0,
            max_value=9000.0,
            allow_nan=False,
            allow_infinity=False,
        ),
        time_advance=st.floats(
            min_value=0.1,
            max_value=1000.0,
            allow_nan=False,
            allow_infinity=False,
        ),
    )
    def test_buffering_normal_when_resolved_within_threshold(
        self, initial_time: float, time_advance: float
    ) -> None:
        """Quando player retoma reprodução com currentTime avançando dentro
        do threshold, a classificação DEVE ser BUFFERING_NORMAL.

        Para qualquer sequência onde:
        1. Player entra em buffering
        2. Player volta a reproduzir com currentTime > last_current_time
        3. Duração do buffering <= threshold

        O resultado DEVE ser BUFFERING_NORMAL.

        **Validates: Requirements 7.2, 7.3**
        """
        detector = BufferingDetector(threshold_seconds=10.0)

        # Player entra em buffering
        sample_buffering = _make_buffering_sample(current_time=initial_time)
        detector.update(sample_buffering)

        # Player volta a reproduzir com currentTime avançando
        # (duration_seconds é ~0 pois não houve espera real)
        resumed_time = initial_time + time_advance
        sample_playing = _make_playing_sample(current_time=resumed_time)
        result = detector.update(sample_playing)

        assert result.classification == BufferingClassification.BUFFERING_NORMAL, (
            f"initial_time={initial_time}, time_advance={time_advance}: "
            f"esperava BUFFERING_NORMAL, obteve {result.classification}"
        )

    @settings(max_examples=100)
    @given(
        sample=telemetry_sample_strategy(
            ready_state=st.integers(3, 4),
            playing=st.just(True),
            buffering=st.just(False),
            paused=st.just(False),
        )
    )
    def test_no_buffering_when_playing_normally(
        self, sample: TelemetrySample
    ) -> None:
        """Quando player está reproduzindo normalmente (playing=True,
        buffering=False, readyState >= 3), classificação DEVE ser NO_BUFFERING.

        Para qualquer amostra onde o player está saudável, o detector
        não deve reportar nenhum buffering.

        **Validates: Requirements 7.1, 7.2**
        """
        detector = BufferingDetector()

        result = detector.update(sample)

        assert result.classification == BufferingClassification.NO_BUFFERING, (
            f"Player reproduzindo normalmente deveria ser NO_BUFFERING, "
            f"obteve {result.classification}"
        )
        assert result.duration_seconds == 0.0

    @settings(max_examples=100)
    @given(
        initial_time=st.floats(
            min_value=0.0,
            max_value=9000.0,
            allow_nan=False,
            allow_infinity=False,
        ),
        buffering_flag=st.booleans(),
        ready_state=st.integers(0, 4),
    )
    def test_reset_always_returns_to_no_buffering(
        self, initial_time: float, buffering_flag: bool, ready_state: int
    ) -> None:
        """Após reset(), o estado DEVE ser NO_BUFFERING independente
        do estado anterior.

        Para qualquer sequência de estados seguida por reset(),
        o detector deve voltar ao estado limpo.

        **Validates: Requirements 7.1**
        """
        detector = BufferingDetector()

        # Coloca detector em algum estado (pode ser buffering ou não)
        sample = TelemetrySample(
            timestamp="2024-01-15T10:00:00.000Z",
            channel_id="test-channel",
            video=VideoMetrics(
                current_time=initial_time,
                video_width=1920,
                video_height=1080,
                ready_state=ready_state,
                paused=False,
                error=None,
                buffered_seconds=10.0,
            ),
            audio=AudioMetrics(
                average_level=50.0,
                peak_level=75.0,
                is_muted=False,
            ),
            subtitles=SubtitleMetrics(
                tracks_available=1,
                active_track="Português",
                has_active_cues=True,
            ),
            player=PlayerMetrics(
                playing=not buffering_flag,
                buffering=buffering_flag,
                drm_ok=True,
            ),
        )
        detector.update(sample)

        # Reset
        detector.reset()

        # Após reset, estado deve ser limpo
        assert detector._classification == BufferingClassification.NO_BUFFERING
        assert detector._buffering_active is False
        assert detector._duration_seconds == 0.0
        assert detector._start_time is None
        assert detector._last_current_time is None

    @settings(max_examples=100)
    @given(
        threshold=st.floats(
            min_value=0.1,
            max_value=3600.0,
            allow_nan=False,
            allow_infinity=False,
        )
    )
    def test_is_persistent_false_when_not_buffering(
        self, threshold: float
    ) -> None:
        """Para qualquer threshold > 0, is_persistent() DEVE retornar False
        quando não há buffering ativo.

        Independente do valor do threshold configurado, se o detector
        não está monitorando buffering ativo, is_persistent() nunca
        deve retornar True.

        **Validates: Requirements 7.2**
        """
        detector = BufferingDetector(threshold_seconds=threshold)

        # Sem nenhuma atualização, não deve ser persistente
        assert detector.is_persistent() is False

        # Após uma amostra saudável, não deve ser persistente
        sample_healthy = _make_playing_sample(current_time=100.0)
        detector.update(sample_healthy)
        assert detector.is_persistent() is False

    @settings(max_examples=100)
    @given(
        initial_time=st.floats(
            min_value=0.0,
            max_value=5000.0,
            allow_nan=False,
            allow_infinity=False,
        ),
        threshold=st.floats(
            min_value=1.0,
            max_value=60.0,
            allow_nan=False,
            allow_infinity=False,
        ),
    )
    def test_buffering_starts_as_normal_classification(
        self, initial_time: float, threshold: float
    ) -> None:
        """Quando buffering é detectado pela primeira vez, a classificação
        inicial DEVE ser BUFFERING_NORMAL (ainda não excedeu threshold).

        Para qualquer current_time e threshold, o primeiro registro de
        buffering deve ser classificado como normal.

        **Validates: Requirements 7.1, 7.3**
        """
        detector = BufferingDetector(threshold_seconds=threshold)

        sample_buffering = _make_buffering_sample(current_time=initial_time)
        result = detector.update(sample_buffering)

        assert result.classification == BufferingClassification.BUFFERING_NORMAL, (
            f"Primeiro buffering deveria ser NORMAL, obteve {result.classification}"
        )
        assert result.start_time is not None

    @settings(max_examples=100)
    @given(
        initial_time=st.floats(
            min_value=0.0,
            max_value=5000.0,
            allow_nan=False,
            allow_infinity=False,
        ),
        time_advance=st.floats(
            min_value=0.1,
            max_value=500.0,
            allow_nan=False,
            allow_infinity=False,
        ),
        threshold=st.floats(
            min_value=1.0,
            max_value=60.0,
            allow_nan=False,
            allow_infinity=False,
        ),
    )
    def test_state_resets_after_normal_buffering_resolved(
        self, initial_time: float, time_advance: float, threshold: float
    ) -> None:
        """Após buffering normal resolvido, o detector DEVE estar em
        estado limpo para próxima detecção.

        Quando o player retoma reprodução com currentTime avançando
        dentro do threshold, o estado interno deve resetar, e uma
        nova amostra saudável deve retornar NO_BUFFERING.

        **Validates: Requirements 7.3**
        """
        detector = BufferingDetector(threshold_seconds=threshold)

        # Inicia buffering
        sample_buffering = _make_buffering_sample(current_time=initial_time)
        detector.update(sample_buffering)

        # Resolve buffering
        resumed_time = initial_time + time_advance
        sample_playing = _make_playing_sample(current_time=resumed_time)
        detector.update(sample_playing)

        # Após resolução, nova amostra saudável deve ser NO_BUFFERING
        sample_healthy = _make_playing_sample(current_time=resumed_time + 1.0)
        result = detector.update(sample_healthy)

        assert result.classification == BufferingClassification.NO_BUFFERING, (
            f"Após resolução de buffering, deveria ser NO_BUFFERING, "
            f"obteve {result.classification}"
        )
