"""Property-Based Tests para ChannelMonitor — Sinalização de alta confidence.

Feature: player-discovery, Property 18: Sinalização de validação quando
capability de alta confidence falha

Para qualquer capability com confidence >= 0.9 que falha em um teste funcional,
o sistema deve sinalizar necessidade de validação do Capability Map.

**Validates: Requirements 11.4**
"""

from unittest.mock import MagicMock

from hypothesis import given, settings, strategies as st

from src.player_discovery.models import (
    Capability,
    CapabilityMap,
    CapabilityMapData,
    InteractionLevel,
    PlayerInfo,
)
from src.player_discovery.monitoring.channel_monitor import ChannelMonitor


# --- Helpers ---


def _build_capability_map_with(
    capability_name: str, confidence: float
) -> CapabilityMap:
    """Cria um CapabilityMap com uma capability específica e confidence definida.

    Args:
        capability_name: Nome da capability.
        confidence: Valor de confidence (0.0 a 1.0).

    Returns:
        CapabilityMap configurado com a capability.
    """
    cap = Capability(
        name=capability_name,
        available=True,
        confidence=confidence,
        evidence=["teste funcional"],
        interaction_strategy=InteractionLevel.PLAYER_API,
        strategies=[],
    )

    # Capabilities obrigatórias mínimas para CapabilityMap válido
    capabilities = {capability_name: cap}

    data = CapabilityMapData(
        player_info=PlayerInfo(
            library="test-player",
            version="1.0.0",
            video_elements=["video"],
            discovered_at="2024-01-01T00:00:00.000Z",
        ),
        capabilities=capabilities,
        discovery_duration_ms=1000,
        version_hash="test_hash",
        valid=True,
    )

    return CapabilityMap(data)


def _build_composite_capability_map(
    composite_name: str,
    individual_names: list[str],
    confidence: float,
) -> CapabilityMap:
    """Cria um CapabilityMap com capabilities individuais de um teste composto.

    Args:
        composite_name: Nome do teste composto (ex: play_pause).
        individual_names: Nomes das capabilities individuais (ex: [play, pause]).
        confidence: Valor de confidence para cada capability individual.

    Returns:
        CapabilityMap configurado com as capabilities individuais.
    """
    capabilities = {}
    for name in individual_names:
        capabilities[name] = Capability(
            name=name,
            available=True,
            confidence=confidence,
            evidence=["teste funcional"],
            interaction_strategy=InteractionLevel.PLAYER_API,
            strategies=[],
        )

    data = CapabilityMapData(
        player_info=PlayerInfo(
            library="test-player",
            version="1.0.0",
            video_elements=["video"],
            discovered_at="2024-01-01T00:00:00.000Z",
        ),
        capabilities=capabilities,
        discovery_duration_ms=1000,
        version_hash="test_hash",
        valid=True,
    )

    return CapabilityMap(data)


# --- Estratégias de geração ---

# Capabilities individuais que podem ter alta confidence
individual_capability_names = st.sampled_from([
    "play", "pause", "mute", "unmute",
    "audio_selection", "subtitle_selection",
    "quality_selection", "fullscreen", "settings",
])

# Testes compostos e suas capabilities individuais
composite_tests = st.sampled_from([
    ("play_pause", ["play", "pause"]),
    ("mute_unmute", ["mute", "unmute"]),
])

# Confidence alta: >= 0.9
high_confidence = st.floats(
    min_value=0.9, max_value=1.0,
    allow_nan=False, allow_infinity=False,
)

# Confidence baixa: < 0.9
low_confidence = st.floats(
    min_value=0.0, max_value=0.8999999,
    allow_nan=False, allow_infinity=False,
)


# --- Property Tests ---


