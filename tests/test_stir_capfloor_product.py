import datetime
import math
from dataclasses import dataclass

import pytest
import pytz
import QuantLib as ql

from BT.query_order import QueryOrder
from MDP.STIRCapFloors.STIRCapFloorMDP import STIRCapFloorMDP, STIRCapFloorMarketContext
from MDP.STIRFutures._sofr_option_contracts import _strike_from_symbol
from Query.STIRCapFloors.STIRCapFloorQuery import STIRCapFloorQuery
from Query.STIRCapFloors.STIRCapFloorStructure import STIRCapFloorStructure
from Query.STIRCapFloors.STIRCapFloorValue import STIRCapFloorValue
from Query.STIRCapFloors.position_handler import STIRCapFloorPositionHandler
from Query.STIRCapFloors.pricer import STIRCapFloorLegMarket
from Query.STIRFutureOptions.backends.quantlib.QLSTIRFutureOptionPricer import QLSTIRFutureOptionPricer
from TB.STIRCapFloorsTB import STIRCapFloorsTB
from TB.TimeseriesBuilder import TimeseriesBuilder


@dataclass
class _DummySwap:
    effective_date: datetime.date
    maturity_date: datetime.date
    fixed_rate: float
    notional: float


class _DummyCurve:
    def __init__(self, as_of: datetime.date, *, flat_swap_rate: float = 0.03125, zero_rate: float = 0.04):
        self.as_of = as_of
        self.flat_swap_rate = float(flat_swap_rate)
        self.zero_rate = float(zero_rate)

    def handle(self):
        return self

    def discount(self, ql_date):
        py_date = datetime.date(ql_date.year(), ql_date.month(), ql_date.dayOfMonth())
        t = max((py_date - self.as_of).days, 0) / 365.0
        return math.exp(-self.zero_rate * t)

    def build_irswap(
        self,
        *,
        effective_date=None,
        maturity_date=None,
        fixed_rate=-0.0,
        notional=1.0,
        **_,
    ):
        return _DummySwap(
            effective_date=effective_date,
            maturity_date=maturity_date,
            fixed_rate=float(fixed_rate),
            notional=float(notional),
        )

    def fair_rate(self, swap: _DummySwap) -> float:
        _ = swap
        return self.flat_swap_rate


class _DummySmileParams:
    def __init__(self, *, forward_price: float, time_to_expiry: float, expiry_date: datetime.date):
        self.forward_price = float(forward_price)
        self.time_to_expiry = float(time_to_expiry)
        self.expiry_date = expiry_date

    def to_dict(self):
        return {
            "forward_price": self.forward_price,
            "time_to_expiry": self.time_to_expiry,
            "expiry_date": self.expiry_date.isoformat(),
        }


class _DummySmile:
    def __init__(self, *, forward_price: float, expiry_date: datetime.date):
        self.quote_timestamp = pytz.UTC.localize(datetime.datetime(2026, 3, 6, 17, 0))
        self.params = _DummySmileParams(
            forward_price=forward_price,
            time_to_expiry=1.0,
            expiry_date=expiry_date,
        )

    def normal_vol(self, strikes, strike_space="price", vol_units="price"):
        _ = strikes, strike_space, vol_units
        return 0.9


def _mk_pricer(
    *,
    symbol: str,
    price: float,
    delta: float,
    gamma: float = 0.2,
    vega: float = 0.1,
    theta: float = -0.01,
    forward: float = 96.875,
    expiry_date: datetime.date = datetime.date(2027, 3, 17),
) -> QLSTIRFutureOptionPricer:
    return QLSTIRFutureOptionPricer(
        symbol=symbol,
        right=symbol[-1],
        underlying_symbol=symbol.split("|", 1)[0],
        strike=_strike_from_symbol(symbol),
        quote_timestamp=pytz.UTC.localize(datetime.datetime(2026, 3, 6, 17, 0)),
        expiry_date=expiry_date,
        market_price=float(price),
        model_price=float(price),
        iv_normal=0.9,
        delta=float(delta),
        gamma=float(gamma),
        vega=float(vega),
        theta=float(theta),
        forward=float(forward),
        discount=1.0,
        meta_data={},
    )


