"""Detector de buffering persistente do player.

Monitora o estado do player ao longo de múltiplas amostras de telemetria
e classifica o buffering como NORMAL ou PERSISTENT com base em um
threshold configurável.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from src.models import (
    BufferingClassification,
    BufferingState,
    TelemetrySample,
)
from src.structured_logger import StructuredLogger

STAGE_ID = "buffering_detector"


class BufferingDetector:
    """Detecta buffering persistente do player.

    Mantém estado interno entre chamadas de update() para
    acompanhar a duração do buffering e classificar como
    NORMAL ou PERSISTENT.
    """

    def __init__(self, threshold_seconds: float = 10.0) -> None:
        """Inicializa o detector com threshold configurável.

        Args:
            threshold_seconds: Tempo em segundos após o qual
                buffering é classificado como persistente.
                Default: 10.0 segundos.
        """
        self._threshold_seconds = threshold_seconds
        self._logger = StructuredLogger()

        # Estado interno
        self._buffering_active: bool = False
        self._start_time: Optional[str] = None
        self._start_datetime: Optional[datetime] = None
        self._duration_seconds: float = 0.0
        self._last_current_time: Optional[float] = None
        self._classification: BufferingClassification = (
            BufferingClassification.NO_BUFFERING
        )

    def _is_buffering(self, sample: TelemetrySample) -> bool:
        """Determina se o player está em estado de buffering.

        Condições de buffering:
        - player.buffering == True, OU
        - readyState < 3 E não está pausado

        Args:
            sample: Amostra de telemetria atual.

        Returns:
            True se o player está em buffering.
        """
        if sample.player.buffering:
            return True
        if sample.video.ready_state < 3 and not sample.video.paused:
            return True
        return False

    def _is_playing(self, sample: TelemetrySample) -> bool:
        """Determina se o player está reproduzindo normalmente.

        Args:
            sample: Amostra de telemetria atual.

        Returns:
            True se o player está reproduzindo.
        """
        return sample.player.playing and not sample.player.buffering

    def _is_unexpected_state(self, sample: TelemetrySample) -> bool:
        """Verifica se o player está em um estado inesperado.

        Estados esperados durante monitoramento de buffering:
        - waiting/stalled: readyState < 3
        - playing: readyState >= 3 e playing=True

        Um estado inesperado é quando readyState >= 3 mas o
        player não está playing nem buffering (ex: paused
        inesperadamente).

        Args:
            sample: Amostra de telemetria atual.

        Returns:
            True se o estado é inesperado.
        """
        # Se está claramente em buffering ou playing, não é inesperado
        if self._is_buffering(sample) or self._is_playing(sample):
            return False
        # Se está pausado, é um estado válido (não monitoramos)
        if sample.video.paused:
            return False
        # Qualquer outro estado é inesperado
        return True

    def _get_current_timestamp(self) -> str:
        """Gera timestamp ISO 8601 atual."""
        return datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S."
        ) + f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"

    def _calculate_duration(self) -> float:
        """Calcula duração do buffering atual em segundos."""
        if self._start_datetime is None:
            return 0.0
        now = datetime.now(timezone.utc)
        delta = (now - self._start_datetime).total_seconds()
        return max(delta, self._duration_seconds)

    def update(self, sample: TelemetrySample) -> BufferingState:
        """Atualiza estado de buffering com nova amostra de telemetria.

        Lógica principal:
        - Se buffering inicia: registra start_time e current_time
        - Se buffering continua: acumula duração, verifica currentTime
        - Se player volta a reproduzir dentro do threshold: BUFFERING_NORMAL
        - Se duração excede threshold sem currentTime avançando:
          BUFFERING_PERSISTENT
        - Se estado inesperado: log WARNING, continua monitoramento

        Args:
            sample: Amostra de telemetria do player.

        Returns:
            BufferingState com classificação, duração e start_time.
        """
        # Verificar estado inesperado
        if self._is_unexpected_state(sample):
            self._logger.warning(
                STAGE_ID,
                "Estado inesperado do player durante monitoramento",
                ready_state=sample.video.ready_state,
                playing=sample.player.playing,
                buffering=sample.player.buffering,
                paused=sample.video.paused,
            )
            # Não interrompe detecção, retorna estado atual
            return BufferingState(
                classification=self._classification,
                duration_seconds=self._duration_seconds,
                start_time=self._start_time,
            )

        # Player voltou a reproduzir
        if self._buffering_active and self._is_playing(sample):
            current_time = sample.video.current_time
            current_time_advancing = (
                self._last_current_time is not None
                and current_time > self._last_current_time
            )

            if current_time_advancing:
                # Buffering resolvido dentro do threshold
                if self._duration_seconds <= self._threshold_seconds:
                    self._classification = (
                        BufferingClassification.BUFFERING_NORMAL
                    )
                    self._logger.info(
                        STAGE_ID,
                        "Buffering normal resolvido",
                        duration_seconds=self._duration_seconds,
                    )
                else:
                    # Mesmo resolvendo, já foi persistente
                    self._classification = (
                        BufferingClassification.BUFFERING_PERSISTENT
                    )

                result = BufferingState(
                    classification=self._classification,
                    duration_seconds=self._duration_seconds,
                    start_time=self._start_time,
                )
                self.reset()
                return result

        # Player está em buffering
        if self._is_buffering(sample):
            if not self._buffering_active:
                # Início de novo buffering
                self._buffering_active = True
                self._start_time = self._get_current_timestamp()
                self._start_datetime = datetime.now(timezone.utc)
                self._last_current_time = sample.video.current_time
                self._duration_seconds = 0.0
                self._classification = (
                    BufferingClassification.BUFFERING_NORMAL
                )
                self._logger.info(
                    STAGE_ID,
                    "Buffering detectado",
                    current_time=sample.video.current_time,
                    ready_state=sample.video.ready_state,
                )
            else:
                # Buffering continua - atualizar duração
                self._duration_seconds = self._calculate_duration()
                current_time = sample.video.current_time
                current_time_advancing = (
                    self._last_current_time is not None
                    and current_time > self._last_current_time
                )

                # Se currentTime não avança e excedeu threshold
                if (
                    not current_time_advancing
                    and self._duration_seconds > self._threshold_seconds
                ):
                    self._classification = (
                        BufferingClassification.BUFFERING_PERSISTENT
                    )
                    self._logger.warning(
                        STAGE_ID,
                        "Buffering persistente detectado",
                        duration_seconds=self._duration_seconds,
                        threshold_seconds=self._threshold_seconds,
                    )

                # Atualizar último currentTime observado
                self._last_current_time = current_time

            return BufferingState(
                classification=self._classification,
                duration_seconds=self._duration_seconds,
                start_time=self._start_time,
            )

        # Player não está em buffering e não estávamos monitorando
        if not self._buffering_active:
            return BufferingState(
                classification=BufferingClassification.NO_BUFFERING,
                duration_seconds=0.0,
                start_time=None,
            )

        # Caso fallback - retorna estado atual
        return BufferingState(
            classification=self._classification,
            duration_seconds=self._duration_seconds,
            start_time=self._start_time,
        )

    def is_persistent(self) -> bool:
        """Verifica se o buffering atual excedeu o threshold.

        Returns:
            True se buffering ativo e duração > threshold.
        """
        if not self._buffering_active:
            return False
        current_duration = self._calculate_duration()
        return current_duration > self._threshold_seconds

    def reset(self) -> None:
        """Reseta estado interno quando player volta a reproduzir.

        Limpa todos os dados de buffering acumulados.
        """
        self._buffering_active = False
        self._start_time = None
        self._start_datetime = None
        self._duration_seconds = 0.0
        self._last_current_time = None
        self._classification = BufferingClassification.NO_BUFFERING
        self._logger.debug(
            STAGE_ID,
            "Estado de buffering resetado",
        )
