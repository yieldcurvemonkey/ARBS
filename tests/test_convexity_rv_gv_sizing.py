"""GV block — the mark-noise model and the six declared sizing rules.

Every number this block reports about "was it sizing" comes out of these
primitives, so each one is pinned against a case whose answer is known before
the code runs: a synthetic random-walk-plus-noise series with planted
variances, a planted opposite-sign level/change relation, and a leg whose
relation to vol is pure noise (which must be refused, not divided by).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from RVUtils.ConvexityRV import gv_sizing as S


def _rw_plus_noise(n: int, sigma_true: float, sigma_noise: float, seed: int = 7):
    rng = np.random.default_rng(seed)
    true = np.cumsum(rng.normal(0.0, sigma_true, n))
    obs = true + rng.normal(0.0, sigma_noise, n)
    idx = pd.bdate_range("2015-01-01", periods=n)
    return pd.Series(obs, index=idx), pd.Series(true, index=idx)


# ---------------------------------------------------------------------------
# 1. The noise model
# ---------------------------------------------------------------------------
def test_noise_fit_recovers_planted_variances():
    obs, _ = _rw_plus_noise(20_000, sigma_true=0.5, sigma_noise=0.7)
    f = S.noise_fit(obs)
    assert f.sigma_true == pytest.approx(0.5, rel=0.06)
    assert f.sigma_noise == pytest.approx(0.7, rel=0.06)
    assert f.noise_ratio == pytest.approx(1.4, rel=0.10)
    assert not f.pure_noise


def test_pure_noise_hits_the_minus_half_bound():
    rng = np.random.default_rng(3)
    idx = pd.bdate_range("2015-01-01", periods=20_000)
    s = pd.Series(rng.normal(0.0, 1.0, len(idx)), index=idx)   # no random walk
    f = S.noise_fit(s)
    assert f.ac1 == pytest.approx(-0.5, abs=0.02)
    # the inversion cannot say "zero signal" from a finite sample, but it must
    # say "almost all noise": WHITES/REDS land here on the real panel.
    assert f.noise_ratio > 5.0
    assert f.snr < 0.05


def test_past_the_bound_is_flagged_pure_noise():
    """A series whose daily change autocorrelates BELOW -0.5 has no random-walk
    component the model can attribute variance to, and must be flagged rather
    than silently clipped to a tiny positive tau."""
    idx = pd.bdate_range("2015-01-01", periods=2_000)
    s = pd.Series(np.where(np.arange(len(idx)) % 2 == 0, 1.0, -1.0), index=idx)
    f = S.noise_fit(s)
    assert f.ac1 < -0.5
    assert f.pure_noise
    assert f.sigma_true == 0.0
    assert f.noise_ratio == float("inf")


def test_a_clean_random_walk_has_no_noise_and_no_smoothing():
    obs, _ = _rw_plus_noise(20_000, sigma_true=1.0, sigma_noise=0.0)
    f = S.noise_fit(obs)
    assert abs(f.ac1) < 0.03
    assert S.kalman_ewma_alpha(f.snr) > 0.9


def test_kalman_gain_limits():
    assert S.kalman_ewma_alpha(float("inf")) == pytest.approx(1.0)
    assert S.kalman_ewma_alpha(1e6) > 0.999
    assert S.kalman_ewma_alpha(1e-6) < 0.002
    # monotone in signal-to-noise
    qs = [0.1, 0.5, 1.0, 5.0, 50.0]
    ks = [S.kalman_ewma_alpha(q) for q in qs]
    assert ks == sorted(ks)


def test_the_kalman_ewma_beats_a_naive_alternative_on_the_planted_series():
    """The whole reason for deriving the half-life rather than guessing it."""
    obs, true = _rw_plus_noise(6_000, sigma_true=0.4, sigma_noise=0.9)
    f = S.noise_fit(obs)
    hl = math.log(0.5) / math.log(1.0 - S.kalman_ewma_alpha(f.snr))
    fitted = S.denoise(obs, hl)
    raw_err = float(((obs - true) ** 2).mean())
    fit_err = float(((fitted - true) ** 2).mean())
    assert fit_err < raw_err
    # and a badly-chosen half-life is worse than the derived one
    for bad in (0.05, 40.0):
        assert float(((S.denoise(obs, bad) - true) ** 2).mean()) > fit_err


def test_denoise_is_causal():
    obs, _ = _rw_plus_noise(400, 0.5, 0.5)
    full = S.denoise(obs, 3.0)
    trunc = S.denoise(obs.iloc[:200], 3.0)
    assert np.allclose(full.iloc[:200].to_numpy(), trunc.to_numpy())


def test_fit_denoise_halflives_reports_burn_in_and_full_side_by_side():
    obs, _ = _rw_plus_noise(1_000, 0.4, 0.6)
    df = S.fit_denoise_halflives(pd.DataFrame({"x": obs}), ["x"], burn_in=252)
    r = df.loc["x"]
    assert r["n_burn"] <= 252
    assert np.isfinite(r["halflife_bd"]) and r["halflife_bd"] > 0
    assert {"ac1_burn", "ac1_full", "noise_ratio_burn",
            "noise_ratio_full"} <= set(df.columns)


# ---------------------------------------------------------------------------
# 2. The CA as a price of variance
# ---------------------------------------------------------------------------
def test_variance_price_is_defined_for_a_negative_adjustment():
    v = S.ca_implied_variance_bp2(pd.Series([-1.5, 0.0, 9.183]),
                                  pd.Series([12.0, 12.0, 12.363]))
    assert np.isfinite(v).all()
    assert v.iloc[0] < 0 and v.iloc[2] > 0
    # and the vol inversion refuses exactly where the variance is non-positive
    s = S.ca_implied_vol_bp(pd.Series([-1.5, 0.0, 9.183]),
                            pd.Series([12.0, 12.0, 12.363]))
    assert np.isnan(s.iloc[0]) and np.isnan(s.iloc[1]) and np.isfinite(s.iloc[2])


def test_variance_and_vol_round_trip_against_the_holee_kernel():
    """Known answer against the module the whole package already ties to Citi
    with: sigma -> CA -> sigma must be the identity."""
    from RVUtils.ConvexityRV.holee import pack_ca_bp, pack_time_weight
    t1s = [3.25, 3.50, 3.75, 4.00]
    w = pack_time_weight(t1s)
    ca = pack_ca_bp(118.0, t1s)
    back = S.ca_implied_vol_bp(pd.Series([ca]), pd.Series([w])).iloc[0]
    assert back == pytest.approx(118.0, rel=1e-9)


def test_ca_vega_is_the_derivative_of_the_quadratic():
    """``dCA/dsigma = sigma*w/1e4`` must equal a finite difference of
    ``pack_ca_bp``, and equal ``2*CA/sigma`` at the CA's own implied vol."""
    from RVUtils.ConvexityRV.holee import pack_ca_bp, pack_time_weight
    t1s = [3.25, 3.50, 3.75, 4.00]
    w = pack_time_weight(t1s)
    sig = 118.0
    analytic = S.ca_vega_bp_per_bp(pd.Series([sig]), pd.Series([w])).iloc[0]
    h = 1e-4
    fd = (pack_ca_bp(sig + h, t1s) - pack_ca_bp(sig - h, t1s)) / (2 * h)
    assert analytic == pytest.approx(fd, rel=1e-6)
    ca = pack_ca_bp(sig, t1s)
    assert analytic == pytest.approx(2.0 * ca / sig, rel=1e-9)


