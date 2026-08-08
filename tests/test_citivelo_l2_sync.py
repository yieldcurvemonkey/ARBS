r"""The unified Citi L2 backfill CLI.

The family matcher gets its own class because the five suffixes overlap:
``-CITIVELO`` is a prefix of ``-CITIVELOEXCEL``, which is a suffix of
``-SWAPTIONVOL-CITIVELOEXCEL``. Getting that wrong routes a 244 MB minute asset
into the EOD family or a cube into the curve table, and the failure would be
silent - each family's ``local_dates`` would simply come back empty or, worse,
full of the wrong thing.

``TestVerifier`` mirrors the corruption self-test that is run against the real
production table, so the same guarantees are pinned in the fast gate.
"""

from __future__ import annotations

import datetime

import pytest

from scripts.citivelo_l2_sync import (
    FAMILY_BY_NAME,
    build_parser,
    family_for,
    human,
    plan_asset,
    verify_asset,
)
from tests.test_supabase_blob_blocks import (
    ASSET,
    D1,
    D2,
    D3,
    FakeBlobDB,
    _CubeSync,
    make_parquet,
    write_local,
)


class TestFamilyMatching:
    @pytest.mark.parametrize(
        "asset,expected",
        [
            ("USD-SOFR-1D-CITIVELO", "workbook"),
            ("USD-SOFR-1D-CITIVELOEXCEL", "eod"),
            ("EUR-ESTR-1D-CITIVELOEXCEL", "eod"),
            ("JPY-TONAR-1D-LCH-CITIVELOEXCELMIN", "minute"),
            ("USD-SOFR-1D-CITIVELOEXCELMIN", "minute"),
            ("USD-SOFR-1D-CITIVELOSTREAM", "stream"),
            ("USD-SWAPTIONVOL-CITIVELOEXCEL", "cube"),
            ("EUR-SWAPTIONVOL-CITIVELOEXCEL", "cube"),
        ],
    )
    def test_every_real_asset_lands_in_exactly_one_family(self, asset, expected):
        fam = family_for(asset)
        assert fam is not None and fam.name == expected
        matches = [f.name for f in FAMILY_BY_NAME.values() if f.matches(asset)]
        assert matches == [expected], f"{asset} matched {matches}"

    @pytest.mark.parametrize(
        "asset",
        [
            "USD-SOFR-1D",                # the shared ERIS asset
            "USD-SOFR-1D-ERISLIVE",       # ERIS, not Citi, despite looking similar
            "USD-SOFR-1D-Q12STIRT",
            "USD-OIS-Q12xM12STIRT-SERFFX-MIX23",
            "CAD-CORRA-Q8STIRT",
        ],
    )
    def test_non_citi_assets_are_not_claimed(self, asset):
        assert family_for(asset) is None

    def test_a_cube_is_never_routed_to_the_curve_table(self):
        """It ends '-CITIVELOEXCEL', which is the EOD suffix."""
        assert FAMILY_BY_NAME["eod"].matches("USD-SWAPTIONVOL-CITIVELOEXCEL") is False
        assert FAMILY_BY_NAME["cube"].matches("USD-SWAPTIONVOL-CITIVELOEXCEL") is True

    def test_a_minute_asset_is_never_routed_to_eod(self):
        """Sharing the key would have an EOD re-warm delete a day of minute curves."""
        assert FAMILY_BY_NAME["eod"].matches("USD-SOFR-1D-CITIVELOEXCELMIN") is False
        assert FAMILY_BY_NAME["workbook"].matches("USD-SOFR-1D-CITIVELOEXCELMIN") is False


class TestPlan:
    @pytest.fixture
    def scene(self, tmp_path):
        db = FakeBlobDB()
        sync = _CubeSync(tmp_path / "local", db)
        # D1 both, identical.  D2 local only.  D3 both, differing.
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
        remote_only = datetime.date(2026, 1, 8)
        write_local(other, ASSET, remote_only, make_parquet(vol=8.0))
        other.push_day(ASSET, remote_only)
        return sync, db, remote_only

    def test_identical_days_are_not_queued(self, scene):
        sync, _, remote_only = scene
        plan = plan_asset(sync, FAMILY_BY_NAME["cube"], ASSET, start=None, end=None, rewrite=False)
        assert D1 not in plan.to_push
        assert plan.to_push == [D2]
        assert plan.differing == [D3]
        assert plan.remote_only == [remote_only]
        assert plan.local_days == 3 and plan.remote_days == 3

    def test_differing_days_are_only_queued_with_rewrite(self, scene):
        sync, _, _ = scene
        plan = plan_asset(sync, FAMILY_BY_NAME["cube"], ASSET, start=None, end=None, rewrite=True)
        assert sorted(plan.to_push) == sorted([D2, D3])

    def test_plan_moves_no_payload(self, scene):
        """The resume primitive must cost a manifest, not a gigabyte."""
        sync, db, _ = scene
        db.payload_reads.clear()
        plan_asset(sync, FAMILY_BY_NAME["cube"], ASSET, start=None, end=None, rewrite=True)
        assert db.payload_reads == []

    def test_push_bytes_is_the_real_file_size(self, scene):
        sync, _, _ = scene
        plan = plan_asset(sync, FAMILY_BY_NAME["cube"], ASSET, start=None, end=None, rewrite=False)
        expected = next(sync.partition_dir(ASSET, D2).glob("*.parquet")).stat().st_size
        assert plan.push_bytes == expected

    def test_a_multi_file_partition_is_reported_not_pushed(self, tmp_path):
        db = FakeBlobDB()
        sync = _CubeSync(tmp_path / "local", db)
        write_local(sync, ASSET, D1, make_parquet(vol=1.0))
        write_local(sync, ASSET, D1, make_parquet(vol=2.0))
        plan = plan_asset(sync, FAMILY_BY_NAME["cube"], ASSET, start=None, end=None, rewrite=False)
        assert plan.to_push == []
        assert len(plan.unreadable) == 1

    def test_date_bounds_are_honoured(self, scene):
        sync, _, _ = scene
        plan = plan_asset(sync, FAMILY_BY_NAME["cube"], ASSET, start=D2, end=D2, rewrite=True)
        assert plan.local_days == 1 and plan.to_push == [D2]


