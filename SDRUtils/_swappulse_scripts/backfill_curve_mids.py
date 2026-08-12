"""Materialise the intraday swap mid, per tenor per minute, into Postgres.

    schema    create/ALTER the two tables. Cheap, additive, idempotent.
    backfill  per ET calendar day, parallel, expensive -> parquet on D: -> PG
    verify    re-read what was written and prove each day produced its rows
    validate  the known-answer check against arbs_dd_unit_v1.deviation_bps
    status    what exists, per stage

WHY THIS TABLE EXISTS
=====================

The tape front end draws prints against where the market actually was. The
Citi Velocity minute curve store is local parquet/DuckDB and the web tier
cannot reach it -- the same constraint that forced the dealer-direction
materialisation -- so the mid has to be materialised too.

ONE PRICER, NOT TWO
===================

The mid published here comes from ``midprice.SessionBranchPricer.price_leg``:
the same object, the same curve, the same session-branched snapshot policy
that priced the deviation behind every direction annotation. This is the
single most important property of this runner. A second, independent
discount-factor path would let the chart and the annotations drawn on top of
it disagree by a fraction of a basis point, and nothing anywhere would say so.

It is measured rather than asserted. ``arbs_dd_unit_v1`` stores, per print,
``deviation_bps = traded structure price - model mid``, so for a single-leg
OUTRIGHT decided by ``RATE_VS_MID``::

    implied_mid_pct = fixed_rate * 100 - deviation_bps / 100

and the grid must reproduce that. Over 890 such prints on three days, at
1-minute spacing, matched on the print's own dates: **max |error| 2.7e-13 bp,
median 4.4e-14 bp**. That is the ``validate`` stage, and it is a first-class
stage precisely because a pipeline that is subtly wrong on conventions looks
completely plausible and is off by a basis point.

ONE MINUTE, AND WHY IT IS NOT A TASTE CALL
==========================================

``snapshot.snap_instant`` floors the pricing clock to the minute and steps
back one, so every ``arbs_dd_unit_v1.curve_timestamp`` sits on a whole minute
(973,305 of 973,305 rows carry ``second = 0``). A 1-minute grid therefore
lands on *exactly* the instant the annotation priced at, and the join is
equality. Coarser grids do not merely lose resolution, they disagree with the
annotation drawn on them -- measured, median / p95 |error| in bp on exact-date
prints:

    spacing     1Y            5Y            10Y
     1-min      0.000/0.097   0.000/0.000   0.000/0.000
     5-min      0.040/0.455   0.100/0.575   0.080/0.498
    15-min      0.101/1.687   0.150/0.953   0.156/0.864

At ~101 s of CPU per day the finest grid is affordable (2.3-2.7 h for the
whole 610-day tape at 8 workers), so there is no trade to make.

THE GRID INSTANTS COME FROM THE STORE, NOT FROM A DATE RANGE
============================================================

The minutes priced are the store partition's **own** minute stamps for the ET
calendar day. That gets DST, truncated sessions and interior holes right for
free: 0 strict misses on 5 of 5 pilot days, against 180 wasted misses when a
01:00-22:59 range was generated for 2026-06-05. It is also what makes the
completion check an equality -- ``n_rows == n_tenors * minutes_served`` -- and
not a "non-zero" test. Exit code 0 is not evidence a day produced anything.

WHAT A DAY IS
=============

An **ET calendar date**, because that is what the store partitions on and what
a chart is drawn for. NOT the tape's ``as_of_date``, which is a UTC date: ~4%
of a tape day's prints were executed the previous ET evening, and keying the
grid on ``as_of_date`` puts those prints a whole day from their own minutes.
The day set is still derived from the tape (see :func:`grid_days`) and never
from a calendar, because a calendar disagrees with the tape on exactly the
days that matter -- but it is derived as the ET dates the tape's own clocks
fall on, clamped to the requested window.

A date on which Citi has no session at all (Saturday) is recorded as
``NO_SESSION`` and is not an error. A date **with** a session whose partition
is empty is a failed read, and is.

COSTS AND THE FIXINGS FLAG
==========================

Measured on 2026-04-01, one process: the curve build is 3.3 ms and pricing the
22 SOFR tenors is 458 ms, so the tenor count is the cost lever and the
frequency is nearly free per curve. ``ARBS_RL_OMIT_UNUSED_FIXINGS=1`` takes
that 458 ms to 67.5 ms -- 6.8x -- and the 33 tenor-curve par rates it produces
are **bit-identical** (max difference 0.000e+00). It only applies to legs
starting after the curve's reference date, which is exactly what a spot grid
is, and it must be set before the first curve build in the process because the
env read is cached.
"""
from __future__ import annotations

import os

# Before anything can import Caching, which reads the flag at import time.
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
# The citivelo curve path must never open Excel from a batch worker.
os.environ.setdefault("ARBS_CITIVELO_QUOTES_OFFLINE", "1")
# 6.8x on the pricing, bit-identical output on a spot-start grid. See the
# module docstring. Set here because `omit_unused_fixings()` caches the read,
# so it must precede the first curve build in the process.
os.environ.setdefault("ARBS_RL_OMIT_UNUSED_FIXINGS", "1")

import argparse  # noqa: E402
import datetime  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import pathlib  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
import traceback  # noqa: E402
import warnings  # noqa: E402

import pandas as pd  # noqa: E402

REPO = str(pathlib.Path(__file__).resolve().parents[2])
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from SDRUtils._swappulse_scripts import _dealer_direction_schema_v1 as S  # noqa: E402
# One adapter, not two. `_sanitize` is the psycopg2 numpy/NaN adapter and
# `_atomic_parquet` the .tmp-then-os.replace writer; re-spelling either here
# would let this runner drift away from the one that was debugged.
from SDRUtils._swappulse_scripts.backfill_dealer_direction import (  # noqa: E402
    _atomic_parquet, _sanitize, connect,
)
from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE  # noqa: E402

DEFAULT_CACHE = pathlib.Path(os.getenv("MIDGRID_CACHE", r"D:\midgrid_cache"))

