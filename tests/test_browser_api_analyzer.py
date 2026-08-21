"""Testes unitários para o BrowserAPIAnalyzer.

Testa a análise de Browser APIs usando mocks do Playwright Page.
"""

import pytest
from unittest.mock import AsyncMock

from src.player_discovery.discovery.browser_api_analyzer import (
    BrowserAPIAnalyzer,
    BrowserAPIEvidence,
)


@pytest.fixture
def analyzer():
    """Instância do BrowserAPIAnalyzer."""
    return BrowserAPIAnalyzer()


@pytest.fixture
def mock_page():
    """Mock do Playwright Page com evaluate."""
    page = AsyncMock()
    return page


@pytest.fixture
def full_api_results():
    """Resultados completos de todas as APIs disponíveis."""
    return [
        {
            "api_name": "HTMLMediaElement",
            "available": True,
            "capability_hint": "video_playback",
            "details": {
                "video_count": 1,
                "has_src": True,
                "current_src": "https://example.com/video.m3u8",
                "ready_state": 4,
                "paused": False,
            },
        },
        {
            "api_name": "TextTrackList",
            "available": True,
            "capability_hint": "subtitle_selection",
            "details": {
                "track_count": 2,
                "tracks": [
                    {
                        "kind": "subtitles",
                        "language": "pt",
                        "label": "Português",
                        "mode": "showing",
                    },
                    {
                        "kind": "subtitles",
                        "language": "en",
                        "label": "English",
                        "mode": "hidden",
                    },
                ],
            },
        },
        {
            "api_name": "AudioTrackList",
            "available": True,
            "capability_hint": "audio_selection",
            "details": {
                "track_count": 2,
                "tracks": [
                    {
                        "id": "1",
                        "language": "pt",
                        "label": "Português",
                        "enabled": True,
                    },
                    {
                        "id": "2",
                        "language": "en",
                        "label": "English",
                        "enabled": False,
                    },
                ],
            },
        },
        {
            "api_name": "MediaCapabilities",
            "available": True,
            "capability_hint": "quality_selection",
            "details": {
                "has_decoding_info": True,
                "has_encoding_info": True,
            },
        },
        {
            "api_name": "MediaSession",
            "available": True,
            "capability_hint": "play",
            "details": {
                "playback_state": "playing",
                "has_metadata": True,
            },
        },
        {
            "api_name": "PerformanceAPI",
            "available": True,
            "capability_hint": "video_playback",
            "details": {
                "media_entries_count": 3,
                "media_entries": [
                    {
                        "name": "segment_001.ts",
                        "duration": 150.5,
                        "transfer_size": 524288,
                    }
                ],
            },
        },
        {
            "api_name": "VideoPlaybackQuality",
            "available": True,
            "capability_hint": "video_playback",
            "details": {
                "total_frames": 1500,
                "dropped_frames": 3,
                "corrupted_frames": 0,
                "creation_time": 1000.5,
            },
        },
    ]


@pytest.mark.asyncio
async def test_analyze_retorna_todas_apis(
    analyzer, mock_page, full_api_results
):
    """Deve retornar evidência para todas as 7 APIs verificadas."""
    mock_page.evaluate.return_value = full_api_results

    result = await analyzer.analyze(mock_page)

    assert len(result) == 7
    api_names = [e.api_name for e in result]
    assert "HTMLMediaElement" in api_names
    assert "TextTrackList" in api_names
    assert "AudioTrackList" in api_names
    assert "MediaCapabilities" in api_names
    assert "MediaSession" in api_names
    assert "PerformanceAPI" in api_names
    assert "VideoPlaybackQuality" in api_names


@pytest.mark.asyncio
async def test_analyze_apis_disponiveis_tem_confidence_positiva(
    analyzer, mock_page, full_api_results
):
    """APIs disponíveis devem ter confidence_contribution > 0."""
    mock_page.evaluate.return_value = full_api_results

    result = await analyzer.analyze(mock_page)

    for evidence in result:
        assert evidence.available is True
        assert evidence.confidence_contribution > 0.0


@pytest.mark.asyncio
async def test_analyze_api_indisponivel_tem_confidence_zero(
    analyzer, mock_page
):
    """APIs indisponíveis devem ter confidence_contribution = 0."""
    mock_page.evaluate.return_value = [
        {
            "api_name": "AudioTrackList",
            "available": False,
            "capability_hint": "audio_selection",
            "details": {"track_count": 0, "tracks": []},
        }
    ]

    result = await analyzer.analyze(mock_page)

    assert len(result) == 1
    assert result[0].available is False
    assert result[0].confidence_contribution == 0.0


