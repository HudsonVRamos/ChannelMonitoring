"""Testes unitários para o StructuredLogger."""

import json
import os
from unittest.mock import patch

import pytest

from src.structured_logger import StructuredLogger, _LOG_LEVELS


class TestStructuredLoggerInit:
    """Testes de inicialização do logger."""

    def test_default_level_is_info(self):
        """Logger padrão deve ter nível INFO."""
        # Limpar variável de ambiente caso exista
        with patch.dict(os.environ, {}, clear=True):
            logger = StructuredLogger()
            assert logger.min_level == "INFO"

    def test_custom_min_level(self):
        """Logger deve aceitar nível mínimo customizado."""
        with patch.dict(os.environ, {}, clear=True):
            logger = StructuredLogger(min_level="DEBUG")
            assert logger.min_level == "DEBUG"

    def test_env_variable_overrides_default(self):
        """Variável de ambiente LOG_LEVEL deve ter prioridade."""
        with patch.dict(os.environ, {"LOG_LEVEL": "ERROR"}):
            logger = StructuredLogger()
            assert logger.min_level == "ERROR"

    def test_invalid_level_falls_back_to_info(self):
        """Nível inválido deve fazer fallback para INFO."""
        with patch.dict(os.environ, {}, clear=True):
            logger = StructuredLogger(min_level="INVALID")
            assert logger.min_level == "INFO"

    def test_case_insensitive_level(self):
        """Nível deve ser case-insensitive."""
        with patch.dict(os.environ, {}, clear=True):
            logger = StructuredLogger(min_level="debug")
            assert logger.min_level == "DEBUG"


class TestStructuredLoggerOutput:
    """Testes de saída do logger."""

    def test_log_produces_valid_json(self, capsys):
        """Log deve produzir JSON válido em stdout."""
        with patch.dict(os.environ, {}, clear=True):
            logger = StructuredLogger(min_level="DEBUG")
            logger.info("test_stage", "mensagem de teste")

            captured = capsys.readouterr()
            output = json.loads(captured.out.strip())

            assert output["level"] == "INFO"
            assert output["stage_id"] == "test_stage"
            assert output["message"] == "mensagem de teste"
            assert "timestamp" in output

    def test_log_contains_required_fields(self, capsys):
        """Cada entrada deve conter: timestamp, level, stage_id, message."""
        with patch.dict(os.environ, {}, clear=True):
            logger = StructuredLogger(min_level="DEBUG")
            logger.log("INFO", "drm_init", "DRM inicializado")

            captured = capsys.readouterr()
            output = json.loads(captured.out.strip())

            required_fields = ["timestamp", "level", "stage_id", "message"]
            for field in required_fields:
                assert field in output, f"Campo '{field}' ausente na saída"

    def test_log_includes_data_when_provided(self, capsys):
        """Campo data deve ser incluído quando fornecido."""
        with patch.dict(os.environ, {}, clear=True):
            logger = StructuredLogger(min_level="DEBUG")
            logger.log("INFO", "stage", "msg", data={"key": "value"})

            captured = capsys.readouterr()
            output = json.loads(captured.out.strip())

            assert output["data"] == {"key": "value"}

    def test_log_excludes_data_when_none(self, capsys):
        """Campo data não deve aparecer quando é None."""
        with patch.dict(os.environ, {}, clear=True):
            logger = StructuredLogger(min_level="DEBUG")
            logger.log("INFO", "stage", "msg", data=None)

            captured = capsys.readouterr()
            output = json.loads(captured.out.strip())

            assert "data" not in output

    def test_timestamp_is_iso8601_with_milliseconds(self, capsys):
        """Timestamp deve estar em formato ISO 8601 com milissegundos."""
        with patch.dict(os.environ, {}, clear=True):
            logger = StructuredLogger(min_level="DEBUG")
            logger.info("stage", "msg")

            captured = capsys.readouterr()
            output = json.loads(captured.out.strip())
            ts = output["timestamp"]

            # Formato esperado: 2024-01-15T10:30:45.123Z
            assert ts.endswith("Z")
            assert "T" in ts
            # Verificar milissegundos (3 dígitos antes do Z)
            parts = ts.split(".")
            assert len(parts) == 2
            assert len(parts[1]) == 4  # "123Z"


