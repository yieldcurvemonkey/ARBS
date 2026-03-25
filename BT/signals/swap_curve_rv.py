"""Reusable research helpers for USD SOFR swap-curve RV studies."""

from __future__ import annotations

import copy
import datetime as dt
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import pytz

from BT.signals.pca_rv_engine import PCARVConfig, rolling_pca, pca_fly_weights, adf_test, ou_half_life, ou_params
from BT.signals.regime_filter import RegimeFilterConfig, traffic_light
from BT.signals.regression_rv import RegressionRVConfig, rolling_regression
from BT.signals.rv_backtest import RVBacktestConfig, RVQueryBacktestResult, run_query_rv_backtest
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapStructure import IRSwapStructure
from Query.IRSwaps.IRSwapValue import IRSwapValue
from TB.TimeseriesBuilder import TimeseriesBuilder


DEFAULT_DATA_START = dt.date(2021, 1, 4)
DEFAULT_SOURCE = "ERIS_EOD_LIVE-RL_BASIC"
DEFAULT_CURVE = "USD-SOFR-1D"


@dataclass(frozen=True)
class FlyDefinition:
    left: str
    belly: str
    right: str
    category: str

    @property
    def fly_id(self) -> str:
        return f"{self.left}/{self.belly}/{self.right}"

    @property
    def legs(self) -> Tuple[str, str, str]:
        return (self.left, self.belly, self.right)


@dataclass
class CurveDataset:
    source: str
    curve_name: str
    mdp: IRSwapsMDP
    dates: pd.DatetimeIndex
    curves_by_date: Dict[pd.Timestamp, Any]
    rate_panel: pd.DataFrame
    surface_panel: pd.DataFrame
    surface_token_map: Dict[str, Tuple[str, str]]
    trade_universe: List[FlyDefinition]


@dataclass
class SignalBundle:
    fly_definitions: List[FlyDefinition]
    residuals: Dict[str, pd.Series]
    residual_stats: Dict[str, pd.DataFrame]
    zscores: Dict[str, pd.Series]
    fit_quality: Dict[str, pd.Series]
    weights: Dict[str, pd.DataFrame]
    rate_triplets: Dict[str, pd.DataFrame]
    entry_snapshots: Dict[str, Dict[pd.Timestamp, Any]]
    carry_bp: Dict[str, pd.Series]
    roll_bp: Dict[str, pd.Series]
    carry_roll_bp: Dict[str, pd.Series]
    stationarity_pvalues: Dict[str, pd.Series]
    stationarity_half_lives: Dict[str, pd.Series]
    regime: pd.Series
    regime_details: pd.DataFrame
    reference_betas: pd.DataFrame
    surface_residuals: pd.DataFrame
    surface_zscores: pd.DataFrame
    surface_fit_quality: pd.Series

    @property
    def fly_categories(self) -> Dict[str, str]:
        return {fly.fly_id: fly.category for fly in self.fly_definitions}


@dataclass
class StudyResult:
    dataset: CurveDataset
    signals: SignalBundle
    backtest: RVQueryBacktestResult


@dataclass
class SurfaceSnapshot:
    as_of: pd.Timestamp
    actual: pd.DataFrame
    residual: pd.DataFrame
    zscore: pd.DataFrame
    carry_bp: pd.DataFrame
    roll_bp: pd.DataFrame
    carry_roll_bp: pd.DataFrame


@dataclass
class TwoStageTradeAnalytics:
    fly_id: str
    as_of: pd.Timestamp
    weights: pd.Series
    stage1_residual_bp: float
    stage1_zscore: float
    stage1_fit_quality: float
    pc_loadings: pd.DataFrame
    pc_exposures: pd.Series
    pca_fly_series: pd.Series
    fly_5050_series: pd.Series
    level_series: pd.Series
    slope_series: pd.Series
    correlations: pd.Series
    adf: Dict[str, float]
    ou: Dict[str, float]
    current_level: float
    target_level: float
    stop_level: float
    current_ou_zscore: float
    carry_bp: float
    roll_bp: float
    carry_roll_bp: float
    expected_profit_bp: float
    passes_cost_filter: bool


def _canonical_token(token: Any) -> str:
    text = str(token).strip().upper().replace(" ", "")
    match = re.fullmatch(r"(\d+[DWMY])X(\d+[DWMY])", text)
    if match:
        return f"{match.group(1)}x{match.group(2)}"
    return text


def tenor_to_months(token: Any) -> int:
    text = str(token).strip().upper().replace(" ", "")
    match = re.fullmatch(r"(\d+)([DWMY])", text)
    if not match:
        raise ValueError(f"Unsupported tenor token '{token}'")
    value = int(match.group(1))
    unit = match.group(2)
    if unit == "Y":
        return value * 12
    if unit == "M":
        return value
    if unit == "W":
        return int(round(value * 12 / 52))
    return max(1, int(round(value * 12 / 365)))


def months_to_tenor(months: int) -> str:
    months = int(months)
    if months <= 0:
        raise ValueError(f"Tenor months must be positive, got {months}")
    if months % 12 == 0:
        return f"{months // 12}Y"
    return f"{months}M"


def split_surface_token(token: Any) -> Tuple[str, str]:
    norm = _canonical_token(token)
    if "x" in norm:
        swap_tenor, forward_start = norm.split("x", 1)
        return swap_tenor, forward_start
    return norm, "Spot"


def format_surface_token(swap_tenor: Any, forward_start: Any = "Spot") -> str:
    swap_label = months_to_tenor(tenor_to_months(swap_tenor)) if not re.fullmatch(r"\d+[DWMY]", str(swap_tenor).strip().upper()) else str(swap_tenor).strip().upper()
    fwd_text = str(forward_start).strip().upper().replace(" ", "")
    if fwd_text in {"SPOT", "0D", "0"}:
        return swap_label
    fwd_label = months_to_tenor(tenor_to_months(fwd_text)) if not re.fullmatch(r"\d+[DWMY]", fwd_text) else fwd_text
    return _canonical_token(f"{swap_label}X{fwd_label}")


def shift_surface_token(token: Any, *, swap_months_delta: int = 0, forward_months_delta: int = 0) -> str:
    swap_tenor, forward_start = split_surface_token(token)
    swap_months = tenor_to_months(swap_tenor) + int(swap_months_delta)
    forward_months = 0 if forward_start == "Spot" else tenor_to_months(forward_start)
    forward_months += int(forward_months_delta)
    forward_label = "Spot" if forward_months <= 0 else months_to_tenor(forward_months)
    return format_surface_token(months_to_tenor(swap_months), forward_label)


def _as_date(value: Any) -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, dt.date):
        return value
    return pd.Timestamp(value).date()


def _data_cfg(config: Mapping[str, Any]) -> Mapping[str, Any]:
    out = dict(config.get("data", {}))
    if "start" not in out and "data_start" in config:
        out["start"] = config["data_start"]
    if "end" not in out and "data_end" in config:
        out["end"] = config["data_end"]
    if "curve_name" not in out and "curve_name" in config:
        out["curve_name"] = config["curve_name"]
    if "source" not in out and "source" in config:
        out["source"] = config["source"]
    return out


