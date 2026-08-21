"""Testes unitários para o BehavioralTester.

Testa os testes comportamentais seguros usando mocks do Playwright Page.
Verifica que cada teste de capability segue o padrão:
observar estado → interação controlada → verificar mudança → restaurar.

Requirements: 1.6
"""

import pytest
from unittest.mock import AsyncMock

from src.player_discovery.discovery.behavioral_tester import (
    BehavioralTester,
    BehavioralTestResult,
    _CONFIDENCE_BOOSTS,
    _TEST_SCRIPTS,
)


@pytest.fixture
def tester():
    """Instância do BehavioralTester."""
    return BehavioralTester()


@pytest.fixture
def mock_page():
    """Mock do Playwright Page com evaluate."""
    page = AsyncMock()
    return page


# --- Testes de play/pause ---


@pytest.mark.asyncio
async def test_play_confirmado_retorna_boost(tester, mock_page):
    """Play confirmado deve retornar confidence_boost > 0."""
    mock_page.evaluate.return_value = {
        "confirmed": True,
        "observation": "play() via API mudou paused de true para false — restaurado",
    }

    result = await tester.test_capability(mock_page, "play")

    assert result.confirmed is True
    assert result.confidence_boost == _CONFIDENCE_BOOSTS["play"]
    assert result.capability == "play"
    assert result.duration_ms >= 0
    assert "play()" in result.observation


@pytest.mark.asyncio
async def test_pause_confirmado_retorna_boost(tester, mock_page):
    """Pause confirmado deve retornar confidence_boost > 0."""
    mock_page.evaluate.return_value = {
        "confirmed": True,
        "observation": "pause() via API mudou paused de false para true — restaurado",
    }

    result = await tester.test_capability(mock_page, "pause")

    assert result.confirmed is True
    assert result.confidence_boost == _CONFIDENCE_BOOSTS["pause"]
    assert result.capability == "pause"


@pytest.mark.asyncio
async def test_play_nao_confirmado_retorna_zero_boost(tester, mock_page):
    """Play não confirmado deve retornar confidence_boost = 0."""
    mock_page.evaluate.return_value = {
        "confirmed": False,
        "observation": "play() via API não alterou estado paused",
    }

    result = await tester.test_capability(mock_page, "play")

    assert result.confirmed is False
    assert result.confidence_boost == 0.0


# --- Testes de mute/unmute ---


@pytest.mark.asyncio
async def test_mute_confirmado(tester, mock_page):
    """Mute confirmado deve retornar resultado correto."""
    mock_page.evaluate.return_value = {
        "confirmed": True,
        "observation": "video.muted alterou de false para true — restaurado",
    }

    result = await tester.test_capability(mock_page, "mute")

    assert result.confirmed is True
    assert result.confidence_boost == _CONFIDENCE_BOOSTS["mute"]
    assert result.capability == "mute"


@pytest.mark.asyncio
async def test_unmute_confirmado(tester, mock_page):
    """Unmute confirmado deve retornar resultado correto."""
    mock_page.evaluate.return_value = {
        "confirmed": True,
        "observation": "video.muted alterou de true para false — restaurado",
    }

    result = await tester.test_capability(mock_page, "unmute")

    assert result.confirmed is True
    assert result.confidence_boost == _CONFIDENCE_BOOSTS["unmute"]


# --- Testes de fullscreen ---


@pytest.mark.asyncio
async def test_fullscreen_api_disponivel(tester, mock_page):
    """Fullscreen API disponível deve confirmar capability."""
    mock_page.evaluate.return_value = {
        "confirmed": True,
        "observation": "Fullscreen API disponível: requestFullscreen=true, "
        "exitFullscreen=true, enabled=true",
    }

    result = await tester.test_capability(mock_page, "fullscreen")

    assert result.confirmed is True
    assert result.confidence_boost == _CONFIDENCE_BOOSTS["fullscreen"]


@pytest.mark.asyncio
async def test_fullscreen_api_indisponivel(tester, mock_page):
    """Fullscreen API indisponível deve negar capability."""
    mock_page.evaluate.return_value = {
        "confirmed": False,
        "observation": "Fullscreen API parcialmente indisponível",
    }

    result = await tester.test_capability(mock_page, "fullscreen")

    assert result.confirmed is False
    assert result.confidence_boost == 0.0


# --- Testes de subtitle_selection ---


@pytest.mark.asyncio
async def test_subtitle_tracks_acessiveis(tester, mock_page):
    """textTracks acessíveis com tracks deve confirmar."""
    mock_page.evaluate.return_value = {
        "confirmed": True,
        "observation": 'textTracks acessíveis: 2 tracks encontradas — '
        '[{"kind":"subtitles","language":"pt"}]',
    }

    result = await tester.test_capability(
        mock_page, "subtitle_selection"
    )

    assert result.confirmed is True
    assert result.confidence_boost == _CONFIDENCE_BOOSTS["subtitle_selection"]


