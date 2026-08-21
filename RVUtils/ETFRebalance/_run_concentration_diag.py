"""Follow-up diagnostics on the concentration search: is the |z|>=2.5 cell and the 2025
year cell real, or an artefact of a thin, autocorrelated tail?
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from RVUtils.ETFRebalance import _run_concentration_search as CS  # noqa: E402
from RVUtils.ETFRebalance import bond_panel as BP  # noqa: E402

pd.set_option("display.width", 220)

d = CS.build_universe("TLT", "2016-01-01", 1)
d = CS.attach_flow(d, "TLT")
d = CS.attach_vol_regime(d)

h = 63
sub_all = d.dropna(subset=["z_active_w", f"fwd_{h}_orth"])

print("=" * 100)
print("1. How many names/dates actually clear |z|>=2.5, per year?")
print("=" * 100)
sub25 = sub_all[sub_all["z_active_w"].abs() >= 2.5]
tab = sub25.groupby("year").agg(n_obs=("cusip", "size"), n_cusip=("cusip", "nunique"),
                                 n_dates=("date", "nunique"))
print(tab.to_string())

print("\n" + "=" * 100)
print("2. Per-year mean edge_63 WITHIN the |z|>=2.5 cell -- is it a few years driving it?")
print("=" * 100)
rows = []
for year, g in sub25.groupby("year"):
    st = CS.date_clustered_stat(g[f"edge_{h}"], g["date"])
    rows.append({"year": year, **st})
print(pd.DataFrame(rows).round(4).to_string(index=False))

print("\n" + "=" * 100)
print("3. Per-year mean edge_63, UNCONDITIONAL (for comparison against the panel note)")
print("=" * 100)
rows = []
for year, g in sub_all.groupby("year"):
    st = CS.date_clustered_stat(g[f"edge_{h}"], g["date"])
    rows.append({"year": year, **st})
print(pd.DataFrame(rows).round(4).to_string(index=False))

print("\n" + "=" * 100)
print("4. Is |z|>=2.5 dominated by a handful of CUSIPs (concentration WITHIN the cell)?")
print("=" * 100)
by_cusip = sub25.groupby("cusip").agg(n=("date", "size"),
                                       mean_edge=(f"edge_{h}", "mean")).sort_values("n", ascending=False)
print(f"n_cusips={len(by_cusip)}, top 10 by count cover "
      f"{by_cusip['n'].head(10).sum() / by_cusip['n'].sum() * 100:.1f}% of obs")
print(by_cusip.head(15).round(4).to_string())

print("\n" + "=" * 100)
print("5. CALENDAR NULL for the size-conditioning result: does |raw_active_w| track")
print("   proximity to the deletion boundary mechanically (i.e. is a big z just a bond")
print("   near 20y, which deletion/addition already flags with no holdings file)?")
print("=" * 100)
sub25["near_boundary"] = (sub25["ttm"] < 21.5) | (sub25["ttm"] > 29.0)
print(f"share of |z|>=2.5 obs within 1.5y of a band edge (20y or 30y): "
      f"{sub25['near_boundary'].mean() * 100:.1f}%")
print(f"  (for comparison, share of ALL obs within that band): "
      f"{((sub_all['ttm'] < 21.5) | (sub_all['ttm'] > 29.0)).mean() * 100:.1f}%")
# calendar-only cut: same date filter but replace direction with sign(raw deletion/addition)
print("\n   mean edge_63 in the |z|>=2.5 cell, split by near-boundary vs not:")
for flag, g in sub25.groupby("near_boundary"):
    st = CS.date_clustered_stat(g[f"edge_{h}"], g["date"])
    print(f"   near_boundary={flag}: {st}")

print("\n" + "=" * 100)
print("6. Sign flip check: [1.5,2.0) bin negative, [2.5,3.0) positive -- same cusips?")
print("=" * 100)
b_neg = sub_all[(sub_all["z_active_w"].abs() >= 1.5) & (sub_all["z_active_w"].abs() < 2.0)]
b_pos = sub_all[(sub_all["z_active_w"].abs() >= 2.5) & (sub_all["z_active_w"].abs() < 3.0)]
cn = set(b_neg["cusip"].unique())
cp = set(b_pos["cusip"].unique())
print(f"cusips in [1.5,2.0) bin: {len(cn)}, in [2.5,3.0) bin: {len(cp)}, overlap: {len(cn & cp)}")

print("\n" + "=" * 100)
print("7. Interaction: size x vol_regime -- is the size effect ITSELF a vol-regime effect?")
print("=" * 100)
rows = []
for regime in ("low_vol", "mid_vol", "high_vol"):
    for lo, hi in ((0.0, 1.5), (1.5, 2.5), (2.5, np.inf)):
        g = sub_all[(sub_all["vol_regime"] == regime) &
                    (sub_all["z_active_w"].abs() >= lo) & (sub_all["z_active_w"].abs() < hi)]
        st = CS.date_clustered_stat(g[f"edge_{h}"], g["date"])
        rows.append({"vol_regime": regime, "size_bin": f"[{lo},{hi})", **st})
print(pd.DataFrame(rows).round(4).to_string(index=False))

print("\n" + "=" * 100)
print("8. Interaction: size x year(bucket 2016-2021 vs 2022-2026) -- pre/post regime shift")
print("=" * 100)
sub_all["era"] = np.where(sub_all["year"] <= 2021, "2016-2021", "2022-2026")
rows = []
for era in ("2016-2021", "2022-2026"):
    for lo, hi in ((0.0, 1.5), (1.5, 2.5), (2.5, np.inf)):
        g = sub_all[(sub_all["era"] == era) &
                    (sub_all["z_active_w"].abs() >= lo) & (sub_all["z_active_w"].abs() < hi)]
        st = CS.date_clustered_stat(g[f"edge_{h}"], g["date"])
        rows.append({"era": era, "size_bin": f"[{lo},{hi})", **st})
print(pd.DataFrame(rows).round(4).to_string(index=False))
