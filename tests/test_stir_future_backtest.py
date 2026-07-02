import datetime

import pytest

from BT.data_handler import TimeGrid
from BT.query_actions import AddQueryAction
from BT.query_engine import QueryDrivenBacktest
from BT.query_strategy import QueryStrategy
from BT.triggers import DateTrigger, DateTriggerRequirements
from Query.STIRFutures.STIRFutureQuery import STIRFutureQuery
from Query.STIRFutures.STIRFutureStructure import STIRFutureStructure
from Query.STIRFutures.STIRFutureValue import STIRFutureValue
from Query.STIRFutures._STIRFutureGenericPricer import _STIRFutureGenericPricer
from Query.STIRFutures._STIRFutureGenericPricable import _STIRFutureGenericPricable


class _MockSTIRFuturePricable(_STIRFutureGenericPricable):
    def __init__(self, price: float = 95.125):
        self._price = float(price)
        self._fixed_rate = 100.0 - self._price

    def effective_date(self) -> datetime.date:
        return datetime.date(2026, 1, 1)

    def maturity_date(self) -> datetime.date:
        return datetime.date(2026, 3, 31)

    def price(self) -> float:
        return self._price

    def fixed_rate(self) -> float:
        return self._fixed_rate

    def set_fixed_rate(self, rate_decimal: float) -> None:
        self._fixed_rate = float(rate_decimal) * 100.0
        self._price = 100.0 - self._fixed_rate

    def nominal(self) -> float:
        return 1_000_000.0

    def with_notional(self, notional: float) -> "_STIRFutureGenericPricable":
        return self

    def fair_rate(self) -> float:
        return self._fixed_rate / 100.0

    def npv(self) -> float:
        return self._price

    def pv01(self) -> float:
        return 1.0

    def dv01(self, shift: float = 1e-4) -> float:
        return 1.0

    def gamma(self, shift: float = 1e-4) -> float:
        return 0.0

    def dollar_carry(self, horizon: str) -> float:
        return 0.0

    def carry_bps_running(self, horizon: str) -> float:
        return 0.0

    def roll_bps_running(self, horizon: str) -> float:
        return 0.0

    def carry_and_roll_bps_running(self, horizon: str) -> float:
        return 0.0


class _MockSTIRFuturePricer(_STIRFutureGenericPricer):
    def __init__(self, symbol: str, price: float = 95.125):
        self._symbol = symbol
        self._price = float(price)

    def id(self) -> str:
        return self._symbol

    def price(self) -> float:
        return self._price

    def pv01(self, stirf=None, contracts=None, notional=None) -> float:
        return 1.0

    def fair_rate(self, stirf=None) -> float:
        return (100.0 - self._price) / 100.0

    def npv(self, stirf=None) -> float:
        return self._price

    def build_pricable(self, /, **kwargs) -> _MockSTIRFuturePricable:
        price = kwargs.get("price")
        if price is None:
            price = self._price
        return _MockSTIRFuturePricable(price=price)

    def build_stirf(self, **kwargs) -> _MockSTIRFuturePricable:
        return _MockSTIRFuturePricable(price=self._price)

    def reference_date(self) -> datetime.date:
        return datetime.date(2025, 1, 6)

    def calendar(self):
        return None

    def calendar_advance(self, dt1, dt2):
        return dt1

    def handle(self):
        return None

    def index(self):
        return None

    def meta(self):
        return {}

    def effective_date(self, stirf=None) -> datetime.date:
        return datetime.date(2026, 1, 1)

    def maturity_date(self, stirf=None) -> datetime.date:
        return datetime.date(2026, 3, 31)

    def fixed_rate(self, stirf=None) -> float:
        return 100.0 - self._price

    def set_fixed_rate(self, stirf=None, rate_decimal: float = 0.0) -> None:
        pass

    def notional(self, stirf=None) -> float:
        return 1_000_000.0

    def dv01(self, stirf=None, shift: float = 1e-4) -> float:
        return 1.0

    def gamma(self, stirf=None, shift: float = 1e-4) -> float:
        return 0.0

    def dollar_carry(self, stirf=None, horizon: str = "1M") -> float:
        return 0.0

    def carry_bps_running(self, stirf=None, horizon: str = "1M") -> float:
        return 0.0

    def roll_bps_running(self, stirf=None, horizon: str = "1M") -> float:
        return 0.0

    def carry_and_roll_bps_running(self, stirf=None, horizon: str = "1M") -> float:
        return 0.0

    def resolve_pricable(self, stirf, risk_weight=None) -> _MockSTIRFuturePricable:
        return stirf


class _MockSTIRFutureMDP:
    """Mock MDP returning Dict[str, _STIRFutureGenericPricer] as required by STIR adapter."""
    source = "MOCK-STIR"

    def get_pricer(self, request):
        return {"SFRCM1": _MockSTIRFuturePricer("SFRCM1", price=95.125)}


def test_stir_future_outright_backtest():
    dates = [
        datetime.datetime(2025, 1, 6),
        datetime.datetime(2025, 1, 7),
        datetime.datetime(2025, 1, 8),
    ]
    tg = TimeGrid(dates)

    query = STIRFutureQuery(
        structure=STIRFutureStructure.OUTRIGHT,
        value=STIRFutureValue.NPV,
        tenor="3M",
        curve="USD-SOFR-1D",
        structure_kwargs={"notional": 1_000_000},
    )

    trigger = DateTrigger(
        DateTriggerRequirements(dates=[dates[0].date()]),
        actions=[AddQueryAction(query=query)],
    )

    strategy = QueryStrategy(name="STIR Outright", triggers=[trigger])

    bt = QueryDrivenBacktest(
        time_grid=tg,
        mdp=_MockSTIRFutureMDP(),
        strategy=strategy,
        show_progress=False,
    )

    bt.run()

    assert len(bt.mtm_history) == len(dates)
    assert len(list(bt.portfolio.iter_positions())) == 1
    first_mark = bt.mtm_history[dates[0]]
    assert isinstance(first_mark, float)
