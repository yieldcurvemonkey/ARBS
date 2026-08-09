r"""Warm the computed-timeseries cache with minute-resolution Citi Velocity IRS structures.

This is the pricing sibling of ``scripts/citivelo_excel_intraday_warm.py``. That
script fills the **CurveStore** with one solved curve per published minute; this
one prices structures off those curves and fills the **ComputedTimeseriesStore**,
so a notebook asking for::

    ts.get_timeseries(start=..., end=..., queries=[UnifiedQuery(curve="USD-SOFR-1D",
        tenor="5y/10y/30y", value=UnifiedValue.IRS_RATE)], freq="1min",
        routers={"IRS": IRSwapsTB(mdp)})

returns in seconds off disk instead of repricing 781 minutes.

Where the time actually goes (measured 2026-08-08, USD-SOFR-1D, 2026-07-29)
--------------------------------------------------------------------------
Curve acquisition is already solved. ``IRSwapsMDP.bulk_get_data`` serves 781
warmed minute curves in **1.3 s (1.6 ms/curve)**; it is not the problem. Pricing
is:

===================  =========  =========
structure            ms/point   note
===================  =========  =========
``10y``                  12.9   one leg
``5y/10y``               38.4   two legs
``5y/10y/30y``          126.7   three legs, 30y is the expensive one
===================  =========  =========

Three measurements set this script's whole shape:

1. **``ARBS_RL_OMIT_UNUSED_FIXINGS`` is worth 8.7x** and costs 1.8e-15 bp
   (max |delta| over 120 points, 10y). Nearly all of a ``rate()`` call is the
   RFR fixings lookup for observations a spot-starting swap never consumes. The
   warm turns it on; see :data:`OMIT_UNUSED_FIXINGS_DEFAULT`.
2. **Threads do not help.** Measured 1440 pricings across a 6-tenor mix:
   1 worker 531/s, 2 workers 624/s, 4 workers 468/s, 8 workers 323/s. The loop is
   GIL-bound, so ``n_jobs`` is left at 1 and parallelism is a **process pool over
   days** - the shape ``citivelo_excel_intraday_warm build`` already proved.
3. **Curves and flies are arithmetic on outrights.** Pricing only the outrights
   and deriving the rest turns a 3-leg fly from 127 ms into a subtraction: run
   cost is O(outrights), not O(structures). The weights and the formula are
   ``IRSwapsTB._decompose_rate_into_outright_legs`` and its ``sum(w * abs(leg)) *
   100``, and ``verify`` checks the derived numbers against directly-priced ones
   rather than trusting that.

Every structure is MATERIALISED rather than left to be derived on read
----------------------------------------------------------------------
``IRSwapsTB.get_timeseries`` contains exactly this synthesis - build a cached
``a/b/c`` out of cached legs - and **it cannot fire**. Its guard skips any query
carrying ``structure_kwargs['notional']``, and ``IRSwapQuery`` populates that with
``1_000_000`` on every query ever constructed, so the branch is unreachable. That
is worth knowing before relying on it, because the fallback is not "reprice the
one structure": ``get_timeseries`` reprices EVERY query in the batch at any
reference point where ANY query is uncached. Measured on this data, one uncached
uppercase fly in an 8-query cell took the read from 0.4 s to 374 s.

So the warm writes each structure under both the lowercase spelling and
``.upper()``. Deriving is free, storage is the only cost, and it means a caller
gets the cache whichever way they spell it. Mixed spellings (``5Yx5Y``) are not
pre-warmed - the pair is the tenor as listed and its uppercase form.

Days are independent, and each worker owns a whole day. That is what makes
concurrent writes safe: the Parquet tier partitions by ``date=YYYY-MM-DD`` under
each symbol, so two workers on two days never touch one directory. Workers open
the store with ``use_duckdb=False`` - the DuckDB and row-level L2 tiers are keyed
``(symbol, date)`` and the writer already refuses intraday rows for them, so
turning it off changes nothing except removing N processes contending for one
DuckDB write lock.

Citi's published swap spread
----------------------------
``UnifiedValue.IRS_CITIVELO_SWAP_SPREAD`` is a **quote**, not a computation: it
reads ``RATES.OIS.USD_SOFR.SWAP_SPREAD.<tenor>`` at the curve's own instant. Two
consequences the rest of this file is built around.

*It needs Excel, once.* ``fetch-spreads`` pulls the MI01 tag history through
``fetch_windowed`` in <=4-day chunks (``CVTSHIST`` silently downsamples a request
spanning more than six days) into the ``CitiVeloTagCache``. Measured 2026-08-08,
MI01 ``SWAP_SPREAD`` serves true 1-minute data at every probe from T-30d back to
**T-1460d** - the full span of the minute CurveStore - so the axis is not the
limit; Excel time is.

*Workers must be unable to reach Excel.* The value map builds its own quotes
object when the caller passes none, and ``quotes=``/``offline=`` cannot be passed
through ``value_kwargs`` without changing the query fingerprint that keys the
cache - a warm keyed on ``{"offline": True}`` is a symbol no user query ever
reads. So the parent slices the day's rows out of the tag cache, ships them in the
task, and the worker installs them with
``swap_spreads.set_default_quotes``; ``set_force_offline(True)`` is the belt to
that braces, making a COM connect impossible rather than unlikely.

Usage::

    conda run -n stir python scripts/citivelo_intraday_ts_warm.py plan
    conda run -n stir python scripts/citivelo_intraday_ts_warm.py fetch-spreads \
        --start 2022-08-29 --end 2026-08-07
    conda run -n stir python scripts/citivelo_intraday_ts_warm.py verify --date 2026-07-29
    conda run -n stir python scripts/citivelo_intraday_ts_warm.py warm --workers 10
    conda run -n stir python scripts/citivelo_intraday_ts_warm.py status
"""

from __future__ import annotations

# MUST precede any Caching import, and is re-applied in every spawned worker:
# ComputedTimeseriesStore.append_many_rows background-pushes day blobs to the
# prod Supabase L2 otherwise. Sync deliberately, later, via scripts/citivelo_l2_sync.py.
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import argparse
import contextlib
import datetime
import gc
import hashlib
import io
import json
import logging
import subprocess
import sys
import time
import zoneinfo
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

LOGGER = logging.getLogger("citivelo_intraday_ts_warm")

#: The MDP source token. Embedded verbatim in every cache symbol
#: (``IRS::{source}::{curve}::{sha1}``), so it must be spelled the way callers
#: spell it or the warm fills symbols nobody reads.
SOURCE = "citivelo_excel_rl"

CURVE = "USD-SOFR-1D"
CITI_INDEX = "USD_SOFR"

#: Where the minute curves live. Written by ``citivelo_excel_intraday_warm``.
MINUTE_ASSET = f"{CURVE}-CITIVELOEXCELMIN"

#: The curves are stamped in their own zone; for USD that is the wire zone too.
LOCAL_TZ = "America/New_York"

#: 1.8e-15 bp for 8.7x. See the module docstring.
OMIT_UNUSED_FIXINGS_DEFAULT = True

#: Rows dated later than ``today - _STALE_THRESHOLD_DAYS`` are evicted from the
#: read cache and repriced on every read, so warming them is work that throws
#: itself away. ``IRSwapsTB._STALE_THRESHOLD_DAYS`` is 2; stop at 2 days back.
STALE_LAG_DAYS = 2


# ---------------------------------------------------------------------------
# the structure universe
# ---------------------------------------------------------------------------
#
# Spelled LOWERCASE because the fingerprint that keys the cache does not
# normalise case - ``10y`` and ``10Y`` hash to two different symbols and print
# two different column names - and lowercase is what the notebooks and the
# reference request in this repo actually type. ``--case-aliases`` additionally
# writes the UPPERCASE outright symbols, which costs storage but no pricing (the
# same number is written twice) and makes an uppercase CURVE or FLY free as well:
# the reader synthesises those from uppercase legs.

SPOT_TENORS: Tuple[str, ...] = (
    "1m", "2m", "3m", "4m", "5m", "6m", "9m",
    "1y", "15m", "18m", "21m",
    "2y", "3y", "4y", "5y", "6y", "7y", "8y", "9y", "10y",
    "11y", "12y", "15y", "20y", "25y", "30y", "40y", "50y",
)

#: ``<forward>x<tenor>``. Every one lands inside the curve's 50-year node span.
FORWARD_TENORS: Tuple[str, ...] = (
    "3mx1y", "3mx2y", "3mx5y", "3mx10y",
    "6mx1y", "6mx2y", "6mx5y", "6mx10y",
    "1yx1y", "1yx2y", "1yx3y", "1yx5y", "1yx10y", "1yx20y", "1yx30y",
    "2yx1y", "2yx2y", "2yx3y", "2yx5y", "2yx10y",
    "3yx1y", "3yx2y", "3yx5y", "3yx7y",
    "5yx1y", "5yx2y", "5yx5y", "5yx10y", "5yx15y", "5yx25y",
    "7yx3y",
    "10yx1y", "10yx2y", "10yx5y", "10yx10y", "10yx20y",
    "15yx15y",
    "20yx10y",
    "25yx5y",
)

OUTRIGHT_TENORS: Tuple[str, ...] = SPOT_TENORS + FORWARD_TENORS

_SPOT_CURVE_PAIRS: Tuple[Tuple[str, str], ...] = (
    ("3m", "1y"), ("3m", "2y"), ("3m", "5y"),
    ("6m", "1y"), ("6m", "2y"), ("6m", "5y"),
    ("1y", "2y"), ("1y", "3y"), ("1y", "5y"), ("1y", "10y"), ("1y", "30y"),
    ("2y", "3y"), ("2y", "5y"), ("2y", "7y"), ("2y", "10y"),
    ("2y", "15y"), ("2y", "20y"), ("2y", "30y"),
    ("3y", "5y"), ("3y", "7y"), ("3y", "10y"), ("3y", "30y"),
    ("4y", "5y"),
    ("5y", "7y"), ("5y", "10y"), ("5y", "15y"), ("5y", "20y"), ("5y", "30y"),
    ("7y", "10y"), ("7y", "30y"),
    ("10y", "12y"), ("10y", "15y"), ("10y", "20y"), ("10y", "30y"), ("10y", "50y"),
    ("15y", "20y"), ("15y", "30y"),
    ("20y", "30y"), ("20y", "50y"),
    ("30y", "50y"),
)

