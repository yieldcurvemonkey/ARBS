"""Types and configuration for the SFR Convex Linear Structure Screener."""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


class StructureType(Enum):
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
    calendar_gaps: Tuple[int, ...] = (1, 2, 4)
    fly_gaps: Tuple[int, ...] = (1, 2, 4)

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
