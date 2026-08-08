r"""The shared blob-block L2 mechanics.

These use an in-memory stand-in for the handful of statements
:class:`BlobBlockSync` issues, rather than a ``MagicMock`` engine. A MagicMock
makes a push→pull round trip a tautology - it hands back whatever you told it to
- and the spec's whole point is that a round trip which compares a blob to
itself proves nothing. :class:`FakeBlobDB` actually stores bytes, so the round
trip is real, and it exposes ``rows`` so a test can **corrupt what is stored**
and confirm the check goes red.
"""

from __future__ import annotations

import datetime
import hashlib
import io
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from Caching.supabase_blob_blocks import (
    BlobBlockSync,
    BlobBlockTable,
    BlobIntegrityError,
    BlobRestatement,
    MultiFilePartition,
)

TABLE = "arbs_swaption_cube_blocks_v1"
KEY_COL = "asset"
ASSET = "USD-SWAPTIONVOL-CITIVELOEXCEL"
D1 = datetime.date(2026, 1, 5)
D2 = datetime.date(2026, 1, 6)
D3 = datetime.date(2026, 1, 7)


def make_parquet(n_rows: int = 3, vol: float = 100.0) -> bytes:
    table = pa.table(
        {
            "expiry": pa.array([f"{i+1}Y" for i in range(n_rows)]),
            "tenor": pa.array(["10Y"] * n_rows),
            "offset_bp": pa.array([0.0] * n_rows, type=pa.float64()),
            "vol_bp": pa.array([vol + i for i in range(n_rows)], type=pa.float64()),
        }
    )
    buf = io.BytesIO()
    pq.write_table(table, buf, compression="zstd")
    return buf.getvalue()


