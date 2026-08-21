"""Property-Based Tests para rejeição de coordenadas fixas e índices posicionais.

Feature: player-discovery, Property 20: Rejeição de coordenadas fixas
e índices posicionais

Para qualquer tentativa de interação com o player, strategies baseadas em
coordenadas absolutas (x, y fixos), posição fixa ou índice posicional de
elementos (primeiro botão, segundo item) devem ser rejeitadas.

Validates: Requirements 12.4
"""

import asyncio
from unittest.mock import MagicMock, AsyncMock

import pytest
from hypothesis import given, settings, strategies as st

from src.player_discovery.interaction.manager import (
    InteractionManager,
    InteractionRejectedError,
)
from src.player_discovery.models import (
    Capability,
    CapabilityMap,
    CapabilityMapData,
    InteractionStrategy,
    PlayerInfo,
    InteractionLevel,
    REQUIRED_CAPABILITIES,
)


# --- Constantes de teste ---

# Chaves proibidas que representam coordenadas fixas ou índices
FORBIDDEN_KEYS = [
    "x", "y", "top", "left", "right", "bottom",
    "position_x", "position_y",
    "absolute_x", "absolute_y",
    "index", "nth", "ordinal",
]

# Padrões proibidos em valores string — coordenadas
FORBIDDEN_COORDINATE_PATTERNS = [
    "x: 100", "y: 200", "x=50", "y=300",
    "x: 0", "y: 0", "position: 42",
    "coord_left", "coordinate",
]

# Padrões proibidos em valores string — posicionais
FORBIDDEN_POSITIONAL_PATTERNS = [
    ":nth-child(2)", ":first-child", ":last-child",
    ":nth-of-type(3)", "first button", "second item",
    "third element", "nth element",
    "index=0", "index=5", "index: 3",
]

# Chaves semânticas válidas que NUNCA devem ser rejeitadas
VALID_SEMANTIC_KEYS = [
    "role", "aria_label", "text", "method",
    "js_code", "data_testid", "title",
    "selector_type", "description",
]


# --- Estratégias de geração ---

forbidden_keys_st = st.sampled_from(FORBIDDEN_KEYS)

forbidden_coordinate_values_st = st.sampled_from(
    FORBIDDEN_COORDINATE_PATTERNS
)

forbidden_positional_values_st = st.sampled_from(
    FORBIDDEN_POSITIONAL_PATTERNS
)

valid_semantic_keys_st = st.sampled_from(VALID_SEMANTIC_KEYS)

# Valores semânticos válidos (sem padrões proibidos)
valid_semantic_values_st = st.sampled_from([
    "button", "Play", "Pause", "player.play()",
    "player.pause()", "aria-label", "menu",
    "dialog", "slider", "volume",
    "document.querySelector('[role=button]')",
    "player.mute()", "player.setVolume(0.5)",
])


def _make_capability_map_with_strategy(
    strategy: InteractionStrategy,
    capability_name: str = "play",
) -> CapabilityMap:
    """Cria um CapabilityMap com uma capability que usa a strategy fornecida."""
    cap = Capability(
        name=capability_name,
        available=True,
        confidence=0.95,
        evidence=["teste"],
        interaction_strategy=strategy.level,
        strategies=[strategy],
    )

    capabilities = {}
    # Preencher capabilities obrigatórias com defaults
    for req_cap in REQUIRED_CAPABILITIES:
        if req_cap == capability_name:
            capabilities[req_cap] = cap
        else:
            capabilities[req_cap] = Capability(
                name=req_cap,
                available=False,
                confidence=0.3,
                evidence=[],
                interaction_strategy=InteractionLevel.SEMANTIC_DOM,
                strategies=[],
            )

    data = CapabilityMapData(
        player_info=PlayerInfo(
            library="test-player",
            version="1.0",
            video_elements=["video"],
            discovered_at="2024-01-01T00:00:00Z",
        ),
        capabilities=capabilities,
        discovery_duration_ms=1000,
        version_hash="test-hash",
        valid=True,
    )
    return CapabilityMap(data)


