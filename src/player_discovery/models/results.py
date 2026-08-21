"""Data models de resultados do Player Discovery.

Define as estruturas de dados para resultados de interações,
testes funcionais, scores de saúde e relatórios de canal.
"""

from dataclasses import dataclass, field
from typing import Optional

from dataclasses_json import dataclass_json

from .enums import ChannelHealthStatus, FunctionalTestStatus, InteractionLevel
from .telemetry import (
    AudioTelemetry,
    BufferTelemetry,
    PlayerEvent,
    SubtitleTelemetry,
    VideoTelemetry,
)


@dataclass_json
@dataclass
class InteractionResult:
    """Resultado de uma interação com o player.

    Attributes:
        success: Se a interação foi bem-sucedida
        level_used: Nível de interação que funcionou
        duration_ms: Duração da interação em milissegundos
        error: Mensagem de erro se a interação falhou
    """

    success: bool
    level_used: InteractionLevel
    duration_ms: int
    error: Optional[str] = None


@dataclass_json
@dataclass
class FunctionalTestResult:
    """Resultado de um teste funcional.

    Attributes:
        capability: Nome da capability testada (ex: "play", "mute")
        status: Resultado do teste (PASS, FAIL, SKIPPED)
        action_executed: Descrição da ação executada
        expected_result: Resultado esperado
        actual_result: Resultado observado
        duration_ms: Duração do teste em milissegundos
        error: Mensagem de erro se o teste falhou
    """

    capability: str
    status: FunctionalTestStatus
    action_executed: str
    expected_result: str
    actual_result: str
    duration_ms: int
    error: Optional[str] = None


@dataclass_json
@dataclass
class HealthScores:
    """Scores de saúde compostos.

    Utilizados exclusivamente para tendência e priorização —
    estados objetivos (PASS/FAIL) têm precedência para alertas.

    Attributes:
        video_health: Score de saúde de vídeo (0-100)
        audio_health: Score de saúde de áudio (0-100)
        functional_health: Score de saúde funcional (0-100)
    """

    video_health: float = 0.0   # 0-100
    audio_health: float = 0.0   # 0-100
    functional_health: float = 0.0  # 0-100


@dataclass_json
@dataclass
class ChannelReport:
    """Relatório consolidado de um canal.

    Contém todos os dados coletados durante o período de observação
    de um canal específico.

    Attributes:
        channel_id: Identificador do canal
        channel_url: URL do canal
        status: Status de saúde classificado
        health_scores: Scores compostos de saúde
        video_telemetry: Telemetria de vídeo consolidada
        audio_telemetry: Telemetria de áudio consolidada
        subtitle_telemetry: Telemetria de legendas consolidada
        buffer_telemetry: Telemetria de buffer consolidada
        events: Lista de eventos registrados durante observação
        functional_tests: Resultados de testes funcionais (se executados)
        observation_duration_ms: Duração total da observação em milissegundos
        escalated_to_opencv: Se houve escalação para OpenCV
        escalated_to_bedrock: Se houve escalação para Bedrock
    """

    channel_id: str
    channel_url: str
    status: ChannelHealthStatus
    health_scores: HealthScores
    video_telemetry: VideoTelemetry
    audio_telemetry: AudioTelemetry
    subtitle_telemetry: SubtitleTelemetry
    buffer_telemetry: BufferTelemetry
    events: list[PlayerEvent] = field(default_factory=list)
    functional_tests: list[FunctionalTestResult] = field(default_factory=list)
    observation_duration_ms: int = 0
    escalated_to_opencv: bool = False
    escalated_to_bedrock: bool = False
