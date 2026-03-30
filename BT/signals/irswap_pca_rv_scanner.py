"""IRSwap PCA relative-value scanner for swap curves.

Implements a practitioner-grade PCA RV workflow:
  Stage 1: Full-curve PCA scan → residuals → Z-score surface
  Stage 2: Trade-specific PCA on 3 selected tenors → level+slope-neutral weights
  Stage 3: OU mean-reversion analytics (via in-house arbitragelab fork)
  Stage 4: Carry/roll-down integration and trade filtering

Supports three curve input modes:
  - "spot"             : PCA on spot par swap tenors
  - "forward_stanchart": PCA on spot + separate forward curves (Standard Chartered)
  - "forward_cs"       : PCA on non-overlapping forward rates (Credit Suisse)

References:
  - Standard Chartered "Introducing a relative-value tool for swaps" (Aug 2013)
  - Credit Suisse "PCA Unleashed" (Oct 2012)
  - ASM Quant Macro "PCA ~ Part II" (Jun 2015)
  - Musaelian, Nagarajan, Villani "PCA: invariant risk metrics" (SSRN 2777026)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════

# Default tenor grids for each mode
DEFAULT_SPOT_TENORS = [
    "1Y", "2Y", "3Y", "4Y", "5Y", "6Y", "7Y", "8Y", "9Y",
    "10Y", "15Y", "20Y", "25Y", "30Y",
]

DEFAULT_FORWARD_STARTS = [
    None, "1M", "3M", "6M", "1Y", "2Y", "5Y", "7Y", "10Y",
]

# Credit Suisse non-overlapping forwards
DEFAULT_CS_FORWARD_TENORS = [
    "1Y",       # spot 1y
    "1Yx1Y",    # 1y1y
    "2Yx1Y",    # 2y1y
    "3Yx1Y",    # 3y1y
    "4Yx1Y",    # 4y1y
    "5Yx1Y",    # 5y1y
    "6Yx1Y",    # 6y1y
    "7Yx1Y",    # 7y1y
    "8Yx1Y",    # 8y1y
    "9Yx1Y",    # 9y1y
    "10Yx2Y",   # 10y2y
    "12Yx3Y",   # 12y3y
    "15Yx5Y",   # 15y5y
    "20Yx5Y",   # 20y5y
    "25Yx5Y",   # 25y5y
    "30Yx10Y",  # 30y10y
]

# Default butterfly universe (when auto_scan_fly is False)
DEFAULT_FLY_UNIVERSE: List[Tuple[str, str, str]] = [
    # Front end
    ("2Y", "3Y", "5Y"),
    ("2Y", "3Y", "4Y"),
    ("3Y", "4Y", "5Y"),
    # Belly
    ("3Y", "5Y", "7Y"),
    ("3Y", "5Y", "10Y"),
    ("5Y", "7Y", "10Y"),
    ("4Y", "5Y", "6Y"),
    ("5Y", "6Y", "7Y"),
    # Long end
    ("5Y", "10Y", "15Y"),
    ("5Y", "10Y", "20Y"),
    ("7Y", "10Y", "20Y"),
    ("7Y", "10Y", "30Y"),
    ("10Y", "15Y", "20Y"),
    ("10Y", "20Y", "30Y"),
    ("15Y", "20Y", "30Y"),
]


@dataclass
class IRSwapPCARVConfig:
    """Configuration for the IRSwap PCA RV scanner.

    All parameters have sensible defaults. Adjust for research velocity.
    """

    # ── Curve identity ───────────────────────────────────────────
    curve: str = "USD-SOFR-1D"
    source: str = "ERIS_EOD_LIVE-RL_BASIC"

    # ── Curve input mode ─────────────────────────────────────────
    curve_input_mode: str = "spot"
    # "spot"              → PCA on spot par swap tenors
    # "forward_stanchart" → PCA on spot + separate forward curves
    # "forward_cs"        → PCA on non-overlapping forward rates

    # ── Tenor grids ──────────────────────────────────────────────
    spot_tenors: List[str] = field(
        default_factory=lambda: list(DEFAULT_SPOT_TENORS)
    )
    forward_starts: List[Optional[str]] = field(
        default_factory=lambda: list(DEFAULT_FORWARD_STARTS)
    )
    cs_forward_tenors: List[str] = field(
        default_factory=lambda: list(DEFAULT_CS_FORWARD_TENORS)
    )

    # ── PCA parameters ───────────────────────────────────────────
    pca_window_days: int = 520          # ~2 years of business days
    pca_input: str = "levels"           # "levels" or "changes"
    n_components: int = 3
    # NOTE: use_correlation is intentionally NOT configurable.
    # Per textbook: always use covariance, never correlation.

    # ── Z-score (decoupled from PCA window) ──────────────────────
    zscore_lookback_days: int = 260     # ~1 year — shorter than PCA window

    # ── OU estimation ────────────────────────────────────────────
    ou_window_days: int = 520
    ou_discount_rate: float = 0.0
    ou_transaction_cost: float = 0.0
    investment_horizon_pct: float = 0.875  # 87.5% = 3 half-lives

    # ── Trade filtering ──────────────────────────────────────────
    min_zscore_belly: float = 1.5       # Belly must exceed this
    min_zscore_wing: float = 0.5        # Each wing must exceed this (magnitude)
    min_profit_cost_ratio: float = 2.0
    round_trip_cost_bps: float = 0.5    # Per leg, one way
    max_adf_pvalue: float = 0.10
    min_half_life_days: float = 3.0     # Reject implausibly fast
    max_half_life_days: float = 120.0   # Reject too-slow reversion

    # ── Fly universe ─────────────────────────────────────────────
    fly_universe: Optional[List[Tuple[str, str, str]]] = None
    auto_scan_fly: bool = True
    # When auto_scan_fly=True AND fly_universe is None → algorithmic scan
    # When auto_scan_fly=True AND fly_universe is set  → scan only those combos
    # When auto_scan_fly=False AND fly_universe is set → use exactly those combos

    # ── Carry / roll-down ────────────────────────────────────────
    include_carry_roll: bool = True
    carry_horizon: str = "1M"

    # ── Portfolio constraints ────────────────────────────────────
    max_concurrent_positions: int = 5
    trade_belly_bpv: float = 100_000.0

    def get_fly_universe(self) -> List[Tuple[str, str, str]]:
        """Return the fly universe to scan."""
        if self.fly_universe is not None:
            return self.fly_universe
        return list(DEFAULT_FLY_UNIVERSE)

    def get_tenors_for_mode(self) -> List[str]:
        """Return the tenor list appropriate for the current mode."""
        if self.curve_input_mode == "forward_cs":
            return self.cs_forward_tenors
        return self.spot_tenors


# ═══════════════════════════════════════════════════════════════════
# Data Loading Helpers
# ═══════════════════════════════════════════════════════════════════

def build_rate_queries(config: IRSwapPCARVConfig) -> list:
    """Build IRSwapQuery objects for rates based on curve_input_mode.

    Returns a flat list of IRSwapQuery for the configured mode.
    """
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapValue import IRSwapValue

    queries = []

    if config.curve_input_mode == "spot":
        for tenor in config.spot_tenors:
            queries.append(
                IRSwapQuery(curve=config.curve, tenor=tenor, value=IRSwapValue.RATE)
            )

    elif config.curve_input_mode == "forward_stanchart":
        for fwd in config.forward_starts:
            for tenor in config.spot_tenors:
                t = f"{fwd}x{tenor}" if fwd else tenor
                queries.append(
                    IRSwapQuery(curve=config.curve, tenor=t, value=IRSwapValue.RATE)
                )

    elif config.curve_input_mode == "forward_cs":
        for tenor in config.cs_forward_tenors:
            queries.append(
                IRSwapQuery(curve=config.curve, tenor=tenor, value=IRSwapValue.RATE)
            )

    else:
        raise ValueError(f"Unknown curve_input_mode: {config.curve_input_mode}")

    return queries


def build_carry_roll_queries(config: IRSwapPCARVConfig) -> list:
    """Build carry and roll-down queries matching the rate queries.

    Uses UnifiedQuery for carry/roll to leverage the horizon parameter
    and avoid slow per-curve pricing.
    """
    from Query.Unified.UnifiedQuery import UnifiedQuery
    from Query.Unified.registry import UnifiedValue

    queries = []
    tenors_to_query = []

    if config.curve_input_mode == "spot":
        tenors_to_query = [(None, t) for t in config.spot_tenors]
    elif config.curve_input_mode == "forward_stanchart":
        for fwd in config.forward_starts:
            for tenor in config.spot_tenors:
                tenors_to_query.append((fwd, tenor))
    elif config.curve_input_mode == "forward_cs":
        tenors_to_query = [(None, t) for t in config.cs_forward_tenors]

    for fwd, tenor in tenors_to_query:
        t = f"{fwd}x{tenor}" if fwd else tenor
        queries.append(UnifiedQuery(
            curve=config.curve, tenor=t,
            value=UnifiedValue.IRS_CARRY_BPS_RUNNING,
            structure_kwargs={"horizon": config.carry_horizon},
        ))
        queries.append(UnifiedQuery(
            curve=config.curve, tenor=t,
            value=UnifiedValue.IRS_ROLL_BPS_RUNNING,
            structure_kwargs={"horizon": config.carry_horizon},
        ))
    return queries


def reshape_rates_panel(
    df: pd.DataFrame,
    config: IRSwapPCARVConfig,
) -> Dict[Optional[str], pd.DataFrame]:
    """Reshape flat TimeseriesBuilder DataFrame into per-forward-start panels.

    Returns dict mapping forward_start -> DataFrame[dates x tenors].
    For "spot" and "forward_cs" modes, returns {None: single_panel}.
    For "forward_stanchart", returns {None: spot_panel, "1M": ..., etc.}.
    """
    panels: Dict[Optional[str], pd.DataFrame] = {}

    if config.curve_input_mode == "spot":
        cols = {}
        for tenor in config.spot_tenors:
            matches = [c for c in df.columns if tenor in c and "RATE" in c.upper()]
            if matches:
                cols[tenor] = df[matches[0]]
        if cols:
            panels[None] = pd.DataFrame(cols, index=df.index)

    elif config.curve_input_mode == "forward_stanchart":
        for fwd in config.forward_starts:
            cols = {}
            for tenor in config.spot_tenors:
                key = f"{fwd}x{tenor}" if fwd else tenor
                matches = [c for c in df.columns if key in c and "RATE" in c.upper()]
                if matches:
                    cols[tenor] = df[matches[0]]
            if cols:
                panels[fwd] = pd.DataFrame(cols, index=df.index)

    elif config.curve_input_mode == "forward_cs":
        cols = {}
        for tenor in config.cs_forward_tenors:
            matches = [c for c in df.columns if tenor in c and "RATE" in c.upper()]
            if matches:
                cols[tenor] = df[matches[0]]
        if cols:
            panels[None] = pd.DataFrame(cols, index=df.index)

    return panels


def reshape_carry_roll_panel(
    df: pd.DataFrame,
    config: IRSwapPCARVConfig,
) -> Dict[Optional[str], pd.DataFrame]:
    """Reshape carry/roll-down data into panels matching rate panels.

    Handles column names from both IRSwapQuery and UnifiedQuery formats.
    """
    panels: Dict[Optional[str], pd.DataFrame] = {}

    def _find_col(df_cols, tenor_key, metric):
        """Find column matching tenor and carry/roll metric."""
        metric_upper = metric.upper()
        for c in df_cols:
            c_upper = c.upper()
            if tenor_key.upper() in c_upper and metric_upper in c_upper:
                return c
        return None

    if config.curve_input_mode in ("spot", "forward_cs"):
        tenor_list = config.cs_forward_tenors if config.curve_input_mode == "forward_cs" else config.spot_tenors
        cols = {}
        for tenor in tenor_list:
            carry_col = _find_col(df.columns, tenor, "CARRY")
            roll_col = _find_col(df.columns, tenor, "ROLL")
            if carry_col:
                cols[f"{tenor}_carry"] = df[carry_col]
            if roll_col:
                cols[f"{tenor}_roll"] = df[roll_col]
        if cols:
            panels[None] = pd.DataFrame(cols, index=df.index)

    elif config.curve_input_mode == "forward_stanchart":
        for fwd in config.forward_starts:
            cols = {}
            for tenor in config.spot_tenors:
                key = f"{fwd}x{tenor}" if fwd else tenor
                carry_col = _find_col(df.columns, key, "CARRY")
                roll_col = _find_col(df.columns, key, "ROLL")
                if carry_col:
                    cols[f"{tenor}_carry"] = df[carry_col]
                if roll_col:
                    cols[f"{tenor}_roll"] = df[roll_col]
            if cols:
                panels[fwd] = pd.DataFrame(cols, index=df.index)

    return panels


# ═══════════════════════════════════════════════════════════════════
# Stage 1: Full-Curve PCA Surface Scan
# ═══════════════════════════════════════════════════════════════════

@dataclass
class IRSwapPCASurfaceScan:
    """Output of Stage 1 full-curve PCA scan."""
    zscore_surface: Dict[Optional[str], pd.DataFrame]
    residuals: Dict[Optional[str], pd.DataFrame]
    variance_explained: Dict[Optional[str], pd.DataFrame]
    loadings: Dict[Optional[str], Dict[pd.Timestamp, np.ndarray]]
    reconstructed: Dict[Optional[str], pd.DataFrame]


def _pca_eigen(data: np.ndarray, n_components: int) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """PCA via direct eigendecomposition of the covariance matrix.

    Parameters
    ----------
    data : (n_samples, n_features) array, already centered
    n_components : number of PCs to retain

    Returns
    -------
    eigvecs : (n_features, n_components) — columns are eigenvectors, sorted by eigenvalue desc
    eigvals : (n_components,) — eigenvalues sorted desc
    var_explained : (n_components,) — fraction of variance explained
    """
    cov = np.cov(data, rowvar=False)
    eigvals_all, eigvecs_all = np.linalg.eigh(cov)

    # eigh returns ascending order; reverse to descending
    idx = np.argsort(eigvals_all)[::-1]
    eigvals_all = eigvals_all[idx]
    eigvecs_all = eigvecs_all[:, idx]

    eigvals = eigvals_all[:n_components]
    eigvecs = eigvecs_all[:, :n_components]

    total_var = eigvals_all.sum()
    var_explained = eigvals / total_var if total_var > 0 else np.zeros(n_components)

    return eigvecs, eigvals, var_explained


def _rolling_pca_surface(
    rates: pd.DataFrame,
    config: IRSwapPCARVConfig,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, Dict[pd.Timestamp, np.ndarray], pd.DataFrame]:
    """Rolling PCA on a single curve panel.

    Returns (residuals, zscores, variance_explained, loadings_dict, reconstructed).
    """
    n_dates = len(rates)
    tenors = rates.columns.tolist()
    n_tenors = len(tenors)
    pca_win = config.pca_window_days
    n_comp = min(config.n_components, n_tenors)

    residuals = pd.DataFrame(np.nan, index=rates.index, columns=tenors)
    reconstructed = pd.DataFrame(np.nan, index=rates.index, columns=tenors)
    var_exp = pd.DataFrame(np.nan, index=rates.index, columns=[f"PC{i+1}" for i in range(n_comp)])
    loadings_dict: Dict[pd.Timestamp, np.ndarray] = {}

    for i in range(pca_win, n_dates):
        train = rates.iloc[i - pca_win : i]
        if train.isna().any().any():
            continue

        # Prepare training data
        if config.pca_input == "changes":
            train_data = train.diff().iloc[1:].values
        else:
            train_data = train.values

        # Center the data
        mean_vec = train_data.mean(axis=0)
        centered = train_data - mean_vec

        # Eigendecomposition of covariance
        try:
            eigvecs, eigvals, var_ratio = _pca_eigen(centered, n_comp)
        except np.linalg.LinAlgError:
            continue

        loadings_dict[rates.index[i]] = eigvecs.copy()  # (n_tenors, n_comp)
        var_exp.iloc[i] = var_ratio

        # Out-of-sample reconstruction for date i
        actual = rates.iloc[i].values
        if config.pca_input == "changes":
            prev = rates.iloc[i - 1].values
            change = actual - prev
            # Use the mean of changes from training
            change_centered = change - mean_vec
            scores = change_centered @ eigvecs  # (n_comp,)
            recon_change = scores @ eigvecs.T + mean_vec
            recon = prev + recon_change
        else:
            actual_centered = actual - mean_vec
            scores = actual_centered @ eigvecs
            recon = scores @ eigvecs.T + mean_vec

        reconstructed.iloc[i] = recon
        residuals.iloc[i] = actual - recon

    # Z-score the residuals with DECOUPLED lookback
    zs_win = config.zscore_lookback_days
    zscores = pd.DataFrame(np.nan, index=rates.index, columns=tenors)
    min_start = pca_win + zs_win
    for i in range(min_start, n_dates):
        lookback = residuals.iloc[i - zs_win : i]
        valid_count = lookback.notna().sum()
        mu = lookback.mean()
        sigma = lookback.std()
        sigma = sigma.replace(0, np.nan)
        # Only compute Z-score where we have enough data
        mask = valid_count >= max(30, zs_win // 4)
        current_res = residuals.iloc[i]
        z = (current_res - mu) / sigma
        z[~mask] = np.nan
        zscores.iloc[i] = z

    return residuals, zscores, var_exp, loadings_dict, reconstructed


def scan_surface(
    panels: Dict[Optional[str], pd.DataFrame],
    config: IRSwapPCARVConfig,
) -> IRSwapPCASurfaceScan:
    """Stage 1: Run PCA scan across the curve surface.

    Parameters
    ----------
    panels : dict mapping forward_start -> DataFrame[dates x tenors]
    config : IRSwapPCARVConfig

    Returns
    -------
    IRSwapPCASurfaceScan with Z-scores, residuals, loadings per curve.
    """
    zs: Dict[Optional[str], pd.DataFrame] = {}
    res: Dict[Optional[str], pd.DataFrame] = {}
    ve: Dict[Optional[str], pd.DataFrame] = {}
    ld: Dict[Optional[str], Dict[pd.Timestamp, np.ndarray]] = {}
    rc: Dict[Optional[str], pd.DataFrame] = {}

    for fwd, rates in panels.items():
        if rates.dropna(how="all").empty:
            logger.warning("Empty panel for forward_start=%s, skipping", fwd)
            continue
        residuals, zscores, var_exp, loadings, reconstructed = _rolling_pca_surface(rates, config)
        zs[fwd] = zscores
        res[fwd] = residuals
        ve[fwd] = var_exp
        ld[fwd] = loadings
        rc[fwd] = reconstructed

    return IRSwapPCASurfaceScan(
        zscore_surface=zs, residuals=res,
        variance_explained=ve, loadings=ld, reconstructed=rc,
    )


def zscore_snapshot(
    result: IRSwapPCASurfaceScan,
    date: Optional[pd.Timestamp] = None,
) -> pd.DataFrame:
    """Pivot the Z-score surface into SC Figure 12 format.

    Returns DataFrame with rows=tenors, columns=forward starts.
    """
    rows = {}
    for fwd, zs_df in result.zscore_surface.items():
        if date is None:
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
class IRSwapFlyCandidate:
    """A candidate butterfly trade identified by the scanner."""
    forward_start: Optional[str]
    tenors: Tuple[str, str, str]          # (left, belly, right)
    weights: Tuple[float, float, float]   # PCA-normalized (w_left, 1.0, w_right)
    direction: str                         # "receive_belly" or "pay_belly"
    zscore_belly: float
    zscore_left: float
    zscore_right: float
    neutrality_check: Tuple[float, float]  # (PC1 residual, PC2 residual)


def compute_fly_weights(
    rates_3tenor: pd.DataFrame,
    config: IRSwapPCARVConfig,
    as_of_idx: Optional[int] = None,
) -> Tuple[Tuple[float, float, float], np.ndarray, Tuple[float, float]]:
    """Stage 2: Compute PCA-weighted butterfly from 3 tenors.

    Parameters
    ----------
    rates_3tenor : DataFrame with exactly 3 columns (left, belly, right).
    config : IRSwapPCARVConfig
    as_of_idx : If provided, use data up to this index for estimation.

    Returns
    -------
    (weights, eigenvectors, neutrality_check)
    - weights: (w_left, 1.0, w_right) normalized to belly=1
    - eigenvectors: (3, 3) matrix, columns are PC1/PC2/PC3
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
    if len(train) < 30:
        raise ValueError(f"Insufficient data for local PCA: {len(train)} rows")

    centered = train.values - train.values.mean(axis=0)
    eigvecs, eigvals, var_ratio = _pca_eigen(centered, 3)

    # PC3 = third eigenvector (curvature)
    pc3 = eigvecs[:, 2]  # [left, belly, right]

    # Ensure butterfly shape: wings same sign, belly opposite
    # If not, this 3-tenor system may not have a butterfly factor
    if np.sign(pc3[0]) == np.sign(pc3[1]) == np.sign(pc3[2]):
        logger.warning("PC3 does not have butterfly shape: %s", pc3)

    belly_loading = pc3[1]
    if abs(belly_loading) < 1e-12:
        raise ValueError("Belly PC3 loading is near zero — cannot normalize")

    # Normalize so belly = 1.0
    w_left = float(pc3[0] / belly_loading)
    w_right = float(pc3[2] / belly_loading)
    weights = (w_left, 1.0, w_right)

    # Verify PC1 and PC2 neutrality
    w_vec = np.array([w_left, 1.0, w_right])
    pc1_exp = float(w_vec @ eigvecs[:, 0])
    pc2_exp = float(w_vec @ eigvecs[:, 1])
    neutrality = (pc1_exp, pc2_exp)

    if abs(pc1_exp) > 1e-4 or abs(pc2_exp) > 1e-4:
        logger.warning(
            "Neutrality check FAILED: PC1=%.6f, PC2=%.6f (tenors=%s)",
            pc1_exp, pc2_exp, rates_3tenor.columns.tolist(),
        )

    return weights, eigvecs, neutrality


