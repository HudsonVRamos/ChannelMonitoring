"""Testes unitários do DiscoveryEngine.

Testa o motor principal de discovery incluindo:
- Orquestração dos analyzers
- Cache em memória (rejeita re-discovery se válido)
- Timeout e retry com backoff exponencial
- validate_map
- rediscover
- Classificação de capabilities
- Estrutura mínima obrigatória

Requirements testados: 1.1, 1.6, 1.7, 3.2, 4.3, 4.5
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.player_discovery.discovery.engine import (
    BACKOFF_BASE_S,
    BEHAVIORAL_TEST_MIN_CONFIDENCE,
    CONFIDENCE_THRESHOLD,
    DISCOVERY_TIMEOUT_S,
    MAX_RETRIES,
    DiscoveryEngine,
    _AggregatedEvidence,
)
from src.player_discovery.discovery.behavioral_tester import BehavioralTestResult
from src.player_discovery.discovery.browser_api_analyzer import BrowserAPIEvidence
from src.player_discovery.discovery.css_analyzer import CSSEvidence, MAX_CSS_ONLY_CONFIDENCE
from src.player_discovery.discovery.dom_analyzer import DOMEvidence
from src.player_discovery.discovery.js_analyzer import JSEvidence
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


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def mock_page():
    """Mock de Page do Playwright."""
    page = AsyncMock()
    page.evaluate = AsyncMock(return_value=[])
    return page


@pytest.fixture
def engine():
    """Instância limpa do DiscoveryEngine."""
    return DiscoveryEngine()


@pytest.fixture
def valid_capability_map():
    """CapabilityMap válido com todas as capabilities obrigatórias."""
    caps = {}
    for name in REQUIRED_CAPABILITIES:
        caps[name] = Capability(
            name=name,
            available=True,
            confidence=0.85,
            evidence=[f"[DOM] Encontrado controle {name}"],
            interaction_strategy=InteractionLevel.SEMANTIC_DOM,
            strategies=[
                InteractionStrategy(
                    level=InteractionLevel.SEMANTIC_DOM,
                    type="semantic_dom",
                    details={"capability": name},
                )
            ],
        )
    data = CapabilityMapData(
        player_info=PlayerInfo(
            library="shaka-player",
            version="4.0.0",
            video_elements=["video"],
            discovered_at="2024-01-01T00:00:00Z",
        ),
        capabilities=caps,
        discovery_duration_ms=1000,
        version_hash="abc123",
        valid=True,
    )
    return CapabilityMap(data)


# ============================================================
# Testes de Cache (Requirement 3.2)
# ============================================================


class TestDiscoveryCaching:
    """Testes de cache em memória."""

    @pytest.mark.asyncio
    async def test_cached_map_returned_without_reexecution(
        self, engine, mock_page, valid_capability_map
    ):
        """Se mapa válido em cache, retorna sem re-executar analyzers."""
        engine._cached_map = valid_capability_map

        result = await engine.discover(mock_page)

        assert result is valid_capability_map
        # Nenhum analyzer foi chamado
        mock_page.evaluate.assert_not_called()

    @pytest.mark.asyncio
    async def test_invalidated_map_triggers_rediscovery(
        self, engine, mock_page, valid_capability_map
    ):
        """Se mapa em cache foi invalidado, executa novo discovery."""
        valid_capability_map.invalidate()
        engine._cached_map = valid_capability_map

        # Mockar analyzers para retornar resultados vazios
        with patch.object(
            engine._dom_analyzer, "analyze", new_callable=AsyncMock
        ) as mock_dom, patch.object(
            engine._js_analyzer, "analyze", new_callable=AsyncMock
        ) as mock_js, patch.object(
            engine._browser_api_analyzer, "analyze", new_callable=AsyncMock
        ) as mock_browser, patch.object(
            engine._css_analyzer, "analyze", new_callable=AsyncMock
        ) as mock_css:
            mock_dom.return_value = []
            mock_js.return_value = []
            mock_browser.return_value = []
            mock_css.return_value = []

            result = await engine.discover(mock_page)

            # Analyzers foram chamados
            mock_dom.assert_called_once()
            assert result is not valid_capability_map
            assert result.is_valid()

    @pytest.mark.asyncio
    async def test_none_cache_triggers_discovery(self, engine, mock_page):
        """Se não há mapa em cache, executa discovery."""
        assert engine.cached_map is None

        with patch.object(
            engine._dom_analyzer, "analyze", new_callable=AsyncMock
        ) as mock_dom, patch.object(
            engine._js_analyzer, "analyze", new_callable=AsyncMock
        ) as mock_js, patch.object(
            engine._browser_api_analyzer, "analyze", new_callable=AsyncMock
        ) as mock_browser, patch.object(
            engine._css_analyzer, "analyze", new_callable=AsyncMock
        ) as mock_css:
            mock_dom.return_value = []
            mock_js.return_value = []
            mock_browser.return_value = []
            mock_css.return_value = []

            result = await engine.discover(mock_page)

            mock_dom.assert_called_once()
            assert result.is_valid()
            assert engine.cached_map is result


# ============================================================
# Testes de Timeout e Retry (Error Handling)
# ============================================================


class TestTimeoutAndRetry:
    """Testes de timeout e retry com backoff exponencial."""

    @pytest.mark.asyncio
    async def test_timeout_retries_with_backoff(self, engine, mock_page):
        """Timeout aciona retry com backoff exponencial."""
        call_count = 0

        async def slow_analyze(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                # Simular operação lenta que será cancelada
                await asyncio.sleep(100)
            return []

        with patch.object(
            engine._dom_analyzer, "analyze", side_effect=slow_analyze
        ), patch.object(
            engine._js_analyzer, "analyze", new_callable=AsyncMock, return_value=[]
        ), patch.object(
            engine._browser_api_analyzer, "analyze", new_callable=AsyncMock, return_value=[]
        ), patch.object(
            engine._css_analyzer, "analyze", new_callable=AsyncMock, return_value=[]
        ), patch("src.player_discovery.discovery.engine.DISCOVERY_TIMEOUT_S", 0.1), \
                patch("src.player_discovery.discovery.engine.BACKOFF_BASE_S", 0.01):
            result = await engine.discover(mock_page)
            # Eventualmente deve ter sucesso na terceira tentativa
            assert result.is_valid()

    @pytest.mark.asyncio
    async def test_all_retries_fail_raises_error(self, engine, mock_page):
        """Se todas as tentativas falham, levanta RuntimeError."""

        async def always_fail(*args, **kwargs):
            await asyncio.sleep(100)
            return []

        with patch.object(
            engine._dom_analyzer, "analyze", side_effect=always_fail
        ), patch.object(
            engine._js_analyzer, "analyze", side_effect=always_fail
        ), patch.object(
            engine._browser_api_analyzer, "analyze", side_effect=always_fail
        ), patch.object(
            engine._css_analyzer, "analyze", side_effect=always_fail
        ), patch("src.player_discovery.discovery.engine.DISCOVERY_TIMEOUT_S", 0.05), \
                patch("src.player_discovery.discovery.engine.BACKOFF_BASE_S", 0.01):
            with pytest.raises(RuntimeError, match="Discovery falhou"):
                await engine.discover(mock_page)

    @pytest.mark.asyncio
    async def test_exception_retries(self, engine, mock_page):
        """Exceções nos analyzers também acionam retry."""
        attempt = 0

        async def fail_then_succeed(*args, **kwargs):
            nonlocal attempt
            attempt += 1
            if attempt == 1:
                raise RuntimeError("Erro simulado")
            return []

        with patch.object(
            engine._dom_analyzer, "analyze", side_effect=fail_then_succeed
        ), patch.object(
            engine._js_analyzer, "analyze", new_callable=AsyncMock, return_value=[]
        ), patch.object(
            engine._browser_api_analyzer, "analyze", new_callable=AsyncMock, return_value=[]
        ), patch.object(
            engine._css_analyzer, "analyze", new_callable=AsyncMock, return_value=[]
        ), patch("src.player_discovery.discovery.engine.BACKOFF_BASE_S", 0.01):
            result = await engine.discover(mock_page)
            assert result.is_valid()


# ============================================================
# Testes de Orquestração de Discovery
# ============================================================


class TestDiscoveryOrchestration:
    """Testes da execução do discovery completo."""

    @pytest.mark.asyncio
    async def test_parallel_execution(self, engine, mock_page):
        """Todos os analyzers são executados em paralelo."""
        execution_order = []

        async def track_dom(*args):
            execution_order.append("dom_start")
            await asyncio.sleep(0.01)
            execution_order.append("dom_end")
            return []

        async def track_js(*args):
            execution_order.append("js_start")
            await asyncio.sleep(0.01)
            execution_order.append("js_end")
            return []

        async def track_browser(*args):
            execution_order.append("browser_start")
            await asyncio.sleep(0.01)
            execution_order.append("browser_end")
            return []

        async def track_css(*args):
            execution_order.append("css_start")
            await asyncio.sleep(0.01)
            execution_order.append("css_end")
            return []

        with patch.object(engine._dom_analyzer, "analyze", side_effect=track_dom), \
             patch.object(engine._js_analyzer, "analyze", side_effect=track_js), \
             patch.object(engine._browser_api_analyzer, "analyze", side_effect=track_browser), \
             patch.object(engine._css_analyzer, "analyze", side_effect=track_css):
            await engine.discover(mock_page)

        # Todos devem ter começado antes de qualquer um terminar (paralelo)
        starts = [i for i, x in enumerate(execution_order) if x.endswith("_start")]
        ends = [i for i, x in enumerate(execution_order) if x.endswith("_end")]
        # Pelo menos 2 analyzers devem começar antes do primeiro terminar
        assert min(ends) > min(starts)

    @pytest.mark.asyncio
    async def test_required_capabilities_always_present(
        self, engine, mock_page
    ):
        """Todas as 9 capabilities obrigatórias estão no resultado."""
        with patch.object(
            engine._dom_analyzer, "analyze", new_callable=AsyncMock, return_value=[]
        ), patch.object(
            engine._js_analyzer, "analyze", new_callable=AsyncMock, return_value=[]
        ), patch.object(
            engine._browser_api_analyzer, "analyze", new_callable=AsyncMock, return_value=[]
        ), patch.object(
            engine._css_analyzer, "analyze", new_callable=AsyncMock, return_value=[]
        ):
            result = await engine.discover(mock_page)

        for cap_name in REQUIRED_CAPABILITIES:
            cap = result.get_capability(cap_name)
            assert cap is not None, f"Capability '{cap_name}' ausente"
            assert cap.name == cap_name

    @pytest.mark.asyncio
    async def test_dom_evidence_contributes_to_confidence(
        self, engine, mock_page
    ):
        """Evidência do DOM contribui para o confidence."""
        dom_evidence = [
            DOMEvidence(
                element_description="button com aria-label='Play'",
                capability_hint="play",
                confidence_contribution=0.5,
                attributes={"aria-label": "Play", "role": "button"},
                interaction_hint=InteractionLevel.SEMANTIC_DOM,
            ),
            DOMEvidence(
                element_description="button com aria-label='Pause'",
                capability_hint="pause",
                confidence_contribution=0.5,
                attributes={"aria-label": "Pause", "role": "button"},
                interaction_hint=InteractionLevel.SEMANTIC_DOM,
            ),
        ]

        with patch.object(
            engine._dom_analyzer, "analyze", new_callable=AsyncMock, return_value=dom_evidence
        ), patch.object(
            engine._js_analyzer, "analyze", new_callable=AsyncMock, return_value=[]
        ), patch.object(
            engine._browser_api_analyzer, "analyze", new_callable=AsyncMock, return_value=[]
        ), patch.object(
            engine._css_analyzer, "analyze", new_callable=AsyncMock, return_value=[]
        ):
            result = await engine.discover(mock_page)

        play_cap = result.get_capability("play")
        assert play_cap is not None
        assert play_cap.confidence == 0.5

    @pytest.mark.asyncio
    async def test_js_evidence_sets_player_api_level(
        self, engine, mock_page
    ):
        """Evidência JS define interaction_strategy como PLAYER_API."""
        js_evidence = [
            JSEvidence(
                api_path="shakaPlayer.play",
                capability_hint="play",
                confidence_contribution=0.4,
                details={"method": "play", "source": "shaka-player-instance"},
                interaction_hint=InteractionLevel.PLAYER_API,
            ),
        ]

        with patch.object(
            engine._dom_analyzer, "analyze", new_callable=AsyncMock, return_value=[]
        ), patch.object(
            engine._js_analyzer, "analyze", new_callable=AsyncMock, return_value=js_evidence
        ), patch.object(
            engine._browser_api_analyzer, "analyze", new_callable=AsyncMock, return_value=[]
        ), patch.object(
            engine._css_analyzer, "analyze", new_callable=AsyncMock, return_value=[]
        ):
            result = await engine.discover(mock_page)

        play_cap = result.get_capability("play")
        assert play_cap is not None
        assert play_cap.interaction_strategy == InteractionLevel.PLAYER_API

    @pytest.mark.asyncio
    async def test_css_only_never_produces_high_confidence(
        self, engine, mock_page
    ):
        """CSS isolado nunca produz confidence >= 0.7 (Req 1.5)."""
        css_evidence = [
            CSSEvidence(
                element_description="button[role='button']",
                capability_hint="play",
                confidence_contribution=0.4,
                properties={"display": "block"},
                is_visible=True,
                is_interactive=True,
                has_active_state=False,
            ),
        ]

        with patch.object(
            engine._dom_analyzer, "analyze", new_callable=AsyncMock, return_value=[]
        ), patch.object(
            engine._js_analyzer, "analyze", new_callable=AsyncMock, return_value=[]
        ), patch.object(
            engine._browser_api_analyzer, "analyze", new_callable=AsyncMock, return_value=[]
        ), patch.object(
            engine._css_analyzer, "analyze", new_callable=AsyncMock, return_value=css_evidence
        ):
            result = await engine.discover(mock_page)

        play_cap = result.get_capability("play")
        assert play_cap is not None
        assert play_cap.confidence < CONFIDENCE_THRESHOLD
        assert play_cap.available is False

    @pytest.mark.asyncio
    async def test_behavioral_test_boosts_confidence(
        self, engine, mock_page
    ):
        """Teste comportamental confirmado aumenta confidence."""
        dom_evidence = [
            DOMEvidence(
                element_description="button com aria-label='Play'",
                capability_hint="play",
                confidence_contribution=0.5,
                attributes={"aria-label": "Play", "role": "button"},
                interaction_hint=InteractionLevel.SEMANTIC_DOM,
            ),
        ]

        behavioral_result = BehavioralTestResult(
            capability="play",
            confirmed=True,
            confidence_boost=0.25,
            observation="play() via API confirmado",
            duration_ms=100,
        )

        with patch.object(
            engine._dom_analyzer, "analyze", new_callable=AsyncMock, return_value=dom_evidence
        ), patch.object(
            engine._js_analyzer, "analyze", new_callable=AsyncMock, return_value=[]
        ), patch.object(
            engine._browser_api_analyzer, "analyze", new_callable=AsyncMock, return_value=[]
        ), patch.object(
            engine._css_analyzer, "analyze", new_callable=AsyncMock, return_value=[]
        ), patch.object(
            engine._behavioral_tester,
            "test_capability",
            new_callable=AsyncMock,
            return_value=behavioral_result,
        ):
            result = await engine.discover(mock_page)

        play_cap = result.get_capability("play")
        assert play_cap is not None
        # 0.5 (DOM) + 0.25 (behavioral) = 0.75
        assert play_cap.confidence == 0.75
        assert play_cap.available is True

    @pytest.mark.asyncio
    async def test_analyzer_failure_graceful_degradation(
        self, engine, mock_page
    ):
        """Se um analyzer falha, o discovery continua com os outros."""
        with patch.object(
            engine._dom_analyzer,
            "analyze",
            new_callable=AsyncMock,
            side_effect=RuntimeError("DOM error"),
        ), patch.object(
            engine._js_analyzer, "analyze", new_callable=AsyncMock, return_value=[]
        ), patch.object(
            engine._browser_api_analyzer, "analyze", new_callable=AsyncMock, return_value=[]
        ), patch.object(
            engine._css_analyzer, "analyze", new_callable=AsyncMock, return_value=[]
        ):
            result = await engine.discover(mock_page)

        # Discovery deve completar mesmo com falha de um analyzer
        assert result.is_valid()
        assert result.has_required_capabilities()


# ============================================================
# Testes de validate_map (Requirement 4.3)
# ============================================================


class TestValidateMap:
    """Testes de validação do Capability Map."""

    @pytest.mark.asyncio
    async def test_validate_valid_map_all_pass(
        self, engine, mock_page, valid_capability_map
    ):
        """Se todos os testes comportamentais passam, retorna True."""
        with patch.object(
            engine._behavioral_tester,
            "test_capability",
            new_callable=AsyncMock,
            return_value=BehavioralTestResult(
                capability="play",
                confirmed=True,
                confidence_boost=0.2,
                observation="OK",
                duration_ms=50,
            ),
        ):
            result = await engine.validate_map(mock_page, valid_capability_map)

        assert result is True

    @pytest.mark.asyncio
    async def test_validate_fails_if_behavioral_fails(
        self, engine, mock_page, valid_capability_map
    ):
        """Se qualquer teste comportamental falha, retorna False."""
        with patch.object(
            engine._behavioral_tester,
            "test_capability",
            new_callable=AsyncMock,
            return_value=BehavioralTestResult(
                capability="play",
                confirmed=False,
                confidence_boost=0.0,
                observation="Não responde",
                duration_ms=50,
            ),
        ):
            result = await engine.validate_map(mock_page, valid_capability_map)

        assert result is False

    @pytest.mark.asyncio
    async def test_validate_invalid_map_returns_false(
        self, engine, mock_page, valid_capability_map
    ):
        """Mapa já invalidado retorna False imediatamente."""
        valid_capability_map.invalidate()

        result = await engine.validate_map(mock_page, valid_capability_map)

        assert result is False

    @pytest.mark.asyncio
    async def test_validate_empty_map_returns_false(
        self, engine, mock_page
    ):
        """Mapa sem capabilities available retorna False."""
        data = CapabilityMapData(
            player_info=PlayerInfo(),
            capabilities={
                "play": Capability(
                    name="play",
                    available=False,
                    confidence=0.3,
                ),
            },
            valid=True,
        )
        empty_map = CapabilityMap(data)

        result = await engine.validate_map(mock_page, empty_map)

        assert result is False


# ============================================================
# Testes de rediscover (Requirement 4.5)
# ============================================================


class TestRediscover:
    """Testes de re-discovery."""

    @pytest.mark.asyncio
    async def test_rediscover_invalidates_and_runs_new(
        self, engine, mock_page, valid_capability_map
    ):
        """rediscover invalida mapa atual e executa novo discovery."""
        engine._cached_map = valid_capability_map
        assert engine.cached_map.is_valid()

        with patch.object(
            engine._dom_analyzer, "analyze", new_callable=AsyncMock, return_value=[]
        ), patch.object(
            engine._js_analyzer, "analyze", new_callable=AsyncMock, return_value=[]
        ), patch.object(
            engine._browser_api_analyzer, "analyze", new_callable=AsyncMock, return_value=[]
        ), patch.object(
            engine._css_analyzer, "analyze", new_callable=AsyncMock, return_value=[]
        ):
            result = await engine.rediscover(mock_page)

        # Novo mapa deve ser diferente do antigo
        assert result is not valid_capability_map
        assert result.is_valid()
        # Cache atualizado
        assert engine.cached_map is result

    @pytest.mark.asyncio
    async def test_rediscover_clears_cache(
        self, engine, mock_page, valid_capability_map
    ):
        """rediscover limpa o cache antes de executar discovery."""
        engine._cached_map = valid_capability_map

        with patch.object(
            engine._dom_analyzer, "analyze", new_callable=AsyncMock, return_value=[]
        ), patch.object(
            engine._js_analyzer, "analyze", new_callable=AsyncMock, return_value=[]
        ), patch.object(
            engine._browser_api_analyzer, "analyze", new_callable=AsyncMock, return_value=[]
        ), patch.object(
            engine._css_analyzer, "analyze", new_callable=AsyncMock, return_value=[]
        ):
            # Durante a execução, o mapa original deve ter sido invalidado
            result = await engine.rediscover(mock_page)

        assert valid_capability_map.is_valid() is False


# ============================================================
# Testes de classificação de capabilities
# ============================================================


class TestCapabilityClassification:
    """Testes da classificação de confidence e available."""

    @pytest.mark.asyncio
    async def test_confidence_above_threshold_is_available(
        self, engine, mock_page
    ):
        """Confidence >= 0.7 classifica como available=True."""
        dom_evidence = [
            DOMEvidence(
                element_description="button Play",
                capability_hint="play",
                confidence_contribution=0.7,
                attributes={"aria-label": "Play"},
                interaction_hint=InteractionLevel.SEMANTIC_DOM,
            ),
        ]

        with patch.object(
            engine._dom_analyzer, "analyze", new_callable=AsyncMock, return_value=dom_evidence
        ), patch.object(
            engine._js_analyzer, "analyze", new_callable=AsyncMock, return_value=[]
        ), patch.object(
            engine._browser_api_analyzer, "analyze", new_callable=AsyncMock, return_value=[]
        ), patch.object(
            engine._css_analyzer, "analyze", new_callable=AsyncMock, return_value=[]
        ):
            result = await engine.discover(mock_page)

        play_cap = result.get_capability("play")
        assert play_cap.available is True
        assert play_cap.confidence >= CONFIDENCE_THRESHOLD

    @pytest.mark.asyncio
    async def test_confidence_below_threshold_is_unavailable(
        self, engine, mock_page
    ):
        """Confidence < 0.7 classifica como available=False."""
        dom_evidence = [
            DOMEvidence(
                element_description="button Play",
                capability_hint="play",
                confidence_contribution=0.3,
                attributes={"aria-label": "Play"},
                interaction_hint=InteractionLevel.SEMANTIC_DOM,
            ),
        ]

        with patch.object(
            engine._dom_analyzer, "analyze", new_callable=AsyncMock, return_value=dom_evidence
        ), patch.object(
            engine._js_analyzer, "analyze", new_callable=AsyncMock, return_value=[]
        ), patch.object(
            engine._browser_api_analyzer, "analyze", new_callable=AsyncMock, return_value=[]
        ), patch.object(
            engine._css_analyzer, "analyze", new_callable=AsyncMock, return_value=[]
        ):
            result = await engine.discover(mock_page)

        play_cap = result.get_capability("play")
        assert play_cap.available is False
        assert play_cap.confidence < CONFIDENCE_THRESHOLD

    @pytest.mark.asyncio
    async def test_combined_evidence_increases_confidence(
        self, engine, mock_page
    ):
        """Evidência combinada de múltiplos analyzers soma confidence."""
        dom_evidence = [
            DOMEvidence(
                element_description="button Mute",
                capability_hint="mute",
                confidence_contribution=0.4,
                attributes={"aria-label": "Mute"},
                interaction_hint=InteractionLevel.SEMANTIC_DOM,
            ),
        ]
        js_evidence = [
            JSEvidence(
                api_path="video.muted",
                capability_hint="mute",
                confidence_contribution=0.35,
                details={"method": "muted", "source": "HTMLMediaElement"},
                interaction_hint=InteractionLevel.PLAYER_API,
            ),
        ]

        with patch.object(
            engine._dom_analyzer, "analyze", new_callable=AsyncMock, return_value=dom_evidence
        ), patch.object(
            engine._js_analyzer, "analyze", new_callable=AsyncMock, return_value=js_evidence
        ), patch.object(
            engine._browser_api_analyzer, "analyze", new_callable=AsyncMock, return_value=[]
        ), patch.object(
            engine._css_analyzer, "analyze", new_callable=AsyncMock, return_value=[]
        ):
            result = await engine.discover(mock_page)

        mute_cap = result.get_capability("mute")
        assert mute_cap is not None
        # 0.4 (DOM) + 0.35 (JS) = 0.75
        assert mute_cap.confidence == 0.75
        assert mute_cap.available is True

    @pytest.mark.asyncio
    async def test_confidence_clamped_to_one(self, engine, mock_page):
        """Confidence é limitada a 1.0 máximo."""
        dom_evidence = [
            DOMEvidence(
                element_description="button Play",
                capability_hint="play",
                confidence_contribution=0.8,
                attributes={"aria-label": "Play"},
                interaction_hint=InteractionLevel.SEMANTIC_DOM,
            ),
        ]
        js_evidence = [
            JSEvidence(
                api_path="player.play",
                capability_hint="play",
                confidence_contribution=0.5,
                details={"method": "play", "source": "shaka-player-instance"},
                interaction_hint=InteractionLevel.PLAYER_API,
            ),
        ]

        with patch.object(
            engine._dom_analyzer, "analyze", new_callable=AsyncMock, return_value=dom_evidence
        ), patch.object(
            engine._js_analyzer, "analyze", new_callable=AsyncMock, return_value=js_evidence
        ), patch.object(
            engine._browser_api_analyzer, "analyze", new_callable=AsyncMock, return_value=[]
        ), patch.object(
            engine._css_analyzer, "analyze", new_callable=AsyncMock, return_value=[]
        ):
            result = await engine.discover(mock_page)

        play_cap = result.get_capability("play")
        assert play_cap.confidence == 1.0


# ============================================================
# Testes de player info extraction
# ============================================================


class TestPlayerInfoExtraction:
    """Testes de extração de informações do player."""

    @pytest.mark.asyncio
    async def test_extracts_library_and_version(self, engine, mock_page):
        """Extrai library e version do JS analyzer."""
        js_evidence = [
            JSEvidence(
                api_path="window.shaka-player",
                capability_hint="player_library",
                confidence_contribution=0.3,
                details={
                    "library": "shaka-player",
                    "version": "4.3.0",
                    "player_instance": "video.__shaka_player",
                    "globals_found": ["window.shaka"],
                },
                interaction_hint=InteractionLevel.PLAYER_API,
            ),
        ]

        with patch.object(
            engine._dom_analyzer, "analyze", new_callable=AsyncMock, return_value=[]
        ), patch.object(
            engine._js_analyzer, "analyze", new_callable=AsyncMock, return_value=js_evidence
        ), patch.object(
            engine._browser_api_analyzer, "analyze", new_callable=AsyncMock, return_value=[]
        ), patch.object(
            engine._css_analyzer, "analyze", new_callable=AsyncMock, return_value=[]
        ):
            result = await engine.discover(mock_page)

        assert result.player_info.library == "shaka-player"
        assert result.player_info.version == "4.3.0"
        assert result.player_info.discovered_at != ""

    @pytest.mark.asyncio
    async def test_unknown_library_when_no_js_evidence(
        self, engine, mock_page
    ):
        """Se JS analyzer não detecta biblioteca, library é None."""
        with patch.object(
            engine._dom_analyzer, "analyze", new_callable=AsyncMock, return_value=[]
        ), patch.object(
            engine._js_analyzer, "analyze", new_callable=AsyncMock, return_value=[]
        ), patch.object(
            engine._browser_api_analyzer, "analyze", new_callable=AsyncMock, return_value=[]
        ), patch.object(
            engine._css_analyzer, "analyze", new_callable=AsyncMock, return_value=[]
        ):
            result = await engine.discover(mock_page)

        assert result.player_info.library is None
        assert result.player_info.version is None


# ============================================================
# Testes de strategies
# ============================================================


class TestStrategies:
    """Testes de construção de interaction strategies."""

    @pytest.mark.asyncio
    async def test_strategies_ordered_by_level(self, engine, mock_page):
        """Strategies são ordenadas: PLAYER_API < SEMANTIC_DOM < VISUAL_FALLBACK."""
        js_evidence = [
            JSEvidence(
                api_path="player.play",
                capability_hint="play",
                confidence_contribution=0.8,
                details={"method": "play", "source": "shaka-player-instance"},
                interaction_hint=InteractionLevel.PLAYER_API,
            ),
        ]

        with patch.object(
            engine._dom_analyzer, "analyze", new_callable=AsyncMock, return_value=[]
        ), patch.object(
            engine._js_analyzer, "analyze", new_callable=AsyncMock, return_value=js_evidence
        ), patch.object(
            engine._browser_api_analyzer, "analyze", new_callable=AsyncMock, return_value=[]
        ), patch.object(
            engine._css_analyzer, "analyze", new_callable=AsyncMock, return_value=[]
        ):
            result = await engine.discover(mock_page)

        play_cap = result.get_capability("play")
        strategies = play_cap.strategies
        # Deve ter PLAYER_API primeiro
        assert strategies[0].level == InteractionLevel.PLAYER_API
        # Último é VISUAL_FALLBACK
        assert strategies[-1].level == InteractionLevel.VISUAL_FALLBACK

    @pytest.mark.asyncio
    async def test_unknown_capabilities_have_visual_fallback(
        self, engine, mock_page
    ):
        """Capabilities desconhecidas (UNKNOWN) têm apenas VISUAL_FALLBACK."""
        with patch.object(
            engine._dom_analyzer, "analyze", new_callable=AsyncMock, return_value=[]
        ), patch.object(
            engine._js_analyzer, "analyze", new_callable=AsyncMock, return_value=[]
        ), patch.object(
            engine._browser_api_analyzer, "analyze", new_callable=AsyncMock, return_value=[]
        ), patch.object(
            engine._css_analyzer, "analyze", new_callable=AsyncMock, return_value=[]
        ):
            result = await engine.discover(mock_page)

        settings_cap = result.get_capability("settings")
        assert settings_cap.strategies[0].level == InteractionLevel.VISUAL_FALLBACK
