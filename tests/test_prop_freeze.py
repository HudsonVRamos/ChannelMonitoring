# Feature: widevine-poc, Property 9: Classificação de freeze
"""Property-based test para classificação de freeze.

Valida que o sistema classifica corretamente o estado de freeze
combinando similaridade visual (SSIM) e telemetria do player:
- Similaridade > 0.98 + currentTime diff < 0.5 + janela >= 5.0s → FREEZE_CONFIRMED
- Similaridade > 0.98 + currentTime diff >= 0.5 → STATIC_CONTENT
- Similaridade baixa (frames diferentes) → NO_FREEZE
- Similaridade sempre no range [0.0, 1.0]
- Similaridade > 0.98 + currentTime diff < 0.5 + janela < 5.0s → STATIC_CONTENT

**Validates: Requirements 6.1, 6.2, 6.3**
"""
import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st

from src.models import FreezeClassification
from src.opencv_analyzer import OpenCVAnalyzer


# Strategies reutilizáveis
# currentTime diff < 0.5 (indica player travado)
small_time_diff = st.floats(min_value=0.0, max_value=0.49)

# currentTime diff >= 0.5 (indica player avançando)
large_time_diff = st.floats(min_value=0.5, max_value=10.0)

# Janela de observação >= 5.0s (suficiente para confirmar freeze)
sufficient_window = st.floats(min_value=5.0, max_value=60.0)

# Janela de observação < 5.0s (insuficiente para confirmar)
insufficient_window = st.floats(
    min_value=0.1, max_value=4.99
)


def _create_uniform_frame(value: int = 128) -> np.ndarray:
    """Cria frame uniforme 100x100 BGR com valor controlado.

    Args:
        value: Valor de pixel (0-255) para preencher o frame.

    Returns:
        Frame numpy array 100x100 BGR.
    """
    return np.full((100, 100, 3), value, dtype=np.uint8)


