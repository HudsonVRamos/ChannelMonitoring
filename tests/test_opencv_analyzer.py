"""Testes unitários para o OpenCVAnalyzer.

Valida detecção de tela preta, cena escura, freeze e tratamento de erros.
"""
from __future__ import annotations

import numpy as np
import pytest

from src.models import FreezeClassification
from src.opencv_analyzer import OpenCVAnalyzer


@pytest.fixture
def analyzer() -> OpenCVAnalyzer:
    """Cria instância do analisador com defaults."""
    return OpenCVAnalyzer()


@pytest.fixture
def black_frame() -> np.ndarray:
    """Frame completamente preto (720p BGR)."""
    return np.zeros((720, 1280, 3), dtype=np.uint8)


@pytest.fixture
def white_frame() -> np.ndarray:
    """Frame completamente branco (720p BGR)."""
    return np.ones((720, 1280, 3), dtype=np.uint8) * 255


@pytest.fixture
def gray_frame() -> np.ndarray:
    """Frame cinza médio (720p BGR)."""
    return np.ones((720, 1280, 3), dtype=np.uint8) * 128


@pytest.fixture
def dark_scene_frame() -> np.ndarray:
    """Frame com cena escura mas com variância alta (conteúdo visual)."""
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    # Adicionar variação significativa em algumas regiões
    frame[0:360, 0:640] = 40  # Quadrante com tom mais claro
    frame[360:720, 640:1280] = 60  # Outro quadrante ainda mais claro
    return frame


class TestAnalyzeLuminance:
    """Testes para analyze_luminance."""

    def test_frame_preto_luminancia_zero(self, analyzer: OpenCVAnalyzer, black_frame: np.ndarray):
        """Frame preto deve ter luminância próxima de zero."""
        result = analyzer.analyze_luminance(black_frame)
        assert result.mean_luminance == 0.0
        assert result.black_pixel_percent == 100.0
        assert result.pixel_variance == 0.0

    def test_frame_branco_luminancia_alta(self, analyzer: OpenCVAnalyzer, white_frame: np.ndarray):
        """Frame branco deve ter luminância máxima."""
        result = analyzer.analyze_luminance(white_frame)
        assert result.mean_luminance == 255.0
        assert result.black_pixel_percent == 0.0

    def test_frame_cinza_luminancia_media(self, analyzer: OpenCVAnalyzer, gray_frame: np.ndarray):
        """Frame cinza médio deve ter luminância ~128."""
        result = analyzer.analyze_luminance(gray_frame)
        assert 127.0 <= result.mean_luminance <= 129.0
        assert result.black_pixel_percent == 0.0

    def test_frame_none_raises_error(self, analyzer: OpenCVAnalyzer):
        """Frame None deve lançar ValueError."""
        with pytest.raises(ValueError):
            analyzer.analyze_luminance(None)

    def test_frame_vazio_raises_error(self, analyzer: OpenCVAnalyzer):
        """Frame vazio deve lançar ValueError."""
        empty = np.array([], dtype=np.uint8)
        with pytest.raises(ValueError):
            analyzer.analyze_luminance(empty)

    def test_frame_grayscale_input(self, analyzer: OpenCVAnalyzer):
        """Deve aceitar frame grayscale diretamente."""
        gray = np.ones((720, 1280), dtype=np.uint8) * 100
        result = analyzer.analyze_luminance(gray)
        assert 99.0 <= result.mean_luminance <= 101.0


