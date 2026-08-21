"""EventProbe — Registro de todos os eventos do HTMLMediaElement.

Registra listeners para eventos do player e mantém histórico com
janela de retenção de 5 minutos por canal.

Requirements: 9.1, 9.2, 9.3, 9.4
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from playwright.async_api import Page

from src.player_discovery.models import PlayerEvent

logger = logging.getLogger(__name__)

# Eventos do HTMLMediaElement que devem ser monitorados
MEDIA_EVENTS: list[str] = [
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

# Janela de retenção padrão: 5 minutos (300 segundos)
DEFAULT_RETENTION_SECONDS: int = 300


class EventProbe:
    """Registra todos os eventos do HTMLMediaElement com timestamps.

    Utiliza page.expose_function() para receber eventos do browser
    e mantém em memória os eventos dos últimos 5 minutos.

    Attributes:
        _events: Lista de eventos capturados
        _retention_seconds: Janela de retenção em segundos
        _attached: Se os listeners já foram anexados
        _function_name: Nome da função exposta no browser
    """

    def __init__(
        self, retention_seconds: int = DEFAULT_RETENTION_SECONDS
    ) -> None:
        """Inicializa EventProbe.

        Args:
            retention_seconds: Janela de retenção em segundos
                (padrão: 300 = 5 minutos)
        """
        self._events: list[PlayerEvent] = []
        self._retention_seconds: int = retention_seconds
        self._attached: bool = False
        self._function_name: str = "__eventProbeCallback"

    async def attach_listeners(self, page: Page) -> None:
        """Registra listeners para todos os eventos HTMLMediaElement.

        Usa page.expose_function() para criar um canal de comunicação
        entre o browser e o Python. Os listeners no browser enviam
        dados via essa função exposta.

        Args:
            page: Instância Playwright Page
        """
        if self._attached:
            logger.warning(
                "EventProbe: listeners já anexados, ignorando."
            )
            return

        # Expor função Python no browser para receber eventos
        await page.expose_function(
            self._function_name, self._handle_event
        )

        # Injetar script que registra listeners em todos os
        # elementos <video> encontrados
        js_script = self._build_listener_script()
        await page.evaluate(js_script)

        self._attached = True
        logger.info(
            "EventProbe: listeners anexados para %d eventos.",
            len(MEDIA_EVENTS),
        )

    async def get_events(self, page: Optional[Page] = None) -> list[PlayerEvent]:
        """Retorna eventos dentro da janela de retenção de 5 minutos.

        Remove eventos expirados antes de retornar.

        Args:
            page: Instância Playwright Page (não utilizada, mantida
                  para consistência de interface)

        Returns:
            Lista de PlayerEvent dentro da janela de retenção
        """
        self._apply_retention_window()
        return list(self._events)

    def clear_events(self) -> None:
        """Limpa registro de eventos do canal atual.

        Chamado quando o ChannelMonitor navega para um novo canal.
        """
        self._events.clear()
        logger.info("EventProbe: eventos limpos para novo canal.")

    def _apply_retention_window(self) -> None:
        """Remove eventos mais antigos que a janela de retenção."""
        if not self._events:
            return

        cutoff = datetime.now(timezone.utc) - timedelta(
            seconds=self._retention_seconds
        )
        cutoff_iso = cutoff.isoformat(timespec="milliseconds")

        self._events = [
            event
            for event in self._events
            if event.timestamp >= cutoff_iso
        ]

    async def _handle_event(
        self,
        event_type: str,
        timestamp: str,
        current_time: float,
        additional_data: Optional[dict] = None,
    ) -> None:
        """Callback invocado pelo browser quando um evento ocorre.

        Args:
            event_type: Tipo do evento (ex: "play", "pause")
            timestamp: Timestamp ISO 8601 com milissegundos
            current_time: Posição de reprodução no momento do evento
            additional_data: Dados adicionais (error code, etc.)
        """
        if additional_data is None:
            additional_data = {}

        event = PlayerEvent(
            event_type=event_type,
            timestamp=timestamp,
            current_time=float(current_time),
            additional_data=additional_data,
        )
        self._events.append(event)
        logger.debug(
            "EventProbe: evento '%s' registrado em %s",
            event_type,
            timestamp,
        )

    def _build_listener_script(self) -> str:
        """Constrói script JS para registrar listeners no browser.

        O script encontra todos os elementos <video> na página e
        registra listeners para cada evento do HTMLMediaElement.
        Quando um evento é disparado, invoca a função exposta com
        os dados capturados.

        Returns:
            String com código JavaScript
        """
        events_json = str(MEDIA_EVENTS)
        return f"""
        (() => {{
            const events = {events_json};
            const videos = document.querySelectorAll('video');
            const callbackName = '{self._function_name}';

            videos.forEach((video) => {{
                events.forEach((eventType) => {{
                    video.addEventListener(eventType, (e) => {{
                        const timestamp = new Date().toISOString();
                        const currentTime = video.currentTime || 0;
                        let additionalData = {{}};

                        if (eventType === 'error' && video.error) {{
                            additionalData = {{
                                error_code: video.error.code,
                                error_message: video.error.message || ''
                            }};
                        }}

                        if (
                            eventType === 'waiting'
                            || eventType === 'stalled'
                        ) {{
                            const buffered = video.buffered;
                            let bufferedEnd = 0;
                            if (buffered && buffered.length > 0) {{
                                bufferedEnd = buffered.end(
                                    buffered.length - 1
                                );
                            }}
                            additionalData = {{
                                buffered_seconds: bufferedEnd
                                    - currentTime
                            }};
                        }}

                        window[callbackName](
                            eventType,
                            timestamp,
                            currentTime,
                            additionalData
                        );
                    }});
                }});
            }});
        }})();
        """

    @property
    def attached(self) -> bool:
        """Indica se os listeners estão anexados."""
        return self._attached

    @property
    def event_count(self) -> int:
        """Retorna quantidade total de eventos armazenados."""
        return len(self._events)

    def reset(self) -> None:
        """Reseta completamente o estado do probe.

        Limpa eventos e marca como não-anexado para permitir
        re-attach em nova página.
        """
        self._events.clear()
        self._attached = False
        logger.info("EventProbe: reset completo.")
