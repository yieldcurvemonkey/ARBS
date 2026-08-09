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
    """The exact case the guard is for: a zero-residual regression.

    ``se`` is a Python float, so ``lam / se`` raises ZeroDivisionError there --
    np.errstate governs numpy's arithmetic and does nothing for it. The fixture
    needs FOUR quote bars so three differences survive the n >= 3 floor, and the
    mid must move exactly proportionally to signed volume so the residual is
    genuinely zero.
    """
    tob = _tob([(0, 96.000, 10, 96.000, 10),
                (60 * S, 96.005, 10, 96.005, 10),
                (120 * S, 96.015, 10, 96.015, 10),
                (180 * S, 96.030, 10, 96.030, 10)])
    tape = _tape([(60 * S + 1, 96.005, 5, 1),
                  (120 * S + 1, 96.015, 10, 1),
                  (180 * S + 1, 96.030, 15, 1)])
    # The contract is that it RETURNS. A perfect fit may give an infinite
    # t-statistic; what it may not do is raise and end a 553-session sweep.
    out = kyle_lambda(tob, tape, freq="60s")
    assert set(out) >= {"lam", "t_stat", "r2", "n_bars", "alpha"}
    assert out["n_bars"] >= 3
    assert np.isfinite(out["lam"])


def test_kyle_lambda_on_a_pinned_mid_returns_rather_than_raising():
    """The degenerate day the guard exists for, and the only one that reaches it.

    A near-perfect fit does NOT: floating-point lstsq leaves a residual around
    1e-31, so the standard error is tiny but non-zero and the division is safe.
    The standard error is exactly zero only when the residual vector is exactly
    zero -- which is a mid that never moves at all, while volume varies. That is
    the listed butterfly pinned to one tick for a session, the most common quiet
    instrument-day in this catalogue, and without the guard it is 0.0 / 0.0.
    """
    tob = _tob([(k * 60 * S, 96.000, 10, 96.005, 10) for k in range(5)])
    tape = _tape([(k * 60 * S + 1, 96.005, 5 * (k + 1), 1) for k in range(5)])
    out = kyle_lambda(tob, tape, freq="60s")
    assert out["n_bars"] >= 3
    assert out["lam"] == 0.0
    assert np.isnan(out["t_stat"])


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


# --------------------------------------------------------------------------- #
# flow: contracts the original suite documented but did not pin
# --------------------------------------------------------------------------- #

def test_d_mid_is_the_bar_to_bar_change_not_the_within_bar_one():
    """A surviving mutation: swapping mid_last for mid_first in ofi_bars left all
    45 tests green, because every fixture that asserted d_mid had exactly ONE
    event per bar, where the two columns are identical by construction. On real
    SR3 data bars are never single-event, so the mutant would have tripled d_mid
    everywhere while the suite stayed green.
    """
    from RVUtils.MBO.analytics.flow import ofi_bars

    # Bar 0 holds three events with the mid walking inside it; bar 1 holds one.
    rows = [
        (0, 96.000, 10, 96.010, 10),
        (3 * S, 96.005, 10, 96.015, 10),
        (7 * S, 96.010, 10, 96.020, 10),
        (12 * S, 96.015, 10, 96.025, 10),
    ]
    bars = ofi_bars(_tob(rows), freq="10s")
    assert len(bars) == 2
    # bar 0 ends at mid 96.015, bar 1 ends at 96.020: the change is one tick.
    assert bars["d_mid"].iloc[1] == pytest.approx(0.005)
    # mid_first would give 96.020 - 96.005 = 0.015, three times as much.
    assert bars["mid_first"].iloc[0] != bars["mid_last"].iloc[0]


def test_events_sharing_one_nanosecond_are_ordered_by_sequence():
    """A surviving mutation: dropping ``sequence`` from the sort key left all 45
    tests green, because no fixture had two rows stamped at the same nanosecond.
    Every record in a CME packet shares one ts_recv, so that is the normal case,
    and OFI is a first difference -- within-packet order sets the sign.
    """
    from RVUtils.MBO.analytics.flow import ofi_events

    # One packet: the bid queue builds 10 -> 20, then is cut to 4, all at one
    # timestamp. Handed over with the sequence out of order.
    t = _tob([(0, 96.00, 10, 96.01, 5),
              (0, 96.00, 20, 96.01, 5),
              (0, 96.00, 4, 96.01, 5)])
    t["sequence"] = np.array([0, 1, 2], dtype=np.uint32)
    shuffled = t.iloc[[2, 0, 1]].reset_index(drop=True)

    got = ofi_events(shuffled).to_numpy()
    # Correct order gives +10 (queue built) then -16 (queue cut).
    assert got[1] == pytest.approx(10.0)
    assert got[2] == pytest.approx(-16.0)


def test_a_bucket_median_is_not_a_mean():
    """A surviving mutation: median -> mean left all 43 impact tests green,
    because every populated bucket held one or two symmetric rows. The module's
    headline claim is that one large print must not move a bucket."""
    from RVUtils.MBO.analytics.impact import impact_by_size

    tape = _tape([(1, 96.005, 1, 1), (2, 96.005, 1, 1), (3, 96.005, 1, 1)])
    tape["prev_mid"] = [96.0, 96.0, 95.995]        # eff 0.01, 0.01, 0.02
    out = impact_by_size(tape, None, bins=(1, 2))
    first = out[out["n"] > 0].iloc[0]
    assert first["eff_median"] == pytest.approx(0.01)   # mean would be 0.0133
