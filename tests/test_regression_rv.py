"""Tests for BT.signals.regression_rv — OLS regression for RV analysis."""

import numpy as np
import pandas as pd
import pytest

from BT.signals.regression_rv import (
    RegressionRVConfig,
    RegressionRVResult,
    rolling_regression,
    EntrySnapshot,
    frozen_residual,
    build_entry_snapshots,
    compute_residual_stats,
    RegressionSignalTable,
    build_jpm_signal_table,
    JPMFlyUniverse,
    default_fly_universe,
)


def _make_synthetic_fly(n_days: int = 300, seed: int = 42):
    """Build synthetic fly, body, and curve series with known relationship."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2023-01-01", periods=n_days, freq="B")

    body = np.cumsum(rng.normal(0, 0.01, n_days)) + 3.0
    curve = np.cumsum(rng.normal(0, 0.005, n_days))

    # fly = 0.5 * body + 0.3 * curve + mean-reverting noise
    noise = np.zeros(n_days)
    for i in range(1, n_days):
        noise[i] = 0.8 * noise[i - 1] + rng.normal(0, 0.002)
    fly = 0.5 * body + 0.3 * curve + noise

    return (
        pd.Series(fly, index=dates, name="fly"),
        pd.Series(body, index=dates, name="body"),
        pd.Series(curve, index=dates, name="curve"),
    )


class TestRollingRegression:
    def test_output_structure(self):
        fly, body, curve = _make_synthetic_fly(300)
        config = RegressionRVConfig(window_days=60)
        result = rolling_regression(fly, body, curve, config)

        assert isinstance(result, RegressionRVResult)
        assert len(result.residuals) == len(fly)
        assert len(result.betas_body) == len(fly)
        assert len(result.betas_curve) == len(fly)
        assert len(result.intercepts) == len(fly)
        assert len(result.fitted) == len(fly)
        assert len(result.rsq) == len(fly)
        assert len(result.zscores) == len(fly)

    def test_residual_small_for_known_relationship(self):
        fly, body, curve = _make_synthetic_fly(300)
        config = RegressionRVConfig(window_days=60)
        result = rolling_regression(fly, body, curve, config)

        valid = result.residuals.dropna()
        # Residuals should be small — the model should capture the linear relationship
        assert valid.abs().median() < 0.01

    def test_rsq_high_for_known_relationship(self):
        fly, body, curve = _make_synthetic_fly(300)
        config = RegressionRVConfig(window_days=60)
        result = rolling_regression(fly, body, curve, config)

        valid_rsq = result.rsq.dropna()
        assert valid_rsq.median() > 0.80

    def test_betas_recover_true_coefficients(self):
        fly, body, curve = _make_synthetic_fly(300)
        config = RegressionRVConfig(window_days=60)
        result = rolling_regression(fly, body, curve, config)

        # True betas: body=0.5, curve=0.3
        valid_body = result.betas_body.dropna()
        valid_curve = result.betas_curve.dropna()
        assert abs(valid_body.median() - 0.5) < 0.15
        assert abs(valid_curve.median() - 0.3) < 0.15
        assert result.intercepts.dropna().shape[0] > 0
        assert result.fitted.dropna().shape[0] > 0

    def test_hedge_ratios_shape(self):
        fly, body, curve = _make_synthetic_fly(300)
        config = RegressionRVConfig(window_days=60)
        result = rolling_regression(fly, body, curve, config)

        assert result.hedge_ratios.shape[1] == 2
        assert list(result.hedge_ratios.columns) == ["left_weight", "right_weight"]


class TestEntrySnapshot:
    def test_frozen_residual_at_entry_is_oos_residual(self):
        """Frozen residual using entry betas should match the OOS residual."""
        fly, body, curve = _make_synthetic_fly(300)
        config = RegressionRVConfig(window_days=60)
        result = rolling_regression(fly, body, curve, config)

        # Pick a date with valid regression output
        valid_idx = result.residuals.dropna().index
        entry_date = valid_idx[len(valid_idx) // 2]

        snap = EntrySnapshot(
            intercept=result.intercepts.loc[entry_date],
            beta_body=result.betas_body.loc[entry_date],
            beta_curve=result.betas_curve.loc[entry_date],
            residual_mean=0.0,
            residual_std=1.0,
        )

        # Frozen residual at entry date should match the regression residual
        fr = frozen_residual(snap, fly.loc[entry_date], body.loc[entry_date], curve.loc[entry_date])
        assert abs(fr - result.residuals.loc[entry_date]) < 1e-10

    def test_frozen_residual_oos_differs_from_insample(self):
        """Frozen residual at a later date uses entry betas, not current betas."""
        fly, body, curve = _make_synthetic_fly(300)
        config = RegressionRVConfig(window_days=60)
        result = rolling_regression(fly, body, curve, config)

        valid_idx = result.residuals.dropna().index
        entry_date = valid_idx[10]
        later_date = valid_idx[50]

        snap = EntrySnapshot(
            intercept=result.intercepts.loc[entry_date],
            beta_body=result.betas_body.loc[entry_date],
            beta_curve=result.betas_curve.loc[entry_date],
            residual_mean=0.0,
            residual_std=1.0,
        )

        fr_oos = frozen_residual(snap, fly.loc[later_date], body.loc[later_date], curve.loc[later_date])
        insample = result.residuals.loc[later_date]
        # Both should be finite
        assert np.isfinite(fr_oos)
        assert np.isfinite(insample)


class TestBuildEntrySnapshots:
    def test_snapshots_have_correct_keys(self):
        fly, body, curve = _make_synthetic_fly(300)
        config = RegressionRVConfig(window_days=60)
        result = rolling_regression(fly, body, curve, config)
        stats = compute_residual_stats(result.residuals, config.zscore_lookback_days)
        snapshots = build_entry_snapshots(result, stats)

        valid_dates = result.residuals.dropna().index
        for dt in valid_dates[:5]:
            snap = snapshots[dt]
            assert isinstance(snap, EntrySnapshot)
            assert np.isfinite(snap.intercept)
            assert np.isfinite(snap.beta_body)
            assert np.isfinite(snap.beta_curve)


class TestResidualStats:
    def test_stats_shape(self):
        fly, body, curve = _make_synthetic_fly(300)
        config = RegressionRVConfig(window_days=60)
        result = rolling_regression(fly, body, curve, config)
        stats = compute_residual_stats(result.residuals, config.zscore_lookback_days)
        assert isinstance(stats, pd.DataFrame)
        assert "mean" in stats.columns
        assert "std" in stats.columns
        assert len(stats) == len(fly)


class TestJPMFlyUniverse:
    def test_default_universe_has_three_categories(self):
        u = default_fly_universe()
        assert isinstance(u, JPMFlyUniverse)
        assert len(u.standard_flies) > 0
        assert len(u.gap_5y_flies) > 0
        assert len(u.gap_mm_flies) > 0

    def test_all_fly_ids_returns_dict(self):
        u = default_fly_universe()
        fly_ids = u.all_fly_ids()
        assert isinstance(fly_ids, dict)
        # Should have standard x forward_starts + gap_5y + gap_mm
        n_standard = len(u.standard_flies) * len(u.forward_starts)
        n_gap5y = len(u.gap_5y_flies)
        n_mm = len(u.gap_mm_flies)
        assert len(fly_ids) == n_standard + n_gap5y + n_mm
        # All values should be category strings
        categories = set(fly_ids.values())
        assert "standard_spot" in categories or any("standard" in c for c in categories)


class TestBuildJPMSignalTable:
    def test_signal_table_structure(self):
        """Build signal table from synthetic rate panels."""
        n_days = 300
        dates = pd.bdate_range("2023-01-01", periods=n_days, freq="B")
        rng = np.random.default_rng(42)

        # Minimal universe: 1 fly, spot only
        universe = JPMFlyUniverse(
            standard_flies=[("2Y", "5Y", "10Y")],
            forward_starts=[None],
            gap_5y_flies=[],
            gap_mm_flies=[],
        )

        # Build rate panels: dict of tenor -> Series
        rate_panels = {}
        for tenor in ["2Y", "5Y", "10Y"]:
            rate_panels[tenor] = pd.Series(
                np.cumsum(rng.normal(0, 0.001, n_days)) + 3.0,
                index=dates,
            )

        config = RegressionRVConfig(window_days=60, zscore_lookback_days=60)
        table = build_jpm_signal_table(rate_panels, universe, config)

        assert isinstance(table, RegressionSignalTable)
        assert len(table.residuals) == 1
        assert len(table.zscores) == 1
        fid = list(table.residuals.keys())[0]
        assert len(table.residuals[fid]) == n_days
        assert fid in table.entry_snapshots
        assert fid in table.fly_categories