@pytest.mark.asyncio
async def test_subtitle_tracks_vazio(tester, mock_page):
    """textTracks acessível mas vazio não deve confirmar."""
    mock_page.evaluate.return_value = {
        "confirmed": False,
        "observation": "textTracks acessível mas vazio (0 tracks)",
    }

    result = await tester.test_capability(
        mock_page, "subtitle_selection"
    )

    assert result.confirmed is False
    assert result.confidence_boost == 0.0


# --- Testes de audio_selection ---


@pytest.mark.asyncio
async def test_audio_tracks_acessiveis(tester, mock_page):
    """audioTracks acessíveis com tracks deve confirmar."""
    mock_page.evaluate.return_value = {
        "confirmed": True,
        "observation": "audioTracks acessíveis: 2 tracks",
    }

    result = await tester.test_capability(
        mock_page, "audio_selection"
    )

    assert result.confirmed is True
    assert result.confidence_boost == _CONFIDENCE_BOOSTS["audio_selection"]


@pytest.mark.asyncio
async def test_audio_tracks_indisponiveis(tester, mock_page):
    """audioTracks indisponível não deve confirmar."""
    mock_page.evaluate.return_value = {
        "confirmed": False,
        "observation": "video.audioTracks não está definido",
    }

    result = await tester.test_capability(
        mock_page, "audio_selection"
    )

    assert result.confirmed is False
    assert result.confidence_boost == 0.0


# --- Testes de quality_selection ---


@pytest.mark.asyncio
async def test_quality_tracks_via_shaka(tester, mock_page):
    """Quality selection via Shaka Player deve confirmar."""
    mock_page.evaluate.return_value = {
        "confirmed": True,
        "observation": "Shaka Player: getVariantTracks() retornou 5 tracks",
    }

    result = await tester.test_capability(
        mock_page, "quality_selection"
    )

    assert result.confirmed is True
    assert result.confidence_boost == _CONFIDENCE_BOOSTS["quality_selection"]


@pytest.mark.asyncio
async def test_quality_nenhuma_api_detectada(tester, mock_page):
    """Sem API de quality detectada não deve confirmar."""
    mock_page.evaluate.return_value = {
        "confirmed": False,
        "observation": "Nenhuma API de quality/variant tracks detectada",
    }

    result = await tester.test_capability(
        mock_page, "quality_selection"
    )

    assert result.confirmed is False
    assert result.confidence_boost == 0.0


# --- Testes de settings ---


@pytest.mark.asyncio
async def test_settings_panel_detectado(tester, mock_page):
    """Painel de settings detectado deve confirmar."""
    mock_page.evaluate.return_value = {
        "confirmed": True,
        "observation": "Painel de settings detectado: 2 elementos",
    }

    result = await tester.test_capability(mock_page, "settings")

    assert result.confirmed is True
    assert result.confidence_boost == _CONFIDENCE_BOOSTS["settings"]


@pytest.mark.asyncio
async def test_settings_nao_detectado(tester, mock_page):
    """Settings não detectado não deve confirmar."""
    mock_page.evaluate.return_value = {
        "confirmed": False,
        "observation": "Nenhum painel de settings detectado via semântica DOM",
    }

    result = await tester.test_capability(mock_page, "settings")

    assert result.confirmed is False
    assert result.confidence_boost == 0.0


# --- Testes de erro e edge cases ---


@pytest.mark.asyncio
async def test_capability_desconhecida_retorna_nao_confirmado(
    tester, mock_page
):
    """Capability sem teste definido deve retornar não confirmado."""
    result = await tester.test_capability(
        mock_page, "capability_inventada"
    )

    assert result.confirmed is False
    assert result.confidence_boost == 0.0
    assert "Nenhum teste comportamental" in result.observation
    # page.evaluate não deve ser chamado
    mock_page.evaluate.assert_not_called()


@pytest.mark.asyncio
async def test_page_evaluate_exception_retorna_erro(
    tester, mock_page
):
    """Quando page.evaluate lança exceção, deve retornar erro."""
    mock_page.evaluate.side_effect = Exception(
        "Execution context destroyed"
    )

    result = await tester.test_capability(mock_page, "play")

    assert result.confirmed is False
    assert result.confidence_boost == 0.0
    assert "Erro na execução" in result.observation
    assert "Execution context destroyed" in result.observation


@pytest.mark.asyncio
async def test_resultado_sem_campo_confirmed_retorna_false(
    tester, mock_page
):
    """Resultado JS sem campo 'confirmed' deve retornar False."""
    mock_page.evaluate.return_value = {
        "observation": "algo observado"
    }

    result = await tester.test_capability(mock_page, "play")

    assert result.confirmed is False
    assert result.confidence_boost == 0.0


