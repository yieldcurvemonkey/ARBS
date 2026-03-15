import pytest
import datetime


class TestPolymarketFetcher:
    def test_parse_price_history(self):
        from MDP.EventContracts.polymarket_fetcher import parse_price_history
        raw = {"history": [{"t": 1710532800, "p": 0.65}, {"t": 1710619200, "p": 0.70}, {"t": 1710705600, "p": 0.68}]}
        df = parse_price_history(raw)
        assert len(df) == 3
        assert "price" in df.columns
        assert df["price"].iloc[0] == pytest.approx(0.65)

    def test_build_url(self):
        from MDP.EventContracts.polymarket_fetcher import build_price_history_url
        url = build_price_history_url(market_id="0x1234abc", start_ts=1710000000, end_ts=1710600000, interval="1d")
        assert "market=0x1234abc" in url
        assert "interval=1d" in url
        assert "clob.polymarket.com" in url
