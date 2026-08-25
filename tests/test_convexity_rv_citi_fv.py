"""Citi's Figure-6 fair-value machinery, promoted out of the notebook.

Every test here is built so that the code path under test can actually fail:
the synthetic panels leave a real hole (a fit that must be refused, a future
value that must not be seen, a weight that must not sum to one).  The
mutation harness ``notebooks/backtests/convexity_rv/_p4_mutate_citi.py``
plants the corresponding defects and each must be killed.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from RVUtils.ConvexityRV import citi_fv as FV


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
def _panel(n: int = 600, seed: int = 7) -> pd.DataFrame:
    """A synthetic percent-par-rate panel on a business-day index."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2020-01-01", periods=n)
    r2 = 2.0 + np.cumsum(rng.normal(0, 0.02, n))
    r5 = 2.4 + np.cumsum(rng.normal(0, 0.02, n))
    r10 = 2.8 + np.cumsum(rng.normal(0, 0.02, n))
    return pd.DataFrame({"r2y_pct": r2, "r5y_pct": r5, "r10y_pct": r10},
                        index=idx)


def _exact_y(p: pd.DataFrame, a: float, b: float, w2: float, w10: float
             ) -> pd.Series:
    return a + b * FV.fly_combo(p, w2, w10)


# ---------------------------------------------------------------------------
# 1. the combination and its units
# ---------------------------------------------------------------------------
def test_fly_combo_is_the_declared_algebra():
    p = _panel(40)
    got = FV.fly_combo(p, 0.705, 0.465)
    want = -0.705 * p["r2y_pct"] + p["r5y_pct"] - 0.465 * p["r10y_pct"]
    pd.testing.assert_series_equal(got, want.rename("fly_pct"))


def test_fly_combo_at_equal_wings_is_half_the_house_fly_rate_convention():
    """``2 * fly_combo(0.5, 0.5) * 100`` IS ``gv_universe``'s ``FLY RATE``.

    The two modules quote the same object at a factor of two apart, which is
    exactly the silent-halving hazard ``gv_engine`` documents; pinning the tie
    here means neither can drift alone.
    """
    p = _panel(40)
    combo_bp = 2.0 * FV.fly_combo(p, 0.5, 0.5) * 100.0
    house = (2.0 * p["r5y_pct"] - p["r2y_pct"] - p["r10y_pct"]) * 100.0
    assert float((combo_bp - house).abs().max()) < 1e-9


def test_beta_units_are_bp_of_ca_per_bp_of_fly():
    f = FV.FairValueFit(FV.CITI_FEB2017_A, FV.CITI_FEB2017_B,
                        FV.CITI_FEB2017_W2, FV.CITI_FEB2017_W10, 0.9, 500)
    assert f.beta_bp_per_bp == pytest.approx(0.206)
    assert FV.hedge_beta_bp_per_bp(f) == pytest.approx(0.206)


def test_citis_published_weights_are_not_a_butterfly():
    """A 3-rate regression does not constrain the weights to sum to one."""
    f = FV.FairValueFit(FV.CITI_FEB2017_A, FV.CITI_FEB2017_B,
                        FV.CITI_FEB2017_W2, FV.CITI_FEB2017_W10, 0.9, 500)
    assert f.net_weight == pytest.approx(-0.17, abs=1e-9)
    assert abs(f.net_weight) > 0.05


# ---------------------------------------------------------------------------
# 2. the three fits recover what they are given
# ---------------------------------------------------------------------------
def test_free_fit_recovers_weights_that_do_not_sum_to_one():
    """The hole: a fit that silently imposed the fly constraint would fail."""
    p = _panel()
    y = _exact_y(p, 9.7, 20.6, 0.705, 0.465)
    f = FV.fit_fair_value(y, p, "free")
    assert f is not None
    assert f.a == pytest.approx(9.7, abs=1e-6)
    assert f.b == pytest.approx(20.6, abs=1e-6)
    assert f.w2 == pytest.approx(0.705, abs=1e-6)
    assert f.w10 == pytest.approx(0.465, abs=1e-6)
    assert f.r2 == pytest.approx(1.0, abs=1e-9)
    assert abs(f.w2 + f.w10 - 1.0) > 0.1


