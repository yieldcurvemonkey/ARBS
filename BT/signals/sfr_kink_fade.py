"""SFR Kink-Fading Strategy -- Signal Construction & Analytics.

Fades localized curvature anomalies ("kinks") in the SR3 strip using
butterflies (BF), double butterflies (DF), and condors (CF).

Signal normalization methods:
  - Time-series z-score (existing, via sfr_cal_spread_rv)
  - Percentile rank (nonparametric)
  - Cross-sectional rank (relative to strip peers)
  - Intersection signals (multiple methods agreeing)

Mean-reversion analytics:
  - OU half-life estimation (AR(1) regression)
  - ADF stationarity tests
  - Rolling half-life time series

Regime detection:
  - FOMC step Herfindahl (one-and-done vs cycle)
  - FOMC blackout windows
  - Volatility regime (trailing fly vol)
  - Conditional half-life gating
"""
from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from BT.signals.sfr_cal_spread_rv import (
    SFRCalSpreadRVConfig,
    StructureType,
    compute_fly_curve,
    compute_dfly_curve,
    compute_condor_curve,
    compute_zscore_ts,
    compute_realized_vol,
    compute_roll,
    load_rate_panel,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════

class KinkStructure(str, Enum):
    BF_3M = "bf_3m"
    BF_6M = "bf_6m"
    DF_3M = "df_3m"
    DF_6M = "df_6m"
    CF_3M = "cf_3m"
    CF_6M = "cf_6m"


_KINK_STRUCTURE_TO_COMPUTE = {
    KinkStructure.BF_3M: ("fly", 1),
    KinkStructure.BF_6M: ("fly", 2),
    KinkStructure.DF_3M: ("dfly", 1),
    KinkStructure.DF_6M: ("dfly", 2),
    KinkStructure.CF_3M: ("condor", 1),
    KinkStructure.CF_6M: ("condor", 2),
}

_KINK_STRUCTURE_LEGS = {
    KinkStructure.BF_3M: 3,
    KinkStructure.BF_6M: 3,
    KinkStructure.DF_3M: 4,
    KinkStructure.DF_6M: 4,
    KinkStructure.CF_3M: 4,
    KinkStructure.CF_6M: 4,
}


@dataclass
class KinkFadeConfig:
    """Configuration for the SFR Kink-Fading Strategy."""

    # ── Data ──
    source: str = "BARCHART_STIRF-RL"
    curve: str = "USD-SOFR-1D-Q12STIRT"
    n_contracts: int = 12
    constant_maturity: bool = True

    # ── Structure selection ──
    structures: List[KinkStructure] = field(
        default_factory=lambda: [KinkStructure.BF_3M, KinkStructure.DF_3M]
    )

    # ── Signal parameters ──
    zscore_window: int = 60
    vol_window: int = 20
    carry_horizon: int = 1
    percentile_window: int = 60
    halflife_window: int = 120

    # ── Signal mode ──
    signal_mode: str = "zscore"  # "zscore", "percentile", "xsection", "intersection", "pca_residual"
    intersection_require_all: bool = False  # True = AND, False = OR with boost
    pca_n_components: int = 3
    pca_window: int = 252

    # ── Entry filters ──
    entry_min_zscore: float = 1.5
    entry_min_percentile: float = 0.85
    entry_min_xsection_rank: float = 0.8
    entry_max_vol: Optional[float] = None
    entry_require_carry: bool = False
    entry_min_risk_adj_roll: float = 0.0

    # ── Exit rules ──
    exit_mean_reversion: bool = True
    exit_take_profit_zscore: Optional[float] = 0.5
    exit_stop_loss_sd: Optional[float] = 2.0
    exit_take_profit_bp: Optional[float] = None
    exit_stop_loss_bp: Optional[float] = None
    exit_max_holding_days: int = 22
    exit_halflife_based: bool = False

    # ── Portfolio ──
    max_concurrent_trades: Optional[int] = 5
    no_duplicate_structures: bool = True
    belly_bpv: float = 100_000.0

    # ── Regime filters ──
    regime_fomc_blackout_days: Optional[int] = 5
    regime_max_vol_percentile: Optional[float] = None
    regime_min_halflife_days: Optional[float] = 3.0
    regime_max_halflife_days: Optional[float] = 120.0
    regime_max_adf_pvalue: Optional[float] = 0.20
    regime_halflife_gated: bool = False
    regime_vol_filter: bool = False
    regime_vol_percentile_window: int = 252

    # ── IMM Roll handling ──
    roll_adjusted: bool = True
    roll_blackout_days: Optional[int] = 3
    roll_model: str = "none"  # "none", "seasonal_demean", "fourier", "gbm_regime"
    roll_seasonal_window: int = 8  # quarters of history for seasonal models

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "KinkFadeConfig":
        """Build config from a plain dict, converting structure strings to enums."""
        d = dict(d)
        if "structures" in d and d["structures"]:
            raw = d["structures"]
            if isinstance(raw[0], str):
                d["structures"] = [KinkStructure(s) for s in raw]
        return cls(**d)

    def to_dict(self) -> Dict[str, Any]:
        from dataclasses import asdict
        d = asdict(self)
        d["structures"] = [s.value for s in self.structures]
        return d


# ═══════════════════════════════════════════════════════════════════
# Signal Normalization
# ═══════════════════════════════════════════════════════════════════

def compute_percentile_rank(
    curve: pd.DataFrame,
    window: int = 60,
) -> pd.DataFrame:
    """Rolling percentile rank: where current value sits in its trailing distribution.

    Returns DataFrame in [0, 1]. 0.95 = 95th percentile (extreme high).
    """
    def _pctile(arr):
        if len(arr) < 2 or np.all(np.isnan(arr)):
            return np.nan
        val = arr[-1]
        if np.isnan(val):
            return np.nan
        valid = arr[~np.isnan(arr)]
        return float(np.sum(valid <= val)) / len(valid)

    return curve.rolling(window, min_periods=max(20, window // 2)).apply(
        _pctile, raw=True
    )


def compute_cross_sectional_rank(curve: pd.DataFrame) -> pd.DataFrame:
    """Cross-sectional rank at each timestamp: rank among all structures in the strip.

    Returns DataFrame in [0, 1]. Uses absolute values for ranking
    (most extreme kink regardless of direction gets rank 1.0).
    """
    abs_curve = curve.abs()
    ranked = abs_curve.rank(axis=1, pct=True, na_option="keep")
    return ranked


def compute_directional_xsection_rank(curve: pd.DataFrame) -> pd.DataFrame:
    """Cross-sectional rank preserving direction.

    Returns DataFrame in [-1, 1]. Positive = rich (sell), negative = cheap (buy).
    The magnitude indicates how extreme relative to peers.
    """
    ranked = curve.rank(axis=1, pct=True, na_option="keep")
    return 2 * ranked - 1


# ═══════════════════════════════════════════════════════════════════
# Mean-Reversion Analytics
# ═══════════════════════════════════════════════════════════════════

def fit_ou_halflife(series: pd.Series) -> Dict[str, float]:
    """Fit OU model via AR(1) regression and return half-life + ADF p-value.

    AR(1): dx_t = a + b * x_{t-1} + eps
    Half-life = ln(2) / (-b)  [b < 0 for mean-reversion]

    Returns dict: {half_life, adf_pvalue, theta, mu, sigma, ar1_slope}.
    """
    clean = series.dropna()
    if len(clean) < 30:
        return {
            "half_life": np.inf, "adf_pvalue": 1.0, "theta": np.nan,
            "mu": 0.0, "sigma": 0.0, "ar1_slope": 0.0,
        }

    x = clean.values[:-1]
    dy = np.diff(clean.values)

    if len(x) < 10 or np.std(x) < 1e-12:
        return {
            "half_life": np.inf, "adf_pvalue": 1.0, "theta": float(clean.mean()),
            "mu": 0.0, "sigma": 0.0, "ar1_slope": 0.0,
        }

    coeffs = np.polyfit(x, dy, 1)
    slope, intercept = float(coeffs[0]), float(coeffs[1])

    k_daily = -slope
    if k_daily <= 0:
        k_daily = 1e-6

    theta = -intercept / slope if abs(slope) > 1e-12 else float(clean.mean())
    half_life = float(np.log(2) / k_daily)

    residuals = dy - (slope * x + intercept)
    sigma = float(np.std(residuals))

    # ADF test
    try:
        from statsmodels.tsa.stattools import adfuller
        adf_result = adfuller(
            clean.values,
            maxlag=int(min(len(clean) // 4, 20)),
            regression="c",
        )
        adf_pvalue = float(adf_result[1])
    except Exception:
        adf_pvalue = 1.0

    return {
        "half_life": half_life,
        "adf_pvalue": adf_pvalue,
        "theta": theta,
        "mu": k_daily,
        "sigma": sigma,
        "ar1_slope": slope,
    }


def compute_rolling_halflife(
    curve: pd.DataFrame,
    window: int = 120,
) -> pd.DataFrame:
    """Rolling OU half-life for each column.

    Returns DataFrame of half-lives in business days.
    """
    result = pd.DataFrame(np.nan, index=curve.index, columns=curve.columns)
    min_obs = max(30, window // 3)

    for col in curve.columns:
        series = curve[col].dropna()
        for i in range(min_obs, len(series)):
            start = max(0, i - window)
            chunk = series.iloc[start:i + 1]
            if len(chunk) < min_obs:
                continue

            x = chunk.values[:-1]
            dy = np.diff(chunk.values)
            if len(x) < 10 or np.std(x) < 1e-12:
                continue

            coeffs = np.polyfit(x, dy, 1)
            slope = float(coeffs[0])
            if slope >= 0:
                continue
            hl = float(np.log(2) / (-slope))
            if 1.0 < hl < 500.0:
                result.loc[series.index[i], col] = hl

    return result


def compute_halflife_snapshot(curve: pd.DataFrame, window: int = 120) -> pd.Series:
    """Half-life cross-section at the latest date."""
    result = {}
    min_obs = max(30, window // 3)
    for col in curve.columns:
        chunk = curve[col].dropna().iloc[-window:]
        if len(chunk) < min_obs:
            result[col] = np.nan
            continue
        ou = fit_ou_halflife(chunk)
        result[col] = ou["half_life"]
    return pd.Series(result)


def compute_adf_snapshot(curve: pd.DataFrame, window: int = 120) -> pd.Series:
    """ADF p-value cross-section at the latest date."""
    result = {}
    min_obs = max(30, window // 3)
    for col in curve.columns:
        chunk = curve[col].dropna().iloc[-window:]
        if len(chunk) < min_obs:
            result[col] = 1.0
            continue
        ou = fit_ou_halflife(chunk)
        result[col] = ou["adf_pvalue"]
    return pd.Series(result)


# ═══════════════════════════════════════════════════════════════════
# Regime Detection
# ═══════════════════════════════════════════════════════════════════

# FOMC dates (announcement days) 2020-2027
_FOMC_DATES = [
    "2020-01-29", "2020-03-03", "2020-03-15", "2020-04-29", "2020-06-10",
    "2020-07-29", "2020-09-16", "2020-11-05", "2020-12-16",
    "2021-01-27", "2021-03-17", "2021-04-28", "2021-06-16",
    "2021-07-28", "2021-09-22", "2021-11-03", "2021-12-15",
    "2022-01-26", "2022-03-16", "2022-05-04", "2022-06-15",
    "2022-07-27", "2022-09-21", "2022-11-02", "2022-12-14",
    "2023-02-01", "2023-03-22", "2023-05-03", "2023-06-14",
    "2023-07-26", "2023-09-20", "2023-11-01", "2023-12-13",
    "2024-01-31", "2024-03-20", "2024-05-01", "2024-06-12",
    "2024-07-31", "2024-09-18", "2024-11-07", "2024-12-18",
    "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18",
    "2025-07-30", "2025-09-17", "2025-10-29", "2025-12-17",
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
    "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-16",
    "2027-01-27", "2027-03-17", "2027-04-28", "2027-06-16",
    "2027-07-28", "2027-09-15", "2027-10-27", "2027-12-15",
]
_FOMC_DATES_PARSED = [pd.Timestamp(d) for d in _FOMC_DATES]


def compute_imm_roll_dates(start_year: int = 2019, end_year: int = 2028) -> List[pd.Timestamp]:
    """IMM roll dates: 3rd Wednesday of Mar/Jun/Sep/Dec."""
    from calendar import monthcalendar, WEDNESDAY
    dates = []
    for yr in range(start_year, end_year + 1):
        for mo in [3, 6, 9, 12]:
            cal = monthcalendar(yr, mo)
            wed_count = 0
            for week in cal:
                if week[WEDNESDAY] != 0:
                    wed_count += 1
                    if wed_count == 3:
                        dates.append(pd.Timestamp(yr, mo, week[WEDNESDAY]))
                        break
    return dates


_IMM_ROLL_DATES = compute_imm_roll_dates()


def days_to_next_imm_roll(dt_val) -> int:
    """Business days until next IMM roll date."""
    dt_date = pd.Timestamp(dt_val).normalize()
    if dt_date.tzinfo is not None:
        dt_date = dt_date.tz_localize(None)
    for rd in _IMM_ROLL_DATES:
        if rd >= dt_date:
            return max(0, len(pd.bdate_range(dt_date, rd)) - 1)
    return 999


def compute_imm_roll_proximity_ts(index: pd.DatetimeIndex) -> pd.Series:
    """Business days to next IMM roll for each date in index."""
    return pd.Series(
        [days_to_next_imm_roll(dt) for dt in index],
        index=index,
        dtype=float,
    )


# ═══════════════════════════════════════════════════════════════════
# ML Roll-Seasonality Models
# ═══════════════════════════════════════════════════════════════════

def _quarter_phase(index: pd.DatetimeIndex) -> pd.Series:
    """Position within IMM quarter as fraction [0, 1].

    0.0 = day after previous roll, 1.0 = roll day.
    """
    phase = pd.Series(np.nan, index=index)
    roll_dates = sorted(_IMM_ROLL_DATES)
    for i in range(len(index)):
        dt = pd.Timestamp(index[i]).normalize()
        if dt.tzinfo is not None:
            dt = dt.tz_localize(None)
        prev_roll = None
        next_roll = None
        for rd in roll_dates:
            if rd <= dt:
                prev_roll = rd
            if rd > dt and next_roll is None:
                next_roll = rd
        if prev_roll is not None and next_roll is not None:
            total = (next_roll - prev_roll).days
            elapsed = (dt - prev_roll).days
            phase.iloc[i] = elapsed / total if total > 0 else 0.5
    return phase


def apply_seasonal_demean(
    curve: pd.DataFrame,
    index: pd.DatetimeIndex,
    n_bins: int = 13,
) -> pd.DataFrame:
    """Remove quarterly seasonal pattern from fly levels.

    Bins each day by its position in the IMM quarter (0-1), computes
    the average fly level in each bin over history, and subtracts it.
    This removes the systematic roll-driven component.
    """
    phase = _quarter_phase(index)
    bins = pd.cut(phase, bins=n_bins, labels=False)
    adjusted = curve.copy()
    for col in curve.columns:
        for b in range(n_bins):
            mask = bins == b
            if mask.sum() > 5:
                seasonal_mean = curve.loc[mask, col].mean()
                adjusted.loc[mask, col] = curve.loc[mask, col] - seasonal_mean
    return adjusted


def apply_fourier_deseason(
    curve: pd.DataFrame,
    index: pd.DatetimeIndex,
    n_harmonics: int = 2,
) -> pd.DataFrame:
    """Remove quarterly seasonality via Fourier regression.

    Fits sin/cos harmonics at the quarterly frequency (period ~63 bdays)
    to each fly series and subtracts the fitted seasonal component.
    More flexible than binned demeaning — captures smooth seasonal shapes.
    """
    phase = _quarter_phase(index).values
    valid = ~np.isnan(phase)
    adjusted = curve.copy()

    for col in curve.columns:
        y = curve[col].values.copy()
        both_valid = valid & ~np.isnan(y)
        if both_valid.sum() < 30:
            continue

        X_cols = []
        for k in range(1, n_harmonics + 1):
            X_cols.append(np.sin(2 * np.pi * k * phase))
            X_cols.append(np.cos(2 * np.pi * k * phase))
        X = np.column_stack(X_cols)
        X = np.column_stack([np.ones(len(phase)), X])

        X_fit = X[both_valid]
        y_fit = y[both_valid]

        try:
            beta = np.linalg.lstsq(X_fit, y_fit, rcond=None)[0]
            seasonal = X @ beta
            seasonal[~valid] = 0.0
            adjusted[col] = y - seasonal + np.nanmean(y_fit)
        except np.linalg.LinAlgError:
            pass

    return adjusted


def build_gbm_roll_regime_features(
    curve: pd.DataFrame,
    rates: pd.DataFrame,
    index: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Build feature matrix for GBM roll-regime classifier.

    Features capture quarterly cycle position, vol regime, and
    curve shape — all observable at time t (no lookahead).
    """
    phase = _quarter_phase(index)
    features = pd.DataFrame(index=index)

    features['quarter_phase'] = phase
    features['phase_sin1'] = np.sin(2 * np.pi * phase)
    features['phase_cos1'] = np.cos(2 * np.pi * phase)
    features['phase_sin2'] = np.sin(4 * np.pi * phase)
    features['phase_cos2'] = np.cos(4 * np.pi * phase)

    # Days to next roll
    features['days_to_roll'] = compute_imm_roll_proximity_ts(index)

    # Vol features
    strip_changes = rates.diff()
    features['strip_vol_5d'] = strip_changes.rolling(5, min_periods=3).std().mean(axis=1) * np.sqrt(252)
    features['strip_vol_20d'] = strip_changes.rolling(20, min_periods=10).std().mean(axis=1) * np.sqrt(252)
    features['vol_ratio'] = features['strip_vol_5d'] / features['strip_vol_20d'].replace(0, np.nan)

    # Curve shape
    features['slope_1_12'] = rates.iloc[:, -1] - rates.iloc[:, 0]
    features['curvature_mid'] = rates.iloc[:, 0] - 2 * rates.iloc[:, 5] + rates.iloc[:, -1]

    # Quarter identity (one-hot: Q1=Mar, Q2=Jun, Q3=Sep, Q4=Dec)
    months = pd.DatetimeIndex(index).month
    for q, m in [(1, 3), (2, 6), (3, 9), (4, 12)]:
        quarter_months = [(m - 2) % 12 or 12, (m - 1) % 12 or 12, m]
        features[f'is_q{q}'] = months.isin(quarter_months).astype(float)

    return features


def apply_gbm_roll_filter(
    curve: pd.DataFrame,
    rates: pd.DataFrame,
    index: pd.DatetimeIndex,
    lookahead_days: int = 5,
    min_train_quarters: int = 4,
) -> pd.Series:
    """GBM classifier: predict whether next 5 days' fly change is roll-driven.

    Trains on expanding window. Label = 1 if the fly changes in the next
    `lookahead_days` are outliers relative to non-roll periods.
    Returns Series of probabilities [0, 1] that current date is roll-contaminated.
    High probability → suppress signal (likely roll artifact).

    Uses walk-forward: only trains on data strictly before current date.
    """
    from sklearn.ensemble import GradientBoostingClassifier

    features = build_gbm_roll_regime_features(curve, rates, index)
    avg_fly_change = curve.diff().abs().mean(axis=1)

    # Label: is the average fly change in the next N days an outlier?
    fwd_vol = avg_fly_change.rolling(lookahead_days).mean().shift(-lookahead_days)
    rolling_median = avg_fly_change.rolling(60, min_periods=20).median()
    rolling_std = avg_fly_change.rolling(60, min_periods=20).std()
    is_outlier = (fwd_vol > rolling_median + 1.5 * rolling_std).astype(int)

    probs = pd.Series(0.0, index=index)
    quarter_len = 63

    for i in range(min_train_quarters * quarter_len, len(index)):
        train_end = i
        train_start = max(0, train_end - 8 * quarter_len)

        X_train = features.iloc[train_start:train_end].dropna()
        y_train = is_outlier.iloc[train_start:train_end].reindex(X_train.index).dropna()
        common = X_train.index.intersection(y_train.index)
        if len(common) < 60:
            continue

        X_tr = X_train.loc[common]
        y_tr = y_train.loc[common]
        if y_tr.sum() < 3 or (y_tr == 0).sum() < 3:
            continue

        X_pred = features.iloc[i:i + 1].dropna()
        if X_pred.empty:
            continue

        try:
            clf = GradientBoostingClassifier(
                n_estimators=50, max_depth=3, learning_rate=0.1,
                min_samples_leaf=5, random_state=42,
            )
            clf.fit(X_tr.values, y_tr.values)
            prob = clf.predict_proba(X_pred.values)[0]
            probs.iloc[i] = float(prob[1]) if len(prob) > 1 else 0.0
        except Exception:
            pass

    return probs


def days_to_next_fomc(dt_val) -> int:
    """Business days until next FOMC announcement."""
    dt_date = pd.Timestamp(dt_val).normalize()
    if dt_date.tzinfo is not None:
        dt_date = dt_date.tz_localize(None)
    for fomc in _FOMC_DATES_PARSED:
        if fomc >= dt_date:
            return max(0, len(pd.bdate_range(dt_date, fomc)) - 1)
    return 999


def compute_fomc_proximity_ts(index: pd.DatetimeIndex) -> pd.Series:
    """Business days to next FOMC for each date in index."""
    return pd.Series(
        [days_to_next_fomc(dt) for dt in index],
        index=index,
        dtype=float,
    )


def compute_vol_regime_ts(
    curve: pd.DataFrame,
    vol_window: int = 20,
    percentile_window: int = 252,
) -> pd.DataFrame:
    """Rolling realized vol percentile for each structure.

    Returns DataFrame in [0, 1]. High = volatile regime.
    """
    daily_vol = curve.diff().rolling(vol_window, min_periods=max(10, vol_window // 2)).std() * np.sqrt(252)

    def _pctile(arr):
        if len(arr) < 2:
            return np.nan
        val = arr[-1]
        if np.isnan(val):
            return np.nan
        valid = arr[~np.isnan(arr)]
        return float(np.sum(valid <= val)) / len(valid)

    return daily_vol.rolling(percentile_window, min_periods=60).apply(_pctile, raw=True)


# ═══════════════════════════════════════════════════════════════════
# Signal Table Construction
# ═══════════════════════════════════════════════════════════════════

@dataclass
class KinkSignal:
    """A single kink-fading signal at a point in time."""
    structure_id: str       # e.g., "SFR1/SFR2/SFR3" (BF) or "SFR1/SFR2/SFR3|SFR2/SFR3/SFR4" (DF)
    structure_type: KinkStructure
    level: float            # structure level in bps
    zscore: float
    percentile: float       # time-series percentile [0, 1]
    xsection_rank: float    # cross-sectional rank [0, 1]
    vol: float              # annualized realized vol
    roll: float             # carry/roll in bps
    risk_adj_roll: float
    half_life: float        # OU half-life in bdays (NaN if not computed)
    adf_pvalue: float       # ADF p-value (NaN if not computed)
    direction: str          # "sell_kink" (fade rich) or "buy_kink" (fade cheap)
    composite_score: float  # combined signal strength
    passes_entry: bool


def _compute_composite_score(
    zscore: float,
    percentile: float,
    xsection_rank: float,
    config: KinkFadeConfig,
) -> float:
    """Combine signal metrics into a single composite score.

    Higher absolute value = stronger signal.
    """
    if config.signal_mode in ("zscore", "pca_residual"):
        return abs(zscore)
    elif config.signal_mode == "percentile":
        return abs(percentile - 0.5) * 2  # map [0,1] to [0,1] centered
    elif config.signal_mode == "xsection":
        return xsection_rank
    elif config.signal_mode == "intersection":
        z_pass = abs(zscore) >= config.entry_min_zscore
        p_pass = percentile >= config.entry_min_percentile or percentile <= (1 - config.entry_min_percentile)
        x_pass = xsection_rank >= config.entry_min_xsection_rank

        n_passing = sum([z_pass, p_pass, x_pass])
        if config.intersection_require_all and n_passing < 3:
            return 0.0
        # weighted combo: z-score contributes most, rank adds tiebreaker
        return abs(zscore) * 0.5 + (abs(percentile - 0.5) * 2) * 0.3 + xsection_rank * 0.2
    return abs(zscore)


def _check_entry_filters(
    zscore: float,
    percentile: float,
    xsection_rank: float,
    vol: float,
    roll: float,
    risk_adj_roll: float,
    direction: str,
    half_life: float,
    adf_pvalue: float,
    config: KinkFadeConfig,
) -> bool:
    """Check whether a signal passes all entry filters."""
    mode = config.signal_mode

    # Signal threshold check
    if mode in ("zscore", "pca_residual") or mode == "intersection":
        if abs(zscore) < config.entry_min_zscore:
            return False
    if mode == "percentile" or mode == "intersection":
        extreme = percentile >= config.entry_min_percentile or percentile <= (1 - config.entry_min_percentile)
        if not extreme:
            if mode == "percentile":
                return False
            if mode == "intersection" and config.intersection_require_all:
                return False
    if mode == "xsection" or mode == "intersection":
        if xsection_rank < config.entry_min_xsection_rank:
            if mode == "xsection":
                return False
            if mode == "intersection" and config.intersection_require_all:
                return False

    # Vol filter
    if config.entry_max_vol is not None and not np.isnan(vol):
        if vol > config.entry_max_vol:
            return False

    # Carry alignment
    if config.entry_require_carry and not np.isnan(roll):
        carry_aligned = (direction == "buy_kink" and roll > 0) or \
                        (direction == "sell_kink" and roll < 0)
        if not carry_aligned:
            return False
        if config.entry_min_risk_adj_roll > 0 and not np.isnan(risk_adj_roll):
            if abs(risk_adj_roll) < config.entry_min_risk_adj_roll:
                return False

    # Half-life gating
    if config.regime_halflife_gated and not np.isnan(half_life):
        if config.regime_min_halflife_days is not None and half_life < config.regime_min_halflife_days:
            return False
        if config.regime_max_halflife_days is not None and half_life > config.regime_max_halflife_days:
            return False

    # ADF stationarity
    if config.regime_max_adf_pvalue is not None and not np.isnan(adf_pvalue):
        if adf_pvalue > config.regime_max_adf_pvalue:
            return False

    return True


def compute_kink_curves(
    rates: pd.DataFrame,
    config: KinkFadeConfig,
) -> Dict[KinkStructure, pd.DataFrame]:
    """Compute all requested kink structure curves from the rate panel."""
    curves = {}
    for ks in config.structures:
        kind, gap = _KINK_STRUCTURE_TO_COMPUTE[ks]
        if kind == "fly":
            curves[ks] = compute_fly_curve(rates, gap)
        elif kind == "dfly":
            curves[ks] = compute_dfly_curve(rates, gap)
        elif kind == "condor":
            curves[ks] = compute_condor_curve(rates, gap)
    return curves


def _apply_roll_model(
    curve: pd.DataFrame,
    rates: pd.DataFrame,
    config: KinkFadeConfig,
) -> Tuple[pd.DataFrame, Optional[pd.Series]]:
    """Apply the configured roll-seasonality model to a fly curve.

    Returns (adjusted_curve, gbm_probs_or_None).
    """
    model = config.roll_model
    gbm_probs = None

    if model == "seasonal_demean":
        curve = apply_seasonal_demean(curve, curve.index)
    elif model == "fourier":
        curve = apply_fourier_deseason(curve, curve.index, n_harmonics=2)
    elif model == "gbm_regime":
        gbm_probs = apply_gbm_roll_filter(curve, rates, curve.index)

    return curve, gbm_probs


def build_kink_fade_analytics(
    rates: pd.DataFrame,
    config: KinkFadeConfig,
) -> Dict[KinkStructure, Dict[str, pd.DataFrame]]:
    """Build all analytics DataFrames for each structure type.

    Returns dict of {KinkStructure: {curve, zscore, percentile, xsection, vol, roll, risk_adj_roll, [gbm_probs]}}.
    """
    raw_curves = compute_kink_curves(rates, config)
    analytics: Dict[KinkStructure, Dict[str, pd.DataFrame]] = {}

    for ks, raw_curve in raw_curves.items():
        if raw_curve.empty:
            continue

        curve, gbm_probs = _apply_roll_model(raw_curve, rates, config)

        zscore = compute_zscore_ts(curve, config.zscore_window)
        pctile = compute_percentile_rank(curve, config.percentile_window)
        xsection = compute_cross_sectional_rank(curve)

        vol_series = curve.diff().rolling(
            config.vol_window, min_periods=max(10, config.vol_window // 2)
        ).std() * np.sqrt(252)

        # Roll: shift-and-difference for each structure
        latest_row = curve.iloc[-1] if len(curve) > 0 else pd.Series(dtype=float)
        roll_vals = compute_roll(curve, config.carry_horizon)
        # Broadcast roll to time series (static snapshot carry)
        roll_ts = pd.DataFrame(
            np.tile(roll_vals.values, (len(curve), 1)),
            index=curve.index,
            columns=curve.columns,
        )
        risk_adj = roll_ts / vol_series.replace(0, np.nan)

        anl_dict = {
            "curve": curve,
            "zscore": zscore,
            "percentile": pctile,
            "xsection": xsection,
            "vol": vol_series,
            "roll": roll_ts,
            "risk_adj_roll": risk_adj,
        }
        if gbm_probs is not None:
            anl_dict["gbm_roll_probs"] = gbm_probs

        analytics[ks] = anl_dict

    return analytics


def build_kink_fade_signal_table(
    rates: pd.DataFrame,
    config: KinkFadeConfig,
    halflife_data: Optional[Dict[KinkStructure, pd.DataFrame]] = None,
    adf_data: Optional[Dict[KinkStructure, pd.Series]] = None,
) -> Dict[pd.Timestamp, List[KinkSignal]]:
    """Build date-keyed signal table for the kink-fading strategy.

    Parameters
    ----------
    rates : Rate panel (dates × contracts).
    config : Strategy configuration.
    halflife_data : Optional pre-computed rolling half-life DataFrames per structure.
    adf_data : Optional pre-computed ADF p-value Series per structure.
    """
    analytics = build_kink_fade_analytics(rates, config)

    # FOMC proximity
    fomc_proximity = None
    if config.regime_fomc_blackout_days is not None:
        fomc_proximity = compute_fomc_proximity_ts(rates.index)

    # IMM roll proximity
    imm_roll_proximity = None
    if config.roll_blackout_days is not None:
        imm_roll_proximity = compute_imm_roll_proximity_ts(rates.index)

    signal_table: Dict[pd.Timestamp, List[KinkSignal]] = {}

    for dt_idx in rates.index:
        # FOMC blackout
        if fomc_proximity is not None and config.regime_fomc_blackout_days is not None:
            days_fomc = fomc_proximity.get(dt_idx, 999)
            if days_fomc <= config.regime_fomc_blackout_days:
                continue

        # IMM roll blackout
        if imm_roll_proximity is not None and config.roll_blackout_days is not None:
            days_roll = imm_roll_proximity.get(dt_idx, 999)
            if days_roll <= config.roll_blackout_days:
                continue

        signals: List[KinkSignal] = []

        for ks, anl in analytics.items():
            if dt_idx not in anl["curve"].index:
                continue

            # GBM roll-regime filter: skip if model says roll-contaminated
            if "gbm_roll_probs" in anl:
                gbm_p = anl["gbm_roll_probs"].get(dt_idx, 0.0)
                if not np.isnan(gbm_p) and gbm_p > 0.5:
                    continue

            for col in anl["curve"].columns:
                level = anl["curve"].loc[dt_idx, col]
                z = anl["zscore"].loc[dt_idx, col] if dt_idx in anl["zscore"].index else np.nan
                pct = anl["percentile"].loc[dt_idx, col] if dt_idx in anl["percentile"].index else np.nan
                xsr = anl["xsection"].loc[dt_idx, col] if dt_idx in anl["xsection"].index else np.nan
                vol = anl["vol"].loc[dt_idx, col] if dt_idx in anl["vol"].index else np.nan
                roll = anl["roll"].loc[dt_idx, col] if dt_idx in anl["roll"].index else np.nan
                radj = anl["risk_adj_roll"].loc[dt_idx, col] if dt_idx in anl["risk_adj_roll"].index else np.nan

                if np.isnan(z) or np.isnan(level):
                    continue

                # Half-life
                hl = np.nan
                if halflife_data is not None and ks in halflife_data:
                    hl_df = halflife_data[ks]
                    if dt_idx in hl_df.index and col in hl_df.columns:
                        hl = hl_df.loc[dt_idx, col]

                # ADF (snapshot, not rolling — applies to all dates)
                adf_p = np.nan
                if adf_data is not None and ks in adf_data:
                    adf_s = adf_data[ks]
                    if col in adf_s.index:
                        adf_p = adf_s[col]

                # Direction: z > 0 → kink rich → sell (fade); z < 0 → kink cheap → buy (fade)
                direction = "sell_kink" if z > 0 else "buy_kink"

                composite = _compute_composite_score(z, pct if not np.isnan(pct) else 0.5, xsr if not np.isnan(xsr) else 0.5, config)

                passes = _check_entry_filters(
                    z, pct if not np.isnan(pct) else 0.5,
                    xsr if not np.isnan(xsr) else 0.5,
                    vol, roll, radj, direction, hl, adf_p, config,
                )

                signals.append(KinkSignal(
                    structure_id=col,
                    structure_type=ks,
                    level=float(level),
                    zscore=float(z),
                    percentile=float(pct) if not np.isnan(pct) else 0.5,
                    xsection_rank=float(xsr) if not np.isnan(xsr) else 0.5,
                    vol=float(vol) if not np.isnan(vol) else 0.0,
                    roll=float(roll) if not np.isnan(roll) else 0.0,
                    risk_adj_roll=float(radj) if not np.isnan(radj) else 0.0,
                    half_life=float(hl) if not np.isnan(hl) else np.nan,
                    adf_pvalue=float(adf_p) if not np.isnan(adf_p) else np.nan,
                    direction=direction,
                    composite_score=composite,
                    passes_entry=passes,
                ))

        if signals:
            # Sort by composite score descending (strongest signals first)
            signals.sort(key=lambda s: s.composite_score, reverse=True)
            signal_table[pd.Timestamp(dt_idx)] = signals

    return signal_table


# ═══════════════════════════════════════════════════════════════════
# Convenience: Full Pipeline
# ═══════════════════════════════════════════════════════════════════

def run_kink_fade_analytics(
    start,
    end,
    config: Optional[KinkFadeConfig] = None,
    *,
    rates_panel: Optional[pd.DataFrame] = None,
    curve_mdp=None,
    ts_builder=None,
    compute_halflife: bool = True,
    compute_adf: bool = True,
) -> Dict[str, Any]:
    """Run the full kink-fading analytics pipeline.

    Returns dict with:
      - rates: rate panel
      - curves: structure curve DataFrames
      - analytics: full analytics per structure
      - halflife: rolling half-life DataFrames (if computed)
      - adf: ADF snapshot Series (if computed)
      - signal_table: date-keyed signal table
      - config: config used
    """
    if config is None:
        config = KinkFadeConfig()

    if rates_panel is None:
        rv_config = SFRCalSpreadRVConfig(
            source=config.source,
            curve=config.curve,
            n_contracts=config.n_contracts,
            constant_maturity=config.constant_maturity,
            roll_adjusted=config.roll_adjusted,
        )
        rates_panel = load_rate_panel(
            rv_config, start=start, end=end,
            curve_mdp=curve_mdp, ts_builder=ts_builder,
        )

    curves = compute_kink_curves(rates_panel, config)
    analytics = build_kink_fade_analytics(rates_panel, config)

    halflife_data = None
    if compute_halflife:
        halflife_data = {}
        for ks, curve in curves.items():
            if not curve.empty:
                halflife_data[ks] = compute_rolling_halflife(curve, config.halflife_window)

    adf_data = None
    if compute_adf:
        adf_data = {}
        for ks, curve in curves.items():
            if not curve.empty:
                adf_data[ks] = compute_adf_snapshot(curve, config.halflife_window)

    signal_table = build_kink_fade_signal_table(
        rates_panel, config,
        halflife_data=halflife_data,
        adf_data=adf_data,
    )

    return {
        "rates": rates_panel,
        "curves": curves,
        "analytics": analytics,
        "halflife": halflife_data,
        "adf": adf_data,
        "signal_table": signal_table,
        "config": config,
    }


# ═══════════════════════════════════════════════════════════════════
# PCA-Residual Mode
# ═══════════════════════════════════════════════════════════════════

def compute_pca_residual_rates(
    rates: pd.DataFrame,
    n_components: int = 3,
    window: int = 252,
) -> pd.DataFrame:
    """Remove first K PCA components from rate changes, reconstruct residual levels.

    PC1 ~ level, PC2 ~ slope, PC3 ~ curvature. Residual = idiosyncratic kinks.
    """
    from sklearn.decomposition import PCA

    changes = rates.diff().dropna()
    residual_changes = pd.DataFrame(np.nan, index=changes.index, columns=changes.columns)
    min_obs = max(60, window // 3)

    for i in range(min_obs, len(changes)):
        start_idx = max(0, i - window)
        chunk = changes.iloc[start_idx:i].dropna()
        if len(chunk) < min_obs:
            continue

        n_comp = min(n_components, len(chunk.columns) - 1, len(chunk) - 1)
        if n_comp < 1:
            continue

        pca = PCA(n_components=n_comp)
        pca.fit(chunk.values)

        current = changes.iloc[i:i + 1].values
        projection = pca.inverse_transform(pca.transform(current))
        residual_changes.iloc[i] = (current - projection)[0]

    return residual_changes.cumsum()


def build_kink_fade_analytics_pca(
    rates: pd.DataFrame,
    config: KinkFadeConfig,
) -> Dict[KinkStructure, Dict[str, pd.DataFrame]]:
    """Build analytics from PCA-residual rates instead of raw rates."""
    residual_rates = compute_pca_residual_rates(
        rates, n_components=config.pca_n_components, window=config.pca_window,
    )
    return build_kink_fade_analytics(residual_rates, config)


# ═══════════════════════════════════════════════════════════════════
# Vol Regime Filter (MOVE proxy)
# ═══════════════════════════════════════════════════════════════════

def compute_strip_vol_proxy(
    rates: pd.DataFrame,
    vol_window: int = 20,
    percentile_window: int = 252,
) -> pd.Series:
    """MOVE proxy: average annualized realized vol across the strip, as percentile.

    Returns Series in [0, 1]. High = volatile regime.
    """
    daily_vols = rates.diff().rolling(vol_window, min_periods=max(10, vol_window // 2)).std() * np.sqrt(252)
    avg_vol = daily_vols.mean(axis=1)

    def _pctile(arr):
        if len(arr) < 2:
            return np.nan
        val = arr[-1]
        if np.isnan(val):
            return np.nan
        valid = arr[~np.isnan(arr)]
        return float(np.sum(valid <= val)) / len(valid)

    return avg_vol.rolling(percentile_window, min_periods=60).apply(_pctile, raw=True)


# ═══════════════════════════════════════════════════════════════════
# Backtest Runner (for grid search)
# ═══════════════════════════════════════════════════════════════════

def run_backtest(
    config_dict: Dict[str, Any],
    rates: pd.DataFrame,
    curve_mdp,
    bt_datetimes: list,
    *,
    compute_halflife: bool = False,
    compute_adf: bool = False,
    pca_residual_rates: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:
    """Run a single backtest from a config dict and return metrics.

    Parameters
    ----------
    config_dict : Strategy parameters (passed to KinkFadeConfig.from_dict).
    rates : Pre-loaded rate panel.
    curve_mdp : Market data provider.
    bt_datetimes : List of backtest datetime steps.
    pca_residual_rates : Pre-computed PCA residual rates (avoids recomputing).
    """
    from BT.signals.sfr_kink_fade_triggers import KinkFadeEntryTrigger, KinkFadeExitTrigger
    from BT.data_handler import TimeGrid
    from BT.query_engine import QueryDrivenBacktest
    from BT.query_strategy import QueryStrategy

    config = KinkFadeConfig.from_dict(config_dict)

    # Build analytics — use PCA residual if requested
    if config.signal_mode == "pca_residual":
        input_rates = pca_residual_rates if pca_residual_rates is not None else \
            compute_pca_residual_rates(rates, config.pca_n_components, config.pca_window)
    else:
        input_rates = rates

    curves = compute_kink_curves(input_rates, config)

    halflife_data = None
    if compute_halflife or config.regime_halflife_gated:
        halflife_data = {}
        for ks, curve in curves.items():
            if not curve.empty:
                halflife_data[ks] = compute_rolling_halflife(curve, config.halflife_window)

    adf_data = None
    if compute_adf or config.regime_max_adf_pvalue is not None:
        adf_data = {}
        for ks, curve in curves.items():
            if not curve.empty:
                adf_data[ks] = compute_adf_snapshot(curve, config.halflife_window)

    # Vol regime filter
    vol_regime = None
    if config.regime_vol_filter:
        vol_regime = compute_strip_vol_proxy(rates, config.vol_window, config.regime_vol_percentile_window)

    signal_table = build_kink_fade_signal_table(
        input_rates, config,
        halflife_data=halflife_data,
        adf_data=adf_data,
    )

    # If vol regime filter active, remove dates in top vol regime percentile
    if vol_regime is not None and config.regime_max_vol_percentile is not None:
        filtered = {}
        for dt, sigs in signal_table.items():
            vr = vol_regime.get(dt, np.nan)
            if np.isnan(vr) or vr <= config.regime_max_vol_percentile:
                filtered[dt] = sigs
        signal_table = filtered

    entry_trigger = KinkFadeEntryTrigger(signal_table, config)
    exit_trigger = KinkFadeExitTrigger(signal_table, config)

    strategy = QueryStrategy(
        name='kink_fade_grid',
        triggers=[entry_trigger, exit_trigger],
        default_mdp=curve_mdp,
    )

    bt = QueryDrivenBacktest(
        time_grid=TimeGrid(bt_datetimes),
        strategy=strategy,
        mdp=curve_mdp,
        show_progress=False,
    )
    bt.run()

    # Extract metrics
    mtm = pd.Series(bt.mtm_history).sort_index()
    if len(mtm) == 0:
        return {"sharpe": 0, "final_mtm": 0, "max_dd": 0, "n_trades": 0,
                "win_rate": 0, "calmar": 0, "avg_pnl": 0, "hit_rate": 0,
                "n_closed": 0, "daily_pnl": [],
                "sr_per_period": 0.0, "T_obs": 0, "skew": 0.0, "kurt": 3.0,
                "config": config_dict}

    daily_pnl = mtm.diff().dropna()
    std_d = daily_pnl.std()
    sharpe = float(daily_pnl.mean() / std_d * np.sqrt(252)) if std_d > 0 else 0.0
    peak = mtm.cummax()
    dd = mtm - peak
    max_dd = float(dd.min())
    calmar = float(daily_pnl.mean() * 252 / abs(max_dd)) if max_dd != 0 else 0.0
    hit_rate = float((daily_pnl > 0).mean())
    n_trades = len(bt.portfolio.trades_log)

    # Closed position stats
    closed = getattr(bt.portfolio, 'closed_positions_log', []) or []
    n_closed = len(closed)
    realized_pnls = [cp.get('realized_pnl', 0) for cp in closed]
    win_rate = float(sum(1 for p in realized_pnls if p > 0) / n_closed) if n_closed else 0.0
    avg_pnl = float(np.mean(realized_pnls)) if realized_pnls else 0.0
    avg_hold = float(np.mean([cp.get('holding_period_days', 0) for cp in closed])) if closed else 0.0

    # Per-structure breakdown
    struct_pnl = {}
    for cp in closed:
        st = (cp.get('position_meta') or {}).get('structure_type', 'unknown')
        struct_pnl.setdefault(st, []).append(cp.get('realized_pnl', 0))

    # Per-period stats for downstream Deflated Sharpe gating.
    from BT.signals.deflated_sharpe import sharpe_stats
    sr_stats = sharpe_stats(daily_pnl.values)

    return {
        "sharpe": round(sharpe, 3),
        "final_mtm": round(float(mtm.iloc[-1]), 0),
        "max_dd": round(max_dd, 0),
        "calmar": round(calmar, 3),
        "hit_rate": round(hit_rate, 3),
        "n_trades": n_trades,
        "n_closed": n_closed,
        "win_rate": round(win_rate, 3),
        "avg_pnl": round(avg_pnl, 0),
        "avg_hold_days": round(avg_hold, 1),
        "struct_pnl": {k: round(sum(v), 0) for k, v in struct_pnl.items()},
        # Per-period series + moments needed by deflated_sharpe.apply_dsr_gate.
        "daily_pnl": daily_pnl.values.tolist(),
        "sr_per_period": sr_stats["sr"],
        "T_obs": sr_stats["T"],
        "skew": sr_stats["skew"],
        "kurt": sr_stats["kurt"],
        "config": config_dict,
    }
