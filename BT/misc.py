import datetime

import pandas as pd
import QuantLib as ql


def ql_cal_date_range(ql_cal: ql.Calendar, start: datetime.datetime, end: datetime.datetime):
    if type(start) == datetime.datetime and start.tzinfo is not None:
        assert str(start.tzinfo) == str(end.tzinfo), "must be from same tz!"
        assert start.time() == end.time(), "must be same closes!"

    def _to_ql_date(dt: datetime.datetime):
        return ql.Date(dt.day, dt.month, dt.year)

    pd_range = pd.date_range(start=start, end=end, freq="1b")
    return [d for d in pd_range if ql_cal.isBusinessDay(_to_ql_date(d))]
