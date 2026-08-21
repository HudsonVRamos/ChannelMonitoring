"""Property-based tests para AudioTrackTester.

# Feature: unified-channel-monitor, Property 6: Track test failure produces correct status and reason

Valida que para qualquer audio track onde a validação via Shaka API
resulta em timeout, o resultado tem status=FAIL, fail_reason="switch_timeout"
e switch_validated=False.

**Validates: Requirements 5.5, 6.4**
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from src.unified_channel_monitor.audio_tester import AudioTrackTester
from src.unified_channel_monitor.config import UnifiedMonitorConfig
from src.unified_channel_monitor.models import AudioTrackResult


# Estratégia: nomes de track não-vazios (caracteres imprimíveis)
_track_name_strategy = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "S", "Z"),
        blacklist_characters="\x00",
    ),
    min_size=1,
    max_size=50,
).filter(lambda s: s.strip() != "")


# Feature: unified-channel-monitor, Property 6: Track test failure produces correct status and reason


class TestPropertyAudioTrackFailureStatus:
    """Property 6 (Audio): Track test failure produces correct status and reason.

    Para qualquer audio track onde a validação via Shaka API resulta em
    timeout (_validate_switch_shaka retorna False), o resultado SHALL ter
    status=FAIL e fail_reason="switch_timeout" e switch_validated=False.

    **Validates: Requirements 5.5, 6.4**
    """

    @given(track_name=_track_name_strategy)
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_audio_switch_timeout_produces_fail_status(
        self, track_name: str
    ) -> None:
        """Para qualquer nome de track, se _validate_switch_shaka retorna
        False (timeout), o resultado deve ser FAIL com switch_timeout.

        **Validates: Requirements 5.5**
        """
        # Setup: mock page e telemetry collector
        mock_page = AsyncMock()
        mock_page.hover = AsyncMock()
        mock_page.click = AsyncMock()
        mock_page.evaluate = AsyncMock(return_value=True)
        mock_page.keyboard = MagicMock()
        mock_page.keyboard.press = AsyncMock()

        # Locator mock para _ensure_dialog_open
        mock_locator = AsyncMock()
        mock_locator.is_visible = AsyncMock(return_value=False)
        mock_page.locator = MagicMock(return_value=mock_locator)

        mock_telemetry = MagicMock()
        mock_telemetry.annotate_current_sample = MagicMock()

        mock_capability_map = {
            "settings": {"selector": '[aria-label="settings"]'},
        }

        # Config com timeout muito curto para testes rápidos
        config = UnifiedMonitorConfig(
            track_switch_timeout_s=0.01,
        )

        tester = AudioTrackTester(
            page=mock_page,
            capability_map=mock_capability_map,
            config=config,
            telemetry_collector=mock_telemetry,
        )

        # Mock: _select_track retorna True (UI selection ok)
        # mas _validate_switch_shaka retorna False (timeout)
        with patch.object(
            tester, "_select_track", new_callable=AsyncMock
        ) as mock_select, patch.object(
            tester, "_validate_switch_shaka", new_callable=AsyncMock
        ) as mock_validate:
            mock_select.return_value = True
            mock_validate.return_value = False

            result = await tester._test_single_track(track_name)

        # Assertions
        assert isinstance(result, AudioTrackResult)
        assert result.track_name == track_name
        assert result.status == "FAIL"
        assert result.fail_reason == "switch_timeout"
        assert result.switch_validated is False
        assert result.duration_ms >= 0

    @given(track_name=_track_name_strategy)
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_audio_select_failure_produces_fail_status(
        self, track_name: str
    ) -> None:
        """Para qualquer nome de track, se _select_track retorna False
        (seleção na UI falhou), o resultado também deve ser FAIL
        com switch_timeout.

        **Validates: Requirements 5.5**
        """
        # Setup
        mock_page = AsyncMock()
        mock_page.hover = AsyncMock()
        mock_page.click = AsyncMock()
        mock_page.evaluate = AsyncMock(return_value=True)
        mock_page.keyboard = MagicMock()
        mock_page.keyboard.press = AsyncMock()

        mock_locator = AsyncMock()
        mock_locator.is_visible = AsyncMock(return_value=False)
        mock_page.locator = MagicMock(return_value=mock_locator)

        mock_telemetry = MagicMock()
        mock_telemetry.annotate_current_sample = MagicMock()

        mock_capability_map = {
            "settings": {"selector": '[aria-label="settings"]'},
        }

        config = UnifiedMonitorConfig(
            track_switch_timeout_s=0.01,
        )

        tester = AudioTrackTester(
            page=mock_page,
            capability_map=mock_capability_map,
            config=config,
            telemetry_collector=mock_telemetry,
        )

        # Mock: _select_track retorna False (falha na UI)
        with patch.object(
            tester, "_select_track", new_callable=AsyncMock
        ) as mock_select:
            mock_select.return_value = False

            result = await tester._test_single_track(track_name)

        # Assertions
        assert isinstance(result, AudioTrackResult)
        assert result.track_name == track_name
        assert result.status == "FAIL"
        assert result.fail_reason == "switch_timeout"
        assert result.switch_validated is False
        assert result.duration_ms >= 0