def test_ca_vega_grows_with_pack_depth():
    from RVUtils.ConvexityRV.holee import pack_time_weight
    ws = [pack_time_weight([a + 0.25 * i for i in range(4)])
          for a in (0.75, 2.75, 4.75)]
    vs = [S.ca_vega_bp_per_bp(pd.Series([115.0]), pd.Series([w])).iloc[0]
          for w in ws]
    assert vs == sorted(vs)


# ---------------------------------------------------------------------------
# 3. The sizing rules
# ---------------------------------------------------------------------------
def _inputs(ca, leg, nvol=None, w=None) -> S.SizingInputs:
    idx = ca.index
    if nvol is None:
        nvol = pd.Series(100.0, index=idx)
    if w is None:
        w = pd.Series(12.363, index=idx)
    return S.SizingInputs(ca=ca, ca_denoised=ca, leg=leg, nvol=nvol, w=w)


def test_level_and_change_betas_can_disagree_in_sign_and_the_rules_show_it():
    """The M1 defect, planted: a common upward trend gives a POSITIVE level
    beta while the day-to-day co-movement is NEGATIVE.  Block 3 sized its
    hedge with the first and traded the second."""
    n = 1500
    idx = pd.bdate_range("2015-01-01", periods=n)
    rng = np.random.default_rng(11)
    trend = np.linspace(0.0, 30.0, n)
    shock = rng.normal(0.0, 1.0, n).cumsum()
    ca = pd.Series(trend + 0.6 * shock, index=idx)
    leg = pd.Series(2.0 * trend - 0.6 * shock, index=idx)
    b_lvl, _, _ = S.rolling_beta_levels(ca, leg, window=n, min_periods=200)
    b_chg, _, _ = S.rolling_beta_changes(ca, leg, window=n, min_periods=200)
    assert b_lvl.iloc[-1] > 0
    assert b_chg.iloc[-1] < 0
    # and hedging the changes with the LEVEL beta adds variance
    d = ca.diff().dropna()
    dl = leg.diff().reindex(d.index)
    v_unhedged = float(d.var(ddof=1))
    v_lvl = float((d - b_lvl.iloc[-1] * dl).var(ddof=1))
    v_chg = float((d - b_chg.iloc[-1] * dl).var(ddof=1))
    assert v_lvl > v_unhedged > v_chg


