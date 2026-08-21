"""Análise de CSS auxiliar para o Player Discovery.

Coleta evidência auxiliar de propriedades CSS (display, visibility, opacity,
pointer-events, estados active/selected) para apoiar o discovery de capabilities.

RESTRIÇÃO CRÍTICA: CSS isolado NUNCA deve produzir confidence >= 0.7.
Este módulo é exclusivamente auxiliar — apenas suporta/confirma evidência
de outros analyzers (DOM, JS, Browser APIs).

Requirements: 1.5
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = logging.getLogger(__name__)

# Constante: máximo de confidence que CSS isolado pode contribuir
MAX_CSS_ONLY_CONFIDENCE = 0.4  # NUNCA >= 0.7


@dataclass
class CSSEvidence:
    """Evidência auxiliar coletada via análise CSS.

    Attributes:
        element_description: Descrição do elemento analisado
        capability_hint: Qual capability este elemento pode representar
        confidence_contribution: Contribuição de confidence (SEMPRE <= MAX_CSS_ONLY_CONFIDENCE)
        properties: Propriedades CSS observadas (display, visibility, etc.)
        is_visible: Se o elemento está visível (display != none, visibility != hidden, opacity > 0)
        is_interactive: Se pointer-events permite interação (pointer-events != none)
        has_active_state: Se possui estado active/selected (aria-pressed, aria-selected, data-active)
    """

    element_description: str
    capability_hint: str
    confidence_contribution: float
    properties: dict = field(default_factory=dict)
    is_visible: bool = False
    is_interactive: bool = False
    has_active_state: bool = False

    def __post_init__(self) -> None:
        """Garante que confidence_contribution nunca excede o máximo permitido."""
        self.confidence_contribution = min(
            self.confidence_contribution, MAX_CSS_ONLY_CONFIDENCE
        )


# Script JS para coletar propriedades CSS e estados de elementos interativos
_CSS_ANALYSIS_SCRIPT = """
() => {
    // Buscar elementos potencialmente interativos próximos ao player de vídeo
    const videoElements = document.querySelectorAll('video');
    const results = [];

    // Função auxiliar para verificar se um elemento é potencial controle do player
    function isPlayerControl(element) {
        const tag = element.tagName.toLowerCase();
        const role = element.getAttribute('role');
        const tabindex = element.getAttribute('tabindex');
        const ariaLabel = element.getAttribute('aria-label') || '';
        const title = element.getAttribute('title') || '';

        // Elementos com role interativo
        const interactiveRoles = ['button', 'slider', 'menuitem', 'tab', 'switch', 'checkbox'];
        if (role && interactiveRoles.includes(role)) return true;

        // Tags nativamente interativas
        if (['button', 'input', 'select'].includes(tag)) return true;

        // Elementos com tabindex (focáveis)
        if (tabindex !== null && tabindex !== '-1') return true;

        // Elementos com aria-label ou title sugestivo de controle de mídia
        const mediaKeywords = [
            'play', 'pause', 'mute', 'unmute', 'volume', 'audio',
            'subtitle', 'legenda', 'quality', 'qualidade', 'fullscreen',
            'settings', 'configurações', 'closed caption', 'cc'
        ];
        const textToCheck = (ariaLabel + ' ' + title).toLowerCase();
        if (mediaKeywords.some(kw => textToCheck.includes(kw))) return true;

        return false;
    }

    // Função para obter computed styles relevantes
    function getRelevantStyles(element) {
        const computed = window.getComputedStyle(element);
        return {
            display: computed.display,
            visibility: computed.visibility,
            opacity: parseFloat(computed.opacity),
            pointerEvents: computed.pointerEvents,
            cursor: computed.cursor,
            position: computed.position,
            zIndex: computed.zIndex
        };
    }

    // Função para verificar estados active/selected
    function getActiveStates(element) {
        return {
            ariaPressed: element.getAttribute('aria-pressed'),
            ariaSelected: element.getAttribute('aria-selected'),
            ariaExpanded: element.getAttribute('aria-expanded'),
            ariaChecked: element.getAttribute('aria-checked'),
            dataActive: element.hasAttribute('data-active') ||
                        element.getAttribute('data-state') === 'active' ||
                        element.getAttribute('data-selected') === 'true',
            classList: Array.from(element.classList)
                .filter(c => c.includes('active') || c.includes('selected') || c.includes('pressed'))
        };
    }

    // Função para construir descrição do elemento sem depender de IDs ou classes
    function describeElement(element) {
        const tag = element.tagName.toLowerCase();
        const role = element.getAttribute('role') || '';
        const ariaLabel = element.getAttribute('aria-label') || '';
        const title = element.getAttribute('title') || '';
        const text = (element.textContent || '').trim().substring(0, 50);

        let description = tag;
        if (role) description += `[role="${role}"]`;
        if (ariaLabel) description += `[aria-label="${ariaLabel}"]`;
        else if (title) description += `[title="${title}"]`;
        else if (text) description += `[text="${text}"]`;

        return description;
    }

    // Função para inferir capability hint baseado em contexto
    function inferCapabilityHint(element) {
        const ariaLabel = (element.getAttribute('aria-label') || '').toLowerCase();
        const title = (element.getAttribute('title') || '').toLowerCase();
        const text = (element.textContent || '').toLowerCase().trim();
        const combined = ariaLabel + ' ' + title + ' ' + text;

        const hints = [
            { keywords: ['play'], hint: 'play' },
            { keywords: ['pause'], hint: 'pause' },
            { keywords: ['mute', 'unmute', 'volume'], hint: 'mute' },
            { keywords: ['audio', 'áudio', 'idioma', 'language'], hint: 'audio_selection' },
            { keywords: ['subtitle', 'legenda', 'closed caption', 'cc'], hint: 'subtitle_selection' },
            { keywords: ['quality', 'qualidade', 'hd', 'resolução'], hint: 'quality_selection' },
            { keywords: ['fullscreen', 'tela cheia'], hint: 'fullscreen' },
            { keywords: ['settings', 'config', 'configurações', 'gear'], hint: 'settings' }
        ];

        for (const { keywords, hint } of hints) {
            if (keywords.some(kw => combined.includes(kw))) {
                return hint;
            }
        }
        return 'unknown';
    }

    // Buscar controles dentro de containers de player ou próximos a vídeos
    const playerContainers = document.querySelectorAll(
        '[class*="player"], [class*="video"], [id*="player"], [id*="video"], ' +
        '[data-player], [data-video-player]'
    );

    // Coletar todos os elementos candidatos (perto de vídeo ou em containers de player)
    const candidates = new Set();

    // De containers de player
    playerContainers.forEach(container => {
        const controls = container.querySelectorAll('button, [role="button"], [role="slider"], ' +
            '[role="menuitem"], [tabindex]:not([tabindex="-1"]), input[type="range"]');
        controls.forEach(el => candidates.add(el));
    });

    // De ancestrais de vídeos
    videoElements.forEach(video => {
        let ancestor = video.parentElement;
        for (let i = 0; i < 5 && ancestor; i++) {
            const controls = ancestor.querySelectorAll('button, [role="button"], [role="slider"], ' +
                '[role="menuitem"], [tabindex]:not([tabindex="-1"]), input[type="range"]');
            controls.forEach(el => candidates.add(el));
            ancestor = ancestor.parentElement;
        }
    });

    // Analisar cada candidato
    candidates.forEach(element => {
        if (!isPlayerControl(element)) return;

        const styles = getRelevantStyles(element);
        const states = getActiveStates(element);

        const isVisible = styles.display !== 'none' &&
                         styles.visibility !== 'hidden' &&
                         styles.opacity > 0;
        const isInteractive = styles.pointerEvents !== 'none';
        const hasActiveState = states.ariaPressed === 'true' ||
                              states.ariaSelected === 'true' ||
                              states.dataActive ||
                              states.classList.length > 0;

        results.push({
            description: describeElement(element),
            capabilityHint: inferCapabilityHint(element),
            properties: styles,
            states: states,
            isVisible: isVisible,
            isInteractive: isInteractive,
            hasActiveState: hasActiveState
        });
    });

    return results;
}
"""


class CSSAnalyzer:
    """Coleta evidência auxiliar de CSS para o discovery.

    Este analyzer inspeciona propriedades CSS computadas de controles
    potenciais do player para fornecer evidência de suporte. CSS isolado
    nunca gera alta confidence — é sempre evidência auxiliar.

    A análise inclui:
    - Propriedades de visibilidade (display, visibility, opacity)
    - Propriedades de interatividade (pointer-events, cursor)
    - Estados ativos (aria-pressed, aria-selected, data-active, classes CSS)
    """

    async def analyze(self, page: Page) -> list[CSSEvidence]:
        """Analisa propriedades CSS de controles potenciais do player.

        Usa page.evaluate() para executar JavaScript no contexto do browser,
        coletando computed styles e estados de elementos interativos.

        Args:
            page: Instância de Page do Playwright

        Returns:
            Lista de CSSEvidence com evidências auxiliares coletadas.
            Cada evidência terá confidence_contribution <= MAX_CSS_ONLY_CONFIDENCE.
        """
        try:
            raw_results = await page.evaluate(_CSS_ANALYSIS_SCRIPT)
        except Exception as e:
            logger.warning(
                "Falha ao executar análise CSS: %s", str(e)
            )
            return []

        evidences: list[CSSEvidence] = []

        for result in raw_results:
            confidence = self._calculate_confidence(result)
            evidence = CSSEvidence(
                element_description=result.get("description", "unknown"),
                capability_hint=result.get("capabilityHint", "unknown"),
                confidence_contribution=confidence,
                properties=result.get("properties", {}),
                is_visible=result.get("isVisible", False),
                is_interactive=result.get("isInteractive", False),
                has_active_state=result.get("hasActiveState", False),
            )
            evidences.append(evidence)

        logger.info(
            "CSS analysis concluída: %d evidências coletadas",
            len(evidences),
        )
        return evidences

    def _calculate_confidence(self, result: dict) -> float:
        """Calcula a contribuição de confidence baseada em propriedades CSS.

        A confidence é calculada com base em:
        - Visibilidade do elemento (display, visibility, opacity)
        - Interatividade (pointer-events)
        - Estado ativo (aria-pressed, aria-selected, data-active)
        - Hint de capability identificado

        RESTRIÇÃO: O resultado SEMPRE será <= MAX_CSS_ONLY_CONFIDENCE (0.4).

        Args:
            result: Dicionário com dados crus do elemento analisado

        Returns:
            Float entre 0.0 e MAX_CSS_ONLY_CONFIDENCE (0.4)
        """
        score = 0.0

        is_visible = result.get("isVisible", False)
        is_interactive = result.get("isInteractive", False)
        has_active_state = result.get("hasActiveState", False)
        capability_hint = result.get("capabilityHint", "unknown")

        # Elemento visível contribui com base
        if is_visible:
            score += 0.15

        # Elemento interativo (pointer-events permite clique)
        if is_interactive:
            score += 0.10

        # Elemento possui estado ativo/selected
        if has_active_state:
            score += 0.10

        # Capability hint reconhecido (não "unknown")
        if capability_hint != "unknown":
            score += 0.05

        # Garantir que NUNCA excede o máximo
        return min(score, MAX_CSS_ONLY_CONFIDENCE)
