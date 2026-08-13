"""Probe 7: (a) why the IRSwapQuery instrument is 8-20x slower to price than the
identical raw rl.IRS, (b) fixed_rate linearity with non-zero anchors."""
import os, sys, time, datetime, statistics
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, "C:/Users/chris/clee/ARBS-dd")
sys.path.insert(0, "C:/Users/chris/clee/ARBS-dd/scratch")

import numpy as np, pandas as pd, rateslib as rl
from dd_common import make_pricer, strict_policy, CURVE_FOR
from MDP.IRSwaps.BARCHART_STIRF.risk import build_delta_risk_ladder
from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from utils.rl_compat import rate_fixings_kwargs

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
FIX = h.index()
scal = np.array(slv.pre_rate_scalars) / 100.0


def q_pkg(eff, mat, notl, fr_pct):
    q = IRSwapQuery(curve=name, effective_date=pd.Timestamp(eff).date(),
                    maturity_date=pd.Timestamp(mat).date(),
                    structure_kwargs={"notional": float(notl), "fixed_rate": fr_pct / 100.0},
                    ).resolve_query(ts, pricer_or_curve=rc)
    return q.resolve_package(pricer_or_curve=rc)[0]


def timeit(fn, n=15):
    fn()
    t = []
    for _ in range(n):
        t0 = time.perf_counter(); fn(); t.append(time.perf_counter() - t0)
    return statistics.median(t) * 1000


print("=== raw rl.IRS with and without the curve's fixings series attached ===")
for tnr in ("2Y", "10Y", "30Y", "50Y"):
    mat = rl.add_tenor(SPOT, tnr, "MF", "nyc")
    qi = q_pkg(SPOT, mat, 100e6, 4.0)[0]
    raw = rl.IRS(effective=SPOT, termination=mat, spec="usd_irs", curves=rcurve,
                 notional=100e6, fixed_rate=4.0)
    rawf = rl.IRS(effective=SPOT, termination=mat, spec="usd_irs", curves=rcurve,
                  notional=100e6, fixed_rate=4.0, **rate_fixings_kwargs(FIX))
    npv_q = float(qi.npv(solver=slv, local=True)["usd"].real)
    npv_r = float(raw.npv(solver=slv, local=True)["usd"].real)
    npv_rf = float(rawf.npv(solver=slv, local=True)["usd"].real)
    print(f"  {tnr:4s} npv query={npv_q:16,.4f} raw={npv_r:16,.4f} raw+fix={npv_rf:16,.4f} "
          f"| dq-r={npv_q-npv_r:.6f} drf-r={npv_rf-npv_r:.6f}")
    print(f"        time query={timeit(lambda: qi.npv(solver=slv, local=True)):7.3f} "
          f"raw={timeit(lambda: raw.npv(solver=slv, local=True)):7.3f} "
          f"raw+fix={timeit(lambda: rawf.npv(solver=slv, local=True)):7.3f} ms")
    print(f"        periods query {len(qi.leg1.periods)}/{len(qi.leg2.periods)} "
          f"raw {len(raw.leg1.periods)}/{len(raw.leg2.periods)}")

print("\n=== fixed_rate linearity, anchors at 3% and 5% ===")
mat = rl.add_tenor(SPOT, "10Y", "MF", "nyc")
a3 = rl.Portfolio(q_pkg(SPOT, mat, 1e6, 3.0)).delta(solver=slv).iloc[:, 0].to_numpy(float)
a5 = rl.Portfolio(q_pkg(SPOT, mat, 1e6, 5.0)).delta(solver=slv).iloc[:, 0].to_numpy(float)
slope = (a5 - a3) / 2.0
for notl, fr in ((100e6, 4.04), (-250e6, 2.5), (37.5e6, 6.0), (5e6, 0.5)):
    got = (notl / 1e6) * (a3 + (fr - 3.0) * slope)
    ref = rl.Portfolio(q_pkg(SPOT, mat, notl, fr)).delta(solver=slv).iloc[:, 0].to_numpy(float)
    print(f"  N={notl:>12,.0f} K={fr:5.2f}%  max|lin-direct|={np.abs(got-ref).max():.3e} "
          f"rel={np.abs(got-ref).max()/max(np.abs(ref).max(),1e-9):.2e}")

print("\n=== was fixed_rate=0 silently replaced by par? ===")
for frp in (0.0, 1.0, 3.0):
    p = q_pkg(SPOT, mat, 1e6, frp)[0]
    print(f"  requested {frp}% -> leg1.fixed_rate = {p.leg1.fixed_rate}")
