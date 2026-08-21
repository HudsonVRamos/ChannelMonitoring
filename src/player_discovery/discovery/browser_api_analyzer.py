"""Analisador de Browser APIs padrão para Player Discovery.

Verifica a disponibilidade de Browser APIs que fornecem informações
de telemetria do player de vídeo:
- HTMLMediaElement (elemento de vídeo com src/currentSrc)
- TextTrackList (legendas via video.textTracks)
- AudioTrackList (faixas de áudio via video.audioTracks)
- MediaCapabilities API (navigator.mediaCapabilities)
- Media Session API (navigator.mediaSession)
- Performance APIs (performance.getEntriesByType)
- getVideoPlaybackQuality() (qualidade de reprodução)

Requirements: 1.4
"""

import logging
from dataclasses import dataclass, field

from playwright.async_api import Page

logger = logging.getLogger(__name__)


@dataclass
class BrowserAPIEvidence:
    """Evidência encontrada via Browser APIs padrão.

    Attributes:
        api_name: Nome da API verificada
            (ex: "HTMLMediaElement", "TextTrackList")
        available: Se a API está disponível no browser
        capability_hint: Qual capability esta API suporta
        confidence_contribution: Contribuição para confidence
            (0.0 a 1.0)
        details: Detalhes adicionais da verificação
    """

    api_name: str
    available: bool
    capability_hint: str
    confidence_contribution: float
    details: dict = field(default_factory=dict)


# JavaScript que verifica todas as Browser APIs de uma vez
_BROWSER_API_CHECK_JS = """
() => {
    const results = [];

    // 1. HTMLMediaElement - verifica se existe video com src
    const videos = document.querySelectorAll('video');
    const videoElement = videos.length > 0 ? videos[0] : null;
    const hasVideoSrc = videoElement
        ? !!(videoElement.src || videoElement.currentSrc)
        : false;
    results.push({
        api_name: 'HTMLMediaElement',
        available: videos.length > 0,
        capability_hint: 'video_playback',
        details: {
            video_count: videos.length,
            has_src: hasVideoSrc,
            current_src: videoElement
                ? (videoElement.currentSrc || '').substring(0, 100)
                : null,
            ready_state: videoElement ? videoElement.readyState : null,
            paused: videoElement ? videoElement.paused : null
        }
    });

    // 2. TextTrackList - legendas
    const hasTextTracks = videoElement
        ? typeof videoElement.textTracks !== 'undefined'
        : false;
    const textTrackCount = hasTextTracks
        ? videoElement.textTracks.length
        : 0;
    results.push({
        api_name: 'TextTrackList',
        available: hasTextTracks,
        capability_hint: 'subtitle_selection',
        details: {
            track_count: textTrackCount,
            tracks: hasTextTracks
                ? Array.from(videoElement.textTracks).map(t => ({
                    kind: t.kind,
                    language: t.language,
                    label: t.label,
                    mode: t.mode
                }))
                : []
        }
    });

    // 3. AudioTrackList - faixas de áudio
    const hasAudioTracks = videoElement
        ? typeof videoElement.audioTracks !== 'undefined'
        : false;
    const audioTrackCount = hasAudioTracks
        ? videoElement.audioTracks.length
        : 0;
    results.push({
        api_name: 'AudioTrackList',
        available: hasAudioTracks,
        capability_hint: 'audio_selection',
        details: {
            track_count: audioTrackCount,
            tracks: hasAudioTracks
                ? Array.from(videoElement.audioTracks).map(t => ({
                    id: t.id,
                    language: t.language,
                    label: t.label,
                    enabled: t.enabled
                }))
                : []
        }
    });

    // 4. MediaCapabilities API
    const hasMediaCapabilities =
        typeof navigator.mediaCapabilities !== 'undefined';
    results.push({
        api_name: 'MediaCapabilities',
        available: hasMediaCapabilities,
        capability_hint: 'quality_selection',
        details: {
            has_decoding_info:
                hasMediaCapabilities
                && typeof navigator.mediaCapabilities.decodingInfo
                    === 'function',
            has_encoding_info:
                hasMediaCapabilities
                && typeof navigator.mediaCapabilities.encodingInfo
                    === 'function'
        }
    });

    // 5. Media Session API
    const hasMediaSession =
        typeof navigator.mediaSession !== 'undefined';
    results.push({
        api_name: 'MediaSession',
        available: hasMediaSession,
        capability_hint: 'play',
        details: {
            playback_state: hasMediaSession
                ? navigator.mediaSession.playbackState
                : null,
            has_metadata: hasMediaSession
                ? navigator.mediaSession.metadata !== null
                : false
        }
    });

    // 6. Performance APIs
    const hasPerformance =
        typeof performance !== 'undefined'
        && typeof performance.getEntriesByType === 'function';
    let resourceEntries = [];
    if (hasPerformance) {
        try {
            const entries = performance.getEntriesByType('resource');
            resourceEntries = entries
                .filter(e =>
                    e.name.includes('.m3u8')
                    || e.name.includes('.mpd')
                    || e.name.includes('.mp4')
                    || e.name.includes('.ts')
                    || e.name.includes('segment')
                )
                .slice(0, 10)
                .map(e => ({
                    name: e.name.substring(0, 100),
                    duration: e.duration,
                    transfer_size: e.transferSize
                }));
        } catch (err) {
            // Silenciar erros de segurança
        }
    }
    results.push({
        api_name: 'PerformanceAPI',
        available: hasPerformance,
        capability_hint: 'video_playback',
        details: {
            media_entries_count: resourceEntries.length,
            media_entries: resourceEntries
        }
    });

    // 7. getVideoPlaybackQuality
    const hasPlaybackQuality = videoElement
        ? typeof videoElement.getVideoPlaybackQuality === 'function'
        : false;
    let qualityData = null;
    if (hasPlaybackQuality) {
        try {
            const quality = videoElement.getVideoPlaybackQuality();
            qualityData = {
                total_frames: quality.totalVideoFrames,
                dropped_frames: quality.droppedVideoFrames,
                corrupted_frames: quality.corruptedVideoFrames || 0,
                creation_time: quality.creationTime
            };
        } catch (err) {
            // Silenciar erros
        }
    }
    results.push({
        api_name: 'VideoPlaybackQuality',
        available: hasPlaybackQuality,
        capability_hint: 'video_playback',
        details: qualityData || {}
    });

    return results;
}
"""


