"""Cross-structure RV screener (data-agnostic generalization of STIRRVScreener).

Given a wide DataFrame of structure timeseries (DatetimeIndex; columns = any RV
structures such as flies/curves/spreads, values in bp or rate), rank them by a
composite RV score built from z-score, carry-to-vol, percentile, half-life and
forward consistency. Also exposes the ING-style RV Dislocation Index.

    build, rank, to_dataframe, rv_dislocation_index, get_data = make_rv_screener(df)
    top = rank(10)

Math sources: Astor Ridge process, SC RV-tool ranking, ING RV Dislocation Index,
existing BT STIRRVScreener.compute_composite_score (generalized).
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from RVUtils.mean_reversion import calibrate_ou

DEFAULT_WEIGHTS = {"z": 0.40, "carry_to_vol": 0.25, "percentile": 0.15, "half_life": 0.20}


def make_rv_screener(
    structures_df: pd.DataFrame,
    *,
    zscore_window: int = 65,
    vol_window: int = 20,
    percentile_window: int = 65,
    halflife_window: int = 120,
    weights: Optional[dict] = None,
    carry_df: Optional[pd.DataFrame] = None,
    max_halflife: float = 90.0,
    min_abs_z: float = 1.0,
    min_abs_carry_to_vol: float = 0.0,
    trading_days: int = 252,
):
    """Build a cross-structure RV screener over a panel of structure timeseries.

    Returns (build, rank, to_dataframe, rv_dislocation_index, get_data).
    `carry_df` (optional) supplies a per-structure carry/roll timeseries (same
    columns); its latest value feeds carry-to-vol and the composite score.
    """
    df = structures_df.sort_index()
    W = dict(DEFAULT_WEIGHTS)
    if weights:
        W.update(weights)

    state = {"df": df, "carry_df": carry_df, "result": None}

    def _metrics_for(col: str) -> dict:
        s = df[col].dropna()
        level = float(s.iloc[-1]) if len(s) else np.nan
        chg = float(s.diff().iloc[-1]) if len(s) > 1 else np.nan

        roll_z = s.rolling(int(zscore_window))
        z_ser = (s - roll_z.mean()) / roll_z.std(ddof=1)
        z = float(z_ser.iloc[-1]) if len(z_ser.dropna()) else np.nan

        pctl = s.rolling(int(percentile_window)).rank(pct=True)
        percentile = float(pctl.iloc[-1]) if len(pctl.dropna()) else np.nan

        vol = float(s.diff().rolling(int(vol_window)).std(ddof=1).iloc[-1] * np.sqrt(trading_days)) if len(s) > vol_window else np.nan

        hl = calibrate_ou(s.tail(int(halflife_window)))["half_life"]

        if carry_df is not None and col in carry_df.columns:
            cseries = carry_df[col].dropna()
            carry = float(cseries.iloc[-1]) if len(cseries) else np.nan
        else:
            carry = np.nan
        carry_to_vol = float(carry / vol) if (np.isfinite(carry) and np.isfinite(vol) and vol != 0) else np.nan

        composite = _composite(z, carry_to_vol, percentile, hl)
        direction = "SELL" if (np.isfinite(z) and z > 0) else "BUY" if (np.isfinite(z) and z < 0) else "FLAT"
        filters = {
            "z_pass": (abs(z) >= min_abs_z) if np.isfinite(z) else False,
            "ctv_pass": (abs(carry_to_vol) >= min_abs_carry_to_vol) if np.isfinite(carry_to_vol) else (min_abs_carry_to_vol <= 0),
            "hl_pass": (0 < hl <= max_halflife) if np.isfinite(hl) else False,
        }
        actionable = bool(all(filters.values()))

        return {
            "structure": col,
            "level": level,
            "chg_1d": chg,
            "zscore": z,
            "percentile": percentile,
            "vol": vol,
            "carry": carry,
            "carry_to_vol": carry_to_vol,
            "half_life": hl,
            "composite": composite,
            "direction": direction,
            "actionable": actionable,
        }

    def _composite(z, carry_to_vol, percentile, hl) -> float:
        if not np.isfinite(z):
            return np.nan
        z_capped = np.clip(z, -4, 4) / 4.0
        # carry-to-vol aligned so that positive reinforces fading the z-dislocation
        if np.isfinite(carry_to_vol):
            rar_norm = np.clip(carry_to_vol * (-np.sign(z)), -3, 3) / 3.0
        else:
            rar_norm = 0.0
        if np.isfinite(percentile):
            pctl_norm = (percentile - 0.5) * 2.0 * (-np.sign(z))
        else:
            pctl_norm = 0.0
        if np.isfinite(hl) and hl > 0:
            hl_norm = np.clip(1.0 - hl / max_halflife, -1, 1)
        else:
            hl_norm = 0.0
        mag = (
            W["z"] * abs(z_capped)
            + W["carry_to_vol"] * max(rar_norm, 0.0)
            + W["percentile"] * max(pctl_norm, 0.0)
            + W["half_life"] * max(hl_norm, 0.0)
        )
        return float(mag * np.sign(z))

    def build() -> pd.DataFrame:
        rows = [_metrics_for(c) for c in df.columns]
        result = pd.DataFrame(rows).set_index("structure")
        state["result"] = result
        return result

    def to_dataframe() -> pd.DataFrame:
        if state["result"] is None:
            build()
        return state["result"]

    def rank(n: int = 10) -> pd.DataFrame:
        out = to_dataframe()
        order = out["composite"].abs().sort_values(ascending=False, na_position="last").index
        ranked = out.reindex(order)
        actionable = ranked[ranked["actionable"]]
        if len(actionable) >= n:
            return actionable.head(n)
        return ranked.head(n)

    def rv_dislocation_index(window_z: Optional[int] = None, ma: int = 10) -> pd.Series:
        zw = int(window_z or zscore_window)
        roll = df.rolling(zw)
        Z = (df - roll.mean()) / roll.std(ddof=1)
        di = (Z ** 2).sum(axis=1, min_count=1).rolling(int(ma)).mean()
        di.name = "rv_dislocation_index"
        return di

    def get_data() -> pd.DataFrame:
        return state["df"]

    build.state = state
    return (build, rank, to_dataframe, rv_dislocation_index, get_data)
