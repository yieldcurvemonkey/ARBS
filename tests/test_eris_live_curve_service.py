import datetime
import pytz
import pytest

from scripts import eris_live_curve_service as svc

ET = pytz.timezone("America/New_York")
UTC = pytz.UTC


def _et(y, m, d, hh, mm, ss=0):
    return ET.localize(datetime.datetime(y, m, d, hh, mm, ss))


def test_in_session_boundaries():
    # window is [SESSION_START_MIN, SESSION_END_MIN)
    assert svc.in_session(_et(2026, 7, 23, 8, 0), start_min=8 * 60, end_min=17 * 60) is True
    assert svc.in_session(_et(2026, 7, 23, 7, 59), start_min=8 * 60, end_min=17 * 60) is False
    assert svc.in_session(_et(2026, 7, 23, 17, 0), start_min=8 * 60, end_min=17 * 60) is False


def test_is_business_day():
    assert svc.is_business_day(datetime.date(2026, 7, 23)) is True     # Thursday
    assert svc.is_business_day(datetime.date(2026, 7, 25)) is False    # Saturday
    assert svc.is_business_day(datetime.date(2026, 7, 4)) is False     # Independence Day (observed context)


def test_should_persist_dedup_and_freshness():
    now = _et(2026, 7, 23, 14, 31)
    fresh_ts = _et(2026, 7, 23, 14, 30, 30)  # 30s old
    ok, _ = svc.should_persist(fresh_ts, now, datetime.date(2026, 7, 23), last_ts=None)
    assert ok is True
    # unchanged stamp -> skip
    ok, reason = svc.should_persist(fresh_ts, now, datetime.date(2026, 7, 23), last_ts=fresh_ts)
    assert ok is False and "unchanged" in reason
    # stale stamp (10 min old) -> skip
    stale = _et(2026, 7, 23, 14, 21)
    ok, reason = svc.should_persist(stale, now, datetime.date(2026, 7, 23), last_ts=None)
    assert ok is False and "stale" in reason
    # naive stamp -> skip
    ok, reason = svc.should_persist(datetime.datetime(2026, 7, 23, 14, 30), now, datetime.date(2026, 7, 23), last_ts=None)
    assert ok is False and "tz" in reason
    # ref_date not today -> skip
    ok, reason = svc.should_persist(fresh_ts, now, datetime.date(2026, 7, 22), last_ts=None)
    assert ok is False and "reference_date" in reason


def test_build_snapshot_from_rl_curve():
    import rateslib as rl
    from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve

    handle = rl.Curve(
        nodes={rl.dt(2026, 7, 24): 1.0, rl.dt(2026, 7, 25): 0.99989, rl.dt(2027, 7, 24): 0.95},
        id="USD-SOFR-1D", convention="act360", calendar="nyc", interpolation="log_linear",
    )
    vendor_ts = _et(2026, 7, 23, 14, 31)
    curve = RLIRSwapCurve(rl_curve_id="USD-SOFR-1D", rl_curve_handle=handle,
                          fixings=None, meta_data={"timestamp": vendor_ts})
    snap = svc.build_snapshot(curve, vendor_ts)
    assert snap.curve_name == "USD-SOFR-1D-ERISLIVE"
    assert snap.reference_key == "USD-SOFR-1D"
    assert snap.source_variant == "ERIS_RL_BASIC_NOJUMPS"
    assert snap.trading_date == datetime.date(2026, 7, 23)      # ET calendar date
    assert snap.session_minute == 14 * 60 + 31                  # ET minute-of-day
    assert snap.timestamp_utc.tzinfo is not None
    assert snap.node_dates == [datetime.date(2026, 7, 24), datetime.date(2026, 7, 25), datetime.date(2027, 7, 24)]
    assert len(snap.discount_factors) == 3


def test_single_instance_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(svc.tempfile, "gettempdir", lambda: str(tmp_path))
    a = svc.SingleInstanceLock("eris-test")
    b = svc.SingleInstanceLock("eris-test")
    assert a.acquire() is True
    assert b.acquire() is False     # already held
    a.release()
    assert b.acquire() is True      # reclaimed after release
    b.release()


def test_run_service_dedups_and_gates(monkeypatch):
    import datetime
    calls = {"writes": []}

    ticks = [
        _et(2026, 7, 23, 8, 0),   # in session -> write (first, fresh stamp)
        _et(2026, 7, 23, 8, 1),   # in session, same vendor stamp -> skip
        _et(2026, 7, 23, 17, 30), # past stop -> loop ends
    ]
    stamps = [
        _et(2026, 7, 23, 7, 59, 40),
        _et(2026, 7, 23, 7, 59, 40),  # unchanged
    ]
    now_iter = iter(ticks)
    stamp_iter = iter(stamps)

    class FakeCurve:
        def __init__(self, ts):
            self._ts = ts
        def meta(self):
            return {"timestamp": self._ts}
        def reference_date(self):
            return None

    def now_fn():
        return next(now_iter)

    def poll_fn():
        return FakeCurve(next(stamp_iter))

    def writer_fn(curve, vendor_ts):
        calls["writes"].append(vendor_ts)

    def stop_fn(now_et):
        return now_et.hour >= 17  # stop after session

    # bypass the ref_date==today freshness leg for this synthetic clock:
    monkeypatch.setattr(svc, "should_persist",
                        lambda vt, now, ref, last, **k: (last != vt and (now - vt.astimezone(now.tzinfo)).total_seconds() <= 90, "unchanged" if last == vt else "ok"))

    counters = svc.run_service(poll_fn=poll_fn, now_fn=now_fn, writer_fn=writer_fn,
                               sleep_fn=lambda s: None, stop_fn=stop_fn, poll_seconds=0)
    assert len(calls["writes"]) == 1
    assert counters["wrote"] == 1 and counters["skipped"] == 1
