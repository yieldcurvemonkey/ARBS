"""SFRCalSpreadRV -- SOFR Futures Calendar Spread Relative Value Screener.

Computes the full structure curve across the Q12 SOFR contract ladder:
  - Calendar spreads (3M, 6M, 9M, 12M gaps)
  - Butterflies / microflies (3M, 6M, 9M, 12M gaps)
  - Double butterflies (3M, 6M gaps)

For each structure provides:
  - Current level and 1d change
  - Roll/carry (Barnes microfly decay)
  - Realized volatility (annualized)
  - Z-score (rank-aligned rolling window)
  - Risk-adjusted roll (roll / vol)

Data loading uses the repo's established pattern:
  IRSwapsMDP(source="BARCHART_STIRF-RL") + UnifiedQuery on USD-SOFR-1D-Q12STIRT
  with IMM tenor notation (IMM_1xIMM_2, etc.)

References:
  - Chris Barnes "A Dummies Guide to Trading Interest Rate Swaps" (Jun 2024)
  - Clarus "Carry as a Trading Strategy" -- microfly carry concept
"""
from __future__ import annotations

import datetime
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════

class StructureType(str, Enum):
    STRIP = "strip"
    SPD_3M = "spd_3m"
    SPD_6M = "spd_6m"
    SPD_9M = "spd_9m"
    SPD_12M = "spd_12m"
    FLY_3M = "fly_3m"
    FLY_6M = "fly_6m"
    FLY_9M = "fly_9m"
    FLY_12M = "fly_12m"
    DFLY_3M = "dfly_3m"
    DFLY_6M = "dfly_6m"


_STRUCTURE_SPEC: Dict[StructureType, Tuple[str, int]] = {
    StructureType.STRIP: ("strip", 0),
    StructureType.SPD_3M: ("spread", 1),
    StructureType.SPD_6M: ("spread", 2),
    StructureType.SPD_9M: ("spread", 3),
    StructureType.SPD_12M: ("spread", 4),
    StructureType.FLY_3M: ("fly", 1),
    StructureType.FLY_6M: ("fly", 2),
    StructureType.FLY_9M: ("fly", 3),
    StructureType.FLY_12M: ("fly", 4),
    StructureType.DFLY_3M: ("dfly", 1),
    StructureType.DFLY_6M: ("dfly", 2),
}

STRUCTURE_LABELS: Dict[StructureType, str] = {
    StructureType.STRIP: "Strip",
    StructureType.SPD_3M: "3M Spd",
    StructureType.SPD_6M: "6M Spd",
    StructureType.SPD_9M: "9M Spd",
    StructureType.SPD_12M: "12M Spd",
    StructureType.FLY_3M: "3M Fly",
    StructureType.FLY_6M: "6M Fly",
    StructureType.FLY_9M: "9M Fly",
    StructureType.FLY_12M: "12M Fly",
    StructureType.DFLY_3M: "3M DFly",
    StructureType.DFLY_6M: "6M DFly",
}


@dataclass
class SFRCalSpreadRVConfig:
    """Configuration for the SFR Calendar Spread RV Screener."""

    source: str = "BARCHART_STIRF-RL"
    curve: str = "USD-SOFR-1D-Q12STIRT"
    n_contracts: int = 12

    zscore_window: int = 60
    vol_window: int = 20
    carry_horizon: int = 1

    comparison_date: Optional[str] = None

    # ---- Constant maturity mode ----
    # When True, columns are labelled by rank (SFR1, SFR2, ...)
    # instead of specific contract codes (M26, U26, ...).
    # The underlying data is already rank-aligned (queries use IMM_NxIMM_{N+1}).
    constant_maturity: bool = False

    # When True AND constant_maturity=True, the time series is
    # back-adjusted at roll boundaries so there are no discontinuities
    # when the front contract expires and ranks shift.
    roll_adjusted: bool = False

    structure_types: List[StructureType] = field(
        default_factory=lambda: list(StructureType)
    )


