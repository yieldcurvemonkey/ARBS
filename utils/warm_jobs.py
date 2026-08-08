r"""Declared ordering for cache-warming jobs, so a warm cannot silently invert.

The daily warmer runs its jobs in list order, unattended, from a scheduled task.
That is fine until one job *reads* what another job *writes*, at which point list
order stops being cosmetic and becomes a correctness constraint - and an
invisible one, because getting it wrong does not raise.

The failure it produces
-----------------------
A value job asks for a date the store has not been warmed for. The store misses,
and the source falls through to its live path - for the Velocity sources, that
means opening Excel. On a desktop with a signed-in session and a human present,
that looks like a slow job. On a scheduled task at 04:00 it means either a
long stall against an add-in nobody is watching, or - since the add-in's memory
only ever grows and only a human restart clears it - a warm that wedges Excel for
whoever sits down next. The recorded wedge was 5,249 MB.

Reordering two lines in a list is a one-character-looking change that causes
this, and no test catches it unless the dependency is *declared*. So it is
declared: each job names the store assets it ``provides`` and the ones it
``requires``, and :func:`assert_ordered` refuses an ordering where a requirement
is satisfied later than its consumer.

Why assets rather than job names
--------------------------------
Store assets are the real unit of dependency, and they are already the unit that
matters for a different reason: ``write_day`` replaces a whole day partition, so
two producers sharing an asset key means one silently deletes the other's data.
Naming assets here makes both hazards visible in the same place -
:func:`assert_unique_providers` catches the second one.
"""

from __future__ import annotations

import dataclasses
from typing import Callable, Dict, Iterable, List, Sequence, Tuple

__all__ = [
    "STORE",
    "VALUE",
    "WarmJob",
    "WarmOrderError",
    "assert_ordered",
    "assert_unique_providers",
    "check",
    "describe",
]

#: A job that WRITES a store partition. Must precede anything that reads it.
STORE = "store"
#: A job that READS stores and writes computed timeseries.
VALUE = "value"


class WarmOrderError(RuntimeError):
    """A job ordering that would let a value job run before its store warm."""


@dataclasses.dataclass(frozen=True)
class WarmJob:
    """One entry in the warmer's job list.

    Attributes
    ----------
    name
        Human label, shown by ``--list`` and in the run summary.
    fn
        ``fn(start, end)``, the existing warmer job signature.
    kind
        :data:`STORE` or :data:`VALUE`.
    provides
        Store asset keys this job writes, e.g. ``("USD-SOFR-1D-CITIVELO",)``.
        Empty for a value job.
    requires
        Store asset keys this job reads. A value job that reads nothing from a
        store leaves this empty and is then unconstrained.
    """

    name: str
    fn: Callable
    kind: str = VALUE
    provides: Tuple[str, ...] = ()
    requires: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in (STORE, VALUE):
            raise ValueError(f"kind must be {STORE!r} or {VALUE!r}; got {self.kind!r}")
        if self.kind == VALUE and self.provides:
            raise ValueError(
                f"{self.name!r} is a {VALUE} job but declares provides={self.provides}. "
                f"A job that writes a store partition is a {STORE} job — the distinction "
                "is what the ordering check runs on."
            )

    def as_tuple(self) -> Tuple[str, Callable]:
        """``(name, fn)``, the shape the warmer's runner already consumes."""
        return (self.name, self.fn)


def assert_ordered(jobs: Sequence[WarmJob]) -> None:
    """Raise unless every requirement is provided by an EARLIER job.

    A requirement nothing provides is allowed on purpose: plenty of value jobs
    read stores warmed by a different schedule entirely, and forbidding that
    would mean listing every external producer here just to keep the check quiet.
    What is forbidden is a requirement provided by this same list, later.

    Raises
    ------
    WarmOrderError
        Naming the consumer, the asset, and the producer that comes too late.
    """
    seen: Dict[str, int] = {}
    for i, job in enumerate(jobs):
        for asset in job.provides:
            seen.setdefault(asset, i)

    problems: List[str] = []
    for i, job in enumerate(jobs):
        for asset in job.requires:
            at = seen.get(asset)
            if at is None:
                continue
            if at >= i:
                problems.append(
                    f"  job {i + 1} {job.name!r} requires {asset!r}, which job "
                    f"{at + 1} {jobs[at].name!r} provides — that is "
                    f"{'the same job' if at == i else 'later in the list'}."
                )
    if problems:
        raise WarmOrderError(
            "Warm jobs are out of order; a value job would run before the store it "
            "reads, and the source would fall through to its LIVE path (for the "
            "Velocity sources, that opens Excel on an unattended scheduled task):\n"
            + "\n".join(problems)
        )


def assert_unique_providers(jobs: Sequence[WarmJob]) -> None:
    """Raise if two jobs write the same store asset.

    ``write_day`` replaces a whole day partition rather than merging into it, so
    two producers sharing an asset key do not interleave — the later one deletes
    the earlier one's rows for that day, and the warm reports success both times.

    Raises
    ------
    WarmOrderError
        Naming the asset and both jobs.
    """
    owner: Dict[str, str] = {}
    clashes: List[str] = []
    for job in jobs:
        for asset in job.provides:
            if asset in owner:
                clashes.append(
                    f"  {asset!r} is written by both {owner[asset]!r} and {job.name!r}"
                )
            else:
                owner[asset] = job.name
    if clashes:
        raise WarmOrderError(
            "Two warm jobs write the same store asset. write_day replaces a whole day "
            "partition, so one will silently delete the other's data and both will "
            "report success:\n" + "\n".join(clashes)
        )


def check(jobs: Sequence[WarmJob]) -> None:
    """Both invariants. Call at import so a bad edit fails before anything runs."""
    assert_unique_providers(jobs)
    assert_ordered(jobs)


def describe(jobs: Iterable[WarmJob]) -> str:
    """A listing that shows the dependency structure, for ``--list``."""
    lines = []
    for i, job in enumerate(jobs, 1):
        bits = [f"  {i}. {job.name}  [{job.kind}]"]
        if job.provides:
            bits.append(f"       provides: {', '.join(job.provides)}")
        if job.requires:
            bits.append(f"       requires: {', '.join(job.requires)}")
        lines.extend(bits)
    return "\n".join(lines)
