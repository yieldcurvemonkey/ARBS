import datetime
import pandas as pd
import pytest
from SDRUtils.stir_flow import trade_selection as sel


def _leg(**kw):
    base = dict(
        trade_id="T1", package_id="OUTRIGHT-T1", as_of_date=datetime.date(2026, 7, 10),
        execution_timestamp=pd.Timestamp("2026-07-10 16:00:00+00:00"),
        original_execution_timestamp=pd.Timestamp("2026-07-10 16:00:00+00:00"),
        trade_type="OUTRIGHT", rate_index_clean="FED_FUNDS", venue="D2C",
        special_tenor_type="FOMC", fomc_meeting_label="JUL26",
        tenor_label="2M", forward_label=None, forward_start_years=0.0,
        effective_date=datetime.date(2026, 7, 29), expiration_date=datetime.date(2026, 9, 16),
        notional=1e9, risk=13_500.0, fixed_rate=0.03713,
        other_payment_ufro=0.0, pkg_ptp=None, pkg_pts=None,
        is_capped=False, is_block=False, is_off_date=False,
        leg_tape_label="USD-Federal Funds-OIS Compound 1D Constant FOMC JUL26 Outright PHYS",
        n_package_legs=1, package_structure="2M Outright",
    )
    base.update(kw)
    return base


def test_exclusion_reasons():
    ok = pd.DataFrame([_leg()])
    assert sel.is_excluded_unit(ok) is None

    cme_term = pd.DataFrame([_leg(leg_tape_label="USD-SOFR CME Term 1D Amortizing Spot 3Y Outright CASH")])
    assert sel.is_excluded_unit(cme_term) == "EXCLUDED_UNDERLIER"

    mms = pd.DataFrame([_leg(trade_type="MATCHED_MATURITY")])
    assert sel.is_excluded_unit(mms) == "EXCLUDED_TRADE_TYPE"

    too_long = pd.DataFrame([
        _leg(),
        _leg(trade_id="T2", expiration_date=datetime.date(2056, 9, 16)),
    ])
    assert sel.is_excluded_unit(too_long) == "LEG_BEYOND_3Y"

    no_rate = pd.DataFrame([_leg(fixed_rate=None)])
    assert sel.is_excluded_unit(no_rate) == "MISSING_FIXED_RATE"


def test_resolve_upfront():
    # plausible USD PTP wins
    assert sel.resolve_upfront(-48419.0, [22998.0, 25503.0]) == (48419.0, "PTP", False)
    # notation-polluted PTP falls back to UFRO sum
    up, src, flag = sel.resolve_upfront(9.99, [13427.27])
    assert (round(up, 2), src, flag) == (13427.27, "UFRO_SUM", False)
    # disagreement >2x flags
    up, src, flag = sel.resolve_upfront(-5392.0, [20430.0, 13219.0, 13257.0])
    assert src == "PTP" and flag is True
    # nothing present
    assert sel.resolve_upfront(None, [0.0]) == (None, None, False)


def test_build_units_groups_outright_and_package():
    eligible = pd.DataFrame([
        _leg(),
        _leg(trade_id="C1", package_id="PTP_C1", n_package_legs=2,
             package_structure="1M/1M Curve", trade_type="FOMC",
             pkg_ptp=-48419.0, other_payment_ufro=22998.0),
    ])
    all_legs = pd.DataFrame([
        _leg(),
        _leg(trade_id="C1", package_id="PTP_C1", n_package_legs=2,
             package_structure="1M/1M Curve", pkg_ptp=-48419.0,
             other_payment_ufro=22998.0),
        _leg(trade_id="C2", package_id="PTP_C1", n_package_legs=2,
             package_structure="1M/1M Curve", pkg_ptp=-48419.0,
             other_payment_ufro=25503.0, venue="D2D",   # ineligible leg still included
             effective_date=datetime.date(2026, 9, 16),
             expiration_date=datetime.date(2026, 10, 28)),
    ])
    units = sel.build_units(eligible, all_legs)
    keys = {u.unit_key: u for u in units}
    assert keys["T1"].kind == "OUTRIGHT" and len(keys["T1"].legs) == 1
    pkg = keys["PTP_C1"]
    assert pkg.kind == "CURVE" and len(pkg.legs) == 2 and pkg.is_off_market
    # legs sorted by expiration
    assert list(pkg.legs["trade_id"]) == ["C1", "C2"]


def test_build_units_deterministic_leg_order_on_tied_expiration():
    # Two legs share an expiration but differ in effective_date/trade_id.
    # Whatever physical order the DB returns, build_units must impose the same
    # total order (else FLY belly / iloc picks flake run-to-run).
    eligible = pd.DataFrame([
        _leg(trade_id="A", package_id="PTP_X", n_package_legs=2,
             package_structure="curve", pkg_ptp=-40000.0),
    ])
    leg_a = _leg(trade_id="A", package_id="PTP_X", n_package_legs=2,
                 effective_date=datetime.date(2026, 7, 29),
                 expiration_date=datetime.date(2026, 9, 16), pkg_ptp=-40000.0)
    leg_b = _leg(trade_id="B", package_id="PTP_X", n_package_legs=2,
                 effective_date=datetime.date(2026, 8, 12),
                 expiration_date=datetime.date(2026, 9, 16), pkg_ptp=-40000.0)
    fwd = sel.build_units(eligible, pd.DataFrame([leg_a, leg_b]))
    rev = sel.build_units(eligible, pd.DataFrame([leg_b, leg_a]))  # reversed input
    o1 = list({u.unit_key: u for u in fwd}["PTP_X"].legs["trade_id"])
    o2 = list({u.unit_key: u for u in rev}["PTP_X"].legs["trade_id"])
    assert o1 == o2 == ["A", "B"]   # tie broken by effective_date (07-29 < 08-12)