# ═══════════════════════════════════════════════════════════════════
# Contract Ladder & IMM Tenor Mapping
# ═══════════════════════════════════════════════════════════════════

_CME_MONTH_CODES = "FGHJKMNQUVXZ"
_CME_CODE_TO_MONTH = {c: i + 1 for i, c in enumerate(_CME_MONTH_CODES)}
_MONTH_TO_CME_CODE = {v: k for k, v in _CME_CODE_TO_MONTH.items()}
_IMM_MONTHS = {3, 6, 9, 12}


def build_contract_ladder(
    as_of: datetime.date,
    n_contracts: int = 12,
) -> List[str]:
    """Build ordered list of next N active IMM contract codes (e.g., ['H26', 'M26', ...])."""
    from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils.tos import _imm_cutoff, _next_contracts

    symbols = _next_contracts(
        as_of, prefix="SR3", count=n_contracts,
        valid_months=[3, 6, 9, 12], cutoff_fn=_imm_cutoff,
    )
    # Extract short labels: SR3H26 -> H26
    labels = []
    for sym in symbols:
        m = re.match(r"^[A-Z0-9]+([FGHJKMNQUVXZ]\d{2})$", sym)
        labels.append(m.group(1) if m else sym)
    return labels


def imm_tenor(rank: int) -> str:
    """Rank (1-based) to IMM tenor string: rank 1 -> 'IMM_1xIMM_2'."""
    return f"IMM_{rank}xIMM_{rank + 1}"


def cm_label(rank: int) -> str:
    """Constant-maturity label: rank 1 -> 'SFR1'."""
    return f"SFR{rank}"


# ═══════════════════════════════════════════════════════════════════
# Constant Maturity Resolution
# ═══════════════════════════════════════════════════════════════════

def resolve_cm_to_specific(
    as_of: datetime.date,
    n_contracts: int = 12,
) -> Dict[str, str]:
    """Map constant-maturity labels to specific contract codes at a reference date.

    Example (as_of=2026-04-07):
        {'SFR1': 'M26', 'SFR2': 'U26', 'SFR3': 'Z26', ...}

    Parameters
    ----------
    as_of : Reference date for ladder resolution.
    n_contracts : Number of ranks to resolve.

    Returns
    -------
    Dict mapping 'SFR{rank}' -> specific contract code (e.g. 'M26').
    """
    ladder = build_contract_ladder(as_of, n_contracts=n_contracts)
    return {cm_label(i + 1): code for i, code in enumerate(ladder)}


def resolve_specific_to_cm(
    as_of: datetime.date,
    n_contracts: int = 12,
) -> Dict[str, str]:
    """Inverse of resolve_cm_to_specific.

    Example (as_of=2026-04-07):
        {'M26': 'SFR1', 'U26': 'SFR2', 'Z26': 'SFR3', ...}
    """
    return {v: k for k, v in resolve_cm_to_specific(as_of, n_contracts).items()}


def resolve_cm_structure_label(
    cm_structure_label: str,
    as_of: datetime.date,
    n_contracts: int = 12,
) -> str:
    """Resolve a CM structure label to specific contracts.

    Examples (as_of=2026-04-07):
        'SFR1/SFR2/SFR3' -> 'M26/U26/Z26'
        'SFR1/SFR2'      -> 'M26/U26'
        'SFR1'            -> 'M26'

    Also handles dfly pipe notation:
        'SFR1/SFR2/SFR3|SFR2/SFR3/SFR4' -> 'M26/U26/Z26|U26/Z26/H27'
    """
    cm_map = resolve_cm_to_specific(as_of, n_contracts)

    def _resolve_part(part: str) -> str:
        tokens = part.split("/")
        resolved = [cm_map.get(t.strip(), t.strip()) for t in tokens]
        return "/".join(resolved)

    if "|" in cm_structure_label:
        parts = cm_structure_label.split("|")
        return "|".join(_resolve_part(p) for p in parts)
    return _resolve_part(cm_structure_label)