def _manual_context(*, prices=(1.0, 0.5), quantities=(1.0, 2.0), unit_quantities=(1.0, 1.0)) -> STIRCapFloorMarketContext:
    contracts = ["SFRH27", "SFRM27"]
    pricers = [
        _mk_pricer(symbol="SFRH27|9687P", price=prices[0], delta=-0.4, gamma=0.2, vega=0.1, theta=-0.01),
        _mk_pricer(symbol="SFRM27|9687P", price=prices[1], delta=-0.2, gamma=0.1, vega=0.05, theta=-0.02, expiry_date=datetime.date(2027, 6, 16)),
    ]
    legs = []
    for idx, (contract, pricer, qty, unit_qty) in enumerate(zip(contracts, pricers, quantities, unit_quantities)):
        start = datetime.date(2027, 3, 17) if idx == 0 else datetime.date(2027, 6, 16)
        end = datetime.date(2027, 6, 16) if idx == 0 else datetime.date(2027, 9, 15)
        legs.append(
            STIRCapFloorLegMarket(
                option_symbol=pricer.symbol(),
                requested_symbol=pricer.symbol(),
                right="P",
                underlying_contract=contract,
                reference_quarter_start=start,
                reference_quarter_end=end,
                strike_price=pricer.strike(),
                strike_rate=100.0 - pricer.strike(),
                requested_strike_price=pricer.strike(),
                requested_strike_rate=100.0 - pricer.strike(),
                economic_weight=0.5,
                unit_quantity=float(unit_qty),
                quantity=float(qty),
                quote_source="market",
                quarter_end_flag=False,
                fomc_loading=0.0,
                pricer=pricer,
                metadata={"leg_index": idx},
            )
        )
    return STIRCapFloorMarketContext(
        structure="CAP",
        curve_name="USD-SOFR-1D",
        as_of_date=datetime.date(2026, 3, 6),
        swap_start=datetime.date(2027, 3, 17),
        swap_end=datetime.date(2027, 9, 15),
        weight_method="equal",
        strike_convention="flat_swap_rate",
        contracts=1.0,
        curve=_DummyCurve(datetime.date(2026, 3, 6)),
        legs=tuple(legs),
        metadata={"strip_contracts": contracts},
    )


def _model_consistent_context(*, sigma: float = 0.9) -> STIRCapFloorMarketContext:
    as_of = datetime.date(2026, 3, 6)
    pricer_specs = [
        ("SFRH27|9687P", 96.875, datetime.date(2027, 3, 17)),
        ("SFRM27|9687P", 96.875, datetime.date(2027, 6, 16)),
    ]
    prices = []
    for symbol, forward, expiry_date in pricer_specs:
        strike = _strike_from_symbol(symbol)
        tte = max((expiry_date - as_of).days / 365.0, 1e-12)
        prices.append(
            float(
                ql.bachelierBlackFormula(
                    ql.Option.Put,
                    float(strike),
                    float(forward),
                    float(sigma) * math.sqrt(float(tte)),
                    1.0,
                )
            )
        )
    return _manual_context(prices=tuple(prices), quantities=(1.0, 1.0), unit_quantities=(1.0, 1.0))


def test_query_parses_shorthand_and_defaults():
    q = STIRCapFloorQuery(
        structure=STIRCapFloorStructure.CAP,
        shorthand="1Yx1Y",
        value=STIRCapFloorValue.PRICE,
    )
    req = q.build_mdp_request(datetime.datetime(2026, 3, 6, 10, 0))
    assert req["endpoint"] == "synthetic_capfloor_snapshot"
    assert req["curve_name"] == "USD-SOFR-1D"
    assert req["structure"] == "CAP"
    assert req["expiry"] == "1Y"
    assert req["tail"] == "1Y"
    assert req["weight_method"] == "equal"
    assert req["strike_convention"] == "atm_per_caplet"
    assert req["contracts"] == pytest.approx(1.0)

    req_from_date = q.build_mdp_request(datetime.date(2026, 3, 6))
    assert req_from_date["timestamp"] == datetime.date(2026, 3, 6)


