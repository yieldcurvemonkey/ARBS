r"""One retried ``os.replace``, shared by every temp-then-rename on the warm path.

The fault was measured in the Velocity tag cache - a second handle on
``RATES.BOND.US912810QU51.ROLLCARRY.6M.meta.json`` cost the 2026-08-12 nightly
warm 829 of 877 bonds - but it is not a Velocity fault. CPython's ``open()`` does
not pass ``FILE_SHARE_DELETE``, so on Windows ANY concurrent reader of the target
makes ``os.replace`` raise ``PermissionError [WinError 5] Access is denied``,
with no antivirus and no second process involved. Five other writes on the same
nightly path were bare:

``Caching/curve_store``, ``Caching/swaption_cube_store``,
``Caching/timeseries_cache``, ``scripts/citivelo_excel_intraday_warm``,
``scripts/citivelo_curve_service``.

They now share ``utils.atomic_replace.replace_with_retry`` rather than carrying
five copies of a bounded retry whose entire value is that its budget is measured.

The contract has two sides and needs both, because each alone is satisfiable by a
broken implementation: a budget of zero fails the transient case, and a swallow
or an unbounded retry fails the permanent one.

Windows-only where the fault is Windows-only: POSIX ``rename`` over an open file
succeeds by design, so there is nothing to ride out there.
"""

from __future__ import annotations

import contextlib
import pathlib
import sys
import threading
import time
from typing import Iterator, Optional

import pandas as pd
import pytest

from utils.atomic_replace import REPLACE_BUDGET_S, replace_with_retry

_WINDOWS = sys.platform == "win32"

#: How long the TRANSIENT holder keeps the target open. Must be under the budget
#: or the transient case is indistinguishable from the permanent one.
_TRANSIENT_HOLD = 0.3


@contextlib.contextmanager
def _held_open(path: pathlib.Path, *, release_after: Optional[float]) -> Iterator[None]:
    """Hold ``path`` open the way a concurrent reader does, and let go or not."""
    handle = open(path, "r", encoding="utf-8")  # noqa: SIM115 - held on purpose
    timer = None
    if release_after is not None:
        timer = threading.Timer(release_after, handle.close)
        timer.daemon = True
        timer.start()
    try:
        yield
    finally:
        if timer is not None:
            timer.cancel()
        with contextlib.suppress(Exception):
            handle.close()


def _pair(tmp_path: pathlib.Path):
    dst = tmp_path / "target.txt"
    dst.write_text("old", encoding="utf-8")
    tmp = tmp_path / "target.txt.tmp"
    tmp.write_text("new", encoding="utf-8")
    return tmp, dst


def test_the_budget_is_longer_than_a_transient_holder():
    """The two tests below are only different stimuli if this holds."""
    assert REPLACE_BUDGET_S > _TRANSIENT_HOLD


@pytest.mark.skipif(not _WINDOWS, reason="POSIX rename over an open file succeeds by design")
def test_a_transient_holder_is_ridden_out(tmp_path):
    """Defender, the Search indexer, a second warm - all let go in milliseconds."""
    tmp, dst = _pair(tmp_path)
    with _held_open(dst, release_after=_TRANSIENT_HOLD):
        replace_with_retry(tmp, dst)
    assert dst.read_text(encoding="utf-8") == "new"
    assert not tmp.exists()


@pytest.mark.skipif(not _WINDOWS, reason="POSIX rename over an open file succeeds by design")
def test_a_permanent_holder_still_raises_and_unlinks_the_temporary(tmp_path):
    """A retry that becomes a swallow is the persists-nothing fault, one layer down.

    And the temporary must go with it: a ``.tmp`` sharing a stem with a real
    cache entry is a partial file every later reader has to know to ignore.
    """
    tmp, dst = _pair(tmp_path)
    with _held_open(dst, release_after=None):
        with pytest.raises(PermissionError):
            replace_with_retry(tmp, dst, budget_s=0.05)
    assert not tmp.exists(), "the failed replace left its temporary behind"
    assert dst.read_text(encoding="utf-8") == "old", "the target was damaged"


