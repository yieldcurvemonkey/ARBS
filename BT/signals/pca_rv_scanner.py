"""Two-stage PCA relative value scanner for swap curves.

Implements the Standard Chartered methodology (Lee, Davies, Fernandez 2013):
  Stage 1: Full-curve PCA scan across the forward surface
  Stage 2: Trade-specific PCA weighting for level+slope neutrality
  Stage 3: OU mean-reversion analytics (via arbitragelab)
  Stage 4: Carry/roll-down integration and trade filtering

Reference:
  - SC "Introducing a relative-value tool for swaps" (Aug 2013)
  - ASM Quant Macro "PCA ~ Part II" (Jun 2015)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.decomposition import PCA

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════

@dataclass
class PCARVScannerConfig:
    """Configuration for the two-stage PCA RV scanner."""

    # Curve identity
    curve: str = "USD-SOFR-1D"
    source: str = "ERIS_EOD_LIVE-RL_BASIC"

    # Tenor grid (spot tenors scanned across the surface)
    tenors: List[str] = field(default_factory=lambda: [
        "1Y", "2Y", "3Y", "4Y", "5Y", "7Y", "8Y", "9Y",
        "10Y", "15Y", "20Y", "25Y", "30Y",
    ])

    # Forward starts (None = spot curve)
    forward_starts: List[Optional[str]] = field(default_factory=lambda: [
        None, "1M", "3M", "6M", "1Y", "2Y", "5Y", "7Y", "10Y",
    ])

    # PCA parameters
    pca_window_days: int = 520
    n_components: int = 3
    use_correlation: bool = False
    pca_input: str = "levels"

    # Z-score
    zscore_lookback_days: int = 520

    # OU estimation (via arbitragelab)
    ou_window_days: int = 520
    investment_horizon_pct: float = 0.875  # 87.5% = ln(8)/mu

    # Carry/roll-down
    carry_horizon: str = "1M"

    # Trade filtering
    min_zscore_entry: float = 1.5
    min_profit_cost_ratio: float = 2.0
    round_trip_cost_bps: float = 0.5
    max_adf_pvalue: float = 0.05

    # Butterfly tenor categories
    fly_tenor_categories: Dict[str, List[Tuple[str, str, str]]] = field(
        default_factory=lambda: {
            "front_end": [("2Y", "3Y", "5Y"), ("2Y", "3Y", "4Y")],
            "belly": [
                ("3Y", "5Y", "7Y"), ("3Y", "5Y", "10Y"),
                ("5Y", "7Y", "10Y"),
            ],
            "long_end": [
                ("5Y", "10Y", "15Y"), ("7Y", "10Y", "20Y"),
                ("10Y", "20Y", "30Y"),
            ],
        }
    )


# ═══════════════════════════════════════════════════════════════════
# Data Loading Helpers
# ═══════════════════════════════════════════════════════════════════

def build_rate_queries(config: PCARVScannerConfig) -> List:
    """Build IRSwapQuery objects for the full forward surface.

    Returns a flat list of IRSwapQuery for spot + forward-starting
    rates across all tenors, plus carry and roll-down queries.
    """
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapValue import IRSwapValue

    queries = []
    for fwd in config.forward_starts:
        for tenor in config.tenors:
            t = f"{fwd}x{tenor}" if fwd else tenor
            queries.append(
                IRSwapQuery(curve=config.curve, tenor=t, value=IRSwapValue.RATE)
            )
    return queries


def build_carry_roll_queries(config: PCARVScannerConfig) -> List:
    """Build carry and roll-down queries for the full surface."""
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapValue import IRSwapValue

    queries = []
    for fwd in config.forward_starts:
        for tenor in config.tenors:
            t = f"{fwd}x{tenor}" if fwd else tenor
            queries.append(
                IRSwapQuery(curve=config.curve, tenor=t, value=IRSwapValue.CARRY_BPS_RUNNING)
            )
            queries.append(
                IRSwapQuery(curve=config.curve, tenor=t, value=IRSwapValue.ROLL_BPS_RUNNING)
            )
    return queries


def _tenor_key(fwd: Optional[str], tenor: str) -> str:
    """Build the column key matching TimeseriesBuilder output."""
    return f"{fwd}x{tenor}" if fwd else tenor


def reshape_rates_panel(
    df: pd.DataFrame,
    config: PCARVScannerConfig,
) -> Dict[Optional[str], pd.DataFrame]:
    """Reshape flat TimeseriesBuilder DataFrame into per-forward-start panels.

    Returns dict mapping forward_start -> DataFrame[dates x tenors].
    """
    panels = {}
    for fwd in config.forward_starts:
        cols = {}
        for tenor in config.tenors:
            key = _tenor_key(fwd, tenor)
            # Match column by tenor substring (TimeseriesBuilder column names
            # include curve and value info)
            matches = [c for c in df.columns if key in c and "RATE" in c.upper()]
            if matches:
                cols[tenor] = df[matches[0]]
        if cols:
            panels[fwd] = pd.DataFrame(cols, index=df.index)
    return panels


# ═══════════════════════════════════════════════════════════════════
# Stage 1: Full-Curve PCA Surface Scan
# ═══════════════════════════════════════════════════════════════════

@dataclass
class SurfaceScanResult:
    """Output of Stage 1 full-curve PCA scan."""
    zscore_surface: Dict[Optional[str], pd.DataFrame]
    residuals: Dict[Optional[str], pd.DataFrame]
    variance_explained: Dict[Optional[str], pd.DataFrame]
    loadings: Dict[Optional[str], Dict[pd.Timestamp, np.ndarray]]
    reconstructed: Dict[Optional[str], pd.DataFrame]


def _rolling_pca_surface(
    rates: pd.DataFrame,
    config: PCARVScannerConfig,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, Dict[pd.Timestamp, np.ndarray], pd.DataFrame]:
    """Rolling PCA on a single forward curve.

    Returns (residuals, zscores, variance_explained, loadings_dict, reconstructed).
    """
    n_dates = len(rates)
    tenors = rates.columns.tolist()
    n_tenors = len(tenors)
    window = config.pca_window_days
    n_comp = min(config.n_components, n_tenors)

    residuals = pd.DataFrame(np.nan, index=rates.index, columns=tenors)
    reconstructed = pd.DataFrame(np.nan, index=rates.index, columns=tenors)
    var_exp = pd.DataFrame(np.nan, index=rates.index, columns=[f"PC{i+1}" for i in range(n_comp)])
    loadings_dict: Dict[pd.Timestamp, np.ndarray] = {}

    for i in range(window, n_dates):
        train = rates.iloc[i - window : i]
        if train.isna().any().any():
            continue

        if config.pca_input == "changes":
            train_data = train.diff().iloc[1:]
        else:
            train_data = train

        if config.use_correlation:
            std = train_data.std()
            std = std.replace(0, 1)
            train_data = train_data / std
        else:
            std = None

        pca = PCA(n_components=n_comp)
        pca.fit(train_data.values)
        components = pca.components_  # (n_comp, n_tenors)

        # Store loadings (transpose: n_tenors x n_comp)
        loadings_dict[rates.index[i]] = components.T.copy()
        var_exp.iloc[i] = pca.explained_variance_ratio_[:n_comp]

        # Out-of-sample reconstruction for date i
        actual = rates.iloc[i].values
        if config.pca_input == "changes":
            # For changes mode, reconstruct the change and add to previous level
            prev = rates.iloc[i - 1].values
            change = actual - prev
            if std is not None:
                change = change / std.values
            scores = change @ components.T
            recon_change = scores @ components
            if std is not None:
                recon_change = recon_change * std.values
            recon = prev + recon_change
        else:
            mean = train_data.mean().values
            centered = actual - mean
            if std is not None:
                centered = centered / std.values
            scores = centered @ components.T
            recon_centered = scores @ components
            if std is not None:
                recon_centered = recon_centered * std.values
            recon = mean + recon_centered

        reconstructed.iloc[i] = recon
        residuals.iloc[i] = actual - recon

    # Z-score the residuals
    zs_window = config.zscore_lookback_days
    zscores = pd.DataFrame(np.nan, index=rates.index, columns=tenors)
    for i in range(window + zs_window, n_dates):
        lookback = residuals.iloc[i - zs_window : i]
        mu = lookback.mean()
        sigma = lookback.std()
        sigma = sigma.replace(0, np.nan)
        zscores.iloc[i] = (residuals.iloc[i] - mu) / sigma

    return residuals, zscores, var_exp, loadings_dict, reconstructed


def scan_forward_surface(
    panels: Dict[Optional[str], pd.DataFrame],
    config: PCARVScannerConfig,
) -> SurfaceScanResult:
    """Stage 1: Run PCA scan across the full forward surface.

    Parameters
    ----------
    panels : dict mapping forward_start -> DataFrame[dates x tenors]
        Rate panels for each forward curve. Key None = spot.
    config : PCARVScannerConfig

    Returns
    -------
    SurfaceScanResult with Z-scores, residuals, loadings per forward curve.
    """
    zs_surface: Dict[Optional[str], pd.DataFrame] = {}
    res_surface: Dict[Optional[str], pd.DataFrame] = {}
    ve_surface: Dict[Optional[str], pd.DataFrame] = {}
    ld_surface: Dict[Optional[str], Dict[pd.Timestamp, np.ndarray]] = {}
    rc_surface: Dict[Optional[str], pd.DataFrame] = {}

    for fwd, rates in panels.items():
        if rates.dropna(how="all").empty:
            logger.warning("Empty panel for forward_start=%s, skipping", fwd)
            continue
        residuals, zscores, var_exp, loadings, reconstructed = _rolling_pca_surface(rates, config)
        zs_surface[fwd] = zscores
        res_surface[fwd] = residuals
        ve_surface[fwd] = var_exp
        ld_surface[fwd] = loadings
        rc_surface[fwd] = reconstructed

    return SurfaceScanResult(
        zscore_surface=zs_surface,
        residuals=res_surface,
        variance_explained=ve_surface,
        loadings=ld_surface,
        reconstructed=rc_surface,
    )


def zscore_snapshot(
    result: SurfaceScanResult,
    date: Optional[pd.Timestamp] = None,
) -> pd.DataFrame:
    """Pivot the Z-score surface into SC Figure 12 format.

    Returns DataFrame with rows=tenors, columns=forward starts.
    """
    rows = {}
    for fwd, zs_df in result.zscore_surface.items():
        if date is None:
            # Use last non-NaN date
            valid = zs_df.dropna(how="all")
            if valid.empty:
                continue
            row = valid.iloc[-1]
        else:
            if date not in zs_df.index:
                continue
            row = zs_df.loc[date]
        col_name = "Spot" if fwd is None else fwd
        rows[col_name] = row

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


# ═══════════════════════════════════════════════════════════════════
# Stage 2: Trade-Specific PCA Weighting + Candidate Identification
# ═══════════════════════════════════════════════════════════════════

@dataclass
class FlyCandidate:
    """A candidate butterfly trade identified by the scanner."""
    forward_start: Optional[str]
    tenors: Tuple[str, str, str]  # (left, belly, right)
    weights: Tuple[float, float, float]  # PCA-normalized (w_left, 1.0, w_right)
    direction: str  # "receive_belly" or "pay_belly"
    zscore_belly: float
    zscore_left: float
    zscore_right: float
    neutrality_check: Tuple[float, float]  # (PC1 residual, PC2 residual)


def compute_fly_weights(
    rates_3tenor: pd.DataFrame,
    config: PCARVScannerConfig,
    as_of_idx: Optional[int] = None,
) -> Tuple[Tuple[float, float, float], np.ndarray, Tuple[float, float]]:
    """Stage 2: Compute PCA-weighted butterfly from 3 tenors.

    Parameters
    ----------
    rates_3tenor : DataFrame with exactly 3 columns (left, belly, right).
    config : PCARVScannerConfig
    as_of_idx : If provided, use data up to this index for estimation.
                If None, use trailing pca_window_days from the end.

    Returns
    -------
    (weights, eigenvectors, neutrality_check)
    - weights: (w_left, 1.0, w_right) normalized to belly
    - eigenvectors: (3 x 3) matrix, columns are PC1/PC2/PC3
    - neutrality_check: (pc1_exposure, pc2_exposure) — should be ~0
    """
    if as_of_idx is None:
        train = rates_3tenor.iloc[-config.pca_window_days:]
    else:
        start = max(0, as_of_idx - config.pca_window_days)
        train = rates_3tenor.iloc[start:as_of_idx]

    if config.pca_input == "changes":
        train = train.diff().iloc[1:]

    train = train.dropna()
    if len(train) < 10:
        raise ValueError(f"Insufficient data for PCA: {len(train)} rows")

    pca = PCA(n_components=3)
    pca.fit(train.values)
    # eigenvectors: columns of components_.T → (3 tenors x 3 PCs)
    eigvecs = pca.components_.T  # shape (3, 3)

    # PC3 loadings
    pc3 = eigvecs[:, 2]  # [left, belly, right]
    belly_loading = pc3[1]
    if abs(belly_loading) < 1e-12:
        raise ValueError("Belly PC3 loading is near zero — cannot normalize")

    w_left = float(pc3[0] / belly_loading)
    w_right = float(pc3[2] / belly_loading)
    weights = (w_left, 1.0, w_right)

    # Verify neutrality
    pc1_exposure = float(eigvecs[0, 0] * w_left + eigvecs[1, 0] * 1.0 + eigvecs[2, 0] * w_right)
    pc2_exposure = float(eigvecs[0, 1] * w_left + eigvecs[1, 1] * 1.0 + eigvecs[2, 1] * w_right)
    neutrality = (pc1_exposure, pc2_exposure)

    if abs(pc1_exposure) > 1e-6 or abs(pc2_exposure) > 1e-6:
        logger.warning(
            "Neutrality check: PC1=%.6f, PC2=%.6f (expected ~0)",
            pc1_exposure, pc2_exposure,
        )

    return weights, eigvecs, neutrality


def identify_candidates(
    scan_result: SurfaceScanResult,
    panels: Dict[Optional[str], pd.DataFrame],
    config: PCARVScannerConfig,
    date: Optional[pd.Timestamp] = None,
) -> List[FlyCandidate]:
    """Identify butterfly candidates from the Z-score surface.

    For each forward curve x fly category, check for the butterfly pattern:
    belly cheap + wings rich → receive belly, or belly rich + wings cheap → pay belly.
    """
    candidates = []
    for fwd, zs_df in scan_result.zscore_surface.items():
        if date is None:
            valid = zs_df.dropna(how="all")
            if valid.empty:
                continue
            snap = valid.iloc[-1]
            snap_date = valid.index[-1]
        else:
            if date not in zs_df.index:
                continue
            snap = zs_df.loc[date]
            snap_date = date

        rates_panel = panels.get(fwd)
        if rates_panel is None:
            continue

        for cat_name, fly_list in config.fly_tenor_categories.items():
            for left_t, belly_t, right_t in fly_list:
                if belly_t not in snap.index or left_t not in snap.index or right_t not in snap.index:
                    continue

                z_belly = snap[belly_t]
                z_left = snap[left_t]
                z_right = snap[right_t]

                if pd.isna(z_belly) or pd.isna(z_left) or pd.isna(z_right):
                    continue

                # Butterfly pattern detection
                # Belly cheap (positive Z) + wings rich (negative Z) → receive belly
                # Belly rich (negative Z) + wings cheap (positive Z) → pay belly
                belly_cheap = z_belly > config.min_zscore_entry
                belly_rich = z_belly < -config.min_zscore_entry
                wings_rich = (z_left < 0) and (z_right < 0)
                wings_cheap = (z_left > 0) and (z_right > 0)

                if belly_cheap and wings_rich:
                    direction = "receive_belly"
                elif belly_rich and wings_cheap:
                    direction = "pay_belly"
                else:
                    continue

                # Compute PCA weights on the 3 tenors
                cols = [left_t, belly_t, right_t]
                if not all(c in rates_panel.columns for c in cols):
                    continue
                rates_3 = rates_panel[cols]
                snap_idx = rates_panel.index.get_loc(snap_date)

                try:
                    weights, eigvecs, neutrality = compute_fly_weights(
                        rates_3, config, as_of_idx=snap_idx,
                    )
                except (ValueError, np.linalg.LinAlgError) as exc:
                    logger.debug("Skipping %s/%s/%s: %s", left_t, belly_t, right_t, exc)
                    continue

                candidates.append(FlyCandidate(
                    forward_start=fwd,
                    tenors=(left_t, belly_t, right_t),
                    weights=weights,
                    direction=direction,
                    zscore_belly=float(z_belly),
                    zscore_left=float(z_left),
                    zscore_right=float(z_right),
                    neutrality_check=neutrality,
                ))

    return candidates


# ═══════════════════════════════════════════════════════════════════
# Stage 3: OU Analytics + Stage 4: Carry/Roll-Down
# ═══════════════════════════════════════════════════════════════════

@dataclass
class AnalyzedTrade:
    """Fully analyzed PCA butterfly trade."""
    candidate: FlyCandidate
    fly_series: pd.Series
    ou_speed: float          # mu
    ou_mean: float           # theta
    ou_vol: float            # sigma
    half_life_days: float
    investment_horizon_days: float
    current_level: float
    target_level: float
    stop_loss_level: float
    lifetime_zscore: float
    adf_pvalue: float
    carry_bps: float
    roll_bps: float
    carry_roll_bps: float
    expected_profit_bps: float
    profit_cost_ratio: float
    passes_filter: bool


def _build_fly_series(
    candidate: FlyCandidate,
    rates_panel: pd.DataFrame,
) -> pd.Series:
    """Compute PCA-weighted fly level time series."""
    left_t, belly_t, right_t = candidate.tenors
    w_left, _, w_right = candidate.weights
    return (
        w_left * rates_panel[left_t]
        + 1.0 * rates_panel[belly_t]
        + w_right * rates_panel[right_t]
    )


def _fit_ou(fly_series: pd.Series) -> Dict[str, float]:
    """Fit Ornstein-Uhlenbeck model via arbitragelab.

    Returns dict with keys: mu, theta, sigma, half_life, adf_pvalue.
    """
    clean = fly_series.dropna()
    if len(clean) < 30:
        raise ValueError(f"Insufficient data for OU fit: {len(clean)} points")

    try:
        from arbitragelab.optimal_mean_reversion.ou_model import OrnsteinUhlenbeck

        ou = OrnsteinUhlenbeck()
        ou.fit(clean, data_frequency="D")
        theta, mu, sigma_sq, _ = ou.optimal_coefficients(clean)
        half_life = ou.half_life()
        sigma = float(np.sqrt(max(sigma_sq, 0)))
    except Exception as exc:
        logger.warning("arbitragelab OU fit failed, falling back: %s", exc)
        # Fallback: simple AR(1)
        y = clean.values
        dy = np.diff(y)
        x = y[:-1]
        if len(x) < 2:
            raise
        beta = np.polyfit(x, dy, 1)
        mu = float(-beta[0])
        if mu <= 0:
            mu = 1e-6
        theta = float(-beta[1] / beta[0]) if abs(beta[0]) > 1e-12 else float(clean.mean())
        residuals = dy - (beta[0] * x + beta[1])
        sigma = float(np.std(residuals) * np.sqrt(2 * mu))
        half_life = float(np.log(2) / mu)

    # ADF test
    try:
        from arbitragelab.stochastic_control_approach.ou_model_jurek import OUModelJurek

        jurek = OUModelJurek()
        jurek.fit(clean, delta_t=1 / 252, adf_test=True)
        desc = jurek.describe()
        adf_pvalue = float(desc.get("ADF p-value", 1.0))
    except Exception:
        from statsmodels.tsa.stattools import adfuller
        adf_result = adfuller(clean.values, maxlag=1, regression="c")
        adf_pvalue = float(adf_result[1])

    return {
        "mu": float(mu),
        "theta": float(theta),
        "sigma": sigma,
        "half_life": float(half_life),
        "adf_pvalue": adf_pvalue,
    }


def analyze_candidates(
    candidates: List[FlyCandidate],
    panels: Dict[Optional[str], pd.DataFrame],
    config: PCARVScannerConfig,
    carry_roll_panels: Optional[Dict[Optional[str], pd.DataFrame]] = None,
) -> List[AnalyzedTrade]:
    """Stage 3+4: OU analytics, carry/roll-down, and trade filtering.

    Parameters
    ----------
    candidates : output of identify_candidates()
    panels : rate panels (same as passed to scan_forward_surface)
    config : PCARVScannerConfig
    carry_roll_panels : optional dict of carry+roll DataFrames per forward start.
        Columns should match tenor names with "_carry" and "_roll" suffixes,
        or be a separate dict with "carry" and "roll" sub-dicts.
    """
    trades = []
    for cand in candidates:
        rates_panel = panels.get(cand.forward_start)
        if rates_panel is None:
            continue

        fly = _build_fly_series(cand, rates_panel)
        # Use trailing ou_window for estimation
        fly_est = fly.iloc[-config.ou_window_days:]

        try:
            ou = _fit_ou(fly_est)
        except (ValueError, Exception) as exc:
            logger.debug("OU fit failed for %s: %s", cand.tenors, exc)
            continue

        mu = ou["mu"]
        theta = ou["theta"]
        sigma = ou["sigma"]
        half_life = ou["half_life"]
        adf_pvalue = ou["adf_pvalue"]

        # Investment horizon: ln(8) / mu (87.5% life)
        inv_horizon = float(np.log(8) / mu) if mu > 0 else 999.0

        current = float(fly.iloc[-1])
        target = theta
        dist = abs(current - target)

        # Stop-loss: half the target distance, adverse direction
        if current > target:
            stop_loss = current + 0.5 * dist
        else:
            stop_loss = current - 0.5 * dist

        # Lifetime Z-score
        stationary_std = sigma / np.sqrt(2 * mu) if mu > 0 else 1.0
        lifetime_z = (current - theta) / stationary_std if stationary_std > 0 else 0.0

        # Carry and roll-down (default to 0 if not provided)
        carry_bps = 0.0
        roll_bps = 0.0
        if carry_roll_panels is not None:
            cr_panel = carry_roll_panels.get(cand.forward_start)
            if cr_panel is not None:
                left_t, belly_t, right_t = cand.tenors
                w_left, _, w_right = cand.weights
                for tenor, weight in [(left_t, w_left), (belly_t, 1.0), (right_t, w_right)]:
                    carry_col = [c for c in cr_panel.columns if tenor in c and "CARRY" in c.upper()]
                    roll_col = [c for c in cr_panel.columns if tenor in c and "ROLL" in c.upper()]
                    if carry_col:
                        carry_bps += weight * float(cr_panel[carry_col[0]].iloc[-1])
                    if roll_col:
                        roll_bps += weight * float(cr_panel[roll_col[0]].iloc[-1])

        carry_roll_bps = carry_bps + roll_bps

        # Profitability filter
        expected_profit = dist * 10000  # convert to bps
        round_trip = config.round_trip_cost_bps * 3  # 3 legs
        profit_cost = expected_profit / round_trip if round_trip > 0 else float("inf")

        passes = (
            profit_cost >= config.min_profit_cost_ratio
            and adf_pvalue <= config.max_adf_pvalue
        )

        trades.append(AnalyzedTrade(
            candidate=cand,
            fly_series=fly,
            ou_speed=mu,
            ou_mean=theta,
            ou_vol=sigma,
            half_life_days=half_life,
            investment_horizon_days=inv_horizon,
            current_level=current,
            target_level=target,
            stop_loss_level=stop_loss,
            lifetime_zscore=lifetime_z,
            adf_pvalue=adf_pvalue,
            carry_bps=carry_bps,
            roll_bps=roll_bps,
            carry_roll_bps=carry_roll_bps,
            expected_profit_bps=expected_profit,
            profit_cost_ratio=profit_cost,
            passes_filter=passes,
        ))

    return trades


# ═══════════════════════════════════════════════════════════════════
# Rolling Signal Table Builder
# ═══════════════════════════════════════════════════════════════════

def build_signal_table(
    panels: Dict[Optional[str], pd.DataFrame],
    config: PCARVScannerConfig,
    carry_roll_panels: Optional[Dict[Optional[str], pd.DataFrame]] = None,
    start_date: Optional[pd.Timestamp] = None,
    end_date: Optional[pd.Timestamp] = None,
) -> Dict[pd.Timestamp, List[AnalyzedTrade]]:
    """Build a date-indexed signal table by running the scanner rolling.

    For each date in the panel (after warm-up), runs the full pipeline:
    scan → identify → analyze. Returns a dict mapping each date to its
    list of AnalyzedTrade objects.

    This is the pre-computation step before the backtest — the scanner
    runs once over the full history, and triggers do simple lookups.
    """
    # Get the date index from any panel
    any_panel = next(iter(panels.values()))
    dates = any_panel.index

    warmup = config.pca_window_days + config.zscore_lookback_days

    # Normalize timezone awareness for comparison
    if start_date is not None:
        if dates.tz is None and start_date.tzinfo is not None:
            start_date = start_date.tz_localize(None)
        dates = dates[dates >= start_date]
    if end_date is not None:
        if dates.tz is None and end_date.tzinfo is not None:
            end_date = end_date.tz_localize(None)
        dates = dates[dates <= end_date]

    # Run full surface scan once (it's already rolling internally)
    scan_result = scan_forward_surface(panels, config)

    signal_table: Dict[pd.Timestamp, List[AnalyzedTrade]] = {}

    for dt in dates:
        idx_pos = any_panel.index.get_loc(dt)
        if idx_pos < warmup:
            continue

        # Identify candidates at this date
        candidates = identify_candidates(scan_result, panels, config, date=dt)
        if not candidates:
            continue

        # Build truncated panels up to this date for OU estimation
        panels_to_date = {
            fwd: p.iloc[: idx_pos + 1]
            for fwd, p in panels.items()
        }
        cr_to_date = None
        if carry_roll_panels is not None:
            cr_to_date = {
                fwd: p.iloc[: idx_pos + 1]
                for fwd, p in carry_roll_panels.items()
            }

        trades = analyze_candidates(candidates, panels_to_date, config, cr_to_date)
        if trades:
            signal_table[dt] = trades

    return signal_table
