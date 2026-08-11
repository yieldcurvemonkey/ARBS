"""Probe 14: re-run the two measurements whose console output was lost.

(a) FED_FUNDS: does ``build_delta_risk_ladder`` work on USD-FEDFUNDS-1D, which
    is NOT in RATESLIB_CURVE_DEFINITIONS, and does it need a
    ``reference_curve_name`` override?
(b) the 28-pillar grid: reprice tie-out, cond(J), and the 11Y / >=40Y necessity
    measured as max bucket disagreement vs K=28 in % of the trade's total DV01.

Both run on the fixings-STRIPPED handle, which p12 measured at 300 ms vs 2555 ms
and bit-equal to 6.1e-11.
"""
from __future__ import annotations

import datetime
import os
import statistics
import sys
import time

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, "C:/Users/chris/clee/ARBS-dd")
sys.path.insert(0, "C:/Users/chris/clee/ARBS-dd/scratch")

import numpy as np
import pandas as pd
import rateslib as rl

from dd_common import CURVE_FOR, make_pricer, strict_policy
from MDP.IRSwaps.BARCHART_STIRF.risk import build_delta_risk_ladder
from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapValue import IRSwapValue
from Query.IRSwaps.backends.rateslib.rl_curve_definitions_map import (
    RATESLIB_CURVE_DEFINITIONS,
)

pd.set_option("display.width", 250)
NY = "America/New_York"

P28 = ["1M", "2M", "3M", "4M", "6M", "9M", "1Y", "15M", "18M", "21M", "2Y", "30M",
       "3Y", "4Y", "5Y", "6Y", "7Y", "8Y", "9Y", "10Y", "11Y", "12Y", "15Y", "20Y",
       "25Y", "30Y", "40Y", "50Y"]
P21 = ["3M", "6M", "9M", "1Y", "18M", "2Y", "3Y", "4Y", "5Y", "6Y", "7Y", "8Y", "9Y",
       "10Y", "11Y", "12Y", "15Y", "20Y", "25Y", "30Y", "40Y"]
P15 = ["3M", "6M", "1Y", "18M", "2Y", "3Y", "4Y", "5Y", "7Y", "10Y", "12Y", "15Y",
       "20Y", "25Y", "30Y"]
P28_no11 = [t for t in P28 if t != "11Y"]
P28_no40 = [t for t in P28 if t not in ("40Y", "50Y")]

TS = pd.Timestamp("2026-06-16 11:00", tz=NY)
PRICER = make_pricer(strict_policy(1.0))


def handles(curve_name, ts):
    """(stripped-fixings handle for the solver, full-fixings twin for pricing)."""
    h0 = PRICER.handle(curve_name, ts)
    meta = dict(h0._meta_data)
    meta["requested_curve_name"] = curve_name
    fx = h0.index()
    return (RLIRSwapCurve(h0.id(), h0.handle(), fx.iloc[0:0], meta),
            RLIRSwapCurve(h0.id(), h0.handle(), fx, dict(meta)), fx)


# ==========================================================================
# (a) FED_FUNDS
# ==========================================================================
print("=" * 100)
print("(a) FED_FUNDS curve definition")
for key in ("USD-SOFR-1D", "USD-FEDFUNDS-1D", "USD-SOFR-1D-RISK",
            "USD-FEDFUNDS-1D-RISK"):
    print(f"    RATESLIB_CURVE_DEFINITIONS has {key:24s}: "
          f"{key in RATESLIB_CURVE_DEFINITIONS}")

for idx in ("SOFR", "FED_FUNDS"):
    nm = CURVE_FOR[idx]
    h_strip, h_full, fx = handles(nm, TS)
    dense = h_strip.handle()
    print(f"\n  [{idx}] curve={nm} id={h_strip.id()} ref={h_strip.reference_date()} "
          f"nodes={len(dense.nodes.nodes)} conv={dense.meta.convention} "
          f"cal={dense.meta.calendar} fixings={len(fx)}")
    try:
        h_strip._curve_definition()
        print("        _curve_definition() -> OK (in the map)")
    except Exception as e:                                     # noqa: BLE001
        print(f"        _curve_definition() -> {type(e).__name__}: {e}")
    t0 = time.perf_counter()
    try:
        rc, slv = build_delta_risk_ladder(P28, h_strip, timestamp=TS)
        dt = time.perf_counter() - t0
        J = np.asarray(slv.J)
        print(f"        build_delta_risk_ladder(P28) -> OK in {dt*1000:.0f} ms, "
              f"labels match={list(slv.instrument_labels) == P28}, "
              f"J{J.shape} cond={np.linalg.cond(J):.3f}")
        print("        par (%): " + "  ".join(
            f"{lab}={s:.4f}" for lab, s in zip(slv.instrument_labels, np.asarray(slv.s))
            if lab in ("1M", "3M", "1Y", "2Y", "5Y", "10Y", "30Y", "50Y")))
        rcurve = rc.handle()
        print(f"        risk curve id={rc.id()} nodes={len(rcurve.nodes.nodes)} "
              f"conv={rcurve.meta.convention} cal={rcurve.meta.calendar}")
    except Exception as e:                                     # noqa: BLE001
        print(f"        build_delta_risk_ladder -> {type(e).__name__}: {e}")


