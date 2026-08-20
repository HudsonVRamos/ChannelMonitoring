# Feature: widevine-poc, Property 12: Lógica de escalação Haiku → Sonnet
"""Testes de propriedade para a lógica de escalação Haiku → Sonnet.

Validates: Requirements 8.5

Property 12: Para qualquer resultado do Haiku, se confidence < threshold
configurado, o sistema SHALL escalar para Sonnet. Se confidence >= threshold,
SHALL utilizar o resultado do Haiku sem escalação.
"""
from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import patch

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from src.bedrock_client import BedrockClient
from src.models import DiagnosisStatus


# =============================================================================
# Estratégias de geração de dados
# =============================================================================

# Confidence válida no range [0.0, 1.0]
confidence_st = st.floats(min_value=0.0, max_value=1.0, allow_nan=False)

# Threshold válido no range (0.0, 1.0) — excluindo extremos para ter espaço
threshold_st = st.floats(
    min_value=0.01, max_value=0.99, allow_nan=False
)

# Status válidos para resposta do Bedrock
status_st = st.sampled_from(["OK", "DEGRADED", "UNKNOWN"])

# Texto para campos de diagnóstico
diagnosis_text_st = st.text(min_size=1, max_size=50)

# Lista de issues
issues_st = st.lists(st.text(min_size=1, max_size=20), max_size=5)


# =============================================================================
# Helpers
# =============================================================================


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


def _make_valid_response(confidence: float, status: str = "DEGRADED") -> dict:
    """Cria um dicionário de resposta válida com confidence específica."""
    return {
        "status": status,
        "diagnosis": "Diagnóstico de teste",
        "issues": ["test_issue"],
        "description": "Descrição do diagnóstico de teste.",
        "confidence": confidence,
    }


def _create_client_with_threshold(threshold: float) -> BedrockClient:
    """Cria um BedrockClient com mock de boto3 e threshold configurado."""
    with patch("src.bedrock_client.boto3.client") as mock_boto:
        client = BedrockClient(
            timeout_seconds=30,
            confidence_threshold=threshold,
            region="us-east-1",
        )
        client._client = mock_boto.return_value
        return client


# =============================================================================
# Propriedade 12a: confidence < threshold → escalação (2 chamadas)
# =============================================================================


class TestEscalacaoQuandoConfidenceBaixa:
    """Para qualquer confidence < threshold, DEVE escalar para Sonnet."""

    @settings(max_examples=100)
    @given(
        haiku_confidence=confidence_st,
        threshold=threshold_st,
        sonnet_confidence=confidence_st,
        status=status_st,
    )
    @pytest.mark.asyncio
    async def test_escala_para_sonnet_quando_confidence_abaixo_threshold(
        self,
        haiku_confidence: float,
        threshold: float,
        sonnet_confidence: float,
        status: str,
    ):
        """**Validates: Requirements 8.5**

        Para qualquer resultado do Haiku com confidence < threshold,
        o sistema SHALL escalar para Sonnet (invoke_model chamado 2x).
        """
        # Garantir que haiku_confidence é estritamente menor que threshold
        assume(haiku_confidence < threshold)

        client = _create_client_with_threshold(threshold)
        sample_frame = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100

        # Respostas simuladas
        haiku_response = _make_valid_response(haiku_confidence, status)
        sonnet_response = _make_valid_response(sonnet_confidence, status)

        call_count = [0]

        def mock_invoke_model(**kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return _make_bedrock_response(haiku_response)
            return _make_bedrock_response(sonnet_response)

        client._client.invoke_model.side_effect = mock_invoke_model

        result = await client.diagnose_frame(sample_frame, anomaly_confirmed=True)

        # Deve ter escalado (2 chamadas ao invoke_model)
        assert client._client.invoke_model.call_count == 2, (
            f"Esperado 2 chamadas (escalação), mas obteve "
            f"{client._client.invoke_model.call_count}. "
            f"haiku_confidence={haiku_confidence}, threshold={threshold}"
        )
        # Resultado deve indicar escalação
        assert result.escalated is True, (
            f"Resultado deveria ter escalated=True. "
            f"haiku_confidence={haiku_confidence}, threshold={threshold}"
        )
        # Modelo usado deve ser sonnet
        assert result.model_used == "sonnet", (
            f"Modelo usado deveria ser 'sonnet', mas foi '{result.model_used}'"
        )


# =============================================================================
# Propriedade 12b: confidence >= threshold → sem escalação (1 chamada)
# =============================================================================


class TestSemEscalacaoQuandoConfidenceSuficiente:
    """Para qualquer confidence >= threshold, NÃO deve escalar."""

    @settings(max_examples=100)
    @given(
        haiku_confidence=confidence_st,
        threshold=threshold_st,
        status=status_st,
    )
    @pytest.mark.asyncio
    async def test_nao_escala_quando_confidence_acima_ou_igual_threshold(
        self,
        haiku_confidence: float,
        threshold: float,
        status: str,
    ):
        """**Validates: Requirements 8.5**

        Para qualquer resultado do Haiku com confidence >= threshold,
        o sistema SHALL usar resultado do Haiku sem escalação (invoke_model 1x).
        """
        # Garantir que haiku_confidence >= threshold
        assume(haiku_confidence >= threshold)

        client = _create_client_with_threshold(threshold)
        sample_frame = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100

        # Resposta simulada do Haiku com confidence suficiente
        haiku_response = _make_valid_response(haiku_confidence, status)
        client._client.invoke_model.return_value = _make_bedrock_response(
            haiku_response
        )

        result = await client.diagnose_frame(sample_frame, anomaly_confirmed=True)

        # Deve ter usado apenas Haiku (1 chamada ao invoke_model)
        assert client._client.invoke_model.call_count == 1, (
            f"Esperado 1 chamada (sem escalação), mas obteve "
            f"{client._client.invoke_model.call_count}. "
            f"haiku_confidence={haiku_confidence}, threshold={threshold}"
        )
        # Resultado NÃO deve indicar escalação
        assert result.escalated is False, (
            f"Resultado deveria ter escalated=False. "
            f"haiku_confidence={haiku_confidence}, threshold={threshold}"
        )
        # Modelo usado deve ser haiku
        assert result.model_used == "haiku", (
            f"Modelo usado deveria ser 'haiku', mas foi '{result.model_used}'"
        )
        # Confidence no resultado deve ser a mesma do Haiku
        assert result.confidence == haiku_confidence, (
            f"Confidence deveria ser {haiku_confidence}, "
            f"mas foi {result.confidence}"
        )
