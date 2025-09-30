# BT/strategy.py
from __future__ import annotations
import datetime as dt
from dataclasses import dataclass
from typing import Iterable, List

from BT.triggers import Trigger
from BT.order import Order

@dataclass
class Strategy:
    name: str
    triggers: Iterable[Trigger]

    def evaluate(self, now: dt.datetime, backtest) -> List[Order]:
        orders: List[Order] = []
        for trig in self.triggers:
            info = trig.has_triggered(now, backtest)
            if info:
                for action in trig.actions:
                    orders.extend(action(pricer=backtest._current_pricer(), now=now, backtest=backtest, info=info.info))
        return orders
