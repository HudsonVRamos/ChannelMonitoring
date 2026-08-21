"""Gerador de relatórios unificados para o Channel Monitor.

Responsável por:
- Gerar UnifiedChannelReport por canal (video + áudio + legendas + escalações)
- Gerar ConsolidatedReport por rotação com contagens por status
- Persistir relatórios como JSON no diretório de output configurado
- Gerar session_id (UUID) por Channel Session para correlação de logs
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from src.unified_channel_monitor.models import (
    AudioTrackResult,
    ChannelSessionStatus,
    ConsolidatedReport,
    EscalationResult,
    SubtitleTrackResult,
    TelemetrySummary,
    UnifiedChannelReport,
)

logger = logging.getLogger(__name__)


class UnifiedReportGenerator:
    """Gera UnifiedReport por canal e ConsolidatedReport por rotação.

    Cada Channel Session recebe um session_id (UUID) único para
    correlação de logs e rastreabilidade entre componentes.
    """

    def __init__(self, output_dir: str = "reports/") -> None:
        """Inicializa o gerador de relatórios.

        Args:
            output_dir: Diretório de saída para persistência
                dos relatórios JSON.
        """
        self._output_dir = Path(output_dir)

    def create_channel_report(
        self,
        channel_url: str,
        video_summary: TelemetrySummary,
        audio_results: list[AudioTrackResult],
        subtitle_results: list[SubtitleTrackResult],
        escalation_results: list[EscalationResult],
        duration_ms: int,
    ) -> UnifiedChannelReport:
        """Cria relatório unificado para um canal.

        Agrega video summary, resultados de áudio, resultados de legendas
        e escalações em um único UnifiedChannelReport com session_id único.

        Args:
            channel_url: URL do canal monitorado.
            video_summary: Resumo da telemetria de vídeo coletada.
            audio_results: Resultados individuais por track de áudio.
            subtitle_results: Resultados individuais por track de legenda.
            escalation_results: Resultados de escalações processadas.
            duration_ms: Duração total da Channel Session em milissegundos.

        Returns:
            UnifiedChannelReport com todos os dados agregados.
        """
        session_id = str(uuid.uuid4())
        channel_id = self._derive_channel_id(channel_url)
        timestamp = datetime.now(timezone.utc).isoformat()

        # Contagens de áudio
        audio_tracks_tested = len(audio_results)
        audio_tracks_passed = sum(
            1 for r in audio_results if r.status == "PASS"
        )

        # Contagens de legendas
        subtitle_tracks_tested = len(subtitle_results)
        subtitle_tracks_passed = sum(
            1 for r in subtitle_results if r.status == "PASS"
        )

        # Calcular status da sessão
        status = self._calculate_channel_status(
            video_summary=video_summary,
            audio_results=audio_results,
            subtitle_results=subtitle_results,
            audio_tracks_passed=audio_tracks_passed,
            subtitle_tracks_passed=subtitle_tracks_passed,
        )

        # Coletar anotações de telemetria
        telemetry_annotations = list(video_summary.annotations)

        report = UnifiedChannelReport(
            channel_url=channel_url,
            channel_id=channel_id,
            session_id=session_id,
            timestamp=timestamp,
            status=status,
            duration_ms=duration_ms,
            video_summary=video_summary,
            audio_tracks_tested=audio_tracks_tested,
            audio_tracks_passed=audio_tracks_passed,
            audio_results=audio_results,
            subtitle_tracks_tested=subtitle_tracks_tested,
            subtitle_tracks_passed=subtitle_tracks_passed,
            subtitle_results=subtitle_results,
            escalation_results=escalation_results,
            telemetry_annotations=telemetry_annotations,
        )

        logger.info(
            "Relatório de canal gerado",
            extra={
                "session_id": session_id,
                "channel_url": channel_url,
                "status": status,
                "audio_tested": audio_tracks_tested,
                "audio_passed": audio_tracks_passed,
                "subtitle_tested": subtitle_tracks_tested,
                "subtitle_passed": subtitle_tracks_passed,
            },
        )

        return report

    def create_consolidated_report(
        self,
        channel_reports: list[UnifiedChannelReport],
    ) -> ConsolidatedReport:
        """Cria relatório consolidado de uma rotação completa.

        Agrega todos os UnifiedChannelReports com contagens por status
        para visão geral rápida da rotação.

        Args:
            channel_reports: Lista de relatórios individuais por canal.

        Returns:
            ConsolidatedReport com contagens por status e totais.
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        total_channels = len(channel_reports)

        # Contagem por status
        channels_pass = sum(
            1 for r in channel_reports
            if r.status == ChannelSessionStatus.PASS.value
        )
        channels_partial = sum(
            1 for r in channel_reports
            if r.status == ChannelSessionStatus.PARTIAL.value
        )
        channels_fail = sum(
            1 for r in channel_reports
            if r.status == ChannelSessionStatus.FAIL.value
        )
        channels_unreachable = sum(
            1 for r in channel_reports
            if r.status == ChannelSessionStatus.UNREACHABLE.value
        )
        channels_error = sum(
            1 for r in channel_reports
            if r.status == ChannelSessionStatus.ERROR.value
        )

        # Duração total
        total_duration_ms = sum(r.duration_ms for r in channel_reports)

        report = ConsolidatedReport(
            timestamp=timestamp,
            total_channels=total_channels,
            channels_pass=channels_pass,
            channels_partial=channels_partial,
            channels_fail=channels_fail,
            channels_unreachable=channels_unreachable,
            channels_error=channels_error,
            total_duration_ms=total_duration_ms,
            channel_reports=channel_reports,
        )

        logger.info(
            "Relatório consolidado gerado",
            extra={
                "total_channels": total_channels,
                "pass": channels_pass,
                "partial": channels_partial,
                "fail": channels_fail,
                "unreachable": channels_unreachable,
                "error": channels_error,
                "total_duration_ms": total_duration_ms,
            },
        )

        return report

    def persist_report(self, report: dict, filename: str) -> Path:
        """Serializa e persiste relatório como JSON no diretório de output.

        Cria o diretório de saída caso não exista. Usa formatação legível
        com indentação e suporte a caracteres Unicode.

        Args:
            report: Dicionário com os dados do relatório
                (já convertido de dataclass).
            filename: Nome do arquivo de saída
                (ex: 'report_2024-01-01T12-00-00.json').

        Returns:
            Path do arquivo JSON gerado.
        """
        # Criar diretório de output se não existir
        self._output_dir.mkdir(parents=True, exist_ok=True)

        filepath = self._output_dir / filename

        json_content = json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
            default=str,
        )

        filepath.write_text(json_content, encoding="utf-8")

        logger.info(
            "Relatório persistido",
            extra={"filepath": str(filepath), "filename": filename},
        )

        return filepath

    def _calculate_channel_status(
        self,
        video_summary: TelemetrySummary,
        audio_results: list[AudioTrackResult],
        subtitle_results: list[SubtitleTrackResult],
        audio_tracks_passed: int,
        subtitle_tracks_passed: int,
    ) -> str:
        """Calcula o status final da Channel Session.

        Lógica de classificação:
        - PASS: todos os testes de áudio/legendas passaram
          E vídeo HEALTHY/SUSPECT
        - PARTIAL: alguns testes passaram, outros falharam
        - FAIL: maioria dos testes falhou
          OU vídeo DEGRADED/CRITICAL

        Args:
            video_summary: Resumo da telemetria de vídeo.
            audio_results: Resultados dos testes de áudio.
            subtitle_results: Resultados dos testes de legenda.
            audio_tracks_passed: Número de tracks de áudio que passaram.
            subtitle_tracks_passed: Número de tracks de legenda que passaram.

        Returns:
            Status como string: PASS, PARTIAL ou FAIL.
        """
        health = video_summary.health_classification.upper()
        video_degraded = health in ("DEGRADED", "CRITICAL")

        # Filtrar tracks efetivamente testados (excluir SKIPs)
        audio_tested = [r for r in audio_results if r.status != "SKIP"]
        subtitle_tested = [r for r in subtitle_results if r.status != "SKIP"]

        total_tested = len(audio_tested) + len(subtitle_tested)
        total_passed = audio_tracks_passed + subtitle_tracks_passed

        # Se vídeo está degradado/crítico → FAIL
        if video_degraded:
            return ChannelSessionStatus.FAIL.value

        # Se não há tracks testados, status baseado apenas no vídeo
        if total_tested == 0:
            if health in ("HEALTHY", "SUSPECT"):
                return ChannelSessionStatus.PASS.value
            return ChannelSessionStatus.FAIL.value

        # Todos os testes passaram E vídeo saudável
        if total_passed == total_tested and health in ("HEALTHY", "SUSPECT"):
            return ChannelSessionStatus.PASS.value

        # Nenhum passou ou maioria falhou
        total_failed = total_tested - total_passed
        if total_passed == 0 or total_failed > total_tested // 2:
            return ChannelSessionStatus.FAIL.value

        # Caso intermediário: alguns passaram, outros falharam
        return ChannelSessionStatus.PARTIAL.value

    @staticmethod
    def _derive_channel_id(channel_url: str) -> str:
        """Deriva identificador do canal a partir da URL.

        Usa o último segmento do path da URL. Se o path estiver vazio
        ou for apenas '/', usa o hostname completo.

        Args:
            channel_url: URL do canal.

        Returns:
            Identificador derivado da URL.
        """
        parsed = urlparse(channel_url)
        path = parsed.path.rstrip("/")

        if path:
            # Último segmento do path
            return path.split("/")[-1]

        # Fallback: usar hostname
        if parsed.hostname:
            return parsed.hostname

        # Último fallback: URL completa como ID
        return channel_url
