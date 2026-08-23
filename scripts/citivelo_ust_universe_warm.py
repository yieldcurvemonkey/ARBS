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

So the reasons ARE asked for, through ``failures=``. But the reasons alone
cannot carry the decision, and betting the nightly on them was the second
mistake. ``parse_tshist_block`` maps a spill under two rows to ``"no block"``
for EVERY requested tag - the same string a dead wire produces - and the benign
``"empty"`` is only reachable once some OTHER tag in the same chunk has returned
rows, which an all-matured chunk cannot supply. Batch 0 IS an all-matured chunk
(the 22 lowest ISINs redeemed between 2016 and 2025), so a guard keyed on the
reason string alone re-creates the 0/877 abort under one plausible answer and
fails open under the other. Widening :data:`BENIGN_FAILURE_REASONS` until batch 0
survives is failing open with extra steps.

**Maturity is the discriminator, because it is catalog data and needs no wire.**
A bond that had already redeemed cannot serve the window whatever the add-in
says about it, so its failure is not evidence of anything. Only a chunk in which
every ALIVE tag failed, over at least :data:`MIN_ALIVE_BONDS_FOR_OUTAGE` alive
bonds, stops the run. The reasons still do real work below that bar - they say
whether Velocity ANSWERED - and a per-tag failure now costs that bond a retry
rather than costing the run 877 bonds.

Three cases, three signals, and only one of them is on the wire
--------------------------------------------------------------
``(a)`` the transport fetched and persisted nothing, ``(b)`` Velocity served
nothing for this window, ``(c)`` the window was already cached. They are
separated by three questions asked in order, and the middle one is the only one
the transport gets a vote in:

* **did the batch NEED anything?** ``missing_spans``, before the fetch. No means
  ``(c)``: no ``CVTSHIST`` is issued at all, so no reason can be reported and no
  sidecar can move, and reading that as a fault would stop the run on the
  healthiest thing it can meet.
* **did the transport say anything?** the reasons. ``(b)`` comes with one.
* **did anything reach the DISK?** :func:`_sidecar_state`, sampled either side of
  the fetch. This is what makes ``(a)`` visible, and it has to be a real disk
  read: the guard it replaces compared a row count that came from
  ``CitiVeloTagCache.get``'s own re-read of the parquets, so on a transport that
  wrote nothing the count was zero and the predicate could never fire. Measured:
  a client serving 30 rows with ``cache.write`` neutered produced ``len(frame)
  == 0``. Two signals derived from the same disk read are one signal.

Depth is a separate job from freshness
--------------------------------------
Everything above keeps the cache CURRENT. Nothing above can make it DEEP, and
the difference is structural rather than a bug: ``missing_spans``' backwards
branch is ``want_start < cov.first``, and a nightly ``want_start`` of ``end - 2
days`` only ever advances, so after the first successful run it can never fire.
The real cache is the proof - all 698 MI01 bond tags share ``first =
2026-08-04`` and ``last = 2026-08-07``, one window, banked once by hand and never
extended. :func:`backfill_depth` is the other half: a budgeted, resumable
backwards walk over a stable Monday-to-Friday grid. See its section below for
the grid, the cursor, and how many nights the defaults need.

A file that exists is not a window that is covered
--------------------------------------------------
The cache check above counts FILES. That is the right question for "did the
transport write anything at all" and the wrong one for "is what it wrote
current", and the tag cache is CUMULATIVE, so after the first ever run the file
is always there. Measured on the real cache on 2026-08-19, against the nightly
window ``2026-07-19..2026-08-18``: all 877 bonds stamped done, **522 of them with
DAILY data ending before the window started**, and 0 missing sidecars. At tag
level it is worse - of the 8,510 DAILY tags belonging to bonds that were ALIVE
through that window, **2,891 hold no row inside it**. The job was green every
night regardless, and a warm that cannot fail cannot be trusted.

The fix is not a calendar bar. Three different things produce an empty window
and only one is a fault:

* the bond **matured** - 528 of 877 have, so this is the majority answer and
  flagging it re-creates the batch-0 abort;
* the tag is **sparse** - ``ASW_4_CHF/EUR/GBP`` went from daily to roughly
  monthly in October 2024, widest historical gap 76 days against a trailing 48;
* the tag has **stalled** - ``CAS``, ``ZSPREAD``, ``ASW`` and ``OISS`` stop dead
  on 2025-10-03 and the four ``*_SOFR`` spreads on 2025-11-28, across every bond
  that serves them, widest historical gap 4 days against a trailing 320 and 264.

No fixed number separates the last two. Each tag's OWN widest observed gap does,
with nothing to configure. :func:`tag_states` is that predicate,
:func:`coverage_record` is what it writes into the manifest, and the exit code
alarms on a tag falling silent SINCE THE LAST RUN rather than on the standing
level - because the standing level is ten dead value families and an exit code
that is always 1 is an exit code nobody reads.

THE FIRST RUN AFTER THIS SHIPS WILL EXIT 1, once, and that is intended. Manifest
entries written before this change carry no ``stalled`` key, so the "what did we
know last night" set is empty and the entire standing level - the ten dead value
families, plus the three 2026-07-31 auctions that have never been warmed at MI01
- reads as new. There is no honest way to distinguish "silent since October" from
"silent since last night" against a manifest that never recorded either, and
guessing the level away on the first run would hide a real outage that happened
to land on the same night. One loud night, then only changes. It is pinned by
``test_a_value_that_falls_silent_since_the_last_run_is_a_regression``.

Usage
-----
::

    python scripts/citivelo_ust_universe_warm.py eod
    python scripts/citivelo_ust_universe_warm.py intraday --days 2
    python scripts/citivelo_ust_universe_warm.py depth --depth-days 365
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
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

from utils import window_ledger  # noqa: E402 - after the sys.path insert above

log = logging.getLogger("citivelo-ust-warm")

#: Environment override for the manifest path, and it exists because of a
#: measured accident rather than a hypothetical one.
#:
#: :data:`MANIFEST` is bound at IMPORT, so the only way to redirect it is to
#: monkeypatch the module attribute — which every test in this repo's own warm
#: suites does, and which one test outside them did not. On 2026-08-20
#: ``tests/test_ust_coverage_regression_escalates.py`` stubbed ``warm`` and
#: called the nightly job; the depth pass added to that job is a SECOND entry
#: point, it was not stubbed, and it wrote a 397-bond ``depth`` book straight
#: into the production manifest (and fetched 794 tags from the live add-in on
#: the way). The manifest was restored byte-for-byte, but "remember to patch the
#: global" is not a safety property.
#:
#: An env var is read at import, before any test body runs, so a session fixture
#: can redirect the manifest no matter when — or how lazily — this module is
#: first imported. ``tests/conftest.py`` sets it for the whole session.
MANIFEST_ENV = "ARBS_UST_WARM_MANIFEST"


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

    override = os.environ.get(MANIFEST_ENV)
    if override:
        return pathlib.Path(override)
    return default_cache_dir() / "ust_universe_warm_manifest.json"


MANIFEST = _manifest_path()

#: Leave headroom below the hard 3,800 MB ceiling so a batch in flight cannot
#: cross it. One intraday batch is ~14 MB, so 300 MB is ~20 batches of slack.
WORKING_CEILING_MB = 3500.0

#: Intraday defaults to the two values EVERY bond serves. Measured on the cached
#: transport at ~0.24 MB/tag, so 698 tags is ~170 MB; the full 2,302-tag set
#: projects to ~560 MB and would fit, but has not been run end to end. Two values
#: is what is measured, so two values is the default.
INTRADAY_VALUES = ("PRICE", "YIELD", "CAS_RFR", "YYS_RFR")

#: Why four and not two, and why these two.
#:
#: PRICE and YIELD are what every bond serves and were the whole intraday set.
#: CAS_RFR (coupon-adjusted spread vs RFR) and YYS_RFR (yield-yield spread vs
#: RFR) are the two SPREAD reads a relative-value book watches during a session,
#: and they are the live successors of the CAS/YYS that Citi retired on
#: 2025-10-03 (``bonds.values.DISCONTINUED_2025_10_03``) - so a study written
#: against the old names has nothing to read after that date and this is where
#: it gets it back.
#:
#: THE MARGINAL COST IS 240 TAGS, NOT 1,754, and that is what makes it
#: affordable. ``CitiVeloBondFetcher.plan`` filters each bond's requested values
#: against its VALIDATED coverage, and only 120 of the 877 catalogued ISINs
#: carry CAS_RFR/YYS_RFR (the same 120 for both, and a strict subset of the 877
#: that carry PRICE). So the tag count goes 1,754 -> 1,994.
#:
#: At the transport this script actually uses - ``CitiVeloQuotes.frame`` through
#: ``windowed.warm_windows``, measured at **0.24 MB of Excel per tag** (349
#: bonds / 698 tags over a 2-day MI01 window cost 48 s and +170 MB) - that is
#: about +58 MB. Note the figure quoted in ``daily_cache_warmer``'s own
#: docstring, ~1.7 MB/tag, belongs to ``fetch_windowed``, a sheet-per-window
#: transport this warm deliberately does not use; its own arithmetic in the same
#: sentence (698 tags = 170 MB) is the 0.24 number. Sized off the wrong one, two
#: extra values look like +1.2 GB against a 3,800 MB ceiling.

