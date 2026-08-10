r"""Which minute the ``-CITIVELOEXCELMIN`` read path serves, and whether it says so.

The four failure modes these pin, all of which were silent:

1. ``(stamps - wanted).abs().argmin()`` is nearest in EITHER direction, so a
   request can be answered by a snapshot from *after* it. For valuation that is
   a rounding choice; for inferring a trade's direction from where it printed
   relative to mid it is circular, because a post-trade curve can already carry
   the print's own impact.
2. There was no staleness bound on this path at all. The class's existing
   ``_assert_snapshot_fresh`` was wired into the two sibling paths and not this
   one - and its twelve-hour default would not have helped anyway.
3. The ``(D, D-1, D+1)`` window plus (1) plus (2) lets a thin partition resolve
   to *yesterday's or tomorrow's* curve.
4. ``resolve_request`` reads exact midnight as END OF DAY, and the direction
   classifier's own ``snap_timestamp`` produces exact midnight for every print in
   the 00:01 ET minute - so those requests skip the minute store entirely and are
   answered with that day's close.

Two of these tests (``test_the_shipped_argmin_rule_can_pick_the_future`` and
``test_the_shipped_window_spans_neighbouring_days``) are written against the
*expression that shipped*, not against the new code, so they reproduce the bugs
independently of the fix and keep doing so if the fix is reverted.
"""

from __future__ import annotations

import datetime
import zoneinfo

import numpy as np
import pandas as pd
import pytest

from MDP.IRSwaps.CITIVELO_EXCEL import day_cache
from MDP.IRSwaps.CITIVELO_EXCEL.snapshot_policy import (
    SnapshotMiss,
    SnapshotPolicy,
    reset_warnings,
    select_snapshot,
)
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

ET = zoneinfo.ZoneInfo("America/New_York")
CURVE = "USD-SOFR-1D"
ASSET = f"{CURVE}-CITIVELOEXCELMIN"
DAY = datetime.date(2026, 6, 10)


# --------------------------------------------------------------------------- #
#                                  fixtures                                   #
# --------------------------------------------------------------------------- #


class FakeStore:
    """A CurveStore with hand-placed minute snapshots.

    Real directories with a real (empty) parquet file per populated day, because
    ``day_cache`` builds its cache signature from ``os.scandir`` + ``stat`` on the
    partition and treats a directory with no parquet as a cold day. The frames
    themselves are returned from memory - the point of the fixture is which row
    is chosen, not how it is stored.
    """

    def __init__(self, base, frames):
        self._base = base
        self._frames = frames
        for (asset, day) in frames:
            d = self.raw_partition_dir(asset, day)
            d.mkdir(parents=True, exist_ok=True)
            (d / "part.parquet").write_bytes(b"x")
        self.reconstructed = []

    @property
    def base_dir(self):
        return self._base

    def raw_partition_dir(self, asset, day):
        return self._base / "raw" / f"asset={asset}" / f"date={day.isoformat()}"

    def has_day(self, asset, day):
        return (asset, day) in self._frames

    def read_raw_day(self, asset, day):
        return self._frames.get((asset, day))

    def reconstruct_curves_batch(self, frame, cfg=None, max_workers=1):
        self.reconstructed.append(list(frame["timestamp_utc"]))
        return {str(t): f"CURVE@{t}" for t in frame["timestamp_utc"]}


def _frame(stamps_et):
    """One day's rows, stamped in UTC the way the store writes them."""
    utc = [pd.Timestamp(s, tz=ET).tz_convert("UTC") for s in stamps_et]
    return pd.DataFrame({"timestamp_utc": utc, "payload": range(len(utc))})


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """The default layout: a normal session on DAY, and a session on DAY-1."""
    frames = {
        (ASSET, DAY): _frame(
            [f"2026-06-10 {h:02d}:{m:02d}" for h in (10,) for m in (0, 5, 10)]
        ),
        (ASSET, DAY - datetime.timedelta(days=1)): _frame(
            ["2026-06-09 19:00", "2026-06-09 20:00"]
        ),
    }
    return _install(tmp_path, monkeypatch, frames)


