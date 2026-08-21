"""UnifiedOrchestrator — orquestrador principal do monitoramento unificado.

Orquestrador de monitoramento unificado de canais.

Coordena todo o ciclo de vida de monitoramento:
- Navegação e espera por playback
- Discovery de capabilities (com reuso e invalidação)
- Coleta de telemetria de vídeo em background
- Testes de áudio e legendas
- Verificação e recuperação de playback entre fases
- Escalação deferida
- Geração de relatórios unificados e consolidados
- Modo contínuo (loop) com shutdown graceful

Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 3.1, 3.2, 3.3, 3.4, 3.5,
              9.1, 9.2, 9.3, 9.4, 9.5, 11.1, 11.2, 11.3, 11.4, 11.5
"""

from __future__ import annotations

import asyncio
import logging
import platform
import signal
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from src.unified_channel_monitor.audio_tester import AudioTrackTester
from src.unified_channel_monitor.config import UnifiedMonitorConfig
from src.unified_channel_monitor.escalation import EscalationManager
from src.unified_channel_monitor.models import (
    AudioTrackResult,
    ChannelSessionStatus,
    ConsolidatedReport,
    SubtitleTrackResult,
    TelemetrySummary,
    UnifiedChannelReport,
)
from src.unified_channel_monitor.report_generator import UnifiedReportGenerator
from src.unified_channel_monitor.subtitle_tester import SubtitleTrackTester
from src.unified_channel_monitor.video_telemetry import VideoTelemetryCollector

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext, Page

    from src.bedrock_client import BedrockClient
    from src.frame_capturer import FrameCapturer
    from src.opencv_analyzer import OpenCVAnalyzer

logger = logging.getLogger(__name__)


