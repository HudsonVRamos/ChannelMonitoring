"""Testes de integração do Player Discovery.

Verificam o fluxo end-to-end com mocks de Playwright Page:
1. Fluxo completo: discovery → capabilities → rotação de 3 canais
2. Re-discovery acionado por MutationObserver (mudança estrutural)
3. Escalação: telemetria SUSPECT → OpenCV → Bedrock
4. Testes funcionais executando na rotação correta
5. Canal HEALTHY não aciona OpenCV/Bedrock

Requirements: 1.1, 4.3, 10.1, 14.1
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from src.player_discovery.main import PlayerDiscoveryOrchestrator
from src.player_discovery.models.capability import (
    Capability,
    CapabilityMapData,
    InteractionStrategy,
    PlayerInfo,
)
from src.player_discovery.models.capability_map import CapabilityMap
from src.player_discovery.models.enums import (
    AudioStatus,
    BufferStatus,
    ChannelHealthStatus,
    FunctionalTestStatus,
    InteractionLevel,
)
from src.player_discovery.models.results import (
    ChannelReport,
    FunctionalTestResult,
    HealthScores,
)
from src.player_discovery.models.telemetry import (
    AudioTelemetry,
    BufferTelemetry,
    SubtitleTelemetry,
    VideoTelemetry,
)
from src.player_discovery.monitoring.channel_monitor import (
    ChannelMonitor,
)


# =============================================================================
# Helpers e Fixtures
# =============================================================================


def _build_valid_capability_map() -> CapabilityMap:
    """Constrói um CapabilityMap válido com todas as capabilities."""
    capabilities = {}
    required = [
        "play", "pause", "mute", "unmute", "audio_selection",
        "subtitle_selection", "quality_selection", "fullscreen",
        "settings",
    ]
    for name in required:
        capabilities[name] = Capability(
            name=name,
            available=True,
            confidence=0.95,
            evidence=[f"teste comportamental confirmou {name}"],
            interaction_strategy=InteractionLevel.PLAYER_API,
            strategies=[
                InteractionStrategy(
                    level=InteractionLevel.PLAYER_API,
                    type="player_api",
                    details={"method": f"player.{name}()"},
                ),
                InteractionStrategy(
                    level=InteractionLevel.SEMANTIC_DOM,
                    type="semantic_dom",
                    details={"role": "button", "aria_label": name},
                ),
            ],
        )

    data = CapabilityMapData(
        player_info=PlayerInfo(
            library="skyplus-player",
            version="3.2.1",
            video_elements=["video#main"],
            discovered_at="2024-01-01T00:00:00.000Z",
        ),
        capabilities=capabilities,
        discovery_duration_ms=12000,
        version_hash="abc123hash",
        valid=True,
    )
    return CapabilityMap(data)


def _mock_page() -> MagicMock:
    """Cria mock de Playwright Page com métodos essenciais."""
    page = MagicMock()
    page.goto = AsyncMock(return_value=None)
    page.evaluate = AsyncMock(return_value=None)
    page.expose_function = AsyncMock(return_value=None)
    page.wait_for_selector = AsyncMock(return_value=None)
    return page


def _healthy_video_telemetry() -> VideoTelemetry:
    """Retorna telemetria de vídeo saudável."""
    return VideoTelemetry(
        current_time=120.5,
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
        total_frames=3600,
        dropped_frames=5,
        drop_rate=0.0014,
        fps_avg=30.0,
    )


def _healthy_audio_telemetry() -> AudioTelemetry:
    """Retorna telemetria de áudio saudável."""
    return AudioTelemetry(
        rms=0.25,
        peak=0.5,
        silence_duration=0.0,
        muted=False,
        status=AudioStatus.OK,
        tracks_available=["por", "eng"],
    )


def _healthy_buffer_telemetry() -> BufferTelemetry:
    """Retorna telemetria de buffer saudável."""
    return BufferTelemetry(
        buffered_start=100.0,
        buffered_end=135.0,
        buffer_ahead=15.0,
        waiting_count=0,
        waiting_total_ms=0.0,
        longest_wait_ms=0.0,
        time_since_last_wait=None,
        status=BufferStatus.OK,
    )


def _suspect_audio_telemetry() -> AudioTelemetry:
    """Retorna telemetria de áudio SUSPECT (AUDIO_LOW)."""
    return AudioTelemetry(
        rms=0.03,
        peak=0.04,
        silence_duration=8.0,
        muted=False,
        status=AudioStatus.AUDIO_LOW,
        tracks_available=["por"],
    )


@dataclass
class FakeFrameResult:
    """Frame simulado para testes de escalação."""

    data: bytes
    width: int = 1920
    height: int = 1080
    is_valid: bool = True
    timestamp: str = "2024-01-01T00:00:05.000Z"


@dataclass
class FakeBlackScreenResult:
    """Resultado de detecção de tela preta."""

    is_black_screen: bool
    is_dark_scene: bool = False


@dataclass
class FakeFreezeClassification:
    """Classificação de freeze."""

    value: str


@dataclass
class FakeFreezeResult:
    """Resultado de detecção de freeze."""

    classification: FakeFreezeClassification
    similarity: float = 0.99


def _create_valid_png_bytes() -> bytes:
    """Cria bytes PNG válidos para testes de escalação."""
    import cv2
    img = np.full((100, 100, 3), 128, dtype=np.uint8)
    success, buffer = cv2.imencode(".png", img)
    assert success
    return buffer.tobytes()


def _create_black_png_bytes() -> bytes:
    """Cria bytes PNG de tela preta para testes."""
    import cv2
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    success, buffer = cv2.imencode(".png", img)
    assert success
    return buffer.tobytes()


# =============================================================================
# Teste 1: Fluxo completo discovery → capabilities → rotação 3 canais
# =============================================================================


class TestFullFlowIntegration:
    """Testa o fluxo end-to-end do PlayerDiscoveryOrchestrator."""

    @pytest.mark.asyncio
    async def test_full_flow_discovery_to_rotation(self) -> None:
        """Fluxo completo: discovery produz CapabilityMap →
        rotação monitora 3 canais → produz ChannelReports.

        Validates: Requirements 1.1, 10.1
        """
        page = _mock_page()
        capability_map = _build_valid_capability_map()
        channels = [
            "https://skyplus.com/channel/globo",
            "https://skyplus.com/channel/sbt",
            "https://skyplus.com/channel/record",
        ]

        orchestrator = PlayerDiscoveryOrchestrator(
            page=page,
            config={
                "observation_period_s": 0.01,
                "telemetry_interval_s": 0.005,
                "functional_test_interval": 100,
                "debounce_window_ms": 50,
            },
        )

        # Mock DiscoveryEngine
        orchestrator._discovery_engine = MagicMock()
        orchestrator._discovery_engine.discover = AsyncMock(
            return_value=capability_map
        )

        # Mock MutationObserverWatcher
        orchestrator._mutation_watcher = MagicMock()
        orchestrator._mutation_watcher.start = AsyncMock()
        orchestrator._mutation_watcher.on_structural_change = (
            MagicMock()
        )

        # Mock ChannelMonitor para simular rotação com relatórios
        mock_reports = [
            ChannelReport(
                channel_id="globo",
                channel_url=channels[0],
                status=ChannelHealthStatus.HEALTHY,
                health_scores=HealthScores(90.0, 85.0, 0.0),
                video_telemetry=_healthy_video_telemetry(),
                audio_telemetry=_healthy_audio_telemetry(),
                subtitle_telemetry=SubtitleTelemetry(),
                buffer_telemetry=_healthy_buffer_telemetry(),
                events=[],
                functional_tests=[],
                observation_duration_ms=300,
            ),
            ChannelReport(
                channel_id="sbt",
                channel_url=channels[1],
                status=ChannelHealthStatus.HEALTHY,
                health_scores=HealthScores(88.0, 82.0, 0.0),
                video_telemetry=_healthy_video_telemetry(),
                audio_telemetry=_healthy_audio_telemetry(),
                subtitle_telemetry=SubtitleTelemetry(),
                buffer_telemetry=_healthy_buffer_telemetry(),
                events=[],
                functional_tests=[],
                observation_duration_ms=280,
            ),
            ChannelReport(
                channel_id="record",
                channel_url=channels[2],
                status=ChannelHealthStatus.HEALTHY,
                health_scores=HealthScores(92.0, 87.0, 0.0),
                video_telemetry=_healthy_video_telemetry(),
                audio_telemetry=_healthy_audio_telemetry(),
                subtitle_telemetry=SubtitleTelemetry(),
                buffer_telemetry=_healthy_buffer_telemetry(),
                events=[],
                functional_tests=[],
                observation_duration_ms=310,
            ),
        ]

        with patch(
            "src.player_discovery.main.ChannelMonitor"
        ) as MockMonitor:
            mock_monitor_instance = MagicMock()
            mock_monitor_instance.start_rotation = AsyncMock(
                return_value=mock_reports
            )
            MockMonitor.return_value = mock_monitor_instance

            await orchestrator.start(page, channels)

        # Verificações
        # 1. Discovery foi executado uma vez
        orchestrator._discovery_engine.discover.assert_awaited_once()

        # 2. CapabilityMap foi gerado
        assert orchestrator.capability_map is capability_map
        assert orchestrator.capability_map.is_valid()

        # 3. MutationObserverWatcher foi inicializado
        orchestrator._mutation_watcher.start.assert_awaited_once()

        # 4. ChannelMonitor recebeu o CapabilityMap
        call_kwargs = MockMonitor.call_args[1]
        assert call_kwargs["capability_map"] is capability_map

        # 5. Rotação foi iniciada com os 3 canais
        mock_monitor_instance.start_rotation.assert_awaited_once_with(
            channels
        )

    @pytest.mark.asyncio
    async def test_channel_monitor_produces_reports(self) -> None:
        """ChannelMonitor produz relatórios para cada canal na rotação.

        Testa diretamente o ChannelMonitor com mocks das probes para
        verificar que cada canal na rotação gera um ChannelReport.

        Validates: Requirements 10.1, 10.2
        """
        page = _mock_page()
        capability_map = _build_valid_capability_map()
        channels = [
            "https://skyplus.com/channel/globo",
            "https://skyplus.com/channel/sbt",
            "https://skyplus.com/channel/record",
        ]

        monitor = ChannelMonitor(
            capability_map=capability_map,
            page=page,
            config={
                "observation_period_s": 0.01,
                "telemetry_interval_s": 0.005,
                "functional_test_interval": 100,
                "invalidation_threshold": 3,
            },
        )

        # Mock das probes para retornar telemetria saudável
        monitor._video_probe.collect = AsyncMock(
            return_value=_healthy_video_telemetry()
        )
        monitor._audio_probe.collect = AsyncMock(
            return_value=_healthy_audio_telemetry()
        )
        monitor._buffer_probe.collect = AsyncMock(
            return_value=_healthy_buffer_telemetry()
        )
        monitor._subtitle_probe.collect = AsyncMock(
            return_value=SubtitleTelemetry()
        )
        monitor._event_probe.attach_listeners = AsyncMock()
        monitor._event_probe.get_events = AsyncMock(return_value=[])
        monitor._event_probe.clear_events = AsyncMock()

        reports = await monitor.start_rotation(channels)

        # 3 canais → 3 relatórios
        assert len(reports) == 3
        assert all(
            isinstance(r, ChannelReport) for r in reports
        )
        # Todos saudáveis
        assert all(
            r.status == ChannelHealthStatus.HEALTHY for r in reports
        )
        # Cada relatório tem o canal correto
        assert reports[0].channel_id == "globo"
        assert reports[1].channel_id == "sbt"
        assert reports[2].channel_id == "record"
        # Navegação foi chamada para cada canal
        assert page.goto.await_count == 3


# =============================================================================
# Teste 2: Re-discovery acionado por MutationObserver
# =============================================================================


class TestRediscoveryIntegration:
    """Testa o fluxo de re-discovery via mudança estrutural."""

    @pytest.mark.asyncio
    async def test_structural_change_triggers_rediscovery(
        self,
    ) -> None:
        """Mudança estrutural no DOM dispara re-discovery e produz
        novo CapabilityMap.

        Validates: Requirements 4.3
        """
        page = _mock_page()
        old_map = _build_valid_capability_map()
        new_map = _build_valid_capability_map()
        # Alterar hash para diferenciar os mapas
        new_map._data.version_hash = "new_hash_456"

        orchestrator = PlayerDiscoveryOrchestrator(page=page)
        orchestrator._capability_map = old_map
        orchestrator._running = True

        # Mock DiscoveryEngine.rediscover para retornar novo mapa
        orchestrator._discovery_engine = MagicMock()
        orchestrator._discovery_engine.rediscover = AsyncMock(
            return_value=new_map
        )

        # Mock MutationObserverWatcher
        orchestrator._mutation_watcher = MagicMock()
        orchestrator._mutation_watcher.stop = AsyncMock()
        orchestrator._mutation_watcher.start = AsyncMock()

        # Simular ChannelMonitor existente
        mock_monitor = MagicMock()
        orchestrator._channel_monitor = mock_monitor

        # Executar re-discovery (simula callback de mudança estrutural)
        await orchestrator._handle_rediscovery()

        # Verificações
        # 1. Rediscover foi chamado
        orchestrator._discovery_engine.rediscover.assert_awaited_once()

        # 2. CapabilityMap foi atualizado
        assert orchestrator.capability_map is new_map
        assert (
            orchestrator.capability_map.version_hash == "new_hash_456"
        )

        # 3. MutationWatcher foi reiniciado com novo mapa
        orchestrator._mutation_watcher.stop.assert_awaited_once()
        orchestrator._mutation_watcher.start.assert_awaited_once_with(
            page, new_map
        )

        # 4. ChannelMonitor recebeu o novo mapa
        assert mock_monitor._capability_map is new_map

    @pytest.mark.asyncio
    async def test_on_structural_change_schedules_rediscovery(
        self,
    ) -> None:
        """Callback _on_structural_change agenda _handle_rediscovery.

        Validates: Requirements 4.3
        """
        page = _mock_page()
        capability_map = _build_valid_capability_map()

        orchestrator = PlayerDiscoveryOrchestrator(page=page)
        orchestrator._capability_map = capability_map
        orchestrator._running = True

        # Substituir _handle_rediscovery por mock para verificar chamada
        mock_rediscovery = AsyncMock()
        orchestrator._handle_rediscovery = mock_rediscovery

        # Chamar _on_structural_change dentro de um event loop ativo
        # Isso deve agendar a task de re-discovery
        orchestrator._on_structural_change()

        # Aguardar para que a task agendada execute
        await asyncio.sleep(0.05)

        # Verificar que _handle_rediscovery foi agendado/executado
        mock_rediscovery.assert_awaited_once()


# =============================================================================
# Teste 3: Escalação — telemetria SUSPECT → OpenCV → Bedrock
# =============================================================================


class TestEscalationPipelineIntegration:
    """Testa pipeline de escalação determinística."""

    @pytest.mark.asyncio
    async def test_suspect_channel_escalates_to_opencv_then_bedrock(
        self,
    ) -> None:
        """Canal SUSPECT captura frames → OpenCV confirma anomalia →
        Bedrock é acionado para diagnóstico.

        Validates: Requirements 14.1
        """
        page = _mock_page()
        capability_map = _build_valid_capability_map()

        # Mocks de dependências externas
        frame_capturer = MagicMock()
        black_frame_data = _create_black_png_bytes()
        fake_frames = [
            FakeFrameResult(data=black_frame_data),
            FakeFrameResult(data=black_frame_data),
            FakeFrameResult(data=black_frame_data),
        ]
        frame_capturer.capture_frame = AsyncMock(
            return_value=fake_frames[0]
        )
        frame_capturer.capture_sequence = AsyncMock(
            return_value=fake_frames
        )

        opencv_analyzer = MagicMock()
        # OpenCV detecta tela preta → confirma anomalia
        opencv_analyzer.detect_black_screen = MagicMock(
            return_value=FakeBlackScreenResult(is_black_screen=True)
        )
        opencv_analyzer.detect_freeze = MagicMock(
            return_value=FakeFreezeResult(
                classification=FakeFreezeClassification("NO_FREEZE")
            )
        )

        bedrock_client = MagicMock()
        bedrock_client.diagnose_frame = AsyncMock(
            return_value={"diagnosis": "tela preta detectada"}
        )

        monitor = ChannelMonitor(
            capability_map=capability_map,
            page=page,
            config={
                "observation_period_s": 0.01,
                "telemetry_interval_s": 0.005,
                "functional_test_interval": 100,
                "invalidation_threshold": 3,
            },
            frame_capturer=frame_capturer,
            opencv_analyzer=opencv_analyzer,
            bedrock_client=bedrock_client,
        )

        # Mock probes: áudio retorna AUDIO_LOW → canal SUSPECT
        monitor._video_probe.collect = AsyncMock(
            return_value=_healthy_video_telemetry()
        )
        monitor._audio_probe.collect = AsyncMock(
            return_value=_suspect_audio_telemetry()
        )
        monitor._buffer_probe.collect = AsyncMock(
            return_value=_healthy_buffer_telemetry()
        )
        monitor._subtitle_probe.collect = AsyncMock(
            return_value=SubtitleTelemetry()
        )
        monitor._event_probe.attach_listeners = AsyncMock()
        monitor._event_probe.get_events = AsyncMock(return_value=[])
        monitor._event_probe.clear_events = AsyncMock()

        report = await monitor.monitor_channel(
            "https://skyplus.com/channel/globo"
        )

        # Verificações
        # 1. Canal classificado como SUSPECT
        assert report.status == ChannelHealthStatus.SUSPECT

        # 2. Frames foram capturados (sequência para SUSPECT)
        frame_capturer.capture_sequence.assert_awaited_once()

        # 3. OpenCV foi acionado
        assert report.escalated_to_opencv is True
        opencv_analyzer.detect_black_screen.assert_called()

        # 4. Bedrock foi acionado (pois OpenCV confirmou anomalia)
        assert report.escalated_to_bedrock is True
        bedrock_client.diagnose_frame.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_suspect_channel_opencv_no_anomaly_no_bedrock(
        self,
    ) -> None:
        """Canal SUSPECT → OpenCV NÃO confirma anomalia → Bedrock
        NÃO é acionado.

        Validates: Requirements 14.1
        """
        page = _mock_page()
        capability_map = _build_valid_capability_map()

        frame_capturer = MagicMock()
        normal_frame_data = _create_valid_png_bytes()
        fake_frames = [
            FakeFrameResult(data=normal_frame_data),
            FakeFrameResult(data=normal_frame_data),
            FakeFrameResult(data=normal_frame_data),
        ]
        frame_capturer.capture_frame = AsyncMock(
            return_value=fake_frames[0]
        )
        frame_capturer.capture_sequence = AsyncMock(
            return_value=fake_frames
        )

        opencv_analyzer = MagicMock()
        # OpenCV NÃO detecta tela preta → não confirma anomalia
        opencv_analyzer.detect_black_screen = MagicMock(
            return_value=FakeBlackScreenResult(is_black_screen=False)
        )
        opencv_analyzer.detect_freeze = MagicMock(
            return_value=FakeFreezeResult(
                classification=FakeFreezeClassification("NO_FREEZE")
            )
        )

        bedrock_client = MagicMock()
        bedrock_client.diagnose_frame = AsyncMock()

        monitor = ChannelMonitor(
            capability_map=capability_map,
            page=page,
            config={
                "observation_period_s": 0.01,
                "telemetry_interval_s": 0.005,
                "functional_test_interval": 100,
                "invalidation_threshold": 3,
            },
            frame_capturer=frame_capturer,
            opencv_analyzer=opencv_analyzer,
            bedrock_client=bedrock_client,
        )

        # Canal SUSPECT via áudio baixo
        monitor._video_probe.collect = AsyncMock(
            return_value=_healthy_video_telemetry()
        )
        monitor._audio_probe.collect = AsyncMock(
            return_value=_suspect_audio_telemetry()
        )
        monitor._buffer_probe.collect = AsyncMock(
            return_value=_healthy_buffer_telemetry()
        )
        monitor._subtitle_probe.collect = AsyncMock(
            return_value=SubtitleTelemetry()
        )
        monitor._event_probe.attach_listeners = AsyncMock()
        monitor._event_probe.get_events = AsyncMock(return_value=[])
        monitor._event_probe.clear_events = AsyncMock()

        report = await monitor.monitor_channel(
            "https://skyplus.com/channel/sbt"
        )

        # Verificações
        assert report.status == ChannelHealthStatus.SUSPECT
        # OpenCV foi acionado
        assert report.escalated_to_opencv is True
        # Bedrock NÃO foi acionado (Req 14.4)
        assert report.escalated_to_bedrock is False
        bedrock_client.diagnose_frame.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_healthy_channel_no_opencv_no_bedrock(
        self,
    ) -> None:
        """Canal HEALTHY captura apenas 1 frame de validação,
        sem acionar OpenCV nem Bedrock.

        Validates: Requirements 14.1
        """
        page = _mock_page()
        capability_map = _build_valid_capability_map()

        frame_capturer = MagicMock()
        frame_capturer.capture_frame = AsyncMock(
            return_value=FakeFrameResult(
                data=_create_valid_png_bytes()
            )
        )
        frame_capturer.capture_sequence = AsyncMock()

        opencv_analyzer = MagicMock()
        bedrock_client = MagicMock()
        bedrock_client.diagnose_frame = AsyncMock()

        monitor = ChannelMonitor(
            capability_map=capability_map,
            page=page,
            config={
                "observation_period_s": 0.01,
                "telemetry_interval_s": 0.005,
                "functional_test_interval": 100,
                "invalidation_threshold": 3,
            },
            frame_capturer=frame_capturer,
            opencv_analyzer=opencv_analyzer,
            bedrock_client=bedrock_client,
        )

        # Canal totalmente saudável
        monitor._video_probe.collect = AsyncMock(
            return_value=_healthy_video_telemetry()
        )
        monitor._audio_probe.collect = AsyncMock(
            return_value=_healthy_audio_telemetry()
        )
        monitor._buffer_probe.collect = AsyncMock(
            return_value=_healthy_buffer_telemetry()
        )
        monitor._subtitle_probe.collect = AsyncMock(
            return_value=SubtitleTelemetry()
        )
        monitor._event_probe.attach_listeners = AsyncMock()
        monitor._event_probe.get_events = AsyncMock(return_value=[])
        monitor._event_probe.clear_events = AsyncMock()

        report = await monitor.monitor_channel(
            "https://skyplus.com/channel/globo"
        )

        # HEALTHY: apenas 1 frame de validação
        assert report.status == ChannelHealthStatus.HEALTHY
        frame_capturer.capture_frame.assert_awaited_once()
        # Sequência de frames NÃO capturada
        frame_capturer.capture_sequence.assert_not_awaited()
        # OpenCV e Bedrock NÃO acionados
        assert report.escalated_to_opencv is False
        assert report.escalated_to_bedrock is False
        bedrock_client.diagnose_frame.assert_not_awaited()


# =============================================================================
# Teste 4: Testes funcionais na rotação correta
# =============================================================================


class TestFunctionalTestsIntegration:
    """Testa a execução periódica de testes funcionais na rotação."""

    @pytest.mark.asyncio
    async def test_functional_tests_execute_every_n_rotations(
        self,
    ) -> None:
        """Testes funcionais executam a cada N rotações configurado.

        Com functional_test_interval=2, testes devem executar nas
        rotações 2, 4, 6, etc.

        Validates: Requirements 10.1, 14.1
        """
        page = _mock_page()
        capability_map = _build_valid_capability_map()
        channels = ["https://skyplus.com/channel/globo"]

        monitor = ChannelMonitor(
            capability_map=capability_map,
            page=page,
            config={
                "observation_period_s": 0.01,
                "telemetry_interval_s": 0.005,
                "functional_test_interval": 2,
                "invalidation_threshold": 3,
            },
        )

        # Mock probes
        monitor._video_probe.collect = AsyncMock(
            return_value=_healthy_video_telemetry()
        )
        monitor._audio_probe.collect = AsyncMock(
            return_value=_healthy_audio_telemetry()
        )
        monitor._buffer_probe.collect = AsyncMock(
            return_value=_healthy_buffer_telemetry()
        )
        monitor._subtitle_probe.collect = AsyncMock(
            return_value=SubtitleTelemetry()
        )
        monitor._event_probe.attach_listeners = AsyncMock()
        monitor._event_probe.get_events = AsyncMock(return_value=[])
        monitor._event_probe.clear_events = AsyncMock()

        # Mock run_functional_tests para rastrear chamadas
        mock_functional = AsyncMock(return_value=[
            FunctionalTestResult(
                capability="play_pause",
                status=FunctionalTestStatus.PASS,
                action_executed="pause → play",
                expected_result="player pausou e retomou",
                actual_result="play/pause ok",
                duration_ms=150,
            ),
        ])
        monitor.run_functional_tests = mock_functional

        # Rotação 1: NÃO executa testes funcionais
        await monitor.start_rotation(channels)
        assert monitor.rotation_count == 1
        mock_functional.assert_not_awaited()

        # Rotação 2: EXECUTA testes funcionais (múltiplo de 2)
        await monitor.start_rotation(channels)
        assert monitor.rotation_count == 2
        mock_functional.assert_awaited_once()

        # Rotação 3: NÃO executa testes funcionais
        mock_functional.reset_mock()
        await monitor.start_rotation(channels)
        assert monitor.rotation_count == 3
        mock_functional.assert_not_awaited()

        # Rotação 4: EXECUTA testes funcionais (múltiplo de 2)
        await monitor.start_rotation(channels)
        assert monitor.rotation_count == 4
        mock_functional.assert_awaited_once()

        # Rotação 5: NÃO executa
        mock_functional.reset_mock()
        await monitor.start_rotation(channels)
        assert monitor.rotation_count == 5
        mock_functional.assert_not_awaited()

        # Rotação 6: EXECUTA
        await monitor.start_rotation(channels)
        assert monitor.rotation_count == 6
        mock_functional.assert_awaited_once()