def eod_values():
    """The DAILY value set: the whole vocabulary MINUS the six Citi retired.

    ``DEFAULT_BOND_VALUES`` is every token in ``tags.BOND_VALUES``, and six of
    them - ASW, ASWNP, CAS, OISS, YYS, ZSPREAD - stopped publishing on
    2025-10-03. They still VALIDATE, which is the trap: the tag is real and
    returns four years of rows, so a coverage probe calls it served, and a
    request for a recent date returns "no rows in the window", which reads as an
    outage rather than as a retired field.

    Asking for them nightly does two bad things and no good one. It spends 5,262
    tag-slots (6 x 877 bonds) on a wire that will never answer again, and it
    guarantees six permanently STALLED tags per bond - which is noise in exactly
    the channel the coverage alarm listens to. Their ``_RFR`` successors are
    already in the set and are what serves after that date, so nothing is lost:
    the retired tags' history is already banked and is not re-fetched by asking
    for them again.

    Ask for them explicitly with ``--values`` if a historical repair ever needs
    them.
    """
    from MDP.CitiVelocityExcel.bonds.fetcher import DEFAULT_BOND_VALUES
    from MDP.CitiVelocityExcel.bonds.values import DISCONTINUED_2025_10_03

    retired = set(DISCONTINUED_2025_10_03)
    return tuple(v for v in DEFAULT_BOND_VALUES if v not in retired)


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


#: A chunk-wide failure needs at least this many ALIVE bonds behind it before it
#: is allowed to stop the run.
#:
#: One alive bond's two tags hitting a per-COLUMN Excel error satisfies "every
#: alive tag in this chunk failed" without being an outage at all -
#: ``block_parser``'s own module docstring says a failure is per tag and must not
#: discard the batch, and it writes an error NAME per column while every other
#: tag in the same call returns normally. Two independent bonds failing together
#: is the cheapest thing that cannot be one bad column. The cost of the rule is
#: that a chunk holding exactly one alive bond can never stop the run on its own
#: - deliberate: it records the failure, leaves the bond unstamped so a re-run
#: retries it, and the next chunk carrying two alive bonds stops the run.
MIN_ALIVE_BONDS_FOR_OUTAGE = 2


def _retired_before(maturity: Optional[datetime.date], start: datetime.date) -> bool:
    """Had this bond already redeemed by the time ``start`` came around?

    The same predicate :func:`tag_states` uses, named once so the coverage record
    and the outage guard cannot drift apart. ``None`` is ALIVE on purpose: an
    unknown maturity must fail towards visibility.
    """
    return maturity is not None and maturity < start + MATURITY_GRACE


def _sidecar_state(cache, tags: Sequence[str], freq: str,
                   price_point: str = "CLOSE") -> Dict[str, Optional[tuple]]:
    """``{tag: fingerprint}`` off the tag cache's sidecars, read fresh from disk.

    THE ONLY DISK-SIDE EVIDENCE THAT CAN STILL FIRE
    -----------------------------------------------
    The guard this replaces asked ``landed == 0 and rows_served > 0``, and
    ``rows_served`` cannot carry what that predicate needed. It is
    ``len(frame)`` where ``frame`` came back from ``CitiVeloQuotes.frame`` ->
    ``CitiVeloTagCache.get``, and ``get`` builds its return value by RE-READING
    THE PARQUETS. Measured: a client that served 30 real rows with
    ``cache.write`` neutered produced ``len(frame) == 0``, so ``landed == 0 and
    rows_served > 0`` was unreachable on the real transport. Both halves of a
    two-signal guard were the same disk read, and the fault it existed for -
    a transport that fetches and persists nothing - went back to being invisible.

    A fingerprint of the sidecar, sampled either side of the fetch, is evidence
    the wire cannot fabricate and the cache cannot launder. ``write`` stamps
    ``fetched_at`` on EVERY persist (``cache.py:313``), so a call that merged
    rows identical to the ones already held still moves the fingerprint - which
    matters, because the steady-state nightly span ``(cov.last, want_end)`` can
    legitimately re-serve exactly the row already on disk over a holiday, and a
    fingerprint of ``n_rows`` alone would have read that as "nothing persisted"
    and stopped a healthy run.

    ``mtime_ns`` is carried too, because ``fetched_at`` has second resolution and
    two writes inside one second are a real thing in a test.

    ``None`` for a tag means there is no sidecar at all, which is distinct from
    one that exists and did not move.
    """
    out: Dict[str, Optional[tuple]] = {}
    for tag in tags:
        path = cache.meta_path(str(tag), freq, price_point)
        try:
            st = path.stat()
        except OSError:
            out[str(tag)] = None
            continue
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - an unreadable sidecar is "no evidence"
            meta = {}
        out[str(tag)] = (
            int(st.st_mtime_ns),
            int(meta.get("n_rows") or 0),
            str(meta.get("first") or ""),
            str(meta.get("last") or ""),
            str(meta.get("fetched_at") or ""),
        )
    return out


def _tags_needing_data(cache, tags: Sequence[str], freq: str, *,
                       start, end, price_point: str = "CLOSE") -> List[str]:
    """Which of ``tags`` the cache cannot already answer over ``[start, end]``.

    Asked BEFORE the fetch, and it is what separates the third case from the
    other two. A batch that needs nothing issues no ``CVTSHIST`` at all -
    measured: a fully cached window drove a client that raises on contact ZERO
    times - so there are no transport reasons to read and no sidecars to move,
    and a fault check that did not know this would call a perfectly warm batch
    a silent transport.
    """
    need: List[str] = []
    for tag in tags:
        try:
            spans = cache.missing_spans(str(tag), freq, start=start, end=end,
                                        price_point=price_point)
        except Exception:  # noqa: BLE001 - an unreadable sidecar means "ask for it"
            spans = [(start, end)]
        if spans:
            need.append(str(tag))
    return need


def _warm_intraday(
    quotes,
    tags: Sequence[str],
    *,
    start: datetime.date,
    end: datetime.date,
    failures: Optional[Dict[str, str]] = None,
    force: bool = False,
) -> int:
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

    Returns the number of rows THE CACHE HOLDS across every window after the
    fetch, which is NOT the number of rows Velocity served, and the sentence
    that used to claim it was is the reason the guard built on it never fired.
    ``warm_windows`` reports ``len(frame)``, and ``frame`` is
    ``CitiVeloQuotes.frame`` -> ``CitiVeloTagCache.get``, whose return value is
    a re-read of the parquets. On a transport that fetched 30 rows and persisted
    none it is 0. It is kept, and logged, because it is a fair answer to "how
    much does this window hold" - it is simply not evidence about the wire. The
    evidence about the wire is :func:`_sidecar_state` and the reasons in
    ``failures``.

    ``force`` bypasses ``warm_windows``' own cache consultation, and the
    backwards pass needs it for a reason that is easy to get wrong.
    ``warm_windows`` skips a window whose tags ``missing_spans`` calls covered -
    which is right for a forward warm and WRONG here, because ``missing_spans``
    only ever inspects the head and the tail of the cached range. A week sitting
    in a HOLE inside that range reads as covered to it, and the hole is exactly
    what the backwards pass is for. The caller has already established the week
    is missing, against the parquet's own day set, which is strictly better
    evidence; the window is a Monday-to-Friday five days, so forcing it cannot
    take the wire span over the cliff.

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
        force_refresh=force,
    )
    return sum(int(w.n_rows) for w in windows)


def cached_tags(freq: str, tags: Sequence[str]) -> int:
    """How many of ``tags`` are actually on disk in the tag cache at ``freq``.

    The point of a warm is the file, not the fetch. This reads the cache
    directly rather than trusting a return value, because the bug this guards
    against is precisely a fetch that succeeds and persists nothing.

    EXISTENCE ONLY, and deliberately so
    -----------------------------------
    This answers "did the transport write anything at all", which is the only
    question the 134-second lie needed. It cannot answer "is what it wrote
    current": a file whose newest row is from 2016 counts here exactly like one
    written five minutes ago. That is not a defect in this function - it is the
    reason :func:`tag_states` exists beside it. Both guards run, in that order,
    because they fail differently: this one catches a transport that lost the
    cache, and that one catches a cache that stopped moving.
    """
    from MDP.CitiVelocityExcel.cache import default_cache_dir
    from MDP.CitiVelocityExcel.frequencies import normalise_frequency

    root = default_cache_dir() / normalise_frequency(freq)
    if not root.is_dir():
        return 0
    on_disk = {p.stem for p in root.rglob("*.parquet")}
    return sum(1 for t in tags if str(t) in on_disk)


# ──────────────────────────────────────────────────────────────────────────
# COVERAGE: what the cache holds for the window that was asked for
# ──────────────────────────────────────────────────────────────────────────
#
# ``cached_tags`` above is membership by FILE NAME. Measured against the real
# cache on 2026-08-19, that check calls the whole universe warm while a third of
# it holds nothing inside the requested window: for the nightly window
# ``2026-07-19..2026-08-18``, 522 of 877 bonds have DAILY data ENDING BEFORE the
# window starts, and every one of the 877 was stamped done. Worse at tag level -
# of the 8,510 DAILY tags belonging to bonds that were ALIVE through that window,
# 2,891 hold no row inside it.
#
# Three separate things have to be told apart, and only one of them is a fault:
#
# ``matured``   The bond redeemed before the window. 528 of the 877 catalogued
#               USTs have matured, so "no rows in this window" is the CORRECT
#               answer for the majority of the universe. A freshness check that
#               ignores maturity flags two thirds of the catalog for ever, which
#               is the batch-0 abort that cost five of ten nightly runs.
# ``sparse``    The tag still prints, just not every day. ``ASW_4_CHF/EUR/GBP``
#               went from daily to roughly monthly in October 2024: measured
#               over 60 bonds, median gap 1 day, WIDEST gap 76 days, and the
#               trailing gap on 2026-08-19 was 48 days. A fixed calendar bar
#               calls all 345 of them stale every month and is simply wrong.
# ``stalled``   Velocity stopped answering. ``CAS``, ``ZSPREAD``, ``ASW`` and
#               ``OISS`` all stop dead on 2025-10-03 and the four ``*_SOFR``
#               spread tags on 2025-11-28, across every bond that serves them,
#               with a widest historical gap of 4 days against a trailing gap of
#               320 and 264. Nothing about a calendar separates that from the
#               sparse case; the tag's OWN gap envelope separates both cleanly.
#
# So the bar is not a constant. It is each tag's own widest observed gap, which
# needs no configuration, no per-value allowlist, and no guess about what Citi
# publishes daily.

