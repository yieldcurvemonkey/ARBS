r"""Warm the WHOLE Citi Velocity US Treasury universe — EOD and intraday.

Citi is the truth source for these bonds, so the tag cache should hold all of
them rather than the fourteen on-the-run aliases the daily value jobs happen to
ask for. A warmed tag is what stops a later value request from falling through to
live Excel, and an unattended scheduled task is exactly where that must not
happen.

What the universe costs, measured 2026-08-08 rather than estimated
-----------------------------------------------------------------
**349 bonds, 2,302 EOD tags** (mean 6.6 per bond). Per-value coverage is uneven
and is read per bond, never assumed:

======================  ==========
value                   bonds
======================  ==========
``PRICE``                  349/349
``YIELD``                  349/349
``DURATION``               349/349
``SPREAD_TSY``             349/349
``ASW_4_AUD``              348/349
``DV01``                   305/349
``ASW_4_USD``              253/349
======================  ==========

**EOD is nearly free.** 52 tags over five years (1,249 rows) cost **+1 MB** of
Excel and 3.3 s. The whole universe is minutes and tens of megabytes.

**Intraday is dearer, and the cost depends entirely on which transport is used.**
The first ``MI01`` fetch costs **+952 MB** — that is one-time setup, and measuring
only that would have condemned the whole idea. Two marginal costs were then
measured, and the difference between them is why :func:`_warm_intraday` exists:

=========================================  ==============  ==================
transport                                  349 bonds       per tag
=========================================  ==============  ==================
``fetch_windowed`` (a sheet per window)    134 s, +971 MB  ~1.7 MB
``CitiVeloQuotes.frame`` (this script)      48 s, +170 MB  ~0.24 MB
=========================================  ==============  ==================

The chunker pushes and drops a worksheet per window per batch; the cached path
sends one batched ``CVTSHIST`` per window. **5.7× cheaper and it actually caches**
— the windowed transport writes nothing to the tag cache at all, which is the bug
recorded on :func:`_warm_intraday`.

At the measured 0.24 MB/tag, ``PRICE`` + ``YIELD`` for all 349 bonds (698 tags) is
**~170 MB**, and the full seven-value set (2,302 tags) projects to **~560 MB** —
which would fit, though it has not been run. The default stays at two values
because that is what has been measured end to end; widen with ``--values`` when
someone is watching, and it will stop at the ceiling and resume either way.

``recycle_workbook()`` does **not** give memory back: measured on the same run it
returned ``True`` and memory went **up 7 MB**. Only a human restart shrinks the
process, which is why this script stops rather than pushes.

Stop and resume, because a lost session must cost time and not data
-------------------------------------------------------------------
Progress is written to a manifest after **every batch**. A run that stops - at the
ceiling, on a COM error, or because someone closed Excel - loses at most the batch
in flight, and the next run skips everything already done. That is what makes
"warm the entire universe" a thing you can finish across several sessions instead
of one heroic pass that must not fail.

An outage and a matured bond are the same observation until you ask
-------------------------------------------------------------------
``CitiVeloQuotes.frame`` returns an EMPTY FRAME and raises NOTHING both when every
tag in the request failed and when every tag legitimately held no rows - its own
docstring says a failed tag "is simply an absent COLUMN here, which is
indistinguishable from a tag that returned no rows unless the reasons are asked
for". Both cases are real here: 528 of the 877 catalogued bonds have matured, and
Velocity does go away.

Conflating them has now cost this warm in both directions. Calling "no rows" a
fault aborted the whole 877-bond intraday warm at 0/877 on five of ten retained
nightly runs. Calling a fault "no rows" is worse and silent: measured against a
dead transport, the warm stamped 877 bonds done, warmed 0, returned
``stopped=False`` - so the job wrapper did not raise, the warmer exited 0, and the
stamped manifest blocked the same-day re-run that would have recovered the day.

So the reasons ARE asked for, through ``failures=``, and
:data:`BENIGN_FAILURE_REASONS` is the line between them.

Usage
-----
::

    python scripts/citivelo_ust_universe_warm.py eod
    python scripts/citivelo_ust_universe_warm.py intraday --days 2
    python scripts/citivelo_ust_universe_warm.py eod --years 10 --force
    python scripts/citivelo_ust_universe_warm.py status
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
from typing import Dict, List, Optional, Sequence

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

log = logging.getLogger("citivelo-ust-warm")

def _manifest_path() -> pathlib.Path:
    """Where progress lives: beside the TAG CACHE, not in the repo.

    It describes what THIS MACHINE's cache holds, which is not a property of the
    codebase — and it is rewritten after every batch by a nightly scheduled task
    running against the primary checkout. A tracked file in that position leaves
    the user's working tree dirty every morning with a change nobody made and
    nobody commits, which is precisely the state that makes a real edit
    invisible.
    """
    from MDP.CitiVelocityExcel.cache import default_cache_dir

    return default_cache_dir() / "ust_universe_warm_manifest.json"


MANIFEST = _manifest_path()

#: Leave headroom below the hard 3,800 MB ceiling so a batch in flight cannot
#: cross it. One intraday batch is ~14 MB, so 300 MB is ~20 batches of slack.
WORKING_CEILING_MB = 3500.0

#: Intraday defaults to the two values EVERY bond serves. Measured on the cached
#: transport at ~0.24 MB/tag, so 698 tags is ~170 MB; the full 2,302-tag set
#: projects to ~560 MB and would fit, but has not been run end to end. Two values
#: is what is measured, so two values is the default.
INTRADAY_VALUES = ("PRICE", "YIELD")

#: Bonds per batch. Small enough that the manifest is fine-grained and a stop
#: loses little; large enough that per-call overhead is not the cost.
DEFAULT_BATCH = 8

#: Per-tag failure reasons that mean "the add-in ANSWERED for this column, and
#: the answer was that there is nothing here". These are not a transport fault
#: and must not stop the warm.
#:
#: The split is by whether the add-in answered, not by whether the caller liked
#: the answer, and the reasons are the ones ``block_parser.parse_tshist_block``
#: actually writes (``block_parser.py:360, 365, 385``):
#:
#: ``"empty"``      the column came back with no rows in this window. Exactly
#:                  what an MI01 request against a bond that matured in 2016
#:                  returns, and 528 of the 877 catalogued bonds have matured.
#: ``"bad tag"``    the add-in replied ``Bad tag: ...`` in the column. A live
#:                  add-in rejecting one symbol, not a dead wire.
#: ``"no column"``  the block came back and this tag was not in it. Same.
#:
#: Everything else - ``"no block"``, ``"no header row"``, and any Excel error
#: NAME - means the request did not produce a readable block at all, which is
#: the signature of the outage this discriminates against: ``fetch_timeseries``
#: writes ``failures[tag] = excel_error_name(value) or "no block"`` for EVERY
#: tag in a chunk that came back with no rows (``com_client.py:968-971``).
#:
#: Unknown reasons fall in the STOP set on purpose. A reason nobody has seen is
#: not evidence that the wire is healthy, and this guard exists because the
#: previous version failed open. If nightly evidence ever shows a matured bond
#: producing a per-column Excel error name, demote that name here - with the
#: measurement, as everything else in this file is.
BENIGN_FAILURE_REASONS = frozenset({"empty", "bad tag", "no column"})


def _transport_faults(reported) -> Dict[str, str]:
    """The subset of ``{tag: reason}`` that means the transport did not answer."""
    if not reported:
        return {}
    return {
        str(tag): str(why)
        for tag, why in reported.items()
        if str(why).strip().lower() not in BENIGN_FAILURE_REASONS
    }


def _warm_intraday(
    quotes,
    tags: Sequence[str],
    *,
    start: datetime.date,
    end: datetime.date,
    failures: Optional[Dict[str, str]] = None,
) -> None:
    r"""Fetch ``MI01`` through the CACHE, in windows held under the cliff.

    This is deliberately NOT ``CitiVeloBondFetcher.fetch``. That is the right call
    to *read* an intraday quote - it routes through ``windowed.fetch_windowed``,
    which chunks under the cliff and verifies the spacing of every window - but it
    talks to ``quotes.client()`` directly, so nothing it fetches reaches the tag
    cache. Using it here warmed nothing: measured on the first run of this script,
    349 bonds and 698 tags "succeeded" in 134 s and left **zero** ``MI01``
    parquets on disk, while the manifest recorded 349/349 done. A warm that
    reports success and caches nothing is worse than one that fails.

    ``CitiVeloQuotes.frame`` does go through the cache, so this drives that
    instead and takes on the cliff obligation itself: ``CVTSHIST`` silently
    downsamples by requested SPAN, and the ``MI01`` threshold is measured at
    exactly 6 days (7 days returns 10-minute rows that look identical). Every
    request is bounded by ``MAX_SPAN["MI01"]``, so a caller asking for a month
    gets a month of true minutes in five cached requests rather than one
    downsampled block.

    The loop itself now lives in ``windowed.warm_windows``, because the intraday
    FRB read path needs exactly the same warm and a second copy of a bound whose
    whole value is that it is measured once is how the two drift apart.

    Returns the number of ROWS Velocity served across every window. The caller
    needs that number to tell the two things apart that the cache check alone
    cannot: a transport that fetched rows and persisted none (the real fault) and
    a window that legitimately held no rows at all (a matured bond). See the
    guard in :func:`warm`.

    ``failures`` is threaded through to :func:`warm_windows`, which merges the
    per-tag reasons across every window it issues. This used to be passed as
    ``None``, and passing ``None`` discarded the ONE piece of information that
    separates "Velocity has nothing for this window" from "Velocity answered
    nothing at all": ``frame`` returns an empty frame and raises nothing in both
    cases, so a total outage was byte-for-byte a batch of matured bonds. See the
    guard in :func:`warm` and :data:`BENIGN_FAILURE_REASONS`.
    """
    from MDP.CitiVelocityExcel.windowed import warm_windows

    windows = warm_windows(
        quotes,
        list(tags),
        "MI01",
        datetime.datetime.combine(start, datetime.time(0, 0)),
        datetime.datetime.combine(end, datetime.time(23, 59)),
        failures=failures,
    )
    return sum(int(w.n_rows) for w in windows)


def cached_tags(freq: str, tags: Sequence[str]) -> int:
    """How many of ``tags`` are actually on disk in the tag cache at ``freq``.

    The point of a warm is the file, not the fetch. This reads the cache
    directly rather than trusting a return value, because the bug this guards
    against is precisely a fetch that succeeds and persists nothing.
    """
    from MDP.CitiVelocityExcel.cache import default_cache_dir
    from MDP.CitiVelocityExcel.frequencies import normalise_frequency

    root = default_cache_dir() / normalise_frequency(freq)
    if not root.is_dir():
        return 0
    on_disk = {p.stem for p in root.rglob("*.parquet")}
    return sum(1 for t in tags if str(t) in on_disk)


class WarmCachedNothingError(RuntimeError):
    """A batch fetched without error and left nothing in the cache."""


def _load_manifest() -> dict:
    if MANIFEST.exists():
        try:
            return json.loads(MANIFEST.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - a corrupt manifest must not block a warm
            log.warning("manifest unreadable; starting a fresh one")
    return {"eod": {}, "intraday": {}}


def _save_manifest(man: dict) -> None:
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(man, indent=1, sort_keys=True), encoding="utf-8")


def _key(mode: str, start, end, values: Sequence[str]) -> str:
    """What "already done" means. Widening the window or asking for a value that
    was not fetched last time must NOT count as done, or a resumed run would
    silently skip work it never did."""
    return f"{start}|{end}|{','.join(sorted(values))}"


def refresh(*, as_of=None, ceiling_mb: float = WORKING_CEILING_MB) -> dict:
    """Ask Citi for today's universe and merge it into the catalog before warming.

    Without this the warm is only ever as current as the last harvest, and the
    UST universe moves in both directions: Treasury auctions weekly, and 24 of
    the 349 bonds Citi carries mature during 2026. Measured 2026-08-08, Citi was
    missing three USTs issued eight days earlier - which happen to be the
    on-the-run 2Y, 5Y and 7Y - so ``CT2`` did not resolve to anything quotable.

    The merge never removes: matured bonds are unrecoverable from ``CVCURVEBOND``
    (asking it for an old date returns today's set filtered, not the set as it
    stood), so a bond seen once is kept forever and its cached history stays
    valid. See ``bonds/refresh.py``.
    """
    from MDP.CitiVelocityExcel.bonds.refresh import refresh_universe
    from MDP.CitiVelocityExcel.memory_guard import assert_safe_to_connect
    from MDP.CitiVelocityExcel.quotes import CitiVeloQuotes

    assert_safe_to_connect(ceiling_mb, what="the UST universe refresh")
    q = CitiVeloQuotes()
    try:
        res = refresh_universe(quotes=q, country="USA", currency="USD",
                               asset_type="GOVT", as_of=as_of)
        log.info("refresh: %s", res.describe())
        for isin in res.added:
            log.info("  NEW %s serves %s", isin,
                     ", ".join(res.validated.get(isin, [])) or "(nothing yet)")
        return {"seen": res.seen, "added": res.added,
                "retained": len(res.retained_not_seen)}
    finally:
        q.close()


def universe():
    """The resolved Citi UST universe, in a stable order."""
    from MDP.CitiVelocityExcel.bonds.resolution import resolve_bonds
    from MDP.CitiVelocityExcel.bonds.universe import BondUniverse

    uni = BondUniverse.from_catalog(country="USA", asset_type="GOVT")
    isins = sorted(d.isin for d in uni)
    resolved, failures = resolve_bonds(isins, strict=False)
    for token, why in failures.items():
        log.info("  %s skipped: %s", token, why)
    return list(resolved.values())


def warm(
    mode: str,
    *,
    start: datetime.date,
    end: datetime.date,
    values: Optional[Sequence[str]] = None,
    batch: int = DEFAULT_BATCH,
    ceiling_mb: float = WORKING_CEILING_MB,
    force: bool = False,
    limit: Optional[int] = None,
    do_refresh: bool = True,
) -> dict:
    """Warm the universe for one mode, resumably.

    Returns a summary dict; also written to the manifest as it goes.
    """
    from MDP.CitiVelocityExcel.bonds.fetcher import CitiVeloBondFetcher, DEFAULT_BOND_VALUES
    from MDP.CitiVelocityExcel.memory_guard import ExcelTooLargeError, assert_safe_to_connect

    wanted = tuple(values) if values else (
        INTRADAY_VALUES if mode == "intraday" else DEFAULT_BOND_VALUES
    )
    # Gate BEFORE constructing anything that can connect.
    mem0 = assert_safe_to_connect(ceiling_mb, what=f"the UST universe {mode} warm")

    if do_refresh:
        # Pick up newly auctioned bonds before deciding what "the universe" is.
        # A warm that reads a stale catalog is a warm that silently omits every
        # bond issued since the last harvest.
        try:
            refresh(ceiling_mb=ceiling_mb)
        except Exception as exc:  # noqa: BLE001 - a stale universe still warms
            log.warning("universe refresh failed (%s); warming the catalog as it stands", exc)

    man = _load_manifest()
    book = man.setdefault(mode, {})
    stamp = _key(mode, start, end, wanted)

    everything = universe()
    # "already done" means done AT THIS EXACT WINDOW AND VALUE SET. Counting the
    # whole manifest instead would report a widened window as already warm, which
    # is the one thing a resume must never do.
    at_this_window = sum(1 for r in everything if book.get(r.isin, {}).get("key") == stamp)
    todo = everything if force else [
        r for r in everything if book.get(r.isin, {}).get("key") != stamp
    ]
    if limit:
        todo = todo[:limit]

    total = len(todo)
    log.info(
        "%s warm: %d bonds to do, %d/%d already warm at THIS window, "
        "%d in the manifest overall; values=%s, %s..%s, Excel %.0f MB, ceiling %.0f",
        mode, total, at_this_window, len(everything), len(book),
        ",".join(wanted), start, end, mem0, ceiling_mb,
    )
    if not todo:
        log.info("  nothing to do — the manifest says this window is fully warm")
        return {"mode": mode, "done": 0, "already": len(book), "stopped": False}

    fetcher = CitiVeloBondFetcher()
    quotes = fetcher.quotes()
    done = tags_done = 0
    stopped_reason = ""
    t_start = time.perf_counter()
    try:
        for i in range(0, total, batch):
            chunk = todo[i:i + batch]
            mem = None
            try:
                from MDP.CitiVelocityExcel.memory_guard import excel_memory_mb
                mem = excel_memory_mb()
            except Exception:  # noqa: BLE001
                mem = None
            if mem is None:
                stopped_reason = "could not read Excel's memory"
                log.warning("STOPPING: %s (fails closed)", stopped_reason)
                break
            if mem >= ceiling_mb:
                stopped_reason = f"Excel reached {mem:.0f} MB (ceiling {ceiling_mb:.0f})"
                log.warning("STOPPING: %s — rerun after a human restarts Excel", stopped_reason)
                break

            plan = fetcher.plan(chunk, values=wanted)
            tags = [t for e in plan.values() for t in e["tags"].values()]
            if not tags:
                for r in chunk:
                    book[r.isin] = {"key": stamp, "tags": 0, "note": "serves none of these values"}
                continue
            # ASK FOR THE REASONS. ``frame`` returns an empty frame and raises
            # nothing whether every tag failed or every tag legitimately held no
            # rows - its own docstring says so - and this loop used to ask for
            # neither, which made a total Velocity outage indistinguishable from
            # a batch of matured bonds. It is only indistinguishable if you do
            # not ask.
            reported: Dict[str, str] = {}
            try:
                if mode == "eod":
                    frame = quotes.frame(tags, "DAILY", start=start, end=end,
                                         failures=reported)
                    rows_served = int(len(frame)) if frame is not None else 0
                else:
                    rows_served = _warm_intraday(quotes, tags, start=start, end=end,
                                                 failures=reported)
            except Exception as exc:  # noqa: BLE001 - one bad batch must not lose the rest
                stopped_reason = f"{type(exc).__name__}: {exc}"
                log.warning("STOPPING at batch %d: %s", i // batch, stopped_reason[:200])
                break

            # DID THE TRANSPORT ANSWER? That question comes first, deliberately
            # before anything looks at the cache, and it is the one the guards
            # below cannot ask.
            #
            # ``landed`` cannot carry it, because the tag cache is CUMULATIVE: on
            # any night after the first, last night's parquets are still on disk,
            # so ``landed`` is the full tag count even while tonight's wire is
            # serving nothing at all. A fault check gated on ``landed == 0``
            # would pass on precisely the nights it exists for.
            #
            # ``rows_served`` cannot carry it either - zero rows is what a total
            # outage and a matured bond both look like. The REASONS separate
            # them, they are scoped to the call that just happened, and
            # ``failures=`` is how they are asked for. See
            # :data:`BENIGN_FAILURE_REASONS` for which reason means which.
            faults = _transport_faults(reported)
            if faults:
                shown = ", ".join(f"{t} ({why})" for t, why in sorted(faults.items())[:5])
                stopped_reason = (
                    f"batch {i // batch}: Velocity FAILED {len(faults)} of {len(tags)} "
                    f"tag(s) - {shown}"
                    f"{f' and {len(faults) - 5} more' if len(faults) > 5 else ''}. "
                    f"That is the transport, not a matured bond: a bond with nothing "
                    f"in this window comes back as {sorted(BENIGN_FAILURE_REASONS)}. "
                    f"Nothing in this batch is recorded, so a re-run retries it."
                )
                log.error("STOPPING: %s", stopped_reason)
                break

            # A warm is the file on disk, not the call returning. The first
            # version of this script "warmed" 349 bonds intraday in 134 s and
            # left zero MI01 parquets, because the transport it used bypassed the
            # cache — and recorded 349/349 done. Nothing is marked done now until
            # the cache is asked whether it actually holds the tags.
            #
            # But "nothing landed" has TWO causes and they need opposite actions,
            # and conflating them cost this warm more than the bug it was written
            # to catch. ``rows_served`` is what separates them.
            #
            # Rows came back and none of them landed: that IS the transport, stop.
            # NO rows came back: Velocity was asked for a window it has nothing
            # in, which for an MI01 request against a matured bond is the correct
            # and expected answer. 528 of the 877 bonds in the catalog have
            # matured, ``universe()`` sorts by ISIN, and the 22 lowest ISINs all
            # matured between 2016 and 2025 — so with ``DEFAULT_BATCH = 8``,
            # batch 0 is all-dead BY CONSTRUCTION. Treating that as a broken
            # transport aborted the whole 877-bond intraday warm at 0/877 on five
            # of ten retained nightly runs, in 2.9-4.4 s each, and it had never
            # once warmed a bond since the universe grew past the live 349.
            landed = cached_tags("DAILY" if mode == "eod" else "MI01", tags)
            if landed == 0 and rows_served > 0:
                stopped_reason = (
                    f"batch {i // batch} fetched {len(tags)} tags and {rows_served} rows "
                    f"without error and cached NONE of them — the transport is not "
                    f"writing to the tag cache"
                )
                log.error("STOPPING: %s", stopped_reason)
                break
            if landed == 0:
                # Recorded, not skipped. A bond left out of the manifest is a
                # bond re-requested from Velocity on every run for ever — and
                # these are precisely the ones that will never have anything to
                # serve. The ``note`` idiom is the one already used above for a
                # bond that serves none of the requested values, so ``status``
                # and any later reader can tell "warm" from "nothing to warm"
                # without inventing a second vocabulary.
                #
                # Reaching here now MEANS something it did not mean before: the
                # reasons were asked for above and none of them was a transport
                # fault, so "no rows" is Velocity's answer rather than its
                # silence. The answer it gave is recorded alongside, because a
                # note that cannot say WHY there were no rows is the same
                # unfalsifiable claim in a smaller place.
                why = sorted({str(w) for w in reported.values()}) or ["nothing reported"]
                log.info(
                    "  batch %d served no rows for %d tags (%s) — recorded and "
                    "skipped, not treated as a fault",
                    i // batch, len(tags), ", ".join(why),
                )
                for r in chunk:
                    book[r.isin] = {
                        "key": stamp,
                        "tags": 0,
                        "note": "no rows in this window",
                        "why": ", ".join(why),
                        "at": datetime.datetime.now().isoformat(timespec="seconds"),
                    }
                _save_manifest(man)
                continue

            for r in chunk:
                book[r.isin] = {
                    "key": stamp,
                    "tags": len(plan[r.isin]["tags"]),
                    "at": datetime.datetime.now().isoformat(timespec="seconds"),
                }
            done += len(chunk)
            tags_done += len(tags)
            _save_manifest(man)          # after EVERY batch: a stop costs one batch
            if (i // batch) % 5 == 0 or done >= total:
                log.info("  %d/%d bonds, %d tags, Excel %.0f MB, %.0fs",
                         done, total, tags_done, mem, time.perf_counter() - t_start)
    finally:
        _save_manifest(man)
        fetcher.close()

    try:
        from MDP.CitiVelocityExcel.memory_guard import excel_memory_mb
        mem_end = excel_memory_mb()
    except Exception:  # noqa: BLE001
        mem_end = None
    log.info(
        "%s warm finished: %d/%d bonds, %d tags, %.0fs, Excel %.0f -> %s MB%s",
        mode, done, total, tags_done, time.perf_counter() - t_start, mem0,
        f"{mem_end:.0f}" if mem_end is not None else "?",
        f" (STOPPED: {stopped_reason})" if stopped_reason else "",
    )
    return {
        "mode": mode, "done": done, "of": total, "tags": tags_done,
        "stopped": bool(stopped_reason), "reason": stopped_reason,
        "mem_before": mem0, "mem_after": mem_end,
    }


def status() -> None:
    """What the manifest says is warm, without touching Excel."""
    man = _load_manifest()
    try:
        uni = universe()
        n_uni = len(uni)
    except Exception:  # noqa: BLE001
        n_uni = 0
    print(f"manifest: {MANIFEST}")
    for mode in ("eod", "intraday"):
        book = man.get(mode, {})
        keys = {v.get("key") for v in book.values()}
        tags = sum(v.get("tags", 0) for v in book.values())
        print(f"  {mode:>8}: {len(book)}/{n_uni} bonds, {tags} tags, "
              f"{len(keys)} distinct window(s)")
        for k in sorted(x for x in keys if x):
            n = sum(1 for v in book.values() if v.get("key") == k)
            print(f"            {n:>4} bonds @ {k}")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                        datefmt="%H:%M:%S")
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("mode", choices=["eod", "intraday", "status", "refresh"])
    p.add_argument("--years", type=float, default=5.0, help="EOD history depth (default 5)")
    p.add_argument("--days", type=int, default=2, help="intraday window in days (default 2)")
    p.add_argument("--end", type=datetime.date.fromisoformat, default=None)
    p.add_argument("--values", nargs="*", default=None, help="override the value set")
    p.add_argument("--batch", type=int, default=DEFAULT_BATCH)
    p.add_argument("--ceiling-mb", type=float, default=WORKING_CEILING_MB)
    p.add_argument("--limit", type=int, default=None, help="only the first N bonds (for a smoke run)")
    p.add_argument("--no-refresh", action="store_true",
               help="skip the universe refresh and warm the catalog as it stands")
    p.add_argument("--force", action="store_true", help="re-warm bonds the manifest calls done")
    args = p.parse_args()

    if args.mode == "status":
        status()
        return
    if args.mode == "refresh":
        refresh(as_of=args.end, ceiling_mb=args.ceiling_mb)
        return

    end = args.end or datetime.date.today()
    start = (end - datetime.timedelta(days=int(args.years * 365.25)) if args.mode == "eod"
             else end - datetime.timedelta(days=args.days))
    out = warm(args.mode, start=start, end=end, values=args.values, batch=args.batch,
               ceiling_mb=args.ceiling_mb, force=args.force, limit=args.limit,
               do_refresh=not args.no_refresh)
    if out.get("stopped"):
        # A partial warm is a real outcome, not a failure to hide: exit non-zero so
        # a scheduled task's summary shows it, but the manifest keeps the progress.
        sys.exit(2)


if __name__ == "__main__":
    main()
