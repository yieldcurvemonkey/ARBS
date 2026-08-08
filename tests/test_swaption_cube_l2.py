r"""SwaptionCubeStore's opt-in L2 tier.

The load-bearing test in here is
``test_default_store_never_even_asks_for_an_engine``: it replaces
``Caching.supabase_engine.get_engine`` with something that *raises*, so a store
operation that merely tries to resolve an engine fails the test. Asserting "no
rows were written" would pass for a store that connected, ran ``ensure_schema``
(which is DDL) and then decided not to write - which is most of the hazard.
"""

from __future__ import annotations

import datetime

import pytest

from Caching.l2_policy import SWAPTION_CUBE_L2_ENV, L2Mode
from Caching.swaption_cube_store import SwaptionCubeStore, asset_for
from tests.test_supabase_blob_blocks import FakeBlobDB, make_parquet, sha_of

ASSET = asset_for("USD")
DAY = datetime.date(2026, 1, 5)


class _Boom(RuntimeError):
    pass


@pytest.fixture
def no_engine_allowed(monkeypatch):
    """Any attempt to resolve an engine is a test failure."""
    import Caching.supabase_engine as eng

    def _explode():
        raise _Boom("get_engine() was called; the L2 gate did not hold")

    monkeypatch.setattr(eng, "get_engine", _explode)
    return eng


@pytest.fixture
def fake_engine(monkeypatch):
    import Caching.supabase_engine as eng

    db = FakeBlobDB()
    monkeypatch.setattr(eng, "get_engine", lambda: db)
    return db


@pytest.fixture
def store(tmp_path):
    return SwaptionCubeStore(base_dir=tmp_path / "cubes")


def _seed_local(store: SwaptionCubeStore, day=DAY, vol: float = 100.0) -> bytes:
    payload = make_parquet(vol=vol)
    part = store._part_dir(ASSET, day)
    part.mkdir(parents=True, exist_ok=True)
    (part / f"{sha_of(payload)}.parquet").write_bytes(payload)
    return payload


class _FakeCube:
    """The minimum ``to_frame`` needs. Keeps this file off the vol package."""

    as_of = DAY
    currency = "USD"
    measure = "normal"
    skew_measure = "offset"
    served_unit = "bp"
    vol_unit = "bp"
    strike_unit = "bp"
    source = "test"

    def __init__(self, vol: float = 100.0):
        self._vol = vol

    def expiries(self):
        return ["1Y", "2Y"]

    def tenors(self):
        return ["10Y"]

    def offsets(self):
        return [0.0]

    def vol(self, expiry, tenor, off):
        return self._vol + len(str(expiry))


# ── off by default ────────────────────────────────────────────────────────


class TestDefaultIsOff:
    def test_env_unset_means_off(self, monkeypatch):
        monkeypatch.delenv(SWAPTION_CUBE_L2_ENV, raising=False)
        from Caching.l2_policy import swaption_cube_l2_mode

        assert swaption_cube_l2_mode() is L2Mode.OFF

    def test_default_store_never_even_asks_for_an_engine(
        self, monkeypatch, store, no_engine_allowed
    ):
        monkeypatch.delenv(SWAPTION_CUBE_L2_ENV, raising=False)
        store.write_day(ASSET, DAY, _FakeCube())
        assert store.has_day(ASSET, DAY)
        assert store.read_day(ASSET, DAY) is not None
        # a genuine miss must not reach for L2 either
        assert store.read_day(ASSET, datetime.date(2026, 1, 6)) is None
        assert store.prefetch_range(ASSET, DAY, DAY) == []
        assert store.l2_coverage(ASSET) is None
        assert store.l2_sync(need="read") is None
        assert store.l2_sync(need="write") is None

    def test_a_typo_in_the_env_raises_rather_than_enabling(self, monkeypatch, store):
        monkeypatch.setenv(SWAPTION_CUBE_L2_ENV, "enabled")
        from Caching.l2_policy import L2ModeError, swaption_cube_l2_mode

        with pytest.raises(L2ModeError):
            swaption_cube_l2_mode()
        # ...and the store degrades to local rather than propagating it into a write
        assert store.l2_sync(need="write") is None
        assert store.write_day(ASSET, DAY, _FakeCube()) is not None


