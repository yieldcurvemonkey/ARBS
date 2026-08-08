"""Transaction labelling and timeouts (Caching.db_session)."""

from __future__ import annotations

import os

import pytest

from Caching.db_session import (
    APP_NAME_MAX,
    apply_session_settings,
    labelled_transaction,
    make_label,
)


class _RecordingConn:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def execute(self, stmt, params=None):
        self.calls.append((str(stmt), dict(params or {})))
        return None


class _RecordingEngine:
    def __init__(self):
        self.conn = _RecordingConn()
        self.committed = False
        self.rolled_back = False

    def begin(self):
        return self

    def __enter__(self):
        return self.conn

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.committed = True
        else:
            self.rolled_back = True
        return False


class TestMakeLabel:
    def test_shape(self):
        label = make_label("l2_backfill", detail="USD-SOFR-1D")
        assert label.startswith("arbs:l2_backfill:USD-SOFR-1D:")
        assert label.endswith(str(os.getpid()))

    def test_truncates_to_what_postgres_keeps_and_keeps_the_pid(self):
        label = make_label("x" * 200, detail="y" * 200)
        assert len(label) == APP_NAME_MAX
        assert label.endswith(f":{os.getpid()}")

    def test_strips_characters_that_would_need_quoting(self):
        label = make_label("a b'c;drop", detail="d\"e")
        assert "'" not in label and '"' not in label and ";" not in label


class TestApplySessionSettings:
    def test_uses_set_config_with_is_local_true_and_bound_params(self):
        conn = _RecordingConn()
        apply_session_settings(
            conn, label="arbs:test", statement_timeout_ms=0, lock_timeout_ms=5000
        )
        sql = [s for s, _ in conn.calls]
        params = [p for _, p in conn.calls]
        assert len(sql) == 3
        assert all("set_config(" in s and "true)" in s for s in sql), sql
        # The label is a bound parameter, never interpolated: SET takes no binds,
        # and building one by concatenation makes a label an injection point.
        assert params[0] == {"v": "arbs:test"}
        assert params[1] == {"v": "0"}
        assert params[2] == {"v": "5000"}
        assert "application_name" in sql[0]
        assert "statement_timeout" in sql[1]
        assert "lock_timeout" in sql[2]

    def test_omitted_settings_are_not_issued(self):
        conn = _RecordingConn()
        apply_session_settings(conn, label="arbs:test")
        assert len(conn.calls) == 1

    def test_statement_timeout_zero_is_issued_not_skipped(self):
        """0 means 'no limit' and is the point of the call; falsy must not drop it."""
        conn = _RecordingConn()
        apply_session_settings(conn, statement_timeout_ms=0)
        assert conn.calls and conn.calls[0][1] == {"v": "0"}

    def test_label_longer_than_namedatalen_is_truncated_before_it_is_sent(self):
        conn = _RecordingConn()
        apply_session_settings(conn, label="z" * 200)
        assert len(conn.calls[0][1]["v"]) == APP_NAME_MAX


class TestLabelledTransaction:
    def test_settings_land_before_the_body_runs(self):
        engine = _RecordingEngine()
        with labelled_transaction(engine, label="arbs:test", statement_timeout_ms=0) as conn:
            assert len(conn.calls) == 2  # applied before the caller got the conn
            conn.execute("SELECT 1")
        assert engine.committed is True
        assert conn.calls[-1][0] == "SELECT 1"

    def test_exception_propagates_and_the_transaction_is_not_committed(self):
        engine = _RecordingEngine()
        with pytest.raises(ValueError):
            with labelled_transaction(engine, label="arbs:test"):
                raise ValueError("boom")
        assert engine.committed is False
        assert engine.rolled_back is True
