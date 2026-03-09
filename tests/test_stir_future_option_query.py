import datetime

import pytest
import pytz

from Query.Base.product_adapter import get_adapter
from Query.STIRFutureOptions.STIRFutureOptionQuery import STIRFutureOptionQuery
from Query.STIRFutureOptions.STIRFutureOptionStructure import STIRFutureOptionStructure
from Query.STIRFutureOptions.STIRFutureOptionValue import STIRFutureOptionValue
from Query.STIRFutureOptions.backends.quantlib.QLSTIRFutureOptionPricer import QLSTIRFutureOptionPricer


def _mk_pricer(
    *,
    symbol: str,
    right: str,
    price: float,
    delta: float,
    gamma: float,
    vega: float,
    theta: float,
    iv_normal: float,
) -> QLSTIRFutureOptionPricer:
    strike = float(int(symbol.split("|", 1)[1][:-1])) / 100.0
    return QLSTIRFutureOptionPricer(
        symbol=symbol,
        right=right,
        underlying_symbol=symbol.split("|", 1)[0],
        strike=strike,
        quote_timestamp=pytz.UTC.localize(datetime.datetime(2026, 1, 2, 17, 0)),
        expiry_date=datetime.date(2026, 12, 16),
        market_price=price,
        model_price=price,
        iv_normal=iv_normal,
        delta=delta,
        gamma=gamma,
        vega=vega,
        theta=theta,
        forward=96.0,
        discount=0.99,
        meta_data={},
    )


def test_adapter_registration_and_outright_structure_resolution():
    adapter_cls = get_adapter("STIRFUTUREOPTION")
    assert adapter_cls.__name__ == "STIRFutureOptionProductAdapter"

    p = _mk_pricer(symbol="SR3Z30|9700C", right="C", price=0.20, delta=0.55, gamma=0.9, vega=0.1, theta=-0.02, iv_normal=0.80)
    q = STIRFutureOptionQuery(
        structure=STIRFutureOptionStructure.OUTRIGHT,
        value=STIRFutureOptionValue.PRICE,
        symbol="SR3Z30|9700C",
    )
    package, weights = q.resolve_package(pricer_or_curve={"SR3Z30|9700C": [p]})
    assert len(package) == 1
    assert weights == [1.0]
    assert package[0].symbol() == "SR3Z30|9700C"


def test_vertical_and_straddle_structure_builders():
    p_call_97 = _mk_pricer(symbol="SR3Z30|9700C", right="C", price=0.21, delta=0.60, gamma=1.2, vega=0.11, theta=-0.03, iv_normal=0.90)
    p_call_975 = _mk_pricer(symbol="SR3Z30|9750C", right="C", price=0.08, delta=0.30, gamma=0.8, vega=0.06, theta=-0.02, iv_normal=0.70)
    p_put_97 = _mk_pricer(symbol="SR3Z30|9700P", right="P", price=0.10, delta=-0.40, gamma=1.1, vega=0.10, theta=-0.03, iv_normal=0.85)

    pricer_map = {
        "SR3Z30|9700C": [p_call_97],
        "SR3Z30|9750C": [p_call_975],
        "SR3Z30|9700P": [p_put_97],
    }

    q_vertical = STIRFutureOptionQuery(
        structure=STIRFutureOptionStructure.VERTICAL,
        value=STIRFutureOptionValue.PRICE,
        structure_kwargs={"long_symbol": "SR3Z30|9700C", "short_symbol": "SR3Z30|9750C"},
    )
    package_v, weights_v = q_vertical.resolve_package(pricer_or_curve=pricer_map)
    assert len(package_v) == 2
    assert weights_v == [1.0, -1.0]

    q_straddle = STIRFutureOptionQuery(
        structure=STIRFutureOptionStructure.STRADDLE,
        value=STIRFutureOptionValue.PRICE,
        symbol="SR3Z30|9700S",
    )
    package_s, weights_s = q_straddle.resolve_package(pricer_or_curve=pricer_map)
    assert len(package_s) == 2
    assert weights_s == [1.0, 1.0]


def test_value_map_weighted_aggregation():
    p_call_97 = _mk_pricer(symbol="SR3Z30|9700C", right="C", price=0.21, delta=0.60, gamma=1.2, vega=0.11, theta=-0.03, iv_normal=0.90)
    p_call_975 = _mk_pricer(symbol="SR3Z30|9750C", right="C", price=0.08, delta=0.30, gamma=0.8, vega=0.06, theta=-0.02, iv_normal=0.70)
    pricer_map = {"SR3Z30|9700C": [p_call_97], "SR3Z30|9750C": [p_call_975]}

    q = STIRFutureOptionQuery(
        structure=STIRFutureOptionStructure.VERTICAL,
        value=STIRFutureOptionValue.PRICE,
        structure_kwargs={"long_symbol": "SR3Z30|9700C", "short_symbol": "SR3Z30|9750C"},
    )
    package, weights = q.resolve_package(pricer_or_curve=pricer_map)
    value_map = q.build_value_map(pricer_or_curve=pricer_map, package=package, risk_weights=weights)

    assert value_map.apply(STIRFutureOptionValue.PRICE) == pytest.approx(0.13)
    assert value_map.apply(STIRFutureOptionValue.NPV) == pytest.approx(0.13)
    assert value_map.apply(STIRFutureOptionValue.DV01) == pytest.approx(7.5)
    assert value_map.apply(STIRFutureOptionValue.DELTA) == pytest.approx(0.30)
    assert value_map.apply(STIRFutureOptionValue.GAMMA) == pytest.approx(0.40)
    assert value_map.apply(STIRFutureOptionValue.GAMMA_01) == pytest.approx(0.10)
    assert value_map.apply(STIRFutureOptionValue.VEGA) == pytest.approx(0.05)
    assert value_map.apply(STIRFutureOptionValue.VEGA_01) == pytest.approx(1.25)
    assert value_map.apply(STIRFutureOptionValue.THETA) == pytest.approx(-0.01)
    assert value_map.apply(STIRFutureOptionValue.IV_NORMAL_BPS) == pytest.approx(20.0)


