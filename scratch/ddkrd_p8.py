"""Probe 8: (a) npv cost vs length of the attached fixings series,
(b) real per-day leg / distinct-schedule counts from the v3 tape."""
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
FIX = h0.index()
REF = h0.reference_date()
SPOT = rl.get_calendar("nyc").lag_bus_days(REF, 2, True)


def mk_handle(fixings):
    meta = dict(h0._meta_data); meta["requested_curve_name"] = name
    return RLIRSwapCurve(h0.id(), h0.handle(), fixings, meta)


def timeit(fn, n=10):
    fn()
    t = []
    for _ in range(n):
        t0 = time.perf_counter(); fn(); t.append(time.perf_counter() - t0)
    return statistics.median(t) * 1000


print("=== npv cost vs attached fixings length (spot 30Y, $100mm, 4%) ===")
base_h = mk_handle(FIX)
rc_full, slv = build_delta_risk_ladder(P28, base_h, timestamp=ts)
mat30 = rl.add_tenor(SPOT, "30Y", "MF", "nyc")


def q_on(rc, eff, mat, notl, frp):
    return IRSwapQuery(curve=name, effective_date=pd.Timestamp(eff).date(),
                       maturity_date=pd.Timestamp(mat).date(),
                       structure_kwargs={"notional": float(notl), "fixed_rate": frp / 100.0},
                       ).resolve_query(ts, pricer_or_curve=rc).resolve_package(pricer_or_curve=rc)[0]


for nfix in (0, 1, 10, 260, 1300, len(FIX)):
    fx = FIX.tail(nfix) if nfix else FIX.iloc[0:0]
    rch = RLIRSwapCurve(rc_full.id(), rc_full.handle(), fx, dict(rc_full._meta_data))
    try:
        p = q_on(rch, SPOT, mat30, 100e6, 4.0)
        v = float(p[0].npv(solver=slv, local=True)["usd"].real)
        t = timeit(lambda: p[0].npv(solver=slv, local=True))
        print(f"  fixings={nfix:6d}  npv={v:16,.4f}  npv time={t:7.3f} ms")
    except Exception as e:
        print(f"  fixings={nfix:6d}  {type(e).__name__}: {str(e)[:90]}")

print("\n=== past-effective leg: how short can the fixings window be? ===")
past_eff = datetime.date(2024, 3, 15)
past_mat = datetime.date(2029, 3, 15)
need = FIX[FIX.index >= pd.Timestamp(past_eff) - pd.Timedelta(days=10)]
print(f"  need window from {past_eff} -> {len(need)} rows of {len(FIX)}")
for tag, fx in (("full", FIX), ("windowed", need), ("tail-30", FIX.tail(30)), ("empty", FIX.iloc[0:0])):
    rch = RLIRSwapCurve(rc_full.id(), rc_full.handle(), fx, dict(rc_full._meta_data))
    try:
        p = q_on(rch, past_eff, past_mat, 50e6, 4.25)
        v = float(p[0].npv(solver=slv, local=True)["usd"].real)
        t = timeit(lambda: p[0].npv(solver=slv, local=True))
        print(f"  {tag:9s} n={len(fx):5d} npv={v:16,.4f} time={t:7.3f} ms")
    except Exception as e:
        print(f"  {tag:9s} n={len(fx):5d} {type(e).__name__}: {str(e)[:110]}")

# ------------------------------------------------------------------ tape shape
print("\n=== v3 tape: per-day legs and distinct schedules ===")
import sqlalchemy as sa
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE

eng = sa.create_engine(resolve_pg_url())
sql = f"""
select as_of_date,
       count(*) as legs,
       count(distinct (effective_date, expiration_date)) as sched,
       count(distinct (rate_index_clean, effective_date, expiration_date)) as sched_idx,
       count(distinct rate_index_clean) as idxs
from {LEGS_TABLE}
where as_of_date in ('2024-03-04','2024-09-18','2025-06-18','2026-01-28',
                     '2026-06-16','2026-06-17','2026-08-06')
group by 1 order by 1
"""
with eng.connect() as c:
    print(pd.read_sql(sa.text(sql), c).to_string(index=False))
sql2 = f"""
select count(*) legs, count(distinct (rate_index_clean, effective_date, expiration_date)) sched
from {LEGS_TABLE}
"""
with eng.connect() as c:
    print(pd.read_sql(sa.text(sql2), c).to_string(index=False))
