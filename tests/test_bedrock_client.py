"""Testes unitários para o BedrockClient.

Testa a lógica de gate de pré-requisito, parsing de resposta,
escalação para Sonnet e tratamento de erros.
"""
from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import patch

import pytest

from src.bedrock_client import BedrockClient
from src.models import DiagnosisStatus


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def client():
    """Cria um BedrockClient com mock do boto3."""
    with patch("src.bedrock_client.boto3.client") as mock_boto:
        c = BedrockClient(
            timeout_seconds=30,
            confidence_threshold=0.7,
            region="us-east-1",
        )
        c._client = mock_boto.return_value
        yield c


@pytest.fixture
def sample_frame() -> bytes:
    """Frame de exemplo (dados binários simples)."""
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * 100


def _make_bedrock_response(diagnosis_json: dict, http_status: int = 200):
    """Cria uma resposta simulada do Bedrock."""
    content_text = json.dumps(diagnosis_json)
    response_body = json.dumps({
        "content": [{"type": "text", "text": content_text}],
    })
    body_stream = BytesIO(response_body.encode("utf-8"))
    return {
        "body": body_stream,
        "ResponseMetadata": {"HTTPStatusCode": http_status},
    }


# =============================================================================
# Testes do Gate de Pré-requisito
# =============================================================================


class TestGatePrerequisito:
    """Testes para o gate de pré-requisito (anomaly_confirmed)."""

    @pytest.mark.asyncio
    async def test_rejeita_quando_anomalia_nao_confirmada(self, client, sample_frame):
        """Deve retornar UNKNOWN sem chamar API quando anomaly_confirmed=False."""
        result = await client.diagnose_frame(sample_frame, anomaly_confirmed=False)

        assert result.status == DiagnosisStatus.UNKNOWN
        assert result.confidence == 0.0
        assert result.diagnosis == "Anomaly not confirmed"
        assert result.model_used == "none"
        assert result.response_time_ms == 0
        # Não deve ter chamado o boto3
        client._client.invoke_model.assert_not_called()

    @pytest.mark.asyncio
    async def test_aceita_quando_anomalia_confirmada(self, client, sample_frame):
        """Deve chamar API quando anomaly_confirmed=True."""
        # Configurar resposta válida do Bedrock
        valid_response = {
            "status": "DEGRADED",
            "diagnosis": "Tela preta detectada",
            "issues": ["black_screen"],
            "description": "O frame apresenta tela completamente preta.",
            "confidence": 0.9,
        }
        client._client.invoke_model.return_value = _make_bedrock_response(
            valid_response
        )

        result = await client.diagnose_frame(sample_frame, anomaly_confirmed=True)

        assert result.status == DiagnosisStatus.DEGRADED
        assert result.confidence == 0.9
        client._client.invoke_model.assert_called_once()


# =============================================================================
# Testes do _parse_response
# =============================================================================


