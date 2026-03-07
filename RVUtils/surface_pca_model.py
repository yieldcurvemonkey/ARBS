from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from definitions.IRSwaptions import SURFACE_NODE_KEYS


def _coerce_date(value: Any) -> dt.date:
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    raise TypeError(f"Unsupported date-like value: {type(value)!r}")


def _coerce_grid_vector(
    values: Mapping[str, Any] | pd.Series | Sequence[float] | np.ndarray,
    columns: Sequence[str],
) -> np.ndarray:
    if isinstance(values, pd.Series):
        series = values.reindex(columns)
    elif isinstance(values, Mapping):
        series = pd.Series({column: values.get(column) for column in columns}, index=columns, dtype=float)
    else:
        array = np.asarray(values, dtype=float)
        if array.shape != (len(columns),):
            raise ValueError(
                f"Grid vector must have shape {(len(columns),)}, got {array.shape}."
            )
        return array

    if series.isna().any():
        missing = series[series.isna()].index.tolist()
        raise ValueError(f"Grid vector is missing values for nodes: {missing}")
    return series.astype(float).to_numpy()


def _coerce_observation_series(
    observations: Mapping[str, Any] | pd.Series | Sequence[Mapping[str, Any]],
) -> pd.Series:
    if isinstance(observations, pd.Series):
        out = observations.copy()
    elif isinstance(observations, Mapping):
        out = pd.Series(observations, dtype=float)
    else:
        items: dict[str, float] = {}
        for entry in observations:
            node_key = (
                entry.get("grid_node_key")
                or entry.get("node_key")
                or entry.get("column")
                or entry.get("key")
            )
            observed_value = (
                entry.get("observed_bpvol")
                if "observed_bpvol" in entry
                else entry.get("observed_value", entry.get("value"))
            )
            if not node_key or observed_value is None:
                continue
            items[str(node_key)] = float(observed_value)
        out = pd.Series(items, dtype=float)

    out = out.dropna()
    if out.empty:
        return pd.Series(dtype=float)
    out.index = out.index.astype(str)
    return out.astype(float)


def _coerce_weight_series(
    staleness_weights: Mapping[str, Any] | pd.Series | Sequence[float] | np.ndarray | None,
    observation_keys: Sequence[str],
) -> np.ndarray:
    if staleness_weights is None:
        return np.ones(len(observation_keys), dtype=float)

    if isinstance(staleness_weights, pd.Series):
        series = staleness_weights.reindex(observation_keys)
    elif isinstance(staleness_weights, Mapping):
        series = pd.Series(
            {key: staleness_weights.get(key) for key in observation_keys},
            index=observation_keys,
            dtype=float,
        )
    else:
        array = np.asarray(staleness_weights, dtype=float)
        if array.shape != (len(observation_keys),):
            raise ValueError(
                "staleness_weights must align with the observation count."
            )
        return np.where(array > 0, array, 1.0)

    return np.where(series.fillna(1.0).astype(float).to_numpy() > 0, series.fillna(1.0).astype(float).to_numpy(), 1.0)


def _canonical_surface_columns(columns: Sequence[str]) -> list[str]:
    column_set = set(columns)
    canonical = [column for column in SURFACE_NODE_KEYS if column in column_set]
    if len(canonical) == len(columns):
        return canonical
    return list(columns)


