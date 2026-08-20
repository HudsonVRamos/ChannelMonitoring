"""Testes unitários para o ReportGenerator."""
from __future__ import annotations

import json
import os
from typing import Optional

import pytest

from src.models import (
    GoNoGoDecision,
    PerformanceMetrics,
    PoCReport,
    ValidationResult,
    ValidationStatus,
)
from src.report_generator import (
    CRITICAL_VALIDATIONS,
    DEPENDENCY_MAP,
    ReportGenerator,
)


def _make_validation(
    name: str,
    status: ValidationStatus = ValidationStatus.PASS,
    duration_ms: int = 1000,
    error_message: Optional[str] = None,
    evidence_paths: Optional[list] = None,
    metrics: Optional[dict] = None,
    skipped_reason: Optional[str] = None,
) -> ValidationResult:
    """Cria um ValidationResult para testes."""
    return ValidationResult(
        name=name,
        status=status,
        start_time="2024-01-15T10:00:00.000Z",
        end_time="2024-01-15T10:00:01.000Z",
        duration_ms=duration_ms,
        error_message=error_message,
        evidence_paths=evidence_paths or [],
        metrics=metrics or {},
        skipped_reason=skipped_reason,
    )


def _make_all_pass_results() -> list[ValidationResult]:
    """Cria lista de resultados com todas as validações PASS."""
    return [
        _make_validation("login", metrics={"browser_init_time_ms": 2500}),
        _make_validation("drm", metrics={"drm_ready_time_ms": 5000}),
        _make_validation("telemetry"),
        _make_validation("frames", metrics={"time_per_frame_ms": 150}),
        _make_validation("opencv"),
        _make_validation("bedrock", metrics={"bedrock_response_time_ms": 800}),
        _make_validation("docker"),
    ]


class TestReportGeneratorGenerate:
    """Testes do método generate."""

    def test_generate_produces_poc_report(self):
        """generate deve produzir um PoCReport válido."""
        generator = ReportGenerator(log_file_path="/tmp/test.log")
        results = _make_all_pass_results()

        report = generator.generate(results)

        assert isinstance(report, PoCReport)
        assert report.execution_id  # UUID não vazio
        assert report.start_time
        assert report.end_time
        assert report.total_duration_ms > 0
        assert report.log_file_path == "/tmp/test.log"

    def test_generate_includes_all_validations(self):
        """Relatório deve conter todas as validações fornecidas."""
        generator = ReportGenerator()
        results = _make_all_pass_results()

        report = generator.generate(results)

        assert len(report.validations) == len(results)
        names = {v.name for v in report.validations}
        assert "login" in names
        assert "drm" in names
        assert "docker" in names

    def test_generate_unique_execution_id(self):
        """Cada chamada a generate deve produzir execution_id único."""
        generator = ReportGenerator()
        results = _make_all_pass_results()

        report1 = generator.generate(results)
        report2 = generator.generate(results)

        assert report1.execution_id != report2.execution_id

    def test_generate_with_empty_results(self):
        """generate com lista vazia deve produzir relatório válido."""
        generator = ReportGenerator()

        report = generator.generate([])

        assert isinstance(report, PoCReport)
        assert report.validations == []
        assert report.total_duration_ms == 0

    def test_generate_extracts_performance_metrics(self):
        """generate deve extrair métricas de performance dos resultados."""
        generator = ReportGenerator()
        results = _make_all_pass_results()

        report = generator.generate(results)

        assert report.performance.browser_init_time_ms == 2500
        assert report.performance.drm_ready_time_ms == 5000
        assert report.performance.time_per_frame_ms == 150
        assert report.performance.bedrock_response_time_ms == 800

    def test_generate_includes_environment_info(self):
        """Relatório deve incluir informações de ambiente."""
        generator = ReportGenerator()
        results = _make_all_pass_results()

        report = generator.generate(results)

        assert "python_version" in report.environment