def _install(tmp_path, monkeypatch, frames):
    day_cache.reset_day_cache()
    reset_warnings()
    fake = FakeStore(tmp_path, frames)
    monkeypatch.setattr(IRSwapsMDP, "_get_curve_store", staticmethod(lambda: fake))
    # Fixings resolve through the tag cache and are irrelevant to which row is
    # picked; stub them so the test cannot touch Excel or the network.
    monkeypatch.setattr(
        IRSwapsMDP,
        "_citivelo_excel_store_fixings",
        lambda self, **kw: pd.Series(dtype="float64"),
    )
    # `bulk_get_data` does NOT go through the store's own batch reconstructor -
    # it calls the CurveStore CLASS method directly, by position. Without this
    # the fixture's rows raise KeyError('node_dates'), the bulk window branch
    # takes its `except Exception` fallback, and every bulk assertion silently
    # becomes an assertion about the single-point path instead. That is exactly
    # how the agreement test below was vacuous until a review pointed at it.
    from Caching.curve_store import CurveStore

    monkeypatch.setattr(
        CurveStore,
        "reconstruct_curve",
        staticmethod(lambda row, cfg=None: f"CURVE@{row['timestamp_utc']}"),
    )
    return fake


@pytest.fixture()
def mdp():
    return IRSwapsMDP(source="citivelo_excel_rl")


def _load(mdp, when, policy=None):
    return mdp._load_citivelo_excel_minute_store_point(
        curve_name=CURVE, timestamp=when, policy=policy
    )


def _served(curve):
    return pd.Timestamp(curve.meta()["timestamp"]).tz_convert(ET)


# --------------------------------------------------------------------------- #
#          the bugs, reproduced against the expression that shipped           #
# --------------------------------------------------------------------------- #


def test_the_shipped_argmin_rule_can_pick_the_future():
    """``(stamps - wanted).abs().values.argmin()`` - the line as it shipped.

    Reproduced here directly rather than through the loader, so that it keeps
    demonstrating the defect no matter what the loader is changed to.
    """
    stamps = pd.Series(
        pd.to_datetime(
            [pd.Timestamp(s, tz=ET).tz_convert("UTC")
             for s in ("2026-06-10 10:00", "2026-06-10 10:05")]
        )
    )
    wanted = pd.Timestamp("2026-06-10 10:04", tz=ET)
    position = int((stamps - wanted.tz_convert("UTC")).abs().values.argmin())
    assert pd.Timestamp(stamps.iloc[position]) > wanted, (
        "the shipped rule is supposed to be able to serve the future; if this "
        "fails the fixture no longer reproduces the bug"
    )


def test_the_shipped_window_spans_neighbouring_days():
    """A thin day plus nearest-in-either-direction reaches into a neighbour.

    The window is ``(D, D-1, D+1)`` and the search has no notion of "the day I
    asked for", so an empty D resolves against D-1 or D+1 with nothing raised.
    """
    stamps = pd.Series(
        pd.to_datetime(
            [pd.Timestamp(s, tz=ET).tz_convert("UTC")
             for s in ("2026-06-09 20:00", "2026-06-11 05:00")]
        )
    )
    wanted = pd.Timestamp("2026-06-10 14:30", tz=ET)
    position = int((stamps - wanted.tz_convert("UTC")).abs().values.argmin())
    served = pd.Timestamp(stamps.iloc[position]).tz_convert(ET)
    assert served.date() != wanted.date()


# --------------------------------------------------------------------------- #
#                     1. served from after the request                        #
# --------------------------------------------------------------------------- #


def test_default_policy_still_serves_the_nearest_snapshot_either_way(store, mdp):
    """The default must not move a single number for existing callers."""
    curve = _load(mdp, datetime.datetime(2026, 6, 10, 10, 4, tzinfo=ET))
    assert _served(curve) == pd.Timestamp("2026-06-10 10:05", tz=ET)


