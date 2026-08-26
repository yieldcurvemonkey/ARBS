"""Independent metric-choice / measurement audit of Analysis B (chair regime split).

Adversarial re-computation. Writes b1_metric_audit.txt next to this file.
Creates no other files; modifies nothing tracked.
"""
import os
import sys
import json
import ast
import numpy as np
import pandas as pd

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

HERE = r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_driver_analysis"
PARENT = r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove"
OUT = os.path.join(HERE, "b1_metric_audit.txt")

LINES = []


def say(s=""):
    print(s)
    LINES.append(str(s))


rng = np.random.default_rng(20260825)

# ----------------------------------------------------------------------------
say("=" * 96)
say("B1  INDEPENDENT METRIC AUDIT -- Analysis B chair regime split")
say("=" * 96)

panel = pd.read_parquet(os.path.join(HERE, "panel_daily.parquet"))
if "date" not in panel.columns:
    panel = panel.reset_index()
    if "date" not in panel.columns:
        panel = panel.rename(columns={panel.columns[0]: "date"})
panel["date"] = pd.to_datetime(panel["date"])
say(f"panel rows {len(panel)}  cols {len(panel.columns)}  span {panel.date.min().date()} .. {panel.date.max().date()}")

# ---------------------------------------------------------------- CONTROL ---
say()
say("-" * 96)
say("[CONTROL] reproduce the author's four cell means from scratch")
say("-" * 96)

clean = panel[
    (~panel["is_fomc_day"].astype(bool))
    & (~panel["is_cpi_day"].astype(bool))
    & (~panel["is_nfp_day"].astype(bool))
    & panel["abs_d_rate_bp"].notna()
].copy()
say(f"clean sample (ex-FOMC/CPI/NFP, |d| present) = {len(clean)}   author said 1672   match={len(clean)==1672}")


def arm(df):
    s = df.loc[df["is_speech_day"].astype(bool), "abs_d_rate_bp"].to_numpy(float)
    n = df.loc[~df["is_speech_day"].astype(bool), "abs_d_rate_bp"].to_numpy(float)
    return dict(n_days=len(df), ns=len(s), nn=len(n), num=s.mean(), den=n.mean(),
                ratio=s.mean() / n.mean(), s=s, n=n)


A = {r: arm(clean[clean["chair_regime"] == r]) for r in ["Powell", "Warsh"]}
AUTH = {"Powell": (3.847, 3.824, 1.006, 1616, 753), "Warsh": (3.722, 3.153, 1.181, 56, 22)}
ctl_ok = True
for r in ["Powell", "Warsh"]:
    a = A[r]
    an, ad, ar, and_, ans = AUTH[r]
    ok = (abs(a["num"] - an) < 0.002 and abs(a["den"] - ad) < 0.002 and abs(a["ratio"] - ar) < 0.002
          and a["n_days"] == and_ and a["ns"] == ans)
    ctl_ok &= ok
    say(f"  {r:7s} n={a['n_days']:5d} sp={a['ns']:4d} nsp={a['nn']:4d}  "
        f"num(mean|d| speech)={a['num']:.4f} (author {an})  den(non-speech)={a['den']:.4f} (author {ad})  "
        f"ratio={a['ratio']:.4f} (author {ar})   MATCH={ok}")
rho = A["Warsh"]["ratio"] / A["Powell"]["ratio"]
say(f"  ratio-of-ratios rho = {rho:.4f}   (author 1.174)   CONTROL_PASS={ctl_ok}")
if not ctl_ok:
    say("  *** CONTROL FAILED -- everything below is meaningless. STOP. ***")

# --------------------------------------------------------- NORMALIZATION ----
say()
say("-" * 96)
say("[1] NORMALIZATION -- did the ratio actually lead, and what drives rho?")
say("-" * 96)
num_ratio = A["Warsh"]["num"] / A["Powell"]["num"]
den_ratio = A["Warsh"]["den"] / A["Powell"]["den"]
say(f"  rho = (Warsh num / Powell num) / (Warsh den / Powell den)")
say(f"      = {num_ratio:.4f} / {den_ratio:.4f} = {num_ratio/den_ratio:.4f}   (identity check vs rho: {abs(num_ratio/den_ratio - rho) < 1e-9})")
say(f"  NUMERATOR   moves {100*(num_ratio-1):+.1f}%  across the handover (speech-day |d| 3.85 -> 3.72 bp)")
say(f"  DENOMINATOR moves {100*(den_ratio-1):+.1f}%  across the handover (non-speech |d| 3.82 -> 3.15 bp)")
say(f"  log decomposition: share of log(rho) from the numerator = {np.log(num_ratio)/np.log(rho)*100:.1f}%,"
    f" from the denominator = {-np.log(den_ratio)/np.log(rho)*100:.1f}%")
