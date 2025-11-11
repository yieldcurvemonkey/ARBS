# ABOUTME: Utility functions for converting between Python dates and QuantLib dates
# ABOUTME: Handles date conversions and business day calendar operations for QuantLib integration
from datetime import date, datetime
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd
import QuantLib as ql


def ql_date_to_datetime(ql_date: ql.Date):
    return datetime(ql_date.year(), ql_date.month(), ql_date.dayOfMonth())


def ql_date_to_pydate(ql_date: ql.Date):
    return date(ql_date.year(), ql_date.month(), ql_date.dayOfMonth())


def datetime_to_ql_date(dt: datetime):
    day = dt.day
    month = dt.month
    year = dt.year

    ql_month = {
        1: ql.January,
        2: ql.February,
        3: ql.March,
        4: ql.April,
        5: ql.May,
        6: ql.June,
        7: ql.July,
        8: ql.August,
        9: ql.September,
        10: ql.October,
        11: ql.November,
        12: ql.December,
    }[month]

    return ql.Date(day, ql_month, year)


def most_recent_business_day_ql(ql_calendar: ql.Calendar, tz: Optional[str] = "UTC", to_pydate: Optional[bool] = False):
    current_ts = pd.Timestamp.now(ZoneInfo(tz)).normalize()
    current_pydate = current_ts.to_pydatetime().date()
    current_ql = ql.Date(current_pydate.day, current_pydate.month, current_pydate.year)

    while not ql_calendar.isBusinessDay(current_ql):
        current_ql = current_ql - 1

    if to_pydate:
        return datetime(current_ql.year(), current_ql.month(), current_ql.dayOfMonth())
    else:
        return current_ql
