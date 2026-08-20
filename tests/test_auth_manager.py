"""Testes unitários para o AuthManager.

Valida a lógica de validação de storageState, detecção de
sessão expirada e restauração de sessão.
"""
from __future__ import annotations

import json
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.auth_manager import AuthManager, _LOGIN_PATTERNS
from src.models import SessionResult, StorageStateResult


# =============================================================================
# Testes para validate_storage_state
# =============================================================================


class TestValidateStorageState:
    """Testes para validação do arquivo storageState."""

    def test_arquivo_inexistente_retorna_false(self, tmp_path):
        """Arquivo que não existe deve retornar False."""
        path = str(tmp_path / "nao_existe.json")
        manager = AuthManager(storage_state_path=path)
        assert manager.validate_storage_state() is False

    def test_arquivo_vazio_retorna_false(self, tmp_path):
        """Arquivo vazio (0 bytes) deve retornar False."""
        path = str(tmp_path / "vazio.json")
        with open(path, "w") as f:
            pass  # Cria arquivo vazio
        manager = AuthManager(storage_state_path=path)
        assert manager.validate_storage_state() is False

    def test_json_invalido_retorna_false(self, tmp_path):
        """Arquivo com JSON inválido deve retornar False."""
        path = str(tmp_path / "invalido.json")
        with open(path, "w") as f:
            f.write("isso não é json {{{")
        manager = AuthManager(storage_state_path=path)
        assert manager.validate_storage_state() is False

    def test_json_sem_cookies_retorna_false(self, tmp_path):
        """JSON válido mas sem array cookies deve retornar False."""
        path = str(tmp_path / "sem_cookies.json")
        with open(path, "w") as f:
            json.dump({"origins": []}, f)
        manager = AuthManager(storage_state_path=path)
        assert manager.validate_storage_state() is False

    def test_json_com_cookies_vazio_retorna_false(self, tmp_path):
        """JSON com array cookies vazio deve retornar False."""
        path = str(tmp_path / "cookies_vazio.json")
        with open(path, "w") as f:
            json.dump({"cookies": []}, f)
        manager = AuthManager(storage_state_path=path)
        assert manager.validate_storage_state() is False

    def test_json_valido_com_cookies_retorna_true(self, tmp_path):
        """JSON válido com ao menos um cookie deve retornar True."""
        path = str(tmp_path / "valido.json")
        data = {
            "cookies": [
                {
                    "name": "session_id",
                    "value": "abc123",
                    "domain": ".sky.com.br",
                    "path": "/",
                }
            ],
            "origins": [],
        }
        with open(path, "w") as f:
            json.dump(data, f)
        manager = AuthManager(storage_state_path=path)
        assert manager.validate_storage_state() is True

    def test_aceita_path_alternativo(self, tmp_path):
        """Deve aceitar um path diferente do configurado."""
        path_padrao = str(tmp_path / "padrao.json")
        path_alt = str(tmp_path / "alternativo.json")
        data = {
            "cookies": [{"name": "x", "value": "y"}],
        }
        with open(path_alt, "w") as f:
            json.dump(data, f)
        manager = AuthManager(storage_state_path=path_padrao)
        assert manager.validate_storage_state(path=path_alt) is True

    def test_cookies_nao_lista_retorna_false(self, tmp_path):
        """Se cookies não for uma lista, deve retornar False."""
        path = str(tmp_path / "cookies_str.json")
        with open(path, "w") as f:
            json.dump({"cookies": "invalid"}, f)
        manager = AuthManager(storage_state_path=path)
        assert manager.validate_storage_state() is False


# =============================================================================
# Testes para detect_session_expired
# =============================================================================


class TestDetectSessionExpired:
    """Testes para detecção de sessão expirada."""

    @pytest.mark.asyncio
    async def test_url_com_login_detecta_expirada(self):
        """URL contendo 'login' indica sessão expirada."""
        page = MagicMock()
        page.url = "https://sky.com.br/login?redirect=/canais"
        page.evaluate = AsyncMock(
            return_value={"status": 200}
        )

        manager = AuthManager(storage_state_path="fake.json")
        result = await manager.detect_session_expired(page)
        assert result is True

    @pytest.mark.asyncio
    async def test_url_com_signin_detecta_expirada(self):
        """URL contendo 'signin' indica sessão expirada."""
        page = MagicMock()
        page.url = "https://sky.com.br/signin"
        page.evaluate = AsyncMock(
            return_value={"status": 200}
        )

        manager = AuthManager(storage_state_path="fake.json")
        result = await manager.detect_session_expired(page)
        assert result is True

    @pytest.mark.asyncio
    async def test_url_com_auth_detecta_expirada(self):
        """URL contendo 'auth' indica sessão expirada."""
        page = MagicMock()
        page.url = "https://sky.com.br/auth/oauth2"
        page.evaluate = AsyncMock(
            return_value={"status": 200}
        )

        manager = AuthManager(storage_state_path="fake.json")
        result = await manager.detect_session_expired(page)
        assert result is True

    @pytest.mark.asyncio
    async def test_http_401_detecta_expirada(self):
        """Resposta HTTP 401 indica sessão expirada."""
        page = MagicMock()
        page.url = "https://sky.com.br/canais/ao-vivo"
        page.evaluate = AsyncMock(
            return_value={"status": 401}
        )

        manager = AuthManager(storage_state_path="fake.json")
        result = await manager.detect_session_expired(page)
        assert result is True

    @pytest.mark.asyncio
    async def test_http_403_detecta_expirada(self):
        """Resposta HTTP 403 indica sessão expirada."""
        page = MagicMock()
        page.url = "https://sky.com.br/canais/ao-vivo"
        page.evaluate = AsyncMock(
            return_value={"status": 403}
        )

        manager = AuthManager(storage_state_path="fake.json")
        result = await manager.detect_session_expired(page)
        assert result is True

    @pytest.mark.asyncio
    async def test_sessao_ativa_retorna_false(self):
        """URL normal + HTTP 200 indica sessão ativa."""
        page = MagicMock()
        page.url = "https://sky.com.br/canais/ao-vivo"
        page.evaluate = AsyncMock(
            return_value={"status": 200}
        )

        manager = AuthManager(storage_state_path="fake.json")
        result = await manager.detect_session_expired(page)
        assert result is False

    @pytest.mark.asyncio
    async def test_erro_evaluate_nao_lanca_excecao(self):
        """Se evaluate falhar, verifica apenas pela URL."""
        page = MagicMock()
        page.url = "https://sky.com.br/canais/ao-vivo"
        page.evaluate = AsyncMock(side_effect=Exception("fail"))

        manager = AuthManager(storage_state_path="fake.json")
        result = await manager.detect_session_expired(page)
        assert result is False


