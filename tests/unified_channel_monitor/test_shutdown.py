"""Testes unitários e property tests para shutdown graceful do UnifiedOrchestrator.

Valida:
- Registro de signal handlers (Unix e Windows fallback)
- Flag _shutting_down setada ao receber sinal
- Timeout de 10s para sessão em andamento
- Persistência de relatórios parciais
- Geração de relatório parcial para canal interrompido
- Fechamento de browser context
- Exit codes (0 clean, 1 erro)
- Property 12: Shutdown preserves all collected data
"""

from __future__ import annotations

import asyncio
import platform
import signal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.unified_channel_monitor.config import UnifiedMonitorConfig
from src.unified_channel_monitor.models import (
    ChannelSessionStatus,
    ConsolidatedReport,
    TelemetrySummary,
    UnifiedChannelReport,
)
from src.unified_channel_monitor.orchestrator import UnifiedOrchestrator


# ============================================================
# Helpers
# ============================================================


def _make_orchestrator(
    mock_page=None,
    browser_context=None,
    output_dir="/tmp/test_shutdown/",
) -> UnifiedOrchestrator:
    """Cria UnifiedOrchestrator com mocks para testes."""
    if mock_page is None:
        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.wait_for_selector = AsyncMock()
        mock_page.evaluate = AsyncMock(return_value=False)

    config = UnifiedMonitorConfig(
        output_dir=output_dir,
        invalidation_threshold=3,
    )

    return UnifiedOrchestrator(
        page=mock_page,
        config=config,
        browser_context=browser_context,
    )


def _make_report(
    channel_url: str, status: str = "PASS"
) -> UnifiedChannelReport:
    """Cria um UnifiedChannelReport para testes."""
    return UnifiedChannelReport(
        channel_url=channel_url,
        channel_id=f"ch-test",
        session_id="test-session",
        timestamp="2024-01-01T00:00:00Z",
        status=status,
        duration_ms=1000,
        video_summary=TelemetrySummary(total_samples=10),
        audio_tracks_tested=1,
        audio_tracks_passed=1,
        audio_results=[],
        subtitle_tracks_tested=1,
        subtitle_tracks_passed=1,
        subtitle_results=[],
        escalation_results=[],
        telemetry_annotations=[],
        errors=[],
    )


# ============================================================
# Test: shutdown() seta flag _shutting_down
# ============================================================


class TestShutdownFlag:
    """Testes da flag _shutting_down."""

    @pytest.mark.asyncio
    async def test_shutdown_sets_flag(self) -> None:
        """shutdown() deve setar _shutting_down = True."""
        orchestrator = _make_orchestrator()
        assert orchestrator._shutting_down is False

        await orchestrator.shutdown()

        assert orchestrator._shutting_down is True

    @pytest.mark.asyncio
    async def test_shutdown_idempotent(self) -> None:
        """Chamadas duplicadas a shutdown() não causam erro."""
        orchestrator = _make_orchestrator()

        await orchestrator.shutdown()
        await orchestrator.shutdown()  # segunda chamada

        assert orchestrator._shutting_down is True


# ============================================================
# Test: register_signal_handlers
# ============================================================


class TestSignalHandlers:
    """Testes de registro de signal handlers."""

    def test_register_signal_handlers_windows(self) -> None:
        """No Windows usa signal.signal como fallback."""
        orchestrator = _make_orchestrator()

        with patch("src.unified_channel_monitor.orchestrator.platform") as mock_platform:
            mock_platform.system.return_value = "Windows"
            with patch("src.unified_channel_monitor.orchestrator.signal") as mock_signal:
                orchestrator.register_signal_handlers()
                mock_signal.signal.assert_called_once_with(
                    mock_signal.SIGINT,
                    orchestrator._handle_sigint_sync,
                )

    def test_register_signal_handlers_unix(self) -> None:
        """No Unix usa asyncio.add_signal_handler."""
        orchestrator = _make_orchestrator()

        with patch("src.unified_channel_monitor.orchestrator.platform") as mock_platform:
            mock_platform.system.return_value = "Linux"
            with patch("src.unified_channel_monitor.orchestrator.asyncio") as mock_asyncio:
                mock_loop = MagicMock()
                mock_asyncio.get_event_loop.return_value = mock_loop
                orchestrator.register_signal_handlers()
                mock_loop.add_signal_handler.assert_called_once()

    def test_unix_fallback_to_windows_on_error(self) -> None:
        """Se add_signal_handler falhar, usa signal.signal."""
        orchestrator = _make_orchestrator()

        with patch("src.unified_channel_monitor.orchestrator.platform") as mock_platform:
            mock_platform.system.return_value = "Linux"
            with patch("src.unified_channel_monitor.orchestrator.asyncio") as mock_asyncio:
                mock_loop = MagicMock()
                mock_loop.add_signal_handler.side_effect = NotImplementedError
                mock_asyncio.get_event_loop.return_value = mock_loop
                with patch("src.unified_channel_monitor.orchestrator.signal") as mock_signal:
                    orchestrator.register_signal_handlers()
                    mock_signal.signal.assert_called_once()

    def test_handle_sigint_sync_sets_flag(self) -> None:
        """_handle_sigint_sync seta _shutting_down diretamente."""
        orchestrator = _make_orchestrator()
        assert orchestrator._shutting_down is False

        orchestrator._handle_sigint_sync(signal.SIGINT, None)

        assert orchestrator._shutting_down is True


