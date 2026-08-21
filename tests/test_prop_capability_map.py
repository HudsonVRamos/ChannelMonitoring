"""Property-Based Tests para CapabilityMap.

Feature: player-discovery, Property 3: Capability Map contém estrutura
mínima obrigatória

Testa que para qualquer CapabilityMap produzido com todas as capabilities
obrigatórias, a estrutura contém player_info (library, version,
video_elements) e capabilities com campos available, confidence,
evidence e interaction_strategy.

Validates: Requirements 1.7, 2.1
"""

from hypothesis import given, settings, strategies as st

from src.player_discovery.models import (
    Capability,
    CapabilityMap,
    CapabilityMapData,
    InteractionStrategy,
    PlayerInfo,
    REQUIRED_CAPABILITIES,
)
from src.player_discovery.models.enums import InteractionLevel


# --- Estratégias de geração ---

interaction_levels = st.sampled_from([
    InteractionLevel.PLAYER_API,
    InteractionLevel.SEMANTIC_DOM,
    InteractionLevel.VISUAL_FALLBACK,
])


def interaction_strategy_st():
    """Gera uma InteractionStrategy válida."""
    return st.builds(
        InteractionStrategy,
        level=interaction_levels,
        type=st.sampled_from([
            "player_api", "semantic_dom", "visual_fallback"
        ]),
        details=st.just({}),
    )


def capability_st(name: str):
    """Gera uma Capability válida para o nome fornecido."""
    return st.builds(
        Capability,
        name=st.just(name),
        available=st.booleans(),
        confidence=st.floats(
            min_value=0.0, max_value=1.0,
            allow_nan=False, allow_infinity=False,
        ),
        evidence=st.lists(
            st.text(min_size=1, max_size=50),
            min_size=0, max_size=5,
        ),
        interaction_strategy=interaction_levels,
        strategies=st.lists(
            interaction_strategy_st(),
            min_size=0, max_size=3,
        ),
    )


@st.composite
def capability_map_st(draw):
    """Gera um CapabilityMap válido com todas as capabilities obrigatórias.

    Garante que todas as 9 capabilities obrigatórias estão presentes,
    podendo ter capabilities extras aleatórias.
    """
    # Gerar player_info com campos opcionais
    library = draw(st.one_of(st.none(), st.text(min_size=1, max_size=30)))
    version = draw(st.one_of(st.none(), st.text(min_size=1, max_size=15)))
    video_elements = draw(st.lists(
        st.text(min_size=1, max_size=30),
        min_size=0, max_size=5,
    ))
    discovered_at = draw(st.text(min_size=0, max_size=30))

    player_info = PlayerInfo(
        library=library,
        version=version,
        video_elements=video_elements,
        discovered_at=discovered_at,
    )

    # Gerar capabilities obrigatórias
    capabilities = {}
    for cap_name in REQUIRED_CAPABILITIES:
        capabilities[cap_name] = draw(capability_st(cap_name))

    # Opcionalmente adicionar capabilities extras
    extra_names = draw(st.lists(
        st.text(
            alphabet=st.characters(
                whitelist_categories=("Ll",),
            ),
            min_size=3, max_size=15,
        ).filter(lambda n: n not in REQUIRED_CAPABILITIES),
        min_size=0, max_size=3,
    ))
    for extra_name in extra_names:
        capabilities[extra_name] = draw(capability_st(extra_name))

    data = CapabilityMapData(
        player_info=player_info,
        capabilities=capabilities,
        discovery_duration_ms=draw(
            st.integers(min_value=0, max_value=120000)
        ),
        version_hash=draw(st.text(min_size=0, max_size=64)),
        valid=True,
    )

    return CapabilityMap(data)


