"""Property-based tests para VideoTelemetryCollector.

Valida propriedades de corretude da coleta de telemetria de vídeo,
incluindo detecção de freeze e correlação de anotações com track switches.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from src.unified_channel_monitor.config import UnifiedMonitorConfig
from src.unified_channel_monitor.models import FreezeEvent
from src.unified_channel_monitor.video_telemetry import (
    VideoTelemetryCollector,
)


# ============================================================
# Estratégias Hypothesis
# ============================================================

# Tipos de track válidos conforme o design
_track_types = st.sampled_from(["audio", "subtitle"])

# Nomes de track não-vazios
_track_names = st.text(min_size=1, max_size=50).filter(
    lambda s: s.strip() != ""
)

# Timestamps ISO format
_iso_timestamps = st.builds(
    lambda y, m, d, h, mi, s: (
        f"{y:04d}-{m:02d}-{d:02d}T{h:02d}:{mi:02d}:{s:02d}Z"
    ),
    y=st.integers(min_value=2020, max_value=2030),
    m=st.integers(min_value=1, max_value=12),
    d=st.integers(min_value=1, max_value=28),
    h=st.integers(min_value=0, max_value=23),
    mi=st.integers(min_value=0, max_value=59),
    s=st.integers(min_value=0, max_value=59),
)

# Estratégia para gerar contexto de track switch
_track_switch_context = st.fixed_dictionaries({
    "track_name": _track_names,
    "track_type": _track_types,
    "switch_timestamp": _iso_timestamps,
})


# ============================================================
# Helpers
# ============================================================


def _make_mock_page_with_metrics(metrics_sequence: list[dict]) -> AsyncMock:
    """Cria mock Page que retorna métricas em sequência.

    Args:
        metrics_sequence: Lista de dicts com métricas JS a retornar
            em chamadas consecutivas a page.evaluate().

    Returns:
        Mock de Page configurado.
    """
    page = AsyncMock()
    page.evaluate = AsyncMock(side_effect=metrics_sequence)
    return page


def _freeze_metrics(
    num_samples: int,
    stalled_frames: int = 1000,
    current_time: float = 10.0,
) -> list[dict]:
    """Gera sequência de métricas que produz freeze.

    Freeze ocorre quando 3+ amostras consecutivas têm
    total_frames_decoded sem avanço.

    Args:
        num_samples: Número de amostras a gerar.
        stalled_frames: Valor fixo de totalFramesDecoded.
        current_time: Valor fixo de currentTime.

    Returns:
        Lista de dicts de métricas JS simuladas.
    """
    return [
        {
            "currentTime": current_time,
            "totalFramesDecoded": stalled_frames,
            "framesDropped": 0,
            "bufferAhead": 5.0,  # buffer OK
            "readyState": 4,
        }
        for _ in range(num_samples)
    ]


def _buffer_underrun_metrics(
    buffer_ahead: float = 0.3,
    advancing_start: int = 1000,
) -> list[dict]:
    """Gera uma amostra com buffer underrun (< 0.5s).

    Frames avançam para não disparar freeze, mas buffer está baixo.

    Args:
        buffer_ahead: Valor de buffer abaixo do limiar (0.5s).
        advancing_start: Valor base de totalFramesDecoded.

    Returns:
        Lista com 1 dict de métricas.
    """
    return [
        {
            "currentTime": 10.0 + i * 2.0,
            "totalFramesDecoded": advancing_start + (i * 50),
            "framesDropped": 0,
            "bufferAhead": buffer_ahead,
            "readyState": 4,
        }
        for i in range(1)
    ]


# ============================================================
# Feature: unified-channel-monitor, Property 11: Telemetry annotation correlates freeze with track switch  # noqa: E501
# ============================================================


class TestPropertyTelemetryAnnotation:
    """Property 11: Telemetry annotation correlates freeze with track switch.

    Para qualquer TelemetrySample onde um FreezeEvent ou buffer underrun
    é detectado E um track switch está em andamento, a amostra DEVE ter
    uma annotation não-nula contendo o contexto de track switch
    (track_name, track_type, switch_timestamp).

    **Validates: Requirements 4.5, 8.5**
    """

    @given(context=_track_switch_context)
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_freeze_with_annotation_contains_track_switch_context(
        self, context: dict
    ) -> None:
        """Amostra com freeze detectado durante track switch tem annotation
        com campos do contexto (track_name, track_type, switch_timestamp).

        **Validates: Requirements 4.5, 8.5**
        """
        # Gera 3 amostras com frames estagnados → freeze na 3ª amostra
        # A annotation é definida ANTES de coletar a 3ª amostra
        # (a que dispara o freeze)
        freeze_metrics = _freeze_metrics(num_samples=4)
        page = _make_mock_page_with_metrics(freeze_metrics)

        config = UnifiedMonitorConfig()
        collector = VideoTelemetryCollector(config=config)

        # Inicia coleta manualmente (sem o loop, controlamos as amostras)
        collector._page = page
        collector._running = True
        collector._start_time = datetime.now(timezone.utc).isoformat()

        # Coleta 2 amostras iniciais (sem annotation ainda)
        await collector._collect_sample()
        await collector._collect_sample()

        # Agora simula track switch em andamento — anota próxima amostra
        collector.annotate_current_sample(context)

        # Coleta a 3ª amostra — esta deve disparar freeze E ter annotation
        await collector._collect_sample()

        # Verifica que a 3ª amostra (índice 2) tem annotation não-nula
        sample = collector.samples[2]
        assert sample.annotation is not None, (
            "Amostra com freeze durante track switch deve ter "
            "annotation não-nula"
        )

        # Verifica campos obrigatórios do contexto de track switch
        assert "track_name" in sample.annotation
        assert "track_type" in sample.annotation
        assert "switch_timestamp" in sample.annotation

        # Verifica que os valores correspondem ao contexto fornecido
        assert sample.annotation["track_name"] == context["track_name"]
        assert sample.annotation["track_type"] == context["track_type"]
        assert (
            sample.annotation["switch_timestamp"]
            == context["switch_timestamp"]
        )

    @given(context=_track_switch_context)
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_buffer_underrun_with_annotation_contains_track_switch_context(
        self, context: dict
    ) -> None:
        """Amostra com buffer underrun durante track switch tem annotation
        com campos do contexto (track_name, track_type, switch_timestamp).

        **Validates: Requirements 4.5, 8.5**
        """
        # Gera amostras com frames avançando (sem freeze) mas buffer baixo
        # Primeira amostra com buffer normal para dar baseline
        metrics_sequence = [
            {
                "currentTime": 10.0,
                "totalFramesDecoded": 1000,
                "framesDropped": 0,
                "bufferAhead": 5.0,
                "readyState": 4,
            },
            {
                "currentTime": 12.0,
                "totalFramesDecoded": 1050,
                "framesDropped": 0,
                "bufferAhead": 0.3,  # buffer underrun < 0.5
                "readyState": 4,
            },
        ]
        page = _make_mock_page_with_metrics(metrics_sequence)

        config = UnifiedMonitorConfig()
        collector = VideoTelemetryCollector(config=config)

        # Configura manualmente
        collector._page = page
        collector._running = True
        collector._start_time = datetime.now(timezone.utc).isoformat()

        # Coleta primeira amostra (baseline)
        await collector._collect_sample()

        # Anota próxima amostra com contexto de track switch
        collector.annotate_current_sample(context)

        # Coleta segunda amostra — buffer underrun com annotation
        await collector._collect_sample()

        # Verifica que a 2ª amostra (índice 1) tem annotation não-nula
        sample = collector.samples[1]
        assert sample.annotation is not None, (
            "Amostra com buffer underrun durante track switch deve "
            "ter annotation não-nula"
        )

        # Verifica campos obrigatórios do contexto
        assert "track_name" in sample.annotation
        assert "track_type" in sample.annotation
        assert "switch_timestamp" in sample.annotation

        # Verifica que os valores correspondem ao contexto fornecido
        assert sample.annotation["track_name"] == context["track_name"]
        assert sample.annotation["track_type"] == context["track_type"]
        assert (
            sample.annotation["switch_timestamp"]
            == context["switch_timestamp"]
        )

    @given(context=_track_switch_context)
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_annotation_consumed_after_single_sample(
        self, context: dict
    ) -> None:
        """Annotation é consumida após uma única amostra — amostras
        subsequentes sem nova anotação devem ter annotation=None.

        **Validates: Requirements 4.5, 8.5**
        """
        metrics_sequence = [
            {
                "currentTime": 10.0 + i * 2.0,
                "totalFramesDecoded": 1000 + i * 50,
                "framesDropped": 0,
                "bufferAhead": 5.0,
                "readyState": 4,
            }
            for i in range(3)
        ]
        page = _make_mock_page_with_metrics(metrics_sequence)

        config = UnifiedMonitorConfig()
        collector = VideoTelemetryCollector(config=config)

        collector._page = page
        collector._running = True
        collector._start_time = datetime.now(timezone.utc).isoformat()

        # Anota antes da primeira coleta
        collector.annotate_current_sample(context)

        # Coleta 3 amostras
        await collector._collect_sample()
        await collector._collect_sample()
        await collector._collect_sample()

        # Primeira amostra tem annotation
        assert collector.samples[0].annotation is not None
        assert collector.samples[0].annotation == context

        # Amostras subsequentes não têm annotation (consumida)
        assert collector.samples[1].annotation is None
        assert collector.samples[2].annotation is None



# ============================================================
# Feature: unified-channel-monitor, Property 5: Freeze detection on consecutive non-advancing samples  # noqa: E501
# ============================================================


# --- Helpers para Property 5 ---


def _make_metrics_p5(total_frames_decoded: int) -> dict:
    """Cria dict de métricas como retornado por page.evaluate()."""
    return {
        "currentTime": 10.0,
        "totalFramesDecoded": total_frames_decoded,
        "framesDropped": 0,
        "bufferAhead": 5.0,
        "readyState": 4,
    }


async def _feed_samples_p5(
    collector: VideoTelemetryCollector,
    frame_values: list[int],
) -> None:
    """Alimenta o collector com sequência de amostras mockadas.

    Configura page.evaluate para retornar métricas com os
    total_frames_decoded fornecidos, e chama _collect_sample
    para cada valor.
    """
    page = AsyncMock()
    collector._page = page

    for frames in frame_values:
        page.evaluate = AsyncMock(
            return_value=_make_metrics_p5(frames)
        )
        await collector._collect_sample()


def _has_consecutive_run(
    values: list[int], run_length: int
) -> bool:
    """Verifica se existe subsequência de run_length valores iguais."""
    if len(values) < run_length:
        return False
    count = 1
    for i in range(1, len(values)):
        if values[i] == values[i - 1]:
            count += 1
            if count >= run_length:
                return True
        else:
            count = 1
    return False


# --- Estratégias para Property 5 ---


@st.composite
def frames_with_freeze(draw):
    """Gera sequência com 3+ amostras consecutivas iguais (freeze).

    Estratégia:
    - Gera prefixo de frames crescentes (0-5 amostras)
    - Insere bloco de 3+ amostras com mesmo valor
    - Gera sufixo opcional de frames crescentes
    """
    # Prefixo: frames crescentes
    prefix_len = draw(st.integers(min_value=0, max_value=5))
    base_value = draw(st.integers(min_value=0, max_value=10000))

    prefix = []
    current = base_value
    for _ in range(prefix_len):
        current += draw(st.integers(min_value=1, max_value=100))
        prefix.append(current)

    # Bloco de freeze: 3+ amostras com mesmo valor
    freeze_length = draw(st.integers(min_value=3, max_value=8))
    freeze_value = current if not prefix else prefix[-1]
    if not prefix:
        freeze_value = base_value
    freeze_block = [freeze_value] * freeze_length

    # Sufixo: frames crescentes (opcional)
    suffix_len = draw(st.integers(min_value=0, max_value=3))
    suffix = []
    current = freeze_value
    for _ in range(suffix_len):
        current += draw(st.integers(min_value=1, max_value=100))
        suffix.append(current)

    return prefix + freeze_block + suffix


@st.composite
def frames_without_freeze(draw):
    """Gera sequência sem 3+ amostras consecutivas iguais (sem freeze).

    Estratégia:
    - Gera lista onde no máximo 2 consecutivos possuem mesmo valor,
      forçando incremento no terceiro.
    """
    length = draw(st.integers(min_value=3, max_value=20))
    base_value = draw(st.integers(min_value=0, max_value=10000))

    values = [base_value]
    consecutive_same = 1

    for _ in range(length - 1):
        if consecutive_same >= 2:
            # Deve incrementar para evitar run de 3
            increment = draw(
                st.integers(min_value=1, max_value=100)
            )
            new_val = values[-1] + increment
            values.append(new_val)
            consecutive_same = 1
        else:
            # Pode ficar igual ou incrementar
            should_stay = draw(st.booleans())
            if should_stay:
                values.append(values[-1])
                consecutive_same += 1
            else:
                increment = draw(
                    st.integers(min_value=1, max_value=100)
                )
                new_val = values[-1] + increment
                values.append(new_val)
                consecutive_same = 1

    return values


# --- Property 5 Tests ---


class TestPropertyFreezeDetection:
    """Property 5: Freeze detection on consecutive non-advancing samples.

    Para qualquer sequência de TelemetrySamples:
    - Se existem 3+ amostras consecutivas com total_frames_decoded
      sem avanço, pelo menos um FreezeEvent deve ser flagrado.
    - Se nenhuma tal subsequência existe, nenhum FreezeEvent deve
      ser flagrado.

    **Validates: Requirements 4.4**
    """

    @given(frame_values=frames_with_freeze())
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_freeze_detected_with_consecutive_stalled(
        self,
        frame_values: list[int],
    ) -> None:
        """Sequências com 3+ amostras consecutivas iguais DEVEM
        gerar pelo menos um FreezeEvent.

        **Validates: Requirements 4.4**
        """
        # Pré-condição: confirma que há run de 3+
        assume(_has_consecutive_run(frame_values, 3))

        config = UnifiedMonitorConfig()
        collector = VideoTelemetryCollector(config=config)

        await _feed_samples_p5(collector, frame_values)

        # Deve ter pelo menos um FreezeEvent
        assert len(collector._freeze_events) >= 1, (
            f"Esperava pelo menos 1 FreezeEvent para "
            f"frame_values={frame_values}, "
            f"mas obteve {len(collector._freeze_events)}"
        )

        # Verifica que FreezeEvents são instâncias corretas
        for event in collector._freeze_events:
            assert isinstance(event, FreezeEvent)
            assert event.duration_samples >= 3

    @given(frame_values=frames_without_freeze())
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_no_freeze_without_consecutive_stalled(
        self,
        frame_values: list[int],
    ) -> None:
        """Sequências sem 3+ amostras consecutivas iguais NÃO DEVEM
        gerar nenhum FreezeEvent.

        **Validates: Requirements 4.4**
        """
        # Pré-condição: confirma que NÃO há run de 3+
        assume(not _has_consecutive_run(frame_values, 3))

        config = UnifiedMonitorConfig()
        collector = VideoTelemetryCollector(config=config)

        await _feed_samples_p5(collector, frame_values)

        # Não deve ter nenhum FreezeEvent
        assert len(collector._freeze_events) == 0, (
            f"Não esperava FreezeEvent para "
            f"frame_values={frame_values}, "
            f"mas obteve {len(collector._freeze_events)}"
        )

        # Nenhuma amostra marcada como freeze
        for sample in collector._samples:
            assert sample.is_freeze is False, (
                f"Amostra marcada como freeze: "
                f"total_frames_decoded="
                f"{sample.total_frames_decoded}"
            )
