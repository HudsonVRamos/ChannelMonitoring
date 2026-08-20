# Feature: widevine-poc, Property 1: Detecção de sessão expirada
"""Testes de propriedade para o AuthManager - detecção de sessão expirada.

Validates: Requirements 1.4

Property 1: Para qualquer resposta HTTP com status 401 ou 403, ou qualquer
redirecionamento para uma URL contendo padrão de página de login, o sistema
SHALL classificar o storageState como expirado.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from src.auth_manager import AuthManager, _LOGIN_PATTERNS


# =============================================================================
# Estratégias de geração de dados
# =============================================================================

# Gerar URLs que contêm padrões de login (case-insensitive)
login_pattern_st = st.sampled_from(_LOGIN_PATTERNS)

# Gerar URLs com padrão de login embutido
url_with_login_pattern_st = st.builds(
    lambda prefix, pattern, suffix: f"https://{prefix}.example.com/{pattern}/{suffix}",
    prefix=st.text(
        alphabet=st.characters(whitelist_categories=("Ll",), min_codepoint=97, max_codepoint=122),
        min_size=3,
        max_size=10,
    ),
    pattern=login_pattern_st,
    suffix=st.text(
        alphabet=st.characters(whitelist_categories=("Ll", "Nd"), min_codepoint=48, max_codepoint=122),
        min_size=0,
        max_size=15,
    ),
)

# Gerar URLs SEM padrão de login
safe_path_segments = st.text(
    alphabet=st.characters(whitelist_categories=("Ll", "Nd"), min_codepoint=48, max_codepoint=122),
    min_size=3,
    max_size=15,
).filter(lambda s: not any(p in s.lower() for p in _LOGIN_PATTERNS))

url_without_login_pattern_st = st.builds(
    lambda domain, path: f"https://{domain}.example.com/{path}",
    domain=safe_path_segments,
    path=safe_path_segments,
)

# Status HTTP que indicam sessão expirada
expired_status_st = st.sampled_from([401, 403])

# Status HTTP normais (não expirado)
ok_status_st = st.just(200)

# Status HTTP que NÃO indicam expiração (excluindo 401 e 403)
non_expired_status_st = st.integers(min_value=100, max_value=599).filter(
    lambda s: s not in (401, 403)
)


# =============================================================================
# Helpers
# =============================================================================


def _create_mock_page(url: str, response_status: int = 200) -> AsyncMock:
    """Cria um mock do Playwright Page com URL e status configuráveis."""
    page = AsyncMock()
    page.url = url
    page.evaluate = AsyncMock(return_value={"status": response_status})
    return page


def _run_async(coro):
    """Executa coroutine de forma síncrona para uso com Hypothesis."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# =============================================================================
# Propriedade 1: URL com padrão de login → sessão expirada
# =============================================================================


class TestProperty1URLLoginPattern:
    """Para qualquer URL contendo padrão de login, detect_session_expired retorna True."""

    @settings(max_examples=100)
    @given(url=url_with_login_pattern_st, status=non_expired_status_st)
    def test_url_with_login_pattern_detected_as_expired(self, url, status):
        """**Validates: Requirements 1.4**

        Para qualquer URL contendo "login", "signin", ou "auth",
        detect_session_expired DEVE retornar True independente do status HTTP.
        """
        auth_manager = AuthManager(storage_state_path="/tmp/fake_state.json")
        page = _create_mock_page(url=url, response_status=status)

        result = _run_async(auth_manager.detect_session_expired(page))

        assert result is True, (
            f"URL '{url}' contém padrão de login mas detect_session_expired "
            f"retornou False (status={status})"
        )


# =============================================================================
# Propriedade 2: HTTP 401/403 → sessão expirada
# =============================================================================


class TestProperty1HTTPStatus:
    """Para HTTP status 401 ou 403, detect_session_expired retorna True."""

    @settings(max_examples=100)
    @given(url=url_without_login_pattern_st, status=expired_status_st)
    def test_http_401_403_detected_as_expired(self, url, status):
        """**Validates: Requirements 1.4**

        Para qualquer resposta HTTP com status 401 ou 403,
        detect_session_expired DEVE retornar True.
        """
        auth_manager = AuthManager(storage_state_path="/tmp/fake_state.json")
        page = _create_mock_page(url=url, response_status=status)

        result = _run_async(auth_manager.detect_session_expired(page))

        assert result is True, (
            f"Status HTTP {status} deveria indicar sessão expirada mas "
            f"detect_session_expired retornou False (url='{url}')"
        )


# =============================================================================
# Propriedade 3: URL sem login + HTTP 200 → sessão válida
# =============================================================================


class TestProperty1SessionValid:
    """URL sem padrão de login E HTTP 200 → detect_session_expired retorna False."""

    @settings(max_examples=100)
    @given(url=url_without_login_pattern_st)
    def test_no_login_pattern_and_200_returns_not_expired(self, url):
        """**Validates: Requirements 1.4**

        Para qualquer URL sem padrão de login E resposta HTTP 200,
        detect_session_expired DEVE retornar False.
        """
        auth_manager = AuthManager(storage_state_path="/tmp/fake_state.json")
        page = _create_mock_page(url=url, response_status=200)

        result = _run_async(auth_manager.detect_session_expired(page))

        assert result is False, (
            f"URL '{url}' não contém padrão de login e status é 200, "
            f"mas detect_session_expired retornou True"
        )


# =============================================================================
# Propriedade 4: Padrão de login detectado independente do HTTP status
# =============================================================================


class TestProperty1LoginPatternAlwaysDetected:
    """Padrão de login na URL sempre é detectado, independente do status HTTP."""

    @settings(max_examples=100)
    @given(
        url=url_with_login_pattern_st,
        status=st.integers(min_value=100, max_value=599),
    )
    def test_login_pattern_detected_regardless_of_status(self, url, status):
        """**Validates: Requirements 1.4**

        Para qualquer URL contendo padrão de login, detect_session_expired
        DEVE retornar True independente de qualquer código de status HTTP.
        """
        auth_manager = AuthManager(storage_state_path="/tmp/fake_state.json")
        page = _create_mock_page(url=url, response_status=status)

        result = _run_async(auth_manager.detect_session_expired(page))

        assert result is True, (
            f"URL '{url}' contém padrão de login mas detect_session_expired "
            f"retornou False (status HTTP={status})"
        )
