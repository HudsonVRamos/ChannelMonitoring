"""Testes unitários do SubtitleProbe.

Testa a coleta de telemetria de legendas via TextTrack API e
o teste funcional de seleção de legendas.

Requirements testados: 7.1, 7.2, 7.3, 7.4, 7.5
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.player_discovery.models.capability import (
    Capability,
    CapabilityMapData,
    InteractionStrategy,
    PlayerInfo,
)
from src.player_discovery.models.capability_map import CapabilityMap
from src.player_discovery.models.enums import (
    FunctionalTestStatus,
    InteractionLevel,
)
from src.player_discovery.probes.subtitle_probe import SubtitleProbe


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def probe():
    """Instância limpa do SubtitleProbe."""
    return SubtitleProbe()


@pytest.fixture
def mock_page():
    """Mock de Page do Playwright."""
    page = AsyncMock()
    page.evaluate = AsyncMock()
    return page


@pytest.fixture
def capability_map_with_subtitle():
    """CapabilityMap com subtitle_selection disponível."""
    caps = {
        "subtitle_selection": Capability(
            name="subtitle_selection",
            available=True,
            confidence=0.9,
            evidence=["TextTrack API disponível"],
            interaction_strategy=InteractionLevel.PLAYER_API,
            strategies=[
                InteractionStrategy(
                    level=InteractionLevel.PLAYER_API,
                    type="player_api",
                    details={"method": "textTracks[0].mode='showing'"},
                ),
            ],
        ),
    }
    data = CapabilityMapData(
        player_info=PlayerInfo(
            library="shaka-player",
            version="4.0",
            video_elements=["video"],
        ),
        capabilities=caps,
        valid=True,
    )
    return CapabilityMap(data)


@pytest.fixture
def capability_map_without_subtitle():
    """CapabilityMap sem subtitle_selection."""
    caps = {
        "play": Capability(
            name="play",
            available=True,
            confidence=0.9,
            evidence=["API disponível"],
            interaction_strategy=InteractionLevel.PLAYER_API,
            strategies=[],
        ),
    }
    data = CapabilityMapData(
        player_info=PlayerInfo(),
        capabilities=caps,
        valid=True,
    )
    return CapabilityMap(data)


@pytest.fixture
def subtitle_data_with_tracks():
    """Dados de retorno do JS com tracks disponíveis."""
    return {
        "tracks_available": 2,
        "tracks": [
            {
                "language": "pt",
                "label": "Português",
                "kind": "subtitles",
                "mode": "disabled",
            },
            {
                "language": "en",
                "label": "English",
                "kind": "subtitles",
                "mode": "showing",
            },
        ],
        "active_track": "English",
        "has_active_cues": True,
    }


@pytest.fixture
def subtitle_data_no_tracks():
    """Dados de retorno do JS sem tracks."""
    return {
        "tracks_available": 0,
        "tracks": [],
        "active_track": None,
        "has_active_cues": False,
    }


# ============================================================
# Testes de collect() — Requirement 7.1, 7.2, 7.5
# ============================================================


class TestCollect:
    """Testes da coleta de telemetria de legendas."""

    @pytest.mark.asyncio
    async def test_collect_with_tracks_returns_ok(
        self, probe, mock_page, capability_map_with_subtitle,
        subtitle_data_with_tracks,
    ):
        """Coleta com tracks disponíveis retorna status OK."""
        mock_page.evaluate.return_value = subtitle_data_with_tracks

        result = await probe.collect(
            mock_page, capability_map_with_subtitle
        )

        assert result.status == "OK"
        assert result.tracks_available == 2
        assert len(result.tracks) == 2
        assert result.active_track == "English"
        assert result.has_active_cues is True

    @pytest.mark.asyncio
    async def test_collect_tracks_contain_required_fields(
        self, probe, mock_page, capability_map_with_subtitle,
        subtitle_data_with_tracks,
    ):
        """Cada track contém language, label, kind, mode."""
        mock_page.evaluate.return_value = subtitle_data_with_tracks

        result = await probe.collect(
            mock_page, capability_map_with_subtitle
        )

        for track in result.tracks:
            assert "language" in track
            assert "label" in track
            assert "kind" in track
            assert "mode" in track

    @pytest.mark.asyncio
    async def test_collect_no_tracks_returns_unavailable(
        self, probe, mock_page, capability_map_with_subtitle,
        subtitle_data_no_tracks,
    ):
        """Sem tracks retorna SUBTITLE_UNAVAILABLE (Req 7.5)."""
        mock_page.evaluate.return_value = subtitle_data_no_tracks

        result = await probe.collect(
            mock_page, capability_map_with_subtitle
        )

        assert result.status == "SUBTITLE_UNAVAILABLE"
        assert result.tracks_available == 0
        assert result.tracks == []
        assert result.active_track is None
        assert result.has_active_cues is False

    @pytest.mark.asyncio
    async def test_collect_null_result_returns_unavailable(
        self, probe, mock_page, capability_map_with_subtitle,
    ):
        """Resultado null do JS retorna SUBTITLE_UNAVAILABLE."""
        mock_page.evaluate.return_value = None

        result = await probe.collect(
            mock_page, capability_map_with_subtitle
        )

        assert result.status == "SUBTITLE_UNAVAILABLE"
        assert result.tracks_available == 0

    @pytest.mark.asyncio
    async def test_collect_exception_returns_unavailable(
        self, probe, mock_page, capability_map_with_subtitle,
    ):
        """Exceção no page.evaluate retorna SUBTITLE_UNAVAILABLE."""
        mock_page.evaluate.side_effect = Exception("Page crashed")

        result = await probe.collect(
            mock_page, capability_map_with_subtitle
        )

        assert result.status == "SUBTITLE_UNAVAILABLE"
        assert result.tracks_available == 0

    @pytest.mark.asyncio
    async def test_collect_with_showing_track_detects_active(
        self, probe, mock_page, capability_map_with_subtitle,
    ):
        """Track com mode=showing é detectada como ativa."""
        mock_page.evaluate.return_value = {
            "tracks_available": 1,
            "tracks": [
                {
                    "language": "pt",
                    "label": "Português",
                    "kind": "subtitles",
                    "mode": "showing",
                },
            ],
            "active_track": "Português",
            "has_active_cues": False,
        }

        result = await probe.collect(
            mock_page, capability_map_with_subtitle
        )

        assert result.active_track == "Português"

    @pytest.mark.asyncio
    async def test_collect_stores_last_telemetry(
        self, probe, mock_page, capability_map_with_subtitle,
        subtitle_data_with_tracks,
    ):
        """A última telemetria coletada é armazenada."""
        mock_page.evaluate.return_value = subtitle_data_with_tracks

        result = await probe.collect(
            mock_page, capability_map_with_subtitle
        )

        assert probe._last_telemetry is result


# ============================================================
# Testes de run_functional_test() — Requirement 7.3, 7.4, 7.5
# ============================================================


class TestRunFunctionalTest:
    """Testes do teste funcional de seleção de legenda."""

    @pytest.mark.asyncio
    async def test_skipped_when_no_tracks(
        self, probe, mock_page, capability_map_with_subtitle,
    ):
        """Retorna SKIPPED quando nenhuma track disponível (Req 7.5)."""
        mock_page.evaluate.return_value = {
            "tracks_available": 0,
            "tracks": [],
            "active_track": None,
            "has_active_cues": False,
        }

        result = await probe.run_functional_test(
            mock_page, capability_map_with_subtitle
        )

        assert result.status == FunctionalTestStatus.SKIPPED
        assert result.capability == "subtitle_selection"
        assert "SUBTITLE_UNAVAILABLE" in result.error

    @pytest.mark.asyncio
    async def test_skipped_when_capability_not_in_map(
        self, probe, mock_page, capability_map_without_subtitle,
    ):
        """Retorna SKIPPED se subtitle_selection não está no mapa."""
        # Primeira chamada: collect (retorna tracks)
        mock_page.evaluate.return_value = {
            "tracks_available": 1,
            "tracks": [
                {
                    "language": "pt",
                    "label": "Português",
                    "kind": "subtitles",
                    "mode": "disabled",
                },
            ],
            "active_track": None,
            "has_active_cues": False,
        }

        result = await probe.run_functional_test(
            mock_page, capability_map_without_subtitle
        )

        assert result.status == FunctionalTestStatus.SKIPPED
        assert "não disponível" in result.error

    @pytest.mark.asyncio
    async def test_pass_when_selection_and_cue_detected(
        self, probe, mock_page, capability_map_with_subtitle,
    ):
        """PASS quando seleção funciona e cue é detectada (Req 7.4)."""
        # Sequência de chamadas evaluate:
        # 1. collect: retorna tracks
        # 2. select track: sucesso
        # 3. check cues: encontra cue
        mock_page.evaluate.side_effect = [
            # collect
            {
                "tracks_available": 1,
                "tracks": [
                    {
                        "language": "pt",
                        "label": "Português",
                        "kind": "subtitles",
                        "mode": "disabled",
                    },
                ],
                "active_track": None,
                "has_active_cues": False,
            },
            # select track
            {
                "success": True,
                "mode": "showing",
                "label": "Português",
                "language": "pt",
            },
            # check active cues (primeira verificação)
            {"has_cues": True, "cue_count": 1},
        ]

        result = await probe.run_functional_test(
            mock_page, capability_map_with_subtitle
        )

        assert result.status == FunctionalTestStatus.PASS
        assert result.capability == "subtitle_selection"
        assert result.duration_ms >= 0

    @pytest.mark.asyncio
    async def test_fail_when_select_returns_error(
        self, probe, mock_page, capability_map_with_subtitle,
    ):
        """FAIL quando seleção retorna erro."""
        mock_page.evaluate.side_effect = [
            # collect
            {
                "tracks_available": 1,
                "tracks": [
                    {
                        "language": "pt",
                        "label": "Português",
                        "kind": "subtitles",
                        "mode": "disabled",
                    },
                ],
                "active_track": None,
                "has_active_cues": False,
            },
            # select track: falha
            {"success": False, "error": "índice de track inválido"},
        ]

        result = await probe.run_functional_test(
            mock_page, capability_map_with_subtitle
        )

        assert result.status == FunctionalTestStatus.FAIL
        assert "índice de track inválido" in result.error

    @pytest.mark.asyncio
    async def test_fail_when_select_throws_exception(
        self, probe, mock_page, capability_map_with_subtitle,
    ):
        """FAIL quando seleção lança exceção."""
        mock_page.evaluate.side_effect = [
            # collect
            {
                "tracks_available": 1,
                "tracks": [
                    {
                        "language": "pt",
                        "label": "Português",
                        "kind": "subtitles",
                        "mode": "disabled",
                    },
                ],
                "active_track": None,
                "has_active_cues": False,
            },
            # select track: exceção
            Exception("Page navigation"),
        ]

        result = await probe.run_functional_test(
            mock_page, capability_map_with_subtitle
        )

        assert result.status == FunctionalTestStatus.FAIL
        assert "Page navigation" in result.error

    @pytest.mark.asyncio
    async def test_fail_when_mode_not_showing(
        self, probe, mock_page, capability_map_with_subtitle,
    ):
        """FAIL quando mode não é 'showing' após seleção."""
        mock_page.evaluate.side_effect = [
            # collect
            {
                "tracks_available": 1,
                "tracks": [
                    {
                        "language": "pt",
                        "label": "Português",
                        "kind": "subtitles",
                        "mode": "disabled",
                    },
                ],
                "active_track": None,
                "has_active_cues": False,
            },
            # select track: sucesso mas mode errado
            {
                "success": True,
                "mode": "hidden",
                "label": "Português",
                "language": "pt",
            },
        ]

        result = await probe.run_functional_test(
            mock_page, capability_map_with_subtitle
        )

        assert result.status == FunctionalTestStatus.FAIL
        assert "mode=hidden" in result.actual_result

    @pytest.mark.asyncio
    async def test_fail_when_cue_timeout(
        self, probe, mock_page, capability_map_with_subtitle,
    ):
        """FAIL quando timeout esperando cue ativa (Req 7.4)."""
        mock_page.evaluate.side_effect = [
            # collect
            {
                "tracks_available": 1,
                "tracks": [
                    {
                        "language": "pt",
                        "label": "Português",
                        "kind": "subtitles",
                        "mode": "disabled",
                    },
                ],
                "active_track": None,
                "has_active_cues": False,
            },
            # select track: sucesso
            {
                "success": True,
                "mode": "showing",
                "label": "Português",
                "language": "pt",
            },
            # check cues: nunca encontra
            {"has_cues": False, "cue_count": 0},
            {"has_cues": False, "cue_count": 0},
            {"has_cues": False, "cue_count": 0},
        ]

        # Usar timeout curto para o teste não demorar
        with patch.object(
            probe, '_wait_for_active_cue',
            return_value=False,
        ):
            result = await probe.run_functional_test(
                mock_page, capability_map_with_subtitle
            )

        assert result.status == FunctionalTestStatus.FAIL
        assert "timeout" in result.error

    @pytest.mark.asyncio
    async def test_functional_test_has_duration(
        self, probe, mock_page, capability_map_with_subtitle,
    ):
        """Resultado sempre inclui duration_ms >= 0."""
        mock_page.evaluate.return_value = {
            "tracks_available": 0,
            "tracks": [],
            "active_track": None,
            "has_active_cues": False,
        }

        result = await probe.run_functional_test(
            mock_page, capability_map_with_subtitle
        )

        assert result.duration_ms >= 0


# ============================================================
# Testes de _wait_for_active_cue
# ============================================================


class TestWaitForActiveCue:
    """Testes do aguardo de cue ativa."""

    @pytest.mark.asyncio
    async def test_returns_true_when_cue_found_immediately(
        self, probe, mock_page,
    ):
        """Retorna True se cue encontrada na primeira verificação."""
        mock_page.evaluate.return_value = {
            "has_cues": True, "cue_count": 2
        }

        result = await probe._wait_for_active_cue(
            mock_page, timeout_seconds=1
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_on_timeout(
        self, probe, mock_page,
    ):
        """Retorna False quando timeout é atingido."""
        mock_page.evaluate.return_value = {
            "has_cues": False, "cue_count": 0
        }

        result = await probe._wait_for_active_cue(
            mock_page, timeout_seconds=1
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_handles_exception_gracefully(
        self, probe, mock_page,
    ):
        """Trata exceções sem falhar, espera timeout."""
        mock_page.evaluate.side_effect = Exception("disconnected")

        result = await probe._wait_for_active_cue(
            mock_page, timeout_seconds=1
        )

        assert result is False
