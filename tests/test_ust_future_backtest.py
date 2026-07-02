import datetime

import pandas as pd

from BT.data_handler import TimeGrid
from BT.query_actions import AddQueryAction
from BT.query_engine import QueryDrivenBacktest
from BT.query_strategy import QueryStrategy
from BT.triggers import DateTrigger, DateTriggerRequirements
from MDP.USTFutures.USTFuturesMDP import USTFuturesMDP
from Query.USTFutures import adapter as _ust_adapter  # noqa: F401
from Query.USTFutures.USTFutureQuery import USTFutureQuery
from Query.USTFutures.USTFutureStructure import USTFutureStructure
from Query.USTFutures.USTFutureValue import USTFutureValue
from Query.USTFutures._USTFutureGenericPricable import _USTFutureGenericPricable
from Query.USTFutures._USTFutureGenericPricer import _USTFutureGenericPricer


class MockUSTFuture(_USTFutureGenericPricable):
    def __init__(self, contract_code: str, price: float, contracts: int = 1, notional: float = 100_000.0):
        self._contract_code = contract_code
        self._price = price
        self._contracts = contracts
        self._notional = notional
        self._effective_date = datetime.date(2025, 1, 1)
        self._maturity_date = datetime.date(2025, 12, 31)

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


class MockUSTFuturePricer(_USTFutureGenericPricer):
    def __init__(self, symbol: str, price: float = 110.0):
        self._symbol = symbol
        self._price = price

    def id(self) -> str:
        return self._symbol

    def reference_date(self) -> datetime.date:
        return datetime.date(2025, 1, 1)

    def meta(self):
        return {}

    def effective_date(self, ustf: MockUSTFuture) -> datetime.date:
        return ustf.effective_date()

    def maturity_date(self, ustf: MockUSTFuture) -> datetime.date:
        return ustf.maturity_date()

    def price(self, ustf: MockUSTFuture) -> float:
        return ustf.price()

    def yield_to_maturity(self, ustf: MockUSTFuture) -> float:
        return 0.0

    def pv01(self, ustf: MockUSTFuture) -> float:
        return float(ustf.contracts())

    def dv01(self, ustf: MockUSTFuture) -> float:
        return float(ustf.contracts())

    def npv(self, instrument: MockUSTFuture, /, **kwargs):
        return self.price(instrument) * self.pv01(instrument)

    def resolve_pricable(self, priceable: MockUSTFuture, risk_weight=None) -> MockUSTFuture:
        return priceable

    def build_pricable(self, /, **kwargs):
        return self.build_ustf(
            contract_code=kwargs.get("contract_code"),
            price=kwargs.get("price"),
            contracts=kwargs.get("contracts"),
            notional=kwargs.get("notional"),
        )

    def build_ustf(
        self,
        contract_code: str | None = None,
        effective_date: datetime.date | None = None,
        maturity_date: datetime.date | None = None,
        price: float | None = None,
        contracts: int | None = None,
        notional: float | None = None,
        **kwargs,
    ) -> MockUSTFuture:
        return MockUSTFuture(
            contract_code=contract_code or self._symbol,
            price=price if price is not None else self._price,
            contracts=contracts or 1,
            notional=notional or 100_000.0,
        )


def test_create_ust_query():
    query = USTFutureQuery(
        structure=USTFutureStructure.OUTRIGHT,
        value=USTFutureValue.PRICE,
        tenor="10Y",
        contract="Z4",
    )
    assert query.structure == USTFutureStructure.OUTRIGHT
    assert query.structure_kwargs["symbol"] == "TYZ4"


def test_resolve_ust_package():
    pricer = {"TUZ4": MockUSTFuturePricer("TUZ4"), "FVZ4": MockUSTFuturePricer("FVZ4")}
    query = USTFutureQuery(
        structure=USTFutureStructure.CURVE,
        value=USTFutureValue.PRICE,
        structure_kwargs={"front_symbol": "TUZ4", "back_symbol": "FVZ4"},
    )

    package, weights = query.resolve_package(pricer_or_curve=pricer)
    assert len(package) == 2
    assert weights == [1.0, -1.0]


def test_ust_mdp_fetch(monkeypatch):
    mdp = USTFuturesMDP()
    df = pd.DataFrame([{"ZNZ4": 110.5, "ZFZ4": 106.25}])

    def _mock_fetch(*args, **kwargs):
        return df

    monkeypatch.setattr(mdp, "_fetch_barchart_timeseries", _mock_fetch)
    pricers = mdp.get_pricer({"symbols": ["TYZ4", "FVZ4"], "timestamp": datetime.date(2025, 1, 6), "include_basket": False})

    assert "TYZ4" in pricers
    assert "FVZ4" in pricers
    assert pricers["TYZ4"].id() == "TYZ4"


def test_ust_backtest_run():
    dates = [
        datetime.datetime(2025, 1, 6),
        datetime.datetime(2025, 1, 7),
        datetime.datetime(2025, 1, 8),
    ]
    tg = TimeGrid(dates)

    class MockUSTMDP:
        def get_pricer(self, request):
            symbols = request.get("symbols", ["TYZ4"])
            return {sym: MockUSTFuturePricer(sym) for sym in symbols}

    query = USTFutureQuery(
        structure=USTFutureStructure.OUTRIGHT,
        value=USTFutureValue.PRICE,
        tenor="10Y",
        contract="Z24",
        structure_kwargs={"contracts": 1},
    )

    trigger = DateTrigger(
        DateTriggerRequirements(dates=[dates[0].date()]),
        actions=[AddQueryAction(query=query)],
    )

    strategy = QueryStrategy(name="UST Outright", triggers=[trigger])

    bt = QueryDrivenBacktest(
        time_grid=tg,
        mdp=MockUSTMDP(),
        strategy=strategy,
        show_progress=False,
    )

    bt.run()

    assert len(bt.mtm_history) == len(dates)
    assert len(list(bt.portfolio.iter_positions())) == 1
