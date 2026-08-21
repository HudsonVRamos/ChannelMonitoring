"""Property-based tests para os data models do Audio & Subtitle Monitor.

Testa propriedades universais de serialização e formatação de nomes de arquivo
usando Hypothesis para validar com inputs arbitrários.

Feature: audio-subtitle-monitoring
"""

from __future__ import annotations

import re

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from src.audio_subtitle_monitor.models import (
    ChannelTestReport,
    OverallStatus,
    TrackTestResult,
    TrackTestStatus,
)


# ============================================================
# Estratégias (Generators) para Hypothesis
# ============================================================


@st.composite
def track_test_result_strategy(draw):
    """Gera instâncias válidas de TrackTestResult."""
    track_name = draw(st.text(min_size=1, max_size=30))
    track_type = draw(st.sampled_from(["audio", "subtitle"]))
    status = draw(st.sampled_from(list(TrackTestStatus)))
    evidence = draw(st.fixed_dictionaries({"reason": st.text(max_size=50)}))
    duration_ms = draw(st.integers(min_value=0, max_value=1_000_000))
    telemetry = draw(
        st.none() | st.fixed_dictionaries({"data": st.text(max_size=20)})
    )

    return TrackTestResult(
        track_name=track_name,
        track_type=track_type,
        status=status,
        evidence=evidence,
        duration_ms=duration_ms,
        telemetry=telemetry,
    )


@st.composite
def channel_test_report_strategy(draw):
    """Gera instâncias válidas de ChannelTestReport."""
    channel_url = draw(
        st.text(
            alphabet=st.characters(whitelist_categories=("L", "N", "P")),
            min_size=5,
            max_size=80,
        )
    )
    channel_id = draw(
        st.text(
            alphabet=st.characters(whitelist_categories=("L", "N")),
            min_size=1,
            max_size=20,
        )
    )
    timestamp = draw(st.datetimes().map(lambda d: d.isoformat()))
    audio_results = draw(
        st.lists(track_test_result_strategy(), min_size=0, max_size=5)
    )
    subtitle_results = draw(
        st.lists(track_test_result_strategy(), min_size=0, max_size=5)
    )
    overall_status = draw(st.sampled_from(list(OverallStatus)))
    duration_ms = draw(st.integers(min_value=0, max_value=1_000_000))

    return ChannelTestReport(
        channel_url=channel_url,
        channel_id=channel_id,
        timestamp=timestamp,
        audio_results=audio_results,
        subtitle_results=subtitle_results,
        overall_status=overall_status,
        duration_ms=duration_ms,
    )


# ============================================================
# Property 10: Report Serialization Completeness
# ============================================================


class TestReportSerializationCompleteness:
    """Feature: audio-subtitle-monitoring, Property 10: Report Serialization Completeness

    Validates: Requirements 7.1, 7.4

    Para qualquer ChannelTestReport válido, a serialização JSON (via to_dict())
    deve conter todas as chaves obrigatórias no nível superior e em cada
    TrackTestResult aninhado.
    """

    @given(report=channel_test_report_strategy())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_top_level_keys_present(self, report: ChannelTestReport):
        """**Validates: Requirements 7.1**

        A serialização deve conter todas as chaves obrigatórias no nível superior.
        """
        serialized = report.to_dict()

        required_keys = {
            "channel_url",
            "channel_id",
            "timestamp",
            "audio_results",
            "subtitle_results",
            "overall_status",
            "duration_ms",
        }

        for key in required_keys:
            assert key in serialized, (
                f"Chave obrigatória '{key}' ausente na serialização"
            )

    @given(report=channel_test_report_strategy())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_track_result_keys_present(self, report: ChannelTestReport):
        """**Validates: Requirements 7.4**

        Cada TrackTestResult serializado deve conter todas as chaves obrigatórias.
        """
        serialized = report.to_dict()

        required_track_keys = {
            "track_name",
            "track_type",
            "status",
            "evidence",
            "duration_ms",
            "telemetry",
        }

        all_results = serialized["audio_results"] + serialized["subtitle_results"]

        for track_result in all_results:
            for key in required_track_keys:
                assert key in track_result, (
                    f"Chave obrigatória '{key}' ausente em TrackTestResult"
                )

    @given(report=channel_test_report_strategy())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_serialized_values_match_original(self, report: ChannelTestReport):
        """**Validates: Requirements 7.1**

        Os valores serializados devem corresponder aos valores originais do report.
        """
        serialized = report.to_dict()

        assert serialized["channel_url"] == report.channel_url
        assert serialized["channel_id"] == report.channel_id
        assert serialized["timestamp"] == report.timestamp
        assert serialized["overall_status"] == report.overall_status.value
        assert serialized["duration_ms"] == report.duration_ms
        assert len(serialized["audio_results"]) == len(report.audio_results)
        assert len(serialized["subtitle_results"]) == len(report.subtitle_results)


