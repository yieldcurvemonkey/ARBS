"""Full distribution of (grid_mid - implied_mid) in bp: n / median / IQR / p95,
split by tenor and by distance from the grid point.

Reads the parquets `validate` wrote, so this is the SAME comparison set the
runner made -- not a second re-implementation of the SQL, which could diverge.
"""
import pandas as pd

FILES = {
    "2026-04-01": "D:/midgrid_cacheval_2026-04-01.parquet",
    "2026-06-17": "D:/midgrid_cacheval_2026-06-17.parquet",
    "2025-04-07": "D:/midgrid_cacheval_2025-04-07.parquet",
}
BUCKETS = [-1, 0, 30, 60, 120, 300, 600, 1800, 1e9]
LABELS = ["0s", "<=30s", "30-60s", "1-2m", "2-5m", "5-10m", "10-30m", ">30m"]


def stat(s, label):
    s = pd.Series(s).dropna().astype(float)
    if not len(s):
        return f"  {label:<26} n=0"
    q25, q75 = s.quantile(0.25), s.quantile(0.75)
    return (f"  {label:<26} n={len(s):>5}  med={s.median():+10.6f}  "
            f"IQR=[{q25:+9.6f},{q75:+9.6f}] w={q75 - q25:9.6f}  "
            f"p95={s.quantile(0.95):+9.5f}  |p95|={s.abs().quantile(0.95):8.5f}  "
            f"|max|={s.abs().max():9.2e}")


for day, path in FILES.items():
    df = pd.read_parquet(path)
    df["dtb"] = pd.cut(df["dt_s"], BUCKETS, labels=LABELS)
    ex = df[df["exact_date"]]
    print("\n" + "#" * 100)
    print(f"# {day}   n={len(df)}  exact-date={len(ex)} ({100*len(ex)/len(df):.1f}%)"
          f"  dt=0s: {int((df['dt_s'] == 0).sum())} ({100*(df['dt_s']==0).mean():.2f}%)")
    print("#" * 100)
    print(stat(df["err_bp"], "ALL prints"))
    print(stat(ex["err_bp"], "EXACT-DATE"))
    print(stat(ex.loc[ex["dt_s"] == 0, "err_bp"], "EXACT-DATE, dt = 0 s"))
    print(stat(df.loc[~df["exact_date"], "err_bp"], "other-date (bucket)"))

    print("\n  -- EXACT-DATE by tenor --")
    for (idx, t), d in ex.groupby(["rate_index", "tenor_label"]):
        print(stat(d["err_bp"], f"{idx} {t}"))

    print("\n  -- EXACT-DATE by distance to grid point --")
    for b, d in ex.groupby("dtb", observed=True):
        print(stat(d["err_bp"], str(b)))

    print("\n  -- ALL prints by distance to grid point --")
    for b, d in df.groupby("dtb", observed=True):
        print(stat(d["err_bp"], str(b)))

    # THE key question: is every non-zero exact-date error a far-from-grid
    # print? If yes the residual is staleness, not a convention fault.
    nz = ex[ex["err_bp"].abs() > 1e-9]
    print(f"\n  exact-date prints with |err| > 1e-9 bp: {len(nz)} of {len(ex)}")
    if len(nz):
        print(f"    their dt_s: min={nz['dt_s'].min():.0f}s "
              f"max={nz['dt_s'].max():.0f}s")
        print(f"    all of them dt_s > 600 s? {bool((nz['dt_s'] > 600).all())}")
        print(nz[["rate_index", "tenor_label", "curve_timestamp", "ts",
                  "dt_s", "err_bp", "snapshot_policy", "g_policy"]]
              .sort_values("dt_s").to_string(index=False, max_colwidth=30))
    # and the ET hour those far prints sit in
    if len(nz):
        h = pd.to_datetime(nz["curve_timestamp"], utc=True).dt.tz_convert(
            "America/New_York").dt.hour
        print("    ET hour of curve_timestamp:", sorted(h.unique().tolist()))
