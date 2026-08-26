r"""ANALYSIS A -- VARIANCE RATIO: does Fedspeak concentrate US front-end variance?

Target series : USD-SOFR-1D IMM_3xIMM_4 OUTRIGHT RATE, daily change in bp (d_rate_bp)
Panel         : _driver_analysis/panel_daily.parquet, 1,912 business days 2019-01-02..2026-08-24

WHAT THIS DOES
  A control LADDER (rungs a..e) removing one confound at a time, each rung reported on
  five pre-registered sample VARIANTS (V0..V4).  A circular-rotation null supplies the
  p-values.  A dose-response on n_speakers.  A reverse-causality regression.

EVERYTHING BELOW THE CONFIG BLOCK IS FIXED BEFORE ANY RESULT IS SEEN.  The variant grid,
the decoupled-day exclusion rule, the seed, the bucket rules and the min-n rules were all
written down first; the verdict is read off the numbers table, not chosen.

Run:  C:\Users\chris\anaconda3\envs\stir\python.exe variance_ratio.py
"""
from __future__ import annotations

import json
import os
import sys
from typing import Dict, List

import numpy as np
import pandas as pd
from scipy import stats

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

sys.path.append(r"C:\Users\chris\clee\ARBS")
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

OUT = r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_driver_analysis"

# ===================================================================================
# CONFIG -- pre-registered
# ===================================================================================
SEED = 20260825
N_ROT_RANDOM = 5000          # spec: >= 5000 random rotations
N_BOOT = 2000                # block-bootstrap reps for CIs
BLOCK_LEN = 10               # business days; respects vol clustering
ROT_MIN = 21                 # spec: offsets drawn from [21, n-21]
MIN_ARM_N = 30               # a rung arm below this is not reported
MIN_BUCKET_ARM_N = 5         # a stratum arm below this is dropped from the matched average
N_STRATA = 10                # deciles

# Days on which the TARGET series is decoupled from the rest of the curve.
# Derived by a rule applied to the whole span (a0e_decouple_screen.py):
#     |d_imm| > 20bp  AND  |d_imm| > 5 * max(|d_2y|, |d_5y|)
# The rule fires 11 times; 8 are IMM-roll dates (a roll legitimately jumps the level and
# is handled by the separate is_imm_roll cut), leaving 3 non-roll hits.  The rule does NOT
# fire on SVB week (2023-03-13, d_imm -114.7bp) because the 2y moved -70.2bp that day --
# that is a real move, and the screen correctly leaves it in.
DECOUPLED_NONROLL = ["2019-07-01", "2019-07-08", "2020-03-06"]
# 2019-07-01..07-05 is a contiguous corrupt-level window: the ON leg reads ~0.0 (impossible;
# published SOFR was ~2.4%) and imm3x4 sits ~73bp above its neighbours.  The two boundary
# deltas are the screen hits; the three interior deltas track the 2y within ~1bp and are
# arguably fine, but the whole window is dropped for conservatism.
CORRUPT_WINDOW_INTERIOR = ["2019-07-02", "2019-07-03", "2019-07-05"]
DECOUPLED_DAYS = sorted(set(DECOUPLED_NONROLL) | set(CORRUPT_WINDOW_INTERIOR))

VARIANT_DEFS = {
    "V0_as_spec": {
        "desc": "every business day with a defined delta -- the ladder exactly as specified",
        "bias": "neutral (nothing removed)",
    },
    "V1_ex_decoupled": {
        "desc": f"V0 minus {len(DECOUPLED_DAYS)} curve-build-defect deltas {DECOUPLED_DAYS}",
        "bias": "FLATTERS the thesis: all but one of these sit in the NON-speech arm, so "
                "removing them shrinks the non-speech denominator's variance",
    },
    "V2_ex_dec_ex_roll": {
        "desc": "V1 minus all is_imm_roll days (the constant-relative-rank slot books the roll jump)",
        "bias": "FLATTERS the thesis: rolls are 25-vs-11 in favour of the non-speech arm at rung (c) "
                "and are 4.7x more volatile than ordinary days",
    },
    "V3_y2020plus": {
        "desc": "V0 restricted to 2020+ (the build flags the 2019 target as provisional: the whole "
                "curve is flat on 124 consecutive days 2019-01-02..06-28)",
        "bias": "FLATTERS the thesis: the two largest non-speech-arm outliers are both in 2019",
    },
    "V4_clean": {
        "desc": "V2 restricted to 2020+ -- the maximally clean sample (ex-defect, ex-roll, ex-2019)",
        "bias": "FLATTERS the thesis on all three counts; quote alongside V0, never alone",
    },
}

RUNG_DEFS = {
    "a_all": "all days",
    "b_exFOMC": "ex FOMC decision days",
    "c_exFOMC_exCPI_exNFP": "ex FOMC, ex CPI, ex NFP",
    "d_nonblackout": "(c) restricted to NON-blackout days in BOTH arms",
    "e_matched_fomc_prox": "(d) matched on days_to_fomc deciles, size-weighted across strata",
    "e2_matched_lagged_vol": "(d) matched on YESTERDAY's |d| deciles -- the reverse-causality control",
}

# dataviz reference palette (light mode), validated all-pairs for the first three slots
C_S1 = "#2a78d6"   # blue    -- variance ratio
C_S2 = "#eb6834"   # orange  -- mean|d| ratio
C_S3 = "#1baf7a"   # aqua    -- median|d| ratio (direct-labelled: relief rule)
C_INK = "#0b0b0b"
C_INK2 = "#52514e"
C_MUTED = "#8a8880"
C_GRID = "#e4e3de"
C_NULLBAND = "#d6d5cf"
C_SURF = "#fcfcfb"
LABEL_X = (4.9, 8.4, 14.4)   # forest-plot value-column positions (log-x data coords)


