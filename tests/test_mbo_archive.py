"""Archive indexing tests.

Built against synthetic zips so they run in the fast gate.  The real archives on
``D:\\`` are exercised by the marked test at the end, which is skipped when the
drive is absent.
"""
from __future__ import annotations

import datetime
import os
import zipfile

import pytest

from RVUtils.MBO.archive import ARCHIVE_ROOTS, MboArchive, session_key

D1 = datetime.date(2026, 5, 5)
D2 = datetime.date(2026, 5, 6)


def _archive(tmp_path, product, dates, zip_name="GLBX-20260808-FAKE.zip", size=32):
    d = tmp_path / f"{product.lower()}_mbo"
    d.mkdir(exist_ok=True)
    with zipfile.ZipFile(d / zip_name, "w") as z:
        z.writestr("metadata.json", "{}")
        z.writestr("condition.json", "{}")
        for dt in dates:
            z.writestr(f"glbx-mdp3-{dt}.mbo.dbn.zst", b"\x00" * size)
    return str(d)


# --------------------------------------------------------------------------- #
# indexing
# --------------------------------------------------------------------------- #

def test_sessions_lists_one_row_per_day(tmp_path):
    root = _archive(tmp_path, "ZN", ["20260505", "20260506"])
    s = MboArchive([root]).sessions()
    assert list(s["product"]) == ["ZN", "ZN"]
    assert list(s["date"]) == [D1, D2]
    assert (s["member_bytes"] == 32).all()


def test_the_json_members_are_not_mistaken_for_sessions(tmp_path):
    root = _archive(tmp_path, "ZN", ["20260505"])
    assert len(MboArchive([root]).sessions()) == 1


def test_sessions_merges_two_zips_of_one_product(tmp_path):
    """SR3 arrives as two batch downloads covering different date ranges."""
    root = _archive(tmp_path, "SR3", ["20260601"], zip_name="a.zip")
    _archive(tmp_path, "SR3", ["20260602"], zip_name="b.zip")
    s = MboArchive([root]).sessions()
    assert len(s) == 2
    assert s["zip_path"].nunique() == 2
    assert s["date"].is_monotonic_increasing


def test_duplicate_session_across_zips_raises_rather_than_picking_one(tmp_path):
    """Preferring one silently would make the build depend on listing order."""
    root = _archive(tmp_path, "ZN", ["20260601"], zip_name="a.zip")
    _archive(tmp_path, "ZN", ["20260601"], zip_name="b.zip")
    with pytest.raises(ValueError, match="appears in more than one archive"):
        MboArchive([root]).sessions()


def test_a_missing_root_is_skipped_not_fatal(tmp_path):
    root = _archive(tmp_path, "ZN", ["20260505"])
    s = MboArchive([root, str(tmp_path / "nope_mbo")]).sessions()
    assert len(s) == 1


def test_an_empty_index_is_an_empty_frame_with_the_right_columns(tmp_path):
    s = MboArchive([str(tmp_path / "nothing")]).sessions()
    assert s.empty
    assert list(s.columns) == ["product", "date", "zip_path", "member", "member_bytes"]


def test_products_and_dates_helpers(tmp_path):
    root = _archive(tmp_path, "ZN", ["20260505", "20260506"])
    a = MboArchive([root])
    assert a.products() == ["ZN"]
    assert a.dates("ZN") == [D1, D2]
    assert a.dates("SR3") == []


def test_session_key_is_stable_and_sortable():
    assert session_key("ZN", datetime.date(2026, 7, 14)) == "ZN/2026-07-14"


def test_default_roots_cover_every_registered_product():
    from RVUtils.MBO.products import PRODUCTS
    tails = {r.rsplit("/", 1)[-1] for r in ARCHIVE_ROOTS}
    assert tails == {f"{p.lower()}_mbo" for p in PRODUCTS}


# --------------------------------------------------------------------------- #
# extraction
# --------------------------------------------------------------------------- #

def test_open_session_yields_a_readable_path(tmp_path):
    root = _archive(tmp_path, "ZN", ["20260505"], size=64)
    a = MboArchive([root])
    with a.open_session("ZN", D1, scratch=str(tmp_path / "scratch")) as path:
        assert os.path.getsize(path) == 64


def test_open_session_removes_the_scratch_copy_by_default(tmp_path):
    root = _archive(tmp_path, "ZN", ["20260505"])
    a = MboArchive([root])
    with a.open_session("ZN", D1, scratch=str(tmp_path / "s")) as path:
        held = path
    assert not os.path.exists(held)


def test_open_session_can_keep_the_copy_for_a_second_tier(tmp_path):
    root = _archive(tmp_path, "ZN", ["20260505"])
    a = MboArchive([root])
    with a.open_session("ZN", D1, scratch=str(tmp_path / "s"), keep=True) as p1:
        pass
    assert os.path.exists(p1)
    with a.open_session("ZN", D1, scratch=str(tmp_path / "s")) as p2:
        assert p2 == p1


def test_open_session_re_extracts_a_truncated_scratch_copy(tmp_path):
    root = _archive(tmp_path, "ZN", ["20260505"], size=128)
    a = MboArchive([root])
    scratch = str(tmp_path / "s")
    with a.open_session("ZN", D1, scratch=scratch, keep=True) as p:
        pass
    with open(p, "wb") as fh:            # a killed extraction leaves a short file
        fh.write(b"\x00" * 5)
    with a.open_session("ZN", D1, scratch=scratch) as p2:
        assert os.path.getsize(p2) == 128


def test_open_session_raises_for_an_unknown_date(tmp_path):
    root = _archive(tmp_path, "ZN", ["20260505"])
    with pytest.raises(KeyError, match="ZN/2026-05-06"):
        with MboArchive([root]).open_session("ZN", D2):
            pass


# --------------------------------------------------------------------------- #
# the real archives
# --------------------------------------------------------------------------- #

@pytest.mark.slow
@pytest.mark.skipif(not os.path.isdir("D:/zn_mbo"), reason="archives not present")
def test_the_real_archives_index_to_the_expected_shape():
    s = MboArchive().sessions()
    counts = s.groupby("product").size().to_dict()
    assert counts["SR3"] == 53
    for root in ("ZT", "ZF", "ZN", "TN", "ZB", "UB"):
        assert counts[root] == 79, f"{root} has {counts.get(root)} sessions"
    assert s["date"].min() == datetime.date(2026, 5, 7)
    assert s["date"].max() == datetime.date(2026, 8, 6)
