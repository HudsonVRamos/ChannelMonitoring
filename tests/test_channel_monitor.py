"""Testes unitários para o ChannelMonitor.

Testa a rotação multi-canal, monitoramento individual de canais,
reutilização do CapabilityMap, consolidação de ChannelReport e
classificação de status.

Requirements: 10.1, 10.2, 10.3, 3.1, 3.4
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.player_discovery.monitoring.channel_monitor import (
    ChannelMonitor,
    _extract_channel_id,
)
from src.player_discovery.models.enums import (
    AudioStatus,
    BufferStatus,
    ChannelHealthStatus,
)
from src.player_discovery.models.results import (
    ChannelReport,
    HealthScores,
)
from src.player_discovery.models.telemetry import (
    AudioTelemetry,
    BufferTelemetry,
    SubtitleTelemetry,
    VideoTelemetry,
)


# --- Fixtures ---


@pytest.fixture
def mock_capability_map():
    """Mock de CapabilityMap válido e reutilizável."""
    cap_map = MagicMock()
    cap_map.is_valid.return_value = True
    cap_map.get_capability.return_value = MagicMock(
        available=True, confidence=0.9
    )
    return cap_map


@pytest.fixture
def mock_page():
    """Mock da Playwright Page com navegação funcional."""
    page = AsyncMock()
    page.goto = AsyncMock(return_value=None)
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
    page.expose_function = AsyncMock(return_value=None)
    page.wait_for_timeout = AsyncMock(return_value=None)
    return page


@pytest.fixture
def channel_monitor(mock_capability_map, mock_page):
    """ChannelMonitor configurado com período de observação curto."""
    config = {
        "observation_period_s": 0.1,  # Período curto para testes
        "telemetry_interval_s": 0.05,
        "navigation_timeout_ms": 5000,
    }
    return ChannelMonitor(
        capability_map=mock_capability_map,
        page=mock_page,
        config=config,
    )


# --- Testes de _extract_channel_id ---


class TestExtractChannelId:
    """Testes para extração de channel_id a partir de URL."""

    def test_extrai_ultimo_segmento_path(self):
        """Deve extrair o último segmento do path como ID."""
        result = _extract_channel_id(
            "https://example.com/channels/hbo-max"
        )
        assert result == "hbo-max"

    def test_extrai_de_url_com_path_longo(self):
        """Deve usar último segmento de paths longos."""
        result = _extract_channel_id(
            "https://sky.com/live/channels/sport/espn"
        )
        assert result == "espn"

    def test_url_sem_path_retorna_netloc(self):
        """Deve retornar netloc quando path está vazio."""
        result = _extract_channel_id("https://example.com/")
        assert result == "example.com"

    def test_url_invalida_retorna_url_completa(self):
        """Deve retornar a URL completa quando parsing falha."""
        result = _extract_channel_id("not-a-valid-url")
        assert result == "not-a-valid-url"


# --- Testes de __init__ ---


class TestChannelMonitorInit:
    """Testes de inicialização do ChannelMonitor."""

    def test_reutiliza_capability_map(
        self, mock_capability_map, mock_page
    ):
        """Deve armazenar a referência ao mesmo CapabilityMap (Req 3.1)."""
        monitor = ChannelMonitor(
            capability_map=mock_capability_map, page=mock_page
        )
        assert monitor.capability_map is mock_capability_map

    def test_rotation_count_inicia_zero(
        self, mock_capability_map, mock_page
    ):
        """Rotation count deve iniciar em 0."""
        monitor = ChannelMonitor(
            capability_map=mock_capability_map, page=mock_page
        )
        assert monitor.rotation_count == 0

    def test_config_padrao_aplicada(
        self, mock_capability_map, mock_page
    ):
        """Deve aplicar configurações padrão quando config=None."""
        monitor = ChannelMonitor(
            capability_map=mock_capability_map, page=mock_page
        )
        assert monitor._observation_period_s == 30.0
        assert monitor._telemetry_interval_s == 2.0
        assert monitor._navigation_timeout_ms == 30000

    def test_config_custom_aplicada(
        self, mock_capability_map, mock_page
    ):
        """Deve aplicar configurações custom quando fornecidas."""
        config = {
            "observation_period_s": 60.0,
            "telemetry_interval_s": 5.0,
            "navigation_timeout_ms": 60000,
        }
        monitor = ChannelMonitor(
            capability_map=mock_capability_map,
            page=mock_page,
            config=config,
        )
        assert monitor._observation_period_s == 60.0
        assert monitor._telemetry_interval_s == 5.0
        assert monitor._navigation_timeout_ms == 60000


# --- Testes de start_rotation ---


class TestStartRotation:
    """Testes para rotação multi-canal."""

    @pytest.mark.asyncio
    async def test_retorna_lista_vazia_sem_canais(
        self, channel_monitor
    ):
        """Deve retornar lista vazia quando channels é vazio."""
        result = await channel_monitor.start_rotation([])
        assert result == []

    @pytest.mark.asyncio
    async def test_retorna_report_por_canal(
        self, channel_monitor
    ):
        """Deve retornar um ChannelReport para cada canal."""
        channels = [
            "https://example.com/channel/hbo",
            "https://example.com/channel/espn",
            "https://example.com/channel/discovery",
        ]

        reports = await channel_monitor.start_rotation(channels)

        assert len(reports) == 3
        for report in reports:
            assert isinstance(report, ChannelReport)

    @pytest.mark.asyncio
    async def test_incrementa_rotation_count(
        self, channel_monitor
    ):
        """Deve incrementar rotation_count após completar rotação."""
        assert channel_monitor.rotation_count == 0

        await channel_monitor.start_rotation(
            ["https://example.com/ch1"]
        )
        assert channel_monitor.rotation_count == 1

        await channel_monitor.start_rotation(
            ["https://example.com/ch2"]
        )
        assert channel_monitor.rotation_count == 2

    @pytest.mark.asyncio
    async def test_reutiliza_mesmo_capability_map_para_todos_canais(
        self, channel_monitor, mock_capability_map
    ):
        """Deve usar o MESMO CapabilityMap para todos os canais (Req 3.1, 3.4)."""
        channels = [
            "https://example.com/ch1",
            "https://example.com/ch2",
            "https://example.com/ch3",
        ]

        await channel_monitor.start_rotation(channels)

        # O capability_map não deve ter sido substituído
        assert (
            channel_monitor.capability_map is mock_capability_map
        )

    @pytest.mark.asyncio
    async def test_canal_com_erro_continua_rotacao(
        self, channel_monitor, mock_page
    ):
        """Deve continuar rotação mesmo se um canal falhar."""
        call_count = 0

        async def goto_side_effect(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise Exception("Navigation timeout")
            return None

        mock_page.goto = AsyncMock(side_effect=goto_side_effect)

        channels = [
            "https://example.com/ch1",
            "https://example.com/ch2",  # Este vai falhar
            "https://example.com/ch3",
        ]

        reports = await channel_monitor.start_rotation(channels)

        assert len(reports) == 3
        # Canal 2 deve ter status CRITICAL
        assert reports[1].status == ChannelHealthStatus.CRITICAL


# --- Testes de monitor_channel ---


class TestMonitorChannel:
    """Testes para monitoramento individual de canal."""

    @pytest.mark.asyncio
    async def test_navega_para_url_do_canal(
        self, channel_monitor, mock_page
    ):
        """Deve navegar para a URL do canal antes de monitorar."""
        channel_url = "https://example.com/channel/hbo"

        await channel_monitor.monitor_channel(channel_url)

        mock_page.goto.assert_called_once_with(
            channel_url,
            timeout=5000,
            wait_until="domcontentloaded",
        )

    @pytest.mark.asyncio
    async def test_retorna_channel_report_completo(
        self, channel_monitor
    ):
        """Deve retornar ChannelReport com todos os campos."""
        report = await channel_monitor.monitor_channel(
            "https://example.com/channel/hbo"
        )

        assert isinstance(report, ChannelReport)
        assert report.channel_url == "https://example.com/channel/hbo"
        assert report.channel_id == "hbo"
        assert isinstance(report.status, ChannelHealthStatus)
        assert isinstance(report.health_scores, HealthScores)
        assert isinstance(report.video_telemetry, VideoTelemetry)
        assert isinstance(report.audio_telemetry, AudioTelemetry)
        assert isinstance(
            report.subtitle_telemetry, SubtitleTelemetry
        )
        assert isinstance(report.buffer_telemetry, BufferTelemetry)
        assert isinstance(report.events, list)
        assert isinstance(report.functional_tests, list)
        assert report.observation_duration_ms > 0

    @pytest.mark.asyncio
    async def test_classifica_canal_saudavel(
        self, mock_capability_map
    ):
        """Deve classificar canal como HEALTHY quando telemetria ok."""
        # Usar page com evaluate que retorna dados compatíveis
        # com todas as probes (video, audio e buffer)
        page = AsyncMock()

        call_count = [0]

        async def smart_evaluate(js_code, *args, **kwargs):
            """Retorna dados adequados para cada probe."""
            call_count[0] += 1
            js_str = str(js_code)

            # BufferProbe: verifica buffer ranges
            if "buffered" in js_str and "bufferAhead" in js_str:
                return {
                    "buffered_start": 90.0,
                    "buffered_end": 135.0,
                    "buffer_ahead": 15.0,
                    "playing": True,
                }

            # AudioProbe init: Web Audio API
            if "AudioContext" in js_str:
                return True

            # AudioProbe collect / SubtitleProbe: textTracks
            if "textTracks" in js_str and "tracks_available" in js_str:
                return {
                    "tracks_available": 0,
                    "tracks": [],
                    "active_track": None,
                    "has_active_cues": False,
                }

            # AudioProbe collect
            if "audioProbeAnalyser" in js_str:
                return {
                    "muted": False,
                    "volume": 1.0,
                    "rms": 0.15,
                    "peak": 0.4,
                    "tracks_available": ["Portuguese"],
                }

            # VideoProbe: padrão
            return {
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
            }

        page.evaluate = AsyncMock(side_effect=smart_evaluate)
        page.goto = AsyncMock(return_value=None)
        page.expose_function = AsyncMock(return_value=None)
        page.wait_for_timeout = AsyncMock(return_value=None)

        config = {
            "observation_period_s": 0.1,
            "telemetry_interval_s": 0.05,
            "navigation_timeout_ms": 5000,
        }
        monitor = ChannelMonitor(
            capability_map=mock_capability_map,
            page=page,
            config=config,
        )

        report = await monitor.monitor_channel(
            "https://example.com/channel/espn"
        )

        assert report.status == ChannelHealthStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_observation_duration_registrada(
        self, channel_monitor
    ):
        """Deve registrar a duração real da observação."""
        report = await channel_monitor.monitor_channel(
            "https://example.com/channel/hbo"
        )

        # Com período de 0.1s, deve registrar ~100ms
        assert report.observation_duration_ms > 0

    @pytest.mark.asyncio
    async def test_escalacao_padrao_desativada(
        self, channel_monitor
    ):
        """Escalação para OpenCV/Bedrock deve estar desativada por padrão."""
        report = await channel_monitor.monitor_channel(
            "https://example.com/channel/hbo"
        )

        assert report.escalated_to_opencv is False
        assert report.escalated_to_bedrock is False


# --- Testes de classificação de status ---


class TestClassifyChannelStatus:
    """Testes para classificação de status do canal."""

    def test_critical_com_erro_de_video(self, channel_monitor):
        """CRITICAL quando há erro no vídeo."""
        video = VideoTelemetry(
            current_time=0.0, duration=0.0, ready_state=0,
            paused=True, playing=False, ended=False,
            seeking=False, playback_rate=1.0, network_state=3,
            buffered_seconds=0.0, video_width=0, video_height=0,
            error="code=4: MEDIA_ERR_SRC_NOT_SUPPORTED",
        )
        audio = AudioTelemetry(
            rms=0.1, peak=0.3, silence_duration=0.0,
            muted=False, status=AudioStatus.OK,
            tracks_available=[],
        )
        buffer = BufferTelemetry(
            buffered_start=0.0, buffered_end=0.0,
            buffer_ahead=0.0, waiting_count=0,
            waiting_total_ms=0.0, longest_wait_ms=0.0,
            time_since_last_wait=None, status=BufferStatus.OK,
        )

        status = channel_monitor._classify_channel_status(
            video, audio, buffer
        )
        assert status == ChannelHealthStatus.CRITICAL

    def test_degraded_com_no_audio(self, channel_monitor):
        """DEGRADED quando status de áudio é NO_AUDIO."""
        video = VideoTelemetry(
            current_time=100.0, duration=3600.0, ready_state=4,
            paused=False, playing=True, ended=False,
            seeking=False, playback_rate=1.0, network_state=2,
            buffered_seconds=10.0, video_width=1920,
            video_height=1080,
        )
        audio = AudioTelemetry(
            rms=0.001, peak=0.002, silence_duration=15.0,
            muted=False, status=AudioStatus.NO_AUDIO,
            tracks_available=[],
        )
        buffer = BufferTelemetry(
            buffered_start=0.0, buffered_end=110.0,
            buffer_ahead=10.0, waiting_count=0,
            waiting_total_ms=0.0, longest_wait_ms=0.0,
            time_since_last_wait=None, status=BufferStatus.OK,
        )

        status = channel_monitor._classify_channel_status(
            video, audio, buffer
        )
        assert status == ChannelHealthStatus.DEGRADED

    def test_degraded_com_buffering_frequent(
        self, channel_monitor
    ):
        """DEGRADED quando buffer é BUFFERING_FREQUENT."""
        video = VideoTelemetry(
            current_time=100.0, duration=3600.0, ready_state=4,
            paused=False, playing=True, ended=False,
            seeking=False, playback_rate=1.0, network_state=2,
            buffered_seconds=1.0, video_width=1920,
            video_height=1080,
        )
        audio = AudioTelemetry(
            rms=0.1, peak=0.3, silence_duration=0.0,
            muted=False, status=AudioStatus.OK,
            tracks_available=[],
        )
        buffer = BufferTelemetry(
            buffered_start=0.0, buffered_end=101.0,
            buffer_ahead=1.0, waiting_count=5,
            waiting_total_ms=8000.0, longest_wait_ms=3000.0,
            time_since_last_wait=2.0,
            status=BufferStatus.BUFFERING_FREQUENT,
        )

        status = channel_monitor._classify_channel_status(
            video, audio, buffer
        )
        assert status == ChannelHealthStatus.DEGRADED

    def test_suspect_com_audio_low(self, channel_monitor):
        """SUSPECT quando status de áudio é AUDIO_LOW."""
        video = VideoTelemetry(
            current_time=100.0, duration=3600.0, ready_state=4,
            paused=False, playing=True, ended=False,
            seeking=False, playback_rate=1.0, network_state=2,
            buffered_seconds=10.0, video_width=1920,
            video_height=1080,
        )
        audio = AudioTelemetry(
            rms=0.03, peak=0.05, silence_duration=0.0,
            muted=False, status=AudioStatus.AUDIO_LOW,
            tracks_available=[],
        )
        buffer = BufferTelemetry(
            buffered_start=0.0, buffered_end=110.0,
            buffer_ahead=10.0, waiting_count=0,
            waiting_total_ms=0.0, longest_wait_ms=0.0,
            time_since_last_wait=None, status=BufferStatus.OK,
        )

        status = channel_monitor._classify_channel_status(
            video, audio, buffer
        )
        assert status == ChannelHealthStatus.SUSPECT

    def test_suspect_com_buffer_low(self, channel_monitor):
        """SUSPECT quando buffer é BUFFER_LOW."""
        video = VideoTelemetry(
            current_time=100.0, duration=3600.0, ready_state=4,
            paused=False, playing=True, ended=False,
            seeking=False, playback_rate=1.0, network_state=2,
            buffered_seconds=1.5, video_width=1920,
            video_height=1080,
        )
        audio = AudioTelemetry(
            rms=0.1, peak=0.3, silence_duration=0.0,
            muted=False, status=AudioStatus.OK,
            tracks_available=[],
        )
        buffer = BufferTelemetry(
            buffered_start=0.0, buffered_end=101.5,
            buffer_ahead=1.5, waiting_count=1,
            waiting_total_ms=500.0, longest_wait_ms=500.0,
            time_since_last_wait=5.0,
            status=BufferStatus.BUFFER_LOW,
        )

        status = channel_monitor._classify_channel_status(
            video, audio, buffer
        )
        assert status == ChannelHealthStatus.SUSPECT

    def test_healthy_sem_problemas(self, channel_monitor):
        """HEALTHY quando não há problemas detectados."""
        video = VideoTelemetry(
            current_time=100.0, duration=3600.0, ready_state=4,
            paused=False, playing=True, ended=False,
            seeking=False, playback_rate=1.0, network_state=2,
            buffered_seconds=15.0, video_width=1920,
            video_height=1080,
        )
        audio = AudioTelemetry(
            rms=0.1, peak=0.3, silence_duration=0.0,
            muted=False, status=AudioStatus.OK,
            tracks_available=["Portuguese"],
        )
        buffer = BufferTelemetry(
            buffered_start=0.0, buffered_end=115.0,
            buffer_ahead=15.0, waiting_count=0,
            waiting_total_ms=0.0, longest_wait_ms=0.0,
            time_since_last_wait=None, status=BufferStatus.OK,
        )

        status = channel_monitor._classify_channel_status(
            video, audio, buffer
        )
        assert status == ChannelHealthStatus.HEALTHY


# --- Testes de health scores ---


class TestHealthScoreCalculation:
    """Testes para cálculo de health scores no ChannelMonitor."""

    def test_calcula_video_e_audio_health(self, channel_monitor):
        """Deve calcular video e audio health scores."""
        video = VideoTelemetry(
            current_time=100.0, duration=3600.0, ready_state=4,
            paused=False, playing=True, ended=False,
            seeking=False, playback_rate=1.0, network_state=2,
            buffered_seconds=15.0, video_width=1920,
            video_height=1080,
        )
        audio = AudioTelemetry(
            rms=0.15, peak=0.4, silence_duration=0.0,
            muted=False, status=AudioStatus.OK,
            tracks_available=["Portuguese", "English"],
        )

        scores = channel_monitor._calculate_health_scores(
            video, audio
        )

        assert isinstance(scores, HealthScores)
        assert 0.0 <= scores.video_health <= 100.0
        assert 0.0 <= scores.audio_health <= 100.0
        assert scores.functional_health == 0.0  # Não calculado aqui


# --- Testes de error report ---


class TestBuildErrorReport:
    """Testes para construção de report de erro."""

    def test_error_report_status_critical(self, channel_monitor):
        """Error report deve ter status CRITICAL."""
        report = channel_monitor._build_error_report(
            "https://example.com/channel/hbo",
            "Navigation timeout",
        )

        assert report.status == ChannelHealthStatus.CRITICAL
        assert report.channel_url == "https://example.com/channel/hbo"
        assert report.channel_id == "hbo"
        assert report.observation_duration_ms == 0

    def test_error_report_health_scores_zero(
        self, channel_monitor
    ):
        """Error report deve ter health scores zerados."""
        report = channel_monitor._build_error_report(
            "https://example.com/channel/hbo", "Error"
        )

        assert report.health_scores.video_health == 0.0
        assert report.health_scores.audio_health == 0.0
        assert report.health_scores.functional_health == 0.0


# --- Testes de invalidação por falhas consecutivas (Req 10.4) ---


class TestConsecutiveFailureInvalidation:
    """Testes para lógica de invalidação por falhas consecutivas.

    Requirements: 10.4, 4.3, 4.5
    - Acumular falhas somente em canais consecutivos
    - Invalidar CapabilityMap com N falhas consecutivas (threshold: 3)
    - Falhas em canais não-consecutivos não acumulam
    - Ao invalidar, pausar rotação, executar re-discovery, retomar
    """

    @pytest.fixture
    def monitor_with_threshold(
        self, mock_capability_map, mock_page
    ):
        """ChannelMonitor com threshold configurável."""
        config = {
            "observation_period_s": 0.1,
            "telemetry_interval_s": 0.05,
            "navigation_timeout_ms": 5000,
            "invalidation_threshold": 3,
        }
        return ChannelMonitor(
            capability_map=mock_capability_map,
            page=mock_page,
            config=config,
        )

    def test_consecutive_failures_inicia_zero(
        self, monitor_with_threshold
    ):
        """Contador de falhas consecutivas deve iniciar em 0."""
        assert monitor_with_threshold.consecutive_failures == 0

    def test_invalidation_threshold_padrao(
        self, mock_capability_map, mock_page
    ):
        """Threshold padrão deve ser 3."""
        monitor = ChannelMonitor(
            capability_map=mock_capability_map, page=mock_page
        )
        assert monitor.invalidation_threshold == 3

    def test_invalidation_threshold_configuravel(
        self, mock_capability_map, mock_page
    ):
        """Threshold deve ser configurável via config."""
        config = {"invalidation_threshold": 5}
        monitor = ChannelMonitor(
            capability_map=mock_capability_map,
            page=mock_page,
            config=config,
        )
        assert monitor.invalidation_threshold == 5

    def test_register_channel_success_reseta_contador(
        self, monitor_with_threshold
    ):
        """Sucesso de canal deve resetar falhas consecutivas."""
        # Simular falhas acumuladas
        monitor_with_threshold._consecutive_failures = 2

        monitor_with_threshold.register_channel_success()

        assert monitor_with_threshold.consecutive_failures == 0

    def test_register_channel_failure_incrementa(
        self, monitor_with_threshold
    ):
        """Falha de canal deve incrementar falhas consecutivas."""
        monitor_with_threshold.register_channel_failure()
        assert monitor_with_threshold.consecutive_failures == 1

        monitor_with_threshold.register_channel_failure()
        assert monitor_with_threshold.consecutive_failures == 2

    def test_register_failure_retorna_false_abaixo_threshold(
        self, monitor_with_threshold
    ):
        """Deve retornar False quando abaixo do threshold."""
        result = monitor_with_threshold.register_channel_failure()
        assert result is False  # 1 < 3

        result = monitor_with_threshold.register_channel_failure()
        assert result is False  # 2 < 3

    def test_register_failure_retorna_true_no_threshold(
        self, monitor_with_threshold
    ):
        """Deve retornar True quando threshold é atingido."""
        monitor_with_threshold.register_channel_failure()  # 1
        monitor_with_threshold.register_channel_failure()  # 2
        result = (
            monitor_with_threshold.register_channel_failure()
        )  # 3
        assert result is True

    def test_falhas_nao_consecutivas_nao_acumulam(
        self, monitor_with_threshold
    ):
        """Falhas separadas por sucesso não devem acumular."""
        # Falha 1
        monitor_with_threshold.register_channel_failure()
        assert monitor_with_threshold.consecutive_failures == 1

        # Sucesso reseta
        monitor_with_threshold.register_channel_success()
        assert monitor_with_threshold.consecutive_failures == 0

        # Falha 2 (não é consecutiva à falha 1)
        monitor_with_threshold.register_channel_failure()
        assert monitor_with_threshold.consecutive_failures == 1

        # Sucesso reseta novamente
        monitor_with_threshold.register_channel_success()
        assert monitor_with_threshold.consecutive_failures == 0

    @pytest.mark.asyncio
    async def test_handle_invalidation_invalida_mapa(
        self, mock_capability_map, mock_page
    ):
        """Deve invalidar o CapabilityMap ao atingir threshold."""
        config = {
            "observation_period_s": 0.1,
            "telemetry_interval_s": 0.05,
            "invalidation_threshold": 3,
        }
        monitor = ChannelMonitor(
            capability_map=mock_capability_map,
            page=mock_page,
            config=config,
        )
        monitor._consecutive_failures = 3

        await monitor._handle_invalidation()

        mock_capability_map.invalidate.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_invalidation_executa_rediscovery(
        self, mock_capability_map, mock_page
    ):
        """Deve executar re-discovery via DiscoveryEngine."""
        # Mock do DiscoveryEngine
        mock_engine = AsyncMock()
        new_map = MagicMock()
        new_map.is_valid.return_value = True
        mock_engine.rediscover = AsyncMock(return_value=new_map)

        config = {
            "observation_period_s": 0.1,
            "telemetry_interval_s": 0.05,
            "invalidation_threshold": 3,
        }
        monitor = ChannelMonitor(
            capability_map=mock_capability_map,
            page=mock_page,
            config=config,
            discovery_engine=mock_engine,
        )
        monitor._consecutive_failures = 3

        await monitor._handle_invalidation()

        # Deve ter chamado rediscover com a page
        mock_engine.rediscover.assert_called_once_with(mock_page)
        # Mapa deve ter sido atualizado
        assert monitor.capability_map is new_map

    @pytest.mark.asyncio
    async def test_handle_invalidation_reseta_contador(
        self, mock_capability_map, mock_page
    ):
        """Deve resetar falhas consecutivas após invalidação."""
        config = {
            "observation_period_s": 0.1,
            "telemetry_interval_s": 0.05,
            "invalidation_threshold": 3,
        }
        monitor = ChannelMonitor(
            capability_map=mock_capability_map,
            page=mock_page,
            config=config,
        )
        monitor._consecutive_failures = 3

        await monitor._handle_invalidation()

        assert monitor.consecutive_failures == 0

    @pytest.mark.asyncio
    async def test_handle_invalidation_sem_engine(
        self, mock_capability_map, mock_page
    ):
        """Sem DiscoveryEngine, deve apenas invalidar o mapa."""
        config = {
            "observation_period_s": 0.1,
            "telemetry_interval_s": 0.05,
            "invalidation_threshold": 3,
        }
        monitor = ChannelMonitor(
            capability_map=mock_capability_map,
            page=mock_page,
            config=config,
            discovery_engine=None,
        )
        monitor._consecutive_failures = 3

        await monitor._handle_invalidation()

        # Deve invalidar mesmo sem engine
        mock_capability_map.invalidate.assert_called_once()
        # Contador resetado
        assert monitor.consecutive_failures == 0

    @pytest.mark.asyncio
    async def test_handle_invalidation_engine_falha(
        self, mock_capability_map, mock_page
    ):
        """Se re-discovery falhar, mapa fica inválido mas não quebra."""
        mock_engine = AsyncMock()
        mock_engine.rediscover = AsyncMock(
            side_effect=RuntimeError("Discovery failed")
        )

        config = {
            "observation_period_s": 0.1,
            "telemetry_interval_s": 0.05,
            "invalidation_threshold": 3,
        }
        monitor = ChannelMonitor(
            capability_map=mock_capability_map,
            page=mock_page,
            config=config,
            discovery_engine=mock_engine,
        )
        monitor._consecutive_failures = 3

        # Não deve lançar exceção
        await monitor._handle_invalidation()

        # Mapa invalidado
        mock_capability_map.invalidate.assert_called_once()
        # Contador resetado
        assert monitor.consecutive_failures == 0
        # Mapa NÃO foi substituído (rediscover falhou)
        assert monitor.capability_map is mock_capability_map

    @pytest.mark.asyncio
    async def test_start_rotation_invalida_apos_n_falhas(
        self, mock_capability_map, mock_page
    ):
        """Deve invalidar CapabilityMap após N falhas consecutivas."""
        # Todos os canais vão falhar na navegação
        mock_page.goto = AsyncMock(
            side_effect=Exception("Navigation timeout")
        )

        mock_engine = AsyncMock()
        new_map = MagicMock()
        new_map.is_valid.return_value = True
        mock_engine.rediscover = AsyncMock(return_value=new_map)

        config = {
            "observation_period_s": 0.1,
            "telemetry_interval_s": 0.05,
            "navigation_timeout_ms": 5000,
            "invalidation_threshold": 3,
        }
        monitor = ChannelMonitor(
            capability_map=mock_capability_map,
            page=mock_page,
            config=config,
            discovery_engine=mock_engine,
        )

        channels = [
            "https://example.com/ch1",
            "https://example.com/ch2",
            "https://example.com/ch3",
            "https://example.com/ch4",
        ]

        await monitor.start_rotation(channels)

        # Após 3 falhas consecutivas, rediscovery deve ser chamado
        mock_engine.rediscover.assert_called()
        mock_capability_map.invalidate.assert_called()

    @pytest.mark.asyncio
    async def test_start_rotation_sucesso_reseta_falhas(
        self, mock_capability_map, mock_page
    ):
        """Canal com sucesso deve resetar o contador de falhas."""
        call_count = [0]

        async def goto_side_effect(url, **kwargs):
            """Primeiro canal falha, segundo sucede."""
            call_count[0] += 1
            if call_count[0] == 1:
                raise Exception("Timeout")
            return None

        mock_page.goto = AsyncMock(side_effect=goto_side_effect)

        config = {
            "observation_period_s": 0.1,
            "telemetry_interval_s": 0.05,
            "navigation_timeout_ms": 5000,
            "invalidation_threshold": 3,
        }
        monitor = ChannelMonitor(
            capability_map=mock_capability_map,
            page=mock_page,
            config=config,
        )

        channels = [
            "https://example.com/ch1",  # Falha (failure=1)
            "https://example.com/ch2",  # Sucesso (reset)
        ]

        await monitor.start_rotation(channels)

        # Sucesso no ch2 deve ter resetado o contador
        assert monitor.consecutive_failures == 0

    @pytest.mark.asyncio
    async def test_start_rotation_pausa_e_retoma(
        self, mock_capability_map, mock_page
    ):
        """Ao invalidar, deve pausar, re-discovery e retomar rotação."""
        # Todos os canais vão falhar
        mock_page.goto = AsyncMock(
            side_effect=Exception("Navigation timeout")
        )

        mock_engine = AsyncMock()
        new_map = MagicMock()
        new_map.is_valid.return_value = True
        mock_engine.rediscover = AsyncMock(return_value=new_map)

        config = {
            "observation_period_s": 0.1,
            "telemetry_interval_s": 0.05,
            "navigation_timeout_ms": 5000,
            "invalidation_threshold": 3,
        }
        monitor = ChannelMonitor(
            capability_map=mock_capability_map,
            page=mock_page,
            config=config,
            discovery_engine=mock_engine,
        )

        channels = [
            "https://example.com/ch1",  # Falha 1
            "https://example.com/ch2",  # Falha 2
            "https://example.com/ch3",  # Falha 3 → invalidação
            "https://example.com/ch4",  # Continua após re-discovery
        ]

        reports = await monitor.start_rotation(channels)

        # Todos os 4 canais devem ter reports (rotação continuou)
        assert len(reports) == 4
        # Re-discovery foi executado
        mock_engine.rediscover.assert_called()

    @pytest.mark.asyncio
    async def test_threshold_custom_funciona(
        self, mock_capability_map, mock_page
    ):
        """Threshold customizado deve funcionar corretamente."""
        mock_page.goto = AsyncMock(
            side_effect=Exception("Timeout")
        )

        mock_engine = AsyncMock()
        new_map = MagicMock()
        new_map.is_valid.return_value = True
        mock_engine.rediscover = AsyncMock(return_value=new_map)

        # Threshold de 2
        config = {
            "observation_period_s": 0.1,
            "telemetry_interval_s": 0.05,
            "navigation_timeout_ms": 5000,
            "invalidation_threshold": 2,
        }
        monitor = ChannelMonitor(
            capability_map=mock_capability_map,
            page=mock_page,
            config=config,
            discovery_engine=mock_engine,
        )

        channels = [
            "https://example.com/ch1",
            "https://example.com/ch2",  # Threshold atingido aqui
            "https://example.com/ch3",
        ]

        await monitor.start_rotation(channels)

        # Com threshold 2, rediscovery deve ter sido chamado
        mock_engine.rediscover.assert_called()
