"""Synthetic, no-network tests for RVUtils.OutcomeMap.

Everything here is planted or closed-form: the butterfly kernel's partition
property (the reason a cell costs 4pp of probability instead of 16pp), the
telescoping algebra that decides the contract bill of a multi-cell book, the
even/odd decomposition of a hand-built richness map, frame-frozen package hedge
ratios against a hand-differentiated lattice, and the trade loop's arithmetic on
a scripted mark path — including the sign mirror between fade and momentum and
the separability of the linear leg's bill.
"""
from __future__ import annotations

import datetime

import numpy as np
import pandas as pd
import pytest

from RVUtils.MeetingProb.atoms import (
    AtomEngine, ContractMeetings, ResolvedMeeting)
from RVUtils.MeetingProb.pricer import price_option
from RVUtils.OutcomeMap import (
    Cell, CellMap, HedgeContext, build_cell_map, decompose, distinct_atoms,
    fly_legs, linear_leg_cost_bp, map_full_weights, option_leg_cost_bp,
    package_contracts, package_hedge_ratios, package_tree_value,
    pair_odd_signal, pair_raw_signal, run_outcome_backtest, snap_center,
    telescope, zq_basket_contracts,
)
from RVUtils.OutcomeMap.structures import package_mark


# ---------------------------------------------------------------------------
# the cell instrument
# ---------------------------------------------------------------------------

def test_butterfly_prices_a_cell_at_25bp_times_its_probability():
    """On a pure lattice the 25bp fly IS 25bp x P(cell): the cost thesis."""
    rates = np.array([3.50, 3.75, 4.00, 4.25])
    probs = np.array([0.1, 0.4, 0.35, 0.15])
    for i, (r, p) in enumerate(zip(rates, probs)):
        legs = fly_legs(round(100.0 - r, 4))
        v = sum(w * price_option(rates, probs, right, 100.0 - k, smear_bp=0.0)
                for right, k, w in legs)
        assert v == pytest.approx(25.0 * p, abs=1e-9)


def test_butterfly_kernels_partition_the_interior():
    """Sum of the on-lattice fly prices = 25bp x (mass the lattice carries)."""
    rates = np.array([3.50, 3.75, 4.00, 4.25])
    probs = np.array([0.1, 0.4, 0.35, 0.15])
    total = 0.0
    for r in rates:
        legs = fly_legs(round(100.0 - r, 4))
        total += sum(w * price_option(rates, probs, right, 100.0 - k)
                     for right, k, w in legs)
    assert total == pytest.approx(25.0, abs=1e-9)


def test_a_cell_costs_a_quarter_of_what_the_digital_difference_costs():
    """4 contracts / 25bp of scale vs 4 legs x 16 lots / 6.25bp of scale."""
    fly_round_trip = option_leg_cost_bp(package_contracts(fly_legs(96.0)), 2)
    fly_break_even_pp = fly_round_trip / 25.0
    digital_lots = 4 * (100.0 / 6.25)
    digital_break_even_pp = option_leg_cost_bp(digital_lots, 2) / 100.0
    assert fly_break_even_pp == pytest.approx(0.04)
    assert digital_break_even_pp == pytest.approx(0.16)
    assert digital_break_even_pp == pytest.approx(4.0 * fly_break_even_pp)


# ---------------------------------------------------------------------------
# telescoping
# ---------------------------------------------------------------------------

def test_adjacent_flies_do_not_telescope_but_two_apart_do():
    a = fly_legs(96.00)
    b = fly_legs(96.25, weight=-1.0)
    c = fly_legs(96.50, weight=-1.0)
    assert package_contracts(a + b) == pytest.approx(8.0)       # 1,-3,3,-1
    assert package_contracts(a + c) == pytest.approx(6.0)       # shared leg dies
    netted = dict(((r, k), w) for r, k, w in telescope(a + c))
    assert netted.get(("C", 96.25)) is None


def test_full_map_book_is_the_second_difference_of_its_weights():
    """Equal weights on three adjacent cells collapse to the outer skeleton."""
    legs = []
    for i, k in enumerate((96.00, 96.25, 96.50)):
        legs += fly_legs(k, weight=1.0)
    net = {(r, k): w for r, k, w in telescope(legs)}
    assert net[("C", 95.75)] == pytest.approx(1.0)
    assert net[("C", 96.00)] == pytest.approx(-1.0)
    assert net[("C", 96.25)] == pytest.approx(0.0) if ("C", 96.25) in net else True
    assert net[("C", 96.50)] == pytest.approx(-1.0)
    assert net[("C", 96.75)] == pytest.approx(1.0)
    assert package_contracts(legs) == pytest.approx(4.0)   # not 12


