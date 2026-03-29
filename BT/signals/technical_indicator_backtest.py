"""Query-driven backtest adapter for precomputed technical indicator signals."""

from __future__ import annotations

import datetime
import inspect
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Mapping, Optional

import numpy as np
import pandas as pd
from tqdm.std import tqdm as _tqdm

from BT.data_handler import TimeGrid
from BT.event import TriggerInfo
from BT.query_actions import BuiltQuery, _normalize_built_queries
from BT.query_engine import QueryDrivenBacktest
from BT.query_order import QueryOrder, UnwindOrder
from BT.query_portfolio import ResolvedQueryPosition
from BT.query_strategy import QueryStrategy
from BT.signals.technical_indicators import TechnicalIndicatorSignalResult
from BT.triggers import Trigger, TriggerRequirements


@dataclass
class TechnicalIndicatorQueryBacktestResult:
    signal_result: TechnicalIndicatorSignalResult
    backtest: QueryDrivenBacktest
    mtm_history: pd.Series
    pnl_history: pd.Series
    order_frame: pd.DataFrame
    metrics: dict[str, float]


@dataclass
class TechnicalIndicatorTriggerRequirements(TriggerRequirements):
    position_table: Mapping[pd.Timestamp, Mapping[str, int]]
    fire_mode: str = "changes_only"
    indicator_table: Optional[Mapping[pd.Timestamp, Mapping[str, Any]]] = None
    desired_table: Optional[Mapping[pd.Timestamp, Mapping[str, int]]] = None
    raw_table: Optional[Mapping[pd.Timestamp, Mapping[str, Any]]] = None
    calc_type: str = "technical_indicator"
    _normalized_positions: dict[pd.Timestamp, dict[str, int]] = field(init=False, default_factory=dict)
    _previous_positions: dict[pd.Timestamp, dict[str, int]] = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:
        if self.fire_mode not in {"changes_only", "all_steps"}:
            raise ValueError("fire_mode must be 'changes_only' or 'all_steps'.")

        normalized = {
            pd.Timestamp(timestamp): {
                str(signal_key): _coerce_position(value)
                for signal_key, value in dict(row).items()
            }
            for timestamp, row in dict(self.position_table).items()
        }
        previous: dict[str, int] = {}
        previous_positions: dict[pd.Timestamp, dict[str, int]] = {}
        for timestamp in sorted(normalized):
            previous_positions[timestamp] = dict(previous)
            previous = dict(normalized[timestamp])
        self._normalized_positions = normalized
        self._previous_positions = previous_positions

    def has_triggered(self, state, backtest=None):
        matched_timestamp, target_positions = _lookup_table_entry(self._normalized_positions, state)
        if target_positions is None:
            return TriggerInfo(False)

        previous_positions = self._previous_positions.get(matched_timestamp, {})
        if self.fire_mode == "changes_only" and not _positions_changed(target_positions, previous_positions):
            return TriggerInfo(False)

        _, indicator_row = _lookup_table_entry(self.indicator_table, state)
        _, desired_positions = _lookup_table_entry(self.desired_table, state)
        _, raw_row = _lookup_table_entry(self.raw_table, state)
        info = {
            "signal_timestamp": matched_timestamp,
            "target_positions": dict(target_positions),
            "desired_positions": dict(desired_positions or {}),
            "indicator_row": dict(indicator_row or {}),
            "raw_row": dict(raw_row or {}),
        }
        return TriggerInfo(True, info=info)


