"""Independent verification of the X and Y inputs to R0, before any regression."""
import os
os.environ["ARBS_SUPABASE_ENABLED"] = "0"
import pandas as pd
import numpy as np

D = r"C:\Users\chris\clee\ARBS-r0\r0_leadlag\data"

pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 60)

print("=" * 100)
print("X  --  x_signed_dv01.parquet")
print("=" * 100)
x = pd.read_parquet(os.path.join(D, "x_signed_dv01.parquet"))
print("shape:", x.shape)
print("columns:", list(x.columns))
print(x.dtypes)
print(x.head(5))
print()
print("clock values:", x["clock"].unique())
print("bucket values:", sorted(x["bucket"].unique()))
print("venue_class:", sorted(x["venue_class"].astype(str).unique()))
print("is_block:", x["is_block"].unique())
print("minute_utc dtype/tz:", x["minute_utc"].dtype)
print("minute range:", x["minute_utc"].min(), "->", x["minute_utc"].max())
print("minute-aligned:", int((x["minute_utc"].dt.second == 0).all()), int((x["minute_utc"].dt.microsecond == 0).all()))
print()
for clk, g in x.groupby("clock"):
    days = g["minute_utc"].dt.floor("D").nunique()
    print(f"  clock={clk}: rows={len(g):,} cells n_prints={g['n_prints'].sum():,} "
          f"unique minutes={g['minute_utc'].nunique():,} N_days={days}")
print()
print("per-bucket per-clock:")
print(x.groupby(["clock", "bucket"]).agg(
    n_cells=("n_prints", "size"), n_prints=("n_prints", "sum"),
    gross=("gross_dv01", "sum"), signed=("signed_dv01", "sum"),
    minutes=("minute_utc", "nunique")).round(1))
print()
print("invariants:")
print("  |signed|>gross rows:", int((x["signed_dv01"].abs() > x["gross_dv01"] + 1e-6).sum()))
print("  gross<0 rows:", int((x["gross_dv01"] < 0).sum()))
print("  gross==0 rows:", int((x["gross_dv01"] == 0).sum()))
print("  nulls:", x.isna().sum().sum())
print("  dup grain:", int(x.duplicated(["bucket", "minute_utc", "clock", "is_block", "venue_class"]).sum()))
print()
# report claims
print("REPORT CLAIM CHECK (X):")
xe = x[x["clock"] == "exec"]
xd = x[x["clock"] == "diss"]
print(f"  claimed exec 145,143 cells / 58,220 minutes -> actual {len(xe):,} / {xe['minute_utc'].nunique():,}")
print(f"  claimed diss 136,054 cells / 52,678 minutes -> actual {len(xd):,} / {xd['minute_utc'].nunique():,}")
print(f"  claimed N_prints 292,525 exec -> actual {xe['n_prints'].sum():,}; diss {xd['n_prints'].sum():,}")
print(f"  claimed 68 UTC days 2026-05-01..2026-08-07 -> exec {xe['minute_utc'].dt.floor('D').nunique()} "
      f"{xe['minute_utc'].min().date()}..{xe['minute_utc'].max().date()}")
print("  claimed total rows 281,197 -> actual", len(x))
print()
# per-bucket DV01 vs report table
rep_x = {"SFR_FF": (41745, 925.8, 24003), "TU": (38575, 1187.4, 21301),
         "FV": (87204, 3609.5, 35763), "TY_UXY": (73682, 3565.7, 31447),
         "US": (51319, 3647.0, 23810)}
print("  per-bucket exec: bucket | prints(claim/actual) | gross $mm(claim/actual) | minutes(claim/actual)")
for b, (np_, gd, mn) in rep_x.items():
    g = xe[xe["bucket"] == b]
    print(f"    {b:8s} {np_:>7,}/{int(g['n_prints'].sum()):>7,}   {gd:>8.1f}/{g['gross_dv01'].sum()/1e6:>8.1f}   "
          f"{mn:>6,}/{g['minute_utc'].nunique():>6,}")

print()
print("=" * 100)
print("Y  --  y_signed_volume.parquet")
print("=" * 100)
y = pd.read_parquet(os.path.join(D, "y_signed_volume.parquet"))
print("shape:", y.shape)
print("columns:", list(y.columns))
print(y.dtypes)
print(y.head(5))
print("minute range:", y["minute_utc"].min(), "->", y["minute_utc"].max())
print("minute-aligned:", int((y["minute_utc"].dt.second == 0).all()))
print()
cov = y.groupby("bucket").agg(
    n_bins=("minute_utc", "size"), n_days=("minute_utc", lambda s: s.dt.floor("D").nunique()),
    first=("minute_utc", "min"), last=("minute_utc", "max"),
    gross=("gross_volume", "sum"), signed=("signed_volume", "sum"), n_trades=("n_trades", "sum"))
print(cov)
print()
print("invariants:")
print("  dup (bucket,minute):", int(y.duplicated(["bucket", "minute_utc"]).sum()))
print("  |signed|>gross:", int((y["signed_volume"].abs() > y["gross_volume"]).sum()))
print("  gross<0:", int((y["gross_volume"] < 0).sum()))
print("  nulls:", y.isna().sum().sum())
print("  total rows (claim 512,019):", len(y))
print()
print("y_coverage.csv:")
print(pd.read_csv(os.path.join(D, "y_coverage.csv")))
print()
print("y_root_stats.csv:")
print(pd.read_csv(os.path.join(D, "y_root_stats.csv")))

print()
print("=" * 100)
print("OVERLAP of X and Y")
print("=" * 100)
for clk in ["exec", "diss"]:
    xc = x[x["clock"] == clk].groupby(["bucket", "minute_utc"], as_index=False)["signed_dv01"].sum()
    for b in sorted(set(y["bucket"]) & set(xc["bucket"])):
        yb = y[y["bucket"] == b]
        xb = xc[xc["bucket"] == b]
        common_days = set(yb["minute_utc"].dt.floor("D")) & set(xb["minute_utc"].dt.floor("D"))
        # x minutes falling on y's grid
        inter = len(set(xb["minute_utc"]) & set(yb["minute_utc"]))
        print(f"  {clk} {b:8s}: y_bins={len(yb):>7,} x_minutes={len(xb):>7,} "
              f"x-minutes-on-y-grid={inter:>7,} ({inter/max(len(xb),1):.1%}) common_days={len(common_days)}")

print()
print("=" * 100)
print("SIGN CONVENTION SPOT CHECK: corr(X_exec signed_dv01, Y signed_volume) at k=0..+5, raw")
print("=" * 100)
for clk in ["exec", "diss"]:
    xc = x[x["clock"] == clk].groupby(["bucket", "minute_utc"], as_index=False)["signed_dv01"].sum()
    for b in ["SFR_FF", "TU", "FV", "TY_UXY", "US"]:
        yb = y[y["bucket"] == b].set_index("minute_utc")["signed_volume"].sort_index()
        xb = xc[xc["bucket"] == b].set_index("minute_utc")["signed_dv01"].sort_index()
        xr = xb.reindex(yb.index).fillna(0.0)
        cs = []
        for k in range(0, 6):
            cs.append(np.corrcoef(yb.values[k:], xr.values[:len(xr) - k if k else None])[0, 1] if k else
                      np.corrcoef(yb.values, xr.values)[0, 1])
        print(f"  {clk} {b:8s} corr(Y_t, X_(t-k)) k=0..5: " + " ".join(f"{c:+.4f}" for c in cs))
