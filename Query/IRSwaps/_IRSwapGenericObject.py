# ABOUTME: Abstract interface defining methods for interest rate swap contracts
# ABOUTME: Specifies core swap operations (rates, NPV, Greeks, carry) independent of backend implementation
import datetime
from abc import ABC, abstractmethod

from Query.Base._GenericPricable import _GenericPricable


class _IRSwapGenericObject(_GenericPricable, ABC):

    @abstractmethod
    def effective_date(self) -> datetime.date: ...

    @abstractmethod
    def maturity_date(self) -> datetime.date: ...

    @abstractmethod
    def fixed_rate(self) -> float: ...

    @abstractmethod
    def set_fixed_rate(self, rate_decimal: float) -> None: ...

    @abstractmethod
    def nominal(self) -> float: ...

    @abstractmethod
    def with_notional(self, notional: float) -> "_IRSwapGenericObject": ...

    @abstractmethod
    def fair_rate(self) -> float: ...

    @abstractmethod
    def npv(self) -> float: ...

    @abstractmethod
    def pv01(self) -> float: ...

    @abstractmethod
    def dv01(self, shift: float = 1e-4) -> float: ...

    @abstractmethod
    def gamma(self, shift: float = 1e-4) -> float: ...

    @abstractmethod
    def dollar_carry(self, horizon: str) -> float: ...

    @abstractmethod
    def carry_bps_running(self, horizon: str) -> float: ...

    @abstractmethod
    def roll_bps_running(self, horizon: str) -> float: ...

    @abstractmethod
    def carry_and_roll_bps_running(self, horizon: str) -> float: ...
