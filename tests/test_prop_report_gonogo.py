# Feature: widevine-poc, Property 16: Decisão Go/No-Go
"""Testes de propriedade para decisão Go/No-Go do ReportGenerator.

Validates: Requirements 11.4

Property 16: Para qualquer conjunto de resultados de validação, se todas
as validações críticas (login, drm, frames, docker) têm status=PASS,
a decisão SHALL ser GO. Se qualquer validação crítica tem status=FAIL
ou SKIPPED, a decisão SHALL ser NO_GO. Se qualquer validação crítica
estiver ausente, a decisão SHALL ser NO_GO.
"""
from __future__ import annotations

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from src.report_generator import ReportGenerator, CRITICAL_VALIDATIONS
from src.models import ValidationResult, ValidationStatus, GoNoGoDecision


# =============================================================================
# Estratégias de geração de dados
# =============================================================================

# Nomes de validações não-críticas possíveis
NON_CRITICAL_NAMES = [
    "telemetry", "opencv", "bedrock", "audio", "subtitles"
]

status_st = st.sampled_from(list(ValidationStatus))

non_critical_status_st = st.sampled_from(list(ValidationStatus))

timestamp_st = st.just("2024-01-01T00:00:00.000Z")


def make_validation_result(
    name: str, status: ValidationStatus
) -> ValidationResult:
    """Cria um ValidationResult com dados mínimos válidos."""
    return ValidationResult(
        name=name,
        status=status,
        start_time="2024-01-01T00:00:00.000Z",
        end_time="2024-01-01T00:00:01.000Z",
        duration_ms=1000,
    )


# Estratégia para gerar lista de validações não-críticas
non_critical_results_st = st.lists(
    st.tuples(
        st.sampled_from(NON_CRITICAL_NAMES),
        non_critical_status_st,
    ),
    min_size=0,
    max_size=5,
    unique_by=lambda x: x[0],
)


# =============================================================================
# Property 16.1: Todas críticas PASS → GO
# =============================================================================


@settings(max_examples=100)
@given(non_critical_results=non_critical_results_st)
def test_all_critical_pass_implies_go(non_critical_results):
    """Se TODAS as validações críticas têm status=PASS,
    decisão SHALL ser GO, independentemente do status das não-críticas.

    **Validates: Requirements 11.4**
    """
    # Montar resultados: todas críticas com PASS
    results = [
        make_validation_result(name, ValidationStatus.PASS)
        for name in CRITICAL_VALIDATIONS
    ]

    # Adicionar validações não-críticas com status variado
    for name, status in non_critical_results:
        results.append(make_validation_result(name, status))

    generator = ReportGenerator()
    report = generator.generate(results)

    assert report.decision == GoNoGoDecision.GO


# =============================================================================
# Property 16.2: Qualquer crítica FAIL → NO_GO
# =============================================================================


@settings(max_examples=100)
@given(
    failing_critical=st.sampled_from(sorted(CRITICAL_VALIDATIONS)),
    other_statuses=st.fixed_dictionaries({}),
    non_critical_results=non_critical_results_st,
)
def test_any_critical_fail_implies_nogo(
    failing_critical, other_statuses, non_critical_results
):
    """Se QUALQUER validação crítica tem status=FAIL,
    decisão SHALL ser NO_GO.

    **Validates: Requirements 11.4**
    """
    results = []

    for name in sorted(CRITICAL_VALIDATIONS):
        if name == failing_critical:
            results.append(
                make_validation_result(name, ValidationStatus.FAIL)
            )
        else:
            results.append(
                make_validation_result(name, ValidationStatus.PASS)
            )

    # Adicionar não-críticas
    for name, status in non_critical_results:
        results.append(make_validation_result(name, status))

    generator = ReportGenerator()
    report = generator.generate(results)

    assert report.decision == GoNoGoDecision.NO_GO


# =============================================================================
# Property 16.3: Qualquer crítica SKIPPED → NO_GO
# =============================================================================


@settings(max_examples=100)
@given(
    skipped_critical=st.sampled_from(sorted(CRITICAL_VALIDATIONS)),
    non_critical_results=non_critical_results_st,
)
def test_any_critical_skipped_implies_nogo(
    skipped_critical, non_critical_results
):
    """Se QUALQUER validação crítica tem status=SKIPPED,
    decisão SHALL ser NO_GO.

    **Validates: Requirements 11.4**
    """
    results = []

    for name in sorted(CRITICAL_VALIDATIONS):
        if name == skipped_critical:
            results.append(
                make_validation_result(name, ValidationStatus.SKIPPED)
            )
        else:
            results.append(
                make_validation_result(name, ValidationStatus.PASS)
            )

    # Adicionar não-críticas
    for name, status in non_critical_results:
        results.append(make_validation_result(name, status))

    generator = ReportGenerator()
    report = generator.generate(results)

    assert report.decision == GoNoGoDecision.NO_GO


# =============================================================================
# Property 16.4: Validação crítica ausente → NO_GO
# =============================================================================


@settings(max_examples=100)
@given(
    missing_critical=st.sampled_from(sorted(CRITICAL_VALIDATIONS)),
    non_critical_results=non_critical_results_st,
)
def test_missing_critical_implies_nogo(
    missing_critical, non_critical_results
):
    """Se QUALQUER validação crítica está AUSENTE dos resultados,
    decisão SHALL ser NO_GO.

    **Validates: Requirements 11.4**
    """
    # Montar resultados: todas críticas com PASS, exceto a ausente
    results = [
        make_validation_result(name, ValidationStatus.PASS)
        for name in sorted(CRITICAL_VALIDATIONS)
        if name != missing_critical
    ]

    # Adicionar não-críticas
    for name, status in non_critical_results:
        results.append(make_validation_result(name, status))

    generator = ReportGenerator()
    report = generator.generate(results)

    assert report.decision == GoNoGoDecision.NO_GO
