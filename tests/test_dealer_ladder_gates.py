"""Pure tests for the gate orchestrator's helpers (no DB, no vendor).

The gates themselves need real data; what is testable in isolation is the
bookkeeping that decides which contracts, which dates, and which row of a league
table gets reported — all places where a silent error would misstate a result.
"""
import datetime

import numpy as np
import pandas as pd
import pytest

from BT.dealer_ladder import gates

NY = "America/New_York"


# ---------------------------------------------------------- contract calendar
def test_contract_calendar_takes_the_front_six_of_each_space():
    cal = gates.contract_calendar(datetime.date(2026, 7, 10), count=6)
    buckets = [b for b, *_ in cal]
    assert buckets[:6] == ["SFRU26", "SFRZ26", "SFRH27", "SFRM27", "SFRU27", "SFRZ27"]
    assert buckets[6:] == ["FFN26", "FFQ26", "FFU26", "FFV26", "FFX26", "FFZ26"]
    assert len(cal) == 12


def test_contract_calendar_carries_the_right_spec_flag_per_space():
    """is_ser picks monthly-averaged (ZQ) vs quarterly-compounded (SR3)."""
    cal = dict((b, is_ser) for b, _e, _m, is_ser in
               gates.contract_calendar(datetime.date(2026, 7, 10), count=2))
    assert cal["SFRU26"] is False
    assert cal["FFN26"] is True


def test_contract_calendar_single_space():
    cal = gates.contract_calendar(datetime.date(2026, 7, 10), spaces=("FUTURES",),
                                  count=3)
    assert [b for b, *_ in cal] == ["SFRU26", "SFRZ26", "SFRH27"]


@pytest.mark.parametrize("bucket,space", [
    ("SFRU26", "FUTURES"), ("SFRZ28", "FUTURES"),
    ("FFN26", "FED_FUNDS"), ("FFF27", "FED_FUNDS"),
])
def test_space_of(bucket, space):
    assert gates._space_of(bucket) == space


# ------------------------------------------------------------------ date mask
def test_date_mask_is_inclusive_on_both_ends_in_et():
    idx = pd.date_range("2026-06-08", "2026-06-12", freq="1D", tz=NY)
    m = gates._date_mask(idx, datetime.date(2026, 6, 9), datetime.date(2026, 6, 11))
    assert list(m) == [False, True, True, True, False]


def test_date_mask_uses_et_session_dates_not_utc():
    """21:00 ET on 06-09 is 01:00 UTC on 06-10; the ET session date must win."""
    idx = pd.DatetimeIndex([pd.Timestamp("2026-06-09 21:00", tz=NY)])
    m = gates._date_mask(idx, datetime.date(2026, 6, 9), datetime.date(2026, 6, 9))
    assert list(m) == [True]


# --------------------------------------------------------- league table rows
def _league():
    return pd.DataFrame([
        {"variant": "a", "mean": 0.9, "t": 4.0, "n": 100},
        {"variant": "b", "mean": 0.4, "t": 2.0, "n": 100},
        {"variant": "c", "mean": 0.1, "t": 0.5, "n": 100},
        {"variant": "d", "mean": -0.2, "t": -1.0, "n": 100},
    ])


def test_best_and_median_reports_both_rows():
    """A league table showing only the winner is a maximum reported as a draw."""
    out = gates._best_and_median(_league())
    assert list(out["role"]) == ["best-config", "median-config"]
    assert out.iloc[0]["variant"] == "a"
    assert out.iloc[0]["t"] == 4.0
    # median t over {4, 2, 0.5, -1} is 1.25; nearest row is b (t=2)
    assert out.iloc[1]["variant"] == "b"


def test_best_and_median_ignores_nan_t():
    league = _league()
    league.loc[len(league)] = {"variant": "e", "mean": 99.0, "t": np.nan, "n": 5}
    out = gates._best_and_median(league)
    assert out.iloc[0]["variant"] == "a"          # the NaN row cannot win


def test_best_and_median_empty():
    assert gates._best_and_median(pd.DataFrame(columns=["variant", "t"])).empty


# ------------------------------------------------------- Romano-Wolf assembly
class _Cfg:
    """Minimal stand-in for a GateContext: only ``.config.stats`` is read."""

    class config:
        class stats:
            n_boot = 50
            seed = 0


def _ledger(days, net):
    ts = [pd.Timestamp(f"2026-06-{d:02d} 10:00", tz=NY) for d in days]
    return pd.DataFrame({"ts": ts, "net_bp": net})


def test_romano_wolf_over_variants_aggregates_to_one_row_per_session():
    per = {
        "v1": _ledger([1, 1, 2, 3], [1.0, 3.0, 2.0, 2.0]),
        "v2": _ledger([1, 2, 3], [0.0, 0.0, 0.0]),
    }
    out = gates._romano_wolf_over_variants(per, _Cfg())
    assert out is not None
    assert set(out.index) == {"v1", "v2"}
    # v1's session 1 mean is (1+3)/2 = 2, so its overall mean is 2.0
    assert out.loc["v1", "mean"] == pytest.approx(2.0)
    assert out.loc["v1", "n_blocks"] == 3


def test_romano_wolf_over_variants_needs_two_variants():
    assert gates._romano_wolf_over_variants({"only": _ledger([1, 2], [1.0, 1.0])},
                                            _Cfg()) is None
    assert gates._romano_wolf_over_variants({}, _Cfg()) is None


def test_romano_wolf_over_variants_fills_missing_sessions_with_zero():
    """A variant that did not trade on a session earns 0 there, not a dropped row."""
    per = {"v1": _ledger([1, 2, 3], [1.0, 1.0, 1.0]),
           "v2": _ledger([1], [5.0])}
    out = gates._romano_wolf_over_variants(per, _Cfg())
    assert out.loc["v2", "n_blocks"] == 3
    assert out.loc["v2", "mean"] == pytest.approx(5.0 / 3.0)


# ------------------------------------------------------------------ verdicts
def test_verdict_shape_and_tri_state_pass():
    v = gates._verdict("G2", None, "no data")
    assert v["gate"] == "G2" and v["pass"] is None
    assert gates._verdict("G2", True, "x")["pass"] is True
    assert gates._verdict("G2", False, "x")["pass"] is False


def test_verdict_carries_extra_detail():
    v = gates._verdict("G3", False, "collapsed", controls_used=["basis_bp"])
    assert v["controls_used"] == ["basis_bp"]