# ============================================================
# Test: close_browser
# ============================================================


class TestCloseBrowser:
    """Testes de fechamento do browser context."""

    @pytest.mark.asyncio
    async def test_close_browser_with_context(self) -> None:
        """Fecha browser context quando disponível."""
        mock_context = AsyncMock()
        orchestrator = _make_orchestrator(
            browser_context=mock_context
        )

        await orchestrator.close_browser()

        mock_context.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_browser_without_context(self) -> None:
        """Sem browser_context, close_browser não falha."""
        orchestrator = _make_orchestrator(browser_context=None)

        # Não deve lançar exceção
        await orchestrator.close_browser()

    @pytest.mark.asyncio
    async def test_close_browser_handles_error(self) -> None:
        """Se fechar browser falhar, loga sem propagar."""
        mock_context = AsyncMock()
        mock_context.close.side_effect = RuntimeError("browser crash")
        orchestrator = _make_orchestrator(
            browser_context=mock_context
        )

        # Não deve lançar exceção
        await orchestrator.close_browser()


# ============================================================
# Test: _create_partial_channel_report
# ============================================================


class TestPartialChannelReport:
    """Testes de geração de relatório parcial."""

    def test_partial_report_status(self) -> None:
        """Relatório parcial tem status PARTIAL."""
        orchestrator = _make_orchestrator()

        report = orchestrator._create_partial_channel_report(
            channel_url="https://example.com/live",
            duration_ms=5000,
        )

        assert report.status == ChannelSessionStatus.PARTIAL.value

    def test_partial_report_has_error_message(self) -> None:
        """Relatório parcial indica interrupção por shutdown."""
        orchestrator = _make_orchestrator()

        report = orchestrator._create_partial_channel_report(
            channel_url="https://example.com/live",
            duration_ms=5000,
        )

        assert len(report.errors) == 1
        assert "shutdown" in report.errors[0].lower()

    def test_partial_report_preserves_url(self) -> None:
        """Relatório parcial preserva a URL do canal."""
        orchestrator = _make_orchestrator()
        url = "https://example.com/channel/123"

        report = orchestrator._create_partial_channel_report(
            channel_url=url,
            duration_ms=3000,
        )

        assert report.channel_url == url
        assert report.duration_ms == 3000


# ============================================================
# Test: _persist_partial_results
# ============================================================


class TestPersistPartialResults:
    """Testes de persistência de resultados parciais."""

    @pytest.mark.asyncio
    async def test_persist_with_reports(self) -> None:
        """Persiste relatório parcial com canais já coletados."""
        orchestrator = _make_orchestrator()
        orchestrator._report_generator = MagicMock()
        orchestrator._report_generator.create_consolidated_report = (
            MagicMock(
                return_value=ConsolidatedReport(
                    timestamp="2024-01-01T00:00:00Z",
                    total_channels=3,
                    channels_pass=2,
                )
            )
        )
        orchestrator._report_generator.persist_report = MagicMock()

        reports = [
            _make_report("https://ch1.com/live"),
            _make_report("https://ch2.com/live"),
        ]

        await orchestrator._persist_partial_results(
            channel_reports=reports,
            total_channels=5,
        )

        orchestrator._report_generator.persist_report.assert_called_once()
        call_args = (
            orchestrator._report_generator.persist_report.call_args
        )
        filename = call_args[1]["filename"] if "filename" in call_args[1] else call_args[0][1]
        assert "PARTIAL" in filename

    @pytest.mark.asyncio
    async def test_persist_empty_reports_noop(self) -> None:
        """Sem relatórios coletados, não persiste nada."""
        orchestrator = _make_orchestrator()
        orchestrator._report_generator = MagicMock()
        orchestrator._report_generator.persist_report = MagicMock()

        await orchestrator._persist_partial_results(
            channel_reports=[],
            total_channels=5,
        )

        orchestrator._report_generator.persist_report.assert_not_called()


# ============================================================
# Test: exit_code property
# ============================================================