_SPOT_FLY_TRIPLES: Tuple[Tuple[str, str, str], ...] = (
    ("3m", "6m", "1y"), ("6m", "1y", "2y"),
    ("1y", "2y", "3y"), ("1y", "2y", "5y"), ("1y", "3y", "5y"),
    ("1y", "5y", "10y"), ("1y", "10y", "30y"),
    ("2y", "3y", "5y"), ("2y", "3y", "10y"), ("2y", "5y", "10y"),
    ("2y", "5y", "30y"), ("2y", "7y", "10y"), ("2y", "10y", "30y"),
    ("3y", "5y", "7y"), ("3y", "5y", "10y"), ("3y", "7y", "10y"), ("3y", "10y", "30y"),
    ("5y", "7y", "10y"), ("5y", "10y", "15y"), ("5y", "10y", "20y"),
    ("5y", "10y", "30y"), ("5y", "15y", "30y"),
    ("7y", "10y", "20y"), ("7y", "10y", "30y"),
    ("10y", "15y", "20y"), ("10y", "15y", "30y"), ("10y", "20y", "30y"),
    ("10y", "30y", "50y"),
    ("15y", "20y", "30y"), ("20y", "30y", "50y"),
)

_FWD_CURVE_PAIRS: Tuple[Tuple[str, str], ...] = (
    ("3mx1y", "6mx1y"), ("3mx2y", "6mx2y"), ("3mx5y", "6mx5y"), ("3mx10y", "6mx10y"),
    ("1yx1y", "2yx1y"), ("2yx1y", "3yx1y"), ("1yx1y", "3yx1y"),
    ("1yx1y", "5yx1y"), ("1yx1y", "10yx1y"),
    ("1yx2y", "2yx2y"), ("2yx2y", "3yx2y"), ("1yx2y", "3yx2y"),
    ("1yx5y", "2yx5y"), ("2yx5y", "5yx5y"), ("1yx5y", "5yx5y"), ("5yx5y", "10yx5y"),
    ("1yx10y", "2yx10y"), ("2yx10y", "5yx10y"), ("5yx10y", "10yx10y"),
    ("1yx10y", "10yx10y"),
    ("1yx1y", "5yx5y"), ("2yx2y", "5yx5y"), ("5yx5y", "10yx10y"),
    ("10yx10y", "20yx10y"), ("5yx5y", "5yx25y"), ("10yx10y", "15yx15y"),
)

_FWD_FLY_TRIPLES: Tuple[Tuple[str, str, str], ...] = (
    ("1yx1y", "2yx1y", "3yx1y"), ("1yx1y", "3yx1y", "5yx1y"),
    ("2yx1y", "3yx1y", "5yx1y"),
    ("1yx2y", "2yx2y", "3yx2y"),
    ("1yx5y", "2yx5y", "5yx5y"), ("1yx5y", "5yx5y", "10yx5y"),
    ("1yx10y", "2yx10y", "5yx10y"), ("2yx10y", "5yx10y", "10yx10y"),
    ("1yx1y", "5yx5y", "10yx10y"), ("2yx2y", "5yx5y", "10yx10y"),
    ("5yx5y", "10yx10y", "20yx10y"), ("3mx1y", "6mx1y", "1yx1y"),
)


def _structure_tenors() -> Tuple[str, ...]:
    """Every derived (curve/fly) tenor string, in a stable order."""
    out: List[str] = []
    for pair in _SPOT_CURVE_PAIRS + _FWD_CURVE_PAIRS:
        out.append("/".join(pair))
    for triple in _SPOT_FLY_TRIPLES + _FWD_FLY_TRIPLES:
        out.append("/".join(triple))
    return tuple(out)


STRUCTURE_TENORS: Tuple[str, ...] = _structure_tenors()

#: Citi's published SWAP_SPREAD axis for USD_SOFR, uppercase because that is what
#: ``swap_spread_tenors("USD_SOFR")`` returns and therefore what a caller passes.
SWAP_SPREAD_TENORS: Tuple[str, ...] = (
    "1M", "3M", "6M", "1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y",
)


def _assert_universe_is_closed() -> None:
    """Every derived leg must be an outright we actually price.

    A typo here is invisible at runtime - the structure would simply produce no
    rows, and a warm that quietly wrote 106 of 108 structures looks exactly like
    one that wrote all of them.
    """
    known = set(OUTRIGHT_TENORS)
    missing = sorted(
        {leg for tenor in STRUCTURE_TENORS for leg in tenor.split("/")} - known
    )
    if missing:
        raise AssertionError(
            f"citivelo_intraday_ts_warm: {len(missing)} derived leg(s) are not in "
            f"OUTRIGHT_TENORS and would silently produce no rows: {missing}"
        )


_assert_universe_is_closed()


# ---------------------------------------------------------------------------
# config, ledger, progress
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WarmConfig:
    curve: str = CURVE
    source: str = SOURCE
    omit_unused_fixings: bool = OMIT_UNUSED_FIXINGS_DEFAULT
    case_aliases: bool = True
    structures: bool = True
    swap_spreads: bool = True
    ts_base_dir: Optional[str] = None
    outrights: Tuple[str, ...] = OUTRIGHT_TENORS
    derived: Tuple[str, ...] = STRUCTURE_TENORS
    spread_tenors: Tuple[str, ...] = SWAP_SPREAD_TENORS

    def fingerprint(self) -> str:
        """Hash of everything that changes what a completed day CONTAINS.

        The ledger stores it per day so a config change re-runs that day instead
        of leaving a run that is half one universe and half another - which no
        later reader could tell apart from a complete one.
        """
        payload = {
            # Bumped when the MEANING of a flag changes without the flag itself
            # changing - v2 made ``case_aliases`` cover derived structures, not
            # just outrights, and a ledger written at v1 would otherwise claim
            # those days were complete.
            "v": 2,
            "curve": self.curve,
            "source": self.source,
            "omit": bool(self.omit_unused_fixings),
            "aliases": bool(self.case_aliases),
            "outrights": list(self.outrights),
            "derived": list(self.derived) if self.structures else [],
            "spreads": list(self.spread_tenors) if self.swap_spreads else [],
        }
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]

    def expected_symbols(self) -> int:
        n = len(self.outrights)
        if self.case_aliases:
            n += sum(1 for t in self.outrights if t.upper() != t)
        if self.structures:
            n += len(self.derived)
            if self.case_aliases:
                n += sum(1 for t in self.derived if t.upper() != t)
        if self.swap_spreads:
            n += len(self.spread_tenors)
        return n


@dataclass
class DayStat:
    date: str
    status: str = "ok"
    minutes: int = 0
    priced_rows: int = 0
    derived_rows: int = 0
    spread_rows: int = 0
    symbols: int = 0
    elapsed: float = 0.0
    error: Optional[str] = None
    cfg: str = ""


#: Statuses that mean "this day is finished, do not come back to it".
#:
#: ``non_business`` and ``empty`` are as final as ``ok``: the first is a Sunday or
#: a holiday, whose reference points USD-SOFR-1D filters away by design, and the
#: second is a store day that turned out to hold no minutes. Retrying either on
#: every run costs a little and, worse, keeps them in the "not done" count, so a
#: complete run never reads as complete.
TERMINAL_STATUSES = frozenset({"ok", "non_business", "empty"})


