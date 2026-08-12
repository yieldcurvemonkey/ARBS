"""One full tape day through the pipeline, timed, with the counts the pilot
window has to have: recovered PKG-N, upfront-rule units, both venue classes.

    python scratch/nbhelp_probe2.py 2025-06-17
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
import warnings  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import psycopg2  # noqa: E402

from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url  # noqa: E402
from SDRUtils.dealer_direction import conventions as conv  # noqa: E402
from SDRUtils.dealer_direction import krd, midprice, package_price as pp  # noqa: E402
from SDRUtils.dealer_direction import snapshot, universe  # noqa: E402

DAY = sys.argv[1]
CACHE = pathlib.Path("D:/ddnb_cache/legs")
CACHE.mkdir(parents=True, exist_ok=True)


def t(label, fn):
    t0 = time.perf_counter()
    out = fn()
    print(f"  [{time.perf_counter() - t0:7.1f}s] {label}", flush=True)
    return out


path = CACHE / f"{DAY}.parquet"
if path.exists():
    legs = t("load_legs (cached)", lambda: pd.read_parquet(path))
else:
    def _load():
        conn = psycopg2.connect(resolve_pg_url())
        try:
            return universe.load_legs(conn, DAY, DAY)
        finally:
            conn.close()
    legs = t("load_legs (db)", _load)
    legs.to_parquet(path, index=False)

print(f"legs: {len(legs)} rows, {legs['as_of_date'].nunique()} days")

uf = t("unit_frame", lambda: universe.unit_frame(legs))
units, excl = t("build_universe", lambda: universe.build_universe(legs))

kept = uf[uf["exclusion"].isna()]
print(f"\nunits total {len(uf)}, kept {len(kept)} ({len(kept)/len(uf):.1%})")
print("kept by kind:\n", kept["kind"].value_counts().to_string())
print("kept by rate_index:\n", kept["rate_index"].value_counts().to_string())
print("kept by venue_class:\n", kept["venue_class"].value_counts().to_string())
print("kept lifecycle:", int(kept["is_lifecycle"].sum()))
print("kept with upfront:", int(kept["upfront"].notna().sum()))
print("kept PKG (n_legs>=4):", int((kept["n_legs"] >= 4).sum()))
print("\nexclusions by reason:\n",
      uf["exclusion"].value_counts(dropna=False).to_string())
print("\nDV01 share kept: "
      f"{kept['dv01_proxy'].sum() / uf['dv01_proxy'].sum():.4%}")

# ---- the pricing population, all three rules -----------------------------
INDEX = {"SOFR"}
pop, rules = [], []
for u in units:
    if u.rate_index not in INDEX:
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

print(f"\npricing population {len(pop)}: "
      f"{pd.Series(rules).value_counts().to_string()}")
pop_rule = dict(zip((u.unit_key for u in pop), rules))
pop.sort(key=lambda u: snapshot.snap_instant(u.clocks.pricing))

rep = t("UnitRepricer.for_source",
        lambda: midprice.UnitRepricer.for_source(snapshot.CURVE_SOURCE))
proj = krd.KrdProjector(rep.pricer)

priced = {}
t0 = time.perf_counter()
with rep.day_scope():
    for u in pop:
        priced[u.unit_key] = rep.price_unit(u)
print(f"  [{time.perf_counter() - t0:7.1f}s] price {len(pop)} units")

ok = [k for k, v in priced.items() if v.failure is None]
print(f"priced ok {len(ok)}/{len(pop)} = {len(ok)/len(pop):.2%}")
fails = pd.Series([v.failure for v in priced.values() if v.failure]).value_counts()
print("failures:\n", fails.to_string() if len(fails) else "  none")

# start_class stratification, per leg
strat = pd.DataFrame([{"start_class": q.start_class, "ok": q.ok}
                      for v in priced.values() for q in v.legs])
print("\nper-leg priced fraction by start_class:")
print(strat.groupby("start_class")["ok"].agg(["size", "mean"]).to_string())

# ---- the package rule on the recovered PKG-N ------------------------------
n_pkg, pkg_calls = 0, []
for u in pop:
    if pop_rule[u.unit_key] != pp.RULE_PACKAGE_PRICE:
        continue
    r = priced[u.unit_key]
    if r.failure is not None:
        continue
    n_pkg += 1
    ptp = pd.to_numeric(u.legs["package_transaction_price"],
                        errors="coerce").abs().max()
    c = pp.classify(
        opas=[float(x) for x in pd.to_numeric(
            u.legs["other_payment_amount"], errors="coerce").fillna(np.nan)],
        package_price=ptp,
        npv_pays=[q.npv_pay for q in r.legs],
        pv01s=[q.pv01 for q in r.legs],
        structure_dv01=r.pricing.structure_dv01,
        is_lifecycle=u.is_lifecycle,
    )
    pkg_calls.append(c)

got = pd.Series([c.exclusion or "ORIENTED" for c in pkg_calls]).value_counts()
print(f"\npackage rule on {n_pkg} priced PKG-N units:\n{got.to_string()}")
oriented = [c for c in pkg_calls if c.exclusion is None]
if oriented:
    print(f"  deviation_bps: {pd.Series([c.deviation_bps for c in oriented]).describe().to_string()}")
    print(f"  example base_orientation: {oriented[0].base_orientation}, "
          f"dealer_sign={oriented[0].dealer_sign}, "
          f"tieout_bps={oriented[0].tieout_bps:.4f}, "
          f"margin_bps={oriented[0].margin_bps:.4f}")
