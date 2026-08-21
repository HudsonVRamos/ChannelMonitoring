"""Testes unitários para CapabilityMap.

Valida os métodos de consulta, validação, invalidação e serialização
da classe CapabilityMap.
"""

import json

import pytest

from src.player_discovery.models import (
    Capability,
    CapabilityMap,
    CapabilityMapData,
    InteractionStrategy,
    PlayerInfo,
    REQUIRED_CAPABILITIES,
)
from src.player_discovery.models.enums import InteractionLevel


def _make_capability(
    name: str,
    available: bool = True,
    confidence: float = 0.9,
    level: InteractionLevel = InteractionLevel.SEMANTIC_DOM,
) -> Capability:
    """Helper para criar uma capability de teste."""
    return Capability(
        name=name,
        available=available,
        confidence=confidence,
        evidence=[f"teste para {name}"],
        interaction_strategy=level,
        strategies=[
            InteractionStrategy(
                level=level,
                type=level.value,
                details={"method": f"{name}()"},
            )
        ],
    )


def _make_full_capability_map() -> CapabilityMap:
    """Cria um CapabilityMap com todas as capabilities obrigatórias."""
    caps = {}
    for cap_name in REQUIRED_CAPABILITIES:
        caps[cap_name] = _make_capability(cap_name)

    data = CapabilityMapData(
        player_info=PlayerInfo(
            library="shaka-player",
            version="4.3.0",
            video_elements=["video#main"],
            discovered_at="2024-01-01T00:00:00.000Z",
        ),
        capabilities=caps,
        discovery_duration_ms=5000,
        version_hash="abc123",
        valid=True,
    )
    return CapabilityMap(data)


class TestCapabilityMapInit:
    """Testes de inicialização do CapabilityMap."""

    def test_cria_com_data_valida(self):
        cmap = _make_full_capability_map()
        assert cmap.is_valid()
        assert cmap.player_info.library == "shaka-player"

    def test_propriedades_expostas_corretamente(self):
        cmap = _make_full_capability_map()
        assert cmap.version_hash == "abc123"
        assert cmap.discovery_duration_ms == 5000
        assert len(cmap.capabilities) == len(REQUIRED_CAPABILITIES)


class TestGetCapability:
    """Testes para get_capability()."""

    def test_retorna_capability_existente(self):
        cmap = _make_full_capability_map()
        cap = cmap.get_capability("play")
        assert cap is not None
        assert cap.name == "play"
        assert cap.available is True

    def test_retorna_none_para_inexistente(self):
        cmap = _make_full_capability_map()
        cap = cmap.get_capability("nao_existe")
        assert cap is None


class TestGetInteractionStrategy:
    """Testes para get_interaction_strategy()."""

    def test_retorna_primeira_strategy(self):
        cmap = _make_full_capability_map()
        strategy = cmap.get_interaction_strategy("play")
        assert strategy is not None
        assert strategy.type == InteractionLevel.SEMANTIC_DOM.value

    def test_retorna_none_para_inexistente(self):
        cmap = _make_full_capability_map()
        strategy = cmap.get_interaction_strategy("nao_existe")
        assert strategy is None

    def test_fallback_quando_sem_strategies(self):
        """Se capability não tem strategies, cria uma baseada no level."""
        cap = Capability(
            name="test_cap",
            available=True,
            confidence=0.8,
            evidence=["teste"],
            interaction_strategy=InteractionLevel.PLAYER_API,
            strategies=[],
        )
        data = CapabilityMapData(
            player_info=PlayerInfo(),
            capabilities={"test_cap": cap},
        )
        cmap = CapabilityMap(data)
        strategy = cmap.get_interaction_strategy("test_cap")
        assert strategy is not None
        assert strategy.level == InteractionLevel.PLAYER_API
        assert strategy.type == "player_api"


class TestIsValid:
    """Testes para is_valid()."""

    def test_mapa_valido(self):
        cmap = _make_full_capability_map()
        assert cmap.is_valid() is True

    def test_mapa_invalido(self):
        data = CapabilityMapData(
            player_info=PlayerInfo(),
            valid=False,
        )
        cmap = CapabilityMap(data)
        assert cmap.is_valid() is False


