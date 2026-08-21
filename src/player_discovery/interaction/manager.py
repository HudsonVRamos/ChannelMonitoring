"""InteractionManager — Gerencia interações com o player via três níveis.

Implementa a hierarquia de interação definida no Requirement 12:
- Nível 1 (PLAYER_API): Chamada direta à API do player via page.evaluate()
- Nível 2 (SEMANTIC_DOM): Locator via role, aria-label, text, data-attributes
- Nível 3 (VISUAL_FALLBACK): Interação visual sem coordenadas fixas

CRÍTICO: Rejeita qualquer interação baseada em:
- Coordenadas fixas (x, y)
- Posição absoluta
- Índice posicional (primeiro botão, segundo item)

Requirements: 12.1, 12.2, 12.3, 12.4
"""

from __future__ import annotations

import logging
import re
import time
from typing import Optional

from playwright.async_api import Page

from src.player_discovery.models.capability import (
    Capability,
    InteractionStrategy,
)
from src.player_discovery.models.capability_map import CapabilityMap
from src.player_discovery.models.enums import InteractionLevel
from src.player_discovery.models.results import InteractionResult


logger = logging.getLogger(__name__)

# Padrões proibidos — coordenadas fixas e índices posicionais
_COORDINATE_PATTERNS = [
    re.compile(r"\bx\s*[:=]\s*\d+", re.IGNORECASE),
    re.compile(r"\by\s*[:=]\s*\d+", re.IGNORECASE),
    re.compile(r"\bposition\s*[:=]\s*\d+", re.IGNORECASE),
    re.compile(r"\bcoord", re.IGNORECASE),
]

_POSITIONAL_INDEX_PATTERNS = [
    re.compile(r"\b(first|second|third|nth)\b", re.IGNORECASE),
    re.compile(r"\bindex\s*[:=]\s*\d+", re.IGNORECASE),
    re.compile(r":nth-child", re.IGNORECASE),
    re.compile(r":nth-of-type", re.IGNORECASE),
    re.compile(r":first-child", re.IGNORECASE),
    re.compile(r":last-child", re.IGNORECASE),
]

# Chaves proibidas no dicionário de details
_FORBIDDEN_DETAIL_KEYS = frozenset([
    "x", "y", "top", "left", "right", "bottom",
    "position_x", "position_y",
    "absolute_x", "absolute_y",
    "index", "nth", "ordinal",
])


class InteractionRejectedError(Exception):
    """Exceção levantada ao detectar interação proibida.

    Interações baseadas em coordenadas fixas, posição absoluta
    ou índice posicional são rejeitadas pelo sistema.
    """

    pass


