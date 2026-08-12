"""Probe 5: FED_FUNDS curve-definition gap, solver rebuild cost, per-unit delta cost,
and the batched grad_s_Ploc equivalence."""
import os, sys, time, datetime, statistics
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, "C:/Users/chris/clee/ARBS-dd")
sys.path.insert(0, "C:/Users/chris/clee/ARBS-dd/scratch")

import numpy as np, pandas as pd, rateslib as rl
from dd_common import make_pricer, strict_policy, CURVE_FOR
from MDP.IRSwaps.BARCHART_STIRF.risk import build_delta_risk_ladder
from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.backends.rateslib.rl_curve_definitions_map import RATESLIB_CURVE_DEFINITIONS

pd.set_option("display.width", 240)
NY = "America/New_York"
P28 = ["1M","2M","3M","4M","6M","9M","1Y","15M","18M","21M","2Y","30M","3Y","4Y",
       "5Y","6Y","7Y","8Y","9Y","10Y","11Y","12Y","15Y","20Y","25Y","30Y","40Y","50Y"]
ts = pd.Timestamp("2026-06-16 11:00", tz=NY)
pricer = make_pricer(strict_policy(1.0))

print("map has USD-SOFR-1D:", "USD-SOFR-1D" in RATESLIB_CURVE_DEFINITIONS,
      " USD-FEDFUNDS-1D:", "USD-FEDFUNDS-1D" in RATESLIB_CURVE_DEFINITIONS,
      " USD-FEDFUNDS-1D-RISK:", "USD-FEDFUNDS-1D-RISK" in RATESLIB_CURVE_DEFINITIONS)

# ---------------- FED_FUNDS ----------------
nm = CURVE_FOR["FED_FUNDS"]
h0 = pricer.handle(nm, ts)
print(f"\n[FF] id={h0.id()} asset={h0._meta_data.get('asset')} nodes={len(h0.handle().nodes.nodes)}")
for ref_override in (None, "USD-FEDFUNDS", "USD-FEDFUNDS-1D-RISK"):
    meta = dict(h0._meta_data); meta["requested_curve_name"] = nm
    if ref_override:
        meta["reference_curve_name"] = ref_override
    hh = RLIRSwapCurve(h0.id(), h0.handle(), h0.index(), meta)
    try:
        rcf, slvf = build_delta_risk_ladder(P28, hh, timestamp=ts)
        print(f"[FF] reference_curve_name={ref_override!r} -> OK, risk id={rcf.id()}, "
              f"cond(J)={np.linalg.cond(np.asarray(slvf.J)):.1f}")
        FF = (nm, hh, rcf, slvf)
    except Exception as e:
        print(f"[FF] reference_curve_name={ref_override!r} -> {type(e).__name__}: {e}")

# ---------------- SOFR timings ----------------
name = CURVE_FOR["SOFR"]
h0 = pricer.handle(name, ts)
meta = dict(h0._meta_data); meta["requested_curve_name"] = name
h = RLIRSwapCurve(h0.id(), h0.handle(), h0.index(), meta)
REF = h.reference_date()
SPOT = rl.get_calendar("nyc").lag_bus_days(REF, 2, True)

tt = []
for _ in range(3):
    t0 = time.perf_counter(); rc, slv = build_delta_risk_ladder(P28, h, timestamp=ts)
    tt.append(time.perf_counter() - t0)
print(f"\n[cost] build_delta_risk_ladder K=28, warm: {statistics.median(tt)*1000:.0f} ms "
      f"(all: {[round(x*1000) for x in tt]})")

# same but with fixings stripped from the handle (do the 7140 fixings slow the solve?)
h_nofix = RLIRSwapCurve(h0.id(), h0.handle(), h0.index().tail(5), dict(meta))
tt2 = []
for _ in range(2):
    t0 = time.perf_counter(); build_delta_risk_ladder(P28, h_nofix, timestamp=ts)
    tt2.append(time.perf_counter() - t0)
print(f"[cost] same with a 5-row fixings series:   {statistics.median(tt2)*1000:.0f} ms")

# ---------------- per-unit cost on a realistic tenor mix ----------------
rng = np.random.default_rng(7)
TENORS = ["6M","1Y","2Y","3Y","5Y","7Y","10Y","12Y","15Y","20Y","30Y"]
N = 300
picks = rng.choice(TENORS, N)
notls = rng.uniform(5e6, 500e6, N)
frs = rng.uniform(3.0, 5.0, N)
mats = {t: rl.add_tenor(SPOT, t, "MF", "nyc") for t in TENORS}

t_build = t_delta = 0.0
duals = []
for i in range(N):
    t0 = time.perf_counter()
    q = IRSwapQuery(curve=name, effective_date=pd.Timestamp(SPOT).date(),
                    maturity_date=pd.Timestamp(mats[picks[i]]).date(),
                    structure_kwargs={"notional": float(notls[i]),
                                      "fixed_rate": float(frs[i]) / 100.0},
                    ).resolve_query(ts, pricer_or_curve=rc)
    pkg, _ = q.resolve_package(pricer_or_curve=rc)
    t_build += time.perf_counter() - t0
    t0 = time.perf_counter()
    d = rl.Portfolio(pkg).delta(solver=slv)
    t_delta += time.perf_counter() - t0
    if i < 5:
        duals.append((pkg, d.iloc[:, 0].to_numpy(float)))
print(f"\n[cost] {N} single-leg units: instrument build {t_build/N*1000:.3f} ms/unit, "
      f"Portfolio.delta {t_delta/N*1000:.3f} ms/unit  (total {(t_build+t_delta)/N*1000:.3f} ms/unit)")

# ---------------- batched grad_s_Ploc equivalence ----------------
t0 = time.perf_counter()
npvs = [rl.Portfolio(p).npv(solver=slv, local=True) for p, _ in duals]
t_npv = time.perf_counter() - t0
scal = np.array(slv.pre_rate_scalars) / 100.0
t0 = time.perf_counter()
batched = np.array([np.asarray(slv.grad_s_Ploc(v["usd"])) * scal for v in npvs])
t_g = time.perf_counter() - t0
ref = np.array([d for _, d in duals])
print(f"[equiv] batched grad_s_Ploc vs Portfolio.delta: max|diff| = {np.abs(batched-ref).max():.3e} "
      f"(values of order {np.abs(ref).max():,.0f})")
print(f"[equiv] npv {t_npv/len(duals)*1000:.3f} ms/unit, grad_s_Ploc {t_g/len(duals)*1000:.3f} ms/unit")
