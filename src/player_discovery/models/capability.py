"""Data models de capabilities do Player Discovery.

Define as estruturas de dados para representar capabilities descobertas,
estratégias de interação e informações do player.
"""

from dataclasses import dataclass, field
from typing import Optional

from dataclasses_json import dataclass_json

from .enums import InteractionLevel


@dataclass_json
@dataclass
class InteractionStrategy:
    """Estratégia de interação para uma capability.

    Attributes:
        level: Nível de interação (PLAYER_API, SEMANTIC_DOM, VISUAL_FALLBACK)
        type: Tipo da estratégia (ex: "player_api", "semantic_dom", "visual_fallback")
        details: Detalhes adicionais da estratégia (ex: method, role, aria_label)
    """

    level: InteractionLevel
    type: str
    details: dict = field(default_factory=dict)


@dataclass_json
@dataclass
class Capability:
    """Uma capability descoberta do player.

    Attributes:
        name: Nome da capability (ex: "play", "pause", "mute")
        available: Se a capability está disponível (confidence >= 0.7)
        confidence: Grau de certeza sobre a capability (0.0 a 1.0)
        evidence: Lista de razões que justificam a classificação
        interaction_strategy: Nível de interação preferencial
        strategies: Lista de estratégias disponíveis ordenadas por preferência
    """

    name: str
    available: bool
    confidence: float  # 0.0 a 1.0
    evidence: list[str] = field(default_factory=list)
    interaction_strategy: InteractionLevel = InteractionLevel.SEMANTIC_DOM
    strategies: list[InteractionStrategy] = field(default_factory=list)


@dataclass_json
@dataclass
class PlayerInfo:
    """Informações gerais do player descobertas no startup.

    Attributes:
        library: Biblioteca do player (ex: "shaka-player", "video.js")
        version: Versão do player
        video_elements: Descrições dos elementos de vídeo encontrados
        discovered_at: Timestamp ISO 8601 do momento da descoberta
    """

    library: Optional[str] = None
    version: Optional[str] = None
    video_elements: list[str] = field(default_factory=list)
    discovered_at: str = ""


@dataclass_json
@dataclass
class CapabilityMapData:
    """Dados internos do Capability Map.

    Estrutura central que armazena todas as informações descobertas sobre
    o player, incluindo informações gerais e capabilities individuais.

    Attributes:
        player_info: Informações gerais do player
        capabilities: Dicionário de capabilities por nome
        discovery_duration_ms: Duração do processo de discovery em milissegundos
        version_hash: Hash SHA-256 da estrutura DOM para detecção de mudanças
        valid: Se o mapa está válido (não invalidado por mudanças)
    """

    player_info: PlayerInfo
    capabilities: dict[str, Capability] = field(default_factory=dict)
    discovery_duration_ms: int = 0
    version_hash: str = ""
    valid: bool = True
