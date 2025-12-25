import datetime
from dataclasses import dataclass
from typing import Any, Optional, Union

import rateslib as rl

from Query.USTFutures._USTFutureGenericPricer import _USTFutureGenericPricer
from Query.USTFutures.backends.rateslib.RLUSTFuturePricable import RLUSTFuturePricable


@dataclass
class RLUSTFuturePricer(_USTFutureGenericPricer):
    _symbol: str
    _reference_date: datetime.date
    _price: float
    _contracts: int
    _notional: float
    _dv01_per_contract: float
    _meta_data: Any

    def __init__(
        self,
        symbol: str,
        reference_date: Union[datetime.date, datetime.datetime],
        price: float,
        contracts: Optional[int] = None,
        notional: Optional[float] = None,
        dv01_per_contract: Optional[float] = None,
        meta_data: Optional[Any] = None,
    ):
        self._symbol = symbol
        self._reference_date = reference_date.date() if isinstance(reference_date, datetime.datetime) else reference_date
        self._price = float(price)
        self._contracts = int(contracts or 1)
        self._notional = float(notional or 100_000.0)
        self._dv01_per_contract = float(dv01_per_contract or 1.0)
        self._meta_data = meta_data or {}

    def id(self) -> str:
        return self._symbol

    def reference_date(self) -> datetime.date:
        return self._reference_date

    def meta(self) -> Any:
        return self._meta_data

    def effective_date(self, ustf: RLUSTFuturePricable) -> datetime.date:
        return ustf.effective_date()

    def maturity_date(self, ustf: RLUSTFuturePricable) -> datetime.date:
        return ustf.maturity_date()

    def price(self, ustf: RLUSTFuturePricable) -> float:
        return float(ustf.price())

    def yield_to_maturity(self, ustf: RLUSTFuturePricable) -> float:
        if isinstance(self._meta_data, dict):
            val = self._meta_data.get("yield")
            if val is not None:
                return float(val)
        return 0.0

    def pv01(self, ustf: RLUSTFuturePricable) -> float:
        return float(self._dv01_per_contract * ustf.contracts())

    def dv01(self, ustf: RLUSTFuturePricable) -> float:
        return self.pv01(ustf)

    def npv(self, instrument: RLUSTFuturePricable, /, **kwargs: Any) -> float:
        return self.price(instrument) * self.pv01(instrument)

    def resolve_pricable(self, priceable: RLUSTFuturePricable, risk_weight: Optional[float] = None) -> RLUSTFuturePricable:
        if risk_weight is None:
            return priceable
        if risk_weight >= 0:
            return priceable
        return RLUSTFuturePricable(
            _contract_code=priceable.contract_code(),
            _effective_date=priceable.effective_date(),
            _maturity_date=priceable.maturity_date(),
            _price=priceable.price(),
            _contracts=-abs(priceable.contracts()),
            _notional=priceable.notional(),
        )

    def build_pricable(self, /, **kwargs: Any) -> RLUSTFuturePricable:
        return self.build_ustf(
            contract_code=kwargs.get("contract_code"),
            effective_date=kwargs.get("effective_date"),
            maturity_date=kwargs.get("maturity_date"),
            price=kwargs.get("price"),
            contracts=kwargs.get("contracts"),
            notional=kwargs.get("notional"),
        )

    def build_ustf(
        self,
        contract_code: Optional[str] = None,
        effective_date: Optional[datetime.date] = None,
        maturity_date: Optional[datetime.date] = None,
        price: Optional[float] = None,
        contracts: Optional[int] = None,
        notional: Optional[float] = None,
        **kwargs: Any,
    ) -> RLUSTFuturePricable:
        eff = effective_date or self.reference_date()
        mat = maturity_date or self.reference_date()
        return RLUSTFuturePricable(
            _contract_code=contract_code or self._symbol,
            _effective_date=eff,
            _maturity_date=mat,
            _price=float(price if price is not None else self._price),
            _contracts=int(contracts or self._contracts),
            _notional=float(notional or self._notional),
        )

    def _to_rl_dt(self, pydate: datetime.date) -> rl.dt:
        return rl.dt(pydate.year, pydate.month, pydate.day)
