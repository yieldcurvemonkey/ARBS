"""Probe 2: why is the 28-pillar solver delta smeared and 21x too large?"""
import os, sys, time, datetime
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, "C:/Users/chris/clee/ARBS-dd")
sys.path.insert(0, "C:/Users/chris/clee/ARBS-dd/scratch")

import numpy as np, pandas as pd, rateslib as rl
from dd_common import make_pricer, strict_policy, CURVE_FOR
from MDP.IRSwaps.BARCHART_STIRF.risk import build_delta_risk_ladder
from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapValue import IRSwapValue

pd.set_option("display.width", 220)
NY = "America/New_York"
P28 = ["1M","2M","3M","4M","6M","9M","1Y","15M","18M","21M","2Y","30M","3Y","4Y",
       "5Y","6Y","7Y","8Y","9Y","10Y","11Y","12Y","15Y","20Y","25Y","30Y","40Y","50Y"]
P15 = ["3M","6M","1Y","18M","2Y","3Y","4Y","5Y","7Y","10Y","12Y","15Y","20Y","25Y","30Y"]

ts = pd.Timestamp("2026-06-16 11:00", tz=NY)
name = CURVE_FOR["SOFR"]
h0 = make_pricer(strict_policy(1.0)).handle(name, ts)
meta = dict(h0._meta_data); meta["requested_curve_name"] = name
h = RLIRSwapCurve(h0.id(), h0.handle(), h0.index(), meta)
dense = h.handle()
REF = h.reference_date()
CAL = dense.meta.calendar
SPOT = rl.get_calendar("nyc").lag_bus_days(REF, 2, True)
print(f"ref={REF} spot={SPOT} nodes={len(dense.nodes.nodes)}")


def show(tag, pillars):
    rc, slv = build_delta_risk_ladder(pillars, h, timestamp=ts)
    rcurve = None
    for c in slv.pre_curves.values() if hasattr(slv, "pre_curves") else []:
        rcurve = c
    q = IRSwapQuery(curve=name, effective_date=pd.Timestamp(SPOT).date(),
                    maturity_date=datetime.date(2036, 6, 18),
                    structure_kwargs={"notional": 100e6, "fixed_rate": 4.0},
                    ).resolve_query(ts, pricer_or_curve=rc)
    pkg, rws = q.resolve_package(pricer_or_curve=rc)
    print(f"\n--- {tag}: n_pkg={len(pkg)} rws={rws}")
    irs = pkg[0]
    print(f"    irs.curves={getattr(irs, '_curves', None)}  "
          f"notional={getattr(irs.leg1, '_notional', None)}  "
          f"term={irs.leg1.schedule.termination} eff={irs.leg1.schedule.effective}")
    vmap = q.build_value_map(pricer_or_curve=rc, package=pkg, risk_weights=rws)
    print(f"    PV01={float(vmap.apply(value=IRSwapValue.PV01)):,.2f} "
          f"rate={float(vmap.apply(value=IRSwapValue.RATE)):.6f}")
    d = rl.Portfolio(pkg).delta(solver=slv)
    print(f"    delta frame shape={d.shape} cols={list(d.columns)}")
    col = d.iloc[:, 0]
    print(pd.DataFrame({"label": [i[-1] for i in col.index], "delta": col.to_numpy()}
                       ).round(1).to_string(index=False))
    print(f"    SUM={col.sum():,.1f}")
    # control: raw rl.IRS solver on the same node grid
    return rc, slv


show("28 pillars via build_delta_risk_ladder", P28)
show("15 pillars via build_delta_risk_ladder", P15)

# ---------- control: hand-built solver exactly like scratch/krd_final.py ----------
print("\n\n########## CONTROL: raw rl.IRS solver (krd_final.py recipe) ##########")
for tag, pil in (("15", P15), ("28", P28)):
    ins = [rl.IRS(effective=SPOT, termination=t, spec="usd_irs", curves=dense, notional=100e6)
           for t in pil]
    par = [float(i.rate(curves=dense).real) for i in ins]
    mats = [i.leg1.schedule.termination for i in ins]
    nodes = {REF: 1.0}
    for m in mats:
        nodes[m] = float(dense[m])
    rc2 = rl.Curve(nodes=dict(sorted(nodes.items())), convention=dense.meta.convention,
                   calendar=dense.meta.calendar, modifier=dense.meta.modifier,
                   interpolation="log_linear", id="CTRL")
    slv2 = rl.Solver(curves=[rc2],
                     instruments=[rl.IRS(effective=SPOT, termination=t, spec="usd_irs",
                                         curves=rc2, notional=100e6) for t in pil],
                     s=par, instrument_labels=pil, id="CTRL", func_tol=1e-8, conv_tol=1e-10)
    swap = rl.IRS(effective=SPOT, termination="10Y", spec="usd_irs", curves=rc2,
                  notional=100e6, fixed_rate=4.0)
    d = rl.Portfolio([swap]).delta(solver=slv2).iloc[:, 0]
    print(f"\n[control {tag}] cond(J)={np.linalg.cond(np.asarray(slv2.J)):.3f}  SUM={d.sum():,.1f}")
    print({str(k[-1]): round(float(v), 1) for k, v in d.items() if abs(v) > 1.0})
