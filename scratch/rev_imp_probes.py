"""Silent-degradation probes on the fitter."""
import numpy as np
import pandas as pd
from scipy import optimize
from SDRUtils.dealer_direction import imputation as imp

print("=== 1. fit_frequency_table on a table where no cell is fittable ===")
freq = pd.DataFrame({
    "vintage": ["V1"] * 6, "lo": [0.0] * 6, "cap": [1e9] * 6,
    "notional": [3e8, 4e8, 5e8, 6e8, 7e8, 1e9],
    "is_capped": [False] * 5 + [True], "n": [3, 3, 3, 3, 3, 40],
})
out = imp.fit_frequency_table(freq)
print(f"  returned {type(out).__name__} of len {len(out)}; no exception, no warning")

print("\n=== 2. a cell whose capped prints all sit OFF the exact cap value ===")
rng = np.random.default_rng(0)
z = np.exp(rng.normal(19.0, 1.5, 60_000))
sub = z[(z >= 2.5e8) & (z < 1e9)]
vals, cnts = np.unique(np.round(sub / 1e6) * 1e6, return_counts=True)
freq2 = pd.DataFrame({
    "vintage": "V1", "lo": 0.0, "cap": 1e9,
    "notional": list(vals) + [1_000_000_001.0],   # capped, one dollar off C
    "is_capped": [False] * len(vals) + [True],
    "n": list(cnts.astype(float)) + [900.0],
})
fits = imp.fit_frequency_table(freq2)
f = fits[("V1", 0.0)]
print(f"  n_cap seen by the fit = {f.n_cap} (900 capped prints in the table)")
print(f"  multiplier still produced = {f.multiplier:.4f}")
try:
    print("  capped_count_error =", f.capped_count_error)
except ZeroDivisionError as e:
    print(f"  capped_count_error raises ZeroDivisionError: {e}")

print("\n=== 3. does _ln_mle ever check convergence? ===")
calls = {"n": 0, "fail": 0, "maxiter": 0}
real = optimize.minimize
def spy(*a, **k):
    r = real(*a, **k)
    calls["n"] += 1
    calls["fail"] += (not r.success)
    calls["maxiter"] += ("aximum" in str(r.message))
    return r
optimize.minimize = spy
imp.optimize.minimize = spy
freqc = pd.read_csv("scratch/partB_freq_cache.csv")
p = freqc["cell"].str.split("|", expand=True)
freqc["vintage"], freqc["lo"] = p[0], p[1].astype(float)
freqc["cap"] = p[3].astype(float)
imp.fit_frequency_table(freqc[["vintage", "lo", "cap", "notional",
                               "is_capped", "n"]])
optimize.minimize = real
imp.optimize.minimize = real
print(f"  Nelder-Mead runs {calls['n']}, non-converged {calls['fail']}, "
      f"hit maxiter {calls['maxiter']}  -- r.success is never inspected")

print("\n=== 4. impute() vs impute_frame(): None or NaN for the factor? ===")
s = imp.impute(250e6, "2025-05-01", is_capped=False)
fr = imp.impute_frame(pd.DataFrame({
    "notional": [250e6], "as_of_date": ["2025-05-01"], "is_capped": [False]}))
print(f"  scalar factor = {s.notional_impute_factor!r} "
      f"(types.Provenance declares float | None)")
print(f"  frame  factor = {fr.loc[0, 'notional_impute_factor']!r}")
print(f"  frame  notional_imputed dtype = {fr['notional_imputed'].dtype} "
      f"value {fr.loc[0, 'notional_imputed']!r}")
print(f"  frame  notional_expected on a non-capped leg = "
      f"{fr.loc[0, 'notional_expected']!r}")

print("\n=== 5. weighted_ks on zero total weight ===")
print("  ", imp.weighted_ks([1.0, 2.0], [0.0, 0.0],
                            lambda q: np.zeros_like(q)))
