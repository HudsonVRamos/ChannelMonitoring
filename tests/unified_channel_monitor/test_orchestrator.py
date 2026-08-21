"""Property-based tests para UnifiedOrchestrator.

Valida propriedades de processamento sequencial com resiliência
e reuso de CapabilityMap (discovery única enquanto válido).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from src.unified_channel_monitor.config import UnifiedMonitorConfig
from src.unified_channel_monitor.models import (
    ChannelSessionStatus,
    ConsolidatedReport,
    TelemetrySummary,
    UnifiedChannelReport,
)
from src.unified_channel_monitor.orchestrator import UnifiedOrchestrator


# ============================================================
# Helpers
# ============================================================


def _make_channel_url(index: int) -> str:
    """Gera URL de canal fictícia para testes."""
    return f"https://channel-{index}.example.com/live"


def _create_mock_report(
    channel_url: str, status: str = "PASS"
) -> UnifiedChannelReport:
    """Cria um UnifiedChannelReport mock para testes."""
    return UnifiedChannelReport(
        channel_url=channel_url,
        channel_id=f"channel-{hash(channel_url) % 1000}",
        session_id="test-session-id",
        timestamp="2024-01-01T00:00:00Z",
        status=status,
        duration_ms=1000,
        video_summary=TelemetrySummary(total_samples=10),
        audio_tracks_tested=1,
        audio_tracks_passed=1,
        audio_results=[],
        subtitle_tracks_tested=1,
        subtitle_tracks_passed=1,
        subtitle_results=[],
        escalation_results=[],
        telemetry_annotations=[],
        errors=[],
    )


# ============================================================
# Feature: unified-channel-monitor, Property 4: Discovery
# executes once while CapabilityMap is valid
# ============================================================


class TestPropertyDiscoveryOnce:
    """Property 4: Discovery executes once while CapabilityMap is valid.

    Para qualquer sequência de K sessões de canal bem-sucedidas (K >= 1),
    o DiscoveryEngine SHALL ser invocado exatamente uma vez. Se falhas
    consecutivas atingirem o threshold T configurado, re-discovery
    SHALL ser disparado exatamente uma vez por breach do threshold.

    **Validates: Requirements 3.2, 3.3**
    """

    @given(
        k=st.integers(min_value=1, max_value=15),
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_discovery_called_once_for_successful_channels(
        self, k: int
    ) -> None:
        """Para K canais bem-sucedidos, discovery executa exatamente 1 vez.

        **Validates: Requirements 3.2, 3.3**
        """
        # Setup: criar mock page e config
        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.wait_for_selector = AsyncMock()
        mock_page.evaluate = AsyncMock(return_value=False)

        config = UnifiedMonitorConfig(
            invalidation_threshold=3,
            output_dir="/tmp/test_reports",
        )

        orchestrator = UnifiedOrchestrator(
            page=mock_page, config=config
        )

        # Mock _run_discovery para rastrear call count
        discovery_result = {"player_type": "shaka", "video": "video"}
        orchestrator._run_discovery = AsyncMock(
            return_value=discovery_result
        )

        # Mock _run_channel_session para sempre ter sucesso
        channels = [_make_channel_url(i) for i in range(k)]

        async def mock_channel_session(url: str):
            """Simula sessão bem-sucedida que usa _ensure_capability_map."""
            # Forçar chamada ao _ensure_capability_map real
            await orchestrator._ensure_capability_map("test-session")
            return _create_mock_report(url, status="PASS")

        orchestrator._run_channel_session = AsyncMock(
            side_effect=mock_channel_session
        )

        # Mock report generator para não precisar de I/O
        orchestrator._report_generator = MagicMock()
        orchestrator._report_generator.create_consolidated_report = (
            MagicMock(
                return_value=ConsolidatedReport(
                    timestamp="2024-01-01T00:00:00Z",
                    total_channels=k,
                    channels_pass=k,
                )
            )
        )
        orchestrator._report_generator.persist_report = MagicMock()

        # Executar rotação
        await orchestrator.run_single_rotation(channels)

        # Verificar: _run_discovery chamado exatamente 1 vez
        assert orchestrator._run_discovery.call_count == 1, (
            f"Para {k} canais bem-sucedidos, discovery deveria ser "
            f"chamado 1 vez, mas foi chamado "
            f"{orchestrator._run_discovery.call_count} vezes"
        )

    @given(
        t=st.integers(min_value=2, max_value=5),
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_rediscovery_after_threshold_breach(
        self, t: int
    ) -> None:
        """Após T falhas consecutivas + 1 sucesso, discovery = 2 vezes.

        Sequência: 1 sucesso (discovery inicial) + T falhas (invalida
        capability map) + 1 sucesso (re-discovery).
        Total de discovery calls: exatamente 2.

        **Validates: Requirements 3.2, 3.3**
        """
        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.wait_for_selector = AsyncMock()
        mock_page.evaluate = AsyncMock(return_value=False)

        config = UnifiedMonitorConfig(
            invalidation_threshold=t,
            output_dir="/tmp/test_reports",
        )

        orchestrator = UnifiedOrchestrator(
            page=mock_page, config=config
        )

        # Mock _run_discovery para rastrear call count
        discovery_result = {"player_type": "shaka", "video": "video"}
        orchestrator._run_discovery = AsyncMock(
            return_value=discovery_result
        )

        # Construir sequência: 1 sucesso + T falhas + 1 sucesso
        # Total de canais: 1 + T + 1
        total_channels = 1 + t + 1
        channels = [
            _make_channel_url(i) for i in range(total_channels)
        ]

        # Rastrear índice de canal processado
        call_index = [0]

        async def mock_channel_session(url: str):
            """Primeira chamada sucesso, T falhas, última sucesso."""
            idx = call_index[0]
            call_index[0] += 1

            if idx == 0:
                # Primeiro canal: sucesso (dispara discovery)
                await orchestrator._ensure_capability_map(
                    "test-session"
                )
                return _create_mock_report(url, status="PASS")
            elif idx <= t:
                # T canais falham (TimeoutError para incrementar
                # consecutive_failures)
                raise TimeoutError(
                    f"Canal {idx} inacessível"
                )
            else:
                # Último canal: sucesso (re-discovery após invalida)
                await orchestrator._ensure_capability_map(
                    "test-session"
                )
                return _create_mock_report(url, status="PASS")

        orchestrator._run_channel_session = AsyncMock(
            side_effect=mock_channel_session
        )

        # Mock report generator
        orchestrator._report_generator = MagicMock()
        orchestrator._report_generator.create_consolidated_report = (
            MagicMock(
                return_value=ConsolidatedReport(
                    timestamp="2024-01-01T00:00:00Z",
                    total_channels=total_channels,
                    channels_pass=2,
                    channels_unreachable=t,
                )
            )
        )
        orchestrator._report_generator.persist_report = MagicMock()

        # Executar rotação
        await orchestrator.run_single_rotation(channels)

        # Verificar: discovery chamado exatamente 2 vezes
        # (inicial + re-discovery após invalidação)
        assert orchestrator._run_discovery.call_count == 2, (
            f"Com threshold={t}, após {t} falhas consecutivas "
            f"+ 1 sucesso, discovery deveria ser chamado 2 vezes, "
            f"mas foi chamado "
            f"{orchestrator._run_discovery.call_count} vezes"
        )


# ============================================================
# Feature: unified-channel-monitor, Property 3: Sequential
# processing with error resilience
# ============================================================

# Estratégia: tipo de comportamento por canal
_channel_behavior = st.one_of(
    st.just("success"),
    st.just("timeout"),
    st.just("exception"),
)

# Lista de 1-10 canais com comportamento definido
_channel_behaviors = st.lists(
    _channel_behavior,
    min_size=1,
    max_size=10,
)


def _make_success_report(channel_url: str) -> UnifiedChannelReport:
    """Cria um UnifiedChannelReport de sucesso para testes."""
    return UnifiedChannelReport(
        channel_url=channel_url,
        channel_id=f"ch-{hash(channel_url) % 1000}",
        session_id=str(uuid.uuid4()),
        timestamp=datetime.now(timezone.utc).isoformat(),
        status=ChannelSessionStatus.PASS.value,
        duration_ms=1500,
        video_summary=TelemetrySummary(total_samples=15),
        audio_tracks_tested=2,
        audio_tracks_passed=2,
        audio_results=[],
        subtitle_tracks_tested=1,
        subtitle_tracks_passed=1,
        subtitle_results=[],
        escalation_results=[],
        telemetry_annotations=[],
        errors=[],
    )


class TestPropertySequentialProcessingWithResilience:
    """Property 3: Sequential processing with error resilience.

    Para qualquer lista de N canais onde alguns canais falham
    (timeout ou exceção), o UnifiedOrchestrator produz um
    ConsolidatedReport com exatamente N entradas, onde canais
    com falha têm status UNREACHABLE ou ERROR e todos os canais
    sem falha são processados até o fim.

    **Validates: Requirements 2.1, 2.3, 2.4**
    """

    @given(behaviors=_channel_behaviors)
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_sequential_processing_with_error_resilience(
        self, behaviors: list[str]
    ) -> None:
        """Para qualquer combinação de canais com sucesso/falha,
        o relatório consolidado tem exatamente N entradas e os
        status corretos por tipo de falha.

        **Validates: Requirements 2.1, 2.3, 2.4**
        """
        n = len(behaviors)
        channel_urls = [_make_channel_url(i) for i in range(n)]

        # Setup mock page
        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.wait_for_selector = AsyncMock()
        mock_page.evaluate = AsyncMock(return_value=False)

        # Configuração mínima — desabilitar invalidação
        config = UnifiedMonitorConfig(
            output_dir="/tmp/test_reports_prop3/",
            invalidation_threshold=100,
        )

        orchestrator = UnifiedOrchestrator(
            page=mock_page,
            config=config,
        )

        # Rastrear ordem de processamento
        call_index = [0]

        async def mock_run_channel_session(channel_url: str):
            """Side effect baseado no comportamento esperado."""
            idx = call_index[0]
            call_index[0] += 1
            behavior = behaviors[idx]

            if behavior == "success":
                return _make_success_report(channel_url)
            elif behavior == "timeout":
                raise TimeoutError(
                    f"Timeout ao acessar canal: {channel_url}"
                )
            else:  # "exception"
                raise RuntimeError(
                    f"Erro inesperado no canal: {channel_url}"
                )

        # Mock _run_channel_session para controlar comportamento
        orchestrator._run_channel_session = AsyncMock(
            side_effect=mock_run_channel_session
        )

        # Mock persist_report para não fazer I/O
        orchestrator._report_generator.persist_report = MagicMock()

        # Executar rotação
        consolidated = await orchestrator.run_single_rotation(
            channel_urls
        )

        # ========================================================
        # Verificações da propriedade
        # ========================================================

        # 1. consolidated.total_channels == N
        assert consolidated.total_channels == n, (
            f"Esperado total_channels={n}, "
            f"obtido {consolidated.total_channels}"
        )

        # 2. len(consolidated.channel_reports) == N
        assert len(consolidated.channel_reports) == n, (
            f"Esperado {n} channel_reports, "
            f"obtido {len(consolidated.channel_reports)}"
        )

        # 3. Canais com falha têm status UNREACHABLE ou ERROR
        for i, behavior in enumerate(behaviors):
            report = consolidated.channel_reports[i]
            if behavior == "timeout":
                assert (
                    report.status
                    == ChannelSessionStatus.UNREACHABLE.value
                ), (
                    f"Canal {i} (timeout) deveria ter status "
                    f"UNREACHABLE, obtido {report.status}"
                )
            elif behavior == "exception":
                assert (
                    report.status
                    == ChannelSessionStatus.ERROR.value
                ), (
                    f"Canal {i} (exception) deveria ter status "
                    f"ERROR, obtido {report.status}"
                )

        # 4. Canais com sucesso têm status in (PASS, PARTIAL, FAIL)
        #    — NÃO UNREACHABLE/ERROR
        valid_success_statuses = {
            ChannelSessionStatus.PASS.value,
            ChannelSessionStatus.PARTIAL.value,
            ChannelSessionStatus.FAIL.value,
        }
        for i, behavior in enumerate(behaviors):
            report = consolidated.channel_reports[i]
            if behavior == "success":
                assert report.status in valid_success_statuses, (
                    f"Canal {i} (success) deveria ter status em "
                    f"{valid_success_statuses}, obtido "
                    f"{report.status}"
                )

        # 5. Todos os N canais foram processados (sem terminação
        #    prematura) — verificado pelo call_index
        assert call_index[0] == n, (
            f"Esperado processar {n} canais, "
            f"mas apenas {call_index[0]} foram chamados"
        )
