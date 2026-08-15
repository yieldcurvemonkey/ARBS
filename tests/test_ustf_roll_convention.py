"""Treasury futures roll: which contract a bare root resolves to, and when carry ends.

Four sites resolved a bare root independently, all using the IMM date (third Wednesday) -- a
Eurodollar convention with no meaning for a Treasury future. They agreed only because all four had
been written the same way, so a fix to one would have made `warm_ustf_cache` warm `TYU26` while
`usd_swaps` read `TYZ26`, with no error anywhere. They now share one resolver, and the last test
here is the cross-site invariant that would have caught the drift.

The handover's suspicion -- that the IMM rule names EXPIRED contracts -- is false: measured over
2,168 CME business days it never does, because the IMM date always falls before the last trading
day. The real defect is the opposite. The IMM rule holds the expiring contract a median 16 business
days past the liquidity roll, so on ~25% of days every implicit quote, warm and basis report in the
repo came off a contract holding a median ~1% of the liquid contract's open interest.

Against the contract actually carrying the most open interest, 2018-2026:
    IMM (previous)      TY 25.3% wrong   TU 25.4%   WN 26.9%
    last trading day    TY 28.8% wrong   TU 39.9%   WN 29.4%   <- the obvious "fix" is WORSE
    first position day  TY  3.7% wrong   TU  3.8%   WN  4.4%   <- adopted

These are date arithmetic on a holiday calendar, so the failure mode is a wrong calendar and the
tests are a golden table, not properties. The fixture is the last bar BarChart actually holds for
192 expired contracts (6 roots x 2018-2025); the mutation test at the end swaps in the federal
calendar and requires the table to fail.
"""

from __future__ import annotations

import csv
import datetime
import pathlib

import pytest

from definitions.USTFutures import (
    CMEInterestRateCalendar,
    back_months,
    front_month,
    ust_deliverable_contract,
    ust_first_position_day,
    ust_last_trading_day,
)

_FIXTURE = pathlib.Path(__file__).parent / "_data" / "ustf_last_trading_days.csv"
_MONTH = {"H": 3, "M": 6, "U": 9, "Z": 12}


def _fixture_rows():
    with _FIXTURE.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            code = row["code"]
            yield row["root"], code, 2000 + int(code[1:]), _MONTH[code[0]], datetime.date.fromisoformat(row["observed"])


def test_last_trading_day_matches_every_observed_final_bar():
    """192 expired contracts, 6 roots, 2018-2025. Exact, not approximate."""
    rows = list(_fixture_rows())
    assert len(rows) == 192, "fixture truncated"

    wrong = [
        (f"{root}{code}", observed, ust_last_trading_day(root, year, month))
        for root, code, year, month, observed in rows
        if ust_last_trading_day(root, year, month) != observed
    ]
    assert not wrong, f"{len(wrong)} of {len(rows)} contracts disagree: {wrong[:5]}"


def test_the_calendar_check_discriminates():
    """MUTATION TEST. Swap the CME calendar for the federal one; the table must break.

    Without this the test above passes for any calendar that happens to agree on most dates, which
    is exactly how a wrong calendar survives. Measured: the federal calendar scores 174/192, and the
    18 it misses are Good Friday 2018 and 2024 and the 2021 New Year.
    """
    import pandas as pd
    from pandas.tseries.holiday import USFederalHolidayCalendar
    from pandas.tseries.offsets import CustomBusinessDay

    from definitions.USTFutures import UST_FUTURE_LAST_TRADE_BD_BEFORE_MONTH_END

    fed = CustomBusinessDay(calendar=USFederalHolidayCalendar())

    def fed_ltd(root, year, month):
        stamp = pd.Timestamp(year=year, month=month, day=1) + pd.offsets.MonthEnd(0)
        if not fed.is_on_offset(stamp):
            stamp = stamp - fed
        offset = UST_FUTURE_LAST_TRADE_BD_BEFORE_MONTH_END[root]
        return (stamp - offset * fed).date() if offset else stamp.date()

    rows = list(_fixture_rows())
    misses = [f"{r}{c}" for r, c, y, m, obs in rows if fed_ltd(r, y, m) != obs]
    assert len(misses) == 18, f"expected the federal calendar to miss 18, got {len(misses)}: {misses}"


@pytest.mark.parametrize(
    "day,closed",
    [
        (datetime.date(2024, 3, 29), True),   # Good Friday -- CME closed, federal calendar has no rule
        (datetime.date(2018, 3, 30), True),   # Good Friday
        (datetime.date(2024, 10, 14), False),  # Columbus Day -- CME OPEN, federal closed
        (datetime.date(2024, 11, 11), False),  # Veterans Day -- CME OPEN, federal closed
        (datetime.date(2021, 12, 31), False),  # New Year on a Saturday -- exchange traded 12-31
        (datetime.date(2024, 6, 19), True),   # Juneteenth
    ],
)
def test_the_three_calendar_rules_that_actually_differ(day, closed):
    holidays = set(CMEInterestRateCalendar().holidays(datetime.date(2015, 1, 1), datetime.date(2027, 1, 1)).date)
    assert (day in holidays) is closed


