import datetime as dt

from BT.position_handler import get_handler
from BT.query_order import QueryOrder
import Query.IRSwaptions.adapter  # noqa: F401
from Query.IRSwaptions.IRSwaptionQuery import IRSwaptionQuery
from Query.IRSwaptions.IRSwaptionValue import IRSwaptionValue


class _DummyValueMap:
    def __init__(self, unit: float, risk_weights):
        self._unit = float(unit)
        self._rw = [float(x) for x in risk_weights]

    def apply(self, value, **kwargs):
        _ = value, kwargs
        return self._unit * sum(self._rw)


def test_handler_registration_for_aliases():
    h1 = get_handler("IRSWAPTION")
    h2 = get_handler("IRSWAPTIONS")
    assert h1.name == "ir_swaption"
    assert h2.name == "ir_swaption"


def test_entry_to_current_spot_npv_pnl_semantics(monkeypatch):
    q = IRSwaptionQuery(
        curve="USD-SOFR-1D",
        expiry="1Y",
        tail="5Y",
        value=IRSwaptionValue.NVOL,
    )
    handler = get_handler("IRSWAPTION")

    monkeypatch.setattr(
        IRSwaptionQuery,
        "resolve_package",
        lambda self, pricer_or_curve, **kwargs: (["leg"], [1.0, -2.0]),
    )
    monkeypatch.setattr(
        IRSwaptionQuery,
        "build_value_map",
        lambda self, pricer_or_curve, package, risk_weights: _DummyValueMap(pricer_or_curve["unit"], risk_weights),
    )

    order = QueryOrder(timestamp=dt.datetime(2026, 3, 4, 10, 0), query=q)
    pos = handler.build_position(
        order=order,
        pricer_provider=lambda _q: {"unit": 5.0},
        now=dt.datetime(2026, 3, 4, 10, 0),
        backtest=None,
    )
    pnl = handler.value_position(
        position=pos,
        pricer_provider=lambda _q: {"unit": 7.0},
        now=dt.datetime(2026, 3, 5, 10, 0),
        backtest=None,
    )

    # Entry = 5*(1-2)=-5, Current = 7*(1-2)=-7, PnL=current-entry=-2.
    assert pnl == -2.0

