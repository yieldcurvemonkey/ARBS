r"""Serve Citi swaption cubes from the warmed store instead of driving Excel.

The gap this closes
-------------------
:class:`Caching.swaption_cube_store.SwaptionCubeStore` was written by, and read
by, exactly one thing: ``scripts/citivelo_swaption_vol_warm.py``. Nothing under
``MDP/`` referenced it, so ``IRSwaptionMDP``'s only route to a cube was
``_cube_for_date`` -> ``fetch_cube`` -> ``CitiVelocityExcelClient.connect()``.
Every dated swaption request therefore drove the user's signed-in Excel, once per
date, for data already sitting on disk. Two consequences, both observed:

* a 4-day timeseries took 134 s and returned an empty frame;
* it failed with ``A swaption CUBE needs strike offsets; this cube data has
  none`` - Excel had served an ATM-only cube for a date whose stored partition
  holds the full thirteen-offset smile.

Note the *second* cache it also bypassed: ``fetch_cube`` accepts a
``cache=CitiVeloTagCache`` ("the cache does the fetching and only the missing
spans hit Excel") and ``provider.py`` never passed one. So the live path was
uncached at both levels.

The history is not uniform, and that is data
--------------------------------------------
Measured over all 2,699 stored USD days on 2026-08-08:

    ATM only        1,067 days   2015-10-08 .. 2020-01-23   1 offset,     153 rows
    full smile      1,632 days   2020-01-24 .. 2026-08-07   13 offsets, 1,989 rows

Citi published no strike offsets before 2020-01-24. A cube build on a 2016 date
legitimately has no smile. That is the single most mistakable thing here: it
looks exactly like a cache miss, and the "obvious" fix - refetch from Excel - is
the behaviour being removed. So :class:`StoredCube` carries ``smile`` explicitly
and :func:`explain_missing_smile` writes the reason out in full, rather than
leaving a caller to infer it from an offsets list.

Read cost
---------
Profiled 2026-08-08 over 60 real USD days. ``reconstruct_cube`` was 62 ms/day, of
which ``read_day`` (the parquet) was 6 ms and ``cube_from_frame`` was the rest -
78% of it in fourteen separate ``pivot_table`` calls, one of them dead code. That
is fixed in the store (one reshape, sliced per offset: 33.3 -> 8.25 ms/day,
bit-identical over all 2,699 days). What remains here is a per-process memo,
because the expensive part is date-DEPENDENT and cannot be hoisted the way the
curve side hoisted its fixings lookup.

``reconstruct_cubes_batch`` is **not** faster than a loop - measured 61.9 vs 63.9
ms/day, because it *is* a loop over ``reconstruct_cube``. It is used anyway for
the batch entry point, since it is the store's own API and correctly tolerates a
bad day, but no speed claim is made for it.
"""

from __future__ import annotations

import dataclasses
import datetime
import logging
import threading
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

_logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_STORE_PROVIDER",
    "STORE_GAP_NEIGHBOURHOOD_DAYS",
    "StoredCube",
    "store_asset",
    "load_stored_cubes",
    "stored_coverage",
    "stored_gap_dates",
    "explain_missing_smile",
    "clear_stored_cube_cache",
]

#: The provider segment of the store asset name. ``asset_for(currency, provider=)``
#: mints ``USD-SWAPTIONVOL-CITIVELOEXCEL``; the warm writes that and nothing else.
DEFAULT_STORE_PROVIDER = "CITIVELOEXCEL"

#: How far either side of a date the store has to be warm before an absent
#: partition is read as a COVERAGE GAP rather than an unwarmed date.
#:
#: Seven days is the longest run of consecutive non-session days a US rates
#: calendar produces (a Thursday holiday plus the Friday plus a weekend still
#: leaves a warm neighbour inside a week), and it matches
#: ``provider._MAX_SKEW_DONOR_DAYS`` so the two windows do not have to be
#: reasoned about separately.
STORE_GAP_NEIGHBOURHOOD_DAYS = 7

#: The first date Citi served strike offsets, measured from the store itself
#: rather than asserted. Used only in messages - the code never branches on a
#: hard-coded date, it branches on how many offsets the partition actually has.
FIRST_SMILE_DATE = datetime.date(2020, 1, 24)

