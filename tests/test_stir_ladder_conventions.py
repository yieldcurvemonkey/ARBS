import datetime
import pandas as pd
import pytest
from SDRUtils.stir_flow import ladder_conventions as lc


def test_visibility_rule():
    ts = pd.Timestamp("2026-07-10 19:41:45+00:00")
    assert lc.visibility_timestamp(ts, is_block=False) == ts + pd.Timedelta(minutes=1)
    assert lc.visibility_timestamp(ts, is_block=True) == ts + pd.Timedelta(minutes=15)


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