# =============================================================================
# Testes para export_storage_state
# =============================================================================


class TestExportStorageState:
    """Testes para exportação de storageState."""

    @pytest.mark.asyncio
    async def test_exporta_com_sucesso(self, tmp_path):
        """Exportação bem-sucedida retorna resultado com cookies."""
        path = str(tmp_path / "state.json")
        data = {
            "cookies": [
                {"name": "sess", "value": "abc"},
                {"name": "token", "value": "xyz"},
            ],
            "origins": [],
        }

        # Mock do context.storage_state que cria o arquivo
        async def mock_storage_state(path=None):
            with open(path, "w") as f:
                json.dump(data, f)

        context = MagicMock()
        context.storage_state = AsyncMock(
            side_effect=mock_storage_state
        )

        page = MagicMock()
        page.context = context

        manager = AuthManager(storage_state_path=path)
        result = await manager.export_storage_state(page)

        assert result.success is True
        assert result.cookies_count == 2
        assert result.path == path
        assert result.error is None

    @pytest.mark.asyncio
    async def test_exporta_com_falha(self, tmp_path):
        """Falha na exportação retorna resultado com erro."""
        path = str(tmp_path / "state.json")

        context = MagicMock()
        context.storage_state = AsyncMock(
            side_effect=Exception("permission denied")
        )

        page = MagicMock()
        page.context = context

        manager = AuthManager(storage_state_path=path)
        result = await manager.export_storage_state(page)

        assert result.success is False
        assert result.cookies_count == 0
        assert result.error is not None
        assert "permission denied" in result.error


# =============================================================================
# Testes para restore_session
# =============================================================================


class TestRestoreSession:
    """Testes para restauração de sessão."""

    @pytest.mark.asyncio
    async def test_restaura_com_sucesso(self, tmp_path):
        """Restauração bem-sucedida com storageState válido."""
        path = str(tmp_path / "state.json")
        data = {
            "cookies": [{"name": "sess", "value": "abc"}],
            "origins": [],
        }
        with open(path, "w") as f:
            json.dump(data, f)

        page = MagicMock()
        page.url = "https://sky.com.br/canais"
        page.goto = AsyncMock()
        page.evaluate = AsyncMock(return_value={"status": 200})
        page.close = AsyncMock()

        context = MagicMock()
        context.new_page = AsyncMock(return_value=page)

        manager = AuthManager(storage_state_path=path)
        result = await manager.restore_session(context)

        assert result.success is True
        assert result.restored is True
        assert result.elapsed_ms >= 0
        assert result.error is None

    @pytest.mark.asyncio
    async def test_falha_com_storage_invalido(self, tmp_path):
        """Falha se storageState for inválido."""
        path = str(tmp_path / "invalido.json")
        # Não cria o arquivo

        context = MagicMock()

        manager = AuthManager(storage_state_path=path)
        result = await manager.restore_session(context)

        assert result.success is False
        assert result.restored is False
        assert "inválido" in result.error.lower()

    @pytest.mark.asyncio
    async def test_falha_com_sessao_expirada(self, tmp_path):
        """Falha se sessão estiver expirada após restauração."""
        path = str(tmp_path / "state.json")
        data = {
            "cookies": [{"name": "sess", "value": "abc"}],
        }
        with open(path, "w") as f:
            json.dump(data, f)

        page = MagicMock()
        page.url = "https://sky.com.br/login"
        page.goto = AsyncMock()
        page.evaluate = AsyncMock(return_value={"status": 200})
        page.close = AsyncMock()

        context = MagicMock()
        context.new_page = AsyncMock(return_value=page)

        manager = AuthManager(storage_state_path=path)
        result = await manager.restore_session(context)

        assert result.success is False
        assert result.restored is False
        assert "expirada" in result.error.lower()

    @pytest.mark.asyncio
    async def test_falha_com_excecao(self, tmp_path):
        """Falha graciosamente se houver exceção."""
        path = str(tmp_path / "state.json")
        data = {
            "cookies": [{"name": "sess", "value": "abc"}],
        }
        with open(path, "w") as f:
            json.dump(data, f)

        context = MagicMock()
        context.new_page = AsyncMock(
            side_effect=Exception("browser crashed")
        )

        manager = AuthManager(storage_state_path=path)
        result = await manager.restore_session(context)

        assert result.success is False
        assert result.restored is False
        assert "browser crashed" in result.error
