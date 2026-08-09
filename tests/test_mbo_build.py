"""Build-runner tests.

The runner's job is to be resumable, bounded and honest: skip what is already
built at this engine version, refuse a build that would fill the drive, and
record a failed session as failed rather than letting one bad day stop the
other five hundred and fifty-two.
"""
from __future__ import annotations

import datetime
import zipfile

import pandas as pd
import pytest

from RVUtils.MBO.archive import MboArchive
from RVUtils.MBO.build import estimate_bytes, main, plan, workers_for
from RVUtils.MBO.store import manifest as mf

D1 = datetime.date(2026, 5, 5)
D2 = datetime.date(2026, 5, 6)


@pytest.fixture
def archive(tmp_path):
    d = tmp_path / "zn_mbo"
    d.mkdir()
    with zipfile.ZipFile(d / "batch.zip", "w") as z:
        for dt in ("20260505", "20260506"):
            z.writestr(f"glbx-mdp3-{dt}.mbo.dbn.zst", b"\x00" * 1_000_000)
    return MboArchive([str(d)])


# --------------------------------------------------------------------------- #
# worker sizing
# --------------------------------------------------------------------------- #

def test_worker_count_is_derived_from_session_size_not_core_count():
    """One SR3 session held whole is about 4 GB, so a 32-core host runs nine of
    them, not thirty-two."""
    assert workers_for(session_gb=4.0, free_ram_gb=64.0, cap=32) == 9


def test_a_small_session_is_capped_by_the_core_count():
    assert workers_for(session_gb=0.4, free_ram_gb=64.0, cap=16) == 16


def test_a_session_larger_than_memory_still_gets_one_worker():
    assert workers_for(session_gb=200.0, free_ram_gb=64.0, cap=32) == 1


def test_an_unknown_session_size_falls_back_to_the_cap():
    assert workers_for(session_gb=0.0, free_ram_gb=64.0, cap=7) == 7


# --------------------------------------------------------------------------- #
# planning and resume
# --------------------------------------------------------------------------- #

def test_plan_lists_every_session_when_nothing_is_built(tmp_path, archive):
    assert len(plan(str(tmp_path), archive)) == 2


def test_plan_skips_sessions_already_built_at_this_engine_version(tmp_path, archive):
    for kind in ("tob", "trades", "catalog"):
        mf.append(str(tmp_path), {
            "product": "ZN", "date": D1, "tier": "wide", "kind": kind,
            "engine_version": mf.ENGINE_VERSION, "status": "OK",
        })
    p = plan(str(tmp_path), archive)
    assert list(p["date"]) == [D2]


def test_plan_rebuilds_after_an_engine_bump(tmp_path, archive):
    for kind in ("tob", "trades", "catalog"):
        mf.append(str(tmp_path), {
            "product": "ZN", "date": D1, "tier": "wide", "kind": kind,
            "engine_version": "0.0.1-old", "status": "OK",
        })
    assert len(plan(str(tmp_path), archive)) == 2


def test_plan_filters_by_product_and_date(tmp_path, archive):
    assert len(plan(str(tmp_path), archive, products=["SR3"])) == 0
    assert len(plan(str(tmp_path), archive, dates=(D2, D2))) == 1


# --------------------------------------------------------------------------- #
# the disk guard
# --------------------------------------------------------------------------- #

def test_estimate_scales_with_source_size():
    small = pd.DataFrame({"member_bytes": [1_000_000]})
    big = pd.DataFrame({"member_bytes": [10_000_000]})
    assert estimate_bytes(big) == pytest.approx(10 * estimate_bytes(small))


def test_estimate_of_nothing_is_zero():
    assert estimate_bytes(pd.DataFrame({"member_bytes": []})) == 0.0


def test_a_build_that_would_exceed_the_budget_is_refused_before_it_starts(tmp_path,
                                                                         archive):
    """Running out of disk nine hours in is the failure this prevents."""
    with pytest.raises(RuntimeError, match="disk budget exceeded"):
        main([
            "--root", str(tmp_path / "store"),
            "--archive-roots", archive.roots[0],
            "--disk-budget-gb", "0.00000001",
        ])


def test_a_dry_run_builds_nothing(tmp_path, archive, capsys):
    rc = main([
        "--root", str(tmp_path / "store"),
        "--archive-roots", archive.roots[0],
        "--dry-run",
    ])
    assert rc == 0
    assert mf.read(str(tmp_path / "store")).empty


def test_nothing_to_build_is_success_not_an_error(tmp_path, capsys):
    rc = main([
        "--root", str(tmp_path / "store"),
        "--archive-roots", str(tmp_path / "empty_mbo"),
    ])
    assert rc == 0
    assert "nothing to build" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# failure handling
# --------------------------------------------------------------------------- #

def test_a_corrupt_session_records_a_failed_row_and_does_not_raise(tmp_path, archive):
    """The zip members here are zeroes, not DBN, so every session fails."""
    from RVUtils.MBO.build import build_session

    row = build_session(str(tmp_path / "store"), archive.roots, "ZN", D1)
    assert row["status"] == "FAILED"
    assert row["error"]

    log = mf.read(str(tmp_path / "store"))
    assert set(log["kind"]) == {"tob", "trades", "catalog"}
    assert (log["status"] == "FAILED").all()


def test_a_failed_session_is_still_pending_afterwards(tmp_path, archive):
    from RVUtils.MBO.build import build_session

    root = str(tmp_path / "store")
    build_session(root, archive.roots, "ZN", D1)
    assert D1 in list(plan(root, archive)["date"])


def test_a_failed_session_leaves_no_partial_store_files(tmp_path, archive):
    import os

    from RVUtils.MBO.build import build_session

    root = str(tmp_path / "store")
    build_session(root, archive.roots, "ZN", D1)
    leftovers = []
    for dirpath, _, files in os.walk(root):
        leftovers += [f for f in files if f.endswith(".part")]
    assert leftovers == []
