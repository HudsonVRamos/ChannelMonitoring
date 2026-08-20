"""Validador de DRM Widevine via Playwright.

Monitora o processo de inicialização do Widevine CDM (Encrypted Media
Extensions) injetando JavaScript na página para capturar eventos EME:
criação de MediaKeys, license request e obtenção de licença.

Referências: Requirements 2.1, 2.4, 2.5, 10.3
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Optional

from playwright.async_api import Page

from src.models import DRMResult
from src.structured_logger import StructuredLogger


STAGE_ID = "drm_validator"


@dataclass
class LicenseResult:
    """Resultado da espera pela obtenção de licença DRM."""

    obtained: bool
    time_to_license_ms: int
    key_status: Optional[str] = None
    error: Optional[str] = None


@dataclass
class DRMError:
    """Erro específico do CDM capturado durante o handshake."""

    code: Optional[str] = None
    message: str = ""
    system_code: Optional[int] = None
    timestamp_ms: int = 0


# JavaScript injetado na página para monitorar eventos EME do Widevine.
# Armazena resultados em window.__drm_monitor__ para posterior leitura.
_EME_MONITOR_JS = """
() => {
    if (window.__drm_monitor__) return;

    window.__drm_monitor__ = {
        mediaKeysCreated: false,
        licenseRequested: false,
        licenseObtained: false,
        keyStatus: null,
        error: null,
        timestamps: {
            start: Date.now(),
            mediaKeysCreated: null,
            licenseRequested: null,
            licenseObtained: null,
            error: null
        }
    };

    const monitor = window.__drm_monitor__;

    // Interceptar navigator.requestMediaKeySystemAccess
    const originalRequest = navigator.requestMediaKeySystemAccess;
    if (originalRequest) {
        navigator.requestMediaKeySystemAccess = async function(...args) {
            const access = await originalRequest.apply(navigator, args);

            // Interceptar createMediaKeys
            const originalCreateKeys = access.createMediaKeys.bind(access);
            access.createMediaKeys = async function() {
                const mediaKeys = await originalCreateKeys();
                monitor.mediaKeysCreated = true;
                monitor.timestamps.mediaKeysCreated = Date.now();

                // Interceptar createSession no MediaKeys
                const originalCreateSession = mediaKeys.createSession.bind(mediaKeys);
                mediaKeys.createSession = function(sessionType) {
                    const session = originalCreateSession(sessionType);

                    // Monitorar evento message (license request)
                    session.addEventListener('message', () => {
                        if (!monitor.licenseRequested) {
                            monitor.licenseRequested = true;
                            monitor.timestamps.licenseRequested = Date.now();
                        }
                    });

                    // Monitorar keystatuseschange (licença obtida)
                    session.addEventListener('keystatuseschange', (event) => {
                        const keyStatuses = event.target.keyStatuses;
                        let status = 'unknown';
                        keyStatuses.forEach((value) => {
                            status = value;
                        });
                        if (status === 'usable' || status === 'output-restricted') {
                            monitor.licenseObtained = true;
                            monitor.keyStatus = status;
                            monitor.timestamps.licenseObtained = Date.now();
                        } else if (status === 'internal-error' || status === 'expired') {
                            monitor.error = {
                                code: status,
                                message: 'Key status: ' + status,
                                systemCode: 0,
                                timestamp: Date.now()
                            };
                            monitor.timestamps.error = Date.now();
                        }
                    });

                    return session;
                };

                return mediaKeys;
            };

            return access;
        };
    }

    // Monitorar evento encrypted no video element
    const observeVideo = () => {
        const videos = document.querySelectorAll('video');
        videos.forEach((video) => {
            if (video.__drm_observed__) return;
            video.__drm_observed__ = true;

            video.addEventListener('encrypted', () => {
                // Evento encrypted indica que o conteúdo DRM foi detectado
            });

            video.addEventListener('error', (e) => {
                if (!monitor.error) {
                    const mediaError = video.error;
                    monitor.error = {
                        code: mediaError ? String(mediaError.code) : 'unknown',
                        message: mediaError ? mediaError.message : 'Unknown video error',
                        systemCode: mediaError ? mediaError.code : 0,
                        timestamp: Date.now()
                    };
                    monitor.timestamps.error = Date.now();
                }
            });
        });
    };

    // Observar DOM para novos elementos video
    observeVideo();
    const observer = new MutationObserver(observeVideo);
    observer.observe(document.body || document.documentElement, {
        childList: true, subtree: true
    });
}
"""

_GET_DRM_STATE_JS = """
() => {
    if (!window.__drm_monitor__) {
        return null;
    }
    return JSON.parse(JSON.stringify(window.__drm_monitor__));
}
"""


class DRMValidator:
    """Valida o funcionamento do Widevine DRM.

    Injeta JavaScript via Playwright para interceptar eventos EME
    (Encrypted Media Extensions) e monitorar o handshake DRM completo:
    criação de MediaKeys, geração de license request e obtenção de licença.
    """

    def __init__(self, timeout_seconds: int = 15) -> None:
        """Inicializa o validador DRM.

        Args:
            timeout_seconds: Timeout máximo para operações DRM (padrão: 15s).
        """
        self._timeout_seconds = timeout_seconds
        self._logger = StructuredLogger()

    async def _inject_monitor(self, page: Page) -> None:
        """Injeta o monitor EME na página se ainda não injetado."""
        await page.evaluate(_EME_MONITOR_JS)

    async def _get_drm_state(self, page: Page) -> Optional[dict]:
        """Recupera o estado atual do monitor DRM da página."""
        return await page.evaluate(_GET_DRM_STATE_JS)

    async def validate_drm_initialization(self, page: Page) -> DRMResult:
        """Valida criação de MediaKeys e license request.

        Injeta o monitor EME na página e aguarda até o timeout configurado
        pela criação de MediaKeys e geração do license request.

        Args:
            page: Instância de Page do Playwright com o player carregado.

        Returns:
            DRMResult com o estado da inicialização DRM.
        """
        start_time = time.perf_counter()
        self._logger.info(
            STAGE_ID,
            "Iniciando validação de inicialização DRM",
            timeout_seconds=self._timeout_seconds,
        )

        await self._inject_monitor(page)

        deadline = start_time + self._timeout_seconds
        media_keys_created = False
        license_requested = False
        license_obtained = False
        error_msg: Optional[str] = None

        while time.perf_counter() < deadline:
            state = await self._get_drm_state(page)

            if state is None:
                # Monitor ainda não injetado ou página recarregou
                await self._inject_monitor(page)
                await asyncio.sleep(0.5)
                continue

            # Verificar erro
            if state.get("error"):
                err = state["error"]
                error_msg = (
                    f"CDM Error: code={err.get('code')}, "
                    f"message={err.get('message')}"
                )
                elapsed_ms = int(
                    (time.perf_counter() - start_time) * 1000
                )
                self._logger.error(
                    STAGE_ID,
                    "Erro detectado no CDM durante inicialização",
                    error_code=err.get("code"),
                    error_message=err.get("message"),
                    elapsed_ms=elapsed_ms,
                )
                break

            # Log de progresso quando MediaKeys é criado
            if state.get("mediaKeysCreated") and not media_keys_created:
                media_keys_created = True
                ts = state.get("timestamps", {})
                mk_time = ts.get("mediaKeysCreated", 0)
                start_ts = ts.get("start", 0)
                elapsed_mk = mk_time - start_ts if mk_time and start_ts else 0
                self._logger.info(
                    STAGE_ID,
                    "MediaKeys criado com sucesso",
                    elapsed_ms=elapsed_mk,
                )

            # Log quando license request é gerado
            if state.get("licenseRequested") and not license_requested:
                license_requested = True
                ts = state.get("timestamps", {})
                lr_time = ts.get("licenseRequested", 0)
                start_ts = ts.get("start", 0)
                elapsed_lr = lr_time - start_ts if lr_time and start_ts else 0
                self._logger.info(
                    STAGE_ID,
                    "License request gerado",
                    elapsed_ms=elapsed_lr,
                )

            # Verificar licença obtida
            if state.get("licenseObtained"):
                license_obtained = True
                ts = state.get("timestamps", {})
                lo_time = ts.get("licenseObtained", 0)
                start_ts = ts.get("start", 0)
                elapsed_lo = lo_time - start_ts if lo_time and start_ts else 0
                self._logger.info(
                    STAGE_ID,
                    "Licença DRM obtida com sucesso",
                    elapsed_ms=elapsed_lo,
                    key_status=state.get("keyStatus"),
                )
                break

            # Se já tem MediaKeys + license request, aguardar licença
            if media_keys_created and license_requested:
                await asyncio.sleep(0.3)
            else:
                await asyncio.sleep(0.5)

        total_elapsed_ms = int((time.perf_counter() - start_time) * 1000)

        # Se timeout sem licença e sem erro, registrar timeout
        if not license_obtained and not error_msg:
            if not media_keys_created:
                error_msg = (
                    f"Timeout ({self._timeout_seconds}s): "
                    f"MediaKeys não foi criado"
                )
            elif not license_requested:
                error_msg = (
                    f"Timeout ({self._timeout_seconds}s): "
                    f"License request não foi gerado"
                )
            else:
                error_msg = (
                    f"Timeout ({self._timeout_seconds}s): "
                    f"Licença DRM não obtida após license request"
                )
            self._logger.error(
                STAGE_ID,
                "Timeout na inicialização DRM",
                error=error_msg,
                elapsed_ms=total_elapsed_ms,
                media_keys_created=media_keys_created,
                license_requested=license_requested,
            )

        result = DRMResult(
            media_keys_created=media_keys_created,
            license_requested=license_requested,
            license_obtained=license_obtained,
            time_to_license_ms=total_elapsed_ms,
            error=error_msg,
        )

        self._logger.info(
            STAGE_ID,
            "Validação de inicialização DRM concluída",
            media_keys_created=result.media_keys_created,
            license_requested=result.license_requested,
            license_obtained=result.license_obtained,
            time_to_license_ms=result.time_to_license_ms,
            error=result.error,
        )

        return result

    async def wait_for_license(self, page: Page) -> LicenseResult:
        """Aguarda obtenção da licença DRM.

        Faz polling do estado do monitor DRM até que a licença seja
        obtida ou o timeout seja atingido.

        Args:
            page: Instância de Page do Playwright com o player carregado.

        Returns:
            LicenseResult com detalhes da obtenção da licença.
        """
        start_time = time.perf_counter()
        self._logger.info(
            STAGE_ID,
            "Aguardando obtenção de licença DRM",
            timeout_seconds=self._timeout_seconds,
        )

        await self._inject_monitor(page)

        deadline = start_time + self._timeout_seconds

        while time.perf_counter() < deadline:
            state = await self._get_drm_state(page)

            if state is None:
                await asyncio.sleep(0.5)
                continue

            # Verificar erro
            if state.get("error"):
                err = state["error"]
                elapsed_ms = int(
                    (time.perf_counter() - start_time) * 1000
                )
                error_msg = (
                    f"CDM Error: code={err.get('code')}, "
                    f"message={err.get('message')}"
                )
                self._logger.error(
                    STAGE_ID,
                    "Erro ao aguardar licença DRM",
                    error_code=err.get("code"),
                    error_message=err.get("message"),
                    elapsed_ms=elapsed_ms,
                )
                return LicenseResult(
                    obtained=False,
                    time_to_license_ms=elapsed_ms,
                    error=error_msg,
                )

            # Verificar licença obtida
            if state.get("licenseObtained"):
                elapsed_ms = int(
                    (time.perf_counter() - start_time) * 1000
                )
                key_status = state.get("keyStatus", "unknown")
                self._logger.info(
                    STAGE_ID,
                    "Licença DRM obtida",
                    elapsed_ms=elapsed_ms,
                    key_status=key_status,
                )
                return LicenseResult(
                    obtained=True,
                    time_to_license_ms=elapsed_ms,
                    key_status=key_status,
                )

            await asyncio.sleep(0.3)

        # Timeout
        elapsed_ms = int((time.perf_counter() - start_time) * 1000)
        error_msg = (
            f"Timeout ({self._timeout_seconds}s): "
            f"licença DRM não obtida"
        )
        self._logger.error(
            STAGE_ID,
            "Timeout aguardando licença DRM",
            elapsed_ms=elapsed_ms,
        )
        return LicenseResult(
            obtained=False,
            time_to_license_ms=elapsed_ms,
            error=error_msg,
        )

    async def capture_drm_error(self, page: Page) -> Optional[DRMError]:
        """Captura erro específico do CDM se houver falha.

        Verifica o estado do monitor DRM e retorna detalhes do erro
        caso algum tenha sido registrado durante o handshake.

        Args:
            page: Instância de Page do Playwright com o player carregado.

        Returns:
            DRMError com detalhes do erro ou None se sem erros.
        """
        self._logger.debug(
            STAGE_ID,
            "Verificando erros do CDM",
        )

        state = await self._get_drm_state(page)

        if state is None:
            self._logger.debug(
                STAGE_ID,
                "Monitor DRM não encontrado na página",
            )
            return None

        error_data = state.get("error")
        if not error_data:
            self._logger.debug(
                STAGE_ID,
                "Nenhum erro DRM detectado",
            )
            return None

        drm_error = DRMError(
            code=error_data.get("code"),
            message=error_data.get("message", ""),
            system_code=error_data.get("systemCode"),
            timestamp_ms=error_data.get("timestamp", 0),
        )

        self._logger.error(
            STAGE_ID,
            "Erro DRM capturado",
            error_code=drm_error.code,
            error_message=drm_error.message,
            system_code=drm_error.system_code,
            timestamp_ms=drm_error.timestamp_ms,
        )

        return drm_error
