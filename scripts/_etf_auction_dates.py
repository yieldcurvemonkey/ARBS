"""Which named 13:00-New-York auctions fall inside the MI01 blocks, and which do not.

A test that reports "no auction days found" when the layer simply was not warmed
over auction days is a coverage artefact wearing a failed test's clothes, so this
is settled from the calendar BEFORE the test is run.
"""

import datetime
import pathlib
import sys

import pandas as pd

REPO = pathlib.Path(__file__).resolve().parents[1]
DATA = REPO / "notebooks/backtests/etf_rebalance/_data"
sys.path.insert(0, str(REPO))
from scripts.etf_intraday_backfill import month_turn_blocks  # noqa: E402
from RVUtils.ETFRebalance.bond_panel import reference_frame  # noqa: E402

uni = pd.read_csv(DATA / "intraday_universe.csv")
ref = reference_frame()
ref["cusip"] = ref["cusip"].astype(str).str.upper()
mine = ref[ref["cusip"].isin(uni["cusip"].astype(str).str.upper())].copy()
mine["auction_date"] = pd.to_datetime(mine["auction_date"], errors="coerce").dt.date
mine = mine.dropna(subset=["auction_date"])
mine = mine[(mine["auction_date"] >= datetime.date(2021, 1, 1))
            & (mine["auction_date"] <= datetime.date(2026, 8, 20))]

blocks = month_turn_blocks(datetime.date(2021, 1, 1), datetime.date(2026, 8, 20))
mine["in_block"] = [any(b0 <= d <= b1 for b0, b1 in blocks) for d in mine["auction_date"]]
print(f"auctions of universe bonds in window: {len(mine)}; "
      f"inside an MI01 month-turn block: {int(mine['in_block'].sum())}")
print(mine.groupby([mine['auction_date'].map(lambda d: d.day), "in_block"])
      .size().rename("n").reset_index().head(30).to_string(index=False))
print("\nmost recent auctions (any oi):")
print(mine.sort_values("auction_date", ascending=False)
      [["cusip", "oi", "auction_date", "maturity_date", "in_block"]]
      .head(10).to_string(index=False))
mine.to_csv(DATA / "intraday_auction_dates.csv", index=False)
print("\nwrote intraday_auction_dates.csv")
