"""Is a MULTI-DAY barchart fetch bar-for-bar identical to the per-day `_day_bars`?

If yes the warm can fetch a month at a time instead of a day at a time (~20x
fewer round trips). If no - Barchart downsamples by requested SPAN, which this
repo has been burned by before - the warm must stay on `_day_bars`.

Known-answer test: `_day_bars` for three separate days is the reference, because
that is the exact function the panel is required to use.
"""
from __future__ import annotations

import datetime
import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.append(r"C:\Users\chris\clee\ARBS")
sys.path.append(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove")

import pandas as pd
import pytz

from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP, _normalize_symbol, _to_barchart_symbol
import global_hawk_dove_common as G

TZ = pytz.timezone("America/New_York")


def span_bars(fetcher, symbol: str, d0: datetime.date, d1: datetime.date) -> pd.DataFrame:
    start = TZ.localize(datetime.datetime(d0.year, d0.month, d0.day, 0, 0))
    end = TZ.localize(datetime.datetime(d1.year, d1.month, d1.day, 23, 59))
    bc = _to_barchart_symbol(_normalize_symbol(symbol) or symbol)
    per = fetcher.barchart_timeseries_api(
        barchart_symbols=[bc], start_date=start, end_date=end,
        interval=1, one_df=False, show_tqdm=False) or {}
    for _k, v in per.items():
        if v is not None and len(v):
            df = v.copy()
            if getattr(df.index, "tz", None) is not None:
                df.index = df.index.tz_convert(TZ)
            return df
    return pd.DataFrame()


def main() -> None:
    mdp = STIRFutureMDP(source="BARCHART_STIRF-RL")
    fetcher = mdp._get_barchart_fetcher(required_concurrency=6)

    cases = [
        ("SR3M26", datetime.date(2025, 11, 17), datetime.date(2025, 11, 21)),   # liquid rank ~3
        ("SR3Z26", datetime.date(2025, 3, 3), datetime.date(2025, 3, 7)),       # further out
        ("SR3H26", datetime.date(2024, 6, 10), datetime.date(2024, 7, 12)),     # a MONTH span
    ]
    ok_all = True
    for sym, d0, d1 in cases:
        print("=" * 70)
        print(f"{sym}  {d0} -> {d1}")
        wide = span_bars(fetcher, sym, d0, d1)
        print(f"  span fetch: {len(wide)} bars, "
              f"{wide.index.min() if len(wide) else '-'} -> {wide.index.max() if len(wide) else '-'}")
        days = pd.bdate_range(d0, d1).date
        for day in days:
            ref = G._day_bars(fetcher, sym, day, TZ)
            sub = wide[wide.index.date == day] if len(wide) else pd.DataFrame()
            same_n = len(ref) == len(sub)
            if len(ref) and len(sub) and same_n:
                same_ix = ref.index.equals(sub.index)
                cols = ["Open", "High", "Low", "Close", "Volume"]
                same_v = bool((ref[cols].to_numpy() == sub[cols].to_numpy()).all())
            else:
                same_ix = same_v = False
            flag = "OK " if (same_n and same_ix and same_v) else "DIFF"
            if flag == "DIFF":
                ok_all = False
            print(f"    {day}  day_bars={len(ref):>4}  span_slice={len(sub):>4}  "
                  f"n={same_n} idx={same_ix} vals={same_v}  {flag}")
            if flag == "DIFF" and len(ref) and len(sub):
                miss = ref.index.difference(sub.index)
                extra = sub.index.difference(ref.index)
                print(f"        in day_bars only: {len(miss)}  in span only: {len(extra)}")
                if len(miss):
                    print(f"        e.g. {list(miss[:5])}")
    print("=" * 70)
    print("VERDICT:", "span fetch is IDENTICAL - safe to batch" if ok_all
          else "span fetch DIFFERS - must stay on _day_bars per day")
    print("FETCH_FAILURES:", G.FETCH_FAILURES)


if __name__ == "__main__":
    main()
