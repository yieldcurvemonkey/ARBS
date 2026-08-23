r"""Warm the Citi Velocity swaption vol history, then build the cube store from it.

Two phases, deliberately separable, because they fail for different reasons and
only one of them can hurt anybody.

``fetch``
    Pull the ``RATES.VOL.<ccy>`` tag grid into the :class:`CitiVeloTagCache`.
    This is the only phase that touches Excel. It is chunked by strike offset,
    checks the add-in's memory between chunks, and aborts cleanly at
    ``--memory-abort-mb`` rather than pushing a 3-4 GB process over the edge -
    the add-in's cache only ever grows and only a HUMAN restart clears it.
``build``
    Assemble one :class:`SwaptionCubeData` per observation date out of the cached
    quotes and write it into the store. Pure local work: no Excel, no network.

Splitting them is what makes the whole thing resumable. The tag cache is
incremental (``missing_spans``), so a re-run of ``fetch`` asks only for what it
does not already have, and ``build`` can run at any time against whatever has
landed so far - including after the add-in has died.

The offset groups are ordered by how much they are worth, so an abort leaves
something usable rather than a random third of a surface:

1. ``atm``       - the ATM surface alone is a complete, priceable cube
2. ``+/-25,50``  - the liquid smile
3. ``+/-75,100`` - the wings people actually quote
4. ``+/-10,200`` - the tails

Run from the repo root::

    <env>/python.exe scripts/citivelo_swaption_vol_warm.py fetch --years 7
    <env>/python.exe scripts/citivelo_swaption_vol_warm.py build
    <env>/python.exe scripts/citivelo_swaption_vol_warm.py status
"""

from __future__ import annotations

import argparse
import datetime
import logging
import math
import os
import pathlib
import sys
import time
from typing import Dict, List, Optional, Sequence, Tuple

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pandas as pd  # noqa: E402

_logger = logging.getLogger("citivelo_swaption_vol_warm")

#: Strike-offset groups, most valuable first. See the module docstring.
OFFSET_GROUPS: Tuple[Tuple[str, Tuple[float, ...]], ...] = (
    ("atm", ()),
    ("liquid", (-25.0, 25.0, -50.0, 50.0)),
    ("wings", (-100.0, 100.0, -75.0, 75.0)),
    ("tails", (-200.0, 200.0, -10.0, 10.0)),
)

#: Stop asking Excel for more once it is this large. The add-in's own cache grows
#: with everything it has served and is never released; a spawned Excel cannot
#: replace it because it would not register the CV* UDFs. Leaving headroom is the
#: difference between "resume tomorrow" and "the user has to restart Excel".
DEFAULT_MEMORY_ABORT_MB = 6000


def _excel_memory_mb() -> Optional[float]:
    """Resident size of the running Excel, or None if it cannot be read."""
    try:
        import subprocess

        out = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "(Get-Process EXCEL -ErrorAction SilentlyContinue | "
                "Measure-Object WorkingSet64 -Sum).Sum",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        raw = (out.stdout or "").strip()
        return float(raw) / 1e6 if raw else None
    except Exception:  # noqa: BLE001 - a missing probe must not stop the warm
        return None


def _tags_for(currency: str, offsets: Sequence[float]) -> Dict[str, tuple]:
    from MDP.CitiVelocityExcel.vol.cube_data import cube_tags

    return cube_tags(currency=currency, offsets_bp=list(offsets))


# ------------------------------------------------------------------ #
#                              fetch                                 #
# ------------------------------------------------------------------ #