class UnifiedOrchestrator:
    """Orquestrador unificado de monitoramento de canais.

    Coordena sequencialmente por canal: navegação → discovery (se necessário)
    → telemetria → testes de áudio → verificação de playback → testes de
    legendas → escalação → relatório. Implementa fail-forward: exceções em
    um canal resultam em status ERROR/UNREACHABLE sem interromper a rotação.

    Attributes:
        _page: Instância Playwright Page compartilhada.
        _config: Configuração unificada do monitor.
        _capability_map: Mapa de capabilities do player (reutilizado).
        _consecutive_failures: Contador de falhas consecutivas para
            invalidação do CapabilityMap.
        _shutting_down: Flag de shutdown graceful.
    """

    def __init__(
        self,
        page: Page,
        config: UnifiedMonitorConfig,
        frame_capturer: FrameCapturer | None = None,
        opencv_analyzer: OpenCVAnalyzer | None = None,
        bedrock_client: BedrockClient | None = None,
        browser_context: BrowserContext | None = None,
    ) -> None:
        """Inicializa o orquestrador unificado.

        Args:
            page: Instância Playwright Page compartilhada por todos
                os componentes.
            config: Configuração unificada com timeouts, thresholds
                e diretório de output.
            frame_capturer: Capturador de frames para escalação (opcional).
            opencv_analyzer: Analisador OpenCV para escalação (opcional).
            bedrock_client: Cliente Bedrock para diagnóstico IA (opcional).
            browser_context: Contexto do browser Playwright para
                cleanup no shutdown (opcional).
        """
        self._page = page
        self._config = config
        self._frame_capturer = frame_capturer
        self._opencv_analyzer = opencv_analyzer
        self._bedrock_client = bedrock_client
        self._browser_context = browser_context

        # Estado do CapabilityMap
        self._capability_map = None
        self._consecutive_failures: int = 0

        # Shutdown graceful
        self._shutting_down: bool = False
        self._exit_code: int = 0

        # Componentes internos
        self._report_generator = UnifiedReportGenerator(config.output_dir)
        self._escalation_manager = EscalationManager(
            page=page,
            frame_capturer=frame_capturer,
            opencv_analyzer=opencv_analyzer,
            bedrock_client=bedrock_client,
        )

        logger.info(
            "UnifiedOrchestrator inicializado",
            extra={
                "output_dir": config.output_dir,
                "invalidation_threshold": config.invalidation_threshold,
                "playback_wait_timeout_s": config.playback_wait_timeout_s,
                "telemetry_interval_s": config.telemetry_interval_s,
            },
        )

    async def run_single_rotation(
        self, channels: list[str]
    ) -> ConsolidatedReport:
        """Executa uma única rotação por todos os canais.

        Processa cada canal sequencialmente com fail-forward: exceção
        em um canal resulta em status ERROR/UNREACHABLE sem interromper
        o processamento dos demais.

        Após N falhas consecutivas (configurável via invalidation_threshold),
        o CapabilityMap é invalidado para forçar re-discovery no próximo canal.

        Args:
            channels: Lista de URLs dos canais a monitorar.

        Returns:
            ConsolidatedReport com resultados de todos os canais.
        """
        rotation_start = time.time()
        channel_reports: list[UnifiedChannelReport] = []

        logger.info(
            "Iniciando rotação com %d canais",
            len(channels),
            extra={"total_channels": len(channels)},
        )

        for channel_url in channels:
            # Verificar shutdown entre canais
            if self._shutting_down:
                logger.info(
                    "Shutdown detectado — interrompendo rotação",
                    extra={"channels_completed": len(channel_reports)},
                )
                break

            try:
                # Se shutdown foi solicitado durante a sessão anterior,
                # aplicar timeout de 10s para sessão atual completar
                if self._shutting_down:
                    report = await asyncio.wait_for(
                        self._run_channel_session(channel_url),
                        timeout=10.0,
                    )
                else:
                    report = await self._run_channel_session(
                        channel_url
                    )
                channel_reports.append(report)
                self._consecutive_failures = 0

                logger.info(
                    "Canal processado com sucesso",
                    extra={
                        "channel_url": channel_url,
                        "session_id": report.session_id,
                        "status": report.status,
                    },
                )

            except asyncio.TimeoutError:
                # Timeout de shutdown — gerar relatório parcial
                duration_ms = int(
                    (time.time() - rotation_start) * 1000
                )
                report = self._create_partial_channel_report(
                    channel_url=channel_url,
                    duration_ms=duration_ms,
                )
                channel_reports.append(report)

                logger.warning(
                    "Sessão interrompida por timeout de shutdown "
                    "(10s)",
                    extra={
                        "channel_url": channel_url,
                        "session_id": report.session_id,
                    },
                )
                break

            except TimeoutError as exc:
                # Canal inacessível — marcar UNREACHABLE
                self._consecutive_failures += 1
                report = self._create_error_report(
                    channel_url=channel_url,
                    status=ChannelSessionStatus.UNREACHABLE.value,
                    error_msg=f"Timeout ao acessar canal: {exc}",
                    duration_ms=0,
                )
                channel_reports.append(report)

                logger.warning(
                    "Canal UNREACHABLE (timeout)",
                    extra={
                        "channel_url": channel_url,
                        "session_id": report.session_id,
                        "consecutive_failures": (
                            self._consecutive_failures
                        ),
                        "error": str(exc),
                    },
                )

            except Exception as exc:
                # Erro inesperado — marcar ERROR
                self._consecutive_failures += 1
                report = self._create_error_report(
                    channel_url=channel_url,
                    status=ChannelSessionStatus.ERROR.value,
                    error_msg=f"Erro inesperado: {exc}",
                    duration_ms=0,
                )
                channel_reports.append(report)

                logger.error(
                    "Canal ERROR (exceção inesperada)",
                    extra={
                        "channel_url": channel_url,
                        "session_id": report.session_id,
                        "consecutive_failures": (
                            self._consecutive_failures
                        ),
                        "error": str(exc),
                    },
                    exc_info=True,
                )

            # Invalidação de CapabilityMap após N falhas consecutivas
            if (
                self._consecutive_failures
                >= self._config.invalidation_threshold
            ):
                self._invalidate_capability_map()

            # Verificar shutdown após processar canal
            if self._shutting_down:
                logger.info(
                    "Shutdown detectado após canal — "
                    "interrompendo rotação",
                    extra={
                        "channels_completed": len(channel_reports)
                    },
                )
                break

        # Gerar relatório consolidado
        consolidated = self._report_generator.create_consolidated_report(
            channel_reports
        )

        # Marcar como parcial se shutdown interrompeu
        if self._shutting_down and len(channel_reports) < len(channels):
            consolidated.is_partial = True

        # Persistir relatório
        rotation_duration_ms = int((time.time() - rotation_start) * 1000)
        timestamp_str = datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H-%M-%S"
        )

        # Escolher nome do arquivo baseado no estado
        if consolidated.is_partial:
            filename = (
                f"consolidated_report_PARTIAL_{timestamp_str}.json"
            )
        else:
            filename = f"consolidated_report_{timestamp_str}.json"

        self._report_generator.persist_report(
            report=asdict(consolidated),
            filename=filename,
        )

        logger.info(
            "Rotação concluída",
            extra={
                "total_channels": len(channels),
                "processed": len(channel_reports),
                "duration_ms": rotation_duration_ms,
                "is_partial": consolidated.is_partial,
            },
        )

        return consolidated

    async def run_continuous(self, channels: list[str]) -> int:
        """Executa rotações em loop até shutdown.

        Cada rotação processa todos os canais na lista. O loop continua
        até que shutdown() seja chamado (via SIGINT ou programaticamente).

        Args:
            channels: Lista de URLs dos canais a monitorar.

        Returns:
            Exit code: 0 para clean shutdown, 1 para erro.
        """
        rotation_count = 0

        logger.info(
            "Modo contínuo iniciado",
            extra={"channels": len(channels)},
        )

        try:
            while not self._shutting_down:
                rotation_count += 1
                logger.info(
                    "Iniciando rotação #%d",
                    rotation_count,
                    extra={"rotation": rotation_count},
                )

                await self.run_single_rotation(channels)

                if self._shutting_down:
                    break

                # Pequena pausa entre rotações para não sobrecarregar
                await asyncio.sleep(1.0)

        except Exception as exc:
            logger.error(
                "Erro fatal no modo contínuo: %s",
                exc,
                exc_info=True,
            )
            self._exit_code = 1

        finally:
            # Cleanup do browser no shutdown
            await self.close_browser()

        logger.info(
            "Modo contínuo encerrado após %d rotações",
            rotation_count,
            extra={
                "total_rotations": rotation_count,
                "exit_code": self._exit_code,
            },
        )

        return self._exit_code

    async def shutdown(self) -> None:
        """Shutdown graceful: completa operação atual, salva parciais.

        Seta flag _shutting_down para que o loop principal interrompa
        entre canais. A sessão em andamento tem tempo para completar
        antes de ser cancelada.
        """
        if self._shutting_down:
            logger.warning("Shutdown já em andamento — ignorando duplicata")
            return

        logger.info("Shutdown solicitado — finalizando operação atual")
        self._shutting_down = True

    def register_signal_handlers(self) -> None:
        """Registra handler para SIGINT (Ctrl+C) no event loop.

        No Linux/macOS usa asyncio add_signal_handler.
        No Windows usa signal.signal como fallback, pois
        add_signal_handler não suporta SIGINT no Windows.
        """
        if platform.system() == "Windows":
            self._register_signal_windows()
        else:
            self._register_signal_unix()

    def _register_signal_unix(self) -> None:
        """Registra SIGINT handler via asyncio (Unix/macOS)."""
        try:
            loop = asyncio.get_event_loop()
            loop.add_signal_handler(
                signal.SIGINT,
                self._handle_sigint,
            )
            logger.info(
                "Signal handler SIGINT registrado (asyncio)"
            )
        except (NotImplementedError, RuntimeError) as exc:
            logger.warning(
                "Falha ao registrar signal handler via asyncio: %s. "
                "Usando fallback signal.signal()",
                exc,
            )
            self._register_signal_windows()

    def _register_signal_windows(self) -> None:
        """Registra SIGINT handler via signal.signal (Windows)."""
        signal.signal(signal.SIGINT, self._handle_sigint_sync)
        logger.info(
            "Signal handler SIGINT registrado (signal.signal)"
        )

    def _handle_sigint(self) -> None:
        """Handler de SIGINT para asyncio (Unix).

        Agenda o shutdown como task no event loop.
        """
        logger.info("SIGINT recebido — iniciando shutdown graceful")
        asyncio.ensure_future(self.shutdown())

    def _handle_sigint_sync(
        self, signum: int, frame: object
    ) -> None:
        """Handler de SIGINT síncrono (Windows).

        Args:
            signum: Número do sinal recebido.
            frame: Frame stack atual (não utilizado).
        """
        logger.info(
            "SIGINT recebido (sync handler) — iniciando shutdown"
        )
        self._shutting_down = True

    @property
    def exit_code(self) -> int:
        """Retorna o exit code do processo.

        Returns:
            0 para clean shutdown, 1 para erro.
        """
        return self._exit_code

    async def close_browser(self) -> None:
        """Fecha o browser context do Playwright.

        Tenta fechar o contexto de forma limpa. Se falhar,
        loga o erro sem propagar a exceção.
        """
        if self._browser_context is None:
            logger.info(
                "Nenhum browser_context para fechar"
            )
            return

        try:
            await self._browser_context.close()
            logger.info("Browser context fechado com sucesso")
        except Exception as exc:
            logger.error(
                "Erro ao fechar browser context: %s",
                exc,
                exc_info=True,
            )

    async def _persist_partial_results(
        self,
        channel_reports: list[UnifiedChannelReport],
        total_channels: int,
    ) -> None:
        """Persiste resultados parciais durante shutdown.

        Gera um ConsolidatedReport marcado como parcial com os
        relatórios coletados até o momento da interrupção.

        Args:
            channel_reports: Relatórios já coletados.
            total_channels: Número total de canais na rotação.
        """
        if not channel_reports:
            logger.info(
                "Nenhum resultado parcial para persistir"
            )
            return

        consolidated = (
            self._report_generator.create_consolidated_report(
                channel_reports
            )
        )
        consolidated.is_partial = True

        timestamp_str = datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H-%M-%S"
        )
        filename = (
            f"consolidated_report_PARTIAL_{timestamp_str}.json"
        )

        self._report_generator.persist_report(
            report=asdict(consolidated),
            filename=filename,
        )

        logger.info(
            "Relatório parcial persistido (shutdown)",
            extra={
                "filename": filename,
                "channels_completed": len(channel_reports),
                "total_channels": total_channels,
            },
        )

    def _create_partial_channel_report(
        self,
        channel_url: str,
        duration_ms: int,
    ) -> UnifiedChannelReport:
        """Cria relatório parcial para canal interrompido no shutdown.

        Gera UnifiedChannelReport com status PARTIAL e dados
        disponíveis até o momento da interrupção.

        Args:
            channel_url: URL do canal interrompido.
            duration_ms: Duração até a interrupção em milissegundos.

        Returns:
            UnifiedChannelReport parcial com dados disponíveis.
        """
        session_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()
        channel_id = (
            UnifiedReportGenerator._derive_channel_id(channel_url)
        )

        return UnifiedChannelReport(
            channel_url=channel_url,
            channel_id=channel_id,
            session_id=session_id,
            timestamp=timestamp,
            status=ChannelSessionStatus.PARTIAL.value,
            duration_ms=duration_ms,
            video_summary=TelemetrySummary(total_samples=0),
            audio_tracks_tested=0,
            audio_tracks_passed=0,
            audio_results=[],
            subtitle_tracks_tested=0,
            subtitle_tracks_passed=0,
            subtitle_results=[],
            escalation_results=[],
            telemetry_annotations=[],
            errors=["Sessão interrompida por shutdown graceful"],
        )

    async def _run_channel_session(
        self, channel_url: str
    ) -> UnifiedChannelReport:
        """Executa sessão completa de monitoramento para um canal.

        Sequência:
        1. Navegar para o canal e aguardar elemento <video>
        2. Discovery (se CapabilityMap não disponível)
        3. Iniciar coleta de telemetria em background
        4. Ativar flag de track testing na escalação
        5. Testar tracks de áudio
        6. Verificar playback (recovery se necessário)
        7. Testar tracks de legendas
        8. Desativar flag de track testing
        9. Parar telemetria → TelemetrySummary
        10. Processar escalações deferidas
        11. Gerar relatório unificado

        Args:
            channel_url: URL do canal a monitorar.

        Returns:
            UnifiedChannelReport com todos os resultados.

        Raises:
            TimeoutError: Se navegação ou espera por vídeo exceder timeout.
            Exception: Qualquer erro não tratado durante a sessão.
        """
        session_id = str(uuid.uuid4())
        session_start = time.time()

        logger.info(
            "Sessão iniciada",
            extra={
                "session_id": session_id,
                "channel_url": channel_url,
            },
        )

        # 1. Navegação
        await self._navigate_to_channel(channel_url, session_id)

        # 2. Discovery (se necessário)
        await self._ensure_capability_map(session_id)

        # 3. Iniciar telemetria
        telemetry_collector = VideoTelemetryCollector(self._config)
        await telemetry_collector.start(
            self._page, self._config.telemetry_interval_s
        )
        logger.info(
            "Telemetria iniciada",
            extra={"session_id": session_id},
        )

        # 4. Ativar flag de track testing
        self._escalation_manager.set_track_testing_active(True)

        # 5. Testar áudio
        audio_results = await self._test_audio_tracks(
            telemetry_collector, session_id
        )

        # 6. Verificar playback (recovery entre áudio e legendas)
        playback_ok = await self._verify_playback(session_id)

        # 7. Testar legendas
        if playback_ok:
            subtitle_results = await self._test_subtitle_tracks(
                telemetry_collector, session_id
            )
        else:
            # Playback perdido — marcar legendas como SKIP
            subtitle_results = []
            logger.warning(
                "Playback perdido — testes de legenda pulados",
                extra={"session_id": session_id},
            )

        # 8. Desativar flag de track testing
        self._escalation_manager.set_track_testing_active(False)

        # 9. Parar telemetria
        telemetry_summary = await telemetry_collector.stop()
        logger.info(
            "Telemetria finalizada",
            extra={
                "session_id": session_id,
                "total_samples": telemetry_summary.total_samples,
                "health": telemetry_summary.health_classification,
            },
        )

        # Enfileirar escalações detectadas pela telemetria
        deferred = telemetry_collector.get_deferred_escalations()
        for esc in deferred:
            self._escalation_manager.defer_escalation(esc)

        # 10. Processar escalações deferidas
        escalation_results = (
            await self._escalation_manager.process_deferred()
        )
        logger.info(
            "Escalações processadas",
            extra={
                "session_id": session_id,
                "escalations_count": len(escalation_results),
            },
        )

        # 11. Gerar relatório
        duration_ms = int((time.time() - session_start) * 1000)
        report = self._report_generator.create_channel_report(
            channel_url=channel_url,
            video_summary=telemetry_summary,
            audio_results=audio_results,
            subtitle_results=subtitle_results,
            escalation_results=escalation_results,
            duration_ms=duration_ms,
        )

        # Sobrescrever session_id gerado pelo report_generator com o nosso
        report.session_id = session_id

        logger.info(
            "Sessão concluída",
            extra={
                "session_id": session_id,
                "channel_url": channel_url,
                "status": report.status,
                "duration_ms": duration_ms,
            },
        )

        return report

    async def _navigate_to_channel(
        self, channel_url: str, session_id: str
    ) -> None:
        """Navega para a URL do canal e aguarda elemento <video>.

        Args:
            channel_url: URL do canal.
            session_id: ID da sessão para logging.

        Raises:
            TimeoutError: Se navegação ou espera pelo vídeo exceder timeout.
        """
        timeout_ms = int(self._config.playback_wait_timeout_s * 1000)

        logger.info(
            "Navegando para canal",
            extra={
                "session_id": session_id,
                "channel_url": channel_url,
                "timeout_ms": timeout_ms,
            },
        )

        await self._page.goto(channel_url, timeout=timeout_ms)
        await self._page.wait_for_selector(
            "video", timeout=timeout_ms
        )

        logger.info(
            "Elemento <video> detectado — playback iniciando",
            extra={"session_id": session_id},
        )

    async def _ensure_capability_map(self, session_id: str) -> None:
        """Garante que o CapabilityMap está disponível.

        Discovery executa apenas na primeira vez ou após invalidação.
        Se já existe um CapabilityMap válido, reutiliza sem re-executar.

        Args:
            session_id: ID da sessão para logging.
        """
        if self._capability_map is not None:
            logger.info(
                "CapabilityMap reutilizado (já disponível)",
                extra={"session_id": session_id},
            )
            return

        logger.info(
            "Executando discovery (CapabilityMap não disponível)",
            extra={"session_id": session_id},
        )

        self._capability_map = await self._run_discovery(session_id)

        logger.info(
            "Discovery concluído — CapabilityMap disponível",
            extra={"session_id": session_id},
        )

    async def _run_discovery(self, session_id: str):
        """Executa discovery de capabilities do player.

        Tenta usar o DiscoveryEngine existente. Se não disponível,
        retorna um mapa placeholder com seletores comuns.

        Args:
            session_id: ID da sessão para logging.

        Returns:
            CapabilityMap (objeto) ou dict placeholder.
        """
        try:
            from src.player_discovery.discovery.engine import DiscoveryEngine

            engine = DiscoveryEngine()
            capability_map = await engine.discover(self._page)

            logger.info(
                "Discovery via DiscoveryEngine concluído",
                extra={"session_id": session_id},
            )

            # Retorna o objeto CapabilityMap diretamente
            # (SettingsDialogManager precisa de get_interaction_strategy())
            return capability_map

        except ImportError:
            logger.warning(
                "DiscoveryEngine não disponível — usando placeholder",
                extra={"session_id": session_id},
            )
            return self._create_placeholder_capability_map()

        except Exception as exc:
            logger.error(
                "Erro no Discovery — usando placeholder",
                extra={
                    "session_id": session_id,
                    "error": str(exc),
                },
                exc_info=True,
            )
            return self._create_placeholder_capability_map()

    def _create_placeholder_capability_map(self) -> dict:
        """Cria CapabilityMap placeholder com seletores comuns.

        Returns:
            Dicionário com seletores genéricos de player.
        """
        return {
            "settings": {
                "selector": (
                    'button[aria-label*="settings"], '
                    'button[aria-label*="configurações"], '
                    ".settings-button"
                ),
            },
            "video": {"selector": "video"},
            "player_type": "unknown",
        }

    def _invalidate_capability_map(self) -> None:
        """Invalida o CapabilityMap para forçar re-discovery.

        Chamado após N falhas consecutivas (configurável via
        config.invalidation_threshold). Reseta o contador de falhas.
        """
        logger.warning(
            "CapabilityMap invalidado após %d falhas consecutivas",
            self._consecutive_failures,
            extra={
                "consecutive_failures": self._consecutive_failures,
                "threshold": self._config.invalidation_threshold,
            },
        )
        self._capability_map = None
        self._consecutive_failures = 0

    async def _test_audio_tracks(
        self,
        telemetry_collector: VideoTelemetryCollector,
        session_id: str,
    ) -> list[AudioTrackResult]:
        """Executa testes de todos os tracks de áudio.

        Args:
            telemetry_collector: Coletor de telemetria ativo.
            session_id: ID da sessão para logging.

        Returns:
            Lista de AudioTrackResult.
        """
        logger.info(
            "Iniciando testes de áudio",
            extra={"session_id": session_id},
        )

        audio_tester = AudioTrackTester(
            page=self._page,
            capability_map=self._capability_map,
            config=self._config,
            telemetry_collector=telemetry_collector,
        )

        try:
            results = await audio_tester.test_all_tracks()
            logger.info(
                "Testes de áudio concluídos",
                extra={
                    "session_id": session_id,
                    "tracks_tested": len(results),
                    "tracks_passed": sum(
                        1 for r in results if r.status == "PASS"
                    ),
                },
            )
            return results

        except Exception as exc:
            logger.error(
                "Erro nos testes de áudio",
                extra={
                    "session_id": session_id,
                    "error": str(exc),
                },
                exc_info=True,
            )
            return []

    async def _verify_playback(self, session_id: str) -> bool:
        """Verifica se o vídeo continua reproduzindo e tenta recovery.

        Consulta video.paused via page.evaluate(). Se pausado, tenta
        chamar video.play() e aguarda até 5s por currentTime avançar.

        Args:
            session_id: ID da sessão para logging.

        Returns:
            True se playback está ativo, False se recovery falhou.
        """
        logger.info(
            "Verificando playback",
            extra={"session_id": session_id},
        )

        try:
            is_paused = await self._page.evaluate(
                "() => { const v = document.querySelector('video'); "
                "return v ? v.paused : true; }"
            )

            if not is_paused:
                logger.info(
                    "Playback ativo — continuando",
                    extra={"session_id": session_id},
                )
                return True

            # Playback pausado — tentar recovery
            logger.warning(
                "Playback pausado — tentando recovery",
                extra={"session_id": session_id},
            )

            await self._page.evaluate(
                "() => { const v = document.querySelector('video'); "
                "if (v) v.play(); }"
            )

            # Aguardar até 5s por currentTime avançar
            initial_time = await self._page.evaluate(
                "() => { const v = document.querySelector('video'); "
                "return v ? v.currentTime : 0; }"
            )

            recovery_timeout = 5.0
            poll_interval = 0.5
            elapsed = 0.0

            while elapsed < recovery_timeout:
                await asyncio.sleep(poll_interval)
                elapsed += poll_interval

                current_time = await self._page.evaluate(
                    "() => { const v = document.querySelector('video'); "
                    "return v ? v.currentTime : 0; }"
                )

                if current_time > initial_time:
                    logger.info(
                        "Playback recovery bem-sucedido",
                        extra={
                            "session_id": session_id,
                            "recovered_after_s": elapsed,
                        },
                    )
                    return True

            logger.error(
                "Playback recovery falhou — currentTime não avançou",
                extra={
                    "session_id": session_id,
                    "initial_time": initial_time,
                },
            )
            return False

        except Exception as exc:
            logger.error(
                "Erro ao verificar playback",
                extra={
                    "session_id": session_id,
                    "error": str(exc),
                },
                exc_info=True,
            )
            return False

    async def _test_subtitle_tracks(
        self,
        telemetry_collector: VideoTelemetryCollector,
        session_id: str,
    ) -> list[SubtitleTrackResult]:
        """Executa testes de todos os tracks de legendas.

        Args:
            telemetry_collector: Coletor de telemetria ativo.
            session_id: ID da sessão para logging.

        Returns:
            Lista de SubtitleTrackResult.
        """
        logger.info(
            "Iniciando testes de legendas",
            extra={"session_id": session_id},
        )

        subtitle_tester = SubtitleTrackTester(
            page=self._page,
            capability_map=self._capability_map,
            config=self._config,
            telemetry_collector=telemetry_collector,
        )

        try:
            results = await subtitle_tester.test_all_tracks()
            logger.info(
                "Testes de legendas concluídos",
                extra={
                    "session_id": session_id,
                    "tracks_tested": len(results),
                    "tracks_passed": sum(
                        1 for r in results if r.status == "PASS"
                    ),
                },
            )
            return results

        except Exception as exc:
            logger.error(
                "Erro nos testes de legendas",
                extra={
                    "session_id": session_id,
                    "error": str(exc),
                },
                exc_info=True,
            )
            return []

    def _create_error_report(
        self,
        channel_url: str,
        status: str,
        error_msg: str,
        duration_ms: int,
    ) -> UnifiedChannelReport:
        """Cria relatório de erro para canal que falhou.

        Args:
            channel_url: URL do canal.
            status: Status do erro (UNREACHABLE ou ERROR).
            error_msg: Mensagem descritiva do erro.
            duration_ms: Duração até o momento do erro.

        Returns:
            UnifiedChannelReport com status de erro.
        """
        session_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()
        channel_id = UnifiedReportGenerator._derive_channel_id(channel_url)

        return UnifiedChannelReport(
            channel_url=channel_url,
            channel_id=channel_id,
            session_id=session_id,
            timestamp=timestamp,
            status=status,
            duration_ms=duration_ms,
            video_summary=TelemetrySummary(total_samples=0),
            audio_tracks_tested=0,
            audio_tracks_passed=0,
            audio_results=[],
            subtitle_tracks_tested=0,
            subtitle_tracks_passed=0,
            subtitle_results=[],
            escalation_results=[],
            telemetry_annotations=[],
            errors=[error_msg],
        )
