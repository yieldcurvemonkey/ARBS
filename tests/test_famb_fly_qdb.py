"""Synthetic tests: the FLY structure + the FLY25 carry port (no network)."""
import datetime
import sys
from pathlib import Path

import pandas as pd
import pytest
import pytz

sys.path.insert(0, str(Path(__file__).resolve().parent.parent
                       / "notebooks" / "backtests"))

from famb_fly_qdb import (        # noqa: E402
    FlyState,
    build_roll_schedule,          # noqa: F401  (import check)
    linear_cost_usd,
    make_fly_backtest,
    package_delta,
)
from famb_fade_qdb import closed_positions_frame  # noqa: E402
from BT.query_order import QueryOrder, UnwindOrder  # noqa: E402
from Query.STIRFutureOptions.STIRFutureOptionQuery import (  # noqa: E402
    STIRFutureOptionQuery,
)
from Query.STIRFutureOptions.STIRFutureOptionStructure import (  # noqa: E402
    STIRFutureOptionStructure,
)
from Query.STIRFutureOptions.STIRFutureOptionValue import (  # noqa: E402
    STIRFutureOptionValue,
)
from Query.STIRFutureOptions.backends.quantlib.QLSTIRFutureOptionPricer import (  # noqa: E402
    QLSTIRFutureOptionPricer,
)

NY = pytz.timezone("America/New_York")
DATES = pd.bdate_range("2026-06-01", periods=6)
LOW, MID, HIGH = "SFRU26|9575C", "SFRU26|9600C", "SFRU26|9625C"


def _pricer(label, price, ts, delta=0.5):
    right = label[-1]
    strike = float(label.split("|", 1)[1][:-1]) / 100.0
    return QLSTIRFutureOptionPricer(
        symbol=label, right=right,
        underlying_symbol=label.split("|", 1)[0], strike=strike,
        quote_timestamp=ts, expiry_date=datetime.date(2026, 9, 11),
        market_price=price, model_price=price, iv_normal=0.8, delta=delta,
        gamma=0.1, vega=0.05, theta=-0.01, forward=96.0, discount=1.0,
        meta_data={},
    )


class StubOptMDP:
    """schedule: {date -> {label -> (premium, delta)}}."""

    def __init__(self, schedule):
        self.schedule = schedule

    def get_pricer(self, request):
        d = request["timestamp"]
        ts = NY.localize(datetime.datetime(d.year, d.month, d.day, 17, 0))
        return {lbl: [_pricer(lbl, pv[0], ts, pv[1])]
                for lbl, pv in self.schedule[d].items()}


def _schedule_frame():
    return pd.DataFrame([
        {"symbol": "SFRU26", "future": "SR3U26", "low": LOW, "mid": MID,
         "high": HIGH, "start": DATES[0], "end": DATES[3]},
        {"symbol": "SFRZ26", "future": "SR3Z26",
         "low": "SFRZ26|9575C", "mid": "SFRZ26|9600C",
         "high": "SFRZ26|9625C", "start": DATES[3], "end": DATES[5]},
    ])


def _prices(fly_prem_path):
    """low/high at fixed premia; mid premium moves the fly premium."""
    out = {}
    zlegs = {"SFRZ26|9575C": (0.30, 0.8), "SFRZ26|9600C": (0.20, 0.5),
             "SFRZ26|9625C": (0.12, 0.3)}
    for d, fp in zip(DATES, fly_prem_path):
        # fly = low - 2*mid + high  ->  mid = (low + high - fly)/2
        low, high = 0.30, 0.12
        mid = (low + high - fp) / 2.0
        out[d.date()] = {LOW: (low, 0.8), MID: (mid, 0.5),
                         HIGH: (high, 0.3), **zlegs}
    return out


class TestFlyStructureThroughEngine:
    def test_short_fly_roll_and_fees(self):
        # fly premium 0.02 -> 0.05 over holding 1: SHORT fly LOSES 0.03pts
        sched = _schedule_frame()
        prices = _prices([0.02, 0.03, 0.04, 0.05, 0.05, 0.05])
        bt, state = make_fly_backtest(
            sched, DATES, StubOptMDP(prices), contracts=1.0, side="short",
            tcost_vol_bp=0.125, show_progress=False)
        bt.run()
        cl = closed_positions_frame(bt)
        assert len(cl) == 2                      # both holdings rolled out
        t1 = cl.iloc[0]
        # gross = -(0.05 - 0.02) * 2500 = -75; fee = 2 * 4 * 0.125 * 25 = 25
        assert t1["realized_pnl"] == pytest.approx(-75.0 - 25.0)
        assert pd.Timestamp(t1["closed_at"]).date() == DATES[3].date()
        # second holding enters at the roll session and unwinds at the end
        t2 = cl.iloc[1]
        assert pd.Timestamp(t2["opened_at"]).date() == DATES[3].date()
        assert pd.Timestamp(t2["closed_at"]).date() == DATES[5].date()

    def test_long_side_mirrors_gross(self):
        sched = _schedule_frame()
        prices = _prices([0.02, 0.03, 0.04, 0.05, 0.05, 0.05])
        b_s, _ = make_fly_backtest(sched, DATES, StubOptMDP(prices),
                                   side="short", tcost_vol_bp=0.0,
                                   show_progress=False)
        b_l, _ = make_fly_backtest(sched, DATES, StubOptMDP(prices),
                                   side="long", tcost_vol_bp=0.0,
                                   show_progress=False)
        b_s.run()
        b_l.run()
        s = closed_positions_frame(b_s)["realized_pnl"].sum()
        l = closed_positions_frame(b_l)["realized_pnl"].sum()
        assert s == pytest.approx(-l)

    def test_vol_tcost_scales_fees(self):
        sched = _schedule_frame()
        prices = _prices([0.02, 0.02, 0.02, 0.02, 0.02, 0.02])
        outs = {}
        for c in (0.125, 0.25):
            bt, _ = make_fly_backtest(sched, DATES, StubOptMDP(prices),
                                      tcost_vol_bp=c, show_progress=False)
            bt.run()
            outs[c] = closed_positions_frame(bt)["realized_pnl"].sum()
        # flat premiums: PnL is pure fees; doubling tcost doubles the drag
        assert outs[0.25] == pytest.approx(2 * outs[0.125])