def test_fly_fit_is_constrained_to_a_real_butterfly():
    p = _panel()
    y = _exact_y(p, 5.0, 12.0, 0.30, 0.70)
    f = FV.fit_fair_value(y, p, "fly")
    assert f is not None
    assert f.w2 + f.w10 == pytest.approx(1.0, abs=1e-12)
    assert f.net_weight == pytest.approx(0.0, abs=1e-12)
    assert f.w2 == pytest.approx(0.30, abs=0.011)
    assert f.r2 > 0.999


def test_fly_fit_stays_constrained_even_when_the_truth_is_not_a_butterfly():
    """The hole: truth has w2 + w10 = 1.17, the constrained fit must not chase it."""
    p = _panel()
    y = _exact_y(p, 9.7, 20.6, 0.705, 0.465)
    f = FV.fit_fair_value(y, p, "fly")
    assert f is not None
    assert f.w2 + f.w10 == pytest.approx(1.0, abs=1e-12)
    assert f.r2 < 1.0


def test_citi_fit_holds_the_published_weights_and_refits_level_and_scale():
    p = _panel()
    y = _exact_y(p, 3.0, 7.0, 0.705, 0.465) + 0.0
    f = FV.fit_fair_value(y, p, "citi")
    assert f is not None
    assert (f.w2, f.w10) == (FV.CITI_FEB2017_W2, FV.CITI_FEB2017_W10)
    assert f.a == pytest.approx(3.0, abs=1e-6)
    assert f.b == pytest.approx(7.0, abs=1e-6)


def test_citi_fit_honours_an_overridden_weight_pair():
    p = _panel()
    f = FV.fit_fair_value(p["r5y_pct"] * 10.0, p, "citi",
                          fixed_w2=FV.CITI_JAN2017_W2,
                          fixed_w10=FV.CITI_JAN2017_W10)
    assert (f.w2, f.w10) == (FV.CITI_JAN2017_W2, FV.CITI_JAN2017_W10)


def test_fitted_series_is_the_fit_evaluated_on_the_panel():
    p = _panel(80)
    f = FV.FairValueFit(1.5, -3.25, 0.4, 0.6, 0.5, 80)
    got = FV.fitted_series(p, f)
    want = 1.5 - 3.25 * FV.fly_combo(p, 0.4, 0.6)
    assert float((got - want).abs().max()) < 1e-12


# ---------------------------------------------------------------------------
# 3. refusals
# ---------------------------------------------------------------------------
def test_a_window_shorter_than_min_obs_returns_none_for_every_kind():
    p = _panel(40)
    y = _exact_y(p, 1.0, 1.0, 0.5, 0.5)
    for kind in FV.FIT_KINDS:
        assert FV.fit_fair_value(y, p, kind) is None


def test_nans_in_the_regressors_reduce_the_usable_window():
    p = _panel(70)
    p.loc[p.index[:20], "r5y_pct"] = np.nan
    y = _exact_y(p.fillna(2.0), 1.0, 1.0, 0.5, 0.5)
    assert FV.fit_fair_value(y, p, "fly", min_obs=60) is None
    f = FV.fit_fair_value(y, p, "fly", min_obs=50)
    assert f is not None and f.n == 50


def test_unknown_kind_and_missing_columns_raise():
    p = _panel(80)
    with pytest.raises(ValueError):
        FV.fit_fair_value(p["r5y_pct"], p, "quadratic")
    with pytest.raises(KeyError):
        FV.fit_fair_value(p["r5y_pct"], p, "fly", cols=("a", "b", "c"))