def resolve_specific_structure_label(
    specific_label: str,
    as_of: datetime.date,
    n_contracts: int = 12,
) -> str:
    """Resolve a specific-contract label to CM notation.

    Examples (as_of=2026-04-07):
        'M26/U26/Z26' -> 'SFR1/SFR2/SFR3'
    """
    inv_map = resolve_specific_to_cm(as_of, n_contracts)

    def _resolve_part(part: str) -> str:
        tokens = part.split("/")
        resolved = [inv_map.get(t.strip(), t.strip()) for t in tokens]
        return "/".join(resolved)

    if "|" in specific_label:
        parts = specific_label.split("|")
        return "|".join(_resolve_part(p) for p in parts)
    return _resolve_part(specific_label)


# ═══════════════════════════════════════════════════════════════════
# Roll Adjustment
# ═══════════════════════════════════════════════════════════════════

def detect_roll_dates(panel: pd.DataFrame, threshold_std: float = 3.0) -> List[pd.Timestamp]:
    """Detect dates where the front contract rolled.

    On a roll date the front rank (column 0) jumps because it now
    points to a different underlying contract.  We detect this as
    a day where the front-contract daily change is an outlier
    relative to the overall curve movement.

    Parameters
    ----------
    panel : Rate panel with CM-labelled columns.
    threshold_std : Number of stds above median change to flag as roll.

    Returns
    -------
    List of timestamps identified as roll dates.
    """
    if len(panel) < 3:
        return []

    changes = panel.diff()
    front_chg = changes.iloc[:, 0].abs()
    # Compare front change to median absolute change across all ranks
    median_chg = changes.abs().median(axis=1)
    median_chg = median_chg.replace(0, np.nan)

    ratio = front_chg / median_chg
    # A roll typically shows as the front changing much more than the rest
    roll_mask = ratio > threshold_std
    return list(panel.index[roll_mask])


def roll_adjust_panel(panel: pd.DataFrame, threshold_std: float = 3.0) -> pd.DataFrame:
    """Back-adjust a CM rate panel to remove roll discontinuities.

    At each detected roll date, the jump in each column is decomposed into:
      - market move (estimated as median change across ranks)
      - roll artefact (residual)

    The roll artefact is subtracted from all prior history so the
    series is continuous.  This is analogous to back-adjusted futures
    in equity index futures.

    Parameters
    ----------
    panel : Rate panel (columns = SFR1, SFR2, ...).
    threshold_std : Sensitivity for roll detection.

    Returns
    -------
    Roll-adjusted copy of the panel.
    """
    adjusted = panel.copy()
    if len(adjusted) < 3:
        return adjusted

    changes = adjusted.diff()
    roll_dates = detect_roll_dates(adjusted, threshold_std)

    if not roll_dates:
        return adjusted

    # Process rolls from latest to earliest so adjustments don't cascade
    for rd in sorted(roll_dates, reverse=True):
        idx = adjusted.index.get_loc(rd)
        if idx < 1:
            continue

        day_change = changes.loc[rd]
        # Estimate the "true" market move as the median change across ranks
        market_move = day_change.median()
        # Roll artefact per column = observed change - market move
        roll_artefact = day_change - market_move

        # Only adjust columns where the artefact is large
        for col in adjusted.columns:
            art = roll_artefact[col]
            if abs(art) > abs(market_move) * 0.5:
                # Subtract artefact from all dates BEFORE the roll
                adjusted.loc[adjusted.index[:idx], col] += art

    return adjusted


# ═══════════════════════════════════════════════════════════════════
# Rate Panel Loading (UnifiedQuery pattern)
# ═══════════════════════════════════════════════════════════════════

