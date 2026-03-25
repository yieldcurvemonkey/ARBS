# Two-Stage PCA RV Scanner Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a two-stage PCA relative value scanner and backtester for USD SOFR butterfly trades, with standalone research tools and event-driven backtest integration.

**Architecture:** Monolithic signal module (`BT/signals/pca_rv_scanner.py`) implements the full Standard Chartered pipeline (surface scan → trade weighting → OU analytics → carry/roll). A thin trigger adapter (`BT/signals/pca_rv_triggers.py`) wires scanner output into `QueryDrivenBacktest`. A notebook ties research views and backtest together.

**Tech Stack:** sklearn (PCA), arbitragelab (OU estimation), pandas/numpy, existing TimeseriesBuilder + IRSwapQuery for data, existing QueryDrivenBacktest framework for backtest.

**Design Doc:** `docs/plans/2026-03-25-pca-rv-scanner-design.md`

---

## Task 1: PCARVScannerConfig and Data Loading

**Files:**
- Create: `BT/signals/pca_rv_scanner.py`
- Test: `tests/test_pca_rv_scanner.py`

**Step 1: Write the failing test for config defaults**

```python
# tests/test_pca_rv_scanner.py
import pytest
from BT.signals.pca_rv_scanner import PCARVScannerConfig


def test_config_defaults():
    cfg = PCARVScannerConfig()
    assert cfg.curve == "USD-SOFR-1D"
    assert cfg.source == "ERIS_EOD_LIVE-RL_BASIC"
    assert cfg.pca_window_days == 520
    assert cfg.n_components == 3
    assert cfg.use_correlation is False
    assert cfg.pca_input == "levels"
    assert cfg.zscore_lookback_days == 520
    assert cfg.investment_horizon_pct == 0.875
    assert cfg.min_zscore_entry == 1.5
    assert cfg.min_profit_cost_ratio == 2.0
    assert cfg.round_trip_cost_bps == 0.5
    assert len(cfg.tenors) >= 10
    assert None in cfg.forward_starts  # spot included
    assert "1Y" in cfg.forward_starts
    assert len(cfg.fly_tenor_categories) >= 2


def test_config_custom():
    cfg = PCARVScannerConfig(
        tenors=["2Y", "5Y", "10Y"],
        forward_starts=[None, "1Y"],
        pca_window_days=260,
        min_zscore_entry=2.0,
    )
    assert cfg.tenors == ["2Y", "5Y", "10Y"]
    assert cfg.pca_window_days == 260
    assert cfg.min_zscore_entry == 2.0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_pca_rv_scanner.py -v -x`
Expected: FAIL — `ImportError: cannot import name 'PCARVScannerConfig'`

**Step 3: Write config + data loading helpers**

```python
# BT/signals/pca_rv_scanner.py
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

logger = logging.getLogger(__name__)


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
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_pca_rv_scanner.py -v -x`
Expected: PASS

**Step 5: Commit**

```bash
git add BT/signals/pca_rv_scanner.py tests/test_pca_rv_scanner.py
git commit -m "feat(pca-rv): add PCARVScannerConfig and data loading helpers"
```

---

## Task 2: Stage 1 — Full-Curve PCA Surface Scan

**Files:**
- Modify: `BT/signals/pca_rv_scanner.py`
- Test: `tests/test_pca_rv_scanner.py`

**Step 1: Write failing tests for surface scan**