@pytest.mark.asyncio
async def test_analyze_htmlmediaelement_com_src_aumenta_confidence(
    analyzer, mock_page
):
    """HTMLMediaElement com src/currentSrc deve ter confidence maior."""
    results_com_src = [
        {
            "api_name": "HTMLMediaElement",
            "available": True,
            "capability_hint": "video_playback",
            "details": {
                "video_count": 1,
                "has_src": True,
                "current_src": "https://example.com/video.m3u8",
                "ready_state": 4,
                "paused": False,
            },
        }
    ]
    results_sem_src = [
        {
            "api_name": "HTMLMediaElement",
            "available": True,
            "capability_hint": "video_playback",
            "details": {
                "video_count": 1,
                "has_src": False,
                "current_src": None,
                "ready_state": 0,
                "paused": True,
            },
        }
    ]

    mock_page.evaluate.return_value = results_com_src
    result_com = await analyzer.analyze(mock_page)

    mock_page.evaluate.return_value = results_sem_src
    result_sem = await analyzer.analyze(mock_page)

    assert (
        result_com[0].confidence_contribution
        > result_sem[0].confidence_contribution
    )


@pytest.mark.asyncio
async def test_analyze_fallback_quando_evaluate_falha(
    analyzer, mock_page
):
    """Quando page.evaluate falha, deve retornar fallback."""
    mock_page.evaluate.side_effect = Exception(
        "Execution context destroyed"
    )

    result = await analyzer.analyze(mock_page)

    assert len(result) == 7
    for evidence in result:
        assert evidence.available is False
        assert evidence.confidence_contribution == 0.0
        assert "error" in evidence.details


@pytest.mark.asyncio
async def test_analyze_confidence_bounded(
    analyzer, mock_page, full_api_results
):
    """Confidence nunca deve exceder 1.0 ou ser negativa."""
    mock_page.evaluate.return_value = full_api_results

    result = await analyzer.analyze(mock_page)

    for evidence in result:
        assert 0.0 <= evidence.confidence_contribution <= 1.0


@pytest.mark.asyncio
async def test_analyze_capability_hints_corretos(
    analyzer, mock_page, full_api_results
):
    """Capability hints devem corresponder à API verificada."""
    mock_page.evaluate.return_value = full_api_results

    result = await analyzer.analyze(mock_page)

    hints_map = {e.api_name: e.capability_hint for e in result}
    assert hints_map["HTMLMediaElement"] == "video_playback"
    assert hints_map["TextTrackList"] == "subtitle_selection"
    assert hints_map["AudioTrackList"] == "audio_selection"
    assert hints_map["MediaCapabilities"] == "quality_selection"
    assert hints_map["MediaSession"] == "play"
    assert hints_map["PerformanceAPI"] == "video_playback"
    assert hints_map["VideoPlaybackQuality"] == "video_playback"


@pytest.mark.asyncio
async def test_analyze_text_tracks_com_tracks_aumenta_confidence(
    analyzer, mock_page
):
    """TextTrackList com tracks > 0 deve ter confidence maior."""
    results_com_tracks = [
        {
            "api_name": "TextTrackList",
            "available": True,
            "capability_hint": "subtitle_selection",
            "details": {
                "track_count": 2,
                "tracks": [
                    {"kind": "subtitles", "language": "pt",
                     "label": "PT", "mode": "showing"}
                ],
            },
        }
    ]
    results_sem_tracks = [
        {
            "api_name": "TextTrackList",
            "available": True,
            "capability_hint": "subtitle_selection",
            "details": {"track_count": 0, "tracks": []},
        }
    ]

    mock_page.evaluate.return_value = results_com_tracks
    result_com = await analyzer.analyze(mock_page)

    mock_page.evaluate.return_value = results_sem_tracks
    result_sem = await analyzer.analyze(mock_page)

    assert (
        result_com[0].confidence_contribution
        > result_sem[0].confidence_contribution
    )


@pytest.mark.asyncio
async def test_analyze_retorna_browser_api_evidence_dataclass(
    analyzer, mock_page, full_api_results
):
    """Resultado deve ser uma lista de BrowserAPIEvidence."""
    mock_page.evaluate.return_value = full_api_results

    result = await analyzer.analyze(mock_page)

    for evidence in result:
        assert isinstance(evidence, BrowserAPIEvidence)
        assert isinstance(evidence.api_name, str)
        assert isinstance(evidence.available, bool)
        assert isinstance(evidence.capability_hint, str)
        assert isinstance(evidence.confidence_contribution, float)
        assert isinstance(evidence.details, dict)
