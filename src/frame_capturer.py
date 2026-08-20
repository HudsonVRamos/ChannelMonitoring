"""Capturador de frames do player durante reprodução DRM.

Captura screenshots do viewport do player via Playwright,
valida resolução, tamanho e conteúdo visual (luminância),
e descarta frames de tela preta registrando warning.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import cv2
import numpy as np
from playwright.async_api import Page

from src.structured_logger import StructuredLogger


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class FrameValidation:
    """Resultado da validação de conteúdo visual de um frame."""

    mean_luminance: float
    is_valid: bool
    width: int
    height: int


@dataclass
class FrameResult:
    """Resultado de uma captura de frame."""

    data: bytes
    width: int
    height: int
    size_bytes: int
    mean_luminance: float
    is_valid: bool
    timestamp: str  # ISO 8601
    rejected_reason: Optional[str] = None


# =============================================================================
# Frame Capturer
# =============================================================================


class FrameCapturer:
    """Captura frames do player durante reprodução.

    Utiliza Playwright para capturar screenshots PNG do viewport,
    valida resolução mínima, tamanho máximo e conteúdo visual
    via cálculo de luminância com OpenCV.
    """

    def __init__(
        self,
        min_interval_seconds: float = 5.0,
        min_resolution: tuple[int, int] = (1280, 720),
        max_size_bytes: int = 5 * 1024 * 1024,
    ) -> None:
        """Inicializa o capturador de frames.

        Args:
            min_interval_seconds: Intervalo mínimo entre capturas (1-60s).
            min_resolution: Resolução mínima aceita (largura, altura).
            max_size_bytes: Tamanho máximo do frame em bytes.

        Raises:
            ValueError: Se min_interval_seconds estiver fora do range 1-60.
        """
        if not (1.0 <= min_interval_seconds <= 60.0):
            raise ValueError(
                f"min_interval_seconds deve estar entre 1 e 60, "
                f"valor recebido: {min_interval_seconds}"
            )

        self._min_interval_seconds = min_interval_seconds
        self._min_resolution = min_resolution
        self._max_size_bytes = max_size_bytes
        self._logger = StructuredLogger()

    @property
    def min_interval_seconds(self) -> float:
        """Retorna o intervalo mínimo entre capturas."""
        return self._min_interval_seconds

    @property
    def min_resolution(self) -> tuple[int, int]:
        """Retorna a resolução mínima aceita."""
        return self._min_resolution

    @property
    def max_size_bytes(self) -> int:
        """Retorna o tamanho máximo do frame em bytes."""
        return self._max_size_bytes

    async def capture_frame(self, page: Page) -> FrameResult:
        """Captura um frame do viewport do player.

        Realiza screenshot PNG via Playwright e valida:
        - Resolução >= min_resolution
        - Tamanho <= max_size_bytes
        - Conteúdo visual (luminância > 16)

        Args:
            page: Página Playwright com o player ativo.

        Returns:
            FrameResult com dados do frame e status de validação.
        """
        timestamp = self._get_timestamp()

        # Captura screenshot PNG do viewport
        frame_data: bytes = await page.screenshot(type="png")
        size_bytes = len(frame_data)

        # Decodifica para obter dimensões
        np_array = np.frombuffer(frame_data, dtype=np.uint8)
        image = cv2.imdecode(np_array, cv2.IMREAD_COLOR)

        if image is None:
            self._logger.warning(
                "frame_capturer",
                "Frame capturado não pôde ser decodificado",
                size_bytes=size_bytes,
            )
            return FrameResult(
                data=frame_data,
                width=0,
                height=0,
                size_bytes=size_bytes,
                mean_luminance=0.0,
                is_valid=False,
                timestamp=timestamp,
                rejected_reason="Frame não pôde ser decodificado",
            )

        height, width = image.shape[:2]

        # Validar resolução mínima
        min_w, min_h = self._min_resolution
        if width < min_w or height < min_h:
            reason = (
                f"Resolução insuficiente: {width}x{height} "
                f"(mínimo: {min_w}x{min_h})"
            )
            self._logger.warning(
                "frame_capturer",
                reason,
                width=width,
                height=height,
                min_width=min_w,
                min_height=min_h,
            )
            return FrameResult(
                data=frame_data,
                width=width,
                height=height,
                size_bytes=size_bytes,
                mean_luminance=0.0,
                is_valid=False,
                timestamp=timestamp,
                rejected_reason=reason,
            )

        # Validar tamanho máximo
        if size_bytes > self._max_size_bytes:
            reason = (
                f"Tamanho excede limite: {size_bytes} bytes "
                f"(máximo: {self._max_size_bytes} bytes)"
            )
            self._logger.warning(
                "frame_capturer",
                reason,
                size_bytes=size_bytes,
                max_size_bytes=self._max_size_bytes,
            )
            return FrameResult(
                data=frame_data,
                width=width,
                height=height,
                size_bytes=size_bytes,
                mean_luminance=0.0,
                is_valid=False,
                timestamp=timestamp,
                rejected_reason=reason,
            )

        # Validar conteúdo visual (luminância)
        validation = self.validate_frame_content(frame_data)
        is_valid = validation.is_valid

        if not is_valid:
            self._logger.warning(
                "frame_capturer",
                "Frame descartado: tela preta detectada "
                "(possível proteção DRM ativa)",
                mean_luminance=validation.mean_luminance,
                width=width,
                height=height,
                timestamp=timestamp,
            )
            return FrameResult(
                data=frame_data,
                width=width,
                height=height,
                size_bytes=size_bytes,
                mean_luminance=validation.mean_luminance,
                is_valid=False,
                timestamp=timestamp,
                rejected_reason="Tela preta (luminância <= 16)",
            )

        # Frame válido — registrar log INFO
        self._logger.info(
            "frame_capturer",
            "Frame capturado com sucesso",
            timestamp=timestamp,
            size_bytes=size_bytes,
            width=width,
            height=height,
            mean_luminance=round(validation.mean_luminance, 2),
        )

        return FrameResult(
            data=frame_data,
            width=width,
            height=height,
            size_bytes=size_bytes,
            mean_luminance=validation.mean_luminance,
            is_valid=True,
            timestamp=timestamp,
        )

    def validate_frame_content(self, frame_data: bytes) -> FrameValidation:
        """Verifica se o frame contém conteúdo visual (não tela preta DRM).

        Decodifica os bytes PNG, converte para escala de cinza e calcula
        a média de luminância. Frame é válido se luminância > 16.

        Args:
            frame_data: Bytes do frame em formato PNG.

        Returns:
            FrameValidation com luminância média e status de validação.
        """
        # Decodifica PNG para numpy array
        np_array = np.frombuffer(frame_data, dtype=np.uint8)
        image = cv2.imdecode(np_array, cv2.IMREAD_COLOR)

        if image is None:
            return FrameValidation(
                mean_luminance=0.0,
                is_valid=False,
                width=0,
                height=0,
            )

        height, width = image.shape[:2]

        # Converter para escala de cinza
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        # Calcular média de luminância
        mean_luminance = float(np.mean(gray))

        # Frame é válido se luminância > 16
        is_valid = mean_luminance > 16.0

        return FrameValidation(
            mean_luminance=mean_luminance,
            is_valid=is_valid,
            width=width,
            height=height,
        )

    async def capture_sequence(
        self, page: Page, count: int, interval_seconds: float
    ) -> list[FrameResult]:
        """Captura sequência de frames com intervalo configurável.

        Args:
            page: Página Playwright com o player ativo.
            count: Quantidade de frames a capturar.
            interval_seconds: Intervalo entre capturas em segundos.

        Returns:
            Lista de FrameResult com todos os frames capturados.

        Raises:
            ValueError: Se interval_seconds estiver fora do range 1-60.
        """
        if not (1.0 <= interval_seconds <= 60.0):
            raise ValueError(
                f"interval_seconds deve estar entre 1 e 60, "
                f"valor recebido: {interval_seconds}"
            )

        results: list[FrameResult] = []

        for i in range(count):
            frame = await self.capture_frame(page)
            results.append(frame)

            # Aguardar intervalo entre capturas (exceto após o último)
            if i < count - 1:
                await asyncio.sleep(interval_seconds)

        self._logger.info(
            "frame_capturer",
            f"Sequência de captura concluída: {len(results)} frames",
            total_frames=len(results),
            valid_frames=sum(1 for f in results if f.is_valid),
            rejected_frames=sum(1 for f in results if not f.is_valid),
            interval_seconds=interval_seconds,
        )

        return results

    def _get_timestamp(self) -> str:
        """Gera timestamp ISO 8601 com milissegundos em UTC."""
        now = datetime.now(timezone.utc)
        return (
            now.strftime("%Y-%m-%dT%H:%M:%S.")
            + f"{now.microsecond // 1000:03d}Z"
        )
