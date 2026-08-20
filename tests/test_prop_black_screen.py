"""Property-based test para classificação de tela preta vs cena escura.

# Feature: widevine-poc, Property 7: Classificação de tela preta vs cena escura

Valida que o OpenCVAnalyzer classifica corretamente frames como BLACK_SCREEN,
cena escura legítima, ou conteúdo normal, baseado em luminância, percentual de
pixels pretos e variância.

**Validates: Requirements 5.1, 5.2, 5.3**
"""
from __future__ import annotations

import numpy as np
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from src.opencv_analyzer import OpenCVAnalyzer


# =============================================================================
# Strategies para geração de frames
# =============================================================================

# Valores de pixel para frame uniforme preto (luminância < 10)
st_black_pixel_value = st.integers(min_value=0, max_value=9)

# Valores de pixel para frame normal/claro (luminância >= 50)
st_bright_pixel_value = st.integers(min_value=50, max_value=255)


# =============================================================================
# Property Tests
# =============================================================================


class TestPropertyBlackScreenClassification:
    """Property 7: Classificação de tela preta vs cena escura.

    Para qualquer frame em escala de cinza, o sistema SHALL classificar como
    BLACK_SCREEN se e somente se a média de luminância < threshold (default 10)
    E o percentual de pixels com valor < 20 excede 95% E a variância dos pixels
    é <= 50. Se a variância é > 50, SHALL classificar como cena escura legítima.
    """

    @given(value=st_black_pixel_value)
    @settings(max_examples=100)
    def test_uniform_black_frame_is_black_screen(self, value: int):
        """Frame uniforme com valor 0-9 deve ser classificado como BLACK_SCREEN.

        Luminância < 10, 100% dos pixels < 20, variância = 0.
        """
        analyzer = OpenCVAnalyzer()
        frame = np.full((100, 100, 3), value, dtype=np.uint8)

        result = analyzer.detect_black_screen(frame)

        # Frame uniforme com valor 0-9:
        # - mean_luminance = value < 10 ✓
        # - todos pixels < 20 → black_pixel_percent = 100% > 95% ✓
        # - variância = 0 <= 50 ✓
        assert result.is_black_screen is True
        assert result.is_dark_scene is False
        assert result.luminance.mean_luminance == float(value)
        assert result.luminance.black_pixel_percent == 100.0
        assert result.luminance.pixel_variance == 0.0

    @given(
        low_value=st.integers(min_value=0, max_value=5),
        high_value=st.integers(min_value=60, max_value=150),
        high_ratio=st.floats(min_value=0.3, max_value=0.7),
    )
    @settings(max_examples=100)
    def test_dark_frame_high_variance_is_dark_scene(
        self, low_value: int, high_value: int, high_ratio: float
    ):
        """Frame escuro com alta variância deve ser cena escura, NÃO black screen.

        Mix de valores baixos e altos produz variância > 50, indicando
        distribuição não uniforme (conteúdo visual presente).
        """
        analyzer = OpenCVAnalyzer()

        # Criar frame com mistura de pixels escuros e claros
        frame = np.full((100, 100, 3), low_value, dtype=np.uint8)
        num_high_pixels = int(100 * 100 * high_ratio)

        # Distribuir pixels claros linearmente no frame
        flat_frame = frame.reshape(-1, 3)
        flat_frame[:num_high_pixels] = high_value
        frame = flat_frame.reshape(100, 100, 3)

        # Calcular variância esperada para garantir > 50
        gray_values = np.full(10000, low_value, dtype=np.float64)
        gray_values[:num_high_pixels] = high_value
        expected_variance = float(np.var(gray_values))
        assume(expected_variance > 50.0)

        result = analyzer.detect_black_screen(frame)

        # Variância > 50 → cena escura legítima, não black screen
        assert result.is_dark_scene is True
        assert result.is_black_screen is False
        assert result.luminance.pixel_variance > 50.0

    @given(value=st_bright_pixel_value)
    @settings(max_examples=100)
    def test_bright_uniform_frame_is_neither(self, value: int):
        """Frame claro uniforme (valor >= 50) não é tela preta nem cena escura.

        Luminância alta e variância zero: conteúdo normal.
        """
        analyzer = OpenCVAnalyzer()
        frame = np.full((100, 100, 3), value, dtype=np.uint8)

        result = analyzer.detect_black_screen(frame)

        # Frame claro:
        # - mean_luminance >= 50, muito acima do threshold 10
        # - black_pixel_percent = 0% (todos >= 50, acima de 20)
        # - variância = 0 <= 50, mas luminância alta impede black_screen
        assert result.is_black_screen is False
        assert result.is_dark_scene is False
        assert result.luminance.mean_luminance == float(value)
        assert result.luminance.black_pixel_percent == 0.0