def _surface_cfg(config: Mapping[str, Any]) -> Mapping[str, Any]:
    out = dict(config.get("surface", {}))
    if "swap_tenors" not in out and "tenors_spot" in config:
        out["swap_tenors"] = config["tenors_spot"]
    if "forward_starts" not in out and "forward_tails" in config:
        out["forward_starts"] = config["forward_tails"]
    if "fly_categories" not in out and "fly_categories" in config:
        out["fly_categories"] = config["fly_categories"]
    if "enabled_categories" not in out and "enabled_categories" in config:
        out["enabled_categories"] = config["enabled_categories"]
    if "custom_tokens" not in out and "custom_tokens" in config:
        out["custom_tokens"] = config["custom_tokens"]
    if "include_forward_fly_variants" not in out and "include_forward_fly_variants" in config:
        out["include_forward_fly_variants"] = config["include_forward_fly_variants"]
    if "auto_forward_from_categories" not in out and "auto_forward_from_categories" in config:
        out["auto_forward_from_categories"] = config["auto_forward_from_categories"]
    return out


def _signal_cfg(config: Mapping[str, Any]) -> Mapping[str, Any]:
    out = dict(config.get("signal", {}))
    if "pca_window_days" not in out and "window_days" in config:
        out["pca_window_days"] = config["window_days"]
    if "zscore_lookback_days" not in out and "zscore_lookback_days" in config:
        out["zscore_lookback_days"] = config["zscore_lookback_days"]
    if "n_components" not in out and "n_components" in config:
        out["n_components"] = config["n_components"]
    return out


def _stationarity_cfg(config: Mapping[str, Any]) -> Mapping[str, Any]:
    out = dict(config.get("stationarity", {}))
    if "enabled" not in out and "stationarity_filter_enabled" in config:
        out["enabled"] = config["stationarity_filter_enabled"]
    return out


def _entry_cfg(config: Mapping[str, Any]) -> Mapping[str, Any]:
    out = dict(config.get("entry", {}))
    if "min_rsq" not in out and "entry_min_rsq" in config:
        out["min_rsq"] = config["entry_min_rsq"]
    if "min_fit" not in out and "entry_min_rsq" in config:
        out["min_fit"] = config["entry_min_rsq"]
    if "min_residual_bp" not in out and "entry_min_residual_bp" in config:
        out["min_residual_bp"] = config["entry_min_residual_bp"]
    if "min_zscore" not in out and "entry_min_zscore" in config:
        out["min_zscore"] = config["entry_min_zscore"]
    return out


def _exit_cfg(config: Mapping[str, Any]) -> Mapping[str, Any]:
    out = dict(config.get("exit", {}))
    if "mean_reversion" not in out and "exit_mean_reversion" in config:
        out["mean_reversion"] = config["exit_mean_reversion"]
    if "stop_loss_sd" not in out and "exit_stop_loss_sd" in config:
        out["stop_loss_sd"] = config["exit_stop_loss_sd"]
    if "max_holding_days" not in out and "exit_max_holding_days" in config:
        out["max_holding_days"] = config["exit_max_holding_days"]
    if "carry_adjusted" not in out and "exit_carry_adjusted" in config:
        out["carry_adjusted"] = config["exit_carry_adjusted"]
    return out


def _regime_cfg(config: Mapping[str, Any]) -> Mapping[str, Any]:
    out = dict(config.get("regime", {}))
    if "reference_fly" not in out and "regime_reference_fly" in config:
        out["reference_fly"] = config["regime_reference_fly"]
    if "beta_vol_window_days" not in out and "beta_vol_window_days" in config:
        out["beta_vol_window_days"] = config["beta_vol_window_days"]
    if "beta_vol_zscore_window_days" not in out and "beta_vol_zscore_window_days" in config:
        out["beta_vol_zscore_window_days"] = config["beta_vol_zscore_window_days"]
    if "threshold" not in out and "regime_threshold" in config:
        out["threshold"] = config["regime_threshold"]
    return out


def _portfolio_cfg(config: Mapping[str, Any]) -> Mapping[str, Any]:
    out = dict(config.get("portfolio", {}))
    if "max_concurrent_trades" not in out and "max_concurrent_trades" in config:
        out["max_concurrent_trades"] = config["max_concurrent_trades"]
    if "no_duplicate_flies" not in out and "no_duplicate_flies" in config:
        out["no_duplicate_flies"] = config["no_duplicate_flies"]
    if "reentry_after_stop" not in out and "reentry_after_stop" in config:
        out["reentry_after_stop"] = config["reentry_after_stop"]
    return out


def _costs_cfg(config: Mapping[str, Any]) -> Mapping[str, Any]:
    out = dict(config.get("costs", {}))
    if "round_trip_cost_bp" not in out and "round_trip_cost_bp" in config:
        out["round_trip_cost_bp"] = config["round_trip_cost_bp"]
    if "min_profit_to_cost_ratio" not in out and "min_profit_to_cost_ratio" in config:
        out["min_profit_to_cost_ratio"] = config["min_profit_to_cost_ratio"]
    return out


def _normalized_forward_starts(surface_cfg: Mapping[str, Any]) -> List[str]:
    starts = surface_cfg.get("forward_starts", ["Spot", "1Y", "2Y", "5Y"])
    out: List[str] = []
    seen: set[str] = set()
    for value in starts:
        text = str(value).strip().upper().replace(" ", "")
        norm = "Spot" if text in {"SPOT", "0D", "0"} else _canonical_token(text)
        if norm in seen:
            continue
        seen.add(norm)
        out.append(norm)
    return out


def _is_plain_swap_tenor(token: Any) -> bool:
    return re.fullmatch(r"\d+[DWMY]", _canonical_token(token)) is not None


def _forward_category_name(category: str) -> str:
    if category.endswith("_spot"):
        return f"{category[:-5]}_fwd"
    if category.endswith("spot"):
        return f"{category[:-4]}fwd"
    return f"{category}_fwd"


def _expand_forward_fly_categories(surface_cfg: Mapping[str, Any], fly_categories: Mapping[str, Sequence[Sequence[str]]]) -> Dict[str, List[Tuple[str, str, str]]]:
    expanded: Dict[str, List[Tuple[str, str, str]]] = {
        str(category): [tuple(_canonical_token(token) for token in tuple(fly)) for fly in flies]
        for category, flies in fly_categories.items()
    }
    if not bool(surface_cfg.get("include_forward_fly_variants", False)):
        return expanded

    forward_starts = [start for start in _normalized_forward_starts(surface_cfg) if start != "Spot"]
    if not forward_starts:
        return expanded

    selected_categories = surface_cfg.get("auto_forward_from_categories")
    if selected_categories in (None, True):
        base_categories = list(fly_categories)
    elif selected_categories in (False, []):
        base_categories = []
    elif isinstance(selected_categories, str):
        base_categories = [selected_categories]
    else:
        base_categories = [str(category) for category in selected_categories]

    for base_category in base_categories:
        base_flies = fly_categories.get(base_category, [])
        if not base_flies:
            continue
        forward_category = _forward_category_name(str(base_category))
        generated = expanded.setdefault(forward_category, [])
        seen = {tuple(fly) for fly in generated}
        for forward_start in forward_starts:
            for fly in base_flies:
                norm_fly = tuple(_canonical_token(token) for token in tuple(fly))
                if not all(_is_plain_swap_tenor(token) for token in norm_fly):
                    continue
                forward_fly = tuple(_canonical_token(f"{token}x{forward_start}") for token in norm_fly)
                if forward_fly in seen:
                    continue
                seen.add(forward_fly)
                generated.append(forward_fly)

    return expanded


