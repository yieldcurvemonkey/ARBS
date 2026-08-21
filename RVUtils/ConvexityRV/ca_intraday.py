r"""Transport and guards for the **intraday** convexity adjustment.

The daily CA (``TB.IRSwapsTB.sfr_cvx_adj``) marks a futures leg against a swap
leg at the 17:00 New York settle. The intraday CA marks the same difference at a
one-minute instant. Everything in this module exists because those two series
must never touch each other, and because reaching the intraday one by accident
costs a vendor crawl.

THE TAPE IS SPELLED TWO WAYS AND ONLY TWO SPELLINGS HIT
========================================================
``STIRFutureMDP._get_data_for_timestamp`` resolves an intraday request by
**exact string match** against a list of candidate diskcache keys. There is no
nearest-snapshot rule and no tolerance: a key one character different is a miss,
and a miss on this source goes to Barchart.

The candidate list it builds is, in order, the instant as **UTC** isoformat
(three near-identical spellings) and then the request **exactly as the caller
spelled it**. So the reachable key space is ``{UTC iso, caller's-tz iso}`` --
and the SR3 minute tape on this machine is written in *both*, by different
writers at different times. Scanned 2026-08-20 over all 12,772,278 keys of
``BARCHART_TOS_LIVE_STIRF-RL`` (1,667 dates, 2018-05-31..2026-08-20), the
offset each key carries:

======  ===========  ===========  ===========  ==========
year     ``+00:00``   ``-06:00``   ``-05:00``   ``-04:00``
======  ===========  ===========  ===========  ==========
2018        197,483            1          481           0
2019        345,250            4          989           0
2020        346,631            4          619           0
2021        112,793          940           90          96
2022            197            0           49          48
2023          1,975            0           17          43
2024            191            1            1          68
2025            254            0           42         105
2026         77,962       52,478      123,029         558
======  ===========  ===========  ===========  ==========

2018-2021 is a UTC tape; 2026 is predominantly a **Chicago** tape (``-06:00``
in winter, ``-05:00`` in summer -- CME's own zone) with a UTC tape beside it.
741 of the 1,667 dates carry more than one family.

The two families are the same instants, not two clocks: on the 41 dates that
carry both densely, reading ``SR3U26`` at the same instant through the CT key
and through the UTC key returned the identical price on every date checked
(96.74 / 96.76 / 96.725 / 96.715 / 96.75, ``family_agree.py``). So probing both
spellings is safe, and probing only one silently halves the reachable universe.

What is *not* safe is any other spelling. Measured 2026-08-20, one symbol
(``SR3U26``), one instant (2026-08-19 15:00 ET), inside
``listed_cache_guard.cache_only()``:

=====================  ===============================  =========  ===============
request spelling       key the MDP looks for            price      network blocked
=====================  ===============================  =========  ===============
``ZoneInfo`` Chicago   ``2026-08-19T14:00:00-05:00``    96.2175    **0**
``ZoneInfo`` New York  ``2026-08-19T15:00:00-04:00``    --         **20**
naive (Chicago wall)   ``2026-08-19T14:00:00``          --         **20**
=====================  ===============================  =========  ===============

(UTC missed on *that* instant because that date's UTC family does not cover it;
it is a first-class candidate in general.) All three name the same instant. Two
of them are a Barchart crawl. That is why :func:`tape_instant` refuses a naive
datetime rather than localising one -- ``STIRFutureMDP._as_datetime`` localises
naive input to *New York*, so a caller who meant CME wall-clock silently moves
an hour -- and why the zone is a ``ZoneInfo`` name and never a fixed offset.

There is a **third** family and it is deliberately unreachable. 558 of 2026's
254,027 keys (0.22%) carry ``-04:00`` -- New York summer -- written by some other
job. ``2026-08-19T14:00:00-04:00`` is 13:00 Chicago, a *different instant* from
the ``14:00:00-05:00`` key one character away, so admitting that family would
mean deciding which of two plausible instants a request meant. It is not
probed. The consequence is absence (a few minutes cannot be reached), which is
the safe half of the trade.

REACHABILITY IS A JOINT PROPERTY, AND IT IS A 2026 PRODUCT
===========================================================
An intraday CA needs both legs at the same instant. The minute CURVE store
(``USD-SOFR-1D-CITIVELOEXCELMIN``) holds 1,543 days from 2021-09-14; the SR3
minute tape holds 1,667 dates from 2018-05-31. They overlap on **678 dates** --
and on all but 181 of those the futures tape is 2-5 stamps for the whole day,
which is a point, not a series. Measured 2026-08-20:

======  ===========  =========================  ===============================
year     joint dates  WHITES/REDS/GREENS at      dates with >=300 minute stamps
                      15:00 ET                   (a usable intraday series)
======  ===========  =========================  ===============================
2021             77                          5                                0
2022            105                          1                                0
2023             77                         12                                0
2024             78                          0                                0
2025            149                          0                                0
2026            192                        155                              181
======  ===========  =========================  ===============================

``BLUES`` (needs contiguous depth 16) reaches 68 dates at 15:00 ET, all of them
2026. ``GOLDS`` (needs 20) and ``SILVERS`` (needs 24) reach **zero** dates in
every year: the tape's deepest contiguous front strip anywhere in the local
slice is **17**. That is why the API raises for those ranks instead of quietly
serving a shallower pack.

PREFLIGHT, DON'T PROBE-BY-FETCHING
===================================
``cache_only()`` turns a miss into an exception, which is safe but not cheap in
attention: one missing WHITES leg is ~20 blocked calls and a traceback. So the
order here is inverted -- :func:`tape_depth` reads the diskcache keys directly
and reports what is present, and ``get_data`` is called only for instants where
every requested leg's key has already been verified. The verified key **is** the
provenance: the pricer object the MDP returns exposes only a reference
``date`` (``RLSTIRFuturePricer._reference_date``), never the minute, so "which
instant was served" cannot be recovered downstream and has to be pinned upstream.

WHY THE SPLICE GUARD IS STRUCTURAL RATHER THAN ADVISORY
========================================================
The intraday-vs-settle basis on the same date is the same order of magnitude as
the CA itself, so one settle row inside an intraday series is not noise -- it is
a different measurement wearing the same column name. Two mechanisms keep them
apart:

* every intraday row carries :data:`PRICE_SOURCE_INTRADAY` in a ``price_source``
  column, and :func:`concat_ca_frames` refuses to concatenate frames that do not
  agree on it (an *untagged* frame is treated as a settle frame, which is the
  safe direction: the daily path emits untagged frames today);
* the intraday path writes **nothing** -- not the mapping cache, not
  ``data/ts``. It cannot, safely: ``IRSwapsTB._ts_symbol_for_query`` is
  ``IRS::{source}::{curve}::{fingerprint}`` and ``market_request`` is not part of
  ``_query_fingerprint`` (pinned in
  ``tests/test_convexity_rv_intraday_ca.py``), so an intraday row and a settle
  row for the same instrument would land in the *same* ``data/ts`` symbol and be
  read back as one series.
"""