say("  -> the entire directional signal is a FALL IN THE DENOMINATOR, not a rise in the numerator.")

# grep the report for whether a raw difference drove the verdict
rep = open(os.path.join(HERE, "regime_split_report.txt"), encoding="utf-8", errors="replace").read()
res = json.load(open(os.path.join(HERE, "regime_split_results.json"), encoding="utf-8"))
say(f"  report labels the raw cross-regime diff 'SECONDARY (subordinate)': {'SECONDARY (subordinate)' in rep}")
say(f"  report contains an explicit V3 mutation removing the normalization      : {'[V3] MUTATION' in rep}")
say(f"  verdict string in report                                                : "
    f"{[l for l in rep.splitlines() if l.startswith('VERDICT')][:1]}")

# ---------------------------------------------------------------- UNITS -----
say()
say("-" * 96)
say("[5] UNITS -- is d_rate_bp really basis points, in BOTH regimes?")
say("-" * 96)
p = panel.sort_values("date").reset_index(drop=True)
recon = p["imm3x4_rate"].diff() * 100.0
m = p["d_rate_bp"].notna() & recon.notna()
err = (p.loc[m, "d_rate_bp"] - recon[m]).abs()
say(f"  |d_rate_bp - 100*diff(imm3x4_rate)|  max={err.max():.3e}  mean={err.mean():.3e}  n={m.sum()}")
for r in ["Powell", "Warsh"]:
    mm = m & (p["chair_regime"] == r)
    say(f"    {r:7s} max err {(p.loc[mm,'d_rate_bp'] - recon[mm]).abs().max():.3e}   "
        f"level imm3x4_rate mean {p.loc[mm,'imm3x4_rate'].mean():.3f} (percent-scale rate)  "
        f"mean|d| {p.loc[mm,'abs_d_rate_bp'].mean():.3f} bp")
say(f"  100x factor test: is mean|d| in the plausible bp band 0.3-10 in both regimes? "
    f"{0.3 < A['Powell']['num'] < 10 and 0.3 < A['Warsh']['num'] < 10}")
say(f"  sqrt(252)=15.87 test: Powell/Warsh num ratio {num_ratio:.3f} -- nowhere near 15.87 or 1/15.87. OK")

# ------------------------------------------------------- FILTER INTEGRITY ---
say()
say("-" * 96)
say("[3] FILTER INTEGRITY -- do the ex-CPI/NFP/FOMC flags actually FIRE in the Warsh window?")
say("-" * 96)
w = panel[panel["chair_regime"] == "Warsh"]
say(f"  Warsh regime panel days = {len(w)}   clean = {A['Warsh']['n_days']}   excluded = {len(w)-A['Warsh']['n_days']}"
    f" (+ {int(w['abs_d_rate_bp'].isna().sum())} NaN |d|)")
say(f"    is_cpi_day  in window: {int(w['is_cpi_day'].sum())}   dates {list(pd.to_datetime(w.loc[w.is_cpi_day.astype(bool),'date']).dt.date)}")
say(f"    is_nfp_day  in window: {int(w['is_nfp_day'].sum())}   dates {list(pd.to_datetime(w.loc[w.is_nfp_day.astype(bool),'date']).dt.date)}")
say(f"    is_fomc_day in window: {int(w['is_fomc_day'].sum())}  dates {list(pd.to_datetime(w.loc[w.is_fomc_day.astype(bool),'date']).dt.date)}")
say(f"    is_blackout in window: {int(w['is_blackout'].sum())}")
yr = panel.groupby("year")[["is_cpi_day", "is_nfp_day", "is_fomc_day"]].sum()
say("  per-year flag counts (a dead flag in the last year would be a vacuous filter):")
for k, v in yr.iterrows():
    say(f"    {k}  cpi={int(v.is_cpi_day):3d}  nfp={int(v.is_nfp_day):3d}  fomc={int(v.is_fomc_day):3d}")

