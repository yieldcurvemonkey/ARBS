"""Verification harness: re-run the review's mutation survivors against the
FIXED probability.py, plus fresh mutations aimed at the new tests.

Copy of scratch/rev_prob_mutate.py's idea, with anchors re-pointed at the
current source (three of the review's anchors no longer exist -- the code they
named was changed or deleted by the fix). Nothing in the worktree is edited.

Usage: vprob_mut.py <id> [<id> ...]   (or `all`)
"""
from __future__ import annotations

import concurrent.futures as cf
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "SDRUtils", "dealer_direction", "probability.py")
PY = r"C:/Users/chris/anaconda3/envs/stir/python.exe"

MUTATIONS = {
    "none": None,
    # --- harness validation (must be CAUGHT) ---
    "sign_flip_p": ("    z = (x - fit.b0) / fit.tau",
                    "    z = (fit.b0 - x) / fit.tau"),
    # --- the review's survivors, re-run ---
    "anchored_b0_mean": ("    return float(np.median(xt)), h_fb, s_fb, extra",
                         "    return 0.0, h_fb, s_fb, extra"),
    "anchored_b0_subtle": ("    return float(np.median(xt)), h_fb, s_fb, extra",
                           "    return float(np.mean(xt)), h_fb, s_fb, extra"),
    "disp_about_zero": ("    c = xt - xt.mean()\n    return float(math.sqrt(float((c * c).mean())))",
                        "    return float(math.sqrt(float((xt * xt).mean())))"),
    "s_ind_arm": ("        s_ind = float(sigma_mid(stats))",
                  "        s_ind = 7.0 * float(sigma_mid(stats))"),
    "no_crosscheck_flag": ("        if xcheck.comparable and not xcheck.agrees:\n"
                           "            flags.append(FIT_CROSSCHECK_DISAGREES)",
                           "        if False:\n"
                           "            flags.append(FIT_CROSSCHECK_DISAGREES)"),
    "forkey_uses_n": ("            if fit.n_trimmed < fit.min_n_required and label != GLOBAL_BUCKET:",
                      "            if fit.n < fit.min_n_required and label != GLOBAL_BUCKET:"),
    "em_labelswap": ("            b0_new = xbar - (-h_new) * ubar",
                     "            b0_new = xbar - h_new * ubar"),
    "labelswap_poison": ("            h_new = -h_new\n"
                         "            b0_new = xbar - (-h_new) * ubar\n",
                         "            raise AssertionError('EM label-swap branch reached')\n"),
    # --- re-anchored: the fix moved the line the review named ---
    "never_anchor": ("MAX_SE_LOG_TAU = TAU_RECOVERY_TOLERANCE / 1.6449",
                     "MAX_SE_LOG_TAU = 1e9"),
    "gate_back_to_1_2816": ("MAX_SE_LOG_TAU = TAU_RECOVERY_TOLERANCE / 1.6449",
                            "MAX_SE_LOG_TAU = TAU_RECOVERY_TOLERANCE / 1.2816"),
    "gate_1_5": ("MAX_SE_LOG_TAU = TAU_RECOVERY_TOLERANCE / 1.6449",
                 "MAX_SE_LOG_TAU = TAU_RECOVERY_TOLERANCE / 1.5"),
    "bootstrap_denominator_reverted": ("    return (worse + 1) / (used + 1), used",
                                       "    return (worse + 1) / (reps + 1), used"),
    "bootstrap_used_counts_failures": ("        if len(ys) < 2:\n            continue\n        used += 1",
                                       "        used += 1\n        if len(ys) < 2:\n            continue"),
    # --- fresh: are the NEW tests pinned to the mechanism? ---
    "tenor_zero_back_to_first_band": ("    if not math.isfinite(y) or y <= 0.0:\n        return \"UNKNOWN\"",
                                      "    if not math.isfinite(y):\n        return \"UNKNOWN\""),
    "report_h_used_unfloored": ("                h_used_bps=max(float(f.h), _h_floor(f.s)),",
                                "                h_used_bps=float(f.h),"),
    "report_columns_dropped": ("        return pd.DataFrame(rows, columns=list(REPORT_COLUMNS))",
                               "        return pd.DataFrame(rows)"),
    "rolling_empty_returns_quietly": ("    if not out:\n        raise ValueError(",
                                      "    if False:\n        raise ValueError("),
    "rolling_no_warning": ("    if thin:\n        warnings.warn(",
                           "    if False:\n        warnings.warn("),
    "tau_stability_dropped_zero": ("    dropped = len(fits) - len(usable)",
                                   "    dropped = 0"),
    "pool_straight_to_global": ("        for label in pooling_ladder(key, self.order):",
                                "        for label in [want, GLOBAL_BUCKET] if False else ([want] if want in self.fits else []) + [GLOBAL_BUCKET]:"),
    "bootstrap_empty_no_raise": ("    if used == 0:\n        raise ValueError(",
                                 "    if False:\n        raise ValueError("),
}


def build(mut_id: str) -> str:
    src = open(SRC, encoding="utf-8", newline="").read()
    spec = MUTATIONS[mut_id]
    if spec is not None:
        old, new = spec
        # source on disk is CRLF; anchors are written LF
        old_c, new_c = old.replace("\n", "\r\n"), new.replace("\n", "\r\n")
        if src.count(old_c) == 1:
            old, new = old_c, new_c
        assert src.count(old) == 1, f"{mut_id}: anchor appears {src.count(old)}x"
        src = src.replace(old, new)
    out = os.path.join(HERE, "_vmut", f"probability_{mut_id}.py")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="") as fh:
        fh.write(src)
    return out


def run(mut_id: str) -> str:
    path = build(mut_id)
    env = dict(os.environ, ARBS_MUT_PATH=path, ARBS_SUPABASE_ENABLED="0",
               PYTHONDONTWRITEBYTECODE="1",
               PYTHONPATH=os.pathsep.join([ROOT, HERE]))
    cmd = [PY, "-m", "pytest", "-q", "--no-header", "-p", "no:randomly",
           "-p", "no:cacheprovider", "-p", "rev_prob_mutplug",
           "tests/test_dealer_direction_probability.py"]
    r = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True)
    tail = [ln for ln in r.stdout.splitlines() if ln.strip()][-1:]
    fails = [ln.split("::", 1)[-1].split(" ")[0]
             for ln in r.stdout.splitlines() if ln.startswith("FAILED")]
    ok = "[mutplug] probability loaded from" in r.stderr
    lines = [f"=== {mut_id}: rc={r.returncode} {tail} loaded={ok}"]
    for f in fails:
        lines.append(f"      {f}")
    if not ok:
        lines.append(f"      !!! MUTANT NOT LOADED: {r.stderr[-600:]}")
    return "\n".join(lines)


def main() -> int:
    ids = sys.argv[1:]
    if ids == ["all"]:
        ids = list(MUTATIONS)
    with cf.ThreadPoolExecutor(max_workers=4) as ex:
        for out in ex.map(run, ids):
            print(out, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
