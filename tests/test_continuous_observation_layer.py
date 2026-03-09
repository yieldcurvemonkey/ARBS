"""Tests for the continuous-coordinate observation layer.

Covers:
- Bilinear weight computation (_compute_bilinear_weights)
- Observation operator in conditional_mvn_update (backward compat + off-grid)
- build_observation_operator assembly
- map_observations_to_grid with use_continuous_observations flag
"""

from __future__ import annotations

import datetime as dt
import math

import numpy as np
import pandas as pd
import pytest

from RVUtils.surface_pca_model import (
    SurfacePCAModel,
    conditional_mvn_update,
    fit_surface_pca_from_eod_grids,
)

# ---------------------------------------------------------------------------
# Helpers to build synthetic grid + model
# ---------------------------------------------------------------------------

# Use a small 3x2 grid for clarity in weight tests.
SMALL_EXPIRY_LABELS = ["1m", "1y", "10y"]
SMALL_TENOR_LABELS = ["1y", "10y"]
SMALL_COLUMNS = [
    f"{e}_{t}" for e in SMALL_EXPIRY_LABELS for t in SMALL_TENOR_LABELS
]  # 6 nodes


def _make_small_training_levels() -> pd.DataFrame:
    rng = np.random.default_rng(42)
    base = np.array([72.0, 73.0, 80.0, 81.0, 90.0, 91.0])
    loading_1 = np.array([1.0, 0.9, 0.8, 0.7, 0.5, 0.4])
    loading_2 = np.array([-0.3, 0.2, -0.1, 0.3, -0.2, 0.1])

    levels = [base]
    for _ in range(80):
        f1 = rng.normal(scale=0.8)
        f2 = rng.normal(scale=0.25)
        shock = f1 * loading_1 + f2 * loading_2 + rng.normal(scale=0.05, size=6)
        levels.append(levels[-1] + shock)

    index = pd.bdate_range(dt.date(2025, 8, 1), periods=len(levels))
    return pd.DataFrame(levels, index=index, columns=SMALL_COLUMNS)


def _small_model_and_eod():
    levels = _make_small_training_levels()
    model, _ = fit_surface_pca_from_eod_grids(levels, n_components=2)
    eod = levels.iloc[-1]
    return model, eod


# ---------------------------------------------------------------------------
# Import the grid functions being tested
# ---------------------------------------------------------------------------

from SDRUtils._swappulse_scripts.ingest_and_build_live_atmf_grid import (
    CORE_GRID_NODES,
    GridNode,
    StraddleObservation,
    _compute_bilinear_weights,
    build_observation_operator,
    map_observations_to_grid,
)


# Build small grid nodes for weight tests
SMALL_GRID_NODES = [
    GridNode(
        key=f"{e}_{t}",
        expiry_label=e,
        tenor_label=t,
        expiry_years={
            "1m": 1.0 / 12,
            "1y": 1.0,
            "10y": 10.0,
        }[e],
        tenor_years={
            "1y": 1.0,
            "10y": 10.0,
        }[t],
    )
    for e in SMALL_EXPIRY_LABELS
    for t in SMALL_TENOR_LABELS
]


# ===================================================================
# Tests: _compute_bilinear_weights
# ===================================================================