def build_trade_universe(config: Mapping[str, Any]) -> List[FlyDefinition]:
    surface_cfg = _surface_cfg(config)
    raw_categories = dict(surface_cfg.get("fly_categories", {}))
    fly_categories = _expand_forward_fly_categories(surface_cfg, raw_categories)

    enabled_cfg = surface_cfg.get("enabled_categories")
    if enabled_cfg:
        enabled = [str(category) for category in enabled_cfg]
    else:
        enabled = list(fly_categories)

    if bool(surface_cfg.get("include_forward_fly_variants", False)):
        selected_categories = surface_cfg.get("auto_forward_from_categories")
        if selected_categories in (None, True):
            base_categories = list(raw_categories)
        elif selected_categories in (False, []):
            base_categories = []
        elif isinstance(selected_categories, str):
            base_categories = [selected_categories]
        else:
            base_categories = [str(category) for category in selected_categories]
        for base_category in base_categories:
            forward_category = _forward_category_name(str(base_category))
            if forward_category in fly_categories and base_category in enabled and forward_category not in enabled:
                enabled.append(forward_category)

    universe: List[FlyDefinition] = []
    seen: set[str] = set()
    for category in enabled:
        for fly in fly_categories.get(category, []):
            left, belly, right = (_canonical_token(token) for token in tuple(fly))
            definition = FlyDefinition(left=left, belly=belly, right=right, category=category)
            if definition.fly_id in seen:
                continue
            seen.add(definition.fly_id)
            universe.append(definition)
    return universe


def _surface_tokens(config: Mapping[str, Any]) -> Tuple[List[str], Dict[str, Tuple[str, str]]]:
    surface_cfg = _surface_cfg(config)
    forward_starts = list(surface_cfg.get("forward_starts", ["Spot", "1Y", "2Y", "5Y"]))
    swap_tenors = list(surface_cfg.get("swap_tenors", surface_cfg.get("spot_tenors", [])))

    tokens: List[str] = []
    mapping: Dict[str, Tuple[str, str]] = {}
    for fwd in forward_starts:
        fwd_label = "Spot" if str(fwd).strip().upper() in {"SPOT", "0D", "0"} else str(fwd).upper()
        for swap in swap_tenors:
            swap_label = str(swap).upper()
            token = swap_label if fwd_label == "Spot" else _canonical_token(f"{swap_label}X{fwd_label}")
            tokens.append(token)
            mapping[token] = (swap_label, fwd_label)
    return tokens, mapping


def _unique_required_tokens(config: Mapping[str, Any], universe: Sequence[FlyDefinition]) -> Tuple[List[str], Dict[str, Tuple[str, str]]]:
    surface_tokens, surface_map = _surface_tokens(config)
    required = list(surface_tokens)
    for fly in universe:
        required.extend(list(fly.legs))

    regime_reference = _regime_cfg(config).get("reference_fly")
    if regime_reference:
        required.extend(list(regime_reference))

    required.extend(list(_surface_cfg(config).get("custom_tokens", [])))
    unique = []
    seen = set()
    for token in required:
        norm = _canonical_token(token)
        if norm not in seen:
            seen.add(norm)
            unique.append(norm)
    return unique, surface_map


def build_rate_queries(config: Mapping[str, Any], required_tokens: Sequence[str], curve_name: str) -> List[IRSwapQuery]:
    queries: List[IRSwapQuery] = []
    seen: set[str] = set()
    for token in required_tokens:
        norm = _canonical_token(token)
        if norm in seen:
            continue
        seen.add(norm)
        queries.append(
            IRSwapQuery(
                curve=curve_name,
                tenor=norm,
                value=IRSwapValue.RATE,
                name=norm,
            )
        )
    return queries


def _history_bounds(config: Mapping[str, Any]) -> Tuple[dt.datetime, dt.datetime]:
    data_cfg = _data_cfg(config)
    start_raw = data_cfg.get("start", data_cfg.get("data_start", DEFAULT_DATA_START))
    end_raw = data_cfg.get("end", data_cfg.get("data_end", dt.date.today()))
    start_date = _as_date(start_raw)
    end_date = _as_date(end_raw)
    tz_name = str(data_cfg.get("timezone", "America/New_York"))
    tz = pytz.timezone(tz_name)
    start_dt = tz.localize(dt.datetime(start_date.year, start_date.month, start_date.day, 17, 0))
    end_dt = tz.localize(dt.datetime(end_date.year, end_date.month, end_date.day, 17, 0))
    return start_dt, end_dt


def load_rate_timeseries(
    config: Mapping[str, Any],
    curve_mdp: IRSwapsMDP,
    ts_builder: Optional[TimeseriesBuilder] = None,
    *,
    required_tokens: Optional[Sequence[str]] = None,
    show_tqdm: bool = True,
) -> pd.DataFrame:
    from TB.IRSwapsTB import IRSwapsTB

    data_cfg = _data_cfg(config)
    curve_name = str(data_cfg.get("curve_name", DEFAULT_CURVE))
    ts_builder = ts_builder or TimeseriesBuilder()
    start_dt, end_dt = _history_bounds(config)

    if required_tokens is None:
        universe = build_trade_universe(config)
        required_tokens, _ = _unique_required_tokens(config, universe)

    queries = build_rate_queries(config, required_tokens, curve_name)
    n_jobs = int(data_cfg.get("timeseries_n_jobs", data_cfg.get("n_jobs", 12)))
    use_duckdb = bool(data_cfg.get("timeseries_use_duckdb", True))
    duckdb_path = data_cfg.get("timeseries_duckdb_path")
    ignore_cache = bool(data_cfg.get("ignore_cache", False))

    router = IRSwapsTB(
        curve_mdp,
        show_tqdm=show_tqdm,
        use_duckdb=use_duckdb,
        duckdb_path=duckdb_path,
    )
    frame = ts_builder.get_timeseries(
        start=start_dt,
        end=end_dt,
        queries=queries,
        n_jobs=n_jobs,
        ignore_cache=ignore_cache,
        routers={"IRS": router},
        drop_multilevel_cols=True,
        use_duckdb=use_duckdb,
        duckdb_path=duckdb_path,
    )
    if frame.empty:
        return frame

    rate_panel = frame.copy()
    rename_map = {}
    for query in queries:
        try:
            rename_map[str(query.col_name())] = str(query.name or query.col_name())
        except Exception:
            continue
    rate_panel = rate_panel.rename(columns=rename_map)
    rate_panel.index = pd.DatetimeIndex(pd.to_datetime(rate_panel.index)).normalize()
    rate_panel = rate_panel.groupby(level=0).last().sort_index()
    rate_panel.columns = [_canonical_token(col) for col in rate_panel.columns]
    rate_panel = rate_panel.loc[:, ~rate_panel.columns.duplicated()]
    rate_panel = rate_panel.reindex(columns=list(required_tokens))
    for column in rate_panel.columns:
        series = pd.to_numeric(rate_panel[column], errors="coerce")
        finite = series[np.isfinite(series)]
        if finite.empty:
            rate_panel[column] = series
            continue
        median_abs = float(np.nanmedian(np.abs(finite)))
        if median_abs > 50.0:
            series = series / 10_000.0
        elif median_abs > 1.0:
            series = series / 100.0
        rate_panel[column] = series

    rate_panel.index.name = "Date"
    return rate_panel


def _rate_from_standard_curve_token(curve: Any, token: str) -> Optional[float]:
    norm = _canonical_token(token)
    if re.fullmatch(r"\d+[DWMY]", norm):
        instrument = curve.build_irswap(fwd="0D", tenor=norm)
        return float(curve.fair_rate(instrument))
    match = re.fullmatch(r"(\d+[DWMY])x(\d+[DWMY])", norm)
    if match:
        swap_tenor, fwd = match.group(1), match.group(2)
        instrument = curve.build_irswap(fwd=fwd, tenor=swap_tenor)
        return float(curve.fair_rate(instrument))
    return None