def load_rate_panel(
    config: SFRCalSpreadRVConfig,
    start,
    end,
    *,
    curve_mdp=None,
    ts_builder=None,
    freq: str = "nyc_eod",
    n_jobs: int = 12,
    show_tqdm: bool = True,
) -> pd.DataFrame:
    """Load EOD outright rates for Q12 SOFR contracts.

    Returns DataFrame[dates x labels] with implied rates (%).

    Column labelling depends on ``config.constant_maturity``:
      - False (default): specific contract codes resolved at *end* date
        e.g. ['M26', 'U26', 'Z26', ...].
      - True: rank-based constant-maturity labels
        e.g. ['SFR1', 'SFR2', 'SFR3', ...].

    The underlying query always uses ``IMM_NxIMM_{N+1}`` tenors, so
    each row already reflects whichever contract was at that rank on
    that date — constant maturity by construction.

    If ``config.roll_adjusted`` is True (requires ``constant_maturity``),
    the panel is back-adjusted at roll boundaries to remove
    discontinuities when the front contract expires.

    Uses UnifiedQuery + IRSwapsMDP (see notebooks/timeseries/intraday_stirf.ipynb).
    """
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from Query.Unified.UnifiedQuery import UnifiedQuery
    from Query.Unified.registry import UnifiedValue
    from TB.IRSwapsTB import IRSwapsTB
    from TB.TimeseriesBuilder import TimeseriesBuilder

    if curve_mdp is None:
        curve_mdp = IRSwapsMDP(source=config.source)
    if ts_builder is None:
        ts_builder = TimeseriesBuilder()

    queries = []
    for rank in range(1, config.n_contracts + 1):
        queries.append(
            UnifiedQuery(
                curve=config.curve,
                tenor=imm_tenor(rank),
                value=UnifiedValue.IRS_RATE,
            )
        )

    panel = ts_builder.get_timeseries(
        start=start,
        end=end,
        queries=queries,
        freq=freq,
        n_jobs=n_jobs,
        routers={"IRS": IRSwapsTB(curve_mdp, show_tqdm=show_tqdm)},
        ignore_cache_miss=True,
    )

    # ---- Column labelling ----
    if config.constant_maturity:
        # Rank-based labels: SFR1, SFR2, ...
        rename_map = {col: cm_label(i + 1) for i, col in enumerate(panel.columns)}
    else:
        # Specific contract codes resolved at the end date
        ref_date = end if isinstance(end, datetime.date) else datetime.date.today()
        ladder = build_contract_ladder(ref_date, n_contracts=config.n_contracts)
        rename_map = {}
        for i, col in enumerate(panel.columns):
            if i < len(ladder):
                rename_map[col] = ladder[i]

    panel = panel.rename(columns=rename_map)

    for col in panel.columns:
        panel[col] = pd.to_numeric(panel[col], errors="coerce")

    panel = panel.dropna(how="all").sort_index()

    # ---- Roll adjustment ----
    if config.constant_maturity and config.roll_adjusted:
        panel = roll_adjust_panel(panel)

    return panel


# ═══════════════════════════════════════════════════════════════════
# Structure Computation
# ═══════════════════════════════════════════════════════════════════

def _spread_label(cols: List[str], i: int, gap: int) -> str:
    return f"{cols[i]}/{cols[i + gap]}"


def _fly_label(cols: List[str], i: int, gap: int) -> str:
    return f"{cols[i]}/{cols[i + gap]}/{cols[i + 2 * gap]}"


def _dfly_label(cols: List[str], i: int, gap: int) -> str:
    return f"{_fly_label(cols, i, gap)}|{_fly_label(cols, i + gap, gap)}"


def compute_strip(rates: pd.DataFrame) -> pd.DataFrame:
    return rates.copy()


def compute_spread_curve(rates: pd.DataFrame, gap: int = 1) -> pd.DataFrame:
    """Calendar spreads: spread[i] = (rate[i+gap] - rate[i]) * 100 bps."""
    cols = list(rates.columns)
    result = {}
    for i in range(len(cols) - gap):
        result[_spread_label(cols, i, gap)] = (rates.iloc[:, i + gap] - rates.iloc[:, i]) * 100
    return pd.DataFrame(result, index=rates.index)


