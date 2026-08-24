"""The engine wiring: sign map, leg construction, date pinning — all offline.

The sign map is the one place a silent inversion would corrupt every certified
number downstream, so it is pinned per side and per leg, not once.
"""
import datetime

import pandas as pd
import pytest

from RVUtils.ConvexityRV.cavf_engine import (
    CavfTradeSpec,
    assert_ran,
    build_trade_queries,
    fly_leg_dates,
    spec_from_episode,
)
from RVUtils.ConvexityRV.strat2_fly_universe import fly_universe

FLIES = {f.fly_id: f for f in fly_universe(
    forward_starts=(0.0, 1.0, 2.0, 3.0, 4.0, 5.0))}
ENTRY, EXIT = datetime.date(2024, 7, 1), datetime.date(2024, 8, 15)


def _spec(side, label="BLUES", fly="2s5s10s", beta=0.2):
    return spec_from_episode(label=label, side=side, entry=ENTRY, exit=EXIT,
                             beta_entry=beta, fly=FLIES[fly])


class TestSpecResolution:
    def test_blues_resolves_contracts_and_window(self):
        s = _spec(-1)
        assert s.symbols == ("SR3U27", "SR3Z27", "SR3H28", "SR3M28")
        assert s.contracts_per_leg == 1000
        assert s.swap_start == datetime.date(2027, 9, 15)
        assert s.swap_end == datetime.date(2028, 9, 20)

    def test_bundle_and_outright_leg_counts(self):
        b = _spec(-1, label="BUNDLE2Y")
        assert len(b.symbols) == 8 and b.contracts_per_leg == 500
        o = _spec(-1, label="SFR8")
        assert len(o.symbols) == 1 and o.contracts_per_leg == 4000

    def test_belly_dv01_sign_per_side(self):
        """Short spread with β>0 PAYS the belly (+); long spread receives (−);
        and a NEGATIVE β flips the belly rather than shrinking it — the abs()
        variant shipped once and certified at corr −0.005."""
        assert _spec(-1).fly.belly_dv01 == +0.2 * 100_000.0
        assert _spec(+1).fly.belly_dv01 == -0.2 * 100_000.0
        assert _spec(-1, beta=-0.2).fly.belly_dv01 == -0.2 * 100_000.0
        assert _spec(+1, beta=-0.2).fly.belly_dv01 == +0.2 * 100_000.0

    def test_zero_beta_attaches_no_fly(self):
        s = spec_from_episode(label="BLUES", side=-1, entry=ENTRY, exit=EXIT,
                              beta_entry=0.0, fly=FLIES["2s5s10s"])
        assert s.fly is None


class TestFlyDatePinning:
    def test_spot_legs_start_at_entry(self):
        d = fly_leg_dates(FLIES["2s5s10s"], ENTRY)
        assert d["front"] == (ENTRY, datetime.date(2026, 7, 1))
        assert d["belly"] == (ENTRY, datetime.date(2029, 7, 1))
        assert d["back"] == (ENTRY, datetime.date(2034, 7, 1))

    def test_forward_start_shifts_the_effective(self):
        d = fly_leg_dates(FLIES["2s5s10s@4Y"], ENTRY)
        eff = datetime.date(2028, 7, 1)
        assert d["front"] == (eff, datetime.date(2030, 7, 1))
        assert d["back"] == (eff, datetime.date(2038, 7, 1))


class TestQueryConstruction:
    def test_short_spread_is_citis_book(self):
        """side=−1: LONG futures, PAY the swap, PAY the belly. Direction rides
        the risk weight; contracts stay POSITIVE (negative contracts cancel
        against the builder's weight flip and go silently long)."""
        qs = build_trade_queries(_spec(-1))
        fut, swap, fly = qs[:4], qs[4], qs[5]
        assert len(qs) == 6
        for q in fut:
            assert q.structure_kwargs["contracts"] == +1000
            assert q.structure_kwargs["risk_weights"] == [+1.0]
        assert swap.structure_kwargs["bpv"] == +100_000.0
        assert fly.structure_kwargs["bpv"] == +20_000.0

    def test_long_spread_mirrors_every_leg(self):
        qs = build_trade_queries(_spec(+1))
        for q in qs[:4]:
            assert q.structure_kwargs["contracts"] == +1000, (
                "contracts must NEVER be negative on a STIRFutureQuery")
            assert q.structure_kwargs["risk_weights"] == [-1.0]
        assert qs[4].structure_kwargs["bpv"] == -100_000.0
        assert qs[5].structure_kwargs["bpv"] == -20_000.0

    def test_swap_is_date_pinned_not_tenor(self):
        qs = build_trade_queries(_spec(-1))
        swap = qs[4]
        assert swap.effective_date == datetime.date(2027, 9, 15)
        assert swap.maturity_date == datetime.date(2028, 9, 20)

    def test_fly_legs_are_date_pinned(self):
        """A relative tenor re-resolves at every mark (the w4 defect); every
        fly leg must carry explicit dates."""
        qs = build_trade_queries(_spec(-1, fly="2s5s10s@4Y"))
        k = qs[5].structure_kwargs
        for leg in ("front", "belly", "back"):
            assert isinstance(k[f"{leg}_effective_date"], datetime.date)
            assert isinstance(k[f"{leg}_maturity_date"], datetime.date)
        assert k["front_effective_date"] == datetime.date(2028, 7, 1)

    def test_risk_weights_list_is_fresh_per_call(self):
        """_build_fly mutates risk_weights in place; two calls must not share."""
        q1 = build_trade_queries(_spec(-1))[5]
        q2 = build_trade_queries(_spec(-1))[5]
        assert q1.structure_kwargs["risk_weights"] is not q2.structure_kwargs["risk_weights"]

    def test_every_query_carries_the_tag(self):
        s = _spec(-1)
        for q in build_trade_queries(s):
            assert s.tag in tuple(q.tags)


class TestAssertRan:
    class _StubBT:
        def __init__(self, mtm, n_closed):
            self.mtm_history = mtm

            class P:
                closed_positions_log = [{}] * n_closed
            self.portfolio = P()

    def test_empty_mtm_is_a_swallowed_exception(self):
        with pytest.raises(AssertionError, match="swallowed"):
            assert_ran(self._StubBT({}, 0), [_spec(-1)])

    def test_flat_equity_is_a_planning_failure(self):
        mtm = {pd.Timestamp("2024-07-01") + pd.Timedelta(days=i): 0.0
               for i in range(30)}
        with pytest.raises(AssertionError, match="identically zero"):
            assert_ran(self._StubBT(mtm, 12), [_spec(-1)])

    def test_missing_unwind_is_caught(self):
        mtm = {pd.Timestamp("2024-07-01"): 0.0, pd.Timestamp("2024-07-02"): 5.0}
        with pytest.raises(AssertionError, match="unwind never matched"):
            assert_ran(self._StubBT(mtm, 2), [_spec(-1)])
