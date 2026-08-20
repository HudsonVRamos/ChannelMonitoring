"""Testes unitários para o DRMValidator.

Testa a lógica de inicialização, timeout e captura de erros
utilizando mocks do Playwright Page.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.drm_validator import DRMValidator, DRMError, LicenseResult
from src.models import DRMResult


@pytest.fixture
def validator():
    """Instância do DRMValidator com timeout curto para testes."""
    return DRMValidator(timeout_seconds=2)


@pytest.fixture
def mock_page():
    """Mock de Playwright Page."""
    page = AsyncMock()
    return page


class TestDRMValidatorInit:
    """Testes de inicialização do DRMValidator."""

    def test_default_timeout(self):
        """Timeout padrão deve ser 15 segundos."""
        validator = DRMValidator()
        assert validator._timeout_seconds == 15

    def test_custom_timeout(self):
        """Timeout customizado deve ser respeitado."""
        validator = DRMValidator(timeout_seconds=30)
        assert validator._timeout_seconds == 30


class TestValidateDRMInitialization:
    """Testes de validate_drm_initialization."""

    async def test_successful_initialization(self, validator, mock_page):
        """Inicialização bem-sucedida retorna DRMResult completo."""
        # Simular progresso do handshake DRM
        call_count = 0

        async def mock_evaluate(js_code):
            nonlocal call_count
            call_count += 1
            if call_count <= 1:
                # Primeira chamada: injeta monitor
                return None
            # Retornar estado completo de sucesso
            return {
                "mediaKeysCreated": True,
                "licenseRequested": True,
                "licenseObtained": True,
                "keyStatus": "usable",
                "error": None,
                "timestamps": {
                    "start": 1000,
                    "mediaKeysCreated": 1100,
                    "licenseRequested": 1200,
                    "licenseObtained": 1500,
                    "error": None,
                },
            }

        mock_page.evaluate = mock_evaluate

        result = await validator.validate_drm_initialization(mock_page)

        assert isinstance(result, DRMResult)
        assert result.media_keys_created is True
        assert result.license_requested is True
        assert result.license_obtained is True
        assert result.error is None
        assert result.time_to_license_ms >= 0

    async def test_timeout_no_media_keys(self, validator, mock_page):
        """Timeout sem criação de MediaKeys retorna erro."""
        call_count = 0

        async def mock_evaluate(js_code):
            nonlocal call_count
            call_count += 1
            if call_count <= 1:
                return None
            # Retornar estado vazio (nada aconteceu)
            return {
                "mediaKeysCreated": False,
                "licenseRequested": False,
                "licenseObtained": False,
                "keyStatus": None,
                "error": None,
                "timestamps": {
                    "start": 1000,
                    "mediaKeysCreated": None,
                    "licenseRequested": None,
                    "licenseObtained": None,
                    "error": None,
                },
            }

        mock_page.evaluate = mock_evaluate

        result = await validator.validate_drm_initialization(mock_page)

        assert result.media_keys_created is False
        assert result.license_obtained is False
        assert result.error is not None
        assert "MediaKeys" in result.error

    async def test_cdm_error_during_init(self, validator, mock_page):
        """Erro do CDM durante inicialização é capturado."""
        call_count = 0

        async def mock_evaluate(js_code):
            nonlocal call_count
            call_count += 1
            if call_count <= 1:
                return None
            return {
                "mediaKeysCreated": True,
                "licenseRequested": True,
                "licenseObtained": False,
                "keyStatus": None,
                "error": {
                    "code": "internal-error",
                    "message": "CDM internal error",
                    "systemCode": 1,
                    "timestamp": 1500,
                },
                "timestamps": {
                    "start": 1000,
                    "mediaKeysCreated": 1100,
                    "licenseRequested": 1200,
                    "licenseObtained": None,
                    "error": 1500,
                },
            }

        mock_page.evaluate = mock_evaluate

        result = await validator.validate_drm_initialization(mock_page)

        assert result.license_obtained is False
        assert result.error is not None
        assert "CDM Error" in result.error


class TestWaitForLicense:
    """Testes de wait_for_license."""

    async def test_license_obtained_successfully(self, validator, mock_page):
        """Licença obtida com sucesso retorna LicenseResult."""
        call_count = 0

        async def mock_evaluate(js_code):
            nonlocal call_count
            call_count += 1
            if call_count <= 1:
                return None
            return {
                "mediaKeysCreated": True,
                "licenseRequested": True,
                "licenseObtained": True,
                "keyStatus": "usable",
                "error": None,
                "timestamps": {},
            }

        mock_page.evaluate = mock_evaluate

        result = await validator.wait_for_license(mock_page)

        assert isinstance(result, LicenseResult)
        assert result.obtained is True
        assert result.key_status == "usable"
        assert result.error is None
        assert result.time_to_license_ms >= 0

    async def test_license_timeout(self, validator, mock_page):
        """Timeout sem licença retorna erro."""
        call_count = 0

        async def mock_evaluate(js_code):
            nonlocal call_count
            call_count += 1
            if call_count <= 1:
                return None
            return {
                "mediaKeysCreated": True,
                "licenseRequested": True,
                "licenseObtained": False,
                "keyStatus": None,
                "error": None,
                "timestamps": {},
            }

        mock_page.evaluate = mock_evaluate

        result = await validator.wait_for_license(mock_page)

        assert result.obtained is False
        assert result.error is not None
        assert "Timeout" in result.error

    async def test_error_during_wait(self, validator, mock_page):
        """Erro durante espera retorna LicenseResult com erro."""
        call_count = 0

        async def mock_evaluate(js_code):
            nonlocal call_count
            call_count += 1
            if call_count <= 1:
                return None
            return {
                "mediaKeysCreated": True,
                "licenseRequested": True,
                "licenseObtained": False,
                "keyStatus": None,
                "error": {
                    "code": "expired",
                    "message": "License expired",
                    "systemCode": 0,
                    "timestamp": 2000,
                },
                "timestamps": {},
            }

        mock_page.evaluate = mock_evaluate

        result = await validator.wait_for_license(mock_page)

        assert result.obtained is False
        assert result.error is not None
        assert "CDM Error" in result.error


class TestCaptureDRMError:
    """Testes de capture_drm_error."""

    async def test_no_error(self, validator, mock_page):
        """Sem erro retorna None."""
        mock_page.evaluate = AsyncMock(return_value={
            "mediaKeysCreated": True,
            "licenseRequested": True,
            "licenseObtained": True,
            "keyStatus": "usable",
            "error": None,
            "timestamps": {},
        })

        result = await validator.capture_drm_error(mock_page)

        assert result is None

    async def test_captures_error(self, validator, mock_page):
        """Erro existente é capturado como DRMError."""
        mock_page.evaluate = AsyncMock(return_value={
            "mediaKeysCreated": True,
            "licenseRequested": True,
            "licenseObtained": False,
            "keyStatus": None,
            "error": {
                "code": "internal-error",
                "message": "CDM initialization failed",
                "systemCode": 42,
                "timestamp": 5000,
            },
            "timestamps": {},
        })

        result = await validator.capture_drm_error(mock_page)

        assert isinstance(result, DRMError)
        assert result.code == "internal-error"
        assert result.message == "CDM initialization failed"
        assert result.system_code == 42
        assert result.timestamp_ms == 5000

    async def test_no_monitor_returns_none(self, validator, mock_page):
        """Sem monitor na página retorna None."""
        mock_page.evaluate = AsyncMock(return_value=None)

        result = await validator.capture_drm_error(mock_page)

        assert result is None