def fetch(
    *,
    currency: str,
    years: float,
    groups: Sequence[str],
    memory_abort_mb: float,
    freq: str = "DAILY",
) -> int:
    """Pull the vol tag grid into the tag cache. The only phase that uses Excel."""
    from MDP.CitiVelocityExcel.cache import CitiVeloTagCache
    from MDP.CitiVelocityExcel.quotes import CitiVeloQuotes

    end = datetime.date.today()
    start = end - datetime.timedelta(days=int(round(365.25 * years)))
    cache = CitiVeloTagCache()
    quotes = CitiVeloQuotes(cache=cache)

    baseline = _excel_memory_mb()
    _logger.warning(
        "fetch: %s %.1fy (%s .. %s); Excel at %s MB, abort at %.0f MB",
        currency, years, start, end,
        f"{baseline:.0f}" if baseline else "unknown",
        memory_abort_mb,
    )

    done, aborted = [], False
    try:
        for name, offsets in OFFSET_GROUPS:
            if groups and name not in groups:
                continue
            mem = _excel_memory_mb()
            if mem is not None and mem >= memory_abort_mb:
                _logger.warning(
                    "fetch: ABORTING before group %r - Excel is at %.0f MB (limit %.0f). "
                    "Everything already fetched is cached and the next run resumes here.",
                    name, mem, memory_abort_mb,
                )
                aborted = True
                break

            # cube_tags returns ATM + the requested offsets; for a non-ATM group
            # drop the ATM tags, which the 'atm' group already covers.
            tag_map = _tags_for(currency, offsets)
            tags = [t for t, meta in tag_map.items() if name == "atm" or meta[0] == "OTM"]
            if not tags:
                continue

            t0 = time.time()
            _logger.warning(
                "fetch: group %r - %d tags, ~%d CVTSHIST call(s), Excel at %s MB",
                name, len(tags), math.ceil(len(tags) / 44),
                f"{mem:.0f}" if mem else "unknown",
            )
            frame = quotes.frame(tags, freq, start=start, end=end)
            served = 0 if frame is None or frame.empty else int(frame.notna().any().sum())
            after = _excel_memory_mb()
            _logger.warning(
                "fetch: group %r DONE - %d/%d tags served, %s rows, %.0fs, Excel %s MB (%s)",
                name, served, len(tags),
                0 if frame is None or frame.empty else len(frame),
                time.time() - t0,
                f"{after:.0f}" if after else "unknown",
                f"{after - mem:+.0f} MB" if (after and mem) else "delta unknown",
            )
            done.append(name)
    finally:
        try:
            quotes.close()
        except Exception:  # noqa: BLE001
            pass

    _logger.warning("fetch: groups completed %s%s", done, " (ABORTED early)" if aborted else "")
    return 0 if done else 1


# ------------------------------------------------------------------ #
#                              build                                 #
# ------------------------------------------------------------------ #



def _cube_rank(candidate: Tuple[int, int, object]) -> Tuple[int, int]:
    """Rank key: expiry x tenor COVERAGE first, smile richness only as a tie-break."""
    nodes, n_offsets, _ = candidate
    return (int(nodes), int(n_offsets))


#: How much of the widest ATM rectangle a SMILE cube may give up and still win.
#:
#: Coverage-beats-smile was the right correction and it is kept; what it lacked
#: was a sense of proportion. See :func:`pick_widest_cube`.
SMILE_COVERAGE_FLOOR = float(os.environ.get("ARBS_CITIVELO_SMILE_COVERAGE_FLOOR", "0.75"))


def pick_widest_cube(candidates: Sequence[Tuple[int, int, object]]):
    """Choose among successfully-built cubes for one day.

    ``candidates`` is ``[(atm_node_count, n_offsets, cube), ...]``.

    COVERAGE STILL BEATS SMILE, but only when the coverage is actually at stake.

    The warm used to try the full offset grid first and take the first build that succeeded,
    whatever survived. That ranks a day by smile richness when what matters is which part of
    the curve you can price at all, and it cost the short end for 59 consecutive stored days --
    2020-01-24 to 2020-04-21, exactly across COVID. On 2020-03-09 it preferred a 1 expiry x 5
    tenor cube (65 nodes, minimum expiry 15Y) over the full 17 x 9 ATM surface; on 2026-08-12 it
    preferred 2 nodes over 153.

    The cause is structural rather than a run of bad days: the rectangle search requires EVERY
    offset present, and a 1Y option has no -200bp strike when rates are ~1.5%, so one
    structurally unquotable wing amputates a whole expiry row.

    THE PLAIN MAXIMUM WAS TOO ABSOLUTE, and it cost every smile on the current
    week. Measured 2026-08-17..08-21: the full-offset grid drops tenors 4Y and
    12Y for incomplete quotes, giving a 136-cell ATM rectangle against the
    ATM-only build's 153. So ``153 > 136`` and the ATM-only cube won every day --
    trading **17 extra ATM cells for 1,632 smile quotes** (136 x 12 offsets),
    and leaving ``citivelo_swaption_eod_warm`` with nothing to price, since its
    manifest is mostly ATMF+/-25 payers, receivers, strangles, risk reversals,
    1x2s and ladders. All of those need the wings.

    The floor restores proportion. A smile cube wins if it keeps at least
    :data:`SMILE_COVERAGE_FLOOR` of the widest rectangle:

    ===========  ==========  ==========  ==============================
    day          smile ATM   widest ATM  outcome
    ===========  ==========  ==========  ==============================
    2026-08-21          136         153  136/153 = 89%  -> SMILE wins
    2020-03-09           65         153   65/153 = 42%  -> ATM-only wins
    2026-08-12            2         153    2/153 =  1%  -> ATM-only wins
    ===========  ==========  ==========  ==============================

    which is exactly the separation the COVID measurement asked for. Anything
    that amputates the short end fails the floor by a wide margin; losing two
    long tenors does not.
    """
    if not candidates:
        return None
    widest = max(candidates, key=_cube_rank)
    smiles = [c for c in candidates if int(c[1]) > 0]
    if not smiles or int(widest[1]) > 0:
        return widest[2]
    richest = max(smiles, key=_cube_rank)
    if widest[0] > 0 and (richest[0] / widest[0]) >= SMILE_COVERAGE_FLOOR:
        return richest[2]
    return widest[2]


