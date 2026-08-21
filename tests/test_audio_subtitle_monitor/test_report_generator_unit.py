"""Unit tests para ReportGenerator.

Testa:
- Cálculo de overall_status com combinações diversas
- Serialização JSON com chaves obrigatórias
- Geração de filename com caracteres especiais
- save_channel_report cria arquivo no diretório correto
- Contadores do relatório consolidado

Requirements: 7.1, 7.2, 7.3, 7.4
"""

from __future__ import annotations

import json
import os

import pytest

from src.audio_subtitle_monitor.models import (
    ChannelTestReport,
    OverallStatus,
    TrackTestResult,
    TrackTestStatus,
)
from src.audio_subtitle_monitor.report_generator import ReportGenerator


# ============================================================
# Helpers
# ============================================================


def make_result(
    status: TrackTestStatus,
    name: str = "Test",
    track_type: str = "audio",
) -> TrackTestResult:
    """Cria um TrackTestResult para testes."""
    return TrackTestResult(
        track_name=name,
        track_type=track_type,
        status=status,
        evidence={"reason": "test"},
        duration_ms=1000,
    )


@pytest.fixture
def report_gen(tmp_path):
    """ReportGenerator com diretório temporário."""
    return ReportGenerator(output_dir=str(tmp_path))


# ============================================================
# Testes de overall_status
# ============================================================


class TestOverallStatusCalculation:
    """Testa o cálculo de overall_status com diversas combinações."""

    def test_overall_status_all_pass(self, report_gen):
        """Todos os resultados PASS → OverallStatus.PASS."""
        results = [
            make_result(TrackTestStatus.PASS, "Track 1"),
            make_result(TrackTestStatus.PASS, "Track 2"),
            make_result(TrackTestStatus.PASS, "Track 3"),
        ]
        report = report_gen.create_channel_report(
            channel_url="https://example.com/player/live/CH001",
            audio_results=results,
            subtitle_results=[],
            duration_ms=5000,
        )
        assert report.overall_status == OverallStatus.PASS

    def test_overall_status_all_fail(self, report_gen):
        """Todos os resultados FAIL → OverallStatus.FAIL."""
        results = [
            make_result(TrackTestStatus.FAIL, "Track 1"),
            make_result(TrackTestStatus.FAIL, "Track 2"),
        ]
        report = report_gen.create_channel_report(
            channel_url="https://example.com/player/live/CH001",
            audio_results=results,
            subtitle_results=[],
            duration_ms=5000,
        )
        assert report.overall_status == OverallStatus.FAIL

    def test_overall_status_all_timeout(self, report_gen):
        """Todos os resultados TIMEOUT → OverallStatus.FAIL."""
        results = [
            make_result(TrackTestStatus.TIMEOUT, "Track 1"),
            make_result(TrackTestStatus.TIMEOUT, "Track 2"),
        ]
        report = report_gen.create_channel_report(
            channel_url="https://example.com/player/live/CH001",
            audio_results=[],
            subtitle_results=results,
            duration_ms=3000,
        )
        assert report.overall_status == OverallStatus.FAIL

    def test_overall_status_mix_pass_fail(self, report_gen):
        """Mix de PASS + FAIL → OverallStatus.PARTIAL."""
        audio = [make_result(TrackTestStatus.PASS, "Português")]
        subtitle = [make_result(TrackTestStatus.FAIL, "Inglês", "subtitle")]
        report = report_gen.create_channel_report(
            channel_url="https://example.com/player/live/CH001",
            audio_results=audio,
            subtitle_results=subtitle,
            duration_ms=5000,
        )
        assert report.overall_status == OverallStatus.PARTIAL

    def test_overall_status_mix_pass_timeout(self, report_gen):
        """Mix de PASS + TIMEOUT → OverallStatus.PARTIAL."""
        audio = [make_result(TrackTestStatus.PASS, "Português")]
        subtitle = [
            make_result(TrackTestStatus.TIMEOUT, "Inglês", "subtitle")
        ]
        report = report_gen.create_channel_report(
            channel_url="https://example.com/player/live/CH001",
            audio_results=audio,
            subtitle_results=subtitle,
            duration_ms=5000,
        )
        assert report.overall_status == OverallStatus.PARTIAL

    def test_overall_status_empty(self, report_gen):
        """Lista vazia de resultados → OverallStatus.PASS."""
        report = report_gen.create_channel_report(
            channel_url="https://example.com/player/live/CH001",
            audio_results=[],
            subtitle_results=[],
            duration_ms=0,
        )
        assert report.overall_status == OverallStatus.PASS


# ============================================================
# Testes de serialização JSON
# ============================================================


