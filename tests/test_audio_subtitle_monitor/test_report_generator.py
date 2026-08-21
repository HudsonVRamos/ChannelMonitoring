"""Property-based tests para ReportGenerator do Audio & Subtitle Monitor.

Testa propriedades universais de cálculo de overall_status e agregação
de relatórios consolidados usando Hypothesis.

Feature: audio-subtitle-monitoring
"""

from __future__ import annotations

import tempfile

from hypothesis import given, settings
from hypothesis import strategies as st

from src.audio_subtitle_monitor.models import (
    ChannelTestReport,
    ConsolidatedReport,
    OverallStatus,
    TrackTestResult,
    TrackTestStatus,
)
from src.audio_subtitle_monitor.report_generator import ReportGenerator


# ============================================================
# Estratégias (Generators) para Hypothesis
# ============================================================


@st.composite
def track_test_result_with_status(draw, status=None):
    """Gera TrackTestResult com status específico ou aleatório."""
    if status is None:
        status = draw(st.sampled_from(list(TrackTestStatus)))

    track_name = draw(st.text(min_size=1, max_size=20))
    track_type = draw(st.sampled_from(["audio", "subtitle"]))
    evidence = draw(
        st.fixed_dictionaries({"reason": st.text(max_size=30)})
    )
    duration_ms = draw(st.integers(min_value=0, max_value=500_000))

    return TrackTestResult(
        track_name=track_name,
        track_type=track_type,
        status=status,
        evidence=evidence,
        duration_ms=duration_ms,
    )


