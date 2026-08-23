import datetime as dt

import pandas as pd

from scripts import stirf_curve_service as warm_script
from TB.barchart_irs_bulk import bucket_timestamps_by_trading_date


def test_window_for_date_cme_trading_day_spans_prior_evening():
    start, end = warm_script._window_for_date(
        dt.date(2026, 3, 16),
        window_template="cme_trading_day",
        timezone_name="America/New_York",
        start_time=dt.time(7, 0),
        end_time=dt.time(17, 0),
    )

    assert start.isoformat() == "2026-03-15T17:00:00-05:00"
    assert end.isoformat() == "2026-03-16T16:00:00-05:00"


def test_cap_end_at_now_trims_future_minutes():
    start = dt.datetime(2026, 3, 20, 9, 0, tzinfo=dt.timezone.utc)
    end = dt.datetime(2026, 3, 20, 12, 0, tzinfo=dt.timezone.utc)
    now = dt.datetime(2026, 3, 20, 10, 17, 42, tzinfo=dt.timezone.utc)

    capped = warm_script._cap_end_at_now(start, end, now_utc=now)

    assert capped == (
        dt.datetime(2026, 3, 20, 9, 0, tzinfo=dt.timezone.utc),
        dt.datetime(2026, 3, 20, 10, 2, tzinfo=dt.timezone.utc),
    )


def test_resolve_dates_defaults_to_today_or_inclusive_range():
    assert warm_script._resolve_dates(
        explicit_dates=[],
        start_date=None,
        end_date=None,
        default_date=dt.date(2026, 3, 20),
    ) == [dt.date(2026, 3, 20)]

    assert warm_script._resolve_dates(
        explicit_dates=[],
        start_date=dt.date(2026, 3, 18),
        end_date=dt.date(2026, 3, 20),
        default_date=dt.date(2026, 3, 20),
    ) == [
        dt.date(2026, 3, 18),
        dt.date(2026, 3, 19),
        dt.date(2026, 3, 20),
    ]


def test_default_tenors_for_stirt_curve_defaults_to_first_twelve_quarterly_imm_pairs():
    tenors = warm_script._default_tenors_for_curve(
        "USD-SOFR-1D-Q12STIRT",
        anchor_date=dt.date(2026, 3, 20),
    )

    assert tenors == [f"IMM_{idx}xIMM_{idx + 1}" for idx in range(1, 13)]


def test_default_tenors_for_non_cb_curve_stays_generic():
    tenors = warm_script._default_tenors_for_curve("MXN-TIIE", anchor_date=dt.date(2026, 3, 13))

    assert len(tenors) > 70
    assert "1Y" in tenors
    assert "1Y1Y" in tenors
    assert "fomc_1" not in tenors


def test_explicit_imm_pair_tenors_include_adjacent_and_one_year_pairs():
    tenors = warm_script._explicit_imm_pair_tenors(
        as_of=dt.date(2026, 3, 13),
        horizon_count=13,
        spans=(1, 4),
    )

    assert "IMM_H26xIMM_M26" in tenors
    assert "IMM_Z26xIMM_H27" in tenors
    assert "IMM_H26xIMM_H27" in tenors


def test_stirt_tenor_maturity_date_respects_three_year_horizon_examples():
    assert warm_script._stirt_tenor_maturity_date(
        "USD-SOFR-1D-Q12STIRT",
        "IMM_Z26xIMM_H27",
        anchor_date=dt.date(2026, 3, 20),
    ) <= dt.date(2029, 3, 20)

    assert warm_script._stirt_tenor_maturity_date(
        "USD-SOFR-1D-Q12STIRT",
        "IMM_Z28xIMM_H29",
        anchor_date=dt.date(2026, 3, 20),
    ) > dt.date(2029, 3, 20)


