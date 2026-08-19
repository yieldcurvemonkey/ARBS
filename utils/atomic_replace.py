r"""``os.replace``, retried while Windows says the target is busy.

Lifted out of ``MDP/CitiVelocityExcel/cache.py``, which is where the fault was
measured, because the fault is not a Velocity fault. It is a property of Windows
and of CPython's ``open()``, and every temp-then-rename write in this repo sits
on it. The Velocity tag cache was simply the first one to be run 877 times a
night with a second reader in the way.

Sites that share it, all on the nightly warm's hot path and all previously bare:

======================================  ==================================
``MDP/CitiVelocityExcel/cache.py``      the parquet, the sidecar, the
                                        history-start rewrite
``Caching/curve_store.py``              the content-addressed curve partition
``Caching/swaption_cube_store.py``      the cube partition, same shape
``Caching/timeseries_cache.py``         the computed timeseries partition
``scripts/citivelo_excel_intraday_warm``the per-day intraday parquet
``scripts/citivelo_curve_service.py``   the extracted per-day parquet
======================================  ==================================

A second copy of a bounded retry whose whole value is that its budget is
measured is how the two drift apart, which is the same argument that moved the
window loop into ``windowed.warm_windows``.

This module deliberately imports nothing but the standard library, so a caller
in ``Caching`` does not drag the Velocity COM bridge in behind it.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Union

__all__ = [
    "REPLACE_BUDGET_S",
    "replace_with_retry",
]

_logger = logging.getLogger(__name__)

#: How long :func:`replace_with_retry` keeps trying before it gives up.
#:
#: Sized against the fault, not guessed. The holders that cause this are
#: short-lived by nature - Defender opening a just-written file, the Search
#: indexer, a second warm reading the sidecar it is about to overwrite - and they
#: let go in tens of milliseconds. A second and a half is comfortably past that
#: and still bounded.
#:
#: Bounded PER FILE, not per run, and the difference matters for the budget
#: arithmetic: the 877-bond EOD warm writes ~6.6 tags per bond across two files
#: each, so a run in which EVERY write paid the full budget would be hours, not
#: the 22 minutes a one-write-per-bond count suggests. That is not an argument
#: for a smaller budget - a write that has been contended for 1.5 s is a write
#: that is not coming back - it is an argument against growing this number
#: without a measurement, because the multiplier is ~13x per bond.
REPLACE_BUDGET_S = 1.5

#: First backoff, then doubling to :data:`_REPLACE_MAX_SLEEP_S`. Starts small
#: because the common case clears almost immediately and a coarse first sleep
#: would turn a 20 ms stall into a 200 ms one on every contended write.
_REPLACE_FIRST_SLEEP_S = 0.02
_REPLACE_MAX_SLEEP_S = 0.2

PathLike = Union[str, "os.PathLike[str]"]


def replace_with_retry(
    tmp: PathLike, dst: PathLike, *, budget_s: float = REPLACE_BUDGET_S
) -> None:
    r"""``os.replace(tmp, dst)``, retried while Windows says the target is busy.

    ``os.replace`` is already the right call and always was: it overwrites
    atomically, so "the target exists" - the classic ``os.rename`` trap - is not
    a failure mode here. The failure mode on Windows is that the target is
    **open**. CPython's ``open()`` does not pass ``FILE_SHARE_DELETE``, so any
    concurrent reader of the sidecar makes the replace raise
    ``PermissionError [WinError 5] Access is denied`` - with no antivirus and no
    second process required. It is reproducible from a plain read-only
    ``open()`` of the target in the same interpreter.

    It cost the 2026-08-12 nightly warm 829 of 877 bonds. The exception escaped
    ``write`` -> ``CitiVeloTagCache.get`` -> ``CitiVeloQuotes.frame`` into the
    per-batch handler in ``scripts/citivelo_ust_universe_warm.py``, which stops
    the run - so one unlucky handle on
    ``RATES.BOND.US912810QU51.ROLLCARRY.6M.meta.json`` ended the whole universe
    warm at bond 48.

    **This is a retry, not a swallow, and the distinction is the whole point.**
    A transient holder is ridden out; a target that is permanently unavailable -
    read-only, a wedged process, a permission that will never be granted - still
    raises, because a cache write that fails silently is the
    persists-nothing-and-reports-success fault that the warm's own guard exists
    to catch, reintroduced one layer down where nothing is watching for it.

    Only ``PermissionError`` is retried. A broader ``except OSError`` would sit
    here for a second and a half burning the budget on ``ENOSPC`` or a vanished
    parent directory, neither of which time fixes, and would report them late
    and identically.

    On the final failure the temporary is removed. A ``.parquet.tmp`` left in the
    tree is not inert: it is a partial file sharing a stem with a real cache
    entry, and the next reader to glob the directory has to know to ignore it.

    Accepts ``str`` as well as ``Path`` on purpose - ``Caching/timeseries_cache``
    passes ``\\?\``-prefixed extended-length strings, and rebuilding those as
    ``Path`` objects would drop the prefix that makes long paths work at all.
    """
    deadline = time.monotonic() + budget_s
    sleep_s = _REPLACE_FIRST_SLEEP_S
    while True:
        try:
            os.replace(tmp, dst)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                # Best effort, and deliberately silent: the original
                # PermissionError is the one the operator needs, and an unlink
                # that also fails must not replace it with a less informative one.
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                _logger.warning(
                    "could not replace %s after %.1fs of retries - something is "
                    "holding it open; the write was NOT persisted",
                    dst, budget_s,
                )
                raise
            time.sleep(sleep_s)
            sleep_s = min(sleep_s * 2, _REPLACE_MAX_SLEEP_S)
