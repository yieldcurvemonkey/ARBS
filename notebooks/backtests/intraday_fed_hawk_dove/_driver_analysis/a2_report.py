import json, sys
import numpy as np

OUT = r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_driver_analysis"
R = json.load(open(OUT + r"\variance_ratio_results.json"))

def g(x, d="n/a", f="{:.3f}"):
    return f.format(x) if isinstance(x, (int, float)) else d

print("=" * 118)
print("LADDER")
print("=" * 118)
print(f"{'rung':<24}{'variant':<19}{'n_sp':>6}{'n_no':>6}{'shDay':>7}{'shSS':>7}{'conc':>7}"
      f"{'varR':>8}{'mAbsR':>7}{'medR':>7}{'WelchT':>8}{'Wp':>8}{'BFp':>8}")
print("-" * 118)
for r, vv in R["ladder"].items():
    for v in ["V0_as_spec", "V1_ex_decoupled", "V2_ex_dec_ex_roll", "V3_y2020plus", "V4_clean"]:
        s = vv[v]
        print(f"{r:<24}{v:<19}{s['n_speech']:>6}{s['n_nospeech']:>6}"
              f"{g(s.get('share_days')):>7}{g(s.get('share_sumsq')):>7}{g(s.get('concentration')):>7}"
              f"{g(s.get('var_ratio')):>8}{g(s.get('mean_abs_ratio')):>7}{g(s.get('median_abs_ratio')):>7}"
              f"{g(s.get('welch_t'),f='{:.2f}'):>8}{g(s.get('welch_p')):>8}{g(s.get('brown_forsythe_p')):>8}")
    print()

print("=" * 118)
print("BOOTSTRAP 95% CI (V0)")
print("=" * 118)
for r, vv in R["ladder_bootstrap_ci_95"].items():
    s = vv["V0_as_spec"]
    print(f"  {r:<26} varR [{g(s['var_ratio']['lo'])},{g(s['var_ratio']['hi'])}]  "
          f"mAbsR [{g(s['mean_abs_ratio']['lo'])},{g(s['mean_abs_ratio']['hi'])}]  "
          f"medR [{g(s['median_abs_ratio']['lo'])},{g(s['median_abs_ratio']['hi'])}]")

print()
print("=" * 118)
print("ROTATION NULL (exhaustive 1871) -- all variants")
print("=" * 118)
print(f"{'key':<56}{'obs':>9}{'nullMed':>9}{'n2.5':>9}{'n97.5':>9}{'p':>9}")
for k, v in R["rotation_null_exhaustive"].items():
    print(f"{k:<56}{g(v['observed']):>9}{g(v['null_median']):>9}{g(v['null_p2_5']):>9}"
          f"{g(v['null_p97_5']):>9}{g(v['p_two_sided'],f='{:.4f}'):>9}")

print()
print("=== random-5000 p's, rung c/d/e V0 (spec compliance; compare with exhaustive) ===")
for k, v in R["rotation_null_random_5000"].items():
    if "V0_as_spec" in k and k.split("|")[0] in ("c_exFOMC_exCPI_exNFP", "d_nonblackout",
                                                 "e_matched_fomc_prox", "e2_matched_lagged_vol"):
        print(f"  {k:<54} p={g(v['p_two_sided'],f='{:.4f}')}")

print()
print("=" * 118)
print("DOSE-RESPONSE")
print("=" * 118)
for v, dv in R["dose_response"].items():
    print(f"  {v}")
    for b in dv["buckets"]:
        print(f"    speakers {b['bucket']:>2}  n={b['n']:>5}  mean|d|={g(b['mean_abs_d'])}bp"
              f"  median|d|={g(b['median_abs_d'])}  var={g(b['var_d'],f='{:.2f}')}")
    print(f"    rho(incl 0)={g(dv['spearman_rho_incl_zero'],f='{:+.4f}')} (asym p {g(dv['spearman_p_asymptotic'],f='{:.4f}')})"
          f"   rho(speech only, n={dv['n_speech_days_only']})={g(dv['spearman_rho_speech_days_only'],f='{:+.4f}')}"
          f" (asym p {g(dv['spearman_p_asymptotic_speech_only'],f='{:.4f}')})"
          f"   slope={g(dv['bucket_mean_ols_slope_bp_per_speaker'],f='{:+.4f}')} bp/spk  r2={g(dv['bucket_mean_ols_r2'])}")
