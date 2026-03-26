"""Intraday PCA momentum pipeline for Q12 SOFR STIR swaps."""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence

import numpy as np
import pandas as pd
import pytz
from sklearn.decomposition import PCA
from sklearn.model_selection import GridSearchCV, TimeSeriesSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC

logger = logging.getLogger(__name__)

CHICAGO_TZ = pytz.timezone("America/Chicago")
DEFAULT_CONTRACT_LABELS = tuple(f"SFR{rank}" for rank in range(1, 13))


@dataclass
class PCAMomentumConfig:
    """Configuration for the Q12 SOFR PCA momentum signal."""

    source: str = "BARCHART_STIRF-RL"
    curve: str = "USD-SOFR-1D-Q12STIRT"
    contract_ranks: list[int] = field(default_factory=lambda: list(range(1, 13)))

    loader_freq: str = "1min"
    signal_bar_freq: str = "30min"
    n_jobs: int = 12

    ewma_short_spans: list[int] = field(default_factory=lambda: [48, 96, 240, 480])
    ewma_long_spans: list[int] = field(default_factory=lambda: [720, 2160, 2880])

    label_forward_window: int = 13
    label_volatility_window: int = 130
    label_z_threshold: float = 0.5

    train_window_sessions: int = 120
    retrain_every_sessions: int = 5
    cv_splits: int = 3
    n_components: int = 2
    svm_c_grid: list[float] = field(default_factory=lambda: [0.1, 1.0, 10.0])
    svm_gamma_grid: list[Any] = field(default_factory=lambda: ["scale", 0.1, 0.01])

    trade_bpv: float = 100_000.0
    transaction_cost_bps_per_side: float = 0.25


@dataclass
class PCAMomentumWalkForwardResult:
    """Walk-forward output aligned to the signal timestamps."""

    config: PCAMomentumConfig
    rate_panel: pd.DataFrame
    session_labels: pd.Series
    contract_to_tenor: dict[str, str]
    per_contract: dict[str, pd.DataFrame]
    signal_panel: pd.DataFrame
    decision_score_panel: pd.DataFrame
    target_zscore_panel: pd.DataFrame
    label_panel: pd.DataFrame


def build_rank_tenor_map(contract_ranks: Optional[Sequence[int]] = None) -> dict[str, str]:
    """Map SFR rank labels to IMM outrights on the Q12 SOFR curve."""
    ranks = list(contract_ranks or range(1, 13))
    return {f"SFR{rank}": f"IMM_{rank}xIMM_{rank + 1}" for rank in ranks}


def build_intraday_rate_queries(config: PCAMomentumConfig):
    """Build cache-friendly IR swap rate queries for the configured SFR ranks."""
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapValue import IRSwapValue

    queries = []
    for tenor in build_rank_tenor_map(config.contract_ranks).values():
        queries.append(
            IRSwapQuery(
                curve=config.curve,
                tenor=tenor,
                value=IRSwapValue.RATE,
            )
        )
    return queries


def load_intraday_rate_panel(
    start: dt.datetime,
    end: dt.datetime,
    config: PCAMomentumConfig,
    *,
    ts_builder=None,
    curve_mdp=None,
    show_tqdm: bool = True,
) -> pd.DataFrame:
    """Load and optionally resample the configured SOFR rank panel."""
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from TB.IRSwapsTB import IRSwapsTB
    from TB.TimeseriesBuilder import TimeseriesBuilder

    if ts_builder is None:
        ts_builder = TimeseriesBuilder()
    if curve_mdp is None:
        curve_mdp = IRSwapsMDP(source=config.source)

    queries = build_intraday_rate_queries(config)
    panel = ts_builder.get_timeseries(
        start=start,
        end=end,
        queries=queries,
        freq=config.loader_freq,
        n_jobs=config.n_jobs,
        routers={"IRS": IRSwapsTB(curve_mdp, show_tqdm=show_tqdm)},
    )
    panel = panel.sort_index()
    rename_map = _build_intraday_column_rename_map(panel.columns, config)
    panel = panel.rename(columns=rename_map)
    desired_columns = list(build_rank_tenor_map(config.contract_ranks))
    panel = panel.reindex(columns=desired_columns)
    for column in panel.columns:
        panel[column] = pd.to_numeric(panel[column], errors="coerce")

    if config.signal_bar_freq and config.signal_bar_freq != config.loader_freq:
        panel = panel.resample(config.signal_bar_freq).last()

    panel = panel.dropna(how="all")
    return panel.astype(float)