def _auto_scan_candidates(
    zscores_snap: pd.Series,
    tenors: List[str],
    config: IRSwapPCARVConfig,
) -> List[Tuple[str, str, str, str]]:
    """Algorithmically scan Z-score snapshot for butterfly patterns.

    Returns list of (left, belly, right, direction) tuples.
    """
    hits = []
    for i, belly_t in enumerate(tenors):
        z_belly = zscores_snap.get(belly_t, np.nan)
        if pd.isna(z_belly):
            continue

        belly_cheap = z_belly > config.min_zscore_belly
        belly_rich = z_belly < -config.min_zscore_belly

        if not (belly_cheap or belly_rich):
            continue

        # Search for wing pairs (any tenor on either side)
        for j in range(i):
            for k in range(i + 1, len(tenors)):
                left_t = tenors[j]
                right_t = tenors[k]
                z_left = zscores_snap.get(left_t, np.nan)
                z_right = zscores_snap.get(right_t, np.nan)

                if pd.isna(z_left) or pd.isna(z_right):
                    continue

                if belly_cheap:
                    # Belly cheap → wings must be rich (negative Z)
                    if z_left < -config.min_zscore_wing and z_right < -config.min_zscore_wing:
                        hits.append((left_t, belly_t, right_t, "receive_belly"))
                elif belly_rich:
                    # Belly rich → wings must be cheap (positive Z)
                    if z_left > config.min_zscore_wing and z_right > config.min_zscore_wing:
                        hits.append((left_t, belly_t, right_t, "pay_belly"))

    return hits


