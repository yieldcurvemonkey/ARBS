"""Historical realized payoff distribution for benchmark comparison."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
import pandas as pd

from RVUtils.SFRConvexScreener._types import Leg


@dataclass(frozen=True)
class HistoricalAsymmetry:
    median_asymmetry: float
    p95_asymmetry: float
    n_observations: int
    current_rn_percentile: float


def rolling_structure_payoffs_bp(
    price_panel: pd.DataFrame,
    *,
    legs: Sequence[Leg],
    horizon_days: int = 63,
) -> pd.Series:
    """For each date in price_panel, compute the structure P&L (in bp) over the
    next ``horizon_days`` business days."""
    contracts = [leg.contract for leg in legs]
    weights = np.array([leg.weight for leg in legs], dtype=float)
    sub = price_panel[contracts].dropna(how="any")
    rate_panel = 100.0 - sub
    horizon_rate_change = rate_panel.shift(-horizon_days) - rate_panel
    payoff_pct = horizon_rate_change.to_numpy() @ weights
    return pd.Series(payoff_pct * 100.0, index=sub.index, name="payoff_bp")


def historical_asymmetry_summary(
    samples_bp: pd.Series, *, current_rn_asymmetry: float,
) -> HistoricalAsymmetry:
    s = samples_bp.dropna()
    if len(s) < 5:
        return HistoricalAsymmetry(
            median_asymmetry=float("nan"),
            p95_asymmetry=float("nan"),
            n_observations=len(s),
            current_rn_percentile=float("nan"),
        )
    pos = s[s > 0]
    neg = s[s < 0]
    upper = float(pos.mean() * len(pos) / len(s)) if len(pos) else 0.0
    lower = float(abs(neg.mean() * len(neg) / len(s))) if len(neg) else 0.0
    realized_asym = upper / lower if lower > 0 else float("inf")
    pct = float(s.rank().iloc[-1] / len(s)) if len(s) else float("nan")
    return HistoricalAsymmetry(
        median_asymmetry=float(realized_asym),
        p95_asymmetry=float(realized_asym),
        n_observations=len(s),
        current_rn_percentile=pct,
    )
