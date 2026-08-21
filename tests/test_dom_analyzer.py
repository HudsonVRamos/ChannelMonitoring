"""Testes unitários para o DOMAnalyzer.

Testa a análise semântica do DOM sem utilizar seletores CSS fixos,
IDs específicos ou classes CSS.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.player_discovery.discovery.dom_analyzer import (
    DOMAnalyzer,
    DOMEvidence,
    CAPABILITY_KEYWORDS,
    INTERACTIVE_ROLES,
)
from src.player_discovery.models.enums import InteractionLevel


@pytest.fixture
def analyzer():
    """Fixture que retorna uma instância do DOMAnalyzer."""
    return DOMAnalyzer()


@pytest.fixture
def mock_page():
    """Fixture que retorna um mock de Page do Playwright."""
    page = AsyncMock()
    return page


class TestDOMAnalyzerAnalyze:
    """Testes para o método analyze()."""

    @pytest.mark.asyncio
    async def test_analyze_returns_list(self, analyzer, mock_page):
        """analyze() deve retornar uma lista de DOMEvidence."""
        mock_page.evaluate.return_value = []
        result = await analyzer.analyze(mock_page)
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_analyze_with_play_button(self, analyzer, mock_page):
        """Identifica botão de play via aria-label."""
        mock_page.evaluate.return_value = [
            {
                "tag": "button",
                "role": "button",
                "aria_label": "Play",
                "aria_haspopup": "",
                "title": "",
                "tabindex": "0",
                "text_content": "",
                "data_attributes": {},
                "is_visible": True,
                "is_interactive": True,
            }
        ]
        result = await analyzer.analyze(mock_page)
        assert len(result) == 1
        assert result[0].capability_hint == "play"
        assert result[0].interaction_hint == InteractionLevel.SEMANTIC_DOM

    @pytest.mark.asyncio
    async def test_analyze_with_mute_button(self, analyzer, mock_page):
        """Identifica botão de mute via title."""
        mock_page.evaluate.return_value = [
            {
                "tag": "button",
                "role": "button",
                "aria_label": "",
                "aria_haspopup": "",
                "title": "Mute",
                "tabindex": "0",
                "text_content": "",
                "data_attributes": {},
                "is_visible": True,
                "is_interactive": True,
            }
        ]
        result = await analyzer.analyze(mock_page)
        assert len(result) == 1
        assert result[0].capability_hint == "mute"

    @pytest.mark.asyncio
    async def test_analyze_with_subtitle_via_data_attr(self, analyzer, mock_page):
        """Identifica controle de legendas via data-attribute."""
        mock_page.evaluate.return_value = [
            {
                "tag": "div",
                "role": "",
                "aria_label": "",
                "aria_haspopup": "",
                "title": "",
                "tabindex": "0",
                "text_content": "",
                "data_attributes": {"data-control": "subtitle"},
                "is_visible": True,
                "is_interactive": True,
            }
        ]
        result = await analyzer.analyze(mock_page)
        assert len(result) == 1
        assert result[0].capability_hint == "subtitle_selection"

    @pytest.mark.asyncio
    async def test_analyze_with_fullscreen_via_text_content(self, analyzer, mock_page):
        """Identifica botão fullscreen via textContent."""
        mock_page.evaluate.return_value = [
            {
                "tag": "button",
                "role": "button",
                "aria_label": "",
                "aria_haspopup": "",
                "title": "",
                "tabindex": None,
                "text_content": "Tela cheia",
                "data_attributes": {},
                "is_visible": True,
                "is_interactive": True,
            }
        ]
        result = await analyzer.analyze(mock_page)
        assert len(result) == 1
        assert result[0].capability_hint == "fullscreen"

    @pytest.mark.asyncio
    async def test_analyze_empty_dom(self, analyzer, mock_page):
        """DOM vazio retorna lista vazia."""
        mock_page.evaluate.return_value = []
        result = await analyzer.analyze(mock_page)
        assert result == []

    @pytest.mark.asyncio
    async def test_analyze_ignores_non_capability_elements(self, analyzer, mock_page):
        """Elementos sem match de capability são ignorados."""
        mock_page.evaluate.return_value = [
            {
                "tag": "div",
                "role": "navigation",
                "aria_label": "Menu principal",
                "aria_haspopup": "",
                "title": "",
                "tabindex": None,
                "text_content": "Home About Contact",
                "data_attributes": {},
                "is_visible": True,
                "is_interactive": False,
            }
        ]
        result = await analyzer.analyze(mock_page)
        assert result == []

    @pytest.mark.asyncio
    async def test_analyze_handles_page_evaluate_error(self, analyzer, mock_page):
        """Erro no page.evaluate() retorna lista vazia."""
        mock_page.evaluate.side_effect = Exception("Page crashed")
        result = await analyzer.analyze(mock_page)
        assert result == []

    @pytest.mark.asyncio
    async def test_analyze_multiple_capabilities(self, analyzer, mock_page):
        """Identifica múltiplas capabilities em um DOM complexo."""
        mock_page.evaluate.return_value = [
            {
                "tag": "button",
                "role": "button",
                "aria_label": "Play",
                "aria_haspopup": "",
                "title": "",
                "tabindex": "0",
                "text_content": "",
                "data_attributes": {},
                "is_visible": True,
                "is_interactive": True,
            },
            {
                "tag": "button",
                "role": "button",
                "aria_label": "Pause",
                "aria_haspopup": "",
                "title": "",
                "tabindex": "0",
                "text_content": "",
                "data_attributes": {},
                "is_visible": True,
                "is_interactive": True,
            },
            {
                "tag": "div",
                "role": "slider",
                "aria_label": "Quality",
                "aria_haspopup": "",
                "title": "",
                "tabindex": "0",
                "text_content": "",
                "data_attributes": {},
                "is_visible": True,
                "is_interactive": True,
            },
        ]
        result = await analyzer.analyze(mock_page)
        assert len(result) == 3
        hints = {e.capability_hint for e in result}
        assert "play" in hints
        assert "pause" in hints
        assert "quality_selection" in hints


class TestDOMAnalyzerConfidence:
    """Testes para o cálculo de confidence."""

    @pytest.mark.asyncio
    async def test_high_confidence_with_all_semantic_attrs(self, analyzer, mock_page):
        """Elemento com todos os atributos semânticos tem alta confidence."""
        mock_page.evaluate.return_value = [
            {
                "tag": "button",
                "role": "button",
                "aria_label": "Play video",
                "aria_haspopup": "true",
                "title": "Play",
                "tabindex": "0",
                "text_content": "Play",
                "data_attributes": {"data-action": "play"},
                "is_visible": True,
                "is_interactive": True,
            }
        ]
        result = await analyzer.analyze(mock_page)
        assert len(result) == 1
        # Alta confidence: aria-label(0.3) + role(0.2) + title(0.1) + visible(0.1) +
        # interactive(0.1) + data-attrs(0.1) + aria-haspopup(0.1) = 1.0
        assert result[0].confidence_contribution == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_low_confidence_with_minimal_attrs(self, analyzer, mock_page):
        """Elemento com poucos atributos tem baixa confidence."""
        mock_page.evaluate.return_value = [
            {
                "tag": "div",
                "role": "",
                "aria_label": "",
                "aria_haspopup": "",
                "title": "Play",
                "tabindex": None,
                "text_content": "",
                "data_attributes": {},
                "is_visible": False,
                "is_interactive": False,
            }
        ]
        result = await analyzer.analyze(mock_page)
        assert len(result) == 1
        # Apenas title(0.1) = 0.1
        assert result[0].confidence_contribution == 0.1


class TestDOMAnalyzerInteractionLevel:
    """Testes para a determinação do nível de interação."""

    @pytest.mark.asyncio
    async def test_player_api_level_with_data_player(self, analyzer, mock_page):
        """Elemento com data-player sugere interação via API."""
        mock_page.evaluate.return_value = [
            {
                "tag": "button",
                "role": "button",
                "aria_label": "Play",
                "aria_haspopup": "",
                "title": "",
                "tabindex": "0",
                "text_content": "",
                "data_attributes": {"data-player": "main"},
                "is_visible": True,
                "is_interactive": True,
            }
        ]
        result = await analyzer.analyze(mock_page)
        assert len(result) == 1
        assert result[0].interaction_hint == InteractionLevel.PLAYER_API

    @pytest.mark.asyncio
    async def test_player_api_level_with_data_action(self, analyzer, mock_page):
        """Elemento com data-action sugere interação via API."""
        mock_page.evaluate.return_value = [
            {
                "tag": "button",
                "role": "button",
                "aria_label": "Pause",
                "aria_haspopup": "",
                "title": "",
                "tabindex": "0",
                "text_content": "",
                "data_attributes": {"data-action": "pause"},
                "is_visible": True,
                "is_interactive": True,
            }
        ]
        result = await analyzer.analyze(mock_page)
        assert len(result) == 1
        assert result[0].interaction_hint == InteractionLevel.PLAYER_API

    @pytest.mark.asyncio
    async def test_semantic_dom_level_default(self, analyzer, mock_page):
        """Elemento sem indicadores de API tem nível DOM semântico."""
        mock_page.evaluate.return_value = [
            {
                "tag": "button",
                "role": "button",
                "aria_label": "Settings",
                "aria_haspopup": "",
                "title": "",
                "tabindex": "0",
                "text_content": "",
                "data_attributes": {},
                "is_visible": True,
                "is_interactive": True,
            }
        ]
        result = await analyzer.analyze(mock_page)
        assert len(result) == 1
        assert result[0].interaction_hint == InteractionLevel.SEMANTIC_DOM


class TestDOMAnalyzerAttributes:
    """Testes para extração de atributos semânticos."""

    @pytest.mark.asyncio
    async def test_attributes_contain_semantic_info(self, analyzer, mock_page):
        """Os atributos extraídos contêm apenas informação semântica."""
        mock_page.evaluate.return_value = [
            {
                "tag": "button",
                "role": "button",
                "aria_label": "Play",
                "aria_haspopup": "dialog",
                "title": "Reproduzir",
                "tabindex": "0",
                "text_content": "",
                "data_attributes": {"data-testid": "play-btn"},
                "is_visible": True,
                "is_interactive": True,
            }
        ]
        result = await analyzer.analyze(mock_page)
        assert len(result) == 1
        attrs = result[0].attributes
        assert attrs["role"] == "button"
        assert attrs["aria-label"] == "Play"
        assert attrs["aria-haspopup"] == "dialog"
        assert attrs["title"] == "Reproduzir"
        assert attrs["tabindex"] == "0"
        assert attrs["data-testid"] == "play-btn"

    @pytest.mark.asyncio
    async def test_no_css_ids_or_classes_in_attributes(self, analyzer, mock_page):
        """Nenhum ID ou classe CSS é incluído nos atributos."""
        mock_page.evaluate.return_value = [
            {
                "tag": "button",
                "role": "button",
                "aria_label": "Mute",
                "aria_haspopup": "",
                "title": "",
                "tabindex": None,
                "text_content": "",
                "data_attributes": {},
                "is_visible": True,
                "is_interactive": True,
            }
        ]
        result = await analyzer.analyze(mock_page)
        assert len(result) == 1
        attrs = result[0].attributes
        # Não deve conter id ou class
        assert "id" not in attrs
        assert "class" not in attrs
        assert "className" not in attrs


class TestDOMEvidenceDataclass:
    """Testes para a dataclass DOMEvidence."""

    def test_create_evidence(self):
        """Cria DOMEvidence com todos os campos."""
        evidence = DOMEvidence(
            element_description="button com role='button', aria-label='Play'",
            capability_hint="play",
            confidence_contribution=0.7,
            attributes={"role": "button", "aria-label": "Play"},
            interaction_hint=InteractionLevel.SEMANTIC_DOM,
        )
        assert evidence.element_description == "button com role='button', aria-label='Play'"
        assert evidence.capability_hint == "play"
        assert evidence.confidence_contribution == 0.7
        assert evidence.attributes == {"role": "button", "aria-label": "Play"}
        assert evidence.interaction_hint == InteractionLevel.SEMANTIC_DOM

    def test_create_evidence_defaults(self):
        """Cria DOMEvidence com defaults."""
        evidence = DOMEvidence(
            element_description="test",
            capability_hint="play",
            confidence_contribution=0.5,
        )
        assert evidence.attributes == {}
        assert evidence.interaction_hint == InteractionLevel.SEMANTIC_DOM


class TestCapabilityKeywords:
    """Testes para o mapeamento de keywords."""

    def test_all_required_capabilities_have_keywords(self):
        """Todas as capabilities obrigatórias têm keywords definidas."""
        required = [
            "play", "pause", "mute", "unmute",
            "audio_selection", "subtitle_selection",
            "quality_selection", "fullscreen", "settings",
        ]
        for cap in required:
            assert cap in CAPABILITY_KEYWORDS, f"Capability '{cap}' sem keywords"
            assert len(CAPABILITY_KEYWORDS[cap]) > 0

    def test_keywords_are_lowercase(self):
        """Todas as keywords devem estar em minúsculas para matching."""
        for cap, keywords in CAPABILITY_KEYWORDS.items():
            for kw in keywords:
                assert kw == kw.lower(), f"Keyword '{kw}' em '{cap}' não está lowercase"
