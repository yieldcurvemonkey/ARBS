"""Load and prepare the study's two panels into one analysis-ready frame."""

from __future__ import annotations

import pathlib
from typing import Optional, Tuple

import numpy as np
import pandas as pd

from RVUtils.USTSwitch.carry import (
    JPM_END,
    JPM_START,
    apply_specialness_model,
    attach_financing,
    attach_gc_fallback,
    build_specialness_model,
    load_repo_panel,
)

DATA_DIR = (
    pathlib.Path(__file__).resolve().parents[2] / "notebooks" / "backtests" / "ust_switch" / "_data"
)
PANEL_PATH = DATA_DIR / "bond_panel.parquet"
MAP_PATH = DATA_DIR / "alias_cusip_map.parquet"
PREPARED_PATH = DATA_DIR / "prepared_panel.parquet"


def load_prepared(
    *, rebuild: bool = False, repo_horizon: str = "1m"
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """(prepared_panel, alias_map). Caches the prepared panel to parquet."""
    amap = pd.read_parquet(MAP_PATH)
    amap["date"] = pd.to_datetime(amap["date"])

    if PREPARED_PATH.exists() and not rebuild:
        p = pd.read_parquet(PREPARED_PATH)
        p["date"] = pd.to_datetime(p["date"])
        return p, amap

    if not PANEL_PATH.exists():
        raise FileNotFoundError(
            f"no bond panel at {PANEL_PATH}. Build it first:\n"
            f"  python notebooks/backtests/ust_switch/build_bond_panel.py"
        )
    panel = pd.read_parquet(PANEL_PATH)
    for c in ("date", "issue_date", "maturity_date"):
        panel[c] = pd.to_datetime(panel[c])

    repo = load_repo_panel()
    panel = attach_financing(panel, repo, horizon=repo_horizon)
    panel = attach_gc_fallback(panel)

    model = build_specialness_model(panel)
    model = _sanity_check_model(model, panel)
    panel = apply_specialness_model(panel, model)

    # Two usable specialness columns, chosen per financing mode by the engine:
    #   special_bp        -- measured, NaN outside the JPM window
    #   special_bp_filled -- measured inside, modelled outside
    panel["special_actual_bp"] = panel["special_bp"].fillna(0.0)
    panel["special_modelled_bp"] = panel["special_bp_filled"].fillna(0.0)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(PREPARED_PATH, index=False)
    model.to_parquet(DATA_DIR / "specialness_model.parquet", index=False)
    return panel, amap


def select_financing(panel: pd.DataFrame, mode: str) -> pd.DataFrame:
    """Materialise ``special_used_bp`` for a financing mode.

    Done here rather than inside the engine so a config cannot silently run with the
    wrong column, and so the "actual" mode can also CLIP THE WINDOW -- reporting a
    2010-2016 result under a label that claims measured financing would be the same
    misrepresentation as reporting no financing at all.
    """
    out = panel.copy()
    if mode == "none":
        out["special_used_bp"] = 0.0
    elif mode == "actual":
        out["special_used_bp"] = out["special_actual_bp"]
        out = out[(out["date"] >= JPM_START) & (out["date"] <= JPM_END)]
    elif mode == "modelled":
        out["special_used_bp"] = out["special_modelled_bp"]
    else:
        raise ValueError(f"unknown financing mode {mode!r}")
    return out


def coverage_report(panel: pd.DataFrame) -> pd.DataFrame:
    """Per tenor: date span, rows, and what fraction has MEASURED financing."""
    g = panel.groupby("tenor").agg(
        first=("date", "min"),
        last=("date", "max"),
        days=("date", "nunique"),
        rows=("date", "size"),
        cusips=("cusip", "nunique"),
        ytm_nan=("YTM", lambda s: float(s.isna().mean())),
        financing_actual=("has_actual_financing", "mean"),
        mean_special_bp=("special_actual_bp", "mean"),
    )
    return g.round(4).reset_index()


#: A modelled specialness cell fitted from too few observations is the single most
#: dangerous number in this study, because it is applied to ~40% of the sample and it
#: moves the P&L directly. Measured on a deliberately-starved fit (one tenor, 19% actual
#: coverage, all of it inside the late-2016 squeeze) the model returned **73.8bp** for the
#: 10y on-the-run against a 9-year measured mean of 4.6bp -- a 16x overstatement that would
#: have made the short leg look ruinously expensive and killed every long-old cell for the
#: wrong reason. Guarded rather than trusted.
MIN_CELL_OBS = 30
MODEL_CAP_QUANTILE = 0.95


def _sanity_check_model(model: pd.DataFrame, panel: pd.DataFrame) -> pd.DataFrame:
    """Drop thin cells and cap the rest at the measured distribution's own tail."""
    out = model.copy()
    measured = panel.loc[panel["has_actual_financing"], "special_bp"].dropna()
    cap = float(measured.quantile(MODEL_CAP_QUANTILE)) if len(measured) else 0.0

    thin = out["count"] < MIN_CELL_OBS
    n_thin = int(thin.sum())
    # NaN, not 0: a thin cell has an UNKNOWN median, and apply_specialness_model falls
    # back to the (tenor, rank) level for it. Zeroing would hand the short leg free
    # financing, which is the direction that flatters a long-old switch.
    out.loc[thin, "special_bp_model"] = np.nan

    hot = out["special_bp_model"] > cap
    n_hot = int(hot.sum())
    out.loc[hot, "special_bp_model"] = cap

    print(f"[specialness model] {len(out)} cells fitted from {len(measured):,} measured "
          f"observations; p{int(MODEL_CAP_QUANTILE*100)} cap = {cap:.2f}bp")
    if n_thin:
        print(f"                    {n_thin} cells dropped (< {MIN_CELL_OBS} obs)")
    if n_hot:
        print(f"                    {n_hot} cells capped at the measured p95")
    keep = out.dropna(subset=["special_bp_model"])
    if len(keep):
        print("                    fitted median specialness by (tenor, rank), bp:")
        piv = keep.pivot_table(index="tenor", columns="rank", values="special_bp_model",
                               aggfunc="median")
        print(piv.round(2).to_string().replace("\n", "\n                    "))
    return out