@dataclass
class TargetPositionSignalAction:
    query_factory: Callable[..., Any]
    position_key_fn: Optional[Callable[..., Optional[str]]] = None
    signal_key_fn: Optional[Callable[..., str]] = None
    strategy_name: str = "technical_indicator"
    _trade_seq: int = field(default=0, init=False)

    def __call__(self, *, now, backtest, info) -> list[Any]:
        target_positions = dict(info.get("target_positions") or {})
        logical_targets: dict[str, tuple[str, int]] = {}
        for raw_signal_key, target_position in target_positions.items():
            item_info = dict(info)
            item_info["raw_signal_key"] = str(raw_signal_key)
            item_info["target_position"] = int(target_position)
            logical_key = self._signal_key(raw_signal_key, int(target_position), item_info)
            existing_target = logical_targets.get(logical_key)
            if existing_target is not None and existing_target[1] != int(target_position):
                raise ValueError(
                    f"Conflicting target positions for logical key {logical_key!r}: "
                    f"{existing_target[1]} versus {int(target_position)}."
                )
            logical_targets[logical_key] = (str(raw_signal_key), int(target_position))

        open_positions = self._group_open_positions(backtest)
        all_keys = sorted(set(open_positions) | set(logical_targets))
        orders: list[Any] = []

        for logical_key in all_keys:
            raw_signal_key, target_position = logical_targets.get(logical_key, (logical_key, 0))
            existing_positions = open_positions.get(logical_key, [])
            current_signal = self._current_signal(existing_positions)
            if current_signal == target_position:
                continue

            for position in existing_positions:
                position_id = position.meta.get("position_id")
                if position_id is not None:
                    selector = lambda p, position_id=position_id: p.meta.get("position_id") == position_id
                else:
                    selector = lambda p, position=position: p is position
                orders.append(
                    UnwindOrder(
                        timestamp=now,
                        selector=selector,
                        meta={
                            "technical_indicator_strategy": self.strategy_name,
                            "signal_key": logical_key,
                            "raw_signal_key": raw_signal_key,
                            "signal_direction": int(position.meta.get("signal_direction", 0)),
                            "position_id": position_id,
                        },
                    )
                )

            if target_position == 0:
                continue

            item_info = dict(info)
            item_info["signal_key"] = logical_key
            item_info["raw_signal_key"] = raw_signal_key
            item_info["target_position"] = int(target_position)

            built_queries = _normalize_built_queries(
                _invoke_callable(
                    self.query_factory,
                    target_position=int(target_position),
                    now=now,
                    info=item_info,
                )
            )
            if not built_queries:
                continue

            self._trade_seq += 1
            position_group_id = f"{logical_key}|{pd.Timestamp(now).isoformat()}|{self._trade_seq}"
            for leg_index, payload in enumerate(built_queries, start=1):
                position_id = f"{position_group_id}|leg{leg_index}"
                meta = {
                    "technical_indicator_strategy": self.strategy_name,
                    "signal_key": logical_key,
                    "raw_signal_key": raw_signal_key,
                    "signal_direction": int(target_position),
                    "position_group_id": position_group_id,
                    "position_id": position_id,
                    "tags": [f"{self.strategy_name}_{logical_key}"],
                }
                merged_meta = meta | dict(payload.meta or {})
                merged_meta["tags"] = _merge_tags(meta.get("tags"), (payload.meta or {}).get("tags"))
                orders.append(QueryOrder(timestamp=now, query=payload.query, meta=merged_meta))

        return orders

    def _group_open_positions(self, backtest: QueryDrivenBacktest) -> dict[str, list[ResolvedQueryPosition]]:
        grouped: dict[str, list[ResolvedQueryPosition]] = {}
        for position in backtest.portfolio.iter_positions():
            key = self._position_key(position)
            if key is None:
                continue
            grouped.setdefault(key, []).append(position)
        return grouped

    def _position_key(self, position: ResolvedQueryPosition) -> Optional[str]:
        if self.position_key_fn is None:
            meta = position.meta or {}
            if meta.get("technical_indicator_strategy") != self.strategy_name:
                return None
            signal_key = meta.get("signal_key")
            return None if signal_key is None else str(signal_key)
        return _invoke_callable(self.position_key_fn, position=position, default=None)

    def _signal_key(self, raw_signal_key: str, target_position: int, info: dict[str, Any]) -> str:
        if self.signal_key_fn is None:
            return str(raw_signal_key)
        return str(
            _invoke_callable(
                self.signal_key_fn,
                raw_signal_key=str(raw_signal_key),
                target_position=int(target_position),
                info=info,
            )
        )

    @staticmethod
    def _current_signal(positions: list[ResolvedQueryPosition]) -> Optional[int]:
        if not positions:
            return 0
        directions = {int(position.meta.get("signal_direction", 0)) for position in positions}
        group_ids = {position.meta.get("position_group_id") for position in positions}
        if len(group_ids) > 1 or (len(positions) > 1 and None in group_ids):
            return None
        if len(directions) != 1:
            return None
        return next(iter(directions))