from __future__ import annotations

import datetime
from typing import Any, Callable, Iterable, List, Optional, Sequence, Set

import pandas as pd

from RVUtils.ConvexityRV.strat2_sofr_convexity import (
    INTRADAY_SOURCE_MARKERS,
    LIVE_SOURCE,
)

__all__ = [
    "TAPE_TZ_NAME",
    "INTRADAY_FUTURES_SOURCE",
    "SETTLE_FUTURES_SOURCE",
    "PRICE_SOURCE_INTRADAY",
    "PRICE_SOURCE_SETTLE",
    "LIVE_QUOTE_GUARD_MINUTES",
    "PRICE_SOURCE_COL",
    "IntradayTimestampError",
    "IntradaySpliceError",
    "IntradayRankUnavailable",
    "assert_intraday_source",
    "tape_instant",
    "tape_keys",
    "tape_key",
    "served_tape_key",
    "key_stamp",
    "assert_offline_instant",
    "mdp_key_probe",
    "tape_present",
    "tape_depth",
    "price_source_of",
    "assert_single_price_source",
    "concat_ca_frames",
    "tag_settle_frame",
]

#: The zone the SR3 one-minute diskcache keys are written in. A **name**, not an
#: offset: the tape stamps ``-06:00`` in winter and ``-05:00`` in summer, and a
#: frozen offset is a half-year-long silent cache miss.
TAPE_TZ_NAME = "America/Chicago"

#: The intraday quote feed. Same string as
#: :data:`RVUtils.ConvexityRV.strat2_sofr_convexity.LIVE_SOURCE`; re-exported
#: under a name that says what it is *for* here rather than what it is banned
#: from there.
INTRADAY_FUTURES_SOURCE = LIVE_SOURCE

