"""Feasibility probe: can this worktree load the two sides and the SR3 settles
with NO network and NO Excel/COM?  Prints shapes, ranges, and the first/last
rows of everything the new study needs.
"""
from __future__ import annotations

import pathlib
import sys

import numpy as np
import pandas as pd

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
for p in (str(HERE), str(REPO)):
    if p not in sys.path:
        sys.path.insert(0, p)

import fed_detachment_data as D
import fed_detachment_prices as PX
import fed_sentiment_lead_data as L


def line(t):
    print("\n" + "=" * 78 + f"\n{t}\n" + "=" * 78, flush=True)


line("1. surprise panel")
panel, prov = L.load_surprise_panel()
print(panel.shape, panel.index.min(), panel.index.max())
print(panel.columns.tolist())
print(panel.tail(3))
print("prov keys:", list(prov)[:20])

line("2. sides -- JPM")
cfg = D.PRIMARY
zc, zs, sprov = D.load_sides(cfg)
print("zc", zc.dropna().shape, zc.dropna().index.min(), zc.dropna().index.max())
print("zs", zs.dropna().shape, zs.dropna().index.min(), zs.dropna().index.max())
print(sprov.get("note"))
print(pd.concat([zc.rename("zc"), zs.rename("zs")], axis=1).dropna().tail(5))

line("3. sides -- FedLock")
cfg_fl = D.dataclasses.replace(cfg, source="fedlock")
zc2, zs2, p2 = D.load_sides(cfg_fl)
print("zs(fedlock)", zs2.dropna().shape, zs2.dropna().index.min(), zs2.dropna().index.max())

line("4. detachment")
for con in D.CONSTRUCTIONS:
    for k in (0, 5, 11):
        c = D.dataclasses.replace(cfg, construction=con, lead_k=k)
        d = D.detachment(zc, zs, c)
        print(f"  {con:8s} k={k:2d}  n={len(d):4d}  "
              f"{d.index.min().date()}..{d.index.max().date()}  "
              f"mean {d.mean():+.3f} sd {d.std():.3f}")

line("5. SR3 settles")
seeded = PX.seed_local_cache()
print("seeded:", {k: v for k, v in list(seeded.items())[:6]}, "... n=", len(seeded))
syms = PX.sr3_universe(pd.Timestamp("2018-06-01").date(),
                       pd.Timestamp("2026-08-24").date(), max_rank=6)
print("universe", len(syms), syms[:4], syms[-4:])
sp = PX.settle_panel(syms)
print("settle panel", sp.shape, sp.index.min(), sp.index.max())
nn = sp.notna().sum(axis=1)
print("contracts with a settle, last 5 sessions:\n", nn.tail(5))

line("6. rank symbols today and a year ago")
for d in ("2026-08-21", "2025-08-21", "2019-08-21"):
    dd = pd.Timestamp(d).date()
    print(d, [PX.rank_symbol(dd, r) for r in range(1, 5)])

line("7. curve_store_par_rate 2y")
try:
    r2 = PX.curve_store_par_rate(2)
    print("par2y", r2.shape, r2.index.min(), r2.index.max(), "last", float(r2.dropna().iloc[-1]))
    print(PX.gate_rate_sanity(r2, name="par2y"))
except Exception as e:
    print("FAILED:", type(e).__name__, e)

line("8. JPM Fed score book")
sc = L.load_fed_scores(L.LeadConfig())
print(sc.shape, sc.columns.tolist())
print(sc.head(3))
print("date range", sc["date"].min(), sc["date"].max())
