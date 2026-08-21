"""Enumerações do Player Discovery.

Define os enums utilizados por todo o sistema de monitoramento:
- InteractionLevel: Níveis de interação com o player (API, DOM, Visual)
- CapabilityStatus: Status de disponibilidade de capabilities
- ChannelHealthStatus: Status de saúde de canais
- FunctionalTestStatus: Resultado de testes funcionais
- AudioStatus: Estado de áudio
- BufferStatus: Estado de buffer
"""

from enum import Enum


class InteractionLevel(Enum):
    """Nível de interação com o player.

    Define a hierarquia de preferência para interação:
    - PLAYER_API (Nível 1): Chamada direta à API do player
    - SEMANTIC_DOM (Nível 2): Locator via role, aria-label, text, data-attributes
    - VISUAL_FALLBACK (Nível 3): Interação visual sem coordenadas fixas
    """

    PLAYER_API = "player_api"        # Nível 1
    SEMANTIC_DOM = "semantic_dom"     # Nível 2
    VISUAL_FALLBACK = "visual_fallback"  # Nível 3


class CapabilityStatus(Enum):
    """Status de disponibilidade de uma capability."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class ChannelHealthStatus(Enum):
    """Status de saúde de um canal."""

    HEALTHY = "HEALTHY"
    SUSPECT = "SUSPECT"
    DEGRADED = "DEGRADED"
    CRITICAL = "CRITICAL"


class FunctionalTestStatus(Enum):
    """Resultado de um teste funcional."""

    PASS = "PASS"
    FAIL = "FAIL"
    SKIPPED = "SKIPPED"


class AudioStatus(Enum):
    """Estado de áudio detectado pela AudioProbe."""

    OK = "OK"
    NO_AUDIO = "NO_AUDIO"
    AUDIO_LOW = "AUDIO_LOW"


class BufferStatus(Enum):
    """Estado de buffer detectado pela BufferProbe."""

    OK = "OK"
    BUFFER_LOW = "BUFFER_LOW"
    BUFFERING_FREQUENT = "BUFFERING_FREQUENT"
