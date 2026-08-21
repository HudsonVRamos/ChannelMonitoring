"""Testes unitários para o EventProbe.

Valida:
- Registro de listeners para todos os eventos HTMLMediaElement
- get_events() retorna eventos dentro da janela de retenção
- clear_events() limpa o registro de eventos
- Janela de retenção de 5 minutos funciona corretamente
- Campos obrigatórios dos eventos (event_type, timestamp, current_time)
- Dados adicionais são registrados corretamente

Requirements: 9.1, 9.2, 9.3, 9.4
"""

import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.player_discovery.probes.event_probe import (
    EventProbe,
    MEDIA_EVENTS,
    DEFAULT_RETENTION_SECONDS,
)
from src.player_discovery.models import PlayerEvent


class TestEventProbeInit:
    """Testes de inicialização do EventProbe."""

    def test_inicializacao_padrao(self):
        """EventProbe inicializa com valores padrão corretos."""
        probe = EventProbe()

        assert probe._events == []
        assert probe._retention_seconds == 300
        assert probe._attached is False
        assert probe.event_count == 0

    def test_inicializacao_com_retention_customizado(self):
        """EventProbe aceita janela de retenção customizada."""
        probe = EventProbe(retention_seconds=600)

        assert probe._retention_seconds == 600

    def test_attached_property_inicial(self):
        """Property attached retorna False antes de attach."""
        probe = EventProbe()

        assert probe.attached is False


class TestAttachListeners:
    """Testes de attach_listeners()."""

    @pytest.mark.asyncio
    async def test_attach_listeners_expoe_funcao_e_avalia_js(self):
        """attach_listeners expõe função e injeta script JS."""
        probe = EventProbe()
        page = AsyncMock()

        await probe.attach_listeners(page)

        page.expose_function.assert_called_once_with(
            "__eventProbeCallback", probe._handle_event
        )
        page.evaluate.assert_called_once()
        assert probe.attached is True

    @pytest.mark.asyncio
    async def test_attach_listeners_nao_repete_se_ja_attached(self):
        """attach_listeners não repete se já foi chamado."""
        probe = EventProbe()
        page = AsyncMock()

        await probe.attach_listeners(page)
        await probe.attach_listeners(page)

        # Deve ter sido chamado apenas uma vez
        assert page.expose_function.call_count == 1
        assert page.evaluate.call_count == 1

    @pytest.mark.asyncio
    async def test_script_js_contém_todos_eventos(self):
        """Script JS gerado contém todos os eventos do HTMLMediaElement."""
        probe = EventProbe()
        script = probe._build_listener_script()

        for event in MEDIA_EVENTS:
            assert event in script


class TestHandleEvent:
    """Testes do callback _handle_event()."""

    @pytest.mark.asyncio
    async def test_handle_event_registra_evento(self):
        """_handle_event registra evento corretamente."""
        probe = EventProbe()
        timestamp = "2024-01-15T10:30:00.123Z"

        await probe._handle_event(
            "play", timestamp, 42.5, {}
        )

        assert probe.event_count == 1
        event = probe._events[0]
        assert event.event_type == "play"
        assert event.timestamp == timestamp
        assert event.current_time == 42.5
        assert event.additional_data == {}

    @pytest.mark.asyncio
    async def test_handle_event_com_dados_adicionais(self):
        """_handle_event registra dados adicionais (error, buffer)."""
        probe = EventProbe()
        timestamp = "2024-01-15T10:30:00.456Z"
        additional = {"error_code": 4, "error_message": "MEDIA_ERR_SRC"}

        await probe._handle_event(
            "error", timestamp, 10.0, additional
        )

        event = probe._events[0]
        assert event.additional_data == additional

    @pytest.mark.asyncio
    async def test_handle_event_sem_dados_adicionais_usa_dict_vazio(self):
        """_handle_event sem dados adicionais usa dict vazio."""
        probe = EventProbe()
        timestamp = "2024-01-15T10:30:00.789Z"

        await probe._handle_event(
            "pause", timestamp, 5.0, None
        )

        event = probe._events[0]
        assert event.additional_data == {}

    @pytest.mark.asyncio
    async def test_handle_event_multiple_eventos(self):
        """Múltiplos eventos são armazenados em ordem."""
        probe = EventProbe()

        await probe._handle_event(
            "loadstart", "2024-01-15T10:30:00.000Z", 0.0, {}
        )
        await probe._handle_event(
            "loadedmetadata", "2024-01-15T10:30:01.000Z", 0.0, {}
        )
        await probe._handle_event(
            "play", "2024-01-15T10:30:02.000Z", 0.0, {}
        )

        assert probe.event_count == 3
        assert probe._events[0].event_type == "loadstart"
        assert probe._events[1].event_type == "loadedmetadata"
        assert probe._events[2].event_type == "play"