def identify_candidates(
    scan_result: IRSwapPCASurfaceScan,
    panels: Dict[Optional[str], pd.DataFrame],
    config: IRSwapPCARVConfig,
    date: Optional[pd.Timestamp] = None,
) -> List[IRSwapFlyCandidate]:
    """Identify butterfly candidates from the Z-score surface.

    Supports both manual universe and auto-scan modes.
    """
    candidates = []

    for fwd, zs_df in scan_result.zscore_surface.items():
        # Get Z-score snapshot
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

        # Determine fly triplets to evaluate
        if config.auto_scan_fly:
            available_tenors = [t for t in snap.index if not pd.isna(snap[t])]
            triplets = _auto_scan_candidates(snap, available_tenors, config)
        else:
            # Manual universe: check each combo for pattern
            triplets = []
            for left_t, belly_t, right_t in config.get_fly_universe():
                if belly_t not in snap.index or left_t not in snap.index or right_t not in snap.index:
                    continue
                z_belly = snap[belly_t]
                z_left = snap[left_t]
                z_right = snap[right_t]
                if pd.isna(z_belly) or pd.isna(z_left) or pd.isna(z_right):
                    continue

                belly_cheap = z_belly > config.min_zscore_belly
                belly_rich = z_belly < -config.min_zscore_belly
                wings_rich = z_left < -config.min_zscore_wing and z_right < -config.min_zscore_wing
                wings_cheap = z_left > config.min_zscore_wing and z_right > config.min_zscore_wing

                if belly_cheap and wings_rich:
                    triplets.append((left_t, belly_t, right_t, "receive_belly"))
                elif belly_rich and wings_cheap:
                    triplets.append((left_t, belly_t, right_t, "pay_belly"))

        # Compute PCA weights for each triplet
        for left_t, belly_t, right_t, direction in triplets:
            cols = [left_t, belly_t, right_t]
            if not all(c in rates_panel.columns for c in cols):
                continue

            rates_3 = rates_panel[cols]
            try:
                snap_idx = rates_panel.index.get_loc(snap_date)
            except KeyError:
                continue

            try:
                weights, eigvecs, neutrality = compute_fly_weights(
                    rates_3, config, as_of_idx=snap_idx,
                )
            except (ValueError, np.linalg.LinAlgError) as exc:
                logger.debug("Skipping %s/%s/%s: %s", left_t, belly_t, right_t, exc)
                continue

            candidates.append(IRSwapFlyCandidate(
                forward_start=fwd,
                tenors=(left_t, belly_t, right_t),
                weights=weights,
                direction=direction,
                zscore_belly=float(snap[belly_t]),
                zscore_left=float(snap[left_t]),
                zscore_right=float(snap[right_t]),
                neutrality_check=neutrality,
            ))

    return candidates