class TestSerialization:
    """Testa que a serialização JSON contém todas as chaves obrigatórias."""

    def test_serialization_has_required_keys(self, report_gen):
        """to_dict() do ChannelTestReport contém todas as chaves."""
        audio = [make_result(TrackTestStatus.PASS, "Português")]
        subtitle = [
            make_result(TrackTestStatus.PASS, "Inglês", "subtitle")
        ]
        report = report_gen.create_channel_report(
            channel_url="https://example.com/player/live/CH001",
            audio_results=audio,
            subtitle_results=subtitle,
            duration_ms=5000,
        )
        data = report.to_dict()

        # Chaves obrigatórias do ChannelTestReport
        required_keys = {
            "channel_url",
            "channel_id",
            "timestamp",
            "audio_results",
            "subtitle_results",
            "overall_status",
            "duration_ms",
        }
        assert required_keys.issubset(data.keys())

        # Chaves obrigatórias de cada TrackTestResult
        track_required_keys = {
            "track_name",
            "track_type",
            "status",
            "evidence",
            "duration_ms",
            "telemetry",
        }
        for track_result in data["audio_results"] + data["subtitle_results"]:
            assert track_required_keys.issubset(track_result.keys())

    def test_serialization_json_parseable(self, report_gen):
        """O resultado de to_dict() é serializável em JSON válido."""
        audio = [make_result(TrackTestStatus.FAIL, "Track A")]
        report = report_gen.create_channel_report(
            channel_url="https://example.com/player/live/CH002",
            audio_results=audio,
            subtitle_results=[],
            duration_ms=2000,
        )
        json_str = json.dumps(report.to_dict(), ensure_ascii=False)
        parsed = json.loads(json_str)
        assert parsed["channel_id"] == "CH002"
        assert parsed["overall_status"] == "FAIL"


# ============================================================
# Testes de filename
# ============================================================


class TestFilenameGeneration:
    """Testa geração de filename com caracteres especiais."""

    def test_filename_format(self, report_gen, tmp_path):
        """save_channel_report cria arquivo com padrão correto."""
        audio = [make_result(TrackTestStatus.PASS, "Português")]
        report = report_gen.create_channel_report(
            channel_url="https://example.com/player/live/CH001",
            audio_results=audio,
            subtitle_results=[],
            duration_ms=1000,
        )
        filepath = report_gen.save_channel_report(report)
        filename = os.path.basename(filepath)

        # Verifica padrão: audio_subtitle_report_{channel_id}_{ts}.json
        assert filename.startswith("audio_subtitle_report_CH001_")
        assert filename.endswith(".json")

    def test_filename_filesystem_safe(self, report_gen, tmp_path):
        """Timestamp com ':' é substituído no filename."""
        audio = [make_result(TrackTestStatus.PASS, "Test")]
        report = report_gen.create_channel_report(
            channel_url="https://example.com/player/live/CH001",
            audio_results=audio,
            subtitle_results=[],
            duration_ms=1000,
        )
        # O timestamp ISO 8601 contém ":" que deve ser substituído
        filepath = report_gen.save_channel_report(report)
        filename = os.path.basename(filepath)

        # ":" não deve estar presente no filename
        assert ":" not in filename


# ============================================================
# Testes de save_channel_report
# ============================================================


class TestSaveChannelReport:
    """Testa que save_channel_report cria arquivo no diretório correto."""

    def test_save_creates_file_in_output_dir(self, tmp_path):
        """Arquivo é criado no diretório de output configurado."""
        report_gen = ReportGenerator(output_dir=str(tmp_path))
        audio = [make_result(TrackTestStatus.PASS, "Track 1")]
        report = report_gen.create_channel_report(
            channel_url="https://example.com/player/live/CH123",
            audio_results=audio,
            subtitle_results=[],
            duration_ms=2000,
        )
        filepath = report_gen.save_channel_report(report)

        # Arquivo existe no path retornado
        assert os.path.isfile(filepath)

        # Arquivo está no diretório configurado
        assert os.path.dirname(filepath) == str(tmp_path)

        # Conteúdo é JSON válido
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["channel_id"] == "CH123"
        assert data["overall_status"] == "PASS"


# ============================================================
# Testes de relatório consolidado
# ============================================================


class TestConsolidatedReport:
    """Testa contadores do relatório consolidado."""

    def test_consolidated_report_counters(self, report_gen):
        """Contadores pass/partial/fail calculados corretamente."""
        # Criar 3 reports com status diferentes
        report_pass = report_gen.create_channel_report(
            channel_url="https://example.com/player/live/CH001",
            audio_results=[make_result(TrackTestStatus.PASS, "A")],
            subtitle_results=[make_result(TrackTestStatus.PASS, "B", "subtitle")],
            duration_ms=1000,
        )
        report_partial = report_gen.create_channel_report(
            channel_url="https://example.com/player/live/CH002",
            audio_results=[make_result(TrackTestStatus.PASS, "A")],
            subtitle_results=[make_result(TrackTestStatus.FAIL, "B", "subtitle")],
            duration_ms=2000,
        )
        report_fail = report_gen.create_channel_report(
            channel_url="https://example.com/player/live/CH003",
            audio_results=[make_result(TrackTestStatus.FAIL, "A")],
            subtitle_results=[make_result(TrackTestStatus.TIMEOUT, "B", "subtitle")],
            duration_ms=3000,
        )

        consolidated = report_gen.create_consolidated_report(
            [report_pass, report_partial, report_fail]
        )

        assert consolidated.total_channels == 3
        assert consolidated.channels_pass == 1
        assert consolidated.channels_partial == 1
        assert consolidated.channels_fail == 1
        assert consolidated.total_duration_ms == 6000
