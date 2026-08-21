"""SubtitleMonitor — Monitora e valida funcionalidade de legendas.

Valida mudanças de track de legenda via Shaka Player API
(window.player.getTextTracks()) e monitora cues ativas via
TextTrack API (video.textTracks) com polling configurável.

Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 10.2
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from .config import AudioSubtitleConfig
from .models import CueResult, ValidationResult

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = logging.getLogger(__name__)


class SubtitleMonitor:
    """Monitora e valida funcionalidade de legendas.

    Utiliza Shaka Player API para verificar mudanças de track e
    TextTrack API para monitorar cues ativas após seleção via UI.

    Attributes:
        page: Instância do Playwright Page para interação com o browser.
        config: Configuração com timeouts e intervalos de polling.
    """

    def __init__(self, page: Page, config: AudioSubtitleConfig) -> None:
        """Inicializa o SubtitleMonitor.

        Args:
            page: Instância do Playwright Page para interação com o browser.
            config: Configuração com timeouts e intervalos de polling.
        """
        self.page = page
        self.config = config

    async def validate_track_switch(
        self, expected_language: str, timeout_s: float = 5.0
    ) -> ValidationResult:
        """Verifica via Shaka API que o track de legenda ativo mudou.

        Faz polling de window.player.getTextTracks() até encontrar um
        track com o language esperado marcado como active, ou até o
        timeout ser atingido.

        Args:
            expected_language: Código do idioma esperado (ex: "pt", "en").
            timeout_s: Tempo máximo de espera em segundos. Padrão: 5.0.

        Returns:
            ValidationResult com success=True se track encontrado e ativo,
            ou success=False com detalhes do estado atual da API.
        """
        poll_interval = 0.5
        start = time.monotonic()

        actual_active_language: str | None = None
        api_tracks: list[dict] = []

        while (time.monotonic() - start) < timeout_s:
            try:
                tracks = await self.page.evaluate(
                    "() => window.player.getTextTracks()"
                )
            except Exception as exc:
                logger.warning(
                    "Erro ao consultar getTextTracks(): %s", exc
                )
                tracks = []

            if tracks is None:
                tracks = []

            api_tracks = tracks

            # Procurar track ativo com o idioma esperado
            for track in tracks:
                if track.get("active"):
                    actual_active_language = track.get("language")

                if (
                    track.get("language") == expected_language
                    and track.get("active") is True
                ):
                    logger.info(
                        "Track de legenda '%s' confirmado como ativo.",
                        expected_language,
                    )
                    return ValidationResult(
                        success=True,
                        expected_language=expected_language,
                        actual_active_language=expected_language,
                        api_tracks=api_tracks,
                    )

            await asyncio.sleep(poll_interval)

        # Timeout — track não foi confirmado como ativo
        logger.warning(
            "Timeout: track de legenda '%s' não confirmado. "
            "Ativo atual: '%s'.",
            expected_language,
            actual_active_language,
        )
        return ValidationResult(
            success=False,
            expected_language=expected_language,
            actual_active_language=actual_active_language,
            api_tracks=api_tracks,
            error="subtitle_switch_not_confirmed",
        )

    async def get_active_tracks(self) -> list[dict]:
        """Consulta window.player.getTextTracks() via Shaka API.

        Returns:
            Lista de dicts com informações de cada text track
            (language, active, label, etc.). Lista vazia se
            a API não estiver disponível.
        """
        try:
            tracks = await self.page.evaluate(
                "() => window.player.getTextTracks()"
            )
        except Exception as exc:
            logger.warning(
                "Erro ao consultar getTextTracks(): %s", exc
            )
            return []

        if tracks is None:
            return []

        return tracks

    async def wait_for_active_cue(
        self, timeout_s: float = 15.0, poll_interval_s: float = 0.5
    ) -> CueResult:
        """Monitora activeCues na track ativa até timeout.

        Faz polling via TextTrack API (video.textTracks) procurando
        uma track no modo 'showing' com activeCues disponíveis.
        Retorna o texto da primeira cue encontrada (truncado a 50 chars).

        Args:
            timeout_s: Tempo máximo de espera em segundos. Padrão: 15.0.
            poll_interval_s: Intervalo entre tentativas. Padrão: 0.5.

        Returns:
            CueResult com found=True e cue_text se cue detectada,
            ou found=False com error se timeout atingido.
        """
        start = time.monotonic()

        js_poll_cues = """() => {
    const video = document.querySelector('video');
    if (!video || !video.textTracks) return null;
    for (let i = 0; i < video.textTracks.length; i++) {
        const track = video.textTracks[i];
        const showing = track.mode === 'showing';
        const hasCues = track.activeCues
            && track.activeCues.length > 0;
        if (showing && hasCues) {
            return {
                text: track.activeCues[0].text,
                trackLabel: track.label
            };
        }
    }
    return null;
}"""

        while (time.monotonic() - start) < timeout_s:
            try:
                result = await self.page.evaluate(js_poll_cues)
            except Exception as exc:
                logger.warning(
                    "Erro ao consultar activeCues: %s", exc
                )
                result = None

            if result is not None:
                elapsed_ms = int(
                    (time.monotonic() - start) * 1000
                )
                cue_text = result.get("text", "") or ""
                # Truncar a 50 caracteres conforme Req 5.4
                cue_text_truncated = cue_text[:50]

                logger.info(
                    "Cue ativa detectada em %dms: '%s'",
                    elapsed_ms,
                    cue_text_truncated,
                )
                return CueResult(
                    found=True,
                    cue_text=cue_text_truncated,
                    time_to_first_cue_ms=elapsed_ms,
                )

            await asyncio.sleep(poll_interval_s)

        # Timeout — nenhuma cue ativa encontrada
        logger.warning(
            "Timeout: nenhuma cue ativa detectada em %.1fs.",
            timeout_s,
        )
        return CueResult(
            found=False,
            error="no_active_cues_within_15s",
        )