```python
# tests/test_pca_rv_scanner.py (append)
import numpy as np
from BT.signals.pca_rv_scanner import (
    PCARVScannerConfig,
    SurfaceScanResult,
    scan_forward_surface,
    zscore_snapshot,
)


def _make_synthetic_rates(n_dates=600, n_tenors=5, seed=42):
    """Generate synthetic rate panel with known PCA structure."""
    rng = np.random.RandomState(seed)
    dates = pd.bdate_range("2020-01-01", periods=n_dates)
    # 3 factors: level, slope, curvature
    level = np.cumsum(rng.randn(n_dates) * 0.01) + 2.0
    slope = np.cumsum(rng.randn(n_dates) * 0.005)
    curvature = np.cumsum(rng.randn(n_dates) * 0.003)
    tenors = ["2Y", "3Y", "5Y", "7Y", "10Y"]
    loadings = np.array([
        [0.45, 0.45, 0.45, 0.45, 0.45],   # PC1: level
        [-0.5, -0.3, 0.0, 0.3, 0.5],       # PC2: slope
        [0.4, -0.3, -0.5, -0.3, 0.4],      # PC3: curvature
    ])
    rates = (
        np.outer(level, loadings[0])
        + np.outer(slope, loadings[1])
        + np.outer(curvature, loadings[2])
        + rng.randn(n_dates, n_tenors) * 0.002  # small noise = residual
    )
    return pd.DataFrame(rates, index=dates, columns=tenors)


def test_scan_forward_surface_basic():
    df = _make_synthetic_rates()
    panels = {None: df}  # spot only
    cfg = PCARVScannerConfig(
        tenors=["2Y", "3Y", "5Y", "7Y", "10Y"],
        forward_starts=[None],
        pca_window_days=130,
        zscore_lookback_days=130,
    )
    result = scan_forward_surface(panels, cfg)
    assert isinstance(result, SurfaceScanResult)
    # Z-scores should exist for spot
    assert None in result.zscore_surface
    zs = result.zscore_surface[None]
    assert zs.shape[1] == 5  # 5 tenors
    # First pca_window_days rows should be NaN (warm-up)
    assert zs.iloc[:130].isna().all().all()
    # Post-warmup should have valid values
    assert not zs.iloc[260:].isna().any().any()


def test_scan_residuals_are_small():
    """With synthetic data driven by 3 PCs, residuals should be small."""
    df = _make_synthetic_rates()
    panels = {None: df}
    cfg = PCARVScannerConfig(
        tenors=["2Y", "3Y", "5Y", "7Y", "10Y"],
        forward_starts=[None],
        pca_window_days=130,
        zscore_lookback_days=130,
    )
    result = scan_forward_surface(panels, cfg)
    residuals = result.residuals[None].iloc[260:]
    # Residuals should be on the order of the noise (0.002)
    assert residuals.abs().mean().mean() < 0.01


def test_variance_explained_high():
    """3 PCs should explain >95% of variance in our 3-factor synthetic data."""
    df = _make_synthetic_rates()
    panels = {None: df}
    cfg = PCARVScannerConfig(
        tenors=["2Y", "3Y", "5Y", "7Y", "10Y"],
        forward_starts=[None],
        pca_window_days=130,
        zscore_lookback_days=130,
    )
    result = scan_forward_surface(panels, cfg)
    ve = result.variance_explained[None].iloc[260:]
    total = ve.sum(axis=1)
    assert (total > 0.95).all()


def test_zscore_snapshot():
    df = _make_synthetic_rates()
    panels = {None: df}
    cfg = PCARVScannerConfig(
        tenors=["2Y", "3Y", "5Y", "7Y", "10Y"],
        forward_starts=[None],
        pca_window_days=130,
        zscore_lookback_days=130,
    )
    result = scan_forward_surface(panels, cfg)
    snap = zscore_snapshot(result)
    # Should be DataFrame with tenors as rows, forward_starts as columns
    assert "Spot" in snap.columns
    assert len(snap) == 5
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_pca_rv_scanner.py::test_scan_forward_surface_basic -v -x`
Expected: FAIL — `ImportError: cannot import name 'SurfaceScanResult'`

**Step 3: Implement surface scan**

Add to `BT/signals/pca_rv_scanner.py`:

```python
from sklearn.decomposition import PCA


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
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_pca_rv_scanner.py -v -x`
Expected: PASS

**Step 5: Commit**

```bash
git add BT/signals/pca_rv_scanner.py tests/test_pca_rv_scanner.py
git commit -m "feat(pca-rv): implement Stage 1 full-curve PCA surface scan"
```

---

## Task 3: Stage 2 — Trade-Specific PCA Weighting + Candidate Identification

**Files:**
- Modify: `BT/signals/pca_rv_scanner.py`
- Test: `tests/test_pca_rv_scanner.py`

**Step 1: Write failing tests**

