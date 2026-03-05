import datetime

import pytest

from definitions.USTFutureOptions import (
    WEEKLY_ROOTS_BY_BASE_ROOT,
    decode_strike_token,
    encode_strike_token,
    normalize_contract_code,
    normalize_option_contract,
    normalize_strike_token,
    option_root_base_root,
    underlying_contract_for_option,
)
from MDP.USTFutures.USTFutureOptionMDP import (
    _canonical_to_barchart_option,
    _canonical_underlying,
    _expand_straddle_symbol,
    _norm_option_symbol,
    _parse_option_request_symbol,
    _strike_from_symbol,
)


def test_root_alias_and_symbol_normalization():
    assert normalize_option_contract("TYM6", as_of=datetime.date(2026, 3, 4)) == "ZNM26"
    assert normalize_option_contract("TUM6", as_of=datetime.date(2026, 3, 4)) == "ZTM26"
    assert _norm_option_symbol("TYM6|1125c") == "ZNM26|1125C"
    assert _canonical_to_barchart_option("TYM6|1125C") == "ZNM26|1125C"


def test_year_normalization_1_and_2_digit_inputs():
    as_of = datetime.date(2026, 3, 4)
    assert normalize_contract_code("M6", as_of=as_of) == "M26"
    assert normalize_contract_code("M26", as_of=as_of) == "M26"


def test_weekly_extrapolation_maps_to_base_roots():
    assert WEEKLY_ROOTS_BY_BASE_ROOT["ZN"]["friday"][0] == "BN1"
    assert WEEKLY_ROOTS_BY_BASE_ROOT["ZT"]["monday"][1] == "BD2"
    assert WEEKLY_ROOTS_BY_BASE_ROOT["ZF"]["tuesday"][1] == "BFB"
    assert WEEKLY_ROOTS_BY_BASE_ROOT["ZB"]["thursday"][0] == "BBF"

    assert option_root_base_root("BN3") == "ZN"
    assert option_root_base_root("BT1") == "ZT"
    assert option_root_base_root("BFB") == "ZF"
    assert option_root_base_root("BBG") == "ZB"


def test_underlying_contract_resolution_monthly_and_weekly():
    # Monthly quarter option -> same quarter underlying.
    assert underlying_contract_for_option("ZNM26") == "ZNM26"
    # Monthly serial option -> next quarter underlying.
    assert underlying_contract_for_option("ZNJ26") == "ZNM26"
    # Weekly option -> strictly next quarter underlying.
    assert underlying_contract_for_option("BN1H26") == "ZNM26"
    assert underlying_contract_for_option("BBFH26") == "ZBM26"

    assert _canonical_underlying("BN1H26|11270C") == "ZNM26"


def test_strike_codec_parity_monthly_and_weekly():
    cases = [
        ("ZTM26", 104.125, "1041"),
        ("ZFM26", 109.25, "1092"),
        ("ZNM26", 112.5, "1125"),
        ("ZBM26", 117.0, "11700"),
        ("BT1H26", 104.25, "10420"),
        ("BFBH26", 109.5, "10950"),
        ("BN6H26", 112.75, "11270"),
        ("BBFH26", 117.5, "11750"),
    ]

    for contract, strike, token in cases:
        assert encode_strike_token(contract_or_root=contract, strike=strike) == token
        assert decode_strike_token(contract_or_root=contract, strike_token=token) == pytest.approx(strike)
        assert normalize_strike_token(contract_or_root=contract, strike_token=token) == token


def test_parse_and_expand_alias_symbols():
    atm = _parse_option_request_symbol("ZNM6|ATMS", as_of=datetime.date(2026, 3, 4))
    assert atm["selector"] == "atm"
    assert atm["contract"] == "ZNM26"
    assert atm["right"] == "S"

    delta = _parse_option_request_symbol("ZNM6|25DC", as_of=datetime.date(2026, 3, 4))
    assert delta["selector"] == "delta"
    assert delta["contract"] == "ZNM26"
    assert delta["delta"] == pytest.approx(25.0)

    assert _expand_straddle_symbol("ZNM26|1125S") == ["ZNM26|1125C", "ZNM26|1125P"]
    assert _strike_from_symbol("BN1H26|11270C") == pytest.approx(112.75)
