"""Integration tests para o Unified Channel Monitor.

Valida o wiring completo do orquestrador com todos os componentes,
verificando:
- Rotação com 2-3 canais funciona end-to-end (com mocks)
- Relatório JSON é gerado corretamente no diretório de output
- Sequência de fases é respeitada no orchestrator

Requirements: 9.1, 8.7, 2.1
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.unified_channel_monitor.config import UnifiedMonitorConfig
from src.unified_channel_monitor.models import (
    AudioTrackResult,
    ChannelSessionStatus,
    ConsolidatedReport,
    SubtitleTrackResult,
    TelemetrySummary,
    UnifiedChannelReport,
)
from src.unified_channel_monitor.orchestrator import UnifiedOrchestrator


# ============================================================
# Helpers
# ============================================================


def _make_video_metrics(current_time: float = 10.0) -> dict:
    """Retorna métricas de vídeo simuladas para page.evaluate."""
    return {
        "currentTime": current_time,
        "totalFramesDecoded": int(current_time * 30),
        "framesDropped": 0,
        "bufferAhead": 5.0,
        "readyState": 4,
    }


def _create_mock_page() -> AsyncMock:
    """Cria mock de Page do Playwright para integration tests.

    Configura evaluate para retornar métricas de vídeo progressivas,
    simular vídeo não pausado, e responder a queries de playback.
    """
    page = AsyncMock()
    page.goto = AsyncMock()
    page.wait_for_selector = AsyncMock()
    page.click = AsyncMock()
    page.hover = AsyncMock()

    # Contador de chamadas evaluate para produzir métricas progressivas
    call_count = {"n": 0}

    async def _mock_evaluate(js_code, *args, **kwargs):
        """Retorna métricas de vídeo progressivas ou valores padrão."""
        call_count["n"] += 1

        # Se é o check de playback (video.paused)
        if "paused" in str(js_code):
            return False

        # Se é o check de currentTime para recovery
        if "currentTime" in str(js_code) and "paused" not in str(js_code):
            # Verificar se é o JS completo de telemetria
            if "totalFramesDecoded" in str(js_code) or "totalVideoFrames" in str(js_code):
                ct = 10.0 + call_count["n"] * 2.0
                return {
                    "currentTime": ct,
                    "totalFramesDecoded": int(ct * 30),
                    "framesDropped": 0,
                    "bufferAhead": 5.0,
                    "readyState": 4,
                }
            return 10.0 + call_count["n"]

        # Default: métricas de vídeo progressivas
        ct = 10.0 + call_count["n"] * 2.0
        return {
            "currentTime": ct,
            "totalFramesDecoded": int(ct * 30),
            "framesDropped": 0,
            "bufferAhead": 5.0,
            "readyState": 4,
        }

    page.evaluate = AsyncMock(side_effect=_mock_evaluate)

    # Keyboard mock
    page.keyboard = AsyncMock()
    page.keyboard.press = AsyncMock()

    # Locator mock
    mock_locator = AsyncMock()
    mock_locator.click = AsyncMock()
    mock_locator.is_visible = AsyncMock(return_value=True)
    mock_locator.count = AsyncMock(return_value=1)
    mock_locator.all_text_contents = AsyncMock(return_value=[])
    mock_locator.first = mock_locator
    mock_locator.nth = MagicMock(return_value=mock_locator)
    page.locator = MagicMock(return_value=mock_locator)

    return page


def _make_audio_results() -> list[AudioTrackResult]:
    """Cria resultados simulados de teste de áudio."""
    return [
        AudioTrackResult(
            track_name="Português",
            status="PASS",
            rms_avg=0.05,
            audio_present_ratio=0.95,
            switch_validated=True,
            duration_ms=2000,
        ),
        AudioTrackResult(
            track_name="English",
            status="PASS",
            rms_avg=0.04,
            audio_present_ratio=0.92,
            switch_validated=True,
            duration_ms=2100,
        ),
    ]


def _make_subtitle_results() -> list[SubtitleTrackResult]:
    """Cria resultados simulados de teste de legendas."""
    return [
        SubtitleTrackResult(
            track_name="Português",
            status="PASS",
            cue_received=True,
            time_to_first_cue_ms=800,
            switch_validated=True,
            duration_ms=3000,
        ),
    ]


# ============================================================
# Integration Test: Rotação com 2-3 canais
# ============================================================


class TestIntegrationRotation:
    """Testa rotação completa com mock Page executando 2-3 canais."""

    @pytest.fixture
    def config(self, tmp_path: Path) -> UnifiedMonitorConfig:
        """Config com output_dir temporário para testes."""
        return UnifiedMonitorConfig(
            channels=[],
            output_dir=str(tmp_path / "reports"),
            telemetry_interval_s=0.1,
            observation_period_s=1.0,
            playback_wait_timeout_s=5.0,
            invalidation_threshold=5,
        )

    @pytest.fixture
    def mock_page(self) -> AsyncMock:
        """Mock Page para integration tests."""
        return _create_mock_page()

    @pytest.mark.asyncio
    async def test_rotation_two_channels_produces_consolidated_report(
        self,
        mock_page: AsyncMock,
        config: UnifiedMonitorConfig,
        tmp_path: Path,
    ):
        """Rotação com 2 canais deve produzir ConsolidatedReport correto.

        Verifica que:
        - ConsolidatedReport tem total_channels=2
        - Cada channel_report tem channel_url correspondente
        - JSON é persistido no diretório de output
        """
        channels = [
            "https://example.com/channel-1",
            "https://example.com/channel-2",
        ]

        orchestrator = UnifiedOrchestrator(
            page=mock_page,
            config=config,
        )

        # Mock dos métodos internos de teste de tracks
        # (evita dependência real de SettingsDialog)
        audio_results = _make_audio_results()
        subtitle_results = _make_subtitle_results()

        with patch.object(
            orchestrator,
            "_test_audio_tracks",
            new_callable=AsyncMock,
            return_value=audio_results,
        ), patch.object(
            orchestrator,
            "_test_subtitle_tracks",
            new_callable=AsyncMock,
            return_value=subtitle_results,
        ):
            result = await orchestrator.run_single_rotation(channels)

        # Verificações do ConsolidatedReport
        assert isinstance(result, ConsolidatedReport)
        assert result.total_channels == 2
        assert len(result.channel_reports) == 2

        # Cada report tem a URL correta
        urls = [r.channel_url for r in result.channel_reports]
        assert "https://example.com/channel-1" in urls
        assert "https://example.com/channel-2" in urls

        # Nenhum canal com erro
        for report in result.channel_reports:
            assert report.status in (
                ChannelSessionStatus.PASS.value,
                ChannelSessionStatus.PARTIAL.value,
            )

    @pytest.mark.asyncio
    async def test_rotation_three_channels_all_processed(
        self,
        mock_page: AsyncMock,
        config: UnifiedMonitorConfig,
        tmp_path: Path,
    ):
        """Rotação com 3 canais processa todos sequencialmente."""
        channels = [
            "https://example.com/ch-a",
            "https://example.com/ch-b",
            "https://example.com/ch-c",
        ]

        orchestrator = UnifiedOrchestrator(
            page=mock_page,
            config=config,
        )

        audio_results = _make_audio_results()
        subtitle_results = _make_subtitle_results()

        with patch.object(
            orchestrator,
            "_test_audio_tracks",
            new_callable=AsyncMock,
            return_value=audio_results,
        ), patch.object(
            orchestrator,
            "_test_subtitle_tracks",
            new_callable=AsyncMock,
            return_value=subtitle_results,
        ):
            result = await orchestrator.run_single_rotation(channels)

        assert result.total_channels == 3
        assert len(result.channel_reports) == 3

        # Verificar que goto foi chamado para cada canal
        goto_calls = mock_page.goto.call_args_list
        assert len(goto_calls) == 3

        # Verificar URLs em ordem
        for i, channel_url in enumerate(channels):
            assert goto_calls[i][0][0] == channel_url


# ============================================================
# Integration Test: JSON Report no diretório de output
# ============================================================


class TestIntegrationReportPersistence:
    """Verifica que JSON report é gerado corretamente no output dir."""

    @pytest.fixture
    def config(self, tmp_path: Path) -> UnifiedMonitorConfig:
        """Config com output_dir temporário."""
        return UnifiedMonitorConfig(
            channels=[],
            output_dir=str(tmp_path / "reports"),
            telemetry_interval_s=0.1,
            observation_period_s=1.0,
            playback_wait_timeout_s=5.0,
            invalidation_threshold=5,
        )

    @pytest.mark.asyncio
    async def test_json_report_file_exists_after_rotation(
        self,
        config: UnifiedMonitorConfig,
        tmp_path: Path,
    ):
        """Após rotação, arquivo JSON deve existir no output dir."""
        mock_page = _create_mock_page()
        channels = [
            "https://example.com/canal-1",
            "https://example.com/canal-2",
        ]

        orchestrator = UnifiedOrchestrator(
            page=mock_page,
            config=config,
        )

        audio_results = _make_audio_results()
        subtitle_results = _make_subtitle_results()

        with patch.object(
            orchestrator,
            "_test_audio_tracks",
            new_callable=AsyncMock,
            return_value=audio_results,
        ), patch.object(
            orchestrator,
            "_test_subtitle_tracks",
            new_callable=AsyncMock,
            return_value=subtitle_results,
        ):
            await orchestrator.run_single_rotation(channels)

        # Verificar que diretório de reports existe
        reports_dir = tmp_path / "reports"
        assert reports_dir.exists()

        # Verificar que pelo menos um JSON foi gerado
        json_files = list(reports_dir.glob("*.json"))
        assert len(json_files) >= 1, (
            f"Nenhum JSON encontrado em {reports_dir}"
        )

    @pytest.mark.asyncio
    async def test_json_report_content_is_valid(
        self,
        config: UnifiedMonitorConfig,
        tmp_path: Path,
    ):
        """Conteúdo do JSON deve ser válido e ter campos esperados."""
        mock_page = _create_mock_page()
        channels = ["https://example.com/canal-test"]

        orchestrator = UnifiedOrchestrator(
            page=mock_page,
            config=config,
        )

        audio_results = _make_audio_results()
        subtitle_results = _make_subtitle_results()

        with patch.object(
            orchestrator,
            "_test_audio_tracks",
            new_callable=AsyncMock,
            return_value=audio_results,
        ), patch.object(
            orchestrator,
            "_test_subtitle_tracks",
            new_callable=AsyncMock,
            return_value=subtitle_results,
        ):
            await orchestrator.run_single_rotation(channels)

        # Encontrar o JSON gerado
        reports_dir = tmp_path / "reports"
        json_files = list(reports_dir.glob("consolidated_report_*.json"))
        assert len(json_files) >= 1

        # Ler e parsear JSON
        json_content = json_files[0].read_text(encoding="utf-8")
        data = json.loads(json_content)

        # Campos obrigatórios do ConsolidatedReport
        assert "timestamp" in data
        assert "total_channels" in data
        assert data["total_channels"] == 1
        assert "channels_pass" in data
        assert "channels_partial" in data
        assert "channels_fail" in data
        assert "channels_unreachable" in data
        assert "channels_error" in data
        assert "channel_reports" in data
        assert isinstance(data["channel_reports"], list)
        assert len(data["channel_reports"]) == 1

        # Campos obrigatórios do UnifiedChannelReport
        channel_report = data["channel_reports"][0]
        assert "channel_url" in channel_report
        assert channel_report["channel_url"] == "https://example.com/canal-test"
        assert "status" in channel_report
        assert "video_summary" in channel_report
        assert "audio_results" in channel_report
        assert "subtitle_results" in channel_report
        assert "session_id" in channel_report
        assert "duration_ms" in channel_report

    @pytest.mark.asyncio
    async def test_json_report_has_correct_structure_per_channel(
        self,
        config: UnifiedMonitorConfig,
        tmp_path: Path,
    ):
        """Estrutura do report por canal inclui video_summary, audio e subtitle."""
        mock_page = _create_mock_page()
        channels = [
            "https://example.com/ch-alpha",
            "https://example.com/ch-beta",
        ]

        orchestrator = UnifiedOrchestrator(
            page=mock_page,
            config=config,
        )

        audio_results = _make_audio_results()
        subtitle_results = _make_subtitle_results()

        with patch.object(
            orchestrator,
            "_test_audio_tracks",
            new_callable=AsyncMock,
            return_value=audio_results,
        ), patch.object(
            orchestrator,
            "_test_subtitle_tracks",
            new_callable=AsyncMock,
            return_value=subtitle_results,
        ):
            await orchestrator.run_single_rotation(channels)

        reports_dir = tmp_path / "reports"
        json_files = list(reports_dir.glob("consolidated_report_*.json"))
        data = json.loads(json_files[0].read_text(encoding="utf-8"))

        for channel_report in data["channel_reports"]:
            # Video summary
            vs = channel_report["video_summary"]
            assert "total_samples" in vs
            assert "health_classification" in vs

            # Audio results
            assert "audio_tracks_tested" in channel_report
            assert "audio_tracks_passed" in channel_report
            for ar in channel_report["audio_results"]:
                assert "track_name" in ar
                assert "status" in ar
                assert "rms_avg" in ar
                assert "audio_present_ratio" in ar

            # Subtitle results
            assert "subtitle_tracks_tested" in channel_report
            assert "subtitle_tracks_passed" in channel_report
            for sr in channel_report["subtitle_results"]:
                assert "track_name" in sr
                assert "status" in sr
                assert "cue_received" in sr


# ============================================================
# Integration Test: Validação da sequência de fases
# ============================================================


class TestIntegrationPhaseSequence:
    """Valida que fases executam na ordem correta no orchestrator."""

    @pytest.fixture
    def config(self, tmp_path: Path) -> UnifiedMonitorConfig:
        """Config com output_dir temporário."""
        return UnifiedMonitorConfig(
            channels=[],
            output_dir=str(tmp_path / "reports"),
            telemetry_interval_s=0.1,
            observation_period_s=1.0,
            playback_wait_timeout_s=5.0,
            invalidation_threshold=5,
        )

    @pytest.mark.asyncio
    async def test_phase_sequence_per_channel(
        self,
        config: UnifiedMonitorConfig,
        tmp_path: Path,
    ):
        """Verifica sequência: navigate → discovery → telemetry start →
        audio → verify playback → subtitles → telemetry stop → escalation.

        Usa call_order tracking para garantir a ordem correta.
        """
        mock_page = _create_mock_page()
        channels = ["https://example.com/test-channel"]

        orchestrator = UnifiedOrchestrator(
            page=mock_page,
            config=config,
        )

        # Tracking de ordem de chamadas
        call_order: list[str] = []

        # Mock _navigate_to_channel
        original_navigate = orchestrator._navigate_to_channel

        async def track_navigate(url, sid):
            call_order.append("navigate")
            await original_navigate(url, sid)

        # Mock _ensure_capability_map
        async def track_discovery(sid):
            call_order.append("discovery")
            orchestrator._capability_map = {"player_type": "mock"}

        # Mock _test_audio_tracks
        async def track_audio(*args, **kwargs):
            call_order.append("test_audio")
            return _make_audio_results()

        # Mock _verify_playback
        async def track_verify(sid):
            call_order.append("verify_playback")
            return True

        # Mock _test_subtitle_tracks
        async def track_subtitles(*args, **kwargs):
            call_order.append("test_subtitles")
            return _make_subtitle_results()

        with patch.object(
            orchestrator, "_navigate_to_channel", side_effect=track_navigate
        ), patch.object(
            orchestrator, "_ensure_capability_map", side_effect=track_discovery
        ), patch.object(
            orchestrator, "_test_audio_tracks", side_effect=track_audio
        ), patch.object(
            orchestrator, "_verify_playback", side_effect=track_verify
        ), patch.object(
            orchestrator, "_test_subtitle_tracks", side_effect=track_subtitles
        ):
            await orchestrator.run_single_rotation(channels)

        # Verificar ordem
        expected_order = [
            "navigate",
            "discovery",
            "test_audio",
            "verify_playback",
            "test_subtitles",
        ]
        assert call_order == expected_order, (
            f"Sequência incorreta: {call_order} != {expected_order}"
        )

    @pytest.mark.asyncio
    async def test_phase_sequence_repeats_for_each_channel(
        self,
        config: UnifiedMonitorConfig,
        tmp_path: Path,
    ):
        """A sequência de fases se repete para cada canal na rotação."""
        mock_page = _create_mock_page()
        channels = [
            "https://example.com/ch-1",
            "https://example.com/ch-2",
        ]

        orchestrator = UnifiedOrchestrator(
            page=mock_page,
            config=config,
        )

        call_order: list[str] = []

        async def track_navigate(url, sid):
            call_order.append(f"navigate:{url}")
            # Simular o que o navigate faz sem chamar page real
            # (page mock já está configurado)

        async def track_discovery(sid):
            call_order.append("discovery")
            orchestrator._capability_map = {"player_type": "mock"}

        async def track_audio(*args, **kwargs):
            call_order.append("test_audio")
            return _make_audio_results()

        async def track_verify(sid):
            call_order.append("verify_playback")
            return True

        async def track_subtitles(*args, **kwargs):
            call_order.append("test_subtitles")
            return _make_subtitle_results()

        with patch.object(
            orchestrator, "_navigate_to_channel", side_effect=track_navigate
        ), patch.object(
            orchestrator, "_ensure_capability_map", side_effect=track_discovery
        ), patch.object(
            orchestrator, "_test_audio_tracks", side_effect=track_audio
        ), patch.object(
            orchestrator, "_verify_playback", side_effect=track_verify
        ), patch.object(
            orchestrator, "_test_subtitle_tracks", side_effect=track_subtitles
        ):
            await orchestrator.run_single_rotation(channels)

        # Para 2 canais, discovery executa na primeira vez e reusa na segunda
        # Mas como mockamos _ensure_capability_map, ela vai chamar "discovery"
        # para ambos (o mock não verifica se já existe).
        # O importante é que para CADA canal, as fases ocorrem em ordem.
        assert call_order[0] == "navigate:https://example.com/ch-1"
        assert call_order[1] == "discovery"
        assert call_order[2] == "test_audio"
        assert call_order[3] == "verify_playback"
        assert call_order[4] == "test_subtitles"

        assert call_order[5] == "navigate:https://example.com/ch-2"
        assert call_order[6] == "discovery"
        assert call_order[7] == "test_audio"
        assert call_order[8] == "verify_playback"
        assert call_order[9] == "test_subtitles"

    @pytest.mark.asyncio
    async def test_telemetry_start_and_stop_around_track_tests(
        self,
        config: UnifiedMonitorConfig,
        tmp_path: Path,
    ):
        """Telemetria inicia antes dos testes de track e para depois.

        Usa patch no VideoTelemetryCollector para rastrear start/stop.
        """
        mock_page = _create_mock_page()
        channels = ["https://example.com/telemetry-test"]

        orchestrator = UnifiedOrchestrator(
            page=mock_page,
            config=config,
        )

        call_order: list[str] = []
        audio_results = _make_audio_results()
        subtitle_results = _make_subtitle_results()

        # Patch VideoTelemetryCollector
        with patch(
            "src.unified_channel_monitor.orchestrator.VideoTelemetryCollector"
        ) as MockVTC:
            mock_vtc_instance = AsyncMock()
            mock_vtc_instance.get_deferred_escalations.return_value = []
            mock_vtc_instance.stop.return_value = TelemetrySummary(
                total_samples=5,
                health_classification="HEALTHY",
            )

            async def track_start(*args, **kwargs):
                call_order.append("telemetry_start")

            async def track_stop():
                call_order.append("telemetry_stop")
                return TelemetrySummary(
                    total_samples=5,
                    health_classification="HEALTHY",
                )

            mock_vtc_instance.start = AsyncMock(side_effect=track_start)
            mock_vtc_instance.stop = AsyncMock(side_effect=track_stop)
            MockVTC.return_value = mock_vtc_instance

            async def track_audio(*args, **kwargs):
                call_order.append("test_audio")
                return audio_results

            async def track_subtitles(*args, **kwargs):
                call_order.append("test_subtitles")
                return subtitle_results

            with patch.object(
                orchestrator, "_test_audio_tracks", side_effect=track_audio
            ), patch.object(
                orchestrator,
                "_test_subtitle_tracks",
                side_effect=track_subtitles,
            ):
                await orchestrator.run_single_rotation(channels)

        # Verificar que telemetry_start vem antes dos testes
        # e telemetry_stop vem depois
        assert "telemetry_start" in call_order
        assert "test_audio" in call_order
        assert "test_subtitles" in call_order
        assert "telemetry_stop" in call_order

        start_idx = call_order.index("telemetry_start")
        audio_idx = call_order.index("test_audio")
        subtitle_idx = call_order.index("test_subtitles")
        stop_idx = call_order.index("telemetry_stop")

        assert start_idx < audio_idx, "Telemetria deve iniciar antes do áudio"
        assert audio_idx < subtitle_idx, "Áudio antes de legendas"
        assert subtitle_idx < stop_idx, "Telemetria deve parar após legendas"


# ============================================================
# Integration Test: Imports no __init__.py
# ============================================================


class TestModuleImports:
    """Verifica que todos os componentes estão importáveis via __init__.py."""

    def test_models_importable(self):
        """Todos os models devem ser importáveis do pacote."""
        from src.unified_channel_monitor import (
            AudioTrackResult,
            ChannelSessionStatus,
            ConsolidatedReport,
            DeferredEscalation,
            EscalationResult,
            FreezeEvent,
            SubtitleTrackResult,
            TelemetrySample,
            TelemetrySummary,
            UnifiedChannelReport,
        )

        # Verificar que são as classes corretas
        assert ChannelSessionStatus.PASS.value == "PASS"
        assert hasattr(TelemetrySample, "__dataclass_fields__")
        assert hasattr(ConsolidatedReport, "__dataclass_fields__")

    def test_config_importable(self):
        """UnifiedMonitorConfig deve ser importável do pacote."""
        from src.unified_channel_monitor import UnifiedMonitorConfig

        config = UnifiedMonitorConfig()
        assert config.telemetry_interval_s == 2.0

    def test_components_importable(self):
        """Todos os componentes principais devem ser importáveis."""
        from src.unified_channel_monitor import (
            AudioTrackTester,
            EscalationManager,
            SubtitleTrackTester,
            UnifiedOrchestrator,
            UnifiedReportGenerator,
            VideoTelemetryCollector,
        )

        # Verificar que são classes
        assert callable(UnifiedOrchestrator)
        assert callable(VideoTelemetryCollector)
        assert callable(AudioTrackTester)
        assert callable(SubtitleTrackTester)
        assert callable(EscalationManager)
        assert callable(UnifiedReportGenerator)

    def test_version_defined(self):
        """__version__ deve estar definido."""
        from src.unified_channel_monitor import __version__

        assert __version__ == "0.1.0"
