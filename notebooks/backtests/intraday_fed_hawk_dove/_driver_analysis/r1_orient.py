import sys, json
sys.path.append(r"C:\Users\chris\clee\ARBS")
import pandas as pd, numpy as np

D = r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_driver_analysis"
p = pd.read_parquet(D + r"\panel_daily.parquet")

DOWN = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri"}

# ---- 1. DOW clustering of speeches, and DOW vol profile ----
print("=" * 78)
print("DAY-OF-WEEK: speech clustering vs vol profile (FULL PANEL, d defined)")
print("=" * 78)
q = p.dropna(subset=["d_rate_bp"]).copy()
q["downame"] = q["dow"].map(DOWN)
g = q.groupby("dow").agg(
    n=("d_rate_bp", "size"),
    p_speech=("is_speech_day", "mean"),
    mean_nspk=("n_speakers", "mean"),
    mean_absd=("abs_d_rate_bp", "mean"),
    med_absd=("abs_d_rate_bp", "median"),
    var_d=("d_rate_bp", "var"),
)
g.index = [DOWN[i] for i in g.index]
print(g.round(4).to_string())
print()
print("corr across 5 DOW cells: p_speech vs mean_absd =",
      round(np.corrcoef(g["p_speech"], g["mean_absd"])[0, 1], 4))
print("corr across 5 DOW cells: p_speech vs var_d     =",
      round(np.corrcoef(g["p_speech"], g["var_d"])[0, 1], 4))

# ---- 2. rung (c) mask reconstruction ----
print()
print("=" * 78)
print("RUNG (c) reconstruction: ex-FOMC, ex-CPI, ex-NFP")
print("=" * 78)
c = q[~q["is_fomc_day"] & ~q["is_cpi_day"] & ~q["is_nfp_day"]].copy()
print("n rung(c) =", len(c), " speech =", int(c["is_speech_day"].sum()),
      " nonspeech =", int((~c["is_speech_day"]).sum()))
sp = c[c["is_speech_day"]]["d_rate_bp"]
ns = c[~c["is_speech_day"]]["d_rate_bp"]
print("share_days_speech   =", round(len(sp) / len(c), 4), " (claim 0.4636)")
ss_sp = (sp ** 2).sum(); ss_ns = (ns ** 2).sum()
print("share_sumsq_speech  =", round(ss_sp / (ss_sp + ss_ns), 4), " (claim 0.3363)")
print("concentration       =", round((ss_sp / (ss_sp + ss_ns)) / (len(sp) / len(c)), 4), " (claim 0.725)")
print("var_ratio           =", round(sp.var() / ns.var(), 4), " (claim 0.586)")
print("mean|d| ratio       =", round(sp.abs().mean() / ns.abs().mean(), 4), " (claim 1.012)")
print("med|d| ratio        =", round(sp.abs().median() / ns.abs().median(), 4), " (claim 1.229)")

# ---- 3. DOW composition of the two arms in rung (c) ----
print()
print("DOW composition of the two arms in rung (c):")
tab = pd.crosstab(c["dow"].map(DOWN), c["is_speech_day"], normalize="columns")
tab.columns = ["nonspeech_share", "speech_share"]
tab["diff"] = tab["speech_share"] - tab["nonspeech_share"]
print(tab.round(4).to_string())

# ---- 4. IMM roll days: which arm? ----
print()
print("=" * 78)
print("IMM ROLL DAYS")
print("=" * 78)
rolls = q[q["is_imm_roll"]]
print("n roll rows:", len(rolls))
print("  of which speech    :", int(rolls["is_speech_day"].sum()))
print("  of which non-speech:", int((~rolls["is_speech_day"]).sum()))
print("  mean|d| roll days  :", round(rolls["abs_d_rate_bp"].mean(), 3))
print("  mean|d| other days :", round(q[~q["is_imm_roll"]]["abs_d_rate_bp"].mean(), 3))
print("  var roll / var other:", round(rolls["d_rate_bp"].var() / q[~q["is_imm_roll"]]["d_rate_bp"].var(), 3))
print()
print("Largest 15 |d| in whole panel, with flags:")
top = q.nlargest(15, "abs_d_rate_bp")[
    ["d_rate_bp", "is_speech_day", "n_speakers", "is_fomc_day", "is_cpi_day",
     "is_nfp_day", "is_imm_roll", "is_blackout", "dow"]]
top["downame"] = top["dow"].map(DOWN)
print(top.drop(columns=["dow"]).round(3).to_string())

# ---- 5. placebo series availability ----
print()
print("=" * 78)
print("PLACEBO SERIES available in rates_daily")
print("=" * 78)
r = pd.read_parquet(D + r"\rates_daily.parquet")
print(list(r.columns))
print("non-null counts:")
print(r.notna().sum().to_string())
