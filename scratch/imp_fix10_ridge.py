"""Is the degenerate cell's likelihood really monotone toward larger sigma, or
does it turn over just outside the box? The docstring claims the former."""
import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import numpy as np  # noqa: E402

from imp_fix01_sweep import load  # noqa: E402
from SDRUtils.dealer_direction import imputation as imp  # noqa: E402

freq = load()
for cell in ("V1|5.25|10.5|170000000", "V2|0.0|0.12|17000000000",
             "V1|2.25|5.25|240000000"):
    g = freq[freq["cell"] == cell]
    C = float(g["cap"].iloc[0])
    u = C / 4.0
    cap_rows, sub = g[g["is_capped"]], g[~g["is_capped"]]
    n_cap = float(cap_rows.loc[cap_rows["notional"] == C, "n"].sum())
    t = sub[(sub["notional"] >= u) & (sub["notional"] < C)]
    x, w = t["notional"].to_numpy(float), t["n"].to_numpy(float)
    S = imp._suffstats(np.log(x), w)
    print(f"\n{cell}")
    for smax in (6.0, 8.0, 12.0, 20.0, 40.0):
        imp.LN_SIGMA_MAX = smax
        mu, sg = imp.lognormal_censored_mle(x, w, u, C, n_cap)
        negll = imp._ln_negll([mu, np.log(sg)], S, np.log(u), np.log(C), n_cap)
        mult = imp.lognormal_mean_above(mu, sg, C) / C
        print(f"  LN_SIGMA_MAX={smax:5.1f}  mu={mu:10.3f} sigma={sg:7.3f} "
              f"negll={negll:.6f} mult={mult:7.3f}")
imp.LN_SIGMA_MAX = 6.0
