"""Testes unitários e property tests para o EscalationManager.

Valida o pipeline de escalação com deferimento, processamento
imediato e integração com FrameCapturer, OpenCVAnalyzer e BedrockClient.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from src.unified_channel_monitor.escalation import EscalationManager
from src.unified_channel_monitor.models import (
    DeferredEscalation,
    EscalationResult,
    TelemetrySample,
)


def _make_sample(
    timestamp: str = "2024-01-01T00:00:00.000Z",
    is_freeze: bool = False,
) -> TelemetrySample:
    """Cria uma TelemetrySample para testes."""
    return TelemetrySample(
        timestamp=timestamp,
        current_time=10.0,
        total_frames_decoded=300,
        frames_dropped=0,
        estimated_fps=30.0,
        buffer_ahead_s=5.0,
        ready_state=4,
        is_freeze=is_freeze,
    )


def _make_trigger(
    timestamp: str = "2024-01-01T00:00:00.000Z",
    health: str = "SUSPECT",
    track_context: dict | None = None,
) -> DeferredEscalation:
    """Cria um DeferredEscalation para testes."""
    return DeferredEscalation(
        trigger_timestamp=timestamp,
        health_classification=health,
        telemetry_sample=_make_sample(timestamp),
        track_switch_context=track_context,
    )


@pytest.fixture
def mock_page():
    """Mock da Playwright Page."""
    return MagicMock()


@pytest.fixture
def manager(mock_page):
    """EscalationManager com todos os componentes None."""
    return EscalationManager(
        page=mock_page,
        frame_capturer=None,
        opencv_analyzer=None,
        bedrock_client=None,
    )


class TestDeferEscalation:
    """Testes para defer_escalation."""

    def test_enfileira_trigger(self, manager):
        """Deve enfileirar trigger na fila de escalações deferidas."""
        trigger = _make_trigger()
        manager.defer_escalation(trigger)
        assert manager.deferred_count == 1

    def test_enfileira_multiplos_triggers(self, manager):
        """Deve acumular múltiplos triggers na fila."""
        for i in range(5):
            trigger = _make_trigger(
                timestamp=f"2024-01-01T00:00:0{i}.000Z"
            )
            manager.defer_escalation(trigger)
        assert manager.deferred_count == 5

    def test_nao_executa_dom_interaction(self, manager, mock_page):
        """Defer NÃO deve interagir com DOM/page."""
        trigger = _make_trigger()
        manager.defer_escalation(trigger)
        # Nenhuma chamada ao page deve ter ocorrido
        mock_page.assert_not_called()

    def test_preserva_track_switch_context(self, manager):
        """Deve preservar contexto de track switch na escalação."""
        context = {
            "track_name": "Português",
            "track_type": "audio",
            "switch_timestamp": "2024-01-01T00:00:00.000Z",
        }
        trigger = _make_trigger(track_context=context)
        manager.defer_escalation(trigger)
        # Acessa a fila interna para verificar
        assert manager._deferred_queue[0].track_switch_context == context


class TestSetTrackTestingActive:
    """Testes para set_track_testing_active."""

    def test_ativa_flag(self, manager):
        """Deve setar track_testing_active para True."""
        manager.set_track_testing_active(True)
        assert manager.track_testing_active is True

    def test_desativa_flag(self, manager):
        """Deve setar track_testing_active para False."""
        manager.set_track_testing_active(True)
        manager.set_track_testing_active(False)
        assert manager.track_testing_active is False


class TestProcessDeferred:
    """Testes para process_deferred."""

    @pytest.mark.asyncio
    async def test_retorna_vazio_sem_fila(self, manager):
        """Deve retornar lista vazia se não há escalações pendentes."""
        results = await manager.process_deferred()
        assert results == []

    @pytest.mark.asyncio
    async def test_limpa_fila_apos_processamento(self, manager):
        """Deve limpar a fila após processar todas as escalações."""
        manager.defer_escalation(_make_trigger())
        manager.defer_escalation(_make_trigger(timestamp="2024-01-01T00:00:01.000Z"))
        await manager.process_deferred()
        assert manager.deferred_count == 0

    @pytest.mark.asyncio
    async def test_retorna_resultados_para_cada_trigger(self, manager):
        """Deve retornar um EscalationResult para cada trigger na fila."""
        manager.defer_escalation(_make_trigger())
        manager.defer_escalation(_make_trigger(timestamp="2024-01-01T00:00:01.000Z"))
        results = await manager.process_deferred()
        assert len(results) == 2
        assert all(isinstance(r, EscalationResult) for r in results)

    @pytest.mark.asyncio
    async def test_marca_resultados_como_deferred(self, manager):
        """Deve marcar resultados como deferred=True."""
        manager.defer_escalation(_make_trigger())
        results = await manager.process_deferred()
        assert results[0].deferred is True

    @pytest.mark.asyncio
    async def test_sem_frame_capturer_retorna_sem_analise(self, manager):
        """Sem FrameCapturer, resultado deve ter frames_analyzed=0."""
        manager.defer_escalation(_make_trigger())
        results = await manager.process_deferred()
        assert results[0].frames_analyzed == 0
        assert results[0].opencv_verdict is None
        assert results[0].bedrock_diagnosis is None


class TestEscalateImmediate:
    """Testes para escalate_immediate."""

    @pytest.mark.asyncio
    async def test_retorna_escalation_result(self, manager):
        """Deve retornar EscalationResult."""
        trigger = _make_trigger()
        result = await manager.escalate_immediate(trigger)
        assert isinstance(result, EscalationResult)

    @pytest.mark.asyncio
    async def test_marca_como_nao_deferred(self, manager):
        """Escalação imediata deve ter deferred=False."""
        trigger = _make_trigger()
        result = await manager.escalate_immediate(trigger)
        assert result.deferred is False

    @pytest.mark.asyncio
    async def test_nao_adiciona_na_fila(self, manager):
        """Escalação imediata NÃO deve adicionar na fila."""
        trigger = _make_trigger()
        await manager.escalate_immediate(trigger)
        assert manager.deferred_count == 0


class TestPipelineComFrameCapturer:
    """Testes do pipeline com FrameCapturer mockado."""

    @pytest.fixture
    def frame_capturer(self):
        """Mock do FrameCapturer."""
        fc = MagicMock()
        fc.capture_frame = AsyncMock()
        return fc

    @pytest.fixture
    def manager_with_fc(self, mock_page, frame_capturer):
        """Manager com FrameCapturer."""
        return EscalationManager(
            page=mock_page,
            frame_capturer=frame_capturer,
            opencv_analyzer=None,
            bedrock_client=None,
        )

    @pytest.mark.asyncio
    async def test_captura_frame_na_escalacao(
        self, manager_with_fc, frame_capturer, mock_page
    ):
        """Deve chamar capture_frame durante escalação."""
        frame_capturer.capture_frame.return_value = MagicMock(
            is_valid=True, data=b"fake_frame_data"
        )
        trigger = _make_trigger()
        result = await manager_with_fc.escalate_immediate(trigger)
        frame_capturer.capture_frame.assert_called_once_with(mock_page)
        assert result.frames_analyzed == 1

    @pytest.mark.asyncio
    async def test_frame_invalido_encerra_pipeline(
        self, manager_with_fc, frame_capturer
    ):
        """Frame inválido deve encerrar o pipeline sem OpenCV/Bedrock."""
        frame_capturer.capture_frame.return_value = MagicMock(
            is_valid=False, rejected_reason="too_small"
        )
        trigger = _make_trigger()
        result = await manager_with_fc.escalate_immediate(trigger)
        assert result.frames_analyzed == 0
        assert result.opencv_verdict is None

    @pytest.mark.asyncio
    async def test_excecao_na_captura_nao_propaga(
        self, manager_with_fc, frame_capturer
    ):
        """Exceção na captura não deve propagar — resultado parcial."""
        frame_capturer.capture_frame.side_effect = RuntimeError("Boom")
        trigger = _make_trigger()
        result = await manager_with_fc.escalate_immediate(trigger)
        assert result.frames_analyzed == 0
        assert result.opencv_verdict is None


class TestDeferredNaoExecutaDomDuranteTrackTests:
    """Garante que escalações deferidas NÃO executam DOM interactions
    durante testes de track."""

    @pytest.mark.asyncio
    async def test_defer_nao_chama_page(self, mock_page):
        """Enquanto track_testing_active, defer NÃO interage com page."""
        fc = MagicMock()
        fc.capture_frame = AsyncMock()
        mgr = EscalationManager(
            page=mock_page,
            frame_capturer=fc,
            opencv_analyzer=None,
            bedrock_client=None,
        )
        mgr.set_track_testing_active(True)
        trigger = _make_trigger()
        # Defer apenas enfileira, não captura
        mgr.defer_escalation(trigger)
        fc.capture_frame.assert_not_called()
        mock_page.assert_not_called()



# ============================================================
# Feature: unified-channel-monitor, Property 10: Escalation is
# deferred during track testing
# ============================================================


# Strategies para geração de dados de property test

_health_classifications = st.sampled_from(
    ["SUSPECT", "DEGRADED", "CRITICAL"]
)

_track_switch_context = st.one_of(
    st.none(),
    st.fixed_dictionaries(
        {
            "track_name": st.text(
                min_size=1, max_size=30
            ),
            "track_type": st.sampled_from(
                ["audio", "subtitle"]
            ),
            "switch_timestamp": st.text(
                min_size=10, max_size=30
            ),
        }
    ),
)

_telemetry_sample = st.builds(
    TelemetrySample,
    timestamp=st.just("2024-01-01T00:00:00.000Z"),
    current_time=st.floats(
        min_value=0.0, max_value=3600.0
    ),
    total_frames_decoded=st.integers(
        min_value=0, max_value=100000
    ),
    frames_dropped=st.integers(min_value=0, max_value=1000),
    estimated_fps=st.one_of(
        st.none(),
        st.floats(min_value=0.0, max_value=120.0),
    ),
    buffer_ahead_s=st.floats(
        min_value=0.0, max_value=60.0
    ),
    ready_state=st.integers(min_value=0, max_value=4),
    is_freeze=st.booleans(),
    annotation=st.none(),
)

_deferred_escalation = st.builds(
    DeferredEscalation,
    trigger_timestamp=st.from_regex(
        r"2024-01-01T00:00:[0-5][0-9]\.\d{3}Z", fullmatch=True
    ),
    health_classification=_health_classifications,
    telemetry_sample=_telemetry_sample,
    track_switch_context=_track_switch_context,
)

_escalation_triggers = st.lists(
    _deferred_escalation, min_size=1, max_size=10
)


class TestProperty10EscalationDeferredDuringTrackTesting:
    """Property 10: Escalation is deferred during track testing.

    Para qualquer trigger de escalação que ocorra enquanto um
    AudioTrackTester ou SubtitleTrackTester está ativamente testando
    um track, a escalação NÃO DEVE executar frame capture ou DOM
    interactions até o teste atual completar. A escalação deferida
    DEVE ser processada após o fim do teste.

    **Validates: Requirements 7.3, 7.4, 7.5**
    """

    @settings(max_examples=100)
    @given(triggers=_escalation_triggers)
    @pytest.mark.asyncio
    async def test_no_frame_capture_or_dom_during_track_testing(
        self, triggers: list[DeferredEscalation]
    ):
        """Enquanto track_testing_active, defer_escalation NÃO
        executa frame capture nem DOM interactions.

        **Validates: Requirements 7.3, 7.4, 7.5**
        """
        # Arrange: mocks para page e frame_capturer
        page = AsyncMock()
        frame_capturer = MagicMock()
        frame_capturer.capture_frame = AsyncMock()
        opencv_analyzer = MagicMock()
        bedrock_client = MagicMock()

        manager = EscalationManager(
            page=page,
            frame_capturer=frame_capturer,
            opencv_analyzer=opencv_analyzer,
            bedrock_client=bedrock_client,
        )

        # Act: ativar modo de teste de tracks
        manager.set_track_testing_active(True)

        # Deferir todas as escalações
        for trigger in triggers:
            manager.defer_escalation(trigger)

        # Assert: NENHUMA interação com DOM ou frame capture
        frame_capturer.capture_frame.assert_not_called()
        page.evaluate.assert_not_called()
        page.click.assert_not_called()
        page.goto.assert_not_called()
        page.wait_for_selector.assert_not_called()

    @settings(max_examples=100)
    @given(triggers=_escalation_triggers)
    @pytest.mark.asyncio
    async def test_deferred_processed_after_testing_ends(
        self, triggers: list[DeferredEscalation]
    ):
        """Após desativar track_testing, process_deferred retorna
        resultados para cada trigger com deferred=True e esvazia
        a fila.

        **Validates: Requirements 7.3, 7.4, 7.5**
        """
        # Arrange
        page = AsyncMock()
        frame_capturer = MagicMock()
        frame_capturer.capture_frame = AsyncMock(
            return_value=MagicMock(
                is_valid=True, data=b"fake_frame"
            )
        )
        opencv_analyzer = None
        bedrock_client = None

        manager = EscalationManager(
            page=page,
            frame_capturer=frame_capturer,
            opencv_analyzer=opencv_analyzer,
            bedrock_client=bedrock_client,
        )

        # Ativar track testing e deferir
        manager.set_track_testing_active(True)
        for trigger in triggers:
            manager.defer_escalation(trigger)

        # Verificar que nada executou durante o teste
        frame_capturer.capture_frame.assert_not_called()

        # Desativar track testing
        manager.set_track_testing_active(False)

        # Processar escalações deferidas
        results = await manager.process_deferred()

        # Assert: um resultado para cada trigger
        assert len(results) == len(triggers)

        # Assert: cada resultado marcado como deferred
        for result in results:
            assert result.deferred is True

        # Assert: fila vazia após processamento
        assert manager.deferred_count == 0
