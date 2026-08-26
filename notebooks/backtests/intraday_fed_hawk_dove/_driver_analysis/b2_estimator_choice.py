"""B2 -- does the CHOICE OF AGGREGATOR change the answer? plus denominator composition."""
import os
import numpy as np
import pandas as pd

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
HERE = r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_driver_analysis"
L = []


def say(s=""):
    print(s)
    L.append(str(s))


rng = np.random.default_rng(20260825)
p = pd.read_parquet(os.path.join(HERE, "panel_daily.parquet"))
if "date" not in p.columns:
    p = p.reset_index()
p["date"] = pd.to_datetime(p["date"])
clean = p[(~p.is_fomc_day.astype(bool)) & (~p.is_cpi_day.astype(bool)) & (~p.is_nfp_day.astype(bool))
          & p.abs_d_rate_bp.notna()].copy()

AGG = {
    "mean|d|            (author primary)": lambda x: np.mean(x),
    "median|d|          (author V4)": lambda x: np.median(x),
    "RMS  sqrt(mean d^2)": lambda x: np.sqrt(np.mean(x ** 2)),
    "trimmed mean 10%": lambda x: pd.Series(x).sort_values().iloc[int(.1 * len(x)):len(x) - int(.1 * len(x))].mean(),
    "geometric mean exp(mean log|d|)": lambda x: np.exp(np.mean(np.log(np.clip(x, 1e-6, None)))),
    "mean of winsorized@95pct": lambda x: np.clip(x, None, np.percentile(x, 95)).mean(),
    "80th pctile |d|": lambda x: np.percentile(x, 80),
}

say("=" * 96)
say("B2  METRIC-CHOICE ROBUSTNESS -- is rho an artifact of using the MEAN of a heavy-tailed |d|?")
say("=" * 96)
say(f"{'aggregator':38s} {'PowNum':>8s} {'PowDen':>8s} {'PowR':>6s} {'WarNum':>8s} {'WarDen':>8s} {'WarR':>6s} {'rho':>7s}")
rows = []
for nm, f in AGG.items():
    o = {}
    for r in ["Powell", "Warsh"]:
        d = clean[clean.chair_regime == r]
        s = d.loc[d.is_speech_day.astype(bool), "abs_d_rate_bp"].to_numpy(float)
        n = d.loc[~d.is_speech_day.astype(bool), "abs_d_rate_bp"].to_numpy(float)
        o[r] = (f(s), f(n), f(s) / f(n))
    rho = o["Warsh"][2] / o["Powell"][2]
    rows.append((nm, rho))
    say(f"{nm:38s} {o['Powell'][0]:8.3f} {o['Powell'][1]:8.3f} {o['Powell'][2]:6.3f} "
        f"{o['Warsh'][0]:8.3f} {o['Warsh'][1]:8.3f} {o['Warsh'][2]:6.3f} {rho:7.3f}")
rr = np.array([r for _, r in rows])
say(f"  rho across aggregators: min {rr.min():.3f}  max {rr.max():.3f}  -- all below the author's MDE 1.69: "
    f"{bool((rr < 1.69).all())}")

say()
say("-" * 96)
say("DENOMINATOR COMPOSITION -- are the 34 Warsh non-speech days a peculiar set?")
say("-" * 96)
for r in ["Powell", "Warsh"]:
    d = clean[clean.chair_regime == r]
    n = d[~d.is_speech_day.astype(bool)]
    dw = n.dow.value_counts(normalize=True).sort_index()
    say(f"  {r:7s} non-speech dow share Mon..Fri: {[round(dw.get(i,0),3) for i in range(5)]}   "
        f"mean days_to_fomc {n.days_to_fomc.mean():.1f}  median {n.days_to_fomc.median():.0f}")
    s = d[d.is_speech_day.astype(bool)]
    dws = s.dow.value_counts(normalize=True).sort_index()
    say(f"  {r:7s} speech     dow share Mon..Fri: {[round(dws.get(i,0),3) for i in range(5)]}   "
        f"mean days_to_fomc {s.days_to_fomc.mean():.1f}")

# dow-matched ratio: reweight non-speech days to the speech-day dow distribution, within regime
say()
say("  dow-REWEIGHTED excess ratio (non-speech days reweighted to the speech-day day-of-week mix):")
out = {}
for r in ["Powell", "Warsh"]:
    d = clean[clean.chair_regime == r]
    s = d[d.is_speech_day.astype(bool)]
    n = d[~d.is_speech_day.astype(bool)]
    wsp = s.dow.value_counts(normalize=True)
    num = s.abs_d_rate_bp.mean()
    den = 0.0
    tot = 0.0
    for dow, wt in wsp.items():
        sub = n[n.dow == dow]
        if len(sub):
            den += wt * sub.abs_d_rate_bp.mean()
            tot += wt
    den /= tot
    out[r] = num / den
    say(f"    {r:7s} num {num:.3f}  dow-matched den {den:.3f}  ratio {num/den:.3f}")
say(f"    rho(dow-matched) = {out['Warsh']/out['Powell']:.3f}")

# what does the 2026 within-year comparison look like (no cross-vol-regime issue at all)?
say()
say("  WITHIN-2026 only (ambient vol identical by construction, no normalization needed):")
d26 = clean[clean.year == 2026]
for lbl, sub in [("2026 pre  (Powell)", d26[d26.chair_regime == "Powell"]),
                 ("2026 post (Warsh) ", d26[d26.chair_regime == "Warsh"])]:
    s = sub.loc[sub.is_speech_day.astype(bool), "abs_d_rate_bp"]
    n = sub.loc[~sub.is_speech_day.astype(bool), "abs_d_rate_bp"]
    say(f"    {lbl}  n={len(sub):3d} sp={len(s):3d}  num {s.mean():.3f}  den {n.mean():.3f}  "
        f"ratio {s.mean()/n.mean():.3f}  excess {s.mean()-n.mean():+.3f} bp")

# SE of the Warsh within-regime excess (bp) -- how many SEs is +0.570?
w = clean[clean.chair_regime == "Warsh"]
s = w.loc[w.is_speech_day.astype(bool), "abs_d_rate_bp"].to_numpy(float)
n = w.loc[~w.is_speech_day.astype(bool), "abs_d_rate_bp"].to_numpy(float)
se = np.sqrt(s.var(ddof=1) / len(s) + n.var(ddof=1) / len(n))
say()
say(f"  Warsh within-regime excess = {s.mean()-n.mean():+.3f} bp, SE {se:.3f} -> t = {(s.mean()-n.mean())/se:+.2f} "
    f"(Welch, n={len(s)}/{len(n)})  -- consistent with the author's p 0.38")

with open(os.path.join(HERE, "b2_estimator_choice.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(L))
print("\nwrote b2_estimator_choice.txt")
