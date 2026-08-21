"""Property-Based Tests para CSS confidence.

Feature: player-discovery, Property 4: CSS isolado nunca produz alta
confidence

Testa que para qualquer CSSEvidence gerada com propriedades CSS
aleatórias (display, visibility, opacity, pointer-events), a confidence
resultante é SEMPRE inferior a 0.7 — ou seja, CSS isolado nunca
classifica uma capability como available.

Validates: Requirements 1.5
"""

from hypothesis import given, settings, strategies as st

from src.player_discovery.discovery.css_analyzer import (
    CSSAnalyzer,
    CSSEvidence,
    MAX_CSS_ONLY_CONFIDENCE,
)


# Constante do threshold de alta confidence
HIGH_CONFIDENCE_THRESHOLD = 0.7


# --- Estratégias de geração ---

# Capability hints possíveis (incluindo unknown)
capability_hints = st.sampled_from([
    "play", "pause", "mute", "unmute", "audio_selection",
    "subtitle_selection", "quality_selection", "fullscreen",
    "settings", "unknown",
])

# Propriedades CSS possíveis
css_properties_st = st.fixed_dictionaries({
    "display": st.sampled_from([
        "block", "inline", "flex", "grid", "none", "inline-block",
    ]),
    "visibility": st.sampled_from([
        "visible", "hidden", "collapse",
    ]),
    "opacity": st.floats(
        min_value=0.0, max_value=1.0,
        allow_nan=False, allow_infinity=False,
    ),
    "pointerEvents": st.sampled_from([
        "auto", "none", "all", "inherit",
    ]),
    "cursor": st.sampled_from([
        "pointer", "default", "not-allowed", "grab",
    ]),
    "position": st.sampled_from([
        "static", "relative", "absolute", "fixed", "sticky",
    ]),
    "zIndex": st.sampled_from([
        "auto", "1", "10", "100", "9999",
    ]),
})


@st.composite
def css_evidence_st(draw):
    """Gera uma CSSEvidence com valores aleatórios.

    Gera qualquer combinação possível de propriedades CSS e flags
    para verificar que a confidence nunca excede o limite.
    """
    confidence_raw = draw(st.floats(
        min_value=0.0, max_value=10.0,
        allow_nan=False, allow_infinity=False,
    ))

    return CSSEvidence(
        element_description=draw(
            st.text(min_size=1, max_size=50)
        ),
        capability_hint=draw(capability_hints),
        confidence_contribution=confidence_raw,
        properties=draw(css_properties_st),
        is_visible=draw(st.booleans()),
        is_interactive=draw(st.booleans()),
        has_active_state=draw(st.booleans()),
    )


def build_raw_result(
    is_visible: bool,
    is_interactive: bool,
    has_active_state: bool,
    capability_hint: str,
) -> dict:
    """Constrói um dicionário de resultado cru como os vindos do JS.

    Simula o formato retornado pelo _CSS_ANALYSIS_SCRIPT do browser.
    """
    return {
        "description": "button[role='button']",
        "capabilityHint": capability_hint,
        "properties": {
            "display": "block",
            "visibility": "visible",
            "opacity": 1.0,
            "pointerEvents": "auto",
            "cursor": "pointer",
            "position": "relative",
            "zIndex": "auto",
        },
        "states": {
            "ariaPressed": "true" if has_active_state else None,
            "ariaSelected": None,
            "ariaExpanded": None,
            "ariaChecked": None,
            "dataActive": has_active_state,
            "classList": (
                ["active"] if has_active_state else []
            ),
        },
        "isVisible": is_visible,
        "isInteractive": is_interactive,
        "hasActiveState": has_active_state,
    }


