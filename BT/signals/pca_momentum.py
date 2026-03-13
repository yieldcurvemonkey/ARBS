"""PCA Momentum signal generation module.

Ports the PM's legacy PCA momentum strategy (pf_momentumPCA from timeSeries.py
and pfBBGHourlySVM.m) to modern sklearn with configurable hyperparameters.

Feature engineering:
  1. EWMA - SMA spreads for short-term spans (velocity)
  2. EWMA - SMA spreads for long-term spans (trend)
  3. EWMA_long - EWMA_short cross-regime spreads (interaction)

Pipeline: StandardScaler → PCA → Classifier (LogReg or SVM)
Labels: Forward return z-score binned into {-1, 0, +1}
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Literal, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.decomposition import PCA
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC


@dataclass
class PCAMomentumConfig:
    """All hyperparameters for the PCA momentum strategy.

    Default spans are calibrated for ~30min intraday bars, mirroring the
    hourly lookbacks from pfBBGHourlySVM.m scaled down by 2x.
    """

    # MA feature parameters
    ewma_short_spans: List[int] = field(default_factory=lambda: [24, 48, 120, 240])
    ewma_long_spans: List[int] = field(default_factory=lambda: [360, 1080, 1440])

    # PCA
    n_components: int = 2

    # Classifier
    classifier: Literal["logistic", "svm"] = "logistic"
    classifier_C: float = 1.0

    # Label generation
    label_z_threshold: float = 1.0  # dead-zone: |z| < threshold → neutral (0)
    label_lookback: int = 120  # rolling window for z-score normalization
    label_forward_window: int = 10  # forward return horizon for labels

    # Train/test
    train_fraction: float = 0.7

    # Signal post-processing
    signal_smoothing: Optional[int] = None


# ---------------------------------------------------------------------------
# Feature generation
# ---------------------------------------------------------------------------

def generate_ma_features(
    rate_series: pd.Series,
    ewma_short_spans: List[int],
    ewma_long_spans: List[int],
) -> pd.DataFrame:
    """Generate moving-average spread feature matrix from a rate time series.

    Replicates the legacy pf_momentumPCA feature grid:
      1. EWMA_short[i] - SMA_short[i]   (velocity at each short horizon)
      2. EWMA_long[i]  - SMA_long[i]    (trend at each long horizon)
      3. EWMA_long[i]  - EWMA_short[j]  (cross-regime interaction)

    Parameters
    ----------
    rate_series : pd.Series
        Rate time series (intraday or daily).
    ewma_short_spans, ewma_long_spans : list of int
        Window spans for short/long EWMA and SMA.

    Returns
    -------
    pd.DataFrame
        Feature matrix. NaN rows at the start (warm-up) are preserved.
    """
    features = {}
    ewma_cache_short = {}
    ewma_cache_long = {}

    for span in ewma_short_spans:
        ew = rate_series.ewm(span=span, adjust=False).mean()
        sm = rate_series.rolling(window=span).mean()
        ewma_cache_short[span] = ew
        features[f"ewma_sma_short_{span}"] = ew - sm

    for span in ewma_long_spans:
        ew = rate_series.ewm(span=span, adjust=False).mean()
        sm = rate_series.rolling(window=span).mean()
        ewma_cache_long[span] = ew
        features[f"ewma_sma_long_{span}"] = ew - sm

    for l_span in ewma_long_spans:
        for s_span in ewma_short_spans:
            features[f"cross_{l_span}_{s_span}"] = (
                ewma_cache_long[l_span] - ewma_cache_short[s_span]
            )

    return pd.DataFrame(features, index=rate_series.index)


# ---------------------------------------------------------------------------
# Label generation
# ---------------------------------------------------------------------------

def generate_labels(
    rate_series: pd.Series,
    forward_window: int = 10,
    z_lookback: int = 120,
    z_threshold: float = 1.0,
) -> pd.Series:
    """Generate classification labels from forward-return z-scores.

    Mirrors the PM's MATLAB labeling: compute a rolling z-score of the
    N-period forward return, then bin into classes:
      +1  if z > z_threshold   (strong up-trend)
      -1  if z < -z_threshold  (strong down-trend)
       0  if |z| <= z_threshold (chop / dead zone → no trade)

    The dead zone is critical for intraday to avoid over-trading in noise.

    Returns pd.Series of {-1, 0, +1}, NaN where not computable.
    """
    fwd_return = rate_series.shift(-forward_window) - rate_series
    rolling_mean = fwd_return.rolling(z_lookback).mean()
    rolling_std = fwd_return.rolling(z_lookback).std()
    z_score = (fwd_return - rolling_mean) / rolling_std.replace(0, np.nan)

    labels = pd.Series(0, index=rate_series.index, dtype=float)
    labels[z_score > z_threshold] = 1.0
    labels[z_score < -z_threshold] = -1.0
    labels[z_score.isna() | fwd_return.isna()] = np.nan
    return labels


# ---------------------------------------------------------------------------
# Pipeline construction, fitting, prediction
# ---------------------------------------------------------------------------

def build_pipeline(
    n_components: int = 2,
    classifier: Literal["logistic", "svm"] = "logistic",
    classifier_C: float = 1.0,
) -> Pipeline:
    """Build sklearn Pipeline: StandardScaler → PCA → Classifier."""
    if classifier == "logistic":
        clf = LogisticRegression(
            C=classifier_C,
            max_iter=1000,
            solver="lbfgs",
            class_weight="balanced",
        )
    elif classifier == "svm":
        clf = SVC(C=classifier_C, kernel="rbf", class_weight="balanced")
    else:
        raise ValueError(f"Unknown classifier: {classifier}")

    return Pipeline([
        ("scaler", StandardScaler()),
        ("pca", PCA(n_components=n_components)),
        ("clf", clf),
    ])


def fit_pca_momentum(
    features: pd.DataFrame,
    labels: pd.Series,
    config: PCAMomentumConfig,
) -> Tuple[Pipeline, pd.Index]:
    """Fit the PCA momentum pipeline on the training portion.

    Neutral labels (0) are excluded from classifier training — the model
    only learns to distinguish strong-up (+1) vs strong-down (-1).

    Returns (fitted_pipeline, train_index).
    """
    # Align: keep rows where ALL features AND labels are non-NaN
    valid = features.dropna().index.intersection(labels.dropna().index)
    # Exclude neutral class for training
    valid_non_neutral = valid[labels.loc[valid] != 0]

    if len(valid_non_neutral) == 0:
        raise ValueError("No valid non-neutral training samples after alignment")

    X = features.loc[valid_non_neutral].values
    y = labels.loc[valid_non_neutral].values.astype(int)

    split = int(len(X) * config.train_fraction)
    if split == 0:
        raise ValueError("Training set is empty — check train_fraction or data length")

    X_train, y_train = X[:split], y[:split]

    pipeline = build_pipeline(
        n_components=min(config.n_components, X_train.shape[1]),
        classifier=config.classifier,
        classifier_C=config.classifier_C,
    )
    pipeline.fit(X_train, y_train)
    return pipeline, valid_non_neutral[:split]


def predict_signals(
    pipeline: Pipeline,
    features: pd.DataFrame,
    smoothing: Optional[int] = None,
) -> pd.Series:
    """Predict trading signals from a fitted pipeline.

    Returns pd.Series of {-1, +1} for rows with valid features, NaN otherwise.
    Optional EWMA smoothing + sign for signal filtering.
    """
    valid_mask = features.notna().all(axis=1)
    signals = pd.Series(np.nan, index=features.index, name="signal")
    if valid_mask.sum() == 0:
        return signals

    X = features.loc[valid_mask].values
    preds = pipeline.predict(X)
    signals.loc[valid_mask] = preds

    if smoothing is not None and smoothing > 1:
        signals = signals.ewm(span=smoothing, adjust=False).mean().apply(np.sign)

    return signals


# ---------------------------------------------------------------------------
# PCA component extraction (for visualization)
# ---------------------------------------------------------------------------

def extract_pca_components(
    pipeline: Pipeline,
    features: pd.DataFrame,
) -> pd.DataFrame:
    """Extract PCA-transformed components for visualization.

    Returns DataFrame with columns PC1, PC2, ... aligned to features index.
    """
    valid_mask = features.notna().all(axis=1)
    scaler = pipeline.named_steps["scaler"]
    pca = pipeline.named_steps["pca"]

    result = pd.DataFrame(
        np.nan,
        index=features.index,
        columns=[f"PC{i + 1}" for i in range(pca.n_components_)],
    )
    if valid_mask.sum() > 0:
        X_scaled = scaler.transform(features.loc[valid_mask].values)
        X_pca = pca.transform(X_scaled)
        result.loc[valid_mask] = X_pca

    return result
