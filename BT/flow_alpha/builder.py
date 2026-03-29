from __future__ import annotations

import datetime as dt
import inspect
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Optional

import QuantLib as ql

from BT.data_handler import TimeGrid
from BT.flow_alpha.models import EventSource, KnownDemandEvent, StateSignalSource
from BT.flow_alpha.window_rules import WindowRule, default_rates_calendar
from BT.misc import ql_cal_date_range
from BT.query_actions import AddQueryFactoryAction, BuiltQuery, UnwindPositionsAction
from BT.query_strategy import QueryStrategy
from BT.triggers import DateTrigger, DateTriggerRequirements, FlowSignalTriggerRequirements, Trigger


def _invoke_factory(factory: Callable[..., Any], **kwargs: Any) -> Any:
    try:
        sig = inspect.signature(factory)
    except (TypeError, ValueError):
        return factory(**kwargs)

    if any(param.kind == inspect.Parameter.VAR_KEYWORD for param in sig.parameters.values()):
        return factory(**kwargs)

    accepted = {name: value for name, value in kwargs.items() if name in sig.parameters}
    return factory(**accepted)


@dataclass(frozen=True)
class FlowAlphaStrategySpec:
    name: str
    source: EventSource | StateSignalSource
    query_factory: Callable[..., Any]
    window_rule: Optional[WindowRule] = None
    tag_template: str = "{family}-{anchor_date:%Y%m%d}-{event_id}"
    calendar: Optional[ql.Calendar] = None
    mdps: Optional[Mapping[str, Any]] = None
    default_mdp: Optional[Any] = None
    mtm_map: Optional[Mapping[str, str]] = None
    unwind_fee: float = 0.0
    order_meta_factory: Optional[Callable[..., Mapping[str, Any]]] = None
    state_exit_selector: Optional[Callable[[Any], bool]] = None


def _format_tag(spec: FlowAlphaStrategySpec, event: KnownDemandEvent) -> str:
    return spec.tag_template.format(
        event_id=event.event_id,
        family=event.family,
        anchor_date=event.anchor_date,
        entry_date=event.entry_date or event.anchor_date,
        exit_date=event.exit_date or event.anchor_date,
        source=event.source,
        asset_class=event.asset_class,
    )


