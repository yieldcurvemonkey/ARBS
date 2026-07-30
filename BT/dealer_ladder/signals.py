"""Ladder-state signal panels for the dealer-ladder study.

The ladder itself is defined by ``SDRUtils.stir_flow.ladder_state.ladder_at``:

    ladder(t) = sum over prints visible by t of
                delta_dv01 * weight(print) * 0.5 ** (age_minutes / half_life)

with ``weight = (1 - 2*p_flip)`` under ``"expected"`` (NaN p_flip -> 1.0) or 1.0
under ``"unweighted"``, curve-suspect prints dropped unless asked for, and
lifecycle-unwound prints removed from their unwind's visibility time.

``ladder_at`` is the authority on those semantics and this module is pinned
against it by test. What this module adds is a panel over a whole intraday grid
computed at a workable cost: ``ladder_grid`` calls ``ladder_at`` once per
timestamp, re-filtering the entire print frame each time, which over 138 sessions
x 96 decisions is ~13,000 full scans. Here the work is done per SESSION with one
vectorised (prints x grid) decay matrix, which is small because a print's weight
decays out of relevance inside its own session.

Panels produced, all indexed by decision timestamp with one column per bucket:

``level``      the ladder itself, in dealer-signed \\$/bp
``increment``  its change between consecutive decisions -- the X variable for the
               Hayashi-Yoshida lead-lag test, per the research plan's insistence
               that Y be per-print INCREMENTS and never EWMA levels
``z``          the level standardised against the trailing N COMPLETE sessions
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from SDRUtils.stir_flow import ladder_conventions as conv

# A print is carried forward this many half-lives before being dropped from a
# session's computation. 2**-20 ~ 1e-6 relative weight, which keeps the panel
# agreeing with ladder_at to well inside float tolerance while bounding the
# lookback for long half-lives.
DECAY_CUTOFF_HALF_LIVES = 20


def _session_dates(index) -> np.ndarray:
    idx = pd.DatetimeIndex(index)
    et = idx.tz_convert("America/New_York") if idx.tz is not None else idx
    return et.date


def print_weights(prints: pd.DataFrame, weighting: str) -> np.ndarray:
    """Per-print static weight. Mirrors ``ladder_state._weight`` exactly.

    Note ``p_flip`` arrives as numeric NaN rather than NULL for a large minority
    of rows, which lands on the 1.0 fallback -- intended, but it means the
    ``expected`` scheme is only doing work on part of the sample.
    """
    if weighting == "unweighted":
        return np.ones(len(prints), dtype=float)
    if weighting == "expected":
        p = pd.to_numeric(prints["p_flip"], errors="coerce").astype(float)
        return (1.0 - 2.0 * p).fillna(1.0).to_numpy()
    raise ValueError(f"unknown weighting {weighting!r}")


def _half_lives(prints: pd.DataFrame, half_lives: dict) -> np.ndarray:
    blk = prints["is_block"].fillna(False).astype(bool).to_numpy()
    return np.where(blk, half_lives["block"], half_lives["default"]).astype(float)


def ladder_panel(prints: pd.DataFrame, grid, *, space="FUTURES", half_lives=None,
                 weighting="expected", include_suspect=False, unwinds=None,
                 buckets=None) -> pd.DataFrame:
    """Decayed, weighted ladder over ``grid``: index = grid, columns = bucket_key."""
    half_lives = half_lives or conv.PROVISIONAL_HALF_LIVES_MIN
    grid = pd.DatetimeIndex(grid)
    df = prints[prints["bucket_space"] == space]
    if not include_suspect:
        df = df[~df["curve_suspect_trade"].fillna(False).astype(bool)]
    if buckets is None:
        buckets = sorted(df["bucket_key"].dropna().unique()) if len(df) else []
    out = pd.DataFrame(0.0, index=grid, columns=list(buckets), dtype=float)
    if df.empty or not len(grid) or not len(buckets):
        return out

    df = df.copy()
    df["_vis"] = pd.to_datetime(df["visibility_timestamp"])
    if df["_vis"].dt.tz is None:
        df["_vis"] = df["_vis"].dt.tz_localize("UTC")
    df["_w"] = print_weights(df, weighting)
    df["_hl"] = _half_lives(df, half_lives)
    df["_contrib"] = df["delta_dv01"].astype(float) * df["_w"]

    dead_at = {}
    if unwinds is not None and len(unwinds):
        u = unwinds.copy()
        u["unwind_visibility_ts"] = pd.to_datetime(u["unwind_visibility_ts"])
        dead_at = dict(zip(u["unit_key"], u["unwind_visibility_ts"]))

    max_hl = float(max(half_lives.values()))
    lookback = pd.Timedelta(minutes=DECAY_CUTOFF_HALF_LIVES * max_hl)
    grid_days = _session_dates(grid)
    bucket_pos = {b: i for i, b in enumerate(out.columns)}
    values = out.to_numpy()

    for day in pd.unique(grid_days):
        sel = grid_days == day
        gts = grid[sel]
        lo = gts.min() - lookback
        hi = gts.max()
        chunk = df[(df["_vis"] <= hi) & (df["_vis"] >= lo)]
        if chunk.empty:
            continue
        # int64 nanoseconds throughout: a tz-aware DatetimeIndex's .to_numpy()
        # yields object dtype, which will not broadcast against a timedelta64
        vis_ns = pd.DatetimeIndex(chunk["_vis"]).astype("int64").to_numpy()
        hl = chunk["_hl"].to_numpy()
        contrib = chunk["_contrib"].to_numpy()
        cols = chunk["bucket_key"].map(bucket_pos).to_numpy()
        keep = ~pd.isna(cols)
        if not keep.any():
            continue
        vis_ns, hl = vis_ns[keep], hl[keep]
        contrib, cols = contrib[keep], cols[keep].astype(int)

        # age in minutes: (grid x prints)
        g_ns = gts.astype("int64").to_numpy()
        age = (g_ns[:, None] - vis_ns[None, :]) / 6.0e10
        w = np.where(age >= 0.0, np.power(0.5, age / hl[None, :]), 0.0)

        if dead_at:
            units = chunk["unit_key"].to_numpy()[keep]
            dead = pd.DatetimeIndex([dead_at.get(u, pd.NaT) for u in units])
            if dead.tz is None:
                dead = dead.tz_localize("UTC")
            dead_ns = dead.astype("int64").to_numpy()
            has_dead = np.asarray(dead.notna())
            if has_dead.any():
                killed = (g_ns[:, None] >= dead_ns[None, :]) & has_dead[None, :]
                w = np.where(killed, 0.0, w)

        signed = w * contrib[None, :]
        rows = np.flatnonzero(sel)
        np.add.at(values, (rows[:, None], cols[None, :]), signed)

    return pd.DataFrame(values, index=grid, columns=out.columns)


def ladder_increments(panel: pd.DataFrame) -> pd.DataFrame:
    """Change in the ladder between consecutive decisions, NOT the level.

    The research plan is explicit that the lead-lag X must be increments: an EWMA
    level is autocorrelated by construction, so a lead-lag statistic computed on
    levels measures the decay kernel rather than information arrival. Increments
    are also what a hedger would actually respond to.

    Never differences across a session boundary: an overnight change is not an
    intraday innovation.
    """
    diff = panel.diff()
    days = _session_dates(panel.index)
    first_of_day = np.r_[True, days[1:] != days[:-1]]
    diff.iloc[first_of_day] = np.nan
    return diff


def trailing_zscore(panel: pd.DataFrame, window_days=10, min_days=5) -> pd.DataFrame:
    """Standardise each session against the trailing ``window_days`` COMPLETE sessions.

    Deliberately excludes the current session from its own moments. Same-session
    earlier observations would be legitimate information, but excluding whole
    sessions makes the estimator trivially auditable: nothing about session *d* can
    influence session *d*'s z-scores, which is what ``audit_trailing_moments``
    checks. Sessions with fewer than ``min_days`` of history yield NaN rather than
    a z-score fitted on almost nothing.
    """
    if panel.empty:
        return panel.copy()
    days = pd.Index(_session_dates(panel.index))
    uniq = list(pd.unique(days))
    out = pd.DataFrame(np.nan, index=panel.index, columns=panel.columns, dtype=float)
    for i, day in enumerate(uniq):
        hist_days = uniq[max(0, i - window_days):i]
        if len(hist_days) < min_days:
            continue
        hist = panel[days.isin(hist_days)]
        mu, sd = hist.mean(), hist.std()
        sd = sd.replace(0.0, np.nan)
        rows = days == day
        out.loc[rows] = (panel.loc[rows] - mu) / sd
    return out


def build_signal(prints: pd.DataFrame, grid, signal_cfg, *, unwinds=None,
                 buckets=None) -> dict:
    """``{"level", "increment", "z"}`` for one signal configuration."""
    level = ladder_panel(
        prints, grid, space=signal_cfg.space, half_lives=signal_cfg.half_lives,
        weighting=signal_cfg.weighting, include_suspect=signal_cfg.include_suspect,
        unwinds=unwinds, buckets=buckets)
    return {
        "level": level,
        "increment": ladder_increments(level),
        "z": trailing_zscore(level, window_days=signal_cfg.z_window_days),
    }


def print_intensity_panel(prints: pd.DataFrame, grid, *, space="FUTURES",
                          half_lives=None, include_suspect=False) -> pd.DataFrame:
    """UNSIGNED decayed DV01 per bucket — the label-free control.

    Immune to classification accuracy: it uses |delta_dv01| and ignores direction
    entirely. If only this works and the signed ladder does not, the finding is a
    flow-ACTIVITY effect and the direction model is carrying nothing, which is a
    materially different (and much weaker) claim.
    """
    unsigned = prints.copy()
    unsigned["delta_dv01"] = unsigned["delta_dv01"].astype(float).abs()
    return ladder_panel(unsigned, grid, space=space, half_lives=half_lives,
                        weighting="unweighted", include_suspect=include_suspect)
