# Feature: widevine-poc, Property 11: Parsing de resposta do Bedrock
"""
Property-based tests para parsing de resposta do Bedrock.

Validates: Requirements 8.2, 8.4

Propriedade: Para qualquer resposta válida do Bedrock (JSON com status
OK|DEGRADED|UNKNOWN, diagnosis string, issues list, description string,
confidence float 0.0-1.0), o parser SHALL produzir um DiagnosisResult válido.
Para qualquer resposta inválida (não-JSON, campos faltando, tipos incorretos),
SHALL retornar status=UNKNOWN com confidence=0.0.
"""
from __future__ import annotations

from unittest.mock import patch

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from src.bedrock_client import BedrockClient
from src.models import DiagnosisStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_client() -> BedrockClient:
    """Cria instância de BedrockClient com boto3 mockado."""
    with patch("src.bedrock_client.boto3.client"):
        return BedrockClient()


# Cliente reutilizável — _parse_response é stateless
_client = _create_client()


def make_valid_response(
    status: str,
    diagnosis: str,
    issues: list,
    description: str,
    confidence: float,
) -> dict:
    """Monta dicionário de resposta válida do Bedrock."""
    return {
        "status": status,
        "diagnosis": diagnosis,
        "issues": issues,
        "description": description,
        "confidence": confidence,
    }


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

valid_status_st = st.sampled_from(["OK", "DEGRADED", "UNKNOWN"])
valid_diagnosis_st = st.text(min_size=1, max_size=200)
valid_issues_st = st.lists(st.text(min_size=0, max_size=100), max_size=10)
valid_description_st = st.text(min_size=1, max_size=500)
valid_confidence_st = st.floats(min_value=0.0, max_value=1.0, allow_nan=False)

# Campos obrigatórios para remoção
required_fields = ["status", "diagnosis", "issues", "description", "confidence"]

# Status inválidos
invalid_status_st = st.text(min_size=1, max_size=50).filter(
    lambda s: s not in ("OK", "DEGRADED", "UNKNOWN")
)


# ---------------------------------------------------------------------------
# Propriedade 1: Respostas válidas → DiagnosisResult válido
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    status=valid_status_st,
    diagnosis=valid_diagnosis_st,
    issues=valid_issues_st,
    description=valid_description_st,
    confidence=valid_confidence_st,
)
def test_valid_response_produces_valid_diagnosis_result(
    status, diagnosis, issues, description, confidence
):
    """
    **Validates: Requirements 8.2, 8.4**

    Respostas válidas com todos os campos corretos produzem
    DiagnosisResult com valores correspondentes.
    """
    response = make_valid_response(
        status=status,
        diagnosis=diagnosis,
        issues=issues,
        description=description,
        confidence=confidence,
    )

    result = _client._parse_response(response)

    assert result.status == DiagnosisStatus(status)
    assert result.diagnosis == diagnosis
    assert result.issues == [str(i) for i in issues]
    assert result.description == description
    assert result.confidence == confidence


# ---------------------------------------------------------------------------
# Propriedade 2: Campo obrigatório ausente → UNKNOWN com confidence=0.0
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    status=valid_status_st,
    diagnosis=valid_diagnosis_st,
    issues=valid_issues_st,
    description=valid_description_st,
    confidence=valid_confidence_st,
    field_to_remove=st.sampled_from(required_fields),
)
def test_missing_required_field_returns_unknown(
    status,
    diagnosis,
    issues,
    description,
    confidence,
    field_to_remove,
):
    """
    **Validates: Requirements 8.2, 8.4**

    A ausência de qualquer campo obrigatório produz
    status=UNKNOWN com confidence=0.0.
    """
    response = make_valid_response(
        status=status,
        diagnosis=diagnosis,
        issues=issues,
        description=description,
        confidence=confidence,
    )
    del response[field_to_remove]

    result = _client._parse_response(response)

    assert result.status == DiagnosisStatus.UNKNOWN
    assert result.confidence == 0.0


