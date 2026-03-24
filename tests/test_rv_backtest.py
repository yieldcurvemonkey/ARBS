"""Tests for BT.signals.rv_backtest — RV strategy backtest engine."""

import numpy as np
import pandas as pd
import pytest

from BT.signals.rv_backtest import (
    RVBacktestConfig,
    RVBacktestResult,
    Trade,
    run_rv_backtest,
)


def _make_backtest_inputs(n_days: int = 250, seed: int = 42):
    """Create synthetic inputs for the backtest engine."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2023-01-01", periods=n_days, freq="B")

    fly_ids = ["2Y/5Y/10Y", "3Y/7Y/15Y"]
    categories = {"2Y/5Y/10Y": "standard_spot", "3Y/7Y/15Y": "standard_spot"}

    residuals = {}
    zscores = {}
    rsq = {}
    weights = {}
    rates = {}

    for fid in fly_ids:
        # Mean-reverting residual
        res = np.zeros(n_days)
        for i in range(1, n_days):
            res[i] = 0.85 * res[i - 1] + rng.normal(0, 0.0003)
        residuals[fid] = pd.Series(res, index=dates)
        zscores[fid] = pd.Series(res / 0.0003 * 0.3, index=dates)  # roughly z-scored
        rsq[fid] = pd.Series(0.75, index=dates)  # constant high R²
        weights[fid] = pd.DataFrame(
            np.tile([-0.9, 1.0, -0.46], (n_days, 1)),
            index=dates,
            columns=["left", "belly", "right"],
        )
        rates[fid] = pd.DataFrame(
            rng.normal(3.5, 0.01, (n_days, 3)) + np.cumsum(rng.normal(0, 0.001, (n_days, 3)), axis=0),
            index=dates,
            columns=["left", "belly", "right"],
        )

    regime = pd.Series("green", index=dates)

    return residuals, zscores, rsq, weights, rates, regime, categories


class TestRVBacktest:
    def test_output_structure(self):
        residuals, zscores, rsq, weights, rates, regime, cats = _make_backtest_inputs()
        config = RVBacktestConfig(entry_min_zscore=0.5)
        result = run_rv_backtest(
            residuals=residuals,
            zscores=zscores,
            rsq=rsq,
            weights=weights,
            rates=rates,
            regime=regime,
            fly_categories=cats,
            config=config,
        )
        assert isinstance(result, RVBacktestResult)
        assert isinstance(result.trades, list)
        assert isinstance(result.daily_pnl, pd.Series)
        assert isinstance(result.cumulative_pnl, pd.Series)
        assert "sharpe" in result.metrics

    def test_no_trades_when_red_regime(self):
        residuals, zscores, rsq, weights, rates, regime, cats = _make_backtest_inputs()
        regime[:] = "red"  # all red
        config = RVBacktestConfig(entry_min_zscore=0.1)
        result = run_rv_backtest(
            residuals=residuals, zscores=zscores, rsq=rsq, weights=weights,
            rates=rates, regime=regime, fly_categories=cats, config=config,
        )
        assert len(result.trades) == 0

    def test_no_duplicate_flies(self):
        residuals, zscores, rsq, weights, rates, regime, cats = _make_backtest_inputs()
        config = RVBacktestConfig(entry_min_zscore=0.3, no_duplicate_flies=True)
        result = run_rv_backtest(
            residuals=residuals, zscores=zscores, rsq=rsq, weights=weights,
            rates=rates, regime=regime, fly_categories=cats, config=config,
        )
        # Check no overlapping trades on the same fly
        # Use strict inequality: same-day exit/entry is sequential, not overlapping
        for t in result.trades:
            overlapping = [
                o for o in result.trades
                if o.fly_id == t.fly_id
                and o is not t
                and o.entry_date < (t.exit_date or t.entry_date)
                and (o.exit_date or o.entry_date) > t.entry_date
            ]
            assert len(overlapping) == 0, f"Duplicate fly {t.fly_id}"

    def test_max_holding_period_respected(self):
        residuals, zscores, rsq, weights, rates, regime, cats = _make_backtest_inputs()
        config = RVBacktestConfig(
            entry_min_zscore=0.3,
            exit_max_holding_days=10,
            exit_mean_reversion=False,
            exit_stop_loss_sd=999.0,  # disable stop loss
        )
        result = run_rv_backtest(
            residuals=residuals, zscores=zscores, rsq=rsq, weights=weights,
            rates=rates, regime=regime, fly_categories=cats, config=config,
        )
        for t in result.trades:
            if t.exit_date is not None:
                holding = len(pd.bdate_range(t.entry_date, t.exit_date)) - 1
                assert holding <= config.exit_max_holding_days + 1  # +1 for boundary

    def test_approximate_pnl_nonzero(self):
        residuals, zscores, rsq, weights, rates, regime, cats = _make_backtest_inputs()
        config = RVBacktestConfig(mtm_mode="approximate", entry_min_zscore=0.3)
        result = run_rv_backtest(
            residuals=residuals, zscores=zscores, rsq=rsq, weights=weights,
            rates=rates, regime=regime, fly_categories=cats, config=config,
        )
        if len(result.trades) > 0:
            assert result.daily_pnl.abs().sum() > 0
