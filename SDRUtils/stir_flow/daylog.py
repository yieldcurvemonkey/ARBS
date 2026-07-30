"""Per-day log capture for the process-pool backfill drivers.

A multi-hour, multi-day backfill fanned across a process pool interleaves every
worker's stdout into one stream, so a single day's warm counts, error histogram
and per-unit failures become unreadable exactly when they matter. Each worker
redirects its own stdout/stderr into ``<log_dir>/<date>.log`` instead, which also
means a crashed or killed run leaves the completed days' diagnostics on disk.
"""
from __future__ import annotations

import contextlib
import os
import sys


@contextlib.contextmanager
def day_log(log_dir, date_iso):
    """Redirect this process's stdout/stderr to ``<log_dir>/<date_iso>.log``.

    A no-op when ``log_dir`` is falsy, so the same worker code serves both the
    interactive single-day path and the fanned-out range path.
    """
    if not log_dir:
        yield None
        return
    os.makedirs(log_dir, exist_ok=True)
    path = os.path.join(log_dir, f"{date_iso}.log")
    # line-buffered so a killed run still leaves a readable tail
    handle = open(path, "w", encoding="utf-8", buffering=1)
    saved_out, saved_err = sys.stdout, sys.stderr
    sys.stdout = sys.stderr = handle
    try:
        yield path
    finally:
        sys.stdout, sys.stderr = saved_out, saved_err
        handle.close()