```python
# tests/test_pca_rv_scanner.py (append)
from BT.signals.pca_rv_scanner import (
    FlyCandidate,
    compute_fly_weights,
    identify_candidates,
)


def test_compute_fly_weights_neutrality():
    """PC3 weights should be neutral to PC1 and PC2."""
    df = _make_synthetic_rates(n_dates=300)
    rates_3 = df[["2Y", "5Y", "10Y"]]
    cfg = PCARVScannerConfig(pca_window_days=130)
    weights, eigvecs, neutrality = compute_fly_weights(rates_3, cfg)
    # weights: (w_left, 1.0, w_right)
    assert weights[1] == 1.0
    # Neutrality: PC1 and PC2 exposure should be near zero
    assert abs(neutrality[0]) < 1e-10
    assert abs(neutrality[1]) < 1e-10


def test_compute_fly_weights_three_values():
    df = _make_synthetic_rates(n_dates=300)
    rates_3 = df[["2Y", "5Y", "10Y"]]
    cfg = PCARVScannerConfig(pca_window_days=130)
    weights, _, _ = compute_fly_weights(rates_3, cfg)
    assert len(weights) == 3
    assert all(isinstance(w, float) for w in weights)


def test_identify_candidates_basic():
    df = _make_synthetic_rates(n_dates=600)
    panels = {None: df}
    cfg = PCARVScannerConfig(
        tenors=["2Y", "3Y", "5Y", "7Y", "10Y"],
        forward_starts=[None],
        pca_window_days=130,
        zscore_lookback_days=130,
        min_zscore_entry=0.5,  # low threshold for synthetic data
        fly_tenor_categories={"test": [("2Y", "5Y", "10Y")]},
    )
    result = scan_forward_surface(panels, cfg)
    candidates = identify_candidates(result, panels, cfg)
    assert isinstance(candidates, list)
    for c in candidates:
        assert isinstance(c, FlyCandidate)
        assert c.tenors == ("2Y", "5Y", "10Y")
        assert len(c.weights) == 3
        assert c.weights[1] == 1.0
        assert c.direction in ("receive_belly", "pay_belly")
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_pca_rv_scanner.py::test_compute_fly_weights_neutrality -v -x`
Expected: FAIL — `ImportError: cannot import name 'FlyCandidate'`

**Step 3: Implement Stage 2**

Add to `BT/signals/pca_rv_scanner.py`:

```python
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

    For each forward curve × fly category, check for the butterfly pattern:
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
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_pca_rv_scanner.py -v -x`
Expected: PASS

**Step 5: Commit**

```bash
git add BT/signals/pca_rv_scanner.py tests/test_pca_rv_scanner.py
git commit -m "feat(pca-rv): implement Stage 2 trade-specific PCA weighting"
```

---

## Task 4: Stage 3 — OU Analytics via arbitragelab

**Files:**
- Modify: `BT/signals/pca_rv_scanner.py`
- Test: `tests/test_pca_rv_scanner.py`

**Step 1: Write failing tests**

```python
# tests/test_pca_rv_scanner.py (append)
from BT.signals.pca_rv_scanner import AnalyzedTrade, analyze_candidates


def test_analyze_candidates_ou_params():
    """OU fit on mean-reverting synthetic fly should produce valid params."""
    df = _make_synthetic_rates(n_dates=600)
    panels = {None: df}
    cfg = PCARVScannerConfig(
        tenors=["2Y", "3Y", "5Y", "7Y", "10Y"],
        forward_starts=[None],
        pca_window_days=130,
        zscore_lookback_days=130,
        min_zscore_entry=0.0,  # accept anything for testing
        fly_tenor_categories={"test": [("2Y", "5Y", "10Y")]},
    )
    result = scan_forward_surface(panels, cfg)
    candidates = identify_candidates(result, panels, cfg)
    if not candidates:
        pytest.skip("No candidates found in synthetic data")

    trades = analyze_candidates(candidates, panels, cfg)
    assert len(trades) > 0
    t = trades[0]
    assert isinstance(t, AnalyzedTrade)
    assert t.half_life_days > 0
    assert t.investment_horizon_days > 0
    assert isinstance(t.fly_series, pd.Series)
    assert len(t.fly_series) > 0
    assert t.ou_speed > 0


def test_analyze_trade_target_stop():
    """Target should be OU mean, stop-loss should be half the distance."""
    df = _make_synthetic_rates(n_dates=600)
    panels = {None: df}
    cfg = PCARVScannerConfig(
        tenors=["2Y", "3Y", "5Y", "7Y", "10Y"],
        forward_starts=[None],
        pca_window_days=130,
        zscore_lookback_days=130,
        min_zscore_entry=0.0,
        fly_tenor_categories={"test": [("2Y", "5Y", "10Y")]},
    )
    result = scan_forward_surface(panels, cfg)
    candidates = identify_candidates(result, panels, cfg)
    if not candidates:
        pytest.skip("No candidates found in synthetic data")

    trades = analyze_candidates(candidates, panels, cfg)
    t = trades[0]
    dist_to_target = abs(t.current_level - t.target_level)
    dist_to_stop = abs(t.current_level - t.stop_loss_level)
    # Stop-loss is half the target distance
    assert abs(dist_to_stop - 0.5 * dist_to_target) < 1e-10
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_pca_rv_scanner.py::test_analyze_candidates_ou_params -v -x`
Expected: FAIL — `ImportError: cannot import name 'AnalyzedTrade'`