def generate_ma_features(
    rate_series: pd.Series,
    ewma_short_spans: Sequence[int],
    ewma_long_spans: Sequence[int],
) -> pd.DataFrame:
    """Generate the MACD-style feature grid used by the PCA model."""
    features: dict[str, pd.Series] = {}
    ewma_cache_short: dict[int, pd.Series] = {}
    ewma_cache_long: dict[int, pd.Series] = {}

    for span in ewma_short_spans:
        ewma = rate_series.ewm(span=span, adjust=False).mean()
        sma = rate_series.rolling(window=span).mean()
        ewma_cache_short[span] = ewma
        features[f"ewma_minus_sma_short_{span}"] = ewma - sma

    for span in ewma_long_spans:
        ewma = rate_series.ewm(span=span, adjust=False).mean()
        sma = rate_series.rolling(window=span).mean()
        ewma_cache_long[span] = ewma
        features[f"ewma_minus_sma_long_{span}"] = ewma - sma

    for long_span in ewma_long_spans:
        for short_span in ewma_short_spans:
            features[f"ewma_cross_{long_span}_{short_span}"] = (
                ewma_cache_long[long_span] - ewma_cache_short[short_span]
            )

    return pd.DataFrame(features, index=rate_series.index)


def compute_forward_return_zscore(
    rate_series: pd.Series,
    *,
    forward_window: int,
    volatility_window: int,
) -> pd.Series:
    """Compute the forward mean return scaled by trailing realized volatility."""
    delta = rate_series.diff()
    future_mean = pd.concat(
        [delta.shift(-step) for step in range(1, forward_window + 1)],
        axis=1,
    ).mean(axis=1)
    trailing_vol = delta.rolling(volatility_window).std()
    return future_mean / trailing_vol.replace(0.0, np.nan)


def generate_labels(target_zscore: pd.Series, *, z_threshold: float) -> pd.Series:
    """Bucket the target z-score into {-1, 0, +1}."""
    labels = pd.Series(np.nan, index=target_zscore.index, dtype=float)
    valid = target_zscore.notna()
    labels.loc[valid & (target_zscore > z_threshold)] = 1.0
    labels.loc[valid & (target_zscore < -z_threshold)] = -1.0
    labels.loc[valid & (target_zscore.abs() <= z_threshold)] = 0.0
    return labels


def build_pipeline(*, n_components: int, classifier_c: float, classifier_gamma: Any) -> Pipeline:
    """Construct the scaled PCA plus RBF SVM classifier."""
    return Pipeline(
        steps=[
            ("scaler", StandardScaler()),
            ("pca", PCA(n_components=n_components)),
            (
                "clf",
                SVC(
                    kernel="rbf",
                    C=classifier_c,
                    gamma=classifier_gamma,
                    class_weight="balanced",
                    probability=True,
                ),
            ),
        ]
    )


def walk_forward_pca_momentum(
    rate_panel: pd.DataFrame,
    config: Optional[PCAMomentumConfig] = None,
) -> PCAMomentumWalkForwardResult:
    """Run the non-leaky walk-forward PCA momentum model per SFR rank."""
    cfg = config or PCAMomentumConfig()
    rate_panel = rate_panel.sort_index().copy()
    session_labels = pd.Series(
        [_cme_trading_session_label(ts) for ts in rate_panel.index],
        index=rate_panel.index,
        name="session",
    )

    per_contract: dict[str, pd.DataFrame] = {}
    signal_panel = pd.DataFrame(index=rate_panel.index)
    decision_panel = pd.DataFrame(index=rate_panel.index)
    zscore_panel = pd.DataFrame(index=rate_panel.index)
    label_panel = pd.DataFrame(index=rate_panel.index)

    for contract in rate_panel.columns:
        contract_frame = _walk_forward_contract(
            rate_series=rate_panel[contract],
            session_labels=session_labels,
            config=cfg,
        )
        per_contract[contract] = contract_frame
        signal_panel[contract] = contract_frame["prediction"]
        decision_panel[contract] = contract_frame["decision_score"]
        zscore_panel[contract] = contract_frame["target_zscore"]
        label_panel[contract] = contract_frame["label"]

    return PCAMomentumWalkForwardResult(
        config=cfg,
        rate_panel=rate_panel,
        session_labels=session_labels,
        contract_to_tenor=build_rank_tenor_map(cfg.contract_ranks),
        per_contract=per_contract,
        signal_panel=signal_panel,
        decision_score_panel=decision_panel,
        target_zscore_panel=zscore_panel,
        label_panel=label_panel,
    )


def fit_pca_momentum(
    rate_series: pd.Series,
    config: Optional[PCAMomentumConfig] = None,
) -> pd.DataFrame:
    """Convenience wrapper for single-contract walk-forward fitting."""
    cfg = config or PCAMomentumConfig(contract_ranks=[1])
    series = rate_series.sort_index()
    session_labels = pd.Series(
        [_cme_trading_session_label(ts) for ts in series.index],
        index=series.index,
        name="session",
    )
    return _walk_forward_contract(rate_series=series, session_labels=session_labels, config=cfg)


