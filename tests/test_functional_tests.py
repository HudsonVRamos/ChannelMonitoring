"""Testes unitários para os testes funcionais periódicos do ChannelMonitor.

Testa:
- Execução de run_functional_tests() com ordem correta
- Intervalo de execução a cada N rotações
- Sinalização de validação quando capability com confidence >= 0.9 falha
- Comportamento quando capabilities não estão disponíveis (SKIPPED)

Requirements: 11.1, 11.2, 11.3, 11.4
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.player_discovery.monitoring.channel_monitor import (
    ChannelMonitor,
)
from src.player_discovery.models.enums import (
    FunctionalTestStatus,
)
from src.player_discovery.models.results import (
    FunctionalTestResult,
)


# --- Fixtures ---


@pytest.fixture
def mock_capability_map_with_all():
    """Mock de CapabilityMap com todas as capabilities disponíveis."""
    cap_map = MagicMock()
    cap_map.is_valid.return_value = True

    # Capabilities com alta confidence
    play_cap = MagicMock(available=True, confidence=0.95)
    pause_cap = MagicMock(available=True, confidence=0.95)
    mute_cap = MagicMock(available=True, confidence=0.92)
    unmute_cap = MagicMock(available=True, confidence=0.92)
    audio_cap = MagicMock(available=True, confidence=0.85)
    subtitle_cap = MagicMock(available=True, confidence=0.90)

    def get_cap(name):
        caps = {
            "play": play_cap,
            "pause": pause_cap,
            "mute": mute_cap,
            "unmute": unmute_cap,
            "audio_selection": audio_cap,
            "subtitle_selection": subtitle_cap,
        }
        return caps.get(name)

    cap_map.get_capability.side_effect = get_cap
    return cap_map


@pytest.fixture
def mock_capability_map_limited():
    """Mock de CapabilityMap com capabilities limitadas."""
    cap_map = MagicMock()
    cap_map.is_valid.return_value = True

    # Apenas play/pause disponível
    play_cap = MagicMock(available=True, confidence=0.95)
    pause_cap = MagicMock(available=True, confidence=0.95)

    def get_cap(name):
        caps = {
            "play": play_cap,
            "pause": pause_cap,
            "mute": None,
            "unmute": None,
            "audio_selection": None,
            "subtitle_selection": None,
        }
        return caps.get(name)

    cap_map.get_capability.side_effect = get_cap
    return cap_map


@pytest.fixture
def mock_page():
    """Mock da Playwright Page."""
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
def monitor_with_all_caps(mock_capability_map_with_all, mock_page):
    """ChannelMonitor com todas as capabilities disponíveis."""
    config = {
        "observation_period_s": 0.05,
        "telemetry_interval_s": 0.02,
        "navigation_timeout_ms": 5000,
        "functional_test_interval": 5,
    }
    return ChannelMonitor(
        capability_map=mock_capability_map_with_all,
        page=mock_page,
        config=config,
    )


@pytest.fixture
def monitor_with_limited_caps(mock_capability_map_limited, mock_page):
    """ChannelMonitor com capabilities limitadas."""
    config = {
        "observation_period_s": 0.05,
        "telemetry_interval_s": 0.02,
        "navigation_timeout_ms": 5000,
        "functional_test_interval": 5,
    }
    return ChannelMonitor(
        capability_map=mock_capability_map_limited,
        page=mock_page,
        config=config,
    )


# --- Testes de Configuração ---


class TestFunctionalTestConfig:
    """Testes da configuração de testes funcionais."""

    def test_intervalo_padrao_5(self, mock_page):
        """Intervalo padrão de testes funcionais deve ser 5."""
        cap_map = MagicMock()
        cap_map.is_valid.return_value = True
        monitor = ChannelMonitor(
            capability_map=cap_map,
            page=mock_page,
        )
        assert monitor.functional_test_interval == 5

    def test_intervalo_configuravel(self, mock_page):
        """Intervalo de testes funcionais deve ser configurável."""
        cap_map = MagicMock()
        cap_map.is_valid.return_value = True
        monitor = ChannelMonitor(
            capability_map=cap_map,
            page=mock_page,
            config={"functional_test_interval": 10},
        )
        assert monitor.functional_test_interval == 10

    def test_needs_map_validation_inicia_false(self, mock_page):
        """Flag needs_map_validation deve iniciar False."""
        cap_map = MagicMock()
        cap_map.is_valid.return_value = True
        monitor = ChannelMonitor(
            capability_map=cap_map,
            page=mock_page,
        )
        assert monitor.needs_map_validation is False


# --- Testes de run_functional_tests ---


class TestRunFunctionalTests:
    """Testes de execução de testes funcionais."""

    @pytest.mark.asyncio
    async def test_retorna_lista_de_resultados(
        self, monitor_with_all_caps
    ):
        """run_functional_tests deve retornar lista de resultados."""
        # Mock das probes para sucesso
        monitor_with_all_caps._interaction_manager.execute = (
            AsyncMock(
                return_value=MagicMock(success=True, error=None)
            )
        )
        monitor_with_all_caps._audio_probe.run_functional_test = (
            AsyncMock(
                return_value=FunctionalTestResult(
                    capability="mute_unmute",
                    status=FunctionalTestStatus.PASS,
                    action_executed="mute → unmute",
                    expected_result="mute/unmute funciona",
                    actual_result="sucesso",
                    duration_ms=100,
                )
            )
        )
        monitor_with_all_caps._subtitle_probe.run_functional_test = (
            AsyncMock(
                return_value=FunctionalTestResult(
                    capability="subtitle_selection",
                    status=FunctionalTestStatus.PASS,
                    action_executed="selecionar legenda",
                    expected_result="legenda ativa",
                    actual_result="sucesso",
                    duration_ms=200,
                )
            )
        )

        results = await monitor_with_all_caps.run_functional_tests(
            "http://example.com/channel1"
        )

        assert isinstance(results, list)
        assert len(results) == 4  # play/pause, mute, audio, subtitle

    @pytest.mark.asyncio
    async def test_ordem_execucao_menor_impacto_para_maior(
        self, monitor_with_all_caps
    ):
        """Ordem: play/pause → mute → audio → subtitle."""
        execution_order: list[str] = []

        async def mock_interaction(*args, **kwargs):
            return MagicMock(success=True, error=None)

        async def mock_audio_test(*args, **kwargs):
            execution_order.append("audio")
            return FunctionalTestResult(
                capability="mute_unmute",
                status=FunctionalTestStatus.PASS,
                action_executed="mute",
                expected_result="ok",
                actual_result="ok",
                duration_ms=50,
            )

        async def mock_subtitle_test(*args, **kwargs):
            execution_order.append("subtitle")
            return FunctionalTestResult(
                capability="subtitle_selection",
                status=FunctionalTestStatus.PASS,
                action_executed="subtitle",
                expected_result="ok",
                actual_result="ok",
                duration_ms=50,
            )

        # Interceptar chamadas de interação para rastrear ordem

        async def mock_play_pause():
            execution_order.append("play_pause")
            return FunctionalTestResult(
                capability="play_pause",
                status=FunctionalTestStatus.PASS,
                action_executed="play/pause",
                expected_result="ok",
                actual_result="ok",
                duration_ms=50,
            )

        async def mock_mute_unmute():
            execution_order.append("mute_unmute")
            return FunctionalTestResult(
                capability="mute_unmute",
                status=FunctionalTestStatus.PASS,
                action_executed="mute/unmute",
                expected_result="ok",
                actual_result="ok",
                duration_ms=50,
            )

        async def mock_audio_selection():
            execution_order.append("audio_selection")
            return FunctionalTestResult(
                capability="audio_selection",
                status=FunctionalTestStatus.PASS,
                action_executed="audio",
                expected_result="ok",
                actual_result="ok",
                duration_ms=50,
            )

        async def mock_subtitle_selection():
            execution_order.append("subtitle_selection")
            return FunctionalTestResult(
                capability="subtitle_selection",
                status=FunctionalTestStatus.PASS,
                action_executed="subtitle",
                expected_result="ok",
                actual_result="ok",
                duration_ms=50,
            )

        monitor_with_all_caps._test_play_pause = mock_play_pause
        monitor_with_all_caps._test_mute_unmute = mock_mute_unmute
        monitor_with_all_caps._test_audio_selection = (
            mock_audio_selection
        )
        monitor_with_all_caps._test_subtitle_selection = (
            mock_subtitle_selection
        )

        await monitor_with_all_caps.run_functional_tests(
            "http://example.com/channel1"
        )

        assert execution_order == [
            "play_pause",
            "mute_unmute",
            "audio_selection",
            "subtitle_selection",
        ]

    @pytest.mark.asyncio
    async def test_play_pause_skipped_quando_indisponivel(
        self, monitor_with_limited_caps
    ):
        """Play/pause SKIPPED quando capabilities não disponíveis."""
        # mute/unmute/audio/subtitle não disponíveis
        monitor_with_limited_caps._audio_probe.run_functional_test = (
            AsyncMock(
                return_value=FunctionalTestResult(
                    capability="audio",
                    status=FunctionalTestStatus.SKIPPED,
                    action_executed="nenhum",
                    expected_result="disponível",
                    actual_result="não disponível",
                    duration_ms=0,
                )
            )
        )
        monitor_with_limited_caps._subtitle_probe.run_functional_test = (
            AsyncMock(
                return_value=FunctionalTestResult(
                    capability="subtitle_selection",
                    status=FunctionalTestStatus.SKIPPED,
                    action_executed="verificar",
                    expected_result="disponível",
                    actual_result="não disponível",
                    duration_ms=0,
                )
            )
        )
        monitor_with_limited_caps._interaction_manager.execute = (
            AsyncMock(
                return_value=MagicMock(success=True, error=None)
            )
        )

        results = await monitor_with_limited_caps.run_functional_tests(
            "http://example.com/channel1"
        )

        # play/pause deve ser PASS (caps disponíveis)
        assert results[0].capability == "play_pause"
        assert results[0].status == FunctionalTestStatus.PASS

    @pytest.mark.asyncio
    async def test_registra_fail_quando_interacao_falha(
        self, monitor_with_all_caps
    ):
        """Deve registrar FAIL quando interação do play/pause falha."""
        monitor_with_all_caps._interaction_manager.execute = (
            AsyncMock(
                return_value=MagicMock(
                    success=False, error="elemento não encontrado"
                )
            )
        )
        monitor_with_all_caps._audio_probe.run_functional_test = (
            AsyncMock(
                return_value=FunctionalTestResult(
                    capability="mute_unmute",
                    status=FunctionalTestStatus.PASS,
                    action_executed="mute",
                    expected_result="ok",
                    actual_result="ok",
                    duration_ms=50,
                )
            )
        )
        monitor_with_all_caps._subtitle_probe.run_functional_test = (
            AsyncMock(
                return_value=FunctionalTestResult(
                    capability="subtitle_selection",
                    status=FunctionalTestStatus.PASS,
                    action_executed="subtitle",
                    expected_result="ok",
                    actual_result="ok",
                    duration_ms=50,
                )
            )
        )

        results = await monitor_with_all_caps.run_functional_tests(
            "http://example.com/channel1"
        )

        play_pause_result = results[0]
        assert play_pause_result.capability == "play_pause"
        assert play_pause_result.status == FunctionalTestStatus.FAIL
        assert "elemento não encontrado" in play_pause_result.actual_result


# --- Testes de Sinalização de Validação (Req 11.4) ---


class TestHighConfidenceValidation:
    """Testes de sinalização quando capability com confidence >= 0.9 falha."""

    @pytest.mark.asyncio
    async def test_sinaliza_validacao_quando_alta_confidence_falha(
        self, monitor_with_all_caps
    ):
        """Sinaliza validação quando cap confidence >= 0.9 falha."""
        # play_pause tem confidence 0.95
        monitor_with_all_caps._interaction_manager.execute = (
            AsyncMock(
                return_value=MagicMock(
                    success=False, error="falhou"
                )
            )
        )
        monitor_with_all_caps._audio_probe.run_functional_test = (
            AsyncMock(
                return_value=FunctionalTestResult(
                    capability="mute_unmute",
                    status=FunctionalTestStatus.PASS,
                    action_executed="mute",
                    expected_result="ok",
                    actual_result="ok",
                    duration_ms=50,
                )
            )
        )
        monitor_with_all_caps._subtitle_probe.run_functional_test = (
            AsyncMock(
                return_value=FunctionalTestResult(
                    capability="subtitle_selection",
                    status=FunctionalTestStatus.PASS,
                    action_executed="subtitle",
                    expected_result="ok",
                    actual_result="ok",
                    duration_ms=50,
                )
            )
        )

        assert monitor_with_all_caps.needs_map_validation is False

        await monitor_with_all_caps.run_functional_tests(
            "http://example.com/channel1"
        )

        # play_pause tem confidence 0.95 e falhou → deve sinalizar
        assert monitor_with_all_caps.needs_map_validation is True

    @pytest.mark.asyncio
    async def test_nao_sinaliza_quando_baixa_confidence(
        self, mock_page
    ):
        """Não deve sinalizar quando capability com confidence < 0.9 falha."""
        cap_map = MagicMock()
        cap_map.is_valid.return_value = True

        # Capabilities com baixa confidence
        play_cap = MagicMock(available=True, confidence=0.75)
        pause_cap = MagicMock(available=True, confidence=0.75)

        def get_cap(name):
            caps = {
                "play": play_cap,
                "pause": pause_cap,
                "mute": None,
                "unmute": None,
                "audio_selection": None,
                "subtitle_selection": None,
            }
            return caps.get(name)

        cap_map.get_capability.side_effect = get_cap

        monitor = ChannelMonitor(
            capability_map=cap_map,
            page=mock_page,
            config={
                "observation_period_s": 0.05,
                "telemetry_interval_s": 0.02,
                "functional_test_interval": 5,
            },
        )

        # Forçar falha no play/pause
        monitor._interaction_manager.execute = AsyncMock(
            return_value=MagicMock(
                success=False, error="falhou"
            )
        )
        monitor._audio_probe.run_functional_test = AsyncMock(
            return_value=FunctionalTestResult(
                capability="audio",
                status=FunctionalTestStatus.SKIPPED,
                action_executed="nenhum",
                expected_result="ok",
                actual_result="não disponível",
                duration_ms=0,
            )
        )
        monitor._subtitle_probe.run_functional_test = AsyncMock(
            return_value=FunctionalTestResult(
                capability="subtitle_selection",
                status=FunctionalTestStatus.SKIPPED,
                action_executed="verificar",
                expected_result="ok",
                actual_result="não disponível",
                duration_ms=0,
            )
        )

        await monitor.run_functional_tests(
            "http://example.com/channel1"
        )

        # play_pause tem confidence 0.75 → não sinaliza
        assert monitor.needs_map_validation is False


# --- Testes de Integração com start_rotation ---


class TestFunctionalTestsInRotation:
    """Testes de execução de testes funcionais durante rotação."""

    @pytest.mark.asyncio
    async def test_executa_na_rotacao_multipla_de_n(self, mock_page):
        """Testes funcionais devem executar quando rotation_count % N == 0."""
        cap_map = MagicMock()
        cap_map.is_valid.return_value = True
        cap_map.get_capability.return_value = MagicMock(
            available=True, confidence=0.95
        )

        # Intervalo = 2 para teste rápido
        config = {
            "observation_period_s": 0.01,
            "telemetry_interval_s": 0.005,
            "navigation_timeout_ms": 5000,
            "functional_test_interval": 2,
        }
        monitor = ChannelMonitor(
            capability_map=cap_map,
            page=mock_page,
            config=config,
        )

        # Mock run_functional_tests para rastrear chamadas
        call_count = 0

        async def mock_run(url):
            nonlocal call_count
            call_count += 1
            return [
                FunctionalTestResult(
                    capability="play_pause",
                    status=FunctionalTestStatus.PASS,
                    action_executed="test",
                    expected_result="ok",
                    actual_result="ok",
                    duration_ms=10,
                )
            ]

        monitor.run_functional_tests = mock_run

        channels = ["http://example.com/ch1"]

        # Rotação 1: NÃO executa (1 % 2 != 0)
        await monitor.start_rotation(channels)
        assert call_count == 0
        assert monitor.rotation_count == 1

        # Rotação 2: EXECUTA (2 % 2 == 0)
        await monitor.start_rotation(channels)
        assert call_count == 1
        assert monitor.rotation_count == 2

        # Rotação 3: NÃO executa (3 % 2 != 0)
        await monitor.start_rotation(channels)
        assert call_count == 1
        assert monitor.rotation_count == 3

        # Rotação 4: EXECUTA (4 % 2 == 0)
        await monitor.start_rotation(channels)
        assert call_count == 2
        assert monitor.rotation_count == 4

    @pytest.mark.asyncio
    async def test_nao_executa_antes_da_primeira_multipla(
        self, mock_page
    ):
        """Não deve executar testes funcionais antes da primeira múltipla."""
        cap_map = MagicMock()
        cap_map.is_valid.return_value = True
        cap_map.get_capability.return_value = MagicMock(
            available=True, confidence=0.9
        )

        config = {
            "observation_period_s": 0.01,
            "telemetry_interval_s": 0.005,
            "navigation_timeout_ms": 5000,
            "functional_test_interval": 5,
        }
        monitor = ChannelMonitor(
            capability_map=cap_map,
            page=mock_page,
            config=config,
        )

        call_count = 0

        async def mock_run(url):
            nonlocal call_count
            call_count += 1
            return []

        monitor.run_functional_tests = mock_run

        channels = ["http://example.com/ch1"]

        # Rotações 1-4: NÃO executa
        for _ in range(4):
            await monitor.start_rotation(channels)

        assert call_count == 0
        assert monitor.rotation_count == 4

    @pytest.mark.asyncio
    async def test_resultado_associado_ao_ultimo_canal(
        self, mock_page
    ):
        """Resultados devem ser associados ao último canal."""
        cap_map = MagicMock()
        cap_map.is_valid.return_value = True
        cap_map.get_capability.return_value = MagicMock(
            available=True, confidence=0.9
        )

        config = {
            "observation_period_s": 0.01,
            "telemetry_interval_s": 0.005,
            "navigation_timeout_ms": 5000,
            "functional_test_interval": 1,  # Executar toda rotação
        }
        monitor = ChannelMonitor(
            capability_map=cap_map,
            page=mock_page,
            config=config,
        )

        test_result = FunctionalTestResult(
            capability="play_pause",
            status=FunctionalTestStatus.PASS,
            action_executed="test",
            expected_result="ok",
            actual_result="ok",
            duration_ms=10,
        )

        async def mock_run(url):
            return [test_result]

        monitor.run_functional_tests = mock_run

        channels = [
            "http://example.com/ch1",
            "http://example.com/ch2",
        ]

        reports = await monitor.start_rotation(channels)

        # Último canal deve ter os resultados
        assert len(reports[-1].functional_tests) == 1
        assert reports[-1].functional_tests[0] == test_result
        # Primeiro canal NÃO deve ter resultados
        assert len(reports[0].functional_tests) == 0