def _build_order_meta(
    spec: FlowAlphaStrategySpec,
    *,
    event: Optional[KnownDemandEvent] = None,
    tag: Optional[str] = None,
    now: Optional[dt.datetime] = None,
    backtest=None,
    info: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    base = {"flow_alpha_strategy": spec.name}
    if tag is not None:
        base["tags"] = [tag]
        base["flow_alpha_tag"] = tag
    if event is not None:
        base["flow_alpha_event_id"] = event.event_id
        base["flow_alpha_family"] = event.family
        base["flow_alpha_source"] = event.source
    elif info is not None:
        family = info.get("flow_alpha_family")
        if family:
            base["flow_alpha_family"] = family
    if spec.order_meta_factory is None:
        return base
    extra = dict(
        _invoke_factory(
            spec.order_meta_factory,
            event=event,
            tag=tag,
            now=now,
            backtest=backtest,
            info=info or {},
        )
        or {}
    )
    if "tags" in extra and "tags" in base:
        extra["tags"] = list(dict.fromkeys(list(base["tags"]) + list(extra.get("tags") or [])))
    return base | extra


def _normalize_query_payloads(
    built: Any,
    *,
    spec: FlowAlphaStrategySpec,
    event: Optional[KnownDemandEvent],
    tag: Optional[str],
    now: dt.datetime,
    backtest,
    info: dict[str, Any],
) -> list[BuiltQuery]:
    from BT.query_actions import _normalize_built_queries

    payloads = _normalize_built_queries(built)
    out: list[BuiltQuery] = []
    for payload in payloads:
        meta = _build_order_meta(spec, event=event, tag=tag, now=now, backtest=backtest, info=info) | dict(payload.meta or {})
        out.append(BuiltQuery(query=payload.query, meta=meta))
    return out


def _event_query_factory(spec: FlowAlphaStrategySpec, event: KnownDemandEvent, tag: str) -> Callable[..., Iterable[BuiltQuery]]:
    def _factory(*, now, backtest, info):
        built = _invoke_factory(
            spec.query_factory,
            event=event,
            tag=tag,
            now=now,
            backtest=backtest,
            info=info,
        )
        return _normalize_query_payloads(
            built,
            spec=spec,
            event=event,
            tag=tag,
            now=now,
            backtest=backtest,
            info=info,
        )

    return _factory


def _state_query_factory(spec: FlowAlphaStrategySpec) -> Callable[..., Iterable[BuiltQuery]]:
    def _factory(*, now, backtest, info):
        signal_info = dict(info or {})
        tag = signal_info.get("flow_alpha_tag") or f"{spec.name}-{now:%Y%m%d}"
        built = _invoke_factory(
            spec.query_factory,
            signal=signal_info.get("flow_signal"),
            tag=tag,
            now=now,
            backtest=backtest,
            info=signal_info,
        )
        return _normalize_query_payloads(
            built,
            spec=spec,
            event=None,
            tag=tag,
            now=now,
            backtest=backtest,
            info=signal_info,
        )

    return _factory


def _build_time_grid(
    start: dt.date,
    end: dt.date,
    *,
    calendar: ql.Calendar,
    freq: str = "1b",
) -> TimeGrid:
    states = ql_cal_date_range(
        ql_cal=calendar,
        start=dt.datetime.combine(start, dt.time()),
        end=dt.datetime.combine(end, dt.time()),
        freq=freq,
    )
    return TimeGrid(states)


def build_query_strategy(
    spec: FlowAlphaStrategySpec,
    start: dt.date,
    end: dt.date,
    *,
    ql_cal: Optional[ql.Calendar] = None,
    grid_freq: str = "1b",
    **kwargs: Any,
) -> tuple[QueryStrategy, list[KnownDemandEvent], TimeGrid]:
    calendar = ql_cal or spec.calendar or default_rates_calendar()

    if isinstance(spec.source, EventSource):
        events = spec.source.materialize(start, end, **kwargs)
        if spec.window_rule is not None:
            events = [spec.window_rule.apply(event, calendar=calendar) for event in events]
        events = [
            event
            for event in events
            if (event.entry_date or event.anchor_date) >= start
            and (event.exit_date or event.entry_date or event.anchor_date) <= end
        ]
        events = sorted(events, key=lambda event: (event.entry_date or event.anchor_date, event.exit_date or event.anchor_date, event.event_id))

        triggers: list[Trigger] = []
        for event in events:
            entry_date = event.entry_date or event.anchor_date
            exit_date = event.exit_date or entry_date
            tag = _format_tag(spec, event)
            info = {
                "flow_event": event,
                "flow_alpha_tag": tag,
                "flow_alpha_family": event.family,
            }
            triggers.append(
                DateTrigger(
                    DateTriggerRequirements(dates=[entry_date], info=info),
                    actions=[AddQueryFactoryAction(query_factory=_event_query_factory(spec, event, tag))],
                )
            )
            if exit_date >= entry_date:
                triggers.append(
                    DateTrigger(
                        DateTriggerRequirements(dates=[exit_date], info=info),
                        actions=[UnwindPositionsAction(match_tag=tag, fee=spec.unwind_fee)],
                    )
                )

        grid_start = min((event.entry_date or event.anchor_date) for event in events) if events else start
        grid_end = max((event.exit_date or event.entry_date or event.anchor_date) for event in events) if events else end
        time_grid = _build_time_grid(grid_start, grid_end, calendar=calendar, freq=grid_freq)
        strategy = QueryStrategy(
            name=spec.name,
            triggers=triggers,
            mdps=spec.mdps,
            default_mdp=spec.default_mdp,
            mtm_map=spec.mtm_map,
        )
        return strategy, events, time_grid

    if isinstance(spec.source, StateSignalSource):
        entry_trigger = Trigger(
            FlowSignalTriggerRequirements(
                signal_fn=lambda state, backtest: spec.source.signal(state, backtest=backtest, **kwargs)
            ),
            actions=[AddQueryFactoryAction(query_factory=_state_query_factory(spec))],
        )
        selector = spec.state_exit_selector or (lambda pos: pos.meta.get("flow_alpha_strategy") == spec.name)
        exit_trigger = Trigger(
            FlowSignalTriggerRequirements(
                signal_fn=lambda state, backtest: spec.source.exit_signal(state, backtest=backtest, **kwargs)
            ),
            actions=[UnwindPositionsAction(selector=selector, fee=spec.unwind_fee)],
        )
        strategy = QueryStrategy(
            name=spec.name,
            triggers=[entry_trigger, exit_trigger],
            mdps=spec.mdps,
            default_mdp=spec.default_mdp,
            mtm_map=spec.mtm_map,
        )
        return strategy, [], _build_time_grid(start, end, calendar=calendar, freq=grid_freq)

    raise TypeError(f"Unsupported source type: {type(spec.source)!r}")
