"""Red evidence for every fix, and mutation coverage for every new test.

Two batteries against tests/test_dealer_direction_imputation.py:

  HEAD   -- the pre-fix module (git show HEAD:...), to show which of the new
            tests actually go red on the code they were written against.
  MUT-*  -- one-line mutations of the FIXED module, to show that the tests
            written for functions that were already correct can fail at all.

The module is restored from an in-memory copy after every run and the restore
is checked by sha256; the script refuses to start if the tree is not clean of
its own leftovers.
"""
from __future__ import annotations

import hashlib
import io
import os
import subprocess
import sys

ROOT = r"C:\Users\chris\clee\ARBS-dd"
MOD = os.path.join(ROOT, "SDRUtils", "dealer_direction", "imputation.py")
TEST = "tests/test_dealer_direction_imputation.py"
PY = r"C:/Users/chris/anaconda3/envs/stir/python.exe"


def read(path):
    with io.open(path, encoding="utf-8", newline="") as fh:
        return fh.read()


def write(path, text):
    with io.open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


ORIGINAL = read(MOD)
ORIG_HASH = hashlib.sha256(ORIGINAL.encode("utf-8")).hexdigest()

HEAD = subprocess.run(["git", "-C", ROOT, "show",
                       "HEAD:SDRUtils/dealer_direction/imputation.py"],
                      capture_output=True, text=True, check=True).stdout

MUTANTS = [
    # (name, find, replace)
    ("pareto_truncated_mle -> naive Hill",
     "    lo, hi = -5.0, 200.0\n"
     "    if score(lo) * score(hi) > 0:\n"
     "        return float(\"nan\")\n"
     "    return float(optimize.brentq(score, lo, hi, xtol=1e-10))",
     "    return float(1.0 / m)"),
    ("lognormal_cdf_truncated -> no renormalisation",
     "    return (F - F_u) / (F_C - F_u)", "    return F"),
    ("pareto_cdf_truncated -> no truncation denominator",
     "    return (1.0 - (u / q) ** alpha) / (1.0 - (u / C) ** alpha)",
     "    return 1.0 - (u / q) ** alpha"),
    ("weighted_ks -> upper arm only",
     "    return float(max(np.max(np.abs(upper - F)), np.max(np.abs(F - lower))))",
     "    return float(np.max(np.abs(upper - F)))"),
    ("pareto_tail_ratio -> inverted",
     "    return float((u / C) ** alpha)", "    return float((C / u) ** alpha)"),
    ("fit_frequency_table -> everything keyed V1",
     "        fits[(str(vintage), float(lo))] = fit",
     "        fits[(\"V1\", float(lo))] = fit"),
    ("MIN_TAIL_POINTS 5 -> 0", "MIN_TAIL_POINTS = 5", "MIN_TAIL_POINTS = 0"),
    ("THRESHOLD_DIVISOR 4 -> 10",
     "THRESHOLD_DIVISOR = 4.0", "THRESHOLD_DIVISOR = 10.0"),
    ("ln_degenerate hard-wired False",
     "        ln_degenerate=_ln_on_box_wall(mu_c, sigma_c, u, C),",
     "        ln_degenerate=False,"),
    ("_ln_on_box_wall -> sigma only (the old blind detector)",
     "    return bool(sigma > 0.98 * LN_SIGMA_MAX\n"
     "                or sigma < np.exp(-3.0) * 1.02\n"
     "                or mu < np.log(u) - LN_MU_SLACK + LN_BOX_TOL\n"
     "                or mu > np.log(C) + 10.0 - LN_BOX_TOL)",
     "    return bool(sigma > 0.98 * LN_SIGMA_MAX)"),
    ("LN_SIGMA_MAX 6 -> 60", "LN_SIGMA_MAX = 6.0", "LN_SIGMA_MAX = 60.0"),
    ("LN_MU_SLACK 150 -> 30", "LN_MU_SLACK = 150.0", "LN_MU_SLACK = 30.0"),
    ("censored MLE accepts a non-converged optimum",
     "    pool = [r for r in runs if r.success] if require_converged else runs",
     "    pool = runs"),
    ("fit_cell accepts n_cap = 0",
     "    if not float(n_cap) > 0:", "    if False:"),
    ("impute_frame -> unmarked notional_expected column",
     "    out[\"notional_expected_reporting_only\"] = ",
     "    out[\"notional_expected\"] = "),
    ("tail_mean_exists > 1.0 -> >= 1.0",
     "        return bool(self.tail_index > 1.0)",
     "        return bool(self.tail_index >= 1.0)"),
    ("fit_frequency_table -> silent skip (no warning, empty ok)",
     "    if skipped:\n        warnings.warn(", "    if False:\n        warnings.warn("),
]


def run_pytest(label):
    p = subprocess.run([PY, "-m", "pytest", TEST, "-q", "--no-header",
                        "-p", "no:randomly", "--tb=no"],
                       cwd=ROOT, capture_output=True, text=True,
                       env={**os.environ, "ARBS_SUPABASE_ENABLED": "0"})
    failed = sorted({ln.split("::")[1].split()[0]
                     for ln in p.stdout.splitlines() if ln.startswith("FAILED ")})
    tail = [ln for ln in p.stdout.splitlines()
            if " passed" in ln or " failed" in ln or "error" in ln.lower()]
    return failed, (tail[-1] if tail else "NO SUMMARY"), p.returncode


def with_source(text, label):
    write(MOD, text)
    try:
        return run_pytest(label)
    finally:
        write(MOD, ORIGINAL)
        assert hashlib.sha256(read(MOD).encode("utf-8")).hexdigest() == ORIG_HASH, \
            "RESTORE FAILED -- the module on disk is not what it was"


def main() -> int:
    print("baseline (fixed module, unmutated):")
    base_failed, base_tail, _ = run_pytest("baseline")
    print(f"  {base_tail}")
    if base_failed:
        print("  baseline is not green; stop.", base_failed)
        return 1

    only = sys.argv[1:]
    if not only or "head" in only:
        print("\n=== HEAD (pre-fix module) vs the new suite ===")
        failed, tail, _ = with_source(HEAD, "HEAD")
        print(f"  {tail}")
        for name in failed:
            print(f"    RED  {name}")

    print("\n=== mutations of the fixed module ===")
    survivors = []
    for name, find, repl in MUTANTS:
        if only and "head" not in only and not any(o in name for o in only):
            continue
        assert text_ok(name, find), name
        failed, tail, _ = with_source(ORIGINAL.replace(find, repl, 1), name)
        status = "KILLED" if failed else "SURVIVED"
        if not failed:
            survivors.append(name)
        print(f"  {status:8s} {name}")
        print(f"           {tail}   {failed[:4]}{'...' if len(failed) > 4 else ''}")
    print(f"\nsurvivors: {len(survivors)}  {survivors}")
    assert hashlib.sha256(read(MOD).encode("utf-8")).hexdigest() == ORIG_HASH
    print("module restored byte-for-byte: OK")
    return 0


def text_ok(name, find):
    n = ORIGINAL.count(find)
    if n != 1:
        print(f"  !! mutation {name!r} matches {n} times, not 1")
    return n == 1


if __name__ == "__main__":
    raise SystemExit(main())
