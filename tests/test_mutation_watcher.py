"""Testes unitários do MutationObserverWatcher.

Testa o componente de observação de mudanças no DOM incluindo:
- Classificação de mutações (estrutural vs cosmética)
- Debounce/coalescing de mutações
- Callback para mudanças estruturais
- Start/stop do watcher
- Comportamento com MutationObserver via Playwright

Requirements testados: 4.1, 4.2, 4.3, 4.4
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.player_discovery.discovery.mutation_watcher import (
    COSMETIC_ATTRIBUTES,
    STRUCTURAL_ATTRIBUTES,
    STRUCTURAL_ATTRIBUTE_PREFIXES,
    MutationObserverWatcher,
    classify_mutation,
)
from src.player_discovery.models.capability import (
    Capability,
    CapabilityMapData,
    InteractionStrategy,
    PlayerInfo,
)
from src.player_discovery.models.capability_map import (
    CapabilityMap,
    REQUIRED_CAPABILITIES,
)
from src.player_discovery.models.enums import InteractionLevel


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def mock_page():
    """Mock de Page do Playwright."""
    page = AsyncMock()
    page.evaluate = AsyncMock(return_value=None)
    page.expose_function = AsyncMock(return_value=None)
    return page


@pytest.fixture
def valid_capability_map():
    """CapabilityMap válido com todas as capabilities obrigatórias."""
    caps = {}
    for name in REQUIRED_CAPABILITIES:
        caps[name] = Capability(
            name=name,
            available=True,
            confidence=0.85,
            evidence=[f"[DOM] Encontrado controle {name}"],
            interaction_strategy=InteractionLevel.SEMANTIC_DOM,
            strategies=[
                InteractionStrategy(
                    level=InteractionLevel.SEMANTIC_DOM,
                    type="semantic_dom",
                    details={"capability": name},
                )
            ],
        )
    data = CapabilityMapData(
        player_info=PlayerInfo(
            library="shaka-player",
            version="4.0.0",
            video_elements=["video"],
            discovered_at="2024-01-01T00:00:00Z",
        ),
        capabilities=caps,
        discovery_duration_ms=1000,
        version_hash="abc123",
        valid=True,
    )
    return CapabilityMap(data)


@pytest.fixture
def watcher():
    """Instância do MutationObserverWatcher com debounce curto para testes."""
    return MutationObserverWatcher(debounce_window_ms=50)


# ============================================================
# Testes de classify_mutation
# ============================================================


class TestClassifyMutation:
    """Testes da função classify_mutation."""

    def test_childlist_with_added_nodes_is_structural(self):
        """Criação de nós filhos é mudança estrutural."""
        mutation = {
            "type": "childList",
            "addedNodes": 2,
            "removedNodes": 0,
        }
        assert classify_mutation(mutation) == "structural"

    def test_childlist_with_removed_nodes_is_structural(self):
        """Remoção de nós filhos é mudança estrutural."""
        mutation = {
            "type": "childList",
            "addedNodes": 0,
            "removedNodes": 1,
        }
        assert classify_mutation(mutation) == "structural"

    def test_childlist_with_no_changes_is_cosmetic(self):
        """childList sem adição/remoção é cosmético."""
        mutation = {
            "type": "childList",
            "addedNodes": 0,
            "removedNodes": 0,
        }
        assert classify_mutation(mutation) == "cosmetic"

    def test_character_data_is_cosmetic(self):
        """Mudanças de texto (characterData) são cosméticas."""
        mutation = {"type": "characterData"}
        assert classify_mutation(mutation) == "cosmetic"

    def test_attribute_role_is_structural(self):
        """Mudança no atributo 'role' é estrutural."""
        mutation = {"type": "attributes", "attributeName": "role"}
        assert classify_mutation(mutation) == "structural"

    def test_attribute_aria_label_is_structural(self):
        """Mudança no atributo 'aria-label' é estrutural."""
        mutation = {"type": "attributes", "attributeName": "aria-label"}
        assert classify_mutation(mutation) == "structural"

    def test_attribute_tabindex_is_structural(self):
        """Mudança no atributo 'tabindex' é estrutural."""
        mutation = {"type": "attributes", "attributeName": "tabindex"}
        assert classify_mutation(mutation) == "structural"

    def test_attribute_title_is_structural(self):
        """Mudança no atributo 'title' é estrutural."""
        mutation = {"type": "attributes", "attributeName": "title"}
        assert classify_mutation(mutation) == "structural"

    def test_attribute_data_prefix_is_structural(self):
        """Mudança em atributo com prefixo 'data-' é estrutural."""
        mutation = {"type": "attributes", "attributeName": "data-testid"}
        assert classify_mutation(mutation) == "structural"

    def test_attribute_aria_prefix_is_structural(self):
        """Mudança em atributo com prefixo 'aria-' é estrutural."""
        mutation = {"type": "attributes", "attributeName": "aria-expanded"}
        assert classify_mutation(mutation) == "structural"

    def test_attribute_style_is_cosmetic(self):
        """Mudança no atributo 'style' é cosmética."""
        mutation = {"type": "attributes", "attributeName": "style"}
        assert classify_mutation(mutation) == "cosmetic"

    def test_attribute_class_is_cosmetic(self):
        """Mudança no atributo 'class' é cosmética."""
        mutation = {"type": "attributes", "attributeName": "class"}
        assert classify_mutation(mutation) == "cosmetic"

    def test_attribute_id_is_cosmetic(self):
        """Mudança no atributo 'id' é cosmética."""
        mutation = {"type": "attributes", "attributeName": "id"}
        assert classify_mutation(mutation) == "cosmetic"

    def test_unknown_attribute_is_cosmetic(self):
        """Atributo desconhecido é tratado como cosmético."""
        mutation = {"type": "attributes", "attributeName": "custom-thing"}
        assert classify_mutation(mutation) == "cosmetic"

    def test_unknown_type_is_cosmetic(self):
        """Tipo de mutação desconhecido é cosmético."""
        mutation = {"type": "unknown_type"}
        assert classify_mutation(mutation) == "cosmetic"

    def test_empty_mutation_is_cosmetic(self):
        """Mutação vazia é cosmética."""
        assert classify_mutation({}) == "cosmetic"

    def test_all_structural_attributes_classified_correctly(self):
        """Todos os atributos na lista STRUCTURAL_ATTRIBUTES são estruturais."""
        for attr in STRUCTURAL_ATTRIBUTES:
            mutation = {"type": "attributes", "attributeName": attr}
            assert classify_mutation(mutation) == "structural", (
                f"Atributo '{attr}' deveria ser structural"
            )

    def test_all_cosmetic_attributes_classified_correctly(self):
        """Todos os atributos na lista COSMETIC_ATTRIBUTES são cosméticos."""
        for attr in COSMETIC_ATTRIBUTES:
            mutation = {"type": "attributes", "attributeName": attr}
            assert classify_mutation(mutation) == "cosmetic", (
                f"Atributo '{attr}' deveria ser cosmetic"
            )


# ============================================================
# Testes de start/stop
# ============================================================


class TestStartStop:
    """Testes de inicialização e parada do watcher."""

    @pytest.mark.asyncio
    async def test_start_sets_running_state(
        self, watcher, mock_page, valid_capability_map
    ):
        """start() coloca o watcher em estado running."""
        await watcher.start(mock_page, valid_capability_map)

        assert watcher.running is True

    @pytest.mark.asyncio
    async def test_start_exposes_function(
        self, watcher, mock_page, valid_capability_map
    ):
        """start() chama page.expose_function para registrar callback."""
        await watcher.start(mock_page, valid_capability_map)

        mock_page.expose_function.assert_called_once_with(
            "__kiro_mutation_callback",
            watcher._on_mutations_received,
        )

    @pytest.mark.asyncio
    async def test_start_evaluates_observer_script(
        self, watcher, mock_page, valid_capability_map
    ):
        """start() executa script para criar MutationObserver."""
        await watcher.start(mock_page, valid_capability_map)

        mock_page.evaluate.assert_called_once()
        # Verificar que o script contém 'MutationObserver'
        call_args = mock_page.evaluate.call_args[0][0]
        assert "MutationObserver" in call_args

    @pytest.mark.asyncio
    async def test_start_twice_raises_error(
        self, watcher, mock_page, valid_capability_map
    ):
        """Chamar start() duas vezes levanta RuntimeError."""
        await watcher.start(mock_page, valid_capability_map)

        with pytest.raises(RuntimeError, match="já está em execução"):
            await watcher.start(mock_page, valid_capability_map)

    @pytest.mark.asyncio
    async def test_stop_clears_running_state(
        self, watcher, mock_page, valid_capability_map
    ):
        """stop() coloca o watcher em estado parado."""
        await watcher.start(mock_page, valid_capability_map)
        await watcher.stop()

        assert watcher.running is False

    @pytest.mark.asyncio
    async def test_stop_disconnects_observer(
        self, watcher, mock_page, valid_capability_map
    ):
        """stop() executa script para desconectar MutationObserver."""
        await watcher.start(mock_page, valid_capability_map)
        mock_page.evaluate.reset_mock()

        await watcher.stop()

        mock_page.evaluate.assert_called_once()
        call_args = mock_page.evaluate.call_args[0][0]
        assert "disconnect" in call_args

    @pytest.mark.asyncio
    async def test_stop_clears_pending_mutations(
        self, watcher, mock_page, valid_capability_map
    ):
        """stop() limpa mutações pendentes."""
        await watcher.start(mock_page, valid_capability_map)
        watcher._pending_mutations = [{"type": "childList", "addedNodes": 1, "removedNodes": 0}]

        await watcher.stop()

        assert watcher.pending_mutations == []

    @pytest.mark.asyncio
    async def test_stop_when_not_running_is_noop(self, watcher):
        """stop() quando não está rodando não faz nada."""
        await watcher.stop()
        assert watcher.running is False

    @pytest.mark.asyncio
    async def test_stop_handles_page_error_gracefully(
        self, watcher, mock_page, valid_capability_map
    ):
        """stop() trata erros de page.evaluate() sem propagar."""
        await watcher.start(mock_page, valid_capability_map)
        mock_page.evaluate.side_effect = Exception("Page crashed")

        # Não deve levantar exceção
        await watcher.stop()
        assert watcher.running is False


# ============================================================
# Testes de on_structural_change callback
# ============================================================


class TestOnStructuralChange:
    """Testes do registro e disparo de callback."""

    def test_register_callback(self, watcher):
        """on_structural_change() registra o callback."""
        callback = MagicMock()
        watcher.on_structural_change(callback)

        assert watcher._callback is callback

    @pytest.mark.asyncio
    async def test_structural_mutation_triggers_callback(
        self, watcher, mock_page, valid_capability_map
    ):
        """Mutação estrutural após debounce dispara callback registrado."""
        callback = MagicMock()
        watcher.on_structural_change(callback)
        await watcher.start(mock_page, valid_capability_map)

        # Simular mutação estrutural
        mutations = [{"type": "childList", "addedNodes": 1, "removedNodes": 0, "target": "DIV"}]
        await watcher._on_mutations_received(json.dumps(mutations))

        # Aguardar debounce (50ms + margem)
        await asyncio.sleep(0.1)

        callback.assert_called_once()
        # O callback recebe a lista de mutações estruturais
        args = callback.call_args[0][0]
        assert len(args) == 1
        assert args[0]["type"] == "childList"

    @pytest.mark.asyncio
    async def test_cosmetic_mutation_does_not_trigger_callback(
        self, watcher, mock_page, valid_capability_map
    ):
        """Mutação cosmética NÃO dispara callback."""
        callback = MagicMock()
        watcher.on_structural_change(callback)
        await watcher.start(mock_page, valid_capability_map)

        # Simular mutação cosmética
        mutations = [{"type": "attributes", "attributeName": "style", "addedNodes": 0, "removedNodes": 0, "target": "DIV"}]
        await watcher._on_mutations_received(json.dumps(mutations))

        # Aguardar debounce
        await asyncio.sleep(0.1)

        callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_callback_registered_no_error(
        self, watcher, mock_page, valid_capability_map
    ):
        """Se nenhum callback registrado, mutação estrutural não gera erro."""
        await watcher.start(mock_page, valid_capability_map)

        mutations = [{"type": "childList", "addedNodes": 1, "removedNodes": 0, "target": "DIV"}]
        await watcher._on_mutations_received(json.dumps(mutations))

        # Não deve levantar exceção
        await asyncio.sleep(0.1)


# ============================================================
# Testes de debounce/coalescing
# ============================================================


class TestDebounce:
    """Testes de debounce e coalescing de mutações."""

    @pytest.mark.asyncio
    async def test_multiple_mutations_coalesced_into_one_evaluation(
        self, watcher, mock_page, valid_capability_map
    ):
        """Múltiplas mutações dentro da janela de debounce geram uma única avaliação."""
        callback = MagicMock()
        watcher.on_structural_change(callback)
        await watcher.start(mock_page, valid_capability_map)

        # Enviar 3 lotes de mutações rapidamente
        for i in range(3):
            mutations = [{"type": "childList", "addedNodes": 1, "removedNodes": 0, "target": "DIV"}]
            await watcher._on_mutations_received(json.dumps(mutations))
            await asyncio.sleep(0.01)  # Menor que o debounce (50ms)

        # Aguardar debounce
        await asyncio.sleep(0.1)

        # Callback deve ter sido chamado apenas UMA vez
        callback.assert_called_once()
        # Com todas as mutações agrupadas
        args = callback.call_args[0][0]
        assert len(args) == 3

    @pytest.mark.asyncio
    async def test_mutations_after_debounce_trigger_new_evaluation(
        self, watcher, mock_page, valid_capability_map
    ):
        """Mutações após a janela de debounce geram nova avaliação."""
        callback = MagicMock()
        watcher.on_structural_change(callback)
        await watcher.start(mock_page, valid_capability_map)

        # Primeiro lote
        mutations = [{"type": "childList", "addedNodes": 1, "removedNodes": 0, "target": "DIV"}]
        await watcher._on_mutations_received(json.dumps(mutations))

        # Aguardar debounce completo
        await asyncio.sleep(0.1)

        # Segundo lote (após o debounce)
        mutations = [{"type": "childList", "addedNodes": 2, "removedNodes": 0, "target": "SPAN"}]
        await watcher._on_mutations_received(json.dumps(mutations))

        # Aguardar segundo debounce
        await asyncio.sleep(0.1)

        # Callback deve ter sido chamado duas vezes
        assert callback.call_count == 2

    @pytest.mark.asyncio
    async def test_debounce_resets_on_new_mutation(
        self, watcher, mock_page, valid_capability_map
    ):
        """Novas mutações reiniciam o timer de debounce."""
        callback = MagicMock()
        watcher.on_structural_change(callback)

        # Usar debounce maior para controlar timing
        watcher._debounce_window_ms = 100
        await watcher.start(mock_page, valid_capability_map)

        # Enviar mutação
        mutations = [{"type": "childList", "addedNodes": 1, "removedNodes": 0, "target": "DIV"}]
        await watcher._on_mutations_received(json.dumps(mutations))

        # Esperar 70ms (dentro do debounce de 100ms)
        await asyncio.sleep(0.07)
        callback.assert_not_called()

        # Enviar outra mutação — reinicia o timer
        mutations = [{"type": "childList", "addedNodes": 1, "removedNodes": 0, "target": "SPAN"}]
        await watcher._on_mutations_received(json.dumps(mutations))

        # Esperar 70ms novamente (total 140ms, mas timer reiniciou)
        await asyncio.sleep(0.07)
        callback.assert_not_called()

        # Esperar o debounce final expirar
        await asyncio.sleep(0.06)
        callback.assert_called_once()
        # Ambas as mutações agrupadas
        args = callback.call_args[0][0]
        assert len(args) == 2

    @pytest.mark.asyncio
    async def test_configurable_debounce_window(
        self, mock_page, valid_capability_map
    ):
        """Debounce window é configurável via construtor."""
        watcher = MutationObserverWatcher(debounce_window_ms=200)
        callback = MagicMock()
        watcher.on_structural_change(callback)
        await watcher.start(mock_page, valid_capability_map)

        mutations = [{"type": "childList", "addedNodes": 1, "removedNodes": 0, "target": "DIV"}]
        await watcher._on_mutations_received(json.dumps(mutations))

        # Antes do debounce de 200ms
        await asyncio.sleep(0.1)
        callback.assert_not_called()

        # Após o debounce
        await asyncio.sleep(0.15)
        callback.assert_called_once()

        await watcher.stop()


# ============================================================
# Testes de mixed mutations (estruturais + cosméticas)
# ============================================================


class TestMixedMutations:
    """Testes com mix de mutações estruturais e cosméticas."""

    @pytest.mark.asyncio
    async def test_mixed_batch_filters_only_structural(
        self, watcher, mock_page, valid_capability_map
    ):
        """Batch com mix de tipos filtra apenas estruturais para o callback."""
        callback = MagicMock()
        watcher.on_structural_change(callback)
        await watcher.start(mock_page, valid_capability_map)

        mutations = [
            {"type": "attributes", "attributeName": "style", "addedNodes": 0, "removedNodes": 0, "target": "DIV"},
            {"type": "childList", "addedNodes": 1, "removedNodes": 0, "target": "DIV"},
            {"type": "characterData", "addedNodes": 0, "removedNodes": 0, "target": "TEXT"},
            {"type": "attributes", "attributeName": "aria-label", "addedNodes": 0, "removedNodes": 0, "target": "BUTTON"},
        ]
        await watcher._on_mutations_received(json.dumps(mutations))

        await asyncio.sleep(0.1)

        callback.assert_called_once()
        structural = callback.call_args[0][0]
        # Somente childList e aria-label são estruturais
        assert len(structural) == 2
        assert structural[0]["type"] == "childList"
        assert structural[1]["attributeName"] == "aria-label"

    @pytest.mark.asyncio
    async def test_all_cosmetic_batch_no_callback(
        self, watcher, mock_page, valid_capability_map
    ):
        """Batch com apenas mutações cosméticas não dispara callback."""
        callback = MagicMock()
        watcher.on_structural_change(callback)
        await watcher.start(mock_page, valid_capability_map)

        mutations = [
            {"type": "attributes", "attributeName": "style", "addedNodes": 0, "removedNodes": 0, "target": "DIV"},
            {"type": "characterData", "addedNodes": 0, "removedNodes": 0, "target": "TEXT"},
            {"type": "attributes", "attributeName": "class", "addedNodes": 0, "removedNodes": 0, "target": "SPAN"},
        ]
        await watcher._on_mutations_received(json.dumps(mutations))

        await asyncio.sleep(0.1)

        callback.assert_not_called()


# ============================================================
# Testes de error handling
# ============================================================


class TestErrorHandling:
    """Testes de tratamento de erros."""

    @pytest.mark.asyncio
    async def test_invalid_json_handled_gracefully(
        self, watcher, mock_page, valid_capability_map
    ):
        """JSON inválido é tratado sem exceção."""
        await watcher.start(mock_page, valid_capability_map)

        # Não deve levantar exceção
        await watcher._on_mutations_received("invalid json {{{{")
        await asyncio.sleep(0.1)

        assert watcher.pending_mutations == []

    @pytest.mark.asyncio
    async def test_mutations_received_when_not_running_ignored(
        self, watcher, mock_page, valid_capability_map
    ):
        """Mutações recebidas quando não está rodando são ignoradas."""
        await watcher.start(mock_page, valid_capability_map)
        await watcher.stop()

        callback = MagicMock()
        watcher.on_structural_change(callback)

        mutations = [{"type": "childList", "addedNodes": 1, "removedNodes": 0, "target": "DIV"}]
        await watcher._on_mutations_received(json.dumps(mutations))

        await asyncio.sleep(0.1)
        callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_stop_cancels_pending_debounce(
        self, watcher, mock_page, valid_capability_map
    ):
        """stop() cancela debounce task pendente sem disparar callback."""
        callback = MagicMock()
        watcher.on_structural_change(callback)
        await watcher.start(mock_page, valid_capability_map)

        mutations = [{"type": "childList", "addedNodes": 1, "removedNodes": 0, "target": "DIV"}]
        await watcher._on_mutations_received(json.dumps(mutations))

        # Parar antes do debounce
        await asyncio.sleep(0.01)
        await watcher.stop()

        # Aguardar tempo que seria suficiente para o debounce
        await asyncio.sleep(0.1)

        # Callback NÃO deve ter sido chamado
        callback.assert_not_called()