# ----------------------------------------------------------- DENOMINATOR ----
say()
say("-" * 96)
say("[2] DENOMINATOR INSTABILITY -- levels, sampling error, fragility, and mix")
say("-" * 96)
for r in ["Powell", "Warsh"]:
    a = A[r]
    n = a["n"]
    se = n.std(ddof=1) / np.sqrt(len(n))
    bs = np.array([rng.choice(n, len(n), replace=True).mean() for _ in range(10000)])
    say(f"  {r:7s} DENOMINATOR mean|d| non-speech = {n.mean():.3f} bp   sd={n.std(ddof=1):.3f}  n={len(n)}  "
        f"SE={se:.3f}  boot95=[{np.percentile(bs,2.5):.3f},{np.percentile(bs,97.5):.3f}]  "
        f"median={np.median(n):.3f}")
    s = a["s"]
    ses = s.std(ddof=1) / np.sqrt(len(s))
    say(f"  {r:7s} NUMERATOR   mean|d| speech     = {s.mean():.3f} bp   sd={s.std(ddof=1):.3f}  n={len(s)}  "
        f"SE={ses:.3f}  median={np.median(s):.3f}")
say(f"  -> the Warsh denominator's own 95% CI is roughly +-{1.96*A['Warsh']['n'].std(ddof=1)/np.sqrt(len(A['Warsh']['n'])):.2f} bp on a {A['Warsh']['den']:.2f} bp mean:"
    f" a {100*1.96*A['Warsh']['n'].std(ddof=1)/np.sqrt(len(A['Warsh']['n']))/A['Warsh']['den']:.0f}% band.")

# leave-one-out fragility of the 34-day denominator
nW = A["Warsh"]["n"]
loo_den = np.array([np.delete(nW, i).mean() for i in range(len(nW))])
loo_rho = (A["Warsh"]["num"] / loo_den) / A["Powell"]["ratio"]
say(f"  leave-one-out on the 34 Warsh non-speech days: denominator range [{loo_den.min():.3f},{loo_den.max():.3f}], "
    f"rho range [{loo_rho.min():.3f},{loo_rho.max():.3f}]")
top = np.sort(nW)[::-1][:5]
say(f"  5 largest Warsh non-speech |d| (bp): {np.round(top,2).tolist()}   "
    f"drop the single largest -> den {np.delete(nW, np.argmax(nW)).mean():.3f}, rho {(A['Warsh']['num']/np.delete(nW,np.argmax(nW)).mean())/A['Powell']['ratio']:.3f}")
# also LOO on the 22 speech days
sW = A["Warsh"]["s"]
loo_num = np.array([np.delete(sW, i).mean() for i in range(len(sW))])
loo_rho2 = (loo_num / A["Warsh"]["den"]) / A["Powell"]["ratio"]
say(f"  leave-one-out on the 22 Warsh speech days:     numerator   range [{loo_num.min():.3f},{loo_num.max():.3f}], "
    f"rho range [{loo_rho2.min():.3f},{loo_rho2.max():.3f}]")

# is the Warsh denominator actually COLLAPSED, or ordinary for a summer?
say()
say("  is the Warsh denominator anomalously LOW, or ordinary? season-matched (22 May .. 24 Aug) non-speech mean|d|:")
sm = []
for y in range(2019, 2027):
    lo = pd.Timestamp(f"{y}-05-22")
    hi = pd.Timestamp(f"{y}-08-24")
    d = clean[(clean.date >= lo) & (clean.date <= hi)]
    if len(d) < 10:
        continue
    nn = d.loc[~d.is_speech_day.astype(bool), "abs_d_rate_bp"]
    ss = d.loc[d.is_speech_day.astype(bool), "abs_d_rate_bp"]
    # rest-of-year denominator for the same year
    ry = clean[(clean.year == y) & ~((clean.date >= lo) & (clean.date <= hi))]
    rn = ry.loc[~ry.is_speech_day.astype(bool), "abs_d_rate_bp"]
    sm.append(dict(year=y, n=len(d), nsp=len(nn), den_summer=nn.mean(), num_summer=ss.mean(),
                   ratio=ss.mean() / nn.mean(), den_restofyear=rn.mean() if len(rn) else np.nan,
                   den_summer_over_rest=nn.mean() / rn.mean() if len(rn) else np.nan))
sm = pd.DataFrame(sm)
say(sm.round(3).to_string(index=False))
say(f"  Warsh 2026 summer denominator {A['Warsh']['den']:.3f} vs 2025 summer {sm.loc[sm.year==2025,'den_summer'].iloc[0]:.3f} "
    f"and 2024 summer {sm.loc[sm.year==2024,'den_summer'].iloc[0]:.3f}")

