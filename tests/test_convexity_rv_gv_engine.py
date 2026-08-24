"""GV block — the engine layer: instrument resolution, sizing, sign map.

These tests are all offline: they inspect the query objects the engine WOULD
send, which is where the silent factor-of-two and the silent sign flip live.
The end-to-end certification against real marks lives in
``notebooks/backtests/convexity_rv/_p2_certify.py``.
"""
from __future__ import annotations

import datetime

import numpy as np
import pandas as pd
import pytest

from RVUtils.ConvexityRV import gv_engine as GE
from RVUtils.ConvexityRV import gv_sizing as S
from RVUtils.ConvexityRV import gv_universe as U

ENTRY = datetime.date(2024, 3, 5)
EXIT = datetime.date(2024, 5, 6)


def _spec(**kw):
    base = dict(structure="BLUES", leg_id="immM_2s5s10s", side=-1,
                entry=ENTRY, exit=EXIT, beta_entry=0.25, ca_dv01=100_000.0)
    base.update(kw)
    return GE.spec_from_episode(**base)


def _kwargs(q):
    return dict(getattr(q, "structure_kwargs", {}) or {})


# ---------------------------------------------------------------------------
# 1. Instrument resolution
# ---------------------------------------------------------------------------
def test_imm_leg_dates_are_pinned_to_the_entry_dates_imm():
    """The whole point of an IMM-dated position: the effective date is the IMM
    the rank resolved to AT ENTRY, and it does not re-resolve later."""
    from Query.Base.imm_resolution import resolve_imm_token
    d = GE.leg_dates("immM_2s5s10s", "BLUES", ENTRY)
    eff = resolve_imm_token("IMM_13", ENTRY)
    eff = eff.date() if hasattr(eff, "date") else eff
    assert [x[0] for x in d] == [eff, eff, eff]
    assert [x[1] for x in d] == [GE.add_years(eff, y) for y in (2, 5, 10)]


def test_matched_leg_uses_the_structures_rank_not_the_front():
    a = GE.leg_dates("immM_2s5s10s", "BLUES", ENTRY)[0][0]
    b = GE.leg_dates("immF_2s5s10s", "BLUES", ENTRY)[0][0]
    assert a > b, "the matched leg must start at IMM_13, not IMM_1"
    g = GE.leg_dates("immM_2s5s10s", "GREENS", ENTRY)[0][0]
    assert b < g < a, "GREENS (IMM_9) sits between IMM_1 and IMM_13"


def test_spot_and_forward_legs_resolve_from_the_entry_date():
    s = GE.leg_dates("spot_2s5s10s", None, ENTRY)
    assert [x[0] for x in s] == [ENTRY] * 3
    f = GE.leg_dates("le_10y10y_15y10y", None, ENTRY)
    assert f[0] == (GE.add_years(ENTRY, 10), GE.add_years(ENTRY, 20))
    assert f[1] == (GE.add_years(ENTRY, 15), GE.add_years(ENTRY, 25))


def test_add_years_is_calendar_and_day_capped():
    assert GE.add_years(datetime.date(2024, 3, 31), 1) == datetime.date(2025, 3, 28)
    assert GE.add_years(datetime.date(2024, 3, 5), 0.5) == datetime.date(2024, 9, 5)


# ---------------------------------------------------------------------------
# 2. The factor of two, and the sign map
# ---------------------------------------------------------------------------
def test_a_fly_leg_is_sent_at_twice_the_quoted_dv01():
    """This block quotes a fly as ``2b-f-k``; a [0.5,1,0.5] package earns
    ``bpv/2`` per bp of that, so the bpv sent must be 2x the quoted leg DV01.
    Halving it silently halves exactly the leg this block re-sizes."""
    sp = _spec()
    qs = GE.build_trade_queries(sp)
    fly = qs[-1]
    k = _kwargs(fly)
    assert k["risk_weights"] == [0.5, 1.0, 0.5]
    assert k["bpv"] == pytest.approx(2.0 * sp.leg.leg_dv01_signed)
    # and the package's P&L per bp of the quoted fly is the quoted leg DV01
    assert k["bpv"] / 2.0 == pytest.approx(sp.leg.leg_dv01_signed)


def test_a_curve_leg_is_sent_at_one_times_the_quoted_dv01():
    sp = _spec(leg_id="le_10y10y_15y10y")
    k = _kwargs(GE.build_trade_queries(sp)[-1])
    assert k["risk_weights"] == [1.0, 1.0]
    assert k["bpv"] == pytest.approx(sp.leg.leg_dv01_signed)


def test_leg_dv01_reproduces_the_panel_identity():
    """``P&L = side*(dCA - beta*dleg)*dv01`` means the leg earns
    ``-side*beta*dv01`` per bp of the leg."""
    for side in (-1, 1):
        for beta in (0.25, -0.4):
            sp = _spec(side=side, beta_entry=beta)
            assert sp.leg.leg_dv01_signed == pytest.approx(
                -side * beta * 100_000.0)


def test_a_negative_beta_flips_the_leg_it_does_not_shrink_it():
    """An ``abs(beta)`` here shipped once in block 3 and certified at corr
    -0.005."""
    pos = _spec(beta_entry=+0.3).leg.leg_dv01_signed
    neg = _spec(beta_entry=-0.3).leg.leg_dv01_signed
    assert pos == pytest.approx(-neg)
    assert pos * neg < 0


def test_futures_direction_rides_the_risk_weight_with_contracts_positive():
    """A negative ``contracts`` on a STIRFutureQuery silently goes LONG: the
    outright builder flips the weight AND the rateslib leg carries the negative
    notional, so the two negations cancel."""
    for side, want in ((-1, +1.0), (+1, -1.0)):
        qs = GE.build_trade_queries(_spec(side=side))
        futs = [q for q in qs if type(q).__name__ == "STIRFutureQuery"]
        assert futs, "no futures legs were built"
        for q in futs:
            k = _kwargs(q)
            assert k["contracts"] > 0, "contracts must stay positive"
            assert k["risk_weights"] == [want]


