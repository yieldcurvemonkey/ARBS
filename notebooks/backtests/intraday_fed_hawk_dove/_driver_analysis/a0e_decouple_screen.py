"""Rule-based screen for short-end curve-build defects in the target series.

RULE (fixed before looking at results, applied to the whole span):
  a day is DECOUPLED if  |d_imm| > 20bp  AND  |d_imm| > 5 * max(|d_2y|, |d_5y|).
A 3m forward starting ~3m out cannot move 20bp+ on a day the 2y and 5y barely move,
unless the slot rolled (is_imm_roll) -- so roll days are reported separately.
"""
import sys
import pandas as pd

sys.path.append(r"C:\Users\chris\clee\ARBS")
pd.set_option("display.width", 240)
pd.set_option("display.max_columns", 40)

OUT = r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_driver_analysis"
r = pd.read_parquet(OUT + r"\rates_daily.parquet")
p = pd.read_parquet(OUT + r"\panel_daily.parquet")

d = (r.diff() * 100.0)
d.columns = ["d_1d", "d_2y", "d_5y", "d_imm"]
d["max_long"] = d[["d_2y", "d_5y"]].abs().max(axis=1)
d["is_imm_roll"] = p["is_imm_roll"]
d["is_speech_day"] = p["is_speech_day"]

flag = (d.d_imm.abs() > 20) & (d.d_imm.abs() > 5 * d.max_long)
print("=== DECOUPLED days (|d_imm|>20bp and >5x the 2y/5y move) ===")
print(d.loc[flag].round(2).to_string())
print()
print("total flagged:", int(flag.sum()), " of which IMM-roll days:", int((flag & d.is_imm_roll).sum()))
print("flagged NON-roll days:", int((flag & ~d.is_imm_roll).sum()),
      " speech:", int((flag & ~d.is_imm_roll & d.is_speech_day).sum()))
print()
print("=== sanity: the 10 largest |d_imm| with their 2y/5y companions ===")
print(d.assign(a=d.d_imm.abs()).sort_values("a", ascending=False).head(12).round(2).to_string())
print()
print("=== all-year: correlation of d_imm with d_2y, by year (a decoupled short end shows up as a low year) ===")
cc = d.dropna().groupby(d.dropna().index.year).apply(
    lambda g: pd.Series({"n": len(g), "corr_imm_2y": g.d_imm.corr(g.d_2y),
                         "beta_imm_on_2y": g.d_imm.cov(g.d_2y) / g.d_2y.var()}), include_groups=False)
print(cc.round(3).to_string())
