"""Tests for the cross-currency basis book.

Unlike GSS, this port *has* a numeric reference: the archive's own banked panels. The tie-out test
at the bottom runs the whole signal-and-allocation stack on them and checks the information ratio
against the value recovered from the archive. It skips when the archive is not on this machine.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from BT.xccy_rv.config import SignalConfig, XccyConfig
from BT.xccy_rv.data import XccyPanel, xccy_basis_tag
from BT.xccy_rv.product import (
    XccyBasisLeg,
    XccyBasisQuery,
    XccyBasisStructure,
    XccyBasisValue,
    XccyPanelMDP,
)
from BT.xccy_rv.signals import build_signals, clip_outliers, combine_alpha, realized_vol
from BT.xccy_rv.strategy import no_trade_band_step

RVPF_ROOT = Path(r"C:/Users/chris/clee/jpm_pfin/RVPF")


# ---------------------------------------------------------------- no-trade band
def test_no_trade_band_unconstrained_optimum():
    """With no cost the band collapses to α/(λ·var)."""
    assert no_trade_band_step(0.02, 0.01, 0.0, 2.0, 0.0) == pytest.approx(0.02 / (2.0 * 0.01))


def test_no_trade_band_holds_inside_the_band():
    """At the optimum, a cost band means do nothing."""
    lam, var, cost = 2.0, 0.01, 0.005
    h = 0.02 / (lam * var)
    assert no_trade_band_step(0.02, var, h, lam, cost) == pytest.approx(h)


def test_no_trade_band_moves_only_to_the_band_edge():
    """Outside the band the new holding is shifted by the cost, not to the free optimum."""
    lam, var, cost = 2.0, 0.01, 0.005
    got = no_trade_band_step(0.02, var, 0.0, lam, cost)
    assert got == pytest.approx((0.02 - cost) / (lam * var))
    assert got < 0.02 / (lam * var)


def test_no_trade_band_is_symmetric_in_sign():
    lam, var, cost = 2.0, 0.01, 0.005
    up = no_trade_band_step(0.02, var, 0.0, lam, cost)
    dn = no_trade_band_step(-0.02, var, 0.0, lam, cost)
    assert up == pytest.approx(-dn)


def test_no_trade_band_holds_on_bad_inputs():
    assert no_trade_band_step(np.nan, 0.01, 0.7, 2.0, 0.0) == 0.7
    assert no_trade_band_step(0.02, 0.0, 0.7, 2.0, 0.0) == 0.7


# --------------------------------------------------------------------- signals
def test_outlier_rule_is_one_sided_and_zeroes():
    """The original zeroes returns ABOVE n sds and leaves large negatives alone."""
    s = pd.DataFrame({"A": [0.0, 0.0, 0.0, 1.0, -1.0]})
    out = clip_outliers(s, n_std=1.0)
    assert out["A"].iloc[3] == 0.0     # the large positive is zeroed
    assert out["A"].iloc[4] == -1.0    # the large negative survives


def test_realized_vol_scale_is_sqrt_halflife():
    rng = np.random.default_rng(2)
    r = pd.DataFrame({"A": rng.normal(scale=0.001, size=400)}, index=pd.bdate_range("2024-01-01", periods=400))
    v = realized_vol(r, 63)
    direct = r["A"].ewm(halflife=63, min_periods=63).std().iloc[-1] * np.sqrt(63)
    assert v["A"].iloc[-1] == pytest.approx(direct)


def _toy_panel(n: int = 400) -> XccyPanel:
    idx = pd.bdate_range("2024-01-01", periods=n)
    rng = np.random.default_rng(5)
    fwd = pd.DataFrame({"A": -30 + np.cumsum(rng.normal(scale=0.3, size=n))}, index=idx)
    rolled = fwd - 1.5                     # a steady +1.5bp/yr of carry
    rets = pd.DataFrame({"A": rng.normal(scale=1e-4, size=n)}, index=idx)
    return XccyPanel(fwd_basis=fwd, rolled_basis=rolled, returns=rets)


def test_carry_sign_follows_the_original():
    """carry = -(fwd - rolled). Rolled BELOW forward is negative carry for the long."""
    p = _toy_panel()
    assert p.carry()["A"].iloc[-1] == pytest.approx(-1.5)


def test_scoring_has_no_mean_subtraction():
    """score = raw/ewmstd(raw). A strictly positive raw signal must score strictly positive.

    This is the property that makes it a vol-scaled level rather than a z-score, and it is the
    original's behaviour, so it is pinned rather than corrected.
    """
    p = _toy_panel()
    sig = build_signals(p, SignalConfig())
    raw, score = sig["raw_1"].dropna(), sig["score_1"].dropna()
    common = raw.index.intersection(score.index)
    assert (np.sign(raw.loc[common, "A"]) == np.sign(score.loc[common, "A"])).all()


def test_alpha_is_zero_weighted_signals_only():
    p = _toy_panel()
    cfg = SignalConfig(weights=(1.0, 0.0, 0.0, 0.0, 0.0))
    sig = build_signals(p, cfg)
    a = combine_alpha(sig, cfg)
    pd.testing.assert_frame_equal(a.dropna(), sig["alpha_1"].dropna())


def test_missing_inputs_make_a_signal_nan_not_absent():
    """Signals 3-5 have no inputs in the toy panel; they must be present and NaN."""
    sig = build_signals(_toy_panel(), SignalConfig())
    for i in (3, 4, 5):
        assert f"alpha_{i}" in sig
        assert sig[f"alpha_{i}"].isna().all().all()


def test_all_zero_weights_raises():
    p = _toy_panel()
    cfg = SignalConfig(weights=(0.0, 0.0, 0.0, 0.0, 0.0))
    with pytest.raises(ValueError):
        combine_alpha(build_signals(p, cfg), cfg)


# --------------------------------------------------------------------- product
def test_tag_grammar():
    assert (
        xccy_basis_tag("EUR", "USD", "5Y", "1Y")
        == "RATES.XCCY_OIS_SWAP.EUR.USD.1Y.5Y.SPREAD_LEG.BASIS_SPREAD"
    )


def test_npv_is_basis_move_times_dv01():
    idx = pd.bdate_range("2026-01-05", periods=3)
    mdp = XccyPanelMDP(pd.DataFrame({"X": [-20.0, -15.0, -10.0]}, index=idx))
    pricer = mdp.get_pricer({"timestamp": idx[-1]})
    leg = XccyBasisLeg(instrument="X", dv01=100.0, direction=1.0, entry_basis_bp=-20.0)
    from BT.xccy_rv.product import XccyBasisValueFunctionMap

    vmap = XccyBasisValueFunctionMap(pricer=pricer, package=[leg])
    assert vmap.apply(value=XccyBasisValue.NPV) == pytest.approx(10.0 * 100.0)


def test_npv_direction_flips():
    idx = pd.bdate_range("2026-01-05", periods=2)
    mdp = XccyPanelMDP(pd.DataFrame({"X": [-20.0, -10.0]}, index=idx))
    pricer = mdp.get_pricer({"timestamp": idx[-1]})
    from BT.xccy_rv.product import XccyBasisValueFunctionMap

    long_ = XccyBasisValueFunctionMap(
        pricer=pricer, package=[XccyBasisLeg("X", 100.0, +1.0, -20.0)]
    ).apply(value=XccyBasisValue.NPV)
    short = XccyBasisValueFunctionMap(
        pricer=pricer, package=[XccyBasisLeg("X", 100.0, -1.0, -20.0)]
    ).apply(value=XccyBasisValue.NPV)
    assert long_ == pytest.approx(-short)


def test_carry_accrues_with_time_held():
    """A year of 4bp/yr carry on a $100/bp position is 4*100 = $400."""
    idx = pd.DatetimeIndex(["2026-01-05", "2027-01-05"])
    mdp = XccyPanelMDP(pd.DataFrame({"X": [-20.0, -20.0]}, index=idx))   # basis unchanged
    pricer = mdp.get_pricer({"timestamp": idx[-1]})
    leg = XccyBasisLeg("X", 100.0, 1.0, -20.0, carry_bp_per_year=4.0, entry_ts=idx[0])
    from BT.xccy_rv.product import XccyBasisValueFunctionMap

    got = XccyBasisValueFunctionMap(pricer=pricer, package=[leg]).apply(value=XccyBasisValue.NPV)
    assert got == pytest.approx(4.0 * (365 / 365.0) * 100.0, rel=1e-3)


def test_notional_to_dv01_conversion():
    """$1m of notional is $100 per bp. Reading this as $/bp inflates fees 10,000x."""
    cfg = XccyConfig()
    assert cfg.backtest.dv01_per_unit == pytest.approx(cfg.backtest.notional_per_unit / 1e4)
    assert cfg.backtest.dv01_per_unit == pytest.approx(100.0)


def test_query_registers_its_product():
    from BT.position_handler import get_handler

    q = XccyBasisQuery(instrument="X", structure=XccyBasisStructure.OUTRIGHT)
    assert q.product == "XCCYB"
    assert get_handler(q.product) is not None


# --------------------------------------------------------------------- tie-out
@pytest.mark.skipif(not RVPF_ROOT.exists(), reason="the RVPF archive is not on this machine")
def test_banked_panel_reproduces_the_archive_information_ratio():
    """The whole point of the port: the archive's own numbers, on the archive's own inputs.

    Reference, recovered from the archive by an independent reimplementation:
    gross IR +0.39, net +0.25 over 2007-09-13..2015-10-22 on 20 instruments.
    """
    from BT.xccy_rv.backtest import run_panel_backtest
    from BT.xccy_rv.data import BankedRVPFSource

    cfg = XccyConfig()
    panel = BankedRVPFSource(root=RVPF_ROOT, pairs=cfg.pairs, points=cfg.points).load()
    assert len(panel.instruments) == 20

    res = run_panel_backtest(panel, cfg)
    s = res.summary()
    assert s["ir_gross"] == pytest.approx(0.39, abs=0.05)
    assert s["ir_net"] == pytest.approx(0.25, abs=0.05)

    era = res.by_era()
    # The crisis era carries the book; the post-crisis era does not clear its own costs.
    assert era.loc["2007-2009", "ir_gross"] > 1.0
    assert era.loc["2010-2012", "ir_net"] < 0.2


@pytest.mark.skipif(not RVPF_ROOT.exists(), reason="the RVPF archive is not on this machine")
def test_banked_basis_is_normalised_to_basis_points():
    """The archive banks decimals; the panel must hand out bp or every mark is 10,000x small."""
    from BT.xccy_rv.data import BankedRVPFSource

    cfg = XccyConfig()
    panel = BankedRVPFSource(root=RVPF_ROOT, pairs=cfg.pairs, points=cfg.points).load()
    assert panel.fwd_basis.abs().max().max() > 1.0          # bp, not decimals
    assert panel.carry().abs().median().median() > 0.1      # bp/yr, order 1
