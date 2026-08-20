"""Data models para a PoC de validação do Widevine DRM.

Contém todas as dataclasses, enums e result classes utilizados
pelos componentes do sistema de monitoramento.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# =============================================================================
# Telemetry Models
# =============================================================================


@dataclass
class VideoMetrics:
    """Métricas de vídeo do player."""

    current_time: float
    video_width: int
    video_height: int
    ready_state: int
    paused: bool
    error: Optional[str]
    buffered_seconds: float


@dataclass
class AudioMetrics:
    """Métricas de áudio do player."""

    average_level: Optional[float]  # 0.0 a 100.0, None se indisponível
    peak_level: Optional[float]  # 0.0 a 100.0, None se indisponível
    is_muted: bool
    unavailable: bool = False


@dataclass
class SubtitleMetrics:
    """Métricas de legendas do player."""

    tracks_available: int
    active_track: Optional[str]
    has_active_cues: bool


@dataclass
class PlayerMetrics:
    """Estado geral do player."""

    playing: bool
    buffering: bool
    drm_ok: bool


@dataclass
class TelemetrySample:
    """Amostra completa de telemetria."""

    timestamp: str  # ISO 8601
    channel_id: str
    video: VideoMetrics
    audio: AudioMetrics
    subtitles: SubtitleMetrics
    player: PlayerMetrics


# =============================================================================
# Enums
# =============================================================================


class ValidationStatus(Enum):
    """Status de uma validação individual."""

    PASS = "PASS"
    FAIL = "FAIL"
    SKIPPED = "SKIPPED"


class GoNoGoDecision(Enum):
    """Decisão final da PoC."""

    GO = "GO"
    NO_GO = "NO_GO"


class FreezeClassification(Enum):
    """Classificação do estado de freeze."""

    NO_FREEZE = "NO_FREEZE"
    FREEZE_CONFIRMED = "FREEZE_CONFIRMED"
    STATIC_CONTENT = "STATIC_CONTENT"
    ANALYSIS_ERROR = "ANALYSIS_ERROR"


class BufferingClassification(Enum):
    """Classificação do estado de buffering."""

    NO_BUFFERING = "NO_BUFFERING"
    BUFFERING_NORMAL = "BUFFERING_NORMAL"
    BUFFERING_PERSISTENT = "BUFFERING_PERSISTENT"


class DiagnosisStatus(Enum):
    """Status do diagnóstico via Bedrock."""

    OK = "OK"
    DEGRADED = "DEGRADED"
    UNKNOWN = "UNKNOWN"


# =============================================================================
# Result Classes
# =============================================================================


@dataclass
class ValidationResult:
    """Resultado de uma validação individual."""

    name: str
    status: ValidationStatus
    start_time: str  # ISO 8601
    end_time: str  # ISO 8601
    duration_ms: int
    error_message: Optional[str] = None
    evidence_paths: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    skipped_reason: Optional[str] = None


@dataclass
class StorageStateResult:
    """Resultado da exportação de storageState."""

    success: bool
    path: str
    cookies_count: int
    error: Optional[str] = None


@dataclass
class SessionResult:
    """Resultado da restauração de sessão."""

    success: bool
    restored: bool
    elapsed_ms: int
    error: Optional[str] = None


@dataclass
class DRMResult:
    """Resultado da validação de DRM."""

    media_keys_created: bool
    license_requested: bool
    license_obtained: bool
    time_to_license_ms: int
    error: Optional[str] = None


@dataclass
class LuminanceResult:
    """Resultado da análise de luminância."""

    mean_luminance: float  # 0-255
    black_pixel_percent: float  # 0-100
    pixel_variance: float


@dataclass
class BlackScreenResult:
    """Resultado da detecção de tela preta."""

    is_black_screen: bool
    is_dark_scene: bool
    luminance: LuminanceResult


@dataclass
class FreezeResult:
    """Resultado da detecção de freeze."""

    classification: FreezeClassification
    similarity: float
    current_time_diff: float
    observation_window_seconds: float


@dataclass
class BufferingState:
    """Estado atual de buffering."""

    classification: BufferingClassification
    duration_seconds: float
    start_time: Optional[str] = None


@dataclass
class DiagnosisResult:
    """Resultado do diagnóstico via Bedrock."""

    status: DiagnosisStatus
    diagnosis: str
    issues: list[str]
    description: str
    confidence: float  # 0.0 a 1.0
    model_used: str  # "haiku" ou "sonnet"
    response_time_ms: int
    escalated: bool = False  # Se foi escalado para Sonnet


# =============================================================================
# Performance and Report Models
# =============================================================================


@dataclass
class PerformanceMetrics:
    """Métricas de performance da PoC."""

    browser_init_time_ms: int
    drm_ready_time_ms: int
    time_per_frame_ms: int
    bedrock_response_time_ms: Optional[int]


@dataclass
class PoCReport:
    """Relatório consolidado da PoC."""

    execution_id: str
    start_time: str  # ISO 8601
    end_time: str  # ISO 8601
    total_duration_ms: int
    decision: GoNoGoDecision
    validations: list[ValidationResult]
    performance: PerformanceMetrics
    log_file_path: str
    environment: dict  # Versões de Playwright, Chromium, Python, OpenCV


# =============================================================================
# Logging Model
# =============================================================================


@dataclass
class LogEntry:
    """Entrada de log estruturada."""

    timestamp: str  # ISO 8601 com milissegundos
    level: str  # DEBUG, INFO, WARNING, ERROR
    stage_id: str
    message: str
    data: Optional[dict] = None
