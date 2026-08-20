# Feature: widevine-poc, Property 17: Lógica de skip por dependência
"""Property-based test para lógica de skip por dependência no ReportGenerator.

Valida que o ReportGenerator._apply_skip_logic marca corretamente
validações como SKIPPED quando suas dependências falharam, indicando
no skipped_reason qual dependência impediu a execução.

A lógica de skip só se aplica a validações que NÃO passaram por conta
própria (status != PASS). Se uma validação já passou, ela mantém o PASS
independente do status das dependências.

**Validates: Requirements 11.6**
"""
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from src.report_generator import ReportGenerator, DEPENDENCY_MAP
from src.models import ValidationResult, ValidationStatus


# =============================================================================
# Helpers
# =============================================================================


def _make_validation(name: str, status: ValidationStatus) -> ValidationResult:
    """Cria um ValidationResult com dados mínimos para teste."""
    return ValidationResult(
        name=name,
        status=status,
        start_time="2024-01-15T10:00:00.000Z",
        end_time="2024-01-15T10:00:01.000Z",
        duration_ms=1000,
    )


def _build_results_with_status(
    status_map: dict[str, ValidationStatus],
) -> list[ValidationResult]:
    """Constrói lista de ValidationResult a partir de um mapa nome→status."""
    # Ordem fixa para garantir que dependências vêm antes dos dependentes
    order = ["login", "drm", "telemetry", "frames", "opencv", "bedrock"]
    results = []
    for name in order:
        if name in status_map:
            results.append(_make_validation(name, status_map[name]))
    return results


# =============================================================================
# Strategies
# =============================================================================

# Status que indica "não passou por conta própria" — elegível para skip
non_pass_status = st.sampled_from([ValidationStatus.FAIL, ValidationStatus.SKIPPED])


# =============================================================================
# Property Tests
# =============================================================================