def test_a_future_snapshot_is_reported_even_on_the_default_path(store, mdp):
    """Unchanged behaviour, no longer silent - this is what makes it detectable."""
    meta = _load(mdp, datetime.datetime(2026, 6, 10, 10, 4, tzinfo=ET)).meta()
    assert meta["snapshot_served_from_future"] is True
    assert meta["snapshot_lag_signed_seconds"] == -60.0
    assert meta["snapshot_lag_seconds"] == 60.0, "the absolute field must stay absolute"
    assert meta["snapshot_served_utc"] == "2026-06-10T14:05:00+00:00"
    assert meta["snapshot_requested_utc"] == "2026-06-10T14:04:00+00:00"


def test_asof_never_serves_a_snapshot_from_after_the_request(store, mdp):
    curve = _load(mdp, datetime.datetime(2026, 6, 10, 10, 4, tzinfo=ET),
                  policy=SnapshotPolicy.strict(minutes=60))
    assert _served(curve) == pd.Timestamp("2026-06-10 10:00", tz=ET)
    meta = curve.meta()
    assert meta["snapshot_served_from_future"] is False
    assert meta["snapshot_lag_signed_seconds"] == 240.0


def test_nearest_with_allow_future_false_misses_rather_than_jumping_back(store, mdp):
    """``allow_future=False`` is a veto, not a silent switch to the other rule.

    A caller that says "nearest, but never the future" and is handed the
    preceding snapshot instead would be getting ``asof`` under another name -
    and would not know its request had been reinterpreted.
    """
    policy = SnapshotPolicy(method="nearest", allow_future=False, on_miss="raise")
    with pytest.raises(SnapshotMiss):
        _load(mdp, datetime.datetime(2026, 6, 10, 10, 4, tzinfo=ET), policy=policy)


# --------------------------------------------------------------------------- #
#                       2. and 3. tolerance and the window                    #
# --------------------------------------------------------------------------- #


def test_the_pm1_day_window_resolves_to_a_different_calendar_day(tmp_path, monkeypatch, mdp):
    """An empty requested day silently answers out of a neighbouring one."""
    _install(tmp_path, monkeypatch,
             {(ASSET, DAY - datetime.timedelta(days=1)): _frame(["2026-06-09 20:00"])})
    meta = _load(mdp, datetime.datetime(2026, 6, 10, 14, 30, tzinfo=ET)).meta()
    assert meta["snapshot_same_local_date"] is False
    assert meta["snapshot_served_utc"].startswith("2026-06-10T00:00")  # 20:00 ET on the 9th


def test_a_strict_caller_is_told_instead(tmp_path, monkeypatch, mdp):
    _install(tmp_path, monkeypatch,
             {(ASSET, DAY - datetime.timedelta(days=1)): _frame(["2026-06-09 20:00"])})
    with pytest.raises(SnapshotMiss, match="no snapshot satisfies"):
        _load(mdp, datetime.datetime(2026, 6, 10, 14, 30, tzinfo=ET),
              policy=SnapshotPolicy.strict(minutes=5))


def test_a_lenient_caller_with_a_tolerance_gets_none_not_an_exception(tmp_path, monkeypatch, mdp):
    """``on_miss="none"`` keeps the degrade-to-live-build contract intact."""
    _install(tmp_path, monkeypatch,
             {(ASSET, DAY - datetime.timedelta(days=1)): _frame(["2026-06-09 20:00"])})
    policy = SnapshotPolicy(method="asof", max_lag=datetime.timedelta(minutes=5))
    assert _load(mdp, datetime.datetime(2026, 6, 10, 14, 30, tzinfo=ET), policy=policy) is None