def sha_of(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


# ── the stand-in ──────────────────────────────────────────────────────────


class _Row:
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def __getitem__(self, i):
        return list(self.__dict__.values())[i]


class _Result:
    def __init__(self, rows):
        self._rows = list(rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def __iter__(self):
        return iter(self._rows)


class _Conn:
    def __init__(self, db: "FakeBlobDB"):
        self.db = db

    def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        params = dict(params or {})
        self.db.log.append((sql, params))
        if "set_config(" in sql:
            return _Result([])
        if sql.upper().startswith(("CREATE ", "ALTER ", "DROP ")):
            self.db.ddl.append(sql)
            return _Result([])
        if "information_schema.tables" in sql and ":t" in sql or (
            "information_schema.tables" in sql and "table_name = :t" in sql
        ):
            present = self.db.table_present and params.get("t") == self.db.table
            return _Result([_Row(one=1)] if present else [])
        if "information_schema.tables" in sql:  # ANY(:names) currency check
            names = params.get("names") or []
            return _Result([_Row(table_name=n) for n in names] if self.db.table_present else [])
        if "information_schema.columns" in sql:
            from Caching.supabase_schema import SCHEMA_SQL, declared_objects

            _, cols, _ = declared_objects(SCHEMA_SQL)
            return _Result([_Row(table_name=t, column_name=c) for t, c in cols])
        if "pg_indexes" in sql:
            names = params.get("names") or []
            return _Result([_Row(indexname=n) for n in names])
        if sql.upper().startswith("INSERT INTO"):
            key = (params["trading_date"], params["key"])
            self.db.rows[key] = {
                "payload": params["payload"],
                "sha256": params["sha256"],
                "row_count": params["row_count"],
                "data_format": params["data_format"],
            }
            self.db.inserts += 1
            return _Result([])
        if "length(payload)" in sql:  # manifest
            out = []
            for (day, key), row in sorted(self.db.rows.items()):
                if key != params["key"]:
                    continue
                if params.get("start") and day < params["start"]:
                    continue
                if params.get("end") and day > params["end"]:
                    continue
                out.append(
                    _Row(
                        trading_date=day,
                        sha256=row["sha256"],
                        row_count=row["row_count"],
                        nbytes=len(row["payload"]),
                    )
                )
            return _Result(out)
        if "SELECT DISTINCT" in sql:
            return _Result([_Row(k=k) for k in sorted({k for _, k in self.db.rows})])
        if "SELECT payload, sha256, data_format" in sql:
            row = self.db.rows.get((params["d"], params["key"]))
            if row is None:
                return _Result([])
            self.db.payload_reads.append((params["d"], params["key"]))
            return _Result([_Row(**row)])
        if "SELECT trading_date, payload, sha256" in sql:
            out = []
            for day in params["days"]:
                row = self.db.rows.get((day, params["key"]))
                if row is None:
                    continue
                self.db.payload_reads.append((day, params["key"]))
                out.append(_Row(trading_date=day, payload=row["payload"], sha256=row["sha256"]))
            return _Result(out)
        raise AssertionError(f"FakeBlobDB got an unexpected statement: {sql[:160]}")


class _Txn:
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return _Conn(self.db)

    def __exit__(self, *a):
        return False


class FakeBlobDB:
    """Stores real bytes for the statements BlobBlockSync issues."""

    def __init__(self, *, table: str = TABLE, table_present: bool = True):
        self.table = table
        self.table_present = table_present
        self.rows: dict[tuple, dict] = {}
        self.log: list[tuple[str, dict]] = []
        self.ddl: list[str] = []
        self.inserts = 0
        self.payload_reads: list[tuple] = []
        self.url = "postgresql://fake/fake"

    # SQLAlchemy Engine surface that BlobBlockSync actually uses
    def begin(self):
        return _Txn(self)

    def connect(self):
        return _Txn(self)

    # helpers for the corruption tests
    def truncate_payload(self, day, key, keep: int = 10) -> None:
        self.rows[(day, key)]["payload"] = self.rows[(day, key)]["payload"][:keep]

    def scramble_sha(self, day, key) -> None:
        self.rows[(day, key)]["sha256"] = "0" * 64


class _CubeSync(BlobBlockSync):
    def __init__(self, base_dir, engine):
        super().__init__(
            table=BlobBlockTable(name=TABLE, key_column=KEY_COL),
            base_dir=Path(base_dir),
            engine=engine,
            label_component="test",
        )

    def asset_root(self, key: str) -> Path:
        return self.base_dir / "vol_raw" / f"asset={key}"

    def partition_dir(self, key, trading_date) -> Path:
        return self.asset_root(key) / f"date={trading_date.isoformat()}"


@pytest.fixture
def db():
    return FakeBlobDB()


@pytest.fixture
def sync(tmp_path, db):
    return _CubeSync(tmp_path / "cube", db)


def write_local(sync: BlobBlockSync, key: str, day: datetime.date, payload: bytes) -> Path:
    part = sync.partition_dir(key, day)
    part.mkdir(parents=True, exist_ok=True)
    dest = part / f"{sha_of(payload)}.parquet"
    dest.write_bytes(payload)
    return dest


# ── identifiers ───────────────────────────────────────────────────────────


class TestTableIdentifiers:
    @pytest.mark.parametrize(
        "name,col",
        [("bad-table", "asset"), ("t", "a; DROP TABLE x"), ("SELECT", "asset"), ("", "asset")],
    )
    def test_rejects_anything_that_is_not_a_bare_identifier(self, name, col):
        with pytest.raises(ValueError):
            BlobBlockTable(name=name, key_column=col)

    def test_accepts_the_real_one(self):
        assert BlobBlockTable(name=TABLE, key_column=KEY_COL).name == TABLE


# ── the round trip, and making it fail ────────────────────────────────────


class TestRoundTrip:
    def test_push_then_pull_into_a_cold_directory_reproduces_the_bytes(self, tmp_path, db, sync):
        payload = make_parquet()
        write_local(sync, ASSET, D1, payload)
        assert sync.push_day(ASSET, D1).status == "pushed"

        cold = _CubeSync(tmp_path / "cold", db)
        assert cold.pull_day(ASSET, D1) is True
        landed = list(cold.partition_dir(ASSET, D1).glob("*.parquet"))
        assert len(landed) == 1
        assert landed[0].read_bytes() == payload
        assert landed[0].stem == sha_of(payload)
        # and it is still readable parquet, not just equal bytes
        assert pq.read_table(landed[0]).num_rows == 3

    def test_a_truncated_stored_payload_is_refused_and_nothing_lands(self, tmp_path, db, sync):
        """The check has to go red. This is the test that makes the green one mean something."""
        payload = make_parquet()
        write_local(sync, ASSET, D1, payload)
        sync.push_day(ASSET, D1)
        db.truncate_payload(D1, ASSET, keep=40)

        cold = _CubeSync(tmp_path / "cold", db)
        with pytest.raises(BlobIntegrityError) as excinfo:
            cold.pull_day(ASSET, D1)
        assert "does not hash to its stored sha256" in str(excinfo.value)
        assert not cold.partition_dir(ASSET, D1).exists()

    def test_a_scrambled_stored_sha_is_refused(self, tmp_path, db, sync):
        write_local(sync, ASSET, D1, make_parquet())
        sync.push_day(ASSET, D1)
        db.scramble_sha(D1, ASSET)

        cold = _CubeSync(tmp_path / "cold", db)
        with pytest.raises(BlobIntegrityError):
            cold.pull_day(ASSET, D1)
        assert not cold.partition_dir(ASSET, D1).exists()

    def test_a_swapped_payload_under_the_old_sha_is_refused(self, tmp_path, db, sync):
        """The realistic corruption: right key, right sha column, wrong bytes."""
        write_local(sync, ASSET, D1, make_parquet(vol=100.0))
        sync.push_day(ASSET, D1)
        db.rows[(D1, ASSET)]["payload"] = make_parquet(vol=999.0)  # sha column unchanged

        cold = _CubeSync(tmp_path / "cold", db)
        with pytest.raises(BlobIntegrityError):
            cold.pull_day(ASSET, D1)

    def test_pull_of_an_absent_day_is_a_miss_not_an_error(self, sync):
        assert sync.pull_day(ASSET, D3) is False


# ── restatement, both directions ──────────────────────────────────────────


class TestRestatement:
    def test_identical_content_is_skipped_not_re_uploaded(self, sync, db):
        write_local(sync, ASSET, D1, make_parquet())
        assert sync.push_day(ASSET, D1).status == "pushed"
        assert db.inserts == 1
        again = sync.push_day(ASSET, D1)
        assert again.status == "identical" and again.wrote is False
        assert db.inserts == 1, "an identical day was re-uploaded"

    def test_push_refuses_a_differing_remote_without_rewrite(self, sync, db):
        write_local(sync, ASSET, D1, make_parquet(vol=100.0))
        sync.push_day(ASSET, D1)
        # a restatement of the same day
        for f in sync.partition_dir(ASSET, D1).glob("*.parquet"):
            f.unlink()
        write_local(sync, ASSET, D1, make_parquet(vol=101.0))
        with pytest.raises(BlobRestatement) as excinfo:
            sync.push_day(ASSET, D1)
        assert "restatement" in str(excinfo.value).lower()
        assert db.inserts == 1

    def test_push_with_rewrite_replaces_and_says_so(self, sync, db):
        write_local(sync, ASSET, D1, make_parquet(vol=100.0))
        sync.push_day(ASSET, D1)
        for f in sync.partition_dir(ASSET, D1).glob("*.parquet"):
            f.unlink()
        new = make_parquet(vol=101.0)
        write_local(sync, ASSET, D1, new)
        assert sync.push_day(ASSET, D1, rewrite=True).status == "rewritten"
        assert db.rows[(D1, ASSET)]["payload"] == new
        assert db.inserts == 2

    def test_pull_refuses_to_clobber_a_differing_local_partition(self, tmp_path, db, sync):
        write_local(sync, ASSET, D1, make_parquet(vol=100.0))
        sync.push_day(ASSET, D1)

        other = _CubeSync(tmp_path / "other", db)
        local_bytes = make_parquet(vol=555.0)
        write_local(other, ASSET, D1, local_bytes)
        with pytest.raises(BlobRestatement):
            other.pull_day(ASSET, D1)
        # the local copy is untouched
        files = list(other.partition_dir(ASSET, D1).glob("*.parquet"))
        assert len(files) == 1 and files[0].read_bytes() == local_bytes

        assert other.pull_day(ASSET, D1, overwrite=True) is True
        files = list(other.partition_dir(ASSET, D1).glob("*.parquet"))
        assert len(files) == 1 and files[0].read_bytes() != local_bytes


# ── multi-file partitions ─────────────────────────────────────────────────


class TestMultiFilePartition:
    def test_push_refuses_rather_than_picking_one_file(self, sync):
        """The silent-loss case: a local read concats, a blob push of file[0] does not."""
        write_local(sync, ASSET, D1, make_parquet(vol=100.0))
        write_local(sync, ASSET, D1, make_parquet(vol=200.0))
        assert len(list(sync.partition_dir(ASSET, D1).glob("*.parquet"))) == 2
        with pytest.raises(MultiFilePartition) as excinfo:
            sync.push_day(ASSET, D1)
        assert "2 parquet files" in str(excinfo.value)

    def test_local_sha_declines_to_answer_for_a_multi_file_partition(self, sync):
        write_local(sync, ASSET, D1, make_parquet(vol=100.0))
        write_local(sync, ASSET, D1, make_parquet(vol=200.0))
        assert sync.local_sha(ASSET, D1) is None


# ── prefetch only fetches what is missing ─────────────────────────────────


class TestPrefetch:
    def test_prefetch_does_not_download_days_it_already_has(self, tmp_path, db, sync):
        payloads = {D1: make_parquet(vol=1.0), D2: make_parquet(vol=2.0), D3: make_parquet(vol=3.0)}
        for day, payload in payloads.items():
            write_local(sync, ASSET, day, payload)
            sync.push_day(ASSET, day)

        warm = _CubeSync(tmp_path / "warm", db)
        write_local(warm, ASSET, D1, payloads[D1])  # already has one of the three
        db.payload_reads.clear()

        fetched = warm.prefetch_range(ASSET, D1, D3)
        assert sorted(fetched) == [D2, D3]
        # the assertion that matters: D1's payload never crossed the wire
        assert sorted({d for d, _ in db.payload_reads}) == [D2, D3]

    def test_prefetch_verifies_every_payload_it_lands(self, tmp_path, db, sync):
        for day in (D1, D2):
            write_local(sync, ASSET, day, make_parquet(vol=float(day.day)))
            sync.push_day(ASSET, day)
        db.truncate_payload(D2, ASSET, keep=25)

        cold = _CubeSync(tmp_path / "cold", db)
        with pytest.raises(BlobIntegrityError):
            cold.prefetch_range(ASSET, D1, D2)

    def test_prefetch_keeps_a_differing_local_day_unless_told_otherwise(self, tmp_path, db, sync, caplog):
        write_local(sync, ASSET, D1, make_parquet(vol=1.0))
        sync.push_day(ASSET, D1)

        other = _CubeSync(tmp_path / "other", db)
        mine = make_parquet(vol=42.0)
        write_local(other, ASSET, D1, mine)
        assert other.prefetch_range(ASSET, D1, D1) == []
        assert list(other.partition_dir(ASSET, D1).glob("*.parquet"))[0].read_bytes() == mine
        assert other.prefetch_range(ASSET, D1, D1, overwrite=True) == [D1]

    def test_prefetch_on_an_empty_remote_is_a_no_op(self, sync):
        assert sync.prefetch_range(ASSET, D1, D3) == []


# ── no DDL on the read path ───────────────────────────────────────────────


class TestNoDdlOnRead:
    def test_reads_against_a_missing_table_answer_empty_and_run_no_ddl(self, tmp_path):
        db = FakeBlobDB(table_present=False)
        sync = _CubeSync(tmp_path / "cube", db)
        assert sync.pull_day(ASSET, D1) is False
        assert sync.prefetch_range(ASSET, D1, D3) == []
        assert sync.remote_manifest(ASSET) == {}
        assert sync.remote_keys() == []
        assert db.ddl == [], f"a read path issued DDL: {db.ddl}"

    def test_no_engine_means_no_queries_at_all(self, tmp_path):
        sync = _CubeSync(tmp_path / "cube", None)
        write_local(sync, ASSET, D1, make_parquet())
        assert sync.pull_day(ASSET, D1) is False
        assert sync.prefetch_range(ASSET, D1, D3) == []
        assert sync.push_day(ASSET, D1).status == "missing_local"


# ── reporting ─────────────────────────────────────────────────────────────


class TestCoverage:
    def test_coverage_separates_local_only_remote_only_and_differing(self, tmp_path, db, sync):
        # D1 both and equal, D2 local only, D3 both but different
        write_local(sync, ASSET, D1, make_parquet(vol=1.0))
        sync.push_day(ASSET, D1)
        write_local(sync, ASSET, D2, make_parquet(vol=2.0))
        write_local(sync, ASSET, D3, make_parquet(vol=3.0))
        sync.push_day(ASSET, D3)
        for f in sync.partition_dir(ASSET, D3).glob("*.parquet"):
            f.unlink()
        write_local(sync, ASSET, D3, make_parquet(vol=33.0))

        # a remote-only day
        other = _CubeSync(tmp_path / "other", db)
        write_local(other, ASSET, datetime.date(2026, 1, 8), make_parquet(vol=8.0))
        other.push_day(ASSET, datetime.date(2026, 1, 8))

        cov = sync.coverage(ASSET)
        assert cov["local_days"] == 3
        assert cov["remote_days"] == 3
        assert cov["local_only"] == [D2]
        assert cov["remote_only"] == [datetime.date(2026, 1, 8)]
        assert cov["differing"] == [D3]
        assert cov["remote_bytes"] > 0

    def test_push_days_issues_one_manifest_query_for_the_whole_batch(self, sync, db):
        for day in (D1, D2, D3):
            write_local(sync, ASSET, day, make_parquet(vol=float(day.day)))
        db.log.clear()
        results = sync.push_days(ASSET, [D1, D2, D3])
        assert [r.status for r in results] == ["pushed"] * 3
        manifests = [s for s, _ in db.log if "length(payload)" in s]
        assert len(manifests) == 1, f"expected one manifest query, got {len(manifests)}"