def test_query_supports_explicit_dates_and_rejects_non_quarter_tenors():
    q = STIRCapFloorQuery(
        structure=STIRCapFloorStructure.FLOOR,
        swap_start=datetime.date(2027, 3, 17),
        swap_end=datetime.date(2028, 3, 15),
        value=STIRCapFloorValue.PRICE,
    )
    req = q.build_mdp_request(datetime.datetime(2026, 3, 6, 10, 0))
    assert req["swap_start"] == datetime.date(2027, 3, 17)
    assert req["swap_end"] == datetime.date(2028, 3, 15)

    with pytest.raises(ValueError, match="multiple of 3M"):
        STIRCapFloorQuery(shorthand="1Mx1Y", value=STIRCapFloorValue.PRICE)


def test_mdp_mapping_for_standard_strips(monkeypatch):
    mdp = STIRCapFloorMDP()
    monkeypatch.setattr(mdp._curve_mdp, "get_pricer", lambda req: _DummyCurve(req["timestamp"]))

    requested = []

    def _fake_option_snapshot(req):
        symbol = req["symbols"][0]
        requested.append(symbol)
        contract = symbol.split("|", 1)[0]
        right = symbol[-1]
        actual_symbol = f"{contract}|9687{right}"
        return {symbol: [_mk_pricer(symbol=actual_symbol, price=1.0, delta=-0.4 if right == 'P' else 0.4)]}

    monkeypatch.setattr(mdp._option_mdp, "get_data", _fake_option_snapshot)

    q_6m = STIRCapFloorQuery(shorthand="6Mx1Y", value=STIRCapFloorValue.PRICE)
    ctx_6m = mdp.get_pricer(q_6m.build_mdp_request(datetime.datetime(2026, 3, 6, 10, 0)))
    assert ctx_6m.meta()["strip_contracts"] == ["SFRU26", "SFRZ26", "SFRH27", "SFRM27"]

    q_1y = STIRCapFloorQuery(shorthand="1Yx1Y", value=STIRCapFloorValue.PRICE)
    ctx_1y = mdp.get_pricer(q_1y.build_mdp_request(datetime.datetime(2026, 3, 6, 10, 0)))
    assert ctx_1y.meta()["strip_contracts"] == ["SFRH27", "SFRM27", "SFRU27", "SFRZ27"]
    assert requested[:4] == ["SFRU26|ATMP", "SFRZ26|ATMP", "SFRH27|ATMP", "SFRM27|ATMP"]


def test_roll_handling_and_partial_strip_rejection(monkeypatch):
    mdp = STIRCapFloorMDP()
    monkeypatch.setattr(mdp._curve_mdp, "get_pricer", lambda req: _DummyCurve(req["timestamp"]))
    monkeypatch.setattr(
        mdp._option_mdp,
        "get_data",
        lambda req: {req["symbols"][0]: [_mk_pricer(symbol=f"{req['symbols'][0].split('|', 1)[0]}|9687P", price=1.0, delta=-0.4)]},
    )

    q_roll = STIRCapFloorQuery(shorthand="3Mx1Y", value=STIRCapFloorValue.PRICE)
    before_roll = mdp.get_pricer(q_roll.build_mdp_request(datetime.datetime(2026, 3, 17, 10, 0)))
    after_roll = mdp.get_pricer(q_roll.build_mdp_request(datetime.datetime(2026, 3, 18, 10, 0)))
    assert before_roll.meta()["strip_contracts"] == ["SFRM26", "SFRU26", "SFRZ26", "SFRH27"]
    assert after_roll.meta()["strip_contracts"] == ["SFRU26", "SFRZ26", "SFRH27", "SFRM27"]

    with pytest.raises(ValueError, match="before the first live quarterly contract"):
        mdp.get_pricer(
            {
                "endpoint": "synthetic_capfloor_snapshot",
                "structure": "CAP",
                "curve_name": "USD-SOFR-1D",
                "timestamp": datetime.date(2026, 3, 20),
                "swap_start": datetime.date(2026, 3, 18),
                "swap_end": datetime.date(2027, 3, 17),
            }
        )


