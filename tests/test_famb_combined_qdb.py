"""Synthetic test: both sleeves coexist on one engine (tag-scoped gates)."""
import datetime
import sys
from pathlib import Path

import pandas as pd
import pytest
import pytz

sys.path.insert(0, str(Path(__file__).resolve().parent.parent
                       / "notebooks" / "backtests"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from famb_combined_qdb import make_combined_backtest, split_by_sleeve  # noqa: E402
from famb_fade_qdb import closed_positions_frame  # noqa: E402
from test_famb_fade_qdb import StubMDP, _panel, _schedule  # noqa: E402

NY = pytz.timezone("America/New_York")
DATES = pd.bdate_range("2026-06-01", periods=8)
FLY_L, FLY_M, FLY_H = "SFRU26|9550C", "SFRU26|9575C", "SFRU26|9600C"


def test_carry_does_not_jam_the_fade_and_pnl_splits_by_sleeve():
    # fade: rich 5bp on day0 -> lag-1 entry day1, converge-exit at day3
    panel = _panel([5.0, 4.8, 3.0, 1.0, 0.5, 0.4, 0.3, 0.2])
    fly_sched = pd.DataFrame([{
        "symbol": "SFRU26", "future": "SR3U26", "low": FLY_L, "mid": FLY_M,
        "high": FLY_H, "start": DATES[0], "end": DATES[6]}])
    sched = _schedule([(0.06, 0.06), (0.05, 0.05), (0.045, 0.035),
                       (0.03, 0.03), (0.02, 0.02), (0.02, 0.02),
                       (0.02, 0.02), (0.02, 0.02)])
    for d in sched:                      # flat fly legs: carry PnL = fees only
        sched[d].update({FLY_L: 0.10, FLY_M: 0.07, FLY_H: 0.05})
    bt, state = make_combined_backtest(
        panel, fly_sched, StubMDP(sched), contracts_fade=1.0,
        contracts_fly=1.0, tcost_vol_bp=0.125, show_progress=False)
    bt.run()
    cl = closed_positions_frame(bt)
    sl = split_by_sleeve(cl)
    assert len(sl["fade"]) == 1          # carry position did NOT block entry
    assert len(sl["carry"]) == 1
    f = sl["fade"].iloc[0]
    # same economics as the standalone fade test: +$100 gross - $12.50 fees
    assert f["realized_pnl"] == pytest.approx(100.0 - 12.50)
    c = sl["carry"].iloc[0]
    # flat fly marks: pure round-trip fees, 2 x 4 x 0.125 x 25
    assert c["realized_pnl"] == pytest.approx(-25.0)
    assert pd.Timestamp(c["closed_at"]).date() == DATES[6].date()
