r"""Is the carried ``p2_legs.parquet`` still what the pricing layer returns today?

The step-1 certification re-priced six dates and found the CA panel exact
(max |diff| 0.0 bp) but the spot 2y/5y/10y par rates OFF by up to 0.0121
percent = 1.21 bp.  A basis point on the 10y moves the fitted 2s5s10s fly, so
"a copied panel is a hypothesis until re-priced" has to be answered over the
whole window, not on a sample, before anything is fitted to it.

Pulls the three fair-value regressors and the five ATMF normal vols fresh over
the full window and diffs them against the carried panel, date by date.

Output: notebooks/data/convexity_rv/p4_leg_vintage_diff.{parquet,json}
"""
from __future__ import annotations

import datetime
import json
import os
import pathlib
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
REPO = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.stdout.reconfigure(line_buffering=True)
pd.set_option("display.width", 220)

DATA = REPO / "notebooks" / "data" / "convexity_rv"
CURVE = "USD-SOFR-1D"
SPOT = ("2Y", "5Y", "10Y")
VOLS = ("1Yx1Y", "2Yx1Y", "3Yx1Y", "4Yx1Y", "5Yx1Y")
MATCHED = tuple(f"IMM_{k}x1y" for k in (1, 5, 9, 13, 17))

LEGS = pd.read_parquet(DATA / "p2_legs.parquet")
LEGS.index = pd.to_datetime(LEGS.index)
CA = pd.read_parquet(DATA / "cavf_ca_panel.parquet")
CA.index = pd.to_datetime(CA.index)
IDX = CA.index.intersection(LEGS.index)
print(f"{len(IDX)} dates {IDX.min().date()}..{IDX.max().date()}")

from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP  # noqa: E402
from MDP.IRSwaptions.IRSwaptionMDP import IRSwaptionMDP  # noqa: E402
from Query.Unified.UnifiedQuery import UnifiedQuery  # noqa: E402
from Query.Unified.registry import UnifiedStructure, UnifiedValue  # noqa: E402
from TB.IRSwapsTB import IRSwapsTB  # noqa: E402
from TB.IRSwaptionsTB import IRSwaptionsTB  # noqa: E402
from TB.TimeseriesBuilder import TimeseriesBuilder  # noqa: E402

tb = IRSwapsTB(IRSwapsMDP(source="citivelo_excel_rl"), show_tqdm=False)
tb_vol = IRSwaptionsTB(
    IRSwaptionMDP(source="CITIVELO-RL", curve_source="citivelo_excel_rl",
                  request_defaults={"verify": False}), show_tqdm=False)
qs = [UnifiedQuery(curve=CURVE, tenor=t, value=UnifiedValue.IRS_RATE)
      for t in SPOT + MATCHED]
qs += [UnifiedQuery(curve=CURVE, selector={"shorthand": sh, "strike": "ATMF"},
                    structure=UnifiedStructure.IRSWAPTION_STRADDLE,
                    value=UnifiedValue.IRSWAPTION_NVOL) for sh in VOLS]
print(f"pulling {len(qs)} series fresh over the full window ...")
frames = []
for y in range(IDX.min().year, IDX.max().year + 1):
    a = max(IDX.min().date(), datetime.date(y, 1, 1))
    b = min(IDX.max().date(), datetime.date(y, 12, 31))
    if a > b:
        continue
    df = TimeseriesBuilder().get_timeseries(
        start=a, end=b, queries=qs, n_jobs=8,
        routers={"IRS": tb, "IRSWAPTION": tb_vol})
    df.index = pd.to_datetime(df.index)
    print(f"  {y}: {df.shape}")
    frames.append(df)
fresh = pd.concat(frames).sort_index()
fresh = fresh[~fresh.index.duplicated(keep="last")]
tb.close()
print(f"fresh {fresh.shape}  {fresh.index.min().date()}..{fresh.index.max().date()}")

rows = []
diffs = {}
for c in fresh.columns:
    if c not in LEGS.columns:
        print(f"  NOT IN CARRIED PANEL: {c}")
        continue
    a = LEGS.loc[IDX, c].astype(float)
    b = fresh[c].reindex(IDX).astype(float)
    d = (b - a)
    diffs[c] = d
    both = d.dropna()
    scale = 100.0 if "NVOL" not in c else 1.0        # percent -> bp for rates
    rows.append({
        "column": c.replace(CURVE + " ", ""),
        "n_both": int(len(both)),
        "n_panel_only": int((a.notna() & b.isna()).sum()),
        "n_fresh_only": int((a.isna() & b.notna()).sum()),
        "n_exact": int((both.abs() < 1e-12).sum()),
        "frac_exact": float((both.abs() < 1e-12).mean()) if len(both) else np.nan,
        "max_abs_diff": float(both.abs().max() * scale) if len(both) else np.nan,
        "mean_abs_diff": float(both.abs().mean() * scale) if len(both) else np.nan,
        "p99_abs_diff": float(both.abs().quantile(0.99) * scale) if len(both) else np.nan,
        "units": "bp" if "NVOL" not in c else "bp/yr",
    })
T = pd.DataFrame(rows).set_index("column")
print("\ncarried panel vs fresh pull, whole window:")
print(T.round(6).to_string())

D = pd.DataFrame(diffs).loc[IDX]
D.columns = [c.replace(CURVE + " ", "") for c in D.columns]
rate_cols = [c for c in D.columns if "NVOL" not in c]
bad = (D[rate_cols].abs() > 1e-12).any(axis=1)
print(f"\ndates where ANY rate column differs: {int(bad.sum())} of {len(IDX)} "
      f"({100 * bad.mean():.1f}%)")
if bad.any():
    first, last = D.index[bad][0], D.index[bad][-1]
    print(f"  first {first.date()}  last {last.date()}")
    by_year = bad.groupby(bad.index.year).mean().round(4)
    print("  fraction of dates differing, by year:")
    print(by_year.to_string())
    print("\n  the ten largest 10Y differences (bp):")
    c10 = "10Y OUTRIGHT RATE"
    top = (D[c10].abs() * 100).nlargest(10)
    print(pd.DataFrame({"diff_bp": (D[c10] * 100).loc[top.index]}).round(4).to_string())

D.to_parquet(DATA / "p4_leg_vintage_diff.parquet")
(DATA / "p4_leg_vintage_diff.json").write_text(json.dumps({
    "n_dates": int(len(IDX)),
    "n_dates_any_rate_differs": int(bad.sum()),
    "table": json.loads(T.reset_index().to_json(orient="records")),
}, indent=1))
print(f"\nwrote {DATA / 'p4_leg_vintage_diff.parquet'}")
