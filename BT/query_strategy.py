# BT/query_strategy.py
from __future__ import annotations
import datetime
from dataclasses import dataclass
from typing import Iterable, List

from BT.triggers import Trigger
from BT.query_order import QueryOrder


@dataclass
class QueryStrategy:
    name: str
    triggers: Iterable[Trigger]

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
