"""Testes unitários para a lógica de escalação do ChannelMonitor.

Testa o pipeline de escalação determinística:
- HEALTHY: captura apenas 1 frame de validação, sem OpenCV/Bedrock
- SUSPECT: captura frames adicionais + OpenCV
- DEGRADED/CRITICAL: OpenCV + Bedrock (se OpenCV confirma anomalia)
- Bedrock somente acionado se OpenCV confirmar anomalia

Requirements: 14.1, 14.2, 14.3, 14.4, 14.5
"""

import pytest
import numpy as np
import cv2
from dataclasses import dataclass
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

from src.player_discovery.monitoring.channel_monitor import (
    ChannelMonitor,
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


# --- Helpers ---


def _create_valid_png(
    width: int = 100, height: int = 100, color: tuple = (128, 128, 128)
) -> bytes:
    """Cria um PNG válido em memória para testes."""
    img = np.full((height, width, 3), color, dtype=np.uint8)
    success, buffer = cv2.imencode(".png", img)
    assert success
    return buffer.tobytes()


def _create_black_png(width: int = 100, height: int = 100) -> bytes:
    """Cria um PNG preto (tela preta) para testes."""
    return _create_valid_png(width, height, color=(0, 0, 0))


# --- Helpers ---


@dataclass
class FakeFrameResult:
    """Frame simulado para testes."""

    data: bytes
    width: int = 1920
    height: int = 1080
    size_bytes: int = 1000
    mean_luminance: float = 128.0
    is_valid: bool = True
    timestamp: str = "2024-01-01T00:00:00.000Z"
    rejected_reason: Optional[str] = None


@dataclass
class FakeBlackScreenResult:
    """Resultado de tela preta simulado."""

    is_black_screen: bool
    is_dark_scene: bool = False


@dataclass
class FakeFreezeClassification:
    """Classificação de freeze simulada."""

    value: str


@dataclass
class FakeFreezeResult:
    """Resultado de freeze simulado."""

    classification: FakeFreezeClassification
    similarity: float = 0.99
    current_time_diff: float = 0.0
    observation_window_seconds: float = 6.0


def _make_report(
    status: ChannelHealthStatus = ChannelHealthStatus.HEALTHY,
) -> ChannelReport:
    """Cria um ChannelReport de teste."""
    return ChannelReport(
        channel_id="test-channel",
        channel_url="https://example.com/channel/test",
        status=status,
        health_scores=HealthScores(
            video_health=90.0,
            audio_health=85.0,
            functional_health=0.0,
        ),
        video_telemetry=VideoTelemetry(
            current_time=120.0,
            duration=7200.0,
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
        ),
        audio_telemetry=AudioTelemetry(
            rms=0.3,
            peak=0.5,
            silence_duration=0.0,
            muted=False,
            status=AudioStatus.OK,
            tracks_available=[],
        ),
        subtitle_telemetry=SubtitleTelemetry(
            tracks_available=0,
            tracks=[],
            active_track=None,
            has_active_cues=False,
            status="OK",
        ),
        buffer_telemetry=BufferTelemetry(
            buffered_start=0.0,
            buffered_end=135.0,
            buffer_ahead=15.0,
            waiting_count=0,
            waiting_total_ms=0.0,
            longest_wait_ms=0.0,
            time_since_last_wait=None,
            status=BufferStatus.OK,
        ),
        events=[],
        functional_tests=[],
        observation_duration_ms=30000,
        escalated_to_opencv=False,
        escalated_to_bedrock=False,
    )


# --- Fixtures ---


@pytest.fixture
def mock_capability_map():
    """Mock de CapabilityMap válido."""
    cap_map = MagicMock()
    cap_map.is_valid.return_value = True
    cap_map.get_capability.return_value = MagicMock(
        available=True, confidence=0.9
    )
    return cap_map


@pytest.fixture
def mock_page():
    """Mock da Playwright Page."""
    page = AsyncMock()
    page.goto = AsyncMock(return_value=None)
    page.evaluate = AsyncMock(return_value={})
    page.expose_function = AsyncMock(return_value=None)
    return page


@pytest.fixture
def mock_frame_capturer():
    """Mock do FrameCapturer com frames PNG válidos."""
    capturer = AsyncMock()
    valid_png = _create_valid_png()
    frame = FakeFrameResult(data=valid_png)
    capturer.capture_frame = AsyncMock(return_value=frame)
    capturer.capture_sequence = AsyncMock(
        return_value=[frame, frame, frame]
    )
    return capturer


@pytest.fixture
def mock_opencv_analyzer():
    """Mock do OpenCVAnalyzer."""
    analyzer = MagicMock()
    analyzer.detect_black_screen = MagicMock(
        return_value=FakeBlackScreenResult(is_black_screen=False)
    )
    analyzer.detect_freeze = MagicMock(
        return_value=FakeFreezeResult(
            classification=FakeFreezeClassification(value="NO_FREEZE")
        )
    )
    return analyzer


@pytest.fixture
def mock_bedrock_client():
    """Mock do BedrockClient."""
    client = AsyncMock()
    client.diagnose_frame = AsyncMock(return_value=MagicMock(
        status="DEGRADED",
        diagnosis="Anomalia visual detectada",
        confidence=0.85,
    ))
    return client


@pytest.fixture
def monitor_with_escalation(
    mock_capability_map,
    mock_page,
    mock_frame_capturer,
    mock_opencv_analyzer,
    mock_bedrock_client,
):
    """ChannelMonitor com todas as dependências de escalação."""
    config = {
        "observation_period_s": 0.1,
        "telemetry_interval_s": 0.05,
        "escalation_frame_count": 3,
        "escalation_frame_interval": 2.0,
    }
    return ChannelMonitor(
        capability_map=mock_capability_map,
        page=mock_page,
        config=config,
        frame_capturer=mock_frame_capturer,
        opencv_analyzer=mock_opencv_analyzer,
        bedrock_client=mock_bedrock_client,
    )


@pytest.fixture
def monitor_sem_dependencias(mock_capability_map, mock_page):
    """ChannelMonitor sem dependências de escalação."""
    config = {
        "observation_period_s": 0.1,
        "telemetry_interval_s": 0.05,
    }
    return ChannelMonitor(
        capability_map=mock_capability_map,
        page=mock_page,
        config=config,
    )


# =============================================================================
# Testes: Canal HEALTHY — apenas 1 frame de validação (Req 14.1, 14.5)
# =============================================================================


class TestEscalacaoHealthy:
    """Testes para canal HEALTHY no pipeline de escalação."""

    @pytest.mark.asyncio
    async def test_healthy_captura_apenas_1_frame(
        self, monitor_with_escalation, mock_frame_capturer
    ):
        """Canal HEALTHY deve capturar apenas 1 frame de validação."""
        report = _make_report(ChannelHealthStatus.HEALTHY)

        result = await monitor_with_escalation._escalate_channel(
            ChannelHealthStatus.HEALTHY, report
        )

        # Deve chamar capture_frame (1 frame) e NÃO capture_sequence
        mock_frame_capturer.capture_frame.assert_called_once()
        mock_frame_capturer.capture_sequence.assert_not_called()

    @pytest.mark.asyncio
    async def test_healthy_nao_aciona_opencv(
        self, monitor_with_escalation, mock_opencv_analyzer
    ):
        """Canal HEALTHY não deve acionar OpenCV."""
        report = _make_report(ChannelHealthStatus.HEALTHY)

        result = await monitor_with_escalation._escalate_channel(
            ChannelHealthStatus.HEALTHY, report
        )

        mock_opencv_analyzer.detect_black_screen.assert_not_called()
        mock_opencv_analyzer.detect_freeze.assert_not_called()
        assert result.escalated_to_opencv is False

    @pytest.mark.asyncio
    async def test_healthy_nao_aciona_bedrock(
        self, monitor_with_escalation, mock_bedrock_client
    ):
        """Canal HEALTHY não deve acionar Bedrock."""
        report = _make_report(ChannelHealthStatus.HEALTHY)

        result = await monitor_with_escalation._escalate_channel(
            ChannelHealthStatus.HEALTHY, report
        )

        mock_bedrock_client.diagnose_frame.assert_not_called()
        assert result.escalated_to_bedrock is False

    @pytest.mark.asyncio
    async def test_healthy_report_nao_marca_escalacao(
        self, monitor_with_escalation
    ):
        """Canal HEALTHY deve retornar report sem marcação de escalação."""
        report = _make_report(ChannelHealthStatus.HEALTHY)

        result = await monitor_with_escalation._escalate_channel(
            ChannelHealthStatus.HEALTHY, report
        )

        assert result.escalated_to_opencv is False
        assert result.escalated_to_bedrock is False


# =============================================================================
# Testes: Canal SUSPECT — captura frames + OpenCV (Req 14.2)
# =============================================================================


class TestEscalacaoSuspect:
    """Testes para canal SUSPECT no pipeline de escalação."""

    @pytest.mark.asyncio
    async def test_suspect_captura_frames_adicionais(
        self, monitor_with_escalation, mock_frame_capturer
    ):
        """Canal SUSPECT deve capturar frames adicionais via capture_sequence."""
        report = _make_report(ChannelHealthStatus.SUSPECT)

        await monitor_with_escalation._escalate_channel(
            ChannelHealthStatus.SUSPECT, report
        )

        # Deve chamar capture_sequence (múltiplos frames)
        mock_frame_capturer.capture_sequence.assert_called_once_with(
            monitor_with_escalation._page, 3, 2.0
        )
        # NÃO deve chamar capture_frame (1 frame é só para HEALTHY)
        mock_frame_capturer.capture_frame.assert_not_called()

    @pytest.mark.asyncio
    async def test_suspect_aciona_opencv(
        self, monitor_with_escalation, mock_opencv_analyzer
    ):
        """Canal SUSPECT deve acionar OpenCV para confirmar anomalia."""
        report = _make_report(ChannelHealthStatus.SUSPECT)

        result = await monitor_with_escalation._escalate_channel(
            ChannelHealthStatus.SUSPECT, report
        )

        assert result.escalated_to_opencv is True

    @pytest.mark.asyncio
    async def test_suspect_opencv_nao_confirma_nao_chama_bedrock(
        self,
        monitor_with_escalation,
        mock_opencv_analyzer,
        mock_bedrock_client,
    ):
        """Se OpenCV NÃO confirma anomalia, Bedrock NÃO deve ser acionado."""
        # OpenCV retorna sem anomalia (default do mock)
        report = _make_report(ChannelHealthStatus.SUSPECT)

        result = await monitor_with_escalation._escalate_channel(
            ChannelHealthStatus.SUSPECT, report
        )

        mock_bedrock_client.diagnose_frame.assert_not_called()
        assert result.escalated_to_bedrock is False

    @pytest.mark.asyncio
    async def test_suspect_opencv_confirma_chama_bedrock(
        self,
        monitor_with_escalation,
        mock_opencv_analyzer,
        mock_bedrock_client,
    ):
        """Se OpenCV CONFIRMA anomalia, Bedrock DEVE ser acionado."""
        # Configurar OpenCV para detectar tela preta
        mock_opencv_analyzer.detect_black_screen.return_value = (
            FakeBlackScreenResult(is_black_screen=True)
        )

        report = _make_report(ChannelHealthStatus.SUSPECT)

        result = await monitor_with_escalation._escalate_channel(
            ChannelHealthStatus.SUSPECT, report
        )

        mock_bedrock_client.diagnose_frame.assert_called_once()
        assert result.escalated_to_bedrock is True


# =============================================================================
# Testes: Canal DEGRADED/CRITICAL — OpenCV + Bedrock (Req 14.3)
# =============================================================================


class TestEscalacaoDegradedCritical:
    """Testes para canais DEGRADED e CRITICAL no pipeline."""

    @pytest.mark.asyncio
    async def test_degraded_captura_frames_adicionais(
        self, monitor_with_escalation, mock_frame_capturer
    ):
        """Canal DEGRADED deve capturar frames adicionais."""
        report = _make_report(ChannelHealthStatus.DEGRADED)

        await monitor_with_escalation._escalate_channel(
            ChannelHealthStatus.DEGRADED, report
        )

        mock_frame_capturer.capture_sequence.assert_called_once()

    @pytest.mark.asyncio
    async def test_critical_captura_frames_adicionais(
        self, monitor_with_escalation, mock_frame_capturer
    ):
        """Canal CRITICAL deve capturar frames adicionais."""
        report = _make_report(ChannelHealthStatus.CRITICAL)

        await monitor_with_escalation._escalate_channel(
            ChannelHealthStatus.CRITICAL, report
        )

        mock_frame_capturer.capture_sequence.assert_called_once()

    @pytest.mark.asyncio
    async def test_degraded_opencv_confirma_escala_bedrock(
        self,
        monitor_with_escalation,
        mock_opencv_analyzer,
        mock_bedrock_client,
    ):
        """Canal DEGRADED com OpenCV confirmando deve escalar para Bedrock."""
        mock_opencv_analyzer.detect_black_screen.return_value = (
            FakeBlackScreenResult(is_black_screen=True)
        )

        report = _make_report(ChannelHealthStatus.DEGRADED)

        result = await monitor_with_escalation._escalate_channel(
            ChannelHealthStatus.DEGRADED, report
        )

        assert result.escalated_to_opencv is True
        assert result.escalated_to_bedrock is True
        mock_bedrock_client.diagnose_frame.assert_called_once()

    @pytest.mark.asyncio
    async def test_critical_opencv_nao_confirma_nao_escala_bedrock(
        self,
        monitor_with_escalation,
        mock_opencv_analyzer,
        mock_bedrock_client,
    ):
        """Canal CRITICAL sem confirmação OpenCV NÃO deve escalar Bedrock."""
        # OpenCV não confirma anomalia (default)
        report = _make_report(ChannelHealthStatus.CRITICAL)

        result = await monitor_with_escalation._escalate_channel(
            ChannelHealthStatus.CRITICAL, report
        )

        assert result.escalated_to_opencv is True
        assert result.escalated_to_bedrock is False
        mock_bedrock_client.diagnose_frame.assert_not_called()


# =============================================================================
# Testes: Sem dependências de escalação
# =============================================================================


class TestEscalacaoSemDependencias:
    """Testes para cenários sem dependências opcionais."""

    @pytest.mark.asyncio
    async def test_sem_frame_capturer_nao_escala(
        self, monitor_sem_dependencias
    ):
        """Sem frame_capturer, escalação deve ser desativada."""
        report = _make_report(ChannelHealthStatus.SUSPECT)

        result = await monitor_sem_dependencias._escalate_channel(
            ChannelHealthStatus.SUSPECT, report
        )

        assert result.escalated_to_opencv is False
        assert result.escalated_to_bedrock is False

    @pytest.mark.asyncio
    async def test_sem_opencv_limita_a_captura(
        self, mock_capability_map, mock_page, mock_frame_capturer
    ):
        """Sem opencv_analyzer, escalação limita-se à captura de frames."""
        config = {"observation_period_s": 0.1, "telemetry_interval_s": 0.05}
        monitor = ChannelMonitor(
            capability_map=mock_capability_map,
            page=mock_page,
            config=config,
            frame_capturer=mock_frame_capturer,
            opencv_analyzer=None,
            bedrock_client=None,
        )

        report = _make_report(ChannelHealthStatus.SUSPECT)
        result = await monitor._escalate_channel(
            ChannelHealthStatus.SUSPECT, report
        )

        # Frames foram capturados mas OpenCV não acionado
        mock_frame_capturer.capture_sequence.assert_called_once()
        assert result.escalated_to_opencv is False
        assert result.escalated_to_bedrock is False

    @pytest.mark.asyncio
    async def test_sem_bedrock_limita_a_opencv(
        self,
        mock_capability_map,
        mock_page,
        mock_frame_capturer,
        mock_opencv_analyzer,
    ):
        """Sem bedrock_client, escalação limita-se a OpenCV."""
        mock_opencv_analyzer.detect_black_screen.return_value = (
            FakeBlackScreenResult(is_black_screen=True)
        )
        config = {"observation_period_s": 0.1, "telemetry_interval_s": 0.05}
        monitor = ChannelMonitor(
            capability_map=mock_capability_map,
            page=mock_page,
            config=config,
            frame_capturer=mock_frame_capturer,
            opencv_analyzer=mock_opencv_analyzer,
            bedrock_client=None,
        )

        report = _make_report(ChannelHealthStatus.SUSPECT)
        result = await monitor._escalate_channel(
            ChannelHealthStatus.SUSPECT, report
        )

        assert result.escalated_to_opencv is True
        assert result.escalated_to_bedrock is False


# =============================================================================
# Testes: Detecção de freeze (OpenCV com múltiplos frames)
# =============================================================================


class TestEscalacaoFreeze:
    """Testes para detecção de freeze via OpenCV."""

    @pytest.mark.asyncio
    async def test_opencv_detecta_freeze_escala_bedrock(
        self,
        monitor_with_escalation,
        mock_opencv_analyzer,
        mock_bedrock_client,
    ):
        """Se OpenCV detecta FREEZE_CONFIRMED, deve escalar para Bedrock."""
        # Black screen não detectado, mas freeze sim
        mock_opencv_analyzer.detect_black_screen.return_value = (
            FakeBlackScreenResult(is_black_screen=False)
        )
        mock_opencv_analyzer.detect_freeze.return_value = FakeFreezeResult(
            classification=FakeFreezeClassification(value="FREEZE_CONFIRMED")
        )

        report = _make_report(ChannelHealthStatus.SUSPECT)

        result = await monitor_with_escalation._escalate_channel(
            ChannelHealthStatus.SUSPECT, report
        )

        assert result.escalated_to_opencv is True
        assert result.escalated_to_bedrock is True
        mock_bedrock_client.diagnose_frame.assert_called_once()


# =============================================================================
# Testes: Tratamento de erros na escalação
# =============================================================================


class TestEscalacaoErros:
    """Testes para tratamento de erros no pipeline de escalação."""

    @pytest.mark.asyncio
    async def test_erro_captura_frame_nao_propaga(
        self, monitor_with_escalation, mock_frame_capturer
    ):
        """Erro na captura de frame não deve propagar exceção."""
        mock_frame_capturer.capture_frame.side_effect = RuntimeError(
            "falha na captura"
        )

        report = _make_report(ChannelHealthStatus.HEALTHY)
        # Não deve lançar exceção
        result = await monitor_with_escalation._escalate_channel(
            ChannelHealthStatus.HEALTHY, report
        )

        assert result.escalated_to_opencv is False
        assert result.escalated_to_bedrock is False

    @pytest.mark.asyncio
    async def test_erro_capture_sequence_nao_propaga(
        self, monitor_with_escalation, mock_frame_capturer
    ):
        """Erro na captura de sequência não deve propagar exceção."""
        mock_frame_capturer.capture_sequence.side_effect = RuntimeError(
            "falha na sequência"
        )

        report = _make_report(ChannelHealthStatus.SUSPECT)
        result = await monitor_with_escalation._escalate_channel(
            ChannelHealthStatus.SUSPECT, report
        )

        # Deve retornar report sem marcação
        assert result.escalated_to_opencv is False
        assert result.escalated_to_bedrock is False

    @pytest.mark.asyncio
    async def test_erro_bedrock_marca_escalacao(
        self,
        monitor_with_escalation,
        mock_opencv_analyzer,
        mock_bedrock_client,
    ):
        """Erro no Bedrock deve marcar escalated_to_bedrock mesmo assim."""
        mock_opencv_analyzer.detect_black_screen.return_value = (
            FakeBlackScreenResult(is_black_screen=True)
        )
        mock_bedrock_client.diagnose_frame.side_effect = RuntimeError(
            "Bedrock timeout"
        )

        report = _make_report(ChannelHealthStatus.SUSPECT)
        result = await monitor_with_escalation._escalate_channel(
            ChannelHealthStatus.SUSPECT, report
        )

        assert result.escalated_to_opencv is True
        assert result.escalated_to_bedrock is True


# =============================================================================
# Testes: Configuração de escalação
# =============================================================================


class TestEscalacaoConfiguracao:
    """Testes de configuração do pipeline de escalação."""

    def test_frame_count_configuravel(
        self, mock_capability_map, mock_page, mock_frame_capturer
    ):
        """Número de frames na escalação deve ser configurável."""
        config = {
            "observation_period_s": 0.1,
            "escalation_frame_count": 5,
            "escalation_frame_interval": 1.0,
        }
        monitor = ChannelMonitor(
            capability_map=mock_capability_map,
            page=mock_page,
            config=config,
            frame_capturer=mock_frame_capturer,
        )
        assert monitor._escalation_frame_count == 5
        assert monitor._escalation_frame_interval == 1.0

    def test_frame_count_padrao(
        self, mock_capability_map, mock_page, mock_frame_capturer
    ):
        """Configuração padrão: 3 frames com intervalo 2.0s."""
        monitor = ChannelMonitor(
            capability_map=mock_capability_map,
            page=mock_page,
            frame_capturer=mock_frame_capturer,
        )
        assert monitor._escalation_frame_count == 3
        assert monitor._escalation_frame_interval == 2.0

    def test_dependencias_opcionais_inicializam_none(
        self, mock_capability_map, mock_page
    ):
        """Dependências opcionais devem ser None por padrão."""
        monitor = ChannelMonitor(
            capability_map=mock_capability_map,
            page=mock_page,
        )
        assert monitor._frame_capturer is None
        assert monitor._opencv_analyzer is None
        assert monitor._bedrock_client is None

    def test_dependencias_opcionais_aceitam_instancia(
        self,
        mock_capability_map,
        mock_page,
        mock_frame_capturer,
        mock_opencv_analyzer,
        mock_bedrock_client,
    ):
        """Dependências opcionais devem aceitar instâncias."""
        monitor = ChannelMonitor(
            capability_map=mock_capability_map,
            page=mock_page,
            frame_capturer=mock_frame_capturer,
            opencv_analyzer=mock_opencv_analyzer,
            bedrock_client=mock_bedrock_client,
        )
        assert monitor._frame_capturer is mock_frame_capturer
        assert monitor._opencv_analyzer is mock_opencv_analyzer
        assert monitor._bedrock_client is mock_bedrock_client


# =============================================================================
# Testes: Integração com monitor_channel
# =============================================================================


class TestEscalacaoIntegracaoMonitorChannel:
    """Testes verificando que _escalate_channel é chamado por monitor_channel."""

    @pytest.mark.asyncio
    async def test_monitor_channel_chama_escalacao(
        self, monitor_with_escalation, mock_frame_capturer
    ):
        """monitor_channel deve invocar _escalate_channel após classificar."""
        report = await monitor_with_escalation.monitor_channel(
            "https://example.com/channel/test"
        )

        # Para um canal saudável (mock retorna valores ok),
        # deve capturar 1 frame de validação
        # Note: os mocks do probe retornam dados saudáveis por padrão
        assert isinstance(report, ChannelReport)
        # Frame capturer foi chamado (indicando escalação executou)
        assert mock_frame_capturer.capture_frame.called or \
               mock_frame_capturer.capture_sequence.called


# =============================================================================
# Testes: _analyze_frames_with_opencv
# =============================================================================


class TestAnalyzeFramesWithOpenCV:
    """Testes para o método auxiliar _analyze_frames_with_opencv."""

    def test_frames_vazio_retorna_false(self, monitor_with_escalation):
        """Lista vazia de frames deve retornar False."""
        result = monitor_with_escalation._analyze_frames_with_opencv([])
        assert result is False

    def test_sem_opencv_retorna_false(self, monitor_sem_dependencias):
        """Sem opencv_analyzer deve retornar False."""
        frames = [FakeFrameResult(data=b"\x00" * 100)]
        result = monitor_sem_dependencias._analyze_frames_with_opencv(frames)
        assert result is False

    def test_frame_sem_data_pula(self, monitor_with_escalation):
        """Frames sem data devem ser ignorados."""
        frame_sem_data = FakeFrameResult(data=b"")
        result = monitor_with_escalation._analyze_frames_with_opencv(
            [frame_sem_data]
        )
        assert result is False

    def test_frame_invalido_pula(self, monitor_with_escalation):
        """Frames marcados como inválidos devem ser ignorados."""
        frame_invalido = FakeFrameResult(
            data=b"\x00" * 100, is_valid=False
        )
        result = monitor_with_escalation._analyze_frames_with_opencv(
            [frame_invalido]
        )
        assert result is False


# =============================================================================
# Testes: _get_first_valid_frame_data
# =============================================================================


class TestGetFirstValidFrameData:
    """Testes para o método auxiliar _get_first_valid_frame_data."""

    def test_retorna_primeiro_frame_valido(self, monitor_with_escalation):
        """Deve retornar dados do primeiro frame válido."""
        frames = [
            FakeFrameResult(data=b"frame_1", is_valid=True),
            FakeFrameResult(data=b"frame_2", is_valid=True),
        ]
        result = monitor_with_escalation._get_first_valid_frame_data(frames)
        assert result == b"frame_1"

    def test_pula_frames_invalidos(self, monitor_with_escalation):
        """Deve pular frames inválidos e retornar o primeiro válido."""
        frames = [
            FakeFrameResult(data=b"frame_1", is_valid=False),
            FakeFrameResult(data=b"frame_2", is_valid=True),
        ]
        result = monitor_with_escalation._get_first_valid_frame_data(frames)
        assert result == b"frame_2"

    def test_lista_vazia_retorna_none(self, monitor_with_escalation):
        """Lista vazia deve retornar None."""
        result = monitor_with_escalation._get_first_valid_frame_data([])
        assert result is None

    def test_todos_invalidos_retorna_none(self, monitor_with_escalation):
        """Se todos os frames são inválidos, retorna None."""
        frames = [
            FakeFrameResult(data=b"frame_1", is_valid=False),
            FakeFrameResult(data=b"frame_2", is_valid=False),
        ]
        result = monitor_with_escalation._get_first_valid_frame_data(frames)
        assert result is None

    def test_frame_sem_data_retorna_none(self, monitor_with_escalation):
        """Frame sem data deve ser tratado como inválido."""
        frames = [FakeFrameResult(data=b"")]
        result = monitor_with_escalation._get_first_valid_frame_data(frames)
        assert result is None
