import datetime as dt
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from TB.IRSwapSpreadsTB import IRSwapSpreadsTB, deadband_step_filter


def _oasis_valid_trade_row(*, trade_id: str = "1") -> dict:
    return {
        "Dissemination Identifier": trade_id,
        "Unique Product Identifier": "QZXQ4R16245X",
        "Action type": "NEWT",
        "Event type": "TRAD",
        "Mandatory clearing indicator": True,
        "Fixed rate-Leg 1": 0.041,
        "Platform identifier": "SEF1",
        "Large notional off-facility swap election indicator": None,
        "Other payment type": "",
        "Package transaction price notation": 0,
        "Floating rate reset frequency period-leg 1": "MNTH",
        "Floating rate reset frequency period multiplier-leg 1": 12,
        "Floating rate reset frequency period-leg 2": "DAY",
        "Floating rate reset frequency period multiplier-leg 2": 0,
        "Fixed rate payment frequency period-Leg 1": "MNTH",
        "Fixed rate payment frequency period multiplier-Leg 1": 12,
        "Fixed rate payment frequency period-Leg 2": "DAY",
        "Fixed rate payment frequency period multiplier-Leg 2": 0,
        "Floating rate payment frequency period-Leg 1": "MNTH",
        "Floating rate payment frequency period multiplier-Leg 1": 12,
        "Floating rate payment frequency period-Leg 2": "DAY",
        "Floating rate payment frequency period multiplier-Leg 2": 0,
        "Execution Timestamp": pd.Timestamp("2026-03-19 13:00:00Z"),
        "Effective Date": pd.Timestamp("2026-03-23"),
        "Expiration Date": pd.Timestamp("2028-03-23"),
        "Notional amount-Leg 1": "100,000,000",
    }


def test_deadband_step_filter_matches_notebook_behavior():
    x = pd.Series([1.0, 1.1, 1.6, 1.55], index=pd.RangeIndex(4))

    out = deadband_step_filter(x, threshold=0.25, snap=0.25)

    assert out.tolist() == [1.0, 1.0, 1.5, 1.5]


def test_oasis_filter_removes_non_notebook_trades():
    tb = IRSwapSpreadsTB(source="SDR-WSJ-INTRADAY-SPREADOVER", show_tqdm=False)
    good = _oasis_valid_trade_row(trade_id="good")
    bad_platform = {**_oasis_valid_trade_row(trade_id="bad_platform"), "Platform identifier": "XOFF"}
    bad_package = {**_oasis_valid_trade_row(trade_id="bad_package"), "Package transaction price notation": 1}
    bad_clearing = {**_oasis_valid_trade_row(trade_id="bad_clearing"), "Mandatory clearing indicator": False}
    bad_freq = {
        **_oasis_valid_trade_row(trade_id="bad_freq"),
        "Floating rate reset frequency period-leg 1": "DAY",
        "Floating rate reset frequency period multiplier-leg 1": 1,
        "Fixed rate payment frequency period-Leg 1": "DAY",
        "Fixed rate payment frequency period multiplier-Leg 1": 1,
        "Floating rate payment frequency period-Leg 1": "DAY",
        "Floating rate payment frequency period multiplier-Leg 1": 1,
    }

    raw = pd.DataFrame([good, bad_platform, bad_package, bad_clearing, bad_freq])
    filtered = tb._apply_oasis_sdr_filters(raw)

    assert filtered["Dissemination Identifier"].tolist() == ["good"]


def test_oasis_filter_keeps_intraday_rows_with_missing_optional_fields():
    tb = IRSwapSpreadsTB(source="SDR-WSJ-INTRADAY-SPREADOVER", show_tqdm=False)
    raw = pd.DataFrame(
        [
            {
                **_oasis_valid_trade_row(trade_id="good_missing"),
                "Other payment type": pd.NA,
                "Package transaction price notation": pd.NA,
            }
        ]
    )

    filtered = tb._apply_oasis_sdr_filters(raw)

    assert filtered["Dissemination Identifier"].tolist() == ["good_missing"]


