"""Strict, call-time L2 mode parsing."""

from __future__ import annotations

import pytest

from Caching.l2_policy import (
    SWAPTION_CUBE_L2_ENV,
    L2Mode,
    L2ModeError,
    env_l2_mode,
    parse_l2_mode,
    swaption_cube_l2_mode,
)


class TestVocabulary:
    @pytest.mark.parametrize("token", [None, "", "  ", "0", "off", "false", "f", "no", "n"])
    def test_off_tokens(self, token):
        assert parse_l2_mode(token) is L2Mode.OFF

    @pytest.mark.parametrize("token", ["none", "null", "disabled", "DISABLED", " None "])
    def test_tokens_that_env_enabled_reads_as_ENABLED_are_off_here(self, token):
        """``_env_enabled`` treats every one of these as enabled, i.e. production."""
        from Caching.supabase_engine import _env_enabled

        import os

        os.environ["_ARBS_L2_POLICY_PROBE"] = token
        try:
            assert _env_enabled("_ARBS_L2_POLICY_PROBE") is True  # the trap, restated
        finally:
            del os.environ["_ARBS_L2_POLICY_PROBE"]
        assert parse_l2_mode(token) is L2Mode.OFF

    @pytest.mark.parametrize("token", ["read", "ro", "readonly", "read_only", "READ-ONLY", "pull"])
    def test_read_tokens(self, token):
        assert parse_l2_mode(token) is L2Mode.READ

    @pytest.mark.parametrize("token", ["1", "on", "true", "yes", "rw", "read_write", "PUSH"])
    def test_read_write_tokens(self, token):
        assert parse_l2_mode(token) is L2Mode.READ_WRITE

    @pytest.mark.parametrize("token", ["nope", "enabled", "2", "yess", "write", "rwx"])
    def test_unknown_token_raises_rather_than_guessing(self, token):
        with pytest.raises(L2ModeError) as excinfo:
            parse_l2_mode(token, var_name="ARBS_THING")
        message = str(excinfo.value)
        assert "ARBS_THING" in message
        assert token in message
        assert "read_write" in message  # the accepted vocabulary is named

    def test_write_implies_read(self):
        assert L2Mode.READ_WRITE.reads and L2Mode.READ_WRITE.writes
        assert L2Mode.READ.reads and not L2Mode.READ.writes
        assert not L2Mode.OFF.reads and not L2Mode.OFF.writes


class TestReadAtCallTime:
    def test_mode_follows_the_environment_without_a_reload(self, monkeypatch):
        """The property ``supabase_engine`` lacks: no import-order sensitivity."""
        monkeypatch.delenv(SWAPTION_CUBE_L2_ENV, raising=False)
        assert swaption_cube_l2_mode() is L2Mode.OFF
        monkeypatch.setenv(SWAPTION_CUBE_L2_ENV, "rw")
        assert swaption_cube_l2_mode() is L2Mode.READ_WRITE
        monkeypatch.setenv(SWAPTION_CUBE_L2_ENV, "read")
        assert swaption_cube_l2_mode() is L2Mode.READ
        monkeypatch.setenv(SWAPTION_CUBE_L2_ENV, "0")
        assert swaption_cube_l2_mode() is L2Mode.OFF

    def test_default_is_off(self, monkeypatch):
        monkeypatch.delenv(SWAPTION_CUBE_L2_ENV, raising=False)
        assert env_l2_mode(SWAPTION_CUBE_L2_ENV) is L2Mode.OFF
