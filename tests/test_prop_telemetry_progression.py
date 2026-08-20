# Feature: widevine-poc, Property 2: Validação de progressão do currentTime
"""Property-based test para validação de progressão do currentTime.

Valida que a classificação de progressão entre amostras consecutivas
de telemetria é consistente com os thresholds definidos:
- diff >= 1.0: "healthy" (reprodução normal)
- 0.5 <= diff < 1.0: "degraded" (reprodução lenta)
- diff < 0.5: "potential_stall" (possível travamento)

**Validates: Requirements 2.3**
"""
from hypothesis import given, settings
from hypothesis import strategies as st


def classify_progression(
    current_time_diff: float, interval_seconds: float = 2.0
) -> str:
    """Classifica progressão do currentTime entre amostras consecutivas.

    Args:
        current_time_diff: Diferença de currentTime entre duas amostras.
        interval_seconds: Intervalo esperado entre amostras.

    Returns:
        "healthy" se diff >= 1.0
        "potential_stall" se diff < 0.5
        "degraded" se 0.5 <= diff < 1.0
    """
    if current_time_diff >= 1.0:
        return "healthy"
    elif current_time_diff < 0.5:
        return "potential_stall"
    else:
        return "degraded"


class TestClassifyProgression:
    """Testes de propriedade para classify_progression."""

    @settings(max_examples=100)
    @given(
        diff=st.floats(
            min_value=1.0,
            max_value=1000.0,
            allow_nan=False,
            allow_infinity=False,
        )
    )
    def test_healthy_classification_for_diff_gte_1(self, diff: float) -> None:
        """Para qualquer diff >= 1.0, classificação DEVE ser 'healthy'.

        Valida que durante reprodução ativa com intervalo de 2 segundos,
        qualquer diferença de currentTime >= 1.0 segundo indica reprodução
        saudável.

        **Validates: Requirements 2.3**
        """
        result = classify_progression(diff)
        assert result == "healthy", (
            f"diff={diff} deveria ser 'healthy', mas obteve '{result}'"
        )

    @settings(max_examples=100)
    @given(
        diff=st.floats(
            min_value=-100.0,
            max_value=0.4999999999,
            allow_nan=False,
            allow_infinity=False,
        )
    )
    def test_potential_stall_for_diff_lt_05(self, diff: float) -> None:
        """Para qualquer diff < 0.5, classificação DEVE ser 'potential_stall'.

        Valida que se a diferença de currentTime entre amostras consecutivas
        é menor que 0.5 segundos, o estado é classificado como potencial
        travamento (stall).

        **Validates: Requirements 2.3**
        """
        result = classify_progression(diff)
        assert result == "potential_stall", (
            f"diff={diff} deveria ser 'potential_stall', mas obteve '{result}'"
        )

    @settings(max_examples=100)
    @given(
        diff=st.floats(
            min_value=0.5,
            max_value=0.9999999999,
            allow_nan=False,
            allow_infinity=False,
        )
    )
    def test_degraded_for_diff_between_05_and_1(self, diff: float) -> None:
        """Para qualquer 0.5 <= diff < 1.0, classificação DEVE ser 'degraded'.

        Valida a zona intermediária onde a reprodução está abaixo do esperado
        mas não é considerada um stall completo.

        **Validates: Requirements 2.3**
        """
        result = classify_progression(diff)
        assert result == "degraded", (
            f"diff={diff} deveria ser 'degraded', mas obteve '{result}'"
        )

    @settings(max_examples=100)
    @given(
        diff=st.floats(
            min_value=-1000.0,
            max_value=1000.0,
            allow_nan=False,
            allow_infinity=False,
        )
    )
    def test_classification_boundaries_are_exhaustive(
        self, diff: float
    ) -> None:
        """Para qualquer diff válido, a classificação DEVE ser um dos três estados.

        Valida que não existe nenhum valor de diff que escape da classificação,
        garantindo que as boundaries cobrem todo o espaço de entrada.

        **Validates: Requirements 2.3**
        """
        result = classify_progression(diff)
        assert result in {"healthy", "degraded", "potential_stall"}, (
            f"diff={diff} retornou classificação inesperada: '{result}'"
        )

    @settings(max_examples=100)
    @given(
        diff=st.floats(
            min_value=1.0,
            max_value=1000.0,
            allow_nan=False,
            allow_infinity=False,
        ),
        interval=st.floats(
            min_value=0.5,
            max_value=10.0,
            allow_nan=False,
            allow_infinity=False,
        ),
    )
    def test_interval_parameter_does_not_affect_classification(
        self, diff: float, interval: float
    ) -> None:
        """O parâmetro interval_seconds não altera a classificação baseada em diff.

        Valida que a classificação depende exclusivamente do current_time_diff,
        independente do intervalo de coleta configurado.

        **Validates: Requirements 2.3**
        """
        result = classify_progression(diff, interval_seconds=interval)
        assert result == "healthy", (
            f"diff={diff}, interval={interval}: deveria ser 'healthy', "
            f"mas obteve '{result}'"
        )

    def test_exact_boundary_1_is_healthy(self) -> None:
        """O valor exato diff=1.0 DEVE ser classificado como 'healthy'."""
        assert classify_progression(1.0) == "healthy"

    def test_exact_boundary_05_is_degraded(self) -> None:
        """O valor exato diff=0.5 DEVE ser classificado como 'degraded'."""
        assert classify_progression(0.5) == "degraded"

    def test_zero_diff_is_potential_stall(self) -> None:
        """diff=0.0 (sem progressão) DEVE ser 'potential_stall'."""
        assert classify_progression(0.0) == "potential_stall"

    def test_negative_diff_is_potential_stall(self) -> None:
        """diff negativo (seek backward) DEVE ser 'potential_stall'."""
        assert classify_progression(-1.0) == "potential_stall"