def predict_signals(result: PCAMomentumWalkForwardResult | pd.DataFrame) -> pd.Series | pd.DataFrame:
    """Extract predictions from a walk-forward result."""
    if isinstance(result, PCAMomentumWalkForwardResult):
        return result.signal_panel.copy()
    return result["prediction"].copy()


def extract_pca_components(contract_frame: pd.DataFrame) -> pd.DataFrame:
    """Extract stored PCA component columns if present."""
    columns = [column for column in contract_frame.columns if column.startswith("pc_")]
    return contract_frame[columns].copy()


def _walk_forward_contract(
    *,
    rate_series: pd.Series,
    session_labels: pd.Series,
    config: PCAMomentumConfig,
) -> pd.DataFrame:
    features = generate_ma_features(
        rate_series=rate_series,
        ewma_short_spans=config.ewma_short_spans,
        ewma_long_spans=config.ewma_long_spans,
    )
    target_zscore = compute_forward_return_zscore(
        rate_series,
        forward_window=config.label_forward_window,
        volatility_window=config.label_volatility_window,
    )
    labels = generate_labels(target_zscore, z_threshold=config.label_z_threshold)

    result = features.copy()
    result["rate"] = rate_series
    result["target_zscore"] = target_zscore
    result["label"] = labels
    result["prediction"] = np.nan
    result["decision_score"] = np.nan
    result["model_c"] = pd.Series(index=result.index, dtype="object")
    result["model_gamma"] = pd.Series(index=result.index, dtype="object")
    result["train_session_start"] = pd.Series(index=result.index, dtype="object")
    result["train_session_end"] = pd.Series(index=result.index, dtype="object")
    result["predict_session_start"] = pd.Series(index=result.index, dtype="object")
    result["predict_session_end"] = pd.Series(index=result.index, dtype="object")
    result["model_kind"] = pd.Series(index=result.index, dtype="object")
    for component in range(1, config.n_components + 1):
        result[f"pc_{component}"] = np.nan

    unique_sessions = pd.Index(dict.fromkeys(session_labels.tolist()))
    if len(unique_sessions) <= config.train_window_sessions:
        return result

    feature_mask = features.notna().all(axis=1)
    block_width = max(1, int(config.retrain_every_sessions))
    for block_start in range(config.train_window_sessions, len(unique_sessions), block_width):
        train_sessions = unique_sessions[block_start - config.train_window_sessions : block_start]
        predict_sessions = unique_sessions[block_start : min(len(unique_sessions), block_start + block_width)]
        if len(predict_sessions) == 0:
            continue

        train_mask = session_labels.isin(train_sessions)
        predict_mask = session_labels.isin(predict_sessions)
        valid_train = train_mask & feature_mask & labels.notna()
        valid_predict = predict_mask & feature_mask
        if not valid_predict.any():
            continue

        block_meta = {
            "train_session_start": train_sessions[0],
            "train_session_end": train_sessions[-1],
            "predict_session_start": predict_sessions[0],
            "predict_session_end": predict_sessions[-1],
        }

        X_train = features.loc[valid_train]
        y_train = labels.loc[valid_train].astype(int)
        if X_train.empty or y_train.empty:
            continue

        model_bundle = _fit_model_block(X_train, y_train, config)
        X_predict = features.loc[valid_predict]
        prediction_frame = _predict_block(model_bundle, X_predict)

        result.loc[valid_predict, "prediction"] = prediction_frame["prediction"]
        result.loc[valid_predict, "decision_score"] = prediction_frame["decision_score"]
        for component in range(1, config.n_components + 1):
            column = f"pc_{component}"
            if column in prediction_frame:
                result.loc[valid_predict, column] = prediction_frame[column]
        result.loc[valid_predict, "model_c"] = model_bundle["c"]
        result.loc[valid_predict, "model_gamma"] = model_bundle["gamma"]
        result.loc[valid_predict, "model_kind"] = model_bundle["kind"]
        for key, value in block_meta.items():
            result.loc[valid_predict, key] = value

    return result


