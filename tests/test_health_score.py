"""Testes unitários para HealthScoreCalculator.

Valida o cálculo de Video Health Score, Audio Health Score e
Functional Health Score com cenários específicos e edge cases.

Requirements: 13.1, 13.2, 13.3, 13.4
"""

import pytest

from src.player_discovery.models.enums import (
    AudioStatus,
    FunctionalTestStatus,
)
from src.player_discovery.models.results import FunctionalTestResult
from src.player_discovery.models.telemetry import AudioTelemetry, VideoTelemetry
from src.player_discovery.monitoring.health_score import HealthScoreCalculator


@pytest.fixture
def calculator():
    """Instância do HealthScoreCalculator para testes."""
    return HealthScoreCalculator()


# --- Testes de Video Health Score ---


class TestCalculateVideoHealth:
    """Testes para calculate_video_health."""

    def test_video_perfeito_retorna_score_alto(self, calculator):
        """Vídeo playing, sem erros, buffer cheio, FPS ideal = score alto."""
        telemetry = VideoTelemetry(
            current_time=120.0,
            duration=3600.0,
            ready_state=4,
            paused=False,
            playing=True,
            ended=False,
            seeking=False,
            playback_rate=1.0,
            network_state=2,
            buffered_seconds=15.0,
            video_width=1920,
            video_height=1080,
            error=None,
            total_frames=3000,
            dropped_frames=0,
            drop_rate=0.0,
            fps_avg=29.97,
            fps_min=29.0,
            fps_max=30.0,
        )
        score = calculator.calculate_video_health(telemetry)
        assert score == 100.0

    def test_video_com_erro_drm_score_baixo(self, calculator):
        """Vídeo com erro de DRM reduz score significativamente."""
        telemetry = VideoTelemetry(
            current_time=0.0,
            duration=3600.0,
            ready_state=4,
            paused=False,
            playing=True,
            ended=False,
            seeking=False,
            playback_rate=1.0,
            network_state=2,
            buffered_seconds=15.0,
            video_width=1920,
            video_height=1080,
            error="DRM license expired",
            total_frames=3000,
            dropped_frames=0,
            drop_rate=0.0,
            fps_avg=29.97,
        )
        score = calculator.calculate_video_health(telemetry)
        # DRM 20% = 0, Playback 20% penalizado pelo error
        assert score < 70.0

    def test_video_buffer_baixo(self, calculator):
        """Buffer muito baixo reduz score."""
        telemetry = VideoTelemetry(
            current_time=120.0,
            duration=3600.0,
            ready_state=4,
            paused=False,
            playing=True,
            ended=False,
            seeking=False,
            playback_rate=1.0,
            network_state=2,
            buffered_seconds=1.0,  # Buffer baixo
            video_width=1920,
            video_height=1080,
            error=None,
            drop_rate=0.0,
            fps_avg=29.97,
        )
        score = calculator.calculate_video_health(telemetry)
        assert score < 100.0

    def test_video_alto_drop_rate(self, calculator):
        """Drop rate alto reduz score."""
        telemetry = VideoTelemetry(
            current_time=120.0,
            duration=3600.0,
            ready_state=4,
            paused=False,
            playing=True,
            ended=False,
            seeking=False,
            playback_rate=1.0,
            network_state=2,
            buffered_seconds=15.0,
            video_width=1920,
            video_height=1080,
            error=None,
            drop_rate=0.10,  # 10% drop rate
            fps_avg=29.97,
        )
        score = calculator.calculate_video_health(telemetry)
        assert score < 100.0

    def test_video_resolucao_480p(self, calculator):
        """Resolução 480p reduz score de resolução."""
        telemetry = VideoTelemetry(
            current_time=120.0,
            duration=3600.0,
            ready_state=4,
            paused=False,
            playing=True,
            ended=False,
            seeking=False,
            playback_rate=1.0,
            network_state=2,
            buffered_seconds=15.0,
            video_width=854,
            video_height=480,
            error=None,
            drop_rate=0.0,
            fps_avg=29.97,
        )
        score = calculator.calculate_video_health(telemetry)
        # Resolução 480p = 40/100, afeta 10% do total
        assert score < 100.0
        assert score >= 90.0  # Só penaliza 10% * (100-40) = 6 pontos

    def test_video_fps_baixo(self, calculator):
        """FPS abaixo de 15 reduz score significativamente."""
        telemetry = VideoTelemetry(
            current_time=120.0,
            duration=3600.0,
            ready_state=4,
            paused=False,
            playing=True,
            ended=False,
            seeking=False,
            playback_rate=1.0,
            network_state=2,
            buffered_seconds=15.0,
            video_width=1920,
            video_height=1080,
            error=None,
            drop_rate=0.0,
            fps_avg=10.0,  # FPS muito baixo
        )
        score = calculator.calculate_video_health(telemetry)
        assert score < 100.0

    def test_video_score_bounded_0_100(self, calculator):
        """Score nunca sai do range [0, 100]."""
        # Pior caso possível
        telemetry = VideoTelemetry(
            current_time=0.0,
            duration=0.0,
            ready_state=0,
            paused=True,
            playing=False,
            ended=True,
            seeking=True,
            playback_rate=0.0,
            network_state=0,
            buffered_seconds=0.0,
            video_width=0,
            video_height=0,
            error="critical error",
            drop_rate=1.0,
            fps_avg=0.0,
        )
        score = calculator.calculate_video_health(telemetry)
        assert 0.0 <= score <= 100.0

    def test_video_sem_info_frames_e_fps(self, calculator):
        """Sem informação de frames/FPS assume OK (100)."""
        telemetry = VideoTelemetry(
            current_time=120.0,
            duration=3600.0,
            ready_state=4,
            paused=False,
            playing=True,
            ended=False,
            seeking=False,
            playback_rate=1.0,
            network_state=2,
            buffered_seconds=15.0,
            video_width=1920,
            video_height=1080,
            error=None,
            drop_rate=None,
            fps_avg=None,
        )
        score = calculator.calculate_video_health(telemetry)
        assert score == 100.0


