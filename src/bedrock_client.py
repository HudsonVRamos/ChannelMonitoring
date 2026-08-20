"""Cliente para diagnóstico visual via Amazon Bedrock.

Envia frames com anomalia confirmada ao Claude Haiku para diagnóstico.
Se a confiança for baixa, escala para Claude Sonnet.
Canal saudável não consome IA — gate de pré-requisito rejeita frames
sem anomalia confirmada.
"""
from __future__ import annotations

import asyncio
import base64
import json
import time

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import (
    ClientError,
    ReadTimeoutError,
    ConnectTimeoutError,
)

from src.models import DiagnosisResult, DiagnosisStatus
from src.structured_logger import StructuredLogger

# IDs dos modelos Anthropic no Bedrock
_HAIKU_MODEL_ID = "anthropic.claude-3-haiku-20240307-v1:0"
_SONNET_MODEL_ID = "anthropic.claude-3-sonnet-20240229-v1:0"

# Prompt de diagnóstico para análise visual
_DIAGNOSIS_PROMPT = (
    "Analise este frame de vídeo ao vivo de um canal de TV. "
    "Identifique problemas visuais como: tela preta, "
    "freeze/congelamento, artefatos de vídeo, buffering, "
    "degradação de qualidade ou problemas de DRM. "
    "Responda APENAS com um JSON válido no seguinte formato:\n"
    "{\n"
    '  "status": "OK" | "DEGRADED" | "UNKNOWN",\n'
    '  "diagnosis": "descrição curta do diagnóstico",\n'
    '  "issues": ["lista", "de", "problemas"],\n'
    '  "description": "descrição detalhada da análise",\n'
    '  "confidence": 0.0 a 1.0\n'
    "}"
)

# Stage ID para logging estruturado
_STAGE_ID = "bedrock_client"


