"""Multi-level order-flow imbalance: the definition, and the reason for Ridge.

The load-bearing test is that at one level MLOFI reduces exactly to
Cont-Kukanov-Stoikov. If it does not, one of the two implementations is wrong and
every deeper level inherits the error.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from RVUtils.MBO.analytics.flow import ofi_events
from RVUtils.MBO.analytics.mlofi import mlofi_bars, mlofi_regression, ofi_bar_scan
from RVUtils.MBO.book import build_price_grid, replay_book
from RVUtils.MBO.mlofi import replay_mlofi
from tests.test_mbo_book import L, make

S = 1_000_000_000


def _run(rows, levels=3):
    rec = make(rows)
    g = build_price_grid(rec["price"].astype(np.int64))
    return replay_mlofi(rec, grid=g, levels=levels)


# --------------------------------------------------------------------------- #
# the definition
# --------------------------------------------------------------------------- #

def test_one_level_mlofi_is_exactly_cks_order_flow_imbalance():
    """The check that anchors everything deeper. Xu-Gould-Howison state that at
    M = 1 their measure is identical to Cont-Kukanov-Stoikov, so two independent
    implementations in this repo must agree event for event."""
    rows = [
        (1, "A", "B", 96.000, 10, 1, 0),
        (1, "A", "A", 96.010, 7, 2, L),
        (2 * S, "A", "B", 96.000, 5, 3, L),        # bid queue builds
        (3 * S, "A", "B", 96.005, 4, 4, L),        # bid improves
        (4 * S, "C", "B", 96.005, 4, 4, L),        # and is pulled
        (5 * S, "A", "A", 96.005, 3, 5, L),        # ask improves
    ]
    r = _run(rows, levels=1)
    rec = make(rows)
    g = build_price_grid(rec["price"].astype(np.int64))
    tob = replay_book(rec, grid=g).tob
    cks = ofi_events(tob.assign(symbol="X", date=pd.Timestamp("2026-07-15").date(),
                                sequence=np.arange(len(tob), dtype=np.uint32)))
    # MLOFI's first row is the first COMPARABLE pair, so line the two up on the
    # events they share.
    a = r.frame["e_1"].to_numpy(dtype=float)
    b = cks.to_numpy(dtype=float)[1:]
    n = min(len(a), len(b))
    np.testing.assert_allclose(a[:n], b[:n])


def test_a_build_at_a_standing_bid_is_the_size_difference():
    r = _run([
        (1, "A", "B", 96.000, 10, 1, 0),
        (1, "A", "A", 96.010, 7, 2, L),
        (2 * S, "A", "B", 96.000, 6, 3, L),
    ], levels=1)
    assert r.frame["e_1"].iloc[-1] == 6


def test_a_price_improvement_contributes_the_whole_new_size():
    r = _run([
        (1, "A", "B", 96.000, 10, 1, 0),
        (1, "A", "A", 96.010, 7, 2, L),
        (2 * S, "A", "B", 96.005, 4, 3, L),
    ], levels=1)
    assert r.frame["e_1"].iloc[-1] == 4


def test_an_ask_improvement_contributes_negatively():
    """A better offer is downward pressure, so the sign must invert."""
    r = _run([
        (1, "A", "B", 96.000, 10, 1, 0),
        (1, "A", "A", 96.010, 7, 2, L),
        (2 * S, "A", "A", 96.005, 3, 3, L),
    ], levels=1)
    assert r.frame["e_1"].iloc[-1] == -3


def test_levels_are_populated_prices_not_ticks():
    """Level 2 is the next price where something rests, not the next tick.
    Counting empty ticks would make the measure respond to the grid."""
    r = _run([
        (1, "A", "B", 96.000, 10, 1, 0),
        (1, "A", "B", 95.900, 20, 2, 0),          # far below, still level 2
        (1, "A", "A", 96.010, 7, 3, L),
        (2 * S, "A", "B", 95.900, 5, 4, L),       # builds level 2
    ], levels=2)
    assert r.frame["e_1"].iloc[-1] == 0           # touch untouched
    assert r.frame["e_2"].iloc[-1] == 5


def test_one_event_can_move_several_components():
    """The paper's own caution: a new best bid shifts every deeper level down a
    rank, so several components change from one arrival."""
    r = _run([
        (1, "A", "B", 96.000, 10, 1, 0),
        (1, "A", "B", 95.995, 20, 2, 0),
        (1, "A", "A", 96.010, 7, 3, L),
        (2 * S, "A", "B", 96.005, 4, 4, L),       # new best bid
    ], levels=3)
    last = r.frame.iloc[-1]
    assert last["e_1"] != 0
    assert last["e_2"] != 0                        # the ladder shifted


def test_replaying_two_instruments_raises():
    a = make([(1, "A", "B", 96.0, 1, 1, L)], instrument_id=1)
    b = make([(1, "A", "B", 96.0, 1, 2, L)], instrument_id=2)
    with pytest.raises(ValueError, match="exactly one instrument_id"):
        replay_mlofi(np.concatenate([a, b]))


# --------------------------------------------------------------------------- #
# bars and the regression
# --------------------------------------------------------------------------- #

def _walk_rows(n=400, step=S):
    rows = [(0, "A", "B", 96.000, 10, 1, 0), (0, "A", "A", 96.010, 10, 2, L)]
    for i in range(1, n):
        t = i * step
        rows.append((t, "M", "B", 96.000 + i * 0.005, 10 + (i % 5), 1, 0))
        rows.append((t, "M", "A", 96.010 + i * 0.005, 10 + (i % 3), 2, L))
    return rows


def test_bars_sum_the_level_vector_and_difference_the_mid():
    r = _run(_walk_rows(60), levels=2)
    b = mlofi_bars(r.frame, freq="10s")
    assert {"e_1", "e_2", "d_mid", "n_events"} <= set(b.columns)
    assert b["n_events"].sum() == len(r.frame)


def test_an_empty_frame_gives_a_typed_empty_bar_frame():
    out = mlofi_bars(pd.DataFrame(), freq="10s")
    assert out.empty


def test_the_regression_reports_both_fits_so_collinearity_is_visible():
    r = _run(_walk_rows(400), levels=3)
    b = mlofi_bars(r.frame, freq="5s")
    got = mlofi_regression(b)
    assert got["n_bars"] > 30
    assert set(got) >= {"lambda", "rmse_ridge", "rmse_ols", "rmse_1", "improvement"}
    assert len(got["beta_ridge"]) == 3


def test_too_few_bars_returns_nan_rather_than_a_confident_number():
    r = _run(_walk_rows(20), levels=2)
    got = mlofi_regression(mlofi_bars(r.frame, freq="60s"))
    assert np.isnan(got["rmse_ridge"])
    assert got["n_bars"] < 30


def test_the_fit_is_deterministic():
    """Folds are contiguous blocks in time, not random draws: bars are serially
    dependent and a shuffled fold leaks a bar's neighbours into training, which
    flatters the out-of-sample error. Determinism is the observable consequence --
    a randomised split would not repeat."""
    r = _run(_walk_rows(400), levels=3)
    b = mlofi_bars(r.frame, freq="5s")
    a1 = mlofi_regression(b)
    a2 = mlofi_regression(b)
    assert a1["lambda"] == a2["lambda"]
    assert a1["rmse_ridge"] == a2["rmse_ridge"]
    assert a1["beta_ridge"] == a2["beta_ridge"]


# --------------------------------------------------------------------------- #
# the bar-length diagnostic
# --------------------------------------------------------------------------- #

def test_the_bar_scan_reports_correlation_and_pinned_bars_per_frequency():
    rec = make(_walk_rows(600))
    g = build_price_grid(rec["price"].astype(np.int64))
    tob = replay_book(rec, grid=g).tob
    tob = tob.assign(symbol="X", date=pd.Timestamp("2026-07-15").date())
    out = ofi_bar_scan(tob, freqs=("1s", "10s", "60s"))
    assert list(out["freq"]) == ["1s", "10s", "60s"]
    assert (out["n_bars"].diff().dropna() <= 0).all()
    assert out["zero_frac"].dropna().between(0, 1).all()


def test_a_rank_deficient_design_does_not_raise():
    """The ordinary case, not the pathological one. The paper measures the
    eigenvalue ratio of this design matrix collapsing to zero beyond the first
    component, so a solver that raises on collinear levels would refuse to compute
    the unpenalised baseline the penalty is meant to beat."""
    n = 200
    idx = pd.date_range("2026-07-15", periods=n, freq="5s", tz="UTC")
    e1 = np.arange(n, dtype=float)
    bars = pd.DataFrame({
        "e_1": e1,
        "e_2": e1 * 2.0,            # perfectly collinear with e_1
        "e_3": np.zeros(n),         # and a dead level
        "d_mid": e1 * 0.5 + 1.0,
        "n_events": np.ones(n),
        "mid_last": np.cumsum(np.ones(n)),
    }, index=idx)
    got = mlofi_regression(bars)
    assert np.isfinite(got["rmse_ridge"])
    assert np.isfinite(got["rmse_ols"])
    assert len(got["beta_ridge"]) == 3


def test_the_penalty_actually_penalises():
    """Before standardising the design, cross-validation picked the largest lambda
    on the grid for every fit and Ridge matched OLS to four decimals -- because
    these columns are order flow in lots, so X'X ran to 1e11 and the penalty was a
    rounding error. A large penalty must visibly shrink the coefficients."""
    from RVUtils.MBO.analytics.mlofi import _ridge

    rng = np.random.default_rng(0)
    x = rng.normal(0, 1000.0, size=(500, 3))          # lots, not returns
    y = x @ np.array([0.5, -0.2, 0.1]) + rng.normal(0, 1.0, 500)
    small = _ridge(x, y, 1e-6)[1:]
    large = _ridge(x, y, 1e6)[1:]
    assert np.abs(large).sum() < np.abs(small).sum() * 0.5


def test_a_penalty_on_the_grid_boundary_is_flagged():
    n = 200
    idx = pd.date_range("2026-07-15", periods=n, freq="5s", tz="UTC")
    rng = np.random.default_rng(1)
    bars = pd.DataFrame({
        "e_1": rng.normal(0, 1, n), "e_2": rng.normal(0, 1, n),
        "d_mid": rng.normal(0, 1, n), "n_events": np.ones(n),
        "mid_last": np.arange(float(n)),
    }, index=idx)
    got = mlofi_regression(bars, lambdas=[1e7, 1e8])   # deliberately truncated grid
    assert got["lambda_at_bound"]
