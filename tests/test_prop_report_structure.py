# Feature: widevine-poc, Property 15: Estrutura do relatório
"""Testes de propriedade para a estrutura do relatório.

Validates: Requirements 11.1, 11.2

Property 15: Para qualquer conjunto de ValidationResults, o relatório
gerado SHALL conter cada validação com status (PASS|FAIL|SKIPPED),
start_time, end_time, e duration_ms. Para validações com status=FAIL,
SHALL incluir error_message não-vazio e evidence_paths.
"""
from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from src.models import ValidationResult, ValidationStatus
from src.report_generator import ReportGenerator


# =============================================================================
# Estratégias de geração de dados
# =============================================================================

validation_names_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "Pd")),
    min_size=1,
    max_size=20,
)

status_st = st.sampled_from(
    [ValidationStatus.PASS, ValidationStatus.FAIL, ValidationStatus.SKIPPED]
)

timestamp_st = st.from_regex(
    r"2024-0[1-9]-[012][0-9]T[01][0-9]:[0-5][0-9]:[0-5][0-9]\.\d{3}Z",
    fullmatch=True,
)

duration_ms_st = st.integers(min_value=0, max_value=300_000)

error_message_st = st.text(min_size=1, max_size=100)

evidence_paths_st = st.lists(
    st.text(min_size=1, max_size=50), min_size=0, max_size=5
)


def validation_result_st():
    """Estratégia para gerar ValidationResult com dados consistentes."""
    return st.builds(
        _build_validation_result,
        name=validation_names_st,
        status=status_st,
        start_time=timestamp_st,
        end_time=timestamp_st,
        duration_ms=duration_ms_st,
        error_message=error_message_st,
        evidence_paths=evidence_paths_st,
    )


def fail_validation_result_st():
    """Estratégia para gerar ValidationResult com status FAIL."""
    return st.builds(
        _build_fail_validation_result,
        name=validation_names_st,
        start_time=timestamp_st,
        end_time=timestamp_st,
        duration_ms=duration_ms_st,
        error_message=error_message_st,
        evidence_paths=st.lists(
            st.text(min_size=1, max_size=50), min_size=1, max_size=5
        ),
    )


def _build_validation_result(
    name: str,
    status: ValidationStatus,
    start_time: str,
    end_time: str,
    duration_ms: int,
    error_message: str,
    evidence_paths: list[str],
) -> ValidationResult:
    """Constrói ValidationResult com error_message para FAIL."""
    if status == ValidationStatus.FAIL:
        return ValidationResult(
            name=name,
            status=status,
            start_time=start_time,
            end_time=end_time,
            duration_ms=duration_ms,
            error_message=error_message,
            evidence_paths=evidence_paths,
        )
    return ValidationResult(
        name=name,
        status=status,
        start_time=start_time,
        end_time=end_time,
        duration_ms=duration_ms,
    )


def _build_fail_validation_result(
    name: str,
    start_time: str,
    end_time: str,
    duration_ms: int,
    error_message: str,
    evidence_paths: list[str],
) -> ValidationResult:
    """Constrói ValidationResult com status FAIL garantido."""
    return ValidationResult(
        name=name,
        status=ValidationStatus.FAIL,
        start_time=start_time,
        end_time=end_time,
        duration_ms=duration_ms,
        error_message=error_message,
        evidence_paths=evidence_paths,
    )


validation_list_st = st.lists(
    validation_result_st(), min_size=1, max_size=10
)


# =============================================================================
# Propriedade 1: Cada validação tem campos obrigatórios
# =============================================================================


class TestProperty15CamposObrigatorios:
    """Cada validação no relatório deve ter status, start_time,
    end_time e duration_ms."""

    @settings(max_examples=100)
    @given(results=validation_list_st)
    def test_every_validation_has_required_fields(self, results):
        """**Validates: Requirements 11.1**

        Para qualquer conjunto de ValidationResults, cada validação
        no relatório DEVE conter status, start_time, end_time e
        duration_ms.
        """
        generator = ReportGenerator()
        report = generator.generate(results)

        for validation in report.validations:
            # status deve ser um ValidationStatus válido
            assert validation.status in (
                ValidationStatus.PASS,
                ValidationStatus.FAIL,
                ValidationStatus.SKIPPED,
            ), (
                f"Status inválido para '{validation.name}': "
                f"{validation.status}"
            )

            # start_time deve ser string não-vazia
            assert isinstance(validation.start_time, str)
            assert len(validation.start_time) > 0, (
                f"start_time vazio para '{validation.name}'"
            )

            # end_time deve ser string não-vazia
            assert isinstance(validation.end_time, str)
            assert len(validation.end_time) > 0, (
                f"end_time vazio para '{validation.name}'"
            )

            # duration_ms deve ser inteiro >= 0
            assert isinstance(validation.duration_ms, int)
            assert validation.duration_ms >= 0, (
                f"duration_ms negativo para '{validation.name}': "
                f"{validation.duration_ms}"
            )


# =============================================================================
# Propriedade 2: FAIL inclui error_message e evidence_paths
# =============================================================================


class TestProperty15FailIncluiErroEvidencia:
    """Para validações FAIL com error_message definido, o relatório
    deve preservar error_message e evidence_paths."""

    @settings(max_examples=100)
    @given(
        results=st.lists(
            fail_validation_result_st(), min_size=1, max_size=10
        )
    )
    def test_fail_validations_have_error_and_evidence(self, results):
        """**Validates: Requirements 11.2**

        Para validações com status=FAIL que possuem error_message
        definido, o relatório DEVE preservar error_message não-vazio
        e evidence_paths.
        """
        generator = ReportGenerator()
        report = generator.generate(results)

        for validation in report.validations:
            if validation.status == ValidationStatus.FAIL:
                # error_message deve estar presente e não-vazio
                assert validation.error_message is not None, (
                    f"error_message ausente para FAIL "
                    f"'{validation.name}'"
                )
                assert len(validation.error_message) > 0, (
                    f"error_message vazio para FAIL "
                    f"'{validation.name}'"
                )

                # evidence_paths deve existir como lista
                assert isinstance(
                    validation.evidence_paths, list
                ), (
                    f"evidence_paths não é lista para FAIL "
                    f"'{validation.name}'"
                )


# =============================================================================
# Propriedade 3: Relatório contém todas as validações do input
# =============================================================================


class TestProperty15ContemTodasValidacoes:
    """O relatório deve conter todas as validações fornecidas."""

    @settings(max_examples=100)
    @given(results=validation_list_st)
    def test_report_contains_all_input_validations(self, results):
        """**Validates: Requirements 11.1**

        Para qualquer lista de ValidationResults fornecida, o
        relatório gerado DEVE conter todas as validações da lista
        de entrada (mesmo número de itens).
        """
        generator = ReportGenerator()
        report = generator.generate(results)

        # O relatório deve conter o mesmo número de validações
        assert len(report.validations) == len(results), (
            f"Relatório tem {len(report.validations)} validações, "
            f"mas foram fornecidas {len(results)}"
        )

        # Todos os nomes de entrada devem estar no relatório
        input_names = [r.name for r in results]
        output_names = [v.name for v in report.validations]

        for name in input_names:
            assert name in output_names, (
                f"Validação '{name}' não encontrada no relatório"
            )