#: The 17:00 New York settle source the daily path uses.
SETTLE_FUTURES_SOURCE = "BARCHART_STIRF-RL"

#: Row tags. These are the values of the ``price_source`` column and the whole
#: basis of the splice guard, so they are constants rather than literals.
PRICE_SOURCE_INTRADAY = f"{INTRADAY_FUTURES_SOURCE}@minute"
PRICE_SOURCE_SETTLE = f"{SETTLE_FUTURES_SOURCE}@17:00"

PRICE_SOURCE_COL = "price_source"

#: ``STIRFutureMDP._should_use_live_quotes`` returns True for any datetime
#: within **15 minutes** of now, and that sets ``read_cache = False`` -- so a
#: perfectly cached minute inside that window still goes to the live quote API,
#: which is both network *and* a third price source (Schwab) in a series that
#: claims to be Barchart minute bars. Guarded at 20 minutes for margin.
LIVE_QUOTE_GUARD_MINUTES = 20


class IntradayTimestampError(ValueError):
    """A requested instant cannot be served from the minute tape safely."""


class IntradaySpliceError(ValueError):
    """An attempt to put intraday quotes and settles in one series."""


class IntradayRankUnavailable(LookupError):
    """A requested pack rank is not reachable on the intraday tape, ever."""


# ===========================================================================
# Source pinning
# ===========================================================================
def assert_intraday_source(source: str, *, field: str = "futures_source") -> str:
    """Raise unless *source* is an intraday quote feed.

    The exact inverse of
    :func:`RVUtils.ConvexityRV.strat2_sofr_convexity.assert_settle_source`, and
    it shares that function's marker list so the two can never disagree about
    which token is which. Pinning the source is not decoration: the settle
    source resolves a ``datetime`` request by falling back to its own EOD
    behaviour, so an intraday call under ``BARCHART_STIRF-RL`` would return a
    number -- the 17:00 one -- with no error at all.
    """
    s = str(source)
    up = s.upper()
    if not any(m in up for m in INTRADAY_SOURCE_MARKERS):
        raise ValueError(
            f"{field}={s!r} is not an intraday quote feed. The intraday convexity "
            f"adjustment marks its futures leg at a one-minute instant; a settle "
            f"source answers with the 17:00 mark and does not say so. Use "
            f"{INTRADAY_FUTURES_SOURCE!r}."
        )
    return s


# ===========================================================================
# Instants and keys
# ===========================================================================
def tape_instant(ts: Any) -> datetime.datetime:
    """Normalise *ts* to the tape's own wall clock: Chicago, floored to a minute.

    A **naive** datetime raises rather than being localised. ``_as_datetime``
    in ``STIRFutureMDP`` localises a naive stamp to *New York*, so a caller who
    meant Chicago wall-clock and passed it naive gets a one-hour error and a
    cache miss; and a caller who meant New York gets a cache miss too. Neither
    is recoverable from the value, so neither is guessed at here.
    """
    from zoneinfo import ZoneInfo                                # noqa: PLC0415

    if isinstance(ts, str):
        raise IntradayTimestampError(
            f"timestamp {ts!r} is a string; pass a tz-aware datetime. The "
            "'live'/'now' sentinels reach the vendor, not the tape."
        )
    if not isinstance(ts, datetime.datetime):
        raise IntradayTimestampError(
            f"timestamp {ts!r} ({type(ts).__name__}) is not a datetime. A "
            "date means the 17:00 settle, which is the daily path."
        )
    if ts.tzinfo is None or ts.tzinfo.utcoffset(ts) is None:
        raise IntradayTimestampError(
            f"timestamp {ts.isoformat()} is naive. The SR3 minute tape is keyed "
            f"by {TAPE_TZ_NAME} wall clock and STIRFutureMDP localises a naive "
            "stamp to America/New_York, so a naive request misses the cache and "
            "goes to Barchart (measured: 20 blocked calls for one symbol). Pass "
            "a tz-aware datetime."
        )
    out = pd.Timestamp(ts).tz_convert(ZoneInfo(TAPE_TZ_NAME)).floor("min")
    return out.to_pydatetime()