#: How long BEFORE its maturity a bond can legitimately stop printing.
#:
#: Measured over the 522 catalogued USTs that had already matured on 2026-08-19,
#: as ``maturity - last DAILY row``: 1 day for 127 bonds, 2 for 202, 3 for 80,
#: 4 for 95, 5 for 18. Never 0, never above 5, and never negative - no matured
#: bond has a row dated after it redeemed. An exemption pinned to the maturity
#: date alone would therefore false-flag each maturing bond for the few nights
#: the rolling window start sits inside that tail.
MATURITY_GRACE = datetime.timedelta(days=5)

#: Rows a tag needs before its own gap envelope means anything. Two rows give
#: one gap, which is not an envelope. Below this the tag is reported
#: ``uncalibrated`` rather than called stalled: "I have never seen this tag
#: print three times" is not evidence that it stopped.
MIN_ROWS_TO_CALIBRATE = 3

#: The cache holds a row inside the requested window. Nothing to do.
COVERED = "covered"
#: The bond redeemed before the window, so no row inside it can exist. Nothing
#: to do, and this is the majority of the universe.
MATURED = "matured"
#: No row inside the window, but the tag's own history contains a gap at least
#: this long. It prints; it just did not print here.
SPARSE = "sparse"
#: No row inside the window, and the silence is longer than anything this tag
#: has ever gone quiet for. Velocity has stopped answering for it.
STALLED = "stalled"
#: The cache has no file for this tag at all, and the bond is alive. It has
#: never been warmed at this frequency.
ABSENT = "absent"
#: Quiet, alive, and too short to judge. Reported, never alarmed on.
UNCALIBRATED = "uncalibrated"

#: The states that are NOT explained by maturity or by the tag's own cadence.
#: These are the only two that can move an exit code.
ALARMING_STATES = frozenset({STALLED, ABSENT})


def _last_row(meta: Mapping[str, object]) -> Optional[datetime.date]:
    """The newest row the sidecar claims, as a date, or ``None``.

    The sidecar is authoritative and that is measured, not assumed:
    ``CitiVeloTagCache.write`` writes ``first``/``last``/``n_rows`` from the
    MERGED series on every write, and on a hand-checked sample of eight tags
    across a live and a matured bond the sidecar ``last`` equalled the parquet's
    own maximum timestamp every time. All 14,535 DAILY and 1,502 MI01 parquets
    in the real cache have a sidecar and all of them carry ``last``, so reading
    coverage costs a small JSON read rather than a parquet parse.
    """
    raw = meta.get("last")
    if not raw:
        return None
    try:
        return datetime.date.fromisoformat(str(raw)[:10])
    except ValueError:  # a hand-edited or truncated sidecar is a miss, not a crash
        return None


def _widest_gap_days(cache, tag: str, freq: str) -> Optional[int]:
    """The longest quiet stretch this tag has ever had, in days.

    This is the whole bar. A tag is only called ``stalled`` when its current
    silence is longer than anything in its own past, which is what separates
    ``CAS`` (widest gap 4 days, silent 320) from ``ASW_4_CHF`` (widest gap 76
    days, silent 48) without knowing anything about either.

    Distinct DAYS, not rows: an ``MI01`` series has hundreds of rows per day and
    the question is which days Velocity answered on.

    Costs a parquet parse, so it is asked ONLY for a tag that is already known
    to be quiet and not exempt - measured on the real cache that is 2,891 of the
    11,120 tags a nightly EOD warm plans, and zero of the intraday ones.
    """
    series = cache.read(tag, freq)
    if series is None or series.empty:
        return None
    days = series.index.normalize().unique()
    if len(days) < MIN_ROWS_TO_CALIBRATE:
        return None
    gaps = days.to_series().diff().dropna()
    if gaps.empty:
        return None
    return int(gaps.dt.days.max())


