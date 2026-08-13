"""Backtest-integrity tests for the basis-vs-vol V2 strategy.

These are the tests that would have caught the defects actually found while building this:
a P&L booked across an 80-day data hole, a contract roll booked as a return, and an edge that
existed only where the vol surface was extrapolated rather than quoted.

They run against the local parquet mirror and skip if it is absent.
"""

from __future__ import annotations

import pathlib
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from RVUtils.BasisVsVol import strategy as ST
from RVUtils.BasisVsVol import surfaces as S
from RVUtils.BasisVsVol import voldata as V

DATA = V.DEFAULT_DATA_DIR
pytestmark = pytest.mark.skipif(
    not (DATA / "arbs_ustf_vol_snapshots_v2.parquet").exists(),
    reason="local vol-snapshot parquet mirror not present",
)


@pytest.fixture(scope="module")
def vd():
    return V.load(products=list(ST.DEFAULT_UNIVERSE))


@pytest.fixture(scope="module")
def book(vd):
    return S.SurfaceBook(vd)


# --------------------------------------------------------------------------- data integrity
def test_bp_vol_identity_holds(vd):
    """atm_nvol_bps == atm_nvol_price / fv01 pins the unit convention of the whole panel."""
    err = (vd.ustf["atm_nvol_price"] / vd.ustf["fv01"] - vd.ustf["atm_nvol_bps"]).abs().max()
    assert err < 1e-9


def test_sanitizer_rejects_the_corrupt_ultra_bond_rows():
    """A block of UL rows stores forward_price 11.28 for 111.28 -- a dropped leading digit."""
    raw = V.load(sanitize=False)
    clean, dropped = V.sanitize_ustf(raw.ustf)
    assert len(dropped) > 0
    assert set(dropped["product"]) == {"UL"}
    assert dropped["forward_yield"].max() > 20.0  # the tell: a 50% "yield"
    assert clean["forward_yield"].between(0, 20).all()


def test_ul_is_excluded_from_the_default_universe():
    """Not a performance judgement: UL's forward yield moves 20bp in 3.3 years."""
    assert "UL" not in ST.DEFAULT_UNIVERSE


def test_term_structure_interpolation_is_linear_in_total_variance(vd):
    ttes = np.array([0.0822, 0.1644, 0.2466])
    vols = np.array([100.0, 110.0, 120.0])
    mid = V.vol_term_structure_interp(ttes, vols, 0.1233)  # halfway 1M->2M
    w = np.interp(0.1233, ttes, vols**2 * ttes)
    assert mid == pytest.approx(np.sqrt(w / 0.1233), rel=1e-12)
    # flat outside the quoted range, both ends
    assert V.vol_term_structure_interp(ttes, vols, 0.01) == pytest.approx(100.0)
    assert V.vol_term_structure_interp(ttes, vols, 5.0) == pytest.approx(120.0)


def test_smile_reconstruction_is_atm_at_zero_offset(vd, book):
    """The rebuilt futures smile must return the stored ATM at zero offset."""
    surf = book.ustf("US")
    d = sorted(surf)[300]
    row = vd.ustf[(vd.ustf["product"] == "US") & (vd.ustf["as_of_date"] == d)
                  & (vd.ustf["expiry_label"] == "3M")].iloc[0]
    assert surf[d].vol(float(row["time_to_expiry"]), 0.0) == pytest.approx(
        float(row["atm_nvol_bps"]), rel=1e-6)


def test_smile_has_real_curvature(vd, book):
    """Guard against the strike axis silently collapsing to ATM, as the stored buckets did."""
    surf = book.ustf("US")
    d = sorted(surf)[300]
    t = 0.2466
    atm = surf[d].vol(t, 0.0)
    assert surf[d].vol(t, 100.0) - atm > 2.0
    assert surf[d].vol(t, -100.0) - atm > 2.0


def test_stored_strike_offset_buckets_are_corrupt_on_the_futures_leg(vd):
    """Pins the defect so nobody re-adopts that axis: the '100bp' bucket is ~ATM."""
    import json

    row = vd.ustf[vd.ustf["product"] == "US"].iloc[500]
    so = json.loads(row["strike_offset_otm_vols"])
    far = so["put"]["100"]
    assert abs(far["strike_futures_ytm_offset_bps"]) < 5.0, "expected the broken ~1bp offset"
    assert abs(far["vol_bps"] - row["atm_nvol_bps"]) < 0.5


