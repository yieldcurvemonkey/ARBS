"""Does the placebo match the real book on CALENDAR TIME as well as clock time?

The brief requires time-of-day and weekday matching. It does not require date
matching - but rates trended hard over 2022-2026 and the hawk/dove roster is not
evenly spread across it. If the real hawk events cluster in the tightening years
while their placebos are drawn uniformly over the whole sample, the placebo band
carries a different drift from the events it is meant to null out, and that error
runs in the direction that FLATTERS the hypothesis.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import pandas as pd

HERE = Path(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_event_study")
ev = pd.read_parquet(HERE / "events.parquet")
pl = pd.read_parquet(HERE / "placebo_events.parquet")
for d in (ev, pl):
    d["year"] = pd.to_datetime(d["date"]).dt.year
    d["yq"] = pd.to_datetime(d["date"]).dt.to_period("Q").astype(str)

print("=== year mix, ALL events ===")
a = ev["year"].value_counts(normalize=True).sort_index()
b = pl["year"].value_counts(normalize=True).sort_index()
print(pd.DataFrame({"real": a.round(3), "placebo": b.round(3),
                    "diff_pp": ((b - a) * 100).round(1)}).to_string())

for sg, lab in ((1, "HAWK"), (-1, "DOVE")):
    print(f"\n=== year mix, {lab} only ===")
    a = ev[ev["stance_sign"] == sg]["year"].value_counts(normalize=True).sort_index()
    b = pl[pl["stance_sign"] == sg]["year"].value_counts(normalize=True).sort_index()
    t = pd.DataFrame({"real": a, "placebo": b}).fillna(0)
    t["diff_pp"] = ((t["placebo"] - t["real"]) * 100).round(1)
    print(t.round(3).to_string())
    print(f"  max |year-share gap|: {t['diff_pp'].abs().max():.1f} pp")

print("\n=== how far is a placebo from its parent, in days ===")
m = pl.merge(ev[["event_id", "date"]].rename(
    columns={"event_id": "parent_event_id", "date": "parent_date"}), on="parent_event_id")
gap = (pd.to_datetime(m["date"]) - pd.to_datetime(m["parent_date"])).dt.days.abs()
print(f"  median {gap.median():.0f} d   mean {gap.mean():.0f} d   "
      f"p10/p90 {gap.quantile(0.1):.0f}/{gap.quantile(0.9):.0f} d")
print(f"  within 90 d of the parent: {(gap <= 90).mean():.1%}")
