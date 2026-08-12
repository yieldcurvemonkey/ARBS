"""Two questions the shipped fitter cannot currently answer, at u = C/4.

1. Does inspecting ``r.success`` change the answer?  The restart grid keeps the
   lowest ``fun`` without ever looking at convergence.  If best-overall is always
   a converged run, the guard is free; if not, it changes numbers and has to be
   argued for rather than added.
2. How much of the imputed DV01 rests on cells whose fit is bound-determined?
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import numpy as np
import pandas as pd
from scipy import optimize

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from SDRUtils.dealer_direction import imputation as imp  # noqa: E402
from imp_fix01_sweep import BUCKET, load, run  # noqa: E402

SLACK = float(sys.argv[1]) if len(sys.argv) > 1 else 150.0
imp.LN_MU_SLACK = SLACK


def restarts(x, w, u, C, n_cap):
    log_x, log_u, log_C = np.log(x), np.log(u), np.log(C)
    S = imp._suffstats(log_x, np.asarray(w, dtype=float))
    W, S1, S2 = S
    m0 = S1 / W
    s0 = float(np.sqrt(max(S2 / W - m0 * m0, 1e-6)))
    out = []
    for mu0 in (m0, m0 - 1.0, m0 - 3.0, log_u):
        for sigma0 in (s0, 2 * s0, 1.0, 2.5):
            r = optimize.minimize(imp._ln_negll, [mu0, np.log(sigma0)],
                                  args=(S, log_u, log_C, n_cap),
                                  method="Nelder-Mead",
                                  options={"maxiter": 4000, "xatol": 1e-9,
                                           "fatol": 1e-9})
            out.append(r)
    return out


freq = load()
print(f"LN_MU_SLACK = {SLACK}\n")
print(f"{'cell':14s} {'runs':>5s} {'maxiter':>8s} {'best ok':>8s} "
      f"{'converged-best == overall-best':>32s}")
n_bad = 0
for cell, g in freq.groupby("cell", sort=True):
    C = float(g["cap"].iloc[0])
    u = C / 4.0
    cap_rows, sub = g[g["is_capped"]], g[~g["is_capped"]]
    n_cap = float(cap_rows.loc[cap_rows["notional"] == C, "n"].sum())
    t = sub[(sub["notional"] >= u) & (sub["notional"] < C)]
    for label, ncap_arg in (("cens", n_cap), ("trunc", None)):
        rs = restarts(t["notional"].to_numpy(float), t["n"].to_numpy(float),
                      u, C, ncap_arg)
        best = min(rs, key=lambda r: r.fun)
        conv = [r for r in rs if r.success]
        best_conv = min(conv, key=lambda r: r.fun) if conv else None
        same = (best_conv is not None
                and np.allclose(best_conv.x, best.x, rtol=0, atol=1e-9))
        n_bad += not same
        key = f"{cell.split('|')[0]} {cell.split('|')[1]}"
        print(f"{key:9s} {label:5s} {len(rs):5d} {sum(not r.success for r in rs):8d} "
              f"{str(best.success):>8s} {str(same):>32s}"
              + ("" if same else f"   d(fun)={best_conv.fun - best.fun:.3e}"
                 if best_conv else "   NO CONVERGED RUN"))
print(f"\ncells where best-among-converged differs from best-overall: {n_bad}")

# ---------------------------------------------------------------- degeneracy
d = run(freq, ("div", 4.0))
deg = pd.Series(d["degenerate"]).fillna(False).astype(bool)
exc = d["exc_dv01"]
capped_at_cap_dv01 = float((d["n_cap"] * d["cap"] * d["cap_mean_t"] * 1e-4).sum())
tot = float(d["tot_dv01"].sum())
print(f"\nimputed excess DV01 from bound-determined cells: "
      f"{exc[deg].sum() / exc.sum():.4f} of all excess "
      f"({int(deg.sum())} cells: {[f'{v} {lo}' for v, lo in zip(d.vintage[deg], d.lo[deg])]})")
print(f"capped-at-cap DV01 share of the tape proxy: {capped_at_cap_dv01 / tot:.4f}")
print(f"DV01-weighted effective multiplier k: "
      f"{1.0 + exc.sum() / capped_at_cap_dv01:.4f}")
k = 1.0 + exc.sum() / capped_at_cap_dv01
c = capped_at_cap_dv01 / tot
print(f"flat-k cross-check (k-1)c/(1+(k-1)c) = {(k - 1) * c / (1 + (k - 1) * c):.4f}")
imp.LN_MU_SLACK = 30.0
