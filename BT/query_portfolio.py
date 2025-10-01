# BT/query_portfolio.py
from __future__ import annotations
import datetime
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Callable

from Query.Base._GenericPricable import _GenericPricable
from Query.Base.BaseQuery import BaseQuery


@dataclass(frozen=True)
class ResolvedQueryPosition:
    package: List[_GenericPricable]
    weights: List[float]
    opened: datetime.datetime
    source_query: BaseQuery
    meta: Dict[str, Any] = field(default_factory=dict)


class QueryPortfolio:
    def __init__(self) -> None:
        self.positions: List[ResolvedQueryPosition] = []
        self.orders_log: List[Any] = []
        self.trades_log: List[Any] = []

    def add(self, pos: ResolvedQueryPosition) -> None:
        self.positions.append(pos)

    def pop_matching(self, predicate: Callable[[ResolvedQueryPosition], bool]) -> List[ResolvedQueryPosition]:
        removed, kept = [], []
        for p in self.positions:
            try:
                match = bool(predicate(p))
            except Exception:
                match = False
            (removed if match else kept).append(p)
        self.positions = kept
        return removed

    def trade_count_between(self, start: datetime.datetime, end: datetime.datetime) -> int:
        return sum(1 for p in self.positions if start <= p.opened <= end)

    def iter_positions(self) -> Iterable[ResolvedQueryPosition]:
        return tuple(self.positions)
