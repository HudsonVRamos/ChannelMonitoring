"""Testes unitários e property-based tests para UnifiedMonitorConfig.

Valida defaults, parsing de env vars, tratamento de valores inválidos,
e parsing de channels como lista comma-separated.
"""

from __future__ import annotations

import logging
import os
from unittest.mock import patch

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from src.unified_channel_monitor.config import UnifiedMonitorConfig


class TestUnifiedMonitorConfigDefaults:
    """Valida que todos os defaults estão corretos conforme design."""

    def test_default_channels_is_empty_list(self):
        cfg = UnifiedMonitorConfig()
        assert cfg.channels == []

    def test_default_telemetry_interval(self):
        cfg = UnifiedMonitorConfig()
        assert cfg.telemetry_interval_s == 2.0

    def test_default_observation_period(self):
        cfg = UnifiedMonitorConfig()
        assert cfg.observation_period_s == 30.0

    def test_default_freeze_consecutive_samples(self):
        cfg = UnifiedMonitorConfig()
        assert cfg.freeze_consecutive_samples == 3

    def test_default_audio_telemetry_window(self):
        cfg = UnifiedMonitorConfig()
        assert cfg.audio_telemetry_window_s == 30.0

    def test_default_audio_sample_interval(self):
        cfg = UnifiedMonitorConfig()
        assert cfg.audio_sample_interval_s == 2.0

    def test_default_audio_pass_threshold(self):
        cfg = UnifiedMonitorConfig()
        assert cfg.audio_pass_threshold == 0.80

    def test_default_audio_rms_threshold(self):
        cfg = UnifiedMonitorConfig()
        assert cfg.audio_rms_threshold == 0.01

    def test_default_subtitle_cue_timeout(self):
        cfg = UnifiedMonitorConfig()
        assert cfg.subtitle_cue_timeout_s == 15.0

    def test_default_subtitle_poll_interval(self):
        cfg = UnifiedMonitorConfig()
        assert cfg.subtitle_poll_interval_s == 0.5

    def test_default_track_switch_timeout(self):
        cfg = UnifiedMonitorConfig()
        assert cfg.track_switch_timeout_s == 5.0

    def test_default_invalidation_threshold(self):
        cfg = UnifiedMonitorConfig()
        assert cfg.invalidation_threshold == 3

    def test_default_output_dir(self):
        cfg = UnifiedMonitorConfig()
        assert cfg.output_dir == "reports/"

    def test_default_log_level(self):
        cfg = UnifiedMonitorConfig()
        assert cfg.log_level == "INFO"

    def test_default_chrome_profile_dir(self):
        cfg = UnifiedMonitorConfig()
        assert cfg.chrome_profile_dir == ""

    def test_default_playback_wait_timeout(self):
        cfg = UnifiedMonitorConfig()
        assert cfg.playback_wait_timeout_s == 30.0

    def test_default_continuous(self):
        cfg = UnifiedMonitorConfig()
        assert cfg.continuous is False