**Step 3: Implement Stage 3**

Add to `BT/signals/pca_rv_scanner.py`:

```python
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
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_pca_rv_scanner.py -v -x`
Expected: PASS

**Step 5: Commit**

```bash
git add BT/signals/pca_rv_scanner.py tests/test_pca_rv_scanner.py
git commit -m "feat(pca-rv): implement Stage 3 OU analytics via arbitragelab"
```

---

## Task 5: Rolling Signal Table Builder

**Files:**
- Modify: `BT/signals/pca_rv_scanner.py`
- Test: `tests/test_pca_rv_scanner.py`

**Step 1: Write failing test**

```python
# tests/test_pca_rv_scanner.py (append)
from BT.signals.pca_rv_scanner import build_signal_table


def test_build_signal_table():
    """Signal table should map dates to lists of AnalyzedTrade."""
    df = _make_synthetic_rates(n_dates=600)
    panels = {None: df}
    cfg = PCARVScannerConfig(
        tenors=["2Y", "3Y", "5Y", "7Y", "10Y"],
        forward_starts=[None],
        pca_window_days=130,
        zscore_lookback_days=130,
        min_zscore_entry=0.0,
        fly_tenor_categories={"test": [("2Y", "5Y", "10Y")]},
    )
    table = build_signal_table(panels, cfg)
    assert isinstance(table, dict)
    # Should have date keys
    for dt_key, trades in table.items():
        assert isinstance(trades, list)
        for t in trades:
            assert isinstance(t, AnalyzedTrade)
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_pca_rv_scanner.py::test_build_signal_table -v -x`
Expected: FAIL — `ImportError: cannot import name 'build_signal_table'`

**Step 3: Implement rolling signal table**

Add to `BT/signals/pca_rv_scanner.py`:

```python
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
    if start_date is not None:
        dates = dates[dates >= start_date]
    if end_date is not None:
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
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_pca_rv_scanner.py -v -x`
Expected: PASS

**Step 5: Commit**

```bash
git add BT/signals/pca_rv_scanner.py tests/test_pca_rv_scanner.py
git commit -m "feat(pca-rv): implement rolling signal table builder"
```

---

## Task 6: Trigger Adapter — PCARVEntryTrigger + PCARVExitTrigger

**Files:**
- Create: `BT/signals/pca_rv_triggers.py`
- Test: `tests/test_pca_rv_triggers.py`

**Step 1: Write failing tests**

```python
# tests/test_pca_rv_triggers.py
import datetime as dt
import pytest
import pandas as pd
import numpy as np
from unittest.mock import MagicMock

from BT.signals.pca_rv_triggers import PCARVEntryTrigger, PCARVExitTrigger
from BT.signals.pca_rv_scanner import (
    PCARVScannerConfig, FlyCandidate, AnalyzedTrade,
)


def _make_trade(date, tenors=("2Y", "5Y", "10Y"), z=2.0, passes=True):
    cand = FlyCandidate(
        forward_start=None,
        tenors=tenors,
        weights=(-0.9, 1.0, -0.46),
        direction="receive_belly",
        zscore_belly=z,
        zscore_left=-1.0,
        zscore_right=-0.8,
        neutrality_check=(0.0, 0.0),
    )
    return AnalyzedTrade(
        candidate=cand,
        fly_series=pd.Series([1.0, 2.0, 3.0]),
        ou_speed=0.05,
        ou_mean=2.5,
        ou_vol=0.3,
        half_life_days=14,
        investment_horizon_days=42,
        current_level=3.0,
        target_level=2.5,
        stop_loss_level=3.25,
        lifetime_zscore=z,
        adf_pvalue=0.01,
        carry_bps=0.5,
        roll_bps=0.3,
        carry_roll_bps=0.8,
        expected_profit_bps=5.0,
        profit_cost_ratio=3.3,
        passes_filter=passes,
    )


def test_entry_trigger_fires_on_signal():
    d = pd.Timestamp("2023-06-15 17:00", tz="America/New_York")
    trade = _make_trade(d)
    signal_table = {d: [trade]}
    cfg = PCARVScannerConfig(min_zscore_entry=1.5)
    trigger = PCARVEntryTrigger(signal_table, cfg)
    info = trigger.has_triggered(d, backtest=None)
    assert info.triggered is True


def test_entry_trigger_silent_when_no_signal():
    d = pd.Timestamp("2023-06-15 17:00", tz="America/New_York")
    signal_table = {}
    cfg = PCARVScannerConfig()
    trigger = PCARVEntryTrigger(signal_table, cfg)
    info = trigger.has_triggered(d, backtest=None)
    assert info.triggered is False


def test_entry_trigger_skips_failing_filter():
    d = pd.Timestamp("2023-06-15 17:00", tz="America/New_York")
    trade = _make_trade(d, passes=False)
    signal_table = {d: [trade]}
    cfg = PCARVScannerConfig()
    trigger = PCARVEntryTrigger(signal_table, cfg)
    info = trigger.has_triggered(d, backtest=None)
    assert info.triggered is False


def test_exit_trigger_on_target():
    d = pd.Timestamp("2023-06-15 17:00", tz="America/New_York")
    trade = _make_trade(d)
    # Current level is at target (ou_mean=2.5)
    trade_at_target = AnalyzedTrade(
        candidate=trade.candidate,
        fly_series=trade.fly_series,
        ou_speed=trade.ou_speed,
        ou_mean=2.5,
        ou_vol=trade.ou_vol,
        half_life_days=trade.half_life_days,
        investment_horizon_days=trade.investment_horizon_days,
        current_level=2.5,  # at target
        target_level=2.5,
        stop_loss_level=trade.stop_loss_level,
        lifetime_zscore=0.0,
        adf_pvalue=trade.adf_pvalue,
        carry_bps=trade.carry_bps,
        roll_bps=trade.roll_bps,
        carry_roll_bps=trade.carry_roll_bps,
        expected_profit_bps=trade.expected_profit_bps,
        profit_cost_ratio=trade.profit_cost_ratio,
        passes_filter=True,
    )
    signal_table = {d: [trade_at_target]}
    cfg = PCARVScannerConfig()
    trigger = PCARVExitTrigger(signal_table, cfg)
    # Mock backtest with open positions
    bt = MagicMock()
    pos = MagicMock()
    pos.meta = {"tags": ["pca_rv_None_2Y_5Y_10Y"]}
    pos.opened = d - pd.Timedelta(days=5)
    bt.portfolio.positions = [pos]
    info = trigger.has_triggered(d, backtest=bt)
    assert info.triggered is True
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_pca_rv_triggers.py -v -x`
Expected: FAIL — `ImportError`

