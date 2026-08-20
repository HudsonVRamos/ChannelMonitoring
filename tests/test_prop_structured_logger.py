# Feature: widevine-poc, Property 14: Formato de log estruturado
"""Testes de propriedade para o StructuredLogger.

Validates: Requirements 10.1, 10.9, 10.10

Property 14: Para qualquer invocação de log com qualquer combinação de
level, stage_id, message e data, a saída SHALL ser JSON válido contendo
os campos timestamp (ISO 8601 com milissegundos), level, stage_id, message,
e data (quando fornecido). Erros SHALL incluir adicionalmente stack_trace.
"""
from __future__ import annotations

import json
import os
import re
import sys
from io import StringIO
from unittest.mock import patch

from hypothesis import given, settings
from hypothesis import strategies as st

from src.structured_logger import StructuredLogger


# =============================================================================
# Estratégias de geração de dados
# =============================================================================

levels_st = st.sampled_from(["DEBUG", "INFO", "WARNING", "ERROR"])

stage_id_st = st.text(min_size=1, max_size=50)

message_st = st.text(min_size=1, max_size=50)

data_st = st.none() | st.dictionaries(
    st.text(min_size=1, max_size=10),
    st.integers() | st.text(max_size=20),
)

# Regex ISO 8601 com milissegundos: YYYY-MM-DDTHH:MM:SS.mmmZ
ISO8601_MS_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"
)


# =============================================================================
# Propriedade 1: Saída é sempre JSON válido
# =============================================================================


class TestProperty14JSONValido:
    """Para qualquer combinação válida de inputs, a saída deve ser JSON válido."""

    @settings(max_examples=100)
    @given(
        level=levels_st,
        stage_id=stage_id_st,
        message=message_st,
        data=data_st,
    )
    def test_output_is_valid_json(self, level, stage_id, message, data):
        """**Validates: Requirements 10.1**

        Para qualquer combinação de level, stage_id, message e data,
        a saída DEVE ser JSON válido parseável.
        """
        with patch.dict(os.environ, {}, clear=True):
            logger = StructuredLogger(min_level="DEBUG")

        captured = StringIO()
        with patch.object(sys, "stdout", captured):
            logger.log(level, stage_id, message, data=data)

        output_str = captured.getvalue().strip()
        assert output_str != "", "Logger não produziu saída"

        # Deve ser JSON válido sem exceção
        parsed = json.loads(output_str)
        assert isinstance(parsed, dict)


# =============================================================================
# Propriedade 2: Campos obrigatórios presentes
# =============================================================================


class TestProperty14CamposObrigatorios:
    """Saída deve conter timestamp, level, stage_id, message."""

    @settings(max_examples=100)
    @given(
        level=levels_st,
        stage_id=stage_id_st,
        message=message_st,
        data=data_st,
    )
    def test_output_contains_required_fields(
        self, level, stage_id, message, data
    ):
        """**Validates: Requirements 10.1, 10.10**

        Cada entrada de log DEVE conter os campos: timestamp (ISO 8601
        com milissegundos), level, stage_id, message.
        """
        with patch.dict(os.environ, {}, clear=True):
            logger = StructuredLogger(min_level="DEBUG")

        captured = StringIO()
        with patch.object(sys, "stdout", captured):
            logger.log(level, stage_id, message, data=data)

        output = json.loads(captured.getvalue().strip())

        # Campos obrigatórios presentes
        assert "timestamp" in output
        assert "level" in output
        assert "stage_id" in output
        assert "message" in output

        # Valores corretos
        assert output["level"] == level.upper()
        assert output["stage_id"] == stage_id
        assert output["message"] == message

        # Timestamp em formato ISO 8601 com milissegundos
        assert ISO8601_MS_PATTERN.match(output["timestamp"]), (
            f"Timestamp '{output['timestamp']}' não está no formato "
            f"ISO 8601 com milissegundos (YYYY-MM-DDTHH:MM:SS.mmmZ)"
        )


# =============================================================================
# Propriedade 3: Campo data presente quando fornecido
# =============================================================================


