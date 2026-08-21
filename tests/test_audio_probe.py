"""Testes unitários para AudioProbe.

Testa:
- Classificação de status de áudio (NO_AUDIO, AUDIO_LOW, OK)
- Cálculo de silence_duration
- Reset de estado
- Coleta de telemetria (com mock de page)
- Teste funcional mute/unmute (com mock de page)

Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.player_discovery.models.capability import (
    Capability,
    CapabilityMapData,
    InteractionStrategy,
    PlayerInfo,
)
from src.player_discovery.models.capability_map import CapabilityMap
from src.player_discovery.models.enums import (
    AudioStatus,
    FunctionalTestStatus,
    InteractionLevel,
)
from src.player_discovery.models.telemetry import AudioTelemetry
from src.player_discovery.probes.audio_probe import (
    AudioProbe,
    RMS_AUDIO_LOW_UPPER,
    RMS_NO_AUDIO_THRESHOLD,
    SILENCE_DURATION_THRESHOLD_S,
)


# --- Fixtures ---


@pytest.fixture
def audio_probe():
    """Cria uma instância limpa do AudioProbe."""
    return AudioProbe()


@pytest.fixture
def capability_map_with_audio():
    """Cria um CapabilityMap com capabilities de áudio disponíveis."""
    data = CapabilityMapData(
        player_info=PlayerInfo(
            library="test-player",
            version="1.0",
            video_elements=["video"],
            discovered_at="2024-01-01T00:00:00Z",
        ),
        capabilities={
            "play": Capability(
                name="play",
                available=True,
                confidence=0.9,
                evidence=["test"],
                interaction_strategy=InteractionLevel.PLAYER_API,
                strategies=[],
            ),
            "pause": Capability(
                name="pause",
                available=True,
                confidence=0.9,
                evidence=["test"],
                interaction_strategy=InteractionLevel.PLAYER_API,
                strategies=[],
            ),
            "mute": Capability(
                name="mute",
                available=True,
                confidence=0.9,
                evidence=["aria-label='Mute'"],
                interaction_strategy=InteractionLevel.PLAYER_API,
                strategies=[
                    InteractionStrategy(
                        level=InteractionLevel.PLAYER_API,
                        type="player_api",
                        details={"js_code": "document.querySelector('video').muted = true"},
                    ),
                ],
            ),
            "unmute": Capability(
                name="unmute",
                available=True,
                confidence=0.9,
                evidence=["aria-label='Unmute'"],
                interaction_strategy=InteractionLevel.PLAYER_API,
                strategies=[
                    InteractionStrategy(
                        level=InteractionLevel.PLAYER_API,
                        type="player_api",
                        details={"js_code": "document.querySelector('video').muted = false"},
                    ),
                ],
            ),
            "audio_selection": Capability(
                name="audio_selection",
                available=True,
                confidence=0.85,
                evidence=["audioTracks API disponível"],
                interaction_strategy=InteractionLevel.PLAYER_API,
                strategies=[
                    InteractionStrategy(
                        level=InteractionLevel.PLAYER_API,
                        type="player_api",
                        details={"js_code": "openAudioMenu()"},
                    ),
                ],
            ),
            "subtitle_selection": Capability(
                name="subtitle_selection",
                available=False,
                confidence=0.3,
                evidence=[],
                interaction_strategy=InteractionLevel.SEMANTIC_DOM,
                strategies=[],
            ),
            "quality_selection": Capability(
                name="quality_selection",
                available=False,
                confidence=0.3,
                evidence=[],
                interaction_strategy=InteractionLevel.SEMANTIC_DOM,
                strategies=[],
            ),
            "fullscreen": Capability(
                name="fullscreen",
                available=True,
                confidence=0.8,
                evidence=["test"],
                interaction_strategy=InteractionLevel.SEMANTIC_DOM,
                strategies=[],
            ),
            "settings": Capability(
                name="settings",
                available=False,
                confidence=0.2,
                evidence=[],
                interaction_strategy=InteractionLevel.SEMANTIC_DOM,
                strategies=[],
            ),
        },
    )
    return CapabilityMap(data)


@pytest.fixture
def capability_map_no_audio():
    """CapabilityMap sem capabilities de áudio disponíveis."""
    data = CapabilityMapData(
        player_info=PlayerInfo(
            library="test-player",
            version="1.0",
            video_elements=["video"],
            discovered_at="2024-01-01T00:00:00Z",
        ),
        capabilities={
            "play": Capability(
                name="play", available=True, confidence=0.9,
                evidence=["test"],
                interaction_strategy=InteractionLevel.PLAYER_API,
            ),
            "pause": Capability(
                name="pause", available=True, confidence=0.9,
                evidence=["test"],
                interaction_strategy=InteractionLevel.PLAYER_API,
            ),
            "mute": Capability(
                name="mute", available=False, confidence=0.4,
                evidence=[],
                interaction_strategy=InteractionLevel.SEMANTIC_DOM,
            ),
            "unmute": Capability(
                name="unmute", available=False, confidence=0.4,
                evidence=[],
                interaction_strategy=InteractionLevel.SEMANTIC_DOM,
            ),
            "audio_selection": Capability(
                name="audio_selection", available=False, confidence=0.3,
                evidence=[],
                interaction_strategy=InteractionLevel.SEMANTIC_DOM,
            ),
            "subtitle_selection": Capability(
                name="subtitle_selection", available=False,
                confidence=0.3, evidence=[],
                interaction_strategy=InteractionLevel.SEMANTIC_DOM,
            ),
            "quality_selection": Capability(
                name="quality_selection", available=False,
                confidence=0.3, evidence=[],
                interaction_strategy=InteractionLevel.SEMANTIC_DOM,
            ),
            "fullscreen": Capability(
                name="fullscreen", available=False, confidence=0.3,
                evidence=[],
                interaction_strategy=InteractionLevel.SEMANTIC_DOM,
            ),
            "settings": Capability(
                name="settings", available=False, confidence=0.2,
                evidence=[],
                interaction_strategy=InteractionLevel.SEMANTIC_DOM,
            ),
        },
    )
    return CapabilityMap(data)


# --- Testes de classify_status ---


class TestClassifyStatus:
    """Testes para classificação de status de áudio."""

    def test_ok_when_no_samples(self, audio_probe):
        """Status OK quando não há amostras."""
        result = audio_probe.classify_status([], False)
        assert result == AudioStatus.OK

    def test_ok_when_insufficient_samples(self, audio_probe):
        """Status OK quando há menos amostras que o mínimo para 10s."""
        # Com intervalo de 2s, precisa de 5 amostras para 10s
        samples = [0.005, 0.005, 0.005, 0.005]  # Apenas 4
        result = audio_probe.classify_status(samples, False)
        assert result == AudioStatus.OK

    def test_no_audio_when_rms_below_threshold_for_10s(self, audio_probe):
        """NO_AUDIO quando RMS < 0.01 por 10s+ e muted=false."""
        # 5 amostras (cada 2s = 10s total) abaixo do limiar
        samples = [0.005, 0.003, 0.001, 0.008, 0.009]
        result = audio_probe.classify_status(samples, False)
        assert result == AudioStatus.NO_AUDIO

    def test_ok_when_rms_below_threshold_but_muted(self, audio_probe):
        """OK quando RMS < 0.01 por 10s MAS muted=true."""
        samples = [0.005, 0.003, 0.001, 0.008, 0.009]
        result = audio_probe.classify_status(samples, True)
        # Muted=True não classifica como NO_AUDIO
        assert result == AudioStatus.OK

    def test_audio_low_when_rms_between_thresholds_for_10s(
        self, audio_probe
    ):
        """AUDIO_LOW quando RMS entre 0.01 e 0.05 por 10s+."""
        samples = [0.02, 0.03, 0.015, 0.04, 0.035]
        result = audio_probe.classify_status(samples, False)
        assert result == AudioStatus.AUDIO_LOW

    def test_ok_when_rms_normal(self, audio_probe):
        """OK quando RMS está acima de 0.05."""
        samples = [0.2, 0.3, 0.15, 0.4, 0.35]
        result = audio_probe.classify_status(samples, False)
        assert result == AudioStatus.OK

    def test_ok_when_mixed_samples(self, audio_probe):
        """OK quando amostras variam entre normal e baixo."""
        samples = [0.001, 0.3, 0.005, 0.2, 0.1]
        result = audio_probe.classify_status(samples, False)
        assert result == AudioStatus.OK

    def test_no_audio_takes_recent_samples(self, audio_probe):
        """Classificação usa apenas as últimas 5 amostras."""
        # Primeiras amostras normais, últimas 5 silenciosas
        samples = [0.5, 0.3, 0.2, 0.005, 0.003, 0.001, 0.008, 0.009]
        result = audio_probe.classify_status(samples, False)
        assert result == AudioStatus.NO_AUDIO

    def test_audio_low_boundary_rms_equals_0_01(self, audio_probe):
        """AUDIO_LOW quando RMS exatamente 0.01 (limite inferior)."""
        samples = [0.01, 0.02, 0.03, 0.04, 0.049]
        result = audio_probe.classify_status(samples, False)
        assert result == AudioStatus.AUDIO_LOW

    def test_ok_when_rms_equals_0_05(self, audio_probe):
        """OK quando RMS = 0.05 (limite superior de AUDIO_LOW)."""
        # 0.05 não está no range [0.01, 0.05) para AUDIO_LOW
        samples = [0.01, 0.02, 0.03, 0.04, 0.05]
        result = audio_probe.classify_status(samples, False)
        assert result == AudioStatus.OK


# --- Testes de silence_duration ---


class TestSilenceDuration:
    """Testes para cálculo de silence_duration."""

    def test_silence_starts_counting(self, audio_probe):
        """Silêncio começa a contar quando RMS < 0.01 e não muted."""
        now = time.time()
        duration = audio_probe._calculate_silence_duration(
            0.005, False, now
        )
        assert duration == 0.0  # Primeira medição, acabou de começar

    def test_silence_accumulates(self, audio_probe):
        """Silêncio acumula ao longo do tempo."""
        now = time.time()
        # Primeira medição: inicia o contador
        audio_probe._calculate_silence_duration(0.005, False, now)
        # Segunda medição: 2 segundos depois
        duration = audio_probe._calculate_silence_duration(
            0.003, False, now + 2.0
        )
        assert duration == pytest.approx(2.0, abs=0.01)

    def test_silence_resets_on_audio(self, audio_probe):
        """Silêncio reseta quando RMS volta ao normal."""
        now = time.time()
        audio_probe._calculate_silence_duration(0.005, False, now)
        # Audio volta
        duration = audio_probe._calculate_silence_duration(
            0.1, False, now + 2.0
        )
        assert duration == 0.0

    def test_silence_resets_on_mute(self, audio_probe):
        """Silêncio reseta quando player é mutado."""
        now = time.time()
        audio_probe._calculate_silence_duration(0.005, False, now)
        # Mutado — não é silêncio real
        duration = audio_probe._calculate_silence_duration(
            0.005, True, now + 2.0
        )
        assert duration == 0.0

    def test_no_silence_when_rms_none(self, audio_probe):
        """Sem silêncio quando RMS é None (API indisponível)."""
        now = time.time()
        duration = audio_probe._calculate_silence_duration(
            None, False, now
        )
        assert duration == 0.0


# --- Testes de collect ---


class TestCollect:
    """Testes para o método collect()."""

    @pytest.mark.asyncio
    async def test_collect_returns_telemetry(
        self, audio_probe, capability_map_with_audio
    ):
        """Collect retorna AudioTelemetry com dados válidos."""
        page = AsyncMock()
        page.evaluate = AsyncMock(side_effect=[
            True,  # _JS_INIT_AUDIO_CONTEXT
            {  # _JS_COLLECT_AUDIO
                "rms": 0.15,
                "peak": 0.4,
                "muted": False,
                "volume": 1.0,
                "tracks_available": ["Português", "English"],
            },
        ])

        result = await audio_probe.collect(page, capability_map_with_audio)

        assert isinstance(result, AudioTelemetry)
        assert result.rms == 0.15
        assert result.peak == 0.4
        assert result.muted is False
        assert result.status == AudioStatus.OK
        assert "Português" in result.tracks_available

    @pytest.mark.asyncio
    async def test_collect_handles_no_video_element(
        self, audio_probe, capability_map_with_audio
    ):
        """Collect retorna telemetria vazia quando vídeo não encontrado."""
        page = AsyncMock()
        page.evaluate = AsyncMock(side_effect=[
            True,  # _JS_INIT_AUDIO_CONTEXT
            None,  # _JS_COLLECT_AUDIO — sem vídeo
        ])

        result = await audio_probe.collect(page, capability_map_with_audio)

        assert isinstance(result, AudioTelemetry)
        assert result.rms is None
        assert result.status == AudioStatus.OK

    @pytest.mark.asyncio
    async def test_collect_handles_evaluate_error(
        self, audio_probe, capability_map_with_audio
    ):
        """Collect lida graciosamente com erros de page.evaluate()."""
        page = AsyncMock()
        page.evaluate = AsyncMock(side_effect=[
            True,  # _JS_INIT_AUDIO_CONTEXT
            Exception("Tab crashed"),  # _JS_COLLECT_AUDIO
        ])

        result = await audio_probe.collect(page, capability_map_with_audio)

        assert isinstance(result, AudioTelemetry)
        assert result.status == AudioStatus.OK


# --- Testes de run_functional_test ---


class TestRunFunctionalTest:
    """Testes para testes funcionais de áudio."""

    @pytest.mark.asyncio
    async def test_skipped_when_no_audio_capabilities(
        self, audio_probe, capability_map_no_audio
    ):
        """Retorna SKIPPED quando capabilities de áudio não disponíveis."""
        page = AsyncMock()

        result = await audio_probe.run_functional_test(
            page, capability_map_no_audio
        )

        assert result.status == FunctionalTestStatus.SKIPPED
        assert result.capability == "audio"

    @pytest.mark.asyncio
    async def test_mute_unmute_pass(
        self, audio_probe, capability_map_with_audio
    ):
        """Teste mute/unmute PASS quando tudo funciona."""
        page = AsyncMock()
        page.wait_for_timeout = AsyncMock()

        # Simular: mute OK, verificar muted=true, unmute OK, verificar muted=false
        page.evaluate = AsyncMock(side_effect=[
            # mute (via InteractionManager._execute_api)
            None,
            # verificar muted=true (_JS_CHECK_MUTED)
            {"muted": True, "volume": 1.0},
            # unmute (via InteractionManager._execute_api)
            None,
            # verificar muted=false (_JS_CHECK_MUTED)
            {"muted": False, "volume": 1.0},
        ])

        result = await audio_probe.run_functional_test(
            page, capability_map_with_audio
        )

        assert result.status == FunctionalTestStatus.PASS
        assert result.capability == "mute_unmute"

    @pytest.mark.asyncio
    async def test_mute_fail_when_still_unmuted(
        self, audio_probe, capability_map_with_audio
    ):
        """Teste FAIL quando player não fica muted após ação."""
        page = AsyncMock()
        page.wait_for_timeout = AsyncMock()

        page.evaluate = AsyncMock(side_effect=[
            # mute (via InteractionManager)
            None,
            # verificar — ainda não está muted
            {"muted": False, "volume": 1.0},
        ])

        result = await audio_probe.run_functional_test(
            page, capability_map_with_audio
        )

        assert result.status == FunctionalTestStatus.FAIL
        assert "muted" in result.actual_result.lower()


# --- Testes de reset ---


class TestReset:
    """Testes para reset de estado do AudioProbe."""

    def test_reset_clears_all_state(self, audio_probe):
        """Reset limpa todo o estado interno."""
        # Simular estado acumulado
        audio_probe._rms_samples = [0.1, 0.2, 0.3]
        audio_probe._sample_timestamps = [1.0, 2.0, 3.0]
        audio_probe._silence_start = time.time()
        audio_probe._audio_initialized = True

        audio_probe.reset()

        assert audio_probe._rms_samples == []
        assert audio_probe._sample_timestamps == []
        assert audio_probe._silence_start is None
        assert audio_probe._audio_initialized is False
