"""Daily panels: forward par rates, implied vols, and the funding factor.

Panels are constant-maturity by construction (today's 10Y10Y is priced fresh
every day). Positions age; panels do not. Never join one to the other without
going through ``replication``, which owns the aging.
"""
from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

import pandas as pd

from RVUtils.StrikelessVol.conventions import slope_bp
from RVUtils.StrikelessVol.universe import ForwardLeg, ForwardPair

logger = logging.getLogger(__name__)

PANEL_DIR = Path(__file__).resolve().parents[2] / "notebooks" / "data" / "strikeless_vol"

__all__ = ["PANEL_DIR", "forward_rate_panel", "spread_panel"]


def forward_rate_panel(
    curve_name: str,
    dates: Sequence[dt.date],
    legs: Iterable[ForwardLeg],
    *,
    source: str = "GSQUANT-RL",
    mdp=None,
    cache_path: Optional[str | Path] = None,
    show_progress: bool = False,
) -> pd.DataFrame:
    """Constant-maturity forward par rates (decimals), one column per leg.

    Dates the provider cannot serve are dropped. They are never forward-filled:
    a filled day is a manufactured zero-change observation, and every realized
    vol and every changes-regression in this package would inherit the bias.
    """
    legs = list(legs)
    if cache_path and Path(cache_path).exists():
        cached = pd.read_parquet(cache_path)
        cached.index = pd.to_datetime(cached.index)
        wanted = pd.to_datetime(pd.Index(list(dates)))
        if wanted.isin(cached.index).all():
            return cached.loc[cached.index.isin(wanted), [l.label for l in legs]]

    if mdp is None:
        from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

        mdp = IRSwapsMDP(source=source)

    curve_map = mdp.bulk_get_data(
        {"curve_name": curve_name, "timestamps": list(dates)}
    )

    rows: List[dict] = []
    for ts, curve in curve_map.items():
        if curve is None:
            continue
        rec: dict = {}
        try:
            for leg in legs:
                swap = curve.build_irswap(fwd=leg.fwd, tenor=leg.tail)
                rec[leg.label] = float(curve.fair_rate(swap))
        except Exception:  # a curve that cannot price a leg contributes nothing
            logger.warning("skipping %s on %s", curve_name, ts, exc_info=True)
            continue
        rec["date"] = ts.date() if hasattr(ts, "date") else ts
        rows.append(rec)

    if not rows:
        return pd.DataFrame(columns=[l.label for l in legs])

    panel = pd.DataFrame(rows).set_index("date").sort_index()
    panel.index = pd.to_datetime(panel.index)
    panel = panel[[l.label for l in legs]]

    if cache_path:
        Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
        panel.to_parquet(cache_path)
    return panel


def spread_panel(rates: pd.DataFrame, pair: ForwardPair) -> pd.Series:
    """The pair's slope in bp: longer forward minus shorter forward."""
    s = rates[pair.short.label].astype(float)
    l = rates[pair.long.label].astype(float)
    out = (l - s) * 10_000.0
    out.name = pair.name
    return out