def test_get_timeseries_builds_spreads_and_smoothing(monkeypatch: pytest.MonkeyPatch):
    tb = IRSwapSpreadsTB(source="SDR-WSJ-INTRADAY-SPREADOVER", show_tqdm=False)
    ny = ZoneInfo("America/New_York")
    start = dt.datetime(2026, 3, 19, 9, 0, tzinfo=ny)
    end = dt.datetime(2026, 3, 19, 9, 2, tzinfo=ny)
    effective_date, maturity_date = tb._resolve_swap_dates(dt.date(2026, 3, 19), "2Y")

    sdr_df = pd.DataFrame(
        [
            {
                **_oasis_valid_trade_row(trade_id="t1"),
                "Execution Timestamp": pd.Timestamp("2026-03-19 13:00:00Z"),
                "Effective Date": pd.Timestamp(effective_date),
                "Expiration Date": pd.Timestamp(maturity_date),
                "Fixed rate-Leg 1": 0.0400,
                "Notional amount-Leg 1": "100,000,000",
            },
            {
                **_oasis_valid_trade_row(trade_id="t2"),
                "Execution Timestamp": pd.Timestamp("2026-03-19 13:02:00Z"),
                "Effective Date": pd.Timestamp(effective_date),
                "Expiration Date": pd.Timestamp(maturity_date),
                "Fixed rate-Leg 1": 0.0410,
                "Notional amount-Leg 1": "100,000,000",
            },
        ]
    )
    wsj_df = pd.DataFrame(
        {
            "2Y_UST_YIELD_PCT": [3.95, 3.95],
        },
        index=pd.DatetimeIndex(
            [
                dt.datetime(2026, 3, 19, 9, 0, tzinfo=ny),
                dt.datetime(2026, 3, 19, 9, 2, tzinfo=ny),
            ],
            name="Date",
        ),
    )

    monkeypatch.setattr(tb, "_fetch_raw_sdr_trades", lambda **kwargs: sdr_df.copy())
    monkeypatch.setattr(
        tb,
        "_fetch_wsj_ct_timeseries",
        lambda **kwargs: wsj_df.copy(),
    )

    out = tb.get_timeseries(
        start=start,
        end=end,
        tenors=["2Y"],
        include_components=True,
        smoothing_window=2,
        deadband_threshold=4.0,
        deadband_snap=None,
        ignore_cache=True,
    )

    assert list(out.index.strftime("%H:%M")) == ["09:00", "09:01", "09:02"]
    assert out.loc[out.index[0], "2Y_SWAP_RATE_PCT"] == pytest.approx(4.00)
    assert out.loc[out.index[1], "2Y_SWAP_RATE_PCT"] == pytest.approx(4.00)
    assert out.loc[out.index[2], "2Y_SWAP_RATE_PCT"] == pytest.approx(4.10)
    assert out.loc[out.index[0], "2Y_SWAP_SPREAD_BPS"] == pytest.approx(5.0)
    assert out.loc[out.index[1], "2Y_SWAP_SPREAD_BPS"] == pytest.approx(5.0)
    assert out.loc[out.index[2], "2Y_SWAP_SPREAD_BPS"] == pytest.approx(15.0)
    assert out.loc[out.index[2], "2Y_SWAP_SPREAD_BPS_SMA_2"] == pytest.approx(10.0)
    assert out.loc[out.index[2], "2Y_SWAP_SPREAD_BPS_MEDIAN_2"] == pytest.approx(10.0)
    assert out.loc[out.index[2], "2Y_SWAP_SPREAD_BPS_STEP"] == pytest.approx(15.0)


def test_rejects_illiquid_tenor():
    tb = IRSwapSpreadsTB(source="SDR-WSJ-INTRADAY-SPREADOVER", show_tqdm=False)

    with pytest.raises(ValueError, match="Unsupported tenor"):
        tb.get_timeseries(
            start=dt.datetime(2026, 3, 19, 9, 0, tzinfo=dt.timezone.utc),
            end=dt.datetime(2026, 3, 19, 9, 1, tzinfo=dt.timezone.utc),
            tenors=["7Y"],
        )


def test_rejects_unknown_source():
    with pytest.raises(ValueError, match="Unsupported source"):
        IRSwapSpreadsTB(source="UNKNOWN", show_tqdm=False)