class TestFromEnvChannelsParsing:
    """Valida parsing de UNIFIED_MONITOR_CHANNELS como lista comma-separated."""

    def test_channels_basic_parsing(self):
        env = {"UNIFIED_MONITOR_CHANNELS": "https://a.com,https://b.com"}
        with patch.dict(os.environ, env, clear=True):
            cfg = UnifiedMonitorConfig.from_env()
        assert cfg.channels == ["https://a.com", "https://b.com"]

    def test_channels_with_whitespace_trimmed(self):
        env = {"UNIFIED_MONITOR_CHANNELS": "  https://a.com , https://b.com  "}
        with patch.dict(os.environ, env, clear=True):
            cfg = UnifiedMonitorConfig.from_env()
        assert cfg.channels == ["https://a.com", "https://b.com"]

    def test_channels_empty_entries_removed(self):
        env = {"UNIFIED_MONITOR_CHANNELS": "https://a.com,,, ,https://b.com,"}
        with patch.dict(os.environ, env, clear=True):
            cfg = UnifiedMonitorConfig.from_env()
        assert cfg.channels == ["https://a.com", "https://b.com"]

    def test_channels_empty_string_gives_empty_list(self):
        env = {"UNIFIED_MONITOR_CHANNELS": ""}
        with patch.dict(os.environ, env, clear=True):
            cfg = UnifiedMonitorConfig.from_env()
        assert cfg.channels == []

    def test_channels_not_set_gives_empty_list(self):
        with patch.dict(os.environ, {}, clear=True):
            cfg = UnifiedMonitorConfig.from_env()
        assert cfg.channels == []

    def test_channels_single_url(self):
        env = {"UNIFIED_MONITOR_CHANNELS": "https://only.com"}
        with patch.dict(os.environ, env, clear=True):
            cfg = UnifiedMonitorConfig.from_env()
        assert cfg.channels == ["https://only.com"]

    def test_channels_preserves_order(self):
        env = {"UNIFIED_MONITOR_CHANNELS": "https://c.com,https://a.com,https://b.com"}
        with patch.dict(os.environ, env, clear=True):
            cfg = UnifiedMonitorConfig.from_env()
        assert cfg.channels == ["https://c.com", "https://a.com", "https://b.com"]


class TestFromEnvNumericParsing:
    """Valida parsing de campos numéricos (float e int)."""

    def test_float_field_parsed_correctly(self):
        env = {"UNIFIED_MONITOR_TELEMETRY_INTERVAL_S": "5.5"}
        with patch.dict(os.environ, env, clear=True):
            cfg = UnifiedMonitorConfig.from_env()
        assert cfg.telemetry_interval_s == 5.5

    def test_int_field_parsed_correctly(self):
        env = {"UNIFIED_MONITOR_INVALIDATION_THRESHOLD": "10"}
        with patch.dict(os.environ, env, clear=True):
            cfg = UnifiedMonitorConfig.from_env()
        assert cfg.invalidation_threshold == 10

    def test_invalid_float_keeps_default_and_logs_warning(self, caplog):
        env = {"UNIFIED_MONITOR_TELEMETRY_INTERVAL_S": "not_a_number"}
        with patch.dict(os.environ, env, clear=True):
            with caplog.at_level(logging.WARNING):
                cfg = UnifiedMonitorConfig.from_env()
        assert cfg.telemetry_interval_s == 2.0
        assert "Valor inválido" in caplog.text

    def test_invalid_int_keeps_default_and_logs_warning(self, caplog):
        env = {"UNIFIED_MONITOR_FREEZE_CONSECUTIVE_SAMPLES": "abc"}
        with patch.dict(os.environ, env, clear=True):
            with caplog.at_level(logging.WARNING):
                cfg = UnifiedMonitorConfig.from_env()
        assert cfg.freeze_consecutive_samples == 3
        assert "Valor inválido" in caplog.text

    def test_all_float_fields_can_be_overridden(self):
        env = {
            "UNIFIED_MONITOR_TELEMETRY_INTERVAL_S": "1.0",
            "UNIFIED_MONITOR_OBSERVATION_PERIOD_S": "60.0",
            "UNIFIED_MONITOR_AUDIO_TELEMETRY_WINDOW_S": "45.0",
            "UNIFIED_MONITOR_AUDIO_SAMPLE_INTERVAL_S": "3.0",
            "UNIFIED_MONITOR_AUDIO_PASS_THRESHOLD": "0.90",
            "UNIFIED_MONITOR_AUDIO_RMS_THRESHOLD": "0.02",
            "UNIFIED_MONITOR_SUBTITLE_CUE_TIMEOUT_S": "20.0",
            "UNIFIED_MONITOR_SUBTITLE_POLL_INTERVAL_S": "1.0",
            "UNIFIED_MONITOR_TRACK_SWITCH_TIMEOUT_S": "10.0",
            "UNIFIED_MONITOR_PLAYBACK_WAIT_TIMEOUT_S": "45.0",
        }
        with patch.dict(os.environ, env, clear=True):
            cfg = UnifiedMonitorConfig.from_env()
        assert cfg.telemetry_interval_s == 1.0
        assert cfg.observation_period_s == 60.0
        assert cfg.audio_telemetry_window_s == 45.0
        assert cfg.audio_sample_interval_s == 3.0
        assert cfg.audio_pass_threshold == 0.90
        assert cfg.audio_rms_threshold == 0.02
        assert cfg.subtitle_cue_timeout_s == 20.0
        assert cfg.subtitle_poll_interval_s == 1.0
        assert cfg.track_switch_timeout_s == 10.0
        assert cfg.playback_wait_timeout_s == 45.0


