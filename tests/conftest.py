"""
Configuração compartilhada de fixtures para os testes da PoC Widevine.
"""

import pytest
import numpy as np


@pytest.fixture
def sample_frame_black():
    """Frame completamente preto (1280x720) para testes."""
    return np.zeros((720, 1280, 3), dtype=np.uint8)


@pytest.fixture
def sample_frame_white():
    """Frame completamente branco (1280x720) para testes."""
    return np.full((720, 1280, 3), 255, dtype=np.uint8)


@pytest.fixture
def sample_frame_content():
    """Frame com conteúdo visual variado (1280x720) para testes."""
    rng = np.random.default_rng(42)
    return rng.integers(0, 256, size=(720, 1280, 3), dtype=np.uint8)


@pytest.fixture
def output_dir(tmp_path):
    """Diretório temporário para output de testes."""
    output = tmp_path / "output"
    output.mkdir()
    return output
