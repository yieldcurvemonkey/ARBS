from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Protocol, Type

from Query.Base._GenericPricer import _GenericPricer
from Query.Base._GenericPricable import _GenericPricable
from BT.order import Order


class Action(Protocol):
    risk: Optional[str]

    def __call__(self, *, pricer: _GenericPricer, now, backtest, info: Dict[Type, Any]) -> List[Order]: ...


@dataclass
class AddTradeAction:
    build_kwargs: Dict[str, Any]
    risk: Optional[str] = None

    def __call__(self, *, pricer: _GenericPricer, now, backtest, info) -> List[Order]:
        instr = pricer.build_pricable(**self.build_kwargs)
        return [Order(timestamp=now, instrument=instr, meta={"action": "add_trade"})]


@dataclass
class AddScaledTradeAction:
    build_kwargs: Dict[str, Any]
    scale_key: str = "scaling"
    notional_key: str = "notional"
    default_notional: float = 1.0e6
    risk: Optional[str] = None

    def __call__(self, *, pricer: _GenericPricer, now, backtest, info) -> List[Order]:
        scale = float(info.get(AddScaledTradeAction, {}).get(self.scale_key, 1.0))
        kwargs = dict(self.build_kwargs)
        base_notional = float(kwargs.get(self.notional_key, self.default_notional))
        kwargs[self.notional_key] = base_notional * scale
        instr = pricer.build_pricable(**kwargs)
        return [Order(timestamp=now, instrument=instr, meta={"action": "add_scaled", "scale": scale})]


@dataclass
class HedgeAction:
    risk_name: str
    hedge_builder: Callable[[_GenericPricer, float], _GenericPricable]
    risk: Optional[str] = None

    def __call__(self, *, pricer: _GenericPricer, now, backtest, info) -> List[Order]:
        exposure = backtest.get_strategy_risk(self.risk_name)
        instr = self.hedge_builder(pricer, -float(exposure))
        return [Order(timestamp=now, instrument=instr, meta={"action": "hedge", "risk": self.risk_name})]