# ═══════════════════════════════════════════════════════════════════
# Stage 3: OU Analytics
# ═══════════════════════════════════════════════════════════════════

def _build_fly_series(
    candidate: IRSwapFlyCandidate,
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


def _fit_ou(
    fly_series: pd.Series,
    config: IRSwapPCARVConfig,
) -> Dict[str, float]:
    """Fit Ornstein-Uhlenbeck model using the in-house arbitragelab fork.

    Returns dict with keys: mu, theta, sigma, half_life, adf_pvalue.
    """
    clean = fly_series.dropna()
    if len(clean) < 60:
        raise ValueError(f"Insufficient data for OU fit: {len(clean)} points")

    # Scale fly series to bps for numerical stability in OU fitting.
    # The arbitragelab optimizer converges poorly on tiny rate-decimal values
    # (e.g., 0.001 = 10bps). Scaling to bps gives values ~10-100 which the
    # MLE optimizer handles much better.
    BPS_SCALE = 10_000.0
    clean_bps = clean * BPS_SCALE

    theta = np.nan
    mu = np.nan
    sigma = np.nan
    half_life = np.nan

    # Primary: arbitragelab OrnsteinUhlenbeck (fit in bps space)
    try:
        from RVUtils.arbitragelab.arbitragelab.optimal_mean_reversion.ou_model import OrnsteinUhlenbeck

        ou = OrnsteinUhlenbeck()
        ou.fit(
            data=clean_bps.values,
            data_frequency="D",
            discount_rate=config.ou_discount_rate,
            transaction_cost=config.ou_transaction_cost,
        )
        theta_bps, mu_est, sigma_sq_bps, mll = ou.optimal_coefficients(clean_bps.values)
        # Convert theta and sigma back to rate-decimal space
        theta = float(theta_bps) / BPS_SCALE
        mu = float(mu_est)  # annualized speed (dimensionless, same in bps or rate space)
        sigma = float(np.sqrt(max(sigma_sq_bps, 0))) / BPS_SCALE  # back to rate space
        # arbitragelab returns half_life in YEARS — convert to business days
        hl_years = float(ou.half_life()) if mu > 1e-10 else 999.0
        half_life = hl_years * 252  # convert to business days

        # Sanity: reject if half-life in days is implausible
        if half_life < 1.0:
            logger.warning("arbitragelab OU half_life=%.1fd too small (mu_ann=%.4f), using AR(1) fallback", half_life, mu)
            raise ValueError("Implausible half_life from arbitragelab")

    except Exception as exc:
        logger.warning("arbitragelab OU fit failed, using AR(1) fallback: %s", exc)

        # Fallback: AR(1) regression (in bps space for numerical stability)
        y = clean_bps.values
        dy = np.diff(y)
        x = y[:-1]
        if len(x) < 10:
            raise ValueError("Insufficient data for AR(1) fallback")

        # Discrete AR(1): x_{t+1} = a + b*x_t + eps
        # => dx = a + (b-1)*x_t + eps
        # For OU: dx = k*(theta - x)*dt + sigma*dW
        # With dt=1 day: slope = -k_daily, intercept = k_daily * theta
        coeffs = np.polyfit(x, dy, 1)
        slope, intercept = coeffs[0], coeffs[1]

        k_daily = float(-slope)
        if k_daily <= 0:
            k_daily = 1e-6

        theta_bps = float(-intercept / slope) if abs(slope) > 1e-12 else float(clean_bps.mean())
        theta = theta_bps / BPS_SCALE  # back to rate space
        mu = k_daily  # daily speed
        residuals_ar = dy - (slope * x + intercept)
        sigma = float(np.std(residuals_ar)) / BPS_SCALE  # back to rate space, daily
        half_life = float(np.log(2) / k_daily)  # in days

    # ADF test
    try:
        from statsmodels.tsa.stattools import adfuller
        adf_result = adfuller(clean.values, maxlag=int(min(len(clean) // 4, 20)), regression="c")
        adf_pvalue = float(adf_result[1])
    except Exception:
        adf_pvalue = 1.0

    return {
        "mu": mu,
        "theta": theta,
        "sigma": sigma,
        "half_life": half_life,
        "adf_pvalue": adf_pvalue,
    }


# ═══════════════════════════════════════════════════════════════════
# Stage 4: Trade Analytics + Filtering
# ═══════════════════════════════════════════════════════════════════

@dataclass
class IRSwapAnalyzedTrade:
    """Fully analyzed PCA butterfly trade."""
    candidate: IRSwapFlyCandidate
    fly_series: pd.Series
    ou_speed: float
    ou_mean: float
    ou_vol: float
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
    filter_reasons: List[str]


def analyze_candidates(
    candidates: List[IRSwapFlyCandidate],
    panels: Dict[Optional[str], pd.DataFrame],
    config: IRSwapPCARVConfig,
    carry_roll_panels: Optional[Dict[Optional[str], pd.DataFrame]] = None,
) -> List[IRSwapAnalyzedTrade]:
    """Stage 3+4: OU analytics, carry/roll-down, and trade filtering."""
    trades = []

    for cand in candidates:
        rates_panel = panels.get(cand.forward_start)
        if rates_panel is None:
            continue

        fly = _build_fly_series(cand, rates_panel)
        fly_est = fly.iloc[-config.ou_window_days:]

        try:
            ou = _fit_ou(fly_est, config)
        except (ValueError, Exception) as exc:
            logger.debug("OU fit failed for %s: %s", cand.tenors, exc)
            continue

        mu = ou["mu"]
        theta = ou["theta"]
        sigma = ou["sigma"]
        half_life = ou["half_life"]
        adf_pvalue = ou["adf_pvalue"]

        # Investment horizon: 3 half-lives ≈ 87.5% convergence (half_life already in days)
        inv_horizon = half_life * 3.0 if half_life > 0 else 999.0

        current = float(fly.dropna().iloc[-1])
        target = theta
        dist = abs(current - target)

        # Stop-loss: half the target distance, adverse direction
        if current > target:
            stop_loss = current + 0.5 * dist
        else:
            stop_loss = current - 0.5 * dist

        # Lifetime Z-score (using OU stationary distribution)
        # mu from arbitragelab is annualized; sigma is annualized
        # stationary_std = sigma / sqrt(2*mu) when both in same units (annual)
        stationary_std = sigma / np.sqrt(2 * mu) if mu > 0 else 1.0
        if stationary_std <= 0:
            stationary_std = 1.0
        lifetime_z = (current - theta) / stationary_std

        # Carry and roll-down
        carry_bps = 0.0
        roll_bps = 0.0
        if carry_roll_panels is not None:
            cr_panel = carry_roll_panels.get(cand.forward_start)
            if cr_panel is not None:
                left_t, belly_t, right_t = cand.tenors
                w_left, _, w_right = cand.weights
                for tenor, weight in [(left_t, w_left), (belly_t, 1.0), (right_t, w_right)]:
                    carry_col = [c for c in cr_panel.columns if f"{tenor}_carry" in c]
                    roll_col = [c for c in cr_panel.columns if f"{tenor}_roll" in c]
                    if carry_col and not cr_panel[carry_col[0]].dropna().empty:
                        carry_bps += weight * float(cr_panel[carry_col[0]].dropna().iloc[-1])
                    if roll_col and not cr_panel[roll_col[0]].dropna().empty:
                        roll_bps += weight * float(cr_panel[roll_col[0]].dropna().iloc[-1])
        carry_roll_bps = carry_bps + roll_bps

        # Expected profit (in bps, accounting for PCA weights)
        expected_profit_bps = dist * 10000  # convergence in bps

        # Round-trip cost: 3 legs × cost per leg
        round_trip_bps = config.round_trip_cost_bps * 3
        profit_cost = expected_profit_bps / round_trip_bps if round_trip_bps > 0 else float("inf")

        # Filtering with reasons
        filter_reasons = []
        passes = True

        if profit_cost < config.min_profit_cost_ratio:
            filter_reasons.append(f"profit_cost={profit_cost:.1f} < {config.min_profit_cost_ratio}")
            passes = False

        if adf_pvalue > config.max_adf_pvalue:
            filter_reasons.append(f"adf_pvalue={adf_pvalue:.3f} > {config.max_adf_pvalue}")
            passes = False

        if half_life < config.min_half_life_days:
            filter_reasons.append(f"half_life={half_life:.1f}d < {config.min_half_life_days}")
            passes = False

        if half_life > config.max_half_life_days:
            filter_reasons.append(f"half_life={half_life:.1f}d > {config.max_half_life_days}")
            passes = False

        trades.append(IRSwapAnalyzedTrade(
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
            expected_profit_bps=expected_profit_bps,
            profit_cost_ratio=profit_cost,
            passes_filter=passes,
            filter_reasons=filter_reasons,
        ))

    return trades


# ═══════════════════════════════════════════════════════════════════
# Signal Table Builder (pre-computation for backtest)
# ═══════════════════════════════════════════════════════════════════

def build_signal_table(
    panels: Dict[Optional[str], pd.DataFrame],
    config: IRSwapPCARVConfig,
    carry_roll_panels: Optional[Dict[Optional[str], pd.DataFrame]] = None,
    start_date: Optional[pd.Timestamp] = None,
    end_date: Optional[pd.Timestamp] = None,
) -> Dict[pd.Timestamp, List[IRSwapAnalyzedTrade]]:
    """Build a date-indexed signal table by running the scanner rolling.

    For each date (after warm-up), runs: scan → identify → analyze.
    Returns dict mapping each date to its list of IRSwapAnalyzedTrade objects.
    """
    any_panel = next(iter(panels.values()))
    dates = any_panel.index
    warmup = config.pca_window_days + config.zscore_lookback_days

    if start_date is not None:
        start_ts = pd.Timestamp(start_date)
        if start_ts.tzinfo is not None:
            start_ts = start_ts.tz_localize(None)
        # Compare as Timestamps to avoid date vs datetime issues
        dates = dates[pd.Index([pd.Timestamp(d) for d in dates]) >= start_ts]
    if end_date is not None:
        end_ts = pd.Timestamp(end_date)
        if end_ts.tzinfo is not None:
            end_ts = end_ts.tz_localize(None)
        dates = dates[pd.Index([pd.Timestamp(d) for d in dates]) <= end_ts]

    # Run full surface scan once (internally rolling)
    scan_result = scan_surface(panels, config)

    signal_table: Dict[pd.Timestamp, List[IRSwapAnalyzedTrade]] = {}

    for dt in dates:
        idx_pos = any_panel.index.get_loc(dt)
        if idx_pos < warmup:
            continue

        candidates = identify_candidates(scan_result, panels, config, date=dt)
        if not candidates:
            continue

        # Truncate panels to this date for OU estimation
        panels_to_date = {fwd: p.iloc[:idx_pos + 1] for fwd, p in panels.items()}
        cr_to_date = None
        if carry_roll_panels is not None:
            cr_to_date = {fwd: p.iloc[:idx_pos + 1] for fwd, p in carry_roll_panels.items()}

        analyzed = analyze_candidates(candidates, panels_to_date, config, cr_to_date)
        if analyzed:
            signal_table[dt] = analyzed

    return signal_table
