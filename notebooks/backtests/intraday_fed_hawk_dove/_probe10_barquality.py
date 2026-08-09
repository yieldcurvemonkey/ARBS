"""Probe 10: are the 1440-bar days real minute data, or a padded grid?

A day that returns exactly 24*60 bars for an illiquid contract is suspicious. If
those bars are forward-filled, the gate accepts them, the backtest prices off
them, and the P&L is noise dressed as data. Distinguish by looking at how many
DISTINCT prices a day actually contains and how long the flat runs are.
"""

from __future__ import annotations

import sys
import io
import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\chris\clee\ARBS-gcb")

import numpy as np
import pandas as pd
import pytz

from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP, _normalize_symbol, _to_barchart_symbol

LDN = pytz.timezone("Europe/London")
TOR = pytz.timezone("America/Toronto")
NY = pytz.timezone("America/New_York")

CASES = [
    ("TVZ23", datetime.date(2023, 6, 14), LDN, "TV 1440-bar day"),
    ("TVZ25", datetime.date(2025, 6, 11), LDN, "TV sparse day"),
    ("RGZ21", datetime.date(2021, 6, 15), TOR, "RG 1440-bar day"),
    ("RGZ25", datetime.date(2025, 6, 11), TOR, "RG normal day"),
    ("IMZ21", datetime.date(2021, 6, 15), LDN, "IM 2021"),
    ("IMZ23", datetime.date(2023, 6, 14), LDN, "IM 2023"),
    ("IMZ25", datetime.date(2025, 6, 11), LDN, "IM 2025"),
    ("SQZ25", datetime.date(2025, 6, 11), NY, "SR3 control"),
    ("J8Z25", datetime.date(2025, 6, 11), LDN, "J8 control"),
]


def main():
    mdp = STIRFutureMDP(source="BARCHART_STIRF-RL")
    fetcher = mdp._get_barchart_fetcher(required_concurrency=3)
    rows = []
    for sym, day, tz, label in CASES:
        bc = _to_barchart_symbol(_normalize_symbol(sym) or sym)
        per = fetcher.barchart_timeseries_api(
            barchart_symbols=[bc],
            start_date=tz.localize(datetime.datetime(day.year, day.month, day.day, 0, 0)),
            end_date=tz.localize(datetime.datetime(day.year, day.month, day.day, 23, 59)),
            interval=1, one_df=False, show_tqdm=False,
        ) or {}
        df = None
        for _k, v in per.items():
            if v is not None and len(v):
                df = v
                break
        if df is None:
            print(f"  {label:22s} {sym:7s} {day}  NO BARS")
            continue
        c = df["Close"].astype(float)
        # longest run of an unchanged price
        chg = (c.diff() != 0).cumsum()
        longest_flat = int(chg.value_counts().max())
        vol = "Volume" in df.columns
        zero_vol = int((df["Volume"].astype(float) == 0).sum()) if vol else -1
        rows.append(dict(label=label, symbol=sym, date=day, bars=len(df),
                         distinct_px=int(c.nunique()),
                         pct_unchanged=round(float((c.diff() == 0).mean()), 3),
                         longest_flat_run=longest_flat,
                         zero_volume_bars=zero_vol,
                         rng_bp=round(float((c.max() - c.min()) * 100), 2)))
        print(f"  {label:22s} {sym:7s} bars={len(df):5d} distinct={c.nunique():4d} "
              f"unchanged={float((c.diff()==0).mean()):.1%} longest_flat={longest_flat:4d} "
              f"zero_vol={zero_vol:5d} range={float((c.max()-c.min())*100):.1f}bp", flush=True)

    out = pd.DataFrame(rows)
    print()
    print(out.to_string(index=False))
    print()
    print("Read: a real session has many distinct prices and few zero-volume bars.")
    print("A padded grid shows ~1440 bars, few distinct prices, long flat runs and/or all-zero volume.")


if __name__ == "__main__":
    main()
