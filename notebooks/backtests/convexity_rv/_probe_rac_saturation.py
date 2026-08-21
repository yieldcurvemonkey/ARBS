r"""Is ``be_over_rv`` usable as a continuous signal, or is it saturated at zero?

The screen's breakeven is **truncated to zero whenever carry is non-negative**
(Citi: *"daily breakeven, zero if carry is positive"*). That is fine for a
cross-sectional screen printed on one day, and potentially fatal for a
time-series rule: a percentile of a series that is exactly 0 for months is
undefined precisely where the rule most wants to fire, because carry >= 0 is the
condition Citi's own entry rule is keyed on.

So measure the saturation before choosing the statistic. If it is material, the
continuous alternative is

    rac = carry_1y_bp / (rlzd_vol_bp * sqrt(252))

which is signed, passes smoothly through zero, needs no truncation, and is
literally risk-adjusted carry -- the quantity the brief names as workflow 4's
dominant driver. JPM's own definition is the same shape: expected return over a
horizon divided by annualised realised vol.

Reads ``rac_leg_panel.parquet``. No network.
"""
from __future__ import annotations

import os
import pathlib
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

REPO = pathlib.Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import RVUtils.ConvexityRV.strat3_strikeless_vol as S3  # noqa: E402

DATA = REPO / "notebooks" / "data" / "convexity_rv"
legs = pd.read_parquet(DATA / "rac_leg_panel.parquet")
print(f"leg panel: {len(legs):,} rows, "
      f"{legs.index.get_level_values('date').nunique():,} dates, "
      f"{legs.index.get_level_values('leg').nunique()} legs")

panel = S3.screen_panel_from_legs(legs, S3.PAIRS_15)
panel = S3.add_screen_stats(panel, legs)
print(f"screen panel: {panel.shape}, columns {list(panel.columns)}")

out = panel.reset_index()
out["year"] = out["date"].dt.year

# ---------------------------------------------------------------------------
# 1. Saturation of the published statistic
# ---------------------------------------------------------------------------
print("\n=== fraction of (date, pair) cells with be_over_rv == 0 ===")
z = out.groupby("year").apply(
    lambda g: pd.Series({
        "cells": len(g),
        "carry>=0": float((g["carry_1y_bp"] >= 0).mean()),
        "be==0": float((g["be_daily_analytic"] == 0).mean()),
        "ratio==0": float((g["be_over_rv"].fillna(0) == 0).mean()),
    }), include_groups=False)
print(z.round(3).to_string())

print("\nby pair, whole sample:")
p = out.groupby("pair").apply(
    lambda g: pd.Series({"be==0": float((g["be_daily_analytic"] == 0).mean())}),
    include_groups=False).sort_values("be==0", ascending=False)
print(p.round(3).to_string())

# ---------------------------------------------------------------------------
# 2. The continuous alternative
# ---------------------------------------------------------------------------
out["rac"] = out["carry_1y_bp"] / (out["rlzd_vol_bp"] * np.sqrt(252.0))
print("\n=== the continuous statistic: carry / (rlzd_vol * sqrt(252)) ===")
r = out.groupby("year").apply(
    lambda g: pd.Series({
        "n": len(g),
        "nan": float(g["rac"].isna().mean()),
        "exactly 0": float((g["rac"] == 0).mean()),
        "p05": g["rac"].quantile(.05), "p50": g["rac"].median(),
        "p95": g["rac"].quantile(.95),
        "frac > 0": float((g["rac"] > 0).mean()),
    }), include_groups=False)
print(r.round(4).to_string())

print("\n=== two-sidedness: does the sign actually flip? ===")
for pair, g in out.groupby("pair"):
    g = g.dropna(subset=["rac"])
    if g.empty:
        continue
    print(f"  {pair:18} n={len(g):5d}  frac carry>0 {float((g['rac'] > 0).mean()):.3f}  "
          f"rac p05 {g['rac'].quantile(.05):+.4f}  p95 {g['rac'].quantile(.95):+.4f}")

sat = float((out["be_daily_analytic"] == 0).mean())
print(f"\nVERDICT: be_daily is truncated to zero on {sat:.1%} of all cells.")
print("         The continuous rac is NaN on "
      f"{float(out['rac'].isna().mean()):.1%} (trailing-vol warmup only) and "
      f"exactly zero on {float((out['rac'] == 0).mean()):.2%}.")

out.to_parquet(DATA / "rac_screen_panel.parquet", index=False)
print(f"\nwrote {DATA / 'rac_screen_panel.parquet'}  {out.shape}")
