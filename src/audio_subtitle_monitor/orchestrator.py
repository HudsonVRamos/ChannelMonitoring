"""Orquestrador principal do módulo de monitoramento de áudio e legendas.

Coordena o fluxo completo de testes de áudio e legendas em múltiplos
canais, iterando sequencialmente e gerando relatório consolidado.

Responsabilidades:
- Navegar para cada canal e aguardar playback
- Executar Monitoring_Session por canal (delegando a run_channel)
- Tratar erros inesperados por canal sem interromper execução
- Gerar ConsolidatedReport com resultados de todos os canais

Requirements: 9.1, 9.2, 9.3, 9.5
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from .audio_monitor import AudioMonitor
from .config import AudioSubtitleConfig
from .models import (
    ChannelTestReport,
    ConsolidatedReport,
    OverallStatus,
    TrackTestResult,
    TrackTestStatus,
)
from .report_generator import ReportGenerator
from .settings_dialog_manager import (
    AUDIO_SECTION_TITLE,
    SUBTITLE_SECTION_TITLE,
    SettingsDialogManager,
)
from .subtitle_monitor import SubtitleMonitor

if TYPE_CHECKING:
    from playwright.async_api import Page

    from src.player_discovery.models.capability_map import CapabilityMap

logger = logging.getLogger(__name__)


class AudioSubtitleOrchestrator:
    """Orquestrador principal do módulo de monitoramento de áudio e legendas.

    Coordena a execução sequencial de testes em múltiplos canais,
    instanciando e orquestrando os componentes SettingsDialogManager,
    AudioMonitor, SubtitleMonitor e ReportGenerator.

    Attributes:
        _page: Instância do Playwright Page para interação com o browser.
        _capability_map: Mapa de capabilities do player descoberto.
        _config: Configuração com timeouts, thresholds e canais.
        _settings_manager: Gerenciador do Settings Dialog.
        _audio_monitor: Monitor de áudio (validação + telemetria).
        _subtitle_monitor: Monitor de legendas (validação + cues).
        _report_generator: Gerador de relatórios JSON.
        _logger: Logger do módulo.
    """

    def __init__(
        self,
        page: Page,
        capability_map: CapabilityMap,
        config: AudioSubtitleConfig,
    ) -> None:
        """Inicializa o AudioSubtitleOrchestrator.

        Instancia todos os componentes necessários para execução
        dos testes de áudio e legendas.

        Args:
            page: Instância do Playwright Page.
            capability_map: CapabilityMap com estratégias de interação.
            config: Configuração completa do módulo.
        """
        self._page = page
        self._capability_map = capability_map
        self._config = config

        # Instanciar componentes
        self._settings_manager = SettingsDialogManager(
            page, capability_map, config
        )
        self._audio_monitor = AudioMonitor(page, config)
        self._subtitle_monitor = SubtitleMonitor(page, config)
        self._report_generator = ReportGenerator(config.output_dir)

        self._logger = logging.getLogger(__name__)

    async def run(self, channels: list[str]) -> ConsolidatedReport:
        """Executa testes em todos os canais configurados.

        Itera sequencialmente pela lista de canais, executando
        run_channel para cada um. Se um canal falha com exceção
        inesperada, registra o erro e avança para o próximo.

        Args:
            channels: Lista de URLs dos canais a serem testados.

        Returns:
            ConsolidatedReport com resultados de todos os canais.

        Req 9.1: Iterar pela lista de canais executando Monitoring_Session.
        Req 9.5: Se erro inesperado, registrar e avançar para próximo canal.
        """
        self._logger.info(
            "Iniciando execução multi-canal: %d canais.", len(channels)
        )
        channel_reports: list[ChannelTestReport] = []

        for channel_url in channels:
            self._logger.info("Processando canal: %s", channel_url)
            try:
                report = await self.run_channel(channel_url)
            except Exception as e:
                # Erro inesperado — criar report de erro e continuar (Req 9.5)
                self._logger.error(
                    "Erro inesperado no canal %s: %s",
                    channel_url,
                    str(e),
                )
                channel_id = channel_url.rstrip("/").split("/")[-1]
                report = ChannelTestReport(
                    channel_url=channel_url,
                    channel_id=channel_id,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    audio_results=[],
                    subtitle_results=[],
                    overall_status=OverallStatus.FAIL,
                    duration_ms=0,
                    errors=[str(e)],
                )

            channel_reports.append(report)

        # Gerar relatório consolidado (Req 9.4)
        consolidated = self._report_generator.create_consolidated_report(
            channel_reports
        )

        self._logger.info(
            "Execução multi-canal concluída: %d canais "
            "(pass=%d, partial=%d, fail=%d).",
            consolidated.total_channels,
            consolidated.channels_pass,
            consolidated.channels_partial,
            consolidated.channels_fail,
        )

        return consolidated

    async def run_channel(self, channel_url: str) -> ChannelTestReport:
        """Executa Monitoring_Session completa para um canal.

        Fluxo completo:
        1. Navegar para o canal
        2. Aguardar playback iniciar
        3. Abrir Settings Dialog
        4. Descobrir opções de áudio (UI + validação API)
        5. Descobrir opções de legendas (UI + validação API)
        6. Testar cada audio track (selecionar UI → validar API → telemetria 30s)
        7. Testar cada subtitle track (selecionar UI → validar API → aguardar cue 15s)
        8. Restaurar tracks iniciais
        9. Fechar dialog
        10. Gerar ChannelTestReport

        Args:
            channel_url: URL do canal a ser testado.

        Returns:
            ChannelTestReport com resultados de todos os tracks testados.

        Requirements: 1.1, 1.2, 1.3, 2.1, 2.2, 2.3, 3.1, 3.2, 3.7,
                      4.1, 4.2, 4.3, 5.1, 5.7, 6.5, 8.5, 10.1, 10.2,
                      10.3, 10.4
        """
        start_time = time.time()
        channel_id = channel_url.rstrip("/").split("/")[-1]
        audio_results: list[TrackTestResult] = []
        subtitle_results: list[TrackTestResult] = []

        self._logger.info(
            "Iniciando Monitoring_Session completa para canal %s",
            channel_id,
        )

        # 1. Navegar para o canal
        if not await self._navigate_to_channel(channel_url):
            return self._error_report(
                channel_url, channel_id, start_time,
                ["navigation_failed"],
            )

        # 2. Aguardar playback iniciar (Req 9.2)
        if not await self._wait_for_playback(
            self._config.playback_wait_timeout_s
        ):
            return self._error_report(
                channel_url, channel_id, start_time,
                ["playback_not_started"],
            )

        # 3. Abrir Settings Dialog (Req 1.1, 1.2)
        if not await self._settings_manager.open_dialog():
            return self._error_report(
                channel_url, channel_id, start_time,
                ["settings_dialog_unavailable"],
            )

        # 4. Descobrir opções de áudio (Req 2.1, 2.2)
        audio_options = await self._settings_manager.discover_audio_options()
        initial_audio = next(
            (o.text for o in audio_options if o.is_selected), None
        )

        # 5. Descobrir opções de legendas (Req 4.1, 4.2)
        subtitle_options = (
            await self._settings_manager.discover_subtitle_options()
        )
        initial_subtitle = next(
            (o.text for o in subtitle_options if o.is_selected), None
        )

        # 6. Testar cada audio track (Req 3.1, 3.2, 3.3, 10.1, 10.4)
        for option in audio_options:
            result = await self._test_audio_track(option.text)
            audio_results.append(result)

        # 7. Testar cada subtitle track excluindo "Desativadas" (Req 5.1)
        for option in subtitle_options:
            if option.text == "Desativadas":
                continue
            result = await self._test_subtitle_track(option.text)
            subtitle_results.append(result)

        # 8. Restaurar tracks iniciais (Req 3.7, 5.7)
        if initial_audio:
            await self._settings_manager.select_option(
                AUDIO_SECTION_TITLE, initial_audio
            )
        if initial_subtitle:
            await self._settings_manager.select_option(
                SUBTITLE_SECTION_TITLE, initial_subtitle
            )

        # 9. Fechar dialog (Req 6.5)
        await self._settings_manager.close_dialog()

        # 10. Gerar relatório
        duration_ms = int((time.time() - start_time) * 1000)

        self._logger.info(
            "Monitoring_Session concluída para canal %s em %dms. "
            "Audio tracks: %d, Subtitle tracks: %d.",
            channel_id,
            duration_ms,
            len(audio_results),
            len(subtitle_results),
        )

        return self._report_generator.create_channel_report(
            channel_url=channel_url,
            audio_results=audio_results,
            subtitle_results=subtitle_results,
            duration_ms=duration_ms,
        )

    async def _test_audio_track(self, track_name: str) -> TrackTestResult:
        """Testa um audio track: selecionar UI → validar API → coletar telemetria.

        Fluxo:
        1. Capturar api_state_before via Shaka API
        2. Selecionar track via UI (Settings Dialog)
        3. Validar mudança via Shaka API (timeout configurável)
        4. Capturar api_state_after
        5. Se validação falhou: retornar FAIL com evidence
        6. Coletar telemetria de áudio durante 30s
        7. Classificar resultado (PASS se >=80% amostras com áudio)

        Args:
            track_name: Nome do track a ser testado (ex: "Português").

        Returns:
            TrackTestResult com status, evidence, telemetria e api_states.

        Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 10.1, 10.4
        """
        start = time.time()
        self._logger.info("Testando audio track: '%s'", track_name)

        # Capturar api_state_before (Req 10.4)
        api_state_before = await self._audio_monitor.get_active_tracks()

        # Selecionar via UI (Req 3.1)
        await self._settings_manager.select_option(
            AUDIO_SECTION_TITLE, track_name
        )

        # Validar via Shaka API (Req 3.2, 10.1)
        validation = await self._audio_monitor.validate_track_switch(
            track_name, self._config.track_switch_timeout_s
        )

        # Capturar api_state_after (Req 10.4)
        api_state_after = await self._audio_monitor.get_active_tracks()

        if not validation.success:
            duration_ms = int((time.time() - start) * 1000)
            self._logger.warning(
                "Audio track '%s': switch não confirmado pela API.",
                track_name,
            )
            return TrackTestResult(
                track_name=track_name,
                track_type="audio",
                status=TrackTestStatus.FAIL,
                evidence={
                    "error": validation.error
                    or "track_switch_not_confirmed"
                },
                duration_ms=duration_ms,
                api_state_before={"tracks": api_state_before},
                api_state_after={"tracks": api_state_after},
            )

        # Coletar telemetria de áudio por 30s (Req 3.3)
        telemetry = await self._audio_monitor.collect_telemetry(
            self._config.audio_telemetry_window_s,
            self._config.audio_sample_interval_s,
        )

        # Classificar resultado (Req 3.4, 3.5)
        status = self._audio_monitor.classify_result(telemetry)
        duration_ms = int((time.time() - start) * 1000)

        self._logger.info(
            "Audio track '%s': status=%s, "
            "audio_present_ratio=%.2f, rms_avg=%.4f",
            track_name,
            status.value,
            telemetry.audio_present_ratio,
            telemetry.rms_avg,
        )

        return TrackTestResult(
            track_name=track_name,
            track_type="audio",
            status=status,
            evidence={
                "audio_present_ratio": telemetry.audio_present_ratio,
                "rms_avg": telemetry.rms_avg,
            },
            duration_ms=duration_ms,
            telemetry=telemetry.to_dict(),
            api_state_before={"tracks": api_state_before},
            api_state_after={"tracks": api_state_after},
        )

    async def _test_subtitle_track(
        self, track_name: str
    ) -> TrackTestResult:
        """Testa um subtitle track: selecionar UI → validar API → aguardar cue.

        Fluxo:
        1. Capturar api_state_before via Shaka API
        2. Selecionar track via UI (Settings Dialog)
        3. Validar mudança via Shaka API (timeout configurável)
        4. Capturar api_state_after
        5. Se validação falhou: retornar FAIL com evidence
        6. Aguardar cue ativa durante 15s
        7. Retornar PASS se cue encontrada, TIMEOUT caso contrário

        Args:
            track_name: Nome do track a ser testado (ex: "Português").

        Returns:
            TrackTestResult com status, evidence e api_states.

        Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 10.2, 10.4
        """
        start = time.time()
        self._logger.info("Testando subtitle track: '%s'", track_name)

        # Capturar api_state_before (Req 10.4)
        api_state_before = (
            await self._subtitle_monitor.get_active_tracks()
        )

        # Selecionar via UI (Req 5.1)
        await self._settings_manager.select_option(
            SUBTITLE_SECTION_TITLE, track_name
        )

        # Validar via Shaka API (Req 5.2, 10.2)
        validation = await self._subtitle_monitor.validate_track_switch(
            track_name, self._config.track_switch_timeout_s
        )

        # Capturar api_state_after (Req 10.4)
        api_state_after = (
            await self._subtitle_monitor.get_active_tracks()
        )

        if not validation.success:
            duration_ms = int((time.time() - start) * 1000)
            self._logger.warning(
                "Subtitle track '%s': switch não confirmado pela API.",
                track_name,
            )
            return TrackTestResult(
                track_name=track_name,
                track_type="subtitle",
                status=TrackTestStatus.FAIL,
                evidence={
                    "error": validation.error
                    or "subtitle_switch_not_confirmed"
                },
                duration_ms=duration_ms,
                api_state_before={"tracks": api_state_before},
                api_state_after={"tracks": api_state_after},
            )

        # Aguardar cue ativa por 15s (Req 5.3)
        cue_result = await self._subtitle_monitor.wait_for_active_cue(
            self._config.subtitle_cue_timeout_s,
            self._config.subtitle_poll_interval_s,
        )

        duration_ms = int((time.time() - start) * 1000)

        if cue_result.found:
            self._logger.info(
                "Subtitle track '%s': cue encontrada em %dms.",
                track_name,
                cue_result.time_to_first_cue_ms or 0,
            )
            return TrackTestResult(
                track_name=track_name,
                track_type="subtitle",
                status=TrackTestStatus.PASS,
                evidence={
                    "cue_text": cue_result.cue_text,
                    "time_to_first_cue_ms": (
                        cue_result.time_to_first_cue_ms
                    ),
                },
                duration_ms=duration_ms,
                api_state_before={"tracks": api_state_before},
                api_state_after={"tracks": api_state_after},
            )
        else:
            self._logger.warning(
                "Subtitle track '%s': timeout aguardando cue.",
                track_name,
            )
            return TrackTestResult(
                track_name=track_name,
                track_type="subtitle",
                status=TrackTestStatus.TIMEOUT,
                evidence={
                    "error": cue_result.error
                    or "no_active_cues_within_15s"
                },
                duration_ms=duration_ms,
                api_state_before={"tracks": api_state_before},
                api_state_after={"tracks": api_state_after},
            )

    def _error_report(
        self,
        channel_url: str,
        channel_id: str,
        start_time: float,
        errors: list[str],
    ) -> ChannelTestReport:
        """Cria um ChannelTestReport de erro para falhas early-exit.

        Utilizado quando a sessão precisa ser encerrada prematuramente
        (navegação falhou, playback não iniciou, dialog indisponível).

        Args:
            channel_url: URL do canal.
            channel_id: Identificador do canal.
            start_time: Timestamp do início da sessão (time.time()).
            errors: Lista de erros a serem registrados.

        Returns:
            ChannelTestReport com overall_status=FAIL e erros.
        """
        duration_ms = int((time.time() - start_time) * 1000)
        self._logger.warning(
            "Monitoring_Session encerrada com erro para canal %s: %s",
            channel_id,
            errors,
        )
        return ChannelTestReport(
            channel_url=channel_url,
            channel_id=channel_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            audio_results=[],
            subtitle_results=[],
            overall_status=OverallStatus.FAIL,
            duration_ms=duration_ms,
            errors=errors,
        )

    async def _navigate_to_channel(self, url: str) -> bool:
        """Navega para canal e aguarda DOM carregado.

        Utiliza Playwright page.goto com wait_until="domcontentloaded"
        para garantir que o DOM está pronto antes de prosseguir.

        Args:
            url: URL completa do canal.

        Returns:
            True se a navegação foi bem-sucedida, False caso contrário.
        """
        self._logger.debug("Navegando para %s...", url)
        try:
            await self._page.goto(url, wait_until="domcontentloaded")
            self._logger.info("Navegação concluída para %s.", url)
            return True
        except Exception as e:
            self._logger.error(
                "Erro ao navegar para %s: %s", url, str(e)
            )
            return False

    async def _wait_for_playback(self, timeout_s: float = 30.0) -> bool:
        """Aguarda player iniciar reprodução (currentTime avançando).

        Faz polling de document.querySelector('video').currentTime,
        verificando se o valor é > 0 e está avançando entre duas
        leituras consecutivas.

        O polling ocorre a cada 1 segundo até o timeout.

        Args:
            timeout_s: Tempo máximo de espera em segundos. Padrão: 30.0.

        Returns:
            True se playback confirmado (currentTime avançando),
            False se timeout atingido.

        Req 9.2: Aguardar reprodução (currentTime avançando) por até 30s.
        Req 9.3: Se não iniciar em 30s, classificar como
        "playback_not_started".
        """
        self._logger.debug(
            "Aguardando playback iniciar (timeout=%.1fs)...", timeout_s
        )

        poll_interval = 1.0
        deadline = time.time() + timeout_s
        previous_time: float = 0.0

        js_get_current_time = (
            "() => document.querySelector('video')?.currentTime || 0"
        )

        while time.time() < deadline:
            try:
                current_time = await self._page.evaluate(
                    js_get_current_time
                )
            except Exception as e:
                self._logger.warning(
                    "Erro ao consultar currentTime: %s", str(e)
                )
                current_time = 0.0

            # Verificar se currentTime > 0 e está avançando
            if current_time > 0 and current_time > previous_time:
                self._logger.info(
                    "Playback confirmado: currentTime=%.2f",
                    current_time,
                )
                return True

            previous_time = current_time
            await asyncio.sleep(poll_interval)

        self._logger.warning(
            "Timeout: playback não iniciou em %.1fs.", timeout_s
        )
        return False