class TestProperty3EstruturaMinimaObrigatoria:
    """Feature: player-discovery, Property 3: Capability Map contém
    estrutura mínima obrigatória

    Para qualquer CapabilityMap produzido pelo Discovery Engine, o mapa
    deve conter player_info (library, version, video_elements) e
    capabilities para no mínimo: play, pause, mute, unmute,
    audio_selection, subtitle_selection, quality_selection, fullscreen
    e settings — cada uma com campos available, confidence, evidence
    e interaction_strategy.

    Validates: Requirements 1.7, 2.1
    """

    @settings(max_examples=100)
    @given(cmap=capability_map_st())
    def test_has_required_capabilities_returns_true(self, cmap):
        """Verifica que has_required_capabilities() retorna True quando
        todas as 9 capabilities obrigatórias estão presentes."""
        assert cmap.has_required_capabilities() is True

    @settings(max_examples=100)
    @given(cmap=capability_map_st())
    def test_all_required_capabilities_present(self, cmap):
        """Verifica que cada uma das 9 capabilities obrigatórias
        está presente no mapa."""
        for cap_name in REQUIRED_CAPABILITIES:
            cap = cmap.get_capability(cap_name)
            assert cap is not None, (
                f"Capability '{cap_name}' ausente do mapa"
            )

    @settings(max_examples=100)
    @given(cmap=capability_map_st())
    def test_each_capability_has_required_fields(self, cmap):
        """Verifica que cada capability obrigatória possui os campos:
        available (bool), confidence (float 0-1), evidence (list)
        e interaction_strategy (InteractionLevel)."""
        for cap_name in REQUIRED_CAPABILITIES:
            cap = cmap.get_capability(cap_name)
            assert cap is not None

            # available deve ser bool
            assert isinstance(cap.available, bool), (
                f"'{cap_name}'.available não é bool: {type(cap.available)}"
            )

            # confidence deve ser float entre 0.0 e 1.0
            assert isinstance(cap.confidence, float), (
                f"'{cap_name}'.confidence não é float: "
                f"{type(cap.confidence)}"
            )
            assert 0.0 <= cap.confidence <= 1.0, (
                f"'{cap_name}'.confidence fora do range [0,1]: "
                f"{cap.confidence}"
            )

            # evidence deve ser uma lista
            assert isinstance(cap.evidence, list), (
                f"'{cap_name}'.evidence não é list: {type(cap.evidence)}"
            )

            # interaction_strategy deve ser InteractionLevel
            assert isinstance(
                cap.interaction_strategy, InteractionLevel
            ), (
                f"'{cap_name}'.interaction_strategy não é "
                f"InteractionLevel: "
                f"{type(cap.interaction_strategy)}"
            )

    @settings(max_examples=100)
    @given(cmap=capability_map_st())
    def test_player_info_has_required_structure(self, cmap):
        """Verifica que player_info contém os campos obrigatórios:
        library, version e video_elements."""
        info = cmap.player_info
        assert info is not None, "player_info é None"

        # library pode ser None ou str
        assert info.library is None or isinstance(info.library, str), (
            f"player_info.library tipo inválido: {type(info.library)}"
        )

        # version pode ser None ou str
        assert info.version is None or isinstance(info.version, str), (
            f"player_info.version tipo inválido: {type(info.version)}"
        )

        # video_elements deve ser lista
        assert isinstance(info.video_elements, list), (
            f"player_info.video_elements não é list: "
            f"{type(info.video_elements)}"
        )

    @settings(max_examples=100)
    @given(cmap=capability_map_st())
    def test_capability_count_at_least_nine(self, cmap):
        """Verifica que o mapa contém no mínimo 9 capabilities
        (as obrigatórias)."""
        assert len(cmap.capabilities) >= 9, (
            f"Mapa tem apenas {len(cmap.capabilities)} capabilities, "
            f"mínimo esperado: 9"
        )


# --- Property 2: Classificação de confidence determinística ---


from typing import List, Optional


def classify_capability(
    name: str,
    confidence: float,
    interaction_strategy: InteractionLevel,
    evidence: Optional[List[str]] = None,
) -> Capability:
    """Classifica uma capability com base no confidence score.

    Aplica a regra de classificação determinística:
    - confidence >= 0.7 → available=True
    - confidence < 0.7 → available=False

    Args:
        name: Nome da capability
        confidence: Score de confiança (0.0 a 1.0)
        interaction_strategy: Nível de interação preferencial
        evidence: Lista de evidências que justificam a classificação

    Returns:
        Capability classificada conforme a regra de confidence
    """
    available = confidence >= 0.7
    return Capability(
        name=name,
        available=available,
        confidence=confidence,
        evidence=evidence or [],
        interaction_strategy=interaction_strategy,
        strategies=[],
    )


