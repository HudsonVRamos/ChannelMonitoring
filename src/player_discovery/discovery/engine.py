"""DiscoveryEngine — Motor principal de descoberta de capabilities do player.

Orquestra todos os analyzers (DOM, JS, Browser APIs, CSS) e testes
comportamentais para produzir um Capability Map completo. Implementa:
- Execução paralela dos analyzers via asyncio.gather
- Agregação de evidências por capability
- Testes comportamentais para capabilities com evidência inicial
- Classificação de confidence (>= 0.7 → available, < 0.7 → unavailable)
- Cache em memória (rejeita re-discovery se mapa válido)
- Timeout de 60s com retry e backoff exponencial (max 3 tentativas)

Requirements: 1.1, 1.6, 1.7, 3.2, 4.3, 4.5
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING

from src.player_discovery.models.capability import (
    Capability,
    CapabilityMapData,
    InteractionStrategy,
    PlayerInfo,
)
from src.player_discovery.models.capability_map import (
    CapabilityMap,
    REQUIRED_CAPABILITIES,
)
from src.player_discovery.models.enums import InteractionLevel

from .behavioral_tester import BehavioralTester, BehavioralTestResult
from .browser_api_analyzer import BrowserAPIAnalyzer, BrowserAPIEvidence
from .css_analyzer import CSSAnalyzer, CSSEvidence, MAX_CSS_ONLY_CONFIDENCE
from .dom_analyzer import DOMAnalyzer, DOMEvidence
from .js_analyzer import JSAnalyzer, JSEvidence

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = logging.getLogger(__name__)

# Constantes de configuração
DISCOVERY_TIMEOUT_S = 60
MAX_RETRIES = 3
BACKOFF_BASE_S = 2  # 2s, 4s, 8s
CONFIDENCE_THRESHOLD = 0.7
# Evidência mínima para rodar teste comportamental
BEHAVIORAL_TEST_MIN_CONFIDENCE = 0.3
# Quantas capabilities testar no validate_map
VALIDATION_SAMPLE_SIZE = 3


class DiscoveryEngine:
    """Motor de descoberta dinâmica de capabilities do player.

    Orquestra a análise completa (DOM, JS, Browser APIs, CSS, behavioral)
    no startup e produz um Capability Map reutilizável. Implementa cache
    em memória e retry com backoff exponencial.

    Requirements: 1.1, 1.6, 1.7, 3.2, 4.3, 4.5
    """

    def __init__(self) -> None:
        """Inicializa o DiscoveryEngine com todos os analyzers."""
        self._cached_map: Optional[CapabilityMap] = None
        self._dom_analyzer = DOMAnalyzer()
        self._js_analyzer = JSAnalyzer()
        self._browser_api_analyzer = BrowserAPIAnalyzer()
        self._css_analyzer = CSSAnalyzer()
        self._behavioral_tester = BehavioralTester()
        self._logger = logging.getLogger(
            f"{__name__}.{self.__class__.__name__}"
        )

    @property
    def cached_map(self) -> Optional[CapabilityMap]:
        """Acesso ao mapa em cache (somente leitura)."""
        return self._cached_map

    async def discover(self, page: "Page") -> CapabilityMap:
        """Executa discovery completo e retorna Capability Map.

        Se existe um mapa válido em cache, retorna sem re-executar.
        Caso contrário, executa discovery com timeout de 60s e retry
        com backoff exponencial (max 3 tentativas).

        Args:
            page: Instância de Page do Playwright.

        Returns:
            CapabilityMap com todas as capabilities descobertas.

        Raises:
            TimeoutError: Se todas as tentativas falharem por timeout.
            RuntimeError: Se discovery falhar após todas as tentativas.
        """
        # Cache: rejeitar re-execução se mapa válido em memória (Req 3.2)
        if self._cached_map is not None and self._cached_map.is_valid():
            self._logger.info(
                "Capability Map válido em cache — retornando sem re-discovery"
            )
            return self._cached_map

        # Retry com backoff exponencial
        last_exception: Optional[Exception] = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                self._logger.info(
                    "Discovery tentativa %d/%d", attempt, MAX_RETRIES
                )
                capability_map = await asyncio.wait_for(
                    self._execute_discovery(page),
                    timeout=DISCOVERY_TIMEOUT_S,
                )
                # Armazenar em cache
                self._cached_map = capability_map
                self._logger.info(
                    "Discovery concluído com sucesso na tentativa %d: %s",
                    attempt,
                    capability_map,
                )
                return capability_map

            except asyncio.TimeoutError:
                last_exception = TimeoutError(
                    f"Discovery timeout ({DISCOVERY_TIMEOUT_S}s) na "
                    f"tentativa {attempt}/{MAX_RETRIES}"
                )
                self._logger.error(
                    "Timeout no discovery (tentativa %d/%d)",
                    attempt,
                    MAX_RETRIES,
                )
            except Exception as e:
                last_exception = e
                self._logger.error(
                    "Erro no discovery (tentativa %d/%d): %s",
                    attempt,
                    MAX_RETRIES,
                    str(e),
                )

            # Backoff exponencial antes da próxima tentativa
            if attempt < MAX_RETRIES:
                backoff = BACKOFF_BASE_S * (2 ** (attempt - 1))
                self._logger.info(
                    "Aguardando %ds antes da próxima tentativa", backoff
                )
                await asyncio.sleep(backoff)

        # Todas as tentativas falharam
        raise RuntimeError(
            f"Discovery falhou após {MAX_RETRIES} tentativas: "
            f"{last_exception}"
        ) from last_exception

    async def validate_map(
        self, page: "Page", capability_map: CapabilityMap
    ) -> bool:
        """Valida se o Capability Map atual continua válido.

        Testa uma amostra de capabilities (2-3) via behavioral tester
        para verificar se os controles do player ainda respondem como
        esperado.

        Args:
            page: Instância de Page do Playwright.
            capability_map: CapabilityMap a ser validado.

        Returns:
            True se todas as capabilities testadas passaram, False se
            alguma falhou.
        """
        if not capability_map.is_valid():
            return False

        available_caps = capability_map.get_available_capabilities()
        if not available_caps:
            self._logger.warning(
                "Nenhuma capability available para validação"
            )
            return False

        # Selecionar amostra para teste (até VALIDATION_SAMPLE_SIZE)
        # Priorizar capabilities com alta confidence
        sorted_caps = sorted(
            available_caps.values(),
            key=lambda c: c.confidence,
            reverse=True,
        )
        sample = sorted_caps[:VALIDATION_SAMPLE_SIZE]

        self._logger.info(
            "Validando %d capabilities: %s",
            len(sample),
            [c.name for c in sample],
        )

        # Testar cada capability da amostra
        for cap in sample:
            result = await self._behavioral_tester.test_capability(
                page, cap.name
            )
            if not result.confirmed:
                self._logger.warning(
                    "Validação falhou para capability '%s': %s",
                    cap.name,
                    result.observation,
                )
                return False

        self._logger.info("Validação do Capability Map: PASSOU")
        return True

    async def rediscover(self, page: "Page") -> CapabilityMap:
        """Re-executa discovery completo (após invalidação).

        Invalida o mapa em cache e executa novo discovery.

        Args:
            page: Instância de Page do Playwright.

        Returns:
            Novo CapabilityMap produzido pelo re-discovery.
        """
        self._logger.info("Iniciando re-discovery completo")

        # Invalidar mapa atual
        if self._cached_map is not None:
            self._cached_map.invalidate()
        self._cached_map = None

        # Executar novo discovery
        return await self.discover(page)

    async def _execute_discovery(self, page: "Page") -> CapabilityMap:
        """Executa o fluxo completo de discovery internamente.

        Etapas:
        1. Executa analyzers em paralelo (DOM, JS, Browser APIs, CSS)
        2. Agrega evidência por capability
        3. Executa testes comportamentais para capabilities com evidência
        4. Classifica capabilities (confidence >= 0.7 → available)
        5. Garante 9 capabilities obrigatórias (UNKNOWN para ausentes)
        6. Produz CapabilityMap

        Args:
            page: Instância de Page do Playwright.

        Returns:
            CapabilityMap com todas as capabilities descobertas.
        """
        start_time = time.perf_counter()

        # 1. Executar analyzers em paralelo (asyncio.gather)
        self._logger.info("Executando analyzers em paralelo...")
        dom_results, js_results, browser_results, css_results = (
            await asyncio.gather(
                self._dom_analyzer.analyze(page),
                self._js_analyzer.analyze(page),
                self._browser_api_analyzer.analyze(page),
                self._css_analyzer.analyze(page),
                return_exceptions=True,
            )
        )

        # Tratar exceções individuais (degradação graciosa)
        if isinstance(dom_results, BaseException):
            self._logger.error("DOM analyzer falhou: %s", dom_results)
            dom_results = []
        if isinstance(js_results, BaseException):
            self._logger.error("JS analyzer falhou: %s", js_results)
            js_results = []
        if isinstance(browser_results, BaseException):
            self._logger.error(
                "Browser API analyzer falhou: %s", browser_results
            )
            browser_results = []
        if isinstance(css_results, BaseException):
            self._logger.error("CSS analyzer falhou: %s", css_results)
            css_results = []

        # 2. Extrair player info do JS analyzer
        player_info = self._extract_player_info(js_results)

        # 3. Agregar evidência por capability
        evidence_map = self._aggregate_evidence(
            dom_results, js_results, browser_results, css_results
        )

        # 4. Executar testes comportamentais para capabilities com evidência
        behavioral_results = await self._run_behavioral_tests(
            page, evidence_map
        )

        # 5. Classificar capabilities
        capabilities = self._classify_capabilities(
            evidence_map, behavioral_results
        )

        # 6. Garantir capabilities obrigatórias
        capabilities = self._ensure_required_capabilities(capabilities)

        # 7. Calcular hash da estrutura
        version_hash = self._compute_version_hash(capabilities)

        # 8. Calcular duração
        duration_ms = int((time.perf_counter() - start_time) * 1000)

        # 9. Produzir CapabilityMap
        map_data = CapabilityMapData(
            player_info=player_info,
            capabilities=capabilities,
            discovery_duration_ms=duration_ms,
            version_hash=version_hash,
            valid=True,
        )

        capability_map = CapabilityMap(map_data)

        self._logger.info(
            "Discovery executado em %dms: %d capabilities (%d available)",
            duration_ms,
            len(capabilities),
            sum(1 for c in capabilities.values() if c.available),
        )

        return capability_map

    def _extract_player_info(
        self, js_results: list[JSEvidence]
    ) -> PlayerInfo:
        """Extrai informações do player a partir das evidências JS.

        Args:
            js_results: Resultados do JS analyzer.

        Returns:
            PlayerInfo com library, version e video_elements.
        """
        library: Optional[str] = None
        version: Optional[str] = None
        video_elements: list[str] = []

        for evidence in js_results:
            if evidence.capability_hint == "player_library":
                library = evidence.details.get("library")
                version = evidence.details.get("version")
            if evidence.details.get("source") == "HTMLMediaElement":
                method = evidence.details.get("method", "")
                if method in ("currentSrc", "src"):
                    video_elements.append(evidence.api_path)

        # Se não encontrou video_elements via JS, registrar genérico
        if not video_elements:
            video_elements = ["video (HTMLMediaElement)"]

        return PlayerInfo(
            library=library,
            version=version,
            video_elements=video_elements,
            discovered_at=datetime.now(timezone.utc).isoformat(),
        )

    def _aggregate_evidence(
        self,
        dom_results: list[DOMEvidence],
        js_results: list[JSEvidence],
        browser_results: list[BrowserAPIEvidence],
        css_results: list[CSSEvidence],
    ) -> dict[str, _AggregatedEvidence]:
        """Agrega evidência de todos os analyzers por capability.

        Combina evidências de DOM, JS, Browser APIs e CSS numa estrutura
        unificada por capability, calculando confidence acumulada e
        registrando as fontes de evidência.

        Returns:
            Dicionário de capability_name → _AggregatedEvidence.
        """
        evidence_map: dict[str, _AggregatedEvidence] = {}

        # Processar DOM evidence
        for ev in dom_results:
            cap_name = ev.capability_hint
            if not cap_name:
                continue
            agg = evidence_map.setdefault(
                cap_name,
                _AggregatedEvidence(capability_name=cap_name),
            )
            agg.confidence_sum += ev.confidence_contribution
            agg.evidence_texts.append(
                f"[DOM] {ev.element_description}"
            )
            agg.has_non_css_evidence = True
            if ev.interaction_hint == InteractionLevel.PLAYER_API:
                agg.best_interaction_level = InteractionLevel.PLAYER_API
            elif (
                ev.interaction_hint == InteractionLevel.SEMANTIC_DOM
                and agg.best_interaction_level != InteractionLevel.PLAYER_API
            ):
                agg.best_interaction_level = InteractionLevel.SEMANTIC_DOM

        # Processar JS evidence
        for ev in js_results:
            cap_name = ev.capability_hint
            if not cap_name or cap_name == "player_library":
                continue
            agg = evidence_map.setdefault(
                cap_name,
                _AggregatedEvidence(capability_name=cap_name),
            )
            agg.confidence_sum += ev.confidence_contribution
            agg.evidence_texts.append(
                f"[JS] {ev.api_path} disponível"
            )
            agg.has_non_css_evidence = True
            # JS evidence sempre indica PLAYER_API
            agg.best_interaction_level = InteractionLevel.PLAYER_API

        # Processar Browser API evidence
        for ev in browser_results:
            cap_name = ev.capability_hint
            if not cap_name or not ev.available:
                continue
            agg = evidence_map.setdefault(
                cap_name,
                _AggregatedEvidence(capability_name=cap_name),
            )
            agg.confidence_sum += ev.confidence_contribution
            agg.evidence_texts.append(
                f"[BrowserAPI] {ev.api_name} disponível"
            )
            agg.has_non_css_evidence = True

        # Processar CSS evidence (auxiliar — nunca sozinha >= 0.7)
        for ev in css_results:
            cap_name = ev.capability_hint
            if not cap_name or cap_name == "unknown":
                continue
            agg = evidence_map.setdefault(
                cap_name,
                _AggregatedEvidence(capability_name=cap_name),
            )
            agg.confidence_sum += ev.confidence_contribution
            agg.evidence_texts.append(
                f"[CSS] {ev.element_description} "
                f"(visible={ev.is_visible}, interactive={ev.is_interactive})"
            )
            agg.has_css_evidence = True

        return evidence_map

    async def _run_behavioral_tests(
        self,
        page: "Page",
        evidence_map: dict[str, _AggregatedEvidence],
    ) -> dict[str, BehavioralTestResult]:
        """Executa testes comportamentais para capabilities com evidência.

        Apenas capabilities com confidence acumulada >=
        BEHAVIORAL_TEST_MIN_CONFIDENCE são testadas comportamentalmente.

        Args:
            page: Instância de Page do Playwright.
            evidence_map: Evidências agregadas por capability.

        Returns:
            Dicionário capability_name → BehavioralTestResult.
        """
        results: dict[str, BehavioralTestResult] = {}
        supported = set(
            BehavioralTester.get_supported_capabilities()
        )

        for cap_name, agg in evidence_map.items():
            if cap_name not in supported:
                continue
            if agg.confidence_sum < BEHAVIORAL_TEST_MIN_CONFIDENCE:
                continue

            try:
                result = await self._behavioral_tester.test_capability(
                    page,
                    cap_name,
                    evidence=agg.evidence_texts,
                )
                results[cap_name] = result
            except Exception as e:
                self._logger.warning(
                    "Teste comportamental falhou para '%s': %s",
                    cap_name,
                    e,
                )

        self._logger.info(
            "Testes comportamentais: %d executados, %d confirmados",
            len(results),
            sum(1 for r in results.values() if r.confirmed),
        )
        return results

    def _classify_capabilities(
        self,
        evidence_map: dict[str, _AggregatedEvidence],
        behavioral_results: dict[str, BehavioralTestResult],
    ) -> dict[str, Capability]:
        """Classifica capabilities com base na evidência e testes.

        Aplica regras:
        - confidence >= 0.7 → available=True
        - confidence < 0.7 → available=False
        - CSS isolado nunca >= 0.7 (clamp)
        - Behavioral test boost é adicionado se confirmado

        Args:
            evidence_map: Evidências agregadas.
            behavioral_results: Resultados dos testes comportamentais.

        Returns:
            Dicionário capability_name → Capability.
        """
        capabilities: dict[str, Capability] = {}

        for cap_name, agg in evidence_map.items():
            confidence = agg.confidence_sum
            evidence_texts = list(agg.evidence_texts)

            # Aplicar boost de teste comportamental
            behavioral = behavioral_results.get(cap_name)
            if behavioral is not None:
                if behavioral.confirmed:
                    confidence += behavioral.confidence_boost
                    evidence_texts.append(
                        f"[Behavioral] Teste confirmou: "
                        f"{behavioral.observation}"
                    )
                else:
                    evidence_texts.append(
                        f"[Behavioral] Teste não confirmou: "
                        f"{behavioral.observation}"
                    )

            # CSS isolado nunca >= 0.7 (Req 1.5)
            if agg.has_css_evidence and not agg.has_non_css_evidence:
                confidence = min(confidence, MAX_CSS_ONLY_CONFIDENCE)

            # Clamp confidence em [0.0, 1.0]
            confidence = max(0.0, min(1.0, confidence))

            # Classificação: >= 0.7 → available (Req 2.2, 2.3)
            available = confidence >= CONFIDENCE_THRESHOLD

            # Determinar interaction level
            interaction_level = agg.best_interaction_level

            # Construir lista de strategies
            strategies = self._build_strategies(
                cap_name, agg, behavioral
            )

            capabilities[cap_name] = Capability(
                name=cap_name,
                available=available,
                confidence=round(confidence, 3),
                evidence=evidence_texts,
                interaction_strategy=interaction_level,
                strategies=strategies,
            )

        return capabilities

    def _build_strategies(
        self,
        cap_name: str,
        agg: _AggregatedEvidence,
        behavioral: Optional[BehavioralTestResult],
    ) -> list[InteractionStrategy]:
        """Constrói lista de strategies ordenadas por nível.

        Sempre tenta incluir strategies dos 3 níveis quando há evidência.

        Returns:
            Lista de InteractionStrategy ordenada por nível.
        """
        strategies: list[InteractionStrategy] = []

        # Nível 1: PLAYER_API (se JS evidence disponível)
        if agg.best_interaction_level == InteractionLevel.PLAYER_API:
            strategies.append(InteractionStrategy(
                level=InteractionLevel.PLAYER_API,
                type="player_api",
                details={"capability": cap_name},
            ))

        # Nível 2: SEMANTIC_DOM (se DOM evidence disponível)
        if agg.has_non_css_evidence:
            strategies.append(InteractionStrategy(
                level=InteractionLevel.SEMANTIC_DOM,
                type="semantic_dom",
                details={"capability": cap_name},
            ))

        # Nível 3: VISUAL_FALLBACK (sempre como fallback)
        strategies.append(InteractionStrategy(
            level=InteractionLevel.VISUAL_FALLBACK,
            type="visual_fallback",
            details={"capability": cap_name},
        ))

        # Ordenar por nível (PLAYER_API < SEMANTIC_DOM < VISUAL_FALLBACK)
        level_order = {
            InteractionLevel.PLAYER_API: 1,
            InteractionLevel.SEMANTIC_DOM: 2,
            InteractionLevel.VISUAL_FALLBACK: 3,
        }
        strategies.sort(key=lambda s: level_order.get(s.level, 99))

        return strategies

    def _ensure_required_capabilities(
        self, capabilities: dict[str, Capability]
    ) -> dict[str, Capability]:
        """Garante que todas as 9 capabilities obrigatórias estão presentes.

        Capabilities ausentes são adicionadas como UNKNOWN (available=False,
        confidence=0.0).

        Args:
            capabilities: Dicionário de capabilities descobertas.

        Returns:
            Dicionário com todas as capabilities obrigatórias garantidas.
        """
        for cap_name in REQUIRED_CAPABILITIES:
            if cap_name not in capabilities:
                capabilities[cap_name] = Capability(
                    name=cap_name,
                    available=False,
                    confidence=0.0,
                    evidence=["Nenhuma evidência encontrada — UNKNOWN"],
                    interaction_strategy=InteractionLevel.VISUAL_FALLBACK,
                    strategies=[
                        InteractionStrategy(
                            level=InteractionLevel.VISUAL_FALLBACK,
                            type="visual_fallback",
                            details={"capability": cap_name},
                        )
                    ],
                )
        return capabilities

    def _compute_version_hash(
        self, capabilities: dict[str, Capability]
    ) -> str:
        """Computa hash da estrutura de capabilities para detecção de mudanças.

        Args:
            capabilities: Dicionário de capabilities.

        Returns:
            Hash SHA-256 representando a estrutura atual.
        """
        # Criar representação estável para hash
        parts: list[str] = []
        for name in sorted(capabilities.keys()):
            cap = capabilities[name]
            parts.append(
                f"{name}:{cap.available}:{cap.interaction_strategy.value}"
            )
        content = "|".join(parts)
        return hashlib.sha256(content.encode()).hexdigest()


class _AggregatedEvidence:
    """Evidência agregada de múltiplos analyzers para uma capability.

    Classe interna usada durante o processo de agregação.
    """

    def __init__(self, capability_name: str) -> None:
        self.capability_name = capability_name
        self.confidence_sum: float = 0.0
        self.evidence_texts: list[str] = []
        self.has_css_evidence: bool = False
        self.has_non_css_evidence: bool = False
        self.best_interaction_level: InteractionLevel = (
            InteractionLevel.VISUAL_FALLBACK
        )