def test_vega_match_gate_refuses_a_noise_sized_vol_relation():
    n = 800
    idx = pd.bdate_range("2015-01-01", periods=n)
    rng = np.random.default_rng(5)
    ca = pd.Series(rng.normal(0, 1, n).cumsum() + 9.0, index=idx)
    leg = pd.Series(rng.normal(0, 5, n).cumsum(), index=idx)
    nvol = pd.Series(rng.normal(0, 2, n).cumsum() + 100.0, index=idx)
    b, ok = S.sizing_beta("vega_match", _inputs(ca, leg, nvol))
    # an unrelated leg/vol pair must fail the gate on the large majority of days
    assert float(ok.mean()) < 0.5
    assert not np.isfinite(b[~ok]).any()


def test_vega_match_recovers_a_planted_vol_beta():
    """If the leg IS a vol proxy with slope ``g`` bp per bp/yr, the vega-matched
    beta must be ``(sigma*w/1e4) / g``."""
    n = 900
    idx = pd.bdate_range("2015-01-01", periods=n)
    rng = np.random.default_rng(2)
    nvol = pd.Series(100.0 + rng.normal(0, 1.5, n).cumsum(), index=idx)
    g = 0.35
    leg = (g * nvol + rng.normal(0, 0.05, n)).rename("leg")
    ca = pd.Series(9.0 + rng.normal(0, 0.3, n), index=idx)
    w = pd.Series(12.363, index=idx)
    b, ok = S.sizing_beta("vega_match", _inputs(ca, leg, nvol, w))
    expect = (nvol * 12.363 / 1e4) / g
    j = pd.concat([b.rename("got"), expect.rename("want")], axis=1).dropna()
    assert len(j) > 300
    # the gate is False through the rolling window's warm-up by construction;
    # once the fit exists it must pass essentially every day.
    warm = b.notna()
    assert float(ok[warm].mean()) > 0.95
    assert np.allclose(j["got"], j["want"], rtol=0.05)


def test_vol_ratio_is_risk_parity_and_takes_its_sign_from_the_changes():
    n = 900
    idx = pd.bdate_range("2015-01-01", periods=n)
    rng = np.random.default_rng(9)
    dl = rng.normal(0, 2.0, n)
    dc = -0.4 * dl + rng.normal(0, 0.2, n)
    leg = pd.Series(dl.cumsum(), index=idx)
    ca = pd.Series(dc.cumsum(), index=idx)
    b = S.rolling_vol_ratio(ca, leg, window=500, min_periods=200)
    assert b.dropna().iloc[-1] < 0
    assert abs(b.dropna().iloc[-1]) == pytest.approx(
        float(pd.Series(dc).std(ddof=1) / pd.Series(dl).std(ddof=1)), rel=0.15)


def test_none_and_unit_rules_are_the_declared_brackets():
    idx = pd.bdate_range("2015-01-01", periods=50)
    ca = pd.Series(np.arange(50.0), index=idx)
    leg = pd.Series(np.arange(50.0) * 2, index=idx)
    b0, ok0 = S.sizing_beta("none", _inputs(ca, leg))
    b1, ok1 = S.sizing_beta("unit", _inputs(ca, leg))
    assert (b0 == 0.0).all() and ok0.all()
    assert (b1 == 1.0).all() and ok1.all()


def test_every_declared_rule_is_reachable_and_unknown_ones_refuse():
    idx = pd.bdate_range("2015-01-01", periods=400)
    rng = np.random.default_rng(1)
    ca = pd.Series(rng.normal(0, 1, 400).cumsum(), index=idx)
    leg = pd.Series(rng.normal(0, 1, 400).cumsum(), index=idx)
    for r in S.SIZING_RULES:
        b, ok = S.sizing_beta(r, _inputs(ca, leg))
        assert len(b) == len(idx) and len(ok) == len(idx)
    with pytest.raises(ValueError, match="unknown sizing rule"):
        S.sizing_beta("magic", _inputs(ca, leg))