class Ledger:
    """Append-only JSONL of completed days. Resume reads it; nothing else does."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def completed(self, *, cfg_fingerprint: str) -> Dict[datetime.date, DayStat]:
        out: Dict[datetime.date, DayStat] = {}
        if not self.path.is_file():
            return out
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:  # noqa: BLE001 - a torn last line must not be fatal
                    continue
                if row.get("cfg") != cfg_fingerprint:
                    continue
                if row.get("status") not in TERMINAL_STATUSES:
                    # Append-only, so an earlier success line is still on disk.
                    # A later failure must un-complete the day, or a re-run that
                    # went wrong would be skipped on the strength of the run
                    # before it.
                    try:
                        out.pop(_parse_date(str(row.get("date", ""))), None)
                    except Exception:  # noqa: BLE001 - an unparseable date is not a day
                        pass
                    continue
                try:
                    day = _parse_date(str(row["date"]))
                except Exception:  # noqa: BLE001
                    continue
                out[day] = DayStat(**row)
        return out

    def record(self, stat: DayStat) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(stat), separators=(",", ":")) + "\n")


@dataclass
class Progress:
    total_days: int
    started: float = field(default_factory=time.time)
    days_done: int = 0
    rows: int = 0
    minutes: int = 0
    errors: int = 0
    skipped: int = 0

    def record(self, stat: DayStat) -> None:
        self.days_done += 1
        self.rows += stat.priced_rows + stat.derived_rows + stat.spread_rows
        self.minutes += stat.minutes
        if stat.status == "ok":
            return
        # A Sunday is not a failure, and counting it as one buries the failures.
        if stat.status in TERMINAL_STATUSES:
            self.skipped += 1
        else:
            self.errors += 1

    def heartbeat(self) -> str:
        elapsed = max(time.time() - self.started, 1e-9)
        pct = 100.0 * self.days_done / self.total_days if self.total_days else 100.0
        rate = self.days_done / (elapsed / 60.0)
        eta = ((self.total_days - self.days_done) / rate * 60.0) if rate > 0 else 0.0
        return (
            f"day {self.days_done}/{self.total_days} ({pct:.1f}%) "
            f"rows={self.rows:,} minutes={self.minutes:,} "
            f"errors={self.errors} skipped={self.skipped} "
            f"({self.rows / elapsed:,.0f} rows/s) elapsed={elapsed / 60:.1f}m "
            f"eta={eta / 60:.1f}m mem={_rss_mb():.0f}MB"
        )


def _rss_mb() -> float:
    try:
        import psutil

        return psutil.Process().memory_info().rss / 1e6
    except Exception:  # noqa: BLE001
        return 0.0


def free_gb(path: Union[str, Path]) -> float:
    """Free space on the volume holding ``path``, or ``inf`` if it cannot be read.

    ``inf`` on failure is deliberate and is the ONE place in this file that fails
    open: a probe that cannot answer must not stop a healthy run, and the caller
    still has the ledger. Everything else here fails closed.
    """
    try:
        import shutil

        target = Path(path)
        while not target.exists() and target.parent != target:
            target = target.parent
        return shutil.disk_usage(target).free / 1e9
    except Exception:  # noqa: BLE001
        return float("inf")


def _parse_date(value: str) -> datetime.date:
    return datetime.date.fromisoformat(str(value).strip())


# ---------------------------------------------------------------------------
# the minute grid
# ---------------------------------------------------------------------------


def session_minutes(store: Any, day: datetime.date) -> List[datetime.datetime]:
    """The curve-local minutes this day actually holds, as tz-aware datetimes.

    Taken from the store's OWN stamps rather than from a synthetic
    ``pd.date_range``. Two reasons, both measured:

    * Sessions are not a fixed window - 2025-01-02 runs 01:00-18:59 local and
      2026-06-22 runs 01:00-22:59 - so any hardcoded window either truncates
      good minutes or asks for minutes that do not exist.
    * The 2022 tail is 10-minute data. A 1-minute grid over it would request ten
      instants per snapshot, and the nearest-snapshot loader would serve the same
      curve to all ten, writing ten identical rows carrying one observation.

    The cache key is the UTC-normalised instant (``_normalize_intraday_key``), so
    a caller's ``freq="1min"`` grid in any timezone hits these rows exactly.
    """
    frame = store.read_raw_nodes(MINUTE_ASSET, start=day, end=day)
    if frame is None or frame.empty or "timestamp_utc" not in frame.columns:
        return []
    stamps = pd.to_datetime(frame["timestamp_utc"], utc=True, errors="coerce").dropna()
    if stamps.empty:
        return []
    local = stamps.dt.tz_convert(LOCAL_TZ).dt.floor("min")
    unique = sorted(set(local))
    zone = zoneinfo.ZoneInfo(LOCAL_TZ)
    return [ts.to_pydatetime().astimezone(zone) for ts in unique]


def store_days(
    store: Any,
    *,
    start: Optional[datetime.date],
    end: Optional[datetime.date],
) -> List[datetime.date]:
    days = [pd.Timestamp(d).date() for d in store.available_dates(MINUTE_ASSET)]
    if start is not None:
        days = [d for d in days if d >= start]
    if end is not None:
        days = [d for d in days if d <= end]
    return sorted(days)


def default_end() -> datetime.date:
    return datetime.date.today() - datetime.timedelta(days=STALE_LAG_DAYS)


# ---------------------------------------------------------------------------
# Citi's published swap spread - the day slice shipped to each worker
# ---------------------------------------------------------------------------


class DayQuotes:
    """A frozen ``CitiVeloQuotes``-shaped view over one day's tag rows.

    The duck type is exactly what ``fetch_swap_spreads(quotes=...)`` documents, so
    the value map runs its real code path - the as-of search, the staleness
    guard, the spot-start check - and only the data source is narrowed. Installed
    process-wide via ``swap_spreads.set_default_quotes`` because ``quotes=``
    cannot be routed through ``value_kwargs`` without changing the cache key.
    """

    __slots__ = ("_frame",)

    def __init__(self, frame: pd.DataFrame):
        self._frame = frame

    def frame(
        self,
        tags: Sequence[str],
        freq: str,
        *,
        start: Any = None,
        end: Any = None,
        price_point: str = "CLOSE",
        force_refresh: bool = False,
    ) -> pd.DataFrame:
        _ = freq, price_point, force_refresh
        cols = [t for t in tags if t in self._frame.columns]
        out = self._frame.loc[:, cols]
        if start is not None:
            out = out.loc[out.index >= pd.Timestamp(start)]
        if end is not None:
            out = out.loc[out.index <= pd.Timestamp(end)]
        return out

    def close(self) -> None:  # pragma: no cover - nothing to release
        return None


def swap_spread_tags(tenors: Sequence[str]) -> Dict[str, str]:
    from MDP.IRSwaps.CITIVELO_EXCEL.swap_spreads import swap_spread_tag

    return {t: swap_spread_tag(CITI_INDEX, t) for t in tenors}


def load_spread_series(tenors: Sequence[str]) -> pd.DataFrame:
    """Every cached MI01 SWAP_SPREAD tag, as one wide naive-wire-stamped frame.

    Read ONCE in the parent. Each worker gets a per-day slice in its task, which
    keeps ~1.4M rows/tag out of N worker processes and off the pricing path.
    """
    from MDP.CitiVelocityExcel.cache import CitiVeloTagCache

    cache = CitiVeloTagCache()
    series: Dict[str, pd.Series] = {}
    for tag in swap_spread_tags(tenors).values():
        cached = cache.read(tag, "MI01")
        if cached is None or cached.empty:
            continue
        series[tag] = cached
    if not series:
        return pd.DataFrame()
    return pd.DataFrame(series).sort_index()


def _spread_lookback() -> datetime.timedelta:
    from MDP.IRSwaps.CITIVELO_EXCEL.swap_spreads import LOOKBACK_BY_MODE

    return LOOKBACK_BY_MODE["intraday"]


def _spread_max_staleness() -> datetime.timedelta:
    from MDP.IRSwaps.CITIVELO_EXCEL.fetcher import DEFAULT_MAX_STALENESS

    return DEFAULT_MAX_STALENESS


def fresh_spread_minutes(
    minutes: Sequence[datetime.datetime],
    spread_slice: pd.DataFrame,
    tags: Mapping[str, str],
    *,
    max_staleness: Optional[datetime.timedelta] = None,
) -> Dict[str, List[datetime.datetime]]:
    """``{tenor: minutes}`` where Citi's print is fresh enough for THAT tenor.

    Citi publishes SWAP_SPREAD only during its session, but the minute CurveStore
    holds the Sunday-evening open and the small hours - so a Monday 01:44 curve
    exists while the newest 30Y print is Friday 17:59, 55.8 hours back. The value
    map REFUSES that, correctly (``StaleCurveError``, 12-hour limit), and it
    refuses it one (tenor, minute) at a time inside ``IRSwapsTB``, which logs a
    full traceback for each. So the warm asks only for what will be served.

    **Per tenor, not per minute.** The obvious version tested "does this slice have
    a row here" with ``dropna(how="all")`` on the assumption that eleven tags
    fetched in one CVTSHIST call share their stamps. Measured on 2024-09-23 01:44
    they do not: 1M/3M/6M/1Y carry prints while 2Y through 30Y are NaN, so a
    row-level test passed the minute and the seven long tenors raised anyway. The
    money-market tenors genuinely trade in those hours; collapsing to an
    all-tenors rule would have thrown their coverage away to silence the others.

    This changes no value - it applies the value map's own 12-hour rule ahead of
    it, vectorised, per tag.
    """
    if spread_slice is None or spread_slice.empty or not minutes:
        return {}

    from MDP.IRSwaps.CITIVELO_EXCEL.timestamps import to_wire_naive

    limit = max_staleness if max_staleness is not None else _spread_max_staleness()
    wanted = pd.DatetimeIndex([to_wire_naive(m) for m in minutes])

    out: Dict[str, List[datetime.datetime]] = {}
    for tenor, tag in tags.items():
        if tag not in spread_slice.columns:
            continue
        published = spread_slice[tag].dropna().index
        if published.empty:
            continue
        position = published.searchsorted(wanted, side="right") - 1
        keep = [
            minute
            for minute, wire, pos in zip(minutes, wanted, position)
            if pos >= 0 and (wire - published[pos]) <= limit
        ]
        if keep:
            out[tenor] = keep
    return out


def slice_spreads_for_day(
    frame: pd.DataFrame, day: datetime.date, *, lookback: datetime.timedelta
) -> pd.DataFrame:
    """``[day 00:00 - lookback, day+1 00:00]`` in naive wire time.

    The lookback is the fetch window ``swap_spreads._window`` asks for, carried
    over verbatim: cutting the slice at the day boundary would make the session's
    first minutes look like they had no print at all.
    """
    if frame.empty:
        return frame
    lo = pd.Timestamp(datetime.datetime.combine(day, datetime.time())) - lookback
    hi = pd.Timestamp(datetime.datetime.combine(day + datetime.timedelta(days=1), datetime.time()))
    return frame.loc[(frame.index >= lo) & (frame.index <= hi)]


# ---------------------------------------------------------------------------
# derivation - a curve or a fly from its cached outright legs
# ---------------------------------------------------------------------------

#: The reader's own weights, from ``IRSwapsTB._decompose_rate_into_outright_legs``.
_LEG_WEIGHTS: Dict[int, Tuple[float, ...]] = {2: (-1.0, 1.0), 3: (-1.0, 2.0, -1.0)}


def decompose(tenor: str) -> Optional[Tuple[Tuple[float, str], ...]]:
    """``((weight, leg), ...)`` for an ``a/b`` or ``a/b/c`` RATE tenor, else None."""
    tokens = [t.strip() for t in str(tenor).split("/") if t.strip()]
    weights = _LEG_WEIGHTS.get(len(tokens))
    if weights is None or len(tokens) != str(tenor).count("/") + 1:
        return None
    return tuple(zip(weights, tokens))


def derive_value(legs: Sequence[Tuple[float, str]], leg_values: Dict[str, float]) -> Optional[float]:
    """The reader's formula, verbatim: ``sum(w * abs(leg)) * 100``.

    ``abs()`` is not a rounding of the sign - it is what
    ``IRSwapsTB.get_timeseries`` does when it synthesises the same value from
    cached legs, and reproducing it is the point: a derived row that disagreed
    with the reader's own synthesis would surface as a value that changes
    depending on whether the structure happened to be cached. It is wrong for a
    NEGATIVE outright rate (CHF, JPY), which is why this script is USD-only;
    ``verify`` re-checks derived against directly-priced numbers every run.
    """
    total = 0.0
    for weight, leg in legs:
        value = leg_values.get(leg)
        if value is None:
            return None
        total += weight * abs(value)
    return total * 100.0


# ---------------------------------------------------------------------------
# worker
# ---------------------------------------------------------------------------

_WORKER: Dict[str, Any] = {}


def _init_worker(cfg_dict: Dict[str, Any]) -> None:
    # Windows spawns a fresh interpreter per worker, so the parent's environment
    # assignment does NOT carry over - this line is the one that actually keeps
    # a pool of processes from background-pushing to prod Supabase.
    os.environ["ARBS_SUPABASE_ENABLED"] = "0"
    os.environ["ARBS_CITIVELO_QUOTES_OFFLINE"] = "1"

    cfg = WarmConfig(**{k: (tuple(v) if isinstance(v, list) else v) for k, v in cfg_dict.items()})

    from MDP.IRSwaps.CITIVELO_EXCEL import swap_spreads as ss_mod
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from Query.IRSwaps.backends.rateslib import RLIRSwapCurve as rl_mod
    from TB.IRSwapsTB import IRSwapsTB

    rl_mod.set_omit_unused_fixings(bool(cfg.omit_unused_fixings))
    # Belt to the ARBS_CITIVELO_QUOTES_OFFLINE brace: N pool workers racing COM
    # into the one shared Excel is how the add-in gets driven into an access
    # violation, so make it impossible rather than unlikely.
    ss_mod.set_force_offline(True)

    mdp = IRSwapsMDP(source=cfg.source)
    tb = IRSwapsTB(
        mdp,
        show_tqdm=False,
        use_ts_cache=True,
        # The DuckDB and row-level L2 tiers are keyed (symbol, date) and the
        # writer already refuses intraday rows for them, so this removes N
        # processes contending for one DuckDB write lock and changes nothing else.
        use_duckdb=False,
        ts_base_dir=cfg.ts_base_dir or "./data/ts",
    )
    _WORKER.update({"cfg": cfg, "mdp": mdp, "tb": tb})


def _price_outrights(tb: Any, cfg: WarmConfig, minutes: List[datetime.datetime]) -> pd.DataFrame:
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapValue import IRSwapValue

    queries = [
        IRSwapQuery(curve=cfg.curve, tenor=tenor, value=IRSwapValue.RATE)
        for tenor in cfg.outrights
    ]
    return tb.get_timeseries(
        start=minutes[0],
        end=minutes[-1],
        queries=queries,
        timestamps=list(minutes),
        n_jobs=1,
        ignore_cache=False,
    )


def _price_swap_spreads(
    tb: Any, cfg: WarmConfig, minutes: List[datetime.datetime], spread_slice: pd.DataFrame
) -> int:
    """Price Citi's published spread through the real value map. Returns row count."""
    from MDP.IRSwaps.CITIVELO_EXCEL import swap_spreads as ss_mod
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapValue import IRSwapValue

    if spread_slice is None or spread_slice.empty:
        return 0

    # Only ask for tenors whose tag is in the slice, at minutes their own tag was
    # published near. A missing tag does not return NaN - it raises inside the
    # pricing loop, where IRSwapsTB logs a full traceback per (tenor, minute).
    tag_by_tenor = swap_spread_tags(cfg.spread_tenors)
    by_tenor = fresh_spread_minutes(minutes, spread_slice, tag_by_tenor)
    if not by_tenor:
        return 0

    # Tenors that share a minute set share a request. Measured, the axis falls
    # into two or three such groups - the money-market tenors print in hours the
    # long end does not - so this is a couple of calls a day, not eleven.
    groups: Dict[Tuple[datetime.datetime, ...], List[str]] = {}
    for tenor, usable in by_tenor.items():
        groups.setdefault(tuple(usable), []).append(tenor)

    written = 0
    ss_mod.set_default_quotes(DayQuotes(spread_slice))
    try:
        for usable, tenors in groups.items():
            queries = [
                IRSwapQuery(
                    curve=cfg.curve, tenor=tenor, value=IRSwapValue.CITIVELO_SWAP_SPREAD
                )
                for tenor in tenors
            ]
            frame = tb.get_timeseries(
                start=usable[0],
                end=usable[-1],
                queries=queries,
                timestamps=list(usable),
                n_jobs=1,
                ignore_cache=False,
            )
            if not frame.empty:
                written += int(frame.notna().to_numpy().sum())
    finally:
        ss_mod.set_default_quotes(None)
    return written


