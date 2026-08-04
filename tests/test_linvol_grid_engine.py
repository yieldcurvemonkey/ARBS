"""Synthetic tests for the linvol grid package engine (no data files)."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent
                       / "notebooks" / "backtests"))

from linvol_grid_common import (          # noqa: E402
    OPT_HALF_TICK_BP,
    PackageTrade,
    _classify_boundaries,
    claim_series,
    fly_series,
    league_row,
    run_package_backtest,
)


def _q_idx(rows):
    df = pd.DataFrame(rows, columns=["symbol", "right", "strike_price",
                                     "as_of", "premium_bp"])
    df["as_of"] = pd.to_datetime(df["as_of"])
    return df.set_index(["symbol", "right", "strike_price", "as_of"])[
        "premium_bp"].sort_index()


DATES = pd.to_datetime(["2026-01-05", "2026-01-06", "2026-01-07",
                        "2026-01-08", "2026-01-09"])


class TestClaimMarks:
    def test_put_vertical_is_the_spread_premium(self):
        qi = _q_idx([("S", "P", 96.0, DATES[0], 4.0),
                     ("S", "P", 96.0625, DATES[0], 6.5)])
        s = claim_series(qi, "S", "P", 96.0, 96.0625)
        assert s.iloc[0] == pytest.approx(2.5)

    def test_call_claim_drops_a_constant_not_the_moves(self):
        rows = []
        for d, (lo, hi) in zip(DATES[:2], [(6.0, 2.0), (7.0, 2.5)]):
            rows += [("S", "C", 96.0, d, lo), ("S", "C", 96.0625, d, hi)]
        s = claim_series(_q_idx(rows), "S", "C", 96.0, 96.0625)
        # claim = width - spread; day-over-day change = -(spread change)
        assert s.iloc[1] - s.iloc[0] == pytest.approx(-(4.5 - 4.0))

    def test_fly_is_one_minus_two_plus_one(self):
        rows = [("S", "C", k, DATES[0], p) for k, p in
                [(95.75, 30.0), (96.0, 12.0), (96.25, 4.0)]]
        out = fly_series(_q_idx(rows), "S", "C", 96.0)
        assert out is not None
        s, n = out
        assert n == 4
        assert s.iloc[0] == pytest.approx(30.0 - 24.0 + 4.0)

    def test_missing_strike_returns_none(self):
        qi = _q_idx([("S", "C", 96.0, DATES[0], 12.0)])
        assert fly_series(qi, "S", "C", 96.0) is None
        assert claim_series(qi, "S", "C", 96.0, 96.5) is None


class TestPackageBacktest:
    def _mark_fn(self, marks):
        def fn(row):
            return marks, 4
        return fn

    def test_lag_one_entry_and_time_stop(self):
        marks = pd.Series([10.0, 8.0, 6.0, 5.0, 4.0], index=DATES)
        entries = pd.DataFrame({"as_of": [DATES[0]], "symbol": ["S"]})
        trades = run_package_backtest(
            entries, self._mark_fn(marks), DATES,
            direction="long", lag=1, hold_sessions=2)
        assert len(trades) == 1
        t = trades[0]
        assert t.entry == DATES[1]           # lag-1: signal day never trades
        assert t.exit == DATES[3]            # 2 sessions after entry
        assert t.gross_bp == pytest.approx(5.0 - 8.0)
        assert t.net_bp(1.0) == pytest.approx(-3.0 - 4 * OPT_HALF_TICK_BP * 2)

    def test_short_direction_flips_sign(self):
        marks = pd.Series([10.0, 8.0, 6.0, 5.0, 4.0], index=DATES)
        entries = pd.DataFrame({"as_of": [DATES[0]], "symbol": ["S"]})
        t = run_package_backtest(entries, self._mark_fn(marks), DATES,
                                 direction="short", lag=1, hold_sessions=2)[0]
        assert t.gross_bp == pytest.approx(3.0)

    def test_one_open_package_per_symbol(self):
        marks = pd.Series(np.linspace(10, 5, 5), index=DATES)
        entries = pd.DataFrame({"as_of": DATES[:3], "symbol": ["S"] * 3})
        trades = run_package_backtest(entries, self._mark_fn(marks), DATES,
                                      direction="long", lag=1,
                                      hold_sessions=10)
        assert len(trades) == 1              # later signals blocked while open

    def test_league_row_cost_multipliers(self):
        t = PackageTrade(symbol="S", entry=DATES[1], exit=DATES[2],
                         direction="long", entry_bp=8.0, exit_bp=11.0,
                         n_contracts=4, exit_reason="x", meta={})
        row = league_row([t], {"family": "B"})
        assert row["total_gross_bp"] == pytest.approx(3.0)
        assert row["net_1x_bp"] == pytest.approx(3.0 - 1.0)
        assert row["net_2x_bp"] == pytest.approx(3.0 - 2.0)


class TestBoundaryClassifier:
    def test_outer_flank_largest(self):
        g = pd.DataFrame({
            "boundary_rate": [3.6, 3.85, 4.1, 4.35],
            "p_tree": [0.98, 0.60, 0.15, 0.02],   # mode bucket = 0.60-0.15
            "p_listed": [0.95, 0.66, 0.20, 0.08],
            "gap": [-0.03, 0.06, 0.05, 0.06],
        })
        out = _classify_boundaries(g)
        assert out["is_outer"].tolist() == [True, False, False, True]
        assert out["is_mode_flank"].tolist() == [False, True, True, False]
        assert int(out["is_largest"].sum()) == 1