def test_the_short_end_and_long_end_have_different_last_trading_days():
    """TU/FV run to the last business day; TY/UXY/US/WN stop seven business days earlier.

    A one-rule-for-all regression would make these equal, and would still pass a spot check on the
    long end alone.
    """
    for year, month in ((2025, 12), (2024, 6), (2018, 9)):
        short = ust_last_trading_day("TU", year, month)
        long = ust_last_trading_day("TY", year, month)
        assert short > long
        assert ust_last_trading_day("FV", year, month) == short
        assert ust_last_trading_day("US", year, month) == long
        assert ust_last_trading_day("WN", year, month) == long
        assert ust_last_trading_day("UXY", year, month) == long


def test_first_position_day_is_shared_by_every_root():
    """The roll is the same date for all roots -- only the last trading day differs by family."""
    assert ust_first_position_day(2025, 9) == datetime.date(2025, 8, 28)
    assert ust_first_position_day(2025, 12) == datetime.date(2025, 11, 26)
    for year, month in ((2025, 9), (2025, 12), (2024, 3)):
        first_bd_minus_2 = ust_first_position_day(year, month)
        assert first_bd_minus_2 < datetime.date(year, month, 1)


@pytest.mark.parametrize("root", ["TU", "FV", "TY", "UXY", "US", "WN"])
def test_the_roll_happens_on_the_first_position_day_and_not_before(root):
    """Boundary, per root: the day before the FPD is still the old contract; the FPD is the new one."""
    fpd = ust_first_position_day(2025, 9)
    day_before = fpd - datetime.timedelta(days=1)
    while day_before.weekday() >= 5:
        day_before -= datetime.timedelta(days=1)

    assert front_month(day_before, root) == f"{root}U25"
    assert front_month(fpd, root) == f"{root}Z25"


def test_the_deliverable_contract_is_a_different_question_from_the_front_month():
    """They disagree between the roll and expiry, which is the whole reason they are separate."""
    mid_roll = datetime.date(2025, 9, 17)  # after TYU25's FPD, before its last trading day
    assert front_month(mid_roll, "TY") == "TYZ25"
    assert ust_deliverable_contract(mid_roll, "TY") == "TYU25"
    # The day after TYU25's last trading day, the deliverable contract rolls too.
    after_ltd = ust_last_trading_day("TY", 2025, 9) + datetime.timedelta(days=1)
    assert ust_deliverable_contract(after_ltd, "TY") == "TYZ25"


def test_back_months_follow_the_same_roll():
    fpd = ust_first_position_day(2025, 9)
    assert back_months(fpd, "TY", 2) == ["TYH26", "TYM26"]
    day_before = fpd - datetime.timedelta(days=1)
    assert back_months(day_before, "TY", 2) == ["TYZ25", "TYH26"]


def test_every_resolution_site_agrees():
    """CROSS-SITE INVARIANT -- the test that would have caught this class of drift.

    Four sites resolved a bare root: `front_month`, `back_months`, `USTFuturesMDP.
    _resolve_contract_symbol` and `treasury_conversion_factors.resolve_delivery_contract`. They now
    share one implementation; this asserts it, over a range that crosses two rolls.
    """
    import pytz

    from MDP.USTFutures.treasury_conversion_factors import resolve_delivery_contract
    from MDP.USTFutures.USTFuturesMDP import USTFuturesMDP

    chi = pytz.timezone("America/Chicago")
    code_for_month = {3: "H", 6: "M", 9: "U", 12: "Z"}

    day = datetime.date(2025, 8, 1)
    checked = 0
    while day <= datetime.date(2025, 12, 31):
        if day.weekday() < 5:
            expected = front_month(day, "TY")
            ts = chi.localize(datetime.datetime(day.year, day.month, day.day, 14, 0))
            assert USTFuturesMDP._resolve_contract_symbol("TY", ts) == expected, day

            _, imm_date, period = resolve_delivery_contract("TY", day)
            assert f"TY{code_for_month[imm_date.month]}{str(imm_date.year)[-2:]}" == expected, day
            checked += 1
        day += datetime.timedelta(days=1)
    assert checked > 100


def test_two_digit_year_keeps_its_leading_zero():
    """`int(strftime('%y'))` dropped it, giving `TYH8` for 2008. Harmless now, wrong pre-2010."""
    assert front_month(datetime.date(2008, 1, 15), "TY") == "TYH08"