#: The tape starts here, and both minute stores cover **610 of 610** tape days
#: from this date with no missing day -- measured, which is why there is no
#: store-floor truncation. Kept equal to the dealer-direction price floor so
#: the two materialisations describe the same history.
GRID_FLOOR = "2024-03-01"

#: Both indices the direction universe admits, and both are drawn.
INDICES = ("SOFR", "FED_FUNDS")

#: The minute-store asset for a curve. Spelled the way ``IRSwapsMDP`` spells it
#: (``IRSwapsMDP.py:3207``) and derived from the pricer's own curve name rather
#: than hard-coded, because if the asset we take the grid instants from is not
#: the asset the pricer serves from, every single minute misses -- which is
#: indistinguishable from a cold store.
MINUTE_ASSET_SUFFIX = "-CITIVELOEXCELMIN"

#: THE TENOR GRID, decided by measurement, not by taste.
#:
#: SOFR: 21 tenors covering **95.3% of all SOFR flow prints and 93.7% of
#: |risk|** (96.5% / 97.1% restricted to spot-start STANDARD prints). 40Y is
#: deliberately absent: it alone is 17% of a full SOFR grid minute (9.7 ms of
#: 67.5) and buys 2.4 prints a day.
#:
#: FED_FUNDS: 12 tenors, 88.7% of FF flow prints and 90.4% of |risk|. Widening
#: to 19 buys 93.5% for +10 s/day and +9,086 rows/day -- measured, and not
#: worth it. Note what no standard-tenor grid can represent: **67% of FF flow
#: legs are FOMC meeting-dated**, and a meeting-to-meeting swap is not a
#: constant-maturity point. Those prints have no row here by construction.
TENORS = {
    "SOFR": ("1M", "2M", "3M", "6M", "9M", "1Y", "18M", "2Y", "3Y", "4Y",
             "5Y", "6Y", "7Y", "8Y", "9Y", "10Y", "12Y", "15Y", "20Y", "25Y",
             "30Y"),
    "FED_FUNDS": ("1M", "2M", "3M", "4M", "6M", "9M", "1Y", "18M", "2Y", "3Y",
                  "5Y", "10Y"),
}

#: Notional every grid leg is priced on, so ``pv01`` is per 1 mm and a reader
#: can scale it. The rate itself is notional-invariant.
GRID_NOTIONAL = 1_000_000.0

#: The spot rule: ``calendar_advance(curve.reference_date(), "2b")``, which is
#: what ``RLIRSwapCurve.build_irswap(fwd="0D")`` already does in this repo
#: (``SettlementDays: 2, Calendar: "nyc", BusinessConvention: "mf"`` for both
#: curves). Scored against the tape's own modal effective date over 629 ET
#: dates: 500 exact, and 598 once the reference date's own weekend/holiday
#: roll-back is counted -- 99.3% by print count. The residue is IMM roll weeks,
#: which have no modal spot convention to match.
#:
#: One measured anomaly, bounded: Good Friday 2026 (04-03) traded as a
#: settlement day on the tape while ``nyc`` holds it, so on 2026-04-01/02 this
#: rule differs from the tape's by <= 0.16 bp at 1M, <= 0.06 bp at 2Y-10Y and
#: ~0 at 30Y. Two days a year, and both dates are on every row.
SPOT_TENOR = "2b"

#: A served minute must be answered within this. In-session the policy is
#: strict to the minute, and every grid instant is a store stamp and therefore
#: in-session, so this is a check on the branch rather than a tolerance.
MAX_EXPECTED_LAG_SECONDS = 60.0

#: ``verify``: hard floor on served/partition. The pilot measured 1.000 on
#: every day, so anything below this is a real refusal to explain.
DEFAULT_SERVED_FLOOR = 0.99

#: ``verify``: soft floor on partition/session-expected, REPORTED not raised.
#: Truncated sessions are real -- 2026-04-02 ends 19:59 ET, 2026-06-05 ends
#: 17:59, the minimum observed is 911 of 1,320 minutes -- so a hard floor here
#: would fail on the market rather than on the pipeline.
DEFAULT_DENSITY_WARN = 0.65

STATUS_OK = "ok"
STATUS_NO_SESSION = "NO_SESSION"


# ==========================================================================
# small helpers
# ==========================================================================

