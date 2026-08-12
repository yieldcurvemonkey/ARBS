"""Butterfly construction: wing selection, maturity weights, and the fly state variables.

Port of ``GSS_module.wing_selection`` / ``build_weights`` / ``Fly`` / ``build_flies``.

The weights deserve a note because they are unusual and deliberate. GSS solves

    w_L = -(M_R - M_B) / (M_R - M_L),   w_B = +1,   w_R = -(M_B - M_L) / (M_R - M_L)

on **maturities**, so ``w_L + w_R = -1`` and the three weights sum to zero. That makes the fly
*maturity*-neutral, not DV01-neutral and not cash-neutral — a choice the original states outright.
It is preserved here: re-weighting to DV01 neutrality would be a different strategy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from BT.gss_fly.config import FlyConfig
from BT.gss_fly.signals import ts_scoring

__all__ = ["wing_window", "select_wings", "build_weights", "FlyState", "build_fly_state", "scan_flies"]


def wing_window(belly_ttm: float, cfg: FlyConfig) -> tuple:
    """(lower, upper) TTM bounds wings may be drawn from, for a belly at ``belly_ttm``."""
    if belly_ttm < cfg.maturity_window_1:
        return belly_ttm - cfg.wing_range_1, belly_ttm + cfg.wing_range_1
    if belly_ttm < cfg.maturity_window_2:
        return belly_ttm - cfg.wing_range_2, belly_ttm + cfg.wing_range_2
    # Long end: the original searches left from the 20y bound and right effectively without limit.
    return cfg.maturity_window_2, belly_ttm + cfg.long_end_right_reach


def select_wings(curve: pd.DataFrame, belly: str, cfg: Optional[FlyConfig] = None) -> List[str]:
    """Pick the wings that maximise the richness gap to the belly.

    ``curve`` is indexed by bond id with columns ``ttm`` and ``signal``.

    Returns ``[left, belly, right]`` or ``[]`` when either side has no candidate.

    The objective is where this port deviates from the original — see
    :attr:`~BT.gss_fly.config.FlyConfig.wing_objective`. ``signal_gap`` maximises
    ``|signal_wing - signal_belly|``, which is what the docstring of the original describes.
    ``legacy_ttm_bug`` maximises ``|signal_wing - ttm_belly|``, which is what its code does.
    """
    cfg = cfg or FlyConfig()
    if belly not in curve.index:
        return []
    b = curve.loc[belly]
    lo, hi = wing_window(float(b["ttm"]), cfg)

    left = curve[(curve["ttm"] >= lo) & (curve["ttm"] < b["ttm"])]
    right = curve[(curve["ttm"] > b["ttm"]) & (curve["ttm"] <= hi)]
    left = left[left["signal"].notna()]
    right = right[right["signal"].notna()]
    if left.empty or right.empty:
        return []

    ref = float(b["ttm"]) if cfg.wing_objective == "legacy_ttm_bug" else float(b["signal"])
    if not np.isfinite(ref):
        return []

    return [
        (left["signal"] - ref).abs().idxmax(),
        belly,
        (right["signal"] - ref).abs().idxmax(),
    ]


def build_weights(maturities: Sequence[float]) -> List[float]:
    """Maturity weights for ``[left, belly, right]``; belly is always +1 before signing."""
    m_l, m_b, m_r = (float(x) for x in maturities)
    span = m_r - m_l
    if span == 0:
        raise ValueError("degenerate fly: left and right wing share a maturity")
    return [-((m_r - m_b) / span), 1.0, -((m_b - m_l) / span)]


@dataclass
class FlyState:
    """Everything the entry/exit gates need about one fly on one date."""

    fly_id: str
    legs: List[str]
    weights: List[float]
    z: float
    d_abs_z: float
    std_bp: float
    zsig_bp: float
    fly_yield_bp: float
    fly_s2c: float
    ttms: List[float]

    @property
    def direction(self) -> int:
        """+1 when the book holds the belly long (weights unflipped), -1 otherwise."""
        return 1 if self.weights[1] >= 0 else -1


def _compose(panel: pd.DataFrame, legs: Sequence[str], weights: Sequence[float]) -> pd.Series:
    sub = panel[list(legs)]
    return pd.Series((sub.to_numpy() * np.asarray(weights, dtype=float)).sum(axis=1), index=sub.index).where(
        sub.notna().all(axis=1)
    )


def build_fly_state(
    fly_id: str,
    legs: Sequence[str],
    weights: Sequence[float],
    *,
    s2c_panel: pd.DataFrame,
    yield_panel: pd.DataFrame,
    ttms: Sequence[float],
    asof: pd.Timestamp,
    cfg: Optional[FlyConfig] = None,
    sign_by_z: bool = True,
) -> Optional[FlyState]:
    """Compose a fly's series up to ``asof`` and evaluate its state variables there.

    Everything is strictly trailing: the z, its change, and the vol are all read at ``asof`` from
    series built only from data at or before ``asof``.
    """
    cfg = cfg or FlyConfig()
    legs = list(legs)
    if any(c not in s2c_panel.columns or c not in yield_panel.columns for c in legs):
        return None

    s2c_hist = _compose(s2c_panel.loc[:asof], legs, weights).dropna()
    if len(s2c_hist) < 5:
        return None

    z_hist = ts_scoring(s2c_hist, cfg.fly_smoothing_halflife, cfg.fly_scoring_com)
    if asof not in z_hist.index or not np.isfinite(z_hist.get(asof, np.nan)):
        return None

    w = list(weights)
    if sign_by_z:
        sgn = np.sign(z_hist.loc[asof])
        if sgn == 0:
            return None
        w = [x * sgn for x in w]
        # Re-composing with the signed weights only flips the sign of the series, so the |z| and
        # the vol are unchanged; recompute anyway so the recorded state matches the held position.
        s2c_hist = _compose(s2c_panel.loc[:asof], legs, w).dropna()
        z_hist = ts_scoring(s2c_hist, cfg.fly_smoothing_halflife, cfg.fly_scoring_com)
        if asof not in z_hist.index:
            return None

    y_hist = _compose(yield_panel.loc[:asof], legs, w).dropna()
    if asof not in y_hist.index:
        return None

    abs_z = z_hist.abs()
    std_bp = y_hist.ewm(halflife=cfg.std_halflife, min_periods=2).std().get(asof, np.nan)
    if not np.isfinite(std_bp):
        return None

    z_now = float(z_hist.loc[asof])
    d_abs = abs_z.diff().get(asof, np.nan)

    return FlyState(
        fly_id=fly_id,
        legs=legs,
        weights=[float(x) for x in w],
        z=z_now,
        d_abs_z=float(d_abs) if np.isfinite(d_abs) else np.nan,
        std_bp=float(std_bp),
        zsig_bp=float(abs(z_now) * std_bp),
        fly_yield_bp=float(y_hist.loc[asof]),
        fly_s2c=float(s2c_hist.loc[asof]),
        ttms=[float(t) for t in ttms],
    )


def scan_flies(
    curve: pd.DataFrame,
    *,
    s2c_panel: pd.DataFrame,
    yield_panel: pd.DataFrame,
    asof: pd.Timestamp,
    cfg: Optional[FlyConfig] = None,
) -> List[FlyState]:
    """Every candidate fly on ``asof``, ranked the way GSS ranks them.

    ``curve`` is the eligible universe for the date, indexed by bond id, with ``ttm``, ``maturity``
    and ``signal``. Bellies are scanned in descending ``|signal|`` — the richest and cheapest bonds
    are considered first, exactly as ``build_flies`` sorts on ``AbsSignal``.
    """
    cfg = cfg or FlyConfig()
    ranked = curve.dropna(subset=["signal"]).reindex(
        curve["signal"].abs().sort_values(ascending=False).index
    ).dropna(subset=["signal"])
    if cfg.max_bellies_per_date:
        ranked = ranked.head(cfg.max_bellies_per_date)

    out: List[FlyState] = []
    seen = set()
    for belly in ranked.index:
        legs = select_wings(curve, belly, cfg)
        if len(legs) != 3:
            continue
        fly_id = "-".join(legs)
        if fly_id in seen:
            continue
        seen.add(fly_id)
        try:
            weights = build_weights([curve.loc[c, "maturity"] for c in legs])
        except (ValueError, KeyError):
            continue
        st = build_fly_state(
            fly_id,
            legs,
            weights,
            s2c_panel=s2c_panel,
            yield_panel=yield_panel,
            ttms=[curve.loc[c, "ttm"] for c in legs],
            asof=asof,
            cfg=cfg,
        )
        if st is not None:
            out.append(st)
    return out