class TestParseResponse:
    """Testes para validação e parsing da resposta do Bedrock."""

    def test_resposta_valida_ok(self, client):
        """Deve parsear corretamente uma resposta válida com status OK."""
        response = {
            "status": "OK",
            "diagnosis": "Canal funcionando normalmente",
            "issues": [],
            "description": "Nenhum problema detectado no frame.",
            "confidence": 0.95,
        }
        result = client._parse_response(response)

        assert result.status == DiagnosisStatus.OK
        assert result.diagnosis == "Canal funcionando normalmente"
        assert result.issues == []
        assert result.description == "Nenhum problema detectado no frame."
        assert result.confidence == 0.95

    def test_resposta_valida_degraded(self, client):
        """Deve parsear corretamente uma resposta com status DEGRADED."""
        response = {
            "status": "DEGRADED",
            "diagnosis": "Artefatos de vídeo",
            "issues": ["video_artifacts", "compression"],
            "description": "Artefatos visíveis indicando degradação.",
            "confidence": 0.85,
        }
        result = client._parse_response(response)

        assert result.status == DiagnosisStatus.DEGRADED
        assert result.issues == ["video_artifacts", "compression"]
        assert result.confidence == 0.85

    def test_resposta_valida_unknown(self, client):
        """Deve parsear corretamente uma resposta com status UNKNOWN."""
        response = {
            "status": "UNKNOWN",
            "diagnosis": "Não foi possível determinar",
            "issues": [],
            "description": "Frame ambíguo.",
            "confidence": 0.3,
        }
        result = client._parse_response(response)

        assert result.status == DiagnosisStatus.UNKNOWN
        assert result.confidence == 0.3

    def test_status_invalido_retorna_unknown(self, client):
        """Deve retornar UNKNOWN se status não é OK/DEGRADED/UNKNOWN."""
        response = {
            "status": "INVALID",
            "diagnosis": "teste",
            "issues": [],
            "description": "teste",
            "confidence": 0.5,
        }
        result = client._parse_response(response)

        assert result.status == DiagnosisStatus.UNKNOWN
        assert result.confidence == 0.0

    def test_campo_diagnosis_ausente_retorna_unknown(self, client):
        """Deve retornar UNKNOWN se campo diagnosis está ausente."""
        response = {
            "status": "OK",
            "issues": [],
            "description": "teste",
            "confidence": 0.5,
        }
        result = client._parse_response(response)

        assert result.status == DiagnosisStatus.UNKNOWN
        assert result.confidence == 0.0

    def test_campo_issues_nao_lista_retorna_unknown(self, client):
        """Deve retornar UNKNOWN se campo issues não é uma lista."""
        response = {
            "status": "OK",
            "diagnosis": "teste",
            "issues": "não é lista",
            "description": "teste",
            "confidence": 0.5,
        }
        result = client._parse_response(response)

        assert result.status == DiagnosisStatus.UNKNOWN
        assert result.confidence == 0.0

    def test_campo_description_ausente_retorna_unknown(self, client):
        """Deve retornar UNKNOWN se campo description está ausente."""
        response = {
            "status": "OK",
            "diagnosis": "teste",
            "issues": [],
            "confidence": 0.5,
        }
        result = client._parse_response(response)

        assert result.status == DiagnosisStatus.UNKNOWN
        assert result.confidence == 0.0

    def test_confidence_fora_range_retorna_unknown(self, client):
        """Deve retornar UNKNOWN se confidence está fora de [0.0, 1.0]."""
        response = {
            "status": "OK",
            "diagnosis": "teste",
            "issues": [],
            "description": "teste",
            "confidence": 1.5,
        }
        result = client._parse_response(response)

        assert result.status == DiagnosisStatus.UNKNOWN
        assert result.confidence == 0.0

    def test_confidence_negativa_retorna_unknown(self, client):
        """Deve retornar UNKNOWN se confidence é negativa."""
        response = {
            "status": "OK",
            "diagnosis": "teste",
            "issues": [],
            "description": "teste",
            "confidence": -0.1,
        }
        result = client._parse_response(response)

        assert result.status == DiagnosisStatus.UNKNOWN
        assert result.confidence == 0.0

    def test_confidence_inteiro_aceito(self, client):
        """Deve aceitar confidence como inteiro (0 ou 1)."""
        response = {
            "status": "OK",
            "diagnosis": "teste",
            "issues": [],
            "description": "teste",
            "confidence": 1,
        }
        result = client._parse_response(response)

        assert result.status == DiagnosisStatus.OK
        assert result.confidence == 1.0

    def test_confidence_nao_numero_retorna_unknown(self, client):
        """Deve retornar UNKNOWN se confidence não é número."""
        response = {
            "status": "OK",
            "diagnosis": "teste",
            "issues": [],
            "description": "teste",
            "confidence": "alto",
        }
        result = client._parse_response(response)

        assert result.status == DiagnosisStatus.UNKNOWN
        assert result.confidence == 0.0


# =============================================================================
# Testes de Escalação Haiku → Sonnet
# =============================================================================


