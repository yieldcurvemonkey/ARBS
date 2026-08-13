"""R0 / Y-side probe 7: verify the SR3 single-digit-year resolution and the
"first 12 quarterly outrights" set, empirically, from the cached per-contract data.

Evidence sought:
  * SR3H6 (Mar-2026 contract) trades early in the sample and stops around its
    2026-06-16 last trading day -- if the digit 6 meant 2036 this could not happen.
  * The first-12 set, printed for the first and last session in the sample.
"""
import glob, os, sys
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_y_mbo import parse_outright, QUARTERLY_MONTHS, sr3_first_n_quarterlies, CACHE

files = sorted(glob.glob(os.path.join(CACHE, "sr3", "*.parquet")))
print("cached sr3 day files:", len(files))
df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
df["session_date"] = pd.to_datetime(df["session_date"])
print("sessions:", df["session_date"].min().date(), "->", df["session_date"].max().date(),
      " n_sessions:", df["session_date"].nunique())

meta = pd.DataFrame([(s, *(parse_outright(s, 2026) or (None, None, None)))
                     for s in df["sym"].unique()],
                    columns=["sym", "root", "yr", "mo"]).dropna()
meta["quarterly"] = meta["mo"].isin(QUARTERLY_MONTHS)
print("\ndistinct sr3 outrights in cache:", len(meta),
      " quarterly:", int(meta["quarterly"].sum()))

# --- H6 lifecycle ---
for s in ["SR3H6", "SR3M6", "SR3H9", "SR3M9"]:
    sub = df[df["sym"] == s]
    if len(sub) == 0:
        print(f"  {s}: never traded in cache")
        continue
    dd = sub.groupby("session_date")["gross_volume"].sum()
    print(f"  {s}: {len(dd)} sessions, first {dd.index.min().date()} last {dd.index.max().date()}, "
          f"total {int(dd.sum()):,}")
    print("      tail:", {str(k.date()): int(v) for k, v in dd.tail(4).items()})

# --- first-12 set on first and last session ---
sel = sr3_first_n_quarterlies(df)
for sess in [df["session_date"].min(), df["session_date"].max()]:
    s = sel[sel["session_date"] == sess]
    syms = sorted(s["sym"].unique(),
                  key=lambda x: (parse_outright(x, 2026)[1], parse_outright(x, 2026)[2]))
    v = s.groupby("sym")["gross_volume"].sum()
    print(f"\nfirst-12 on {pd.Timestamp(sess).date()}: {len(syms)}")
    for y in syms:
        print(f"   {y}  {parse_outright(y,2026)[1]}-{parse_outright(y,2026)[2]:02d}  vol={int(v.get(y,0)):,}")

tot_all = df["gross_volume"].sum()
tot_sel = sel["gross_volume"].sum()
print(f"\nfirst-12 keeps {tot_sel:,} of {tot_all:,} SR3 outright contracts ({tot_sel/tot_all:.2%})")

# what got dropped
dropped = df.merge(sel[["sym", "session_date"]].drop_duplicates(),
                   on=["sym", "session_date"], how="left", indicator=True)
dropped = dropped[dropped["_merge"] == "left_only"]
dv = dropped.groupby("sym")["gross_volume"].sum().sort_values(ascending=False)
print("dropped contracts by volume (top 12):")
print(dv.head(12).to_string())
