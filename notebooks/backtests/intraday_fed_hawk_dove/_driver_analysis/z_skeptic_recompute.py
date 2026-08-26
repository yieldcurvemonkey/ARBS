r"""INDEPENDENT SKEPTIC RE-COMPUTE of Analysis A headline numbers.

Written from the panel alone; does NOT import variance_ratio.py.
Run: C:\Users\chris\anaconda3\envs\stir\python.exe z_skeptic_recompute.py
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
print("panel shape", p.shape)
print("columns:", list(p.columns))
print()

n = len(p)
d_raw = p["d_rate_bp"].to_numpy(float)
has_d = np.isfinite(d_raw)
print("n_all", n, "deltas defined", int(has_d.sum()), "NaN deltas", int((~has_d).sum()))

d = np.nan_to_num(d_raw, nan=0.0)
absd = np.abs(d)
sp = p["is_speech_day"].to_numpy(bool)
ns = p["n_speakers"].to_numpy(int)

# --- consistency: is_speech_day == n_speakers>0 ? ------------------------------
mismatch = int((sp != (ns > 0)).sum())
print("is_speech_day != (n_speakers>0) on", mismatch, "rows")

is_fomc = p["is_fomc_day"].to_numpy(bool)
is_cpi = p["is_cpi_day"].to_numpy(bool)
is_nfp = p["is_nfp_day"].to_numpy(bool)
is_blk = p["is_blackout"].to_numpy(bool)

mask_c = (~(is_fomc | is_cpi | is_nfp)) & has_d
print("rung (c) V0 n =", int(mask_c.sum()), "(JSON says 1672)")
print()


def arm(mask, spflag):
    ms = mask & spflag
    mn = mask & ~spflag
    ns_, nn_ = int(ms.sum()), int(mn.sum())
    ds, dn = d[ms], d[mn]
    as_, an_ = absd[ms], absd[mn]
    ss_s, ss_n = float((ds ** 2).sum()), float((dn ** 2).sum())
    return dict(
        n_speech=ns_, n_nospeech=nn_,
        share_days=ns_ / (ns_ + nn_),
        share_sumsq=ss_s / (ss_s + ss_n),
        concentration=(ss_s / (ss_s + ss_n)) / (ns_ / (ns_ + nn_)),
        var_ratio=float(ds.var(ddof=1) / dn.var(ddof=1)),
        mean_abs_ratio=float(as_.mean() / an_.mean()),
        median_abs_ratio=float(np.median(as_) / np.median(an_)),
        mean_abs_speech=float(as_.mean()), mean_abs_nospeech=float(an_.mean()),
    )


base = arm(mask_c, sp)
print("=== RUNG (c) V0 -- headline recompute ===")
for k, v in base.items():
    print(f"  {k:22s} {v}")
print()

# --- REQUIRED: trim the top 1% of |d| days WITHIN rung (c) ---------------------
idx_c = np.where(mask_c)[0]
nc = len(idx_c)
order = idx_c[np.argsort(-absd[idx_c])]
for pct, label in ((0.01, "top 1%"), (0.005, "top 0.5%"), (0.02, "top 2%")):
    k = int(np.ceil(pct * nc))
    mm = mask_c.copy()
    mm[order[:k]] = False
    a = arm(mm, sp)
    print(f"=== rung (c) TRIMMED {label} ({k} days dropped) ===")
    print(f"  n {a['n_speech']}/{a['n_nospeech']}  share_days {a['share_days']:.4f} "
          f"share_sumsq {a['share_sumsq']:.4f}")
    print(f"  concentration {a['concentration']:.4f}   var_ratio {a['var_ratio']:.4f}   "
          f"mean|d|R {a['mean_abs_ratio']:.4f}   med|d|R {a['median_abs_ratio']:.4f}")
    # how are the trimmed days split by arm?
    tr = order[:k]
    print(f"  trimmed days: {int(sp[tr].sum())} speech / {int((~sp[tr]).sum())} non-speech")
    print()

# --- symmetric two-sided trim (winsor-free): also show top-20 for cross-check ---
for k in (1, 5, 10, 17, 20):
    mm = mask_c.copy()
    mm[order[:k]] = False
    a = arm(mm, sp)
    print(f"  ex-top{k:>3}: conc {a['concentration']:.3f}  varR {a['var_ratio']:.3f}  "
          f"meanR {a['mean_abs_ratio']:.3f}  medR {a['median_abs_ratio']:.3f}")
print()

# --- rank-based / robust alternatives ------------------------------------------
a_s = absd[mask_c & sp]
a_n = absd[mask_c & ~sp]
mw = stats.mannwhitneyu(a_s, a_n, alternative="two-sided")
print("Mann-Whitney U on |d| (speech vs non-speech), rung c V0: "
      f"U={mw.statistic:.0f} p={mw.pvalue:.4f}")
ks = stats.ks_2samp(a_s, a_n)
print(f"KS two-sample on |d|: D={ks.statistic:.4f} p={ks.pvalue:.4f}")
mood = stats.median_test(a_s, a_n)
print(f"Mood median test on |d|: stat={mood[0]:.3f} p={mood[1]:.4f}")
lev = stats.levene(d[mask_c & sp], d[mask_c & ~sp], center="median")
print(f"Brown-Forsythe on d: W={lev.statistic:.4f} p={lev.pvalue:.4f}  (JSON 0.877)")
tt = stats.ttest_ind(a_s, a_n, equal_var=False)
print(f"Welch on |d|: t={tt.statistic:.4f} p={tt.pvalue:.4f}  (JSON t=0.16 p=0.875)")
print(f"kurtosis of d on rung c: {stats.kurtosis(d[mask_c], fisher=True):.2f}")
print()

# --- INDEPENDENT EXHAUSTIVE ROTATION NULL, rung (c) V0 -------------------------
ROT_MIN = 21
offsets = np.arange(ROT_MIN, n - ROT_MIN + 1)
print("independent exhaustive rotation null, n_offsets =", len(offsets))

nullv = np.full(len(offsets), np.nan)
nullm = np.full(len(offsets), np.nan)
nullmed = np.full(len(offsets), np.nan)
nullcon = np.full(len(offsets), np.nan)
for i, k in enumerate(offsets):
    spr = np.roll(sp, k)
    a = arm(mask_c, spr)
    nullv[i] = a["var_ratio"]
    nullm[i] = a["mean_abs_ratio"]
    nullmed[i] = a["median_abs_ratio"]
    nullcon[i] = a["concentration"]


def two_sided_p(obs, nl):
    nl = np.asarray(nl, float)
    nl = nl[np.isfinite(nl)]
    nn = len(nl)
    ge = int((nl >= obs).sum())
    le = int((nl <= obs).sum())
    return float(min(1.0, 2.0 * min((1 + ge) / (nn + 1), (1 + le) / (nn + 1))))


for nm, nl, obs in (("var_ratio", nullv, base["var_ratio"]),
                    ("mean_abs_ratio", nullm, base["mean_abs_ratio"]),
                    ("median_abs_ratio", nullmed, base["median_abs_ratio"]),
                    ("concentration", nullcon, base["concentration"])):
    print(f"  {nm:18s} obs {obs:8.4f}  nullMed {np.median(nl):7.4f} "
          f"[{np.percentile(nl,2.5):7.4f},{np.percentile(nl,97.5):7.4f}]  p={two_sided_p(obs,nl):.4f}")
print()

# --- DOW-preserving subset of the null (offset multiple of 5) ------------------
sel5 = (offsets % 5) == 0
print("DOW-preserving subset (offset %% 5 == 0), n =", int(sel5.sum()))
for nm, nl, obs in (("var_ratio", nullv[sel5], base["var_ratio"]),
                    ("mean_abs_ratio", nullm[sel5], base["mean_abs_ratio"]),
                    ("median_abs_ratio", nullmed[sel5], base["median_abs_ratio"]),
                    ("concentration", nullcon[sel5], base["concentration"])):
    print(f"  {nm:18s} obs {obs:8.4f}  nullMed {np.median(nl):7.4f} "
          f"[{np.percentile(nl,2.5):7.4f},{np.percentile(nl,97.5):7.4f}]  p={two_sided_p(obs,nl):.4f}")
print()
print("non-DOW-preserving subset:")
for nm, nl, obs in (("var_ratio", nullv[~sel5], base["var_ratio"]),
                    ("median_abs_ratio", nullmed[~sel5], base["median_abs_ratio"])):
    print(f"  {nm:18s} obs {obs:8.4f}  nullMed {np.median(nl):7.4f}  p={two_sided_p(obs,nl):.4f}")
print()

# --- rotation-null self-match check: how correlated is rolled sp with sp0? -----
ov = np.array([float((np.roll(sp, k) == sp).mean()) for k in offsets])
print(f"agreement of rotated flag with original: min {ov.min():.3f} max {ov.max():.3f} "
      f"mean {ov.mean():.3f}; identity would be 1.000")
print(f"  n offsets with agreement > 0.70: {int((ov>0.70).sum())}")
print()

# --- DOSE-RESPONSE recompute ---------------------------------------------------
cap = np.minimum(ns, 4)
print("=== dose response, rung (c) V0 ===")
rows = []
for k in range(5):
    bm = mask_c & (cap == k)
    rows.append((k, int(bm.sum()), float(absd[bm].mean()), float(np.median(absd[bm]))))
    print(f"  speakers {k}: n={int(bm.sum()):>5}  mean|d|={absd[bm].mean():.3f}  "
          f"median|d|={np.median(absd[bm]):.3f}")
rho = stats.spearmanr(cap[mask_c].astype(float), absd[mask_c])
print(f"  spearman incl zero rho={rho.statistic:+.4f} asymptotic p={rho.pvalue:.4f}")
sm = mask_c & (ns >= 1)
rho2 = stats.spearmanr(ns[sm].astype(float), absd[sm])
print(f"  spearman speech-only  rho={rho2.statistic:+.4f} asymptotic p={rho2.pvalue:.4f}")
sl = stats.linregress(np.arange(5, dtype=float), np.array([r[2] for r in rows]))
print(f"  bucket-mean OLS slope {sl.slope:+.4f} bp/speaker")
print()

# --- blackout / speech interaction ---------------------------------------------
print("blackout mean|d| ", float(absd[mask_c & is_blk].mean()),
      " non-blackout ", float(absd[mask_c & ~is_blk].mean()))
print("speech rate in blackout", float(sp[mask_c & is_blk].mean()),
      " outside", float(sp[mask_c & ~is_blk].mean()))
print()

# --- COUNT p<0.05 CELLS IN THE JSON --------------------------------------------
js = json.load(open(os.path.join(OUT, "variance_ratio_results.json")))
rot = js["rotation_null_exhaustive"]
sig = [(k, v["p_two_sided"], v["observed"]) for k, v in rot.items()
       if v["p_two_sided"] is not None and v["p_two_sided"] < 0.05]
print(f"ladder rotation cells total = {len(rot)}; p<0.05 = {len(sig)}")
for s in sig:
    print("   ", s)
allp = sorted([(v["p_two_sided"], k) for k, v in rot.items() if v["p_two_sided"] is not None])
print("  five smallest p:", [(f"{a:.4f}", b) for a, b in allp[:5]])
print()

# --- min detectable effect: what median|d| ratio WOULD have cleared? ------------
k = "c_exFOMC_exCPI_exNFP|V0_as_spec|median_abs_ratio"
print("rung c V0 median_abs_ratio JSON:", rot[k])
k2 = "c_exFOMC_exCPI_exNFP|V0_as_spec|mean_abs_ratio"
print("rung c V0 mean_abs_ratio JSON:", rot[k2])
k3 = "c_exFOMC_exCPI_exNFP|V0_as_spec|var_ratio"
print("rung c V0 var_ratio JSON:", rot[k3])
k4 = "c_exFOMC_exCPI_exNFP|V0_as_spec|concentration"
print("rung c V0 concentration JSON:", rot[k4])
print()
print("JSON ladder rung c V0:")
lc = js["ladder"]["c_exFOMC_exCPI_exNFP"]["V0_as_spec"]
for kk in ("n_speech", "n_nospeech", "share_days", "share_sumsq", "concentration",
           "var_ratio", "mean_abs_ratio", "median_abs_ratio", "welch_t", "welch_p",
           "brown_forsythe_p"):
    print(f"   {kk:20s} {lc.get(kk)}")
