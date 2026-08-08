r"""Decide whether it is safe to open Excel, WITHOUT opening Excel.

The Citi Velocity add-in's memory only ever grows, and only a human restart
clears it. A 528-window fetch left the process at **5,249 MB** on 2026-08-07 and
wedged it - unresponsive to a 15 s window ping, no modal dialog, no cell-edit
mode, and it did not recover when the COM client was released. On 2026-08-08 the
same process was measured climbing through **7,639 MB** and then **13,884 MB**
with nothing in this repo connected to it.

So any unattended job that might touch Excel has to check first. The check has
exactly one hard requirement, and it is easy to get wrong:

    **The probe must not itself connect.**

``CitiVelocityExcelClient.excel_memory_mb`` is a method on a *connected* client,
so reading it means doing the thing the guard exists to prevent - the guard runs
after the damage. This module asks Windows instead, over ``Get-Process``, with no
COM anywhere near it.

The second thing to get right is that **"no Excel" and "could not tell" are
different facts with opposite correct actions.** A machine with no ``EXCEL.EXE``
is the safest state there is and should proceed. A probe that timed out, could
not find PowerShell, or was refused by execution policy says *nothing at all*
about what is running - and what might be running is a 13 GB add-in. Collapsing
both to ``None`` is what makes a gate fail open, so :func:`excel_memory_mb`
returns ``0.0`` for the first and ``None`` only for the second.
"""

from __future__ import annotations

import subprocess
from typing import Optional

__all__ = [
    "DEFAULT_CEILING_MB",
    "ExcelTooLargeError",
    "assert_safe_to_connect",
    "excel_memory_mb",
    "is_safe_to_connect",
]

#: Stop here. Comfortably below the 5,249 MB that wedged the add-in, leaving room
#: for the run itself to grow.
DEFAULT_CEILING_MB = 3800.0

_PROBE = (
    "$s = (Get-Process EXCEL -ErrorAction SilentlyContinue | "
    "Measure-Object WorkingSet64 -Sum).Sum; "
    "if ($null -eq $s) { 'NONE' } else { $s }"
)


class ExcelTooLargeError(RuntimeError):
    """Excel is above the ceiling, or its size could not be established."""


def excel_memory_mb(*, timeout: float = 60.0) -> Optional[float]:
    """Total ``EXCEL.EXE`` working set in MB.

    Returns
    -------
    float
        The size, or ``0.0`` when no ``EXCEL.EXE`` is running.
    None
        The probe FAILED - it timed out, PowerShell was unavailable, or the
        output could not be parsed. Distinct from ``0.0`` on purpose: see the
        module docstring. Callers must treat ``None`` as "do not proceed".

    Notes
    -----
    Sums across processes rather than taking the largest, because two workbooks
    in one session is a normal state and the ceiling is about the machine.
    Megabytes are decimal (``/1e6``), matching
    ``CitiVelocityExcelClient.excel_memory_mb`` so the two numbers are comparable.
    """
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", _PROBE],
            capture_output=True, text=True, timeout=timeout,
        )
    except Exception:  # noqa: BLE001 - an unreadable probe must not look like "fine"
        return None
    if getattr(out, "returncode", 1) != 0:
        return None
    raw = (out.stdout or "").strip()
    if raw == "NONE":
        return 0.0
    try:
        return float(raw) / 1e6
    except (TypeError, ValueError):
        return None


def is_safe_to_connect(limit_mb: float = DEFAULT_CEILING_MB) -> bool:
    """Whether Excel is small enough to connect to. Fails CLOSED."""
    mb = excel_memory_mb()
    return mb is not None and mb < limit_mb


def assert_safe_to_connect(
    limit_mb: float = DEFAULT_CEILING_MB, *, what: str = "this job"
) -> float:
    """Return Excel's size, or raise before anything connects.

    Call this **before** constructing a ``CitiVeloQuotes`` or touching
    ``client()`` - not after. A guard placed after the connection has already
    done the thing it was meant to prevent.

    Raises
    ------
    ExcelTooLargeError
        Above ``limit_mb``, or the probe could not be read at all. The message
        says which, and what to do about it, because the fix differs: one needs a
        human to restart Excel, the other needs the probe repaired.
    """
    mb = excel_memory_mb()
    if mb is None:
        raise ExcelTooLargeError(
            f"Refusing to start {what}: could not read Excel's memory (the probe timed "
            f"out, PowerShell was unavailable, or its output was unparseable). A probe "
            f"that did not complete says nothing about what is running, and connecting "
            f"into a wedged add-in is only cleared by a human restart. Check by hand "
            f"with `Get-Process EXCEL` and re-run."
        )
    if mb >= limit_mb:
        raise ExcelTooLargeError(
            f"Refusing to start {what}: Excel is at {mb:.0f} MB, at or above the "
            f"{limit_mb:.0f} MB ceiling. The add-in's memory only ever grows and only a "
            f"HUMAN restart clears it - it wedged at 5,249 MB on 2026-08-07. Restart "
            f"Excel, sign in to Velocity, and re-run."
        )
    return mb
