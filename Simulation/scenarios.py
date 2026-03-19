from __future__ import annotations

import datetime as dt
from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from typing import Optional


@dataclass(frozen=True)
class MarketState:
    """Flat market snapshot used for analytical repricing."""

    forward: Optional[float] = None
    vol_normal: Optional[float] = None
    discount: Optional[float] = None
    tte: Optional[float] = None
    eval_date: Optional[dt.date] = None


@dataclass(frozen=True)
class ScenarioAxis(ABC):
    """Single immutable market mutation."""

    @abstractmethod
    def mutate(self, market_state: MarketState) -> MarketState:
        raise NotImplementedError


@dataclass(frozen=True)
class UnderlyingShift(ScenarioAxis):
    """Shift forward price in absolute price points."""

    shift: float = 0.0

    def mutate(self, market_state: MarketState) -> MarketState:
        if market_state.forward is None or self.shift == 0.0:
            return market_state
        return replace(market_state, forward=float(market_state.forward) + float(self.shift))


@dataclass(frozen=True)
class VolShift(ScenarioAxis):
    """Shift normal volatility in basis points."""

    shift_bps: float = 0.0

    def mutate(self, market_state: MarketState) -> MarketState:
        if market_state.vol_normal is None or self.shift_bps == 0.0:
            return market_state
        return replace(market_state, vol_normal=float(market_state.vol_normal) + float(self.shift_bps) * 0.0001)


@dataclass(frozen=True)
class TimeDecay(ScenarioAxis):
    """Advance evaluation date and reduce time-to-expiry."""

    days: int = 0

    def mutate(self, market_state: MarketState) -> MarketState:
        if self.days == 0:
            return market_state

        new_tte = market_state.tte
        if new_tte is not None:
            new_tte = max(float(new_tte) - float(self.days) / 365.0, 0.0)

        new_eval_date = market_state.eval_date
        if new_eval_date is not None:
            new_eval_date = new_eval_date + dt.timedelta(days=int(self.days))

        return replace(market_state, tte=new_tte, eval_date=new_eval_date)


@dataclass(frozen=True)
class CompositeScenario(ScenarioAxis):
    """Apply multiple scenario axes sequentially."""

    axes: tuple[ScenarioAxis, ...] = ()

    def mutate(self, market_state: MarketState) -> MarketState:
        state = market_state
        for axis in self.axes:
            state = axis.mutate(state)
        return state
