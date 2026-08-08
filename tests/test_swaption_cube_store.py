r"""The swaption cube store: round trip, coverage, and the ways a store lies.

Shaped after ``tests/test_ust_future_store.py`` and ``tests/test_curve_store_eris.py``
- every test builds ``SwaptionCubeStore(base_dir=tmp_path)``, so nothing here can
reach the real cache, and there is no Supabase tier to patch out because the
store deliberately has none (see its module docstring).

The cube under test is the RECORDED LIVE one, not a generated surface. A store
that round-trips a smooth synthetic grid can still lose a kink, a stale corner or
a wing that only real quotes have.
"""

from __future__ import annotations

import dataclasses
import datetime

import pandas as pd
import pytest

from Caching.swaption_cube_store import (
    CUBE_SCHEMA_VERSION,
    SwaptionCubeStore,
    asset_for,
)
from MDP.CitiVelocityExcel.vol.live_snapshot import load_snapshot


@pytest.fixture(scope="module")
def snapshot():
    return load_snapshot()


@pytest.fixture(scope="module")
def cube(snapshot):
    return snapshot.cube()


@pytest.fixture()
def store(tmp_path):
    return SwaptionCubeStore(base_dir=tmp_path)


def test_asset_name_carries_the_provider():
    """Two providers must never share a key.

    This repo has a recorded incident where two curve variants shared one
    CurveStore asset and which answer you got depended on cache state.
    """
    assert asset_for("USD") == "USD-SWAPTIONVOL-CITIVELOEXCEL"
    assert asset_for("eur", provider="citivelostream") == "EUR-SWAPTIONVOL-CITIVELOSTREAM"
    assert asset_for("USD") != asset_for("USD", provider="CITIVELO")


def test_a_cold_store_misses_rather_than_raises(store, snapshot):
    asset = asset_for("USD")
    assert store.has_day(asset, snapshot.as_of) is False
    assert store.read_day(asset, snapshot.as_of) is None
    assert store.reconstruct_cube(asset, snapshot.as_of) is None
    assert store.available_dates(asset) == []
    assert store.available_assets() == []
    assert store.coverage(asset)["n_days"] == 0


def test_every_node_round_trips_exactly(store, cube, snapshot):
    """260 real nodes, in and out, with no tolerance at all.

    A store is allowed to be slow or large. It is not allowed to change a number,
    so this asserts equality rather than approximate equality.
    """
    asset = asset_for("USD")
    meta = store.write_day(asset, snapshot.as_of, cube, citi_index=snapshot.citi_index)
    assert meta is not None and meta["size"] > 0

    back = store.reconstruct_cube(asset, snapshot.as_of)
    assert back is not None
    assert back.expiries() == cube.expiries()
    assert back.tenors() == cube.tenors()
    assert back.offsets() == cube.offsets()
    n = 0
    for expiry in cube.expiries():
        for tenor in cube.tenors():
            for off in cube.offsets():
                assert back.vol(expiry, tenor, off) == cube.vol(expiry, tenor, off)
                n += 1
    assert n == len(cube.expiries()) * len(cube.tenors()) * len(cube.offsets())


def test_the_units_survive_because_they_are_stored(store, cube, snapshot):
    """The grid alone is not enough: a cube in the wrong unit is 10,000x wrong.

    ``served_unit`` / ``vol_unit`` / ``strike_unit`` / ``measure`` are carried in
    the file rather than re-declared at read time, so a reader cannot silently
    reinterpret a stored surface.
    """
    asset = asset_for("USD")
    store.write_day(asset, snapshot.as_of, cube, citi_index=snapshot.citi_index)
    back = store.reconstruct_cube(asset, snapshot.as_of)
    for field in ("currency", "measure", "skew_measure", "served_unit", "vol_unit",
                  "strike_unit", "source", "as_of"):
        assert getattr(back, field) == getattr(cube, field), field


def test_the_rebuilt_cube_has_passed_its_own_validation(store, cube, snapshot):
    """reconstruct_cube returns a validated object, not a bag of numbers."""
    asset = asset_for("USD")
    store.write_day(asset, snapshot.as_of, cube, citi_index=snapshot.citi_index)
    back = store.reconstruct_cube(asset, snapshot.as_of)
    assert back.validate() is back  # idempotent, and it did not raise


def test_an_identical_rewrite_is_a_no_op(store, cube, snapshot):
    """Content-addressed: the same day written twice costs one file."""
    asset = asset_for("USD")
    first = store.write_day(asset, snapshot.as_of, cube, citi_index=snapshot.citi_index)
    second = store.write_day(asset, snapshot.as_of, cube, citi_index=snapshot.citi_index)
    assert first is not None
    assert second is None, "an unchanged day must not rewrite"
    part = store._part_dir(asset, snapshot.as_of)
    assert len(list(part.glob("*.parquet"))) == 1