def test_explicit_contract_sizing_scales_package_metrics():
    pricer = _mk_pricer(symbol="SR3Z30|9700C", right="C", price=0.21, delta=0.60, gamma=1.2, vega=0.11, theta=-0.03, iv_normal=0.90)
    pricer_map = {"SR3Z30|9700C": [pricer]}

    q = STIRFutureOptionQuery(
        structure=STIRFutureOptionStructure.OUTRIGHT,
        value=STIRFutureOptionValue.NPV,
        symbol="SR3Z30|9700C",
        contracts=10,
    )
    package, weights = q.resolve_package(pricer_or_curve=pricer_map)
    value_map = q.build_value_map(pricer_or_curve=pricer_map, package=package, risk_weights=weights)

    assert package[0].quantity() == pytest.approx(10.0)
    assert value_map.apply(STIRFutureOptionValue.PRICE) == pytest.approx(0.21)
    assert value_map.apply(STIRFutureOptionValue.NPV) == pytest.approx(2.10)
    assert value_map.apply(STIRFutureOptionValue.DV01) == pytest.approx(150.0)
    assert value_map.apply(STIRFutureOptionValue.DELTA) == pytest.approx(6.0)
    assert value_map.apply(STIRFutureOptionValue.GAMMA) == pytest.approx(12.0)
    assert value_map.apply(STIRFutureOptionValue.GAMMA_01) == pytest.approx(3.0)
    assert value_map.apply(STIRFutureOptionValue.VEGA) == pytest.approx(1.10)
    assert value_map.apply(STIRFutureOptionValue.VEGA_01) == pytest.approx(27.5)
    assert value_map.apply(STIRFutureOptionValue.THETA) == pytest.approx(-0.30)
    assert value_map.apply(STIRFutureOptionValue.IV_NORMAL_BPS) == pytest.approx(90.0)


@pytest.mark.parametrize(
    ("size_kwargs", "expected_quantity"),
    [
        ({"dv01": 150.0}, 10.0),
        ({"gamma_01": 3.0}, 10.0),
        ({"vega_01": 27.5}, 10.0),
    ],
)
def test_dollar_risk_targets_scale_contract_quantity(size_kwargs, expected_quantity):
    pricer = _mk_pricer(symbol="SR3Z30|9700C", right="C", price=0.21, delta=0.60, gamma=1.2, vega=0.11, theta=-0.03, iv_normal=0.90)
    pricer_map = {"SR3Z30|9700C": [pricer]}

    q = STIRFutureOptionQuery(
        structure=STIRFutureOptionStructure.OUTRIGHT,
        value=STIRFutureOptionValue.NPV,
        symbol="SR3Z30|9700C",
        **size_kwargs,
    )
    package, weights = q.resolve_package(pricer_or_curve=pricer_map)
    value_map = q.build_value_map(pricer_or_curve=pricer_map, package=package, risk_weights=weights)

    assert package[0].quantity() == pytest.approx(expected_quantity)
    assert value_map.apply(STIRFutureOptionValue.DV01) == pytest.approx(150.0)
    assert value_map.apply(STIRFutureOptionValue.GAMMA_01) == pytest.approx(3.0)
    assert value_map.apply(STIRFutureOptionValue.VEGA_01) == pytest.approx(27.5)


def test_multiple_size_targets_raise_explicit_error():
    with pytest.raises(ValueError, match="Specify only one STIR option size target"):
        STIRFutureOptionQuery(
            structure=STIRFutureOptionStructure.OUTRIGHT,
            value=STIRFutureOptionValue.PRICE,
            symbol="SR3Z30|9700C",
            contracts=10,
            dv01=150.0,
        )


def test_build_mdp_request_endpoint_and_symbols_wiring():
    now = datetime.datetime(2026, 1, 2, 10, 30)

    q_default = STIRFutureOptionQuery(
        structure=STIRFutureOptionStructure.OUTRIGHT,
        value=STIRFutureOptionValue.PRICE,
        symbol="SR3Z30|9700C",
    )
    req_default = q_default.build_mdp_request(now=now)
    assert req_default["endpoint"] == "option_snapshot"
    assert req_default["symbols"] == ["SR3Z30|9700C"]
    assert req_default["timestamp"] == now.date()

    q_ts = STIRFutureOptionQuery(
        structure=STIRFutureOptionStructure.VERTICAL,
        value=STIRFutureOptionValue.PRICE,
        structure_kwargs={"long_symbol": "SR3Z30|9700C", "short_symbol": "SR3Z30|9750C"},
        market_request={
            "endpoint": "option_timeseries",
            "start": datetime.date(2026, 1, 1),
            "end": datetime.date(2026, 1, 10),
        },
    )
    req_ts = q_ts.build_mdp_request(now=now)
    assert req_ts["endpoint"] == "option_timeseries"
    assert req_ts["symbols"] == ["SR3Z30|9700C", "SR3Z30|9750C"]
    assert req_ts["timestamp"] == now.date()
