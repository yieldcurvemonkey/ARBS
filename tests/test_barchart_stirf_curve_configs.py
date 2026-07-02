import datetime

import pytest

pytest.importorskip("rateslib")
pytest.importorskip("QuantLib")
import rateslib as rl

from MDP.IRSwaps.BARCHART_STIRF.rl import BARCHART_STIRF_CURVE
from MDP.STIRFutures import STIRFutureMDP as stir_mdp_module
from Query.IRSwaps._CENTRAL_BANK_DATES import _CENTRAL_BANK_DATES
from Query.IRSwaps.backends.rateslib.rl_curve_definitions_map import RATESLIB_CURVE_DEFINITIONS


def test_new_barchart_root_to_curve_mapping():
    expected = {
        "IJH26": "EUR-ESTR",
        "RGH26": "CAD-CORRA",
        "IMH26": "EUR-EURIBOR-3M",
        "TVH26": "EUR-EURIBOR-3M",
        "J8H26": "GBP-SONIA",
        "JUH26": "GBP-SONIA",
        "T0H26": "JPY-TONA",
        "ITH26": "JPY-TONA",
        "J2H26": "CHF-SARON",
    }

    for symbol, curve in expected.items():
        assert stir_mdp_module._curve_from_symbol(symbol) == curve


def test_new_cm_aliases_resolve_for_added_roots():
    asof = datetime.date(2026, 1, 15)
    aliases = stir_mdp_module._resolve_aliases_bulk(
        ["IJCM1", "RGCM1", "J8CM1", "JUCM1", "T0CM1", "ITCM1", "J2CM1", "IMCM1", "TVCM1"],
        asof,
    )

    assert aliases["IJCM1"][0].startswith("IJ")
    assert aliases["RGCM1"][0].startswith("RG")
    assert aliases["J8CM1"][0].startswith("J8")
    assert aliases["JUCM1"][0].startswith("JU")
    assert aliases["T0CM1"][0].startswith("T0")
    assert aliases["ITCM1"][0].startswith("IT")
    assert aliases["J2CM1"][0].startswith("J2")
    assert aliases["IMCM1"][0].startswith("IM")
    assert aliases["TVCM1"][0].startswith("TV")


def test_curve_configs_cover_central_banks_added_from_calendar_file():
    curve_builder = BARCHART_STIRF_CURVE()
    cfgs = curve_builder._STIRF_CURVE_CONFIGS

    required_cb_keys = {"CAD-CORRA", "GBP-SONIA", "JPY-TONA", "CHF-SARON"}
    assert required_cb_keys.issubset(set(_CENTRAL_BANK_DATES.keys()))

    node_keys = {cfg.get("node_reference_key", cfg["reference_key"]) for cfg in cfgs.values()}
    assert required_cb_keys.issubset(node_keys)

    assert "EUR-ESTR-LONDON-Q12STIRT" in cfgs
    assert "CAD-CORRA-Q8STIRT" in cfgs
    assert "GBP-SONIA-Q12STIRT" in cfgs
    assert "JPY-TONA-JPX-Q12STIRT" in cfgs
    assert "JPY-TONA-TFX-Q12STIRT" in cfgs
    assert "CHF-SARON-Q12STIRT" in cfgs
    assert "EUR-EURIBOR-ICE-Q12STIRT" in cfgs
    assert "EUR-EURIBOR-EUREX-Q12STIRT" in cfgs


def test_rateslib_calendar_keys_exist_for_added_curves():
    for curve_key in ["CAD-CORRA", "GBP-SONIA", "JPY-TONA", "CHF-SARON", "EUR-EURIBOR-3M"]:
        cal_key = RATESLIB_CURVE_DEFINITIONS[curve_key]["Calendar"]
        assert cal_key in rl.defaults.calendars


def test_reference_rate2_3_stir_specs_when_available():
    expected = {
        "USD-SOFR-1D": ("usd_stir", "usd_stir1"),
        "USD-FEDFUNDS": ("usd_stir1", "usd_stir1"),
        "USD-OIS": ("usd_stir", "usd_stir1"),
        "USD-OIS-STIR": ("usd_stir", "usd_stir1"),
        "EUR-ESTR": ("eur_stir", "eur_stir1"),
        "EUR-EURIBOR-3M": ("eur_stir3", "eur_stir3"),
        "GBP-SONIA": ("gbp_stir", "gbp_stir"),
    }

    for curve_key, (rr2, rr3) in expected.items():
        assert RATESLIB_CURVE_DEFINITIONS[curve_key]["ReferenceRate2"] == rr2
        assert RATESLIB_CURVE_DEFINITIONS[curve_key]["ReferenceRate3"] == rr3
        assert rr2 in rl.defaults.spec
        assert rr3 in rl.defaults.spec