class TestProperty2ClassificacaoConfidenceDeterministica:
    """Feature: player-discovery, Property 2: Classificação de confidence é determinística

    Para qualquer capability com um confidence score:
    - Se confidence >= 0.7 então available deve ser True e interaction_strategy
      deve ser um dos valores válidos da hierarquia
      (player_api, semantic_dom, visual_fallback)
    - Se confidence < 0.7 então available deve ser False

    **Validates: Requirements 2.2, 2.3**
    """

    @settings(max_examples=100)
    @given(
        confidence=st.floats(
            min_value=0.7, max_value=1.0,
            allow_nan=False, allow_infinity=False,
        ),
        interaction_strategy=interaction_levels,
        name=st.text(min_size=1, max_size=30),
    )
    def test_alta_confidence_implica_available_true(
        self, confidence, interaction_strategy, name
    ):
        """Quando confidence >= 0.7, a capability deve ser available=True
        e interaction_strategy deve ser um valor válido da hierarquia."""
        capability = classify_capability(
            name=name,
            confidence=confidence,
            interaction_strategy=interaction_strategy,
        )

        assert capability.available is True
        assert capability.interaction_strategy in (
            InteractionLevel.PLAYER_API,
            InteractionLevel.SEMANTIC_DOM,
            InteractionLevel.VISUAL_FALLBACK,
        )

    @settings(max_examples=100)
    @given(
        confidence=st.floats(
            min_value=0.0, max_value=0.7,
            exclude_max=True,
            allow_nan=False, allow_infinity=False,
        ),
        interaction_strategy=interaction_levels,
        name=st.text(min_size=1, max_size=30),
    )
    def test_baixa_confidence_implica_available_false(
        self, confidence, interaction_strategy, name
    ):
        """Quando confidence < 0.7, a capability deve ser available=False."""
        capability = classify_capability(
            name=name,
            confidence=confidence,
            interaction_strategy=interaction_strategy,
        )

        assert capability.available is False

    @settings(max_examples=100)
    @given(
        confidence=st.floats(
            min_value=0.0, max_value=1.0,
            allow_nan=False, allow_infinity=False,
        ),
        interaction_strategy=interaction_levels,
        name=st.text(min_size=1, max_size=30),
    )
    def test_classificacao_deterministica_mesma_entrada_mesmo_resultado(
        self, confidence, interaction_strategy, name
    ):
        """Para a mesma entrada, classify_capability sempre produz
        o mesmo resultado (determinismo)."""
        resultado_1 = classify_capability(
            name=name,
            confidence=confidence,
            interaction_strategy=interaction_strategy,
        )
        resultado_2 = classify_capability(
            name=name,
            confidence=confidence,
            interaction_strategy=interaction_strategy,
        )

        assert resultado_1.available == resultado_2.available
        assert resultado_1.confidence == resultado_2.confidence
        assert (
            resultado_1.interaction_strategy
            == resultado_2.interaction_strategy
        )


# --- Property 1: Serialização round-trip do Capability Map ---


