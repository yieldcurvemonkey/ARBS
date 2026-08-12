"""Mutate imputation.py, run its suite, restore. A test that stays green on a
mutated implementation is not testing what it names."""
import pathlib
import subprocess
import sys

SRC = pathlib.Path("SDRUtils/dealer_direction/imputation.py")
PY = r"C:/Users/chris/anaconda3/envs/stir/python.exe"
original = SRC.read_text(encoding="utf-8")

MUTANTS = [
    ("LN_MU_SLACK 30 -> 60 (the mu box the shipped fit sits on)",
     "LN_MU_SLACK = 30.0", "LN_MU_SLACK = 60.0"),
    ("LN_SIGMA_MAX 6 -> 60 (the degeneracy guard)",
     "LN_SIGMA_MAX = 6.0", "LN_SIGMA_MAX = 60.0"),
    ("THRESHOLD_DIVISOR 4 -> 10 (the shipped tail threshold)",
     "THRESHOLD_DIVISOR = 4.0", "THRESHOLD_DIVISOR = 10.0"),
    ("MIN_TAIL_POINTS 5 -> 0",
     "MIN_TAIL_POINTS = 5", "MIN_TAIL_POINTS = 0"),
    ("ln_degenerate always False",
     "ln_degenerate=bool(sigma_t > 0.98 * LN_SIGMA_MAX",
     "ln_degenerate=bool(False and sigma_t > 0.98 * LN_SIGMA_MAX"),
    ("weighted_ks: drop the lower-edge arm (classic KS off-by-one)",
     "return float(max(np.max(np.abs(upper - F)), np.max(np.abs(F - lower))))",
     "return float(np.max(np.abs(upper - F)))"),
    ("pareto_cdf_truncated: drop the truncation denominator",
     "return (1.0 - (u / q) ** alpha) / (1.0 - (u / C) ** alpha)",
     "return (1.0 - (u / q) ** alpha)"),
    ("pareto_truncated_mle -> naive Hill (drop the truncation term)",
     "return 1.0 / a - rho / np.expm1(a * rho) - m",
     "return 1.0 / a - m"),
    ("lognormal_cdf_truncated: forget to renormalise",
     "return (F - F_u) / (F_C - F_u)", "return F"),
    ("pareto_tail_ratio inverted",
     "return float((u / C) ** alpha)", "return float((C / u) ** alpha)"),
    ("fit_frequency_table: ignore the vintage when keying cells",
     'fits[(str(vintage), float(lo))] = fit',
     'fits[("V1", float(lo))] = fit'),
    ("tail_mean_exists: > 1.0  ->  >= 1.0",
     "return bool(self.tail_index > 1.0)", "return bool(self.tail_index >= 1.0)"),
    ("apply_to_signed_krd: reject only negatives, not < 1",
     "or factor < 1.0:", "or factor < 0.0:"),
    ("lognormal_mean_above: sign of the sigma shift",
     "ndtr(-(z - sigma))", "ndtr(-(z + sigma))"),
    ("censored likelihood: sign of the cap-mass term",
     "+ n_cap * (np.log(s_C) - np.log(s_u))",
     "- n_cap * (np.log(s_C) - np.log(s_u))"),
    ("vintage boundary: < -> <=",
     "return VINTAGE_V1 if _as_date(as_of_date) < CAP_SCHEDULE_SWITCH",
     "return VINTAGE_V1 if _as_date(as_of_date) <= CAP_SCHEDULE_SWITCH"),
    ("band lookup ignores the vintage",
     "return _BY_CAP.get((vintage_for(as_of_date), float(notional)))",
     "return next((b for b in CAP_BANDS if b.cap == float(notional)), None)"),
]

for name, old, new in MUTANTS:
    assert original.count(old) == 1, f"anchor not unique for {name!r}"
    SRC.write_text(original.replace(old, new), encoding="utf-8")
    r = subprocess.run([PY, "-m", "pytest",
                        "tests/test_dealer_direction_imputation.py", "-q",
                        "--no-header", "-p", "no:cacheprovider"],
                       capture_output=True, text=True)
    tail = [l for l in r.stdout.splitlines() if "passed" in l or "failed" in l
            or "error" in l.lower()]
    verdict = "GREEN (undetected)" if r.returncode == 0 else "red"
    print(f"{verdict:20s} {name}\n{'':20s}   {tail[-1] if tail else r.stdout[-200:]}")
    SRC.write_text(original, encoding="utf-8")

assert SRC.read_text(encoding="utf-8") == original, "FAILED TO RESTORE"
print("\nsource restored byte-for-byte")
