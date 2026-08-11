"""Probe 12: (a) solver build cost with the fixings series stripped from the
calibrating instruments, (b) KRD error vs solver-block length on the worst day."""
import os, sys, time, datetime, statistics
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, "C:/Users/chris/clee/ARBS-dd")
sys.path.insert(0, "C:/Users/chris/clee/ARBS-dd/scratch")

import numpy as np, pandas as pd, rateslib as rl, pytz
from dd_common import make_pricer, strict_policy, CURVE_FOR
from MDP.IRSwaps.BARCHART_STIRF.risk import build_delta_risk_ladder
from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Caching.curve_store import CurveStore

pd.set_option("display.width", 240)
NY = pytz.timezone("America/New_York")
P28 = ["1M","2M","3M","4M","6M","9M","1Y","15M","18M","21M","2Y","30M","3Y","4Y",
       "5Y","6Y","7Y","8Y","9Y","10Y","11Y","12Y","15Y","20Y","25Y","30Y","40Y","50Y"]
NAME = CURVE_FOR["SOFR"]
ASSET = "USD-SOFR-1D-CITIVELOEXCELMIN"
pricer = make_pricer(strict_policy(1.0))
store = CurveStore.default()


def model_at(ts, strip_fixings):
    h0 = pricer.handle(NAME, ts)
    meta = dict(h0._meta_data); meta["requested_curve_name"] = NAME
    fx = h0.index()
    h = RLIRSwapCurve(h0.id(), h0.handle(), fx.iloc[0:0] if strip_fixings else fx, meta)
    rc, slv = build_delta_risk_ladder(P28, h, timestamp=ts)
    rc_fix = RLIRSwapCurve(rc.id(), rc.handle(), fx, dict(rc._meta_data))
    return rc, rc_fix, slv


ts = pd.Timestamp("2026-06-16 11:00", tz=NY)
print("=== solver build cost, fixings attached vs stripped ===")
for strip in (False, True):
    t = []
    for _ in range(3):
        t0 = time.perf_counter(); rc, rcf, slv = model_at(ts, strip)
        t.append(time.perf_counter() - t0)
    print(f"  strip_fixings={strip!s:5s}: {statistics.median(t)*1000:7.0f} ms   "
          f"(all {[round(x*1000) for x in t]})")
    if strip:
        rc_s, rcf_s, slv_s = rc, rcf, slv
    else:
        rc_n, rcf_n, slv_n = rc, rcf, slv

print("\n=== do the two solvers give the same delta? (must be bit-comparable) ===")
spot = rl.get_calendar("nyc").lag_bus_days(rl.dt(2026, 6, 16), 2, True)
cases = [("10Y payer", spot, rl.add_tenor(spot, "10Y", "MF", "nyc"), 100e6, 4.04),
         ("50Y payer", spot, rl.add_tenor(spot, "50Y", "MF", "nyc"), 25e6, 3.99),
         ("past-eff 5Y", datetime.date(2024, 3, 15), datetime.date(2029, 3, 15), 50e6, 4.25)]


def krd(rc, slv, eff, mat, notl, frp):
    pkg = IRSwapQuery(curve=NAME, effective_date=pd.Timestamp(eff).date(),
                      maturity_date=pd.Timestamp(mat).date(),
                      structure_kwargs={"notional": float(notl), "fixed_rate": frp / 100.0},
                      ).resolve_query(ts, pricer_or_curve=rc).resolve_package(pricer_or_curve=rc)[0]
    d = rl.Portfolio(pkg).delta(solver=slv).iloc[:, 0]
    return np.array([float(d.loc[("instruments", slv.id, lab)]) for lab in P28])


for nm, eff, mat, notl, frp in cases:
    past = pd.Timestamp(eff).date() < pd.Timestamp(rc_n.reference_date()).date()
    a = krd(rcf_n if past else rc_n, slv_n, eff, mat, notl, frp)
    b = krd(rcf_s if past else rc_s, slv_s, eff, mat, notl, frp)
    print(f"  {nm:12s} past_eff={past!s:5s} max|full-stripped| = {np.abs(a-b).max():.6e} "
          f"(sum {a.sum():,.1f} vs {b.sum():,.1f})")

# --------------------------------------------------------- block-length error
print("\n=== KRD error vs solver-block length, worst day 2025-04-07 ===")
day = datetime.date(2025, 4, 7)
raw = store.read_raw_nodes(ASSET, start=day, end=day)
stamps = sorted(pd.Timestamp(t).tz_convert(NY) for t in raw["timestamp_utc"])
spot = rl.get_calendar("nyc").lag_bus_days(rl.dt(day.year, day.month, day.day), 2, True)
fwd5 = rl.add_tenor(spot, "5Y", "MF", "nyc")
CASES = [("2Y payer 200mm", spot, rl.add_tenor(spot, "2Y", "MF", "nyc"), 200e6, 3.9),
         ("10Y payer 100mm", spot, rl.add_tenor(spot, "10Y", "MF", "nyc"), 100e6, 4.1),
         ("30Y recv 50mm", spot, rl.add_tenor(spot, "30Y", "MF", "nyc"), -50e6, 4.3),
         ("50Y payer 25mm", spot, rl.add_tenor(spot, "50Y", "MF", "nyc"), 25e6, 4.2),
         ("5Yx5Y payer 300mm", fwd5, rl.add_tenor(fwd5, "5Y", "MF", "nyc"), 300e6, 4.2)]

# exact per-minute reference on a 20-minute sample
sample = [stamps[int(round(i * (len(stamps) - 1) / 19))] for i in range(20)]
exact, blocks = {}, {}
for m in sample:
    rc, rcf, slv = model_at(m, True)
    exact[m] = {nm: krd(rc, slv, e, mt, n, f) for nm, e, mt, n, f in CASES}

for block_min in (60, 120, 240, 480):
    errs = []
    for m in sample:
        # the block anchor: floor the minute to the block, then the first stored
        # snapshot at or after that boundary (no lookahead beyond the block start)
        secs = (m - stamps[0]).total_seconds()
        anchor_t = stamps[0] + pd.Timedelta(minutes=block_min * int(secs // (block_min * 60)))
        anchor = min((s for s in stamps if s >= anchor_t), default=stamps[0])
        if anchor not in blocks:
            rc, rcf, slv = model_at(anchor, True)
            blocks[anchor] = (rc, slv)
        rc, slv = blocks[anchor]
        for nm, e, mt, n, f in CASES:
            ex = exact[m][nm]
            ap = krd(rc, slv, e, mt, n, f)
            tot = abs(ex.sum())
            errs.append((nm, np.abs(ap - ex).max() / tot * 100,
                         abs(ap.sum() - ex.sum()) / tot * 100))
    e = pd.DataFrame(errs, columns=["case", "bkt_pct", "tot_pct"])
    print(f"  block={block_min:4d} min  max bucket err {e['bkt_pct'].max():6.3f}%  "
          f"p95 {e['bkt_pct'].quantile(.95):6.3f}%  median {e['bkt_pct'].median():6.3f}%  "
          f"| max total err {e['tot_pct'].max():6.3f}%  ({len(blocks)} solvers cached)")
