"""Build one mutant of probability.py in scratch/ and run tests against it.

Usage: rev_prob_mutate.py <mutant-id> [pytest args...]
"""
from __future__ import annotations

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "SDRUtils", "dealer_direction", "probability.py")
PY = r"C:/Users/chris/anaconda3/envs/stir/python.exe"

# id -> (old, new). Each `old` must appear EXACTLY once in the source, which is
# asserted, so a refactor cannot silently turn a mutation into a no-op.
MUTATIONS = {
    "none": None,
    # --- sign / core algebra (expected CAUGHT) ---
    "sign_flip_p": ("    z = (x - fit.b0) / fit.tau",
                    "    z = (fit.b0 - x) / fit.tau"),
    "tau_is_half_spread": ("        return float(self.s) ** 2 / (2.0 * h)",
                           "        return h"),
    "h_floor_huge": ("    return MIN_SEPARATION * max(float(s), 1e-300)",
                     "    return 1000.0 * max(float(s), 1e-300)"),
    "em_labelswap": ("            b0_new = xbar - (-h_new) * ubar",
                     "            b0_new = xbar - h_new * ubar"),
    "labelswap_poison": ("            h_new = -h_new\n"
                         "            b0_new = xbar - (-h_new) * ubar\n",
                         "            raise AssertionError('EM label-swap branch reached')\n"),
    "crosscheck_tautology": (
        "    h_own = fit.h if fit.h_mle is None else fit.h_mle",
        "    h_own = fit.h"),
    "never_anchor": ("MAX_SE_LOG_TAU = TAU_RECOVERY_TOLERANCE / 1.2816",
                     "MAX_SE_LOG_TAU = 1e9"),
    # --- expected SURVIVORS ---
    "s_ind_arm": ("        s_ind = float(sigma_mid(stats))",
                  "        s_ind = 7.0 * float(sigma_mid(stats))"),
    "disp_about_zero": ("    c = xt - xt.mean()\n    return float(math.sqrt(float((c * c).mean())))",
                        "    return float(math.sqrt(float((xt * xt).mean())))"),
    "parent_h_dead": ("        if f is not None and FIT_UNSEPARATED not in f.flags and f.h > 0:\n"
                      "            return float(f.h)\n",
                      "        if False:\n"
                      "            return float(f.h)\n"),
    "forkey_uses_n": ("            if fit.n_trimmed < fit.min_n_required and label != GLOBAL_BUCKET:",
                      "            if fit.n < fit.min_n_required and label != GLOBAL_BUCKET:"),
    "no_crosscheck_flag": ("        if xcheck.comparable and not xcheck.agrees:\n"
                           "            flags.append(FIT_CROSSCHECK_DISAGREES)",
                           "        if False:\n"
                           "            flags.append(FIT_CROSSCHECK_DISAGREES)"),
    "bootstrap_denominator": ("    return (worse + 1) / (reps + 1)",
                              "    return 0.99"),
    "implied_split_se": ("    se = float(p.std(ddof=1) / math.sqrt(n)) if n > 1 else float(\"nan\")",
                         "    se = float(p.std(ddof=1)) if n > 1 else float(\"nan\")"),
    "reliability_edges": ("    idx = np.clip(np.digitize(p, edges[1:-1], right=False), 0, n_bins - 1)",
                          "    idx = np.clip(np.digitize(p, edges[1:-1], right=True), 0, n_bins - 1)"),
    "trim_k_2": ("TRIM_MAD_K = 6.0", "TRIM_MAD_K = 2.0"),
    "sep_pvalue_x2": ("    return 0.5 * math.erfc(math.sqrt(lr / 2.0))",
                      "    return math.erfc(math.sqrt(lr / 2.0))"),
    "degenerate_narrow": ("            b0=float(np.median(xt)), h=MIN_SEPARATION * s_deg, s=s_deg,",
                          "            b0=float(np.median(xt)), h=10.0 * s_deg, s=s_deg,"),
    "anchored_b0_mean": ("    return float(np.median(xt)), h_fb, s_fb, extra",
                         "    return 0.0, h_fb, s_fb, extra"),
}


def build(mut_id: str) -> str:
    src = open(SRC, encoding="utf-8").read()
    spec = MUTATIONS[mut_id]
    if spec is not None:
        old, new = spec
        assert src.count(old) == 1, f"{mut_id}: anchor appears {src.count(old)}x"
        src = src.replace(old, new)
    out = os.path.join(HERE, "_mut", f"probability_{mut_id}.py")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(src)
    return out


def main() -> int:
    mut_id = sys.argv[1]
    path = build(mut_id)
    env = dict(os.environ, ARBS_MUT_PATH=path, ARBS_SUPABASE_ENABLED="0",
               PYTHONPATH=os.pathsep.join([ROOT, HERE]))
    args = sys.argv[2:] or ["tests/test_dealer_direction_probability.py"]
    cmd = [PY, "-m", "pytest", "-q", "--no-header", "-p", "no:randomly",
           "-p", "rev_prob_mutplug", *args]
    r = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True)
    tail = [ln for ln in r.stdout.splitlines() if ln.strip()][-1:]
    fails = [ln for ln in r.stdout.splitlines() if ln.startswith("FAILED")]
    print(f"=== {mut_id}: rc={r.returncode} {tail}")
    for ln in fails:
        print(f"      {ln}")
    if "[mutplug] probability loaded from" not in r.stderr:
        print(f"      !!! HARNESS DID NOT LOAD THE MUTANT: {r.stderr[-800:]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
