from __future__ import annotations
import datetime
from dataclasses import dataclass
from typing import Iterable, List, Mapping, Optional

from BT.triggers import Trigger
from BT.query_order import QueryOrder
from MDP.MarketDataProvider import MarketDataProvider
from Query.Base.BaseQuery import BaseQuery


@dataclass
class QueryStrategy:
    name: str
    triggers: Iterable[Trigger]
    mdps: Optional[Mapping[str, MarketDataProvider]] = None
    default_mdp: Optional[MarketDataProvider] = None
    mtm_map: Optional[Mapping[str, str]] = None

    def mdp_for_query(self, query: BaseQuery) -> Optional[MarketDataProvider]:
        if self.mdps is None:
            return self.default_mdp
        mdp = self.mdps.get(query.product)
        return mdp if mdp is not None else self.default_mdp

    def mtm_handler_name_for_query(self, query: BaseQuery) -> Optional[str]:
        if self.mtm_map is None:
            return None
        return self.mtm_map.get(query.product)

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
