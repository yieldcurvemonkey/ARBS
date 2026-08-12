"""Probe 6: where the 10.7 ms/unit NPV goes, and whether (notional, fixed_rate)
linearity lets one pair of solved vectors serve every leg on the same schedule."""
import os, sys, time, datetime, statistics
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, "C:/Users/chris/clee/ARBS-dd")
sys.path.insert(0, "C:/Users/chris/clee/ARBS-dd/scratch")

import numpy as np, pandas as pd, rateslib as rl
from dd_common import make_pricer, strict_policy, CURVE_FOR
from MDP.IRSwaps.BARCHART_STIRF.risk import build_delta_risk_ladder
from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve
from Query.IRSwaps.IRSwapQuery import IRSwapQuery

pd.set_option("display.width", 240)
NY = "America/New_York"
P28 = ["1M","2M","3M","4M","6M","9M","1Y","15M","18M","21M","2Y","30M","3Y","4Y",
       "5Y","6Y","7Y","8Y","9Y","10Y","11Y","12Y","15Y","20Y","25Y","30Y","40Y","50Y"]
ts = pd.Timestamp("2026-06-16 11:00", tz=NY)
name = CURVE_FOR["SOFR"]
h0 = make_pricer(strict_policy(1.0)).handle(name, ts)
meta = dict(h0._meta_data); meta["requested_curve_name"] = name
h = RLIRSwapCurve(h0.id(), h0.handle(), h0.index(), meta)
REF = h.reference_date()
SPOT = rl.get_calendar("nyc").lag_bus_days(REF, 2, True)
rc, slv = build_delta_risk_ladder(P28, h, timestamp=ts)
rcurve = rc.handle()
scal = np.array(slv.pre_rate_scalars) / 100.0


def q_pkg(eff, mat, notl, fr_pct):
    q = IRSwapQuery(curve=name, effective_date=pd.Timestamp(eff).date(),
                    maturity_date=pd.Timestamp(mat).date(),
                    structure_kwargs={"notional": float(notl), "fixed_rate": fr_pct / 100.0},
                    ).resolve_query(ts, pricer_or_curve=rc)
    return q.resolve_package(pricer_or_curve=rc)[0]


def timeit(fn, n=20):
    fn()
    t = []
    for _ in range(n):
        t0 = time.perf_counter(); fn(); t.append(time.perf_counter() - t0)
    return statistics.median(t) * 1000


print("=== npv cost by tenor: IRSwapQuery-resolved vs raw rl.IRS ===")
for tnr in ("1Y", "2Y", "5Y", "10Y", "30Y", "50Y"):
    mat = rl.add_tenor(SPOT, tnr, "MF", "nyc")
    pkg = q_pkg(SPOT, mat, 100e6, 4.0)
    raw = rl.IRS(effective=SPOT, termination=mat, spec="usd_irs", curves=rcurve,
                 notional=100e6, fixed_rate=4.0)
    t_q = timeit(lambda: pkg[0].npv(solver=slv, local=True))
    t_r = timeit(lambda: raw.npv(solver=slv, local=True))
    t_rf = timeit(lambda: raw.npv(curves=rcurve, local=True))
    t_d = timeit(lambda: rl.Portfolio(pkg).delta(solver=slv), n=10)
    print(f"  {tnr:4s} query-npv {t_q:7.3f} ms | raw-npv {t_r:7.3f} ms | "
          f"raw-npv-nosolver {t_rf:7.3f} ms | Portfolio.delta {t_d:7.3f} ms")

print("\n=== does the query instrument carry the 7140 fixings? ===")
mat10 = rl.add_tenor(SPOT, "10Y", "MF", "nyc")
pkg = q_pkg(SPOT, mat10, 100e6, 4.0)
per = pkg[0].leg2.periods[0]
print("  leg2 period0 type", type(per).__name__,
      " fixings attr:", str(getattr(per, "fixings", None))[:80])
print("  leg2 n_periods", len(pkg[0].leg2.periods))

print("\n=== (notional, fixed_rate) linearity of the solver delta ===")
mat = rl.add_tenor(SPOT, "10Y", "MF", "nyc")
d0 = rl.Portfolio(q_pkg(SPOT, mat, 1e6, 0.0)).delta(solver=slv).iloc[:, 0].to_numpy(float)
d1 = rl.Portfolio(q_pkg(SPOT, mat, 1e6, 1.0)).delta(solver=slv).iloc[:, 0].to_numpy(float)
for notl, fr in ((100e6, 4.04), (-250e6, 2.5), (37.5e6, 6.0)):
    got = (notl / 1e6) * (d0 + fr * (d1 - d0))
    ref = rl.Portfolio(q_pkg(SPOT, mat, notl, fr)).delta(solver=slv).iloc[:, 0].to_numpy(float)
    print(f"  N={notl:>12,.0f} K={fr:5.2f}%  max|lin - direct| = {np.abs(got-ref).max():.3e} "
          f"(scale {np.abs(ref).max():,.0f})  rel {np.abs(got-ref).max()/np.abs(ref).max():.2e}")

print("\n=== batched: one npv per leg, one matmul for all ===")
rng = np.random.default_rng(3)
TEN = ["6M","1Y","2Y","3Y","5Y","7Y","10Y","12Y","15Y","20Y","30Y"]
N = 200
picks = rng.choice(TEN, N); notls = rng.uniform(5e6, 500e6, N); frs = rng.uniform(3., 5., N)
mats = {t: rl.add_tenor(SPOT, t, "MF", "nyc") for t in TEN}
t0 = time.perf_counter()
pkgs = [q_pkg(SPOT, mats[picks[i]], notls[i], frs[i]) for i in range(N)]
t_build = time.perf_counter() - t0
t0 = time.perf_counter()
duals = [p[0].npv(solver=slv, local=True)["usd"] for p in pkgs]
t_npv = time.perf_counter() - t0
t0 = time.perf_counter()
out = np.array([np.asarray(slv.grad_s_Ploc(d)) * scal for d in duals])
t_grad = time.perf_counter() - t0
print(f"  build {t_build/N*1000:.3f} ms/leg | npv {t_npv/N*1000:.3f} ms/leg | "
      f"grad_s_Ploc {t_grad/N*1000:.4f} ms/leg | TOTAL {(t_build+t_npv+t_grad)/N*1000:.3f} ms/leg")

# the schedule-reuse route: 2 solved vectors per distinct (effective, termination)
t0 = time.perf_counter()
cache = {}
res2 = np.empty((N, len(P28)))
for i in range(N):
    key = (SPOT, mats[picks[i]])
    if key not in cache:
        a = np.asarray(slv.grad_s_Ploc(q_pkg(*key, 1e6, 0.0)[0].npv(solver=slv, local=True)["usd"])) * scal
        b = np.asarray(slv.grad_s_Ploc(q_pkg(*key, 1e6, 1.0)[0].npv(solver=slv, local=True)["usd"])) * scal
        cache[key] = (a, b - a)
    a, slope = cache[key]
    res2[i] = (notls[i] / 1e6) * (a + frs[i] * slope)
t_reuse = time.perf_counter() - t0
print(f"  schedule-reuse route ({len(cache)} distinct schedules for {N} legs): "
      f"{t_reuse/N*1000:.3f} ms/leg   max|diff vs direct| = {np.abs(res2-out).max():.3e}")
