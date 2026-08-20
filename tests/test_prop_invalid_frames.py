# Feature: widevine-poc, Property 8: Tratamento de frames inválidos
"""Property-based test para tratamento de frames inválidos.

Valida que para qualquer frame inválido (None, empty array, zero dimensions,
wrong type), o OpenCVAnalyzer SHALL retornar ANALYSIS_ERROR sem exceção
não tratada e sem classificar o frame.

**Validates: Requirements 5.4, 6.4**
"""
from __future__ import annotations

import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st

from src.opencv_analyzer import OpenCVAnalyzer
from src.models import FreezeClassification


class TestInvalidFrameBlackScreen:
    """Testes de propriedade para detect_black_screen com frames inválidos."""

    def test_none_frame_returns_result_without_exception(self) -> None:
        """None → detect_black_screen retorna resultado sem exceção.

        Quando o frame é None, o sistema deve retornar um
        BlackScreenResult sem classificar como tela preta.

        **Validates: Requirements 5.4**
        """
        analyzer = OpenCVAnalyzer()
        result = analyzer.detect_black_screen(None)

        assert result.is_black_screen is False, (
            "Frame None não deve ser classificado como tela preta"
        )
        assert result.is_dark_scene is False, (
            "Frame None não deve ser classificado como cena escura"
        )

    def test_empty_array_returns_result_without_exception(self) -> None:
        """Empty array → detect_black_screen retorna resultado sem exceção.

        Quando o frame é um array vazio, o sistema deve retornar
        um resultado sem classificar.

        **Validates: Requirements 5.4**
        """
        empty_frame = np.array([], dtype=np.uint8)
        analyzer = OpenCVAnalyzer()
        result = analyzer.detect_black_screen(empty_frame)

        assert result.is_black_screen is False, (
            "Frame vazio não deve ser classificado como tela preta"
        )
        assert result.is_dark_scene is False, (
            "Frame vazio não deve ser classificado como cena escura"
        )

    @settings(max_examples=100)
    @given(
        invalid_input=st.one_of(
            st.text(min_size=0, max_size=50),
            st.integers(),
            st.lists(st.integers(), max_size=10),
        )
    )
    def test_non_ndarray_types_returns_result_without_exception(
        self, invalid_input
    ) -> None:
        """Non-ndarray types → detect_black_screen retorna sem exceção.

        Para qualquer input que não é numpy ndarray (string, int, list),
        o sistema deve retornar resultado sem classificar.

        **Validates: Requirements 5.4**
        """
        analyzer = OpenCVAnalyzer()
        result = analyzer.detect_black_screen(invalid_input)

        assert result.is_black_screen is False, (
            f"Input tipo {type(invalid_input).__name__} não deve "
            f"ser classificado como tela preta"
        )
        assert result.is_dark_scene is False, (
            f"Input tipo {type(invalid_input).__name__} não deve "
            f"ser classificado como cena escura"
        )