class TestDetectBlackScreen:
    """Testes para detect_black_screen."""

    def test_frame_preto_detecta_tela_preta(self, analyzer: OpenCVAnalyzer, black_frame: np.ndarray):
        """Frame completamente preto deve ser classificado como tela preta."""
        result = analyzer.detect_black_screen(black_frame)
        assert result.is_black_screen is True
        assert result.is_dark_scene is False

    def test_frame_branco_nao_e_tela_preta(self, analyzer: OpenCVAnalyzer, white_frame: np.ndarray):
        """Frame branco não deve ser tela preta."""
        result = analyzer.detect_black_screen(white_frame)
        assert result.is_black_screen is False

    def test_cena_escura_nao_e_tela_preta(self, analyzer: OpenCVAnalyzer, dark_scene_frame: np.ndarray):
        """Cena escura com variância alta não deve ser classificada como tela preta."""
        result = analyzer.detect_black_screen(dark_scene_frame)
        # A cena escura tem variância > 50, então deve ser is_dark_scene
        assert result.is_dark_scene is True

    def test_frame_none_retorna_resultado_sem_excecao(self, analyzer: OpenCVAnalyzer):
        """Frame None deve retornar resultado sem lançar exceção."""
        result = analyzer.detect_black_screen(None)
        assert result.is_black_screen is False
        assert result.is_dark_scene is False

    def test_frame_vazio_retorna_resultado_sem_excecao(self, analyzer: OpenCVAnalyzer):
        """Frame vazio deve retornar resultado sem lançar exceção."""
        empty = np.array([], dtype=np.uint8)
        result = analyzer.detect_black_screen(empty)
        assert result.is_black_screen is False

    def test_luminance_result_incluso(self, analyzer: OpenCVAnalyzer, black_frame: np.ndarray):
        """Resultado deve incluir LuminanceResult."""
        result = analyzer.detect_black_screen(black_frame)
        assert result.luminance is not None
        assert result.luminance.mean_luminance == 0.0


class TestCalculateFrameSimilarity:
    """Testes para calculate_frame_similarity."""

    def test_frames_identicos_similaridade_1(self, analyzer: OpenCVAnalyzer, gray_frame: np.ndarray):
        """Frames idênticos devem ter similaridade ~1.0."""
        similarity = analyzer.calculate_frame_similarity(gray_frame, gray_frame.copy())
        assert similarity >= 0.99

    def test_frames_diferentes_similaridade_baixa(self, analyzer: OpenCVAnalyzer, black_frame: np.ndarray, white_frame: np.ndarray):
        """Frames completamente diferentes devem ter similaridade baixa."""
        similarity = analyzer.calculate_frame_similarity(black_frame, white_frame)
        assert similarity < 0.5

    def test_resultado_no_range_0_1(self, analyzer: OpenCVAnalyzer):
        """Similaridade deve estar no range [0.0, 1.0]."""
        frame_a = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)
        frame_b = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)
        similarity = analyzer.calculate_frame_similarity(frame_a, frame_b)
        assert 0.0 <= similarity <= 1.0

    def test_frames_none_raises_error(self, analyzer: OpenCVAnalyzer, gray_frame: np.ndarray):
        """Frames None devem lançar ValueError."""
        with pytest.raises(ValueError):
            analyzer.calculate_frame_similarity(None, gray_frame)
        with pytest.raises(ValueError):
            analyzer.calculate_frame_similarity(gray_frame, None)

    def test_dimensoes_diferentes_raises_error(self, analyzer: OpenCVAnalyzer):
        """Frames com dimensões diferentes devem lançar ValueError."""
        frame_a = np.zeros((720, 1280, 3), dtype=np.uint8)
        frame_b = np.zeros((480, 640, 3), dtype=np.uint8)
        with pytest.raises(ValueError):
            analyzer.calculate_frame_similarity(frame_a, frame_b)


