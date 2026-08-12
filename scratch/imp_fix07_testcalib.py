"""Calibrate the synthetic fixtures the new tests will assert on."""
import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, r"C:\Users\chris\clee\ARBS-dd")

import numpy as np
import pandas as pd

from SDRUtils.dealer_direction import imputation as imp

rng = np.random.default_rng(20260811)

# ---- 1. does a Pareto-generated cell make the LOGNORMAL run to the wall?
u, cap = 5e7, 2e8
for alpha in (1.1, 1.2, 1.4):
    z = u * (rng.random(200_000) ** (-1.0 / alpha))
    sub, n_cap = z[z < cap], float((z >= cap).sum())
    f = imp.fit_cell(sub, np.ones_like(sub), u, cap, n_cap)
    print(f"pareto alpha={alpha}: mu={f.ln_mu_censored:9.3f} sigma={f.ln_sigma_censored:6.3f} "
          f"mult={f.multiplier:6.3f} degen={f.ln_degenerate} "
          f"deg_t={f.ln_degenerate_truncated} conv_t={f.ln_truncated_converged} "
          f"ncap_err={f.capped_count_error:+.3f}")

# ---- 2. a clean lognormal cell must NOT be degenerate, and must recover
for mu_t, s_t in ((17.4, 1.5), (17.0, 1.2)):
    z = np.exp(rng.normal(mu_t, s_t, 200_000))
    z = z[z >= u]
    sub, n_cap = z[z < cap], float((z >= cap).sum())
    f = imp.fit_cell(sub, np.ones_like(sub), u, cap, n_cap)
    print(f"lognormal ({mu_t},{s_t}): mu={f.ln_mu_censored:8.3f} sigma={f.ln_sigma_censored:6.3f} "
          f"mult={f.multiplier:6.3f} degen={f.ln_degenerate} n_cap={n_cap:.0f}")

# ---- 3. a two-vintage frequency table for fit_frequency_table
def cell(vintage, lo, cap_, mu, sigma, n):
    z = np.exp(rng.normal(mu, sigma, n))
    z = z[z > 0]
    capped = z >= cap_
    lattice = np.round(z[~capped] / 1e6) * 1e6
    lattice = lattice[lattice > 0]
    vals, cnts = np.unique(lattice, return_counts=True)
    rows = [{"vintage": vintage, "lo": lo, "cap": cap_, "notional": float(v),
             "is_capped": False, "n": int(c)} for v, c in zip(vals, cnts)]
    rows.append({"vintage": vintage, "lo": lo, "cap": cap_, "notional": cap_,
                 "is_capped": True, "n": int(capped.sum())})
    return rows


rows = (cell("V1", 0.0, 4e8, 18.0, 1.1, 60_000)
        + cell("V1", 2.0, 2e8, 17.4, 1.2, 60_000)
        + cell("V2", 0.0, 8e8, 18.6, 1.1, 60_000))
freq = pd.DataFrame(rows)
fits = imp.fit_frequency_table(freq)
print("\nkeys:", sorted(fits))
for k, f in sorted(fits.items()):
    truth = {("V1", 0.0): (18.0, 1.1, 4e8), ("V1", 2.0): (17.4, 1.2, 2e8),
             ("V2", 0.0): (18.6, 1.1, 8e8)}[k]
    exact = imp.lognormal_mean_above(truth[0], truth[1], truth[2]) / truth[2]
    print(f"  {k}: u={f.u:.4g} (cap/4={truth[2]/4:.4g}) mu={f.ln_mu_censored:.3f} "
          f"sigma={f.ln_sigma_censored:.3f} mult={f.multiplier:.4f} "
          f"true_mult={exact:.4f}  err={f.multiplier/exact-1:+.4f} "
          f"ncap_err={f.capped_count_error:+.4f} degen={f.ln_degenerate}")

# ---- 4. thin cell -> skipped with a warning; nothing fittable -> raise
thin = pd.DataFrame([
    {"vintage": "V1", "lo": 9.0, "cap": 1e8, "notional": 3e7, "is_capped": False, "n": 4},
    {"vintage": "V1", "lo": 9.0, "cap": 1e8, "notional": 1e8, "is_capped": True, "n": 7},
])
import warnings
with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    try:
        imp.fit_frequency_table(pd.concat([freq, thin], ignore_index=True))
    except Exception as exc:
        print("\nRAISED", type(exc).__name__, exc)
    print("\nwarnings:", [str(w.message)[:140] for w in caught])
try:
    imp.fit_frequency_table(thin)
except Exception as exc:
    print("empty table ->", type(exc).__name__, str(exc)[:90])

# ---- 5. capped prints all off the cap
offcap = pd.DataFrame([
    {"vintage": "V1", "lo": 0.0, "cap": 4e8, "notional": 1.5e8, "is_capped": False, "n": 900},
    {"vintage": "V1", "lo": 0.0, "cap": 4e8, "notional": 2.5e8, "is_capped": False, "n": 400},
    {"vintage": "V1", "lo": 0.0, "cap": 4e8, "notional": 4e8 - 1, "is_capped": True, "n": 900},
])
try:
    imp.fit_frequency_table(offcap)
except Exception as exc:
    print("all capped prints off C ->", type(exc).__name__, str(exc)[:120])
