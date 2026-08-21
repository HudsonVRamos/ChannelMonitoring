"""Testes unitários para o CLI entry point (run.py).

Valida:
- Parsing da flag --continuous
- Saída com exit code 1 quando não há canais configurados
- Saída com exit code 1 quando o browser falha ao lançar
- Setup de logging estruturado
- Execução de rotação única vs contínua

Requirements: 1.1, 1.2, 1.3, 1.5, 1.6
"""

from __future__ import annotations

import logging
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.unified_channel_monitor.run import _setup_logging, main


class TestSetupLogging:
    """Testes para configuração de logging."""

    def test_setup_logging_info_level(self) -> None:
        """Deve configurar logging com nível INFO."""
        _setup_logging("INFO")
        root_logger = logging.getLogger()
        assert root_logger.level == logging.INFO

    def test_setup_logging_debug_level(self) -> None:
        """Deve configurar logging com nível DEBUG."""
        _setup_logging("DEBUG")
        root_logger = logging.getLogger()
        assert root_logger.level == logging.DEBUG

    def test_setup_logging_invalid_level_defaults_info(
        self,
    ) -> None:
        """Nível inválido deve resultar em INFO."""
        _setup_logging("INVALIDO")
        root_logger = logging.getLogger()
        assert root_logger.level == logging.INFO


class TestMainNoChannels:
    """Testes para validação de canais."""

    @pytest.mark.asyncio
    async def test_exit_code_1_when_no_channels(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Deve sair com exit code 1 se nenhum canal configurado."""
        monkeypatch.delenv(
            "UNIFIED_MONITOR_CHANNELS", raising=False
        )
        monkeypatch.setattr(sys, "argv", ["run.py"])

        with pytest.raises(SystemExit) as exc_info:
            await main()

        assert exc_info.value.code == 1


def _create_mock_playwright_context():
    """Cria mocks para o async context manager do Playwright."""
    mock_page = AsyncMock()
    mock_browser = AsyncMock()
    mock_browser.pages = [mock_page]
    mock_browser.close = AsyncMock()

    mock_pw_instance = AsyncMock()
    mock_pw_instance.chromium.launch_persistent_context = (
        AsyncMock(return_value=mock_browser)
    )

    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(
        return_value=mock_pw_instance
    )
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    return mock_cm, mock_browser, mock_page


class TestMainContinuousFlag:
    """Testes para parsing da flag --continuous."""

    @pytest.mark.asyncio
    async def test_continuous_flag_parsed_from_argv(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Flag --continuous deve ativar modo contínuo."""
        monkeypatch.setenv(
            "UNIFIED_MONITOR_CHANNELS",
            "https://example.com/ch1",
        )
        monkeypatch.setattr(
            sys, "argv", ["run.py", "--continuous"]
        )

        mock_cm, _, _ = _create_mock_playwright_context()

        with patch(
            "src.unified_channel_monitor.run.async_playwright",
            return_value=mock_cm,
        ):
            with patch.object(
                __import__(
                    "src.unified_channel_monitor.orchestrator",
                    fromlist=["UnifiedOrchestrator"],
                ).UnifiedOrchestrator,
                "run_continuous",
                new_callable=AsyncMock,
                return_value=0,
            ) as mock_continuous:
                with patch.object(
                    __import__(
                        "src.unified_channel_monitor.orchestrator",
                        fromlist=["UnifiedOrchestrator"],
                    ).UnifiedOrchestrator,
                    "register_signal_handlers",
                ):
                    with pytest.raises(SystemExit) as exc_info:
                        await main()

                    mock_continuous.assert_called_once()
                    assert exc_info.value.code == 0

    @pytest.mark.asyncio
    async def test_single_rotation_without_flag(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Sem flag --continuous deve executar rotação única."""
        monkeypatch.setenv(
            "UNIFIED_MONITOR_CHANNELS",
            "https://example.com/ch1",
        )
        monkeypatch.setattr(sys, "argv", ["run.py"])

        mock_cm, _, _ = _create_mock_playwright_context()
        mock_report = MagicMock()

        with patch(
            "src.unified_channel_monitor.run.async_playwright",
            return_value=mock_cm,
        ):
            with patch.object(
                __import__(
                    "src.unified_channel_monitor.orchestrator",
                    fromlist=["UnifiedOrchestrator"],
                ).UnifiedOrchestrator,
                "run_single_rotation",
                new_callable=AsyncMock,
                return_value=mock_report,
            ) as mock_single:
                with patch.object(
                    __import__(
                        "src.unified_channel_monitor.orchestrator",
                        fromlist=["UnifiedOrchestrator"],
                    ).UnifiedOrchestrator,
                    "register_signal_handlers",
                ):
                    with pytest.raises(SystemExit) as exc_info:
                        await main()

                    mock_single.assert_called_once()
                    assert exc_info.value.code == 0


class TestMainBrowserFailure:
    """Testes para falha no lançamento do browser."""

    @pytest.mark.asyncio
    async def test_exit_code_1_on_browser_launch_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Deve sair com exit code 1 se browser falhar ao lançar."""
        monkeypatch.setenv(
            "UNIFIED_MONITOR_CHANNELS",
            "https://example.com/ch1",
        )
        monkeypatch.setattr(sys, "argv", ["run.py"])

        mock_pw_instance = AsyncMock()
        mock_pw_instance.chromium.launch_persistent_context = (
            AsyncMock(
                side_effect=Exception("Chrome não encontrado")
            )
        )

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(
            return_value=mock_pw_instance
        )
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "src.unified_channel_monitor.run.async_playwright",
            return_value=mock_cm,
        ):
            with pytest.raises(SystemExit) as exc_info:
                await main()

            assert exc_info.value.code == 1
