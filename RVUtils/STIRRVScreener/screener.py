"""STIR Relative Value Screener — Astor Ridge Framework Applied to SOFR Futures.

Unified cross-structure ranking across the Q12 SOFR strip:
  - Outright strip rates
  - Calendar spreads (3M, 6M, 9M, 12M)
  - Butterflies (3M, 6M, 9M, 12M)
  - Double butterflies (3M, 6M)
  - Condors (3M, 6M)

For each structure computes:
  - Level (bp) and 1d change
  - Z-score (rolling window, Astor Ridge vol-adjusted move)
  - Realized vol (annualized)
  - Carry/roll (Barnes microfly decay)
  - Risk-adjusted roll (roll / vol) — Astor Ridge's primary ranking metric
  - Percentile rank
  - Forward curve consistency flag
  - Composite score for unified ranking

Overlays:
  - FOMC blackout gating
  - IMM roll blackout gating
  - Half-life (OU mean-reversion speed)
"""
from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from BT.signals.sfr_cal_spread_rv import (
    SFRCalSpreadRVConfig,
    StructureType,
    STRUCTURE_LABELS,
    load_rate_panel,
    compute_structure,
    compute_zscore,
    compute_zscore_ts,
    compute_realized_vol,
    compute_roll,
    compute_risk_adj_roll,
    resolve_cm_to_specific,
)
from BT.signals.sfr_kink_fade import (
    compute_percentile_rank,
    compute_cross_sectional_rank,
    compute_rolling_halflife,
    days_to_next_fomc,
    days_to_next_imm_roll,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════

SCREENER_STRUCTURES: List[StructureType] = [
    StructureType.STRIP,
    StructureType.SPD_3M,
    StructureType.SPD_6M,
    StructureType.SPD_9M,
    StructureType.SPD_12M,
    StructureType.FLY_3M,
    StructureType.FLY_6M,
    StructureType.FLY_9M,
    StructureType.FLY_12M,
    StructureType.DFLY_3M,
    StructureType.DFLY_6M,
    StructureType.CF_3M,
    StructureType.CF_6M,
]


@dataclass
class STIRRVScreenerConfig:
    source: str = "BARCHART_STIRF-RL"
    curve: str = "USD-SOFR-1D-Q12STIRT"
    n_contracts: int = 12

    zscore_window: int = 65
    vol_window: int = 20
    percentile_window: int = 65
    halflife_window: int = 120
    lookback_days: int = 252

    carry_horizon: int = 1

    fomc_blackout_days: int = 5
    roll_blackout_days: int = 3

    structures: List[StructureType] = field(
        default_factory=lambda: list(SCREENER_STRUCTURES)
    )

    # composite score weights
    w_zscore: float = 0.30
    w_risk_adj_roll: float = 0.35
    w_fwd_consistency: float = 0.15
    w_halflife: float = 0.10
    w_percentile: float = 0.10

    # entry thresholds
    min_abs_zscore: float = 1.0
    min_abs_risk_adj_roll: float = 0.3
    max_halflife_days: float = 90.0


# ═══════════════════════════════════════════════════════════════════
# Result Structures
# ═══════════════════════════════════════════════════════════════════

@dataclass
class StructureRVRow:
    structure_type: str
    label: str
    specific_label: str

    level_bp: float
    change_1d_bp: float

    zscore: float
    percentile: float
    vol_ann_bp: float

    roll_bp: float
    risk_adj_roll: float

    halflife_days: float

    fwd_consistency_flag: bool
    fwd_consistency_score: float

    composite_score: float
    direction: str
    actionable: bool
    filters: Dict[str, bool]


@dataclass
class STIRRVSnapshot:
    as_of: datetime.date
    rows: List[StructureRVRow]

    strip_rates: Dict[str, float]
    fwd_curve_slope: str
    fwd_curve_kinks: List[str]

    days_to_fomc: int
    days_to_imm_roll: int
    fomc_blackout_active: bool
    roll_blackout_active: bool

    cm_resolution: Dict[str, str]
    config: STIRRVScreenerConfig

    n_actionable: int = 0
    actionable_ids: List[str] = field(default_factory=list)

    def to_dataframe(self) -> pd.DataFrame:
        records = []
        for r in self.rows:
            records.append({
                "Type": r.structure_type,
                "Structure": r.label,
                "Contracts": r.specific_label,
                "Level (bp)": round(r.level_bp, 2),
                "Chg 1d": round(r.change_1d_bp, 2),
                "Z-Score": round(r.zscore, 2),
                "Pctl": round(r.percentile, 2),
                "Vol (ann)": round(r.vol_ann_bp, 2),
                "Roll (bp)": round(r.roll_bp, 2),
                "Roll/Vol": round(r.risk_adj_roll, 2),
                "HL (days)": round(r.halflife_days, 1) if not np.isnan(r.halflife_days) else None,
                "Fwd Flag": r.fwd_consistency_flag,
                "Score": round(r.composite_score, 3),
                "Dir": r.direction,
                "Actionable": r.actionable,
            })
        df = pd.DataFrame(records)
        if not df.empty:
            df = df.sort_values("Score", ascending=False, key=abs)
        return df

    def top_trades(self, n: int = 10) -> pd.DataFrame:
        df = self.to_dataframe()
        actionable = df[df["Actionable"]]
        if len(actionable) >= n:
            return actionable.head(n)
        return df.head(n)

    def by_type(self, structure_type: str) -> pd.DataFrame:
        df = self.to_dataframe()
        return df[df["Type"] == structure_type].sort_values("Score", ascending=False, key=abs)


# ═══════════════════════════════════════════════════════════════════
# Forward Curve Consistency
# ═══════════════════════════════════════════════════════════════════

def compute_forward_consistency(rates: pd.DataFrame) -> Tuple[pd.Series, str, List[str]]:
    """Detect local forward rate inconsistencies (Astor Ridge Layer 2).

    Compares each consecutive forward rate change to the global slope.
    Returns a score per contract (high abs = inconsistent), global slope
    direction, and list of flagged kink points.
    """
    latest = rates.iloc[-1]
    n = len(latest)

    fwd_changes = latest.diff().dropna()
    global_slope = latest.iloc[-1] - latest.iloc[0]
    slope_dir = "upward" if global_slope > 0 else "downward" if global_slope < 0 else "flat"

    sign_consistent = np.sign(fwd_changes) == np.sign(global_slope)

    fwd_vol = rates.diff(axis=1).iloc[:, 1:].std()
    fwd_vol = fwd_vol.replace(0, np.nan)
    normalized_inconsistency = fwd_changes.abs() / fwd_vol.reindex(fwd_changes.index).replace(0, np.nan)

    scores = pd.Series(0.0, index=latest.index)
    for i, idx in enumerate(fwd_changes.index):
        if not sign_consistent.iloc[i]:
            scores[idx] = normalized_inconsistency.iloc[i] if not np.isnan(normalized_inconsistency.iloc[i]) else 1.0

    kinks = [str(idx) for idx in scores.index if scores[idx] > 1.5]

    return scores, slope_dir, kinks


def compute_fly_fwd_consistency(
    fly_ts: pd.DataFrame,
    rates: pd.DataFrame,
) -> pd.Series:
    """For each butterfly, score how much the belly forward rate deviates
    from the interpolated wing forward rates.

    A fly that is extreme AND sits at a forward rate inconsistency
    is a higher-conviction signal.
    """
    latest_rates = rates.iloc[-1]
    n_rates = len(latest_rates)
    scores = pd.Series(0.0, index=fly_ts.columns)

    for col in fly_ts.columns:
        parts = str(col).split("/")
        if len(parts) != 3:
            continue
        try:
            idxs = [list(rates.columns).index(p) for p in parts]
        except ValueError:
            continue

        near_rate = latest_rates.iloc[idxs[0]]
        belly_rate = latest_rates.iloc[idxs[1]]
        far_rate = latest_rates.iloc[idxs[2]]

        interpolated = (near_rate + far_rate) / 2
        deviation = abs(belly_rate - interpolated)

        recent_fly_vol = fly_ts[col].diff().rolling(20, min_periods=10).std().iloc[-1]
        if recent_fly_vol and recent_fly_vol > 0:
            scores[col] = deviation / recent_fly_vol
        else:
            scores[col] = deviation * 100

    return scores


# ═══════════════════════════════════════════════════════════════════
# Composite Score
# ═══════════════════════════════════════════════════════════════════

def compute_composite_score(
    zscore: float,
    risk_adj_roll: float,
    fwd_score: float,
    halflife: float,
    percentile: float,
    config: STIRRVScreenerConfig,
) -> float:
    """Weighted composite score (Astor Ridge unified ranking).

    Components are normalized to roughly [-1, 1] scale:
      - zscore: already normalized, capped at ±4
      - risk_adj_roll: sign-aligned with zscore direction, capped at ±3
      - fwd_consistency: 0-1 scale (1 = inconsistent fwd at this point)
      - halflife: inverse score (faster reversion = better), 0-1
      - percentile: rescaled to [-1, 1]
    """
    z_capped = np.clip(zscore, -4, 4) / 4.0

    rar_aligned = risk_adj_roll * (-np.sign(zscore)) if zscore != 0 else risk_adj_roll
    rar_norm = np.clip(rar_aligned, -3, 3) / 3.0

    fwd_norm = np.clip(fwd_score, 0, 3) / 3.0

    if not np.isnan(halflife) and halflife > 0:
        hl_norm = np.clip(1.0 - halflife / config.max_halflife_days, -1, 1)
    else:
        hl_norm = 0.0

    pctl_norm = (percentile - 0.5) * 2.0 * (-np.sign(zscore)) if zscore != 0 else 0.0

    composite = (
        config.w_zscore * abs(z_capped)
        + config.w_risk_adj_roll * max(rar_norm, 0)
        + config.w_fwd_consistency * fwd_norm
        + config.w_halflife * max(hl_norm, 0)
        + config.w_percentile * max(pctl_norm, 0)
    )

    return composite * np.sign(zscore) if zscore != 0 else 0.0


# ═══════════════════════════════════════════════════════════════════
# Main Builder
# ═══════════════════════════════════════════════════════════════════

def build_snapshot(
    as_of: datetime.date,
    config: Optional[STIRRVScreenerConfig] = None,
    *,
    curve_mdp=None,
    ts_builder=None,
    show_tqdm: bool = True,
) -> STIRRVSnapshot:
    """Build a complete STIR RV snapshot for the given date."""
    if config is None:
        config = STIRRVScreenerConfig()

    import pytz
    NYC = pytz.timezone("America/New_York")

    end = NYC.localize(datetime.datetime.combine(as_of, datetime.time(17, 0)))
    start = end - datetime.timedelta(days=config.lookback_days + 30)

    rv_config = SFRCalSpreadRVConfig(
        source=config.source,
        curve=config.curve,
        n_contracts=config.n_contracts,
        zscore_window=config.zscore_window,
        vol_window=config.vol_window,
        carry_horizon=config.carry_horizon,
        constant_maturity=True,
    )

    logger.info("Loading rate panel: %s -> %s", start.date(), as_of)
    rates = load_rate_panel(
        rv_config, start, end,
        curve_mdp=curve_mdp, ts_builder=ts_builder,
        show_tqdm=show_tqdm,
    )

    if rates.empty:
        raise ValueError(f"No data loaded for {as_of}")

    rates = rates.dropna(how="all")
    if len(rates) < config.zscore_window:
        logger.warning("Only %d observations, need %d for z-score", len(rates), config.zscore_window)

    cm_map = resolve_cm_to_specific(as_of, config.n_contracts)
    strip_rates = {k: round(float(v), 4) for k, v in rates.iloc[-1].items()}

    fwd_scores, fwd_slope, fwd_kinks = compute_forward_consistency(rates)

    d_fomc = days_to_next_fomc(as_of)
    d_roll = days_to_next_imm_roll(as_of)
    fomc_blackout = d_fomc <= config.fomc_blackout_days
    roll_blackout = d_roll <= config.roll_blackout_days

    all_rows: List[StructureRVRow] = []

    for st in config.structures:
        type_label = STRUCTURE_LABELS.get(st, st.value)
        curve_ts = compute_structure(rates, st)
        if curve_ts.empty or len(curve_ts) < 20:
            continue

        zscores = compute_zscore(curve_ts, config.zscore_window)
        vols = compute_realized_vol(curve_ts, config.vol_window)
        rolls = compute_roll(curve_ts, config.carry_horizon)
        risk_adj_rolls = compute_risk_adj_roll(rolls, vols)

        zscore_full = compute_zscore_ts(curve_ts, config.zscore_window)
        pctl_df = compute_percentile_rank(curve_ts, config.percentile_window)
        latest_pctls = pctl_df.iloc[-1] if not pctl_df.empty else pd.Series(dtype=float)

        hl_df = compute_rolling_halflife(curve_ts, config.halflife_window)
        latest_hl = hl_df.iloc[-1] if not hl_df.empty else pd.Series(dtype=float)

        if st in (StructureType.FLY_3M, StructureType.FLY_6M, StructureType.FLY_9M, StructureType.FLY_12M):
            fly_fwd_scores = compute_fly_fwd_consistency(curve_ts, rates)
        else:
            fly_fwd_scores = pd.Series(0.0, index=curve_ts.columns)

        latest_levels = curve_ts.iloc[-1]
        prev_levels = curve_ts.iloc[-2] if len(curve_ts) > 1 else curve_ts.iloc[-1]

        for col in curve_ts.columns:
            z = _safe(zscores, col)
            vol = _safe(vols, col)
            roll = _safe(rolls, col)
            rar = _safe(risk_adj_rolls, col)
            pctl = _safe(latest_pctls, col)
            hl = _safe(latest_hl, col)
            fwd_sc = _safe(fly_fwd_scores, col)
            level = _safe(latest_levels, col)
            prev = _safe(prev_levels, col)
            chg = level - prev if not (np.isnan(level) or np.isnan(prev)) else np.nan

            composite = compute_composite_score(z, rar, fwd_sc, hl, pctl, config)

            direction = "SELL" if z > 0 else "BUY" if z < 0 else "FLAT"

            fwd_flag = fwd_sc > 1.5

            filters = {
                "zscore_pass": abs(z) >= config.min_abs_zscore if not np.isnan(z) else False,
                "rar_pass": abs(rar) >= config.min_abs_risk_adj_roll if not np.isnan(rar) else False,
                "hl_pass": 0 < hl <= config.max_halflife_days if not np.isnan(hl) else False,
                "fomc_clear": not fomc_blackout,
                "roll_clear": not roll_blackout,
            }
            actionable = all(filters.values())

            specific = _resolve_col_to_specific(col, cm_map)

            all_rows.append(StructureRVRow(
                structure_type=type_label,
                label=col,
                specific_label=specific,
                level_bp=level,
                change_1d_bp=chg if not np.isnan(chg) else 0.0,
                zscore=z,
                percentile=pctl,
                vol_ann_bp=vol,
                roll_bp=roll,
                risk_adj_roll=rar,
                halflife_days=hl,
                fwd_consistency_flag=fwd_flag,
                fwd_consistency_score=fwd_sc,
                composite_score=composite,
                direction=direction,
                actionable=actionable,
                filters=filters,
            ))

    actionable_rows = [r for r in all_rows if r.actionable]
    actionable_rows.sort(key=lambda r: abs(r.composite_score), reverse=True)

    return STIRRVSnapshot(
        as_of=as_of,
        rows=all_rows,
        strip_rates=strip_rates,
        fwd_curve_slope=fwd_slope,
        fwd_curve_kinks=fwd_kinks,
        days_to_fomc=d_fomc,
        days_to_imm_roll=d_roll,
        fomc_blackout_active=fomc_blackout,
        roll_blackout_active=roll_blackout,
        cm_resolution=cm_map,
        config=config,
        n_actionable=len(actionable_rows),
        actionable_ids=[r.label for r in actionable_rows],
    )


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════

def _safe(series_or_val, key, default=np.nan) -> float:
    try:
        v = float(series_or_val[key]) if key in series_or_val.index else default
        return v if not np.isnan(v) else default
    except (KeyError, TypeError, ValueError):
        return default


def _resolve_col_to_specific(col: str, cm_map: Dict[str, str]) -> str:
    parts = str(col).replace("|", "/").split("/")
    resolved = [cm_map.get(p.strip(), p.strip()) for p in parts]
    return "/".join(resolved)