class TestProperty4CSSIsoladoNuncaProduzAltaConfidence:
    """Feature: player-discovery, Property 4: CSS isolado nunca produz
    alta confidence

    Para qualquer capability onde a única evidência é de natureza CSS
    (display, visibility, opacity, pointer-events), a confidence
    resultante deve ser inferior a 0.7 (ou seja, CSS isolado nunca
    classifica uma capability como available).

    **Validates: Requirements 1.5**
    """

    @settings(max_examples=100)
    @given(evidence=css_evidence_st())
    def test_css_evidence_confidence_clamped_to_max(
        self, evidence: CSSEvidence
    ) -> None:
        """CSSEvidence.__post_init__ garante que confidence_contribution
        nunca excede MAX_CSS_ONLY_CONFIDENCE (0.4), que é < 0.7.

        Para qualquer CSSEvidence gerada com confidence_contribution
        arbitrário, o valor resultante após __post_init__ deve ser
        <= MAX_CSS_ONLY_CONFIDENCE.

        **Validates: Requirements 1.5**
        """
        assert evidence.confidence_contribution <= MAX_CSS_ONLY_CONFIDENCE, (
            f"confidence_contribution={evidence.confidence_contribution} "
            f"excede MAX_CSS_ONLY_CONFIDENCE={MAX_CSS_ONLY_CONFIDENCE}"
        )
        assert evidence.confidence_contribution < HIGH_CONFIDENCE_THRESHOLD, (
            f"confidence_contribution={evidence.confidence_contribution} "
            f"atingiu alta confidence (>= {HIGH_CONFIDENCE_THRESHOLD})"
        )

    @settings(max_examples=100)
    @given(
        is_visible=st.booleans(),
        is_interactive=st.booleans(),
        has_active_state=st.booleans(),
        capability_hint=capability_hints,
    )
    def test_calculate_confidence_never_reaches_high(
        self,
        is_visible: bool,
        is_interactive: bool,
        has_active_state: bool,
        capability_hint: str,
    ) -> None:
        """CSSAnalyzer._calculate_confidence() nunca retorna >= 0.7.

        Para qualquer combinação de is_visible, is_interactive,
        has_active_state e capability_hint, o resultado de
        _calculate_confidence() deve ser < 0.7.

        **Validates: Requirements 1.5**
        """
        analyzer = CSSAnalyzer()
        raw_result = build_raw_result(
            is_visible=is_visible,
            is_interactive=is_interactive,
            has_active_state=has_active_state,
            capability_hint=capability_hint,
        )

        confidence = analyzer._calculate_confidence(raw_result)

        assert confidence <= MAX_CSS_ONLY_CONFIDENCE, (
            f"_calculate_confidence retornou {confidence} "
            f"que excede MAX_CSS_ONLY_CONFIDENCE={MAX_CSS_ONLY_CONFIDENCE}"
        )
        assert confidence < HIGH_CONFIDENCE_THRESHOLD, (
            f"_calculate_confidence retornou {confidence} "
            f"que atingiu alta confidence (>= {HIGH_CONFIDENCE_THRESHOLD})"
        )

    @settings(max_examples=100)
    @given(
        is_visible=st.booleans(),
        is_interactive=st.booleans(),
        has_active_state=st.booleans(),
        capability_hint=capability_hints,
    )
    def test_calculate_confidence_is_non_negative(
        self,
        is_visible: bool,
        is_interactive: bool,
        has_active_state: bool,
        capability_hint: str,
    ) -> None:
        """_calculate_confidence() sempre retorna valor >= 0.0.

        Para qualquer combinação de inputs, a confidence calculada
        deve estar no range [0.0, MAX_CSS_ONLY_CONFIDENCE].

        **Validates: Requirements 1.5**
        """
        analyzer = CSSAnalyzer()
        raw_result = build_raw_result(
            is_visible=is_visible,
            is_interactive=is_interactive,
            has_active_state=has_active_state,
            capability_hint=capability_hint,
        )

        confidence = analyzer._calculate_confidence(raw_result)

        assert confidence >= 0.0, (
            f"_calculate_confidence retornou valor negativo: {confidence}"
        )

    @settings(max_examples=100)
    @given(
        confidence_raw=st.floats(
            min_value=0.0, max_value=100.0,
            allow_nan=False, allow_infinity=False,
        ),
    )
    def test_max_css_only_confidence_is_below_threshold(
        self, confidence_raw: float
    ) -> None:
        """MAX_CSS_ONLY_CONFIDENCE garante invariante estrutural.

        Independente do valor de entrada, o clamp por
        MAX_CSS_ONLY_CONFIDENCE (0.4) garante que o resultado final
        é sempre < 0.7 (HIGH_CONFIDENCE_THRESHOLD).

        **Validates: Requirements 1.5**
        """
        # Simula o clamp do __post_init__
        clamped = min(confidence_raw, MAX_CSS_ONLY_CONFIDENCE)

        assert clamped <= MAX_CSS_ONLY_CONFIDENCE
        assert clamped < HIGH_CONFIDENCE_THRESHOLD, (
            f"Valor clamped={clamped} atingiu threshold de alta "
            f"confidence ({HIGH_CONFIDENCE_THRESHOLD}). "
            f"MAX_CSS_ONLY_CONFIDENCE={MAX_CSS_ONLY_CONFIDENCE} "
            f"deveria impedir isso."
        )
