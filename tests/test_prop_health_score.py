# Feature: player-discovery, Property 21: Health Scores são bounded e seguem pesos definidos
"""Property-based test para Health Scores bounded e ponderados.

Valida que o HealthScoreCalculator produz scores dentro de [0, 100] para
qualquer conjunto de métricas de telemetria:
- Video Health Score em [0, 100]
- Audio Health Score em [0, 100]
- Functional Health Score em [0, 100]

**Validates: Requirements 13.1, 13.2, 13.3**
"""
from hypothesis import given, settings
from hypothesis import strategies as st

from src.player_discovery.models.enums import AudioStatus, FunctionalTestStatus
from src.player_discovery.models.results import FunctionalTestResult
from src.player_discovery.models.telemetry import AudioTelemetry, VideoTelemetry
from src.player_discovery.monitoring.health_score import HealthScoreCalculator


# --- Strategies para VideoTelemetry ---

video_telemetry_strategy = st.builds(
    VideoTelemetry,
    current_time=st.floats(min_value=0.0, max_value=36000.0),
    duration=st.floats(min_value=0.0, max_value=36000.0),
    ready_state=st.integers(min_value=0, max_value=4),
    paused=st.booleans(),
    playing=st.booleans(),
    ended=st.booleans(),
    seeking=st.booleans(),
    playback_rate=st.floats(min_value=0.0, max_value=4.0),
    network_state=st.integers(min_value=0, max_value=3),
    buffered_seconds=st.floats(min_value=0.0, max_value=300.0),
    video_width=st.integers(min_value=0, max_value=7680),
    video_height=st.integers(min_value=0, max_value=4320),
    error=st.one_of(st.none(), st.text(min_size=1, max_size=50)),
    total_frames=st.one_of(st.none(), st.integers(min_value=0, max_value=1_000_000)),
    dropped_frames=st.one_of(st.none(), st.integers(min_value=0, max_value=1_000_000)),
    drop_rate=st.one_of(st.none(), st.floats(min_value=0.0, max_value=1.0)),
    fps_avg=st.one_of(st.none(), st.floats(min_value=0.0, max_value=120.0)),
    fps_min=st.one_of(st.none(), st.floats(min_value=0.0, max_value=120.0)),
    fps_max=st.one_of(st.none(), st.floats(min_value=0.0, max_value=120.0)),
    quality_changes=st.integers(min_value=0, max_value=100),
    up_switches=st.integers(min_value=0, max_value=100),
    down_switches=st.integers(min_value=0, max_value=100),
)


# --- Strategies para AudioTelemetry ---

audio_telemetry_strategy = st.builds(
    AudioTelemetry,
    rms=st.one_of(st.none(), st.floats(min_value=0.0, max_value=1.0)),
    peak=st.one_of(st.none(), st.floats(min_value=0.0, max_value=1.0)),
    silence_duration=st.floats(min_value=0.0, max_value=300.0),
    muted=st.booleans(),
    status=st.sampled_from(AudioStatus),
    tracks_available=st.lists(st.text(min_size=1, max_size=20), min_size=0, max_size=5),
)


# --- Strategies para FunctionalTestResult ---

functional_test_result_strategy = st.builds(
    FunctionalTestResult,
    capability=st.sampled_from([
        "play_pause", "audio_selection", "subtitle_selection", "quality_selection",
    ]),
    status=st.sampled_from(FunctionalTestStatus),
    action_executed=st.text(min_size=1, max_size=30),
    expected_result=st.text(min_size=1, max_size=30),
    actual_result=st.text(min_size=1, max_size=30),
    duration_ms=st.integers(min_value=0, max_value=30000),
    error=st.one_of(st.none(), st.text(min_size=1, max_size=50)),
)


class TestHealthScoresBounded:
    """Testes de propriedade para Health Scores bounded [0, 100]."""

    @settings(max_examples=100)
    @given(telemetry=video_telemetry_strategy)
    def test_video_health_score_bounded(self, telemetry: VideoTelemetry) -> None:
        """Video Health Score está sempre em [0, 100] para qualquer telemetria.

        Para qualquer combinação de métricas de vídeo (currentTime, duration,
        readyState, paused, playing, ended, seeking, playbackRate, networkState,
        bufferedSeconds, videoWidth, videoHeight, error, dropRate, fpsAvg),
        o score resultante DEVE estar em [0, 100].

        **Validates: Requirements 13.1**
        """
        calculator = HealthScoreCalculator()
        score = calculator.calculate_video_health(telemetry)

        assert 0.0 <= score <= 100.0, (
            f"Video Health Score {score} fora do range [0, 100]. "
            f"Telemetria: playing={telemetry.playing}, paused={telemetry.paused}, "
            f"error={telemetry.error}, drop_rate={telemetry.drop_rate}, "
            f"fps_avg={telemetry.fps_avg}, buffered={telemetry.buffered_seconds}, "
            f"height={telemetry.video_height}"
        )

    @settings(max_examples=100)
    @given(telemetry=audio_telemetry_strategy)
    def test_audio_health_score_bounded(self, telemetry: AudioTelemetry) -> None:
        """Audio Health Score está sempre em [0, 100] para qualquer telemetria.

        Para qualquer combinação de métricas de áudio (rms, peak,
        silence_duration, muted, tracks_available), o score resultante
        DEVE estar em [0, 100].

        **Validates: Requirements 13.2**
        """
        calculator = HealthScoreCalculator()
        score = calculator.calculate_audio_health(telemetry)

        assert 0.0 <= score <= 100.0, (
            f"Audio Health Score {score} fora do range [0, 100]. "
            f"Telemetria: rms={telemetry.rms}, peak={telemetry.peak}, "
            f"silence={telemetry.silence_duration}, muted={telemetry.muted}, "
            f"tracks={len(telemetry.tracks_available)}"
        )

    @settings(max_examples=100)
    @given(
        results=st.lists(
            functional_test_result_strategy,
            min_size=0,
            max_size=10,
        )
    )
    def test_functional_health_score_bounded(
        self, results: list[FunctionalTestResult]
    ) -> None:
        """Functional Health Score está sempre em [0, 100] para qualquer resultado.

        Para qualquer lista de resultados de testes funcionais (PASS, FAIL,
        SKIPPED), o score resultante DEVE estar em [0, 100].

        **Validates: Requirements 13.3**
        """
        calculator = HealthScoreCalculator()
        score = calculator.calculate_functional_health(results)

        assert 0.0 <= score <= 100.0, (
            f"Functional Health Score {score} fora do range [0, 100]. "
            f"Resultados: {[(r.capability, r.status.value) for r in results]}"
        )
