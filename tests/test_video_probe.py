"""Testes unitários para o VideoProbe.

Testa coleta de telemetria via page.evaluate(), detecção de freeze
e cálculo de drop_rate.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.player_discovery.probes.video_probe import VideoProbe
from src.player_discovery.models.telemetry import VideoTelemetry


# --- Fixtures ---


@pytest.fixture
def video_probe():
    """Instância limpa do VideoProbe."""
    return VideoProbe()


@pytest.fixture
def mock_page():
    """Mock da Playwright Page com evaluate retornando dados válidos."""
    page = AsyncMock()
    page.evaluate = AsyncMock(return_value={
        "current_time": 120.5,
        "duration": 7200.0,
        "ready_state": 4,
        "paused": False,
        "playing": True,
        "ended": False,
        "seeking": False,
        "playback_rate": 1.0,
        "network_state": 2,
        "buffered_seconds": 15.3,
        "video_width": 1920,
        "video_height": 1080,
        "error": None,
        "total_frames": 3600,
        "dropped_frames": 12,
    })
    return page


@pytest.fixture
def mock_capability_map():
    """Mock do CapabilityMap."""
    return MagicMock()


# --- Testes de collect() ---


class TestVideoProbeCollect:
    """Testes para o método collect()."""

    @pytest.mark.asyncio
    async def test_collect_retorna_video_telemetry(
        self, video_probe, mock_page, mock_capability_map
    ):
        """Collect deve retornar VideoTelemetry com todos os campos preenchidos."""
        result = await video_probe.collect(mock_page, mock_capability_map)

        assert isinstance(result, VideoTelemetry)
        assert result.current_time == 120.5
        assert result.duration == 7200.0
        assert result.ready_state == 4
        assert result.paused is False
        assert result.playing is True
        assert result.ended is False
        assert result.seeking is False
        assert result.playback_rate == 1.0
        assert result.network_state == 2
        assert result.buffered_seconds == 15.3
        assert result.video_width == 1920
        assert result.video_height == 1080
        assert result.error is None

    @pytest.mark.asyncio
    async def test_collect_calcula_drop_rate(
        self, video_probe, mock_page, mock_capability_map
    ):
        """Collect deve calcular drop_rate a partir de total_frames e dropped_frames."""
        result = await video_probe.collect(mock_page, mock_capability_map)

        assert result.total_frames == 3600
        assert result.dropped_frames == 12
        assert result.drop_rate == pytest.approx(12 / 3600)

    @pytest.mark.asyncio
    async def test_collect_sem_video_element_levanta_erro(
        self, video_probe, mock_capability_map
    ):
        """Collect deve levantar RuntimeError se não houver <video>."""
        page = AsyncMock()
        page.evaluate = AsyncMock(return_value=None)

        with pytest.raises(RuntimeError, match="Nenhum elemento <video>"):
            await video_probe.collect(page, mock_capability_map)

    @pytest.mark.asyncio
    async def test_collect_page_evaluate_falha(
        self, video_probe, mock_capability_map
    ):
        """Collect deve levantar RuntimeError se page.evaluate falhar."""
        page = AsyncMock()
        page.evaluate = AsyncMock(side_effect=Exception("Tab crashed"))

        with pytest.raises(RuntimeError, match="Falha ao coletar telemetria"):
            await video_probe.collect(page, mock_capability_map)

    @pytest.mark.asyncio
    async def test_collect_sem_playback_quality(
        self, video_probe, mock_capability_map
    ):
        """Collect funciona quando getVideoPlaybackQuality não está disponível."""
        page = AsyncMock()
        page.evaluate = AsyncMock(return_value={
            "current_time": 10.0,
            "duration": 3600.0,
            "ready_state": 4,
            "paused": False,
            "playing": True,
            "ended": False,
            "seeking": False,
            "playback_rate": 1.0,
            "network_state": 2,
            "buffered_seconds": 5.0,
            "video_width": 1280,
            "video_height": 720,
            "error": None,
            "total_frames": None,
            "dropped_frames": None,
        })

        result = await video_probe.collect(page, mock_capability_map)

        assert result.total_frames is None
        assert result.dropped_frames is None
        assert result.drop_rate is None
        assert result.fps_avg is None

    @pytest.mark.asyncio
    async def test_collect_fps_calculado_entre_coletas(
        self, video_probe, mock_capability_map
    ):
        """FPS deve ser calculado na segunda coleta baseado no delta de frames."""
        from unittest.mock import patch
        import time

        page = AsyncMock()

        # Primeira coleta: 1000 frames, time=100.0
        page.evaluate = AsyncMock(return_value={
            "current_time": 10.0,
            "duration": 3600.0,
            "ready_state": 4,
            "paused": False,
            "playing": True,
            "ended": False,
            "seeking": False,
            "playback_rate": 1.0,
            "network_state": 2,
            "buffered_seconds": 10.0,
            "video_width": 1920,
            "video_height": 1080,
            "error": None,
            "total_frames": 1000,
            "dropped_frames": 5,
        })

        with patch("src.player_discovery.probes.video_probe.time.monotonic", return_value=100.0):
            result1 = await video_probe.collect(page, mock_capability_map)
        # Na primeira coleta, FPS é None (não há delta)
        assert result1.fps_avg is None

        # Segunda coleta: 1060 frames, time=102.0 (2s depois)
        page.evaluate = AsyncMock(return_value={
            "current_time": 12.0,
            "duration": 3600.0,
            "ready_state": 4,
            "paused": False,
            "playing": True,
            "ended": False,
            "seeking": False,
            "playback_rate": 1.0,
            "network_state": 2,
            "buffered_seconds": 10.0,
            "video_width": 1920,
            "video_height": 1080,
            "error": None,
            "total_frames": 1060,
            "dropped_frames": 7,
        })

        with patch("src.player_discovery.probes.video_probe.time.monotonic", return_value=102.0):
            result2 = await video_probe.collect(page, mock_capability_map)
        # 60 frames em 2 segundos = 30 FPS
        assert result2.fps_avg is not None
        assert result2.fps_avg == pytest.approx(30.0)

    @pytest.mark.asyncio
    async def test_collect_com_erro_no_video(
        self, video_probe, mock_capability_map
    ):
        """Collect deve capturar erro do elemento de vídeo."""
        page = AsyncMock()
        page.evaluate = AsyncMock(return_value={
            "current_time": 0.0,
            "duration": 0.0,
            "ready_state": 0,
            "paused": True,
            "playing": False,
            "ended": False,
            "seeking": False,
            "playback_rate": 1.0,
            "network_state": 3,
            "buffered_seconds": 0.0,
            "video_width": 0,
            "video_height": 0,
            "error": "code=4: MEDIA_ERR_SRC_NOT_SUPPORTED",
            "total_frames": None,
            "dropped_frames": None,
        })

        result = await video_probe.collect(page, mock_capability_map)
        assert result.error == "code=4: MEDIA_ERR_SRC_NOT_SUPPORTED"


# --- Testes de detect_freeze() ---


class TestVideoProbeDetectFreeze:
    """Testes para detecção de freeze."""

    def test_freeze_detectado_current_time_estagnado(self):
        """Deve detectar freeze quando currentTime não avança por >5s."""
        # 4 amostras com mesmo currentTime e paused=false = 6s > 5s
        samples = [
            VideoTelemetry(
                current_time=100.0, duration=3600.0, ready_state=4,
                paused=False, playing=True, ended=False, seeking=False,
                playback_rate=1.0, network_state=2, buffered_seconds=10.0,
                video_width=1920, video_height=1080,
            )
            for _ in range(4)
        ]

        assert VideoProbe.detect_freeze(samples) is True

    def test_sem_freeze_current_time_avancando(self):
        """Não deve detectar freeze quando currentTime avança normalmente."""
        samples = [
            VideoTelemetry(
                current_time=100.0 + (i * 2.0), duration=3600.0, ready_state=4,
                paused=False, playing=True, ended=False, seeking=False,
                playback_rate=1.0, network_state=2, buffered_seconds=10.0,
                video_width=1920, video_height=1080,
            )
            for i in range(5)
        ]

        assert VideoProbe.detect_freeze(samples) is False

    def test_sem_freeze_quando_pausado(self):
        """Não deve detectar freeze quando o player está pausado."""
        samples = [
            VideoTelemetry(
                current_time=100.0, duration=3600.0, ready_state=4,
                paused=True, playing=False, ended=False, seeking=False,
                playback_rate=1.0, network_state=2, buffered_seconds=10.0,
                video_width=1920, video_height=1080,
            )
            for _ in range(10)
        ]

        assert VideoProbe.detect_freeze(samples) is False

    def test_sem_freeze_com_poucas_amostras(self):
        """Não deve detectar freeze com menos de 2 amostras."""
        sample = VideoTelemetry(
            current_time=100.0, duration=3600.0, ready_state=4,
            paused=False, playing=True, ended=False, seeking=False,
            playback_rate=1.0, network_state=2, buffered_seconds=10.0,
            video_width=1920, video_height=1080,
        )

        assert VideoProbe.detect_freeze([]) is False
        assert VideoProbe.detect_freeze([sample]) is False

    def test_sem_freeze_stall_curto(self):
        """Não deve detectar freeze se stall dura <=5s (2 amostras = 4s)."""
        # 3 amostras = 2 intervalos = 4s, não excede 5s
        samples = [
            VideoTelemetry(
                current_time=100.0, duration=3600.0, ready_state=4,
                paused=False, playing=True, ended=False, seeking=False,
                playback_rate=1.0, network_state=2, buffered_seconds=10.0,
                video_width=1920, video_height=1080,
            )
            for _ in range(3)
        ]

        assert VideoProbe.detect_freeze(samples) is False

    def test_freeze_detectado_exatamente_no_limite(self):
        """Deve detectar freeze com 4 amostras (3 intervalos = 6s > 5s)."""
        samples = [
            VideoTelemetry(
                current_time=50.0, duration=3600.0, ready_state=4,
                paused=False, playing=True, ended=False, seeking=False,
                playback_rate=1.0, network_state=2, buffered_seconds=10.0,
                video_width=1920, video_height=1080,
            )
            for _ in range(4)
        ]

        assert VideoProbe.detect_freeze(samples) is True

    def test_freeze_com_pausa_no_meio_reseta_contagem(self):
        """Pausa no meio da sequência deve resetar a contagem de freeze."""
        samples = [
            # 2 amostras estagnadas (4s, < 5s)
            VideoTelemetry(
                current_time=100.0, duration=3600.0, ready_state=4,
                paused=False, playing=True, ended=False, seeking=False,
                playback_rate=1.0, network_state=2, buffered_seconds=10.0,
                video_width=1920, video_height=1080,
            ),
            VideoTelemetry(
                current_time=100.0, duration=3600.0, ready_state=4,
                paused=False, playing=True, ended=False, seeking=False,
                playback_rate=1.0, network_state=2, buffered_seconds=10.0,
                video_width=1920, video_height=1080,
            ),
            # Pausa (reseta contagem)
            VideoTelemetry(
                current_time=100.0, duration=3600.0, ready_state=4,
                paused=True, playing=False, ended=False, seeking=False,
                playback_rate=1.0, network_state=2, buffered_seconds=10.0,
                video_width=1920, video_height=1080,
            ),
            # 2 amostras estagnadas após pausa (4s, < 5s)
            VideoTelemetry(
                current_time=100.0, duration=3600.0, ready_state=4,
                paused=False, playing=True, ended=False, seeking=False,
                playback_rate=1.0, network_state=2, buffered_seconds=10.0,
                video_width=1920, video_height=1080,
            ),
            VideoTelemetry(
                current_time=100.0, duration=3600.0, ready_state=4,
                paused=False, playing=True, ended=False, seeking=False,
                playback_rate=1.0, network_state=2, buffered_seconds=10.0,
                video_width=1920, video_height=1080,
            ),
        ]

        assert VideoProbe.detect_freeze(samples) is False


# --- Testes de calculate_drop_rate() ---


class TestVideoProbeCalculateDropRate:
    """Testes para cálculo da taxa de descarte de frames."""

    def test_drop_rate_calculo_basico(self):
        """Calcula drop_rate = dropped/total corretamente."""
        result = VideoProbe.calculate_drop_rate(1000, 50)
        assert result == pytest.approx(0.05)

    def test_drop_rate_zero_frames_descartados(self):
        """Drop rate deve ser 0.0 sem frames descartados."""
        result = VideoProbe.calculate_drop_rate(5000, 0)
        assert result == 0.0

    def test_drop_rate_todos_frames_descartados(self):
        """Drop rate deve ser 1.0 se todos os frames foram descartados."""
        result = VideoProbe.calculate_drop_rate(100, 100)
        assert result == 1.0

    def test_drop_rate_bounded_maximo_1(self):
        """Drop rate nunca deve exceder 1.0 mesmo com dados inválidos."""
        # Cenário impossível mas defensivo
        result = VideoProbe.calculate_drop_rate(50, 100)
        assert result == 1.0

    def test_drop_rate_bounded_minimo_0(self):
        """Drop rate nunca deve ser negativo."""
        result = VideoProbe.calculate_drop_rate(100, -5)
        assert result == 0.0

    def test_drop_rate_total_zero(self):
        """Drop rate deve ser 0.0 quando total_frames é 0."""
        result = VideoProbe.calculate_drop_rate(0, 0)
        assert result == 0.0

    def test_drop_rate_none_total(self):
        """Drop rate deve ser None quando total_frames é None."""
        result = VideoProbe.calculate_drop_rate(None, 10)
        assert result is None

    def test_drop_rate_none_dropped(self):
        """Drop rate deve ser None quando dropped_frames é None."""
        result = VideoProbe.calculate_drop_rate(1000, None)
        assert result is None

    def test_drop_rate_ambos_none(self):
        """Drop rate deve ser None quando ambos são None."""
        result = VideoProbe.calculate_drop_rate(None, None)
        assert result is None
