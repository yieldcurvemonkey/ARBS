import datetime

import pytest
import pytz

from Query.Base.bachelier import bachelier_greeks_fd, implied_normal_vol
from Query.Base.product_adapter import get_adapter
from Query.USTFutureOptions.USTFutureOptionQuery import USTFutureOptionQuery
from Query.USTFutureOptions.USTFutureOptionStructure import USTFutureOptionStructure
from Query.USTFutureOptions.USTFutureOptionValue import USTFutureOptionValue
from Query.USTFutureOptions.backends.quantlib.QLUSTFutureOptionPricer import QLUSTFutureOptionPricer
from definitions.USTFutureOptions import decode_strike_token


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
    fv01: float = 0.04,
) -> QLUSTFutureOptionPricer:
    contract, tail = symbol.split("|", 1)
    strike = decode_strike_token(contract_or_root=contract, strike_token=tail[:-1])
    return QLUSTFutureOptionPricer(
        symbol=symbol,
        right=right,
        underlying_symbol=contract,
        strike=float(strike),
        quote_timestamp=pytz.UTC.localize(datetime.datetime(2026, 1, 2, 17, 0)),
        expiry_date=datetime.date(2026, 6, 25),
        market_price=price,
        model_price=price,
        iv_normal=iv_normal,
        delta=delta,
        gamma=gamma,
        vega=vega,
        theta=theta,
        forward=112.5,
        discount=0.99,
        fv01=fv01,
        meta_data={},
    )


def test_adapter_registration_and_outright_structure_resolution():
    adapter_cls = get_adapter("USTFUTUREOPTION")
    assert adapter_cls.__name__ == "USTFutureOptionProductAdapter"

    p = _mk_pricer(symbol="ZNM26|1125C", right="C", price=1.20, delta=0.55, gamma=0.9, vega=0.1, theta=-0.02, iv_normal=0.80)
    q = USTFutureOptionQuery(
        structure=USTFutureOptionStructure.OUTRIGHT,
        value=USTFutureOptionValue.PRICE,
        symbol="ZNM26|1125C",
    )
    package, weights = q.resolve_package(pricer_or_curve={"ZNM26|1125C": [p]})
    assert len(package) == 1
    assert weights == [1.0]
    assert package[0].symbol() == "ZNM26|1125C"


def test_vertical_and_straddle_structure_builders():
    p_call_1125 = _mk_pricer(symbol="ZNM26|1125C", right="C", price=1.20, delta=0.60, gamma=1.2, vega=0.11, theta=-0.03, iv_normal=0.90)
    p_call_1130 = _mk_pricer(symbol="ZNM26|1130C", right="C", price=0.80, delta=0.30, gamma=0.8, vega=0.06, theta=-0.02, iv_normal=0.70)
    p_put_1125 = _mk_pricer(symbol="ZNM26|1125P", right="P", price=0.75, delta=-0.40, gamma=1.1, vega=0.10, theta=-0.03, iv_normal=0.85)

    pricer_map = {
        "ZNM26|1125C": [p_call_1125],
        "ZNM26|1130C": [p_call_1130],
        "ZNM26|1125P": [p_put_1125],
    }

    q_vertical = USTFutureOptionQuery(
        structure=USTFutureOptionStructure.VERTICAL,
        value=USTFutureOptionValue.PRICE,
        structure_kwargs={"long_symbol": "ZNM26|1125C", "short_symbol": "ZNM26|1130C"},
    )
    package_v, weights_v = q_vertical.resolve_package(pricer_or_curve=pricer_map)
    assert len(package_v) == 2
    assert weights_v == [1.0, -1.0]

    q_straddle = USTFutureOptionQuery(
        structure=USTFutureOptionStructure.STRADDLE,
        value=USTFutureOptionValue.PRICE,
        symbol="ZNM26|1125S",
    )
    package_s, weights_s = q_straddle.resolve_package(pricer_or_curve=pricer_map)
    assert len(package_s) == 2
    assert weights_s == [1.0, 1.0]


