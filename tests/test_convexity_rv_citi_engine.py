"""The Citi engine layer: fitted-weight flies, per-segment tags, the sign map.

Offline: these inspect the query objects the engine WOULD send, which is where
the silent factor-of-two and the silent sign flip live.  The end-to-end
certification against real marks lives in
``notebooks/backtests/convexity_rv/_p4_engine.py``.
"""
from __future__ import annotations

import datetime

import pytest

from RVUtils.ConvexityRV import citi_engine as CE

ENTRY = datetime.date(2024, 3, 5)
EXIT = datetime.date(2024, 6, 5)
RESTRIKE = datetime.date(2024, 3, 20)


def _spec(**kw):
    base = dict(structure="BLUES", side=-1, entry=ENTRY, exit=EXIT,
                ca_dv01=200_000.0,
                hedge_path=[(ENTRY, 0.206, 0.705, 0.465)])
    base.update(kw)
    return CE.spec_from_episode(**base)


def _kw(q):
    return dict(getattr(q, "structure_kwargs", {}) or {})


# ---------------------------------------------------------------------------
# 1. Instrument resolution
# ---------------------------------------------------------------------------
def test_fly_legs_are_pinned_at_the_strike_date():
    """A relative tenor re-resolves at every mark and prices a fresh at-market
    package forever -- one of the two documented ways a QueryDrivenBacktest
    returns a flat curve while reporting success."""
    d = CE.fly_leg_dates(ENTRY)
    assert [x[0] for x in d] == [ENTRY] * 3
    assert [x[1] for x in d] == [CE.add_years(ENTRY, y) for y in (2, 5, 10)]


def test_a_restrike_produces_a_second_segment_pinned_at_its_own_date():
    sp = _spec(hedge_path=[(ENTRY, 0.206, 0.705, 0.465),
                           (RESTRIKE, 0.15, 0.5, 0.5)])
    assert len(sp.fly_segments) == 2
    a, b = sp.fly_segments
    assert (a.start, a.end) == (ENTRY, RESTRIKE)
    assert (b.start, b.end) == (RESTRIKE, EXIT)
    assert a.dates[0][0] == ENTRY and b.dates[0][0] == RESTRIKE
    assert a.w2 == 0.705 and b.w2 == 0.5


def test_the_futures_and_swap_windows_are_the_notes_own():
    """"buy 2000 of H0-Z0 packs ... pay $2bn on a matched-maturity
    (3/18/20-3/17/21) swap" -- four contracts, and a swap that tiles them."""
    sp = _spec()
    assert len(sp.symbols) == 4
    assert sp.swap_start < sp.swap_end
    assert 350 < (sp.swap_end - sp.swap_start).days < 380
    assert sp.contracts_per_leg == int(round(200_000.0 / (4 * 25.0)))


def test_an_empty_hedge_path_is_the_unhedged_variant():
    sp = _spec(hedge_path=[])
    assert sp.fly_segments == ()
    q = CE.build_queries(sp)
    assert set(q) == {sp.tag}
    assert len(q[sp.tag]) == 5           # four futures + the matched swap


def test_a_zero_beta_segment_is_dropped_rather_than_sent_at_zero_size():
    sp = _spec(hedge_path=[(ENTRY, 0.0, 0.5, 0.5)])
    assert sp.fly_segments == ()


def test_a_restrike_after_the_exit_is_dropped():
    late = datetime.date(2024, 9, 1)
    sp = _spec(hedge_path=[(ENTRY, 0.2, 0.5, 0.5), (late, 0.9, 0.1, 0.9)])
    assert len(sp.fly_segments) == 1
    assert sp.fly_segments[0].end == EXIT


# ---------------------------------------------------------------------------
# 2. The factor of ONE, and the sign map
# ---------------------------------------------------------------------------
def test_a_fitted_fly_is_sent_at_ONE_times_the_quoted_dv01():
    """``gv_engine`` quotes ``2b-f-k`` with 50/50 wings and must send 2x.  This
    fly is quoted ``r5 - w2*r2 - w10*r10`` with FITTED weights, so a
    ``[w2, 1, w10]`` package earns exactly ``bpv`` per bp and 2x here would
    DOUBLE the hedge."""
    sp = _spec()
    seg = sp.fly_segments[0]
    fly = CE.build_queries(sp)[sp.fly_tag(0)][0]
    k = _kw(fly)
    assert k["risk_weights"] == [0.705, 1.0, 0.465]
    assert k["bpv"] == pytest.approx(seg.leg_dv01_signed)
    assert k["bpv"] != pytest.approx(2.0 * seg.leg_dv01_signed)


def test_the_risk_weights_list_is_fresh_each_time():
    """``_build_fly`` mutates ``risk_weights`` in place; a shared list would be
    corrupted by the first query built from it."""
    seg = _spec().fly_segments[0]
    a, b = seg.risk_weights, seg.risk_weights
    assert a == b and a is not b
    a[0] = -99.0
    assert seg.risk_weights[0] == 0.705


def test_leg_dv01_reproduces_the_panel_identity():
    """``P&L = side*(dCA - beta*dcombo)*dv01`` means the fly leg earns
    ``-side*beta*dv01`` per bp of the combination."""
    for side in (-1, 1):
        for beta in (0.206, -0.4):
            sp = _spec(side=side, hedge_path=[(ENTRY, beta, 0.5, 0.5)])
            assert sp.fly_segments[0].leg_dv01_signed == pytest.approx(
                -side * beta * 200_000.0)


