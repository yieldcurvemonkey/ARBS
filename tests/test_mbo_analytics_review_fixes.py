"""Regressions for defects the adversarial review found in the Phase-2 analytics.

Each test here exists because a mutation survived the original suite, or because
a documented contract was contradicted by the code. They are kept together rather
than folded into the per-module files so the provenance stays visible.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from RVUtils.MBO.analytics.impact import impact_by_size, kyle_lambda
from RVUtils.MBO.analytics.liquidity import quoted_spread

S = 1_000_000_000
T0 = pd.Timestamp(1_784_073_600 * S, unit="ns", tz="UTC")


def _at(ns):
    return T0 + pd.Timedelta(ns, unit="ns")


def _tob(rows):
    """rows: (ns, bid_px, bid_sz, ask_px, ask_sz)"""
    return pd.DataFrame({
        "symbol": ["ZNU6"] * len(rows),
        "ts_recv": [_at(r[0]) for r in rows],
        "ts_event": [_at(r[0]) for r in rows],
        "sequence": np.arange(len(rows), dtype=np.uint32),
        "date": [T0.date()] * len(rows),
        "bid_px": [r[1] for r in rows],
        "bid_sz": [r[2] for r in rows],
        "bid_ct": [1] * len(rows),
        "ask_px": [r[3] for r in rows],
        "ask_sz": [r[4] for r in rows],
        "ask_ct": [1] * len(rows),
        "mid": [(r[1] + r[3]) / 2 for r in rows],
        "spread": [r[3] - r[1] for r in rows],
    })


def _tape(rows):
    """rows: (ns, price, size, aggressor)"""
    return pd.DataFrame({
        "symbol": ["ZNU6"] * len(rows),
        "ts_recv": [_at(r[0]) for r in rows],
        "ts_event": [_at(r[0]) for r in rows],
        "sequence": np.arange(len(rows), dtype=np.uint32),
        "order_id": np.arange(len(rows), dtype=np.uint64),
        "date": [T0.date()] * len(rows),
        "price": [r[1] for r in rows],
        "size": [r[2] for r in rows],
        "aggressor": np.array([r[3] for r in rows], dtype=np.int8),
        "prev_bid_px": [r[1] - 0.005 for r in rows],
        "prev_ask_px": [r[1] + 0.005 for r in rows],
        "prev_bid_sz": [10] * len(rows),
        "prev_ask_sz": [10] * len(rows),
        "prev_mid": [r[1] for r in rows],
    })


# --------------------------------------------------------------------------- #
# liquidity: a locked or crossed book is not a quoted market
# --------------------------------------------------------------------------- #

def test_a_locked_book_is_excluded_from_the_quoted_spread():
    """Locked states reach the store -- the replay counts them and the catalogue
    persists them -- and they stand for the whole settlement break, so time
    weighting makes them dominate rather than dilute. Averaging over them
    reports a width the lattice cannot quote."""
    rows = [
        (0, 96.00, 10, 96.00, 10),          # locked, stands 3600 s
        (3600 * S, 96.00, 10, 96.005, 10),  # a real one-tick market, 600 s
        (4200 * S, 96.00, 10, 96.005, 10),
    ]
    out = quoted_spread(_tob(rows), tick=0.005)
    assert out["spread_mean"] == pytest.approx(0.005)
    assert out["spread_ticks"] == pytest.approx(1.0)
    assert out["locked_frac"] > 0.8
    assert out["two_sided_frac"] < 0.2


def test_a_crossed_book_never_produces_a_negative_spread():
    rows = [
        (0, 96.010, 10, 96.000, 10),        # crossed
        (600 * S, 96.000, 10, 96.005, 10),  # genuine
        (1200 * S, 96.000, 10, 96.005, 10),
    ]
    out = quoted_spread(_tob(rows), tick=0.005)
    assert out["spread_mean"] > 0
    assert out["spread_ticks"] == pytest.approx(1.0)
    assert out["crossed_frac"] > 0.4


def test_locked_and_crossed_time_is_reported_not_discarded():
    rows = [(0, 96.00, 10, 96.00, 10), (100 * S, 96.00, 10, 96.005, 10),
            (200 * S, 96.00, 10, 96.005, 10)]
    out = quoted_spread(_tob(rows))
    assert out["locked_frac"] + out["crossed_frac"] + out["two_sided_frac"] == \
        pytest.approx(1.0)


def test_a_book_that_is_only_ever_locked_reports_no_spread():
    rows = [(0, 96.00, 10, 96.00, 10), (100 * S, 96.00, 12, 96.00, 12)]
    out = quoted_spread(_tob(rows))
    assert np.isnan(out["spread_mean"])
    assert out["two_sided_frac"] == 0.0
    assert out["locked_frac"] == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
# impact: a degenerate fit must not stop a sweep
# --------------------------------------------------------------------------- #

def test_kyle_lambda_on_a_perfect_fit_returns_instead_of_raising():
    """The exact case: an instrument whose mid moves in lockstep with volume over
    two bars gives a zero-residual fit. ``se`` is a Python float, so the division
    raises ZeroDivisionError -- which np.errstate does not govern -- and would
    kill a sweep over hundreds of instrument-days."""
    tob = _tob([(0, 96.000, 10, 96.005, 10),
                (60 * S, 96.005, 10, 96.010, 10),
                (120 * S, 96.010, 10, 96.015, 10)])
    tape = _tape([(1, 96.005, 5, 1), (60 * S + 1, 96.010, 5, 1),
                  (120 * S + 1, 96.015, 5, 1)])
    # The contract is that it RETURNS. A perfect fit may legitimately give NaN or
    # an infinite t-statistic; what it may not do is raise and end the sweep.
    out = kyle_lambda(tob, tape, freq="60s")
    assert set(out) >= {"lam", "t_stat", "r2", "n_bars", "alpha"}
    assert not np.isnan(out["n_bars"])


def test_kyle_lambda_on_a_pinned_mid_returns_nan_rather_than_raising():
    """A listed butterfly that trades all session without leaving one tick."""
    tob = _tob([(k * 60 * S, 96.000, 10, 96.005, 10) for k in range(4)])
    tape = _tape([(k * 60 * S + 1, 96.005, 5, 1) for k in range(4)])
    out = kyle_lambda(tob, tape, freq="60s")
    assert out["lam"] == 0.0 or np.isnan(out["lam"])
    assert not np.isnan(out["n_bars"])


# --------------------------------------------------------------------------- #
# impact: a NaN size must not become a negative volume
# --------------------------------------------------------------------------- #

def test_a_non_finite_trade_size_raises_rather_than_becoming_int64_min():
    """NaN fails every comparison, so it slipped past the bin-edge guard, landed
    in the final bucket and became -9.2e18 on the int64 cast."""
    tape = _tape([(1, 96.005, 1, 1), (2, 96.005, 2, 1)])
    tape["size"] = tape["size"].astype(float)
    tape.loc[1, "size"] = np.nan
    with pytest.raises(ValueError, match="non-finite size"):
        impact_by_size(tape, None, bins=(1, 2, 5))


def test_a_clean_tape_still_buckets_normally():
    tape = _tape([(1, 96.005, 1, 1), (2, 96.005, 7, 1)])
    out = impact_by_size(tape, None, bins=(1, 2, 5))
    assert int(out["volume"].sum()) == 8
    assert (out["volume"] >= 0).all()
