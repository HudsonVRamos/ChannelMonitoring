"""Analisador de JavaScript APIs do player.

Investiga objetos globais e APIs do player via page.evaluate() do Playwright,
descobrindo dinamicamente:
- Player instance e biblioteca (shaka-player, video.js, hls.js, dashjs, etc.)
- Versão do player
- Track APIs (getVariantTracks, getAudioLanguages, etc.)
- Quality APIs (getStats, getPlaybackRate, etc.)
- Audio APIs (getAudioTracks, selectAudioLanguage, etc.)
- Subtitle APIs (getTextTracks, setTextTrackVisibility, etc.)
- Event APIs (addEventListener, listeners disponíveis)

Requirements: 1.3
"""

import logging
from dataclasses import dataclass, field
from typing import Protocol

from src.player_discovery.models.enums import InteractionLevel


logger = logging.getLogger(__name__)


class Page(Protocol):
    """Protocolo mínimo de Page do Playwright para type checking."""

    async def evaluate(self, expression: str) -> object:
        """Avalia expressão JavaScript na página."""
        ...


@dataclass
class JSEvidence:
    """Evidência encontrada via análise de JavaScript APIs.

    Attributes:
        api_path: Caminho da API (ex: "window.player.play")
        capability_hint: Qual capability esta API pode representar
        confidence_contribution: Contribuição para confidence (0.0-1.0)
        details: Detalhes adicionais (library, version, methods, etc.)
        interaction_hint: Sempre PLAYER_API para APIs JS (Nível 1)
    """

    api_path: str
    capability_hint: str
    confidence_contribution: float
    details: dict = field(default_factory=dict)
    interaction_hint: InteractionLevel = InteractionLevel.PLAYER_API


# Mapeamento de objetos globais conhecidos → biblioteca do player
KNOWN_PLAYER_GLOBALS = {
    "window.shaka": "shaka-player",
    "window.shaka.Player": "shaka-player",
    "window.videojs": "video.js",
    "window.Hls": "hls.js",
    "window.dashjs": "dashjs",
    "window.flvjs": "flv.js",
    "window.jwplayer": "jwplayer",
    "window.bitmovin": "bitmovin",
    "window.castPlayer": "cast-player",
}

# Mapeamento de APIs → capability que representam
CAPABILITY_API_MAP = {
    # Play/Pause
    "play": "play",
    "pause": "pause",
    # Mute/Unmute
    "setMuted": "mute",
    "mute": "mute",
    "unmute": "unmute",
    "isMuted": "mute",
    "getMuted": "mute",
    # Audio
    "getAudioTracks": "audio_selection",
    "getAudioLanguages": "audio_selection",
    "getAudioLanguagesAndRoles": "audio_selection",
    "selectAudioLanguage": "audio_selection",
    "selectAudioTrack": "audio_selection",
    # Subtitle/Legendas
    "getTextTracks": "subtitle_selection",
    "getTextLanguages": "subtitle_selection",
    "getTextLanguagesAndRoles": "subtitle_selection",
    "setTextTrackVisibility": "subtitle_selection",
    "selectTextLanguage": "subtitle_selection",
    "selectTextTrack": "subtitle_selection",
    # Quality
    "getVariantTracks": "quality_selection",
    "selectVariantTrack": "quality_selection",
    "getQualityLevels": "quality_selection",
    "setQualityLevel": "quality_selection",
    "getStats": "quality_selection",
    "getPlaybackRate": "quality_selection",
    # Fullscreen
    "requestFullscreen": "fullscreen",
    "enterFullscreen": "fullscreen",
    "exitFullscreen": "fullscreen",
    "isFullscreen": "fullscreen",
    # Settings/Config
    "configure": "settings",
    "getConfiguration": "settings",
    "getNetworkingEngine": "settings",
}