def test_incremental_range_uses_latest_curve_store_timestamp(monkeypatch):
    latest_ts = dt.datetime(2026, 3, 20, 13, 30, tzinfo=dt.timezone.utc)
    now_utc = dt.datetime(2026, 3, 20, 14, 0, tzinfo=dt.timezone.utc)

    class _FakeStore:
        pass

    class _FakeMdp:
        def __init__(self):
            self._store = _FakeStore()

        def _get_curve_store(self):
            return self._store

    class _FakeTsBuilder:
        def _prepare_product_intraday_timestamps(self, *, product, mdp, start, end, freq, timestamps):
            _ = product, mdp, start, end, freq
            return timestamps[::2]

    monkeypatch.setattr(warm_script, "_resolve_curve_store_name", lambda mdp, curve_name: curve_name)
    monkeypatch.setattr(warm_script, "_latest_curve_store_timestamp", lambda store, curve_name: latest_ts)

    timestamps = warm_script._resolve_incremental_timestamp_range(
        curve_name="USD-SOFR-1D-Q12STIRT",
        mdp=_FakeMdp(),
        ts_builder=_FakeTsBuilder(),
        window_template="nyc_rth",
        timezone_name="America/New_York",
        start_time=dt.time(7, 0),
        end_time=dt.time(17, 0),
        now_utc=now_utc,
    )

    assert timestamps[0] == latest_ts
    assert timestamps[-1] == dt.datetime(2026, 3, 20, 13, 44, tzinfo=dt.timezone.utc)


def test_select_missing_curve_store_timestamps_backfills_internal_gap():
    timestamps = [
        dt.datetime(2026, 3, 20, 9, 30, tzinfo=dt.timezone.utc),
        dt.datetime(2026, 3, 20, 9, 31, tzinfo=dt.timezone.utc),
        dt.datetime(2026, 3, 20, 9, 32, tzinfo=dt.timezone.utc),
        dt.datetime(2026, 3, 20, 9, 33, tzinfo=dt.timezone.utc),
    ]

    class _FakeStore:
        def read_raw_nodes(self, curve_name, timestamps_utc):
            _ = curve_name
            return pd.DataFrame(
                {
                    "timestamp_utc": [
                        timestamps_utc[0],
                        timestamps_utc[-1],
                    ]
                }
            )

    missing = warm_script._select_missing_curve_store_timestamps(
        _FakeStore(),
        curve_name="USD-SOFR-1D-Q12STIRT",
        timestamps=timestamps,
    )

    assert missing == timestamps[1:3]


def test_bucket_timestamps_by_trading_date_preserves_barchart_trade_date_boundaries():
    timestamps = [
        dt.datetime(2026, 3, 15, 23, 0, tzinfo=dt.timezone.utc),
        dt.datetime(2026, 3, 16, 14, 30, tzinfo=dt.timezone.utc),
        dt.datetime(2026, 3, 16, 23, 0, tzinfo=dt.timezone.utc),
    ]

    buckets = bucket_timestamps_by_trading_date(timestamps)

    assert list(buckets) == [dt.date(2026, 3, 16), dt.date(2026, 3, 17)]
    assert buckets[dt.date(2026, 3, 16)] == timestamps[:2]
    assert buckets[dt.date(2026, 3, 17)] == timestamps[2:]


def test_parser_defaults_to_cme_trading_day():
    args = warm_script.parse_args(["live-service"])

    assert args.window_template == "cme_trading_day"