print()
for w in ("exhaustive", "random_5000"):
    print(f"  [{w}]")
    for k, v in R["rotation_null_dose"][w].items():
        print(f"    {k:<34} obs={g(v['observed'],f='{:+.4f}')}  null95 "
              f"[{g(v['null_p2_5'],f='{:+.4f}')},{g(v['null_p97_5'],f='{:+.4f}')}]  p={g(v['p_two_sided'],f='{:.4f}')}")

print()
print("=" * 118)
print("DOSE CI (V0)")
for b in R["dose_response_bootstrap_ci_95"]["V0_as_spec"]:
    print(f"    {b['bucket']:>2}  [{g(b['lo'])}, {g(b['hi'])}]")

print()
print("=" * 118)
print("REVERSE CAUSALITY")
print("=" * 118)
for k in ["m1_lags1to5", "m2_trailing5", "m3_lags_plus_calendar", "m4_trailing5_plus_calendar",
          "m0_lag1_alone", "m0_lag2_alone", "m0_lag3_alone", "m0_lag4_alone", "m0_lag5_alone"]:
    m = R["reverse_causality"][k]
    print(f"  {m['label']}   n={m['n']}  R2={m['r2']:.4f}  adjR2={m['r2_adj']:.4f}")
    for cn, cv in m["coefs"].items():
        if cn == "const" or cn.startswith("dow"):
            continue
        print(f"      {cn:<14} coef={cv['coef']:+.5f}  t_HAC={cv['t_hac']:+.2f}  "
              f"t_OLS={cv['t_ols']:+.2f}  p={cv['p_hac']:.4f}")
print(f"  R2 calendar only: {R['reverse_causality']['r2_calendar_only']:.4f}")
print(f"  incremental R2 of lagged vol: {R['reverse_causality']['incremental_r2_of_lagged_vol_over_calendar']:.5f}")

print()
print("=" * 118)
print("TAIL SENSITIVITY (rung c, V0)")
print("=" * 118)
t = R["tail_sensitivity_rung_c_V0"]
for k in ("top1", "top5", "top10", "top20"):
    print(f"  {k:>6} share of sum(d^2) = {t[k+'_share_of_rung_c_sumsq']*100:5.1f}%   "
          f"varR ex = {g(t['var_ratio_ex_'+k])}   mAbsR ex = {g(t['mean_abs_ratio_ex_'+k])}")
for d in t["top10_days_rung_c"]:
    print(f"    {d['date']}  d={d['d_bp']:+8.2f}  speech={str(d['speech']):<5} n_sp={d['n_speakers']} roll={d['imm_roll']}")

print()
print("=== rung sample sizes ===")
for r, vv in R["rung_sample_sizes"].items():
    print(f"  {r:<26} " + "  ".join(f"{k}={n}" for k, n in vv.items()))

print()
print("=== rung (e) per-stratum, V0 ===")
for s in R["ladder"]["e_matched_fomc_prox"]["V0_as_spec"]["strata"]:
    print(f"    stratum {s['stratum']}  n_sp={s['n_speech']:>4} n_no={s['n_nospeech']:>4} "
          f"varR={g(s.get('var_ratio')):>7} mAbsR={g(s.get('mean_abs_ratio')):>7} dropped={s['dropped']}")
print()
print("=== rung (e2) per-stratum, V0 ===")
for s in R["ladder"]["e2_matched_lagged_vol"]["V0_as_spec"]["strata"]:
    print(f"    stratum {s['stratum']}  n_sp={s['n_speech']:>4} n_no={s['n_nospeech']:>4} "
          f"varR={g(s.get('var_ratio')):>7} mAbsR={g(s.get('mean_abs_ratio')):>7} dropped={s['dropped']}")