def run_technical_indicator_query_backtest(
    signal_result: TechnicalIndicatorSignalResult,
    *,
    trade_query_factory: Callable[..., Any],
    mdp,
    strategy_name: str,
    show_progress: bool = False,
    fire_mode: str = "changes_only",
    ignore_cache_miss: bool = False,
    signal_key_fn: Optional[Callable[..., str]] = None,
    position_key_fn: Optional[Callable[..., Optional[str]]] = None,
) -> TechnicalIndicatorQueryBacktestResult:
    position_frame = _prepare_frame(signal_result.execution_position)
    desired_frame = _prepare_frame(signal_result.desired_position)
    indicator_frame = _prepare_frame(signal_result.indicator_frame)
    raw_frame = _prepare_frame(signal_result.raw_series)
    if ignore_cache_miss:
        covered_index = _cached_coverage_index(
            position_frame=position_frame,
            desired_frame=desired_frame,
            indicator_frame=indicator_frame,
            raw_frame=raw_frame,
            trade_query_factory=trade_query_factory,
            mdp=mdp,
            signal_key_fn=signal_key_fn,
            show_progress=show_progress,
            strategy_name=strategy_name,
        )
        position_frame = position_frame.loc[position_frame.index.intersection(covered_index)]
        desired_frame = desired_frame.loc[desired_frame.index.intersection(covered_index)]
        indicator_frame = indicator_frame.loc[indicator_frame.index.intersection(covered_index)]
        raw_frame = raw_frame.loc[raw_frame.index.intersection(covered_index)]
    time_index = pd.DatetimeIndex(position_frame.index)
    prep_total = len(position_frame) + len(desired_frame) + len(indicator_frame) + len(raw_frame) + 1

    progress_cm = _tqdm(
        total=prep_total,
        desc=f"{strategy_name.upper()} PREP",
        disable=not show_progress,
        dynamic_ncols=True,
        leave=False,
    )
    with progress_cm as prep_progress:
        trigger = Trigger(
            trigger_requirements=TechnicalIndicatorTriggerRequirements(
                position_table=_build_position_table(position_frame, progress=prep_progress),
                desired_table=_build_position_table(desired_frame, progress=prep_progress),
                indicator_table=_build_row_table(indicator_frame, progress=prep_progress),
                raw_table=_build_row_table(raw_frame, progress=prep_progress),
                fire_mode=fire_mode,
            ),
            actions=[
                TargetPositionSignalAction(
                    query_factory=_wrap_query_factory_ignore_cache_miss(
                        trade_query_factory,
                        enabled=ignore_cache_miss,
                    ),
                    position_key_fn=position_key_fn,
                    signal_key_fn=signal_key_fn,
                    strategy_name=strategy_name,
                )
            ],
        )
        prep_progress.update(1)

        strategy = QueryStrategy(name=strategy_name, triggers=[trigger])
        backtest = QueryDrivenBacktest(
            time_grid=TimeGrid(list(time_index.to_pydatetime())),
            strategy=strategy,
            mdp=mdp,
            show_progress=show_progress,
            progress_desc=f"{strategy_name.upper()} QUERY BT",
        )

    backtest.run()

    mtm_history = pd.Series(backtest.mtm_history).sort_index()
    pnl_history = mtm_history.diff().fillna(mtm_history)
    order_frame = pd.DataFrame(
        [
            {
                "timestamp": order.timestamp,
                "signal_key": (order.meta or {}).get("signal_key"),
                "raw_signal_key": (order.meta or {}).get("raw_signal_key"),
                "position_id": (order.meta or {}).get("position_id"),
                "signal_direction": (order.meta or {}).get("signal_direction"),
                "order_type": type(order).__name__,
            }
            for order in backtest.portfolio.orders_log
        ]
    )
    metrics = _compute_backtest_metrics(
        pnl_series=pnl_history,
        cumulative_pnl=mtm_history,
        trade_sides=float(len(order_frame)),
        annualization_factor=_annualization_factor(mtm_history.index),
    )
    return TechnicalIndicatorQueryBacktestResult(
        signal_result=signal_result,
        backtest=backtest,
        mtm_history=mtm_history,
        pnl_history=pnl_history,
        order_frame=order_frame,
        metrics=metrics,
    )


