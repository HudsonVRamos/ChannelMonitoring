"""Gerador de relatórios consolidados da PoC.

Produz relatório PoCReport com status de cada validação,
decisão Go/No-Go, métricas de performance e referências
para logs e evidências.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from src.models import (
    GoNoGoDecision,
    PerformanceMetrics,
    PoCReport,
    ValidationResult,
    ValidationStatus,
)
from src.structured_logger import StructuredLogger

# Validações consideradas críticas para decisão Go/No-Go
CRITICAL_VALIDATIONS = {"login", "drm", "frames", "docker"}

# Mapa de dependências entre validações
# Se uma dependência falha, as validações dependentes são marcadas como SKIPPED
DEPENDENCY_MAP: dict[str, list[str]] = {
    "drm": ["login"],
    "telemetry": ["login", "drm"],
    "frames": ["login", "drm"],
    "opencv": ["login", "drm", "frames"],
    "bedrock": ["login", "drm", "frames", "opencv"],
}

STAGE_ID = "report_generator"


class ReportGenerator:
    """Gera relatório consolidado da PoC com decisão Go/No-Go."""

    def __init__(self, log_file_path: str = "", logger: Optional[StructuredLogger] = None) -> None:
        """Inicializa o gerador de relatórios.

        Args:
            log_file_path: Caminho para o arquivo de log completo da execução.
            logger: Instância do StructuredLogger. Se não fornecido, cria um novo.
        """
        self._logger = logger or StructuredLogger()
        self._log_file_path = log_file_path

    def generate(self, results: list[ValidationResult]) -> PoCReport:
        """Gera relatório consolidado com status de cada validação.

        Processa a lista de ValidationResult, marca validações com dependências
        falhas como SKIPPED, extrai métricas de performance e produz o PoCReport
        final com decisão Go/No-Go.

        Args:
            results: Lista de resultados de validação individuais.

        Returns:
            PoCReport consolidado com todas as informações.
        """
        self._logger.info(STAGE_ID, "Iniciando geração do relatório", total_validations=len(results))

        execution_id = str(uuid.uuid4())

        # Marcar validações com dependências falhas como SKIPPED
        processed_results = self._apply_skip_logic(results)

        # Extrair métricas de performance dos resultados
        performance = self._extract_performance_metrics(processed_results)

        # Calcular timestamps e duração total
        start_time, end_time, total_duration_ms = self._calculate_timing(processed_results)

        # Coletar informações de ambiente
        environment = self._collect_environment_info()

        # Construir relatório
        report = PoCReport(
            execution_id=execution_id,
            start_time=start_time,
            end_time=end_time,
            total_duration_ms=total_duration_ms,
            decision=GoNoGoDecision.GO,  # Placeholder, será classificado abaixo
            validations=processed_results,
            performance=performance,
            log_file_path=self._log_file_path,
            environment=environment,
        )

        # Classificar decisão Go/No-Go
        report.decision = self.classify_go_nogo(report)

        self._logger.info(
            STAGE_ID,
            "Relatório gerado com sucesso",
            execution_id=execution_id,
            decision=report.decision.value,
            total_duration_ms=total_duration_ms,
        )

        return report

    def classify_go_nogo(self, report: PoCReport) -> GoNoGoDecision:
        """Classifica resultado geral como GO ou NO_GO.

        Regras:
        - GO: Todas as validações críticas (login, drm, frames, docker) têm status PASS.
        - NO_GO: Qualquer validação crítica tem status FAIL ou SKIPPED.

        Args:
            report: Relatório com as validações processadas.

        Returns:
            GoNoGoDecision.GO ou GoNoGoDecision.NO_GO.
        """
        critical_results: dict[str, ValidationStatus] = {}

        for validation in report.validations:
            if validation.name in CRITICAL_VALIDATIONS:
                critical_results[validation.name] = validation.status

        # Verificar se todas as críticas foram executadas
        missing_criticals = CRITICAL_VALIDATIONS - set(critical_results.keys())
        if missing_criticals:
            self._logger.warning(
                STAGE_ID,
                "Validações críticas não encontradas no relatório",
                missing=list(missing_criticals),
            )
            return GoNoGoDecision.NO_GO

        # GO somente se TODAS as críticas são PASS
        for name, status in critical_results.items():
            if status != ValidationStatus.PASS:
                self._logger.info(
                    STAGE_ID,
                    "Decisão NO_GO: validação crítica não passou",
                    validation=name,
                    status=status.value,
                )
                return GoNoGoDecision.NO_GO

        self._logger.info(STAGE_ID, "Decisão GO: todas as validações críticas passaram")
        return GoNoGoDecision.GO

    def save_report(self, report: PoCReport, output_path: str) -> None:
        """Salva relatório em formato JSON.

        Serializa o PoCReport completo para um arquivo JSON, tratando
        enums e dataclasses corretamente.

        Args:
            report: Relatório a ser salvo.
            output_path: Caminho do arquivo de saída.
        """
        self._logger.info(STAGE_ID, "Salvando relatório", output_path=output_path)

        # Garantir que o diretório de saída existe
        output_dir = os.path.dirname(output_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

        # Serializar relatório
        report_dict = self._serialize_report(report)

        # Escrever JSON formatado
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report_dict, f, ensure_ascii=False, indent=2, default=str)

        self._logger.info(
            STAGE_ID,
            "Relatório salvo com sucesso",
            output_path=output_path,
            size_bytes=os.path.getsize(output_path),
        )

    def _apply_skip_logic(self, results: list[ValidationResult]) -> list[ValidationResult]:
        """Marca validações com dependências falhas como SKIPPED.

        Verifica o mapa de dependências e marca validações cujas
        dependências falharam como SKIPPED com motivo indicando
        qual dependência impediu a execução.

        Args:
            results: Lista original de resultados.

        Returns:
            Lista de resultados com lógica de skip aplicada.
        """
        # Criar mapa de status por nome
        status_map: dict[str, ValidationStatus] = {}
        for result in results:
            status_map[result.name] = result.status

        processed: list[ValidationResult] = []

        for result in results:
            # Se já está SKIPPED com motivo, manter
            if result.status == ValidationStatus.SKIPPED and result.skipped_reason:
                processed.append(result)
                continue

            # Verificar dependências
            dependencies = DEPENDENCY_MAP.get(result.name, [])
            failed_deps = [
                dep for dep in dependencies
                if status_map.get(dep) in (ValidationStatus.FAIL, ValidationStatus.SKIPPED)
            ]

            if failed_deps and result.status != ValidationStatus.PASS:
                # Marcar como SKIPPED com motivo
                skipped_result = ValidationResult(
                    name=result.name,
                    status=ValidationStatus.SKIPPED,
                    start_time=result.start_time,
                    end_time=result.end_time,
                    duration_ms=result.duration_ms,
                    error_message=result.error_message,
                    evidence_paths=result.evidence_paths,
                    metrics=result.metrics,
                    skipped_reason=f"Dependência falhou: {', '.join(failed_deps)}",
                )
                self._logger.info(
                    STAGE_ID,
                    "Validação marcada como SKIPPED por dependência",
                    validation=result.name,
                    failed_dependencies=failed_deps,
                )
                processed.append(skipped_result)
            else:
                processed.append(result)

        return processed

    def _extract_performance_metrics(self, results: list[ValidationResult]) -> PerformanceMetrics:
        """Extrai métricas de performance dos resultados de validação.

        Procura nos metrics de cada ValidationResult por métricas
        de performance relevantes (browser_init_time, drm_ready_time,
        time_per_frame, bedrock_response_time).

        Args:
            results: Lista de resultados processados.

        Returns:
            PerformanceMetrics com valores extraídos ou defaults.
        """
        browser_init_time_ms = 0
        drm_ready_time_ms = 0
        time_per_frame_ms = 0
        bedrock_response_time_ms: Optional[int] = None

        for result in results:
            metrics = result.metrics

            # Extrair browser_init_time do login/auth
            if result.name == "login" and "browser_init_time_ms" in metrics:
                browser_init_time_ms = int(metrics["browser_init_time_ms"])

            # Extrair drm_ready_time do DRM
            if result.name == "drm" and "drm_ready_time_ms" in metrics:
                drm_ready_time_ms = int(metrics["drm_ready_time_ms"])

            # Extrair time_per_frame dos frames
            if result.name == "frames" and "time_per_frame_ms" in metrics:
                time_per_frame_ms = int(metrics["time_per_frame_ms"])

            # Extrair bedrock_response_time do bedrock
            if result.name == "bedrock" and "bedrock_response_time_ms" in metrics:
                bedrock_response_time_ms = int(metrics["bedrock_response_time_ms"])

        return PerformanceMetrics(
            browser_init_time_ms=browser_init_time_ms,
            drm_ready_time_ms=drm_ready_time_ms,
            time_per_frame_ms=time_per_frame_ms,
            bedrock_response_time_ms=bedrock_response_time_ms,
        )

    def _calculate_timing(
        self, results: list[ValidationResult]
    ) -> tuple[str, str, int]:
        """Calcula timestamps de início, fim e duração total.

        Args:
            results: Lista de resultados com timestamps.

        Returns:
            Tupla (start_time, end_time, total_duration_ms).
        """
        if not results:
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + "000Z"
            return now, now, 0

        start_time = min(r.start_time for r in results)
        end_time = max(r.end_time for r in results)
        total_duration_ms = sum(r.duration_ms for r in results)

        return start_time, end_time, total_duration_ms

    def _collect_environment_info(self) -> dict:
        """Coleta informações de ambiente para o relatório.

        Returns:
            Dicionário com versões de componentes do sistema.
        """
        import sys

        environment: dict = {
            "python_version": sys.version.split()[0],
        }

        # Tentar coletar versão do Playwright
        try:
            import playwright
            environment["playwright_version"] = getattr(playwright, "__version__", "unknown")
        except ImportError:
            environment["playwright_version"] = "not_installed"

        # Tentar coletar versão do OpenCV
        try:
            import cv2
            environment["opencv_version"] = cv2.__version__
        except ImportError:
            environment["opencv_version"] = "not_installed"

        # Tentar coletar versão do numpy
        try:
            import numpy
            environment["numpy_version"] = numpy.__version__
        except ImportError:
            environment["numpy_version"] = "not_installed"

        return environment

    def _serialize_report(self, report: PoCReport) -> dict:
        """Serializa PoCReport para dicionário JSON-compatível.

        Trata enums usando .value e dataclasses usando asdict,
        com tratamento especial para tipos complexos.

        Args:
            report: Relatório a ser serializado.

        Returns:
            Dicionário pronto para serialização JSON.
        """
        return {
            "execution_id": report.execution_id,
            "start_time": report.start_time,
            "end_time": report.end_time,
            "total_duration_ms": report.total_duration_ms,
            "decision": report.decision.value,
            "validations": [
                self._serialize_validation(v) for v in report.validations
            ],
            "performance": {
                "browser_init_time_ms": report.performance.browser_init_time_ms,
                "drm_ready_time_ms": report.performance.drm_ready_time_ms,
                "time_per_frame_ms": report.performance.time_per_frame_ms,
                "bedrock_response_time_ms": report.performance.bedrock_response_time_ms,
            },
            "log_file_path": report.log_file_path,
            "environment": report.environment,
        }

    def _serialize_validation(self, validation: ValidationResult) -> dict:
        """Serializa um ValidationResult para dicionário.

        Args:
            validation: Resultado de validação individual.

        Returns:
            Dicionário com campos do resultado.
        """
        result: dict = {
            "name": validation.name,
            "status": validation.status.value,
            "start_time": validation.start_time,
            "end_time": validation.end_time,
            "duration_ms": validation.duration_ms,
        }

        if validation.error_message is not None:
            result["error_message"] = validation.error_message

        if validation.evidence_paths:
            result["evidence_paths"] = validation.evidence_paths

        if validation.metrics:
            result["metrics"] = validation.metrics

        if validation.skipped_reason is not None:
            result["skipped_reason"] = validation.skipped_reason

        return result
