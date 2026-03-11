from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Optional

from Query.STIRFutureOptions._STIRFutureOptionGenericPricable import _STIRFutureOptionGenericPricable
from Query.STIRFutureOptions._STIRFutureOptionGenericPricer import _STIRFutureOptionGenericPricer
from Query.STIRFutureOptions._risk import dollar_dv01, dollar_gamma_01, dollar_vega_01


@dataclass(frozen=True)
class STIRCapFloorLegPricable(_STIRFutureOptionGenericPricable):
    _symbol: str
    _right: str
    _strike: float
    _expiry_date: dt.date
    _quote_timestamp: dt.datetime
    _quantity: float
    _unit_quantity: float
    _underlying_contract: str
    _reference_quarter_start: dt.date
    _reference_quarter_end: dt.date
    _strike_rate: float
    _requested_symbol: str
    _requested_strike_price: float
    _requested_strike_rate: float
    _economic_weight: float
    _quote_source: str
    _quarter_end_flag: bool
    _fomc_loading: float
    _meta_data: dict[str, Any] = field(default_factory=dict)

    def symbol(self) -> str:
        return self._symbol

    def right(self) -> str:
        return self._right

    def strike(self) -> float:
        return self._strike

    def expiry_date(self) -> dt.date:
        return self._expiry_date

    def quote_timestamp(self) -> dt.datetime:
        return self._quote_timestamp

    def quantity(self) -> float:
        return self._quantity

    def unit_quantity(self) -> float:
        return self._unit_quantity

    def underlying_contract(self) -> str:
        return self._underlying_contract

    def reference_quarter_start(self) -> dt.date:
        return self._reference_quarter_start

    def reference_quarter_end(self) -> dt.date:
        return self._reference_quarter_end

    def strike_rate(self) -> float:
        return self._strike_rate

    def requested_symbol(self) -> str:
        return self._requested_symbol

    def requested_strike_price(self) -> float:
        return self._requested_strike_price

    def requested_strike_rate(self) -> float:
        return self._requested_strike_rate

    def economic_weight(self) -> float:
        return self._economic_weight

    def quote_source(self) -> str:
        return self._quote_source

    def quarter_end_flag(self) -> bool:
        return self._quarter_end_flag

    def fomc_loading(self) -> float:
        return self._fomc_loading

    def meta(self) -> dict[str, Any]:
        return dict(self._meta_data or {})


@dataclass(frozen=True)
class STIRCapFloorLegMarket:
    option_symbol: str
    requested_symbol: str
    right: str
    underlying_contract: str
    reference_quarter_start: dt.date
    reference_quarter_end: dt.date
    strike_price: float
    strike_rate: float
    requested_strike_price: float
    requested_strike_rate: float
    economic_weight: float
    unit_quantity: float
    quantity: float
    quote_source: str
    quarter_end_flag: bool
    fomc_loading: float
    pricer: _STIRFutureOptionGenericPricer
    metadata: dict[str, Any] = field(default_factory=dict)

    def build_pricable(self) -> STIRCapFloorLegPricable:
        return STIRCapFloorLegPricable(
            _symbol=str(self.option_symbol),
            _right=str(self.right),
            _strike=float(self.strike_price),
            _expiry_date=self.pricer.expiry_date(),
            _quote_timestamp=self.pricer.quote_timestamp(),
            _quantity=float(self.quantity),
            _unit_quantity=float(self.unit_quantity),
            _underlying_contract=str(self.underlying_contract),
            _reference_quarter_start=self.reference_quarter_start,
            _reference_quarter_end=self.reference_quarter_end,
            _strike_rate=float(self.strike_rate),
            _requested_symbol=str(self.requested_symbol),
            _requested_strike_price=float(self.requested_strike_price),
            _requested_strike_rate=float(self.requested_strike_rate),
            _economic_weight=float(self.economic_weight),
            _quote_source=str(self.quote_source),
            _quarter_end_flag=bool(self.quarter_end_flag),
            _fomc_loading=float(self.fomc_loading),
            _meta_data=dict(self.metadata or {}),
        )


def build_leg_breakdown(
    leg: STIRCapFloorLegPricable,
    pricer: _STIRFutureOptionGenericPricer,
    *,
    index: int,
    risk_weight: float = 1.0,
) -> dict[str, Any]:
    qty = float(leg.quantity())
    return {
        "index": int(index),
        "symbol": str(leg.symbol()),
        "requested_symbol": str(leg.requested_symbol()),
        "right": str(leg.right()),
        "underlying_contract": str(leg.underlying_contract()),
        "reference_quarter_start": leg.reference_quarter_start(),
        "reference_quarter_end": leg.reference_quarter_end(),
        "strike_price": float(leg.strike()),
        "strike_rate": float(leg.strike_rate()),
        "requested_strike_price": float(leg.requested_strike_price()),
        "requested_strike_rate": float(leg.requested_strike_rate()),
        "economic_weight": float(leg.economic_weight()),
        "unit_quantity": float(leg.unit_quantity()),
        "quantity": qty,
        "risk_weight": float(risk_weight),
        "price": float(pricer.price()),
        "npv": float(pricer.npv(leg)),
        "dv01": float(qty * dollar_dv01(pricer)),
        "delta": float(qty * pricer.delta()),
        "gamma": float(qty * pricer.gamma()),
        "gamma_01": float(qty * dollar_gamma_01(pricer)),
        "vega": float(qty * pricer.vega()),
        "vega_01": float(qty * dollar_vega_01(pricer)),
        "theta": float(qty * pricer.theta()),
        "iv_normal_bps": float(pricer.iv_normal_bps()),
        "forward_price": float(pricer.forward()),
        "forward_rate": float(100.0 - pricer.forward()),
        "quote_source": str(leg.quote_source()),
        "quarter_end_flag": bool(leg.quarter_end_flag()),
        "fomc_loading": float(leg.fomc_loading()),
        "metadata": {
            **leg.meta(),
            "pricer_meta": dict(pricer.meta() or {}),
        },
    }


def extract_leg_pricer(entry: Any) -> _STIRFutureOptionGenericPricer:
    candidate = entry[0] if isinstance(entry, list) and entry else entry
    if not isinstance(candidate, _STIRFutureOptionGenericPricer):
        raise TypeError(f"Expected STIR future option pricer, got {type(candidate)}")
    return candidate


def maybe_priceable_quantity(obj: Any, default: float = 1.0) -> float:
    if hasattr(obj, "quantity"):
        qty = obj.quantity
        return float(qty() if callable(qty) else qty)
    return float(default)


def leg_requested_symbol(leg: Any) -> Optional[str]:
    if hasattr(leg, "requested_symbol"):
        value = leg.requested_symbol
        return str(value() if callable(value) else value)
    return None
