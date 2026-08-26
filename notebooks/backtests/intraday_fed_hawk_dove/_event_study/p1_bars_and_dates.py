"""Probe: raw bar frame shape, FOMC decision-date semantics, CPI/NFP themes."""
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

from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP
import global_hawk_dove_common as G
import fomc_extras as FX

print("=== FOMC decision dates from central_bank_date_map ===")
md = FX.fomc_decision_dates()
md24 = [d for d in md if d.year == 2024]
print("2024 from map:", md24)
print("2024 TRUE decision dates:", ["2024-01-31", "2024-03-20", "2024-05-01", "2024-06-12",
                                    "2024-07-31", "2024-09-18", "2024-11-07", "2024-12-18"])
md25 = [d for d in md if d.year == 2025]
print("2025 from map:", md25)
print("range:", md[0], "->", md[-1], " n:", len(md))

print()
print("=== G.decision_dates(FED) ===")
dd = G.decision_dates(G.CB_CONFIGS["FED"])
print("2024:", [d for d in dd if d.year == 2024])

print()
print("=== cpi/nfp themes ===")
cn = pd.read_parquet(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_driver_analysis\cpi_nfp_raw.parquet")
print(cn["Theme"].value_counts())
print(cn.groupby("Theme")["Date"].agg(["min", "max"]))
print("titles per theme:")
for t, g in cn.groupby("Theme"):
    print(" ", t, sorted(g["Title"].unique())[:10])

print()
print("=== a raw day-bar frame ===")
mdp = STIRFutureMDP(source="BARCHART_STIRF-RL")
fetcher = mdp._get_barchart_fetcher(required_concurrency=6)
tz = pytz.timezone("America/New_York")
day = datetime.date(2025, 11, 20)
bars = G._day_bars(fetcher, "SR3Z25", day, tz)
print("shape:", bars.shape)
print("cols:", list(bars.columns))
print("index dtype:", bars.index.dtype, " tz:", getattr(bars.index, "tz", None))
print(bars.head(5).to_string())
print("...")
print(bars.loc["2025-11-20 09:55":"2025-11-20 10:05"].to_string())
gaps = pd.Series(bars.index).diff().dt.total_seconds().div(60).value_counts().head(10)
print("minute gap histogram:\n", gaps)
print("FETCH_FAILURES:", G.FETCH_FAILURES)

print()
print("=== rank map check ===")
for n in range(1, 6):
    print(n, G.nth_quarterly_contract("SR3", day, n))