# ==========================================================================
# (b) grid validation on SOFR
# ==========================================================================
print("\n" + "=" * 100)
print("(b) 28-pillar grid validation, SOFR")
name = CURVE_FOR["SOFR"]
h_strip, h_full, FX = handles(name, TS)
dense = h_strip.handle()
REF = h_strip.reference_date()
SPOT = rl.get_calendar("nyc").lag_bus_days(REF, 2, True)
print(f"  ref={REF} spot={SPOT}")

models = {}
for tag, pil in (("K28", P28), ("K21", P21), ("K15", P15),
                 ("K27_no11Y", P28_no11), ("K26_no40Y+", P28_no40)):
    tt = []
    for _ in range(2):
        t0 = time.perf_counter()
        rc, slv = build_delta_risk_ladder(pil, h_strip, timestamp=TS)
        tt.append(time.perf_counter() - t0)
    rc_fix = RLIRSwapCurve(rc.id(), rc.handle(), FX, dict(rc._meta_data))
    models[tag] = (pil, rc, rc_fix, slv, statistics.median(tt))
    print(f"  [{tag:11s}] K={len(pil):2d}  build {statistics.median(tt)*1000:6.0f} ms  "
          f"cond(J)={np.linalg.cond(np.asarray(slv.J)):8.3f}")

# ---- reprice tie-out: does the reduced risk curve reprice the dense curve's pars?
pil, rc28, rc28f, slv28, _ = models["K28"]
errs = []
for tnr in P28:
    q_d = IRSwapQuery(curve=name, tenor=tnr).resolve_query(TS, pricer_or_curve=h_full)
    r_d = float(q_d.resolve_package(pricer_or_curve=h_full)[0][0].rate().real)
    q_r = IRSwapQuery(curve=name, tenor=tnr).resolve_query(TS, pricer_or_curve=rc28f)
    r_r = float(q_r.resolve_package(pricer_or_curve=rc28f)[0][0].rate().real)
    errs.append((tnr, r_d, r_r, (r_r - r_d) * 1e4))
edf = pd.DataFrame(errs, columns=["tenor", "dense_pct", "risk_pct", "diff_bp"])
print("\n  reprice tie-out (risk curve vs dense curve, bp):")
print("   " + edf.round(6).to_string(index=False).replace("\n", "\n   "))
print(f"  max|reprice err| = {edf['diff_bp'].abs().max():.8f} bp")

# ---- necessity of 11Y and 40Y/50Y
fwd1 = rl.add_tenor(SPOT, "1Y", "MF", "nyc")
fwd5 = rl.add_tenor(SPOT, "5Y", "MF", "nyc")
CASES = [
    ("spot 2Y payer", SPOT, rl.add_tenor(SPOT, "2Y", "MF", "nyc"), 200e6, 0.0392),
    ("spot 10Y payer", SPOT, rl.add_tenor(SPOT, "10Y", "MF", "nyc"), 100e6, 0.0404),
    ("spot 11Y payer", SPOT, rl.add_tenor(SPOT, "11Y", "MF", "nyc"), 100e6, 0.0407),
    ("spot 30Y recv", SPOT, rl.add_tenor(SPOT, "30Y", "MF", "nyc"), -50e6, 0.0423),
    ("spot 40Y payer", SPOT, rl.add_tenor(SPOT, "40Y", "MF", "nyc"), 50e6, 0.0412),
    ("spot 50Y payer", SPOT, rl.add_tenor(SPOT, "50Y", "MF", "nyc"), 25e6, 0.0399),
    ("1Yx10Y receiver", fwd1, rl.add_tenor(fwd1, "10Y", "MF", "nyc"), -150e6, 0.0410),
    ("5Yx5Y payer", fwd5, rl.add_tenor(fwd5, "5Y", "MF", "nyc"), 300e6, 0.0420),
    ("past-eff 5Y payer", datetime.date(2024, 3, 15), datetime.date(2029, 3, 15),
     50e6, 0.0425),
    ("7Y off-mkt payer", SPOT, rl.add_tenor(SPOT, "7Y", "MF", "nyc"), 250e6, 0.0250),
]


def krd(rc_plain, rc_fixed, slv, eff, mat, notl, fr_dec):
    past = pd.Timestamp(eff).date() < pd.Timestamp(REF).date()
    rcx = rc_fixed if past else rc_plain
    q = IRSwapQuery(curve=name, effective_date=pd.Timestamp(eff).date(),
                    maturity_date=pd.Timestamp(mat).date(),
                    structure_kwargs={"notional": float(notl),
                                      "fixed_rate": float(fr_dec)},
                    ).resolve_query(TS, pricer_or_curve=rcx)
    pkg, rws = q.resolve_package(pricer_or_curve=rcx)
    d = rl.Portfolio(pkg).delta(solver=slv).iloc[:, 0]
    return ({str(k[-1]): float(v) for k, v in d.items()}, q, pkg, rws, rcx)