def _rate_from_curve(curve: Any, curve_name: str, token: str) -> float:
    direct = _rate_from_standard_curve_token(curve, token)
    if direct is not None:
        return direct

    query = IRSwapQuery(
        curve=curve_name,
        tenor=token,
        value=IRSwapValue.RATE,
        structure_kwargs={"bpv": 1.0},
    )
    package, risk_weights = query.resolve_package(pricer_or_curve=curve)
    value_map = query.build_value_map(pricer_or_curve=curve, package=package, risk_weights=risk_weights)
    return float(value_map.apply(value=IRSwapValue.RATE)) / 100.0


def build_curve_dataset(
    config: Mapping[str, Any],
    curve_mdp: Optional[IRSwapsMDP] = None,
    ts_builder: Optional[TimeseriesBuilder] = None,
    *,
    show_tqdm: bool = True,
) -> CurveDataset:
    data_cfg = _data_cfg(config)
    source = str(data_cfg.get("source", DEFAULT_SOURCE))
    curve_name = str(data_cfg.get("curve_name", DEFAULT_CURVE))
    mdp = curve_mdp or IRSwapsMDP(source=source)

    universe = build_trade_universe(config)
    required_tokens, surface_map = _unique_required_tokens(config, universe)
    rate_panel = load_rate_timeseries(
        config,
        curve_mdp=mdp,
        ts_builder=ts_builder,
        required_tokens=required_tokens,
        show_tqdm=show_tqdm,
    )
    if rate_panel.empty:
        dates = pd.DatetimeIndex([], name="Date")
        curves_by_date: Dict[pd.Timestamp, Any] = {}
    else:
        rate_panel = rate_panel.reindex(columns=required_tokens)
        dates = pd.DatetimeIndex(rate_panel.index).normalize()
        curve_n_jobs = int(data_cfg.get("curve_n_jobs", data_cfg.get("n_jobs", 12)))
        requested_dates = [d.date() for d in dates]
        raw_curves = mdp.bulk_get_data({"curve_name": curve_name, "timestamps": requested_dates, "n_jobs": curve_n_jobs})
        curves_by_date = {
            pd.Timestamp(date_key).normalize(): curve
            for date_key, curve in raw_curves.items()
        }
        available_dates = pd.DatetimeIndex(sorted(set(dates).intersection(curves_by_date.keys()))).normalize()
        rate_panel = rate_panel.loc[available_dates]
        dates = available_dates

    surface_tokens = [token for token in surface_map if token in rate_panel.columns]
    surface_panel = rate_panel[surface_tokens].copy() if surface_tokens else pd.DataFrame(index=rate_panel.index)

    return CurveDataset(
        source=source,
        curve_name=curve_name,
        mdp=mdp,
        dates=dates,
        curves_by_date=curves_by_date,
        rate_panel=rate_panel,
        surface_panel=surface_panel,
        surface_token_map=surface_map,
        trade_universe=universe,
    )