def _build_position_table(
    position_data: pd.Series | pd.DataFrame,
    *,
    progress=None,
) -> dict[pd.Timestamp, dict[str, int]]:
    frame = _prepare_frame(position_data)
    table: dict[pd.Timestamp, dict[str, int]] = {}
    for timestamp, row in frame.iterrows():
        coerced = {
            str(column): _coerce_position(value)
            for column, value in row.items()
            if not pd.isna(value)
        }
        if coerced:
            table[pd.Timestamp(timestamp)] = coerced
        if progress is not None:
            progress.update(1)
    return table


def _build_row_table(
    data: pd.Series | pd.DataFrame,
    *,
    progress=None,
) -> dict[pd.Timestamp, dict[str, Any]]:
    frame = _prepare_frame(data)
    table: dict[pd.Timestamp, dict[str, Any]] = {}
    for timestamp, row in frame.iterrows():
        table[pd.Timestamp(timestamp)] = {
            str(column): value
            for column, value in row.items()
        }
        if progress is not None:
            progress.update(1)
    return table


def _to_frame(data: pd.Series | pd.DataFrame) -> pd.DataFrame:
    if isinstance(data, pd.Series):
        return data.to_frame(name=str(data.name or "value"))
    if isinstance(data, pd.DataFrame):
        return data.copy()
    raise TypeError(f"Expected Series or DataFrame, got {type(data)!r}")


def _prepare_frame(data: pd.Series | pd.DataFrame) -> pd.DataFrame:
    frame = _to_frame(data)
    return frame.sort_index()


def _extract_index(data: pd.Series | pd.DataFrame) -> pd.DatetimeIndex:
    frame = _prepare_frame(data)
    return pd.DatetimeIndex(frame.index)


def _lookup_table_entry(
    table: Optional[Mapping[pd.Timestamp, Mapping[str, Any]]],
    timestamp: Any,
) -> tuple[Optional[pd.Timestamp], Optional[dict[str, Any]]]:
    if table is None:
        return None, None
    ts = pd.Timestamp(timestamp)
    direct = table.get(ts)
    if direct is not None:
        return ts, dict(direct)

    if ts.tzinfo is not None:
        naive = ts.tz_localize(None)
        direct = table.get(naive)
        if direct is not None:
            return naive, dict(direct)

    for key, value in table.items():
        key_ts = pd.Timestamp(key)
        if key_ts == ts:
            return key_ts, dict(value)
        if key_ts.tzinfo is not None and ts.tzinfo is None and key_ts.tz_localize(None) == ts:
            return key_ts, dict(value)
        if key_ts.tzinfo is None and ts.tzinfo is not None and key_ts == ts.tz_localize(None):
            return key_ts, dict(value)

    return None, None


def _positions_changed(current: Mapping[str, int], previous: Mapping[str, int]) -> bool:
    all_keys = set(current) | set(previous)
    return any(int(current.get(key, 0)) != int(previous.get(key, 0)) for key in all_keys)


def _coerce_position(value: Any) -> int:
    if pd.isna(value):
        raise ValueError("Position table should not contain NaN values.")
    return int(np.sign(float(value)))


def _cached_coverage_index(
    *,
    position_frame: pd.DataFrame,
    desired_frame: pd.DataFrame,
    indicator_frame: pd.DataFrame,
    raw_frame: pd.DataFrame,
    trade_query_factory: Callable[..., Any],
    mdp,
    signal_key_fn: Optional[Callable[..., str]],
    show_progress: bool,
    strategy_name: str,
) -> pd.DatetimeIndex:
    if not callable(getattr(mdp, "bulk_get_data", None)):
        return pd.DatetimeIndex(position_frame.index)

    request_families = _discover_request_families(
        position_frame=position_frame,
        desired_frame=desired_frame,
        indicator_frame=indicator_frame,
        raw_frame=raw_frame,
        trade_query_factory=trade_query_factory,
        signal_key_fn=signal_key_fn,
    )
    if not request_families:
        return pd.DatetimeIndex(position_frame.index)

    coverage = set(pd.DatetimeIndex(position_frame.index))
    coverage_progress = _tqdm(
        total=len(request_families),
        desc=f"{strategy_name.upper()} CACHE",
        disable=not show_progress,
        dynamic_ncols=True,
        leave=False,
    )
    with coverage_progress as progress:
        for family in request_families:
            reference_points = _prefetch_reference_points_for_request(family["sample_request"], position_frame.index)
            if not reference_points:
                progress.update(1)
                continue
            bulk_request = dict(family["base_request"])
            bulk_request["timestamps"] = reference_points
            bulk_request["ignore_cache_miss"] = True
            hits = mdp.bulk_get_data(bulk_request)
            family_index = _covered_index_from_hits(
                hits,
                position_frame.index,
                sample_request=family["sample_request"],
            )
            coverage &= set(family_index)
            progress.update(1)
    return pd.DatetimeIndex(sorted(coverage))


