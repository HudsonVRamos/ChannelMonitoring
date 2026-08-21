"""Monitor de áudio do player SKY+.

Valida mudanças de track de áudio via Shaka Player API e coleta
telemetria via Web Audio API (AudioContext + AnalyserNode).

Responsabilidades:
- Validar que a mudança de track via UI foi refletida na API
- Inicializar AudioContext no browser para captura de sinal
- Coletar amostras RMS/peak durante janela de telemetria
- Calcular agregações (média, min, max, ratio de presença)
- Classificar resultado como PASS ou FAIL

Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 10.1
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from .config import AudioSubtitleConfig
from .models import (
    AudioSample,
    AudioTelemetryResult,
    TrackTestStatus,
    ValidationResult,
)

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = logging.getLogger(__name__)


# JavaScript para inicializar AudioContext e conectar ao vídeo
_JS_INIT_AUDIO_CONTEXT = """
() => {
    if (window.__audioMonitorCtx) return true;
    const video = document.querySelector('video');
    if (!video) return false;
    const ctx = new AudioContext();
    const source = ctx.createMediaElementSource(video);
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 2048;
    source.connect(analyser);
    analyser.connect(ctx.destination);
    window.__audioMonitorCtx = ctx;
    window.__audioMonitorAnalyser = analyser;
    return true;
}
"""

# JavaScript para coletar amostra RMS e peak do AnalyserNode
_JS_COLLECT_SAMPLE = """
() => {
    const analyser = window.__audioMonitorAnalyser;
    if (!analyser) return null;
    const data = new Float32Array(analyser.fftSize);
    analyser.getFloatTimeDomainData(data);
    let sum = 0;
    let peak = 0;
    for (let i = 0; i < data.length; i++) {
        sum += data[i] * data[i];
        peak = Math.max(peak, Math.abs(data[i]));
    }
    const rms = Math.sqrt(sum / data.length);
    return { rms, peak };
}
"""


class AudioMonitor:
    """Monitora e valida funcionalidade de áudio.

    Utiliza a Shaka Player API (window.player.getAudioTracks()) para
    validar mudanças de track e a Web Audio API (AudioContext +
    AnalyserNode) para coletar telemetria de presença de áudio.

    Attributes:
        _page: Instância do Playwright Page para interação com o browser
        _config: Configuração com thresholds e timeouts
        _audio_context_initialized: Se o AudioContext foi criado no browser
    """

    def __init__(self, page: Page, config: AudioSubtitleConfig) -> None:
        """Inicializa o AudioMonitor.

        Args:
            page: Instância do Playwright Page
            config: Configuração com thresholds e timeouts de áudio
        """
        self._page = page
        self._config = config
        self._audio_context_initialized = False

    async def validate_track_switch(
        self, expected_language: str, timeout_s: float = 5.0
    ) -> ValidationResult:
        """Verifica via Shaka API que o track ativo mudou.

        Realiza polling com intervalo de 0.5s até o timeout,
        consultando window.player.getAudioTracks() e verificando
        se existe um track com o language esperado marcado como active.

        Args:
            expected_language: Idioma esperado (ex: "por", "eng")
            timeout_s: Tempo máximo de espera em segundos (padrão: 5.0)

        Returns:
            ValidationResult com success=True se track ativo corresponde
            ao idioma esperado, False caso contrário.

        Req 3.2, 10.1: Verificar via Shaka API que o track ativo
        mudou para o idioma selecionado dentro de 5 segundos.
        """
        poll_interval = 0.5
        deadline = time.time() + timeout_s
        tracks: list[dict] = []
        actual_language: str | None = None

        logger.info(
            f"Validando track switch para '{expected_language}' "
            f"(timeout={timeout_s}s)..."
        )

        while time.time() < deadline:
            try:
                tracks = await self.get_active_tracks()
            except Exception as e:
                logger.warning(f"Erro ao consultar audio tracks: {e}")
                await asyncio.sleep(poll_interval)
                continue

            # Procurar track ativo com language correspondente
            for track in tracks:
                if track.get("active"):
                    actual_language = track.get("language")
                    if actual_language == expected_language:
                        logger.info(
                            f"Track switch confirmado: "
                            f"'{expected_language}' ativo."
                        )
                        return ValidationResult(
                            success=True,
                            expected_language=expected_language,
                            actual_active_language=actual_language,
                            api_tracks=tracks,
                        )

            await asyncio.sleep(poll_interval)

        # Timeout atingido sem confirmação
        logger.warning(
            f"Track switch não confirmado para "
            f"'{expected_language}' em {timeout_s}s. "
            f"Track ativo: '{actual_language}'."
        )
        return ValidationResult(
            success=False,
            expected_language=expected_language,
            actual_active_language=actual_language,
            api_tracks=tracks,
            error="track_switch_not_confirmed",
        )

    async def get_active_tracks(self) -> list[dict]:
        """Consulta window.player.getAudioTracks() via Shaka API.

        Returns:
            Lista de dicts representando tracks de áudio,
            cada um com campos como language, active, label, etc.

        Req 10.1: Consultar window.player.getAudioTracks() e verificar
        que o track com o language correspondente está marcado como active.
        """
        result = await self._page.evaluate(
            "() => window.player.getAudioTracks()"
        )
        if result is None:
            logger.warning("getAudioTracks() retornou null.")
            return []
        return result

    async def _init_audio_context(self) -> bool:
        """Inicializa Web Audio API AudioContext no browser.

        Cria um AudioContext, conecta o elemento video a um
        AnalyserNode e armazena referências globais para uso
        nas coletas de amostras.

        Returns:
            True se o AudioContext foi inicializado com sucesso,
            False se falhou (ex: elemento video não encontrado).
        """
        if self._audio_context_initialized:
            return True

        logger.debug("Inicializando AudioContext no browser...")
        try:
            result = await self._page.evaluate(_JS_INIT_AUDIO_CONTEXT)
            if result:
                self._audio_context_initialized = True
                logger.info("AudioContext inicializado com sucesso.")
                return True
            else:
                logger.error(
                    "Falha ao inicializar AudioContext: "
                    "elemento video não encontrado."
                )
                return False
        except Exception as e:
            logger.error(f"Erro ao inicializar AudioContext: {e}")
            return False

    async def _collect_single_sample(self) -> AudioSample:
        """Coleta uma única amostra RMS/peak via Web Audio API.

        Executa JavaScript que lê o buffer do AnalyserNode,
        calcula RMS e peak do sinal de áudio atual.

        Returns:
            AudioSample com timestamp, rms e peak.
            Se a coleta falhar, retorna amostra com rms=0.0, peak=0.0.
        """
        try:
            result = await self._page.evaluate(_JS_COLLECT_SAMPLE)
            if result is None:
                logger.warning(
                    "Coleta de amostra retornou null "
                    "(AnalyserNode não disponível)."
                )
                return AudioSample(
                    timestamp=time.time(), rms=0.0, peak=0.0
                )
            return AudioSample(
                timestamp=time.time(),
                rms=result["rms"],
                peak=result["peak"],
            )
        except Exception as e:
            logger.warning(f"Erro ao coletar amostra de áudio: {e}")
            return AudioSample(
                timestamp=time.time(), rms=0.0, peak=0.0
            )

    async def collect_telemetry(
        self,
        duration_s: float = 30.0,
        sample_interval_s: float = 2.0,
    ) -> AudioTelemetryResult:
        """Coleta telemetria de áudio durante a janela especificada.

        Inicializa o AudioContext (se necessário), coleta amostras
        em intervalos regulares durante duration_s e calcula
        agregações estatísticas.

        Args:
            duration_s: Duração total da coleta em segundos
                (padrão: 30.0)
            sample_interval_s: Intervalo entre amostras em segundos
                (padrão: 2.0)

        Returns:
            AudioTelemetryResult com amostras e agregações calculadas.

        Req 3.3: Coletar telemetria durante Audio_Telemetry_Window de 30s,
        registrando RMS médio, RMS mínimo, RMS máximo, presença de áudio
        e duração de silêncio.
        """
        logger.info(
            f"Iniciando coleta de telemetria: "
            f"duration={duration_s}s, interval={sample_interval_s}s"
        )

        # Inicializar AudioContext se necessário
        if not await self._init_audio_context():
            logger.error("Não foi possível inicializar AudioContext.")
            return AudioTelemetryResult(
                samples=[],
                rms_avg=0.0,
                rms_min=0.0,
                rms_max=0.0,
                audio_present_ratio=0.0,
                silence_duration_s=duration_s,
                total_duration_s=duration_s,
            )

        # Coletar amostras durante a janela
        samples: list[AudioSample] = []
        start_time = time.time()
        elapsed = 0.0

        while elapsed < duration_s:
            sample = await self._collect_single_sample()
            samples.append(sample)
            elapsed = time.time() - start_time

            # Aguardar intervalo (mas não ultrapassar duration)
            remaining = duration_s - elapsed
            if remaining > 0:
                wait_time = min(sample_interval_s, remaining)
                await asyncio.sleep(wait_time)
                elapsed = time.time() - start_time

        # Calcular agregações
        telemetry = self._calculate_aggregations(
            samples, sample_interval_s, duration_s
        )

        logger.info(
            f"Telemetria coletada: {len(samples)} amostras, "
            f"rms_avg={telemetry.rms_avg:.4f}, "
            f"audio_present_ratio={telemetry.audio_present_ratio:.2f}"
        )

        return telemetry

    def _calculate_aggregations(
        self,
        samples: list[AudioSample],
        sample_interval_s: float,
        total_duration_s: float,
    ) -> AudioTelemetryResult:
        """Calcula agregações estatísticas a partir das amostras.

        Args:
            samples: Lista de amostras coletadas
            sample_interval_s: Intervalo entre amostras
                (para cálculo de silêncio)
            total_duration_s: Duração total da janela de coleta

        Returns:
            AudioTelemetryResult com todas as agregações calculadas.
        """
        if not samples:
            return AudioTelemetryResult(
                samples=[],
                rms_avg=0.0,
                rms_min=0.0,
                rms_max=0.0,
                audio_present_ratio=0.0,
                silence_duration_s=total_duration_s,
                total_duration_s=total_duration_s,
            )

        rms_values = [s.rms for s in samples]
        threshold = self._config.audio_rms_threshold

        rms_avg = sum(rms_values) / len(rms_values)
        rms_min = min(rms_values)
        rms_max = max(rms_values)

        # Contar amostras com áudio presente (RMS > threshold)
        audio_present_count = sum(
            1 for rms in rms_values if rms > threshold
        )
        audio_present_ratio = audio_present_count / len(rms_values)

        # Duração de silêncio = amostras sem áudio * intervalo
        silence_count = len(rms_values) - audio_present_count
        silence_duration_s = silence_count * sample_interval_s

        return AudioTelemetryResult(
            samples=samples,
            rms_avg=rms_avg,
            rms_min=rms_min,
            rms_max=rms_max,
            audio_present_ratio=audio_present_ratio,
            silence_duration_s=silence_duration_s,
            total_duration_s=total_duration_s,
        )

    def classify_result(
        self, telemetry: AudioTelemetryResult
    ) -> TrackTestStatus:
        """Classifica resultado: PASS se >=80% amostras com RMS > threshold.

        Args:
            telemetry: Resultado da coleta de telemetria de áudio.

        Returns:
            TrackTestStatus.PASS se audio_present_ratio >=
            audio_pass_threshold,
            TrackTestStatus.FAIL caso contrário.

        Req 3.4: Classificar como PASS se áudio detectado em pelo menos
        80% das amostras coletadas.
        Req 3.5: Classificar como FAIL se áudio não detectado em mais de
        20% das amostras.
        """
        if telemetry.audio_present_ratio >= self._config.audio_pass_threshold:
            logger.info(
                f"Classificação: PASS "
                f"(ratio={telemetry.audio_present_ratio:.2f} "
                f">= {self._config.audio_pass_threshold})"
            )
            return TrackTestStatus.PASS

        logger.info(
            f"Classificação: FAIL "
            f"(ratio={telemetry.audio_present_ratio:.2f} "
            f"< {self._config.audio_pass_threshold})"
        )
        return TrackTestStatus.FAIL