def tag_states(
    freq: str,
    tags: Mapping[str, str],
    *,
    start: datetime.date,
    end: datetime.date,
    maturity: Optional[datetime.date] = None,
    cache=None,
) -> Dict[str, Tuple[str, Optional[datetime.date]]]:
    """``{value: (state, last row)}`` for one bond's tags at one window.

    ``tags`` is the ``{value: tag}`` mapping ``CitiVeloBondFetcher.plan`` builds,
    so the answer is keyed by the value token a human reads (``ASW_4_CHF``)
    rather than by the full tag string.

    The order of the tests is the meaning of the answer:

    1. a row inside the window is the strongest claim available, so it wins even
       for a bond that matured during the window - six of the 877 did;
    2. maturity next, because for 522 of 877 bonds it is the CORRECT explanation
       for an empty window and must never look like a fault;
    3. no file at all, for a live bond, is "never warmed" - three USTs auctioned
       2026-07-31 are in exactly that state at ``MI01``;
    4. only then is the parquet opened and the tag judged against its own
       history.

    ``maturity`` comes from ``BondResolution.descriptor.maturity``, which
    ``bonds.universe._descriptor_from_ref`` takes from the catalog's dedicated
    ``maturity`` column in preference to the parsed description - the two
    disagree on exactly one of 2,162 catalogued rows. It is already in hand
    inside :func:`warm`: ``plan[isin]["resolution"].descriptor``. ``None`` means
    "not known to have matured", which is treated as ALIVE on purpose - an
    unknown maturity must fail towards visibility, not towards silence. Measured
    on the real catalog, no USA.USD.GOVT bond has one.
    """
    from MDP.CitiVelocityExcel.cache import CitiVeloTagCache, default_cache_dir
    from MDP.CitiVelocityExcel.frequencies import normalise_frequency

    if cache is None:
        cache = CitiVeloTagCache(base_dir=default_cache_dir())
    token = normalise_frequency(freq)
    retired = maturity is not None and maturity < start + MATURITY_GRACE

    out: Dict[str, Tuple[str, Optional[datetime.date]]] = {}
    for value, tag in dict(tags).items():
        meta: Dict[str, object] = {}
        path = cache.meta_path(str(tag), token)
        if path.is_file():
            try:
                meta = json.loads(path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001 - an unreadable sidecar is a miss
                meta = {}
        last = _last_row(meta)
        if last is not None and last >= start:
            out[value] = (COVERED, last)
        elif retired:
            out[value] = (MATURED, last)
        elif last is None:
            out[value] = (ABSENT, None)
        else:
            widest = _widest_gap_days(cache, str(tag), token)
            if widest is None:
                out[value] = (UNCALIBRATED, last)
            elif (end - last).days > widest:
                out[value] = (STALLED, last)
            else:
                out[value] = (SPARSE, last)
    return out


def newly_stalled(
    prior: Optional[Mapping[str, object]],
    record: Mapping[str, object],
) -> list:
    """Tags that went quiet SINCE the last run, or ``[]`` if that is unanswerable.

    ``prior`` is this bond's previous manifest entry, or ``None`` if the
    manifest has never recorded it.

    A BOND WITH NO PRIOR ENTRY CANNOT HAVE REGRESSED, and treating its absence
    as "an empty stalled set last night" is what made this alarm fire on 324
    bonds at once. The catalog grew from 349 to 877 ISINs; every bond added by
    that growth arrived with no baseline, so every structurally quiet tag it
    carried - the six fields Citi retired on 2025-10-03, and the
    CARRY/ROLL/ROLLCARRY family, which lags its own horizon BY CONSTRUCTION -
    counted as a fresh outage.

    What that cost: on 2026-08-21 the EOD job ran 3,466 s, COMPLETED, and then
    raised "324 bond(s) newly stopped updating". The runner marks a store asset
    blocking when its provider fails, so both downstream value jobs were
    SKIPPED. Same cascade on 08-19 and 08-20. The alarm was built to catch a
    tag that stops answering; it was firing on tags that had never answered
    within this manifest's memory.

    The first sighting still WRITES its baseline, so a tag that goes quiet
    tomorrow is caught tomorrow. Only the sighting that carries no information
    about change is exempt.
    """
    if prior is None:
        return []
    known = set(prior.get("stalled") or ())
    return sorted(set(record.get("stalled") or ()) - known)


def coverage_record(
    states: Mapping[str, Tuple[str, Optional[datetime.date]]]
) -> Dict[str, object]:
    """The compact per-bond coverage record that goes into the manifest.

    Compact because the manifest is rewritten after every batch for 877 bonds:
    counts for the two states that need no attention, and the quiet tags named
    with the date they stop at. ``stalled`` is the list an exit code is allowed
    to look at - the tags whose silence is explained by neither maturity nor
    their own cadence, plus the ones with no file at all.

    Writing the OBSERVATION rather than a boolean is the point. "Done" used to
    mean "the batch did not abort", which is true of a night that cached
    nothing; it now carries what the cache actually holds, so the next run can
    tell a shortfall that is new from one that has been there since October.
    """
    counts: Dict[str, int] = {}
    quiet: Dict[str, str] = {}
    for value, (state, last) in sorted(states.items()):
        counts[state] = counts.get(state, 0) + 1
        if state not in (COVERED, MATURED):
            quiet[value] = last.isoformat() if last is not None else ""
    record: Dict[str, object] = {
        "covered": counts.get(COVERED, 0),
        "matured": counts.get(MATURED, 0),
    }
    if quiet:
        record["quiet"] = quiet
    stalled = sorted(v for v, (state, _) in states.items() if state in ALARMING_STATES)
    if stalled:
        record["stalled"] = stalled
    return record


def _maturity_of(entry: Mapping[str, object]) -> Optional[datetime.date]:
    """The maturity on a ``plan`` entry, or ``None`` when Citi never gave one."""
    descriptor = getattr(entry.get("resolution"), "descriptor", None)
    return getattr(descriptor, "maturity", None)


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
    """What "already done" USED to mean, and still means to an older reader.

    Widening the window or asking for a value that was not fetched last time must
    NOT count as done, or a resumed run would silently skip work it never did.
    That requirement has not changed - see :func:`_residual_window`, which now
    enforces it per value instead of by making the whole key move.

    Still written to the manifest beside the ledger, and deliberately: if this
    change is reverted, an older ``warm()`` reading a ledger-era manifest finds
    the key it expects. It stamps the window that was requested, so the worst a
    rollback can do is re-fetch.
    """
    return f"{start}|{end}|{','.join(sorted(values))}"


def _banked(entry: Optional[Mapping], value: str) -> list:
    """The windows already fetched for one ``(bond, value)``.

    Migrates a pre-ledger entry on read rather than in a separate pass: the old
    ``key`` asserts exactly "this window, these values, done", so seeding the
    value's ledger with that one interval is what the old stamp already claimed.
    A manifest written before this change therefore costs nothing on the first
    night rather than re-fetching five years.
    """
    if not entry:
        return []
    windows = (entry.get("windows") or {}).get(value)
    if windows is not None:
        return window_ledger.normalize(windows)

    legacy = str(entry.get("key") or "")
    parts = legacy.split("|")
    if len(parts) != 3:
        return []
    lo, hi, values = parts
    if value not in values.split(","):
        return []
    try:
        return window_ledger.normalize([(lo, hi)])
    except Exception:  # noqa: BLE001 - an unreadable stamp means "not banked"
        return []


def _residual_window(entry: Optional[Mapping], values: Sequence[str], start, end):
    """The window this bond still owes, or ``None`` when it owes nothing.

    Per VALUE, then unioned. Per value because the value set has already grown
    once - ``INTRADAY_VALUES`` went from two to four when ``CAS_RFR`` and
    ``YYS_RFR`` were added - and a set-shaped key makes that growth invalidate
    every banked window for all 877 bonds. Unioned into one span because the
    wire call is one ``start``/``end`` for a batch of tags: a bond owing
    different tails for different values is asked for the range covering both,
    which over-fetches the middle and never under-fetches.
    """
    gaps = []
    for value in values:
        gaps.extend(window_ledger.subtract(start, end, _banked(entry, value)))
    return window_ledger.span(gaps)


def _record_bond(book: dict, isin: str, *, stamp: str, values: Sequence[str],
                 fetched, fields: Mapping[str, object]) -> None:
    """Write one bond's manifest entry, extending its ledger by what was fetched.

    ``fetched`` is the ``(lo, hi)`` this batch actually asked Velocity for, or
    ``None`` to write the entry without banking anything - which is what a run
    whose whole window is today does, because :func:`_bankable_end` refuses to
    call an unsettled session done.

    Values NOT in ``values`` keep whatever they had. A narrower run must never
    erase a wider ledger: ``--values PRICE`` would otherwise drop the record of
    every YIELD window ever fetched, and the next full run would look un-warmed
    while the ledger claimed otherwise.
    """
    prior = book.get(isin)
    windows = dict((prior or {}).get("windows") or {})

    # Migrate the whole legacy key, not just the values this run asked for -
    # otherwise a narrow run silently discards the old stamp's claim on the rest.
    legacy = str((prior or {}).get("key") or "").split("|")
    if not windows and len(legacy) == 3:
        for value in legacy[2].split(","):
            if value:
                windows[value] = window_ledger.to_json(_banked(prior, value))

    for value in values:
        banked = window_ledger.normalize(windows.get(value) or _banked(prior, value))
        if fetched is not None:
            banked = window_ledger.add(banked, fetched[0], fetched[1])
        windows[value] = window_ledger.to_json(banked)

    book[isin] = {"key": stamp, "windows": windows, **dict(fields)}


def _bankable_end(end) -> Optional[datetime.date]:
    """The latest date this run may RECORD as fetched.

    Never today. Today's session is still moving - an MI01 series grows all day
    and an EOD print is not final until the close - so banking it would make
    tomorrow's run skip a day it only half has. The nightly already avoids this
    by being pointed at the last settled session (``WarmJob.banks_today``); this
    is what protects a human running the CLI at noon, which nothing else does.

    Returns ``None`` when the whole window is unbankable, which is the correct
    answer for a run whose window is only today: it fetched, and it records
    nothing, so tomorrow asks again.
    """
    end = end.date() if isinstance(end, datetime.datetime) else end
    cutoff = datetime.date.today() - datetime.timedelta(days=1)
    return min(end, cutoff) if end is not None else None


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
        INTRADAY_VALUES if mode == "intraday" else eod_values()
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
    # One token, named once. The cache check and the coverage check MUST ask at
    # the same frequency the fetch used - a DAILY answer to an MI01 question is
    # the original 349/349 lie in a different place.
    freq_token = "DAILY" if mode == "eod" else "MI01"

    everything = universe()

    # WHAT EACH BOND STILL OWES, rather than whether its stamp matches.
    #
    # The stamp used to be f"{start}|{end}|{values}", so a nightly window ending
    # at the last settled session changed it every night and all 877 bonds looked
    # un-warmed on every run. The requirement it was enforcing has not gone away
    # - a value never fetched must not count as done - it is now enforced per
    # value by the ledger, which records the windows actually fetched instead of
    # the window last asked for. See :func:`_residual_window`.
    #
    # Grouped by the residual so the wire call keeps its shape: ``quotes.frame``
    # takes ONE start/end for a batch of tags, and a banked bond needing the
    # one-day tail must not be batched with a newly auctioned one needing thirty.
    owed: Dict[Tuple[datetime.date, datetime.date], List] = {}
    for r in everything:
        need = ((start, end) if force
                else _residual_window(book.get(r.isin), wanted, start, end))
        if need is not None:
            owed.setdefault(need, []).append(r)

    todo = [r for group in owed.values() for r in group]
    if limit:
        todo = todo[:limit]
        kept = {r.isin for r in todo}
        owed = {w: [r for r in g if r.isin in kept] for w, g in owed.items()}
        owed = {w: g for w, g in owed.items() if g}

    total = len(todo)
    already = len(everything) - len(todo)
    # WHAT THE NIGHT COSTS, in the unit that moves: a bond that owes one day and
    # a bond that owes thirty both read as "to do", and the whole point of the
    # ledger is the difference between them. Asked-for bond-days against what a
    # window-keyed resume would have asked for, so a regression here is visible
    # in the run log rather than only in a wall clock.
    asked = sum(len(g) * ((w[1] - w[0]).days + 1) for w, g in owed.items())
    flat = len(everything) * ((end - start).days + 1)
    log.info(
        "%s warm: %d bonds to do over %d distinct residual window(s), %d/%d owe "
        "nothing, %d in the manifest overall; %s bond-days asked against %s for "
        "the whole universe over the whole window (%s); values=%s, %s..%s, "
        "Excel %.0f MB, ceiling %.0f",
        mode, total, len(owed), already, len(everything), len(book),
        f"{asked:,}", f"{flat:,}",
        f"{flat / asked:.0f}x less" if asked else "nothing to ask",
        ",".join(wanted), start, end, mem0, ceiling_mb,
    )
    for (w_lo, w_hi), group in sorted(owed.items()):
        log.info("  %d bond(s) owe %s..%s", len(group), w_lo, w_hi)
    if not todo:
        log.info("  nothing to do — the ledger says this window is fully banked")
        return {"mode": mode, "done": 0, "of": 0, "already": len(book),
                "stopped": False, "reason": "", "coverage": {}, "regressed": {}}

    from MDP.CitiVelocityExcel.cache import CitiVeloTagCache, default_cache_dir

    fetcher = CitiVeloBondFetcher()
    quotes = fetcher.quotes()
    # One cache handle for the whole run: its parquet parse is memoised per
    # instance, and the coverage check re-reads a quiet tag once per bond.
    cover_cache = CitiVeloTagCache(base_dir=default_cache_dir())
    coverage: Dict[str, int] = {}
    regressed: Dict[str, List[str]] = {}
    done = tags_done = 0
    stopped_reason = ""
    t_start = time.perf_counter()
    try:
        # One flat list of (fetch window, chunk), so the memory ceiling, the
        # batch numbering and the manifest all still see a single sequence of
        # batches - only now each batch carries the window ITS bonds owe.
        batches = []
        for _w, _group in sorted(owed.items()):
            for _i in range(0, len(_group), batch):
                batches.append((_w[0], _w[1], _group[_i:_i + batch]))

        for bi, (f_start, f_end, chunk) in enumerate(batches):
            # WHAT THIS BATCH MAY RECORD, which is not always what it fetches.
            # An unsettled session is fetched (a partial day is better than no
            # day in the cache) and never banked, so tomorrow asks for it again.
            _bank_hi = _bankable_end(f_end)
            banked_to = ((f_start, _bank_hi)
                         if _bank_hi is not None and _bank_hi >= f_start else None)
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
                # Recorded, but NOTHING BANKED, and that is deliberate. A bond
                # that serves none of the requested values costs no wire at all
                # (there is nothing to ask for), so re-checking it nightly is
                # free - and it is the only way a value the catalog validates
                # later ever gets noticed. Banking here would make "serves
                # nothing" permanent.
                for r in chunk:
                    _record_bond(book, r.isin, stamp=stamp, values=wanted,
                                 fetched=None,
                                 fields={"tags": 0,
                                         "note": "serves none of these values"})
                continue
            # ASK FOR THE REASONS. ``frame`` returns an empty frame and raises
            # nothing whether every tag failed or every tag legitimately held no
            # rows - its own docstring says so - and this loop used to ask for
            # neither, which made a total Velocity outage indistinguishable from
            # a batch of matured bonds. It is only indistinguishable if you do
            # not ask.
            # WHO OWNS WHICH TAG, and which of those bonds was ALIVE in this
            # window. Both are known offline, from the catalog, and that is the
            # whole reason the outage guard below can be trusted: it never has
            # to guess what reason string a dead MI01 chunk produces on the wire.
            tag_owner = {str(t): isin for isin, e in plan.items()
                         for t in e["tags"].values()}
            alive_bonds = {isin for isin in plan
                           if not _retired_before(_maturity_of(plan[isin]), f_start)}
            alive_tags = [t for t in tags if tag_owner.get(str(t)) in alive_bonds]

            # WHAT DID THIS BATCH ACTUALLY NEED, and what did the sidecars look
            # like before anything was asked for? Both are sampled BEFORE the
            # fetch, because both are the "before" half of a comparison the wire
            # cannot fake. See :func:`_sidecar_state`.
            need = _tags_needing_data(cover_cache, tags, freq_token,
                                      start=f_start, end=f_end)
            before = _sidecar_state(cover_cache, tags, freq_token)

            reported: Dict[str, str] = {}
            try:
                if mode == "eod":
                    frame = quotes.frame(tags, "DAILY", start=f_start, end=f_end,
                                         failures=reported)
                    rows_held = int(len(frame)) if frame is not None else 0
                else:
                    rows_held = _warm_intraday(quotes, tags, start=f_start, end=f_end,
                                               failures=reported)
            except Exception as exc:  # noqa: BLE001 - one bad batch must not lose the rest
                stopped_reason = f"{type(exc).__name__}: {exc}"
                log.warning("STOPPING at batch %d: %s", bi, stopped_reason[:200])
                break

            after = _sidecar_state(cover_cache, tags, freq_token)
            persisted = sorted(str(t) for t in tags if after.get(str(t)) != before.get(str(t)))
            log.debug(
                "  batch %d: %d/%d tag(s) needed data, %d sidecar(s) moved, "
                "the cache holds %d row(s) in the window",
                bi, len(need), len(tags), len(persisted), rows_held,
            )

            # DID THE TRANSPORT ANSWER? Asked first, and asked per tag rather
            # than per batch.
            #
            # The version this replaces did ``if faults: break`` - ANY single
            # non-benign reason stopped all 877 bonds. ``block_parser`` writes a
            # per-COLUMN Excel error name for one tag while every other tag in
            # the same call returns normally, and its own module docstring says
            # "a failure is per-tag and must not discard the batch". With 110
            # batches a night, one bad column ended the run.
            #
            # And the reason vocabulary alone cannot settle it. An all-matured
            # MI01 chunk plausibly spills under two rows, which
            # ``parse_tshist_block`` maps to ``"no block"`` for EVERY requested
            # tag - the same string a real outage produces - and the benign
            # ``"empty"`` is only reachable when some OTHER tag in the chunk
            # returned rows, which an all-dead chunk cannot supply. Widening
            # :data:`BENIGN_FAILURE_REASONS` to cover that is failing open again.
            #
            # So the discriminator is MATURITY, which is catalog data and needs
            # no wire at all. A bond that had already redeemed cannot serve this
            # window whatever the add-in says about it, so its failure is not
            # evidence of anything. Only a chunk in which every ALIVE tag failed,
            # over at least :data:`MIN_ALIVE_BONDS_FOR_OUTAGE` alive bonds, is
            # the outage signature. Batch 0 - the 22 lowest ISINs, all matured -
            # therefore cannot stop the run under any reason string, which is the
            # 0/877 abort that cost five of ten retained nightly runs.
            faults = _transport_faults(reported)
            alive_faults = [t for t in alive_tags if str(t) in faults]
            failed_bonds = {tag_owner[str(t)] for t in faults if str(t) in tag_owner}
            alive_failed_bonds = failed_bonds & alive_bonds
            if (alive_tags and len(alive_faults) == len(alive_tags)
                    and len(alive_failed_bonds) >= MIN_ALIVE_BONDS_FOR_OUTAGE):
                shown = ", ".join(f"{t} ({why})" for t, why in sorted(faults.items())[:5])
                stopped_reason = (
                    f"batch {bi}: Velocity FAILED every tag of all "
                    f"{len(alive_failed_bonds)} bond(s) in it that were alive on "
                    f"{f_start} - {shown}"
                    f"{f' and {len(faults) - 5} more' if len(faults) > 5 else ''}. "
                    f"A matured bond cannot explain that: these bonds had not "
                    f"redeemed, so the window is one Velocity should be able to "
                    f"answer. Nothing in this batch is recorded, so a re-run "
                    f"retries it."
                )
                log.error("STOPPING: %s", stopped_reason)
                break
            if faults:
                # Per-tag, not chunk-wide. Recorded and stepped over; the bonds
                # behind the failed tags are deliberately NOT stamped below, so a
                # re-run the same night retries exactly them and nothing else.
                log.warning(
                    "  batch %d: %d of %d tag(s) failed on %d bond(s) - recorded, "
                    "not fatal (%s)",
                    bi, len(faults), len(tags), len(failed_bonds),
                    ", ".join(f"{t} ({why})" for t, why in sorted(faults.items())[:3]),
                )

            # DID ANYTHING REACH THE DISK? The one question neither the reasons
            # nor the returned frame can answer, and the one the fault this whole
            # file exists for turns on.
            #
            # It only means something when the batch NEEDED something. A fully
            # cached window issues no CVTSHIST at all - measured, a client that
            # raises on contact was never touched - so no sidecar can move and no
            # reason can be reported, and reading that as a silent transport
            # would stop the run on the healthiest thing it can encounter.
            #
            # Given the batch did need data: no sidecar moved AND the transport
            # said nothing at all is the signature of a reader that returns
            # cleanly and persists nothing. Velocity answering "there is nothing
            # here" is a different observation - it comes with a reason - and is
            # handled below as coverage, not as a fault.
            if need and not persisted and not reported:
                stopped_reason = (
                    f"batch {bi} asked Velocity for {len(need)} of "
                    f"{len(tags)} tag(s), was told nothing at all, and moved no "
                    f"sidecar in the {freq_token} cache — the transport is not "
                    f"writing to the tag cache. This is the fault that let an "
                    f"earlier version report 349/349 done over zero parquets; it "
                    f"is checked on the DISK because a row count taken from the "
                    f"cache's own re-read cannot see it."
                )
                log.error("STOPPING: %s", stopped_reason)
                break

            # WHAT DOES THE CACHE NOW HOLD FOR THE WINDOW THAT WAS ASKED FOR?
            #
            # Asked after the fetch has had its chance to write and after the
            # transport has been cleared, because it is a question about the
            # DATA and the two guards around it are questions about the wire.
            # It never breaks the loop: a batch whose bonds are quiet is not a
            # fault, and stopping on one would abort every night on the first
            # batch that serves ``CAS``. It is recorded, aggregated, and judged
            # once at the end of the run. See :func:`tag_states`.
            covers = {
                r.isin: tag_states(
                    # start..end, NOT the residual. Coverage is a question
                    # about the DATA and the cache is cumulative, so judging it
                    # on the tail this batch happened to fetch would make the
                    # regression alarm mean something different every night.
                    freq_token, plan[r.isin]["tags"], start=start, end=end,
                    maturity=_maturity_of(plan[r.isin]), cache=cover_cache,
                )
                for r in chunk
            }
            records = {isin: coverage_record(s) for isin, s in covers.items()}
            for states in covers.values():
                for state, _ in states.values():
                    coverage[state] = coverage.get(state, 0) + 1
            for isin, record in records.items():
                # NEW silence, against what the previous run recorded for this
                # same bond. The level cannot drive an alarm - ten value
                # families have been dead since October 2025 and a job that is
                # red every night is a job nobody reads - but a tag that fell
                # silent since last night is exactly the event nothing here
                # could see before.
                fresh = newly_stalled(book.get(isin), record)
                if fresh:
                    regressed[isin] = fresh

            # Bonds one of whose tags the wire refused. Left OUT of the manifest
            # on purpose: stamping them would make a same-night re-run skip the
            # exact bonds that did not warm, which is the resume bug in miniature.
            unstamped = {isin for isin in failed_bonds if isin in plan}

            # A warm is the file on disk, not the call returning. The first
            # version of this script "warmed" 349 bonds intraday in 134 s and
            # left zero MI01 parquets, because the transport it used bypassed the
            # cache — and recorded 349/349 done. Nothing is marked done now until
            # the cache is asked whether it actually holds the tags.
            #
            # The transport-lost-the-cache half of that question is answered
            # above, on the sidecars. What is left here is the DATA question: the
            # cache holds no file at all for these tags. NO rows came back and
            # Velocity said why - which for an MI01 request against a bond that
            # matured in 2016 is the correct and expected answer. 528 of the 877
            # catalogued bonds have matured, ``universe()`` sorts by ISIN, and
            # the 22 lowest ISINs all matured between 2016 and 2025, so with
            # ``DEFAULT_BATCH = 8`` batch 0 is all-dead BY CONSTRUCTION. Treating
            # that as a broken transport aborted the whole 877-bond intraday warm
            # at 0/877 on five of ten retained nightly runs, in 2.9-4.4 s each.
            landed = cached_tags(freq_token, tags)
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
                    bi, len(tags), ", ".join(why),
                )
                # BANKED, unlike the branch above. Velocity was asked for this
                # window and answered that there is nothing in it - which for an
                # MI01 request against a bond that redeemed in 2016 is the
                # correct and permanent answer. 528 of the 877 catalogued bonds
                # have matured; re-asking them every night is the largest single
                # piece of waste this ledger removes.
                for r in chunk:
                    if r.isin in unstamped:
                        continue
                    _record_bond(
                        book, r.isin, stamp=stamp, values=wanted, fetched=banked_to,
                        fields={
                            "tags": 0,
                            "note": "no rows in this window",
                            "why": ", ".join(why),
                            "at": datetime.datetime.now().isoformat(timespec="seconds"),
                            **records[r.isin],
                        },
                    )
                _save_manifest(man)
                continue

            for r in chunk:
                if r.isin in unstamped:
                    continue
                _record_bond(
                    book, r.isin, stamp=stamp, values=wanted, fetched=banked_to,
                    fields={
                        "tags": len(plan[r.isin]["tags"]),
                        "at": datetime.datetime.now().isoformat(timespec="seconds"),
                        # The MEASUREMENT, not a boolean. "Done" used to mean
                        # only "this batch did not abort" - true of a night that
                        # fetched nothing new for a third of the universe.
                        **records[r.isin],
                    },
                )
            done += len(chunk) - len(unstamped & {r.isin for r in chunk})
            tags_done += len(tags)
            _save_manifest(man)          # after EVERY batch: a stop costs one batch
            if (bi) % 5 == 0 or done >= total:
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
    if coverage:
        log.info(
            "  coverage of %s..%s across %d tag(s): %s",
            start, end, sum(coverage.values()),
            ", ".join(f"{state}={n}" for state, n in sorted(coverage.items())),
        )
    quiet_now = coverage.get(STALLED, 0) + coverage.get(ABSENT, 0)
    if quiet_now:
        log.warning(
            "  %d tag(s) are quiet with no explanation — the bond is alive and the "
            "silence is longer than that tag has ever gone quiet for. Not a fault "
            "of this run; see the per-bond 'stalled' lists in %s",
            quiet_now, MANIFEST,
        )
    if regressed:
        shown = "; ".join(
            f"{isin}: {', '.join(vals)}" for isin, vals in sorted(regressed.items())[:5]
        )
        log.error(
            "COVERAGE REGRESSED on %d bond(s) since the last run — %s%s",
            len(regressed), shown,
            f" and {len(regressed) - 5} more" if len(regressed) > 5 else "",
        )
    return {
        "mode": mode, "done": done, "of": total, "tags": tags_done,
        "stopped": bool(stopped_reason), "reason": stopped_reason,
        "mem_before": mem0, "mem_after": mem_end,
        "coverage": coverage, "regressed": regressed,
    }


