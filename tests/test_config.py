"""Testes unitários para src/config.py."""

import os
from unittest.mock import patch

import pytest

from src.config import PoCConfig


class TestPoCConfigDefaults:
    """Testa valores padrão da configuração."""

    def test_default_values(self):
        config = PoCConfig()
        assert config.storage_state_path == ""
        assert config.channel_url == ""
        assert config.output_dir == "./output"
        assert config.log_level == "INFO"
        assert config.session_restore_timeout == 15
        assert config.drm_timeout == 15
        assert config.playback_timeout == 30
        assert config.bedrock_timeout == 30
        assert config.docker_startup_timeout == 60
        assert config.telemetry_interval == 2.0
        assert config.telemetry_duration == 30.0
        assert config.frame_interval == 5.0
        assert config.frame_min_resolution == (1280, 720)
        assert config.frame_max_size == 5 * 1024 * 1024
        assert config.black_screen_luminance_threshold == 10.0
        assert config.black_pixel_value_threshold == 20
        assert config.black_pixel_percent_threshold == 95.0
        assert config.variance_threshold == 50.0
        assert config.freeze_similarity_threshold == 0.98
        assert config.freeze_observation_window == 5.0
        assert config.buffering_threshold == 10.0
        assert config.bedrock_region == "us-east-1"
        assert config.bedrock_confidence_threshold == 0.7

    def test_custom_values(self):
        config = PoCConfig(
            storage_state_path="/path/to/state.json",
            channel_url="https://example.com/channel",
            log_level="DEBUG",
            drm_timeout=30,
            frame_interval=10.0,
        )
        assert config.storage_state_path == "/path/to/state.json"
        assert config.channel_url == "https://example.com/channel"
        assert config.log_level == "DEBUG"
        assert config.drm_timeout == 30
        assert config.frame_interval == 10.0


class TestPoCConfigFromEnv:
    """Testa carregamento via variáveis de ambiente."""

    def test_from_env_string_fields(self):
        env = {
            "POC_STORAGE_STATE_PATH": "/env/state.json",
            "POC_CHANNEL_URL": "https://env.example.com",
            "POC_LOG_LEVEL": "DEBUG",
            "POC_OUTPUT_DIR": "/env/output",
            "POC_BEDROCK_REGION": "us-west-2",
        }
        with patch.dict(os.environ, env, clear=False):
            config = PoCConfig.from_env()
        assert config.storage_state_path == "/env/state.json"
        assert config.channel_url == "https://env.example.com"
        assert config.log_level == "DEBUG"
        assert config.output_dir == "/env/output"
        assert config.bedrock_region == "us-west-2"

    def test_from_env_int_fields(self):
        env = {
            "POC_DRM_TIMEOUT": "25",
            "POC_PLAYBACK_TIMEOUT": "45",
            "POC_SESSION_RESTORE_TIMEOUT": "20",
            "POC_DOCKER_STARTUP_TIMEOUT": "90",
            "POC_BLACK_PIXEL_VALUE_THRESHOLD": "30",
        }
        with patch.dict(os.environ, env, clear=False):
            config = PoCConfig.from_env()
        assert config.drm_timeout == 25
        assert config.playback_timeout == 45
        assert config.session_restore_timeout == 20
        assert config.docker_startup_timeout == 90
        assert config.black_pixel_value_threshold == 30

    def test_from_env_float_fields(self):
        env = {
            "POC_TELEMETRY_INTERVAL": "1.5",
            "POC_FRAME_INTERVAL": "10.0",
            "POC_FREEZE_SIMILARITY_THRESHOLD": "0.95",
            "POC_BEDROCK_CONFIDENCE_THRESHOLD": "0.8",
            "POC_BUFFERING_THRESHOLD": "15.0",
        }
        with patch.dict(os.environ, env, clear=False):
            config = PoCConfig.from_env()
        assert config.telemetry_interval == 1.5
        assert config.frame_interval == 10.0
        assert config.freeze_similarity_threshold == 0.95
        assert config.bedrock_confidence_threshold == 0.8
        assert config.buffering_threshold == 15.0

    def test_from_env_frame_min_resolution(self):
        env = {"POC_FRAME_MIN_RESOLUTION": "1920x1080"}
        with patch.dict(os.environ, env, clear=False):
            config = PoCConfig.from_env()
        assert config.frame_min_resolution == (1920, 1080)

    def test_from_env_invalid_values_ignored(self):
        env = {
            "POC_DRM_TIMEOUT": "not_a_number",
            "POC_FRAME_INTERVAL": "invalid",
            "POC_FRAME_MIN_RESOLUTION": "badformat",
        }
        with patch.dict(os.environ, env, clear=False):
            config = PoCConfig.from_env()
        # Valores inválidos mantêm os defaults
        assert config.drm_timeout == 15
        assert config.frame_interval == 5.0
        assert config.frame_min_resolution == (1280, 720)

    def test_from_env_no_env_vars_uses_defaults(self):
        # Limpa qualquer variável POC_ que possa estar setada
        env_to_remove = [k for k in os.environ if k.startswith("POC_")]
        clean_env = {k: v for k, v in os.environ.items() if not k.startswith("POC_")}
        with patch.dict(os.environ, clean_env, clear=True):
            config = PoCConfig.from_env()
        assert config.log_level == "INFO"
        assert config.drm_timeout == 15


