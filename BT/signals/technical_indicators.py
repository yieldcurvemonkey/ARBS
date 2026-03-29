"""pandas-ta-backed technical indicator signal builders."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np
import pandas as pd
import pandas_ta as ta
import tqdm


@dataclass(frozen=True)
class TechnicalIndicatorSignalResult:
    raw_series: pd.Series | pd.DataFrame
    indicator_frame: pd.DataFrame
    desired_position: pd.Series | pd.DataFrame
    execution_position: pd.Series | pd.DataFrame


def moving_average_crossover_signal(
    raw_series: pd.Series | pd.DataFrame,
    *,
    fast_window: int,
    slow_window: int,
    ema: bool = False,
) -> TechnicalIndicatorSignalResult:
    """Return discrete crossover positions from fast and slow simple moving averages."""
    if fast_window <= 0 or slow_window <= 0:
        raise ValueError("Moving-average windows must be positive.")
    if fast_window >= slow_window:
        raise ValueError("fast_window must be smaller than slow_window.")

    raw, was_series = _coerce_numeric_input(raw_series)
    if ema:
        fast_ma = _apply_series_indicator(raw, lambda series: ta.ema(series, length=fast_window))
        slow_ma = _apply_series_indicator(raw, lambda series: ta.ema(series, length=slow_window))
    else:
        fast_ma = _apply_series_indicator(raw, lambda series: ta.sma(series, length=fast_window))
        slow_ma = _apply_series_indicator(raw, lambda series: ta.sma(series, length=slow_window))

    spread = fast_ma - slow_ma

    desired = _empty_positions_like(raw)
    valid = fast_ma.notna() & slow_ma.notna()
    desired = desired.mask(valid & (spread > 0.0), 1.0)
    desired = desired.mask(valid & (spread < 0.0), -1.0)
    desired = desired.mask(valid & (spread == 0.0), 0.0)

    indicator_frame = _build_indicator_frame(
        was_series=was_series,
        components={
            "fast_ma": fast_ma,
            "slow_ma": slow_ma,
            "spread": spread,
        },
    )
    return _finalize_signal_result(
        raw_input=raw_series,
        raw_frame=raw,
        indicator_frame=indicator_frame,
        desired_frame=desired,
        was_series=was_series,
    )


def rsi_signal(
    raw_series: pd.Series | pd.DataFrame,
    *,
    window: int = 14,
    lower: float = 30.0,
    upper: float = 70.0,
) -> TechnicalIndicatorSignalResult:
    """Return discrete positions from the relative-strength index."""
    if window <= 0:
        raise ValueError("window must be positive.")
    if lower >= upper:
        raise ValueError("lower threshold must be below upper threshold.")

    raw, was_series = _coerce_numeric_input(raw_series)
    delta = raw.diff()
    gains = delta.clip(lower=0.0)
    losses = -delta.clip(upper=0.0)
    avg_gain = _apply_series_indicator(gains, lambda series: ta.rma(series, length=window))
    avg_loss = _apply_series_indicator(losses, lambda series: ta.rma(series, length=window))
    rsi = _apply_series_indicator(raw, lambda series: ta.rsi(series, length=window))
    warmup_mask = _valid_observation_counts(raw) < int(window)
    avg_gain = avg_gain.mask(warmup_mask)
    avg_loss = avg_loss.mask(warmup_mask)
    rsi = rsi.mask(warmup_mask)

    desired = _empty_positions_like(raw)
    valid = rsi.notna()
    desired = desired.mask(valid & (rsi < lower), 1.0)
    desired = desired.mask(valid & (rsi > upper), -1.0)
    desired = desired.mask(valid & (rsi >= lower) & (rsi <= upper), 0.0)

    indicator_frame = _build_indicator_frame(
        was_series=was_series,
        components={
            "rsi": rsi,
            "avg_gain": avg_gain,
            "avg_loss": avg_loss,
        },
    )
    return _finalize_signal_result(
        raw_input=raw_series,
        raw_frame=raw,
        indicator_frame=indicator_frame,
        desired_frame=desired,
        was_series=was_series,
    )


def bollinger_signal(
    raw_series: pd.Series | pd.DataFrame,
    *,
    window: int = 20,
    num_std: float = 2.0,
) -> TechnicalIndicatorSignalResult:
    """Return discrete positions from Bollinger band breaks."""
    if window <= 0:
        raise ValueError("window must be positive.")
    if num_std <= 0.0:
        raise ValueError("num_std must be positive.")

    raw, was_series = _coerce_numeric_input(raw_series)
    lower_band = _empty_indicator_like(raw)
    basis = _empty_indicator_like(raw)
    upper_band = _empty_indicator_like(raw)
    for column in raw.columns:
        bands = ta.bbands(raw[column], length=window, std=float(num_std))
        if bands is None or bands.empty:
            continue
        bands = bands.reindex(raw.index)
        lower_band[column] = pd.to_numeric(bands.iloc[:, 0], errors="coerce")
        basis[column] = pd.to_numeric(bands.iloc[:, 1], errors="coerce")
        upper_band[column] = pd.to_numeric(bands.iloc[:, 2], errors="coerce")

    desired = _empty_positions_like(raw)
    prior_lower = lower_band.shift(1)
    prior_upper = upper_band.shift(1)
    valid = prior_lower.notna() & prior_upper.notna()
    desired = desired.mask(valid & (raw < prior_lower), 1.0)
    desired = desired.mask(valid & (raw > prior_upper), -1.0)
    desired = desired.mask(valid & (raw >= prior_lower) & (raw <= prior_upper), 0.0)

    indicator_frame = _build_indicator_frame(
        was_series=was_series,
        components={
            "basis": basis,
            "upper_band": upper_band,
            "lower_band": lower_band,
            "band_width": upper_band - lower_band,
        },
    )
    return _finalize_signal_result(
        raw_input=raw_series,
        raw_frame=raw,
        indicator_frame=indicator_frame,
        desired_frame=desired,
        was_series=was_series,
    )


def macd_signal(
    raw_series: pd.Series | pd.DataFrame,
    *,
    fast_span: int = 12,
    slow_span: int = 26,
    signal_span: int = 9,
) -> TechnicalIndicatorSignalResult:
    """Return discrete positions from MACD line versus signal line."""
    if fast_span <= 0 or slow_span <= 0 or signal_span <= 0:
        raise ValueError("MACD spans must be positive.")
    if fast_span >= slow_span:
        raise ValueError("fast_span must be smaller than slow_span.")

    raw, was_series = _coerce_numeric_input(raw_series)
    ema_fast = _apply_series_indicator(raw, lambda series: ta.ema(series, length=fast_span))
    ema_slow = _apply_series_indicator(raw, lambda series: ta.ema(series, length=slow_span))
    macd_line = _empty_indicator_like(raw)
    signal_line = _empty_indicator_like(raw)
    histogram = _empty_indicator_like(raw)
    for column in raw.columns:
        macd_frame = ta.macd(raw[column], fast=fast_span, slow=slow_span, signal=signal_span)
        if macd_frame is None or macd_frame.empty:
            continue
        macd_frame = macd_frame.reindex(raw.index)
        macd_line[column] = pd.to_numeric(macd_frame.iloc[:, 0], errors="coerce")
        histogram[column] = pd.to_numeric(macd_frame.iloc[:, 1], errors="coerce")
        signal_line[column] = pd.to_numeric(macd_frame.iloc[:, 2], errors="coerce")

    desired = _empty_positions_like(raw)
    valid = signal_line.notna()
    desired = desired.mask(valid & (macd_line > signal_line), 1.0)
    desired = desired.mask(valid & (macd_line < signal_line), -1.0)
    desired = desired.mask(valid & (macd_line == signal_line), 0.0)

    indicator_frame = _build_indicator_frame(
        was_series=was_series,
        components={
            "ema_fast": ema_fast,
            "ema_slow": ema_slow,
            "macd_line": macd_line,
            "signal_line": signal_line,
            "histogram": histogram,
        },
    )
    return _finalize_signal_result(
        raw_input=raw_series,
        raw_frame=raw,
        indicator_frame=indicator_frame,
        desired_frame=desired,
        was_series=was_series,
    )


def pca_svm_momentum_signal(
    raw_series: pd.Series | pd.DataFrame,
    *,
    ewma_short_spans: Sequence[int] = (7, 14, 20),
    ewma_long_spans: Sequence[int] = (50, 75, 100),
    n_components: int = 2,
    svm_c: float = 0.02,
    svm_gamma: float = 0.1,
    label_window: int = 10,
    z_threshold: float = 1.75,
    train_fraction: float = 0.7,
    retrain_every: int | None = None,
    tod_volatility_adjust: bool = False,
    tod_volatility_lookback: int | None = None,
) -> TechnicalIndicatorSignalResult:
    """Return discrete positions from PCA-reduced SVM momentum classification.

    Ported from the Matlab ``pfBBGDailySVM`` pipeline:

    1. EMA minus SMA spreads for short and long windows, plus long-vs-short
       EMA cross-spreads (``len(short) + len(long) + len(short)*len(long)``
       features).
    2. Feature normalization (zero mean, unit variance).
    3. PCA projection to *n_components* dimensions.
    4. SVM with RBF kernel on backward-looking momentum z-score labels
       binned into {-1, 0, +1} via *z_threshold*.

    Uses expanding-window walk-forward training.  The first model is fitted
    on the initial *train_fraction* of valid observations; subsequent
    retrains expand the training set every *retrain_every* bars.  When
    *retrain_every* is ``None`` a single train/test split is used (matching
    the original Matlab 70/30 split).

    When *tod_volatility_adjust* is ``True``, the z-score denominator uses
    time-of-day adjusted volatility instead of a flat rolling std.  This
    prevents the z-scores from spiking during low-volatility sessions
    (e.g. Asian hours) and compressing during high-volatility sessions
    (e.g. US open).  *tod_volatility_lookback* controls the expanding
    lookback in calendar days for the time-of-day profile (default: all
    available history).
    """
    from sklearn.decomposition import PCA
    from sklearn.preprocessing import StandardScaler
    from sklearn.svm import SVC

    if n_components <= 0:
        raise ValueError("n_components must be positive.")
    if train_fraction <= 0.0 or train_fraction >= 1.0:
        raise ValueError("train_fraction must be between 0 and 1 exclusive.")

    raw, was_series = _coerce_numeric_input(raw_series)

    desired = _empty_positions_like(raw)
    pc_frames: dict[str, pd.DataFrame] = {
        f"pc_{i + 1}": _empty_indicator_like(raw) for i in range(n_components)
    }
    zscore_frame = _empty_indicator_like(raw)
    label_frame = _empty_indicator_like(raw)
    decision_frame = _empty_indicator_like(raw)

    for column in raw.columns:
        series = raw[column].dropna()
        if len(series) < 2:
            continue

        # 1. Feature generation (Matlab: EMA-SMA spreads + cross spreads)
        features = _build_momentum_features(series, ewma_short_spans, ewma_long_spans)

        # 2. Backward-looking momentum z-score (Matlab: yZscore)
        if tod_volatility_adjust:
            zscore = _tod_adjusted_momentum_zscore(
                series, label_window, lookback_days=tod_volatility_lookback
            )
        else:
            zscore = _backward_momentum_zscore(series, label_window)
        zscore_frame[column] = zscore

        # 3. Bin z-score into {-1, 0, +1} (Matlab: histc with labelBreaks)
        labels = pd.Series(np.nan, index=series.index, dtype=float)
        valid_z = zscore.notna()
        labels = labels.mask(valid_z & (zscore > z_threshold), 1.0)
        labels = labels.mask(valid_z & (zscore < -z_threshold), -1.0)
        labels = labels.mask(valid_z & (zscore.abs() <= z_threshold), 0.0)
        label_frame[column] = labels

        # 4. Walk-forward PCA-SVM
        feature_valid = features.notna().all(axis=1) & labels.notna()
        valid_idx = features.index[feature_valid]
        if len(valid_idx) < n_components + 1:
            continue

        n_train = int(len(valid_idx) * train_fraction)
        if n_train < n_components + 1:
            continue

        if retrain_every is None:
            blocks = [(0, n_train, n_train, len(valid_idx))]
        else:
            step = max(1, retrain_every)
            blocks = [
                (0, pred_start, pred_start, min(pred_start + step, len(valid_idx)))
                for pred_start in range(n_train, len(valid_idx), step)
            ]

        for train_start, train_end, pred_start, pred_end in blocks:
            train_idx = valid_idx[train_start:train_end]
            pred_idx = valid_idx[pred_start:pred_end]
            if len(train_idx) < n_components + 1 or len(pred_idx) == 0:
                continue

            X_train = features.loc[train_idx].values
            y_train = labels.loc[train_idx].values.astype(int)
            X_pred = features.loc[pred_idx].values

            unique_labels = set(int(v) for v in y_train)
            if len(unique_labels) < 2:
                pred_label = float(y_train[0])
                desired.loc[pred_idx, column] = pred_label
                decision_frame.loc[pred_idx, column] = pred_label
                continue

            # Normalize (Matlab: featureNormalize)
            scaler = StandardScaler()
            X_train_scaled = scaler.fit_transform(X_train)
            X_pred_scaled = scaler.transform(X_pred)

            # PCA (Matlab: pcaCustom + projectData)
            k = min(n_components, X_train_scaled.shape[1], len(X_train_scaled))
            pca = PCA(n_components=k)
            Z_train = pca.fit_transform(X_train_scaled)
            Z_pred = pca.transform(X_pred_scaled)

            # SVM with RBF kernel (Matlab: svmTrain + gaussianKernel)
            clf = SVC(kernel="rbf", C=svm_c, gamma=svm_gamma)
            clf.fit(Z_train, y_train)
            predictions = clf.predict(Z_pred)
            decision = clf.decision_function(Z_pred)

            desired.loc[pred_idx, column] = predictions.astype(float)
            if decision.ndim == 1:
                decision_frame.loc[pred_idx, column] = decision.astype(float)
            else:
                decision_frame.loc[pred_idx, column] = decision.max(axis=1).astype(float)

            for i in range(k):
                pc_frames[f"pc_{i + 1}"].loc[pred_idx, column] = Z_pred[:, i]

    components: dict[str, pd.DataFrame] = {
        "momentum_zscore": zscore_frame,
        "label": label_frame,
        "decision_score": decision_frame,
    }
    components.update(pc_frames)

    indicator_frame = _build_indicator_frame(
        was_series=was_series,
        components=components,
    )
    return _finalize_signal_result(
        raw_input=raw_series,
        raw_frame=raw,
        indicator_frame=indicator_frame,
        desired_frame=desired,
        was_series=was_series,
    )


def svr_momentum_signal(
    raw_series: pd.Series | pd.DataFrame,
    *,
    ewma_short_spans: Sequence[int] = (24, 48, 120, 240),
    ewma_long_spans: Sequence[int] = (360, 1080, 1440),
    svr_c: float = 400.0,
    svr_gamma: float = 0.5,
    svr_epsilon: float = 0.000000025,
    signal_threshold: float = 0.0,
    train_fraction: float = 0.7,
    retrain_every: int | None = None,
) -> TechnicalIndicatorSignalResult:
    """Return discrete positions from SVR momentum regression.

    Ported from the Matlab ``pfBBGHourlySVM`` intraday pipeline:

    1. Long EMA minus short EMA cross-spreads, each individually min/max
       scaled to [-1, 1] (``svm_feature_scale``), plus an intercept column.
    2. Labels are 1-step-ahead scaled returns (continuous, not binned).
    3. SVR with RBF kernel predicts the next return; the sign of the
       prediction is discretised into {-1, 0, +1} via *signal_threshold*.

    No PCA is applied (matching the Matlab intraday variant).
    """
    from sklearn.preprocessing import MinMaxScaler
    from sklearn.svm import SVR

    if train_fraction <= 0.0 or train_fraction >= 1.0:
        raise ValueError("train_fraction must be between 0 and 1 exclusive.")

    raw, was_series = _coerce_numeric_input(raw_series)

    desired = _empty_positions_like(raw)
    predicted_return_frame = _empty_indicator_like(raw)
    scaled_target_frame = _empty_indicator_like(raw)

    for column in raw.columns:
        series = raw[column].dropna()
        if len(series) < 2:
            continue

        # 1. Cross-spread features with per-feature min/max scaling
        features = _build_cross_spread_features(series, ewma_short_spans, ewma_long_spans)

        # 2. Continuous target: 1-step-ahead return, min/max scaled
        delta = series.diff()
        target = delta.shift(-1)
        scaled_target_frame[column] = target

        # Valid mask
        feature_valid = features.notna().all(axis=1) & target.notna()
        valid_idx = features.index[feature_valid]
        if len(valid_idx) < 3:
            continue

        n_train = int(len(valid_idx) * train_fraction)
        if n_train < 3:
            continue

        if retrain_every is None:
            blocks = [(0, n_train, n_train, len(valid_idx))]
        else:
            step = max(1, retrain_every)
            blocks = [
                (0, pred_start, pred_start, min(pred_start + step, len(valid_idx)))
                for pred_start in range(n_train, len(valid_idx), step)
            ]

        for train_start, train_end, pred_start, pred_end in tqdm.tqdm(blocks, desc="Building SVR momentum signal...", unit="block"):
            train_idx = valid_idx[train_start:train_end]
            pred_idx = valid_idx[pred_start:pred_end]
            if len(train_idx) < 3 or len(pred_idx) == 0:
                continue

            X_train_raw = features.loc[train_idx].values
            y_train_raw = target.loc[train_idx].values
            X_pred_raw = features.loc[pred_idx].values

            # Per-feature min/max scaling (Matlab: svm_feature_scale)
            x_scaler = MinMaxScaler(feature_range=(-1, 1))
            X_train_scaled = x_scaler.fit_transform(X_train_raw)
            X_pred_scaled = x_scaler.transform(X_pred_raw)

            # Scale target to [-1, 1] as well (Matlab: svm_feature_scale on y)
            y_scaler = MinMaxScaler(feature_range=(-1, 1))
            y_train_scaled = y_scaler.fit_transform(y_train_raw.reshape(-1, 1)).ravel()

            # Add intercept column (Matlab: ones(size(ohlc)))
            X_train_scaled = np.column_stack([np.ones(len(X_train_scaled)), X_train_scaled])
            X_pred_scaled = np.column_stack([np.ones(len(X_pred_scaled)), X_pred_scaled])

            # SVR with RBF kernel (Matlab: svr_trainer)
            svr = SVR(kernel="rbf", C=svr_c, gamma=svr_gamma, epsilon=svr_epsilon)
            svr.fit(X_train_scaled, y_train_scaled)
            y_pred_scaled = svr.predict(X_pred_scaled)

            # Inverse-scale predictions back to return space
            y_pred = y_scaler.inverse_transform(y_pred_scaled.reshape(-1, 1)).ravel()
            predicted_return_frame.loc[pred_idx, column] = y_pred

            # Discretise: sign of predicted return → position
            positions = np.where(
                y_pred > signal_threshold, 1.0,
                np.where(y_pred < -signal_threshold, -1.0, 0.0),
            )
            desired.loc[pred_idx, column] = positions

    indicator_frame = _build_indicator_frame(
        was_series=was_series,
        components={
            "predicted_return": predicted_return_frame,
            "scaled_target": scaled_target_frame,
        },
    )
    return _finalize_signal_result(
        raw_input=raw_series,
        raw_frame=raw,
        indicator_frame=indicator_frame,
        desired_frame=desired,
        was_series=was_series,
    )


def svr_momentum_signal_optimized(
    raw_series: pd.Series | pd.DataFrame,
    *,
    ewma_short_spans: Sequence[int] = (24, 48, 120, 240),
    ewma_long_spans: Sequence[int] = (360, 1080, 1440),
    svr_c: float = 400.0,
    svr_gamma: float = 0.5,
    svr_epsilon: float = 0.000000025,
    signal_threshold: float = 0.0,
    train_fraction: float = 0.7,
    retrain_every: int | None = None,
) -> TechnicalIndicatorSignalResult:
    """Drop-in replacement for :func:`svr_momentum_signal` with performance optimizations.

    Speed-ups over the base version:

    * **RBFSampler + SGDRegressor** — approximates the RBF kernel via
      random Fourier features (O(n·d) instead of O(n²–n³) libsvm), then
      fits a linear model with SGD which scales linearly.
    * **Numba-JIT EWM** — feature computation runs in compiled native code
      instead of pandas ``.ewm()``.
    * **Numpy-only walk-forward** — all array indexing, scaling, and
      intercept insertion use pre-allocated numpy buffers (no ``pd.loc``
      writes in the inner loop).
    * **Parallel columns** — multi-column DataFrames are processed
      concurrently via ``joblib.Parallel``.
    """
    import joblib
    from sklearn.kernel_approximation import RBFSampler
    from sklearn.linear_model import SGDRegressor
    from sklearn.preprocessing import MinMaxScaler

    if train_fraction <= 0.0 or train_fraction >= 1.0:
        raise ValueError("train_fraction must be between 0 and 1 exclusive.")

    raw, was_series = _coerce_numeric_input(raw_series)

    short_spans = np.array(list(ewma_short_spans), dtype=np.int64)
    long_spans = np.array(list(ewma_long_spans), dtype=np.int64)
    n_features = len(short_spans) * len(long_spans)

    def _process_column(col_values: np.ndarray, col_notna: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Process a single column entirely in numpy. Returns (desired, predicted_return, target)."""
        n = len(col_values)
        desired_out = np.full(n, np.nan, dtype=np.float64)
        pred_return_out = np.full(n, np.nan, dtype=np.float64)

        # Identify valid (non-NaN) slice
        valid_mask = col_notna.astype(bool)
        valid_positions = np.where(valid_mask)[0]
        if len(valid_positions) < 2:
            target_out = np.full(n, np.nan, dtype=np.float64)
            return desired_out, pred_return_out, target_out

        first_valid = valid_positions[0]
        last_valid = valid_positions[-1]
        vals = col_values[first_valid : last_valid + 1].copy()
        m = len(vals)

        # 1. Numba-JIT feature computation
        feat_matrix = _numba_cross_spread_features(vals, short_spans, long_spans)

        # 2. Continuous target: 1-step-ahead return
        delta = np.empty(m, dtype=np.float64)
        delta[0] = np.nan
        delta[1:] = vals[1:] - vals[:-1]
        target_local = np.empty(m, dtype=np.float64)
        target_local[:-1] = delta[1:]
        target_local[-1] = np.nan

        # Write target back to full-size array
        target_out = np.full(n, np.nan, dtype=np.float64)
        target_out[first_valid : last_valid + 1] = target_local

        # 3. Valid mask for training
        feat_valid = np.all(np.isfinite(feat_matrix), axis=1)
        target_valid = np.isfinite(target_local)
        row_valid = feat_valid & target_valid
        valid_local_idx = np.where(row_valid)[0]
        if len(valid_local_idx) < 3:
            return desired_out, pred_return_out, target_out

        n_train = int(len(valid_local_idx) * train_fraction)
        if n_train < 3:
            return desired_out, pred_return_out, target_out

        # 4. Build walk-forward blocks
        if retrain_every is None:
            blocks = [(0, n_train, n_train, len(valid_local_idx))]
        else:
            step = max(1, retrain_every)
            blocks = [
                (0, ps, ps, min(ps + step, len(valid_local_idx)))
                for ps in range(n_train, len(valid_local_idx), step)
            ]

        # 5. Walk-forward SVR
        # for train_start, train_end, pred_start, pred_end in blocks:
        for train_start, train_end, pred_start, pred_end in tqdm.tqdm(blocks, desc="Building SVR momentum signal...", unit="block"):
            t_idx = valid_local_idx[train_start:train_end]
            p_idx = valid_local_idx[pred_start:pred_end]
            if len(t_idx) < 3 or len(p_idx) == 0:
                continue

            X_train_raw = feat_matrix[t_idx]
            y_train_raw = target_local[t_idx]
            X_pred_raw = feat_matrix[p_idx]

            # Min/max scale features to [-1, 1]
            x_scaler = MinMaxScaler(feature_range=(-1, 1))
            X_train_s = x_scaler.fit_transform(X_train_raw)
            X_pred_s = x_scaler.transform(X_pred_raw)

            # Min/max scale target
            y_scaler = MinMaxScaler(feature_range=(-1, 1))
            y_train_s = y_scaler.fit_transform(y_train_raw.reshape(-1, 1)).ravel()

            # Add intercept column
            X_train_s = np.column_stack([np.ones(len(X_train_s)), X_train_s])
            X_pred_s = np.column_stack([np.ones(len(X_pred_s)), X_pred_s])

            # RBFSampler (random Fourier features) + SGDRegressor (O(n·d))
            n_rff = min(100, X_train_s.shape[1] * 8)
            rbf_sampler = RBFSampler(gamma=svr_gamma, n_components=n_rff, random_state=0)
            X_train_rff = rbf_sampler.fit_transform(X_train_s)
            X_pred_rff = rbf_sampler.transform(X_pred_s)

            sgd = SGDRegressor(
                loss="epsilon_insensitive",
                epsilon=svr_epsilon,
                alpha=1.0 / (svr_c * len(X_train_rff)),
                max_iter=2000,
                tol=1e-4,
                random_state=0,
            )
            sgd.fit(X_train_rff, y_train_s)
            y_pred_s = sgd.predict(X_pred_rff)

            y_pred = y_scaler.inverse_transform(y_pred_s.reshape(-1, 1)).ravel()

            # Map local indices back to full array positions
            global_p_idx = p_idx + first_valid
            pred_return_out[global_p_idx] = y_pred
            desired_out[global_p_idx] = np.where(
                y_pred > signal_threshold, 1.0,
                np.where(y_pred < -signal_threshold, -1.0, 0.0),
            )

        return desired_out, pred_return_out, target_out

    # Parallel column processing
    col_data = [
        (raw.iloc[:, i].values, raw.iloc[:, i].notna().values)
        for i in range(raw.shape[1])
    ]
    n_jobs = min(len(col_data), max(1, joblib.cpu_count() or 1))
    if len(col_data) == 1:
        results = [_process_column(*col_data[0])]
    else:
        results = joblib.Parallel(n_jobs=n_jobs, prefer="threads")(
            joblib.delayed(_process_column)(vals, mask) for vals, mask in col_data
        )

    # Assemble output arrays into DataFrames
    desired_arr = np.column_stack([r[0] for r in results])
    pred_return_arr = np.column_stack([r[1] for r in results])
    target_arr = np.column_stack([r[2] for r in results])

    desired = pd.DataFrame(desired_arr, index=raw.index, columns=raw.columns, dtype=float)
    predicted_return_frame = pd.DataFrame(pred_return_arr, index=raw.index, columns=raw.columns, dtype=float)
    scaled_target_frame = pd.DataFrame(target_arr, index=raw.index, columns=raw.columns, dtype=float)

    indicator_frame = _build_indicator_frame(
        was_series=was_series,
        components={
            "predicted_return": predicted_return_frame,
            "scaled_target": scaled_target_frame,
        },
    )
    return _finalize_signal_result(
        raw_input=raw_series,
        raw_frame=raw,
        indicator_frame=indicator_frame,
        desired_frame=desired,
        was_series=was_series,
    )


