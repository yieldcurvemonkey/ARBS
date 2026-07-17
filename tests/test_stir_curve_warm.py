"""Unit tests for the decoupled curve-warming layer (no network)."""
import pandas as pd
import pytest

from SDRUtils.stir_flow.curve_warm import (
    enumerate_curve_demand, unit_curve_and_snap, warm_pricer,
)


class _U:
    def __init__(self, legs):
        self.legs = legs


def _leg(idx="FED_FUNDS", ts="2026-07-02T13:05:23+00:00", orig=None):
    return pd.DataFrame([{
        "rate_index_clean": idx,
        "execution_timestamp": pd.Timestamp(ts),
        "original_execution_timestamp": pd.Timestamp(orig) if orig else None,
    }])


def test_unit_curve_and_snap_ff():
    cn, snap = unit_curve_and_snap(_U(_leg("FED_FUNDS")))
    assert cn == "USD-OIS-Q12xM12STIRT-SERFFX-MIX23"
    # 13:05:23 UTC -> 09:05 EDT -> secs zeroed, minus 1 minute -> 09:04:00 NY
    assert (snap.minute, snap.second) == (4, 0)
    assert snap.hour == 9 and snap.tzinfo is not None


def test_unit_curve_and_snap_sofr():
    cn, _ = unit_curve_and_snap(_U(_leg("SOFR")))
    assert cn == "USD-SOFR-1D-Q12xM12STIRT"


def test_enumerate_dedupes_same_minute():
    u1 = _U(_leg("SOFR", "2026-07-02T13:05:23+00:00"))
    u2 = _U(_leg("SOFR", "2026-07-02T13:05:47+00:00"))  # same snapped minute
    assert len(enumerate_curve_demand([u1, u2])) == 1


def test_enumerate_separates_index_and_minute():
    us = [
        _U(_leg("SOFR", "2026-07-02T13:05:23+00:00")),
        _U(_leg("FED_FUNDS", "2026-07-02T13:05:23+00:00")),  # diff curve
        _U(_leg("SOFR", "2026-07-02T13:07:23+00:00")),       # diff minute
    ]
    assert len(enumerate_curve_demand(us)) == 3


class _FakeMDP:
    def __init__(self):
        self.calls = []

    def _get_curve(self, curve_name, timestamp):
        self.calls.append((curve_name, timestamp))
        return f"H:{curve_name}:{timestamp}"


class _FakePricer:
    def __init__(self):
        self._mdp = _FakeMDP()
        self._handles = {}


def test_warm_builds_all_and_is_idempotent():
    p = _FakePricer()
    demand = {("C", pd.Timestamp("2026-07-02T13:04:00Z")),
              ("C", pd.Timestamp("2026-07-02T13:05:00Z"))}
    r = warm_pricer(p, demand, max_workers=2)
    assert r["built"] == 2 and r["failed"] == 0 and len(p._handles) == 2
    r2 = warm_pricer(p, demand, max_workers=2)
    assert r2["built"] == 0 and r2["reused"] == 2


def test_warm_isolates_failures():
    p = _FakePricer()

    def boom(curve_name, timestamp):
        if "bad" in curve_name:
            raise RuntimeError("x")
        return "H"

    p._mdp._get_curve = boom
    ok_key = ("ok", pd.Timestamp("2026-07-02T13:04:00Z"))
    r = warm_pricer(p, {ok_key, ("bad", pd.Timestamp("2026-07-02T13:04:00Z"))},
                    max_workers=2)
    assert r["built"] == 1 and r["failed"] == 1 and ok_key in p._handles


def test_warm_reraises_when_configured():
    p = _FakePricer()

    def boom(curve_name, timestamp):
        raise RuntimeError("x")

    p._mdp._get_curve = boom
    with pytest.raises(RuntimeError):
        warm_pricer(p, {("bad", pd.Timestamp("2026-07-02T13:04:00Z"))},
                    max_workers=1, on_error="raise")
