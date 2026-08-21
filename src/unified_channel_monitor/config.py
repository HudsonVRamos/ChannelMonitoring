"""Configuração unificada do Unified Channel Monitor.

Carrega parâmetros via variáveis de ambiente com prefixo UNIFIED_MONITOR_.
Valores inválidos (non-numeric onde esperado número) são ignorados com warning
e o default é mantido.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class UnifiedMonitorConfig:
    """Configuração unificada — combina parâmetros de ambos os módulos.

    Todos os parâmetros possuem defaults sensíveis derivados dos módulos
    Player Discovery e Audio/Subtitle Monitor existentes.

    Override via variáveis de ambiente com prefixo UNIFIED_MONITOR_
    (ex: UNIFIED_MONITOR_TELEMETRY_INTERVAL_S=5.0).
    """

    # Canais
    channels: list[str] = field(default_factory=list)

    # Video Telemetry
    telemetry_interval_s: float = 2.0
    observation_period_s: float = 30.0
    freeze_consecutive_samples: int = 3

    # Audio Testing
    audio_telemetry_window_s: float = 30.0
    audio_sample_interval_s: float = 2.0
    audio_pass_threshold: float = 0.80
    audio_rms_threshold: float = 0.01

    # Subtitle Testing
    subtitle_cue_timeout_s: float = 15.0
    subtitle_poll_interval_s: float = 0.5

    # Track Switch
    track_switch_timeout_s: float = 5.0

    # Discovery
    invalidation_threshold: int = 3

    # Output
    output_dir: str = "reports/"
    log_level: str = "INFO"

    # Browser
    chrome_profile_dir: str = ""
    playback_wait_timeout_s: float = 30.0

    # Continuous mode
    continuous: bool = False

    @classmethod
    def from_env(cls) -> UnifiedMonitorConfig:
        """Cria UnifiedMonitorConfig a partir de variáveis de ambiente.

        Convenção: UNIFIED_MONITOR_ + nome do campo em UPPERCASE.
        Exemplo: UNIFIED_MONITOR_TELEMETRY_INTERVAL_S=5.0

        Casos especiais:
        - UNIFIED_MONITOR_CHANNELS: lista de URLs separada por vírgula,
          com trim de whitespace e remoção de entradas vazias.
        - CHROME_PROFILE_DIR: lido sem prefixo (compatibilidade com Req 1.5).
        - UNIFIED_MONITOR_CONTINUOUS: aceita "true"/"1"/"yes" (case-insensitive).

        Para campos numéricos, valores non-numeric são ignorados com warning
        e o default é mantido.
        """
        env_prefix = "UNIFIED_MONITOR_"
        kwargs: dict = {}

        # --- Parsing de CHANNELS (comma-separated URLs) ---
        channels_raw = os.environ.get(f"{env_prefix}CHANNELS", "")
        if channels_raw:
            parsed_channels = [
                url.strip()
                for url in channels_raw.split(",")
                if url.strip()
            ]
            kwargs["channels"] = parsed_channels

        # --- Campos numéricos float ---
        float_fields = [
            "telemetry_interval_s",
            "observation_period_s",
            "audio_telemetry_window_s",
            "audio_sample_interval_s",
            "audio_pass_threshold",
            "audio_rms_threshold",
            "subtitle_cue_timeout_s",
            "subtitle_poll_interval_s",
            "track_switch_timeout_s",
            "playback_wait_timeout_s",
        ]

        for field_name in float_fields:
            env_var = f"{env_prefix}{field_name.upper()}"
            value = os.environ.get(env_var)
            if value is not None:
                try:
                    kwargs[field_name] = float(value)
                except (ValueError, TypeError):
                    logger.warning(
                        "Valor inválido para %s='%s' (esperado float). "
                        "Usando default.",
                        env_var,
                        value,
                    )

        # --- Campos numéricos int ---
        int_fields = [
            "freeze_consecutive_samples",
            "invalidation_threshold",
        ]

        for field_name in int_fields:
            env_var = f"{env_prefix}{field_name.upper()}"
            value = os.environ.get(env_var)
            if value is not None:
                try:
                    kwargs[field_name] = int(value)
                except (ValueError, TypeError):
                    logger.warning(
                        "Valor inválido para %s='%s' (esperado int). "
                        "Usando default.",
                        env_var,
                        value,
                    )

        # --- Campos string ---
        output_dir_env = os.environ.get(f"{env_prefix}OUTPUT_DIR")
        if output_dir_env is not None:
            kwargs["output_dir"] = output_dir_env

        log_level_env = os.environ.get(f"{env_prefix}LOG_LEVEL")
        if log_level_env is not None:
            kwargs["log_level"] = log_level_env

        # CHROME_PROFILE_DIR — lido sem prefixo (Req 1.5)
        # Também aceita com prefixo como fallback
        chrome_profile = os.environ.get("CHROME_PROFILE_DIR", "")
        chrome_profile_prefixed = os.environ.get(
            f"{env_prefix}CHROME_PROFILE_DIR", ""
        )
        kwargs["chrome_profile_dir"] = chrome_profile or chrome_profile_prefixed

        # --- Campo booleano: continuous ---
        continuous_env = os.environ.get(f"{env_prefix}CONTINUOUS", "")
        if continuous_env:
            kwargs["continuous"] = continuous_env.lower() in (
                "true", "1", "yes",
            )

        return cls(**kwargs)