class TestFromEnvStringFields:
    """Valida parsing de campos string (output_dir, log_level)."""

    def test_output_dir_overridden(self):
        env = {"UNIFIED_MONITOR_OUTPUT_DIR": "/custom/output"}
        with patch.dict(os.environ, env, clear=True):
            cfg = UnifiedMonitorConfig.from_env()
        assert cfg.output_dir == "/custom/output"

    def test_log_level_overridden(self):
        env = {"UNIFIED_MONITOR_LOG_LEVEL": "DEBUG"}
        with patch.dict(os.environ, env, clear=True):
            cfg = UnifiedMonitorConfig.from_env()
        assert cfg.log_level == "DEBUG"


class TestFromEnvChromeProfileDir:
    """Valida leitura de CHROME_PROFILE_DIR sem prefixo (Req 1.5)."""

    def test_chrome_profile_dir_without_prefix(self):
        env = {"CHROME_PROFILE_DIR": "/home/user/.chrome"}
        with patch.dict(os.environ, env, clear=True):
            cfg = UnifiedMonitorConfig.from_env()
        assert cfg.chrome_profile_dir == "/home/user/.chrome"

    def test_chrome_profile_dir_with_prefix_as_fallback(self):
        env = {"UNIFIED_MONITOR_CHROME_PROFILE_DIR": "/fallback/path"}
        with patch.dict(os.environ, env, clear=True):
            cfg = UnifiedMonitorConfig.from_env()
        assert cfg.chrome_profile_dir == "/fallback/path"

    def test_chrome_profile_dir_prefers_without_prefix(self):
        env = {
            "CHROME_PROFILE_DIR": "/primary/path",
            "UNIFIED_MONITOR_CHROME_PROFILE_DIR": "/fallback/path",
        }
        with patch.dict(os.environ, env, clear=True):
            cfg = UnifiedMonitorConfig.from_env()
        assert cfg.chrome_profile_dir == "/primary/path"


class TestFromEnvContinuous:
    """Valida parsing do campo booleano continuous."""

    @pytest.mark.parametrize("value", ["true", "True", "TRUE", "1", "yes", "YES"])
    def test_continuous_truthy_values(self, value):
        env = {"UNIFIED_MONITOR_CONTINUOUS": value}
        with patch.dict(os.environ, env, clear=True):
            cfg = UnifiedMonitorConfig.from_env()
        assert cfg.continuous is True

    @pytest.mark.parametrize("value", ["false", "0", "no", "anything", ""])
    def test_continuous_falsy_values(self, value):
        env = {"UNIFIED_MONITOR_CONTINUOUS": value}
        with patch.dict(os.environ, env, clear=True):
            cfg = UnifiedMonitorConfig.from_env()
        assert cfg.continuous is False


# Feature: unified-channel-monitor, Property 1: Configuration parsing round-trip


# Estratégia: caracteres válidos para URLs (sem vírgula, pois é o separador)
_url_chars = st.sampled_from(
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "0123456789"
    "-._~:/?#[]@!$&'()*+;=%"
)

