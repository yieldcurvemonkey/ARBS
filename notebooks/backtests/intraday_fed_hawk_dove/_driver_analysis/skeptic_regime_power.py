"""
Independent sample-size / power skeptic re-check of Analysis B (chair regime split).

Recomputes, from the panel alone:
  (1) arm sizes under the same clean mask
  (2) excess ratios, ratio-of-ratios, stratified bootstrap CI, permutation p
  (3) analytic MDE at 80% power / alpha=0.05 (delta-method on log ratio-of-ratios)
      + a small simulation cross-check
  (4) BOUNDARY-SHIFT SENSITIVITY: transition date shifted -3,-2,-1,0,+1,+2,+3 months
  (5) chair_regime column vs. the claimed 2026-05-22 date (is the label date-consistent?)

Writes nothing except its own JSON/TXT under the output dir.
"""
import os, sys, json
import numpy as np
import pandas as pd

OUT = r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_driver_analysis"
SEED = 777001
rng = np.random.default_rng(SEED)
N_BOOT = 20000

lines = []
def say(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    lines.append(s)

R = {}

# ---------------------------------------------------------------- load
p = pd.read_parquet(os.path.join(OUT, "panel_daily.parquet"))
if "date" not in p.columns:
    p = p.reset_index()
p["date"] = pd.to_datetime(p["date"])
p = p.sort_values("date").reset_index(drop=True)
for c in ["is_fomc_day", "is_cpi_day", "is_nfp_day", "is_speech_day", "is_blackout", "is_imm_roll"]:
    p[c] = p[c].astype(bool)

say(f"panel rows={len(p)}  span {p.date.min().date()} -> {p.date.max().date()}")
R["panel_rows"] = int(len(p))
R["panel_span"] = [str(p.date.min().date()), str(p.date.max().date())]

# ---------------------------------------------------------------- clean mask
def clean(df, ex_roll=False, year_min=None):
    m = (~df.is_fomc_day) & (~df.is_cpi_day) & (~df.is_nfp_day) & df.abs_d_rate_bp.notna()
    if ex_roll:
        m &= ~df.is_imm_roll
    if year_min is not None:
        m &= df.year >= year_min
    return df[m].copy()

C = clean(p)
say(f"clean sample (ex-FOMC/CPI/NFP, non-null |d|) = {len(C)} of {len(p)}")
R["clean_n"] = int(len(C))

# ---------------------------------------------------------------- (5) label consistency
say("")
say("=== (5) is the chair_regime LABEL consistent with the claimed 2026-05-22 date? ===")
say("chair_regime value counts (full panel):")
vc = p.chair_regime.value_counts().to_dict()
for k, v in vc.items():
    say(f"   {k}: {v}")
R["chair_regime_counts_full_panel"] = {str(k): int(v) for k, v in vc.items()}

lab = p.groupby("chair_regime")["date"].agg(["min", "max", "count"])
for k, row in lab.iterrows():
    say(f"   {k}: {row['min'].date()} .. {row['max'].date()}  n={int(row['count'])}")
non_powell = sorted(set(p.chair_regime) - {"Powell"})
if non_powell:
    lbl = non_powell[0]
    first_post = p.loc[p.chair_regime == lbl, "date"].min()
    last_pre = p.loc[p.chair_regime == "Powell", "date"].max()
    say(f"   first '{lbl}' panel day = {first_post.date()}; last Powell panel day = {last_pre.date()}")
    implied_ok = (first_post >= pd.Timestamp("2026-05-22")) and (last_pre < pd.Timestamp("2026-05-22"))
    say(f"   label boundary consistent with 2026-05-22: {implied_ok}")
    R["label_boundary_consistent_with_20260522"] = bool(implied_ok)
    R["first_post_regime_day"] = str(first_post.date())

# does any Warsh-labelled row carry a Warsh (or any Chair-titled) speaker? -- read raw calendar
try:
    cal = pd.read_parquet(os.path.join(OUT, "fed_calendar_raw.parquet"))
    tcol = [c for c in cal.columns if "Timestamp" in c or c.lower() == "date"][0]
    ts = pd.to_datetime(cal[tcol], utc=True).dt.tz_convert("America/New_York")
    title_col = None
    for c in cal.columns:
        if cal[c].dtype == object and cal[c].astype(str).str.contains("FOMC Member|Fed Chair", na=False).any():
            title_col = c
            break
    if title_col is not None:
        post = cal[ts >= pd.Timestamp("2026-05-22", tz="America/New_York")]
        say(f"   raw calendar events on/after 2026-05-22: {len(post)}")
        chairish = post[post[title_col].astype(str).str.contains("Chair", case=False, na=False)]
        warshy = post[post[title_col].astype(str).str.contains("Warsh", case=False, na=False)]
        say(f"     of which Chair-titled: {len(chairish)}   Warsh-named: {len(warshy)}")
        R["raw_events_post_transition"] = int(len(post))
        R["raw_chair_titled_post_transition"] = int(len(chairish))
        R["raw_warsh_named_post_transition"] = int(len(warshy))
except Exception as e:
    say(f"   (calendar cross-check skipped: {e!r})")

# ---------------------------------------------------------------- (1) arm sizes
say("")
say("=== (1) ARM SIZES, recomputed independently ===")

def arm(df):
    s = df.loc[df.is_speech_day, "abs_d_rate_bp"].to_numpy(float)
    n = df.loc[~df.is_speech_day, "abs_d_rate_bp"].to_numpy(float)
    if len(s) < 2 or len(n) < 2:
        return dict(n_days=int(len(df)), n_speech=int(len(s)), n_nonspeech=int(len(n)),
                    ratio=np.nan, mean_s=float(s.mean()) if len(s) else np.nan,
                    mean_n=float(n.mean()) if len(n) else np.nan, _s=s, _n=n, degenerate=True)
    return dict(n_days=int(len(df)), n_speech=int(len(s)), n_nonspeech=int(len(n)),
                mean_s=float(s.mean()), mean_n=float(n.mean()),
                ratio=float(s.mean() / n.mean()),
                med_ratio=float(np.median(s) / np.median(n)),
                _s=s, _n=n, degenerate=False)

by_regime = {}
for k, g in C.groupby("chair_regime"):
    by_regime[k] = arm(g)
    a = by_regime[k]
    say(f"   {k:8s} clean days={a['n_days']:5d}  speech={a['n_speech']:4d}  nonspeech={a['n_nonspeech']:4d}  "
        f"mean|d| sp={a['mean_s']:.3f} ns={a['mean_n']:.3f}  ratio={a['ratio']:.4f}")

# pre-mask counts too
say("   pre-mask (full panel) day counts by regime:")
for k, g in p.groupby("chair_regime"):
    say(f"     {k:8s} days={len(g):5d}  speech={int(g.is_speech_day.sum()):4d}")

POW = "Powell"
WAR = [k for k in by_regime if k != POW][0]
aP, aW = by_regime[POW], by_regime[WAR]

R["recomputed_arm_sizes"] = {
    "powell_clean_days": aP["n_days"], "powell_speech_days": aP["n_speech"],
    "powell_nonspeech_days": aP["n_nonspeech"],
    "warsh_clean_days": aW["n_days"], "warsh_speech_days": aW["n_speech"],
    "warsh_nonspeech_days": aW["n_nonspeech"],
    "warsh_prepask_panel_days": int((p.chair_regime == WAR).sum()),
}
say(f"   >>> LATER-REGIME SPEECH DAYS = {aW['n_speech']}   (skeptic threshold ~60: "
    f"{'BELOW' if aW['n_speech'] < 60 else 'above'})")
R["later_regime_speech_days"] = aW["n_speech"]
R["later_regime_speech_days_below_60"] = bool(aW["n_speech"] < 60)

# ---------------------------------------------------------------- (2) ratios + CI
say("")
say("=== (2) RATIOS, RATIO-OF-RATIOS, BOOTSTRAP CI (own seed) ===")

def boot_ratio(s, n, rng, nboot=N_BOOT):
    si = rng.integers(0, len(s), size=(nboot, len(s)))
    ni = rng.integers(0, len(n), size=(nboot, len(n)))
    return s[si].mean(axis=1) / n[ni].mean(axis=1)

bP = boot_ratio(aP["_s"], aP["_n"], rng)
bW = boot_ratio(aW["_s"], aW["_n"], rng)
rr_draws = bW / bP
rr_obs = aW["ratio"] / aP["ratio"]
ciP = [float(np.percentile(bP, 2.5)), float(np.percentile(bP, 97.5))]
ciW = [float(np.percentile(bW, 2.5)), float(np.percentile(bW, 97.5))]
ciRR = [float(np.percentile(rr_draws, 2.5)), float(np.percentile(rr_draws, 97.5))]
p_boot = float(2 * min((rr_draws <= 1).mean(), (rr_draws >= 1).mean()))

say(f"   Powell excess ratio = {aP['ratio']:.4f}  CI95 [{ciP[0]:.3f}, {ciP[1]:.3f}]")
say(f"   {WAR}  excess ratio = {aW['ratio']:.4f}  CI95 [{ciW[0]:.3f}, {ciW[1]:.3f}]")
say(f"   ratio-of-ratios     = {rr_obs:.4f}  CI95 [{ciRR[0]:.3f}, {ciRR[1]:.3f}]  "
    f"spans 1.0: {ciRR[0] < 1.0 < ciRR[1]}   two-sided boot p = {p_boot:.3f}")
say(f"   individual CIs span 1.0?  Powell {ciP[0]<1<ciP[1]}   {WAR} {ciW[0]<1<ciW[1]}")

R["powell_excess_ratio"] = aP["ratio"]; R["powell_ci95"] = ciP
R["warsh_excess_ratio"] = aW["ratio"]; R["warsh_ci95"] = ciW
R["ratio_of_ratios"] = float(rr_obs); R["ratio_of_ratios_ci95"] = ciRR
R["rr_ci_spans_one"] = bool(ciRR[0] < 1.0 < ciRR[1])
R["warsh_ci_spans_one"] = bool(ciW[0] < 1.0 < ciW[1])
R["boot_p_two_sided"] = p_boot

# permutation: shuffle speech labels within each regime
def perm_p(dP, dW, nperm=5000):
    obs = rr_obs
    sP = dP["is_speech_day"].to_numpy(bool); xP = dP["abs_d_rate_bp"].to_numpy(float)
    sW = dW["is_speech_day"].to_numpy(bool); xW = dW["abs_d_rate_bp"].to_numpy(float)
    cnt = 0
    for _ in range(nperm):
        lP = rng.permutation(sP); lW = rng.permutation(sW)
        rP = xP[lP].mean() / xP[~lP].mean()
        rW = xW[lW].mean() / xW[~lW].mean()
        if abs(np.log(rW / rP)) >= abs(np.log(obs)):
            cnt += 1
    return (cnt + 1) / (nperm + 1)

dP = C[C.chair_regime == POW]; dW = C[C.chair_regime == WAR]
pp = perm_p(dP, dW)
say(f"   permutation p (5,000 label shuffles inside each regime) = {pp:.3f}")
R["perm_p_two_sided"] = float(pp)

# ---------------------------------------------------------------- (3) MDE
say("")
say("=== (3) MDE at 80% power / alpha=0.05, recomputed analytically ===")

def se_log_mean(x):
    return float(x.std(ddof=1) / x.mean() / np.sqrt(len(x)))

def se_log_ratio(s, n):
    return float(np.sqrt(se_log_mean(s) ** 2 + se_log_mean(n) ** 2))

seP = se_log_ratio(aP["_s"], aP["_n"])
seW = se_log_ratio(aW["_s"], aW["_n"])
se_rr = float(np.sqrt(seP ** 2 + seW ** 2))
z_a, z_b = 1.959964, 0.8416212
mde = float(np.exp((z_a + z_b) * se_rr))
say(f"   SE(log excess ratio) Powell = {seP:.4f}   {WAR} = {seW:.4f}")
say(f"   SE(log ratio-of-ratios)     = {se_rr:.4f}")
say(f"   ANALYTIC MDE (ratio-of-ratios) at 80% power = {mde:.3f}")
say(f"   observed ratio-of-ratios                   = {rr_obs:.3f}")
say(f"   MDE > observed effect: {mde > rr_obs}")

# achieved power at the observed effect (analytic)
from math import erf, sqrt
def norm_cdf(z):
    return 0.5 * (1 + erf(z / sqrt(2)))
lam = abs(np.log(rr_obs)) / se_rr
power_obs = float(norm_cdf(lam - z_a) + norm_cdf(-lam - z_a))
say(f"   achieved power at observed effect (analytic) = {power_obs:.3f}")

R["se_log_rr"] = se_rr
R["mde_analytic_80pct"] = mde
R["observed_rr"] = float(rr_obs)
R["mde_exceeds_observed"] = bool(mde > rr_obs)
R["achieved_power_analytic"] = power_obs

# small simulation cross-check (500 draws) at rho=1 (size) and rho=mde (power)
def z_stat(sA, nA, sB, nB):
    lr = np.log(sB.mean() / nB.mean()) - np.log(sA.mean() / nA.mean())
    se = np.sqrt(se_log_ratio(sA, nA) ** 2 + se_log_ratio(sB, nB) ** 2)
    return lr / se

def sim(rho, nsim=600):
    poolA, poolB = aP["_n"], aW["_n"]
    rP = aP["ratio"]
    rej = 0
    for _ in range(nsim):
        sA = rng.choice(poolA, aP["n_speech"], replace=True) * rP
        nA = rng.choice(poolA, aP["n_nonspeech"], replace=True)
        sB = rng.choice(poolB, aW["n_speech"], replace=True) * (rP * rho)
        nB = rng.choice(poolB, aW["n_nonspeech"], replace=True)
        if abs(z_stat(sA, nA, sB, nB)) > z_a:
            rej += 1
    return rej / nsim

size1 = sim(1.0)
pow_mde = sim(mde)
pow_obs_sim = sim(rr_obs)
say(f"   sim cross-check: size at rho=1.00 -> {size1:.3f} (nominal 0.05)")
say(f"                    power at rho={mde:.2f} -> {pow_mde:.3f} (target 0.80)")
say(f"                    power at rho={rr_obs:.3f} -> {pow_obs_sim:.3f}")
R["sim_size_rho1"] = size1
R["sim_power_at_analytic_mde"] = pow_mde
R["sim_power_at_observed"] = pow_obs_sim

# how many more clean days would the later arm need?
say("")
say("   how long until this is answerable at the OBSERVED effect size?")
frac_speech = aW["n_speech"] / aW["n_days"]
cvS = aW["_s"].std(ddof=1) / aW["_s"].mean()
cvN = aW["_n"].std(ddof=1) / aW["_n"].mean()
target_lam = z_a + z_b
need = None
for nd in range(56, 8000):
    ns = max(2, int(round(nd * frac_speech))); nn = max(2, nd - ns)
    seW_h = np.sqrt(cvS ** 2 / ns + cvN ** 2 / nn)
    se_h = np.sqrt(seP ** 2 + seW_h ** 2)
    if abs(np.log(rr_obs)) / se_h >= target_lam:
        need = nd
        break
if need:
    say(f"   later arm needs ~{need} clean days (~{need/63:.1f} quarters) at rho={rr_obs:.3f}; has {aW['n_days']}")
    R["later_arm_clean_days_needed_at_observed_effect"] = int(need)
    R["later_arm_quarters_needed"] = round(need / 63.0, 1)
else:
    say("   >8000 clean days needed (effect too small to ever resolve at this vol)")
    R["later_arm_clean_days_needed_at_observed_effect"] = None

# ---------------------------------------------------------------- (4) BOUNDARY SHIFT
say("")
say("=== (4) BOUNDARY-SHIFT SENSITIVITY  (the check the original script never ran) ===")
say("    post-arm := date >= shifted transition; pre-arm := everything before it")
say("")
say(f"{'shift':>7s} {'date':>12s} | {'post_n':>6s} {'post_sp':>7s} {'post_ns':>7s} {'post_r':>7s} "
    f"| {'pre_n':>6s} {'pre_r':>7s} | {'rho':>7s} {'rho_CI95':>18s} {'spans1':>7s} {'MDE':>6s} {'verdict':>20s}")

BASE = pd.Timestamp("2026-05-22")
rows = []
for k in [-3, -2, -1, 0, 1, 2, 3]:
    d = BASE + pd.DateOffset(months=k)
    post = C[C.date >= d]
    pre = C[C.date < d]
    a_post = arm(post) if len(post) else None
    a_pre = arm(pre)
    if a_post is None or a_post["degenerate"] or not np.isfinite(a_post.get("ratio", np.nan)):
        npost = int(len(post)); nsp = int(post.is_speech_day.sum()) if len(post) else 0
        say(f"{k:>+7d} {str(d.date()):>12s} | {npost:6d} {nsp:7d} {npost-nsp:7d} {'--':>7s} "
            f"| {a_pre['n_days']:6d} {a_pre['ratio']:7.3f} | {'DEGENERATE (post arm too small to form a ratio)':>7s}")
        rows.append(dict(shift_months=k, date=str(d.date()), post_n=npost, post_speech=nsp,
                         post_nonspeech=npost - nsp, post_ratio=None, pre_n=int(a_pre["n_days"]),
                         pre_ratio=float(a_pre["ratio"]), rho=None, rho_ci95=[None, None],
                         spans_one=None, mde=None, verdict="degenerate"))
        continue
    bpost = boot_ratio(a_post["_s"], a_post["_n"], rng, nboot=8000)
    bpre = boot_ratio(a_pre["_s"], a_pre["_n"], rng, nboot=8000)
    rrd = bpost / bpre
    rr = a_post["ratio"] / a_pre["ratio"]
    c = [float(np.percentile(rrd, 2.5)), float(np.percentile(rrd, 97.5))]
    spans = bool(c[0] < 1.0 < c[1])
    se_pre = se_log_ratio(a_pre["_s"], a_pre["_n"])
    se_post = se_log_ratio(a_post["_s"], a_post["_n"])
    se_k = float(np.sqrt(se_pre ** 2 + se_post ** 2))
    mde_k = float(np.exp((z_a + z_b) * se_k))
    verdict = "undetermined_sample" if (spans or mde_k > rr) else "DETECTED"
    say(f"{k:>+7d} {str(d.date()):>12s} | {a_post['n_days']:6d} {a_post['n_speech']:7d} {a_post['n_nonspeech']:7d} "
        f"{a_post['ratio']:7.3f} | {a_pre['n_days']:6d} {a_pre['ratio']:7.3f} | {rr:7.3f} "
        f"[{c[0]:6.3f},{c[1]:6.3f}] {str(spans):>7s} {mde_k:6.3f} {verdict:>20s}")
    rows.append(dict(shift_months=k, date=str(d.date()), post_n=int(a_post["n_days"]),
                     post_speech=int(a_post["n_speech"]), post_nonspeech=int(a_post["n_nonspeech"]),
                     post_ratio=float(a_post["ratio"]), pre_n=int(a_pre["n_days"]),
                     pre_ratio=float(a_pre["ratio"]), rho=float(rr), rho_ci95=c,
                     spans_one=spans, mde=mde_k, verdict=verdict))

R["boundary_shift"] = rows
verds = [r["verdict"] for r in rows if r["verdict"] != "degenerate"]
say("")
say(f"   verdicts across non-degenerate shifts: {sorted(set(verds))}")
say(f"   any shift flips to DETECTED: {'DETECTED' in verds}")
R["boundary_any_shift_detected"] = bool("DETECTED" in verds)
R["boundary_verdict_set"] = sorted(set(verds))

post_ratios = [(r["shift_months"], r["post_ratio"]) for r in rows if r["post_ratio"] is not None]
say(f"   post-arm ratio vs shift: " + "  ".join(f"{k:+d}m={v:.3f}" for k, v in post_ratios))
rvals = [v for _, v in post_ratios]
say(f"   post-arm ratio range across shifts = [{min(rvals):.3f}, {max(rvals):.3f}]  "
    f"(monotone-in-earlier-shift: {rvals[0] >= rvals[-1]})")
R["post_arm_ratio_by_shift"] = {f"{k:+d}m": v for k, v in post_ratios}

# ---------------------------------------------------------------- direction stability
say("")
say("=== extra: is the DIRECTION ('higher under the later chair') stable? ===")
say("   sign of log(rho) across shifts:")
for r in rows:
    if r["rho"] is None:
        say(f"     {r['shift_months']:+d}m : degenerate")
    else:
        say(f"     {r['shift_months']:+d}m : rho={r['rho']:.3f}  {'UP' if r['rho']>1 else 'DOWN'}")
signs = [1 if r["rho"] > 1 else -1 for r in rows if r["rho"] is not None]
say(f"   all shifts agree in direction: {len(set(signs)) == 1}")
R["direction_agrees_across_shifts"] = bool(len(set(signs)) == 1)

# season-matched placebo, recomputed: same calendar window in prior years
say("")
say("=== extra: season-matched placebo, recomputed (22 May - 24 Aug of each year) ===")
plac = []
for yr in range(2019, 2026):
    lo = pd.Timestamp(f"{yr}-05-22"); hi = pd.Timestamp(f"{yr}-08-24")
    g = C[(C.date >= lo) & (C.date <= hi)]
    a = arm(g)
    if a["degenerate"]:
        continue
    plac.append((yr, a["ratio"], a["n_days"], a["n_speech"]))
    say(f"   {yr}: ratio={a['ratio']:.3f}  n={a['n_days']}  speech={a['n_speech']}")
pr = [v for _, v, _, _ in plac]
n_ge = sum(1 for v in pr if v >= aW["ratio"])
say(f"   later-regime window ratio {aW['ratio']:.3f}; {n_ge} of {len(pr)} prior summers were >= it "
    f"(one-sided rank p = {(n_ge+1)/(len(pr)+1):.3f})")
R["placebo_summer_ratios"] = {str(y): round(v, 4) for y, v, _, _ in plac}
R["placebo_n_ge"] = int(n_ge)
R["placebo_rank_p"] = float((n_ge + 1) / (len(pr) + 1))

# ---------------------------------------------------------------- self-test
say("")
say("=== self-test: inject a KNOWN 2.0x effect into the later arm; estimator must recover it ===")
Ct = C.copy()
mask = (Ct.chair_regime == WAR) & Ct.is_speech_day
Ct.loc[mask, "abs_d_rate_bp"] = Ct.loc[mask, "abs_d_rate_bp"] * 2.0
aWt = arm(Ct[Ct.chair_regime == WAR])
rr_t = aWt["ratio"] / aP["ratio"]
say(f"   injected 2.00x -> recovered ratio-of-ratios {rr_t:.3f} (expect ~{2*rr_obs:.3f})")
se_t = float(np.sqrt(seP ** 2 + se_log_ratio(aWt["_s"], aWt["_n"]) ** 2))
say(f"   would a 2.0x effect be DETECTED here? |z| = {abs(np.log(rr_t))/se_t:.2f} "
    f"({'yes' if abs(np.log(rr_t))/se_t > z_a else 'NO -- even a doubling is invisible'})")
R["selftest_injected_2x_recovered_rr"] = float(rr_t)
R["selftest_2x_detected"] = bool(abs(np.log(rr_t)) / se_t > z_a)

# ---------------------------------------------------------------- write
with open(os.path.join(OUT, "skeptic_regime_power_report.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
with open(os.path.join(OUT, "skeptic_regime_power_results.json"), "w", encoding="utf-8") as f:
    json.dump(R, f, indent=2, default=str)
say("")
say("wrote skeptic_regime_power_report.txt / skeptic_regime_power_results.json")
