from __future__ import annotations

import datetime
from dataclasses import dataclass

from Query.USTFutures._USTFutureGenericPricable import _USTFutureGenericPricable


@dataclass(frozen=True)
class RLUSTFuturePricable(_USTFutureGenericPricable):
    _contract_code: str
    _effective_date: datetime.date
    _maturity_date: datetime.date
    _price: float
    _contracts: int
    _notional: float

    def contract_code(self) -> str:
        return self._contract_code

    def effective_date(self) -> datetime.date:
        return self._effective_date

    def maturity_date(self) -> datetime.date:
        return self._maturity_date

    def price(self) -> float:
        return self._price

    def contracts(self) -> int:
        return self._contracts

    def notional(self) -> float:
        return self._notional
