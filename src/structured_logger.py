"""Logger estruturado em formato JSON para stdout.

Produz logs estruturados com timestamp ISO 8601, level, stage_id,
message e data, direcionados para stdout em formato JSON.
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from datetime import datetime, timezone
from typing import Optional

from src.models import LogEntry


# Ordem dos níveis de log (menor valor = menor prioridade)
_LOG_LEVELS: dict[str, int] = {
    "DEBUG": 10,
    "INFO": 20,
    "WARNING": 30,
    "ERROR": 40,
}


class StructuredLogger:
    """Logger estruturado em formato JSON para stdout."""

    def __init__(self, min_level: str = "INFO") -> None:
        """Inicializa o logger com nível mínimo configurável.

        O nível mínimo pode ser definido via:
        1. Parâmetro min_level (prioridade)
        2. Variável de ambiente LOG_LEVEL (fallback se min_level não for fornecido explicitamente)

        Args:
            min_level: Nível mínimo de log. Valores aceitos: DEBUG, INFO, WARNING, ERROR.
        """
        # Variável de ambiente tem prioridade sobre o default, mas não sobre argumento explícito
        env_level = os.environ.get("LOG_LEVEL", "").upper()
        if env_level and env_level in _LOG_LEVELS:
            self._min_level = env_level
        else:
            self._min_level = min_level.upper()

        # Validar nível configurado
        if self._min_level not in _LOG_LEVELS:
            self._min_level = "INFO"

    @property
    def min_level(self) -> str:
        """Retorna o nível mínimo de log configurado."""
        return self._min_level

    def _should_log(self, level: str) -> bool:
        """Verifica se o nível fornecido deve ser logado baseado no nível mínimo."""
        level_value = _LOG_LEVELS.get(level.upper(), 0)
        min_value = _LOG_LEVELS.get(self._min_level, 0)
        return level_value >= min_value

    def _get_timestamp(self) -> str:
        """Gera timestamp ISO 8601 com milissegundos em UTC."""
        now = datetime.now(timezone.utc)
        # Formato: 2024-01-15T10:30:45.123Z
        return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"

    def log(
        self,
        level: str,
        stage_id: str,
        message: str,
        data: Optional[dict] = None,
    ) -> None:
        """Registra log estruturado com timestamp ISO 8601.

        Args:
            level: Nível do log (DEBUG, INFO, WARNING, ERROR).
            stage_id: Identificador da etapa/estágio.
            message: Mensagem descritiva do evento.
            data: Dados adicionais opcionais.
        """
        level_upper = level.upper()

        if not self._should_log(level_upper):
            return

        timestamp = self._get_timestamp()

        # Criar entrada de log usando o modelo LogEntry
        entry = LogEntry(
            timestamp=timestamp,
            level=level_upper,
            stage_id=stage_id,
            message=message,
            data=data,
        )

        # Montar dicionário de saída
        output: dict = {
            "timestamp": entry.timestamp,
            "level": entry.level,
            "stage_id": entry.stage_id,
            "message": entry.message,
        }

        if entry.data is not None:
            output["data"] = entry.data

        # Incluir stack_trace em logs de nível ERROR
        if level_upper == "ERROR":
            stack = traceback.format_exc()
            # Apenas incluir se houver exceção ativa (não "NoneType: None")
            if stack and stack.strip() != "NoneType: None":
                output["stack_trace"] = stack.strip()

        # Serializar e enviar para stdout
        json_line = json.dumps(output, ensure_ascii=False, default=str)
        sys.stdout.write(json_line + "\n")
        sys.stdout.flush()

    def debug(self, stage_id: str, message: str, **kwargs) -> None:
        """Registra log nível DEBUG.

        Args:
            stage_id: Identificador da etapa/estágio.
            message: Mensagem descritiva do evento.
            **kwargs: Dados adicionais que serão incluídos no campo 'data'.
        """
        data = kwargs if kwargs else None
        self.log("DEBUG", stage_id, message, data)

    def info(self, stage_id: str, message: str, **kwargs) -> None:
        """Registra log nível INFO.

        Args:
            stage_id: Identificador da etapa/estágio.
            message: Mensagem descritiva do evento.
            **kwargs: Dados adicionais que serão incluídos no campo 'data'.
        """
        data = kwargs if kwargs else None
        self.log("INFO", stage_id, message, data)

    def warning(self, stage_id: str, message: str, **kwargs) -> None:
        """Registra log nível WARNING.

        Args:
            stage_id: Identificador da etapa/estágio.
            message: Mensagem descritiva do evento.
            **kwargs: Dados adicionais que serão incluídos no campo 'data'.
        """
        data = kwargs if kwargs else None
        self.log("WARNING", stage_id, message, data)

    def error(self, stage_id: str, message: str, **kwargs) -> None:
        """Registra log nível ERROR.

        Args:
            stage_id: Identificador da etapa/estágio.
            message: Mensagem descritiva do evento.
            **kwargs: Dados adicionais que serão incluídos no campo 'data'.
        """
        data = kwargs if kwargs else None
        self.log("ERROR", stage_id, message, data)