@dataclass
class SurfacePCAModel:
    columns: list[str]
    mean: np.ndarray
    loadings: np.ndarray
    eigenvalues: np.ndarray
    n_components: int
    training_start: dt.date
    training_end: dt.date
    training_days: int
    total_variance: np.ndarray
    residual_variance: np.ndarray

    def to_json(self) -> dict[str, Any]:
        return {
            "columns": list(self.columns),
            "mean": self.mean.tolist(),
            "loadings": self.loadings.tolist(),
            "eigenvalues": self.eigenvalues.tolist(),
            "n_components": int(self.n_components),
            "training_start": self.training_start.isoformat(),
            "training_end": self.training_end.isoformat(),
            "training_days": int(self.training_days),
            "total_variance": self.total_variance.tolist(),
            "residual_variance": self.residual_variance.tolist(),
        }

    @classmethod
    def from_json(cls, payload: Mapping[str, Any]) -> "SurfacePCAModel":
        return cls(
            columns=[str(column) for column in payload["columns"]],
            mean=np.asarray(payload["mean"], dtype=float),
            loadings=np.asarray(payload["loadings"], dtype=float),
            eigenvalues=np.asarray(payload["eigenvalues"], dtype=float),
            n_components=int(payload["n_components"]),
            training_start=dt.date.fromisoformat(str(payload["training_start"])),
            training_end=dt.date.fromisoformat(str(payload["training_end"])),
            training_days=int(payload["training_days"]),
            total_variance=np.asarray(payload["total_variance"], dtype=float),
            residual_variance=np.asarray(payload["residual_variance"], dtype=float),
        )


@dataclass
class ConditionalMVNUpdateResult:
    live_grid: pd.Series
    delta_grid: pd.Series
    confidence: pd.Series
    posterior_factors: pd.Series
    posterior_factor_cov: pd.DataFrame
    observed_nodes: list[str]
    observation_noise: pd.Series


def fit_surface_pca_from_eod_grids(
    levels_df: pd.DataFrame,
    n_components: int = 5,
) -> tuple[SurfacePCAModel, pd.DataFrame]:
    if levels_df.empty:
        raise ValueError("levels_df must contain at least one row.")

    ordered_columns = _canonical_surface_columns(levels_df.columns.tolist())
    numeric_df = levels_df[ordered_columns].apply(pd.to_numeric, errors="coerce")
    if numeric_df.isna().any().any():
        missing_cols = numeric_df.columns[numeric_df.isna().any()].tolist()
        raise ValueError(f"levels_df contains NaNs after numeric coercion: {missing_cols}")

    levels_sorted = numeric_df.sort_index()
    changes = levels_sorted.diff().dropna(how="any")
    if changes.empty:
        raise ValueError("Need at least two EOD grids to fit a surface PCA model.")

    mean_vec = changes.mean(axis=0).to_numpy(dtype=float)
    x_centered = changes.to_numpy(dtype=float) - mean_vec
    obs_count, width = x_centered.shape
    if obs_count < 2:
        raise ValueError("Need at least two daily changes to estimate covariance.")

    covariance = (x_centered.T @ x_centered) / (obs_count - 1)
    eigenvalues, eigenvectors = np.linalg.eigh(covariance)
    order = np.argsort(eigenvalues)[::-1]
    eigenvalues = eigenvalues[order]
    eigenvectors = eigenvectors[:, order]

    k = min(max(int(n_components), 1), width)
    retained_eigenvalues = eigenvalues[:k]
    retained_loadings = eigenvectors[:, :k]

    explained_variance = np.sum(
        (retained_loadings**2) * retained_eigenvalues[np.newaxis, :],
        axis=1,
    )
    total_variance = np.clip(np.diag(covariance), a_min=0.0, a_max=None)
    residual_variance = np.clip(total_variance - explained_variance, a_min=0.0, a_max=None)

    scores = x_centered @ retained_loadings
    score_columns = [f"PC{i + 1}" for i in range(k)]
    scores_df = pd.DataFrame(scores, index=changes.index, columns=score_columns)

    model = SurfacePCAModel(
        columns=ordered_columns,
        mean=mean_vec,
        loadings=retained_loadings,
        eigenvalues=retained_eigenvalues,
        n_components=k,
        training_start=_coerce_date(levels_sorted.index.min()),
        training_end=_coerce_date(levels_sorted.index.max()),
        training_days=int(obs_count),
        total_variance=total_variance,
        residual_variance=residual_variance,
    )
    return model, scores_df


