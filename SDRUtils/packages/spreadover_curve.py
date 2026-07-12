"""Differential-based SPREADOVER_CURVE / SPREADOVER_FLY detection.

A curve/fly of spreadovers has a package PTS that equals the DIFFERENTIAL of its
legs' standalone swap-vs-UST spread levels (CURVE: back-front; FLY: 2*belly-wings).
We index the most-recent standalone SPREADOVER print per benchmark tenor from the
same frame and upgrade a plain CURVE/FLY whose package PTS ties out to that
differential within a bp tolerance. Complements detect_sub_package_curve_fly,
which handles legs that each carry their own distinct broker spread.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from SDRUtils.core.pts_scale import find_scale_match, spread_to_bp

_BENCHMARKS = (2.0, 3.0, 5.0, 7.0, 10.0, 20.0, 30.0)


def _nearest_benchmark(tenor: object, tol_y: float = 0.1):
    try:
        t = float(tenor)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(t):
        return None
    best = min(_BENCHMARKS, key=lambda b: abs(b - t))
    return best if abs(best - t) <= tol_y else None


def build_spreadover_level_index(df: pd.DataFrame, *, tol_y: float = 0.1) -> dict:
    """{benchmark_tenor -> latest standalone spreadover level in bp}."""
    if df.empty:
        return {}
    base = df.get("package_type", pd.Series(index=df.index, dtype=object)).astype(str).str.upper()
    is_so = base.eq("SPREADOVER")
    if "is_spreadover" in df.columns:
        is_so = is_so | df["is_spreadover"].fillna(False).astype(bool)
    so = df.loc[is_so].copy()
    if so.empty:
        return {}
    so["_ts"] = pd.to_datetime(so.get("execution_timestamp"), errors="coerce", utc=True)
    so = so.sort_values("_ts", kind="mergesort")  # ascending -> latest overwrites
    index: dict = {}
    for _, r in so.iterrows():
        bench = _nearest_benchmark(r.get("tenor_years"), tol_y)
        if bench is None:
            continue
        lvl = spread_to_bp(pd.to_numeric(r.get("package_transaction_spread"), errors="coerce"))
        if lvl is None:
            continue
        index[bench] = lvl
    return index


def _differential_bp(levels_bp: list, structure: str):
    if structure == "CURVE" and len(levels_bp) == 2:
        return levels_bp[1] - levels_bp[0]
    if structure == "FLY" and len(levels_bp) == 3:
        return 2.0 * levels_bp[1] - levels_bp[0] - levels_bp[2]
    return None


def detect_spreadover_curves_df(
    df: pd.DataFrame, *, tol_bp: float = 5.0, level_index: dict | None = None,
) -> pd.DataFrame:
    if df.empty or "package_type" not in df.columns or "package_id" not in df.columns:
        return df
    out = df.copy()
    if level_index is None:
        level_index = build_spreadover_level_index(out)
    if not level_index:
        return out

    base = out["package_type"].astype(str).str.upper()
    cand = base.isin({"CURVE", "FLY"}) & out["package_id"].notna()
    if not cand.any():
        return out

    for pkg_id, gidx in out.loc[cand].groupby("package_id").groups.items():
        gidx = list(gidx)
        g = out.loc[gidx]
        structure = str(g["package_type"].iloc[0]).upper()
        n = len(gidx)
        if (structure == "CURVE" and n != 2) or (structure == "FLY" and n != 3):
            continue
        if "forward_label" in g.columns and not (
            g["forward_label"].astype(str).str.lower() == "spot"
        ).all():
            continue
        g = g.assign(_t=pd.to_numeric(g["tenor_years"], errors="coerce")).sort_values("_t")
        if g["_t"].isna().any():
            continue
        levels = [level_index.get(_nearest_benchmark(t)) for t in g["_t"]]
        if any(l is None for l in levels):
            continue
        diff = _differential_bp(list(levels), structure)
        if diff is None:
            continue
        pkg_pts = pd.to_numeric(g["package_transaction_spread"], errors="coerce").dropna()
        if pkg_pts.empty:
            continue
        m = find_scale_match(abs(diff), abs(float(pkg_pts.iloc[0])), tol_bp)
        if m is None:
            continue
        pkg_bp = abs(float(pkg_pts.iloc[0])) * m["factor"]
        if abs(pkg_bp - abs(diff)) > tol_bp:
            continue
        new_type = "SPREADOVER_CURVE" if structure == "CURVE" else "SPREADOVER_FLY"
        out.loc[gidx, "package_type"] = new_type
        if "trade_type" in out.columns:
            out.loc[gidx, "trade_type"] = new_type
    return out