class TestProperty20RejeicaoCoordenadas:
    """Feature: player-discovery, Property 20: Rejeição de coordenadas
    fixas e índices posicionais

    Para qualquer tentativa de interação com o player, strategies baseadas
    em coordenadas absolutas (x, y fixos), posição fixa ou índice posicional
    devem ser rejeitadas.

    **Validates: Requirements 12.4**
    """

    @settings(max_examples=100)
    @given(
        forbidden_key=forbidden_keys_st,
        value=st.integers(min_value=0, max_value=1920),
    )
    def test_chaves_proibidas_sempre_rejeitadas(
        self, forbidden_key: str, value: int
    ) -> None:
        """Strategies com chaves proibidas (x, y, top, left, index, nth,
        etc.) no dict de details sempre levantam InteractionRejectedError.

        **Validates: Requirements 12.4**
        """
        manager = InteractionManager()

        strategy = InteractionStrategy(
            level=InteractionLevel.SEMANTIC_DOM,
            type="semantic_dom",
            details={forbidden_key: value},
        )

        with pytest.raises(InteractionRejectedError):
            manager._validate_strategy(strategy)

    @settings(max_examples=100)
    @given(
        forbidden_value=st.one_of(
            forbidden_coordinate_values_st,
            forbidden_positional_values_st,
        ),
        key=st.sampled_from([
            "locator", "selector", "target", "description",
        ]),
    )
    def test_padroes_proibidos_em_valores_string_sempre_rejeitados(
        self, forbidden_value: str, key: str
    ) -> None:
        """Strategies com padrões proibidos em valores string (coordenadas
        como 'x: 100', 'y: 200' ou posicionais como ':nth-child',
        'first', 'second') sempre levantam InteractionRejectedError.

        **Validates: Requirements 12.4**
        """
        manager = InteractionManager()

        strategy = InteractionStrategy(
            level=InteractionLevel.VISUAL_FALLBACK,
            type="visual_fallback",
            details={key: forbidden_value},
        )

        with pytest.raises(InteractionRejectedError):
            manager._validate_strategy(strategy)

    @settings(max_examples=100)
    @given(
        key=valid_semantic_keys_st,
        value=valid_semantic_values_st,
    )
    def test_chaves_semanticas_validas_nunca_rejeitadas(
        self, key: str, value: str
    ) -> None:
        """Strategies com chaves semânticas válidas (role, aria_label,
        text, method, js_code) e valores sem padrões proibidos NUNCA
        devem levantar InteractionRejectedError.

        **Validates: Requirements 12.4**
        """
        manager = InteractionManager()

        strategy = InteractionStrategy(
            level=InteractionLevel.SEMANTIC_DOM,
            type="semantic_dom",
            details={key: value},
        )

        # Não deve levantar exceção
        manager._validate_strategy(strategy)

    @settings(max_examples=100)
    @given(
        forbidden_key=forbidden_keys_st,
        extra_valid_key=valid_semantic_keys_st,
        extra_valid_value=valid_semantic_values_st,
    )
    def test_chave_proibida_com_chaves_validas_ainda_rejeita(
        self, forbidden_key: str, extra_valid_key: str,
        extra_valid_value: str,
    ) -> None:
        """Mesmo que uma strategy contenha chaves válidas, a presença de
        QUALQUER chave proibida deve resultar em rejeição.

        **Validates: Requirements 12.4**
        """
        manager = InteractionManager()

        details = {
            extra_valid_key: extra_valid_value,
            forbidden_key: 150,
        }

        strategy = InteractionStrategy(
            level=InteractionLevel.SEMANTIC_DOM,
            type="semantic_dom",
            details=details,
        )

        with pytest.raises(InteractionRejectedError):
            manager._validate_strategy(strategy)

    @settings(max_examples=100)
    @given(
        forbidden_key=forbidden_keys_st,
        value=st.integers(min_value=0, max_value=1920),
        capability_name=st.sampled_from(list(REQUIRED_CAPABILITIES)),
    )
    def test_execute_rejeita_strategy_com_coordenadas_fixas(
        self, forbidden_key: str, value: int, capability_name: str,
    ) -> None:
        """O método execute() completo deve rejeitar interações com
        coordenadas fixas — validando que a rejeição acontece no
        fluxo real de interação.

        **Validates: Requirements 12.4**
        """
        manager = InteractionManager()

        strategy = InteractionStrategy(
            level=InteractionLevel.SEMANTIC_DOM,
            type="semantic_dom",
            details={forbidden_key: value},
        )

        cmap = _make_capability_map_with_strategy(
            strategy, capability_name
        )

        page = MagicMock()
        page.evaluate = AsyncMock(return_value=True)
        page.locator = MagicMock()

        with pytest.raises(InteractionRejectedError):
            asyncio.get_event_loop().run_until_complete(
                manager.execute(
                    page, capability_name, "click", cmap
                )
            )