def tape_keys(ts: Any, ticker: str, *, source: str = INTRADAY_FUTURES_SOURCE) -> List[str]:
    """Every diskcache key ``STIRFutureMDP`` will look for, in ITS order.

    Reproduces the candidate list built in
    ``STIRFutureMDP._get_data_for_timestamp`` for a tz-aware intraday request:
    the UTC-normalised spelling first (``_cache_ts_iso`` converts to UTC when the
    request is tz-aware and the source is a Barchart intraday one), then
    ``ts_exact_local_iso`` -- the request as the caller spelled it, which here is
    always the tape's own Chicago wall clock because :func:`tape_instant` has
    normalised it.

    Both are needed. Neither family covers the store on its own: the tape is UTC
    for 2018-2021 and predominantly Chicago for 2026 (module docstring).
    """
    inst = tape_instant(ts)
    src = str(source).upper()
    local_iso = pd.Timestamp(inst).isoformat()
    utc_iso = pd.Timestamp(inst).tz_convert("UTC").isoformat()
    out: List[str] = []
    for iso in (utc_iso, local_iso):
        k = f"{iso}-{ticker}-{src}"
        if k not in out:
            out.append(k)
    return out


def tape_key(ts: Any, ticker: str, *, source: str = INTRADAY_FUTURES_SOURCE) -> str:
    """The **Chicago-spelled** key -- the one recorded as this row's provenance.

    Always a real key when :func:`tape_present` says the symbol is there? No --
    the hit may have been on the UTC spelling. Use :func:`served_tape_key` when
    the answer must be the key that actually resolved.
    """
    return tape_keys(ts, ticker, source=source)[-1]


def served_tape_key(
    probe: Callable[[str], bool],
    ts: Any,
    ticker: str,
    *,
    source: str = INTRADAY_FUTURES_SOURCE,
) -> Optional[str]:
    """The first candidate key that is actually present, or ``None``.

    This is the provenance a row records. It has to be measured rather than
    assumed because the pricer object the MDP hands back exposes only a
    reference **date** (``RLSTIRFuturePricer._reference_date``) and never the
    minute, so nothing downstream can say which instant it was marked at.
    """
    for k in tape_keys(ts, ticker, source=source):
        if probe(k):
            return k
    return None


def key_stamp(
    key: str,
    ticker: str,
    *,
    source: str = INTRADAY_FUTURES_SOURCE,
) -> pd.Timestamp:
    """The instant a diskcache key names, as a UTC ``Timestamp``.

    The inverse of :func:`tape_key`, and it exists to be *asserted with*: the
    two key spellings for one instant are different strings, so "did every leg
    resolve to the same minute" can only be answered by parsing them back to a
    common representation. Splitting on ``f"-{ticker}-"`` rather than on ``"-"``
    is deliberate -- the ISO prefix is full of hyphens.
    """
    suffix = f"-{ticker}-{str(source).upper()}"
    if not key.endswith(suffix):
        raise ValueError(f"key {key!r} does not end with {suffix!r}")
    return pd.Timestamp(key[: -len(suffix)]).tz_convert("UTC")


def assert_offline_instant(
    ts: Any,
    *,
    guard_minutes: float = LIVE_QUOTE_GUARD_MINUTES,
    now: Optional[datetime.datetime] = None,
) -> datetime.datetime:
    """Refuse an instant close enough to now that the MDP switches to live quotes.

    Returns the tape-normalised instant on success.
    """
    inst = tape_instant(ts)
    ref = now or datetime.datetime.now(datetime.timezone.utc)
    if ref.tzinfo is None:
        raise IntradayTimestampError("`now` must be tz-aware")
    lag = abs((pd.Timestamp(inst) - pd.Timestamp(ref)).total_seconds())
    if lag <= float(guard_minutes) * 60.0:
        raise IntradayTimestampError(
            f"{pd.Timestamp(inst).isoformat()} is {lag / 60.0:.1f} min from now; "
            f"STIRFutureMDP._should_use_live_quotes() treats anything within 15 "
            f"min as LIVE, which sets read_cache=False and answers from the "
            f"Schwab quote API -- network, and a different price source in a "
            f"series that claims to be Barchart minute bars. Guard is "
            f"{guard_minutes:g} min."
        )
    return inst


