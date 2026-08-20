"""Coletor de telemetria do player em tempo real.

Coleta métricas de vídeo, áudio e legendas via JavaScript injection
usando Playwright page.evaluate(). Produz TelemetrySample em formato
JSON com timestamp ISO 8601.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional

from playwright.async_api import Page

from src.models import (
    AudioMetrics,
    PlayerMetrics,
    SubtitleMetrics,
    TelemetrySample,
    VideoMetrics,
)
from src.structured_logger import StructuredLogger

STAGE_ID = "telemetry_collector"


class TelemetryCollector:
    """Coleta telemetria do player em tempo real.

    Usa page.evaluate() para executar JavaScript no contexto do player
    e extrair métricas de vídeo, áudio e legendas.
    """

    def __init__(
        self,
        interval_seconds: float = 2.0,
        channel_id: str = "unknown",
    ) -> None:
        """Inicializa o coletor de telemetria.

        Args:
            interval_seconds: Intervalo entre coletas (padrão: 2s).
            channel_id: Identificador do canal monitorado.
        """
        self.interval_seconds = interval_seconds
        self.channel_id = channel_id
        self._logger = StructuredLogger(min_level="DEBUG")
        self._last_error: Optional[str] = None
        self._error_listener_attached = False

    async def collect_video_metrics(self, page: Page) -> VideoMetrics:
        """Coleta currentTime, readyState, paused, buffered_seconds.

        Executa JavaScript para acessar o elemento <video> e extrair
        as métricas de reprodução.

        Args:
            page: Página do Playwright com o player carregado.

        Returns:
            VideoMetrics com os dados coletados do player.
        """
        try:
            result = await page.evaluate("""
                () => {
                    const video = document.querySelector('video');
                    if (!video) {
                        return {
                            current_time: 0.0,
                            video_width: 0,
                            video_height: 0,
                            ready_state: 0,
                            paused: true,
                            error: 'Elemento video não encontrado',
                            buffered_seconds: 0.0
                        };
                    }
                    let buffered_seconds = 0.0;
                    try {
                        if (video.buffered && video.buffered.length > 0) {
                            buffered_seconds = video.buffered.end(
                                video.buffered.length - 1
                            ) - video.currentTime;
                        }
                    } catch (e) {
                        buffered_seconds = 0.0;
                    }
                    let error_msg = null;
                    if (video.error) {
                        error_msg = `Code: ${video.error.code}, `
                            + `Message: ${video.error.message || 'N/A'}`;
                    }
                    return {
                        current_time: video.currentTime || 0.0,
                        video_width: video.videoWidth || 0,
                        video_height: video.videoHeight || 0,
                        ready_state: video.readyState || 0,
                        paused: video.paused,
                        error: error_msg,
                        buffered_seconds: buffered_seconds
                    };
                }
            """)

            return VideoMetrics(
                current_time=float(result.get("current_time", 0.0)),
                video_width=int(result.get("video_width", 0)),
                video_height=int(result.get("video_height", 0)),
                ready_state=int(result.get("ready_state", 0)),
                paused=bool(result.get("paused", True)),
                error=result.get("error"),
                buffered_seconds=float(
                    result.get("buffered_seconds", 0.0)
                ),
            )

        except Exception as e:
            self._logger.warning(
                STAGE_ID,
                "Falha ao coletar métricas de vídeo",
                error=str(e),
            )
            return VideoMetrics(
                current_time=0.0,
                video_width=0,
                video_height=0,
                ready_state=0,
                paused=True,
                error=f"Coleta falhou: {e}",
                buffered_seconds=0.0,
            )

    async def collect_audio_metrics(self, page: Page) -> AudioMetrics:
        """Coleta nível de áudio via Web Audio API.

        Tenta conectar ao elemento de vídeo via AudioContext e
        AnalyserNode. Se a Web Audio API não estiver disponível ou
        não for conectável, retorna valores null com indicação de
        indisponibilidade.

        Args:
            page: Página do Playwright com o player carregado.

        Returns:
            AudioMetrics com níveis de áudio ou indicação de
            indisponibilidade.
        """
        try:
            result = await page.evaluate("""
                () => {
                    const video = document.querySelector('video');
                    if (!video) {
                        return {
                            average_level: null,
                            peak_level: null,
                            is_muted: true,
                            unavailable: true
                        };
                    }

                    // Verificar mute primeiro
                    const is_muted = video.muted || video.volume === 0;

                    try {
                        // Tentar usar Web Audio API
                        if (!window.__pocAudioContext) {
                            window.__pocAudioContext = new (
                                window.AudioContext
                                || window.webkitAudioContext
                            )();
                            window.__pocAudioSource = (
                                window.__pocAudioContext
                                    .createMediaElementSource(video)
                            );
                            window.__pocAnalyser = (
                                window.__pocAudioContext.createAnalyser()
                            );
                            window.__pocAnalyser.fftSize = 256;
                            window.__pocAudioSource.connect(
                                window.__pocAnalyser
                            );
                            window.__pocAnalyser.connect(
                                window.__pocAudioContext.destination
                            );
                        }

                        const analyser = window.__pocAnalyser;
                        const dataArray = new Uint8Array(
                            analyser.frequencyBinCount
                        );
                        analyser.getByteFrequencyData(dataArray);

                        // Calcular níveis
                        let sum = 0;
                        let peak = 0;
                        for (let i = 0; i < dataArray.length; i++) {
                            sum += dataArray[i];
                            if (dataArray[i] > peak) {
                                peak = dataArray[i];
                            }
                        }
                        const average = sum / dataArray.length;

                        // Converter para escala 0-100
                        const average_level = (average / 255.0) * 100.0;
                        const peak_level = (peak / 255.0) * 100.0;

                        return {
                            average_level: average_level,
                            peak_level: peak_level,
                            is_muted: is_muted,
                            unavailable: false
                        };
                    } catch (e) {
                        // Web Audio API não disponível ou não conectável
                        return {
                            average_level: null,
                            peak_level: null,
                            is_muted: is_muted,
                            unavailable: true
                        };
                    }
                }
            """)

            return AudioMetrics(
                average_level=result.get("average_level"),
                peak_level=result.get("peak_level"),
                is_muted=bool(result.get("is_muted", True)),
                unavailable=bool(result.get("unavailable", True)),
            )

        except Exception as e:
            self._logger.warning(
                STAGE_ID,
                "Falha ao coletar métricas de áudio",
                error=str(e),
            )
            return AudioMetrics(
                average_level=None,
                peak_level=None,
                is_muted=True,
                unavailable=True,
            )

    async def collect_subtitle_metrics(
        self, page: Page
    ) -> SubtitleMetrics:
        """Coleta dados de legendas do player.

        Acessa video.textTracks para obter quantidade de tracks,
        track ativa e presença de cues.

        Args:
            page: Página do Playwright com o player carregado.

        Returns:
            SubtitleMetrics com dados de legendas.
        """
        try:
            result = await page.evaluate("""
                () => {
                    const video = document.querySelector('video');
                    if (!video || !video.textTracks) {
                        return {
                            tracks_available: 0,
                            active_track: null,
                            has_active_cues: false
                        };
                    }

                    const tracks = video.textTracks;
                    let active_track = null;
                    let has_active_cues = false;

                    for (let i = 0; i < tracks.length; i++) {
                        if (tracks[i].mode === 'showing') {
                            active_track = tracks[i].label
                                || tracks[i].language
                                || `Track ${i}`;
                            has_active_cues = (
                                tracks[i].activeCues !== null
                                && tracks[i].activeCues.length > 0
                            );
                            break;
                        }
                    }

                    return {
                        tracks_available: tracks.length,
                        active_track: active_track,
                        has_active_cues: has_active_cues
                    };
                }
            """)

            return SubtitleMetrics(
                tracks_available=int(
                    result.get("tracks_available", 0)
                ),
                active_track=result.get("active_track"),
                has_active_cues=bool(
                    result.get("has_active_cues", False)
                ),
            )

        except Exception as e:
            self._logger.warning(
                STAGE_ID,
                "Falha ao coletar métricas de legendas",
                error=str(e),
            )
            return SubtitleMetrics(
                tracks_available=0,
                active_track=None,
                has_active_cues=False,
            )

    async def collect_sample(self, page: Page) -> TelemetrySample:
        """Coleta uma amostra completa de telemetria.

        Reúne métricas de vídeo, áudio, legendas e estado do player
        em um objeto TelemetrySample com timestamp ISO 8601.

        Args:
            page: Página do Playwright com o player carregado.

        Returns:
            TelemetrySample completo com todas as métricas.
        """
        timestamp = datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S."
        ) + f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"

        # Coletar métricas em paralelo
        video, audio, subtitles = await asyncio.gather(
            self.collect_video_metrics(page),
            self.collect_audio_metrics(page),
            self.collect_subtitle_metrics(page),
        )

        # Determinar estado do player
        player = PlayerMetrics(
            playing=(
                not video.paused
                and video.ready_state >= 3
                and video.current_time > 0
            ),
            buffering=(
                video.ready_state < 3 and not video.paused
            ),
            drm_ok=video.error is None,
        )

        sample = TelemetrySample(
            timestamp=timestamp,
            channel_id=self.channel_id,
            video=video,
            audio=audio,
            subtitles=subtitles,
            player=player,
        )

        # Log DEBUG para cada amostra coletada (Req 10.4)
        self._logger.debug(
            STAGE_ID,
            "Amostra de telemetria coletada",
            current_time=video.current_time,
            ready_state=video.ready_state,
            paused=video.paused,
            buffered_seconds=video.buffered_seconds,
            audio_level=audio.average_level,
            playing=player.playing,
        )

        return sample

    async def start_continuous_collection(
        self, page: Page, duration_seconds: float
    ) -> list[TelemetrySample]:
        """Coleta contínua durante um período configurável.

        Coleta amostras no intervalo configurado até atingir a
        duração total especificada.

        Args:
            page: Página do Playwright com o player carregado.
            duration_seconds: Duração total da coleta em segundos.

        Returns:
            Lista de TelemetrySample coletados durante o período.
        """
        samples: list[TelemetrySample] = []
        elapsed = 0.0

        self._logger.info(
            STAGE_ID,
            "Iniciando coleta contínua de telemetria",
            duration_seconds=duration_seconds,
            interval_seconds=self.interval_seconds,
            channel_id=self.channel_id,
        )

        # Anexar listener de erro do player para captura em ≤500ms
        await self._attach_error_listener(page)

        while elapsed < duration_seconds:
            sample = await self.collect_sample(page)
            samples.append(sample)

            # Verificar se houve erro capturado pelo listener
            if self._last_error:
                self._logger.warning(
                    STAGE_ID,
                    "Erro do player capturado durante coleta",
                    error=self._last_error,
                    elapsed_seconds=elapsed,
                )
                self._last_error = None

            elapsed += self.interval_seconds
            if elapsed < duration_seconds:
                await asyncio.sleep(self.interval_seconds)

        self._logger.info(
            STAGE_ID,
            "Coleta contínua finalizada",
            total_samples=len(samples),
            duration_seconds=duration_seconds,
        )

        return samples

    async def _attach_error_listener(self, page: Page) -> None:
        """Anexa listener de erro no player para captura rápida.

        O listener captura erros do player em ≤500ms após o evento
        de erro, conforme requisito 3.5.

        Args:
            page: Página do Playwright com o player carregado.
        """
        if self._error_listener_attached:
            return

        try:
            await page.evaluate("""
                () => {
                    const video = document.querySelector('video');
                    if (video && !video.__pocErrorListener) {
                        video.__pocErrorListener = true;
                        video.addEventListener('error', (e) => {
                            window.__pocLastPlayerError = {
                                code: video.error
                                    ? video.error.code : -1,
                                message: video.error
                                    ? (video.error.message || 'Unknown')
                                    : 'Unknown',
                                timestamp: new Date().toISOString()
                            };
                        });
                    }
                }
            """)
            self._error_listener_attached = True
        except Exception as e:
            self._logger.warning(
                STAGE_ID,
                "Falha ao anexar listener de erro",
                error=str(e),
            )

    async def _check_player_error(self, page: Page) -> Optional[str]:
        """Verifica se há erro pendente do player.

        Args:
            page: Página do Playwright com o player carregado.

        Returns:
            Mensagem de erro se houver, None caso contrário.
        """
        try:
            error = await page.evaluate("""
                () => {
                    const err = window.__pocLastPlayerError;
                    if (err) {
                        window.__pocLastPlayerError = null;
                        return `Code: ${err.code}, `
                            + `Message: ${err.message}, `
                            + `Time: ${err.timestamp}`;
                    }
                    return null;
                }
            """)
            return error
        except Exception:
            return None