class BrowserAPIAnalyzer:
    """Verifica disponibilidade de Browser APIs padrão.

    Analisa quais APIs do browser estão disponíveis para fornecer
    informações de telemetria do player. Usa page.evaluate() para
    executar JavaScript que verifica cada API.
    """

    # Mapeamento de confidence por API
    _CONFIDENCE_MAP: dict[str, float] = {
        "HTMLMediaElement": 0.3,
        "TextTrackList": 0.2,
        "AudioTrackList": 0.2,
        "MediaCapabilities": 0.1,
        "MediaSession": 0.1,
        "PerformanceAPI": 0.1,
        "VideoPlaybackQuality": 0.2,
    }

    async def analyze(self, page: Page) -> list[BrowserAPIEvidence]:
        """Verifica disponibilidade de Browser APIs.

        Executa JavaScript no browser via page.evaluate() para
        verificar quais APIs estão disponíveis e coletar detalhes
        sobre cada uma.

        Args:
            page: Instância do Playwright Page para executar JS.

        Returns:
            Lista de BrowserAPIEvidence com o resultado de cada
            verificação.
        """
        try:
            raw_results = await page.evaluate(_BROWSER_API_CHECK_JS)
        except Exception as e:
            logger.error(
                "Erro ao verificar Browser APIs: %s", str(e)
            )
            return self._fallback_results()

        evidences: list[BrowserAPIEvidence] = []
        for result in raw_results:
            api_name = result.get("api_name", "Unknown")
            available = result.get("available", False)
            capability_hint = result.get(
                "capability_hint", "unknown"
            )
            details = result.get("details", {})

            confidence = self._calculate_confidence(
                api_name, available, details
            )

            evidence = BrowserAPIEvidence(
                api_name=api_name,
                available=available,
                capability_hint=capability_hint,
                confidence_contribution=confidence,
                details=details,
            )
            evidences.append(evidence)

        logger.info(
            "Browser APIs analisadas: %d APIs verificadas, "
            "%d disponíveis",
            len(evidences),
            sum(1 for e in evidences if e.available),
        )

        return evidences

    def _calculate_confidence(
        self,
        api_name: str,
        available: bool,
        details: dict,
    ) -> float:
        """Calcula a contribuição de confidence para uma API.

        A confidence base vem do mapa de pesos por API. Se a API
        está indisponível, a contribuição é 0.0. Se disponível,
        detalhes adicionais podem aumentar ou reduzir a confidence.

        Args:
            api_name: Nome da API verificada.
            available: Se a API está disponível.
            details: Detalhes coletados da API.

        Returns:
            Valor de confidence entre 0.0 e 1.0.
        """
        if not available:
            return 0.0

        base_confidence = self._CONFIDENCE_MAP.get(api_name, 0.05)

        # Ajustes baseados em detalhes
        if api_name == "HTMLMediaElement":
            if details.get("has_src"):
                base_confidence += 0.1
            if details.get("ready_state", 0) >= 3:
                base_confidence += 0.05

        elif api_name == "TextTrackList":
            track_count = details.get("track_count", 0)
            if track_count > 0:
                base_confidence += 0.1

        elif api_name == "AudioTrackList":
            track_count = details.get("track_count", 0)
            if track_count > 0:
                base_confidence += 0.1

        elif api_name == "VideoPlaybackQuality":
            if details.get("total_frames", 0) > 0:
                base_confidence += 0.1

        elif api_name == "PerformanceAPI":
            entries_count = details.get("media_entries_count", 0)
            if entries_count > 0:
                base_confidence += 0.05

        # Garantir range válido [0.0, 1.0]
        return min(max(base_confidence, 0.0), 1.0)

    def _fallback_results(self) -> list[BrowserAPIEvidence]:
        """Retorna resultados de fallback quando page.evaluate falha.

        Todas as APIs são marcadas como indisponíveis com confidence 0.

        Returns:
            Lista com todas as APIs marcadas como indisponíveis.
        """
        api_hints = [
            ("HTMLMediaElement", "video_playback"),
            ("TextTrackList", "subtitle_selection"),
            ("AudioTrackList", "audio_selection"),
            ("MediaCapabilities", "quality_selection"),
            ("MediaSession", "play"),
            ("PerformanceAPI", "video_playback"),
            ("VideoPlaybackQuality", "video_playback"),
        ]

        return [
            BrowserAPIEvidence(
                api_name=name,
                available=False,
                capability_hint=hint,
                confidence_contribution=0.0,
                details={"error": "page.evaluate falhou"},
            )
            for name, hint in api_hints
        ]