# ──────────────────────────────────────────────────────────────────────────
# DEPTH: the half a rolling window structurally cannot do
# ──────────────────────────────────────────────────────────────────────────
#
# The nightly window walks FORWARD and only forward. Measured on the real cache
# on 2026-08-20: all 698 MI01 bond tags share ``first = 2026-08-04`` and ``last =
# 2026-08-07`` — one window, banked once by hand on 2026-08-08, never extended by
# anything since. The mechanism is in ``CitiVeloTagCache.missing_spans``: the
# backwards branch is ``want_start < cov.first``, and a nightly ``want_start`` of
# ``end - 2 days`` only ever advances, so after the first successful run it can
# never fire again. Nothing about that is a bug in the nightly. It is a
# capability the shape does not have, and "MI01 for the entire UST universe"
# means history, not a two-day sliding pane.
#
# Why weeks, and why Monday to Friday
# -----------------------------------
# The unit has to be under the measured 6-day MI01 cliff (``windowed.MAX_SPAN``),
# and it has to be STABLE — a grid anchored on "today" moves every night, so a
# window banked on Tuesday is not the window Wednesday asks about, and neither
# the coverage test nor the resume cursor would mean anything twice. A Monday
# 00:00 → Friday 23:59 week is 4 days 23:59 on the wire, sits under the cliff,
# is the same grid every night for ever, and puts the seam in the weekend gap
# rather than mid-session — which is what ``windowed.DEFAULT_WINDOW`` already
# chose for the same reason.
#
# Why a cursor and not the cache frontier
# ---------------------------------------
# Walking ``cov.first`` backwards would extend the head of the cached range and
# never look inside it, and there IS something inside it: the nightly's own
# failures leave interior holes (2026-08-08..2026-08-17 as this ships), and
# ``missing_spans`` inspects only the head and the tail, so an interior gap is
# invisible to the fetch path for ever. The cursor walks the GRID instead and
# tests each week against what the parquet actually holds, so a hole the nightly
# left is filled the first time the cursor passes over it. The cursor is
# monotone, so no week is ever considered twice, which is what lets the coverage
# test be strict (every weekday present) without any risk of a re-fetch loop:
# a week with a market holiday is asked for exactly once, ever.
#
# How many nights the defaults need — the arithmetic, not a feeling
# -----------------------------------------------------------------
# PROJECTED from two measurements, not measured end to end. Both anchors are
# from 2026-08-08 on the cached transport: **349 bonds / 698 tags over a 2-day
# MI01 window cost 48 s and +170 MB**, i.e. 0.24 MB per tag and, at
# ``DEFAULT_BATCH = 8``, 1.09 s per batch of eight bonds.
#
# A Monday-to-Friday week is 5 days against that 2-day anchor, so ~2.5x the rows.
# Round trips dominate the time, so call it 2 s per batch rather than 2.7; the
# memory scales with the rows, so 0.6 MB per tag.
#
# The working set at a 365-day target is NOT all 877 bonds, and that part IS
# measured, offline against the real catalog and cache on 2026-08-20: a bond
# whose anchor (``min(end, maturity)``) already sits below the target has no
# history inside the window and is skipped without a single request. **403 bonds
# qualify at 365 days and 474 are skipped**; at a ten-year target 875 qualify.
# The planning itself is free — ``universe()`` 0.05 s and ``plan`` 0.04 s over
# all 877 — and the per-pass week scan costs 8-20 s while parsing ZERO parquets,
# because the sidecar bounds answer every candidate week before the parquet is
# needed.
#
# So 403 bonds, 806 tags, 51 batches per pass:
#
#   time    51 x 2 s + ~10 s scan = ~112 s per pass -> 600 s / 112 = 5.4 passes
#   memory  806 x 0.6 = 484 MB per pass           -> 2,700 MB / 484 = 5.6 passes
#           (2,700 MB is the 3,500 MB working ceiling over a healthy start;
#            the retained logs put that at 696-2,129 MB on the good nights)
#
# The two bind at the same place, ~5.4 passes a night. One pass is one week per
# bond, so that is ~38 calendar days of depth per bond per night, and the
# 365-day default is reached in
#
#                           ~10 NIGHTS
#
# Widen the target and the working set grows as bonds that redeemed earlier come
# back into scope: at a ten-year target 875 bonds qualify, a pass costs 110
# batches and ~1,050 MB, ~2.6 passes fit in a night, depth accrues at ~18
# calendar days a night, and ten years takes roughly 200 nights. That is the
# honest price of a decade of minutes through one add-in.
#
# The projection is deliberately falsifiable: :func:`backfill_depth` logs the
# bond-weeks it actually banked and the passes it completed on every run, so
# after a week of nightlies this paragraph should be replaced with a measurement.
#
# MEASURED, first production run, 2026-08-21 06:58-07:37
# -------------------------------------------------------
#   1,664 bond-weeks over 5 passes, 1,152,769 rows, 2,319 s
#   Excel 305 -> 3,503 MB;  STOPPED on the ceiling, not the clock
#
# The projection was close on shape and wrong on which constraint binds. It had
# time and memory tying at ~5.4 passes; in fact the run stopped on MEMORY at 64%
# of a 3,600 s budget, so the clock never mattered. Per-pass yield held up well
# (403/400/398/399 bond-weeks, then a 64 stub when the ceiling arrived), so the
# ~400 bond-weeks-per-pass figure is confirmed; what was optimistic is the number
# of passes a single Excel survives.
#
# Cost per unit of depth, which is the number to plan with: 3,198 MB of Excel
# growth over 1,664 bond-weeks is ~0.96 MB per bond-week, roughly 1.6x the
# assumed 0.6. A year for the 403 alive bonds needs 403 x 52 = 20,956 bond-weeks,
# so at 1,664 a run that is
#
#                           ~13 RUNS, not ~10
#
# and the difference is entirely the memory estimate. Note "runs", not "nights":
# since the ceiling binds first, a nightly that restarts Excel mid-job could take
# more than one ceiling's worth per night. It does not today -- the depth pass
# stops rather than restarting -- and whether it should is a real question, not an
# oversight: a restart costs ~2.8 min of sign-in and discards the add-in's warm
# series cache, so two half-full passes are not obviously better than one full one.
#
# One outage strike fired and cleared (2026-06-15..19, strike 1 of 2), which is
# the guard behaving: a bad week costs that week, not the run.
#
# Resolution held everywhere. All 806 tags on disk have a minimum inter-row gap of
# exactly 60 s, so nothing in this run crossed the 6-day MI01 span cliff and
# silently banked 10-minute data.


