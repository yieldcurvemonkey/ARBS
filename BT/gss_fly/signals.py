"""Bond-level richness scoring for the GSS butterfly book.

Direct port of ``GSS_module.my_zscore`` / ``ts_scoring`` / ``build_signals`` onto modern pandas.

The one subtlety worth stating plainly: the original writes ``pd.ewma(my_ts, scoring_window)``.
In pandas 0.x the second positional argument of ``ewma`` is ``com``, **not** ``halflife`` — so the
scoring window is a centre-of-mass while the smoothing window (passed by keyword) is a halflife.
That asymmetry is reproduced here rather than silently harmonised: ``com=20`` corresponds to a
halflife of ``ln(2)·(1+com) ≈ 14.6`` days, so harmonising would change every number.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from BT.gss_fly.config import BondSignalConfig

__all__ = ["ewm_zscore", "ts_scoring", "cross_sectional_zscore", "build_bond_signals"]


def ewm_zscore(series: pd.Series, scoring_com: float) -> pd.Series:
    """``(x - ewma(x, com)) / ewmstd(x, com)`` — GSS_module.my_zscore."""
    s = pd.Series(series).astype(float)
    mean = s.ewm(com=scoring_com, min_periods=1).mean()
    std = s.ewm(com=scoring_com, min_periods=2).std()
    return (s - mean) / std.replace(0.0, np.nan)


def ts_scoring(series: pd.Series, smoothing_halflife: float, scoring_com: float) -> pd.Series:
    """Smooth with an EWMA halflife, then z-score with an EWM centre-of-mass.

    GSS_module.ts_scoring. The original drops NaNs between the two steps; reproduced so the
    scoring EWM does not see leading NaNs as observations.
    """
    s = pd.Series(series).astype(float)
    smoothed = s.ewm(halflife=smoothing_halflife, min_periods=1).mean().dropna()
    if smoothed.empty:
        return pd.Series(np.nan, index=s.index, dtype=float)
    return ewm_zscore(smoothed, scoring_com).reindex(s.index)


def cross_sectional_zscore(frame: pd.DataFrame) -> pd.DataFrame:
    """Same-day z across the curve — the ``XZscore`` term.

    ``frame`` is dates × bonds of the fitted spread-to-curve. Standardised **within each date**,
    which is what makes the term cross-sectional: it asks "rich versus its peers today", where the
    time-series term asks "rich versus its own history".
    """
    df = frame.astype(float)
    mu = df.mean(axis=1)
    sd = df.std(axis=1, ddof=1).replace(0.0, np.nan)
    return df.sub(mu, axis=0).div(sd, axis=0)


def build_bond_signals(
    s2c: pd.DataFrame,
    cfg: Optional[BondSignalConfig] = None,
) -> dict:
    """Per-bond richness signal from a dates × bonds spread-to-curve panel.

    Parameters
    ----------
    s2c
        Dates × bonds. In GSS this is ``FittedZspread``, the parallel spread that reprices the bond
        onto the fitted curve. In the ARBS port it is the spline **yield error in bp**
        (:class:`~MDP.FixedRateBonds.cash_spline.CashSpline`), which is the same object measured in
        yield rather than spread space: positive == cheap.

    Returns
    -------
    dict with ``ts_score``, ``xs_score``, ``signal`` and ``abs_signal`` frames, all dates × bonds.
    """
    cfg = cfg or BondSignalConfig()
    s2c = s2c.astype(float).sort_index()

    ts_score = s2c.apply(lambda col: ts_scoring(col, cfg.smoothing_halflife, cfg.scoring_com), axis=0)
    xs_score = cross_sectional_zscore(s2c)

    w = float(cfg.ts_weight)
    signal = w * ts_score + (1.0 - w) * xs_score
    # Where only one component exists, fall back to it rather than propagating NaN — the original
    # would emit NaN and the bond would simply never be selected, which silently shrinks the
    # universe early in a sample. Falling back keeps the early sample tradeable and is stated here.
    signal = signal.where(ts_score.notna() & xs_score.notna(), ts_score.fillna(xs_score))

    return {
        "ts_score": ts_score,
        "xs_score": xs_score,
        "signal": signal,
        "abs_signal": signal.abs(),
    }