class TestFlyQueryRequest:
    def test_build_mdp_request_carries_all_three_legs(self):
        """Regression: option_snapshot silently received NO symbols for FLY
        (the collector didn't know low/mid/high) and the engine swallowed
        the ValueError — a full run produced zero trades."""
        q = STIRFutureOptionQuery(
            structure=STIRFutureOptionStructure.FLY,
            value=STIRFutureOptionValue.PRICE,
            structure_kwargs={"low_symbol": LOW, "mid_symbol": MID,
                              "high_symbol": HIGH},
        )
        req = q.build_mdp_request(NY.localize(
            datetime.datetime(2026, 6, 1, 17, 0)))
        assert set(req["symbols"]) == {LOW, MID, HIGH}
        assert req["endpoint"] == "option_snapshot"


class TestHedgePlumbing:
    def _bt_with_open_fly(self, deltas):
        sched = _schedule_frame()
        prices = _prices([0.02] * 6)
        # override leg deltas
        for d in prices:
            for lbl, (p, _dl) in list(prices[d].items()):
                prices[d][lbl] = (p, deltas.get(lbl, 0.0))
        bt, state = make_fly_backtest(
            sched, DATES, StubOptMDP(prices), fut_mdp=object(), hedge=True,
            hedge_threshold=0.5, show_progress=False)
        now = NY.localize(datetime.datetime(2026, 6, 1, 17, 0))
        # open the first holding manually through the engine's own machinery
        orders = bt.strategy.evaluate(now, bt)
        adds = [o for o in orders if isinstance(o, QueryOrder)
                and o.query.product == "STIRFUTUREOPTION"]
        assert adds
        from BT.position_handler import get_handler
        h = get_handler("STIRFUTUREOPTION")
        pos = h.build_position(adds[0],
                               lambda q: bt._pricer_for_query(q, now),
                               now, bt)
        bt.portfolio.positions.append(pos)
        return bt, state, now

    def test_package_delta_weights_and_quantities(self):
        # short fly weights [-1, 2, -1] on deltas (0.8, 0.5, 0.3):
        # -0.8 + 1.0 - 0.3 = -0.1
        bt, state, now = self._bt_with_open_fly(
            {LOW: 0.8, MID: 0.5, HIGH: 0.3})
        assert package_delta(bt, now) == pytest.approx(-0.1)

    def test_hedge_fires_above_threshold_and_books_linear_traffic(self):
        # deltas (0.9, 0.5, 0.1): package delta = -0.9 + 1.0 - 0.1 = 0.0 ->
        # no trigger; then (0.2, 0.5, 0.9): -0.2 + 1.0 - 0.9 = -0.1 -> no.
        # Use (0.9, 0.2, 0.1): -0.9 + 0.4 - 0.1 = -0.6 -> target +0.6 >= 0.5
        bt, state, now = self._bt_with_open_fly(
            {LOW: 0.9, MID: 0.2, HIGH: 0.1})
        nxt = NY.localize(datetime.datetime(2026, 6, 2, 17, 0))
        orders = bt.strategy.evaluate(nxt, bt)
        unwinds = [o for o in orders if isinstance(o, UnwindOrder)]
        futs = [o for o in orders if isinstance(o, QueryOrder)
                and o.query.product == "STIRFUTURE"]
        assert unwinds and futs
        fq = futs[0].query
        assert fq.structure_kwargs["contracts"] == pytest.approx(0.6)
        assert fq.structure_kwargs["risk_weights"] == [1.0]
        assert fq.structure_kwargs["symbol"] == "SR3U26"
        assert state.n_rebalances == 1
        assert state.linear_traded_contracts == pytest.approx(0.6)
        assert linear_cost_usd(state, 0.25) == pytest.approx(0.6 * 0.25 * 25)

    def test_hedge_quiet_below_threshold(self):
        bt, state, now = self._bt_with_open_fly(
            {LOW: 0.8, MID: 0.5, HIGH: 0.3})   # delta -0.1, |t| < 0.5
        nxt = NY.localize(datetime.datetime(2026, 6, 2, 17, 0))
        orders = bt.strategy.evaluate(nxt, bt)
        assert not [o for o in orders if isinstance(o, QueryOrder)
                    and o.query.product == "STIRFUTURE"]
        assert state.n_rebalances == 0