#: How deep the backwards backfill aims to get, in days before the run date.
#: Overridden by ``CITIVELO_UST_DEPTH_DAYS`` and ``--depth-days``; 0 disables.
#:
#: One year, because that is what the downstream intraday research asks for and
#: because the disk cost is known: 11.21 bytes/row and 886 rows per tag per full
#: weekday were measured over 34,712 tag-days on 2026-08-20, so a year of the
#: 349 alive bonds at PRICE+YIELD is ~1.95 GB and the full 877 is ~4.89 GB. Disk
#: is not the constraint; Excel's memory is.
DEPTH_TARGET_DAYS = 365

#: Wall clock the backwards pass may spend per invocation, in seconds.
#:
#: 600 s against a nightly run that takes 2 h 45 m. It is a budget rather than a
#: bond count because the thing being protected is the SCHEDULE — the other
#: sixteen jobs still have to run — and because the per-window cost is a wire
#: cost nobody controls.
DEPTH_BUDGET_S = 600.0

#: Consecutive empty weeks before a bond is called floored and stops being asked.
#:
#: TWO, not one. Citi's data legitimately stops 1-5 days before a bond redeems
#: (measured over 522 matured USTs: 1 day for 127 of them, 5 for 18, never more),
#: so a matured bond's FIRST backwards week is often the grace tail and holds
#: nothing while every week before it holds a full history. Flooring on one empty
#: week would strand exactly the bonds this pass exists to recover. A week that
#: overlaps that measured tail does not count as a strike at all.
DEPTH_EMPTY_STRIKES = 2