class TestComputeBilinearWeights:
    """Verify bilinear interpolation weights on the core grid."""

    def test_on_grid_node_returns_single_weight(self):
        """Observation exactly on 1y x 10y should get weight 1.0 on that node."""
        weights = _compute_bilinear_weights(1.0, 10.0, SMALL_GRID_NODES)
        assert len(weights) == 1
        assert "1y_10y" in weights
        assert abs(weights["1y_10y"] - 1.0) < 1e-10

    def test_on_grid_line_expiry_axis(self):
        """Observation at 1y expiry, between 1y and 10y tenor -> 2 weights."""
        # 3y tenor in log-space between 1y and 10y
        tenor = 3.0
        weights = _compute_bilinear_weights(1.0, tenor, SMALL_GRID_NODES)
        assert set(weights.keys()) == {"1y_1y", "1y_10y"}
        assert abs(sum(weights.values()) - 1.0) < 1e-10
        # Check it's in the right proportion (log-space)
        r = (math.log(3.0) - math.log(1.0)) / (math.log(10.0) - math.log(1.0))
        assert abs(weights["1y_1y"] - (1.0 - r)) < 1e-10
        assert abs(weights["1y_10y"] - r) < 1e-10

    def test_on_grid_line_tenor_axis(self):
        """Observation between 1y and 10y expiry, exactly at 1y tenor -> 2 weights."""
        expiry = 3.0  # between 1y and 10y
        weights = _compute_bilinear_weights(expiry, 1.0, SMALL_GRID_NODES)
        assert set(weights.keys()) == {"1y_1y", "10y_1y"}
        assert abs(sum(weights.values()) - 1.0) < 1e-10

    def test_off_grid_four_weights(self):
        """Observation between grid lines on both axes -> 4 weights."""
        weights = _compute_bilinear_weights(3.0, 3.0, SMALL_GRID_NODES)
        assert len(weights) == 4
        expected_keys = {"1y_1y", "1y_10y", "10y_1y", "10y_10y"}
        assert set(weights.keys()) == expected_keys
        assert abs(sum(weights.values()) - 1.0) < 1e-10
        # All positive
        assert all(w > 0 for w in weights.values())

    def test_weights_sum_to_one_various_coords(self):
        """Sum-to-1 invariant for many random coordinates."""
        rng = np.random.default_rng(12345)
        for _ in range(50):
            fwd = rng.uniform(0.05, 15.0)
            tenor = rng.uniform(0.5, 15.0)
            weights = _compute_bilinear_weights(fwd, tenor, SMALL_GRID_NODES)
            assert abs(sum(weights.values()) - 1.0) < 1e-10, (
                f"Weights don't sum to 1 for ({fwd}, {tenor}): {weights}"
            )
            assert all(w >= 0 for w in weights.values())

    def test_boundary_extrapolation_low(self):
        """Observation below the grid boundary clamps to edge."""
        # Expiry below 1m, tenor below 1y
        weights = _compute_bilinear_weights(0.01, 0.5, SMALL_GRID_NODES)
        # Should clamp to the (1m, 1y) corner
        assert "1m_1y" in weights
        assert abs(sum(weights.values()) - 1.0) < 1e-10

    def test_boundary_extrapolation_high(self):
        """Observation above the grid boundary clamps to edge."""
        weights = _compute_bilinear_weights(20.0, 20.0, SMALL_GRID_NODES)
        assert "10y_10y" in weights
        assert abs(weights["10y_10y"] - 1.0) < 1e-10

    def test_full_core_grid_18m_1y(self):
        """Typical ULC off-grid trade: 18m x 1y on the full 66-node core grid."""
        fwd_years = 1.5  # 18m
        tenor_years = 1.0  # 1y -- exactly on the tenor grid line
        weights = _compute_bilinear_weights(fwd_years, tenor_years, CORE_GRID_NODES)
        # Tenor is exactly 1y, so should only hit 1y and 2y expiry nodes at 1y tenor
        assert set(weights.keys()) == {"1y_1y", "2y_1y"}
        assert abs(sum(weights.values()) - 1.0) < 1e-10
        # In log-space, 18m is closer to 2y than 1y:
        # log(1.5)-log(1.0) = 0.405 vs log(2.0)-log(1.5) = 0.288
        assert weights["2y_1y"] > weights["1y_1y"]

    def test_full_core_grid_18m_2y(self):
        """Another ULC off-grid trade: 18m x 2y."""
        weights = _compute_bilinear_weights(1.5, 2.0, CORE_GRID_NODES)
        # 18m is between 1y and 2y expiry, 2y tenor is exactly on grid
        assert set(weights.keys()) == {"1y_2y", "2y_2y"}
        assert abs(sum(weights.values()) - 1.0) < 1e-10

    def test_full_core_grid_9m_3y(self):
        """Off-grid on both axes: 9m x 3y (between 6m/1y and 2y/5y)."""
        weights = _compute_bilinear_weights(0.75, 3.0, CORE_GRID_NODES)
        assert len(weights) == 4
        assert set(weights.keys()) == {"6m_2y", "6m_5y", "1y_2y", "1y_5y"}
        assert abs(sum(weights.values()) - 1.0) < 1e-10


# ===================================================================
# Tests: conditional_mvn_update with observation_operator
# ===================================================================


