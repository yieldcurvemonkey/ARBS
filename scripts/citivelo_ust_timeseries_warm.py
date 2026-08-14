r"""Ten years of US Treasury TIMESERIES VALUES, into the computed TS store.

The sibling script ``citivelo_ust_universe_warm.py`` warms TAGS - Citi's raw
per-bond series in the parquet tag cache. This one warms the layer above it: the
numbers a notebook actually asks for, addressed by
``UnifiedQuery(cusip=..., value=...)`` and stored in ``data/ts``. Measured
2026-08-08, that store held roughly 14 aliases x 3 values x 15 days. The target
is 28 aliases and 349 specific issues over ten years.

The hard part is not the volume. It is that a constant-maturity alias is a
different bond every few weeks
------------------------------------------------------------------------
``CT2`` over ten years is 116 different notes. 94 of them have redeemed.
Counted offline from Treasury's own issuance history over
``2016-08-07 .. 2026-08-07``:

========  =====================  =======================  ==========
window    alias constituents     still in Citi's catalog  union to fetch
========  =====================  =======================  ==========
1 year                       87              84  (97%)              352
5 years                     325             250  (77%)              424
10 years                    597             307  (51%)              639
========  =====================  =======================  ==========

The loss is entirely at the short end. ``CT10`` keeps 40 of 41 constituents,
``CT20`` 25 of 25 and ``CT30`` 41 of 41; ``CT2`` keeps 22 of 116. Per calendar
year, the share of alias-days whose bond Citi still lists runs 100% in 2025-26,
89% in 2024, 71% in 2022 and **22% in 2016**.

Three things had to be settled before this script could exist, and two of them
were settled offline:

**Can the aliases be resolved at all ten years ago?** Yes. The UST reference
table (``source="fiscaldata"``) is the full issuance history, not a snapshot of
what is outstanding - 1,785 rows, issue dates from 1979-11-15, and 1,433 of them
already matured. ``_filter_and_rank_ref_df`` ranks on-the-runs correctly at every
date tested back to 2016. 24 of the 28 aliases resolve on every business day; the
four exceptions are the 20-year ranks, and they are not a defect - Treasury
reintroduced the 20-year in May 2020, so ``CT20`` first resolves 2020-06-02,
``O20`` 2020-09-01, ``OO20`` 2020-12-01 and ``OOO20`` 2021-03-02.

**Does Citi still serve a bond that has MATURED?** YES, and ten years back.
Measured 2026-08-08 by reading the tag cache after a ten-year fetch, grouped by
the axis the question is actually about - **maturity year**:

========  =====  ===================  =========
mat year  bonds  series ends at       med rows
          served its own maturity
========  =====  ===================  =========
2016         23                   23         53
2017         50                   50        226
2018         51                   51        476
2019         52                   52        679
2020         55                   55        825
2021         54                   54        985
2022         51                   51      1,052
2023         54                   54      1,129
2024         50                   50      1,131
2025         54                   54      1,191
========  =====  ===================  =========

**494 of 494**, every one ending within a week of its own redemption. The
universe LISTING excludes a matured bond; the per-bond TAG does not, and the
retention window is at least the ten years asked for.
``scripts/citivelo_ust_history_depth_probe.py`` is the tool that re-asks this if
Citi's retention is ever suspected of changing.

How deep the tag history goes, and why the default is PRICE + YIELD
--------------------------------------------------------------------
Depth is per ``(bond, value)``, not per bond. Of the 301 bonds whose ``PRICE``
reaches the 2016-08-08 request floor:

===============  ==================  ============================
value            reach 2016-08-08    floor at 2020-04-01 instead
===============  ==================  ============================
``PRICE``               301 / 301                              0
``YIELD``               301 / 301                              0
``DV01``                301 / 301                              0
``DURATION``            245 / 301                             53
``SPREAD_TSY``          245 / 301                             53
===============  ==================  ============================

Fifty-three bonds landing on **exactly** 2020-04-01 out of one uniform request is
Citi's floor, not ours, and it is not random: 43 of them are 30-years and 10 are
10-years - the long-dated issues that were alive in 2020 and still are. Nothing
short-dated is affected, and the matured bonds keep their older history.

So ``PRICE`` and ``YIELD`` are the two values with ten unbroken years behind them
for every bond, which is why they are the default. ``DV01`` is equally deep and
is one flag away; ``DURATION`` and ``SPREAD_TSY`` are fine too as long as a caller
knows the long end starts in 2020.

What a run costs
----------------
Counted by ``plan``, never estimated - run it before you run anything else. The
numbers move with the committed catalog, which is an accumulating union: it held
349 USA.USD.GOVT ISINs at 15:00 on 2026-08-08 and 877 by 17:00, because a
parallel effort merged the matured bonds into it.

``--years 10 --values PRICE YIELD``, 28 aliases plus every catalogued issue:

==================  ====================  ====================
                    catalog of 349        catalog of 877
==================  ====================  ====================
bonds to fetch                     639                    877
tags                             1,278                  1,754
tag-cache cells              1,304,788              1,672,046
computed TS rows               900,148              1,825,118
synthesised (matured)              290                      0
==================  ====================  ====================

The alias half is invariant at 137,412 rows either way - it is driven by the
reference table, not the catalog. The rest is the specific-issue set, and it
doubled because the catalog did.

Note the last row: as the catalog absorbs matured bonds, ``historic_universe``
synthesises fewer of them and eventually none. That is the correct behaviour and
not a redundancy - it closes whatever gap is actually there, and a catalog
snapshot that ever loses a bond is covered again without anything changing.

FETCH, projected: at the sibling warm's measured EOD rate - 52 tags over five
years for +1 MB of Excel and 3.3 s - 1,278 tags is tens of megabytes and minutes.
EOD really is cheap; it is intraday that is not, and this job has no intraday
phase. Projected, not measured, because the fetch has not been run: Excel was at
9,651 MB against a 3,800 MB ceiling, and the gate below refuses in that state,
which is the correct behaviour and not a defect.

BUILD, measured 2026-08-08 offline against the warmed tag cache: **377 symbols
(28 aliases + 349 issues) x 2 values over 6 business days = 4,488 cells in
372 s.** So the ten-year build extrapolates to roughly **20 hours of CPU** - which
is why it is chunked a calendar year at a time, resumable per (symbol, year), and
why re-running a finished window costs 4 s rather than starting over.

Fetch and build are separate on purpose
---------------------------------------
``fetch`` is the only phase that can touch Excel. ``build`` is pure CPU against
the tag cache and is forced ``offline`` at the MDP, so a cache miss produces an
empty column rather than a workbook. A lost Excel session therefore costs the
fetch time and none of the build, and the build can be re-run as often as
you like on a laptop with no add-in at all.

Both phases are resumable through one manifest, written after every batch, and
both stop at the Excel ceiling rather than pushing past it. The add-in's memory
only ever grows and only a HUMAN restart clears it - it wedged at 5,249 MB on
2026-08-07 and was measured at 13,884 MB the next day.

Usage
-----
::

    python scripts/citivelo_ust_timeseries_warm.py plan --years 10
    python scripts/citivelo_ust_timeseries_warm.py fetch --years 10
    python scripts/citivelo_ust_timeseries_warm.py build --years 10
    python scripts/citivelo_ust_timeseries_warm.py status --years 10
    python scripts/citivelo_ust_timeseries_warm.py build --years 1 --cusips none

The ten-year backfill is a deliberate one-off. The nightly slice is job
"CITIVELO UST timeseries values" in ``scripts/daily_cache_warmer.py``.
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import pathlib
import sys
import time
from typing import Dict, List, Optional, Sequence, Tuple

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

log = logging.getLogger("citivelo-ust-ts-warm")

#: Leave headroom below the hard 3,800 MB ceiling so a batch in flight cannot
#: cross it. Same number as the sibling tag warm, for the same reason.
WORKING_CEILING_MB = 3500.0

#: PRICE and YIELD, and that is a measurement rather than a preference: they are
#: the two values with a bond's whole life behind them. DURATION and SPREAD_TSY
#: floor at 2020-04-01 on every bond measured, so asking for them over ten years
#: buys six years of nothing at full Excel price. Widen with ``--values``.
DEFAULT_VALUES: Tuple[str, ...] = ("PRICE", "YIELD")

#: What the BUILD phase computes, stated directly rather than derived from the
#: fetch set. The two are not the same list and must not be forced to be:
#: ``unified_values`` maps one Citi token to at most one ``UnifiedValue``, so a
#: build driven by the fetch set can only ever produce ``FRB_CLEAN_PRICE`` and
#: ``FRB_YTM`` - while the ten-year backfill writes ten values per bond. Left
#: derived, the nightly job would refresh two of those ten and the other eight
#: would go stale from the day the backfill finished, silently, because a series
#: that stops updating looks exactly like a series with nothing new to say.
#:
#: Four of these need no tag of their own (they are solved from ``PRICE``); the
#: rest read ``DURATION``, ``DV01`` and ``SPREAD_TSY``, which the EOD universe tag
#: warm already caches.
DEFAULT_BUILD_VALUES: Tuple[str, ...] = (
    "FRB_YTM", "FRB_CLEAN_PRICE", "FRB_DIRTY_PRICE", "FRB_DV01", "FRB_MOD_DURATION",
    "FRB_SPREAD_TSY", "FRB_CITI_PRICE", "FRB_CITI_YIELD", "FRB_CITI_DURATION",
    "FRB_CITI_DV01",
)

#: Bonds per fetch batch, and symbols per build batch. Small enough that the
#: manifest is fine-grained and a stop loses little.
DEFAULT_FETCH_BATCH = 16
DEFAULT_BUILD_BATCH = 12

#: Parallelism for the pricing phase, matching the daily warmer's N_JOBS.
DEFAULT_JOBS = 12


def _manifest_path() -> pathlib.Path:
    """Progress lives beside the TAG CACHE, not in the repo.

    It describes what THIS MACHINE holds, which is not a property of the
    codebase - and the nightly slice of this job runs from the PRIMARY checkout.
    A tracked file here would leave the user's working tree dirty every morning
    with a change nobody made, which is exactly the state that makes a real edit
    invisible.
    """
    from MDP.CitiVelocityExcel.cache import default_cache_dir

    return default_cache_dir() / "ust_timeseries_warm_manifest.json"


MANIFEST = _manifest_path()


# ──────────────────────────────────────────────────────────────────────────
# What to warm
# ──────────────────────────────────────────────────────────────────────────


def default_aliases() -> Tuple[str, ...]:
    """The 28 constant-maturity aliases: 4 ranks x 7 tenors."""
    from MDP.CitiVelocityExcel.bonds.historic import constant_maturity_aliases

    return constant_maturity_aliases()


def reference_table(force_refresh: bool = False):
    """Treasury's full issuance history. Cached on disk; no Excel, no Citi."""
    from MDP.FixedRateBonds.reference_data_cache.ust_reference_data import update_reference_data

    return update_reference_data(source="fiscaldata", force_refresh=force_refresh)


