# SDRUtils/stir_flow/ladder_state.py
"""Layer 3: the ladder as a pure read-time transform (ladder spec section 6).

No pricing here — decay, weighting, netting, and views over persisted
per-print projection vectors. Every parameter is an argument.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from SDRUtils.stir_flow import ladder_conventions as conv


def _decay(prints: pd.DataFrame, ts, half_lives) -> pd.Series:
    hl = pd.Series(
        np.where(prints["is_block"].fillna(False), half_lives["block"], half_lives["default"]),
        index=prints.index, dtype=float,
    )
    age_min = (pd.Timestamp(ts) - pd.to_datetime(prints["visibility_timestamp"])).dt.total_seconds() / 60.0
    w = np.power(0.5, age_min / hl)
    w[age_min < 0] = 0.0                      # no-lookahead: invisible prints weigh 0
    return pd.Series(w, index=prints.index)


def _weight(prints: pd.DataFrame, weighting: str) -> pd.Series:
    if weighting == "unweighted":
        return pd.Series(1.0, index=prints.index)
    if weighting == "expected":
        return (1.0 - 2.0 * prints["p_flip"].astype(float)).fillna(1.0)
    raise ValueError(f"unknown weighting {weighting!r}")


def _apply_filters(prints, space, include_suspect, unwinds, ts):
    df = prints[prints["bucket_space"] == space]
    if not include_suspect:
        df = df[~df["curve_suspect_trade"].fillna(False).astype(bool)]
    if unwinds is not None and len(unwinds):
        dead = unwinds[pd.to_datetime(unwinds["unwind_visibility_ts"]) <= pd.Timestamp(ts)]
        df = df[~df["unit_key"].isin(set(dead["unit_key"]))]
    return df


def ladder_at(prints, ts, *, space="MEETING", half_lives=None, weighting="expected",
              include_suspect=False, unwinds=None) -> pd.Series:
    half_lives = half_lives or conv.PROVISIONAL_HALF_LIVES_MIN
    df = _apply_filters(prints, space, include_suspect, unwinds, ts)
    if df.empty:
        return pd.Series(dtype=float)
    contrib = df["delta_dv01"].astype(float) * _decay(df, ts, half_lives) * _weight(df, weighting)
    out = contrib.groupby(df["bucket_key"]).sum()
    return out[out != 0.0].sort_index()


def ladder_grid(prints, timestamps, **kw) -> pd.DataFrame:
    rows = {pd.Timestamp(t): ladder_at(prints, t, **kw) for t in timestamps}
    return pd.DataFrame(rows).T.fillna(0.0)


def print_weights(prints, ts, half_lives) -> pd.Series:
    per_unit = prints.drop_duplicates("unit_key").set_index("unit_key")
    return _decay(per_unit, ts, half_lives)
