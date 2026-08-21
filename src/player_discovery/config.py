"""Configuração centralizada do módulo Player Discovery.

Define uma dataclass com todos os parâmetros configuráveis do sistema,
com valores padrão sensíveis e carregamento via variáveis de ambiente
com prefixo PLAYER_DISCOVERY_.

Requirements: 4.1, 8.4, 9.4, 10.4, 11.1
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class PlayerDiscoveryConfig:
    """Configuração centralizada do Player Discovery.

    Todos os parâmetros possuem valores padrão sensíveis derivados
    dos requisitos do sistema. Override via variáveis de ambiente
    com prefixo PLAYER_DISCOVERY_
    (ex: PLAYER_DISCOVERY_OBSERVATION_PERIOD_S=60).

    Attributes:
        discovery_timeout_s: Timeout máximo do discovery completo
            no startup (Req 1.1). Padrão: 60s.
        telemetry_interval_s: Intervalo de coleta de telemetria
            das probes (Req 5.1, 6.1, 8.1). Padrão: 2.0s.
        observation_period_s: Período de observação por canal
            durante a rotação (Req 10.2). Padrão: 30.0s.
        functional_test_interval: Número de rotações entre
            execuções de testes funcionais (Req 11.1). Padrão: 5.
        invalidation_threshold: Número de falhas consecutivas
            em canais para invalidar o Capability Map (Req 10.4).
            Padrão: 3.
        debounce_window_ms: Janela de debounce do MutationObserver
            para agrupar mutações (Req 4.1). Padrão: 500ms.
        event_retention_s: Janela de retenção de eventos em memória
            (Req 9.4). Padrão: 300s (5 minutos).
        buffer_low_threshold_s: Limite de buffer_ahead abaixo do qual
            o estado é classificado como BUFFER_LOW (Req 8.3).
            Padrão: 2.0s.
        escalation_frame_count: Número de frames adicionais capturados
            quando canal é SUSPECT (Req 14.2). Padrão: 3.
        escalation_frame_interval: Intervalo entre capturas de frames
            na escalação (Req 14.2). Padrão: 2.0s.
        navigation_timeout_ms: Timeout de navegação entre canais
            (Req 10.2). Padrão: 30000ms.
    """

    # Discovery (Req 1.1)
    discovery_timeout_s: int = 60

    # Telemetria (Req 5.1, 6.1, 8.1)
    telemetry_interval_s: float = 2.0

    # Observação por canal (Req 10.2)
    observation_period_s: float = 30.0

    # Testes funcionais (Req 11.1)
    functional_test_interval: int = 5

    # Invalidação do Capability Map (Req 10.4)
    invalidation_threshold: int = 3

    # MutationObserver debounce (Req 4.1)
    debounce_window_ms: int = 500

    # Retenção de eventos (Req 9.4)
    event_retention_s: int = 300

    # Buffer (Req 8.3)
    buffer_low_threshold_s: float = 2.0

    # Escalação (Req 14.2)
    escalation_frame_count: int = 3
    escalation_frame_interval: float = 2.0

    # Navegação (Req 10.2)
    navigation_timeout_ms: int = 30000

    # ------------------------------------------------------------------
    # Factory method: carrega overrides de variáveis de ambiente
    # ------------------------------------------------------------------

    @classmethod
    def from_env(cls) -> PlayerDiscoveryConfig:
        """Cria PlayerDiscoveryConfig com overrides de variáveis de ambiente.

        Convenção: PLAYER_DISCOVERY_ + nome do campo em UPPERCASE.
        Exemplo: PLAYER_DISCOVERY_OBSERVATION_PERIOD_S=60.

        Valores inválidos (não convertíveis para o tipo esperado) são
        silenciosamente ignorados e o default é mantido.

        Returns:
            Instância configurada com valores do ambiente ou defaults.
        """
        env_prefix = "PLAYER_DISCOVERY_"
        kwargs: dict = {}

        # Mapeamento de campos para tipos esperados
        field_types: dict[str, type] = {
            "discovery_timeout_s": int,
            "telemetry_interval_s": float,
            "observation_period_s": float,
            "functional_test_interval": int,
            "invalidation_threshold": int,
            "debounce_window_ms": int,
            "event_retention_s": int,
            "buffer_low_threshold_s": float,
            "escalation_frame_count": int,
            "escalation_frame_interval": float,
            "navigation_timeout_ms": int,
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

        return cls(**kwargs)

    # ------------------------------------------------------------------
    # Conversão para dict (compatibilidade com ChannelMonitor)
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Converte a configuração para dicionário.

        Útil para passar como argumento config={} ao ChannelMonitor
        e outros componentes que aceitam dict de configuração.

        Returns:
            Dicionário com todos os parâmetros de configuração.
        """
        return {
            "discovery_timeout_s": self.discovery_timeout_s,
            "telemetry_interval_s": self.telemetry_interval_s,
            "observation_period_s": self.observation_period_s,
            "functional_test_interval": self.functional_test_interval,
            "invalidation_threshold": self.invalidation_threshold,
            "debounce_window_ms": self.debounce_window_ms,
            "event_retention_s": self.event_retention_s,
            "buffer_low_threshold_s": self.buffer_low_threshold_s,
            "escalation_frame_count": self.escalation_frame_count,
            "escalation_frame_interval": self.escalation_frame_interval,
            "navigation_timeout_ms": self.navigation_timeout_ms,
        }
