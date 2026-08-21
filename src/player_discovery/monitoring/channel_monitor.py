"""ChannelMonitor — Orquestrador de rotação multi-canal.

Itera pela lista de canais utilizando o mesmo Capability Map para
monitorar cada canal. Ativa todas as probes durante o período de
observação e consolida resultados em ChannelReport.

Comportamentos chave:
- Reutiliza o MESMO CapabilityMap para todos os canais (Req 3.1, 3.4)
- Ativa todas as probes durante período de observação (Req 10.2)
- Navega para o canal antes de monitorar (Req 10.1)
- Consolida resultados em ChannelReport por canal (Req 10.3)
- Rastreia contagem de rotações para frequência de testes funcionais
- Invalida CapabilityMap após N falhas consecutivas (Req 10.4)
- Ao invalidar, pausa rotação, executa re-discovery e retoma (Req 4.3, 4.5)
- Pipeline de escalação determinística (Req 14.1, 14.2, 14.3, 14.4, 14.5):
  - HEALTHY: captura apenas 1 frame de validação, sem OpenCV/Bedrock
  - SUSPECT: captura frames adicionais + OpenCV
  - DEGRADED/CRITICAL: OpenCV + Bedrock (se OpenCV confirma anomalia)
  - Bedrock somente acionado se OpenCV confirmar anomalia

Requirements: 10.1, 10.2, 10.3, 3.1, 3.4, 10.4, 4.3, 4.5, 14.1, 14.2, 14.3, 14.4, 14.5
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional, Protocol, runtime_checkable
from urllib.parse import urlparse

from ..models.capability_map import CapabilityMap
from ..models.enums import (
    AudioStatus,
    BufferStatus,
    ChannelHealthStatus,
    FunctionalTestStatus,
)
from ..models.results import (
    ChannelReport,
    FunctionalTestResult,
    HealthScores,
)
from ..models.telemetry import (
    AudioTelemetry,
    BufferTelemetry,
    SubtitleTelemetry,
    VideoTelemetry,
)
from ..interaction.manager import InteractionManager
from ..probes.audio_probe import AudioProbe
from ..probes.buffer_probe import BufferProbe
from ..probes.event_probe import EventProbe
from ..probes.subtitle_probe import SubtitleProbe
from ..probes.video_probe import VideoProbe
from .health_score import HealthScoreCalculator

logger = logging.getLogger(__name__)


# =============================================================================
# Protocolos para dependências externas opcionais
# =============================================================================


@runtime_checkable
class FrameCapturerProtocol(Protocol):
    """Protocolo para captura de frames (src/frame_capturer.py)."""

    async def capture_frame(self, page: object) -> object:
        """Captura um frame do viewport."""
        ...

    async def capture_sequence(
        self, page: object, count: int, interval_seconds: float
    ) -> list:
        """Captura sequência de frames com intervalo."""
        ...


@runtime_checkable
class OpenCVAnalyzerProtocol(Protocol):
    """Protocolo para análise visual via OpenCV (src/opencv_analyzer.py)."""

    def detect_black_screen(self, frame: object) -> object:
        """Detecta tela preta vs cena escura."""
        ...

    def detect_freeze(
        self,
        frame_a: object,
        frame_b: object,
        current_time_diff: float,
        observation_window_seconds: float = 5.0,
    ) -> object:
        """Detecta freeze comparando frames."""
        ...


@runtime_checkable
class BedrockClientProtocol(Protocol):
    """Protocolo para diagnóstico visual via Bedrock (src/bedrock_client.py)."""

    async def diagnose_frame(
        self, frame_data: bytes, anomaly_confirmed: bool
    ) -> object:
        """Envia frame para diagnóstico via Bedrock."""
        ...

# Período de observação padrão por canal (30 segundos)
DEFAULT_OBSERVATION_PERIOD_S = 30.0

# Intervalo de coleta de telemetria (2 segundos, conforme Req 5.1)
DEFAULT_TELEMETRY_INTERVAL_S = 2.0

# Timeout de navegação (30 segundos)
DEFAULT_NAVIGATION_TIMEOUT_MS = 30000

# Intervalo padrão de testes funcionais (a cada N rotações, Req 11.1)
DEFAULT_FUNCTIONAL_TEST_INTERVAL = 5

# Threshold de falhas consecutivas para invalidar CapabilityMap (Req 10.4)
DEFAULT_INVALIDATION_THRESHOLD = 3

# Configuração de escalação (Req 14.1-14.5)
# Número de frames adicionais capturados quando canal é SUSPECT
DEFAULT_ESCALATION_FRAME_COUNT = 3
# Intervalo entre capturas de frames adicionais (segundos)
DEFAULT_ESCALATION_FRAME_INTERVAL = 2.0


def _extract_channel_id(channel_url: str) -> str:
    """Extrai um ID representativo a partir da URL do canal.

    Usa o path da URL como identificador. Se não disponível,
    retorna a URL completa.

    Args:
        channel_url: URL do canal.

    Returns:
        String identificadora do canal.
    """
    try:
        parsed = urlparse(channel_url)
        path = parsed.path.strip("/")
        if path:
            # Usar último segmento do path como ID
            return path.split("/")[-1]
        return parsed.netloc or channel_url
    except Exception:
        return channel_url


class ChannelMonitor:
    """Orquestra rotação de canais usando o Capability Map.

    O ChannelMonitor é responsável por:
    1. Receber uma lista de canais e iterar por eles
    2. Reutilizar o MESMO CapabilityMap para todos os canais
    3. Ativar todas as probes durante cada observação
    4. Consolidar resultados em ChannelReport
    5. Rastrear rotações para controle de testes funcionais
    6. Acumular falhas consecutivas e invalidar CapabilityMap quando
       o threshold é atingido (Req 10.4)
    7. Ao invalidar, pausar rotação, executar re-discovery e retomar
       (Req 4.3, 4.5)

    Attributes:
        _capability_map: Mapa de capabilities compartilhado
        _page: Instância Playwright Page
        _video_probe: Probe de telemetria de vídeo
        _audio_probe: Probe de telemetria de áudio
        _subtitle_probe: Probe de telemetria de legendas
        _buffer_probe: Probe de telemetria de buffer
        _event_probe: Probe de registro de eventos
        _health_calculator: Calculadora de health scores
        _rotation_count: Contador de rotações completas
        _observation_period_s: Período de observação por canal
        _telemetry_interval_s: Intervalo entre coletas
        _navigation_timeout_ms: Timeout de navegação
        _consecutive_failures: Contador de falhas consecutivas
        _invalidation_threshold: Número de falhas para invalidar
        _discovery_engine: Referência ao DiscoveryEngine (opcional)
    """

    def __init__(
        self,
        capability_map: CapabilityMap,
        page: object,
        config: Optional[dict] = None,
        discovery_engine: Optional[object] = None,
        frame_capturer: Optional[FrameCapturerProtocol] = None,
        opencv_analyzer: Optional[OpenCVAnalyzerProtocol] = None,
        bedrock_client: Optional[BedrockClientProtocol] = None,
    ) -> None:
        """Inicializa o ChannelMonitor.

        Args:
            capability_map: CapabilityMap reutilizado para todos
                os canais (Req 3.1, 3.4).
            page: Instância Playwright Page para navegação e coleta.
            config: Configuração opcional com chaves:
                - observation_period_s: Período de observação (30s)
                - telemetry_interval_s: Intervalo de coleta (2s)
                - navigation_timeout_ms: Timeout de navegação (30000)
                - invalidation_threshold: Falhas consecutivas para
                  invalidar CapabilityMap (padrão: 3)
                - escalation_frame_count: Frames capturados na
                  escalação SUSPECT (padrão: 3)
                - escalation_frame_interval: Intervalo entre
                  frames na escalação (padrão: 2.0s)
            discovery_engine: Referência opcional ao DiscoveryEngine
                para executar re-discovery quando necessário.
            frame_capturer: Capturador de frames (opcional).
                Necessário para pipeline de escalação (Req 14.5).
            opencv_analyzer: Analisador OpenCV (opcional).
                Necessário para confirmar anomalias (Req 14.2, 14.3).
            bedrock_client: Cliente Bedrock (opcional).
                Acionado somente se OpenCV confirma anomalia (Req 14.3).
        """
        self._capability_map = capability_map
        self._page = page
        self._discovery_engine = discovery_engine

        # Dependências opcionais de escalação (Req 14.1-14.5)
        self._frame_capturer = frame_capturer
        self._opencv_analyzer = opencv_analyzer
        self._bedrock_client = bedrock_client

        # Probes especializadas
        self._video_probe = VideoProbe()
        self._audio_probe = AudioProbe()
        self._subtitle_probe = SubtitleProbe()
        self._buffer_probe = BufferProbe()
        self._event_probe = EventProbe()

        # Health score calculator
        self._health_calculator = HealthScoreCalculator()

        # Contagem de rotações
        self._rotation_count: int = 0

        # Configuração
        cfg = config or {}
        self._observation_period_s: float = cfg.get(
            "observation_period_s", DEFAULT_OBSERVATION_PERIOD_S
        )
        self._telemetry_interval_s: float = cfg.get(
            "telemetry_interval_s", DEFAULT_TELEMETRY_INTERVAL_S
        )
        self._navigation_timeout_ms: int = cfg.get(
            "navigation_timeout_ms", DEFAULT_NAVIGATION_TIMEOUT_MS
        )

        # Invalidação por falhas consecutivas (Req 10.4)
        self._invalidation_threshold: int = cfg.get(
            "invalidation_threshold", DEFAULT_INVALIDATION_THRESHOLD
        )
        self._consecutive_failures: int = 0

        # Testes funcionais periódicos (Req 11.1, 11.2, 11.3, 11.4)
        self._functional_test_interval: int = cfg.get(
            "functional_test_interval", DEFAULT_FUNCTIONAL_TEST_INTERVAL
        )
        self._needs_map_validation: bool = False

        # Configuração de escalação (Req 14.1-14.5)
        self._escalation_frame_count: int = cfg.get(
            "escalation_frame_count", DEFAULT_ESCALATION_FRAME_COUNT
        )
        self._escalation_frame_interval: float = cfg.get(
            "escalation_frame_interval", DEFAULT_ESCALATION_FRAME_INTERVAL
        )

        # Interaction Manager para testes funcionais
        self._interaction_manager = InteractionManager()

    @property
    def capability_map(self) -> CapabilityMap:
        """Retorna o CapabilityMap compartilhado (somente leitura)."""
        return self._capability_map

    @property
    def rotation_count(self) -> int:
        """Retorna o número de rotações completas realizadas."""
        return self._rotation_count

    @property
    def consecutive_failures(self) -> int:
        """Retorna o número de falhas consecutivas acumuladas."""
        return self._consecutive_failures

    @property
    def invalidation_threshold(self) -> int:
        """Retorna o threshold configurado para invalidação."""
        return self._invalidation_threshold

    def register_channel_success(self) -> None:
        """Registra sucesso de um canal, resetando contador de falhas.

        Quando um canal é monitorado com sucesso (sem falha de
        capability), o contador de falhas consecutivas é resetado.
        Falhas em canais não-consecutivos não acumulam (Req 10.4).
        """
        if self._consecutive_failures > 0:
            logger.info(
                "ChannelMonitor: canal com sucesso, "
                "resetando contador de falhas consecutivas "
                "(%d → 0).",
                self._consecutive_failures,
            )
        self._consecutive_failures = 0

    def register_channel_failure(self) -> bool:
        """Registra falha de capability em um canal.

        Incrementa o contador de falhas consecutivas. Retorna True
        se o threshold foi atingido e a invalidação deve ocorrer.

        Returns:
            True se o threshold de invalidação foi atingido,
            False caso contrário.
        """
        self._consecutive_failures += 1
        logger.warning(
            "ChannelMonitor: falha de capability registrada "
            "(%d/%d consecutivas).",
            self._consecutive_failures,
            self._invalidation_threshold,
        )
        return (
            self._consecutive_failures
            >= self._invalidation_threshold
        )

    async def _handle_invalidation(self) -> None:
        """Executa invalidação do CapabilityMap e re-discovery.

        Procedimento (Req 4.3, 4.5, 10.4):
        1. Invalidar o CapabilityMap atual
        2. Executar re-discovery via DiscoveryEngine
        3. Atualizar referência ao novo CapabilityMap
        4. Resetar contador de falhas

        Se o DiscoveryEngine não estiver disponível, apenas invalida
        o mapa e loga aviso.
        """
        logger.warning(
            "ChannelMonitor: threshold de falhas consecutivas "
            "atingido (%d). Invalidando CapabilityMap e "
            "executando re-discovery.",
            self._consecutive_failures,
        )

        # 1. Invalidar mapa atual
        self._capability_map.invalidate()

        # 2. Executar re-discovery se engine disponível
        if self._discovery_engine is not None:
            try:
                new_map = await self._discovery_engine.rediscover(
                    self._page
                )
                # 3. Atualizar referência ao novo mapa
                self._capability_map = new_map
                logger.info(
                    "ChannelMonitor: re-discovery concluído. "
                    "Novo CapabilityMap disponível."
                )
            except Exception as e:
                logger.error(
                    "ChannelMonitor: falha no re-discovery: %s",
                    str(e),
                )
        else:
            logger.warning(
                "ChannelMonitor: DiscoveryEngine não disponível. "
                "CapabilityMap invalidado sem re-discovery."
            )

        # 4. Resetar contador
        self._consecutive_failures = 0

    async def start_rotation(
        self, channels: list[str]
    ) -> list[ChannelReport]:
        """Inicia rotação pela lista de canais.

        Itera por todos os canais fornecidos, monitorando cada um
        durante o período de observação. Reutiliza o mesmo
        CapabilityMap para todos os canais sem re-discovery.

        Lógica de invalidação (Req 10.4):
        - Quando uma ação do Capability_Map falha → incrementar
          contador de falhas consecutivas
        - Quando um canal é monitorado com sucesso → resetar
          contador
        - Quando contador atinge threshold → invalidar mapa,
          executar re-discovery, retomar rotação

        Args:
            channels: Lista de URLs de canais para monitorar.

        Returns:
            Lista de ChannelReport, um por canal monitorado.
        """
        if not channels:
            logger.warning(
                "ChannelMonitor: lista de canais vazia."
            )
            return []

        logger.info(
            "ChannelMonitor: iniciando rotação por %d canais.",
            len(channels),
        )

        reports: list[ChannelReport] = []

        for channel_url in channels:
            logger.info(
                "ChannelMonitor: monitorando canal '%s'",
                channel_url,
            )

            try:
                report = await self.monitor_channel(channel_url)
                reports.append(report)
                logger.info(
                    "ChannelMonitor: canal '%s' -> status=%s",
                    channel_url,
                    report.status.value,
                )

                # Canal com sucesso reseta falhas consecutivas
                if report.status != ChannelHealthStatus.CRITICAL:
                    self.register_channel_success()
                else:
                    # Canal CRITICAL indica falha de capability
                    should_invalidate = (
                        self.register_channel_failure()
                    )
                    if should_invalidate:
                        await self._handle_invalidation()

            except Exception as e:
                logger.error(
                    "ChannelMonitor: falha no canal '%s': %s",
                    channel_url,
                    str(e),
                )
                # Registrar canal com status CRITICAL
                error_report = self._build_error_report(
                    channel_url, str(e)
                )
                reports.append(error_report)

                # Falha de canal acumula no contador
                should_invalidate = (
                    self.register_channel_failure()
                )
                if should_invalidate:
                    await self._handle_invalidation()

        self._rotation_count += 1

        # Executar testes funcionais a cada N rotações (Req 11.1)
        if (
            self._functional_test_interval > 0
            and self._rotation_count % self._functional_test_interval == 0
        ):
            logger.info(
                "ChannelMonitor: rotação #%d é múltipla de %d. "
                "Executando testes funcionais.",
                self._rotation_count,
                self._functional_test_interval,
            )
            # Executar testes no último canal da rotação
            if channels:
                try:
                    functional_results = (
                        await self.run_functional_tests(channels[-1])
                    )
                    # Associar resultados ao último relatório
                    if reports:
                        reports[-1].functional_tests = functional_results
                except Exception as e:
                    logger.error(
                        "ChannelMonitor: falha nos testes "
                        "funcionais: %s",
                        str(e),
                    )

        logger.info(
            "ChannelMonitor: rotação #%d completa. "
            "%d canais monitorados.",
            self._rotation_count,
            len(reports),
        )

        return reports

    async def monitor_channel(
        self, channel_url: str
    ) -> ChannelReport:
        """Monitora um canal individual durante o período de observação.

        Procedimento:
        1. Navegar para a URL do canal
        2. Ativar EventProbe (listeners)
        3. Coletar telemetria de todas as probes durante observação
        4. Consolidar resultados em ChannelReport
        5. Calcular Health Scores
        6. Classificar status do canal

        Args:
            channel_url: URL do canal a monitorar.

        Returns:
            ChannelReport consolidado com toda a telemetria.
        """
        start_time = time.perf_counter()
        channel_id = _extract_channel_id(channel_url)

        # 1. Navegar para o canal
        await self._navigate_to_channel(channel_url)

        # 2. Ativar EventProbe (attach listeners)
        await self._setup_event_probe()

        # 3. Coletar telemetria durante o período de observação
        video_samples: list[VideoTelemetry] = []
        audio_samples: list[AudioTelemetry] = []
        buffer_samples: list[BufferTelemetry] = []

        elapsed = 0.0
        while elapsed < self._observation_period_s:
            cycle_start = time.perf_counter()

            # Coletar de todas as probes em paralelo
            video_tel, audio_tel, buffer_tel = (
                await self._collect_all_probes()
            )

            video_samples.append(video_tel)
            audio_samples.append(audio_tel)
            buffer_samples.append(buffer_tel)

            # Aguardar intervalo de coleta
            cycle_elapsed = time.perf_counter() - cycle_start
            sleep_time = max(
                0, self._telemetry_interval_s - cycle_elapsed
            )
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)

            elapsed = time.perf_counter() - start_time

        # 4. Coletar telemetria de legendas (uma coleta final)
        subtitle_tel = await self._collect_subtitle()

        # 5. Obter eventos registrados durante observação
        events = await self._event_probe.get_events(self._page)

        # 6. Consolidar resultados
        # Usar última amostra de vídeo, áudio e buffer como referência
        final_video = (
            video_samples[-1] if video_samples
            else self._default_video_telemetry()
        )
        final_audio = (
            audio_samples[-1] if audio_samples
            else self._default_audio_telemetry()
        )
        final_buffer = (
            buffer_samples[-1] if buffer_samples
            else self._default_buffer_telemetry()
        )

        # 7. Calcular Health Scores
        health_scores = self._calculate_health_scores(
            final_video, final_audio
        )

        # 8. Classificar status do canal
        status = self._classify_channel_status(
            final_video, final_audio, final_buffer
        )

        # 9. Calcular duração da observação
        observation_duration_ms = int(
            (time.perf_counter() - start_time) * 1000
        )

        # 10. Construir relatório
        report = ChannelReport(
            channel_id=channel_id,
            channel_url=channel_url,
            status=status,
            health_scores=health_scores,
            video_telemetry=final_video,
            audio_telemetry=final_audio,
            subtitle_telemetry=subtitle_tel,
            buffer_telemetry=final_buffer,
            events=events,
            functional_tests=[],
            observation_duration_ms=observation_duration_ms,
            escalated_to_opencv=False,
            escalated_to_bedrock=False,
        )

        # 11. Pipeline de escalação determinística (Req 14.1-14.5)
        report = await self._escalate_channel(status, report)

        # 12. Limpar estado para próximo canal
        self._cleanup_for_next_channel()

        return report

    async def run_functional_tests(
        self, channel_url: str
    ) -> list[FunctionalTestResult]:
        """Executa testes funcionais no canal atual.

        Testes são executados na ordem de menor impacto para maior
        impacto (Req 11.2):
        1. play/pause
        2. mute/unmute
        3. audio_selection
        4. subtitle_selection

        Se um teste FAIL e a capability tinha confidence >= 0.9,
        sinaliza necessidade de validação do Capability Map (Req 11.4).

        Args:
            channel_url: URL do canal onde executar os testes.

        Returns:
            Lista de FunctionalTestResult com resultados dos testes.
        """
        logger.info(
            "ChannelMonitor: executando testes funcionais no "
            "canal '%s'.",
            channel_url,
        )

        results: list[FunctionalTestResult] = []

        # Ordem de execução: menor impacto → maior impacto (Req 11.2)
        test_sequence = [
            ("play_pause", self._test_play_pause),
            ("mute_unmute", self._test_mute_unmute),
            ("audio_selection", self._test_audio_selection),
            ("subtitle_selection", self._test_subtitle_selection),
        ]

        for test_name, test_fn in test_sequence:
            try:
                result = await test_fn()
                results.append(result)

                # Sinalizar validação se capability com alta
                # confidence falhar (Req 11.4)
                if result.status == FunctionalTestStatus.FAIL:
                    self._check_high_confidence_failure(
                        result.capability
                    )

                logger.debug(
                    "Teste funcional '%s': %s",
                    test_name,
                    result.status.value,
                )
            except Exception as e:
                logger.error(
                    "ChannelMonitor: erro no teste funcional "
                    "'%s': %s",
                    test_name,
                    str(e),
                )
                results.append(
                    FunctionalTestResult(
                        capability=test_name,
                        status=FunctionalTestStatus.FAIL,
                        action_executed=test_name,
                        expected_result="teste executado com sucesso",
                        actual_result=f"exceção: {e}",
                        duration_ms=0,
                        error=str(e),
                    )
                )

        logger.info(
            "ChannelMonitor: testes funcionais concluídos. "
            "%d executados, %d PASS, %d FAIL, %d SKIPPED.",
            len(results),
            sum(
                1 for r in results
                if r.status == FunctionalTestStatus.PASS
            ),
            sum(
                1 for r in results
                if r.status == FunctionalTestStatus.FAIL
            ),
            sum(
                1 for r in results
                if r.status == FunctionalTestStatus.SKIPPED
            ),
        )

        return results

    async def _test_play_pause(self) -> FunctionalTestResult:
        """Executa teste funcional de play/pause.

        Fluxo:
        1. Executar pause (via InteractionManager)
        2. Verificar estado paused
        3. Executar play
        4. Verificar estado playing

        Returns:
            FunctionalTestResult com resultado do teste.
        """
        start_time = time.perf_counter()

        # Verificar se capabilities estão disponíveis
        play_cap = self._capability_map.get_capability("play")
        pause_cap = self._capability_map.get_capability("pause")

        if (
            not play_cap or not play_cap.available
            or not pause_cap or not pause_cap.available
        ):
            duration_ms = int(
                (time.perf_counter() - start_time) * 1000
            )
            return FunctionalTestResult(
                capability="play_pause",
                status=FunctionalTestStatus.SKIPPED,
                action_executed="verificar capabilities",
                expected_result="play e pause disponíveis",
                actual_result="capabilities play/pause não disponíveis",
                duration_ms=duration_ms,
            )

        try:
            # Pause
            pause_result = await self._interaction_manager.execute(
                self._page,
                "pause",
                "click",
                self._capability_map,
            )
            if not pause_result.success:
                duration_ms = int(
                    (time.perf_counter() - start_time) * 1000
                )
                return FunctionalTestResult(
                    capability="play_pause",
                    status=FunctionalTestStatus.FAIL,
                    action_executed="pause",
                    expected_result="player pausado",
                    actual_result=f"falha ao pausar: "
                                  f"{pause_result.error}",
                    duration_ms=duration_ms,
                    error=pause_result.error,
                )

            # Play
            play_result = await self._interaction_manager.execute(
                self._page,
                "play",
                "click",
                self._capability_map,
            )
            if not play_result.success:
                duration_ms = int(
                    (time.perf_counter() - start_time) * 1000
                )
                return FunctionalTestResult(
                    capability="play_pause",
                    status=FunctionalTestStatus.FAIL,
                    action_executed="play",
                    expected_result="player reproduzindo",
                    actual_result=f"falha ao reproduzir: "
                                  f"{play_result.error}",
                    duration_ms=duration_ms,
                    error=play_result.error,
                )

            duration_ms = int(
                (time.perf_counter() - start_time) * 1000
            )
            return FunctionalTestResult(
                capability="play_pause",
                status=FunctionalTestStatus.PASS,
                action_executed="pause → play",
                expected_result="player pausou e retomou reprodução",
                actual_result="play/pause funcionou corretamente",
                duration_ms=duration_ms,
            )
        except Exception as e:
            duration_ms = int(
                (time.perf_counter() - start_time) * 1000
            )
            return FunctionalTestResult(
                capability="play_pause",
                status=FunctionalTestStatus.FAIL,
                action_executed="play/pause",
                expected_result="player pausou e retomou",
                actual_result=f"exceção: {e}",
                duration_ms=duration_ms,
                error=str(e),
            )

    async def _test_mute_unmute(self) -> FunctionalTestResult:
        """Executa teste funcional de mute/unmute via AudioProbe.

        Delega para AudioProbe.run_functional_test() que já
        implementa a lógica completa de mute/unmute (Req 6.6).

        Returns:
            FunctionalTestResult com resultado do teste.
        """
        return await self._audio_probe.run_functional_test(
            self._page, self._capability_map
        )

    async def _test_audio_selection(self) -> FunctionalTestResult:
        """Executa teste funcional de seleção de áudio.

        Verifica se a capability audio_selection está disponível e
        delega para AudioProbe.run_functional_test().

        Returns:
            FunctionalTestResult com resultado do teste.
        """
        audio_cap = self._capability_map.get_capability(
            "audio_selection"
        )
        if not audio_cap or not audio_cap.available:
            return FunctionalTestResult(
                capability="audio_selection",
                status=FunctionalTestStatus.SKIPPED,
                action_executed="verificar capability",
                expected_result="audio_selection disponível",
                actual_result="capability não disponível",
                duration_ms=0,
            )

        # AudioProbe gerencia o teste de audio_selection internamente
        return await self._audio_probe.run_functional_test(
            self._page, self._capability_map
        )

    async def _test_subtitle_selection(self) -> FunctionalTestResult:
        """Executa teste funcional de seleção de legenda.

        Delega para SubtitleProbe.run_functional_test() que
        implementa a lógica completa (Req 7.4).

        Returns:
            FunctionalTestResult com resultado do teste.
        """
        return await self._subtitle_probe.run_functional_test(
            self._page, self._capability_map
        )

    def _check_high_confidence_failure(
        self, capability_name: str
    ) -> None:
        """Verifica se uma capability com alta confidence falhou.

        Se a capability tinha confidence >= 0.9 e falhou no teste
        funcional, sinaliza necessidade de validação do Capability
        Map (Req 11.4).

        Para testes compostos (play_pause, mute_unmute), verifica
        as capabilities individuais que compõem o teste.

        Args:
            capability_name: Nome da capability que falhou.
        """
        # Mapear testes compostos para capabilities individuais
        composite_map: dict[str, list[str]] = {
            "play_pause": ["play", "pause"],
            "mute_unmute": ["mute", "unmute"],
        }

        capabilities_to_check = composite_map.get(
            capability_name, [capability_name]
        )

        for cap_name in capabilities_to_check:
            cap = self._capability_map.get_capability(cap_name)
            if cap is not None and cap.confidence >= 0.9:
                logger.warning(
                    "ChannelMonitor: capability '%s' com confidence "
                    "%.2f FALHOU no teste funcional. "
                    "Sinalizando validação do CapabilityMap.",
                    cap_name,
                    cap.confidence,
                )
                self._needs_map_validation = True
                return

    @property
    def needs_map_validation(self) -> bool:
        """Indica se o Capability Map precisa de validação.

        True quando uma capability com alta confidence (>= 0.9)
        falhou em um teste funcional.
        """
        return self._needs_map_validation

    @property
    def functional_test_interval(self) -> int:
        """Retorna o intervalo configurado para testes funcionais."""
        return self._functional_test_interval

    async def _escalate_channel(
        self,
        status: ChannelHealthStatus,
        report: ChannelReport,
    ) -> ChannelReport:
        """Executa pipeline de escalação determinística para o canal.

        Pipeline de escalação (Req 14.1-14.5):
        - HEALTHY: captura apenas 1 frame de validação, sem OpenCV/Bedrock
        - SUSPECT: captura frames adicionais + aciona OpenCV
        - DEGRADED/CRITICAL: captura frames + OpenCV + Bedrock (se confirmado)

        Regra fundamental: Bedrock é acionado SOMENTE se OpenCV confirma
        anomalia. Se OpenCV não confirma, classifica como alarme falso e
        NÃO aciona Bedrock (Req 14.4).

        Args:
            status: Status de saúde classificado do canal.
            report: ChannelReport atual para atualizar com info de escalação.

        Returns:
            ChannelReport atualizado com campos escalated_to_opencv e
            escalated_to_bedrock refletindo as ações tomadas.
        """
        # Sem frame_capturer não é possível escalar
        if self._frame_capturer is None:
            logger.debug(
                "ChannelMonitor: frame_capturer não disponível. "
                "Escalação desativada."
            )
            return report

        # HEALTHY: captura apenas 1 frame de validação (Req 14.1, 14.5)
        if status == ChannelHealthStatus.HEALTHY:
            try:
                await self._frame_capturer.capture_frame(self._page)
                logger.debug(
                    "ChannelMonitor: canal HEALTHY — "
                    "1 frame de validação capturado."
                )
            except Exception as e:
                logger.warning(
                    "ChannelMonitor: falha ao capturar frame de "
                    "validação: %s",
                    str(e),
                )
            # Não escala para OpenCV nem Bedrock
            return report

        # SUSPECT, DEGRADED ou CRITICAL: capturar frames adicionais (Req 14.2)
        frames: list = []
        try:
            frames = await self._frame_capturer.capture_sequence(
                self._page,
                self._escalation_frame_count,
                self._escalation_frame_interval,
            )
            logger.info(
                "ChannelMonitor: %d frames capturados para "
                "escalação (status=%s).",
                len(frames),
                status.value,
            )
        except Exception as e:
            logger.error(
                "ChannelMonitor: falha ao capturar frames para "
                "escalação: %s",
                str(e),
            )
            return report

        # Sem OpenCV não é possível confirmar anomalia
        if self._opencv_analyzer is None:
            logger.debug(
                "ChannelMonitor: opencv_analyzer não disponível. "
                "Escalação limitada a captura de frames."
            )
            return report

        # Acionar OpenCV para confirmar anomalia (Req 14.2)
        opencv_confirms_anomaly = False
        try:
            opencv_confirms_anomaly = self._analyze_frames_with_opencv(
                frames
            )
            report.escalated_to_opencv = True
            logger.info(
                "ChannelMonitor: OpenCV %s anomalia.",
                "CONFIRMA" if opencv_confirms_anomaly else "NÃO confirma",
            )
        except Exception as e:
            logger.error(
                "ChannelMonitor: falha na análise OpenCV: %s",
                str(e),
            )
            report.escalated_to_opencv = True
            return report

        # Se OpenCV NÃO confirma → alarme falso, NÃO acionar Bedrock (Req 14.4)
        if not opencv_confirms_anomaly:
            logger.info(
                "ChannelMonitor: OpenCV não confirma anomalia. "
                "Classificando como alarme falso. Bedrock NÃO acionado."
            )
            return report

        # OpenCV CONFIRMA anomalia → escalar para Bedrock (Req 14.3)
        if self._bedrock_client is None:
            logger.debug(
                "ChannelMonitor: bedrock_client não disponível. "
                "Escalação limitada a OpenCV."
            )
            return report

        try:
            # Usar o primeiro frame válido para diagnóstico
            frame_data = self._get_first_valid_frame_data(frames)
            if frame_data is not None:
                await self._bedrock_client.diagnose_frame(
                    frame_data, anomaly_confirmed=True
                )
                report.escalated_to_bedrock = True
                logger.info(
                    "ChannelMonitor: Bedrock acionado para "
                    "diagnóstico visual detalhado."
                )
            else:
                logger.warning(
                    "ChannelMonitor: nenhum frame válido para "
                    "enviar ao Bedrock."
                )
        except Exception as e:
            logger.error(
                "ChannelMonitor: falha no diagnóstico Bedrock: %s",
                str(e),
            )
            report.escalated_to_bedrock = True

        return report

    def _analyze_frames_with_opencv(self, frames: list) -> bool:
        """Analisa frames com OpenCV para confirmar anomalia.

        Verifica se há tela preta ou freeze nos frames capturados.
        Retorna True se anomalia é confirmada.

        Args:
            frames: Lista de objetos FrameResult capturados.

        Returns:
            True se OpenCV confirma anomalia (BLACK_SCREEN ou FREEZE),
            False caso contrário.
        """
        if not frames or self._opencv_analyzer is None:
            return False

        for frame in frames:
            # Pular frames inválidos
            if not hasattr(frame, "data") or not frame.data:
                continue
            if hasattr(frame, "is_valid") and not frame.is_valid:
                continue

            try:
                import numpy as np
                import cv2

                # Converter bytes para numpy array
                nparr = np.frombuffer(frame.data, np.uint8)
                img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

                if img is None:
                    continue

                # Detectar tela preta
                black_result = self._opencv_analyzer.detect_black_screen(img)
                if (
                    hasattr(black_result, "is_black_screen")
                    and black_result.is_black_screen
                ):
                    logger.info(
                        "ChannelMonitor: OpenCV detectou BLACK_SCREEN."
                    )
                    return True

            except Exception as e:
                logger.warning(
                    "ChannelMonitor: erro ao analisar frame com "
                    "OpenCV: %s",
                    str(e),
                )
                continue

        # Verificar freeze comparando frames consecutivos
        if len(frames) >= 2:
            try:
                import numpy as np
                import cv2

                valid_frames = [
                    f for f in frames
                    if hasattr(f, "data") and f.data
                    and (not hasattr(f, "is_valid") or f.is_valid)
                ]
                if len(valid_frames) >= 2:
                    nparr_a = np.frombuffer(valid_frames[0].data, np.uint8)
                    nparr_b = np.frombuffer(valid_frames[-1].data, np.uint8)
                    img_a = cv2.imdecode(nparr_a, cv2.IMREAD_COLOR)
                    img_b = cv2.imdecode(nparr_b, cv2.IMREAD_COLOR)

                    if img_a is not None and img_b is not None:
                        freeze_result = self._opencv_analyzer.detect_freeze(
                            img_a,
                            img_b,
                            current_time_diff=0.0,
                            observation_window_seconds=float(
                                self._escalation_frame_count
                                * self._escalation_frame_interval
                            ),
                        )
                        if (
                            hasattr(freeze_result, "classification")
                            and hasattr(freeze_result.classification, "value")
                            and freeze_result.classification.value
                            == "FREEZE_CONFIRMED"
                        ):
                            logger.info(
                                "ChannelMonitor: OpenCV detectou "
                                "FREEZE_CONFIRMED."
                            )
                            return True
            except Exception as e:
                logger.warning(
                    "ChannelMonitor: erro ao verificar freeze: %s",
                    str(e),
                )

        return False

    def _get_first_valid_frame_data(self, frames: list) -> Optional[bytes]:
        """Obtém os dados do primeiro frame válido.

        Args:
            frames: Lista de objetos FrameResult.

        Returns:
            Bytes do frame ou None se nenhum frame válido.
        """
        for frame in frames:
            if hasattr(frame, "data") and frame.data:
                if not hasattr(frame, "is_valid") or frame.is_valid:
                    return frame.data
        return None

    async def _navigate_to_channel(self, channel_url: str) -> None:
        """Navega para a URL do canal.

        Args:
            channel_url: URL do canal.

        Raises:
            RuntimeError: Se a navegação falhar.
        """
        try:
            await self._page.goto(  # type: ignore[union-attr]
                channel_url,
                timeout=self._navigation_timeout_ms,
                wait_until="domcontentloaded",
            )
            logger.debug(
                "ChannelMonitor: navegação para '%s' concluída.",
                channel_url,
            )
        except Exception as e:
            logger.error(
                "ChannelMonitor: falha na navegação para '%s': %s",
                channel_url,
                str(e),
            )
            raise RuntimeError(
                f"Falha na navegação para {channel_url}: {e}"
            ) from e

    async def _setup_event_probe(self) -> None:
        """Configura o EventProbe para o canal atual.

        Limpa eventos anteriores e reanexa listeners se necessário.
        """
        self._event_probe.clear_events()
        if not self._event_probe.attached:
            try:
                await self._event_probe.attach_listeners(
                    self._page  # type: ignore[arg-type]
                )
            except Exception as e:
                logger.warning(
                    "ChannelMonitor: falha ao anexar listeners: %s",
                    str(e),
                )

    async def _collect_all_probes(
        self,
    ) -> tuple[VideoTelemetry, AudioTelemetry, BufferTelemetry]:
        """Coleta telemetria de vídeo, áudio e buffer em paralelo.

        Returns:
            Tupla com (VideoTelemetry, AudioTelemetry, BufferTelemetry).
        """
        try:
            video_tel, audio_tel, buffer_tel = await asyncio.gather(
                self._video_probe.collect(
                    self._page, self._capability_map
                ),
                self._audio_probe.collect(
                    self._page,  # type: ignore[arg-type]
                    self._capability_map,
                ),
                self._buffer_probe.collect(
                    self._page, self._capability_map
                ),
                return_exceptions=True,
            )

            # Tratar exceções individuais das probes
            if isinstance(video_tel, Exception):
                logger.warning(
                    "VideoProbe falhou: %s", str(video_tel)
                )
                video_tel = self._default_video_telemetry()

            if isinstance(audio_tel, Exception):
                logger.warning(
                    "AudioProbe falhou: %s", str(audio_tel)
                )
                audio_tel = self._default_audio_telemetry()

            if isinstance(buffer_tel, Exception):
                logger.warning(
                    "BufferProbe falhou: %s",
                    str(buffer_tel),
                )
                buffer_tel = self._default_buffer_telemetry()

            return (  # type: ignore[return-value]
                video_tel, audio_tel, buffer_tel
            )

        except Exception as e:
            logger.error(
                "ChannelMonitor: erro ao coletar probes: %s",
                str(e),
            )
            return (
                self._default_video_telemetry(),
                self._default_audio_telemetry(),
                self._default_buffer_telemetry(),
            )

    async def _collect_subtitle(self) -> SubtitleTelemetry:
        """Coleta telemetria de legendas.

        Returns:
            SubtitleTelemetry coletada ou padrão em caso de erro.
        """
        try:
            return await self._subtitle_probe.collect(
                self._page, self._capability_map
            )
        except Exception as e:
            logger.warning(
                "SubtitleProbe falhou: %s", str(e)
            )
            return SubtitleTelemetry(
                tracks_available=0,
                tracks=[],
                active_track=None,
                has_active_cues=False,
                status="SUBTITLE_UNAVAILABLE",
            )

    def _calculate_health_scores(
        self,
        video_tel: VideoTelemetry,
        audio_tel: AudioTelemetry,
    ) -> HealthScores:
        """Calcula os Health Scores compostos.

        Args:
            video_tel: Telemetria de vídeo consolidada.
            audio_tel: Telemetria de áudio consolidada.

        Returns:
            HealthScores com video e audio health calculados.
        """
        video_health = self._health_calculator.calculate_video_health(
            video_tel
        )
        audio_health = self._health_calculator.calculate_audio_health(
            audio_tel
        )

        return HealthScores(
            video_health=video_health,
            audio_health=audio_health,
            functional_health=0.0,
        )

    def _classify_channel_status(
        self,
        video_tel: VideoTelemetry,
        audio_tel: AudioTelemetry,
        buffer_tel: BufferTelemetry,
    ) -> ChannelHealthStatus:
        """Classifica o status de saúde do canal.

        Classificação baseada na telemetria coletada:
        - CRITICAL: erro presente ou vídeo não reproduzindo
        - DEGRADED: problemas significativos (NO_AUDIO, BUFFERING_FREQUENT)
        - SUSPECT: problemas menores (AUDIO_LOW, BUFFER_LOW)
        - HEALTHY: sem problemas detectados

        Args:
            video_tel: Telemetria de vídeo.
            audio_tel: Telemetria de áudio.
            buffer_tel: Telemetria de buffer.

        Returns:
            ChannelHealthStatus classificado.
        """
        # CRITICAL: erro de vídeo ou player não reproduzindo
        if video_tel.error is not None:
            return ChannelHealthStatus.CRITICAL
        if not video_tel.playing and not video_tel.paused:
            return ChannelHealthStatus.CRITICAL

        # DEGRADED: problemas significativos
        if audio_tel.status == AudioStatus.NO_AUDIO:
            return ChannelHealthStatus.DEGRADED
        if buffer_tel.status == BufferStatus.BUFFERING_FREQUENT:
            return ChannelHealthStatus.DEGRADED

        # SUSPECT: problemas menores
        if audio_tel.status == AudioStatus.AUDIO_LOW:
            return ChannelHealthStatus.SUSPECT
        if buffer_tel.status == BufferStatus.BUFFER_LOW:
            return ChannelHealthStatus.SUSPECT

        # HEALTHY: sem problemas detectados
        return ChannelHealthStatus.HEALTHY

    def _cleanup_for_next_channel(self) -> None:
        """Limpa estado das probes para o próximo canal.

        Reseta contadores, amostras e eventos que são
        específicos de um canal.
        """
        self._event_probe.clear_events()
        self._audio_probe.reset()
        self._buffer_probe.clear_events()

    def _build_error_report(
        self, channel_url: str, error: str
    ) -> ChannelReport:
        """Constrói um ChannelReport de erro quando o canal falha.

        Args:
            channel_url: URL do canal que falhou.
            error: Mensagem de erro.

        Returns:
            ChannelReport com status CRITICAL.
        """
        channel_id = _extract_channel_id(channel_url)
        return ChannelReport(
            channel_id=channel_id,
            channel_url=channel_url,
            status=ChannelHealthStatus.CRITICAL,
            health_scores=HealthScores(
                video_health=0.0,
                audio_health=0.0,
                functional_health=0.0,
            ),
            video_telemetry=self._default_video_telemetry(),
            audio_telemetry=self._default_audio_telemetry(),
            subtitle_telemetry=SubtitleTelemetry(
                tracks_available=0,
                tracks=[],
                active_track=None,
                has_active_cues=False,
                status="ERROR",
            ),
            buffer_telemetry=self._default_buffer_telemetry(),
            events=[],
            functional_tests=[],
            observation_duration_ms=0,
            escalated_to_opencv=False,
            escalated_to_bedrock=False,
        )

    @staticmethod
    def _default_video_telemetry() -> VideoTelemetry:
        """Retorna telemetria de vídeo com valores padrão."""
        return VideoTelemetry(
            current_time=0.0,
            duration=0.0,
            ready_state=0,
            paused=True,
            playing=False,
            ended=False,
            seeking=False,
            playback_rate=1.0,
            network_state=0,
            buffered_seconds=0.0,
            video_width=0,
            video_height=0,
        )

    @staticmethod
    def _default_audio_telemetry() -> AudioTelemetry:
        """Retorna telemetria de áudio com valores padrão."""
        return AudioTelemetry(
            rms=None,
            peak=None,
            silence_duration=0.0,
            muted=False,
            status=AudioStatus.OK,
            tracks_available=[],
        )

    @staticmethod
    def _default_buffer_telemetry() -> BufferTelemetry:
        """Retorna telemetria de buffer com valores padrão."""
        return BufferTelemetry(
            buffered_start=0.0,
            buffered_end=0.0,
            buffer_ahead=0.0,
            waiting_count=0,
            waiting_total_ms=0.0,
            longest_wait_ms=0.0,
            time_since_last_wait=None,
            status=BufferStatus.OK,
        )