def _numba_cross_spread_features(
    values: np.ndarray,
    short_spans: np.ndarray,
    long_spans: np.ndarray,
) -> np.ndarray:
    """Compute cross-spread features using numba-accelerated EWM.

    Returns an ``(n, len(long_spans) * len(short_spans))`` array.
    """
    n = len(values)
    n_short = len(short_spans)
    n_long = len(long_spans)

    # Compute all EWMs in one pass via numba
    all_spans = np.concatenate([short_spans, long_spans])
    ewm_matrix = _numba_ewm_batch(values, all_spans)

    short_ewms = ewm_matrix[:, :n_short]
    long_ewms = ewm_matrix[:, n_short:]

    # Cross-spreads: long[i] - short[j] for all (i, j)
    out = np.empty((n, n_long * n_short), dtype=np.float64)
    col = 0
    for i in range(n_long):
        for j in range(n_short):
            out[:, col] = long_ewms[:, i] - short_ewms[:, j]
            col += 1
    return out


try:
    from numba import njit as _njit

    @_njit(cache=True)
    def _numba_ewm_batch(values: np.ndarray, spans: np.ndarray) -> np.ndarray:  # type: ignore[misc]
        """Compute EWM (adjust=False) for multiple spans in a single pass.

        Returns ``(len(values), len(spans))`` array.
        """
        n = len(values)
        k = len(spans)
        out = np.empty((n, k), dtype=np.float64)
        for j in range(k):
            alpha = 2.0 / (spans[j] + 1.0)
            out[0, j] = values[0]
            for i in range(1, n):
                out[i, j] = alpha * values[i] + (1.0 - alpha) * out[i - 1, j]
        return out

