"""Refit the shipped calibration with a wider mu box. If the multipliers move,
the shipped ones are a property of LN_MU_SLACK, not of the tape."""
import numpy as np
import pandas as pd
from SDRUtils.dealer_direction import imputation as imp

freq = pd.read_csv("scratch/partB_freq_cache.csv")
parts = freq["cell"].str.split("|", expand=True)
freq["vintage"] = parts[0]
freq["lo"] = parts[1].astype(float)
freq["hi"] = parts[2].astype(float)
freq["cap"] = parts[3].astype(float)
freq = freq[["vintage", "lo", "hi", "cap", "notional", "is_capped", "n"]]

shipped = {(b.vintage, b.lo): b for b in imp.CAP_BANDS}


def run(slack):
    imp.LN_MU_SLACK = slack
    return imp.fit_frequency_table(freq)


base = run(30.0)
print("--- reproduce the shipped table at LN_MU_SLACK = 30 (sanity of the tool)")
bad = 0
for key, fit in sorted(base.items()):
    b = shipped.get(key)
    if b is None:
        print("  no shipped band for", key)
        continue
    ok = abs(fit.multiplier / b.multiplier - 1) < 2e-3
    bad += not ok
    if not ok:
        print(f"  MISMATCH {key} refit {fit.multiplier:.4f} vs shipped {b.multiplier:.4f}")
print(f"  cells refitted: {len(base)}  shipped: {len(shipped)}  mismatches: {bad}")

for slack in (45.0, 60.0, 100.0):
    fits = run(slack)
    print(f"\n--- LN_MU_SLACK = {slack}")
    rows = []
    for key, fit in sorted(fits.items()):
        b = shipped[key]
        rows.append((f"{key[0]} {b.label}", b.multiplier, fit.multiplier,
                     fit.ln_mu_censored, fit.ln_sigma_censored,
                     fit.capped_count_error, fit.ln_degenerate))
    for name, m0, m1, mu, sg, err, deg in rows:
        flag = "  <== MOVED" if abs(m1 / m0 - 1) > 0.02 else ""
        print(f"  {name:16s} mult {m0:6.3f} -> {m1:8.3f}  mu {mu:11.3f} "
              f"sigma {sg:6.3f} ncap_err {err:+.3f} degen={deg}{flag}")
imp.LN_MU_SLACK = 30.0
