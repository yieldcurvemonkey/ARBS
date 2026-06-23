"""Regression tests for fixes from the final code review (Important items + look-ahead)."""
import numpy as np
import pandas as pd
import pytest

from RVUtils.pca_rv import make_pca_rv_builder
from RVUtils.signal_backtest import make_signal_backtest_builder
from RVUtils.mean_reversion import calibrate_ou, ou_ex_ante_sharpe


def _ou(n, seed, kappa=0.1, sigma=0.1):
    r = np.random.default_rng(seed)
    phi = np.exp(-kappa)
    s = np.empty(n)
    s[0] = 0.0
    for t in range(1, n):
        s[t] = phi * s[t - 1] + sigma * r.standard_normal()
    return pd.Series(s, index=pd.date_range("2022-01-03", periods=n, freq="B"), name="sig")


def _pca_df(n=200, seed=0):
    rng = np.random.default_rng(seed)
    X = rng.standard_normal((n, 3)).cumsum(0) * 0.05 + np.array([2.0, 2.5, 3.0])
    return pd.DataFrame(X, columns=["2y", "5y", "10y"], index=pd.date_range("2022", periods=n, freq="B"))


def test_directionality_minvar_raises():
    b = make_pca_rv_builder(_pca_df(), on="levels", sort_by_tenor=False)
    b[0]()
    directionality = b[5]
    with pytest.raises(ValueError):
        directionality(("2y", "5y", "10y"), weights={"2y": -1, "5y": 2, "10y": -1}, method="minvar")
    # supported methods still work
    out = directionality(("2y", "5y", "10y"), weights={"2y": -1, "5y": 2, "10y": -1}, method="pca")
    assert "betas" in out


def test_forecast_reversion_flips_sign():
    sig = _ou(500, 1)
    fc, *_ = make_signal_backtest_builder(sig)
    a = fc()
    b = fc(reversion=True)
    pd.testing.assert_series_equal(b.dropna(), (-a).dropna(), check_names=False)


def test_forecast_causal_window_no_lookahead():
    sig = _ou(500, 2)
    fc, *_ = make_signal_backtest_builder(sig)
    f_full = fc(window=60)
    t = 400
    fc2, *_ = make_signal_backtest_builder(sig.iloc[: t + 1])
    f_tr = fc2(window=60)
    assert np.isfinite(f_full.iloc[t])
    assert f_full.iloc[t] == pytest.approx(f_tr.iloc[-1], rel=1e-9)


def test_pnl_uses_lagged_position_no_lookahead():
    sig = _ou(500, 3)
    fc, zsig, position, pnl, *_ = make_signal_backtest_builder(sig)
    pos = zsig(window=60)
    p = pnl(pos)
    manual = pos.shift(1) * sig.diff()
    pd.testing.assert_series_equal(p.dropna(), manual.dropna(), check_names=False)


def test_ex_ante_sharpe_declines_with_horizon():
    sig = _ou(2000, 4, kappa=0.1, sigma=0.1)
    params = calibrate_ou(sig)
    x0 = float(sig.iloc[-1])
    sr5 = abs(ou_ex_ante_sharpe(x0, params, 5))
    sr60 = abs(ou_ex_ante_sharpe(x0, params, 60))
    assert sr5 > sr60  # annualized OU Sharpe declines with horizon
