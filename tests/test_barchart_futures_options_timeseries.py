import datetime

import pandas as pd

from MDP.STIRFutures.BARCHART.BarchartFetcher import BarchartFetcher


def test_fetch_futures_options_timeseries_normalizes_history_frames(monkeypatch):
    fetcher = BarchartFetcher(debug_verbose=False, info_verbose=False, error_verbose=False)
    captured = {}

    def _fake_barchart_timeseries_api(**kwargs):
        captured.update(kwargs)
        return {
            "SQZ27|9700C": pd.DataFrame(
                {
                    "Date": ["2026-03-03", "2026-03-04"],
                    "Open": [0.4050, 0.3950],
                    "High": [0.4050, 0.3950],
                    "Low": [0.4000, 0.3650],
                    "Close": [0.4000, 0.3650],
                    "Volume": [2028, 5116],
                    "Open Interest": [22800, 27916],
                    "Delta": [0.5607, 0.5819],
                    "Gamma": [0.3725, 0.4424],
                    "Theta": [-0.0002, -0.0002],
                    "Vega": [0.0150, 0.0150],
                    "Implied Volatility": [0.2369, 0.1929],
                }
            )
        }

    monkeypatch.setattr(fetcher, "barchart_timeseries_api", _fake_barchart_timeseries_api)

    out = fetcher.fetch_futures_options_timeseries(
        start=datetime.date(2026, 3, 3),
        end="2026-03-04",
        symbols=["SQZ27|9700C"],
        show_tqdm=False,
    )

    assert captured["barchart_symbols"] == ["SQZ27|9700C"]
    assert captured["start_date"] == datetime.datetime(2026, 3, 3)
    assert captured["end_date"] == datetime.datetime(2026, 3, 4)
    assert captured["max_concurrent_tasks"] == 8
    assert captured["max_keepalive_connections"] == 8
    assert captured["max_requests_per_second"] == 6

    df = out["SQZ27|9700C"]
    assert list(df.columns) == [
        "symbol",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "openinterest",
        "delta",
        "gamma",
        "theta",
        "vega",
        "impliedVolatility",
    ]
    assert df.index.name == "date"
    assert df.loc[pd.Timestamp("2026-03-04"), "symbol"] == "SQZ27|9700C"
    assert df.loc[pd.Timestamp("2026-03-04"), "openinterest"] == 27916


def test_build_eod_url_date_bounds():
    fetcher = BarchartFetcher(debug_verbose=False)

    # Default: full history, no server-side date bounds (cache-friendly).
    default_url = fetcher._build_eod_url("SQM26")
    assert "queryeod.ashx" in default_url
    assert "symbol=SQM26" in default_url
    assert "data=daily" in default_url
    assert "&start=" not in default_url
    assert "&end=" not in default_url

    # Opt-in: server-side YYYYMMDD bounds shrink the payload for tail refreshes.
    bounded = fetcher._build_eod_url(
        "SQM26",
        start=datetime.datetime(2025, 1, 1),
        end=datetime.date(2025, 2, 1),
        server_side_dates=True,
    )
    assert "&start=20250101" in bounded
    assert "&end=20250201" in bounded

    # String boundaries are coerced; missing/invalid boundaries are omitted, not errored.
    from_str = fetcher._build_eod_url("SQM26", start="2025-03-15", server_side_dates=True)
    assert "&start=20250315" in from_str
    assert "&end=" not in from_str

    assert fetcher._format_eod_boundary(None) is None
    assert fetcher._format_eod_boundary("not-a-date") is None
    assert fetcher._format_eod_boundary(datetime.date(2026, 5, 30)) == "20260530"
