"""Backtest-friendly per-(date, structure) signal records derived from
SFRConvexScreenerSnapshots."""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from RVUtils.SFRConvexScreener._types import StructureDef


@dataclass(frozen=True)
class BacktestSignal:
    as_of: datetime.date
    structure_def: StructureDef
    direction: str  # human-readable PAY/RECEIVE string
    flip: bool      # True iff asymmetry_ratio < 1 (long-price / receiver convention)
    asymmetry_ratio: float
    composite_score: float
    mean_bp: float
    std_bp: float
    rolldown_bp: float
    carry_3m_bp: float
    is_stale: bool
