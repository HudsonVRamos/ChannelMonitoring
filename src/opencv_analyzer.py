"""Analisador visual de frames com OpenCV.

Detecta tela preta e freeze combinando análise de luminância,
similaridade visual (SSIM) e telemetria do player.
"""
from __future__ import annotations

import cv2
import numpy as np

from src.models import (
    BlackScreenResult,
    FreezeClassification,
    FreezeResult,
    LuminanceResult,
)
from src.structured_logger import StructuredLogger

_STAGE_ID = "opencv_analyzer"


class OpenCVAnalyzer:
    """Análise visual de frames com OpenCV."""

    def __init__(
        self,
        black_screen_threshold: float = 10.0,
        black_pixel_threshold: int = 20,
        black_pixel_percent: float = 95.0,
        variance_threshold: float = 50.0,
        freeze_similarity_threshold: float = 0.98,
    ) -> None:
        """Inicializa o analisador com thresholds configuráveis.

        Args:
            black_screen_threshold: Limiar de luminância média para tela preta (0-255).
            black_pixel_threshold: Valor máximo de pixel para ser considerado "preto".
            black_pixel_percent: Percentual mínimo de pixels pretos para tela preta.
            variance_threshold: Variância máxima para distinguir tela preta de cena escura.
            freeze_similarity_threshold: Limiar de similaridade SSIM para freeze.
        """
        self._black_screen_threshold = black_screen_threshold
        self._black_pixel_threshold = black_pixel_threshold
        self._black_pixel_percent = black_pixel_percent
        self._variance_threshold = variance_threshold
        self._freeze_similarity_threshold = freeze_similarity_threshold
        self._logger = StructuredLogger()

    def analyze_luminance(self, frame: np.ndarray) -> LuminanceResult:
        """Calcula média de luminância, percentual de pixels pretos e variância.

        Converte o frame para escala de cinza e calcula as métricas de luminância.

        Args:
            frame: Frame em formato numpy array (BGR ou grayscale).

        Returns:
            LuminanceResult com mean_luminance, black_pixel_percent e pixel_variance.

        Raises:
            ValueError: Se o frame for None ou tiver dimensões inválidas.
        """
        if frame is None or frame.size == 0:
            raise ValueError("Frame inválido: None ou vazio")

        # Converter para escala de cinza se necessário
        if len(frame.shape) == 3:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        else:
            gray = frame

        # Calcular média de luminância
        mean_luminance = float(np.mean(gray))

        # Calcular percentual de pixels pretos (valor < threshold)
        total_pixels = gray.size
        black_pixels = int(np.sum(gray < self._black_pixel_threshold))
        black_pixel_pct = (black_pixels / total_pixels) * 100.0

        # Calcular variância dos pixels
        pixel_variance = float(np.var(gray))

        self._logger.info(
            _STAGE_ID,
            "Análise de luminância concluída",
            mean_luminance=round(mean_luminance, 2),
            black_pixel_percent=round(black_pixel_pct, 2),
            pixel_variance=round(pixel_variance, 2),
        )

        return LuminanceResult(
            mean_luminance=mean_luminance,
            black_pixel_percent=black_pixel_pct,
            pixel_variance=pixel_variance,
        )

    def detect_black_screen(self, frame: np.ndarray) -> BlackScreenResult:
        """Detecta tela preta vs cena escura legítima.

        Lógica:
        - BLACK_SCREEN se: luminância < threshold(10) E pixels pretos > 95% E variância <= 50
        - Cena escura legítima se: variância > 50 (distribuição não uniforme = conteúdo visual)

        Args:
            frame: Frame em formato numpy array (BGR ou grayscale).

        Returns:
            BlackScreenResult com is_black_screen, is_dark_scene e luminance.
        """
        # Tratar frame inválido
        if frame is None or not isinstance(frame, np.ndarray) or frame.size == 0:
            # Retornar resultado de erro sem classificar
            empty_luminance = LuminanceResult(
                mean_luminance=0.0,
                black_pixel_percent=0.0,
                pixel_variance=0.0,
            )
            self._logger.error(
                _STAGE_ID,
                "Frame inválido para detecção de tela preta",
            )
            return BlackScreenResult(
                is_black_screen=False,
                is_dark_scene=False,
                luminance=empty_luminance,
            )

        luminance = self.analyze_luminance(frame)

        # Lógica de classificação
        is_black_screen = (
            luminance.mean_luminance < self._black_screen_threshold
            and luminance.black_pixel_percent > self._black_pixel_percent
            and luminance.pixel_variance <= self._variance_threshold
        )

        # Cena escura legítima: variância alta indica conteúdo visual
        is_dark_scene = luminance.pixel_variance > self._variance_threshold

        self._logger.info(
            _STAGE_ID,
            "Detecção de tela preta concluída",
            is_black_screen=is_black_screen,
            is_dark_scene=is_dark_scene,
        )

        return BlackScreenResult(
            is_black_screen=is_black_screen,
            is_dark_scene=is_dark_scene,
            luminance=luminance,
        )

    def calculate_frame_similarity(
        self, frame_a: np.ndarray, frame_b: np.ndarray
    ) -> float:
        """Calcula similaridade entre dois frames usando SSIM.

        Implementação de SSIM (Structural Similarity Index) usando OpenCV e numpy,
        sem dependência de scikit-image.

        Args:
            frame_a: Primeiro frame (BGR ou grayscale).
            frame_b: Segundo frame (BGR ou grayscale).

        Returns:
            Valor de similaridade no range [0.0, 1.0].

        Raises:
            ValueError: Se os frames forem None, vazios ou com dimensões diferentes.
        """
        if frame_a is None or frame_b is None:
            raise ValueError("Frames não podem ser None")

        if frame_a.size == 0 or frame_b.size == 0:
            raise ValueError("Frames não podem ser vazios")

        # Converter para grayscale se necessário
        if len(frame_a.shape) == 3:
            gray_a = cv2.cvtColor(frame_a, cv2.COLOR_BGR2GRAY)
        else:
            gray_a = frame_a

        if len(frame_b.shape) == 3:
            gray_b = cv2.cvtColor(frame_b, cv2.COLOR_BGR2GRAY)
        else:
            gray_b = frame_b

        if gray_a.shape != gray_b.shape:
            raise ValueError(
                f"Frames com dimensões diferentes: {gray_a.shape} vs {gray_b.shape}"
            )

        ssim_value = self._calculate_ssim(gray_a, gray_b)

        self._logger.info(
            _STAGE_ID,
            "Similaridade entre frames calculada",
            ssim=round(ssim_value, 4),
        )

        return ssim_value

    def _calculate_ssim(self, img1: np.ndarray, img2: np.ndarray) -> float:
        """Calcula SSIM (Structural Similarity Index) entre duas imagens grayscale.

        Implementação baseada na fórmula SSIM original de Wang et al. (2004),
        usando GaussianBlur como filtro de suavização.

        Args:
            img1: Primeira imagem em escala de cinza.
            img2: Segunda imagem em escala de cinza.

        Returns:
            Valor SSIM no range [0.0, 1.0].
        """
        # Constantes para estabilidade numérica (baseadas no paper original)
        C1 = (0.01 * 255) ** 2  # 6.5025
        C2 = (0.03 * 255) ** 2  # 58.5225

        # Converter para float64 para precisão
        img1 = img1.astype(np.float64)
        img2 = img2.astype(np.float64)

        # Calcular médias usando GaussianBlur
        kernel_size = (11, 11)
        sigma = 1.5

        mu1 = cv2.GaussianBlur(img1, kernel_size, sigma)
        mu2 = cv2.GaussianBlur(img2, kernel_size, sigma)

        mu1_sq = mu1 * mu1
        mu2_sq = mu2 * mu2
        mu1_mu2 = mu1 * mu2

        # Calcular variâncias e covariância
        sigma1_sq = cv2.GaussianBlur(img1 * img1, kernel_size, sigma) - mu1_sq
        sigma2_sq = cv2.GaussianBlur(img2 * img2, kernel_size, sigma) - mu2_sq
        sigma12 = cv2.GaussianBlur(img1 * img2, kernel_size, sigma) - mu1_mu2

        # Fórmula SSIM
        numerator = (2 * mu1_mu2 + C1) * (2 * sigma12 + C2)
        denominator = (mu1_sq + mu2_sq + C1) * (sigma1_sq + sigma2_sq + C2)

        ssim_map = numerator / denominator

        # Retornar média do mapa SSIM, clamped entre 0 e 1
        mean_ssim = float(np.mean(ssim_map))
        return max(0.0, min(1.0, mean_ssim))

    def detect_freeze(
        self,
        frame_a: np.ndarray,
        frame_b: np.ndarray,
        current_time_diff: float,
        observation_window_seconds: float = 5.0,
    ) -> FreezeResult:
        """Detecta freeze combinando similaridade visual + telemetria.

        Lógica de classificação:
        - FREEZE_CONFIRMED: similaridade > 0.98 E currentTime diff < 0.5 E janela >= 5.0s
        - STATIC_CONTENT: similaridade > 0.98 MAS currentTime diff >= 0.5
        - NO_FREEZE: similaridade <= 0.98
        - ANALYSIS_ERROR: frames inválidos ou dimensões diferentes

        Args:
            frame_a: Primeiro frame (referência).
            frame_b: Segundo frame (atual).
            current_time_diff: Diferença de currentTime do player entre os frames.
            observation_window_seconds: Janela de observação em segundos.

        Returns:
            FreezeResult com classificação, similaridade e métricas.
        """
        # Tratar frames inválidos
        if frame_a is None or frame_b is None:
            self._logger.error(
                _STAGE_ID,
                "Frame inválido para detecção de freeze: None",
            )
            return FreezeResult(
                classification=FreezeClassification.ANALYSIS_ERROR,
                similarity=0.0,
                current_time_diff=current_time_diff,
                observation_window_seconds=observation_window_seconds,
            )

        if not isinstance(frame_a, np.ndarray) or not isinstance(frame_b, np.ndarray):
            self._logger.error(
                _STAGE_ID,
                "Frame inválido para detecção de freeze: tipo incorreto",
            )
            return FreezeResult(
                classification=FreezeClassification.ANALYSIS_ERROR,
                similarity=0.0,
                current_time_diff=current_time_diff,
                observation_window_seconds=observation_window_seconds,
            )

        if frame_a.size == 0 or frame_b.size == 0:
            self._logger.error(
                _STAGE_ID,
                "Frame inválido para detecção de freeze: vazio",
            )
            return FreezeResult(
                classification=FreezeClassification.ANALYSIS_ERROR,
                similarity=0.0,
                current_time_diff=current_time_diff,
                observation_window_seconds=observation_window_seconds,
            )

        # Verificar dimensões diferentes
        # Extrair dimensões de grayscale para comparação justa
        shape_a = frame_a.shape[:2]
        shape_b = frame_b.shape[:2]

        if shape_a != shape_b:
            self._logger.error(
                _STAGE_ID,
                "Frames com dimensões diferentes para detecção de freeze",
                shape_a=str(shape_a),
                shape_b=str(shape_b),
            )
            return FreezeResult(
                classification=FreezeClassification.ANALYSIS_ERROR,
                similarity=0.0,
                current_time_diff=current_time_diff,
                observation_window_seconds=observation_window_seconds,
            )

        # Calcular similaridade
        try:
            similarity = self.calculate_frame_similarity(frame_a, frame_b)
        except (ValueError, cv2.error) as e:
            self._logger.error(
                _STAGE_ID,
                "Erro ao calcular similaridade",
                error=str(e),
            )
            return FreezeResult(
                classification=FreezeClassification.ANALYSIS_ERROR,
                similarity=0.0,
                current_time_diff=current_time_diff,
                observation_window_seconds=observation_window_seconds,
            )

        # Lógica de classificação
        if similarity > self._freeze_similarity_threshold:
            if current_time_diff < 0.5 and observation_window_seconds >= 5.0:
                classification = FreezeClassification.FREEZE_CONFIRMED
            else:
                classification = FreezeClassification.STATIC_CONTENT
        else:
            classification = FreezeClassification.NO_FREEZE

        self._logger.info(
            _STAGE_ID,
            "Detecção de freeze concluída",
            classification=classification.value,
            similarity=round(similarity, 4),
            current_time_diff=round(current_time_diff, 3),
            observation_window=observation_window_seconds,
        )

        return FreezeResult(
            classification=classification,
            similarity=similarity,
            current_time_diff=current_time_diff,
            observation_window_seconds=observation_window_seconds,
        )
