"""Per-day log capture for the process-pool backfill drivers.

A multi-hour, multi-day backfill fanned across a process pool interleaves every
worker's stdout into one stream, so a single day's warm counts, error histogram and
per-unit failures become unreadable exactly when they matter. Each worker redirects
its own stdout/stderr into ``<log_dir>/<date>.log`` instead, which also means a
crashed or killed run leaves the completed days' diagnostics on disk.

LOGGING HANDLERS MUST BE RE-POINTED, NOT JUST sys.stdout
--------------------------------------------------------
Pool workers are REUSED across days. Simply swapping ``sys.stdout``/``sys.stderr``
and closing the file afterwards produced ``ValueError: I/O operation on closed
file`` on the SECOND day a worker handled: any ``logging.StreamHandler`` created
while the redirect was active captured the file object directly and kept writing to
it after it closed. Observed live in classify-2026-01-23.log during the full-window
backfill. So this context manager also re-points every existing ``StreamHandler``
that is aimed at the streams being replaced, and restores them on exit.

This module is deliberately excluded from ``vintage.VINTAGE_SOURCES``: it only moves
diagnostics around and must never invalidate a running backfill.
"""
from __future__ import annotations

import contextlib
import logging
import os
import sys


def _stream_handlers():
    """Every live StreamHandler, root and named loggers alike."""
    seen = list(logging.root.handlers)
    manager = getattr(logging.Logger, "manager", None)
    for logger in list(getattr(manager, "loggerDict", {}).values()):
        seen.extend(getattr(logger, "handlers", []) or [])
    return [h for h in seen if isinstance(h, logging.StreamHandler)]


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
    # re-point any handler currently aimed at the streams we are replacing
    rebound = [(h, h.stream) for h in _stream_handlers()
               if h.stream in (saved_out, saved_err)]
    sys.stdout = sys.stderr = handle
    for h, _old in rebound:
        h.setStream(handle)
    try:
        yield path
    finally:
        sys.stdout, sys.stderr = saved_out, saved_err
        for h, old in rebound:
            try:
                h.setStream(old)
            except Exception:      # a handler torn down mid-run must not mask the real error
                pass
        # Any handler created WHILE redirected still holds this file, so point it
        # somewhere live before closing rather than leaving it a landmine.
        for h in _stream_handlers():
            if getattr(h, "stream", None) is handle:
                try:
                    h.setStream(saved_err)
                except Exception:
                    pass
        try:
            handle.flush()
        finally:
            handle.close()
