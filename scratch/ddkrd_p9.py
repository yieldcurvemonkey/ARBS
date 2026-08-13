"""Probe 9: tape date coverage + the leg-split affine decomposition of the solver delta."""
import os, sys, time, datetime, statistics
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, "C:/Users/chris/clee/ARBS-dd")
sys.path.insert(0, "C:/Users/chris/clee/ARBS-dd/scratch")

import numpy as np, pandas as pd, rateslib as rl, sqlalchemy as sa
from dd_common import make_pricer, strict_policy, CURVE_FOR
from MDP.IRSwaps.BARCHART_STIRF.risk import build_delta_risk_ladder
from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE

pd.set_option("display.width", 240)
eng = sa.create_engine(resolve_pg_url())
with eng.connect() as c:
    print(pd.read_sql(sa.text(
        f"select min(as_of_date) mn, max(as_of_date) mx, count(distinct as_of_date) nd,"
        f" count(*) n from {LEGS_TABLE}"), c).to_string(index=False))
    print(pd.read_sql(sa.text(
        f"select as_of_date, count(*) legs,"
        f" count(distinct (rate_index_clean, effective_date, expiration_date)) sched"
        f" from {LEGS_TABLE} where as_of_date >= '2026-06-10' and as_of_date <= '2026-06-20'"
        f" group by 1 order by 1"), c).to_string(index=False))
    # FOMC days in the tape window
    print(pd.read_sql(sa.text(
        f"select as_of_date, count(*) legs,"
        f" count(distinct (rate_index_clean, effective_date, expiration_date)) sched"
        f" from {LEGS_TABLE} where as_of_date in"
        f" ('2024-09-18','2024-11-07','2024-12-18','2025-03-19','2025-09-17','2025-12-10')"
        f" group by 1 order by 1"), c).to_string(index=False))

# --------------------------------------------------------------- leg-split
NY = "America/New_York"
P28 = ["1M","2M","3M","4M","6M","9M","1Y","15M","18M","21M","2Y","30M","3Y","4Y",
       "5Y","6Y","7Y","8Y","9Y","10Y","11Y","12Y","15Y","20Y","25Y","30Y","40Y","50Y"]
ts = pd.Timestamp("2026-06-16 11:00", tz=NY)
name = CURVE_FOR["SOFR"]
h0 = make_pricer(strict_policy(1.0)).handle(name, ts)
meta = dict(h0._meta_data); meta["requested_curve_name"] = name
FIX = h0.index()
h = RLIRSwapCurve(h0.id(), h0.handle(), FIX, meta)
REF = h.reference_date()
SPOT = rl.get_calendar("nyc").lag_bus_days(REF, 2, True)
rc_full, slv = build_delta_risk_ladder(P28, h, timestamp=ts)
scal = np.array(slv.pre_rate_scalars) / 100.0
# a nofix twin of the risk handle -- same rl.Curve object, empty fixings
rc_nofix = RLIRSwapCurve(rc_full.id(), rc_full.handle(), FIX.iloc[0:0],
                         dict(rc_full._meta_data))


def build(rc, eff, mat, notl, frp):
    return IRSwapQuery(curve=name, effective_date=pd.Timestamp(eff).date(),
                       maturity_date=pd.Timestamp(mat).date(),
                       structure_kwargs={"notional": float(notl), "fixed_rate": frp / 100.0},
                       ).resolve_query(ts, pricer_or_curve=rc).resolve_package(pricer_or_curve=rc)[0][0]


print("\n=== leg-level npv API ===")
mat10 = rl.add_tenor(SPOT, "10Y", "MF", "nyc")
irs = build(rc_nofix, SPOT, mat10, 1e6, 1.0)
crv = rc_full.handle()
n1 = irs.leg1.npv(rate_curve=crv, disc_curve=crv, local=True)
n2 = irs.leg2.npv(rate_curve=crv, disc_curve=crv, local=True)
tot = irs.npv(curves=crv, local=True)
print(f"  leg1 {float(n1['usd'].real):,.2f}  leg2 {float(n2['usd'].real):,.2f}  "
      f"sum {float(n1['usd'].real)+float(n2['usd'].real):,.2f}  irs {float(tot['usd'].real):,.2f}")

g_ann = np.asarray(slv.grad_s_Ploc(n1["usd"])) * scal      # per 1e6 notional per 1% fixed
g_flt = np.asarray(slv.grad_s_Ploc(n2["usd"])) * scal      # per 1e6 notional

print("\n=== affine reconstruction vs Portfolio.delta (10Y schedule) ===")
for notl, frp in ((100e6, 4.04), (-250e6, 2.5), (37.5e6, 6.0), (5e6, 0.5), (1e9, 3.33)):
    got = (notl / 1e6) * (g_flt + frp * g_ann)
    ref = rl.Portfolio([build(rc_nofix, SPOT, mat10, notl, frp)]).delta(solver=slv).iloc[:, 0].to_numpy(float)
    print(f"  N={notl:>14,.0f} K={frp:5.2f}%  max|aff-direct|={np.abs(got-ref).max():.3e} "
          f"rel={np.abs(got-ref).max()/max(np.abs(ref).max(),1e-9):.2e}")

print("\n=== same for a past-effective schedule (needs fixings) ===")
pe, pm = datetime.date(2024, 3, 15), datetime.date(2029, 3, 15)
irs_pe = build(rc_full, pe, pm, 1e6, 1.0)
n1 = irs_pe.leg1.npv(rate_curve=crv, disc_curve=crv, local=True)
n2 = irs_pe.leg2.npv(rate_curve=crv, disc_curve=crv, local=True)
ga = np.asarray(slv.grad_s_Ploc(n1["usd"])) * scal
gf = np.asarray(slv.grad_s_Ploc(n2["usd"])) * scal
for notl, frp in ((50e6, 4.25), (-120e6, 3.1)):
    got = (notl / 1e6) * (gf + frp * ga)
    ref = rl.Portfolio([build(rc_full, pe, pm, notl, frp)]).delta(solver=slv).iloc[:, 0].to_numpy(float)
    print(f"  N={notl:>14,.0f} K={frp:5.2f}%  max|aff-direct|={np.abs(got-ref).max():.3e} "
          f"rel={np.abs(got-ref).max()/max(np.abs(ref).max(),1e-9):.2e}")


def timeit(fn, n=10):
    fn(); t = []
    for _ in range(n):
        t0 = time.perf_counter(); fn(); t.append(time.perf_counter() - t0)
    return statistics.median(t) * 1000


print("\n=== cost of one schedule's affine pair, by tenor (no fixings) ===")
for tnr in ("1Y", "5Y", "10Y", "30Y", "50Y"):
    m = rl.add_tenor(SPOT, tnr, "MF", "nyc")

    def one():
        i = build(rc_nofix, SPOT, m, 1e6, 1.0)
        a = slv.grad_s_Ploc(i.leg1.npv(rate_curve=crv, disc_curve=crv, local=True)["usd"])
        b = slv.grad_s_Ploc(i.leg2.npv(rate_curve=crv, disc_curve=crv, local=True)["usd"])
        return a, b
    print(f"  {tnr:4s} affine pair {timeit(one):7.3f} ms   "
          f"(Portfolio.delta once {timeit(lambda: rl.Portfolio([build(rc_nofix, SPOT, m, 1e6, 1.0)]).delta(solver=slv), n=6):7.3f} ms)")
