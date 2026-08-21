"""Property-Based Tests — Pipeline de escalação determinística.

Feature: player-discovery, Property 22: Pipeline de escalação determinística

Para qualquer estado de telemetria de um canal:
- Se saudável (currentTime avançando, buffer adequado, áudio presente,
  sem erros) → classificar como HEALTHY sem capturar frames adicionais
  nem acionar OpenCV/Bedrock.
- Se suspeito → capturar frames e acionar OpenCV.
- Se OpenCV NÃO confirma anomalia → NÃO acionar Bedrock.

**Validates: Requirements 14.1, 14.2, 14.4**
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Optional
from unittest.mock import AsyncMock, MagicMock

from hypothesis import given, settings, strategies as st

from src.player_discovery.models import (
    AudioTelemetry,
    BufferTelemetry,
    CapabilityMap,
    CapabilityMapData,
    ChannelHealthStatus,
    ChannelReport,
    Capability,
    HealthScores,
    InteractionLevel,
    PlayerInfo,
    SubtitleTelemetry,
    VideoTelemetry,
)
from src.player_discovery.models.enums import AudioStatus, BufferStatus
from src.player_discovery.monitoring.channel_monitor import ChannelMonitor


# --- Helpers ---


def _build_minimal_capability_map() -> CapabilityMap:
    """Cria um CapabilityMap mínimo válido para os testes."""
    caps = {}
    for name in [
        "play", "pause", "mute", "unmute",
        "audio_selection", "subtitle_selection",
        "quality_selection", "fullscreen", "settings",
    ]:
        caps[name] = Capability(
            name=name,
            available=True,
            confidence=0.95,
            evidence=["teste"],
            interaction_strategy=InteractionLevel.PLAYER_API,
            strategies=[],
        )

    data = CapabilityMapData(
        player_info=PlayerInfo(
            library="test-player",
            version="1.0.0",
            video_elements=["video"],
            discovered_at="2024-01-01T00:00:00.000Z",
        ),
        capabilities=caps,
        discovery_duration_ms=1000,
        version_hash="test_hash",
        valid=True,
    )
    return CapabilityMap(data)


def _build_healthy_report(channel_url: str = "http://test/ch1") -> ChannelReport:
    """Cria um ChannelReport base para uso nos testes."""
    return ChannelReport(
        channel_id="ch1",
        channel_url=channel_url,
        status=ChannelHealthStatus.HEALTHY,
        health_scores=HealthScores(
            video_health=90.0,
            audio_health=90.0,
            functional_health=90.0,
        ),
        video_telemetry=VideoTelemetry(
            current_time=10.0,
            duration=0.0,
            ready_state=4,
            paused=False,
            playing=True,
            ended=False,
            seeking=False,
            playback_rate=1.0,
            network_state=2,
            buffered_seconds=15.0,
            video_width=1920,
            video_height=1080,
        ),
        audio_telemetry=AudioTelemetry(
            rms=0.3, peak=0.5, silence_duration=0.0,
            muted=False, status=AudioStatus.OK,
        ),
        subtitle_telemetry=SubtitleTelemetry(),
        buffer_telemetry=BufferTelemetry(
            buffer_ahead=10.0, status=BufferStatus.OK,
        ),
        escalated_to_opencv=False,
        escalated_to_bedrock=False,
    )


@dataclass
class FakeFrame:
    """Frame falso para simular captura."""

    data: Optional[bytes] = b"\x00" * 100
    is_valid: bool = True


# --- Estratégias de geração ---

# Telemetria saudável: currentTime avançando, buffer OK, áudio presente, sem erros
healthy_video_st = st.builds(
    VideoTelemetry,
    current_time=st.floats(
        min_value=1.0, max_value=10000.0,
        allow_nan=False, allow_infinity=False,
    ),
    duration=st.just(0.0),
    ready_state=st.just(4),
    paused=st.just(False),
    playing=st.just(True),
    ended=st.just(False),
    seeking=st.just(False),
    playback_rate=st.just(1.0),
    network_state=st.just(2),
    buffered_seconds=st.floats(
        min_value=5.0, max_value=60.0,
        allow_nan=False, allow_infinity=False,
    ),
    video_width=st.integers(min_value=640, max_value=3840),
    video_height=st.integers(min_value=480, max_value=2160),
    error=st.just(None),
)

healthy_audio_st = st.builds(
    AudioTelemetry,
    rms=st.floats(
        min_value=0.06, max_value=1.0,
        allow_nan=False, allow_infinity=False,
    ),
    peak=st.floats(
        min_value=0.1, max_value=1.0,
        allow_nan=False, allow_infinity=False,
    ),
    silence_duration=st.floats(
        min_value=0.0, max_value=9.0,
        allow_nan=False, allow_infinity=False,
    ),
    muted=st.just(False),
    status=st.just(AudioStatus.OK),
    tracks_available=st.just([]),
)

healthy_buffer_st = st.builds(
    BufferTelemetry,
    buffered_start=st.just(0.0),
    buffered_end=st.floats(
        min_value=10.0, max_value=60.0,
        allow_nan=False, allow_infinity=False,
    ),
    buffer_ahead=st.floats(
        min_value=3.0, max_value=60.0,
        allow_nan=False, allow_infinity=False,
    ),
    waiting_count=st.integers(min_value=0, max_value=2),
    waiting_total_ms=st.just(0.0),
    longest_wait_ms=st.just(0.0),
    time_since_last_wait=st.just(None),
    status=st.just(BufferStatus.OK),
)

# Telemetria suspeita: AUDIO_LOW ou BUFFER_LOW
suspect_audio_st = st.builds(
    AudioTelemetry,
    rms=st.floats(
        min_value=0.01, max_value=0.05,
        allow_nan=False, allow_infinity=False,
    ),
    peak=st.floats(
        min_value=0.01, max_value=0.1,
        allow_nan=False, allow_infinity=False,
    ),
    silence_duration=st.floats(
        min_value=10.0, max_value=60.0,
        allow_nan=False, allow_infinity=False,
    ),
    muted=st.just(False),
    status=st.just(AudioStatus.AUDIO_LOW),
    tracks_available=st.just([]),
)

suspect_buffer_st = st.builds(
    BufferTelemetry,
    buffered_start=st.just(0.0),
    buffered_end=st.floats(
        min_value=1.0, max_value=5.0,
        allow_nan=False, allow_infinity=False,
    ),
    buffer_ahead=st.floats(
        min_value=0.1, max_value=1.9,
        allow_nan=False, allow_infinity=False,
    ),
    waiting_count=st.integers(min_value=0, max_value=3),
    waiting_total_ms=st.just(500.0),
    longest_wait_ms=st.just(500.0),
    time_since_last_wait=st.just(None),
    status=st.just(BufferStatus.BUFFER_LOW),
)


# --- Property Tests ---


class TestEscalacaoDeterministica:
    """Property 22: Pipeline de escalação determinística."""

    @settings(max_examples=100)
    @given(
        video=healthy_video_st,
        audio=healthy_audio_st,
        buffer=healthy_buffer_st,
    )
    def test_healthy_channel_no_opencv_no_bedrock(
        self,
        video: VideoTelemetry,
        audio: AudioTelemetry,
        buffer: BufferTelemetry,
    ) -> None:
        """Canal HEALTHY não deve acionar OpenCV nem Bedrock.

        Para qualquer telemetria saudável (currentTime avançando,
        buffer adequado, áudio presente, sem erros), o canal deve
        ser classificado como HEALTHY e a escalação NÃO deve
        invocar OpenCV nem Bedrock.

        **Validates: Requirements 14.1, 14.2**
        """
        # Arrange
        cap_map = _build_minimal_capability_map()
        page_mock = MagicMock()

        # Mocks de escalação
        frame_capturer = AsyncMock()
        frame_capturer.capture_frame = AsyncMock(
            return_value=FakeFrame()
        )
        frame_capturer.capture_sequence = AsyncMock(
            return_value=[FakeFrame()]
        )

        opencv_mock = MagicMock()
        bedrock_mock = AsyncMock()

        monitor = ChannelMonitor(
            capability_map=cap_map,
            page=page_mock,
            frame_capturer=frame_capturer,
            opencv_analyzer=opencv_mock,
            bedrock_client=bedrock_mock,
        )

        # Act: classificar a telemetria
        status = monitor._classify_channel_status(video, audio, buffer)

        # Verificar que é HEALTHY
        assert status == ChannelHealthStatus.HEALTHY, (
            f"Telemetria saudável classificada como {status.value} "
            f"em vez de HEALTHY. video.error={video.error}, "
            f"audio.status={audio.status}, "
            f"buffer.status={buffer.status}"
        )

        # Act: executar escalação
        report = _build_healthy_report()
        report.status = status

        loop = asyncio.new_event_loop()
        try:
            updated_report = loop.run_until_complete(
                monitor._escalate_channel(status, report)
            )
        finally:
            loop.close()

        # Assert: NÃO deve ter escalado para OpenCV nem Bedrock
        assert updated_report.escalated_to_opencv is False, (
            "Canal HEALTHY NÃO deve escalar para OpenCV, "
            "mas escalated_to_opencv=True."
        )
        assert updated_report.escalated_to_bedrock is False, (
            "Canal HEALTHY NÃO deve escalar para Bedrock, "
            "mas escalated_to_bedrock=True."
        )

        # Assert: OpenCV e Bedrock NÃO foram chamados
        opencv_mock.detect_black_screen.assert_not_called()
        opencv_mock.detect_freeze.assert_not_called()
        bedrock_mock.diagnose_frame.assert_not_called()

    @settings(max_examples=100)
    @given(
        audio=suspect_audio_st,
        buffer=healthy_buffer_st,
    )
    def test_suspect_channel_invokes_opencv(
        self,
        audio: AudioTelemetry,
        buffer: BufferTelemetry,
    ) -> None:
        """Canal SUSPECT deve capturar frames e acionar OpenCV.

        Quando a telemetria indica suspeita (AUDIO_LOW), o canal
        é classificado como SUSPECT e a escalação DEVE capturar
        frames adicionais e acionar OpenCV.

        **Validates: Requirements 14.2**
        """
        # Arrange: vídeo saudável mas áudio AUDIO_LOW → SUSPECT
        video = VideoTelemetry(
            current_time=10.0,
            duration=0.0,
            ready_state=4,
            paused=False,
            playing=True,
            ended=False,
            seeking=False,
            playback_rate=1.0,
            network_state=2,
            buffered_seconds=15.0,
            video_width=1920,
            video_height=1080,
            error=None,
        )

        cap_map = _build_minimal_capability_map()
        page_mock = MagicMock()

        frames = [FakeFrame(), FakeFrame(), FakeFrame()]
        frame_capturer = AsyncMock()
        frame_capturer.capture_frame = AsyncMock(
            return_value=FakeFrame()
        )
        frame_capturer.capture_sequence = AsyncMock(
            return_value=frames
        )

        # OpenCV NÃO confirma anomalia neste cenário
        opencv_mock = MagicMock()
        opencv_mock.detect_black_screen = MagicMock(
            return_value=MagicMock(is_black_screen=False)
        )
        opencv_mock.detect_freeze = MagicMock(
            return_value=MagicMock(
                classification=MagicMock(value="NORMAL")
            )
        )

        bedrock_mock = AsyncMock()

        monitor = ChannelMonitor(
            capability_map=cap_map,
            page=page_mock,
            frame_capturer=frame_capturer,
            opencv_analyzer=opencv_mock,
            bedrock_client=bedrock_mock,
        )

        # Act: classificar
        status = monitor._classify_channel_status(video, audio, buffer)
        assert status == ChannelHealthStatus.SUSPECT, (
            f"Esperado SUSPECT, obtido {status.value}."
        )

        # Act: executar escalação
        report = _build_healthy_report()
        report.status = status

        loop = asyncio.new_event_loop()
        try:
            updated_report = loop.run_until_complete(
                monitor._escalate_channel(status, report)
            )
        finally:
            loop.close()

        # Assert: capturou frames adicionais (capture_sequence chamado)
        frame_capturer.capture_sequence.assert_called_once()

        # Assert: OpenCV foi acionado
        assert updated_report.escalated_to_opencv is True, (
            "Canal SUSPECT DEVE escalar para OpenCV, "
            "mas escalated_to_opencv=False."
        )

    @settings(max_examples=100)
    @given(
        buffer=suspect_buffer_st,
        audio=healthy_audio_st,
    )
    def test_suspect_buffer_low_invokes_opencv(
        self,
        buffer: BufferTelemetry,
        audio: AudioTelemetry,
    ) -> None:
        """Canal SUSPECT por BUFFER_LOW deve capturar frames e acionar OpenCV.

        Quando buffer_ahead < 2s (BUFFER_LOW), o canal é classificado
        como SUSPECT e a escalação DEVE acionar OpenCV.

        **Validates: Requirements 14.2**
        """
        # Arrange: vídeo saudável, buffer BUFFER_LOW → SUSPECT
        video = VideoTelemetry(
            current_time=10.0,
            duration=0.0,
            ready_state=4,
            paused=False,
            playing=True,
            ended=False,
            seeking=False,
            playback_rate=1.0,
            network_state=2,
            buffered_seconds=15.0,
            video_width=1920,
            video_height=1080,
            error=None,
        )

        cap_map = _build_minimal_capability_map()
        page_mock = MagicMock()

        frames = [FakeFrame(), FakeFrame(), FakeFrame()]
        frame_capturer = AsyncMock()
        frame_capturer.capture_frame = AsyncMock(
            return_value=FakeFrame()
        )
        frame_capturer.capture_sequence = AsyncMock(
            return_value=frames
        )

        opencv_mock = MagicMock()
        opencv_mock.detect_black_screen = MagicMock(
            return_value=MagicMock(is_black_screen=False)
        )
        opencv_mock.detect_freeze = MagicMock(
            return_value=MagicMock(
                classification=MagicMock(value="NORMAL")
            )
        )

        bedrock_mock = AsyncMock()

        monitor = ChannelMonitor(
            capability_map=cap_map,
            page=page_mock,
            frame_capturer=frame_capturer,
            opencv_analyzer=opencv_mock,
            bedrock_client=bedrock_mock,
        )

        # Act: classificar
        status = monitor._classify_channel_status(video, audio, buffer)
        assert status == ChannelHealthStatus.SUSPECT, (
            f"Esperado SUSPECT, obtido {status.value}."
        )

        # Act: executar escalação
        report = _build_healthy_report()
        report.status = status

        loop = asyncio.new_event_loop()
        try:
            updated_report = loop.run_until_complete(
                monitor._escalate_channel(status, report)
            )
        finally:
            loop.close()

        # Assert: OpenCV foi acionado
        assert updated_report.escalated_to_opencv is True, (
            "Canal SUSPECT (BUFFER_LOW) DEVE escalar para OpenCV."
        )

        # Assert: Bedrock NÃO foi acionado (OpenCV não confirmou)
        assert updated_report.escalated_to_bedrock is False, (
            "OpenCV NÃO confirmou anomalia, Bedrock NÃO deve "
            "ser acionado."
        )

    @settings(max_examples=100)
    @given(
        audio=suspect_audio_st,
    )
    def test_opencv_no_confirm_no_bedrock(
        self,
        audio: AudioTelemetry,
    ) -> None:
        """Se OpenCV NÃO confirma anomalia, Bedrock NÃO é acionado.

        Para qualquer canal SUSPECT onde OpenCV analisa frames e
        NÃO encontra anomalia (sem BLACK_SCREEN, sem FREEZE),
        Bedrock NÃO deve ser invocado.

        **Validates: Requirements 14.4**
        """
        # Arrange: vídeo saudável, áudio AUDIO_LOW → SUSPECT
        video = VideoTelemetry(
            current_time=10.0,
            duration=0.0,
            ready_state=4,
            paused=False,
            playing=True,
            ended=False,
            seeking=False,
            playback_rate=1.0,
            network_state=2,
            buffered_seconds=15.0,
            video_width=1920,
            video_height=1080,
            error=None,
        )

        cap_map = _build_minimal_capability_map()
        page_mock = MagicMock()

        frames = [FakeFrame(), FakeFrame(), FakeFrame()]
        frame_capturer = AsyncMock()
        frame_capturer.capture_frame = AsyncMock(
            return_value=FakeFrame()
        )
        frame_capturer.capture_sequence = AsyncMock(
            return_value=frames
        )

        # OpenCV NÃO confirma anomalia
        opencv_mock = MagicMock()
        opencv_mock.detect_black_screen = MagicMock(
            return_value=MagicMock(is_black_screen=False)
        )
        opencv_mock.detect_freeze = MagicMock(
            return_value=MagicMock(
                classification=MagicMock(value="NORMAL")
            )
        )

        bedrock_mock = AsyncMock()

        monitor = ChannelMonitor(
            capability_map=cap_map,
            page=page_mock,
            frame_capturer=frame_capturer,
            opencv_analyzer=opencv_mock,
            bedrock_client=bedrock_mock,
        )

        # Act
        status = ChannelHealthStatus.SUSPECT
        report = _build_healthy_report()
        report.status = status

        loop = asyncio.new_event_loop()
        try:
            updated_report = loop.run_until_complete(
                monitor._escalate_channel(status, report)
            )
        finally:
            loop.close()

        # Assert: OpenCV foi acionado
        assert updated_report.escalated_to_opencv is True, (
            "Canal SUSPECT DEVE escalar para OpenCV."
        )

        # Assert: Bedrock NÃO foi acionado
        assert updated_report.escalated_to_bedrock is False, (
            "OpenCV NÃO confirmou anomalia. "
            "Bedrock NÃO deve ser acionado (Req 14.4)."
        )

        # Assert: diagnose_frame nunca foi chamado
        bedrock_mock.diagnose_frame.assert_not_called()


# =============================================================================
# Property 23: Canal HEALTHY limita captura a 1 frame por ciclo
# =============================================================================

# Estratégias para geração de telemetria HEALTHY variada (Property 23)
_p23_current_time_st = st.floats(
    min_value=10.0, max_value=86400.0,
    allow_nan=False, allow_infinity=False,
)
_p23_buffer_ahead_st = st.floats(
    min_value=3.0, max_value=60.0,
    allow_nan=False, allow_infinity=False,
)
_p23_rms_st = st.floats(
    min_value=0.06, max_value=1.0,
    allow_nan=False, allow_infinity=False,
)
_p23_video_width_st = st.integers(min_value=640, max_value=3840)
_p23_video_height_st = st.integers(min_value=480, max_value=2160)
_p23_channel_id_st = st.text(
    min_size=1, max_size=20,
    alphabet=st.characters(whitelist_categories=("L", "N", "Pd")),
)


class TestProperty23CanalHealthyLimitaCaptura:
    """Property 23: Canal HEALTHY limita captura a 1 frame por ciclo.

    Para qualquer canal classificado como HEALTHY, a captura de frames
    deve ser limitada a exatamente 1 frame de validação por ciclo de
    observação — capture_sequence NÃO deve ser chamado, e nem OpenCV
    nem Bedrock devem ser invocados.

    **Validates: Requirements 14.5**
    """

    @settings(max_examples=100)
    @given(
        current_time=_p23_current_time_st,
        buffer_ahead=_p23_buffer_ahead_st,
        rms=_p23_rms_st,
        video_width=_p23_video_width_st,
        video_height=_p23_video_height_st,
        channel_id=_p23_channel_id_st,
    )
    def test_healthy_capture_frame_exatamente_uma_vez(
        self,
        current_time: float,
        buffer_ahead: float,
        rms: float,
        video_width: int,
        video_height: int,
        channel_id: str,
    ) -> None:
        """capture_frame chamado exatamente 1 vez para HEALTHY.

        Para qualquer canal HEALTHY com telemetria válida variada,
        _escalate_channel deve chamar capture_frame exatamente 1 vez
        (1 frame de validação por ciclo).

        **Validates: Requirements 14.5**
        """
        # Arrange
        cap_map = _build_minimal_capability_map()
        page_mock = MagicMock()

        frame_capturer = AsyncMock()
        frame_capturer.capture_frame = AsyncMock(
            return_value=FakeFrame()
        )
        frame_capturer.capture_sequence = AsyncMock(
            return_value=[FakeFrame(), FakeFrame()]
        )

        opencv_mock = MagicMock()
        bedrock_mock = AsyncMock()

        monitor = ChannelMonitor(
            capability_map=cap_map,
            page=page_mock,
            frame_capturer=frame_capturer,
            opencv_analyzer=opencv_mock,
            bedrock_client=bedrock_mock,
        )

        # Criar report HEALTHY com dados variados
        report = ChannelReport(
            channel_id=channel_id,
            channel_url=f"http://test/{channel_id}",
            status=ChannelHealthStatus.HEALTHY,
            health_scores=HealthScores(
                video_health=90.0,
                audio_health=90.0,
                functional_health=0.0,
            ),
            video_telemetry=VideoTelemetry(
                current_time=current_time,
                duration=0.0,
                ready_state=4,
                paused=False,
                playing=True,
                ended=False,
                seeking=False,
                playback_rate=1.0,
                network_state=2,
                buffered_seconds=buffer_ahead,
                video_width=video_width,
                video_height=video_height,
            ),
            audio_telemetry=AudioTelemetry(
                rms=rms,
                peak=rms + 0.1,
                silence_duration=0.0,
                muted=False,
                status=AudioStatus.OK,
            ),
            subtitle_telemetry=SubtitleTelemetry(),
            buffer_telemetry=BufferTelemetry(
                buffer_ahead=buffer_ahead,
                status=BufferStatus.OK,
            ),
            escalated_to_opencv=False,
            escalated_to_bedrock=False,
        )

        # Act
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(
                monitor._escalate_channel(
                    ChannelHealthStatus.HEALTHY, report
                )
            )
        finally:
            loop.close()

        # Assert: capture_frame chamado exatamente 1 vez
        assert frame_capturer.capture_frame.call_count == 1, (
            f"capture_frame deveria ser chamado exatamente 1 vez "
            f"para canal HEALTHY, mas foi chamado "
            f"{frame_capturer.capture_frame.call_count}x. "
            f"current_time={current_time}, buffer={buffer_ahead}, "
            f"rms={rms}"
        )

    @settings(max_examples=100)
    @given(
        current_time=_p23_current_time_st,
        buffer_ahead=_p23_buffer_ahead_st,
        rms=_p23_rms_st,
        video_width=_p23_video_width_st,
        video_height=_p23_video_height_st,
    )
    def test_healthy_capture_sequence_nunca_chamado(
        self,
        current_time: float,
        buffer_ahead: float,
        rms: float,
        video_width: int,
        video_height: int,
    ) -> None:
        """capture_sequence NÃO deve ser chamado para HEALTHY.

        Para qualquer canal HEALTHY, apenas capture_frame (1 frame) é
        permitido. capture_sequence (múltiplos frames) é reservado
        exclusivamente para canais SUSPECT/DEGRADED/CRITICAL.

        **Validates: Requirements 14.5**
        """
        # Arrange
        cap_map = _build_minimal_capability_map()
        page_mock = MagicMock()

        frame_capturer = AsyncMock()
        frame_capturer.capture_frame = AsyncMock(
            return_value=FakeFrame()
        )
        frame_capturer.capture_sequence = AsyncMock(
            return_value=[FakeFrame(), FakeFrame()]
        )

        opencv_mock = MagicMock()
        bedrock_mock = AsyncMock()

        monitor = ChannelMonitor(
            capability_map=cap_map,
            page=page_mock,
            frame_capturer=frame_capturer,
            opencv_analyzer=opencv_mock,
            bedrock_client=bedrock_mock,
        )

        report = _build_healthy_report()

        # Act
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(
                monitor._escalate_channel(
                    ChannelHealthStatus.HEALTHY, report
                )
            )
        finally:
            loop.close()

        # Assert: capture_sequence NUNCA chamado
        frame_capturer.capture_sequence.assert_not_called()

    @settings(max_examples=100)
    @given(
        current_time=_p23_current_time_st,
        buffer_ahead=_p23_buffer_ahead_st,
        rms=_p23_rms_st,
    )
    def test_healthy_sem_opencv_sem_bedrock(
        self,
        current_time: float,
        buffer_ahead: float,
        rms: float,
    ) -> None:
        """Canal HEALTHY não invoca OpenCV nem Bedrock.

        Para qualquer canal HEALTHY, as dependências OpenCV
        (detect_black_screen, detect_freeze) e Bedrock
        (diagnose_frame) NÃO devem ser invocadas.

        **Validates: Requirements 14.5**
        """
        # Arrange
        cap_map = _build_minimal_capability_map()
        page_mock = MagicMock()

        frame_capturer = AsyncMock()
        frame_capturer.capture_frame = AsyncMock(
            return_value=FakeFrame()
        )
        frame_capturer.capture_sequence = AsyncMock(
            return_value=[FakeFrame()]
        )

        opencv_mock = MagicMock()
        opencv_mock.detect_black_screen = MagicMock()
        opencv_mock.detect_freeze = MagicMock()

        bedrock_mock = AsyncMock()
        bedrock_mock.diagnose_frame = AsyncMock()

        monitor = ChannelMonitor(
            capability_map=cap_map,
            page=page_mock,
            frame_capturer=frame_capturer,
            opencv_analyzer=opencv_mock,
            bedrock_client=bedrock_mock,
        )

        report = ChannelReport(
            channel_id="ch-test",
            channel_url="http://test/ch-test",
            status=ChannelHealthStatus.HEALTHY,
            health_scores=HealthScores(
                video_health=95.0,
                audio_health=90.0,
                functional_health=0.0,
            ),
            video_telemetry=VideoTelemetry(
                current_time=current_time,
                duration=0.0,
                ready_state=4,
                paused=False,
                playing=True,
                ended=False,
                seeking=False,
                playback_rate=1.0,
                network_state=2,
                buffered_seconds=buffer_ahead,
                video_width=1920,
                video_height=1080,
            ),
            audio_telemetry=AudioTelemetry(
                rms=rms,
                peak=min(rms + 0.1, 1.0),
                silence_duration=0.0,
                muted=False,
                status=AudioStatus.OK,
            ),
            subtitle_telemetry=SubtitleTelemetry(),
            buffer_telemetry=BufferTelemetry(
                buffer_ahead=buffer_ahead,
                status=BufferStatus.OK,
            ),
            escalated_to_opencv=False,
            escalated_to_bedrock=False,
        )

        # Act
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                monitor._escalate_channel(
                    ChannelHealthStatus.HEALTHY, report
                )
            )
        finally:
            loop.close()

        # Assert: OpenCV NÃO invocado
        opencv_mock.detect_black_screen.assert_not_called()
        opencv_mock.detect_freeze.assert_not_called()

        # Assert: Bedrock NÃO invocado
        bedrock_mock.diagnose_frame.assert_not_called()

        # Assert: flags de escalação permanecem False
        assert result.escalated_to_opencv is False, (
            "Canal HEALTHY não deve marcar escalated_to_opencv"
        )
        assert result.escalated_to_bedrock is False, (
            "Canal HEALTHY não deve marcar escalated_to_bedrock"
        )