def test_value_map_weighted_aggregation():
    p_call_1125 = _mk_pricer(symbol="ZNM26|1125C", right="C", price=1.20, delta=0.60, gamma=1.2, vega=0.11, theta=-0.03, iv_normal=0.90)
    p_call_1130 = _mk_pricer(symbol="ZNM26|1130C", right="C", price=0.80, delta=0.30, gamma=0.8, vega=0.06, theta=-0.02, iv_normal=0.70)
    pricer_map = {"ZNM26|1125C": [p_call_1125], "ZNM26|1130C": [p_call_1130]}

    q = USTFutureOptionQuery(
        structure=USTFutureOptionStructure.VERTICAL,
        value=USTFutureOptionValue.PRICE,
        structure_kwargs={"long_symbol": "ZNM26|1125C", "short_symbol": "ZNM26|1130C"},
    )
    package, weights = q.resolve_package(pricer_or_curve=pricer_map)
    value_map = q.build_value_map(pricer_or_curve=pricer_map, package=package, risk_weights=weights)

    assert value_map.apply(USTFutureOptionValue.PRICE) == pytest.approx(0.40)
    assert value_map.apply(USTFutureOptionValue.NPV) == pytest.approx(0.40)
    assert value_map.apply(USTFutureOptionValue.DELTA) == pytest.approx(0.30)
    assert value_map.apply(USTFutureOptionValue.GAMMA) == pytest.approx(0.40)
    assert value_map.apply(USTFutureOptionValue.VEGA) == pytest.approx(0.05)
    assert value_map.apply(USTFutureOptionValue.THETA) == pytest.approx(-0.01)
    assert value_map.apply(USTFutureOptionValue.IV_NORMAL_BPS) == pytest.approx((0.90 - 0.70) / 0.04)


def test_build_mdp_request_endpoint_and_symbols_wiring():
    now = datetime.datetime(2026, 3, 4, 10, 30)

    q_default = USTFutureOptionQuery(
        structure=USTFutureOptionStructure.OUTRIGHT,
        value=USTFutureOptionValue.PRICE,
        symbol="ZNM26|1125C",
    )
    req_default = q_default.build_mdp_request(now=now)
    assert req_default["endpoint"] == "option_snapshot"
    assert req_default["symbols"] == ["ZNM26|1125C"]
    assert req_default["timestamp"] == now.date()

    q_ts = USTFutureOptionQuery(
        structure=USTFutureOptionStructure.VERTICAL,
        value=USTFutureOptionValue.PRICE,
        structure_kwargs={"long_symbol": "ZNM26|1125C", "short_symbol": "ZNM26|1130C"},
        market_request={
            "endpoint": "option_timeseries",
            "start": datetime.date(2026, 2, 20),
            "end": datetime.date(2026, 3, 4),
        },
    )
    req_ts = q_ts.build_mdp_request(now=now)
    assert req_ts["endpoint"] == "option_timeseries"
    assert req_ts["symbols"] == ["ZNM26|1125C", "ZNM26|1130C"]
    assert req_ts["timestamp"] == now.date()


def test_premium_override_reprices_outright_iv_and_greeks():
    pricer = _mk_pricer(symbol="ZNM26|1125C", right="C", price=1.20, delta=0.55, gamma=0.9, vega=0.1, theta=-0.02, iv_normal=0.80)
    pricer_map = {"ZNM26|1125C": [pricer]}
    q = USTFutureOptionQuery(
        structure=USTFutureOptionStructure.OUTRIGHT,
        value=USTFutureOptionValue.IV_NORMAL_BPS,
        symbol="ZNM26|1125C",
        structure_kwargs={"premium": 1.45},
    )

    package, weights = q.resolve_package(pricer_or_curve=pricer_map)
    value_map = q.build_value_map(pricer_or_curve=pricer_map, package=package, risk_weights=weights)
    tte = max((pricer.expiry_date() - pricer.quote_timestamp().date()).days / 365.0, 1e-12)
    expected_iv = implied_normal_vol("C", package[0].strike(), pricer.forward(), tte, 1.45, pricer.discount())
    exp_delta, exp_gamma, exp_vega, exp_theta = bachelier_greeks_fd(
        right="C",
        strike=package[0].strike(),
        forward=pricer.forward(),
        vol_normal=expected_iv,
        tte=tte,
        discount=pricer.discount(),
    )

    assert package[0].premium_override() == pytest.approx(1.45)
    assert value_map.apply(USTFutureOptionValue.PRICE) == pytest.approx(1.45)
    assert value_map.apply(USTFutureOptionValue.NPV) == pytest.approx(1.45)
    assert value_map.apply(USTFutureOptionValue.IV_NORMAL_BPS) == pytest.approx(expected_iv / pricer.fv01())
    assert value_map.apply(USTFutureOptionValue.DELTA) == pytest.approx(exp_delta)
    assert value_map.apply(USTFutureOptionValue.GAMMA) == pytest.approx(exp_gamma)
    assert value_map.apply(USTFutureOptionValue.VEGA) == pytest.approx(exp_vega)
    assert value_map.apply(USTFutureOptionValue.THETA) == pytest.approx(exp_theta)
