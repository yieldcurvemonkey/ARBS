r"""GV block: the declared C and D overlays -- CFTC positioning and CME-LCH basis.

The brief names both verticals ("models where we consider cme-lch basis and cftc
positioning e.g. street significant short sofr futures making futures trade
cheap vs swaps or making the convexity adjustment large"), so they are answered
with a measurement rather than with silence, even though the base books are
dead.

They are **conditioning overlays on declared base books, not standalone
signals** (pre-registration section 7), and they are reported as diagnostics
with their trial cost stated rather than scored as new cells.

Three things are measured:

  1. Citi's own economic claim, re-run on this block's panel: does the CA widen
     when dealers are stretched long?  (Block 3 reproduced it in BLUES only.)
  2. The overlay as a trade filter: what happens to the finalists' P&L when
     entries additionally require the dealer-net z to be aligned with the trade
     side, and when they require a CME-LCH basis move aligned with it.
  3. What the overlay costs in sample: how many episodes survive.
"""
from __future__ import annotations

import json
import math
import os
import pathlib
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
REPO = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.stdout.reconfigure(line_buffering=True)
pd.set_option("display.width", 240)
pd.set_option("display.max_columns", 60)

from RVUtils.ConvexityRV import gv_grid as GG  # noqa: E402
from RVUtils.ConvexityRV import gv_sizing as S  # noqa: E402
from RVUtils.ConvexityRV import gv_universe as U  # noqa: E402

DATA = REPO / "notebooks" / "data" / "convexity_rv"
CA = pd.read_parquet(DATA / "cavf_ca_panel.parquet")
LEGS = pd.read_parquet(DATA / "p2_legs.parquet")
LEGS.index = pd.to_datetime(LEGS.index)
IDX = CA.index.intersection(LEGS.index)
CA, LEGS = CA.loc[IDX], LEGS.loc[IDX]
st = pd.read_parquet(DATA / "p2_grid_stats.parquet")
ep = pd.read_parquet(DATA / "p2_grid_episodes.parquet")


def sec(t: str) -> None:
    print(f"\n{'=' * 80}\n{t}\n{'=' * 80}")


# ---------------------------------------------------------------------------
sec("1. Enrichment panel -- provenance first, because two things share a name")
# ---------------------------------------------------------------------------
from RVUtils.ConvexityRV.ca_signals import (EnrichmentConfig,  # noqa: E402
                                            build_enrichment_panel)

cfg = EnrichmentConfig(start=str(IDX.min().date()), end=str(IDX.max().date()))
# The CME-LCH basis is fetched explicitly rather than left to the default
# lookup: build_enrichment_panel's fallback returns no basis column at all when
# it cannot reach one, and a silently-absent overlay is exactly the failure
# mode this package keeps writing down.
_basis = None
try:
    from MDP.IRClearingHouseBasisSwaps.ccp_basis_cache import basis_panel
    _basis = basis_panel(str(IDX.min().date()), str(IDX.max().date()),
                         allow_network=False)
    print(f"CME-LCH basis: {_basis.shape} "
          f"{_basis.index.min()}..{_basis.index.max()} (offline cache)")
except Exception as exc:                                        # noqa: BLE001
    print(f"CME-LCH basis UNAVAILABLE offline in this worktree: "
          f"{type(exc).__name__}: {str(exc)[:160]}")
panel, prov = build_enrichment_panel(cfg, basis=_basis)
print(f"enrichment panel {panel.shape}  {panel.index.min().date()}.."
      f"{panel.index.max().date()}")
for k, v in prov.items():
    print(f"  {k:24s} {v}")
print("\nnon-null coverage:")
print(panel.notna().mean().round(4).to_string())
panel.to_parquet(DATA / "p2_overlay_panel.parquet")

# ---------------------------------------------------------------------------
sec("2. Citi's mechanism on this panel: CA level vs dealer positioning")
# ---------------------------------------------------------------------------
pos_col = next((c for c in panel.columns if "dealer" in c.lower()), None)
bas_cols = [c for c in panel.columns if "basis" in c.lower()]
print(f"dealer column: {pos_col!r};  basis columns: {bas_cols}")