# denominator MIX: blackout share among non-speech days
say()
say("  MIX of the denominator -- are Warsh non-speech days disproportionately BLACKOUT (mechanically quiet)?")
for r in ["Powell", "Warsh"]:
    d = clean[clean.chair_regime == r]
    nsp = d[~d.is_speech_day.astype(bool)]
    spd = d[d.is_speech_day.astype(bool)]
    bl = nsp.is_blackout.astype(bool)
    say(f"    {r:7s} non-speech days {len(nsp):4d}: blackout {int(bl.sum()):4d} ({100*bl.mean():5.1f}%)  "
        f"mean|d| blackout {nsp.loc[bl,'abs_d_rate_bp'].mean():.3f}  non-blackout {nsp.loc[~bl,'abs_d_rate_bp'].mean():.3f}")
    say(f"    {r:7s} speech     days {len(spd):4d}: blackout {int(spd.is_blackout.astype(bool).sum()):4d} "
        f"({100*spd.is_blackout.astype(bool).mean():5.1f}%)")
# re-run the ratio restricting BOTH sides to non-blackout days
say("  ratio recomputed on NON-BLACKOUT days only (removes the blackout-mix confound):")
sub = clean[~clean.is_blackout.astype(bool)]
Anb = {r: arm(sub[sub.chair_regime == r]) for r in ["Powell", "Warsh"]}
for r in ["Powell", "Warsh"]:
    a = Anb[r]
    say(f"    {r:7s} n={a['n_days']:4d} sp={a['ns']:4d} num={a['num']:.3f} den={a['den']:.3f} ratio={a['ratio']:.3f}")
say(f"    rho(non-blackout) = {Anb['Warsh']['ratio']/Anb['Powell']['ratio']:.3f}   (primary rho {rho:.3f})")

# ------------------------------------------------------------ COMPOSITION ---
say()
say("-" * 96)
say("[4] SELECTION / COMPOSITION -- who is speaking in each regime?")
say("-" * 96)
def spk_list(x):
    if not isinstance(x, str) or not x.strip():
        return []
    return [t.strip() for t in x.split(",") if t.strip()]


clean = clean.copy()
clean["spk"] = clean["speakers"].apply(spk_list)
clean["has_powell"] = clean["spk"].apply(lambda L: any("Powell" in s for s in L))
for r in ["Powell", "Warsh"]:
    d = clean[clean.chair_regime == r]
    sp = d[d.is_speech_day.astype(bool)]
    say(f"  {r:7s} speech days {len(sp):4d}: containing the sitting CHAIR (Powell) {int(sp.has_powell.sum()):4d} "
        f"({100*sp.has_powell.mean():5.1f}%)")
    cnt = pd.Series([s for L in sp["spk"] for s in L]).value_counts()
    say(f"    top speakers: {', '.join(f'{k}:{v}' for k, v in cnt.head(8).items())}")
    say(f"    distinct speakers {cnt.size}, mean n_speakers/day {sp['n_speakers'].mean():.2f}, "
        f"n_press_conf total {int(d['n_press_conf'].sum())}")
# chair-day effect inside Powell
pw = clean[clean.chair_regime == "Powell"]
pw_sp = pw[pw.is_speech_day.astype(bool)]
say(f"  Powell regime: mean|d| on CHAIR speech days {pw_sp.loc[pw_sp.has_powell,'abs_d_rate_bp'].mean():.3f} "
    f"(n={int(pw_sp.has_powell.sum())})  vs NON-chair speech days "
    f"{pw_sp.loc[~pw_sp.has_powell,'abs_d_rate_bp'].mean():.3f} (n={int((~pw_sp.has_powell).sum())})")
pw_nonchair = pd.concat([pw_sp[~pw_sp.has_powell], pw[~pw.is_speech_day.astype(bool)]])
a_nc = arm(pw_nonchair)
say(f"  APPLES-TO-APPLES: Powell regime with CHAIR speech days DROPPED -> "
    f"num={a_nc['num']:.3f} den={a_nc['den']:.3f} ratio={a_nc['ratio']:.3f} (n_sp={a_nc['ns']})")
say(f"     rho vs that reference = {A['Warsh']['ratio']/a_nc['ratio']:.3f}   (primary rho {rho:.3f})")

# ------------------------------------------------ INTRADAY INSTRUMENT CHECK -
say()
say("-" * 96)
say("[3b] IS |close-to-close d| THE RIGHT INFORMATION PROXY? day-level daily-vs-intraday check")
say("-" * 96)
nav = pd.read_csv(os.path.join(PARENT, "nav_closed.csv"))
nav["opened_at"] = pd.to_datetime(nav["opened_at"], utc=True, format="mixed").dt.tz_convert("America/New_York")
nav["closed_at"] = pd.to_datetime(nav["closed_at"], utc=True, format="mixed").dt.tz_convert("America/New_York")


