import datetime

import pandas as pd
import QuantLib as ql

from typing import Optional


def ql_cal_date_range(
    ql_cal: ql.Calendar,
    start: datetime.datetime,
    end: datetime.datetime,
    freq: str = "1b",
    open_time: datetime.time = datetime.time(7, 0),
    close_time: datetime.time = datetime.time(15, 0),
    to_date: bool = False,
):
    if isinstance(start, datetime.datetime) and start.tzinfo is not None:
        assert str(start.tzinfo) == str(end.tzinfo), "must be from same tz!"

    def _to_ql_date(dt: datetime.datetime):
        return ql.Date(dt.day, dt.month, dt.year)

    def _in_session(ts: pd.Timestamp) -> bool:
        t = ts.time()
        if open_time <= close_time:
            return open_time <= t <= close_time
        else:
            # overnight session, e.g. 17:00 -> 16:00 next day
            return t >= open_time or t <= close_time

    def _session_date(ts: pd.Timestamp) -> pd.Timestamp:
        # For overnight sessions, times after open belong to next calendar day
        if open_time > close_time and ts.time() >= open_time:
            return ts + pd.Timedelta(days=1)
        return ts

    pd_range = pd.date_range(start=start, end=end, freq=freq)

    filtered = []
    for ts in pd_range:
        session_dt = _session_date(ts)
        if ql_cal.isBusinessDay(_to_ql_date(session_dt)) and _in_session(ts):
            filtered.append(ts)

    if to_date:
        return [d.date() for d in filtered]
    return filtered


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