def _alias_and_derived_rows(
    tb: Any, cfg: WarmConfig, priced: pd.DataFrame
) -> Tuple[Dict[str, List[Tuple[Any, str, float]]], int, int]:
    """Uppercase outright aliases and every derived structure, as store rows."""
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapValue import IRSwapValue

    if priced.empty:
        return {}, 0, 0

    by_tenor: Dict[str, pd.Series] = {}
    for tenor in cfg.outrights:
        column = IRSwapQuery(curve=cfg.curve, tenor=tenor, value=IRSwapValue.RATE).col_name(cfg.curve)
        if column in priced.columns:
            by_tenor[tenor] = priced[column].dropna()

    rows_by_symbol: Dict[str, List[Tuple[Any, str, float]]] = {}
    alias_rows = 0
    derived_rows = 0

    def _emit(tenor: str, series: pd.Series) -> int:
        """Write ``series`` under ``tenor``'s symbol. Returns the row count."""
        query = IRSwapQuery(curve=cfg.curve, tenor=tenor, value=IRSwapValue.RATE)
        rows = [(stamp, query.col_name(cfg.curve), float(value)) for stamp, value in series.items()]
        if not rows:
            return 0
        rows_by_symbol[tb._ts_symbol_for_query(cfg.curve, query)] = rows
        return len(rows)

    if cfg.case_aliases:
        for tenor, series in by_tenor.items():
            if tenor.upper() != tenor:
                alias_rows += _emit(tenor.upper(), series)

    if cfg.structures:
        frame = pd.DataFrame(by_tenor)
        for tenor in cfg.derived:
            legs = decompose(tenor)
            if legs is None:
                continue
            if any(leg not in frame.columns for _w, leg in legs):
                continue
            sub = frame.loc[:, [leg for _w, leg in legs]].dropna()
            if sub.empty:
                continue
            values = sum(weight * sub[leg].abs() for weight, leg in legs) * 100.0
            derived_rows += _emit(tenor, values)
            # The UPPERCASE spelling is a separate symbol and would otherwise be
            # repriced - and not only itself. IRSwapsTB reprices EVERY query in a
            # batch at any reference point where ANY query is uncached, so one
            # uppercase fly in a notebook cell drags nine warmed columns back
            # through the pricer with it (measured: 374 s versus 0.4 s). The
            # shortcut that was supposed to cover this - synthesising a cached
            # a/b/c from cached legs - cannot fire: its guard skips any query
            # carrying structure_kwargs['notional'], and IRSwapQuery defaults
            # that to 1,000,000 on every query ever built. Deriving costs no
            # pricing, so the second spelling is written rather than relied on.
            if cfg.case_aliases and tenor.upper() != tenor:
                alias_rows += _emit(tenor.upper(), values)

    return rows_by_symbol, alias_rows, derived_rows


def warm_one_day(task: Tuple[datetime.date, List[datetime.datetime], Any]) -> DayStat:
    day, minutes, spread_slice = task
    cfg: WarmConfig = _WORKER["cfg"]
    tb = _WORKER["tb"]
    started = time.time()
    stat = DayStat(date=day.isoformat(), minutes=len(minutes), cfg=cfg.fingerprint())

    if not minutes:
        stat.status = "empty"
        stat.elapsed = time.time() - started
        return stat

    # The store holds the Sunday-evening open, and USD-SOFR-1D reference points
    # are filtered to US government-bond business days inside
    # IRSwapsTB._filter_reference_points_for_curve - so a Sunday or a holiday
    # prices nothing, by design. Detected here rather than inferred from an empty
    # result, because "the calendar removed every point" and "pricing failed for
    # all 67 tenors" are the same zero rows and opposite facts, and 12 of the
    # first 51 days were Sundays reported as errors before this existed.
    priceable = tb._filter_reference_points_for_curve(minutes, cfg.curve)
    if not priceable:
        stat.status = "non_business"
        stat.elapsed = time.time() - started
        return stat

    try:
        # rateslib prints a line per solve and the value map warns on a running
        # session; across ~10^5 calls both serialise the pool on one stdout.
        with contextlib.redirect_stdout(io.StringIO()):
            import warnings

            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                priced = _price_outrights(tb, cfg, minutes)
                stat.priced_rows = int(priced.notna().to_numpy().sum()) if not priced.empty else 0

                rows_by_symbol, alias_rows, derived_rows = _alias_and_derived_rows(tb, cfg, priced)
                if rows_by_symbol:
                    tb._computed_ts_store.append_many_rows(
                        rows_by_symbol=rows_by_symbol, intraday=True
                    )
                stat.derived_rows = alias_rows + derived_rows
                stat.symbols = len(priced.columns) + len(rows_by_symbol)

                if cfg.swap_spreads:
                    stat.spread_rows = _price_swap_spreads(tb, cfg, minutes, spread_slice)
                    stat.symbols += len(cfg.spread_tenors)

        if stat.priced_rows == 0:
            stat.status = "error"
            stat.error = "no outright rows priced"
    except Exception as exc:  # noqa: BLE001 - one bad day must not end the run
        stat.status = "error"
        stat.error = f"{type(exc).__name__}: {exc}"
    finally:
        stat.elapsed = time.time() - started
        gc.collect()
    return stat


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------


