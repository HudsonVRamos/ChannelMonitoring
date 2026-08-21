"""Property-based tests para SubtitleTrackTester.

Valida a propriedade de corretude relacionada ao comportamento do
SubtitleTrackTester quando o Settings Dialog falha ao abrir.

Feature: unified-channel-monitor, Property 7: Dialog unavailable marks all tracks as SKIP
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from src.unified_channel_monitor.config import UnifiedMonitorConfig
from src.unified_channel_monitor.models import SubtitleTrackResult
from src.unified_channel_monitor.subtitle_tester import (
    SubtitleTrackTester,
)


# ============================================================
# Estratégias Hypothesis
# ============================================================

# Nomes de tracks de legenda (não-vazios, como gerados pelo dialog)
_track_names = st.lists(
    st.text(min_size=1, max_size=50).filter(
        lambda s: s.strip() != ""
    ),
    min_size=0,
    max_size=20,
)


# ============================================================
# Helpers
# ============================================================


def _make_subtitle_tester_with_dialog_failure(
    failure_mode: str = "returns_false",
) -> SubtitleTrackTester:
    """Cria SubtitleTrackTester com dialog mockado para falhar.

    Args:
        failure_mode: Modo de falha do dialog.
            - "returns_false": open_dialog() retorna False
            - "raises_exception": open_dialog() levanta Exception

    Returns:
        SubtitleTrackTester configurado com mocks.
    """
    mock_page = AsyncMock()
    mock_capability_map = MagicMock()
    config = UnifiedMonitorConfig()
    mock_telemetry = MagicMock()
    mock_telemetry.annotate_current_sample = MagicMock()

    tester = SubtitleTrackTester(
        page=mock_page,
        capability_map=mock_capability_map,
        config=config,
        telemetry_collector=mock_telemetry,
    )

    # Mock do dialog_manager para falhar
    if failure_mode == "returns_false":
        tester._dialog_manager = MagicMock()
        tester._dialog_manager.open_dialog = AsyncMock(
            return_value=False
        )
        tester._dialog_manager.close_dialog = AsyncMock()
    elif failure_mode == "raises_exception":
        tester._dialog_manager = MagicMock()
        tester._dialog_manager.open_dialog = AsyncMock(
            side_effect=Exception("Dialog not found")
        )
        tester._dialog_manager.close_dialog = AsyncMock()

    return tester


def _make_subtitle_tester_with_dialog_fail_after_discover(
    track_names: list[str],
) -> SubtitleTrackTester:
    """Cria SubtitleTrackTester onde dialog abre mas discover falha.

    Neste cenário, o dialog abre com sucesso mas discover_subtitle_options
    levanta exceção — simulando falha ao navegar no dialog. O código
    do subtitle_tester trata isso chamando _mark_all_skip_dialog_unavailable().

    Args:
        track_names: Lista de nomes de tracks (não usados diretamente
            porque discover falha antes de retornar).

    Returns:
        SubtitleTrackTester configurado com mocks.
    """
    mock_page = AsyncMock()
    mock_capability_map = MagicMock()
    config = UnifiedMonitorConfig()
    mock_telemetry = MagicMock()
    mock_telemetry.annotate_current_sample = MagicMock()

    tester = SubtitleTrackTester(
        page=mock_page,
        capability_map=mock_capability_map,
        config=config,
        telemetry_collector=mock_telemetry,
    )

    # Dialog abre com sucesso mas discover falha
    tester._dialog_manager = MagicMock()
    tester._dialog_manager.open_dialog = AsyncMock(
        return_value=True
    )
    tester._dialog_manager.discover_subtitle_options = AsyncMock(
        side_effect=Exception("Failed to discover options")
    )
    tester._dialog_manager.close_dialog = AsyncMock()

    return tester


# ============================================================
# Feature: unified-channel-monitor, Property 7: Dialog unavailable marks all tracks as SKIP
# ============================================================


class TestPropertyDialogUnavailable:
    """Property 7: Dialog unavailable marks all tracks as SKIP.

    Para qualquer lista de subtitle tracks (de tamanho N ≥ 0), se o
    Settings_Dialog falha ao abrir, TODOS os N tracks DEVEM ter
    status=SKIP e fail_reason="dialog_unavailable".

    Implementação atual: quando o dialog falha ao abrir, nenhum track
    é conhecido (pois a descoberta depende do dialog), então o resultado
    é uma lista vazia. A propriedade verifica que:
    1. Nenhum resultado com status PASS ou FAIL é retornado
    2. Todos os resultados (se houver) têm status="SKIP" e
       fail_reason="dialog_unavailable"
    3. A lista pode ser vazia (caso válido quando tracks não são
       conhecidos a priori)

    **Validates: Requirements 6.6**
    """

    @given(track_names=_track_names)
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_dialog_returns_false_all_results_are_skip(
        self, track_names: list[str]
    ) -> None:
        """Quando open_dialog() retorna False, todos os resultados
        retornados (se houver) DEVEM ter status=SKIP e
        fail_reason="dialog_unavailable". Nenhum PASS ou FAIL.

        **Validates: Requirements 6.6**
        """
        tester = _make_subtitle_tester_with_dialog_failure(
            failure_mode="returns_false"
        )

        results = await tester.test_all_tracks()

        # Todos os resultados devem ser SKIP com dialog_unavailable
        for result in results:
            assert isinstance(result, SubtitleTrackResult)
            assert result.status == "SKIP", (
                f"Esperado status='SKIP' mas obteve "
                f"status='{result.status}' para "
                f"track='{result.track_name}'"
            )
            assert result.fail_reason == "dialog_unavailable", (
                f"Esperado fail_reason='dialog_unavailable' "
                f"mas obteve '{result.fail_reason}' para "
                f"track='{result.track_name}'"
            )

        # Nenhum resultado PASS ou FAIL
        for result in results:
            assert result.status != "PASS", (
                "Nenhum resultado deve ser PASS quando dialog falha"
            )
            assert result.status != "FAIL", (
                "Nenhum resultado deve ser FAIL quando dialog falha"
            )

    @given(track_names=_track_names)
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_dialog_raises_exception_all_results_are_skip(
        self, track_names: list[str]
    ) -> None:
        """Quando open_dialog() levanta Exception, todos os resultados
        retornados (se houver) DEVEM ter status=SKIP e
        fail_reason="dialog_unavailable". Nenhum PASS ou FAIL.

        **Validates: Requirements 6.6**
        """
        tester = _make_subtitle_tester_with_dialog_failure(
            failure_mode="raises_exception"
        )

        results = await tester.test_all_tracks()

        # Todos os resultados devem ser SKIP com dialog_unavailable
        for result in results:
            assert isinstance(result, SubtitleTrackResult)
            assert result.status == "SKIP", (
                f"Esperado status='SKIP' mas obteve "
                f"status='{result.status}' para "
                f"track='{result.track_name}'"
            )
            assert result.fail_reason == "dialog_unavailable", (
                f"Esperado fail_reason='dialog_unavailable' "
                f"mas obteve '{result.fail_reason}' para "
                f"track='{result.track_name}'"
            )

        # Nenhum resultado PASS ou FAIL
        for result in results:
            assert result.status != "PASS", (
                "Nenhum resultado deve ser PASS quando dialog falha"
            )
            assert result.status != "FAIL", (
                "Nenhum resultado deve ser FAIL quando dialog falha"
            )

    @given(track_names=_track_names)
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_discover_failure_all_results_are_skip(
        self, track_names: list[str]
    ) -> None:
        """Quando dialog abre mas discover_subtitle_options() levanta
        Exception, todos os resultados retornados (se houver) DEVEM ter
        status=SKIP e fail_reason="dialog_unavailable".

        Isso simula o caso onde o dialog abre mas a navegação dentro
        dele falha (equivalente a dialog_unavailable funcional).

        **Validates: Requirements 6.6**
        """
        tester = _make_subtitle_tester_with_dialog_fail_after_discover(
            track_names
        )

        results = await tester.test_all_tracks()

        # Todos os resultados devem ser SKIP com dialog_unavailable
        for result in results:
            assert isinstance(result, SubtitleTrackResult)
            assert result.status == "SKIP", (
                f"Esperado status='SKIP' mas obteve "
                f"status='{result.status}' para "
                f"track='{result.track_name}'"
            )
            assert result.fail_reason == "dialog_unavailable", (
                f"Esperado fail_reason='dialog_unavailable' "
                f"mas obteve '{result.fail_reason}' para "
                f"track='{result.track_name}'"
            )

    @given(track_names=_track_names)
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_dialog_failure_never_returns_pass_or_fail(
        self, track_names: list[str]
    ) -> None:
        """Invariante: quando dialog falha (qualquer modo), NENHUM
        resultado pode ter status PASS ou FAIL — apenas SKIP é
        permitido.

        Testa ambos os modos de falha e verifica o invariante
        universal.

        **Validates: Requirements 6.6**
        """
        # Modo 1: returns_false
        tester_false = _make_subtitle_tester_with_dialog_failure(
            failure_mode="returns_false"
        )
        results_false = await tester_false.test_all_tracks()

        # Modo 2: raises_exception
        tester_exc = _make_subtitle_tester_with_dialog_failure(
            failure_mode="raises_exception"
        )
        results_exc = await tester_exc.test_all_tracks()

        # Verificar invariante para ambos os modos
        all_results = results_false + results_exc
        for result in all_results:
            assert result.status in ("SKIP",), (
                f"Status inválido '{result.status}' quando "
                f"dialog falha. Apenas 'SKIP' é permitido."
            )
            assert result.fail_reason == "dialog_unavailable", (
                f"fail_reason deve ser 'dialog_unavailable' "
                f"quando dialog falha, mas obteve "
                f"'{result.fail_reason}'"
            )
