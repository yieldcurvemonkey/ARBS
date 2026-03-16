import datetime as dt

import pytz
import QuantLib as ql

from BT.misc import ql_cal_date_range


def test_ql_cal_date_range_intraday_without_time_filter_returns_business_day_range():
    chi_tz = pytz.timezone("America/Chicago")
    start = chi_tz.localize(dt.datetime(2026, 3, 10, 9, 0))
    end = chi_tz.localize(dt.datetime(2026, 3, 10, 10, 0))
    cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)

    ts_range = ql_cal_date_range(cal, start=start, end=end, freq="1min")

    assert len(ts_range) == 61
    assert ts_range[0] == start
    assert ts_range[-1] == end