def _discover_request_families(
    *,
    position_frame: pd.DataFrame,
    desired_frame: pd.DataFrame,
    indicator_frame: pd.DataFrame,
    raw_frame: pd.DataFrame,
    trade_query_factory: Callable[..., Any],
    signal_key_fn: Optional[Callable[..., str]],
) -> list[dict[str, Any]]:
    families: dict[tuple[tuple[str, Any], ...], dict[str, Any]] = {}
    for timestamp, row in position_frame.iterrows():
        target_positions = {
            str(column): _coerce_position(value)
            for column, value in row.items()
            if not pd.isna(value)
        }
        desired_positions = {
            str(column): _coerce_position(value)
            for column, value in desired_frame.loc[timestamp].items()
            if not pd.isna(value)
        } if timestamp in desired_frame.index else {}
        indicator_row = {
            str(column): value
            for column, value in indicator_frame.loc[timestamp].items()
        } if timestamp in indicator_frame.index else {}
        raw_row = {
            str(column): value
            for column, value in raw_frame.loc[timestamp].items()
        } if timestamp in raw_frame.index else {}

        for raw_signal_key, target_position in target_positions.items():
            if target_position == 0:
                continue
            item_info = {
                "signal_timestamp": pd.Timestamp(timestamp),
                "target_positions": dict(target_positions),
                "desired_positions": dict(desired_positions),
                "indicator_row": dict(indicator_row),
                "raw_row": dict(raw_row),
                "raw_signal_key": str(raw_signal_key),
                "target_position": int(target_position),
            }
            signal_key = str(raw_signal_key)
            if signal_key_fn is not None:
                signal_key = str(
                    _invoke_callable(
                        signal_key_fn,
                        raw_signal_key=str(raw_signal_key),
                        target_position=int(target_position),
                        info=item_info,
                    )
                )
            item_info["signal_key"] = signal_key
            built_queries = _normalize_built_queries(
                _invoke_callable(
                    trade_query_factory,
                    target_position=int(target_position),
                    now=timestamp,
                    info=item_info,
                )
            )
            for payload in built_queries:
                sample_request = dict(payload.query.build_mdp_request(timestamp))
                base_request = {key: value for key, value in sample_request.items() if key != "timestamp"}
                family_key = tuple((key, repr(base_request[key])) for key in sorted(base_request))
                families.setdefault(
                    family_key,
                    {
                        "base_request": base_request,
                        "sample_request": sample_request,
                    },
                )
    return list(families.values())


def _prefetch_reference_points_for_request(sample_request: Mapping[str, Any], time_index: pd.Index) -> list[Any]:
    timestamp = sample_request.get("timestamp")
    if isinstance(timestamp, datetime.datetime):
        return list(pd.DatetimeIndex(time_index).to_pydatetime())
    if isinstance(timestamp, datetime.date):
        dates: list[datetime.date] = []
        seen: set[datetime.date] = set()
        for ts in pd.DatetimeIndex(time_index):
            ref_date = ts.date()
            if ref_date not in seen:
                seen.add(ref_date)
                dates.append(ref_date)
        return dates
    return []


def _covered_index_from_hits(
    hits: Mapping[Any, Any],
    full_index: pd.Index,
    *,
    sample_request: Mapping[str, Any],
) -> pd.DatetimeIndex:
    if not hits:
        return pd.DatetimeIndex([])
    use_date_keys = isinstance(sample_request.get("timestamp"), datetime.date) and not isinstance(
        sample_request.get("timestamp"),
        datetime.datetime,
    )
    covered = {
        (_date_coverage_key(timestamp) if use_date_keys else _coverage_key(timestamp))
        for timestamp in hits
    }
    selected = [
        pd.Timestamp(timestamp)
        for timestamp in pd.DatetimeIndex(full_index)
        if (_date_coverage_key(timestamp) if use_date_keys else _coverage_key(timestamp)) in covered
    ]
    return pd.DatetimeIndex(selected)