# JavaScript que detecta biblioteca e versão do player
JS_DETECT_PLAYER_LIBRARY = """
() => {
    const result = {
        library: null,
        version: null,
        player_instance: null,
        globals_found: []
    };

    // Shaka Player
    if (window.shaka) {
        result.globals_found.push('window.shaka');
        result.library = 'shaka-player';
        if (window.shaka.Player && window.shaka.Player.version) {
            result.version = window.shaka.Player.version;
        }
        // Procurar instância do player
        const videos = document.querySelectorAll('video');
        for (const video of videos) {
            if (video['__shaka_player'] || video.shakaPlayer) {
                result.player_instance = 'video.__shaka_player';
                break;
            }
        }
    }

    // Video.js
    if (window.videojs) {
        result.globals_found.push('window.videojs');
        if (!result.library) {
            result.library = 'video.js';
        }
        if (window.videojs.VERSION) {
            result.version = result.version || window.videojs.VERSION;
        }
    }

    // HLS.js
    if (window.Hls) {
        result.globals_found.push('window.Hls');
        if (!result.library) {
            result.library = 'hls.js';
        }
        if (window.Hls.version) {
            result.version = result.version || window.Hls.version;
        }
    }

    // DASH.js
    if (window.dashjs) {
        result.globals_found.push('window.dashjs');
        if (!result.library) {
            result.library = 'dashjs';
        }
        if (window.dashjs.Version) {
            result.version = result.version || window.dashjs.Version;
        }
    }

    // JW Player
    if (window.jwplayer) {
        result.globals_found.push('window.jwplayer');
        if (!result.library) {
            result.library = 'jwplayer';
        }
    }

    // Bitmovin
    if (window.bitmovin) {
        result.globals_found.push('window.bitmovin');
        if (!result.library) {
            result.library = 'bitmovin';
        }
    }

    // FLV.js
    if (window.flvjs) {
        result.globals_found.push('window.flvjs');
        if (!result.library) {
            result.library = 'flv.js';
        }
        if (window.flvjs.version) {
            result.version = result.version || window.flvjs.version;
        }
    }

    // Procurar instância genérica em window.player
    if (window.player && typeof window.player === 'object') {
        result.globals_found.push('window.player');
        if (!result.player_instance) {
            result.player_instance = 'window.player';
        }
    }

    return result;
}
"""