def test_live_service_window_reports_partial_when_some_timestamps_fail(monkeypatch):
    timestamps = [
        dt.datetime(2026, 3, 20, 9, 30, tzinfo=dt.timezone.utc),
        dt.datetime(2026, 3, 20, 9, 31, tzinfo=dt.timezone.utc),
    ]

    logger = warm_script.logging.getLogger("test_live_service_window")
    monkeypatch.setattr(
        warm_script,
        "_safe_warm_raw_curves",
        lambda *args, **kwargs: (1, [timestamps[-1]]),
    )
    monkeypatch.setattr(
        warm_script,
        "_warm_timeseries_window",
        lambda **kwargs: {
            "status": "partial",
            "rows": 2,
            "cols": 1,
            "failed_tenors": ["BAD"],
        },
    )

    warm_script_summary = warm_script._run_live_service_window(
        curve_name="USD-SOFR-1D-Q12STIRT",
        curve_timestamps=timestamps,
        timeseries_timestamps=timestamps,
        explicit_tenors=["1Y"],
        mdp=object(),
        ts_builder=object(),
        n_jobs=4,
        calibration_executor="thread",
        curve_ignore_cache=False,
        timeseries_ignore_cache=True,
        show_tqdm=False,
        auto_prime_bulk=True,
        stirf_fetch_max_workers=None,
        calibration_max_workers=None,
        skip_curve_warm=False,
        skip_timeseries_warm=False,
        perf_log_path=None,
        logger=logger,
        label="incremental-from-db",
    )

    assert warm_script_summary["status"] == "partial"
    assert warm_script_summary["curve_status"] == "partial"
    assert warm_script_summary["timeseries_status"] == "partial"


def test_safe_warm_raw_curves_isolates_bad_timestamp():
    bad_ts = dt.datetime(2026, 3, 20, 9, 31, tzinfo=dt.timezone.utc)
    timestamps = [
        dt.datetime(2026, 3, 20, 9, 30, tzinfo=dt.timezone.utc),
        bad_ts,
        dt.datetime(2026, 3, 20, 9, 32, tzinfo=dt.timezone.utc),
    ]

    class _FakeMdp:
        def bulk_get_data(self, request):
            batch = list(request["timestamps"])
            if bad_ts in batch:
                raise RuntimeError("bad timestamp")
            return {ts: object() for ts in batch}

    curve_count, failed = warm_script._safe_warm_raw_curves(
        _FakeMdp(),
        curve_name="USD-SOFR-1D-Q12STIRT",
        timestamps=timestamps,
        ignore_cache=False,
        n_jobs=4,
        calibration_executor="thread",
    )

    assert curve_count == 2
    assert failed == [bad_ts]


def test_safe_warm_timeseries_isolates_bad_tenor():
    timestamps = [
        dt.datetime(2026, 3, 20, 9, 30, tzinfo=dt.timezone.utc),
        dt.datetime(2026, 3, 20, 9, 31, tzinfo=dt.timezone.utc),
    ]

    class _Query:
        def __init__(self, tenor):
            self.tenor = tenor

    class _FakeTsBuilder:
        def get_timeseries(self, *, queries, timestamps, **kwargs):
            _ = kwargs
            tenors = [q.tenor for q in queries]
            if "BAD" in tenors:
                raise RuntimeError("bad tenor")
            import pandas as pd

            return pd.DataFrame(
                {tenor: [float(idx + 1)] * len(timestamps) for idx, tenor in enumerate(tenors)},
                index=pd.Index(timestamps),
            )

    df, failed = warm_script._safe_warm_timeseries(
        _FakeTsBuilder(),
        start=timestamps[0],
        end=timestamps[-1],
        queries=[_Query("1Y"), _Query("BAD"), _Query("IMM_1xIMM_2")],
        n_jobs=4,
        ignore_cache=False,
        timestamps=timestamps,
        mdps={"IRS": object()},
        curve_name="USD-SOFR-1D-Q12STIRT",
    )

    assert list(df.columns) == ["1Y", "IMM_1xIMM_2"]
    assert failed == ["BAD"]