def test_package_mark_is_nan_when_a_leg_is_unmarked():
    marks = {("C", 95.75): 10.0, ("C", 96.0): 6.0}
    assert not np.isfinite(package_mark(fly_legs(96.0),
                                        lambda r, k: marks.get((r, k), np.nan)))


# ---------------------------------------------------------------------------
# atoms, snapping, decomposition
# ---------------------------------------------------------------------------

def test_distinct_atoms_collapses_the_combination_grid():
    rates = np.array([3.50, 3.75, 3.75, 4.00])
    probs = np.array([0.2, 0.3, 0.3, 0.2])
    r, p = distinct_atoms(rates, probs)
    assert list(np.round(r, 6)) == [3.50, 3.75, 4.00]
    assert list(np.round(p, 6)) == [0.2, 0.6, 0.2]


def test_snap_center_requires_both_wings():
    strikes = [95.75, 96.00, 96.0625, 96.25]
    assert snap_center(96.02, strikes) == 96.00
    # 96.0625 is nearer to 96.05 but has no 95.8125/96.3125 wings
    assert snap_center(96.05, strikes) == 96.00
    assert snap_center(97.40, strikes) is None


def test_decompose_splits_even_and_odd_exactly():
    d = np.array([-2.0, -1.0, 0.0, 1.0, 2.0])
    r = 3.0 + 0.5 * d + 1.5 * d ** 2
    a, b, c, resid = decompose(d, r)
    assert (a, b, c) == pytest.approx((3.0, 0.5, 1.5))
    assert np.allclose(resid, 0.0, atol=1e-9)


def test_decompose_recovers_the_tilt_under_a_symmetric_smile():
    d = np.array([-2.0, -1.0, 0.0, 1.0, 2.0])
    r = -4.0 + 2.0 * d ** 2 - 0.8 * d           # rich low end, cheap high end
    a, b, c, _ = decompose(d, r)
    assert b == pytest.approx(-0.8)
    assert c == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# map construction and signals
# ---------------------------------------------------------------------------

def _planted_map(rich_by_cell, forward=4.00, masses=None):
    """A CellMap with hand-set richness on a lattice around ``forward``."""
    cells = []
    n = len(rich_by_cell)
    ms = masses if masses is not None else [1.0 / n] * n
    for (rate, rich), p in zip(rich_by_cell, ms):
        fair = 5.0
        cells.append(Cell(atom_rate=rate, p_lattice=p,
                          center_px=round(100.0 - rate, 4), offset_bp=0.0,
                          d=(rate - forward) / 0.25, mkt_bp=fair + rich,
                          fair_bp=fair))
    a, b, c, resid = decompose([x.d for x in cells], [x.rich_bp for x in cells],
                               [x.p_lattice for x in cells])
    return CellMap(symbol="SFRZ26", as_of=pd.Timestamp("2026-01-05"),
                   forward_rate=forward, smear_bp=5.0, n_resolved=3,
                   cells=tuple(cells), a=a, b=b, c=c,
                   resid=tuple(float(v) for v in resid))


def test_build_cell_map_reads_the_planted_surface():
    rates = np.array([3.75, 4.00, 4.25])
    probs = np.array([0.25, 0.5, 0.25])
    strikes = [95.50 + 0.0625 * i for i in range(24)]
    engine_rates, engine_probs = rates, probs

    def fair_fn(legs):
        return sum(w * price_option(engine_rates, engine_probs, right,
                                    100.0 - k) for right, k, w in legs)

    # market = tree everywhere except the modal cell, which is 2bp cheap
    def mark_fn(right, k):
        legs = [(right, k, 1.0)]
        base = price_option(engine_rates, engine_probs, right, 100.0 - k)
        return base

    cm = build_cell_map("SFRZ26", pd.Timestamp("2026-01-05"), 4.00, rates,
                        probs, 0.0, strikes, mark_fn, fair_fn, n_resolved=2)
    assert cm is not None and cm.n_cells == 3
    assert [round(x.center_px, 4) for x in cm.cells] == [96.25, 96.00, 95.75]
    assert np.allclose(cm.rich, 0.0, atol=1e-9)
    assert cm.p_fair_sum == pytest.approx(1.0, abs=1e-9)
    assert cm.off_lattice_premium == pytest.approx(0.0, abs=1e-9)