class TestInvalidate:
    """Testes para invalidate()."""

    def test_invalida_mapa(self):
        cmap = _make_full_capability_map()
        assert cmap.is_valid() is True
        cmap.invalidate()
        assert cmap.is_valid() is False

    def test_invalidar_mapa_ja_invalido_nao_falha(self):
        data = CapabilityMapData(
            player_info=PlayerInfo(),
            valid=False,
        )
        cmap = CapabilityMap(data)
        cmap.invalidate()
        assert cmap.is_valid() is False


class TestHasRequiredCapabilities:
    """Testes para has_required_capabilities()."""

    def test_mapa_completo_retorna_true(self):
        cmap = _make_full_capability_map()
        assert cmap.has_required_capabilities() is True

    def test_mapa_incompleto_retorna_false(self):
        data = CapabilityMapData(
            player_info=PlayerInfo(),
            capabilities={
                "play": _make_capability("play"),
                "pause": _make_capability("pause"),
            },
        )
        cmap = CapabilityMap(data)
        assert cmap.has_required_capabilities() is False

    def test_mapa_vazio_retorna_false(self):
        data = CapabilityMapData(player_info=PlayerInfo())
        cmap = CapabilityMap(data)
        assert cmap.has_required_capabilities() is False


class TestGetAvailableCapabilities:
    """Testes para get_available_capabilities()."""

    def test_retorna_apenas_available(self):
        caps = {
            "play": _make_capability("play", available=True),
            "pause": _make_capability("pause", available=False),
            "mute": _make_capability("mute", available=True),
        }
        data = CapabilityMapData(
            player_info=PlayerInfo(),
            capabilities=caps,
        )
        cmap = CapabilityMap(data)
        available = cmap.get_available_capabilities()
        assert len(available) == 2
        assert "play" in available
        assert "mute" in available
        assert "pause" not in available


class TestSerialization:
    """Testes para to_json() e from_json()."""

    def test_to_json_retorna_string_valida(self):
        cmap = _make_full_capability_map()
        json_str = cmap.to_json()
        parsed = json.loads(json_str)
        assert "player_info" in parsed
        assert "capabilities" in parsed

    def test_from_json_reconstroi_mapa(self):
        cmap = _make_full_capability_map()
        json_str = cmap.to_json()
        restored = CapabilityMap.from_json(json_str)
        assert restored.is_valid()
        assert restored.player_info.library == "shaka-player"
        assert len(restored.capabilities) == len(REQUIRED_CAPABILITIES)

    def test_round_trip_preserva_capabilities(self):
        cmap = _make_full_capability_map()
        json_str = cmap.to_json()
        restored = CapabilityMap.from_json(json_str)

        for name in REQUIRED_CAPABILITIES:
            original = cmap.get_capability(name)
            restored_cap = restored.get_capability(name)
            assert restored_cap is not None
            assert original is not None
            assert restored_cap.name == original.name
            assert restored_cap.available == original.available
            assert restored_cap.confidence == original.confidence

    def test_round_trip_preserva_strategies(self):
        cmap = _make_full_capability_map()
        json_str = cmap.to_json()
        restored = CapabilityMap.from_json(json_str)

        cap = restored.get_capability("play")
        assert cap is not None
        assert len(cap.strategies) == 1
        assert cap.strategies[0].type == "semantic_dom"

    def test_from_json_invalido_levanta_excecao(self):
        with pytest.raises((json.JSONDecodeError, Exception)):
            CapabilityMap.from_json("json invalido")

    def test_round_trip_mapa_invalidado(self):
        cmap = _make_full_capability_map()
        cmap.invalidate()
        json_str = cmap.to_json()
        restored = CapabilityMap.from_json(json_str)
        assert restored.is_valid() is False


class TestRepr:
    """Testes para __repr__."""

    def test_repr_valido(self):
        cmap = _make_full_capability_map()
        rep = repr(cmap)
        assert "CapabilityMap" in rep
        assert "valid" in rep

    def test_repr_invalido(self):
        cmap = _make_full_capability_map()
        cmap.invalidate()
        rep = repr(cmap)
        assert "INVALID" in rep