class TestHighConfidenceSignaling:
    """Property 18: Sinalização quando capability de alta confidence falha."""

    @settings(max_examples=100)
    @given(
        capability_name=individual_capability_names,
        confidence=high_confidence,
    )
    def test_high_confidence_failure_signals_validation(
        self, capability_name: str, confidence: float
    ):
        """Para qualquer capability com confidence >= 0.9 que falha,
        o sistema DEVE sinalizar necessidade de validação do CapabilityMap.

        **Validates: Requirements 11.4**
        """
        # Arrange: criar CapabilityMap com a capability de alta confidence
        cap_map = _build_capability_map_with(capability_name, confidence)
        page_mock = MagicMock()
        monitor = ChannelMonitor(
            capability_map=cap_map, page=page_mock
        )

        # Act: simular falha no teste funcional
        monitor._check_high_confidence_failure(capability_name)

        # Assert: deve sinalizar necessidade de validação
        assert monitor.needs_map_validation is True, (
            f"Capability '{capability_name}' com confidence={confidence:.4f} "
            f"(>= 0.9) falhou, mas o sistema NÃO sinalizou validação."
        )

    @settings(max_examples=100)
    @given(
        capability_name=individual_capability_names,
        confidence=low_confidence,
    )
    def test_low_confidence_failure_does_not_signal_validation(
        self, capability_name: str, confidence: float
    ):
        """Para qualquer capability com confidence < 0.9 que falha,
        o sistema NÃO deve sinalizar validação do CapabilityMap.

        **Validates: Requirements 11.4**
        """
        # Arrange: criar CapabilityMap com a capability de baixa confidence
        cap_map = _build_capability_map_with(capability_name, confidence)
        page_mock = MagicMock()
        monitor = ChannelMonitor(
            capability_map=cap_map, page=page_mock
        )

        # Act: simular falha no teste funcional
        monitor._check_high_confidence_failure(capability_name)

        # Assert: NÃO deve sinalizar validação
        assert monitor.needs_map_validation is False, (
            f"Capability '{capability_name}' com confidence={confidence:.4f} "
            f"(< 0.9) falhou, mas o sistema SINALIZOU validação "
            f"incorretamente."
        )

    @settings(max_examples=100)
    @given(
        composite_data=composite_tests,
        confidence=high_confidence,
    )
    def test_composite_high_confidence_failure_signals_validation(
        self, composite_data: tuple, confidence: float
    ):
        """Para testes compostos (play_pause, mute_unmute) com capabilities
        individuais de alta confidence que falham, o sistema DEVE sinalizar
        validação.

        **Validates: Requirements 11.4**
        """
        composite_name, individual_names = composite_data

        # Arrange: criar CapabilityMap com capabilities individuais
        cap_map = _build_composite_capability_map(
            composite_name, individual_names, confidence
        )
        page_mock = MagicMock()
        monitor = ChannelMonitor(
            capability_map=cap_map, page=page_mock
        )

        # Act: simular falha no teste composto
        monitor._check_high_confidence_failure(composite_name)

        # Assert: deve sinalizar validação
        assert monitor.needs_map_validation is True, (
            f"Teste composto '{composite_name}' com capabilities "
            f"{individual_names} e confidence={confidence:.4f} (>= 0.9) "
            f"falhou, mas o sistema NÃO sinalizou validação."
        )

    @settings(max_examples=100)
    @given(
        composite_data=composite_tests,
        confidence=low_confidence,
    )
    def test_composite_low_confidence_failure_does_not_signal(
        self, composite_data: tuple, confidence: float
    ):
        """Para testes compostos com capabilities de baixa confidence
        que falham, o sistema NÃO deve sinalizar validação.

        **Validates: Requirements 11.4**
        """
        composite_name, individual_names = composite_data

        # Arrange: criar CapabilityMap com capabilities de baixa confidence
        cap_map = _build_composite_capability_map(
            composite_name, individual_names, confidence
        )
        page_mock = MagicMock()
        monitor = ChannelMonitor(
            capability_map=cap_map, page=page_mock
        )

        # Act: simular falha no teste composto
        monitor._check_high_confidence_failure(composite_name)

        # Assert: NÃO deve sinalizar validação
        assert monitor.needs_map_validation is False, (
            f"Teste composto '{composite_name}' com capabilities "
            f"{individual_names} e confidence={confidence:.4f} (< 0.9) "
            f"falhou, mas o sistema SINALIZOU validação incorretamente."
        )


# =================================================================
# Feature: player-discovery, Property 17: Ordenação de testes
# funcionais por impacto
# =================================================================
"""
Property 17: Para qualquer conjunto de capabilities disponíveis para
teste funcional, a ordem de execução deve ser:
  play/pause → mute/unmute → audio_selection → subtitle_selection
(menor impacto para maior impacto).

**Validates: Requirements 11.2**
"""

import asyncio

from src.player_discovery.models.results import FunctionalTestResult


# Ordem canônica de menor impacto para maior impacto (Req 11.2)
CANONICAL_ORDER = [
    "play_pause",
    "mute_unmute",
    "audio_selection",
    "subtitle_selection",
]


def _build_functional_test_capability_map(
    available_set: set,
) -> CapabilityMap:
    """Constrói um CapabilityMap para teste de ordenação funcional.

    As capabilities cujo teste está em available_set serão marcadas
    como available=True; as demais como available=False.

    Args:
        available_set: Conjunto de nomes de testes funcionais ativos
            (ex: {"play_pause", "audio_selection"}).

    Returns:
        CapabilityMap configurado.
    """
    # Mapear nomes de teste para capabilities individuais
    cap_names_map = {
        "play_pause": ["play", "pause"],
        "mute_unmute": ["mute", "unmute"],
        "audio_selection": ["audio_selection"],
        "subtitle_selection": ["subtitle_selection"],
    }

    # Capabilities obrigatórias mínimas
    all_caps = [
        "play", "pause", "mute", "unmute",
        "audio_selection", "subtitle_selection",
        "quality_selection", "fullscreen", "settings",
    ]

    capabilities = {}
    for cap_name in all_caps:
        is_available = False
        for test_name, individual_caps in cap_names_map.items():
            if cap_name in individual_caps:
                is_available = test_name in available_set
                break

        capabilities[cap_name] = Capability(
            name=cap_name,
            available=is_available,
            confidence=0.95 if is_available else 0.3,
            evidence=["teste"],
            interaction_strategy=InteractionLevel.PLAYER_API,
            strategies=[],
        )

    data = CapabilityMapData(
        player_info=PlayerInfo(
            library="test-player",
            version="1.0.0",
            video_elements=["video"],
            discovered_at="2024-01-01T00:00:00.000Z",
        ),
        capabilities=capabilities,
        discovery_duration_ms=1000,
        version_hash="test_hash",
        valid=True,
    )

    return CapabilityMap(data)