except ImportError:
    def _numba_ewm_batch(values: np.ndarray, spans: np.ndarray) -> np.ndarray:
        """Pure-numpy fallback when numba is unavailable."""
        n = len(values)
        k = len(spans)
        out = np.empty((n, k), dtype=np.float64)
        for j in range(k):
            alpha = 2.0 / (spans[j] + 1.0)
            out[0, j] = values[0]
            for i in range(1, n):
                out[i, j] = alpha * values[i] + (1.0 - alpha) * out[i - 1, j]
        return out


def _build_cross_spread_features(
    series: pd.Series,
    ewma_short_spans: Sequence[int],
    ewma_long_spans: Sequence[int],
) -> pd.DataFrame:
    """Build cross-spread features from the Matlab pfBBGHourlySVM pipeline.

    Only long-vs-short EMA differences (no EMA−SMA pairs).
    """
    features: dict[str, pd.Series] = {}
    ewma_short: dict[int, pd.Series] = {}
    ewma_long: dict[int, pd.Series] = {}

    for span in ewma_short_spans:
        ewma_short[span] = series.ewm(span=span, adjust=False).mean()

    for span in ewma_long_spans:
        ewma_long[span] = series.ewm(span=span, adjust=False).mean()

    for l_span in ewma_long_spans:
        for s_span in ewma_short_spans:
            features[f"cross_{l_span}_{s_span}"] = ewma_long[l_span] - ewma_short[s_span]

    return pd.DataFrame(features, index=series.index)


