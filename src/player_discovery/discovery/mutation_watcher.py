"""MutationObserver Watcher — Observação de mudanças no DOM.

Monitora mudanças no DOM usando MutationObserver via Playwright
page.evaluate() e page.expose_function(). Agrupa mutações com
debounce/coalescing e classifica mudanças como estruturais
(invalidam Capability Map) ou cosméticas (mantêm mapa).

Requirements testados: 4.1, 4.2, 4.3, 4.4
"""

from __future__ import annotations

import asyncio
import logging
from typing import Callable, Optional

from playwright.async_api import Page

from src.player_discovery.models.capability_map import CapabilityMap

logger = logging.getLogger(__name__)

# Atributos semânticos/estruturais — mudanças invalidam o mapa
STRUCTURAL_ATTRIBUTES = frozenset([
    "role",
    "aria-label",
    "aria-haspopup",
    "aria-controls",
    "aria-expanded",
    "aria-pressed",
    "aria-hidden",
    "tabindex",
    "title",
])

# Prefixos de atributos que indicam mudança estrutural
STRUCTURAL_ATTRIBUTE_PREFIXES = ("data-", "aria-")

# Atributos cosméticos — mudanças neles NÃO invalidam o mapa
COSMETIC_ATTRIBUTES = frozenset([
    "class",
    "style",
    "id",
])


def classify_mutation(mutation: dict) -> str:
    """Classifica uma mutação como 'structural' ou 'cosmetic'.

    Regras de classificação:
    - STRUCTURAL: criação/remoção de nós, mudanças em atributos semânticos
      (role, aria-*, data-*, tabindex, title)
    - COSMETIC: mudanças de texto, style, class, atributos não-estruturais

    Args:
        mutation: Dicionário com informações da mutação.
            Campos esperados: type, attributeName, addedNodes, removedNodes

    Returns:
        'structural' ou 'cosmetic'
    """
    mutation_type = mutation.get("type", "")

    # Criação ou remoção de nós é sempre estrutural
    if mutation_type == "childList":
        added = mutation.get("addedNodes", 0)
        removed = mutation.get("removedNodes", 0)
        if added > 0 or removed > 0:
            return "structural"
        return "cosmetic"

    # Mudanças de texto são cosméticas
    if mutation_type == "characterData":
        return "cosmetic"

    # Mudanças de atributos — depende do atributo
    if mutation_type == "attributes":
        attr_name = mutation.get("attributeName", "")

        # Atributos cosméticos conhecidos
        if attr_name in COSMETIC_ATTRIBUTES:
            return "cosmetic"

        # Atributos estruturais explícitos
        if attr_name in STRUCTURAL_ATTRIBUTES:
            return "structural"

        # Prefixos estruturais (data-*, aria-*)
        for prefix in STRUCTURAL_ATTRIBUTE_PREFIXES:
            if attr_name.startswith(prefix):
                return "structural"

        # Atributo desconhecido — tratar como cosmético
        return "cosmetic"

    # Tipo desconhecido — cosmético por padrão
    return "cosmetic"


