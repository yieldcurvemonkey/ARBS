"""The linear-shadow decomposition.

A butterfly is exactly the sum of two belly-versus-wing spreads::

    fly = 2*belly - front - back = (belly - front) + (belly - back)

so if a "fly mean reversion" result is really a directional or curve trade, it
will show up as the same edge on one of those simpler instruments -- which cost
2 legs to trade instead of 3, and on the outright belly only 1. Running the
identical signal on each shadow is the diagnostic that killed a whole framework
in the prior lab, and it is cheap: same engine, same signal, different level
panel.
"""
from __future__ import annotations

from typing import Dict, Optional, Sequence

import numpy as np
import pandas as pd

from RVUtils.MeanRev.engine import MRConfig, leg_round_trip_bp, run_backtest

__all__ = ["shadow_levels", "shadow_table", "SHADOW_LEGS", "SHADOW_CONTRACTS"]

#: number of futures legs each shadow instrument costs to trade
SHADOW_LEGS: Dict[str, int] = {
    "fly": 3, "belly": 1, "belly_vs_front": 2, "belly_vs_back": 2, "wings_curve": 2,
}

#: number of **contracts** each shadow instrument costs to trade. This differs
#: from the leg count in exactly one place and it is the place that matters: a
#: ``1/-2/1`` butterfly is three legs but **four contracts**, because the belly
#: is two. Costing the fly per leg charges it 1.5bp round trip against the 2.0bp
#: it actually pays, while every shadow's leg count and contract count coincide
#: -- so per-leg costing hands the butterfly a **0.5bp per trade advantage** in
#: the one comparison the shadow test exists to make.
SHADOW_CONTRACTS: Dict[str, int] = {
    "fly": 4, "belly": 1, "belly_vs_front": 2, "belly_vs_back": 2, "wings_curve": 2,
}


def shadow_levels(struct: pd.DataFrame, *, date_col: str = "as_of",
                  n_legs: int = 3, scale: float = 100.0) -> Dict[str, pd.DataFrame]:
    """Build one wide ``date x key`` level panel per shadow instrument.

    Keys are the butterfly's own keys throughout, so the same signal panel
    indexes every shadow without any remapping. Values are in bp.

    ``belly`` is the outright belly rate in bp -- a level in the hundreds, not a
    spread. Its z-score is therefore a *rates-direction* signal; that is the
    point of including it.
    """
    s = struct.copy()
    s[date_col] = pd.to_datetime(s[date_col])
    f = s["leg0_value"].astype(float)
    b = s["leg1_value"].astype(float)
    k = s[f"leg{n_legs-1}_value"].astype(float)
    built = {
        "fly": (2.0 * b - f - k) * scale,
        "belly": b * scale,
        "belly_vs_front": (b - f) * scale,
        "belly_vs_back": (b - k) * scale,
        "wings_curve": (k - f) * scale,
    }
    out = {}
    for name, vals in built.items():
        tmp = s[[date_col, "key"]].copy()
        tmp["v"] = vals.to_numpy()
        out[name] = tmp.pivot_table(index=date_col, columns="key", values="v",
                                    aggfunc="first").sort_index()
    return out


def shadow_table(
    signal: pd.DataFrame, shadows: Dict[str, pd.DataFrame], *,
    base: MRConfig, gate: Optional[pd.DataFrame] = None,
    per_leg_one_way_bp: float = 0.25, cost_mode: str = "per_leg",
    names: Sequence[str] = ("fly", "belly", "belly_vs_front", "belly_vs_back"),
) -> pd.DataFrame:
    """Run the identical signal on each shadow and tabulate the comparison.

    Each instrument is charged **its own** cost, because the shadow test is only
    meaningful if each pays its own spread -- charging them all the fly's cost
    would manufacture the conclusion that the fly is best.

    ``cost_mode``:

    ``'per_leg'``
        the prior lab's convention -- ``2 * n_legs * half_spread``, so a fly pays
        1.5bp and the outright belly 0.5bp. Kept as the default so the published
        fly mean-reversion numbers stay reproducible.
    ``'per_contract'``
        the correct convention for futures -- ``2 * n_contracts * half_spread``.
        Identical to ``per_leg`` for every shadow *except the butterfly*, whose
        belly is two contracts: 2.0bp, not 1.5bp. Per-leg costing therefore hands
        the fly a 0.5bp per-trade advantage over its own shadows, which is
        backwards for a test designed to find out whether the fly is worth its
        extra legs.

    Read the result as: if ``belly_vs_front`` or ``belly_vs_back`` matches the
    fly, the signal is a calendar trade; if ``belly`` matches it, it is a
    directional rates trade.
    """
    import dataclasses

    if cost_mode not in ("per_leg", "per_contract"):
        raise ValueError("cost_mode must be 'per_leg' or 'per_contract'")
    rows = []
    for name in names:
        lv = shadows.get(name)
        if lv is None:
            continue
        n_legs = SHADOW_LEGS.get(name, 3)
        n_units = (n_legs if cost_mode == "per_leg"
                   else SHADOW_CONTRACTS.get(name, 4))
        cfg = dataclasses.replace(
            base, round_trip_cost_bp=leg_round_trip_bp(n_units, per_leg_one_way_bp))
        res = run_backtest(cfg, levels=lv, signal=signal, gate=gate)
        m = res.metrics
        rows.append({
            "instrument": name, "n_legs": n_legs,
            "n_contracts": SHADOW_CONTRACTS.get(name, 4),
            "round_trip_bp": cfg.round_trip_cost_bp,
            "n_trades": m["n_trades"],
            "total_gross_bp": round(m["total_gross_bp"], 1),
            "total_net_bp": round(m["total_net_bp"], 1),
            "avg_net_bp": round(m["avg_net_bp"], 3) if np.isfinite(m["avg_net_bp"]) else np.nan,
            "hit_rate": round(m["hit_rate"], 3) if np.isfinite(m["hit_rate"]) else np.nan,
            "sharpe": round(m["sharpe"], 3) if np.isfinite(m["sharpe"]) else np.nan,
            "max_dd_bp": round(m["max_dd_bp"], 1),
            "avg_hold": round(m["avg_hold_days"], 1) if np.isfinite(m["avg_hold_days"]) else np.nan,
        })
    out = pd.DataFrame(rows)
    if not out.empty and "fly" in set(out["instrument"]):
        fly_net = float(out.loc[out["instrument"] == "fly", "total_net_bp"].iloc[0])
        fly_sh = float(out.loc[out["instrument"] == "fly", "sharpe"].iloc[0])
        out["beats_fly_net"] = out["total_net_bp"] > fly_net
        out["beats_fly_sharpe"] = out["sharpe"] > fly_sh
        out.attrs["verdict"] = (
            "SHADOWED - a simpler instrument beats the fly on net bp"
            if bool(out.loc[out["instrument"] != "fly", "beats_fly_net"].any())
            else "fly beats every linear shadow on net bp")
    return out