def test_a_lenient_policy_still_reaches_the_live_build_through_the_dispatch(
    tmp_path, monkeypatch, mdp
):
    """The loader returning ``None`` is not the whole contract - the dispatch is.

    A backward-only-but-lenient policy documents that a miss falls through to the
    live build. The terminal "this should be unreachable" guard was keyed on
    ``is_legacy``, which made that combination impossible to use: the docstring
    promised a fall-through and the dispatch raised. Found by review; the guard
    is keyed on ``on_miss`` now.
    """
    _install(tmp_path, monkeypatch,
             {(ASSET, DAY - datetime.timedelta(days=1)): _frame(["2026-06-09 20:00"])})
    monkeypatch.setattr(
        IRSwapsMDP, "_get_citivelo_excel_fetcher",
        lambda self, **kw: (_ for _ in ()).throw(RuntimeError("reached the live path")),
    )
    policy = SnapshotPolicy(method="asof", max_lag=datetime.timedelta(minutes=5))
    with pytest.raises(RuntimeError, match="reached the live path"):
        mdp._build_citivelo_excel_curve(
            curve_name=CURVE,
            timestamp=datetime.datetime(2026, 6, 10, 14, 30, tzinfo=ET),
            kwargs={"snapshot_policy": policy},
        )


def test_the_tolerance_that_matters_is_minutes_not_the_twelve_hour_guard(store, mdp):
    """Wiring in the existing guard would not have caught this.

    ``ARBS_MAX_CURVE_STALENESS_HOURS`` defaults to 12 h, so a request three
    hours past the end of the session passes it. The whole point of the policy's
    ``max_lag`` is that the useful bound here is measured in minutes.
    """
    late = datetime.datetime(2026, 6, 10, 13, 10, tzinfo=ET)   # 3 h 10 m past 10:10
    IRSwapsMDP._assert_snapshot_fresh(
        source="probe", requested=late,
        snapshot_utc=pd.Timestamp("2026-06-10 10:10", tz=ET).tz_convert("UTC"),
    )  # the shipped guard: no complaint
    with pytest.raises(SnapshotMiss):
        _load(mdp, late, policy=SnapshotPolicy.strict(minutes=5))


# --------------------------------------------------------------------------- #
#                4. exact midnight is end-of-day, not 00:00                   #
# --------------------------------------------------------------------------- #


def test_the_classifier_snap_lands_on_midnight_for_an_00_01_print():
    """Not hypothetical: this is production's own snap rule."""
    from SDRUtils.stir_flow.pricing import snap_timestamp

    printed = pd.Timestamp("2026-06-10 00:01:30", tz=ET)
    snap = snap_timestamp(printed, None)
    assert (snap.hour, snap.minute) == (0, 0)


def test_a_midnight_request_under_a_strict_policy_refuses_the_close(store, mdp):
    """It would otherwise be answered by that day's CLOSE - hours after the print."""
    with pytest.raises(SnapshotMiss, match="END OF DAY"):
        mdp._build_citivelo_excel_curve(
            curve_name=CURVE,
            timestamp=pd.Timestamp("2026-06-10 00:00", tz=ET),
            kwargs={"snapshot_policy": SnapshotPolicy.strict(minutes=5)},
        )


def test_a_midnight_request_without_a_policy_still_routes_to_the_eod_store(store, mdp, monkeypatch):
    seen = []
    monkeypatch.setattr(
        IRSwapsMDP, "_load_citivelo_excel_curve_store_point",
        lambda self, **kw: seen.append(kw["trading_date"]) or "EOD",
    )
    got = mdp._build_citivelo_excel_curve(
        curve_name=CURVE, timestamp=pd.Timestamp("2026-06-10 00:00", tz=ET), kwargs={}
    )
    assert got == "EOD" and seen == [DAY]


# --------------------------------------------------------------------------- #
#                    no new silent fallback anywhere                          #
# --------------------------------------------------------------------------- #


