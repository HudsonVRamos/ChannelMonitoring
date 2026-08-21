"""Testes unitários para src/player_discovery/config.py.

Valida a dataclass PlayerDiscoveryConfig:
- Valores padrão corretos
- Carregamento via variáveis de ambiente (prefixo PLAYER_DISCOVERY_)
- Valores inválidos são ignorados (mantém default)
- Conversão para dicionário (to_dict)

Requirements: 4.1, 8.4, 9.4, 10.4, 11.1
"""

import os
from unittest.mock import patch

from src.player_discovery.config import PlayerDiscoveryConfig


class TestPlayerDiscoveryConfigDefaults:
    """Testa valores padrão da configuração."""

    def test_default_discovery_timeout(self):
        config = PlayerDiscoveryConfig()
        assert config.discovery_timeout_s == 60

    def test_default_telemetry_interval(self):
        config = PlayerDiscoveryConfig()
        assert config.telemetry_interval_s == 2.0

    def test_default_observation_period(self):
        config = PlayerDiscoveryConfig()
        assert config.observation_period_s == 30.0

    def test_default_functional_test_interval(self):
        config = PlayerDiscoveryConfig()
        assert config.functional_test_interval == 5

    def test_default_invalidation_threshold(self):
        config = PlayerDiscoveryConfig()
        assert config.invalidation_threshold == 3

    def test_default_debounce_window(self):
        config = PlayerDiscoveryConfig()
        assert config.debounce_window_ms == 500

    def test_default_event_retention(self):
        config = PlayerDiscoveryConfig()
        assert config.event_retention_s == 300

    def test_default_buffer_low_threshold(self):
        config = PlayerDiscoveryConfig()
        assert config.buffer_low_threshold_s == 2.0

    def test_default_escalation_frame_count(self):
        config = PlayerDiscoveryConfig()
        assert config.escalation_frame_count == 3

    def test_default_escalation_frame_interval(self):
        config = PlayerDiscoveryConfig()
        assert config.escalation_frame_interval == 2.0

    def test_default_navigation_timeout(self):
        config = PlayerDiscoveryConfig()
        assert config.navigation_timeout_ms == 30000

    def test_all_defaults_at_once(self):
        """Verifica todos os defaults em uma única instância."""
        config = PlayerDiscoveryConfig()
        assert config.discovery_timeout_s == 60
        assert config.telemetry_interval_s == 2.0
        assert config.observation_period_s == 30.0
        assert config.functional_test_interval == 5
        assert config.invalidation_threshold == 3
        assert config.debounce_window_ms == 500
        assert config.event_retention_s == 300
        assert config.buffer_low_threshold_s == 2.0
        assert config.escalation_frame_count == 3
        assert config.escalation_frame_interval == 2.0
        assert config.navigation_timeout_ms == 30000


class TestPlayerDiscoveryConfigCustomValues:
    """Testa criação com valores customizados."""

    def test_custom_discovery_timeout(self):
        config = PlayerDiscoveryConfig(discovery_timeout_s=120)
        assert config.discovery_timeout_s == 120

    def test_custom_telemetry_interval(self):
        config = PlayerDiscoveryConfig(telemetry_interval_s=1.0)
        assert config.telemetry_interval_s == 1.0

    def test_custom_observation_period(self):
        config = PlayerDiscoveryConfig(observation_period_s=60.0)
        assert config.observation_period_s == 60.0

    def test_custom_functional_test_interval(self):
        config = PlayerDiscoveryConfig(functional_test_interval=10)
        assert config.functional_test_interval == 10

    def test_custom_invalidation_threshold(self):
        config = PlayerDiscoveryConfig(invalidation_threshold=5)
        assert config.invalidation_threshold == 5

    def test_custom_multiple_values(self):
        config = PlayerDiscoveryConfig(
            discovery_timeout_s=90,
            debounce_window_ms=1000,
            event_retention_s=600,
            buffer_low_threshold_s=3.0,
        )
        assert config.discovery_timeout_s == 90
        assert config.debounce_window_ms == 1000
        assert config.event_retention_s == 600
        assert config.buffer_low_threshold_s == 3.0