def _coverage_key(timestamp: Any) -> tuple[str, Any]:
    if isinstance(timestamp, datetime.date) and not isinstance(timestamp, (datetime.datetime, pd.Timestamp)):
        return ("date", pd.Timestamp(timestamp).date())
    stamp = pd.Timestamp(timestamp)
    if stamp.tzinfo is None:
        return ("datetime", stamp.to_pydatetime().replace(microsecond=0))
    return ("datetime", stamp.tz_convert("UTC").to_pydatetime().replace(microsecond=0))


def _date_coverage_key(timestamp: Any) -> tuple[str, Any]:
    stamp = pd.Timestamp(timestamp)
    if stamp.tzinfo is None:
        return ("date", stamp.date())
    return ("date", stamp.tz_convert("UTC").date())


def _wrap_query_factory_ignore_cache_miss(query_factory: Callable[..., Any], *, enabled: bool) -> Callable[..., Any]:
    if not enabled:
        return query_factory

    def _wrapped(*, target_position, now, info):
        built_queries = _normalize_built_queries(
            _invoke_callable(
                query_factory,
                target_position=target_position,
                now=now,
                info=info,
            )
        )
        out: list[BuiltQuery] = []
        for payload in built_queries:
            query = payload.query
            market_request = dict(getattr(query, "market_request", {}) or {})
            market_request["ignore_cache_miss"] = True
            query = replace(query, market_request=market_request)
            out.append(BuiltQuery(query=query, meta=dict(payload.meta or {})))
        return out

    return _wrapped


def _invoke_callable(func: Callable[..., Any], **kwargs: Any) -> Any:
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        return func(**kwargs)

    if any(param.kind == inspect.Parameter.VAR_KEYWORD for param in signature.parameters.values()):
        return func(**kwargs)

    accepted = {
        name: value
        for name, value in kwargs.items()
        if name in signature.parameters
    }
    required_missing = [
        param
        for param in signature.parameters.values()
        if param.default is inspect._empty
        and param.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
        and param.name not in accepted
    ]
    if not required_missing:
        return func(**accepted)

    positional_params = [
        param
        for param in signature.parameters.values()
        if param.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    positional_values = list(kwargs.values())[: len(positional_params)]
    return func(*positional_values)


def _merge_tags(base_tags: Any, extra_tags: Any) -> list[str]:
    tags: list[str] = []
    for source in (base_tags or [], extra_tags or []):
        if isinstance(source, (str, bytes)):
            values = [source]
        else:
            values = list(source)
        for value in values:
            text = str(value)
            if text not in tags:
                tags.append(text)
    return tags


def _annualization_factor(index: pd.Index) -> float:
    if len(index) == 0:
        return 252.0
    session_labels = pd.Series([_session_date(ts) for ts in index], index=index)
    counts = session_labels.groupby(session_labels).size()
    bars_per_session = float(counts.median()) if not counts.empty else 1.0
    return max(1.0, bars_per_session) * 252.0


def _compute_backtest_metrics(
    *,
    pnl_series: pd.Series,
    cumulative_pnl: pd.Series,
    trade_sides: float,
    annualization_factor: float,
) -> dict[str, float]:
    pnl = pnl_series.fillna(0.0)
    cumulative = cumulative_pnl.ffill().fillna(0.0)
    std = float(pnl.std())
    sharpe = float(pnl.mean() / std * np.sqrt(annualization_factor)) if std > 0.0 else 0.0
    drawdown = cumulative - cumulative.cummax()
    return {
        "total_pnl": float(cumulative.iloc[-1]) if len(cumulative) else 0.0,
        "sharpe": sharpe,
        "max_drawdown": float(drawdown.min()) if len(drawdown) else 0.0,
        "trade_sides": float(trade_sides),
    }


def _session_date(timestamp: Any) -> Any:
    stamp = pd.Timestamp(timestamp)
    if stamp.tzinfo is None:
        return stamp.date()
    chi_stamp = stamp.tz_convert("America/Chicago")
    if chi_stamp.hour >= 17:
        return (chi_stamp + pd.Timedelta(days=1)).date()
    return chi_stamp.date()
