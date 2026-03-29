# BT/query_actions.py
from __future__ import annotations
from dataclasses import dataclass, replace, field
from typing import Any, Dict, Iterable, List, Optional, Protocol, Type, Callable

from BT.query_order import QueryOrder, UnwindOrder
from Query.Base.BaseQuery import BaseQuery


class QAction(Protocol):
    risk: Optional[str]

    def __call__(self, *, now, backtest, info: Dict[Type, Any]) -> List[QueryOrder]: ...


@dataclass(frozen=True)
class BuiltQuery:
    """Normalized query payload returned by factory-style actions."""

    query: BaseQuery
    meta: Dict[str, Any] = field(default_factory=dict)


def _normalize_built_queries(value: Any) -> List[BuiltQuery]:
    if value is None:
        return []
    if isinstance(value, BuiltQuery):
        return [value]
    if isinstance(value, BaseQuery):
        return [BuiltQuery(query=value)]
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes, dict)):
        out: List[BuiltQuery] = []
        for item in value:
            out.extend(_normalize_built_queries(item))
        return out
    raise TypeError(f"Unsupported query factory output type: {type(value)!r}")


@dataclass
class AddQueryAction:
    """Submit a fully-specified BaseQuery as an order."""

    query: BaseQuery
    risk: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)

    def __call__(self, *, now, backtest, info) -> List[QueryOrder]:
        return [QueryOrder(timestamp=now, query=self.query, meta={"action": "add_query"} | self.meta)]


@dataclass
class AddQueryFactoryAction:
    """Build query orders dynamically from trigger/backtest context."""

    query_factory: Callable[..., Any]
    risk: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)

    def __call__(self, *, now, backtest, info) -> List[QueryOrder]:
        built_queries = _normalize_built_queries(self.query_factory(now=now, backtest=backtest, info=info))
        orders: List[QueryOrder] = []
        for payload in built_queries:
            orders.append(
                QueryOrder(
                    timestamp=now,
                    query=payload.query,
                    meta={"action": "add_query_factory"} | self.meta | dict(payload.meta or {}),
                )
            )
        return orders


@dataclass
class AddScaledQueryAction:
    """Scale a numeric field inside query.structure_kwargs (e.g., 'bpv' or 'notional')."""

    query: BaseQuery
    target_key: str = "bpv"
    scale_key: str = "scaling"
    default_value: float = 1.0
    risk: Optional[str] = None

    def __call__(self, *, now, backtest, info) -> List[QueryOrder]:
        scale = float(info.get(AddScaledQueryAction, {}).get(self.scale_key, 1.0))
        kw = dict(self.query.structure_kwargs or {})
        base = float(kw.get(self.target_key, self.default_value))
        kw[self.target_key] = base * scale
        q2 = replace(self.query, structure_kwargs=kw)
        return [QueryOrder(timestamp=now, query=q2, meta={"action": "add_scaled", "scale": scale})]


@dataclass
class UnwindPositionsAction:
    selector: Optional[Callable[[Any], bool]] = None  # ResolvedQueryPosition -> bool
    match_all: bool = False
    match_tag: Optional[str] = None  # look in pos.meta["tags"] or query.tags
    fee: float = 0.0  # flat fee to subtract from realized P&L
    risk: Optional[str] = None

    def __call__(self, *, now, backtest, info) -> List[UnwindOrder]:
        if self.match_all:
            pred = lambda p: True
        elif self.match_tag is not None:
            tag = self.match_tag

            def pred(p):
                tags = set()
                tags.update(p.meta.get("tags", []))
                tags.update(getattr(p.source_query, "tags", ()) or ())
                return tag in tags

        elif self.selector is not None:
            pred = self.selector
        else:
            raise ValueError("Provide selector, match_all, or match_tag for UnwindPositionsAction")

        return [UnwindOrder(timestamp=now, selector=pred, meta={"action": "unwind", "fee": float(self.fee)})]
