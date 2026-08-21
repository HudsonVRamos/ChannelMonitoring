"""Property-Based Tests para idempotência do cache do DiscoveryEngine.

Feature: player-discovery, Property 5: Idempotência do cache —
discovery válido rejeita re-execução

Para qualquer estado onde o Capability Map está marcado como válido,
chamadas subsequentes ao Discovery Engine devem retornar o mesmo mapa
sem re-executar a análise completa.

Validates: Requirements 3.2
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from hypothesis import given, settings, strategies as st

from src.player_discovery.discovery.engine import DiscoveryEngine
from src.player_discovery.models import (
    Capability,
    CapabilityMap,
    CapabilityMapData,
    InteractionStrategy,
    PlayerInfo,
    InteractionLevel,
    REQUIRED_CAPABILITIES,
)


# --- Estratégias de geração ---

interaction_levels = st.sampled_from([
    InteractionLevel.PLAYER_API,
    InteractionLevel.SEMANTIC_DOM,
    InteractionLevel.VISUAL_FALLBACK,
])


def interaction_strategy_st():
    """Gera uma InteractionStrategy válida."""
    return st.builds(
        InteractionStrategy,
        level=interaction_levels,
        type=st.sampled_from([
            "player_api", "semantic_dom", "visual_fallback"
        ]),
        details=st.just({}),
    )


def capability_st(name: str):
    """Gera uma Capability válida para o nome fornecido."""
    return st.builds(
        Capability,
        name=st.just(name),
        available=st.booleans(),
        confidence=st.floats(
            min_value=0.0, max_value=1.0,
            allow_nan=False, allow_infinity=False,
        ),
        evidence=st.lists(
            st.text(min_size=1, max_size=50),
            min_size=0, max_size=5,
        ),
        interaction_strategy=interaction_levels,
        strategies=st.lists(
            interaction_strategy_st(),
            min_size=0, max_size=3,
        ),
    )


@st.composite
def valid_capability_map_st(draw):
    """Gera um CapabilityMap válido (valid=True) com capabilities obrigatórias.

    O mapa gerado sempre está marcado como válido, simulando um cache
    válido que deve ser reutilizado pelo DiscoveryEngine.
    """
    # Gerar player_info
    library = draw(st.one_of(st.none(), st.text(min_size=1, max_size=30)))
    version = draw(st.one_of(st.none(), st.text(min_size=1, max_size=15)))
    video_elements = draw(st.lists(
        st.text(min_size=1, max_size=30),
        min_size=0, max_size=3,
    ))
    discovered_at = draw(st.text(min_size=0, max_size=30))

    player_info = PlayerInfo(
        library=library,
        version=version,
        video_elements=video_elements,
        discovered_at=discovered_at,
    )

    # Gerar capabilities obrigatórias
    capabilities = {}
    for cap_name in REQUIRED_CAPABILITIES:
        capabilities[cap_name] = draw(capability_st(cap_name))

    # Opcionalmente adicionar capabilities extras
    extra_names = draw(st.lists(
        st.text(
            alphabet=st.characters(whitelist_categories=("Ll",)),
            min_size=3, max_size=15,
        ).filter(lambda n: n not in REQUIRED_CAPABILITIES),
        min_size=0, max_size=2,
    ))
    for extra_name in extra_names:
        capabilities[extra_name] = draw(capability_st(extra_name))

    data = CapabilityMapData(
        player_info=player_info,
        capabilities=capabilities,
        discovery_duration_ms=draw(
            st.integers(min_value=0, max_value=120000)
        ),
        version_hash=draw(st.text(min_size=0, max_size=64)),
        valid=True,  # Sempre válido para testar idempotência do cache
    )

    return CapabilityMap(data)


class TestProperty5IdempotenciaDoCache:
    """Feature: player-discovery, Property 5: Idempotência do cache —
    discovery válido rejeita re-execução

    Para qualquer estado onde o Capability Map está marcado como válido,
    chamadas subsequentes ao Discovery Engine devem retornar o mesmo mapa
    sem re-executar a análise completa.

    **Validates: Requirements 3.2**
    """

    @settings(max_examples=100)
    @given(cmap=valid_capability_map_st())
    def test_discover_retorna_mesmo_objeto_quando_cache_valido(
        self, cmap: CapabilityMap
    ) -> None:
        """Para qualquer CapabilityMap válido em cache, discover() retorna
        o EXATO mesmo objeto (identidade com `is`) sem re-execução.

        Verifica que o DiscoveryEngine retorna a referência ao mapa
        em cache quando este está válido, sem criar novo objeto.

        **Validates: Requirements 3.2**
        """
        engine = DiscoveryEngine()
        # Simular que o mapa já está em cache
        engine._cached_map = cmap

        # Criar page mock (não deve ser chamado)
        page = MagicMock()
        page.evaluate = AsyncMock()

        # Executar discover — deve retornar o cache sem chamar analyzers
        result = asyncio.get_event_loop().run_until_complete(
            engine.discover(page)
        )

        # Deve retornar o EXATO MESMO objeto (identidade)
        assert result is cmap, (
            "discover() não retornou o mesmo objeto em cache — "
            "deveria retornar a referência ao mapa válido"
        )

    @settings(max_examples=100)
    @given(cmap=valid_capability_map_st())
    def test_discover_nao_chama_analyzers_quando_cache_valido(
        self, cmap: CapabilityMap
    ) -> None:
        """Para qualquer CapabilityMap válido em cache, discover() não
        deve chamar page.evaluate (indicando que nenhum analyzer executou).

        **Validates: Requirements 3.2**
        """
        engine = DiscoveryEngine()
        engine._cached_map = cmap

        # Criar page mock que rastreia chamadas
        page = MagicMock()
        page.evaluate = AsyncMock()

        asyncio.get_event_loop().run_until_complete(
            engine.discover(page)
        )

        # page.evaluate NÃO deve ter sido chamado (analyzers não executaram)
        page.evaluate.assert_not_called()

    @settings(max_examples=100)
    @given(
        cmap=valid_capability_map_st(),
        num_calls=st.integers(min_value=2, max_value=5),
    )
    def test_multiplas_chamadas_retornam_mesmo_objeto(
        self, cmap: CapabilityMap, num_calls: int
    ) -> None:
        """Múltiplas chamadas sequenciais a discover() com cache válido
        retornam o mesmo objeto em todas as chamadas.

        **Validates: Requirements 3.2**
        """
        engine = DiscoveryEngine()
        engine._cached_map = cmap

        page = MagicMock()
        page.evaluate = AsyncMock()

        loop = asyncio.get_event_loop()

        # Chamar discover() N vezes
        results = []
        for _ in range(num_calls):
            result = loop.run_until_complete(engine.discover(page))
            results.append(result)

        # Todos os resultados devem ser o MESMO objeto
        for i, result in enumerate(results):
            assert result is cmap, (
                f"Chamada {i + 1}/{num_calls} retornou objeto diferente — "
                "todas as chamadas devem retornar a mesma referência"
            )

        # Nenhum analyzer deve ter sido invocado
        page.evaluate.assert_not_called()

    @settings(max_examples=100)
    @given(cmap=valid_capability_map_st())
    def test_cached_map_property_retorna_mapa_apos_cache(
        self, cmap: CapabilityMap
    ) -> None:
        """A propriedade cached_map deve refletir o mapa em cache
        após ser configurado.

        **Validates: Requirements 3.2**
        """
        engine = DiscoveryEngine()
        engine._cached_map = cmap

        # A propriedade cached_map deve retornar o mesmo objeto
        assert engine.cached_map is cmap, (
            "cached_map não retorna o objeto esperado"
        )

        # Confirmar que is_valid() é True (pré-condição do teste)
        assert cmap.is_valid() is True, (
            "Pré-condição violada: mapa deveria estar válido"
        )