class TestExitCode:
    """Testes de exit code."""

    def test_default_exit_code_zero(self) -> None:
        """Exit code padrão é 0 (clean shutdown)."""
        orchestrator = _make_orchestrator()
        assert orchestrator.exit_code == 0

    @pytest.mark.asyncio
    async def test_exit_code_one_on_error(self) -> None:
        """Exit code 1 quando erro fatal no modo contínuo."""
        orchestrator = _make_orchestrator()
        orchestrator._report_generator = MagicMock()
        orchestrator._report_generator.persist_report = MagicMock()
        orchestrator._report_generator.create_consolidated_report = (
            MagicMock(
                return_value=ConsolidatedReport(
                    timestamp="2024-01-01T00:00:00Z",
                    total_channels=0,
                )
            )
        )

        # Mock _run_channel_session para lançar erro fatal
        orchestrator._run_channel_session = AsyncMock(
            side_effect=RuntimeError("Erro simulado")
        )

        # Simular que o run_single_rotation lança exceção
        # (que propagaria para run_continuous)
        async def failing_rotation(channels):
            raise RuntimeError("Erro fatal simulado")

        orchestrator.run_single_rotation = AsyncMock(
            side_effect=failing_rotation
        )

        exit_code = await orchestrator.run_continuous(
            ["https://ch1.com/live"]
        )

        assert exit_code == 1

    @pytest.mark.asyncio
    async def test_exit_code_zero_on_clean_shutdown(self) -> None:
        """Exit code 0 em clean shutdown."""
        orchestrator = _make_orchestrator()
        orchestrator._report_generator = MagicMock()
        orchestrator._report_generator.persist_report = MagicMock()
        orchestrator._report_generator.create_consolidated_report = (
            MagicMock(
                return_value=ConsolidatedReport(
                    timestamp="2024-01-01T00:00:00Z",
                    total_channels=1,
                    channels_pass=1,
                )
            )
        )

        # Simular shutdown após primeira rotação
        call_count = [0]

        async def mock_rotation(channels):
            call_count[0] += 1
            if call_count[0] >= 1:
                orchestrator._shutting_down = True
            return ConsolidatedReport(
                timestamp="2024-01-01T00:00:00Z",
                total_channels=1,
                channels_pass=1,
            )

        orchestrator.run_single_rotation = AsyncMock(
            side_effect=mock_rotation
        )

        exit_code = await orchestrator.run_continuous(
            ["https://ch1.com/live"]
        )

        assert exit_code == 0


# ============================================================
# Test: run_single_rotation com shutdown
# ============================================================


class TestRotationWithShutdown:
    """Testes de rotação interrompida por shutdown."""

    @pytest.mark.asyncio
    async def test_rotation_stops_between_channels_on_shutdown(
        self,
    ) -> None:
        """Rotação para entre canais quando _shutting_down = True."""
        orchestrator = _make_orchestrator()
        orchestrator._report_generator = MagicMock()
        orchestrator._report_generator.persist_report = MagicMock()
        orchestrator._report_generator.create_consolidated_report = (
            MagicMock(
                return_value=ConsolidatedReport(
                    timestamp="2024-01-01T00:00:00Z",
                    total_channels=3,
                    channels_pass=1,
                    is_partial=True,
                )
            )
        )

        call_count = [0]

        async def mock_session(url: str):
            call_count[0] += 1
            # Após primeiro canal, setar shutdown
            orchestrator._shutting_down = True
            return _make_report(url)

        orchestrator._run_channel_session = AsyncMock(
            side_effect=mock_session
        )

        channels = [
            "https://ch1.com/live",
            "https://ch2.com/live",
            "https://ch3.com/live",
        ]

        result = await orchestrator.run_single_rotation(channels)

        # Apenas 1 canal processado (para no check após retorno)
        assert call_count[0] == 1

    @pytest.mark.asyncio
    async def test_partial_consolidated_report_on_shutdown(
        self,
    ) -> None:
        """Relatório consolidado marcado como parcial no shutdown."""
        orchestrator = _make_orchestrator()
        orchestrator._shutting_down = True  # Shutdown antes de iniciar

        orchestrator._report_generator = MagicMock()
        consolidated = ConsolidatedReport(
            timestamp="2024-01-01T00:00:00Z",
            total_channels=0,
        )
        orchestrator._report_generator.create_consolidated_report = (
            MagicMock(return_value=consolidated)
        )
        orchestrator._report_generator.persist_report = MagicMock()

        channels = [
            "https://ch1.com/live",
            "https://ch2.com/live",
        ]

        result = await orchestrator.run_single_rotation(channels)

        # Deve ser marcado como parcial (0 processados < 2 total)
        assert result.is_partial is True

    @pytest.mark.asyncio
    async def test_partial_report_filename_includes_partial(
        self,
    ) -> None:
        """Filename do relatório parcial inclui 'PARTIAL'."""
        orchestrator = _make_orchestrator()
        orchestrator._shutting_down = True

        orchestrator._report_generator = MagicMock()
        consolidated = ConsolidatedReport(
            timestamp="2024-01-01T00:00:00Z",
            total_channels=0,
        )
        orchestrator._report_generator.create_consolidated_report = (
            MagicMock(return_value=consolidated)
        )
        orchestrator._report_generator.persist_report = MagicMock()

        await orchestrator.run_single_rotation(
            ["https://ch1.com/live"]
        )

        # Verificar que o filename contém PARTIAL
        call_args = (
            orchestrator._report_generator.persist_report.call_args
        )
        kwargs = call_args[1] if call_args[1] else {}
        if "filename" in kwargs:
            assert "PARTIAL" in kwargs["filename"]
        else:
            # Positional arg
            filename = call_args[0][1]
            assert "PARTIAL" in filename