class InteractionManager:
    """Gerencia interações com o player via três níveis.

    Segue a hierarquia definida no Requirement 12:
    API (Nível 1) → DOM semântico (Nível 2) → Visual fallback (Nível 3).

    Toda interação passa por validação de segurança que rejeita
    coordenadas fixas e índices posicionais.
    """

    async def execute(
        self,
        page: Page,
        capability: str,
        action: str,
        capability_map: CapabilityMap,
    ) -> InteractionResult:
        """Executa interação seguindo hierarquia: API → DOM → Visual.

        Obtém as strategies do capability_map e tenta cada uma
        em ordem de preferência (Nível 1 → 2 → 3) até que uma
        seja bem-sucedida.

        Args:
            page: Página Playwright ativa.
            capability: Nome da capability (ex: "play", "mute").
            action: Ação a executar (ex: "click", "toggle").
            capability_map: Mapa de capabilities com strategies.

        Returns:
            InteractionResult com sucesso/falha e nível utilizado.

        Raises:
            InteractionRejectedError: Se uma strategy usar
                coordenadas fixas ou índice posicional.
        """
        cap = capability_map.get_capability(capability)
        if cap is None:
            return InteractionResult(
                success=False,
                level_used=InteractionLevel.VISUAL_FALLBACK,
                duration_ms=0,
                error=f"Capability '{capability}' não encontrada no mapa",
            )

        strategies = self._get_ordered_strategies(cap)
        if not strategies:
            return InteractionResult(
                success=False,
                level_used=InteractionLevel.VISUAL_FALLBACK,
                duration_ms=0,
                error=(
                    f"Nenhuma strategy disponível para "
                    f"capability '{capability}'"
                ),
            )

        last_error: Optional[str] = None
        last_level = InteractionLevel.VISUAL_FALLBACK

        for strategy in strategies:
            # Validar se a strategy não usa padrões proibidos
            self._validate_strategy(strategy)

            last_level = strategy.level

            try:
                result = await self._execute_by_level(
                    page, strategy, action
                )
                if result.success:
                    return result
                last_error = result.error
            except InteractionRejectedError:
                raise
            except Exception as e:
                last_error = str(e)
                logger.warning(
                    "Falha no nível %s para '%s': %s",
                    strategy.level.value,
                    capability,
                    last_error,
                )

        # Todos os níveis falharam
        return InteractionResult(
            success=False,
            level_used=last_level,
            duration_ms=0,
            error=f"Todos os níveis falharam para '{capability}': "
                  f"{last_error}",
        )

    async def _execute_by_level(
        self,
        page: Page,
        strategy: InteractionStrategy,
        action: str,
    ) -> InteractionResult:
        """Despacha execução para o método do nível correto.

        Args:
            page: Página Playwright ativa.
            strategy: Estratégia a executar.
            action: Ação a executar.

        Returns:
            InteractionResult do nível executado.
        """
        if strategy.level == InteractionLevel.PLAYER_API:
            return await self._execute_api(page, strategy)
        elif strategy.level == InteractionLevel.SEMANTIC_DOM:
            return await self._execute_semantic_dom(page, strategy)
        elif strategy.level == InteractionLevel.VISUAL_FALLBACK:
            return await self._execute_visual_fallback(page, strategy)
        else:
            return InteractionResult(
                success=False,
                level_used=strategy.level,
                duration_ms=0,
                error=f"Nível desconhecido: {strategy.level}",
            )

    async def _execute_api(
        self,
        page: Page,
        strategy: InteractionStrategy,
    ) -> InteractionResult:
        """Nível 1: Chamada direta à API do player via page.evaluate().

        Executa JavaScript diretamente no browser para chamar
        métodos do player.

        Args:
            page: Página Playwright ativa.
            strategy: Estratégia com details contendo 'method' ou 'js_code'.

        Returns:
            InteractionResult com sucesso/falha.
        """
        start_time = time.perf_counter()

        js_code = strategy.details.get("js_code") or strategy.details.get(
            "method", ""
        )
        if not js_code:
            return InteractionResult(
                success=False,
                level_used=InteractionLevel.PLAYER_API,
                duration_ms=0,
                error="Strategy API sem 'method' ou 'js_code' definido",
            )

        try:
            # Se js_code não contém parênteses, assumir que é chamada
            if "(" not in js_code and "=" not in js_code:
                js_code = f"{js_code}()"

            await page.evaluate(js_code)
            elapsed_ms = int(
                (time.perf_counter() - start_time) * 1000
            )

            logger.debug(
                "API executada com sucesso: %s (%dms)",
                js_code,
                elapsed_ms,
            )
            return InteractionResult(
                success=True,
                level_used=InteractionLevel.PLAYER_API,
                duration_ms=elapsed_ms,
            )
        except Exception as e:
            elapsed_ms = int(
                (time.perf_counter() - start_time) * 1000
            )
            logger.warning(
                "Falha na API '%s': %s", js_code, str(e)
            )
            return InteractionResult(
                success=False,
                level_used=InteractionLevel.PLAYER_API,
                duration_ms=elapsed_ms,
                error=f"API falhou: {e}",
            )

    async def _execute_semantic_dom(
        self,
        page: Page,
        strategy: InteractionStrategy,
    ) -> InteractionResult:
        """Nível 2: Locator via role, aria-label, text, data-attributes.

        Usa Playwright locators semânticos para encontrar e interagir
        com elementos sem depender de seletores CSS fixos.

        Args:
            page: Página Playwright ativa.
            strategy: Estratégia com details contendo role, aria_label,
                text ou data_attributes.

        Returns:
            InteractionResult com sucesso/falha.
        """
        start_time = time.perf_counter()

        details = strategy.details
        locator = None

        try:
            # Construir locator semântico
            role = details.get("role")
            aria_label = details.get("aria_label")
            text = details.get("text")
            data_testid = details.get("data_testid")

            if role and aria_label:
                locator = page.get_by_role(role, name=aria_label)
            elif role and text:
                locator = page.get_by_role(role, name=text)
            elif role:
                locator = page.get_by_role(role)
            elif aria_label:
                locator = page.get_by_label(aria_label)
            elif text:
                locator = page.get_by_text(text)
            elif data_testid:
                locator = page.get_by_test_id(data_testid)
            else:
                return InteractionResult(
                    success=False,
                    level_used=InteractionLevel.SEMANTIC_DOM,
                    duration_ms=0,
                    error=(
                        "Strategy DOM sem atributos semânticos "
                        "(role, aria_label, text, data_testid)"
                    ),
                )

            # Executar ação no elemento
            action = details.get("action", "click")
            if action == "click":
                await locator.click(timeout=5000)
            elif action == "check":
                await locator.check(timeout=5000)
            elif action == "uncheck":
                await locator.uncheck(timeout=5000)
            else:
                await locator.click(timeout=5000)

            elapsed_ms = int(
                (time.perf_counter() - start_time) * 1000
            )
            logger.debug(
                "DOM semântico executado: role=%s, label=%s (%dms)",
                role,
                aria_label,
                elapsed_ms,
            )
            return InteractionResult(
                success=True,
                level_used=InteractionLevel.SEMANTIC_DOM,
                duration_ms=elapsed_ms,
            )
        except Exception as e:
            elapsed_ms = int(
                (time.perf_counter() - start_time) * 1000
            )
            logger.warning(
                "Falha no DOM semântico: %s", str(e)
            )
            return InteractionResult(
                success=False,
                level_used=InteractionLevel.SEMANTIC_DOM,
                duration_ms=elapsed_ms,
                error=f"DOM semântico falhou: {e}",
            )

    async def _execute_visual_fallback(
        self,
        page: Page,
        strategy: InteractionStrategy,
    ) -> InteractionResult:
        """Nível 3: Interação visual sem coordenadas fixas.

        Usa estratégias visuais como buscar elemento por descrição
        visual (cores, tamanho relativo, posição relativa) sem usar
        coordenadas absolutas fixas.

        Args:
            page: Página Playwright ativa.
            strategy: Estratégia com details descrevendo visualmente
                o elemento alvo.

        Returns:
            InteractionResult com sucesso/falha.
        """
        start_time = time.perf_counter()

        details = strategy.details
        description = details.get("description", "")
        selector = details.get("visual_selector", "")
        js_visual = details.get("js_visual_search", "")

        try:
            if js_visual:
                # Usar JavaScript para busca visual dinâmica
                result = await page.evaluate(js_visual)
                if not result:
                    raise RuntimeError(
                        "Busca visual JS não encontrou elemento"
                    )
            elif selector:
                # Selector semântico como fallback visual
                element = page.locator(selector)
                await element.click(timeout=5000)
            else:
                # Fallback: buscar por texto visível ou atributo
                aria_description = details.get(
                    "aria_description", description
                )
                if aria_description:
                    element = page.get_by_text(
                        aria_description, exact=False
                    )
                    await element.first.click(timeout=5000)
                else:
                    raise RuntimeError(
                        "Visual fallback sem descrição ou selector"
                    )

            elapsed_ms = int(
                (time.perf_counter() - start_time) * 1000
            )
            logger.debug(
                "Visual fallback executado: %s (%dms)",
                description or selector or "js_visual",
                elapsed_ms,
            )
            return InteractionResult(
                success=True,
                level_used=InteractionLevel.VISUAL_FALLBACK,
                duration_ms=elapsed_ms,
            )
        except Exception as e:
            elapsed_ms = int(
                (time.perf_counter() - start_time) * 1000
            )
            logger.warning(
                "Falha no visual fallback: %s", str(e)
            )
            return InteractionResult(
                success=False,
                level_used=InteractionLevel.VISUAL_FALLBACK,
                duration_ms=elapsed_ms,
                error=f"Visual fallback falhou: {e}",
            )

    def _get_ordered_strategies(
        self, cap: Capability
    ) -> list[InteractionStrategy]:
        """Obtém strategies ordenadas por nível (1 → 2 → 3).

        Se a capability tem strategies definidas, retorna ordenadas.
        Caso contrário, cria uma strategy baseada no interaction_strategy.

        Args:
            cap: Capability com strategies.

        Returns:
            Lista de strategies ordenadas por nível.
        """
        if cap.strategies:
            # Ordenar por nível: PLAYER_API=1, SEMANTIC_DOM=2, VISUAL=3
            level_order = {
                InteractionLevel.PLAYER_API: 1,
                InteractionLevel.SEMANTIC_DOM: 2,
                InteractionLevel.VISUAL_FALLBACK: 3,
            }
            return sorted(
                cap.strategies,
                key=lambda s: level_order.get(s.level, 99),
            )

        # Fallback: criar strategy única baseada no campo preferencial
        return [
            InteractionStrategy(
                level=cap.interaction_strategy,
                type=cap.interaction_strategy.value,
                details={},
            )
        ]

    def _validate_strategy(self, strategy: InteractionStrategy) -> None:
        """Valida que a strategy não usa padrões proibidos.

        Rejeita coordenadas fixas, posição absoluta e
        índices posicionais.

        Args:
            strategy: Strategy a validar.

        Raises:
            InteractionRejectedError: Se padrão proibido detectado.
        """
        details = strategy.details

        # Verificar chaves proibidas no dicionário de details
        forbidden_found = _FORBIDDEN_DETAIL_KEYS.intersection(
            details.keys()
        )
        if forbidden_found:
            raise InteractionRejectedError(
                f"Strategy rejeitada: contém chaves proibidas "
                f"{forbidden_found} — coordenadas fixas ou "
                f"índices posicionais não são permitidos"
            )

        # Verificar valores numéricos que parecem coordenadas
        for key, value in details.items():
            if isinstance(value, str):
                self._check_string_for_forbidden_patterns(
                    value, key
                )

    def _check_string_for_forbidden_patterns(
        self, value: str, context: str
    ) -> None:
        """Verifica string por padrões proibidos.

        Args:
            value: String a verificar.
            context: Contexto para mensagem de erro.

        Raises:
            InteractionRejectedError: Se padrão proibido encontrado.
        """
        for pattern in _COORDINATE_PATTERNS:
            if pattern.search(value):
                raise InteractionRejectedError(
                    f"Strategy rejeitada: valor '{value}' em "
                    f"'{context}' contém padrão de coordenada fixa"
                )

        for pattern in _POSITIONAL_INDEX_PATTERNS:
            if pattern.search(value):
                raise InteractionRejectedError(
                    f"Strategy rejeitada: valor '{value}' em "
                    f"'{context}' contém padrão de índice posicional"
                )