def _f(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if not math.isfinite(f) else f


def minute_asset(curve_name: str) -> str:
    return f"{curve_name}{MINUTE_ASSET_SUFFIX}"


def grid_days(start: str, end: str, *, chunk_days: int = 60) -> list[str]:
    """The ET calendar dates to draw, derived FROM THE TAPE.

    Never from a calendar. But also not from ``as_of_date`` directly: that is a
    UTC date and the grid is partitioned on New York, so the dates are taken
    from the tape's own clocks and clamped to the requested window.

    ``execution_timestamp`` is unnested beside ``event_timestamp`` because a
    lifecycle print carries an execution stamp frozen at the *original* trade
    -- sometimes years back (spec Appendix F Example 3 shows a twenty-month
    gap) -- and the event stamp is the one that lands on the day the print is
    drawn on. Taking the union of the two and clamping to the window keeps both
    clocks' dates and drops the stale ones, without a second scan.

    Read in chunks: an unbounded analytical scan of the whole tape dies by
    statement timeout the moment the tape pipeline migrates schema underneath
    it, and the fix for that is to chunk the read, not to raise the timeout.
    """
    lo = datetime.date.fromisoformat(start)
    hi = datetime.date.fromisoformat(end)
    # One day of lead-in: a print executed at 20:30 ET on the evening before
    # `start` carries as_of = start, and its own minutes live on the previous
    # ET date.
    keep_lo = lo - datetime.timedelta(days=1)

    sql = f"""
SELECT DISTINCT unnest(ARRAY[
    (execution_timestamp AT TIME ZONE 'America/New_York')::date,
    (event_timestamp     AT TIME ZONE 'America/New_York')::date]) AS d
FROM {LEGS_TABLE}
WHERE as_of_date BETWEEN %(s)s AND %(e)s
"""
    found: set[datetime.date] = set()
    conn = connect()
    try:
        cur_lo = lo
        while cur_lo <= hi:
            cur_hi = min(cur_lo + datetime.timedelta(days=chunk_days - 1), hi)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                df = pd.read_sql(sql, conn, params={"s": cur_lo.isoformat(),
                                                    "e": cur_hi.isoformat()})
            for d in df["d"].dropna():
                d = pd.Timestamp(d).date()
                if keep_lo <= d <= hi:
                    found.add(d)
            cur_lo = cur_hi + datetime.timedelta(days=1)
    finally:
        conn.close()

    if not found:
        raise RuntimeError(
            f"the tape has no prints in {start}..{end}; that is a failed read, "
            "not an empty range")
    return [d.isoformat() for d in sorted(found)]


class Paths:
    def __init__(self, root: pathlib.Path):
        self.root = pathlib.Path(root)
        self.grid = self.root / "grid"
        self.tmp = self.root / "tmp"

    def mkdirs(self):
        for d in (self.grid, self.tmp):
            d.mkdir(parents=True, exist_ok=True)

    def parquet(self, day: str) -> pathlib.Path:
        return self.grid / f"{day}.parquet"

    def stats(self, day: str) -> pathlib.Path:
        return self.grid / f"{day}.json"


# ==========================================================================
# STAGE 1 -- build one ET calendar day
# ==========================================================================

GRID_COLS = [
    "grid_date", "rate_index", "tenor_label", "ts", "served_ts",
    "snapshot_lag_seconds", "snapshot_policy", "mid_pct", "pv01",
    "effective_date", "maturity_date", "curve_name", "curve_source",
    "code_vintage",
]

DAY_COLS = [
    "grid_date", "rate_index", "curve_name", "partition_minutes",
    "session_expected_minutes", "minutes_served", "minutes_missed", "n_rows",
    "n_tenors", "n_reference_dates", "seconds", "status", "error_text",
    "code_vintage",
]

_ENGINES = None


def _engines():
    """One pricer and one store per worker process, built on first use.

    Built lazily in a module global rather than passed in: an ``IRSwapsMDP``
    and a ``CurveStore`` do not pickle across a process boundary, and building
    them once per day would pay the 1.3-1.9 s cold-import cost 610 times.
    """
    global _ENGINES
    if _ENGINES is None:
        from Caching.curve_store import CurveStore
        from SDRUtils.dealer_direction import midprice, snapshot
        # THE PRICER. `UnitRepricer.for_source` is the direction pipeline's own
        # entry point and it wraps exactly this object; the grid needs
        # `price_leg` rather than `price_unit`, so the SessionBranchPricer is
        # taken directly -- same class, same source token, same two policies.
        rep = midprice.UnitRepricer.for_source(snapshot.CURVE_SOURCE)
        _ENGINES = (rep, rep.pricer, CurveStore.default())
    return _ENGINES


def _served_ts(mark, requested):
    """The instant actually served, as a UTC timestamp.

    Read from the handle's own metadata where it is published, and otherwise
    reconstructed from the signed lag -- which is the same number written twice
    (``IRSwapsMDP.py:3336`` publishes both from one line). ``None`` only when
    the pricer reports neither, and on a snapshot-governed source that state
    already raised upstream.
    """
    raw = getattr(mark, "served_utc", None)
    if raw is not None:
        t = pd.Timestamp(raw)
        return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")
    lag = mark.lag_seconds
    if lag is None:
        return None
    return (pd.Timestamp(requested).tz_convert("UTC")
            - pd.Timedelta(seconds=float(lag)))


def _day_minutes(store, asset: str, day: datetime.date, ny) -> list:
    """The store partition's OWN minute stamps for this ET calendar date.

    Not a generated ``date_range``. See the module docstring: the store's
    stamps carry DST, the truncated sessions and the interior holes for free,
    and they are what makes the completion check an equality.
    """
    raw = store.read_raw_day(asset, day)
    if raw is None or len(raw) == 0:
        return []
    ts = (pd.to_datetime(raw["timestamp_utc"], utc=True)
          .dt.floor("min").dt.tz_convert(ny))
    return sorted(pd.Timestamp(t) for t in ts.unique())


def build_one_day(day: str, paths: Paths, *, dry_run: bool = False,
                  reprice: bool = False) -> dict:
    """One ET calendar date: every servable minute, every tenor, both indices.

    Writes the day's parquet atomically, then delete-and-inserts it into
    Postgres in one transaction at the end -- so a day that fails halfway
    through its second index leaves the previous run's rows intact rather than
    a half-day.
    """
    import pytz

    from MDP.IRSwaps.CITIVELO_EXCEL import citi_session
    from MDP.IRSwaps.CITIVELO_EXCEL.snapshot_policy import SnapshotMiss
    from SDRUtils.dealer_direction import provenance as prov
    from SDRUtils.dealer_direction import snapshot as snap

    t0 = time.perf_counter()
    ny = pytz.timezone("America/New_York")
    vintage = prov.code_vintage(snap.CURVE_SOURCE)
    d = datetime.date.fromisoformat(day)

    cached = _load_cached(paths, day) if not reprice else None
    if cached is not None:
        grid_df, day_rows = cached
        for r in day_rows:
            r["code_vintage"] = r.get("code_vintage") or vintage
    else:
        _rep, pricer, store = _engines()
        rows: list[tuple] = []
        day_rows: list[dict] = []

        with pricer.day_scope():
            for index in INDICES:
                curve = pricer.curve_for(index)
                asset = minute_asset(curve)
                expected = citi_session.expected_minutes(curve, d)
                minutes = _day_minutes(store, asset, d, ny)

                if not minutes:
                    if expected == 0:
                        # Saturday, or the part of Sunday before Citi's weekly
                        # open. There is no session, so there is nothing to
                        # read and nothing to explain.
                        day_rows.append(_day_row(
                            day=day, index=index, curve=curve,
                            partition_minutes=0, expected=expected, served=0,
                            missed=0, n_rows=0, n_tenors=0, n_refs=None,
                            status=STATUS_NO_SESSION, error=None,
                            vintage=vintage))
                        continue
                    raise RuntimeError(
                        f"{day}/{index}: the minute store partition {asset!r} "
                        f"is empty on a date Citi publishes {expected} minutes "
                        "for. That is a failed read, not a quiet market.")

                served = missed = 0
                dates_by_ref: dict = {}
                for t in minutes:
                    try:
                        mark = pricer.mark_curve(curve, t)
                    except SnapshotMiss:
                        # Skipped and COUNTED. Never fabricated: an interpolated
                        # value here would be indistinguishable from a real
                        # mark on the chart.
                        missed += 1
                        continue
                    handle = mark.handle
                    ref = pd.Timestamp(handle.reference_date()).date()
                    dates = dates_by_ref.get(ref)
                    if dates is None:
                        # Memoised per reference date rather than per day: if
                        # the reference date moves inside the day then the spot
                        # date moves with it, and holding the first would make
                        # every later row's stated instrument false.
                        spot = handle.calendar_advance(
                            handle.reference_date(), SPOT_TENOR)
                        dates = (spot, {tn: handle.calendar_advance(spot, tn)
                                        for tn in TENORS[index]})
                        dates_by_ref[ref] = dates
                    spot, mats = dates
                    sts = _served_ts(mark, t)
                    served += 1
                    for tn in TENORS[index]:
                        lp = pricer.price_leg(curve, t, spot, mats[tn],
                                              GRID_NOTIONAL)
                        mid = _f(lp.mid_pct)
                        if mid is None:
                            # The curve WAS served, so this is a pricing defect
                            # rather than a store hole. Failing the day is the
                            # only honest outcome: a NULL mid on a NOT NULL
                            # column would be rejected, and a skipped row would
                            # read as a market that was not publishing.
                            raise RuntimeError(
                                f"{day}/{index}/{tn} at {t}: the served curve "
                                f"produced a non-finite mid ({lp.mid_pct!r})")
                        rows.append((
                            day, index, tn, t, sts, mark.lag_seconds,
                            mark.policy, mid, _f(lp.pv01), spot, mats[tn],
                            curve, snap.CURVE_SOURCE, vintage))

                day_rows.append(_day_row(
                    day=day, index=index, curve=curve,
                    partition_minutes=len(minutes), expected=expected,
                    served=served, missed=missed,
                    n_rows=served * len(TENORS[index]),
                    n_tenors=len(TENORS[index]),
                    n_refs=len(dates_by_ref), status=STATUS_OK, error=None,
                    vintage=vintage))

        grid_df = pd.DataFrame(rows, columns=GRID_COLS)
        _atomic_parquet(grid_df, paths.parquet(day))
        _write_stats(paths, day, day_rows)

    secs = time.perf_counter() - t0
    for r in day_rows:
        r["seconds"] = secs

    # The equality that defines "done". Checked here as well as in `verify`,
    # because a day that silently produced the wrong number of rows must not
    # reach the database and be counted.
    want = sum(int(r["n_rows"]) for r in day_rows)
    if len(grid_df) != want:
        raise RuntimeError(
            f"{day}: wrote {len(grid_df)} rows but the per-index accounting "
            f"says {want} (n_tenors x minutes_served)")

    written = 0
    if not dry_run:
        written = publish_day(day, grid_df, day_rows)

    return {
        "day": day, "rows": len(grid_df), "written": written,
        "seconds": secs, "from_cache": cached is not None,
        "served": {r["rate_index"]: (r["minutes_served"], r["partition_minutes"])
                   for r in day_rows},
        "missed": sum(int(r["minutes_missed"]) for r in day_rows),
        "status": {r["rate_index"]: r["status"] for r in day_rows},
    }


def _day_row(*, day, index, curve, partition_minutes, expected, served, missed,
             n_rows, n_tenors, n_refs, status, error, vintage) -> dict:
    """The per-day accounting row. KEYWORD-ONLY, deliberately.

    Thirteen scalars of which six are integer counts that mean entirely
    different things -- ``partition_minutes``, ``expected``, ``served``,
    ``missed``, ``n_rows``, ``n_tenors``. Positionally, transposing any two of
    them produces a row that inserts cleanly and makes the completion check
    assert the wrong equality; the arity error that caught this on the first
    run was the lucky version of that mistake.
    """
    return {
        "grid_date": day, "rate_index": index, "curve_name": curve,
        "partition_minutes": int(partition_minutes),
        "session_expected_minutes": (None if expected is None else int(expected)),
        "minutes_served": int(served), "minutes_missed": int(missed),
        "n_rows": int(n_rows), "n_tenors": int(n_tenors),
        "n_reference_dates": (None if n_refs is None else int(n_refs)),
        "seconds": None, "status": status, "error_text": error,
        "code_vintage": vintage,
    }


def _write_stats(paths: Paths, day: str, day_rows: list) -> None:
    """The per-day accounting, beside the parquet, written atomically.

    It is a sidecar rather than columns on the frame because it is per
    (day, index) and the frame is per (day, index, tenor, minute) -- and
    because ``partition_minutes`` is a property of the curve store, so a
    re-publish from cache could not otherwise state its own denominator.
    """
    path = paths.stats(day)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.json")
    tmp.write_text(json.dumps(day_rows, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _load_cached(paths: Paths, day: str):
    """The day's staged parquet + stats, or ``None``.

    ``exists()`` is not the test -- a truncated parquet exists -- so both files
    are actually read. This is what makes a failed database write cheap to
    retry: the expensive half is on disk and the retry never touches a curve.
    """
    p, s = paths.parquet(day), paths.stats(day)
    if not (p.exists() and s.exists()):
        return None
    try:
        df = pd.read_parquet(p)
        rows = json.loads(s.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - an unreadable cache is a cache miss
        return None
    if not isinstance(rows, list) or not rows:
        return None
    return df.reindex(columns=GRID_COLS), rows


# ==========================================================================
# the database write
# ==========================================================================

def _rows_for_db(grid_df: pd.DataFrame) -> list:
    out = []
    for r in grid_df.to_dict("records"):
        row = dict(r)
        row["grid_date"] = pd.Timestamp(row["grid_date"]).date()
        for c in ("effective_date", "maturity_date"):
            v = row.get(c)
            row[c] = None if v is None or pd.isna(v) else pd.Timestamp(v).date()
        out.append(row)
    return out


def _write(conn, table: str, columns: list, rows: list, conflict: str,
           batch: int = 5000) -> int:
    from psycopg2.extras import execute_values
    if not rows:
        return 0
    keys = {c.strip() for c in conflict.split(",")}
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in columns if c not in keys)
    sql = (f"INSERT INTO {table} ({', '.join(columns)}) VALUES %s "
           f"ON CONFLICT ({conflict}) DO UPDATE SET {updates}")
    n = 0
    for i in range(0, len(rows), batch):
        chunk = [tuple(_sanitize(r.get(c)) for c in columns)
                 for r in rows[i:i + batch]]
        with conn.cursor() as cur:
            execute_values(cur, sql, chunk, page_size=batch)
        conn.commit()
        n += len(chunk)
    return n


def publish_day(day: str, grid_df: pd.DataFrame, day_rows: list) -> int:
    """Delete-then-insert this ET date, then upsert its accounting.

    One connection per worker, opened here and closed here. The delete is
    scoped to ``grid_date`` and runs only once the whole day priced, so a
    failure mid-day leaves the previous run's rows rather than half of them.
    """
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM {S.CURVE_MID_TABLE} WHERE grid_date = %s",
                        (day,))
        conn.commit()
        n = _write(conn, S.CURVE_MID_TABLE, GRID_COLS, _rows_for_db(grid_df),
                   "rate_index, tenor_label, ts")
        _write(conn, S.CURVE_MID_DAY_TABLE, DAY_COLS, day_rows,
               "grid_date, rate_index")
        return n
    finally:
        conn.close()


# ==========================================================================
# STAGE 1 -- the pool
# ==========================================================================

def _worker(args) -> dict:
    day, root, dry_run, reprice = args
    try:
        return build_one_day(day, Paths(pathlib.Path(root)), dry_run=dry_run,
                             reprice=reprice)
    except Exception as exc:  # noqa: BLE001 - one bad day must not kill a range
        return {"day": day,
                "error": f"{type(exc).__name__}: {exc}"[:500],
                "traceback": traceback.format_exc()[-1500:]}


def pending_days(days: list[str], *, force: bool) -> list[str]:
    """Resume by what is in THE TABLE for that day, not by what a ledger says.

    A ledger row is a claim; the row count is the fact, and the two disagree
    exactly when a publish died between the two writes. A day is done when
    every index it should carry has an accounting row **and** the grid table
    holds precisely ``sum(n_rows)`` rows for it.
    """
    if force:
        return list(days)
    conn = connect()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            led = pd.read_sql(
                f"SELECT grid_date, rate_index, status, n_rows FROM "
                f"{S.CURVE_MID_DAY_TABLE} WHERE grid_date = ANY(%(d)s::date[])",
                conn, params={"d": list(days)})
            got = pd.read_sql(
                f"SELECT grid_date, count(*) n FROM {S.CURVE_MID_TABLE} "
                "WHERE grid_date = ANY(%(d)s::date[]) GROUP BY grid_date",
                conn, params={"d": list(days)})
    finally:
        conn.close()
    if led.empty:
        return list(days)
    led["grid_date"] = led["grid_date"].map(lambda x: pd.Timestamp(x).date().isoformat())
    got["grid_date"] = got["grid_date"].map(lambda x: pd.Timestamp(x).date().isoformat())
    have = dict(zip(got["grid_date"], got["n"].astype(int)))
    claimed = (led.groupby("grid_date")["n_rows"].sum().astype(int).to_dict())
    n_idx = led.groupby("grid_date")["rate_index"].nunique().to_dict()

    todo = []
    for day in days:
        if n_idx.get(day, 0) < len(INDICES):
            todo.append(day)
        elif int(have.get(day, 0)) != int(claimed.get(day, -1)):
            todo.append(day)
    return todo


def stage_backfill(days: list[str], paths: Paths, workers: int,
                   budget_min: float, dry_run: bool, force: bool,
                   reprice: bool) -> int:
    import concurrent.futures as cf

    paths.mkdirs()
    todo = days if dry_run else pending_days(days, force=force)
    print(f"backfill: {len(days)} target ET dates, {len(todo)} to do, "
          f"{workers} workers, budget {budget_min:.0f} min"
          f"{' [DRY RUN]' if dry_run else ''}", flush=True)
    if not todo:
        return 0

    deadline = time.time() + budget_min * 60.0
    done = errs = rows = 0
    t0 = time.time()
    with cf.ProcessPoolExecutor(max_workers=workers) as pool:
        pending, it = set(), iter(todo)
        for _ in range(workers):
            nxt = next(it, None)
            if nxt is not None:
                pending.add(pool.submit(
                    _worker, (nxt, str(paths.root), dry_run, reprice)))
        while pending:
            fin, pending = cf.wait(pending, return_when=cf.FIRST_COMPLETED)
            for fut in fin:
                r = fut.result()
                done += 1
                if "error" in r:
                    errs += 1
                    print(f"  {r['day']}: ERROR {r['error']}", flush=True)
                    print(r.get("traceback", ""), flush=True)
                else:
                    rows += r["rows"]
                    served = ", ".join(
                        f"{k} {v[0]}/{v[1]}" for k, v in r["served"].items())
                    print(f"  {r['day']}: {r['rows']:,} rows ({served}"
                          f"{', %d missed' % r['missed'] if r['missed'] else ''})"
                          f", {r['seconds']:.0f}s"
                          f"{' [cache]' if r['from_cache'] else ''} "
                          f"[{done}/{len(todo)}]", flush=True)
                if time.time() < deadline:
                    nxt = next(it, None)
                    if nxt is not None:
                        pending.add(pool.submit(
                            _worker, (nxt, str(paths.root), dry_run, reprice)))
    wall = time.time() - t0
    print(f"backfill: {done} days, {rows:,} rows in {wall / 60:.1f} min "
          f"({wall / max(done, 1):.1f} s/day wall), {errs} errors", flush=True)
    return 1 if errs else 0


# ==========================================================================
# STAGE 2 -- verify
# ==========================================================================

def stage_verify(days: list[str], served_floor: float,
                 density_warn: float) -> int:
    """Re-read what was written and prove each TARGET day produced its rows.

    Scoped to the target day set, never to the ledger's own contents: a
    completion check that iterates what the ledger holds reports success on the
    days it reached and is silent about the ones it never started.
    """
    conn = connect()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            led = pd.read_sql(
                f"SELECT * FROM {S.CURVE_MID_DAY_TABLE} "
                "WHERE grid_date = ANY(%(d)s::date[])",
                conn, params={"d": list(days)})
            got = pd.read_sql(
                f"SELECT grid_date, rate_index, count(*) n, "
                "count(*) FILTER (WHERE mid_pct IS NULL) n_null, "
                "max(abs(snapshot_lag_seconds)) max_lag, "
                "count(DISTINCT tenor_label) n_tenors "
                f"FROM {S.CURVE_MID_TABLE} "
                "WHERE grid_date = ANY(%(d)s::date[]) "
                "GROUP BY grid_date, rate_index",
                conn, params={"d": list(days)})
    finally:
        conn.close()

    for frame in (led, got):
        if not frame.empty:
            frame["grid_date"] = frame["grid_date"].map(
                lambda x: pd.Timestamp(x).date().isoformat())

    problems: list[str] = []
    warn: list[str] = []
    seen = set()
    if not led.empty:
        seen = set(zip(led["grid_date"], led["rate_index"]))
    counts = ({} if got.empty else
              {(r["grid_date"], r["rate_index"]): r for r in got.to_dict("records")})

    n_ok = n_nosession = 0
    for day in days:
        for index in INDICES:
            key = (day, index)
            if key not in seen:
                problems.append(f"{day}/{index}: no accounting row at all")
                continue
            row = led[(led["grid_date"] == day)
                      & (led["rate_index"] == index)].iloc[0]
            if row["status"] == STATUS_NO_SESSION:
                n_nosession += 1
                continue
            want = int(row["n_rows"])
            have = int(counts.get(key, {}).get("n", 0))
            if have != want:
                problems.append(
                    f"{day}/{index}: {have:,} rows in the table against "
                    f"{want:,} claimed (n_tenors x minutes_served)")
                continue
            if want != int(row["n_tenors"]) * int(row["minutes_served"]):
                problems.append(
                    f"{day}/{index}: the ledger's own n_rows {want} is not "
                    f"{row['n_tenors']} x {row['minutes_served']}")
                continue
            if have == 0:
                problems.append(f"{day}/{index}: zero rows on a session day")
                continue
            part = int(row["partition_minutes"])
            frac = row["minutes_served"] / part if part else 0.0
            if frac < served_floor:
                problems.append(
                    f"{day}/{index}: served {row['minutes_served']}/{part} "
                    f"= {frac:.3f} of the partition, below the {served_floor} "
                    "floor -- those minutes were refused, not absent")
            exp = row["session_expected_minutes"]
            if exp and part / float(exp) < density_warn:
                warn.append(f"{day}/{index}: partition holds {part} of the "
                            f"{int(exp)} minutes Citi publishes "
                            f"({part / float(exp):.2f})")
            lag = counts.get(key, {}).get("max_lag")
            if lag is not None and float(lag) > MAX_EXPECTED_LAG_SECONDS:
                warn.append(f"{day}/{index}: max |snapshot lag| {float(lag):.0f}s "
                            f"exceeds {MAX_EXPECTED_LAG_SECONDS:.0f}s")
            if int(counts[key]["n_null"]):
                problems.append(f"{day}/{index}: {counts[key]['n_null']} NULL mids")
            if int(counts[key]["n_tenors"]) != len(TENORS[index]):
                problems.append(
                    f"{day}/{index}: {counts[key]['n_tenors']} distinct tenors "
                    f"against the {len(TENORS[index])} in the grid")
            n_ok += 1

    print(f"verify: {len(days)} target ET dates x {len(INDICES)} indices; "
          f"{n_ok} complete, {n_nosession} with no session, "
          f"{len(problems)} problems, {len(warn)} warnings", flush=True)
    for w in warn[:20]:
        print(f"  WARN {w}", flush=True)
    if len(warn) > 20:
        print(f"  ... and {len(warn) - 20} more warnings", flush=True)
    if problems:
        for p in problems[:20]:
            print(f"  FAIL {p}", flush=True)
        if len(problems) > 20:
            print(f"  ... and {len(problems) - 20} more", flush=True)
        raise RuntimeError(
            f"{len(problems)} day/index pair(s) did not produce their rows. "
            "Exit code 0 is not evidence a day produced anything.")
    return 0


# ==========================================================================
# STAGE 3 -- validate: the known-answer check
# ==========================================================================

#: The population the identity holds on exactly: one leg, priced by the rate
#: rule, kept by the direction pipeline, spot-starting and standard-tenor so a
#: constant-maturity grid point is the same instrument.
VALIDATE_SQL = f"""
SELECT u.package_id, u.rate_index, u.curve_timestamp, u.deviation_bps,
       u.snapshot_policy, l.tenor_label, l.effective_date, l.expiration_date,
       l.fixed_rate
FROM {S.UNIT_TABLE} u
JOIN {LEGS_TABLE} l ON l.package_id = u.package_id
WHERE u.as_of_date BETWEEN %(s)s AND %(e)s
  AND u.kind = 'OUTRIGHT' AND u.n_legs = 1 AND u.rule = 'RATE_VS_MID'
  AND u.exclusion_reason IS NULL AND u.deviation_bps IS NOT NULL
  AND u.curve_timestamp IS NOT NULL
  AND u.special_tenor_type = 'STANDARD'
  AND l.economic_class = 'ECONOMIC_FLOW'
  AND l.fixed_rate IS NOT NULL
  -- The (index, tenor) PAIRS this grid can answer, not the union of the two
  -- tenor sets. Measured on 2025-10-15: filtering on the union left 11 prints
  -- of 647 "unmatched" -- every one of them a SOFR 4M or a FED_FUNDS 4Y/7Y,
  -- i.e. a tenor that is in the OTHER index's grid and absent from its own by
  -- construction. An unmatched count that is really a filter artifact sends
  -- the next reader hunting a gap that is not there.
  AND (u.rate_index, l.tenor_label) IN %(pairs)s
  AND (l.forward_start_years IS NULL OR abs(l.forward_start_years) < 0.02)
  AND l.effective_date >= (l.execution_timestamp
                           AT TIME ZONE 'America/New_York')::date
"""

#: The nearest grid point to each print, within a bounded window. A LATERAL
#: rather than a join on equality **on purpose**: the annotated print joins by
#: equality (its ``curve_timestamp`` IS a grid instant), and measuring the
#: distance is what proves that rather than assuming it.
NEAREST_SQL = f"""
SELECT p.package_id, g.ts, g.mid_pct, g.effective_date AS g_eff,
       g.maturity_date AS g_mat, g.snapshot_policy AS g_policy
FROM (VALUES %s) AS p(package_id, rate_index, tenor_label, curve_timestamp)
CROSS JOIN LATERAL (
    SELECT ts, mid_pct, effective_date, maturity_date, snapshot_policy
    FROM {S.CURVE_MID_TABLE} m
    WHERE m.rate_index = p.rate_index AND m.tenor_label = p.tenor_label
      AND m.ts BETWEEN p.curve_timestamp - interval '2 hours'
                   AND p.curve_timestamp + interval '2 hours'
    ORDER BY abs(extract(epoch FROM (m.ts - p.curve_timestamp)))
    LIMIT 1
) g
"""


def stage_validate(start: str, end: str, tenors: list | None,
                   out_path: pathlib.Path | None) -> int:
    """Does the grid reproduce the direction pipeline's own mid?

    ``arbs_dd_unit_v1.deviation_bps`` is the traded structure price minus the
    model mid, computed by the direction pipeline against this same curve store
    and this same pricer. For a single-leg OUTRIGHT priced by ``RATE_VS_MID``
    the structure price is the rate itself, so::

        implied_mid_pct = fixed_rate * 100 - deviation_bps / 100

    and the grid's par rate at (or nearest to) that instant must reproduce it.
    That is an independent known-answer check on the WHOLE pipeline -- the
    conventions, the day counts, the roll, the spot lag and the curve selection
    -- and it is the one measurement that decides whether this works.

    Split three ways because a convention fault otherwise hides inside a
    spacing number:

    * **exact-date** prints, whose own effective/maturity equal the grid's,
      isolate the pipeline. These must come back at ~1e-13 bp.
    * **other-date** prints differ only in the instrument. ``tenor_label`` is a
      bucket -- '10Y' spans 3,468-3,830 days over 273 distinct offsets -- so
      their spread is the bucket's width, not an error.
    * **by distance to the nearest grid point**, which is the only thing that
      says whether the spacing is too coarse.
    """
    from psycopg2.extras import execute_values

    want = set(tenors) if tenors else None
    pairs = tuple((idx, t) for idx in INDICES for t in TENORS[idx]
                  if want is None or t in want)
    if not pairs:
        raise ValueError(f"--validate-tenors {tenors} matches nothing in the "
                         "grid; there is nothing to check")
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT count(*) FROM {S.CURVE_MID_TABLE}")
            n_grid = int(cur.fetchone()[0])
        if n_grid == 0:
            print(f"validate: {S.CURVE_MID_TABLE} is empty -- run `backfill` "
                  "first. Nothing to check, and an empty check is not a pass.",
                  flush=True)
            return 1
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            prints = pd.read_sql(VALIDATE_SQL, conn,
                                 params={"s": start, "e": end, "pairs": pairs})
        if prints.empty:
            print("validate: no RATE_VS_MID single-leg prints in "
                  f"{start}..{end}. A window with no prints is a failed read, "
                  "not a quiet market.", flush=True)
            return 1
        prints = prints.drop_duplicates("package_id")

        keys = [(str(r["package_id"]), str(r["rate_index"]),
                 str(r["tenor_label"]), r["curve_timestamp"])
                for r in prints.to_dict("records")]
        near = []
        with conn.cursor() as cur:
            for i in range(0, len(keys), 2000):
                page = keys[i:i + 2000]
                # `fetch=True`, not a bare call followed by `fetchall()`:
                # execute_values splits an argslist longer than `page_size`
                # into several executes, and only the last one's rows would
                # still be on the cursor -- silently dropping most of the
                # comparisons this stage exists to make.
                near.extend(execute_values(
                    cur, NEAREST_SQL, page,
                    template="(%s,%s,%s,%s::timestamptz)",
                    page_size=len(page), fetch=True))
    finally:
        conn.close()

    grid = pd.DataFrame(near, columns=["package_id", "ts", "mid_pct", "g_eff",
                                       "g_mat", "g_policy"])
    df = prints.merge(grid, on="package_id", how="inner")
    n_unmatched = len(prints) - len(df)

    df["implied_mid_pct"] = (df["fixed_rate"].astype(float) * 100.0
                             - df["deviation_bps"].astype(float) / 100.0)
    df["err_bp"] = (df["mid_pct"].astype(float) - df["implied_mid_pct"]) * 100.0
    df["dt_s"] = (pd.to_datetime(df["ts"], utc=True)
                  - pd.to_datetime(df["curve_timestamp"], utc=True)
                  ).dt.total_seconds().abs()
    df["exact_date"] = (
        pd.to_datetime(df["effective_date"]).values
        == pd.to_datetime(df["g_eff"]).values) & (
        pd.to_datetime(df["expiration_date"]).values
        == pd.to_datetime(df["g_mat"]).values)

    print(f"\nvalidate: {len(prints):,} prints in {start}..{end}, "
          f"{len(df):,} matched to a grid point within 2 h, "
          f"{n_unmatched:,} unmatched", flush=True)
    print(f"  exact instant (dt = 0 s): {int((df['dt_s'] == 0).sum()):,} "
          f"({100.0 * (df['dt_s'] == 0).mean():.2f}%) -- the join rule is "
          "equality on ts, so this is the number that matters", flush=True)
    print(f"  exact-date prints:        {int(df['exact_date'].sum()):,} "
          f"({100.0 * df['exact_date'].mean():.2f}%)", flush=True)

    print("\n" + "=" * 76)
    print("(grid_mid - implied_mid) in bp")
    print("=" * 76)
    exact = df[df["exact_date"]]
    print(_dist(df["err_bp"], "ALL prints"))
    print(_dist(exact["err_bp"], "EXACT-DATE prints"))
    print(_dist(exact.loc[exact["dt_s"] <= 30, "err_bp"],
                "EXACT-DATE, |dt| <= 30 s"))
    print(_dist(df.loc[~df["exact_date"], "err_bp"],
                "other-date (bucket width)"))

    print("\nby rate_index and tenor, EXACT-DATE prints:")
    for (idx, t), d in exact.groupby(["rate_index", "tenor_label"]):
        print(_dist(d["err_bp"], f"{idx} {t}"))

    print("\nby distance to the nearest grid point, EXACT-DATE prints:")
    buckets = pd.cut(exact["dt_s"], [-1, 0, 30, 60, 120, 300, 600, 1800, 1e9],
                     labels=["0s", "<=30s", "30-60s", "1-2m", "2-5m", "5-10m",
                             "10-30m", ">30m"])
    for b, d in exact.groupby(buckets, observed=True):
        print(_dist(d["err_bp"], str(b)))

    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(out_path, index=False)
        print(f"\nwrote {out_path} ({len(df):,} comparisons)", flush=True)
    return 0


def _dist(s, label: str) -> str:
    s = pd.Series(s).dropna().astype(float)
    if not len(s):
        return f"  {label:<28} n=0"
    return (f"  {label:<28} n={len(s):>6}  med={s.median():+9.5f}  "
            f"mean={s.mean():+9.5f}  |p50|={s.abs().median():9.5f}  "
            f"|p95|={s.abs().quantile(0.95):9.5f}  "
            f"|max|={s.abs().max():9.2e}")


# ==========================================================================
# STAGE 4 -- status
# ==========================================================================

def stage_status(days: list[str], paths: Paths) -> int:
    staged = sum(1 for d in days
                 if paths.parquet(d).exists() and paths.stats(d).exists())
    print(f"staged: {staged}/{len(days)} ET dates under {paths.root}")
    try:
        conn = connect()
    except Exception as exc:  # noqa: BLE001
        print(f"  (no db: {exc})")
        return 0
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            for table, col in ((S.CURVE_MID_TABLE, "grid_date"),
                               (S.CURVE_MID_DAY_TABLE, "grid_date")):
                try:
                    df = pd.read_sql(
                        f"SELECT count(*) n, count(DISTINCT {col}) d, "
                        f"min({col}) lo, max({col}) hi FROM {table}", conn)
                    print(f"  {table}: {int(df['n'][0]):,} rows over "
                          f"{int(df['d'][0]):,} days {df['lo'][0]} .. "
                          f"{df['hi'][0]}")
                except Exception as exc:  # noqa: BLE001
                    print(f"  {table}: {type(exc).__name__}: {exc}")
                    conn.rollback()
            try:
                df = pd.read_sql(
                    f"SELECT rate_index, status, count(*) n, "
                    "sum(minutes_served) served, sum(minutes_missed) missed "
                    f"FROM {S.CURVE_MID_DAY_TABLE} GROUP BY 1, 2 ORDER BY 1, 2",
                    conn)
                if not df.empty:
                    print(df.to_string(index=False))
            except Exception:  # noqa: BLE001
                conn.rollback()
        todo = pending_days(days, force=False)
        print(f"  {len(todo)} of {len(days)} target ET dates still to do"
              + (f"; first: {todo[:5]}" if todo else ""))
    finally:
        conn.close()
    return 0


# ==========================================================================

#: The stages, in the order they are run. A constant so a test can pin them:
#: a renamed stage in a scheduled invocation fails as an unrecognised argument,
#: which is loud, but a *dropped* one fails as a stage nobody runs.
STAGES = ("schema", "backfill", "verify", "validate", "status")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Materialise the intraday swap mid grid, per tenor per "
                    "minute, from the same pricer the direction inference uses")
    ap.add_argument("stage", choices=list(STAGES))
    ap.add_argument("--start", default=GRID_FLOOR)
    ap.add_argument("--end", default=None)
    # 2, not 8. This box carries other long jobs; the parent widens it for the
    # real backfill, where 8 workers is 2.3-2.7 h for the whole tape.
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--budget-min", type=float, default=10_000.0)
    ap.add_argument("--cache-dir", default=str(DEFAULT_CACHE))
    ap.add_argument("--dry-run", action="store_true",
                    help="price and stage to parquet, write nothing to Postgres")
    ap.add_argument("--force", action="store_true",
                    help="re-do days that already have their rows")
    ap.add_argument("--reprice", action="store_true",
                    help="ignore the staged parquet and price from the curve "
                         "store again")
    ap.add_argument("--served-floor", type=float, default=DEFAULT_SERVED_FLOOR)
    ap.add_argument("--density-warn", type=float, default=DEFAULT_DENSITY_WARN)
    ap.add_argument("--validate-tenors", default=None,
                    help="comma-separated; defaults to the whole grid")
    ap.add_argument("--validate-out", default=None,
                    help="write the per-print comparisons to this parquet")
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    os.environ.setdefault("TMPDIR", str(pathlib.Path(args.cache_dir) / "tmp"))
    paths = Paths(pathlib.Path(args.cache_dir))
    paths.mkdirs()

    if args.stage == "schema":
        conn = connect()
        try:
            S.ensure_schema(conn)
        finally:
            conn.close()
        print("schema ensured: "
              + ", ".join((S.CURVE_MID_TABLE, S.CURVE_MID_DAY_TABLE)))
        return 0

    end = args.end or datetime.date.today().isoformat()

    if args.stage == "validate":
        tn = (args.validate_tenors.split(",") if args.validate_tenors else None)
        out = pathlib.Path(args.validate_out) if args.validate_out else None
        return stage_validate(args.start, end, tn, out)

    days = grid_days(args.start, end)
    print(f"{len(days)} ET calendar dates from the tape: "
          f"{days[0]} .. {days[-1]}", flush=True)

    if args.stage == "backfill":
        return stage_backfill(days, paths, args.workers, args.budget_min,
                              args.dry_run, args.force, args.reprice)
    if args.stage == "verify":
        return stage_verify(days, args.served_floor, args.density_warn)
    return stage_status(days, paths)


if __name__ == "__main__":
    sys.exit(main())
