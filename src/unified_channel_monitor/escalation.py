"""Gerenciador de escalação para o Unified Channel Monitor.

Implementa pipeline de escalação com suporte a deferimento:
- Escalações são deferidas quando testes de track estão ativos (sem DOM interactions)
- Escalações imediatas são executadas quando não há testes de track em andamento
- Pipeline: Frame Capture → OpenCV Analysis → Bedrock Diagnosis
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from src.unified_channel_monitor.models import DeferredEscalation, EscalationResult

if TYPE_CHECKING:
    from playwright.async_api import Page

    from src.bedrock_client import BedrockClient
    from src.frame_capturer import FrameCapturer
    from src.opencv_analyzer import OpenCVAnalyzer

logger = logging.getLogger(__name__)


class EscalationManager:
    """Gerencia escalação HEALTHY → SUSPECT → OpenCV → Bedrock.

    Responsável por coordenar o pipeline de escalação com suporte a
    deferimento durante testes de track (áudio/legendas). Quando testes
    de track estão ativos, escalações são enfileiradas e processadas
    após a conclusão dos testes, garantindo que nenhuma interação com
    DOM ocorra durante o período de teste.
    """

    def __init__(
        self,
        page: Page,
        frame_capturer: FrameCapturer | None,
        opencv_analyzer: OpenCVAnalyzer | None,
        bedrock_client: BedrockClient | None,
    ) -> None:
        """Inicializa o gerenciador de escalação.

        Args:
            page: Instância Playwright Page compartilhada.
            frame_capturer: Capturador de frames (opcional).
            opencv_analyzer: Analisador OpenCV (opcional).
            bedrock_client: Cliente Bedrock para diagnóstico IA (opcional).
        """
        self._page = page
        self._frame_capturer = frame_capturer
        self._opencv_analyzer = opencv_analyzer
        self._bedrock_client = bedrock_client
        self._deferred_queue: list[DeferredEscalation] = []
        self._track_testing_active: bool = False

    @property
    def track_testing_active(self) -> bool:
        """Indica se testes de track estão em andamento."""
        return self._track_testing_active

    @property
    def deferred_count(self) -> int:
        """Retorna a quantidade de escalações deferidas na fila."""
        return len(self._deferred_queue)

    def set_track_testing_active(self, active: bool) -> None:
        """Sinaliza se testes de track estão em andamento.

        Quando active=True, qualquer escalação será deferida ao invés
        de executada imediatamente, evitando interações DOM durante testes.

        Args:
            active: True se testes de track estão em andamento.
        """
        self._track_testing_active = active
        logger.info(
            "Track testing %s",
            "ativado" if active else "desativado",
        )

    def defer_escalation(self, trigger: DeferredEscalation) -> None:
        """Enfileira escalação para processamento posterior.

        Utilizado quando testes de track estão ativos. A escalação é
        armazenada na fila e será processada após os testes completarem,
        garantindo que NENHUMA interação DOM ocorra durante o período.

        Args:
            trigger: Trigger de escalação com contexto de telemetria.
        """
        self._deferred_queue.append(trigger)
        logger.info(
            "Escalação deferida enfileirada: health=%s, timestamp=%s, "
            "track_context=%s, total_na_fila=%d",
            trigger.health_classification,
            trigger.trigger_timestamp,
            "sim" if trigger.track_switch_context else "não",
            len(self._deferred_queue),
        )

    async def process_deferred(self) -> list[EscalationResult]:
        """Processa todas as escalações deferidas.

        Itera sobre a fila de escalações deferidas e executa o pipeline
        completo para cada uma: captura de frames → análise OpenCV →
        diagnóstico Bedrock (se anomalia confirmada).

        Returns:
            Lista de EscalationResult com resultados de cada escalação.
        """
        if not self._deferred_queue:
            logger.info("Nenhuma escalação deferida para processar")
            return []

        results: list[EscalationResult] = []
        pending = list(self._deferred_queue)
        self._deferred_queue.clear()

        logger.info(
            "Processando %d escalações deferidas",
            len(pending),
        )

        for trigger in pending:
            result = await self._execute_escalation_pipeline(
                trigger, deferred=True
            )
            results.append(result)

        logger.info(
            "Processamento de escalações deferidas concluído: %d resultados",
            len(results),
        )
        return results

    async def escalate_immediate(
        self, trigger: DeferredEscalation
    ) -> EscalationResult:
        """Executa escalação imediata (quando não há testes de track ativos).

        Pipeline completo executado imediatamente sem enfileiramento:
        captura de frames → análise OpenCV → diagnóstico Bedrock.

        Args:
            trigger: Trigger de escalação com contexto de telemetria.

        Returns:
            EscalationResult com resultado da escalação.
        """
        logger.info(
            "Escalação imediata: health=%s, timestamp=%s",
            trigger.health_classification,
            trigger.trigger_timestamp,
        )
        return await self._execute_escalation_pipeline(
            trigger, deferred=False
        )

    async def _execute_escalation_pipeline(
        self, trigger: DeferredEscalation, *, deferred: bool
    ) -> EscalationResult:
        """Executa o pipeline de escalação para um trigger.

        Fluxo:
        1. Captura frames via FrameCapturer
        2. Analisa com OpenCV (black_screen / freeze detection)
        3. Se anomalia confirmada, envia para Bedrock

        Cada etapa é protegida por try/except — falha em uma etapa
        não impede o registro do resultado parcial.

        Args:
            trigger: Trigger de escalação.
            deferred: True se foi uma escalação deferida.

        Returns:
            EscalationResult com dados coletados em cada etapa.
        """
        opencv_verdict: str | None = None
        bedrock_diagnosis: str | None = None
        frames_analyzed: int = 0

        # Etapa 1: Captura de frames
        frames_data = await self._capture_frames(trigger)
        if frames_data is None:
            # Sem frames → não há como analisar
            logger.warning(
                "Captura de frames falhou para trigger %s — "
                "escalação encerrada sem análise",
                trigger.trigger_timestamp,
            )
            return EscalationResult(
                trigger_timestamp=trigger.trigger_timestamp,
                opencv_verdict=None,
                bedrock_diagnosis=None,
                frames_analyzed=0,
                deferred=deferred,
            )

        frames_analyzed = len(frames_data)

        # Etapa 2: Análise OpenCV
        opencv_verdict = await self._analyze_opencv(frames_data, trigger)

        # Etapa 3: Bedrock (somente se OpenCV confirma anomalia)
        if opencv_verdict and opencv_verdict != "normal":
            bedrock_diagnosis = await self._diagnose_bedrock(
                frames_data, opencv_verdict, trigger
            )

        # Anotar com contexto de track switch se aplicável
        result = EscalationResult(
            trigger_timestamp=trigger.trigger_timestamp,
            opencv_verdict=opencv_verdict,
            bedrock_diagnosis=bedrock_diagnosis,
            frames_analyzed=frames_analyzed,
            deferred=deferred,
        )

        logger.info(
            "Escalação concluída: timestamp=%s, opencv=%s, "
            "bedrock=%s, frames=%d, deferred=%s",
            result.trigger_timestamp,
            result.opencv_verdict,
            "sim" if result.bedrock_diagnosis else "não",
            result.frames_analyzed,
            result.deferred,
        )

        return result

    async def _capture_frames(
        self, trigger: DeferredEscalation
    ) -> list[bytes] | None:
        """Captura frames via FrameCapturer.

        Args:
            trigger: Trigger com contexto para logging.

        Returns:
            Lista de bytes dos frames capturados, ou None se falhar.
        """
        if self._frame_capturer is None:
            logger.warning(
                "FrameCapturer não disponível — pulando captura"
            )
            return None

        try:
            frame_result = await self._frame_capturer.capture_frame(self._page)
            if frame_result.is_valid:
                return [frame_result.data]
            else:
                logger.warning(
                    "Frame capturado inválido: reason=%s",
                    frame_result.rejected_reason,
                )
                return None
        except Exception:
            logger.exception(
                "Erro ao capturar frame para escalação (trigger=%s)",
                trigger.trigger_timestamp,
            )
            return None

    async def _analyze_opencv(
        self,
        frames_data: list[bytes],
        trigger: DeferredEscalation,
    ) -> str | None:
        """Analisa frames com OpenCV para detectar anomalias.

        Verifica black_screen e freeze usando os métodos do OpenCVAnalyzer.

        Args:
            frames_data: Lista de bytes dos frames capturados.
            trigger: Trigger com contexto para logging.

        Returns:
            Veredito: 'black_screen' | 'freeze' | 'normal' | None se falhar.
        """
        if self._opencv_analyzer is None:
            logger.warning(
                "OpenCVAnalyzer não disponível — pulando análise OpenCV"
            )
            return None

        try:
            import numpy as np
            import cv2

            # Decodificar primeiro frame para análise
            frame_bytes = frames_data[0]
            nparr = np.frombuffer(frame_bytes, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

            if frame is None:
                logger.warning("Falha ao decodificar frame para OpenCV")
                return None

            # Verificar black screen
            black_result = self._opencv_analyzer.detect_black_screen(frame)
            if black_result.is_black_screen:
                logger.info(
                    "OpenCV detectou black_screen (trigger=%s)",
                    trigger.trigger_timestamp,
                )
                return "black_screen"

            # Verificar freeze (se houver mais de um frame)
            if len(frames_data) > 1:
                nparr_b = np.frombuffer(frames_data[1], np.uint8)
                frame_b = cv2.imdecode(nparr_b, cv2.IMREAD_COLOR)
                if frame_b is not None:
                    freeze_result = self._opencv_analyzer.detect_freeze(
                        frame_a=frame,
                        frame_b=frame_b,
                        current_time_diff=0.0,
                        observation_window_seconds=5.0,
                    )
                    # Importar FreezeClassification para verificar resultado
                    from src.opencv_analyzer import FreezeClassification

                    if (
                        freeze_result.classification
                        == FreezeClassification.FREEZE_CONFIRMED
                    ):
                        logger.info(
                            "OpenCV detectou freeze (trigger=%s)",
                            trigger.trigger_timestamp,
                        )
                        return "freeze"

            logger.info(
                "OpenCV: frame normal (trigger=%s)",
                trigger.trigger_timestamp,
            )
            return "normal"

        except Exception:
            logger.exception(
                "Erro na análise OpenCV (trigger=%s)",
                trigger.trigger_timestamp,
            )
            return None

    async def _diagnose_bedrock(
        self,
        frames_data: list[bytes],
        opencv_verdict: str,
        trigger: DeferredEscalation,
    ) -> str | None:
        """Envia frame para diagnóstico via Bedrock.

        Chamado somente quando OpenCV confirma anomalia (não 'normal').

        Args:
            frames_data: Lista de bytes dos frames.
            opencv_verdict: Veredito do OpenCV ('black_screen' ou 'freeze').
            trigger: Trigger com contexto para logging.

        Returns:
            Diagnóstico textual do Bedrock ou None se falhar.
        """
        if self._bedrock_client is None:
            logger.warning(
                "BedrockClient não disponível — pulando diagnóstico IA"
            )
            return None

        try:
            frame_bytes = frames_data[0]
            diagnosis_result = await self._bedrock_client.diagnose_frame(
                frame_data=frame_bytes,
                anomaly_confirmed=True,
            )
            diagnosis_text = (
                f"[{opencv_verdict}] {diagnosis_result.diagnosis}"
            )
            logger.info(
                "Bedrock diagnóstico: %s (trigger=%s)",
                diagnosis_text,
                trigger.trigger_timestamp,
            )
            return diagnosis_text

        except Exception:
            logger.exception(
                "Erro no diagnóstico Bedrock (trigger=%s)",
                trigger.trigger_timestamp,
            )
            return None

    def _get_timestamp(self) -> str:
        """Gera timestamp ISO 8601 com milissegundos em UTC."""
        now = datetime.now(timezone.utc)
        return (
            now.strftime("%Y-%m-%dT%H:%M:%S.")
            + f"{now.microsecond // 1000:03d}Z"
        )