class TestDetectFreeze:
    """Testes para detect_freeze."""

    def test_freeze_confirmado(self, analyzer: OpenCVAnalyzer, gray_frame: np.ndarray):
        """Frames idênticos + currentTime parado + janela >= 5s = FREEZE_CONFIRMED."""
        result = analyzer.detect_freeze(
            frame_a=gray_frame,
            frame_b=gray_frame.copy(),
            current_time_diff=0.0,
            observation_window_seconds=5.0,
        )
        assert result.classification == FreezeClassification.FREEZE_CONFIRMED
        assert result.similarity >= 0.98

    def test_conteudo_estatico(self, analyzer: OpenCVAnalyzer, gray_frame: np.ndarray):
        """Frames idênticos mas currentTime avançando = STATIC_CONTENT."""
        result = analyzer.detect_freeze(
            frame_a=gray_frame,
            frame_b=gray_frame.copy(),
            current_time_diff=2.0,
            observation_window_seconds=5.0,
        )
        assert result.classification == FreezeClassification.STATIC_CONTENT

    def test_sem_freeze(self, analyzer: OpenCVAnalyzer):
        """Frames diferentes = NO_FREEZE."""
        frame_a = np.zeros((720, 1280, 3), dtype=np.uint8)
        frame_b = np.ones((720, 1280, 3), dtype=np.uint8) * 255
        result = analyzer.detect_freeze(
            frame_a=frame_a,
            frame_b=frame_b,
            current_time_diff=2.0,
            observation_window_seconds=5.0,
        )
        assert result.classification == FreezeClassification.NO_FREEZE

    def test_frame_none_retorna_analysis_error(self, analyzer: OpenCVAnalyzer, gray_frame: np.ndarray):
        """Frame None deve retornar ANALYSIS_ERROR sem exceção."""
        result = analyzer.detect_freeze(
            frame_a=None,
            frame_b=gray_frame,
            current_time_diff=0.0,
        )
        assert result.classification == FreezeClassification.ANALYSIS_ERROR

    def test_dimensoes_diferentes_retorna_analysis_error(self, analyzer: OpenCVAnalyzer):
        """Frames com dimensões diferentes devem retornar ANALYSIS_ERROR."""
        frame_a = np.zeros((720, 1280, 3), dtype=np.uint8)
        frame_b = np.zeros((480, 640, 3), dtype=np.uint8)
        result = analyzer.detect_freeze(
            frame_a=frame_a,
            frame_b=frame_b,
            current_time_diff=0.0,
        )
        assert result.classification == FreezeClassification.ANALYSIS_ERROR

    def test_janela_observacao_insuficiente_nao_confirma_freeze(self, analyzer: OpenCVAnalyzer, gray_frame: np.ndarray):
        """Janela de observação < 5s não deve confirmar freeze mesmo com frames idênticos."""
        result = analyzer.detect_freeze(
            frame_a=gray_frame,
            frame_b=gray_frame.copy(),
            current_time_diff=0.0,
            observation_window_seconds=3.0,
        )
        # Com janela < 5.0 mas currentTime < 0.5 e similarity alta → STATIC_CONTENT
        assert result.classification == FreezeClassification.STATIC_CONTENT

    def test_resultado_inclui_metricas(self, analyzer: OpenCVAnalyzer, gray_frame: np.ndarray):
        """Resultado deve incluir todas as métricas."""
        result = analyzer.detect_freeze(
            frame_a=gray_frame,
            frame_b=gray_frame.copy(),
            current_time_diff=0.1,
            observation_window_seconds=6.0,
        )
        assert result.similarity >= 0.0
        assert result.current_time_diff == 0.1
        assert result.observation_window_seconds == 6.0

    def test_frame_tipo_invalido_retorna_analysis_error(self, analyzer: OpenCVAnalyzer):
        """Frame com tipo inválido deve retornar ANALYSIS_ERROR."""
        result = analyzer.detect_freeze(
            frame_a="not_a_frame",
            frame_b="also_not_a_frame",
            current_time_diff=0.0,
        )
        assert result.classification == FreezeClassification.ANALYSIS_ERROR


class TestThresholdsConfiguraveis:
    """Testes para thresholds configuráveis."""

    def test_threshold_luminancia_personalizado(self):
        """Threshold de luminância personalizado deve ser respeitado."""
        # Threshold mais alto + black_pixel_threshold mais alto: permite detectar como preto
        analyzer = OpenCVAnalyzer(
            black_screen_threshold=50.0,
            black_pixel_threshold=40,  # Pixels < 40 são considerados pretos
        )
        # Frame com luminância 30, que é < threshold 50, e todos pixels < 40
        frame = np.ones((100, 100, 3), dtype=np.uint8) * 30
        result = analyzer.detect_black_screen(frame)
        assert result.is_black_screen is True

    def test_threshold_freeze_personalizado(self):
        """Threshold de freeze personalizado deve ser respeitado."""
        # Threshold mais baixo: mais fácil de confirmar freeze
        analyzer = OpenCVAnalyzer(freeze_similarity_threshold=0.5)
        frame_a = np.ones((100, 100, 3), dtype=np.uint8) * 100
        # Frame levemente diferente
        frame_b = frame_a.copy()
        frame_b[0:50, 0:50] = 110
        result = analyzer.detect_freeze(
            frame_a=frame_a,
            frame_b=frame_b,
            current_time_diff=0.0,
            observation_window_seconds=5.0,
        )
        # Com threshold 0.5, frames levemente diferentes devem confirmar freeze
        assert result.classification == FreezeClassification.FREEZE_CONFIRMED
