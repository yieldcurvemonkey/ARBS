"""Tests for PCA engine additions (Task 2) and pca_rv builder (Task 3)."""
import numpy as np
import pandas as pd
import pytest

from RVUtils.df_based_pca_risk_model import fit_curve_pca_from_timeseries
from RVUtils.pca_rv import make_pca_rv_builder


def _panel(n=700, seed=0, noise=0.002):
    """3-factor synthetic curve (level/slope/curvature) on 4 tenors."""
    rng = np.random.default_rng(seed)
    cols = ["2", "5", "10", "30"]
    L = np.array([[1.0, -1.5, 1.0],
                  [1.0, -0.5, -1.0],
                  [1.0, 0.5, -0.5],
                  [1.0, 1.5, 1.0]])
    f = np.cumsum(rng.standard_normal((n, 3)) * np.array([0.05, 0.03, 0.02]), axis=0)
    base = np.array([2.0, 2.5, 3.0, 3.5])
    X = base + f @ L.T + rng.standard_normal((n, 4)) * noise
    idx = pd.date_range("2022-01-03", periods=n, freq="B")
    return pd.DataFrame(X, index=idx, columns=cols)


# ---- Task 2: engine additions ----

def test_engine_backward_compatible_default():
    df = _panel()
    model, scores = fit_curve_pca_from_timeseries(df, use_changes=True, sort_by_tenor=False)
    assert list(model.loadings.columns) == ["PC1", "PC2", "PC3", "PC4"]
    assert scores.shape[1] == 4


def test_engine_reconstruct_identity_full_rank():
    df = _panel()
    model, _ = fit_curve_pca_from_timeseries(df, use_changes=False, sort_by_tenor=False)
    x = df.iloc[-1]
    rec = model.reconstruct(x, k=4)
    assert np.allclose(rec.values, x.values, atol=1e-8)


def test_engine_explained_variance_sums_one():
    df = _panel()
    model, _ = fit_curve_pca_from_timeseries(df, use_changes=False, sort_by_tenor=False)
    ev = model.explained_variance()
    assert ev.sum() == pytest.approx(1.0, abs=1e-9)
    assert ev.iloc[0] > 0.5  # PC1 dominates a level-driven curve


def test_engine_sign_pinning_opt_in():
    df = _panel()
    model, _ = fit_curve_pca_from_timeseries(df, use_changes=False, sort_by_tenor=False, pin_signs=True)
    for pc in model.loadings.columns:
        col = model.loadings[pc].values
        assert col[np.argmax(np.abs(col))] > 0  # largest-abs loading is positive


# ---- Task 3: pca_rv builder ----

def test_fly_weights_neutralize_pc1_pc2():
    df = _panel()
    (fit, fair_value, residual, fly_weights, curve_weights,
     directionality, risk_buckets, factor_corr_check, get_model) = \
        make_pca_rv_builder(df, on="levels", n_factors=3, sort_by_tenor=False)
    fit()
    w = fly_weights("2", "10", "30", neutralize=("PC1", "PC2"))  # short, body, long
    model, _ = get_model()
    e1 = model.loadings.loc[["2", "10", "30"], "PC1"].values
    e2 = model.loadings.loc[["2", "10", "30"], "PC2"].values
    wv = np.array([w["2"], w["10"], w["30"]])
    assert abs(float(e1 @ wv)) < 1e-9
    assert abs(float(e2 @ wv)) < 1e-9
    assert w["10"] == pytest.approx(1.0)  # belly normalized


def test_curve_weights_neutralize_pc1():
    df = _panel()
    (fit, fair_value, residual, fly_weights, curve_weights,
     directionality, risk_buckets, factor_corr_check, get_model) = \
        make_pca_rv_builder(df, on="levels", sort_by_tenor=False)
    fit()
    w = curve_weights("2", "10", neutralize=("PC1",))
    model, _ = get_model()
    e1 = model.loadings.loc[["2", "10"], "PC1"].values
    wv = np.array([w["2"], w["10"]])
    assert abs(float(e1 @ wv)) < 1e-9


def test_residual_is_finite_and_chainable():
    df = _panel()
    (fit, fair_value, residual, fly_weights, curve_weights,
     directionality, risk_buckets, factor_corr_check, get_model) = \
        make_pca_rv_builder(df, on="levels", n_factors=2, sort_by_tenor=False)
    fit()
    res = residual("10")
    assert res.series.notna().sum() > 100
    z = res.zscore(60)
    assert z.notna().sum() > 50


def test_risk_buckets_projects_ladder():
    df = _panel()
    (fit, fair_value, residual, fly_weights, curve_weights,
     directionality, risk_buckets, factor_corr_check, get_model) = \
        make_pca_rv_builder(df, on="changes", sort_by_tenor=False)
    fit()
    model, _ = get_model()
    ladder = pd.Series([0.0, 0.0, 1.0, 0.0], index=["2", "5", "10", "30"])  # unit at 10y
    f = risk_buckets(ladder)
    assert f["PC1"] == pytest.approx(model.loadings.loc["10", "PC1"], abs=1e-9)


def test_fair_value_changes_mode_returns_levels():
    df = _panel()
    (fit, fair_value, residual, fly_weights, curve_weights,
     directionality, risk_buckets, factor_corr_check, get_model) = \
        make_pca_rv_builder(df, on="changes", n_factors=3, sort_by_tenor=False)
    fit()
    fv = fair_value(k=3)
    assert isinstance(fv, pd.DataFrame)
    assert fv.shape[1] == 4
    assert abs(fv["10"].iloc[-1] - df["10"].iloc[-1]) < 1.0


def test_directionality_returns_betas_and_residual():
    df = _panel()
    (fit, fair_value, residual, fly_weights, curve_weights,
     directionality, risk_buckets, factor_corr_check, get_model) = \
        make_pca_rv_builder(df, on="levels", sort_by_tenor=False)
    fit()
    out = directionality(("2", "10", "30"), weights={"2": -1, "10": 2, "30": -1}, drivers=("PC1", "PC2"))
    assert "betas" in out and "residual" in out
    assert out["residual"].notna().sum() > 100
