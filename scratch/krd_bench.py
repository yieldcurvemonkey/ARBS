"""Measure cost of a per-trade key-rate DV01 profile: rateslib solver vs analytic.

Run:  ARBS_SUPABASE_ENABLED=0 python scratch/krd_bench.py
"""
import os, sys, time, datetime, statistics, json
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
import numpy as np
import pandas as pd
import rateslib as rl
from Caching.curve_store import CurveStore

NAME_SOFR = "USD-SOFR-1D-CITIVELOEXCELMIN"
DAY = datetime.date(2026, 6, 15)
LADDER = ["3M", "6M", "1Y", "18M", "2Y", "3Y", "4Y", "5Y", "7Y",
          "10Y", "12Y", "15Y", "20Y", "25Y", "30Y"]


def timeit(fn, n=10, warm=2):
    for _ in range(warm):
        fn()
    ts = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        ts.append(time.perf_counter() - t0)
    return statistics.median(ts), min(ts), statistics.mean(ts)


# ---------------------------------------------------------------- curve
store = CurveStore.default()
t0 = time.perf_counter()
raw = store.read_raw_nodes(NAME_SOFR, start=DAY, end=DAY)
t_read_day = time.perf_counter() - t0
row = raw.iloc[len(raw) // 2].to_dict()
print(f"[read] read_raw_nodes one day: {t_read_day*1000:.1f} ms for {len(raw)} minute rows "
      f"({t_read_day/len(raw)*1e6:.1f} us/minute-row)")

med, mn, mean = timeit(lambda: CurveStore.reconstruct_curve(row), n=50)
print(f"[curve] reconstruct_curve: median {med*1000:.3f} ms  min {mn*1000:.3f} ms")

curve = CurveStore.reconstruct_curve(row)
REF = curve.nodes.initial
print(f"[curve] ref={REF} nodes={len(curve.nodes.nodes)} interp={row['interpolation']} ts={row['timestamp_utc']}")

CAL = rl.get_calendar("nyc")
SPOT = CAL.lag_bus_days(REF, 2, True) if hasattr(CAL, "lag_bus_days") else rl.add_tenor(REF, "2B", "F", "nyc")
print(f"[curve] spot={SPOT}")


def mk_irs(term, curves, notional=100e6, fixed_rate=None, effective=None):
    kw = dict(effective=effective or SPOT, termination=term, spec="usd_irs",
              curves=curves, notional=notional)
    if fixed_rate is not None:
        kw["fixed_rate"] = fixed_rate
    return rl.IRS(**kw)


med, mn, mean = timeit(lambda: mk_irs("10Y", curve), n=50)
print(f"[inst] rl.IRS(10Y) construction: median {med*1000:.3f} ms  min {mn*1000:.3f} ms")

# ---------------------------------------------------------------- ladder solver
t0 = time.perf_counter()
ladder_insts_dense = [mk_irs(t, curve) for t in LADDER]
par = [float(i.rate(curves=curve).real) for i in ladder_insts_dense]
mats = [i.leg1.schedule.termination for i in ladder_insts_dense]
t_par = time.perf_counter() - t0
print(f"[ladder] {len(LADDER)} par rates from dense curve: {t_par*1000:.1f} ms")
print("[ladder] par:", {t: round(p, 4) for t, p in zip(LADDER, par)})


def build_solver():
    nodes = {REF: 1.0}
    for m in mats:
        nodes[m] = float(curve[m])
    rc = rl.Curve(nodes=dict(sorted(nodes.items())), convention=curve.meta.convention,
                  calendar=curve.meta.calendar, modifier=curve.meta.modifier,
                  interpolation="log_linear", id="RISK")
    insts = [mk_irs(t, rc) for t in LADDER]
    slv = rl.Solver(curves=[rc], instruments=insts, s=par, instrument_labels=LADDER,
                    id="RISK", func_tol=1e-8, conv_tol=1e-10)
    return rc, slv


med, mn, mean = timeit(build_solver, n=5, warm=1)
print(f"[ladder] build risk curve + rl.Solver ({len(LADDER)} inst): median {med*1000:.1f} ms  min {mn*1000:.1f} ms")
risk_curve, solver = build_solver()
print(f"[ladder] solver result: {getattr(solver, 'result', {}).get('status', '?')} "
      f"iters={getattr(solver, 'result', {}).get('iterations', '?')}")

# ---------------------------------------------------------------- delta timings
TEST_TERM = "10Y"
TEST_N = 100e6
TEST_K = par[LADDER.index("10Y")]

swap_risk = mk_irs(TEST_TERM, risk_curve, notional=TEST_N, fixed_rate=TEST_K)
med1, mn1, _ = timeit(lambda: rl.Portfolio([swap_risk]).delta(solver=solver), n=10, warm=2)
print(f"[delta] 1 swap  Portfolio.delta(solver): median {med1*1000:.1f} ms  min {mn1*1000:.1f} ms")

rng = np.random.default_rng(0)
terms100 = [f"{int(x)}Y" for x in rng.integers(1, 31, 100)]
t0 = time.perf_counter()
pkg100 = [mk_irs(t, risk_curve, notional=100e6, fixed_rate=3.5) for t in terms100]
t_build100 = time.perf_counter() - t0
print(f"[delta] build 100 rl.IRS on risk curve: {t_build100*1000:.1f} ms ({t_build100/100*1000:.3f} ms/swap)")

med100, mn100, _ = timeit(lambda: rl.Portfolio(pkg100).delta(solver=solver), n=5, warm=1)
print(f"[delta] 100 swaps Portfolio.delta(solver): median {med100*1000:.1f} ms  min {mn100*1000:.1f} ms "
      f"-> {med100/100*1000:.2f} ms/swap marginal")

t0 = time.perf_counter()
pkg500 = [mk_irs(f"{int(x)}Y", risk_curve, notional=100e6, fixed_rate=3.5)
          for x in rng.integers(1, 31, 500)]
t_b500 = time.perf_counter() - t0
med500, mn500, _ = timeit(lambda: rl.Portfolio(pkg500).delta(solver=solver), n=3, warm=1)
print(f"[delta] build 500 rl.IRS: {t_b500*1000:.1f} ms; 500-swap delta median {med500*1000:.1f} ms "
      f"-> {med500/500*1000:.2f} ms/swap marginal")

d1 = rl.Portfolio([swap_risk]).delta(solver=solver)
print("[delta] shape", d1.shape, "index sample", list(d1.index[:3]))
col = d1.columns[0]
solver_delta = d1[col].copy()
solver_delta.index = [ix[-1] if isinstance(ix, tuple) else ix for ix in solver_delta.index]
print("[delta] 10Y payer $100mm solver par delta (USD per bp):")
print(solver_delta.round(2).to_string())
print(f"[delta] sum = {solver_delta.sum():.2f}")

np.save(os.path.join(os.path.dirname(__file__), "_solver_delta.npy"), solver_delta.values)
with open(os.path.join(os.path.dirname(__file__), "_bench_ctx.json"), "w") as f:
    json.dump({"par": par, "mats": [str(m) for m in mats], "spot": str(SPOT),
               "ref": str(REF), "test_k": TEST_K}, f)
