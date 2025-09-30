# BT/query_actions.py
from __future__ import annotations
from dataclasses import dataclass, replace
from typing import Any, Dict, List, Optional, Protocol, Type

from BT.query_order import QueryOrder
from Query.Base.BaseQuery import BaseQuery


class QAction(Protocol):
    risk: Optional[str]
    def __call__(self, *, now, backtest, info: Dict[Type, Any]) -> List[QueryOrder]: ...


@dataclass
class AddQueryAction:
    """Submit a fully-specified BaseQuery as an order."""
    query: BaseQuery
    risk: Optional[str] = None

    def __call__(self, *, now, backtest, info) -> List[QueryOrder]:
        return [QueryOrder(timestamp=now, query=self.query, meta={"action": "add_query"})]


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
