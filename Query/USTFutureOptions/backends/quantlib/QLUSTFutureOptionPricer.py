import datetime
import math
from dataclasses import dataclass, replace
from typing import Any, Optional

from Query.USTFutureOptions._USTFutureOptionGenericPricable import _USTFutureOptionGenericPricable
from Query.USTFutureOptions._USTFutureOptionGenericPricer import _USTFutureOptionGenericPricer


@dataclass
class QLUSTFutureOptionPricable(_USTFutureOptionGenericPricable):
    _symbol: str
    _right: str
    _strike: float
    _expiry_date: datetime.date
    _quote_timestamp: datetime.datetime
    _quantity: float = 1.0
    _premium_override: Optional[float] = None

    def symbol(self) -> str:
        return self._symbol

    def right(self) -> str:
        return self._right

    def strike(self) -> float:
        return self._strike

    def expiry_date(self) -> datetime.date:
        return self._expiry_date

    def quote_timestamp(self) -> datetime.datetime:
        return self._quote_timestamp

    def quantity(self) -> float:
        return self._quantity

    def premium_override(self) -> Optional[float]:
        return self._premium_override


@dataclass
class QLUSTFutureOptionPricer(_USTFutureOptionGenericPricer):
    _symbol: str
    _right: str
    _underlying_symbol: str
    _strike: float
    _quote_timestamp: datetime.datetime
    _expiry_date: datetime.date

    _market_price: float
    _model_price: float
    _iv_normal: float
    _delta: float
    _gamma: float
    _vega: float
    _theta: float

    _forward: float
    _discount: float
    _fv01: float
    _meta_data: Any

    def __init__(
        self,
        symbol: str,
        right: str,
        underlying_symbol: str,
        strike: float,
        quote_timestamp: datetime.datetime,
        expiry_date: datetime.date,
        market_price: float,
        model_price: float,
        iv_normal: float,
        delta: float,
        gamma: float,
        vega: float,
        theta: float,
        forward: float,
        discount: float,
        fv01: float = float("nan"),
        meta_data: Optional[Any] = None,
    ):
        self._symbol = str(symbol).upper()
        self._right = str(right).upper()
        self._underlying_symbol = str(underlying_symbol).upper()
        self._strike = float(strike)
        self._quote_timestamp = quote_timestamp
        self._expiry_date = expiry_date

        self._market_price = float(market_price)
        self._model_price = float(model_price)
        self._iv_normal = float(iv_normal)
        self._delta = float(delta)
        self._gamma = float(gamma)
        self._vega = float(vega)
        self._theta = float(theta)
        self._forward = float(forward)
        self._discount = float(discount)
        self._fv01 = float(fv01) if fv01 == fv01 else float("nan")
        self._meta_data = meta_data or {}

    def id(self) -> str:
        return f"{self._symbol}@{self._quote_timestamp.isoformat()}"

    def symbol(self) -> str:
        return self._symbol

    def right(self) -> str:
        return self._right

    def underlying_symbol(self) -> str:
        return self._underlying_symbol

    def strike(self) -> float:
        return self._strike

    def quote_timestamp(self) -> datetime.datetime:
        return self._quote_timestamp

    def expiry_date(self) -> datetime.date:
        return self._expiry_date

    def price(self) -> float:
        return self._market_price

    def model_price(self) -> float:
        return self._model_price

    def iv_normal(self) -> float:
        return self._iv_normal

    def fv01(self) -> float:
        return self._fv01

    def iv_normal_bps(self) -> float:
        # Convert annualised Bachelier price-vol to yield-vol in bps.
        # fv01 = forward DV01 per bp (price change per 1 bp yield move).
        if self._fv01 > 0.0:
            return self._iv_normal / self._fv01
        return float("nan")

    def delta(self) -> float:
        return self._delta

    def gamma(self) -> float:
        return self._gamma

    def vega(self) -> float:
        return self._vega

    def theta(self) -> float:
        return self._theta

    def discount(self) -> float:
        return self._discount

    def forward(self) -> float:
        return self._forward

    def meta(self) -> Any:
        return self._meta_data

    def npv(self, instrument: _USTFutureOptionGenericPricable, /, **kwargs: Any) -> float:
        _ = kwargs
        qty = float(getattr(instrument, "quantity", lambda: 1.0)())
        return self._market_price * qty

    def build_pricable(self, /, **kwargs: Any) -> _USTFutureOptionGenericPricable:
        return QLUSTFutureOptionPricable(
            _symbol=str(kwargs.get("symbol", self._symbol)).upper(),
            _right=str(kwargs.get("right", self._right)).upper(),
            _strike=float(kwargs.get("strike", self._strike)),
            _expiry_date=kwargs.get("expiry_date", self._expiry_date),
            _quote_timestamp=kwargs.get("quote_timestamp", self._quote_timestamp),
            _quantity=float(kwargs.get("quantity", 1.0)),
            _premium_override=kwargs.get("premium_override"),
        )

    def resolve_pricable(
        self,
        priceable: _USTFutureOptionGenericPricable,
        risk_weight: Optional[float] = None,
    ) -> _USTFutureOptionGenericPricable:
        if risk_weight is None:
            return priceable
        qty = float(getattr(priceable, "quantity", lambda: 1.0)())
        target_qty = abs(qty) if risk_weight >= 0 else -abs(qty)
        if isinstance(priceable, QLUSTFutureOptionPricable):
            return replace(priceable, _quantity=target_qty)
        return self.build_pricable(
            symbol=priceable.symbol(),
            right=priceable.right(),
            strike=priceable.strike(),
            expiry_date=priceable.expiry_date(),
            quote_timestamp=priceable.quote_timestamp(),
            quantity=target_qty,
        )
