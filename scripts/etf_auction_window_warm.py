r"""One targeted MI01 window over a real 13:00-New-York auction, for the timezone test.

The month-turn blocks run from the 24th to the 3rd. Thirty-year auctions land on
the 8th to the 14th and twenty-year auctions in the third week, so NOT ONE of the
universe's 44 auctions in the study window falls inside a warmed block - measured,
not assumed (``intraday_auction_dates.csv``). A minute-resolution auction test on
the month-turn data would therefore return nothing, and returning nothing would
look like a failed test rather than a coverage gap.

So the window is warmed on purpose. It is small - one five-day MI01 window over a
handful of long bonds - and it exists to close the timezone question with the
event the task names, at the resolution that makes 13:00 distinguishable from
13:30.

The auctioned bond itself is not required and is deliberately not relied on: Citi
lags a new auction by about eight days, and a thirty-year auction moves the whole
long end at 13:00 regardless of which CUSIP was sold.
"""

from __future__ import annotations

import argparse
import datetime
import logging
import pathlib
import sys

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("etf_auction_warm")

DATA = pathlib.Path(__file__).resolve().parents[1] / "notebooks/backtests/etf_rebalance/_data"

#: 30-year auctions, 13:00 New York, both comfortably inside Citi's MI01 retention.
DEFAULT_AUCTIONS = ["2026-08-13", "2026-05-13"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--auctions", nargs="+", default=DEFAULT_AUCTIONS)
    ap.add_argument("--bonds", type=int, default=40,
                    help="how many of the longest bonds to warm")
    args = ap.parse_args()

    from MDP.CitiVelocityExcel import memory_guard
    from MDP.CitiVelocityExcel.quotes import CitiVeloQuotes

    mb = memory_guard.assert_safe_to_connect(what="the targeted auction-window warm")
    log.info("memory gate passed at %.0f MB", mb)

    uni = pd.read_csv(DATA / "intraday_universe.csv")
    uni["maturity_date"] = pd.to_datetime(uni["maturity_date"])
    # The longest bonds are the ones a 30-year auction actually moves.
    picks = uni.sort_values("maturity_date", ascending=False).head(args.bonds)
    tags = [f"RATES.BOND.{i}.YIELD" for i in picks["isin"].astype(str)]
    log.info("warming %d tags over %d auction window(s)", len(tags), len(args.auctions))

    quotes = CitiVeloQuotes()
    total = 0
    try:
        for a in args.auctions:
            day = pd.Timestamp(a)
            # Bounds are read as UTC and stamps come back New York, so the window
            # is opened wide enough that the shift cannot clip the auction hour.
            w0 = (day - pd.Timedelta(days=2)).to_pydatetime()
            w1 = (day + pd.Timedelta(days=2)).to_pydatetime()
            for i in range(0, len(tags), 44):
                chunk = tags[i:i + 44]
                failures: dict = {}
                frame = quotes.frame(chunk, "MI01", start=w0, end=w1,
                                     price_point="CLOSE", force_refresh=True,
                                     failures=failures)
                d = pd.Series(frame.index).diff().dropna()
                log.info("auction %s chunk %d: %d rows x %d tags, min gap %s s",
                         a, i // 44, len(frame), frame.shape[1],
                         None if d.empty else d.min().total_seconds())
                total += len(frame)
                if failures:
                    log.info("  failures: %s", dict(list(failures.items())[:5]))
    finally:
        quotes.close()
        log.info("done: %d rows; Excel at %.0f MB", total,
                 memory_guard.excel_memory_mb() or -1.0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
