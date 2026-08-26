import sys
import pandas as pd
import numpy as np

sys.path.append(r"C:\Users\chris\clee\ARBS")
pd.set_option("display.width", 240)
pd.set_option("display.max_columns", 60)

OUT = r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_driver_analysis"
p = pd.read_parquet(OUT + r"\panel_daily.parquet")

print("=== 15 largest |d_rate_bp| ===")
cols = ["d_rate_bp", "n_speakers", "is_speech_day", "is_fomc_day", "is_cpi_day", "is_nfp_day",
        "is_blackout", "is_imm_roll", "days_to_fomc"]
print(p.reindex(columns=cols).assign(a=p["abs_d_rate_bp"]).sort_values("a", ascending=False).head(15).to_string())

print()
print("=== IMM roll days: |d| stats ===")
for lab, m in [("imm_roll", p["is_imm_roll"]), ("not_roll", ~p["is_imm_roll"])]:
    s = p.loc[m, "abs_d_rate_bp"].dropna()
    print(f"{lab:10s} n={len(s):5d} mean={s.mean():7.3f} median={s.median():7.3f} var(d)={p.loc[m,'d_rate_bp'].var():9.2f}")

print()
print("=== overlap counts ===")
print("speech & fomc :", int((p.is_speech_day & p.is_fomc_day).sum()), "of", int(p.is_fomc_day.sum()), "fomc days")
print("speech & cpi  :", int((p.is_speech_day & p.is_cpi_day).sum()), "of", int(p.is_cpi_day.sum()))
print("speech & nfp  :", int((p.is_speech_day & p.is_nfp_day).sum()), "of", int(p.is_nfp_day.sum()))
print("speech & blk  :", int((p.is_speech_day & p.is_blackout).sum()), "of", int(p.is_blackout.sum()))
print("speech & roll :", int((p.is_speech_day & p.is_imm_roll).sum()), "of", int(p.is_imm_roll.sum()))

print()
print("=== abs_d by blackout (ex fomc/cpi/nfp) ===")
m = ~(p.is_fomc_day | p.is_cpi_day | p.is_nfp_day)
for lab, mm in [("blackout", m & p.is_blackout), ("nonblack", m & ~p.is_blackout)]:
    s = p.loc[mm, "abs_d_rate_bp"].dropna()
    print(f"{lab:10s} n={len(s):5d} mean|d|={s.mean():7.3f} var(d)={p.loc[mm,'d_rate_bp'].var():9.3f}")

print()
try:
    import statsmodels.api as sm
    print("statsmodels OK", sm.__version__ if hasattr(sm, "__version__") else "")
except Exception as e:
    print("statsmodels MISSING:", e)
import scipy
print("scipy", scipy.__version__)
print("numpy", np.__version__, "pandas", pd.__version__)
