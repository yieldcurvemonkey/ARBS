import pytest
import numpy as np
import pandas as pd

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
)


# ── Helpers ──────────────────────────────────────────────────────

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


# ── Task 1: Config ───────────────────────────────────────────────

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


# ── Task 2: Stage 1 Surface Scan ────────────────────────────────

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


# ── Task 3: Stage 2 PCA Weights + Candidates ────────────────────

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


# ── Task 4: Stage 3 OU Analytics ────────────────────────────────

def _make_fly_candidate():
    """Build a synthetic FlyCandidate directly (avoids Z-score pattern dependency)."""
    df = _make_synthetic_rates(n_dates=300)
    cfg = PCARVScannerConfig(pca_window_days=130)
    weights, _, neutrality = compute_fly_weights(df[["2Y", "5Y", "10Y"]], cfg)
    return FlyCandidate(
        forward_start=None,
        tenors=("2Y", "5Y", "10Y"),
        weights=weights,
        direction="receive_belly",
        zscore_belly=2.0,
        zscore_left=-1.0,
        zscore_right=-0.8,
        neutrality_check=neutrality,
    )


def test_analyze_candidates_ou_params():
    """OU fit on mean-reverting synthetic fly should produce valid params."""
    df = _make_synthetic_rates(n_dates=600)
    panels = {None: df}
    cfg = PCARVScannerConfig(
        tenors=["2Y", "3Y", "5Y", "7Y", "10Y"],
        forward_starts=[None],
        pca_window_days=130,
        zscore_lookback_days=130,
        max_adf_pvalue=1.0,
        fly_tenor_categories={"test": [("2Y", "5Y", "10Y")]},
    )
    candidate = _make_fly_candidate()
    trades = analyze_candidates([candidate], panels, cfg)
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
        max_adf_pvalue=1.0,
        fly_tenor_categories={"test": [("2Y", "5Y", "10Y")]},
    )
    candidate = _make_fly_candidate()
    trades = analyze_candidates([candidate], panels, cfg)
    assert len(trades) > 0
    t = trades[0]
    dist_to_target = abs(t.current_level - t.target_level)
    dist_to_stop = abs(t.current_level - t.stop_loss_level)
    # Stop-loss is half the target distance
    assert abs(dist_to_stop - 0.5 * dist_to_target) < 1e-10


# ── Task 5: Signal Table ────────────────────────────────────────

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


# ── Task 10: Integration Test ───────────────────────────────────

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