def _run_backfill_capturing(monkeypatch, tmp_path, trading_date, extra=None):
    """Drive `_run_backfill_mode` for one day with every side effect stubbed.

    Same stub set as the test below, factored out so the settled/today/override
    cases differ only in the date and the flags.
    """
    timestamps = [
        dt.datetime(2026, 3, 20, 9, 30, tzinfo=dt.timezone.utc),
        dt.datetime(2026, 3, 20, 9, 31, tzinfo=dt.timezone.utc),
    ]
    captured: list[dict] = []

    class _FakeMdp:
        def __init__(self, source):
            self.source = source
            self._store = object()

        def _get_curve_store(self):
            return self._store

    monkeypatch.setattr(warm_script, "IRSwapsMDP", _FakeMdp)
    monkeypatch.setattr(warm_script, "_build_timeseries_builder", lambda **kwargs: object())
    monkeypatch.setattr(warm_script, "count_business_day_buckets", lambda **kwargs: 1)
    monkeypatch.setattr(
        warm_script, "inspect_curve_store_sync_status",
        lambda **kwargs: {
            "curve_name": kwargs["curve_name"],
            "start_date": kwargs["start_date"].isoformat(),
            "end_date": kwargs["end_date"].isoformat(),
            "local_dates": [], "remote_dates": [],
            "local_days": 0, "remote_days": 0,
            "local_only_days": 0, "local_only_dates": [],
        },
    )
    monkeypatch.setattr(
        warm_script, "backfill_local_curve_store_to_supabase",
        lambda **kwargs: {"status": "ok", "pushed_days": 0, "failed_days": 0, "queued_days": 0},
    )
    monkeypatch.setattr(
        warm_script, "iter_daily_minute_buckets",
        lambda **kwargs: iter([(trading_date, timestamps)]),
    )
    monkeypatch.setattr(
        warm_script, "_select_missing_curve_store_timestamps",
        lambda store, curve_name, timestamps: [timestamps[-1]],
    )
    monkeypatch.setattr(warm_script, "_flush_curve_store_pushes", lambda **kwargs: None)
    monkeypatch.setattr(warm_script, "_flush_computed_ts_pushes", lambda **kwargs: None)

    def _fake_window(**kwargs):
        captured.append(kwargs)
        return {
            "status": "ok", "curve_status": "ok", "timeseries_status": "ok",
            "curve_requested": len(kwargs["curve_timestamps"]),
            "curve_ready": len(kwargs["curve_timestamps"]),
            "curve_failed_timestamps": [],
            "timeseries_rows": len(kwargs["timeseries_timestamps"]),
            "timeseries_cols": 12,
            "timeseries_failed_tenors": [],
        }

    monkeypatch.setattr(warm_script, "_run_live_service_window", _fake_window)

    args = warm_script.parse_args([
        "backfill", "--curve", "USD-SOFR-1D-Q12STIRT",
        "--start-date", trading_date.isoformat(),
        "--end-date", trading_date.isoformat(),
        "--perf-log-path", str(tmp_path / "perf.jsonl"),
        *(extra or []),
    ])
    assert warm_script._run_backfill_mode(
        args, warm_script.logging.getLogger("test_backfill_mode")
    ) == 0
    assert len(captured) == 1
    return captured