class TestInvalidFrameFreeze:
    """Testes de propriedade para detect_freeze com frames inválidos."""

    def test_none_frame_returns_analysis_error(self) -> None:
        """None → detect_freeze retorna ANALYSIS_ERROR.

        Quando qualquer frame é None, o sistema deve retornar
        FreezeClassification.ANALYSIS_ERROR sem exceção.

        **Validates: Requirements 6.4**
        """
        analyzer = OpenCVAnalyzer()

        # Ambos None
        result = analyzer.detect_freeze(None, None, current_time_diff=0.0)
        assert result.classification == FreezeClassification.ANALYSIS_ERROR, (
            "Frames None devem resultar em ANALYSIS_ERROR"
        )

        # Apenas frame_a None
        valid_frame = np.zeros((100, 100, 3), dtype=np.uint8)
        result = analyzer.detect_freeze(
            None, valid_frame, current_time_diff=0.0
        )
        assert result.classification == FreezeClassification.ANALYSIS_ERROR, (
            "frame_a=None deve resultar em ANALYSIS_ERROR"
        )

        # Apenas frame_b None
        result = analyzer.detect_freeze(
            valid_frame, None, current_time_diff=0.0
        )
        assert result.classification == FreezeClassification.ANALYSIS_ERROR, (
            "frame_b=None deve resultar em ANALYSIS_ERROR"
        )

    def test_empty_array_returns_analysis_error(self) -> None:
        """Empty array → detect_freeze retorna ANALYSIS_ERROR.

        Quando qualquer frame é array vazio, o sistema deve retornar
        FreezeClassification.ANALYSIS_ERROR sem exceção.

        **Validates: Requirements 6.4**
        """
        analyzer = OpenCVAnalyzer()
        empty_frame = np.array([], dtype=np.uint8)
        valid_frame = np.zeros((100, 100, 3), dtype=np.uint8)

        # Ambos vazios
        result = analyzer.detect_freeze(
            empty_frame, empty_frame, current_time_diff=0.0
        )
        assert result.classification == FreezeClassification.ANALYSIS_ERROR, (
            "Frames vazios devem resultar em ANALYSIS_ERROR"
        )

        # Apenas frame_a vazio
        result = analyzer.detect_freeze(
            empty_frame, valid_frame, current_time_diff=0.0
        )
        assert result.classification == FreezeClassification.ANALYSIS_ERROR, (
            "frame_a vazio deve resultar em ANALYSIS_ERROR"
        )

        # Apenas frame_b vazio
        result = analyzer.detect_freeze(
            valid_frame, empty_frame, current_time_diff=0.0
        )
        assert result.classification == FreezeClassification.ANALYSIS_ERROR, (
            "frame_b vazio deve resultar em ANALYSIS_ERROR"
        )

    @settings(max_examples=100)
    @given(
        invalid_input=st.one_of(
            st.text(min_size=0, max_size=50),
            st.integers(),
            st.lists(st.integers(), max_size=10),
            st.dictionaries(
                keys=st.text(max_size=5),
                values=st.integers(),
                max_size=3,
            ),
        )
    )
    def test_non_ndarray_types_returns_analysis_error(
        self, invalid_input
    ) -> None:
        """Non-ndarray types → detect_freeze retorna ANALYSIS_ERROR.

        Para qualquer input que não é numpy ndarray (string, int, list, dict),
        o sistema deve retornar ANALYSIS_ERROR sem exceção.

        **Validates: Requirements 6.4**
        """
        analyzer = OpenCVAnalyzer()
        valid_frame = np.zeros((100, 100, 3), dtype=np.uint8)

        # Input inválido como frame_a
        result = analyzer.detect_freeze(
            invalid_input, valid_frame, current_time_diff=0.0
        )
        assert result.classification == FreezeClassification.ANALYSIS_ERROR, (
            f"Input tipo {type(invalid_input).__name__} como frame_a "
            f"deve resultar em ANALYSIS_ERROR"
        )

        # Input inválido como frame_b
        result = analyzer.detect_freeze(
            valid_frame, invalid_input, current_time_diff=0.0
        )
        assert result.classification == FreezeClassification.ANALYSIS_ERROR, (
            f"Input tipo {type(invalid_input).__name__} como frame_b "
            f"deve resultar em ANALYSIS_ERROR"
        )

    @settings(max_examples=100)
    @given(
        h1=st.integers(min_value=50, max_value=200),
        w1=st.integers(min_value=50, max_value=200),
        h2=st.integers(min_value=50, max_value=200),
        w2=st.integers(min_value=50, max_value=200),
    )
    def test_different_dimensions_returns_analysis_error(
        self, h1: int, w1: int, h2: int, w2: int
    ) -> None:
        """Frames com dimensões diferentes → detect_freeze retorna ANALYSIS_ERROR.

        Para quaisquer dois frames com dimensões (height, width) diferentes,
        o sistema não deve classificar como freeze e deve retornar
        ANALYSIS_ERROR.

        **Validates: Requirements 6.4**
        """
        # Garantir que as dimensões são realmente diferentes
        if (h1, w1) == (h2, w2):
            return  # Pular caso as dimensões sejam iguais

        analyzer = OpenCVAnalyzer()
        frame_a = np.zeros((h1, w1, 3), dtype=np.uint8)
        frame_b = np.zeros((h2, w2, 3), dtype=np.uint8)

        result = analyzer.detect_freeze(
            frame_a, frame_b, current_time_diff=0.0
        )
        assert result.classification == FreezeClassification.ANALYSIS_ERROR, (
            f"Frames com dimensões diferentes ({h1}x{w1} vs {h2}x{w2}) "
            f"devem resultar em ANALYSIS_ERROR, "
            f"mas obteve {result.classification}"
        )
        assert result.classification != FreezeClassification.FREEZE_CONFIRMED, (
            "Frames com dimensões diferentes nunca devem ser "
            "classificados como freeze"
        )
