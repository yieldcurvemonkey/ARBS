import sys
sys.path.append(r"C:\Users\chris\clee\ARBS")
sys.path.append(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove")
import numpy as np
import pandas as pd

pd.set_option("display.width", 260)
pd.set_option("display.max_columns", 100)

base = r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_event_study"
ev = pd.read_parquet(base + r"\event_paths.parquet")
pl = pd.read_parquet(base + r"\placebo_paths.parquet")


def prof(df, off, cut=None):
    s = df[(df["offset_min"] == off) & df["signed_d_bp"].notna() & (df["stance_sign"] != 0)]
    if cut == "clean":
        s = s[~s["is_overlapping"]]
    if cut == "bucket":
        s = s[s["bucket"].abs() >= 1]
    rows = []
    for r, g in s.groupby("contract_rank"):
        h = g[g["stance_sign"] > 0]["signed_d_bp"]
        d = g[g["stance_sign"] < 0]["signed_d_bp"]
        rows.append(dict(
            rank=r, n=len(g), days=g["date"].nunique(),
            mean=g["signed_d_bp"].mean(), sd=g["signed_d_bp"].std(),
            tstat=g["signed_d_bp"].mean() / (g["signed_d_bp"].std() / np.sqrt(len(g))),
            hawk_n=len(h), hawk_mean=h.mean(), dove_n=len(d), dove_mean=d.mean(),
            balanced=0.5 * h.mean() + 0.5 * d.mean(),
        ))
    return pd.DataFrame(rows).set_index("rank")


for off in (30, 240):
    print("=" * 120)
    print(f"OFFSET +{off}")
    for name, cut in (("ALL SIGNED", None), ("CLEAN (non-overlapping)", "clean"), ("|bucket|>=1", "bucket")):
        print(f"\n--- REAL, {name}")
        print(prof(ev, off, cut).round(4).to_string())
    print(f"\n--- PLACEBO (all signed)")
    print(prof(pl, off, None).round(4).to_string())

print()
print("=" * 120)
print("EXCESS (real all-signed minus placebo) mean bp, and normalised by placebo SD")
for off in (30, 240):
    r = prof(ev, off, None)
    p = prof(pl, off, None)
    ex = pd.DataFrame({
        "real_mean": r["mean"], "plac_mean": p["mean"], "excess": r["mean"] - p["mean"],
        "plac_sd": p["sd"], "excess_over_sd": (r["mean"] - p["mean"]) / p["sd"],
        "real_mean_over_sd": r["mean"] / r["sd"],
    })
    print(f"\noffset +{off}")
    print(ex.round(4).to_string())

print()
print("=" * 120)
print("CLEAN real vs placebo excess")
for off in (30, 240):
    r = prof(ev, off, "clean")
    p = prof(pl, off, None)
    ex = pd.DataFrame({"real_mean": r["mean"], "n": r["n"], "plac_mean": p["mean"],
                       "excess": r["mean"] - p["mean"], "plac_sd": p["sd"],
                       "excess_over_sd": (r["mean"] - p["mean"]) / p["sd"]})
    print(f"\noffset +{off} CLEAN")
    print(ex.round(4).to_string())
