import sys
import pandas as pd
import numpy as np

sys.path.append(r"C:\Users\chris\clee\ARBS")
pd.set_option("display.width", 240)
pd.set_option("display.max_columns", 60)

OUT = r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_driver_analysis"
p = pd.read_parquet(OUT + r"\panel_daily.parquet")

print("=== 2019-06-20 .. 2019-07-20 imm3x4 / ON ===")
w = p.loc["2019-06-20":"2019-07-20", ["imm3x4_rate", "d_rate_bp", "on_sofr_rate", "n_speakers"]]
print(w.to_string())

print()
print("=== how much of total sum(d^2) do the top-k days carry? ===")
d2 = (p["d_rate_bp"] ** 2).dropna().sort_values(ascending=False)
tot = d2.sum()
for k in [1, 2, 3, 5, 10, 20, 50]:
    print(f"  top {k:3d} days = {d2.head(k).sum()/tot*100:5.1f}% of sum(d^2)")

print()
print("=== rung (c) sample composition ===")
mc = ~(p.is_fomc_day | p.is_cpi_day | p.is_nfp_day) & p.d_rate_bp.notna()
sub = p[mc]
print("n =", len(sub), " speech", int(sub.is_speech_day.sum()), " nonspeech", int((~sub.is_speech_day).sum()))
print("  imm_roll in speech arm   :", int((sub.is_imm_roll & sub.is_speech_day).sum()))
print("  imm_roll in nonspeech arm:", int((sub.is_imm_roll & ~sub.is_speech_day).sum()))
print("  blackout in speech arm   :", int((sub.is_blackout & sub.is_speech_day).sum()), "/", int(sub.is_speech_day.sum()))
print("  blackout in nonspeech arm:", int((sub.is_blackout & ~sub.is_speech_day).sum()), "/", int((~sub.is_speech_day).sum()))

print()
print("=== quick rung-(c) headline (mean|d|, median|d|, var) ===")
for lab, mm in [("speech", sub.is_speech_day), ("nospeech", ~sub.is_speech_day)]:
    s = sub.loc[mm, "abs_d_rate_bp"]
    print(f"  {lab:9s} n={len(s):5d} mean|d|={s.mean():7.3f} med|d|={s.median():6.3f} var={sub.loc[mm,'d_rate_bp'].var():8.2f}")

print()
print("=== days_to_fomc distribution by arm on rung (c) ===")
print(sub.groupby("is_speech_day")["days_to_fomc"].describe().to_string())