print("\n  sum(delta) vs PV01, and bucket-grid necessity (max |reduced - K28| as % of "
      "the trade's total DV01):")
rows = []
for nm_, eff, mat, notl, fr in CASES:
    m28, q, pkg, rws, rcx = krd(rc28, rc28f, slv28, eff, mat, notl, fr)
    pv01 = float(q.build_value_map(pricer_or_curve=rcx, package=pkg,
                                   risk_weights=rws).apply(value=IRSwapValue.PV01))
    tot = sum(m28.values())
    rec = {"case": nm_, "sum_K28": tot, "pv01": pv01, "ratio": tot / pv01}
    for tag in ("K21", "K15", "K27_no11Y", "K26_no40Y+"):
        pl, rcp, rcf, sv, _ = models[tag]
        m, *_ = krd(rcp, rcf, sv, eff, mat, notl, fr)
        keys = set(m) | set(m28)
        rec[tag] = max(abs(m.get(k, 0.0) - m28.get(k, 0.0)) for k in keys) / abs(tot) * 100
    rows.append(rec)
out = pd.DataFrame(rows)
print("   " + out.to_string(index=False, float_format=lambda v: f"{v:,.4f}"
                            ).replace("\n", "\n   "))

# ---- where does a 50Y trade's risk land?
print("\n  50Y payer 25mm placement, K28 vs a 30Y-capped grid:")
m28, *_ = krd(rc28, rc28f, slv28, SPOT, rl.add_tenor(SPOT, "50Y", "MF", "nyc"),
              25e6, 0.0399)
pl, rcp, rcf, sv, _ = models["K26_no40Y+"]
m26, *_ = krd(rcp, rcf, sv, SPOT, rl.add_tenor(SPOT, "50Y", "MF", "nyc"), 25e6, 0.0399)
for k in ("20Y", "25Y", "30Y", "40Y", "50Y"):
    print(f"    {k:4s}  K28 {m28.get(k, 0.0):14,.1f}   no40Y+ {m26.get(k, 0.0):14,.1f}")
print(f"    SUM   K28 {sum(m28.values()):14,.1f}   no40Y+ {sum(m26.values()):14,.1f}")

# ---- does Portfolio.delta aggregate across instruments?
print("\n  does rl.Portfolio.delta aggregate across instruments? (batching check)")
a = IRSwapQuery(curve=name, effective_date=pd.Timestamp(SPOT).date(),
                maturity_date=pd.Timestamp(rl.add_tenor(SPOT, "2Y", "MF", "nyc")).date(),
                structure_kwargs={"notional": 100e6, "fixed_rate": 0.04},
                ).resolve_query(TS, pricer_or_curve=rc28).resolve_package(
                    pricer_or_curve=rc28)[0]
b = IRSwapQuery(curve=name, effective_date=pd.Timestamp(SPOT).date(),
                maturity_date=pd.Timestamp(rl.add_tenor(SPOT, "10Y", "MF", "nyc")).date(),
                structure_kwargs={"notional": 100e6, "fixed_rate": 0.04},
                ).resolve_query(TS, pricer_or_curve=rc28).resolve_package(
                    pricer_or_curve=rc28)[0]
d_ab = rl.Portfolio(list(a) + list(b)).delta(solver=slv28)
d_a = rl.Portfolio(a).delta(solver=slv28)
d_b = rl.Portfolio(b).delta(solver=slv28)
print(f"    shape(2 instruments) = {d_ab.shape}, columns = {list(d_ab.columns)}")
print(f"    max|d(a+b) - (d(a)+d(b))| = "
      f"{np.abs(d_ab.iloc[:, 0].to_numpy() - (d_a.iloc[:, 0].to_numpy() + d_b.iloc[:, 0].to_numpy())).max():.3e}")


def timeit(fn, n=8):
    fn()
    t = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        t.append(time.perf_counter() - t0)
    return statistics.median(t) * 1000


print("\n  per-unit cost on the risk handle (no fixings attached):")
for tnr in ("2Y", "10Y", "30Y"):
    mt = rl.add_tenor(SPOT, tnr, "MF", "nyc")

    def build():
        return IRSwapQuery(curve=name, effective_date=pd.Timestamp(SPOT).date(),
                           maturity_date=pd.Timestamp(mt).date(),
                           structure_kwargs={"notional": 100e6, "fixed_rate": 0.04},
                           ).resolve_query(TS, pricer_or_curve=rc28).resolve_package(
                               pricer_or_curve=rc28)[0]

    pk = build()
    print(f"    {tnr:4s} build {timeit(build):6.3f} ms | "
          f"Portfolio.delta {timeit(lambda: rl.Portfolio(pk).delta(solver=slv28)):6.3f} ms")
