import datetime

import pytz
import pytest

from BT.query_order import QueryOrder
from Query.STIRFutureOptions.STIRFutureOptionQuery import STIRFutureOptionQuery
from Query.STIRFutureOptions.STIRFutureOptionStructure import STIRFutureOptionStructure
from Query.STIRFutureOptions.STIRFutureOptionValue import STIRFutureOptionValue
from Query.STIRFutureOptions.backends.quantlib.QLSTIRFutureOptionPricer import QLSTIRFutureOptionPricer
from Query.STIRFutureOptions.position_handler import STIRFutureOptionHandler


def _mk_pricer(symbol: str, price: float, delta: float) -> QLSTIRFutureOptionPricer:
    right = symbol[-1]
    strike = float(int(symbol.split("|", 1)[1][:-1])) / 100.0
    return QLSTIRFutureOptionPricer(
        symbol=symbol,
        right=right,
        underlying_symbol=symbol.split("|", 1)[0],
        strike=strike,
        quote_timestamp=pytz.UTC.localize(datetime.datetime(2026, 3, 4, 17, 0)),
        expiry_date=datetime.date(2026, 12, 16),
        market_price=price,
        model_price=price,
        iv_normal=0.90,
        delta=delta,
        gamma=0.20,
        vega=0.10,
        theta=-0.01,
        forward=96.0,
        discount=1.0,
        meta_data={},
    )


def test_position_handler_keeps_entry_contracts_for_dv01_target():
    handler = STIRFutureOptionHandler()
    entry_dt = datetime.datetime(2026, 3, 4, 10, 0)
    now_dt = datetime.datetime(2026, 3, 5, 10, 0)

    q = STIRFutureOptionQuery(
        structure=STIRFutureOptionStructure.OUTRIGHT,
        value=STIRFutureOptionValue.PRICE,
        symbol="SR3Z30|9700C",
        dv01=100.0,
    )
    order = QueryOrder(timestamp=entry_dt, query=q)

    pos = handler.build_position(
        order,
        pricer_provider=lambda _q: {"SR3Z30|9700C": [_mk_pricer("SR3Z30|9700C", 1.00, 0.50)]},
        now=entry_dt,
        backtest=None,
    )
    assert pos.package[0].quantity() == pytest.approx(8.0)

    pnl = handler.value_position(
        pos,
        pricer_provider=lambda _q: {"SR3Z30|9700C": [_mk_pricer("SR3Z30|9700C", 1.10, 1.00)]},
        now=now_dt,
        backtest=None,
    )

    assert pnl == pytest.approx((1.10 - 1.00) * 2500.0 * 8.0)