# --------------------------------------------------------------------------- backtest guards
def test_gap_guard_prevents_holding_through_the_80_day_hole(vd, book):
    cfg = ST.StrategyConfig(product="US", expiry_label="3M", entry_z=1.5, max_hold_days=21)
    res = ST.run_strategy(vd, cfg, book)
    assert not res.trades.empty
    assert res.trades["held_days"].max() <= cfg.max_hold_days
    loose = ST.run_strategy(vd, replace(cfg, max_gap_days=999), book)
    assert loose.trades["held_days"].max() > cfg.max_hold_days, (
        "with the guard off a position should span a data hole -- if not, the test is inert")


def test_support_gate_removes_the_extrapolated_edge(vd, book):
    """The 1M cell's apparent edge lives entirely below the shortest quoted node."""
    base = ST.StrategyConfig(product="US", expiry_label="1M", entry_z=2.0, max_hold_days=21)
    off = ST.run_strategy(vd, replace(base, require_on_support=False), book)
    on = ST.run_strategy(vd, replace(base, require_on_support=True), book)
    assert off.daily["pnl_volbp"].sum() > on.daily["pnl_volbp"].sum()
    assert on.diagnostics["n_trades"] < off.diagnostics["n_trades"]


def test_a_contract_roll_is_never_booked_as_pnl(vd, book):
    cfg = ST.StrategyConfig(product="US", expiry_label="3M", entry_z=1.0,
                            ustf_cost_vol_bp=0.0, swpt_cost_vol_bp=0.0, hedge_cost_bp=0.0)
    res = ST.run_strategy(vd, cfg, book)
    panel = res.signal
    roll_days = panel.index[panel["is_roll"].astype(bool)]
    booked = res.daily.loc[res.daily.index.isin(roll_days), "gross_pnl"]
    assert (booked.abs() < 1e-9).all(), "a forward gap from a contract change is not a return"


# --------------------------------------------------------------------------- engine agreement
@pytest.mark.parametrize("product,expiry", [("US", "3M"), ("TY", "2M"), ("FV", "3M")])
def test_query_driven_backtest_matches_the_reference_engine(vd, book, product, expiry):
    """Two independent implementations, identical P&L.

    The QueryDrivenBacktest path goes through the framework's MDP, query, adapter, handler and
    trigger machinery; the reference is a standalone vectorised loop. They share only the
    Bachelier primitives and the surfaces. Costs are zeroed because the framework has no
    entry-side fee hook, so the two cost conventions differ by construction -- the pricing is what
    is being compared.
    """
    from BT.signals.basis_vs_vol import qdb_equity_series, run_bvv_qdb_backtest

    cfg = ST.StrategyConfig(product=product, expiry_label=expiry, entry_z=2.0, max_hold_days=21,
                            ustf_cost_vol_bp=0.0, swpt_cost_vol_bp=0.0, hedge_cost_bp=0.0)
    bt, ref = run_bvv_qdb_backtest(vd, cfg, book)
    qdb = float(qdb_equity_series(bt).iloc[-1])
    reference = float(ref.daily["gross_pnl"].sum())
    assert qdb == pytest.approx(reference, abs=1e-2)
    assert len(bt.portfolio.closed_positions_log) == len(ref.trades)


# --------------------------------------------------------------------------- lookahead sensitivity
def test_harness_detects_deliberate_lookahead(vd, book):
    """Mutation test on the backtest itself.

    Feeding the signal one day of future knowledge must visibly improve results. If it does not,
    the harness cannot detect lookahead and none of its other verdicts mean anything.
    """
    cfg = ST.StrategyConfig(product="US", expiry_label="3M", entry_z=1.5, exec_lag_days=1,
                            ustf_cost_vol_bp=0.0, swpt_cost_vol_bp=0.0, hedge_cost_bp=0.0)
    honest = ST.run_strategy(vd, cfg, book)
    cheating = ST.run_strategy(vd, replace(cfg, exec_lag_days=-1), book)
    h = honest.daily["pnl_volbp"].sum()
    c = cheating.daily["pnl_volbp"].sum()
    assert c != pytest.approx(h, rel=1e-6), "harness is blind to a one-day signal shift"
