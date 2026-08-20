# Feature: widevine-poc, Property 13: Gate de pré-requisito para Bedrock
"""
Property-based tests para o gate de pré-requisito do Bedrock.

Validates: Requirements 8.6

Propriedade: Para qualquer requisição ao BedrockClient onde
anomaly_confirmed=False, o sistema SHALL rejeitar a requisição
imediatamente sem realizar chamada à API do Bedrock.
"""
from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from src.bedrock_client import BedrockClient
from src.models import DiagnosisStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_client() -> BedrockClient:
    """Cria um BedrockClient com mock de boto3."""
    with patch("src.bedrock_client.boto3.client") as mock_boto:
        client = BedrockClient(
            timeout_seconds=30,
            confidence_threshold=0.7,
            region="us-east-1",
        )
        client._client = mock_boto.return_value
        return client


def _make_bedrock_response(diagnosis_json: dict) -> dict:
    """Cria uma resposta simulada do Bedrock."""
    content_text = json.dumps(diagnosis_json)
    response_body = json.dumps({
        "content": [{"type": "text", "text": content_text}],
    })
    body_stream = BytesIO(response_body.encode("utf-8"))
    return {
        "body": body_stream,
        "ResponseMetadata": {"HTTPStatusCode": 200},
    }


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Frame data: bytes de qualquer tamanho entre 1 e 1000
frame_data_st = st.binary(min_size=1, max_size=1000)


# ---------------------------------------------------------------------------
# Propriedade 1: anomaly_confirmed=False → rejeição sem chamar API
# ---------------------------------------------------------------------------


class TestGateRejeicaoSemAnomalia:
    """anomaly_confirmed=False → rejeita sem chamar invoke_model."""

    @settings(max_examples=100)
    @given(frame_data=frame_data_st)
    @pytest.mark.asyncio
    async def test_rejeita_sem_chamar_api(self, frame_data: bytes):
        """
        **Validates: Requirements 8.6**

        Para qualquer frame_data (bytes de qualquer tamanho),
        se anomaly_confirmed=False:
        - result.status == UNKNOWN
        - result.confidence == 0.0
        - invoke_model NÃO foi chamado
        """
        client = _create_client()

        result = await client.diagnose_frame(
            frame_data, anomaly_confirmed=False
        )

        assert result.status == DiagnosisStatus.UNKNOWN
        assert result.confidence == 0.0
        client._client.invoke_model.assert_not_called()


# ---------------------------------------------------------------------------
# Propriedade 2: anomaly_confirmed=True → invoke_model É chamado
# ---------------------------------------------------------------------------


class TestGateChamaApiComAnomalia:
    """anomaly_confirmed=True → invoke_model é chamado."""

    @settings(max_examples=100)
    @given(frame_data=frame_data_st)
    @pytest.mark.asyncio
    async def test_chama_api_quando_anomalia_confirmada(
        self, frame_data: bytes
    ):
        """
        **Validates: Requirements 8.6**

        Para qualquer frame_data (bytes de qualquer tamanho),
        se anomaly_confirmed=True:
        - invoke_model É chamado (pelo menos uma vez)
        """
        client = _create_client()

        # Configurar resposta válida para a chamada ao Bedrock
        valid_response = {
            "status": "OK",
            "diagnosis": "Canal OK",
            "issues": [],
            "description": "Sem problemas detectados.",
            "confidence": 0.9,
        }
        client._client.invoke_model.return_value = (
            _make_bedrock_response(valid_response)
        )

        await client.diagnose_frame(
            frame_data, anomaly_confirmed=True
        )

        client._client.invoke_model.assert_called()
