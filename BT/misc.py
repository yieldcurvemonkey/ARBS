import datetime

import pandas as pd
import QuantLib as ql

from typing import Optional


def ql_cal_date_range(
    ql_cal: ql.Calendar,
    start: datetime.datetime,
    end: datetime.datetime,
    freq: Optional[str] = "1b",
    open_time: Optional[datetime.time] = datetime.time(7, 00),
    close_time: Optional[datetime.time] = datetime.time(15, 00),
):
    if type(start) == datetime.datetime and start.tzinfo is not None:
        assert str(start.tzinfo) == str(end.tzinfo), "must be from same tz!"
        # assert start.time() == end.time(), "must be same closes!"

    def _to_ql_date(dt: datetime.datetime):
        return ql.Date(dt.day, dt.month, dt.year)

    pd_range = pd.date_range(start=start, end=end, freq=freq)
    date_filtered_range = [d for d in pd_range if ql_cal.isBusinessDay(_to_ql_date(d))]
    if "min" in freq or "hr" in freq:
        time_filtered_range = []
        for ts in date_filtered_range:
            if ts.time() >= open_time and ts.time() <= close_time:
                time_filtered_range.append(ts)
        return time_filtered_range

    return date_filtered_range


def _to_ql(d: datetime.date) -> ql.Date:
    return ql.Date(d.day, d.month, d.year)


def _to_py(d: ql.Date) -> datetime.date:
    return datetime.date(d.year(), int(d.month()), d.dayOfMonth())


def _last_business_day_of_month(cal: ql.Calendar, y: int, m: int) -> datetime.date:
    # start from calendar end-of-month and walk back to a business day
    d = ql.Date.endOfMonth(ql.Date(1, m, y))
    while not cal.isBusinessDay(d):
        d = d - 1
    return _to_py(d)


def _nth_business_day_of_month(cal: ql.Calendar, y: int, m: int, n: int) -> datetime.date:
    # n >= 1, find nth business day counting from first of month
    d = ql.Date(1, m, y)
    count = 0
    while True:
        if cal.isBusinessDay(d):
            count += 1
            if count == n:
                return _to_py(d)
        d = d + 1


def _n_business_days_before(cal: ql.Calendar, d: datetime.date, n: int) -> datetime.date:
    qd = _to_ql(d)
    c = 0
    while c < n:
        qd = qd - 1
        if cal.isBusinessDay(qd):
            c += 1
    return _to_py(qd)


def _month_iter(start: datetime.date, end: datetime.date) -> list[tuple[int, int]]:
    ym = []
    y, m = start.year, start.month
    ey, em = end.year, end.month
    while (y < ey) or (y == ey and m <= em):
        ym.append((y, m))
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1
    return ym
