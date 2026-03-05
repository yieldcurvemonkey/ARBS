import datetime

import pytz
import pytest

from BT.query_order import QueryOrder
from Query.USTFutureOptions.USTFutureOptionQuery import USTFutureOptionQuery
from Query.USTFutureOptions.USTFutureOptionStructure import USTFutureOptionStructure
from Query.USTFutureOptions.USTFutureOptionValue import USTFutureOptionValue
from Query.USTFutureOptions.backends.quantlib.QLUSTFutureOptionPricer import QLUSTFutureOptionPricer
from Query.USTFutureOptions.position_handler import USTFutureOptionHandler
from definitions.USTFutureOptions import decode_strike_token


def _mk_pricer(symbol: str, price: float) -> QLUSTFutureOptionPricer:
    contract, tail = symbol.split("|", 1)
    right = tail[-1]
    strike = float(decode_strike_token(contract_or_root=contract, strike_token=tail[:-1]))
    return QLUSTFutureOptionPricer(
        symbol=symbol,
        right=right,
        underlying_symbol=contract,
        strike=strike,
        quote_timestamp=pytz.UTC.localize(datetime.datetime(2026, 3, 4, 17, 0)),
        expiry_date=datetime.date(2026, 6, 25),
        market_price=price,
        model_price=price,
        iv_normal=1.0,
        delta=0.5 if right == "C" else -0.5,
        gamma=0.1,
        vega=0.1,
        theta=-0.01,
        forward=112.5,
        discount=1.0,
        meta_data={},
    )


def test_position_handler_pnl_scales_by_point_value():
    handler = USTFutureOptionHandler()
    entry_dt = datetime.datetime(2026, 3, 4, 10, 0)
    now_dt = datetime.datetime(2026, 3, 5, 10, 0)

    # 2Y option root (ZT base) should use point value 2000.
    q_zt = USTFutureOptionQuery(
        structure=USTFutureOptionStructure.OUTRIGHT,
        value=USTFutureOptionValue.PRICE,
        symbol="ZTM26|1042C",
    )
    order_zt = QueryOrder(timestamp=entry_dt, query=q_zt)
    pos_zt = handler.build_position(
        order_zt,
        pricer_provider=lambda _q: {"ZTM26|1042C": [_mk_pricer("ZTM26|1042C", 1.00)]},
        now=entry_dt,
        backtest=None,
    )
    pnl_zt = handler.value_position(
        pos_zt,
        pricer_provider=lambda _q: {"ZTM26|1042C": [_mk_pricer("ZTM26|1042C", 1.10)]},
        now=now_dt,
        backtest=None,
    )
    assert pnl_zt == pytest.approx((1.10 - 1.00) * 2000.0)

    # 10Y option root (ZN base) should use point value 1000.
    q_zn = USTFutureOptionQuery(
        structure=USTFutureOptionStructure.OUTRIGHT,
        value=USTFutureOptionValue.PRICE,
        symbol="ZNM26|1125C",
    )
    order_zn = QueryOrder(timestamp=entry_dt, query=q_zn)
    pos_zn = handler.build_position(
        order_zn,
        pricer_provider=lambda _q: {"ZNM26|1125C": [_mk_pricer("ZNM26|1125C", 1.00)]},
        now=entry_dt,
        backtest=None,
    )
    pnl_zn = handler.value_position(
        pos_zn,
        pricer_provider=lambda _q: {"ZNM26|1125C": [_mk_pricer("ZNM26|1125C", 1.10)]},
        now=now_dt,
        backtest=None,
    )
    assert pnl_zn == pytest.approx((1.10 - 1.00) * 1000.0)


def test_position_handler_vertical_respects_leg_weights():
    handler = USTFutureOptionHandler()
    entry_dt = datetime.datetime(2026, 3, 4, 10, 0)
    now_dt = datetime.datetime(2026, 3, 5, 10, 0)

    q = USTFutureOptionQuery(
        structure=USTFutureOptionStructure.VERTICAL,
        value=USTFutureOptionValue.PRICE,
        structure_kwargs={"long_symbol": "ZNM26|1125C", "short_symbol": "ZNM26|1130C"},
    )
    order = QueryOrder(timestamp=entry_dt, query=q)

    pos = handler.build_position(
        order,
        pricer_provider=lambda _q: {
            "ZNM26|1125C": [_mk_pricer("ZNM26|1125C", 1.20)],
            "ZNM26|1130C": [_mk_pricer("ZNM26|1130C", 0.80)],
        },
        now=entry_dt,
        backtest=None,
    )

    pnl = handler.value_position(
        pos,
        pricer_provider=lambda _q: {
            "ZNM26|1125C": [_mk_pricer("ZNM26|1125C", 1.30)],
            "ZNM26|1130C": [_mk_pricer("ZNM26|1130C", 0.85)],
        },
        now=now_dt,
        backtest=None,
    )

    # Spread widens by 0.05 points; ZN point value = 1000.
    assert pnl == pytest.approx(0.05 * 1000.0)