def test_the_matched_swap_is_opposite_the_futures():
    """Short the spread (-1) = buy the futures and PAY the matched swap."""
    qs = GE.build_trade_queries(_spec(side=-1))
    swap = [q for q in qs if type(q).__name__ == "IRSwapQuery"][0]
    assert _kwargs(swap)["bpv"] == pytest.approx(+100_000.0)
    qs = GE.build_trade_queries(_spec(side=+1))
    swap = [q for q in qs if type(q).__name__ == "IRSwapQuery"][0]
    assert _kwargs(swap)["bpv"] == pytest.approx(-100_000.0)


def test_one_futures_query_per_contract_and_the_swap_window_is_dated():
    sp = _spec()
    qs = GE.build_trade_queries(sp)
    n_fut = sum(1 for q in qs if type(q).__name__ == "STIRFutureQuery")
    assert n_fut == len(sp.symbols) == 4          # BLUES is four contracts
    assert sp.swap_start < sp.swap_end
    assert (sp.swap_end - sp.swap_start).days > 300


def test_an_outright_structure_builds_a_single_futures_leg():
    sp = _spec(structure="SFR12")
    assert len(sp.symbols) == 1
    qs = GE.build_trade_queries(sp)
    assert sum(1 for q in qs if type(q).__name__ == "STIRFutureQuery") == 1


def test_zero_beta_builds_no_hedge_leg():
    sp = _spec(beta_entry=0.0)
    assert sp.leg is None
    qs = GE.build_trade_queries(sp)
    assert len(qs) == len(sp.symbols) + 1


def test_risk_weights_are_a_fresh_list_per_query():
    """``IRSwapStructure._build_fly`` mutates ``risk_weights`` in place; two
    specs must not share one."""
    a = _kwargs(GE.build_trade_queries(_spec())[-1])["risk_weights"]
    b = _kwargs(GE.build_trade_queries(_spec())[-1])["risk_weights"]
    assert a == b == [0.5, 1.0, 0.5]
    assert a is not b


def test_assert_ran_refuses_an_empty_plan_and_a_flat_book():
    class _P:
        closed_positions_log = []

    class _BT:
        mtm_history = {}
        portfolio = _P()

    with pytest.raises(AssertionError, match="no specs were planned"):
        GE.assert_ran(_BT(), [])
    with pytest.raises(AssertionError, match="mtm_history is empty"):
        GE.assert_ran(_BT(), [_spec()])

    class _BT2(_BT):
        mtm_history = {pd.Timestamp("2024-03-05"): 0.0,
                       pd.Timestamp("2024-03-06"): 0.0}
    with pytest.raises(AssertionError, match="identically zero"):
        GE.assert_ran(_BT2(), [_spec()])


# ---------------------------------------------------------------------------
# 3. The causal roll splice the dated arm signals on
# ---------------------------------------------------------------------------
def test_roll_splice_removes_a_planted_jump_exactly():
    idx = pd.bdate_range("2021-01-04", periods=300)
    base = pd.Series(10.0, index=idx)                 # flat: nothing to lose
    rolls = [idx[60], idx[140], idx[220]]
    jumped = base.copy()
    for r in rolls:
        jumped.loc[jumped.index >= r] += 1.5
    sp = S.roll_spliced(jumped, rolls)
    assert np.allclose(sp.to_numpy(), base.to_numpy(), atol=1e-12)


def test_roll_splice_also_discards_one_day_of_genuine_move_per_roll():
    """The known cost of the continuous-futures convention, stated rather than
    discovered later: on a roll date the observed change is the contract switch
    PLUS that day's market move, and the panel cannot separate them, so the
    splice removes both.  Over 22 rolls on a series drifting at ~0.007 bp/day
    that is ~0.15 bp of level — an order of magnitude below the +0.95 bp/roll
    jump it removes, which is why the convention is still the right one."""
    idx = pd.bdate_range("2021-01-04", periods=300)
    drift = 0.01
    base = pd.Series(10.0 + drift * np.arange(len(idx)), index=idx)
    rolls = [idx[60], idx[140], idx[220]]
    jumped = base.copy()
    for r in rolls:
        jumped.loc[jumped.index >= r] += 1.5
    sp = S.roll_spliced(jumped, rolls)
    lost = float(base.iloc[-1] - sp.iloc[-1])
    assert lost == pytest.approx(len(rolls) * drift, rel=1e-9)
    assert abs(lost) < 0.02 * len(rolls) * 1.5, "the loss is small vs the jump"


def test_roll_splice_is_causal():
    """Backward adjustment would rewrite history at every new roll -- fine for a
    chart, look-ahead for a z-score."""
    idx = pd.bdate_range("2021-01-04", periods=300)
    rng = np.random.default_rng(5)
    s = pd.Series(rng.normal(0, 1, len(idx)).cumsum() + 10, index=idx)
    rolls = [idx[60], idx[140], idx[220]]
    full = S.roll_spliced(s, rolls)
    trunc = S.roll_spliced(s.iloc[:150], [r for r in rolls if r in s.index[:150]])
    assert np.allclose(full.iloc[:150].to_numpy(), trunc.to_numpy())


def test_roll_splice_leaves_a_series_with_no_rolls_untouched():
    idx = pd.bdate_range("2021-01-04", periods=100)
    s = pd.Series(np.arange(100.0), index=idx)
    assert np.allclose(S.roll_spliced(s, []).to_numpy(), s.to_numpy())
