"""Testes unitários para o JSAnalyzer.

Testa a análise de JavaScript APIs do player via page.evaluate(),
incluindo detecção de biblioteca, versão e APIs disponíveis.

Requirements: 1.3
"""

import pytest
from unittest.mock import AsyncMock

from src.player_discovery.discovery.js_analyzer import (
    JSAnalyzer,
    JSEvidence,
    CAPABILITY_API_MAP,
    KNOWN_PLAYER_GLOBALS,
)
from src.player_discovery.models.enums import InteractionLevel


@pytest.fixture
def analyzer():
    """Fixture que retorna uma instância do JSAnalyzer."""
    return JSAnalyzer()


@pytest.fixture
def mock_page():
    """Fixture que retorna um mock de Page do Playwright."""
    page = AsyncMock()
    return page


class TestJSAnalyzerAnalyze:
    """Testes para o método analyze()."""

    @pytest.mark.asyncio
    async def test_analyze_returns_list(
        self, analyzer, mock_page
    ):
        """analyze() deve retornar uma lista de JSEvidence."""
        mock_page.evaluate.return_value = {
            "library": None,
            "version": None,
            "player_instance": None,
            "globals_found": [],
        }
        result = await analyzer.analyze(mock_page)
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_analyze_detects_shaka_player(
        self, analyzer, mock_page
    ):
        """Detecta shaka-player via objeto global."""
        # Primeiro evaluate: _detect_player_library
        # Segundo evaluate: _discover_apis
        mock_page.evaluate.side_effect = [
            {
                "library": "shaka-player",
                "version": "4.3.0",
                "player_instance": "video.__shaka_player",
                "globals_found": ["window.shaka"],
            },
            [
                {
                    "path": "shakaPlayer.play",
                    "method": "play",
                    "source": "shaka-player-instance",
                    "type": "method",
                },
                {
                    "path": "shakaPlayer.pause",
                    "method": "pause",
                    "source": "shaka-player-instance",
                    "type": "method",
                },
            ],
        ]
        result = await analyzer.analyze(mock_page)

        # Deve ter evidência da biblioteca + APIs
        assert len(result) >= 1
        # Primeira evidência é a biblioteca
        lib_evidence = result[0]
        assert lib_evidence.capability_hint == "player_library"
        assert lib_evidence.details["library"] == "shaka-player"
        assert lib_evidence.details["version"] == "4.3.0"

    @pytest.mark.asyncio
    async def test_analyze_detects_videojs(
        self, analyzer, mock_page
    ):
        """Detecta video.js via objeto global."""
        mock_page.evaluate.side_effect = [
            {
                "library": "video.js",
                "version": "8.0.0",
                "player_instance": None,
                "globals_found": ["window.videojs"],
            },
            [],
        ]
        result = await analyzer.analyze(mock_page)

        assert len(result) >= 1
        lib_evidence = result[0]
        assert lib_evidence.details["library"] == "video.js"
        assert lib_evidence.details["version"] == "8.0.0"

    @pytest.mark.asyncio
    async def test_analyze_detects_hlsjs(
        self, analyzer, mock_page
    ):
        """Detecta hls.js via objeto global."""
        mock_page.evaluate.side_effect = [
            {
                "library": "hls.js",
                "version": "1.4.0",
                "player_instance": None,
                "globals_found": ["window.Hls"],
            },
            [],
        ]
        result = await analyzer.analyze(mock_page)

        assert len(result) >= 1
        assert result[0].details["library"] == "hls.js"

    @pytest.mark.asyncio
    async def test_analyze_no_library_detected(
        self, analyzer, mock_page
    ):
        """Quando nenhuma biblioteca é detectada, retorna
        apenas evidências de APIs."""
        mock_page.evaluate.side_effect = [
            {
                "library": None,
                "version": None,
                "player_instance": None,
                "globals_found": [],
            },
            [
                {
                    "path": "video.play",
                    "method": "play",
                    "source": "HTMLMediaElement",
                    "type": "method",
                },
            ],
        ]
        result = await analyzer.analyze(mock_page)

        # Sem evidência de biblioteca, apenas APIs
        assert len(result) == 1
        assert result[0].capability_hint == "play"

    @pytest.mark.asyncio
    async def test_analyze_maps_apis_to_capabilities(
        self, analyzer, mock_page
    ):
        """APIs são mapeadas corretamente para capabilities."""
        mock_page.evaluate.side_effect = [
            {
                "library": None,
                "version": None,
                "player_instance": None,
                "globals_found": [],
            },
            [
                {
                    "path": "shakaPlayer.getAudioTracks",
                    "method": "getAudioTracks",
                    "source": "shaka-player-instance",
                    "type": "method",
                },
                {
                    "path": "shakaPlayer.getTextTracks",
                    "method": "getTextTracks",
                    "source": "shaka-player-instance",
                    "type": "method",
                },
                {
                    "path": "shakaPlayer.getVariantTracks",
                    "method": "getVariantTracks",
                    "source": "shaka-player-instance",
                    "type": "method",
                },
            ],
        ]
        result = await analyzer.analyze(mock_page)

        assert len(result) == 3
        hints = {e.capability_hint for e in result}
        assert "audio_selection" in hints
        assert "subtitle_selection" in hints
        assert "quality_selection" in hints

    @pytest.mark.asyncio
    async def test_analyze_ignores_unmapped_methods(
        self, analyzer, mock_page
    ):
        """Métodos sem mapeamento de capability são ignorados."""
        mock_page.evaluate.side_effect = [
            {
                "library": None,
                "version": None,
                "player_instance": None,
                "globals_found": [],
            },
            [
                {
                    "path": "player.unknownMethod",
                    "method": "unknownMethod",
                    "source": "window.player",
                    "type": "method",
                },
                {
                    "path": "player.customInternal",
                    "method": "customInternal",
                    "source": "window.player",
                    "type": "method",
                },
            ],
        ]
        result = await analyzer.analyze(mock_page)

        # Métodos sem mapeamento não geram evidências
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_analyze_handles_page_evaluate_error(
        self, analyzer, mock_page
    ):
        """Erro no page.evaluate() retorna lista vazia."""
        mock_page.evaluate.side_effect = Exception(
            "Page crashed"
        )
        result = await analyzer.analyze(mock_page)
        assert result == []

    @pytest.mark.asyncio
    async def test_analyze_handles_partial_error(
        self, analyzer, mock_page
    ):
        """Erro na segunda chamada evaluate() retorna
        evidências parciais."""
        mock_page.evaluate.side_effect = [
            {
                "library": "shaka-player",
                "version": "4.0.0",
                "player_instance": None,
                "globals_found": ["window.shaka"],
            },
            Exception("API discovery failed"),
        ]
        result = await analyzer.analyze(mock_page)

        # Deve ter pelo menos a evidência da biblioteca
        assert len(result) >= 1
        assert result[0].details["library"] == "shaka-player"