class TestVerifier:
    """The hermetic mirror of the production self-test."""

    @pytest.fixture
    def scene(self, tmp_path):
        db = FakeBlobDB()
        sync = _CubeSync(tmp_path / "local", db)
        for day in (D1, D2):
            write_local(sync, ASSET, day, make_parquet(vol=float(day.day)))
            sync.push_day(ASSET, day)
        return sync, db

    def test_clean_rows_verify_clean(self, scene):
        sync, _ = scene
        report = verify_asset(sync, ASSET, [D1, D2])
        assert report["bad"] == []
        assert report["checked"] == 2
        assert report["bytes"] > 0

    def test_a_truncated_payload_is_caught(self, scene):
        sync, db = scene
        db.truncate_payload(D1, ASSET, keep=30)
        bad = verify_asset(sync, ASSET, [D1, D2])["bad"]
        assert len(bad) == 1 and "hash" in bad[0]["problem"]

    def test_a_scrambled_sha_column_is_caught(self, scene):
        sync, db = scene
        db.scramble_sha(D1, ASSET)
        bad = verify_asset(sync, ASSET, [D1, D2])["bad"]
        assert len(bad) == 1 and "hash" in bad[0]["problem"]

    def test_self_consistent_but_wrong_content_is_caught(self, scene):
        """Right sha for the wrong bytes: only the local comparison sees this."""
        from Caching.supabase_blob_blocks import sha256_of

        sync, db = scene
        other = make_parquet(vol=999.0)
        db.rows[(D1, ASSET)].update(payload=other, sha256=sha256_of(other))
        bad = verify_asset(sync, ASSET, [D1, D2])["bad"]
        assert len(bad) == 1 and "differ from the local file" in bad[0]["problem"]

    def test_a_lying_row_count_is_caught(self, scene):
        sync, db = scene
        db.rows[(D1, ASSET)]["row_count"] = 9999
        bad = verify_asset(sync, ASSET, [D1, D2])["bad"]
        assert len(bad) == 1 and "row_count" in bad[0]["problem"]

    def test_a_missing_remote_day_is_caught(self, scene):
        sync, db = scene
        del db.rows[(D2, ASSET)]
        bad = verify_asset(sync, ASSET, [D1, D2])["bad"]
        assert len(bad) == 1 and "absent from L2" in bad[0]["problem"]

    def test_unreadable_parquet_is_caught(self, scene):
        """Bytes that hash correctly and match locally but are not parquet."""
        from Caching.supabase_blob_blocks import sha256_of

        sync, db = scene
        junk = b"not parquet at all" * 8
        db.rows[(D1, ASSET)].update(payload=junk, sha256=sha256_of(junk))
        # make the local file match so the comparison passes and parsing is reached
        for f in sync.partition_dir(ASSET, D1).glob("*.parquet"):
            f.unlink()
        (sync.partition_dir(ASSET, D1) / f"{sha256_of(junk)}.parquet").write_bytes(junk)
        problems = [b["problem"] for b in verify_asset(sync, ASSET, [D1, D2])["bad"]]
        assert any("unreadable parquet" in p for p in problems), problems

    def test_one_damaged_local_day_does_not_hide_the_others(self, scene):
        """A local read that raises must be a finding, not the end of the run."""
        sync, db = scene
        for f in sync.partition_dir(ASSET, D1).glob("*.parquet"):
            f.write_bytes(b"truncated")
        db.truncate_payload(D2, ASSET, keep=30)
        bad = verify_asset(sync, ASSET, [D1, D2])["bad"]
        days = {b["day"] for b in bad}
        assert days == {D1.isoformat(), D2.isoformat()}, bad


class TestCli:
    def test_push_requires_yes(self):
        args = build_parser().parse_args(["push", "--families", "cube"])
        assert args.yes is False

    def test_plan_has_no_yes_flag_because_it_writes_nothing(self):
        args = build_parser().parse_args(["plan"])
        assert not hasattr(args, "yes")

    def test_families_is_repeatable_and_validated(self):
        args = build_parser().parse_args(["plan", "--families", "eod", "--families", "cube"])
        assert args.families == ["eod", "cube"]
        with pytest.raises(SystemExit):
            build_parser().parse_args(["plan", "--families", "nonsense"])

    def test_default_workers_is_bounded(self):
        """One engine, one process: connections are workers+2, not 9 per worker."""
        args = build_parser().parse_args(["push"])
        assert args.workers == 4


def test_human_readable_bytes():
    assert human(0) == "0.0 B"
    assert human(1536) == "1.5 KB"
    assert human(717 * 1024 * 1024).endswith("MB")
