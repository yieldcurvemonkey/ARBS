from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from Query.USTFutureBasis._USTFutureBasisGenericPricable import _USTFutureBasisGenericPricable


@dataclass(frozen=True)
class RLUSTFutureBasisPricable(_USTFutureBasisGenericPricable):
    _future_symbol: str
    _bond_cusip: str
    _future_price: float
    _bond_clean_price: float
    _conversion_factor: float
    _contracts: int
    _bond_notional: float
    _repo_rate: Optional[float]
    _direction: int = 1

    def future_symbol(self) -> str:
        return self._future_symbol

    def bond_cusip(self) -> str:
        return self._bond_cusip

    def future_price(self) -> float:
        return self._future_price

    def bond_clean_price(self) -> float:
        return self._bond_clean_price

    def conversion_factor(self) -> float:
        return self._conversion_factor

    def contracts(self) -> int:
        return self._contracts

    def bond_notional(self) -> float:
        return self._bond_notional

    def repo_rate(self) -> Optional[float]:
        return self._repo_rate

    def direction(self) -> int:
        return self._direction
