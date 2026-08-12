"""Known-kill mutation: visibility_date returns the UTC date.

Expected red: test_the_ladder_date_is_a_new_york_date_not_a_utc_date.
"""
import datetime

import pandas as pd


def _bad(ts):
    if isinstance(ts, datetime.date) and not isinstance(ts, datetime.datetime):
        return ts
    return pd.Timestamp(ts).date()


def pytest_configure(config):
    from SDRUtils.dealer_direction import ladder
    ladder.visibility_date = _bad
    print("\n[mut1] visibility_date -> UTC date")