# Gera string URL-like não vazia (1-80 chars do alfabeto URL)
_url_entry = st.text(
    alphabet=_url_chars, min_size=1, max_size=80
)

# Gera whitespace arbitrário (espaços e tabs)
_whitespace = st.text(
    alphabet=st.sampled_from(" \t"), min_size=0, max_size=5
)

# Gera uma entrada que pode ser URL válida, vazia, ou só whitespace
_channel_entry = st.one_of(
    _url_entry,                         # entrada válida
    st.just(""),                         # entrada vazia
    _whitespace,                         # apenas whitespace
)


class TestPropertyConfigParsingRoundTrip:
    """Property 1: Configuration parsing round-trip.

    Validates: Requirements 1.4, 10.1, 10.3
    """

    @given(
        entries=st.lists(_channel_entry, min_size=0, max_size=20),
        separators=st.lists(
            st.tuples(_whitespace, _whitespace),
            min_size=0, max_size=19,
        ),
    )
    @settings(max_examples=100)
    def test_config_parsing_round_trip(self, entries, separators):
        """Para qualquer string comma-separated de URLs com whitespace
        arbitrário e entradas vazias, from_env() produz uma lista
        onde cada entrada não-vazia está presente, trimada e na
        ordem original.

        **Validates: Requirements 1.4, 10.1, 10.3**
        """
        # Constrói a string comma-separated com whitespace ao redor
        # das vírgulas
        parts = []
        for i, entry in enumerate(entries):
            if i > 0 and i - 1 < len(separators):
                ws_before, ws_after = separators[i - 1]
                parts.append(ws_before + "," + ws_after)
            elif i > 0:
                parts.append(",")
            parts.append(entry)

        channels_raw = "".join(parts)

        # Parse via from_env()
        env = {"UNIFIED_MONITOR_CHANNELS": channels_raw}
        with patch.dict(os.environ, env, clear=True):
            cfg = UnifiedMonitorConfig.from_env()

        # Expectativa: entradas não-vazias (após trim), na ordem
        expected = [
            e.strip() for e in entries if e.strip()
        ]

        # 1. Todas as entradas não-vazias estão presentes após trim
        assert cfg.channels == expected

        # 2. Ordem preservada (já coberto por ==, mas explícito)
        for i, ch in enumerate(cfg.channels):
            assert ch == expected[i]

        # 3. Nenhuma entrada vazia/whitespace-only presente
        for ch in cfg.channels:
            assert ch != ""
            assert ch.strip() == ch  # está trimado