# ============================================================
# Property 11: Report Filename Format
# ============================================================


def generate_report_filename(channel_id: str, timestamp: str) -> str:
    """Gera o nome do arquivo de relatório com timestamp filesystem-safe.

    Esta função implementa a lógica esperada de geração de filename
    conforme especificado no Requirement 7.3.
    """
    safe_timestamp = timestamp.replace(":", "-").replace(" ", "_")
    return f"audio_subtitle_report_{channel_id}_{safe_timestamp}.json"


class TestReportFilenameFormat:
    """Feature: audio-subtitle-monitoring, Property 11: Report Filename Format

    Validates: Requirements 7.3

    Para qualquer channel_id (alfanumérico) e timestamp (ISO 8601),
    o filename gerado deve seguir o padrão esperado e ser filesystem-safe.
    """

    @given(
        channel_id=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N")),
            min_size=1,
            max_size=20,
        ),
        timestamp=st.datetimes().map(lambda d: d.isoformat()),
    )
    @settings(max_examples=100)
    def test_filename_starts_with_prefix(self, channel_id: str, timestamp: str):
        """**Validates: Requirements 7.3**

        O filename deve iniciar com o prefixo 'audio_subtitle_report_'.
        """
        filename = generate_report_filename(channel_id, timestamp)

        assert filename.startswith("audio_subtitle_report_")

    @given(
        channel_id=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N")),
            min_size=1,
            max_size=20,
        ),
        timestamp=st.datetimes().map(lambda d: d.isoformat()),
    )
    @settings(max_examples=100)
    def test_filename_ends_with_json(self, channel_id: str, timestamp: str):
        """**Validates: Requirements 7.3**

        O filename deve terminar com a extensão '.json'.
        """
        filename = generate_report_filename(channel_id, timestamp)

        assert filename.endswith(".json")

    @given(
        channel_id=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N")),
            min_size=1,
            max_size=20,
        ),
        timestamp=st.datetimes().map(lambda d: d.isoformat()),
    )
    @settings(max_examples=100)
    def test_filename_contains_channel_id(self, channel_id: str, timestamp: str):
        """**Validates: Requirements 7.3**

        O filename deve conter o channel_id.
        """
        filename = generate_report_filename(channel_id, timestamp)

        assert channel_id in filename

    @given(
        channel_id=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N")),
            min_size=1,
            max_size=20,
        ),
        timestamp=st.datetimes().map(lambda d: d.isoformat()),
    )
    @settings(max_examples=100)
    def test_filename_is_filesystem_safe(self, channel_id: str, timestamp: str):
        """**Validates: Requirements 7.3**

        O filename não deve conter caracteres proibidos em filesystems
        (sem ':', espaços, ou outros caracteres problemáticos).
        """
        filename = generate_report_filename(channel_id, timestamp)

        # Não deve conter ':' (Windows) ou espaços
        assert ":" not in filename
        assert " " not in filename

    @given(
        channel_id=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N")),
            min_size=1,
            max_size=20,
        ),
        timestamp=st.datetimes().map(lambda d: d.isoformat()),
    )
    @settings(max_examples=100)
    def test_filename_matches_expected_pattern(
        self, channel_id: str, timestamp: str
    ):
        """**Validates: Requirements 7.3**

        O filename deve seguir o padrão completo:
        audio_subtitle_report_{channel_id}_{safe_timestamp}.json
        """
        filename = generate_report_filename(channel_id, timestamp)

        safe_timestamp = timestamp.replace(":", "-").replace(" ", "_")
        expected = f"audio_subtitle_report_{channel_id}_{safe_timestamp}.json"

        assert filename == expected

    @given(
        channel_id=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N")),
            min_size=1,
            max_size=20,
        ),
        timestamp=st.datetimes().map(lambda d: d.isoformat()),
    )
    @settings(max_examples=100)
    def test_filename_matches_regex_pattern(
        self, channel_id: str, timestamp: str
    ):
        """**Validates: Requirements 7.3**

        O filename deve casar com o padrão regex esperado.
        """
        filename = generate_report_filename(channel_id, timestamp)

        # Padrão: audio_subtitle_report_ + alfanuméricos + _ + timestamp-safe + .json
        pattern = r"^audio_subtitle_report_.+_.+\.json$"
        assert re.match(pattern, filename), (
            f"Filename '{filename}' não casa com o padrão esperado"
        )