def test_a_strict_miss_never_reaches_the_live_excel_build(tmp_path, monkeypatch, mdp):
    """The failure the whole change exists to prevent, asserted structurally.

    A strict miss that returned ``None`` would fall through to the live Excel
    fetcher - a different curve, built over COM, from a session a human has to
    be signed into.
    """
    _install(tmp_path, monkeypatch, {})
    monkeypatch.setattr(
        IRSwapsMDP, "_get_citivelo_excel_fetcher",
        lambda self, **kw: pytest.fail("a strict request reached the live Excel path"),
    )
    with pytest.raises(SnapshotMiss):
        mdp._build_citivelo_excel_curve(
            curve_name=CURVE,
            timestamp=datetime.datetime(2026, 6, 10, 10, 4, tzinfo=ET),
            kwargs={"snapshot_policy": SnapshotPolicy.strict(minutes=5)},
        )


def test_a_cold_store_without_a_policy_still_degrades_to_the_live_build(tmp_path, monkeypatch, mdp):
    _install(tmp_path, monkeypatch, {})
    monkeypatch.setattr(
        IRSwapsMDP, "_get_citivelo_excel_fetcher",
        lambda self, **kw: (_ for _ in ()).throw(RuntimeError("reached the live path")),
    )
    with pytest.raises(RuntimeError, match="reached the live path"):
        mdp._build_citivelo_excel_curve(
            curve_name=CURVE,
            timestamp=datetime.datetime(2026, 6, 10, 10, 4, tzinfo=ET),
            kwargs={},
        )


@pytest.mark.parametrize("flag", ["force_refresh", "ignore_cache", "no_curve_store"])
def test_a_policy_combined_with_a_store_bypass_is_a_contradiction(store, mdp, flag):
    with pytest.raises(ValueError, match="bypasses the store"):
        mdp._build_citivelo_excel_curve(
            curve_name=CURVE,
            timestamp=datetime.datetime(2026, 6, 10, 10, 4, tzinfo=ET),
            kwargs={"snapshot_policy": SnapshotPolicy.strict(), flag: True},
        )


def test_a_policy_on_a_source_that_cannot_honour_it_is_rejected():
    """The easiest way to run unprotected while believing otherwise.

    ``CurvePricer``'s default source is BARCHART_STIRF-RL, so a caller who sets
    ``curve_kwargs={"snapshot_policy": ...}`` and forgets to switch the source
    would silently get no protection at all.
    """
    other = IRSwapsMDP(source="BARCHART_STIRF-RL")
    with pytest.raises(ValueError, match="never reads it"):
        other._get_curve(
            "USD-SOFR-1D-Q12xM12STIRT",
            datetime.datetime(2026, 6, 10, 10, 4, tzinfo=ET),
            kwargs={"snapshot_policy": SnapshotPolicy.strict()},
        )


def test_a_non_policy_object_is_rejected_rather_than_ignored(store, mdp):
    """Reading a policy the caller did not set is how "I am protected" goes wrong."""
    with pytest.raises(TypeError, match="must be a"):
        mdp._build_citivelo_excel_curve(
            curve_name=CURVE,
            timestamp=datetime.datetime(2026, 6, 10, 10, 4, tzinfo=ET),
            kwargs={"snapshot_policy": {"method": "asof"}},
        )


# --------------------------------------------------------------------------- #
#                       the two guards must not drift                         #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("lag_s", [-600, -60, 0, 59, 60, 61, 300, 3600, 43200, 50000])
@pytest.mark.parametrize("limit_s", [None, 60, 300, 3600])
@pytest.mark.parametrize("allow_future", [True, False])
def test_select_snapshot_and_assert_snapshot_fresh_agree(lag_s, limit_s, allow_future):
    """One definition of "acceptable lag", pinned across the two mechanisms.

    ``select_snapshot`` decides softly (returns ``None``) because the read path
    must be able to degrade; ``_assert_snapshot_fresh`` decides loudly. They are
    allowed to differ in *how* they report, never in *what* they accept.
    """
    requested = pd.Timestamp("2026-06-10 14:00", tz="UTC")
    served = requested - pd.Timedelta(seconds=lag_s)
    limit = None if limit_s is None else datetime.timedelta(seconds=limit_s)
    policy = SnapshotPolicy(method="nearest", max_lag=limit, allow_future=allow_future)

    accepted_by_policy = (
        select_snapshot(np.array([served.value], dtype=np.int64), requested.value, policy)
        is not None
    )
    try:
        IRSwapsMDP._assert_snapshot_fresh(
            source="probe", requested=requested, snapshot_utc=served,
            limit=limit, allow_future=allow_future,
        )
        accepted_by_guard = True
    except RuntimeError:
        accepted_by_guard = False

    assert accepted_by_policy == accepted_by_guard, (
        f"lag={lag_s}s limit={limit_s}s allow_future={allow_future}: "
        f"policy said {accepted_by_policy}, guard said {accepted_by_guard}"
    )