def _open_store() -> Any:
    from Caching.curve_store import CurveStore

    return CurveStore.default()


def all_symbols(cfg: WarmConfig) -> List[str]:
    """Every computed-timeseries symbol this config will write. Parent-side only."""
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapValue import IRSwapValue
    from TB.IRSwapsTB import IRSwapsTB

    tb = IRSwapsTB(IRSwapsMDP(source=cfg.source), show_tqdm=False, use_duckdb=False,
                   ts_base_dir=cfg.ts_base_dir or "./data/ts")
    tenors: List[Tuple[str, Any]] = [(t, IRSwapValue.RATE) for t in cfg.outrights]
    if cfg.case_aliases:
        tenors += [(t.upper(), IRSwapValue.RATE) for t in cfg.outrights if t.upper() != t]
    if cfg.structures:
        tenors += [(t, IRSwapValue.RATE) for t in cfg.derived]
        if cfg.case_aliases:
            tenors += [(t.upper(), IRSwapValue.RATE) for t in cfg.derived if t.upper() != t]
    if cfg.swap_spreads:
        tenors += [(t, IRSwapValue.CITIVELO_SWAP_SPREAD) for t in cfg.spread_tenors]

    out = []
    for tenor, value in tenors:
        query = IRSwapQuery(curve=cfg.curve, tenor=tenor, value=value)
        out.append(tb._ts_symbol_for_query(cfg.curve, query))
    tb.close()
    return list(dict.fromkeys(out))


def prepare_spill(
    *, cfg: WarmConfig, ts_dir: Path, spill_dir: Path, logger: logging.Logger
) -> int:
    """Point this run's symbol directories at another volume, via NTFS junctions.

    The alternative when the system disk is nearly full is either to fill it or to
    not warm at all. A junction per symbol keeps ONE logical root - readers still
    open ``data/ts/asset=<sha1>/date=.../*.parquet`` and never learn that some of
    those directories live somewhere else - which is what makes this reversible
    and invisible, unlike moving the root and teaching every caller a new path.

    Only symbols that do not already exist are redirected, so nothing already
    written is touched or moved.

    The cost is honest and worth stating: those symbols are unreadable while the
    spill volume is detached. That degrades to a cache MISS rather than an error
    (``IRSwapsTB`` treats an unreadable symbol as uncached and reprices), and this
    cache is derived data that can be rebuilt, which is why it is the part that
    gets exiled rather than anything primary.
    """
    from Caching.timeseries_cache import _sanitize_symbol

    spill_dir.mkdir(parents=True, exist_ok=True)
    ts_dir.mkdir(parents=True, exist_ok=True)
    made = moved = already = 0
    symbols = all_symbols(cfg)
    started = time.time()
    logger.info("spill: redirecting %d symbol director(ies) to %s", len(symbols), spill_dir)
    for index, symbol in enumerate(symbols, start=1):
        if index % 25 == 0:
            logger.info(
                "  spill %d/%d (%d moved) %.1f min elapsed",
                index, len(symbols), moved, (time.time() - started) / 60.0,
            )
        name = f"asset={_sanitize_symbol(symbol)}"
        link = ts_dir / name
        target = spill_dir / name
        if _is_reparse_point(link):
            already += 1
            continue
        if link.is_dir():
            # Redirecting only NEW symbols would not help: a resumed run writes
            # new date partitions INSIDE symbol directories that already exist, so
            # the bytes would keep landing on the full volume. The existing
            # partitions move with it. This cache is derived data - the move is
            # recoverable by re-running even if it is interrupted.
            _robocopy_move(link, target)
            try:
                link.rmdir()
            except FileNotFoundError:
                # robocopy /MOVE removes the emptied source tree itself, so the
                # directory being GONE is the success case, not a failure.
                pass
            except OSError as exc:
                raise RuntimeError(
                    f"moved {link} to {target} but the source directory is not empty "
                    f"({exc}); not junctioning over data."
                ) from exc
            moved += 1
        target.mkdir(parents=True, exist_ok=True)
        # ``mklink`` is a cmd BUILTIN, not an executable, and it parses its own
        # command line - passing an argv list through ``cmd /c`` gets "The syntax
        # of the command is incorrect".
        result = subprocess.run(
            f'mklink /J "{link}" "{target}"',
            shell=True, capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"could not junction {link} -> {target}: "
                f"{(result.stderr or result.stdout).strip()}"
            )
        made += 1
    logger.warning(
        "spill: %d symbol director(ies) now live on %s (%d moved, %d already there). "
        "They are UNREADABLE while that volume is detached - which reads as a cache "
        "miss and reprices, it does not error.",
        made + already, spill_dir, moved, already,
    )
    return made


def unspill(*, ts_dir: Path, logger: logging.Logger) -> int:
    """Undo :func:`prepare_spill`: move every junctioned symbol back, then unlink.

    Symmetrical on purpose. A spill is a judgement about a machine at a moment -
    measured 2026-08-09, moving to a busy USB volume ran at 4 files/s where the
    same move to an idle one ran at 39 - and a judgement that cannot be reversed
    with one command is one nobody will make. Order matters: the data comes back
    FIRST and the junction is removed only once the copy is on the local volume.
    """
    moved = 0
    for link in sorted(ts_dir.glob("asset=*")):
        if not _is_reparse_point(link):
            continue
        # A junction's target comes back with the \\?\ extended-length prefix,
        # which robocopy rejects outright ("the filename, directory name, or
        # volume label syntax is incorrect").
        raw = os.readlink(link)
        target = Path(raw[4:] if raw.startswith("\\\\?\\") else raw)
        staging = ts_dir / f"{link.name}.unspill"
        if target.is_dir():
            _robocopy_move(target, staging)
        link.unlink(missing_ok=True)
        if staging.exists():
            staging.rename(link)
        else:
            link.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(OSError):
            target.rmdir()
        moved += 1
        if moved % 25 == 0:
            logger.info("  unspill %d ...", moved)
    logger.info("unspill: %d symbol director(ies) back on %s", moved, ts_dir)
    return moved