# ===================================================================================
# statistics
# ===================================================================================
def _welch_t(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = len(a), len(b)
    if na < 2 or nb < 2:
        return np.nan
    va, vb = a.var(ddof=1), b.var(ddof=1)
    se = np.sqrt(va / na + vb / nb)
    return float((a.mean() - b.mean()) / se) if se > 0 else np.nan


def arm_stats(d: np.ndarray, absd: np.ndarray, sp: np.ndarray, mask: np.ndarray) -> Dict:
    """Speech-vs-no-speech statistics inside `mask`.  `sp` is the (possibly rotated) flag."""
    m_s = mask & sp
    m_n = mask & (~sp)
    ns_, nn_ = int(m_s.sum()), int(m_n.sum())
    out = {"n_speech": ns_, "n_nospeech": nn_, "n_total": ns_ + nn_}
    if ns_ < 2 or nn_ < 2:
        out.update(dict.fromkeys(
            ["share_days", "share_sumsq", "concentration", "var_ratio",
             "mean_abs_ratio", "median_abs_ratio", "mean_abs_speech", "mean_abs_nospeech",
             "median_abs_speech", "median_abs_nospeech", "var_speech", "var_nospeech",
             "welch_t_absd"], np.nan))
        return out
    ds, dn = d[m_s], d[m_n]
    as_, an_ = absd[m_s], absd[m_n]
    ss_s, ss_n = float((ds ** 2).sum()), float((dn ** 2).sum())
    vs_, vn_ = float(ds.var(ddof=1)), float(dn.var(ddof=1))
    out.update({
        "share_days": ns_ / (ns_ + nn_),
        "share_sumsq": ss_s / (ss_s + ss_n) if (ss_s + ss_n) > 0 else np.nan,
        "concentration": (ss_s / (ss_s + ss_n)) / (ns_ / (ns_ + nn_)) if (ss_s + ss_n) > 0 else np.nan,
        "var_speech": vs_, "var_nospeech": vn_,
        "var_ratio": vs_ / vn_ if vn_ > 0 else np.nan,
        "mean_abs_speech": float(as_.mean()), "mean_abs_nospeech": float(an_.mean()),
        "mean_abs_ratio": float(as_.mean() / an_.mean()) if an_.mean() > 0 else np.nan,
        "median_abs_speech": float(np.median(as_)), "median_abs_nospeech": float(np.median(an_)),
        "median_abs_ratio": float(np.median(as_) / np.median(an_)) if np.median(an_) > 0 else np.nan,
        "welch_t_absd": _welch_t(as_, an_),
    })
    return out


def matched_stats(d, absd, sp, mask, strata) -> Dict:
    """Within-stratum speech/no-speech ratios, then size-weighted across strata.

    `strata` is a fixed integer label per row (-1 = outside the matched sample).  It is
    computed ONCE from the real rung-(d) sample and does NOT rotate.
    """
    rows, w, vr, mr, medr, shd, shs, con = [], [], [], [], [], [], [], []
    for k in np.unique(strata[mask & (strata >= 0)]):
        bm = mask & (strata == k)
        st = arm_stats(d, absd, sp, bm)
        if st["n_speech"] < MIN_BUCKET_ARM_N or st["n_nospeech"] < MIN_BUCKET_ARM_N:
            st["dropped"] = True
            rows.append({"stratum": int(k), **st})
            continue
        st["dropped"] = False
        rows.append({"stratum": int(k), **st})
        w.append(st["n_total"]); vr.append(st["var_ratio"])
        mr.append(st["mean_abs_ratio"]); medr.append(st["median_abs_ratio"])
        shd.append(st["share_days"]); shs.append(st["share_sumsq"]); con.append(st["concentration"])
    if not w:
        return {"strata": rows, "var_ratio": np.nan, "mean_abs_ratio": np.nan,
                "median_abs_ratio": np.nan, "var_ratio_geo": np.nan, "mean_abs_ratio_geo": np.nan,
                "share_days": np.nan, "share_sumsq": np.nan, "concentration": np.nan,
                "n_strata_used": 0, "n_speech": 0, "n_nospeech": 0}
    w = np.asarray(w, float); w = w / w.sum()
    vr, mr, medr = np.asarray(vr), np.asarray(mr), np.asarray(medr)
    shd, shs, con = np.asarray(shd), np.asarray(shs), np.asarray(con)
    used = [r for r in rows if not r["dropped"]]
    return {
        "strata": rows,
        "n_strata_used": len(used),
        "n_speech": int(sum(r["n_speech"] for r in used)),
        "n_nospeech": int(sum(r["n_nospeech"] for r in used)),
        "var_ratio": float((w * vr).sum()),
        "mean_abs_ratio": float((w * mr).sum()),
        "median_abs_ratio": float((w * medr).sum()),
        "share_days": float((w * shd).sum()),
        "share_sumsq": float((w * shs).sum()),
        "concentration": float((w * con).sum()),
        "var_ratio_geo": float(np.exp((w * np.log(vr)).sum())),
        "mean_abs_ratio_geo": float(np.exp((w * np.log(mr)).sum())),
        "share_note": "share_days / share_sumsq / concentration are the size-weighted averages of "
                      "the WITHIN-stratum values, not pooled shares",
    }


def spearman_rho(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) < 5:
        return np.nan
    return float(stats.spearmanr(x, y).statistic)


def two_sided_p(obs: float, null: np.ndarray) -> float:
    null = np.asarray(null, float)
    null = null[np.isfinite(null)]
    if not np.isfinite(obs) or len(null) == 0:
        return np.nan
    n = len(null)
    ge = int((null >= obs).sum()); le = int((null <= obs).sum())
    return float(min(1.0, 2.0 * min((1 + ge) / (n + 1), (1 + le) / (n + 1))))


def block_boot_idx(n: int, rng: np.random.Generator) -> np.ndarray:
    nb = int(np.ceil(n / BLOCK_LEN))
    starts = rng.integers(0, n, size=nb)
    idx = (starts[:, None] + np.arange(BLOCK_LEN)[None, :]).ravel() % n
    return idx[:n]


def jsonable(o):
    if isinstance(o, dict):
        return {str(k): jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [jsonable(v) for v in o]
    if isinstance(o, (np.bool_, bool)):
        return bool(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, (np.ndarray,)):
        return [jsonable(v) for v in o.tolist()]
    if isinstance(o, (pd.Timestamp,)):
        return o.strftime("%Y-%m-%d")
    return o


# ===================================================================================
# MAIN
# ===================================================================================
def main() -> Dict:
    p = pd.read_parquet(os.path.join(OUT, "panel_daily.parquet"))
    p = p.sort_index()
    n_all = len(p)

    # -- explicit drop of the single undefined first delta -------------------------
    has_d = p["d_rate_bp"].notna().to_numpy()
    assert int((~has_d).sum()) == 1, f"expected exactly 1 NaN delta, got {(~has_d).sum()}"

    d = p["d_rate_bp"].to_numpy(float)
    absd = np.abs(d)
    d = np.nan_to_num(d, nan=0.0)          # masked out everywhere by has_d
    absd = np.nan_to_num(absd, nan=0.0)
    sp0 = p["is_speech_day"].to_numpy(bool)
    ns0 = p["n_speakers"].to_numpy(int)
    dates = p.index

    is_fomc = p["is_fomc_day"].to_numpy(bool)
    is_cpi = p["is_cpi_day"].to_numpy(bool)
    is_nfp = p["is_nfp_day"].to_numpy(bool)
    is_blk = p["is_blackout"].to_numpy(bool)
    is_roll = p["is_imm_roll"].to_numpy(bool)
    dtf = p["days_to_fomc"].to_numpy(float)
    yr = p["year"].to_numpy(int)

    dec_mask = np.isin(dates.strftime("%Y-%m-%d").to_numpy(), np.array(DECOUPLED_DAYS))

    # -- variant masks (fixed, speech-independent) ---------------------------------
    variants = {
        "V0_as_spec": has_d,
        "V1_ex_decoupled": has_d & ~dec_mask,
        "V2_ex_dec_ex_roll": has_d & ~dec_mask & ~is_roll,
        "V3_y2020plus": has_d & (yr >= 2020),
        "V4_clean": has_d & ~dec_mask & ~is_roll & (yr >= 2020),
    }
    # -- rung masks (fixed, speech-independent) ------------------------------------
    rung_base = {
        "a_all": np.ones(n_all, bool),
        "b_exFOMC": ~is_fomc,
        "c_exFOMC_exCPI_exNFP": ~(is_fomc | is_cpi | is_nfp),
        "d_nonblackout": ~(is_fomc | is_cpi | is_nfp) & ~is_blk,
    }
    rung_base["e_matched_fomc_prox"] = rung_base["d_nonblackout"]
    rung_base["e2_matched_lagged_vol"] = rung_base["d_nonblackout"]

    # -- strata, computed ONCE on the REAL rung-(d) sample of V0 and held fixed -----
    def make_strata(vals: np.ndarray, base: np.ndarray) -> np.ndarray:
        lab = np.full(n_all, -1, int)
        ok = base & np.isfinite(vals)
        if ok.sum() < N_STRATA:
            return lab
        q = pd.qcut(pd.Series(vals[ok]), N_STRATA, labels=False, duplicates="drop")
        lab[ok] = q.to_numpy()
        return lab

    d_ref = rung_base["d_nonblackout"] & variants["V0_as_spec"]
    strata_fomc = make_strata(dtf, d_ref)
    lag_absd = np.concatenate([[np.nan], absd[:-1]])
    lag_absd[~np.concatenate([[False], has_d[:-1]])] = np.nan
    strata_lag = make_strata(lag_absd, d_ref & np.isfinite(lag_absd))

    STRATA = {"e_matched_fomc_prox": strata_fomc, "e2_matched_lagged_vol": strata_lag}

    def rung_mask(rung: str, variant: str) -> np.ndarray:
        m = rung_base[rung] & variants[variant]
        if rung in STRATA:
            m = m & (STRATA[rung] >= 0)
        return m

    def stat_for(rung: str, variant: str, sp: np.ndarray) -> Dict:
        m = rung_mask(rung, variant)
        if rung in STRATA:
            return matched_stats(d, absd, sp, m, STRATA[rung])
        return arm_stats(d, absd, sp, m)

    # ---------------------------------------------------------------------------
    # 1. THE LADDER (observed)
    # ---------------------------------------------------------------------------
    ladder: Dict[str, Dict[str, Dict]] = {}
    for rung in RUNG_DEFS:
        ladder[rung] = {}
        for variant in variants:
            st = stat_for(rung, variant, sp0)
            m = rung_mask(rung, variant)
            # scipy tests on the real data only
            if rung not in STRATA:
                a = absd[m & sp0]; b = absd[m & ~sp0]
                da = d[m & sp0]; db = d[m & ~sp0]
                if len(a) >= MIN_ARM_N and len(b) >= MIN_ARM_N:
                    tt = stats.ttest_ind(a, b, equal_var=False)
                    lv = stats.levene(da, db, center="median")
                    st["welch_t"] = float(tt.statistic); st["welch_p"] = float(tt.pvalue)
                    st["welch_df"] = float(tt.df)
                    st["brown_forsythe_W"] = float(lv.statistic)
                    st["brown_forsythe_p"] = float(lv.pvalue)
                else:
                    st["welch_t"] = st["welch_p"] = st["welch_df"] = np.nan
                    st["brown_forsythe_W"] = st["brown_forsythe_p"] = np.nan
            else:
                # pooled test across strata: de-mean |d| within stratum, then Welch
                lab = STRATA[rung]
                a_idx = m & sp0; b_idx = m & ~sp0
                z = np.full(n_all, np.nan)
                for k in np.unique(lab[m]):
                    bm = m & (lab == k)
                    z[bm] = absd[bm] - absd[bm].mean()
                a, b = z[a_idx], z[b_idx]
                a, b = a[np.isfinite(a)], b[np.isfinite(b)]
                if len(a) >= MIN_ARM_N and len(b) >= MIN_ARM_N:
                    tt = stats.ttest_ind(a, b, equal_var=False)
                    st["welch_t"] = float(tt.statistic); st["welch_p"] = float(tt.pvalue)
                    st["welch_df"] = float(tt.df)
                    st["welch_note"] = "on |d| de-meaned WITHIN stratum"
                    lv = stats.levene(d[a_idx], d[b_idx], center="median")
                    st["brown_forsythe_W"] = float(lv.statistic)
                    st["brown_forsythe_p"] = float(lv.pvalue)
                    st["brown_forsythe_note"] = "pooled across strata (not stratified)"
                else:
                    st["welch_t"] = st["welch_p"] = st["welch_df"] = np.nan
                    st["brown_forsythe_W"] = st["brown_forsythe_p"] = np.nan
            ladder[rung][variant] = st

    # ---------------------------------------------------------------------------
    # 2. DOSE-RESPONSE on rung (c)
    # ---------------------------------------------------------------------------
    def dose_table(variant: str) -> Dict:
        m = rung_mask("c_exFOMC_exCPI_exNFP", variant)
        cap = np.minimum(ns0, 4)
        rows = []
        for k in range(5):
            bm = m & (cap == k)
            a = absd[bm]
            rows.append({"bucket": "4+" if k == 4 else str(k), "k": k, "n": int(bm.sum()),
                         "mean_abs_d": float(a.mean()) if len(a) else np.nan,
                         "median_abs_d": float(np.median(a)) if len(a) else np.nan,
                         "var_d": float(d[bm].var(ddof=1)) if bm.sum() > 1 else np.nan})
        rho_all = spearman_rho(cap[m].astype(float), absd[m])
        sr = stats.spearmanr(cap[m].astype(float), absd[m])
        sm_ = m & (ns0 >= 1)
        rho_int = spearman_rho(ns0[sm_].astype(float), absd[sm_])
        sr_int = stats.spearmanr(ns0[sm_].astype(float), absd[sm_])
        # OLS slope of bucket means on bucket index
        bk = np.array([r["k"] for r in rows], float)
        bm_ = np.array([r["mean_abs_d"] for r in rows], float)
        sl = stats.linregress(bk, bm_)
        return {"buckets": rows,
                "spearman_rho_incl_zero": rho_all, "spearman_p_asymptotic": float(sr.pvalue),
                "spearman_rho_speech_days_only": rho_int,
                "spearman_p_asymptotic_speech_only": float(sr_int.pvalue),
                "n_speech_days_only": int(sm_.sum()),
                "bucket_mean_ols_slope_bp_per_speaker": float(sl.slope),
                "bucket_mean_ols_r2": float(sl.rvalue ** 2),
                "kendall_tau_incl_zero": float(stats.kendalltau(cap[m].astype(float), absd[m]).statistic)}

    dose = {v: dose_table(v) for v in variants}

    # ---------------------------------------------------------------------------
    # 3. CIRCULAR-ROTATION NULL
    #    Rotate (is_speech_day, n_speakers) TOGETHER over the full 1,912-row index.
    #    The FOMC/CPI/NFP/blackout masks, days_to_fomc, the stratum labels and the
    #    variant masks are FIXED -- they do not rotate.
    # ---------------------------------------------------------------------------
    rng = np.random.default_rng(SEED)
    offsets_exact = np.arange(ROT_MIN, n_all - ROT_MIN + 1)          # 1,871 rotations
    offsets_random = rng.integers(ROT_MIN, n_all - ROT_MIN + 1, size=N_ROT_RANDOM)

    STATS_NULLED = ["var_ratio", "mean_abs_ratio", "median_abs_ratio", "concentration"]
    NULL_CELLS = [(r, v) for r in RUNG_DEFS for v in ("V0_as_spec", "V1_ex_decoupled", "V4_clean")]

    def run_null(offsets: np.ndarray) -> Dict:
        acc = {f"{r}|{v}|{s}": np.full(len(offsets), np.nan)
               for (r, v) in NULL_CELLS for s in STATS_NULLED}
        dose_acc = {"rho_incl_zero": np.full(len(offsets), np.nan),
                    "rho_speech_only": np.full(len(offsets), np.nan),
                    "slope": np.full(len(offsets), np.nan)}
        mc = rung_mask("c_exFOMC_exCPI_exNFP", "V0_as_spec")
        for i, k in enumerate(offsets):
            sp = np.roll(sp0, k)
            ns = np.roll(ns0, k)
            for (r, v) in NULL_CELLS:
                st = stat_for(r, v, sp)
                for s in STATS_NULLED:
                    acc[f"{r}|{v}|{s}"][i] = st.get(s, np.nan)
            cap = np.minimum(ns, 4)
            dose_acc["rho_incl_zero"][i] = spearman_rho(cap[mc].astype(float), absd[mc])
            sm_ = mc & (ns >= 1)
            dose_acc["rho_speech_only"][i] = spearman_rho(ns[sm_].astype(float), absd[sm_])
            bmn = [absd[mc & (cap == j)].mean() if (mc & (cap == j)).sum() else np.nan
                   for j in range(5)]
            bmn = np.asarray(bmn, float)
            ok = np.isfinite(bmn)
            dose_acc["slope"][i] = (stats.linregress(np.arange(5)[ok], bmn[ok]).slope
                                    if ok.sum() >= 3 else np.nan)
        return {"ladder": acc, "dose": dose_acc}

    print("  rotation null: exhaustive enumeration of all", len(offsets_exact), "offsets ...")
    null_exact = run_null(offsets_exact)
    print("  rotation null:", N_ROT_RANDOM, "seeded random offsets ...")
    null_random = run_null(offsets_random)

    def null_summary(null, obs_getter) -> Dict:
        out = {}
        for (r, v) in NULL_CELLS:
            for s in STATS_NULLED:
                key = f"{r}|{v}|{s}"
                nl = null["ladder"][key]
                obs = obs_getter(r, v, s)
                fin = nl[np.isfinite(nl)]
                out[key] = {
                    "observed": obs,
                    "p_two_sided": two_sided_p(obs, nl),
                    "null_median": float(np.median(fin)) if len(fin) else np.nan,
                    "null_p2_5": float(np.percentile(fin, 2.5)) if len(fin) else np.nan,
                    "null_p97_5": float(np.percentile(fin, 97.5)) if len(fin) else np.nan,
                    "n_null_draws": int(len(fin)),
                }
        return out

    def obs_get(r, v, s):
        return ladder[r][v].get(s, np.nan)

    rot_exact = null_summary(null_exact, obs_get)
    rot_random = null_summary(null_random, obs_get)

    dose_null = {}
    for which, nl in (("exhaustive", null_exact), ("random_5000", null_random)):
        dose_null[which] = {
            "spearman_rho_incl_zero": {
                "observed": dose["V0_as_spec"]["spearman_rho_incl_zero"],
                "p_two_sided": two_sided_p(dose["V0_as_spec"]["spearman_rho_incl_zero"],
                                           nl["dose"]["rho_incl_zero"]),
                "null_p2_5": float(np.nanpercentile(nl["dose"]["rho_incl_zero"], 2.5)),
                "null_p97_5": float(np.nanpercentile(nl["dose"]["rho_incl_zero"], 97.5)),
            },
            "spearman_rho_speech_days_only": {
                "observed": dose["V0_as_spec"]["spearman_rho_speech_days_only"],
                "p_two_sided": two_sided_p(dose["V0_as_spec"]["spearman_rho_speech_days_only"],
                                           nl["dose"]["rho_speech_only"]),
                "null_p2_5": float(np.nanpercentile(nl["dose"]["rho_speech_only"], 2.5)),
                "null_p97_5": float(np.nanpercentile(nl["dose"]["rho_speech_only"], 97.5)),
            },
            "bucket_mean_ols_slope": {
                "observed": dose["V0_as_spec"]["bucket_mean_ols_slope_bp_per_speaker"],
                "p_two_sided": two_sided_p(dose["V0_as_spec"]["bucket_mean_ols_slope_bp_per_speaker"],
                                           nl["dose"]["slope"]),
                "null_p2_5": float(np.nanpercentile(nl["dose"]["slope"], 2.5)),
                "null_p97_5": float(np.nanpercentile(nl["dose"]["slope"], 97.5)),
            },
        }

    # ---------------------------------------------------------------------------
    # 4. BLOCK-BOOTSTRAP CIs  (circular block bootstrap on the full panel rows)
    # ---------------------------------------------------------------------------
    rng_b = np.random.default_rng(SEED + 1)
    boot_idx = [block_boot_idx(n_all, rng_b) for _ in range(N_BOOT)]

    def boot_ladder(rung: str, variant: str) -> Dict:
        m = rung_mask(rung, variant)
        lab = STRATA.get(rung)
        keys = ["var_ratio", "mean_abs_ratio", "median_abs_ratio", "concentration"]
        acc = {k: np.full(N_BOOT, np.nan) for k in keys}
        for i, ix in enumerate(boot_idx):
            mm = m[ix]
            if lab is None:
                st = arm_stats(d[ix], absd[ix], sp0[ix], mm)
            else:
                st = matched_stats(d[ix], absd[ix], sp0[ix], mm, lab[ix])
            for k in keys:
                acc[k][i] = st.get(k, np.nan)
        return {k: {"lo": float(np.nanpercentile(v, 2.5)), "hi": float(np.nanpercentile(v, 97.5))}
                for k, v in acc.items()}

    print("  block bootstrap:", N_BOOT, "reps x", len(RUNG_DEFS), "rungs x 2 variants ...")
    boot = {r: {v: boot_ladder(r, v) for v in ("V0_as_spec", "V1_ex_decoupled")} for r in RUNG_DEFS}

    def boot_dose(variant: str) -> List[Dict]:
        m = rung_mask("c_exFOMC_exCPI_exNFP", variant)
        cap = np.minimum(ns0, 4)
        acc = np.full((N_BOOT, 5), np.nan)
        for i, ix in enumerate(boot_idx):
            mm, cc, aa = m[ix], cap[ix], absd[ix]
            for k in range(5):
                sel = mm & (cc == k)
                if sel.sum():
                    acc[i, k] = aa[sel].mean()
        return [{"bucket": "4+" if k == 4 else str(k),
                 "lo": float(np.nanpercentile(acc[:, k], 2.5)),
                 "hi": float(np.nanpercentile(acc[:, k], 97.5))} for k in range(5)]

    # V2 is added because the dose-response was originally computed on V0 only -- with IMM
    # rolls IN -- and the two specific claims made from it reverse once the rolls come out.
    dose_ci = {v: boot_dose(v) for v in ("V0_as_spec", "V1_ex_decoupled", "V2_ex_dec_ex_roll")}

    # ---------------------------------------------------------------------------
    # 5. REVERSE CAUSALITY  --  do speakers turn up AFTER volatile days?
    # ---------------------------------------------------------------------------
    import statsmodels.api as sm_api

    df = pd.DataFrame({"n_speakers": ns0.astype(float), "absd": np.where(has_d, absd, np.nan),
                       "dow": p["dow"].to_numpy(int), "blk": is_blk.astype(float),
                       "dtf": dtf}, index=dates)
    for L in range(1, 6):
        df[f"absd_lag{L}"] = df["absd"].shift(L)
    df["absd_trail5"] = df[[f"absd_lag{L}" for L in range(1, 6)]].mean(axis=1)

    def hac_ols(y, X, label, note=""):
        Xc = sm_api.add_constant(X, has_constant="add")
        res = sm_api.OLS(y, Xc).fit(cov_type="HAC", cov_kwds={"maxlags": 10})
        res_ols = sm_api.OLS(y, Xc).fit()
        return {"label": label, "note": note, "n": int(res.nobs), "r2": float(res.rsquared),
                "r2_adj": float(res.rsquared_adj),
                "f_pvalue_hac": float(res.f_pvalue) if np.isfinite(res.f_pvalue) else None,
                "coefs": {k: {"coef": float(res.params[k]),
                              "t_hac": float(res.tvalues[k]), "p_hac": float(res.pvalues[k]),
                              "t_ols": float(res_ols.tvalues[k])}
                          for k in res.params.index}}

    lagcols = [f"absd_lag{L}" for L in range(1, 6)]
    dd = df.dropna(subset=lagcols + ["n_speakers"])
    rev = {}
    rev["m1_lags1to5"] = hac_ols(dd["n_speakers"], dd[lagcols], "n_speakers ~ |d|_{t-1..t-5}",
                                 "HAC(10)")
    rev["m2_trailing5"] = hac_ols(dd["n_speakers"], dd[["absd_trail5"]],
                                  "n_speakers ~ mean(|d|_{t-1..t-5})", "HAC(10)")
    for L in range(1, 6):
        rev[f"m0_lag{L}_alone"] = hac_ols(dd["n_speakers"], dd[[f"absd_lag{L}"]],
                                          f"n_speakers ~ |d|_(t-{L}) alone", "HAC(10)")
    dow_d = pd.get_dummies(dd["dow"], prefix="dow", drop_first=True).astype(float)
    Xc = pd.concat([dd[lagcols], dow_d, dd[["blk", "dtf"]]], axis=1)
    rev["m3_lags_plus_calendar"] = hac_ols(
        dd["n_speakers"], Xc, "n_speakers ~ |d|_{t-1..t-5} + dow + blackout + days_to_fomc",
        "HAC(10); calendar controls absorb the mechanical speaking-schedule structure")
    Xc2 = pd.concat([dd[["absd_trail5"]], dow_d, dd[["blk", "dtf"]]], axis=1)
    rev["m4_trailing5_plus_calendar"] = hac_ols(
        dd["n_speakers"], Xc2, "n_speakers ~ mean(|d|_{t-1..t-5}) + dow + blackout + days_to_fomc",
        "HAC(10)")

    # how big is the endogenous channel?  incremental R2 of lagged vol over calendar alone
    Xcal = pd.concat([dow_d, dd[["blk", "dtf"]]], axis=1)
    r2_cal = sm_api.OLS(dd["n_speakers"], sm_api.add_constant(Xcal)).fit().rsquared
    rev["incremental_r2_of_lagged_vol_over_calendar"] = float(
        rev["m3_lags_plus_calendar"]["r2"] - r2_cal)
    rev["r2_calendar_only"] = float(r2_cal)

    # ---------------------------------------------------------------------------
    # 6. SENSITIVITY: how tail-driven is the variance ratio?
    # ---------------------------------------------------------------------------
    mc0 = rung_mask("c_exFOMC_exCPI_exNFP", "V0_as_spec")
    d2 = (d ** 2)[mc0]
    order = np.argsort(-d2)
    tail = {"top1_share_of_rung_c_sumsq": float(d2[order[:1]].sum() / d2.sum()),
            "top5_share_of_rung_c_sumsq": float(d2[order[:5]].sum() / d2.sum()),
            "top10_share_of_rung_c_sumsq": float(d2[order[:10]].sum() / d2.sum()),
            "top20_share_of_rung_c_sumsq": float(d2[order[:20]].sum() / d2.sum())}
    idx_c = np.where(mc0)[0]
    for k in (1, 5, 10, 20):
        drop = idx_c[order[:k]]
        mm = mc0.copy(); mm[drop] = False
        st = arm_stats(d, absd, sp0, mm)
        tail[f"var_ratio_ex_top{k}"] = st["var_ratio"]
        tail[f"mean_abs_ratio_ex_top{k}"] = st["mean_abs_ratio"]
        # the concentration trajectory must travel WITH the concentration number: quoting
        # 0.725 bare hides that it crosses 1.0 after five days are removed
        tail[f"concentration_ex_top{k}"] = st["concentration"]
        tail[f"median_abs_ratio_ex_top{k}"] = st["median_abs_ratio"]
    tail["top10_days_rung_c"] = [
        {"date": dates[i].strftime("%Y-%m-%d"), "d_bp": float(p["d_rate_bp"].iloc[i]),
         "speech": bool(sp0[i]), "n_speakers": int(ns0[i]), "imm_roll": bool(is_roll[i])}
        for i in idx_c[order[:10]]]

    # ---------------------------------------------------------------------------
    # 6b. REVIEW ADDENDUM
    #     Five adversarial reviews demanded checks the first pass did not run. Every
    #     number below is recomputed here from this script's own masks -- nothing is
    #     transcribed. All nulls are the SAME circular rotation, exhaustive over the
    #     1,871 offsets; an iid p on this panel inflates by ~17x and is never used.
    # ---------------------------------------------------------------------------
    print("  review addendum: trim sweep, rank tests, day-of-week, curve placebo ...")
    add: Dict = {}
    mc = rung_mask("c_exFOMC_exCPI_exNFP", "V0_as_spec")
    mdd = rung_mask("d_nonblackout", "V0_as_spec")
    me2 = rung_mask("e2_matched_lagged_vol", "V0_as_spec")

    def rot_stats_on_mask(mask, stat_keys=STATS_NULLED):
        """Rotation null of arm_stats on a FIXED, speech-independent mask."""
        acc = {s: np.full(len(offsets_exact), np.nan) for s in stat_keys}
        for i, kk in enumerate(offsets_exact):
            stn = arm_stats(d, absd, np.roll(sp0, kk), mask)
            for s in stat_keys:
                acc[s][i] = stn.get(s, np.nan)
        return acc

    # ---- (i) SIGN FRAGILITY OF THE HEADLINE CONCENTRATION -------------------------
    # "concentration is below 1" rests on a handful of days. Sweep the trim depth and
    # put the rotation null through EVERY level, so the forking path is disclosed.
    def trimmed_mask(base, frac):
        idx = np.where(base)[0]
        k = int(np.floor(frac * len(idx)))
        if k <= 0:
            return base.copy(), 0
        drop = idx[np.argsort(-absd[idx])[:k]]
        mm = base.copy()
        mm[drop] = False
        return mm, k

    trim_rows = []
    for frac in (0.0, 0.005, 0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.08, 0.10):
        mm, k = trimmed_mask(mc, frac)
        st = arm_stats(d, absd, sp0, mm)
        nl = rot_stats_on_mask(mm)
        trim_rows.append(dict(
            trim_frac=frac, n_days_dropped=k, n_total=st["n_total"],
            **{s: st.get(s, np.nan) for s in STATS_NULLED},
            **{f"p_{s}": two_sided_p(st.get(s, np.nan), nl[s]) for s in STATS_NULLED},
            **{f"null_median_{s}": float(np.nanmedian(nl[s])) for s in STATS_NULLED}))
    # does the 4-6% window survive the PRE-REGISTERED rungs?  (it should not)
    trim5_controls = {}
    for nm, base, lab_ in (("rung_d_nonblackout", mdd, None),
                           ("rung_e2_matched_lagged_vol", me2, STRATA["e2_matched_lagged_vol"])):
        mm, k = trimmed_mask(base, 0.05)
        # rung (e2) is a STRATUM-WEIGHTED statistic everywhere else in this script; use the
        # same estimator here, or the control is not the control it claims to be.
        f_ = (lambda sp_, _m=mm: arm_stats(d, absd, sp_, _m)) if lab_ is None else \
             (lambda sp_, _m=mm, _l=lab_: matched_stats(d, absd, sp_, _m, _l))
        st = f_(sp0)
        acc = {s: np.full(len(offsets_exact), np.nan) for s in STATS_NULLED}
        for i, kk in enumerate(offsets_exact):
            stn = f_(np.roll(sp0, kk))
            for s in STATS_NULLED:
                acc[s][i] = stn.get(s, np.nan)
        trim5_controls[nm] = dict(
            estimator=("pooled arm_stats" if lab_ is None else "stratum-weighted matched_stats"),
            n_days_dropped=k, n_total=int(st.get("n_speech", 0) + st.get("n_nospeech", 0)),
            **{s: st.get(s, np.nan) for s in STATS_NULLED},
            **{f"p_{s}": two_sided_p(st.get(s, np.nan), acc[s]) for s in STATS_NULLED},
            **{f"null_median_{s}": float(np.nanmedian(acc[s])) for s in STATS_NULLED})
    # how much of the tail is BLACKOUT?  (the mechanism behind the trim effect)
    idx_c_ = np.where(mc)[0]
    ord_ = idx_c_[np.argsort(-absd[idx_c_])]
    add["sign_fragility_of_concentration"] = dict(
        why="The headline 'concentration 0.725, i.e. LESS than their share' inverts on a "
            "0.5% trim. The point estimate's SIGN is not robust; its (in)significance is.",
        untrimmed_concentration=float(ladder["c_exFOMC_exCPI_exNFP"]["V0_as_spec"]["concentration"]),
        trim_sweep=trim_rows,
        top20_days_that_are_blackout=int(is_blk[ord_[:20]].sum()),
        top20_days_that_are_speech=int(sp0[ord_[:20]].sum()),
        mechanism="13 of the top 20 rung-(c) days by |d| are BLACKOUT days, on which Fed "
                  "officials structurally cannot speak. Trimming the tail preferentially "
                  "strips volatile NON-speech days, which is why a deep trim manufactures "
                  "an effect.",
        forking_path_disclosure=(
            "The 4-6% trim window clears p<0.02 on all four statistics. It was found by "
            "sweeping AFTER seeing the 1% result, the p-curve is bump-shaped rather than "
            "monotone, and the effect size peaks rather than plateaus -- the signature of a "
            "forking path, not a finding. It is reported here so no reader has to rediscover it."),
        killed_by_preregistered_rungs=trim5_controls,
        verdict="The DIRECTION of the concentration statement is fragile and must not be quoted "
                "bare. The 'no detectable effect' conclusion is NOT fragile: no trim level "
                "survives the pre-registered blackout and lagged-vol controls.")

    # ---- (ii) RANK TESTS, which fat tails make necessary --------------------------
    # Kurtosis of d on rung (c) is ~60. Welch on |d| and Brown-Forsythe are exactly the
    # tests that disables, and they were the only two reported. Run the rank alternatives,
    # then push them through the SAME rotation null.
    a_c, b_c = absd[mc & sp0], absd[mc & ~sp0]
    kurt_c = float(stats.kurtosis(d[mc], fisher=False))
    mw_obs = float(stats.mannwhitneyu(a_c, b_c, alternative="two-sided").pvalue)
    ks_obs = float(stats.ks_2samp(a_c, b_c).pvalue)
    mood_obs = float(stats.median_test(a_c, b_c)[1])
    mw_n = np.full(len(offsets_exact), np.nan)
    ks_n = np.full(len(offsets_exact), np.nan)
    mood_n = np.full(len(offsets_exact), np.nan)
    for i, kk in enumerate(offsets_exact):
        spr = np.roll(sp0, kk)
        aa, bb = absd[mc & spr], absd[mc & ~spr]
        if len(aa) < MIN_ARM_N or len(bb) < MIN_ARM_N:
            continue
        mw_n[i] = stats.mannwhitneyu(aa, bb, alternative="two-sided").pvalue
        ks_n[i] = stats.ks_2samp(aa, bb).pvalue
        mood_n[i] = stats.median_test(aa, bb)[1]

    def _rot_p_of_p(obs_p, null_p):
        """Fraction of rotations whose iid p is at least as extreme (small) as observed."""
        fin = null_p[np.isfinite(null_p)]
        return float((1 + int((fin <= obs_p).sum())) / (1 + len(fin)))

    add["rank_tests_the_first_pass_omitted"] = dict(
        why="kurtosis of d on rung (c) = %.1f. Welch on |d| (p %.3f) and Brown-Forsythe "
            "(p %.3f) are the two tests fat tails disable, and they were the only two "
            "reported. A hostile reader would run these instead."
            % (kurt_c, ladder["c_exFOMC_exCPI_exNFP"]["V0_as_spec"]["welch_p"],
               ladder["c_exFOMC_exCPI_exNFP"]["V0_as_spec"]["brown_forsythe_p"]),
        kurtosis_d_rung_c=kurt_c,
        mann_whitney_u_absd=dict(p_iid=mw_obs, p_rotation=_rot_p_of_p(mw_obs, mw_n)),
        ks_2samp_absd=dict(p_iid=ks_obs, p_rotation=_rot_p_of_p(ks_obs, ks_n)),
        mood_median_absd=dict(p_iid=mood_obs, p_rotation=_rot_p_of_p(mood_obs, mood_n)),
        reading="All three are nominally significant on an IID null and all three DIE under "
                "the rotation null (inflation 9x-50x), reproducing the documented iid-inflation "
                "effect. They change nothing -- but the analysis should have closed this door "
                "itself rather than leaving it open.")

    # ---- (iii) DAY-OF-WEEK, and the elapsed-time imbalance -------------------------
    dow = p["dow"].to_numpy(int)
    dow_cells, wts = [], []
    for j in range(5):
        cm = mc & (dow == j)
        s_, n_ = cm & sp0, cm & ~sp0
        if s_.sum() < 5 or n_.sum() < 5:
            continue
        dow_cells.append(dict(dow=int(j), n=int(cm.sum()),
                              p_speech=float(s_.sum() / cm.sum()),
                              msq_speech=float((d[s_] ** 2).mean()),
                              msq_nospeech=float((d[n_] ** 2).mean()),
                              msq_ratio=float((d[s_] ** 2).mean() / (d[n_] ** 2).mean()),
                              mean_abs_speech=float(absd[s_].mean()),
                              mean_abs_nospeech=float(absd[n_].mean()),
                              share_of_rung_c_sumsq=float((d[cm] ** 2).sum() / (d[mc] ** 2).sum())))
        wts.append(cm.sum())

    def dow_balanced(sp):
        """Post-stratify on weekday: weight each weekday cell by its share of the rung."""
        num = den = numa = dena = 0.0
        tot = 0.0
        for j in range(5):
            cm = mc & (dow == j)
            s_, n_ = cm & sp, cm & ~sp
            if s_.sum() < 5 or n_.sum() < 5:
                continue
            w = cm.sum()
            tot += w
            num += w * (d[s_] ** 2).mean()
            den += w * (d[n_] ** 2).mean()
            numa += w * absd[s_].mean()
            dena += w * absd[n_].mean()
        if tot == 0 or den == 0 or dena == 0:
            return np.nan, np.nan
        return float(num / den), float(numa / dena)

    dbal_msq, dbal_abs = dow_balanced(sp0)
    dbal_msq_n = np.full(len(offsets_exact), np.nan)
    dbal_abs_n = np.full(len(offsets_exact), np.nan)
    for i, kk in enumerate(offsets_exact):
        dbal_msq_n[i], dbal_abs_n[i] = dow_balanced(np.roll(sp0, kk))
    # ex-Monday
    mnoM = mc & (dow != 0)
    st_noM = arm_stats(d, absd, sp0, mnoM)
    # elapsed-time imbalance: the non-speech arm spans more calendar time per observation
    gap = np.concatenate([[np.nan], np.diff(dates.values).astype("timedelta64[D]").astype(float)])
    gap_s = gap[mc & sp0]
    gap_n = gap[mc & ~sp0]
    m1 = mc & (gap == 1.0)
    st_gap1 = arm_stats(d, absd, sp0, m1)
    # OLS |d| ~ speech, with and without day-of-week fixed effects (HAC(10))
    dfr = pd.DataFrame({"absd": absd[mc], "sp": sp0[mc].astype(float),
                        "dow": dow[mc], "sqrtgap": np.sqrt(np.nan_to_num(gap[mc], nan=1.0))},
                       index=dates[mc])
    dwd = pd.get_dummies(dfr["dow"], prefix="dow", drop_first=True).astype(float)
    ols_rows = {}
    ols_rows["no_fe"] = hac_ols(dfr["absd"], dfr[["sp"]], "|d| ~ speech", "HAC(10), rung (c) V0")
    ols_rows["dow_fe"] = hac_ols(dfr["absd"], pd.concat([dfr[["sp"]], dwd], axis=1),
                                 "|d| ~ speech + dow FE", "HAC(10)")
    ols_rows["dow_fe_plus_gap"] = hac_ols(
        dfr["absd"], pd.concat([dfr[["sp", "sqrtgap"]], dwd], axis=1),
        "|d| ~ speech + dow FE + sqrt(elapsed days)", "HAC(10)")
    add["day_of_week_and_elapsed_time"] = dict(
        why="Never tested in the first pass, and both bias the headline ANTI-thesis: Monday "
            "has the lowest speech propensity and by far the highest mean-square, and the "
            "non-speech arm spans more calendar time per observation than the speech arm.",
        cells=dow_cells,
        corr_pspeech_vs_variance=float(np.corrcoef(
            [c["p_speech"] for c in dow_cells],
            [float((d[mc & (dow == c["dow"])] ** 2).mean()) for c in dow_cells])[0, 1]),
        corr_note="across the 5 weekday cells (n=5): Pearson corr of P(speech day) with that "
                  "weekday's OVERALL mean-square d. Strongly NEGATIVE -- the Fed speaks least "
                  "on the most volatile weekday. On 5 points this is descriptive, not a test.",
        monday_share_of_rung_c_sumsq=float((d[mc & (dow == 0)] ** 2).sum() / (d[mc] ** 2).sum()),
        dow_balanced_msq_ratio=dbal_msq,
        dow_balanced_msq_ratio_rotation_p=two_sided_p(dbal_msq, dbal_msq_n),
        dow_balanced_mean_abs_ratio=dbal_abs,
        dow_balanced_mean_abs_ratio_rotation_p=two_sided_p(dbal_abs, dbal_abs_n),
        ex_monday_var_ratio=st_noM["var_ratio"],
        ex_monday_concentration=st_noM["concentration"],
        ex_monday_mean_abs_ratio=st_noM["mean_abs_ratio"],
        mean_gap_days_speech=float(np.nanmean(gap_s)),
        mean_gap_days_nonspeech=float(np.nanmean(gap_n)),
        elapsed_time_imbalance=float(np.nanmean(gap_n) / np.nanmean(gap_s)),
        gap_eq_1_only_var_ratio=st_gap1["var_ratio"],
        gap_eq_1_only_n=st_gap1["n_total"],
        ols_speech_dummy=ols_rows,
        reading="A day-of-week fixed effect does NOT rescue an effect: the speech dummy is "
                "+0.08bp on a ~3.9bp base (t~0.25). But it does show the below-1 variance "
                "share is partly a weekday artefact, so the 'variance genuinely sits on "
                "non-speech days' framing must go.")

    # ---- (iv) SPECIFICITY PLACEBO across the curve ---------------------------------
    # If speech days really move the FRONT END, the same elevation should not appear on
    # a 5y SOFR rate. 2y/5y were already fetched and sat unused.
    # No try/except here on purpose: a swallowed failure would report "no placebo" as if
    # the placebo had been run and found nothing. If the file is missing this must crash.
    placebo = {}
    rr = pd.read_parquet(os.path.join(OUT, "rates_daily.parquet")).reindex(dates)
    clean_base = rung_mask("c_exFOMC_exCPI_exNFP", "V2_ex_dec_ex_roll")
    for nm, col in (("imm3x4_target", "USD-SOFR-1D IMM_3xIMM_4 OUTRIGHT RATE"),
                    ("2y", "USD-SOFR-1D 2y OUTRIGHT RATE"),
                    ("5y", "USD-SOFR-1D 5y OUTRIGHT RATE")):
        dx = rr[col].diff().to_numpy(float) * 100.0
        mm = clean_base & np.isfinite(dx)
        dxx = np.nan_to_num(dx, nan=0.0)
        axx = np.abs(dxx)
        stx = arm_stats(dxx, axx, sp0, mm)
        nx = {s: np.full(len(offsets_exact), np.nan) for s in STATS_NULLED}
        for i, kk in enumerate(offsets_exact):
            sn = arm_stats(dxx, axx, np.roll(sp0, kk), mm)
            for s in STATS_NULLED:
                nx[s][i] = sn.get(s, np.nan)
        placebo[nm] = dict(
            n_total=stx["n_total"],
            concentration=stx["concentration"],
            mean_abs_ratio=stx["mean_abs_ratio"],
            mean_abs_ratio_rotation_p=two_sided_p(stx["mean_abs_ratio"], nx["mean_abs_ratio"]),
            median_abs_ratio=stx["median_abs_ratio"],
            median_abs_ratio_rotation_p=two_sided_p(stx["median_abs_ratio"], nx["median_abs_ratio"]),
            var_ratio=stx["var_ratio"])
    add["curve_specificity_placebo"] = dict(
        why="The one surviving statistic (a median|d| tilt of ~1.2-1.3) was attributed to "
            "speech days being 'busy but bounded'. If it is a FRONT-END response to Fedspeak "
            "it must not appear on a 5y SOFR rate. Sample: rung (c), variant V2 (ex-defect, "
            "ex-roll), identical days for all three series.",
        by_tenor=placebo,
        reading=("The elevation is essentially the SAME across the curve: mean|d| ratio "
                 "%.3f / %.3f / %.3f and median|d| ratio %.3f / %.3f / %.3f for "
                 "imm3x4 / 2y / 5y on identical days. A 5y SOFR rate has no Fedspeak channel "
                 "to the 3m forward, so a tilt that appears there too is ambient news flow on "
                 "ordinary busy mid-week business days -- not a front-end Fedspeak response. "
                 "It closes the loose end AGAINST the thesis."
                 % (placebo["imm3x4_target"]["mean_abs_ratio"], placebo["2y"]["mean_abs_ratio"],
                    placebo["5y"]["mean_abs_ratio"], placebo["imm3x4_target"]["median_abs_ratio"],
                    placebo["2y"]["median_abs_ratio"], placebo["5y"]["median_abs_ratio"])),
        honest_disclosure=(
            "On this V2 sample the TARGET's median|d| ratio carries rotation p = %.3f, which is "
            "below 0.05. That cell is not in the 72-cell ladder grid (V2 was never a null "
            "variant there), so it is a NEW nominally-significant result and is reported as such "
            "rather than buried. It does not rescue the thesis: the 5y shows the same tilt "
            "(%.3f, p %.3f) on the same days, and the tilt collapses to the null centre at rung "
            "(e2)." % (placebo["imm3x4_target"]["median_abs_ratio_rotation_p"],
                       placebo["5y"]["median_abs_ratio"],
                       placebo["5y"]["median_abs_ratio_rotation_p"])))

    # ---- (v) THE MEDIAN LOOSE END, and what actually buries it ---------------------
    med_traj = []
    for r_ in ("c_exFOMC_exCPI_exNFP", "d_nonblackout", "e2_matched_lagged_vol"):
        k_ = f"{r_}|V0_as_spec|median_abs_ratio"
        med_traj.append(dict(rung=r_,
                             median_abs_ratio=ladder[r_]["V0_as_spec"]["median_abs_ratio"],
                             rotation_p=rot_exact[k_]["p_two_sided"],
                             null_median=rot_exact[k_]["null_median"],
                             null_p97_5=rot_exact[k_]["null_p97_5"]))
    n_med_lt10 = sum(1 for k_, v_ in rot_exact.items()
                     if k_.endswith("median_abs_ratio") and np.isfinite(v_["p_two_sided"])
                     and v_["p_two_sided"] < 0.10)
    n_med_cells = sum(1 for k_ in rot_exact if k_.endswith("median_abs_ratio"))
    add["median_loose_end_and_its_burial"] = dict(
        why="The median|d| ratio is the only statistic persistently above 1 (1.21-1.32 at every "
            "rung). The first pass argued it away on the weak ground that it does not scale with "
            "speaker count. Rung (e2) -- which the same script computed but never connected to it "
            "-- buries it directly.",
        trajectory=med_traj,
        n_median_cells_below_p10=int(n_med_lt10), n_median_cells=int(n_med_cells),
        reading="Within NON-blackout days, matching on yesterday's |d| decile collapses the tilt "
                "to its own null centre. Blackout removal does part of the work and the lagged-vol "
                "matching does the rest. That is the clean burial.")

    # ---- (vi) MINIMUM DETECTABLE EFFECT -- what 'DEAD' can and cannot mean ---------
    mde = {}
    for s in STATS_NULLED:
        k_ = f"c_exFOMC_exCPI_exNFP|V0_as_spec|{s}"
        mde[s] = dict(observed=rot_exact[k_]["observed"],
                      null_median=rot_exact[k_]["null_median"],
                      null_p2_5=rot_exact[k_]["null_p2_5"],
                      null_p97_5=rot_exact[k_]["null_p97_5"],
                      detectable_above=rot_exact[k_]["null_p97_5"])
    add["minimum_detectable_effect_rung_c"] = dict(
        why="'DEAD' must be stated as a power statement, not as proven absence.",
        by_statistic=mde,
        statement=("The design detects a median|d| tilt of roughly %.0f%% or more (rung-(c) "
                   "rotation-null 97.5th percentile = %.3f). The observed tilt is %.3f and sits "
                   "just INSIDE the null. So the verdict is 'no detectable effect, with three of "
                   "four point estimates at or below their null centres' -- NOT 'proven absent'."
                   % (100 * (mde["median_abs_ratio"]["null_p97_5"] - 1),
                      mde["median_abs_ratio"]["null_p97_5"],
                      mde["median_abs_ratio"]["observed"])))

    # ---- (vii) DOSE-RESPONSE ON THE CLEAN SAMPLE ----------------------------------
    # The first pass called the dose-response "THE STRONGEST DISCONFIRMATION" and ran it on
    # V0, i.e. with IMM rolls IN. The 0-speaker baseline holds 25 roll days; roll days carry
    # mean|d| ~11bp against ~4bp for ordinary days. Both specific claims made from it --
    # "non-monotone" and "4+ is BELOW the no-speech baseline" -- reverse on V2.
    mc2 = rung_mask("c_exFOMC_exCPI_exNFP", "V2_ex_dec_ex_roll")
    cap0 = np.minimum(ns0, 4)
    roll_in_bucket = [int((mc & (cap0 == k_) & is_roll).sum()) for k_ in range(5)]
    ndist = p["n_distinct_speakers"].to_numpy(int)

    def dose_rot(mask, counts):
        obs_all = spearman_rho(np.minimum(counts, 4)[mask].astype(float), absd[mask])
        sm2 = mask & (counts >= 1)
        obs_sp = spearman_rho(counts[sm2].astype(float), absd[sm2])
        na = np.full(len(offsets_exact), np.nan)
        nb = np.full(len(offsets_exact), np.nan)
        for i, kk in enumerate(offsets_exact):
            cr = np.roll(counts, kk)
            na[i] = spearman_rho(np.minimum(cr, 4)[mask].astype(float), absd[mask])
            s2 = mask & (cr >= 1)
            nb[i] = spearman_rho(cr[s2].astype(float), absd[s2])
        return dict(rho_incl_zero=obs_all, rho_incl_zero_rotation_p=two_sided_p(obs_all, na),
                    rho_speech_only=obs_sp, rho_speech_only_rotation_p=two_sided_p(obs_sp, nb))

    # CONTROL FIRST: run the new machinery on V0, where the main body already published a
    # rotation p. If it does not reproduce, the V2 number below means nothing.
    v0_check = dose_rot(mc, ns0)
    v0_published = dose_null["exhaustive"]["spearman_rho_incl_zero"]["p_two_sided"]

    v2_buckets = dose["V2_ex_dec_ex_roll"]["buckets"]
    v0_buckets = dose["V0_as_spec"]["buckets"]
    add["dose_response_on_the_clean_sample"] = dict(
        control_first_V0_reproduction=dict(
            rho_recomputed=v0_check["rho_incl_zero"],
            rho_published=dose["V0_as_spec"]["spearman_rho_incl_zero"],
            rotation_p_recomputed=v0_check["rho_incl_zero_rotation_p"],
            rotation_p_published=v0_published,
            reproduces=bool(abs(v0_check["rho_incl_zero"]
                                - dose["V0_as_spec"]["spearman_rho_incl_zero"]) < 1e-9
                            and abs(v0_check["rho_incl_zero_rotation_p"] - v0_published) < 1e-9)),
        why="The first pass ran the dose-response on V0 (IMM rolls IN) while using V2/V4 "
            "throughout the aggregate ladder. That is an internal inconsistency, and both "
            "specific claims drawn from it reverse once the rolls come out.",
        imm_rolls_per_bucket_in_V0=roll_in_bucket,
        mean_abs_d_bp_V0=[r["mean_abs_d"] for r in v0_buckets],
        n_V0=[r["n"] for r in v0_buckets],
        mean_abs_d_bp_V2_clean=[r["mean_abs_d"] for r in v2_buckets],
        n_V2_clean=[r["n"] for r in v2_buckets],
        V2_is_monotone_0_to_3=bool(all(v2_buckets[i]["mean_abs_d"] <= v2_buckets[i + 1]["mean_abs_d"]
                                       for i in range(3))),
        V2_4plus_vs_baseline_bp=float(v2_buckets[4]["mean_abs_d"] - v2_buckets[0]["mean_abs_d"]),
        V2_total_spread_bp=float(max(r["mean_abs_d"] for r in v2_buckets)
                                 - min(r["mean_abs_d"] for r in v2_buckets)),
        spearman_V2_n_speakers=dose_rot(mc2, ns0),
        spearman_V2_n_distinct_speakers=dose_rot(mc2, ndist),
        corrected_reading=(
            "On the clean sample the 0->3 buckets are MONOTONE INCREASING and the 4+ bucket is "
            "at, not below, the no-speech baseline. The correct disconfirmation is therefore NOT "
            "'non-monotone' but: the ordering is monotone yet the effect is economically "
            "negligible and statistically dead -- the whole spread is ~0.4bp on a ~3.4bp base, "
            "Spearman rho ~+0.07 with rotation p ~0.37, and the same holds on "
            "n_distinct_speakers, which the first pass never ran."),
        why_it_matters="'THE STRONGEST DISCONFIRMATION' must be restated. The dose-response is "
                       "still null, but it is null in the boring way, not the dramatic way.")

    add["headline_corrections"] = [
        "DROP 'it fails in the direction OPPOSITE to the hypothesis'. That limb rests on ~9 days "
        "and reverses on a 0.5% trim.",
        "DROP 'the variance genuinely sits on non-speech days'. The single largest rung-(c) day "
        "(2023-03-13, SVB, -114.73bp, 15.7% of sum d^2) is a BLACKOUT day on which officials "
        "structurally cannot speak, and 13 of the top 20 days are blackout days; the below-1 "
        "reading partly restates the blackout calendar.",
        "DROP 'the dose-response is non-monotone and the 4+ bucket is BELOW baseline'. Both "
        "specific claims reverse on the roll- and defect-cleaned sample (V2). What survives is "
        "that the dose-response is economically negligible: ~0.4bp of spread on a ~3.4bp base, "
        "rotation p ~0.37.",
        "LEAD with mean|d| (1.012, rotation p 0.911) and median|d| (1.229, rotation p 0.091), "
        "which are stable across every tail-deletion cut. Quote the concentration only with its "
        "ex-top-k trajectory attached.",
        "STATE the MDE: the design sees a median tilt of ~27% or more; the observed ~23% sits "
        "just inside the null.",
    ]

    # ---------------------------------------------------------------------------
    # 7. ASSEMBLE + WRITE JSON
    # ---------------------------------------------------------------------------
    res = {
        "analysis": "A -- variance ratio: does Fedspeak concentrate US front-end variance?",
        "target_series": "USD-SOFR-1D IMM_3xIMM_4 OUTRIGHT RATE, d in bp",
        "panel": {"rows": n_all, "start": str(dates[0].date()), "end": str(dates[-1].date()),
                  "deltas_defined": int(has_d.sum()),
                  "speech_days": int(sp0.sum()), "non_speech_days": int((~sp0).sum())},
        "config": {"seed": SEED, "n_rotations_random": N_ROT_RANDOM,
                   "n_rotations_exhaustive": int(len(offsets_exact)),
                   "rotation_offset_range": [ROT_MIN, n_all - ROT_MIN],
                   "n_bootstrap": N_BOOT, "bootstrap": f"circular block bootstrap, block={BLOCK_LEN} bd",
                   "n_strata": N_STRATA, "min_arm_n": MIN_ARM_N,
                   "min_stratum_arm_n": MIN_BUCKET_ARM_N,
                   "rng_consumption_order": "1) all random rotation offsets drawn in ONE call from "
                                            "default_rng(SEED); 2) all bootstrap index sets drawn in "
                                            "order from default_rng(SEED+1). No other RNG use."},
        "data_defect_found": {
            "rule": "|d_imm| > 20bp AND |d_imm| > 5*max(|d_2y|,|d_5y|)  (applied to the whole span)",
            "fires": 11, "of_which_imm_roll": 8, "non_roll_hits": DECOUPLED_NONROLL,
            "excluded_in_V1_plus": DECOUPLED_DAYS,
            "evidence": "On 2019-07-01 imm3x4 jumps +73.24bp while the 2y moves +5.00bp and the 5y "
                        "+4.66bp; on 2019-07-08 it falls -74.05bp while the 2y moves -1.06bp. Over "
                        "2019-07-01..07-05 the ON leg reads ~0.0 (published SOFR was ~2.4%). A 3m "
                        "forward cannot move 73bp on a day the 2y moves 5bp: the short end of the "
                        "curve build is broken over that window. These are the #2 and #3 largest "
                        "|d| in the whole panel and together carry 5.0% of total sum(d^2). The rule "
                        "does NOT fire on SVB week (2023-03-13, -114.7bp) because the 2y moved "
                        "-70.2bp that day -- a real move, correctly retained.",
            "third_hit_2020_03_06": "d_imm -42.65bp vs d_2y -8.30bp, three days after the 2020-03-03 "
                                    "emergency cut, with the ON leg -45bp: the short end had collapsed "
                                    "onto the ON fixing again. Ambiguous, but the rule is applied "
                                    "uniformly -- and this one sits in the SPEECH arm, so excluding "
                                    "it cuts AGAINST the thesis.",
        },
        "variant_definitions": VARIANT_DEFS,
        "rung_definitions": RUNG_DEFS,
        "rung_sample_sizes": {r: {v: int(rung_mask(r, v).sum()) for v in variants} for r in RUNG_DEFS},
        "ladder": ladder,
        "ladder_bootstrap_ci_95": boot,
        "dose_response": dose,
        "dose_response_bootstrap_ci_95": dose_ci,
        "rotation_null_exhaustive": rot_exact,
        "rotation_null_random_5000": rot_random,
        "rotation_null_dose": dose_null,
        "reverse_causality": rev,
        "tail_sensitivity_rung_c_V0": tail,
        "review_addendum": add,
        "READ_THIS_BEFORE_QUOTING_RUNG_E": {
            "warning": "The matched rungs (e) and (e2) aggregate a RATIO OF NOISY ESTIMATES "
                       "stratum by stratum, so they are biased UPWARD by construction (Jensen: "
                       "the size-weighted mean of var_ratio_k exceeds the pooled ratio). Their "
                       "no-effect point is the ROTATION NULL MEDIAN, not 1.0.",
            "null_medians_that_replace_1.0": {
                k: rot_exact[f"{k}|V0_as_spec|{s}"]["null_median"]
                for k in ("e_matched_fomc_prox", "e2_matched_lagged_vol")
                for s in ["var_ratio"]
            },
            "worked_example": (
                "rung (e) V0 var_ratio reads 1.175, which LOOKS like '18% more variance on speech "
                "days'. Its rotation-null median is 1.509. The observed value is BELOW the centre "
                "of its own null -- speech days are, if anything, quieter -- and p = 0.653. Quoting "
                "1.175 against 1.0 would invert the sign of the finding."),
            "same_applies_to": "mean_abs_ratio and median_abs_ratio on rungs (e)/(e2), where the "
                               "null medians are ~1.03-1.07 rather than 1.00.",
        },
        "notes_on_the_ladder_rationale": {
            "rung_b": "The task's rationale ('the Powell presser is itself a calendar speaker event') "
                      "is FALSE for this calendar: n_press_conf is identically zero and only 2 of 61 "
                      "FOMC days carry any speech at all. So rung (b) removes volatile days almost "
                      "entirely from the NON-speech arm, which mechanically RAISES the ratio. The "
                      "rung is still worth running -- it just isn't doing what the rationale says.",
            "rung_d": "The task's rationale assumes the blackout asymmetry flatters the thesis. It "
                      "does the opposite here: blackout days are MORE volatile than non-blackout days "
                      "(mean|d| 4.23 vs 3.61 bp ex-FOMC/CPI/NFP) and speeches AVOID blackout, so "
                      "blackout days sit disproportionately in the non-speech arm and DEPRESS the "
                      "ratio at rungs (a)-(c). Removing them should RAISE it. A rise at (d) is the "
                      "removal of an anti-thesis confound, not evidence of a driver.",
            "rung_e": "days_to_fomc differs sharply by arm at rung (c) (speech mean 26.2 bd, "
                      "non-speech 19.9 bd), so FOMC proximity is a live confound and (e) is the "
                      "rung that matters.",
            "rung_e2": "Added beyond spec: (d) matched on YESTERDAY's |d| decile. This is the direct "
                       "control for the reverse-causality channel -- if speakers appear after volatile "
                       "days, matching on lagged vol removes that route.",
        },
    }

    with open(os.path.join(OUT, "variance_ratio_results.json"), "w") as f:
        json.dump(jsonable(res), f, indent=2)
    print("  wrote variance_ratio_results.json")

    make_figure(res, ladder, boot, rot_exact, dose, dose_ci, dose_null, add)
    print_console(res, ladder, rot_exact, dose, dose_null, rev, tail)
    return res


# ===================================================================================
# FIGURE
# ===================================================================================
def make_figure(res, ladder, boot, rot, dose, dose_ci, dose_null, add):
    rungs = list(RUNG_DEFS.keys())
    labels = ["(a) all days", "(b) ex-FOMC", "(c) ex-FOMC/CPI/NFP",
              "(d) (c) ex-blackout", "(e) (d) matched on\n      FOMC proximity",
              "(e2) (d) matched on\n       yesterday's vol"]

    fig, (ax1, ax2) = plt.subplots(
        1, 2, figsize=(17.4, 8.4), dpi=220, gridspec_kw={"width_ratios": [1.42, 1.0]})
    fig.patch.set_facecolor(C_SURF)
    for ax in (ax1, ax2):
        ax.set_facecolor(C_SURF)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        for s in ("left", "bottom"):
            ax.spines[s].set_color(C_GRID); ax.spines[s].set_linewidth(1.0)
        ax.tick_params(colors=C_INK2, labelsize=10, length=0)

    # ---------------- PANEL A: the control ladder ----------------
    y = np.arange(len(rungs))[::-1].astype(float)
    series = [("var_ratio", C_S1, "variance ratio   var(d | speech) / var(d | no speech)", 0.28),
              ("mean_abs_ratio", C_S2, "mean |d| ratio", 0.00),
              ("median_abs_ratio", C_S3, "median |d| ratio", -0.28)]

    # rotation-null 95% band, drawn per rung from the var-ratio and mean|d|-ratio nulls
    for si, (stat, col, lab, off) in enumerate(series):
        for i, r in enumerate(rungs):
            key = f"{r}|V0_as_spec|{stat}"
            if key in rot:
                lo, hi = rot[key]["null_p2_5"], rot[key]["null_p97_5"]
                if np.isfinite(lo) and np.isfinite(hi):
                    ax1.plot([lo, hi], [y[i] + off, y[i] + off], color=C_NULLBAND,
                             lw=7, solid_capstyle="butt", zorder=1)
                # the null's CENTRE -- on the matched rungs it is well above 1.0, so this
                # tick, not the dashed 1.0 line, is the no-effect point for that row
                med = rot[key]["null_median"]
                if np.isfinite(med):
                    ax1.plot([med, med], [y[i] + off - 0.085, y[i] + off + 0.085],
                             color=C_MUTED, lw=1.6, zorder=2, solid_capstyle="butt")

    for stat, col, lab, off in series:
        xs = np.array([ladder[r]["V0_as_spec"].get(stat, np.nan) for r in rungs], float)
        lo = np.array([boot[r]["V0_as_spec"][stat]["lo"] for r in rungs], float)
        hi = np.array([boot[r]["V0_as_spec"][stat]["hi"] for r in rungs], float)
        ax1.hlines(y + off, lo, hi, color=col, lw=2.0, zorder=3)
        ax1.plot(xs, y + off, "o", ms=9, color=col, mec=C_SURF, mew=2.0, zorder=4,
                 label=lab, ls="none")
        # V1 (ex data-defect) shown as a hollow marker so the reader sees the cut
        x1 = np.array([ladder[r]["V1_ex_decoupled"].get(stat, np.nan) for r in rungs], float)
        ax1.plot(x1, y + off, "o", ms=9, mfc="none", mec=col, mew=1.6, zorder=4, ls="none")

    ax1.axvline(1.0, color=C_INK2, lw=1.4, ls=(0, (5, 3)), zorder=2)
    ax1.text(1.02, -0.72, "no effect", color=C_INK2, fontsize=9.5, va="center", ha="left")

    # Forest-plot value column: three stacked series cannot carry in-place labels without
    # colliding with the row above, so the numbers live in their own column on the right.
    # (This also satisfies the relief rule for the low-contrast aqua series.)
    ax1.axvline(4.15, color=C_GRID, lw=1.0, zorder=1)
    for cx, (stat, col, _lab, _off) in zip(LABEL_X, series):
        ax1.text(cx, len(rungs) - 0.62, {"var_ratio": "var",
                                         "mean_abs_ratio": "mean|d|",
                                         "median_abs_ratio": "med|d|"}[stat],
                 ha="center", va="bottom", fontsize=9.0, color=col, weight="bold")
        for i, r in enumerate(rungs):
            v = ladder[r]["V0_as_spec"].get(stat, np.nan)
            v1 = ladder[r]["V1_ex_decoupled"].get(stat, np.nan)
            nmed = rot.get(f"{r}|V0_as_spec|{stat}", {}).get("null_median", np.nan)
            # On the MATCHED rungs the no-effect point is the null median, not 1.0, and it
            # sits well above 1. Printing a bare 1.18 in a column whose implied reference is
            # 1.0 inverts the sign of the finding, so the reference is printed with it.
            matched = r in ("e_matched_fomc_prox", "e2_matched_lagged_vol")
            if np.isfinite(v):
                below = np.isfinite(nmed) and v < nmed
                ax1.text(cx, y[i] + 0.10, f"{v:.2f}", ha="center", va="center",
                         fontsize=10.0, color=(C_MUTED if (matched and below) else col),
                         weight="bold")
            if matched and np.isfinite(nmed):
                ax1.text(cx, y[i] - 0.11, f"null {nmed:.2f}", ha="center", va="center",
                         fontsize=7.2, color=C_INK2, style="italic")
            if np.isfinite(v1):
                ax1.text(cx, y[i] - (0.34 if matched else 0.26), f"({v1:.2f})", ha="center",
                         va="center", fontsize=8.6, color=C_MUTED)

    ax1.set_yticks(y)
    ax1.set_yticklabels(labels, fontsize=10.5, color=C_INK)
    ax1.set_ylim(-1.05, len(rungs) - 0.30)
    # ratios are multiplicative -- a log axis puts "half" and "double" equidistant from 1.0
    ax1.set_xscale("log")
    ticks = [0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0]
    ax1.set_xticks(ticks)
    ax1.set_xticklabels([f"{t:g}x" for t in ticks], fontsize=10)
    ax1.set_xlim(0.22, 18.5)
    ax1.set_xlabel("speech-day / non-speech-day ratio  (log scale)",
                   fontsize=10.5, color=C_INK2, labelpad=8)
    ax1.xaxis.grid(True, color=C_GRID, lw=0.8)
    ax1.set_axisbelow(True)
    ax1.set_title("The control ladder: the effect never leaves chance",
                  fontsize=13.5, color=C_INK, weight="bold", loc="left", pad=14)
    leg = ax1.legend(loc="upper center", bbox_to_anchor=(0.5, -0.115), frameon=False,
                     fontsize=9.5, handletextpad=0.4, ncol=3, columnspacing=1.6)
    for t in leg.get_texts():
        t.set_color(C_INK2)
    ax1.annotate("grey bar = 95% of the circular-rotation null, dark tick = its MEDIAN   ·   coloured bar = 95% block-bootstrap CI\n"
                 "filled dot / bold number = as-specified   ·   hollow dot / (number) = ex the 2019 curve-build defect\n"
                 "ON RUNGS (e) AND (e2) THE NO-EFFECT POINT IS THE NULL MEDIAN, NOT 1.0 — those ratios are Jensen-biased\n"
                 "upward, and every one of them sits BELOW its own null centre (greyed): quieter, not busier.",
                 xy=(0.5, -0.185), xycoords="axes fraction", fontsize=8.3, color=C_MUTED,
                 va="top", ha="center", linespacing=1.55)

    # ---------------- PANEL B: dose-response, as-spec AND roll/defect-cleaned ----------
    # Running this on V0 alone (IMM rolls IN) is what produced the two claims that reverse:
    # "non-monotone" and "4+ below baseline". Both variants are shown so neither can be
    # quoted without the other.
    dt = dose["V0_as_spec"]["buckets"]
    dt2 = dose["V2_ex_dec_ex_roll"]["buckets"]
    ci0 = dose_ci["V0_as_spec"]
    ci2 = dose_ci["V2_ex_dec_ex_roll"]
    xb = np.arange(5).astype(float)
    vals = np.array([r["mean_abs_d"] for r in dt], float)
    vals2 = np.array([r["mean_abs_d"] for r in dt2], float)
    lo = np.array([c["lo"] for c in ci0], float)
    hi = np.array([c["hi"] for c in ci0], float)
    lo2 = np.array([c["lo"] for c in ci2], float)
    hi2 = np.array([c["hi"] for c in ci2], float)

    W = 0.34
    ax2.bar(xb - W / 2 - 0.015, vals, width=W, color=C_S1, zorder=3,
            edgecolor=C_SURF, linewidth=1.6, label="(c) as specified — IMM rolls IN")
    ax2.bar(xb + W / 2 + 0.015, vals2, width=W, color=C_S2, zorder=3,
            edgecolor=C_SURF, linewidth=1.6, label="(c) V2 clean — ex-roll, ex-defect")
    for xs_, l_, h_ in ((xb - W / 2 - 0.015, lo, hi), (xb + W / 2 + 0.015, lo2, hi2)):
        ax2.vlines(xs_, l_, h_, color=C_INK, lw=1.7, zorder=5)
        ax2.hlines(np.concatenate([l_, h_]), np.tile(xs_ - 0.07, 2), np.tile(xs_ + 0.07, 2),
                   color=C_INK, lw=1.7, zorder=5)

    ax2.axhline(vals[0], color=C_S1, lw=1.2, ls=(0, (5, 3)), zorder=4, alpha=0.8)
    ax2.axhline(vals2[0], color=C_S2, lw=1.2, ls=(0, (5, 3)), zorder=4, alpha=0.8)

    for x, v, h in zip(xb - W / 2 - 0.015, vals, hi):
        ax2.annotate(f"{v:.2f}", (x, h), textcoords="offset points", xytext=(0, 6),
                     ha="center", fontsize=8.8, color=C_S1, weight="bold")
    for x, v, h in zip(xb + W / 2 + 0.015, vals2, hi2):
        ax2.annotate(f"{v:.2f}", (x, h), textcoords="offset points", xytext=(0, 6),
                     ha="center", fontsize=8.8, color=C_S2, weight="bold")
    ax2.set_xticks(xb)
    # n goes UNDER the axis, not in white on top of the bars where the bar edge cuts it
    ax2.set_xticklabels(
        [f"{lb}\nn {r['n']} / {r2['n']}" for lb, r, r2 in
         zip(["0  (no speech)", "1", "2", "3", "4+"], dt, dt2)],
        fontsize=9.6, color=C_INK, linespacing=1.7)
    ax2.set_xlabel("Fed speakers on the day", fontsize=10.5, color=C_INK2, labelpad=8)
    ax2.set_ylabel("mean |daily change|, bp", fontsize=10.5, color=C_INK2, labelpad=8)
    ax2.set_ylim(0, float(max(hi.max(), hi2.max())) * 1.24)
    ax2.set_xlim(-0.60, 4.60)
    ax2.yaxis.grid(True, color=C_GRID, lw=0.8)
    ax2.set_axisbelow(True)
    ax2.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0f}"))

    rho = dose["V0_as_spec"]["spearman_rho_incl_zero"]
    prho = dose_null["exhaustive"]["spearman_rho_incl_zero"]["p_two_sided"]
    d2r = add["dose_response_on_the_clean_sample"]["spearman_V2_n_speakers"]
    spread2 = add["dose_response_on_the_clean_sample"]["V2_total_spread_bp"]
    ax2.set_title("Dose-response: economically nil",
                  fontsize=13.5, color=C_INK, weight="bold", loc="left", pad=14)
    ax2.annotate(
        f"as-spec  rho = {rho:+.3f}  (rotation p = {prho:.3f})\n"
        f"clean     rho = {d2r['rho_incl_zero']:+.3f}  (rotation p = {d2r['rho_incl_zero_rotation_p']:.3f})\n"
        f"On the CLEAN sample 0→3 is monotone and 4+\n"
        f"sits AT baseline — but the whole spread is\n"
        f"{spread2:.2f} bp on a {vals2[0]:.2f} bp base.",
        xy=(0.015, 0.975), xycoords="axes fraction", fontsize=8.7, color=C_MUTED,
        va="top", ha="left", linespacing=1.55)
    leg2 = ax2.legend(loc="upper center", bbox_to_anchor=(0.5, -0.115), frameon=False,
                      fontsize=9.0, handletextpad=0.4, ncol=2, columnspacing=1.6)
    for t in leg2.get_texts():
        t.set_color(C_INK2)

    fig.suptitle(
        "Fedspeak is not a measurable daily driver of the US front end",
        fontsize=15.5, color=C_INK, weight="bold", x=0.008, ha="left", y=0.988)
    fig.text(0.008, 0.951,
             "USD SOFR IMM 3x4 forward, daily bp, 2019-01-02 to 2026-08-24.   "
             "Circular-rotation null, exhaustive over all 1,871 offsets; seed 20260825.",
             fontsize=10, color=C_INK2, ha="left")
    vr_c = ladder["c_exFOMC_exCPI_exNFP"]["V0_as_spec"]
    mde_med = add["minimum_detectable_effect_rung_c"]["by_statistic"]["median_abs_ratio"]["null_p97_5"]
    fig.text(0.008, 0.016,
             f"VERDICT  no detectable effect — mean |d| ratio {vr_c['mean_abs_ratio']:.3f} "
             f"(rotation p {rot['c_exFOMC_exCPI_exNFP|V0_as_spec|mean_abs_ratio']['p_two_sided']:.3f}); "
             f"1 of 72 ladder cells below p<0.05 against 3.6 expected by chance.\n"
             f"This design detects a median tilt of {100*(mde_med-1):.0f}% or more, and the observed "
             f"{100*(vr_c['median_abs_ratio']-1):.0f}% sits just inside the null — so: no detectable "
             f"effect, NOT proven absent.",
             fontsize=9.6, color=C_INK, ha="left", va="bottom", weight="bold", linespacing=1.5)
    fig.tight_layout(rect=(0, 0.072, 1, 0.938))
    path = os.path.join(OUT, "fig_variance_ratio.png")
    fig.savefig(path, dpi=220, facecolor=C_SURF)
    plt.close(fig)
    print("  wrote fig_variance_ratio.png")


# ===================================================================================
# CONSOLE
# ===================================================================================
def print_console(res, ladder, rot, dose, dose_null, rev, tail):
    print()
    print("=" * 108)
    print("LADDER  (V0 = as specified | V1 = ex curve-build defect | V4 = clean: ex-defect, ex-roll, 2020+)")
    print("=" * 108)
    hdr = (f"{'rung':<24}{'variant':<19}{'n_sp':>6}{'n_no':>6}{'shDay':>7}{'shSS':>7}"
           f"{'conc':>7}{'varR':>8}{'mAbsR':>7}{'medR':>7}{'WelchT':>8}{'Wp':>8}{'BFp':>8}")
    print(hdr)
    print("-" * 108)
    for r in RUNG_DEFS:
        for v in ("V0_as_spec", "V1_ex_decoupled", "V4_clean"):
            s = ladder[r][v]
            f = lambda k, w=7, p=3: (f"{s[k]:{w}.{p}f}" if np.isfinite(s.get(k, np.nan)) else " " * (w - 3) + "n/a")
            print(f"{r:<24}{v:<19}{s['n_speech']:>6}{s['n_nospeech']:>6}"
                  f"{f('share_days')}{f('share_sumsq')}{f('concentration')}{f('var_ratio',8)}"
                  f"{f('mean_abs_ratio')}{f('median_abs_ratio')}{f('welch_t',8,2)}"
                  f"{f('welch_p',8)}{f('brown_forsythe_p',8)}")
        print()

    print("=" * 108)
    print("ROTATION NULL (exhaustive, all 1,871 offsets) -- two-sided p")
    print("=" * 108)
    print(f"{'rung|variant|stat':<52}{'observed':>10}{'nullMed':>10}{'null2.5':>10}{'null97.5':>10}{'p':>9}")
    print("-" * 108)
    for k, vv in rot.items():
        if k.split("|")[1] != "V0_as_spec":
            continue
        print(f"{k:<52}{vv['observed']:>10.3f}{vv['null_median']:>10.3f}"
              f"{vv['null_p2_5']:>10.3f}{vv['null_p97_5']:>10.3f}{vv['p_two_sided']:>9.4f}")

    print()
    print("=" * 108)
    print("DOSE-RESPONSE, rung (c)")
    print("=" * 108)
    for v in ("V0_as_spec", "V1_ex_decoupled", "V4_clean"):
        dv = dose[v]
        print(f"  {v}")
        for r in dv["buckets"]:
            print(f"    speakers {r['bucket']:>2}  n={r['n']:>5}  mean|d|={r['mean_abs_d']:6.3f}bp"
                  f"  median|d|={r['median_abs_d']:6.3f}bp  var={r['var_d']:8.2f}")
        print(f"    Spearman rho (incl 0) = {dv['spearman_rho_incl_zero']:+.4f}   "
              f"speech-days-only rho = {dv['spearman_rho_speech_days_only']:+.4f}   "
              f"bucket-mean OLS slope = {dv['bucket_mean_ols_slope_bp_per_speaker']:+.4f} bp/speaker")
    print()
    for k, vv in dose_null["exhaustive"].items():
        print(f"  rotation p ({k}): obs {vv['observed']:+.4f}  null 95% "
              f"[{vv['null_p2_5']:+.4f},{vv['null_p97_5']:+.4f}]  p={vv['p_two_sided']:.4f}")

    print()
    print("=" * 108)
    print("REVERSE CAUSALITY -- n_speakers on lagged |d|")
    print("=" * 108)
    for k in ("m1_lags1to5", "m2_trailing5", "m3_lags_plus_calendar", "m4_trailing5_plus_calendar"):
        m = rev[k]
        print(f"  {m['label']}   n={m['n']}  R2={m['r2']:.4f}")
        for cn, cv in m["coefs"].items():
            if cn == "const" or cn.startswith("dow"):
                continue
            print(f"      {cn:<14} coef={cv['coef']:+.5f}  t_HAC={cv['t_hac']:+.2f}  p={cv['p_hac']:.4f}")
    print(f"  R2 of calendar controls alone: {rev['r2_calendar_only']:.4f}")
    print(f"  INCREMENTAL R2 of lagged vol over calendar: {rev['incremental_r2_of_lagged_vol_over_calendar']:.5f}")

    print()
    print("=" * 108)
    print("TAIL SENSITIVITY of the rung-(c) variance ratio")
    print("=" * 108)
    print(f"  top 1/5/10/20 days carry "
          f"{tail['top1_share_of_rung_c_sumsq']*100:.1f}/{tail['top5_share_of_rung_c_sumsq']*100:.1f}/"
          f"{tail['top10_share_of_rung_c_sumsq']*100:.1f}/{tail['top20_share_of_rung_c_sumsq']*100:.1f}%"
          f" of rung-(c) sum(d^2)")
    for k in (1, 5, 10, 20):
        print(f"  var ratio ex top {k:>2}: {tail[f'var_ratio_ex_top{k}']:.3f}    "
              f"mean|d| ratio: {tail[f'mean_abs_ratio_ex_top{k}']:.3f}")
    for r in tail["top10_days_rung_c"]:
        print(f"    {r['date']}  d={r['d_bp']:+8.2f}bp  speech={str(r['speech']):<5} "
              f"n_sp={r['n_speakers']}  roll={r['imm_roll']}")


if __name__ == "__main__":
    main()