class MutationObserverWatcher:
    """Observa mudanças no DOM do player com debounce/coalescing.

    Usa page.expose_function() para receber notificações de mutação
    do browser e asyncio tasks para lógica de debounce.

    Classifica mudanças como estruturais (invalidam Capability Map) ou
    cosméticas (mantêm mapa) e notifica via callback registrado.

    Attributes:
        _debounce_window_ms: Janela de debounce em milissegundos.
        _callback: Callback registrado para mudanças estruturais.
        _running: Se a observação está ativa.
        _page: Referência à Page do Playwright.
        _capability_map: Referência ao CapabilityMap sendo monitorado.
        _debounce_task: Task asyncio para debounce.
        _pending_mutations: Mutações acumuladas durante janela de debounce.
    """

    def __init__(self, debounce_window_ms: int = 500) -> None:
        """Inicializa o MutationObserverWatcher.

        Args:
            debounce_window_ms: Janela de debounce para agrupar mutações.
                Padrão: 500ms.
        """
        self._debounce_window_ms = debounce_window_ms
        self._callback: Optional[Callable] = None
        self._running = False
        self._page: Optional[Page] = None
        self._capability_map: Optional[CapabilityMap] = None
        self._debounce_task: Optional[asyncio.Task] = None
        self._pending_mutations: list[dict] = []
        self._function_exposed = False

    @property
    def running(self) -> bool:
        """Se a observação está ativa."""
        return self._running

    @property
    def pending_mutations(self) -> list[dict]:
        """Mutações pendentes acumuladas durante debounce."""
        return self._pending_mutations

    async def start(self, page: Page, capability_map: CapabilityMap) -> None:
        """Inicia observação do DOM com MutationObserver via Playwright.

        Registra uma função exposta no browser que recebe as mutações
        e configura um MutationObserver no contexto da página.

        Args:
            page: Page do Playwright para observação.
            capability_map: CapabilityMap atual para referência.

        Raises:
            RuntimeError: Se o watcher já estiver em execução.
        """
        if self._running:
            raise RuntimeError("MutationObserverWatcher já está em execução")

        self._page = page
        self._capability_map = capability_map
        self._running = True
        self._pending_mutations = []

        # Expor função no browser para receber mutações
        if not self._function_exposed:
            await page.expose_function(
                "__kiro_mutation_callback",
                self._on_mutations_received,
            )
            self._function_exposed = True

        # Iniciar MutationObserver no browser
        await page.evaluate("""() => {
            if (window.__kiro_mutation_observer) {
                window.__kiro_mutation_observer.disconnect();
            }

            const observer = new MutationObserver((mutations) => {
                const serialized = mutations.map(m => ({
                    type: m.type,
                    attributeName: m.attributeName || null,
                    addedNodes: m.addedNodes.length,
                    removedNodes: m.removedNodes.length,
                    target: m.target.tagName || 'unknown'
                }));
                window.__kiro_mutation_callback(JSON.stringify(serialized));
            });

            const target = document.querySelector('video')?.parentElement
                || document.body;

            observer.observe(target, {
                childList: true,
                attributes: true,
                characterData: true,
                subtree: true,
                attributeOldValue: true
            });

            window.__kiro_mutation_observer = observer;
        }""")

        logger.info(
            "MutationObserverWatcher iniciado (debounce=%dms)",
            self._debounce_window_ms,
        )

    async def stop(self) -> None:
        """Para a observação do DOM.

        Desconecta o MutationObserver no browser e cancela tasks pendentes.
        """
        if not self._running:
            return

        self._running = False

        # Cancelar debounce task pendente
        if self._debounce_task and not self._debounce_task.done():
            self._debounce_task.cancel()
            try:
                await self._debounce_task
            except asyncio.CancelledError:
                pass
            self._debounce_task = None

        # Desconectar observer no browser
        if self._page:
            try:
                await self._page.evaluate("""() => {
                    if (window.__kiro_mutation_observer) {
                        window.__kiro_mutation_observer.disconnect();
                        window.__kiro_mutation_observer = null;
                    }
                }""")
            except Exception as e:
                logger.warning(
                    "Erro ao desconectar MutationObserver: %s", e
                )

        self._pending_mutations = []
        logger.info("MutationObserverWatcher parado")

    def on_structural_change(self, callback: Callable) -> None:
        """Registra callback para quando mudanças estruturais são detectadas.

        O callback será chamado com uma lista de mutações estruturais
        agrupadas após o debounce.

        Args:
            callback: Função a ser chamada com as mutações estruturais.
                Assinatura: callback(mutations: list[dict]) -> None
        """
        self._callback = callback

    async def _on_mutations_received(self, mutations_json: str) -> None:
        """Handler chamado pelo browser quando mutações são detectadas.

        Recebe mutações serializadas em JSON, acumula na lista pendente
        e reinicia o timer de debounce.

        Args:
            mutations_json: JSON string com lista de mutações.
        """
        if not self._running:
            return

        import json
        try:
            mutations = json.loads(mutations_json)
        except (json.JSONDecodeError, TypeError):
            logger.warning("Mutações recebidas com formato inválido")
            return

        self._pending_mutations.extend(mutations)

        # Reiniciar debounce timer
        if self._debounce_task and not self._debounce_task.done():
            self._debounce_task.cancel()
            try:
                await self._debounce_task
            except asyncio.CancelledError:
                pass

        self._debounce_task = asyncio.create_task(self._debounce_evaluate())

    async def _debounce_evaluate(self) -> None:
        """Aguarda a janela de debounce e avalia mutações acumuladas.

        Após o debounce, classifica as mutações pendentes e decide
        se há mudança estrutural. Se sim, dispara o callback registrado.
        """
        try:
            await asyncio.sleep(self._debounce_window_ms / 1000.0)
        except asyncio.CancelledError:
            return

        if not self._running:
            return

        # Coletar e limpar mutações pendentes
        mutations = self._pending_mutations.copy()
        self._pending_mutations = []

        if not mutations:
            return

        # Classificar mutações
        structural_mutations = []
        cosmetic_count = 0

        for mutation in mutations:
            classification = classify_mutation(mutation)
            if classification == "structural":
                structural_mutations.append(mutation)
            else:
                cosmetic_count += 1

        if structural_mutations:
            logger.info(
                "Mudanças estruturais: %d estruturais, %d cosméticas",
                len(structural_mutations),
                cosmetic_count,
            )
            # Notificar callback
            if self._callback:
                self._callback(structural_mutations)
        else:
            logger.debug(
                "Apenas mudanças cosméticas: %d mutações ignoradas",
                cosmetic_count,
            )