def _fit_model_block(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    config: PCAMomentumConfig,
) -> dict[str, Any]:
    unique_labels = sorted(set(int(value) for value in y_train.tolist()))
    if len(unique_labels) == 1:
        label = unique_labels[0]
        return {
            "kind": "constant",
            "constant_label": label,
            "model": None,
            "c": None,
            "gamma": None,
        }

    max_components = min(config.n_components, X_train.shape[1], len(X_train))
    if max_components <= 0:
        label = int(y_train.mode(dropna=True).iloc[0])
        return {
            "kind": "constant",
            "constant_label": label,
            "model": None,
            "c": None,
            "gamma": None,
        }

    n_splits = min(config.cv_splits, max(1, len(X_train) - 1))
    if n_splits < 2:
        pipeline = build_pipeline(
            n_components=max_components,
            classifier_c=config.svm_c_grid[0],
            classifier_gamma=config.svm_gamma_grid[0],
        )
        pipeline.fit(X_train, y_train)
        return {
            "kind": "svm",
            "constant_label": None,
            "model": pipeline,
            "c": config.svm_c_grid[0],
            "gamma": config.svm_gamma_grid[0],
        }

    grid = GridSearchCV(
        estimator=build_pipeline(
            n_components=max_components,
            classifier_c=config.svm_c_grid[0],
            classifier_gamma=config.svm_gamma_grid[0],
        ),
        param_grid={
            "clf__C": list(config.svm_c_grid),
            "clf__gamma": list(config.svm_gamma_grid),
        },
        cv=TimeSeriesSplit(n_splits=n_splits),
        scoring="accuracy",
        n_jobs=1,
        refit=True,
        error_score="raise",
    )

    try:
        grid.fit(X_train, y_train)
        best_model = grid.best_estimator_
        best_c = grid.best_params_["clf__C"]
        best_gamma = grid.best_params_["clf__gamma"]
    except Exception as exc:
        logger.debug("Grid search failed, using direct fit fallback: %s", exc)
        best_c = config.svm_c_grid[0]
        best_gamma = config.svm_gamma_grid[0]
        best_model = build_pipeline(
            n_components=max_components,
            classifier_c=best_c,
            classifier_gamma=best_gamma,
        )
        best_model.fit(X_train, y_train)

    return {
        "kind": "svm",
        "constant_label": None,
        "model": best_model,
        "c": best_c,
        "gamma": best_gamma,
    }


def _predict_block(model_bundle: Mapping[str, Any], X_predict: pd.DataFrame) -> pd.DataFrame:
    if model_bundle["kind"] == "constant":
        label = float(model_bundle["constant_label"])
        return pd.DataFrame(
            {
                "prediction": pd.Series(label, index=X_predict.index, dtype=float),
                "decision_score": pd.Series(label, index=X_predict.index, dtype=float),
            }
        )

    model = model_bundle["model"]
    predictions = pd.Series(model.predict(X_predict), index=X_predict.index, dtype=float)
    probabilities = model.predict_proba(X_predict)
    X_scaled = model.named_steps["scaler"].transform(X_predict)
    X_pca = model.named_steps["pca"].transform(X_scaled)
    classes = [int(value) for value in model.classes_]
    class_to_idx = {label: idx for idx, label in enumerate(classes)}
    prob_up = probabilities[:, class_to_idx.get(1, -1)] if 1 in class_to_idx else np.zeros(len(X_predict))
    prob_down = probabilities[:, class_to_idx.get(-1, -1)] if -1 in class_to_idx else np.zeros(len(X_predict))
    decision_score = pd.Series(prob_up - prob_down, index=X_predict.index, dtype=float)
    output = pd.DataFrame({"prediction": predictions, "decision_score": decision_score})
    for component in range(X_pca.shape[1]):
        output[f"pc_{component + 1}"] = X_pca[:, component]
    return output


def _cme_trading_session_label(timestamp: Any) -> dt.date:
    stamp = pd.Timestamp(timestamp)
    if stamp.tzinfo is None:
        return stamp.date()
    chi_stamp = stamp.tz_convert(CHICAGO_TZ)
    if chi_stamp.hour >= 17:
        return (chi_stamp + pd.Timedelta(days=1)).date()
    return chi_stamp.date()


def _build_intraday_column_rename_map(
    columns: Iterable[Any],
    config: PCAMomentumConfig,
) -> dict[str, str]:
    tenor_map = build_rank_tenor_map(config.contract_ranks)
    remaining = [str(column) for column in columns]
    rename_map: dict[str, str] = {}

    for label, tenor in tenor_map.items():
        exact_candidates = [
            text for text in remaining
            if tenor in text and "RATE" in text.upper()
        ]
        if not exact_candidates:
            continue

        chosen = None
        for candidate in exact_candidates:
            if candidate.startswith("USD-SOFR-1D "):
                chosen = candidate
                break
        if chosen is None:
            for candidate in exact_candidates:
                if candidate.startswith(f"{config.curve} "):
                    chosen = candidate
                    break
        if chosen is None:
            chosen = exact_candidates[0]

        rename_map[chosen] = label
        remaining.remove(chosen)

    return rename_map