def _build_momentum_features(
    series: pd.Series,
    ewma_short_spans: Sequence[int],
    ewma_long_spans: Sequence[int],
) -> pd.DataFrame:
    """Build the MACD-style feature grid from the Matlab pfBBGDailySVM pipeline.

    Features:
    - ``EMA(span) - SMA(span)`` for each short span
    - ``EMA(span) - SMA(span)`` for each long span
    - ``EMA(long) - EMA(short)`` for every long/short combination
    """
    features: dict[str, pd.Series] = {}
    ewma_short: dict[int, pd.Series] = {}
    ewma_long: dict[int, pd.Series] = {}

    for span in ewma_short_spans:
        ew = series.ewm(span=span, adjust=False).mean()
        sm = series.rolling(window=span).mean()
        ewma_short[span] = ew
        features[f"ema_sma_short_{span}"] = ew - sm

    for span in ewma_long_spans:
        ew = series.ewm(span=span, adjust=False).mean()
        sm = series.rolling(window=span).mean()
        ewma_long[span] = ew
        features[f"ema_sma_long_{span}"] = ew - sm

    for l_span in ewma_long_spans:
        for s_span in ewma_short_spans:
            features[f"cross_{l_span}_{s_span}"] = ewma_long[l_span] - ewma_short[s_span]

    return pd.DataFrame(features, index=series.index)


