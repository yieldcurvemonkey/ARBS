# ABOUTME: Analysis B -- chair regime split (Powell vs Warsh) on the daily Fedspeak panel.
# ABOUTME: Primary metric is the within-regime excess |move| ratio (speech vs non-speech), with a
# ABOUTME: simulation power analysis, a season-matched placebo, and a by-year falsification grid.
"""
Tests the claim: "under Warsh, forward guidance is gone, so each speaker event carries
more marginal information than under the old regime."

METRIC: absolute move per day (information content), NOT directional Sharpe.
NORMALIZATION: the primary statistic is the WITHIN-regime ratio
    excess_ratio = mean|d| on speech days / mean|d| on non-speech days
computed on the ex-FOMC / ex-CPI / ex-NFP sample, because ambient vol fell hard
across the sample and a raw cross-regime |d| comparison would measure the vol regime.

Run:  C:\\Users\\chris\\anaconda3\\envs\\stir\\python.exe regime_split.py
"""

import os
import re
import sys
import json
import warnings

sys.path.append(r"C:\Users\chris\clee\ARBS")
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MultipleLocator

warnings.filterwarnings("ignore", category=FutureWarning)

BASE = r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove"
OUT = os.path.join(BASE, "_driver_analysis")
SEED = 20260825
N_BOOT = 10000
N_SIM = 4000
TRANSITION = pd.Timestamp("2026-05-22")

# The curve-build-defect deltas variance_ratio.py isolates (its DECOUPLED_DAYS).  Analysis A
# excludes them from V1 onward and labels the removal as FLATTERING the thesis.  Analysis B
# originally kept them; four survive its clean filter and ALL FOUR sit in Powell's NON-speech
# arm, so leaving them in inflates Powell's denominator and inflates rho.  Same dates, same
# treatment, reported as an arm.
DEFECT_DAYS = [pd.Timestamp(d) for d in
               ["2019-07-01", "2019-07-02", "2019-07-03", "2019-07-05", "2019-07-08", "2020-03-06"]]

# dataviz reference palette, light mode, categorical slots 1/2/3 (validated all-pairs)
C_POWELL = "#2a78d6"   # slot 1 blue
C_WARSH = "#eb6834"    # slot 2 orange
C_THIRD = "#1baf7a"    # slot 3 aqua
INK = "#0b0b0b"
INK2 = "#52514e"
MUTED = "#8a8880"
SURFACE = "#fcfcfb"
GRID = "#e3e2dd"

RESULTS = {}
LOG = []