# ---------------------------------------------------------------------------
# Propriedade 3: Status inválido → UNKNOWN com confidence=0.0
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    invalid_status=invalid_status_st,
    diagnosis=valid_diagnosis_st,
    issues=valid_issues_st,
    description=valid_description_st,
    confidence=valid_confidence_st,
)
def test_invalid_status_returns_unknown(
    invalid_status,
    diagnosis,
    issues,
    description,
    confidence,
):
    """
    **Validates: Requirements 8.2, 8.4**

    Valor de status que não é OK, DEGRADED ou UNKNOWN produz
    status=UNKNOWN com confidence=0.0.
    """
    response = make_valid_response(
        status=invalid_status,
        diagnosis=diagnosis,
        issues=issues,
        description=description,
        confidence=confidence,
    )

    result = _client._parse_response(response)

    assert result.status == DiagnosisStatus.UNKNOWN
    assert result.confidence == 0.0


# ---------------------------------------------------------------------------
# Propriedade 4: Confidence fora de [0, 1] → UNKNOWN com confidence=0.0
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    status=valid_status_st,
    diagnosis=valid_diagnosis_st,
    issues=valid_issues_st,
    description=valid_description_st,
    confidence=st.one_of(
        st.floats(max_value=-0.001, allow_nan=False, allow_infinity=False),
        st.floats(min_value=1.001, allow_nan=False, allow_infinity=False),
    ),
)
def test_confidence_outside_range_returns_unknown(
    status,
    diagnosis,
    issues,
    description,
    confidence,
):
    """
    **Validates: Requirements 8.2, 8.4**

    Confidence fora do range [0.0, 1.0] produz
    status=UNKNOWN com confidence=0.0.
    """
    response = make_valid_response(
        status=status,
        diagnosis=diagnosis,
        issues=issues,
        description=description,
        confidence=confidence,
    )

    result = _client._parse_response(response)

    assert result.status == DiagnosisStatus.UNKNOWN
    assert result.confidence == 0.0


# ---------------------------------------------------------------------------
# Propriedade 5: Diagnosis não-string → UNKNOWN
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    status=valid_status_st,
    non_string_diagnosis=st.one_of(
        st.integers(),
        st.lists(st.text(), max_size=3),
        st.dictionaries(st.text(max_size=5), st.integers(), max_size=3),
        st.none(),
        st.booleans(),
    ),
    issues=valid_issues_st,
    description=valid_description_st,
    confidence=valid_confidence_st,
)
def test_non_string_diagnosis_returns_unknown(
    status,
    non_string_diagnosis,
    issues,
    description,
    confidence,
):
    """
    **Validates: Requirements 8.2, 8.4**

    Campo diagnosis com tipo diferente de string produz
    status=UNKNOWN com confidence=0.0.
    """
    response = {
        "status": status,
        "diagnosis": non_string_diagnosis,
        "issues": issues,
        "description": description,
        "confidence": confidence,
    }

    result = _client._parse_response(response)

    assert result.status == DiagnosisStatus.UNKNOWN
    assert result.confidence == 0.0


# ---------------------------------------------------------------------------
# Propriedade 6: Issues não-lista → UNKNOWN
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    status=valid_status_st,
    diagnosis=valid_diagnosis_st,
    non_list_issues=st.one_of(
        st.text(min_size=1, max_size=50),
        st.integers(),
        st.dictionaries(st.text(max_size=5), st.integers(), max_size=3),
        st.none(),
        st.booleans(),
    ),
    description=valid_description_st,
    confidence=valid_confidence_st,
)
def test_non_list_issues_returns_unknown(
    status,
    diagnosis,
    non_list_issues,
    description,
    confidence,
):
    """
    **Validates: Requirements 8.2, 8.4**

    Campo issues com tipo diferente de lista produz
    status=UNKNOWN com confidence=0.0.
    """
    response = {
        "status": status,
        "diagnosis": diagnosis,
        "issues": non_list_issues,
        "description": description,
        "confidence": confidence,
    }

    result = _client._parse_response(response)

    assert result.status == DiagnosisStatus.UNKNOWN
    assert result.confidence == 0.0
