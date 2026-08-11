r"""A fetched day counts as done when it is COMPLETE, not when it exists.

The defect this closes made ~16 % of fetched days permanent: they stop at
**23:59 UTC** - 19:59 ET on daylight time, 18:59 on standard - instead of the
session end, and both the planner (``plan_curve``) and the fetcher
(``fetch_curve``) treated the presence of a day file as proof it was done. No
later run ever asked for the rest.

Two facts make the repair worth doing, and both are measurements rather than
arguments:

* the partial is **transient**, not a market close - ``2026-08-03`` came back
  complete at 1,320 minutes in one run and truncated at 1,140 in another;
* which also means a re-fetch can be **worse** than what is on disk, so the
  write rule has to keep the better of the two rather than "first wins" (which
  froze the truncations) or "--force wins" (which would discard good data).
"""

from __future__ import annotations

import datetime
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import citivelo_excel_intraday_warm as warm  # noqa: E402

CURVE = "USD-FEDFUNDS-1D"
DENSE_FROM = datetime.date(2018, 9, 1)


def _write(dirpath: Path, day: datetime.date, n_rows: int) -> Path:
    """A day file with ``n_rows`` minutes, shaped like the fetcher's own."""
    dirpath.mkdir(parents=True, exist_ok=True)
    start = pd.Timestamp(f"{day} 01:00")
    frame = pd.DataFrame(
        {
            "timestamp": pd.date_range(start, periods=n_rows, freq="1min"),
            "1D": [4.3] * n_rows,
        }
    )
    out = dirpath / f"{day.isoformat()}.parquet"
    frame.to_parquet(out, index=False)
    return out


# --------------------------------------------------------------------------- #
#                       what counts as a complete day                         #
# --------------------------------------------------------------------------- #


def test_a_full_weekday_is_complete(tmp_path):
    _write(tmp_path, datetime.date(2026, 6, 17), 1320)
    assert warm._day_file_is_complete(CURVE, datetime.date(2026, 6, 17), tmp_path) is True


def test_the_23_59_utc_truncation_is_not_complete(tmp_path):
    """1,140 of 1,320 - the exact shape the fetch leaves behind."""
    _write(tmp_path, datetime.date(2026, 6, 17), 1140)
    assert warm._day_file_is_complete(CURVE, datetime.date(2026, 6, 17), tmp_path) is False


def test_a_genuinely_short_friday_is_complete(tmp_path):
    """The failure in the other direction, and the more expensive one.

    Friday really does close at 21:59 UTC. A rule that called it incomplete
    would re-fetch 52 days a year forever, and burn the Excel session doing it.
    """
    _write(tmp_path, datetime.date(2026, 6, 19), 1020)
    assert warm._day_file_is_complete(CURVE, datetime.date(2026, 6, 19), tmp_path) is True


def test_a_sunday_evening_is_complete(tmp_path):
    _write(tmp_path, datetime.date(2026, 6, 21), 360)
    assert warm._day_file_is_complete(CURVE, datetime.date(2026, 6, 21), tmp_path) is True


def test_a_pre_2022_day_is_judged_against_the_24_hour_session(tmp_path):
    """The era matters: 1,320 minutes is a FULL day now and a SHORT one in 2021.

    Judging 2021 by the narrowed session would report a day missing two hours as
    complete - the direction that hides work.
    """
    day = datetime.date(2021, 11, 3)
    _write(tmp_path, day, 1320)
    assert warm._day_file_is_complete(CURVE, day, tmp_path) is False
    _write(tmp_path, day, 1439)
    assert warm._day_file_is_complete(CURVE, day, tmp_path) is True


def test_an_absent_day_is_not_complete(tmp_path):
    assert warm._day_file_is_complete(CURVE, datetime.date(2026, 6, 17), tmp_path) is False


def test_an_unmodelled_curve_keeps_the_old_presence_behaviour(tmp_path):
    """The eighteen non-USD curves must not change behaviour at all.

    Their session was never measured, so a completeness rule would be a guess -
    and a guess here means re-fetching years of already-good data.
    """
    _write(tmp_path, datetime.date(2026, 6, 17), 5)
    assert warm._day_file_is_complete("GBP-SONIA-1D", datetime.date(2026, 6, 17), tmp_path) is True


def test_a_date_before_the_measured_range_keeps_presence_behaviour(tmp_path):
    day = datetime.date(2016, 6, 15)
    _write(tmp_path, day, 5)
    assert warm._day_file_is_complete(CURVE, day, tmp_path) is True


# --------------------------------------------------------------------------- #
#                     the write rule keeps the better day                     #
# --------------------------------------------------------------------------- #


def test_row_count_reads_the_footer_and_handles_absence(tmp_path):
    assert warm._parquet_row_count(tmp_path / "nope.parquet") is None
    p = _write(tmp_path, datetime.date(2026, 6, 17), 42)
    assert warm._parquet_row_count(p) == 42


def test_a_corrupt_day_file_reads_as_absent(tmp_path):
    bad = tmp_path / "2026-06-17.parquet"
    bad.write_bytes(b"not a parquet")
    assert warm._parquet_row_count(bad) is None
    assert warm._day_file_is_complete(CURVE, datetime.date(2026, 6, 17), tmp_path) is False


def test_the_planner_and_the_fetcher_agree_on_completeness(tmp_path):
    """Two gates, one definition - they disagreed before, which is the bug.

    ``plan_curve`` decided which chunks to fetch and ``fetch_curve`` decided
    which windows inside them to skip. Fixing only the first would produce
    chunks that the second then skipped.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import citivelo_deep_intraday_warm as deep

    day = datetime.date(2026, 6, 17)
    for n, expected in ((1320, True), (1140, False)):
        _write(tmp_path, day, n)
        assert warm._day_file_is_complete(CURVE, day, tmp_path) is expected
        assert deep._count_is_complete(CURVE, day, n, dense_from=DENSE_FROM) is expected
