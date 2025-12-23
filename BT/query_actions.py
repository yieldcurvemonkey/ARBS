# BT/query_actions.py
from __future__ import annotations
from dataclasses import dataclass, replace, field
from typing import Any, Dict, List, Optional, Protocol, Type, Callable

from BT.query_order import QueryOrder, UnwindOrder
from Query.Base.BaseQuery import BaseQuery


class QAction(Protocol):
    risk: Optional[str]

    def __call__(self, *, now, backtest, info: Dict[Type, Any]) -> List[QueryOrder]: ...


@dataclass
class AddQueryAction:
    """Submit a fully-specified BaseQuery as an order."""

    query: BaseQuery
    risk: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)

    def __call__(self, *, now, backtest, info) -> List[QueryOrder]:
        return [QueryOrder(timestamp=now, query=self.query, meta={"action": "add_query"} | self.meta)]


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