class TestConditionalMVNUpdateOperator:
    """Verify the observation operator path produces correct results."""

    def test_identity_operator_matches_legacy_path(self):
        """When H is an identity-selection matrix, results should match legacy path."""
        model, eod = _small_model_and_eod()
        observed_node = "1y_1y"
        observed_value = float(eod[observed_node] + 3.0)

        # Legacy path
        legacy = conditional_mvn_update(
            model, eod,
            {observed_node: observed_value},
            {observed_node: 1.0},
            base_noise=0.5,
        )

        # Operator path: build identity-selection H
        col_idx = model.columns.index(observed_node)
        H = np.zeros((1, len(model.columns)), dtype=float)
        H[0, col_idx] = 1.0

        operator = conditional_mvn_update(
            model, eod,
            np.array([observed_value]),
            np.array([1.0]),
            base_noise=0.5,
            observation_operator=H,
            observation_labels=[observed_node],
        )

        np.testing.assert_allclose(
            operator.live_grid.to_numpy(),
            legacy.live_grid.to_numpy(),
            atol=1e-10,
        )
        np.testing.assert_allclose(
            operator.delta_grid.to_numpy(),
            legacy.delta_grid.to_numpy(),
            atol=1e-10,
        )
        np.testing.assert_allclose(
            operator.confidence.to_numpy(),
            legacy.confidence.to_numpy(),
            atol=1e-10,
        )
        np.testing.assert_allclose(
            operator.posterior_factors.to_numpy(),
            legacy.posterior_factors.to_numpy(),
            atol=1e-10,
        )

    def test_off_grid_observation_influences_multiple_nodes(self):
        """An off-grid observation should move multiple grid nodes."""
        model, eod = _small_model_and_eod()

        # Bilinear weights for 3yr expiry, 3yr tenor (between 1y and 10y on both)
        weights = _compute_bilinear_weights(3.0, 3.0, SMALL_GRID_NODES)
        H = np.zeros((1, len(model.columns)), dtype=float)
        for node_key, w in weights.items():
            idx = model.columns.index(node_key)
            H[0, idx] = w

        # Implied observation: the interpolated surface value +5 bpvol
        eod_vec = eod.to_numpy(dtype=float)
        interpolated_eod = float(H @ eod_vec)
        observed = interpolated_eod + 5.0

        result = conditional_mvn_update(
            model, eod,
            np.array([observed]),
            np.array([1.0]),
            base_noise=0.5,
            observation_operator=H,
            observation_labels=["3y_3y_offgrid"],
        )

        # All 4 bracketing nodes should have moved up
        for node_key in weights:
            assert result.delta_grid[node_key] > 0, (
                f"Node {node_key} should have moved up but delta={result.delta_grid[node_key]}"
            )

        # The update should propagate to other nodes too (PCA coupling)
        assert result.delta_grid.abs().sum() > 0
        # Confidence should be > 0 somewhere
        assert result.confidence.max() > 0

    def test_empty_operator_returns_prior(self):
        """Zero-row operator should return the prior (no update)."""
        model, eod = _small_model_and_eod()

        H = np.empty((0, len(model.columns)), dtype=float)
        result = conditional_mvn_update(
            model, eod,
            np.empty(0),
            np.empty(0),
            base_noise=0.5,
            observation_operator=H,
            observation_labels=[],
        )

        np.testing.assert_allclose(result.live_grid.to_numpy(), eod.to_numpy(), atol=1e-10)
        np.testing.assert_allclose(result.delta_grid.to_numpy(), 0.0, atol=1e-10)

    def test_multiple_observations_operator(self):
        """Multiple off-grid observations should be processed correctly."""
        model, eod = _small_model_and_eod()

        # Two observations at different off-grid points
        w1 = _compute_bilinear_weights(0.5, 3.0, SMALL_GRID_NODES)  # 6m, 3y
        w2 = _compute_bilinear_weights(5.0, 5.0, SMALL_GRID_NODES)  # 5y, 5y

        H = np.zeros((2, len(model.columns)), dtype=float)
        for node_key, w in w1.items():
            H[0, model.columns.index(node_key)] = w
        for node_key, w in w2.items():
            H[1, model.columns.index(node_key)] = w

        eod_vec = eod.to_numpy(dtype=float)
        obs1 = float(H[0] @ eod_vec) + 3.0
        obs2 = float(H[1] @ eod_vec) - 2.0

        result = conditional_mvn_update(
            model, eod,
            np.array([obs1, obs2]),
            np.array([1.0, 1.0]),
            base_noise=0.5,
            observation_operator=H,
            observation_labels=["obs_0", "obs_1"],
        )

        # Delta should be non-zero
        assert result.delta_grid.abs().sum() > 0
        assert len(result.observed_nodes) == 2


