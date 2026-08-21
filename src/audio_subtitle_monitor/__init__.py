"""Audio & Subtitle Monitor — Monitoramento de áudio e legendas via UI."""

from .audio_monitor import AudioMonitor
from .config import AudioSubtitleConfig
from .main import run_audio_subtitle_monitoring
from .models import TrackOption
from .orchestrator import AudioSubtitleOrchestrator
from .report_generator import ReportGenerator
from .settings_dialog_manager import (
    AUDIO_SECTION_TITLE,
    SUBTITLE_SECTION_TITLE,
    SettingsDialogManager,
)
from .subtitle_monitor import SubtitleMonitor

__all__ = [
    "AudioMonitor",
    "AudioSubtitleConfig",
    "AudioSubtitleOrchestrator",
    "ReportGenerator",
    "SettingsDialogManager",
    "SubtitleMonitor",
    "TrackOption",
    "run_audio_subtitle_monitoring",
    "AUDIO_SECTION_TITLE",
    "SUBTITLE_SECTION_TITLE",
]
