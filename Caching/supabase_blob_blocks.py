r"""One partition, one row, one sha: the blob-block L2 pattern, written once.

This repo already has three copies of it - ``supabase_curve_sync`` (which
copy-pastes its own pair for ``raw`` and ``analytics``), ``supabase_ustf_sync``
(which at least parameterises by ``kind``) and
``supabase_computed_timeseries_sync``. The house precedent is genuinely
clone-don't-reuse - ``USTFutureStore`` is a near-line-for-line copy of
``CurveStore`` - so a fourth copy would not have been a code smell on its own.
The reason not to write one is that the three existing copies **disagree**, and
each disagreement is a defect rather than a preference:

* ``supabase_curve_sync.pull_day`` writes with ``dest.write_bytes(...)``, not
  atomically. An interrupted pull leaves a truncated file named after the sha of
  the whole one. ``supabase_ustf_sync`` uses ``_atomic_write_bytes``.
* **Nothing verifies the payload against the stored sha on the way in.** Both
  name the file ``f"{row.sha256}.parquet"`` and trust it. A short read, a
  corrupted TOAST chunk or a mismatched row lands under a filename that lies,
  and every later reader believes the name.
* ``prefetch_range`` selects ``payload`` for the **whole range** and then throws
  away the days it finds locally. On a 400 MB asset that is 400 MB over the
  pooler to discover that nothing was needed.
* ``_local_parquet_bytes`` reads ``pq_files[0]`` (curve) or ``pq_files[-1]``
  (ustf) when a partition holds several files. ``CurveStore.read_raw_day``
  *concats* them, so the blob and the local read can legitimately disagree -
  silently, and in the direction of losing rows. There are multi-file partitions
  on this machine right now (``USD-OIS-Q12xM12STIRT-SERFFX-MIX23``: 2,613 files
  across 1,382 days).

So the new tier gets one implementation with all four fixed, and the three
existing ones are left alone: they are load-bearing for the live curve path and
rewriting them is a separate change with a separate blast radius. The defects
above are reported rather than fixed here.

Restatement, in both directions
-------------------------------
``SwaptionCubeStore.write_day`` raises ``FileExistsError`` when a day is already
stored with different content, because a cube partition is one surface and
content addressing means a restatement lands under a *different* sha rather than
replacing - so "pick a file" becomes "pick at random". That property has to
survive the round trip, which means it is checked on the way out as well as the
way in:

* :meth:`BlobBlockSync.push_day` reads the remote sha first. Equal -> skip.
  Different -> :class:`BlobRestatement` unless ``rewrite=True``.
* :meth:`BlobBlockSync.pull_day` compares against what is already local.
  Different -> :class:`BlobRestatement` unless ``overwrite=True``.

An upsert that just overwrote would make L2 the one place a restatement is
applied quietly.

No DDL on the read path
-----------------------
``ensure_schema`` is what makes merely *reading* a cache able to run
``ALTER TABLE`` against a live production table. Reads here do a cheap
``information_schema`` existence check instead and answer "no data" when the
table is absent. Only the write path may create anything.
"""

from __future__ import annotations

import dataclasses
import datetime
import hashlib
import io
import logging
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

import pyarrow.parquet as pq
from sqlalchemy import Engine, text

from Caching.db_session import labelled_transaction, make_label
from Caching.timeseries_cache import _atomic_write_bytes

logger = logging.getLogger(__name__)

__all__ = [
    "BlobBlockTable",
    "BlobBlockSync",
    "LocalPartition",
    "RemoteBlock",
    "PushOutcome",
    "BlobIntegrityError",
    "BlobRestatement",
    "MultiFilePartition",
    "DATA_FORMAT",
]

DATA_FORMAT = "parquet_zstd"

_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")


class BlobIntegrityError(RuntimeError):
    """A stored payload does not hash to its stored sha256."""


class BlobRestatement(RuntimeError):
    """The same key holds different content on the other side."""