# JavaScript que descobre APIs disponíveis no player
JS_DISCOVER_APIS = """
() => {
    const apis = [];

    // Função auxiliar para inspecionar métodos de um objeto
    function inspectMethods(obj, basePath) {
        if (!obj || typeof obj !== 'object') return;
        const methods = [];
        try {
            // Propriedades próprias e do protótipo
            const props = new Set([
                ...Object.getOwnPropertyNames(obj),
                ...Object.getOwnPropertyNames(Object.getPrototypeOf(obj) || {})
            ]);
            for (const prop of props) {
                try {
                    const isFn = typeof obj[prop] === 'function';
                    if (isFn && !prop.startsWith('_')) {
                        methods.push(prop);
                    }
                } catch (e) {
                    // Ignorar propriedades inacessíveis
                }
            }
        } catch (e) {
            // Ignorar erros de inspeção
        }
        return methods;
    }

    // 1. Inspecionar instância Shaka Player
    if (window.shaka) {
        const videos = document.querySelectorAll('video');
        for (const video of videos) {
            const playerObj = video['__shaka_player'] || video.shakaPlayer;
            if (playerObj) {
                const methods = inspectMethods(playerObj, 'shakaPlayer');
                for (const method of methods) {
                    apis.push({
                        path: `shakaPlayer.${method}`,
                        method: method,
                        source: 'shaka-player-instance',
                        type: 'method'
                    });
                }
                break;
            }
        }
    }

    // 2. Inspecionar window.player genérico
    if (window.player && typeof window.player === 'object') {
        const methods = inspectMethods(window.player, 'window.player');
        for (const method of methods) {
            apis.push({
                path: `window.player.${method}`,
                method: method,
                source: 'window.player',
                type: 'method'
            });
        }
    }

    // 3. Verificar HTMLMediaElement (video)
    const video = document.querySelector('video');
    if (video) {
        // Métodos padrão do HTMLMediaElement
        const mediaMethods = [
            'play', 'pause', 'load', 'canPlayType',
            'addTextTrack', 'requestFullscreen'
        ];
        for (const method of mediaMethods) {
            if (typeof video[method] === 'function') {
                apis.push({
                    path: `video.${method}`,
                    method: method,
                    source: 'HTMLMediaElement',
                    type: 'method'
                });
            }
        }

        // Propriedades relevantes
        const mediaProps = [
            'currentTime', 'duration', 'paused', 'muted',
            'volume', 'playbackRate', 'readyState',
            'videoWidth', 'videoHeight', 'src', 'currentSrc'
        ];
        for (const prop of mediaProps) {
            if (prop in video) {
                apis.push({
                    path: `video.${prop}`,
                    method: prop,
                    source: 'HTMLMediaElement',
                    type: 'property'
                });
            }
        }

        // TextTracks (legendas)
        if (video.textTracks && video.textTracks.length > 0) {
            apis.push({
                path: 'video.textTracks',
                method: 'textTracks',
                source: 'HTMLMediaElement',
                type: 'property',
                details: { count: video.textTracks.length }
            });
        }

        // AudioTracks
        if (video.audioTracks && video.audioTracks.length > 0) {
            apis.push({
                path: 'video.audioTracks',
                method: 'audioTracks',
                source: 'HTMLMediaElement',
                type: 'property',
                details: { count: video.audioTracks.length }
            });
        }

        // getVideoPlaybackQuality
        if (typeof video.getVideoPlaybackQuality === 'function') {
            apis.push({
                path: 'video.getVideoPlaybackQuality',
                method: 'getVideoPlaybackQuality',
                source: 'HTMLMediaElement',
                type: 'method'
            });
        }
    }

    // 4. Inspecionar video.js player
    if (window.videojs) {
        try {
            const players = window.videojs.getPlayers
                ? window.videojs.getPlayers()
                : {};
            const playerIds = Object.keys(players);
            if (playerIds.length > 0) {
                const vjsPlayer = players[playerIds[0]];
                if (vjsPlayer) {
                    const methods = inspectMethods(vjsPlayer, 'videojs');
                    for (const method of methods) {
                        apis.push({
                            path: `videojs.${method}`,
                            method: method,
                            source: 'video.js-instance',
                            type: 'method'
                        });
                    }
                }
            }
        } catch (e) {
            // Ignorar erros de acesso ao video.js
        }
    }

    return apis;
}
"""