def test_weights_sum_to_one_and_duration_differs_from_equal(monkeypatch):
    mdp = STIRCapFloorMDP()
    monkeypatch.setattr(mdp._curve_mdp, "get_pricer", lambda req: _DummyCurve(req["timestamp"], zero_rate=0.07))
    monkeypatch.setattr(
        mdp._option_mdp,
        "get_data",
        lambda req: {req["symbols"][0]: [_mk_pricer(symbol=f"{req['symbols'][0].split('|', 1)[0]}|9687P", price=1.0, delta=-0.4)]},
    )

    base_req = {
        "endpoint": "synthetic_capfloor_snapshot",
        "structure": "CAP",
        "curve_name": "USD-SOFR-1D",
        "timestamp": datetime.date(2026, 3, 6),
        "shorthand": "1Yx1Y",
    }
    equal_ctx = mdp.get_pricer({**base_req, "weight_method": "equal"})
    duration_ctx = mdp.get_pricer({**base_req, "weight_method": "duration"})
    equal_weights = [leg.economic_weight for leg in equal_ctx.legs]
    duration_weights = [leg.economic_weight for leg in duration_ctx.legs]
    assert sum(equal_weights) == pytest.approx(1.0)
    assert sum(duration_weights) == pytest.approx(1.0)
    assert duration_weights != pytest.approx(equal_weights)
    assert [leg.quantity for leg in equal_ctx.legs] == pytest.approx([1.0, 1.0, 1.0, 1.0])


def test_flat_swap_rate_market_and_sabr_fallback_are_recorded(monkeypatch):
    mdp = STIRCapFloorMDP()
    monkeypatch.setattr(mdp._curve_mdp, "get_pricer", lambda req: _DummyCurve(req["timestamp"], flat_swap_rate=0.03125))

    def _fake_snapshot(req):
        symbol = req["symbols"][0]
        contract = symbol.split("|", 1)[0]
        if contract == "SFRH27":
            return {}
        return {symbol: [_mk_pricer(symbol=symbol, price=1.25, delta=-0.35)]}

    monkeypatch.setattr(mdp._option_mdp, "get_data", _fake_snapshot)
    monkeypatch.setattr(
        mdp._option_mdp,
        "fetch_sabr_smile",
        lambda req: _DummySmile(
            forward_price=96.875,
            expiry_date=datetime.date(2027, 3, 17) if req["symbol"] == "SFRH27" else datetime.date(2027, 6, 16),
        ),
    )

    q = STIRCapFloorQuery(
        shorthand="1Yx1Y",
        strike_convention="flat_swap_rate",
        value=STIRCapFloorValue.BREAKDOWN,
    )
    ctx = mdp.get_pricer(q.build_mdp_request(datetime.datetime(2026, 3, 6, 10, 0)))
    package, weights = q.resolve_package(pricer_or_curve=ctx)
    breakdown = q.build_value_map(pricer_or_curve=ctx, package=package, risk_weights=weights).apply(STIRCapFloorValue.BREAKDOWN)

    assert any(row["quote_source"] == "sabr_fallback" for row in breakdown)
    assert any(row["quote_source"] == "market" for row in breakdown)
    assert breakdown[0]["requested_strike_price"] == pytest.approx(96.875)
    assert "strike_snap_bps" in breakdown[0]["metadata"]


