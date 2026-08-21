"""Testes para o PlayerDiscoveryOrchestrator — Entry point principal.

Testa o fluxo de orquestração:
- Startup: discovery → capability map → mutation watcher → channel monitor
- Stop: para todos os componentes
- Integração com módulos existentes (FrameCapturer, OpenCV, Bedrock)
- Logging estruturado

Requirements: 1.1, 2.4, 3.1, 10.1, 14.1
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.player_discovery.main import PlayerDiscoveryOrchestrator
from src.player_discovery.models.capability import (
    Capability,
    CapabilityMapData,
    InteractionStrategy,
    PlayerInfo,
)
from src.player_discovery.models.capability_map import CapabilityMap
from src.player_discovery.models.enums import InteractionLevel


# =============================================================================
# Helpers
# =============================================================================


def _build_valid_capability_map() -> CapabilityMap:
    """Cria um CapabilityMap válido para testes."""
    capabilities = {}
    required = [
        "play", "pause", "mute", "unmute", "audio_selection",
        "subtitle_selection", "quality_selection", "fullscreen", "settings",
    ]
    for name in required:
        capabilities[name] = Capability(
            name=name,
            available=True,
            confidence=0.9,
            evidence=["test evidence"],
            interaction_strategy=InteractionLevel.PLAYER_API,
            strategies=[
                InteractionStrategy(
                    level=InteractionLevel.PLAYER_API,
                    type="player_api",
                    details={"method": f"player.{name}()"},
                )
            ],
        )

    data = CapabilityMapData(
        player_info=PlayerInfo(
            library="test-player",
            version="1.0.0",
            video_elements=["video"],
            discovered_at="2024-01-01T00:00:00.000Z",
        ),
        capabilities=capabilities,
        discovery_duration_ms=5000,
        version_hash="testhash123",
        valid=True,
    )
    return CapabilityMap(data)


# =============================================================================
# Testes de inicialização
# =============================================================================


class TestOrchestratorInit:
    """Testes de inicialização do orquestrador."""

    def test_init_default_config(self) -> None:
        """Orquestrador inicializa com configuração padrão."""
        page = MagicMock()
        orchestrator = PlayerDiscoveryOrchestrator(page=page)

        assert orchestrator.running is False
        assert orchestrator.capability_map is None
        assert orchestrator.channel_monitor is None

    def test_init_custom_config(self) -> None:
        """Orquestrador aceita configuração customizada."""
        page = MagicMock()
        config = {
            "discovery_timeout_s": 120,
            "observation_period_s": 60.0,
            "telemetry_interval_s": 5.0,
            "functional_test_interval": 10,
            "invalidation_threshold": 5,
            "debounce_window_ms": 1000,
            "log_level": "DEBUG",
        }
        orchestrator = PlayerDiscoveryOrchestrator(
            page=page, config=config
        )

        assert orchestrator.running is False

    def test_init_with_external_modules(self) -> None:
        """Orquestrador aceita módulos externos opcionais."""
        page = MagicMock()
        frame_capturer = MagicMock()
        opencv_analyzer = MagicMock()
        bedrock_client = MagicMock()

        orchestrator = PlayerDiscoveryOrchestrator(
            page=page,
            frame_capturer=frame_capturer,
            opencv_analyzer=opencv_analyzer,
            bedrock_client=bedrock_client,
        )

        assert orchestrator._frame_capturer is frame_capturer
        assert orchestrator._opencv_analyzer is opencv_analyzer
        assert orchestrator._bedrock_client is bedrock_client


# =============================================================================
# Testes do fluxo start()
# =============================================================================


class TestOrchestratorStart:
    """Testes do fluxo start() — discovery → monitoring."""

    @pytest.mark.asyncio
    async def test_start_executes_discovery(self) -> None:
        """start() executa DiscoveryEngine e produz CapabilityMap."""
        page = MagicMock()
        capability_map = _build_valid_capability_map()

        orchestrator = PlayerDiscoveryOrchestrator(page=page)

        # Mock do DiscoveryEngine
        orchestrator._discovery_engine = MagicMock()
        orchestrator._discovery_engine.discover = AsyncMock(
            return_value=capability_map
        )

        # Mock do MutationObserverWatcher
        orchestrator._mutation_watcher = MagicMock()
        orchestrator._mutation_watcher.start = AsyncMock()
        orchestrator._mutation_watcher.on_structural_change = MagicMock()

        # Mock do ChannelMonitor.start_rotation
        with patch(
            "src.player_discovery.main.ChannelMonitor"
        ) as MockMonitor:
            mock_monitor_instance = MagicMock()
            mock_monitor_instance.start_rotation = AsyncMock(return_value=[])
            MockMonitor.return_value = mock_monitor_instance

            await orchestrator.start(page, ["http://ch1.test"])

        # Verificar que discovery foi executado
        orchestrator._discovery_engine.discover.assert_awaited_once_with(page)
        assert orchestrator.capability_map is capability_map

    @pytest.mark.asyncio
    async def test_start_initializes_mutation_watcher(self) -> None:
        """start() inicializa MutationObserverWatcher com o mapa."""
        page = MagicMock()
        capability_map = _build_valid_capability_map()

        orchestrator = PlayerDiscoveryOrchestrator(page=page)
        orchestrator._discovery_engine = MagicMock()
        orchestrator._discovery_engine.discover = AsyncMock(
            return_value=capability_map
        )
        orchestrator._mutation_watcher = MagicMock()
        orchestrator._mutation_watcher.start = AsyncMock()
        orchestrator._mutation_watcher.on_structural_change = MagicMock()

        with patch(
            "src.player_discovery.main.ChannelMonitor"
        ) as MockMonitor:
            mock_monitor_instance = MagicMock()
            mock_monitor_instance.start_rotation = AsyncMock(return_value=[])
            MockMonitor.return_value = mock_monitor_instance

            await orchestrator.start(page, ["http://ch1.test"])

        # Mutation watcher deve ter sido iniciado com page e mapa
        orchestrator._mutation_watcher.start.assert_awaited_once_with(
            page, capability_map
        )
        orchestrator._mutation_watcher.on_structural_change.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_creates_channel_monitor(self) -> None:
        """start() cria ChannelMonitor com CapabilityMap e dependências."""
        page = MagicMock()
        capability_map = _build_valid_capability_map()
        frame_capturer = MagicMock()
        opencv_analyzer = MagicMock()
        bedrock_client = MagicMock()

        orchestrator = PlayerDiscoveryOrchestrator(
            page=page,
            frame_capturer=frame_capturer,
            opencv_analyzer=opencv_analyzer,
            bedrock_client=bedrock_client,
        )
        orchestrator._discovery_engine = MagicMock()
        orchestrator._discovery_engine.discover = AsyncMock(
            return_value=capability_map
        )
        orchestrator._mutation_watcher = MagicMock()
        orchestrator._mutation_watcher.start = AsyncMock()
        orchestrator._mutation_watcher.on_structural_change = MagicMock()

        with patch(
            "src.player_discovery.main.ChannelMonitor"
        ) as MockMonitor:
            mock_monitor_instance = MagicMock()
            mock_monitor_instance.start_rotation = AsyncMock(return_value=[])
            MockMonitor.return_value = mock_monitor_instance

            await orchestrator.start(page, ["http://ch1.test", "http://ch2.test"])

        # ChannelMonitor deve ter sido instanciado com os parâmetros corretos
        MockMonitor.assert_called_once()
        call_kwargs = MockMonitor.call_args[1]
        assert call_kwargs["capability_map"] is capability_map
        assert call_kwargs["page"] is page
        assert call_kwargs["frame_capturer"] is frame_capturer
        assert call_kwargs["opencv_analyzer"] is opencv_analyzer
        assert call_kwargs["bedrock_client"] is bedrock_client

    @pytest.mark.asyncio
    async def test_start_starts_rotation(self) -> None:
        """start() inicia rotação com a lista de canais."""
        page = MagicMock()
        capability_map = _build_valid_capability_map()
        channels = ["http://ch1.test", "http://ch2.test", "http://ch3.test"]

        orchestrator = PlayerDiscoveryOrchestrator(page=page)
        orchestrator._discovery_engine = MagicMock()
        orchestrator._discovery_engine.discover = AsyncMock(
            return_value=capability_map
        )
        orchestrator._mutation_watcher = MagicMock()
        orchestrator._mutation_watcher.start = AsyncMock()
        orchestrator._mutation_watcher.on_structural_change = MagicMock()

        with patch(
            "src.player_discovery.main.ChannelMonitor"
        ) as MockMonitor:
            mock_monitor_instance = MagicMock()
            mock_monitor_instance.start_rotation = AsyncMock(return_value=[])
            MockMonitor.return_value = mock_monitor_instance

            await orchestrator.start(page, channels)

        mock_monitor_instance.start_rotation.assert_awaited_once_with(channels)

    @pytest.mark.asyncio
    async def test_start_raises_if_already_running(self) -> None:
        """start() levanta RuntimeError se já está em execução."""
        page = MagicMock()
        capability_map = _build_valid_capability_map()

        orchestrator = PlayerDiscoveryOrchestrator(page=page)
        orchestrator._discovery_engine = MagicMock()
        orchestrator._discovery_engine.discover = AsyncMock(
            return_value=capability_map
        )
        orchestrator._mutation_watcher = MagicMock()
        orchestrator._mutation_watcher.start = AsyncMock()
        orchestrator._mutation_watcher.on_structural_change = MagicMock()

        with patch(
            "src.player_discovery.main.ChannelMonitor"
        ) as MockMonitor:
            mock_monitor_instance = MagicMock()
            mock_monitor_instance.start_rotation = AsyncMock(return_value=[])
            MockMonitor.return_value = mock_monitor_instance

            await orchestrator.start(page, ["http://ch1.test"])

        # Tentar start() novamente deve falhar
        with pytest.raises(RuntimeError, match="já está em execução"):
            await orchestrator.start(page, ["http://ch1.test"])

    @pytest.mark.asyncio
    async def test_start_propagates_discovery_error(self) -> None:
        """start() propaga exceção do DiscoveryEngine."""
        page = MagicMock()

        orchestrator = PlayerDiscoveryOrchestrator(page=page)
        orchestrator._discovery_engine = MagicMock()
        orchestrator._discovery_engine.discover = AsyncMock(
            side_effect=TimeoutError("Discovery timeout")
        )

        with pytest.raises(TimeoutError, match="Discovery timeout"):
            await orchestrator.start(page, ["http://ch1.test"])

        # Após erro, running deve ser False
        assert orchestrator.running is False


# =============================================================================
# Testes do fluxo stop()
# =============================================================================


class TestOrchestratorStop:
    """Testes do fluxo stop()."""

    @pytest.mark.asyncio
    async def test_stop_sets_running_false(self) -> None:
        """stop() marca running como False."""
        page = MagicMock()
        capability_map = _build_valid_capability_map()

        orchestrator = PlayerDiscoveryOrchestrator(page=page)
        orchestrator._discovery_engine = MagicMock()
        orchestrator._discovery_engine.discover = AsyncMock(
            return_value=capability_map
        )
        orchestrator._mutation_watcher = MagicMock()
        orchestrator._mutation_watcher.start = AsyncMock()
        orchestrator._mutation_watcher.stop = AsyncMock()
        orchestrator._mutation_watcher.on_structural_change = MagicMock()

        with patch(
            "src.player_discovery.main.ChannelMonitor"
        ) as MockMonitor:
            mock_monitor_instance = MagicMock()
            mock_monitor_instance.start_rotation = AsyncMock(return_value=[])
            MockMonitor.return_value = mock_monitor_instance

            await orchestrator.start(page, ["http://ch1.test"])

        assert orchestrator.running is True

        await orchestrator.stop()

        assert orchestrator.running is False

    @pytest.mark.asyncio
    async def test_stop_stops_mutation_watcher(self) -> None:
        """stop() para o MutationObserverWatcher."""
        page = MagicMock()
        capability_map = _build_valid_capability_map()

        orchestrator = PlayerDiscoveryOrchestrator(page=page)
        orchestrator._discovery_engine = MagicMock()
        orchestrator._discovery_engine.discover = AsyncMock(
            return_value=capability_map
        )
        orchestrator._mutation_watcher = MagicMock()
        orchestrator._mutation_watcher.start = AsyncMock()
        orchestrator._mutation_watcher.stop = AsyncMock()
        orchestrator._mutation_watcher.on_structural_change = MagicMock()

        with patch(
            "src.player_discovery.main.ChannelMonitor"
        ) as MockMonitor:
            mock_monitor_instance = MagicMock()
            mock_monitor_instance.start_rotation = AsyncMock(return_value=[])
            MockMonitor.return_value = mock_monitor_instance

            await orchestrator.start(page, ["http://ch1.test"])

        await orchestrator.stop()

        orchestrator._mutation_watcher.stop.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stop_is_idempotent(self) -> None:
        """stop() é idempotente — chamar múltiplas vezes é seguro."""
        page = MagicMock()
        orchestrator = PlayerDiscoveryOrchestrator(page=page)

        # Chamar stop sem estar running não deve falhar
        await orchestrator.stop()
        await orchestrator.stop()

        assert orchestrator.running is False


# =============================================================================
# Testes do callback de re-discovery
# =============================================================================


class TestOrchestratorRediscovery:
    """Testes do fluxo de re-discovery via mudança estrutural."""

    @pytest.mark.asyncio
    async def test_handle_rediscovery_updates_map(self) -> None:
        """_handle_rediscovery() atualiza o CapabilityMap."""
        page = MagicMock()
        old_map = _build_valid_capability_map()
        new_map = _build_valid_capability_map()

        orchestrator = PlayerDiscoveryOrchestrator(page=page)
        orchestrator._capability_map = old_map
        orchestrator._running = True

        orchestrator._discovery_engine = MagicMock()
        orchestrator._discovery_engine.rediscover = AsyncMock(
            return_value=new_map
        )
        orchestrator._mutation_watcher = MagicMock()
        orchestrator._mutation_watcher.stop = AsyncMock()
        orchestrator._mutation_watcher.start = AsyncMock()

        await orchestrator._handle_rediscovery()

        assert orchestrator.capability_map is new_map
        orchestrator._discovery_engine.rediscover.assert_awaited_once_with(page)

    @pytest.mark.asyncio
    async def test_handle_rediscovery_restarts_watcher(self) -> None:
        """_handle_rediscovery() reinicia o MutationObserverWatcher."""
        page = MagicMock()
        new_map = _build_valid_capability_map()

        orchestrator = PlayerDiscoveryOrchestrator(page=page)
        orchestrator._capability_map = _build_valid_capability_map()
        orchestrator._running = True

        orchestrator._discovery_engine = MagicMock()
        orchestrator._discovery_engine.rediscover = AsyncMock(
            return_value=new_map
        )
        orchestrator._mutation_watcher = MagicMock()
        orchestrator._mutation_watcher.stop = AsyncMock()
        orchestrator._mutation_watcher.start = AsyncMock()

        await orchestrator._handle_rediscovery()

        orchestrator._mutation_watcher.stop.assert_awaited_once()
        orchestrator._mutation_watcher.start.assert_awaited_once_with(
            page, new_map
        )

    @pytest.mark.asyncio
    async def test_handle_rediscovery_updates_channel_monitor(self) -> None:
        """_handle_rediscovery() atualiza ChannelMonitor com novo mapa."""
        page = MagicMock()
        new_map = _build_valid_capability_map()

        orchestrator = PlayerDiscoveryOrchestrator(page=page)
        orchestrator._capability_map = _build_valid_capability_map()
        orchestrator._running = True

        # Simular channel monitor existente
        mock_monitor = MagicMock()
        orchestrator._channel_monitor = mock_monitor

        orchestrator._discovery_engine = MagicMock()
        orchestrator._discovery_engine.rediscover = AsyncMock(
            return_value=new_map
        )
        orchestrator._mutation_watcher = MagicMock()
        orchestrator._mutation_watcher.stop = AsyncMock()
        orchestrator._mutation_watcher.start = AsyncMock()

        await orchestrator._handle_rediscovery()

        assert mock_monitor._capability_map is new_map

    @pytest.mark.asyncio
    async def test_handle_rediscovery_handles_error(self) -> None:
        """_handle_rediscovery() lida com erro sem propagar."""
        page = MagicMock()

        orchestrator = PlayerDiscoveryOrchestrator(page=page)
        orchestrator._capability_map = _build_valid_capability_map()
        orchestrator._running = True

        orchestrator._discovery_engine = MagicMock()
        orchestrator._discovery_engine.rediscover = AsyncMock(
            side_effect=RuntimeError("Re-discovery failed")
        )
        orchestrator._mutation_watcher = MagicMock()
        orchestrator._mutation_watcher.stop = AsyncMock()
        orchestrator._mutation_watcher.start = AsyncMock()

        # Não deve propagar exceção
        await orchestrator._handle_rediscovery()

        # O mapa antigo deve permanecer
        assert orchestrator.capability_map is not None