@pytest.mark.asyncio
async def test_resultado_sem_campo_observation(tester, mock_page):
    """Resultado JS sem campo 'observation' deve usar fallback."""
    mock_page.evaluate.return_value = {"confirmed": True}

    result = await tester.test_capability(mock_page, "play")

    assert result.confirmed is True
    assert result.observation == "Sem observação"


# --- Testes de test_all_capabilities ---


@pytest.mark.asyncio
async def test_all_capabilities_testa_todas(tester, mock_page):
    """test_all_capabilities deve testar todas as capabilities conhecidas."""
    mock_page.evaluate.return_value = {
        "confirmed": True,
        "observation": "teste ok",
    }

    results = await tester.test_all_capabilities(mock_page)

    # Deve ter uma entrada por capability única
    capabilities_testadas = {r.capability for r in results}
    assert "play" in capabilities_testadas
    assert "pause" in capabilities_testadas
    assert "mute" in capabilities_testadas
    assert "unmute" in capabilities_testadas
    assert "fullscreen" in capabilities_testadas
    assert "subtitle_selection" in capabilities_testadas
    assert "audio_selection" in capabilities_testadas
    assert "quality_selection" in capabilities_testadas
    assert "settings" in capabilities_testadas


@pytest.mark.asyncio
async def test_all_capabilities_subset(tester, mock_page):
    """test_all_capabilities com subset deve testar apenas as listadas."""
    mock_page.evaluate.return_value = {
        "confirmed": True,
        "observation": "teste ok",
    }

    results = await tester.test_all_capabilities(
        mock_page, capabilities=["play", "mute"]
    )

    assert len(results) == 2
    capabilities_testadas = [r.capability for r in results]
    assert "play" in capabilities_testadas
    assert "mute" in capabilities_testadas


@pytest.mark.asyncio
async def test_all_capabilities_remove_duplicados(tester, mock_page):
    """test_all_capabilities deve remover duplicados."""
    mock_page.evaluate.return_value = {
        "confirmed": True,
        "observation": "teste ok",
    }

    results = await tester.test_all_capabilities(
        mock_page, capabilities=["play", "play", "mute", "mute"]
    )

    assert len(results) == 2


# --- Testes de get_supported_capabilities ---


def test_get_supported_capabilities_retorna_lista():
    """get_supported_capabilities deve retornar lista não-vazia."""
    caps = BehavioralTester.get_supported_capabilities()

    assert isinstance(caps, list)
    assert len(caps) > 0
    assert "play" in caps
    assert "mute" in caps
    assert "fullscreen" in caps


# --- Testes de BehavioralTestResult ---


def test_behavioral_test_result_dataclass():
    """BehavioralTestResult deve ser criado corretamente."""
    result = BehavioralTestResult(
        capability="play",
        confirmed=True,
        confidence_boost=0.25,
        observation="teste ok",
        duration_ms=42,
    )

    assert result.capability == "play"
    assert result.confirmed is True
    assert result.confidence_boost == 0.25
    assert result.observation == "teste ok"
    assert result.duration_ms == 42


# --- Testes de confidence_boost bounded ---


@pytest.mark.asyncio
async def test_confidence_boost_bounded_zero_a_ponto_tres(
    tester, mock_page
):
    """Confidence boost deve estar entre 0.0 e 0.3."""
    mock_page.evaluate.return_value = {
        "confirmed": True,
        "observation": "ok",
    }

    for capability in _TEST_SCRIPTS.keys():
        result = await tester.test_capability(
            mock_page, capability
        )
        assert 0.0 <= result.confidence_boost <= 0.3, (
            f"confidence_boost para '{capability}' = "
            f"{result.confidence_boost} fora do range [0.0, 0.3]"
        )


@pytest.mark.asyncio
async def test_nao_confirmado_sempre_boost_zero(tester, mock_page):
    """Capabilities não confirmadas devem sempre ter boost = 0."""
    mock_page.evaluate.return_value = {
        "confirmed": False,
        "observation": "não confirmado",
    }

    for capability in _TEST_SCRIPTS.keys():
        result = await tester.test_capability(
            mock_page, capability
        )
        assert result.confidence_boost == 0.0


# --- Teste de evidence opcional ---


@pytest.mark.asyncio
async def test_evidence_parametro_opcional(tester, mock_page):
    """O parâmetro evidence deve ser opcional sem afetar o resultado."""
    mock_page.evaluate.return_value = {
        "confirmed": True,
        "observation": "ok",
    }

    result_sem = await tester.test_capability(mock_page, "play")
    result_com = await tester.test_capability(
        mock_page, "play", evidence=["aria-label='Play'"]
    )

    assert result_sem.confirmed == result_com.confirmed
    assert result_sem.confidence_boost == result_com.confidence_boost