def catalog_cusips() -> Tuple[str, ...]:
    """Every UST Citi currently lists, as CUSIPs, in a stable order.

    This is the default ``--cusips`` set: the 349 bonds whose tags the sibling
    warm already keeps current. Ordered by ISIN so a ``--limit`` run is
    reproducible.
    """
    from MDP.CitiVelocityExcel.bonds.universe import BondUniverse
    from utils.identifiers import InvalidIdentifierError, isin_to_cusip, normalise_cusip

    out: List[str] = []
    for descriptor in sorted(
        BondUniverse.from_catalog(country="USA", asset_type="GOVT"), key=lambda d: d.isin
    ):
        try:
            out.append(normalise_cusip(isin_to_cusip(descriptor.isin)))
        except InvalidIdentifierError:
            continue
    return tuple(out)


def business_days(start: datetime.date, end: datetime.date) -> List[datetime.date]:
    import pandas as pd

    return [d.date() for d in pd.bdate_range(start, end)]


class WarmPlan:
    """Everything a run needs, computed offline before anything connects.

    Deliberately built in full before either phase starts. The fetch needs the
    union of every bond any alias ever was; the build needs each symbol's own
    live window; and the memory gate needs to be able to say "this is what it
    would cost" without opening a workbook to find out.
    """

    def __init__(
        self,
        *,
        start: datetime.date,
        end: datetime.date,
        aliases: Sequence[str],
        cusips: Sequence[str],
        values: Sequence[str],
        build_values: Optional[Sequence[str]] = None,
        force_refresh: bool = False,
        base_universe=None,
    ) -> None:
        from MDP.CitiVelocityExcel.bonds.historic import (
            alias_rank_and_tenor,
            cusips_to_isins,
            resolve_alias_history,
        )

        self.start = start
        self.end = end
        self.aliases = tuple(aliases)
        self.cusips = tuple(cusips)
        self.values = tuple(values)
        #: ``UnifiedValue`` member names for the build phase. ``None`` keeps the
        #: old behaviour of deriving them from the fetch set.
        self.build_values = tuple(build_values) if build_values else None
        # The catalog is an ACCUMULATING UNION and a moving target - it went from
        # 349 to 877 USA.USD.GOVT ISINs in one afternoon. Anything that needs a
        # fixed starting universe (a test, or a caller deliberately restricting
        # the run) passes one here rather than depending on today's snapshot.
        self.base_universe = base_universe

        self.ref_df = reference_table(force_refresh=force_refresh)
        self.days = business_days(start, end)

        # Alias history is resolved for anything ALIAS-SHAPED, wherever it came
        # from. ``--cusips CT20`` is a reasonable thing to type and the identifier
        # is chained whichever flag carried it; resolving only ``--aliases`` would
        # give that one the full requested window instead of its own, and the
        # 20-year ranks would then look permanently unfinished.
        alias_shaped = []
        for symbol in (*self.aliases, *self.cusips):
            try:
                alias_rank_and_tenor(symbol)
            except ValueError:
                continue
            alias_shaped.append(symbol)
        self.history = resolve_alias_history(
            self.ref_df, tuple(dict.fromkeys(alias_shaped)), self.days
        )

        alias_cusips: List[str] = []
        for track in self.history.values():
            alias_cusips.extend(track.cusips)
        self.constituents = tuple(dict.fromkeys(alias_cusips))

        self.isin_of = cusips_to_isins([*self.constituents, *self.cusips])
        # Sorted so a --limit run and a resume see the same order.
        self.isins = tuple(sorted(set(self.isin_of.values())))

        self._life: Dict[str, Tuple[datetime.date, datetime.date]] = {}
        for _, row in self.ref_df.iterrows():
            isin = self.isin_of.get(str(row["cusip"]).strip().upper())
            if isin is None:
                continue
            self._life[str(row["cusip"]).strip().upper()] = (
                _as_date(row["issue_date"]),
                _as_date(row["maturity_date"]),
            )

    # -- the fetch side -------------------------------------------------

    def universe(self):
        """A universe that admits the matured constituents. No Excel.

        Additive over whatever base is in play. If the committed catalog already
        names a bond it keeps its catalog descriptor and its validated coverage;
        only the ones the catalog cannot name are synthesised from the UST
        reference table. So this stays correct whether the catalog holds 349 names
        or 877 - it closes whatever gap is actually there rather than assuming a
        particular one.
        """
        from MDP.CitiVelocityExcel.bonds.historic import historic_universe

        return historic_universe(self.isins, self.ref_df, base=self.base_universe)

    def resolutions(self):
        """One :class:`BondResolution` per bond, in ISIN order."""
        from MDP.CitiVelocityExcel.bonds.resolution import resolve_bonds

        resolved, failures = resolve_bonds(list(self.isins), universe=self.universe(), strict=False)
        for token, why in failures.items():
            log.info("  %s skipped: %s", token, why)
        return [resolved[i] for i in self.isins if i in resolved]

    # -- the build side -------------------------------------------------

    def symbols(self) -> Tuple[str, ...]:
        """What the computed store gets rows for: aliases first, then CUSIPs.

        Aliases first because they are the smaller, more-read half - a run that
        stops at the ceiling should have finished the curve everyone looks at
        rather than a third of the specific issues.
        """
        return (*self.aliases, *self.cusips)

    def window_for(self, symbol: str) -> Optional[Tuple[datetime.date, datetime.date]]:
        """The days this symbol can possibly have data on, or ``None``.

        For an alias that is the span it actually resolved over, which is what
        keeps the 20-year ranks from looking permanently unfinished: ``CT20``
        cannot exist before 2020-06-02, so a "done means the whole requested
        window" rule would re-price it every night forever and never mark it.

        For a specific issue it is the bond's own life clipped to the window,
        which is where most of the saving is - the 349 bonds Citi lists have a
        median of about four years inside a ten-year window, so pricing each of
        them over the full span would be mostly empty days at full CPU price.
        """
        if symbol in self.history:
            track = self.history[symbol]
            if not track.by_date:
                return None
            first, last = min(track.by_date), max(track.by_date)
            # Snap back to the REQUESTED bound when the alias resolved on the very
            # first (or last) business day, because then the bound is ours and not
            # the alias's. Without this the effective window inherits a business-day
            # edge - a run starting 2025-01-01 gets 2025-01-02 - and widening the
            # request shifts that edge by a day or two, changing the key and
            # re-pricing a year that gained nothing. The 20-year ranks, whose floor
            # is genuinely interior, keep their own date either way, which is the
            # whole point of keying on the effective window.
            lo = self.start if self.days and first == self.days[0] else first
            hi = self.end if self.days and last == self.days[-1] else last
            return lo, hi
        life = self._life.get(str(symbol).strip().upper())
        if life is None:
            # Not a CUSIP this table knows - price the whole window rather than
            # silently skipping it. Guessing "no data" for an identifier we do
            # not recognise is how a warm quietly omits something.
            return self.start, self.end
        issue, maturity = life
        lo = max(self.start, issue) if issue else self.start
        hi = min(self.end, maturity) if maturity else self.end
        return None if hi < lo else (lo, hi)

    def slices(self, symbol: str) -> List[Tuple[int, datetime.date, datetime.date]]:
        """``[(year, lo, hi), ...]`` - the build unit.

        A calendar year at a time, so memory is bounded and the manifest is
        fine-grained enough that a stop costs one year of one batch.
        """
        window = self.window_for(symbol)
        if window is None:
            return []
        lo, hi = window
        out = []
        for year in range(lo.year, hi.year + 1):
            y_lo = max(lo, datetime.date(year, 1, 1))
            y_hi = min(hi, datetime.date(year, 12, 31))
            if y_lo <= y_hi:
                out.append((year, y_lo, y_hi))
        return out

    def describe(self) -> str:
        n_alias_days = sum(len(t.by_date) for t in self.history.values())
        # Count "unlisted" against the base this run is actually using, not
        # against the committed catalog - otherwise a restricted run reports a
        # gap it does not have, or hides one it does.
        listed = (
            {d.isin for d in self.base_universe} if self.base_universe is not None
            else _listed_isins()
        )
        matured = sum(1 for i in self.isins if i not in listed)
        cells = 0
        for cusip, isin in self.isin_of.items():
            life = self._life.get(cusip)
            if life is None:
                continue
            lo = max(self.start, life[0]) if life[0] else self.start
            hi = min(self.end, life[1]) if life[1] else self.end
            if hi >= lo:
                cells += len(business_days(lo, hi))
        n_values = len(self.values)
        build_rows = n_alias_days + sum(
            len(business_days(*w)) for w in (self.window_for(c) for c in self.cusips) if w
        )
        return "\n".join(
            [
                f"window            {self.start} .. {self.end}  ({len(self.days)} business days)",
                f"values            {', '.join(self.values)}  (N={n_values})",
                f"aliases           {len(self.aliases)}  ->  {len(self.constituents)} distinct constituents,"
                f" {n_alias_days} resolvable alias-days of {len(self.days) * len(self.aliases)}",
                f"specific issues   {len(self.cusips)}",
                f"bonds to FETCH    {len(self.isins)}  ({len(self.isins) - matured} listed by Citi,"
                f" {matured} matured/unlisted)",
                f"tags              {len(self.isins) * n_values}",
                f"tag-cache cells   {cells * n_values:,}",
                f"computed TS rows  {build_rows * n_values:,}",
            ]
        )