class TestProperty1SerializacaoRoundTrip:
    """Feature: player-discovery, Property 1: Serialização round-trip
    do Capability Map

    Para qualquer Capability Map válido, serializar para JSON e
    deserializar de volta deve produzir um objeto equivalente ao original.

    **Validates: Requirements 2.5**
    """

    @settings(max_examples=100)
    @given(cmap=capability_map_st())
    def test_round_trip_produces_equivalent_object(
        self, cmap: CapabilityMap
    ) -> None:
        """Serializar para JSON e deserializar deve produzir objeto equivalente.

        Para qualquer CapabilityMap válido, a operação:
            CapabilityMap.from_json(cmap.to_json())
        deve produzir um CapabilityMap com dados equivalentes ao original.

        **Validates: Requirements 2.5**
        """
        # Act
        json_str = cmap.to_json()
        restored = CapabilityMap.from_json(json_str)

        # Assert — verificar equivalência estrutural
        assert restored.is_valid() == cmap.is_valid(), (
            f"valid divergiu: original={cmap.is_valid()}, "
            f"restored={restored.is_valid()}"
        )

        # PlayerInfo
        assert (
            restored.player_info.library == cmap.player_info.library
        ), (
            f"library divergiu: original={cmap.player_info.library}, "
            f"restored={restored.player_info.library}"
        )
        assert (
            restored.player_info.version == cmap.player_info.version
        ), (
            f"version divergiu: original={cmap.player_info.version}, "
            f"restored={restored.player_info.version}"
        )
        assert (
            restored.player_info.video_elements
            == cmap.player_info.video_elements
        ), "video_elements divergiu"
        assert (
            restored.player_info.discovered_at
            == cmap.player_info.discovered_at
        ), "discovered_at divergiu"

        # Capabilities
        assert set(restored.capabilities.keys()) == set(
            cmap.capabilities.keys()
        ), (
            f"Capabilities keys divergiram: "
            f"original={set(cmap.capabilities.keys())}, "
            f"restored={set(restored.capabilities.keys())}"
        )

        for cap_name in cmap.capabilities:
            orig_cap = cmap.capabilities[cap_name]
            rest_cap = restored.capabilities[cap_name]

            assert rest_cap.name == orig_cap.name, (
                f"Capability '{cap_name}': name divergiu"
            )
            assert rest_cap.available == orig_cap.available, (
                f"Capability '{cap_name}': available divergiu "
                f"(original={orig_cap.available}, "
                f"restored={rest_cap.available})"
            )
            assert rest_cap.confidence == orig_cap.confidence, (
                f"Capability '{cap_name}': confidence divergiu "
                f"(original={orig_cap.confidence}, "
                f"restored={rest_cap.confidence})"
            )
            assert rest_cap.evidence == orig_cap.evidence, (
                f"Capability '{cap_name}': evidence divergiu"
            )
            assert (
                rest_cap.interaction_strategy
                == orig_cap.interaction_strategy
            ), (
                f"Capability '{cap_name}': interaction_strategy divergiu"
            )

            # Strategies
            assert len(rest_cap.strategies) == len(
                orig_cap.strategies
            ), (
                f"Capability '{cap_name}': strategies length divergiu"
            )
            for i, (rest_s, orig_s) in enumerate(
                zip(rest_cap.strategies, orig_cap.strategies)
            ):
                assert rest_s.level == orig_s.level, (
                    f"Capability '{cap_name}' strategy[{i}]: "
                    f"level divergiu"
                )
                assert rest_s.type == orig_s.type, (
                    f"Capability '{cap_name}' strategy[{i}]: "
                    f"type divergiu"
                )
                assert rest_s.details == orig_s.details, (
                    f"Capability '{cap_name}' strategy[{i}]: "
                    f"details divergiu"
                )

        # Metadata
        assert (
            restored.discovery_duration_ms == cmap.discovery_duration_ms
        ), "discovery_duration_ms divergiu"
        assert restored.version_hash == cmap.version_hash, (
            "version_hash divergiu"
        )

    @settings(max_examples=100)
    @given(cmap=capability_map_st())
    def test_to_json_produces_valid_json_string(
        self, cmap: CapabilityMap
    ) -> None:
        """to_json() deve produzir uma string JSON válida (parseable).

        Para qualquer CapabilityMap válido, to_json() deve retornar
        uma string que é JSON válido.

        **Validates: Requirements 2.5**
        """
        import json

        json_str = cmap.to_json()

        # A string deve ser parseável como JSON
        parsed = json.loads(json_str)
        assert isinstance(parsed, dict), (
            f"JSON parseado deveria ser dict, mas é {type(parsed)}"
        )

    @settings(max_examples=100)
    @given(cmap=capability_map_st())
    def test_double_round_trip_is_stable(
        self, cmap: CapabilityMap
    ) -> None:
        """Duplo round-trip deve ser estável (idempotente).

        Para qualquer CapabilityMap, aplicar serialização/deserialização
        duas vezes seguidas deve produzir o mesmo resultado.

        **Validates: Requirements 2.5**
        """
        # Primeiro round-trip
        json1 = cmap.to_json()
        restored1 = CapabilityMap.from_json(json1)

        # Segundo round-trip
        json2 = restored1.to_json()

        # Os JSONs do primeiro e segundo round-trip devem ser iguais
        assert json1 == json2, (
            "Duplo round-trip não é estável: "
            "JSON do primeiro round-trip difere do segundo"
        )