class TestSkipLogicProperty:
    """Property tests para lógica de skip por dependência.

    A regra fundamental: quando uma dependência falha (FAIL ou SKIPPED),
    as validações dependentes que NÃO passaram por conta própria (status != PASS)
    devem ser marcadas como SKIPPED com skipped_reason indicando a dependência.

    **Validates: Requirements 11.6**
    """

    @settings(max_examples=100)
    @given(
        drm_status=non_pass_status,
    )
    def test_login_fail_skips_drm(
        self,
        drm_status: ValidationStatus,
    ) -> None:
        """Quando login=FAIL e drm não passou (FAIL ou SKIPPED),
        drm DEVE ser SKIPPED com "login" no skipped_reason.

        **Validates: Requirements 11.6**
        """
        generator = ReportGenerator(logger=None)

        status_map = {
            "login": ValidationStatus.FAIL,
            "drm": drm_status,
            "telemetry": ValidationStatus.FAIL,
            "frames": ValidationStatus.FAIL,
            "opencv": ValidationStatus.FAIL,
            "bedrock": ValidationStatus.FAIL,
        }
        results = _build_results_with_status(status_map)
        processed = generator._apply_skip_logic(results)

        drm_result = next(r for r in processed if r.name == "drm")

        assert drm_result.status == ValidationStatus.SKIPPED, (
            f"drm deveria ser SKIPPED quando login=FAIL e drm={drm_status.value}, "
            f"obteve {drm_result.status.value}"
        )
        assert drm_result.skipped_reason is not None
        assert "login" in drm_result.skipped_reason, (
            f"skipped_reason deveria mencionar 'login', "
            f"obteve: {drm_result.skipped_reason}"
        )

    @settings(max_examples=100)
    @given(
        telemetry_status=non_pass_status,
        frames_status=non_pass_status,
    )
    def test_drm_fail_skips_telemetry_and_frames(
        self,
        telemetry_status: ValidationStatus,
        frames_status: ValidationStatus,
    ) -> None:
        """Quando drm=FAIL (com login=PASS), telemetry e frames que não
        passaram DEVEM ser SKIPPED com "drm" no skipped_reason.

        **Validates: Requirements 11.6**
        """
        generator = ReportGenerator(logger=None)

        status_map = {
            "login": ValidationStatus.PASS,
            "drm": ValidationStatus.FAIL,
            "telemetry": telemetry_status,
            "frames": frames_status,
            "opencv": ValidationStatus.FAIL,
            "bedrock": ValidationStatus.FAIL,
        }
        results = _build_results_with_status(status_map)
        processed = generator._apply_skip_logic(results)

        # Verificar telemetry
        telemetry_result = next(r for r in processed if r.name == "telemetry")
        assert telemetry_result.status == ValidationStatus.SKIPPED, (
            f"telemetry deveria ser SKIPPED quando drm=FAIL e "
            f"telemetry={telemetry_status.value}, "
            f"obteve {telemetry_result.status.value}"
        )
        assert telemetry_result.skipped_reason is not None
        assert "drm" in telemetry_result.skipped_reason, (
            f"skipped_reason de telemetry deveria mencionar 'drm', "
            f"obteve: {telemetry_result.skipped_reason}"
        )

        # Verificar frames
        frames_result = next(r for r in processed if r.name == "frames")
        assert frames_result.status == ValidationStatus.SKIPPED, (
            f"frames deveria ser SKIPPED quando drm=FAIL e "
            f"frames={frames_status.value}, "
            f"obteve {frames_result.status.value}"
        )
        assert frames_result.skipped_reason is not None
        assert "drm" in frames_result.skipped_reason, (
            f"skipped_reason de frames deveria mencionar 'drm', "
            f"obteve: {frames_result.skipped_reason}"
        )

    @settings(max_examples=100)
    @given(
        opencv_status=non_pass_status,
    )
    def test_frames_fail_skips_opencv(
        self,
        opencv_status: ValidationStatus,
    ) -> None:
        """Quando frames=FAIL (com login e drm PASS), opencv que não
        passou DEVE ser SKIPPED com "frames" no skipped_reason.

        **Validates: Requirements 11.6**
        """
        generator = ReportGenerator(logger=None)

        status_map = {
            "login": ValidationStatus.PASS,
            "drm": ValidationStatus.PASS,
            "telemetry": ValidationStatus.PASS,
            "frames": ValidationStatus.FAIL,
            "opencv": opencv_status,
            "bedrock": ValidationStatus.FAIL,
        }
        results = _build_results_with_status(status_map)
        processed = generator._apply_skip_logic(results)

        opencv_result = next(r for r in processed if r.name == "opencv")

        assert opencv_result.status == ValidationStatus.SKIPPED, (
            f"opencv deveria ser SKIPPED quando frames=FAIL e "
            f"opencv={opencv_status.value}, "
            f"obteve {opencv_result.status.value}"
        )
        assert opencv_result.skipped_reason is not None
        assert "frames" in opencv_result.skipped_reason, (
            f"skipped_reason de opencv deveria mencionar 'frames', "
            f"obteve: {opencv_result.skipped_reason}"
        )

    @settings(max_examples=100)
    @given(
        bedrock_status=non_pass_status,
    )
    def test_opencv_fail_skips_bedrock(
        self,
        bedrock_status: ValidationStatus,
    ) -> None:
        """Quando opencv=FAIL (com login, drm e frames PASS), bedrock que
        não passou DEVE ser SKIPPED com "opencv" no skipped_reason.

        **Validates: Requirements 11.6**
        """
        generator = ReportGenerator(logger=None)

        status_map = {
            "login": ValidationStatus.PASS,
            "drm": ValidationStatus.PASS,
            "telemetry": ValidationStatus.PASS,
            "frames": ValidationStatus.PASS,
            "opencv": ValidationStatus.FAIL,
            "bedrock": bedrock_status,
        }
        results = _build_results_with_status(status_map)
        processed = generator._apply_skip_logic(results)

        bedrock_result = next(r for r in processed if r.name == "bedrock")

        assert bedrock_result.status == ValidationStatus.SKIPPED, (
            f"bedrock deveria ser SKIPPED quando opencv=FAIL e "
            f"bedrock={bedrock_status.value}, "
            f"obteve {bedrock_result.status.value}"
        )
        assert bedrock_result.skipped_reason is not None
        assert "opencv" in bedrock_result.skipped_reason, (
            f"skipped_reason de bedrock deveria mencionar 'opencv', "
            f"obteve: {bedrock_result.skipped_reason}"
        )

    @settings(max_examples=100)
    @given(
        drm_status=st.sampled_from([ValidationStatus.PASS, ValidationStatus.FAIL]),
        telemetry_status=st.sampled_from([ValidationStatus.PASS, ValidationStatus.FAIL]),
        frames_status=st.sampled_from([ValidationStatus.PASS, ValidationStatus.FAIL]),
        opencv_status=st.sampled_from([ValidationStatus.PASS, ValidationStatus.FAIL]),
        bedrock_status=st.sampled_from([ValidationStatus.PASS, ValidationStatus.FAIL]),
    )
    def test_all_deps_pass_no_skip(
        self,
        drm_status: ValidationStatus,
        telemetry_status: ValidationStatus,
        frames_status: ValidationStatus,
        opencv_status: ValidationStatus,
        bedrock_status: ValidationStatus,
    ) -> None:
        """Quando TODAS as dependências de uma validação são PASS,
        essa validação NÃO deve ser SKIPPED (independente do seu próprio status).

        Para cada validação no DEPENDENCY_MAP, se todas as suas dependências
        diretas passaram, ela nunca será marcada como SKIPPED pela lógica de skip.

        **Validates: Requirements 11.6**
        """
        generator = ReportGenerator(logger=None)

        # Todas as validações que são dependências de outras são PASS
        status_map = {
            "login": ValidationStatus.PASS,
            "drm": drm_status,
            "telemetry": telemetry_status,
            "frames": frames_status,
            "opencv": opencv_status,
            "bedrock": bedrock_status,
        }
        results = _build_results_with_status(status_map)
        processed = generator._apply_skip_logic(results)

        # Verificar: para cada validação, se TODAS as suas deps diretas são PASS,
        # essa validação NÃO deve ser SKIPPED
        processed_map = {r.name: r for r in processed}
        for name, deps in DEPENDENCY_MAP.items():
            if name not in status_map:
                continue
            all_deps_pass = all(
                status_map.get(dep) == ValidationStatus.PASS for dep in deps
            )
            if all_deps_pass:
                result = processed_map[name]
                assert result.status != ValidationStatus.SKIPPED, (
                    f"Validação '{name}' não deveria ser SKIPPED "
                    f"quando todas as suas dependências {deps} passam, "
                    f"obteve status={result.status.value}"
                )
