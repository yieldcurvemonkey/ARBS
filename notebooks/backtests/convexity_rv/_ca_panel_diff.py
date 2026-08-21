r"""Rebuilt Q20 panel against the pre-warm baseline: what moved, and why.

The previous coverage repair could assert ``published_values_moved: 0``, because
it was a pure coverage fix. This one cannot, and saying so up front is the point:

* the warm ran with ``--protect-min-depth 21``, so dates already carrying deep
  rows were deepened, which re-solves their Q20 curve; and
* the rebuild happens in a tree containing ``db95871d``, whose whole purpose was
  to move ranks 15-17 by giving the terminal instrument a node.

So the deliverable is a **quantified before/after**, split by rank, with the
ranks the fix was not supposed to touch shown to be unchanged.

Baseline: ``notebooks/data/convexity_rv/_baseline_prewarm/strat2_q20_panel.parquet``
(the Aug-19 artifact, built at a9bc31a7, which does NOT contain db95871d).
"""
from __future__ import annotations

import json
import os
import pathlib
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

REPO = pathlib.Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

DATA = REPO / "notebooks" / "data" / "convexity_rv"
BASE_F = DATA / "_baseline_prewarm" / "strat2_q20_panel.parquet"
NEW_F = DATA / "strat2_q20_panel.parquet"

RANKS = [(1, "Whites"), (5, "Reds"), (9, "Greens"), (13, "Blues"), (17, "Golds")]

base = pd.read_parquet(BASE_F)
new = pd.read_parquet(NEW_F)
for f in (base, new):
    f["date"] = pd.to_datetime(f["date"])
    f["year"] = f["date"].dt.year

print(f"baseline : {len(base):>7,} rows  {base['date'].nunique():>5,} dates  "
      f"{base['date'].min().date()} .. {base['date'].max().date()}")
print(f"rebuilt  : {len(new):>7,} rows  {new['date'].nunique():>5,} dates  "
      f"{new['date'].min().date()} .. {new['date'].max().date()}")

# ---------------------------------------------------------------------------
# 1. Coverage by colour, gate applied -- the number the brief asks for
# ---------------------------------------------------------------------------
def cov(df: pd.DataFrame, gated: bool) -> pd.DataFrame:
    d = df[df["gate_ok"]] if gated else df
    rows = []
    for y in sorted(set(new["year"]) | set(base["year"])):
        row = {"year": int(y)}
        for rank, colour in RANKS:
            row[colour] = int(d[(d["rank"] == rank) & (d["year"] == y)]["date"].nunique())
        rows.append(row)
    return pd.DataFrame(rows).set_index("year")


for gated in (False, True):
    tag = "GATE APPLIED" if gated else "all rows"
    b, n = cov(base, gated), cov(new, gated)
    print(f"\n=== dates per colour per year -- {tag} ===")
    joined = pd.concat({"before": b, "after": n, "delta": n - b}, axis=1)
    print(joined.to_string())
    if gated:
        cov_gated_after = n

# ---------------------------------------------------------------------------
# 2. What moved on rows PRESENT IN BOTH -- split by rank
# ---------------------------------------------------------------------------
KEY = ["date", "rank"]
m = base.merge(new, on=KEY, suffixes=("_b", "_n"))
print(f"\n=== rows present in both panels: {len(m):,} ===")

cols = [c for c in ("ca_bp", "ca_bp_q20", "ca_bp_settle", "swap_rate",
                    "pack_rate_q20", "max_settle_diff_bp") if f"{c}_b" in m.columns]
rows = []
for rank, colour in RANKS:
    sub = m[m["rank"] == rank]
    if sub.empty:
        continue
    r = {"rank": rank, "colour": colour, "n": len(sub)}
    for c in cols:
        d = (sub[f"{c}_n"] - sub[f"{c}_b"]).astype(float)
        r[f"{c} median"] = round(float(np.nanmedian(d)), 4)
        r[f"{c} p95|.|"] = round(float(np.nanpercentile(np.abs(d), 95)), 4)
    rows.append(r)
moved = pd.DataFrame(rows)
pd.set_option("display.width", 220, "display.max_columns", 40)
print(moved.to_string(index=False))

print("\nRanks 1-13 are not what db95871d changed; ranks 15-17 are.")

# ---------------------------------------------------------------------------
# 3. The gate condition that was binding -- did the Golds fix land?
# ---------------------------------------------------------------------------
print("\n=== settle agreement by rank (the binding gate condition) ===")
rows = []
for rank, colour in RANKS:
    b = base[base["rank"] == rank]
    n = new[new["rank"] == rank]
    rows.append({
        "rank": rank, "colour": colour,
        "before median |diff| bp": round(float(b["max_settle_diff_bp"].median()), 3),
        "after  median |diff| bp": round(float(n["max_settle_diff_bp"].median()), 3),
        "before pass rate": round(float(b["gate_settle_agrees"].mean()), 3),
        "after  pass rate": round(float(n["gate_settle_agrees"].mean()), 3),
    })
print(pd.DataFrame(rows).to_string(index=False))

summary = {
    "baseline": {"rows": int(len(base)), "dates": int(base["date"].nunique())},
    "rebuilt": {"rows": int(len(new)), "dates": int(new["date"].nunique())},
    "rows_in_both": int(len(m)),
    "coverage_gated_after": cov_gated_after.to_dict(),
}
(DATA / "ca_panel_diff_summary.json").write_text(json.dumps(summary, indent=1))
print(f"\nwrote {DATA / 'ca_panel_diff_summary.json'}")
