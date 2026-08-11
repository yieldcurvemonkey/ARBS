"""Probe 11: is one solver per (rate_index, as_of_date) enough?

Compares the KRD a trade gets from a DAY solver (built at one instant) against the
KRD it gets from a solver built at its own execution minute, on the three hardest
days available: the biggest intraday shape break in the store and two FOMC days.
"""
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


def model_at(ts):
    h0 = pricer.handle(NAME, ts)
    meta = dict(h0._meta_data); meta["requested_curve_name"] = NAME
    h = RLIRSwapCurve(h0.id(), h0.handle(), h0.index(), meta)
    return build_delta_risk_ladder(P28, h, timestamp=ts)


def krd(rc, slv, ts, eff, mat, notl, frp):
    pkg = IRSwapQuery(curve=NAME, effective_date=pd.Timestamp(eff).date(),
                      maturity_date=pd.Timestamp(mat).date(),
                      structure_kwargs={"notional": float(notl), "fixed_rate": frp / 100.0},
                      ).resolve_query(ts, pricer_or_curve=rc).resolve_package(pricer_or_curve=rc)[0]
    d = rl.Portfolio(pkg).delta(solver=slv).iloc[:, 0]
    return np.array([float(d.loc[("instruments", slv.id, lab)]) for lab in P28])


DAYS = [(datetime.date(2025, 4, 7), "biggest intraday shape break (2y 42bp, 10y 33bp)"),
        (datetime.date(2024, 6, 12), "FOMC, biggest 10y range of any FOMC day (15bp)"),
        (datetime.date(2026, 6, 17), "FOMC, recent (2y 17bp)")]

for day, why in DAYS:
    raw = store.read_raw_nodes(ASSET, start=day, end=day)
    stamps = sorted(pd.Timestamp(t).tz_convert(NY) for t in raw["timestamp_utc"])
    first, last = stamps[0], stamps[-1]
    print(f"\n{'='*100}\n{day}  {why}\n  {len(stamps)} minutes, {first} .. {last}")

    # test trades priced/held at each sampled minute
    ref = pd.Timestamp(day)
    spot = rl.get_calendar("nyc").lag_bus_days(rl.dt(day.year, day.month, day.day), 2, True)
    T = {t: rl.add_tenor(spot, t, "MF", "nyc") for t in ("2Y", "5Y", "10Y", "30Y", "50Y")}
    fwd5 = rl.add_tenor(spot, "5Y", "MF", "nyc")
    CASES = [("2Y payer 200mm", spot, T["2Y"], 200e6, 3.9),
             ("10Y payer 100mm", spot, T["10Y"], 100e6, 4.1),
             ("30Y recv 50mm", spot, T["30Y"], -50e6, 4.3),
             ("50Y payer 25mm", spot, T["50Y"], 25e6, 4.2),
             ("5Yx5Y payer 300mm", fwd5, rl.add_tenor(fwd5, "5Y", "MF", "nyc"), 300e6, 4.2)]

    anchors = {"first_minute": first, "midday": min(stamps, key=lambda s: abs(
        (s - NY.localize(datetime.datetime(day.year, day.month, day.day, 12, 0))).total_seconds()))}
    day_models = {}
    for tag, a in anchors.items():
        t0 = time.perf_counter()
        day_models[tag] = (a,) + model_at(a)
        print(f"  day model [{tag}] at {a}: {(time.perf_counter()-t0)*1000:.0f} ms")

    sample = [stamps[int(round(i * (len(stamps) - 1) / 11))] for i in range(12)]
    rows = []
    for m in sample:
        rcm, slvm = model_at(m)
        for nm, eff, mat, notl, frp in CASES:
            exact = krd(rcm, slvm, m, eff, mat, notl, frp)
            tot = abs(exact.sum())
            rec = {"minute": m.strftime("%H:%M"), "case": nm, "total_dv01": exact.sum()}
            for tag, (a, rca, slva) in day_models.items():
                approx = krd(rca, slva, a, eff, mat, notl, frp)
                rec[f"{tag}_maxbkt_pct"] = np.abs(approx - exact).max() / tot * 100
                rec[f"{tag}_tot_pct"] = abs(approx.sum() - exact.sum()) / tot * 100
            rows.append(rec)
    r = pd.DataFrame(rows)
    print(r.pivot(index="minute", columns="case", values="first_minute_maxbkt_pct")
          .round(3).to_string())
    print("\n  worst over the day, by anchor (% of the trade's total DV01):")
    for tag in day_models:
        print(f"    {tag:12s} max bucket err {r[f'{tag}_maxbkt_pct'].max():7.3f}%   "
              f"max total err {r[f'{tag}_tot_pct'].max():7.3f}%   "
              f"median bucket err {r[f'{tag}_maxbkt_pct'].median():7.3f}%")
    r.to_csv(f"C:/Users/chris/clee/ARBS-dd/scratch/ddkrd_perday_{day}.csv", index=False)
