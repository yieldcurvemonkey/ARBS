import sys
import pandas as pd

sys.path.append(r"C:\Users\chris\clee\ARBS")
pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 60)

OUT = r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_driver_analysis"
p = pd.read_parquet(OUT + r"\panel_daily.parquet")
print(p.shape)
print(p.dtypes)
print(p.head(5).to_string())
print(p.tail(3).to_string())
print()
for c in p.columns:
    if p[c].dtype.kind in "biufc":
        print(f"{c:24s} nan={p[c].isna().sum():5d} min={p[c].min()!s:>12.12} max={p[c].max()!s:>12.12} mean={p[c].mean() if p[c].dtype.kind!='b' else p[c].mean():.4f}")
    else:
        print(f"{c:24s} nan={p[c].isna().sum():5d} nuniq={p[c].nunique()}")
print()
print("n_speakers value counts:")
print(p["n_speakers"].value_counts().sort_index())
print()
print("is_cpi_day", p["is_cpi_day"].sum() if "is_cpi_day" in p else "MISSING")
print(sorted(p.columns.tolist()))