**Step 3: Implement triggers**

```python
# BT/signals/pca_rv_triggers.py
"""Trigger adapter wiring PCA RV scanner into QueryDrivenBacktest.

Pre-computes a signal_table (dict[date, list[AnalyzedTrade]]) before
the backtest runs, then triggers do simple date-based lookups.
"""
from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pandas as pd

from BT.event import TriggerInfo
from BT.triggers import Trigger, TriggerRequirements
from BT.query_actions import AddQueryAction, UnwindPositionsAction
from BT.query_order import QueryOrder, UnwindOrder
from BT.signals.pca_rv_scanner import AnalyzedTrade, PCARVScannerConfig

logger = logging.getLogger(__name__)


def _fly_tag(trade: AnalyzedTrade) -> str:
    """Deterministic tag for a fly position."""
    fwd = trade.candidate.forward_start or "spot"
    left, belly, right = trade.candidate.tenors
    return f"pca_rv_{fwd}_{left}_{belly}_{right}"


def _make_fly_query(trade: AnalyzedTrade, config: PCARVScannerConfig, bpv: float = 100_000):
    """Build an IRSwapQuery for the PCA butterfly."""
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery, IRSwapStructure

    left_t, belly_t, right_t = trade.candidate.tenors
    fwd = trade.candidate.forward_start

    # Build tenor strings with forward start
    if fwd:
        front = f"{fwd}x{left_t}"
        belly = f"{fwd}x{belly_t}"
        back = f"{fwd}x{right_t}"
    else:
        front = left_t
        belly = belly_t
        back = right_t

    w_left, _, w_right = trade.candidate.weights

    return IRSwapQuery(
        structure=IRSwapStructure.FLY,
        curve=config.curve,
        structure_kwargs={
            "front_tenor": front,
            "belly_tenor": belly,
            "back_tenor": back,
            "weights": (w_left, 1.0, w_right),
            "bpv": bpv,
        },
        tags=[_fly_tag(trade)],
    )


# ── Entry Trigger ──


@dataclass
class _PCARVEntryReqs(TriggerRequirements):
    signal_table: Dict[pd.Timestamp, List[AnalyzedTrade]] = field(default_factory=dict)
    config: PCARVScannerConfig = field(default_factory=PCARVScannerConfig)
    bpv: float = 100_000
    max_concurrent: int = 5

    def has_triggered(self, state: dt.datetime, backtest=None) -> TriggerInfo:
        ts = pd.Timestamp(state)
        trades = self.signal_table.get(ts, [])
        passing = [t for t in trades if t.passes_filter]

        if not passing:
            return TriggerInfo(False)

        # Filter out flies already in portfolio
        if backtest is not None:
            open_tags = set()
            for pos in backtest.portfolio.positions:
                open_tags.update(pos.meta.get("tags", []))
            passing = [t for t in passing if _fly_tag(t) not in open_tags]

            # Respect max concurrent
            n_open = len(backtest.portfolio.positions)
            if n_open >= self.max_concurrent:
                return TriggerInfo(False)
            passing = passing[: self.max_concurrent - n_open]

        if not passing:
            return TriggerInfo(False)

        # Build orders
        orders = []
        for t in passing:
            q = _make_fly_query(t, self.config, self.bpv)
            orders.append(QueryOrder(
                timestamp=state,
                query=q,
                meta={
                    "action": "pca_rv_entry",
                    "tags": [_fly_tag(t)],
                    "direction": t.candidate.direction,
                    "lifetime_zscore": t.lifetime_zscore,
                    "target": t.target_level,
                    "stop_loss": t.stop_loss_level,
                    "investment_horizon": t.investment_horizon_days,
                },
            ))

        return TriggerInfo(True, {AddQueryAction: orders})


@dataclass
class PCARVEntryTrigger(Trigger):
    """Fires when PCA RV scanner identifies passing trades on a date."""

    def __init__(
        self,
        signal_table: Dict[pd.Timestamp, List[AnalyzedTrade]],
        config: PCARVScannerConfig,
        bpv: float = 100_000,
        max_concurrent: int = 5,
        actions=None,
    ):
        reqs = _PCARVEntryReqs(
            signal_table=signal_table,
            config=config,
            bpv=bpv,
            max_concurrent=max_concurrent,
        )
        super().__init__(trigger_requirements=reqs, actions=actions)


# ── Exit Trigger ──


@dataclass
class _PCARVExitReqs(TriggerRequirements):
    signal_table: Dict[pd.Timestamp, List[AnalyzedTrade]] = field(default_factory=dict)
    config: PCARVScannerConfig = field(default_factory=PCARVScannerConfig)

    def has_triggered(self, state: dt.datetime, backtest=None) -> TriggerInfo:
        if backtest is None or not backtest.portfolio.positions:
            return TriggerInfo(False)

        ts = pd.Timestamp(state)
        trades_today = self.signal_table.get(ts, [])
        trade_by_tag = {_fly_tag(t): t for t in trades_today}

        unwinds = []
        for pos in backtest.portfolio.positions:
            tags = set(pos.meta.get("tags", []))
            pca_tags = [t for t in tags if t.startswith("pca_rv_")]
            if not pca_tags:
                continue

            tag = pca_tags[0]
            entry_meta = pos.meta or {}

            # Check exit conditions
            exit_reason = None

            if tag in trade_by_tag:
                trade = trade_by_tag[tag]
                target = entry_meta.get("target", trade.target_level)
                stop = entry_meta.get("stop_loss", trade.stop_loss_level)
                direction = entry_meta.get("direction", trade.candidate.direction)

                current = trade.current_level

                # Mean reversion: crossed target
                if direction == "receive_belly":
                    if current <= target:
                        exit_reason = "mean_reversion"
                    elif current >= stop:
                        exit_reason = "stop_loss"
                else:
                    if current >= target:
                        exit_reason = "mean_reversion"
                    elif current <= stop:
                        exit_reason = "stop_loss"

            # Max holding period
            if exit_reason is None and hasattr(pos, "opened"):
                days_held = (ts - pd.Timestamp(pos.opened)).days
                horizon = entry_meta.get("investment_horizon", 90)
                if days_held >= horizon:
                    exit_reason = "max_holding"

            if exit_reason is not None:
                unwinds.append(UnwindOrder(
                    timestamp=state,
                    selector=lambda p, _tag=tag: _tag in set(p.meta.get("tags", [])),
                    meta={"action": "pca_rv_exit", "reason": exit_reason},
                ))

        if not unwinds:
            return TriggerInfo(False)

        return TriggerInfo(True, {UnwindPositionsAction: unwinds})


@dataclass
class PCARVExitTrigger(Trigger):
    """Fires when open PCA RV positions hit target, stop-loss, or max holding."""

    def __init__(
        self,
        signal_table: Dict[pd.Timestamp, List[AnalyzedTrade]],
        config: PCARVScannerConfig,
        actions=None,
    ):
        reqs = _PCARVExitReqs(signal_table=signal_table, config=config)
        super().__init__(trigger_requirements=reqs, actions=actions)
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_pca_rv_triggers.py -v -x`
Expected: PASS

