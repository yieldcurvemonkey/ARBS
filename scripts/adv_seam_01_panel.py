r"""Independent rebuild of the seam panel straight from the tag cache.

Deliberately does NOT import RVUtils.ETFRebalance.intraday or scripts/etf_seam_*:
the point is to reproduce the numbers with my own indexing so a shared helper
cannot carry a shared bug.
"""
from __future__ import annotations

import pathlib
import sys

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DATA = ROOT / "notebooks/backtests/etf_rebalance/_data"

from MDP.CitiVelocityExcel.cache import CitiVeloTagCache  # noqa: E402

uni = pd.read_csv(DATA / "intraday_universe.csv")
print("universe cols:", list(uni.columns))
print(uni.head(3).to_string())
print("n bonds:", len(uni))

cache = CitiVeloTagCache()
series = {}
gaps = []
for isin in uni["isin"].astype(str):
    tag = f"RATES.BOND.{isin}.YIELD"
    s = cache.read(tag, "HOURLY", "CLOSE")
    if s is None or s.empty:
        gaps.append({"isin": isin, "n": 0})
        continue
    s = s.dropna()
    idx = pd.DatetimeIndex(s.index)
    d = np.diff(idx.view("int64")) / 1e9 / 60.0  # minutes
    gaps.append({"isin": isin, "n": len(s),
                 "min_gap_min": float(d.min()) if len(d) else np.nan,
                 "p01_gap_min": float(np.percentile(d, 1)) if len(d) else np.nan,
                 "median_gap_min": float(np.median(d)) if len(d) else np.nan,
                 "first": idx.min(), "last": idx.max(),
                 "n_gap_lt_60": int((d < 59.9).sum())})
    series[isin] = s
G = pd.DataFrame(gaps)
G.to_csv(DATA / "adv_seam_hourly_gap_census.csv", index=False)
print("\n=== HOURLY SPACING CENSUS (downsampling check) ===")
print(G[["n", "min_gap_min", "p01_gap_min", "median_gap_min", "n_gap_lt_60"]].describe().to_string())
print("tags whose MINIMUM gap exceeds 60 min (=> downsampled):",
      int((G["min_gap_min"] > 60.5).sum()), "of", len(G))
print("tags with any sub-hour gap:", int((G["n_gap_lt_60"] > 0).sum()))

frame = pd.DataFrame(series).sort_index()
print("\nhourly frame:", frame.shape, frame.index.min(), "..", frame.index.max())
# possibility gate, same band as theirs
frame = frame.mask((frame < 0.20) | (frame > 12.0))

# stamp-hour histogram
hh = pd.Series(pd.DatetimeIndex(frame.index).hour).value_counts().sort_index()
print("\nrows per stamp hour:")
print(hh.to_string())

STAMPS = {"y10": 9, "y13": 12, "y14": 13, "y15": 14, "y16": 15, "y17": 16}
marks = {}
for name, st in STAMPS.items():
    sub = frame[pd.DatetimeIndex(frame.index).hour == st]
    out = sub.copy()
    out.index = pd.DatetimeIndex(pd.DatetimeIndex(sub.index).normalize())
    out = out[~out.index.duplicated(keep="last")]
    marks[name] = out[out.index.to_series().dt.weekday < 5]
    print(f"{name} (stamp {st}): {out.shape}")

pieces = []
for name, m in marks.items():
    s = m.stack(future_stack=True).rename(name)
    s.index.names = ["date", "isin"]
    pieces.append(s)
panel = pd.concat(pieces, axis=1).reset_index()

u = uni.set_index("isin")
panel["cusip"] = panel["isin"].map(u["cusip"])
panel["maturity_date"] = pd.to_datetime(panel["isin"].map(u["maturity_date"]))
panel["issue_date"] = pd.to_datetime(panel["isin"].map(u["issue_date"]))
panel["ttm"] = (panel["maturity_date"] - panel["date"]).dt.days / 365.25
panel = panel[panel["date"] >= panel["issue_date"]]
panel = panel[panel["ttm"] > 0]
panel = panel.dropna(subset=["y15", "y16"], how="all")

panel["seam"] = (panel["y16"] - panel["y15"]) * 100.0
panel["c1415"] = (panel["y15"] - panel["y14"]) * 100.0
panel["c1314"] = (panel["y14"] - panel["y13"]) * 100.0
panel["c1617"] = (panel["y17"] - panel["y16"]) * 100.0

print("\nMY panel:", len(panel), "bond-dates,", panel["date"].nunique(), "dates,",
      panel["isin"].nunique(), "bonds", panel["date"].min().date(), panel["date"].max().date())
print("ttm range:", panel["ttm"].min().round(2), panel["ttm"].max().round(2))

# --- exact-zero census, the staleness proxy available without MI01 -------------
z = panel.dropna(subset=["seam"]).groupby("date")["seam"].agg(
    n="size", nzero=lambda s: int((s == 0).sum()))
z["zero_frac"] = z["nzero"] / z["n"]
z["is_early_close"] = z["zero_frac"] > 0.50
flagged = z.index[z["is_early_close"]]
print(f"\nearly-close flagged: {len(flagged)} of {len(z)} dates")
z.to_csv(DATA / "adv_seam_zero_census.csv")

clean = panel[~panel["date"].isin(set(flagged))].copy()
print("clean panel:", len(clean), "bond-dates,", clean["date"].nunique(), "dates")
zc = clean.dropna(subset=["seam"])
print("EXACT-ZERO seam moves on NON-flagged days: "
      f"{(zc['seam'] == 0).mean():.4f} of {len(zc):,} bond-dates")
for c in ("c1314", "c1415", "c1617"):
    v = clean[c].dropna()
    print(f"  exact-zero {c}: {(v==0).mean():.4f} of {len(v):,}")

print("\nmean |move| bp (non-flagged):")
for c, lab in [("seam", "15->16 SEAM"), ("c1314", "13->14"), ("c1415", "14->15"),
               ("c1617", "16->17")]:
    v = clean[c].dropna()
    print(f"  {lab:12s} mean|d| {v.abs().mean():.4f}  n {len(v):,}")

clean.to_parquet(DATA / "adv_seam_panel.parquet", index=False)
print("\nwrote adv_seam_panel.parquet")