def _backward_momentum_zscore(series: pd.Series, window: int) -> pd.Series:
    """Backward-looking z-scored momentum (Matlab: ``yMovAvg ./ yMovAvgStd * nOffset``)."""
    delta = series.diff()
    mov_avg = delta.rolling(window=window).mean()
    mov_std = delta.rolling(window=window).std()
    return mov_avg / mov_std.replace(0.0, np.nan) * window


def _tod_adjusted_momentum_zscore(
    series: pd.Series,
    window: int,
    lookback_days: int | None = None,
) -> pd.Series:
    """Momentum z-score with time-of-day volatility adjustment.

    Instead of a flat rolling std as the z-score denominator, this groups
    returns by time-of-day (hour:minute) and computes an expanding (or
    rolling by *lookback_days*) volatility for each bucket.  This prevents
    spuriously large z-scores during quiet sessions (e.g. Asian hours)
    and compressed z-scores during volatile sessions (e.g. US open).
    """
    delta = series.diff()
    mov_avg = delta.rolling(window=window).mean()

    # Build time-of-day key (HH:MM string to handle any bar frequency)
    tod_key = series.index.strftime("%H:%M")

    # Compute per-bar time-of-day volatility using expanding or rolling window
    tod_std = pd.Series(np.nan, index=series.index, dtype=float)

    for tod in np.unique(tod_key):
        mask = tod_key == tod
        tod_deltas = delta[mask]

        if lookback_days is None:
            # Expanding std over all history for this time-of-day bucket
            tod_std[mask] = tod_deltas.expanding(min_periods=5).std()
        else:
            # Rolling std using lookback_days worth of same-TOD observations
            tod_std[mask] = tod_deltas.rolling(
                window=lookback_days, min_periods=min(5, lookback_days)
            ).std()

    return mov_avg / tod_std.replace(0.0, np.nan) * window


