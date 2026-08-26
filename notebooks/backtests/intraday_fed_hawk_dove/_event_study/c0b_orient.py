"""Second orientation: balanced-panel counts, day clusters, bucket cut."""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd

HERE = Path(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_event_study")
OFFSETS = [-120, -90, -60, -45, -30, -20, -15, -10, -5, 0,
           5, 10, 15, 20, 30, 45, 60, 90, 120, 180, 240, 300]

ev = pd.read_parquet(HERE / "event_paths.parquet")
pl = pd.read_parquet(HERE / "placebo_paths.parquet")

r3 = ev[ev["contract_rank"] == 3].copy()
p3 = pl[pl["contract_rank"] == 3].copy()


def summarise(d, tag):
    d = d[d["stance_sign"] != 0]
    piv = d.pivot_table(index="event_id", columns="offset_min",
                        values="d_rate_bp_from_baseline", dropna=False)
    piv = piv.reindex(columns=OFFSETS)
    full = piv.notna().all(axis=1)
    meta = d.drop_duplicates("event_id").set_index("event_id")
    print(f"--- {tag}: {len(piv)} signed events; balanced (all 22 offsets priced): {int(full.sum())}")
    bal = meta.loc[full[full].index]
    print("    balanced hawk/dove:", (bal["stance_sign"] == 1).sum(), "/", (bal["stance_sign"] == -1).sum())
    print("    balanced distinct days:", bal["date"].nunique())
    allm = meta
    print("    all-signed hawk/dove:", (allm["stance_sign"] == 1).sum(), "/", (allm["stance_sign"] == -1).sum(),
          " distinct days:", allm["date"].nunique())
    # how many priced through +240
    thru240 = piv[[o for o in OFFSETS if o <= 240]].notna().all(axis=1)
    print("    balanced through +240:", int(thru240.sum()))
    b1 = meta[meta["bucket"].abs() >= 1]
    print("    |bucket|>=1:", len(b1), " hawk/dove:", (b1["stance_sign"] == 1).sum(), "/", (b1["stance_sign"] == -1).sum())
    print("    year mix:", meta["speech_ts"].dt.year.value_counts().sort_index().to_dict())
    return piv, meta


print("=== NON-OVERLAPPING (headline) ===")
summarise(r3[~r3["is_overlapping"]], "nonoverlap")
print()
print("=== ALL EVENTS ===")
summarise(r3, "all")
print()
print("=== PLACEBO ===")
summarise(p3, "placebo")
print()

# day clustering: events per day
u = r3[(~r3["is_overlapping"]) & (r3["stance_sign"] != 0)].drop_duplicates("event_id")
print("non-overlap signed: events per day distribution:")
print(u.groupby("date").size().value_counts().sort_index().to_string())
print()
# do hawk and dove share days?
g = u.groupby("date")["stance_sign"].nunique()
print("days carrying BOTH a hawk and a dove:", int((g > 1).sum()))
print()
print("placebo days reused:")
pu = p3[p3["stance_sign"] != 0].drop_duplicates("event_id")
print("  placebo signed events:", len(pu), " distinct days:", pu["date"].nunique(),
      " max events/day:", pu.groupby("date").size().max())
