"""Final validation of the deliverable JSON: completeness, internal consistency, convergence."""
import json
import numpy as np

OUT = r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_driver_analysis"
R = json.load(open(OUT + r"\variance_ratio_results.json"))
ok = True

print("[1] every rung x variant present, and matched rungs now carry share_sumsq")
for r, vv in R["ladder"].items():
    for v, s in vv.items():
        need = ["n_speech", "n_nospeech", "var_ratio", "mean_abs_ratio", "median_abs_ratio",
                "share_days", "share_sumsq", "concentration"]
        miss = [k for k in need if k not in s or s[k] is None]
        if miss:
            print(f"    MISSING {r}|{v}: {miss}"); ok = False
print("    OK" if ok else "    FAIL")

print()
print("[2] concentration == share_sumsq / share_days  (identity check on the non-matched rungs)")
bad = 0
for r in ["a_all", "b_exFOMC", "c_exFOMC_exCPI_exNFP", "d_nonblackout"]:
    for v, s in R["ladder"][r].items():
        lhs, rhs = s["concentration"], s["share_sumsq"] / s["share_days"]
        if abs(lhs - rhs) > 1e-9:
            print(f"    MISMATCH {r}|{v}: {lhs} vs {rhs}"); bad += 1
print(f"    {'OK' if bad == 0 else 'FAIL'} ({bad} mismatches)")
ok &= bad == 0

print()
print("[3] exhaustive vs random-5000 rotation p agree to within Monte-Carlo error")
worst = 0.0
for k, v in R["rotation_null_exhaustive"].items():
    pe, pr = v["p_two_sided"], R["rotation_null_random_5000"][k]["p_two_sided"]
    if pe is None or pr is None:
        continue
    worst = max(worst, abs(pe - pr))
print(f"    max |p_exhaustive - p_random| over all {len(R['rotation_null_exhaustive'])} cells = {worst:.4f}")
c = worst < 0.05
print("    OK" if c else "    FAIL -- the two nulls disagree, investigate")
ok &= c

print()
print("[4] how many of ALL rotation tests clear p<0.05?  (multiple-comparison context)")
ps = [v["p_two_sided"] for v in R["rotation_null_exhaustive"].values() if v["p_two_sided"] is not None]
sig = [(k, v["p_two_sided"]) for k, v in R["rotation_null_exhaustive"].items()
       if v["p_two_sided"] is not None and v["p_two_sided"] < 0.05]
print(f"    {len(sig)} of {len(ps)} ladder tests have p<0.05   (expected by chance at 5%: {0.05*len(ps):.1f})")
for k, pv in sig:
    print(f"      {k}  p={pv:.4f}")
dose_sig = [(k, v["p_two_sided"]) for k, v in R["rotation_null_dose"]["exhaustive"].items()
            if v["p_two_sided"] < 0.05]
print(f"    dose tests with p<0.05: {len(dose_sig)} of 3   {dose_sig}")

print()
print("[5] headline numbers, rung (c) V0 vs V1 side by side")
for v in ("V0_as_spec", "V1_ex_decoupled"):
    s = R["ladder"]["c_exFOMC_exCPI_exNFP"][v]
    print(f"    {v:<18} n {s['n_speech']}/{s['n_nospeech']}  shareDays {s['share_days']:.3f}  "
          f"shareSS {s['share_sumsq']:.3f}  conc {s['concentration']:.3f}  "
          f"varR {s['var_ratio']:.3f}  mAbsR {s['mean_abs_ratio']:.3f}  medR {s['median_abs_ratio']:.3f}")

print()
print("[6] iid-vs-rotation null inflation on the dose trend (the task's central warning)")
a = R["dose_response"]["V0_as_spec"]["spearman_p_asymptotic"]
b = R["rotation_null_dose"]["exhaustive"]["spearman_rho_incl_zero"]["p_two_sided"]
print(f"    asymptotic (iid-style) Spearman p = {a:.4f}")
print(f"    circular-rotation          p = {b:.4f}    inflation factor {b/a:.1f}x")

print()
print("[7] config recorded")
c = R["config"]
print(f"    seed={c['seed']}  exhaustive={c['n_rotations_exhaustive']}  random={c['n_rotations_random']}"
      f"  boot={c['n_bootstrap']}  offsets={c['rotation_offset_range']}")

print()
print("VERIFY:", "ALL PASS" if ok else "FAILURES")
