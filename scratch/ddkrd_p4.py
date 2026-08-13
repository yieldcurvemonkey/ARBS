"""Probe 4: correct units (fixed_rate is a DECIMAL in structure_kwargs).
Grid validation + per-unit delta cost + FED_FUNDS + past-effective legs."""
import os, sys, time, datetime, statistics
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, "C:/Users/chris/clee/ARBS-dd")
sys.path.insert(0, "C:/Users/chris/clee/ARBS-dd/scratch")

import numpy as np, pandas as pd, rateslib as rl
from dd_common import make_pricer, strict_policy, CURVE_FOR
from MDP.IRSwaps.BARCHART_STIRF.risk import build_delta_risk_ladder
from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapValue import IRSwapValue

pd.set_option("display.width", 240)
NY = "America/New_York"
P28 = ["1M","2M","3M","4M","6M","9M","1Y","15M","18M","21M","2Y","30M","3Y","4Y",
       "5Y","6Y","7Y","8Y","9Y","10Y","11Y","12Y","15Y","20Y","25Y","30Y","40Y","50Y"]
P21 = ["3M","6M","9M","1Y","18M","2Y","3Y","4Y","5Y","6Y","7Y","8Y","9Y","10Y","11Y","12Y",
       "15Y","20Y","25Y","30Y","40Y"]
P15 = ["3M","6M","1Y","18M","2Y","3Y","4Y","5Y","7Y","10Y","12Y","15Y","20Y","25Y","30Y"]
P28_no11 = [t for t in P28 if t != "11Y"]
P28_no40 = [t for t in P28 if t not in ("40Y", "50Y")]

ts = pd.Timestamp("2026-06-16 11:00", tz=NY)


def handle_for(idx, ts):
    nm = CURVE_FOR[idx]
    h0 = make_pricer(strict_policy(1.0)).handle(nm, ts)
    meta = dict(h0._meta_data); meta["requested_curve_name"] = nm
    return nm, RLIRSwapCurve(h0.id(), h0.handle(), h0.index(), meta)


name, h = handle_for("SOFR", ts)
dense = h.handle()
REF = h.reference_date()
SPOT = rl.get_calendar("nyc").lag_bus_days(REF, 2, True)
print(f"ref={REF} spot={SPOT}")


def mk(rc, eff, mat, notional, fixed_rate_pct):
    """fixed_rate in structure_kwargs is a DECIMAL FRACTION (0.04 == 4%)."""
    q = IRSwapQuery(curve=name, effective_date=pd.Timestamp(eff).date(),
                    maturity_date=pd.Timestamp(mat).date(),
                    structure_kwargs={"notional": float(notional),
                                      "fixed_rate": fixed_rate_pct / 100.0},
                    ).resolve_query(ts, pricer_or_curve=rc)
    return q.resolve_package(pricer_or_curve=rc)


models = {}
for tag, pil in (("K28", P28), ("K21", P21), ("K15", P15),
                 ("K27_no11Y", P28_no11), ("K26_no40+", P28_no40)):
    t0 = time.perf_counter()
    rc, slv = build_delta_risk_ladder(pil, h, timestamp=ts)
    models[tag] = (pil, rc, slv, time.perf_counter() - t0)
    print(f"[{tag}] solver {(models[tag][3])*1000:7.1f} ms  cond(J)={np.linalg.cond(np.asarray(slv.J)):8.2f}")

