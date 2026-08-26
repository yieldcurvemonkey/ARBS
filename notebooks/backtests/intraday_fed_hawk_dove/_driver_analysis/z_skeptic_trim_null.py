r"""Decisive follow-up: does the TRIMMED rung-(c) statistic clear the rotation null?

The trim mask depends only on |d| (speech-independent), so it is held FIXED under
rotation exactly like the variant masks -- same treatment as the original script.
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd
from scipy import stats

sys.path.append(r"C:\Users\chris\clee\ARBS")
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
OUT = r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_driver_analysis"

p = pd.read_parquet(os.path.join(OUT, "panel_daily.parquet")).sort_index()
n = len(p)
d_raw = p["d_rate_bp"].to_numpy(float)
has_d = np.isfinite(d_raw)
d = np.nan_to_num(d_raw, nan=0.0)
absd = np.abs(d)
sp0 = p["is_speech_day"].to_numpy(bool)
ns0 = p["n_speakers"].to_numpy(int)
is_fomc = p["is_fomc_day"].to_numpy(bool)
is_cpi = p["is_cpi_day"].to_numpy(bool)
is_nfp = p["is_nfp_day"].to_numpy(bool)
is_blk = p["is_blackout"].to_numpy(bool)
is_roll = p["is_imm_roll"].to_numpy(bool)
yr = p["year"].to_numpy(int)
dates = p.index

DEC = ["2019-07-01", "2019-07-02", "2019-07-03", "2019-07-05", "2019-07-08", "2020-03-06"]
dec_mask = np.isin(dates.strftime("%Y-%m-%d").to_numpy(), np.array(DEC))

mask_c = (~(is_fomc | is_cpi | is_nfp)) & has_d
mask_c_V1 = mask_c & ~dec_mask
mask_c_V4 = mask_c & ~dec_mask & ~is_roll & (yr >= 2020)
mask_d = mask_c & ~is_blk


def arm(mask, spf):
    ms, mn = mask & spf, mask & ~spf
    ns_, nn_ = int(ms.sum()), int(mn.sum())
    if ns_ < 2 or nn_ < 2:
        return None
    ds, dn = d[ms], d[mn]
    as_, an_ = absd[ms], absd[mn]
    ss, sn = float((ds ** 2).sum()), float((dn ** 2).sum())
    return dict(share_days=ns_ / (ns_ + nn_), share_sumsq=ss / (ss + sn),
                concentration=(ss / (ss + sn)) / (ns_ / (ns_ + nn_)),
                var_ratio=float(ds.var(ddof=1) / dn.var(ddof=1)),
                mean_abs_ratio=float(as_.mean() / an_.mean()),
                median_abs_ratio=float(np.median(as_) / np.median(an_)))


def two_sided_p(obs, nl):
    nl = np.asarray(nl, float); nl = nl[np.isfinite(nl)]
    nn = len(nl)
    return float(min(1.0, 2.0 * min((1 + int((nl >= obs).sum())) / (nn + 1),
                                    (1 + int((nl <= obs).sum())) / (nn + 1))))


OFF = np.arange(21, n - 21 + 1)
KEYS = ["concentration", "var_ratio", "mean_abs_ratio", "median_abs_ratio"]


def null_table(mask, label):
    obs = arm(mask, sp0)
    acc = {k: np.full(len(OFF), np.nan) for k in KEYS}
    for i, k in enumerate(OFF):
        a = arm(mask, np.roll(sp0, k))
        if a is None:
            continue
        for kk in KEYS:
            acc[kk][i] = a[kk]
    print(f"--- {label}   n={int(mask.sum())} "
          f"(speech {int((mask & sp0).sum())}/non {int((mask & ~sp0).sum())})")
    for kk in KEYS:
        nl = acc[kk][np.isfinite(acc[kk])]
        print(f"    {kk:18s} obs {obs[kk]:7.4f}  nullMed {np.median(nl):7.4f}  "
              f"null95 [{np.percentile(nl,2.5):6.3f},{np.percentile(nl,97.5):6.3f}]  "
              f"p={two_sided_p(obs[kk], nl):.4f}")
    return obs, acc


def trim_mask(mask, pct):
    idx = np.where(mask)[0]
    k = int(np.ceil(pct * len(idx)))
    order = idx[np.argsort(-absd[idx])]
    mm = mask.copy(); mm[order[:k]] = False
    return mm, k


print("=" * 96)
print("ROTATION NULL ON TRIMMED SAMPLES  (trim is |d|-based, speech-independent, held FIXED)")
print("=" * 96)
null_table(mask_c, "rung (c) V0 UNTRIMMED")
print()
for pct in (0.005, 0.01, 0.02, 0.05):
    mm, k = trim_mask(mask_c, pct)
    null_table(mm, f"rung (c) V0 trimmed top {pct*100:g}% ({k} days)")
    print()

mm1, k1 = trim_mask(mask_c_V1, 0.01)
null_table(mask_c_V1, "rung (c) V1 (ex 2019 defect) UNTRIMMED")
null_table(mm1, f"rung (c) V1 trimmed top 1% ({k1} days)")
print()
mm4, k4 = trim_mask(mask_c_V4, 0.01)
null_table(mask_c_V4, "rung (c) V4_clean UNTRIMMED")
null_table(mm4, f"rung (c) V4_clean trimmed top 1% ({k4} days)")
print()
mmd, kd = trim_mask(mask_d, 0.01)
null_table(mask_d, "rung (d) V0 UNTRIMMED")
null_table(mmd, f"rung (d) V0 trimmed top 1% ({kd} days)")

# ------------------------------------------------------------------
# Rank-based location tests under the ROTATION null (not iid)
# ------------------------------------------------------------------
print()
print("=" * 96)
print("RANK / ROBUST LOCATION TESTS ON |d|, rung (c) V0 -- iid p vs ROTATION p")
print("=" * 96)


def mw_stat(mask, spf):
    a, b = absd[mask & spf], absd[mask & ~spf]
    return float(stats.mannwhitneyu(a, b, alternative="two-sided").statistic
                 / (len(a) * len(b)))          # common-language effect size (AUC)


def mood_stat(mask, spf):
    a, b = absd[mask & spf], absd[mask & ~spf]
    return float(stats.median_test(a, b)[0])


def ks_stat(mask, spf):
    a, b = absd[mask & spf], absd[mask & ~spf]
    return float(stats.ks_2samp(a, b).statistic)


for nm, fn, iidp in (("MannWhitney_AUC", mw_stat,
                      stats.mannwhitneyu(absd[mask_c & sp0], absd[mask_c & ~sp0],
                                         alternative="two-sided").pvalue),
                     ("Mood_median_chi2", mood_stat,
                      stats.median_test(absd[mask_c & sp0], absd[mask_c & ~sp0])[1]),
                     ("KS_D", ks_stat,
                      stats.ks_2samp(absd[mask_c & sp0], absd[mask_c & ~sp0]).pvalue)):
    obs = fn(mask_c, sp0)
    nl = np.array([fn(mask_c, np.roll(sp0, k)) for k in OFF])
    print(f"  {nm:18s} obs {obs:9.4f}  nullMed {np.median(nl):9.4f}  "
          f"iid p={iidp:.4f}   ROTATION p={two_sided_p(obs, nl):.4f}   "
          f"inflation x{(two_sided_p(obs,nl)/iidp if iidp>0 else np.nan):.1f}")

# ------------------------------------------------------------------
# Dependence among the 72 ladder cells: is "1 of 72, 3.6 expected" fair?
# ------------------------------------------------------------------
print()
print("=" * 96)
print("DEPENDENCE AMONG THE 72 LADDER CELLS")
print("=" * 96)
js = json.load(open(os.path.join(OUT, "variance_ratio_results.json")))
rot = js["rotation_null_exhaustive"]
byst = {}
for k, v in rot.items():
    r, var, st = k.split("|")
    byst.setdefault(st, []).append((v["p_two_sided"], r, var))
for st, lst in byst.items():
    lst2 = sorted([x for x in lst if x[0] is not None])
    print(f"  {st:18s} n={len(lst2)}  min p={lst2[0][0]:.4f} ({lst2[0][1]}|{lst2[0][2]})  "
          f"median p={np.median([x[0] for x in lst2]):.4f}  "
          f"n<0.10={sum(1 for x in lst2 if x[0]<0.10)}")
print()
print("  median_abs_ratio cells sorted by p:")
for pv, r, var in sorted([x for x in byst['median_abs_ratio'] if x[0] is not None]):
    o = rot[f"{r}|{var}|median_abs_ratio"]
    print(f"    p={pv:.4f}  {r:24s} {var:16s} obs={o['observed']:.3f} "
          f"nullMed={o['null_median']:.3f}")