class TestProperty14DataPresente:
    """Quando data é fornecido e não None, deve estar presente na saída."""

    @settings(max_examples=100)
    @given(
        level=levels_st,
        stage_id=stage_id_st,
        message=message_st,
        data=st.dictionaries(
            st.text(min_size=1, max_size=10),
            st.integers() | st.text(max_size=20),
            min_size=1,
        ),
    )
    def test_data_present_when_provided(self, level, stage_id, message, data):
        """**Validates: Requirements 10.1**

        Quando data é fornecido (não None e não vazio), DEVE estar
        presente na saída JSON.
        """
        with patch.dict(os.environ, {}, clear=True):
            logger = StructuredLogger(min_level="DEBUG")

        captured = StringIO()
        with patch.object(sys, "stdout", captured):
            logger.log(level, stage_id, message, data=data)

        output = json.loads(captured.getvalue().strip())
        assert "data" in output
        assert output["data"] == data

    @settings(max_examples=100)
    @given(
        level=levels_st,
        stage_id=stage_id_st,
        message=message_st,
    )
    def test_data_absent_when_none(self, level, stage_id, message):
        """**Validates: Requirements 10.1**

        Quando data é None, o campo data NÃO DEVE estar presente na saída.
        """
        with patch.dict(os.environ, {}, clear=True):
            logger = StructuredLogger(min_level="DEBUG")

        captured = StringIO()
        with patch.object(sys, "stdout", captured):
            logger.log(level, stage_id, message, data=None)

        output = json.loads(captured.getvalue().strip())
        assert "data" not in output


# =============================================================================
# Propriedade 4: stack_trace em logs ERROR com exceção ativa
# =============================================================================


class TestProperty14StackTrace:
    """Logs ERROR com exceção ativa devem incluir stack_trace."""

    @settings(max_examples=100)
    @given(
        stage_id=stage_id_st,
        message=message_st,
        error_msg=st.text(min_size=1, max_size=30),
    )
    def test_error_with_exception_includes_stack_trace(
        self, stage_id, message, error_msg
    ):
        """**Validates: Requirements 10.9**

        Quando level é ERROR e há uma exceção ativa, stack_trace
        DEVE estar presente na saída.
        """
        with patch.dict(os.environ, {}, clear=True):
            logger = StructuredLogger(min_level="DEBUG")

        captured = StringIO()
        with patch.object(sys, "stdout", captured):
            try:
                raise RuntimeError(error_msg)
            except RuntimeError:
                logger.log("ERROR", stage_id, message)

        output = json.loads(captured.getvalue().strip())
        assert "stack_trace" in output
        assert "RuntimeError" in output["stack_trace"]


# =============================================================================
# Propriedade 5: Filtragem por nível mínimo
# =============================================================================


class TestProperty14FiltragemNivel:
    """Logs abaixo do nível mínimo não devem produzir saída."""

    @settings(max_examples=100)
    @given(
        stage_id=stage_id_st,
        message=message_st,
        data=data_st,
    )
    def test_logs_below_min_level_produce_no_output(
        self, stage_id, message, data
    ):
        """**Validates: Requirements 10.11**

        Logs com nível inferior ao min_level configurado NÃO DEVEM
        produzir saída alguma.
        """
        # Logger com nível mínimo ERROR: DEBUG, INFO, WARNING não devem sair
        with patch.dict(os.environ, {}, clear=True):
            logger = StructuredLogger(min_level="ERROR")

        levels_below = ["DEBUG", "INFO", "WARNING"]

        for level in levels_below:
            captured = StringIO()
            with patch.object(sys, "stdout", captured):
                logger.log(level, stage_id, message, data=data)

            assert captured.getvalue() == "", (
                f"Nível {level} não deveria produzir saída com "
                f"min_level=ERROR, mas produziu: {captured.getvalue()}"
            )

    @settings(max_examples=100)
    @given(
        level=levels_st,
        stage_id=stage_id_st,
        message=message_st,
        data=data_st,
    )
    def test_logs_at_or_above_min_level_produce_output(
        self, level, stage_id, message, data
    ):
        """**Validates: Requirements 10.11**

        Logs com nível igual ou superior ao min_level configurado
        DEVEM produzir saída.
        """
        # Logger com nível mínimo DEBUG: todos devem sair
        with patch.dict(os.environ, {}, clear=True):
            logger = StructuredLogger(min_level="DEBUG")

        captured = StringIO()
        with patch.object(sys, "stdout", captured):
            logger.log(level, stage_id, message, data=data)

        assert captured.getvalue() != "", (
            f"Nível {level} deveria produzir saída com min_level=DEBUG"
        )