@st.composite
def channel_test_report_with_status(draw, overall_status=None):
    """Gera ChannelTestReport com overall_status específico ou aleatório."""
    if overall_status is None:
        overall_status = draw(st.sampled_from(list(OverallStatus)))

    channel_url = draw(
        st.text(
            alphabet=st.characters(whitelist_categories=("L", "N", "P")),
            min_size=5,
            max_size=60,
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
    duration_ms = draw(st.integers(min_value=0, max_value=1_000_000))

    return ChannelTestReport(
        channel_url=channel_url,
        channel_id=channel_id,
        timestamp=timestamp,
        audio_results=[],
        subtitle_results=[],
        overall_status=overall_status,
        duration_ms=duration_ms,
    )


def _make_report_generator() -> ReportGenerator:
    """Cria instância de ReportGenerator com diretório temporário."""
    output_dir = tempfile.mkdtemp()
    return ReportGenerator(output_dir)


# ============================================================
# Property 9: Overall Status Calculation
# ============================================================


class TestOverallStatusCalculation:
    """Feature: audio-subtitle-monitoring, Property 9: Overall Status Calculation

    **Validates: Requirements 7.2**

    Para qualquer lista de TrackTestResults, overall_status é:
    - PASS quando lista vazia ou todos PASS
    - FAIL quando todos FAIL/TIMEOUT (com pelo menos um resultado)
    - PARTIAL em todos os outros casos mistos
    """

    @given(
        results=st.lists(
            track_test_result_with_status(
                status=TrackTestStatus.PASS
            ),
            min_size=1,
            max_size=10,
        )
    )
    @settings(max_examples=100)
    def test_all_pass_returns_pass(self, results):
        """**Validates: Requirements 7.2**

        Quando todos os resultados são PASS, overall_status deve ser PASS.
        """
        rg = _make_report_generator()
        status = rg._calculate_overall_status(results)
        assert status == OverallStatus.PASS

    @given(
        results=st.lists(
            track_test_result_with_status(
                status=TrackTestStatus.FAIL
            ),
            min_size=1,
            max_size=10,
        )
    )
    @settings(max_examples=100)
    def test_all_fail_returns_fail(self, results):
        """**Validates: Requirements 7.2**

        Quando todos os resultados são FAIL, overall_status deve ser FAIL.
        """
        rg = _make_report_generator()
        status = rg._calculate_overall_status(results)
        assert status == OverallStatus.FAIL

    @given(
        results=st.lists(
            track_test_result_with_status(
                status=TrackTestStatus.TIMEOUT
            ),
            min_size=1,
            max_size=10,
        )
    )
    @settings(max_examples=100)
    def test_all_timeout_returns_fail(self, results):
        """**Validates: Requirements 7.2**

        Quando todos os resultados são TIMEOUT, overall_status deve ser FAIL.
        """
        rg = _make_report_generator()
        status = rg._calculate_overall_status(results)
        assert status == OverallStatus.FAIL

    @given(
        fail_results=st.lists(
            track_test_result_with_status(
                status=TrackTestStatus.FAIL
            ),
            min_size=1,
            max_size=5,
        ),
        timeout_results=st.lists(
            track_test_result_with_status(
                status=TrackTestStatus.TIMEOUT
            ),
            min_size=1,
            max_size=5,
        ),
    )
    @settings(max_examples=100)
    def test_mix_fail_timeout_returns_fail(
        self, fail_results, timeout_results
    ):
        """**Validates: Requirements 7.2**

        Quando a lista contém apenas FAIL e TIMEOUT (sem PASS),
        overall_status deve ser FAIL.
        """
        rg = _make_report_generator()
        combined = fail_results + timeout_results
        status = rg._calculate_overall_status(combined)
        assert status == OverallStatus.FAIL

    @given(
        pass_results=st.lists(
            track_test_result_with_status(
                status=TrackTestStatus.PASS
            ),
            min_size=1,
            max_size=5,
        ),
        fail_results=st.lists(
            track_test_result_with_status(
                status=st.sampled_from(
                    [TrackTestStatus.FAIL, TrackTestStatus.TIMEOUT]
                )
            ),
            min_size=1,
            max_size=5,
        ),
    )
    @settings(max_examples=100)
    def test_mix_pass_and_fail_returns_partial(
        self, pass_results, fail_results
    ):
        """**Validates: Requirements 7.2**

        Quando há pelo menos um PASS e pelo menos um FAIL/TIMEOUT,
        overall_status deve ser PARTIAL.
        """
        rg = _make_report_generator()
        combined = pass_results + fail_results
        status = rg._calculate_overall_status(combined)
        assert status == OverallStatus.PARTIAL

    @given(data=st.data())
    @settings(max_examples=100)
    def test_empty_list_returns_pass(self, data):
        """**Validates: Requirements 7.2**

        Lista vazia de resultados deve retornar PASS
        (sem falhas = sem problemas).
        """
        rg = _make_report_generator()
        status = rg._calculate_overall_status([])
        assert status == OverallStatus.PASS

    @given(
        results=st.lists(
            track_test_result_with_status(),
            min_size=1,
            max_size=10,
        )
    )
    @settings(max_examples=100, deadline=None)
    def test_overall_status_exhaustive_classification(self, results):
        """**Validates: Requirements 7.2**

        Para qualquer lista não-vazia, o status calculado deve ser
        consistente com as regras definidas.
        """
        rg = _make_report_generator()
        status = rg._calculate_overall_status(results)

        statuses = [r.status for r in results]
        all_pass = all(s == TrackTestStatus.PASS for s in statuses)
        all_fail_or_timeout = all(
            s in {TrackTestStatus.FAIL, TrackTestStatus.TIMEOUT}
            for s in statuses
        )

        if all_pass:
            assert status == OverallStatus.PASS
        elif all_fail_or_timeout:
            assert status == OverallStatus.FAIL
        else:
            assert status == OverallStatus.PARTIAL


# ============================================================
# Property 12: Consolidated Report Aggregation
# ============================================================


class TestConsolidatedReportAggregation:
    """Feature: audio-subtitle-monitoring, Property 12: Consolidated Report Aggregation

    **Validates: Requirements 9.4**

    Para qualquer lista de ChannelTestReports:
    - total_channels == len(channel_reports)
    - channels_pass == count(overall_status == PASS)
    - channels_partial == count(overall_status == PARTIAL)
    - channels_fail == count(overall_status == FAIL)
    """

    @given(
        reports=st.lists(
            channel_test_report_with_status(),
            min_size=0,
            max_size=10,
        )
    )
    @settings(max_examples=100)
    def test_total_channels_equals_list_length(self, reports):
        """**Validates: Requirements 9.4**

        total_channels deve ser igual ao número de relatórios na lista.
        """
        rg = _make_report_generator()
        consolidated = rg.create_consolidated_report(reports)

        assert consolidated.total_channels == len(reports)

    @given(
        reports=st.lists(
            channel_test_report_with_status(),
            min_size=0,
            max_size=10,
        )
    )
    @settings(max_examples=100)
    def test_channels_pass_count_correct(self, reports):
        """**Validates: Requirements 9.4**

        channels_pass deve contar corretamente os relatórios com PASS.
        """
        rg = _make_report_generator()
        consolidated = rg.create_consolidated_report(reports)

        expected_pass = sum(
            1 for r in reports
            if r.overall_status == OverallStatus.PASS
        )
        assert consolidated.channels_pass == expected_pass

    @given(
        reports=st.lists(
            channel_test_report_with_status(),
            min_size=0,
            max_size=10,
        )
    )
    @settings(max_examples=100)
    def test_channels_partial_count_correct(self, reports):
        """**Validates: Requirements 9.4**

        channels_partial deve contar corretamente os relatórios com PARTIAL.
        """
        rg = _make_report_generator()
        consolidated = rg.create_consolidated_report(reports)

        expected_partial = sum(
            1 for r in reports
            if r.overall_status == OverallStatus.PARTIAL
        )
        assert consolidated.channels_partial == expected_partial

    @given(
        reports=st.lists(
            channel_test_report_with_status(),
            min_size=0,
            max_size=10,
        )
    )
    @settings(max_examples=100)
    def test_channels_fail_count_correct(self, reports):
        """**Validates: Requirements 9.4**

        channels_fail deve contar corretamente os relatórios com FAIL.
        """
        rg = _make_report_generator()
        consolidated = rg.create_consolidated_report(reports)

        expected_fail = sum(
            1 for r in reports
            if r.overall_status == OverallStatus.FAIL
        )
        assert consolidated.channels_fail == expected_fail

    @given(
        reports=st.lists(
            channel_test_report_with_status(),
            min_size=0,
            max_size=10,
        )
    )
    @settings(max_examples=100)
    def test_counters_sum_equals_total(self, reports):
        """**Validates: Requirements 9.4**

        A soma de channels_pass + channels_partial + channels_fail
        deve ser igual a total_channels.
        """
        rg = _make_report_generator()
        consolidated = rg.create_consolidated_report(reports)

        total_from_counters = (
            consolidated.channels_pass
            + consolidated.channels_partial
            + consolidated.channels_fail
        )
        assert total_from_counters == consolidated.total_channels

    @given(
        reports=st.lists(
            channel_test_report_with_status(),
            min_size=1,
            max_size=10,
        )
    )
    @settings(max_examples=100)
    def test_total_duration_is_sum_of_individual(self, reports):
        """**Validates: Requirements 9.4**

        total_duration_ms deve ser a soma das durações individuais.
        """
        rg = _make_report_generator()
        consolidated = rg.create_consolidated_report(reports)

        expected_duration = sum(r.duration_ms for r in reports)
        assert consolidated.total_duration_ms == expected_duration

    @given(
        reports=st.lists(
            channel_test_report_with_status(),
            min_size=0,
            max_size=10,
        )
    )
    @settings(max_examples=100)
    def test_channel_reports_preserved(self, reports):
        """**Validates: Requirements 9.4**

        A lista channel_reports no consolidado deve conter
        todos os relatórios fornecidos.
        """
        rg = _make_report_generator()
        consolidated = rg.create_consolidated_report(reports)

        assert consolidated.channel_reports == reports
