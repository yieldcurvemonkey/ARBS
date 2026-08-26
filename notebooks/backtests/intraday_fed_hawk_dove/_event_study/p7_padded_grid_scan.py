"""How much of the warmed cache is a PADDED GRID rather than data?

Barchart fabricates a full 24x60 minute grid carrying ONE price on days an
instrument did not trade (documented in gate_events: TVZ23 2023-06-14, RGZ21
2021-06-15). Those bars pass every timestamp and staleness check and then book a
guaranteed ZERO move, which shrinks every standard error downstream.

This scans the whole warmed cache so the filter is chosen on measured evidence,
not on the one Saturday that happened to be looked at.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.append(r"C:\Users\chris\clee\ARBS")
sys.path.append(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove")

import numpy as np
import pandas as pd

import global_hawk_dove_common as G

HERE = Path(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_event_study")
n = G.load_bar_cache(HERE / "_snap_bars.pkl")
print(f"cache: {n} symbol-days")

rows = []
for (sym, day), b in G._BAR_CACHE.items():
    if b is None or len(b) == 0:
        rows.append({"sym": sym, "day": day, "n": 0, "nuniq": 0, "vuniq": 0,
                     "rng_bp": np.nan, "wd": day.weekday()})
        continue
    rows.append({"sym": sym, "day": day, "n": len(b),
                 "nuniq": int(b["Close"].nunique()),
                 "vuniq": int(b["Volume"].nunique()),
                 "rng_bp": float((b["High"].max() - b["Low"].min()) * 100),
                 "wd": day.weekday()})
d = pd.DataFrame(rows)
print(f"\nframes: {len(d)}   empty {int((d['n']==0).sum())}")

flat = d[(d["n"] > 0) & (d["nuniq"] < 2)]
print(f"\nFLAT frames (n>0 and <2 distinct closes): {len(flat)} "
      f"({len(flat)/max(len(d),1):.1%} of the cache)")
print("  by weekday (Mon=0):", flat["wd"].value_counts().sort_index().to_dict())
print("  bar counts:", flat["n"].value_counts().head(6).to_dict())
print("  constant Volume too:", int((flat["vuniq"] <= 1).sum()), "of", len(flat))
print("  by year:", flat["day"].apply(lambda x: x.year).value_counts().sort_index().to_dict())

full = d[d["n"] == 1440]
print(f"\nframes with exactly 1440 bars (a complete 24x60 grid): {len(full)}")
print("  distinct-close distribution:", full["nuniq"].value_counts().head(8).to_dict())
print("  by weekday:", full["wd"].value_counts().sort_index().to_dict())
rich = full[full["nuniq"] > 2]
print(f"  1440-bar frames with >2 distinct closes (would be WRONGLY dropped by a "
      f"bar-count rule): {len(rich)}")
if len(rich):
    print(rich.head(8).to_string(index=False))

print("\nnear-flat but not flat (2-4 distinct closes, n>200):")
nf = d[(d["n"] > 200) & (d["nuniq"].between(2, 4))]
print(f"  {len(nf)} frames; by weekday {nf['wd'].value_counts().sort_index().to_dict()}; "
      f"median range {nf['rng_bp'].median():.2f} bp")
print(nf.sort_values("n", ascending=False).head(8).to_string(index=False))

print("\nrange (High-Low over the day, bp) percentiles for NON-flat weekday frames:")
wk = d[(d["wd"] < 5) & (d["n"] > 0) & (d["nuniq"] >= 2)]
print("  ", np.percentile(wk["rng_bp"].dropna(), [1, 5, 25, 50, 75]).round(2))

print("\nVERDICT INPUTS")
print(f"  rule 'Close.nunique() < 2' would void {len(flat)} frames")
print(f"  of those, on a weekday: {int((flat['wd']<5).sum())}   "
      f"on a weekend: {int((flat['wd']>=5).sum())}")
print(f"  it would NOT void any frame with real intraday variation, by construction")
