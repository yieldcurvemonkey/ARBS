import pandas as pd
DIR = r"C:\Users\chris\clee\ARBS\notebooks\backtests\SFR_screeners"
opt = pd.read_parquet(DIR + r"\butterfly_rv_backfill.parquet")
opt["date"] = pd.to_datetime(opt["date"])
with_sig = opt[opt["var_signal_adj"].notna()]
print(f"OPTIONS PANEL: {opt.shape[0]} rows, {opt['date'].nunique()} dates, "
      f"{with_sig['date'].nunique()} dates w/ adj_signal")
print(f"  date range: {opt['date'].min().date()} .. {opt['date'].max().date()}")
print(f"  rows w/ adj_signal: {len(with_sig)} / {len(opt)} ({len(with_sig)/len(opt):.0%})")
print(f"  by spacing (rows w/ signal): "
      + ", ".join(f"{s}:{(with_sig['spacing']==s).sum()}" for s in [1,2,3,4]))
# coverage by date
cov = with_sig.groupby("date").size()
print(f"  flies-with-signal per date: min={cov.min()} med={int(cov.median())} max={cov.max()}")