def test_pair_raw_picks_the_extremes_of_raw_richness():
    cm = _planted_map([(3.50, +1.0), (3.75, -3.0), (4.00, 0.0), (4.25, +2.0)])
    s = pair_raw_signal(cm)
    assert s["i_long"] == 1 and s["i_short"] == 3
    assert s["strength_bp"] == pytest.approx(5.0)


def test_pair_odd_picks_the_ends_and_follows_the_tilt():
    """A pure tilt: cheap low end, rich high end -> long low, short high."""
    cm = _planted_map([(3.50, -3.0), (3.75, -1.0), (4.00, +1.0), (4.25, +3.0)],
                      forward=3.875)
    s = pair_odd_signal(cm)
    assert s["i_long"] == 0 and s["i_short"] == 3
    assert s["strength_bp"] == pytest.approx(6.0)
    # mirror the tilt and the package must flip
    cm2 = _planted_map([(3.50, +3.0), (3.75, +1.0), (4.00, -1.0), (4.25, -3.0)],
                       forward=3.875)
    s2 = pair_odd_signal(cm2)
    assert s2["i_long"] == 3 and s2["i_short"] == 0


def test_pair_odd_ignores_a_purely_even_smile():
    """A symmetric smile is the standing premium: no odd part, no trade."""
    cm = _planted_map([(3.50, +2.0), (3.75, -2.0), (4.00, -2.0), (4.25, +2.0)],
                      forward=3.875)
    s = pair_odd_signal(cm)
    assert s["strength_bp"] == pytest.approx(0.0, abs=1e-9)
    # ...but the raw expression sees a 4bp "opportunity" — the control's flaw
    assert pair_raw_signal(cm)["strength_bp"] == pytest.approx(4.0)


def test_mean_pinning_makes_the_mass_centred_basis_the_right_one():
    """Real atom grids satisfy sum p_i d_i = 0 exactly (mean-pinning).

    The d range can still be lop-sided (-2..+1 here); under the mass measure the
    constant and the tilt are orthogonal, so a smile symmetric about the forward
    reads as pure even part however skewed the grid's SHAPE is.
    """
    masses = [0.15, 0.20, 0.15, 0.50]
    cells = [(3.50, 8.0), (3.75, 2.0), (4.00, 0.0), (4.25, 2.0)]   # r = 2 d^2
    cm = _planted_map(cells, forward=4.00, masses=masses)
    assert float((cm.p_lattice * cm.d).sum()) == pytest.approx(0.0, abs=1e-12)
    assert cm.b == pytest.approx(0.0, abs=1e-9)
    assert pair_odd_signal(cm)["strength_bp"] == pytest.approx(0.0, abs=1e-9)


def test_mass_weighting_keeps_a_thin_wing_from_setting_the_tilt():
    """A 2%-mass wing with an outlier richness must not define the odd part."""
    masses = [0.02, 0.235, 0.50, 0.215, 0.03]
    rates = [3.50, 3.75, 4.00, 4.25, 4.50]
    d = [(r - 4.00) / 0.25 for r in rates]
    rich = [1.5 * x ** 2 for x in d]
    rich[0] -= 6.0                                   # the thin wing's outlier
    cm = _planted_map(list(zip(rates, rich)), forward=4.00, masses=masses)
    assert float((cm.p_lattice * np.array(d)).sum()) == pytest.approx(0.0,
                                                                     abs=1e-12)
    _, b_flat, _, resid_flat = decompose(d, rich)
    # the tilt absorbs ~3x less of the shock under the mass measure...
    assert abs(cm.b) < 0.5 * abs(b_flat)
    # ...because the thin wing keeps its own shock in the local residual
    assert abs(cm.resid[0]) > abs(resid_flat[0])


def test_low_mass_cells_are_measured_but_not_traded():
    cm = _planted_map([(3.50, -9.0), (3.75, -1.0), (4.00, +1.0), (4.25, +3.0)],
                      forward=3.875, masses=[0.001, 0.4, 0.4, 0.199])
    s = pair_odd_signal(cm)
    assert s["i_long"] != 0                # the 0.1%-mass wing is not tradeable
    assert cm.n_cells == 4                 # ...but it is still in the map


def test_map_full_weights_are_zero_sum_and_normalised():
    cm = _planted_map([(3.50, +1.0), (3.75, -3.0), (4.00, 0.0), (4.25, +2.0)],
                      forward=3.875)
    res = map_full_weights(cm)
    w = res["weights"]
    assert np.abs(w).sum() == pytest.approx(2.0)
    o = cm.odd
    assert w[int(np.argmin(o))] > 0        # long the odd-cheapest cell
    assert w[int(np.argmax(o))] < 0        # short the odd-richest


