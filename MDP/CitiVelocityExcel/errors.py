"""Exception hierarchy for the Citi Velocity Excel bridge.

Every failure mode the design spec records gets its own type, because the caller's
correct response differs per mode: "no Excel" is fixed by opening Excel, "not
signed in" is fixed by signing in, and "Excel died mid-request" must NEVER be
retried into (a retry storm against a dying OLE server is what wedges it for
~15 minutes).

See ``docs/superpowers/specs/2026-08-04-citivelo-excel-timeseries-design.md``.
"""

from __future__ import annotations

from typing import Iterable, Optional

__all__ = [
    "CitiVelocityError",
    "ExcelNotRunningError",
    "AddInNotSignedInError",
    "ExcelDiedError",
    "AsyncTimeoutError",
    "BadTagError",
    "UnknownTagError",
    "CatalogError",
    "FrequencyError",
]


class CitiVelocityError(RuntimeError):
    """Base class for every Citi Velocity bridge failure."""


class ExcelNotRunningError(CitiVelocityError):
    """No running Excel instance exposes a usable Application object.

    The bridge never spawns Excel: a spawned instance loads the XLL but never
    registers the UDFs, because registration is gated on
    ``CustomRibbon.onLoad`` -> portal session resume -> entitlements, and the
    ribbon does not load in an automation instance.
    """

    def __init__(self, detail: str = ""):
        msg = (
            "No running Excel with the Citi Velocity add-in. "
            "Open Excel and sign in to Velocity, then retry. "
            "(The bridge attaches to a human-authenticated Excel; it never spawns one, "
            "because spawned instances never register the CV* UDFs.)"
        )
        super().__init__(f"{msg} {detail}".strip())


class AddInNotSignedInError(CitiVelocityError):
    """Excel is running and reachable but the add-in has not registered its UDFs.

    Surfaces as ``#NAME?`` from the ``=CVTODAY()`` readiness probe. This is
    distinct from :class:`ExcelNotRunningError` and must not be retried in a
    tight loop: after an Excel restart the Velocity login takes ~13 minutes,
    logs nothing in between, and needs Excel idle (it runs through
    ``ExcelAsyncUtil.QueueAsMacro``).
    """

    def __init__(self, detail: str = ""):
        msg = (
            "Excel is running but the Citi Velocity add-in is not signed in "
            "(=CVTODAY() returned #NAME?). Sign in to Velocity in Excel. "
            "After an Excel restart the login takes ~13 minutes and logs nothing "
            "in between - wait at least 15 minutes before concluding it is dead, "
            "and do not poll COM hard while it starts up."
        )
        super().__init__(f"{msg} {detail}".strip())


class ExcelDiedError(CitiVelocityError):
    """A COM error was raised mid-request, i.e. the Excel process went away.

    Raised immediately and never retried: retrying into a dead or dying OLE
    server is what wedges it, and recovery then costs a full add-in re-login.
    """


class AsyncTimeoutError(CitiVelocityError):
    """A ``CV*`` async cell never settled within the poll timeout."""

    def __init__(self, tags: Iterable[str], elapsed: float, formula: Optional[str] = None):
        tag_list = list(tags)
        shown = ", ".join(tag_list[:8]) + (f" (+{len(tag_list) - 8} more)" if len(tag_list) > 8 else "")
        detail = f"\nformula: {formula}" if formula else ""
        super().__init__(
            f"Citi Velocity request did not settle after {elapsed:.1f}s for {len(tag_list)} tag(s): "
            f"{shown}{detail}"
        )
        self.tags = tag_list
        self.elapsed = elapsed


class BadTagError(CitiVelocityError):
    """The add-in reported ``Bad tag: <tag>`` for a requested tag.

    ``CVTSHIST`` degrades per column, so this is raised only when the caller
    asked for strict behaviour; the default is to surface per-tag failures in
    the result rather than lose the whole batch.
    """


class UnknownTagError(CitiVelocityError, ValueError):
    """A tag builder was handed a token that is not in the harvested catalog."""


class CatalogError(CitiVelocityError, ValueError):
    """The harvested catalog cannot answer the question that was asked."""


class FrequencyError(CitiVelocityError, ValueError):
    """An unsupported ``CVTSHIST`` frequency was requested."""