class BedrockClient:
    """Cliente para diagnóstico visual via Amazon Bedrock."""

    def __init__(
        self,
        timeout_seconds: int = 30,
        confidence_threshold: float = 0.7,
        region: str = "us-east-1",
    ) -> None:
        """Inicializa o cliente Bedrock com configuração de timeout.

        Args:
            timeout_seconds: Timeout máximo para chamadas ao
                Bedrock (padrão: 30s).
            confidence_threshold: Threshold mínimo de confiança
                do Haiku para aceitar sem escalar (padrão: 0.7).
            region: Região AWS onde o Bedrock está disponível.
        """
        self._timeout_seconds = timeout_seconds
        self._confidence_threshold = confidence_threshold
        self._region = region
        self._logger = StructuredLogger()

        # Configuração do boto3 com timeout
        boto_config = BotoConfig(
            region_name=self._region,
            read_timeout=self._timeout_seconds,
            connect_timeout=self._timeout_seconds,
            retries={"max_attempts": 0},
        )
        self._client = boto3.client(
            "bedrock-runtime",
            config=boto_config,
            region_name=self._region,
        )

    async def diagnose_frame(
        self, frame_data: bytes, anomaly_confirmed: bool
    ) -> DiagnosisResult:
        """Envia frame para diagnóstico. Rejeita se não confirmada.

        Gate de pré-requisito: se anomaly_confirmed=False, retorna
        imediatamente sem chamar a API do Bedrock (canal saudável
        não consome IA).

        Args:
            frame_data: Dados do frame em bytes (PNG/JPEG).
            anomaly_confirmed: Se a anomalia foi confirmada pelas camadas
                anteriores (detecção determinística ou OpenCV).

        Returns:
            DiagnosisResult com o diagnóstico do frame.
        """
        # Gate de pré-requisito — rejeitar se anomalia não confirmada
        if not anomaly_confirmed:
            self._logger.info(
                _STAGE_ID,
                "Requisição rejeitada: anomalia não confirmada",
            )
            return DiagnosisResult(
                status=DiagnosisStatus.UNKNOWN,
                diagnosis="Anomaly not confirmed",
                issues=[],
                description="Requisição rejeitada pelo gate de pré-requisito. "
                "Anomalia não foi confirmada pelas camadas anteriores.",
                confidence=0.0,
                model_used="none",
                response_time_ms=0,
                escalated=False,
            )

        # Codificar frame em base64
        frame_b64 = base64.b64encode(frame_data).decode("utf-8")

        # Invocar Haiku primeiro
        result = await self._invoke_haiku(frame_b64)

        # Escalar para Sonnet se confiança abaixo do threshold
        if result.confidence < self._confidence_threshold:
            self._logger.info(
                _STAGE_ID,
                "Escalando para Sonnet: confidence abaixo do threshold",
                haiku_confidence=result.confidence,
                threshold=self._confidence_threshold,
            )
            sonnet_result = await self._invoke_sonnet(frame_b64)
            sonnet_result.escalated = True
            return sonnet_result

        return result

    async def _invoke_haiku(self, frame_b64: str) -> DiagnosisResult:
        """Invoca Claude Haiku para diagnóstico visual.

        Args:
            frame_b64: Frame codificado em base64.

        Returns:
            DiagnosisResult com diagnóstico do Haiku.
        """
        return await self._invoke_model(
            model_id=_HAIKU_MODEL_ID,
            model_name="haiku",
            frame_b64=frame_b64,
        )

    async def _invoke_sonnet(self, frame_b64: str) -> DiagnosisResult:
        """Invoca Claude Sonnet para casos de baixa confiança.

        Args:
            frame_b64: Frame codificado em base64.

        Returns:
            DiagnosisResult com diagnóstico do Sonnet.
        """
        return await self._invoke_model(
            model_id=_SONNET_MODEL_ID,
            model_name="sonnet",
            frame_b64=frame_b64,
        )

    async def _invoke_model(
        self, model_id: str, model_name: str, frame_b64: str
    ) -> DiagnosisResult:
        """Invoca um modelo Bedrock com o frame fornecido.

        Usa asyncio.to_thread para executar a chamada síncrona do boto3
        sem bloquear o event loop.

        Args:
            model_id: ID do modelo no Bedrock.
            model_name: Nome amigável do modelo (para logging).
            frame_b64: Frame codificado em base64.

        Returns:
            DiagnosisResult com diagnóstico do modelo.
        """
        payload_size = len(frame_b64)
        start_time = time.perf_counter()

        try:
            # Montar payload no formato Anthropic Messages API
            body = json.dumps({
                "anthropic_version": "bedrock-2023-12-15",
                "max_tokens": 1024,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": frame_b64,
                                },
                            },
                            {
                                "type": "text",
                                "text": _DIAGNOSIS_PROMPT,
                            },
                        ],
                    }
                ],
            })

            # Executar chamada síncrona do boto3 em thread separada
            response = await asyncio.to_thread(
                self._client.invoke_model,
                modelId=model_id,
                contentType="application/json",
                accept="application/json",
                body=body,
            )

            elapsed_ms = int((time.perf_counter() - start_time) * 1000)
            http_status = response.get("ResponseMetadata", {}).get(
                "HTTPStatusCode", 0
            )

            # Log INFO com modelo, payload, tempo e status HTTP
            self._logger.info(
                _STAGE_ID,
                "Resposta recebida do Bedrock",
                model=model_name,
                payload_size_bytes=payload_size,
                response_time_ms=elapsed_ms,
                http_status=http_status,
            )

            # Parsear corpo da resposta
            response_body = json.loads(
                response["body"].read().decode("utf-8")
            )

            # Extrair texto da resposta do modelo
            content = response_body.get("content", [])
            if not content or not isinstance(content, list):
                self._logger.error(
                    _STAGE_ID,
                    "Resposta do Bedrock sem conteúdo válido",
                    response_body=str(response_body)[:500],
                )
                return self._unknown_result(model_name, elapsed_ms)

            text_content = ""
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_content = block.get("text", "")
                    break

            if not text_content:
                self._logger.error(
                    _STAGE_ID,
                    "Resposta do Bedrock sem bloco de texto",
                    content=str(content)[:500],
                )
                return self._unknown_result(model_name, elapsed_ms)

            # Parsear JSON do diagnóstico
            try:
                diagnosis_data = json.loads(text_content)
            except json.JSONDecodeError:
                self._logger.error(
                    _STAGE_ID,
                    "Resposta do Bedrock não é JSON válido",
                    raw_text=text_content[:500],
                )
                return self._unknown_result(model_name, elapsed_ms)

            result = self._parse_response(diagnosis_data)
            result.model_used = model_name
            result.response_time_ms = elapsed_ms
            return result

        except (ReadTimeoutError, ConnectTimeoutError) as e:
            elapsed_ms = int((time.perf_counter() - start_time) * 1000)
            self._logger.error(
                _STAGE_ID,
                "Timeout na chamada ao Bedrock",
                model=model_name,
                timeout_seconds=self._timeout_seconds,
                error=str(e),
            )
            return self._unknown_result(model_name, elapsed_ms)

        except ClientError as e:
            elapsed_ms = int((time.perf_counter() - start_time) * 1000)
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_msg = e.response.get("Error", {}).get("Message", str(e))
            self._logger.error(
                _STAGE_ID,
                "Erro de API na chamada ao Bedrock",
                model=model_name,
                error_code=error_code,
                error_message=error_msg,
                response_time_ms=elapsed_ms,
            )
            return self._unknown_result(model_name, elapsed_ms)

        except Exception as e:
            elapsed_ms = int((time.perf_counter() - start_time) * 1000)
            self._logger.error(
                _STAGE_ID,
                "Erro inesperado na chamada ao Bedrock",
                model=model_name,
                error=str(e),
                error_type=type(e).__name__,
            )
            return self._unknown_result(model_name, elapsed_ms)

    def _parse_response(self, response: dict) -> DiagnosisResult:
        """Parseia e valida resposta JSON do Bedrock.

        Valida presença e tipos dos campos obrigatórios:
        - status: "OK", "DEGRADED" ou "UNKNOWN"
        - diagnosis: string
        - issues: lista de strings
        - description: string
        - confidence: float entre 0.0 e 1.0

        Args:
            response: Dicionário parseado da resposta do modelo.

        Returns:
            DiagnosisResult válido ou UNKNOWN se validação falhar.
        """
        try:
            # Validar campo status
            status_str = response.get("status")
            if status_str not in ("OK", "DEGRADED", "UNKNOWN"):
                self._logger.error(
                    _STAGE_ID,
                    "Campo 'status' inválido na resposta",
                    status=status_str,
                )
                return self._unknown_result("unknown", 0)

            # Validar campo diagnosis
            diagnosis = response.get("diagnosis")
            if not isinstance(diagnosis, str):
                self._logger.error(
                    _STAGE_ID,
                    "Campo 'diagnosis' ausente ou inválido",
                )
                return self._unknown_result("unknown", 0)

            # Validar campo issues
            issues = response.get("issues")
            if not isinstance(issues, list):
                self._logger.error(
                    _STAGE_ID,
                    "Campo 'issues' ausente ou inválido",
                )
                return self._unknown_result("unknown", 0)

            # Validar campo description
            description = response.get("description")
            if not isinstance(description, str):
                self._logger.error(
                    _STAGE_ID,
                    "Campo 'description' ausente ou inválido",
                )
                return self._unknown_result("unknown", 0)

            # Validar campo confidence
            confidence = response.get("confidence")
            if not isinstance(confidence, (int, float)):
                self._logger.error(
                    _STAGE_ID,
                    "Campo 'confidence' ausente ou inválido",
                )
                return self._unknown_result("unknown", 0)

            confidence = float(confidence)
            if confidence < 0.0 or confidence > 1.0:
                self._logger.error(
                    _STAGE_ID,
                    "Campo 'confidence' fora do range [0.0, 1.0]",
                    confidence=confidence,
                )
                return self._unknown_result("unknown", 0)

            # Mapear status string para enum
            status = DiagnosisStatus(status_str)

            return DiagnosisResult(
                status=status,
                diagnosis=diagnosis,
                issues=[str(i) for i in issues],
                description=description,
                confidence=confidence,
                model_used="unknown",  # Será sobrescrito pelo chamador
                response_time_ms=0,  # Será sobrescrito pelo chamador
                escalated=False,
            )

        except Exception as e:
            self._logger.error(
                _STAGE_ID,
                "Erro ao parsear resposta do Bedrock",
                error=str(e),
                error_type=type(e).__name__,
            )
            return self._unknown_result("unknown", 0)

    def _unknown_result(
        self, model_name: str, response_time_ms: int
    ) -> DiagnosisResult:
        """Cria um DiagnosisResult padrão para erros/falhas.

        Args:
            model_name: Nome do modelo que falhou.
            response_time_ms: Tempo decorrido até o erro.

        Returns:
            DiagnosisResult com status UNKNOWN e confidence 0.0.
        """
        return DiagnosisResult(
            status=DiagnosisStatus.UNKNOWN,
            diagnosis="Diagnóstico indisponível",
            issues=[],
            description="Não foi possível obter diagnóstico do modelo.",
            confidence=0.0,
            model_used=model_name,
            response_time_ms=response_time_ms,
            escalated=False,
        )