class TestJSAnalyzerConfidence:
    """Testes para o cálculo de confidence_contribution."""

    @pytest.mark.asyncio
    async def test_shaka_instance_high_confidence(
        self, analyzer, mock_page
    ):
        """APIs de instância shaka-player têm alta confidence."""
        mock_page.evaluate.side_effect = [
            {
                "library": None,
                "version": None,
                "player_instance": None,
                "globals_found": [],
            },
            [
                {
                    "path": "shakaPlayer.play",
                    "method": "play",
                    "source": "shaka-player-instance",
                    "type": "method",
                },
            ],
        ]
        result = await analyzer.analyze(mock_page)
        assert len(result) == 1
        assert result[0].confidence_contribution == 0.4

    @pytest.mark.asyncio
    async def test_window_player_medium_confidence(
        self, analyzer, mock_page
    ):
        """APIs de window.player têm confidence média."""
        mock_page.evaluate.side_effect = [
            {
                "library": None,
                "version": None,
                "player_instance": None,
                "globals_found": [],
            },
            [
                {
                    "path": "window.player.play",
                    "method": "play",
                    "source": "window.player",
                    "type": "method",
                },
            ],
        ]
        result = await analyzer.analyze(mock_page)
        assert len(result) == 1
        assert result[0].confidence_contribution == 0.3

    @pytest.mark.asyncio
    async def test_html_media_element_control_confidence(
        self, analyzer, mock_page
    ):
        """APIs de controle do HTMLMediaElement têm confidence
        0.25."""
        mock_page.evaluate.side_effect = [
            {
                "library": None,
                "version": None,
                "player_instance": None,
                "globals_found": [],
            },
            [
                {
                    "path": "video.play",
                    "method": "play",
                    "source": "HTMLMediaElement",
                    "type": "method",
                },
            ],
        ]
        result = await analyzer.analyze(mock_page)
        assert len(result) == 1
        assert result[0].confidence_contribution == 0.25

    @pytest.mark.asyncio
    async def test_library_detection_confidence(
        self, analyzer, mock_page
    ):
        """Detecção de biblioteca contribui com 0.3."""
        mock_page.evaluate.side_effect = [
            {
                "library": "dashjs",
                "version": "4.5.0",
                "player_instance": None,
                "globals_found": ["window.dashjs"],
            },
            [],
        ]
        result = await analyzer.analyze(mock_page)
        assert len(result) == 1
        assert result[0].confidence_contribution == 0.3


