"""Probe 1: can we build a 28-pillar delta risk ladder on the Citi minute curve,
and what does it cost? Grid validation + reprice tie-out + per-unit delta timing."""
import os, sys, time, datetime, statistics
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, "C:/Users/chris/clee/ARBS-dd")
sys.path.insert(0, "C:/Users/chris/clee/ARBS-dd/scratch")

import numpy as np
import pandas as pd
import rateslib as rl

from dd_common import make_pricer, strict_policy, CURVE_FOR, curve_meta
from MDP.IRSwaps.BARCHART_STIRF.risk import build_delta_risk_ladder
from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve
from Query.IRSwaps.IRSwapQuery import IRSwapQuery

PILLARS = ["1M","2M","3M","4M","6M","9M","1Y","15M","18M","21M","2Y","30M","3Y","4Y",
           "5Y","6Y","7Y","8Y","9Y","10Y","11Y","12Y","15Y","20Y","25Y","30Y","40Y","50Y"]

pd.set_option("display.width", 220)
NY = "America/New_York"
pricer = make_pricer(strict_policy(1.0))


def augment(h, curve_name):
    meta = dict(h._meta_data)
    meta["requested_curve_name"] = curve_name
    return RLIRSwapCurve(rl_curve_id=h.id(), rl_curve_handle=h.handle(),
                         fixings=h.index(), meta_data=meta)


def run(idx, ts):
    name = CURVE_FOR[idx]
    t0 = time.perf_counter()
    h0 = pricer.handle(name, ts)
    print(f"\n===== {idx} {name} @ {ts} =====")
    print(f"[build] handle: {(time.perf_counter()-t0)*1000:.0f} ms  meta={curve_meta(h0)}")
    dense = h0.handle()
    fx = h0.index()
    print(f"[curve] ref={h0.reference_date()} nodes={len(dense.nodes.nodes)} "
          f"conv={dense.meta.convention} id={h0.id()} fixings={len(fx)} last={fx.index.max()}")
    try:
        print(f"[def] curve_definition_id = {h0._curve_definition_id()!r} -> ok? ", end="")
        h0._curve_definition()
        print("YES")
    except KeyError as e:
        print(f"NO -- KeyError {e}")

    h = augment(h0, name)
    t0 = time.perf_counter()
    rc, slv = build_delta_risk_ladder(PILLARS, h, timestamp=ts)
    t_solver = time.perf_counter() - t0
    print(f"[solver] 28-pillar build: {t_solver*1000:.1f} ms  n_labels={len(list(slv.instrument_labels))}")
    print(f"[solver] labels={list(slv.instrument_labels)}")
    print(f"[solver] result={getattr(slv,'result',None)}")
    J = np.asarray(slv.J)
    print(f"[grid] J shape={J.shape} cond={np.linalg.cond(J):.4f}")

    errs = []
    for tnr in PILLARS:
        q = IRSwapQuery(curve=name, tenor=tnr).resolve_query(ts, pricer_or_curve=h)
        pkg, _ = q.resolve_package(pricer_or_curve=h)
        r_dense = float(pkg[0].rate().real)
        qr = IRSwapQuery(curve=name, tenor=tnr).resolve_query(ts, pricer_or_curve=rc)
        pkgr, _ = qr.resolve_package(pricer_or_curve=rc)
        r_risk = float(pkgr[0].rate().real)
        errs.append((tnr, r_dense, r_risk, (r_risk - r_dense) * 1e4))
    edf = pd.DataFrame(errs, columns=["tenor", "dense_pct", "risk_pct", "diff_bp"])
    print(edf.round(6).to_string(index=False))
    print(f"[grid] max|reprice err vs dense| = {edf['diff_bp'].abs().max():.6f} bp")
    return h, rc, slv


h, rc, slv = run("SOFR", pd.Timestamp("2026-06-16 11:00", tz=NY))

# ---- per-unit delta: cost and shape
name = CURVE_FOR["SOFR"]
ts = pd.Timestamp("2026-06-16 11:00", tz=NY)


def leg_pkg(eff, mat, notional, fixed_rate):
    q = IRSwapQuery(curve=name, effective_date=eff, maturity_date=mat,
                    structure_kwargs={"notional": notional, "fixed_rate": fixed_rate},
                    ).resolve_query(ts, pricer_or_curve=rc)
    pkg, _ = q.resolve_package(pricer_or_curve=rc)
    return pkg


REF = pd.Timestamp(h.reference_date()).date()
cases = [
    ("spot 10Y payer 100mm", REF + datetime.timedelta(days=2), datetime.date(2036, 6, 18), 100e6, 4.0),
    ("spot 2Y recv 200mm", REF + datetime.timedelta(days=2), datetime.date(2028, 6, 20), -200e6, 3.8),
    ("past-eff 5Y payer", datetime.date(2024, 3, 15), datetime.date(2029, 3, 15), 50e6, 4.25),
    ("50Y payer", REF + datetime.timedelta(days=2), datetime.date(2076, 6, 18), 25e6, 4.3),
]
for nm, eff, mat, notl, fr in cases:
    t0 = time.perf_counter()
    try:
        pkg = leg_pkg(eff, mat, notl, fr)
        t_build = time.perf_counter() - t0
        t0 = time.perf_counter()
        d = rl.Portfolio(pkg).delta(solver=slv)
        t_delta = time.perf_counter() - t0
        col = d.iloc[:, 0]
        tot = float(col.sum())
        top = col.abs().sort_values(ascending=False).head(4)
        print(f"\n[{nm}] build={t_build*1000:.1f}ms delta={t_delta*1000:.1f}ms sum={tot:,.1f}")
        print("   top buckets:", {str(k[-1]): round(float(col.loc[k]), 1) for k in top.index})
    except Exception as e:
        print(f"\n[{nm}] FAILED {type(e).__name__}: {e}")
