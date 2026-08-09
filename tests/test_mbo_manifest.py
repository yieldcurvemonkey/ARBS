"""Manifest and resume tests.

Resume that ignores the engine version is how a store ends up holding two
vintages of derived data that nothing can tell apart afterwards.
"""
from __future__ import annotations

import datetime

import pandas as pd
import pytest

from RVUtils.MBO.store import manifest as mf

D1 = datetime.date(2026, 7, 14)
D2 = datetime.date(2026, 7, 15)


def _row(product="ZN", date=D1, kind="tob", version="v1", status="OK", tier="wide"):
    return {
        "product": product, "date": date, "tier": tier, "kind": kind,
        "engine_version": version, "source_zip": "z.zip", "source_member": "m",
        "source_bytes": 1, "n_records": 10, "n_symbols": 1, "n_rows": 5,
        "bytes_written": 100, "wall_s": 0.1, "locked_states": 0,
        "crossed_states": 0, "trades_outside_book": 0, "status": status, "error": "",
    }


# --------------------------------------------------------------------------- #
# reading and writing
# --------------------------------------------------------------------------- #

def test_read_on_an_empty_store_is_an_empty_frame_not_an_error(tmp_path):
    df = mf.read(str(tmp_path))
    assert df.empty
    assert "engine_version" in df.columns


def test_append_then_read(tmp_path):
    mf.append(str(tmp_path), _row())
    df = mf.read(str(tmp_path))
    assert len(df) == 1
    assert df.iloc[0]["product"] == "ZN"
    assert df.iloc[0]["date"] == D1
    assert df.iloc[0]["ts_built"] > 0


def test_append_is_lock_free_across_many_writes(tmp_path):
    """A process pool appends these concurrently; one fragment per append means
    no coordination is needed."""
    for i in range(25):
        mf.append(str(tmp_path), _row(date=D1 + datetime.timedelta(days=i)))
    assert len(mf.read(str(tmp_path))) == 25


def test_rows_come_back_oldest_first(tmp_path):
    mf.append(str(tmp_path), _row(status="FAILED"))
    mf.append(str(tmp_path), _row(status="OK"))
    df = mf.read(str(tmp_path))
    assert list(df["status"]) == ["FAILED", "OK"]


# --------------------------------------------------------------------------- #
# completeness
# --------------------------------------------------------------------------- #

def test_is_complete_only_for_ok_status(tmp_path):
    mf.append(str(tmp_path), _row(status="FAILED"))
    assert not mf.is_complete(str(tmp_path), "ZN", D1, "tob", "v1")


def test_is_complete_requires_a_matching_engine_version(tmp_path):
    mf.append(str(tmp_path), _row(version="v1"))
    assert mf.is_complete(str(tmp_path), "ZN", D1, "tob", "v1")
    assert not mf.is_complete(str(tmp_path), "ZN", D1, "tob", "v2")


def test_a_later_row_supersedes_an_earlier_one(tmp_path):
    mf.append(str(tmp_path), _row(status="FAILED"))
    mf.append(str(tmp_path), _row(status="OK"))
    assert mf.is_complete(str(tmp_path), "ZN", D1, "tob", "v1")


def test_a_later_failure_supersedes_an_earlier_success(tmp_path):
    """Re-running a session that then failed must not read as still built."""
    mf.append(str(tmp_path), _row(status="OK"))
    mf.append(str(tmp_path), _row(status="FAILED"))
    assert not mf.is_complete(str(tmp_path), "ZN", D1, "tob", "v1")


def test_is_complete_is_unknown_for_a_session_never_attempted(tmp_path):
    mf.append(str(tmp_path), _row(date=D1))
    assert not mf.is_complete(str(tmp_path), "ZN", D2, "tob", "v1")


def test_tiers_are_tracked_separately(tmp_path):
    mf.append(str(tmp_path), _row(tier="wide"))
    assert mf.is_complete(str(tmp_path), "ZN", D1, "tob", "v1", tier="wide")
    assert not mf.is_complete(str(tmp_path), "ZN", D1, "tob", "v1", tier="deep")


# --------------------------------------------------------------------------- #
# resume
# --------------------------------------------------------------------------- #

def _sessions():
    return pd.DataFrame({"product": ["ZN", "ZN"], "date": [D1, D2]})


def test_pending_lists_only_unbuilt_sessions(tmp_path):
    mf.append(str(tmp_path), _row(date=D1))
    p = mf.pending(str(tmp_path), _sessions(), kinds=("tob",), engine_version="v1")
    assert list(p["date"]) == [D2]


def test_pending_is_everything_when_nothing_is_built(tmp_path):
    p = mf.pending(str(tmp_path), _sessions(), kinds=("tob",), engine_version="v1")
    assert len(p) == 2


def test_an_engine_bump_makes_everything_pending_again(tmp_path):
    """The vintage trap, made structural: a code change re-builds visibly."""
    for d in (D1, D2):
        mf.append(str(tmp_path), _row(date=d, version="v1"))
    assert mf.pending(str(tmp_path), _sessions(), ("tob",), "v1").empty
    assert len(mf.pending(str(tmp_path), _sessions(), ("tob",), "v2")) == 2


def test_a_session_is_pending_unless_every_requested_kind_is_built(tmp_path):
    mf.append(str(tmp_path), _row(date=D1, kind="tob"))
    p = mf.pending(str(tmp_path), _sessions(), kinds=("tob", "trades"),
                   engine_version="v1")
    assert list(p["date"]) == [D1, D2]

    mf.append(str(tmp_path), _row(date=D1, kind="trades"))
    p = mf.pending(str(tmp_path), _sessions(), kinds=("tob", "trades"),
                   engine_version="v1")
    assert list(p["date"]) == [D2]


def test_pending_on_an_empty_session_list_is_empty(tmp_path):
    empty = pd.DataFrame({"product": [], "date": []})
    assert mf.pending(str(tmp_path), empty, ("tob",), "v1").empty


def test_engine_version_is_a_real_constant():
    assert isinstance(mf.ENGINE_VERSION, str)
    assert mf.ENGINE_VERSION.count(".") == 2
