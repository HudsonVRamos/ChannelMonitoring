"""Testes comportamentais seguros para confirmar capabilities do player.

Executa testes não-destrutivos para confirmar que capabilities detectadas
pelo DOM/JS/Browser analyzers realmente funcionam. Cada teste segue o
padrão: observar estado → interação controlada via API → verificar mudança
→ restaurar estado original.

Testes implementados (todos SAFE — non-destructive):
- play/pause: Verifica se video.paused muda via API
- mute/unmute: Verifica se video.muted muda via API
- fullscreen: Verifica disponibilidade da Fullscreen API
- subtitle_selection: Verifica se textTracks são acessíveis
- audio_selection: Verifica se audioTracks são acessíveis
- quality_selection: Verifica se variant tracks API responde
- settings: Verifica se painel de configurações pode ser detectado

Requirements: 1.6
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from playwright.async_api import Page

logger = logging.getLogger(__name__)


@dataclass
class BehavioralTestResult:
    """Resultado de um teste comportamental.

    Attributes:
        capability: Nome da capability testada
        confirmed: Se o teste confirmou a capability
        confidence_boost: Boost de confidence se confirmado (0.0-0.3)
        observation: O que foi observado durante o teste
        duration_ms: Duração do teste em milissegundos
    """

    capability: str
    confirmed: bool
    confidence_boost: float
    observation: str
    duration_ms: int


# JavaScript para testar play/pause via API (não clica em nada)
_TEST_PLAY_PAUSE_JS = """
async () => {
    const video = document.querySelector('video');
    if (!video) return { confirmed: false, observation: 'Nenhum elemento video encontrado' };

    const originalPaused = video.paused;

    try {
        if (originalPaused) {
            // Tentar dar play via API
            await video.play();
            const changed = !video.paused;
            // Restaurar estado original
            video.pause();
            return {
                confirmed: changed,
                observation: changed
                    ? 'play() via API mudou paused de true para false — restaurado'
                    : 'play() via API não alterou estado paused'
            };
        } else {
            // Vídeo está tocando — testar pause
            video.pause();
            const changed = video.paused;
            // Restaurar estado original
            await video.play();
            return {
                confirmed: changed,
                observation: changed
                    ? 'pause() via API mudou paused de false para true — restaurado'
                    : 'pause() via API não alterou estado paused'
            };
        }
    } catch (err) {
        return {
            confirmed: false,
            observation: 'Erro ao testar play/pause: ' + err.message
        };
    }
}
"""

# JavaScript para testar mute/unmute via API
_TEST_MUTE_UNMUTE_JS = """
() => {
    const video = document.querySelector('video');
    if (!video) return { confirmed: false, observation: 'Nenhum elemento video encontrado' };

    const originalMuted = video.muted;

    try {
        // Alternar muted via propriedade
        video.muted = !originalMuted;
        const changed = video.muted !== originalMuted;

        // Restaurar estado original
        video.muted = originalMuted;

        return {
            confirmed: changed,
            observation: changed
                ? 'video.muted alterou de ' + originalMuted + ' para ' + !originalMuted + ' — restaurado'
                : 'video.muted não respondeu à alteração via API'
        };
    } catch (err) {
        return {
            confirmed: false,
            observation: 'Erro ao testar mute/unmute: ' + err.message
        };
    }
}
"""

# JavaScript para testar Fullscreen API (apenas verifica disponibilidade)
_TEST_FULLSCREEN_JS = """
() => {
    const video = document.querySelector('video');
    if (!video) return { confirmed: false, observation: 'Nenhum elemento video encontrado' };

    try {
        const hasRequestFullscreen = typeof video.requestFullscreen === 'function'
            || typeof video.webkitRequestFullscreen === 'function'
            || typeof video.mozRequestFullScreen === 'function';

        const hasExitFullscreen = typeof document.exitFullscreen === 'function'
            || typeof document.webkitExitFullscreen === 'function'
            || typeof document.mozCancelFullScreen === 'function';

        const fullscreenEnabled = document.fullscreenEnabled
            || document.webkitFullscreenEnabled
            || document.mozFullScreenEnabled
            || false;

        const confirmed = hasRequestFullscreen && hasExitFullscreen && fullscreenEnabled;

        return {
            confirmed: confirmed,
            observation: confirmed
                ? 'Fullscreen API disponível: requestFullscreen=' + hasRequestFullscreen
                    + ', exitFullscreen=' + hasExitFullscreen + ', enabled=' + fullscreenEnabled
                : 'Fullscreen API parcialmente indisponível: requestFullscreen='
                    + hasRequestFullscreen + ', exitFullscreen=' + hasExitFullscreen
                    + ', enabled=' + fullscreenEnabled
        };
    } catch (err) {
        return {
            confirmed: false,
            observation: 'Erro ao verificar Fullscreen API: ' + err.message
        };
    }
}
"""

# JavaScript para testar acesso a textTracks (legendas)
_TEST_SUBTITLE_JS = """
() => {
    const video = document.querySelector('video');
    if (!video) return { confirmed: false, observation: 'Nenhum elemento video encontrado' };

    try {
        const hasTextTracks = typeof video.textTracks !== 'undefined' && video.textTracks !== null;

        if (!hasTextTracks) {
            return {
                confirmed: false,
                observation: 'video.textTracks não está definido'
            };
        }

        const trackCount = video.textTracks.length;
        const tracks = Array.from(video.textTracks).map(t => ({
            kind: t.kind,
            language: t.language,
            label: t.label,
            mode: t.mode
        }));

        const confirmed = trackCount > 0;
        return {
            confirmed: confirmed,
            observation: confirmed
                ? 'textTracks acessíveis: ' + trackCount + ' tracks encontradas — '
                    + JSON.stringify(tracks.slice(0, 3))
                : 'textTracks acessível mas vazio (0 tracks)'
        };
    } catch (err) {
        return {
            confirmed: false,
            observation: 'Erro ao acessar textTracks: ' + err.message
        };
    }
}
"""

# JavaScript para testar acesso a audioTracks
_TEST_AUDIO_SELECTION_JS = """
() => {
    const video = document.querySelector('video');
    if (!video) return { confirmed: false, observation: 'Nenhum elemento video encontrado' };

    try {
        const hasAudioTracks = typeof video.audioTracks !== 'undefined'
            && video.audioTracks !== null;

        if (!hasAudioTracks) {
            return {
                confirmed: false,
                observation: 'video.audioTracks não está definido (API não suportada pelo browser)'
            };
        }

        const trackCount = video.audioTracks.length;
        const tracks = Array.from(video.audioTracks).map(t => ({
            id: t.id,
            language: t.language,
            label: t.label,
            enabled: t.enabled
        }));

        const confirmed = trackCount > 0;
        return {
            confirmed: confirmed,
            observation: confirmed
                ? 'audioTracks acessíveis: ' + trackCount + ' tracks — '
                    + JSON.stringify(tracks.slice(0, 3))
                : 'audioTracks acessível mas vazio (0 tracks)'
        };
    } catch (err) {
        return {
            confirmed: false,
            observation: 'Erro ao acessar audioTracks: ' + err.message
        };
    }
}
"""

# JavaScript para testar quality/variant tracks (via player APIs comuns)
_TEST_QUALITY_JS = """
() => {
    const video = document.querySelector('video');
    if (!video) return { confirmed: false, observation: 'Nenhum elemento video encontrado' };

    try {
        // Verifica APIs comuns de players de vídeo para quality selection
        // Shaka Player
        const shakaPlayer = window.shakaPlayer || window.player;
        if (shakaPlayer && typeof shakaPlayer.getVariantTracks === 'function') {
            const tracks = shakaPlayer.getVariantTracks();
            return {
                confirmed: tracks.length > 0,
                observation: 'Shaka Player: getVariantTracks() retornou ' + tracks.length + ' tracks'
            };
        }

        // Video.js
        const videojs = window.videojs;
        if (videojs) {
            const players = videojs.getAllPlayers ? videojs.getAllPlayers() : [];
            if (players.length > 0 && players[0].qualityLevels) {
                const levels = players[0].qualityLevels();
                return {
                    confirmed: levels.length > 0,
                    observation: 'Video.js: qualityLevels retornou ' + levels.length + ' níveis'
                };
            }
        }

        // HLS.js
        const hls = window.hls || window.Hls;
        if (hls && hls.levels) {
            return {
                confirmed: hls.levels.length > 0,
                observation: 'HLS.js: ' + hls.levels.length + ' quality levels disponíveis'
            };
        }

        // DASH.js
        const dashPlayer = window.dashPlayer || window.player;
        if (dashPlayer && typeof dashPlayer.getBitrateInfoListFor === 'function') {
            const bitrates = dashPlayer.getBitrateInfoListFor('video');
            return {
                confirmed: bitrates.length > 0,
                observation: 'DASH.js: ' + bitrates.length + ' bitrates disponíveis'
            };
        }

        // MediaSource Extensions — verifica se há SourceBuffers ativos
        if (video.mediaKeys || (video.srcObject && video.srcObject instanceof MediaSource)) {
            return {
                confirmed: true,
                observation: 'MediaSource/EME detectado — quality selection provável via player API'
            };
        }

        // Fallback: verificar se o vídeo tem resolução que sugere streaming adaptativo
        if (video.videoWidth > 0 && video.videoHeight > 0) {
            return {
                confirmed: false,
                observation: 'Nenhuma API de quality encontrada. Vídeo '
                    + video.videoWidth + 'x' + video.videoHeight
                    + ' — quality selection pode não estar disponível via API'
            };
        }

        return {
            confirmed: false,
            observation: 'Nenhuma API de quality/variant tracks detectada'
        };
    } catch (err) {
        return {
            confirmed: false,
            observation: 'Erro ao verificar quality APIs: ' + err.message
        };
    }
}
"""

# JavaScript para testar detecção de painel de settings
_TEST_SETTINGS_JS = """
() => {
    const video = document.querySelector('video');
    if (!video) return { confirmed: false, observation: 'Nenhum elemento video encontrado' };

    try {
        // Busca elementos que indicam settings/configurações
        const settingsSelectors = [
            '[aria-label*="settings" i]',
            '[aria-label*="configurações" i]',
            '[aria-label*="configuracoes" i]',
            '[aria-label*="config" i]',
            '[role="menu"]',
            '[aria-haspopup="true"]',
            '[data-testid*="settings" i]',
            '[title*="settings" i]',
            '[title*="configurações" i]',
        ];

        let foundElements = [];
        for (const selector of settingsSelectors) {
            const elements = document.querySelectorAll(selector);
            for (const el of elements) {
                // Verificar se está próximo do player (dentro do container do vídeo)
                const videoParent = video.closest('[class*="player"]')
                    || video.parentElement?.parentElement?.parentElement
                    || document.body;

                if (videoParent.contains(el)) {
                    foundElements.push({
                        selector: selector,
                        tag: el.tagName.toLowerCase(),
                        aria_label: el.getAttribute('aria-label') || '',
                        title: el.getAttribute('title') || '',
                        role: el.getAttribute('role') || ''
                    });
                }
            }
        }

        const confirmed = foundElements.length > 0;
        return {
            confirmed: confirmed,
            observation: confirmed
                ? 'Painel de settings detectado: ' + foundElements.length
                    + ' elementos — ' + JSON.stringify(foundElements.slice(0, 3))
                : 'Nenhum painel de settings detectado via semântica DOM'
        };
    } catch (err) {
        return {
            confirmed: false,
            observation: 'Erro ao detectar settings: ' + err.message
        };
    }
}
"""


# Mapeamento de capabilities para seus scripts de teste
_TEST_SCRIPTS: Dict[str, str] = {
    "play": _TEST_PLAY_PAUSE_JS,
    "pause": _TEST_PLAY_PAUSE_JS,
    "mute": _TEST_MUTE_UNMUTE_JS,
    "unmute": _TEST_MUTE_UNMUTE_JS,
    "fullscreen": _TEST_FULLSCREEN_JS,
    "subtitle_selection": _TEST_SUBTITLE_JS,
    "audio_selection": _TEST_AUDIO_SELECTION_JS,
    "quality_selection": _TEST_QUALITY_JS,
    "settings": _TEST_SETTINGS_JS,
}

# Confidence boost por tipo de teste quando confirmado
_CONFIDENCE_BOOSTS: Dict[str, float] = {
    "play": 0.25,
    "pause": 0.25,
    "mute": 0.20,
    "unmute": 0.20,
    "fullscreen": 0.15,
    "subtitle_selection": 0.20,
    "audio_selection": 0.20,
    "quality_selection": 0.15,
    "settings": 0.10,
}


class BehavioralTester:
    """Executa testes comportamentais seguros para confirmar capabilities.

    Cada teste segue o padrão:
    1. Observar estado atual (via API, sem interação visual)
    2. Executar interação controlada (via API do player, não via clique)
    3. Verificar se o estado mudou conforme esperado
    4. Restaurar estado original

    Todos os testes são non-destructive — não alteram permanentemente
    o estado do player.
    """

    # Timeout padrão para execução de cada teste (ms)
    DEFAULT_TIMEOUT_MS: int = 5000

    async def test_capability(
        self,
        page: Page,
        capability: str,
        evidence: Optional[List[str]] = None,
    ) -> BehavioralTestResult:
        """Executa teste comportamental seguro para confirmar capability.

        Pattern: interação controlada → observação do resultado →
        confirmação via API/DOM.

        Args:
            page: Instância do Playwright Page para executar JS.
            capability: Nome da capability a testar
                (ex: "play", "mute", "subtitle_selection").
            evidence: Lista de evidências já coletadas (opcional,
                usada para logging).

        Returns:
            BehavioralTestResult com o resultado do teste.
        """
        start_time = time.perf_counter()

        # Verificar se temos um script de teste para esta capability
        test_script = _TEST_SCRIPTS.get(capability)
        if test_script is None:
            duration_ms = int(
                (time.perf_counter() - start_time) * 1000
            )
            logger.warning(
                "Nenhum teste comportamental definido para "
                "capability '%s'",
                capability,
            )
            return BehavioralTestResult(
                capability=capability,
                confirmed=False,
                confidence_boost=0.0,
                observation=f"Nenhum teste comportamental definido "
                f"para '{capability}'",
                duration_ms=duration_ms,
            )

        try:
            result = await page.evaluate(test_script)
        except Exception as e:
            duration_ms = int(
                (time.perf_counter() - start_time) * 1000
            )
            logger.error(
                "Erro ao executar teste comportamental para "
                "'%s': %s",
                capability,
                str(e),
            )
            return BehavioralTestResult(
                capability=capability,
                confirmed=False,
                confidence_boost=0.0,
                observation=f"Erro na execução: {str(e)}",
                duration_ms=duration_ms,
            )

        duration_ms = int(
            (time.perf_counter() - start_time) * 1000
        )

        confirmed = result.get("confirmed", False)
        observation = result.get("observation", "Sem observação")

        # Calcular boost de confidence baseado na confirmação
        confidence_boost = 0.0
        if confirmed:
            confidence_boost = _CONFIDENCE_BOOSTS.get(
                capability, 0.1
            )

        logger.info(
            "Teste comportamental '%s': confirmed=%s, "
            "boost=%.2f, duration=%dms",
            capability,
            confirmed,
            confidence_boost,
            duration_ms,
        )

        return BehavioralTestResult(
            capability=capability,
            confirmed=confirmed,
            confidence_boost=confidence_boost,
            observation=observation,
            duration_ms=duration_ms,
        )

    async def test_all_capabilities(
        self,
        page: Page,
        capabilities: Optional[List[str]] = None,
    ) -> List[BehavioralTestResult]:
        """Executa testes comportamentais para múltiplas capabilities.

        Args:
            page: Instância do Playwright Page.
            capabilities: Lista de capabilities a testar. Se None,
                testa todas as capabilities conhecidas.

        Returns:
            Lista de BehavioralTestResult, um para cada capability.
        """
        if capabilities is None:
            capabilities = list(_TEST_SCRIPTS.keys())

        # Remover duplicados preservando ordem
        seen: Set[str] = set()
        unique_capabilities: List[str] = []
        for cap in capabilities:
            if cap not in seen:
                seen.add(cap)
                unique_capabilities.append(cap)

        results: List[BehavioralTestResult] = []
        for capability in unique_capabilities:
            result = await self.test_capability(
                page, capability
            )
            results.append(result)

        confirmed_count = sum(
            1 for r in results if r.confirmed
        )
        logger.info(
            "Testes comportamentais concluídos: %d/%d "
            "confirmados",
            confirmed_count,
            len(results),
        )

        return results

    @staticmethod
    def get_supported_capabilities() -> List[str]:
        """Retorna lista de capabilities que possuem testes comportamentais.

        Returns:
            Lista de nomes de capabilities suportadas.
        """
        # Retornar capabilities únicas (play e pause usam o mesmo script)
        return list(_TEST_SCRIPTS.keys())