# Feature: unified-channel-monitor, Property 2: Configuration robustness against invalid values  # noqa: E501
class TestConfigRobustnessProperty:
    """Property 2: Configuration robustness against invalid values.

    Para qualquer variável de ambiente que espera um valor numérico
    (int ou float), se o valor é uma string não-numérica,
    from_env() retorna o default para aquele campo e o default
    original é preservado inalterado.

    **Validates: Requirements 10.4**
    """

    # Campos float com seus env var names e defaults
    FLOAT_FIELDS: list[tuple[str, str, float]] = [
        (
            "telemetry_interval_s",
            "UNIFIED_MONITOR_TELEMETRY_INTERVAL_S",
            2.0,
        ),
        (
            "observation_period_s",
            "UNIFIED_MONITOR_OBSERVATION_PERIOD_S",
            30.0,
        ),
        (
            "audio_telemetry_window_s",
            "UNIFIED_MONITOR_AUDIO_TELEMETRY_WINDOW_S",
            30.0,
        ),
        (
            "audio_sample_interval_s",
            "UNIFIED_MONITOR_AUDIO_SAMPLE_INTERVAL_S",
            2.0,
        ),
        (
            "audio_pass_threshold",
            "UNIFIED_MONITOR_AUDIO_PASS_THRESHOLD",
            0.80,
        ),
        (
            "audio_rms_threshold",
            "UNIFIED_MONITOR_AUDIO_RMS_THRESHOLD",
            0.01,
        ),
        (
            "subtitle_cue_timeout_s",
            "UNIFIED_MONITOR_SUBTITLE_CUE_TIMEOUT_S",
            15.0,
        ),
        (
            "subtitle_poll_interval_s",
            "UNIFIED_MONITOR_SUBTITLE_POLL_INTERVAL_S",
            0.5,
        ),
        (
            "track_switch_timeout_s",
            "UNIFIED_MONITOR_TRACK_SWITCH_TIMEOUT_S",
            5.0,
        ),
        (
            "playback_wait_timeout_s",
            "UNIFIED_MONITOR_PLAYBACK_WAIT_TIMEOUT_S",
            30.0,
        ),
    ]

    # Campos int com seus env var names e defaults
    INT_FIELDS: list[tuple[str, str, int]] = [
        (
            "freeze_consecutive_samples",
            "UNIFIED_MONITOR_FREEZE_CONSECUTIVE_SAMPLES",
            3,
        ),
        (
            "invalidation_threshold",
            "UNIFIED_MONITOR_INVALIDATION_THRESHOLD",
            3,
        ),
    ]

    @staticmethod
    def _is_valid_float(s: str) -> bool:
        """Verifica se a string pode ser parseada como float."""
        try:
            float(s)
            return True
        except (ValueError, TypeError):
            return False

    @staticmethod
    def _is_valid_int(s: str) -> bool:
        """Verifica se a string pode ser parseada como int."""
        try:
            int(s)
            return True
        except (ValueError, TypeError):
            return False

    @given(
        invalid_value=st.text(min_size=1).filter(
            lambda s: not TestConfigRobustnessProperty._is_valid_float(
                s
            )
        )
    )
    @settings(max_examples=100)
    def test_float_fields_reject_non_numeric(
        self, invalid_value: str
    ) -> None:
        """Para qualquer string não-numérica, campos float usam default.

        **Validates: Requirements 10.4**
        """
        default_cfg = UnifiedMonitorConfig()

        for field_name, env_var, expected_default in self.FLOAT_FIELDS:
            env = {env_var: invalid_value}
            with patch.dict(os.environ, env, clear=True):
                cfg = UnifiedMonitorConfig.from_env()

            # O campo deve ter o valor default
            parsed_value = getattr(cfg, field_name)
            assert parsed_value == expected_default, (
                f"Campo {field_name} com valor inválido "
                f"'{invalid_value}' deveria ser "
                f"{expected_default}, mas foi {parsed_value}"
            )

            # O default original não foi alterado
            original_default = getattr(default_cfg, field_name)
            assert original_default == expected_default, (
                f"Default original de {field_name} foi "
                f"alterado para {original_default}"
            )

    @given(
        invalid_value=st.text(min_size=1).filter(
            lambda s: not TestConfigRobustnessProperty._is_valid_int(
                s
            )
        )
    )
    @settings(max_examples=100)
    def test_int_fields_reject_non_numeric(
        self, invalid_value: str
    ) -> None:
        """Para qualquer string não-numérica, campos int usam default.

        **Validates: Requirements 10.4**
        """
        default_cfg = UnifiedMonitorConfig()

        for field_name, env_var, expected_default in self.INT_FIELDS:
            env = {env_var: invalid_value}
            with patch.dict(os.environ, env, clear=True):
                cfg = UnifiedMonitorConfig.from_env()

            # O campo deve ter o valor default
            parsed_value = getattr(cfg, field_name)
            assert parsed_value == expected_default, (
                f"Campo {field_name} com valor inválido "
                f"'{invalid_value}' deveria ser "
                f"{expected_default}, mas foi {parsed_value}"
            )

            # O default original não foi alterado
            original_default = getattr(default_cfg, field_name)
            assert original_default == expected_default, (
                f"Default original de {field_name} foi "
                f"alterado para {original_default}"
            )
