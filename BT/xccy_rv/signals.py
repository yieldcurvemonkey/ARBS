"""The five RVPF signals and the Grinold-Kahn combination.

Direct port of ``jpm_pfin/RVPF/signal_building.py``. Every window and weight is in
:mod:`BT.xccy_rv.config`.

One property of the original is worth naming because it is easy to mistake for a bug. Scoring is

    score = raw / ewmstd(raw)

with **no mean subtraction**. That is not a z-score: it is a vol-scaled *level*. For a carry
signal that is defensible and probably deliberate — you want to be long carry when carry is high
outright, not merely high relative to its own recent average — but it means a persistently
positive carry produces a persistently large score, and |score| does not sit around 1.
"""

from __future__ import annotations

from typing import Dict, Optional

import numpy as np
import pandas as pd

from BT.xccy_rv.config import SignalConfig
from BT.xccy_rv.data import XccyPanel

__all__ = ["clip_outliers", "realized_vol", "build_signals", "combine_alpha"]


def clip_outliers(returns: pd.DataFrame, n_std: float) -> pd.DataFrame:
    """``swap_returns_df[swap_returns_df > n*std] = 0`` — the original's outlier rule.

    Note it is one-sided and it *zeroes* rather than clips: a return more than ``n`` sample
    standard deviations above the mean is replaced by zero, and large negative returns are left
    alone. Reproduced exactly; the asymmetry is the original's.
    """
    out = returns.copy()
    thresh = returns.std()
    for c in out.columns:
        out.loc[out[c] > n_std * thresh[c], c] = 0.0
    return out


def realized_vol(returns: pd.DataFrame, halflife: int) -> pd.DataFrame:
    """``ewmstd(returns, halflife) * sqrt(halflife)`` — the original's vol scale.

    The multiplier is ``sqrt(halflife)``, not ``sqrt(252)``: this is not an annualisation, it is a
    scaling to the signal's own horizon, and every alpha inherits it.
    """
    return returns.ewm(halflife=halflife, min_periods=halflife).std() * np.sqrt(halflife)


def _score(raw: pd.DataFrame, cfg: SignalConfig) -> pd.DataFrame:
    sd = raw.ewm(halflife=cfg.scoring_halflife, min_periods=cfg.scoring_halflife).std()
    out = raw / sd.replace(0.0, np.nan)
    if cfg.smoothing_halflife:
        out = out.ewm(halflife=cfg.smoothing_halflife, min_periods=cfg.smoothing_halflife).mean()
    return out


def build_signals(panel: XccyPanel, cfg: Optional[SignalConfig] = None) -> Dict[str, pd.DataFrame]:
    """Raw signals, their scores, and the per-signal alphas.

    Returns a dict with ``vol``, ``raw_1..raw_5``, ``score_1..score_5`` and ``alpha_1..alpha_5``,
    each a dates × instruments frame. A signal whose inputs the panel does not carry comes back
    as all-NaN rather than being silently dropped, so a mis-specified weight vector is visible.
    """
    cfg = cfg or SignalConfig()
    rets = clip_outliers(panel.returns, cfg.outliers_std)
    vol = realized_vol(rets, cfg.vol_halflife)

    carry = panel.carry()
    raw1 = carry.reindex_like(vol) / vol

    d_carry = panel.fwd_basis.diff(cfg.carry_shift)
    d_carry = d_carry.ewm(halflife=cfg.carry_change_halflife, min_periods=cfg.carry_change_halflife).mean()
    raw2 = d_carry.reindex_like(vol) / vol

    if panel.short_basis is not None:
        st = panel.short_basis.ewm(halflife=cfg.momentum_halflife_st, min_periods=cfg.momentum_halflife_st).mean()
        lt = panel.short_basis.ewm(halflife=cfg.momentum_halflife_lt, min_periods=cfg.momentum_halflife_lt).mean()
        raw3 = (st - lt).reindex_like(vol)
    else:
        raw3 = pd.DataFrame(np.nan, index=vol.index, columns=vol.columns)

    if panel.fx_spot is not None:
        fx = panel.fx_spot.reindex_like(vol)
        fx_carry = fx.diff().ewm(halflife=cfg.carry_change_halflife, min_periods=cfg.carry_change_halflife).mean()
        fx_vol = fx.ewm(halflife=cfg.vol_halflife, min_periods=cfg.vol_halflife).std() * np.sqrt(cfg.vol_halflife)
        raw4 = fx_carry / fx_vol.replace(0.0, np.nan)
    else:
        raw4 = pd.DataFrame(np.nan, index=vol.index, columns=vol.columns)

    raw5 = (
        panel.credit_spread.reindex_like(vol)
        if panel.credit_spread is not None
        else pd.DataFrame(np.nan, index=vol.index, columns=vol.columns)
    )

    out: Dict[str, pd.DataFrame] = {"vol": vol}
    for i, raw in enumerate([raw1, raw2, raw3, raw4, raw5], start=1):
        score = _score(raw, cfg)
        out[f"raw_{i}"] = raw
        out[f"score_{i}"] = score
        out[f"alpha_{i}"] = vol * score
    return out


def combine_alpha(signals: Dict[str, pd.DataFrame], cfg: Optional[SignalConfig] = None) -> pd.DataFrame:
    """``alpha = Σ w_i · vol · score_i`` — the Grinold-Kahn form the original uses."""
    cfg = cfg or SignalConfig()
    total: Optional[pd.DataFrame] = None
    for i, w in enumerate(cfg.weights, start=1):
        if w == 0.0:
            continue
        a = signals[f"alpha_{i}"] * w
        total = a if total is None else total.add(a, fill_value=0.0)
    if total is None:
        raise ValueError("every signal weight is zero — the book has no alpha")
    return total
