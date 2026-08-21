"""Data models do módulo de monitoramento de áudio e legendas.

Define as estruturas de dados para resultados de testes de tracks,
relatórios por canal e relatório consolidado multi-canal.

Enums:
- TrackTestStatus: Status individual de teste de track (PASS/FAIL/TIMEOUT)
- OverallStatus: Status consolidado do canal (PASS/PARTIAL/FAIL)

Dataclasses:
- TrackOption: Opção de track descoberta no Settings Dialog
- ValidationResult: Resultado de validação cruzada UI vs API
- AudioSample: Amostra individual de áudio
- AudioTelemetryResult: Resultado agregado da coleta de telemetria de áudio
- CueResult: Resultado da espera por cue de legenda
- TrackTestResult: Resultado individual do teste de um track
- ChannelTestReport: Relatório consolidado de uma Monitoring_Session
- ConsolidatedReport: Relatório consolidado de execução multi-canal
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal


class TrackTestStatus(Enum):
    """Status do teste de um track."""

    PASS = "PASS"
    FAIL = "FAIL"
    TIMEOUT = "TIMEOUT"


class OverallStatus(Enum):
    """Status geral do canal."""

    PASS = "PASS"
    PARTIAL = "PARTIAL"
    FAIL = "FAIL"


@dataclass
class TrackOption:
    """Opção de track descoberta no Settings Dialog.

    Attributes:
        text: Texto exibido na opção (ex: "Português", "Inglês")
        is_selected: Se a opção está atualmente selecionada/ativa
        index: Posição da opção na lista (0-indexed)
    """

    text: str
    is_selected: bool
    index: int

    def to_dict(self) -> dict[str, Any]:
        """Serializa para dicionário."""
        return {
            "text": self.text,
            "is_selected": self.is_selected,
            "index": self.index,
        }


@dataclass
class ValidationResult:
    """Resultado de validação cruzada UI vs API.

    Attributes:
        success: Se a validação foi bem-sucedida (UI e API consistentes)
        expected_language: Idioma esperado (selecionado na UI)
        actual_active_language: Idioma ativo reportado pela API
        api_tracks: Lista completa de tracks retornada pela API
        error: Mensagem de erro, se aplicável
    """

    success: bool
    expected_language: str
    actual_active_language: str | None
    api_tracks: list[dict]
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serializa para dicionário."""
        return {
            "success": self.success,
            "expected_language": self.expected_language,
            "actual_active_language": self.actual_active_language,
            "api_tracks": self.api_tracks,
            "error": self.error,
        }


@dataclass
class AudioSample:
    """Uma amostra individual de áudio.

    Attributes:
        timestamp: Momento da coleta (segundos desde início da janela)
        rms: Root Mean Square do sinal de áudio (0.0 a 1.0)
        peak: Valor de pico do sinal (0.0 a 1.0)
    """

    timestamp: float
    rms: float
    peak: float

    def to_dict(self) -> dict[str, Any]:
        """Serializa para dicionário."""
        return {
            "timestamp": self.timestamp,
            "rms": self.rms,
            "peak": self.peak,
        }


@dataclass
class AudioTelemetryResult:
    """Resultado da coleta de telemetria de áudio.

    Attributes:
        samples: Lista de amostras coletadas durante a janela
        rms_avg: Média aritmética dos valores RMS
        rms_min: Menor valor RMS encontrado
        rms_max: Maior valor RMS encontrado
        audio_present_ratio: Fração de amostras com RMS > threshold (0.0 a 1.0)
        silence_duration_s: Duração total de silêncio detectado em segundos
        total_duration_s: Duração total da janela de coleta em segundos
    """

    samples: list[AudioSample]
    rms_avg: float
    rms_min: float
    rms_max: float
    audio_present_ratio: float
    silence_duration_s: float
    total_duration_s: float

    def to_dict(self) -> dict[str, Any]:
        """Serializa para dicionário, convertendo samples."""
        return {
            "samples": [sample.to_dict() for sample in self.samples],
            "rms_avg": self.rms_avg,
            "rms_min": self.rms_min,
            "rms_max": self.rms_max,
            "audio_present_ratio": self.audio_present_ratio,
            "silence_duration_s": self.silence_duration_s,
            "total_duration_s": self.total_duration_s,
        }