rows = []
if pos_col:
    dn = panel[pos_col].reindex(IDX).ffill()
    for lab in list(U.PRIMARY_STRUCTURES) + ["BUNDLE5Y"]:
        ca = CA[U.ca_col(lab)].dropna()
        j = pd.concat([ca.rename("ca"), dn.rename("pos")], axis=1).dropna()
        # monthly changes, Citi's own frequency for Figure 4
        m = j.resample("ME").last().diff().dropna()
        if len(m) < 24:
            continue
        b = float(m["ca"].cov(m["pos"]) / m["pos"].var(ddof=1))
        r = float(m["ca"].corr(m["pos"]))
        t = r * math.sqrt(max(len(m) - 2, 1) / max(1e-12, 1 - r * r))
        lb = float(j["ca"].cov(j["pos"]) / j["pos"].var(ddof=1))
        lr = float(j["ca"].corr(j["pos"]))
        rows.append({"structure": lab, "n_months": len(m),
                     "d_slope_bp_per_contract": b, "d_r2": r * r, "d_t": t,
                     "level_slope": lb, "level_r2": lr * lr})
    reg = pd.DataFrame(rows).set_index("structure")
    print(reg.round(6).to_string())
    print("\nCiti (Sell Eurodollar convexity in Blues, Fig 4, monthly 2013-2017, "
          "Eurodollars): slope +2e-06, R2 0.2724.  A positive slope is the "
          "published mechanism -- dealers long, adjustment widens.")
    reg.to_parquet(DATA / "p2_overlay_positioning.parquet")

# ---------------------------------------------------------------------------
sec("3. The overlays as trade filters on the finalists")
# ---------------------------------------------------------------------------
FINALISTS = ["S|SFR12|immM_2s5s10s|beta_lvl|const_dv01",
             "A|GREENS|le_10y10y_15y10y|beta_chg|const_dv01",
             "A|GOLDS|imm2_2s5s10s|beta_lvl|inv_vol",
             "A|GREENS|spot_2s5s10s|beta_lvl|const_dv01"]

rows = []
if pos_col:
    dn = panel[pos_col].reindex(IDX).ffill()
    dz = ((dn - dn.rolling(252, min_periods=126).mean())
          / dn.rolling(252, min_periods=126).std(ddof=1))
    for cid in FINALISTS:
        sub = ep[ep["cell_id"] == cid]
        if sub.empty:
            continue
        keep = []
        for _, r in sub.iterrows():
            v = dz.dropna().asof(pd.Timestamp(r["entry"]))
            if not np.isfinite(v):
                keep.append((False, r["pnl_usd"], np.nan))
                continue
            # Citi's mechanism, sided: short the CA only when dealers are
            # stretched LONG; long it only when they are stretched short.
            ok = (v >= 1.0) if r["side"] < 0 else (v <= -1.0)
            keep.append((ok, r["pnl_usd"], v))
        k = pd.DataFrame(keep, columns=["ok", "pnl", "z"])
        rows.append({"cell_id": cid, "n": len(k), "n_pass": int(k["ok"].sum()),
                     "pnl_all": float(k["pnl"].sum()),
                     "pnl_conditioned": float(k.loc[k["ok"], "pnl"].sum()),
                     "mean_pnl_pass": float(k.loc[k["ok"], "pnl"].mean())
                     if k["ok"].any() else np.nan,
                     "mean_pnl_fail": float(k.loc[~k["ok"], "pnl"].mean())
                     if (~k["ok"]).any() else np.nan})
    if rows:
        ov = pd.DataFrame(rows)
        print("C -- positioning overlay (dealer-net z >= +1 for short-CA, "
              "<= -1 for long-CA):")
        print(ov.round(1).to_string(index=False))
        ov.to_parquet(DATA / "p2_overlay_C.parquet")

rows = []
if bas_cols:
    bc = bas_cols[0]
    bs = panel[bc].reindex(IDX).ffill()
    d20 = bs.diff(20)
    for cid in FINALISTS:
        sub = ep[ep["cell_id"] == cid]
        if sub.empty:
            continue
        keep = []
        for _, r in sub.iterrows():
            v = d20.dropna().asof(pd.Timestamp(r["entry"]))
            if not np.isfinite(v):
                keep.append((False, r["pnl_usd"]))
                continue
            ok = abs(v) >= 0.25 and ((v > 0) if r["side"] < 0 else (v < 0))
            keep.append((ok, r["pnl_usd"]))
        k = pd.DataFrame(keep, columns=["ok", "pnl"])
        rows.append({"cell_id": cid, "basis_col": bc, "n": len(k),
                     "n_pass": int(k["ok"].sum()),
                     "pnl_all": float(k["pnl"].sum()),
                     "pnl_conditioned": float(k.loc[k["ok"], "pnl"].sum())})
    if rows:
        ov = pd.DataFrame(rows)
        print("\nD -- CME-LCH basis overlay (|20d basis change| >= 0.25 bp, "
              "aligned with the trade side):")
        print(ov.round(1).to_string(index=False))
        ov.to_parquet(DATA / "p2_overlay_D.parquet")

print("\nA conditioning overlay can only ever SUBTRACT episodes; with 6-12 "
      "episodes per cell, an overlay that keeps 1-3 of them cannot be "
      "distinguished from noise, and that -- not the sign of its P&L -- is the "
      "reportable fact.")
