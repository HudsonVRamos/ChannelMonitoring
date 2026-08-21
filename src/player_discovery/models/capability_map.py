"""Capability Map — ponto central de acesso às capabilities do player.

O CapabilityMap encapsula o CapabilityMapData e fornece métodos
para consulta, validação e serialização das capabilities descobertas.
Nenhum módulo do sistema deve acessar seletores, IDs ou classes CSS
diretamente — toda interação com o player passa pelo CapabilityMap.
"""

from typing import Optional

from .capability import (
    Capability,
    CapabilityMapData,
    InteractionStrategy,
    PlayerInfo,
)


# Capabilities mínimas obrigatórias (Requirement 2.1)
REQUIRED_CAPABILITIES = frozenset([
    "play",
    "pause",
    "mute",
    "unmute",
    "audio_selection",
    "subtitle_selection",
    "quality_selection",
    "fullscreen",
    "settings",
])


class CapabilityMap:
    """Mapa central de capabilities do player.

    Ponto único de acesso para informações de interação com o player.
    Encapsula CapabilityMapData e oferece interface para consulta,
    validação, invalidação e serialização JSON.

    Attributes:
        _data: Dados internos do Capability Map.
    """

    def __init__(self, data: CapabilityMapData) -> None:
        """Inicializa o CapabilityMap com os dados fornecidos.

        Args:
            data: Instância de CapabilityMapData com as capabilities.
        """
        self._data = data

    @property
    def data(self) -> CapabilityMapData:
        """Acesso somente leitura aos dados internos."""
        return self._data

    @property
    def player_info(self) -> PlayerInfo:
        """Informações do player descobertas."""
        return self._data.player_info

    @property
    def capabilities(self) -> dict[str, Capability]:
        """Dicionário de capabilities disponíveis."""
        return self._data.capabilities

    @property
    def version_hash(self) -> str:
        """Hash da estrutura DOM para detecção de mudanças."""
        return self._data.version_hash

    @property
    def discovery_duration_ms(self) -> int:
        """Duração do processo de discovery em milissegundos."""
        return self._data.discovery_duration_ms

    def get_capability(self, name: str) -> Optional[Capability]:
        """Retorna uma capability pelo nome.

        Args:
            name: Nome da capability (ex: "play", "pause", "mute").

        Returns:
            A Capability correspondente ou None se não encontrada.
        """
        return self._data.capabilities.get(name)

    def get_interaction_strategy(
        self, capability: str
    ) -> Optional[InteractionStrategy]:
        """Retorna a estratégia de interação preferencial para uma capability.

        A estratégia preferencial é a primeira da lista de strategies
        (ordenada por nível: player_api > semantic_dom > visual_fallback).
        Se não houver strategies definidas, cria uma baseada no
        interaction_strategy da capability.

        Args:
            capability: Nome da capability.

        Returns:
            A InteractionStrategy preferencial ou None se capability
            não encontrada.
        """
        cap = self._data.capabilities.get(capability)
        if cap is None:
            return None

        if cap.strategies:
            return cap.strategies[0]

        # Fallback: criar strategy baseada no interaction_strategy
        return InteractionStrategy(
            level=cap.interaction_strategy,
            type=cap.interaction_strategy.value,
            details={},
        )

    def is_valid(self) -> bool:
        """Verifica se o mapa está válido (não invalidado).

        Returns:
            True se o mapa está válido para uso, False caso contrário.
        """
        return self._data.valid

    def invalidate(self) -> None:
        """Marca o mapa como inválido.

        Após invalidação, o DiscoveryEngine deve executar re-discovery
        para produzir um novo CapabilityMap.
        """
        self._data.valid = False

    def has_required_capabilities(self) -> bool:
        """Verifica se o mapa contém todas as capabilities obrigatórias.

        Returns:
            True se todas as capabilities mínimas estão presentes.
        """
        return REQUIRED_CAPABILITIES.issubset(
            self._data.capabilities.keys()
        )

    def get_available_capabilities(self) -> dict[str, Capability]:
        """Retorna apenas as capabilities marcadas como available.

        Returns:
            Dicionário com capabilities onde available=True.
        """
        return {
            name: cap
            for name, cap in self._data.capabilities.items()
            if cap.available
        }

    def to_json(self) -> str:
        """Serializa o Capability Map completo para JSON.

        Returns:
            String JSON representando o mapa completo.
        """
        return self._data.to_json()  # type: ignore[no-any-return]

    @classmethod
    def from_json(cls, json_str: str) -> "CapabilityMap":
        """Deserializa um Capability Map a partir de JSON.

        Args:
            json_str: String JSON produzida por to_json().

        Returns:
            Nova instância de CapabilityMap com os dados deserializados.

        Raises:
            json.JSONDecodeError: Se o JSON for inválido.
            KeyError: Se campos obrigatórios estiverem ausentes.
        """
        data = CapabilityMapData.from_json(  # type: ignore[attr-defined]
            json_str
        )
        return cls(data)

    def __repr__(self) -> str:
        """Representação legível do CapabilityMap."""
        available = len(self.get_available_capabilities())
        total = len(self._data.capabilities)
        valid_str = "valid" if self.is_valid() else "INVALID"
        return (
            f"CapabilityMap("
            f"capabilities={available}/{total} available, "
            f"{valid_str})"
        )