def _rolling_residual_stats(series: pd.Series, lookback: int) -> pd.DataFrame:
    min_periods = min(lookback, max(lookback // 2, 20))
    mean = series.rolling(window=lookback, min_periods=min_periods).mean()
    std = series.rolling(window=lookback, min_periods=min_periods).std().replace(0.0, np.nan)
    zscore = (series - mean) / std
    return pd.DataFrame({"mean": mean, "std": std, "zscore": zscore}, index=series.index)


def _fifty_fly(rate_triplet: pd.DataFrame) -> pd.Series:
    return 0.5 * rate_triplet.iloc[:, 0] + 0.5 * rate_triplet.iloc[:, 2] - rate_triplet.iloc[:, 1]


def _wing_curve(rate_triplet: pd.DataFrame) -> pd.Series:
    return rate_triplet.iloc[:, 2] - rate_triplet.iloc[:, 0]


def _weights_from_regression(rate_triplet: pd.DataFrame, config: RegressionRVConfig) -> pd.DataFrame:
    regression = rolling_regression(
        fly=_fifty_fly(rate_triplet),
        body=rate_triplet.iloc[:, 1],
        curve=_wing_curve(rate_triplet),
        config=config,
    )
    out = pd.DataFrame(np.nan, index=rate_triplet.index, columns=rate_triplet.columns)
    out.iloc[:, 0] = regression.hedge_ratios["left_weight"]
    out.iloc[:, 1] = 1.0
    out.iloc[:, 2] = regression.hedge_ratios["right_weight"]
    return out


def _trade_residual_from_pca(actual: pd.DataFrame, reconstructed: pd.DataFrame, weights: pd.DataFrame) -> pd.Series:
    aligned_actual = actual.reindex(weights.index)
    aligned_recon = reconstructed.reindex(weights.index)[actual.columns]
    return ((aligned_actual - aligned_recon) * weights).sum(axis=1)


def _build_pca_snapshot(result: Any, date_key: pd.Timestamp, trade_columns: Sequence[str], weights: np.ndarray) -> Dict[str, Any]:
    return {
        "kind": "pca",
        "columns": tuple(result.reconstructed.columns),
        "trade_columns": tuple(trade_columns),
        "mean": result.means[date_key],
        "scale": result.scales[date_key],
        "loadings": result.loadings[date_key],
        "weights": np.asarray(weights, dtype=float),
    }


def _build_regression_snapshot(
    *,
    date_key: pd.Timestamp,
    regression_result: Any,
    trade_columns: Sequence[str],
) -> Dict[str, Any]:
    return {
        "kind": "regression",
        "trade_columns": tuple(trade_columns),
        "intercept": float(regression_result.intercepts.loc[date_key]),
        "beta_body": float(regression_result.betas_body.loc[date_key]),
        "beta_curve": float(regression_result.betas_curve.loc[date_key]),
    }


def _compute_stationarity_metrics(
    series: pd.Series,
    lookback: int,
) -> Tuple[pd.Series, pd.Series]:
    pvalues = pd.Series(np.nan, index=series.index, dtype=float)
    half_lives = pd.Series(np.nan, index=series.index, dtype=float)
    for i in range(lookback, len(series)):
        window = series.iloc[i - lookback : i].dropna()
        if len(window) < max(lookback // 2, 20):
            continue
        try:
            test_result = adf_test(window)
        except Exception:
            test_result = {"pvalue": np.nan}
        pvalues.iloc[i] = test_result.get("pvalue", np.nan)
        half_lives.iloc[i] = ou_half_life(window)
    return pvalues, half_lives


def _compute_carry_roll_panels(
    *,
    dataset: CurveDataset,
    universe: Sequence[FlyDefinition],
    weights: Dict[str, pd.DataFrame],
    trade_belly_bpv: float,
    horizon: str,
) -> Tuple[Dict[str, pd.Series], Dict[str, pd.Series], Dict[str, pd.Series]]:
    carry: Dict[str, pd.Series] = {}
    roll: Dict[str, pd.Series] = {}
    carry_roll: Dict[str, pd.Series] = {}

    for fly in universe:
        fid = fly.fly_id
        weight_panel = weights[fid]
        carry_series = pd.Series(np.nan, index=dataset.dates, dtype=float)
        roll_series = pd.Series(np.nan, index=dataset.dates, dtype=float)
        carry_roll_series = pd.Series(np.nan, index=dataset.dates, dtype=float)
        for date_key in dataset.dates:
            if date_key not in weight_panel.index:
                continue
            w = weight_panel.loc[date_key].to_numpy(dtype=float)
            if np.any(np.isnan(w)):
                continue
            curve = dataset.curves_by_date[date_key]
            query = IRSwapQuery(
                structure=IRSwapStructure.FLY,
                value=IRSwapValue.CARRY_AND_ROLL_BPS_RUNNING,
                curve=dataset.curve_name,
                structure_kwargs={
                    "front_tenor": fly.left,
                    "belly_tenor": fly.belly,
                    "back_tenor": fly.right,
                    "bpv": float(trade_belly_bpv),
                    "risk_weights": [float(x) for x in w],
                },
                value_kwargs={"horizon": horizon},
            )
            package, risk_weights = query.resolve_package(pricer_or_curve=curve)
            value_map = query.build_value_map(pricer_or_curve=curve, package=package, risk_weights=risk_weights)
            carry_series.loc[date_key] = float(value_map.apply(value=IRSwapValue.CARRY_BPS_RUNNING, horizon=horizon))
            roll_series.loc[date_key] = float(value_map.apply(value=IRSwapValue.ROLL_BPS_RUNNING, horizon=horizon))
            carry_roll_series.loc[date_key] = float(value_map.apply(value=IRSwapValue.CARRY_AND_ROLL_BPS_RUNNING, horizon=horizon))
        carry[fid] = carry_series
        roll[fid] = roll_series
        carry_roll[fid] = carry_roll_series

    return carry, roll, carry_roll


def _build_pca_config(config: Mapping[str, Any]) -> PCARVConfig:
    signal_cfg = _signal_cfg(config)
    return PCARVConfig(
        pca_window_days=int(signal_cfg.get("pca_window_days", 130)),
        pca_input=str(signal_cfg.get("pca_input", "levels")),
        n_components=int(signal_cfg.get("n_components", 3)),
        pca_scope=str(signal_cfg.get("residual_method", "full_curve_pca")),
        use_correlation=bool(signal_cfg.get("use_correlation", False)),
        zscore_lookback_days=int(signal_cfg.get("zscore_lookback_days", signal_cfg.get("pca_window_days", 130))),
    )


def _build_regression_config(config: Mapping[str, Any]) -> RegressionRVConfig:
    signal_cfg = _signal_cfg(config)
    entry_cfg = _entry_cfg(config)
    return RegressionRVConfig(
        window_days=int(signal_cfg.get("pca_window_days", 130)),
        min_rsq=float(entry_cfg.get("min_fit", entry_cfg.get("min_rsq", 0.60))),
        zscore_lookback_days=int(signal_cfg.get("zscore_lookback_days", signal_cfg.get("pca_window_days", 130))),
    )


def build_signal_bundle(dataset: CurveDataset, config: Mapping[str, Any]) -> SignalBundle:
    signal_cfg = _signal_cfg(config)
    stationarity_cfg = _stationarity_cfg(config)
    portfolio_cfg = _portfolio_cfg(config)
    regime_cfg = _regime_cfg(config)

    pca_config = _build_pca_config(config)
    regression_config = _build_regression_config(config)
    residual_method = str(signal_cfg.get("residual_method", "full_curve_pca"))
    weighting_method = str(signal_cfg.get("weighting_method", "pca_pc3"))
    zscore_lookback = int(signal_cfg.get("zscore_lookback_days", pca_config.zscore_lookback_days))
    stationarity_lookback = int(stationarity_cfg.get("lookback_days", signal_cfg.get("pca_window_days", 130)))
    compute_stationarity = bool(stationarity_cfg.get("enabled", False) or stationarity_cfg.get("compute", False))

    surface_result = rolling_pca(dataset.surface_panel, pca_config) if not dataset.surface_panel.empty else None
    surface_residuals = surface_result.residuals if surface_result is not None else pd.DataFrame(index=dataset.dates)
    surface_zscores = surface_result.zscores if surface_result is not None else pd.DataFrame(index=dataset.dates)
    surface_fit_quality = surface_result.fit_quality if surface_result is not None else pd.Series(index=dataset.dates, dtype=float)

    residuals: Dict[str, pd.Series] = {}
    residual_stats: Dict[str, pd.DataFrame] = {}
    zscores: Dict[str, pd.Series] = {}
    fit_quality: Dict[str, pd.Series] = {}
    weights: Dict[str, pd.DataFrame] = {}
    rate_triplets: Dict[str, pd.DataFrame] = {}
    entry_snapshots: Dict[str, Dict[pd.Timestamp, Any]] = {}
    stationarity_pvalues: Dict[str, pd.Series] = {}
    stationarity_half_lives: Dict[str, pd.Series] = {}

    full_curve_panel = dataset.rate_panel.copy()
    full_curve_result = rolling_pca(full_curve_panel, pca_config) if residual_method == "full_curve_pca" else None

    for fly in dataset.trade_universe:
        fid = fly.fly_id
        triplet = dataset.rate_panel.loc[:, list(fly.legs)].copy()
        triplet.columns = [fly.left, fly.belly, fly.right]
        rate_triplets[fid] = triplet

        if weighting_method == "regression_betas":
            weight_panel = _weights_from_regression(triplet, regression_config)
        else:
            weight_panel = pca_fly_weights(triplet, pca_config)
        weight_panel.columns = [fly.left, fly.belly, fly.right]
        weights[fid] = weight_panel

        snapshots: Dict[pd.Timestamp, Any] = {}
        if residual_method == "trade_tenors_pca":
            trade_pca = rolling_pca(triplet, pca_config)
            trade_residual = _trade_residual_from_pca(
                actual=triplet,
                reconstructed=trade_pca.reconstructed,
                weights=weight_panel,
            )
            stats = _rolling_residual_stats(trade_residual, zscore_lookback)
            fit_quality[fid] = trade_pca.fit_quality
            for date_key in trade_residual.dropna().index:
                if date_key not in trade_pca.loadings or date_key not in weight_panel.index:
                    continue
                snapshots[date_key] = _build_pca_snapshot(trade_pca, date_key, triplet.columns, weight_panel.loc[date_key].to_numpy(dtype=float))
        elif residual_method == "regression":
            regression = rolling_regression(
                fly=_fifty_fly(triplet),
                body=triplet.iloc[:, 1],
                curve=_wing_curve(triplet),
                config=regression_config,
            )
            trade_residual = regression.residuals
            stats = _rolling_residual_stats(trade_residual, zscore_lookback)
            fit_quality[fid] = regression.rsq
            for date_key in trade_residual.dropna().index:
                snapshots[date_key] = _build_regression_snapshot(
                    date_key=date_key,
                    regression_result=regression,
                    trade_columns=triplet.columns,
                )
        else:
            if full_curve_result is None:
                raise ValueError("full_curve_pca residual method requires a full-curve PCA result")
            aligned_reconstructed = full_curve_result.reconstructed.loc[:, list(fly.legs)]
            trade_residual = _trade_residual_from_pca(
                actual=triplet,
                reconstructed=aligned_reconstructed,
                weights=weight_panel,
            )
            stats = _rolling_residual_stats(trade_residual, zscore_lookback)
            fit_quality[fid] = full_curve_result.fit_quality
            for date_key in trade_residual.dropna().index:
                if date_key not in full_curve_result.loadings or date_key not in weight_panel.index:
                    continue
                snapshots[date_key] = _build_pca_snapshot(full_curve_result, date_key, triplet.columns, weight_panel.loc[date_key].to_numpy(dtype=float))

        residuals[fid] = trade_residual
        residual_stats[fid] = stats
        zscores[fid] = stats["zscore"]
        entry_snapshots[fid] = snapshots

        if compute_stationarity:
            pvalues, half_life = _compute_stationarity_metrics(trade_residual, stationarity_lookback)
        else:
            pvalues = pd.Series(np.nan, index=trade_residual.index, dtype=float)
            half_life = pd.Series(np.nan, index=trade_residual.index, dtype=float)
        stationarity_pvalues[fid] = pvalues
        stationarity_half_lives[fid] = half_life

    trade_belly_bpv = float(portfolio_cfg.get("trade_belly_bpv", 100_000.0))
    carry_horizon = str(signal_cfg.get("carry_horizon", "1M"))
    carry_bp, roll_bp, carry_roll_bp = _compute_carry_roll_panels(
        dataset=dataset,
        universe=dataset.trade_universe,
        weights=weights,
        trade_belly_bpv=trade_belly_bpv,
        horizon=carry_horizon,
    )

    reference_fly_tuple = tuple(regime_cfg.get("reference_fly", (dataset.trade_universe[0].left, dataset.trade_universe[0].belly, dataset.trade_universe[0].right)))
    reference_triplet = dataset.rate_panel.loc[:, list(reference_fly_tuple)].copy()
    reference_triplet.columns = list(reference_fly_tuple)
    reference_regression = rolling_regression(
        fly=_fifty_fly(reference_triplet),
        body=reference_triplet.iloc[:, 1],
        curve=_wing_curve(reference_triplet),
        config=regression_config,
    )
    regime_details = traffic_light(
        reference_regression.betas_body,
        reference_regression.betas_curve,
        RegimeFilterConfig(
            beta_vol_window_days=int(regime_cfg.get("beta_vol_window_days", 65)),
            beta_vol_zscore_window_days=int(regime_cfg.get("beta_vol_zscore_window_days", 130)),
            threshold=float(regime_cfg.get("threshold", 3.0)),
        ),
    )
    reference_betas = pd.DataFrame(
        {
            "beta_body": reference_regression.betas_body,
            "beta_curve": reference_regression.betas_curve,
        }
    )

    return SignalBundle(
        fly_definitions=dataset.trade_universe,
        residuals=residuals,
        residual_stats=residual_stats,
        zscores=zscores,
        fit_quality=fit_quality,
        weights=weights,
        rate_triplets=rate_triplets,
        entry_snapshots=entry_snapshots,
        carry_bp=carry_bp,
        roll_bp=roll_bp,
        carry_roll_bp=carry_roll_bp,
        stationarity_pvalues=stationarity_pvalues,
        stationarity_half_lives=stationarity_half_lives,
        regime=regime_details["regime"],
        regime_details=regime_details,
        reference_betas=reference_betas,
        surface_residuals=surface_residuals,
        surface_zscores=surface_zscores,
        surface_fit_quality=surface_fit_quality,
    )


def _frozen_residual_getter(dataset: CurveDataset) -> Any:
    def _getter(fly_id: str, date_key: pd.Timestamp, snapshot: Mapping[str, Any]) -> float:
        dt_key = pd.Timestamp(date_key).normalize()
        if snapshot["kind"] == "regression":
            trade_columns = list(snapshot["trade_columns"])
            row = dataset.rate_panel.loc[dt_key, trade_columns].astype(float)
            fly = 0.5 * row.iloc[0] + 0.5 * row.iloc[2] - row.iloc[1]
            curve = row.iloc[2] - row.iloc[0]
            return float(fly - (snapshot["intercept"] + snapshot["beta_body"] * row.iloc[1] + snapshot["beta_curve"] * curve))

        columns = list(snapshot["columns"])
        trade_columns = list(snapshot["trade_columns"])
        current_row = dataset.rate_panel.loc[dt_key, columns].astype(float).to_numpy()
        mean = np.asarray(snapshot["mean"], dtype=float)
        scale = np.asarray(snapshot["scale"], dtype=float)
        scale = np.where(scale == 0.0, 1.0, scale)
        loadings = np.asarray(snapshot["loadings"], dtype=float)
        normalized = (current_row - mean) / scale
        scores = normalized @ loadings
        reconstructed_norm = scores @ loadings.T
        reconstructed = reconstructed_norm * scale + mean
        reconstructed_series = pd.Series(reconstructed, index=columns)
        actual_trade = dataset.rate_panel.loc[dt_key, trade_columns].astype(float).to_numpy()
        recon_trade = reconstructed_series.loc[trade_columns].to_numpy(dtype=float)
        return float(np.dot(np.asarray(snapshot["weights"], dtype=float), actual_trade - recon_trade))

    return _getter


def _query_factory(dataset: CurveDataset, signal_bundle: SignalBundle, config: Mapping[str, Any]) -> Any:
    portfolio_cfg = _portfolio_cfg(config)
    trade_belly_bpv = float(portfolio_cfg.get("trade_belly_bpv", 100_000.0))
    fly_map = {fly.fly_id: fly for fly in signal_bundle.fly_definitions}

    def _factory(fly_id: str, weights: np.ndarray, direction: int) -> IRSwapQuery:
        fly = fly_map[fly_id]
        if str(portfolio_cfg.get("sizing_method", "equal_belly_bpv")) != "equal_belly_bpv":
            raise NotImplementedError("Only equal_belly_bpv sizing is implemented in v1")
        signed_bpv = trade_belly_bpv * float(direction)
        return IRSwapQuery(
            structure=IRSwapStructure.FLY,
            value=IRSwapValue.NPV,
            curve=dataset.curve_name,
            structure_kwargs={
                "front_tenor": fly.left,
                "belly_tenor": fly.belly,
                "back_tenor": fly.right,
                "bpv": signed_bpv,
                "risk_weights": [float(x) for x in weights],
            },
        )

    return _factory


def _build_backtest_config(config: Mapping[str, Any]) -> RVBacktestConfig:
    entry_cfg = _entry_cfg(config)
    exit_cfg = _exit_cfg(config)
    portfolio_cfg = _portfolio_cfg(config)
    costs_cfg = _costs_cfg(config)
    stationarity_cfg = _stationarity_cfg(config)

    return RVBacktestConfig(
        trade_belly_bpv=float(portfolio_cfg.get("trade_belly_bpv", 100_000.0)),
        ranking_method=str(portfolio_cfg.get("ranking_method", "abs_zscore")),
        sizing_method=str(portfolio_cfg.get("sizing_method", "equal_belly_bpv")),
        entry_min_rsq=float(entry_cfg.get("min_rsq", 0.60)),
        entry_min_fit=float(entry_cfg.get("min_fit", entry_cfg.get("min_rsq", 0.60))),
        entry_min_residual_bp=float(entry_cfg.get("min_residual_bp", 4.0)),
        entry_min_zscore=float(entry_cfg.get("min_zscore", 1.5)),
        entry_use_carry_filter=bool(entry_cfg.get("use_carry_filter", False)),
        exit_mean_reversion=bool(exit_cfg.get("mean_reversion", True)),
        exit_stop_loss_sd=float(exit_cfg.get("stop_loss_sd", 2.0)),
        exit_max_holding_days=int(exit_cfg.get("max_holding_days", 22)),
        exit_carry_adjusted=bool(exit_cfg.get("carry_adjusted", False)),
        max_concurrent_trades=portfolio_cfg.get("max_concurrent_trades"),
        no_duplicate_flies=bool(portfolio_cfg.get("no_duplicate_flies", True)),
        reentry_after_stop=bool(portfolio_cfg.get("reentry_after_stop", True)),
        stationarity_filter_enabled=bool(stationarity_cfg.get("enabled", False)),
        stationarity_max_adf_pvalue=float(stationarity_cfg.get("max_adf_pvalue", 0.05)),
        stationarity_max_half_life_days=stationarity_cfg.get("max_half_life_days"),
        round_trip_cost_bp=float(costs_cfg.get("round_trip_cost_bp", 0.5)),
        min_profit_to_cost_ratio=float(costs_cfg.get("min_profit_to_cost_ratio", 2.0)),
    )


def run_study(
    config: Mapping[str, Any],
    dataset: Optional[CurveDataset] = None,
    signal_bundle: Optional[SignalBundle] = None,
    *,
    show_progress: Optional[bool] = None,
) -> StudyResult:
    if show_progress is None:
        backtest_cfg = config.get("backtest", {})
        show_progress = bool(backtest_cfg.get("show_progress", True))
    dataset = dataset or build_curve_dataset(config)
    signal_bundle = signal_bundle or build_signal_bundle(dataset, config)
    backtest_config = _build_backtest_config(config)
    backtest = run_query_rv_backtest(
        residuals=signal_bundle.residuals,
        zscores=signal_bundle.zscores,
        fit_quality=signal_bundle.fit_quality,
        weights=signal_bundle.weights,
        fly_categories=signal_bundle.fly_categories,
        entry_snapshots=signal_bundle.entry_snapshots,
        residual_stats=signal_bundle.residual_stats,
        regime=signal_bundle.regime,
        mdp=dataset.mdp,
        query_factory=_query_factory(dataset, signal_bundle, config),
        frozen_residual_getter=_frozen_residual_getter(dataset),
        config=backtest_config,
        carry_roll=signal_bundle.carry_roll_bp,
        stationarity_pvalues=signal_bundle.stationarity_pvalues,
        stationarity_half_lives=signal_bundle.stationarity_half_lives,
        show_progress=show_progress,
    )
    return StudyResult(dataset=dataset, signals=signal_bundle, backtest=backtest)


def pivot_surface_values(dataset: CurveDataset, values: pd.Series) -> pd.DataFrame:
    if values.empty:
        return pd.DataFrame()
    grid = pd.DataFrame(index=sorted({swap for swap, _ in dataset.surface_token_map.values()}), columns=sorted({fwd for _, fwd in dataset.surface_token_map.values()}), dtype=float)
    for token, value in values.items():
        if token not in dataset.surface_token_map:
            continue
        swap_tenor, forward_start = dataset.surface_token_map[token]
        grid.loc[swap_tenor, forward_start] = float(value)
    grid.index.name = "swap_tenor"
    grid.columns.name = "forward_tenor"
    return grid


def run_threshold_sweep(
    config: Mapping[str, Any],
    dataset: Optional[CurveDataset] = None,
    signal_bundle: Optional[SignalBundle] = None,
) -> pd.DataFrame:
    sweep_cfg = config.get("sweep", {})
    rsq_values = list(sweep_cfg.get("min_fit", [config.get("entry", {}).get("min_fit", 0.60)]))
    residual_values = list(sweep_cfg.get("min_residual_bp", [config.get("entry", {}).get("min_residual_bp", 4.0)]))
    z_values = list(sweep_cfg.get("min_zscore", [config.get("entry", {}).get("min_zscore", 1.5)]))
    dataset = dataset or build_curve_dataset(config)
    signal_bundle = signal_bundle or build_signal_bundle(dataset, config)

    rows: List[Dict[str, Any]] = []
    for min_fit in rsq_values:
        for min_residual_bp in residual_values:
            for min_zscore in z_values:
                local = copy.deepcopy(dict(config))
                local.setdefault("entry", {})
                local["entry"] = dict(local["entry"])
                local["entry"]["min_fit"] = min_fit
                local["entry"]["min_rsq"] = min_fit
                local["entry"]["min_residual_bp"] = min_residual_bp
                local["entry"]["min_zscore"] = min_zscore
                result = run_study(local, dataset=dataset, signal_bundle=signal_bundle, show_progress=False)
                rows.append(
                    {
                        "min_fit": min_fit,
                        "min_residual_bp": min_residual_bp,
                        "min_zscore": min_zscore,
                        **result.backtest.metrics,
                    }
                )
    return pd.DataFrame(rows)


def build_surface_snapshot(
    dataset: CurveDataset,
    signal_bundle: SignalBundle,
    *,
    as_of: Optional[Any] = None,
    horizon: str = "1M",
) -> SurfaceSnapshot:
    as_of_ts = pd.Timestamp(as_of or dataset.dates[-1]).normalize()
    curve = dataset.curves_by_date[as_of_ts]
    horizon_months = tenor_to_months(horizon)

    carry_vals: Dict[str, float] = {}
    roll_vals: Dict[str, float] = {}
    carry_roll_vals: Dict[str, float] = {}
    for token in dataset.surface_token_map:
        current_rate = _rate_from_curve(curve, dataset.curve_name, token)
        try:
            carry_token = shift_surface_token(token, forward_months_delta=horizon_months)
            carry_rate = _rate_from_curve(curve, dataset.curve_name, carry_token)
            carry_bp = (current_rate - carry_rate) * 10_000.0
        except Exception:
            carry_bp = np.nan

        try:
            roll_token = shift_surface_token(token, swap_months_delta=-horizon_months)
            roll_rate = _rate_from_curve(curve, dataset.curve_name, roll_token)
            roll_bp = (current_rate - roll_rate) * 10_000.0
        except Exception:
            roll_bp = np.nan

        carry_vals[token] = carry_bp
        roll_vals[token] = roll_bp
        carry_roll_vals[token] = carry_bp + roll_bp if np.isfinite(carry_bp) and np.isfinite(roll_bp) else np.nan

    actual = pivot_surface_values(dataset, dataset.surface_panel.loc[as_of_ts].dropna())
    residual = pivot_surface_values(dataset, signal_bundle.surface_residuals.loc[as_of_ts].dropna())
    zscore = pivot_surface_values(dataset, signal_bundle.surface_zscores.loc[as_of_ts].dropna())
    carry_grid = pivot_surface_values(dataset, pd.Series(carry_vals))
    roll_grid = pivot_surface_values(dataset, pd.Series(roll_vals))
    carry_roll_grid = pivot_surface_values(dataset, pd.Series(carry_roll_vals))

    return SurfaceSnapshot(
        as_of=as_of_ts,
        actual=actual,
        residual=residual,
        zscore=zscore,
        carry_bp=carry_grid,
        roll_bp=roll_grid,
        carry_roll_bp=carry_roll_grid,
    )


def rank_surface_dislocations(
    dataset: CurveDataset,
    signal_bundle: SignalBundle,
    *,
    as_of: Optional[Any] = None,
    top_n: int = 15,
    absolute: bool = True,
) -> pd.DataFrame:
    as_of_ts = pd.Timestamp(as_of or dataset.dates[-1]).normalize()
    z_row = signal_bundle.surface_zscores.loc[as_of_ts].dropna()
    residual_row = signal_bundle.surface_residuals.loc[as_of_ts].reindex(z_row.index)
    current_row = dataset.surface_panel.loc[as_of_ts].reindex(z_row.index)

    frame = pd.DataFrame(
        {
            "token": z_row.index,
            "actual_rate": current_row.values,
            "residual_bp": residual_row.values * 10_000.0,
            "zscore": z_row.values,
        }
    )
    frame["abs_zscore"] = frame["zscore"].abs()
    frame["swap_tenor"] = frame["token"].map(lambda x: split_surface_token(x)[0])
    frame["forward_start"] = frame["token"].map(lambda x: split_surface_token(x)[1])
    sort_cols = ["abs_zscore", "zscore"] if absolute else ["zscore"]
    ascending = [False, False] if absolute else [False]
    return frame.sort_values(sort_cols, ascending=ascending).head(top_n).reset_index(drop=True)


def compute_pca_weighted_fly_series(
    signal_bundle: SignalBundle,
    fly_id: str,
    *,
    as_of: Optional[Any] = None,
    mode: str = "latest",
) -> pd.Series:
    triplet = signal_bundle.rate_triplets[fly_id]
    if mode == "rolling":
        return (triplet * signal_bundle.weights[fly_id].reindex(triplet.index)).sum(axis=1)
    as_of_ts = pd.Timestamp(as_of or triplet.index[-1]).normalize()
    weights = signal_bundle.weights[fly_id].loc[:as_of_ts].dropna()
    if weights.empty:
        return pd.Series(np.nan, index=triplet.index, name=fly_id)
    latest_weights = weights.iloc[-1]
    series = (triplet * latest_weights.values).sum(axis=1)
    series.name = fly_id
    return series


def compute_two_stage_trade_analytics(
    dataset: CurveDataset,
    signal_bundle: SignalBundle,
    config: Mapping[str, Any],
    fly_id: str,
    *,
    as_of: Optional[Any] = None,
    ou_lookback_days: Optional[int] = None,
    validation_weight_mode: str = "latest",
) -> TwoStageTradeAnalytics:
    fly = next(f for f in signal_bundle.fly_definitions if f.fly_id == fly_id)
    as_of_ts = pd.Timestamp(as_of or dataset.dates[-1]).normalize()
    triplet = signal_bundle.rate_triplets[fly_id]
    triplet_up_to = triplet.loc[:as_of_ts]

    pca_config = _build_pca_config(config)
    stage2_result = rolling_pca(triplet_up_to, pca_config)
    stage2_weights = pca_fly_weights(triplet_up_to, pca_config).dropna()
    if stage2_weights.empty:
        raise ValueError(f"No valid stage-2 PCA weights for {fly_id} as of {as_of_ts.date()}")
    stage2_date = stage2_weights.index[-1]
    current_weights = stage2_weights.iloc[-1]
    pc_loadings = pd.DataFrame(
        stage2_result.loadings[stage2_date],
        index=triplet.columns,
        columns=[f"PC{i+1}" for i in range(stage2_result.loadings[stage2_date].shape[1])],
    )
    pc_exposures = pd.Series(
        {
            col: float(np.dot(pc_loadings[col].values, current_weights.values))
            for col in pc_loadings.columns
        }
    )

    if validation_weight_mode == "rolling":
        pca_fly_series = (triplet_up_to * stage2_weights.reindex(triplet_up_to.index)).sum(axis=1).reindex(triplet.index)
    else:
        pca_fly_series = (triplet * current_weights.values).sum(axis=1)
    pca_fly_series.name = fly_id
    fly_5050_series = (triplet.iloc[:, 1] - 0.5 * triplet.iloc[:, 0] - 0.5 * triplet.iloc[:, 2]).rename("fly_5050")
    level_series = triplet.iloc[:, 1].rename("level")
    slope_series = (triplet.iloc[:, 2] - triplet.iloc[:, 0]).rename("slope")
    aligned = pd.concat([pca_fly_series, fly_5050_series, level_series, slope_series], axis=1).dropna()
    correlations = pd.Series(
        {
            "pca_vs_level": aligned.iloc[:, 0].corr(aligned.iloc[:, 2]),
            "pca_vs_slope": aligned.iloc[:, 0].corr(aligned.iloc[:, 3]),
            "fly_5050_vs_level": aligned.iloc[:, 1].corr(aligned.iloc[:, 2]),
            "fly_5050_vs_slope": aligned.iloc[:, 1].corr(aligned.iloc[:, 3]),
        }
    )

    lookback = int(ou_lookback_days or _stationarity_cfg(config).get("lookback_days", _signal_cfg(config).get("pca_window_days", 130)))
    ou_window = pca_fly_series.loc[:as_of_ts].dropna().tail(lookback)
    adf_result = adf_test(ou_window)
    ou_result = ou_params(ou_window)
    current_level = float(pca_fly_series.loc[as_of_ts])
    target_level = float(ou_result.get("theta", np.nan))
    distance_to_mean = target_level - current_level
    stop_level = current_level - np.sign(distance_to_mean) * 0.5 * abs(distance_to_mean)

    mu = float(ou_result.get("mu", np.nan))
    sigma = float(ou_result.get("sigma", np.nan))
    if np.isfinite(mu) and mu > 0 and np.isfinite(sigma):
        equilibrium_sigma = sigma / np.sqrt(2.0 * mu)
        current_ou_z = (current_level - target_level) / equilibrium_sigma if equilibrium_sigma > 0 else np.nan
    else:
        current_ou_z = np.nan

    carry_bp = float(signal_bundle.carry_bp[fly_id].loc[as_of_ts]) if fly_id in signal_bundle.carry_bp else np.nan
    roll_bp = float(signal_bundle.roll_bp[fly_id].loc[as_of_ts]) if fly_id in signal_bundle.roll_bp else np.nan
    carry_roll_bp = float(signal_bundle.carry_roll_bp[fly_id].loc[as_of_ts]) if fly_id in signal_bundle.carry_roll_bp else np.nan
    expected_profit_bp = abs(distance_to_mean) * 10_000.0
    cost_cfg = _costs_cfg(config)
    cost_threshold = float(cost_cfg.get("round_trip_cost_bp", 0.5)) * float(cost_cfg.get("min_profit_to_cost_ratio", 2.0))
    passes_cost_filter = bool(expected_profit_bp >= cost_threshold)

    stage1_residual_bp = float(signal_bundle.residuals[fly_id].loc[as_of_ts] * 10_000.0)
    stage1_zscore = float(signal_bundle.zscores[fly_id].loc[as_of_ts])
    stage1_fit_quality = float(signal_bundle.fit_quality[fly_id].loc[as_of_ts])

    return TwoStageTradeAnalytics(
        fly_id=fly_id,
        as_of=as_of_ts,
        weights=current_weights,
        stage1_residual_bp=stage1_residual_bp,
        stage1_zscore=stage1_zscore,
        stage1_fit_quality=stage1_fit_quality,
        pc_loadings=pc_loadings,
        pc_exposures=pc_exposures,
        pca_fly_series=pca_fly_series,
        fly_5050_series=fly_5050_series,
        level_series=level_series,
        slope_series=slope_series,
        correlations=correlations,
        adf=adf_result,
        ou=ou_result,
        current_level=current_level,
        target_level=target_level,
        stop_level=stop_level,
        current_ou_zscore=current_ou_z,
        carry_bp=carry_bp,
        roll_bp=roll_bp,
        carry_roll_bp=carry_roll_bp,
        expected_profit_bp=expected_profit_bp,
        passes_cost_filter=passes_cost_filter,
    )
