"""Property-Based Tests para hierarquia de interação e fallback.

Feature: player-discovery, Property 19: Hierarquia de interação —
strategies ordenadas e fallback correto

Para qualquer capability no CapabilityMap, as strategies disponíveis
devem estar ordenadas por nível (1: player_api, 2: semantic_dom,
3: visual_fallback), e durante execução, o fallback deve seguir
estritamente: tentar Nível 1 → se falhar, Nível 2 → se falhar, Nível 3.

Validates: Requirements 12.1, 12.2, 12.3
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from hypothesis import given, settings, strategies as st

from src.player_discovery.interaction.manager import InteractionManager
from src.player_discovery.models import (
    Capability,
    CapabilityMap,
    CapabilityMapData,
    InteractionLevel,
    InteractionResult,
    InteractionStrategy,
    PlayerInfo,
)


# --- Estratégias de geração ---

interaction_levels = st.sampled_from([
    InteractionLevel.PLAYER_API,
    InteractionLevel.SEMANTIC_DOM,
    InteractionLevel.VISUAL_FALLBACK,
])

# Mapa de ordem esperada dos níveis
LEVEL_ORDER = {
    InteractionLevel.PLAYER_API: 1,
    InteractionLevel.SEMANTIC_DOM: 2,
    InteractionLevel.VISUAL_FALLBACK: 3,
}


def safe_details_for_level(level: InteractionLevel) -> dict:
    """Gera detalhes seguros (sem padrões proibidos) para cada nível."""
    if level == InteractionLevel.PLAYER_API:
        return {"method": "player.play()"}
    elif level == InteractionLevel.SEMANTIC_DOM:
        return {"role": "button", "aria_label": "Play"}
    else:
        return {"description": "botão play no centro"}


def interaction_strategy_for_level(level: InteractionLevel) -> InteractionStrategy:
    """Cria uma InteractionStrategy válida para o nível dado."""
    return InteractionStrategy(
        level=level,
        type=level.value,
        details=safe_details_for_level(level),
    )


@st.composite
def random_strategies_st(draw):
    """Gera uma lista de strategies com níveis aleatórios em ordem aleatória.

    Garante pelo menos 1 strategy e no máximo uma de cada nível.
    """
    available_levels = list(InteractionLevel)
    # Escolher subconjunto aleatório de níveis (1 a 3)
    num_levels = draw(st.integers(min_value=1, max_value=3))
    selected_levels = draw(
        st.permutations(available_levels).map(lambda x: x[:num_levels])
    )

    strategies = [
        interaction_strategy_for_level(level)
        for level in selected_levels
    ]
    return strategies


@st.composite
def capability_with_random_strategies_st(draw):
    """Gera uma Capability com strategies em ordem aleatória."""
    strategies = draw(random_strategies_st())
    cap_name = draw(st.sampled_from([
        "play", "pause", "mute", "unmute",
        "audio_selection", "subtitle_selection",
    ]))

    return Capability(
        name=cap_name,
        available=True,
        confidence=draw(st.floats(
            min_value=0.7, max_value=1.0,
            allow_nan=False, allow_infinity=False,
        )),
        evidence=["teste comportamental confirmado"],
        interaction_strategy=strategies[0].level,
        strategies=strategies,
    )


@st.composite
def capability_map_with_capability_st(draw):
    """Gera um CapabilityMap contendo uma capability com strategies aleatórias."""
    cap = draw(capability_with_random_strategies_st())

    capabilities = {cap.name: cap}
    data = CapabilityMapData(
        player_info=PlayerInfo(
            library="test-player",
            version="1.0",
            video_elements=["video"],
            discovered_at="2024-01-01T00:00:00.000Z",
        ),
        capabilities=capabilities,
        valid=True,
    )
    return CapabilityMap(data), cap


class TestProperty19HierarquiaInteracaoFallback:
    """Feature: player-discovery, Property 19: Hierarquia de interação —
    strategies ordenadas e fallback correto

    Para qualquer capability no CapabilityMap, as strategies disponíveis
    devem estar ordenadas por nível (1: player_api, 2: semantic_dom,
    3: visual_fallback), e durante execução, o fallback deve seguir
    estritamente: tentar Nível 1 → se falhar, Nível 2 → se falhar, Nível 3.

    **Validates: Requirements 12.1, 12.2, 12.3**
    """

    @settings(max_examples=100)
    @given(cap=capability_with_random_strategies_st())
    def test_get_ordered_strategies_retorna_ordenado_por_nivel(
        self, cap: Capability
    ) -> None:
        """Para qualquer capability com strategies em qualquer ordem,
        _get_ordered_strategies() deve retornar ordenadas:
        PLAYER_API < SEMANTIC_DOM < VISUAL_FALLBACK.

        **Validates: Requirements 12.1, 12.2, 12.3**
        """
        manager = InteractionManager()

        ordered = manager._get_ordered_strategies(cap)

        # Verificar que a lista está ordenada por nível
        levels = [LEVEL_ORDER[s.level] for s in ordered]
        assert levels == sorted(levels), (
            f"Strategies não estão ordenadas por nível: "
            f"obtido {[s.level.value for s in ordered]}, "
            f"esperado ordem PLAYER_API < SEMANTIC_DOM < VISUAL_FALLBACK"
        )

    @settings(max_examples=100)
    @given(cap=capability_with_random_strategies_st())
    def test_get_ordered_strategies_preserva_todos_os_elementos(
        self, cap: Capability
    ) -> None:
        """Para qualquer capability, _get_ordered_strategies() deve
        preservar todas as strategies (mesmo conjunto, apenas reordenado).

        **Validates: Requirements 12.3**
        """
        manager = InteractionManager()

        ordered = manager._get_ordered_strategies(cap)

        # Mesmo número de strategies
        assert len(ordered) == len(cap.strategies), (
            f"Número de strategies alterado: "
            f"original={len(cap.strategies)}, ordenado={len(ordered)}"
        )

        # Mesmos níveis (como conjunto)
        original_levels = {s.level for s in cap.strategies}
        ordered_levels = {s.level for s in ordered}
        assert original_levels == ordered_levels, (
            f"Níveis alterados: original={original_levels}, "
            f"ordenado={ordered_levels}"
        )

    @settings(max_examples=100)
    @given(data=capability_map_with_capability_st())
    def test_execute_fallback_segue_ordem_estrita(
        self, data: tuple[CapabilityMap, Capability]
    ) -> None:
        """Para qualquer capability com múltiplas strategies onde todas
        falham, execute() deve tentar níveis na ordem estrita:
        PLAYER_API → SEMANTIC_DOM → VISUAL_FALLBACK.

        Verifica que o fallback segue a hierarquia correta mockando
        todas as execuções para falhar e verificando a ordem de chamada.

        **Validates: Requirements 12.2**
        """
        cmap, cap = data

        manager = InteractionManager()
        page = MagicMock()
        page.evaluate = AsyncMock(
            side_effect=RuntimeError("API falhou")
        )
        page.get_by_role = MagicMock(return_value=MagicMock(
            click=AsyncMock(side_effect=RuntimeError("DOM falhou"))
        ))
        page.get_by_label = MagicMock(return_value=MagicMock(
            click=AsyncMock(side_effect=RuntimeError("DOM falhou"))
        ))
        page.get_by_text = MagicMock(return_value=MagicMock(
            first=MagicMock(
                click=AsyncMock(side_effect=RuntimeError("Visual falhou"))
            )
        ))
        page.locator = MagicMock(return_value=MagicMock(
            click=AsyncMock(side_effect=RuntimeError("Visual falhou"))
        ))

        # Rastrear a ordem de execução dos níveis
        execution_order = []
        original_execute_by_level = manager._execute_by_level

        async def tracking_execute_by_level(page, strategy, action):
            execution_order.append(strategy.level)
            return InteractionResult(
                success=False,
                level_used=strategy.level,
                duration_ms=0,
                error=f"Mock falha no {strategy.level.value}",
            )

        loop = asyncio.get_event_loop()

        with patch.object(
            manager, "_execute_by_level", side_effect=tracking_execute_by_level
        ):
            result = loop.run_until_complete(
                manager.execute(page, cap.name, "click", cmap)
            )

        # Resultado deve ser falha (todos falharam)
        assert result.success is False

        # Verificar que a ordem de execução está ordenada por nível
        if len(execution_order) > 1:
            order_values = [LEVEL_ORDER[level] for level in execution_order]
            assert order_values == sorted(order_values), (
                f"Fallback não seguiu a ordem hierárquica correta: "
                f"obtido {[l.value for l in execution_order]}, "
                f"esperado ordem crescente de nível"
            )

    @settings(max_examples=100)
    @given(data=capability_map_with_capability_st())
    def test_execute_para_no_primeiro_sucesso(
        self, data: tuple[CapabilityMap, Capability]
    ) -> None:
        """Para qualquer capability com múltiplas strategies, execute()
        deve parar no primeiro nível que retorna sucesso, sem tentar
        os níveis subsequentes.

        **Validates: Requirements 12.2**
        """
        cmap, cap = data

        manager = InteractionManager()
        page = MagicMock()

        # Rastrear execuções
        execution_order = []
        ordered_strategies = manager._get_ordered_strategies(cap)

        if not ordered_strategies:
            return  # Nada a testar se não há strategies

        # O primeiro nível (na ordem) sempre retorna sucesso
        first_level = ordered_strategies[0].level

        async def tracking_execute_by_level(page, strategy, action):
            execution_order.append(strategy.level)
            if strategy.level == first_level:
                return InteractionResult(
                    success=True,
                    level_used=strategy.level,
                    duration_ms=10,
                )
            return InteractionResult(
                success=False,
                level_used=strategy.level,
                duration_ms=0,
                error="Falhou",
            )

        loop = asyncio.get_event_loop()

        with patch.object(
            manager, "_execute_by_level", side_effect=tracking_execute_by_level
        ):
            result = loop.run_until_complete(
                manager.execute(page, cap.name, "click", cmap)
            )

        # Resultado deve ser sucesso
        assert result.success is True
        assert result.level_used == first_level

        # Deve ter tentado apenas o primeiro nível
        assert len(execution_order) == 1, (
            f"Executou {len(execution_order)} níveis após sucesso no primeiro: "
            f"{[l.value for l in execution_order]}"
        )