def build(
    *,
    currency: str,
    citi_index: str,
    overwrite: bool,
    max_days: Optional[int] = None,
    freq: str = "DAILY",
    atm_fallback: bool = True,
    push_l2: bool = False,
    start: Optional[datetime.date] = None,
    end: Optional[datetime.date] = None,
) -> int:
    """Assemble one cube per observation date from the CACHE. No Excel, no network.

    ``start``/``end`` bound the rebuild. Without them a repair of a handful of days means
    rebuilding all 2,702, which is slow enough that it does not get done.
    """
    from Caching.swaption_cube_store import SwaptionCubeStore, asset_for
    from MDP.CitiVelocityExcel.cache import CitiVeloTagCache
    from MDP.CitiVelocityExcel.vol.cube_data import (
        DEFAULT_OFFSETS_BP,
        RaggedCubeError,
        cube_from_quotes,
    )

    cache = CitiVeloTagCache()
    tag_map = _tags_for(currency, list(DEFAULT_OFFSETS_BP))

    # L2 is opt-in and read at CALL time, so this flag works even though nothing
    # set an env var before the first Caching import - which is exactly what made
    # citivelo_excel_warm.py's --push-l2 a dead flag for its whole life.
    if push_l2:
        from Caching.l2_policy import SWAPTION_CUBE_L2_ENV

        _logger.warning(
            "--push-l2: each written cube is also pushed to %s. For a bulk backfill "
            "prefer scripts/citivelo_l2_sync.py --families cube, which diffs by "
            "content. (%s is not required when the flag is passed.)",
            "arbs_swaption_cube_blocks_v1", SWAPTION_CUBE_L2_ENV,
        )

    # Read every cached tag once; a date is buildable when its row is complete
    # enough for cube_from_quotes(strict=False) to keep a rectangle.
    series: Dict[str, pd.Series] = {}
    for tag in tag_map:
        s = cache.read(tag, freq)
        if s is not None and not s.empty:
            series[tag] = s
    if not series:
        _logger.error("build: no RATES.VOL tags are cached. Run the fetch phase first.")
        return 1

    frame = pd.DataFrame(series).sort_index()
    store = SwaptionCubeStore.default()
    asset = asset_for(currency)
    _logger.warning(
        "build: %d cached tags, %d dates (%s .. %s) -> asset %s",
        frame.shape[1], len(frame), frame.index.min().date(), frame.index.max().date(), asset,
    )

    written = skipped = failed = 0
    last_exc: Optional[BaseException] = None
    dates = list(frame.index)
    if start is not None:
        dates = [d for d in dates if (d.date() if hasattr(d, "date") else d) >= start]
    if end is not None:
        dates = [d for d in dates if (d.date() if hasattr(d, "date") else d) <= end]
    if max_days:
        dates = dates[-int(max_days):]
    for stamp in dates:
        as_of = stamp.date() if hasattr(stamp, "date") else stamp
        if not overwrite and store.has_day(asset, as_of):
            skipped += 1
            continue
        row = frame.loc[stamp].dropna()
        # An exact 0.0 is a PLACEHOLDER, not a quote. Citi serves them on the
        # corners of the grid that were not quoted that day, and they are finite,
        # so cube_from_quotes keeps them and assert_vol_units then rejects the
        # whole day - measured, 174 days of early history lost to a handful of
        # zeros each. A normal swaption vol cannot be 0.0 bp (the plausible band
        # starts at 0.5), so dropping them here is the same judgement the units
        # guard makes, applied at the node instead of the day. strict=False then
        # keeps the largest complete rectangle.
        row = row[row != 0.0]
        if row.empty:
            continue
        # Build every candidate shape and keep the one with the LARGEST expiry x tenor
        # coverage, breaking ties toward the richer smile.
        #
        # This used to try the full offset grid first and `break` on the first success,
        # whatever survived. That ordering ranks a day by smile richness when the thing
        # that matters is axis coverage, and it lost the short end of the curve for 59
        # consecutive stored days -- 2020-01-24 to 2020-04-21, i.e. exactly across COVID.
        # Measured: on 2020-01-24 the 13-offset grid yielded 8 expiries x 9 tenors with a
        # minimum expiry of 4Y and that won, while the ATM-only build would have given the
        # full 17 x 9 from 1M. On 2020-03-09 the winner was 1 expiry x 5 tenors; on 2026-08-12,
        # 1 x 2. The rank below is the ATM RECTANGLE (expiries x tenors), not the cube's total
        # number of quotes -- 8 x 9 x 13 is 936 numbers against the ATM surface's 153, so ranking
        # by total would have kept the truncated axis and changed nothing.
        #
        # The cause is structural, not a bad day: `_drop_incomplete`/`_largest_rectangle`
        # needs EVERY offset present, and a 1Y option has no -200bp strike when rates are
        # ~1.5%, so one structurally unquotable wing amputates a whole expiry row. The
        # rectangle search maximises area over a sparse mask, which is why the orientation
        # flips between dropping expiries and dropping tenors, and why the shape wobbles
        # day to day. Ranking by coverage makes that irrelevant.
        #
        # The data was never missing upstream: all 2,702 stored days -- including all 60
        # degraded ones -- hold a complete 17 x 9 ATM surface in the tag cache, so the 59
        # days are recoverable offline with `--overwrite`.
        candidates: list[tuple[int, int, object]] = []
        for offsets, tag in (
            (list(DEFAULT_OFFSETS_BP), ""),
            # Citi's OTM skew history is shorter than its ATM history: before
            # 2020-01-24 there is no expiry x tenor rectangle for which all
            # twelve offsets were served, so the full grid has nothing to build.
            # Those days DO have an ATM surface, and an ATM-only cube is a
            # complete, priceable one - so fall back rather than leave a hole,
            # and record the shape in `source` so a reader can tell the two
            # apart without inspecting the axes.
            ((), "/atm_only") if atm_fallback else (None, None),
        ):
            if offsets is None:
                continue
            try:
                built = cube_from_quotes(
                    quotes=row.to_dict(),
                    currency=currency,
                    as_of=as_of,
                    offsets_bp=list(offsets),
                    served_unit="bp",
                    strict=False,
                    source=f"citivelo_excel_warm/{freq}{tag}",
                )
            except (RaggedCubeError, ValueError, KeyError) as exc:
                last_exc = exc
                continue
            candidates.append((int(built.atm.size), len(offsets), built))

        cube = pick_widest_cube(candidates)
        if len(candidates) > 1 and cube is not None:
            # Report the CHOICE, not the comparison. This line used to say
            # "coverage wins" whenever the widest candidate was wider, which
            # stopped being the same thing once the smile floor existed - and a
            # log that describes a decision the code did not make is worse than
            # no log.
            chosen = next((c for c in candidates if c[2] is cube), None)
            widest = max(candidates, key=_cube_rank)
            if chosen is not None and chosen[0] != widest[0]:
                _logger.info(
                    "build: %s kept the SMILE - %d ATM cells x %d offsets over a wider "
                    "%d-cell ATM-only surface (%.0f%% of it, floor %.0f%%)",
                    as_of, chosen[0], chosen[1], widest[0],
                    100.0 * chosen[0] / widest[0], 100.0 * SMILE_COVERAGE_FLOOR,
                )
            elif chosen is not None and chosen[1] == 0:
                other = max((c for c in candidates if c[1] > 0), key=_cube_rank, default=None)
                if other is not None and widest[0] > other[0]:
                    _logger.info(
                        "build: %s kept %d ATM cells (0 offsets) over %d cells (%d offsets) "
                        "- the smile keeps only %.0f%% of the surface, under the %.0f%% floor",
                        as_of, widest[0], other[0], other[1],
                        100.0 * other[0] / widest[0], 100.0 * SMILE_COVERAGE_FLOOR,
                    )
        if cube is None:
            # A day with too few served nodes is a real gap, not an error to
            # paper over. Skip it and say so; the store stays honest about which
            # days exist.
            _logger.info("build: %s unbuildable (%s: %s)", as_of, type(last_exc).__name__, last_exc)
            failed += 1
            continue
        store.write_day(
            asset, as_of, cube, citi_index=citi_index, overwrite=overwrite,
            push_l2=True if push_l2 else None,
        )
        written += 1
        if written % 100 == 0:
            _logger.warning("build: %d written, %d skipped, %d unbuildable", written, skipped, failed)

    _logger.warning(
        "build: DONE - %d written, %d already present, %d unbuildable", written, skipped, failed
    )
    return 0