#: ``(base_dir, asset, iso date) -> StoredCube``.
#:
#: The **base_dir is part of the key** and has to be: ``load_stored_cubes``
#: accepts a ``store=``, tests build one under ``tmp_path``, and without the
#: directory in the key the first store to answer for an asset/date poisons every
#: other store for the life of the process - a caller that passed a specific
#: store would silently get the DEFAULT store's cube.
#:
#: Per process and unbounded. A full-history USD warm is 2,699 entries of a few
#: hundred KB of float frames each; the alternative is re-pivoting at 8 ms a day
#: on every repeat request. :func:`clear_stored_cube_cache` drops it if a
#: long-lived process needs the memory back.
_STORE_CACHE: Dict[Tuple[str, str, str], "StoredCube"] = {}
_STORE_CACHE_LOCK = threading.Lock()


@dataclasses.dataclass(frozen=True)
class StoredCube:
    """One day out of the store, with its shape stated rather than implied."""

    as_of: datetime.date
    asset: str
    data: Any  #: SwaptionCubeData
    offsets_bp: Tuple[float, ...]
    source: str  #: the store's own provenance column, e.g. ".../DAILY/atm_only"

    @property
    def smile(self) -> str:
        """``'full'`` when there is at least one non-zero offset, else ``'atm_only'``."""
        return "full" if any(float(o) != 0.0 for o in self.offsets_bp) else "atm_only"

    @property
    def has_smile(self) -> bool:
        return self.smile == "full"

    def provenance(self) -> Dict[str, Any]:
        """What to put in a context's metadata so the shape is visible downstream."""
        return {
            "origin": "swaption_cube_store",
            "asset": self.asset,
            "as_of": self.as_of.isoformat(),
            "smile": self.smile,
            "n_offsets": len(self.offsets_bp),
            "offsets_bp": list(self.offsets_bp),
            "store_source": self.source,
        }


def store_asset(currency: str, *, provider: str = DEFAULT_STORE_PROVIDER) -> str:
    from Caching.swaption_cube_store import asset_for

    return asset_for(currency, provider=provider)


def explain_missing_smile(stored: "StoredCube", *, backend: str = "the QuantLib cube") -> str:
    """The message to raise when a backend needs offsets and the day has none.

    Deliberately long. The default message - "A swaption CUBE needs strike
    offsets; this cube data has none... or refetch with offsets_bp=(-50,...)" -
    reads as a cache problem and invites exactly the Excel refetch this module
    exists to remove. On a pre-2020 date the refetch cannot succeed, because the
    quotes were never published.
    """
    return (
        f"{stored.asset} {stored.as_of.isoformat()} is stored ATM-only "
        f"({len(stored.offsets_bp)} offset, source={stored.source!r}), and "
        f"{backend} needs strike offsets. This is DATA, not a cache miss: Citi "
        f"published no swaption strike offsets before {FIRST_SMILE_DATE.isoformat()} "
        f"(measured over the whole store - 1,067 ATM-only days to "
        f"2020-01-23, 1,632 full-smile days after). Refetching from Excel will "
        f"not produce a smile for this date and will drive the add-in for nothing. "
        f"Either request an ATM surface for this date, or restrict the range to "
        f"{FIRST_SMILE_DATE.isoformat()} onward."
    )


def _default_store():
    from Caching.swaption_cube_store import SwaptionCubeStore

    return SwaptionCubeStore.default()


def _store_key(store: Any) -> str:
    """A stable identity for a store, for the memo key. Never raises."""
    try:
        return str(getattr(store, "base_dir", None) or repr(store))
    except Exception:  # noqa: BLE001
        return repr(store)


def _stored_one(store: Any, asset: str, day: datetime.date) -> Optional[StoredCube]:
    key = (_store_key(store), asset, day.isoformat())
    hit = _STORE_CACHE.get(key)
    if hit is not None:
        return hit
    frame = store.read_day(asset, day)
    if frame is None or getattr(frame, "empty", True):
        return None
    try:
        data = store.cube_from_frame(frame)
    except Exception as exc:  # noqa: BLE001 - one bad day must not kill a range
        _logger.warning("swaption cube store: %s %s unusable (%s)", asset, day, exc)
        return None
    offsets = tuple(sorted(float(o) for o in frame["offset_bp"].unique()))
    source = str(frame["source"].iloc[0]) if "source" in frame else ""
    stored = StoredCube(
        as_of=day, asset=asset, data=data, offsets_bp=offsets, source=source
    )
    with _STORE_CACHE_LOCK:
        _STORE_CACHE[key] = stored
    return stored


