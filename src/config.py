"""Configuração principal da PoC Widevine."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class PoCConfig:
    """Configuração principal da PoC.

    Todos os parâmetros possuem valores padrão sensíveis.
    Override via variáveis de ambiente com prefixo POC_ (ex: POC_LOG_LEVEL).
    """

    # Obrigatórios (sem default útil — devem ser fornecidos)
    storage_state_path: str = ""
    channel_url: str = ""

    # Diretório de saída e nível de log
    output_dir: str = "./output"
    log_level: str = "INFO"

    # Timeouts (segundos)
    session_restore_timeout: int = 15
    drm_timeout: int = 15
    playback_timeout: int = 30
    bedrock_timeout: int = 30
    docker_startup_timeout: int = 60

    # Telemetria
    telemetry_interval: float = 2.0  # segundos
    telemetry_duration: float = 30.0  # segundos

    # Frames
    frame_interval: float = 5.0  # segundos
    frame_min_resolution: tuple[int, int] = (1280, 720)
    frame_max_size: int = 5 * 1024 * 1024  # 5 MB

    # OpenCV — Tela preta
    black_screen_luminance_threshold: float = 10.0
    black_pixel_value_threshold: int = 20
    black_pixel_percent_threshold: float = 95.0
    variance_threshold: float = 50.0

    # OpenCV — Freeze
    freeze_similarity_threshold: float = 0.98
    freeze_observation_window: float = 5.0  # segundos

    # Buffering
    buffering_threshold: float = 10.0  # segundos

    # Bedrock
    bedrock_region: str = "us-east-1"
    bedrock_confidence_threshold: float = 0.7

    # ------------------------------------------------------------------
    # Factory method: carrega overrides de variáveis de ambiente
    # ------------------------------------------------------------------

    @classmethod
    def from_env(cls) -> PoCConfig:
        """Cria PoCConfig com overrides de variáveis de ambiente.

        Convenção: POC_ + nome do campo em UPPERCASE.
        Exemplo: POC_LOG_LEVEL, POC_DRM_TIMEOUT, POC_STORAGE_STATE_PATH.

        Para frame_min_resolution usa formato "WIDTHxHEIGHT" (ex: "1920x1080").
        """
        env_prefix = "POC_"
        kwargs: dict = {}

        # Mapeamento de campos para tipos esperados
        field_types: dict[str, type] = {
            "storage_state_path": str,
            "channel_url": str,
            "output_dir": str,
            "log_level": str,
            "session_restore_timeout": int,
            "drm_timeout": int,
            "playback_timeout": int,
            "bedrock_timeout": int,
            "docker_startup_timeout": int,
            "telemetry_interval": float,
            "telemetry_duration": float,
            "frame_interval": float,
            "frame_max_size": int,
            "black_screen_luminance_threshold": float,
            "black_pixel_value_threshold": int,
            "black_pixel_percent_threshold": float,
            "variance_threshold": float,
            "freeze_similarity_threshold": float,
            "freeze_observation_window": float,
            "buffering_threshold": float,
            "bedrock_region": str,
            "bedrock_confidence_threshold": float,
        }

        for field_name, field_type in field_types.items():
            env_var = f"{env_prefix}{field_name.upper()}"
            value = os.environ.get(env_var)
            if value is not None:
                try:
                    kwargs[field_name] = field_type(value)
                except (ValueError, TypeError):
                    # Ignora valores inválidos, mantém o default
                    pass

        # Caso especial: frame_min_resolution (tuple)
        resolution_env = os.environ.get(f"{env_prefix}FRAME_MIN_RESOLUTION")
        if resolution_env:
            try:
                parts = resolution_env.lower().split("x")
                if len(parts) == 2:
                    kwargs["frame_min_resolution"] = (
                        int(parts[0]), int(parts[1])
                    )
            except (ValueError, TypeError):
                pass

        return cls(**kwargs)

    # ------------------------------------------------------------------
    # Validação
    # ------------------------------------------------------------------

    def validate(self) -> list[str]:
        """Valida a configuração e retorna lista de erros encontrados.

        Returns:
            Lista vazia se válido, ou lista de mensagens de erro.
        """
        errors: list[str] = []

        # Campos obrigatórios
        if not self.storage_state_path:
            errors.append("storage_state_path não pode ser vazio")
        if not self.channel_url:
            errors.append("channel_url não pode ser vazio")

        # Intervalo de captura: entre 1 e 60 segundos (Req 4.3)
        if not (1.0 <= self.frame_interval <= 60.0):
            errors.append(
                f"frame_interval deve estar entre 1 e 60 segundos, "
                f"valor atual: {self.frame_interval}"
            )

        # Thresholds de luminância e pixels (ranges válidos)
        if not (0.0 <= self.black_screen_luminance_threshold <= 255.0):
            errors.append(
                f"black_screen_luminance_threshold deve estar entre 0 e 255, "
                f"valor atual: {self.black_screen_luminance_threshold}"
            )
        if not (0 <= self.black_pixel_value_threshold <= 255):
            errors.append(
                f"black_pixel_value_threshold deve estar entre 0 e 255, "
                f"valor atual: {self.black_pixel_value_threshold}"
            )
        if not (0.0 <= self.black_pixel_percent_threshold <= 100.0):
            errors.append(
                f"black_pixel_percent_threshold deve estar entre 0 e 100, "
                f"valor atual: {self.black_pixel_percent_threshold}"
            )
        if not (0.0 <= self.variance_threshold):
            errors.append(
                f"variance_threshold deve ser >= 0, "
                f"valor atual: {self.variance_threshold}"
            )

        # Similaridade de freeze: entre 0 e 1
        if not (0.0 <= self.freeze_similarity_threshold <= 1.0):
            errors.append(
                f"freeze_similarity_threshold deve estar entre 0.0 e 1.0, "
                f"valor atual: {self.freeze_similarity_threshold}"
            )

        # Confidence do Bedrock: entre 0 e 1
        if not (0.0 <= self.bedrock_confidence_threshold <= 1.0):
            errors.append(
                f"bedrock_confidence_threshold deve estar entre 0.0 e 1.0, "
                f"valor atual: {self.bedrock_confidence_threshold}"
            )

        # Timeouts devem ser positivos
        if self.session_restore_timeout <= 0:
            errors.append("session_restore_timeout deve ser > 0")
        if self.drm_timeout <= 0:
            errors.append("drm_timeout deve ser > 0")
        if self.playback_timeout <= 0:
            errors.append("playback_timeout deve ser > 0")
        if self.bedrock_timeout <= 0:
            errors.append("bedrock_timeout deve ser > 0")
        if self.docker_startup_timeout <= 0:
            errors.append("docker_startup_timeout deve ser > 0")

        # Intervalos de telemetria devem ser positivos
        if self.telemetry_interval <= 0:
            errors.append("telemetry_interval deve ser > 0")
        if self.telemetry_duration <= 0:
            errors.append("telemetry_duration deve ser > 0")

        # Buffering threshold positivo
        if self.buffering_threshold <= 0:
            errors.append("buffering_threshold deve ser > 0")

        # Freeze observation window positivo
        if self.freeze_observation_window <= 0:
            errors.append("freeze_observation_window deve ser > 0")

        # Frame size deve ser positivo
        if self.frame_max_size <= 0:
            errors.append("frame_max_size deve ser > 0")

        # Resolução mínima deve ser positiva
        w, h = self.frame_min_resolution
        if w <= 0 or h <= 0:
            errors.append("frame_min_resolution deve ter valores positivos")

        return errors
