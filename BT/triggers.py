# BT/triggers.py
from __future__ import annotations
import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Callable, ClassVar, Dict, Iterable, List, Optional, Sequence, Tuple, Type, Union
import math
import statistics as stats

from BT.event import TriggerInfo
from BT.actions import Action, AddTradeAction, AddScaledTradeAction, HedgeAction
from BT.order import Order

# ---------------- Base Requirements ----------------


class TriggerRequirements:
    calc_type: str = "point_in_time"

    def has_triggered(self, state: dt.datetime, backtest=None) -> TriggerInfo:
        raise NotImplementedError

    def get_trigger_times(self) -> List[dt.time]:
        return []  # overridden by intraday/periodic


# ---------------- Trigger Base ----------------


@dataclass
class Trigger:
    trigger_requirements: TriggerRequirements
    actions: Union[Action, Iterable[Action], None] = None
    __sub_classes: ClassVar[List[type]] = []

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        Trigger.__sub_classes.append(cls)

    @staticmethod
    def sub_classes():
        return tuple(Trigger.__sub_classes)

    def __post_init__(self):
        if self.actions is None:
            self.actions = []  # actions optional
        if not isinstance(self.actions, list):
            self.actions = [self.actions]  # normalize to list

    def has_triggered(self, state: dt.datetime, backtest=None) -> TriggerInfo:
        # matches GSQuant pattern delegating to requirements :contentReference[oaicite:4]{index=4}
        return self.trigger_requirements.has_triggered(state, backtest)

    def get_trigger_times(self) -> List[dt.time]:
        return self.trigger_requirements.get_trigger_times()

    @property
    def calc_type(self):  # parity with GSQuant API :contentReference[oaicite:5]{index=5}
        return self.trigger_requirements.calc_type

    @property
    def risks(self):
        # aligns with GSQuant property behavior :contentReference[oaicite:6]{index=6}
        return [x.risk for x in self.actions if getattr(x, "risk", None) is not None]


# ---------------- Concrete Requirements ----------------


# 1) Periodic / IntradayPeriodic
@dataclass
class PeriodicTriggerRequirements(TriggerRequirements):
    dates: Sequence[dt.date]  # explicit dates
    calc_type: str = "calendar"

    def has_triggered(self, state: dt.datetime, backtest=None) -> TriggerInfo:
        trig = state.date() in set(self.dates)
        return TriggerInfo(trig)


@dataclass
class IntradayTriggerRequirements(TriggerRequirements):
    times: Sequence[dt.time]  # e.g., [09:30, 10:00, ...]
    calc_type: str = "intraday"

    def get_trigger_times(self) -> List[dt.time]:
        return list(self.times)

    def has_triggered(self, state: dt.datetime, backtest=None) -> TriggerInfo:
        return TriggerInfo(state.time() in self.times)


# 2) MktTrigger (signal/operator on a data coordinate)
@dataclass
class MktTriggerRequirements(TriggerRequirements):
    fetch: Callable[[dt.datetime], Optional[float]]  # e.g., lambda t: md_series.loc[t]
    op: Callable[[float, float], bool]  # e.g., operator.gt
    threshold: float
    calc_type: str = "market"

    def has_triggered(self, state: dt.datetime, backtest=None) -> TriggerInfo:
        v = self.fetch(state)
        return TriggerInfo(v is not None and self.op(float(v), float(self.threshold)))


# 3) StrategyRiskTrigger (risk exceeding threshold)
@dataclass
class RiskTriggerRequirements(TriggerRequirements):
    risk: str
    op: Callable[[float, float], bool]
    threshold: float
    calc_type: str = "risk"

    def has_triggered(self, state: dt.datetime, backtest=None) -> TriggerInfo:
        val = backtest.get_strategy_risk(self.risk)
        return TriggerInfo(self.op(val, self.threshold))


# 4) Aggregate / Not
@dataclass
class AggregateTriggerRequirements(TriggerRequirements):
    triggers: List[Trigger]  # AND / OR on sub-triggers
    mode: str = "any"  # "any" == OR, "all" == AND
    calc_type: str = "aggregate"

    def has_triggered(self, state: dt.datetime, backtest=None) -> TriggerInfo:
        infos = [t.has_triggered(state, backtest) for t in self.triggers]
        trig = all(bool(i) for i in infos) if self.mode == "all" else any(bool(i) for i in infos)
        # Merge action info maps by type
        info_map: Dict[Type, Any] = {}
        for i in infos:
            info_map.update(i.info)
        return TriggerInfo(trig, info_map)


@dataclass
class NotTriggerRequirements(TriggerRequirements):
    trigger: Trigger
    calc_type: str = "not"

    def has_triggered(self, state: dt.datetime, backtest=None) -> TriggerInfo:
        child = self.trigger.has_triggered(state, backtest)
        return TriggerInfo(not bool(child), child.info)


