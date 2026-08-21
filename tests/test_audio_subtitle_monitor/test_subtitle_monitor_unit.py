"""Unit tests para SubtitleMonitor.

Testa cenários específicos e edge cases para:
- validate_track_switch: track encontrado/não encontrado
- wait_for_active_cue: cue encontrada rapidamente, timeout, truncamento, texto vazio
- get_active_tracks: retorno normal e erro de API

Requirements: 5.1, 5.2, 5.3, 5.4, 5.5
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from src.audio_subtitle_monitor.subtitle_monitor import SubtitleMonitor
from src.audio_subtitle_monitor.config import AudioSubtitleConfig


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def config():
    """Configuração padrão para testes do SubtitleMonitor."""
    return AudioSubtitleConfig(channels=[])


@pytest.fixture
def subtitle_monitor(config):
    """Instância do SubtitleMonitor com page mockado."""
    page = AsyncMock()
    page.evaluate = AsyncMock(return_value=None)
    return SubtitleMonitor(page=page, config=config)


# ============================================================
# Testes: validate_track_switch
# ============================================================


class TestValidateTrackSwitch:
    """Testes para o método validate_track_switch."""

    @pytest.mark.asyncio
    async def test_track_found(self, subtitle_monitor):
        """Track com idioma esperado está ativo → success=True.

        Req 5.2: Verificar via Shaka API que o track de legenda
        ativo mudou para o idioma selecionado.
        """
        subtitle_monitor.page.evaluate = AsyncMock(
            return_value=[
                {"language": "pt", "active": True, "label": "Português"},
                {"language": "en", "active": False, "label": "English"},
            ]
        )

        result = await subtitle_monitor.validate_track_switch(
            "pt", timeout_s=1.0
        )

        assert result.success is True
        assert result.actual_active_language == "pt"
        assert result.expected_language == "pt"
        assert result.error is None

    @pytest.mark.asyncio
    async def test_track_not_found(self, subtitle_monitor):
        """Track com idioma esperado NÃO está ativo → success=False.

        Req 5.6: Se a mudança não for confirmada dentro de 5s,
        classificar como FAIL com evidence "subtitle_switch_not_confirmed".
        """
        subtitle_monitor.page.evaluate = AsyncMock(
            return_value=[
                {"language": "pt", "active": True, "label": "Português"},
                {"language": "en", "active": False, "label": "English"},
            ]
        )

        result = await subtitle_monitor.validate_track_switch(
            "en", timeout_s=0.6
        )

        assert result.success is False
        assert result.actual_active_language == "pt"
        assert result.expected_language == "en"
        assert result.error == "subtitle_switch_not_confirmed"


# ============================================================
# Testes: wait_for_active_cue
# ============================================================


class TestWaitForActiveCue:
    """Testes para o método wait_for_active_cue."""

    @pytest.mark.asyncio
    async def test_cue_found_quickly(self, subtitle_monitor):
        """Cue ativa detectada na primeira tentativa → found=True.

        Req 5.3: Monitorar activeCues no TextTrack durante 15s
        aguardando pelo menos uma cue ativa.
        Req 5.4: Classificar como PASS com cue_text e time_to_first_cue_ms.
        """
        subtitle_monitor.page.evaluate = AsyncMock(
            return_value={"text": "Olá mundo", "trackLabel": "Português"}
        )

        result = await subtitle_monitor.wait_for_active_cue(
            timeout_s=0.5, poll_interval_s=0.1
        )

        assert result.found is True
        assert result.cue_text == "Olá mundo"
        assert result.time_to_first_cue_ms is not None
        assert result.time_to_first_cue_ms >= 0
        assert result.error is None

    @pytest.mark.asyncio
    async def test_timeout_no_cues(self, subtitle_monitor):
        """Nenhuma cue ativa detectada dentro do timeout → found=False.

        Req 5.5: Se nenhuma cue ativa for detectada dentro de 15s,
        classificar como TIMEOUT com evidence "no_active_cues_within_15s".
        """
        subtitle_monitor.page.evaluate = AsyncMock(return_value=None)

        result = await subtitle_monitor.wait_for_active_cue(
            timeout_s=0.5, poll_interval_s=0.1
        )

        assert result.found is False
        assert result.cue_text is None
        assert result.time_to_first_cue_ms is None
        assert result.error == "no_active_cues_within_15s"

    @pytest.mark.asyncio
    async def test_truncation_over_50_chars(self, subtitle_monitor):
        """Cue com texto > 50 caracteres → cue_text truncado a 50 chars.

        Req 5.4: Evidence contém cue_text com primeiros 50 caracteres.
        """
        long_text = "A" * 100  # 100 caracteres
        subtitle_monitor.page.evaluate = AsyncMock(
            return_value={"text": long_text, "trackLabel": "Português"}
        )

        result = await subtitle_monitor.wait_for_active_cue(
            timeout_s=0.5, poll_interval_s=0.1
        )

        assert result.found is True
        assert result.cue_text == "A" * 50
        assert len(result.cue_text) == 50

    @pytest.mark.asyncio
    async def test_empty_text(self, subtitle_monitor):
        """Cue com texto vazio → cue_text="" (string vazia).

        Edge case: cue ativa existe mas sem conteúdo textual.
        """
        subtitle_monitor.page.evaluate = AsyncMock(
            return_value={"text": "", "trackLabel": "Português"}
        )

        result = await subtitle_monitor.wait_for_active_cue(
            timeout_s=0.5, poll_interval_s=0.1
        )

        assert result.found is True
        assert result.cue_text == ""
        assert result.time_to_first_cue_ms is not None
        assert result.time_to_first_cue_ms >= 0

    @pytest.mark.asyncio
    async def test_all_disabled_tracks(self, subtitle_monitor):
        """Lista de legendas onde todas são "Desativadas".

        Req 5.1: O sistema deve iterar apenas por tracks que não sejam
        "Desativadas". Quando todas são desativadas, nenhuma cue será
        encontrada — simulado como page.evaluate retornando None sempre.
        """
        # Simula cenário onde nenhuma track está em modo "showing"
        subtitle_monitor.page.evaluate = AsyncMock(return_value=None)

        result = await subtitle_monitor.wait_for_active_cue(
            timeout_s=0.5, poll_interval_s=0.1
        )

        assert result.found is False
        assert result.error == "no_active_cues_within_15s"


# ============================================================
# Testes: get_active_tracks
# ============================================================


class TestGetActiveTracks:
    """Testes para o método get_active_tracks."""

    @pytest.mark.asyncio
    async def test_returns_list(self, subtitle_monitor):
        """page.evaluate retorna tracks → retorna lista de dicts.

        Verifica que get_active_tracks repassa corretamente os
        dados da Shaka API.
        """
        tracks = [
            {"language": "pt", "active": True, "label": "Português"},
            {"language": "en", "active": False, "label": "English"},
        ]
        subtitle_monitor.page.evaluate = AsyncMock(return_value=tracks)

        result = await subtitle_monitor.get_active_tracks()

        assert result == tracks
        assert len(result) == 2
        assert result[0]["language"] == "pt"
        assert result[0]["active"] is True

    @pytest.mark.asyncio
    async def test_api_error(self, subtitle_monitor):
        """page.evaluate lança exceção → retorna lista vazia.

        Garante resiliência quando a Shaka API não está disponível.
        """
        subtitle_monitor.page.evaluate = AsyncMock(
            side_effect=Exception("Shaka API indisponível")
        )

        result = await subtitle_monitor.get_active_tracks()

        assert result == []