def bpv_of(s):
    try:
        i = s.index("'bpv':")
        return float(s[i + 6:].split(",")[0].strip())
    except Exception:
        return np.nan


nav["bpv"] = nav["source_query"].apply(bpv_of)
nav["move_bp_signed"] = nav["realized_pnl"] / nav["bpv"]
nav["abs_move_bp"] = nav["move_bp_signed"].abs()
nav["day"] = nav["opened_at"].dt.normalize().dt.tz_localize(None)
say(f"  nav_closed.csv: {len(nav)} FED event trades, {nav.day.min().date()} .. {nav.day.max().date()}, "
    f"bpv values {sorted(nav.bpv.unique())}")
say(f"  intraday 3h event |move| bp: mean {nav.abs_move_bp.mean():.3f} median {nav.abs_move_bp.median():.3f} "
    f"max {nav.abs_move_bp.max():.3f}  -- same bp order as the daily panel (units cross-check)")
post = nav[nav.day >= pd.Timestamp("2026-05-22")]
say(f"  post-2026-05-22 intraday trades: {len(post)}  (author claimed 0)")

g = nav.groupby("day").agg(intr_mean=("abs_move_bp", "mean"), intr_max=("abs_move_bp", "max"),
                           intr_sum_abs=("abs_move_bp", "sum"), n_ev=("abs_move_bp", "size")).reset_index()
j = g.merge(panel[["date", "abs_d_rate_bp", "is_speech_day", "is_fomc_day", "is_cpi_day", "is_nfp_day",
                   "chair_regime", "n_speakers"]],
            left_on="day", right_on="date", how="inner")
jc = j[(~j.is_fomc_day.astype(bool)) & (~j.is_cpi_day.astype(bool)) & (~j.is_nfp_day.astype(bool))
       & j.abs_d_rate_bp.notna()]
say(f"  day-level join: {len(j)} days with intraday events matched to the panel; clean {len(jc)}")
for col in ["intr_mean", "intr_max"]:
    pr = np.corrcoef(jc[col], jc["abs_d_rate_bp"])[0, 1]
    sr = pd.Series(jc[col]).corr(pd.Series(jc["abs_d_rate_bp"]), method="spearman")
    say(f"    corr(daily |d|, {col})  pearson {pr:.3f}   spearman {sr:.3f}   n={len(jc)}")
say(f"    -> daily |close-to-close| explains only R^2={np.corrcoef(jc['intr_max'], jc['abs_d_rate_bp'])[0,1]**2:.3f} "
    f"of the day-level variation in the intraday EVENT-WINDOW move.")
# how often does a big intraday move sit inside a small daily move (offsetting intraday moves)?
hi_intr = jc["intr_max"] >= jc["intr_max"].quantile(0.75)
lo_day = jc["abs_d_rate_bp"] <= jc["abs_d_rate_bp"].quantile(0.25)
say(f"    days in the TOP quartile of intraday event |move| that are ALSO in the BOTTOM quartile of daily |d|: "
    f"{int((hi_intr & lo_day).sum())} of {int(hi_intr.sum())} ({100*(hi_intr&lo_day).mean()/max(hi_intr.mean(),1e-9):.1f}%) "
    f"-- offsetting/absorbed intraday information invisible to the daily metric")
# ratio-of-ratios using the intraday instrument is impossible post-transition; state it
say(f"    post-transition intraday observations = {len(post)} -> the intraday instrument CANNOT arbitrate the regime split.")

# ------------------------------------------------------------------ WRAP ----
say()
say("-" * 96)
say("SUMMARY OF RECOMPUTED NUMBERS")
say("-" * 96)
say(f"  Powell  num {A['Powell']['num']:.3f}  den {A['Powell']['den']:.3f}  ratio {A['Powell']['ratio']:.3f}  (n {A['Powell']['ns']}/{A['Powell']['nn']})")
say(f"  Warsh   num {A['Warsh']['num']:.3f}  den {A['Warsh']['den']:.3f}  ratio {A['Warsh']['ratio']:.3f}  (n {A['Warsh']['ns']}/{A['Warsh']['nn']})")
say(f"  rho {rho:.3f} = num_ratio {num_ratio:.3f} / den_ratio {den_ratio:.3f}")
say(f"  CONTROL_PASS {ctl_ok}")

with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(LINES))
print(f"\nwrote {OUT}")
