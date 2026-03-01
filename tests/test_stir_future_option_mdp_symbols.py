import datetime

import pytest

from MDP.STIRFutures.STIRFutureOptionMDP import (
    _canonical_to_barchart_contract,
    _canonical_to_barchart_option,
    _canonical_underlying,
    _contract_code_from_symbol,
    _expand_straddle_symbol,
    _norm_option_symbol,
    _parse_option_request_symbol,
    _resolve_option_contract_aliases_for_date,
    _right_from_symbol,
    _strike_from_symbol,
)


def test_symbol_aliases_normalize_to_sfr():
    assert _norm_option_symbol("SR3Z30|9700C") == "SFRZ30|9700C"
    assert _norm_option_symbol("SFRZ30|9700c") == "SFRZ30|9700C"
    assert _norm_option_symbol("SQZ30|9700P") == "SFRZ30|9700P"


def test_symbol_components_and_barchart_mapping():
    sym = _norm_option_symbol("SQZ30|9750C")
    assert _right_from_symbol(sym) == "C"
    assert _contract_code_from_symbol(sym) == "Z30"
    assert _strike_from_symbol(sym) == pytest.approx(97.50)
    assert _canonical_to_barchart_contract(sym) == "SQZ30"
    assert _canonical_to_barchart_option(sym) == "SQZ30|9750C"


def test_straddle_expansion():
    assert _expand_straddle_symbol("SR3Z30|9700S") == ["SFRZ30|9700C", "SFRZ30|9700P"]
    assert _expand_straddle_symbol("SFRZ30|9700C") == ["SFRZ30|9700C"]


def test_invalid_root_rejected():
    with pytest.raises(ValueError):
        _norm_option_symbol("TYZ30|9700C")


def test_option_alias_parsing_atm_and_delta():
    atm = _parse_option_request_symbol("SFRZ27|ATMS")
    assert atm["selector"] == "atm"
    assert atm["contract"] == "SFRZ27"
    assert atm["right"] == "S"

    delta = _parse_option_request_symbol("SQZ27|25DC")
    assert delta["selector"] == "delta"
    assert delta["contract"] == "SFRZ27"
    assert delta["right"] == "C"
    assert delta["delta"] == pytest.approx(25.0)

    natural = _parse_option_request_symbol("SFRZ27 ATM straddle")
    assert natural["selector"] == "atm"
    assert natural["right"] == "S"


def test_constant_maturity_option_contract_alias_parsing():
    cm = _parse_option_request_symbol("SFRCM1|ATMS")
    assert cm["selector"] == "atm"
    assert cm["contract_selector"] == "cm"
    assert cm["cm_root"] == "SFR"
    assert cm["cm_rank"] == 1

    cm_default = _parse_option_request_symbol("CM2|9700C")
    assert cm_default["selector"] == "strike"
    assert cm_default["contract_selector"] == "cm"
    assert cm_default["cm_root"] == "SFR"
    assert cm_default["cm_rank"] == 2

    # Midcurve CM alias: S0CM1 -> first listed 1Y midcurve contract
    cm_s0 = _parse_option_request_symbol("S0CM1|ATMS")
    assert cm_s0["selector"] == "atm"
    assert cm_s0["contract_selector"] == "cm"
    assert cm_s0["cm_root"] == "0Q"
    assert cm_s0["cm_rank"] == 1

    resolved = _resolve_option_contract_aliases_for_date({"x": cm_s0}, datetime.date(2026, 2, 27))
    # Internal canonical root for S0 is 0Q.
    assert resolved["x"]["contract"] == "0QH26"


def test_midcurve_contract_mapping_and_underlying():
    sym = _norm_option_symbol("0QH26|9700C")
    assert sym == "0QH26|9700C"
    assert _canonical_to_barchart_contract(sym) == "MMAH26"
    assert _canonical_underlying(sym) == "SFRH27"

    # S0 alias should canonicalize to 0Q.
    sym_alias = _norm_option_symbol("S0H26|9700C")
    assert sym_alias == "0QH26|9700C"
