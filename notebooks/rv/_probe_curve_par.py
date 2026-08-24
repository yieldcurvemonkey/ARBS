"""Par 2y OIS from the stored discount factors -- tie out to the known answer."""
import pathlib

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

ROOT = pathlib.Path(
    r"C:\Users\chris\AppData\Local\ARBS\Cache\curve_store\raw"
    r"\asset=USD-SOFR-1D-CITIVELOEXCEL")

dataset = ds.dataset(str(ROOT), format="parquet", partitioning="hive")
df = dataset.to_table(columns=["trading_date", "session_minute", "node_dates",
                               "discount_factors"]).to_pandas()
df["trading_date"] = pd.to_datetime(df["trading_date"])
g = df.sort_values(["trading_date", "session_minute"]).groupby("trading_date").tail(1)
row = g[g["trading_date"] == pd.Timestamp("2026-08-14")].iloc[0]

nd = pd.to_datetime(pd.Series(list(row["node_dates"])))
dfs = np.asarray(list(row["discount_factors"]), float)
ref = row["trading_date"]
days = (nd - ref).dt.days.to_numpy(float)
ok = np.isfinite(dfs) & (dfs > 0) & (days >= 0)
days, dfs = days[ok], dfs[ok]
lg = np.log(dfs)


def df_at(d_days: float) -> float:
    return float(np.exp(np.interp(d_days, days, lg)))


for basis in (360.0, 365.0):
    pay = [ref + pd.DateOffset(years=1), ref + pd.DateOffset(years=2)]
    prev = ref
    num_df = df_at((pay[-1] - ref).days)
    ann = 0.0
    for p in pay:
        tau = (p - prev).days / basis
        ann += tau * df_at((p - ref).days)
        prev = p
    par = (1.0 - num_df) / ann * 100.0
    print(f"annual pay, ACT/{basis:.0f}: 2y par = {par:.5f}")

zero = (df_at((ref + pd.DateOffset(years=2) - ref).days) ** (-1.0 / 2.0) - 1.0) * 100.0
print(f"annualised 2y zero          = {zero:.5f}")
print("known answer (CurveStore reprice, recorded in the tag-poison note) = 4.02995")
