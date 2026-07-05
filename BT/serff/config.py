"""Configuration dataclasses for the SERFF fair-value model and backtest.

Every numeric choice called out as a calibration parameter in the design spec
is surfaced here (repo convention: dataclass configs, cf. RegressionRVConfig).
Defaults reproduce the standalone prototype exactly.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple


@dataclass(frozen=True)
class SerffDataConfig:
    """Panel construction and publication-lag alignment."""

    start: datetime.date = datetime.date(2018, 4, 2)
    end: Optional[datetime.date] = None  # None -> latest published fixing

    # Publication alignment.  'contemporaneous' reproduces the prototype
    # (weekly series ffilled on reference dates -- look-ahead for trading);
    # 'published' makes each input usable only after its release timestamp.
    alignment: str = "contemporaneous"

    # SOFR/EFFR fixings publish ~08:00 ET the next business day.  For an
    # end-of-day decision at `decision_time_et`, the fixing for the decision
    # date itself is never available; the previous business day's is.
    fixing_publication_lag_bd: int = 1

    # H.4.1 releases Thursday ~16:30 ET for the prior Wednesday.  With an
    # end-of-day decision cutoff earlier than the release time, Thursday's
    # release is usable from Friday: reference Wednesday + 1 (release) + 1.
    h41_release_lag_days: int = 1
    h41_available_next_day: bool = True

    # BEA advance estimate ~one month after quarter end; revisions ignored
    # (documented limitation -- DBnomics serves final vintages).
    gdp_publication_lag_days: int = 30

    decision_time_et: datetime.time = datetime.time(16, 0)


@dataclass(frozen=True)
class SerffModelConfig:
    """Three-layer model calibration parameters (defaults = prototype)."""

    # -- regimes (boundary dates are left-inclusive of the next regime) ----
    regime_boundaries: Tuple[datetime.date, ...] = (
        datetime.date(2020, 3, 1),    # pre-covid QT1 | flood
        datetime.date(2021, 4, 1),    # flood | RRP abundance
        datetime.date(2023, 10, 1),   # RRP abundance | QT2 drain
        datetime.date(2024, 12, 19),  # QT2 drain | post ON-RRP-adjustment
    )
    regime_labels: Tuple[str, ...] = (
        "r0_precovid_QT1",
        "r1_flood",
        "r2_rrp_abundance",
        "r3_QT2_drain",
        "r4_postadj_RMO",
    )

    # -- Layer 1: level model ----------------------------------------------
    hac_lags: int = 20
    # turn window excluded from the level model: last N bd + first M bd
    turn_window_last_bd: int = 2
    turn_window_first_bd: int = 1
    # mid-month pressure dummy (UST coupon settlement / corp tax), calendar days
    mid_month_days: Tuple[int, ...] = (14, 15, 16, 17)

    # -- Layer 2: turn model -----------------------------------------------
    spike_threshold_bp: float = 5.0
    local_base_window: int = 15      # trailing non-turn observations (median)
    local_base_min_periods: int = 5
    local_base_shift: int = 1
    quantiles: Tuple[float, ...] = (0.50, 0.90)

    # -- aggregation ---------------------------------------------------------
    # turn pressure assumed to span ~N effective daily prints around the turn
    effective_spike_days: float = 2.0


@dataclass(frozen=True)
class SerffWalkForwardConfig:
    """Point-in-time estimation schedule."""

    refit_frequency: str = "ME"      # pandas offset alias for refit dates
    min_train_days: int = 750        # daily observations before first fit
    min_turn_events: int = 24        # month-ends required before Layer 2 activates
    expanding: bool = True           # expanding window (False -> rolling)
    rolling_window_days: Optional[int] = None


@dataclass(frozen=True)
class SerffTradeConfig:
    """Trade construction, costs and rolls."""

    # DV01 per contract, $/bp
    dv01: Dict[str, float] = field(
        default_factory=lambda: {"ZQ": 41.67, "SR1": 41.67, "SR3": 25.0}
    )
    # tick size in price points (front month / nearest expiring vs back)
    tick_front: Dict[str, float] = field(
        default_factory=lambda: {"ZQ": 0.0025, "SR1": 0.0025, "SR3": 0.0025}
    )
    tick_back: Dict[str, float] = field(
        default_factory=lambda: {"ZQ": 0.005, "SR1": 0.005, "SR3": 0.005}
    )
    # $ per 1.00 price point per contract (1bp = 0.01 -> $ per point = 100 * $/bp)
    point_value: Dict[str, float] = field(
        default_factory=lambda: {"ZQ": 4167.0, "SR1": 4167.0, "SR3": 2500.0}
    )

    # transaction costs: half a tick per leg per side (minimum requirement)
    cost_ticks_per_leg_per_side: float = 0.5

    # structure sizing: SR3 contracts per unit (hedge = 1 ZQ per 5 SR3 per
    # full covered month, stubs weighted by window-days/month-days)
    sr3_contracts_per_unit: int = 5
    round_hedge_contracts: bool = False  # keep fractional ZQ (report both)

    # signal thresholds on the tradable (basis+turn) residual, bp of SR3 rate
    entry_threshold_bp: float = 1.5
    exit_threshold_bp: float = 0.5
    max_units: int = 1

    # roll rule: stop trading an SR3 window once fewer than this many
    # business days of unrealized fixings remain (exposure ~gone), and
    # mandatorily unwind then.
    min_unrealized_bd_to_hold: int = 10
    # re-true ZQ hedge weights at this frequency (stub weights drift)
    hedge_rebalance: str = "ME"

    # settlement reconciliation gate: |recomputed - exchange| tolerance, bp
    settle_recon_tolerance_bp: float = 0.35


@dataclass(frozen=True)
class SerffBacktestConfig:
    """Bundle: data + model + walk-forward + trading."""

    data: SerffDataConfig = field(default_factory=SerffDataConfig)
    model: SerffModelConfig = field(default_factory=SerffModelConfig)
    walkforward: SerffWalkForwardConfig = field(default_factory=SerffWalkForwardConfig)
    trade: SerffTradeConfig = field(default_factory=SerffTradeConfig)