def test_the_shipped_guard_is_blind_to_a_future_snapshot():
    """Documents *why* a tolerance alone was never going to be enough."""
    requested = pd.Timestamp("2026-06-10 14:00", tz="UTC")
    future = requested + pd.Timedelta(hours=3)
    IRSwapsMDP._assert_snapshot_fresh(  # no limit is small enough to catch this
        source="probe", requested=requested, snapshot_utc=future,
        limit=datetime.timedelta(seconds=0),
    )
    with pytest.raises(RuntimeError, match="AFTER the requested"):
        IRSwapsMDP._assert_snapshot_fresh(
            source="probe", requested=requested, snapshot_utc=future, allow_future=False,
        )


def test_the_default_limit_is_still_the_env_var(monkeypatch):
    """``limit=None`` means unbounded; omitting it means the twelve-hour guard.

    Conflating those two would silently give every existing caller no bound at
    all, or give a caller who asked for none the twelve hours.
    """
    monkeypatch.setenv("ARBS_MAX_CURVE_STALENESS_HOURS", "1")
    requested = pd.Timestamp("2026-06-10 14:00", tz="UTC")
    stale = requested - pd.Timedelta(hours=2)
    with pytest.raises(RuntimeError, match="stale"):
        IRSwapsMDP._assert_snapshot_fresh(source="probe", requested=requested, snapshot_utc=stale)
    IRSwapsMDP._assert_snapshot_fresh(
        source="probe", requested=requested, snapshot_utc=stale, limit=None
    )


# --------------------------------------------------------------------------- #
#                    the two read paths must not drift either                 #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "policy", [None, SnapshotPolicy.strict(minutes=30), SnapshotPolicy(method="asof")]
)
def test_bulk_serves_the_same_snapshot_as_the_single_point_loader(store, mdp, policy):
    wants = [
        datetime.datetime(2026, 6, 10, 10, 4, tzinfo=ET),   # nearest is in the future
        datetime.datetime(2026, 6, 10, 10, 0, tzinfo=ET),   # exact
        datetime.datetime(2026, 6, 10, 10, 7, tzinfo=ET),   # nearest is behind
        datetime.datetime(2026, 6, 10, 13, 0, tzinfo=ET),   # past the end of the session
        datetime.datetime(2026, 6, 10, 2, 0, tzinfo=ET),    # before it starts
    ]
    request = {} if policy is None else {"snapshot_policy": policy}

    # Non-vacuity guard. The bulk window branch degrades to per-point on any
    # exception, and a per-point fallback would make every assertion below a
    # tautology - it would be comparing the single-point loader with itself.
    per_point = []
    real_get_data = IRSwapsMDP.get_data
    mdp_cls = type(mdp)
    monkeypatch_target = []

    def _spy(self, req):
        per_point.append(req.get("timestamp"))
        return real_get_data(self, req)

    mdp_cls.get_data = _spy
    monkeypatch_target.append(True)
    try:
        bulk = mdp._bulk_citivelo_excel_curves(
            curve_name=CURVE, timestamps=wants, request=dict(request),
            ignore_cache=False, n_jobs=1,
        )
    finally:
        mdp_cls.get_data = real_get_data

    served_any = False
    for when in wants:
        try:
            single = _load(mdp, when, policy=policy)
        except SnapshotMiss:
            # The batch reports a data miss as an absent key; the single-point
            # path raises. Same selection, different reporting - pinned by
            # test_a_strict_data_miss_omits_the_key_rather_than_killing_the_batch.
            assert when not in bulk, when
            continue
        assert (when in bulk) == (single is not None), when
        if single is not None:
            served_any = True
            assert _served(bulk[when]) == _served(single), when
            assert when not in per_point, (
                f"{when} was served by the per-point fallback, so this comparison "
                "says nothing about the batch's own selection"
            )
    assert served_any, "no request was served, so this test compared nothing"