def test_value_map_aggregates_strip_metrics_and_breakdown():
    ctx = _manual_context()
    q = STIRCapFloorQuery(
        structure=STIRCapFloorStructure.CAP,
        swap_start=ctx.swap_start,
        swap_end=ctx.swap_end,
        value=STIRCapFloorValue.PRICE,
    )
    package, weights = q.resolve_package(pricer_or_curve=ctx)
    vmap = q.build_value_map(pricer_or_curve=ctx, package=package, risk_weights=weights)

    assert vmap.apply(STIRCapFloorValue.PRICE) == pytest.approx(1.5)
    assert vmap.apply(STIRCapFloorValue.NPV) == pytest.approx(2.0)
    assert vmap.apply(STIRCapFloorValue.BPVOL) == pytest.approx(90.0)
    assert vmap.apply(STIRCapFloorValue.DV01) == pytest.approx(-20.0)
    assert vmap.apply(STIRCapFloorValue.DELTA) == pytest.approx(-0.8)
    assert vmap.apply(STIRCapFloorValue.GAMMA) == pytest.approx(0.4)
    assert vmap.apply(STIRCapFloorValue.GAMMA_01) == pytest.approx(0.10)
    assert vmap.apply(STIRCapFloorValue.VEGA) == pytest.approx(0.20)
    assert vmap.apply(STIRCapFloorValue.VEGA_01) == pytest.approx(5.0)
    assert vmap.apply(STIRCapFloorValue.THETA) == pytest.approx(-0.05)

    breakdown = vmap.apply(STIRCapFloorValue.BREAKDOWN)
    assert [row["symbol"] for row in breakdown] == ["SFRH27|9687P", "SFRM27|9687P"]
    assert breakdown[1]["quantity"] == pytest.approx(2.0)


def test_flat_bp_vol_reprices_strip_price():
    ctx = _model_consistent_context(sigma=0.9)
    q = STIRCapFloorQuery(
        structure=STIRCapFloorStructure.CAP,
        swap_start=ctx.swap_start,
        swap_end=ctx.swap_end,
        value=STIRCapFloorValue.FLAT_BP_VOL,
    )
    package, weights = q.resolve_package(pricer_or_curve=ctx)
    vmap = q.build_value_map(pricer_or_curve=ctx, package=package, risk_weights=weights)

    assert vmap.apply(STIRCapFloorValue.BPVOL) == pytest.approx(90.0)
    assert vmap.apply(STIRCapFloorValue.FLAT_BP_VOL) == pytest.approx(90.0, abs=1e-6)


def test_position_handler_uses_leg_level_pnl():
    entry_ctx = _manual_context(prices=(1.0, 0.5))
    current_ctx = _manual_context(prices=(1.1, 0.6))
    q = STIRCapFloorQuery(
        structure=STIRCapFloorStructure.CAP,
        swap_start=entry_ctx.swap_start,
        swap_end=entry_ctx.swap_end,
        value=STIRCapFloorValue.PRICE,
    )
    handler = STIRCapFloorPositionHandler()
    order = QueryOrder(timestamp=datetime.datetime(2026, 3, 6, 10, 0), query=q)

    position = handler.build_position(
        order,
        pricer_provider=lambda _q: entry_ctx,
        now=datetime.datetime(2026, 3, 6, 10, 0),
        backtest=None,
    )
    pnl = handler.value_position(
        position,
        pricer_provider=lambda _q: current_ctx,
        now=datetime.datetime(2026, 3, 7, 10, 0),
        backtest=None,
    )
    assert pnl == pytest.approx(((1.1 - 1.0) * 1.0 + (0.6 - 0.5) * 2.0) * 2500.0)


def test_timeseries_builder_routes_stir_capfloor_queries():
    class _StubCapFloorMDP:
        source = "MOCK-STIRCAPFLOOR"

        def get_pricer(self, request):
            _ = request
            return _manual_context()

    tb = TimeseriesBuilder(
        stircapfloors_tb=STIRCapFloorsTB(_StubCapFloorMDP(), show_tqdm=False),
    )
    df = tb.get_timeseries(
        start=datetime.date(2026, 3, 6),
        end=datetime.date(2026, 3, 6),
        queries=[
            STIRCapFloorQuery(
                shorthand="1Yx1Y",
                value=STIRCapFloorValue.PRICE,
                name="cap_strip",
            )
        ],
        drop_multilevel_cols=True,
    )
    assert not df.empty
    assert "cap_strip" in df.columns