# ============================================================
# Property Test: Shutdown preserves all collected data
# Feature: unified-channel-monitor, Property 12: Shutdown preserves all collected data
# ============================================================


from hypothesis import given, settings, strategies as st


class TestShutdownPreservesDataProperty:
    """Property 12: Shutdown preserves all collected data.

    **Validates: Requirements 12.2, 12.4**

    Para qualquer shutdown disparado durante uma rotação com K canais
    completados, o relatório consolidado persistido deve conter
    exatamente K reports e ser marcado como parcial.
    """

    @pytest.mark.asyncio
    @settings(max_examples=100)
    @given(
        n_total=st.integers(min_value=2, max_value=12),
        k_completed=st.integers(min_value=1, max_value=11),
    )
    async def test_shutdown_preserves_k_completed_reports(
        self, n_total: int, k_completed: int
    ) -> None:
        """Shutdown após K canais gera relatório parcial com K reports.

        Verifica que:
        1. ConsolidatedReport tem exatamente K channel_reports
        2. is_partial = True (pois shutdown interrompeu antes de
           processar todos os canais)
        3. Todos os K reports têm status válido
           (PASS/PARTIAL/FAIL/UNREACHABLE/ERROR)
        4. persist_report foi chamado com os dados do relatório
        """
        # Ajustar k_completed para ser <= n_total - 1
        # (pelo menos 1 canal não processado para ser parcial)
        k_completed = min(k_completed, n_total - 1)

        # Gerar lista de canais
        channels = [
            f"https://channel{i}.example.com/live"
            for i in range(n_total)
        ]

        # Criar orchestrator
        orchestrator = _make_orchestrator()

        # Contador de chamadas para controlar shutdown
        call_count = [0]

        async def mock_session(url: str) -> UnifiedChannelReport:
            call_count[0] += 1
            # Após K canais completarem, setar shutdown
            if call_count[0] >= k_completed:
                orchestrator._shutting_down = True
            return _make_report(url, status="PASS")

        orchestrator._run_channel_session = AsyncMock(
            side_effect=mock_session
        )

        # Mock do report generator para capturar chamadas
        mock_generator = MagicMock()
        # create_consolidated_report deve retornar um
        # ConsolidatedReport real baseado nos reports recebidos
        def fake_consolidated(channel_reports):
            return ConsolidatedReport(
                timestamp="2024-01-01T00:00:00Z",
                total_channels=len(channel_reports),
                channels_pass=sum(
                    1 for r in channel_reports
                    if r.status == "PASS"
                ),
                channel_reports=channel_reports,
            )

        mock_generator.create_consolidated_report = MagicMock(
            side_effect=fake_consolidated
        )
        mock_generator.persist_report = MagicMock()
        orchestrator._report_generator = mock_generator

        # Executar rotação
        result = await orchestrator.run_single_rotation(channels)

        # Verificação 1: Exatamente K reports no resultado
        assert len(result.channel_reports) == k_completed, (
            f"Esperado {k_completed} reports, "
            f"obteve {len(result.channel_reports)}"
        )

        # Verificação 2: is_partial = True
        assert result.is_partial is True, (
            f"Relatório deveria ser parcial "
            f"({k_completed}/{n_total} canais processados)"
        )

        # Verificação 3: Todos os reports têm status válido
        valid_statuses = {"PASS", "PARTIAL", "FAIL",
                         "UNREACHABLE", "ERROR"}
        for report in result.channel_reports:
            assert report.status in valid_statuses, (
                f"Status inválido: {report.status}"
            )

        # Verificação 4: persist_report foi chamado
        mock_generator.persist_report.assert_called_once()

        # Verificar que o filename contém PARTIAL
        call_args = mock_generator.persist_report.call_args
        kwargs = call_args[1] if call_args[1] else {}
        if "filename" in kwargs:
            assert "PARTIAL" in kwargs["filename"], (
                "Filename deveria conter 'PARTIAL'"
            )
        else:
            filename = call_args[0][1]
            assert "PARTIAL" in filename, (
                "Filename deveria conter 'PARTIAL'"
            )
