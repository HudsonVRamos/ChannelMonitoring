"""Orquestrador principal da PoC de validação Widevine DRM.

Executa todas as validações em sequência, respeitando a cadeia
de dependências entre etapas. Se uma etapa crítica falha, etapas
dependentes são marcadas como SKIPPED.

Cadeia de dependências:
  Auth → DRM → Playback/Telemetry → Frames → OpenCV → Bedrock

Referências: Requirements 2.2, 9.1, 9.3, 10.8, 11.4, 11.6
"""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone
from typing import Optional

from playwright.async_api import (
    Page,
    Browser,
    BrowserContext,
    async_playwright,
)

from src.auth_manager import AuthManager
from src.bedrock_client import BedrockClient
from src.buffering_detector import BufferingDetector
from src.config import PoCConfig
from src.drm_validator import DRMValidator
from src.frame_capturer import FrameCapturer
from src.models import (
    PoCReport,
    ValidationResult,
    ValidationStatus,
)
from src.opencv_analyzer import OpenCVAnalyzer
from src.report_generator import ReportGenerator
from src.structured_logger import StructuredLogger
from src.telemetry_collector import TelemetryCollector


STAGE_ID = "poc_orchestrator"


class PoCOrchestrator:
    """Orquestra a execução completa da PoC.

    Executa as validações em sequência respeitando dependências:
    Auth → DRM → Telemetry → Frames → OpenCV → Bedrock.

    Se uma etapa crítica falha, etapas dependentes são
    marcadas como SKIPPED com motivo indicando a dependência.
    """

    def __init__(self, config: PoCConfig) -> None:
        """Inicializa o orquestrador com configuração da PoC.

        Args:
            config: Configuração completa da PoC.
        """
        self._config = config
        self._logger = StructuredLogger(min_level=config.log_level)

        # Módulos da PoC
        self._auth_manager = AuthManager(
            storage_state_path=config.storage_state_path,
            session_timeout=config.session_restore_timeout,
        )
        self._drm_validator = DRMValidator(
            timeout_seconds=config.drm_timeout,
        )
        self._telemetry_collector = TelemetryCollector(
            interval_seconds=config.telemetry_interval,
            channel_id="poc_channel",
        )
        self._frame_capturer = FrameCapturer(
            min_interval_seconds=config.frame_interval,
            min_resolution=config.frame_min_resolution,
            max_size_bytes=config.frame_max_size,
        )
        self._opencv_analyzer = OpenCVAnalyzer(
            black_screen_threshold=(
                config.black_screen_luminance_threshold
            ),
            black_pixel_threshold=config.black_pixel_value_threshold,
            black_pixel_percent=(
                config.black_pixel_percent_threshold
            ),
            variance_threshold=config.variance_threshold,
            freeze_similarity_threshold=(
                config.freeze_similarity_threshold
            ),
        )
        self._bedrock_client = BedrockClient(
            timeout_seconds=config.bedrock_timeout,
            confidence_threshold=(
                config.bedrock_confidence_threshold
            ),
            region=config.bedrock_region,
        )
        self._buffering_detector = BufferingDetector(
            threshold_seconds=config.buffering_threshold,
        )
        self._report_generator = ReportGenerator(
            log_file_path=os.path.join(
                config.output_dir, "poc_execution.log"
            ),
            logger=self._logger,
        )

        # Estado interno do browser
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    async def run(self) -> PoCReport:
        """Executa todas as validações da PoC em sequência.

        Fluxo:
        1. Registra versões do ambiente
        2. Inicializa Playwright com Chromium + Widevine CDM
        3. Executa cadeia de validações com dependências
        4. Gera relatório consolidado
        5. Salva relatório no output_dir
        6. Fecha o browser

        Returns:
            PoCReport com resultado consolidado da PoC.
        """
        self._log_environment_versions()

        results: list[ValidationResult] = []
        auth_passed = False
        drm_passed = False
        frames_passed = False
        opencv_passed = False

        async with async_playwright() as p:
            try:
                # Inicializar browser com Widevine (Google Chrome com CDM built-in)
                browser_start = time.perf_counter()

                # Se user_data_dir existe, usar persistent context
                chrome_profile = os.environ.get(
                    "CHROME_PROFILE_DIR", "/data/chrome-profile"
                )
                use_profile = os.path.isdir(chrome_profile)

                if use_profile:
                    self._logger.info(
                        STAGE_ID,
                        "Usando persistent context com Chrome profile",
                        profile_dir=chrome_profile,
                    )
                    self._context = (
                        await p.chromium.launch_persistent_context(
                            user_data_dir=chrome_profile,
                            executable_path="/usr/bin/google-chrome",
                            headless=False,
                            timeout=300000,
                            args=[
                                "--autoplay-policy="
                                "no-user-gesture-required",
                                "--no-sandbox",
                                "--disable-setuid-sandbox",
                                "--disable-extensions",
                                "--disable-background-networking",
                                "--disable-default-apps",
                                "--no-first-run",
                                "--disable-popup-blocking",
                            ],
                            viewport={"width": 1920, "height": 1080},
                            ignore_default_args=[
                                "--enable-automation",
                            ],
                        )
                    )
                    self._page = (
                        self._context.pages[0]
                        if self._context.pages
                        else await self._context.new_page()
                    )
                else:
                    self._browser = await p.chromium.launch(
                        channel="chrome",
                        headless=False,
                        args=[
                            "--autoplay-policy="
                            "no-user-gesture-required",
                            "--no-sandbox",
                            "--disable-setuid-sandbox",
                        ],
                    )
                    # Criar contexto com storageState
                    storage_path = (
                        self._config.storage_state_path
                        if os.path.exists(
                            self._config.storage_state_path
                        )
                        else None
                    )
                    self._context = (
                        await self._browser.new_context(
                            storage_state=storage_path,
                        )
                    )
                    self._page = await self._context.new_page()

                browser_init_ms = int(
                    (time.perf_counter() - browser_start) * 1000
                )
                self._logger.info(
                    STAGE_ID,
                    "Browser inicializado",
                    browser_init_time_ms=browser_init_ms,
                    using_profile=use_profile,
                )

                # === Validação Auth ===
                auth_result = await self._validate_auth()
                results.append(auth_result)
                auth_passed = (
                    auth_result.status == ValidationStatus.PASS
                )
                # Adicionar browser_init_time_ms ao auth
                auth_result.metrics[
                    "browser_init_time_ms"
                ] = browser_init_ms

                # === Tentar iniciar playback (clicar no player) ===
                if auth_passed:
                    await self._try_start_playback()

                # === Capturar screenshot para diagnóstico ===
                if auth_passed:
                    await self._capture_diagnostic_screenshot(
                        "before_drm"
                    )

                # === Validação DRM ===
                if auth_passed:
                    drm_result = await self._validate_drm()
                    # Screenshot após DRM (para ver estado do player)
                    await self._capture_diagnostic_screenshot(
                        "after_drm"
                    )
                    results.append(drm_result)
                    drm_passed = (
                        drm_result.status == ValidationStatus.PASS
                    )
                else:
                    results.append(
                        self._skipped_result(
                            "drm", "Dependência falhou: login"
                        )
                    )

                # === Validação Telemetry ===
                if drm_passed:
                    telemetry_result = (
                        await self._validate_telemetry()
                    )
                    results.append(telemetry_result)
                else:
                    results.append(
                        self._skipped_result(
                            "telemetry",
                            "Dependência falhou: drm",
                        )
                    )

                # === Validação Frames ===
                if drm_passed:
                    frames_result = (
                        await self._validate_frames()
                    )
                    results.append(frames_result)
                    frames_passed = (
                        frames_result.status
                        == ValidationStatus.PASS
                    )
                else:
                    results.append(
                        self._skipped_result(
                            "frames",
                            "Dependência falhou: drm",
                        )
                    )

                # === Validação OpenCV ===
                if frames_passed:
                    opencv_result = (
                        await self._validate_opencv()
                    )
                    results.append(opencv_result)
                    opencv_passed = (
                        opencv_result.status
                        == ValidationStatus.PASS
                    )
                else:
                    results.append(
                        self._skipped_result(
                            "opencv",
                            "Dependência falhou: frames",
                        )
                    )

                # === Validação Bedrock ===
                if opencv_passed:
                    bedrock_result = (
                        await self._validate_bedrock()
                    )
                    results.append(bedrock_result)
                else:
                    results.append(
                        self._skipped_result(
                            "bedrock",
                            "Dependência falhou: opencv",
                        )
                    )

            except Exception as e:
                self._logger.error(
                    STAGE_ID,
                    "Erro fatal durante execução da PoC",
                    error=str(e),
                    error_type=type(e).__name__,
                )
            finally:
                # Fechar browser/context
                if self._browser:
                    await self._browser.close()
                elif self._context:
                    await self._context.close()
                self._logger.info(
                    STAGE_ID,
                    "Browser fechado com sucesso",
                )

        # Gerar relatório consolidado
        report = self._report_generator.generate(results)

        # Salvar relatório no output_dir
        os.makedirs(self._config.output_dir, exist_ok=True)
        report_path = os.path.join(
            self._config.output_dir, "poc_report.json"
        )
        self._report_generator.save_report(report, report_path)

        self._logger.info(
            STAGE_ID,
            "Execução da PoC concluída",
            decision=report.decision.value,
            total_duration_ms=report.total_duration_ms,
            report_path=report_path,
        )

        return report

    async def _validate_auth(self) -> ValidationResult:
        """Valida autenticação via storageState.

        Verifica que o storageState é válido e a sessão pode
        ser restaurada sem redirecionamento para login.

        Returns:
            ValidationResult com status da validação de auth.
        """
        start_time = self._get_timestamp()
        start_perf = time.perf_counter()

        self._logger.info(
            STAGE_ID,
            "Iniciando validação de autenticação",
        )

        try:
            # Se usando Chrome profile, pular validação de storageState
            chrome_profile = os.environ.get(
                "CHROME_PROFILE_DIR", ""
            )
            if not chrome_profile or not os.path.isdir(chrome_profile):
                # Validar storageState (modo legado)
                is_valid = (
                    self._auth_manager.validate_storage_state()
                )
                if not is_valid:
                    elapsed_ms = int(
                        (time.perf_counter() - start_perf) * 1000
                    )
                    return ValidationResult(
                        name="login",
                        status=ValidationStatus.FAIL,
                        start_time=start_time,
                        end_time=self._get_timestamp(),
                        duration_ms=elapsed_ms,
                        error_message=(
                            "StorageState inválido ou não encontrado"
                        ),
                    )

            # Navegar para o canal e verificar sessão
            assert self._page is not None
            await self._page.goto(
                self._config.channel_url,
                timeout=(
                    self._config.session_restore_timeout * 1000
                ),
                wait_until="domcontentloaded",
            )

            # Aguardar renderização completa do JS
            await self._page.wait_for_timeout(3000)

            # Verificar se foi redirecionado para login
            session_expired = (
                await self._auth_manager.detect_session_expired(
                    self._page
                )
            )

            elapsed_ms = int(
                (time.perf_counter() - start_perf) * 1000
            )
            end_time = self._get_timestamp()

            if session_expired:
                return ValidationResult(
                    name="login",
                    status=ValidationStatus.FAIL,
                    start_time=start_time,
                    end_time=end_time,
                    duration_ms=elapsed_ms,
                    error_message=(
                        "Sessão expirada: redirecionado "
                        "para login"
                    ),
                )

            self._logger.info(
                STAGE_ID,
                "Autenticação validada com sucesso",
                elapsed_ms=elapsed_ms,
            )

            return ValidationResult(
                name="login",
                status=ValidationStatus.PASS,
                start_time=start_time,
                end_time=end_time,
                duration_ms=elapsed_ms,
                metrics={
                    "session_restore_time_ms": elapsed_ms,
                },
            )

        except Exception as e:
            elapsed_ms = int(
                (time.perf_counter() - start_perf) * 1000
            )
            self._logger.error(
                STAGE_ID,
                "Erro na validação de autenticação",
                error=str(e),
            )
            return ValidationResult(
                name="login",
                status=ValidationStatus.FAIL,
                start_time=start_time,
                end_time=self._get_timestamp(),
                duration_ms=elapsed_ms,
                error_message=f"Erro de autenticação: {e}",
            )

    async def _try_start_playback(self) -> None:
        """Tenta iniciar reprodução no player.

        Alguns players precisam de interação (clique) para
        iniciar o playback e solicitar a licença DRM.
        Tenta clicar no elemento video ou botão de play.
        """
        assert self._page is not None
        self._logger.info(
            STAGE_ID,
            "Tentando iniciar playback no player",
        )

        try:
            # Aguardar a página carregar o player
            await self._page.wait_for_timeout(3000)

            # Tentar clicar no elemento video diretamente
            video = await self._page.query_selector("video")
            if video:
                await video.click()
                self._logger.info(
                    STAGE_ID,
                    "Clicou no elemento <video>",
                )
                await self._page.wait_for_timeout(2000)
                return

            # Tentar clicar em botões de play comuns
            play_selectors = [
                "button[aria-label*='play' i]",
                "button[aria-label*='Play' i]",
                ".play-button",
                ".vjs-big-play-button",
                "[data-testid='play-button']",
                ".player-play-button",
                "button.play",
            ]
            for selector in play_selectors:
                btn = await self._page.query_selector(selector)
                if btn:
                    await btn.click()
                    self._logger.info(
                        STAGE_ID,
                        "Clicou no botão de play",
                        selector=selector,
                    )
                    await self._page.wait_for_timeout(2000)
                    return

            # Se nenhum seletor funcionou, tentar clicar no centro da página
            viewport = self._page.viewport_size
            if viewport:
                await self._page.mouse.click(
                    viewport["width"] // 2,
                    viewport["height"] // 2,
                )
                self._logger.info(
                    STAGE_ID,
                    "Clicou no centro do viewport",
                )
                await self._page.wait_for_timeout(2000)

        except Exception as e:
            self._logger.warning(
                STAGE_ID,
                "Falha ao tentar iniciar playback",
                error=str(e),
            )

    async def _validate_drm(self) -> ValidationResult:
        """Valida inicialização do Widevine CDM e licença DRM.

        Injeta monitor EME e aguarda criação de MediaKeys,
        license request e obtenção de licença.

        Returns:
            ValidationResult com status da validação DRM.
        """
        start_time = self._get_timestamp()
        start_perf = time.perf_counter()

        self._logger.info(
            STAGE_ID,
            "Iniciando validação de DRM",
        )

        try:
            assert self._page is not None
            drm_result = (
                await self._drm_validator
                .validate_drm_initialization(self._page)
            )

            elapsed_ms = int(
                (time.perf_counter() - start_perf) * 1000
            )
            end_time = self._get_timestamp()

            if drm_result.license_obtained:
                return ValidationResult(
                    name="drm",
                    status=ValidationStatus.PASS,
                    start_time=start_time,
                    end_time=end_time,
                    duration_ms=elapsed_ms,
                    metrics={
                        "drm_ready_time_ms": (
                            drm_result.time_to_license_ms
                        ),
                        "media_keys_created": (
                            drm_result.media_keys_created
                        ),
                        "license_requested": (
                            drm_result.license_requested
                        ),
                        "license_obtained": (
                            drm_result.license_obtained
                        ),
                    },
                )
            else:
                return ValidationResult(
                    name="drm",
                    status=ValidationStatus.FAIL,
                    start_time=start_time,
                    end_time=end_time,
                    duration_ms=elapsed_ms,
                    error_message=(
                        drm_result.error
                        or "Licença DRM não obtida"
                    ),
                    metrics={
                        "drm_ready_time_ms": (
                            drm_result.time_to_license_ms
                        ),
                        "media_keys_created": (
                            drm_result.media_keys_created
                        ),
                        "license_requested": (
                            drm_result.license_requested
                        ),
                    },
                )

        except Exception as e:
            elapsed_ms = int(
                (time.perf_counter() - start_perf) * 1000
            )
            self._logger.error(
                STAGE_ID,
                "Erro na validação de DRM",
                error=str(e),
            )
            return ValidationResult(
                name="drm",
                status=ValidationStatus.FAIL,
                start_time=start_time,
                end_time=self._get_timestamp(),
                duration_ms=elapsed_ms,
                error_message=f"Erro DRM: {e}",
            )

    async def _validate_telemetry(self) -> ValidationResult:
        """Valida coleta de telemetria do player.

        Executa coleta contínua durante o período configurado
        e verifica que as amostras contêm dados válidos.

        Returns:
            ValidationResult com status da validação de telemetria.
        """
        start_time = self._get_timestamp()
        start_perf = time.perf_counter()

        self._logger.info(
            STAGE_ID,
            "Iniciando validação de telemetria",
        )

        try:
            assert self._page is not None
            samples = (
                await self._telemetry_collector
                .start_continuous_collection(
                    self._page,
                    duration_seconds=(
                        self._config.telemetry_duration
                    ),
                )
            )

            elapsed_ms = int(
                (time.perf_counter() - start_perf) * 1000
            )
            end_time = self._get_timestamp()

            # Verificar se coletou amostras
            if not samples:
                return ValidationResult(
                    name="telemetry",
                    status=ValidationStatus.FAIL,
                    start_time=start_time,
                    end_time=end_time,
                    duration_ms=elapsed_ms,
                    error_message=(
                        "Nenhuma amostra de telemetria coletada"
                    ),
                )

            # Verificar progressão de currentTime
            valid_progression = False
            if len(samples) >= 2:
                first_time = samples[0].video.current_time
                last_time = samples[-1].video.current_time
                if last_time > first_time:
                    valid_progression = True

            status = (
                ValidationStatus.PASS
                if valid_progression
                else ValidationStatus.FAIL
            )
            error_msg = (
                None
                if valid_progression
                else (
                    "currentTime não progrediu durante "
                    "a coleta"
                )
            )

            return ValidationResult(
                name="telemetry",
                status=status,
                start_time=start_time,
                end_time=end_time,
                duration_ms=elapsed_ms,
                error_message=error_msg,
                metrics={
                    "samples_collected": len(samples),
                    "first_current_time": (
                        samples[0].video.current_time
                    ),
                    "last_current_time": (
                        samples[-1].video.current_time
                    ),
                    "current_time_progression": (
                        valid_progression
                    ),
                },
            )

        except Exception as e:
            elapsed_ms = int(
                (time.perf_counter() - start_perf) * 1000
            )
            self._logger.error(
                STAGE_ID,
                "Erro na validação de telemetria",
                error=str(e),
            )
            return ValidationResult(
                name="telemetry",
                status=ValidationStatus.FAIL,
                start_time=start_time,
                end_time=self._get_timestamp(),
                duration_ms=elapsed_ms,
                error_message=f"Erro de telemetria: {e}",
            )

    async def _validate_frames(self) -> ValidationResult:
        """Valida captura de frames do player.

        Captura uma sequência de frames e verifica resolução,
        tamanho e conteúdo visual.

        Returns:
            ValidationResult com status da validação de frames.
        """
        start_time = self._get_timestamp()
        start_perf = time.perf_counter()

        self._logger.info(
            STAGE_ID,
            "Iniciando validação de captura de frames",
        )

        try:
            assert self._page is not None
            # Capturar sequência de 3 frames
            frames = await self._frame_capturer.capture_sequence(
                self._page,
                count=3,
                interval_seconds=self._config.frame_interval,
            )

            elapsed_ms = int(
                (time.perf_counter() - start_perf) * 1000
            )
            end_time = self._get_timestamp()

            if not frames:
                return ValidationResult(
                    name="frames",
                    status=ValidationStatus.FAIL,
                    start_time=start_time,
                    end_time=end_time,
                    duration_ms=elapsed_ms,
                    error_message=(
                        "Nenhum frame capturado"
                    ),
                )

            valid_frames = [f for f in frames if f.is_valid]
            total_frames = len(frames)
            time_per_frame = (
                elapsed_ms // total_frames
                if total_frames > 0
                else 0
            )

            # Pelo menos um frame válido para PASS
            status = (
                ValidationStatus.PASS
                if valid_frames
                else ValidationStatus.FAIL
            )
            error_msg = (
                None
                if valid_frames
                else (
                    "Todos os frames capturados são "
                    "inválidos (tela preta ou resolução "
                    "insuficiente)"
                )
            )

            return ValidationResult(
                name="frames",
                status=status,
                start_time=start_time,
                end_time=end_time,
                duration_ms=elapsed_ms,
                error_message=error_msg,
                metrics={
                    "total_frames": total_frames,
                    "valid_frames": len(valid_frames),
                    "rejected_frames": (
                        total_frames - len(valid_frames)
                    ),
                    "time_per_frame_ms": time_per_frame,
                },
            )

        except Exception as e:
            elapsed_ms = int(
                (time.perf_counter() - start_perf) * 1000
            )
            self._logger.error(
                STAGE_ID,
                "Erro na validação de captura de frames",
                error=str(e),
            )
            return ValidationResult(
                name="frames",
                status=ValidationStatus.FAIL,
                start_time=start_time,
                end_time=self._get_timestamp(),
                duration_ms=elapsed_ms,
                error_message=f"Erro na captura: {e}",
            )

    async def _validate_opencv(self) -> ValidationResult:
        """Valida análise de frames com OpenCV.

        Captura dois frames com intervalo e executa detecção
        de tela preta e freeze.

        Returns:
            ValidationResult com status da validação OpenCV.
        """
        start_time = self._get_timestamp()
        start_perf = time.perf_counter()

        self._logger.info(
            STAGE_ID,
            "Iniciando validação de análise OpenCV",
        )

        try:
            assert self._page is not None
            import cv2
            import numpy as np

            # Capturar dois frames para análise
            frames = await self._frame_capturer.capture_sequence(
                self._page,
                count=2,
                interval_seconds=self._config.frame_interval,
            )

            elapsed_ms = int(
                (time.perf_counter() - start_perf) * 1000
            )
            end_time = self._get_timestamp()

            if len(frames) < 2:
                return ValidationResult(
                    name="opencv",
                    status=ValidationStatus.FAIL,
                    start_time=start_time,
                    end_time=end_time,
                    duration_ms=elapsed_ms,
                    error_message=(
                        "Frames insuficientes para "
                        "análise OpenCV"
                    ),
                )

            # Decodificar frames para numpy arrays
            np_arr_a = np.frombuffer(
                frames[0].data, dtype=np.uint8
            )
            img_a = cv2.imdecode(np_arr_a, cv2.IMREAD_COLOR)

            np_arr_b = np.frombuffer(
                frames[1].data, dtype=np.uint8
            )
            img_b = cv2.imdecode(np_arr_b, cv2.IMREAD_COLOR)

            if img_a is None or img_b is None:
                return ValidationResult(
                    name="opencv",
                    status=ValidationStatus.FAIL,
                    start_time=start_time,
                    end_time=end_time,
                    duration_ms=elapsed_ms,
                    error_message=(
                        "Falha ao decodificar frames "
                        "para análise"
                    ),
                )

            # Análise de tela preta no primeiro frame
            black_result = (
                self._opencv_analyzer.detect_black_screen(img_a)
            )

            # Análise de freeze entre os dois frames
            freeze_result = self._opencv_analyzer.detect_freeze(
                img_a,
                img_b,
                current_time_diff=self._config.frame_interval,
                observation_window_seconds=(
                    self._config.freeze_observation_window
                ),
            )

            elapsed_ms = int(
                (time.perf_counter() - start_perf) * 1000
            )
            end_time = self._get_timestamp()

            return ValidationResult(
                name="opencv",
                status=ValidationStatus.PASS,
                start_time=start_time,
                end_time=end_time,
                duration_ms=elapsed_ms,
                metrics={
                    "black_screen_detected": (
                        black_result.is_black_screen
                    ),
                    "is_dark_scene": (
                        black_result.is_dark_scene
                    ),
                    "mean_luminance": round(
                        black_result.luminance.mean_luminance,
                        2,
                    ),
                    "freeze_classification": (
                        freeze_result.classification.value
                    ),
                    "frame_similarity": round(
                        freeze_result.similarity, 4
                    ),
                },
            )

        except Exception as e:
            elapsed_ms = int(
                (time.perf_counter() - start_perf) * 1000
            )
            self._logger.error(
                STAGE_ID,
                "Erro na validação OpenCV",
                error=str(e),
            )
            return ValidationResult(
                name="opencv",
                status=ValidationStatus.FAIL,
                start_time=start_time,
                end_time=self._get_timestamp(),
                duration_ms=elapsed_ms,
                error_message=f"Erro OpenCV: {e}",
            )

    async def _validate_bedrock(self) -> ValidationResult:
        """Valida chamada ao Amazon Bedrock para diagnóstico.

        Envia um frame com anomalia simulada ao Bedrock e verifica
        que a resposta é parseada corretamente.

        Returns:
            ValidationResult com status da validação Bedrock.
        """
        start_time = self._get_timestamp()
        start_perf = time.perf_counter()

        self._logger.info(
            STAGE_ID,
            "Iniciando validação do Bedrock",
        )

        try:
            assert self._page is not None

            # Capturar um frame para enviar ao Bedrock
            frame = await self._frame_capturer.capture_frame(
                self._page
            )

            if not frame.is_valid:
                # Mesmo frame inválido, testar a chamada
                self._logger.warning(
                    STAGE_ID,
                    "Frame para Bedrock não é válido, "
                    "testando chamada mesmo assim",
                )

            # Invocar Bedrock com anomaly_confirmed=True
            # para testar a integração
            diagnosis = (
                await self._bedrock_client.diagnose_frame(
                    frame.data,
                    anomaly_confirmed=True,
                )
            )

            elapsed_ms = int(
                (time.perf_counter() - start_perf) * 1000
            )
            end_time = self._get_timestamp()

            # Validar que recebemos uma resposta (qualquer status)
            return ValidationResult(
                name="bedrock",
                status=ValidationStatus.PASS,
                start_time=start_time,
                end_time=end_time,
                duration_ms=elapsed_ms,
                metrics={
                    "bedrock_response_time_ms": (
                        diagnosis.response_time_ms
                    ),
                    "diagnosis_status": (
                        diagnosis.status.value
                    ),
                    "confidence": diagnosis.confidence,
                    "model_used": diagnosis.model_used,
                    "escalated": diagnosis.escalated,
                },
            )

        except Exception as e:
            elapsed_ms = int(
                (time.perf_counter() - start_perf) * 1000
            )
            self._logger.error(
                STAGE_ID,
                "Erro na validação do Bedrock",
                error=str(e),
            )
            return ValidationResult(
                name="bedrock",
                status=ValidationStatus.FAIL,
                start_time=start_time,
                end_time=self._get_timestamp(),
                duration_ms=elapsed_ms,
                error_message=f"Erro Bedrock: {e}",
            )

    # =================================================================
    # Métodos auxiliares
    # =================================================================

    def _log_environment_versions(self) -> None:
        """Registra versões do ambiente no início da execução.

        Registra Python, Playwright, OpenCV e Chromium (quando
        disponível) em log nível INFO.
        """
        python_version = sys.version.split()[0]

        playwright_version = "unknown"
        try:
            import playwright
            playwright_version = getattr(
                playwright, "__version__", "unknown"
            )
        except ImportError:
            playwright_version = "not_installed"

        opencv_version = "unknown"
        try:
            import cv2
            opencv_version = cv2.__version__
        except ImportError:
            opencv_version = "not_installed"

        self._logger.info(
            STAGE_ID,
            "Versões do ambiente registradas",
            python_version=python_version,
            playwright_version=playwright_version,
            opencv_version=opencv_version,
        )

    def _get_timestamp(self) -> str:
        """Gera timestamp ISO 8601 com milissegundos em UTC."""
        now = datetime.now(timezone.utc)
        return (
            now.strftime("%Y-%m-%dT%H:%M:%S.")
            + f"{now.microsecond // 1000:03d}Z"
        )

    async def _capture_diagnostic_screenshot(
        self, label: str
    ) -> None:
        """Captura screenshot para diagnóstico e salva no output.

        Args:
            label: Nome descritivo para o arquivo (ex: "before_drm").
        """
        if self._page is None:
            return

        try:
            output_dir = self._config.output_dir
            os.makedirs(output_dir, exist_ok=True)
            path = os.path.join(
                output_dir, f"screenshot_{label}.png"
            )
            await self._page.screenshot(path=path)
            self._logger.info(
                STAGE_ID,
                f"Screenshot de diagnóstico capturado: {label}",
                path=path,
            )
        except Exception as e:
            self._logger.warning(
                STAGE_ID,
                f"Falha ao capturar screenshot: {label}",
                error=str(e),
            )

    def _skipped_result(
        self, name: str, reason: str
    ) -> ValidationResult:
        """Cria um ValidationResult com status SKIPPED.

        Args:
            name: Nome da validação.
            reason: Motivo do skip.

        Returns:
            ValidationResult com status SKIPPED.
        """
        timestamp = self._get_timestamp()
        self._logger.info(
            STAGE_ID,
            f"Validação '{name}' marcada como SKIPPED",
            reason=reason,
        )
        return ValidationResult(
            name=name,
            status=ValidationStatus.SKIPPED,
            start_time=timestamp,
            end_time=timestamp,
            duration_ms=0,
            skipped_reason=reason,
        )
