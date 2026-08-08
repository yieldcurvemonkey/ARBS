"""Task 31: GSQUANT vs CITIVELO source agreement — a permanent cross-check.

Two independent data paths (GS Marquee curves; Citi Velocity banked par grids)
through the same greeks code, compared per pair per overlapping date.
Disagreement is a FINDING, not a reconciliation chore — the sv study's largest
error (the parallel-vs-spread vol denominator) was caught only by two
implementations disagreeing on the same statistic.

Inputs: the GS-era greeks parquets cached by the sv daily runner
(notebooks/data/strikeless_vol/daily_runner/greeks__USD_*.parquet, 2023-07..
2026-08) and this loop's Citi screen (notebooks/data/citivelo_rv/
sv_screen_USD.parquet). Pure file comparison; no network.

Run: conda run -n stir python scripts/sv_source_agreement.py
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import glob
import pathlib
import sys

_REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

import pandas as pd

GS_GLOB = str(_REPO / "notebooks" / "data" / "strikeless_vol" / "daily_runner" / "greeks__USD_*.parquet")
CITI = _REPO / "notebooks" / "data" / "citivelo_rv" / "sv_screen_USD.parquet"

# sv pair name ("USD 10Y10Y/20Y10Y") is shared by both sides.
COLS = ["short_rate", "long_rate", "spread_bp", "daily_roll_usd", "gamma_25", "be_25"]
GS_RENAME = {"gamma_h25": "gamma_25", "breakeven_h25": "be_25"}


def main() -> None:
    gs_frames = []
    for f in sorted(glob.glob(GS_GLOB)):
        df = pd.read_parquet(f).rename(columns=GS_RENAME)
        df = df.reset_index().rename(columns={df.index.name or "index": "date"})
        gs_frames.append(df[["date", "pair"] + COLS])
    gs = pd.concat(gs_frames).drop_duplicates(subset=["date", "pair"], keep="last")

    citi = pd.read_parquet(CITI)[["date", "pair"] + COLS]
    j = gs.merge(citi, on=["date", "pair"], suffixes=("_gs", "_citi"))
    print(f"overlap: {len(j):,} (pair, date) rows, "
          f"{j['date'].min().date()}..{j['date'].max().date()}, pairs: {sorted(j['pair'].unique())}")

    rows = []
    for pair, g in j.groupby("pair"):
        rec = {"pair": pair, "n": len(g)}
        for c in COLS:
            d = g[f"{c}_citi"] - g[f"{c}_gs"]
            scale = 10_000.0 if c in ("short_rate", "long_rate") else 1.0
            rec[f"{c}_med"] = float((d * scale).median())
            rec[f"{c}_p95abs"] = float((d * scale).abs().quantile(0.95))
        rows.append(rec)
    rep = pd.DataFrame(rows)
    pd.set_option("display.width", 220)
    print("\nCITI minus GS (rates in bp; roll in $/day; gamma $/bp^2; BE bp/day):")
    print(rep.to_string(index=False, float_format=lambda x: f"{x:8.3f}"))

    out = _REPO / "notebooks" / "data" / "citivelo_rv" / "sv_source_agreement.parquet"
    j.to_parquet(out, index=False)
    print(f"\nwrote {out.name}")


if __name__ == "__main__":
    main()
