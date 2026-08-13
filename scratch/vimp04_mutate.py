"""Re-run the review's mutation battery against the FIXED module, plus new
mutants aimed at the fix itself. Nothing on disk is edited: see vimp_mutplug.

Harness validation first (a checking tool that is itself wrong reports success):
  * a no-op "mutation" must leave the suite green -- otherwise the injection
    breaks the suite by itself and every red below is meaningless;
  * a mutant the ORIGINAL battery proved red must still be red -- otherwise the
    injection no-oped and every green below is a false survivor.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = r"C:/Users/chris/anaconda3/envs/stir/python.exe"

# (label, old, new, expectation)  expectation: "red" | "equivalent" | "?"
MUTANTS = [
    # ---- harness validation ------------------------------------------------
    ("HARNESS no-op (must be GREEN)", "", "", "green"),
    ("HARNESS known-red: vintage boundary < -> <=",
     "return VINTAGE_V1 if _as_date(as_of_date) < CAP_SCHEDULE_SWITCH",
     "return VINTAGE_V1 if _as_date(as_of_date) <= CAP_SCHEDULE_SWITCH", "red"),

    # ---- the review's 17, anchors re-pointed at the current source ---------
    ("R1  LN_MU_SLACK 150 -> 30 (the wall that bit)",
     "LN_MU_SLACK = 150.0", "LN_MU_SLACK = 30.0", "red"),
    ("R1b LN_MU_SLACK 150 -> 60 (claimed EQUIVALENT)",
     "LN_MU_SLACK = 150.0", "LN_MU_SLACK = 60.0", "equivalent"),
    ("R1c LN_MU_SLACK 150 -> 300 (claimed EQUIVALENT)",
     "LN_MU_SLACK = 150.0", "LN_MU_SLACK = 300.0", "equivalent"),
    ("R2  LN_SIGMA_MAX 6 -> 60 (the degeneracy guard)",
     "LN_SIGMA_MAX = 6.0", "LN_SIGMA_MAX = 60.0", "red"),
    ("R3  THRESHOLD_DIVISOR 4 -> 10 (the shipped threshold)",
     "THRESHOLD_DIVISOR = 4.0", "THRESHOLD_DIVISOR = 10.0", "red"),
    ("R4  MIN_TAIL_POINTS 5 -> 0",
     "MIN_TAIL_POINTS = 5", "MIN_TAIL_POINTS = 0", "red"),
    ("R5  degeneracy detector hard-wired False",
     "    return bool(sigma > 0.98 * LN_SIGMA_MAX",
     "    return False and bool(sigma > 0.98 * LN_SIGMA_MAX", "red"),
    ("R6  weighted_ks: drop the lower-edge arm",
     "return float(max(np.max(np.abs(upper - F)), np.max(np.abs(F - lower))))",
     "return float(np.max(np.abs(upper - F)))", "red"),
    ("R7  pareto_cdf_truncated: drop the truncation denominator",
     "return (1.0 - (u / q) ** alpha) / (1.0 - (u / C) ** alpha)",
     "return (1.0 - (u / q) ** alpha)", "red"),
    ("R8  pareto_truncated_mle -> naive Hill",
     "return 1.0 / a - rho / np.expm1(a * rho) - m", "return 1.0 / a - m", "red"),
    ("R9  lognormal_cdf_truncated: forget to renormalise",
     "return (F - F_u) / (F_C - F_u)", "return F", "red"),
    ("R10 pareto_tail_ratio inverted",
     "return float((u / C) ** alpha)", "return float((C / u) ** alpha)", "red"),
    ("R11 fit_frequency_table keys every cell as V1",
     'fits[(str(vintage), float(lo))] = fit',
     'fits[("V1", float(lo))] = fit', "red"),
    ("R12 tail_mean_exists: > 1.0 -> >= 1.0",
     "return bool(self.tail_index > 1.0)", "return bool(self.tail_index >= 1.0)",
     "red"),
    ("R13 apply_to_signed_krd: reject only negatives",
     "or factor < 1.0:", "or factor < 0.0:", "red"),
    ("R14 lognormal_mean_above: sign of the sigma shift",
     "ndtr(-(z - sigma))", "ndtr(-(z + sigma))", "red"),
    ("R15 censored likelihood: sign of the cap-mass term",
     "+ n_cap * (np.log(s_C) - np.log(s_u))",
     "- n_cap * (np.log(s_C) - np.log(s_u))", "red"),
    ("R17 band lookup ignores the vintage",
     "return _BY_CAP.get((vintage_for(as_of_date), float(notional)))",
     "return next((b for b in CAP_BANDS if b.cap == float(notional)), None)",
     "red"),

    # ---- new mutants, aimed at the FIX -------------------------------------
    ("N1  detector watches sigma ONLY again (the original blindness)",
     "    return bool(sigma > 0.98 * LN_SIGMA_MAX\n"
     "                or sigma < np.exp(-3.0) * 1.02\n"
     "                or mu < np.log(u) - LN_MU_SLACK + LN_BOX_TOL\n"
     "                or mu > np.log(C) + 10.0 - LN_BOX_TOL)",
     "    return bool(sigma > 0.98 * LN_SIGMA_MAX)", "red"),
    ("N2  shipped table: flip one ln_degenerate True -> False",
     "            ln_degenerate=True, n_capped=9484)",
     "            ln_degenerate=False, n_capped=9484)", "red"),
    ("N3  fit_frequency_table: empty result returns {} again",
     '    if not fits:\n        raise ValueError(',
     '    if False:\n        raise ValueError(', "red"),
    ("N4  fit_frequency_table: drop the skipped-cells warning",
     "    if skipped:\n        warnings.warn(",
     "    if False:\n        warnings.warn(", "red"),
    ("N5  fit_cell: accept n_cap = 0 again",
     "    if not float(n_cap) > 0:\n        raise ValueError(",
     "    if False:\n        raise ValueError(", "red"),
    ("N6  censored MLE accepts a non-converged optimum again",
     "return _ln_mle(x, w, u, C, float(n_cap), require_converged=True)[:2]",
     "return _ln_mle(x, w, u, C, float(n_cap), require_converged=False)[:2]",
     "?"),
    ("N7  rename the column back to notional_expected",
     '    out["notional_expected_reporting_only"] = out[notional].astype(float) * factors',
     '    out["notional_expected"] = out[notional].astype(float) * factors', "red"),
    ("N8  weighted_ks: silent nan on zero weight again",
     '    if not len(x) or not w.sum() > 0:', '    if False:', "red"),
    ("N9  band_for_tenor: TypeError from np.isfinite(None) again",
     "    try:\n        t = float(tenor_years)\n    except (TypeError, ValueError):\n"
     "        t = float(\"nan\")   # None and \"7y\" land here, and get the same message",
     "    t = tenor_years", "red"),
    ("N10 capped_count_error divides by zero again",
     "        if not self.n_cap:\n            return float(\"nan\")", "        pass",
     "red"),
    ("N11 fit_cell: drop the non-evaluable-mean guard",
     "    if not np.isfinite(mean_ln):", "    if False:", "?"),
    ("N12 LN_BOX_TOL 1e-3 -> 0 (detector can no longer see a wall)",
     "LN_BOX_TOL = 1e-3", "LN_BOX_TOL = 0.0", "?"),
]


def run(old, new):
    env = dict(os.environ, ARBS_SUPABASE_ENABLED="0",
               ARBS_VIMP_MUT=json.dumps([old, new]), PYTHONPATH=ROOT)
    r = subprocess.run(
        [PY, "-m", "pytest", "tests/test_dealer_direction_imputation.py", "-q",
         "--no-header", "-p", "no:cacheprovider", "-p", "vimp_mutplug"],
        capture_output=True, text=True, cwd=ROOT, env=env)
    return r


sys.path.insert(0, HERE)   # so -p vimp_mutplug resolves
os.environ["PYTHONPATH"] = HERE + os.pathsep + ROOT

results = []
for label, old, new, expect in MUTANTS:
    env = dict(os.environ, ARBS_SUPABASE_ENABLED="0",
               ARBS_VIMP_MUT=json.dumps([old, new]),
               PYTHONPATH=HERE + os.pathsep + ROOT)
    r = subprocess.run(
        [PY, "-m", "pytest", "tests/test_dealer_direction_imputation.py", "-q",
         "--no-header", "-p", "no:cacheprovider", "-p", "vimp_mutplug"],
        capture_output=True, text=True, cwd=ROOT, env=env)
    if "[vimp] imputation loaded from" not in r.stderr:
        print(f"!! HARNESS DID NOT INJECT for {label}\n{r.stdout[-1500:]}\n{r.stderr[-800:]}")
        results.append((label, "HARNESS-FAIL", expect, ""))
        continue
    tail = [l for l in r.stdout.splitlines()
            if " passed" in l or " failed" in l or " error" in l.lower()]
    verdict = "GREEN (survives)" if r.returncode == 0 else "red (killed)"
    killers = sorted({l.split("::")[1].split(" ")[0]
                      for l in r.stdout.splitlines() if l.startswith("FAILED")})
    results.append((label, verdict, expect, tail[-1] if tail else r.stdout[-160:]))
    flag = ""
    if verdict.startswith("GREEN") and expect == "red":
        flag = "   <== SURVIVOR"
    if verdict.startswith("red") and expect == "equivalent":
        flag = "   <== not equivalent after all"
    print(f"{verdict:17s} exp={expect:11s} {label}{flag}")
    print(f"{'':17s}   {tail[-1] if tail else ''}")
    if killers:
        print(f"{'':17s}   killed by: {', '.join(killers[:6])}"
              f"{' ...' if len(killers) > 6 else ''}")

print("\n" + "=" * 78)
surv = [l for l, v, e, _ in results if v.startswith("GREEN") and e == "red"]
print(f"SURVIVORS among mutants expected to be caught: {len(surv)}")
for s in surv:
    print("  -", s)
