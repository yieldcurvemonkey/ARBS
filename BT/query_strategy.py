# BT/query_strategy.py
from __future__ import annotations
import datetime
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

from BT.triggers import Trigger
from BT.query_order import QueryOrder
from MDP.MarketDataProvider import MarketDataProvider
from Query.Base.BaseQuery import BaseQuery


@dataclass
class QueryStrategy:
    name: str
    triggers: Iterable[Trigger]
    mdps: Dict[str, MarketDataProvider] = field(default_factory=dict)
    mtm_handlers: Dict[str, str] = field(default_factory=dict)

    def evaluate(self, now: datetime.datetime, backtest) -> List[QueryOrder]:
        orders: List[QueryOrder] = []
        for trig in self.triggers:
            info = trig.has_triggered(now, backtest)
            if info:
                for action in trig.actions:
                    if hasattr(action, "__call__"):
                        out = action(now=now, backtest=backtest, info=info.info)
                        if out:
                            orders.extend(out)
        return orders

    def mdp_for_query(self, query: BaseQuery, default: Optional[MarketDataProvider]) -> MarketDataProvider:
        mdp = self.mdps.get(query.product)
        if mdp is not None:
            return mdp
        if default is not None:
            return default
        raise KeyError(f"No MarketDataProvider configured for product={query.product!r}")

    def mtm_handler_for_query(self, query: BaseQuery) -> Optional[str]:
        return self.mtm_handlers.get(query.product)
