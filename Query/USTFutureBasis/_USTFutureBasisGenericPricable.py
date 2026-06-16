from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from Query.Base._GenericPricable import _GenericPricable


class _USTFutureBasisGenericPricable(_GenericPricable, ABC):
    """Trade ticket for a single Treasury-futures basis position.

    A basis position is: a cash bond leg (the CTD by default, or an explicit
    deliverable) versus ``contracts`` futures, CF-weighted. ``direction`` is +1 for
    LONG the basis (buy cash / sell futures = cash-and-carry) and -1 for SHORT the
    basis (sell cash / buy futures).
    """

    @abstractmethod
    def future_symbol(self) -> str: ...

    @abstractmethod
    def bond_cusip(self) -> str: ...

    @abstractmethod
    def future_price(self) -> float: ...

    @abstractmethod
    def bond_clean_price(self) -> float: ...

    @abstractmethod
    def conversion_factor(self) -> float: ...

    @abstractmethod
    def contracts(self) -> int: ...

    @abstractmethod
    def bond_notional(self) -> float: ...

    @abstractmethod
    def repo_rate(self) -> Optional[float]: ...

    @abstractmethod
    def direction(self) -> int: ...