# ===========================================================================
# Preflight: what is actually on the tape at this instant
# ===========================================================================
def mdp_key_probe(futures_mdp: Any) -> Callable[[str], bool]:
    """A ``key -> bool`` probe over the STIR pricer diskcache.

    Uses the MDP's own accessor so the probe reads the same store the fetch
    would, including its pending-write layer. It never fetches: a miss is
    ``None``.
    """
    get = futures_mdp._threadsafe_cache_get            # noqa: SLF001 - the only reader

    def _probe(key: str) -> bool:
        try:
            return get(key) is not None
        except Exception:                              # noqa: BLE001
            return False

    return _probe


def tape_present(
    probe: Callable[[str], bool],
    ts: Any,
    symbols: Iterable[str],
    *,
    source: str = INTRADAY_FUTURES_SOURCE,
) -> Set[str]:
    """Which of *symbols* have a minute bar at exactly this instant, either spelling."""
    return {
        s for s in symbols
        if any(probe(k) for k in tape_keys(ts, s, source=source))
    }


def tape_depth(
    probe: Callable[[str], bool],
    ts: Any,
    ordered_symbols: Sequence[str],
    *,
    source: str = INTRADAY_FUTURES_SOURCE,
) -> int:
    """Length of the **contiguous** front strip present at this instant.

    Contiguity, not a count: a pack is four *consecutive* contracts, so "11 of
    the first 13 present" overstates what can be quoted. Stops at the first
    absence and returns immediately -- there is no reason to probe past a hole.
    """
    depth = 0
    for s in ordered_symbols:
        if not any(probe(k) for k in tape_keys(ts, s, source=source)):
            break
        depth += 1
    return depth


# ===========================================================================
# The splice guard
# ===========================================================================
def price_source_of(df: pd.DataFrame) -> str:
    """The single price source a CA frame speaks for.

    An **untagged** frame is reported as :data:`PRICE_SOURCE_SETTLE`, not as
    "unknown". That is the safe direction and it is not a guess: the daily path
    is the only producer of untagged CA frames in this repo and it is settle-
    marked by construction (``get_barchart_timeseries(interval=None)``).
    """
    if PRICE_SOURCE_COL not in df.columns:
        return PRICE_SOURCE_SETTLE
    vals = sorted({str(v) for v in df[PRICE_SOURCE_COL].dropna().unique()})
    if not vals:
        return PRICE_SOURCE_SETTLE
    if len(vals) > 1:
        raise IntradaySpliceError(
            f"frame already mixes price sources {vals}; a convexity adjustment "
            "is a difference between two legs marked at the SAME instant, so a "
            "series carrying both a minute quote and a 17:00 settle is not a "
            "series."
        )
    return vals[0]


def assert_single_price_source(df: pd.DataFrame, expected: Optional[str] = None) -> str:
    """Assert *df* speaks for one price source, optionally a named one."""
    got = price_source_of(df)
    if expected is not None and got != expected:
        raise IntradaySpliceError(
            f"price_source is {got!r}, expected {expected!r}."
        )
    return got


def concat_ca_frames(frames: Sequence[pd.DataFrame], **kwargs: Any) -> pd.DataFrame:
    """``pd.concat`` that refuses to build a spliced series.

    The measured reason: on 2026-08-19 the SR3 settle strip and the 15:00 ET
    minute strip disagree by up to 2.5 ticks on a single contract, and the WHITES
    CA computed off each differs by 0.53 bp against a CA level of 0.25-0.78 bp.
    Splicing them does not add noise to a signal; it interleaves two signals.
    """
    frames = [f for f in frames if f is not None and len(f)]
    if not frames:
        return pd.DataFrame()
    sources = {price_source_of(f) for f in frames}
    if len(sources) > 1:
        raise IntradaySpliceError(
            f"refusing to concatenate CA frames from {sorted(sources)}. Intraday "
            "quotes and 17:00 settles are different measurements of the same "
            "name; keep them in separate series and compare them explicitly."
        )
    return pd.concat(frames, **kwargs)


def tag_settle_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Stamp a daily (settle) CA frame with its price source, as a **copy**.

    Provided so the guard can be applied to both series without changing what
    ``sfr_cvx_adj`` returns. Its output is deliberately untouched -- adding a
    column there would change every caller's frame shape, and stashing the tag
    in ``DataFrame.attrs`` is not a guarantee because ``attrs`` propagation
    through ``concat``/``merge`` is version-dependent.
    """
    out = df.copy()
    out[PRICE_SOURCE_COL] = PRICE_SOURCE_SETTLE
    return out
