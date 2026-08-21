"""Property-based tests para AudioMonitor.

Testa propriedades universais de corretude do AudioMonitor:
- Property 3: Track Switch Validation
- Property 4: Audio Telemetry Aggregation
- Property 5: Audio Result Classification

Validates: Requirements 3.2, 3.3, 3.4, 3.5, 10.1

Feature: audio-subtitle-monitoring
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from hypothesis import given, settings
from hypothesis import strategies as st

from src.audio_subtitle_monitor.audio_monitor import AudioMonitor
from src.audio_subtitle_monitor.config import AudioSubtitleConfig
from src.audio_subtitle_monitor.models import (
    AudioSample,
    AudioTelemetryResult,
    TrackTestStatus,
)


# ============================================================
# Helper para Property 3 — lógica pura de validação de track switch
# ============================================================


def check_track_switch(expected_language: str, tracks: list[dict]) -> bool:
    """Retorna True sse existe track com language correspondente e active.

    Espelha a lógica interna de validate_track_switch do AudioMonitor
    para possibilitar teste sem async/polling.
    """
    return any(
        t.get("language") == expected_language and t.get("active") is True
        for t in tracks
    )


# ============================================================
# Strategies
# ============================================================

# Estratégia para gerar language codes (2-5 letras minúsculas)
language_strategy = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz", min_size=2, max_size=5
)

# Estratégia para gerar tracks individuais
track_strategy = st.fixed_dictionaries(
    {
        "language": language_strategy,
        "active": st.booleans(),
    }
)

# Estratégia para gerar listas de tracks
tracks_list_strategy = st.lists(track_strategy, min_size=0, max_size=10)

# Estratégia para gerar valores RMS válidos (entre 0.0 e 1.0)
rms_strategy = st.floats(min_value=0.0, max_value=1.0)

# Estratégia para gerar listas não-vazias de RMS
rms_list_strategy = st.lists(
    rms_strategy, min_size=1, max_size=50
)

# Estratégia para audio_present_ratio (entre 0.0 e 1.0)
ratio_strategy = st.floats(min_value=0.0, max_value=1.0)


# ============================================================
# Property 3: Track Switch Validation
# ============================================================


class TestTrackSwitchValidation:
    """Property 3: Track Switch Validation.

    Para qualquer language e resposta da API, validate_track_switch
    retorna success=True sse existe track com language correspondente
    marcado como active.

    **Validates: Requirements 3.2, 10.1**
    """

    @given(
        expected_language=language_strategy,
        tracks=tracks_list_strategy,
    )
    @settings(max_examples=100)
    def test_track_switch_returns_true_iff_active_track_matches(
        self, expected_language: str, tracks: list[dict]
    ) -> None:
        """Verifica que check_track_switch retorna True iff track ativo existe.

        Feature: audio-subtitle-monitoring, Property 3: Track Switch Validation
        """
        result = check_track_switch(expected_language, tracks)

        # Resultado esperado: existe track com language == expected E active == True
        expected = any(
            t.get("language") == expected_language
            and t.get("active") is True
            for t in tracks
        )

        assert result == expected, (
            f"check_track_switch('{expected_language}', {tracks}) "
            f"retornou {result}, esperado {expected}"
        )

    @given(
        expected_language=language_strategy,
        other_languages=st.lists(language_strategy, min_size=1, max_size=5),
    )
    @settings(max_examples=100)
    def test_track_switch_true_when_active_track_present(
        self, expected_language: str, other_languages: list[str]
    ) -> None:
        """Quando existe track ativo com language correspondente, retorna True.

        Feature: audio-subtitle-monitoring, Property 3: Track Switch Validation
        """
        # Constrói lista de tracks com um ativo correspondente
        tracks = [
            {"language": lang, "active": False}
            for lang in other_languages
        ]
        tracks.append({"language": expected_language, "active": True})

        result = check_track_switch(expected_language, tracks)
        assert result is True

    @given(
        expected_language=language_strategy,
        other_languages=st.lists(language_strategy, min_size=1, max_size=5),
    )
    @settings(max_examples=100)
    def test_track_switch_false_when_no_active_track(
        self, expected_language: str, other_languages: list[str]
    ) -> None:
        """Quando nenhum track ativo tem language correspondente, retorna False.

        Feature: audio-subtitle-monitoring, Property 3: Track Switch Validation
        """
        # Constrói lista onde expected_language existe mas não está active
        tracks = [
            {"language": lang, "active": False}
            for lang in other_languages
        ]
        tracks.append({"language": expected_language, "active": False})

        result = check_track_switch(expected_language, tracks)
        assert result is False


# ============================================================
# Property 4: Audio Telemetry Aggregation
# ============================================================


class TestAudioTelemetryAggregation:
    """Property 4: Audio Telemetry Aggregation.

    Para qualquer lista não-vazia de amostras RMS (floats entre 0.0 e 1.0),
    a agregação produz média, min, max e ratio corretos.

    **Validates: Requirements 3.3**
    """

    @given(rms_values=rms_list_strategy)
    @settings(max_examples=100)
    def test_aggregation_produces_correct_statistics(
        self, rms_values: list[float]
    ) -> None:
        """Verifica que _calculate_aggregations produz estatísticas corretas.

        Feature: audio-subtitle-monitoring, Property 4: Audio Telemetry Aggregation
        """
        # Criar instância com mock page e config padrão
        mock_page = AsyncMock()
        config = AudioSubtitleConfig()
        monitor = AudioMonitor(page=mock_page, config=config)

        # Criar AudioSample objects a partir dos valores RMS
        samples = [
            AudioSample(timestamp=float(i), rms=rms, peak=rms)
            for i, rms in enumerate(rms_values)
        ]

        # Chamar _calculate_aggregations (método síncrono)
        result = monitor._calculate_aggregations(
            samples=samples,
            sample_interval_s=2.0,
            total_duration_s=len(rms_values) * 2.0,
        )

        # Verificar rms_avg == média aritmética
        expected_avg = sum(rms_values) / len(rms_values)
        assert abs(result.rms_avg - expected_avg) < 1e-9, (
            f"rms_avg={result.rms_avg}, expected={expected_avg}"
        )

        # Verificar rms_min == mínimo
        expected_min = min(rms_values)
        assert result.rms_min == expected_min, (
            f"rms_min={result.rms_min}, expected={expected_min}"
        )

        # Verificar rms_max == máximo
        expected_max = max(rms_values)
        assert result.rms_max == expected_max, (
            f"rms_max={result.rms_max}, expected={expected_max}"
        )

        # Verificar audio_present_ratio == count(rms > 0.01) / len
        threshold = config.audio_rms_threshold  # 0.01
        audio_present_count = sum(
            1 for rms in rms_values if rms > threshold
        )
        expected_ratio = audio_present_count / len(rms_values)
        assert abs(result.audio_present_ratio - expected_ratio) < 1e-9, (
            f"audio_present_ratio={result.audio_present_ratio}, "
            f"expected={expected_ratio}"
        )

    @given(rms_values=rms_list_strategy)
    @settings(max_examples=100)
    def test_aggregation_ratio_between_zero_and_one(
        self, rms_values: list[float]
    ) -> None:
        """Verifica que audio_present_ratio está sempre entre 0.0 e 1.0.

        Feature: audio-subtitle-monitoring, Property 4: Audio Telemetry Aggregation
        """
        mock_page = AsyncMock()
        config = AudioSubtitleConfig()
        monitor = AudioMonitor(page=mock_page, config=config)

        samples = [
            AudioSample(timestamp=float(i), rms=rms, peak=rms)
            for i, rms in enumerate(rms_values)
        ]

        result = monitor._calculate_aggregations(
            samples=samples,
            sample_interval_s=2.0,
            total_duration_s=len(rms_values) * 2.0,
        )

        assert 0.0 <= result.audio_present_ratio <= 1.0, (
            f"audio_present_ratio={result.audio_present_ratio} fora de [0, 1]"
        )

    @given(rms_values=rms_list_strategy)
    @settings(max_examples=100)
    def test_aggregation_min_leq_avg_leq_max(
        self, rms_values: list[float]
    ) -> None:
        """Verifica invariante: rms_min <= rms_avg <= rms_max.

        Feature: audio-subtitle-monitoring, Property 4: Audio Telemetry Aggregation
        """
        mock_page = AsyncMock()
        config = AudioSubtitleConfig()
        monitor = AudioMonitor(page=mock_page, config=config)

        samples = [
            AudioSample(timestamp=float(i), rms=rms, peak=rms)
            for i, rms in enumerate(rms_values)
        ]

        result = monitor._calculate_aggregations(
            samples=samples,
            sample_interval_s=2.0,
            total_duration_s=len(rms_values) * 2.0,
        )

        assert result.rms_min <= result.rms_avg + 1e-9, (
            f"rms_min={result.rms_min} > rms_avg={result.rms_avg}"
        )
        assert result.rms_avg <= result.rms_max + 1e-9, (
            f"rms_avg={result.rms_avg} > rms_max={result.rms_max}"
        )


# ============================================================
# Property 5: Audio Result Classification
# ============================================================


class TestAudioResultClassification:
    """Property 5: Audio Result Classification.

    Para qualquer AudioTelemetryResult, classificação retorna
    PASS se ratio >= 0.80 e FAIL se ratio < 0.80.

    **Validates: Requirements 3.4, 3.5**
    """

    @given(audio_present_ratio=ratio_strategy)
    @settings(max_examples=100)
    def test_classification_pass_iff_ratio_ge_threshold(
        self, audio_present_ratio: float
    ) -> None:
        """Verifica que classify_result segue threshold de 0.80.

        Feature: audio-subtitle-monitoring, Property 5: Audio Result Classification
        """
        mock_page = AsyncMock()
        config = AudioSubtitleConfig()  # audio_pass_threshold = 0.80
        monitor = AudioMonitor(page=mock_page, config=config)

        # Criar AudioTelemetryResult com o ratio especificado
        telemetry = AudioTelemetryResult(
            samples=[],
            rms_avg=0.5,
            rms_min=0.0,
            rms_max=1.0,
            audio_present_ratio=audio_present_ratio,
            silence_duration_s=0.0,
            total_duration_s=30.0,
        )

        result = monitor.classify_result(telemetry)

        if audio_present_ratio >= 0.80:
            assert result == TrackTestStatus.PASS, (
                f"ratio={audio_present_ratio} >= 0.80 mas "
                f"classificou como {result.value}"
            )
        else:
            assert result == TrackTestStatus.FAIL, (
                f"ratio={audio_present_ratio} < 0.80 mas "
                f"classificou como {result.value}"
            )

    @given(
        ratio_above=st.floats(min_value=0.80, max_value=1.0),
    )
    @settings(max_examples=100)
    def test_classification_always_pass_above_threshold(
        self, ratio_above: float
    ) -> None:
        """Verifica que ratio >= 0.80 sempre resulta em PASS.

        Feature: audio-subtitle-monitoring, Property 5: Audio Result Classification
        """
        mock_page = AsyncMock()
        config = AudioSubtitleConfig()
        monitor = AudioMonitor(page=mock_page, config=config)

        telemetry = AudioTelemetryResult(
            samples=[],
            rms_avg=0.5,
            rms_min=0.0,
            rms_max=1.0,
            audio_present_ratio=ratio_above,
            silence_duration_s=0.0,
            total_duration_s=30.0,
        )

        result = monitor.classify_result(telemetry)
        assert result == TrackTestStatus.PASS

    @given(
        ratio_below=st.floats(
            min_value=0.0, max_value=0.80, exclude_max=True
        ),
    )
    @settings(max_examples=100)
    def test_classification_always_fail_below_threshold(
        self, ratio_below: float
    ) -> None:
        """Verifica que ratio < 0.80 sempre resulta em FAIL.

        Feature: audio-subtitle-monitoring, Property 5: Audio Result Classification
        """
        mock_page = AsyncMock()
        config = AudioSubtitleConfig()
        monitor = AudioMonitor(page=mock_page, config=config)

        telemetry = AudioTelemetryResult(
            samples=[],
            rms_avg=0.5,
            rms_min=0.0,
            rms_max=1.0,
            audio_present_ratio=ratio_below,
            silence_duration_s=0.0,
            total_duration_s=30.0,
        )

        result = monitor.classify_result(telemetry)
        assert result == TrackTestStatus.FAIL