def test_a_degenerate_belly_coefficient_refuses_rather_than_dividing_by_zero():
    """``free`` renormalises by ``b5``; a y that does not load on r5 at all
    must return None rather than an exploded weight."""
    p = _panel()
    y = pd.Series(3.0, index=p.index)          # constant: every slope is zero
    assert FV.fit_fair_value(y, p, "free") is None


# ---------------------------------------------------------------------------
# 4. the quarterly refit, and its causality
# ---------------------------------------------------------------------------
def _rolls(p: pd.DataFrame, step: int = 63):
    return list(p.index[step::step])


def test_refit_parameters_come_into_force_only_after_their_own_window_ends():
    p = _panel(600)
    y = _exact_y(p, 9.7, 20.6, 0.705, 0.465)
    frame, fitted = FV.imm_refit(y, p, "fly", 252, roll_dates=_rolls(p))
    assert len(frame) > 3
    for asof, row in frame.iterrows():
        assert row["fit_end"] <= asof
        assert row["fit_end"] < row["in_force_from"]
        assert row["in_force_from"] <= row["in_force_to"]
    # nothing is fitted before the first set of parameters exists
    first = frame["in_force_from"].min()
    assert fitted.loc[:first].iloc[:-1].isna().all()
    assert fitted.loc[first:].notna().all()


def test_the_fitted_path_cannot_see_the_future():
    """Move the panel LATE and check two things separately.

    (a) every PARAMETER set already in force at the cut is byte-identical --
    that is the look-ahead test proper, and it fails if the window becomes
    ``panel.iloc[:pos + 1]`` or the tail is taken from the wrong end;
    (b) every fitted VALUE strictly before the cut is byte-identical.  On the
    cut date itself the fitted value legitimately moves, because the regressor
    moved there -- the parameters did not.
    """
    p = _panel(600)
    y = _exact_y(p, 9.7, 20.6, 0.705, 0.465)
    rolls = _rolls(p)
    fbase, base = FV.imm_refit(y, p, "fly", 252, roll_dates=rolls)

    cut = p.index[520]
    p2 = p.copy()
    p2.loc[p2.index >= cut, "r5y_pct"] += 3.0
    y2 = y.copy()
    y2.loc[y2.index >= cut] += 50.0
    fmoved, moved = FV.imm_refit(y2, p2, "fly", 252, roll_dates=rolls)

    cols = ["in_force_from", "a", "b", "w2", "w10", "n"]
    a_par = fbase[fbase["in_force_from"] <= cut][cols].reset_index(drop=True)
    b_par = fmoved[fmoved["in_force_from"] <= cut][cols].reset_index(drop=True)
    assert len(a_par) >= 4, "the fixture must put several fits in force"
    pd.testing.assert_frame_equal(a_par, b_par)

    before = p.index[p.index < cut]
    a = base.loc[before].dropna()
    b = moved.loc[before].dropna()
    assert len(a) > 100
    assert a.index.equals(b.index)
    assert float((a - b).abs().max()) < 1e-12


def test_each_refit_is_in_force_until_the_next_roll_and_no_longer():
    p = _panel(600)
    y = _exact_y(p, 2.0, 5.0, 0.5, 0.5)
    rolls = _rolls(p)
    frame, fitted = FV.imm_refit(y, p, "citi", 252, roll_dates=rolls)
    ifs = list(frame["in_force_from"])
    for i, r in enumerate(ifs[:-1]):
        nxt = ifs[i + 1]
        seg = p.loc[(p.index >= r) & (p.index < nxt)]
        row = frame[frame["in_force_from"] == r].iloc[0]
        want = row["a"] + row["b"] * FV.fly_combo(seg, row["w2"], row["w10"])
        assert float((fitted.loc[seg.index] - want).abs().max()) < 1e-10


