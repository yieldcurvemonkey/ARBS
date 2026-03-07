import datetime as dt

import numpy as np
import pandas as pd

from RVUtils.surface_pca_model import (
    SurfacePCAModel,
    conditional_mvn_update,
    fit_surface_pca_from_eod_grids,
)


def _make_training_levels() -> pd.DataFrame:
    rng = np.random.default_rng(7)
    columns = ["1m_1y", "1m_2y", "1m_5y", "1y_1y", "1y_2y", "1y_5y"]
    base = np.array([72.0, 73.0, 75.0, 80.0, 81.0, 83.0])
    loading_1 = np.array([1.0, 1.0, 0.9, 0.7, 0.7, 0.6])
    loading_2 = np.array([-0.3, -0.1, 0.2, -0.2, 0.1, 0.4])

    levels = [base]
    for _ in range(80):
        factor_1 = rng.normal(scale=0.8)
        factor_2 = rng.normal(scale=0.25)
        shock = factor_1 * loading_1 + factor_2 * loading_2 + rng.normal(scale=0.05, size=len(columns))
        levels.append(levels[-1] + shock)

    index = pd.bdate_range(dt.date(2025, 8, 1), periods=len(levels))
    return pd.DataFrame(levels, index=index, columns=columns)


def test_fit_surface_pca_from_eod_grids_shapes_and_round_trip():
    levels_df = _make_training_levels()

    model, scores = fit_surface_pca_from_eod_grids(levels_df, n_components=3)

    assert isinstance(model, SurfacePCAModel)
    assert model.columns == levels_df.columns.tolist()
    assert model.loadings.shape == (levels_df.shape[1], 3)
    assert model.eigenvalues.shape == (3,)
    assert scores.shape == (levels_df.shape[0] - 1, 3)
    assert model.training_start == levels_df.index.min().date()
    assert model.training_end == levels_df.index.max().date()

    restored = SurfacePCAModel.from_json(model.to_json())
    assert restored.columns == model.columns
    assert np.allclose(restored.mean, model.mean)
    assert np.allclose(restored.loadings, model.loadings)
    assert np.allclose(restored.eigenvalues, model.eigenvalues)
    assert np.allclose(restored.total_variance, model.total_variance)
    assert np.allclose(restored.residual_variance, model.residual_variance)


def test_conditional_mvn_update_zero_observation_returns_eod():
    levels_df = _make_training_levels()
    model, _ = fit_surface_pca_from_eod_grids(levels_df, n_components=2)
    eod_grid = levels_df.iloc[-1]

    result = conditional_mvn_update(model, eod_grid, {})

    assert result.observed_nodes == []
    assert np.allclose(result.live_grid.to_numpy(), eod_grid.to_numpy())
    assert np.allclose(result.delta_grid.to_numpy(), 0.0)
    assert np.allclose(result.posterior_factors.to_numpy(), 0.0)


def test_conditional_mvn_update_single_observation_propagates():
    levels_df = _make_training_levels()
    model, _ = fit_surface_pca_from_eod_grids(levels_df, n_components=2)
    eod_grid = levels_df.iloc[-1]

    observed_node = "1m_1y"
    observed_value = float(eod_grid[observed_node] + 4.5)
    result = conditional_mvn_update(
        model,
        eod_grid,
        {observed_node: observed_value},
        {observed_node: 1.0},
        base_noise=0.1,
    )

    assert result.observed_nodes == [observed_node]
    assert result.live_grid[observed_node] > float(eod_grid[observed_node])
    assert result.delta_grid.abs().sum() > 0
    propagated_nodes = [node for node in model.columns if node != observed_node]
    assert any(result.delta_grid[node] > 0 for node in propagated_nodes)
    assert 0.0 <= float(result.confidence[observed_node]) <= 1.0