class TestReportGeneratorClassifyGoNogo:
    """Testes do método classify_go_nogo."""

    def test_go_when_all_critical_pass(self):
        """GO quando login, drm, frames e docker são PASS."""
        generator = ReportGenerator()
        results = _make_all_pass_results()
        report = generator.generate(results)

        decision = generator.classify_go_nogo(report)

        assert decision == GoNoGoDecision.GO

    def test_no_go_when_login_fails(self):
        """NO_GO quando login falha."""
        generator = ReportGenerator()
        results = _make_all_pass_results()
        results[0] = _make_validation("login", status=ValidationStatus.FAIL, error_message="Auth timeout")

        report = generator.generate(results)

        assert report.decision == GoNoGoDecision.NO_GO

    def test_no_go_when_drm_fails(self):
        """NO_GO quando DRM falha."""
        generator = ReportGenerator()
        results = _make_all_pass_results()
        results[1] = _make_validation("drm", status=ValidationStatus.FAIL, error_message="CDM error")

        report = generator.generate(results)

        assert report.decision == GoNoGoDecision.NO_GO

    def test_no_go_when_frames_fail(self):
        """NO_GO quando frames falha."""
        generator = ReportGenerator()
        results = _make_all_pass_results()
        results[3] = _make_validation("frames", status=ValidationStatus.FAIL, error_message="Black screen")

        report = generator.generate(results)

        assert report.decision == GoNoGoDecision.NO_GO

    def test_no_go_when_docker_fails(self):
        """NO_GO quando Docker falha."""
        generator = ReportGenerator()
        results = _make_all_pass_results()
        results[6] = _make_validation("docker", status=ValidationStatus.FAIL, error_message="CDM init")

        report = generator.generate(results)

        assert report.decision == GoNoGoDecision.NO_GO

    def test_no_go_when_critical_is_skipped(self):
        """NO_GO quando validação crítica está SKIPPED."""
        generator = ReportGenerator()
        results = _make_all_pass_results()
        results[1] = _make_validation(
            "drm",
            status=ValidationStatus.SKIPPED,
            skipped_reason="Dependência falhou: login",
        )

        report = generator.generate(results)

        assert report.decision == GoNoGoDecision.NO_GO

    def test_go_when_non_critical_fails(self):
        """GO mesmo quando validação não-crítica (bedrock) falha."""
        generator = ReportGenerator()
        results = _make_all_pass_results()
        results[5] = _make_validation(
            "bedrock", status=ValidationStatus.FAIL, error_message="Timeout"
        )

        report = generator.generate(results)

        assert report.decision == GoNoGoDecision.GO

    def test_no_go_when_critical_missing(self):
        """NO_GO quando validação crítica não está presente."""
        generator = ReportGenerator()
        # Apenas login e telemetry — falta drm, frames, docker
        results = [
            _make_validation("login"),
            _make_validation("telemetry"),
        ]

        report = generator.generate(results)

        assert report.decision == GoNoGoDecision.NO_GO