# Strategy: subconjuntos aleatórios de capabilities funcionais
available_functional_caps_strategy = st.frozensets(
    st.sampled_from(CANONICAL_ORDER),
    min_size=0,
    max_size=4,
)


class TestOrdenacaoPorImpacto:
    """Property 17: Ordenação de testes funcionais por impacto."""

    @settings(max_examples=100)
    @given(available=available_functional_caps_strategy)
    def test_functional_tests_maintain_impact_order(
        self, available: frozenset
    ) -> None:
        """A ordem de execução dos testes funcionais respeita a
        sequência de menor impacto para maior impacto.

        Para qualquer subconjunto de capabilities disponíveis, os
        testes que executam devem manter a ordem relativa:
        play/pause → mute/unmute → audio_selection →
        subtitle_selection.

        **Validates: Requirements 11.2**
        """
        # Rastrear ordem de execução
        execution_order: list = []

        # Construir CapabilityMap
        cap_map = _build_functional_test_capability_map(
            set(available)
        )

        # Criar mock de page
        mock_page = MagicMock()

        # Criar ChannelMonitor
        monitor = ChannelMonitor(
            capability_map=cap_map,
            page=mock_page,
        )

        # Mocks dos métodos de teste que registram a ordem
        async def mock_play_pause():
            execution_order.append("play_pause")
            status = (
                FunctionalTestStatus.PASS
                if "play_pause" in available
                else FunctionalTestStatus.SKIPPED
            )
            return FunctionalTestResult(
                capability="play_pause",
                status=status,
                action_executed="play/pause",
                expected_result="ok",
                actual_result="ok",
                duration_ms=10,
            )

        async def mock_mute_unmute():
            execution_order.append("mute_unmute")
            status = (
                FunctionalTestStatus.PASS
                if "mute_unmute" in available
                else FunctionalTestStatus.SKIPPED
            )
            return FunctionalTestResult(
                capability="mute_unmute",
                status=status,
                action_executed="mute/unmute",
                expected_result="ok",
                actual_result="ok",
                duration_ms=10,
            )

        async def mock_audio_selection():
            execution_order.append("audio_selection")
            status = (
                FunctionalTestStatus.PASS
                if "audio_selection" in available
                else FunctionalTestStatus.SKIPPED
            )
            return FunctionalTestResult(
                capability="audio_selection",
                status=status,
                action_executed="audio_selection",
                expected_result="ok",
                actual_result="ok",
                duration_ms=10,
            )

        async def mock_subtitle_selection():
            execution_order.append("subtitle_selection")
            status = (
                FunctionalTestStatus.PASS
                if "subtitle_selection" in available
                else FunctionalTestStatus.SKIPPED
            )
            return FunctionalTestResult(
                capability="subtitle_selection",
                status=status,
                action_executed="subtitle_selection",
                expected_result="ok",
                actual_result="ok",
                duration_ms=10,
            )

        # Substituir métodos internos
        monitor._test_play_pause = mock_play_pause
        monitor._test_mute_unmute = mock_mute_unmute
        monitor._test_audio_selection = mock_audio_selection
        monitor._test_subtitle_selection = mock_subtitle_selection

        # Executar testes funcionais
        loop = asyncio.new_event_loop()
        try:
            results = loop.run_until_complete(
                monitor.run_functional_tests(
                    "http://test.com/ch1"
                )
            )
        finally:
            loop.close()

        # Verificar que TODOS os 4 testes foram chamados
        assert len(execution_order) == 4, (
            f"Esperado 4 testes executados, "
            f"obtido {len(execution_order)}: "
            f"{execution_order}"
        )

        # Verificar que a ordem é exatamente a canônica
        assert execution_order == CANONICAL_ORDER, (
            f"Ordem de execução incorreta. "
            f"Esperado: {CANONICAL_ORDER}, "
            f"Obtido: {execution_order}. "
            f"Capabilities disponíveis: {set(available)}"
        )

        # Verificar que os resultados retornados mantêm ordem
        result_caps = [r.capability for r in results]
        assert result_caps == CANONICAL_ORDER, (
            f"Ordem dos resultados incorreta. "
            f"Esperado: {CANONICAL_ORDER}, "
            f"Obtido: {result_caps}"
        )
