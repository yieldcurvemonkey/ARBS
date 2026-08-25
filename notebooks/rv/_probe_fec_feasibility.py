"""Feasibility probe for the Fedspeak event-conditioning study.

Three load-bearing assumptions, checked before any of them is built on:
  1. the Fed sentiment index can be evaluated on a DAILY grid (a weekly index
     cannot move inside a 3-day event window, which would kill Study A's x);
  2. the priced meeting step is buildable offline over 2021-2026;
  3. a communication-event calendar exists offline for that window.
"""
from __future__ import annotations

import datetime
import io
import pathlib
import sys
import time

import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
for p in (str(HERE), str(REPO)):
    if p not in sys.path:
        sys.path.insert(0, p)

pd.set_option("display.width", 200)


def line(t):
    print("\n" + "=" * 74 + f"\n{t}\n" + "=" * 74, flush=True)


# ---------------------------------------------------------------- 1. daily sentiment
line("1. can the sentiment index run on a DAILY grid?")
import fed_sentiment_lead_data as L  # noqa: E402

cfg = L.LeadConfig()
scores = L.load_fed_scores(cfg)
print(f"JPM FED rows {len(scores)}, date {scores['date'].min().date()}..{scores['date'].max().date()}")
daily = pd.bdate_range("2021-01-01", "2026-08-21")
t0 = time.time()
sd = L.sentiment_index(scores, daily, cfg, point_in_time=True)
print(f"daily PIT sentiment: {sd.shape} in {time.time()-t0:.1f}s, "
      f"{int(sd['sentiment'].notna().sum())} non-NaN")
ok = sd["sentiment"].dropna()
print(f"  finite span {ok.index.min().date()}..{ok.index.max().date()}")
d1 = ok.diff().abs()
print(f"  daily |change|: nonzero on {int((d1 > 1e-12).sum())} of {len(d1)-1} days "
      f"({100*(d1 > 1e-12).mean():.1f}%), median {d1.median():.4f}, max {d1.max():.4f}")
print("  -> a 3-day event window CAN move it" if (d1 > 1e-12).mean() > 0.3
      else "  -> WARNING: mostly flat day to day")

import fedlock_data as F  # noqa: E402

fl, _ = F.load_speeches()
fb = F.to_score_book(fl, score_column="m")
t0 = time.time()
sdf = L.sentiment_index(fb, daily, cfg, point_in_time=False)
print(f"daily FedLock sentiment: {int(sdf['sentiment'].notna().sum())} non-NaN "
      f"in {time.time()-t0:.1f}s")

# ---------------------------------------------------------------- 2. meeting step
line("2. the priced meeting step, offline")
from RVUtils.MeetingProb import zq_settle_panel, meeting_ladder  # noqa: E402
from SDRUtils.analytics.fomc import load_fomc_schedule  # noqa: E402

_M = "FGHJKMNQUVXZ"
syms = [f"ZQ{c}{y}" for y in range(20, 28) for c in _M]
t0 = time.time()
zq = zq_settle_panel(syms)
fomc = load_fomc_schedule("USD-SOFR-1D")
print(f"ZQ panel {zq.shape} {zq.index.min().date()}..{zq.index.max().date()} "
      f"in {time.time()-t0:.1f}s;  FOMC registry {len(fomc)} rows "
      f"{fomc['effective_date'].min().date()}..{fomc['effective_date'].max().date()}")

for d in ("2021-02-01", "2023-06-15", "2026-08-21"):
    lad = meeting_ladder(pd.Timestamp(d).date(), zq, fomc)
    tag = ", ".join(f"{m.effective}:{m.jump_bp:+.2f}" + ("*" if m.stale else "")
                    for m in lad[:3])
    print(f"  {d}: {len(lad)} meetings   {tag}")

probe = pd.bdate_range("2021-02-01", "2026-08-21")[::20]
t0 = time.time()
n_empty = n_stale = 0
rows = []
for d in probe:
    lad = meeting_ladder(d.date(), zq, fomc)
    if not lad:
        n_empty += 1
        continue
    live = [m for m in lad if not m.stale]
    n_stale += len(lad) - len(live)
    if len(live) >= 2:
        rows.append({"date": d, "step1": live[0].jump_bp, "step2": live[1].jump_bp,
                     "n": len(live)})
el = time.time() - t0
print(f"  {len(probe)} probe dates in {el:.1f}s ({1000*el/len(probe):.0f} ms/date); "
      f"{n_empty} empty, {n_stale} stale legs dropped, {len(rows)} usable")
S = pd.DataFrame(rows).set_index("date")
print(f"  step1+step2 (bp): mean {(S.step1+S.step2).mean():+.2f}, "
      f"sd {(S.step1+S.step2).std():.2f}, "
      f"span {S.index.min().date()}..{S.index.max().date()}")

# ---------------------------------------------------------------- 3. events
line("3. the communication-event calendar, offline")
cands = [
    pathlib.Path.home() / "AppData/Local/ARBS/Cache/forexfactory",
    pathlib.Path.home() / "AppData/Local/ARBS/ARBS/Cache/forexfactory",
]
store = next((c for c in cands if c.exists()), None)
if store is None:
    import os
    base = pathlib.Path.home() / "AppData/Local/ARBS"
    hits = [p for p in base.rglob("*orex*") if p.is_dir()][:5]
    print("  forexfactory store not at the expected paths; rglob hits:", hits)
    store = hits[0] if hits else None
if store is not None:
    files = sorted(store.rglob("*.parquet"))
    print(f"  store {store}  ({len(files)} parquet files)")
    if files:
        df = pd.concat([pd.read_parquet(f) for f in files[:400]], ignore_index=True)
        print("  columns:", df.columns.tolist()[:12])
        tcol = next((c for c in df.columns if c.lower() in ("title", "event", "name")), None)
        dcol = next((c for c in df.columns if "date" in c.lower() or c.lower() in ("dt", "ts")), None)
        print(f"  title col {tcol!r}, date col {dcol!r}, rows {len(df)}")
        if tcol:
            for key in ("FOMC Statement", "FOMC Press Conference", "FOMC Meeting Minutes",
                        "Jackson Hole"):
                m = df[df[tcol].astype(str).str.contains(key, case=False, na=False)]
                if len(m) and dcol:
                    dd = pd.to_datetime(m[dcol]).dt.date
                    print(f"    {key:26s} {len(m):4d} rows  {dd.min()}..{dd.max()}")
                else:
                    print(f"    {key:26s} {len(m):4d} rows")

print("\n  FedLock event types:")
print("   " + fl["speech_type"].value_counts().to_string().replace("\n", "\n   "))
semi = fl[fl["title"].str.contains("semiannual|semi-annual", case=False, na=False)]
print(f"   semiannual-testimony by title: {len(semi)} rows "
      f"{semi['date'].min().date()}..{semi['date'].max().date()}")
pc = fl[fl["speech_type"] == "press_conference"]
print(f"   press_conference: {len(pc)} rows {pc['date'].min().date()}..{pc['date'].max().date()}")
print(f"   ... of which >= 2021: {int((pc['date'] >= '2021-01-01').sum())}")

print("\nPROBE DONE", flush=True)
