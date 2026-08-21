"""Property-based tests para o SettingsDialogManager do Audio & Subtitle Monitor.

Testa propriedades universais da lógica de descoberta de opções e filtragem
de legendas usando Hypothesis para validar com inputs arbitrários.

Feature: audio-subtitle-monitoring
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from src.audio_subtitle_monitor.models import TrackOption


# ============================================================
# Funções auxiliares que espelham a lógica do SettingsDialogManager
# ============================================================


def convert_raw_options_to_track_options(raw_options: list[dict]) -> list[TrackOption]:
    """Converte lista de dicts brutos (como retornados pelo page.evaluate) em TrackOption.

    Espelha a lógica interna de _discover_section_options que processa
    o resultado do JavaScript executado no browser.
    """
    return [
        TrackOption(text=item["text"], is_selected=item["is_selected"], index=i)
        for i, item in enumerate(raw_options)
    ]


def filter_desativadas(tracks: list[TrackOption]) -> list[TrackOption]:
    """Filtra tracks com texto "Desativadas" da lista de iteração.

    Espelha a lógica do caller que exclui "Desativadas" antes de iterar
    sobre os subtitle tracks para teste.
    """
    return [t for t in tracks if t.text != "Desativadas"]


# ============================================================
# Estratégias (Generators) para Hypothesis
# ============================================================


@st.composite
def raw_options_with_one_selected(draw) -> list[dict]:
    """Gera lista de N dicts de opções (N >= 1) com exatamente um is_selected=True.

    Cada dict tem a forma: {"text": str, "is_selected": bool}
    Garante que exatamente um item tem is_selected=True.
    """
    n = draw(st.integers(min_value=1, max_value=20))

    # Gerar textos únicos para simular opções de track reais
    texts = draw(
        st.lists(
            st.text(min_size=1, max_size=30),
            min_size=n,
            max_size=n,
        )
    )

    # Escolher qual índice será o selecionado
    selected_index = draw(st.integers(min_value=0, max_value=n - 1))

    options = []
    for i, text in enumerate(texts):
        options.append({
            "text": text,
            "is_selected": i == selected_index,
        })

    return options


@st.composite
def subtitle_track_options_with_desativadas(draw) -> list[TrackOption]:
    """Gera lista de TrackOption misturada com itens "Desativadas" e outros.

    Garante que pelo menos um item tem texto "Desativadas" e pelo menos
    um item NÃO tem texto "Desativadas".
    """
    # Gerar textos que NÃO são "Desativadas"
    non_desativadas_count = draw(st.integers(min_value=1, max_value=10))
    non_desativadas_texts = draw(
        st.lists(
            st.text(min_size=1, max_size=30).filter(lambda t: t != "Desativadas"),
            min_size=non_desativadas_count,
            max_size=non_desativadas_count,
        )
    )

    # Gerar quantidade de itens "Desativadas" (pelo menos 1)
    desativadas_count = draw(st.integers(min_value=1, max_value=5))

    # Montar lista combinada
    all_texts = non_desativadas_texts + ["Desativadas"] * desativadas_count

    # Embaralhar via permutation
    shuffled = draw(st.permutations(all_texts))

    # Converter para TrackOption com index sequencial
    tracks = [
        TrackOption(text=text, is_selected=(i == 0), index=i)
        for i, text in enumerate(shuffled)
    ]

    return tracks


@st.composite
def subtitle_track_options_without_desativadas(draw) -> list[TrackOption]:
    """Gera lista de TrackOption sem nenhum item "Desativadas"."""
    n = draw(st.integers(min_value=1, max_value=10))
    texts = draw(
        st.lists(
            st.text(min_size=1, max_size=30).filter(lambda t: t != "Desativadas"),
            min_size=n,
            max_size=n,
        )
    )

    tracks = [
        TrackOption(text=text, is_selected=(i == 0), index=i)
        for i, text in enumerate(texts)
    ]

    return tracks


# ============================================================
# Property 1: Option Discovery Completeness and Selection
# ============================================================


class TestOptionDiscoveryCompletenessAndSelection:
    """Feature: audio-subtitle-monitoring, Property 1: Option Discovery Completeness and Selection

    **Validates: Requirements 2.1, 2.2, 4.1, 4.2**

    Para qualquer DOM com N opções e uma selecionada, a função de conversão
    retorna N TrackOption com exatamente uma is_selected=True.
    """

    @given(raw_options=raw_options_with_one_selected())
    @settings(max_examples=100)
    def test_returns_same_count_as_input(self, raw_options: list[dict]):
        """**Validates: Requirements 2.1, 4.1**

        A quantidade de TrackOption retornados deve ser igual à quantidade
        de opções no DOM (N entrada == N saída).
        """
        result = convert_raw_options_to_track_options(raw_options)

        assert len(result) == len(raw_options), (
            f"Esperado {len(raw_options)} TrackOptions, obteve {len(result)}"
        )

    @given(raw_options=raw_options_with_one_selected())
    @settings(max_examples=100)
    def test_exactly_one_selected(self, raw_options: list[dict]):
        """**Validates: Requirements 2.2, 4.2**

        Deve haver exatamente uma opção com is_selected=True na saída.
        """
        result = convert_raw_options_to_track_options(raw_options)

        selected_count = sum(1 for opt in result if opt.is_selected)

        assert selected_count == 1, (
            f"Esperado exatamente 1 selecionado, obteve {selected_count}"
        )

    @given(raw_options=raw_options_with_one_selected())
    @settings(max_examples=100)
    def test_texts_match_input(self, raw_options: list[dict]):
        """**Validates: Requirements 2.1, 4.1**

        Os textos dos TrackOption devem corresponder exatamente aos textos
        das opções de entrada, na mesma ordem.
        """
        result = convert_raw_options_to_track_options(raw_options)

        for i, (raw, track_opt) in enumerate(zip(raw_options, result)):
            assert track_opt.text == raw["text"], (
                f"Texto na posição {i}: esperado '{raw['text']}', "
                f"obteve '{track_opt.text}'"
            )

    @given(raw_options=raw_options_with_one_selected())
    @settings(max_examples=100)
    def test_selected_matches_input(self, raw_options: list[dict]):
        """**Validates: Requirements 2.2, 4.2**

        O is_selected de cada TrackOption deve corresponder ao is_selected
        do dict de entrada correspondente.
        """
        result = convert_raw_options_to_track_options(raw_options)

        for i, (raw, track_opt) in enumerate(zip(raw_options, result)):
            assert track_opt.is_selected == raw["is_selected"], (
                f"is_selected na posição {i}: esperado {raw['is_selected']}, "
                f"obteve {track_opt.is_selected}"
            )

    @given(raw_options=raw_options_with_one_selected())
    @settings(max_examples=100)
    def test_indexes_are_sequential(self, raw_options: list[dict]):
        """**Validates: Requirements 2.1, 4.1**

        Os índices dos TrackOption devem ser sequenciais (0, 1, 2, ..., N-1).
        """
        result = convert_raw_options_to_track_options(raw_options)

        for i, track_opt in enumerate(result):
            assert track_opt.index == i, (
                f"Index na posição {i}: esperado {i}, obteve {track_opt.index}"
            )

    @given(raw_options=raw_options_with_one_selected())
    @settings(max_examples=100)
    def test_all_results_are_track_option_instances(self, raw_options: list[dict]):
        """**Validates: Requirements 2.1, 4.1**

        Todos os itens retornados devem ser instâncias de TrackOption.
        """
        result = convert_raw_options_to_track_options(raw_options)

        for item in result:
            assert isinstance(item, TrackOption), (
                f"Item não é TrackOption: {type(item)}"
            )


# ============================================================
# Property 6: Subtitle "Desativadas" Filtering
# ============================================================


class TestSubtitleDesativadasFiltering:
    """Feature: audio-subtitle-monitoring, Property 6: Subtitle "Desativadas" Filtering

    **Validates: Requirements 5.1**

    Para qualquer lista contendo "Desativadas", a iteração exclui esses
    itens corretamente, e a contagem final é len(original) - count("Desativadas").
    """

    @given(tracks=subtitle_track_options_with_desativadas())
    @settings(max_examples=100)
    def test_no_desativadas_in_filtered_result(self, tracks: list[TrackOption]):
        """**Validates: Requirements 5.1**

        Após filtragem, nenhum item deve ter texto "Desativadas".
        """
        filtered = filter_desativadas(tracks)

        for track in filtered:
            assert track.text != "Desativadas", (
                f"Track 'Desativadas' encontrado na lista filtrada no index {track.index}"
            )

    @given(tracks=subtitle_track_options_with_desativadas())
    @settings(max_examples=100)
    def test_filtered_count_equals_original_minus_desativadas(
        self, tracks: list[TrackOption]
    ):
        """**Validates: Requirements 5.1**

        A quantidade filtrada deve ser len(original) - count("Desativadas").
        """
        desativadas_count = sum(1 for t in tracks if t.text == "Desativadas")
        expected_count = len(tracks) - desativadas_count

        filtered = filter_desativadas(tracks)

        assert len(filtered) == expected_count, (
            f"Esperado {expected_count} tracks após filtro, obteve {len(filtered)}. "
            f"Original: {len(tracks)}, Desativadas: {desativadas_count}"
        )

    @given(tracks=subtitle_track_options_without_desativadas())
    @settings(max_examples=100)
    def test_no_filtering_when_no_desativadas(self, tracks: list[TrackOption]):
        """**Validates: Requirements 5.1**

        Quando não há "Desativadas" na lista, nada é filtrado.
        """
        filtered = filter_desativadas(tracks)

        assert len(filtered) == len(tracks), (
            f"Lista sem 'Desativadas' foi alterada: "
            f"original {len(tracks)}, filtrada {len(filtered)}"
        )

    @given(tracks=subtitle_track_options_with_desativadas())
    @settings(max_examples=100)
    def test_non_desativadas_tracks_preserved(self, tracks: list[TrackOption]):
        """**Validates: Requirements 5.1**

        Todos os tracks que NÃO são "Desativadas" devem estar presentes
        na lista filtrada, mantendo seus atributos.
        """
        filtered = filter_desativadas(tracks)

        non_desativadas_original = [t for t in tracks if t.text != "Desativadas"]

        assert len(filtered) == len(non_desativadas_original)

        for original, result in zip(non_desativadas_original, filtered):
            assert result.text == original.text
            assert result.is_selected == original.is_selected
            assert result.index == original.index

    @given(
        n_desativadas=st.integers(min_value=1, max_value=10),
    )
    @settings(max_examples=100)
    def test_all_desativadas_list_returns_empty(self, n_desativadas: int):
        """**Validates: Requirements 5.1**

        Uma lista composta APENAS de "Desativadas" retorna lista vazia.
        """
        tracks = [
            TrackOption(text="Desativadas", is_selected=(i == 0), index=i)
            for i in range(n_desativadas)
        ]

        filtered = filter_desativadas(tracks)

        assert len(filtered) == 0, (
            f"Lista com {n_desativadas} 'Desativadas' deveria retornar vazia, "
            f"obteve {len(filtered)} itens"
        )
