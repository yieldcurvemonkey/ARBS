"""Coverage / liquidity audit of the SR3 contract panel before anything is built on it.

Prints, per year: sessions, how deep the *tradeable* strip is, and the volume/OI
profile by strip slot. The usable sample start is a liquidity question, not a
feed question - SR3 listed in 2018 but the back of the strip did not trade.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import numpy as np
import pandas as pd

DATA = REPO / "notebooks" / "data" / "sfr_fly_meanrev"

pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 40)

panel = pd.read_parquet(DATA / "contracts.parquet")
panel["as_of"] = pd.to_datetime(panel["as_of"])
panel["imm_start"] = pd.to_datetime(panel["imm_start"])
print(f"rows {len(panel):,}  sessions {panel['as_of'].nunique():,}  "
      f"contracts {panel['code'].nunique()}")
print(f"window {panel['as_of'].min().date()} -> {panel['as_of'].max().date()}")

# strip slot = rank of imm_start among contracts not yet accruing, per date
live = panel[panel["imm_start"] > panel["as_of"]].copy()
live["slot"] = live.groupby("as_of")["imm_start"].rank(method="first").astype(int)
print(f"\nnot-yet-accruing rows: {len(live):,}")

print("\n=== depth of the not-yet-accruing strip, by year ===")
depth = live.groupby([live["as_of"].dt.year, "as_of"])["slot"].max().rename("depth")
print(depth.groupby(level=0).agg(["count", "min", "median", "max"]).to_string())

s16 = live[live["slot"] <= 16]
print("\n=== settle sanity ===")
print(s16["settle"].describe().to_string())
print(f"settles outside [90, 102]: {int(((s16['settle'] < 90) | (s16['settle'] > 102)).sum())}")

print("\n=== median OPEN INTEREST by year x slot ===")
oi = s16.pivot_table(index=s16["as_of"].dt.year, columns="slot",
                     values="open_interest", aggfunc="median")
print(oi.round(0).to_string())

print("\n=== median VOLUME by year x slot ===")
vol = s16.pivot_table(index=s16["as_of"].dt.year, columns="slot",
                      values="volume", aggfunc="median")
print(vol.round(0).to_string())

print("\n=== share of (date,slot) rows with volume == 0, by year x slot ===")
z = s16.assign(zero=(s16["volume"].fillna(0) == 0).astype(float)).pivot_table(
    index=s16["as_of"].dt.year, columns="slot", values="zero", aggfunc="mean")
print((z * 100).round(0).to_string())

print("\n=== stale settles: share of (date,slot) with unchanged settle vs prior date ===")
s16 = s16.sort_values(["code", "as_of"])
s16["dsettle"] = s16.groupby("code")["settle"].diff()
st = s16.assign(stale=(s16["dsettle"].abs() < 1e-12).astype(float)).pivot_table(
    index=s16["as_of"].dt.year, columns="slot", values="stale", aggfunc="mean")
print((st * 100).round(0).to_string())

print("\n=== dates with a complete 16-deep strip, by year ===")
n_by_date = live[live["slot"] <= 16].groupby("as_of")["slot"].nunique()
full = (n_by_date == 16)
print(full.groupby(full.index.year).agg(["sum", "count"]).rename(
    columns={"sum": "full16", "count": "sessions"}).to_string())
