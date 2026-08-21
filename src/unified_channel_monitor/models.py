"""Data models para o Unified Channel Monitor.

Define as dataclasses e enums utilizados por todos os componentes do módulo:
- Telemetria de vídeo (TelemetrySample, TelemetrySummary, FreezeEvent)
- Escalação (DeferredEscalation, EscalationResult)
- Resultados de tracks (AudioTrackResult, SubtitleTrackResult)
- Relatórios (UnifiedChannelReport, ConsolidatedReport)
- Status de sessão (ChannelSessionStatus)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ChannelSessionStatus(str, Enum):
    """Status possíveis de uma Channel Session.

    Valores:
        PASS: todos os testes passaram com sucesso
        PARTIAL: alguns testes passaram, outros falharam
        FAIL: testes críticos falharam
        UNREACHABLE: canal não pôde ser acessado (timeout de navegação)
        ERROR: erro inesperado durante a sessão
    """

    PASS = "PASS"
    PARTIAL = "PARTIAL"
    FAIL = "FAIL"
    UNREACHABLE = "UNREACHABLE"
    ERROR = "ERROR"


@dataclass
class TelemetrySample:
    """Uma amostra individual de telemetria de vídeo.

    Coletada pelo VideoTelemetryCollector a cada intervalo configurado
    via page.evaluate() sem interação com DOM.
    """

    timestamp: str
    """Timestamp ISO 8601 da coleta."""

    current_time: float
    """Valor de video.currentTime no momento da amostra."""

    total_frames_decoded: int
    """Total de frames decodificados (totalVideoFrames)."""

    frames_dropped: int
    """Frames descartados (droppedVideoFrames)."""

    estimated_fps: float | None
    """FPS estimado entre amostras consecutivas. None na primeira amostra."""

    buffer_ahead_s: float
    """Segundos de buffer disponíveis à frente da posição atual."""

    ready_state: int
    """Valor de video.readyState (0-4)."""

    is_freeze: bool
    """Flag indicando se esta amostra faz parte de um evento de freeze."""

    annotation: dict | None = None
    """Contexto de track switch, se aplicável durante esta amostra."""


@dataclass
class FreezeEvent:
    """Evento de freeze detectado na telemetria.

    Gerado quando 3 ou mais amostras consecutivas apresentam
    total_frames_decoded sem avanço.
    """

    timestamp: str
    """Timestamp ISO 8601 do início do freeze."""

    duration_samples: int
    """Número de amostras consecutivas com freeze detectado."""

    current_time_stalled: float
    """Valor de currentTime que permaneceu estagnado."""

    annotation: dict | None = None
    """Contexto concorrente (ex: track switch em andamento)."""


@dataclass
class TelemetrySummary:
    """Resumo da coleta de telemetria de uma Channel Session.

    Produzido pelo VideoTelemetryCollector ao final da sessão,
    agregando todas as amostras coletadas.
    """

    total_samples: int
    """Número total de amostras coletadas durante a sessão."""

    freeze_events: list[FreezeEvent] = field(default_factory=list)
    """Lista de eventos de freeze detectados."""

    average_buffer_ahead_s: float = 0.0
    """Média de buffer disponível em segundos."""

    average_fps: float | None = None
    """FPS médio calculado. None se não houver dados suficientes."""

    health_classification: str = "HEALTHY"
    """Classificação de saúde: HEALTHY | SUSPECT | DEGRADED | CRITICAL."""

    annotations: list[dict] = field(default_factory=list)
    """Amostras anotadas com contexto de track switch."""

    start_time: str = ""
    """Timestamp ISO 8601 da primeira amostra."""

    end_time: str = ""
    """Timestamp ISO 8601 da última amostra."""

    duration_s: float = 0.0
    """Duração total da coleta em segundos."""


@dataclass
class DeferredEscalation:
    """Escalação deferida durante teste de tracks.

    Criada quando o VideoTelemetryCollector detecta anomalia enquanto
    AudioTrackTester ou SubtitleTrackTester está interagindo com a UI.
    A escalação é enfileirada e processada após o teste atual completar.
    """

    trigger_timestamp: str
    """Timestamp ISO 8601 do momento em que a anomalia foi detectada."""

    health_classification: str
    """Classificação de saúde que disparou a escalação."""

    telemetry_sample: TelemetrySample
    """Amostra de telemetria que motivou a escalação."""

    track_switch_context: dict | None = None
    """Contexto do track switch em andamento no momento da detecção."""


@dataclass
class EscalationResult:
    """Resultado de uma escalação processada.

    Contém os vereditos do pipeline OpenCV → Bedrock.
    """

    trigger_timestamp: str
    """Timestamp ISO 8601 do trigger original."""

    opencv_verdict: str | None = None
    """Veredito do OpenCV: 'black_screen' | 'freeze' | 'normal' | None."""

    bedrock_diagnosis: str | None = None
    """Diagnóstico textual do Bedrock ou None se não escalado."""

    frames_analyzed: int = 0
    """Número de frames capturados e analisados."""

    deferred: bool = False
    """True se esta escalação foi deferida durante teste de track."""


@dataclass
class AudioTrackResult:
    """Resultado do teste de um audio track.

    Produzido pelo AudioTrackTester para cada track de áudio
    disponível no Settings Dialog.
    """

    track_name: str
    """Nome do track conforme exibido na UI."""

    status: str
    """Resultado do teste: PASS | FAIL | SKIP."""

    fail_reason: str | None = None
    """Razão da falha: 'switch_timeout' | None."""

    rms_avg: float | None = None
    """RMS médio medido via Web Audio API."""

    audio_present_ratio: float | None = None
    """Proporção de amostras com áudio detectado (0.0 a 1.0)."""

    switch_validated: bool = False
    """True se a troca foi validada via Shaka Player API."""

    duration_ms: int = 0
    """Duração total do teste deste track em milissegundos."""


@dataclass
class SubtitleTrackResult:
    """Resultado do teste de um subtitle track.

    Produzido pelo SubtitleTrackTester para cada track de legenda
    disponível no Settings Dialog.
    """

    track_name: str
    """Nome do track conforme exibido na UI."""

    status: str
    """Resultado do teste: PASS | FAIL | SKIP."""

    fail_reason: str | None = None
    """Razão da falha: 'switch_timeout' | 'no_cue_received' |
    'dialog_unavailable'."""

    cue_received: bool = False
    """True se pelo menos um TextTrack cue foi recebido."""

    time_to_first_cue_ms: int | None = None
    """Tempo até o primeiro cue em milissegundos.
    None se nenhum cue recebido."""

    switch_validated: bool = False
    """True se a troca foi validada via Shaka Player API."""

    duration_ms: int = 0
    """Duração total do teste deste track em milissegundos."""


@dataclass
class UnifiedChannelReport:
    """Relatório unificado por canal.

    Agrega telemetria de vídeo, resultados de áudio, resultados de legendas
    e escalações em um único relatório por Channel Session.
    """

    channel_url: str
    """URL do canal monitorado."""

    channel_id: str
    """Identificador derivado da URL do canal."""

    session_id: str
    """UUID da sessão para correlação de logs."""

    timestamp: str
    """Timestamp ISO 8601 da geração do relatório."""

    status: str
    """Status final da sessão: PASS | PARTIAL | FAIL | UNREACHABLE | ERROR."""

    duration_ms: int
    """Duração total da Channel Session em milissegundos."""

    # Vídeo
    video_summary: TelemetrySummary = field(
        default_factory=lambda: TelemetrySummary(total_samples=0)
    )
    """Resumo da telemetria de vídeo coletada."""

    # Áudio
    audio_tracks_tested: int = 0
    """Número de tracks de áudio testados."""

    audio_tracks_passed: int = 0
    """Número de tracks de áudio que passaram."""

    audio_results: list[AudioTrackResult] = field(default_factory=list)
    """Resultados individuais por track de áudio."""

    # Legendas
    subtitle_tracks_tested: int = 0
    """Número de tracks de legenda testados."""

    subtitle_tracks_passed: int = 0
    """Número de tracks de legenda que passaram."""

    subtitle_results: list[SubtitleTrackResult] = field(default_factory=list)
    """Resultados individuais por track de legenda."""

    # Escalação
    escalation_results: list[EscalationResult] = field(default_factory=list)
    """Resultados de escalações processadas durante a sessão."""

    # Anotações (correlação entre freeze/buffer e track switches)
    telemetry_annotations: list[dict] = field(default_factory=list)
    """Anotações correlacionando eventos de telemetria com switches."""

    errors: list[str] = field(default_factory=list)
    """Erros ocorridos durante a sessão."""


@dataclass
class ConsolidatedReport:
    """Relatório consolidado de uma rotação completa.

    Agrega todos os UnifiedChannelReports de uma rotação,
    com contagens por status para visão geral rápida.
    """

    timestamp: str
    """Timestamp ISO 8601 da geração do relatório consolidado."""

    total_channels: int
    """Número total de canais processados na rotação."""

    channels_pass: int = 0
    """Canais com status PASS."""

    channels_partial: int = 0
    """Canais com status PARTIAL."""

    channels_fail: int = 0
    """Canais com status FAIL."""

    channels_unreachable: int = 0
    """Canais com status UNREACHABLE."""

    channels_error: int = 0
    """Canais com status ERROR."""

    total_duration_ms: int = 0
    """Duração total da rotação em milissegundos."""

    channel_reports: list[UnifiedChannelReport] = field(default_factory=list)
    """Lista de relatórios individuais por canal."""

    is_partial: bool = False
    """True se o shutdown interrompeu a rotação antes de completar."""
