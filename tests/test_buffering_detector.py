"""Testes unitários para o BufferingDetector."""

import time
from unittest.mock import patch

import pytest

from src.buffering_detector import BufferingDetector, STAGE_ID
from src.models import (
    AudioMetrics,
    BufferingClassification,
    BufferingState,
    PlayerMetrics,
    SubtitleMetrics,
    TelemetrySample,
    VideoMetrics,
)


def _make_sample(
    current_time: float = 10.0,
    ready_state: int = 4,
    paused: bool = False,
    playing: bool = True,
    buffering: bool = False,
) -> TelemetrySample:
    """Cria uma amostra de telemetria para testes."""
    return TelemetrySample(
        timestamp="2024-01-15T10:00:00.000Z",
        channel_id="test-channel",
        video=VideoMetrics(
            current_time=current_time,
            video_width=1920,
            video_height=1080,
            ready_state=ready_state,
            paused=paused,
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
            playing=playing,
            buffering=buffering,
            drm_ok=True,
        ),
    )


class TestBufferingDetectorInit:
    """Testes de inicialização do detector."""

    def test_default_threshold(self):
        """Threshold padrão deve ser 10 segundos."""
        detector = BufferingDetector()
        assert detector._threshold_seconds == 10.0

    def test_custom_threshold(self):
        """Deve aceitar threshold customizado."""
        detector = BufferingDetector(threshold_seconds=5.0)
        assert detector._threshold_seconds == 5.0

    def test_initial_state_no_buffering(self):
        """Estado inicial deve ser NO_BUFFERING."""
        detector = BufferingDetector()
        assert not detector._buffering_active
        assert detector._classification == (
            BufferingClassification.NO_BUFFERING
        )


class TestBufferingDetectorUpdate:
    """Testes do método update."""

    def test_no_buffering_when_playing(self):
        """Player reproduzindo normalmente retorna NO_BUFFERING."""
        detector = BufferingDetector()
        sample = _make_sample(playing=True, buffering=False)

        result = detector.update(sample)

        assert result.classification == (
            BufferingClassification.NO_BUFFERING
        )
        assert result.duration_seconds == 0.0
        assert result.start_time is None

    def test_buffering_detected_when_player_buffering(self):
        """Detecta buffering quando player.buffering=True."""
        detector = BufferingDetector()
        sample = _make_sample(
            playing=False, buffering=True, ready_state=2
        )

        result = detector.update(sample)

        assert result.classification == (
            BufferingClassification.BUFFERING_NORMAL
        )
        assert result.start_time is not None

    def test_buffering_detected_when_ready_state_low(self):
        """Detecta buffering quando readyState < 3 e não pausado."""
        detector = BufferingDetector()
        sample = _make_sample(
            playing=False, buffering=False,
            ready_state=2, paused=False,
        )

        result = detector.update(sample)

        assert result.classification == (
            BufferingClassification.BUFFERING_NORMAL
        )
        assert result.start_time is not None

    def test_no_buffering_when_paused_low_ready_state(self):
        """Não detecta buffering se pausado mesmo com readyState < 3."""
        detector = BufferingDetector()
        sample = _make_sample(
            playing=False, buffering=False,
            ready_state=2, paused=True,
        )

        result = detector.update(sample)

        assert result.classification == (
            BufferingClassification.NO_BUFFERING
        )

    def test_buffering_normal_when_resolved_within_threshold(self):
        """Buffering resolvido dentro do threshold = BUFFERING_NORMAL."""
        detector = BufferingDetector(threshold_seconds=10.0)

        # Inicia buffering
        sample_buffering = _make_sample(
            current_time=10.0, playing=False,
            buffering=True, ready_state=2,
        )
        detector.update(sample_buffering)

        # Player volta a reproduzir com currentTime avançando
        sample_playing = _make_sample(
            current_time=11.0, playing=True,
            buffering=False, ready_state=4,
        )
        result = detector.update(sample_playing)

        assert result.classification == (
            BufferingClassification.BUFFERING_NORMAL
        )

    def test_buffering_persistent_when_exceeds_threshold(self):
        """Buffering que excede threshold sem currentTime = PERSISTENT."""
        detector = BufferingDetector(threshold_seconds=0.1)

        # Inicia buffering
        sample1 = _make_sample(
            current_time=10.0, playing=False,
            buffering=True, ready_state=2,
        )
        detector.update(sample1)

        # Aguarda para exceder threshold
        time.sleep(0.15)

        # Continuamos em buffering com currentTime estagnado
        sample2 = _make_sample(
            current_time=10.0, playing=False,
            buffering=True, ready_state=2,
        )
        result = detector.update(sample2)

        assert result.classification == (
            BufferingClassification.BUFFERING_PERSISTENT
        )

    def test_is_persistent_after_threshold(self):
        """is_persistent retorna True após exceder threshold."""
        detector = BufferingDetector(threshold_seconds=0.1)

        # Inicia buffering
        sample = _make_sample(
            current_time=10.0, playing=False,
            buffering=True, ready_state=2,
        )
        detector.update(sample)

        # Aguarda para exceder threshold
        time.sleep(0.15)

        assert detector.is_persistent() is True

    def test_is_persistent_false_when_not_buffering(self):
        """is_persistent retorna False quando não há buffering."""
        detector = BufferingDetector()
        assert detector.is_persistent() is False