# ── read mode reads, and does not write ───────────────────────────────────


class TestReadMode:
    def test_read_mode_pulls_a_missing_day_but_never_pushes(
        self, monkeypatch, tmp_path, fake_engine
    ):
        publisher = SwaptionCubeStore(base_dir=tmp_path / "pub", l2=L2Mode.READ_WRITE)
        payload = _seed_local(publisher)
        assert publisher.l2_sync(need="write").push_day(ASSET, DAY).status == "pushed"

        reader = SwaptionCubeStore(base_dir=tmp_path / "reader", l2=L2Mode.READ)
        assert reader.has_day(ASSET, DAY) is False
        frame = reader.read_day(ASSET, DAY)
        assert frame is not None and len(frame) == 3
        landed = list(reader._part_dir(ASSET, DAY).glob("*.parquet"))
        assert landed[0].read_bytes() == payload

        # writing in read mode must not publish
        before = fake_engine.inserts
        writer = SwaptionCubeStore(base_dir=tmp_path / "w2", l2=L2Mode.READ)
        writer.write_day(ASSET, datetime.date(2026, 2, 2), _FakeCube(vol=7.0))
        assert fake_engine.inserts == before

    def test_read_fallthrough_does_not_loop_when_the_pull_lands_nothing(
        self, monkeypatch, tmp_path, fake_engine
    ):
        reader = SwaptionCubeStore(base_dir=tmp_path / "reader", l2=L2Mode.READ)
        assert reader.read_day(ASSET, DAY) is None  # remote is empty; must terminate


# ── read_write publishes ──────────────────────────────────────────────────


class TestReadWriteMode:
    def test_write_day_publishes(self, tmp_path, fake_engine):
        store = SwaptionCubeStore(base_dir=tmp_path / "cubes", l2=L2Mode.READ_WRITE)
        store.write_day(ASSET, DAY, _FakeCube())
        assert fake_engine.inserts == 1
        assert (DAY, ASSET) in fake_engine.rows

    def test_a_byte_identical_local_write_still_checks_l2(self, tmp_path, fake_engine):
        """`write_day` returns None when the local file is unchanged. That says
        nothing about whether L2 has the day, so the push must still happen."""
        store = SwaptionCubeStore(base_dir=tmp_path / "cubes", l2=L2Mode.READ_WRITE)
        store.write_day(ASSET, DAY, _FakeCube(), push_l2=False)
        assert fake_engine.inserts == 0
        assert store.write_day(ASSET, DAY, _FakeCube()) is None  # local no-op
        assert fake_engine.inserts == 1, "the L2 push was skipped because L1 was a hit"

    def test_push_failure_does_not_fail_the_local_write(self, tmp_path, monkeypatch, fake_engine):
        store = SwaptionCubeStore(base_dir=tmp_path / "cubes", l2=L2Mode.READ_WRITE)
        from Caching.supabase_blob_blocks import BlobBlockSync

        def _explode(self, *a, **k):
            raise RuntimeError("pooler said no")

        monkeypatch.setattr(BlobBlockSync, "push_day", _explode)
        assert store.write_day(ASSET, DAY, _FakeCube()) is not None
        assert store.has_day(ASSET, DAY)

    def test_overwrite_propagates_as_rewrite(self, tmp_path, fake_engine):
        store = SwaptionCubeStore(base_dir=tmp_path / "cubes", l2=L2Mode.READ_WRITE)
        store.write_day(ASSET, DAY, _FakeCube(vol=100.0))
        first = fake_engine.rows[(DAY, ASSET)]["sha256"]
        store.write_day(ASSET, DAY, _FakeCube(vol=200.0), overwrite=True)
        assert fake_engine.rows[(DAY, ASSET)]["sha256"] != first

    def test_a_restatement_without_overwrite_is_refused_locally_first(self, tmp_path, fake_engine):
        store = SwaptionCubeStore(base_dir=tmp_path / "cubes", l2=L2Mode.READ_WRITE)
        store.write_day(ASSET, DAY, _FakeCube(vol=100.0))
        with pytest.raises(FileExistsError):
            store.write_day(ASSET, DAY, _FakeCube(vol=200.0))
        assert fake_engine.inserts == 1, "L2 was written despite the local refusal"