def conditional_mvn_update(
    model: SurfacePCAModel,
    eod_grid: Mapping[str, Any] | pd.Series | Sequence[float] | np.ndarray,
    observations: Mapping[str, Any] | pd.Series | Sequence[Mapping[str, Any]],
    staleness_weights: Mapping[str, Any] | pd.Series | Sequence[float] | np.ndarray | None = None,
    *,
    base_noise: float = 1.0,
) -> ConditionalMVNUpdateResult:
    eod_vector = _coerce_grid_vector(eod_grid, model.columns)
    observation_series = _coerce_observation_series(observations)

    if observation_series.empty:
        zero_delta = pd.Series(np.zeros(len(model.columns), dtype=float), index=model.columns)
        zero_factors = pd.Series(
            np.zeros(model.n_components, dtype=float),
            index=[f"PC{i + 1}" for i in range(model.n_components)],
        )
        prior_cov = np.diag(model.eigenvalues.astype(float))
        return ConditionalMVNUpdateResult(
            live_grid=pd.Series(eod_vector.copy(), index=model.columns),
            delta_grid=zero_delta,
            confidence=pd.Series(np.zeros(len(model.columns), dtype=float), index=model.columns),
            posterior_factors=zero_factors,
            posterior_factor_cov=pd.DataFrame(
                prior_cov,
                index=zero_factors.index,
                columns=zero_factors.index,
            ),
            observed_nodes=[],
            observation_noise=pd.Series(dtype=float),
        )

    unknown_nodes = sorted(set(observation_series.index) - set(model.columns))
    if unknown_nodes:
        raise KeyError(f"Observations contain unknown nodes: {unknown_nodes}")

    observed_nodes = list(observation_series.index)
    observation_weights = _coerce_weight_series(staleness_weights, observed_nodes)
    observation_indices = [model.columns.index(node) for node in observed_nodes]

    observed_vector = observation_series.to_numpy(dtype=float)
    delta_observed = observed_vector - eod_vector[observation_indices]
    mean_observed = model.mean[observation_indices]
    loadings_observed = model.loadings[observation_indices, :]
    residual_observed = model.residual_variance[observation_indices]

    observation_noise = np.clip(base_noise * observation_weights, a_min=1e-8, a_max=None)
    noise_diagonal = residual_observed + observation_noise

    inverse_noise = np.diag(1.0 / noise_diagonal)
    inverse_lambda = np.diag(1.0 / np.clip(model.eigenvalues, a_min=1e-10, a_max=None))

    posterior_precision = loadings_observed.T @ inverse_noise @ loadings_observed + inverse_lambda
    posterior_cov = np.linalg.inv(posterior_precision)
    centered_delta = delta_observed - mean_observed
    posterior_mean = posterior_cov @ loadings_observed.T @ inverse_noise @ centered_delta

    delta_hat = model.mean + model.loadings @ posterior_mean
    live_vector = eod_vector + delta_hat

    predictive_variance = (
        np.sum((model.loadings @ posterior_cov) * model.loadings, axis=1)
        + model.residual_variance
    )
    total_variance = np.clip(model.total_variance, a_min=1e-10, a_max=None)
    confidence = 1.0 - np.sqrt(predictive_variance / total_variance)
    confidence = np.clip(confidence, a_min=0.0, a_max=1.0)

    factor_index = [f"PC{i + 1}" for i in range(model.n_components)]
    return ConditionalMVNUpdateResult(
        live_grid=pd.Series(live_vector, index=model.columns),
        delta_grid=pd.Series(delta_hat, index=model.columns),
        confidence=pd.Series(confidence, index=model.columns),
        posterior_factors=pd.Series(posterior_mean, index=factor_index),
        posterior_factor_cov=pd.DataFrame(posterior_cov, index=factor_index, columns=factor_index),
        observed_nodes=observed_nodes,
        observation_noise=pd.Series(noise_diagonal, index=observed_nodes),
    )
