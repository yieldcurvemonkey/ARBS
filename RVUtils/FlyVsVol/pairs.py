"""Curve-mode (two-contract) fly-vs-vol metrics: the n=2 basis.

For an adjacent pair (front, back):

    spread_bp        = (fwd_back - fwd_front) * 100
    median_spread_bp = (med_back - med_front) * 100
    pair_rent_bp     = spread_bp - median_spread_bp
                     = pair_fit_bp + pair_rent_skew_bp
    pair_fit_bp      = fwd_resid_front - fwd_resid_back      (BL-fit part)
    pair_rent_skew_bp= mm_back - mm_front                    (options-only part)

Negative pair_rent = the traded curve is flatter than the option-implied
median path (e.g. a back-leg dovish fork dragging its mean below its median).
The convergence expression is the two-leg median-path steepener: curve in
futures against the tails that create the gap, delta-hedged.

Input is the per-contract daily panel (one row per (as_of, symbol) with
forward_rate / mean_rate / median_rate / mm_bp / fwd_resid_bp / quality
diagnostics); ``build_pair_history`` reshapes it into the same
(as_of, label) long format the fly screener uses, so ``history_zscores`` and
``series_half_life`` apply unchanged.
"""
from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

import pandas as pd

__all__ = ["adjacent_pairs", "build_pair_history"]

_REQUIRED = ("as_of", "symbol", "forward_rate", "median_rate", "mm_bp", "fwd_resid_bp")

_IMM_ORDER = {"H": 0, "M": 1, "U": 2, "Z": 3}


def _quarterly_sort_key(symbol: str):
    """Chronological key for SFR-style quarterly codes (e.g. SFRU26 -> (26, 2))."""
    code, year = symbol[-3], symbol[-2:]
    if code in _IMM_ORDER and year.isdigit():
        return (int(year), _IMM_ORDER[code])
    return (9999, symbol)  # unknown formats sort last, stably


def adjacent_pairs(symbols: Sequence[str]) -> List[Tuple[str, str]]:
    symbols = list(symbols)
    return [(symbols[i], symbols[i + 1]) for i in range(len(symbols) - 1)]


def build_pair_history(
    panel: pd.DataFrame,
    pairs: Optional[Sequence[Tuple[str, str]]] = None,
    *,
    max_abs_fwd_resid_bp: float = 2.5,
    max_pre_norm_mass: float = 1.02,
) -> pd.DataFrame:
    """Long-format pair metrics per (as_of, label='FRONT-BACK').

    A pair-date requires both legs present that date. ``quality_ok`` is True
    when both legs pass the forward-residual gate (and the mass gate when the
    ``pre_norm_mass`` column is present); rows are never dropped, only flagged.
    """
    missing = [c for c in _REQUIRED if c not in panel.columns]
    if missing:
        raise ValueError(f"panel missing columns {missing}")
    if pairs is None:
        order = sorted(set(panel["symbol"]), key=_quarterly_sort_key)
        pairs = adjacent_pairs(order)

    idx = panel.set_index(["as_of", "symbol"]).sort_index()
    rows = []
    for front, back in pairs:
        try:
            f = idx.xs(front, level="symbol")
            b = idx.xs(back, level="symbol")
        except KeyError:
            continue
        j = f.join(b, how="inner", lsuffix="_f", rsuffix="_b")
        if j.empty:
            continue
        out = pd.DataFrame(index=j.index)
        out["label"] = f"{front}-{back}"
        out["front"], out["back"] = front, back
        out["spread_bp"] = (j["forward_rate_b"] - j["forward_rate_f"]) * 100
        out["median_spread_bp"] = (j["median_rate_b"] - j["median_rate_f"]) * 100
        out["pair_rent_bp"] = out["spread_bp"] - out["median_spread_bp"]
        out["pair_rent_skew_bp"] = j["mm_b"] - j["mm_f"] if "mm_b" in j else (
            j["mm_bp_b"] - j["mm_bp_f"]
        )
        out["pair_fit_bp"] = j["fwd_resid_bp_f"] - j["fwd_resid_bp_b"]
        out["fwd_resid_front_bp"] = j["fwd_resid_bp_f"]
        out["fwd_resid_back_bp"] = j["fwd_resid_bp_b"]
        ok = (j["fwd_resid_bp_f"].abs() <= max_abs_fwd_resid_bp) & (
            j["fwd_resid_bp_b"].abs() <= max_abs_fwd_resid_bp
        )
        if "pre_norm_mass_f" in j:
            ok &= (j["pre_norm_mass_f"] <= max_pre_norm_mass) & (
                j["pre_norm_mass_b"] <= max_pre_norm_mass
            )
        out["quality_ok"] = ok
        rows.append(out.reset_index())
    if not rows:
        return pd.DataFrame()
    hist = pd.concat(rows, ignore_index=True).sort_values(["label", "as_of"])
    return hist.reset_index(drop=True)
