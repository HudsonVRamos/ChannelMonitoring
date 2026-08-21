"""HealthScoreCalculator — Cálculo de scores compostos de saúde.

Calcula Video Health Score, Audio Health Score e Functional Health Score
com base na telemetria coletada e nos resultados de testes funcionais.

Scores são utilizados exclusivamente para tendência e priorização —
estados objetivos (PASS/FAIL, erro específico) têm precedência sobre
scores numéricos para decisões de alerta.

Requirements: 13.1, 13.2, 13.3, 13.4
"""

from ..models.enums import FunctionalTestStatus
from ..models.results import FunctionalTestResult
from ..models.telemetry import AudioTelemetry, VideoTelemetry


def _clamp(value: float) -> float:
    """Garante que o score está bounded em [0, 100]."""
    return max(0.0, min(100.0, value))


class HealthScoreCalculator:
    """Calcula Health Scores compostos para canais.

    Cada método retorna um score entre 0 e 100, onde:
    - 100 = saúde perfeita
    - 0 = saúde crítica

    Os pesos de cada componente são fixos e definidos nos requisitos.
    """

    def calculate_video_health(self, telemetry: VideoTelemetry) -> float:
        """Calcula Video Health Score (0-100).

        Pesos:
        - Playback 20%: vídeo reproduzindo sem erros
        - Buffer 15%: buffer adequado à frente
        - Dropped Frames 15%: baixa taxa de drop_rate
        - Freeze 10%: sem freeze detectado
        - FPS 10%: FPS estável em torno de 25-30
        - Resolution 10%: resolução esperada (1080p ideal)
        - DRM 20%: sem erros de DRM

        Args:
            telemetry: Telemetria de vídeo coletada pela VideoProbe

        Returns:
            Score de 0 a 100 (bounded)
        """
        # Playback 20%: vídeo playing, sem erro, não pausado/ended
        playback_score = self._calc_playback_score(telemetry)

        # Buffer 15%: buffer_ahead adequado (ideal >= 10s)
        buffer_score = self._calc_buffer_score(telemetry)

        # Dropped Frames 15%: drop_rate baixo (ideal = 0)
        dropped_score = self._calc_dropped_frames_score(telemetry)

        # Freeze 10%: currentTime avançando (playing e não seeking)
        freeze_score = self._calc_freeze_score(telemetry)

        # FPS 10%: FPS médio estável (ideal 25-30)
        fps_score = self._calc_fps_score(telemetry)

        # Resolution 10%: resolução (ideal 1080p = 1920x1080)
        resolution_score = self._calc_resolution_score(telemetry)

        # DRM 20%: sem erros (error == None)
        drm_score = self._calc_drm_score(telemetry)

        total = (
            playback_score * 0.20
            + buffer_score * 0.15
            + dropped_score * 0.15
            + freeze_score * 0.10
            + fps_score * 0.10
            + resolution_score * 0.10
            + drm_score * 0.20
        )

        return _clamp(total)

    def calculate_audio_health(self, telemetry: AudioTelemetry) -> float:
        """Calcula Audio Health Score (0-100).

        Pesos:
        - Audio present 40%: RMS > threshold, sem silêncio
        - RMS 20%: bom nível de RMS
        - Peak 10%: bom nível de peak
        - Silence 20%: sem silêncio detectado
        - Track 10%: tracks de áudio disponíveis

        Args:
            telemetry: Telemetria de áudio coletada pela AudioProbe

        Returns:
            Score de 0 a 100 (bounded)
        """
        # Audio present 40%: RMS acima de threshold, não mutado
        audio_present_score = self._calc_audio_present_score(telemetry)

        # RMS 20%: nível de RMS bom (ideal >= 0.1)
        rms_score = self._calc_rms_score(telemetry)

        # Peak 10%: nível de peak bom (ideal >= 0.2)
        peak_score = self._calc_peak_score(telemetry)

        # Silence 20%: pouco ou nenhum silêncio acumulado
        silence_score = self._calc_silence_score(telemetry)

        # Track 10%: tracks de áudio disponíveis (pelo menos 1)
        track_score = self._calc_track_score(telemetry)

        total = (
            audio_present_score * 0.40
            + rms_score * 0.20
            + peak_score * 0.10
            + silence_score * 0.20
            + track_score * 0.10
        )

        return _clamp(total)

    def calculate_functional_health(
        self, results: list[FunctionalTestResult]
    ) -> float:
        """Calcula Functional Health Score (0-100).

        Pesos iguais de 25% por capability testada:
        - Play/Pause 25%
        - Audio selection 25%
        - Subtitle selection 25%
        - Quality selection 25%

        Capabilities com status SKIPPED são ignoradas — somente
        capabilities efetivamente testadas contribuem para o score.

        Args:
            results: Lista de resultados de testes funcionais

        Returns:
            Score de 0 a 100 (bounded)
        """
        # Filtrar resultados que não foram SKIPPED
        tested = [
            r for r in results
            if r.status != FunctionalTestStatus.SKIPPED
        ]

        if not tested:
            # Sem testes executados, retorna 0
            return 0.0

        # Calcular proporção de PASS entre os testados
        passed = sum(
            1 for r in tested
            if r.status == FunctionalTestStatus.PASS
        )

        score = (passed / len(tested)) * 100.0

        return _clamp(score)

    # --- Métodos auxiliares para Video Health ---

    def _calc_playback_score(self, telemetry: VideoTelemetry) -> float:
        """Score de playback (0-100): vídeo playing sem erros."""
        score = 100.0

        if telemetry.error is not None:
            score -= 80.0

        if telemetry.paused and not telemetry.ended:
            score -= 50.0

        if not telemetry.playing and not telemetry.ended:
            score -= 30.0

        if telemetry.ended:
            score -= 20.0

        return max(0.0, score)

    def _calc_buffer_score(self, telemetry: VideoTelemetry) -> float:
        """Score de buffer (0-100): buffer adequado à frente.

        Ideal: >= 10s de buffer. Abaixo de 2s é crítico.
        """
        buffer = telemetry.buffered_seconds

        if buffer >= 10.0:
            return 100.0
        elif buffer >= 5.0:
            # Interpolação linear entre 5s (70) e 10s (100)
            return 70.0 + (buffer - 5.0) * 6.0
        elif buffer >= 2.0:
            # Interpolação linear entre 2s (30) e 5s (70)
            return 30.0 + (buffer - 2.0) * (40.0 / 3.0)
        else:
            # Interpolação linear entre 0s (0) e 2s (30)
            return buffer * 15.0

    def _calc_dropped_frames_score(
        self, telemetry: VideoTelemetry
    ) -> float:
        """Score de dropped frames (0-100): baixo drop_rate.

        Ideal: 0% drop. Acima de 5% é crítico.
        """
        if telemetry.drop_rate is None:
            # Sem informação de frames, assumir OK
            return 100.0

        drop = telemetry.drop_rate

        if drop <= 0.0:
            return 100.0
        elif drop <= 0.01:
            # Até 1%: score entre 80-100
            return 100.0 - (drop / 0.01) * 20.0
        elif drop <= 0.05:
            # 1% a 5%: score entre 20-80
            return 80.0 - ((drop - 0.01) / 0.04) * 60.0
        else:
            # Acima de 5%: score entre 0-20
            return max(0.0, 20.0 - ((drop - 0.05) / 0.05) * 20.0)

    def _calc_freeze_score(self, telemetry: VideoTelemetry) -> float:
        """Score de freeze (0-100): sem freeze detectado.

        Vídeo playing e não fazendo seeking indica sem freeze.
        """
        if telemetry.playing and not telemetry.seeking:
            return 100.0
        elif telemetry.paused or telemetry.ended:
            # Pausado/ended não é freeze, mas não é ideal
            return 50.0
        elif telemetry.seeking:
            # Seeking é transitório
            return 70.0
        else:
            # Não playing, não pausado, não ended = possível freeze
            return 0.0

    def _calc_fps_score(self, telemetry: VideoTelemetry) -> float:
        """Score de FPS (0-100): FPS estável em torno de 25-30.

        Ideal: 25-30 FPS. Abaixo de 15 é crítico.
        """
        if telemetry.fps_avg is None:
            # Sem informação de FPS, assumir OK
            return 100.0

        fps = telemetry.fps_avg

        if 25.0 <= fps <= 30.0:
            return 100.0
        elif 20.0 <= fps < 25.0:
            # Interpolação entre 20 (70) e 25 (100)
            return 70.0 + (fps - 20.0) * 6.0
        elif fps > 30.0:
            # Acima de 30 pode indicar conteúdo 60fps, OK
            return 100.0
        elif 15.0 <= fps < 20.0:
            # Interpolação entre 15 (30) e 20 (70)
            return 30.0 + (fps - 15.0) * 8.0
        else:
            # Abaixo de 15 FPS: score proporcional
            return max(0.0, (fps / 15.0) * 30.0)

    def _calc_resolution_score(self, telemetry: VideoTelemetry) -> float:
        """Score de resolução (0-100): resolução esperada.

        Ideal: 1080p (1920x1080). 720p é aceitável.
        """
        height = telemetry.video_height

        if height >= 1080:
            return 100.0
        elif height >= 720:
            # Interpolação entre 720 (70) e 1080 (100)
            return 70.0 + ((height - 720) / 360.0) * 30.0
        elif height >= 480:
            # Interpolação entre 480 (40) e 720 (70)
            return 40.0 + ((height - 480) / 240.0) * 30.0
        elif height > 0:
            # Abaixo de 480: score proporcional
            return (height / 480.0) * 40.0
        else:
            # Resolução 0 = sem vídeo
            return 0.0

    def _calc_drm_score(self, telemetry: VideoTelemetry) -> float:
        """Score de DRM (0-100): sem erros de DRM.

        Sem erro = 100, com erro = 0.
        """
        if telemetry.error is None:
            return 100.0
        return 0.0

    # --- Métodos auxiliares para Audio Health ---

    def _calc_audio_present_score(
        self, telemetry: AudioTelemetry
    ) -> float:
        """Score de audio present (0-100): RMS acima de threshold.

        Verifica se há áudio presente e não mutado.
        """
        if telemetry.muted:
            return 0.0

        if telemetry.rms is None:
            return 0.0

        # RMS > 0.01 indica áudio presente
        if telemetry.rms >= 0.05:
            return 100.0
        elif telemetry.rms >= 0.01:
            # Interpolação entre 0.01 (50) e 0.05 (100)
            return 50.0 + ((telemetry.rms - 0.01) / 0.04) * 50.0
        else:
            # RMS muito baixo — quase sem áudio
            return (telemetry.rms / 0.01) * 50.0

    def _calc_rms_score(self, telemetry: AudioTelemetry) -> float:
        """Score de RMS (0-100): bom nível de RMS.

        Ideal: RMS >= 0.1
        """
        if telemetry.rms is None:
            return 0.0

        rms = telemetry.rms

        if rms >= 0.1:
            return 100.0
        elif rms >= 0.05:
            # Interpolação entre 0.05 (60) e 0.1 (100)
            return 60.0 + ((rms - 0.05) / 0.05) * 40.0
        elif rms >= 0.01:
            # Interpolação entre 0.01 (20) e 0.05 (60)
            return 20.0 + ((rms - 0.01) / 0.04) * 40.0
        else:
            # RMS muito baixo
            return (rms / 0.01) * 20.0

    def _calc_peak_score(self, telemetry: AudioTelemetry) -> float:
        """Score de peak (0-100): bom nível de peak.

        Ideal: peak >= 0.2
        """
        if telemetry.peak is None:
            return 0.0

        peak = telemetry.peak

        if peak >= 0.2:
            return 100.0
        elif peak >= 0.1:
            # Interpolação entre 0.1 (50) e 0.2 (100)
            return 50.0 + ((peak - 0.1) / 0.1) * 50.0
        elif peak > 0.0:
            # Interpolação entre 0 (0) e 0.1 (50)
            return (peak / 0.1) * 50.0
        else:
            return 0.0

    def _calc_silence_score(self, telemetry: AudioTelemetry) -> float:
        """Score de silence (0-100): sem silêncio detectado.

        Ideal: silence_duration = 0. Acima de 10s é crítico.
        """
        silence = telemetry.silence_duration

        if silence <= 0.0:
            return 100.0
        elif silence <= 2.0:
            # Até 2s de silêncio: score entre 80-100
            return 100.0 - (silence / 2.0) * 20.0
        elif silence <= 5.0:
            # 2s a 5s: score entre 50-80
            return 80.0 - ((silence - 2.0) / 3.0) * 30.0
        elif silence <= 10.0:
            # 5s a 10s: score entre 20-50
            return 50.0 - ((silence - 5.0) / 5.0) * 30.0
        else:
            # Acima de 10s: score entre 0-20
            return max(0.0, 20.0 - ((silence - 10.0) / 10.0) * 20.0)

    def _calc_track_score(self, telemetry: AudioTelemetry) -> float:
        """Score de tracks (0-100): tracks de áudio disponíveis.

        Ideal: pelo menos 1 track disponível.
        """
        num_tracks = len(telemetry.tracks_available)

        if num_tracks >= 2:
            return 100.0
        elif num_tracks == 1:
            return 80.0
        else:
            return 0.0