@dataclass
class CueResult:
    """Resultado da espera por cue de legenda.

    Attributes:
        found: Se uma cue ativa foi detectada dentro do timeout
        cue_text: Primeiros 50 caracteres do texto da cue (se encontrada)
        time_to_first_cue_ms: Tempo até a primeira cue em milissegundos
        error: Mensagem de erro, se aplicável
    """

    found: bool
    cue_text: str | None = None
    time_to_first_cue_ms: int | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serializa para dicionário."""
        return {
            "found": self.found,
            "cue_text": self.cue_text,
            "time_to_first_cue_ms": self.time_to_first_cue_ms,
            "error": self.error,
        }


@dataclass
class TrackTestResult:
    """Resultado individual do teste de um track.

    Attributes:
        track_name: Nome do track testado (ex: "Português", "Inglês")
        track_type: Tipo do track ("audio" ou "subtitle")
        status: Resultado do teste (PASS, FAIL, TIMEOUT)
        evidence: Detalhes da falha ou sucesso (métricas, mensagens)
        duration_ms: Tempo total do teste em milissegundos
        telemetry: Dados de telemetria coletados (quando aplicável)
        api_state_before: Estado da API antes da seleção via UI
        api_state_after: Estado da API após a seleção via UI
    """

    track_name: str
    track_type: Literal["audio", "subtitle"]
    status: TrackTestStatus
    evidence: dict[str, Any]
    duration_ms: int
    telemetry: dict[str, Any] | None = None
    api_state_before: dict[str, Any] | None = None
    api_state_after: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serializa para dicionário, convertendo status enum para string."""
        return {
            "track_name": self.track_name,
            "track_type": self.track_type,
            "status": self.status.value,
            "evidence": self.evidence,
            "duration_ms": self.duration_ms,
            "telemetry": self.telemetry,
            "api_state_before": self.api_state_before,
            "api_state_after": self.api_state_after,
        }


@dataclass
class ChannelTestReport:
    """Relatório consolidado de uma Monitoring_Session.

    Attributes:
        channel_url: URL do canal testado
        channel_id: Identificador do canal (ex: "CH0100000000124")
        timestamp: Data/hora do teste em formato ISO 8601
        audio_results: Lista de resultados dos testes de áudio
        subtitle_results: Lista de resultados dos testes de legendas
        overall_status: Status consolidado (PASS/PARTIAL/FAIL)
        duration_ms: Duração total da sessão em milissegundos
        audio_options_discovered: Textos das opções de áudio encontradas
        subtitle_options_discovered: Textos das opções de legenda encontradas
        errors: Lista de erros ocorridos durante a sessão
    """

    channel_url: str
    channel_id: str
    timestamp: str
    audio_results: list[TrackTestResult]
    subtitle_results: list[TrackTestResult]
    overall_status: OverallStatus
    duration_ms: int
    audio_options_discovered: list[str] = field(default_factory=list)
    subtitle_options_discovered: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serializa para dicionário, convertendo nested results e enums."""
        return {
            "channel_url": self.channel_url,
            "channel_id": self.channel_id,
            "timestamp": self.timestamp,
            "audio_results": [r.to_dict() for r in self.audio_results],
            "subtitle_results": [r.to_dict() for r in self.subtitle_results],
            "overall_status": self.overall_status.value,
            "duration_ms": self.duration_ms,
            "audio_options_discovered": self.audio_options_discovered,
            "subtitle_options_discovered": self.subtitle_options_discovered,
            "errors": self.errors,
        }


@dataclass
class ConsolidatedReport:
    """Relatório consolidado de execução multi-canal.

    Attributes:
        timestamp: Data/hora da execução em formato ISO 8601
        total_channels: Número total de canais testados
        channels_pass: Canais com status PASS
        channels_partial: Canais com status PARTIAL
        channels_fail: Canais com status FAIL
        total_duration_ms: Duração total da execução em milissegundos
        channel_reports: Lista de relatórios individuais por canal
    """

    timestamp: str
    total_channels: int
    channels_pass: int
    channels_partial: int
    channels_fail: int
    total_duration_ms: int
    channel_reports: list[ChannelTestReport] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serializa para dicionário, convertendo nested reports."""
        return {
            "timestamp": self.timestamp,
            "total_channels": self.total_channels,
            "channels_pass": self.channels_pass,
            "channels_partial": self.channels_partial,
            "channels_fail": self.channels_fail,
            "total_duration_ms": self.total_duration_ms,
            "channel_reports": [r.to_dict() for r in self.channel_reports],
        }
