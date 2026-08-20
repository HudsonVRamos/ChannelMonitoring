"""Testes unitários para o TelemetryCollector.

Usa mocks do Playwright para simular page.evaluate() e validar
que as métricas são coletadas e formatadas corretamente.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models import (
    AudioMetrics,
    PlayerMetrics,
    SubtitleMetrics,
    TelemetrySample,
    VideoMetrics,
)
from src.telemetry_collector import TelemetryCollector


@pytest.fixture
def collector():
    """Instância do TelemetryCollector com config padrão."""
    return TelemetryCollector(
        interval_seconds=2.0,
        channel_id="test-channel",
    )


@pytest.fixture
def mock_page():
    """Mock de Page do Playwright."""
    page = AsyncMock()
    return page


class TestCollectVideoMetrics:
    """Testes para coleta de métricas de vídeo."""

    async def test_coleta_metricas_video_sucesso(
        self, collector, mock_page
    ):
        """Deve coletar métricas do player com sucesso."""
        mock_page.evaluate.return_value = {
            "current_time": 45.3,
            "video_width": 1920,
            "video_height": 1080,
            "ready_state": 4,
            "paused": False,
            "error": None,
            "buffered_seconds": 12.5,
        }

        result = await collector.collect_video_metrics(mock_page)

        assert isinstance(result, VideoMetrics)
        assert result.current_time == 45.3
        assert result.video_width == 1920
        assert result.video_height == 1080
        assert result.ready_state == 4
        assert result.paused is False
        assert result.error is None
        assert result.buffered_seconds == 12.5

    async def test_coleta_metricas_video_sem_elemento(
        self, collector, mock_page
    ):
        """Deve retornar defaults quando video não encontrado."""
        mock_page.evaluate.return_value = {
            "current_time": 0.0,
            "video_width": 0,
            "video_height": 0,
            "ready_state": 0,
            "paused": True,
            "error": "Elemento video não encontrado",
            "buffered_seconds": 0.0,
        }

        result = await collector.collect_video_metrics(mock_page)

        assert result.current_time == 0.0
        assert result.paused is True
        assert result.error == "Elemento video não encontrado"

    async def test_coleta_metricas_video_erro_evaluate(
        self, collector, mock_page
    ):
        """Deve retornar defaults quando page.evaluate falha."""
        mock_page.evaluate.side_effect = Exception(
            "Page closed"
        )

        result = await collector.collect_video_metrics(mock_page)

        assert result.current_time == 0.0
        assert result.paused is True
        assert "Coleta falhou" in result.error

    async def test_coleta_metricas_video_com_erro_player(
        self, collector, mock_page
    ):
        """Deve capturar erro reportado pelo player."""
        mock_page.evaluate.return_value = {
            "current_time": 10.0,
            "video_width": 1280,
            "video_height": 720,
            "ready_state": 0,
            "paused": True,
            "error": "Code: 3, Message: MEDIA_ERR_DECODE",
            "buffered_seconds": 0.0,
        }

        result = await collector.collect_video_metrics(mock_page)

        assert result.error is not None
        assert "MEDIA_ERR_DECODE" in result.error


class TestCollectAudioMetrics:
    """Testes para coleta de métricas de áudio."""

    async def test_coleta_audio_disponivel(
        self, collector, mock_page
    ):
        """Deve coletar níveis de áudio via Web Audio API."""
        mock_page.evaluate.return_value = {
            "average_level": 35.2,
            "peak_level": 78.9,
            "is_muted": False,
            "unavailable": False,
        }

        result = await collector.collect_audio_metrics(mock_page)

        assert isinstance(result, AudioMetrics)
        assert result.average_level == 35.2
        assert result.peak_level == 78.9
        assert result.is_muted is False
        assert result.unavailable is False

    async def test_coleta_audio_indisponivel(
        self, collector, mock_page
    ):
        """Deve retornar null com indicação de indisponibilidade."""
        mock_page.evaluate.return_value = {
            "average_level": None,
            "peak_level": None,
            "is_muted": False,
            "unavailable": True,
        }

        result = await collector.collect_audio_metrics(mock_page)

        assert result.average_level is None
        assert result.peak_level is None
        assert result.unavailable is True

    async def test_coleta_audio_erro_evaluate(
        self, collector, mock_page
    ):
        """Deve retornar indisponível quando evaluate falha."""
        mock_page.evaluate.side_effect = Exception(
            "Timeout"
        )

        result = await collector.collect_audio_metrics(mock_page)

        assert result.average_level is None
        assert result.peak_level is None
        assert result.unavailable is True

    async def test_coleta_audio_muted(
        self, collector, mock_page
    ):
        """Deve detectar player mutado."""
        mock_page.evaluate.return_value = {
            "average_level": 0.0,
            "peak_level": 0.0,
            "is_muted": True,
            "unavailable": False,
        }

        result = await collector.collect_audio_metrics(mock_page)

        assert result.is_muted is True


class TestCollectSubtitleMetrics:
    """Testes para coleta de métricas de legendas."""

    async def test_coleta_legendas_com_track_ativa(
        self, collector, mock_page
    ):
        """Deve coletar dados quando há legenda ativa."""
        mock_page.evaluate.return_value = {
            "tracks_available": 3,
            "active_track": "Português",
            "has_active_cues": True,
        }

        result = await collector.collect_subtitle_metrics(mock_page)

        assert isinstance(result, SubtitleMetrics)
        assert result.tracks_available == 3
        assert result.active_track == "Português"
        assert result.has_active_cues is True

    async def test_coleta_legendas_sem_track_ativa(
        self, collector, mock_page
    ):
        """Deve retornar null quando nenhuma legenda ativa."""
        mock_page.evaluate.return_value = {
            "tracks_available": 2,
            "active_track": None,
            "has_active_cues": False,
        }

        result = await collector.collect_subtitle_metrics(mock_page)

        assert result.tracks_available == 2
        assert result.active_track is None
        assert result.has_active_cues is False

    async def test_coleta_legendas_sem_video(
        self, collector, mock_page
    ):
        """Deve retornar defaults quando video não existe."""
        mock_page.evaluate.return_value = {
            "tracks_available": 0,
            "active_track": None,
            "has_active_cues": False,
        }

        result = await collector.collect_subtitle_metrics(mock_page)

        assert result.tracks_available == 0

    async def test_coleta_legendas_erro_evaluate(
        self, collector, mock_page
    ):
        """Deve retornar defaults quando evaluate falha."""
        mock_page.evaluate.side_effect = Exception(
            "Network error"
        )

        result = await collector.collect_subtitle_metrics(mock_page)

        assert result.tracks_available == 0
        assert result.active_track is None
        assert result.has_active_cues is False


class TestCollectSample:
    """Testes para coleta de amostra completa."""

    async def test_coleta_amostra_completa(
        self, collector, mock_page
    ):
        """Deve produzir TelemetrySample com todas as seções."""
        # Configurar mock para retornar dados de cada coleta
        mock_page.evaluate.side_effect = [
            # Video metrics
            {
                "current_time": 30.0,
                "video_width": 1920,
                "video_height": 1080,
                "ready_state": 4,
                "paused": False,
                "error": None,
                "buffered_seconds": 15.0,
            },
            # Audio metrics
            {
                "average_level": 42.0,
                "peak_level": 85.0,
                "is_muted": False,
                "unavailable": False,
            },
            # Subtitle metrics
            {
                "tracks_available": 1,
                "active_track": "English",
                "has_active_cues": True,
            },
        ]

        result = await collector.collect_sample(mock_page)

        assert isinstance(result, TelemetrySample)
        assert result.channel_id == "test-channel"
        assert "T" in result.timestamp  # ISO 8601
        assert result.timestamp.endswith("Z")
        # Video
        assert result.video.current_time == 30.0
        assert result.video.ready_state == 4
        # Audio
        assert result.audio.average_level == 42.0
        assert result.audio.unavailable is False
        # Subtitles
        assert result.subtitles.tracks_available == 1
        # Player state
        assert result.player.playing is True
        assert result.player.buffering is False
        assert result.player.drm_ok is True

    async def test_coleta_amostra_player_pausado(
        self, collector, mock_page
    ):
        """Deve detectar player pausado no PlayerMetrics."""
        mock_page.evaluate.side_effect = [
            {
                "current_time": 10.0,
                "video_width": 1280,
                "video_height": 720,
                "ready_state": 4,
                "paused": True,
                "error": None,
                "buffered_seconds": 5.0,
            },
            {
                "average_level": None,
                "peak_level": None,
                "is_muted": True,
                "unavailable": True,
            },
            {
                "tracks_available": 0,
                "active_track": None,
                "has_active_cues": False,
            },
        ]

        result = await collector.collect_sample(mock_page)

        assert result.player.playing is False
        assert result.player.buffering is False

    async def test_coleta_amostra_buffering(
        self, collector, mock_page
    ):
        """Deve detectar buffering no PlayerMetrics."""
        mock_page.evaluate.side_effect = [
            {
                "current_time": 5.0,
                "video_width": 1280,
                "video_height": 720,
                "ready_state": 2,  # HAVE_CURRENT_DATA
                "paused": False,
                "error": None,
                "buffered_seconds": 0.5,
            },
            {
                "average_level": None,
                "peak_level": None,
                "is_muted": False,
                "unavailable": True,
            },
            {
                "tracks_available": 0,
                "active_track": None,
                "has_active_cues": False,
            },
        ]

        result = await collector.collect_sample(mock_page)

        assert result.player.playing is False
        assert result.player.buffering is True

    async def test_timestamp_formato_iso8601(
        self, collector, mock_page
    ):
        """Deve gerar timestamp em formato ISO 8601."""
        mock_page.evaluate.side_effect = [
            {
                "current_time": 0.0,
                "video_width": 0,
                "video_height": 0,
                "ready_state": 0,
                "paused": True,
                "error": None,
                "buffered_seconds": 0.0,
            },
            {
                "average_level": None,
                "peak_level": None,
                "is_muted": True,
                "unavailable": True,
            },
            {
                "tracks_available": 0,
                "active_track": None,
                "has_active_cues": False,
            },
        ]

        result = await collector.collect_sample(mock_page)

        # Formato esperado: 2024-01-15T10:30:45.123Z
        assert len(result.timestamp) == 24
        assert result.timestamp[4] == "-"
        assert result.timestamp[10] == "T"
        assert result.timestamp[13] == ":"
        assert result.timestamp.endswith("Z")


class TestStartContinuousCollection:
    """Testes para coleta contínua."""

    async def test_coleta_continua_numero_amostras(
        self, collector, mock_page
    ):
        """Deve coletar número correto de amostras."""
        collector.interval_seconds = 1.0

        # Mock para cada chamada evaluate
        mock_page.evaluate.return_value = {
            "current_time": 10.0,
            "video_width": 1920,
            "video_height": 1080,
            "ready_state": 4,
            "paused": False,
            "error": None,
            "buffered_seconds": 10.0,
            "average_level": 50.0,
            "peak_level": 80.0,
            "is_muted": False,
            "unavailable": False,
            "tracks_available": 0,
            "active_track": None,
            "has_active_cues": False,
        }

        with patch("src.telemetry_collector.asyncio.sleep"):
            samples = await collector.start_continuous_collection(
                mock_page, duration_seconds=3.0
            )

        # Com intervalo de 1s e duração de 3s: coletas em t=0, t=1, t=2
        assert len(samples) == 3
        assert all(
            isinstance(s, TelemetrySample) for s in samples
        )

    async def test_coleta_continua_curta_duração(
        self, collector, mock_page
    ):
        """Deve coletar ao menos 1 amostra com duração mínima."""
        collector.interval_seconds = 5.0

        mock_page.evaluate.return_value = {
            "current_time": 1.0,
            "video_width": 1280,
            "video_height": 720,
            "ready_state": 4,
            "paused": False,
            "error": None,
            "buffered_seconds": 5.0,
            "average_level": None,
            "peak_level": None,
            "is_muted": False,
            "unavailable": True,
            "tracks_available": 0,
            "active_track": None,
            "has_active_cues": False,
        }

        with patch("src.telemetry_collector.asyncio.sleep"):
            samples = await collector.start_continuous_collection(
                mock_page, duration_seconds=2.0
            )

        # Deve coletar ao menos uma amostra
        assert len(samples) >= 1


class TestErrorHandling:
    """Testes para tratamento de erros."""

    async def test_attach_error_listener(
        self, collector, mock_page
    ):
        """Deve anexar listener de erro no player."""
        mock_page.evaluate.return_value = None

        await collector._attach_error_listener(mock_page)

        assert collector._error_listener_attached is True

    async def test_attach_error_listener_falha(
        self, collector, mock_page
    ):
        """Deve lidar com falha ao anexar listener."""
        mock_page.evaluate.side_effect = Exception(
            "Page not ready"
        )

        await collector._attach_error_listener(mock_page)

        # Não deve marcar como attached se falhou
        assert collector._error_listener_attached is False

    async def test_check_player_error_nenhum(
        self, collector, mock_page
    ):
        """Deve retornar None quando não há erro."""
        mock_page.evaluate.return_value = None

        error = await collector._check_player_error(mock_page)

        assert error is None

    async def test_check_player_error_presente(
        self, collector, mock_page
    ):
        """Deve retornar mensagem de erro quando presente."""
        mock_page.evaluate.return_value = (
            "Code: 4, Message: MEDIA_ERR_SRC_NOT_SUPPORTED, "
            "Time: 2024-01-15T10:30:00.000Z"
        )

        error = await collector._check_player_error(mock_page)

        assert error is not None
        assert "MEDIA_ERR_SRC_NOT_SUPPORTED" in error


class TestInitialization:
    """Testes para inicialização do collector."""

    def test_valores_padrao(self):
        """Deve usar valores padrão corretos."""
        collector = TelemetryCollector()

        assert collector.interval_seconds == 2.0
        assert collector.channel_id == "unknown"

    def test_valores_customizados(self):
        """Deve aceitar valores customizados."""
        collector = TelemetryCollector(
            interval_seconds=5.0,
            channel_id="sky-sports-hd",
        )

        assert collector.interval_seconds == 5.0
        assert collector.channel_id == "sky-sports-hd"
