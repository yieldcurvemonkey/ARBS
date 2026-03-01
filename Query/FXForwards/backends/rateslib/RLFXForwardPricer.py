import datetime
from dataclasses import dataclass
from typing import Any, Optional

from Query.Base._GenericPricable import _GenericPricable
from Query.FXForwards._FXForwardGenericPricer import _FXForwardGenericPricer


@dataclass
class RLFXForwardPricer(_FXForwardGenericPricer):
    _pair: str
    _symbol: str
    _tenor: str
    _settlement_date: datetime.date
    _quote_timestamp: datetime.datetime

    _spot: float
    _points_raw: float
    _points_decimal: float
    _forward_rate: float

    _basis_bps: Optional[float]
    _fx_rates: Any
    _fx_forwards: Any
    _meta_data: Any

    def __init__(
        self,
        pair: str,
        symbol: str,
        tenor: str,
        settlement_date: datetime.date,
        quote_timestamp: datetime.datetime,
        spot: float,
        points_raw: float,
        points_decimal: float,
        forward_rate: float,
        basis_bps: Optional[float] = None,
        fx_rates: Any = None,
        fx_forwards: Any = None,
        meta_data: Optional[Any] = None,
    ):
        self._pair = str(pair).upper()
        self._symbol = str(symbol).upper()
        self._tenor = str(tenor).upper()
        self._settlement_date = settlement_date
        self._quote_timestamp = quote_timestamp

        self._spot = float(spot)
        self._points_raw = float(points_raw)
        self._points_decimal = float(points_decimal)
        self._forward_rate = float(forward_rate)

        self._basis_bps = None if basis_bps is None else float(basis_bps)
        self._fx_rates = fx_rates
        self._fx_forwards = fx_forwards
        self._meta_data = meta_data or {}

    def id(self) -> str:
        return self._symbol

    def pair(self) -> str:
        return self._pair

    def symbol(self) -> str:
        return self._symbol

    def tenor(self) -> str:
        return self._tenor

    def settlement_date(self) -> datetime.date:
        return self._settlement_date

    def quote_timestamp(self) -> datetime.datetime:
        return self._quote_timestamp

    def spot(self) -> float:
        return self._spot

    def points_raw(self) -> float:
        return self._points_raw

    def points_decimal(self) -> float:
        return self._points_decimal

    def forward_rate(self) -> float:
        return self._forward_rate

    def basis_bps(self) -> Optional[float]:
        return self._basis_bps

    def fx_rates(self) -> Any:
        return self._fx_rates

    def fx_forwards(self) -> Any:
        return self._fx_forwards

    def meta(self) -> Any:
        return self._meta_data

    def npv(self, instrument: _GenericPricable, /, **kwargs: Any) -> float:
        _ = instrument, kwargs
        return float(self._forward_rate)

    def build_pricable(self, /, **kwargs: Any) -> _GenericPricable:
        _ = kwargs
        raise NotImplementedError("RLFXForwardPricer does not expose a standalone rateslib pricable.")

    def resolve_pricable(self, priceable: Any, risk_weight: Optional[float] = None) -> Any:
        _ = risk_weight
        return priceable
