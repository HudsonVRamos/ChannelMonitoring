"""Testes unitários e property tests para UnifiedReportGenerator.

Valida:
- Geração de UnifiedChannelReport com dados corretos
- Cálculo de status (PASS, PARTIAL, FAIL)
- Geração de ConsolidatedReport com contagens
- Persistência de JSON no diretório de output
- Derivação de channel_id a partir da URL
- Geração de session_id UUID
- Property 8: Unified report completeness
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from src.unified_channel_monitor.models import (
    AudioTrackResult,
    EscalationResult,
    SubtitleTrackResult,
    TelemetrySummary,
    UnifiedChannelReport,
)
from src.unified_channel_monitor.report_generator import (
    UnifiedReportGenerator,
)


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def generator(tmp_path: Path) -> UnifiedReportGenerator:
    """Gerador configurado com diretório temporário."""
    return UnifiedReportGenerator(output_dir=str(tmp_path))


@pytest.fixture
def video_summary_healthy() -> TelemetrySummary:
    """TelemetrySummary com classificação HEALTHY."""
    return TelemetrySummary(
        total_samples=15,
        freeze_events=[],
        average_buffer_ahead_s=8.5,
        average_fps=25.0,
        health_classification="HEALTHY",
        annotations=[{"track": "pt", "type": "audio_switch"}],
        start_time="2024-01-01T00:00:00+00:00",
        end_time="2024-01-01T00:00:30+00:00",
        duration_s=30.0,
    )


@pytest.fixture
def video_summary_degraded() -> TelemetrySummary:
    """TelemetrySummary com classificação DEGRADED."""
    return TelemetrySummary(
        total_samples=15,
        freeze_events=[],
        average_buffer_ahead_s=1.0,
        average_fps=10.0,
        health_classification="DEGRADED",
        annotations=[],
        start_time="2024-01-01T00:00:00+00:00",
        end_time="2024-01-01T00:00:30+00:00",
        duration_s=30.0,
    )


@pytest.fixture
def audio_results_all_pass() -> list[AudioTrackResult]:
    """Lista de resultados de áudio todos PASS."""
    return [
        AudioTrackResult(
            track_name="Português",
            status="PASS",
            rms_avg=0.05,
            audio_present_ratio=0.95,
            switch_validated=True,
            duration_ms=5000,
        ),
        AudioTrackResult(
            track_name="Inglês",
            status="PASS",
            rms_avg=0.04,
            audio_present_ratio=0.90,
            switch_validated=True,
            duration_ms=5000,
        ),
    ]


@pytest.fixture
def subtitle_results_all_pass() -> list[SubtitleTrackResult]:
    """Lista de resultados de legendas todos PASS."""
    return [
        SubtitleTrackResult(
            track_name="Português",
            status="PASS",
            cue_received=True,
            time_to_first_cue_ms=3000,
            switch_validated=True,
            duration_ms=4000,
        ),
    ]


# ============================================================
# Tests - create_channel_report
# ============================================================


class TestCreateChannelReport:
    """Testes para create_channel_report."""

    def test_gera_session_id_uuid_valido(
        self,
        generator: UnifiedReportGenerator,
        video_summary_healthy: TelemetrySummary,
    ):
        """session_id deve ser UUID v4 válido."""
        report = generator.create_channel_report(
            channel_url="https://example.com/canal1",
            video_summary=video_summary_healthy,
            audio_results=[],
            subtitle_results=[],
            escalation_results=[],
            duration_ms=30000,
        )
        # Deve ser UUID válido (não lança exceção)
        parsed = uuid.UUID(report.session_id)
        assert parsed.version == 4

    def test_deriva_channel_id_do_path(
        self,
        generator: UnifiedReportGenerator,
        video_summary_healthy: TelemetrySummary,
    ):
        """channel_id derivado do último segmento da URL."""
        report = generator.create_channel_report(
            channel_url="https://sky.com/channels/hbo",
            video_summary=video_summary_healthy,
            audio_results=[],
            subtitle_results=[],
            escalation_results=[],
            duration_ms=30000,
        )
        assert report.channel_id == "hbo"

    def test_status_pass_quando_tudo_ok(
        self,
        generator: UnifiedReportGenerator,
        video_summary_healthy: TelemetrySummary,
        audio_results_all_pass: list[AudioTrackResult],
        subtitle_results_all_pass: list[SubtitleTrackResult],
    ):
        """Status PASS quando vídeo saudável e todos tracks OK."""
        report = generator.create_channel_report(
            channel_url="https://sky.com/ch/1",
            video_summary=video_summary_healthy,
            audio_results=audio_results_all_pass,
            subtitle_results=subtitle_results_all_pass,
            escalation_results=[],
            duration_ms=60000,
        )
        assert report.status == "PASS"

    def test_status_fail_quando_video_degraded(
        self,
        generator: UnifiedReportGenerator,
        video_summary_degraded: TelemetrySummary,
        audio_results_all_pass: list[AudioTrackResult],
        subtitle_results_all_pass: list[SubtitleTrackResult],
    ):
        """Status FAIL quando vídeo DEGRADED."""
        report = generator.create_channel_report(
            channel_url="https://sky.com/ch/1",
            video_summary=video_summary_degraded,
            audio_results=audio_results_all_pass,
            subtitle_results=subtitle_results_all_pass,
            escalation_results=[],
            duration_ms=60000,
        )
        assert report.status == "FAIL"

    def test_status_partial_quando_mix(
        self,
        generator: UnifiedReportGenerator,
        video_summary_healthy: TelemetrySummary,
    ):
        """Status PARTIAL quando alguns testes passam e outros falham."""
        audio = [
            AudioTrackResult(
                track_name="PT", status="PASS",
                rms_avg=0.05, audio_present_ratio=0.9,
                switch_validated=True, duration_ms=5000,
            ),
            AudioTrackResult(
                track_name="EN", status="FAIL",
                fail_reason="switch_timeout",
                rms_avg=None, audio_present_ratio=None,
                switch_validated=False, duration_ms=5000,
            ),
        ]
        subtitle = [
            SubtitleTrackResult(
                track_name="PT", status="PASS",
                cue_received=True, time_to_first_cue_ms=2000,
                switch_validated=True, duration_ms=3000,
            ),
        ]
        report = generator.create_channel_report(
            channel_url="https://sky.com/ch/1",
            video_summary=video_summary_healthy,
            audio_results=audio,
            subtitle_results=subtitle,
            escalation_results=[],
            duration_ms=60000,
        )
        assert report.status == "PARTIAL"

    def test_contagens_audio_e_subtitle(
        self,
        generator: UnifiedReportGenerator,
        video_summary_healthy: TelemetrySummary,
        audio_results_all_pass: list[AudioTrackResult],
        subtitle_results_all_pass: list[SubtitleTrackResult],
    ):
        """Verifica contagens de tracks testados e aprovados."""
        report = generator.create_channel_report(
            channel_url="https://sky.com/ch/1",
            video_summary=video_summary_healthy,
            audio_results=audio_results_all_pass,
            subtitle_results=subtitle_results_all_pass,
            escalation_results=[],
            duration_ms=60000,
        )
        assert report.audio_tracks_tested == 2
        assert report.audio_tracks_passed == 2
        assert report.subtitle_tracks_tested == 1
        assert report.subtitle_tracks_passed == 1

    def test_inclui_annotations_do_video_summary(
        self,
        generator: UnifiedReportGenerator,
        video_summary_healthy: TelemetrySummary,
    ):
        """Anotações de telemetria são copiadas para o relatório."""
        report = generator.create_channel_report(
            channel_url="https://sky.com/ch/1",
            video_summary=video_summary_healthy,
            audio_results=[],
            subtitle_results=[],
            escalation_results=[],
            duration_ms=30000,
        )
        assert len(report.telemetry_annotations) == 1
        assert report.telemetry_annotations[0]["track"] == "pt"

    def test_inclui_escalation_results(
        self,
        generator: UnifiedReportGenerator,
        video_summary_healthy: TelemetrySummary,
    ):
        """Resultados de escalação são incluídos no relatório."""
        escalations = [
            EscalationResult(
                trigger_timestamp="2024-01-01T00:00:10+00:00",
                opencv_verdict="freeze",
                bedrock_diagnosis="Freeze detectado",
                frames_analyzed=5,
                deferred=True,
            ),
        ]
        report = generator.create_channel_report(
            channel_url="https://sky.com/ch/1",
            video_summary=video_summary_healthy,
            audio_results=[],
            subtitle_results=[],
            escalation_results=escalations,
            duration_ms=30000,
        )
        assert len(report.escalation_results) == 1
        assert report.escalation_results[0].opencv_verdict == "freeze"


# ============================================================
# Tests - create_consolidated_report
# ============================================================


class TestCreateConsolidatedReport:
    """Testes para create_consolidated_report."""

    def test_contagens_por_status(
        self, generator: UnifiedReportGenerator
    ):
        """Contagens por status correspondem aos relatórios."""
        reports = [
            self._make_report("PASS", 10000),
            self._make_report("PASS", 15000),
            self._make_report("FAIL", 20000),
            self._make_report("PARTIAL", 12000),
            self._make_report("UNREACHABLE", 5000),
            self._make_report("ERROR", 3000),
        ]
        consolidated = generator.create_consolidated_report(reports)

        assert consolidated.total_channels == 6
        assert consolidated.channels_pass == 2
        assert consolidated.channels_fail == 1
        assert consolidated.channels_partial == 1
        assert consolidated.channels_unreachable == 1
        assert consolidated.channels_error == 1

    def test_total_duration_soma_duracoes(
        self, generator: UnifiedReportGenerator
    ):
        """total_duration_ms é a soma de todas as durações."""
        reports = [
            self._make_report("PASS", 10000),
            self._make_report("PASS", 20000),
        ]
        consolidated = generator.create_consolidated_report(reports)
        assert consolidated.total_duration_ms == 30000

    def test_lista_vazia_retorna_zeros(
        self, generator: UnifiedReportGenerator
    ):
        """Lista vazia retorna totais zerados."""
        consolidated = generator.create_consolidated_report([])
        assert consolidated.total_channels == 0
        assert consolidated.channels_pass == 0
        assert consolidated.total_duration_ms == 0

    @staticmethod
    def _make_report(
        status: str, duration_ms: int
    ) -> UnifiedChannelReport:
        """Helper para criar UnifiedChannelReport mínimo."""
        return UnifiedChannelReport(
            channel_url="https://sky.com/ch/test",
            channel_id="test",
            session_id=str(uuid.uuid4()),
            timestamp="2024-01-01T00:00:00+00:00",
            status=status,
            duration_ms=duration_ms,
            video_summary=TelemetrySummary(total_samples=0),
        )


# ============================================================
# Tests - persist_report
# ============================================================


class TestPersistReport:
    """Testes para persist_report."""

    def test_cria_diretorio_e_arquivo(
        self, generator: UnifiedReportGenerator, tmp_path: Path
    ):
        """Cria diretório e persiste JSON."""
        report_data = {"status": "PASS", "channels": 5}
        filename = "report_2024-01-01T00-00-00.json"

        filepath = generator.persist_report(report_data, filename)

        assert filepath.exists()
        assert filepath.name == filename

        content = json.loads(filepath.read_text(encoding="utf-8"))
        assert content == report_data

    def test_json_formatado_com_indent(
        self, generator: UnifiedReportGenerator, tmp_path: Path
    ):
        """JSON gerado com indentação de 2 espaços."""
        report_data = {"key": "value"}
        filepath = generator.persist_report(
            report_data, "test.json"
        )

        raw = filepath.read_text(encoding="utf-8")
        assert "  " in raw  # Indentação presente

    def test_suporta_unicode(
        self, generator: UnifiedReportGenerator, tmp_path: Path
    ):
        """JSON suporta caracteres Unicode (português)."""
        report_data = {"canal": "São Paulo", "status": "aprovação"}
        filepath = generator.persist_report(
            report_data, "unicode.json"
        )

        raw = filepath.read_text(encoding="utf-8")
        assert "São Paulo" in raw
        assert "aprovação" in raw

    def test_cria_subdiretorios_necessarios(
        self, tmp_path: Path
    ):
        """Cria subdiretórios inexistentes automaticamente."""
        deep_path = tmp_path / "a" / "b" / "c"
        gen = UnifiedReportGenerator(output_dir=str(deep_path))

        filepath = gen.persist_report({"ok": True}, "deep.json")
        assert filepath.exists()


# ============================================================
# Tests - _derive_channel_id
# ============================================================


class TestDeriveChannelId:
    """Testes para _derive_channel_id."""

    def test_ultimo_segmento_do_path(self):
        """Retorna último segmento do path."""
        result = UnifiedReportGenerator._derive_channel_id(
            "https://sky.com/channels/hbo"
        )
        assert result == "hbo"

    def test_path_com_trailing_slash(self):
        """Remove trailing slash antes de derivar."""
        result = UnifiedReportGenerator._derive_channel_id(
            "https://sky.com/channels/hbo/"
        )
        assert result == "hbo"

    def test_sem_path_usa_hostname(self):
        """Sem path, usa hostname."""
        result = UnifiedReportGenerator._derive_channel_id(
            "https://sky.com"
        )
        assert result == "sky.com"

    def test_url_sem_scheme_usa_completa(self):
        """URL sem scheme/hostname usa a URL completa."""
        result = UnifiedReportGenerator._derive_channel_id(
            "canal_local"
        )
        assert result == "canal_local"


# ============================================================
# Tests - _calculate_channel_status
# ============================================================


class TestCalculateChannelStatus:
    """Testes para _calculate_channel_status."""

    def test_pass_sem_tracks(
        self, generator: UnifiedReportGenerator
    ):
        """PASS quando não há tracks e vídeo HEALTHY."""
        summary = TelemetrySummary(
            total_samples=10, health_classification="HEALTHY"
        )
        status = generator._calculate_channel_status(
            video_summary=summary,
            audio_results=[],
            subtitle_results=[],
            audio_tracks_passed=0,
            subtitle_tracks_passed=0,
        )
        assert status == "PASS"

    def test_fail_video_critical(
        self, generator: UnifiedReportGenerator
    ):
        """FAIL quando vídeo CRITICAL independente dos tracks."""
        summary = TelemetrySummary(
            total_samples=10, health_classification="CRITICAL"
        )
        audio = [
            AudioTrackResult(
                track_name="PT", status="PASS",
                rms_avg=0.05, audio_present_ratio=0.9,
                switch_validated=True, duration_ms=5000,
            ),
        ]
        status = generator._calculate_channel_status(
            video_summary=summary,
            audio_results=audio,
            subtitle_results=[],
            audio_tracks_passed=1,
            subtitle_tracks_passed=0,
        )
        assert status == "FAIL"

    def test_skip_nao_conta_como_testado(
        self, generator: UnifiedReportGenerator
    ):
        """Tracks SKIP não influenciam o cálculo de status."""
        summary = TelemetrySummary(
            total_samples=10, health_classification="HEALTHY"
        )
        subtitle = [
            SubtitleTrackResult(
                track_name="PT", status="SKIP",
                fail_reason="dialog_unavailable",
                cue_received=False,
                duration_ms=0,
            ),
        ]
        status = generator._calculate_channel_status(
            video_summary=summary,
            audio_results=[],
            subtitle_results=subtitle,
            audio_tracks_passed=0,
            subtitle_tracks_passed=0,
        )
        # Nenhum track efetivamente testado, vídeo saudável
        assert status == "PASS"


# ============================================================
# Property-Based Tests (Hypothesis)
# ============================================================

# Feature: unified-channel-monitor, Property 9: Consolidated report aggregation is correct

from collections import Counter

from hypothesis import given, settings
from hypothesis import strategies as st


@settings(max_examples=100)
@given(
    reports_data=st.lists(
        st.tuples(
            st.sampled_from(["PASS", "PARTIAL", "FAIL", "UNREACHABLE", "ERROR"]),
            st.integers(min_value=0, max_value=100_000),
        ),
        min_size=0,
        max_size=20,
    )
)
def test_property_9_consolidated_report_aggregation_is_correct(
    reports_data: list[tuple[str, int]],
):
    """Property 9: Consolidated report aggregation is correct.

    For any list of N UnifiedChannelReports with statuses distributed among
    PASS, PARTIAL, FAIL, UNREACHABLE, and ERROR, the ConsolidatedReport SHALL
    have total_channels=N and the sum of channels_pass + channels_partial +
    channels_fail + channels_unreachable + channels_error SHALL equal N.

    **Validates: Requirements 8.6**
    """
    # Construir lista de UnifiedChannelReport a partir dos dados gerados
    channel_reports = []
    for status, duration_ms in reports_data:
        report = UnifiedChannelReport(
            channel_url="https://example.com/ch/test",
            channel_id="test",
            session_id=str(uuid.uuid4()),
            timestamp="2024-01-01T00:00:00+00:00",
            status=status,
            duration_ms=duration_ms,
            video_summary=TelemetrySummary(total_samples=0),
        )
        channel_reports.append(report)

    n = len(channel_reports)

    # Chamar create_consolidated_report
    generator = UnifiedReportGenerator(output_dir="/tmp/test_pbt")
    consolidated = generator.create_consolidated_report(channel_reports)

    # Verificação 1: total_channels == N
    assert consolidated.total_channels == n, (
        f"total_channels={consolidated.total_channels}, esperado={n}"
    )

    # Verificação 2: soma das contagens por status == N
    soma_status = (
        consolidated.channels_pass
        + consolidated.channels_partial
        + consolidated.channels_fail
        + consolidated.channels_unreachable
        + consolidated.channels_error
    )
    assert soma_status == n, (
        f"soma_status={soma_status}, esperado={n}"
    )

    # Verificação 3: cada contagem individual corresponde ao real
    status_counter = Counter(status for status, _ in reports_data)
    assert consolidated.channels_pass == status_counter.get("PASS", 0)
    assert consolidated.channels_partial == status_counter.get("PARTIAL", 0)
    assert consolidated.channels_fail == status_counter.get("FAIL", 0)
    assert consolidated.channels_unreachable == status_counter.get("UNREACHABLE", 0)
    assert consolidated.channels_error == status_counter.get("ERROR", 0)

    # Verificação 4: total_duration_ms == soma de todas as durações
    expected_duration = sum(duration_ms for _, duration_ms in reports_data)
    assert consolidated.total_duration_ms == expected_duration, (
        f"total_duration_ms={consolidated.total_duration_ms}, "
        f"esperado={expected_duration}"
    )


# ============================================================
# Property Tests - Hypothesis
# ============================================================


# Feature: unified-channel-monitor, Property 8: Unified report completeness


# --- Strategies ---

audio_status_st = st.sampled_from(["PASS", "FAIL", "SKIP"])
subtitle_status_st = st.sampled_from(["PASS", "FAIL", "SKIP"])

audio_track_result_st = st.builds(
    AudioTrackResult,
    track_name=st.text(
        alphabet=st.characters(whitelist_categories=("L", "N", "Z")),
        min_size=1,
        max_size=30,
    ),
    status=audio_status_st,
    rms_avg=st.one_of(st.none(), st.floats(min_value=0.0, max_value=1.0)),
    audio_present_ratio=st.one_of(
        st.none(), st.floats(min_value=0.0, max_value=1.0)
    ),
    switch_validated=st.booleans(),
    duration_ms=st.integers(min_value=0, max_value=60000),
)

subtitle_track_result_st = st.builds(
    SubtitleTrackResult,
    track_name=st.text(
        alphabet=st.characters(whitelist_categories=("L", "N", "Z")),
        min_size=1,
        max_size=30,
    ),
    status=subtitle_status_st,
    cue_received=st.booleans(),
    time_to_first_cue_ms=st.one_of(
        st.none(), st.integers(min_value=0, max_value=30000)
    ),
    switch_validated=st.booleans(),
    duration_ms=st.integers(min_value=0, max_value=60000),
)

escalation_result_st = st.builds(
    EscalationResult,
    trigger_timestamp=st.just("2024-01-01T00:00:00+00:00"),
    opencv_verdict=st.one_of(
        st.none(), st.sampled_from(["black_screen", "freeze", "normal"])
    ),
    bedrock_diagnosis=st.one_of(st.none(), st.text(min_size=1, max_size=50)),
    frames_analyzed=st.integers(min_value=0, max_value=10),
    deferred=st.booleans(),
)

channel_url_st = st.from_regex(
    r"https://[a-z]{3,10}\.[a-z]{2,5}/[a-z0-9]{1,10}", fullmatch=True
)


class TestUnifiedReportCompleteness:
    """Property 8: Unified report completeness.

    **Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.5**

    For any completed Channel_Session with V telemetry samples,
    A audio track results, and S subtitle track results, the generated
    UnifiedChannelReport SHALL contain:
    - video_summary with total_samples == V
    - all A audio results with required fields
    - all S subtitle results with required fields
    """

    @given(
        total_samples=st.integers(min_value=0, max_value=50),
        audio_results=st.lists(
            audio_track_result_st, min_size=0, max_size=10
        ),
        subtitle_results=st.lists(
            subtitle_track_result_st, min_size=0, max_size=10
        ),
        escalation_results=st.lists(
            escalation_result_st, min_size=0, max_size=5
        ),
        duration_ms=st.integers(min_value=1, max_value=600000),
        channel_url=channel_url_st,
    )
    @settings(max_examples=100)
    def test_report_completeness(
        self,
        total_samples: int,
        audio_results: list[AudioTrackResult],
        subtitle_results: list[SubtitleTrackResult],
        escalation_results: list[EscalationResult],
        duration_ms: int,
        channel_url: str,
    ):
        """Relatório unificado contém todos os dados de entrada."""
        # Arrange
        video_summary = TelemetrySummary(
            total_samples=total_samples,
            health_classification="HEALTHY",
        )
        generator = UnifiedReportGenerator(output_dir="/tmp/test_reports")

        # Act
        report = generator.create_channel_report(
            channel_url=channel_url,
            video_summary=video_summary,
            audio_results=audio_results,
            subtitle_results=subtitle_results,
            escalation_results=escalation_results,
            duration_ms=duration_ms,
        )

        # Assert 1: video_summary.total_samples == V
        assert report.video_summary.total_samples == total_samples

        # Assert 2: len(report.audio_results) == A
        assert len(report.audio_results) == len(audio_results)

        # Assert 3: cada audio result tem campos obrigatórios
        for audio_result in report.audio_results:
            assert hasattr(audio_result, "track_name")
            assert audio_result.track_name is not None
            assert hasattr(audio_result, "status")
            assert audio_result.status in ("PASS", "FAIL", "SKIP")
            assert hasattr(audio_result, "rms_avg")
            assert hasattr(audio_result, "audio_present_ratio")

        # Assert 4: len(report.subtitle_results) == S
        assert len(report.subtitle_results) == len(subtitle_results)

        # Assert 5: cada subtitle result tem campos obrigatórios
        for sub_result in report.subtitle_results:
            assert hasattr(sub_result, "track_name")
            assert sub_result.track_name is not None
            assert hasattr(sub_result, "status")
            assert sub_result.status in ("PASS", "FAIL", "SKIP")
            assert hasattr(sub_result, "cue_received")

        # Assert 6: audio_tracks_tested == len(audio_results)
        assert report.audio_tracks_tested == len(audio_results)

        # Assert 7: subtitle_tracks_tested == len(subtitle_results)
        assert report.subtitle_tracks_tested == len(subtitle_results)

        # Assert 8: session_id é UUID válido
        parsed_uuid = uuid.UUID(report.session_id)
        assert parsed_uuid.version == 4

        # Assert 9: channel_url preservado
        assert report.channel_url == channel_url