class MultiFilePartition(RuntimeError):
    """A local partition holds several parquet files; one blob cannot represent it."""


@dataclasses.dataclass(frozen=True)
class BlobBlockTable:
    """Identifiers for one blob-block table. Validated, never interpolated blind."""

    name: str
    key_column: str

    def __post_init__(self) -> None:
        for field, value in (("name", self.name), ("key_column", self.key_column)):
            if not _IDENT.match(value or ""):
                raise ValueError(
                    f"BlobBlockTable.{field}={value!r} is not a bare lowercase SQL "
                    "identifier. These go into f-strings, so they are validated here "
                    "rather than trusted."
                )


@dataclasses.dataclass(frozen=True)
class LocalPartition:
    trading_date: datetime.date
    payload: bytes
    row_count: int
    sha256: str
    path: Path

    @property
    def nbytes(self) -> int:
        return len(self.payload)


@dataclasses.dataclass(frozen=True)
class RemoteBlock:
    trading_date: datetime.date
    sha256: str
    row_count: int
    nbytes: int


@dataclasses.dataclass(frozen=True)
class PushOutcome:
    trading_date: datetime.date
    status: str  # "pushed" | "rewritten" | "identical" | "missing_local"
    nbytes: int = 0
    row_count: int = 0

    @property
    def wrote(self) -> bool:
        return self.status in ("pushed", "rewritten")