class TestJSAnalyzerInteractionLevel:
    """Testes para o nível de interação."""

    @pytest.mark.asyncio
    async def test_all_evidences_are_player_api(
        self, analyzer, mock_page
    ):
        """Todas as evidências JS devem ter interaction_hint
        PLAYER_API."""
        mock_page.evaluate.side_effect = [
            {
                "library": "shaka-player",
                "version": "4.0.0",
                "player_instance": "video.__shaka_player",
                "globals_found": ["window.shaka"],
            },
            [
                {
                    "path": "shakaPlayer.play",
                    "method": "play",
                    "source": "shaka-player-instance",
                    "type": "method",
                },
                {
                    "path": "shakaPlayer.getTextTracks",
                    "method": "getTextTracks",
                    "source": "shaka-player-instance",
                    "type": "method",
                },
            ],
        ]
        result = await analyzer.analyze(mock_page)

        for evidence in result:
            assert (
                evidence.interaction_hint
                == InteractionLevel.PLAYER_API
            )


class TestJSEvidenceDataclass:
    """Testes para a dataclass JSEvidence."""

    def test_create_evidence(self):
        """Cria JSEvidence com todos os campos."""
        evidence = JSEvidence(
            api_path="window.player.play",
            capability_hint="play",
            confidence_contribution=0.4,
            details={"library": "shaka-player", "version": "4.0"},
            interaction_hint=InteractionLevel.PLAYER_API,
        )
        assert evidence.api_path == "window.player.play"
        assert evidence.capability_hint == "play"
        assert evidence.confidence_contribution == 0.4
        assert evidence.details["library"] == "shaka-player"
        assert (
            evidence.interaction_hint
            == InteractionLevel.PLAYER_API
        )

    def test_create_evidence_defaults(self):
        """Cria JSEvidence com defaults."""
        evidence = JSEvidence(
            api_path="test.method",
            capability_hint="play",
            confidence_contribution=0.3,
        )
        assert evidence.details == {}
        assert (
            evidence.interaction_hint
            == InteractionLevel.PLAYER_API
        )


class TestCapabilityApiMap:
    """Testes para o mapeamento CAPABILITY_API_MAP."""

    def test_all_required_capabilities_have_apis(self):
        """Todas as capabilities obrigatórias têm pelo menos
        uma API mapeada."""
        required = [
            "play", "pause", "mute",
            "audio_selection", "subtitle_selection",
            "quality_selection", "fullscreen", "settings",
        ]
        mapped_caps = set(CAPABILITY_API_MAP.values())
        for cap in required:
            assert cap in mapped_caps, (
                f"Capability '{cap}' sem API mapeada"
            )

    def test_play_methods_mapped(self):
        """Métodos de play estão mapeados corretamente."""
        assert CAPABILITY_API_MAP["play"] == "play"

    def test_audio_methods_mapped(self):
        """Métodos de áudio estão mapeados corretamente."""
        assert (
            CAPABILITY_API_MAP["getAudioTracks"]
            == "audio_selection"
        )
        assert (
            CAPABILITY_API_MAP["selectAudioLanguage"]
            == "audio_selection"
        )

    def test_subtitle_methods_mapped(self):
        """Métodos de legenda estão mapeados corretamente."""
        assert (
            CAPABILITY_API_MAP["getTextTracks"]
            == "subtitle_selection"
        )
        assert (
            CAPABILITY_API_MAP["setTextTrackVisibility"]
            == "subtitle_selection"
        )

    def test_quality_methods_mapped(self):
        """Métodos de qualidade estão mapeados corretamente."""
        assert (
            CAPABILITY_API_MAP["getVariantTracks"]
            == "quality_selection"
        )


class TestKnownPlayerGlobals:
    """Testes para o dicionário KNOWN_PLAYER_GLOBALS."""

    def test_shaka_globals(self):
        """Globais do shaka-player estão registrados."""
        assert (
            KNOWN_PLAYER_GLOBALS["window.shaka"]
            == "shaka-player"
        )
        assert (
            KNOWN_PLAYER_GLOBALS["window.shaka.Player"]
            == "shaka-player"
        )

    def test_videojs_globals(self):
        """Globais do video.js estão registrados."""
        assert (
            KNOWN_PLAYER_GLOBALS["window.videojs"]
            == "video.js"
        )

    def test_hlsjs_globals(self):
        """Globais do hls.js estão registrados."""
        assert KNOWN_PLAYER_GLOBALS["window.Hls"] == "hls.js"

    def test_dashjs_globals(self):
        """Globais do dashjs estão registrados."""
        assert (
            KNOWN_PLAYER_GLOBALS["window.dashjs"] == "dashjs"
        )
