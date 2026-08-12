"""Is 'the censored fit converged' free across the WHOLE sensitivity sweep?

The diag at u = C/4 says every censored restart grid has a converged best. If
that holds at all six thresholds the convergence guard costs nothing and can
raise; if it does not, raising would break the refit it is meant to protect.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from SDRUtils.dealer_direction import imputation as imp  # noqa: E402
from imp_fix01_sweep import GRID, load  # noqa: E402
from imp_fix03_diag import restarts  # noqa: E402

SLACK = float(sys.argv[1]) if len(sys.argv) > 1 else 150.0
imp.LN_MU_SLACK = SLACK

freq = load()
print(f"LN_MU_SLACK = {SLACK}")
rows = []
for th in GRID:
    for cell, g in freq.groupby("cell", sort=True):
        C = float(g["cap"].iloc[0])
        cap_rows, sub = g[g["is_capped"]], g[~g["is_capped"]]
        n_cap = float(cap_rows.loc[cap_rows["notional"] == C, "n"].sum())
        if th[0] == "div":
            u = C / th[1]
        else:
            v = g.sort_values("notional")
            cw = v["n"].cumsum() / v["n"].sum()
            u = float(v.loc[cw >= th[1], "notional"].iloc[0])
            u = min(max(u, C / 50), C / 1.8)
        t = sub[(sub["notional"] >= u) & (sub["notional"] < C)]
        w = t["n"].to_numpy(float)
        if not len(t) or w.sum() < imp.MIN_TAIL_WEIGHT or len(t) < imp.MIN_TAIL_POINTS:
            continue
        for label, arg in (("cens", n_cap), ("trunc", None)):
            rs = restarts(t["notional"].to_numpy(float), w, u, C, arg)
            best = min(rs, key=lambda r: r.fun)
            conv = [r for r in rs if r.success]
            rows.append({
                "threshold": f"{th[0]}{th[1]:g}", "cell": cell.rsplit("|", 1)[0],
                "fit": label, "best_ok": bool(best.success),
                "any_converged": bool(conv),
                "d_fun_if_forced_converged":
                    (min(conv, key=lambda r: r.fun).fun - best.fun) if conv else np.nan,
            })
d = pd.DataFrame(rows)
for label in ("cens", "trunc"):
    s = d[d["fit"] == label]
    bad = s[~s["best_ok"]]
    print(f"\n{label}: {len(s)} fits, best-run non-converged in {len(bad)}, "
          f"no converged run at all in {int((~s['any_converged']).sum())}")
    if len(bad):
        print(bad[["threshold", "cell", "any_converged",
                   "d_fun_if_forced_converged"]].to_string(index=False))
imp.LN_MU_SLACK = 30.0
