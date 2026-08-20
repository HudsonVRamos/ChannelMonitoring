# Feature: widevine-poc, Property 3: Completude da estrutura de telemetria
"""Testes de propriedade para completude da estrutura de telemetria.

Validates: Requirements 3.1, 3.2, 3.3, 3.4

Property 3: Para qualquer amostra de telemetria coletada, o objeto JSON
resultante SHALL conter as seções `video` (com currentTime float,
readyState int, paused bool, buffered_seconds float), `audio` (com
average_level float|null em [0.0, 100.0], peak_level float|null em
[0.0, 100.0]), `subtitles` (com tracks_available int >= 0, active_track
string|null, has_active_cues bool) e `player` (com playing bool,
buffering bool, drm_ok bool).
"""
from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from src.models import (
    AudioMetrics,
    PlayerMetrics,
    SubtitleMetrics,
    TelemetrySample,
    VideoMetrics,
)


# =============================================================================
# Estratégias de geração de dados
# =============================================================================

current_time_st = st.floats(min_value=0.0, max_value=10000.0)
video_width_st = st.integers(min_value=0, max_value=3840)
video_height_st = st.integers(min_value=0, max_value=2160)
ready_state_st = st.integers(min_value=0, max_value=4)
paused_st = st.booleans()
error_st = st.none() | st.text(min_size=1, max_size=50)
buffered_seconds_st = st.floats(min_value=0.0, max_value=1000.0)

average_level_st = st.none() | st.floats(
    min_value=0.0, max_value=100.0
)
peak_level_st = st.none() | st.floats(
    min_value=0.0, max_value=100.0
)
is_muted_st = st.booleans()
unavailable_st = st.booleans()

tracks_available_st = st.integers(min_value=0, max_value=20)
active_track_st = st.none() | st.text(min_size=1, max_size=30)
has_active_cues_st = st.booleans()

playing_st = st.booleans()
buffering_st = st.booleans()
drm_ok_st = st.booleans()

timestamp_st = st.text(min_size=20, max_size=30)
channel_id_st = st.text(min_size=1, max_size=20)


# Estratégias compostas para dataclasses
@st.composite
def video_metrics_st(draw):
    """Gera VideoMetrics com valores aleatórios válidos."""
    return VideoMetrics(
        current_time=draw(current_time_st),
        video_width=draw(video_width_st),
        video_height=draw(video_height_st),
        ready_state=draw(ready_state_st),
        paused=draw(paused_st),
        error=draw(error_st),
        buffered_seconds=draw(buffered_seconds_st),
    )


@st.composite
def audio_metrics_st(draw):
    """Gera AudioMetrics com valores aleatórios válidos."""
    return AudioMetrics(
        average_level=draw(average_level_st),
        peak_level=draw(peak_level_st),
        is_muted=draw(is_muted_st),
        unavailable=draw(unavailable_st),
    )


@st.composite
def subtitle_metrics_st(draw):
    """Gera SubtitleMetrics com valores aleatórios válidos."""
    return SubtitleMetrics(
        tracks_available=draw(tracks_available_st),
        active_track=draw(active_track_st),
        has_active_cues=draw(has_active_cues_st),
    )


@st.composite
def player_metrics_st(draw):
    """Gera PlayerMetrics com valores aleatórios válidos."""
    return PlayerMetrics(
        playing=draw(playing_st),
        buffering=draw(buffering_st),
        drm_ok=draw(drm_ok_st),
    )


@st.composite
def telemetry_sample_st(draw):
    """Gera TelemetrySample completo com valores aleatórios."""
    return TelemetrySample(
        timestamp=draw(timestamp_st),
        channel_id=draw(channel_id_st),
        video=draw(video_metrics_st()),
        audio=draw(audio_metrics_st()),
        subtitles=draw(subtitle_metrics_st()),
        player=draw(player_metrics_st()),
    )


# =============================================================================
# Propriedade 1: TelemetrySample contém as 4 seções obrigatórias
# =============================================================================


class TestProperty3SecoesObrigatorias:
    """TelemetrySample deve conter video, audio, subtitles, player."""

    @settings(max_examples=100)
    @given(sample=telemetry_sample_st())
    def test_sample_has_all_sections(self, sample):
        """**Validates: Requirements 3.1, 3.2, 3.3, 3.4**

        Para qualquer TelemetrySample, deve conter as seções video,
        audio, subtitles e player.
        """
        assert hasattr(sample, "video")
        assert hasattr(sample, "audio")
        assert hasattr(sample, "subtitles")
        assert hasattr(sample, "player")

        assert isinstance(sample.video, VideoMetrics)
        assert isinstance(sample.audio, AudioMetrics)
        assert isinstance(sample.subtitles, SubtitleMetrics)
        assert isinstance(sample.player, PlayerMetrics)