def load_stored_cubes(
    currency: str,
    dates: Iterable[datetime.date],
    *,
    provider: str = DEFAULT_STORE_PROVIDER,
    store: Any = None,
) -> Dict[datetime.date, StoredCube]:
    """``{date: StoredCube}`` for whatever the store has. Missing days are absent.

    Never raises for a cold store, an unknown currency or a damaged partition:
    the caller's contract is "use this if it is there", and a miss has to fall
    through to the live path rather than take the request down.
    """
    try:
        active = store if store is not None else _default_store()
        asset = store_asset(currency, provider=provider)
    except Exception as exc:  # noqa: BLE001
        _logger.debug("swaption cube store unavailable (%s); falling through", exc)
        return {}

    out: Dict[datetime.date, StoredCube] = {}
    for day in dates:
        try:
            stored = _stored_one(active, asset, day)
        except Exception as exc:  # noqa: BLE001
            _logger.warning("swaption cube store: %s %s failed (%s)", asset, day, exc)
            continue
        if stored is not None:
            out[day] = stored
    return out


def stored_coverage(
    currency: str, *, provider: str = DEFAULT_STORE_PROVIDER, store: Any = None
) -> Dict[str, Any]:
    """``{asset, n_days, first, last}`` - what a caller can expect to be warm."""
    try:
        active = store if store is not None else _default_store()
        asset = store_asset(currency, provider=provider)
        days: List[datetime.date] = active.available_dates(asset)
    except Exception as exc:  # noqa: BLE001
        return {"asset": None, "n_days": 0, "first": None, "last": None, "error": str(exc)}
    return {
        "asset": asset,
        "n_days": len(days),
        "first": days[0] if days else None,
        "last": days[-1] if days else None,
    }


def stored_gap_dates(
    currency: str,
    dates: Iterable[datetime.date],
    *,
    provider: str = DEFAULT_STORE_PROVIDER,
    store: Any = None,
    neighbourhood_days: int = STORE_GAP_NEIGHBOURHOOD_DAYS,
) -> frozenset[datetime.date]:
    """Which of ``dates`` the store is warm AROUND but holds no partition for.

    A ``pd.bdate_range`` contains market holidays. Citi published no cube on
    those days, so the store legitimately has no partition - and the fallback
    below it is ``CitiVelocityExcelClient.connect()``, once per date. Measured
    2026-08-21 on a 2022-01-02..2026-08-20 USD pull: 1,155 of 1,209 business days
    were served from the store and the other 54 each drove Excel, 51 of them for
    a non-session day whose fetch then came back an amputated cube.

    "Warm around" rather than "inside the store's first..last" on purpose. The
    store's span is eleven years, so a bounds test would swallow a partially
    warmed history whole: a caller who has warmed 2015 and 2026 would silently
    lose every date between, with no fetch and no error. Requiring a partition
    within ``neighbourhood_days`` on BOTH sides means a holiday qualifies (its
    neighbours are days away) while a date past the end of the warm, or inside a
    month-wide hole, does not - those keep the existing live fallback.

    Never raises: a cold store, an unknown currency or an unreadable directory
    return an empty set, which restores the previous behaviour exactly.
    """
    try:
        active = store if store is not None else _default_store()
        asset = store_asset(currency, provider=provider)
        available = set(active.available_dates(asset))
    except Exception as exc:  # noqa: BLE001 - a gap probe must never take a request down
        _logger.debug("swaption cube store gap probe unavailable (%s)", exc)
        return frozenset()

    if not available:
        return frozenset()

    span = max(0, int(neighbourhood_days))
    if span == 0:
        return frozenset()

    gaps: set[datetime.date] = set()
    for day in dates:
        if day in available:
            continue
        lags = range(1, span + 1)
        warm_before = any((day - datetime.timedelta(days=k)) in available for k in lags)
        warm_after = any((day + datetime.timedelta(days=k)) in available for k in lags)
        if warm_before and warm_after:
            gaps.add(day)
    return frozenset(gaps)


def clear_stored_cube_cache() -> None:
    """Drop the per-process memo. Tests use this; nothing else should need it."""
    with _STORE_CACHE_LOCK:
        _STORE_CACHE.clear()