def test_a_strict_data_miss_omits_the_key_rather_than_killing_the_batch(store, mdp, caplog):
    """The two paths select identically and REPORT differently, on purpose.

    2.4 % of tape minutes have no snapshot inside a one-minute tolerance, so a
    batch that raised on the first of them would be unusable for exactly the
    research this policy exists to serve. Absence from a dict keyed by the
    caller's own timestamps is unambiguous per request; what it cannot convey is
    how many, so the count is logged.
    """
    import logging

    served = datetime.datetime(2026, 6, 10, 10, 4, tzinfo=ET)
    missed = datetime.datetime(2026, 6, 10, 13, 0, tzinfo=ET)   # 2h50m past the last stamp
    with caplog.at_level(logging.WARNING, logger="MDP.IRSwaps.citivelo_excel"):
        out = mdp._bulk_citivelo_excel_curves(
            curve_name=CURVE, timestamps=[served, missed],
            request={"snapshot_policy": SnapshotPolicy.strict(minutes=30)},
            ignore_cache=False, n_jobs=1,
        )
    assert served in out and missed not in out
    assert any("ABSENT from the result" in r.message for r in caplog.records)

    # ... and the single-point path still raises for the same request, because a
    # caller who asked one question gets an answer or an exception.
    with pytest.raises(SnapshotMiss):
        _load(mdp, missed, policy=SnapshotPolicy.strict(minutes=30))


def test_bulk_refuses_a_midnight_request_under_a_strict_policy(store, mdp):
    """The batch buckets EOD requests in its own pass - and used to serve them.

    An exact-midnight stamp is what ``snap_timestamp`` produces for every 00:01
    ET print, so this is the sixteen-hour lookahead arriving through the door the
    single-point dispatch already guards. The agreement test above could not see
    it, because every timestamp in it is intraday.
    """
    with pytest.raises(SnapshotMiss, match="END OF DAY"):
        mdp._bulk_citivelo_excel_curves(
            curve_name=CURVE,
            timestamps=[
                datetime.datetime(2026, 6, 10, 10, 4, tzinfo=ET),
                pd.Timestamp("2026-06-10 00:00", tz=ET),
            ],
            request={"snapshot_policy": SnapshotPolicy.strict(minutes=5)},
            ignore_cache=False,
            n_jobs=1,
        )


def test_bulk_still_serves_a_midnight_request_without_a_policy(store, mdp, monkeypatch):
    monkeypatch.setattr(
        IRSwapsMDP, "_load_citivelo_excel_curve_store_point", lambda self, **kw: "EOD"
    )
    got = mdp._bulk_citivelo_excel_curves(
        curve_name=CURVE,
        timestamps=[pd.Timestamp("2026-06-10 00:00", tz=ET)],
        request={},
        ignore_cache=False,
        n_jobs=1,
    )
    assert list(got.values()) == ["EOD"]


def test_bulk_refuses_live_under_a_strict_policy(store, mdp):
    """"live" names no instant, so a lag bound cannot mean anything about it."""
    with pytest.raises(ValueError, match="names no instant"):
        mdp._bulk_citivelo_excel_curves(
            curve_name=CURVE, timestamps=["live"],
            request={"snapshot_policy": SnapshotPolicy.strict()},
            ignore_cache=False, n_jobs=1,
        )


