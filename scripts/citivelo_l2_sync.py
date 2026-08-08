r"""Push the Citi Velocity local stores to the Supabase L2 tier, and check that it worked.

One CLI for every Citi asset in both stores, because the five families differ in
size by three orders of magnitude and every previous answer was a per-script
one-off (``citivelo_curve_service.py sync`` covers exactly one asset;
``citivelo_excel_warm.py --push-l2`` covers none, see below).

    family    store         assets                       what it is
    workbook  CurveStore    USD-SOFR-1D-CITIVELO         1-min, from the saved CVTSHIST workbook
    eod       CurveStore    <curve>-CITIVELOEXCEL        one curve per business day
    minute    CurveStore    <curve>-CITIVELOEXCELMIN     1-min, from live Excel
    stream    CurveStore    <curve>-CITIVELOSTREAM       the CVSTREAM daemon's ticks
    cube      CubeStore     <CCY>-SWAPTIONVOL-CITIVELO…  one swaption vol surface per day

Commands::

    plan    what would be pushed: days, bytes, and where local and remote differ
    push    do it (requires --yes; prints the target first)
    verify  pull each remote day back and compare it to the local bytes
    status  local vs remote coverage per asset

Why it does not call CurveStore.write_day
-----------------------------------------
``write_day`` enqueues a background push per call. Under the process pools these
warms use, each worker would build its own engine - pool 5 + overflow 4 = **9
connections per process** against a transaction-mode pooler - and that is how a
dev backfill exhausts a pooler the dashboard is also using. This runs in ONE
process with ONE engine and a bounded thread pool, so the connection count is
``--workers`` plus a small overflow, and it is the same number whether you push
five days or five thousand.

Resume
------
By content, not by presence. Local partitions are content-addressed, so the file
name *is* the sha and a whole-asset diff costs a directory listing plus one
indexed query with no payloads in it. A day whose local parquet was rebuilt since
it was pushed therefore shows up as ``differing`` rather than being skipped, which
is what ``backfill_local_curve_store_to_supabase``'s date-presence resume misses.

A differing day is **not** overwritten without ``--rewrite``. A restatement is
worth noticing.

Safety
------
``get_database_url()`` resolves hard-coded PRODUCTION credentials when nothing is
configured, so ``push`` prints the target and the byte count and refuses without
``--yes``. This script builds and passes its own engine rather than consulting
``Caching.supabase_engine.SUPABASE_ENABLED``, which is evaluated at import and is
therefore already decided by the time any CLI flag is parsed.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import dataclasses
import datetime
import json
import logging
import os
import pathlib
import re
import sys
import threading
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

LOGGER = logging.getLogger("citivelo_l2_sync")


# ── families ──────────────────────────────────────────────────────────────


@dataclasses.dataclass(frozen=True)
class Family:
    name: str
    kind: str  # "curve" | "cube"
    suffix: str
    note: str

    def matches(self, asset: str) -> bool:
        # endswith is unambiguous here even though "-CITIVELO" is a prefix of the
        # other three suffixes: "X-CITIVELOEXCEL" does not END with "-CITIVELO".
        # The one real collision is the cube asset, which also ends "-CITIVELOEXCEL";
        # it lives in a different store, and this excludes it anyway.
        if "-SWAPTIONVOL-" in asset:
            return self.kind == "cube" and asset.endswith(self.suffix)
        return self.kind == "curve" and asset.endswith(self.suffix)


FAMILIES: Tuple[Family, ...] = (
    Family("workbook", "curve", "-CITIVELO", "1-min USD from the saved CVTSHIST workbook"),
    Family("eod", "curve", "-CITIVELOEXCEL", "one EOD curve per business day"),
    Family("minute", "curve", "-CITIVELOEXCELMIN", "1-min curves from live Excel"),
    Family("stream", "curve", "-CITIVELOSTREAM", "CVSTREAM daemon ticks"),
    Family("cube", "cube", "-SWAPTIONVOL-CITIVELOEXCEL", "swaption vol surfaces"),
)
FAMILY_BY_NAME = {f.name: f for f in FAMILIES}


def family_for(asset: str) -> Optional[Family]:
    for fam in FAMILIES:
        if fam.matches(asset):
            return fam
    return None


# ── engine ────────────────────────────────────────────────────────────────


def build_engine(workers: int):
    """Our own engine, sized for this process's thread pool.

    Deliberately not ``Caching.supabase_engine.get_engine()``: that is a
    process-wide singleton sized from ``ARBS_SUPABASE_WRITE_WORKERS`` and gated
    by a module global evaluated at import, so a CLI flag cannot influence
    either. ``get_database_url()`` is reused because it is the one place the
    URL-resolution precedence lives.
    """
    from sqlalchemy import create_engine

    from Caching.supabase_engine import get_database_url

    url = get_database_url()
    return create_engine(
        url,
        pool_size=max(1, workers),
        max_overflow=2,
        pool_timeout=60,
        pool_recycle=1800,
        pool_pre_ping=True,
    )


def redacted_target() -> str:
    from Caching.supabase_engine import get_database_url

    return re.sub(r"//[^@]+@", "//<redacted>@", get_database_url() or "")


# ── discovery ─────────────────────────────────────────────────────────────


def curve_store_base() -> pathlib.Path:
    from Caching.curve_store import CurveStore

    return pathlib.Path(CurveStore._default_base_dir())


def cube_store_base() -> pathlib.Path:
    from Caching.swaption_cube_store import SwaptionCubeStore

    return pathlib.Path(SwaptionCubeStore._default_base_dir())


def discover_assets(kind: str, base: pathlib.Path) -> List[str]:
    root = base / ("raw" if kind == "curve" else "vol_raw")
    if not root.exists():
        return []
    out = []
    for entry in sorted(root.iterdir()):
        if entry.is_dir() and entry.name.startswith("asset="):
            out.append(entry.name[len("asset=") :])
    return out


def select_assets(
    families: Sequence[str], only: Sequence[str], curve_base: pathlib.Path, cube_base: pathlib.Path
) -> List[Tuple[Family, str]]:
    wanted = {f for f in families} if families else set(FAMILY_BY_NAME)
    found: List[Tuple[Family, str]] = []
    for kind, base in (("curve", curve_base), ("cube", cube_base)):
        for asset in discover_assets(kind, base):
            fam = family_for(asset)
            if fam is None or fam.name not in wanted:
                continue
            if only and asset not in only:
                continue
            found.append((fam, asset))
    return found


def make_sync(fam: Family, engine, curve_base: pathlib.Path, cube_base: pathlib.Path):
    if fam.kind == "curve":
        from Caching.supabase_curve_blocks import CurveBlobSync

        return CurveBlobSync(base_dir=curve_base, engine=engine, kind="raw")
    from Caching.supabase_swaption_cube_sync import SupabaseSwaptionCubeSync

    return SupabaseSwaptionCubeSync(base_dir=cube_base, engine=engine)


# ── planning ──────────────────────────────────────────────────────────────


@dataclasses.dataclass
class AssetPlan:
    family: str
    asset: str
    local_days: int
    remote_days: int
    to_push: List[datetime.date]
    differing: List[datetime.date]
    remote_only: List[datetime.date]
    push_bytes: int
    remote_bytes: int
    unreadable: List[str] = dataclasses.field(default_factory=list)

    @property
    def n_to_push(self) -> int:
        return len(self.to_push)


def plan_asset(
    sync,
    fam: Family,
    asset: str,
    *,
    start: Optional[datetime.date],
    end: Optional[datetime.date],
    rewrite: bool,
) -> AssetPlan:
    """What a push would do, without moving a byte of payload."""
    from Caching.supabase_blob_blocks import MultiFilePartition

    local = sync.local_dates(asset, start, end)
    remote = sync.remote_manifest(asset, start, end)

    to_push: List[datetime.date] = []
    differing: List[datetime.date] = []
    push_bytes = 0
    unreadable: List[str] = []

    for day in local:
        try:
            local_sha = sync.local_sha(asset, day)
        except MultiFilePartition as exc:  # pragma: no cover - defensive
            unreadable.append(f"{day}: {exc}")
            continue
        if local_sha is None:
            # more than one parquet in the partition, or an unreadable one
            unreadable.append(f"{day}: partition is not a single content-addressed file")
            continue
        block = remote.get(day)
        if block is not None and block.sha256 == local_sha:
            continue
        if block is not None:
            differing.append(day)
            if not rewrite:
                continue
        to_push.append(day)
        try:
            push_bytes += sync.partition_dir(asset, day).joinpath(f"{local_sha}.parquet").stat().st_size
        except OSError:
            pass

    return AssetPlan(
        family=fam.name,
        asset=asset,
        local_days=len(local),
        remote_days=len(remote),
        to_push=to_push,
        differing=differing,
        remote_only=sorted(set(remote) - set(local)),
        push_bytes=push_bytes,
        remote_bytes=sum(b.nbytes for b in remote.values()),
        unreadable=unreadable,
    )


def human(nbytes: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(nbytes) < 1024 or unit == "TB":
            return f"{nbytes:,.1f} {unit}"
        nbytes /= 1024.0
    return f"{nbytes} B"


def print_plan(plans: Sequence[AssetPlan]) -> None:
    header = (
        f"{'family':<9}{'asset':<40}{'local':>7}{'remote':>8}{'push':>7}"
        f"{'differ':>8}{'rem-only':>10}{'bytes':>13}"
    )
    print(header)
    print("-" * len(header))
    for p in sorted(plans, key=lambda p: (p.family, p.asset)):
        print(
            f"{p.family:<9}{p.asset:<40}{p.local_days:>7}{p.remote_days:>8}{p.n_to_push:>7}"
            f"{len(p.differing):>8}{len(p.remote_only):>10}{human(p.push_bytes):>13}"
        )
    print("-" * len(header))
    total_days = sum(p.n_to_push for p in plans)
    total_bytes = sum(p.push_bytes for p in plans)
    print(
        f"{'TOTAL':<9}{'':<40}"
        f"{sum(p.local_days for p in plans):>7}{sum(p.remote_days for p in plans):>8}"
        f"{total_days:>7}{sum(len(p.differing) for p in plans):>8}"
        f"{sum(len(p.remote_only) for p in plans):>10}{human(total_bytes):>13}"
    )
    problems = [(p.asset, u) for p in plans for u in p.unreadable]
    if problems:
        print(f"\n{len(problems)} partition(s) cannot be pushed as one blob:")
        for asset, note in problems[:20]:
            print(f"  {asset}  {note}")
        if len(problems) > 20:
            print(f"  ... and {len(problems) - 20} more")


# ── perf log ──────────────────────────────────────────────────────────────


class PerfLog:
    def __init__(self, path: Optional[pathlib.Path]):
        self._path = path
        self._lock = threading.Lock()
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, event: dict) -> None:
        if self._path is None:
            return
        line = json.dumps({**event, "ts": datetime.datetime.now().isoformat(timespec="seconds")})
        with self._lock:
            with open(self._path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")


# ── push ──────────────────────────────────────────────────────────────────


@dataclasses.dataclass
class PushTotals:
    pushed: int = 0
    rewritten: int = 0
    identical: int = 0
    failed: int = 0
    nbytes: int = 0

    def record(self, status: str, nbytes: int) -> None:
        # An unrecognised status used to create a NEW attribute and vanish from
        # every total, so a whole class of outcome could go unreported while the
        # run said "0 failed".
        if not hasattr(self, status):
            raise ValueError(
                f"unknown push status {status!r}; expected one of "
                "pushed/rewritten/identical/failed"
            )
        setattr(self, status, getattr(self, status) + 1)
        self.nbytes += nbytes


def push_asset(
    sync,
    fam: Family,
    asset: str,
    plan: AssetPlan,
    *,
    rewrite: bool,
    workers: int,
    perf: PerfLog,
    totals: PushTotals,
    lock: threading.Lock,
    started: float,
    total_days: int,
    counter: Dict[str, int],
) -> None:
    if not plan.to_push:
        return
    manifest = sync.remote_manifest(asset, plan.to_push[0], plan.to_push[-1])

    def one(day: datetime.date) -> None:
        t0 = time.perf_counter()
        try:
            out = sync.push_day(asset, day, rewrite=rewrite, known_remote=manifest.get(day))
            status, nbytes = out.status, out.nbytes
        except Exception as exc:  # noqa: BLE001 - one bad day must not stop a backfill
            status, nbytes = "failed", 0
            LOGGER.warning("%s %s FAILED: %s: %s", asset, day, type(exc).__name__, exc)
            perf.write(
                {"event": "push_day", "asset": asset, "day": day.isoformat(),
                 "status": "failed", "error": f"{type(exc).__name__}: {exc}"}
            )
        elapsed = time.perf_counter() - t0
        with lock:
            totals.record(status if status != "missing_local" else "failed", nbytes)
            counter["done"] += 1
            done = counter["done"]
        if status != "failed":
            perf.write(
                {"event": "push_day", "asset": asset, "day": day.isoformat(),
                 "status": status, "bytes": nbytes, "seconds": round(elapsed, 3)}
            )
        if done % 50 == 0 or done == total_days:
            wall = time.time() - started
            rate = done / wall if wall > 0 else 0.0
            eta = (total_days - done) / rate if rate > 0 else 0.0
            LOGGER.info(
                "%d/%d days (%.1f%%) %s pushed=%d rewritten=%d identical=%d failed=%d "
                "%.1f d/s elapsed=%.1fm eta=%.1fm",
                done, total_days, 100.0 * done / max(total_days, 1), human(totals.nbytes),
                totals.pushed, totals.rewritten, totals.identical, totals.failed,
                rate, wall / 60.0, eta / 60.0,
            )

    if workers <= 1:
        for day in plan.to_push:
            one(day)
        return
    with cf.ThreadPoolExecutor(max_workers=workers, thread_name_prefix="l2push") as pool:
        list(pool.map(one, plan.to_push))


# ── snapshot rows ─────────────────────────────────────────────────────────


def push_snapshot_rows(
    engine,
    curve_base: pathlib.Path,
    asset: str,
    days: Sequence[datetime.date],
    *,
    batch_days: int = 100,
) -> int:
    """Write the tagged ``arbs_curve_snapshots_v1`` rows for a set of days.

    Uses the same ``curve_tag_config.get_tags`` gate the existing
    ``_push_tagged_snapshots`` uses, so the Citi assets end up tagged the way
    ``USD-SOFR-1D-CITIVELO``'s 931 existing rows already are, rather than as a
    second, untagged convention. ``get_tags`` is timezone-agnostic (OPEN when
    ``session_minute == 0``, EOD on the last row of the day), so it is correct
    for the non-US currencies whose ``session_minute`` is minute-of-day in their
    OWN zone.
    """
    import pandas as pd
    import pyarrow.parquet as pq
    from sqlalchemy import text

    from Caching.curve_tag_config import get_tags
    from Caching.db_session import labelled_transaction, make_label
    from Caching.supabase_curve_blocks import CurveBlobSync

    """
    ``batch_days`` groups days into ONE transaction. Measured on the first eod
    run: 13,480 days took 27.1 minutes of which the blob push was ~3 - the rest
    was this function at one transaction (one pooler round trip) per day. The
    rows themselves are ~1 KB each and there is at most one tagged row per EOD
    day, so the batching is pure round-trip elimination.
    """
    sync = CurveBlobSync(base_dir=curve_base, engine=engine, kind="raw")
    written = 0
    pending: List[dict] = []
    sql = text(
        """
        INSERT INTO arbs_curve_snapshots_v1
            (curve_name, timestamp_utc, trading_date, session_minute, tags, cfg_hash,
             reference_key, interpolation, source_variant, node_dates, discount_factors)
        VALUES
            (:curve_name, :timestamp_utc, :trading_date, :session_minute, :tags, :cfg_hash,
             :reference_key, :interpolation, :source_variant, :node_dates, :discount_factors)
        ON CONFLICT (curve_name, timestamp_utc) DO UPDATE SET
            tags = EXCLUDED.tags,
            trading_date = EXCLUDED.trading_date,
            session_minute = EXCLUDED.session_minute,
            reference_key = EXCLUDED.reference_key,
            interpolation = EXCLUDED.interpolation,
            source_variant = EXCLUDED.source_variant,
            node_dates = EXCLUDED.node_dates,
            discount_factors = EXCLUDED.discount_factors
        """
    )
    for day in days:
        local = sync.local_partition(asset, day)
        if local is None:
            continue
        import io

        frame = pq.read_table(io.BytesIO(local.payload)).to_pandas()
        if frame.empty:
            continue
        max_minute = frame["session_minute"].max()
        # Only two kinds of row can be tagged with an empty event calendar:
        # session_minute == 0 (OPEN) and the last row of the day (EOD). Narrowing
        # to those before iterating is the difference between ~2 rows and ~1,100
        # per day on a minute asset — 3.1M pandas row objects across the minute
        # families, to find about 5,700 tagged rows. get_tags is still the
        # authority on what the tags ARE; this only decides who to ask.
        # NOTE: an event calendar would make an interior minute taggable too, so
        # this narrowing is only valid while the calendar is empty.
        candidates = frame[
            (frame["session_minute"] == 0) | (frame["session_minute"] == max_minute)
        ]
        rows = []
        for _, row in candidates.iterrows():
            tags = get_tags(
                session_minute=int(row["session_minute"]),
                trading_date=day,
                is_last_of_day=bool(row["session_minute"] == max_minute),
                event_calendar={},
            )
            if not tags:
                continue
            rows.append(
                {
                    "curve_name": asset,
                    "timestamp_utc": pd.Timestamp(row["timestamp_utc"]).to_pydatetime(),
                    "trading_date": day,
                    "session_minute": int(row["session_minute"]),
                    "tags": tags,
                    "cfg_hash": str(row.get("cfg_hash") or ""),
                    "reference_key": str(row.get("reference_key") or ""),
                    "interpolation": str(row.get("interpolation") or ""),
                    "source_variant": str(row.get("source_variant") or ""),
                    "node_dates": [
                        d.date() if hasattr(d, "date") else d for d in row["node_dates"]
                    ],
                    "discount_factors": [float(v) for v in row["discount_factors"]],
                }
            )
        pending.extend(rows)
        if len(pending) >= batch_days:
            written += _flush_snapshot_rows(engine, sql, asset, pending)
            pending = []

    written += _flush_snapshot_rows(engine, sql, asset, pending)
    return written


def _flush_snapshot_rows(engine, sql, asset: str, rows: List[dict]) -> int:
    if not rows:
        return 0
    with labelled_transaction(
        engine, label=make_label("curve_l2_rows", detail=asset[:20]), statement_timeout_ms=0
    ) as conn:
        for params in rows:
            conn.execute(sql, params)
    return len(rows)


# ── verify ────────────────────────────────────────────────────────────────


def verify_asset(sync, asset: str, days: Sequence[datetime.date]) -> Dict[str, Any]:
    """Pull each day's payload back and compare it to the local bytes.

    Three independent checks per day, because a round trip that only compares a
    blob to itself is a tautology:

    1. the stored payload hashes to the stored ``sha256`` column;
    2. it equals the local file byte for byte;
    3. it parses as parquet and has the row count the row claims.

    Any of them failing is reported per day rather than raised, so one bad day
    does not hide the rest.
    """
    import io

    import pyarrow.parquet as pq
    from sqlalchemy import text

    from Caching.supabase_blob_blocks import sha256_of

    bad: List[Dict[str, Any]] = []
    checked = 0
    nbytes = 0
    for day in days:
        # A damaged or multi-file LOCAL partition is a finding about that day, not
        # a reason to abandon the asset — otherwise one bad file hides every other
        # day's result, which is the opposite of what a verifier is for.
        local = None
        try:
            local = sync.local_partition(asset, day)
        except Exception as exc:  # noqa: BLE001
            bad.append(
                {"day": day.isoformat(), "problem": f"local partition unusable: {exc}"}
            )
        with sync.engine.connect() as conn:
            row = conn.execute(
                text(
                    f"SELECT payload, sha256, row_count FROM {sync.table.name} "
                    f"WHERE trading_date = :d AND {sync.table.key_column} = :k"
                ),
                {"d": day, "k": asset},
            ).fetchone()
        if row is None:
            bad.append({"day": day.isoformat(), "problem": "absent from L2"})
            continue
        payload = bytes(row.payload)
        checked += 1
        nbytes += len(payload)
        actual = sha256_of(payload)
        if actual != str(row.sha256):
            bad.append(
                {"day": day.isoformat(), "problem": "payload does not hash to its sha column",
                 "stored": str(row.sha256)[:12], "actual": actual[:12]}
            )
            continue
        if local is not None and payload != local.payload:
            bad.append(
                {"day": day.isoformat(), "problem": "L2 bytes differ from the local file",
                 "local_sha": local.sha256[:12], "remote_sha": actual[:12]}
            )
            continue
        try:
            n = pq.read_table(io.BytesIO(payload)).num_rows
        except Exception as exc:  # noqa: BLE001
            bad.append({"day": day.isoformat(), "problem": f"unreadable parquet: {exc}"})
            continue
        if int(n) != int(row.row_count):
            bad.append(
                {"day": day.isoformat(), "problem": "row_count column disagrees with the payload",
                 "column": int(row.row_count), "payload": int(n)}
            )
    return {"asset": asset, "checked": checked, "bytes": nbytes, "bad": bad}


# ── commands ──────────────────────────────────────────────────────────────


def _dates(args) -> Tuple[Optional[datetime.date], Optional[datetime.date]]:
    start = datetime.date.fromisoformat(args.start) if args.start else None
    end = datetime.date.fromisoformat(args.end) if args.end else None
    return start, end


def _selected(args, engine):
    curve_base = pathlib.Path(args.curve_base) if args.curve_base else curve_store_base()
    cube_base = pathlib.Path(args.cube_base) if args.cube_base else cube_store_base()
    only = [a.strip() for a in (args.assets or "").split(",") if a.strip()]
    pairs = select_assets(args.families or [], only, curve_base, cube_base)
    return curve_base, cube_base, pairs


def cmd_plan(args) -> int:
    engine = build_engine(1)
    try:
        curve_base, cube_base, pairs = _selected(args, engine)
        start, end = _dates(args)
        LOGGER.info("target %s", redacted_target())
        LOGGER.info("curve store %s", curve_base)
        LOGGER.info("cube store  %s", cube_base)
        plans = []
        for fam, asset in pairs:
            sync = make_sync(fam, engine, curve_base, cube_base)
            plans.append(plan_asset(sync, fam, asset, start=start, end=end, rewrite=args.rewrite))
        print_plan(plans)
        if args.json:
            pathlib.Path(args.json).write_text(
                json.dumps(
                    [
                        {
                            **dataclasses.asdict(p),
                            "to_push": [d.isoformat() for d in p.to_push],
                            "differing": [d.isoformat() for d in p.differing],
                            "remote_only": [d.isoformat() for d in p.remote_only],
                        }
                        for p in plans
                    ],
                    indent=2,
                ),
                encoding="utf-8",
            )
            LOGGER.info("plan written to %s", args.json)
        return 0
    finally:
        engine.dispose()


def cmd_push(args) -> int:
    engine = build_engine(args.workers)
    perf = PerfLog(pathlib.Path(args.perf_log) if args.perf_log else None)
    try:
        curve_base, cube_base, pairs = _selected(args, engine)
        start, end = _dates(args)
        plans = []
        for fam, asset in pairs:
            sync = make_sync(fam, engine, curve_base, cube_base)
            plans.append(
                (fam, asset, sync, plan_asset(sync, fam, asset, start=start, end=end, rewrite=args.rewrite))
            )
        if args.limit is not None:
            # Recompute the byte total from the truncated list. Truncating without
            # it makes the confirmation banner quote the WHOLE asset's size for a
            # five-day smoke test, which is the one number the operator is meant
            # to read before typing --yes.
            for _, asset, sync, p in plans:
                p.to_push = p.to_push[: args.limit]
                p.push_bytes = 0
                for day in p.to_push:
                    sha = sync.local_sha(asset, day)
                    if sha is None:
                        continue
                    try:
                        p.push_bytes += (
                            sync.partition_dir(asset, day).joinpath(f"{sha}.parquet").stat().st_size
                        )
                    except OSError:
                        pass

        total_days = sum(len(p.to_push) for *_, p in plans)
        total_bytes = sum(p.push_bytes for *_, p in plans)
        print_plan([p for *_, p in plans])
        print()
        LOGGER.warning(
            "ABOUT TO WRITE %d day(s) / %s to %s",
            total_days, human(total_bytes), redacted_target(),
        )
        if total_days == 0:
            LOGGER.info("nothing to do.")
            return 0
        if not args.yes:
            LOGGER.error(
                "refusing without --yes. This resolves hard-coded PRODUCTION credentials "
                "when nothing is configured, so the confirmation is not a formality."
            )
            return 2

        started = time.time()
        totals = PushTotals()
        lock = threading.Lock()
        counter = {"done": 0}
        perf.write(
            {"event": "push_start", "days": total_days, "bytes": total_bytes,
             "target": redacted_target(), "workers": args.workers, "rewrite": bool(args.rewrite)}
        )
        for fam, asset, sync, plan in plans:
            if not plan.to_push:
                continue
            LOGGER.info(
                "=== %s / %s: %d day(s), %s ===",
                fam.name, asset, len(plan.to_push), human(plan.push_bytes),
            )
            push_asset(
                sync, fam, asset, plan, rewrite=args.rewrite, workers=args.workers,
                perf=perf, totals=totals, lock=lock, started=started,
                total_days=total_days, counter=counter,
            )
            if args.snapshot_rows != "off" and fam.kind == "curve":
                n = push_snapshot_rows(engine, curve_base, asset, plan.to_push)
                LOGGER.info("%s: %d tagged snapshot row(s)", asset, n)
                perf.write({"event": "snapshot_rows", "asset": asset, "rows": n})

        wall = time.time() - started
        LOGGER.warning(
            "DONE in %.1f min: pushed=%d rewritten=%d identical=%d failed=%d, %s",
            wall / 60.0, totals.pushed, totals.rewritten, totals.identical,
            totals.failed, human(totals.nbytes),
        )
        perf.write(
            {"event": "push_done", "seconds": round(wall, 1), "pushed": totals.pushed,
             "rewritten": totals.rewritten, "identical": totals.identical,
             "failed": totals.failed, "bytes": totals.nbytes}
        )
        return 1 if totals.failed else 0
    finally:
        engine.dispose()


def cmd_verify(args) -> int:
    engine = build_engine(1)
    try:
        curve_base, cube_base, pairs = _selected(args, engine)
        start, end = _dates(args)
        all_bad = 0
        checked = 0
        nbytes = 0
        for fam, asset in pairs:
            sync = make_sync(fam, engine, curve_base, cube_base)
            days = sorted(sync.remote_manifest(asset, start, end))
            if args.sample and len(days) > args.sample:
                step = max(1, len(days) // args.sample)
                days = days[::step][: args.sample]
            if not days:
                LOGGER.info("%-40s no remote days", asset)
                continue
            report = verify_asset(sync, asset, days)
            checked += report["checked"]
            nbytes += report["bytes"]
            all_bad += len(report["bad"])
            status = "OK" if not report["bad"] else f"{len(report['bad'])} BAD"
            LOGGER.info(
                "%-40s %4d day(s) %12s  %s",
                asset, report["checked"], human(report["bytes"]), status,
            )
            for item in report["bad"][:10]:
                LOGGER.error("   %s", item)
        LOGGER.warning(
            "verify: %d day(s) / %s checked, %d problem(s)", checked, human(nbytes), all_bad
        )
        return 1 if all_bad else 0
    finally:
        engine.dispose()


def cmd_status(args) -> int:
    engine = build_engine(1)
    try:
        curve_base, cube_base, pairs = _selected(args, engine)
        rows = []
        for fam, asset in pairs:
            sync = make_sync(fam, engine, curve_base, cube_base)
            rows.append((fam.name, sync.coverage(asset)))
        header = f"{'family':<9}{'asset':<40}{'local':>7}{'remote':>8}{'L-only':>8}{'R-only':>8}{'differ':>8}{'remote bytes':>15}"
        print(header)
        print("-" * len(header))
        for fam_name, cov in sorted(rows, key=lambda r: (r[0], r[1]["key"])):
            print(
                f"{fam_name:<9}{cov['key']:<40}{cov['local_days']:>7}{cov['remote_days']:>8}"
                f"{len(cov['local_only']):>8}{len(cov['remote_only']):>8}{len(cov['differing']):>8}"
                f"{human(cov['remote_bytes']):>15}"
            )
        print("-" * len(header))
        print(
            f"{'TOTAL':<9}{'':<40}"
            f"{sum(c['local_days'] for _, c in rows):>7}"
            f"{sum(c['remote_days'] for _, c in rows):>8}"
            f"{sum(len(c['local_only']) for _, c in rows):>8}"
            f"{sum(len(c['remote_only']) for _, c in rows):>8}"
            f"{sum(len(c['differing']) for _, c in rows):>8}"
            f"{human(sum(c['remote_bytes'] for _, c in rows)):>15}"
        )
        return 0
    finally:
        engine.dispose()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__ or "", formatter_class=argparse.RawDescriptionHelpFormatter
    )

    def common(sub):
        sub.add_argument(
            "--families", action="append", choices=sorted(FAMILY_BY_NAME),
            help="repeatable; default is every family",
        )
        sub.add_argument("--assets", default="", help="comma-separated exact asset names")
        sub.add_argument("--start", default=None, help="YYYY-MM-DD inclusive")
        sub.add_argument("--end", default=None, help="YYYY-MM-DD inclusive")
        sub.add_argument("--curve-base", default=None)
        sub.add_argument("--cube-base", default=None)
        sub.add_argument("--verbose", action="store_true")

    sub = p.add_subparsers(dest="command", required=True)

    a = sub.add_parser("plan", help="what a push would do; moves no payload")
    common(a)
    a.add_argument("--rewrite", action="store_true", help="count days whose content differs")
    a.add_argument("--json", default=None, help="also write the plan to this path")
    a.set_defaults(func=cmd_plan)

    b = sub.add_parser("push", help="push local partitions to L2")
    common(b)
    b.add_argument("--yes", action="store_true", help="required; this writes to production")
    b.add_argument("--rewrite", action="store_true", help="replace days whose content differs")
    b.add_argument(
        "--limit", type=int, default=None,
        help="cap days per asset (smoke test). 0 means push NOTHING, not 'no cap'.",
    )
    b.add_argument(
        "--workers", type=int, default=4,
        help="threads sharing ONE engine. The pool is sized to this, so total "
             "connections are workers+2 however many days are pushed.",
    )
    b.add_argument(
        "--snapshot-rows", choices=["auto", "off"], default="auto",
        help="also write tagged arbs_curve_snapshots_v1 rows for curve assets",
    )
    b.add_argument("--perf-log", default=None, help="JSONL event log path")
    b.set_defaults(func=cmd_push)

    c = sub.add_parser("verify", help="pull each remote day back and compare it")
    common(c)
    c.add_argument("--sample", type=int, default=None, help="check ~N evenly spaced days per asset")
    c.set_defaults(func=cmd_verify)

    d = sub.add_parser("status", help="local vs remote coverage")
    common(d)
    d.set_defaults(func=cmd_status)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