# --- Testes de Audio Health Score ---


class TestCalculateAudioHealth:
    """Testes para calculate_audio_health."""

    def test_audio_perfeito_retorna_100(self, calculator):
        """Áudio com RMS/peak bons, sem silêncio, tracks disponíveis."""
        telemetry = AudioTelemetry(
            rms=0.3,
            peak=0.5,
            silence_duration=0.0,
            muted=False,
            status=AudioStatus.OK,
            tracks_available=["pt", "en"],
        )
        score = calculator.calculate_audio_health(telemetry)
        assert score == 100.0

    def test_audio_muted_reduz_score(self, calculator):
        """Áudio mutado reduz score de audio present."""
        telemetry = AudioTelemetry(
            rms=0.0,
            peak=0.0,
            silence_duration=0.0,
            muted=True,
            status=AudioStatus.OK,
            tracks_available=["pt"],
        )
        score = calculator.calculate_audio_health(telemetry)
        assert score < 100.0

    def test_audio_sem_rms_score_baixo(self, calculator):
        """RMS None (sem informação) reduz score."""
        telemetry = AudioTelemetry(
            rms=None,
            peak=None,
            silence_duration=0.0,
            muted=False,
            status=AudioStatus.OK,
            tracks_available=["pt"],
        )
        score = calculator.calculate_audio_health(telemetry)
        assert score < 100.0

    def test_audio_com_silencio_longo(self, calculator):
        """Silêncio longo reduz score de silence."""
        telemetry = AudioTelemetry(
            rms=0.3,
            peak=0.5,
            silence_duration=30.0,  # 30 segundos de silêncio
            muted=False,
            status=AudioStatus.OK,
            tracks_available=["pt"],
        )
        score = calculator.calculate_audio_health(telemetry)
        assert score < 100.0

    def test_audio_sem_tracks(self, calculator):
        """Sem tracks de áudio reduz score de track."""
        telemetry = AudioTelemetry(
            rms=0.3,
            peak=0.5,
            silence_duration=0.0,
            muted=False,
            status=AudioStatus.OK,
            tracks_available=[],
        )
        score = calculator.calculate_audio_health(telemetry)
        assert score < 100.0

    def test_audio_score_bounded_0_100(self, calculator):
        """Score nunca sai do range [0, 100]."""
        # Pior caso possível
        telemetry = AudioTelemetry(
            rms=None,
            peak=None,
            silence_duration=999.0,
            muted=True,
            status=AudioStatus.NO_AUDIO,
            tracks_available=[],
        )
        score = calculator.calculate_audio_health(telemetry)
        assert 0.0 <= score <= 100.0