def test_single_point_refuses_live_under_a_strict_policy(store, mdp):
    with pytest.raises(ValueError, match="names no instant"):
        mdp._build_citivelo_excel_curve(
            curve_name=CURVE, timestamp="live",
            kwargs={"snapshot_policy": SnapshotPolicy.strict()},
        )


@pytest.mark.parametrize("flag", ["force_refresh", "ignore_cache", "no_curve_store"])
def test_bulk_raises_the_same_contradiction_the_single_path_does(store, mdp, flag):
    """``_single`` swallows ValueError, so validating only there loses it.

    The observable difference would be a silently SHORT result dict - a batch
    that answered fewer requests than it was asked, with nothing raised.
    """
    with pytest.raises(ValueError, match="bypasses the store"):
        mdp._bulk_citivelo_excel_curves(
            curve_name=CURVE,
            timestamps=[datetime.datetime(2026, 6, 10, 10, 4, tzinfo=ET)],
            request={"snapshot_policy": SnapshotPolicy.strict(), flag: True},
            ignore_cache=False, n_jobs=1,
        )


def test_bulk_ignore_cache_argument_counts_as_a_bypass(store, mdp):
    """``ignore_cache`` arrives as an ARGUMENT here, not only in the request."""
    with pytest.raises(ValueError, match="bypasses the store"):
        mdp._bulk_citivelo_excel_curves(
            curve_name=CURVE,
            timestamps=[datetime.datetime(2026, 6, 10, 10, 4, tzinfo=ET)],
            request={"snapshot_policy": SnapshotPolicy.strict()},
            ignore_cache=True, n_jobs=1,
        )


def test_a_nat_stamp_is_skipped_rather_than_selected():
    """The one deliberate divergence from the expression this replaced.

    pandas' ``.abs().values.argmin()`` propagates NaT to int64 minimum and so
    picks the corrupt row, which then fails to reconstruct and takes the whole
    request down. It needs a null ``timestamp_utc`` in a partition, so it should
    never happen - but losing one row beats losing the request.
    """
    base = pd.Timestamp("2026-06-10 10:00", tz="UTC").value
    stamps = np.array([np.iinfo(np.int64).min, base, base + 300 * 10**9], dtype=np.int64)
    wanted = base + 60 * 10**9

    series = pd.Series(pd.to_datetime(stamps, utc=True))
    assert series.isna().any(), "fixture must actually contain NaT"
    assert int((series - pd.Timestamp(wanted, tz="UTC")).abs().values.argmin()) == 0, (
        "the shipped expression is supposed to select the NaT row"
    )

    got = select_snapshot(stamps, wanted, SnapshotPolicy.legacy())
    assert got is not None and got.position == 1

    assert select_snapshot(
        np.array([np.iinfo(np.int64).min], dtype=np.int64), wanted, SnapshotPolicy.legacy()
    ) is None


def test_select_snapshot_matches_the_expression_it_replaced():
    """The legacy policy must be the old line, not merely close to it."""
    rng = np.random.default_rng(7)
    base = pd.Timestamp("2026-06-10 00:00", tz="UTC").value
    for _ in range(200):
        stamps = np.sort(rng.integers(0, 86_400, size=40)).astype(np.int64) * 10**9 + base
        # Duplicates and an unsorted window are both real: partitions overlap
        # after a re-warm, and the window is built in (D, D-1, D+1) order.
        stamps = np.concatenate([stamps[5:], stamps[:5], stamps[:3]])
        wanted = int(base + int(rng.integers(0, 86_400)) * 10**9)
        series = pd.Series(pd.to_datetime(stamps, utc=True))
        expected = int((series - pd.Timestamp(wanted, tz="UTC")).abs().values.argmin())
        got = select_snapshot(stamps, wanted, SnapshotPolicy.legacy())
        assert got is not None and got.position == expected
