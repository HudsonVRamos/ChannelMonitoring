"""Data models de telemetria do Player Discovery.

Define as estruturas de dados para telemetria coletada pelas probes:
- VideoTelemetry: Métricas de reprodução de vídeo
- AudioTelemetry: Métricas de áudio via Web Audio API
- SubtitleTelemetry: Informações de tracks de legenda
- BufferTelemetry: Métricas de buffer e waiting events
- PlayerEvent: Eventos do HTMLMediaElement
"""

from dataclasses import dataclass, field
from typing import Optional

from dataclasses_json import dataclass_json

from .enums import AudioStatus, BufferStatus


@dataclass_json
@dataclass
class VideoTelemetry:
    """Telemetria completa de vídeo por canal.

    Coletada pela VideoProbe a cada 2 segundos via HTMLMediaElement.

    Attributes:
        current_time: Posição atual de reprodução (segundos)
        duration: Duração total do conteúdo (segundos)
        ready_state: Estado de prontidão do elemento (0-4)
        paused: Se o vídeo está pausado
        playing: Se o vídeo está reproduzindo
        ended: Se o vídeo terminou
        seeking: Se o vídeo está fazendo seek
        playback_rate: Taxa de reprodução (1.0 = normal)
        network_state: Estado da rede (0-3)
        buffered_seconds: Segundos de conteúdo em buffer
        video_width: Largura do vídeo em pixels
        video_height: Altura do vídeo em pixels
        error: Mensagem de erro se houver
        total_frames: Total de frames renderizados (getVideoPlaybackQuality)
        dropped_frames: Frames descartados (getVideoPlaybackQuality)
        drop_rate: Taxa de descarte (dropped/total)
        fps_avg: FPS médio na janela de observação
        fps_min: FPS mínimo na janela de observação
        fps_max: FPS máximo na janela de observação
        quality_changes: Número de mudanças de qualidade ABR
        up_switches: Número de mudanças para qualidade superior
        down_switches: Número de mudanças para qualidade inferior
    """

    current_time: float
    duration: float
    ready_state: int
    paused: bool
    playing: bool
    ended: bool
    seeking: bool
    playback_rate: float
    network_state: int
    buffered_seconds: float
    video_width: int
    video_height: int
    error: Optional[str] = None
    total_frames: Optional[int] = None
    dropped_frames: Optional[int] = None
    drop_rate: Optional[float] = None
    fps_avg: Optional[float] = None
    fps_min: Optional[float] = None
    fps_max: Optional[float] = None
    quality_changes: int = 0
    up_switches: int = 0
    down_switches: int = 0


@dataclass_json
@dataclass
class AudioTelemetry:
    """Telemetria completa de áudio por canal.

    Coletada pela AudioProbe via Web Audio API a cada 2 segundos.

    Attributes:
        rms: Nível RMS do áudio (Root Mean Square)
        peak: Nível de pico do áudio
        silence_duration: Duração acumulada de silêncio (segundos)
        muted: Se o player está mutado
        status: Status classificado do áudio (OK, NO_AUDIO, AUDIO_LOW)
        tracks_available: Lista de tracks de áudio disponíveis
    """

    rms: Optional[float] = None
    peak: Optional[float] = None
    silence_duration: float = 0.0
    muted: bool = False
    status: AudioStatus = AudioStatus.OK
    tracks_available: list[str] = field(default_factory=list)


@dataclass_json
@dataclass
class SubtitleTelemetry:
    """Telemetria completa de legendas por canal.

    Coletada pela SubtitleProbe via TextTrack API.

    Attributes:
        tracks_available: Quantidade de tracks de legenda disponíveis
        tracks: Lista de informações de cada track (language, label, kind, mode)
        active_track: Identificador da track ativa (se houver)
        has_active_cues: Se existem cues ativas no momento
        status: Status geral de legendas ("OK", "SUBTITLE_UNAVAILABLE")
    """

    tracks_available: int = 0
    tracks: list[dict] = field(default_factory=list)
    active_track: Optional[str] = None
    has_active_cues: bool = False
    status: str = "OK"


@dataclass_json
@dataclass
class BufferTelemetry:
    """Telemetria detalhada de buffer.

    Coletada pela BufferProbe a cada 2 segundos.

    Attributes:
        buffered_start: Início do range de buffer (segundos)
        buffered_end: Fim do range de buffer (segundos)
        buffer_ahead: Diferença entre buffered_end e currentTime (segundos)
        waiting_count: Número de eventos waiting/stalled
        waiting_total_ms: Soma das durações de waiting (milissegundos)
        longest_wait_ms: Maior duração individual de waiting (milissegundos)
        time_since_last_wait: Tempo desde o último evento waiting (segundos)
        status: Status classificado do buffer (OK, BUFFER_LOW, BUFFERING_FREQUENT)
    """

    buffered_start: float = 0.0
    buffered_end: float = 0.0
    buffer_ahead: float = 0.0
    waiting_count: int = 0
    waiting_total_ms: float = 0.0
    longest_wait_ms: float = 0.0
    time_since_last_wait: Optional[float] = None
    status: BufferStatus = BufferStatus.OK


@dataclass_json
@dataclass
class PlayerEvent:
    """Evento do HTMLMediaElement registrado pela EventProbe.

    Attributes:
        event_type: Tipo do evento (ex: "play", "pause", "waiting", "error")
        timestamp: Timestamp ISO 8601 com milissegundos
        current_time: Posição de reprodução no momento do evento
        additional_data: Dados adicionais relevantes (error code, buffered_seconds, etc.)
    """

    event_type: str
    timestamp: str  # ISO 8601
    current_time: float
    additional_data: dict = field(default_factory=dict)