def test_a_non_permission_oserror_is_not_retried(tmp_path):
    """``ENOSPC`` and a vanished parent are not fixed by waiting.

    A broader ``except OSError`` would sit here burning the whole budget and then
    report them late and identically, which is a worse diagnosis than an
    immediate one. Asserting only the exception TYPE does not catch that - a
    widened clause re-raises the same ``FileNotFoundError``, five seconds later -
    so this pins the two observable consequences of a retry instead: the time,
    and the temporary, which only the timeout path removes.
    """
    missing = tmp_path / "gone" / "target.txt"
    tmp, _ = _pair(tmp_path)
    started = time.monotonic()
    with pytest.raises(OSError) as excinfo:
        replace_with_retry(tmp, missing, budget_s=5.0)
    elapsed = time.monotonic() - started

    assert not isinstance(excinfo.value, PermissionError)
    assert elapsed < 1.0, (
        f"a vanished parent directory was retried for {elapsed:.1f}s of a 5.0s "
        "budget; waiting does not create a directory"
    )
    assert tmp.exists(), (
        "the temporary was removed, which only the exhausted-budget path does - "
        "so this error went round the retry loop"
    )


# --------------------------------------------------------------------------
# the call sites actually use it
#
# The five sites are not equally exposed, and saying so is part of the record.
# ``curve_store``, ``swaption_cube_store`` and ``timeseries_cache`` are
# CONTENT-ADDRESSED - the target's name is the sha256 of its own bytes, and each
# one skips the write when that file already exists - so their replace lands on a
# target that is usually absent. They are wired to the shared helper for
# consistency and because "usually absent" is not "absent", but the reachable
# fault is at the two per-DAY writes below, whose target is a fixed
# ``<date>.parquet`` that a re-run overwrites while a reader may hold it.
# --------------------------------------------------------------------------


def _intraday_warm():
    """Import the intraday warm script by path. It is not in a package."""
    import importlib.util

    name = "_citivelo_excel_intraday_warm_under_test"
    if name in sys.modules:
        return sys.modules[name]
    path = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "citivelo_excel_intraday_warm.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.skipif(not _WINDOWS, reason="POSIX rename over an open file succeeds by design")
def test_the_intraday_day_parquet_survives_a_held_open_target(tmp_path):
    """``citivelo_excel_intraday_warm._write_day_parquet`` was a bare ``os.replace``.

    Its target is ``<date>.parquet`` - a fixed name a re-run overwrites - so a
    reader holding yesterday's file (the ``status`` step globs and reads exactly
    these) is enough to raise WinError 5 and lose the day. This is the same fault
    as the tag cache's, at a site nothing guarded.
    """
    warm = _intraday_warm()
    frame = pd.DataFrame(
        {"10Y": [1.0, 2.0]},
        index=pd.DatetimeIndex(["2026-08-18 09:30", "2026-08-18 09:31"]),
    )
    out = tmp_path / "2026-08-18.parquet"
    warm._write_day_parquet(out, frame)
    assert out.is_file()

    with _held_open(out, release_after=_TRANSIENT_HOLD):
        warm._write_day_parquet(out, frame)

    assert list(tmp_path.rglob("*.tmp")) == [], "the retried replace leaked its temporary"


@pytest.mark.skipif(not _WINDOWS, reason="POSIX rename over an open file succeeds by design")
def test_the_computed_timeseries_write_survives_a_held_open_partition(tmp_path):
    r"""``Caching/timeseries_cache._atomic_write_bytes`` was a bare ``os.replace``.

    Exercised through the call site rather than only through the helper because
    of what it passes: ``\\?\``-prefixed extended-length STRINGS. A wiring that
    rebuilt those as ``Path`` would drop the prefix that makes a long partition
    path work at all, and nothing else here would notice.
    """
    from Caching.timeseries_cache import _atomic_write_bytes

    dst = tmp_path / "part.parquet"
    _atomic_write_bytes(dst, b"first")
    with _held_open(dst, release_after=_TRANSIENT_HOLD):
        _atomic_write_bytes(dst, b"second")

    assert dst.read_bytes() == b"second"
    assert list(tmp_path.rglob("*.tmp")) == []