def test_the_estimation_window_is_capped_at_window_bd():
    p = _panel(600)
    y = _exact_y(p, 2.0, 5.0, 0.5, 0.5)
    frame, _ = FV.imm_refit(y, p, "citi", 100, roll_dates=_rolls(p))
    assert frame["n"].max() <= 100
    assert (frame["fit_end"] - frame["fit_start"]).dt.days.max() < 200


def test_early_refits_use_what_history_there_is_and_say_so():
    p = _panel(600)
    y = _exact_y(p, 2.0, 5.0, 0.5, 0.5)
    frame, _ = FV.imm_refit(y, p, "citi", 504, roll_dates=_rolls(p))
    n = frame["n"].astype(int).to_numpy()
    assert n[0] < 504 and n.max() <= 504
    assert (np.diff(n) >= 0).all(), "the window must grow monotonically"


def test_no_roll_dates_means_no_fit_and_an_all_nan_path():
    p = _panel(600)
    y = _exact_y(p, 2.0, 5.0, 0.5, 0.5)
    frame, fitted = FV.imm_refit(y, p, "fly", 252, roll_dates=[])
    assert frame.empty
    assert fitted.isna().all()


def test_rolls_inside_the_burn_in_are_skipped_not_fitted_on_nothing():
    p = _panel(600)
    y = _exact_y(p, 2.0, 5.0, 0.5, 0.5)
    rolls = [p.index[10]] + _rolls(p)
    frame, _ = FV.imm_refit(y, p, "fly", 252, roll_dates=rolls,
                            min_obs=FV.MIN_FIT_OBS)
    assert p.index[10] not in set(frame["in_force_from"])


def test_refit_default_roll_clock_is_the_ca_rank_map():
    """With no explicit dates the module must use the CA roll clock, not a
    calendar quarter -- the two differ and the CA switches contracts on the
    former."""
    from RVUtils.ConvexityRV.gv_universe import ca_roll_dates

    idx = pd.bdate_range("2022-01-03", "2024-12-31")
    p = pd.DataFrame({"r2y_pct": np.linspace(2, 3, len(idx)),
                      "r5y_pct": np.linspace(2.4, 3.1, len(idx)),
                      "r10y_pct": np.linspace(2.8, 3.4, len(idx))}, index=idx)
    y = _exact_y(p, 1.0, 2.0, 0.5, 0.5)
    frame, _ = FV.imm_refit(y, p, "citi", 252)
    want = [d for d in ca_roll_dates(idx)]
    got = list(frame["in_force_from"])
    assert got, "no refits at all"
    assert set(got).issubset(set(want))
    assert len(got) >= len(want) - 2          # only the burn-in rolls are lost


# ---------------------------------------------------------------------------
# 5. the summary that decides hedgeability
# ---------------------------------------------------------------------------
def test_refit_summary_counts_sign_flips_of_the_scale():
    f = pd.DataFrame({"w2": [0.1, 0.2, 0.9, 0.9],
                      "b": [19.1, 5.0, -7.6, -8.0]})
    s = FV.refit_summary(f)
    assert s["n_refits"] == 4
    assert s["b_sign_flips"] == 1
    assert s["w2_range"] == pytest.approx(0.8)
    assert s["n_boundary_w2"] == 0


def test_refit_summary_counts_boundary_weights():
    f = pd.DataFrame({"w2": [0.05, 0.5, 0.95], "b": [1.0, 1.0, 1.0]})
    assert FV.refit_summary(f)["n_boundary_w2"] == 2


def test_refit_summary_of_an_empty_frame_is_not_an_exception():
    s = FV.refit_summary(pd.DataFrame())
    assert s["n_refits"] == 0 and s["b_sign_flips"] == 0


# ---------------------------------------------------------------------------
# 6. the note's own printed arithmetic -- known answers
# ---------------------------------------------------------------------------
def test_annuity_is_the_flat_curve_annual_factor():
    assert FV.annuity(2.0, 1) == pytest.approx(1.0 / 1.02)
    assert FV.annuity(2.0, 5) == pytest.approx(
        sum(1.02 ** -k for k in range(1, 6)))
    assert FV.annuity(0.0, 7) == pytest.approx(7.0)


