import datetime as dt

import pandas as pd

from scripts import warm_intraday_irs_cache as warm_script


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


def test_default_tenors_for_stirt_curve_stays_inside_3y_and_includes_imm_pairs():
    tenors = warm_script._default_tenors_for_curve(
        "USD-SOFR-1D-Q12STIRT",
        anchor_date=dt.date(2026, 3, 20),
    )

    assert "1Y" in tenors
    assert "3Y" in tenors
    assert "5Y" not in tenors
    assert "fomc_1" in tenors
    assert "IMM_1xIMM_2" in tenors
    assert "IMM_1xIMM_5" in tenors
    assert "IMM_Z26xIMM_H27" in tenors
    assert "IMM_Z28xIMM_H29" not in tenors

    max_maturity = dt.date(2029, 3, 20)
    filtered_maturities = [
        warm_script._stirt_tenor_maturity_date(
            "USD-SOFR-1D-Q12STIRT",
            tenor,
            anchor_date=dt.date(2026, 3, 20),
        )
        for tenor in tenors
        if tenor.startswith("fomc_") or tenor.startswith("IMM_")
    ]
    assert filtered_maturities
    assert all(maturity is not None and maturity <= max_maturity for maturity in filtered_maturities)


def test_default_tenors_for_non_cb_curve_stays_generic():
    tenors = warm_script._default_tenors_for_curve("MXN-TIIE", anchor_date=dt.date(2026, 3, 13))

    assert len(tenors) == 100
    assert "1Y" in tenors
    assert "1Y10Y" in tenors
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


def test_parser_defaults_to_cme_trading_day():
    args = warm_script._build_parser().parse_args([])

    assert args.window_template == "cme_trading_day"


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