def _as_date(value) -> Optional[datetime.date]:
    import pandas as pd

    if value is None:
        return None
    ts = pd.Timestamp(value)
    return None if pd.isna(ts) else ts.date()


def _listed_isins() -> set:
    from MDP.CitiVelocityExcel.bonds.universe import BondUniverse

    return {d.isin for d in BondUniverse.from_catalog(country="USA", asset_type="GOVT")}


# ──────────────────────────────────────────────────────────────────────────
# The manifest
# ──────────────────────────────────────────────────────────────────────────


def _key(start, end, values: Sequence[str]) -> str:
    """What "already done" means, for one unit of work.

    The window AND the value set, both of them. Drop the window and a run that
    widened ``--years`` from 5 to 10 reads the manifest, sees every unit at the
    right key and does nothing, reporting a ten-year warm with five years of it
    missing. Drop the values and the same silence follows an added ``--values``.

    ``start``/``end`` are the EFFECTIVE bounds of the unit, not the bounds the
    caller typed. That is what makes ``CT20`` behave: it cannot exist before
    2020-06-02, so its effective start does not move when a ten-year request
    becomes a twelve-year one, and it is not re-priced for history that cannot
    exist. A key built from the requested window instead would leave the four
    20-year ranks permanently unfinished.

    Values are sorted so ``--values YIELD PRICE`` is the same request as
    ``--values PRICE YIELD``; an order-sensitive key would re-warm everything
    because someone typed the same set in a different order.
    """
    return f"{start}|{end}|{','.join(sorted(values))}"


