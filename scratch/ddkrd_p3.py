"""Probe 3: which curve/AD variables does the IRSwapQuery-resolved package carry?"""
import os, sys, datetime
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, "C:/Users/chris/clee/ARBS-dd")
sys.path.insert(0, "C:/Users/chris/clee/ARBS-dd/scratch")

import numpy as np, pandas as pd, rateslib as rl
from dd_common import make_pricer, strict_policy, CURVE_FOR
from MDP.IRSwaps.BARCHART_STIRF.risk import build_delta_risk_ladder
from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve
from Query.IRSwaps.IRSwapQuery import IRSwapQuery

pd.set_option("display.width", 220)
NY = "America/New_York"
P28 = ["1M","2M","3M","4M","6M","9M","1Y","15M","18M","21M","2Y","30M","3Y","4Y",
       "5Y","6Y","7Y","8Y","9Y","10Y","11Y","12Y","15Y","20Y","25Y","30Y","40Y","50Y"]
ts = pd.Timestamp("2026-06-16 11:00", tz=NY)
name = CURVE_FOR["SOFR"]
h0 = make_pricer(strict_policy(1.0)).handle(name, ts)
meta = dict(h0._meta_data); meta["requested_curve_name"] = name
h = RLIRSwapCurve(h0.id(), h0.handle(), h0.index(), meta)
dense = h.handle()
REF = h.reference_date()
SPOT = rl.get_calendar("nyc").lag_bus_days(REF, 2, True)

rc, slv = build_delta_risk_ladder(P28, h, timestamp=ts)
rcurve = rc.handle()
print(f"risk curve id={rcurve.id} nodes={len(rcurve.nodes.nodes)}")
print(f"solver curves keys={list(slv.pre_curves.keys())}")

q = IRSwapQuery(curve=name, effective_date=pd.Timestamp(SPOT).date(),
                maturity_date=datetime.date(2036, 6, 18),
                structure_kwargs={"notional": 100e6, "fixed_rate": 4.0},
                ).resolve_query(ts, pricer_or_curve=rc)
pkg, rws = q.resolve_package(pricer_or_curve=rc)
irs = pkg[0]
print("irs type", type(irs), "leg2 type", type(irs.leg2))
for attr in ("_curves", "curves", "_fixings"):
    print(" attr", attr, "=", str(getattr(irs, attr, "<none>"))[:120])

npv_nocurves = irs.npv(solver=slv, local=True)
print("\nnpv(solver only)      =", {k: float(v.real) for k, v in npv_nocurves.items()})
print("  vars:", list(npv_nocurves["usd"].vars)[:6], "... n=", len(npv_nocurves["usd"].vars))

npv_explicit = irs.npv(curves=rcurve, solver=slv, local=True)
print("npv(curves=riskcurve) =", {k: float(v.real) for k, v in npv_explicit.items()})
print("  vars:", list(npv_explicit["usd"].vars)[:6], "... n=", len(npv_explicit["usd"].vars))

for tag, kw in (("no curves", {}), ("curves=riskcurve", {"curves": rcurve})):
    d = rl.Portfolio(pkg).delta(solver=slv, **kw).iloc[:, 0]
    print(f"\n[{tag}] SUM={d.sum():,.1f}")
    print("  ", {str(k[-1]): round(float(v), 1) for k, v in d.items() if abs(v) > 1.0})