def compute_fly_curve(rates: pd.DataFrame, gap: int = 1) -> pd.DataFrame:
    """Butterflies: fly[i] = (rate[i] - 2*rate[i+gap] + rate[i+2*gap]) * 100 bps.

    Weights: [1, -2, 1]. Positive = wings expensive vs belly.
    """
    cols = list(rates.columns)
    result = {}
    for i in range(len(cols) - 2 * gap):
        result[_fly_label(cols, i, gap)] = (
            rates.iloc[:, i] - 2 * rates.iloc[:, i + gap] + rates.iloc[:, i + 2 * gap]
        ) * 100
    return pd.DataFrame(result, index=rates.index)


def compute_dfly_curve(rates: pd.DataFrame, gap: int = 1) -> pd.DataFrame:
    """Double butterflies: dfly[i] = fly[i] - fly[i+gap].

    Expanded: rate[i] - 3*rate[i+gap] + 3*rate[i+2*gap] - rate[i+3*gap].
    Weights: [1, -3, 3, -1]. A spike = kink in the curve.
    """
    cols = list(rates.columns)
    result = {}
    for i in range(len(cols) - 3 * gap):
        result[_dfly_label(cols, i, gap)] = (
            rates.iloc[:, i]
            - 3 * rates.iloc[:, i + gap]
            + 3 * rates.iloc[:, i + 2 * gap]
            - rates.iloc[:, i + 3 * gap]
        ) * 100
    return pd.DataFrame(result, index=rates.index)


def compute_structure(rates: pd.DataFrame, st: StructureType) -> pd.DataFrame:
    kind, gap = _STRUCTURE_SPEC[st]
    if kind == "strip":
        return compute_strip(rates)
    elif kind == "spread":
        return compute_spread_curve(rates, gap)
    elif kind == "fly":
        return compute_fly_curve(rates, gap)
    elif kind == "dfly":
        return compute_dfly_curve(rates, gap)
    raise ValueError(f"Unknown kind: {kind}")


# ═══════════════════════════════════════════════════════════════════
# Analytics
# ═══════════════════════════════════════════════════════════════════

def compute_roll(curve: pd.DataFrame, horizon: int = 1) -> pd.Series:
    """Barnes microfly carry: position i slides to i-horizon after one quarter.

    roll[i] = level[i-horizon] - level[i]
    Positive roll = earn positive carry if long.
    """
    latest = curve.iloc[-1]
    roll = pd.Series(np.nan, index=curve.columns, dtype=float)
    for i in range(horizon, len(curve.columns)):
        roll.iloc[i] = latest.iloc[i - horizon] - latest.iloc[i]
    return roll


