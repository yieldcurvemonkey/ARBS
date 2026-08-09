"""Risk partition tests.

The behaviour under test is mostly about failure.  A transient curve error once
produced an all-null DV01 set in this repo that was published as a successful
run, and nothing downstream could tell "no risk" from "risk not computed".  So a
failed pricer must write null with a reason rather than a zero, and the read path
must refuse null rather than pass NaN along.
"""
from __future__ import annotations

import datetime

import numpy as np
import pytest

from RVUtils.MBO.store.risk import build_risk, dv01_for, dv01_map, read_risk

DATE = datetime.date(2026, 7, 14)


def _good(product, symbol, date):
    return {"ctd": "912810TX6", "conversion_factor": 0.7712,
            "dv01_per_contract": 64.5, "ctd_dv01": 83.6}


def _boom(product, symbol, date):
    raise RuntimeError("curve build failed")


def _nan(product, symbol, date):
    return {"ctd": None, "conversion_factor": None,
            "dv01_per_contract": float("nan"), "ctd_dv01": None}


# --------------------------------------------------------------------------- #
# SR3: intrinsic, nothing to fail
# --------------------------------------------------------------------------- #

def test_sr3_dv01_is_synthesised_from_the_intrinsic_bp_value(tmp_path):
    df = build_risk(str(tmp_path), "SR3", DATE, symbols=["SR3Z6", "SR3H7"])
    assert (df["dv01_per_contract"] == 25.0).all()
    assert (df["source"] == "intrinsic").all()


def test_sr3_needs_no_provider(tmp_path):
    """A rate contract's basis point is a property of the contract, not a curve."""
    build_risk(str(tmp_path), "SR3", DATE, symbols=["SR3Z6"], provider=_boom)
    assert dv01_for(str(tmp_path), "SR3Z6", DATE) == 25.0


# --------------------------------------------------------------------------- #
# Treasury: the pricer can fail, and that must be visible
# --------------------------------------------------------------------------- #

def test_treasury_dv01_comes_from_the_provider(tmp_path):
    df = build_risk(str(tmp_path), "ZN", DATE, symbols=["ZNU6"], provider=_good)
    assert df.iloc[0]["dv01_per_contract"] == pytest.approx(64.5)
    assert df.iloc[0]["ctd"] == "912810TX6"
    assert df.iloc[0]["source"] == "_good"


def test_a_failed_curve_build_is_recorded_as_failed_not_as_zero(tmp_path):
    df = build_risk(str(tmp_path), "ZN", DATE, symbols=["ZNU6"], provider=_boom)
    assert df["dv01_per_contract"].isna().all()
    assert (df["source"] == "FAILED").all()


def test_a_nan_from_the_provider_is_also_recorded_as_failed(tmp_path):
    """A pricer that returns NaN rather than raising is the same incident."""
    df = build_risk(str(tmp_path), "ZN", DATE, symbols=["ZNU6"], provider=_nan)
    assert (df["source"] == "FAILED").all()


def test_one_failure_does_not_stop_the_other_symbols(tmp_path):
    def flaky(product, symbol, date):
        if symbol == "ZNZ6":
            raise RuntimeError("nope")
        return _good(product, symbol, date)

    df = build_risk(str(tmp_path), "ZN", DATE, symbols=["ZNU6", "ZNZ6", "ZNH7"],
                    provider=flaky)
    assert len(df) == 3
    assert df.set_index("symbol").loc["ZNU6", "source"] == "flaky"
    assert df.set_index("symbol").loc["ZNZ6", "source"] == "FAILED"


# --------------------------------------------------------------------------- #
# the read path refuses to guess
# --------------------------------------------------------------------------- #

def test_dv01_for_raises_on_a_missing_row(tmp_path):
    build_risk(str(tmp_path), "SR3", DATE, symbols=["SR3Z6"])
    with pytest.raises(KeyError, match="no DV01 row"):
        dv01_for(str(tmp_path), "ZNU6", DATE)


def test_dv01_for_raises_on_a_null_row_rather_than_returning_nan(tmp_path):
    """This is the whole point: NaN would make a bp panel look like a quiet
    session instead of a failed build."""
    build_risk(str(tmp_path), "ZN", DATE, symbols=["ZNU6"], provider=_boom)
    with pytest.raises(KeyError, match="the row exists but is null"):
        dv01_for(str(tmp_path), "ZNU6", DATE)


def test_dv01_for_raises_on_an_unknown_symbol(tmp_path):
    with pytest.raises(KeyError, match="cannot tell which product"):
        dv01_for(str(tmp_path), "WOBBLE9", DATE)


def test_dv01_map_raises_on_the_first_miss(tmp_path):
    build_risk(str(tmp_path), "ZN", DATE, symbols=["ZNU6"], provider=_good)
    with pytest.raises(KeyError):
        dv01_map(str(tmp_path), ["ZNU6", "ZNZ6"], DATE)


def test_dv01_map_returns_every_symbol_when_all_are_present(tmp_path):
    build_risk(str(tmp_path), "ZN", DATE, symbols=["ZNU6", "ZNZ6"], provider=_good)
    got = dv01_map(str(tmp_path), ["ZNU6", "ZNZ6"], DATE)
    assert set(got) == {"ZNU6", "ZNZ6"}


# --------------------------------------------------------------------------- #
# round trip
# --------------------------------------------------------------------------- #

def test_read_risk_on_an_empty_store_is_typed_and_empty(tmp_path):
    df = read_risk(str(tmp_path), "ZN", [DATE])
    assert df.empty
    assert "dv01_per_contract" in df.columns


def test_rebuilding_replaces_rather_than_appends(tmp_path):
    build_risk(str(tmp_path), "ZN", DATE, symbols=["ZNU6"], provider=_boom)
    build_risk(str(tmp_path), "ZN", DATE, symbols=["ZNU6"], provider=_good)
    df = read_risk(str(tmp_path), "ZN", [DATE])
    assert len(df) == 1
    assert df.iloc[0]["dv01_per_contract"] == pytest.approx(64.5)


def test_a_treasury_panel_in_basis_points_works_once_risk_exists(tmp_path):
    """End to end: the units path that raised without a DV01 now resolves."""
    from RVUtils.MBO.store.panel import scale_to

    build_risk(str(tmp_path), "ZN", DATE, symbols=["ZNU6"], provider=_good)
    d = dv01_for(str(tmp_path), "ZNU6", DATE)
    assert scale_to("bp", "ZN", "OUTRIGHT", d) == pytest.approx(1000.0 / 64.5)
