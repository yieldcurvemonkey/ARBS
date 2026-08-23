"""The nightly must warm a day whose rows its writers will actually keep.

Both computed-timeseries routers drop rows stamped today on purpose, and the
warmer defaulted to ``start = end = today``. Between them the weekday warm
computed its values and threw every one away - visible only in partition mtimes,
never in the run log, which said ``OK (1 rows x 28 cols)`` each night. These
tests pin the window arithmetic that fixes it, and the per-job declaration that
decides who gets it.

Everything here is pure date arithmetic against a stubbed ``today``. Nothing
imports a market-data provider, opens Excel or touches a store: the module under
test is loaded by path, exactly as ``tests/test_daily_cache_warmer_citivelo.py``
loads it, so importing it cannot pull the warmer's job bodies into the suite.
"""

import datetime
import importlib.util
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_warmer():
    """The warmer module, by path.

    By path rather than by name because ``scripts`` is not a package on the test
    path and because the module chdirs to the repo root at import; loading it
    once per session keeps that to a single side effect.
    """
    spec = importlib.util.spec_from_file_location(
        "daily_cache_warmer_under_test",
        os.path.join(REPO_ROOT, "scripts", "daily_cache_warmer.py"),
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def warmer():
    return _load_warmer()


class _FrozenDate(datetime.date):
    """``datetime.date`` whose ``today()`` is whatever the test says it is."""

    _today = datetime.date(2026, 8, 24)

    @classmethod
    def today(cls):
        return cls._today


@pytest.fixture
def frozen_today(monkeypatch, warmer):
    def _set(day):
        _FrozenDate._today = day
        monkeypatch.setattr(warmer.datetime, "date", _FrozenDate)
        return day

    return _set


# ── the calendar ─────────────────────────────────────────────────────

def test_settled_session_is_the_previous_business_day(warmer, frozen_today):
    frozen_today(datetime.date(2026, 8, 20))  # a Thursday
    assert warmer._last_settled_session() == datetime.date(2026, 8, 19)


def test_settled_session_reaches_back_over_a_weekend(warmer, frozen_today):
    frozen_today(datetime.date(2026, 8, 24))  # a Monday
    assert warmer._last_settled_session() == datetime.date(2026, 8, 21)


def test_settled_session_skips_a_bond_market_holiday(warmer, frozen_today):
    # 2026-07-03 is the observed Independence Day holiday (the 4th is a
    # Saturday), so the session before Monday 2026-07-06 is Thursday 07-02.
    # pd.bdate_range alone would answer 07-03 and then find nothing there --
    # the failure this repo has recorded as "a 5% failure rate that is really a
    # calendar".
    frozen_today(datetime.date(2026, 7, 6))
    assert warmer._last_settled_session() == datetime.date(2026, 7, 2)


def test_settled_session_skips_good_friday(warmer, frozen_today):
    # QuantLib's GovernmentBond calendar calls Good Friday a business day while
    # the bond market closes and every vendor here serves nothing -- measured
    # independently from GS and from twelve scraped iShares ETFs on 2026-04-03.
    frozen_today(datetime.date(2026, 4, 6))  # the Monday after
    assert warmer._is_good_friday(datetime.date(2026, 4, 3))
    assert warmer._last_settled_session() == datetime.date(2026, 4, 2)


@pytest.mark.parametrize(
    "year,easter",
    [
        (2023, datetime.date(2023, 4, 9)),
        (2024, datetime.date(2024, 3, 31)),
        (2025, datetime.date(2025, 4, 20)),
        (2026, datetime.date(2026, 4, 5)),
        (2027, datetime.date(2027, 3, 28)),
    ],
)
def test_easter_sunday_is_right(warmer, year, easter):
    assert warmer._easter_sunday(year) == easter


# ── the window each job gets ─────────────────────────────────────────

def _job(warmer, *, banks_today):
    from utils.warm_jobs import WarmJob

    return WarmJob("probe", lambda s, e: None, banks_today=banks_today)


def test_a_job_that_banks_today_gets_exactly_what_was_asked(warmer, frozen_today):
    today = frozen_today(datetime.date(2026, 8, 20))
    job = _job(warmer, banks_today=True)
    assert warmer._window_for(job, today, today) == (today, today)


def test_a_job_that_does_not_bank_today_is_moved_back(warmer, frozen_today):
    today = frozen_today(datetime.date(2026, 8, 20))
    job = _job(warmer, banks_today=False)
    settled = datetime.date(2026, 8, 19)
    assert warmer._window_for(job, today, today) == (settled, settled)


def test_a_backfill_keeps_its_start_and_only_loses_today(warmer, frozen_today):
    today = frozen_today(datetime.date(2026, 8, 22))  # the Saturday task
    start = today - datetime.timedelta(days=7)
    job = _job(warmer, banks_today=False)
    got_start, got_end = warmer._window_for(job, start, today)
    assert got_start == start, "a --backfill 7 must still cover the whole week"
    assert got_end == datetime.date(2026, 8, 21)


def test_an_explicitly_historical_range_is_untouched(warmer, frozen_today):
    frozen_today(datetime.date(2026, 8, 20))
    old = datetime.date(2026, 8, 10)
    for banks in (True, False):
        assert warmer._window_for(_job(warmer, banks_today=banks), old, old) == (old, old)


def test_start_is_clamped_when_it_would_pass_the_end(warmer, frozen_today):
    # --date <today> on a settled-only job: start must not end up after end.
    today = frozen_today(datetime.date(2026, 8, 20))
    got_start, got_end = warmer._window_for(_job(warmer, banks_today=False), today, today)
    assert got_start <= got_end


# ── the registry ─────────────────────────────────────────────────────

#: Jobs that own a date-keyed store of their own, have no today-guard, and whose
#: output is the only record of a session that is already closed at 18:15.
_MUST_BANK_TODAY = {
    "SR3 EOD settles (depth 20)",
    "STIRF CME Session",
    "UST Futures Invoice Caches",
    "STIRFO SFR Options EOD",
}

#: Value jobs that write through a computed-timeseries router (which drops
#: today) or read a store that is not built for today yet.
_MUST_NOT_BANK_TODAY = {
    "GSQUANT USD SOFR+OIS EOD (LCH+CME, 30y+STIR)",
    "ERIS USD-SOFR-1D EOD",
    "FRB FedInvest EOD",
    "CitiVelo EOD timeseries",
    "CitiVelo swaption values EOD",
    "CitiVelo intraday timeseries",
    "CITIVELO FRB values EOD",
    "CITIVELO UST timeseries values EOD",
    "CITIVELO swap spreads EOD",
    "CITIVELO swap spreads INTRADAY",
    "CITIVELO UST timeseries values INTRADAY",
}


def test_every_job_is_classified_and_none_drifted(warmer):
    from utils.warm_jobs import STORE

    by_name = {j.name: j for j in warmer.WARM_JOBS}
    unknown = (_MUST_BANK_TODAY | _MUST_NOT_BANK_TODAY) - set(by_name)
    assert not unknown, f"these names are no longer in the registry: {sorted(unknown)}"

    for name in _MUST_BANK_TODAY:
        assert by_name[name].banks_today, (
            f"{name!r} owns a date-keyed store and must keep warming today"
        )
    for name in _MUST_NOT_BANK_TODAY:
        assert not by_name[name].banks_today, (
            f"{name!r} writes through a router that drops today's rows, so warming "
            "today computes numbers nothing keeps"
        )

    # A store warm banks vendor data that cannot be re-fetched later; it must
    # never be moved off today.
    for job in warmer.WARM_JOBS:
        if job.kind == STORE:
            assert job.banks_today, f"{job.name!r} is a store warm and must warm today"

    # And nothing may be left unclassified: a new value job that quietly takes
    # the default is the exact regression this file exists to catch.
    value_names = {j.name for j in warmer.WARM_JOBS if j.kind != STORE}
    assert value_names == (_MUST_BANK_TODAY | _MUST_NOT_BANK_TODAY), (
        "a value job was added or renamed without deciding whether it banks today"
    )


# ── the deadline ─────────────────────────────────────────────────────

def test_watchdog_cancels_cleanly_and_does_not_fire(warmer):
    cancel = warmer._arm_job_watchdog("probe", [], 3600.0)
    cancel()  # must not raise, and must not have fired


def test_watchdog_is_a_no_op_when_disabled(warmer):
    assert warmer._arm_job_watchdog("probe", [], 0.0)() is None


def test_stirf_keeps_a_budget_above_its_own(warmer):
    # The run-level deadline must not become the thing that kills a job that is
    # legitimately inside its own budget.
    assert (
        warmer._JOB_DEADLINE_OVERRIDES["STIRF CME Session"]
        > warmer._STIRF_TOTAL_BUDGET_S
    )


# ── the L2 switch ────────────────────────────────────────────────────

def test_supabase_l2_is_off_by_the_time_caching_can_be_imported(warmer):
    # The flag is read once, at import of Caching.supabase_engine, into a module
    # global -- so setting it later is inert. The warmer sets it above its own
    # imports; this proves the value is in place for anything the jobs import.
    assert os.environ.get("ARBS_SUPABASE_ENABLED") == "0"

    from Caching.supabase_engine import SUPABASE_ENABLED

    assert SUPABASE_ENABLED is False, (
        "the nightly would open connections to the production pooler whose "
        "credentials are hard-coded module defaults"
    )
