"""Unit tests para AudioSubtitleOrchestrator.

Testa o fluxo de orquestração multi-canal com mocks dos componentes
internos (SettingsDialogManager, AudioMonitor, SubtitleMonitor,
ReportGenerator).

Cenários testados:
- Fluxo completo de um canal com mocks
- Sequência de 3 canais com 1 falha no meio (continuidade)
- Canal com playback timeout — skip correto
- Navegação falha — report com erro correto
- Settings dialog indisponível — report com erro correto
- Restauração de tracks iniciais
- Dialog fechado ao final da sessão

Requirements: 9.1, 9.2, 9.3, 9.5
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.audio_subtitle_monitor.config import AudioSubtitleConfig
from src.audio_subtitle_monitor.models import (
    AudioSample,
    AudioTelemetryResult,
    CueResult,
    OverallStatus,
    TrackOption,
    TrackTestStatus,
    ValidationResult,
)
from src.audio_subtitle_monitor.orchestrator import (
    AudioSubtitleOrchestrator,
)


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def config(tmp_path):
    """Configuração com timeouts curtos para testes rápidos."""
    return AudioSubtitleConfig(
        channels=[],
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
def orchestrator(config):
    """Cria orchestrator com page e capability_map mockados."""
    page = AsyncMock()
    capability_map = MagicMock()
    capability_map.get_interaction_strategy.return_value = "semantic_dom"

    orch = AudioSubtitleOrchestrator(
        page=page, capability_map=capability_map, config=config
    )
    return orch


# ============================================================
# Test: Fluxo completo de um canal com mocks
# ============================================================


@pytest.mark.asyncio
async def test_run_channel_full_flow(orchestrator):
    """Testa fluxo completo de um canal com todos componentes mockados.

    Mock de todos os componentes internos, executa run_channel para
    um canal e verifica que o ChannelTestReport contém resultados
    de áudio e legendas.

    Requirements: 9.1, 9.2
    """
    channel_url = (
        "https://www.skymais.com.br/player/live/CH0100000000124"
    )

    # Mock _navigate_to_channel e _wait_for_playback
    orchestrator._navigate_to_channel = AsyncMock(return_value=True)
    orchestrator._wait_for_playback = AsyncMock(return_value=True)

    # Mock SettingsDialogManager
    orchestrator._settings_manager.open_dialog = AsyncMock(
        return_value=True
    )
    orchestrator._settings_manager.discover_audio_options = AsyncMock(
        return_value=[
            TrackOption("Português", True, 0),
            TrackOption("Inglês", False, 1),
        ]
    )
    orchestrator._settings_manager.discover_subtitle_options = AsyncMock(
        return_value=[
            TrackOption("Desativadas", True, 0),
            TrackOption("Português", False, 1),
        ]
    )
    orchestrator._settings_manager.select_option = AsyncMock(
        return_value=True
    )
    orchestrator._settings_manager.close_dialog = AsyncMock(
        return_value=True
    )

    # Mock AudioMonitor
    orchestrator._audio_monitor.get_active_tracks = AsyncMock(
        return_value=[
            {"language": "pt", "active": True},
            {"language": "en", "active": False},
        ]
    )
    orchestrator._audio_monitor.validate_track_switch = AsyncMock(
        return_value=ValidationResult(
            success=True,
            expected_language="Português",
            actual_active_language="pt",
            api_tracks=[
                {"language": "pt", "active": True},
                {"language": "en", "active": False},
            ],
        )
    )
    orchestrator._audio_monitor.collect_telemetry = AsyncMock(
        return_value=AudioTelemetryResult(
            samples=[AudioSample(timestamp=0.0, rms=0.05, peak=0.1)],
            rms_avg=0.05,
            rms_min=0.03,
            rms_max=0.08,
            audio_present_ratio=0.95,
            silence_duration_s=0.0,
            total_duration_s=0.1,
        )
    )
    orchestrator._audio_monitor.classify_result = MagicMock(
        return_value=TrackTestStatus.PASS
    )

    # Mock SubtitleMonitor
    orchestrator._subtitle_monitor.get_active_tracks = AsyncMock(
        return_value=[
            {"language": "off", "active": True},
            {"language": "pt", "active": False},
        ]
    )
    orchestrator._subtitle_monitor.validate_track_switch = AsyncMock(
        return_value=ValidationResult(
            success=True,
            expected_language="Português",
            actual_active_language="pt",
            api_tracks=[
                {"language": "off", "active": False},
                {"language": "pt", "active": True},
            ],
        )
    )
    orchestrator._subtitle_monitor.wait_for_active_cue = AsyncMock(
        return_value=CueResult(
            found=True,
            cue_text="Texto de legenda teste",
            time_to_first_cue_ms=500,
        )
    )

    # Executar
    report = await orchestrator.run_channel(channel_url)

    # Verificações
    assert report.channel_url == channel_url
    assert report.channel_id == "CH0100000000124"
    assert report.overall_status == OverallStatus.PASS
    # 2 audio tracks testados (Português e Inglês)
    assert len(report.audio_results) == 2
    # 1 subtitle track testado ("Desativadas" é excluída)
    assert len(report.subtitle_results) == 1
    assert report.audio_results[0].status == TrackTestStatus.PASS
    assert report.subtitle_results[0].status == TrackTestStatus.PASS
    assert report.subtitle_results[0].track_name == "Português"
    assert not report.errors


# ============================================================
# Test: Sequência de 3 canais com 1 falha no meio
# ============================================================


@pytest.mark.asyncio
async def test_run_3_channels_one_fails(orchestrator):
    """Testa que quando um canal levanta exceção, os demais continuam.

    3 canais configurados. O 2º canal levanta exceção inesperada.
    O relatório consolidado deve ter 3 entradas, com a 2ª contendo
    o erro.

    Requirements: 9.1, 9.5
    """
    channels = [
        "https://www.skymais.com.br/player/live/CH001",
        "https://www.skymais.com.br/player/live/CH002",
        "https://www.skymais.com.br/player/live/CH003",
    ]

    call_count = 0

    async def mock_run_channel(channel_url: str):
        nonlocal call_count
        call_count += 1
        if "CH002" in channel_url:
            raise RuntimeError("Erro inesperado no canal 2")
        # Retorna report simples para canais que não falham
        from src.audio_subtitle_monitor.models import ChannelTestReport
        from datetime import datetime, timezone

        channel_id = channel_url.rstrip("/").split("/")[-1]
        return ChannelTestReport(
            channel_url=channel_url,
            channel_id=channel_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            audio_results=[],
            subtitle_results=[],
            overall_status=OverallStatus.PASS,
            duration_ms=100,
            errors=[],
        )

    orchestrator.run_channel = AsyncMock(side_effect=mock_run_channel)

    # Executar
    consolidated = await orchestrator.run(channels)

    # Verificações
    assert consolidated.total_channels == 3
    assert call_count == 3  # Todos os 3 canais foram processados

    # O 2º canal deve ter status FAIL com erro
    ch002_report = consolidated.channel_reports[1]
    assert ch002_report.overall_status == OverallStatus.FAIL
    assert any("Erro inesperado" in e for e in ch002_report.errors)

    # Os canais 1 e 3 devem ser PASS
    assert consolidated.channel_reports[0].overall_status == OverallStatus.PASS
    assert consolidated.channel_reports[2].overall_status == OverallStatus.PASS


# ============================================================
# Test: Canal com playback timeout — skip correto
# ============================================================


@pytest.mark.asyncio
async def test_playback_timeout_skip(orchestrator):
    """Testa que canal com playback timeout recebe report com erro.

    Quando _wait_for_playback retorna False, o report deve ter
    "playback_not_started" nos erros e overall_status FAIL.

    Requirements: 9.2, 9.3
    """
    channel_url = (
        "https://www.skymais.com.br/player/live/CH0100000000092"
    )

    orchestrator._navigate_to_channel = AsyncMock(return_value=True)
    orchestrator._wait_for_playback = AsyncMock(return_value=False)

    # Executar
    report = await orchestrator.run_channel(channel_url)

    # Verificações
    assert report.overall_status == OverallStatus.FAIL
    assert "playback_not_started" in report.errors
    assert report.channel_id == "CH0100000000092"
    assert len(report.audio_results) == 0
    assert len(report.subtitle_results) == 0


# ============================================================
# Test: Navegação falha
# ============================================================


@pytest.mark.asyncio
async def test_navigation_fails(orchestrator):
    """Testa que falha na navegação gera report com erro correto.

    Quando _navigate_to_channel retorna False, o report deve ter
    "navigation_failed" nos erros e overall_status FAIL.

    Requirements: 9.2
    """
    channel_url = (
        "https://www.skymais.com.br/player/live/CH0100000000093"
    )

    orchestrator._navigate_to_channel = AsyncMock(return_value=False)

    # Executar
    report = await orchestrator.run_channel(channel_url)

    # Verificações
    assert report.overall_status == OverallStatus.FAIL
    assert "navigation_failed" in report.errors
    assert report.channel_id == "CH0100000000093"
    assert len(report.audio_results) == 0
    assert len(report.subtitle_results) == 0


# ============================================================
# Test: Settings dialog indisponível
# ============================================================


@pytest.mark.asyncio
async def test_settings_dialog_unavailable(orchestrator):
    """Testa que settings dialog indisponível gera report com erro.

    Quando open_dialog retorna False, o report deve ter
    "settings_dialog_unavailable" nos erros e overall_status FAIL.

    Requirements: 9.2
    """
    channel_url = (
        "https://www.skymais.com.br/player/live/CH0100000000094"
    )

    orchestrator._navigate_to_channel = AsyncMock(return_value=True)
    orchestrator._wait_for_playback = AsyncMock(return_value=True)
    orchestrator._settings_manager.open_dialog = AsyncMock(
        return_value=False
    )

    # Executar
    report = await orchestrator.run_channel(channel_url)

    # Verificações
    assert report.overall_status == OverallStatus.FAIL
    assert "settings_dialog_unavailable" in report.errors
    assert report.channel_id == "CH0100000000094"
    assert len(report.audio_results) == 0
    assert len(report.subtitle_results) == 0


# ============================================================
# Test: Restauração de tracks iniciais
# ============================================================


@pytest.mark.asyncio
async def test_track_restoration(orchestrator):
    """Testa que tracks iniciais são restaurados ao final da sessão.

    Após testar todos os tracks, select_option deve ser chamado
    com os nomes dos tracks iniciais (áudio e legenda).

    Requirements: 9.1, 9.2
    """
    channel_url = (
        "https://www.skymais.com.br/player/live/CH0100000000124"
    )

    orchestrator._navigate_to_channel = AsyncMock(return_value=True)
    orchestrator._wait_for_playback = AsyncMock(return_value=True)

    # Dialog
    orchestrator._settings_manager.open_dialog = AsyncMock(
        return_value=True
    )
    # Audio: "Português" é o selecionado inicialmente
    orchestrator._settings_manager.discover_audio_options = AsyncMock(
        return_value=[
            TrackOption("Português", True, 0),
            TrackOption("Inglês", False, 1),
        ]
    )
    # Subtitle: "Desativadas" é o selecionado inicialmente
    orchestrator._settings_manager.discover_subtitle_options = AsyncMock(
        return_value=[
            TrackOption("Desativadas", True, 0),
            TrackOption("Espanhol", False, 1),
        ]
    )
    orchestrator._settings_manager.select_option = AsyncMock(
        return_value=True
    )
    orchestrator._settings_manager.close_dialog = AsyncMock(
        return_value=True
    )

    # Audio Monitor
    orchestrator._audio_monitor.get_active_tracks = AsyncMock(
        return_value=[{"language": "pt", "active": True}]
    )
    orchestrator._audio_monitor.validate_track_switch = AsyncMock(
        return_value=ValidationResult(
            success=True,
            expected_language="Português",
            actual_active_language="pt",
            api_tracks=[{"language": "pt", "active": True}],
        )
    )
    orchestrator._audio_monitor.collect_telemetry = AsyncMock(
        return_value=AudioTelemetryResult(
            samples=[],
            rms_avg=0.05,
            rms_min=0.03,
            rms_max=0.08,
            audio_present_ratio=0.90,
            silence_duration_s=0.0,
            total_duration_s=0.1,
        )
    )
    orchestrator._audio_monitor.classify_result = MagicMock(
        return_value=TrackTestStatus.PASS
    )

    # Subtitle Monitor
    orchestrator._subtitle_monitor.get_active_tracks = AsyncMock(
        return_value=[{"language": "es", "active": False}]
    )
    orchestrator._subtitle_monitor.validate_track_switch = AsyncMock(
        return_value=ValidationResult(
            success=True,
            expected_language="Espanhol",
            actual_active_language="es",
            api_tracks=[{"language": "es", "active": True}],
        )
    )
    orchestrator._subtitle_monitor.wait_for_active_cue = AsyncMock(
        return_value=CueResult(
            found=True,
            cue_text="Subtítulo em espanhol",
            time_to_first_cue_ms=300,
        )
    )

    # Executar
    await orchestrator.run_channel(channel_url)

    # Verificar chamadas de select_option
    calls = orchestrator._settings_manager.select_option.call_args_list

    # As últimas 2 chamadas de select_option devem ser para restauração
    # (pode haver chamadas anteriores para os tracks de teste)
    # Áudio: 2 chamadas de teste + 1 restauração = "Português"
    # Subtitle: 1 chamada de teste + 1 restauração = "Desativadas"
    restore_audio_call = None
    restore_subtitle_call = None

    for call in reversed(calls):
        args = call[0]
        if args[0] == "IDIOMA ALTERNATIVO" and restore_audio_call is None:
            restore_audio_call = args
        elif args[0] == "LEGENDAS" and restore_subtitle_call is None:
            restore_subtitle_call = args

    # Restauração de áudio com track inicial
    assert restore_audio_call is not None
    assert restore_audio_call[1] == "Português"

    # Restauração de legenda com track inicial
    assert restore_subtitle_call is not None
    assert restore_subtitle_call[1] == "Desativadas"


# ============================================================
# Test: Dialog fechado ao final da sessão
# ============================================================


@pytest.mark.asyncio
async def test_dialog_closed_at_end(orchestrator):
    """Testa que close_dialog é chamado ao final de run_channel.

    Após toda a sessão de testes, o dialog deve ser fechado
    para restaurar o estado visual do player.

    Requirements: 9.1
    """
    channel_url = (
        "https://www.skymais.com.br/player/live/CH0100000000096"
    )

    orchestrator._navigate_to_channel = AsyncMock(return_value=True)
    orchestrator._wait_for_playback = AsyncMock(return_value=True)

    # Dialog
    orchestrator._settings_manager.open_dialog = AsyncMock(
        return_value=True
    )
    orchestrator._settings_manager.discover_audio_options = AsyncMock(
        return_value=[TrackOption("Português", True, 0)]
    )
    orchestrator._settings_manager.discover_subtitle_options = AsyncMock(
        return_value=[TrackOption("Desativadas", True, 0)]
    )
    orchestrator._settings_manager.select_option = AsyncMock(
        return_value=True
    )
    orchestrator._settings_manager.close_dialog = AsyncMock(
        return_value=True
    )

    # Audio Monitor (1 track para testar)
    orchestrator._audio_monitor.get_active_tracks = AsyncMock(
        return_value=[{"language": "pt", "active": True}]
    )
    orchestrator._audio_monitor.validate_track_switch = AsyncMock(
        return_value=ValidationResult(
            success=True,
            expected_language="Português",
            actual_active_language="pt",
            api_tracks=[{"language": "pt", "active": True}],
        )
    )
    orchestrator._audio_monitor.collect_telemetry = AsyncMock(
        return_value=AudioTelemetryResult(
            samples=[],
            rms_avg=0.05,
            rms_min=0.05,
            rms_max=0.05,
            audio_present_ratio=1.0,
            silence_duration_s=0.0,
            total_duration_s=0.1,
        )
    )
    orchestrator._audio_monitor.classify_result = MagicMock(
        return_value=TrackTestStatus.PASS
    )

    # Subtitle Monitor (nenhum track testável — apenas "Desativadas")
    orchestrator._subtitle_monitor.get_active_tracks = AsyncMock(
        return_value=[]
    )

    # Executar
    await orchestrator.run_channel(channel_url)

    # Verificar que close_dialog foi chamado
    orchestrator._settings_manager.close_dialog.assert_called_once()