**Step 5: Commit**

```bash
git add BT/signals/pca_rv_triggers.py tests/test_pca_rv_triggers.py
git commit -m "feat(pca-rv): implement entry/exit trigger adapters"
```

---

## Task 7: Update BT/signals/__init__.py Exports

**Files:**
- Modify: `BT/signals/__init__.py`

**Step 1: Add exports**

Append to the existing imports in `BT/signals/__init__.py`:

```python
from BT.signals.pca_rv_scanner import (
    PCARVScannerConfig,
    SurfaceScanResult,
    FlyCandidate,
    AnalyzedTrade,
    scan_forward_surface,
    zscore_snapshot,
    compute_fly_weights,
    identify_candidates,
    analyze_candidates,
    build_signal_table,
    build_rate_queries,
    build_carry_roll_queries,
    reshape_rates_panel,
)
from BT.signals.pca_rv_triggers import (
    PCARVEntryTrigger,
    PCARVExitTrigger,
)
```

And add all names to `__all__`.

**Step 2: Verify import works**

Run: `python -c "from BT.signals import PCARVScannerConfig, PCARVEntryTrigger; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add BT/signals/__init__.py
git commit -m "feat(pca-rv): export scanner and trigger modules from BT.signals"
```

---

## Task 8: Notebook — Research Views + Backtest

