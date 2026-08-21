"""Fixtures compartilhadas para testes do Unified Channel Monitor.

Fornece mocks de Playwright Page e CapabilityMap usados por todos
os testes do módulo.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


# ============================================================
# Fixtures - Playwright Page
# ============================================================


@pytest.fixture
def mock_page():
    """Mock de Page do Playwright com métodos async comuns.

    Simula os métodos mais utilizados pelo módulo unificado:
    - goto: navegação para URL de canal
    - wait_for_selector: aguardar elemento <video> no DOM
    - evaluate: execução de JavaScript (telemetria, Shaka API, Web Audio)
    - click: clique em elementos da UI (Settings Dialog, tracks)
    - hover: movimento do cursor sobre elemento
    - locator: criação de locator para interação com DOM
    """
    page = AsyncMock()

    # Métodos async principais
    page.goto = AsyncMock()
    page.wait_for_selector = AsyncMock()
    page.evaluate = AsyncMock(return_value=None)
    page.click = AsyncMock()
    page.hover = AsyncMock()

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
def mock_capability_map() -> dict:
    """Mock do CapabilityMap com capabilities do player.

    Retorna um dict representando o CapabilityMap produzido pelo
    DiscoveryEngine, contendo as capabilities necessárias para
    Audio_Track_Tester e Subtitle_Track_Tester.

    Estrutura:
    - settings: capability de acesso ao Settings Dialog
    - audio: capability de interação com tracks de áudio
    - subtitles: capability de interação com tracks de legendas
    - player_type: tipo de player detectado (shaka)
    """
    return {
        "player_type": "shaka",
        "settings": {
            "available": True,
            "interaction_strategy": "semantic_dom",
            "selectors": {
                "icon": '[aria-label="settings"]',
                "dialog": ".settings-dialog",
            },
        },
        "audio": {
            "available": True,
            "section_label": "IDIOMA ALTERNATIVO",
            "api": "shaka_getAudioTracks",
        },
        "subtitles": {
            "available": True,
            "section_label": "LEGENDAS",
            "api": "shaka_getTextTracks",
        },
        "video_element": {
            "selector": "video",
            "supports_quality_info": True,
        },
    }
