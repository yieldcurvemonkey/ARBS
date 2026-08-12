"""Failure diagnostics + KRD timing for one day. Legs come from the D: cache.

    python scratch/nbhelp_probe3.py 2025-06-17 [--lifecycle-out] [--krd N]
"""
from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
os.environ["ARBS_CITIVELO_QUOTES_OFFLINE"] = "1"
os.environ.setdefault("TMPDIR", "D:/ddnb_cache/tmp")

REPO = r"C:\Users\chris\clee\ARBS-dd"
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import pathlib  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import psycopg2  # noqa: E402

from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url  # noqa: E402
from SDRUtils.dealer_direction import conventions as conv  # noqa: E402
from SDRUtils.dealer_direction import krd, midprice  # noqa: E402
from SDRUtils.dealer_direction import package_price as pp  # noqa: E402
from SDRUtils.dealer_direction import snapshot, universe  # noqa: E402
from SDRUtils.dealer_direction.types import DirectionCall  # noqa: E402

DAY = sys.argv[1]
KRD_N = int(sys.argv[sys.argv.index("--krd") + 1]) if "--krd" in sys.argv else 0
CACHE = pathlib.Path("D:/ddnb_cache/legs")
CACHE.mkdir(parents=True, exist_ok=True)

path = CACHE / f"{DAY}.parquet"
if path.exists():
    legs = pd.read_parquet(path)
else:
    conn = psycopg2.connect(resolve_pg_url())
    try:
        legs = universe.load_legs(conn, DAY, DAY)
    finally:
        conn.close()
    legs.to_parquet(path, index=False)

units, _ = universe.build_universe(legs)
pop, rules = [], []
for u in units:
    if u.rate_index != "SOFR":
        continue
    if u.kind == conv.PKG:
        rule = pp.RULE_PACKAGE_PRICE
    else:
        rule = conv.RULE_UPFRONT if u.upfront is not None else conv.RULE_RATE
        try:
            conv.base_orientation(u.kind, u.n_legs, rule)
        except conv.UnorientableUnit:
            continue
    pop.append(u)
    rules.append(rule)
pop_rule = dict(zip((u.unit_key for u in pop), rules))
pop.sort(key=lambda u: snapshot.snap_instant(u.clocks.pricing))

rep = midprice.UnitRepricer.for_source(snapshot.CURVE_SOURCE)
proj = krd.KrdProjector(rep.pricer)

t0 = time.perf_counter()
rows = []
priced = {}
with rep.day_scope():
    for u in pop:
        out = rep.price_unit(u)
        priced[u.unit_key] = out
        rows.append({
            "unit_key": u.unit_key, "kind": u.kind, "rule": pop_rule[u.unit_key],
            "is_lifecycle": u.is_lifecycle, "n_legs": u.n_legs,
            "pricing_clock_is_date": not isinstance(
                u.clocks.pricing, pd.Timestamp),
            "snap": str(snapshot.snap_instant(u.clocks.pricing)),
            "policy": out.pricing.snapshot_policy,
            "failure": out.failure,
            "detail": (out.failure_detail or "")[:70],
        })
print(f"price {len(pop)} units: {time.perf_counter()-t0:.1f}s")
df = pd.DataFrame(rows)
bad = df[df["failure"].notna()]
print(f"\nfailures {len(bad)}/{len(df)} = {len(bad)/len(df):.2%}")
if len(bad):
    print(bad.groupby(["failure", "is_lifecycle",
                       "pricing_clock_is_date"]).size().to_string())
    print("\ntop failure details:")
    print(bad["detail"].value_counts().head(8).to_string())
    print("\nfailing snap hours (NY):")
    hrs = pd.to_datetime(bad["snap"], utc=True, format="mixed",
                         errors="coerce").dt.tz_convert("America/New_York").dt.hour
    print(hrs.value_counts().sort_index().to_string())
    print("\nALL snap hours (NY):")
    hrs2 = pd.to_datetime(df["snap"], utc=True, format="mixed",
                          errors="coerce").dt.tz_convert("America/New_York").dt.hour
    print(hrs2.value_counts().sort_index().to_string())

# ---- KRD timing on a slice -----------------------------------------------
if KRD_N:
    sub = [u for u in pop if priced[u.unit_key].failure is None][:KRD_N]
    calls = []
    for u in sub:
        calls.append(DirectionCall(
            unit_key=u.unit_key, rule=pop_rule[u.unit_key], deviation_bps=0.0,
            p=0.75, signed_weight=0.5, dealer_sign=1,
            base_orientation=((1,) * u.n_legs
                              if pop_rule[u.unit_key] == pp.RULE_PACKAGE_PRICE
                              else None)))
    t0 = time.perf_counter()
    with proj.day_scope():
        kf, kfail = proj.krd_frame(sub, calls)
    el = time.perf_counter() - t0
    print(f"\nKRD on {len(sub)} units: {el:.1f}s ({el/max(len(sub),1)*1000:.0f} "
          f"ms/unit) -> {len(kf)} rows, {len(kfail)} failures, "
          f"{proj.n_models} solvers")
    if len(kfail):
        print(kfail["failure_reason"].value_counts().to_string())