def test_printed_notionals_reproduce_the_printed_dv01_weights():
    """"notional weights of $147mm/-$85.6mm/$20.89mm (0.705/-1/0.465 DV01
    weights)" -- at the flat ~2% curve 2017 sat on."""
    a2, a5, a10 = (FV.annuity(2.0, y) for y in (2, 5, 10))
    w2 = (147.0 * a2) / (85.6 * a5)
    w10 = (20.89 * a10) / (85.6 * a5)
    assert w2 == pytest.approx(FV.CITI_FEB2017_W2, rel=0.02)
    assert w10 == pytest.approx(FV.CITI_FEB2017_W10, rel=0.02)


def test_the_regression_beta_is_the_printed_belly_dv01():
    """beta * CA_DV01 must be the DV01 the printed 5y notional carries."""
    fit = FV.FairValueFit(FV.CITI_FEB2017_A, FV.CITI_FEB2017_B,
                          FV.CITI_FEB2017_W2, FV.CITI_FEB2017_W10, 0.9, 500)
    from_beta = fit.beta_bp_per_bp * 200_000.0
    from_notional = 85.6 * FV.annuity(2.0, 5) * 100.0
    assert from_beta == pytest.approx(from_notional, rel=0.06)


def test_the_two_printed_roll_numbers_reproduce_the_printed_carry():
    """"+1.3bp" short-CA roll and "+3.2bp" short-fly carry over 3m must give
    the printed "$380k over the next three months"."""
    fit = FV.FairValueFit(FV.CITI_FEB2017_A, FV.CITI_FEB2017_B,
                          FV.CITI_FEB2017_W2, FV.CITI_FEB2017_W10, 0.9, 500)
    belly = fit.beta_bp_per_bp * 200_000.0
    carry = 1.3 * 200_000.0 + 3.2 * belly
    assert carry == pytest.approx(380_000.0, rel=0.08)


def test_the_printed_entry_richness_falls_out_of_the_printed_fit():
    """CA 8.8bp against a fly of -18.2bp must be "about 3bp" rich."""
    fitted = FV.CITI_FEB2017_A + FV.CITI_FEB2017_B * (-18.2 / 100.0)
    assert 8.8 - fitted == pytest.approx(3.0, abs=0.25)


def test_the_published_trades_pnl_falls_out_of_the_panel_identity():
    """Entered 8.8bp CA / -18.2bp fly, closed 6.6 / -16.5 on $200k DV01.

    ``side*(dCA - beta*dfly)*CA_DV01`` must reproduce the note's own recorded
    +$500k / +$552k.  This is the identity the whole backtest books P&L on, so
    it is pinned against the only trade whose answer is published.
    """
    beta = FV.CITI_FEB2017_B / 100.0
    d_ca, d_fly = 6.6 - 8.8, -16.5 - (-18.2)
    pnl = -1 * (d_ca - beta * d_fly) * 200_000.0
    assert 4.7e5 < pnl < 5.6e5


def test_dv01_weights_to_notionals_reproduces_the_printed_ticket():
    n2, n5, n10 = FV.dv01_weights_to_notionals(
        FV.CITI_FEB2017_W2, FV.CITI_FEB2017_W10,
        belly_dv01=(FV.CITI_FEB2017_B / 100.0) * 200_000.0,
        rates_pct=(2.0, 2.0, 2.0))
    assert n5 == pytest.approx(-85.6, rel=0.07)   # PAY the belly -> negative mm
    assert n2 == pytest.approx(147.0, rel=0.08)
    assert n10 == pytest.approx(20.89, rel=0.09)
    assert math.copysign(1, n2) == math.copysign(1, n10) != math.copysign(1, n5)