class JSAnalyzer:
    """Investiga JavaScript APIs do player.

    Utiliza page.evaluate() do Playwright para executar JavaScript na página
    e descobrir dinamicamente as APIs disponíveis do player, incluindo:
    - Biblioteca e versão
    - APIs de track (áudio, legenda, qualidade)
    - APIs de controle (play, pause, mute)
    - APIs de evento

    Requirements: 1.3
    """

    def __init__(self) -> None:
        """Inicializa o analisador de JavaScript."""
        self._logger = logging.getLogger(
            f"{__name__}.{self.__class__.__name__}"
        )

    async def analyze(self, page: Page) -> list[JSEvidence]:
        """Investiga objetos globais e APIs do player.

        Executa scripts JavaScript na página para detectar:
        1. Biblioteca do player (shaka, videojs, hls.js, dashjs, etc.)
        2. Versão do player
        3. APIs disponíveis (track, quality, audio, subtitle, event)

        Args:
            page: Instância de Page do Playwright

        Returns:
            Lista de JSEvidence com todas as APIs descobertas
        """
        evidences: list[JSEvidence] = []

        # 1. Detectar biblioteca e versão do player
        library_info = await self._detect_player_library(page)
        if library_info.get("library"):
            evidences.append(JSEvidence(
                api_path=f"window.{library_info['library']}",
                capability_hint="player_library",
                confidence_contribution=0.3,
                details={
                    "library": library_info["library"],
                    "version": library_info.get("version"),
                    "player_instance": library_info.get("player_instance"),
                    "globals_found": library_info.get("globals_found", []),
                },
                interaction_hint=InteractionLevel.PLAYER_API,
            ))
            self._logger.info(
                "Biblioteca detectada: %s v%s",
                library_info["library"],
                library_info.get("version", "unknown"),
            )

        # 2. Descobrir APIs disponíveis
        raw_apis = await self._discover_apis(page)
        for api_info in raw_apis:
            method = api_info.get("method", "")
            capability_hint = self._resolve_capability_hint(method)

            if capability_hint:
                confidence = self._calculate_confidence(
                    method, api_info.get("source", "")
                )
                evidences.append(JSEvidence(
                    api_path=api_info.get("path", ""),
                    capability_hint=capability_hint,
                    confidence_contribution=confidence,
                    details={
                        "method": method,
                        "source": api_info.get("source", ""),
                        "type": api_info.get("type", "method"),
                        **api_info.get("details", {}),
                    },
                    interaction_hint=InteractionLevel.PLAYER_API,
                ))

        self._logger.info(
            "Análise JS concluída: %d evidências encontradas",
            len(evidences),
        )
        return evidences

    async def _detect_player_library(self, page: Page) -> dict:
        """Detecta biblioteca e versão do player.

        Executa JavaScript que verifica a existência de objetos globais
        conhecidos (window.shaka, window.videojs, window.Hls, etc.)
        e extrai informações de biblioteca e versão.

        Args:
            page: Instância de Page do Playwright

        Returns:
            Dicionário com library, version, player_instance, globals_found
        """
        try:
            result = await page.evaluate(JS_DETECT_PLAYER_LIBRARY)
            if isinstance(result, dict):
                return result
            return {}
        except Exception as e:
            self._logger.warning(
                "Erro ao detectar biblioteca do player: %s", e
            )
            return {}

    async def _discover_apis(self, page: Page) -> list[dict]:
        """Descobre APIs disponíveis (track, quality, audio, subtitle, event).

        Inspeciona objetos do player e o HTMLMediaElement para encontrar
        métodos e propriedades disponíveis que indicam capabilities do player.

        Args:
            page: Instância de Page do Playwright

        Returns:
            Lista de dicionários com path, method, source, type para cada API
        """
        try:
            result = await page.evaluate(JS_DISCOVER_APIS)
            if isinstance(result, list):
                return result
            return []
        except Exception as e:
            self._logger.warning(
                "Erro ao descobrir APIs do player: %s", e
            )
            return []

    def _resolve_capability_hint(self, method: str) -> str:
        """Resolve qual capability uma API/método representa.

        Usa o mapeamento CAPABILITY_API_MAP para traduzir nomes de métodos
        em hints de capability. Para métodos não mapeados, retorna string
        vazia (indicando que não há hint direto).

        Args:
            method: Nome do método ou propriedade

        Returns:
            Nome da capability associada, ou string vazia se não mapeável
        """
        return CAPABILITY_API_MAP.get(method, "")

    def _calculate_confidence(self, method: str, source: str) -> float:
        """Calcula a contribuição de confidence para uma API descoberta.

        APIs de instâncias específicas do player (shaka, videojs) contribuem
        mais que APIs genéricas do HTMLMediaElement, pois indicam controle
        programático direto.

        Args:
            method: Nome do método descoberto
            source: Fonte da API (ex: "shaka-player-instance",
                    "HTMLMediaElement", "window.player")

        Returns:
            Valor de confidence_contribution entre 0.0 e 1.0
        """
        # APIs de instância de player específico → alta confidence
        if source in (
            "shaka-player-instance",
            "video.js-instance",
        ):
            return 0.4

        # APIs de player genérico → confidence média-alta
        if source == "window.player":
            return 0.3

        # APIs do HTMLMediaElement → confidence média
        # (são padrão, mas nem sempre controlam o player diretamente)
        if source == "HTMLMediaElement":
            # Métodos de controle direto têm mais peso
            if method in ("play", "pause", "requestFullscreen"):
                return 0.25
            # Propriedades informativas têm peso menor
            return 0.15

        # Fonte desconhecida
        return 0.1