class TestBufferingDetectorReset:
    """Testes do método reset."""

    def test_reset_clears_state(self):
        """Reset deve limpar todo o estado interno."""
        detector = BufferingDetector(threshold_seconds=10.0)

        # Inicia buffering
        sample = _make_sample(
            current_time=10.0, playing=False,
            buffering=True, ready_state=2,
        )
        detector.update(sample)

        # Reset
        detector.reset()

        assert not detector._buffering_active
        assert detector._start_time is None
        assert detector._duration_seconds == 0.0
        assert detector._last_current_time is None
        assert detector._classification == (
            BufferingClassification.NO_BUFFERING
        )

    def test_reset_allows_new_detection(self):
        """Após reset, nova detecção funciona normalmente."""
        detector = BufferingDetector()

        # Primeiro ciclo
        sample_buf = _make_sample(
            current_time=10.0, playing=False,
            buffering=True, ready_state=2,
        )
        detector.update(sample_buf)
        detector.reset()

        # Segundo ciclo
        result = detector.update(sample_buf)
        assert result.classification == (
            BufferingClassification.BUFFERING_NORMAL
        )
        assert result.start_time is not None


class TestBufferingDetectorUnexpectedState:
    """Testes de estados inesperados."""

    def test_unexpected_state_logs_warning(self, capsys):
        """Estado inesperado deve gerar log WARNING."""
        detector = BufferingDetector()

        # Estado inesperado: readyState alto, não playing,
        # não buffering, não pausado
        sample = _make_sample(
            ready_state=4, playing=False,
            buffering=False, paused=False,
        )

        result = detector.update(sample)

        # Deve retornar estado atual sem interromper
        assert result.classification == (
            BufferingClassification.NO_BUFFERING
        )

        # Verifica que log foi emitido
        captured = capsys.readouterr()
        assert "WARNING" in captured.out
        assert "inesperado" in captured.out

    def test_unexpected_state_during_buffering_preserves_state(
        self, capsys
    ):
        """Estado inesperado durante buffering mantém detecção."""
        detector = BufferingDetector()

        # Inicia buffering
        sample_buf = _make_sample(
            current_time=10.0, playing=False,
            buffering=True, ready_state=2,
        )
        detector.update(sample_buf)

        # Estado inesperado durante monitoramento
        sample_unexpected = _make_sample(
            ready_state=4, playing=False,
            buffering=False, paused=False,
        )
        result = detector.update(sample_unexpected)

        # Deve manter o estado de buffering anterior
        assert result.classification == (
            BufferingClassification.BUFFERING_NORMAL
        )
        assert result.start_time is not None
