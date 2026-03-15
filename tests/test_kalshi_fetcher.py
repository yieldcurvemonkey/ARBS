import pytest
import datetime


class TestKalshiFetcher:
    def test_build_auth_headers_structure(self):
        from MDP.EventContracts.kalshi_fetcher import build_kalshi_auth_headers
        with pytest.raises(Exception):
            build_kalshi_auth_headers(method="GET", path="/trade-api/v2/markets", api_key_id="test-key", private_key_pem=None)

    def test_parse_candlestick_response(self):
        from MDP.EventContracts.kalshi_fetcher import parse_candlestick_response
        raw = {
            "ticker": "TEST-TICKER",
            "candlesticks": [
                {"end_period_ts": 1710532800, "price": {"open_dollars": "0.5500", "low_dollars": "0.5000", "high_dollars": "0.6000", "close_dollars": "0.5800", "mean_dollars": "0.5500", "previous_dollars": "0.5400"}, "volume_fp": "150.00", "open_interest_fp": "500.00"},
                {"end_period_ts": 1710619200, "price": {"open_dollars": "0.5800", "low_dollars": "0.5600", "high_dollars": "0.6200", "close_dollars": "0.6000", "mean_dollars": "0.5900", "previous_dollars": "0.5800"}, "volume_fp": "200.00", "open_interest_fp": "550.00"},
            ],
        }
        df = parse_candlestick_response(raw)
        assert len(df) == 2
        assert "close" in df.columns
        assert "volume" in df.columns
        assert "open_interest" in df.columns
        assert df["close"].iloc[0] == pytest.approx(0.58)
        assert df["volume"].iloc[0] == pytest.approx(150.0)

    def test_historical_url_construction(self):
        from MDP.EventContracts.kalshi_fetcher import build_historical_candlestick_url
        url = build_historical_candlestick_url(ticker="KXFED-26MAR19", start_ts=1710000000, end_ts=1710600000, period_interval=1440)
        assert "KXFED-26MAR19" in url
        assert "period_interval=1440" in url
