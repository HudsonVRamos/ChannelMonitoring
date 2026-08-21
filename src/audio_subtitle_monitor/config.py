"""Configuração centralizada do módulo Audio & Subtitle Monitor.

Define uma dataclass com todos os parâmetros configuráveis do sistema,
com valores padrão sensíveis derivados dos requisitos. Override via
variáveis de ambiente com prefixo AUDIO_SUBTITLE_.

Requirements: 8.1, 9.1
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class AudioSubtitleConfig:
    """Configuração do módulo de monitoramento de áudio e legendas.

    Todos os parâmetros possuem valores padrão sensíveis derivados
    dos requisitos do sistema. Override via variáveis de ambiente
    com prefixo AUDIO_SUBTITLE_
    (ex: AUDIO_SUBTITLE_AUDIO_TELEMETRY_WINDOW_S=60).

    Attributes:
        channels: Lista de URLs dos canais a serem monitorados (Req 9.1).
        output_dir: Diretório para armazenar relatórios JSON (Req 7.3).
            Padrão: "reports/".
        audio_telemetry_window_s: Janela de coleta de telemetria de áudio
            em segundos (Req 3.3). Padrão: 30.0s.
        audio_sample_interval_s: Intervalo entre amostras de áudio durante
            a janela de telemetria (Req 3.3). Padrão: 2.0s.
        audio_pass_threshold: Fração mínima de amostras com áudio
            para classificar como PASS (Req 3.4). Padrão: 0.80 (80%).
        audio_rms_threshold: Limiar de RMS para considerar áudio
            presente (Req 3.4). Padrão: 0.01.
        subtitle_cue_timeout_s: Tempo máximo de espera por cue ativa
            de legenda (Req 5.3). Padrão: 15.0s.
        subtitle_poll_interval_s: Intervalo de polling para verificar
            cues ativas (Req 5.3). Padrão: 0.5s.
        track_switch_timeout_s: Timeout para confirmação de mudança
            de track via Shaka API (Req 3.2, 5.2). Padrão: 5.0s.
        playback_wait_timeout_s: Tempo máximo de espera para o player
            iniciar reprodução (Req 9.2). Padrão: 30.0s.
        settings_dialog_timeout_s: Timeout para aparição do Settings
            Dialog após clique (Req 1.2). Padrão: 5.0s.
        dialog_retry_wait_s: Tempo de espera antes de retry do dialog
            após falha (Req 6.4). Padrão: 2.0s.
    """

    # Canais monitorados (Req 9.1)
    channels: list[str] = field(default_factory=list)

    # Diretório de output (Req 7.3)
    output_dir: str = "reports/"

    # Telemetria de áudio (Req 3.3)
    audio_telemetry_window_s: float = 30.0
    audio_sample_interval_s: float = 2.0

    # Thresholds de áudio (Req 3.4, 3.5)
    audio_pass_threshold: float = 0.80
    audio_rms_threshold: float = 0.01

    # Legendas (Req 5.3)
    subtitle_cue_timeout_s: float = 15.0
    subtitle_poll_interval_s: float = 0.5

    # Track switch (Req 3.2, 5.2)
    track_switch_timeout_s: float = 5.0

    # Playback (Req 9.2)
    playback_wait_timeout_s: float = 30.0

    # Settings Dialog (Req 1.2, 6.4)
    settings_dialog_timeout_s: float = 5.0
    dialog_retry_wait_s: float = 2.0

    # ------------------------------------------------------------------
    # Factory method: carrega overrides de variáveis de ambiente
    # ------------------------------------------------------------------

    @classmethod
    def from_env(cls) -> AudioSubtitleConfig:
        """Cria AudioSubtitleConfig com overrides de variáveis de ambiente.

        Convenção: AUDIO_SUBTITLE_ + nome do campo em UPPERCASE.
        Exemplo: AUDIO_SUBTITLE_AUDIO_TELEMETRY_WINDOW_S=60.

        Para channels, usa AUDIO_SUBTITLE_CHANNELS com URLs separadas
        por vírgula.

        Valores inválidos (não convertíveis para o tipo esperado) são
        silenciosamente ignorados e o default é mantido.

        Returns:
            Instância configurada com valores do ambiente ou defaults.
        """
        env_prefix = "AUDIO_SUBTITLE_"
        kwargs: dict = {}

        # Mapeamento de campos para tipos esperados
        field_types: dict[str, type] = {
            "output_dir": str,
            "audio_telemetry_window_s": float,
            "audio_sample_interval_s": float,
            "audio_pass_threshold": float,
            "audio_rms_threshold": float,
            "subtitle_cue_timeout_s": float,
            "subtitle_poll_interval_s": float,
            "track_switch_timeout_s": float,
            "playback_wait_timeout_s": float,
            "settings_dialog_timeout_s": float,
            "dialog_retry_wait_s": float,
        }

        for field_name, field_type in field_types.items():
            env_var = f"{env_prefix}{field_name.upper()}"
            value = os.environ.get(env_var)
            if value is not None:
                try:
                    kwargs[field_name] = field_type(value)
                except (ValueError, TypeError):
                    pass

        # Channels: lista separada por vírgula
        channels_env = os.environ.get(f"{env_prefix}CHANNELS")
        if channels_env:
            kwargs["channels"] = [
                ch.strip() for ch in channels_env.split(",") if ch.strip()
            ]

        return cls(**kwargs)

    # ------------------------------------------------------------------
    # Conversão para dict
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Converte a configuração para dicionário.

        Returns:
            Dicionário com todos os parâmetros de configuração.
        """
        return {
            "channels": self.channels,
            "output_dir": self.output_dir,
            "audio_telemetry_window_s": self.audio_telemetry_window_s,
            "audio_sample_interval_s": self.audio_sample_interval_s,
            "audio_pass_threshold": self.audio_pass_threshold,
            "audio_rms_threshold": self.audio_rms_threshold,
            "subtitle_cue_timeout_s": self.subtitle_cue_timeout_s,
            "subtitle_poll_interval_s": self.subtitle_poll_interval_s,
            "track_switch_timeout_s": self.track_switch_timeout_s,
            "playback_wait_timeout_s": self.playback_wait_timeout_s,
            "settings_dialog_timeout_s": self.settings_dialog_timeout_s,
            "dialog_retry_wait_s": self.dialog_retry_wait_s,
        }
