r"""The stream daemon's L2 modes.

``push_l2=True`` used to mean "re-INSERT the whole day's BYTEA on every poll".
``CurveStore.write_day`` re-pushes the entire day blob each call, so a per-minute
daemon's traffic grows quadratically through the session - the ERIS design doc
measures ~88 MB re-pushed per minute by end of day at 18k nodes. ``True`` now
means one indexed ROW per tick (the pattern ``eris_live_curve_service.py``
already uses) with the day blob pushed once at :meth:`flush_l2`. The old
behaviour is still reachable as ``"day"``, documented as a footgun.
"""

from __future__ import annotations

import datetime as dt

import pytest

from MDP.IRSwaps.CITIVELO_EXCEL.stream_daemon import (
    CitiVeloStreamDaemon,
    _normalise_l2_mode,
)


class TestModeParsing:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (None, "off"), (False, "off"), ("off", "off"), ("OFF", "off"),
            (True, "rows"), ("rows", "rows"),
            ("day", "day"), ("Day", "day"),
        ],
    )
    def test_accepted(self, value, expected):
        assert _normalise_l2_mode(value) == expected

    def test_true_means_rows_not_the_old_day_blob(self):
        """The change of meaning, pinned so it cannot drift back."""
        assert _normalise_l2_mode(True) == "rows"

    @pytest.mark.parametrize("value", ["yes", "1", "blob", "on", "daily"])
    def test_an_unrecognised_mode_raises(self, value):
        with pytest.raises(ValueError) as excinfo:
            _normalise_l2_mode(value)
        assert "not a recognised mode" in str(excinfo.value)


class _RecordingStore:
    def __init__(self):
        self.writes: list[dict] = []

    def write_day(self, asset, day, snapshots, *, overwrite=False, push_l2=False):
        self.writes.append(
            {"asset": asset, "day": day, "n": len(snapshots), "push_l2": push_l2}
        )
        return {"path": "x"}

    def has_day(self, asset, day):
        return False

    def read_raw_day(self, asset, day):
        return None


class _RecordingSync:
    def __init__(self, *, fail: bool = False):
        self.rows: list = []
        self.days: list = []
        self.fail = fail

    def upsert_snapshot_row(self, snap, curve_name):
        if self.fail:
            raise RuntimeError("pooler said no")
        self.rows.append((curve_name, snap.timestamp_utc))
        return True

    def push_day(self, curve_name, day):
        self.days.append((curve_name, day))
        return True


def _daemon(mode, store, sync):
    d = CitiVeloStreamDaemon(["USD-SOFR-1D"], client=object(), store=store, push_l2=mode)
    d._sync = sync
    return d


def _snapshot(day: dt.date):
    from Caching.curve_store import CurveSnapshot

    ts = dt.datetime.combine(day, dt.time(15, 0), tzinfo=dt.timezone.utc)
    return CurveSnapshot(
        timestamp_utc=ts,
        timestamp_local=ts,
        trading_date=day,
        session_minute=900,
        curve_name="USD-SOFR-1D-CITIVELOSTREAM",
        cfg_hash="",
        reference_key="USD-SOFR-1D",
        interpolation="log_linear",
        source_variant="CITIVELO_STREAM",
        node_dates=[day + dt.timedelta(days=1)],
        discount_factors=[0.999],
    )


class _FakeCurve:
    curve_name = "USD-SOFR-1D"
    asset = "USD-SOFR-1D-CITIVELOSTREAM"
    # run()'s return value reads these off every curve
    written = 0
    skipped = 0
    failed = 0
    cells: dict = {}

    def __init__(self):
        self.day_snapshots: dict = {}


class TestPersistRouting:
    def _persist(self, mode, *, sync=None):
        store = _RecordingStore()
        sync = sync if sync is not None else _RecordingSync()
        daemon = _daemon(mode, store, sync)
        curve = _FakeCurve()
        daemon.curves = {"USD-SOFR-1D": curve}
        day = dt.date(2026, 8, 6)
        snap = _snapshot(day)
        curve.day_snapshots.setdefault(day, []).append(snap)
        # drive the two lines _persist_snapshot runs after building the snapshot
        store.write_day(
            curve.asset, day, curve.day_snapshots[day],
            overwrite=True, push_l2=(daemon._l2_mode == "day"),
        )
        if daemon._l2_mode == "rows":
            daemon._upsert_row(curve, snap)
        return daemon, store, sync

    def test_off_writes_locally_and_publishes_nothing(self):
        daemon, store, sync = self._persist(False)
        assert store.writes[0]["push_l2"] is False
        assert sync.rows == [] and sync.days == []

    def test_rows_mode_upserts_a_row_and_does_not_push_the_day_blob(self):
        daemon, store, sync = self._persist(True)
        assert store.writes[0]["push_l2"] is False, "the per-poll day blob is back"
        assert len(sync.rows) == 1
        assert sync.days == []

    def test_day_mode_keeps_the_old_per_poll_blob(self):
        daemon, store, sync = self._persist("day")
        assert store.writes[0]["push_l2"] is True
        assert sync.rows == []

    def test_a_row_failure_does_not_propagate(self):
        """A daemon that dies because a pooler blinked is worse than a skipped row."""
        daemon, store, sync = self._persist(True, sync=_RecordingSync(fail=True))
        assert daemon._l2_row_failures == 1
        assert daemon._l2_rows == 0


class TestFlush:
    def test_flush_pushes_each_accumulated_day_once(self):
        store, sync = _RecordingStore(), _RecordingSync()
        daemon = _daemon(True, store, sync)
        curve = _FakeCurve()
        curve.day_snapshots = {dt.date(2026, 8, 5): [], dt.date(2026, 8, 6): []}
        daemon.curves = {"USD-SOFR-1D": curve}
        out = daemon.flush_l2()
        assert out["days"] == 2
        assert sorted(d for _, d in sync.days) == [dt.date(2026, 8, 5), dt.date(2026, 8, 6)]

    def test_flush_is_a_no_op_when_l2_is_off(self):
        store, sync = _RecordingStore(), _RecordingSync()
        daemon = _daemon(False, store, sync)
        curve = _FakeCurve()
        curve.day_snapshots = {dt.date(2026, 8, 6): []}
        daemon.curves = {"USD-SOFR-1D": curve}
        assert daemon.flush_l2()["days"] == 0
        assert sync.days == []

    def test_flush_is_a_no_op_in_day_mode_because_every_poll_already_pushed(self):
        store, sync = _RecordingStore(), _RecordingSync()
        daemon = _daemon("day", store, sync)
        curve = _FakeCurve()
        curve.day_snapshots = {dt.date(2026, 8, 6): []}
        daemon.curves = {"USD-SOFR-1D": curve}
        assert daemon.flush_l2()["days"] == 0

    def test_run_flushes_even_on_keyboard_interrupt(self, monkeypatch):
        """The one exit path that actually happens for a daemon."""
        store, sync = _RecordingStore(), _RecordingSync()
        daemon = _daemon(True, store, sync)
        curve = _FakeCurve()
        curve.day_snapshots = {dt.date(2026, 8, 6): []}
        daemon.curves = {"USD-SOFR-1D": curve}
        daemon._opened = True

        def _boom():
            raise KeyboardInterrupt

        monkeypatch.setattr(daemon, "open", lambda: {})
        monkeypatch.setattr(daemon, "poll_once", _boom)
        daemon.run(once=True, verbose=False)
        assert sync.days == [("USD-SOFR-1D-CITIVELOSTREAM", dt.date(2026, 8, 6))]
