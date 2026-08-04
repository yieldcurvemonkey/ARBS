"""Synthetic tests: the pre-registered fade wired through QueryDrivenBacktest.

A stub MDP serves canned QL pricers per (date, label); the engine does the
portfolio/PnL bookkeeping. No network, no panels.
"""
import datetime
import sys
from pathlib import Path

import pandas as pd
import pytest
import pytz

sys.path.insert(0, str(Path(__file__).resolve().parent.parent
                       / "notebooks" / "backtests"))

from famb_fade_qdb import (       # noqa: E402
    build_signal_panel,           # noqa: F401  (import check only)
    closed_positions_frame,
    make_fade_backtest,
    opt_label,
)
from Query.STIRFutureOptions.backends.quantlib.QLSTIRFutureOptionPricer import (  # noqa: E402
    QLSTIRFutureOptionPricer,
)

NY = pytz.timezone("America/New_York")
DATES = pd.bdate_range("2026-06-01", periods=8)


def _pricer(label: str, price: float, ts: datetime.datetime):
    right = label[-1]
    strike = float(label.split("|", 1)[1][:-1]) / 100.0
    return QLSTIRFutureOptionPricer(
        symbol=label, right=right,
        underlying_symbol=label.split("|", 1)[0], strike=strike,
        quote_timestamp=ts, expiry_date=datetime.date(2026, 9, 11),
        market_price=price, model_price=price, iv_normal=0.8,
        delta=0.2 if right == "C" else -0.2, gamma=0.1, vega=0.05,
        theta=-0.01, forward=96.0, discount=1.0, meta_data={},
    )


class StubMDP:
    """price schedule: {date -> {label -> premium (price points)}}."""

    def __init__(self, schedule):
        self.schedule = schedule

    def get_pricer(self, request):
        d = request["timestamp"]
        ts = NY.localize(datetime.datetime(d.year, d.month, d.day, 17, 0))
        day = self.schedule[d]
        return {lbl: [_pricer(lbl, px, ts)] for lbl, px in day.items()}


PUT, CALL = "SFRU26|9500P", "SFRU26|9650C"
PUT2, CALL2 = "SFRZ26|9525P", "SFRZ26|9675C"


def _panel(riches, legs=None):
    legs = legs or [(PUT, CALL)] * len(riches)
    return pd.DataFrame({
        "as_of": DATES[:len(riches)], "symbol": ["SFRU26"] * len(riches),
        "put_label": [l[0] for l in legs],
        "call_label": [l[1] for l in legs],
        "rich_bp": riches,
        "holding_start": [DATES[0]] * len(riches),
    })


def _schedule(prem_pairs, legs=None):
    legs = legs or [(PUT, CALL)] * len(prem_pairs)
    out = {}
    for d, (p, c), (pl, cl) in zip(DATES, prem_pairs, legs):
        out[d.date()] = {pl: p, cl: c}
    return out


class TestFadeQDB:
    def test_lag1_entry_convergence_exit_and_pnl(self):
        # rich: signal fires from day0 (5bp >= 4); exit when rich <= 1.25
        panel = _panel([5.0, 4.8, 3.0, 1.0, 0.5, 0.4, 0.3, 0.2])
        # package premium (put+call, price pts): entry day1 = 0.10,
        # exit day3 = 0.06 -> short gains 0.04 pts = $100/contract
        sched = _schedule([(0.06, 0.06), (0.05, 0.05), (0.045, 0.035),
                           (0.03, 0.03), (0.02, 0.02), (0.02, 0.02),
                           (0.02, 0.02), (0.02, 0.02)])
        bt = make_fade_backtest(panel, StubMDP(sched), contracts=1.0,
                                fee_per_side_usd=6.25, show_progress=False)
        bt.run()
        cl = closed_positions_frame(bt)
        assert len(cl) == 1
        t = cl.iloc[0]
        assert pd.Timestamp(t["opened_at"]).date() == DATES[1].date()
        assert pd.Timestamp(t["closed_at"]).date() == DATES[3].date()
        # (0.10 - 0.06) * 2500 = $100 gross, minus 2-side fee $12.50
        assert t["realized_pnl"] == pytest.approx(100.0 - 12.50)

    def test_one_open_position_blocks_stacking(self):
        panel = _panel([6.0, 6.0, 6.0, 6.0, 6.0, 1.0, 0.5, 0.4])
        sched = _schedule([(0.05, 0.05)] * 8)
        bt = make_fade_backtest(panel, StubMDP(sched), contracts=1.0,
                                fee_per_side_usd=6.25, show_progress=False)
        bt.run()
        cl = closed_positions_frame(bt)
        # one trade opens day1; rich stays >= 1.5bp exit level until day5
        # (1.0 <= 0.25*6.0), so later signals never stack a second position
        assert len(cl) == 1
        assert pd.Timestamp(cl.iloc[0]["closed_at"]).date() == DATES[5].date()

    def test_roll_forces_exit(self):
        legs = [(PUT, CALL)] * 4 + [(PUT2, CALL2)] * 4
        panel = _panel([5.0, 5.0, 5.0, 5.0, 9.0, 9.0, 9.0, 9.0], legs=legs)
        sched = _schedule([(0.05, 0.05)] * 8, legs=legs)
        bt = make_fade_backtest(panel, StubMDP(sched), contracts=1.0,
                                fee_per_side_usd=6.25, show_progress=False)
        bt.run()
        cl = closed_positions_frame(bt)
        assert len(cl) >= 1
        # first trade must close on the roll session (day4, legs change)
        assert pd.Timestamp(cl.iloc[0]["closed_at"]).date() == DATES[4].date()

    def test_max_hold_clock(self):
        n = 8
        panel = _panel([5.0] + [4.9] * (n - 1))
        sched = _schedule([(0.05, 0.05)] * n)
        bt = make_fade_backtest(panel, StubMDP(sched), contracts=1.0,
                                max_hold=3, fee_per_side_usd=6.25,
                                show_progress=False)
        bt.run()
        cl = closed_positions_frame(bt)
        assert len(cl) >= 1
        opened = pd.Timestamp(cl.iloc[0]["opened_at"]).date()
        closed = pd.Timestamp(cl.iloc[0]["closed_at"]).date()
        held = (pd.bdate_range(opened, closed).size - 1)
        assert held == 3

    def test_label_helper(self):
        assert opt_label("SFRZ26", "P", 95.00) == "SFRZ26|9500P"
        assert opt_label("SFRZ26", "C", 96.75) == "SFRZ26|9675C"
