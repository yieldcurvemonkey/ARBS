r"""Time the INTRADAY Citi-Velocity FRB read path, hermetically.

What this measures and why it can be trusted
--------------------------------------------
``TimeseriesBuilder.get_timeseries(..., freq="1min")`` over a 60-minute window on
``FixedRateBondsMDP(source="USTS_CITIVELO-RL")`` was profiled at **593 s for 60
points, 500 s of it in ``time.sleep``** - the client polling Excel for cells to
settle - across **61** ``_get_multi_pricers`` calls. That sleep is a property of a
live add-in and cannot be reproduced offline, so this script measures the two
things that CAN be measured without Excel and reports the third as an explicit
projection:

1. **Vendor round trips.** Every ``fetch_timeseries`` the code issues is counted
   at the client seam. This is the structural number the fix moves, and it is the
   one that multiplies by the add-in's settle latency.
2. **Wall time with a zero-latency vendor.** What the code itself costs once the
   vendor is free. Compares like with like before and after.
3. **Projection.** ``round_trips x SETTLE_SECONDS``, where ``SETTLE_SECONDS`` is
   the 500 s of measured sleep divided by the 61 calls in the original profile.
   Labelled a projection everywhere it appears, because it is one.

Hermetic by construction
------------------------
``CitiVelocityExcelClient.connect`` is replaced with a recorder that serves from
the **real warm MI01 tag cache** (349 USTs, PRICE+YIELD, 2026-08-05..07) and
counts calls. Nothing here can reach Excel: the class method that opens COM is
gone for the life of the process, and the recorder raises if asked for a
frequency the cache cannot serve rather than falling through to anything live.

Two costs are neutralised so they do not drown the signal, and both are
symmetric across before and after:

``update_reference_data``
    ``FixedRateBondsTB`` marks anything inside five days stale and passes
    ``force_refresh=True``, which makes this re-download fiscaldata **per
    timestamp** - 60 network round trips that have nothing to do with Velocity.
    Memoised here on (source), and reported as an open item rather than fixed.
``DiskCacheMixin.CACHE_ROOT``
    Pointed at a fresh temp directory per run, so a second run is not answered
    out of the first run's pricer cache. Without this the "after" number is a
    cache-hit measurement, not a read-path measurement.

What it measured
----------------
``CT10``, ``FRB_YTM``, 2026-08-07 10:00..10:59 at one minute, 60 points:

=====================================  ==========  =========  =============
                                       round trips worksheets wall (vendor 0)
=====================================  ==========  =========  =============
before the fix (unmodified HEAD)                61         60        3.34 s
``--no-prefetch`` control                       60         60        3.42 s
after the fix                                    1          0        3.30 s
=====================================  ==========  =========  =============

The 61st call before the fix is the ``DAILY`` prefetch, which an all-intraday
range had no use for. Projected at the profile's 8.20 s of settle per round trip:
**503 s -> 11.4 s**. All 60 served values are IDENTICAL between the control and
the fixed path (0 differ), once the endpoint disagreement between the two
transports is closed - see ``CitiVeloBondFetcher._fetch_frame``.

Usage
-----
::

    python scripts/bench_citivelo_intraday_frb.py
    python scripts/bench_citivelo_intraday_frb.py --points 60 --no-prefetch
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import pathlib
import sys
import tempfile
import time
from typing import Any, Dict, List, Optional, Sequence

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pandas as pd  # noqa: E402

#: 500 s of measured ``time.sleep`` over the 61 fetches in the original profile.
#: Used ONLY to project a wall time from a round-trip count. Never measured here.
SETTLE_SECONDS = 500.0 / 61.0


# ------------------------------------------------------------------ #
#                       the hermetic vendor seam                     #
# ------------------------------------------------------------------ #


class RecordingCacheClient:
    """A ``CitiVelocityExcelClient`` stand-in that serves the warm tag cache.

    Counts every ``fetch_timeseries`` and records its ``(freq, start, end)``, so
    a caller can assert both how many round trips happened and how wide each one
    was. Serves real numbers - read straight off the committed parquets - so the
    timeseries this benchmark produces is the one the real path would produce,
    not a constant that happens to be fast.
    """

    def __init__(self, *, latency: float = 0.0, dense: bool = True):
        from MDP.CitiVelocityExcel.cache import CitiVeloTagCache

        self._cache = CitiVeloTagCache()
        self.latency = float(latency)
        #: Serve an unbroken one-minute grid rather than the cache's own rows.
        #:
        #: MEASURED: the warm MI01 cache holds 2,766 rows over three days for a
        #: UST, with a MEDIAN gap of TWO minutes (1,525 two-minute gaps against
        #: 1,227 one-minute ones) - Citi prints a bond when it moves, not once a
        #: minute. Served as-is, ``windowed.fetch_windowed``'s spacing guard reads
        #: that as a downsampled block and raises ``DownsampledWindowError`` for
        #: every window, so the ONLINE baseline serves nothing and there is no
        #: like-for-like wall time to compare against. Forward-filling onto the
        #: minute grid models the healthy add-in the original 593 s profile ran
        #: against; ``--sparse`` serves the cache verbatim and exposes the guard.
        #:
        #: As-of resolution is unaffected either way: the newest print at or
        #: before a minute is the same number on both grids.
        self.dense = bool(dense)
        self.calls: List[Dict[str, Any]] = []
        self.sheets_pushed = 0
        self.closed = 0

    # -- the counted seam ------------------------------------------------

    def fetch_timeseries(
        self,
        tags: Sequence[str],
        freq: str = "DAILY",
        *,
        period: Optional[str] = None,
        start: Any = None,
        end: Any = None,
        price_point: str = "CLOSE",
        strict: bool = False,
        timeout: Optional[float] = None,
    ) -> Dict[str, pd.Series]:
        span = None
        if start is not None and end is not None:
            span = pd.Timestamp(end) - pd.Timestamp(start)
        self.calls.append(
            {"freq": str(freq), "n_tags": len(list(tags)), "start": start, "end": end, "span": span}
        )
        if self.latency:
            time.sleep(self.latency)

        out: Dict[str, pd.Series] = {}
        for tag in dict.fromkeys(str(t).strip() for t in tags):
            s = self._cache.read(tag, str(freq), price_point)
            if s is None or s.empty:
                continue
            if self.dense and str(freq).upper() == "MI01":
                grid = pd.date_range(s.index.min().floor("min"), s.index.max().ceil("min"), freq="1min")
                s = s.reindex(s.index.union(grid)).ffill().reindex(grid)
                s.index.name = "Date"
            if start is not None:
                s = s[s.index >= pd.Timestamp(start)]
            if end is not None:
                s = s[s.index <= pd.Timestamp(end)]
            s = s.dropna()
            if not s.empty:
                out[tag] = s
        return out

    # -- the rest of the client surface ----------------------------------

    def last_failures(self) -> Dict[str, str]:
        return {}

    def push_window_sheet(self, name: str) -> str:
        self.sheets_pushed += 1
        return name

    def drop_window_sheet(self) -> bool:
        return True

    def close(self) -> None:
        self.closed += 1

    def excel_memory_mb(self) -> float:
        return 0.0

    # -- reporting -------------------------------------------------------

    @property
    def round_trips(self) -> int:
        return len(self.calls)

    def widest_span(self) -> Optional[datetime.timedelta]:
        spans = [c["span"] for c in self.calls if c["span"] is not None]
        return max(spans).to_pytimedelta() if spans else None


def install_hermetic_vendor(latency: float = 0.0, dense: bool = True) -> RecordingCacheClient:
    """Replace ``CitiVelocityExcelClient.connect`` for the life of the process.

    Returns the ONE recorder every connect hands back, so the count is across
    the whole run rather than per ``CitiVeloQuotes``.
    """
    from MDP.CitiVelocityExcel import com_client as _cc

    recorder = RecordingCacheClient(latency=latency, dense=dense)

    def _connect(*_a: Any, **_k: Any) -> RecordingCacheClient:
        return recorder

    _cc.CitiVelocityExcelClient.connect = staticmethod(_connect)  # type: ignore[assignment]
    return recorder


def install_memoised_reference_data() -> None:
    """Stop ``force_refresh=True`` re-downloading fiscaldata once per timestamp.

    Symmetric across before and after, and not what is under test - but 60 live
    HTTP round trips inside a benchmark would both dominate the number and make
    the run non-hermetic.
    """
    from MDP.FixedRateBonds.reference_data_cache import ust_reference_data as _urd

    real = _urd.update_reference_data
    memo: Dict[str, pd.DataFrame] = {}

    def _memo(source: str, source_kwargs=None, force_refresh: bool = False):
        if source not in memo:
            memo[source] = real(source, source_kwargs, force_refresh=False)
        return memo[source]

    _urd.update_reference_data = _memo  # type: ignore[assignment]


def isolate_disk_caches() -> pathlib.Path:
    """A fresh pricer/row cache root, so a run is not answered by the last one."""
    from Caching.DiskCacheMixin import DiskCacheMixin

    root = pathlib.Path(tempfile.mkdtemp(prefix="bench-citivelo-frb-"))
    DiskCacheMixin.CACHE_ROOT = str(root)
    return root


# ------------------------------------------------------------------ #
#                            the measurement                         #
# ------------------------------------------------------------------ #


def _minute_points(day: datetime.date, hour: int, minute: int, n: int) -> List[datetime.datetime]:
    """``n`` naive one-minute stamps. Naive because ``resolve_request`` reads a
    tz-aware stamp as a WIRE instant to convert, and the cache is stamped in the
    wire zone already - a tz-aware stamp here would shift the window."""
    first = datetime.datetime(day.year, day.month, day.day, hour, minute)
    return [first + datetime.timedelta(minutes=i) for i in range(n)]


def disable_prefetch() -> None:
    """Make the range warm a no-op, to measure the per-point path on its own.

    This is the in-process CONTROL, not a faithful replay of the pre-fix code:
    that also issued one ``DAILY`` request for an all-intraday range, which this
    skips. The difference is one round trip out of sixty-one and it is noted
    rather than modelled.
    """
    from MDP.FixedRateBonds import FixedRateBondsMDP as _mod

    _mod.FixedRateBondsMDP._citivelo_prefetch_range = (  # type: ignore[assignment]
        lambda self, **_k: _mod._CitiVeloPrefetch()
    )


def run_once(*, cusip: str, points: List[datetime.datetime], recorder: RecordingCacheClient) -> Dict[str, Any]:
    from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP
    from Query.Unified.UnifiedQuery import UnifiedQuery
    from Query.Unified.registry import UnifiedValue
    from TB.FixedRateBondsTB import FixedRateBondsTB
    from TB.TimeseriesBuilder import TimeseriesBuilder

    ts_dir = tempfile.mkdtemp(prefix="bench-citivelo-ts-")
    mdp = FixedRateBondsMDP(source="USTS_CITIVELO-RL")
    router = FixedRateBondsTB(mdp, show_tqdm=False, ts_base_dir=ts_dir, use_duckdb=False)
    tb = TimeseriesBuilder()

    before = recorder.round_trips
    t0 = time.perf_counter()
    df = tb.get_timeseries(
        start=points[0],
        end=points[-1],
        timestamps=points,
        queries=[UnifiedQuery(cusip=cusip, value=UnifiedValue.FRB_YTM)],
        routers={"FRB": router},
        n_jobs=1,
    )
    elapsed = time.perf_counter() - t0
    router.close()

    served = 0
    values: Dict[str, float] = {}
    if df is not None and not df.empty:
        numeric = df.select_dtypes("number")
        if not numeric.empty:
            col = numeric.iloc[:, 0]
            served = int(col.notna().sum())
            values = {str(k): float(v) for k, v in col.dropna().items()}

    trips = recorder.round_trips - before
    return {
        "seconds": elapsed,
        "points": len(points),
        "rows": 0 if df is None else int(len(df)),
        "served": served,
        "round_trips": trips,
        "ms_per_point": 1000.0 * elapsed / max(1, len(points)),
        "projected_seconds": elapsed + trips * SETTLE_SECONDS,
        "widest_request_span": str(recorder.widest_span()),
        "sheets_pushed": recorder.sheets_pushed,
        "values": values,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cusip", default="CT10")
    ap.add_argument("--points", type=int, default=60)
    ap.add_argument("--day", default="2026-08-07")
    ap.add_argument("--hour", type=int, default=10)
    ap.add_argument("--minute", type=int, default=0)
    ap.add_argument("--latency", type=float, default=0.0,
                    help="Seconds charged per vendor round trip. 0 measures the code alone.")
    ap.add_argument("--json", default="", help="Write the result dict here.")
    ap.add_argument("--sparse", action="store_true",
                    help="Serve the cache's own (2-minute median) rows instead of a minute grid.")
    ap.add_argument("--no-prefetch", action="store_true",
                    help="CONTROL: no-op the range warm, so every point reads for itself.")
    args = ap.parse_args(list(argv) if argv is not None else None)

    isolate_disk_caches()
    install_memoised_reference_data()
    recorder = install_hermetic_vendor(latency=args.latency, dense=not args.sparse)
    if args.no_prefetch:
        disable_prefetch()

    day = datetime.date.fromisoformat(args.day)
    points = _minute_points(day, args.hour, args.minute, args.points)

    out = run_once(cusip=args.cusip, points=points, recorder=recorder)
    out["settle_seconds_per_round_trip_PROJECTION"] = SETTLE_SECONDS
    out["freqs_requested"] = sorted({c["freq"] for c in recorder.calls})
    out["prefetch"] = "disabled" if args.no_prefetch else "enabled"

    printable = {k: v for k, v in out.items() if k != "values"}
    print(json.dumps(printable, indent=1, default=str))
    if args.json:
        pathlib.Path(args.json).write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
