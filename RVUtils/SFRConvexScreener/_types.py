"""Types and configuration for the SFR Convex Linear Structure Screener."""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


class StructureType(Enum):
    OUTRIGHT = "outright"
    CALENDAR = "calendar"
    BUTTERFLY = "butterfly"


class JointMethod(Enum):
    COMMON_STATE = "common_state"
    HISTORICAL_GAUSSIAN_COPULA = "historical_gaussian_copula"
    PERFECT_CORRELATION = "perfect_correlation"


@dataclass(frozen=True)
class Leg:
    contract: str
    weight: float
    price: float
    dv01: float = 25.0


@dataclass(frozen=True)
class StructureDef:
    structure_id: str
    structure_type: StructureType
    legs: Tuple[Leg, ...]


@dataclass
class SFRConvexScreenerConfig:
    # Universe
    universe_size: int = 12
    include_outrights: bool = True
    calendar_gaps: Tuple[int, ...] = (1, 2, 4)
    fly_gaps: Tuple[int, ...] = (1, 2, 4)

    # Methodology flag — when True, use raw market vols (no SABR
    # extrapolation) per JPM Tech Appendix A.
    jpm_method: bool = False

    # Curve / data sources
    curve_source: str = "BARCHART_STIRF-RL"
    curve_name: str = "USD-SOFR-1D-Q12STIRT"
    options_source: str = "BARCHART_STIRFO-QL"

    # Joint distribution
    joint_methods: Tuple[JointMethod, ...] = (
        JointMethod.COMMON_STATE,
        JointMethod.HISTORICAL_GAUSSIAN_COPULA,
        JointMethod.PERFECT_CORRELATION,
    )
    primary_joint_method: JointMethod = JointMethod.COMMON_STATE
    correlation_window: int = 60
    n_simulations: int = 100_000

    # Carry / horizon
    horizon_days: int = 63  # ~3M
    historical_lookback_years: int = 5

    # Filters
    min_open_interest_per_leg: int = 5_000
    min_avg_daily_volume_per_leg: int = 1_000
    max_bid_ask_bp: float = 0.5
    min_carry_adjusted_ev_bp: float = 0.5

    # Scoring weights: (asymmetry, p_profit, ev+carry, tail_ratio)
    score_weights: Tuple[float, float, float, float] = (0.4, 0.2, 0.3, 0.1)

    # Output
    output_root: str = "data/screener_results/sfr_convex_screener"

    # Reproducibility for copula sampling
    random_seed: int = 17


@dataclass(frozen=True)
class StructureResult:
    structure_def: "StructureDef"
    metrics_by_method: Dict[str, Any]  # Dict[str, PayoffMetrics] (forward ref)
    primary_method: str
    carry_3m_bp: float
    rolldown_3m_bp: float
    iv_rv_diagnostics: Tuple[Any, ...]  # Tuple[IVRVDiagnostic, ...]
    historical: Optional[Any]  # Optional[HistoricalAsymmetry]
    warnings: Tuple[str, ...]
    composite_score: float
    rank: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "structure_id": self.structure_def.structure_id,
            "structure_type": self.structure_def.structure_type.value,
            "legs": [
                {"contract": l.contract, "weight": l.weight, "price": l.price, "dv01": l.dv01}
                for l in self.structure_def.legs
            ],
            "carry_3m_bp": self.carry_3m_bp,
            "rolldown_3m_bp": self.rolldown_3m_bp,
            "metrics_by_method": {
                name: m.to_dict() for name, m in self.metrics_by_method.items()
            },
            "primary_method": self.primary_method,
            "iv_rv_diagnostics": [
                {
                    "contract": d.contract,
                    "iv_bp": d.iv_bp,
                    "rv_bp": d.rv_bp,
                    "iv_rv_ratio": d.iv_rv_ratio,
                }
                for d in self.iv_rv_diagnostics
            ],
            "historical": (
                None
                if self.historical is None
                else {
                    "median_asymmetry": self.historical.median_asymmetry,
                    "p95_asymmetry": self.historical.p95_asymmetry,
                    "n_observations": self.historical.n_observations,
                    "current_rn_percentile": self.historical.current_rn_percentile,
                }
            ),
            "warnings": list(self.warnings),
            "composite_score": self.composite_score,
            "rank": self.rank,
        }


@dataclass(frozen=True)
class SFRConvexScreenerSnapshot:
    as_of: datetime.date
    results: Tuple[StructureResult, ...]
    config_summary: Dict[str, Any]
    run_warnings: Tuple[str, ...] = ()

    def to_dataframe(self) -> pd.DataFrame:
        rows = []
        for r in self.results:
            primary = r.metrics_by_method.get(r.primary_method)
            row = {
                "structure_id": r.structure_def.structure_id,
                "type": r.structure_def.structure_type.value,
                "rank": r.rank,
                "composite_score": r.composite_score,
                "carry_3m_bp": r.carry_3m_bp,
                "rolldown_3m_bp": r.rolldown_3m_bp,
                "primary_method": r.primary_method,
            }
            if primary is not None:
                row.update(primary.to_dict())
            rows.append(row)
        return pd.DataFrame(rows)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "as_of": self.as_of.isoformat(),
            "config": self.config_summary,
            "run_warnings": list(self.run_warnings),
            "results": [r.to_dict() for r in self.results],
        }