def test_webull_wsj_live_source_uses_fixed_rate_bonds_tb(monkeypatch: pytest.MonkeyPatch):
    ny = ZoneInfo("America/New_York")
    start = dt.datetime(2026, 1, 27, 7, 30, tzinfo=ny)
    end = dt.datetime(2026, 1, 27, 15, 0, tzinfo=ny)
    tb = IRSwapSpreadsTB(
        source="SDR-USTS_WEBULL_WSJ_LIVE-INTRADAY-SPREADOVER",
        show_tqdm=False,
    )
    seen: dict = {}

    class _FakeMdp:
        def __init__(self, source):
            seen["mdp_source"] = source

    class _FakeTb:
        def __init__(self, mdp, show_tqdm):
            seen["tb_mdp"] = mdp
            seen["show_tqdm"] = show_tqdm

        def get_timeseries(self, **kwargs):
            seen["tb_kwargs"] = kwargs
            return pd.DataFrame(
                {"CT10 OUTRIGHT YTM": [4.25, 4.26]},
                index=pd.DatetimeIndex([start, end], name="Date"),
            )

    monkeypatch.setattr("TB.IRSwapSpreadsTB.FixedRateBondsMDP", _FakeMdp)
    monkeypatch.setattr("TB.IRSwapSpreadsTB.FixedRateBondsTB", _FakeTb)
    monkeypatch.setattr(
        "TB.IRSwapSpreadsTB.ql_cal_date_range",
        lambda cal, start, end, freq: [start, end],
    )

    out = tb._fetch_usts_webull_wsj_live_ct_timeseries(
        start=start,
        end=end,
        tenors=["10Y"],
    )

    assert seen["mdp_source"] == "USTS_WEBULL_WSJ_LIVE-RL"
    assert seen["show_tqdm"] is False
    assert seen["tb_kwargs"]["start"] is None
    assert seen["tb_kwargs"]["end"] is None
    assert seen["tb_kwargs"]["timestamps"] == [start, end]
    assert seen["tb_kwargs"]["n_jobs"] == 12
    assert len(seen["tb_kwargs"]["queries"]) == 1
    assert seen["tb_kwargs"]["queries"][0].cusip == "CT10"
    assert list(out.columns) == ["10Y_UST_YIELD_PCT"]
    assert out.iloc[0, 0] == pytest.approx(4.25)


def test_get_timeseries_uses_webull_ust_source_branch(monkeypatch: pytest.MonkeyPatch):
    ny = ZoneInfo("America/New_York")
    start = dt.datetime(2026, 3, 19, 9, 0, tzinfo=ny)
    end = dt.datetime(2026, 3, 19, 9, 2, tzinfo=ny)
    tb = IRSwapSpreadsTB(
        source="SDR-USTS_WEBULL_WSJ_LIVE-INTRADAY-SPREADOVER",
        show_tqdm=False,
    )
    effective_date, maturity_date = tb._resolve_swap_dates(dt.date(2026, 3, 19), "10Y")

    sdr_df = pd.DataFrame(
        [
            {
                **_oasis_valid_trade_row(trade_id="t1"),
                "Execution Timestamp": pd.Timestamp("2026-03-19 13:00:00Z"),
                "Effective Date": pd.Timestamp(effective_date),
                "Expiration Date": pd.Timestamp(maturity_date),
                "Fixed rate-Leg 1": 0.0450,
                "Notional amount-Leg 1": "100,000,000",
            }
        ]
    )
    ust_df = pd.DataFrame(
        {"10Y_UST_YIELD_PCT": [4.10]},
        index=pd.DatetimeIndex([start], name="Date"),
    )

    monkeypatch.setattr(tb, "_fetch_raw_sdr_trades", lambda **kwargs: sdr_df.copy())
    monkeypatch.setattr(
        tb,
        "_fetch_usts_webull_wsj_live_ct_timeseries",
        lambda **kwargs: ust_df.copy(),
    )
    monkeypatch.setattr(
        tb,
        "_fetch_wsj_ct_timeseries",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("wrong source branch")),
    )

    out = tb.get_timeseries(
        start=start,
        end=end,
        tenors=["10Y"],
        include_components=True,
        ignore_cache=True,
    )

    assert out.loc[start, "10Y_SWAP_RATE_PCT"] == pytest.approx(4.50)
    assert out.loc[start, "10Y_UST_YIELD_PCT"] == pytest.approx(4.10)
    assert out.loc[start, "10Y_SWAP_SPREAD_BPS"] == pytest.approx(40.0)
