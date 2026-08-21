"""Models — Data models, enums e estruturas de dados do Player Discovery.

Exporta todos os models e enums para importação conveniente:
    from src.player_discovery.models import InteractionLevel, Capability, VideoTelemetry, ...
"""

from .enums import (
    AudioStatus,
    BufferStatus,
    CapabilityStatus,
    ChannelHealthStatus,
    FunctionalTestStatus,
    InteractionLevel,
)
from .capability import (
    Capability,
    CapabilityMapData,
    InteractionStrategy,
    PlayerInfo,
)
from .capability_map import (
    CapabilityMap,
    REQUIRED_CAPABILITIES,
)
from .telemetry import (
    AudioTelemetry,
    BufferTelemetry,
    PlayerEvent,
    SubtitleTelemetry,
    VideoTelemetry,
)
from .results import (
    ChannelReport,
    FunctionalTestResult,
    HealthScores,
    InteractionResult,
)

__all__ = [
    # Enums
    "AudioStatus",
    "BufferStatus",
    "CapabilityStatus",
    "ChannelHealthStatus",
    "FunctionalTestStatus",
    "InteractionLevel",
    # Capability models
    "Capability",
    "CapabilityMap",
    "CapabilityMapData",
    "InteractionStrategy",
    "PlayerInfo",
    "REQUIRED_CAPABILITIES",
    # Telemetry models
    "AudioTelemetry",
    "BufferTelemetry",
    "PlayerEvent",
    "SubtitleTelemetry",
    "VideoTelemetry",
    # Result models
    "ChannelReport",
    "FunctionalTestResult",
    "HealthScores",
    "InteractionResult",
]