def _load_manifest() -> dict:
    if MANIFEST.exists():
        try:
            return json.loads(MANIFEST.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - a corrupt manifest must not block a warm
            log.warning("manifest unreadable; starting a fresh one")
    return {"fetch": {}, "build": {}}


def _save_manifest(man: dict) -> None:
    """Atomic: temp file, fsync, ``os.replace``. See the sibling warm's ``_save``.

    ``write_text`` truncates first, so a write that fails destroys the resume
    state it was recording. The sibling script lost 754 chunks - about nineteen
    hours - to exactly that when the disk filled mid-save with
    ``OSError: [Errno 28] No space left on device``. This one has the same shape
    and the same exposure, so it gets the same fix rather than waiting its turn.
    """
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    tmp = MANIFEST.with_name(MANIFEST.name + f".tmp{os.getpid()}")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(man, fh, indent=1, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, MANIFEST)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def cached_tags(freq: str, tags: Sequence[str]) -> int:
    """How many of ``tags`` are actually on disk in the tag cache at ``freq``.

    The point of a warm is the file, not the fetch. The sibling script learned
    this the expensive way: its first version "warmed" 349 bonds in 134 s, left
    zero parquets on disk and recorded 349/349 done, because the transport it
    used bypassed the cache entirely.
    """
    from MDP.CitiVelocityExcel.cache import default_cache_dir
    from MDP.CitiVelocityExcel.frequencies import normalise_frequency

    root = default_cache_dir() / normalise_frequency(freq)
    if not root.is_dir():
        return 0
    on_disk = {p.stem for p in root.rglob("*.parquet")}
    return sum(1 for t in tags if str(t) in on_disk)


# ──────────────────────────────────────────────────────────────────────────
# Phase 1: FETCH - the only phase that can touch Excel
# ──────────────────────────────────────────────────────────────────────────


def _memory_now() -> Optional[float]:
    from MDP.CitiVelocityExcel.memory_guard import excel_memory_mb

    try:
        return excel_memory_mb()
    except Exception:  # noqa: BLE001 - an unreadable probe is not a crash
        return None


def fetch(
    plan: WarmPlan,
    *,
    batch: int = DEFAULT_FETCH_BATCH,
    ceiling_mb: float = WORKING_CEILING_MB,
    force: bool = False,
    limit: Optional[int] = None,
) -> dict:
    """Warm every constituent's tags at DAILY, resumably.

    The unit is the BOND, and the resume key is the window and value set - not
    the alias list. That is deliberate and it is the property that makes a
    narrowed ``--aliases`` free: a tag warmed for ``CT2``'s 2019 constituent is
    the same tag whatever asked for it, so re-running with a different alias set
    re-fetches only what is genuinely new.
    """
    from MDP.CitiVelocityExcel.bonds.fetcher import CitiVeloBondFetcher
    from MDP.CitiVelocityExcel.memory_guard import assert_safe_to_connect

    # BEFORE anything that can connect. A guard placed after client() has already
    # done the thing it exists to prevent.
    mem0 = assert_safe_to_connect(ceiling_mb, what="the UST timeseries tag fetch")

    man = _load_manifest()
    book = man.setdefault("fetch", {})
    stamp = _key(plan.start, plan.end, plan.values)

    resolutions = plan.resolutions()
    at_this_window = sum(1 for r in resolutions if book.get(r.isin, {}).get("key") == stamp)
    todo = resolutions if force else [r for r in resolutions if book.get(r.isin, {}).get("key") != stamp]
    if limit:
        todo = todo[:limit]

    log.info(
        "fetch: %d bonds to do, %d/%d already warm at THIS window, values=%s, %s..%s, "
        "Excel %.0f MB, ceiling %.0f",
        len(todo), at_this_window, len(resolutions), ",".join(plan.values),
        plan.start, plan.end, mem0, ceiling_mb,
    )
    if not todo:
        log.info("  nothing to do - the manifest says this window is fully fetched")
        return {"phase": "fetch", "done": 0, "of": 0, "tags": 0, "stopped": False, "reason": ""}

    fetcher = CitiVeloBondFetcher()
    done = tags_done = 0
    stopped = ""
    t0 = time.perf_counter()
    try:
        for i in range(0, len(todo), batch):
            chunk = todo[i:i + batch]

            mem = _memory_now()
            if mem is None:
                stopped = (
                    "could not read Excel's memory - the probe timed out, PowerShell was "
                    "unavailable, or its output was unparseable. That says NOTHING about "
                    "what is running, so this fails closed."
                )
                log.warning("STOPPING: %s", stopped)
                break
            if mem >= ceiling_mb:
                stopped = f"Excel reached {mem:.0f} MB (ceiling {ceiling_mb:.0f})"
                log.warning("STOPPING: %s - rerun after a human restarts Excel", stopped)
                break

            entries = fetcher.plan(chunk, values=plan.values)
            tags = [t for e in entries.values() for t in e["tags"].values()]
            if not tags:
                for r in chunk:
                    book[r.isin] = {"key": stamp, "tags": 0, "note": "serves none of these values"}
                continue

            try:
                result = fetcher.prefetch(
                    chunk, plan.start, plan.end,
                    mode="eod", values=plan.values, lookback=datetime.timedelta(0),
                )
            except Exception as exc:  # noqa: BLE001 - one bad batch must not lose the rest
                stopped = f"{type(exc).__name__}: {exc}"
                log.warning("STOPPING at batch %d: %s", i // batch, stopped[:200])
                break

            # A warm is the file on disk, not the call returning. `result.ok` is
            # already data-bearing, but it is derived from what the transport
            # reported; the cache is asked separately because the failure this
            # guards against is precisely a transport that reports success and
            # persists nothing.
            landed = cached_tags("DAILY", tags)
            if landed == 0:
                stopped = (
                    f"batch {i // batch} fetched {len(tags)} tags without error and cached "
                    f"NONE of them - the transport is not writing to the tag cache"
                )
                log.error("STOPPING: %s (prefetch reported ok=%s)", stopped, result.ok)
                break

            for r in chunk:
                book[r.isin] = {
                    "key": stamp,
                    "tags": len(entries[r.isin]["tags"]),
                    "at": datetime.datetime.now().isoformat(timespec="seconds"),
                }
            done += len(chunk)
            tags_done += len(tags)
            _save_manifest(man)          # after EVERY batch: a stop costs one batch
            if (i // batch) % 5 == 0 or done >= len(todo):
                log.info("  %d/%d bonds, %d tags, Excel %.0f MB, %.0fs",
                         done, len(todo), tags_done, mem, time.perf_counter() - t0)
    finally:
        _save_manifest(man)
        fetcher.close()

    mem_end = _memory_now()
    log.info(
        "fetch finished: %d/%d bonds, %d tags, %.0fs, Excel %.0f -> %s MB%s",
        done, len(todo), tags_done, time.perf_counter() - t0, mem0,
        f"{mem_end:.0f}" if mem_end is not None else "?",
        f" (STOPPED: {stopped})" if stopped else "",
    )
    return {
        "phase": "fetch", "done": done, "of": len(todo), "tags": tags_done,
        "stopped": bool(stopped), "reason": stopped,
        "mem_before": mem0, "mem_after": mem_end,
    }


# ──────────────────────────────────────────────────────────────────────────
# Phase 2: BUILD - pure CPU, forced offline, no Excel is even reachable
# ──────────────────────────────────────────────────────────────────────────


def unified_values(values: Sequence[str]):
    """Citi value tokens -> ``UnifiedValue`` members, through the repo's own map.

    ``values.frb_value_for`` already owns this mapping and it is not the identity:
    ``PRICE`` is ``FRB_CLEAN_PRICE`` and ``YIELD`` is ``FRB_YTM``, and on this
    source ``YIELD`` and ``YTM`` are different numbers - the pricer is built from
    ``PRICE`` and re-solves its own yield. Deriving the pair here rather than
    hardcoding it is what stops the fetch and the build drifting onto different
    definitions of the same word.

    A Citi value with no ``UnifiedValue`` counterpart is FETCHED and not BUILT,
    and says so, because the tag is still worth having in the cache.
    """
    from MDP.CitiVelocityExcel.bonds.values import frb_value_for
    from Query.Unified.registry import UnifiedValue

    out = []
    for citi in values:
        frb = None
        try:
            frb = frb_value_for(citi)
        except Exception:  # noqa: BLE001 - an unknown token is a skip, not a crash
            frb = None
        member = getattr(UnifiedValue, f"FRB_{frb}", None) if frb else None
        if member is None:
            log.info("  %s has no UnifiedValue counterpart; fetched but not built", citi)
            continue
        out.append((citi, member))
    return out


def _mdp(universe):
    """A Velocity FRB provider that CANNOT open Excel.

    ``offline`` is given to the constructor, not to a request, because a
    ``TimeseriesBuilder`` run has no way to pass request kwargs -
    ``TB.FixedRateBondsTB`` calls ``bulk_get_data`` with a fixed signature. Set
    at the constructor it reaches both the range prefetch (which is skipped
    outright) and every per-point read.

    ``citivelo_universe`` is what makes the matured constituents reachable at
    all. Without it ``resolve_bonds`` consults the committed catalog - today's
    349 names - and drops every bond that has redeemed, which over ten years is
    290 of the 597 the aliases pass through. The build would then succeed, and be
    empty on exactly the dates that motivated the backfill.
    """
    from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP

    return FixedRateBondsMDP(
        source="USTS_CITIVELO-RL", offline=True, citivelo_universe=universe
    )


def build_pairs(plan):
    """The ``(label, UnifiedValue)`` list the build phase will compute.

    Module level for the same reason as :func:`build_unit_key`: inline, the only
    way to check it was to call ``build`` with a market data provider, so a
    mutation that ignored ``plan.build_values`` and fell back to deriving two
    values from the fetch set passed the whole suite.

    An explicit ``build_values`` wins; without one this derives from the fetch
    tokens, which is the pre-existing behaviour and only ever yields
    ``FRB_CLEAN_PRICE`` and ``FRB_YTM``.
    """
    if getattr(plan, "build_values", None):
        from Query.Unified.registry import UnifiedValue

        pairs = []
        for name in plan.build_values:
            member = getattr(UnifiedValue, name, None)
            if member is None:
                raise ValueError(f"{name!r} is not a UnifiedValue member")
            pairs.append((name, member))
        return pairs
    return unified_values(plan.values)


def build_unit_key(plan, symbol: str, year: int, lo, hi):
    """The manifest key for one build unit: ``(unit, stamp)``.

    Module level rather than a closure inside :func:`build` so a test can drive
    the real thing. The version that lived inside it could only be checked by
    calling ``_key`` directly with two different tuples, which asserts that
    ``_key`` reads its argument - not that the caller passes the right one. That
    test survived deleting the build values from the key.

    The BUILD values are in the stamp, not just the fetch values. Widening the
    built set without this reads the manifest, finds every unit already at the
    right key, does nothing, and reports a ten-value warm holding two - the same
    silence :func:`_key` already documents for the window.
    """
    return (
        f"{symbol}@{year}",
        _key(lo, hi, tuple(plan.values) + tuple(plan.build_values or ())),
    )


def build(
    plan: WarmPlan,
    *,
    batch: int = DEFAULT_BUILD_BATCH,
    force: bool = False,
    limit: Optional[int] = None,
    n_jobs: int = DEFAULT_JOBS,
) -> dict:
    """Price every symbol into the computed TS store, a calendar year at a time.

    Touches no Excel and does not gate on it: the whole point of the split is
    that this half can run on a machine with no add-in, after a session was lost,
    or twice.
    """
    from Query.Unified.UnifiedQuery import UnifiedQuery
    from TB.FixedRateBondsTB import FixedRateBondsTB
    from TB.TimeseriesBuilder import TimeseriesBuilder

    pairs = build_pairs(plan)
    if not pairs:
        raise ValueError(
            f"None of {list(plan.values)} maps onto a UnifiedValue, so there is nothing to "
            f"build. Citi tokens map through MDP.CitiVelocityExcel.bonds.values.frb_value_for."
        )
    wanted = [member for _, member in pairs]

    man = _load_manifest()
    book = man.setdefault("build", {})

    # One flat list of (symbol, year, lo, hi) so the batching and the manifest
    # agree about what a unit is.
    units: List[Tuple[str, int, datetime.date, datetime.date]] = []
    for symbol in plan.symbols():
        for year, lo, hi in plan.slices(symbol):
            units.append((symbol, year, lo, hi))

    def _unit_key(symbol, year, lo, hi):
        return build_unit_key(plan, symbol, year, lo, hi)

    todo = []
    already = 0
    for symbol, year, lo, hi in units:
        unit, stamp = _unit_key(symbol, year, lo, hi)
        if not force and book.get(unit, {}).get("key") == stamp:
            already += 1
            continue
        todo.append((symbol, year, lo, hi))
    if limit:
        todo = todo[:limit]

    log.info(
        "build: %d (symbol, year) slices to do, %d already done at this key, "
        "%d symbols, values=%s",
        len(todo), already, len(plan.symbols()),
        ",".join(f"{c}->{m.name}" for c, m in pairs),
    )
    if not todo:
        return {"phase": "build", "done": 0, "of": 0, "rows": 0, "stopped": False, "reason": ""}

    mdp = _mdp(plan.universe())
    tb = TimeseriesBuilder()
    router = {"FRB": FixedRateBondsTB(mdp, show_tqdm=True)}

    # Group by (year, lo, hi) so one TimeseriesBuilder call covers many symbols.
    grouped: Dict[Tuple[int, datetime.date, datetime.date], List[str]] = {}
    for symbol, year, lo, hi in todo:
        grouped.setdefault((year, lo, hi), []).append(symbol)

    done = rows = 0
    stopped = ""
    t0 = time.perf_counter()
    try:
        for (year, lo, hi), symbols in sorted(grouped.items()):
            for i in range(0, len(symbols), batch):
                chunk = symbols[i:i + batch]
                queries = [
                    UnifiedQuery(cusip=s, value=v) for s in chunk for v in wanted
                ]
                try:
                    frame = tb.get_timeseries(
                        start=lo, end=hi, queries=queries, n_jobs=n_jobs,
                        routers=router, ignore_cache_miss=True,
                    )
                except Exception as exc:  # noqa: BLE001
                    stopped = f"{type(exc).__name__}: {exc}"
                    log.warning("STOPPING at %s %s: %s", year, chunk[:3], stopped[:200])
                    break

                n = 0 if frame is None else int(getattr(frame, "size", 0))
                for s in chunk:
                    unit, stamp = _unit_key(s, year, lo, hi)
                    book[unit] = {
                        "key": stamp,
                        "rows": n // max(1, len(chunk)),
                        "at": datetime.datetime.now().isoformat(timespec="seconds"),
                    }
                done += len(chunk)
                rows += n
                _save_manifest(man)      # after EVERY batch
                log.info("  %d: %d symbols, %d cells, %.0fs total",
                         year, done, rows, time.perf_counter() - t0)
            if stopped:
                break
    finally:
        _save_manifest(man)

    log.info(
        "build finished: %d/%d slices, %d cells, %.0fs%s",
        done, len(todo), rows, time.perf_counter() - t0,
        f" (STOPPED: {stopped})" if stopped else "",
    )
    return {
        "phase": "build", "done": done, "of": len(todo), "rows": rows,
        "stopped": bool(stopped), "reason": stopped,
    }


# ──────────────────────────────────────────────────────────────────────────
# Reporting
# ──────────────────────────────────────────────────────────────────────────


def status(plan: WarmPlan) -> None:
    """What the manifest says, and what it would still cost. Touches no Excel."""
    man = _load_manifest()
    stamp = _key(plan.start, plan.end, plan.values)

    print(f"manifest: {MANIFEST}")
    print(plan.describe())

    fetch_book = man.get("fetch", {})
    at_window = sum(1 for i in plan.isins if fetch_book.get(i, {}).get("key") == stamp)
    print(f"\n  fetch: {at_window}/{len(plan.isins)} bonds at THIS window "
          f"({len(fetch_book)} in the manifest overall)")

    build_book = man.get("build", {})
    total = done = 0
    per_symbol: Dict[str, Tuple[int, int]] = {}
    for symbol in plan.symbols():
        s_total = s_done = 0
        for year, lo, hi in plan.slices(symbol):
            s_total += 1
            if build_book.get(f"{symbol}@{year}", {}).get("key") == _key(lo, hi, plan.values):
                s_done += 1
        total += s_total
        done += s_done
        per_symbol[symbol] = (s_done, s_total)
    print(f"  build: {done}/{total} (symbol, year) slices at THIS key "
          f"({len(build_book)} in the manifest overall)")

    print("\n  aliases:")
    for alias in plan.aliases:
        track = plan.history.get(alias)
        d, t = per_symbol.get(alias, (0, 0))
        described = track.describe() if track is not None else f"{alias}: not alias-shaped"
        print(f"    {alias:<6} {described:<70} build {d}/{t}")


def _parse_cusips(raw: Optional[Sequence[str]]) -> Tuple[str, ...]:
    """``--cusips``: default the whole listed universe, ``none`` for aliases only.

    Also accepts ``@path`` so a hand-picked basket can live in a file rather than
    on a command line Windows would truncate.
    """
    if raw is None:
        return catalog_cusips()
    tokens: List[str] = []
    for item in raw:
        text = str(item).strip()
        if text.lower() in ("none", "-", ""):
            return ()
        if text.lower() == "all":
            return catalog_cusips()
        if text.startswith("@"):
            tokens.extend(
                line.strip()
                for line in pathlib.Path(text[1:]).read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.strip().startswith("#")
            )
            continue
        tokens.extend(part.strip() for part in text.split(",") if part.strip())
    return tuple(dict.fromkeys(t.upper() for t in tokens))


def main(argv: Optional[Sequence[str]] = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                        datefmt="%H:%M:%S")
    p = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    # ``status`` is both a phase and a flag, so ``... build --status`` reports on
    # the request it would run rather than making you retype the window.
    p.add_argument("phase", choices=["plan", "fetch", "build", "status"])
    p.add_argument("--status", action="store_true",
                   help="report on this request and exit, whatever phase was named")
    p.add_argument("--years", type=float, default=10.0, help="history depth (default 10)")
    p.add_argument("--end", type=datetime.date.fromisoformat, default=None)
    p.add_argument("--values", nargs="*", default=None,
                   help=f"Citi value tokens (default {' '.join(DEFAULT_VALUES)})")
    p.add_argument("--aliases", nargs="*", default=None,
                   help="constant-maturity aliases (default the 28 CT/O/OO/OOO x 2..30)")
    p.add_argument("--cusips", nargs="*", default=None,
                   help="specific issues: CUSIPs/ISINs, @file, 'all' (the listed universe, "
                        "the default) or 'none'")
    p.add_argument("--batch", type=int, default=None)
    p.add_argument("--ceiling-mb", type=float, default=WORKING_CEILING_MB)
    p.add_argument("--limit", type=int, default=None, help="only the first N units (a smoke run)")
    p.add_argument("--jobs", type=int, default=DEFAULT_JOBS)
    p.add_argument("--force", action="store_true", help="redo units the manifest calls done")
    args = p.parse_args(argv)

    end = args.end or datetime.date.today()
    start = end - datetime.timedelta(days=int(args.years * 365.25))
    plan = WarmPlan(
        start=start, end=end,
        aliases=args.aliases if args.aliases is not None else default_aliases(),
        cusips=_parse_cusips(args.cusips),
        values=tuple(args.values) if args.values else DEFAULT_VALUES,
    )

    if args.phase == "plan":
        print(plan.describe())
        return
    if args.phase == "status" or args.status:
        status(plan)
        return
    if args.phase == "fetch":
        out = fetch(plan, batch=args.batch or DEFAULT_FETCH_BATCH,
                    ceiling_mb=args.ceiling_mb, force=args.force, limit=args.limit)
    else:
        out = build(plan, batch=args.batch or DEFAULT_BUILD_BATCH,
                    force=args.force, limit=args.limit, n_jobs=args.jobs)

    if out.get("stopped"):
        # A partial warm is a real outcome, not a failure to hide: exit non-zero so
        # a scheduled task's summary shows it, but the manifest keeps the progress.
        sys.exit(2)


if __name__ == "__main__":
    main()