class TestFreezeClassification:
    """Testes de propriedade para classificação de freeze."""

    @settings(max_examples=100)
    @given(
        current_time_diff=small_time_diff,
        observation_window=sufficient_window,
    )
    def test_identical_frames_small_diff_sufficient_window_is_freeze(
        self,
        current_time_diff: float,
        observation_window: float,
    ) -> None:
        """Frames idênticos + currentTime diff < 0.5 + janela >= 5.0s → FREEZE_CONFIRMED.

        Para quaisquer dois frames idênticos, se a diferença de currentTime
        é menor que 0.5s e a janela de observação é >= 5.0s, o sistema
        SHALL classificar como FREEZE_CONFIRMED.

        **Validates: Requirements 6.2**
        """
        frame = _create_uniform_frame(128)
        frame_copy = frame.copy()
        analyzer = OpenCVAnalyzer()

        result = analyzer.detect_freeze(
            frame, frame_copy, current_time_diff, observation_window
        )

        assert result.classification == FreezeClassification.FREEZE_CONFIRMED, (
            f"Frames idênticos com time_diff={current_time_diff:.3f} (<0.5) "
            f"e window={observation_window:.1f} (>=5.0) deveria ser "
            f"FREEZE_CONFIRMED, mas obteve {result.classification.value}"
        )

    @settings(max_examples=100)
    @given(
        current_time_diff=large_time_diff,
        observation_window=sufficient_window,
    )
    def test_identical_frames_large_diff_is_static_content(
        self,
        current_time_diff: float,
        observation_window: float,
    ) -> None:
        """Frames idênticos + currentTime diff >= 0.5 → STATIC_CONTENT.

        Para quaisquer dois frames idênticos, se a diferença de currentTime
        é >= 0.5s (player está avançando), o sistema SHALL classificar
        como STATIC_CONTENT (sem alerta).

        **Validates: Requirements 6.3**
        """
        frame = _create_uniform_frame(128)
        frame_copy = frame.copy()
        analyzer = OpenCVAnalyzer()

        result = analyzer.detect_freeze(
            frame, frame_copy, current_time_diff, observation_window
        )

        assert result.classification == FreezeClassification.STATIC_CONTENT, (
            f"Frames idênticos com time_diff={current_time_diff:.3f} (>=0.5) "
            f"deveria ser STATIC_CONTENT, mas obteve "
            f"{result.classification.value}"
        )

    @settings(max_examples=100)
    @given(
        seed_a=st.integers(min_value=0, max_value=2**32 - 1),
        seed_b=st.integers(min_value=0, max_value=2**32 - 1),
        current_time_diff=st.floats(min_value=0.0, max_value=10.0),
        observation_window=sufficient_window,
    )
    def test_very_different_frames_is_no_freeze(
        self,
        seed_a: int,
        seed_b: int,
        current_time_diff: float,
        observation_window: float,
    ) -> None:
        """Frames muito diferentes → NO_FREEZE (similaridade baixa).

        Para quaisquer dois frames com pixels aleatórios diferentes,
        a similaridade será baixa e o sistema SHALL classificar como
        NO_FREEZE.

        **Validates: Requirements 6.1**
        """
        rng_a = np.random.default_rng(seed_a)
        rng_b = np.random.default_rng(seed_b + 1)  # Garantir seed diferente

        frame_a = rng_a.integers(
            0, 256, size=(100, 100, 3), dtype=np.uint8
        )
        frame_b = rng_b.integers(
            0, 256, size=(100, 100, 3), dtype=np.uint8
        )

        analyzer = OpenCVAnalyzer()
        result = analyzer.detect_freeze(
            frame_a, frame_b, current_time_diff, observation_window
        )

        assert result.classification == FreezeClassification.NO_FREEZE, (
            f"Frames aleatórios diferentes deveriam ser NO_FREEZE, "
            f"mas obteve {result.classification.value} "
            f"(similarity={result.similarity:.4f})"
        )

    @settings(max_examples=100)
    @given(
        value_a=st.integers(min_value=0, max_value=255),
        value_b=st.integers(min_value=0, max_value=255),
        current_time_diff=st.floats(min_value=0.0, max_value=10.0),
        observation_window=st.floats(min_value=0.1, max_value=60.0),
    )
    def test_similarity_always_in_valid_range(
        self,
        value_a: int,
        value_b: int,
        current_time_diff: float,
        observation_window: float,
    ) -> None:
        """Similaridade DEVE estar sempre no range [0.0, 1.0].

        Para quaisquer dois frames válidos de mesmas dimensões,
        o sistema SHALL produzir similaridade no range [0.0, 1.0].

        **Validates: Requirements 6.1**
        """
        frame_a = _create_uniform_frame(value_a)
        frame_b = _create_uniform_frame(value_b)
        analyzer = OpenCVAnalyzer()

        result = analyzer.detect_freeze(
            frame_a, frame_b, current_time_diff, observation_window
        )

        assert 0.0 <= result.similarity <= 1.0, (
            f"Similaridade {result.similarity} está fora do range "
            f"[0.0, 1.0] para frames com valores {value_a} e {value_b}"
        )

    @settings(max_examples=100)
    @given(
        current_time_diff=small_time_diff,
        observation_window=insufficient_window,
    )
    def test_identical_frames_small_diff_insufficient_window_is_static(
        self,
        current_time_diff: float,
        observation_window: float,
    ) -> None:
        """Frames idênticos + currentTime diff < 0.5 + janela < 5.0s → STATIC_CONTENT.

        Quando a janela de observação é insuficiente (< 5.0s),
        mesmo com frames idênticos e currentTime parado, o sistema
        SHALL classificar como STATIC_CONTENT (observação insuficiente
        para confirmar freeze).

        **Validates: Requirements 6.2**
        """
        frame = _create_uniform_frame(128)
        frame_copy = frame.copy()
        analyzer = OpenCVAnalyzer()

        result = analyzer.detect_freeze(
            frame, frame_copy, current_time_diff, observation_window
        )

        assert result.classification == FreezeClassification.STATIC_CONTENT, (
            f"Frames idênticos com time_diff={current_time_diff:.3f} (<0.5) "
            f"e window={observation_window:.1f} (<5.0) deveria ser "
            f"STATIC_CONTENT (observação insuficiente), mas obteve "
            f"{result.classification.value}"
        )
