"""Persist the diagnostic tables from _run_concentration_diag.py to CSV, for both funds."""
from __future__ import annotations

import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from RVUtils.ETFRebalance import _run_concentration_search as CS  # noqa: E402
from RVUtils.ETFRebalance import bond_panel as BP  # noqa: E402

h = 63


def run(fund: str) -> pd.DataFrame:
    d = CS.build_universe(fund, "2016-01-01", 1)
    d = CS.attach_flow(d, fund)
    d = CS.attach_vol_regime(d)
    sub_all = d.dropna(subset=["z_active_w", f"fwd_{h}_orth"]).copy()

    rows = []

    # A: per-year mean edge WITHIN |z|>=2.5
    sub25 = sub_all[sub_all["z_active_w"].abs() >= 2.5]
    for year, g in sub25.groupby("year"):
        st = CS.date_clustered_stat(g[f"edge_{h}"], g["date"])
        rows.append({"table": "year_within_size25", "cell": str(year), **st})

    # B: cusip concentration within |z|>=2.5
    bc = sub25.groupby("cusip").agg(n=("date", "size"), mean_edge=(f"edge_{h}", "mean"))
    bc = bc.sort_values("n", ascending=False)
    top10_share = bc["n"].head(10).sum() / bc["n"].sum() * 100 if len(bc) else np.nan
    for cusip, r in bc.head(15).iterrows():
        rows.append({"table": "cusip_concentration_size25", "cell": cusip,
                     "n_obs": int(r["n"]), "mean_bp": float(r["mean_edge"]),
                     "n_dates": np.nan, "t": np.nan})
    rows.append({"table": "cusip_concentration_size25_summary",
                 "cell": f"n_cusips={len(bc)}, top10_share_pct={top10_share:.1f}",
                 "n_obs": int(bc['n'].sum()) if len(bc) else 0, "n_dates": np.nan,
                 "mean_bp": np.nan, "t": np.nan})

    # C: calendar-boundary null for the size25 cell
    sub25 = sub25.copy()
    sub25["near_boundary"] = (sub25["ttm"] < 21.5) | (sub25["ttm"] > 29.0)
    base_rate = float(((sub_all["ttm"] < 21.5) | (sub_all["ttm"] > 29.0)).mean() * 100)
    for flag, g in sub25.groupby("near_boundary"):
        st = CS.date_clustered_stat(g[f"edge_{h}"], g["date"])
        rows.append({"table": "boundary_null_size25",
                     "cell": f"near_boundary={flag} (base_rate_all={base_rate:.1f}%)", **st})

    # D: size x vol_regime interaction
    for regime in ("low_vol", "mid_vol", "high_vol"):
        for lo, hi in ((0.0, 1.5), (1.5, 2.5), (2.5, np.inf)):
            g = sub_all[(sub_all["vol_regime"] == regime) &
                        (sub_all["z_active_w"].abs() >= lo) & (sub_all["z_active_w"].abs() < hi)]
            st = CS.date_clustered_stat(g[f"edge_{h}"], g["date"])
            rows.append({"table": "size_x_volregime", "cell": f"{regime}|[{lo},{hi})", **st})

    # E: size x era interaction
    sub_all["era"] = np.where(sub_all["year"] <= 2021, "2016-2021", "2022-2026")
    for era in ("2016-2021", "2022-2026"):
        for lo, hi in ((0.0, 1.5), (1.5, 2.5), (2.5, np.inf)):
            g = sub_all[(sub_all["era"] == era) &
                        (sub_all["z_active_w"].abs() >= lo) & (sub_all["z_active_w"].abs() < hi)]
            st = CS.date_clustered_stat(g[f"edge_{h}"], g["date"])
            rows.append({"table": "size_x_era", "cell": f"{era}|[{lo},{hi})", **st})

    out = pd.DataFrame(rows)
    out["fund"] = fund
    out["horizon"] = h
    return out


for fund in ("TLT", "TLH"):
    df = run(fund)
    path = BP.panel_dir() / f"conc_{fund.lower()}_diag.csv"
    df.to_csv(path, index=False)
    print(f"wrote {path} ({len(df)} rows)")
