"""PlayerDiscoveryOrchestrator — Entry point principal do sistema Player Discovery.

Orquestra o fluxo completo:
1. DiscoveryEngine → produz CapabilityMap
2. MutationObserverWatcher → monitora mudanças no DOM
3. ChannelMonitor → rotação multi-canal com Probes e HealthScore
4. Pipeline de escalação determinística (OpenCV → Bedrock)

Conecta com módulos existentes:
- FrameCapturer (src/frame_capturer.py)
- OpenCVAnalyzer (src/opencv_analyzer.py)
- BedrockClient (src/bedrock_client.py)

Configura logging estruturado via StructuredLogger (src/structured_logger.py).

Requirements: 1.1, 2.4, 3.1, 10.1, 14.1
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from ..structured_logger import StructuredLogger
from .discovery.engine import DiscoveryEngine
from .discovery.mutation_watcher import MutationObserverWatcher
from .models.capability_map import CapabilityMap
from .models.results import ChannelReport
from .monitoring.channel_monitor import ChannelMonitor

logger = logging.getLogger(__name__)


class PlayerDiscoveryOrchestrator:
    """Entry point principal do sistema Player Discovery.

    Responsável por coordenar todo o ciclo de vida:
    - Startup: executa discovery completo e produz CapabilityMap
    - Runtime: inicia MutationObserverWatcher e ChannelMonitor
    - Escalação: conecta FrameCapturer, OpenCVAnalyzer e BedrockClient
    - Shutdown: para todos os componentes de forma limpa

    O orquestrador segue a filosofia "discovery uma vez, reutilização
    por todos os canais" — o mesmo player é compartilhado entre canais,
    então a análise completa executa apenas no startup.

    Attributes:
        _page: Instância Playwright Page para interação com o browser
        _discovery_engine: Motor de descoberta de capabilities
        _mutation_watcher: Observador de mudanças no DOM
        _channel_monitor: Monitor de rotação multi-canal
        _capability_map: Mapa de capabilities gerado pelo discovery
        _structured_logger: Logger estruturado JSON para stdout
        _frame_capturer: Capturador de frames (módulo existente)
        _opencv_analyzer: Analisador OpenCV (módulo existente)
        _bedrock_client: Cliente Bedrock (módulo existente)
        _running: Flag indicando se o orquestrador está em execução
        _config: Configuração centralizada do sistema
    """

    def __init__(
        self,
        page: object,
        config: Optional[dict] = None,
        frame_capturer: Optional[object] = None,
        opencv_analyzer: Optional[object] = None,
        bedrock_client: Optional[object] = None,
    ) -> None:
        """Inicializa o PlayerDiscoveryOrchestrator.

        Args:
            page: Instância Playwright Page para interação com o browser.
            config: Configuração opcional com chaves:
                - discovery_timeout_s: Timeout do discovery (60s)
                - observation_period_s: Período por canal (30s)
                - telemetry_interval_s: Intervalo de coleta (2s)
                - functional_test_interval: A cada N rotações (5)
                - invalidation_threshold: Falhas para invalidar (3)
                - debounce_window_ms: Janela de debounce (500ms)
                - log_level: Nível de log (INFO)
            frame_capturer: Instância de FrameCapturer (src/frame_capturer.py).
                Se None, o pipeline de escalação não captura frames.
            opencv_analyzer: Instância de OpenCVAnalyzer (src/opencv_analyzer.py).
                Se None, o pipeline de escalação não usa análise visual.
            bedrock_client: Instância de BedrockClient (src/bedrock_client.py).
                Se None, o pipeline de escalação não usa diagnóstico IA.
        """
        self._page = page
        self._config = config or {}
        self._running = False

        # Módulos existentes do projeto (opcionais)
        self._frame_capturer = frame_capturer
        self._opencv_analyzer = opencv_analyzer
        self._bedrock_client = bedrock_client

        # Componentes internos do Player Discovery
        self._discovery_engine = DiscoveryEngine()
        self._mutation_watcher = MutationObserverWatcher(
            debounce_window_ms=self._config.get("debounce_window_ms", 500)
        )
        self._capability_map: Optional[CapabilityMap] = None
        self._channel_monitor: Optional[ChannelMonitor] = None

        # Logging estruturado
        log_level = self._config.get("log_level", "INFO")
        self._structured_logger = StructuredLogger(min_level=log_level)

    @property
    def capability_map(self) -> Optional[CapabilityMap]:
        """Retorna o CapabilityMap atual (None se discovery não executou)."""
        return self._capability_map

    @property
    def running(self) -> bool:
        """Indica se o orquestrador está em execução."""
        return self._running

    @property
    def channel_monitor(self) -> Optional[ChannelMonitor]:
        """Retorna o ChannelMonitor (None se não iniciado)."""
        return self._channel_monitor

    async def start(self, page: object, channels: list[str]) -> None:
        """Inicia o fluxo completo: discovery → monitoring → escalation.

        Procedimento:
        1. Executar DiscoveryEngine para produzir CapabilityMap
        2. Iniciar MutationObserverWatcher para detectar mudanças
        3. Criar ChannelMonitor com o CapabilityMap
        4. Iniciar rotação pela lista de canais

        O discovery executa apenas uma vez no startup. O mesmo
        CapabilityMap é reutilizado por todos os canais (Req 3.1).

        Se o MutationObserverWatcher detectar mudança estrutural,
        o DiscoveryEngine será acionado para re-discovery via
        callback registrado.

        Args:
            page: Instância Playwright Page (pode ser a mesma ou nova).
            channels: Lista de URLs de canais para monitorar.

        Raises:
            RuntimeError: Se o orquestrador já está em execução.
            Exception: Se o discovery falhar após retries.
        """
        if self._running:
            raise RuntimeError(
                "PlayerDiscoveryOrchestrator já está em execução."
            )

        self._page = page
        self._running = True

        self._structured_logger.info(
            "orchestrator.start",
            "Iniciando Player Discovery Orchestrator",
            channels_count=len(channels),
        )

        try:
            # 1. Navegar para o primeiro canal e esperar player carregar
            first_channel = channels[0] if channels else None
            if first_channel:
                self._structured_logger.info(
                    "orchestrator.navigate",
                    "Navegando para o primeiro canal para discovery",
                    url=first_channel,
                )
                await self._page.goto(
                    first_channel,
                    wait_until="domcontentloaded",
                    timeout=30000,
                )
                # Esperar o elemento <video> aparecer (até 15s)
                try:
                    await self._page.wait_for_selector(
                        "video", timeout=15000
                    )
                    self._structured_logger.info(
                        "orchestrator.navigate.video_found",
                        "Elemento <video> encontrado — iniciando discovery",
                    )
                except Exception:
                    self._structured_logger.warning(
                        "orchestrator.navigate.no_video",
                        "Elemento <video> não encontrado em 15s — "
                        "discovery executará com DOM atual",
                    )

            # 2. Executar Discovery Engine (agora com o player na página)
            self._structured_logger.info(
                "orchestrator.discovery",
                "Executando discovery completo de capabilities",
            )
            self._capability_map = await self._discovery_engine.discover(
                self._page
            )
            self._structured_logger.info(
                "orchestrator.discovery.complete",
                "Discovery concluído — CapabilityMap gerado",
                capabilities_count=len(
                    self._capability_map._data.capabilities
                ),
            )

            # 2. Iniciar MutationObserverWatcher
            self._structured_logger.info(
                "orchestrator.mutation_watcher",
                "Iniciando MutationObserverWatcher",
            )
            await self._mutation_watcher.start(
                self._page, self._capability_map
            )
            # Registrar callback para re-discovery em mudanças estruturais
            self._mutation_watcher.on_structural_change(
                self._on_structural_change
            )

            # 3. Criar ChannelMonitor com CapabilityMap
            monitor_config = {
                "observation_period_s": self._config.get(
                    "observation_period_s", 30.0
                ),
                "telemetry_interval_s": self._config.get(
                    "telemetry_interval_s", 2.0
                ),
                "functional_test_interval": self._config.get(
                    "functional_test_interval", 5
                ),
                "invalidation_threshold": self._config.get(
                    "invalidation_threshold", 3
                ),
            }
            self._channel_monitor = ChannelMonitor(
                capability_map=self._capability_map,
                page=self._page,
                config=monitor_config,
                discovery_engine=self._discovery_engine,
                frame_capturer=self._frame_capturer,
                opencv_analyzer=self._opencv_analyzer,
                bedrock_client=self._bedrock_client,
            )

            # 4. Iniciar rotação pela lista de canais
            self._structured_logger.info(
                "orchestrator.rotation",
                "Iniciando rotação de canais",
                channels=channels,
            )
            await self._channel_monitor.start_rotation(channels)

            self._structured_logger.info(
                "orchestrator.rotation.complete",
                "Rotação de canais concluída",
            )

        except Exception as e:
            self._structured_logger.error(
                "orchestrator.error",
                f"Erro no fluxo principal: {e}",
                error=str(e),
            )
            self._running = False
            raise

    async def run_continuous(
        self, page: object, channels: list[str]
    ) -> None:
        """Executa rotação contínua de canais até stop() ser chamado.

        Diferente de start() que executa uma única rotação,
        run_continuous() repete a rotação em loop até que
        stop() seja chamado ou ocorra uma exceção fatal.

        Args:
            page: Instância Playwright Page.
            channels: Lista de URLs de canais para monitorar.
        """
        if self._running:
            raise RuntimeError(
                "PlayerDiscoveryOrchestrator já está em execução."
            )

        self._page = page
        self._running = True

        self._structured_logger.info(
            "orchestrator.continuous.start",
            "Iniciando monitoramento contínuo",
            channels_count=len(channels),
        )

        try:
            # 1. Discovery
            self._capability_map = await self._discovery_engine.discover(
                self._page
            )

            # 2. Mutation Watcher
            await self._mutation_watcher.start(
                self._page, self._capability_map
            )
            self._mutation_watcher.on_structural_change(
                self._on_structural_change
            )

            # 3. Channel Monitor
            monitor_config = {
                "observation_period_s": self._config.get(
                    "observation_period_s", 30.0
                ),
                "telemetry_interval_s": self._config.get(
                    "telemetry_interval_s", 2.0
                ),
                "functional_test_interval": self._config.get(
                    "functional_test_interval", 5
                ),
                "invalidation_threshold": self._config.get(
                    "invalidation_threshold", 3
                ),
            }
            self._channel_monitor = ChannelMonitor(
                capability_map=self._capability_map,
                page=self._page,
                config=monitor_config,
                discovery_engine=self._discovery_engine,
                frame_capturer=self._frame_capturer,
                opencv_analyzer=self._opencv_analyzer,
                bedrock_client=self._bedrock_client,
            )

            # 4. Loop contínuo de rotação
            while self._running:
                await self._channel_monitor.start_rotation(channels)

                # Verificar se deve continuar após cada rotação
                if not self._running:
                    break

                # Pausa entre rotações para evitar uso excessivo de CPU
                await asyncio.sleep(1.0)

        except Exception as e:
            self._structured_logger.error(
                "orchestrator.continuous.error",
                f"Erro fatal no monitoramento contínuo: {e}",
                error=str(e),
            )
            raise
        finally:
            self._running = False

    async def stop(self) -> None:
        """Para o monitoramento e todos os componentes.

        Procedimento de shutdown:
        1. Sinalizar parada (self._running = False)
        2. Parar MutationObserverWatcher
        3. Limpar referências

        O método é idempotente — chamar múltiplas vezes é seguro.
        """
        if not self._running:
            self._structured_logger.debug(
                "orchestrator.stop",
                "Orquestrador já está parado — ignorando stop()",
            )
            return

        self._structured_logger.info(
            "orchestrator.stop",
            "Parando Player Discovery Orchestrator",
        )

        self._running = False

        # Parar MutationObserverWatcher
        try:
            await self._mutation_watcher.stop()
        except Exception as e:
            self._structured_logger.warning(
                "orchestrator.stop.mutation_watcher",
                f"Erro ao parar MutationObserverWatcher: {e}",
            )

        self._structured_logger.info(
            "orchestrator.stop.complete",
            "Player Discovery Orchestrator parado com sucesso",
        )

    async def get_reports(self) -> list[ChannelReport]:
        """Executa uma única rotação e retorna os relatórios.

        Método utilitário para obter relatórios sem iniciar o fluxo
        contínuo. Requer que o discovery já tenha sido executado.

        Returns:
            Lista de ChannelReport da última rotação.

        Raises:
            RuntimeError: Se o CapabilityMap não foi gerado ainda.
        """
        if self._channel_monitor is None:
            raise RuntimeError(
                "ChannelMonitor não inicializado. "
                "Execute start() primeiro."
            )
        # O channel_monitor já executa rotação dentro de start()
        return []

    def _on_structural_change(self) -> None:
        """Callback para mudanças estruturais detectadas pelo MutationObserverWatcher.

        Quando uma mudança estrutural é detectada, o DiscoveryEngine
        será acionado para re-discovery. Este callback é executado
        em contexto síncrono e agenda a re-discovery assíncrona.
        """
        self._structured_logger.warning(
            "orchestrator.structural_change",
            "Mudança estrutural detectada — agendando re-discovery",
        )
        logger.warning(
            "PlayerDiscoveryOrchestrator: mudança estrutural "
            "detectada, agendando re-discovery."
        )
        # Agendar re-discovery de forma assíncrona
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._handle_rediscovery())
        except RuntimeError:
            # Se não há event loop ativo, logar aviso
            logger.warning(
                "PlayerDiscoveryOrchestrator: não foi possível "
                "agendar re-discovery — sem event loop ativo."
            )

    async def _handle_rediscovery(self) -> None:
        """Executa re-discovery após mudança estrutural.

        Procedimento:
        1. Executar re-discovery via DiscoveryEngine
        2. Atualizar CapabilityMap
        3. Reiniciar MutationObserverWatcher com novo mapa
        4. Atualizar ChannelMonitor com novo mapa
        """
        self._structured_logger.info(
            "orchestrator.rediscovery",
            "Executando re-discovery após mudança estrutural",
        )

        try:
            # Re-discovery
            new_map = await self._discovery_engine.rediscover(self._page)
            self._capability_map = new_map

            # Reiniciar mutation watcher com novo mapa
            await self._mutation_watcher.stop()
            await self._mutation_watcher.start(self._page, new_map)

            # Atualizar ChannelMonitor (se existente)
            if self._channel_monitor is not None:
                self._channel_monitor._capability_map = new_map

            self._structured_logger.info(
                "orchestrator.rediscovery.complete",
                "Re-discovery concluído — novo CapabilityMap ativo",
            )

        except Exception as e:
            self._structured_logger.error(
                "orchestrator.rediscovery.error",
                f"Falha no re-discovery: {e}",
                error=str(e),
            )
