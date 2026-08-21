"""Property-Based Tests para debounce de mutações do MutationObserverWatcher.

Feature: player-discovery, Property 6: Debounce de mutações agrupa dentro da janela

Para qualquer sequência de mutações DOM com timestamps dentro da janela
de debounce configurada, o MutationObserver Watcher deve agrupá-las em
um único evento de avaliação (e não disparar múltiplas avaliações).

Validates: Requirements 4.1
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock

from hypothesis import given, settings, strategies as st, HealthCheck

from src.player_discovery.discovery.mutation_watcher import MutationObserverWatcher
from src.player_discovery.models.capability_map import CapabilityMap, CapabilityMapData
from src.player_discovery.models import PlayerInfo, REQUIRED_CAPABILITIES, Capability, InteractionLevel


# --- Estratégias de geração ---

mutation_types = st.sampled_from(["childList", "attributes", "characterData"])

structural_attributes = st.sampled_from([
    "role", "aria-label", "aria-haspopup", "aria-controls",
    "aria-expanded", "tabindex", "title", "data-testid",
])


def mutation_st():
    """Gera uma mutação DOM válida (estrutural para garantir callback)."""
    return st.fixed_dictionaries({
        "type": st.just("childList"),
        "attributeName": st.none(),
        "addedNodes": st.integers(min_value=1, max_value=5),
        "removedNodes": st.integers(min_value=0, max_value=3),
        "target": st.sampled_from(["DIV", "BUTTON", "SPAN", "VIDEO"]),
    })


def mutation_batch_st():
    """Gera um batch de mutações (1-5 mutações por batch)."""
    return st.lists(mutation_st(), min_size=1, max_size=5)


def _create_minimal_capability_map() -> CapabilityMap:
    """Cria um CapabilityMap mínimo válido para uso nos testes."""
    capabilities = {}
    for name in REQUIRED_CAPABILITIES:
        capabilities[name] = Capability(
            name=name,
            available=True,
            confidence=0.8,
            evidence=["test"],
            interaction_strategy=InteractionLevel.SEMANTIC_DOM,
            strategies=[],
        )
    data = CapabilityMapData(
        player_info=PlayerInfo(
            library="test", version="1.0",
            video_elements=["video"], discovered_at="",
        ),
        capabilities=capabilities,
        discovery_duration_ms=100,
        version_hash="test",
        valid=True,
    )
    return CapabilityMap(data)


class TestProperty6DebounceDeMutacoes:
    """Feature: player-discovery, Property 6: Debounce de mutações agrupa dentro da janela

    Para qualquer sequência de mutações DOM com timestamps dentro da janela
    de debounce configurada, o MutationObserver Watcher deve agrupá-las em
    um único evento de avaliação (e não disparar múltiplas avaliações).

    **Validates: Requirements 4.1**
    """

    @settings(max_examples=100, deadline=None)
    @given(
        num_batches=st.integers(min_value=2, max_value=10),
        mutations_per_batch=st.integers(min_value=1, max_value=5),
    )
    def test_multiplos_batches_dentro_da_janela_geram_unico_callback(
        self, num_batches: int, mutations_per_batch: int
    ) -> None:
        """Para qualquer número de batches de mutações enviados dentro da
        janela de debounce, o callback deve ser chamado exatamente UMA vez.

        Simula envio rápido de mutações (intervalos < debounce_window)
        e verifica que todas são coalescidas em uma única avaliação.

        **Validates: Requirements 4.1**
        """
        debounce_ms = 50  # Curto para testes rápidos
        watcher = MutationObserverWatcher(debounce_window_ms=debounce_ms)

        # Registrar callback e contar invocações
        callback_calls: list[list[dict]] = []
        watcher.on_structural_change(lambda mutations: callback_calls.append(mutations))

        # Simular estado running sem precisar de page real
        watcher._running = True
        watcher._capability_map = _create_minimal_capability_map()

        async def run_test():
            # Enviar múltiplos batches com intervalos menores que debounce
            interval_between = (debounce_ms / 1000.0) * 0.3  # 30% da janela

            for _ in range(num_batches):
                batch = [
                    {
                        "type": "childList",
                        "attributeName": None,
                        "addedNodes": 1,
                        "removedNodes": 0,
                        "target": "DIV",
                    }
                    for _ in range(mutations_per_batch)
                ]
                mutations_json = json.dumps(batch)
                await watcher._on_mutations_received(mutations_json)
                await asyncio.sleep(interval_between)

            # Aguardar debounce expirar completamente
            await asyncio.sleep((debounce_ms / 1000.0) * 2.0)

        asyncio.run(run_test())

        # O callback deve ter sido chamado EXATAMENTE uma vez
        assert len(callback_calls) == 1, (
            f"Callback chamado {len(callback_calls)} vezes — "
            f"deveria ser exatamente 1 para {num_batches} batches "
            f"dentro da janela de debounce ({debounce_ms}ms)"
        )

    @settings(max_examples=100, deadline=None)
    @given(
        num_batches=st.integers(min_value=2, max_value=10),
        mutations_per_batch=st.integers(min_value=1, max_value=5),
    )
    def test_todas_mutacoes_coalescidas_no_unico_callback(
        self, num_batches: int, mutations_per_batch: int
    ) -> None:
        """Verifica que TODAS as mutações de todos os batches enviados
        dentro da janela de debounce são passadas ao callback na
        única invocação.

        O total de mutações estruturais no callback deve corresponder
        ao total de mutações estruturais enviadas.

        **Validates: Requirements 4.1**
        """
        debounce_ms = 50
        watcher = MutationObserverWatcher(debounce_window_ms=debounce_ms)

        callback_calls: list[list[dict]] = []
        watcher.on_structural_change(lambda mutations: callback_calls.append(mutations))

        watcher._running = True
        watcher._capability_map = _create_minimal_capability_map()

        total_mutations_sent = num_batches * mutations_per_batch

        async def run_test():
            interval_between = (debounce_ms / 1000.0) * 0.3

            for _ in range(num_batches):
                batch = [
                    {
                        "type": "childList",
                        "attributeName": None,
                        "addedNodes": 1,
                        "removedNodes": 0,
                        "target": "DIV",
                    }
                    for _ in range(mutations_per_batch)
                ]
                mutations_json = json.dumps(batch)
                await watcher._on_mutations_received(mutations_json)
                await asyncio.sleep(interval_between)

            # Aguardar debounce expirar
            await asyncio.sleep((debounce_ms / 1000.0) * 2.0)

        asyncio.run(run_test())

        # Deve ter exatamente uma chamada
        assert len(callback_calls) == 1, (
            f"Callback chamado {len(callback_calls)} vezes — esperado 1"
        )

        # Todas as mutações estruturais devem estar no callback
        received_mutations = callback_calls[0]
        assert len(received_mutations) == total_mutations_sent, (
            f"Callback recebeu {len(received_mutations)} mutações — "
            f"esperado {total_mutations_sent} "
            f"({num_batches} batches × {mutations_per_batch} mutações)"
        )

    @settings(max_examples=100, deadline=None)
    @given(
        num_batches=st.integers(min_value=2, max_value=8),
    )
    def test_nenhum_callback_disparado_antes_do_debounce_expirar(
        self, num_batches: int
    ) -> None:
        """Para qualquer sequência de batches enviados, nenhum callback
        deve ser disparado ANTES da janela de debounce expirar.

        Verifica que o debounce efetivamente agrupa e atrasa a avaliação.

        **Validates: Requirements 4.1**
        """
        debounce_ms = 80  # Um pouco maior para ter tempo de verificar
        watcher = MutationObserverWatcher(debounce_window_ms=debounce_ms)

        callback_calls: list[list[dict]] = []
        watcher.on_structural_change(lambda mutations: callback_calls.append(mutations))

        watcher._running = True
        watcher._capability_map = _create_minimal_capability_map()

        async def run_test():
            interval_between = (debounce_ms / 1000.0) * 0.2

            for _ in range(num_batches):
                batch = [
                    {
                        "type": "childList",
                        "attributeName": None,
                        "addedNodes": 1,
                        "removedNodes": 0,
                        "target": "BUTTON",
                    }
                ]
                mutations_json = json.dumps(batch)
                await watcher._on_mutations_received(mutations_json)
                await asyncio.sleep(interval_between)

            # Verificar ANTES do debounce expirar — nenhum callback ainda
            assert len(callback_calls) == 0, (
                f"Callback disparado prematuramente ({len(callback_calls)} "
                f"vezes) antes do debounce expirar"
            )

            # Agora aguardar debounce expirar
            await asyncio.sleep((debounce_ms / 1000.0) * 2.0)

        asyncio.run(run_test())

        # Após o debounce expirar, deve ter exatamente 1 chamada
        assert len(callback_calls) == 1, (
            f"Após debounce, callback chamado {len(callback_calls)} vezes — "
            f"esperado 1"
        )