class TestPlayerDiscoveryConfigFromEnv:
    """Testa carregamento via variáveis de ambiente."""

    def test_from_env_int_fields(self):
        env = {
            "PLAYER_DISCOVERY_DISCOVERY_TIMEOUT_S": "90",
            "PLAYER_DISCOVERY_FUNCTIONAL_TEST_INTERVAL": "10",
            "PLAYER_DISCOVERY_INVALIDATION_THRESHOLD": "5",
            "PLAYER_DISCOVERY_DEBOUNCE_WINDOW_MS": "1000",
            "PLAYER_DISCOVERY_EVENT_RETENTION_S": "600",
            "PLAYER_DISCOVERY_ESCALATION_FRAME_COUNT": "5",
            "PLAYER_DISCOVERY_NAVIGATION_TIMEOUT_MS": "60000",
        }
        with patch.dict(os.environ, env, clear=False):
            config = PlayerDiscoveryConfig.from_env()
        assert config.discovery_timeout_s == 90
        assert config.functional_test_interval == 10
        assert config.invalidation_threshold == 5
        assert config.debounce_window_ms == 1000
        assert config.event_retention_s == 600
        assert config.escalation_frame_count == 5
        assert config.navigation_timeout_ms == 60000

    def test_from_env_float_fields(self):
        env = {
            "PLAYER_DISCOVERY_TELEMETRY_INTERVAL_S": "1.5",
            "PLAYER_DISCOVERY_OBSERVATION_PERIOD_S": "45.0",
            "PLAYER_DISCOVERY_BUFFER_LOW_THRESHOLD_S": "3.5",
            "PLAYER_DISCOVERY_ESCALATION_FRAME_INTERVAL": "1.0",
        }
        with patch.dict(os.environ, env, clear=False):
            config = PlayerDiscoveryConfig.from_env()
        assert config.telemetry_interval_s == 1.5
        assert config.observation_period_s == 45.0
        assert config.buffer_low_threshold_s == 3.5
        assert config.escalation_frame_interval == 1.0

    def test_from_env_invalid_int_ignored(self):
        env = {
            "PLAYER_DISCOVERY_DISCOVERY_TIMEOUT_S": "not_a_number",
            "PLAYER_DISCOVERY_INVALIDATION_THRESHOLD": "abc",
        }
        with patch.dict(os.environ, env, clear=False):
            config = PlayerDiscoveryConfig.from_env()
        # Valores inválidos mantêm os defaults
        assert config.discovery_timeout_s == 60
        assert config.invalidation_threshold == 3

    def test_from_env_invalid_float_ignored(self):
        env = {
            "PLAYER_DISCOVERY_TELEMETRY_INTERVAL_S": "invalid",
            "PLAYER_DISCOVERY_OBSERVATION_PERIOD_S": "xyz",
        }
        with patch.dict(os.environ, env, clear=False):
            config = PlayerDiscoveryConfig.from_env()
        assert config.telemetry_interval_s == 2.0
        assert config.observation_period_s == 30.0

    def test_from_env_empty_string_ignored(self):
        env = {
            "PLAYER_DISCOVERY_DISCOVERY_TIMEOUT_S": "",
        }
        with patch.dict(os.environ, env, clear=False):
            config = PlayerDiscoveryConfig.from_env()
        # String vazia falha na conversão int, mantém default
        assert config.discovery_timeout_s == 60

    def test_from_env_no_env_vars_uses_defaults(self):
        """Sem variáveis PLAYER_DISCOVERY_ definidas, usa defaults."""
        clean_env = {
            k: v for k, v in os.environ.items()
            if not k.startswith("PLAYER_DISCOVERY_")
        }
        with patch.dict(os.environ, clean_env, clear=True):
            config = PlayerDiscoveryConfig.from_env()
        assert config.discovery_timeout_s == 60
        assert config.telemetry_interval_s == 2.0
        assert config.observation_period_s == 30.0
        assert config.functional_test_interval == 5
        assert config.invalidation_threshold == 3
        assert config.debounce_window_ms == 500
        assert config.event_retention_s == 300
        assert config.buffer_low_threshold_s == 2.0

    def test_from_env_partial_override(self):
        """Somente variáveis presentes sobrescrevem os defaults."""
        env = {
            "PLAYER_DISCOVERY_OBSERVATION_PERIOD_S": "60.0",
        }
        with patch.dict(os.environ, env, clear=False):
            config = PlayerDiscoveryConfig.from_env()
        # Sobrescrito
        assert config.observation_period_s == 60.0
        # Defaults mantidos
        assert config.discovery_timeout_s == 60
        assert config.telemetry_interval_s == 2.0


class TestPlayerDiscoveryConfigToDict:
    """Testa conversão para dicionário."""

    def test_to_dict_contains_all_fields(self):
        config = PlayerDiscoveryConfig()
        d = config.to_dict()
        expected_keys = {
            "discovery_timeout_s",
            "telemetry_interval_s",
            "observation_period_s",
            "functional_test_interval",
            "invalidation_threshold",
            "debounce_window_ms",
            "event_retention_s",
            "buffer_low_threshold_s",
            "escalation_frame_count",
            "escalation_frame_interval",
            "navigation_timeout_ms",
        }
        assert set(d.keys()) == expected_keys

    def test_to_dict_values_match_config(self):
        config = PlayerDiscoveryConfig(
            discovery_timeout_s=90,
            telemetry_interval_s=1.5,
            observation_period_s=45.0,
        )
        d = config.to_dict()
        assert d["discovery_timeout_s"] == 90
        assert d["telemetry_interval_s"] == 1.5
        assert d["observation_period_s"] == 45.0

    def test_to_dict_with_defaults(self):
        config = PlayerDiscoveryConfig()
        d = config.to_dict()
        assert d["discovery_timeout_s"] == 60
        assert d["telemetry_interval_s"] == 2.0
        assert d["observation_period_s"] == 30.0
        assert d["functional_test_interval"] == 5
        assert d["invalidation_threshold"] == 3
        assert d["debounce_window_ms"] == 500
        assert d["event_retention_s"] == 300
        assert d["buffer_low_threshold_s"] == 2.0
        assert d["escalation_frame_count"] == 3
        assert d["escalation_frame_interval"] == 2.0
        assert d["navigation_timeout_ms"] == 30000


class TestPlayerDiscoveryConfigIsDataclass:
    """Testa propriedades da dataclass."""

    def test_is_dataclass(self):
        """Verifica que PlayerDiscoveryConfig é uma dataclass."""
        from dataclasses import fields
        config = PlayerDiscoveryConfig()
        field_names = [f.name for f in fields(config)]
        assert "discovery_timeout_s" in field_names
        assert "telemetry_interval_s" in field_names
        assert "observation_period_s" in field_names

    def test_equality(self):
        """Dataclasses com mesmos valores são iguais."""
        config1 = PlayerDiscoveryConfig()
        config2 = PlayerDiscoveryConfig()
        assert config1 == config2

    def test_inequality(self):
        """Dataclasses com valores diferentes são desiguais."""
        config1 = PlayerDiscoveryConfig()
        config2 = PlayerDiscoveryConfig(discovery_timeout_s=120)
        assert config1 != config2