def status(*, currency: str) -> int:
    """What is in the tag cache and what is in the store."""
    from Caching.swaption_cube_store import SwaptionCubeStore, asset_for
    from MDP.CitiVelocityExcel.cache import CitiVeloTagCache
    from MDP.CitiVelocityExcel.vol.cube_data import DEFAULT_OFFSETS_BP

    cache = CitiVeloTagCache()
    tag_map = _tags_for(currency, list(DEFAULT_OFFSETS_BP))
    cached = [t for t in tag_map if cache.read(t, "DAILY") is not None]
    print(f"tag cache : {len(cached)}/{len(tag_map)} {currency} vol tags")
    if cached:
        cov = cache.coverage(cached[0], "DAILY")
        print(f"            sample coverage: {cov}")

    store = SwaptionCubeStore.default()
    asset = asset_for(currency)
    days = store.available_dates(asset)
    print(f"cube store: asset {asset}, {len(days)} day(s)")
    if days:
        print(f"            {days[0]} .. {days[-1]}")
    print(f"            base_dir {store.base_dir}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__ or "")
    parser.add_argument("phase", choices=["fetch", "build", "status"])
    parser.add_argument("--currency", default="USD")
    parser.add_argument("--citi-index", default="USD_SOFR")
    parser.add_argument("--years", type=float, default=7.0)
    parser.add_argument(
        "--groups", default="", help="comma-separated subset of " + ",".join(g for g, _ in OFFSET_GROUPS)
    )
    parser.add_argument("--memory-abort-mb", type=float, default=DEFAULT_MEMORY_ABORT_MB)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--max-days", type=int, default=None)
    parser.add_argument("--start", default=None, help="build phase: earliest observation date (YYYY-MM-DD)")
    parser.add_argument("--end", default=None, help="build phase: latest observation date (YYYY-MM-DD)")
    parser.add_argument(
        "--push-l2",
        action="store_true",
        help="also push each written cube to the Supabase L2 tier "
             "(arbs_swaption_cube_blocks_v1). Off by default: the tier is opt-in, "
             "because get_database_url() resolves PRODUCTION credentials when "
             "nothing is configured.",
    )
    parser.add_argument(
        "--no-atm-fallback",
        action="store_true",
        help="do not fall back to an ATM-only cube on days with no full-smile rectangle",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout
    )
    groups = [g.strip() for g in args.groups.split(",") if g.strip()]

    if args.phase == "fetch":
        return fetch(
            currency=args.currency,
            years=args.years,
            groups=groups,
            memory_abort_mb=args.memory_abort_mb,
        )
    if args.phase == "build":
        return build(
            currency=args.currency,
            citi_index=args.citi_index,
            overwrite=args.overwrite,
            max_days=args.max_days,
            atm_fallback=not args.no_atm_fallback,
            push_l2=args.push_l2,
            start=datetime.date.fromisoformat(args.start) if args.start else None,
            end=datetime.date.fromisoformat(args.end) if args.end else None,
        )
    return status(currency=args.currency)


if __name__ == "__main__":
    raise SystemExit(main())