#: Consecutive batches in which every alive tag failed before the pass gives up
#: for the night. Distinct from the floor rule above: this is the wire being
#: down, and a bond must never be recorded floored because of it.
DEPTH_OUTAGE_STRIKES = 2


def _monday_of(day: datetime.date) -> datetime.date:
    """The Monday of ``day``'s week. The grid is anchored on nothing else."""
    return day - datetime.timedelta(days=day.weekday())


def _cached_days(cache, tag: str, freq: str, memo: Dict[str, set]) -> set:
    """The set of calendar dates this tag holds, parsed at most once per pass.

    A parquet parse, so it is asked only after the sidecar bounds say the week
    could be inside the cached range — which for a backwards walk is false for
    almost every week, and true for the handful that matter.
    """
    if tag in memo:
        return memo[tag]
    series = cache.read(tag, freq)
    days = set() if series is None or len(series) == 0 else set(series.index.date)
    memo[tag] = days
    return days


def _cached_bounds(cache, tag: str, freq: str, memo: Dict[str, Optional[tuple]]):
    """``(first, last)`` as dates from the sidecar, or ``None`` when empty."""
    if tag in memo:
        return memo[tag]
    try:
        cov = cache.coverage(str(tag), freq)
    except Exception:  # noqa: BLE001 - an unreadable sidecar means "nothing held"
        cov = None
    if cov is None or cov.first is None or cov.last is None or not cov.n_rows:
        memo[tag] = None
    else:
        memo[tag] = (cov.first.date(), cov.last.date())
    return memo[tag]


def _week_days(monday: datetime.date, maturity: Optional[datetime.date]) -> List[datetime.date]:
    """The weekdays of ``monday``'s week that this bond could have traded on."""
    days = [monday + datetime.timedelta(days=i) for i in range(5)]
    if maturity is not None:
        days = [d for d in days if d <= maturity]
    return days


def next_missing_week(
    cache,
    tags: Sequence[str],
    freq: str,
    *,
    cursor: datetime.date,
    target: datetime.date,
    maturity: Optional[datetime.date],
    day_memo: Dict[str, set],
    bounds_memo: Dict[str, Optional[tuple]],
) -> Optional[Tuple[datetime.date, datetime.date]]:
    """The newest week at or below ``cursor`` the cache does not fully hold.

    "Fully" is every weekday of the week on which the bond could have traded,
    for every tag. Strict on purpose, and safe because the cursor is monotone:
    a week is examined once in the life of the cache, so a holiday week costs
    one extra request forever rather than one per night.

    ``None`` means this bond has nothing left to ask for above ``target``.
    """
    monday = cursor
    while monday >= target:
        if maturity is not None and monday > maturity:
            monday -= datetime.timedelta(days=7)
            continue
        wanted = _week_days(monday, maturity)
        if not wanted:
            monday -= datetime.timedelta(days=7)
            continue
        friday = monday + datetime.timedelta(days=4)
        for tag in tags:
            bounds = _cached_bounds(cache, str(tag), freq, bounds_memo)
            if bounds is None or friday < bounds[0] or monday > bounds[1]:
                return monday, friday          # nothing held anywhere near it
            if not set(wanted) <= _cached_days(cache, str(tag), freq, day_memo):
                return monday, friday          # an interior hole, which is the point
        monday -= datetime.timedelta(days=7)
    return None


def _depth_plan(fetcher, resolutions, values: Sequence[str], chunk: int = 64) -> Dict[str, dict]:
    """``fetcher.plan`` over the whole universe, in pieces. Pure, no wire."""
    out: Dict[str, dict] = {}
    for i in range(0, len(resolutions), chunk):
        out.update(fetcher.plan(resolutions[i:i + chunk], values=list(values)))
    return out