# ── explicit arguments outrank the environment, both ways ─────────────────


class TestExplicitOverrides:
    def test_push_l2_false_beats_read_write(self, tmp_path, monkeypatch, fake_engine):
        monkeypatch.setenv(SWAPTION_CUBE_L2_ENV, "rw")
        store = SwaptionCubeStore(base_dir=tmp_path / "cubes")
        store.write_day(ASSET, DAY, _FakeCube(), push_l2=False)
        assert fake_engine.inserts == 0

    def test_push_l2_true_beats_an_env_that_is_off(self, tmp_path, monkeypatch, fake_engine):
        """The property citivelo_excel_warm.py --push-l2 never had: a flag set
        after import still works, because the mode is read at call time."""
        monkeypatch.delenv(SWAPTION_CUBE_L2_ENV, raising=False)
        store = SwaptionCubeStore(base_dir=tmp_path / "cubes")
        store.write_day(ASSET, DAY, _FakeCube(), push_l2=True)
        assert fake_engine.inserts == 1

    def test_store_level_false_pins_local_only(self, tmp_path, monkeypatch, no_engine_allowed):
        monkeypatch.setenv(SWAPTION_CUBE_L2_ENV, "rw")
        store = SwaptionCubeStore(base_dir=tmp_path / "cubes", l2=False)
        store.write_day(ASSET, DAY, _FakeCube())  # would raise _Boom if it resolved an engine
        assert store.l2_sync(need="read") is None

    def test_env_change_is_picked_up_without_a_module_reload(self, tmp_path, monkeypatch, fake_engine):
        store = SwaptionCubeStore(base_dir=tmp_path / "cubes")
        monkeypatch.delenv(SWAPTION_CUBE_L2_ENV, raising=False)
        store.write_day(ASSET, DAY, _FakeCube())
        assert fake_engine.inserts == 0
        monkeypatch.setenv(SWAPTION_CUBE_L2_ENV, "read_write")
        store.write_day(ASSET, datetime.date(2026, 3, 3), _FakeCube(vol=5.0))
        assert fake_engine.inserts == 1


# ── the table is declared in the shared bundle ────────────────────────────


def test_resolve_cube_sync_fails_closed_on_an_unrecognised_need(tmp_path):
    """It used to fail OPEN: a value that was neither 'read' nor 'write' fell
    through both guards and returned a live, production-bound sync."""
    from Caching.supabase_swaption_cube_sync import resolve_cube_sync

    for need in ("readwrite", "", "READ", "pull", None):
        with pytest.raises(ValueError):
            resolve_cube_sync(tmp_path, mode=L2Mode.OFF, need=need)


def test_the_new_table_is_in_the_ddl_bundle_and_follows_house_conventions():
    from Caching.supabase_schema import SCHEMA_SQL, declared_objects
    from Caching.supabase_swaption_cube_sync import SWAPTION_CUBE_BLOCKS_TABLE

    tables, _, indexes = declared_objects(SCHEMA_SQL)
    assert SWAPTION_CUBE_BLOCKS_TABLE in tables
    assert "idx_swaption_cube_asset_date" in indexes
    assert SWAPTION_CUBE_BLOCKS_TABLE.startswith("arbs_")
    assert SWAPTION_CUBE_BLOCKS_TABLE.endswith("_v1")

    block = SCHEMA_SQL.split(f"CREATE TABLE IF NOT EXISTS {SWAPTION_CUBE_BLOCKS_TABLE}")[1]
    block = block.split(");")[0]
    assert "payload BYTEA NOT NULL" in block          # never base64
    assert "sha256 VARCHAR NOT NULL" in block
    assert "row_count INTEGER NOT NULL" in block
    assert "data_format VARCHAR NOT NULL" in block
    assert "created_at TIMESTAMPTZ" in block          # never TIMESTAMP
    assert "PRIMARY KEY (trading_date, asset)" in block
