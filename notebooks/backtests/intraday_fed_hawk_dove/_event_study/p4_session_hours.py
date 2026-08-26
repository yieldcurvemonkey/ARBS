"""Which clock hours does a `_day_bars` frame actually cover?

~190 events in this book are stamped 16:00-20:00 ET and ~60 are stamped
00:00-07:00. The CME SOFR session runs 18:00 ET to 17:00 ET the next day, so a
19:00 ET speech sits at the START of the NEXT trade date. If Barchart stamps
those bars on the next CALENDAR day, then `_day_bars(symbol, speech_date)` holds
nothing for an evening speech and the panel must reach into day+1 - which it
already fetches, but only if the concat is actually doing the work.
"""
from __future__ import annotations

import datetime
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.append(r"C:\Users\chris\clee\ARBS")
sys.path.append(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove")

import pandas as pd
import pytz

from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP
import global_hawk_dove_common as G

TZ = pytz.timezone("America/New_York")
mdp = STIRFutureMDP(source="BARCHART_STIRF-RL")
fetcher = mdp._get_barchart_fetcher(required_concurrency=4)

for sym, day in [("SR3M26", datetime.date(2025, 11, 19)),   # a Wednesday
                 ("SR3M26", datetime.date(2025, 11, 21)),   # a Friday
                 ("SR3U24", datetime.date(2024, 2, 5))]:    # a Monday
    b = G._day_bars(fetcher, sym, day, TZ)
    print("=" * 70)
    print(f"{sym} {day} ({day.strftime('%a')}): {len(b)} bars")
    if len(b):
        print(f"  first {b.index.min()}   last {b.index.max()}")
        h = b.index.hour.value_counts().sort_index()
        print(f"  bars per clock hour: {h.to_dict()}")
        covered = sorted(h.index)
        print(f"  hours covered: {covered}")
        gaps = [x for x in range(24) if x not in set(covered)]
        print(f"  hours with NO bars: {gaps}")
print("=" * 70)
print("FETCH_FAILURES:", G.FETCH_FAILURES)
