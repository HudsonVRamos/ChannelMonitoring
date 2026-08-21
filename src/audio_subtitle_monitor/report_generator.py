"""Gerador de relatórios consolidados de testes de áudio e legendas.

Este módulo implementa a classe ReportGenerator, responsável por:
- Criar relatórios individuais por canal (ChannelTestReport)
- Calcular o status geral (overall_status) a partir dos resultados de tracks
- Criar relatório consolidado multi-canal (ConsolidatedReport)
- Serializar e salvar relatórios em JSON no diretório de output
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

from .models import (
    ChannelTestReport,
    ConsolidatedReport,
    OverallStatus,
    TrackTestResult,
    TrackTestStatus,
)

logger = logging.getLogger(__name__)


class ReportGenerator:
    """Gera relatórios consolidados de testes de áudio e legendas.

    Attributes:
        _output_dir: Diretório onde os relatórios JSON serão salvos.
    """

    def __init__(self, output_dir: str) -> None:
        """Inicializa o gerador de relatórios.

        Args:
            output_dir: Caminho do diretório de saída para os relatórios.
                       Será criado automaticamente se não existir.
        """
        self._output_dir = output_dir
        os.makedirs(self._output_dir, exist_ok=True)
        logger.info("ReportGenerator inicializado com output_dir=%s", output_dir)

    def create_channel_report(
        self,
        channel_url: str,
        audio_results: list[TrackTestResult],
        subtitle_results: list[TrackTestResult],
        duration_ms: int,
    ) -> ChannelTestReport:
        """Cria um relatório de testes para um canal específico.

        Extrai o channel_id da URL, calcula o overall_status a partir de todos
        os resultados (áudio + legendas) e coleta as opções descobertas.

        Args:
            channel_url: URL completa do canal testado.
            audio_results: Lista de resultados de testes de tracks de áudio.
            subtitle_results: Lista de resultados de testes de tracks de legendas.
            duration_ms: Duração total da sessão de testes em milissegundos.

        Returns:
            ChannelTestReport com todos os dados consolidados.
        """
        # Extrair channel_id do último segmento da URL
        channel_id = channel_url.rstrip("/").split("/")[-1]

        # Gerar timestamp ISO 8601 em UTC
        timestamp = datetime.now(timezone.utc).isoformat()

        # Calcular overall_status combinando todos os resultados
        all_results = audio_results + subtitle_results
        overall_status = self._calculate_overall_status(all_results)

        # Coletar opções descobertas (nomes dos tracks)
        audio_options_discovered = [r.track_name for r in audio_results]
        subtitle_options_discovered = [r.track_name for r in subtitle_results]

        report = ChannelTestReport(
            channel_url=channel_url,
            channel_id=channel_id,
            timestamp=timestamp,
            audio_results=audio_results,
            subtitle_results=subtitle_results,
            overall_status=overall_status,
            duration_ms=duration_ms,
            audio_options_discovered=audio_options_discovered,
            subtitle_options_discovered=subtitle_options_discovered,
        )

        logger.info(
            "Relatório criado para canal %s: overall_status=%s",
            channel_id,
            overall_status.value,
        )
        return report

    def _calculate_overall_status(
        self, results: list[TrackTestResult]
    ) -> OverallStatus:
        """Calcula o status geral a partir dos resultados individuais.

        Regras:
        - Se lista vazia: PASS (sem testes = sem falhas)
        - Se TODOS os statuses são PASS: PASS
        - Se TODOS os statuses são FAIL ou TIMEOUT (nenhum PASS): FAIL
        - Caso contrário (mistura): PARTIAL

        Args:
            results: Lista de resultados de testes de tracks.

        Returns:
            OverallStatus calculado (PASS, PARTIAL ou FAIL).
        """
        if not results:
            return OverallStatus.PASS

        statuses = [r.status for r in results]

        # Verificar se todos são PASS
        if all(s == TrackTestStatus.PASS for s in statuses):
            return OverallStatus.PASS

        # Verificar se todos são FAIL ou TIMEOUT (sem nenhum PASS)
        fail_timeout_statuses = {TrackTestStatus.FAIL, TrackTestStatus.TIMEOUT}
        if all(s in fail_timeout_statuses for s in statuses):
            return OverallStatus.FAIL

        # Caso misto
        return OverallStatus.PARTIAL

    def create_consolidated_report(
        self, channel_reports: list[ChannelTestReport]
    ) -> ConsolidatedReport:
        """Cria um relatório consolidado de todos os canais testados.

        Agrega contadores de status e duração total a partir dos relatórios
        individuais de cada canal.

        Args:
            channel_reports: Lista de relatórios individuais por canal.

        Returns:
            ConsolidatedReport com contadores e dados agregados.
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        total_channels = len(channel_reports)
        channels_pass = sum(
            1 for r in channel_reports if r.overall_status == OverallStatus.PASS
        )
        channels_partial = sum(
            1 for r in channel_reports if r.overall_status == OverallStatus.PARTIAL
        )
        channels_fail = sum(
            1 for r in channel_reports if r.overall_status == OverallStatus.FAIL
        )
        total_duration_ms = sum(r.duration_ms for r in channel_reports)

        report = ConsolidatedReport(
            timestamp=timestamp,
            total_channels=total_channels,
            channels_pass=channels_pass,
            channels_partial=channels_partial,
            channels_fail=channels_fail,
            total_duration_ms=total_duration_ms,
            channel_reports=channel_reports,
        )

        logger.info(
            "Relatório consolidado: %d canais (pass=%d, partial=%d, fail=%d)",
            total_channels,
            channels_pass,
            channels_partial,
            channels_fail,
        )
        return report

    def save_channel_report(self, report: ChannelTestReport) -> str:
        """Serializa e salva o relatório de canal em arquivo JSON.

        O nome do arquivo segue o formato:
        audio_subtitle_report_{channel_id}_{timestamp_safe}.json

        O timestamp é formatado de forma filesystem-safe, substituindo
        caracteres inválidos para nomes de arquivo.

        Args:
            report: ChannelTestReport a ser salvo.

        Returns:
            Caminho completo do arquivo salvo.
        """
        # Formatar timestamp como filesystem-safe
        safe_timestamp = report.timestamp.replace(":", "-").replace(" ", "_")

        filename = (
            f"audio_subtitle_report_{report.channel_id}_{safe_timestamp}.json"
        )
        filepath = os.path.join(self._output_dir, filename)

        # Serializar e salvar
        content = json.dumps(report.to_dict(), indent=2, ensure_ascii=False)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)

        logger.info("Relatório salvo em: %s", filepath)
        return filepath