def sha256_of(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class _Unset:
    """Sentinel: ``known_remote=None`` means 'looked it up, the day is absent'."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<unset>"


_UNSET = _Unset()


class BlobBlockSync:
    """Push/pull whole-partition parquet blobs between local disk and Postgres.

    Subclasses supply :meth:`partition_dir` and :meth:`asset_root`; everything
    else is shared. ``engine`` is passed in rather than resolved from module
    globals on purpose - ``Caching.supabase_engine`` evaluates its state at
    import, so a caller that resolved an engine and a caller that consulted the
    global can disagree about whether L2 is on.
    """

    #: Refuse rather than guess when a partition holds more than one file.
    #: ``CurveStore`` concats them on read, so silently picking one loses rows.
    multi_file_policy = "refuse"

    def __init__(
        self,
        *,
        table: BlobBlockTable,
        base_dir: Path,
        engine: Optional[Engine],
        label_component: str = "blob_blocks",
    ) -> None:
        self.table = table
        self._base_dir = Path(base_dir)
        self._engine = engine
        self._label_component = label_component

    # ── subclass hooks ────────────────────────────────────────────────

    def partition_dir(self, key: str, trading_date: datetime.date) -> Path:
        raise NotImplementedError

    def asset_root(self, key: str) -> Path:
        raise NotImplementedError

    # ── local side ────────────────────────────────────────────────────

    @property
    def base_dir(self) -> Path:
        return self._base_dir

    @property
    def engine(self) -> Optional[Engine]:
        return self._engine

    def local_partition(self, key: str, trading_date: datetime.date) -> Optional[LocalPartition]:
        """The one parquet file for a partition, hashed and row-counted.

        ``None`` when the partition is absent or empty. Raises
        :class:`MultiFilePartition` when it holds several files rather than
        picking one - see the module docstring.
        """
        part_dir = self.partition_dir(key, trading_date)
        if not part_dir.exists():
            return None
        files = sorted(part_dir.glob("*.parquet"))
        if not files:
            return None
        if len(files) > 1:
            if self.multi_file_policy != "refuse":
                raise ValueError(f"unknown multi_file_policy {self.multi_file_policy!r}")
            raise MultiFilePartition(
                f"{key} {trading_date.isoformat()} holds {len(files)} parquet files "
                f"({', '.join(f.name[:12] for f in files[:3])}...). One blob row cannot "
                f"represent them, and pushing just one would silently drop the rest — a "
                f"local read concatenates them. Consolidate the partition first."
            )
        payload = files[0].read_bytes()
        row_count = int(pq.read_table(io.BytesIO(payload)).num_rows)
        return LocalPartition(
            trading_date=trading_date,
            payload=payload,
            row_count=row_count,
            sha256=sha256_of(payload),
            path=files[0],
        )

    def local_dates(
        self,
        key: str,
        start: Optional[datetime.date] = None,
        end: Optional[datetime.date] = None,
    ) -> List[datetime.date]:
        root = self.asset_root(key)
        if not root.exists():
            return []
        out: List[datetime.date] = []
        for entry in root.iterdir():
            if not entry.name.startswith("date=") or not entry.is_dir():
                continue
            try:
                day = datetime.date.fromisoformat(entry.name[5:])
            except ValueError:
                continue
            if start is not None and day < start:
                continue
            if end is not None and day > end:
                continue
            if any(entry.glob("*.parquet")):
                out.append(day)
        return sorted(out)

    def local_sha(self, key: str, trading_date: datetime.date) -> Optional[str]:
        """The sha of a local partition without reading it, when possible.

        Content addressing means the filename *is* the sha, so a coverage diff
        over thousands of days costs a directory listing rather than a gigabyte
        of reads. Falls back to hashing when the name is not a sha (a file
        written by something that did not content-address).
        """
        part_dir = self.partition_dir(key, trading_date)
        if not part_dir.exists():
            return None
        files = sorted(part_dir.glob("*.parquet"))
        if len(files) != 1:
            return None
        stem = files[0].stem
        if len(stem) == 64 and all(c in "0123456789abcdef" for c in stem):
            return stem
        return sha256_of(files[0].read_bytes())

    # ── schema ────────────────────────────────────────────────────────

    def _ensure_schema(self) -> bool:
        """Write path only. Creates the table if it is missing."""
        if self._engine is None:
            return False
        from Caching.supabase_schema import ensure_schema

        return bool(ensure_schema(self._engine))

    def table_exists(self) -> bool:
        """Read path. Never runs DDL."""
        if self._engine is None:
            return False
        try:
            with self._engine.connect() as conn:
                row = conn.execute(
                    text(
                        "SELECT 1 FROM information_schema.tables "
                        "WHERE table_schema = 'public' AND table_name = :t"
                    ),
                    {"t": self.table.name},
                ).fetchone()
            return row is not None
        except Exception as exc:  # noqa: BLE001 - a cold L2 must degrade, not raise
            logger.debug("%s: existence check failed (%s)", self.table.name, exc)
            return False

    # ── remote side ───────────────────────────────────────────────────

    def remote_manifest(
        self,
        key: str,
        start: Optional[datetime.date] = None,
        end: Optional[datetime.date] = None,
    ) -> Dict[datetime.date, RemoteBlock]:
        """``{date: RemoteBlock}`` for a key. **Does not select the payload.**

        This is the resume primitive: a plan or a re-run needs shas and sizes,
        not a gigabyte of blobs. ``length(payload)`` is computed server-side.
        """
        if self._engine is None or not self.table_exists():
            return {}
        clauses = [f"{self.table.key_column} = :key"]
        params: dict = {"key": key}
        if start is not None:
            clauses.append("trading_date >= :start")
            params["start"] = start
        if end is not None:
            clauses.append("trading_date <= :end")
            params["end"] = end
        sql = (
            f"SELECT trading_date, sha256, row_count, length(payload) AS nbytes "
            f"FROM {self.table.name} WHERE {' AND '.join(clauses)} ORDER BY trading_date"
        )
        with self._engine.connect() as conn:
            rows = conn.execute(text(sql), params).fetchall()
        return {
            _as_date(r.trading_date): RemoteBlock(
                trading_date=_as_date(r.trading_date),
                sha256=str(r.sha256),
                row_count=int(r.row_count),
                nbytes=int(r.nbytes),
            )
            for r in rows
        }

    def remote_keys(self) -> List[str]:
        if self._engine is None or not self.table_exists():
            return []
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(f"SELECT DISTINCT {self.table.key_column} AS k FROM {self.table.name} ORDER BY 1")
            ).fetchall()
        return [str(r.k) for r in rows]

    # ── push ──────────────────────────────────────────────────────────

    def push_day(
        self,
        key: str,
        trading_date: datetime.date,
        *,
        rewrite: bool = False,
        known_remote=_UNSET,
        statement_timeout_ms: int = 0,
    ) -> PushOutcome:
        """Upsert one partition. Returns what it did rather than a bare bool.

        ``known_remote`` lets a batch pass the manifest row it already has so a
        thousand-day push does not make a thousand extra round trips. It takes a
        sentinel default rather than ``None`` because ``None`` is a *legitimate
        answer* - "I checked the manifest and this day is not there" - and
        conflating the two put the per-day query straight back for exactly the
        days a batch is about to insert. (Caught by
        ``test_push_days_issues_one_manifest_query_for_the_whole_batch``.)
        """
        if self._engine is None:
            return PushOutcome(trading_date, "missing_local")
        local = self.local_partition(key, trading_date)
        if local is None:
            return PushOutcome(trading_date, "missing_local")

        if not self._ensure_schema():
            return PushOutcome(trading_date, "missing_local")

        if isinstance(known_remote, _Unset):
            remote = self.remote_manifest(key, trading_date, trading_date).get(trading_date)
        else:
            remote = known_remote

        if remote is not None:
            if remote.sha256 == local.sha256:
                return PushOutcome(trading_date, "identical", local.nbytes, local.row_count)
            if not rewrite:
                raise BlobRestatement(
                    f"{key} {trading_date.isoformat()} is already in {self.table.name} with "
                    f"different content (remote {remote.sha256[:12]}... {remote.nbytes} B vs "
                    f"local {local.sha256[:12]}... {local.nbytes} B). Quotes for a past date "
                    f"changing is a restatement worth noticing, not a write to apply quietly. "
                    f"Pass rewrite=True to replace it."
                )

        status = "rewritten" if remote is not None else "pushed"
        sql = f"""
            INSERT INTO {self.table.name}
                (trading_date, {self.table.key_column}, data_format, row_count, payload, sha256)
            VALUES
                (:trading_date, :key, :data_format, :row_count, :payload, :sha256)
            ON CONFLICT (trading_date, {self.table.key_column}) DO UPDATE SET
                data_format = EXCLUDED.data_format,
                row_count   = EXCLUDED.row_count,
                payload     = EXCLUDED.payload,
                sha256      = EXCLUDED.sha256,
                created_at  = NOW()
        """
        with labelled_transaction(
            self._engine,
            label=make_label(self._label_component, detail="push"),
            statement_timeout_ms=statement_timeout_ms,
        ) as conn:
            conn.execute(
                text(sql),
                {
                    "trading_date": trading_date,
                    "key": key,
                    "data_format": DATA_FORMAT,
                    "row_count": local.row_count,
                    "payload": local.payload,
                    "sha256": local.sha256,
                },
            )
        return PushOutcome(trading_date, status, local.nbytes, local.row_count)

    def push_days(
        self,
        key: str,
        trading_dates: Sequence[datetime.date],
        *,
        rewrite: bool = False,
        on_result=None,
    ) -> List[PushOutcome]:
        """:meth:`push_day` over many days, with **one** manifest query up front."""
        days = sorted(set(trading_dates))
        if not days:
            return []
        manifest = self.remote_manifest(key, days[0], days[-1])
        out: List[PushOutcome] = []
        for day in days:
            result = self.push_day(key, day, rewrite=rewrite, known_remote=manifest.get(day))
            out.append(result)
            if on_result is not None:
                on_result(result)
        return out

    # ── pull ──────────────────────────────────────────────────────────

    def _verified_payload(self, key: str, trading_date: datetime.date, row) -> bytes:
        payload = bytes(row.payload)
        actual = sha256_of(payload)
        stored = str(row.sha256)
        if actual != stored:
            raise BlobIntegrityError(
                f"{key} {trading_date.isoformat()} in {self.table.name} does not hash to its "
                f"stored sha256 (stored {stored[:12]}..., payload hashes to {actual[:12]}..., "
                f"{len(payload)} B). Refusing to write it: the existing sync modules name the "
                f"local file after the STORED sha without checking, so a truncated payload "
                f"lands under a filename that lies and every later reader believes it."
            )
        return payload

    def _land(
        self,
        key: str,
        trading_date: datetime.date,
        payload: bytes,
        sha: str,
        *,
        overwrite: bool,
    ) -> bool:
        part_dir = self.partition_dir(key, trading_date)
        dest = part_dir / f"{sha}.parquet"
        if part_dir.exists():
            existing = sorted(part_dir.glob("*.parquet"))
            if existing and not any(f.name == dest.name for f in existing):
                if not overwrite:
                    raise BlobRestatement(
                        f"{key} {trading_date.isoformat()} is already stored locally with "
                        f"different content ({existing[0].name[:12]}... vs {sha[:12]}...). "
                        f"Refusing to replace it silently; pass overwrite=True."
                    )
            elif existing:
                # The NAME matches, which is not the same as the bytes matching.
                # Content addressing makes the filename a claim about the content,
                # and the writers that produced these files do not verify it - so a
                # truncated local file sits here under the right name and this
                # branch used to return "nothing to do", making pull_day unable to
                # repair the one thing it exists to repair. Check, and rewrite when
                # the claim is false. That is a repair, not a restatement, so it
                # does not need `overwrite`.
                if sha256_of(dest.read_bytes()) == sha:
                    return False
                logger.warning(
                    "%s %s: local %s.parquet does not hash to its own name "
                    "(%d bytes on disk); repairing it from L2.",
                    key, trading_date, sha[:12], dest.stat().st_size,
                )
        part_dir.mkdir(parents=True, exist_ok=True)
        _atomic_write_bytes(dest, payload)
        for old in part_dir.glob("*.parquet"):
            if old == dest:
                continue
            try:
                old.unlink()
            except OSError:
                pass
        return True

    def pull_day(
        self, key: str, trading_date: datetime.date, *, overwrite: bool = False
    ) -> bool:
        """Fetch one partition, verify it, land it atomically. No DDL."""
        if self._engine is None or not self.table_exists():
            return False
        with self._engine.connect() as conn:
            row = conn.execute(
                text(
                    f"SELECT payload, sha256, data_format FROM {self.table.name} "
                    f"WHERE trading_date = :d AND {self.table.key_column} = :key"
                ),
                {"d": trading_date, "key": key},
            ).fetchone()
        if row is None:
            return False
        payload = self._verified_payload(key, trading_date, row)
        self._land(key, trading_date, payload, str(row.sha256), overwrite=overwrite)
        return True

    def prefetch_range(
        self,
        key: str,
        start: datetime.date,
        end: datetime.date,
        *,
        overwrite: bool = False,
    ) -> List[datetime.date]:
        """Download only the days that are missing or differ. Manifest first.

        Unlike the existing ``prefetch_range`` implementations this does not
        select ``payload`` for days it already has - on a 400 MB asset that is
        the whole point.
        """
        if self._engine is None or not self.table_exists():
            return []
        manifest = self.remote_manifest(key, start, end)
        if not manifest:
            return []
        wanted: List[datetime.date] = []
        for day, block in manifest.items():
            # A multi-file partition must be left ALONE. local_sha declines to
            # answer for one (there is no single content hash), and treating that
            # "None" as "absent" would send it down the fetch path, where _land
            # unlinks every file that is not the one it just wrote - silently
            # destroying the other parquet files a local read concatenates. Not
            # hypothetical: USD-OIS-Q12xM12STIRT-SERFFX-MIX23 has 2,613 files
            # across 1,382 days on this machine.
            part_dir = self.partition_dir(key, day)
            if part_dir.exists() and len(list(part_dir.glob("*.parquet"))) > 1:
                logger.warning(
                    "%s %s: local partition holds several parquet files; leaving it "
                    "untouched. Pulling would replace them with the single L2 blob. "
                    "Consolidate it first if the L2 copy is the one you want.",
                    key, day,
                )
                continue
            local = self.local_sha(key, day)
            # The filename is a CLAIM about the content, and the writers that
            # produced these files do not verify it - supabase_curve_sync.pull_day
            # writes non-atomically under f"{row.sha256}.parquet", so an
            # interrupted pull leaves a truncated file with a correct-looking
            # name. Cross-check the size against the manifest before believing
            # "identical": a stat() costs nothing and truncation is the failure
            # mode this actually has. (A same-size corruption still slips past
            # here; it is caught on the way in by _verified_payload and by the
            # repair branch in _land.)
            if local == block.sha256:
                try:
                    on_disk = (part_dir / f"{local}.parquet").stat().st_size
                except OSError:
                    on_disk = -1
                if on_disk == block.nbytes:
                    continue
                logger.warning(
                    "%s %s: local %s.parquet is %d bytes but L2 says %d — the name "
                    "cannot be its content hash. Re-pulling.",
                    key, day, local[:12], on_disk, block.nbytes,
                )
                wanted.append(day)
                continue
            if local is not None and not overwrite:
                logger.warning(
                    "%s %s: local content differs from L2 (%s... vs %s...); keeping local. "
                    "Pass overwrite=True to take the remote copy.",
                    key, day, local[:12], block.sha256[:12],
                )
                continue
            wanted.append(day)
        if not wanted:
            return []

        fetched: List[datetime.date] = []
        for chunk in _chunks(wanted, 32):
            with self._engine.connect() as conn:
                rows = conn.execute(
                    text(
                        f"SELECT trading_date, payload, sha256 FROM {self.table.name} "
                        f"WHERE {self.table.key_column} = :key AND trading_date = ANY(:days) "
                        f"ORDER BY trading_date"
                    ),
                    {"key": key, "days": list(chunk)},
                ).fetchall()
            for row in rows:
                day = _as_date(row.trading_date)
                payload = self._verified_payload(key, day, row)
                self._land(key, day, payload, str(row.sha256), overwrite=True)
                fetched.append(day)
        logger.info(
            "%s: pulled %d/%d day(s) from L2 (%d already identical locally)",
            key, len(fetched), len(manifest), len(manifest) - len(wanted),
        )
        return fetched

    # ── reporting ─────────────────────────────────────────────────────

    def coverage(self, key: str) -> dict:
        """What is local, what is remote, and where they disagree. No payloads."""
        local = self.local_dates(key)
        remote = self.remote_manifest(key)
        local_set, remote_set = set(local), set(remote)
        differing = [
            d for d in sorted(local_set & remote_set)
            if (self.local_sha(key, d) or "") != remote[d].sha256
        ]
        return {
            "key": key,
            "table": self.table.name,
            "local_days": len(local_set),
            "remote_days": len(remote_set),
            "local_only": sorted(local_set - remote_set),
            "remote_only": sorted(remote_set - local_set),
            "differing": differing,
            "remote_bytes": sum(b.nbytes for b in remote.values()),
            "remote_rows": sum(b.row_count for b in remote.values()),
        }


def _as_date(value) -> datetime.date:
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    return datetime.date.fromisoformat(str(value))


def _chunks(seq: Sequence, n: int) -> Iterable[Sequence]:
    for i in range(0, len(seq), n):
        yield seq[i : i + n]