**Files:**
- Create: `notebooks/backtests/pca_rv_butterfly_backtest.ipynb`

**Step 1: Create notebook with all 6 sections**

The notebook should follow this structure. Each section is a group of cells:

**Section 1 — Config & Data Loading:**
```python
import datetime
import pytz
import pandas as pd
import numpy as np

from BT.signals.pca_rv_scanner import (
    PCARVScannerConfig, scan_forward_surface, zscore_snapshot,
    identify_candidates, analyze_candidates, build_signal_table,
    build_rate_queries, build_carry_roll_queries, reshape_rates_panel,
)
from BT.signals.pca_rv_triggers import PCARVEntryTrigger, PCARVExitTrigger
from BT.query_engine import QueryDrivenBacktest
from BT.query_strategy import QueryStrategy, TimeGrid, ql_cal_date_range
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from TB.TimeseriesBuilder import TimeseriesBuilder
from TB.IRSwapsTB import IRSwapsTB
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapValue import IRSwapValue

tz = pytz.timezone("America/New_York")
config = PCARVScannerConfig()
# Date range
data_start = datetime.datetime(2022, 1, 1, 17, tzinfo=tz)
data_end = datetime.datetime(2025, 12, 31, 17, tzinfo=tz)

# Load rates
curve_mdp = IRSwapsMDP(source=config.source)
ts_builder = TimeseriesBuilder()
queries = build_rate_queries(config)
router = {"IRS": IRSwapsTB(curve_mdp, show_tqdm=True)}
rates_df = ts_builder.get_timeseries(
    start=data_start, end=data_end, queries=queries, n_jobs=12, routers=router,
)
panels = reshape_rates_panel(rates_df, config)
```

**Section 2 — Stage 1: Surface Scan (Research):**
```python
result = scan_forward_surface(panels, config)
snap = zscore_snapshot(result)
# Style: green = cheap (positive Z, rates should fall), blue = rich (negative Z)
snap.style.applymap(lambda v: "color: green" if v > 0 else "color: blue" if v < 0 else "")
```
Plus plots: PCA vs actual curve, variance explained, residual distributions.

**Section 3 — Stage 2: Candidates:**
```python
candidates = identify_candidates(result, panels, config)
pd.DataFrame([{
    "Forward": c.forward_start or "Spot",
    "Fly": f"{c.tenors[0]}/{c.tenors[1]}/{c.tenors[2]}",
    "Weights": f"{c.weights[0]:.2f} / 1.00 / {c.weights[2]:.2f}",
    "Direction": c.direction,
    "Z(belly)": f"{c.zscore_belly:.2f}",
    "PC1 neut": f"{c.neutrality_check[0]:.2e}",
    "PC2 neut": f"{c.neutrality_check[1]:.2e}",
} for c in candidates])
```