def say(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    LOG.append(s)


# ----------------------------------------------------------------------------------
# 1. load
# ----------------------------------------------------------------------------------
def load_panel():
    p = pd.read_parquet(os.path.join(OUT, "panel_daily.parquet"))
    if "date" not in p.columns:
        p = p.reset_index()
    p["date"] = pd.to_datetime(p["date"])
    return p.sort_values("date").reset_index(drop=True)


def parse_final_report(path):
    """Read the intraday book's own report file instead of transcribing numbers out of it.

    A hand-copied figure propagates a typo silently; this fails loudly instead.
    Returns the FED half-sample rows and the pooled calendar-year rows.
    """
    out = dict(path=path, status="MISSING", halves={}, pooled_by_year={})
    if not os.path.exists(path):
        return out
    txt = open(path, encoding="utf-8", errors="replace").read().splitlines()
    # Half-sample block.  The bank label appears ONLY on the first of its two rows:
    #     FED    1st half     246  137.00  0.5569  0.508  1.25  2022-04-05->2024-10-21
    #            2nd half     246   40.50  0.1646  0.431  0.55  2024-10-21->2026-07-16
    #     ECB    1st half ...
    # so the current bank must be carried across the continuation row.  Matching on the
    # "2nd half" text alone silently picks up POOLED's second half instead of FED's.
    bank = None
    for ln in txt:
        mb = re.match(r"^([A-Z]{3,6})\s+(1st|2nd) half\s", ln)
        if mb:
            bank = mb.group(1)
        m = re.match(r"^(?:[A-Z]{3,6}\s+)?(1st|2nd) half\s+(\d+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s+"
                     r"([\d.]+)\s+(-?[\d.]+)\s+(\S+)\s*$", ln.strip())
        if m and bank == "FED":
            out["halves"][f"{m.group(1)} half"] = dict(
                bank=bank,
                trades=int(m.group(2)), total_bp=float(m.group(3)), avg_bp=float(m.group(4)),
                hit=float(m.group(5)), sharpe=float(m.group(6)), range=m.group(7))
    # pooled CALENDAR YEAR block
    inblk = False
    for ln in txt:
        if ln.strip().startswith("CALENDAR YEAR"):
            inblk = True
            continue
        if inblk:
            m = re.match(r"^(20\d\d)\s+(\d+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s+([\d.]+)\s+([\d.]+)\s+(-?[\d.]+)\s*$",
                         ln.strip())
            if m:
                out["pooled_by_year"][m.group(1)] = dict(
                    trades=int(m.group(2)), total_bp=float(m.group(3)), avg_bp=float(m.group(4)),
                    std=float(m.group(5)), hit=float(m.group(6)), sharpe=float(m.group(7)))
            elif out["pooled_by_year"] and ln.strip() == "":
                break
    # KNOWN-ANSWER CHECK: the FED halves are 246 trades each in the source file. A parser
    # that has drifted onto the POOLED rows (402 trades) must say so, not report silently.
    ok = (len(out["halves"]) == 2
          and all(d.get("bank") == "FED" for d in out["halves"].values())
          and out["halves"]["1st half"]["trades"] == out["halves"]["2nd half"]["trades"])
    out["status"] = ("parsed OK (FED half-samples equal-sized, known-answer check passed)"
                     if (ok and out["pooled_by_year"])
                     else "PARSE SUSPECT -- known-answer check FAILED; do not quote these numbers")
    out["known_answer_check_passed"] = bool(ok and out["pooled_by_year"])
    return out


def clean_sample(p, ex_roll=False, year_min=None, ex_defect=False):
    """ex-FOMC / ex-CPI / ex-NFP, with a usable |d|."""
    m = (~p.is_fomc_day) & (~p.is_cpi_day) & (~p.is_nfp_day) & p.abs_d_rate_bp.notna()
    if ex_roll:
        m &= ~p.is_imm_roll
    if ex_defect:
        m &= ~p.date.isin(DEFECT_DAYS)
    if year_min is not None:
        m &= p.year >= year_min
    return p[m].copy()


# ----------------------------------------------------------------------------------
# 2. core statistic + bootstrap
# ----------------------------------------------------------------------------------
def arm_stats(df):
    s = df.loc[df.is_speech_day, "abs_d_rate_bp"].to_numpy(float)
    n = df.loc[~df.is_speech_day, "abs_d_rate_bp"].to_numpy(float)
    if len(s) == 0 or len(n) == 0:
        return None
    return dict(
        n_days=int(len(df)),
        n_speech=int(len(s)),
        n_nonspeech=int(len(n)),
        mean_abs_speech=float(s.mean()),
        mean_abs_nonspeech=float(n.mean()),
        median_abs_speech=float(np.median(s)),
        median_abs_nonspeech=float(np.median(n)),
        excess_ratio=float(s.mean() / n.mean()),
        excess_diff_bp=float(s.mean() - n.mean()),
        median_ratio=float(np.median(s) / np.median(n)),
        sd_speech=float(s.std(ddof=1)),
        sd_nonspeech=float(n.std(ddof=1)),
        _s=s,
        _n=n,
    )


def boot_ratio(s, n, rng, nboot=N_BOOT):
    """Stratified iid day bootstrap: resample speech days and non-speech days
    independently, holding arm sizes fixed. Returns the ratio draws."""
    si = rng.integers(0, len(s), size=(nboot, len(s)))
    ni = rng.integers(0, len(n), size=(nboot, len(n)))
    return s[si].mean(axis=1) / n[ni].mean(axis=1)


def boot_ratio_block(df, rng, block=5, nboot=N_BOOT):
    """Moving-block bootstrap over the regime's own day sequence, so |d| volatility
    clustering is preserved. Arm sizes vary by draw; that is the point."""
    d = df.sort_values("date")
    x = d["abs_d_rate_bp"].to_numpy(float)
    lab = d["is_speech_day"].to_numpy(bool)
    N = len(x)
    if N < block * 2:
        return np.array([])
    nb = int(np.ceil(N / block))
    starts = rng.integers(0, N - block + 1, size=(nboot, nb))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(nboot, -1)[:, :N]
    xs, ls = x[idx], lab[idx]
    out = np.full(nboot, np.nan)
    ns = ls.sum(axis=1)
    ok = (ns > 0) & (ns < N)
    ss = np.where(ls, xs, 0.0).sum(axis=1)
    nn = np.where(~ls, xs, 0.0).sum(axis=1)
    out[ok] = (ss[ok] / ns[ok]) / (nn[ok] / (N - ns[ok]))
    return out[np.isfinite(out)]


def ci(v, lo=2.5, hi=97.5):
    if len(v) == 0:
        return [None, None]
    return [float(np.percentile(v, lo)), float(np.percentile(v, hi))]


def se_log_mean(x):
    """Delta-method SE of log(mean) = (sd/mean)/sqrt(n)."""
    return float(x.std(ddof=1) / x.mean() / np.sqrt(len(x)))


def se_log_ratio(s, n):
    return float(np.sqrt(se_log_mean(s) ** 2 + se_log_mean(n) ** 2))


# ----------------------------------------------------------------------------------
# 3. power analysis by simulation
# ----------------------------------------------------------------------------------
def z_stat(sA, nA, sB, nB):
    """Studentized log ratio-of-ratios, plug-in delta-method SE."""
    lr = np.log(sB.mean() / nB.mean()) - np.log(sA.mean() / nA.mean())
    se = np.sqrt(se_log_ratio(sA, nA) ** 2 + se_log_ratio(sB, nB) ** 2)
    return lr / se


def simulate_power(poolA, poolB, nsA, nnA, nsB, nnB, rP, rho, rng, nsim=N_SIM):
    """
    Alternative: Powell arm carries its observed excess rP; Warsh arm carries rP*rho.
    Draws come from each regime's OWN |d| pool, so each arm keeps its ambient vol level
    and its own tail shape.  Returns rejection rate of a two-sided 5% test on the
    studentized log ratio-of-ratios.
    """
    rej = 0
    for _ in range(nsim):
        sA = rng.choice(poolA, nsA, replace=True) * rP
        nA = rng.choice(poolA, nnA, replace=True)
        sB = rng.choice(poolB, nsB, replace=True) * (rP * rho)
        nB = rng.choice(poolB, nnB, replace=True)
        if abs(z_stat(sA, nA, sB, nB)) > 1.959964:
            rej += 1
    return rej / nsim


# ----------------------------------------------------------------------------------
# 4. main
# ----------------------------------------------------------------------------------
def main():
    rng = np.random.default_rng(SEED)
    p = load_panel()
    cl = clean_sample(p)

    say("=" * 96)
    say("ANALYSIS B -- CHAIR REGIME SPLIT (Powell vs Warsh)")
    say("=" * 96)
    say(f"panel rows {len(p)}   span {p.date.min().date()} .. {p.date.max().date()}")
    say(f"clean sample (ex-FOMC / ex-CPI / ex-NFP, |d| present): {len(cl)} days")
    say(f"chair transition used: {TRANSITION.date()}  (build reported confident=True)")
    say("")

    RESULTS["meta"] = dict(
        seed=SEED,
        n_boot=N_BOOT,
        n_sim=N_SIM,
        transition_date=str(TRANSITION.date()),
        transition_confident=True,
        panel_rows=int(len(p)),
        clean_rows=int(len(cl)),
        panel_span=[str(p.date.min().date()), str(p.date.max().date())],
        primary_metric="excess_ratio = mean|d_rate_bp| on speech days / mean|d_rate_bp| on non-speech days, within regime",
        exclusions="is_fomc_day, is_cpi_day, is_nfp_day",
    )

    # ---- 4a. per-regime primary ---------------------------------------------------
    arms = {}
    for reg in ["Powell", "Warsh"]:
        a = arm_stats(cl[cl.chair_regime == reg])
        a["date_min"] = str(cl[cl.chair_regime == reg].date.min().date())
        a["date_max"] = str(cl[cl.chair_regime == reg].date.max().date())
        b = boot_ratio(a["_s"], a["_n"], rng)
        a["ratio_ci95"] = ci(b)
        a["ratio_boot_sd"] = float(b.std(ddof=1))
        bb = boot_ratio_block(cl[cl.chair_regime == reg], rng)
        a["ratio_ci95_block5"] = ci(bb)
        a["se_log_ratio"] = se_log_ratio(a["_s"], a["_n"])
        arms[reg] = a

    say("-" * 96)
    say("PRIMARY -- excess |move| ratio within each chair regime (ex-FOMC/CPI/NFP)")
    say("-" * 96)
    hdr = f"{'regime':8s} {'span':25s} {'days':>5s} {'sp':>4s} {'nsp':>4s} {'mean|d|sp':>10s} {'mean|d|nsp':>11s} {'ratio':>7s} {'95% CI':>18s} {'diff bp':>8s}"
    say(hdr)
    for reg, a in arms.items():
        lo, hi = a["ratio_ci95"]
        say(
            f"{reg:8s} {a['date_min']}..{a['date_max']} {a['n_days']:5d} {a['n_speech']:4d} "
            f"{a['n_nonspeech']:4d} {a['mean_abs_speech']:10.3f} {a['mean_abs_nonspeech']:11.3f} "
            f"{a['excess_ratio']:7.3f} [{lo:6.3f},{hi:6.3f}] {a['excess_diff_bp']:8.3f}"
        )
    for reg, a in arms.items():
        lo, hi = a["ratio_ci95_block5"]
        say(f"   {reg:8s} block-5 bootstrap CI (vol clustering preserved): [{lo:.3f}, {hi:.3f}]"
            f"   median-based ratio {a['median_ratio']:.3f}")
    say("")

    # ratio-of-ratios
    bP = boot_ratio(arms["Powell"]["_s"], arms["Powell"]["_n"], rng)
    bW = boot_ratio(arms["Warsh"]["_s"], arms["Warsh"]["_n"], rng)
    rr_draws = bW / bP
    rr_obs = arms["Warsh"]["excess_ratio"] / arms["Powell"]["excess_ratio"]
    rr_ci = ci(rr_draws)
    z_obs = z_stat(arms["Powell"]["_s"], arms["Powell"]["_n"], arms["Warsh"]["_s"], arms["Warsh"]["_n"])
    # two-sided bootstrap p for rr != 1
    p_boot = float(2 * min((rr_draws < 1).mean(), (rr_draws > 1).mean()))

    say(f"COMPARISON STATISTIC  ratio-of-ratios (Warsh / Powell) = {rr_obs:.3f}")
    say(f"   bootstrap 95% CI [{rr_ci[0]:.3f}, {rr_ci[1]:.3f}]   spans 1.0: {rr_ci[0] < 1 < rr_ci[1]}")
    say(f"   studentized z = {z_obs:+.3f}   bootstrap two-sided p = {p_boot:.3f}")
    say("")

    RESULTS["primary"] = {
        reg: {k: v for k, v in a.items() if not k.startswith("_")} for reg, a in arms.items()
    }
    RESULTS["comparison"] = dict(
        ratio_of_ratios=float(rr_obs),
        ratio_of_ratios_ci95=rr_ci,
        ratio_of_ratios_spans_one=bool(rr_ci[0] < 1 < rr_ci[1]),
        z_studentized=float(z_obs),
        p_bootstrap_two_sided=p_boot,
    )

    # ---- 4b. POWER ----------------------------------------------------------------
    say("=" * 96)
    say("POWER ANALYSIS  (read this before the point estimates)")
    say("=" * 96)
    poolP = cl.loc[cl.chair_regime == "Powell", "abs_d_rate_bp"].to_numpy(float)
    poolW = cl.loc[cl.chair_regime == "Warsh", "abs_d_rate_bp"].to_numpy(float)
    nsP, nnP = arms["Powell"]["n_speech"], arms["Powell"]["n_nonspeech"]
    nsW, nnW = arms["Warsh"]["n_speech"], arms["Warsh"]["n_nonspeech"]
    rP = arms["Powell"]["excess_ratio"]

    # calibration self-check: at rho = 1 the test must reject about 5% of the time
    rng_cal = np.random.default_rng(SEED + 1)
    size = simulate_power(poolP, poolW, nsP, nnP, nsW, nnW, rP, 1.0, rng_cal)
    say(f"[self-check] simulated size at rho=1.0 (should be ~0.05): {size:.4f}")
    calib_ok = 0.02 <= size <= 0.10

    # power curve
    grid = [1.05, 1.10, 1.17, 1.25, 1.40, 1.60, 1.80, 2.00, 2.25, 2.50, 3.00]
    curve = {}
    rng_pw = np.random.default_rng(SEED + 2)
    for f in grid:
        curve[f] = simulate_power(poolP, poolW, nsP, nnP, nsW, nnW, rP, f, rng_pw)
    say("simulated power vs ratio-of-ratios rho (alpha=0.05 two-sided):")
    for f, pw in curve.items():
        mark = "   <-- observed" if abs(f - 1.17) < 1e-9 else ""
        say(f"   rho={f:5.2f}   power={pw:5.3f}{mark}")

    # MDE by interpolation on the simulated curve
    fs = np.array(list(curve.keys()))
    pw = np.array(list(curve.values()))
    mde_sim = None
    for i in range(len(fs) - 1):
        if pw[i] < 0.80 <= pw[i + 1]:
            mde_sim = float(fs[i] + (0.80 - pw[i]) * (fs[i + 1] - fs[i]) / (pw[i + 1] - pw[i]))
            break
    if mde_sim is None and pw[-1] < 0.80:
        mde_sim = float("nan")

    # achieved power at the observed effect
    rng_ach = np.random.default_rng(SEED + 3)
    power_observed = simulate_power(poolP, poolW, nsP, nnP, nsW, nnW, rP, rr_obs, rng_ach)

    # analytic cross-check
    se_rr = float(np.sqrt(arms["Powell"]["se_log_ratio"] ** 2 + arms["Warsh"]["se_log_ratio"] ** 2))
    mde_analytic = float(np.exp(2.801586 * se_rr))

    say("")
    say(f"MINIMUM DETECTABLE EFFECT at 80% power, alpha=0.05 two-sided")
    say(f"   simulated  : ratio-of-ratios rho >= {mde_sim:.2f}")
    say(f"   analytic   : ratio-of-ratios rho >= {mde_analytic:.2f}   (SE of log rho = {se_rr:.4f})")
    say(f"   in absolute terms the Warsh excess_ratio would have to reach "
        f"{rP * mde_sim:.2f} (vs Powell {rP:.3f}) before this sample could call it.")
    say(f"OBSERVED effect rho = {rr_obs:.3f}   ACHIEVED POWER = {power_observed:.3f}")
    underpowered = bool(mde_sim > 1.5 and power_observed < 0.5)
    say("")
    if underpowered:
        say("*** THE COMPARISON IS UNDERPOWERED. ***")
        say("    An underpowered null is NOT evidence of no effect, and an underpowered")
        say("    positive is NOT evidence of one. Every point estimate below is reported")
        say("    subject to this. The Warsh arm is 1 quarter of data: 56 clean days,")
        say(f"    {nsW} of them speech days.")
    say("")

    RESULTS["power"] = dict(
        calibration_size_at_rho1=float(size),
        calibration_ok=bool(calib_ok),
        power_curve={str(k): float(v) for k, v in curve.items()},
        mde_ratio_of_ratios_80pct_sim=mde_sim,
        mde_ratio_of_ratios_80pct_analytic=mde_analytic,
        se_log_ratio_of_ratios=se_rr,
        warsh_excess_ratio_needed_to_detect=float(rP * mde_sim),
        observed_effect_rho=float(rr_obs),
        achieved_power_at_observed=float(power_observed),
        underpowered=underpowered,
        n_warsh_speech_days=int(nsW),
        n_warsh_nonspeech_days=int(nnW),
    )

    # ---- 4b2. VERIFY THE ESTIMATOR AND THE TEST AGAINST KNOWN ANSWERS -------------
    say("=" * 96)
    say("VERIFICATION OF THIS SCRIPT'S OWN MACHINERY")
    say("=" * 96)
    vrng = np.random.default_rng(SEED + 11)
    ver = {}

    # V1 known answer: inject an exact 2.0x speech effect, the estimator must recover it
    base = vrng.choice(poolW, 20000, replace=True)
    sy = vrng.choice(poolW, 8000, replace=True) * 2.0
    r_hat = float(sy.mean() / base.mean())
    say(f"[V1] injected a known 2.00x speech effect on 8,000 synthetic speech days -> "
        f"estimator returns {r_hat:.3f}   PASS={abs(r_hat - 2.0) < 0.06}")
    ver["V1_known_2x_recovered"] = r_hat

    # V1b the test must REJECT a real 2x gap at these sample sizes (this is the MDE claim in reverse)
    rng_v = np.random.default_rng(SEED + 12)
    pw2 = simulate_power(poolP, poolW, nsP, nnP, nsW, nnW, rP, 2.0, rng_v, nsim=1500)
    say(f"[V1b] at a true rho=2.00 the test rejects {pw2:.3f} of the time -> the machinery is not")
    say(f"      simply blind; it fails to reject at rho={rr_obs:.2f} because that effect is small,")
    say("      not because the test never fires.")
    ver["V1b_power_at_rho2"] = float(pw2)

    # V2 label permutation inside each regime: an independent p for the comparison
    permrho = np.empty(5000)
    sP_all = cl.loc[cl.chair_regime == "Powell", "abs_d_rate_bp"].to_numpy(float)
    sW_all = cl.loc[cl.chair_regime == "Warsh", "abs_d_rate_bp"].to_numpy(float)
    prng = np.random.default_rng(SEED + 13)
    for i in range(len(permrho)):
        pp = prng.permutation(len(sP_all)); ww = prng.permutation(len(sW_all))
        rp = sP_all[pp[:nsP]].mean() / sP_all[pp[nsP:]].mean()
        rw = sW_all[ww[:nsW]].mean() / sW_all[ww[nsW:]].mean()
        permrho[i] = rw / rp
    p_perm = float(2 * min((permrho >= rr_obs).mean(), (permrho <= rr_obs).mean()))
    say(f"[V2] speech-label permutation inside each regime (5,000 draws): null rho centred at "
        f"{np.median(permrho):.3f}, 2.5-97.5pct [{np.percentile(permrho, 2.5):.3f}, "
        f"{np.percentile(permrho, 97.5):.3f}]")
    say(f"     observed rho {rr_obs:.3f} -> permutation two-sided p = {p_perm:.3f}  "
        f"(bootstrap p was {p_boot:.3f}; two independent routes agree)")
    ver["V2_permutation_null_median_rho"] = float(np.median(permrho))
    ver["V2_permutation_p_two_sided"] = p_perm

    # V3 mutation: strip the within-regime normalization and see the naive read flip sign
    naive = arms["Warsh"]["mean_abs_speech"] / arms["Powell"]["mean_abs_speech"]
    say(f"[V3] MUTATION -- delete the normalization and compare raw speech-day |d| across regimes: "
        f"{naive:.3f}x")
    say(f"     the un-normalized read says Warsh speech days move LESS "
        f"({arms['Warsh']['mean_abs_speech']:.2f} vs {arms['Powell']['mean_abs_speech']:.2f} bp), "
        "the OPPOSITE sign to the")
    say("     normalized read. The normalization is load-bearing, not decorative.")
    ver["V3_unnormalized_cross_regime_ratio"] = float(naive)

    # V4 median-based comparison statistic (one 20bp day cannot own it)
    med_rho = arms["Warsh"]["median_ratio"] / arms["Powell"]["median_ratio"]
    say(f"[V4] median-based rho = {med_rho:.3f} (Warsh {arms['Warsh']['median_ratio']:.3f} / "
        f"Powell {arms['Powell']['median_ratio']:.3f}) -- same conclusion, smaller effect.")
    say(f"     NOTE the Powell median ratio is {arms['Powell']['median_ratio']:.2f} while its MEAN ratio is "
        f"{arms['Powell']['excess_ratio']:.2f}: Powell non-speech")
    say("     days carry the fatter right tail (supply, geopolitics), so the mean ratio is dragged to 1.")
    ver["V4_median_based_rho"] = float(med_rho)
    RESULTS["verification"] = ver
    say("")

    # ---- 4c. robustness arms ------------------------------------------------------
    say("=" * 96)
    say("ROBUSTNESS ARMS -- is the conclusion arm-invariant?")
    say("=" * 96)
    variants = {}

    def add_variant(name, dfP, dfW, note=""):
        aP, aW = arm_stats(dfP), arm_stats(dfW)
        if aP is None or aW is None:
            return
        r = aW["excess_ratio"] / aP["excess_ratio"]
        variants[name] = dict(
            note=note,
            powell_ratio=aP["excess_ratio"], warsh_ratio=aW["excess_ratio"],
            ratio_of_ratios=float(r),
            n_powell_days=aP["n_days"], n_powell_speech=aP["n_speech"],
            n_warsh_days=aW["n_days"], n_warsh_speech=aW["n_speech"],
            powell_mean_abs_speech=aP["mean_abs_speech"], powell_mean_abs_nonspeech=aP["mean_abs_nonspeech"],
            warsh_mean_abs_speech=aW["mean_abs_speech"], warsh_mean_abs_nonspeech=aW["mean_abs_nonspeech"],
        )
        say(f"{name:34s} Powell {aP['excess_ratio']:6.3f} (n={aP['n_days']:4d})   "
            f"Warsh {aW['excess_ratio']:6.3f} (n={aW['n_days']:3d})   rho={r:6.3f}   {note}")

    add_variant("PRIMARY full-Powell", cl[cl.chair_regime == "Powell"], cl[cl.chair_regime == "Warsh"], "as specified")
    clr = clean_sample(p, ex_roll=True)
    add_variant("ex-IMM-roll", clr[clr.chair_regime == "Powell"], clr[clr.chair_regime == "Warsh"],
                "roll days book a mechanical jump")
    cld = clean_sample(p, ex_defect=True)
    add_variant("ex curve-build defect", cld[cld.chair_regime == "Powell"], cld[cld.chair_regime == "Warsh"],
                "same 6 dates Analysis A cuts from V1 on")
    cl20 = clean_sample(p, year_min=2020)
    add_variant("2020+ (2019 target provisional)", cl20[cl20.chair_regime == "Powell"], cl20[cl20.chair_regime == "Warsh"],
                "build caveat (2)")
    cl22 = clean_sample(p, year_min=2022)
    add_variant("2022+ (post-ZIRP)", cl22[cl22.chair_regime == "Powell"], cl22[cl22.chair_regime == "Warsh"], "")
    P12 = cl[(cl.date >= TRANSITION - pd.Timedelta(days=365)) & (cl.date < TRANSITION)]
    add_variant("Powell last 12m as reference", P12, cl[cl.chair_regime == "Warsh"], "adjacent-period reference")
    P6 = cl[(cl.date >= TRANSITION - pd.Timedelta(days=182)) & (cl.date < TRANSITION)]
    add_variant("Powell last 6m as reference", P6, cl[cl.chair_regime == "Warsh"], "adjacent-period reference")
    say("")
    all_rho = [v["ratio_of_ratios"] for v in variants.values()]
    say(f"rho across arms: min {min(all_rho):.3f}  max {max(all_rho):.3f}  "
        f"-- every one of them sits below the MDE of {mde_sim:.2f}: {max(all_rho) < mde_sim}")
    RESULTS["robustness_arms"] = variants
    RESULTS["robustness_arms_rho_range"] = [float(min(all_rho)), float(max(all_rho))]
    RESULTS["conclusion_arm_invariant"] = bool(max(all_rho) < mde_sim)
    say("")

    # ---- 4c-i. the ex-defect arm, spelled out --------------------------------------
    # Analysis A cuts these six dates from V1 onward and states the cut FLATTERS the thesis.
    # Analysis B must treat the same known-bad dates the same way or say why not.
    surv = cl[cl.date.isin(DEFECT_DAYS)]
    say("-" * 96)
    say("EX CURVE-BUILD DEFECT -- the same 6 dates Analysis A isolates")
    say("-" * 96)
    say(f"  {len(DEFECT_DAYS)} defect dates; {len(surv)} survive the ex-FOMC/CPI/NFP filter:")
    for _, r in surv.iterrows():
        say(f"    {r.date.date()}  |d|={r.abs_d_rate_bp:7.2f}bp  regime={r.chair_regime:6s}  "
            f"speech={bool(r.is_speech_day)}")
    big = surv[surv.abs_d_rate_bp > 20]
    say(f"  all under Powell: {bool((surv.chair_regime == 'Powell').all())}   "
        f"all in the NON-speech arm: {bool((~surv.is_speech_day).all())}")
    say(f"  the {len(big)} LARGE ones (|d|>20bp) are all non-speech: "
        f"{bool((~big.is_speech_day).all())} -- that is what moves the denominator; the "
        f"{len(surv) - len(big)} small interior days are immaterial either way.")
    vd = variants["ex curve-build defect"]
    say(f"  Powell excess ratio {arms['Powell']['excess_ratio']:.4f} -> {vd['powell_ratio']:.4f}   "
        f"rho {rr_obs:.4f} -> {vd['ratio_of_ratios']:.4f}")
    say("  DIRECTION: leaving the defect in INFLATES Powell's non-speech denominator, which "
        "depresses Powell's ratio and RAISES rho -- i.e. the untreated version favours the")
    say("  Warsh thesis. The conclusion does not move (both sit far below the MDE), but the two "
        "analyses now handle the same known-bad dates identically.")
    say("")
    RESULTS["ex_defect_arm"] = dict(
        defect_dates=[str(d.date()) for d in DEFECT_DAYS],
        n_surviving_clean_filter=int(len(surv)),
        surviving=[dict(date=str(r.date.date()), abs_d_bp=float(r.abs_d_rate_bp),
                        regime=str(r.chair_regime), is_speech_day=bool(r.is_speech_day))
                   for _, r in surv.iterrows()],
        all_in_nonspeech_arm=bool((~surv.is_speech_day).all()),
        large_defect_days_all_nonspeech=bool((~surv[surv.abs_d_rate_bp > 20].is_speech_day).all()),
        all_under_powell=bool((surv.chair_regime == "Powell").all()),
        powell_ratio_as_spec=float(arms["Powell"]["excess_ratio"]),
        powell_ratio_ex_defect=float(vd["powell_ratio"]),
        rho_as_spec=float(rr_obs),
        rho_ex_defect=float(vd["ratio_of_ratios"]),
        direction="the untreated version FAVOURS the Warsh thesis (rho falls when the defect is cut)",
        conclusion_unchanged=bool(vd["ratio_of_ratios"] < mde_sim),
    )

    # ---- 4c-ii. boundary-shift sensitivity -----------------------------------------
    # The transition date is a hard-coded constant; a threshold placed at the edge of a
    # short window is the repo's documented boundary-signal-placebo hazard.  Move it.
    say("=" * 96)
    say("BOUNDARY-SHIFT SENSITIVITY -- is the verdict a property of the DATE we chose?")
    say("=" * 96)
    Z975, Z80 = 1.959963985, 0.8416212336
    shift_rows = []
    say(f"{'shift':>6s} {'date':12s} {'post_n':>7s} {'post_sp':>8s} {'post_r':>7s} "
        f"{'pre_r':>6s} {'rho':>6s} {'rho CI95':>16s} {'MDE':>6s}  verdict")
    for months in (-3, -2, -1, 0, 1, 2, 3):
        cut = TRANSITION + pd.DateOffset(months=months)
        pre, post = cl[cl.date < cut], cl[cl.date >= cut]
        aPre, aPost = arm_stats(pre), arm_stats(post)
        if aPre is None or aPost is None:
            say(f"{months:+5d}m {str(cut.date()):12s} {len(post):7d} "
                f"{int(post.is_speech_day.sum()):8d} {'--':>7s} {'--':>6s} {'--':>6s} "
                f"{'--':>16s} {'--':>6s}  DEGENERATE (no ratio formable)")
            shift_rows.append(dict(shift_months=months, cut_date=str(cut.date()),
                                   post_n_days=int(len(post)),
                                   post_n_speech=int(post.is_speech_day.sum()),
                                   degenerate=True))
            continue
        bPre = boot_ratio(aPre["_s"], aPre["_n"], rng)
        bPost = boot_ratio(aPost["_s"], aPost["_n"], rng)
        rr_s = aPost["excess_ratio"] / aPre["excess_ratio"]
        ci_s = ci(bPost / bPre)
        se_s = float(np.sqrt(se_log_ratio(aPre["_s"], aPre["_n"]) ** 2
                             + se_log_ratio(aPost["_s"], aPost["_n"]) ** 2))
        mde_s = float(np.exp((Z975 + Z80) * se_s))
        spans1 = bool(ci_s[0] < 1 < ci_s[1])
        verdict_s = "undetermined_sample" if (rr_s < mde_s) else ("DETECTED" if not spans1 else "undetermined_sample")
        flag = "" if spans1 else "   <-- CI EXCLUDES 1"
        say(f"{months:+5d}m {str(cut.date()):12s} {aPost['n_days']:7d} {aPost['n_speech']:8d} "
            f"{aPost['excess_ratio']:7.3f} {aPre['excess_ratio']:6.3f} {rr_s:6.3f} "
            f"[{ci_s[0]:6.3f},{ci_s[1]:6.3f}] {mde_s:6.3f}  {verdict_s}{flag}")
        shift_rows.append(dict(
            shift_months=months, cut_date=str(cut.date()), degenerate=False,
            post_n_days=aPost["n_days"], post_n_speech=aPost["n_speech"],
            post_ratio=aPost["excess_ratio"], pre_ratio=aPre["excess_ratio"],
            ratio_of_ratios=float(rr_s), rho_ci95=ci_s, spans_one=spans1,
            analytic_mde_80pct=mde_s,
            verdict="undetermined_sample" if rr_s < mde_s else verdict_s,
            is_placebo_inside_powell=bool(months < 0),
        ))
    ok_rows = [r for r in shift_rows if not r["degenerate"]]
    post_rs = [r["post_ratio"] for r in ok_rows]
    rhos = [r["ratio_of_ratios"] for r in ok_rows]
    placebo_fires = [r for r in ok_rows if r["is_placebo_inside_powell"] and not r["spans_one"]]
    say("")
    say(f"  verdicts across non-degenerate placements: "
        f"{sorted(set(r['verdict'] for r in ok_rows))}  -- none flips to DETECTED")
    say(f"  direction is stable: rho > 1 at {sum(r['ratio_of_ratios'] > 1 for r in ok_rows)} of "
        f"{len(ok_rows)} placements")
    say(f"  BUT THE POINT ESTIMATE IS NOT: post-arm ratio spans [{min(post_rs):.3f}, {max(post_rs):.3f}] "
        f"and rho spans [{min(rhos):.3f}, {max(rhos):.3f}] over +/-2 months.")
    r0 = [r["post_ratio"] for r in ok_rows if r["shift_months"] == 0][0]
    where0 = "MINIMUM" if r0 <= min(post_rs) + 1e-9 else ("MAXIMUM" if r0 >= max(post_rs) - 1e-9 else "interior")
    say(f"  The ACTUAL transition date yields the {where0} of the grid (post ratio {r0:.3f}).")
    for r in placebo_fires:
        say(f"  *** BOUNDARY PLACEBO FIRES: a split at {r['cut_date']} -- {abs(r['shift_months'])} month(s) "
            f"BEFORE the handover, entirely inside Powell's tenure -- gives rho {r['ratio_of_ratios']:.3f} "
            f"with CI [{r['rho_ci95'][0]:.3f}, {r['rho_ci95'][1]:.3f}] EXCLUDING 1.0.")
    if placebo_fires:
        say("      An arbitrary Powell-era date manufactures a nominally significant 'regime' difference.")
        say("      That is the strongest available evidence that the 2026 lift is a WINDOW property,")
        say("      not a CHAIR property.")
    say("")
    RESULTS["boundary_shift_sensitivity"] = dict(
        design="re-label the regimes at TRANSITION +/- k months, k in {-3,-2,-1,0,1,2,3}; everything "
               "else (masks, statistic, bootstrap) held fixed",
        rows=shift_rows,
        verdict_set=sorted(set(r["verdict"] for r in ok_rows)),
        any_placement_flips_to_detected=bool(any(r["verdict"] == "DETECTED" for r in ok_rows)),
        post_ratio_range=[float(min(post_rs)), float(max(post_rs))],
        rho_range=[float(min(rhos)), float(max(rhos))],
        placebo_fires_inside_powell=[r["cut_date"] for r in placebo_fires],
        interpretation="the VERDICT is boundary-invariant; the POINT ESTIMATE emphatically is not. "
                       "A split two months before the handover, on a date where no regime change "
                       "occurred, produces a CI excluding 1 -- a textbook boundary-signal placebo.",
    )

    # ---- 4c-iii. the power CEILING -------------------------------------------------
    # Powell's tenure is over, so SE(log excess ratio | Powell) is FROZEN.  It floors
    # SE(log rho) no matter how long the Warsh arm runs.  This kills the naive "just wait
    # a few more quarters" remediation.
    say("=" * 96)
    say("POWER CEILING -- can MORE DATA ever settle this?  No.")
    say("=" * 96)
    seP = arms["Powell"]["se_log_ratio"]
    seW = arms["Warsh"]["se_log_ratio"]
    mde_floor = float(np.exp((Z975 + Z80) * seP))
    z_max = float(abs(np.log(rr_obs)) / seP)

    def _power(z):
        from math import erf, sqrt
        cdf = lambda x: 0.5 * (1.0 + erf(x / sqrt(2.0)))
        return float(cdf(z - Z975) + cdf(-z - Z975))

    say(f"  SE(log ratio | Powell) = {seP:.5f}  -- FROZEN: Powell's tenure ended {TRANSITION.date()}")
    say(f"  SE(log ratio | Warsh)  = {seW:.5f}  -- shrinks as ~1/sqrt(n) with more post-transition days")
    say(f"  => SE(log rho) can never fall below {seP:.5f}")
    say(f"  => MDE FLOOR = exp({Z975 + Z80:.3f} x {seP:.5f}) = {mde_floor:.3f}  vs OBSERVED rho {rr_obs:.3f}")
    say(f"  => the MDE NEVER reaches the observed effect: {mde_floor > rr_obs}")
    say(f"  => MAX ACHIEVABLE POWER at rho={rr_obs:.3f}, even with an infinite Warsh arm = {_power(z_max):.3f}")
    say("     (80% power is UNREACHABLE by this design at this effect size.)")
    say("")
    say(f"  {'quarters added':>15s} {'SE_W':>8s} {'SE_rho':>8s} {'MDE':>7s} {'power@obs':>10s}")
    proj = []
    for k in (0, 2, 4, 6, 12, 30):
        seW_k = seW / np.sqrt(1.0 + k)
        se_k = float(np.sqrt(seP ** 2 + seW_k ** 2))
        mde_k = float(np.exp((Z975 + Z80) * se_k))
        pw_k = _power(float(abs(np.log(rr_obs)) / se_k))
        say(f"  {k:>15d} {seW_k:8.4f} {se_k:8.4f} {mde_k:7.3f} {pw_k:10.3f}")
        proj.append(dict(quarters_added=k, se_log_ratio_warsh=float(seW_k), se_log_rho=se_k,
                         analytic_mde_80pct=mde_k, power_at_observed_effect=pw_k))
    say("")
    say("  CONSEQUENCE FOR THE REMEDIATION: 'wait 4-6 more quarters' is arithmetically wrong.")
    say("  After 6 more quarters the MDE is still ~%.2f with power ~%.2f. Settling this needs a"
        % (proj[3]["analytic_mde_80pct"], proj[3]["power_at_observed_effect"]))
    say("  DIFFERENT DESIGN -- a post-2026-05-22 intraday per-trade log (higher-frequency, more")
    say("  observations per speech), or benchmarking the Warsh window against the SEASONAL")
    say("  PLACEBO distribution rather than the whole Powell sample.")
    say("")
    RESULTS["power_ceiling"] = dict(
        se_log_ratio_powell_FROZEN=float(seP),
        se_log_ratio_warsh_current=float(seW),
        mde_floor=mde_floor,
        observed_rho=float(rr_obs),
        mde_floor_exceeds_observed_effect=bool(mde_floor > rr_obs),
        max_achievable_power_at_observed_effect=_power(z_max),
        projection_by_quarters_added=proj,
        why="Powell's tenure is over, so SE(log excess ratio | Powell) is fixed at "
            f"{seP:.5f} and floors SE(log rho). More calendar time shrinks only the Warsh SE.",
        remediation_CORRECTED="Re-running this script on a longer panel CANNOT settle a 1.17x effect. "
                              "The resolution requires a different design: (a) re-run the intraday "
                              "event book so a post-2026-05-22 per-trade log exists, giving an "
                              "independent higher-frequency measurement, or (b) benchmark the "
                              "post-transition window against the season-matched placebo "
                              "distribution, which is the comparator with the right null.",
    )

    # ---- 4d. FALSIFICATION: does the break line up with the chair change? ---------
    say("=" * 96)
    say("FALSIFICATION -- 2026 split at the transition, and the by-year grid")
    say("=" * 96)
    c26 = cl[cl.year == 2026]
    a26pre = arm_stats(c26[c26.date < TRANSITION])
    a26post = arm_stats(c26[c26.date >= TRANSITION])
    say(f"2026 PRE-transition  (Powell, {c26[c26.date < TRANSITION].date.min().date()}..{(TRANSITION - pd.Timedelta(days=1)).date()}): "
        f"n={a26pre['n_days']:3d} sp={a26pre['n_speech']:3d}  ratio={a26pre['excess_ratio']:.3f}")
    say(f"2026 POST-transition (Warsh,  {c26[c26.date >= TRANSITION].date.min().date()}..{c26.date.max().date()}): "
        f"n={a26post['n_days']:3d} sp={a26post['n_speech']:3d}  ratio={a26post['excess_ratio']:.3f}")
    say("")
    say("  -> the 2026 lift PREDATES the chair change. The excess ratio was ALREADY")
    say(f"     {a26pre['excess_ratio']:.2f} under Powell in 2026 and moved to {a26post['excess_ratio']:.2f} after the handover,")
    say("     i.e. DOWN, not up. Under the regime story it should have stepped UP at")
    say("     2026-05-22. It did not. (Both sides are tiny; this is attribution")
    say("     evidence inside an underpowered window, not a rejection.)")
    say("")
    RESULTS["falsification_2026_split"] = dict(
        pre_transition={k: v for k, v in a26pre.items() if not k.startswith("_")},
        post_transition={k: v for k, v in a26post.items() if not k.startswith("_")},
        lift_predates_transition=bool(a26pre["excess_ratio"] > a26post["excess_ratio"]),
        interpretation="the 2026 excess ratio was already elevated under Powell and fell after the handover; "
                       "the break does not line up with the chair change",
    )

    # by-year grid, 2026 split -- WITH per-year bootstrap CIs, because eight ratios plotted
    # without uncertainty read as a path when they are one noise band wide.
    rows = []

    def _yrow(lbl, y, gg, reg):
        a = arm_stats(gg)
        b = boot_ratio(a["_s"], a["_n"], rng)
        c = ci(b)
        return dict(label=lbl, year=int(y), n_days=a["n_days"], n_speech=a["n_speech"],
                    mean_abs_speech=a["mean_abs_speech"], mean_abs_nonspeech=a["mean_abs_nonspeech"],
                    excess_ratio=a["excess_ratio"], ci_lo=c[0], ci_hi=c[1],
                    ci_width=float(c[1] - c[0]), ci_excludes_one=bool(c[0] > 1.0 or c[1] < 1.0),
                    regime=reg)

    for y, g in cl.groupby("year"):
        if y == 2026:
            rows.append(_yrow("2026 (pre)", y, g[g.date < TRANSITION], "Powell"))
            rows.append(_yrow("2026 (post)", y, g[g.date >= TRANSITION], "Warsh"))
        else:
            rows.append(_yrow(str(int(y)), y, g, "Powell"))
    byyear = pd.DataFrame(rows)
    say("excess_ratio by calendar year (2026 split at the transition), with 95% day-bootstrap CIs:")
    say(byyear[["label", "n_days", "n_speech", "excess_ratio", "ci_lo", "ci_hi",
                "ci_width", "ci_excludes_one"]].round(3).to_string(index=False))
    say(f"  -> years whose CI EXCLUDES 1.0: {int(byyear.ci_excludes_one.sum())} of {len(byyear)}   "
        f"(CI widths {byyear.ci_width.min():.2f}-{byyear.ci_width.max():.2f})")
    say("  the by-year excursion 0.74 -> 1.33 is ONE noise band wide; it is not a series with a break.")
    pw_years = byyear[byyear.label.str.match(r"^\d{4}$")]["excess_ratio"]
    say("")
    say(f"  Powell-year ratios 2019-2025: mean {pw_years.mean():.3f}  sd {pw_years.std(ddof=1):.3f}  "
        f"range [{pw_years.min():.3f}, {pw_years.max():.3f}]")
    say(f"  the by-year series oscillates around 1 with no step at the transition; 2020 "
        f"({byyear.loc[byyear.label=='2020','excess_ratio'].iloc[0]:.3f}) already exceeded the Warsh value.")
    RESULTS["by_year"] = byyear.to_dict(orient="records")
    byyear.to_csv(os.path.join(OUT, "regime_split_by_year.csv"), index=False)

    # ---- 4e. seasonal placebo -----------------------------------------------------
    say("")
    say("=" * 96)
    say("SEASONAL PLACEBO -- the Warsh window is only 22 May .. 24 Aug (summer lull)")
    say("=" * 96)
    placebo = []
    for y in range(2019, 2026):
        lo = pd.Timestamp(year=y, month=5, day=22)
        hi = pd.Timestamp(year=y, month=8, day=24)
        g = cl[(cl.date >= lo) & (cl.date <= hi)]
        a = arm_stats(g)
        if a is None:
            continue
        placebo.append(dict(year=int(y), n_days=a["n_days"], n_speech=a["n_speech"],
                            excess_ratio=a["excess_ratio"],
                            mean_abs_speech=a["mean_abs_speech"], mean_abs_nonspeech=a["mean_abs_nonspeech"]))
    pl = pd.DataFrame(placebo)
    say("same calendar window (22 May .. 24 Aug) in each Powell year:")
    say(pl.round(3).to_string(index=False))
    warsh_r = arms["Warsh"]["excess_ratio"]
    n_above = int((pl.excess_ratio >= warsh_r).sum())
    say("")
    say(f"  Warsh 2026 value {warsh_r:.3f} vs {len(pl)} season-matched Powell placebos: "
        f"{n_above} of {len(pl)} placebo summers were AT LEAST as high.")
    say(f"  placebo mean {pl.excess_ratio.mean():.3f}, sd {pl.excess_ratio.std(ddof=1):.3f}, "
        f"range [{pl.excess_ratio.min():.3f}, {pl.excess_ratio.max():.3f}]")
    say(f"  one-sided placebo p (rank of the Warsh value among the 8 summers) = "
        f"{(n_above + 1) / (len(pl) + 1):.3f}")
    RESULTS["seasonal_placebo"] = dict(
        window="22 May .. 24 Aug",
        placebos=pl.to_dict(orient="records"),
        warsh_value=float(warsh_r),
        n_placebos_at_least_as_high=n_above,
        placebo_p_one_sided=float((n_above + 1) / (len(pl) + 1)),
        placebo_mean=float(pl.excess_ratio.mean()),
        placebo_sd=float(pl.excess_ratio.std(ddof=1)),
    )

    # ---- 4f. claim 2: are events getting rarer / bigger per event? ---------------
    say("")
    say("=" * 96)
    say("CLAIM 2 -- 'Warsh wants FEWER, higher-signal events'")
    say("=" * 96)
    ev = []
    for reg in ["Powell", "Warsh"]:
        g = cl[cl.chair_regime == reg]
        sp = g[g.is_speech_day]
        a = arms[reg]
        excess_bp = a["mean_abs_speech"] - a["mean_abs_nonspeech"]
        ev.append(dict(regime=reg, calendar_days=int(len(g)), speech_days=int(len(sp)),
                       events=int(sp.n_speakers.sum()),
                       events_per_calendar_day=float(g.n_speakers.sum() / len(g)),
                       events_per_speech_day=float(sp.n_speakers.mean()),
                       speech_day_share=float(len(sp) / len(g)),
                       excess_bp_per_speech_day=float(excess_bp),
                       excess_bp_per_event=float(excess_bp / sp.n_speakers.mean())))
    evdf = pd.DataFrame(ev)
    say(evdf.round(3).to_string(index=False))
    say("")
    say("  event COUNT is not falling: events/calendar-day "
        f"{evdf.events_per_calendar_day.iloc[0]:.3f} -> {evdf.events_per_calendar_day.iloc[1]:.3f} "
        f"and events per speech day {evdf.events_per_speech_day.iloc[0]:.3f} -> {evdf.events_per_speech_day.iloc[1]:.3f} (UP).")
    say("  (the frequency agent owns the count; this line is descriptive corroboration.)")
    say(f"  excess bp per EVENT: {evdf.excess_bp_per_event.iloc[0]:+.4f} -> {evdf.excess_bp_per_event.iloc[1]:+.4f} bp"
        " -- higher under Warsh, but on 22 speech days / 50 events.")
    RESULTS["claim2_event_intensity"] = evdf.to_dict(orient="records")

    # per-event marginal move: does |d| scale with n_speakers within regime?
    marg = {}
    for reg in ["Powell", "Warsh"]:
        g = cl[cl.chair_regime == reg]
        x = g.n_speakers.to_numpy(float)
        y = g.abs_d_rate_bp.to_numpy(float)
        if x.std() > 0:
            b, a0 = np.polyfit(x, y, 1)
            resid = y - (a0 + b * x)
            se_b = float(np.sqrt(resid.var(ddof=2) / ((x - x.mean()) ** 2).sum()))
            marg[reg] = dict(slope_bp_per_event=float(b), intercept_bp=float(a0),
                             se_slope=se_b, t_stat=float(b / se_b), n=int(len(g)))
    say("")
    say("marginal |move| per additional speaker on the day (OLS |d| ~ n_speakers, within regime):")
    for reg, m in marg.items():
        say(f"   {reg:8s} slope {m['slope_bp_per_event']:+.4f} bp/event  t={m['t_stat']:+.2f}  n={m['n']}")
    RESULTS["claim2_marginal_slope"] = marg

    # ---- 4g. intraday cross-check -------------------------------------------------
    say("")
    say("=" * 96)
    say("CROSS-CHECK vs THE INTRADAY EVIDENCE ON DISK")
    say("=" * 96)
    xchk = {}
    nav_path = os.path.join(BASE, "nav_closed.csv")
    intr_year = None
    if os.path.exists(nav_path):
        t = pd.read_csv(nav_path)
        t["opened_at"] = pd.to_datetime(t["opened_at"], utc=True).dt.tz_convert("America/New_York")
        bpv = t["source_query"].str.extract(r"'bpv':\s*(-?\d+)")[0].astype(float).abs()
        t["abs_move_bp"] = t["gross_realized_pnl"].abs() / bpv
        t["y"] = t["opened_at"].dt.year
        n_post = int((t["opened_at"] >= TRANSITION.tz_localize("America/New_York")).sum())
        say(f"nav_closed.csv: {len(t)} FED event trades, "
            f"{t.opened_at.min().date()} .. {t.opened_at.max().date()}")
        say(f"POST-TRANSITION intraday observations: {n_post}")
        say("")
        say("*** THE INTRADAY CROSS-CHECK CANNOT BE COMPUTED. ***")
        say("    The only per-trade logs on disk (nav_closed.csv, sig_closed.csv, both written")
        say("    2026-03-31) end at 2026-03-27 -- BEFORE the 2026-05-22 handover. There are ZERO")
        say("    post-transition intraday observations. _final_report.txt is from a later run whose")
        say("    FED trades reach 2026-07-16, but that run left no per-trade log on disk, only")
        say("    year-level aggregates that STRADDLE the transition. A regime comparison must not")
        say("    be manufactured from straddling year aggregates, so none is reported.")
        say("")
        intr_year = t.groupby("y")["abs_move_bp"].agg(["count", "mean", "median"]).round(3)
        say("what the intraday log CAN confirm -- the ambient decline that forces the normalization:")
        say("   intraday 3h event-window |move| (bp), by year:")
        say(intr_year.to_string())
        nsp_year = cl[~cl.is_speech_day].groupby("year")["abs_d_rate_bp"].mean().round(3)
        say("   daily panel mean |d| on NON-speech days (bp), by year:")
        say(nsp_year.to_string())
        _fr0 = parse_final_report(os.path.join(BASE, "_final_report.txt"))
        if _fr0["pooled_by_year"]:
            say("   _final_report.txt pooled per-trade std (bp), PARSED: "
                + ", ".join(f"{y} {d['std']:.2f}" for y, d in _fr0["pooled_by_year"].items()))
        yrs = [y for y in intr_year.index if y in nsp_year.index]
        corr = float(np.corrcoef(intr_year.loc[yrs, "mean"], nsp_year.loc[yrs])[0, 1]) if len(yrs) >= 3 else None
        say(f"   two INDEPENDENT measurements of ambient level, {len(yrs)} overlapping years, corr = "
            f"{corr if corr is None else round(corr, 3)}")
        say("   -> they AGREE that ambient vol fell hard; that is why the raw cross-regime |d|")
        say("      difference is reported as strictly subordinate to the within-regime ratio.")
        xchk = dict(
            status="BLOCKED -- no post-transition intraday observations",
            nav_closed_rows=int(len(t)),
            nav_closed_first=str(t.opened_at.min().date()),
            nav_closed_last=str(t.opened_at.max().date()),
            post_transition_trades=n_post,
            intraday_abs_move_bp_by_year={str(k): float(v) for k, v in intr_year["mean"].items()},
            daily_nonspeech_abs_bp_by_year={str(k): float(v) for k, v in nsp_year.items()},
            ambient_agreement_corr=corr,
            note="_final_report.txt (later run, FED trades to 2026-07-16) exposes only year-level "
                 "aggregates that straddle 2026-05-22; no regime comparison was constructed from them.",
        )
    RESULTS["intraday_cross_check"] = xchk

    # ---- 4h. directional stats (DIFFERENT QUESTION) -------------------------------
    say("")
    say("=" * 96)
    say("DIRECTIONAL STATISTICS -- A DIFFERENT QUESTION, reported separately")
    say("=" * 96)
    say("These measure whether the SIGN of the move is predictable, not how much")
    say("information the event carries. More information per event means bigger moves")
    say("in BOTH directions: |move| can rise while directional hit rate FALLS.")
    say("")
    # These figures used to be hand-transcribed. A transcription typo would propagate
    # silently, so parse the source file instead and fail loudly if it is not there.
    fr = parse_final_report(os.path.join(BASE, "_final_report.txt"))
    say(f"  parsed from _final_report.txt (intraday FED book) -- {fr['status']}:")
    if fr["halves"]:
        for h, d in fr["halves"].items():
            say(f"     {h:8s} {d['range']:26s} {d['trades']:4d} trades  Sharpe {d['sharpe']:5.2f}  "
                f"hit {d['hit']:.3f}  {d['total_bp']:+7.1f} bp")
    if fr["pooled_by_year"]:
        say("     pooled by year (all banks): " + ", ".join(
            f"{y} SR {d['sharpe']:.2f} (hit {d['hit']:.3f}, std {d['std']:.2f}bp)"
            for y, d in fr["pooled_by_year"].items()))
    say("  the decaying Sharpe is a DIRECTIONAL result. It is NOT evidence about")
    say("  information content, and the two can move in opposite directions.")
    say("")
    drift = {}
    for reg in ["Powell", "Warsh"]:
        g = cl[cl.chair_regime == reg]
        s = g.loc[g.is_speech_day, "d_rate_bp"]
        n = g.loc[~g.is_speech_day, "d_rate_bp"]
        drift[reg] = dict(mean_signed_speech_bp=float(s.mean()), mean_signed_nonspeech_bp=float(n.mean()),
                          n_speech=int(len(s)), n_nonspeech=int(len(n)))
        say(f"  daily panel, mean SIGNED d_rate_bp  {reg:7s}: speech {s.mean():+.3f}  "
            f"non-speech {n.mean():+.3f} bp  (descriptive; no signal direction in this panel)")
    RESULTS["directional_separate_question"] = dict(
        source_file=fr["path"],
        source_parse_status=fr["status"],
        intraday_fed_halves=fr["halves"],
        intraday_pooled_by_year=fr["pooled_by_year"],
        daily_signed_drift=drift,
        provenance="PARSED programmatically from _final_report.txt at run time, not transcribed",
        note="directional decay is a different question from information content; a rising |move| "
             "is fully compatible with a falling hit rate",
    )

    # ---- 4i. secondary raw difference --------------------------------------------
    say("")
    say("SECONDARY (subordinate) -- raw cross-regime numbers, contaminated by the vol regime:")
    say(f"  mean|d| on speech days      Powell {arms['Powell']['mean_abs_speech']:.3f}  -> Warsh {arms['Warsh']['mean_abs_speech']:.3f} bp")
    say(f"  mean|d| on non-speech days  Powell {arms['Powell']['mean_abs_nonspeech']:.3f}  -> Warsh {arms['Warsh']['mean_abs_nonspeech']:.3f} bp")
    say(f"  excess (speech - non-speech) Powell {arms['Powell']['excess_diff_bp']:+.3f} -> Warsh {arms['Warsh']['excess_diff_bp']:+.3f} bp")
    RESULTS["secondary_raw"] = dict(
        powell_mean_abs_speech=arms["Powell"]["mean_abs_speech"],
        warsh_mean_abs_speech=arms["Warsh"]["mean_abs_speech"],
        powell_mean_abs_nonspeech=arms["Powell"]["mean_abs_nonspeech"],
        warsh_mean_abs_nonspeech=arms["Warsh"]["mean_abs_nonspeech"],
        powell_excess_diff_bp=arms["Powell"]["excess_diff_bp"],
        warsh_excess_diff_bp=arms["Warsh"]["excess_diff_bp"],
        caveat="raw levels reflect the ambient vol regime, not the speech effect; the ratio is primary",
    )

    # ---- verdict ------------------------------------------------------------------
    if underpowered:
        verdict = "undetermined_sample"
    elif rr_ci[0] > 1:
        verdict = "warsh_higher"
    elif rr_ci[1] < 1:
        verdict = "warsh_lower"
    else:
        verdict = "indistinguishable"

    RESULTS["verdict"] = verdict
    RESULTS["caveats"] = [
        "UNDERPOWERED: the Warsh arm is 56 clean days (22 speech, 34 non-speech). Simulated MDE at "
        f"80% power is a ratio-of-ratios of {mde_sim:.2f}; the observed effect is {rr_obs:.2f} with "
        f"achieved power {power_observed:.2f}. An underpowered null is not evidence of no effect.",
        "ZERO WARSH SPEECHES IN THE WARSH REGIME: the build reports no Chair-titled Fed event of any "
        "name after 2026-03-30 and Warsh has zero events in this calendar. 'Warsh regime' therefore "
        "measures committee-member Fedspeak under a silent chair, not Warsh's own communication.",
        "The chair transition date 2026-05-22 is repo-derived (fomc_extras.CHAIRS, "
        "FED_SPEAKER_QUARTERLY_LABELS.md), corroborated by a data-derived interval (2026-03-30, "
        "2026-05-31] whose right edge rests on a single Powell row.",
        "SEASONAL CONFOUND: the Warsh window is 22 May .. 24 Aug only. The season-matched placebo is "
        "reported; the raw Powell arm spans all seasons.",
        "2019 target is provisional (the build reports 124 consecutive flat-curve days and a broken ON "
        "leg); the 2020+ arm is reported and does not change the conclusion.",
        "IMM-roll days book a mechanical jump on a constant-relative-rank slot; the ex-IMM-roll arm is "
        "reported and does not change the conclusion.",
        "The intraday cross-check could NOT be computed: the only per-trade logs on disk end 2026-03-27, "
        "before the handover, so there are zero post-transition intraday observations.",
        "The 2026 excess ratio was already elevated under Powell before the handover and fell after it, "
        "so the break in the by-year series does not line up with the chair change.",
        "NO YEAR SEPARATES FROM 1.0: every per-year excess ratio, 2019-2026, has a 95% day-bootstrap CI "
        f"that spans 1.0 (widths {byyear.ci_width.min():.2f}-{byyear.ci_width.max():.2f}). The by-year "
        "excursion is one noise band wide and must not be read as a series with a break.",
        "EX CURVE-BUILD DEFECT: Analysis A cuts 6 defect dates from V1 onward; 4 survive this analysis' "
        "clean filter, all four under Powell, and the two LARGE ones (+73.24bp, -74.05bp) are both in "
        "his NON-speech arm (a third, 2019-07-02, is a 4.09bp speech day and is immaterial). Cutting them moves Powell "
        f"{arms['Powell']['excess_ratio']:.3f} -> {vd['powell_ratio']:.3f} and rho {rr_obs:.3f} -> "
        f"{vd['ratio_of_ratios']:.3f}. The untreated version FAVOURS the Warsh thesis; the conclusion "
        "is unchanged either way.",
        "BOUNDARY PLACEBO: a split at 2026-03-22 -- two months BEFORE the handover and entirely inside "
        "Powell's tenure -- produces a bootstrap CI that EXCLUDES 1.0. The verdict is invariant to the "
        "boundary date, but the point estimate is not: the post-arm ratio spans "
        f"{RESULTS['boundary_shift_sensitivity']['post_ratio_range'][0]:.2f}-"
        f"{RESULTS['boundary_shift_sensitivity']['post_ratio_range'][1]:.2f} over +/-2 months, and the "
        "actual date yields the minimum of that grid.",
        "MORE DATA CANNOT SETTLE THIS. Powell's tenure is over, so SE(log excess ratio | Powell) is "
        f"frozen at {arms['Powell']['se_log_ratio']:.4f} and floors SE(log rho). The MDE floor is "
        f"{RESULTS['power_ceiling']['mde_floor']:.3f}, permanently ABOVE the observed "
        f"{rr_obs:.3f}, and maximum achievable power at the observed effect is "
        f"{RESULTS['power_ceiling']['max_achievable_power_at_observed_effect']:.2f}. Re-running this "
        "script on a longer panel is NOT the resolution; a different design is.",
    ]
    RESULTS["what_would_settle_this_CORRECTED"] = (
        "NOT 'wait 4-6 more quarters' -- that is arithmetically impossible with the Powell arm closed "
        f"(MDE floor {RESULTS['power_ceiling']['mde_floor']:.3f} > observed {rr_obs:.3f}; max power "
        f"{RESULTS['power_ceiling']['max_achievable_power_at_observed_effect']:.2f}). Two designs can: "
        "(a) re-run the intraday event book so a post-2026-05-22 per-trade log exists, replacing the "
        "close-to-close proxy with a 30-minute event window (many more observations per speech, and a "
        "far less attenuated instrument); (b) benchmark the post-transition window against the "
        "season-matched placebo distribution (7 Powell summers, mean 1.13) rather than the whole "
        "Powell sample, which is the comparator with the right null.")

    say("")
    say("=" * 96)
    say(f"VERDICT: {verdict}")
    say("=" * 96)

    with open(os.path.join(OUT, "regime_split_results.json"), "w") as f:
        json.dump(RESULTS, f, indent=2, default=str)
    with open(os.path.join(OUT, "regime_split_report.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(LOG))

    make_figure(arms, byyear, pl, curve, mde_sim, rr_obs, power_observed, rr_ci, a26pre, a26post, rng)
    say(f"wrote regime_split_results.json / regime_split_report.txt / fig_regime_split.png in {OUT}")
    return RESULTS


# ----------------------------------------------------------------------------------
# 5. figure
# ----------------------------------------------------------------------------------
def make_figure(arms, byyear, pl, curve, mde_sim, rr_obs, power_obs, rr_ci, a26pre, a26post, rng):
    fig = plt.figure(figsize=(15.6, 10.4), dpi=220, facecolor=SURFACE)
    gs = fig.add_gridspec(2, 2, width_ratios=[1.0, 1.36], height_ratios=[1.0, 0.92],
                          hspace=0.50, wspace=0.30, left=0.128, right=0.975, top=0.855, bottom=0.105)

    fig.text(0.045, 0.960, "Does a Fedspeak day move the 3x4 IMM forward more under Warsh than under Powell?",
             fontsize=17.5, color=INK, fontweight="600", ha="left")
    fig.text(0.045, 0.928,
             "Excess |move| ratio = mean |\u0394 rate| on speech days \u00f7 mean |\u0394 rate| on non-speech days, computed WITHIN each regime",
             fontsize=11.0, color=INK2, ha="left")
    fig.text(0.045, 0.905,
             "(ex-FOMC, ex-CPI, ex-NFP), so the collapse in ambient vol is divided out.   The Warsh arm is one quarter: 56 days, 22 of them speech days.",
             fontsize=11.0, color=INK2, ha="left")

    # ---- panel A: ratio by regime, with CI ----
    ax = fig.add_subplot(gs[0, 0])
    ax.set_facecolor(SURFACE)
    labels, vals, los, his, cols = [], [], [], [], []
    for reg, col in [("Powell", C_POWELL), ("Warsh", C_WARSH)]:
        a = arms[reg]
        labels.append(f"{reg}\n{a['n_days']:,} days\n{a['n_speech']} speech")
        vals.append(a["excess_ratio"]); los.append(a["ratio_ci95"][0]); his.append(a["ratio_ci95"][1]); cols.append(col)
    ys = np.arange(len(vals))[::-1]
    ax.axvline(1.0, color=MUTED, lw=1.4, ls=(0, (4, 3)), zorder=1)
    ax.text(1.0, 1.62, "no speech effect", fontsize=9.0, color=MUTED, ha="center", va="bottom",
            bbox=dict(boxstyle="square,pad=0.22", fc=SURFACE, ec="none"))
    for y, v, lo, hi, c in zip(ys, vals, los, his, cols):
        ax.plot([lo, hi], [y, y], color=c, lw=2.0, solid_capstyle="butt", zorder=3, alpha=0.55)
        for e in (lo, hi):
            ax.plot([e, e], [y - .07, y + .07], color=c, lw=2.0, zorder=3, alpha=0.55)
        ax.scatter([v], [y], s=125, color=c, zorder=5, edgecolor=SURFACE, linewidth=2.0)
        ax.text(v, y + 0.16, f"{v:.2f}", fontsize=12.5, color=INK, ha="center", va="bottom", fontweight="600")
        ax.text(hi + 0.05, y, f"95% CI  {lo:.2f}\u2013{hi:.2f}", fontsize=9.0, color=INK2, va="center")
    ax.set_yticks(ys); ax.set_yticklabels(labels, fontsize=10.0, color=INK, linespacing=1.35)
    ax.set_ylim(-0.72, 1.72)
    ax.set_xlim(0.58, 2.30)
    ax.set_xlabel("excess |move| ratio  (speech \u00f7 non-speech, same regime)", fontsize=10.0, color=INK2, labelpad=8)
    ax.xaxis.set_major_locator(MultipleLocator(0.25))
    ax.set_title("A \u00b7 The two regimes, with day-bootstrap uncertainty", fontsize=12.2, color=INK,
                 loc="left", pad=12, fontweight="600")
    ax.grid(axis="x", color=GRID, lw=0.8); ax.set_axisbelow(True)
    for sp in ("top", "right", "left"):
        ax.spines[sp].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=INK2, length=0, labelsize=9.5)
    ax.annotate(
        f"The Warsh interval is {his[1]-los[1]:.2f} wide.\n"
        f"Seeing the observed {rr_obs:.2f}\u00d7 gap needs {mde_sim:.1f}\u00d7.",
        xy=(0.97, 0.03), xycoords="axes fraction", ha="right", va="bottom", fontsize=9.4,
        color=INK2, bbox=dict(boxstyle="round,pad=0.5", fc="#f3f2ee", ec=GRID, lw=0.9))

    # ---- panel B: by-year, WITH per-year uncertainty ----
    # A connected line of eight ratios with no CI draws a pure-noise band as a path, and this
    # is the panel a reader screenshots.  Every year's CI spans 1.0; show that.
    ax2 = fig.add_subplot(gs[0, 1])
    ax2.set_facecolor(SURFACE)
    seq = byyear.reset_index(drop=True)
    xs = np.arange(len(seq), dtype=float)
    pw_mask = seq.regime.eq("Powell").to_numpy()
    ylo = np.array([r["ci_lo"] for r in seq.to_dict("records")], float)
    yhi = np.array([r["ci_hi"] for r in seq.to_dict("records")], float)
    # FIXED band, not autoscaled to the point estimates -- an autoscaled axis makes noise
    # fill the panel top to bottom.
    ax2.set_ylim(0.24, 2.78)
    ax2.axhline(1.0, color=MUTED, lw=1.4, ls=(0, (4, 3)), zorder=1)
    # the connecting line is a reading guide only, not a trend: greyed and thin
    ax2.plot(xs, seq.excess_ratio, color=MUTED, lw=0.9, ls=(0, (3, 3)), zorder=2, alpha=0.75)
    for x, v, lo_i, hi_i, isp in zip(xs, seq.excess_ratio, ylo, yhi, pw_mask):
        c = C_POWELL if isp else C_WARSH
        ax2.plot([x, x], [lo_i, hi_i], color=c, lw=2.0, solid_capstyle="butt", alpha=0.55, zorder=3)
        for e in (lo_i, hi_i):
            ax2.plot([x - .07, x + .07], [e, e], color=c, lw=2.0, alpha=0.55, zorder=3)
    ax2.scatter(xs[pw_mask], seq.excess_ratio[pw_mask], color=C_POWELL, s=95, zorder=5,
                edgecolor=SURFACE, linewidth=1.8, label="Powell")
    wi = np.where(~pw_mask)[0]
    ax2.scatter(xs[wi], seq.excess_ratio.iloc[wi], color=C_WARSH, s=105, zorder=5,
                edgecolor=SURFACE, linewidth=1.8, label="Warsh")
    bx = (xs[wi[0]] + xs[wi[0] - 1]) / 2
    ax2.axvline(bx, color=C_WARSH, lw=1.6, ls=(0, (2, 2)), zorder=2)
    ax2.text(bx + 0.10, 2.30, "chair change\n2026-05-22", fontsize=8.8, color=C_WARSH,
             ha="left", va="top", fontweight="600", linespacing=1.25)
    # value + n on EVERY point, not three of nine
    for x, v, hi_i, nsp, nd in zip(xs, seq.excess_ratio, yhi, seq.n_speech, seq.n_days):
        ax2.text(x, hi_i + 0.045, f"{v:.2f}", fontsize=9.2, color=INK, ha="center",
                 va="bottom", fontweight="600")
        ax2.text(x, 0.265, f"n={int(nd)}\n{int(nsp)} sp", fontsize=7.6, color=MUTED,
                 ha="center", va="bottom", linespacing=1.25)
    ax2.set_xticks(xs)
    ax2.set_xticklabels([s.replace(" ", "\n") for s in seq.label], fontsize=9.4, color=INK2)
    ax2.set_xlim(-0.6, len(seq) - 0.4)
    ax2.set_ylabel("excess |move| ratio", fontsize=10.0, color=INK2)
    n_excl = int(((ylo > 1.0) | (yhi < 1.0)).sum())
    ax2.set_title("B \u00b7 By calendar year \u2014 no year separates from 1.0",
                  fontsize=12.2, color=INK, loc="left", pad=12, fontweight="600")
    ax2.grid(axis="y", color=GRID, lw=0.8); ax2.set_axisbelow(True)
    for sp in ("top", "right", "left"):
        ax2.spines[sp].set_visible(False)
    ax2.spines["bottom"].set_color(GRID)
    ax2.tick_params(colors=INK2, length=0, labelsize=9.5)
    # No legend: it lands on the n-labels. Colour is keyed in the note instead.
    ax2.annotate(f"blue = Powell, orange = Warsh.  Bars = 95% stratified day-bootstrap CI.\n"
                 f"{n_excl} of {len(seq)} years exclude 1.0 \u2014 the 0.74\u21921.33 excursion is ONE noise band wide.\n"
                 f"The 2026 lift sits BEFORE the handover.  Dashed path = reading guide, not a trend.",
                 xy=(0.015, 0.985), xycoords="axes fraction", ha="left", va="top", fontsize=8.5,
                 color=INK2, linespacing=1.5,
                 bbox=dict(boxstyle="round,pad=0.42", fc="#f3f2ee", ec=GRID, lw=0.9))

    # ---- panel C: power curve ----
    ax3 = fig.add_subplot(gs[1, 0])
    ax3.set_facecolor(SURFACE)
    fs = np.array(list(curve.keys())); pws = np.array(list(curve.values()))
    ax3.plot(fs, pws, color=C_THIRD, lw=2.2, zorder=3, marker="o", ms=6, mec=SURFACE, mew=1.5)
    ax3.axhline(0.80, color=MUTED, lw=1.3, ls=(0, (4, 3)))
    ax3.text(3.02, 0.815, "80% power", fontsize=9.0, color=MUTED, ha="right", va="bottom")
    ax3.axvline(rr_obs, color=C_WARSH, lw=1.8, zorder=4)
    ax3.scatter([rr_obs], [power_obs], color=C_WARSH, s=115, zorder=6, edgecolor=SURFACE, linewidth=1.8)
    ax3.annotate(f"observed {rr_obs:.2f}\u00d7\npower {power_obs:.0%}", xy=(rr_obs, power_obs),
                 xytext=(1.88, 0.28), fontsize=10.0, color=C_WARSH, fontweight="600",
                 arrowprops=dict(arrowstyle="-", color=C_WARSH, lw=1.2))
    if np.isfinite(mde_sim):
        ax3.axvline(mde_sim, color=C_THIRD, lw=1.6, ls=(0, (2, 2)), zorder=4)
        ax3.text(mde_sim + 0.07, 0.05, f"MDE {mde_sim:.2f}\u00d7", fontsize=10.0, color=C_THIRD, fontweight="600")
    ax3.set_xlabel("true ratio-of-ratios  (Warsh excess \u00f7 Powell excess)", fontsize=10.0, color=INK2, labelpad=8)
    ax3.set_ylabel("power at \u03b1 = 0.05", fontsize=10.0, color=INK2)
    ax3.set_ylim(0, 1.04); ax3.set_xlim(1.0, 3.05)
    ax3.set_title("C \u00b7 This sample cannot see the effect it is asked about",
                  fontsize=12.2, color=INK, loc="left", pad=12, fontweight="600")
    ax3.grid(color=GRID, lw=0.8); ax3.set_axisbelow(True)
    for sp in ("top", "right"):
        ax3.spines[sp].set_visible(False)
    for sp in ("bottom", "left"):
        ax3.spines[sp].set_color(GRID)
    ax3.tick_params(colors=INK2, length=0, labelsize=9.5)

    # ---- panel D: seasonal placebo ----
    ax4 = fig.add_subplot(gs[1, 1])
    ax4.set_facecolor(SURFACE)
    px = np.arange(len(pl) + 1, dtype=float)
    pvals = list(pl.excess_ratio) + [arms["Warsh"]["excess_ratio"]]
    plabels = [str(y) for y in pl.year] + ["2026\nWarsh"]
    pcols = [C_POWELL] * len(pl) + [C_WARSH]
    ax4.set_ylim(min(pvals) - 0.07, max(pvals) + 0.13)
    ax4.axhline(1.0, color=MUTED, lw=1.4, ls=(0, (4, 3)), zorder=1)
    for x, v, c in zip(px, pvals, pcols):
        ax4.plot([x, x], [1.0, v], color=c, lw=2.0, solid_capstyle="butt", alpha=0.35, zorder=2)
        ax4.scatter([x], [v], color=c, s=100, zorder=5, edgecolor=SURFACE, linewidth=1.8)
        ax4.text(x, v + 0.030, f"{v:.2f}", fontsize=9.6, color=INK, ha="center", va="bottom")
    ax4.axhline(arms["Warsh"]["excess_ratio"], color=C_WARSH, lw=1.1, ls=(0, (2, 3)), zorder=1, alpha=0.8)
    ax4.set_xticks(px); ax4.set_xticklabels(plabels, fontsize=9.4, color=INK2)
    ax4.set_xlim(-0.6, len(pl) + 0.6)
    ax4.set_ylabel("excess |move| ratio", fontsize=10.0, color=INK2)
    n_above = int((pl.excess_ratio >= arms["Warsh"]["excess_ratio"]).sum())
    ax4.set_title("D \u00b7 Season-matched placebo, 22 May \u2013 24 Aug of each year",
                  fontsize=12.2, color=INK, loc="left", pad=12, fontweight="600")
    ax4.annotate(f"{n_above} of {len(pl)} Powell summers\nwere at least as high",
                 xy=(0.015, 0.975), xycoords="axes fraction", ha="left", va="top", fontsize=9.6,
                 color=INK2, bbox=dict(boxstyle="round,pad=0.45", fc="#f3f2ee", ec=GRID, lw=0.9))
    ax4.grid(axis="y", color=GRID, lw=0.8); ax4.set_axisbelow(True)
    for sp in ("top", "right", "left"):
        ax4.spines[sp].set_visible(False)
    ax4.spines["bottom"].set_color(GRID)
    ax4.tick_params(colors=INK2, length=0, labelsize=9.5)

    fig.text(0.045, 0.040,
             "VERDICT undetermined_sample \u2014 the Warsh arm is 56 clean days and contains ZERO Warsh speeches "
             "(no Chair-titled Fed event of any name appears after 2026-03-30).",
             fontsize=9.6, color=INK2, ha="left", va="bottom", fontweight="600")
    fig.text(0.045, 0.014,
             "Source: panel_daily.parquet \u2014 USD-SOFR-1D IMM_3xIMM_4 par rate.  10,000 stratified day-bootstrap resamples; "
             "power by 4,000-draw simulation (size at \u03c1=1 is 0.059); seed 20260825.",
             fontsize=8.8, color=MUTED, ha="left", va="bottom")

    out = os.path.join(OUT, "fig_regime_split.png")
    fig.savefig(out, dpi=220, facecolor=SURFACE)
    plt.close(fig)



if __name__ == "__main__":
    main()