class TestStructuredLoggerLevelFiltering:
    """Testes de filtragem por nível."""

    def test_debug_filtered_when_min_is_info(self, capsys):
        """DEBUG deve ser filtrado quando nível mínimo é INFO."""
        with patch.dict(os.environ, {}, clear=True):
            logger = StructuredLogger(min_level="INFO")
            logger.debug("stage", "debug msg")

            captured = capsys.readouterr()
            assert captured.out == ""

    def test_info_passes_when_min_is_info(self, capsys):
        """INFO deve passar quando nível mínimo é INFO."""
        with patch.dict(os.environ, {}, clear=True):
            logger = StructuredLogger(min_level="INFO")
            logger.info("stage", "info msg")

            captured = capsys.readouterr()
            assert captured.out != ""

    def test_warning_passes_when_min_is_info(self, capsys):
        """WARNING deve passar quando nível mínimo é INFO."""
        with patch.dict(os.environ, {}, clear=True):
            logger = StructuredLogger(min_level="INFO")
            logger.warning("stage", "warn msg")

            captured = capsys.readouterr()
            assert captured.out != ""

    def test_error_passes_when_min_is_error(self, capsys):
        """ERROR deve passar quando nível mínimo é ERROR."""
        with patch.dict(os.environ, {}, clear=True):
            logger = StructuredLogger(min_level="ERROR")
            logger.error("stage", "error msg")

            captured = capsys.readouterr()
            assert captured.out != ""

    def test_info_filtered_when_min_is_warning(self, capsys):
        """INFO deve ser filtrado quando nível mínimo é WARNING."""
        with patch.dict(os.environ, {}, clear=True):
            logger = StructuredLogger(min_level="WARNING")
            logger.info("stage", "info msg")

            captured = capsys.readouterr()
            assert captured.out == ""

    def test_all_levels_pass_when_min_is_debug(self, capsys):
        """Todos os níveis devem passar quando nível mínimo é DEBUG."""
        with patch.dict(os.environ, {}, clear=True):
            logger = StructuredLogger(min_level="DEBUG")
            logger.debug("s", "d")
            logger.info("s", "i")
            logger.warning("s", "w")
            logger.error("s", "e")

            captured = capsys.readouterr()
            lines = [l for l in captured.out.strip().split("\n") if l]
            assert len(lines) == 4


class TestStructuredLoggerErrorStackTrace:
    """Testes de stack_trace em logs ERROR."""

    def test_error_includes_stack_trace_with_active_exception(self, capsys):
        """ERROR com exceção ativa deve incluir stack_trace."""
        with patch.dict(os.environ, {}, clear=True):
            logger = StructuredLogger(min_level="DEBUG")
            try:
                raise ValueError("erro de teste")
            except ValueError:
                logger.error("stage", "falha detectada")

            captured = capsys.readouterr()
            output = json.loads(captured.out.strip())

            assert "stack_trace" in output
            assert "ValueError" in output["stack_trace"]
            assert "erro de teste" in output["stack_trace"]

    def test_error_without_active_exception_no_stack_trace(self, capsys):
        """ERROR sem exceção ativa não deve incluir stack_trace irrelevante."""
        with patch.dict(os.environ, {}, clear=True):
            logger = StructuredLogger(min_level="DEBUG")
            logger.error("stage", "erro genérico")

            captured = capsys.readouterr()
            output = json.loads(captured.out.strip())

            # Não deve incluir "NoneType: None" como stack trace
            assert "stack_trace" not in output or "NoneType" not in output.get(
                "stack_trace", ""
            )


class TestStructuredLoggerConvenienceMethods:
    """Testes dos métodos de conveniência (debug, info, warning, error)."""

    def test_kwargs_passed_as_data(self, capsys):
        """kwargs devem ser passados no campo data."""
        with patch.dict(os.environ, {}, clear=True):
            logger = StructuredLogger(min_level="DEBUG")
            logger.info("drm", "licença obtida", time_ms=150, model="haiku")

            captured = capsys.readouterr()
            output = json.loads(captured.out.strip())

            assert output["data"] == {"time_ms": 150, "model": "haiku"}

    def test_no_kwargs_means_no_data_field(self, capsys):
        """Sem kwargs, campo data não deve aparecer."""
        with patch.dict(os.environ, {}, clear=True):
            logger = StructuredLogger(min_level="DEBUG")
            logger.info("stage", "mensagem simples")

            captured = capsys.readouterr()
            output = json.loads(captured.out.strip())

            assert "data" not in output

    def test_debug_method_sets_correct_level(self, capsys):
        """Método debug deve setar level=DEBUG."""
        with patch.dict(os.environ, {}, clear=True):
            logger = StructuredLogger(min_level="DEBUG")
            logger.debug("s", "m")

            captured = capsys.readouterr()
            output = json.loads(captured.out.strip())
            assert output["level"] == "DEBUG"

    def test_warning_method_sets_correct_level(self, capsys):
        """Método warning deve setar level=WARNING."""
        with patch.dict(os.environ, {}, clear=True):
            logger = StructuredLogger(min_level="DEBUG")
            logger.warning("s", "m")

            captured = capsys.readouterr()
            output = json.loads(captured.out.strip())
            assert output["level"] == "WARNING"
