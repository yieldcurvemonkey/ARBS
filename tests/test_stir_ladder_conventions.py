import datetime
import pandas as pd
import pytest
from SDRUtils.stir_flow import ladder_conventions as lc


def test_visibility_rule_on_facility_non_block():
    ts = pd.Timestamp("2026-07-10 19:41:45+00:00")
    assert lc.visibility_timestamp(
        ts, is_block=False, cleared=None, on_facility=True, is_capped=False,
    ) == ts + pd.Timedelta(minutes=1)


def test_visibility_rule_sef_block():
    ts = pd.Timestamp("2026-07-10 19:41:45+00:00")
    assert lc.visibility_timestamp(
        ts, is_block=True, cleared=None, on_facility=True, is_capped=False,
    ) == ts + pd.Timedelta(minutes=15)


def test_visibility_rule_cleared_off_facility_capped():
    ts = pd.Timestamp("2026-07-10 19:41:45+00:00")
    assert lc.visibility_timestamp(
        ts, is_block=False, cleared=True, on_facility=False, is_capped=True,
    ) == ts + pd.Timedelta(minutes=15)


def test_visibility_rule_uncleared_off_facility():
    ts = pd.Timestamp("2026-07-10 19:41:45+00:00")
    assert lc.visibility_timestamp(
        ts, is_block=False, cleared=False, on_facility=False, is_capped=False,
    ) == ts + pd.Timedelta(minutes=30)


def test_visibility_rule_indeterminate_missing_field():
    ts = pd.Timestamp("2026-07-10 19:41:45+00:00")
    # on_facility missing (None) -> can't classify -> conservative fallback,
    # regardless of the other three fields being fully determined.
    assert lc.visibility_timestamp(
        ts, is_block=False, cleared=True, on_facility=None, is_capped=True,
    ) == ts + pd.Timedelta(minutes=60)


def test_visibility_rule_backward_compat_old_signature():
    # Pre-audit call pattern: only is_block passed positionally-as-keyword,
    # same as the old two-bucket API. on_facility/cleared default to None
    # (indeterminate) -> +60min for BOTH block and non-block, which is more
    # conservative than the old +15min/+1min rule the audit invalidated —
    # acceptable per the audit. The call must not raise despite is_block now
    # being keyword-only.
    ts = pd.Timestamp("2026-07-10 19:41:45+00:00")
    assert lc.visibility_timestamp(ts, is_block=False) == ts + pd.Timedelta(minutes=60)
    assert lc.visibility_timestamp(ts, is_block=True) == ts + pd.Timedelta(minutes=60)


def test_visibility_class_all_branches():
    assert lc.visibility_class(is_block=False, cleared=None, on_facility=True,
                               is_capped=False) == "ON_FACILITY_NON_BLOCK"
    assert lc.visibility_class(is_block=True, cleared=None, on_facility=True,
                               is_capped=False) == "SEF_BLOCK"
    assert lc.visibility_class(is_block=False, cleared=True, on_facility=False,
                               is_capped=True) == "CLEARED_OFF_FACILITY_CAPPED"
    assert lc.visibility_class(is_block=False, cleared=False, on_facility=False,
                               is_capped=False) == "UNCLEARED_OFF_FACILITY"
    assert lc.visibility_class(is_block=False, cleared=None, on_facility=None,
                               is_capped=False) == "INDETERMINATE"
    # Unenumerated combination (off-facility, cleared, but not capped) also
    # falls back to indeterminate -- there's no dedicated class for it.
    assert lc.visibility_class(is_block=False, cleared=True, on_facility=False,
                               is_capped=False) == "INDETERMINATE"


def test_dealer_leg_signs_outright():
    assert lc.dealer_leg_signs("OUTRIGHT", "RATE_VS_MID", "RECEIVED", 1) == [1]
    assert lc.dealer_leg_signs("OUTRIGHT", "RATE_VS_MID", "PAID", 1) == [-1]
    assert lc.dealer_leg_signs("OUTRIGHT", "TICK_RULE", "RECEIVED", 1) == [1]
    assert lc.dealer_leg_signs("OUTRIGHT", "NPV_VS_UPFRONT", "PAID", 1) == [-1]


def test_dealer_leg_signs_on_market_structures():
    # RECEIVED the spread = received back / paid front (legs sorted by maturity)
    assert lc.dealer_leg_signs("CURVE", "SPREAD_VS_MID", "RECEIVED", 2) == [-1, 1]
    assert lc.dealer_leg_signs("CURVE", "SPREAD_VS_MID", "PAID", 2) == [1, -1]
    # RECEIVED the fly = received belly / paid wings
    assert lc.dealer_leg_signs("FLY", "FLY_VS_MID", "RECEIVED", 3) == [-1, 1, -1]
    assert lc.dealer_leg_signs("FLY", "FLY_VS_MID", "PAID", 3) == [1, -1, 1]


def test_dealer_leg_signs_off_market_packages_same_frame():
    # NPV_VS_UPFRONT direction is the net-fixed frame: ALL legs share the sign
    assert lc.dealer_leg_signs("CURVE", "NPV_VS_UPFRONT", "RECEIVED", 2) == [1, 1]
    assert lc.dealer_leg_signs("FLY", "NPV_VS_UPFRONT", "PAID", 3) == [-1, -1, -1]
    assert lc.dealer_leg_signs("PKG", "NPV_VS_UPFRONT", "RECEIVED", 5) == [1] * 5


def test_dealer_leg_signs_rejects_unknown():
    with pytest.raises(ValueError):
        lc.dealer_leg_signs("CURVE", "SPREAD_VS_MID", "UNKNOWN", 2)


def test_bucket_keys():
    assert lc.meeting_bucket_key(datetime.date(2026, 10, 28)) == "2026-10-28"
    assert lc.meeting_bucket_key(pd.Timestamp("2026-10-28")) == "2026-10-28"
    assert lc.contract_month_key(datetime.date(2026, 10, 1)) == "2026-10"


def test_venue_status():
    from SDRUtils.stir_flow.trade_selection import venue_status
    assert venue_status("TWSF") == "D2C_WHITELISTED"
    assert venue_status("BGCD") == "D2D"
    assert venue_status("TREU") == "VENUE_UNKNOWN"
    assert venue_status(None) == "VENUE_UNKNOWN"
    assert venue_status("") == "VENUE_UNKNOWN"


def test_venue_status_full_whitelist_and_normalization():
    from SDRUtils.stir_flow.trade_selection import venue_status
    # All three whitelisted platforms, not just TWSF.
    assert venue_status("BBSF") == "D2C_WHITELISTED"
    assert venue_status("BILT") == "D2C_WHITELISTED"
    # All six D2D/IDB codes remain D2D, not just BGCD.
    for code in ("BGCD", "DWSF", "IGDL", "ISWV", "TPSE", "TSEF"):
        assert venue_status(code) == "D2D"
    # pid normalization: lowercase + surrounding whitespace.
    assert venue_status("twsf") == "D2C_WHITELISTED"
    assert venue_status("  TWSF  ") == "D2C_WHITELISTED"
    assert venue_status("bgcd") == "D2D"
    # Platforms with real volume (BMTF/BGC MTF) that aren't yet validated
    # stay VENUE_UNKNOWN -- conservative-until-proven-D2C per Task A2.
    assert venue_status("BMTF") == "VENUE_UNKNOWN"
    # NaN (as opposed to None) must also route through pd.notna's False branch.
    assert venue_status(float("nan")) == "VENUE_UNKNOWN"
