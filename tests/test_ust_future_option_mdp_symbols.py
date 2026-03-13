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
    _cme_listed_abs_offset_grid_bps_for_contract_forward,
    _expand_straddle_symbol,
    _norm_option_symbol,
    _parse_option_request_symbol,
    _parse_qs_ust_option_request_symbol,
    _snap_to_listed_strike_for_offset,
    _strike_from_symbol,
)


def test_root_alias_and_symbol_normalization():
    assert normalize_option_contract("TYM6", as_of=datetime.date(2026, 3, 4)) == "ZNM26"
    assert normalize_option_contract("TUM6", as_of=datetime.date(2026, 3, 4)) == "ZTM26"
    assert _norm_option_symbol("TYM6|1125c") == "ZNM26|1125C"
    assert _canonical_to_barchart_option("TYM6|1125C") == "ZNM26|1125C"
    assert _canonical_to_barchart_option("USM26|12900C") == "ZBM26|1290C"
    assert _canonical_to_barchart_option("USM26|12950P") == "ZBM26|1295P"


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


def test_parse_ust_atmf_offset_aliases_and_snap_to_listed_strikes():
    as_of = datetime.date(2026, 3, 4)

    offset_call = _parse_option_request_symbol("ZNM6|25BPC", as_of=as_of)
    assert offset_call["selector"] == "atmf_offset"
    assert offset_call["contract"] == "ZNM26"
    assert offset_call["right"] == "C"
    assert offset_call["atm_offset_bps"] == pytest.approx(25.0)
    assert offset_call["canonical"] == "ZNM26|25BPC"

    offset_call_alt = _parse_option_request_symbol("ZNM6|ATMF-25", as_of=as_of)
    assert offset_call_alt["selector"] == "atmf_offset"
    assert offset_call_alt["right"] == "C"
    assert offset_call_alt["atm_offset_bps"] == pytest.approx(25.0)
    assert offset_call_alt["canonical"] == "ZNM26|25BPC"

    offset_put_alt = _parse_option_request_symbol("ZNM6|ATMF+25", as_of=as_of)
    assert offset_put_alt["selector"] == "atmf_offset"
    assert offset_put_alt["right"] == "P"
    assert offset_put_alt["atm_offset_bps"] == pytest.approx(-25.0)
    assert offset_put_alt["canonical"] == "ZNM26|25BPP"

    atm_strike, abs_offsets, signed_offsets = _cme_listed_abs_offset_grid_bps_for_contract_forward(
        contract="ZNM26",
        forward=112.61,
        as_of=as_of,
    )
    assert atm_strike == pytest.approx(112.5)
    assert 50.0 in abs_offsets
    assert -50.0 in signed_offsets
    assert 50.0 in signed_offsets

    call_strike, call_offset = _snap_to_listed_strike_for_offset(
        contract="ZNM26",
        forward=112.61,
        as_of=as_of,
        right="C",
        offset_bps=50.0,
    )
    put_strike, put_offset = _snap_to_listed_strike_for_offset(
        contract="ZNM26",
        forward=112.61,
        as_of=as_of,
        right="P",
        offset_bps=50.0,
    )
    assert call_strike <= atm_strike <= put_strike
    assert call_offset == pytest.approx(abs(call_offset))
    assert put_offset == pytest.approx(-abs(put_offset))


def test_parse_qs_constant_maturity_ust_offset_aliases():
    parsed = _parse_qs_ust_option_request_symbol("TU_30|ATMF-25", as_of=datetime.date(2026, 3, 4))
    assert parsed["selector"] == "atmf_offset"
    assert parsed["right"] == "C"
    assert parsed["atm_offset_bps"] == pytest.approx(25.0)
    assert parsed["canonical"].endswith("|25BPC")
