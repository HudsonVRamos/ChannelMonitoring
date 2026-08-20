"""Gerenciador de autenticação e persistência de sessão via storageState.

Gerencia o ciclo de vida da autenticação na plataforma SKY+:
exportação de storageState após login manual, restauração de sessão,
validação de arquivo storageState e detecção de sessão expirada.
"""
from __future__ import annotations

import json
import os
import time
from typing import Optional

from playwright.async_api import BrowserContext, Page

from src.models import SessionResult, StorageStateResult
from src.structured_logger import StructuredLogger

# Padrões de URL que indicam redirecionamento para login
_LOGIN_PATTERNS: list[str] = ["login", "signin", "auth", "acessar"]

# Timeout padrão para restauração de sessão (segundos)
_DEFAULT_SESSION_TIMEOUT: int = 15


class AuthManager:
    """Gerencia autenticação na plataforma SKY+."""

    def __init__(
        self,
        storage_state_path: str,
        session_timeout: int = _DEFAULT_SESSION_TIMEOUT,
    ) -> None:
        """Inicializa o gerenciador de autenticação.

        Args:
            storage_state_path: Caminho para o arquivo storageState JSON.
            session_timeout: Timeout em segundos para restauração de sessão.
        """
        self._storage_state_path = storage_state_path
        self._session_timeout = session_timeout
        self._logger = StructuredLogger()

    @property
    def storage_state_path(self) -> str:
        """Retorna o caminho do arquivo storageState."""
        return self._storage_state_path

    async def export_storage_state(
        self, page: Page
    ) -> StorageStateResult:
        """Exporta storageState após login manual.

        Salva cookies e localStorage da página atual para o arquivo
        configurado em storage_state_path.

        Args:
            page: Página do Playwright com sessão autenticada.

        Returns:
            StorageStateResult com detalhes da exportação.
        """
        self._logger.info(
            "auth",
            "Exportando storageState",
            path=self._storage_state_path,
        )

        try:
            context = page.context
            await context.storage_state(
                path=self._storage_state_path
            )

            # Validar o arquivo exportado
            with open(self._storage_state_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            cookies = data.get("cookies", [])
            cookies_count = len(cookies)

            self._logger.info(
                "auth",
                "StorageState exportado com sucesso",
                path=self._storage_state_path,
                cookies_count=cookies_count,
            )

            return StorageStateResult(
                success=True,
                path=self._storage_state_path,
                cookies_count=cookies_count,
            )

        except Exception as e:
            error_msg = f"Falha ao exportar storageState: {e}"
            self._logger.error(
                "auth",
                error_msg,
                path=self._storage_state_path,
            )
            return StorageStateResult(
                success=False,
                path=self._storage_state_path,
                cookies_count=0,
                error=error_msg,
            )

    def validate_storage_state(self, path: Optional[str] = None) -> bool:
        """Valida se o arquivo storageState é válido.

        Verifica:
        1. Arquivo existe
        2. Tamanho > 0 bytes
        3. JSON válido
        4. Contém array 'cookies' com ao menos um cookie

        Args:
            path: Caminho para o arquivo. Se None, usa o path configurado.

        Returns:
            True se o storageState é válido, False caso contrário.
        """
        file_path = path or self._storage_state_path

        # Verificar existência do arquivo
        if not os.path.exists(file_path):
            self._logger.error(
                "auth",
                "Arquivo storageState não encontrado",
                path=file_path,
            )
            return False

        # Verificar tamanho > 0
        file_size = os.path.getsize(file_path)
        if file_size <= 0:
            self._logger.error(
                "auth",
                "Arquivo storageState vazio",
                path=file_path,
                size=file_size,
            )
            return False

        # Verificar JSON válido com cookies
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
            self._logger.error(
                "auth",
                "Arquivo storageState com JSON inválido",
                path=file_path,
                error=str(e),
            )
            return False

        # Verificar se contém cookies com ao menos uma entrada
        cookies = data.get("cookies", [])
        if not isinstance(cookies, list) or len(cookies) == 0:
            self._logger.error(
                "auth",
                "StorageState não contém cookies válidos",
                path=file_path,
                cookies_count=0,
            )
            return False

        self._logger.info(
            "auth",
            "StorageState validado com sucesso",
            path=file_path,
            cookies_count=len(cookies),
            size_bytes=file_size,
        )
        return True

    async def detect_session_expired(self, page: Page) -> bool:
        """Detecta se a sessão expirou.

        Verifica duas condições:
        1. URL atual contém padrões de página de login
           (login, signin, auth)
        2. Página recebeu resposta HTTP 401 ou 403

        Args:
            page: Página do Playwright para verificação.

        Returns:
            True se a sessão está expirada, False caso contrário.
        """
        # Verificar URL atual contém padrões de login
        current_url = page.url.lower()
        for pattern in _LOGIN_PATTERNS:
            if pattern in current_url:
                self._logger.error(
                    "auth",
                    "Sessão expirada: redirecionado para página de login",
                    url=page.url,
                    pattern_matched=pattern,
                )
                return True

        # Verificar resposta HTTP 401/403 via avaliação do response
        # Nota: Playwright permite verificar o último response da página
        try:
            response = await page.evaluate(
                """() => {
                    return {
                        status: window.__lastResponseStatus || 200
                    };
                }"""
            )
            status = response.get("status", 200)
            if status in (401, 403):
                self._logger.error(
                    "auth",
                    "Sessão expirada: resposta HTTP indica "
                    "não autorizado",
                    status=status,
                    url=page.url,
                )
                return True
        except Exception:
            # Se não conseguir avaliar, verificar apenas pela URL
            pass

        return False

    async def restore_session(
        self, context: BrowserContext
    ) -> SessionResult:
        """Restaura sessão a partir do storageState.

        Navega usando o contexto configurado com storageState,
        verificando se a sessão foi restaurada sem redirecionamento
        para login, dentro do timeout configurado.

        Args:
            context: BrowserContext do Playwright configurado com
                     storageState.

        Returns:
            SessionResult com detalhes da restauração.
        """
        start_time = time.time()
        timeout_ms = self._session_timeout * 1000

        self._logger.info(
            "auth",
            "Restaurando sessão via storageState",
            path=self._storage_state_path,
            timeout_seconds=self._session_timeout,
        )

        try:
            # Validar storageState antes de restaurar
            if not self.validate_storage_state():
                elapsed_ms = int((time.time() - start_time) * 1000)
                error_msg = (
                    "StorageState inválido, não é possível "
                    "restaurar sessão"
                )
                self._logger.error("auth", error_msg)
                return SessionResult(
                    success=False,
                    restored=False,
                    elapsed_ms=elapsed_ms,
                    error=error_msg,
                )

            # Criar nova página no contexto
            page = await context.new_page()

            try:
                # Navegar para verificar sessão (timeout configurável)
                await page.goto(
                    "about:blank",
                    timeout=timeout_ms,
                )

                elapsed_ms = int((time.time() - start_time) * 1000)

                # Verificar se sessão está ativa
                session_expired = await self.detect_session_expired(page)

                if session_expired:
                    error_msg = (
                        "Sessão expirada após restauração do "
                        "storageState"
                    )
                    self._logger.error(
                        "auth",
                        error_msg,
                        elapsed_ms=elapsed_ms,
                    )
                    return SessionResult(
                        success=False,
                        restored=False,
                        elapsed_ms=elapsed_ms,
                        error=error_msg,
                    )

                self._logger.info(
                    "auth",
                    "Sessão restaurada com sucesso",
                    elapsed_ms=elapsed_ms,
                )
                return SessionResult(
                    success=True,
                    restored=True,
                    elapsed_ms=elapsed_ms,
                )

            finally:
                await page.close()

        except Exception as e:
            elapsed_ms = int((time.time() - start_time) * 1000)
            error_msg = f"Falha ao restaurar sessão: {e}"
            self._logger.error(
                "auth",
                error_msg,
                elapsed_ms=elapsed_ms,
            )
            return SessionResult(
                success=False,
                restored=False,
                elapsed_ms=elapsed_ms,
                error=error_msg,
            )
