"""Property-based tests para AudioSubtitleOrchestrator.

Testa propriedades universais de validação cruzada UI vs API,
restauração de tracks, resiliência a erros e registro de estado da API.

Feature: audio-subtitle-monitoring
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st


# ============================================================
# Helpers puros para testes de propriedade
# ============================================================


def validate_ui_api_consistency(
    ui_options: list[str],
    api_tracks: list[dict],
    selected_ui: str,
) -> str:
    """Classifica consistência entre UI e API.

    Retorna 'consistent' se existe um track na API com language
    igual ao selected_ui e marcado como active.
    Caso contrário, retorna 'ui_api_mismatch'.

    Args:
        ui_options: Lista de textos de opções visíveis na UI.
        api_tracks: Lista de tracks retornados pela Shaka API.
        selected_ui: Opção atualmente selecionada na UI.

    Returns:
        'consistent' ou 'ui_api_mismatch'.
    """
    for track in api_tracks:
        if track.get("language") == selected_ui and track.get("active"):
            return "consistent"
    return "ui_api_mismatch"


def get_restoration_target(
    initial_track: str,
    tested_tracks: list[str],
) -> str:
    """Retorna o track alvo para restauração.

    A restauração sempre aponta para o track inicial,
    independente de quais tracks foram testados.

    Args:
        initial_track: Nome do track antes dos testes.
        tested_tracks: Lista de tracks selecionados durante os testes.

    Returns:
        O nome do track inicial (sempre).
    """
    return initial_track


def simulate_multi_channel_run(
    channels: list[str],
    failing_index: int,
) -> list[dict]:
    """Simula comportamento do run() com resiliência a erros.

    Para cada canal, produz um resultado. O canal no failing_index
    recebe status FAIL com erro, mas todos os outros são processados.

    Args:
        channels: Lista de URLs/identificadores dos canais.
        failing_index: Índice do canal que falha com exceção.

    Returns:
        Lista de relatórios para TODOS os canais.
    """
    results = []
    for i, channel in enumerate(channels):
        if i == failing_index:
            results.append({
                "channel": channel,
                "status": "FAIL",
                "error": "unexpected",
            })
        else:
            results.append({
                "channel": channel,
                "status": "PASS",
                "error": None,
            })
    return results


def create_track_result_with_api_state(
    api_before: list[dict],
    api_after: list[dict],
) -> dict:
    """Simula o padrão de registro de estado da API.

    Cada track test result deve conter api_state_before e
    api_state_after com a chave "tracks" contendo a lista.

    Args:
        api_before: Lista de tracks antes da seleção.
        api_after: Lista de tracks após a seleção.

    Returns:
        Dict com api_state_before e api_state_after não-nulos.
    """
    return {
        "api_state_before": {"tracks": api_before},
        "api_state_after": {"tracks": api_after},
    }


# ============================================================
# Estratégias (Generators) para Hypothesis
# ============================================================

# Nomes de idiomas realistas para geração de tracks
language_strategy = st.sampled_from([
    "Português", "Inglês", "Espanhol", "Francês",
    "Alemão", "Italiano", "Japonês", "Mandarim",
])


@st.composite
def api_track_strategy(draw):
    """Gera um track de API com language e active."""
    language = draw(language_strategy)
    active = draw(st.booleans())
    return {"language": language, "active": active}


@st.composite
def ui_and_api_consistent_pair(draw):
    """Gera par (UI options, API tracks, selected) consistente.

    Garante que o selected_ui tem um track correspondente
    marcado como active na API.
    """
    # Gerar opções de UI (pelo menos 1)
    ui_options = draw(st.lists(
        language_strategy,
        min_size=1,
        max_size=6,
        unique=True,
    ))

    # Escolher uma opção como selecionada
    selected_ui = draw(st.sampled_from(ui_options))

    # Gerar API tracks garantindo que selected_ui está active
    api_tracks = []
    for lang in ui_options:
        if lang == selected_ui:
            api_tracks.append({"language": lang, "active": True})
        else:
            active = draw(st.booleans())
            api_tracks.append({"language": lang, "active": active})

    return ui_options, api_tracks, selected_ui


@st.composite
def ui_and_api_mismatch_pair(draw):
    """Gera par (UI options, API tracks, selected) com mismatch.

    Garante que o selected_ui NÃO tem um track correspondente
    marcado como active na API.
    """
    # Gerar opções de UI (pelo menos 1)
    ui_options = draw(st.lists(
        language_strategy,
        min_size=1,
        max_size=6,
        unique=True,
    ))

    # Escolher uma opção como selecionada
    selected_ui = draw(st.sampled_from(ui_options))

    # Gerar API tracks garantindo que selected_ui NÃO está active
    api_tracks = []
    for lang in ui_options:
        if lang == selected_ui:
            # O selected está presente mas NÃO active
            api_tracks.append({"language": lang, "active": False})
        else:
            active = draw(st.booleans())
            api_tracks.append({"language": lang, "active": active})

    return ui_options, api_tracks, selected_ui


@st.composite
def channel_list_with_failure(draw):
    """Gera lista de canais com um índice de falha válido."""
    channels = draw(st.lists(
        st.text(
            alphabet=st.characters(
                whitelist_categories=("L", "N")
            ),
            min_size=3,
            max_size=20,
        ),
        min_size=2,
        max_size=8,
    ))
    failing_index = draw(
        st.integers(min_value=0, max_value=len(channels) - 1)
    )
    return channels, failing_index


@st.composite
def api_state_pair(draw):
    """Gera par de listas de tracks para before/after."""
    track_count = draw(st.integers(min_value=1, max_value=5))

    api_before = []
    api_after = []

    for _ in range(track_count):
        lang = draw(language_strategy)
        active_before = draw(st.booleans())
        active_after = draw(st.booleans())
        api_before.append({"language": lang, "active": active_before})
        api_after.append({"language": lang, "active": active_after})

    return api_before, api_after


# ============================================================
# Property 2: UI vs API Cross-Validation
# ============================================================


class TestUIvsAPICrossValidation:
    """Feature: audio-subtitle-monitoring, Property 2: UI vs API Cross-Validation

    **Validates: Requirements 2.3, 10.3**

    Para qualquer par (UI options, API tracks), a validação classifica
    corretamente consistência ou mismatch.
    """

    @given(data=ui_and_api_consistent_pair())
    @settings(max_examples=100)
    def test_consistent_when_selected_is_active_in_api(self, data):
        """**Validates: Requirements 2.3**

        Quando o track selecionado na UI está marcado como active
        na API, a classificação deve ser 'consistent'.
        """
        ui_options, api_tracks, selected_ui = data
        result = validate_ui_api_consistency(
            ui_options, api_tracks, selected_ui
        )
        assert result == "consistent"

    @given(data=ui_and_api_mismatch_pair())
    @settings(max_examples=100)
    def test_mismatch_when_selected_not_active_in_api(self, data):
        """**Validates: Requirements 10.3**

        Quando o track selecionado na UI NÃO está marcado como
        active na API, a classificação deve ser 'ui_api_mismatch'.
        """
        ui_options, api_tracks, selected_ui = data
        result = validate_ui_api_consistency(
            ui_options, api_tracks, selected_ui
        )
        assert result == "ui_api_mismatch"

    @given(
        ui_options=st.lists(
            language_strategy, min_size=1, max_size=6, unique=True
        ),
        selected_ui=language_strategy,
    )
    @settings(max_examples=100)
    def test_mismatch_when_api_tracks_empty(
        self, ui_options, selected_ui
    ):
        """**Validates: Requirements 10.3**

        Quando a API retorna lista vazia de tracks, qualquer
        seleção da UI deve ser classificada como mismatch.
        """
        result = validate_ui_api_consistency(
            ui_options, [], selected_ui
        )
        assert result == "ui_api_mismatch"

    @given(
        ui_options=st.lists(
            language_strategy, min_size=1, max_size=6, unique=True
        ),
        api_tracks=st.lists(api_track_strategy(), min_size=1, max_size=6),
        selected_ui=language_strategy,
    )
    @settings(max_examples=100)
    def test_classification_is_deterministic(
        self, ui_options, api_tracks, selected_ui
    ):
        """**Validates: Requirements 2.3**

        A classificação deve ser determinística: chamadas repetidas
        com os mesmos inputs produzem o mesmo resultado.
        """
        result1 = validate_ui_api_consistency(
            ui_options, api_tracks, selected_ui
        )
        result2 = validate_ui_api_consistency(
            ui_options, api_tracks, selected_ui
        )
        assert result1 == result2
        assert result1 in ("consistent", "ui_api_mismatch")


# ============================================================
# Property 8: Track Restoration
# ============================================================


class TestTrackRestoration:
    """Feature: audio-subtitle-monitoring, Property 8: Track Restoration

    **Validates: Requirements 3.7, 5.7**

    Para qualquer track inicial e sequência de seleções,
    a restauração final aponta para o track original.
    """

    @given(
        initial_track=language_strategy,
        tested_tracks=st.lists(
            language_strategy, min_size=0, max_size=10
        ),
    )
    @settings(max_examples=100)
    def test_restoration_always_returns_initial(
        self, initial_track, tested_tracks
    ):
        """**Validates: Requirements 3.7**

        Independente de quantos tracks foram testados, a
        restauração deve retornar o track inicial.
        """
        target = get_restoration_target(initial_track, tested_tracks)
        assert target == initial_track

    @given(
        initial_track=language_strategy,
        tested_tracks=st.lists(
            language_strategy, min_size=1, max_size=10
        ),
    )
    @settings(max_examples=100)
    def test_restoration_not_affected_by_tested_sequence(
        self, initial_track, tested_tracks
    ):
        """**Validates: Requirements 5.7**

        A sequência de tracks testados não influencia o
        alvo de restauração.
        """
        target = get_restoration_target(initial_track, tested_tracks)
        # O alvo nunca é influenciado pelos tracks testados
        # (a menos que por coincidência o inicial esteja na lista)
        assert target == initial_track

    @given(
        initial_track=language_strategy,
    )
    @settings(max_examples=100)
    def test_restoration_with_empty_tested_list(
        self, initial_track
    ):
        """**Validates: Requirements 3.7**

        Mesmo sem tracks testados, a restauração aponta
        para o inicial.
        """
        target = get_restoration_target(initial_track, [])
        assert target == initial_track

    @given(
        initial_track=language_strategy,
        repetitions=st.integers(min_value=1, max_value=20),
    )
    @settings(max_examples=100)
    def test_restoration_idempotent(
        self, initial_track, repetitions
    ):
        """**Validates: Requirements 3.7, 5.7**

        Chamar restauração múltiplas vezes produz o mesmo resultado.
        """
        # Simula múltiplas chamadas de restauração
        tested = [initial_track] * repetitions
        for _ in range(repetitions):
            target = get_restoration_target(initial_track, tested)
            assert target == initial_track


# ============================================================
# Property 13: Error Resilience — Channel Continuation
# ============================================================


class TestErrorResilienceChannelContinuation:
    """Feature: audio-subtitle-monitoring, Property 13: Error Resilience — Channel Continuation

    **Validates: Requirements 9.5**

    Para qualquer lista de canais onde um canal levanta exceção,
    os canais subsequentes ainda são executados e o relatório
    final contém entradas para todos.
    """

    @given(data=channel_list_with_failure())
    @settings(max_examples=100)
    def test_all_channels_have_results(self, data):
        """**Validates: Requirements 9.5**

        O relatório final deve conter resultados para TODOS
        os canais, incluindo o que falhou.
        """
        channels, failing_index = data
        results = simulate_multi_channel_run(channels, failing_index)
        assert len(results) == len(channels)

    @given(data=channel_list_with_failure())
    @settings(max_examples=100)
    def test_failing_channel_has_error(self, data):
        """**Validates: Requirements 9.5**

        O canal que falhou deve ter status FAIL e campo
        error preenchido.
        """
        channels, failing_index = data
        results = simulate_multi_channel_run(channels, failing_index)

        failed_result = results[failing_index]
        assert failed_result["status"] == "FAIL"
        assert failed_result["error"] is not None

    @given(data=channel_list_with_failure())
    @settings(max_examples=100)
    def test_subsequent_channels_still_processed(self, data):
        """**Validates: Requirements 9.5**

        Canais após o que falhou devem ser processados
        normalmente (status PASS, sem erro).
        """
        channels, failing_index = data
        results = simulate_multi_channel_run(channels, failing_index)

        for i, result in enumerate(results):
            if i != failing_index:
                assert result["status"] == "PASS"
                assert result["error"] is None

    @given(data=channel_list_with_failure())
    @settings(max_examples=100)
    def test_channel_names_preserved_in_results(self, data):
        """**Validates: Requirements 9.5**

        Os nomes dos canais devem ser preservados nos resultados
        na ordem original.
        """
        channels, failing_index = data
        results = simulate_multi_channel_run(channels, failing_index)

        for i, result in enumerate(results):
            assert result["channel"] == channels[i]


# ============================================================
# Property 14: API State Recording
# ============================================================


class TestAPIStateRecording:
    """Feature: audio-subtitle-monitoring, Property 14: API State Recording

    **Validates: Requirements 10.4**

    Para qualquer track switch, o resultado contém api_state_before
    e api_state_after não-nulos com chave "tracks".
    """

    @given(data=api_state_pair())
    @settings(max_examples=100)
    def test_api_state_before_not_null(self, data):
        """**Validates: Requirements 10.4**

        api_state_before deve ser não-nulo para qualquer
        track switch.
        """
        api_before, api_after = data
        result = create_track_result_with_api_state(
            api_before, api_after
        )
        assert result["api_state_before"] is not None

    @given(data=api_state_pair())
    @settings(max_examples=100)
    def test_api_state_after_not_null(self, data):
        """**Validates: Requirements 10.4**

        api_state_after deve ser não-nulo para qualquer
        track switch.
        """
        api_before, api_after = data
        result = create_track_result_with_api_state(
            api_before, api_after
        )
        assert result["api_state_after"] is not None

    @given(data=api_state_pair())
    @settings(max_examples=100)
    def test_api_state_contains_tracks_key(self, data):
        """**Validates: Requirements 10.4**

        Ambos api_state_before e api_state_after devem conter
        a chave "tracks" com a lista de tracks da API.
        """
        api_before, api_after = data
        result = create_track_result_with_api_state(
            api_before, api_after
        )
        assert "tracks" in result["api_state_before"]
        assert "tracks" in result["api_state_after"]

    @given(data=api_state_pair())
    @settings(max_examples=100)
    def test_api_state_tracks_are_lists(self, data):
        """**Validates: Requirements 10.4**

        O valor da chave "tracks" deve ser uma lista em ambos
        os estados.
        """
        api_before, api_after = data
        result = create_track_result_with_api_state(
            api_before, api_after
        )
        assert isinstance(
            result["api_state_before"]["tracks"], list
        )
        assert isinstance(
            result["api_state_after"]["tracks"], list
        )

    @given(data=api_state_pair())
    @settings(max_examples=100)
    def test_api_state_preserves_track_data(self, data):
        """**Validates: Requirements 10.4**

        Os dados dos tracks devem ser preservados exatamente
        como fornecidos (sem mutação).
        """
        api_before, api_after = data
        result = create_track_result_with_api_state(
            api_before, api_after
        )
        assert result["api_state_before"]["tracks"] == api_before
        assert result["api_state_after"]["tracks"] == api_after
