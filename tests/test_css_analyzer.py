"""Testes unitários para o CSSAnalyzer.

Verifica que o CSSAnalyzer:
- Coleta evidência auxiliar de CSS corretamente
- NUNCA produz confidence_contribution >= 0.7 (max 0.4)
- Identifica visibilidade, interatividade e estados ativos
- Lida graciosamente com falhas de page.evaluate()
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.player_discovery.discovery.css_analyzer import (
    CSSAnalyzer,
    CSSEvidence,
    MAX_CSS_ONLY_CONFIDENCE,
)


@pytest.fixture
def analyzer():
    """Instância do CSSAnalyzer para testes."""
    return CSSAnalyzer()


@pytest.fixture
def mock_page():
    """Mock do Playwright Page."""
    page = AsyncMock()
    return page


class TestCSSAnalyzerAnalyze:
    """Testes para o método analyze() do CSSAnalyzer."""

    @pytest.mark.asyncio
    async def test_retorna_lista_vazia_quando_nenhum_elemento(
        self, analyzer, mock_page
    ):
        """Deve retornar lista vazia quando não há elementos candidatos."""
        mock_page.evaluate.return_value = []
        result = await analyzer.analyze(mock_page)
        assert result == []

    @pytest.mark.asyncio
    async def test_retorna_lista_vazia_em_caso_de_excecao(
        self, analyzer, mock_page
    ):
        """Deve retornar lista vazia quando page.evaluate() falha."""
        mock_page.evaluate.side_effect = Exception("Page crashed")
        result = await analyzer.analyze(mock_page)
        assert result == []

    @pytest.mark.asyncio
    async def test_coleta_evidencia_de_elemento_visivel_e_interativo(
        self, analyzer, mock_page
    ):
        """Deve coletar evidência com is_visible e is_interactive corretos."""
        mock_page.evaluate.return_value = [
            {
                "description": 'button[aria-label="Play"]',
                "capabilityHint": "play",
                "properties": {
                    "display": "flex",
                    "visibility": "visible",
                    "opacity": 1.0,
                    "pointerEvents": "auto",
                    "cursor": "pointer",
                    "position": "relative",
                    "zIndex": "1",
                },
                "states": {
                    "ariaPressed": None,
                    "ariaSelected": None,
                    "ariaExpanded": None,
                    "ariaChecked": None,
                    "dataActive": False,
                    "classList": [],
                },
                "isVisible": True,
                "isInteractive": True,
                "hasActiveState": False,
            }
        ]

        result = await analyzer.analyze(mock_page)

        assert len(result) == 1
        evidence = result[0]
        assert evidence.is_visible is True
        assert evidence.is_interactive is True
        assert evidence.has_active_state is False
        assert evidence.capability_hint == "play"
        assert evidence.element_description == 'button[aria-label="Play"]'

    @pytest.mark.asyncio
    async def test_coleta_evidencia_com_estado_ativo(
        self, analyzer, mock_page
    ):
        """Deve detectar estado active/selected corretamente."""
        mock_page.evaluate.return_value = [
            {
                "description": 'button[aria-label="Mute"]',
                "capabilityHint": "mute",
                "properties": {
                    "display": "block",
                    "visibility": "visible",
                    "opacity": 1.0,
                    "pointerEvents": "auto",
                    "cursor": "pointer",
                    "position": "absolute",
                    "zIndex": "10",
                },
                "states": {
                    "ariaPressed": "true",
                    "ariaSelected": None,
                    "ariaExpanded": None,
                    "ariaChecked": None,
                    "dataActive": False,
                    "classList": ["active"],
                },
                "isVisible": True,
                "isInteractive": True,
                "hasActiveState": True,
            }
        ]

        result = await analyzer.analyze(mock_page)

        assert len(result) == 1
        evidence = result[0]
        assert evidence.has_active_state is True
        assert evidence.capability_hint == "mute"

    @pytest.mark.asyncio
    async def test_confidence_nunca_excede_max(
        self, analyzer, mock_page
    ):
        """confidence_contribution NUNCA deve exceder MAX_CSS_ONLY_CONFIDENCE."""
        # Cenário com todas as condições que aumentam confidence
        mock_page.evaluate.return_value = [
            {
                "description": 'button[role="button"]',
                "capabilityHint": "play",
                "properties": {
                    "display": "flex",
                    "visibility": "visible",
                    "opacity": 1.0,
                    "pointerEvents": "auto",
                    "cursor": "pointer",
                    "position": "relative",
                    "zIndex": "5",
                },
                "states": {
                    "ariaPressed": "true",
                    "ariaSelected": "true",
                    "ariaExpanded": None,
                    "ariaChecked": None,
                    "dataActive": True,
                    "classList": ["active", "selected"],
                },
                "isVisible": True,
                "isInteractive": True,
                "hasActiveState": True,
            }
        ]

        result = await analyzer.analyze(mock_page)

        assert len(result) == 1
        evidence = result[0]
        assert evidence.confidence_contribution <= MAX_CSS_ONLY_CONFIDENCE
        assert evidence.confidence_contribution <= 0.4

    @pytest.mark.asyncio
    async def test_elemento_invisivel_tem_baixa_confidence(
        self, analyzer, mock_page
    ):
        """Elementos invisíveis devem ter confidence mais baixa."""
        mock_page.evaluate.return_value = [
            {
                "description": 'button[aria-label="Settings"]',
                "capabilityHint": "settings",
                "properties": {
                    "display": "none",
                    "visibility": "hidden",
                    "opacity": 0.0,
                    "pointerEvents": "none",
                    "cursor": "default",
                    "position": "absolute",
                    "zIndex": "-1",
                },
                "states": {
                    "ariaPressed": None,
                    "ariaSelected": None,
                    "ariaExpanded": None,
                    "ariaChecked": None,
                    "dataActive": False,
                    "classList": [],
                },
                "isVisible": False,
                "isInteractive": False,
                "hasActiveState": False,
            }
        ]

        result = await analyzer.analyze(mock_page)

        assert len(result) == 1
        evidence = result[0]
        # Apenas capability_hint reconhecido: +0.05
        assert evidence.confidence_contribution <= 0.05
        assert evidence.is_visible is False
        assert evidence.is_interactive is False

    @pytest.mark.asyncio
    async def test_multiplos_elementos(
        self, analyzer, mock_page
    ):
        """Deve processar múltiplos elementos retornados."""
        mock_page.evaluate.return_value = [
            {
                "description": 'button[aria-label="Play"]',
                "capabilityHint": "play",
                "properties": {},
                "states": {},
                "isVisible": True,
                "isInteractive": True,
                "hasActiveState": False,
            },
            {
                "description": 'button[aria-label="Pause"]',
                "capabilityHint": "pause",
                "properties": {},
                "states": {},
                "isVisible": True,
                "isInteractive": False,
                "hasActiveState": True,
            },
            {
                "description": 'div[role="slider"]',
                "capabilityHint": "unknown",
                "properties": {},
                "states": {},
                "isVisible": False,
                "isInteractive": False,
                "hasActiveState": False,
            },
        ]

        result = await analyzer.analyze(mock_page)

        assert len(result) == 3
        # Verificar que todos respeitam o máximo
        for evidence in result:
            assert evidence.confidence_contribution <= MAX_CSS_ONLY_CONFIDENCE


class TestCSSEvidencePostInit:
    """Testes para o __post_init__ do CSSEvidence."""

    def test_clamp_confidence_acima_do_maximo(self):
        """Deve clampear confidence_contribution para o máximo."""
        evidence = CSSEvidence(
            element_description="test",
            capability_hint="play",
            confidence_contribution=0.9,  # Acima do máximo
        )
        assert evidence.confidence_contribution == MAX_CSS_ONLY_CONFIDENCE

    def test_confidence_abaixo_do_maximo_nao_muda(self):
        """Não deve alterar confidence_contribution dentro do range válido."""
        evidence = CSSEvidence(
            element_description="test",
            capability_hint="play",
            confidence_contribution=0.2,
        )
        assert evidence.confidence_contribution == 0.2

    def test_confidence_zero_permitida(self):
        """confidence_contribution=0.0 é válida."""
        evidence = CSSEvidence(
            element_description="test",
            capability_hint="unknown",
            confidence_contribution=0.0,
        )
        assert evidence.confidence_contribution == 0.0

    def test_confidence_no_maximo_exato(self):
        """confidence_contribution exatamente no MAX deve ser aceita."""
        evidence = CSSEvidence(
            element_description="test",
            capability_hint="play",
            confidence_contribution=MAX_CSS_ONLY_CONFIDENCE,
        )
        assert evidence.confidence_contribution == MAX_CSS_ONLY_CONFIDENCE


class TestCSSAnalyzerCalculateConfidence:
    """Testes para o cálculo de confidence interno."""

    def test_calculo_elemento_completo(self):
        """Elemento visível + interativo + ativo + hint = máximo (0.4)."""
        analyzer = CSSAnalyzer()
        result = {
            "isVisible": True,        # +0.15
            "isInteractive": True,    # +0.10
            "hasActiveState": True,   # +0.10
            "capabilityHint": "play", # +0.05
        }
        confidence = analyzer._calculate_confidence(result)
        assert confidence == pytest.approx(MAX_CSS_ONLY_CONFIDENCE)  # 0.4

    def test_calculo_apenas_visivel(self):
        """Apenas visível: 0.15."""
        analyzer = CSSAnalyzer()
        result = {
            "isVisible": True,
            "isInteractive": False,
            "hasActiveState": False,
            "capabilityHint": "unknown",
        }
        confidence = analyzer._calculate_confidence(result)
        assert confidence == 0.15

    def test_calculo_visivel_e_interativo(self):
        """Visível + interativo: 0.25."""
        analyzer = CSSAnalyzer()
        result = {
            "isVisible": True,
            "isInteractive": True,
            "hasActiveState": False,
            "capabilityHint": "unknown",
        }
        confidence = analyzer._calculate_confidence(result)
        assert confidence == 0.25

    def test_calculo_nenhuma_evidencia(self):
        """Sem nenhuma evidência positiva: 0.0."""
        analyzer = CSSAnalyzer()
        result = {
            "isVisible": False,
            "isInteractive": False,
            "hasActiveState": False,
            "capabilityHint": "unknown",
        }
        confidence = analyzer._calculate_confidence(result)
        assert confidence == 0.0


class TestMAXCSSOnlyConfidence:
    """Testa a constante MAX_CSS_ONLY_CONFIDENCE."""

    def test_max_confidence_is_below_threshold(self):
        """MAX_CSS_ONLY_CONFIDENCE deve ser < 0.7 (threshold de available)."""
        assert MAX_CSS_ONLY_CONFIDENCE < 0.7

    def test_max_confidence_is_0_4(self):
        """MAX_CSS_ONLY_CONFIDENCE deve ser exatamente 0.4."""
        assert MAX_CSS_ONLY_CONFIDENCE == 0.4
