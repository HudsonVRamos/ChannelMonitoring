"""Unified Channel Monitor — módulo base.

Consolida player_discovery (monitoramento de vídeo) e audio_subtitle_monitor
(testes de áudio/legendas) em um único orquestrador unificado.

Componentes principais:
- UnifiedOrchestrator: coordena todo o ciclo de vida
- VideoTelemetryCollector: coleta telemetria de vídeo em background
- AudioTrackTester: testa tracks de áudio
- SubtitleTrackTester: testa tracks de legendas
- EscalationManager: pipeline de escalação deferida
- UnifiedReportGenerator: geração de relatórios unificados
- UnifiedMonitorConfig: configuração centralizada via env vars
"""

__version__ = "0.1.0"

from src.unified_channel_monitor.config import UnifiedMonitorConfig
from src.unified_channel_monitor.models import (
    AudioTrackResult,
    ChannelSessionStatus,
    ConsolidatedReport,
    DeferredEscalation,
    EscalationResult,
    FreezeEvent,
    SubtitleTrackResult,
    TelemetrySample,
    TelemetrySummary,
    UnifiedChannelReport,
)
from src.unified_channel_monitor.video_telemetry import (
    VideoTelemetryCollector,
)
from src.unified_channel_monitor.audio_tester import AudioTrackTester
from src.unified_channel_monitor.subtitle_tester import SubtitleTrackTester
from src.unified_channel_monitor.escalation import EscalationManager
from src.unified_channel_monitor.report_generator import (
    UnifiedReportGenerator,
)
from src.unified_channel_monitor.orchestrator import UnifiedOrchestrator

__all__ = [
    "AudioTrackResult",
    "AudioTrackTester",
    "ChannelSessionStatus",
    "ConsolidatedReport",
    "DeferredEscalation",
    "EscalationManager",
    "EscalationResult",
    "FreezeEvent",
    "SubtitleTrackResult",
    "SubtitleTrackTester",
    "TelemetrySample",
    "TelemetrySummary",
    "UnifiedChannelReport",
    "UnifiedMonitorConfig",
    "UnifiedOrchestrator",
    "UnifiedReportGenerator",
    "VideoTelemetryCollector",
]
