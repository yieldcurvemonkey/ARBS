import datetime

from BT.data_handler import TimeGrid
from BT.query_actions import AddQueryAction
from BT.query_engine import QueryDrivenBacktest
from BT.query_strategy import QueryStrategy
from BT.triggers import DateTrigger, DateTriggerRequirements
from Query.STIRFutures.STIRFutureQuery import STIRFutureQuery
from Query.STIRFutures.STIRFutureStructure import STIRFutureStructure
from Query.STIRFutures.STIRFutureValue import STIRFutureValue


def test_stir_future_outright_backtest(mock_mdp):
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
        mdp=mock_mdp,
        strategy=strategy,
        show_progress=False,
    )

    bt.run()

    assert len(bt.mtm_history) == len(dates)
    assert len(list(bt.portfolio.iter_positions())) == 1
    first_mark = bt.mtm_history[dates[0]]
    assert isinstance(first_mark, float)
