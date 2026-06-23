"""Tests for RVUtils.curve_fit_rv — written BEFORE implementation (TDD).

Run with:
    conda run -n stir python -m pytest tests/test_rv_curve_fit.py -v
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Helpers — synthetic data generators
# ---------------------------------------------------------------------------

MATURITIES = [0.5, 1.0, 2.0, 3.0, 5.0, 7.0, 10.0, 20.0, 30.0]

# NSS params used to plant "true" yields
NSS_PARAMS = dict(b0=4.0, b1=-2.0, b2=1.5, b3=0.5, lam=2.0, lam2=5.0)


def _nss_yield(tau, b0, b1, b2, b3, lam, lam2):
    """Nelson-Siegel-Svensson yield formula."""
    f1 = (1 - np.exp(-tau / lam)) / (tau / lam)
    f2 = f1 - np.exp(-tau / lam)
    f3 = (1 - np.exp(-tau / lam2)) / (tau / lam2) - np.exp(-tau / lam2)
    return b0 + b1 * f1 + b2 * f2 + b3 * f3


def _make_nss_snapshot(params=NSS_PARAMS, maturities=None, id_col="cusip"):
    """Return a single-date snapshot DataFrame."""
    mats = maturities or MATURITIES
    yields = [_nss_yield(t, **params) for t in mats]
    ids = [f"bond_{i}" for i in range(len(mats))]
    return pd.DataFrame({"maturity": mats, "yield": yields, id_col: ids})


def _make_nss_panel(n_dates=5, params=NSS_PARAMS, id_col="cusip"):
    """Return a panel DataFrame with `n_dates` slightly perturbed dates."""
    frames = []
    base_date = pd.Timestamp("2024-01-02")
    for i in range(n_dates):
        snap = _make_nss_snapshot(params=params, id_col=id_col).copy()
        snap["date"] = base_date + pd.tseries.offsets.BDay(i)
        # small random perturbation so each date is distinct but still close
        rng = np.random.default_rng(seed=i)
        snap["yield"] = snap["yield"] + rng.normal(0, 1e-4, len(snap))
        frames.append(snap)
    return pd.concat(frames, ignore_index=True)


def _make_linear_snapshot(a=2.0, b=0.15, maturities=None, id_col="cusip"):
    """Yields generated exactly as y = a + b*maturity (linear)."""
    mats = maturities or MATURITIES
    yields = [a + b * t for t in mats]
    ids = [f"bond_{i}" for i in range(len(mats))]
    return pd.DataFrame({"maturity": mats, "yield": yields, id_col: ids})


# ---------------------------------------------------------------------------
# Import — will fail until the module exists (RED)
# ---------------------------------------------------------------------------
from RVUtils.curve_fit_rv import make_curve_fit_builder  # noqa: E402


# ---------------------------------------------------------------------------
# Test 1 — NSS snapshot: curve recovers planted params (max |residual| < 1e-3)
# ---------------------------------------------------------------------------
class TestNSSSnapshot:
    def setup_method(self):
        snap = _make_nss_snapshot()
        (
            self.fit,
            self.residual_fn,
            self.rank_fn,
            self.rmse_fn,
            self.otr_spread_fn,
            self.get_data,
        ) = make_curve_fit_builder(snap, id_col="cusip", form="nss")

    def test_fit_returns_dataframe_with_required_columns(self):
        result = self.fit()
        assert isinstance(result, pd.DataFrame)
        for col in ("maturity", "yield", "fitted", "residual"):
            assert col in result.columns, f"Missing column: {col}"

    def test_nss_residual_below_1e3(self):
        """NSS curve fitted to its own data => residuals near machine precision."""
        self.fit()
        resid = self.residual_fn()
        # residual is the series/frame of (yield - fitted)
        vals = resid if isinstance(resid, np.ndarray) else np.asarray(resid)
        assert np.max(np.abs(vals)) < 1e-3, (
            f"Max |residual| = {np.max(np.abs(vals)):.6f} >= 1e-3"
        )


# ---------------------------------------------------------------------------
# Test 2 — Bump one bond +5bp; check residual ≈ +0.05 and rank #1 cheap
# ---------------------------------------------------------------------------
class TestBumpedBond:
    BUMPED_ID = "bond_4"  # 5-year bond

    def setup_method(self):
        snap = _make_nss_snapshot()
        # Bump the 5y bond by 5bp (0.05 in same units as yield)
        snap.loc[snap["cusip"] == self.BUMPED_ID, "yield"] += 0.05
        (
            self.fit,
            self.residual_fn,
            self.rank_fn,
            self.rmse_fn,
            self.otr_spread_fn,
            self.get_data,
        ) = make_curve_fit_builder(snap, id_col="cusip", form="ns")
        self.fit()

    def test_bumped_bond_residual_approx_5bp(self):
        resid = self.residual_fn()
        # resid should be a Series indexed by id or a DataFrame; get the bumped value
        if isinstance(resid, pd.Series):
            val = float(resid[self.BUMPED_ID])
        else:
            val = float(resid.loc[resid.index == self.BUMPED_ID].iloc[0])
        assert abs(val - 0.05) < 0.02, (
            f"Expected residual ~0.05 for bumped bond, got {val:.4f}"
        )

    def test_bumped_bond_ranked_first_cheap(self):
        ranking = self.rank_fn()
        # rank() returns cross-sectional ranking with most cheap (highest residual) first
        assert isinstance(ranking, pd.DataFrame)
        top = ranking.iloc[0]
        # The bumped bond should be the cheapest
        assert top["id"] == self.BUMPED_ID or str(top.name) == self.BUMPED_ID, (
            f"Expected {self.BUMPED_ID} to be ranked #1 cheap, got {top}"
        )


# ---------------------------------------------------------------------------
# Test 3 — Linear form on linear yields: residuals ≈ 0 (max abs < 1e-9)
# ---------------------------------------------------------------------------
class TestLinearForm:
    def setup_method(self):
        snap = _make_linear_snapshot(a=2.0, b=0.15)
        (
            self.fit,
            self.residual_fn,
            self.rank_fn,
            self.rmse_fn,
            self.otr_spread_fn,
            self.get_data,
        ) = make_curve_fit_builder(snap, id_col="cusip", form="linear")
        self.fit()

    def test_linear_residuals_near_zero(self):
        resid = self.residual_fn()
        vals = resid if isinstance(resid, np.ndarray) else np.asarray(resid)
        assert np.max(np.abs(vals)) < 1e-9, (
            f"Max |residual| for perfect linear data = {np.max(np.abs(vals)):.2e}"
        )


# ---------------------------------------------------------------------------
# Test 4 — rmse() positive, and ~0 for perfectly-fit linear case
# ---------------------------------------------------------------------------
class TestRMSE:
    def test_rmse_positive_nss(self):
        snap = _make_nss_snapshot()
        fit, _, _, rmse_fn, _, _ = make_curve_fit_builder(snap, id_col="cusip", form="nss")
        fit()
        r = rmse_fn()
        val = float(r) if np.isscalar(r) else float(r.iloc[0])
        assert val >= 0.0, f"RMSE should be non-negative, got {val}"

    def test_rmse_near_zero_for_perfect_linear(self):
        snap = _make_linear_snapshot()
        fit, _, _, rmse_fn, _, _ = make_curve_fit_builder(snap, id_col="cusip", form="linear")
        fit()
        r = rmse_fn()
        val = float(r) if np.isscalar(r) else float(r.iloc[0])
        assert val < 1e-9, f"RMSE should be ~0 for perfectly linear data, got {val:.2e}"


# ---------------------------------------------------------------------------
# Test 5 — Panel mode: 2 dates, fit per date, residual().zscore returns finite values
# ---------------------------------------------------------------------------
class TestPanelMode:
    def setup_method(self):
        panel = _make_nss_panel(n_dates=5)
        (
            self.fit,
            self.residual_fn,
            self.rank_fn,
            self.rmse_fn,
            self.otr_spread_fn,
            self.get_data,
        ) = make_curve_fit_builder(
            panel,
            id_col="cusip",
            date_col="date",
            form="nss",
        )
        self.fit()

    def test_panel_fit_returns_dataframe(self):
        result = self.fit()
        assert isinstance(result, pd.DataFrame)
        assert "date" in result.columns

    def test_panel_residual_zscore_finite(self):
        resid_ns = self.residual_fn()
        # residual() should be a SimpleNamespace with .zscore attribute in panel mode
        assert hasattr(resid_ns, "zscore"), "residual() in panel mode should return a SimpleNamespace with .zscore"
        z = resid_ns.zscore(window=3)
        assert isinstance(z, pd.DataFrame), f"zscore should return a DataFrame, got {type(z)}"
        # at least some finite values (bonds present across multiple dates)
        finite_count = z.notna().sum().sum()
        assert finite_count > 0, "Expected some finite z-scores for bonds present on multiple dates"

    def test_panel_rmse_is_series(self):
        r = self.rmse_fn()
        assert isinstance(r, pd.Series), f"Panel rmse() should return a Series, got {type(r)}"
        assert (r >= 0).all(), "All RMSE values should be non-negative"

    def test_get_data_returns_input(self):
        df = self.get_data()
        assert isinstance(df, pd.DataFrame)
        assert "maturity" in df.columns
        assert "yield" in df.columns


# ---------------------------------------------------------------------------
# Test 6 — otr_spread helper
# ---------------------------------------------------------------------------
class TestOtrSpread:
    def setup_method(self):
        snap = _make_nss_snapshot()
        (
            self.fit,
            self.residual_fn,
            self.rank_fn,
            self.rmse_fn,
            self.otr_spread_fn,
            self.get_data,
        ) = make_curve_fit_builder(snap, id_col="cusip", form="nss")
        self.fit()

    def test_otr_spread_sign(self):
        """bond_8 (30y) should have a higher yield than bond_0 (0.5y) in normal curve."""
        spread = self.otr_spread_fn("bond_8", "bond_0")
        # NSS with these params: 30y > 0.5y (upward-sloping at long end)
        assert isinstance(spread, float)
        # 30y - 0.5y should be positive for our NSS params
        assert spread > 0, f"Expected 30y-0.5y spread > 0, got {spread:.4f}"


# ---------------------------------------------------------------------------
# Test 7 — API: all six closures are callable before fit() (fit should work)
# ---------------------------------------------------------------------------
class TestAPIShape:
    def test_returns_six_callables(self):
        snap = _make_nss_snapshot()
        result = make_curve_fit_builder(snap, id_col="cusip", form="nss")
        assert len(result) == 6
        for fn in result:
            assert callable(fn)

    def test_get_data_matches_input(self):
        snap = _make_nss_snapshot()
        _, _, _, _, _, get_data = make_curve_fit_builder(snap, id_col="cusip", form="nss")
        pd.testing.assert_frame_equal(get_data(), snap, check_like=True)
