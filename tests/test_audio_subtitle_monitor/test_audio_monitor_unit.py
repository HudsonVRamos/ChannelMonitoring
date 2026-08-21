"""Unit tests para AudioMonitor.

Testa cenários específicos e edge cases para:
- validate_track_switch: track encontrado/não encontrado, single track
- classify_result: boundary cases (80%, 79%, 81%, 0%, 100%)
- collect_telemetry: com amostras mockadas e falha de AudioContext

Requirements: 3.2, 3.3, 3.4, 3.5, 3.6
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from src.audio_subtitle_monitor.audio_monitor import AudioMonitor
from src.audio_subtitle_monitor.config import AudioSubtitleConfig
from src.audio_subtitle_monitor.models import (
    AudioSample,
    AudioTelemetryResult,
    TrackTestStatus,
)


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def config():
    """Configuração padrão para testes do AudioMonitor."""
    return AudioSubtitleConfig(channels=[])


@pytest.fixture
def audio_monitor(mock_page, config):
    """Instância do AudioMonitor com page mockado."""
    return AudioMonitor(page=mock_page, config=config)


# ============================================================
# Testes: validate_track_switch
# ============================================================


class TestValidateTrackSwitch:
    """Testes para o método validate_track_switch."""

    @pytest.mark.asyncio
    async def test_track_found(self, audio_monitor):
        """Track com idioma esperado está ativo → success=True.

        Req 3.2: Verificar via Shaka API que o track ativo mudou
        para o idioma selecionado.
        """
        audio_monitor._page.evaluate = AsyncMock(
            return_value=[
                {"language": "por", "active": True, "label": "Português"},
                {"language": "eng", "active": False, "label": "English"},
            ]
        )

        result = await audio_monitor.validate_track_switch(
            "por", timeout_s=1.0
        )

        assert result.success is True
        assert result.actual_active_language == "por"
        assert result.expected_language == "por"
        assert result.error is None

    @pytest.mark.asyncio
    async def test_track_not_found(self, audio_monitor):
        """Track com idioma esperado NÃO está ativo → success=False.

        Req 3.6: Se a mudança não for confirmada dentro de 5s,
        classificar como FAIL com evidence "track_switch_not_confirmed".
        """
        audio_monitor._page.evaluate = AsyncMock(
            return_value=[
                {"language": "por", "active": True, "label": "Português"},
                {"language": "eng", "active": False, "label": "English"},
            ]
        )

        result = await audio_monitor.validate_track_switch(
            "eng", timeout_s=0.6
        )

        assert result.success is False
        assert result.actual_active_language == "por"
        assert result.expected_language == "eng"
        assert result.error == "track_switch_not_confirmed"

    @pytest.mark.asyncio
    async def test_single_track(self, audio_monitor):
        """Canal com apenas 1 track de áudio — valida corretamente.

        Req 3.2: Mesmo com um único track disponível, a validação
        deve confirmar se ele está ativo.
        """
        audio_monitor._page.evaluate = AsyncMock(
            return_value=[
                {"language": "por", "active": True, "label": "Português"},
            ]
        )

        result = await audio_monitor.validate_track_switch(
            "por", timeout_s=1.0
        )

        assert result.success is True
        assert result.actual_active_language == "por"
        assert len(result.api_tracks) == 1


# ============================================================
# Testes: classify_result
# ============================================================


class TestClassifyResult:
    """Testes para o método classify_result com boundary cases.

    Req 3.4: PASS se audio_present_ratio >= 0.80
    Req 3.5: FAIL se audio_present_ratio < 0.80
    """

    def test_exactly_80_percent(self, audio_monitor):
        """audio_present_ratio=0.80 → PASS (boundary exato)."""
        telemetry = AudioTelemetryResult(
            samples=[],
            rms_avg=0.05,
            rms_min=0.01,
            rms_max=0.1,
            audio_present_ratio=0.80,
            silence_duration_s=6.0,
            total_duration_s=30.0,
        )

        result = audio_monitor.classify_result(telemetry)

        assert result == TrackTestStatus.PASS

    def test_79_percent(self, audio_monitor):
        """audio_present_ratio=0.79 → FAIL (abaixo do threshold)."""
        telemetry = AudioTelemetryResult(
            samples=[],
            rms_avg=0.04,
            rms_min=0.0,
            rms_max=0.1,
            audio_present_ratio=0.79,
            silence_duration_s=6.3,
            total_duration_s=30.0,
        )

        result = audio_monitor.classify_result(telemetry)

        assert result == TrackTestStatus.FAIL

    def test_81_percent(self, audio_monitor):
        """audio_present_ratio=0.81 → PASS (acima do threshold)."""
        telemetry = AudioTelemetryResult(
            samples=[],
            rms_avg=0.06,
            rms_min=0.02,
            rms_max=0.12,
            audio_present_ratio=0.81,
            silence_duration_s=5.7,
            total_duration_s=30.0,
        )

        result = audio_monitor.classify_result(telemetry)

        assert result == TrackTestStatus.PASS

    def test_zero_ratio(self, audio_monitor):
        """audio_present_ratio=0.0 → FAIL (sem áudio)."""
        telemetry = AudioTelemetryResult(
            samples=[],
            rms_avg=0.0,
            rms_min=0.0,
            rms_max=0.0,
            audio_present_ratio=0.0,
            silence_duration_s=30.0,
            total_duration_s=30.0,
        )

        result = audio_monitor.classify_result(telemetry)

        assert result == TrackTestStatus.FAIL

    def test_100_percent(self, audio_monitor):
        """audio_present_ratio=1.0 → PASS (áudio em todas amostras)."""
        telemetry = AudioTelemetryResult(
            samples=[],
            rms_avg=0.08,
            rms_min=0.03,
            rms_max=0.15,
            audio_present_ratio=1.0,
            silence_duration_s=0.0,
            total_duration_s=30.0,
        )

        result = audio_monitor.classify_result(telemetry)

        assert result == TrackTestStatus.PASS


# ============================================================
# Testes: collect_telemetry
# ============================================================


class TestCollectTelemetry:
    """Testes para o método collect_telemetry."""

    @pytest.mark.asyncio
    async def test_audio_context_fail(self, audio_monitor):
        """AudioContext não inicializa → retorna telemetria vazia.

        Req 3.3: Se o AudioContext falhar, telemetria indica
        ausência total de áudio.
        """
        # Mock _init_audio_context para retornar False
        with patch.object(
            audio_monitor,
            "_init_audio_context",
            new_callable=AsyncMock,
            return_value=False,
        ):
            result = await audio_monitor.collect_telemetry(
                duration_s=1.0, sample_interval_s=0.5
            )

        assert result.samples == []
        assert result.rms_avg == 0.0
        assert result.rms_min == 0.0
        assert result.rms_max == 0.0
        assert result.audio_present_ratio == 0.0
        assert result.silence_duration_s == 1.0
        assert result.total_duration_s == 1.0

    @pytest.mark.asyncio
    async def test_with_samples(self, audio_monitor):
        """collect_telemetry com amostras mockadas → agregações corretas.

        Req 3.3: Coletar telemetria durante janela, registrando
        RMS médio, mínimo, máximo e presença de áudio.
        """
        # Amostras simuladas: 3 com áudio, 1 silenciosa
        mock_samples = [
            AudioSample(timestamp=0.0, rms=0.05, peak=0.1),
            AudioSample(timestamp=0.5, rms=0.03, peak=0.08),
            AudioSample(timestamp=1.0, rms=0.005, peak=0.01),  # silêncio
            AudioSample(timestamp=1.5, rms=0.07, peak=0.12),
        ]
        sample_iter = iter(mock_samples)

        async def mock_collect_single():
            return next(sample_iter)

        with patch.object(
            audio_monitor,
            "_init_audio_context",
            new_callable=AsyncMock,
            return_value=True,
        ), patch.object(
            audio_monitor,
            "_collect_single_sample",
            side_effect=mock_collect_single,
        ):
            result = await audio_monitor.collect_telemetry(
                duration_s=1.0, sample_interval_s=0.3
            )

        # Verifica que coletou amostras
        assert len(result.samples) > 0
        # RMS avg é a média dos valores coletados
        rms_values = [s.rms for s in result.samples]
        expected_avg = sum(rms_values) / len(rms_values)
        assert abs(result.rms_avg - expected_avg) < 1e-9
        # Min e Max
        assert result.rms_min == min(rms_values)
        assert result.rms_max == max(rms_values)