def _is_reparse_point(path: Path) -> bool:
    """True for a junction or symlink. ``Path.is_symlink`` misses NTFS junctions."""
    try:
        attrs = os.stat(path, follow_symlinks=False).st_file_attributes
    except (OSError, AttributeError):
        return False
    return bool(attrs & getattr(__import__("stat"), "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _robocopy_move(source: Path, target: Path) -> None:
    """Move a directory tree with robocopy. Raises unless it reports success.

    robocopy's exit codes are a bitmask, not a status: 0-7 are success (1 = files
    copied, 2 = extras, 4 = mismatches) and only >=8 is failure. Treating a
    non-zero return as an error here would abort on every successful move.
    """
    target.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["robocopy", str(source), str(target), "/MOVE", "/E", "/MT:16",
         "/NFL", "/NDL", "/NJH", "/NJS", "/NP", "/R:2", "/W:1"],
        capture_output=True, text=True,
    )
    if result.returncode >= 8:
        raise RuntimeError(
            f"robocopy could not move {source} -> {target} (exit {result.returncode}): "
            f"{(result.stdout or result.stderr).strip()[-400:]}"
        )


def _ledger_path(args: Any) -> Path:
    if getattr(args, "ledger", None):
        return Path(args.ledger)
    return _REPO_ROOT / "data" / "ts_warm" / "citivelo_intraday_ts_warm.jsonl"


def _config_from_args(args: Any) -> WarmConfig:
    return WarmConfig(
        omit_unused_fixings=not getattr(args, "no_omit_fixings", False),
        case_aliases=not getattr(args, "no_case_aliases", False),
        structures=not getattr(args, "no_structures", False),
        swap_spreads=not getattr(args, "no_swap_spreads", False),
        ts_base_dir=getattr(args, "ts_base_dir", None),
    )


def cmd_plan(args, logger: logging.Logger) -> int:
    cfg = _config_from_args(args)
    store = _open_store()
    start = _parse_date(args.start) if args.start else None
    end = _parse_date(args.end) if args.end else default_end()
    days = store_days(store, start=start, end=end)
    done = Ledger(_ledger_path(args)).completed(cfg_fingerprint=cfg.fingerprint())
    todo = [d for d in days if d not in done]

    spreads = load_spread_series(cfg.spread_tenors)
    spread_days = 0
    if not spreads.empty:
        covered = set(spreads.index.date)
        spread_days = sum(1 for d in days if d in covered)

    print(f"curve             {cfg.curve}   source={cfg.source}")
    print(f"config            {cfg.fingerprint()}  omit_fixings={cfg.omit_unused_fixings} "
          f"aliases={cfg.case_aliases} structures={cfg.structures} spreads={cfg.swap_spreads}")
    print(f"symbols/day       {cfg.expected_symbols()}  "
          f"(outrights {len(cfg.outrights)}, derived {len(cfg.derived) if cfg.structures else 0}, "
          f"spreads {len(cfg.spread_tenors) if cfg.swap_spreads else 0})")
    print(f"store days        {len(days)}  {days[0] if days else '-'} .. {days[-1] if days else '-'}")
    print(f"already warmed    {len(done)}")
    print(f"to warm           {len(todo)}")
    print(f"MI01 spread tags  {len(spreads.columns)}/{len(cfg.spread_tenors)} cached, "
          f"covering {spread_days}/{len(days)} store day(s)")
    if not spreads.empty:
        print(f"                  {spreads.index.min()} .. {spreads.index.max()}")
    if todo:
        # Sample across the range, not off the front: the 2022 head is 10-minute
        # data with as few as 18 rows a day, and estimating a four-year run off it
        # understates the work by an order of magnitude.
        step = max(1, len(todo) // 6)
        sample = todo[::step][:6]
        total_minutes = 0
        for day in sample:
            total_minutes += len(session_minutes(store, day))
        per_day = total_minutes / max(len(sample), 1)
        pricings = per_day * (len(cfg.outrights) + (len(cfg.spread_tenors) if cfg.swap_spreads else 0))
        seconds = pricings / 500.0
        workers = max(1, int(getattr(args, "workers", 1) or 1))
        print(f"est minutes/day   {per_day:.0f}")
        print(f"est {seconds / 60:.1f} min/day single-process -> "
              f"{len(todo) * seconds / 3600 / workers:.1f} h on {workers} worker(s)")
    logger.debug("plan complete")
    return 0


def _spread_fetch_ledger_path(args: Any) -> Path:
    return _ledger_path(args).with_name("citivelo_intraday_ts_warm.spreads.jsonl")


def _completed_windows(path: Path) -> set[str]:
    done: set[str] = set()
    if not path.is_file():
        return done
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:  # noqa: BLE001 - a torn last line must not be fatal
                continue
            if row.get("status") == "ok" and row.get("window"):
                done.add(str(row["window"]))
    return done


def cmd_fetch_spreads(args, logger: logging.Logger) -> int:
    """Pull the MI01 SWAP_SPREAD axis out of Excel into the tag cache.

    Resume is a **window ledger**, not ``CitiVeloTagCache.missing_spans``. That
    method knows only the cached series' first and last stamp, so once a run has
    reached day 300 it reports every earlier window as covered - including one
    that failed and left a hole in the middle. A hole in a swap-spread series
    does not raise; the as-of search simply serves the last print before it, and
    a whole session silently inherits the previous day's number.

    Writes are batched. ``CitiVeloTagCache.write`` merges by re-reading and
    re-writing the tag's ENTIRE parquet, so flushing every window would cost
    O(windows x history) and grow as the cache fills. Fetched windows accumulate
    in memory and land every ``--flush-every`` windows; the ledger is only
    written after a successful flush, so a crash between fetch and flush re-fetches
    those windows rather than recording work that never reached disk.
    """
    import datetime as _dt

    from MDP.CitiVelocityExcel.cache import CitiVeloTagCache
    from MDP.CitiVelocityExcel.com_client import CitiVelocityExcelClient
    from MDP.CitiVelocityExcel.supervisor import restart_excel
    from MDP.CitiVelocityExcel.windowed import fetch_windowed

    cfg = _config_from_args(args)
    tag_by_tenor = swap_spread_tags(cfg.spread_tenors)
    tags = list(tag_by_tenor.values())
    cache = CitiVeloTagCache()

    start = _parse_date(args.start) if args.start else None
    end = _parse_date(args.end) if args.end else default_end()
    if start is None:
        store = _open_store()
        days = store_days(store, start=None, end=end)
        if not days:
            logger.error("no minute-curve days in the store; nothing to align the fetch to")
            return 2
        # Reach back one lookback further than the first day so the earliest
        # session's opening minutes have a print at or before them.
        start = days[0] - _dt.timedelta(days=_spread_lookback().days + 1)

    window = _dt.timedelta(days=int(args.window_days))
    ledger_path = _spread_fetch_ledger_path(args)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    done = _completed_windows(ledger_path)

    chunks: List[Tuple[datetime.date, datetime.date]] = []
    cursor = start
    while cursor < end:
        chunk_end = min(cursor + window, end)
        chunks.append((cursor, chunk_end))
        cursor = chunk_end
    todo = [c for c in chunks if f"{c[0]}/{c[1]}" not in done]

    logger.info(
        "%d window(s) of %d day(s) over %s .. %s; %d already fetched, %d to go",
        len(chunks), window.days, start, end, len(chunks) - len(todo), len(todo),
    )
    if not todo:
        _report_spread_coverage(cache, tag_by_tenor, logger)
        return 0

    try:
        client = CitiVelocityExcelClient.connect(workbook_tag=args.workbook_tag)
    except Exception as exc:  # noqa: BLE001 - not running, not signed in, or wedged
        if not args.auto_restart:
            logger.error(
                "could not connect to Excel (%s: %s). Sign in to the Velocity add-in, or "
                "pass --auto-restart to have this restart Excel and wait for it.",
                type(exc).__name__, exc,
            )
            return 2
        logger.warning("connect failed (%s: %s); restarting Excel.", type(exc).__name__, exc)
        client = restart_excel(
            workbook_tag=args.workbook_tag,
            ready_timeout=float(args.restart_timeout_minutes) * 60.0,
            logger=logger,
        )
    logger.info("connected to Excel (%s sheets, %.0f MB)",
                client.sheet_count(), client.excel_memory_mb())

    from tqdm import tqdm

    pending: Dict[str, List[pd.Series]] = {}
    staged: List[str] = []
    totals = {"windows": 0, "rows": 0, "flushed": 0, "restarts": 0}
    stopped_early = False

    def _flush() -> None:
        if not staged:
            return
        for tag, parts in pending.items():
            if not parts:
                continue
            merged = pd.concat(parts)
            merged = merged[~merged.index.duplicated(keep="last")].sort_index()
            cache.write(tag, "MI01", merged)
            totals["rows"] += int(merged.size)
        pending.clear()
        with ledger_path.open("a", encoding="utf-8") as handle:
            for key in staged:
                handle.write(json.dumps({"window": key, "status": "ok"}) + "\n")
        totals["flushed"] += len(staged)
        staged.clear()

    bar = tqdm(total=len(todo), desc="FETCH MI01 SWAP_SPREAD", disable=not args.tqdm)
    try:
        for chunk_start, chunk_end in todo:
            used = client.excel_memory_mb()
            if used >= float(args.memory_abort_mb):
                # Recycling the workbook recovers ~200 MB against the ~340 MB the
                # windows before it added, because the memory is in the add-in's
                # own cache rather than in the workbook. Past the abort ceiling
                # the only thing that actually clears it is a restart.
                if args.auto_restart:
                    logger.warning(
                        "Excel is at %.0f MB (abort ceiling %.0f MB). Flushing, then "
                        "restarting Excel and waiting for the add-in to sign back in.",
                        used, float(args.memory_abort_mb),
                    )
                    _flush()
                    with contextlib.suppress(Exception):
                        client.close()
                    try:
                        client = restart_excel(
                            workbook_tag=args.workbook_tag,
                            ready_timeout=float(args.restart_timeout_minutes) * 60.0,
                            logger=logger,
                        )
                    except Exception as exc:  # noqa: BLE001 - stop cleanly, resume later
                        logger.error("auto-restart failed: %s: %s", type(exc).__name__, exc)
                        stopped_early = True
                        break
                    totals["restarts"] += 1
                    logger.info("Excel restarted (%.0f MB); resuming at %s",
                                client.excel_memory_mb(), chunk_start)
                else:
                    logger.warning(
                        "Excel is at %.0f MB, at or above the %.0f MB abort ceiling. Flushing "
                        "what is in hand - restart Excel and re-run to resume, or pass "
                        "--auto-restart to have this do it.",
                        used, float(args.memory_abort_mb),
                    )
                    stopped_early = True
                    break
            elif used >= float(args.memory_ceiling_mb):
                logger.info("  recycling the scratch workbook (Excel %.0f MB)", used)
                if not client.recycle_workbook():
                    logger.warning("  recycle refused at %.0f MB; stopping cleanly.", used)
                    stopped_early = True
                    break

            try:
                series, windows = fetch_windowed(
                    client, tags, "MI01",
                    _dt.datetime.combine(chunk_start, _dt.time()),
                    _dt.datetime.combine(chunk_end, _dt.time()),
                    window=window, strict_spacing=True,
                )
            except Exception as exc:  # noqa: BLE001 - one window must not end the run
                logger.error("  %s..%s FAILED: %s: %s",
                             chunk_start, chunk_end, type(exc).__name__, exc)
                bar.update(1)
                continue

            failed = [w for w in windows if not w.ok and w.error]
            for w in failed:
                logger.warning("  window %s: %s", w.sheet or w.start, w.error)
            if failed:
                # A partially-served window must not be recorded as done, or the
                # hole it left becomes permanent and invisible.
                bar.update(1)
                continue

            rows = 0
            for tag, s in (series or {}).items():
                if s is None or len(s) == 0:
                    continue
                pending.setdefault(tag, []).append(s)
                rows += int(len(s))
            totals["windows"] += 1
            # A weekend window legitimately serves nothing; recording it is what
            # stops the next run re-asking Excel for it forever.
            staged.append(f"{chunk_start}/{chunk_end}")
            bar.update(1)
            bar.set_postfix_str(f"{totals['rows'] + rows:,} rows | Excel {used:.0f}MB",
                                refresh=False)
            if len(staged) >= int(args.flush_every):
                _flush()
    finally:
        try:
            _flush()
        finally:
            bar.close()
            with contextlib.suppress(Exception):
                client.close()

    logger.info(
        "fetch-spreads %s: %d window(s) fetched, %d recorded, %d row(s) merged",
        "STOPPED EARLY" if stopped_early else "complete",
        totals["windows"], totals["flushed"], totals["rows"],
    )
    _report_spread_coverage(cache, tag_by_tenor, logger)
    return 3 if stopped_early else 0


def _report_spread_coverage(cache: Any, tag_by_tenor: Dict[str, str], logger: logging.Logger) -> None:
    for tenor, tag in tag_by_tenor.items():
        cov = cache.coverage(tag, "MI01")
        if cov is None:
            logger.info("  %-4s uncached", tenor)
        else:
            logger.info("  %-4s %9d rows  %s .. %s", tenor, cov.n_rows, cov.first, cov.last)


def cmd_warm(args, logger: logging.Logger) -> int:
    cfg = _config_from_args(args)
    store = _open_store()
    start = _parse_date(args.start) if args.start else None
    end = _parse_date(args.end) if args.end else default_end()

    hard_end = default_end()
    if end > hard_end:
        logger.warning(
            "end %s is inside the %d-day staleness window; rows dated after %s are evicted "
            "from the read cache and repriced on every read, so warming them is work that "
            "throws itself away. Capping at %s.",
            end, STALE_LAG_DAYS, hard_end, hard_end,
        )
        end = hard_end

    days = store_days(store, start=start, end=end)
    ledger = Ledger(_ledger_path(args))
    done = ledger.completed(cfg_fingerprint=cfg.fingerprint())
    todo = [d for d in days if args.force or d not in done]
    if args.limit:
        todo = todo[: int(args.limit)]
    if not todo:
        logger.info("nothing to warm: %d store day(s), all already at config %s",
                    len(days), cfg.fingerprint())
        return 0

    spreads = pd.DataFrame()
    if cfg.swap_spreads:
        spreads = load_spread_series(cfg.spread_tenors)
        if spreads.empty:
            logger.warning(
                "no MI01 SWAP_SPREAD tags are cached, so IRS_CITIVELO_SWAP_SPREAD will be "
                "SKIPPED for every day. Run `fetch-spreads` first, or pass --no-swap-spreads "
                "to make the omission deliberate."
            )
        else:
            logger.info(
                "MI01 swap spreads: %d tag(s), %s .. %s",
                len(spreads.columns), spreads.index.min(), spreads.index.max(),
            )
    lookback = _spread_lookback()

    logger.info(
        "warming %d day(s) %s .. %s across %d worker(s); %d symbol(s)/day, config %s",
        len(todo), todo[0], todo[-1], args.workers, cfg.expected_symbols(), cfg.fingerprint(),
    )

    from tqdm import tqdm

    cfg_dict = {k: (list(v) if isinstance(v, tuple) else v) for k, v in asdict(cfg).items()}
    progress = Progress(total_days=len(todo))

    def _task(day: datetime.date):
        minutes = session_minutes(store, day)
        day_slice = (
            slice_spreads_for_day(spreads, day, lookback=lookback)
            if cfg.swap_spreads and not spreads.empty
            else pd.DataFrame()
        )
        return (day, minutes, day_slice)

    ts_dir = cfg.ts_base_dir or str(_REPO_ROOT / "data" / "ts")
    floor = float(args.min_free_gb)
    if args.spill_dir:
        prepare_spill(
            cfg=cfg, ts_dir=Path(ts_dir), spill_dir=Path(args.spill_dir), logger=logger
        )
        # The floor now has to watch the volume the bytes actually land on.
        ts_dir = str(args.spill_dir)
    logger.info("writing to %s (%.1f GB free; floor %.1f GB)", ts_dir, free_gb(ts_dir), floor)

    stopped_for_disk = False

    def _disk_ok(*, wait: bool = True) -> bool:
        """Block until there is room, then True. False once waiting has given up.

        A cache is not worth a full disk: this run writes ~7 GB of Parquet across
        ~360k files, and the on-disk cost exceeds the byte count because every
        (symbol, day) partition is its own directory holding one small file.

        It WAITS rather than stopping, because on this machine free space is not
        monotonic - measured 2026-08-08/09 it moved between 6 GB and 44 GB inside a
        single minute while other backfills churned a 140 GB pile of ZODB caches.
        Stopping on the first dip would end an eight-hour run over a condition
        that cleared thirty seconds later; waiting rides it out and still refuses
        to be the job that fills the disk. Only a floor that holds for
        ``--disk-wait-minutes`` ends the run, and the ledger makes that free.

        ``wait=False`` answers immediately. The caller passes it while work is
        still in flight: blocking there would leave ten workers finished and
        unharvested for up to three hours, so a full disk would cost the results
        of the day it was already holding.
        """
        nonlocal stopped_for_disk
        if stopped_for_disk:
            return False
        deadline = time.time() + float(args.disk_wait_minutes) * 60.0
        warned = False
        while True:
            remaining = free_gb(ts_dir)
            if remaining >= floor:
                if warned:
                    logger.info("resuming: %s back to %.1f GB free", ts_dir, remaining)
                return True
            if not wait:
                return False
            if time.time() >= deadline:
                logger.error(
                    "STOPPING: %s has %.1f GB free, at or below the %.1f GB floor, and has "
                    "stayed there for %.0f minute(s). %d day(s) are warmed; the ledger "
                    "resumes the rest once there is room.",
                    ts_dir, remaining, floor, float(args.disk_wait_minutes), progress.days_done,
                )
                stopped_for_disk = True
                return False
            if not warned:
                logger.warning(
                    "PAUSING: %s has %.1f GB free, below the %.1f GB floor. Waiting up to "
                    "%.0f minute(s) for room; %d day(s) warmed so far.",
                    ts_dir, remaining, floor, float(args.disk_wait_minutes), progress.days_done,
                )
                warned = True
            time.sleep(30.0)

    bar = tqdm(total=len(todo), desc="WARM citivelo intraday IRS", disable=not args.tqdm)
    try:
        if int(args.workers) <= 1:
            _init_worker(cfg_dict)
            for day in todo:
                if not _disk_ok():
                    break
                stat = warm_one_day(_task(day))
                _record(stat, ledger, progress, bar, logger)
        else:
            with ProcessPoolExecutor(
                max_workers=int(args.workers), initializer=_init_worker, initargs=(cfg_dict,)
            ) as pool:
                pending = {}
                queue = list(todo)
                # Bound in-flight tasks: each carries a day's minute list and
                # spread slice, and submitting 950 of them up front would hold
                # every slice in memory at once for no gain.
                inflight = max(int(args.workers) * 2, 4)
                while queue or pending:
                    while queue and len(pending) < inflight:
                        # Only block on the disk when NOTHING is in flight; with
                        # workers running, a full volume means "stop topping up
                        # and go harvest", not "sleep on ten finished days".
                        if not _disk_ok(wait=not pending):
                            break
                        day = queue.pop(0)
                        pending[pool.submit(warm_one_day, _task(day))] = day
                    if not pending:
                        break
                    for future in as_completed(list(pending)):
                        pending.pop(future, None)
                        stat = future.result()
                        _record(stat, ledger, progress, bar, logger)
                        break
    finally:
        bar.close()

    logger.info("warm %s: %s  (%.1f GB free)",
                "STOPPED EARLY" if stopped_for_disk else "complete",
                progress.heartbeat(), free_gb(ts_dir))
    if stopped_for_disk:
        return 3
    return 1 if progress.errors else 0


def _record(stat: DayStat, ledger: Ledger, progress: Progress, bar: Any, logger: logging.Logger) -> None:
    ledger.record(stat)
    progress.record(stat)
    bar.update(1)
    bar.set_postfix_str(
        f"{progress.rows:,} rows | {progress.errors} err", refresh=False
    )
    if stat.status not in TERMINAL_STATUSES:
        logger.warning("%s %s: %s", stat.date, stat.status, stat.error or "")
    if progress.days_done % 10 == 0 or progress.days_done == progress.total_days:
        logger.info(progress.heartbeat())


def cmd_status(args, logger: logging.Logger) -> int:
    cfg = _config_from_args(args)
    store = _open_store()
    days = store_days(store, start=None, end=None)
    done = Ledger(_ledger_path(args)).completed(cfg_fingerprint=cfg.fingerprint())
    rows = sum(s.priced_rows + s.derived_rows + s.spread_rows for s in done.values())
    minutes = sum(s.minutes for s in done.values())
    elapsed = sum(s.elapsed for s in done.values())
    non_business = sum(1 for s in done.values() if s.status != "ok")
    print(f"config       {cfg.fingerprint()}")
    print(f"store days   {len(days)}")
    print(f"warmed days  {len(done)}  ({100.0 * len(done) / max(len(days), 1):.1f}%)"
          f"  of which {non_business} priced nothing (Sunday/holiday)")
    print(f"minutes      {minutes:,}")
    print(f"rows         {rows:,}")
    print(f"cpu-time     {elapsed / 3600:.2f} h  ({elapsed / max(len(done), 1):.1f} s/day)")
    if done:
        keys = sorted(done)
        print(f"span         {keys[0]} .. {keys[-1]}")
    logger.debug("status complete")
    return 0


def cmd_verify(args, logger: logging.Logger) -> int:
    """Prove the three claims this warm rests on, on one real day.

    1. The symbol a warm query writes IS the symbol a user query reads.
    2. A derived curve/fly equals the directly-priced one.
    3. An uppercase alias equals the lowercase number it was copied from.

    Run before a fleet, and again after: a green ``verify`` is the only evidence
    that a fast run wrote numbers anybody can use.
    """
    os.environ["ARBS_CITIVELO_QUOTES_OFFLINE"] = "1"

    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapValue import IRSwapValue
    from Query.IRSwaps.backends.rateslib import RLIRSwapCurve as rl_mod
    from Query.Unified.UnifiedQuery import UnifiedQuery
    from Query.Unified.registry import UnifiedValue
    from TB.IRSwapsTB import IRSwapsTB, _build_row_for_query
    from TB.TimeseriesBuilder import _normalize_query_like

    cfg = _config_from_args(args)
    store = _open_store()
    day = _parse_date(args.date) if args.date else store_days(store, start=None, end=default_end())[-1]
    minutes = session_minutes(store, day)
    if not minutes:
        logger.error("no minute curves for %s", day)
        return 2
    sample = minutes[:: max(1, len(minutes) // int(args.points))][: int(args.points)]
    logger.info("verifying %s on %d of %d minute(s)", day, len(sample), len(minutes))

    mdp = IRSwapsMDP(source=cfg.source)
    tb = IRSwapsTB(mdp, show_tqdm=False, use_ts_cache=True, use_duckdb=False,
                   ts_base_dir=cfg.ts_base_dir or "./data/ts")
    failures: List[str] = []

    # --- 1. symbol identity ------------------------------------------------
    probes = ["10y", "5y/10y", "5y/10y/30y", "5yx5y", "5yx5y/10yx10y"]
    for tenor in probes:
        warm_q = IRSwapQuery(curve=cfg.curve, tenor=tenor, value=IRSwapValue.RATE)
        user_q = _normalize_query_like(
            UnifiedQuery(curve=cfg.curve, tenor=tenor, value=UnifiedValue.IRS_RATE)
        )[0]
        a = tb._ts_symbol_for_query(cfg.curve, warm_q)
        b = tb._ts_symbol_for_query(cfg.curve, user_q)
        if a != b:
            failures.append(f"symbol mismatch for {tenor!r}: warm {a} vs user {b}")
    ss_warm = IRSwapQuery(curve=cfg.curve, tenor="10Y", value=IRSwapValue.CITIVELO_SWAP_SPREAD)
    ss_user = _normalize_query_like(
        UnifiedQuery(curve=cfg.curve, tenor="10Y", value=UnifiedValue.IRS_CITIVELO_SWAP_SPREAD)
    )[0]
    if tb._ts_symbol_for_query(cfg.curve, ss_warm) != tb._ts_symbol_for_query(cfg.curve, ss_user):
        failures.append("symbol mismatch for the swap-spread query")
    logger.info("  [1] symbol identity: %s", "FAIL" if failures else "ok")

    # --- 2/3. derived and alias values vs direct pricing -------------------
    rl_mod.set_omit_unused_fixings(bool(cfg.omit_unused_fixings))
    curves = mdp.bulk_get_data(
        {"curve_name": cfg.curve, "timestamps": list(sample), "n_jobs": 1}
    )

    def direct(tenor: str, stamp: datetime.datetime) -> float:
        query = IRSwapQuery(curve=cfg.curve, tenor=tenor, value=IRSwapValue.RATE)
        return _build_row_for_query(curves[stamp], query, stamp, "Date")[2]

    checked = 0
    worst_derived = 0.0
    worst_alias = 0.0
    structures = list(args.structures.split(",")) if args.structures else [
        "5y/10y", "2y/10y", "10y/30y", "5y/10y/30y", "2y/5y/10y",
        "5yx5y/10yx10y", "1yx1y/2yx1y/3yx1y",
    ]
    for stamp in sample:
        if stamp not in curves:
            continue
        leg_values: Dict[str, float] = {}
        for tenor in structures:
            legs = decompose(tenor)
            if legs is None:
                failures.append(f"{tenor!r} does not decompose into outright legs")
                continue
            for _weight, leg in legs:
                if leg not in leg_values:
                    leg_values[leg] = direct(leg, stamp)
            derived = derive_value(legs, leg_values)
            actual = direct(tenor, stamp)
            if derived is None:
                failures.append(f"{tenor!r} produced no derived value at {stamp}")
                continue
            worst_derived = max(worst_derived, abs(derived - actual))
        for tenor in ("10y", "5yx5y"):
            lower = leg_values.get(tenor)
            if lower is None:
                lower = direct(tenor, stamp)
            worst_alias = max(worst_alias, abs(direct(tenor.upper(), stamp) - lower))
        checked += 1

    tol = float(args.tolerance)
    if worst_derived > tol:
        failures.append(f"derived vs direct max |delta| {worst_derived:.3e} bp exceeds {tol:g}")
    if worst_alias > tol:
        failures.append(f"UPPERCASE vs lowercase max |delta| {worst_alias:.3e} exceeds {tol:g}")
    logger.info("  [2] derived vs direct: max |delta| %.3e bp over %d point(s) x %d structure(s)",
                worst_derived, checked, len(structures))
    logger.info("  [3] case alias:        max |delta| %.3e", worst_alias)

    # --- 4. does a warmed day actually read back from cache? ---------------
    if args.date and not args.skip_readback:
        probe = [
            IRSwapQuery(curve=cfg.curve, tenor=t, value=IRSwapValue.RATE)
            for t in ("10y", "5y/10y/30y", "5yx5y")
        ]
        t0 = time.perf_counter()
        frame = tb.get_timeseries(
            start=minutes[0], end=minutes[-1], queries=probe,
            timestamps=list(minutes), n_jobs=1, ignore_cache=False,
        )
        logger.info(
            "  [4] cached read-back:  %.2fs for %d point(s) x %d query -> shape %s",
            time.perf_counter() - t0, len(minutes), len(probe), frame.shape,
        )

    rl_mod.set_omit_unused_fixings(None)
    if failures:
        for line in failures:
            logger.error("VERIFY FAILED: %s", line)
        return 1
    logger.info("verify: all checks passed")
    return 0


# ---------------------------------------------------------------------------
# cli
# ---------------------------------------------------------------------------


def _add_config_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--no-omit-fixings", action="store_true",
                        help="price with the full RFR fixings series (8.7x slower, 1.8e-15 bp)")
    parser.add_argument("--no-case-aliases", action="store_true",
                        help="skip the UPPERCASE outright copies")
    parser.add_argument("--no-structures", action="store_true",
                        help="outrights only; curves and flies stay derivable at read time")
    parser.add_argument("--no-swap-spreads", action="store_true",
                        help="skip IRS_CITIVELO_SWAP_SPREAD")
    parser.add_argument("--ts-base-dir", default=None)
    parser.add_argument("--ledger", default=None)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__ or "")
    parser.add_argument("--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan", help="what would run, and roughly how long")
    plan.add_argument("--start", default=None)
    plan.add_argument("--end", default=None)
    plan.add_argument("--workers", type=int, default=1)
    _add_config_args(plan)
    plan.set_defaults(func=cmd_plan)

    fetch = sub.add_parser("fetch-spreads", help="pull MI01 SWAP_SPREAD out of Excel")
    fetch.add_argument("--start", default=None)
    fetch.add_argument("--end", default=None)
    fetch.add_argument("--window-days", type=int, default=5,
                       help="CVTSHIST downsamples an MI01 request spanning >6 days; "
                            "5 is windowed.DEFAULT_WINDOW['MI01']")
    fetch.add_argument("--flush-every", type=int, default=25,
                       help="merge staged windows into the tag cache every N windows")
    fetch.add_argument("--workbook-tag", default="TSWARM")
    # Raised from 3000/3800 now that --auto-restart can clear the add-in's cache
    # instead of stopping the run. Excel wedged at 5,249 MB on 2026-08-07, so the
    # abort ceiling stays a clear margin under that.
    fetch.add_argument("--memory-ceiling-mb", type=float, default=4000.0,
                       help="recycle the scratch workbook above this")
    fetch.add_argument("--memory-abort-mb", type=float, default=4800.0,
                       help="restart Excel (with --auto-restart) or stop, above this. "
                            "Excel wedged at 5,249 MB on 2026-08-07.")
    fetch.add_argument("--auto-restart", action="store_true",
                       help="at the abort ceiling, save the user's unsaved workbooks, "
                            "restart Excel and wait for the add-in to sign back in from "
                            "saved credentials, instead of stopping")
    fetch.add_argument("--restart-timeout-minutes", type=float, default=25.0,
                       help="the Velocity login takes ~13 minutes and logs nothing")
    fetch.add_argument("--no-tqdm", dest="tqdm", action="store_false", default=True)
    _add_config_args(fetch)
    fetch.set_defaults(func=cmd_fetch_spreads)

    warm = sub.add_parser("warm", help="price and cache the structure universe")
    warm.add_argument("--start", default=None)
    warm.add_argument("--end", default=None)
    warm.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 2))
    warm.add_argument("--limit", type=int, default=None)
    warm.add_argument("--force", action="store_true", help="re-warm days the ledger calls done")
    warm.add_argument("--min-free-gb", type=float, default=12.0,
                      help="pause when the timeseries volume drops to this. A cache is not "
                           "worth a full disk, and the ledger makes stopping free.")
    warm.add_argument("--spill-dir", default=None,
                      help="put THIS RUN's symbol directories on another volume via NTFS "
                           "junctions, keeping one logical root so readers need no change. "
                           "For a system disk with no room. Those symbols read as a cache "
                           "miss while the volume is detached.")
    warm.add_argument("--disk-wait-minutes", type=float, default=90.0,
                      help="how long to wait at the floor before giving up. Free space here "
                           "moves tens of GB in a minute under other jobs, so a run that "
                           "stopped on the first dip would end over a cleared condition.")
    warm.add_argument("--no-tqdm", dest="tqdm", action="store_false", default=True)
    _add_config_args(warm)
    warm.set_defaults(func=cmd_warm)

    verify = sub.add_parser("verify", help="symbol identity, derived-vs-direct, alias equality")
    verify.add_argument("--date", default=None)
    verify.add_argument("--points", type=int, default=12)
    verify.add_argument("--structures", default=None)
    verify.add_argument("--tolerance", type=float, default=1e-9)
    verify.add_argument("--skip-readback", action="store_true")
    _add_config_args(verify)
    verify.set_defaults(func=cmd_verify)

    status = sub.add_parser("status", help="ledger summary")
    _add_config_args(status)
    status.set_defaults(func=cmd_status)

    unspill_cmd = sub.add_parser(
        "unspill", help="move every junctioned symbol directory back to the local volume"
    )
    _add_config_args(unspill_cmd)
    unspill_cmd.set_defaults(func=cmd_unspill)
    return parser


def cmd_unspill(args, logger: logging.Logger) -> int:
    cfg = _config_from_args(args)
    ts_dir = Path(cfg.ts_base_dir or (_REPO_ROOT / "data" / "ts"))
    unspill(ts_dir=ts_dir, logger=logger)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    return args.func(args, LOGGER)


if __name__ == "__main__":
    sys.exit(main())