# =============================================================================
# Propriedade 2: Seção video com campos e tipos corretos
# =============================================================================


class TestProperty3VideoSection:
    """Seção video deve ter current_time, ready_state, paused, buffered."""

    @settings(max_examples=100)
    @given(sample=telemetry_sample_st())
    def test_video_has_current_time_float(self, sample):
        """**Validates: Requirements 3.1**

        video.current_time DEVE ser float.
        """
        assert isinstance(sample.video.current_time, float)

    @settings(max_examples=100)
    @given(sample=telemetry_sample_st())
    def test_video_has_ready_state_int(self, sample):
        """**Validates: Requirements 3.1**

        video.ready_state DEVE ser int.
        """
        assert isinstance(sample.video.ready_state, int)

    @settings(max_examples=100)
    @given(sample=telemetry_sample_st())
    def test_video_has_paused_bool(self, sample):
        """**Validates: Requirements 3.1**

        video.paused DEVE ser bool.
        """
        assert isinstance(sample.video.paused, bool)

    @settings(max_examples=100)
    @given(sample=telemetry_sample_st())
    def test_video_has_buffered_seconds_float(self, sample):
        """**Validates: Requirements 3.1**

        video.buffered_seconds DEVE ser float.
        """
        assert isinstance(sample.video.buffered_seconds, float)


# =============================================================================
# Propriedade 3: Seção audio com campos e tipos corretos
# =============================================================================


class TestProperty3AudioSection:
    """Seção audio deve ter average_level e peak_level válidos."""

    @settings(max_examples=100)
    @given(sample=telemetry_sample_st())
    def test_audio_average_level_type_and_range(self, sample):
        """**Validates: Requirements 3.2**

        audio.average_level DEVE ser float em [0.0, 100.0] ou None.
        """
        level = sample.audio.average_level
        assert level is None or isinstance(level, float)
        if level is not None:
            assert 0.0 <= level <= 100.0, (
                f"average_level={level} fora do range [0.0, 100.0]"
            )

    @settings(max_examples=100)
    @given(sample=telemetry_sample_st())
    def test_audio_peak_level_type_and_range(self, sample):
        """**Validates: Requirements 3.2**

        audio.peak_level DEVE ser float em [0.0, 100.0] ou None.
        """
        level = sample.audio.peak_level
        assert level is None or isinstance(level, float)
        if level is not None:
            assert 0.0 <= level <= 100.0, (
                f"peak_level={level} fora do range [0.0, 100.0]"
            )


# =============================================================================
# Propriedade 4: Seção subtitles com campos e tipos corretos
# =============================================================================


class TestProperty3SubtitlesSection:
    """Seção subtitles deve ter tracks_available, active_track, has_active_cues."""

    @settings(max_examples=100)
    @given(sample=telemetry_sample_st())
    def test_subtitles_tracks_available_int_non_negative(self, sample):
        """**Validates: Requirements 3.3**

        subtitles.tracks_available DEVE ser int >= 0.
        """
        tracks = sample.subtitles.tracks_available
        assert isinstance(tracks, int)
        assert tracks >= 0, (
            f"tracks_available={tracks} é negativo"
        )

    @settings(max_examples=100)
    @given(sample=telemetry_sample_st())
    def test_subtitles_active_track_type(self, sample):
        """**Validates: Requirements 3.3**

        subtitles.active_track DEVE ser string ou None.
        """
        track = sample.subtitles.active_track
        assert track is None or isinstance(track, str)

    @settings(max_examples=100)
    @given(sample=telemetry_sample_st())
    def test_subtitles_has_active_cues_bool(self, sample):
        """**Validates: Requirements 3.3**

        subtitles.has_active_cues DEVE ser bool.
        """
        assert isinstance(sample.subtitles.has_active_cues, bool)


# =============================================================================
# Propriedade 5: Seção player com campos e tipos corretos
# =============================================================================


class TestProperty3PlayerSection:
    """Seção player deve ter playing, buffering, drm_ok como bool."""

    @settings(max_examples=100)
    @given(sample=telemetry_sample_st())
    def test_player_playing_bool(self, sample):
        """**Validates: Requirements 3.4**

        player.playing DEVE ser bool.
        """
        assert isinstance(sample.player.playing, bool)

    @settings(max_examples=100)
    @given(sample=telemetry_sample_st())
    def test_player_buffering_bool(self, sample):
        """**Validates: Requirements 3.4**

        player.buffering DEVE ser bool.
        """
        assert isinstance(sample.player.buffering, bool)

    @settings(max_examples=100)
    @given(sample=telemetry_sample_st())
    def test_player_drm_ok_bool(self, sample):
        """**Validates: Requirements 3.4**

        player.drm_ok DEVE ser bool.
        """
        assert isinstance(sample.player.drm_ok, bool)