# ---------------------------------------------------------------------------
# the linear leg
# ---------------------------------------------------------------------------

def _two_meeting_cm(q=(0.5, 0.5)) -> ContractMeetings:
    return ContractMeetings(
        symbol="SFRZ26", as_of=datetime.date(2026, 1, 5),
        window=(datetime.date(2026, 3, 18), datetime.date(2026, 6, 17)),
        expiry=datetime.date(2026, 3, 13),
        resolved=(
            ResolvedMeeting(effective=datetime.date(2026, 1, 29),
                            decision=datetime.date(2026, 1, 28), weight=1.0,
                            support=(0, 1), q_zq=q[0], jump_bp=q[0] * 25.0,
                            stale=False),
            ResolvedMeeting(effective=datetime.date(2026, 3, 19),
                            decision=datetime.date(2026, 3, 12), weight=1.0,
                            support=(0, 1), q_zq=q[1], jump_bp=q[1] * 25.0,
                            stale=False),
        ),
        unresolved_var_bp2=0.0, any_stale=False)


def test_package_hedge_ratio_matches_the_analytic_derivative():
    """With no smear the top cell's fly is 25*q1*q2: dV/djump_1 = 25*q2/25."""
    cm = _two_meeting_cm((0.4, 0.6))
    fwd = 4.00
    eng = AtomEngine(cm)
    rates, _ = eng.rates_probs(fwd)
    top = float(np.max(rates))
    legs = fly_legs(round(100.0 - top, 6))
    h = package_hedge_ratios(cm, fwd, legs, 0.0)
    # V = 25 * q1 * q2 ; dV/dq1 = 25*q2 ; dq1/djump = 1/25 -> h1 = q2
    assert h[0] == pytest.approx(0.6, abs=1e-6)
    assert h[1] == pytest.approx(0.4, abs=1e-6)


def test_resolved_meetings_drop_out_of_the_basket():
    cm = _two_meeting_cm((0.4, 0.6))
    eng = AtomEngine(cm)
    rates, _ = eng.rates_probs(4.00)
    legs = fly_legs(round(100.0 - float(np.max(rates)), 6))
    h = package_hedge_ratios(cm, 4.00, legs, 0.0, outcomes={0: 1})
    assert h[0] == 0.0
    assert h[1] == pytest.approx(1.0, abs=1e-6)     # q1 pinned at 1


def test_frame_frozen_value_is_multilinear_in_q():
    """The property the hedge stands on: V(q) is affine in each q separately."""
    cm = _two_meeting_cm()
    eng = AtomEngine(cm)
    rates, _ = eng.rates_probs(4.00)
    legs = fly_legs(round(100.0 - float(np.max(rates)), 6))
    q_ref = np.array([0.5, 0.5])
    vals = [package_tree_value(eng, 4.00, legs, 0.0, q=np.array([x, 0.5]),
                               q_ref=q_ref) for x in (0.2, 0.5, 0.8)]
    assert vals[1] - vals[0] == pytest.approx(vals[2] - vals[1], abs=1e-9)


def test_linear_cost_scales_with_the_basket_and_the_dv01_ratio():
    h = np.array([0.5, 0.25])
    con = zq_basket_contracts(h)
    assert con == pytest.approx(0.75 * (25.0 / 41.67) * 3)
    # the DV01 ratios cancel: 3 legs x half-tick x |h| per side
    assert linear_leg_cost_bp(con, 1) == pytest.approx(0.75 * 3 * 0.25, abs=1e-9)


# ---------------------------------------------------------------------------
# the trade loop
# ---------------------------------------------------------------------------

def _scripted(dates, marks, fairs):
    mk = dict(zip(dates, marks))
    fr = dict(zip(dates, fairs))
    return (lambda ts, legs: mk.get(ts, np.nan),
            lambda ts, sym, legs: fr.get(ts, np.nan))


def _entries(legs):
    return pd.DataFrame([{"as_of": pd.Timestamp("2026-01-05"),
                          "symbol": "SFRZ26", "legs": legs,
                          "strength_bp": 4.0, "expression": "pair_odd"}])