class TestEscalacao:
    """Testes para lógica de escalação para Sonnet."""

    @pytest.mark.asyncio
    async def test_escala_para_sonnet_quando_confidence_baixa(
        self, client, sample_frame
    ):
        """Deve escalar para Sonnet quando Haiku retorna confidence < threshold."""
        # Primeira chamada (Haiku) com confidence baixa
        haiku_response = {
            "status": "DEGRADED",
            "diagnosis": "Possível problema",
            "issues": ["unclear"],
            "description": "Análise inconclusiva.",
            "confidence": 0.5,
        }
        # Segunda chamada (Sonnet) com confidence alta
        sonnet_response = {
            "status": "DEGRADED",
            "diagnosis": "Tela preta confirmada",
            "issues": ["black_screen"],
            "description": "Tela completamente preta detectada pelo Sonnet.",
            "confidence": 0.95,
        }

        call_count = [0]

        def mock_invoke_model(**kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return _make_bedrock_response(haiku_response)
            return _make_bedrock_response(sonnet_response)

        client._client.invoke_model.side_effect = mock_invoke_model

        result = await client.diagnose_frame(sample_frame, anomaly_confirmed=True)

        assert result.status == DiagnosisStatus.DEGRADED
        assert result.confidence == 0.95
        assert result.escalated is True
        assert result.model_used == "sonnet"
        assert client._client.invoke_model.call_count == 2

    @pytest.mark.asyncio
    async def test_nao_escala_quando_confidence_suficiente(
        self, client, sample_frame
    ):
        """Não deve escalar para Sonnet quando confidence >= threshold."""
        valid_response = {
            "status": "OK",
            "diagnosis": "Canal OK",
            "issues": [],
            "description": "Sem problemas.",
            "confidence": 0.85,
        }
        client._client.invoke_model.return_value = _make_bedrock_response(
            valid_response
        )

        result = await client.diagnose_frame(sample_frame, anomaly_confirmed=True)

        assert result.status == DiagnosisStatus.OK
        assert result.confidence == 0.85
        assert result.escalated is False
        assert result.model_used == "haiku"
        assert client._client.invoke_model.call_count == 1


# =============================================================================
# Testes de Tratamento de Erros
# =============================================================================


class TestTratamentoErros:
    """Testes para tratamento de timeout, erros de API e respostas inválidas."""

    @pytest.mark.asyncio
    async def test_timeout_retorna_unknown(self, client, sample_frame):
        """Deve retornar UNKNOWN com confidence=0.0 em caso de timeout."""
        from botocore.exceptions import ReadTimeoutError

        client._client.invoke_model.side_effect = ReadTimeoutError(
            endpoint_url="https://bedrock.us-east-1.amazonaws.com"
        )

        result = await client.diagnose_frame(sample_frame, anomaly_confirmed=True)

        assert result.status == DiagnosisStatus.UNKNOWN
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_client_error_retorna_unknown(self, client, sample_frame):
        """Deve retornar UNKNOWN com confidence=0.0 em caso de erro de API."""
        from botocore.exceptions import ClientError

        client._client.invoke_model.side_effect = ClientError(
            error_response={
                "Error": {
                    "Code": "ThrottlingException",
                    "Message": "Rate exceeded",
                }
            },
            operation_name="InvokeModel",
        )

        result = await client.diagnose_frame(sample_frame, anomaly_confirmed=True)

        assert result.status == DiagnosisStatus.UNKNOWN
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_resposta_nao_json_retorna_unknown(self, client, sample_frame):
        """Deve retornar UNKNOWN quando resposta do modelo não é JSON válido."""
        # Simular resposta com texto não-JSON
        response_body = json.dumps({
            "content": [{"type": "text", "text": "Isso não é JSON válido..."}],
        })
        body_stream = BytesIO(response_body.encode("utf-8"))
        client._client.invoke_model.return_value = {
            "body": body_stream,
            "ResponseMetadata": {"HTTPStatusCode": 200},
        }

        result = await client.diagnose_frame(sample_frame, anomaly_confirmed=True)

        assert result.status == DiagnosisStatus.UNKNOWN
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_resposta_sem_campos_obrigatorios_retorna_unknown(
        self, client, sample_frame
    ):
        """Deve retornar UNKNOWN quando resposta tem campos faltando."""
        incomplete_response = {"status": "OK"}  # Faltam outros campos
        client._client.invoke_model.return_value = _make_bedrock_response(
            incomplete_response
        )

        result = await client.diagnose_frame(sample_frame, anomaly_confirmed=True)

        assert result.status == DiagnosisStatus.UNKNOWN
        assert result.confidence == 0.0
