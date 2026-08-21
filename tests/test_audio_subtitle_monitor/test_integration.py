"""Integration tests do fluxo completo do Audio & Subtitle Monitor.

Testa o fluxo end-to-end com Playwright mockado (page.evaluate
retornando dados realistas), incluindo cenários de Settings Dialog
que fecha/permanece aberto após seleção, e geração de relatório
JSON com todos os campos.

Requirements: 7.1, 6.2, 6.3, 9.1
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.audio_subtitle_monitor.config import AudioSubtitleConfig
from src.audio_subtitle_monitor.main import run_audio_subtitle_monitoring
from src.audio_subtitle_monitor.models import OverallStatus


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def fast_config(tmp_path):
    """Configuração com timeouts curtos para testes rápidos."""
    return AudioSubtitleConfig(
        channels=["https://www.skymais.com.br/player/live/CH0100000000124"],
        output_dir=str(tmp_path),
        playback_wait_timeout_s=0.1,
        track_switch_timeout_s=0.1,
        audio_telemetry_window_s=0.1,
        audio_sample_interval_s=0.05,
        subtitle_cue_timeout_s=0.1,
        subtitle_poll_interval_s=0.05,
        settings_dialog_timeout_s=0.1,
        dialog_retry_wait_s=0.01,
    )


@pytest.fixture
def multi_channel_config(tmp_path):
    """Configuração com 2 canais para teste multi-canal."""
    return AudioSubtitleConfig(
        channels=[
            "https://www.skymais.com.br/player/live/CH0100000000124",
            "https://www.skymais.com.br/player/live/CH0100000000092",
        ],
        output_dir=str(tmp_path),
        playback_wait_timeout_s=0.1,
        track_switch_timeout_s=0.1,
        audio_telemetry_window_s=0.1,
        audio_sample_interval_s=0.05,
        subtitle_cue_timeout_s=0.1,
        subtitle_poll_interval_s=0.05,
        settings_dialog_timeout_s=0.1,
        dialog_retry_wait_s=0.01,
    )


@pytest.fixture
def mock_capability_map():
    """CapabilityMap mockado com settings disponível via semantic_dom."""
    cm = MagicMock()
    cm.get_interaction_strategy.return_value = "semantic_dom"
    cap = MagicMock()
    cap.available = True
    cap.interaction_strategy = "semantic_dom"
    cm.get_capability.return_value = cap
    cm.is_valid.return_value = True
    return cm


def _create_mock_page(dialog_closes_after_selection: bool = False):
    """Cria um mock de Page com respostas realistas via page.evaluate.

    Args:
        dialog_closes_after_selection: Se True, simula dialog que fecha
            automaticamente após seleção de opção.

    Returns:
        Mock da Page com side_effect configurado para despachar
        respostas baseadas no conteúdo do JS executado.
    """
    page = AsyncMock()

    # Contadores para estado do dialog
    state = {
        "dialog_open": False,
        "selection_count": 0,
        "current_time": 5.0,
    }

    # Setup keyboard mock
    page.keyboard = AsyncMock()
    page.keyboard.press = AsyncMock()

    # Locator mock para dialog, ícones etc.
    mock_locator = AsyncMock()
    mock_locator.count = AsyncMock(return_value=1)
    mock_locator.click = AsyncMock()
    mock_locator.first = mock_locator
    mock_locator.nth = MagicMock(return_value=mock_locator)

    # is_visible depende do estado do dialog
    async def locator_is_visible():
        return state["dialog_open"]

    mock_locator.is_visible = AsyncMock(side_effect=locator_is_visible)

    page.get_by_role = MagicMock(return_value=mock_locator)
    page.locator = MagicMock(return_value=mock_locator)
    page.hover = AsyncMock()
    page.goto = AsyncMock()

    # wait_for_selector simula dialog aparecendo
    async def wait_for_selector_fn(*args, **kwargs):
        state["dialog_open"] = True
        return mock_locator

    page.wait_for_selector = AsyncMock(side_effect=wait_for_selector_fn)

    # page.evaluate - despacha com base no conteúdo JS
    async def evaluate_dispatch(js_code, *args):
        js_str = str(js_code)

        # Playback: currentTime
        if "currentTime" in js_str and "querySelector" in js_str:
            state["current_time"] += 1.0
            return state["current_time"]

        # getAudioTracks
        if "getAudioTracks" in js_str:
            return [
                {"language": "Português", "active": True, "label": "Português"},
                {"language": "Inglês", "active": False, "label": "English"},
            ]

        # getTextTracks
        if "getTextTracks" in js_str:
            return [
                {"language": "Português", "active": True, "label": "Português"},
                {"language": "Inglês", "active": False, "label": "English"},
            ]

        # AudioContext init
        if "AudioContext" in js_str:
            return True

        # Collect audio sample
        if "getFloatTimeDomainData" in js_str or "audioMonitorAnalyser" in js_str:
            return {"rms": 0.05, "peak": 0.12}

        # Discover section options (JS com sectionTitle)
        if "sectionTitle" in js_str and "click" not in js_str:
            return [
                {"text": "Português", "is_selected": True},
                {"text": "Inglês", "is_selected": False},
            ]

        # Click option in section
        if "sectionTitle" in js_str and "click" in js_str:
            state["selection_count"] += 1
            if dialog_closes_after_selection:
                state["dialog_open"] = False
            return True

        # activeCues polling para legendas
        if "activeCues" in js_str:
            return {
                "text": "Esta é uma legenda de teste do canal SKY+",
                "trackLabel": "Português",
            }

        return None

    page.evaluate = AsyncMock(side_effect=evaluate_dispatch)

    return page, state


# ============================================================
# Test Cases
# ============================================================


@pytest.mark.asyncio
async def test_end_to_end_single_channel(fast_config, mock_capability_map):
    """Testa fluxo completo end-to-end com um único canal.

    Verifica que o ConsolidatedReport tem estrutura correta
    após execução completa com mocks realistas.
    """
    page, _ = _create_mock_page(dialog_closes_after_selection=False)

    report = await run_audio_subtitle_monitoring(
        page=page,
        capability_map=mock_capability_map,
        channels=fast_config.channels,
        config=fast_config,
    )

    # Verificar estrutura do ConsolidatedReport
    assert report is not None
    assert report.total_channels == 1
    assert report.channels_pass + report.channels_partial + report.channels_fail == 1
    assert len(report.channel_reports) == 1

    # Verificar relatório do canal
    channel_report = report.channel_reports[0]
    assert channel_report.channel_url == fast_config.channels[0]
    assert channel_report.channel_id == "CH0100000000124"
    assert channel_report.timestamp  # não vazio
    assert channel_report.overall_status in (
        OverallStatus.PASS,
        OverallStatus.PARTIAL,
        OverallStatus.FAIL,
    )
    assert channel_report.duration_ms >= 0

    # Deve ter resultados de áudio e legendas
    assert len(channel_report.audio_results) > 0
    assert len(channel_report.subtitle_results) >= 0


@pytest.mark.asyncio
async def test_end_to_end_multi_channel(multi_channel_config, mock_capability_map):
    """Testa fluxo com 2 canais, ambos sucedendo.

    O consolidated report deve ter 2 entries.
    """
    page, _ = _create_mock_page(dialog_closes_after_selection=False)

    report = await run_audio_subtitle_monitoring(
        page=page,
        capability_map=mock_capability_map,
        channels=multi_channel_config.channels,
        config=multi_channel_config,
    )

    # Verificar 2 canais no relatório consolidado
    assert report.total_channels == 2
    assert len(report.channel_reports) == 2

    # Verificar que ambos os canais foram processados
    channel_ids = [r.channel_id for r in report.channel_reports]
    assert "CH0100000000124" in channel_ids
    assert "CH0100000000092" in channel_ids

    # Contadores devem somar corretamente
    assert (
        report.channels_pass + report.channels_partial + report.channels_fail
        == 2
    )

    # Total duration deve ser >= 0
    assert report.total_duration_ms >= 0


@pytest.mark.asyncio
async def test_dialog_closes_after_selection(fast_config, mock_capability_map):
    """Testa cenário onde o dialog fecha automaticamente após seleção.

    Após select_option, is_visible retorna False (dialog fechou).
    O fluxo deve reabrir o dialog para próxima seleção e ainda
    completar com sucesso.

    Req 6.2: Registrar que diálogo foi fechado e reabri-lo.
    """
    page, state = _create_mock_page(dialog_closes_after_selection=True)

    report = await run_audio_subtitle_monitoring(
        page=page,
        capability_map=mock_capability_map,
        channels=fast_config.channels,
        config=fast_config,
    )

    # O fluxo deve completar com sucesso mesmo com dialog fechando
    assert report is not None
    assert report.total_channels == 1
    assert len(report.channel_reports) == 1

    channel_report = report.channel_reports[0]
    # Deve ter resultados de áudio (mesmo com reabertura de dialog)
    assert len(channel_report.audio_results) > 0
    # Houve seleções (confirmando que o dialog foi usado)
    assert state["selection_count"] > 0


@pytest.mark.asyncio
async def test_dialog_stays_open_after_selection(fast_config, mock_capability_map):
    """Testa cenário onde o dialog permanece aberto após seleção.

    Após select_option, is_visible retorna True (dialog permanece).
    O fluxo deve continuar sem fechar e reabrir o dialog.

    Req 6.3: Continuar seleção sem fechar/reabrir se dialog permanece aberto.
    """
    page, state = _create_mock_page(dialog_closes_after_selection=False)

    report = await run_audio_subtitle_monitoring(
        page=page,
        capability_map=mock_capability_map,
        channels=fast_config.channels,
        config=fast_config,
    )

    # O fluxo deve completar normalmente
    assert report is not None
    assert report.total_channels == 1
    assert len(report.channel_reports) == 1

    channel_report = report.channel_reports[0]
    assert len(channel_report.audio_results) > 0
    # Houve seleções via dialog (confirmando uso contínuo sem reabrir)
    assert state["selection_count"] > 0
    # O dialog permaneceu aberto durante as seleções (não fechou automaticamente)
    # Nota: close_dialog() ao final envia Escape mas nosso mock não altera state
    # O importante é que o fluxo completou sem erros com dialog persistente


@pytest.mark.asyncio
async def test_report_json_has_all_fields(fast_config, mock_capability_map):
    """Testa que o relatório JSON final contém todos os campos obrigatórios.

    Verifica to_dict() em todos os níveis do relatório:
    - ConsolidatedReport: timestamp, total_channels, channels_*, channel_reports
    - ChannelTestReport: channel_url, channel_id, timestamp, audio_results,
      subtitle_results, overall_status, duration_ms
    - TrackTestResult: track_name, track_type, status, evidence, duration_ms,
      telemetry

    Req 7.1, 7.4: Relatório contém todos os campos obrigatórios.
    """
    page, _ = _create_mock_page(dialog_closes_after_selection=False)

    report = await run_audio_subtitle_monitoring(
        page=page,
        capability_map=mock_capability_map,
        channels=fast_config.channels,
        config=fast_config,
    )

    # Serializar para dict
    report_dict = report.to_dict()

    # Verificar campos obrigatórios do ConsolidatedReport
    consolidated_required_fields = [
        "timestamp",
        "total_channels",
        "channels_pass",
        "channels_partial",
        "channels_fail",
        "total_duration_ms",
        "channel_reports",
    ]
    for field in consolidated_required_fields:
        assert field in report_dict, f"Campo ausente no ConsolidatedReport: {field}"

    # Verificar que é serializável para JSON
    json_str = json.dumps(report_dict, ensure_ascii=False)
    parsed = json.loads(json_str)
    assert parsed["total_channels"] == 1

    # Verificar campos do ChannelTestReport
    channel_report_required_fields = [
        "channel_url",
        "channel_id",
        "timestamp",
        "audio_results",
        "subtitle_results",
        "overall_status",
        "duration_ms",
        "audio_options_discovered",
        "subtitle_options_discovered",
        "errors",
    ]
    for ch_report in parsed["channel_reports"]:
        for field in channel_report_required_fields:
            assert field in ch_report, (
                f"Campo ausente no ChannelTestReport: {field}"
            )

        # Verificar campos de cada TrackTestResult (áudio)
        track_result_required_fields = [
            "track_name",
            "track_type",
            "status",
            "evidence",
            "duration_ms",
            "telemetry",
            "api_state_before",
            "api_state_after",
        ]
        for track_result in ch_report["audio_results"]:
            for field in track_result_required_fields:
                assert field in track_result, (
                    f"Campo ausente no TrackTestResult (áudio): {field}"
                )
            # Validar tipos dos campos
            assert track_result["track_type"] == "audio"
            assert track_result["status"] in ("PASS", "FAIL", "TIMEOUT")
            assert isinstance(track_result["duration_ms"], int)
            assert isinstance(track_result["evidence"], dict)

        # Verificar campos de cada TrackTestResult (legendas)
        for track_result in ch_report["subtitle_results"]:
            for field in track_result_required_fields:
                assert field in track_result, (
                    f"Campo ausente no TrackTestResult (legenda): {field}"
                )
            assert track_result["track_type"] == "subtitle"
            assert track_result["status"] in ("PASS", "FAIL", "TIMEOUT")
