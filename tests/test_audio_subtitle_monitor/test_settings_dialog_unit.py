"""Unit tests para o SettingsDialogManager do Audio & Subtitle Monitor.

Testa cenários específicos de abertura/fechamento do dialog, hover,
retry, e gerenciamento de estado usando mocks de Playwright.

Requirements: 1.1, 1.2, 1.4, 6.1, 6.2, 6.3, 6.4
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.audio_subtitle_monitor.config import AudioSubtitleConfig
from src.audio_subtitle_monitor.settings_dialog_manager import (
    DIALOG_SELECTORS,
    PLAYER_CONTAINER_SELECTORS,
    SettingsDialogManager,
)


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def config():
    """Configuração com timeouts curtos para testes rápidos."""
    return AudioSubtitleConfig(
        channels=[],
        settings_dialog_timeout_s=0.1,
        dialog_retry_wait_s=0.01,
    )


@pytest.fixture
def page():
    """Mock de Playwright Page com defaults para testes."""
    mock_page = AsyncMock()

    # Locator padrão com métodos necessários
    mock_locator = AsyncMock()
    mock_locator.count = AsyncMock(return_value=1)
    mock_locator.click = AsyncMock()
    mock_locator.first = mock_locator
    mock_locator.is_visible = AsyncMock(return_value=False)

    mock_page.get_by_role = MagicMock(return_value=mock_locator)
    mock_page.locator = MagicMock(return_value=mock_locator)
    mock_page.hover = AsyncMock()
    mock_page.wait_for_selector = AsyncMock()
    mock_page.keyboard = AsyncMock()
    mock_page.keyboard.press = AsyncMock()
    mock_page.evaluate = AsyncMock(return_value=[])

    return mock_page


@pytest.fixture
def capability_map():
    """Mock do CapabilityMap com semantic_dom como estratégia."""
    cm = MagicMock()
    cm.get_interaction_strategy = MagicMock(
        return_value="semantic_dom"
    )
    return cm


@pytest.fixture
def manager(page, capability_map, config):
    """Instância do SettingsDialogManager para testes."""
    return SettingsDialogManager(
        page=page,
        capability_map=capability_map,
        config=config,
    )


# ============================================================
# Testes de abertura do dialog
# ============================================================


class TestOpenDialog:
    """Testes de abertura do Settings Dialog (Req 1.1, 1.2)."""

    @pytest.mark.asyncio
    async def test_open_dialog_success(
        self, manager, page
    ):
        """Abertura bem-sucedida retorna True e marca visível.

        Req 1.2: Clicar no Settings_Icon e aguardar até 5s
        pela aparição do Settings_Dialog.
        """
        # O locator (retornado por get_by_role) tem count=1
        # e wait_for_selector não levanta exceção → sucesso
        result = await manager.open_dialog()

        assert result is True
        assert manager._dialog_visible is True

    @pytest.mark.asyncio
    async def test_open_dialog_icon_not_found(
        self, manager, page
    ):
        """Ícone não encontrado → retorna False após retry.

        Req 1.4: Se o Settings_Icon não for encontrado, classificar
        como FAIL.
        """
        # Nenhum locator encontra o ícone (count retorna 0)
        mock_locator = AsyncMock()
        mock_locator.count = AsyncMock(return_value=0)
        mock_locator.first = mock_locator
        mock_locator.is_visible = AsyncMock(return_value=False)

        page.get_by_role = MagicMock(return_value=mock_locator)
        page.locator = MagicMock(return_value=mock_locator)

        result = await manager.open_dialog()

        assert result is False
        assert manager._dialog_visible is False

    @pytest.mark.asyncio
    async def test_open_dialog_timeout_then_retry_succeeds(
        self, manager, page
    ):
        """Primeira tentativa falha por timeout, retry abre.

        Req 6.4: Fechar o diálogo, aguardar 2s e tentar reabrir
        uma vez antes de classificar como FAIL.
        """
        call_count = {"n": 0}

        async def wait_side_effect(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] <= len(DIALOG_SELECTORS):
                # Primeira tentativa: todos os seletores falham
                raise TimeoutError("Dialog não apareceu")
            # Retry: primeiro seletor funciona
            return MagicMock()

        page.wait_for_selector = AsyncMock(
            side_effect=wait_side_effect
        )

        result = await manager.open_dialog()

        assert result is True
        assert manager._dialog_visible is True

    @pytest.mark.asyncio
    async def test_open_dialog_timeout_all_retries_fail(
        self, manager, page
    ):
        """Ambas tentativas falham por timeout → retorna False.

        Req 1.4: Se o Settings_Dialog não aparecer dentro de 5s
        após o clique, classificar como FAIL.
        """
        page.wait_for_selector = AsyncMock(
            side_effect=TimeoutError("Dialog não apareceu")
        )

        result = await manager.open_dialog()

        assert result is False
        assert manager._dialog_visible is False


# ============================================================
# Testes de fechamento do dialog
# ============================================================


class TestCloseDialog:
    """Testes de fechamento do Settings Dialog (Req 6.5)."""

    @pytest.mark.asyncio
    async def test_close_dialog(self, manager, page):
        """Fechar o dialog pressiona Escape e marca como não visível.

        Req 6.5: Fechar o Settings_Dialog ao final de cada
        Monitoring_Session.
        """
        manager._dialog_visible = True

        result = await manager.close_dialog()

        assert result is True
        assert manager._dialog_visible is False
        page.keyboard.press.assert_called_once_with("Escape")


# ============================================================
# Testes de ensure_dialog_open
# ============================================================


class TestEnsureDialogOpen:
    """Testes de ensure_dialog_open (Req 6.1)."""

    @pytest.mark.asyncio
    async def test_ensure_dialog_open_already_visible(
        self, manager, page
    ):
        """Dialog já visível → retorna True sem reabrir.

        Req 6.3: Se o dialog permanece aberto, continuar seleção
        sem fechar e reabrir.
        """
        # Simular que o locator de dialog está visível
        mock_locator = AsyncMock()
        mock_locator.is_visible = AsyncMock(return_value=True)
        page.locator = MagicMock(return_value=mock_locator)

        result = await manager.ensure_dialog_open()

        assert result is True
        assert manager._dialog_visible is True
        # Não deve ter tentado hover (não reabriu)
        page.hover.assert_not_called()

    @pytest.mark.asyncio
    async def test_ensure_dialog_open_needs_reopen(
        self, manager, page
    ):
        """Dialog não visível → chama open_dialog para reabrir.

        Req 6.1: Se o diálogo não está visível, reabrir
        clicando no Settings_Icon.
        """
        # Locator padrão para is_visible (dialog check)
        dialog_locator = AsyncMock()
        dialog_locator.is_visible = AsyncMock(return_value=False)

        # Locator para o ícone (get_by_role retorna locator com count>0)
        icon_locator = AsyncMock()
        icon_locator.count = AsyncMock(return_value=1)
        icon_locator.click = AsyncMock()
        icon_locator.first = icon_locator

        page.locator = MagicMock(return_value=dialog_locator)
        page.get_by_role = MagicMock(return_value=icon_locator)

        result = await manager.ensure_dialog_open()

        assert result is True
        # Hover foi chamado (show_player_controls)
        page.hover.assert_called()


# ============================================================
# Testes de _show_player_controls
# ============================================================


class TestShowPlayerControls:
    """Testes de hover para exibir controles (Req 1.5)."""

    @pytest.mark.asyncio
    async def test_show_player_controls_hover_success(
        self, manager, page
    ):
        """Hover no primeiro container funciona.

        Req 1.5: Mover cursor sobre o player para acionar
        exibição dos controles.
        """
        await manager._show_player_controls()

        # O hover deve ser chamado com o primeiro seletor
        page.hover.assert_called_once_with(
            PLAYER_CONTAINER_SELECTORS[0]
        )

    @pytest.mark.asyncio
    async def test_show_player_controls_all_selectors_fail(
        self, manager, page
    ):
        """Todos os seletores de hover falham → continua sem erro.

        O método não levanta exceção mesmo quando nenhum container
        é encontrado — o fluxo prossegue para buscar o ícone.
        """
        page.hover = AsyncMock(
            side_effect=Exception("Elemento não encontrado")
        )

        # Não deve levantar exceção
        await manager._show_player_controls()


# ============================================================
# Testes de select_option
# ============================================================


class TestSelectOption:
    """Testes de seleção de opção no dialog (Req 6.2, 6.3)."""

    @pytest.mark.asyncio
    async def test_select_option_dialog_closes_after(
        self, manager, page
    ):
        """Após selecionar, dialog não está mais visível → marca False.

        Req 6.2: Se o dialog fecha automaticamente após seleção,
        registrar que foi fechado.
        """
        # Dialog visível para is_visible checks iniciais
        # Mas após seleção, não está mais visível
        visibility_calls = {"count": 0}

        # Primeira verificação (ensure_dialog_open): visível
        # Segunda verificação (após click): não visível
        async def locator_is_visible():
            visibility_calls["count"] += 1
            if visibility_calls["count"] <= 1:
                return True  # ensure_dialog_open → já está aberto
            return False  # após seleção → fechou

        mock_locator = AsyncMock()
        mock_locator.is_visible = AsyncMock(
            side_effect=locator_is_visible
        )
        page.locator = MagicMock(return_value=mock_locator)

        # evaluate para _click_option_in_section retorna True
        page.evaluate = AsyncMock(return_value=True)

        result = await manager.select_option(
            "IDIOMA ALTERNATIVO", "Português"
        )

        assert result is True
        assert manager._dialog_visible is False

    @pytest.mark.asyncio
    async def test_select_option_dialog_stays_open(
        self, manager, page
    ):
        """Após selecionar, dialog permanece visível → mantém True.

        Req 6.3: Se o dialog permanece aberto, continuar sem
        fechar e reabrir.
        """
        # Dialog sempre visível
        mock_locator = AsyncMock()
        mock_locator.is_visible = AsyncMock(return_value=True)
        page.locator = MagicMock(return_value=mock_locator)

        # evaluate retorna True (clique executado)
        page.evaluate = AsyncMock(return_value=True)

        manager._dialog_visible = True

        result = await manager.select_option(
            "LEGENDAS", "Português"
        )

        assert result is True
        # Dialog permanece marcado como visível
        # (ensure_dialog_open vê visível, após clique continua visível)
        assert manager._dialog_visible is True

    @pytest.mark.asyncio
    async def test_select_option_not_found(
        self, manager, page
    ):
        """Opção não encontrada na seção → retorna False.

        O evaluate do JS retorna False quando a opção não existe
        no DOM.
        """
        # Dialog visível
        mock_locator = AsyncMock()
        mock_locator.is_visible = AsyncMock(return_value=True)
        page.locator = MagicMock(return_value=mock_locator)

        # evaluate retorna False (opção não encontrada)
        page.evaluate = AsyncMock(return_value=False)

        result = await manager.select_option(
            "IDIOMA ALTERNATIVO", "Japonês"
        )

        assert result is False