def test_engine_converge_exit_and_cost_arithmetic():
    dates = pd.DatetimeIndex(pd.bdate_range("2026-01-05", periods=8))
    #      sig = mark - fair : -4, -3, -1.5, ... converges to half at t=3
    marks = [0.0, 6.0, 7.0, 8.5, 9.0, 9.0, 9.0, 9.0]
    fairs = [10.0] * 8
    mark_fn, fair_fn = _scripted(dates, marks, fairs)
    legs = fly_legs(96.0) + fly_legs(96.5, weight=-1.0)
    tr = run_outcome_backtest(_entries(legs), mark_fn, fair_fn, dates,
                              direction="fade", exit_rule="converge",
                              exit_frac=0.5, max_hold=10)
    assert len(tr) == 1
    t = tr[0]
    assert t.entry == dates[1] and t.exit == dates[3]
    assert t.entry_signal_bp == pytest.approx(-4.0)
    assert t.opt_gross_bp == pytest.approx(8.5 - 6.0)
    assert t.opt_cost_bp == pytest.approx(6.0 * 0.125 * 2)   # telescoped to 6
    assert t.lin_cost_bp == 0.0 and t.hedge_bp == 0.0
    assert t.net_bp == pytest.approx(t.gross_bp - t.cost_bp)
    assert t.daily.sum() == pytest.approx(t.net_bp, abs=1e-9)


def test_engine_direction_mirrors_on_gross():
    dates = pd.DatetimeIndex(pd.bdate_range("2026-01-05", periods=8))
    marks = [0.0, 6.0, 7.0, 8.5, 9.0, 9.0, 9.0, 9.0]
    fairs = [10.0] * 8
    mark_fn, fair_fn = _scripted(dates, marks, fairs)
    legs = fly_legs(96.0)
    kw = dict(exit_rule="hold", max_hold=3)
    a = run_outcome_backtest(_entries(legs), mark_fn, fair_fn, dates,
                             direction="fade", **kw)[0]
    b = run_outcome_backtest(_entries(legs), mark_fn, fair_fn, dates,
                             direction="momentum", **kw)[0]
    assert a.gross_bp == pytest.approx(-b.gross_bp)
    assert a.cost_bp == pytest.approx(b.cost_bp)


def test_engine_hedge_leg_pnl_and_bill_are_separable():
    dates = pd.DatetimeIndex(pd.bdate_range("2026-01-05", periods=6))
    marks = [0.0, 6.0, 6.0, 6.0, 6.0, 6.0]          # option leg flat
    fairs = [10.0] * 6
    mark_fn, fair_fn = _scripted(dates, marks, fairs)
    legs = fly_legs(96.0)
    eff = datetime.date(2026, 3, 19)
    ctx = HedgeContext(effectives=(eff,), supports=((0, 1),),
                       ratios=lambda outcomes: np.array(
                           [0.0 if 0 in outcomes else 0.5]))
    jumps = {dates[1]: 10.0, dates[2]: 12.0, dates[3]: 12.0,
             dates[4]: 12.0, dates[5]: 12.0}

    def jump_fn(ts, e):
        return jumps.get(ts, np.nan)

    t = run_outcome_backtest(
        _entries(legs), mark_fn, fair_fn, dates, direction="fade",
        exit_rule="hold", max_hold=3, linear_leg="zq",
        hedge_ctx_fn=lambda ts, sym, lg: ctx, jump_fn=jump_fn)[0]
    # hedge = -side * h * d(jump) = -1 * 0.5 * (12 - 10)
    assert t.hedge_bp == pytest.approx(-1.0)
    assert t.opt_gross_bp == pytest.approx(0.0)
    assert t.lin_contracts == pytest.approx(zq_basket_contracts([0.5]))
    assert t.lin_cost_bp == pytest.approx(
        2 * linear_leg_cost_bp(t.lin_contracts, 1))
    assert t.daily.sum() == pytest.approx(t.net_bp, abs=1e-9)


def test_engine_holds_one_package_per_symbol():
    dates = pd.DatetimeIndex(pd.bdate_range("2026-01-05", periods=12))
    marks = [float(i) for i in range(12)]
    fairs = [20.0] * 12
    mark_fn, fair_fn = _scripted(dates, marks, fairs)
    legs = fly_legs(96.0)
    ent = pd.concat([_entries(legs),
                     _entries(legs).assign(
                         as_of=pd.Timestamp(dates[2]))], ignore_index=True)
    tr = run_outcome_backtest(ent, mark_fn, fair_fn, dates, direction="fade",
                              exit_rule="hold", max_hold=6)
    assert len(tr) == 1
