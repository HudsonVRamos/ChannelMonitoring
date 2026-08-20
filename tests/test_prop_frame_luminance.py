# Feature: widevine-poc, Property 6: Classificação de luminância de frame
"""Property-based test para classificação de luminância de frame.

Valida que o sistema classifica corretamente frames baseado na
média de luminância:
- Luminância > 16: is_valid=True (contém conteúdo visual)
- Luminância <= 16: is_valid=False (tela preta potencial, descartar)

**Validates: Requirements 4.4, 4.5**
"""
import cv2
import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st

from src.frame_capturer import FrameCapturer, FrameValidation


def _create_frame_png(luminance_value: int) -> bytes:
    """Cria frame PNG uniforme com luminância controlada.

    Args:
        luminance_value: Valor de pixel (0-255) para preencher o frame.

    Returns:
        Bytes do frame encodado em formato PNG.
    """
    img = np.full((720, 1280, 3), luminance_value, dtype=np.uint8)
    success, encoded = cv2.imencode(".png", img)
    assert success, "Falha ao encodar frame PNG"
    return encoded.tobytes()


class TestFrameLuminanceClassification:
    """Testes de propriedade para classificação de luminância."""

    @settings(max_examples=100)
    @given(
        luminance=st.integers(min_value=17, max_value=255)
    )
    def test_above_threshold_is_valid(
        self, luminance: int
    ) -> None:
        """Frames com luminância > 16 SHALL ser classificados como válidos.

        Para qualquer frame com média de luminância acima de 16,
        o sistema deve classificar como contendo conteúdo visual
        (is_valid=True).

        **Validates: Requirements 4.4**
        """
        png_bytes = _create_frame_png(luminance)
        capturer = FrameCapturer()
        result = capturer.validate_frame_content(png_bytes)

        assert result.is_valid is True, (
            f"Luminância {luminance} (>16) deveria ser válido, "
            f"mas obteve is_valid={result.is_valid}"
        )
        assert result.mean_luminance > 16.0, (
            f"mean_luminance={result.mean_luminance} deveria ser > 16"
        )

    @settings(max_examples=100)
    @given(
        luminance=st.integers(min_value=0, max_value=16)
    )
    def test_at_or_below_threshold_is_invalid(
        self, luminance: int
    ) -> None:
        """Frames com luminância <= 16 SHALL ser classificados como inválidos.

        Para qualquer frame com média de luminância igual ou inferior a 16,
        o sistema deve classificar como tela preta potencial
        (is_valid=False) e descartar da análise.

        **Validates: Requirements 4.5**
        """
        png_bytes = _create_frame_png(luminance)
        capturer = FrameCapturer()
        result = capturer.validate_frame_content(png_bytes)

        assert result.is_valid is False, (
            f"Luminância {luminance} (<=16) deveria ser inválido, "
            f"mas obteve is_valid={result.is_valid}"
        )
        assert result.mean_luminance <= 16.0, (
            f"mean_luminance={result.mean_luminance} deveria ser <= 16"
        )

    def test_boundary_exactly_16_is_invalid(self) -> None:
        """Boundary: luminância exatamente 16 SHALL ser is_valid=False.

        O threshold é exclusivo (> 16 para válido), portanto
        exatamente 16 deve ser classificado como tela preta.

        **Validates: Requirements 4.4, 4.5**
        """
        png_bytes = _create_frame_png(16)
        capturer = FrameCapturer()
        result = capturer.validate_frame_content(png_bytes)

        assert result.is_valid is False, (
            "Luminância exatamente 16 deveria ser inválido"
        )

    def test_boundary_exactly_17_is_valid(self) -> None:
        """Boundary: luminância exatamente 17 SHALL ser is_valid=True.

        O primeiro valor acima do threshold (17 > 16) deve ser
        classificado como contendo conteúdo visual.

        **Validates: Requirements 4.4, 4.5**
        """
        png_bytes = _create_frame_png(17)
        capturer = FrameCapturer()
        result = capturer.validate_frame_content(png_bytes)

        assert result.is_valid is True, (
            "Luminância exatamente 17 deveria ser válido"
        )

    @settings(max_examples=100)
    @given(
        luminance=st.integers(min_value=0, max_value=255)
    )
    def test_validation_returns_correct_type(
        self, luminance: int
    ) -> None:
        """Para qualquer luminância, o resultado DEVE ser FrameValidation.

        Valida que validate_frame_content sempre retorna um objeto
        FrameValidation com campos corretos independente do input.

        **Validates: Requirements 4.4, 4.5**
        """
        png_bytes = _create_frame_png(luminance)
        capturer = FrameCapturer()
        result = capturer.validate_frame_content(png_bytes)

        assert isinstance(result, FrameValidation)
        assert isinstance(result.is_valid, bool)
        assert isinstance(result.mean_luminance, float)
        assert 0.0 <= result.mean_luminance <= 255.0
        assert result.width == 1280
        assert result.height == 720