def test_selling_the_ca_pays_the_belly_at_citis_own_size():
    """The note: "$200k DV01 of Blues CA ... hedge by PAYING the belly ... at
    0.705/-1/0.465 DV01 weights".  Its printed beta is 20.6 bp per percent, so
    the belly DV01 must be 0.206 x 200k = $41,200 and POSITIVE (pay)."""
    sp = _spec()
    k = _kw(CE.build_queries(sp)[sp.fly_tag(0)][0])
    assert k["bpv"] == pytest.approx(41_200.0)
    assert k["bpv"] > 0


def test_a_negative_beta_flips_the_hedge_it_does_not_shrink_it():
    pos = _spec(hedge_path=[(ENTRY, +0.3, 0.5, 0.5)]).fly_segments[0]
    neg = _spec(hedge_path=[(ENTRY, -0.3, 0.5, 0.5)]).fly_segments[0]
    assert pos.leg_dv01_signed == pytest.approx(-neg.leg_dv01_signed)
    assert pos.leg_dv01_signed * neg.leg_dv01_signed < 0


def test_futures_direction_rides_the_risk_weight_with_contracts_positive():
    """A negative ``contracts`` on a STIRFutureQuery silently goes LONG."""
    for side, want in ((-1, +1.0), (+1, -1.0)):
        qs = CE.build_queries(_spec(side=side))[f"citi_BLUES_20240305_"
                                                f"{'S' if side < 0 else 'L'}"]
        futs = [q for q in qs if type(q).__name__ == "STIRFutureQuery"]
        assert len(futs) == 4
        for q in futs:
            k = _kw(q)
            assert k["contracts"] > 0
            assert k["risk_weights"] == [want]


def test_selling_the_ca_pays_the_matched_swap():
    """"pay $2bn on a matched-maturity swap": positive bpv is PAY."""
    sp = _spec(side=-1)
    sw = [q for q in CE.build_queries(sp)[sp.tag]
          if type(q).__name__ == "IRSwapQuery"][0]
    assert _kw(sw)["bpv"] == pytest.approx(+200_000.0)
    sp2 = _spec(side=+1)
    sw2 = [q for q in CE.build_queries(sp2)[sp2.tag]
           if type(q).__name__ == "IRSwapQuery"][0]
    assert _kw(sw2)["bpv"] == pytest.approx(-200_000.0)


# ---------------------------------------------------------------------------
# 3. Tags -- the thing that makes a re-strike expressible at all
# ---------------------------------------------------------------------------
def test_each_fly_incarnation_carries_its_own_tag():
    sp = _spec(hedge_path=[(ENTRY, 0.206, 0.705, 0.465),
                           (RESTRIKE, 0.15, 0.5, 0.5)])
    q = CE.build_queries(sp)
    assert set(q) == {sp.tag, sp.fly_tag(0), sp.fly_tag(1)}
    assert sp.fly_tag(0) != sp.fly_tag(1) != sp.tag


def test_the_ca_tag_is_not_a_prefix_match_of_a_fly_tag():
    """``UnwindPositionsAction`` matches by exact set membership, so an unwind
    of the CA package must not also close the hedge -- and vice versa."""
    sp = _spec()
    assert sp.tag not in {sp.fly_tag(0)}
    for q in CE.build_queries(sp)[sp.fly_tag(0)]:
        assert sp.tag not in set(q.tags)
    for q in CE.build_queries(sp)[sp.tag]:
        assert sp.fly_tag(0) not in set(q.tags)


def test_charged_dv01_is_the_sum_of_the_three_leg_dv01s():
    seg = _spec().fly_segments[0]
    assert seg.charged_dv01 == pytest.approx(
        abs(seg.leg_dv01_signed) * (1.0 + 0.705 + 0.465))
    flat = _spec(hedge_path=[(ENTRY, 0.2, 0.5, 0.5)]).fly_segments[0]
    assert flat.charged_dv01 == pytest.approx(2.0 * abs(flat.leg_dv01_signed))


# ---------------------------------------------------------------------------
# 4. assert_ran refuses the two known silent zeros
# ---------------------------------------------------------------------------
class _Portfolio:
    def __init__(self, n):
        self.closed_positions_log = [{}] * n


class _BT:
    def __init__(self, mtm, n_closed):
        self.mtm_history = mtm
        self.portfolio = _Portfolio(n_closed)


def test_assert_ran_refuses_an_empty_plan():
    with pytest.raises(AssertionError, match="no specs"):
        CE.assert_ran(_BT({datetime.date(2024, 1, 2): 1.0}, 9), [])


def test_assert_ran_refuses_an_identically_zero_curve():
    sp = _spec()
    mtm = {datetime.date(2024, 1, 2): 0.0, datetime.date(2024, 1, 3): 0.0}
    with pytest.raises(AssertionError, match="identically zero"):
        CE.assert_ran(_BT(mtm, 6), [sp])


def test_assert_ran_refuses_when_an_unwind_never_matched_its_tag():
    sp = _spec()
    mtm = {datetime.date(2024, 1, 2): 1.0, datetime.date(2024, 1, 3): 2.0}
    with pytest.raises(AssertionError, match="closed positions"):
        CE.assert_ran(_BT(mtm, 3), [sp])


def test_assert_ran_accepts_a_book_that_actually_traded():
    sp = _spec()
    mtm = {datetime.date(2024, 1, 2): 1.0, datetime.date(2024, 1, 3): 2.0}
    eq = CE.assert_ran(_BT(mtm, 6), [sp])       # 4 futures + swap + 1 fly
    assert len(eq) == 2 and float(eq.iloc[-1]) == 2.0
