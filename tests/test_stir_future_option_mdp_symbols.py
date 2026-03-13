import datetime

import pytest

from MDP.STIRFutures.STIRFutureOptionMDP import (
    STIRFutureOptionMDP,
    STIRFutureOptionSmilePoint,
    _canonical_to_barchart_contract,
    _canonical_to_barchart_option,
    _canonical_to_schwab_option_symbol,
    _canonical_underlying,
    _cme_listed_abs_offset_grid_bps_for_contract_forward,
    _cme_listed_strike_rule_for_contract,
    _contract_to_schwab_future_symbol,
    _contract_code_from_symbol,
    _expand_straddle_symbol,
    _format_strike4,
    _norm_option_symbol,
    _parse_option_request_symbol,
    _resolve_option_contract_aliases_for_date,
    _right_from_symbol,
    _snap_to_listed_strike_for_offset,
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


def test_symbol_components_and_schwab_mapping():
    assert _contract_to_schwab_future_symbol("SFRZ27") == "/SR3Z27"
    assert _contract_to_schwab_future_symbol("SERM27") == "/SR1M27"
    assert _canonical_to_schwab_option_symbol("SFRZ27|9700C") == "./SR3Z27C97"
    assert _canonical_to_schwab_option_symbol("SFRZ27|9662C") == "./SR3Z27C96.625"
    assert _canonical_to_schwab_option_symbol("0QH26|9700P") == "./0QH26P97"


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

    offset_call = _parse_option_request_symbol("SFRZ27|25BPC")
    assert offset_call["selector"] == "atmf_offset"
    assert offset_call["right"] == "C"
    assert offset_call["atm_offset_bps"] == pytest.approx(25.0)
    assert offset_call["canonical"] == "SFRZ27|25BPC"

    offset_call_alt = _parse_option_request_symbol("SFRZ27|ATMF-25")
    assert offset_call_alt["selector"] == "atmf_offset"
    assert offset_call_alt["right"] == "C"
    assert offset_call_alt["atm_offset_bps"] == pytest.approx(25.0)
    assert offset_call_alt["canonical"] == "SFRZ27|25BPC"

    offset_put_alt = _parse_option_request_symbol("SFRZ27|ATMF+25")
    assert offset_put_alt["selector"] == "atmf_offset"
    assert offset_put_alt["right"] == "P"
    assert offset_put_alt["atm_offset_bps"] == pytest.approx(-25.0)
    assert offset_put_alt["canonical"] == "SFRZ27|25BPP"

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


def test_sofr_style_fine_grid_tokens_use_vendor_encoding():
    assert _format_strike4(96.0625, contract="SFRU26") == "9606"
    assert _format_strike4(96.1875, contract="SFRU26") == "9618"
    assert _format_strike4(96.3750, contract="SFRU26") == "9637"
    assert _format_strike4(96.4375, contract="SFRU26") == "9643"
    assert _format_strike4(96.6250, contract="SFRU26") == "9662"
    assert _format_strike4(96.9375, contract="SFRU26") == "9693"

    assert _strike_from_symbol("SFRU26|9637C") == pytest.approx(96.3750)
    assert _strike_from_symbol("SFRU26|9643C") == pytest.approx(96.4375)
    assert _strike_from_symbol("SFRU26|9662C") == pytest.approx(96.6250)
    assert _canonical_to_barchart_option("SFRU26|9637C") == "SQU26|9637C"


def test_cme_listed_strike_rules_cover_front_and_back_contract_buckets():
    as_of = datetime.date(2026, 3, 19)

    assert _cme_listed_strike_rule_for_contract(contract="SFRU26", as_of=as_of)["fine_step"] == pytest.approx(0.0625)
    assert _cme_listed_strike_rule_for_contract(contract="SFRZ26", as_of=as_of)["fine_step"] == pytest.approx(0.0625)
    assert _cme_listed_strike_rule_for_contract(contract="SFRH27", as_of=as_of)["fine_step"] == pytest.approx(0.0625)
    assert _cme_listed_strike_rule_for_contract(contract="SFRM27", as_of=as_of)["fine_step"] == pytest.approx(0.125)
    assert _cme_listed_strike_rule_for_contract(contract="0QM26", as_of=as_of)["fine_step"] == pytest.approx(0.0625)
    assert _cme_listed_strike_rule_for_contract(contract="0QU26", as_of=as_of)["fine_step"] == pytest.approx(0.125)
    assert _cme_listed_strike_rule_for_contract(contract="S01M26", as_of=as_of)["fine_step"] == pytest.approx(0.0625)
    assert _cme_listed_strike_rule_for_contract(contract="3QU26", as_of=as_of)["fine_step"] == pytest.approx(0.125)


def test_listed_offset_grid_and_snap_use_rate_space_signs():
    as_of = datetime.date(2026, 3, 4)
    atm_strike, abs_offsets, signed_offsets = _cme_listed_abs_offset_grid_bps_for_contract_forward(
        contract="SFRU26",
        forward=96.61,
        as_of=as_of,
    )

    assert atm_strike == pytest.approx(96.625)
    assert abs_offsets[:4] == pytest.approx([0.0, 6.25, 12.5, 18.75])
    assert 150.0 in abs_offsets
    assert 175.0 in abs_offsets
    assert -12.5 in signed_offsets
    assert 12.5 in signed_offsets

    call_strike, call_offset = _snap_to_listed_strike_for_offset(
        contract="SFRU26",
        forward=96.61,
        as_of=as_of,
        right="C",
        offset_bps=12.5,
    )
    put_strike, put_offset = _snap_to_listed_strike_for_offset(
        contract="SFRU26",
        forward=96.61,
        as_of=as_of,
        right="P",
        offset_bps=12.5,
    )

    assert call_strike == pytest.approx(96.5)
    assert put_strike == pytest.approx(96.75)
    assert call_offset == pytest.approx(12.5)
    assert put_offset == pytest.approx(-12.5)


def test_sabr_smile_offset_request_normalization_uses_absolute_unique_bps():
    mdp = STIRFutureOptionMDP(source="STIRFO_DUAL-QL")

    normalized = mdp._normalize_sabr_smile_point_request({"strike_offsets_bps": [-10, 10.0, -5, 5.0]})
    assert normalized == {
        "mode": "atm_offset_bps",
        "strike_offsets_bps": [5.0, 10.0],
        "auto_full_ladder": False,
    }

    listed = mdp._normalize_sabr_smile_point_request({"strike_offsets_bps": "listed"})
    assert listed == {
        "mode": "atm_offset_bps",
        "strike_offsets_bps": [],
        "auto_full_ladder": True,
    }


def test_sabr_smile_listed_auto_full_ladder_caps_to_225bps():
    mdp = STIRFutureOptionMDP(source="STIRFO_DUAL-QL")

    legs = mdp._build_sabr_smile_offset_leg_specs(
        contract="SFRZ26",
        forward=97.0,
        as_of=datetime.date(2026, 3, 2),
        offset_magnitudes_bps=[],
        auto_full_ladder=True,
    )

    assert len(legs) == 56
    abs_offsets = sorted({round(abs(float(leg["requested_atm_offset_bps"])), 8) for leg in legs})
    assert abs_offsets[-1] == pytest.approx(225.0)
    assert 225.0 in abs_offsets
    assert 250.0 not in abs_offsets


def test_sabr_smile_explicit_offsets_are_not_capped():
    mdp = STIRFutureOptionMDP(source="STIRFO_DUAL-QL")

    legs = mdp._build_sabr_smile_offset_leg_specs(
        contract="SFRZ26",
        forward=97.0,
        as_of=datetime.date(2026, 3, 2),
        offset_magnitudes_bps=[25.0, 300.0],
        auto_full_ladder=False,
    )

    abs_offsets = sorted({round(abs(float(leg["requested_atm_offset_bps"])), 8) for leg in legs})
    assert abs_offsets == pytest.approx([0.0, 25.0, 300.0])


def test_sabr_smile_point_roundtrip_preserves_atm_offset_bps():
    point = STIRFutureOptionSmilePoint(
        label="SFRU26|9662C",
        right="C",
        delta_abs=25.0,
        atm_offset_bps=12.5,
        strike_price=96.5,
        strike_rate=3.5,
        iv_normal_price=0.155,
        iv_normal_bps=15.5,
    )

    assert STIRFutureOptionSmilePoint.from_dict(point.to_dict()) == point
