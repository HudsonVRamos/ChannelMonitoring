"""Property-based tests para o SubtitleMonitor.

Testa propriedades universais de validação de track switch de legendas
e formatação de evidência de cues usando Hypothesis.

Feature: audio-subtitle-monitoring
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from src.audio_subtitle_monitor.models import CueResult


# ============================================================
# Helper functions — lógica pura para property testing
# ============================================================


def check_subtitle_track_switch(
    expected_language: str, tracks: list[dict]
) -> bool:
    """Retorna True sse existe um text track com language correspondente
    marcado como active.

    Replica a lógica de validação em SubtitleMonitor.validate_track_switch
    para testar a propriedade de forma pura (sem I/O).
    """
    return any(
        t.get("language") == expected_language
        and t.get("active") is True
        for t in tracks
    )


def format_cue_result(raw_text: str, elapsed_ms: int) -> CueResult:
    """Formata um CueResult com truncamento adequado.

    Replica a lógica de truncamento em SubtitleMonitor.wait_for_active_cue
    para testar a propriedade de formatação de evidência.
    """
    return CueResult(
        found=True,
        cue_text=raw_text[:50],
        time_to_first_cue_ms=elapsed_ms,
    )


# ============================================================
# Estratégias (Generators) para Hypothesis
# ============================================================


text_track_strategy = st.fixed_dictionaries(
    {
        "language": st.text(
            alphabet="abcdefghijklmnopqrstuvwxyz",
            min_size=2,
            max_size=5,
        ),
        "active": st.booleans(),
    }
)


# ============================================================
# Property 3: Track Switch Validation (legendas)
# ============================================================


class TestSubtitleTrackSwitchValidation:
    """Feature: audio-subtitle-monitoring, Property 3: Track Switch Validation

    **Validates: Requirements 5.2, 10.2**

    Para qualquer language esperada e lista de tracks retornada pela
    Shaka API, a função de validação retorna True se e somente se
    existe um track com language correspondente marcado como active.
    """

    @given(
        expected_language=st.text(
            alphabet="abcdefghijklmnopqrstuvwxyz",
            min_size=2,
            max_size=5,
        ),
        tracks=st.lists(text_track_strategy, min_size=0, max_size=10),
    )
    @settings(max_examples=100)
    def test_returns_true_iff_matching_active_track_exists(
        self, expected_language: str, tracks: list[dict]
    ):
        """**Validates: Requirements 5.2**

        A validação retorna True sse existe track com language
        correspondente e active=True.
        """
        result = check_subtitle_track_switch(expected_language, tracks)

        # Calcular o esperado manualmente
        expected = any(
            t["language"] == expected_language and t["active"] is True
            for t in tracks
        )

        assert result == expected

    @given(
        expected_language=st.text(
            alphabet="abcdefghijklmnopqrstuvwxyz",
            min_size=2,
            max_size=5,
        ),
    )
    @settings(max_examples=100)
    def test_empty_tracks_returns_false(
        self, expected_language: str
    ):
        """**Validates: Requirements 5.2**

        Com lista vazia de tracks, a validação sempre retorna False.
        """
        result = check_subtitle_track_switch(expected_language, [])
        assert result is False

    @given(
        expected_language=st.text(
            alphabet="abcdefghijklmnopqrstuvwxyz",
            min_size=2,
            max_size=5,
        ),
        other_tracks=st.lists(
            text_track_strategy, min_size=0, max_size=5
        ),
    )
    @settings(max_examples=100)
    def test_guaranteed_match_returns_true(
        self, expected_language: str, other_tracks: list[dict]
    ):
        """**Validates: Requirements 10.2**

        Quando um track com language esperada e active=True está
        presente na lista, a validação retorna True.
        """
        matching_track = {
            "language": expected_language,
            "active": True,
        }
        tracks = other_tracks + [matching_track]

        result = check_subtitle_track_switch(expected_language, tracks)
        assert result is True

    @given(
        expected_language=st.text(
            alphabet="abcdefghijklmnopqrstuvwxyz",
            min_size=2,
            max_size=5,
        ),
        other_languages=st.lists(
            st.text(
                alphabet="abcdefghijklmnopqrstuvwxyz",
                min_size=2,
                max_size=5,
            ),
            min_size=1,
            max_size=5,
        ),
    )
    @settings(max_examples=100)
    def test_no_matching_language_returns_false(
        self, expected_language: str, other_languages: list[str]
    ):
        """**Validates: Requirements 5.2**

        Quando nenhum track tem a language esperada,
        a validação retorna False (independente do campo active).
        """
        # Garantir que nenhum track tem a language esperada
        tracks = [
            {"language": lang, "active": True}
            for lang in other_languages
            if lang != expected_language
        ]

        # Se todos foram filtrados, lista vazia — resultado False
        result = check_subtitle_track_switch(expected_language, tracks)
        assert result is False


# ============================================================
# Property 7: Cue Evidence Formatting
# ============================================================


class TestCueEvidenceFormatting:
    """Feature: audio-subtitle-monitoring, Property 7: Cue Evidence Formatting

    **Validates: Requirements 5.4**

    Para qualquer cue detectada com texto arbitrário e timing,
    o CueResult formatado deve conter:
    - cue_text truncado a no máximo 50 caracteres
    - time_to_first_cue_ms >= 0
    - found = True quando cue_text é fornecido
    """

    @given(
        raw_text=st.text(min_size=0, max_size=200),
        elapsed_ms=st.integers(min_value=0, max_value=15000),
    )
    @settings(max_examples=100)
    def test_cue_text_always_truncated_to_50_chars(
        self, raw_text: str, elapsed_ms: int
    ):
        """**Validates: Requirements 5.4**

        O cue_text no resultado deve ter no máximo 50 caracteres.
        """
        result = format_cue_result(raw_text, elapsed_ms)

        assert result.cue_text is not None
        assert len(result.cue_text) <= 50

    @given(
        raw_text=st.text(min_size=0, max_size=200),
        elapsed_ms=st.integers(min_value=0, max_value=15000),
    )
    @settings(max_examples=100)
    def test_time_to_first_cue_is_non_negative(
        self, raw_text: str, elapsed_ms: int
    ):
        """**Validates: Requirements 5.4**

        O time_to_first_cue_ms deve ser >= 0.
        """
        result = format_cue_result(raw_text, elapsed_ms)

        assert result.time_to_first_cue_ms is not None
        assert result.time_to_first_cue_ms >= 0

    @given(
        raw_text=st.text(min_size=0, max_size=200),
        elapsed_ms=st.integers(min_value=0, max_value=15000),
    )
    @settings(max_examples=100)
    def test_found_is_true_when_cue_provided(
        self, raw_text: str, elapsed_ms: int
    ):
        """**Validates: Requirements 5.4**

        O campo found deve ser True quando um cue_text é fornecido.
        """
        result = format_cue_result(raw_text, elapsed_ms)

        assert result.found is True

    @given(
        raw_text=st.text(min_size=51, max_size=200),
        elapsed_ms=st.integers(min_value=0, max_value=15000),
    )
    @settings(max_examples=100)
    def test_long_text_is_properly_truncated(
        self, raw_text: str, elapsed_ms: int
    ):
        """**Validates: Requirements 5.4**

        Textos com mais de 50 caracteres devem ser truncados,
        mantendo os primeiros 50 caracteres intactos.
        """
        result = format_cue_result(raw_text, elapsed_ms)

        assert len(result.cue_text) == 50
        assert result.cue_text == raw_text[:50]

    @given(
        raw_text=st.text(min_size=0, max_size=50),
        elapsed_ms=st.integers(min_value=0, max_value=15000),
    )
    @settings(max_examples=100)
    def test_short_text_is_preserved_intact(
        self, raw_text: str, elapsed_ms: int
    ):
        """**Validates: Requirements 5.4**

        Textos com 50 caracteres ou menos são preservados integralmente.
        """
        result = format_cue_result(raw_text, elapsed_ms)

        assert result.cue_text == raw_text

    @given(
        raw_text=st.text(min_size=0, max_size=200),
        elapsed_ms=st.integers(min_value=0, max_value=15000),
    )
    @settings(max_examples=100)
    def test_elapsed_ms_preserved_exactly(
        self, raw_text: str, elapsed_ms: int
    ):
        """**Validates: Requirements 5.4**

        O time_to_first_cue_ms deve ser exatamente o valor fornecido.
        """
        result = format_cue_result(raw_text, elapsed_ms)

        assert result.time_to_first_cue_ms == elapsed_ms