# --- Testes de Functional Health Score ---


class TestCalculateFunctionalHealth:
    """Testes para calculate_functional_health."""

    def test_todos_pass_retorna_100(self, calculator):
        """Todos os testes PASS = score 100."""
        results = [
            FunctionalTestResult(
                capability="play_pause",
                status=FunctionalTestStatus.PASS,
                action_executed="play",
                expected_result="playing",
                actual_result="playing",
                duration_ms=100,
            ),
            FunctionalTestResult(
                capability="audio_selection",
                status=FunctionalTestStatus.PASS,
                action_executed="select audio",
                expected_result="changed",
                actual_result="changed",
                duration_ms=200,
            ),
            FunctionalTestResult(
                capability="subtitle_selection",
                status=FunctionalTestStatus.PASS,
                action_executed="select subtitle",
                expected_result="showing",
                actual_result="showing",
                duration_ms=150,
            ),
            FunctionalTestResult(
                capability="quality_selection",
                status=FunctionalTestStatus.PASS,
                action_executed="select quality",
                expected_result="changed",
                actual_result="changed",
                duration_ms=180,
            ),
        ]
        score = calculator.calculate_functional_health(results)
        assert score == 100.0

    def test_todos_fail_retorna_0(self, calculator):
        """Todos os testes FAIL = score 0."""
        results = [
            FunctionalTestResult(
                capability="play_pause",
                status=FunctionalTestStatus.FAIL,
                action_executed="play",
                expected_result="playing",
                actual_result="paused",
                duration_ms=100,
            ),
            FunctionalTestResult(
                capability="audio_selection",
                status=FunctionalTestStatus.FAIL,
                action_executed="select audio",
                expected_result="changed",
                actual_result="unchanged",
                duration_ms=200,
            ),
        ]
        score = calculator.calculate_functional_health(results)
        assert score == 0.0

    def test_metade_pass_retorna_50(self, calculator):
        """Metade PASS, metade FAIL = score 50."""
        results = [
            FunctionalTestResult(
                capability="play_pause",
                status=FunctionalTestStatus.PASS,
                action_executed="play",
                expected_result="playing",
                actual_result="playing",
                duration_ms=100,
            ),
            FunctionalTestResult(
                capability="audio_selection",
                status=FunctionalTestStatus.FAIL,
                action_executed="select audio",
                expected_result="changed",
                actual_result="unchanged",
                duration_ms=200,
            ),
        ]
        score = calculator.calculate_functional_health(results)
        assert score == 50.0

    def test_skipped_ignorado(self, calculator):
        """Testes SKIPPED não afetam o score."""
        results = [
            FunctionalTestResult(
                capability="play_pause",
                status=FunctionalTestStatus.PASS,
                action_executed="play",
                expected_result="playing",
                actual_result="playing",
                duration_ms=100,
            ),
            FunctionalTestResult(
                capability="subtitle_selection",
                status=FunctionalTestStatus.SKIPPED,
                action_executed="",
                expected_result="",
                actual_result="",
                duration_ms=0,
            ),
        ]
        score = calculator.calculate_functional_health(results)
        # Só 1 testado (PASS), score = 100
        assert score == 100.0

    def test_todos_skipped_retorna_0(self, calculator):
        """Todos SKIPPED = sem testes executados = score 0."""
        results = [
            FunctionalTestResult(
                capability="play_pause",
                status=FunctionalTestStatus.SKIPPED,
                action_executed="",
                expected_result="",
                actual_result="",
                duration_ms=0,
            ),
        ]
        score = calculator.calculate_functional_health(results)
        assert score == 0.0

    def test_lista_vazia_retorna_0(self, calculator):
        """Lista vazia = sem testes = score 0."""
        score = calculator.calculate_functional_health([])
        assert score == 0.0

    def test_functional_score_bounded_0_100(self, calculator):
        """Score nunca sai do range [0, 100]."""
        results = [
            FunctionalTestResult(
                capability=f"cap_{i}",
                status=FunctionalTestStatus.PASS,
                action_executed="test",
                expected_result="ok",
                actual_result="ok",
                duration_ms=100,
            )
            for i in range(10)
        ]
        score = calculator.calculate_functional_health(results)
        assert 0.0 <= score <= 100.0