def _coerce_numeric_input(raw_series: pd.Series | pd.DataFrame) -> tuple[pd.DataFrame, bool]:
    if isinstance(raw_series, pd.Series):
        column_name = str(raw_series.name or "value")
        series = pd.to_numeric(raw_series.sort_index(), errors="coerce")
        return series.to_frame(name=column_name), True
    if isinstance(raw_series, pd.DataFrame):
        frame = raw_series.sort_index().copy()
        for column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        return frame, False
    raise TypeError(f"Expected Series or DataFrame, got {type(raw_series)!r}")


def _empty_positions_like(frame: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(np.nan, index=frame.index, columns=frame.columns, dtype=float)


def _empty_indicator_like(frame: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(np.nan, index=frame.index, columns=frame.columns, dtype=float)


def _apply_series_indicator(
    frame: pd.DataFrame,
    indicator_fn: Any,
) -> pd.DataFrame:
    output = _empty_indicator_like(frame)
    for column in frame.columns:
        values = indicator_fn(frame[column])
        if values is None:
            continue
        output[column] = pd.to_numeric(pd.Series(values).reindex(frame.index), errors="coerce")
    return output


def _valid_observation_counts(frame: pd.DataFrame) -> pd.DataFrame:
    counts = frame.notna().astype(int)
    return counts.cumsum()


def _build_indicator_frame(
    *,
    was_series: bool,
    components: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    if was_series:
        return pd.DataFrame(
            {
                name: component.iloc[:, 0]
                for name, component in components.items()
            },
            index=next(iter(components.values())).index,
        )
    return pd.concat(components, axis=1)


def _restore_shape(frame: pd.DataFrame, *, was_series: bool, original: pd.Series | pd.DataFrame) -> pd.Series | pd.DataFrame:
    if not was_series:
        return frame
    column_name = str(original.name or frame.columns[0])
    restored = frame.iloc[:, 0].copy()
    restored.name = column_name
    return restored


def _finalize_signal_result(
    *,
    raw_input: pd.Series | pd.DataFrame,
    raw_frame: pd.DataFrame,
    indicator_frame: pd.DataFrame,
    desired_frame: pd.DataFrame,
    was_series: bool,
) -> TechnicalIndicatorSignalResult:
    execution_frame = desired_frame.shift(1)
    return TechnicalIndicatorSignalResult(
        raw_series=_restore_shape(raw_frame, was_series=was_series, original=raw_input),
        indicator_frame=indicator_frame,
        desired_position=_restore_shape(desired_frame, was_series=was_series, original=raw_input),
        execution_position=_restore_shape(execution_frame, was_series=was_series, original=raw_input),
    )
