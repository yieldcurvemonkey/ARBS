"""Does the docstring's "KS favours the lognormal in 13 of 18 cells at u = C/10"
still hold with the mu box unbound? Both KS statistics come from the truncated
fits, and two of those were on the wall at u = C/4."""
import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from imp_fix01_sweep import load, run  # noqa: E402
from SDRUtils.dealer_direction import imputation as imp  # noqa: E402

freq = load()
for th in (("div", 10.0), ("div", 4.0)):
    d = run(freq, th).dropna(subset=["ks_ln"])
    ln = int((d["ks_ln"] < d["ks_par"]).sum())
    par = int((d["ks_par"] < d["ks_ln"]).sum())
    tie = len(d) - ln - par
    print(f"u=C/{th[1]:g} (slack {imp.LN_MU_SLACK}): lognormal {ln}, pareto {par}, "
          f"ties {tie}, of {len(d)} fitted; "
          f"ks_ln [{d['ks_ln'].min():.4f}, {d['ks_ln'].max():.4f}] "
          f"ks_par [{d['ks_par'].min():.4f}, {d['ks_par'].max():.4f}] "
          f"max gap {(d['ks_ln'] - d['ks_par']).abs().max():.4f}")