# ===================================================================
# Tests: build_observation_operator
# ===================================================================


def _make_obs(
    package_id: str,
    fwd_years: float,
    tenor_years: float,
    bpvol: float,
    grid_weights: dict[str, float] | None = None,
    staleness_weight: float = 1.0,
) -> StraddleObservation:
    return StraddleObservation(
        package_id=package_id,
        execution_timestamp=dt.datetime(2025, 12, 1, 14, 0, 0, tzinfo=dt.timezone.utc),
        forward_label="1Y",
        tenor_label="1Y",
        forward_years=fwd_years,
        tenor_years=tenor_years,
        observed_bpvol=bpvol,
        premium=None,
        notional=100_000_000.0,
        platform_identifier="BGCD",
        platform_type="idb",
        event_action="NEWT",
        trade_label=f"{fwd_years}Yx{tenor_years}Y",
        core_node_key="1y_1y",
        grid_weights=grid_weights,
        staleness_weight=staleness_weight,
    )


class TestBuildObservationOperator:
    def test_basic_shape(self):
        model, _ = _small_model_and_eod()
        weights = _compute_bilinear_weights(3.0, 3.0, SMALL_GRID_NODES)
        obs = _make_obs("pkg1", 3.0, 3.0, 85.0, grid_weights=weights)

        values, noise, H, labels, groups = build_observation_operator(
            [obs], model.columns, base_noise_bpvol=0.5,
        )

        assert values.shape == (1,)
        assert noise.shape == (1,)
        assert H.shape == (1, len(model.columns))
        assert len(labels) == 1
        assert abs(H.sum() - 1.0) < 1e-10

    def test_empty_observations(self):
        model, _ = _small_model_and_eod()
        values, noise, H, labels, groups = build_observation_operator(
            [], model.columns, base_noise_bpvol=0.5,
        )
        assert H.shape == (0, len(model.columns))
        assert len(labels) == 0

    def test_observations_without_grid_weights_are_skipped(self):
        model, _ = _small_model_and_eod()
        obs = _make_obs("pkg1", 3.0, 3.0, 85.0, grid_weights=None)

        values, noise, H, labels, groups = build_observation_operator(
            [obs], model.columns, base_noise_bpvol=0.5,
        )
        assert H.shape[0] == 0

    def test_node_groups_populated(self):
        model, _ = _small_model_and_eod()
        weights = _compute_bilinear_weights(3.0, 3.0, SMALL_GRID_NODES)
        obs = _make_obs("pkg1", 3.0, 3.0, 85.0, grid_weights=weights)

        _, _, _, _, groups = build_observation_operator(
            [obs], model.columns, base_noise_bpvol=0.5,
        )

        # All nodes in the weights should appear in groups
        for node_key in weights:
            assert node_key in groups
            assert obs in groups[node_key]


# ===================================================================
# Tests: map_observations_to_grid with continuous flag
# ===================================================================


class TestMapObservationsToGrid:
    def test_continuous_populates_grid_weights(self):
        obs = _make_obs("pkg1", 1.5, 1.0, 85.0)
        mapped = map_observations_to_grid(
            [obs], tenor_weight=0.7, use_continuous_observations=True,
        )
        assert len(mapped) == 1
        assert mapped[0].grid_weights is not None
        assert abs(sum(mapped[0].grid_weights.values()) - 1.0) < 1e-10
        assert mapped[0].core_node_key is not None

    def test_legacy_does_not_populate_grid_weights(self):
        obs = _make_obs("pkg1", 1.5, 1.0, 85.0)
        mapped = map_observations_to_grid(
            [obs], tenor_weight=0.7, use_continuous_observations=False,
        )
        assert len(mapped) == 1
        assert mapped[0].grid_weights is None
        assert mapped[0].core_node_key is not None

    def test_on_grid_trade_has_single_weight(self):
        obs = _make_obs("pkg1", 1.0, 1.0, 85.0)
        mapped = map_observations_to_grid(
            [obs], tenor_weight=0.7, use_continuous_observations=True,
        )
        assert len(mapped) == 1
        w = mapped[0].grid_weights
        assert w is not None
        assert len(w) == 1
        assert "1y_1y" in w
        assert abs(w["1y_1y"] - 1.0) < 1e-10
