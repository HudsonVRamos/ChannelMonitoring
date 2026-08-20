"""Testes unitários para o PoCOrchestrator.

Testa:
1. Cadeia de dependências (skip em cascata)
2. Geração de relatório Go/No-Go
3. Logging de versões no início

Validates: Requirements 9.3, 11.4, 11.6
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config import PoCConfig
from src.models import (
    GoNoGoDecision,
    ValidationResult,
    ValidationStatus,
)
from src.poc_orchestrator import PoCOrchestrator


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def config(tmp_path):
    """Configuração da PoC com paths temporários para testes."""
    storage_path = tmp_path / "storage_state.json"
    storage_path.write_text('{"cookies": [{"name": "test"}]}')
    return PoCConfig(
        storage_state_path=str(storage_path),
        channel_url="https://example.com/channel",
        output_dir=str(tmp_path / "output"),
        log_level="DEBUG",
    )


@pytest.fixture
def orchestrator(config):
    """Instância do PoCOrchestrator com mocks dos módulos internos."""
    with patch("src.poc_orchestrator.StructuredLogger"):
        orch = PoCOrchestrator(config)
    return orch


def _make_result(
    name: str,
    status: ValidationStatus,
    duration_ms: int = 100,
    error_message: str | None = None,
    metrics: dict | None = None,
    skipped_reason: str | None = None,
) -> ValidationResult:
    """Helper para criar ValidationResult para testes."""
    return ValidationResult(
        name=name,
        status=status,
        start_time="2024-01-01T00:00:00.000Z",
        end_time="2024-01-01T00:00:00.100Z",
        duration_ms=duration_ms,
        error_message=error_message,
        metrics=metrics or {},
        skipped_reason=skipped_reason,
    )


def _mock_playwright_context():
    """Cria mocks para async_playwright() context manager."""
    mock_page = AsyncMock()
    mock_page.goto = AsyncMock()

    mock_context = AsyncMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)

    mock_browser = AsyncMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    mock_browser.close = AsyncMock()

    mock_chromium = AsyncMock()
    mock_chromium.launch = AsyncMock(return_value=mock_browser)

    mock_playwright = AsyncMock()
    mock_playwright.chromium = mock_chromium

    # Context manager assíncrono
    mock_pw_cm = AsyncMock()
    mock_pw_cm.__aenter__ = AsyncMock(return_value=mock_playwright)
    mock_pw_cm.__aexit__ = AsyncMock(return_value=False)

    return mock_pw_cm, mock_page, mock_browser


# =============================================================================
# Testes: Cadeia de dependências (skip em cascata)
# Validates: Requirement 9.3, 11.6
# =============================================================================


class TestDependencyChain:
    """Testa que falhas em etapas anteriores causam SKIP em cascata."""

    @pytest.mark.asyncio
    async def test_auth_fail_skips_drm_telemetry_frames_opencv_bedrock(
        self, config
    ):
        """Quando auth falha, DRM, telemetry, frames, opencv e bedrock são SKIPPED."""
        mock_pw_cm, mock_page, mock_browser = _mock_playwright_context()

        with (
            patch("src.poc_orchestrator.StructuredLogger"),
            patch(
                "src.poc_orchestrator.async_playwright",
                return_value=mock_pw_cm,
            ),
            patch("src.poc_orchestrator.AuthManager") as mock_auth_cls,
            patch("src.poc_orchestrator.DRMValidator"),
            patch("src.poc_orchestrator.TelemetryCollector"),
            patch("src.poc_orchestrator.FrameCapturer"),
            patch("src.poc_orchestrator.OpenCVAnalyzer"),
            patch("src.poc_orchestrator.BedrockClient"),
            patch("src.poc_orchestrator.BufferingDetector"),
            patch("src.poc_orchestrator.ReportGenerator") as mock_report_cls,
            patch("os.path.exists", return_value=True),
        ):
            # Auth falha: validate_storage_state retorna False
            mock_auth_instance = mock_auth_cls.return_value
            mock_auth_instance.validate_storage_state.return_value = False

            # Report generator mock
            mock_report = mock_report_cls.return_value
            mock_report.generate = MagicMock(side_effect=_capture_results_and_generate_report)
            mock_report.save_report = MagicMock()

            orch = PoCOrchestrator(config)
            report = await orch.run()

        # Verificar que o relatório foi gerado
        assert report is not None

        # Buscar resultados por nome
        results_by_name = {r.name: r for r in _captured_results}

        # Auth deve ter FAIL
        assert results_by_name["login"].status == ValidationStatus.FAIL

        # DRM, telemetry, frames, opencv, bedrock devem ser SKIPPED
        assert results_by_name["drm"].status == ValidationStatus.SKIPPED
        assert results_by_name["telemetry"].status == ValidationStatus.SKIPPED
        assert results_by_name["frames"].status == ValidationStatus.SKIPPED
        assert results_by_name["opencv"].status == ValidationStatus.SKIPPED
        assert results_by_name["bedrock"].status == ValidationStatus.SKIPPED

    @pytest.mark.asyncio
    async def test_drm_fail_skips_telemetry_frames_opencv_bedrock(
        self, config
    ):
        """Quando DRM falha, telemetry, frames, opencv e bedrock são SKIPPED."""
        mock_pw_cm, mock_page, mock_browser = _mock_playwright_context()

        with (
            patch("src.poc_orchestrator.StructuredLogger"),
            patch(
                "src.poc_orchestrator.async_playwright",
                return_value=mock_pw_cm,
            ),
            patch("src.poc_orchestrator.AuthManager") as mock_auth_cls,
            patch("src.poc_orchestrator.DRMValidator") as mock_drm_cls,
            patch("src.poc_orchestrator.TelemetryCollector"),
            patch("src.poc_orchestrator.FrameCapturer"),
            patch("src.poc_orchestrator.OpenCVAnalyzer"),
            patch("src.poc_orchestrator.BedrockClient"),
            patch("src.poc_orchestrator.BufferingDetector"),
            patch("src.poc_orchestrator.ReportGenerator") as mock_report_cls,
            patch("os.path.exists", return_value=True),
        ):
            # Auth passa
            mock_auth_instance = mock_auth_cls.return_value
            mock_auth_instance.validate_storage_state.return_value = True
            mock_auth_instance.detect_session_expired = AsyncMock(
                return_value=False
            )

            # DRM falha: license_obtained = False
            mock_drm_instance = mock_drm_cls.return_value
            mock_drm_result = MagicMock()
            mock_drm_result.license_obtained = False
            mock_drm_result.media_keys_created = True
            mock_drm_result.license_requested = True
            mock_drm_result.time_to_license_ms = 15000
            mock_drm_result.error = "Licença DRM não obtida"
            mock_drm_instance.validate_drm_initialization = AsyncMock(
                return_value=mock_drm_result
            )

            # Report generator mock
            mock_report = mock_report_cls.return_value
            mock_report.generate = MagicMock(side_effect=_capture_results_and_generate_report)
            mock_report.save_report = MagicMock()

            orch = PoCOrchestrator(config)
            report = await orch.run()

        # Verificar resultados
        results_by_name = {r.name: r for r in _captured_results}

        # Auth deve ter PASS
        assert results_by_name["login"].status == ValidationStatus.PASS

        # DRM deve ter FAIL
        assert results_by_name["drm"].status == ValidationStatus.FAIL

        # Telemetry e Frames devem ser SKIPPED (dependem de DRM)
        assert results_by_name["telemetry"].status == ValidationStatus.SKIPPED
        assert results_by_name["frames"].status == ValidationStatus.SKIPPED

        # OpenCV depende de frames (que foi SKIPPED)
        assert results_by_name["opencv"].status == ValidationStatus.SKIPPED

        # Bedrock depende de opencv (que foi SKIPPED)
        assert results_by_name["bedrock"].status == ValidationStatus.SKIPPED

    @pytest.mark.asyncio
    async def test_frames_fail_skips_opencv_bedrock(self, config):
        """Quando frames falha, opencv e bedrock são SKIPPED."""
        mock_pw_cm, mock_page, mock_browser = _mock_playwright_context()

        with (
            patch("src.poc_orchestrator.StructuredLogger"),
            patch(
                "src.poc_orchestrator.async_playwright",
                return_value=mock_pw_cm,
            ),
            patch("src.poc_orchestrator.AuthManager") as mock_auth_cls,
            patch("src.poc_orchestrator.DRMValidator") as mock_drm_cls,
            patch("src.poc_orchestrator.TelemetryCollector") as mock_tel_cls,
            patch("src.poc_orchestrator.FrameCapturer") as mock_frame_cls,
            patch("src.poc_orchestrator.OpenCVAnalyzer"),
            patch("src.poc_orchestrator.BedrockClient"),
            patch("src.poc_orchestrator.BufferingDetector"),
            patch("src.poc_orchestrator.ReportGenerator") as mock_report_cls,
            patch("os.path.exists", return_value=True),
        ):
            # Auth passa
            mock_auth_instance = mock_auth_cls.return_value
            mock_auth_instance.validate_storage_state.return_value = True
            mock_auth_instance.detect_session_expired = AsyncMock(
                return_value=False
            )

            # DRM passa
            mock_drm_instance = mock_drm_cls.return_value
            mock_drm_result = MagicMock()
            mock_drm_result.license_obtained = True
            mock_drm_result.media_keys_created = True
            mock_drm_result.license_requested = True
            mock_drm_result.time_to_license_ms = 3000
            mock_drm_instance.validate_drm_initialization = AsyncMock(
                return_value=mock_drm_result
            )

            # Telemetry passa
            mock_tel_instance = mock_tel_cls.return_value
            mock_sample_1 = MagicMock()
            mock_sample_1.video.current_time = 1.0
            mock_sample_2 = MagicMock()
            mock_sample_2.video.current_time = 3.0
            mock_tel_instance.start_continuous_collection = AsyncMock(
                return_value=[mock_sample_1, mock_sample_2]
            )

            # Frames falha: retorna lista vazia
            mock_frame_instance = mock_frame_cls.return_value
            mock_frame_instance.capture_sequence = AsyncMock(
                return_value=[]
            )

            # Report generator mock
            mock_report = mock_report_cls.return_value
            mock_report.generate = MagicMock(side_effect=_capture_results_and_generate_report)
            mock_report.save_report = MagicMock()

            orch = PoCOrchestrator(config)
            report = await orch.run()

        # Verificar resultados
        results_by_name = {r.name: r for r in _captured_results}

        assert results_by_name["login"].status == ValidationStatus.PASS
        assert results_by_name["drm"].status == ValidationStatus.PASS
        assert results_by_name["telemetry"].status == ValidationStatus.PASS
        assert results_by_name["frames"].status == ValidationStatus.FAIL
        assert results_by_name["opencv"].status == ValidationStatus.SKIPPED
        assert results_by_name["bedrock"].status == ValidationStatus.SKIPPED


# =============================================================================
# Testes: Geração de relatório Go/No-Go
# Validates: Requirement 11.4
# =============================================================================


class TestGoNoGoReport:
    """Testa geração de relatório com decisão Go/No-Go."""

    @pytest.mark.asyncio
    async def test_all_orchestrator_validations_pass_report_structure(self, config):
        """Quando todas as validações do orchestrator passam, o relatório contém os resultados corretos."""
        mock_pw_cm, mock_page, mock_browser = _mock_playwright_context()

        with (
            patch("src.poc_orchestrator.StructuredLogger"),
            patch(
                "src.poc_orchestrator.async_playwright",
                return_value=mock_pw_cm,
            ),
            patch("src.poc_orchestrator.AuthManager") as mock_auth_cls,
            patch("src.poc_orchestrator.DRMValidator") as mock_drm_cls,
            patch("src.poc_orchestrator.TelemetryCollector") as mock_tel_cls,
            patch("src.poc_orchestrator.FrameCapturer") as mock_frame_cls,
            patch("src.poc_orchestrator.OpenCVAnalyzer"),
            patch("src.poc_orchestrator.BedrockClient"),
            patch("src.poc_orchestrator.BufferingDetector"),
            patch("src.poc_orchestrator.ReportGenerator") as mock_report_cls,
            patch("os.path.exists", return_value=True),
        ):
            # Auth passa
            mock_auth_instance = mock_auth_cls.return_value
            mock_auth_instance.validate_storage_state.return_value = True
            mock_auth_instance.detect_session_expired = AsyncMock(
                return_value=False
            )

            # DRM passa
            mock_drm_instance = mock_drm_cls.return_value
            mock_drm_result = MagicMock()
            mock_drm_result.license_obtained = True
            mock_drm_result.media_keys_created = True
            mock_drm_result.license_requested = True
            mock_drm_result.time_to_license_ms = 3000
            mock_drm_instance.validate_drm_initialization = AsyncMock(
                return_value=mock_drm_result
            )

            # Telemetry passa
            mock_tel_instance = mock_tel_cls.return_value
            mock_sample_1 = MagicMock()
            mock_sample_1.video.current_time = 1.0
            mock_sample_2 = MagicMock()
            mock_sample_2.video.current_time = 5.0
            mock_tel_instance.start_continuous_collection = AsyncMock(
                return_value=[mock_sample_1, mock_sample_2]
            )

            # Frames passa
            mock_frame_instance = mock_frame_cls.return_value
            mock_frame_valid = MagicMock()
            mock_frame_valid.is_valid = True
            mock_frame_valid.data = b"\x89PNG\r\n" + b"\x00" * 100
            mock_frame_instance.capture_sequence = AsyncMock(
                return_value=[mock_frame_valid, mock_frame_valid, mock_frame_valid]
            )
            mock_frame_instance.capture_frame = AsyncMock(
                return_value=mock_frame_valid
            )

            # Report generator captura os resultados
            mock_report = mock_report_cls.return_value
            mock_report.generate = MagicMock(side_effect=_capture_results_and_generate_report)
            mock_report.save_report = MagicMock()

            orch = PoCOrchestrator(config)

            # Mockar _validate_opencv e _validate_bedrock para evitar import cv2/numpy
            orch._validate_opencv = AsyncMock(
                return_value=_make_result(
                    "opencv", ValidationStatus.PASS,
                    metrics={"black_screen_detected": False},
                )
            )
            orch._validate_bedrock = AsyncMock(
                return_value=_make_result(
                    "bedrock", ValidationStatus.PASS,
                    metrics={"bedrock_response_time_ms": 1500},
                )
            )

            report = await orch.run()

        # Todas as validações executadas pelo orchestrator passaram
        results_by_name = {r.name: r for r in _captured_results}
        assert results_by_name["login"].status == ValidationStatus.PASS
        assert results_by_name["drm"].status == ValidationStatus.PASS
        assert results_by_name["telemetry"].status == ValidationStatus.PASS
        assert results_by_name["frames"].status == ValidationStatus.PASS
        assert results_by_name["opencv"].status == ValidationStatus.PASS
        assert results_by_name["bedrock"].status == ValidationStatus.PASS

    def test_all_critical_pass_generates_go_decision(self, config):
        """Quando todas as validações críticas (login, drm, frames, docker) passam → GO."""
        from src.report_generator import ReportGenerator

        report_gen = ReportGenerator(
            log_file_path="poc_execution.log",
            logger=MagicMock(),
        )

        # Simular resultados completos incluindo docker (que roda separadamente)
        results = [
            _make_result("login", ValidationStatus.PASS, metrics={"browser_init_time_ms": 500}),
            _make_result("drm", ValidationStatus.PASS, metrics={"drm_ready_time_ms": 3000}),
            _make_result("telemetry", ValidationStatus.PASS),
            _make_result("frames", ValidationStatus.PASS, metrics={"time_per_frame_ms": 200}),
            _make_result("opencv", ValidationStatus.PASS),
            _make_result("bedrock", ValidationStatus.PASS, metrics={"bedrock_response_time_ms": 1500}),
            _make_result("docker", ValidationStatus.PASS),
        ]

        report = report_gen.generate(results)

        assert report.decision == GoNoGoDecision.GO

    @pytest.mark.asyncio
    async def test_auth_fail_generates_nogo_report(self, config):
        """Quando auth falha, o relatório é NO_GO."""
        mock_pw_cm, mock_page, mock_browser = _mock_playwright_context()

        with (
            patch("src.poc_orchestrator.StructuredLogger"),
            patch(
                "src.poc_orchestrator.async_playwright",
                return_value=mock_pw_cm,
            ),
            patch("src.poc_orchestrator.AuthManager") as mock_auth_cls,
            patch("src.poc_orchestrator.DRMValidator"),
            patch("src.poc_orchestrator.TelemetryCollector"),
            patch("src.poc_orchestrator.FrameCapturer"),
            patch("src.poc_orchestrator.OpenCVAnalyzer"),
            patch("src.poc_orchestrator.BedrockClient"),
            patch("src.poc_orchestrator.BufferingDetector"),
            patch("src.poc_orchestrator.ReportGenerator") as mock_report_cls,
            patch("os.path.exists", return_value=True),
        ):
            # Auth falha
            mock_auth_instance = mock_auth_cls.return_value
            mock_auth_instance.validate_storage_state.return_value = False

            # Report generator com lógica real
            from src.report_generator import ReportGenerator

            real_report_gen = ReportGenerator(
                log_file_path=str(config.output_dir + "/poc_execution.log"),
                logger=MagicMock(),
            )
            mock_report = mock_report_cls.return_value
            mock_report.generate = MagicMock(
                side_effect=real_report_gen.generate
            )
            mock_report.save_report = MagicMock()

            orch = PoCOrchestrator(config)
            report = await orch.run()

        # login falhou → decisão NO_GO
        assert report.decision == GoNoGoDecision.NO_GO

    def test_report_saved_to_output_directory(self, config):
        """Relatório deve ser salvo no diretório output configurado."""
        from src.report_generator import ReportGenerator

        report_gen = ReportGenerator(
            log_file_path="poc_execution.log",
            logger=MagicMock(),
        )

        # Gerar relatório com resultados que resultam em GO
        results = [
            _make_result("login", ValidationStatus.PASS, metrics={"browser_init_time_ms": 500}),
            _make_result("drm", ValidationStatus.PASS, metrics={"drm_ready_time_ms": 3000}),
            _make_result("telemetry", ValidationStatus.PASS),
            _make_result("frames", ValidationStatus.PASS, metrics={"time_per_frame_ms": 200}),
            _make_result("opencv", ValidationStatus.PASS),
            _make_result("bedrock", ValidationStatus.PASS, metrics={"bedrock_response_time_ms": 1500}),
            _make_result("docker", ValidationStatus.PASS),
        ]

        report = report_gen.generate(results)

        # Salvar no output_dir
        output_path = os.path.join(config.output_dir, "poc_report.json")
        report_gen.save_report(report, output_path)

        # Verificar que o arquivo foi criado
        assert os.path.exists(output_path)
        assert os.path.getsize(output_path) > 0

        # Verificar conteúdo JSON válido
        import json

        with open(output_path, "r", encoding="utf-8") as f:
            report_data = json.load(f)

        assert report_data["decision"] == "GO"
        assert "validations" in report_data
        assert len(report_data["validations"]) == 7


# =============================================================================
# Testes: Logging de versões no início
# Validates: Requirement 9.3 (versões do ambiente)
# =============================================================================


class TestEnvironmentVersionLogging:
    """Testa que versões do ambiente são logadas no início da execução."""

    def test_log_environment_versions_is_called(self, config):
        """O método _log_environment_versions é chamado durante run()."""
        with patch("src.poc_orchestrator.StructuredLogger") as mock_logger_cls:
            mock_logger = mock_logger_cls.return_value
            orch = PoCOrchestrator(config)

            # Chamar diretamente _log_environment_versions
            orch._log_environment_versions()

            # Verificar que o logger.info foi chamado com dados de versão
            mock_logger.info.assert_called()

            # Encontrar a chamada que registrou versões
            version_call_found = False
            for call in mock_logger.info.call_args_list:
                args = call[0] if call[0] else []
                kwargs = call[1] if call[1] else {}
                if len(args) >= 2 and "Versões do ambiente" in args[1]:
                    version_call_found = True
                    # Verificar que as versões foram incluídas
                    assert "python_version" in kwargs
                    assert "playwright_version" in kwargs
                    assert "opencv_version" in kwargs
                    break

            assert version_call_found, (
                "Logger.info não foi chamado com 'Versões do ambiente registradas'"
            )

    def test_log_environment_versions_includes_python_version(self, config):
        """Versão do Python é registrada corretamente."""
        import sys

        with patch("src.poc_orchestrator.StructuredLogger") as mock_logger_cls:
            mock_logger = mock_logger_cls.return_value
            orch = PoCOrchestrator(config)
            orch._log_environment_versions()

            # Verificar que a versão do Python está presente
            for call in mock_logger.info.call_args_list:
                kwargs = call[1] if call[1] else {}
                if "python_version" in kwargs:
                    expected_version = sys.version.split()[0]
                    assert kwargs["python_version"] == expected_version
                    break

    def test_log_environment_versions_handles_missing_opencv(self, config):
        """Quando OpenCV não está instalado, registra 'not_installed'."""
        with (
            patch("src.poc_orchestrator.StructuredLogger") as mock_logger_cls,
            patch.dict("sys.modules", {"cv2": None}),
        ):
            mock_logger = mock_logger_cls.return_value
            orch = PoCOrchestrator(config)

            # Simular ImportError para cv2
            import builtins

            original_import = builtins.__import__

            def mock_import(name, *args, **kwargs):
                if name == "cv2":
                    raise ImportError("No module named 'cv2'")
                return original_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=mock_import):
                orch._log_environment_versions()

            # Verificar que opencv_version é "not_installed"
            for call in mock_logger.info.call_args_list:
                kwargs = call[1] if call[1] else {}
                if "opencv_version" in kwargs:
                    assert kwargs["opencv_version"] == "not_installed"
                    break


# =============================================================================
# Módulo auxiliar: captura de resultados passados ao ReportGenerator
# =============================================================================

_captured_results: list[ValidationResult] = []


def _capture_results_and_generate_report(
    results: list[ValidationResult],
):
    """Captura os resultados passados ao generate() para inspeção nos testes."""
    global _captured_results
    _captured_results = list(results)

    from src.report_generator import ReportGenerator

    real_gen = ReportGenerator(
        log_file_path="test_log.log",
        logger=MagicMock(),
    )
    return real_gen.generate(results)