# 5) DateTrigger
@dataclass
class DateTriggerRequirements(TriggerRequirements):
    dates: Sequence[dt.date]
    calc_type: str = "date"

    def has_triggered(self, state: dt.datetime, backtest=None) -> TriggerInfo:
        return TriggerInfo(state.date() in set(self.dates))


# 6) PortfolioTrigger (holdings/order book predicate)
@dataclass
class PortfolioTriggerRequirements(TriggerRequirements):
    predicate: Callable[[Any], bool]  # backtest -> bool
    calc_type: str = "portfolio"

    def has_triggered(self, state: dt.datetime, backtest=None) -> TriggerInfo:
        return TriggerInfo(self.predicate(backtest))


# 7) MeanReversionTrigger (z-score of series)
@dataclass
class MeanReversionTriggerRequirements(TriggerRequirements):
    fetch: Callable[[dt.datetime], Optional[float]]
    lookback: int
    z_entry: float
    calc_type: str = "stat"

    def has_triggered(self, state: dt.datetime, backtest=None) -> TriggerInfo:
        window = backtest.window(self.fetch, state, self.lookback)
        if len(window) < self.lookback or any(x is None for x in window):
            return TriggerInfo(False)
        mu = stats.mean(window)
        sd = stats.pstdev(window) or 1e-12
        z = (window[-1] - mu) / sd
        scaling = -z / self.z_entry if abs(z) >= self.z_entry else 0.0
        return TriggerInfo(abs(z) >= self.z_entry, {AddScaledTradeAction: {"scaling": scaling}})


# 8) TradeCountTrigger
@dataclass
class TradeCountTriggerRequirements(TriggerRequirements):
    lookback: dt.timedelta
    op: Callable[[int, int], bool]
    count: int
    calc_type: str = "trade_count"

    def has_triggered(self, state: dt.datetime, backtest=None) -> TriggerInfo:
        n = backtest.trade_count_since(state - self.lookback, state)
        return TriggerInfo(self.op(n, self.count))


# 9) EventTrigger (macro calendar membership)
@dataclass
class EventTriggerRequirements(TriggerRequirements):
    events_on: Callable[[dt.datetime], List[str]]  # backtest/event calendar adapter
    event_name: str
    calc_type: str = "event"

    def has_triggered(self, state: dt.datetime, backtest=None) -> TriggerInfo:
        todays = set(self.events_on(state))
        return TriggerInfo(self.event_name in todays)


# ---------------- Concrete Triggers (names mirror GSQuant) ----------------
@dataclass
class PeriodicTrigger(Trigger):
    pass  # requirements: PeriodicTriggerRequirements


@dataclass
class IntradayPeriodicTrigger(Trigger):
    pass  # requirements: IntradayTriggerRequirements


@dataclass
class MktTrigger(Trigger):
    pass  # requirements: MktTriggerRequirements


@dataclass
class StrategyRiskTrigger(Trigger):  # same risks extension as GSQuant :contentReference[oaicite:7]{index=7}
    @property
    def risks(self):
        return super().risks + [self.trigger_requirements.risk]


@dataclass
class AggregateTrigger(Trigger):
    pass  # requirements: AggregateTriggerRequirements


@dataclass
class NotTrigger(Trigger):
    pass  # requirements: NotTriggerRequirements


@dataclass
class DateTrigger(Trigger):
    pass


@dataclass
class PortfolioTrigger(Trigger):
    pass


@dataclass
class MeanReversionTrigger(Trigger):
    pass


@dataclass
class TradeCountTrigger(Trigger):
    pass


@dataclass
class EventTrigger(Trigger):
    pass


# 10) OrdersGeneratorTrigger (pattern matches GSQuant) :contentReference[oaicite:8]{index=8}
@dataclass
class OrdersGeneratorTrigger(Trigger):
    """Base class for time-grid order generation."""

    def get_trigger_times(self) -> List[dt.time]:
        return self.trigger_requirements.get_trigger_times()

    def generate_orders(self, state: dt.datetime, backtest=None) -> List[Order]:
        raise RuntimeError("generate_orders must be implemented by subclass")

    def has_triggered(self, state: dt.datetime, backtest=None) -> TriggerInfo:
        if state.time() not in self.get_trigger_times():
            return TriggerInfo(False)
        orders = self.generate_orders(state, backtest)
        info = {type(a): orders for a in (self.actions or [])} if orders else {}
        return TriggerInfo(bool(orders), info)


@dataclass
class ConstantMaturityRollTriggerRequirements(TriggerRequirements):
    timestamp: dt.datetime
    previous: Dict[str, str]
    new: Dict[str, str]
    calc_type: str = "roll_event"

    def has_triggered(self, state: dt.datetime, backtest=None) -> TriggerInfo:
        # One-shot informational trigger; always true once injected
        return TriggerInfo(True, {"roll": {"ts": self.timestamp, "previous": self.previous, "new": self.new}})


@dataclass
class ConstantMaturityRollTrigger(Trigger):
    pass  # requirements: ConstantMaturityRollTriggerRequirements
