"""Gerenciador do Settings Dialog do player SKY+.

Gerencia abertura, fechamento e verificação de visibilidade do
Settings Dialog. Utiliza o CapabilityMap para localizar o
Settings_Icon via estratégias semânticas ou visuais.

Inclui descoberta de opções de áudio e legendas, seleção de opções
e gerenciamento de estado do dialog durante interações.

Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.2, 4.1, 4.2,
              6.1, 6.2, 6.3, 6.4, 6.5, 8.1, 8.2, 8.3, 8.4
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from .config import AudioSubtitleConfig
from .models import TrackOption

if TYPE_CHECKING:
    from playwright.async_api import Locator, Page

    from src.player_discovery.models.capability_map import CapabilityMap

logger = logging.getLogger(__name__)

# Seletores conhecidos para o dialog de configurações
DIALOG_SELECTORS = [
    ".settings-panel",
    '[role="dialog"]',
    '[aria-label*="settings"]',
    '[aria-label*="configurações"]',
]

# Seletores conhecidos para o container do player
PLAYER_CONTAINER_SELECTORS = [
    "video",
    ".shaka-video-container",
    ".player-container",
]

# Seletores fallback para o ícone de configurações
SETTINGS_ICON_FALLBACK_SELECTORS = [
    ".settings-button",
    '[data-testid="settings"]',
    '[aria-label*="settings"]',
    '[aria-label*="configurações"]',
    '[aria-label*="opções"]',
]

# Labels semânticos para busca do ícone via aria-label
SETTINGS_ARIA_LABELS = [
    "settings",
    "configurações",
    "opções",
    "config",
]

# Títulos das seções dentro do Settings Dialog (Req 1.3, 2.1, 4.1)
AUDIO_SECTION_TITLE = "IDIOMA ALTERNATIVO"
SUBTITLE_SECTION_TITLE = "LEGENDAS"

# Seletores para itens de opção dentro de uma seção
OPTION_ITEM_SELECTORS = [
    "li",
    '[role="option"]',
    '[role="menuitemradio"]',
    '[role="menuitem"]',
    "button",
    "div[class*='option']",
    "div[class*='item']",
]

# Classes/atributos que indicam seleção ativa
SELECTED_INDICATORS = [
    "active",
    "selected",
    "checked",
    "current",
    "aria-selected",
    "aria-checked",
]


class SettingsDialogManager:
    """Gerencia interações com o Settings Dialog do player SKY+.

    Responsável por:
    - Abrir o dialog (hover + clique no Settings_Icon)
    - Fechar o dialog (Escape ou clique fora)
    - Verificar visibilidade e reabrir se necessário
    - Localizar o Settings_Icon via estratégia do CapabilityMap
    - Retry com política de 1 tentativa antes de FAIL

    Attributes:
        _page: Instância do Playwright Page para interação com o browser
        _capability_map: Mapa de capabilities do player
        _config: Configuração com timeouts e parâmetros
        _dialog_visible: Estado interno de visibilidade do dialog
    """

    def __init__(
        self,
        page: Page,
        capability_map: CapabilityMap,
        config: AudioSubtitleConfig,
    ) -> None:
        """Inicializa o SettingsDialogManager.

        Args:
            page: Instância do Playwright Page
            capability_map: CapabilityMap com estratégias de interação
            config: Configuração com timeouts e parâmetros
        """
        self._page = page
        self._capability_map = capability_map
        self._config = config
        self._dialog_visible = False

    async def open_dialog(self) -> bool:
        """Abre o Settings Dialog (hover + clique no Settings_Icon).

        Fluxo:
        1. Hover no player para exibir barra de controles
        2. Localizar Settings_Icon via CapabilityMap
        3. Clicar no ícone
        4. Aguardar dialog visível (timeout configurável)
        5. Em caso de timeout: retry 1x (fechar + esperar + reabrir)

        Returns:
            True se o dialog foi aberto com sucesso, False caso contrário.
        """
        logger.info("Abrindo Settings Dialog...")

        # Primeira tentativa
        success = await self._try_open_dialog()
        if success:
            return True

        # Retry: fechar, aguardar e tentar novamente (Req 6.4)
        logger.warning(
            "Settings Dialog não abriu na primeira tentativa. "
            "Executando retry..."
        )
        await self.close_dialog()
        await asyncio.sleep(self._config.dialog_retry_wait_s)

        success = await self._try_open_dialog()
        if success:
            logger.info("Settings Dialog aberto após retry.")
            return True

        logger.error(
            "Settings Dialog não abriu após retry. "
            "Classificando como FAIL."
        )
        return False

    async def _try_open_dialog(self) -> bool:
        """Tentativa única de abrir o dialog.

        Returns:
            True se o dialog ficou visível, False caso contrário.
        """
        # Exibir barra de controles via hover (Req 1.5)
        await self._show_player_controls()

        # Localizar o Settings_Icon (Req 1.1, 8.1, 8.2, 8.3, 8.4)
        icon = await self._find_settings_icon()
        if icon is None:
            logger.warning("Settings_Icon não encontrado.")
            return False

        # Clicar no ícone (Req 1.2)
        try:
            await icon.click()
            logger.debug("Clique no Settings_Icon executado.")
        except Exception as e:
            logger.error(f"Erro ao clicar no Settings_Icon: {e}")
            return False

        # Aguardar dialog visível (timeout de 5s — Req 1.2)
        visible = await self._wait_for_dialog_visible()
        if visible:
            self._dialog_visible = True
            logger.info("Settings Dialog aberto com sucesso.")
        return visible

    async def close_dialog(self) -> bool:
        """Fecha o Settings Dialog (pressionar Escape).

        Utiliza Escape como método primário de fechamento.
        Atualiza o estado interno de visibilidade.

        Returns:
            True (best effort — Escape é sempre enviado).
        """
        logger.debug("Fechando Settings Dialog via Escape.")
        try:
            await self._page.keyboard.press("Escape")
        except Exception as e:
            logger.warning(f"Erro ao pressionar Escape: {e}")
        self._dialog_visible = False
        return True

    async def ensure_dialog_open(self) -> bool:
        """Garante que o dialog está aberto; reabre se necessário.

        Verifica visibilidade atual do dialog. Se não estiver
        visível, chama open_dialog() para reabrir.

        Returns:
            True se o dialog está (ou foi) aberto, False se falhou.
        """
        # Verificar visibilidade atual via locator
        if await self._is_dialog_visible():
            self._dialog_visible = True
            return True

        # Dialog não visível — reabrir (Req 6.1)
        logger.info(
            "Dialog não está visível. Reabrindo..."
        )
        self._dialog_visible = False
        return await self.open_dialog()

    async def _show_player_controls(self) -> None:
        """Move cursor sobre o player para exibir barra de controles.

        Tenta diferentes seletores de container do player.
        Aguarda 300ms após hover para animação de exibição.

        Req 1.5: Mover cursor sobre o player para acionar exibição
        dos controles antes de buscar o Settings_Icon.
        """
        for selector in PLAYER_CONTAINER_SELECTORS:
            try:
                await self._page.hover(selector)
                logger.debug(
                    f"Hover executado no container: {selector}"
                )
                # Aguardar animação de exibição dos controles
                await asyncio.sleep(0.3)
                return
            except Exception:
                continue

        logger.warning(
            "Nenhum container de player encontrado para hover. "
            "Tentando continuar sem exibir controles."
        )

    async def _find_settings_icon(self) -> Locator | None:
        """Localiza o Settings_Icon usando estratégia do CapabilityMap.

        Estratégias por ordem de preferência:
        1. semantic_dom: Playwright locators semânticos (role, aria-label)
        2. visual_fallback: Seletores CSS conhecidos
        3. Heurística: Busca por botões com aria-labels relacionados

        Req 8.1, 8.2, 8.3, 8.4: Utilizar interaction_strategy do
        CapabilityMap para localizar o Settings_Icon.

        Returns:
            Locator do Settings_Icon ou None se não encontrado.
        """
        strategy = self._get_settings_strategy()
        logger.debug(f"Estratégia para settings: {strategy}")

        if strategy == "semantic_dom":
            locator = await self._find_icon_semantic()
            if locator:
                return locator

        if strategy == "visual_fallback":
            locator = await self._find_icon_visual_fallback()
            if locator:
                return locator

        # Heurística como último recurso (Req 8.4)
        locator = await self._find_icon_heuristic()
        if locator:
            return locator

        # Se nenhuma estratégia funcionou, tentar todas
        if strategy == "semantic_dom":
            locator = await self._find_icon_visual_fallback()
            if locator:
                return locator
        elif strategy == "visual_fallback":
            locator = await self._find_icon_semantic()
            if locator:
                return locator

        return None

    async def _find_icon_semantic(self) -> Locator | None:
        """Localiza o ícone via locators semânticos do Playwright.

        Busca por botões com aria-label contendo termos
        relacionados a configurações.

        Req 8.2: Localizar via role, aria-label, text content.

        Returns:
            Locator do ícone ou None se não encontrado.
        """
        for label in SETTINGS_ARIA_LABELS:
            try:
                locator = self._page.get_by_role(
                    "button", name=label
                )
                count = await locator.count()
                if count > 0:
                    logger.debug(
                        f"Settings_Icon encontrado via "
                        f"semantic_dom (label='{label}')."
                    )
                    return locator.first
            except Exception:
                continue

        return None

    async def _find_icon_visual_fallback(self) -> Locator | None:
        """Localiza o ícone via seletores CSS de fallback visual.

        Tenta seletores conhecidos para botões de configurações.

        Req 8.3: Localizar via atributos visuais e contextuais.

        Returns:
            Locator do ícone ou None se não encontrado.
        """
        for selector in SETTINGS_ICON_FALLBACK_SELECTORS:
            try:
                locator = self._page.locator(selector)
                count = await locator.count()
                if count > 0:
                    logger.debug(
                        f"Settings_Icon encontrado via "
                        f"visual_fallback (selector='{selector}')."
                    )
                    return locator.first
            except Exception:
                continue

        return None

    async def _find_icon_heuristic(self) -> Locator | None:
        """Busca heurística por botões com aria-label de settings.

        Última tentativa antes de classificar como indisponível.

        Req 8.4: Tentar descoberta dinâmica usando heurísticas
        semânticas (busca por botões com aria-label contendo
        "settings", "configurações", "opções").

        Returns:
            Locator do ícone ou None se não encontrado.
        """
        for label in SETTINGS_ARIA_LABELS:
            try:
                selector = f'button[aria-label*="{label}"]'
                locator = self._page.locator(selector)
                count = await locator.count()
                if count > 0:
                    logger.debug(
                        f"Settings_Icon encontrado via "
                        f"heurística (selector='{selector}')."
                    )
                    return locator.first
            except Exception:
                continue

        return None

    async def _wait_for_dialog_visible(self) -> bool:
        """Aguarda o dialog ficar visível após clique no ícone.

        Tenta múltiplos seletores conhecidos para o dialog.
        Timeout configurável via config.settings_dialog_timeout_s.

        Returns:
            True se o dialog ficou visível, False se timeout.
        """
        timeout_ms = int(self._config.settings_dialog_timeout_s * 1000)

        for selector in DIALOG_SELECTORS:
            try:
                await self._page.wait_for_selector(
                    selector,
                    state="visible",
                    timeout=timeout_ms,
                )
                logger.debug(
                    f"Dialog visível via selector: {selector}"
                )
                return True
            except Exception:
                continue

        return False

    async def _is_dialog_visible(self) -> bool:
        """Verifica se o dialog está atualmente visível.

        Testa múltiplos seletores conhecidos para o dialog.

        Returns:
            True se algum seletor do dialog está visível.
        """
        for selector in DIALOG_SELECTORS:
            try:
                locator = self._page.locator(selector)
                if await locator.is_visible():
                    return True
            except Exception:
                continue

        return False

    def _get_settings_strategy(self) -> str:
        """Obtém a estratégia de interação para o settings do CapabilityMap.

        Consulta o CapabilityMap para a capability "settings" e
        retorna o nível de interação como string.

        Returns:
            String do nível: "semantic_dom", "visual_fallback",
            "player_api", ou "semantic_dom" como default.
        """
        strategy = self._capability_map.get_interaction_strategy(
            "settings"
        )

        if strategy is None:
            # Capability não encontrada — usar heurística (Req 8.4)
            logger.debug(
                "Capability 'settings' não encontrada no "
                "CapabilityMap. Usando heurística."
            )
            return "semantic_dom"

        # InteractionStrategy pode ser um objeto com .level ou string
        if hasattr(strategy, "level"):
            level = strategy.level
            # level pode ser um enum com .value ou string direta
            if hasattr(level, "value"):
                return level.value
            return str(level)

        # Se for string direta (ex: mock em testes)
        return str(strategy)

    # ------------------------------------------------------------------
    # Descoberta de opções de áudio e legendas (Req 1.3, 2.1, 2.2, 4.1, 4.2)
    # ------------------------------------------------------------------

    async def discover_audio_options(self) -> list[TrackOption]:
        """Coleta opções da Audio_Section ('IDIOMA ALTERNATIVO').

        Abre o Settings Dialog se necessário, localiza a seção de
        áudio pelo título "IDIOMA ALTERNATIVO" e coleta todas as
        opções disponíveis, identificando qual está selecionada.

        Returns:
            Lista de TrackOption com texto, estado de seleção e índice.
            Lista vazia se a seção não for encontrada.

        Req 2.1: Coletar todos os itens da Audio_Section.
        Req 2.2: Identificar opção atualmente selecionada.
        """
        logger.info("Descobrindo opções de áudio...")
        return await self._discover_section_options(
            AUDIO_SECTION_TITLE
        )

    async def discover_subtitle_options(self) -> list[TrackOption]:
        """Coleta opções da Subtitle_Section ('LEGENDAS').

        Abre o Settings Dialog se necessário, localiza a seção de
        legendas pelo título "LEGENDAS" e coleta todas as opções
        disponíveis (incluindo "Desativadas"), identificando qual
        está selecionada.

        Returns:
            Lista de TrackOption com texto, estado de seleção e índice.
            Lista vazia se a seção não for encontrada.

        Req 4.1: Coletar todos os itens da Subtitle_Section.
        Req 4.2: Identificar opção atualmente selecionada.
        """
        logger.info("Descobrindo opções de legendas...")
        return await self._discover_section_options(
            SUBTITLE_SECTION_TITLE
        )

    async def select_option(
        self, section: str, option_text: str
    ) -> bool:
        """Clica em uma opção dentro de uma seção do dialog.

        Garante que o dialog está aberto, localiza a seção e
        clica na opção com texto correspondente. Após o clique,
        verifica se o dialog fechou automaticamente e atualiza
        o estado interno.

        Args:
            section: Título da seção (AUDIO_SECTION_TITLE ou
                SUBTITLE_SECTION_TITLE)
            option_text: Texto da opção a ser clicada

        Returns:
            True se o clique foi executado com sucesso, False caso
            contrário.

        Req 6.2: Registrar se dialog fechou após seleção.
        Req 6.3: Continuar sem reabrir se dialog permanece aberto.
        """
        logger.info(
            f"Selecionando opção '{option_text}' na seção "
            f"'{section}'..."
        )

        # Garantir dialog aberto (Req 6.1)
        if not await self.ensure_dialog_open():
            logger.error(
                "Não foi possível abrir o dialog para seleção."
            )
            return False

        # Localizar e clicar na opção
        clicked = await self._click_option_in_section(
            section, option_text
        )
        if not clicked:
            logger.warning(
                f"Opção '{option_text}' não encontrada na seção "
                f"'{section}'."
            )
            return False

        # Aguardar brevemente para o player processar o clique
        await asyncio.sleep(0.3)

        # Verificar se dialog fechou automaticamente (Req 6.2)
        if not await self._is_dialog_visible():
            logger.info(
                "Dialog fechou automaticamente após seleção."
            )
            self._dialog_visible = False
        else:
            logger.debug(
                "Dialog permanece aberto após seleção."
            )

        return True

    async def get_selected_option(
        self, section: str
    ) -> str | None:
        """Retorna o texto da opção atualmente selecionada em uma seção.

        Garante que o dialog está aberto e busca na seção
        especificada a opção que está marcada como ativa/selecionada.

        Args:
            section: Título da seção (AUDIO_SECTION_TITLE ou
                SUBTITLE_SECTION_TITLE)

        Returns:
            Texto da opção selecionada ou None se nenhuma encontrada.
        """
        logger.debug(
            f"Buscando opção selecionada na seção '{section}'..."
        )

        if not await self.ensure_dialog_open():
            logger.error(
                "Não foi possível abrir o dialog para consulta."
            )
            return None

        options = await self._discover_section_options(section)
        for option in options:
            if option.is_selected:
                logger.debug(
                    f"Opção selecionada: '{option.text}'"
                )
                return option.text

        logger.warning(
            f"Nenhuma opção selecionada encontrada na seção "
            f"'{section}'."
        )
        return None

    # ------------------------------------------------------------------
    # Métodos internos de descoberta e seleção
    # ------------------------------------------------------------------

    async def _discover_section_options(
        self, section_title: str
    ) -> list[TrackOption]:
        """Descobre todas as opções dentro de uma seção do dialog.

        Localiza o header da seção pelo texto e coleta todos os
        itens (opções) dentro dela, determinando qual está
        selecionada.

        Args:
            section_title: Texto do título da seção (ex: "IDIOMA
                ALTERNATIVO", "LEGENDAS")

        Returns:
            Lista de TrackOption encontrados na seção.
        """
        if not await self.ensure_dialog_open():
            logger.error(
                "Dialog não disponível para descoberta de opções."
            )
            return []

        # Estratégia: usar JavaScript para extrair opções do DOM
        # Isso é mais confiável que múltiplos locators sequenciais
        options_data = await self._extract_section_options_js(
            section_title
        )

        if not options_data:
            logger.warning(
                f"Nenhuma opção encontrada na seção "
                f"'{section_title}'."
            )
            return []

        # Converter para TrackOption
        track_options: list[TrackOption] = []
        for i, item in enumerate(options_data):
            track_options.append(
                TrackOption(
                    text=item["text"],
                    is_selected=item["is_selected"],
                    index=i,
                )
            )

        logger.info(
            f"Seção '{section_title}': {len(track_options)} opções "
            f"encontradas."
        )
        return track_options

    async def _extract_section_options_js(
        self, section_title: str
    ) -> list[dict]:
        """Extrai opções de uma seção via JavaScript no DOM.

        Executa um script no browser que:
        1. Localiza o elemento com texto do título da seção
        2. Encontra o container pai da seção
        3. Coleta todos os itens clicáveis dentro da seção
        4. Para cada item, extrai texto e estado de seleção

        Args:
            section_title: Texto do título da seção

        Returns:
            Lista de dicts com 'text' e 'is_selected' para cada opção.
        """
        js_script = """
        (sectionTitle) => {
            // Buscar elemento que contém o título da seção
            const allElements = document.querySelectorAll('*');
            let sectionHeader = null;

            for (const el of allElements) {
                const text = el.textContent?.trim();
                if (text === sectionTitle && el.children.length === 0) {
                    sectionHeader = el;
                    break;
                }
                // Fallback: verificar innerText direto
                if (el.innerText?.trim() === sectionTitle
                    && el.children.length <= 1) {
                    sectionHeader = el;
                    break;
                }
            }

            if (!sectionHeader) return [];

            // Subir para encontrar o container da seção
            let sectionContainer = sectionHeader.parentElement;
            // Tentar subir até encontrar um container que tenha
            // itens clicáveis (li, buttons, divs com role)
            for (let i = 0; i < 3; i++) {
                if (!sectionContainer) break;
                const items = sectionContainer.querySelectorAll(
                    'li, [role="option"], [role="menuitemradio"], '
                    + '[role="menuitem"], button'
                );
                if (items.length > 0) break;
                sectionContainer = sectionContainer.parentElement;
            }

            if (!sectionContainer) return [];

            // Coletar itens de opção dentro do container da seção
            const optionItems = sectionContainer.querySelectorAll(
                'li, [role="option"], [role="menuitemradio"], '
                + '[role="menuitem"]'
            );

            // Se não encontrou com esses seletores, tentar com
            // filhos diretos que sejam clicáveis
            let items = optionItems.length > 0
                ? optionItems
                : sectionContainer.querySelectorAll(
                    'button, div[class*="option"], div[class*="item"]'
                );

            // Filtrar o próprio header (não é uma opção)
            const results = [];
            for (const item of items) {
                const itemText = item.textContent?.trim();
                if (!itemText || itemText === sectionTitle) continue;
                // Verificar se já existe com mesmo texto (evitar duplicatas)
                if (results.some(r => r.text === itemText)) continue;

                // Determinar se está selecionado
                const classList = item.className || '';
                const ariaSelected = item.getAttribute('aria-selected');
                const ariaChecked = item.getAttribute('aria-checked');
                const isSelected = (
                    classList.includes('active') ||
                    classList.includes('selected') ||
                    classList.includes('checked') ||
                    classList.includes('current') ||
                    ariaSelected === 'true' ||
                    ariaChecked === 'true' ||
                    item.hasAttribute('data-selected') ||
                    item.hasAttribute('data-active')
                );

                results.push({
                    text: itemText,
                    is_selected: isSelected
                });
            }

            return results;
        }
        """

        try:
            result = await self._page.evaluate(
                js_script, section_title
            )
            if isinstance(result, list):
                return result
            return []
        except Exception as e:
            logger.error(
                f"Erro ao extrair opções da seção "
                f"'{section_title}' via JS: {e}"
            )
            return []

    async def _click_option_in_section(
        self, section_title: str, option_text: str
    ) -> bool:
        """Clica em uma opção específica dentro de uma seção.

        Usa JavaScript para localizar e clicar no elemento da opção.

        Args:
            section_title: Título da seção contendo a opção
            option_text: Texto da opção a ser clicada

        Returns:
            True se o clique foi executado, False se não encontrou.
        """
        js_click_script = """
        ([sectionTitle, optionText]) => {
            // Buscar header da seção
            const allElements = document.querySelectorAll('*');
            let sectionHeader = null;

            for (const el of allElements) {
                const text = el.textContent?.trim();
                if (text === sectionTitle && el.children.length === 0) {
                    sectionHeader = el;
                    break;
                }
                if (el.innerText?.trim() === sectionTitle
                    && el.children.length <= 1) {
                    sectionHeader = el;
                    break;
                }
            }

            if (!sectionHeader) return false;

            // Subir para container da seção
            let sectionContainer = sectionHeader.parentElement;
            for (let i = 0; i < 3; i++) {
                if (!sectionContainer) break;
                const items = sectionContainer.querySelectorAll(
                    'li, [role="option"], [role="menuitemradio"], '
                    + '[role="menuitem"], button'
                );
                if (items.length > 0) break;
                sectionContainer = sectionContainer.parentElement;
            }

            if (!sectionContainer) return false;

            // Buscar opção com texto correspondente
            const optionItems = sectionContainer.querySelectorAll(
                'li, [role="option"], [role="menuitemradio"], '
                + '[role="menuitem"], button, '
                + 'div[class*="option"], div[class*="item"]'
            );

            for (const item of optionItems) {
                const itemText = item.textContent?.trim();
                if (itemText === optionText) {
                    item.click();
                    return true;
                }
            }

            return false;
        }
        """

        try:
            result = await self._page.evaluate(
                js_click_script, [section_title, option_text]
            )
            if result:
                logger.debug(
                    f"Clique executado na opção '{option_text}' "
                    f"da seção '{section_title}'."
                )
            return bool(result)
        except Exception as e:
            logger.error(
                f"Erro ao clicar na opção '{option_text}' "
                f"da seção '{section_title}': {e}"
            )
            return False
