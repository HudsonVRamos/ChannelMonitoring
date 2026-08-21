"""Testes unitários do InteractionManager.

Testa o gerenciador de interações com três níveis:
- Hierarquia: API (Nível 1) → DOM semântico (Nível 2) → Visual (Nível 3)
- Fallback automático entre níveis
- Rejeição de coordenadas fixas e índices posicionais
- Tratamento de erros e edge cases

Requirements testados: 12.1, 12.2, 12.3, 12.4
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.player_discovery.interaction.manager import (
    InteractionManager,
    InteractionRejectedError,
)
from src.player_discovery.models.capability import (
    Capability,
    CapabilityMapData,
    InteractionStrategy,
    PlayerInfo,
)
from src.player_discovery.models.capability_map import CapabilityMap
from src.player_discovery.models.enums import InteractionLevel


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def manager():
    """Instância limpa do InteractionManager."""
    return InteractionManager()


@pytest.fixture
def mock_page():
    """Mock de Page do Playwright."""
    page = AsyncMock()
    page.evaluate = AsyncMock(return_value=None)
    page.get_by_role = MagicMock()
    page.get_by_label = MagicMock()
    page.get_by_text = MagicMock()
    page.get_by_test_id = MagicMock()
    page.locator = MagicMock()

    # Configurar retorno padrão dos locators
    mock_locator = AsyncMock()
    mock_locator.click = AsyncMock()
    mock_locator.first = mock_locator
    page.get_by_role.return_value = mock_locator
    page.get_by_label.return_value = mock_locator
    page.get_by_text.return_value = mock_locator
    page.get_by_test_id.return_value = mock_locator
    page.locator.return_value = mock_locator

    return page


@pytest.fixture
def capability_map_with_all_levels():
    """CapabilityMap com capability 'play' tendo 3 níveis."""
    caps = {
        "play": Capability(
            name="play",
            available=True,
            confidence=0.9,
            evidence=["API disponível", "DOM semântico", "Visual"],
            interaction_strategy=InteractionLevel.PLAYER_API,
            strategies=[
                InteractionStrategy(
                    level=InteractionLevel.PLAYER_API,
                    type="player_api",
                    details={"method": "player.play()"},
                ),
                InteractionStrategy(
                    level=InteractionLevel.SEMANTIC_DOM,
                    type="semantic_dom",
                    details={
                        "role": "button",
                        "aria_label": "Play",
                    },
                ),
                InteractionStrategy(
                    level=InteractionLevel.VISUAL_FALLBACK,
                    type="visual_fallback",
                    details={
                        "description": "botão play central",
                    },
                ),
            ],
        ),
    }
    data = CapabilityMapData(
        player_info=PlayerInfo(
            library="shaka-player",
            version="4.0",
            video_elements=["video"],
        ),
        capabilities=caps,
        valid=True,
    )
    return CapabilityMap(data)


@pytest.fixture
def capability_map_api_only():
    """CapabilityMap com capability 'mute' tendo só API."""
    caps = {
        "mute": Capability(
            name="mute",
            available=True,
            confidence=0.85,
            evidence=["API disponível"],
            interaction_strategy=InteractionLevel.PLAYER_API,
            strategies=[
                InteractionStrategy(
                    level=InteractionLevel.PLAYER_API,
                    type="player_api",
                    details={"method": "video.muted = true"},
                ),
            ],
        ),
    }
    data = CapabilityMapData(
        player_info=PlayerInfo(),
        capabilities=caps,
        valid=True,
    )
    return CapabilityMap(data)


# ============================================================
# Testes de hierarquia (Requirement 12.1, 12.2)
# ============================================================


class TestHierarchy:
    """Testes da hierarquia de interação API → DOM → Visual."""

    @pytest.mark.asyncio
    async def test_executes_api_first_when_available(
        self, manager, mock_page, capability_map_with_all_levels
    ):
        """Nível 1 (API) é tentado primeiro."""
        result = await manager.execute(
            mock_page, "play", "click", capability_map_with_all_levels
        )

        assert result.success is True
        assert result.level_used == InteractionLevel.PLAYER_API
        mock_page.evaluate.assert_called_once()

    @pytest.mark.asyncio
    async def test_falls_back_to_dom_when_api_fails(
        self, manager, mock_page, capability_map_with_all_levels
    ):
        """Se Nível 1 falha, tenta Nível 2 (DOM semântico)."""
        mock_page.evaluate.side_effect = Exception("API error")

        result = await manager.execute(
            mock_page, "play", "click", capability_map_with_all_levels
        )

        assert result.success is True
        assert result.level_used == InteractionLevel.SEMANTIC_DOM

    @pytest.mark.asyncio
    async def test_falls_back_to_visual_when_dom_fails(
        self, manager, mock_page, capability_map_with_all_levels
    ):
        """Se Nível 1 e 2 falham, tenta Nível 3 (Visual)."""
        mock_page.evaluate.side_effect = Exception("API error")

        # Fazer o locator do DOM falhar
        mock_locator = AsyncMock()
        mock_locator.click = AsyncMock(
            side_effect=Exception("Element not found")
        )
        mock_page.get_by_role.return_value = mock_locator

        # Visual fallback usa get_by_text para busca por descrição
        mock_visual_locator = AsyncMock()
        mock_visual_locator.first = AsyncMock()
        mock_visual_locator.first.click = AsyncMock()
        mock_page.get_by_text.return_value = mock_visual_locator

        result = await manager.execute(
            mock_page, "play", "click", capability_map_with_all_levels
        )

        assert result.success is True
        assert result.level_used == InteractionLevel.VISUAL_FALLBACK

    @pytest.mark.asyncio
    async def test_all_levels_fail_returns_failure(
        self, manager, mock_page, capability_map_with_all_levels
    ):
        """Se todos os níveis falham, retorna failure."""
        mock_page.evaluate.side_effect = Exception("API error")

        mock_locator = AsyncMock()
        mock_locator.click = AsyncMock(
            side_effect=Exception("Not found")
        )
        mock_locator.first = mock_locator
        mock_page.get_by_role.return_value = mock_locator
        mock_page.get_by_text.return_value = mock_locator

        result = await manager.execute(
            mock_page, "play", "click", capability_map_with_all_levels
        )

        assert result.success is False
        assert "Todos os níveis falharam" in result.error

    @pytest.mark.asyncio
    async def test_api_only_no_fallback_needed(
        self, manager, mock_page, capability_map_api_only
    ):
        """Com só Nível 1, sucesso direto sem fallback."""
        result = await manager.execute(
            mock_page, "mute", "toggle", capability_map_api_only
        )

        assert result.success is True
        assert result.level_used == InteractionLevel.PLAYER_API


# ============================================================
# Testes de Nível 1 — API (Requirement 12.1)
# ============================================================


class TestExecuteAPI:
    """Testes do Nível 1: Chamada direta à API do player."""

    @pytest.mark.asyncio
    async def test_api_with_method_call(self, manager, mock_page):
        """Executa método com parênteses."""
        strategy = InteractionStrategy(
            level=InteractionLevel.PLAYER_API,
            type="player_api",
            details={"method": "player.play()"},
        )

        result = await manager._execute_api(mock_page, strategy)

        assert result.success is True
        assert result.level_used == InteractionLevel.PLAYER_API
        mock_page.evaluate.assert_called_with("player.play()")

    @pytest.mark.asyncio
    async def test_api_adds_parentheses_if_missing(
        self, manager, mock_page
    ):
        """Adiciona () se método não contém parênteses."""
        strategy = InteractionStrategy(
            level=InteractionLevel.PLAYER_API,
            type="player_api",
            details={"method": "player.play"},
        )

        result = await manager._execute_api(mock_page, strategy)

        assert result.success is True
        mock_page.evaluate.assert_called_with("player.play()")

    @pytest.mark.asyncio
    async def test_api_with_assignment(self, manager, mock_page):
        """Executa assignment (com =) sem adicionar ()."""
        strategy = InteractionStrategy(
            level=InteractionLevel.PLAYER_API,
            type="player_api",
            details={"method": "video.muted = true"},
        )

        result = await manager._execute_api(mock_page, strategy)

        assert result.success is True
        mock_page.evaluate.assert_called_with("video.muted = true")

    @pytest.mark.asyncio
    async def test_api_with_js_code(self, manager, mock_page):
        """Usa js_code quando disponível em vez de method."""
        strategy = InteractionStrategy(
            level=InteractionLevel.PLAYER_API,
            type="player_api",
            details={
                "js_code": "document.querySelector('video').play()",
            },
        )

        result = await manager._execute_api(mock_page, strategy)

        assert result.success is True
        mock_page.evaluate.assert_called_with(
            "document.querySelector('video').play()"
        )

    @pytest.mark.asyncio
    async def test_api_without_method_returns_error(
        self, manager, mock_page
    ):
        """Retorna erro se strategy não tem method nem js_code."""
        strategy = InteractionStrategy(
            level=InteractionLevel.PLAYER_API,
            type="player_api",
            details={},
        )

        result = await manager._execute_api(mock_page, strategy)

        assert result.success is False
        assert "sem 'method' ou 'js_code'" in result.error

    @pytest.mark.asyncio
    async def test_api_captures_duration(self, manager, mock_page):
        """Registra duração da execução em milissegundos."""
        strategy = InteractionStrategy(
            level=InteractionLevel.PLAYER_API,
            type="player_api",
            details={"method": "player.play()"},
        )

        result = await manager._execute_api(mock_page, strategy)

        assert result.duration_ms >= 0


# ============================================================
# Testes de Nível 2 — DOM Semântico (Requirement 12.1)
# ============================================================


class TestExecuteSemanticDOM:
    """Testes do Nível 2: Locator via role, aria-label, text."""

    @pytest.mark.asyncio
    async def test_dom_with_role_and_aria_label(
        self, manager, mock_page
    ):
        """Usa get_by_role com name (aria_label)."""
        strategy = InteractionStrategy(
            level=InteractionLevel.SEMANTIC_DOM,
            type="semantic_dom",
            details={
                "role": "button",
                "aria_label": "Play",
            },
        )

        result = await manager._execute_semantic_dom(
            mock_page, strategy
        )

        assert result.success is True
        assert result.level_used == InteractionLevel.SEMANTIC_DOM
        mock_page.get_by_role.assert_called_with(
            "button", name="Play"
        )

    @pytest.mark.asyncio
    async def test_dom_with_role_and_text(self, manager, mock_page):
        """Usa get_by_role com name (text)."""
        strategy = InteractionStrategy(
            level=InteractionLevel.SEMANTIC_DOM,
            type="semantic_dom",
            details={"role": "button", "text": "Reproduzir"},
        )

        result = await manager._execute_semantic_dom(
            mock_page, strategy
        )

        assert result.success is True
        mock_page.get_by_role.assert_called_with(
            "button", name="Reproduzir"
        )

    @pytest.mark.asyncio
    async def test_dom_with_aria_label_only(
        self, manager, mock_page
    ):
        """Usa get_by_label quando só aria_label disponível."""
        strategy = InteractionStrategy(
            level=InteractionLevel.SEMANTIC_DOM,
            type="semantic_dom",
            details={"aria_label": "Volume"},
        )

        result = await manager._execute_semantic_dom(
            mock_page, strategy
        )

        assert result.success is True
        mock_page.get_by_label.assert_called_with("Volume")

    @pytest.mark.asyncio
    async def test_dom_with_text_only(self, manager, mock_page):
        """Usa get_by_text quando só text disponível."""
        strategy = InteractionStrategy(
            level=InteractionLevel.SEMANTIC_DOM,
            type="semantic_dom",
            details={"text": "Legendas"},
        )

        result = await manager._execute_semantic_dom(
            mock_page, strategy
        )

        assert result.success is True
        mock_page.get_by_text.assert_called_with("Legendas")

    @pytest.mark.asyncio
    async def test_dom_with_data_testid(self, manager, mock_page):
        """Usa get_by_test_id quando data_testid disponível."""
        strategy = InteractionStrategy(
            level=InteractionLevel.SEMANTIC_DOM,
            type="semantic_dom",
            details={"data_testid": "play-btn"},
        )

        result = await manager._execute_semantic_dom(
            mock_page, strategy
        )

        assert result.success is True
        mock_page.get_by_test_id.assert_called_with("play-btn")

    @pytest.mark.asyncio
    async def test_dom_without_semantic_attrs_returns_error(
        self, manager, mock_page
    ):
        """Retorna erro se sem atributos semânticos."""
        strategy = InteractionStrategy(
            level=InteractionLevel.SEMANTIC_DOM,
            type="semantic_dom",
            details={},
        )

        result = await manager._execute_semantic_dom(
            mock_page, strategy
        )

        assert result.success is False
        assert "sem atributos semânticos" in result.error


# ============================================================
# Testes de Nível 3 — Visual Fallback (Requirement 12.1)
# ============================================================


class TestExecuteVisualFallback:
    """Testes do Nível 3: Interação visual sem coordenadas fixas."""

    @pytest.mark.asyncio
    async def test_visual_with_js_search(self, manager, mock_page):
        """Usa JavaScript para busca visual dinâmica."""
        mock_page.evaluate.return_value = True
        strategy = InteractionStrategy(
            level=InteractionLevel.VISUAL_FALLBACK,
            type="visual_fallback",
            details={
                "js_visual_search": (
                    "document.querySelector('[aria-live]')"
                    ".click()"
                ),
            },
        )

        result = await manager._execute_visual_fallback(
            mock_page, strategy
        )

        assert result.success is True
        assert result.level_used == InteractionLevel.VISUAL_FALLBACK

    @pytest.mark.asyncio
    async def test_visual_with_selector(self, manager, mock_page):
        """Usa selector semântico como fallback visual."""
        strategy = InteractionStrategy(
            level=InteractionLevel.VISUAL_FALLBACK,
            type="visual_fallback",
            details={
                "visual_selector": "[data-player-control='play']",
            },
        )

        result = await manager._execute_visual_fallback(
            mock_page, strategy
        )

        assert result.success is True

    @pytest.mark.asyncio
    async def test_visual_with_description(self, manager, mock_page):
        """Usa descrição textual para busca."""
        mock_text_locator = AsyncMock()
        mock_text_locator.first = AsyncMock()
        mock_text_locator.first.click = AsyncMock()
        mock_page.get_by_text.return_value = mock_text_locator

        strategy = InteractionStrategy(
            level=InteractionLevel.VISUAL_FALLBACK,
            type="visual_fallback",
            details={"description": "botão play central"},
        )

        result = await manager._execute_visual_fallback(
            mock_page, strategy
        )

        assert result.success is True

    @pytest.mark.asyncio
    async def test_visual_without_details_returns_error(
        self, manager, mock_page
    ):
        """Retorna erro se sem qualquer informação visual."""
        mock_page.evaluate.return_value = None
        strategy = InteractionStrategy(
            level=InteractionLevel.VISUAL_FALLBACK,
            type="visual_fallback",
            details={},
        )

        result = await manager._execute_visual_fallback(
            mock_page, strategy
        )

        assert result.success is False
        assert "falhou" in result.error


# ============================================================
# Testes de Rejeição (Requirement 12.4)
# ============================================================


class TestRejection:
    """Testes de rejeição de coordenadas fixas e índices posicionais."""

    @pytest.mark.asyncio
    async def test_rejects_x_coordinate(
        self, manager, mock_page, capability_map_with_all_levels
    ):
        """Rejeita strategy com coordenada x."""
        # Substituir strategy com coordenada proibida
        cap = capability_map_with_all_levels.get_capability("play")
        cap.strategies = [
            InteractionStrategy(
                level=InteractionLevel.PLAYER_API,
                type="player_api",
                details={"x": 100, "method": "click"},
            ),
        ]

        with pytest.raises(InteractionRejectedError):
            await manager.execute(
                mock_page,
                "play",
                "click",
                capability_map_with_all_levels,
            )

    @pytest.mark.asyncio
    async def test_rejects_y_coordinate(
        self, manager, mock_page, capability_map_with_all_levels
    ):
        """Rejeita strategy com coordenada y."""
        cap = capability_map_with_all_levels.get_capability("play")
        cap.strategies = [
            InteractionStrategy(
                level=InteractionLevel.SEMANTIC_DOM,
                type="semantic_dom",
                details={"y": 200, "role": "button"},
            ),
        ]

        with pytest.raises(InteractionRejectedError):
            await manager.execute(
                mock_page,
                "play",
                "click",
                capability_map_with_all_levels,
            )

    @pytest.mark.asyncio
    async def test_rejects_position_key(
        self, manager, mock_page, capability_map_with_all_levels
    ):
        """Rejeita strategy com chave 'top' ou 'left'."""
        cap = capability_map_with_all_levels.get_capability("play")
        cap.strategies = [
            InteractionStrategy(
                level=InteractionLevel.VISUAL_FALLBACK,
                type="visual_fallback",
                details={"top": 50, "left": 100},
            ),
        ]

        with pytest.raises(InteractionRejectedError):
            await manager.execute(
                mock_page,
                "play",
                "click",
                capability_map_with_all_levels,
            )

    @pytest.mark.asyncio
    async def test_rejects_index_key(
        self, manager, mock_page, capability_map_with_all_levels
    ):
        """Rejeita strategy com chave 'index'."""
        cap = capability_map_with_all_levels.get_capability("play")
        cap.strategies = [
            InteractionStrategy(
                level=InteractionLevel.SEMANTIC_DOM,
                type="semantic_dom",
                details={"index": 0, "role": "button"},
            ),
        ]

        with pytest.raises(InteractionRejectedError):
            await manager.execute(
                mock_page,
                "play",
                "click",
                capability_map_with_all_levels,
            )

    @pytest.mark.asyncio
    async def test_rejects_nth_child_in_value(
        self, manager, mock_page, capability_map_with_all_levels
    ):
        """Rejeita strategy com :nth-child em valor string."""
        cap = capability_map_with_all_levels.get_capability("play")
        cap.strategies = [
            InteractionStrategy(
                level=InteractionLevel.SEMANTIC_DOM,
                type="semantic_dom",
                details={
                    "selector": "button:nth-child(2)",
                    "role": "button",
                },
            ),
        ]

        with pytest.raises(InteractionRejectedError):
            await manager.execute(
                mock_page,
                "play",
                "click",
                capability_map_with_all_levels,
            )

    @pytest.mark.asyncio
    async def test_rejects_first_child_in_value(
        self, manager, mock_page, capability_map_with_all_levels
    ):
        """Rejeita strategy com :first-child em valor string."""
        cap = capability_map_with_all_levels.get_capability("play")
        cap.strategies = [
            InteractionStrategy(
                level=InteractionLevel.SEMANTIC_DOM,
                type="semantic_dom",
                details={
                    "selector": ".controls > :first-child",
                    "role": "button",
                },
            ),
        ]

        with pytest.raises(InteractionRejectedError):
            await manager.execute(
                mock_page,
                "play",
                "click",
                capability_map_with_all_levels,
            )

    @pytest.mark.asyncio
    async def test_rejects_coordinate_pattern_in_value(
        self, manager, mock_page, capability_map_with_all_levels
    ):
        """Rejeita strategy com padrão 'x: 100' em valor."""
        cap = capability_map_with_all_levels.get_capability("play")
        cap.strategies = [
            InteractionStrategy(
                level=InteractionLevel.VISUAL_FALLBACK,
                type="visual_fallback",
                details={
                    "description": "click at x: 100, y: 200",
                },
            ),
        ]

        with pytest.raises(InteractionRejectedError):
            await manager.execute(
                mock_page,
                "play",
                "click",
                capability_map_with_all_levels,
            )

    @pytest.mark.asyncio
    async def test_accepts_valid_semantic_strategy(
        self, manager, mock_page, capability_map_with_all_levels
    ):
        """Aceita strategies semânticas válidas sem problemas."""
        result = await manager.execute(
            mock_page,
            "play",
            "click",
            capability_map_with_all_levels,
        )

        assert result.success is True


# ============================================================
# Testes de edge cases
# ============================================================


class TestEdgeCases:
    """Testes de cenários limite."""

    @pytest.mark.asyncio
    async def test_capability_not_found_returns_error(
        self, manager, mock_page, capability_map_with_all_levels
    ):
        """Retorna erro se capability não existe no mapa."""
        result = await manager.execute(
            mock_page,
            "nonexistent",
            "click",
            capability_map_with_all_levels,
        )

        assert result.success is False
        assert "não encontrada" in result.error

    @pytest.mark.asyncio
    async def test_capability_without_strategies_uses_fallback(
        self, manager, mock_page
    ):
        """Capability sem strategies cria fallback do interaction_strategy."""
        caps = {
            "pause": Capability(
                name="pause",
                available=True,
                confidence=0.8,
                evidence=["DOM encontrado"],
                interaction_strategy=InteractionLevel.SEMANTIC_DOM,
                strategies=[],  # Sem strategies explícitas
            ),
        }
        data = CapabilityMapData(
            player_info=PlayerInfo(),
            capabilities=caps,
            valid=True,
        )
        cap_map = CapabilityMap(data)

        # Vai falhar porque strategy criada não tem details úteis
        result = await manager.execute(
            mock_page, "pause", "click", cap_map
        )

        # Sem details semânticos, o DOM semântico falha
        assert result.success is False

    @pytest.mark.asyncio
    async def test_strategies_ordered_correctly(
        self, manager, mock_page
    ):
        """Strategies são ordenadas 1 → 2 → 3 mesmo se desordenadas."""
        caps = {
            "play": Capability(
                name="play",
                available=True,
                confidence=0.9,
                evidence=["Múltiplas evidências"],
                interaction_strategy=InteractionLevel.PLAYER_API,
                strategies=[
                    # Desordenadas propositalmente
                    InteractionStrategy(
                        level=InteractionLevel.VISUAL_FALLBACK,
                        type="visual_fallback",
                        details={"description": "play"},
                    ),
                    InteractionStrategy(
                        level=InteractionLevel.PLAYER_API,
                        type="player_api",
                        details={"method": "player.play()"},
                    ),
                    InteractionStrategy(
                        level=InteractionLevel.SEMANTIC_DOM,
                        type="semantic_dom",
                        details={
                            "role": "button",
                            "aria_label": "Play",
                        },
                    ),
                ],
            ),
        }
        data = CapabilityMapData(
            player_info=PlayerInfo(),
            capabilities=caps,
            valid=True,
        )
        cap_map = CapabilityMap(data)

        # API deve ser tentada primeiro (Nível 1)
        result = await manager.execute(
            mock_page, "play", "click", cap_map
        )

        assert result.success is True
        assert result.level_used == InteractionLevel.PLAYER_API

    @pytest.mark.asyncio
    async def test_duration_ms_is_positive(
        self, manager, mock_page, capability_map_with_all_levels
    ):
        """Duração registrada é >= 0."""
        result = await manager.execute(
            mock_page,
            "play",
            "click",
            capability_map_with_all_levels,
        )

        assert result.duration_ms >= 0