class TestGetEvents:
    """Testes de get_events()."""

    @pytest.mark.asyncio
    async def test_get_events_retorna_lista_vazia_sem_eventos(self):
        """get_events retorna lista vazia quando não há eventos."""
        probe = EventProbe()

        events = await probe.get_events()

        assert events == []

    @pytest.mark.asyncio
    async def test_get_events_retorna_eventos_recentes(self):
        """get_events retorna eventos dentro da janela de retenção."""
        probe = EventProbe()
        now = datetime.now(timezone.utc)
        timestamp = now.isoformat(timespec="milliseconds")

        await probe._handle_event("play", timestamp, 10.0, {})

        events = await probe.get_events()

        assert len(events) == 1
        assert events[0].event_type == "play"

    @pytest.mark.asyncio
    async def test_get_events_remove_eventos_expirados(self):
        """get_events remove eventos mais antigos que 5 minutos."""
        probe = EventProbe(retention_seconds=300)

        # Evento antigo (6 minutos atrás)
        old_time = datetime.now(timezone.utc) - timedelta(minutes=6)
        old_timestamp = old_time.isoformat(timespec="milliseconds")
        await probe._handle_event(
            "loadstart", old_timestamp, 0.0, {}
        )

        # Evento recente (1 minuto atrás)
        recent_time = datetime.now(timezone.utc) - timedelta(minutes=1)
        recent_timestamp = recent_time.isoformat(
            timespec="milliseconds"
        )
        await probe._handle_event(
            "play", recent_timestamp, 5.0, {}
        )

        events = await probe.get_events()

        assert len(events) == 1
        assert events[0].event_type == "play"

    @pytest.mark.asyncio
    async def test_get_events_retorna_copia_da_lista(self):
        """get_events retorna cópia, não referência interna."""
        probe = EventProbe()
        now = datetime.now(timezone.utc)
        timestamp = now.isoformat(timespec="milliseconds")
        await probe._handle_event("play", timestamp, 10.0, {})

        events = await probe.get_events()
        events.clear()

        assert probe.event_count == 1


class TestClearEvents:
    """Testes de clear_events()."""

    @pytest.mark.asyncio
    async def test_clear_events_limpa_todos_eventos(self):
        """clear_events remove todos os eventos."""
        probe = EventProbe()
        now = datetime.now(timezone.utc)
        timestamp = now.isoformat(timespec="milliseconds")

        await probe._handle_event("play", timestamp, 10.0, {})
        await probe._handle_event("pause", timestamp, 15.0, {})

        probe.clear_events()

        assert probe.event_count == 0
        events = await probe.get_events()
        assert events == []

    def test_clear_events_em_lista_vazia_nao_falha(self):
        """clear_events em lista vazia não lança exceção."""
        probe = EventProbe()

        probe.clear_events()  # Não deve lançar exceção

        assert probe.event_count == 0


class TestRetentionWindow:
    """Testes da janela de retenção de 5 minutos."""

    @pytest.mark.asyncio
    async def test_retention_window_mantem_eventos_recentes(self):
        """Janela de retenção mantém eventos dos últimos 5 min."""
        probe = EventProbe(retention_seconds=300)

        # Eventos em 1, 2, 3, 4 minutos atrás (todos dentro)
        for minutes_ago in [1, 2, 3, 4]:
            t = datetime.now(timezone.utc) - timedelta(
                minutes=minutes_ago
            )
            ts = t.isoformat(timespec="milliseconds")
            await probe._handle_event("play", ts, 0.0, {})

        events = await probe.get_events()
        assert len(events) == 4

    @pytest.mark.asyncio
    async def test_retention_window_remove_eventos_antigos(self):
        """Janela de retenção remove eventos > 5 minutos."""
        probe = EventProbe(retention_seconds=300)

        # 3 eventos antigos (6, 7, 8 min atrás)
        for minutes_ago in [6, 7, 8]:
            t = datetime.now(timezone.utc) - timedelta(
                minutes=minutes_ago
            )
            ts = t.isoformat(timespec="milliseconds")
            await probe._handle_event("stalled", ts, 0.0, {})

        # 2 eventos recentes (1, 2 min atrás)
        for minutes_ago in [1, 2]:
            t = datetime.now(timezone.utc) - timedelta(
                minutes=minutes_ago
            )
            ts = t.isoformat(timespec="milliseconds")
            await probe._handle_event("playing", ts, 0.0, {})

        events = await probe.get_events()
        assert len(events) == 2
        assert all(e.event_type == "playing" for e in events)

    @pytest.mark.asyncio
    async def test_retention_customizada(self):
        """Janela de retenção customizada funciona."""
        # Retenção de 60 segundos
        probe = EventProbe(retention_seconds=60)

        # Evento de 2 minutos atrás (fora da janela de 60s)
        old_time = datetime.now(timezone.utc) - timedelta(minutes=2)
        old_ts = old_time.isoformat(timespec="milliseconds")
        await probe._handle_event("play", old_ts, 0.0, {})

        # Evento de 30 segundos atrás (dentro da janela)
        recent_time = datetime.now(timezone.utc) - timedelta(
            seconds=30
        )
        recent_ts = recent_time.isoformat(timespec="milliseconds")
        await probe._handle_event("pause", recent_ts, 0.0, {})

        events = await probe.get_events()
        assert len(events) == 1
        assert events[0].event_type == "pause"


class TestMediaEvents:
    """Testes da lista de eventos monitorados."""

    def test_media_events_contém_todos_eventos_requeridos(self):
        """MEDIA_EVENTS contém todos os 14 eventos requeridos."""
        eventos_requeridos = [
            "loadstart",
            "loadedmetadata",
            "loadeddata",
            "canplay",
            "canplaythrough",
            "play",
            "playing",
            "pause",
            "waiting",
            "stalled",
            "seeking",
            "seeked",
            "ended",
            "error",
        ]

        for evento in eventos_requeridos:
            assert evento in MEDIA_EVENTS

        assert len(MEDIA_EVENTS) == 14

    def test_default_retention_seconds(self):
        """DEFAULT_RETENTION_SECONDS é 300 (5 minutos)."""
        assert DEFAULT_RETENTION_SECONDS == 300


class TestReset:
    """Testes do método reset()."""

    @pytest.mark.asyncio
    async def test_reset_limpa_eventos_e_desanexa(self):
        """reset() limpa eventos e marca como não-anexado."""
        probe = EventProbe()
        page = AsyncMock()

        await probe.attach_listeners(page)
        now = datetime.now(timezone.utc)
        ts = now.isoformat(timespec="milliseconds")
        await probe._handle_event("play", ts, 0.0, {})

        probe.reset()

        assert probe.event_count == 0
        assert probe.attached is False
