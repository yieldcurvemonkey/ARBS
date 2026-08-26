"""Verify the analysis machinery against inputs whose answer is known IN ADVANCE.

A checking tool that is itself wrong reports success and hides what it was built to find.
Three known-answer cases:
  K1  PLANTED DRIVER  -- speech days given a 3x larger sigma. var_ratio must be ~9,
      mean_abs_ratio ~3, and the rotation p must be small.
  K2  PLANTED NULL    -- rates iid, independent of the real speech calendar. Ratios ~1,
      and the rotation p must be LARGE (and roughly uniform across seeds).
  K3  DOSE PLANTED    -- sigma proportional to (1 + n_speakers). Spearman rho must be
      clearly positive and the bucket means must rise monotonically.
Also: a MUTATION of two_sided_p (always return 1.0) must break K1 -- proving the p-value
path is not vacuous.
"""
import sys
import numpy as np
import pandas as pd
from scipy import stats

sys.path.append(r"C:\Users\chris\clee\ARBS")
sys.path.append(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_driver_analysis")

from variance_ratio import arm_stats, matched_stats, two_sided_p, spearman_rho, block_boot_idx

OUT = r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_driver_analysis"
p = pd.read_parquet(OUT + r"\panel_daily.parquet").sort_index()
n = len(p)
sp0 = p["is_speech_day"].to_numpy(bool)
ns0 = p["n_speakers"].to_numpy(int)
mask = np.ones(n, bool)

rng = np.random.default_rng(7)
ok = True


def rot_p(d, absd, sp, stat_key, nrot=600):
    obs = arm_stats(d, absd, sp, mask)[stat_key]
    null = np.array([arm_stats(d, absd, np.roll(sp, k), mask)[stat_key]
                     for k in rng.integers(21, n - 20, size=nrot)])
    return obs, two_sided_p(obs, null)


print("=" * 78)
print("K1  PLANTED DRIVER: sigma 3x on speech days -> expect varR~9, mAbsR~3, p small")
d = rng.normal(0, 1.0, n) * np.where(sp0, 3.0, 1.0)
absd = np.abs(d)
st = arm_stats(d, absd, sp0, mask)
o, pv = rot_p(d, absd, sp0, "var_ratio")
print(f"    var_ratio={st['var_ratio']:.3f}  mean_abs_ratio={st['mean_abs_ratio']:.3f}"
       f"  concentration={st['concentration']:.3f}  rotation p={pv:.4f}")
c1 = 7.0 < st["var_ratio"] < 11.5 and 2.5 < st["mean_abs_ratio"] < 3.5 and pv < 0.01
print(f"    K1 {'PASS' if c1 else 'FAIL'}")
ok &= c1

print()
print("=" * 78)
print("K2  PLANTED NULL: rates iid, unrelated to the calendar -> expect ratios ~1, p large")
ps = []
for s in range(12):
    r2 = np.random.default_rng(100 + s)
    d2 = r2.normal(0, 1.0, n)
    a2 = np.abs(d2)
    obs = arm_stats(d2, a2, sp0, mask)["var_ratio"]
    null = np.array([arm_stats(d2, a2, np.roll(sp0, k), mask)["var_ratio"]
                     for k in r2.integers(21, n - 20, size=400)])
    ps.append(two_sided_p(obs, null))
ps = np.array(ps)
st2 = arm_stats(d2, a2, sp0, mask)
print(f"    last draw var_ratio={st2['var_ratio']:.3f}  mean_abs_ratio={st2['mean_abs_ratio']:.3f}")
print(f"    12 independent rate draws, rotation p: min={ps.min():.3f} median={np.median(ps):.3f}"
      f"  #(p<0.05)={int((ps < 0.05).sum())}/12   (expect ~0-1)")
c2 = 0.85 < st2["var_ratio"] < 1.18 and int((ps < 0.05).sum()) <= 2
print(f"    K2 {'PASS' if c2 else 'FAIL'}")
ok &= c2

print()
print("=" * 78)
print("K3  PLANTED DOSE: sigma proportional to (1+n_speakers) -> expect rising buckets, rho>0")
d3 = rng.normal(0, 1.0, n) * (1.0 + ns0)
a3 = np.abs(d3)
cap = np.minimum(ns0, 4)
means = [a3[cap == k].mean() for k in range(5)]
rho = spearman_rho(cap.astype(float), a3)
print("    bucket mean|d|:", " ".join(f"{m:.2f}" for m in means))
print(f"    Spearman rho = {rho:+.4f}")
mono = all(means[i] < means[i + 1] for i in range(4))
c3 = mono and rho > 0.3
print(f"    monotone={mono}  K3 {'PASS' if c3 else 'FAIL'}")
ok &= c3

print()
print("=" * 78)
print("K4  MATCHED-STRATA path: planted driver INSIDE every stratum must survive matching")
strata = np.repeat(np.arange(10), int(np.ceil(n / 10)))[:n]
ms = matched_stats(d, absd, sp0, mask, strata)
print(f"    matched var_ratio={ms['var_ratio']:.3f} (arith)  {ms['var_ratio_geo']:.3f} (geo)"
      f"  strata used={ms['n_strata_used']}")
c4 = 6.0 < ms["var_ratio"] < 13.0 and ms["n_strata_used"] == 10
print(f"    K4 {'PASS' if c4 else 'FAIL'}")
ok &= c4

print()
print("=" * 78)
print("K5  MUTATION: break two_sided_p (always 1.0) -- K1 must then FAIL")
import variance_ratio as VR
_orig = VR.two_sided_p
VR.two_sided_p = lambda obs, null: 1.0
o5 = arm_stats(d, absd, sp0, mask)["var_ratio"]
p5 = VR.two_sided_p(o5, np.array([1.0]))
VR.two_sided_p = _orig
c5 = not (p5 < 0.01)
print(f"    with the mutation, K1's p = {p5:.4f} -> K1 would {'FAIL' if c5 else 'still pass (BAD)'}")
print(f"    K5 {'PASS' if c5 else 'FAIL'}  (the p-value path is load-bearing, not vacuous)")
ok &= c5

print()
print("=" * 78)
print("K6  block bootstrap draws n indices, blocks are contiguous mod n")
ix = block_boot_idx(n, np.random.default_rng(1))
contig = np.mean(np.diff(ix) == 1)
c6 = len(ix) == n and contig > 0.85
print(f"    len={len(ix)} (want {n})   fraction of consecutive steps = {contig:.3f} (want ~0.9 for L=10)")
print(f"    K6 {'PASS' if c6 else 'FAIL'}")
ok &= c6

print()
print("=" * 78)
print("SELF-TEST:", "ALL PASS" if ok else "FAILURES PRESENT")
sys.exit(0 if ok else 1)