def test_backfill_mode_only_warms_missing_raw_and_does_not_reprice_a_settled_day(monkeypatch, tmp_path):
    """The raw half filters; the timeseries half no longer forces a reprice.

    It used to pass `timeseries_ignore_cache=True` unconditionally, so a
    backfilled day re-priced every minute of every tenor whether or not the
    computed store held it. Backfilling five already-warm nights on 2026-08-15,
    the third curve hit the 3,600 s per-curve cap and was LOST.

    The timestamps are still unfiltered -- that half is the TB's job, not this
    loop's; what changed is only whether it is told to ignore what it finds.
    """
    trading_date = dt.date(2026, 3, 20)
    timestamps = [
        dt.datetime(2026, 3, 20, 9, 30, tzinfo=dt.timezone.utc),
        dt.datetime(2026, 3, 20, 9, 31, tzinfo=dt.timezone.utc),
    ]
    captured: list[dict] = []

    class _FakeMdp:
        def __init__(self, source):
            self.source = source
            self._store = object()

        def _get_curve_store(self):
            return self._store

    monkeypatch.setattr(warm_script, "IRSwapsMDP", _FakeMdp)
    monkeypatch.setattr(warm_script, "_build_timeseries_builder", lambda **kwargs: object())
    monkeypatch.setattr(warm_script, "count_business_day_buckets", lambda **kwargs: 1)
    monkeypatch.setattr(
        warm_script,
        "inspect_curve_store_sync_status",
        lambda **kwargs: {
            "curve_name": kwargs["curve_name"],
            "start_date": kwargs["start_date"].isoformat(),
            "end_date": kwargs["end_date"].isoformat(),
            "local_dates": [],
            "remote_dates": [],
            "local_days": 0,
            "remote_days": 0,
            "local_only_days": 0,
            "local_only_dates": [],
        },
    )
    monkeypatch.setattr(
        warm_script,
        "backfill_local_curve_store_to_supabase",
        lambda **kwargs: {
            "status": "ok",
            "pushed_days": 0,
            "failed_days": 0,
            "queued_days": 0,
        },
    )
    monkeypatch.setattr(
        warm_script,
        "iter_daily_minute_buckets",
        lambda **kwargs: iter([(trading_date, timestamps)]),
    )
    monkeypatch.setattr(
        warm_script,
        "_select_missing_curve_store_timestamps",
        lambda store, curve_name, timestamps: [timestamps[-1]],
    )
    monkeypatch.setattr(warm_script, "_flush_curve_store_pushes", lambda **kwargs: None)
    monkeypatch.setattr(warm_script, "_flush_computed_ts_pushes", lambda **kwargs: None)

    def _fake_run_live_service_window(**kwargs):
        captured.append(kwargs)
        return {
            "status": "ok",
            "curve_status": "ok",
            "timeseries_status": "ok",
            "curve_requested": len(kwargs["curve_timestamps"]),
            "curve_ready": len(kwargs["curve_timestamps"]),
            "curve_failed_timestamps": [],
            "timeseries_rows": len(kwargs["timeseries_timestamps"]),
            "timeseries_cols": len(kwargs["explicit_tenors"]) or len(warm_script._STIRT_DEFAULT_RELATIVE_IMM_TENORS),
            "timeseries_failed_tenors": [],
        }

    monkeypatch.setattr(warm_script, "_run_live_service_window", _fake_run_live_service_window)

    args = warm_script.parse_args(
        [
            "backfill",
            "--curve",
            "USD-SOFR-1D-Q12STIRT",
            "--start-date",
            "2026-03-20",
            "--end-date",
            "2026-03-20",
            "--perf-log-path",
            str(tmp_path / "perf.jsonl"),
        ]
    )

    exit_code = warm_script._run_backfill_mode(
        args,
        warm_script.logging.getLogger("test_backfill_mode"),
    )

    assert exit_code == 0
    assert len(captured) == 1
    assert captured[0]["curve_timestamps"] == [timestamps[-1]]
    assert captured[0]["timeseries_timestamps"] == timestamps
    assert captured[0]["curve_ignore_cache"] is False
    assert captured[0]["timeseries_ignore_cache"] is False, (
        "2026-03-20 is settled; re-pricing it is the behaviour that lost a curve"
    )


def test_backfill_mode_still_reprices_today(monkeypatch, tmp_path):
    """Today's session is still moving, so its partial values SHOULD refresh.

    That is the case the unconditional True was written for; it was simply never
    bounded to it.
    """
    today = dt.date.today()
    captured = _run_backfill_capturing(monkeypatch, tmp_path, today)
    assert captured[0]["timeseries_ignore_cache"] is True


def test_reprice_timeseries_forces_it_on_a_settled_day(monkeypatch, tmp_path):
    """The escape hatch, for a deliberate repair."""
    captured = _run_backfill_capturing(
        monkeypatch, tmp_path, dt.date(2026, 3, 20), extra=["--reprice-timeseries"]
    )
    assert captured[0]["timeseries_ignore_cache"] is True
