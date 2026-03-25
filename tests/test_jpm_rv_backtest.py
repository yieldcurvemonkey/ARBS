"""Tests for BT.signals.jpm_rv_backtest — JPM RV query-driven backtest engine."""

import numpy as np
import pandas as pd
import pytest

from BT.signals.regression_rv import (
    EntrySnapshot,
    RegressionRVConfig,
    RegressionSignalTable,
    compute_residual_stats,
    rolling_regression,
    build_entry_snapshots,
)
from BT.signals.jpm_rv_backtest import (
    JPMRVBacktestConfig,
    JPMRVBacktestResult,
    _JPMRVQuerySignalAction,
    run_jpm_rv_backtest,
)


def _make_jpm_backtest_inputs(n_days: int = 300, n_flies: int = 2, seed: int = 42):
    """Create synthetic RegressionSignalTable for testing."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2023-01-01", periods=n_days, freq="B")

    fly_ids = [f"jpm_rv_standard_spot_2Y_5Y_{10 + i}Y" for i in range(n_flies)]
    categories = {fid: "standard_spot" for fid in fly_ids}

    residuals = {}
    zscores = {}
    rsq = {}
    betas_body = {}
    betas_curve = {}
    intercepts = {}
    fly_series = {}
    body_series = {}
    curve_series = {}
    residual_stats = {}
    entry_snapshots = {}

    for fid in fly_ids:
        # Mean-reverting residual
        res = np.zeros(n_days)
        for i in range(1, n_days):
            res[i] = 0.85 * res[i - 1] + rng.normal(0, 0.0003)
        residuals[fid] = pd.Series(res, index=dates)

        roll_std = pd.Series(res, index=dates).rolling(60, min_periods=20).std().fillna(0.0003)
        roll_mean = pd.Series(res, index=dates).rolling(60, min_periods=20).mean().fillna(0.0)
        roll_std = roll_std.replace(0.0, 0.0003)
        zscores[fid] = (pd.Series(res, index=dates) - roll_mean) / roll_std

        rsq[fid] = pd.Series(0.85, index=dates)
        betas_body[fid] = pd.Series(0.5, index=dates)
        betas_curve[fid] = pd.Series(0.3, index=dates)
        intercepts[fid] = pd.Series(0.01, index=dates)

        body = pd.Series(np.cumsum(rng.normal(0, 0.001, n_days)) + 3.5, index=dates)
        curve = pd.Series(np.cumsum(rng.normal(0, 0.0005, n_days)), index=dates)
        fly = 0.01 + 0.5 * body + 0.3 * curve + res
        fly_series[fid] = fly
        body_series[fid] = body
        curve_series[fid] = curve

        stats = pd.DataFrame({"mean": roll_mean, "std": roll_std}, index=dates)
        residual_stats[fid] = stats

        snaps = {}
        for dt in dates[60:]:
            snaps[dt] = EntrySnapshot(
                intercept=0.01,
                beta_body=0.5,
                beta_curve=0.3,
                residual_mean=float(roll_mean.loc[dt]),
                residual_std=float(roll_std.loc[dt]),
            )
        entry_snapshots[fid] = snaps

    regime = pd.Series("green", index=dates)

    table = RegressionSignalTable(
        residuals=residuals,
        zscores=zscores,
        rsq=rsq,
        betas_body=betas_body,
        betas_curve=betas_curve,
        intercepts=intercepts,
        fly_series=fly_series,
        body_series=body_series,
        curve_series=curve_series,
        fly_categories=categories,
        residual_stats=residual_stats,
        entry_snapshots=entry_snapshots,
    )
    return table, regime, dates


class TestJPMRVBacktestConfig:
    def test_defaults(self):
        config = JPMRVBacktestConfig()
        assert config.exit_max_holding_days == 22
        assert config.exit_stop_loss_sd == 2.0
        assert config.entry_min_rsq == 0.60
        assert config.trade_belly_bpv == 100_000.0


def _make_stop_loss_table(n_days, dates, fid, res, snapshot):
    """Build a RegressionSignalTable where frozen_residual matches the given residuals.

    Given snapshot (intercept, beta_body, beta_curve) and constant body/curve,
    construct fly = fitted + residual so frozen_residual returns the expected values.
    """
    body_val = 3.5
    curve_val = 0.1
    fitted = snapshot.intercept + snapshot.beta_body * body_val + snapshot.beta_curve * curve_val
    fly_vals = fitted + res

    return RegressionSignalTable(
        residuals={fid: pd.Series(res, index=dates)},
        zscores={fid: pd.Series(res / 0.0003, index=dates)},
        rsq={fid: pd.Series(0.9, index=dates)},
        betas_body={fid: pd.Series(0.5, index=dates)},
        betas_curve={fid: pd.Series(0.3, index=dates)},
        intercepts={fid: pd.Series(0.01, index=dates)},
        fly_series={fid: pd.Series(fly_vals, index=dates)},
        body_series={fid: pd.Series(np.full(n_days, body_val), index=dates)},
        curve_series={fid: pd.Series(np.full(n_days, curve_val), index=dates)},
        fly_categories={fid: "test"},
        residual_stats={fid: pd.DataFrame({
            "mean": np.zeros(n_days),
            "std": np.full(n_days, 0.0003),
        }, index=dates)},
        entry_snapshots={fid: {
            dt: snapshot for dt in dates
        }},
    )


class TestStopLossDirection:
    """Verify the stop-loss bug fix: stop-loss should only fire on directional worsening."""

    def test_stop_loss_fires_on_worsening(self):
        """If entry residual is +0.001 (pay belly), stop when residual goes MORE positive."""
        n_days = 100
        dates = pd.bdate_range("2023-01-01", periods=n_days, freq="B")
        fid = "test_fly"
        snapshot = EntrySnapshot(0.01, 0.5, 0.3, 0.0, 0.0003)

        # Residual starts at 0.001, then shoots to 0.005 (worsening for short/pay belly)
        res = np.zeros(n_days)
        res[:20] = 0.001
        res[20:] = 0.005  # way worse

        table = _make_stop_loss_table(n_days, dates, fid, res, snapshot)
        regime = pd.Series("green", index=dates)
        config = JPMRVBacktestConfig(
            entry_min_zscore=1.0,
            entry_min_residual_bp=0.1,
            entry_min_rsq=0.5,
            exit_stop_loss_sd=2.0,
            exit_max_holding_days=999,
        )
        result = run_jpm_rv_backtest(
            signal_table=table, regime=regime, mdp=None, config=config
        )
        stopped = [t for _, t in result.trades.iterrows() if t.get("exit_reason") == "stop_loss"]
        assert len(stopped) > 0, "Stop-loss should have fired on worsening residual"

    def test_stop_loss_does_not_fire_on_improving(self):
        """If entry residual is +0.001, moving toward zero (improving) should NOT stop out."""
        n_days = 100
        dates = pd.bdate_range("2023-01-01", periods=n_days, freq="B")
        fid = "test_fly"
        snapshot = EntrySnapshot(0.01, 0.5, 0.3, 0.0, 0.0003)

        # Residual starts at 0.001, then reverts toward 0
        res = np.zeros(n_days)
        res[:20] = 0.001
        res[20:] = 0.0001  # improving

        table = _make_stop_loss_table(n_days, dates, fid, res, snapshot)
        regime = pd.Series("green", index=dates)
        config = JPMRVBacktestConfig(
            entry_min_zscore=1.0,
            entry_min_residual_bp=0.1,
            entry_min_rsq=0.5,
            exit_stop_loss_sd=2.0,
            exit_max_holding_days=999,
        )
        result = run_jpm_rv_backtest(
            signal_table=table, regime=regime, mdp=None, config=config
        )
        stopped = [t for _, t in result.trades.iterrows() if t.get("exit_reason") == "stop_loss"]
        assert len(stopped) == 0, "Stop-loss should NOT fire when residual improves"


class TestMaxHoldingDays:
    def test_no_trade_exceeds_max_holding(self):
        table, regime, dates = _make_jpm_backtest_inputs(n_days=300)
        config = JPMRVBacktestConfig(
            entry_min_zscore=0.5,
            entry_min_residual_bp=0.01,
            exit_max_holding_days=22,
            exit_mean_reversion=False,
            exit_stop_loss_sd=999.0,
        )
        result = run_jpm_rv_backtest(
            signal_table=table, regime=regime, mdp=None, config=config
        )
        if len(result.trades) > 0:
            for _, trade in result.trades.iterrows():
                if "holding_days" in trade and pd.notna(trade["holding_days"]):
                    assert trade["holding_days"] <= config.exit_max_holding_days + 1


class TestRegimeFiltering:
    def test_no_entries_when_red(self):
        table, regime, dates = _make_jpm_backtest_inputs(n_days=200)
        regime[:] = "red"
        config = JPMRVBacktestConfig(entry_min_zscore=0.1, entry_min_residual_bp=0.001)
        result = run_jpm_rv_backtest(
            signal_table=table, regime=regime, mdp=None, config=config
        )
        assert len(result.trades) == 0


class TestNoDuplicateFlies:
    def test_no_overlapping_same_fly(self):
        table, regime, dates = _make_jpm_backtest_inputs(n_days=300)
        config = JPMRVBacktestConfig(
            entry_min_zscore=0.3,
            entry_min_residual_bp=0.001,
            no_duplicate_flies=True,
        )
        result = run_jpm_rv_backtest(
            signal_table=table, regime=regime, mdp=None, config=config
        )
        if len(result.trades) > 1:
            for i, t1 in result.trades.iterrows():
                for j, t2 in result.trades.iterrows():
                    if i >= j:
                        continue
                    if t1["fly_id"] == t2["fly_id"]:
                        # Should not overlap
                        if pd.notna(t1.get("exit_date")) and pd.notna(t2.get("entry_date")):
                            assert t1["exit_date"] <= t2["entry_date"] or t2["exit_date"] <= t1["entry_date"]


class TestJPMRVBacktestResult:
    def test_result_structure(self):
        table, regime, dates = _make_jpm_backtest_inputs(n_days=300)
        config = JPMRVBacktestConfig(entry_min_zscore=0.5, entry_min_residual_bp=0.01)
        result = run_jpm_rv_backtest(
            signal_table=table, regime=regime, mdp=None, config=config
        )
        assert isinstance(result, JPMRVBacktestResult)
        assert isinstance(result.daily_pnl, pd.Series)
        assert isinstance(result.trades, pd.DataFrame)
        assert isinstance(result.metrics, dict)
        assert "sharpe" in result.metrics
        assert "hit_rate" in result.metrics
