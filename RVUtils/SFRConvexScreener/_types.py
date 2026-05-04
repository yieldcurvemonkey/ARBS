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

    # Methodology flag — when True, use observed OTM premiums with OI >= 100
    # and no SABR extrapolation per JPM Tech Appendix A.
    jpm_method: bool = False
    # Ghost-point extension distance (bp of price per ghost). Override
    # only if you want non-default tail extrapolation reach. ARBS/JPM default
    # is 5bp.
    ghost_extension_bps: Optional[float] = None

    # Curve / data sources
    curve_source: str = "BARCHART_STIRF-RL"
    curve_name: str = "USD-SOFR-1D-Q12STIRT"
    options_source: str = "BARCHART_STIRFO-QL"
    # SABR smile fetch strategy. ``listed`` pulls every CME-listed strike
    # within the 250bp ATM cap (≈30–60 strikes/contract); ``delta_sparse``
    # pulls the 5/10/.../50-delta C+P grid (≈20 strikes/contract). The
    # sparse path is ~2x faster end-to-end against live Barchart but
    # produces materially different rankings on calendars and butterflies
    # because the 4th-order BL spline through 20 widely-spaced delta knots
    # oscillates in the wings — verified on 2026-04-28 where sparse gave a
    # M27/U27/Z27 fly asymmetry of 35.8 vs 0.97 from listed (same input
    # contracts; ~50 strikes vs ~20 strikes is the only difference). The
    # default stays at ``listed`` per the methodology-preservation
    # requirement; sparse remains opt-in for callers that prioritise
    # outright-only screens (where the difference is ≤ 5–10 %).
    smile_strike_mode: str = "listed"

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
    horizon_days: int = 63  # ~3M for the historical realised payoff comparison
    rolldown_horizon: str = "1m"  # IRSwapValue.ROLL_BPS_RUNNING horizon — 3m
    # collapses the SR3 IMM-IMM 3M schedule (effective == termination), so
    # 1m is the safe default. Override only if structures support it.
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


def _format_direction(sd: "StructureDef", *, flip: bool = False) -> str:
    """Render a structure's preferred trade direction as PAY/RECEIVE strings.

    ``flip=False`` returns the long-rate (as-enumerated) interpretation;
    ``flip=True`` returns the long-price (mirror) interpretation. Used by
    :meth:`StructureResult.direction` to surface a 1.5×-asymmetry edge in
    the natural trader phrasing.
    """
    legs = sd.legs
    sign = -1.0 if flip else 1.0
    if sd.structure_type is StructureType.OUTRIGHT:
        leg = legs[0]
        eff_w = sign * float(leg.weight)
        verb = "PAY" if eff_w > 0 else "RECEIVE"
        return f"{verb} {leg.contract}"
    if sd.structure_type is StructureType.CALENDAR:
        front = next((l for l in legs if l.weight > 0), legs[0])
        back = next((l for l in legs if l.weight < 0), legs[-1])
        if flip:
            return f"RECEIVE {front.contract} / PAY {back.contract}"
        return f"PAY {front.contract} / RECEIVE {back.contract}"
    if sd.structure_type is StructureType.BUTTERFLY:
        wings = [l.contract for l in legs if l.weight > 0]
        belly = [l.contract for l in legs if l.weight < 0]
        if not (len(wings) == 2 and len(belly) == 1):
            return ""
        if flip:
            return (
                f"RECEIVE {wings[0]}+{wings[1]} / PAY 2x {belly[0]} (long-price fly)"
            )
        return f"PAY {wings[0]}+{wings[1]} / RECEIVE 2x {belly[0]} (long-rate fly)"
    return ""


@dataclass(frozen=True)
class StructureResult:
    structure_def: "StructureDef"
    metrics_by_method: Dict[str, Any]  # Dict[str, PayoffMetrics] (forward ref)
    primary_method: str
    carry_3m_bp: float          # Current weighted structure rate × 100 (bp)
    rolldown_bp: float          # Roll-down for the configured horizon (default 1M)
    iv_rv_diagnostics: Tuple[Any, ...]  # Tuple[IVRVDiagnostic, ...]
    historical: Optional[Any]  # Optional[HistoricalAsymmetry]
    warnings: Tuple[str, ...]
    composite_score: float
    rank: int
    rolldown_horizon: str = "1m"

    def direction(self) -> str:
        """Human-readable preferred trade direction.

        Structure weights are in rate-space (long-rate convention). A>1 →
        the long-rate position (as enumerated) has positive asymmetric
        edge; A<1 → flip the direction.
        """
        primary = self.metrics_by_method.get(self.primary_method)
        if primary is None:
            return ""
        a = primary.asymmetry_ratio
        if not isinstance(a, (int, float)) or a != a:  # NaN check
            return ""
        flip = a < 1.0
        return _format_direction(self.structure_def, flip=flip)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "structure_id": self.structure_def.structure_id,
            "structure_type": self.structure_def.structure_type.value,
            "legs": [
                {"contract": l.contract, "weight": l.weight, "price": l.price, "dv01": l.dv01}
                for l in self.structure_def.legs
            ],
            "carry_3m_bp": self.carry_3m_bp,
            "rolldown_bp": self.rolldown_bp,
            "rolldown_horizon": self.rolldown_horizon,
            "direction": self.direction(),
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
            stale_legs = [
                w.split("::")[0] for w in r.warnings if "stale_smile_asof" in w
            ]
            row = {
                "structure_id": r.structure_def.structure_id,
                "type": r.structure_def.structure_type.value,
                "direction": r.direction(),
                "rank": r.rank,
                "composite_score": r.composite_score,
                "carry_3m_bp": r.carry_3m_bp,
                "rolldown_bp": r.rolldown_bp,
                "rolldown_horizon": r.rolldown_horizon,
                "primary_method": r.primary_method,
                "is_stale": bool(stale_legs),
                "stale_legs": ",".join(stale_legs) if stale_legs else "",
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