def compute_realized_vol(curve: pd.DataFrame, window: int = 20) -> pd.Series:
    """Annualized realized vol of daily changes (latest value)."""
    return curve.diff().rolling(window, min_periods=max(10, window // 2)).std().iloc[-1] * np.sqrt(252)


def compute_zscore(curve: pd.DataFrame, window: int = 60) -> pd.Series:
    """Z-score: (current - rolling_mean) / rolling_std."""
    mu = curve.rolling(window, min_periods=max(20, window // 2)).mean()
    sigma = curve.rolling(window, min_periods=max(20, window // 2)).std().replace(0, np.nan)
    return ((curve - mu) / sigma).iloc[-1]


def compute_zscore_ts(curve: pd.DataFrame, window: int = 60) -> pd.DataFrame:
    """Full z-score time series."""
    mu = curve.rolling(window, min_periods=max(20, window // 2)).mean()
    sigma = curve.rolling(window, min_periods=max(20, window // 2)).std().replace(0, np.nan)
    return (curve - mu) / sigma


def compute_risk_adj_roll(roll: pd.Series, vol: pd.Series) -> pd.Series:
    return roll / vol.replace(0, np.nan)


# ═══════════════════════════════════════════════════════════════════
# Result Structures
# ═══════════════════════════════════════════════════════════════════

def _safe_float(x) -> float:
    try:
        v = float(x)
        return v if not np.isnan(v) else np.nan
    except (TypeError, ValueError):
        return np.nan


@dataclass
class StructureCurveData:
    """Analytics cross-section for one structure type."""
    structure_type: StructureType
    labels: List[str]
    levels: List[float]
    prev_close: List[float]
    changes: List[float]
    zscores: List[float]
    vols: List[float]
    rolls: List[float]
    risk_adj_rolls: List[float]
    comparison_levels: Optional[List[float]] = None

    def summary(self) -> Dict[str, Any]:
        levels = np.array(self.levels)
        changes = np.array(self.changes)
        d: Dict[str, Any] = {}
        if len(levels[~np.isnan(levels)]) > 0:
            d["front"] = {"label": self.labels[0], "value": round(float(levels[0]), 2)}
            d["back"] = {"label": self.labels[-1], "value": round(float(levels[-1]), 2)}
            pi = int(np.nanargmax(levels))
            ti = int(np.nanargmin(levels))
            d["peak"] = {"label": self.labels[pi], "value": round(float(levels[pi]), 2)}
            d["trough"] = {"label": self.labels[ti], "value": round(float(levels[ti]), 2)}
        if len(changes[~np.isnan(changes)]) > 0:
            mi = int(np.nanargmax(changes))
            ni = int(np.nanargmin(changes))
            d["max_chg"] = {"label": self.labels[mi], "value": round(float(changes[mi]), 2)}
            d["min_chg"] = {"label": self.labels[ni], "value": round(float(changes[ni]), 2)}
        return d

    def to_dataframe(self) -> pd.DataFrame:
        """Flat DataFrame for display in notebooks."""
        df = pd.DataFrame({
            "Label": self.labels,
            "Level (bp)": [round(x, 2) if not np.isnan(x) else None for x in self.levels],
            "Chg (bp)": [round(x, 2) if not np.isnan(x) else None for x in self.changes],
            "Z-Score": [round(x, 2) if not np.isnan(x) else None for x in self.zscores],
            "Vol (ann)": [round(x, 2) if not np.isnan(x) else None for x in self.vols],
            "Roll (bp)": [round(x, 2) if not np.isnan(x) else None for x in self.rolls],
            "Risk-Adj Roll": [round(x, 2) if not np.isnan(x) else None for x in self.risk_adj_rolls],
        })
        if self.comparison_levels is not None:
            df["Hist Level (bp)"] = [round(x, 2) if not np.isnan(x) else None for x in self.comparison_levels]
        return df.set_index("Label")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "structureType": self.structure_type.value,
            "labels": self.labels,
            "levels": [None if np.isnan(x) else round(x, 4) for x in self.levels],
            "prevClose": [None if np.isnan(x) else round(x, 4) for x in self.prev_close],
            "changes": [None if np.isnan(x) else round(x, 4) for x in self.changes],
            "zscores": [None if np.isnan(x) else round(x, 3) for x in self.zscores],
            "vols": [None if np.isnan(x) else round(x, 3) for x in self.vols],
            "rolls": [None if np.isnan(x) else round(x, 4) for x in self.rolls],
            "riskAdjRolls": [None if np.isnan(x) else round(x, 3) for x in self.risk_adj_rolls],
            "comparisonLevels": (
                [None if np.isnan(x) else round(x, 4) for x in self.comparison_levels]
                if self.comparison_levels is not None else None
            ),
            "summary": self.summary(),
        }


@dataclass
class SFRCalSpreadRVSnapshot:
    """Complete screener snapshot across all structure types."""
    as_of: datetime.date
    contract_ladder: List[str]
    structures: Dict[StructureType, StructureCurveData]
    rate_panel: Optional[pd.DataFrame] = None
    constant_maturity: bool = False
    # CM -> specific mapping at as_of (populated when constant_maturity=True)
    cm_resolution: Optional[Dict[str, str]] = None

    def resolve_label(self, cm_label_str: str) -> str:
        """Resolve a CM structure label to specific contracts at as_of.

        Example: 'SFR1/SFR2/SFR3' -> 'M26/U26/Z26' (if as_of=2026-04-07)
        """
        if not self.constant_maturity or not self.cm_resolution:
            return cm_label_str
        return resolve_cm_structure_label(cm_label_str, self.as_of, len(self.contract_ladder))

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "asOf": self.as_of.isoformat(),
            "contractLadder": self.contract_ladder,
            "constantMaturity": self.constant_maturity,
            "structures": {st.value: d.to_dict() for st, d in self.structures.items()},
        }
        if self.cm_resolution:
            d["cmResolution"] = self.cm_resolution
        return d


# ═══════════════════════════════════════════════════════════════════
# Snapshot Builder
# ═══════════════════════════════════════════════════════════════════

def _build_one(
    rates: pd.DataFrame,
    st: StructureType,
    config: SFRCalSpreadRVConfig,
    comp_rates: Optional[pd.DataFrame] = None,
) -> StructureCurveData:
    curve = compute_structure(rates, st)
    if curve.empty or len(curve) < 2:
        return StructureCurveData(
            structure_type=st, labels=[], levels=[], prev_close=[],
            changes=[], zscores=[], vols=[], rolls=[], risk_adj_rolls=[],
        )

    latest = curve.iloc[-1]
    prev = curve.iloc[-2]
    chg = latest - prev
    zs = compute_zscore(curve, config.zscore_window)
    vol = compute_realized_vol(curve, config.vol_window)
    roll = compute_roll(curve, config.carry_horizon)
    radj = compute_risk_adj_roll(roll, vol)

    comp_levels = None
    if comp_rates is not None:
        comp_curve = compute_structure(comp_rates, st)
        if not comp_curve.empty:
            cl = comp_curve.iloc[-1]
            comp_levels = [_safe_float(cl.iloc[i]) if i < len(cl) else np.nan for i in range(len(latest))]

    return StructureCurveData(
        structure_type=st,
        labels=list(curve.columns),
        levels=[_safe_float(x) for x in latest],
        prev_close=[_safe_float(x) for x in prev],
        changes=[_safe_float(x) for x in chg],
        zscores=[_safe_float(x) for x in zs],
        vols=[_safe_float(x) for x in vol],
        rolls=[_safe_float(x) for x in roll],
        risk_adj_rolls=[_safe_float(x) for x in radj],
        comparison_levels=comp_levels,
    )


def build_snapshot(
    config: Optional[SFRCalSpreadRVConfig] = None,
    *,
    rates_panel: Optional[pd.DataFrame] = None,
    comparison_panel: Optional[pd.DataFrame] = None,
    curve_mdp=None,
    ts_builder=None,
) -> SFRCalSpreadRVSnapshot:
    """Build complete RV screener snapshot.

    If rates_panel is None, loads EOD data via the standard pipeline.
    """
    if config is None:
        config = SFRCalSpreadRVConfig()

    as_of = datetime.date.today()

    if rates_panel is None:
        import pytz
        NYC = pytz.timezone("America/New_York")
        lookback = max(config.zscore_window, config.vol_window) + 60
        start = NYC.localize(datetime.datetime.combine(
            as_of - datetime.timedelta(days=int(lookback * 1.6)),
            datetime.time(18, 0),
        ))
        end = "live"
        rates_panel = load_rate_panel(
            config, start=start, end=end,
            curve_mdp=curve_mdp, ts_builder=ts_builder,
        )

    ladder = list(rates_panel.columns)

    structures = {}
    for st in config.structure_types:
        try:
            structures[st] = _build_one(rates_panel, st, config, comparison_panel)
        except Exception as e:
            logger.warning("Failed %s: %s", st.value, e)

    # Build CM resolution map if in constant_maturity mode
    cm_res = None
    if config.constant_maturity:
        cm_res = resolve_cm_to_specific(as_of, n_contracts=config.n_contracts)

    return SFRCalSpreadRVSnapshot(
        as_of=as_of,
        contract_ladder=ladder,
        structures=structures,
        rate_panel=rates_panel,
        constant_maturity=config.constant_maturity,
        cm_resolution=cm_res,
    )


def build_snapshot_from_prices(
    prices: pd.DataFrame,
    config: Optional[SFRCalSpreadRVConfig] = None,
    comparison_prices: Optional[pd.DataFrame] = None,
) -> SFRCalSpreadRVSnapshot:
    """Build from a raw price DataFrame (price = 100 - rate)."""
    if config is None:
        config = SFRCalSpreadRVConfig()
    rates = 100 - prices
    comp = (100 - comparison_prices) if comparison_prices is not None else None
    return build_snapshot(config, rates_panel=rates, comparison_panel=comp)


# ═══════════════════════════════════════════════════════════════════
# Specific Trade Analysis
# ═══════════════════════════════════════════════════════════════════

def analyze_specific_fly(
    rates_panel: pd.DataFrame,
    front: str,
    belly: str,
    back: str,
    config: Optional[SFRCalSpreadRVConfig] = None,
) -> Dict[str, Any]:
    """Analyze a specific butterfly trade (e.g., M26/U26/Z26).

    Returns dict with level, z-score, vol, roll, risk-adj roll, and time series.
    """
    if config is None:
        config = SFRCalSpreadRVConfig()

    cols = list(rates_panel.columns)
    if front not in cols or belly not in cols or back not in cols:
        raise ValueError(f"Contracts {front}/{belly}/{back} not all in panel columns: {cols}")

    # Compute the fly time series
    fly_ts = (rates_panel[front] - 2 * rates_panel[belly] + rates_panel[back]) * 100
    fly_ts = fly_ts.dropna()

    if len(fly_ts) < 2:
        raise ValueError("Insufficient data for fly analysis")

    latest = float(fly_ts.iloc[-1])
    prev = float(fly_ts.iloc[-2])
    change = latest - prev

    # Z-score
    mu = fly_ts.rolling(config.zscore_window, min_periods=20).mean()
    sigma = fly_ts.rolling(config.zscore_window, min_periods=20).std().replace(0, np.nan)
    zs_ts = (fly_ts - mu) / sigma
    zscore = float(zs_ts.iloc[-1])

    # Vol
    vol = float(fly_ts.diff().rolling(config.vol_window, min_periods=10).std().iloc[-1] * np.sqrt(252))

    # Roll: need the fly one position closer to expiry
    fi = cols.index(front)
    bi = cols.index(belly)
    bki = cols.index(back)
    gap = bi - fi

    roll = np.nan
    if fi >= gap:
        roll_front = cols[fi - gap]
        roll_belly = cols[bi - gap]
        roll_back = cols[bki - gap]
        if roll_front in cols and roll_belly in cols and roll_back in cols:
            roll_fly = float((rates_panel[roll_front].iloc[-1] - 2 * rates_panel[roll_belly].iloc[-1] + rates_panel[roll_back].iloc[-1]) * 100)
            roll = roll_fly - latest

    risk_adj = roll / vol if vol != 0 and not np.isnan(vol) else np.nan

    return {
        "trade": f"{front}/{belly}/{back}",
        "level_bp": round(latest, 2),
        "prev_close_bp": round(prev, 2),
        "change_bp": round(change, 2),
        "zscore": round(zscore, 2) if not np.isnan(zscore) else None,
        "vol_ann": round(vol, 2) if not np.isnan(vol) else None,
        "roll_bp": round(roll, 2) if not np.isnan(roll) else None,
        "risk_adj_roll": round(risk_adj, 2) if not np.isnan(risk_adj) else None,
        "timeseries": fly_ts,
        "zscore_ts": zs_ts,
        "mean_60d": round(float(mu.iloc[-1]), 2) if not np.isnan(mu.iloc[-1]) else None,
        "std_60d": round(float(sigma.iloc[-1]), 2) if not np.isnan(sigma.iloc[-1]) else None,
    }
