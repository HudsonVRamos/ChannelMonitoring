"""Análise semântica do DOM para descoberta de capabilities do player.

Este módulo analisa o DOM buscando elementos de controle do player
exclusivamente por atributos semânticos (role, aria-label, aria-haspopup,
title, textContent, data-*, tabindex), sem utilizar seletores CSS fixos,
IDs específicos ou classes CSS.

Requirements: 1.2, 1.5, 12.1
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

from src.player_discovery.models.enums import InteractionLevel

if TYPE_CHECKING:
    from playwright.async_api import Page


# Mapeamento de termos semânticos para capabilities do player.
# Cada entrada associa palavras-chave (em múltiplos idiomas) a uma capability.
CAPABILITY_KEYWORDS: dict[str, list[str]] = {
    "play": [
        "play", "reproduzir", "iniciar", "start", "tocar",
    ],
    "pause": [
        "pause", "pausar", "parar", "stop",
    ],
    "mute": [
        "mute", "mutar", "silenciar", "sem som", "sem áudio",
    ],
    "unmute": [
        "unmute", "desmutar", "ativar som", "com som",
    ],
    "audio_selection": [
        "audio", "áudio", "idioma de áudio", "audio track",
        "audio language", "trilha de áudio", "som",
    ],
    "subtitle_selection": [
        "subtitle", "legenda", "caption", "closed caption",
        "cc", "legendas", "subtítulo",
    ],
    "quality_selection": [
        "quality", "qualidade", "resolution", "resolução",
        "hd", "sd", "4k", "1080p", "720p", "bitrate",
    ],
    "fullscreen": [
        "fullscreen", "tela cheia", "full screen", "maximize",
        "maximizar", "expand", "expandir",
    ],
    "settings": [
        "settings", "configurações", "config", "opções",
        "options", "preferências", "preferences", "gear", "engrenagem",
    ],
}

# Roles ARIA que indicam controles interativos do player
INTERACTIVE_ROLES: list[str] = [
    "button",
    "slider",
    "menuitem",
    "menu",
    "menubar",
    "listbox",
    "option",
    "switch",
    "tab",
    "toolbar",
    "checkbox",
    "radio",
]


@dataclass
class DOMEvidence:
    """Evidência encontrada via análise semântica do DOM.

    Cada instância representa um elemento encontrado no DOM que pode
    indicar uma capability do player, identificado exclusivamente por
    atributos semânticos.
    """

    element_description: str
    """Descrição do elemento encontrado (ex: 'button com aria-label=Play')."""

    capability_hint: str
    """Qual capability este elemento pode representar (ex: 'play', 'mute')."""

    confidence_contribution: float
    """Quanto contribui para o confidence (0.0-1.0)."""

    attributes: dict[str, str] = field(default_factory=dict)
    """Atributos semânticos encontrados (role, aria-label, title, etc.)."""

    interaction_hint: InteractionLevel = InteractionLevel.SEMANTIC_DOM
    """Nível de interação sugerido para este elemento."""


class DOMAnalyzer:
    """Analisa o DOM semanticamente sem seletores fixos.

    Busca elementos de controle do player exclusivamente por atributos
    semânticos: role, aria-label, aria-haspopup, title, textContent,
    data-*, tabindex. Nunca utiliza IDs, classes CSS ou seletores fixos.

    Requirements: 1.2, 1.5, 12.1
    """

    def __init__(self) -> None:
        """Inicializa o DOMAnalyzer."""
        self._capability_keywords = CAPABILITY_KEYWORDS
        self._interactive_roles = INTERACTIVE_ROLES

    async def analyze(self, page: "Page") -> list[DOMEvidence]:
        """Executa análise semântica do DOM do player.

        Utiliza page.evaluate() com JavaScript que busca elementos por
        atributos semânticos e retorna dados estruturados.

        Args:
            page: Instância de Page do Playwright.

        Returns:
            Lista de DOMEvidence com todos os elementos relevantes encontrados.
        """
        raw_elements = await self._query_semantic_elements(page)
        evidences = self._map_elements_to_evidence(raw_elements)
        return evidences

    async def _query_semantic_elements(self, page: "Page") -> list[dict]:
        """Executa JavaScript no browser para buscar elementos semânticos.

        O JavaScript busca elementos por:
        - [role] — roles ARIA que indicam controles interativos
        - [aria-label] — labels acessíveis
        - [aria-haspopup] — elementos que abrem menus/popups
        - [title] — títulos descritivos
        - [data-*] — atributos data customizados
        - [tabindex] — elementos focáveis

        Returns:
            Lista de dicionários com informações dos elementos encontrados.
        """
        js_code = """
        () => {
            const results = [];
            const seen = new Set();

            // Seletores baseados exclusivamente em atributos semânticos
            const selectors = [
                '[role]',
                '[aria-label]',
                '[aria-haspopup]',
                '[title]',
                '[tabindex]',
                '[data-testid]',
                '[data-control]',
                '[data-action]',
                '[data-type]',
                '[data-name]',
                '[data-tooltip]',
                '[data-title]',
                '[data-label]',
                '[data-player]',
                '[data-state]',
                '[data-value]',
            ];

            for (const selector of selectors) {
                const elements = document.querySelectorAll(selector);
                for (const el of elements) {
                    // Gerar identificador único baseado em posição no DOM
                    const path = getElementPath(el);
                    if (seen.has(path)) continue;
                    seen.add(path);

                    const info = extractElementInfo(el);
                    if (info) {
                        results.push(info);
                    }
                }
            }

            return results;

            function getElementPath(el) {
                const parts = [];
                let current = el;
                while (current && current !== document.body) {
                    const tag = current.tagName ? current.tagName.toLowerCase() : '';
                    const index = getChildIndex(current);
                    parts.unshift(tag + '[' + index + ']');
                    current = current.parentElement;
                }
                return parts.join('/');
            }

            function getChildIndex(el) {
                if (!el.parentElement) return 0;
                const siblings = Array.from(el.parentElement.children);
                return siblings.indexOf(el);
            }

            function extractElementInfo(el) {
                const tag = el.tagName ? el.tagName.toLowerCase() : '';
                const role = el.getAttribute('role') || '';
                const ariaLabel = el.getAttribute('aria-label') || '';
                const ariaHaspopup = el.getAttribute('aria-haspopup') || '';
                const title = el.getAttribute('title') || '';
                const tabindex = el.getAttribute('tabindex');
                const textContent = (el.textContent || '').trim().substring(0, 100);

                // Coletar atributos data-*
                const dataAttrs = {};
                for (const attr of el.attributes) {
                    if (attr.name.startsWith('data-')) {
                        dataAttrs[attr.name] = attr.value;
                    }
                }

                // Verificar se o elemento é relevante (tem informação semântica)
                const hasSemanticInfo = (
                    role ||
                    ariaLabel ||
                    ariaHaspopup ||
                    title ||
                    Object.keys(dataAttrs).length > 0 ||
                    (tabindex !== null && tabindex !== '-1')
                );

                if (!hasSemanticInfo) return null;

                return {
                    tag: tag,
                    role: role,
                    aria_label: ariaLabel,
                    aria_haspopup: ariaHaspopup,
                    title: title,
                    tabindex: tabindex,
                    text_content: textContent,
                    data_attributes: dataAttrs,
                    is_visible: isVisible(el),
                    is_interactive: isInteractive(el, role, tabindex),
                };
            }

            function isVisible(el) {
                const style = window.getComputedStyle(el);
                return (
                    style.display !== 'none' &&
                    style.visibility !== 'hidden' &&
                    style.opacity !== '0'
                );
            }

            function isInteractive(el, role, tabindex) {
                const interactiveRoles = [
                    'button', 'slider', 'menuitem', 'menu', 'menubar',
                    'listbox', 'option', 'switch', 'tab', 'toolbar',
                    'checkbox', 'radio'
                ];
                const interactiveTags = ['button', 'a', 'input', 'select'];
                const tag = el.tagName ? el.tagName.toLowerCase() : '';

                return (
                    interactiveRoles.includes(role) ||
                    interactiveTags.includes(tag) ||
                    (tabindex !== null && tabindex !== '-1')
                );
            }
        }
        """
        try:
            result = await page.evaluate(js_code)
            return result if isinstance(result, list) else []
        except Exception:
            # Se falhar (ex: página não carregada), retornar lista vazia
            return []

    def _map_elements_to_evidence(
        self, raw_elements: list[dict]
    ) -> list[DOMEvidence]:
        """Mapeia elementos brutos do DOM para DOMEvidence.

        Para cada elemento, verifica se o conteúdo semântico (aria-label,
        title, textContent, data-*) indica uma capability do player.

        Args:
            raw_elements: Lista de dicts retornados pelo JavaScript.

        Returns:
            Lista de DOMEvidence com capability hints.
        """
        evidences: list[DOMEvidence] = []

        for element in raw_elements:
            capability_hint = self._identify_capability(element)
            if capability_hint is None:
                continue

            confidence = self._calculate_confidence(element)
            description = self._build_description(element)
            attributes = self._extract_semantic_attributes(element)
            interaction_hint = self._determine_interaction_level(element)

            evidence = DOMEvidence(
                element_description=description,
                capability_hint=capability_hint,
                confidence_contribution=confidence,
                attributes=attributes,
                interaction_hint=interaction_hint,
            )
            evidences.append(evidence)

        return evidences

    def _identify_capability(self, element: dict) -> Optional[str]:
        """Identifica qual capability o elemento pode representar.

        Busca matches entre os textos semânticos do elemento e as
        palavras-chave de cada capability.

        Args:
            element: Dict com informações do elemento.

        Returns:
            Nome da capability identificada ou None se não encontrada.
        """
        # Coletar todos os textos semânticos para análise
        searchable_texts: list[str] = []

        aria_label = element.get("aria_label", "")
        if aria_label:
            searchable_texts.append(aria_label.lower())

        title = element.get("title", "")
        if title:
            searchable_texts.append(title.lower())

        text_content = element.get("text_content", "")
        if text_content:
            searchable_texts.append(text_content.lower())

        # Incluir valores de data-attributes
        data_attrs = element.get("data_attributes", {})
        for value in data_attrs.values():
            if value:
                searchable_texts.append(value.lower())

        # Incluir chaves de data-attributes relevantes
        for key in data_attrs:
            searchable_texts.append(key.lower())

        if not searchable_texts:
            return None

        # Buscar match com keywords de cada capability
        combined_text = " ".join(searchable_texts)

        for capability, keywords in self._capability_keywords.items():
            for keyword in keywords:
                if keyword.lower() in combined_text:
                    return capability

        return None

    def _calculate_confidence(self, element: dict) -> float:
        """Calcula a contribuição de confidence baseada na qualidade da evidência.

        Fatores que aumentam confidence:
        - aria-label presente e descritivo (+0.3)
        - role interativo (+0.2)
        - title presente (+0.1)
        - Elemento visível (+0.1)
        - Elemento interativo (+0.1)
        - data-attributes relevantes (+0.1)
        - aria-haspopup para menus (+0.1)

        O resultado é limitado a [0.0, 1.0].

        Args:
            element: Dict com informações do elemento.

        Returns:
            Valor de confidence entre 0.0 e 1.0.
        """
        confidence = 0.0

        # aria-label é forte indicador semântico
        if element.get("aria_label"):
            confidence += 0.3

        # role interativo indica controle
        role = element.get("role", "")
        if role in self._interactive_roles:
            confidence += 0.2

        # title é indicador auxiliar
        if element.get("title"):
            confidence += 0.1

        # Visibilidade é importante
        if element.get("is_visible", False):
            confidence += 0.1

        # Interatividade confirma controle
        if element.get("is_interactive", False):
            confidence += 0.1

        # data-attributes indicam estrutura intencional
        data_attrs = element.get("data_attributes", {})
        if data_attrs:
            confidence += 0.1

        # aria-haspopup indica menu/popup
        if element.get("aria_haspopup"):
            confidence += 0.1

        return min(confidence, 1.0)

    def _build_description(self, element: dict) -> str:
        """Constrói uma descrição legível do elemento.

        Args:
            element: Dict com informações do elemento.

        Returns:
            String descritiva do elemento.
        """
        parts: list[str] = []

        tag = element.get("tag", "unknown")
        role = element.get("role", "")

        if role:
            parts.append(f"{tag} com role='{role}'")
        else:
            parts.append(tag)

        aria_label = element.get("aria_label", "")
        if aria_label:
            parts.append(f"aria-label='{aria_label}'")

        title = element.get("title", "")
        if title:
            parts.append(f"title='{title}'")

        aria_haspopup = element.get("aria_haspopup", "")
        if aria_haspopup:
            parts.append(f"aria-haspopup='{aria_haspopup}'")

        return ", ".join(parts)

    def _extract_semantic_attributes(self, element: dict) -> dict[str, str]:
        """Extrai apenas os atributos semânticos do elemento.

        Retorna um dicionário limpo contendo somente atributos
        semânticos (sem IDs, classes ou seletores fixos).

        Args:
            element: Dict com informações do elemento.

        Returns:
            Dict com atributos semânticos.
        """
        attrs: dict[str, str] = {}

        role = element.get("role", "")
        if role:
            attrs["role"] = role

        aria_label = element.get("aria_label", "")
        if aria_label:
            attrs["aria-label"] = aria_label

        aria_haspopup = element.get("aria_haspopup", "")
        if aria_haspopup:
            attrs["aria-haspopup"] = aria_haspopup

        title = element.get("title", "")
        if title:
            attrs["title"] = title

        tabindex = element.get("tabindex")
        if tabindex is not None:
            attrs["tabindex"] = str(tabindex)

        # Incluir data-attributes
        data_attrs = element.get("data_attributes", {})
        for key, value in data_attrs.items():
            attrs[key] = value

        return attrs

    def _determine_interaction_level(self, element: dict) -> InteractionLevel:
        """Determina o nível de interação sugerido para o elemento.

        Elementos encontrados via DOM semântico são classificados como
        SEMANTIC_DOM (Nível 2). Elementos com data-attributes que sugerem
        API interna podem ser promovidos a PLAYER_API (Nível 1).

        Args:
            element: Dict com informações do elemento.

        Returns:
            InteractionLevel sugerido.
        """
        data_attrs = element.get("data_attributes", {})

        # Se tem data-attributes que sugerem API do player
        api_indicators = ["data-player", "data-action", "data-control"]
        for indicator in api_indicators:
            if indicator in data_attrs:
                return InteractionLevel.PLAYER_API

        # Padrão para elementos DOM semânticos
        return InteractionLevel.SEMANTIC_DOM