class TestReportGeneratorSaveReport:
    """Testes do método save_report."""

    def test_save_report_creates_json_file(self, tmp_path):
        """save_report deve criar arquivo JSON válido."""
        generator = ReportGenerator()
        results = _make_all_pass_results()
        report = generator.generate(results)

        output_path = str(tmp_path / "report.json")
        generator.save_report(report, output_path)

        assert os.path.exists(output_path)
        with open(output_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert data["execution_id"] == report.execution_id
        assert data["decision"] == "GO"
        assert len(data["validations"]) == 7

    def test_save_report_serializes_enums_as_values(self, tmp_path):
        """Enums devem ser serializados como seus valores string."""
        generator = ReportGenerator()
        results = [
            _make_validation("login", status=ValidationStatus.PASS),
            _make_validation("drm", status=ValidationStatus.FAIL, error_message="Erro"),
            _make_validation("frames", status=ValidationStatus.PASS),
            _make_validation("docker", status=ValidationStatus.PASS),
        ]
        report = generator.generate(results)

        output_path = str(tmp_path / "report.json")
        generator.save_report(report, output_path)

        with open(output_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Verificar que enums estão como string
        assert data["decision"] == "NO_GO"
        statuses = [v["status"] for v in data["validations"]]
        assert "PASS" in statuses
        assert "FAIL" in statuses

    def test_save_report_creates_directory_if_missing(self, tmp_path):
        """save_report deve criar diretório de saída se não existir."""
        generator = ReportGenerator()
        results = _make_all_pass_results()
        report = generator.generate(results)

        output_path = str(tmp_path / "subdir" / "nested" / "report.json")
        generator.save_report(report, output_path)

        assert os.path.exists(output_path)

    def test_save_report_includes_error_and_evidence_for_fail(self, tmp_path):
        """Para FAIL, relatório deve conter error_message e evidence_paths."""
        generator = ReportGenerator()
        results = [
            _make_validation("login"),
            _make_validation(
                "drm",
                status=ValidationStatus.FAIL,
                error_message="CDM initialization failed",
                evidence_paths=["/output/drm_error.png", "/output/drm.log"],
            ),
            _make_validation("frames"),
            _make_validation("docker"),
        ]
        report = generator.generate(results)

        output_path = str(tmp_path / "report.json")
        generator.save_report(report, output_path)

        with open(output_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        drm_validation = next(v for v in data["validations"] if v["name"] == "drm")
        assert drm_validation["error_message"] == "CDM initialization failed"
        assert "/output/drm_error.png" in drm_validation["evidence_paths"]
        assert "/output/drm.log" in drm_validation["evidence_paths"]

    def test_save_report_includes_performance_metrics(self, tmp_path):
        """Relatório salvo deve incluir métricas de performance."""
        generator = ReportGenerator()
        results = _make_all_pass_results()
        report = generator.generate(results)

        output_path = str(tmp_path / "report.json")
        generator.save_report(report, output_path)

        with open(output_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        perf = data["performance"]
        assert perf["browser_init_time_ms"] == 2500
        assert perf["drm_ready_time_ms"] == 5000
        assert perf["time_per_frame_ms"] == 150
        assert perf["bedrock_response_time_ms"] == 800

    def test_save_report_includes_log_file_path(self, tmp_path):
        """Relatório salvo deve incluir caminho para log completo."""
        generator = ReportGenerator(log_file_path="/var/log/poc_execution.log")
        results = _make_all_pass_results()
        report = generator.generate(results)

        output_path = str(tmp_path / "report.json")
        generator.save_report(report, output_path)

        with open(output_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert data["log_file_path"] == "/var/log/poc_execution.log"


class TestReportGeneratorSkipLogic:
    """Testes da lógica de skip por dependência."""

    def test_skip_drm_when_login_fails(self):
        """DRM deve ser SKIPPED quando login falha."""
        generator = ReportGenerator()
        results = [
            _make_validation("login", status=ValidationStatus.FAIL, error_message="Auth error"),
            _make_validation("drm", status=ValidationStatus.FAIL, error_message="Not executed"),
            _make_validation("frames", status=ValidationStatus.FAIL),
            _make_validation("docker"),
        ]

        report = generator.generate(results)

        drm = next(v for v in report.validations if v.name == "drm")
        assert drm.status == ValidationStatus.SKIPPED
        assert "login" in drm.skipped_reason

    def test_skip_opencv_when_frames_fail(self):
        """OpenCV deve ser SKIPPED quando frames falha."""
        generator = ReportGenerator()
        results = [
            _make_validation("login"),
            _make_validation("drm"),
            _make_validation("frames", status=ValidationStatus.FAIL, error_message="Black screen"),
            _make_validation("opencv", status=ValidationStatus.FAIL),
            _make_validation("docker"),
        ]

        report = generator.generate(results)

        opencv = next(v for v in report.validations if v.name == "opencv")
        assert opencv.status == ValidationStatus.SKIPPED
        assert "frames" in opencv.skipped_reason

    def test_skip_bedrock_when_opencv_fails(self):
        """Bedrock deve ser SKIPPED quando opencv falha."""
        generator = ReportGenerator()
        results = [
            _make_validation("login"),
            _make_validation("drm"),
            _make_validation("frames"),
            _make_validation("opencv", status=ValidationStatus.FAIL),
            _make_validation("bedrock", status=ValidationStatus.FAIL),
            _make_validation("docker"),
        ]

        report = generator.generate(results)

        bedrock = next(v for v in report.validations if v.name == "bedrock")
        assert bedrock.status == ValidationStatus.SKIPPED
        assert "opencv" in bedrock.skipped_reason

    def test_no_skip_when_dependencies_pass(self):
        """Validações não devem ser marcadas SKIPPED se dependências passam."""
        generator = ReportGenerator()
        results = _make_all_pass_results()

        report = generator.generate(results)

        for v in report.validations:
            assert v.status != ValidationStatus.SKIPPED

    def test_already_skipped_with_reason_preserved(self):
        """Validações já SKIPPED com motivo devem ser preservadas."""
        generator = ReportGenerator()
        results = [
            _make_validation("login"),
            _make_validation("drm"),
            _make_validation("frames"),
            _make_validation(
                "opencv",
                status=ValidationStatus.SKIPPED,
                skipped_reason="Manual skip: OpenCV not installed",
            ),
            _make_validation("docker"),
        ]

        report = generator.generate(results)

        opencv = next(v for v in report.validations if v.name == "opencv")
        assert opencv.status == ValidationStatus.SKIPPED
        assert opencv.skipped_reason == "Manual skip: OpenCV not installed"
