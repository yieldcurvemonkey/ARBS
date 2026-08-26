"""13 Saturday speeches survived the bar gate. CME SOFR is shut from Friday
17:00 ET to Sunday 18:00 ET, so that should be impossible. Either the timestamps
are not what they look like, or bars are being served for a closed market, or the
panel is reaching somewhere it should not. Find out which."""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.append(r"C:\Users\chris\clee\ARBS")
sys.path.append(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove")

import pandas as pd

import global_hawk_dove_common as G

HERE = Path(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_event_study")
G.load_bar_cache(HERE / "_snap_bars.pkl")

panel = pd.read_parquet(HERE / "event_paths.parquet")
ev = pd.read_parquet(HERE / "events.parquet")
ev["wd"] = ev["speech_ts"].apply(lambda t: pd.Timestamp(t).weekday())

print("weekend events in events.parquet:",
      ev[ev["wd"] >= 5]["wd"].value_counts().sort_index().to_dict())
surv = panel[["event_id"]].drop_duplicates()
w = ev[ev["wd"] >= 5].merge(surv, on="event_id", how="left", indicator=True)
print("survived the panel:", w.groupby("wd")["_merge"].value_counts().to_dict())

sat = panel[panel["weekday"] == 5]
print(f"\nSaturday rows in the panel: {len(sat)}, "
      f"events {sat['event_id'].nunique()}, priced rows {int(sat['price'].notna().sum())}")

for eid in sorted(sat["event_id"].unique())[:6]:
    s = sat[(sat["event_id"] == eid) & (sat["contract_rank"] == 3)].sort_values("offset_min")
    if not len(s):
        continue
    ts = pd.Timestamp(s["speech_ts"].iloc[0])
    print("=" * 74)
    print(f"event {eid}  {s['title'].iloc[0]}")
    print(f"  speech_ts {ts}  ({ts.strftime('%A')})   symbol {s['symbol'].iloc[0]}")
    n_px = int(s["price"].notna().sum())
    print(f"  priced offsets at rank 3: {n_px} / {len(s)}")
    b = G._BAR_CACHE.get((s["symbol"].iloc[0], ts.date()))
    print(f"  _day_bars on the speech date: "
          f"{'MISSING FROM CACHE' if b is None else f'{len(b)} bars'}")
    if b is not None and len(b):
        print(f"    first {b.index.min()}  last {b.index.max()}")
        print(f"    distinct closes: {b['Close'].nunique()}  volume sum: {int(b['Volume'].sum())}")
    if n_px:
        pr = s[s["price"].notna()]
        print(f"  priced offsets: {pr['offset_min'].tolist()}")
        print(f"  bar labels used: {pr['bar_label_ts'].astype(str).tolist()[:6]}")
        print(f"  stale_min: {pr['stale_min'].round(1).tolist()[:6]}")

print("=" * 74)
print("\nSunday events that DID survive:")
sun = panel[panel["weekday"] == 6]
for eid in sorted(sun["event_id"].unique())[:4]:
    s = sun[(sun["event_id"] == eid) & (sun["contract_rank"] == 3)].sort_values("offset_min")
    ts = pd.Timestamp(s["speech_ts"].iloc[0])
    pr = s[s["price"].notna()]
    print(f"  {eid} {ts} ({ts.strftime('%A %H:%M')})  priced {len(pr)}/{len(s)}  "
          f"offsets {pr['offset_min'].tolist()[:8]}")