def test_a_restated_day_raises_rather_than_going_ambiguous(store, cube, snapshot):
    """One partition is one cube, so a conflicting write cannot be silent.

    Content addressing means a DIFFERENT cube for the same day lands under a
    different sha - so without a guard it would sit alongside the first and the
    read would pick by hash order, i.e. at random. CurveStore tolerates several
    files per partition because its rows are different timestamps within the day
    and readers concat them; a surface has no such reading.

    Both silent outcomes are wrong (dropping the new quotes, or replacing the old
    ones unasked), so this raises and the caller chooses. Quotes for a past date
    changing is a restatement worth noticing.
    """
    asset = asset_for("USD")
    store.write_day(asset, snapshot.as_of, cube, citi_index=snapshot.citi_index)

    bumped = dataclasses.replace(cube, atm=cube.atm + 1.0)
    with pytest.raises(FileExistsError, match="different content"):
        store.write_day(asset, snapshot.as_of, bumped, citi_index=snapshot.citi_index)
    assert len(list(store._part_dir(asset, snapshot.as_of).glob("*.parquet"))) == 1
    assert store.reconstruct_cube(asset, snapshot.as_of).atm_vol("1Y", "10Y") == pytest.approx(
        cube.atm_vol("1Y", "10Y")
    ), "the stored day must be untouched by a refused write"

    meta = store.write_day(
        asset, snapshot.as_of, bumped, citi_index=snapshot.citi_index, overwrite=True
    )
    assert meta is not None
    back = store.reconstruct_cube(asset, snapshot.as_of)
    assert back.atm_vol("1Y", "10Y") == pytest.approx(cube.atm_vol("1Y", "10Y") + 1.0)
    assert len(list(store._part_dir(asset, snapshot.as_of).glob("*.parquet"))) == 1


def test_coverage_and_dates_report_what_is_actually_there(store, cube, snapshot):
    asset = asset_for("USD")
    days = [snapshot.as_of - datetime.timedelta(days=k) for k in (7, 3, 0)]
    for day in days:
        store.write_day(asset, day, dataclasses.replace(cube, as_of=day))

    assert store.available_dates(asset) == sorted(days)
    assert store.available_assets() == [asset]
    cov = store.coverage(asset)
    assert cov["n_days"] == 3
    assert cov["first"] == min(days) and cov["last"] == max(days)
    assert cov["gaps"] > 0, "business days between the written ones are genuinely missing"


def test_batch_reconstruction_skips_missing_days_rather_than_failing(store, cube, snapshot):
    asset = asset_for("USD")
    present = snapshot.as_of
    absent = snapshot.as_of - datetime.timedelta(days=1)
    store.write_day(asset, present, cube)

    out = store.reconstruct_cubes_batch(asset, [absent, present])
    assert set(out) == {present}
    assert out[present].atm_vol("1Y", "10Y") == cube.atm_vol("1Y", "10Y")


def test_a_damaged_partition_reads_as_a_miss(store, cube, snapshot):
    """A corrupt file must degrade to "rebuild it", never take the caller down.

    Same contract as ``CurveStore._load_..._point``: the fallback recomputes the
    same artefact from the same quotes, so a silent miss is right here and a
    raise is not.
    """
    asset = asset_for("USD")
    store.write_day(asset, snapshot.as_of, cube)
    for f in store._part_dir(asset, snapshot.as_of).glob("*.parquet"):
        f.write_bytes(b"not a parquet file")
    assert store.read_day(asset, snapshot.as_of) is None
    assert store.reconstruct_cube(asset, snapshot.as_of) is None


def test_a_future_schema_version_is_refused_not_guessed(store, cube, snapshot):
    """Reading a newer vintage wrong is worse than not reading it."""
    asset = asset_for("USD")
    store.write_day(asset, snapshot.as_of, cube)
    frame = store.read_day(asset, snapshot.as_of)
    frame["schema_version"] = CUBE_SCHEMA_VERSION + 1
    with pytest.raises(ValueError, match="schema v"):
        SwaptionCubeStore.cube_from_frame(frame)


def test_an_atm_only_cube_stores_and_rebuilds(store, snapshot):
    """The warm's abort path has to leave something usable behind.

    If the Excel fetch stops after the ATM group, what is on disk is an ATM-only
    surface - and that is a complete, priceable cube, not a broken one.
    """
    atm_only = snapshot.cube(offsets_bp=())
    assert atm_only.offsets() == [0.0]
    asset = asset_for("USD")
    store.write_day(asset, snapshot.as_of, atm_only)
    back = store.reconstruct_cube(asset, snapshot.as_of)
    assert back.offsets() == [0.0]
    assert back.skew == {}
    assert back.atm_vol("1Y", "10Y") == atm_only.atm_vol("1Y", "10Y")


def test_the_store_never_touches_the_real_cache_dir(tmp_path):
    """Every test above is hermetic, and the default lives somewhere else."""
    store = SwaptionCubeStore(base_dir=tmp_path)
    assert store.base_dir == tmp_path
    assert "swaption_cube_store" in str(SwaptionCubeStore._default_base_dir())
    assert SwaptionCubeStore._default_base_dir() != tmp_path


def test_stored_frame_is_self_describing(store, cube, snapshot):
    """Someone finding one of these files in three years can read it.

    No sidecar, no external registry: the parquet carries the axes, the units and
    the provenance.
    """
    asset = asset_for("USD")
    store.write_day(asset, snapshot.as_of, cube, citi_index=snapshot.citi_index)
    frame = store.read_day(asset, snapshot.as_of)
    assert isinstance(frame, pd.DataFrame)
    for col in ("expiry", "tenor", "offset_bp", "vol_bp", "as_of", "currency",
                "measure", "served_unit", "citi_index", "schema_version"):
        assert col in frame.columns, col
    assert frame["citi_index"].iloc[0] == snapshot.citi_index
    assert len(frame) == len(cube.expiries()) * len(cube.tenors()) * len(cube.offsets())
