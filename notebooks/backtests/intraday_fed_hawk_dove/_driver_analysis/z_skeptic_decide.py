r"""Is the trimmed-sample effect real, or vol-clustering / blackout confounding?

Tests the trimmed statistic (a) on rung (d) (ex-blackout), (b) matched on YESTERDAY's
|d| decile (the e2 control), (c) with the trim level treated as a forking path.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

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
is_fomc = p["is_fomc_day"].to_numpy(bool)
is_cpi = p["is_cpi_day"].to_numpy(bool)
is_nfp = p["is_nfp_day"].to_numpy(bool)
is_blk = p["is_blackout"].to_numpy(bool)
is_roll = p["is_imm_roll"].to_numpy(bool)
dates = p.index

mask_c = (~(is_fomc | is_cpi | is_nfp)) & has_d
mask_d = mask_c & ~is_blk

# --- what ARE the biggest rung-(c) days? ---------------------------------------
idx = np.where(mask_c)[0]
order = idx[np.argsort(-absd[idx])]
print("top 20 rung-(c) days by |d|:")
cum = 0.0
tot = float((d[mask_c] ** 2).sum())
for i, j in enumerate(order[:20]):
    cum += d[j] ** 2
    print(f"  {i+1:>2} {dates[j].date()}  d={d[j]:+8.2f}bp  speech={str(sp0[j]):<5} "
          f"roll={str(is_roll[j]):<5} blk={str(is_blk[j]):<5} cum_share={cum/tot*100:5.1f}%")
print()


def arm(mask, spf, key):
    ms, mn = mask & spf, mask & ~spf
    ns_, nn_ = int(ms.sum()), int(mn.sum())
    if ns_ < 2 or nn_ < 2:
        return np.nan
    ds, dn = d[ms], d[mn]
    as_, an_ = absd[ms], absd[mn]
    if key == "concentration":
        ss, sn = float((ds ** 2).sum()), float((dn ** 2).sum())
        return (ss / (ss + sn)) / (ns_ / (ns_ + nn_))
    if key == "var_ratio":
        return float(ds.var(ddof=1) / dn.var(ddof=1))
    if key == "mean_abs_ratio":
        return float(as_.mean() / an_.mean())
    if key == "median_abs_ratio":
        return float(np.median(as_) / np.median(an_))


def matched(mask, spf, key, lab):
    w, v = [], []
    for k in np.unique(lab[mask & (lab >= 0)]):
        bm = mask & (lab == k)
        ns_, nn_ = int((bm & spf).sum()), int((bm & ~spf).sum())
        if ns_ < 5 or nn_ < 5:
            continue
        val = arm(bm, spf, key)
        if np.isfinite(val):
            w.append(ns_ + nn_); v.append(val)
    if not w:
        return np.nan
    w = np.asarray(w, float); w /= w.sum()
    return float((w * np.asarray(v)).sum())


def two_sided_p(obs, nl):
    nl = np.asarray(nl, float); nl = nl[np.isfinite(nl)]
    nn = len(nl)
    return float(min(1.0, 2.0 * min((1 + int((nl >= obs).sum())) / (nn + 1),
                                    (1 + int((nl <= obs).sum())) / (nn + 1))))


OFF = np.arange(21, n - 21 + 1)
KEYS = ["concentration", "var_ratio", "mean_abs_ratio", "median_abs_ratio"]


def trim(mask, pct):
    ix = np.where(mask)[0]
    k = int(np.ceil(pct * len(ix)))
    o = ix[np.argsort(-absd[ix])]
    mm = mask.copy(); mm[o[:k]] = False
    return mm, k


def report(mask, label, lab=None):
    print(f"--- {label}  n={int(mask.sum())} "
          f"(sp {int((mask & sp0).sum())}/no {int((mask & ~sp0).sum())})"
          + ("  [MATCHED]" if lab is not None else ""))
    for key in KEYS:
        f = (lambda m, s: matched(m, s, key, lab)) if lab is not None else (lambda m, s: arm(m, s, key))
        obs = f(mask, sp0)
        nl = np.array([f(mask, np.roll(sp0, k)) for k in OFF])
        fin = nl[np.isfinite(nl)]
        print(f"    {key:18s} obs {obs:7.4f}  nullMed {np.median(fin):7.4f}  "
              f"null95 [{np.percentile(fin,2.5):6.3f},{np.percentile(fin,97.5):6.3f}]  "
              f"p={two_sided_p(obs, fin):.4f}")


# ---- lagged-|d| decile labels, computed on the rung-(d) V0 sample (as the author did)
lag = np.concatenate([[np.nan], absd[:-1]])
lag[~np.concatenate([[False], has_d[:-1]])] = np.nan
lab = np.full(n, -1, int)
ok = mask_d & np.isfinite(lag)
lab[ok] = pd.qcut(pd.Series(lag[ok]), 10, labels=False, duplicates="drop").to_numpy()

print("=" * 96)
print("A. TRIM DEPTH SWEEP on rung (c) -- forking-path exposure")
print("=" * 96)
for pct in (0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.08, 0.10):
    mm, k = trim(mask_c, pct)
    obs = {key: arm(mm, sp0, key) for key in KEYS}
    ps = {}
    for key in KEYS:
        nl = np.array([arm(mm, np.roll(sp0, kk), key) for kk in OFF])
        ps[key] = two_sided_p(obs[key], nl[np.isfinite(nl)])
    print(f"  trim {pct*100:4.1f}% ({k:>3}d)  conc {obs['concentration']:.3f} p={ps['concentration']:.4f} | "
          f"varR {obs['var_ratio']:.3f} p={ps['var_ratio']:.4f} | "
          f"meanR {obs['mean_abs_ratio']:.3f} p={ps['mean_abs_ratio']:.4f} | "
          f"medR {obs['median_abs_ratio']:.3f} p={ps['median_abs_ratio']:.4f}")

print()
print("=" * 96)
print("B. DOES THE 5%-TRIM EFFECT SURVIVE THE CONFOUND CONTROLS?")
print("=" * 96)
mm5, k5 = trim(mask_c, 0.05)
report(mm5, f"rung (c) trimmed 5% ({k5}d)")
print()
mmd5, kd5 = trim(mask_d, 0.05)
report(mmd5, f"rung (d) ex-blackout trimmed 5% ({kd5}d)")
print()
report(mask_d, "rung (e2) lagged-vol-matched, UNTRIMMED", lab=lab)
print()
report(mmd5, f"rung (e2) lagged-vol-matched, trimmed 5% ({kd5}d)", lab=lab)