def backfill_depth(
    *,
    end: datetime.date,
    depth_days: int = DEPTH_TARGET_DAYS,
    budget_s: float = DEPTH_BUDGET_S,
    values: Optional[Sequence[str]] = None,
    batch: int = DEFAULT_BATCH,
    ceiling_mb: float = WORKING_CEILING_MB,
    limit: Optional[int] = None,
    force: bool = False,
) -> dict:
    """Walk the universe's MI01 history BACKWARDS, one week per bond per pass.

    Bounded by three separate things, any of which ends the pass cleanly with
    everything banked so far kept and a cursor recording exactly where it got to:

    * ``budget_s`` of wall clock, checked between batches;
    * ``ceiling_mb`` of Excel, checked between batches with the same fail-closed
      probe the forward warm uses — an unreadable reading STOPS, because "could
      not tell" and "nothing running" are different facts;
    * running out of weeks: every bond either reached ``depth_days`` or floored.

    Resumable and idempotent. The cursor is in the manifest, per bond, and the
    coverage test is against the parquets, so re-running the same night finds the
    weeks it already banked and asks the wire for none of them.

    Matured bonds are first-class here, and this is the ONLY path that can ever
    warm them: they can hold no row after they redeemed, so the forward window
    finds nothing for 528 of the 877 for ever, while their history before
    maturity is exactly as real as anyone else's. Their anchor is their maturity
    rather than today, and a week entirely after it is never requested.
    """
    from MDP.CitiVelocityExcel.bonds.fetcher import CitiVeloBondFetcher
    from MDP.CitiVelocityExcel.cache import CitiVeloTagCache, default_cache_dir
    from MDP.CitiVelocityExcel.memory_guard import assert_safe_to_connect, excel_memory_mb

    wanted = tuple(values) if values else INTRADAY_VALUES
    # A ``datetime`` here would compare against ``descriptor.maturity`` (a
    # ``date``) and raise at 18:15 on a scheduled task. The warmer passes a date
    # today; normalising costs nothing and removes the dependency on that.
    end = end.date() if isinstance(end, datetime.datetime) else end
    target = _monday_of(end - datetime.timedelta(days=int(depth_days)))
    mem0 = assert_safe_to_connect(ceiling_mb, what="the UST universe depth backfill")

    man = _load_manifest()
    book = man.setdefault("depth", {})
    everything = universe()
    if limit:
        everything = everything[:limit]

    fetcher = CitiVeloBondFetcher()
    quotes = fetcher.quotes()
    cache = CitiVeloTagCache(base_dir=default_cache_dir())

    by_isin = {r.isin: r for r in everything}
    plan = _depth_plan(fetcher, everything, wanted)

    t_start = time.perf_counter()
    weeks = passes = rows = outage_strikes = 0
    floored_now: List[str] = []
    stopped_reason = ""
    deepest: Optional[datetime.date] = None
    log.info(
        "depth backfill: %d bond(s), target %s (%d days), budget %.0fs, "
        "Excel %.0f MB, ceiling %.0f",
        len(everything), target, depth_days, budget_s, mem0, ceiling_mb,
    )

    try:
        while not stopped_reason:
            # A PASS is "one missing week for every bond that still has one".
            # Memos are per pass, never across: the pass it belongs to is the one
            # that just rewrote the parquets it summarises.
            day_memo: Dict[str, set] = {}
            bounds_memo: Dict[str, Optional[tuple]] = {}
            work: Dict[Tuple[datetime.date, datetime.date], List[str]] = {}
            for isin, entry in plan.items():
                record = book.get(isin, {}) if not force else {}
                if record.get("floor"):
                    continue
                tags = list(entry["tags"].values())
                if not tags:
                    continue
                maturity = _maturity_of(entry)
                anchor = end if maturity is None else min(end, maturity)
                if anchor < target:
                    continue
                raw = record.get("cursor")
                cursor = _monday_of(anchor)
                if raw:
                    try:
                        cursor = min(cursor, datetime.date.fromisoformat(str(raw)))
                    except ValueError:  # a hand-edited cursor restarts the walk
                        pass
                window = next_missing_week(
                    cache, tags, "MI01", cursor=cursor, target=target,
                    maturity=maturity, day_memo=day_memo, bounds_memo=bounds_memo,
                )
                if window is None:
                    # Nothing left above the target. Recorded so ``status`` can
                    # tell "finished" from "never started", and so the 528
                    # matured bonds stop looking permanently un-warm.
                    book[isin] = {**record, "cursor": target.isoformat(),
                                  "complete": True,
                                  "at": datetime.datetime.now().isoformat(timespec="seconds")}
                    continue
                work.setdefault(window, []).append(isin)

            if not work:
                log.info("  depth backfill: nothing left to ask for above %s", target)
                break

            passes += 1
            pass_weeks = 0
            # Batched BY WINDOW. Bonds whose cursors have converged - which after
            # the first pass is most of the alive universe - share one CVTSHIST.
            for window in sorted(work, reverse=True):
                monday, friday = window
                isins = work[window]
                for i in range(0, len(isins), batch):
                    if stopped_reason:
                        break
                    chunk = isins[i:i + batch]
                    spent = time.perf_counter() - t_start
                    if spent >= budget_s:
                        stopped_reason = (
                            f"the {budget_s:.0f}s depth budget is spent "
                            f"({weeks} week(s) banked over {passes} pass(es))"
                        )
                        log.info("  depth backfill stopping cleanly: %s", stopped_reason)
                        break
                    try:
                        mem = excel_memory_mb()
                    except Exception:  # noqa: BLE001
                        mem = None
                    if mem is None:
                        stopped_reason = "could not read Excel's memory (fails closed)"
                        log.warning("  depth backfill stopping: %s", stopped_reason)
                        break
                    if mem >= ceiling_mb:
                        stopped_reason = (
                            f"Excel reached {mem:.0f} MB (ceiling {ceiling_mb:.0f})"
                        )
                        log.warning("  depth backfill stopping: %s", stopped_reason)
                        break

                    tags = [t for isin in chunk for t in plan[isin]["tags"].values()]
                    tag_owner = {str(t): isin for isin in chunk
                                 for t in plan[isin]["tags"].values()}
                    alive_bonds = {isin for isin in chunk
                                   if not _retired_before(_maturity_of(plan[isin]), monday)}
                    alive_tags = [t for t in tags if tag_owner[str(t)] in alive_bonds]
                    before = _sidecar_state(cache, tags, "MI01")
                    reported: Dict[str, str] = {}
                    try:
                        rows += _warm_intraday(quotes, tags, start=monday, end=friday,
                                               failures=reported, force=True)
                    except Exception as exc:  # noqa: BLE001
                        stopped_reason = f"{type(exc).__name__}: {exc}"
                        log.warning("  depth backfill stopping: %s", stopped_reason[:200])
                        break
                    after = _sidecar_state(cache, tags, "MI01")

                    # The same discrimination the forward warm makes, for the
                    # same reason: a chunk-wide failure over ALIVE bonds is the
                    # wire, and anything narrower is not. A bond must never be
                    # recorded floored on a night the wire was down, so an
                    # outage batch records NOTHING - not a cursor, not a strike.
                    faults = _transport_faults(reported)
                    alive_failed = {tag_owner[str(t)] for t in alive_tags if str(t) in faults}
                    if (alive_tags
                            and len([t for t in alive_tags if str(t) in faults]) == len(alive_tags)
                            and len(alive_failed) >= MIN_ALIVE_BONDS_FOR_OUTAGE):
                        outage_strikes += 1
                        log.warning(
                            "  depth backfill: every alive tag failed for %s..%s "
                            "(strike %d of %d)",
                            monday, friday, outage_strikes, DEPTH_OUTAGE_STRIKES,
                        )
                        if outage_strikes >= DEPTH_OUTAGE_STRIKES:
                            stopped_reason = (
                                f"{outage_strikes} consecutive batches in which every "
                                f"alive tag failed - the wire, not the data. No bond "
                                f"is recorded floored on such a night."
                            )
                            log.warning("  depth backfill stopping: %s", stopped_reason)
                            break
                        continue
                    outage_strikes = 0

                    now = datetime.datetime.now().isoformat(timespec="seconds")
                    for isin in chunk:
                        record = dict(book.get(isin, {}))
                        own = [str(t) for t in plan[isin]["tags"].values()]
                        landed = any(after.get(t) != before.get(t) for t in own)
                        failed = any(t in faults for t in own)
                        if failed and not landed:
                            # Not stamped: the cursor does not move, so the next
                            # run asks for this same week again. A per-tag wire
                            # failure must cost a retry, not a hole.
                            continue
                        record["cursor"] = (monday - datetime.timedelta(days=7)).isoformat()
                        record["at"] = now
                        record["weeks"] = int(record.get("weeks", 0)) + 1
                        record.pop("complete", None)
                        maturity = _maturity_of(plan[isin])
                        in_grace = (
                            maturity is not None
                            and friday >= maturity - MATURITY_GRACE
                        )
                        if landed:
                            record["empty"] = 0
                            record["deepest"] = monday.isoformat()
                        elif in_grace:
                            # The measured 1-5 day tail before a redemption. Not
                            # evidence about anything below it.
                            record["empty"] = int(record.get("empty", 0))
                        else:
                            record["empty"] = int(record.get("empty", 0)) + 1
                            if record["empty"] >= DEPTH_EMPTY_STRIKES:
                                record["floor"] = monday.isoformat()
                                record["why"] = ", ".join(
                                    sorted({str(w) for w in reported.values()})
                                ) or "nothing served"
                                floored_now.append(isin)
                        book[isin] = record
                        if landed and (deepest is None or monday < deepest):
                            deepest = monday
                    weeks += len(chunk)
                    pass_weeks += len(chunk)
                    _save_manifest(man)
                if stopped_reason:
                    break
            log.info(
                "  depth pass %d: %d bond-week(s), %d floored so far, %.0fs of %.0fs",
                passes, pass_weeks, len(floored_now),
                time.perf_counter() - t_start, budget_s,
            )
            if not pass_weeks:
                if outage_strikes and not stopped_reason:
                    # Everything this pass tried, failed, over alive bonds. On a
                    # big universe the strike counter reaches its limit inside
                    # the pass; on a small one - or on the last few bonds still
                    # walking - the pass simply runs out of work first, and a
                    # pass that banked nothing because every request failed is
                    # the same observation. It must be said out loud, because the
                    # alternative is a green run over a wire that answered
                    # nothing.
                    stopped_reason = (
                        f"every alive tag failed on every batch this pass "
                        f"({outage_strikes} batch(es)) - the wire, not the data. "
                        f"No bond is recorded floored on such a night."
                    )
                    log.warning("  depth backfill stopping: %s", stopped_reason)
                break
    finally:
        _save_manifest(man)
        fetcher.close()

    elapsed = time.perf_counter() - t_start
    try:
        mem_end = excel_memory_mb()
    except Exception:  # noqa: BLE001
        mem_end = None
    # The number that turns the projection in the commit message into a
    # measurement. Logged every night, so after a week nobody has to estimate.
    log.info(
        "depth backfill finished: %d bond-week(s) over %d pass(es), %d row(s), "
        "%d newly floored, %.0fs, Excel %.0f -> %s MB%s",
        weeks, passes, rows, len(floored_now), elapsed, mem0,
        f"{mem_end:.0f}" if mem_end is not None else "?",
        f" (STOPPED: {stopped_reason})" if stopped_reason else "",
    )
    return {
        "weeks": weeks, "passes": passes, "rows": rows, "bonds": len(by_isin),
        "floored": sorted(floored_now), "deepest": deepest,
        "target": target, "seconds": elapsed,
        "stopped": bool(stopped_reason), "reason": stopped_reason,
        "mem_before": mem0, "mem_after": mem_end,
    }


def status() -> None:
    """What the manifest says is warm, without touching Excel.

    Now also what it says is QUIET, which is the half that was unreadable
    before: a bond count against a window told you a request went out, not that
    anything came back for it. The ``stalled`` lists are per bond and per value,
    so ``status`` can name the value families that stopped rather than leaving a
    reader to notice that a number never moves.
    """
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
        stalled: Dict[str, int] = {}
        for entry in book.values():
            for value in entry.get("stalled") or ():
                stalled[value] = stalled.get(value, 0) + 1
        if stalled:
            n_bonds = sum(1 for e in book.values() if e.get("stalled"))
            print(f"            quiet with no explanation: {n_bonds} bond(s), by value:")
            for value, n in sorted(stalled.items(), key=lambda kv: (-kv[1], kv[0])):
                print(f"              {value:<18} {n:>4} bond(s)")

    depth = man.get("depth", {})
    if depth:
        floored = sum(1 for e in depth.values() if e.get("floor"))
        complete = sum(1 for e in depth.values() if e.get("complete"))
        weeks = sum(int(e.get("weeks", 0)) for e in depth.values())
        deepest = sorted(str(e["deepest"]) for e in depth.values() if e.get("deepest"))
        print(f"     depth: {len(depth)}/{n_uni} bonds walked, {weeks} bond-week(s), "
              f"{complete} at target, {floored} floored")
        if deepest:
            print(f"            deepest week reached: {deepest[0]}; "
                  f"shallowest bond still walking: {deepest[-1]}")
        cursors = sorted(str(e["cursor"]) for e in depth.values() if e.get("cursor"))
        if cursors:
            print(f"            cursors span {cursors[0]} .. {cursors[-1]}")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                        datefmt="%H:%M:%S")
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("mode", choices=["eod", "intraday", "depth", "status", "refresh"])
    p.add_argument("--depth-days", type=int,
                   default=int(os.environ.get("CITIVELO_UST_DEPTH_DAYS", DEPTH_TARGET_DAYS)),
                   help=f"how far back the backwards backfill aims (default {DEPTH_TARGET_DAYS})")
    p.add_argument("--depth-budget-s", type=float,
                   default=float(os.environ.get("CITIVELO_UST_DEPTH_BUDGET_S", DEPTH_BUDGET_S)),
                   help=f"wall clock the backwards backfill may spend (default {DEPTH_BUDGET_S:.0f})")
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
    if args.mode == "depth":
        out = backfill_depth(
            end=args.end or datetime.date.today(),
            depth_days=args.depth_days, budget_s=args.depth_budget_s,
            values=args.values, batch=args.batch, ceiling_mb=args.ceiling_mb,
            limit=args.limit, force=args.force,
        )
        # A spent budget is the DESIGNED outcome, not a partial failure: the pass
        # is meant to run out of time every night until the target is reached, so
        # exiting 2 for it would make the nightly permanently amber. Only a stop
        # that needs a human - the ceiling, an unreadable probe, a dead wire -
        # earns a code.
        if out.get("stopped") and "budget" not in out.get("reason", ""):
            sys.exit(2)
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
    if out.get("regressed"):
        # 1 is "a real defect, read the log" in the parent warmer's own three-code
        # scheme, and a tag that fell silent since the last run is exactly that.
        # The LEVEL deliberately does not come here: ten value families have been
        # dead since 2025-10-03 and 2025-11-28, and a job that exits 1 every night
        # for them is the always-1 exit code the parent warmer's docstring says
        # nobody reads. The level goes to the log and to ``status``; only the
        # CHANGE reaches the scheduler.
        sys.exit(1)


if __name__ == "__main__":
    main()
