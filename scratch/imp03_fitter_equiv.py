"""Is the shipped fitter the same estimator the probe validated, or did I break it?

Two checks, in order:
  1. bit-comparison against scratch/partB_tail_fit.py on identical inputs;
  2. for the case the new test failed on, whether the fit's log-likelihood
     beats the TRUE parameters' -- if it does, the optimiser is fine and the
     sample simply does not identify mu.
"""
import os, sys
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, r"C:\Users\chris\clee\ARBS-dd")
sys.path.insert(0, r"C:\Users\chris\clee\ARBS-dd\scratch")
import numpy as np
import partB_tail_fit as probe
from SDRUtils.dealer_direction import imputation as imp

rng = np.random.default_rng(20260811)
u, cap = 5e7, 5e8
print(f"{'mu':>6} {'sig':>5} {'n_sub':>7} {'n_cap':>6} | "
      f"{'probe mu':>9} {'probe s':>8} | {'mine mu':>9} {'mine s':>8} | "
      f"{'ll(fit)':>14} {'ll(true)':>14} {'E fit':>11} {'E sample':>11}")
for mu_t, s_t in ((17.0, 1.2), (16.0, 1.8), (18.0, 0.9), (17.4, 1.5)):
    z = np.exp(rng.normal(mu_t, s_t, 120_000))
    z = z[z >= u]
    sub, above = z[z < cap], z[z >= cap]
    n_cap = len(above)
    w = np.ones_like(sub)
    pm, ps, _ = probe.lognorm_censored_mle(sub, w, u, cap, n_cap)
    mm, ms = imp.lognormal_censored_mle(sub, w, u, cap, n_cap)
    S = imp._suffstats(np.log(sub), w)
    ll_fit = -imp._ln_negll([mm, np.log(ms)], S, np.log(u), np.log(cap), float(n_cap))
    ll_true = -imp._ln_negll([mu_t, np.log(s_t)], S, np.log(u), np.log(cap), float(n_cap))
    E = imp.lognormal_mean_above(mm, ms, cap)
    print(f"{mu_t:>6.2f} {s_t:>5.2f} {len(sub):>7} {n_cap:>6} | "
          f"{pm:>9.4f} {ps:>8.4f} | {mm:>9.4f} {ms:>8.4f} | "
          f"{ll_fit:>14.4f} {ll_true:>14.4f} {E:>11.4g} {above.mean():>11.4g}")
    assert abs(pm - mm) < 1e-9 and abs(ps - ms) < 1e-9, "SHIPPED FITTER != PROBE FITTER"
print("\nshipped fitter reproduces the probe fitter exactly on all cases")
