"""Adversarial pass 5: the null is calibrated on THREE permutations, not 5,760 cells.

The report treats "placebo max |HAC t| = 3.36 over its own 5,760 cells" as the empirical
null hurdle.  Those 5,760 cells come from only N_PLACEBO=3 random label permutations, so
the statistic "max |t| over one permutation's cells" has been sampled three times.  Its
sampling distribution is what a real signal's max must clear.  Re-draw it 40 times.

Also here: the cost anchor, and one hand-computed trade.
"""
from __future__ import annotations
import pathlib, sys, time
import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import etf_tsgrid_lib as L

DATA = L.DATA
H = L.CLOCK_HOURS
HOLDS = [0, 1, 5, 21]
STRUCTURAL_EXITS = (15, 16)
N_PERM = int(sys.argv[1]) if len(sys.argv) > 1 else 40


def exit_specs(entry):
    out = [(0, x) for x in H if x > entry]
    for hold in HOLDS[1:]:
        for x in dict.fromkeys((entry,) + STRUCTURAL_EXITS):
            out.append((hold, x))
    return out


t0 = time.time()
m = L.load_matrices()
legs = L.build_legs(m, step=1)
FLY = {h: L.fly_level(m, legs, h) for h in H}
COST = L.package_cost_bp(m, legs, anchor="measured")
RET = {}
for entry in H:
    for hold, ex in exit_specs(entry):
        fe = FLY[ex]
        if hold > 0:
            sh = np.full_like(fe, np.nan); sh[:-hold] = fe[hold:]; fe = sh
        RET[(entry, hold, ex)] = -(fe - FLY[entry]) * 100.0
ELIG = {(mk, en): (legs.valid & np.isfinite(FLY[mk]) & np.isfinite(FLY[en]))
        for mk in H for en in H if en >= mk}

raw = L.build_signal_matrices(m, fund="TLT")
perm_cols = np.random.default_rng(L.TIE_SEED).permutation(m.T.shape[1]).astype(float)


def permute_rows(M, seed):
    g = np.random.default_rng(seed)
    out = np.full_like(M, np.nan)
    for d in range(M.shape[0]):
        row = M[d]
        ok = np.where(np.isfinite(row))[0]
        if ok.size:
            out[d, g.permutation(ok)] = row[ok]
    return out


def run_one(M0, lag=1):
    """All (mark, orth, entry, hold, exit) cells for one signal matrix -> DataFrame."""
    Ml = L.lag_matrix(M0, lag)
    rows = []
    for mark in H:
        Zbase = L._xsec_z(Ml)
        for orth in (False, True):
            Z = L.orthogonalize(Zbase, m.RESZ[mark]) if orth else Zbase
            for entry in [e for e in H if e >= mark]:
                sel = L.select(Z, ELIG[(mark, entry)], n=3, rng_perm=perm_cols)
                if not sel.usable.any():
                    continue
                for hold, ex in exit_specs(entry):
                    g, c, ntr = L.cell_pnl(RET[(entry, hold, ex)], COST, sel)
                    fin = np.isfinite(g)
                    if fin.sum() < 50:
                        continue
                    w = ntr[fin].astype(float)
                    rows.append(dict(mark=mark, orth=orth, entry=entry, hold=hold, exit=ex,
                                     n=int(fin.sum()),
                                     gross=float(np.average(g[fin], weights=w)),
                                     cost=float(np.average(c[fin], weights=w)),
                                     t=L.newey_west_t(g, max(1, hold))))
    return pd.DataFrame(rows)


# -------------------------------------------------------------- the permutation null
res = []
for k in range(N_PERM):
    P = permute_rows(raw["active_w"], 10_000 + 31 * k)
    d = run_one(P)
    res.append(dict(perm=k, cells=len(d), max_abs_t=float(d.t.abs().max()),
                    p99_abs_t=float(d.t.abs().quantile(.99)),
                    max_gross=float(d.gross.max()),
                    max_breakeven=float((d.gross / d.cost).max())))
    print("perm %2d: cells %d  max|t| %.2f  max gross %.4f  max BE %.4fx  (%.0fs)"
          % (k, len(d), res[-1]["max_abs_t"], res[-1]["max_gross"],
             res[-1]["max_breakeven"], time.time() - t0), flush=True)
nul = pd.DataFrame(res)
nul.to_csv(DATA / "adv_ts_permutation_null.csv", index=False)
print("\n=== PERMUTATION NULL over %d draws (960 cells each) ===" % N_PERM)
print("max|t| : mean %.2f  median %.2f  p90 %.2f  p95 %.2f  max %.2f" %
      (nul.max_abs_t.mean(), nul.max_abs_t.median(), nul.max_abs_t.quantile(.90),
       nul.max_abs_t.quantile(.95), nul.max_abs_t.max()))
print("max gross : median %.4f bp  p95 %.4f bp" % (nul.max_gross.median(), nul.max_gross.quantile(.95)))
print("max break-even : median %.4fx  p95 %.4fx" % (nul.max_breakeven.median(), nul.max_breakeven.quantile(.95)))

# -------------------------------------------------------------- real signals, same shape
real = []
for s in L.HOLDINGS_SIGNALS + L.CALENDAR_SIGNALS:
    d = run_one(raw[s])
    real.append(dict(signal=s, cells=len(d), max_abs_t=float(d.t.abs().max()),
                     max_gross=float(d.gross.max()),
                     max_breakeven=float((d.gross / d.cost).max())))
    print("real %-14s cells %4d  max|t| %.2f  max gross %.4f  max BE %.4fx"
          % (s, len(d), real[-1]["max_abs_t"], real[-1]["max_gross"], real[-1]["max_breakeven"]), flush=True)
rl = pd.DataFrame(real)
rl.to_csv(DATA / "adv_ts_real_vs_null.csv", index=False)
q = nul.max_abs_t
for _, r in rl.iterrows():
    p = float((q >= r.max_abs_t).mean())
    print("  %-14s max|t| %.2f -> permutation p = %.3f" % (r.signal, r.max_abs_t, p))
