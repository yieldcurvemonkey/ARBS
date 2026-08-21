"""Probe what Citi actually serves for ``RATES.BOND.*`` intraday, before spending Excel on it.

Two things the repo has measured for CURVE tags and never for BOND tags:

* ``HOURLY`` at <= 120 days serves true 60-minute data. That was measured on
  ``RATES.OIS.*``; the HOURLY tag cache holds exactly two parquets, both OIS. A
  bond may not serve HOURLY at all.
* Intraday history reaches years back. Depth is per ``(bond, value)`` and the
  bond stack's own warm script found ``DURATION``/``SPREAD_TSY`` stopping dead at
  2020-04-01 where ``PRICE``/``YIELD`` did not, so ``ASS_SOFR`` cannot be assumed.

Nothing here writes to the tag cache (``cache=False``): a probe that persisted a
silently downsampled block would poison the layer it exists to protect.
"""

from __future__ import annotations

import argparse
import datetime
import logging
import sys

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("etf_probe")

VALUES = ("YIELD", "PRICE", "ASS_SOFR")


def tag(isin: str, value: str) -> str:
    return f"RATES.BOND.{isin}.{value}"


def describe(name: str, s: pd.Series) -> dict:
    if s is None or s.empty:
        return {"series": name, "rows": 0}
    d = pd.Series(s.index).diff().dropna()
    hours = pd.Series(s.index).dt.hour
    return {
        "series": name,
        "rows": int(s.size),
        "first": s.index.min(),
        "last": s.index.max(),
        "min_gap_min": None if d.empty else d.min().total_seconds() / 60.0,
        "med_gap_min": None if d.empty else d.median().total_seconds() / 60.0,
        "max_gap_h": None if d.empty else d.max().total_seconds() / 3600.0,
        "hour_lo": int(hours.min()),
        "hour_hi": int(hours.max()),
        "has_15": bool((hours == 15).any()),
        "has_16": bool((hours == 16).any()),
        "val_first": float(s.iloc[0]),
        "val_last": float(s.iloc[-1]),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["shape", "floor"], required=True)
    ap.add_argument("--isins", nargs="+", required=True)
    ap.add_argument("--freq", default="HOURLY")
    ap.add_argument("--values", nargs="+", default=list(VALUES))
    ap.add_argument("--days", type=float, default=90.0)
    ap.add_argument("--end", default=None, help="YYYY-MM-DD; default = today")
    ap.add_argument("--probe-years", nargs="+", type=int,
                    default=[2025, 2023, 2021, 2019, 2017],
                    help="floor stage: coarse walk-back years")
    ap.add_argument("--ends", nargs="+", default=None,
                    help="floor stage: explicit YYYY-MM-DD window ends, overriding --probe-years")
    args = ap.parse_args()

    from MDP.CitiVelocityExcel import memory_guard
    from MDP.CitiVelocityExcel.quotes import CitiVeloQuotes

    mb = memory_guard.assert_safe_to_connect(what="the ETF intraday probe")
    log.info("memory gate passed at %.0f MB", mb)

    end = pd.Timestamp(args.end) if args.end else pd.Timestamp.now().normalize()
    quotes = CitiVeloQuotes(cache=False)   # NEVER persist a probe
    rows = []
    try:
        if args.stage == "shape":
            start = end - pd.Timedelta(days=args.days)
            tags = [tag(i, v) for i in args.isins for v in args.values]
            failures: dict = {}
            log.info("shape: %s %s -> %s, %d tags", args.freq, start.date(), end.date(), len(tags))
            frame = quotes.frame(tags, args.freq, start=start.to_pydatetime(),
                                 end=end.to_pydatetime(), failures=failures)
            log.info("returned %d rows x %d cols", len(frame), frame.shape[1])
            for t in tags:
                if t in frame.columns:
                    rows.append(describe(t, frame[t].dropna()))
                else:
                    rows.append({"series": t, "rows": 0,
                                 "failure": failures.get(t, "(absent, no reason given)")})
            if not frame.empty:
                hours = pd.Series(frame.index).dt.hour.value_counts().sort_index()
                log.info("HOUR-OF-STAMP histogram (all rows):\n%s", hours.to_string())
                mins = pd.Series(frame.index).dt.minute.value_counts().sort_index()
                log.info("MINUTE-OF-STAMP histogram (top 8):\n%s",
                         mins.sort_values(ascending=False).head(8).to_string())
        else:
            ends = ([pd.Timestamp(e) for e in args.ends] if args.ends
                    else [pd.Timestamp(year=y, month=6, day=15) for y in args.probe_years])
            for w_end in ends:
                year = w_end.date().isoformat()
                w_start = w_end - pd.Timedelta(days=args.days)
                tags = [tag(i, v) for i in args.isins for v in args.values]
                failures = {}
                frame = quotes.frame(tags, args.freq, start=w_start.to_pydatetime(),
                                     end=w_end.to_pydatetime(), failures=failures)
                for t in tags:
                    if t in frame.columns:
                        d = describe(t, frame[t].dropna())
                    else:
                        d = {"series": t, "rows": 0,
                             "failure": failures.get(t, "(absent, no reason given)")}
                    d["probe_year"] = year
                    rows.append(d)
                served = [t for t in tags if t in frame.columns and frame[t].notna().any()]
                log.info("floor probe %s (%s..%s): %d/%d tags served, %d rows",
                         year, w_start.date(), w_end.date(), len(served), len(tags), len(frame))
    finally:
        quotes.close()

    out = pd.DataFrame(rows)
    pd.set_option("display.width", 220)
    print(out.to_string(index=False))
    log.info("Excel now at %.0f MB", memory_guard.excel_memory_mb() or -1.0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
