import sys
sys.path.append(r"C:\Users\chris\clee\ARBS")
sys.path.append(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove")
import pandas as pd
import numpy as np

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 100)

base = r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove"
ev = pd.read_parquet(base + r"\_event_study\event_paths.parquet")
dl = pd.read_parquet(base + r"\_driver_analysis\panel_daily.parquet")
dl = dl.reset_index()
dl["date"] = pd.to_datetime(dl["date"]).dt.date

print("daily panel imm3x4_rate units: min %.4f max %.4f" % (dl.imm3x4_rate.min(), dl.imm3x4_rate.max()))

# level match: for each rank, compare rate_bp at offset 0 with imm3x4_rate*100 on the same date
z = ev[ev.offset_min == 0][["date", "contract_rank", "symbol", "rate_bp", "speech_ts"]].copy()
z["date"] = pd.to_datetime(z["date"]).dt.date
m = z.merge(dl[["date", "imm3x4_rate"]], on="date", how="inner")
m["daily_bp"] = m["imm3x4_rate"] * 100.0
print("\nmerged rows:", len(m))
for r in sorted(ev.contract_rank.unique()):
    s = m[m.contract_rank == r].dropna(subset=["rate_bp", "daily_bp"])
    if len(s) < 20:
        print(f"rank {r}: n={len(s)} too few"); continue
    diff = s.rate_bp - s.daily_bp
    print(f"rank {r}: n={len(s):5d}  corr(level)={np.corrcoef(s.rate_bp, s.daily_bp)[0,1]:.4f}  "
          f"mean_diff_bp={diff.mean():8.2f}  median_abs_diff={diff.abs().median():7.2f}  rmse={np.sqrt((diff**2).mean()):7.2f}")

# also symbol mix by rank on a couple of dates
print()
for d in [pd.Timestamp("2025-04-09").date(), pd.Timestamp("2022-01-11").date(), pd.Timestamp("2024-06-05").date()]:
    s = z[z.date == d][["contract_rank", "symbol"]].drop_duplicates().sort_values("contract_rank")
    print(d, dict(zip(s.contract_rank, s.symbol)))

# sample sizes
print("\n=== SAMPLE ===")
one = ev[(ev.contract_rank == 3) & (ev.offset_min == 0)]
print("rank3 events:", one.event_id.nunique())
sg = ev[(ev.contract_rank == 3)]
ids = sg[["event_id", "stance_sign", "bucket", "is_overlapping", "date"]].drop_duplicates("event_id")
print("signed:", (ids.stance_sign != 0).sum(), " hawk:", (ids.stance_sign > 0).sum(), " dove:", (ids.stance_sign < 0).sum())
print("signed & non-overlapping:", ((ids.stance_sign != 0) & (~ids.is_overlapping)).sum())
print("signed & |bucket|>=1:", ((ids.stance_sign != 0) & (ids.bucket.abs() >= 1)).sum())

# coverage of the daily panel for event dates
ids["date"] = pd.to_datetime(ids["date"]).dt.date
sgn = ids[ids.stance_sign != 0]
have = sgn.date.isin(set(dl.date))
print("signed events whose date is in the daily panel:", have.sum(), "of", len(sgn))
print("distinct signed event dates:", sgn.date.nunique(), " in daily panel:", sgn[have].date.nunique())

# NaN structure by offset for rank3 signed
sub = ev[(ev.contract_rank == 3) & (ev.stance_sign != 0)]
piv = sub.pivot_table(index="event_id", columns="offset_min", values="rate_bp")
print("\nnon-NaN count by offset (rank3, signed events, n=%d):" % len(piv))
print(piv.notna().sum().to_string())
print("\nevents with BOTH offset0 and offset300 present:", (piv[0].notna() & piv[300].notna()).sum())
for w in [5, 15, 30, 60, 120, 240, 300]:
    print(f"  window {w:4d}: both 0 and +{w} present -> {(piv[0].notna() & piv[w].notna()).sum()}")
common = piv[[0, 5, 15, 30, 60, 120, 240, 300]].notna().all(axis=1)
print("common across all windows:", common.sum())
