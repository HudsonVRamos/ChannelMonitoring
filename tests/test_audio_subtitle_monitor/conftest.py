"""Fixtures compartilhadas para testes do Audio & Subtitle Monitor.

Fornece mocks de Playwright Page, CapabilityMap e InteractionManager
usados por todos os testes do módulo.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.audio_subtitle_monitor.config import AudioSubtitleConfig


# ============================================================
# Fixtures - Playwright Page
# ============================================================


@pytest.fixture
def mock_page():
    """Mock de Page do Playwright com métodos async comuns.

    Simula os métodos mais utilizados pelo módulo:
    - evaluate: execução de JavaScript no browser
    - click: clique em elemento
    - hover: movimento do cursor sobre elemento
    - wait_for_selector: aguardar elemento no DOM
    - locator: criação de locator para interação
    - goto: navegação para URL
    """
    page = AsyncMock()

    # Métodos async principais
    page.evaluate = AsyncMock(return_value=None)
    page.click = AsyncMock()
    page.hover = AsyncMock()
    page.wait_for_selector = AsyncMock()
    page.goto = AsyncMock()

    # Locator retorna mock com métodos async
    mock_locator = AsyncMock()
    mock_locator.click = AsyncMock()
    mock_locator.hover = AsyncMock()
    mock_locator.is_visible = AsyncMock(return_value=True)
    mock_locator.count = AsyncMock(return_value=1)
    mock_locator.all_text_contents = AsyncMock(return_value=[])
    mock_locator.first = mock_locator
    mock_locator.nth = MagicMock(return_value=mock_locator)

    page.locator = MagicMock(return_value=mock_locator)
    page.get_by_role = MagicMock(return_value=mock_locator)
    page.get_by_label = MagicMock(return_value=mock_locator)
    page.get_by_text = MagicMock(return_value=mock_locator)

    return page


# ============================================================
# Fixtures - CapabilityMap
# ============================================================


@pytest.fixture
def mock_capability_map():
    """Mock do CapabilityMap com métodos de consulta de capabilities.

    Simula:
    - get_capability(name): retorna dados de uma capability
    - get_interaction_strategy(name): retorna estratégia de interação
    - is_valid(): verifica se o map é válido
    """
    capability_map = MagicMock()

    # Simula capability "settings" disponível com semantic_dom
    settings_capability = MagicMock()
    settings_capability.available = True
    settings_capability.interaction_strategy = "semantic_dom"
    settings_capability.selectors = {
        "icon": '[aria-label="settings"]',
        "dialog": ".settings-dialog",
    }

    capability_map.get_capability = MagicMock(return_value=settings_capability)
    capability_map.get_interaction_strategy = MagicMock(return_value="semantic_dom")
    capability_map.is_valid = MagicMock(return_value=True)

    return capability_map


# ============================================================
# Fixtures - InteractionManager
# ============================================================


@pytest.fixture
def mock_interaction_manager():
    """Mock do InteractionManager para interações via UI.

    Simula:
    - execute(page, action, target): executa interação no player
    - get_strategy_for(capability): retorna estratégia para capability
    """
    interaction_manager = MagicMock()

    interaction_manager.execute = AsyncMock(return_value=True)
    interaction_manager.get_strategy_for = MagicMock(return_value="semantic_dom")

    return interaction_manager


# ============================================================
# Fixtures - Config
# ============================================================


@pytest.fixture
def default_config():
    """Configuração padrão para testes com canais de exemplo."""
    return AudioSubtitleConfig(
        channels=[
            "https://www.skymais.com.br/player/live/CH0100000000124",
            "https://www.skymais.com.br/player/live/CH0100000000092",
        ],
        output_dir="test_reports/",
    )


@pytest.fixture
def output_dir(tmp_path):
    """Diretório temporário para output de relatórios."""
    output = tmp_path / "reports"
    output.mkdir()
    return output
