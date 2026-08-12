"""KS taken against the CENSORED parameters instead of the truncated ones.

The shipped ks_* are truncation-only fits. The CellFit comment claims that
switching to the censored parameters changes the worst cell but not the
conclusion -- measure it rather than assert it.
"""
import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from imp_fix01_sweep import load  # noqa: E402
from SDRUtils.dealer_direction import imputation as imp  # noqa: E402

freq = load()
shipped = {(b.vintage, b.lo): b for b in imp.CAP_BANDS}
ln_wins = par_wins = 0
worst = 0.0
for cell, g in freq.groupby("cell", sort=True):
    C = float(g["cap"].iloc[0])
    u = C / 4.0
    sub = g[~g["is_capped"]]
    t = sub[(sub["notional"] >= u) & (sub["notional"] < C)]
    x, w = t["notional"].to_numpy(float), t["n"].to_numpy(float)
    b = shipped[(g["vintage"].iloc[0], float(g["lo"].iloc[0]))]
    ks_c = imp.weighted_ks(x, w, lambda q: imp.lognormal_cdf_truncated(
        q, b.ln_mu, b.ln_sigma, u, C))
    worst = max(worst, ks_c)
    ln_wins += ks_c < b.ks_pareto
    par_wins += b.ks_pareto < ks_c
    print(f"{b.vintage} {b.label:8s} ks_ln(truncated)={b.ks_lognormal:.4f}  "
          f"ks_ln(censored)={ks_c:.4f}  ks_pareto={b.ks_pareto:.4f}")
print(f"\ncensored-parameter KS: worst {worst:.4f}, lognormal wins {ln_wins}, "
      f"pareto wins {par_wins}")