class TestPoCConfigValidate:
    """Testa método de validação."""

    def test_valid_config(self):
        config = PoCConfig(
            storage_state_path="/path/to/state.json",
            channel_url="https://example.com/channel",
        )
        errors = config.validate()
        assert errors == []

    def test_empty_storage_state_path(self):
        config = PoCConfig(channel_url="https://example.com")
        errors = config.validate()
        assert any("storage_state_path" in e for e in errors)

    def test_empty_channel_url(self):
        config = PoCConfig(storage_state_path="/path/state.json")
        errors = config.validate()
        assert any("channel_url" in e for e in errors)

    def test_frame_interval_below_range(self):
        config = PoCConfig(
            storage_state_path="/path",
            channel_url="https://url",
            frame_interval=0.5,
        )
        errors = config.validate()
        assert any("frame_interval" in e for e in errors)

    def test_frame_interval_above_range(self):
        config = PoCConfig(
            storage_state_path="/path",
            channel_url="https://url",
            frame_interval=61.0,
        )
        errors = config.validate()
        assert any("frame_interval" in e for e in errors)

    def test_frame_interval_at_boundaries(self):
        # Exatamente 1 e 60 devem ser válidos
        config_min = PoCConfig(
            storage_state_path="/path",
            channel_url="https://url",
            frame_interval=1.0,
        )
        config_max = PoCConfig(
            storage_state_path="/path",
            channel_url="https://url",
            frame_interval=60.0,
        )
        assert config_min.validate() == []
        assert config_max.validate() == []

    def test_invalid_freeze_similarity_threshold(self):
        config = PoCConfig(
            storage_state_path="/path",
            channel_url="https://url",
            freeze_similarity_threshold=1.5,
        )
        errors = config.validate()
        assert any("freeze_similarity_threshold" in e for e in errors)

    def test_invalid_bedrock_confidence_threshold(self):
        config = PoCConfig(
            storage_state_path="/path",
            channel_url="https://url",
            bedrock_confidence_threshold=-0.1,
        )
        errors = config.validate()
        assert any("bedrock_confidence_threshold" in e for e in errors)

    def test_invalid_luminance_threshold(self):
        config = PoCConfig(
            storage_state_path="/path",
            channel_url="https://url",
            black_screen_luminance_threshold=300.0,
        )
        errors = config.validate()
        assert any("black_screen_luminance_threshold" in e for e in errors)

    def test_negative_timeout(self):
        config = PoCConfig(
            storage_state_path="/path",
            channel_url="https://url",
            drm_timeout=-1,
        )
        errors = config.validate()
        assert any("drm_timeout" in e for e in errors)

    def test_multiple_errors(self):
        config = PoCConfig(
            frame_interval=0.1,
            freeze_similarity_threshold=2.0,
        )
        errors = config.validate()
        # Deve ter pelo menos 3 erros: storage_state, channel_url, frame_interval, freeze
        assert len(errors) >= 3
