r"""The minute fetch window is anchored on the curve's LOCAL midnight.

The add-in stamps every curve in New York wall-clock and phase 1 buckets what
comes back by curve-local date. Anchoring the window on wire midnight therefore
fetches the wrong 24 hours for anything east of New York: for Tokyo (ET+13h) a
window of ``[d 00:00, d+1 00:00)`` wire lands on ``[d 13:00, d+1 13:00)`` local,
so local day ``d`` gets its afternoon and loses its whole morning.

That is not hypothetical. MEASURED 2026-08-08 against the warmed store,
``JPY-TONAR-1D-LCH`` held **60 minutes instead of 720** on::

    2026-07-10, 07-15, 07-20, 07-30, 08-04     gaps of 5, 5, 10, 5 days

Every gap is a multiple of ``DEFAULT_WINDOW["MI01"]`` = 5 days. The damaged days
were exactly the ones that landed on a fetch-window boundary - which is what
identified the window arithmetic, rather than Citi's data, as the cause. The
other 11 short days surveyed re-fetched to precisely what was already stored.

The tests below assert the two things that were wrong, and a third that must NOT
change: USD and CAD live in the wire zone, so their windows must be untouched.
"""

from __future__ import annotations

import datetime
import importlib.util
import pathlib
import sys
import zoneinfo

import pandas as pd
import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "citivelo_excel_intraday_warm.py"

DAY = datetime.date(2026, 8, 4)
NEXT = datetime.date(2026, 8, 5)


@pytest.fixture(scope="module")
def warm():
    spec = importlib.util.spec_from_file_location("_intraday_warm", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    # Registered BEFORE exec: the script declares @dataclass types, and
    # dataclasses resolves KW_ONLY through sys.modules[cls.__module__], which is
    # None for a module that is mid-exec and unregistered.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def calls(monkeypatch):
    """Record every window asked for, and serve every minute inside it."""
    seen = []

    def _fake(client, tags, freq, start, end, **kwargs):
        seen.append((start, end))
        index = pd.date_range(start, end, freq="1min", inclusive="left")
        series = {
            tag: pd.Series(3.0 + i / 1000.0, index=index, dtype="float64")
            for i, tag in enumerate(tags)
        }
        return series, []

    monkeypatch.setattr("MDP.CitiVelocityExcel.windowed.fetch_windowed", _fake)
    return seen


def _fetch(warm, curve, work_dir, start=DAY, end=NEXT):
    return warm.fetch_curve(
        curve, start, end, work_dir=work_dir, client=object(), freq="MI01"
    )


# ------------------------------------------------------------------ #
#                          the window bounds                         #
# ------------------------------------------------------------------ #


def test_a_tokyo_day_is_requested_as_its_own_midnights_in_wire_time(warm, calls, tmp_path):
    _fetch(warm, "JPY-TONAR-1D-LCH", tmp_path)

    assert len(calls) == 1
    start, end = calls[0]
    tokyo, wire = zoneinfo.ZoneInfo("Asia/Tokyo"), zoneinfo.ZoneInfo("America/New_York")
    expected_start = (
        datetime.datetime.combine(DAY, datetime.time.min, tzinfo=tokyo)
        .astimezone(wire).replace(tzinfo=None)
    )
    assert start == expected_start, (
        "the window must start when the day starts in TOKYO, not when a day with "
        "the same calendar label starts in New York"
    )
    assert end - start == datetime.timedelta(days=1)
    # ET+13h: Tokyo 2026-08-04 00:00 is 2026-08-03 11:00 in New York.
    assert start == datetime.datetime(2026, 8, 3, 11, 0)


def test_a_wire_zone_curve_is_unchanged(warm, calls, tmp_path):
    """USD lives in the wire zone, so the fix must be a no-op for it."""
    _fetch(warm, "USD-SOFR-1D", tmp_path)

    start, end = calls[0]
    assert start == datetime.datetime(2026, 8, 4, 0, 0)
    assert end == datetime.datetime(2026, 8, 5, 0, 0)


# ------------------------------------------------------------------ #
#                          the day that lands                        #
# ------------------------------------------------------------------ #


def _local_stamps(work_dir, curve, day):
    frame = pd.read_parquet(work_dir / curve / f"{day.isoformat()}.parquet")
    return pd.DatetimeIndex(frame["timestamp"]).sort_values()


def test_the_tokyo_day_written_covers_the_whole_local_day(warm, calls, tmp_path):
    """The outcome, not just the request: 1,440 local minutes, 00:00..23:59.

    Under wire-midnight anchoring this file held 13:00..23:59 only - the 660
    minutes that were measured in the store, against a stored 60 that came from
    the neighbouring window's tail and did not overlap them at all.
    """
    _fetch(warm, "JPY-TONAR-1D-LCH", tmp_path)
    stamps = _local_stamps(tmp_path, "JPY-TONAR-1D-LCH", DAY)

    assert stamps[0].strftime("%H:%M") == "00:00"
    assert stamps[-1].strftime("%H:%M") == "23:59"
    assert len(stamps) == 24 * 60
    assert stamps.normalize().unique().tolist() == [pd.Timestamp(DAY)]


def test_every_warmed_currency_gets_a_whole_local_day(warm, calls, tmp_path):
    """The bug was JPY-shaped but the arithmetic is not: EUR and GBP are east too."""
    for curve in ("USD-SOFR-1D", "EUR-ESTR-1D", "GBP-SONIA-1D",
                  "JPY-TONAR-1D-LCH", "CAD-CORRA-1D"):
        stamps = None
        _fetch(warm, curve, tmp_path / curve)
        stamps = _local_stamps(tmp_path / curve, curve, DAY)
        assert len(stamps) == 24 * 60, f"{curve} did not get a whole local day"
        assert stamps[0].strftime("%H:%M") == "00:00", curve
        assert stamps[-1].strftime("%H:%M") == "23:59", curve


def test_the_resume_skip_names_the_same_days_the_files_are_named_after(warm, calls, tmp_path):
    """A second run must fetch nothing - the skip check and the filenames agree.

    Walking wire datetimes made those two disagree for an eastern curve, so the
    resume check could clear a window whose local days it had not actually filled.
    """
    _fetch(warm, "JPY-TONAR-1D-LCH", tmp_path)
    first = len(calls)
    assert first == 1

    days, windows = _fetch(warm, "JPY-TONAR-1D-LCH", tmp_path)
    assert len(calls) == first, "a fully fetched day was requested again"
    assert (days, windows) == (0, 0)
