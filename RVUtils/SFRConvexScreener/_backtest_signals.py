"""Backtest-friendly per-(date, structure) signal records derived from
SFRConvexScreenerSnapshots."""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Dict, Iterable, List

from RVUtils.SFRConvexScreener._types import (
    SFRConvexScreenerSnapshot,
    StructureDef,
)


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


def build_signal_table_from_snapshots(
    snapshots: Iterable[SFRConvexScreenerSnapshot],
) -> Dict[datetime.date, List[BacktestSignal]]:
    """Flatten a sequence of screener snapshots into a date-keyed signal table."""
    out: Dict[datetime.date, List[BacktestSignal]] = {}
    for snap in snapshots:
        rows: List[BacktestSignal] = []
        for r in snap.results:
            primary = r.metrics_by_method.get(r.primary_method)
            if primary is None:
                continue
            asym = float(primary.asymmetry_ratio)
            flip = asym < 1.0
            stale = any("stale_smile_asof" in w for w in r.warnings)
            rows.append(
                BacktestSignal(
                    as_of=snap.as_of,
                    structure_def=r.structure_def,
                    direction=r.direction(),
                    flip=flip,
                    asymmetry_ratio=asym,
                    composite_score=float(r.composite_score),
                    mean_bp=float(primary.mean_bp),
                    std_bp=float(primary.std_bp),
                    rolldown_bp=float(r.rolldown_bp),
                    carry_3m_bp=float(r.carry_3m_bp),
                    is_stale=stale,
                )
            )
        out[snap.as_of] = rows
    return out
