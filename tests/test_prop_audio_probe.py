# Feature: player-discovery, Property 10: Classificação de status de áudio por RMS
"""Property-based test para classificação de status de áudio por RMS.

Valida que o AudioProbe classifica corretamente o status de áudio com base
nas amostras RMS ao longo do tempo:
- NO_AUDIO: RMS < 0.01 por mais de 10s consecutivos com muted=false
- AUDIO_LOW: RMS entre 0.01 e 0.05 por mais de 10s consecutivos
- OK: caso contrário

Com coleta a cada 2s, 10s = 5 amostras mínimas para classificação.

**Validates: Requirements 6.2, 6.3**
"""
from hypothesis import given, settings
from hypothesis import strategies as st

from src.player_discovery.models.enums import AudioStatus
from src.player_discovery.probes.audio_probe import (
    AudioProbe,
    RMS_AUDIO_LOW_UPPER,
    RMS_NO_AUDIO_THRESHOLD,
)


# Strategies reutilizáveis

# RMS abaixo do limiar de NO_AUDIO (< 0.01)
rms_no_audio = st.floats(min_value=0.0, max_value=0.0099)

# RMS na faixa AUDIO_LOW [0.01, 0.05)
rms_audio_low = st.floats(min_value=0.01, max_value=0.0499)

# RMS acima do limiar de AUDIO_LOW (>= 0.05), indicando áudio OK
rms_ok = st.floats(min_value=0.05, max_value=1.0)

# Número de amostras suficientes (5 ou mais para cobrir 10s)
sufficient_sample_count = st.integers(min_value=5, max_value=20)

# Número de amostras insuficientes (menos de 5)
insufficient_sample_count = st.integers(min_value=1, max_value=4)


class TestAudioRMSClassification:
    """Testes de propriedade para classificação de áudio por RMS."""

    @settings(max_examples=100)
    @given(
        samples=st.lists(
            rms_no_audio,
            min_size=5,
            max_size=20,
        ),
    )
    def test_all_samples_below_threshold_muted_false_is_no_audio(
        self,
        samples: list[float],
    ) -> None:
        """Amostras todas < 0.01 com muted=False → NO_AUDIO.

        Para qualquer sequência de 5+ amostras RMS todas abaixo de 0.01
        com muted=False, o status DEVE ser NO_AUDIO.

        **Validates: Requirements 6.2**
        """
        probe = AudioProbe()
        result = probe.classify_status(samples, muted=False)

        assert result == AudioStatus.NO_AUDIO, (
            f"Amostras todas < 0.01 ({samples[-5:]}) com muted=False "
            f"deveria ser NO_AUDIO, mas obteve {result.value}"
        )

    @settings(max_examples=100)
    @given(
        samples=st.lists(
            rms_audio_low,
            min_size=5,
            max_size=20,
        ),
    )
    def test_all_samples_in_low_range_is_audio_low(
        self,
        samples: list[float],
    ) -> None:
        """Amostras todas em [0.01, 0.05) → AUDIO_LOW.

        Para qualquer sequência de 5+ amostras RMS todas entre 0.01 e 0.05
        (inclusive/exclusive), o status DEVE ser AUDIO_LOW.

        **Validates: Requirements 6.3**
        """
        probe = AudioProbe()
        result = probe.classify_status(samples, muted=False)

        assert result == AudioStatus.AUDIO_LOW, (
            f"Amostras todas em [0.01, 0.05) ({samples[-5:]}) "
            f"deveria ser AUDIO_LOW, mas obteve {result.value}"
        )

    @settings(max_examples=100)
    @given(
        prefix=st.lists(
            st.floats(min_value=0.0, max_value=1.0),
            min_size=0,
            max_size=10,
        ),
        ok_sample=rms_ok,
        suffix=st.lists(
            st.floats(min_value=0.0, max_value=1.0),
            min_size=0,
            max_size=4,
        ),
    )
    def test_any_sample_above_threshold_in_last_5_is_ok(
        self,
        prefix: list[float],
        ok_sample: float,
        suffix: list[float],
    ) -> None:
        """Qualquer amostra >= 0.05 nas últimas 5 → OK.

        Se pelo menos uma das últimas 5 amostras tem RMS >= 0.05,
        o status DEVE ser OK (nem NO_AUDIO nem AUDIO_LOW).

        **Validates: Requirements 6.2, 6.3**
        """
        # Construir amostras de modo que ok_sample esteja nas últimas 5
        # Garantir pelo menos 5 amostras totais com ok_sample nas últimas 5
        tail_size = len(suffix)
        # ok_sample + suffix formam parte do tail (até 5 posições)
        tail = [ok_sample] + suffix  # 1 a 5 amostras
        # Preencher o prefix para garantir 5+ amostras totais
        needed = max(0, 5 - len(tail))
        # Adicionar amostras extras no prefix para chegar a 5+ total
        padding = [0.005] * needed  # Valores baixos no início
        samples = prefix + padding + tail

        # Garantir pelo menos 5 amostras
        if len(samples) < 5:
            samples = [0.005] * (5 - len(samples)) + samples

        # Verificar que ok_sample está de fato nas últimas 5
        last_5 = samples[-5:]
        if ok_sample not in last_5:
            # Forçar ok_sample na última posição das últimas 5
            samples = samples[:-1] + [ok_sample]
            if len(samples) < 5:
                samples = [0.005] * (5 - len(samples)) + samples

        probe = AudioProbe()
        result = probe.classify_status(samples, muted=False)

        assert result == AudioStatus.OK, (
            f"Com amostra >= 0.05 ({ok_sample}) nas últimas 5, "
            f"status deveria ser OK, mas obteve {result.value}. "
            f"Últimas 5: {samples[-5:]}"
        )

    @settings(max_examples=100)
    @given(
        samples=st.lists(
            rms_no_audio,
            min_size=5,
            max_size=20,
        ),
    )
    def test_all_samples_below_threshold_muted_true_is_ok(
        self,
        samples: list[float],
    ) -> None:
        """Amostras todas < 0.01 com muted=True → OK (não é problema).

        Quando o player está em mute, RMS baixo é esperado.
        O status NÃO deve ser NO_AUDIO.

        **Validates: Requirements 6.2**
        """
        probe = AudioProbe()
        result = probe.classify_status(samples, muted=True)

        # Com muted=True, não classifica como NO_AUDIO
        assert result != AudioStatus.NO_AUDIO, (
            f"Com muted=True, status NÃO deveria ser NO_AUDIO, "
            f"mas obteve {result.value}"
        )

    @settings(max_examples=100)
    @given(
        samples=st.lists(
            st.floats(min_value=0.0, max_value=1.0),
            min_size=1,
            max_size=4,
        ),
    )
    def test_insufficient_samples_is_ok(
        self,
        samples: list[float],
    ) -> None:
        """Menos de 5 amostras → OK (dados insuficientes para classificar).

        Sem 10 segundos de dados (5 amostras a cada 2s), o sistema
        não deve classificar como problema.

        **Validates: Requirements 6.2, 6.3**
        """
        probe = AudioProbe()
        result = probe.classify_status(samples, muted=False)

        assert result == AudioStatus.OK, (
            f"Com apenas {len(samples)} amostras (< 5), "
            f"status deveria ser OK, mas obteve {result.value}"
        )
