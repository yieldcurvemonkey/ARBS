"""Tests for RVUtils.FlyVsVol.pair_backtest (synthetic wing panel, no network)."""
import numpy as np
import pandas as pd
import pytest

from RVUtils.FlyVsVol.pair_backtest import (
    PairBacktestConfig,
    grid_search,
    prepare_data,
    run_pair_backtest,
)

DATES = pd.bdate_range("2026-01-05", periods=60)


def make_data(spike_days=(49, 50, 51), spike=5.0, bad_resid_day=None):
    wing_rows, con_rows = [], []
    for i, ts in enumerate(DATES):
        bump = spike if i in spike_days else 0.0
        for sym, prems in (("SFRU26", {"P": 5.0, "C": 3.0}),
                           ("SFRZ26", {"P": 8.0 + bump, "C": 4.0})):
            for right, prem in prems.items():
                k_rate = 4.375 if right == "P" else 3.625
                wing_rows.append({
                    "as_of": ts, "symbol": sym, "right": right,
                    "strike_price": 100 - k_rate, "strike_rate": k_rate,
                    "premium_bp": prem, "oi": 10_000.0,
                })
            resid = 5.0 if (bad_resid_day is not None and i == bad_resid_day
                            and sym == "SFRZ26") else 0.0
            con_rows.append({
                "as_of": ts, "symbol": sym, "forward_rate": 4.0,
                "mean_rate": 4.0, "median_rate": 4.0, "mm_bp": 0.0,
                "fwd_resid_bp": resid, "pre_norm_mass": 1.0,
            })
    return pd.DataFrame(wing_rows), pd.DataFrame(con_rows)


CFG = PairBacktestConfig(basis="premium", ma=1, zscore_window=30,
                         zscore_min_periods=20, entry_min_zscore=2.0,
                         exit_style="z0", exit_max_holding_days=15,
                         lag=1, round_trip_cost_bp=1.0)


def test_prepare_data_strike_selection_and_basis():
    wings, cons = make_data(spike_days=())
    data = prepare_data(wings, cons)
    prem = data["premium"]
    assert set(prem["label"]) == {"SFRU26-SFRZ26"}
    row = prem.iloc[0]
    # basis = (8-4) - (5-3) = +2, strikes at 4.375P / 3.625C both legs
    assert row["prem_basis_bp"] == pytest.approx(2.0)
    assert row["hk_K_b"] == pytest.approx(100 - 4.375)
    assert row["ct_K_f"] == pytest.approx(100 - 3.625)
    assert bool(row["quality_ok"])


def test_spike_trade_lag_and_pnl():
    wings, cons = make_data()
    data = prepare_data(wings, cons)
    res = run_pair_backtest(CFG, data=data)
    assert len(res.trades) == 1
    tr = res.trades.iloc[0]
    assert tr["dir"] == -1                       # basis spiked rich -> fade short
    # lag-1: entry executed one business day after the signal
    assert (tr["entry"] - tr["signal_date"]).days >= 1
    # entry lands inside the spike (basis 7), exits after it collapses to 2
    assert tr["gross_bp"] == pytest.approx(5.0, abs=1e-9)
    assert tr["net_bp"] == pytest.approx(4.0, abs=1e-9)
    assert tr["exit_reason"] in ("mean_reversion", "max_hold")
    # daily pnl sums exactly to net
    assert res.daily_pnl.sum() == pytest.approx(tr["net_bp"], abs=1e-9)
    assert res.metrics["total_net_bp"] == pytest.approx(4.0, abs=1e-9)
    assert res.metrics["n_trades"] == 1


def test_quality_gate_blocks_entry():
    wings, cons = make_data(bad_resid_day=49)
    data = prepare_data(wings, cons)
    res = run_pair_backtest(CFG, data=data)
    # signal day 49 gated; day 50/51 still spiked -> may enter later or not at all
    assert all(res.trades["signal_date"] != DATES[49]) if len(res.trades) else True
    res2 = run_pair_backtest(
        PairBacktestConfig(**{**CFG.__dict__, "quality_gate": False}), data=data)
    assert len(res2.trades) >= len(res.trades)


def test_skew_basis_runs():
    wings, cons = make_data()
    data = prepare_data(wings, cons)
    cfg = PairBacktestConfig(**{**CFG.__dict__, "basis": "skew",
                                "entry_min_zscore": 0.5})
    res = run_pair_backtest(cfg, data=data)   # mm all zero -> no signal ever
    assert res.metrics["n_trades"] == 0


def test_grid_search_shape():
    wings, cons = make_data()
    data = prepare_data(wings, cons)
    out = grid_search({"entry_min_zscore": [1.5, 2.0], "exit_style": ["z0", "t10"]},
                      data=data, base=CFG)
    assert len(out) == 4
    for col in ("config", "n_trades", "total_net_bp", "hit_rate", "sharpe"):
        assert col in out.columns