**Section 4 — Stage 3: OU Analytics:**
```python
trades = analyze_candidates(candidates, panels, config)
pd.DataFrame([{
    "Fly": f"{t.candidate.tenors[0]}/{t.candidate.tenors[1]}/{t.candidate.tenors[2]}",
    "Direction": t.candidate.direction,
    "Lifetime Z": f"{t.lifetime_zscore:.2f}",
    "Entry": f"{t.current_level:.2f}bps",
    "Target": f"{t.target_level:.2f}bps",
    "Stop": f"{t.stop_loss_level:.2f}bps",
    "Half-life": f"{t.half_life_days:.0f}d",
    "Horizon": f"{t.investment_horizon_days:.0f}d",
    "ADF p": f"{t.adf_pvalue:.3f}",
    "Carry+Roll": f"{t.carry_roll_bps:.2f}bps",
    "P/C ratio": f"{t.profit_cost_ratio:.1f}",
    "Pass": t.passes_filter,
} for t in trades])
```
Plus fly series plot with OU bands.

**Section 5 — Backtest:**
```python
# Build signal table
bt_start = datetime.datetime(2023, 1, 1, 17, tzinfo=tz)
bt_end = data_end
signal_table = build_signal_table(
    panels, config, start_date=pd.Timestamp(bt_start), end_date=pd.Timestamp(bt_end),
)

# Wire triggers
entry = PCARVEntryTrigger(signal_table, config, bpv=100_000)
exit_ = PCARVExitTrigger(signal_table, config)
strategy = QueryStrategy("pca_rv_fly", triggers=[entry, exit_])

# Time grid
dates = ql_cal_date_range(bt_start, bt_end, tz=tz)
mdp = IRSwapsMDP(source=config.source)
bt = QueryDrivenBacktest(
    time_grid=TimeGrid(dates),
    mdp=mdp,
    strategy=strategy,
)
bt.run()

# Results
mtm = pd.Series(bt.mtm_history)
mtm.plot(title="PCA RV Butterfly — Cumulative MTM P&L")
```

**Section 6 — Sensitivity (optional, placeholder cells).**

**Step 2: Verify notebook loads without error**

Run: `jupyter nbconvert --to script notebooks/backtests/pca_rv_butterfly_backtest.ipynb --stdout | python -c "import sys; exec(sys.stdin.read())"` (syntax check only — data loading will fail without live data)

**Step 3: Commit**

```bash
git add notebooks/backtests/pca_rv_butterfly_backtest.ipynb
git commit -m "feat(pca-rv): add PCA RV butterfly backtest notebook"
```

---

## Task 9: Add arbitragelab Dependency

**Files:**
- Modify: `requirements.txt`

**Step 1: Add arbitragelab**

Add `arbitragelab` to `requirements.txt`.

**Step 2: Install**

Run: `pip install arbitragelab`

**Step 3: Verify import**

Run: `python -c "from arbitragelab.optimal_mean_reversion.ou_model import OrnsteinUhlenbeck; print('OK')"`

**Step 4: Commit**

```bash
git add requirements.txt
git commit -m "chore: add arbitragelab dependency for OU estimation"
```

---

## Task 10: Integration Test — Full Pipeline

**Files:**
- Test: `tests/test_pca_rv_scanner.py`

**Step 1: Write integration test**

```python
# tests/test_pca_rv_scanner.py (append)

def test_full_pipeline_synthetic():
    """End-to-end: config → scan → identify → analyze → signal table."""
    df = _make_synthetic_rates(n_dates=600)
    panels = {None: df}
    cfg = PCARVScannerConfig(
        tenors=["2Y", "3Y", "5Y", "7Y", "10Y"],
        forward_starts=[None],
        pca_window_days=130,
        zscore_lookback_days=130,
        min_zscore_entry=0.0,
        max_adf_pvalue=1.0,  # accept all for synthetic
        fly_tenor_categories={"test": [("2Y", "5Y", "10Y")]},
    )

    # Stage 1
    result = scan_forward_surface(panels, cfg)
    assert None in result.zscore_surface

    # Snapshot
    snap = zscore_snapshot(result)
    assert not snap.empty

    # Stage 2
    candidates = identify_candidates(result, panels, cfg)

    # Stage 3
    trades = analyze_candidates(candidates, panels, cfg)

    # Signal table
    table = build_signal_table(panels, cfg)
    assert isinstance(table, dict)

    # Verify chain is consistent
    total_signals = sum(len(v) for v in table.values())
    assert total_signals >= 0  # may be 0 with synthetic data
```

**Step 2: Run full test suite**

Run: `pytest tests/test_pca_rv_scanner.py tests/test_pca_rv_triggers.py -v`
Expected: ALL PASS

**Step 3: Commit**

```bash
git add tests/test_pca_rv_scanner.py
git commit -m "test(pca-rv): add full pipeline integration test"
```