fwd1 = rl.add_tenor(SPOT, "1Y", "MF", "nyc")
fwd5 = rl.add_tenor(SPOT, "5Y", "MF", "nyc")
CASES = [
    ("spot 2Y payer",   SPOT, rl.add_tenor(SPOT, "2Y", "MF", "nyc"),  200e6, 3.92),
    ("spot 10Y payer",  SPOT, rl.add_tenor(SPOT, "10Y", "MF", "nyc"), 100e6, 4.04),
    ("spot 11Y payer",  SPOT, rl.add_tenor(SPOT, "11Y", "MF", "nyc"), 100e6, 4.07),
    ("spot 30Y recv",   SPOT, rl.add_tenor(SPOT, "30Y", "MF", "nyc"), -50e6, 4.23),
    ("spot 40Y payer",  SPOT, rl.add_tenor(SPOT, "40Y", "MF", "nyc"),  50e6, 4.12),
    ("spot 50Y payer",  SPOT, rl.add_tenor(SPOT, "50Y", "MF", "nyc"),  25e6, 3.99),
    ("1Yx10Y receiver", fwd1, rl.add_tenor(fwd1, "10Y", "MF", "nyc"), -150e6, 4.10),
    ("5Yx5Y payer",     fwd5, rl.add_tenor(fwd5, "5Y", "MF", "nyc"),  300e6, 4.20),
    ("past-eff 5Y payer", datetime.date(2024, 3, 15), datetime.date(2029, 3, 15), 50e6, 4.25),
    ("7Y off-mkt payer", SPOT, rl.add_tenor(SPOT, "7Y", "MF", "nyc"), 250e6, 2.50),
]

print("\n===== per-case totals and placement, by bucket set =====")
rows = []
for nm_, eff, mat, notl, fr in CASES:
    rec = {"case": nm_}
    for tag, (pil, rc, slv, _) in models.items():
        pkg, rws = mk(rc, eff, mat, notl, fr)
        vmap = IRSwapQuery(curve=name, effective_date=pd.Timestamp(eff).date(),
                           maturity_date=pd.Timestamp(mat).date(),
                           structure_kwargs={"notional": float(notl), "fixed_rate": fr / 100.0},
                           ).resolve_query(ts, pricer_or_curve=rc).build_value_map(
            pricer_or_curve=rc, package=pkg, risk_weights=rws)
        pv01 = float(vmap.apply(value=IRSwapValue.PV01))
        d = rl.Portfolio(pkg).delta(solver=slv).iloc[:, 0]
        rec[tag] = d.sum()
        if tag == "K28":
            rec["pv01"] = pv01
            top = d.abs().sort_values(ascending=False).head(3)
            rec["top3_K28"] = "; ".join(f"{str(k[-1])}={float(d.loc[k]):,.0f}" for k in top.index)
    rows.append(rec)
df = pd.DataFrame(rows)
print(df.to_string(index=False, float_format=lambda v: f"{v:,.1f}"))
print("\nsum(delta)/PV01 by bucket set:")
for tag in models:
    df[tag + "_r"] = df[tag] / df["pv01"]
print(df[["case"] + [t + "_r" for t in models]].round(5).to_string(index=False))

# ---- 11Y / 40Y necessity: compare K28 placement vs the reduced grids, per case
print("\n===== bucket-grid necessity: max |delta_reduced - delta_K28| as % of total DV01 =====")
for nm_, eff, mat, notl, fr in CASES:
    pil28, rc28, slv28, _ = models["K28"]
    d28 = rl.Portfolio(mk(rc28, eff, mat, notl, fr)[0]).delta(solver=slv28).iloc[:, 0]
    m28 = {str(k[-1]): float(v) for k, v in d28.items()}
    tot = abs(sum(m28.values()))
    line = [f"{nm_:20s}"]
    for tag in ("K21", "K15", "K27_no11Y", "K26_no40+"):
        pil, rc, slv, _ = models[tag]
        d = rl.Portfolio(mk(rc, eff, mat, notl, fr)[0]).delta(solver=slv).iloc[:, 0]
        m = {str(k[-1]): float(v) for k, v in d.items()}
        keys = set(m) | set(m28)
        mx = max(abs(m.get(k, 0.0) - m28.get(k, 0.0)) for k in keys)
        line.append(f"{tag}={mx/tot*100:7.2f}%")
    print("  ".join(line))
