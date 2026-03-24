import pytest
import datetime
import pandas as pd


class TestEventContractPricer:
    def test_pricer_holds_data(self):
        from MDP.EventContracts.EventContractsMDP import EventContractPricer
        data = pd.DataFrame({"price": [0.5, 0.6]}, index=pd.to_datetime(["2026-01-01", "2026-01-02"]))
        pricer = EventContractPricer(data=data, meta_data={"ticker": "TEST"})
        assert len(pricer.data) == 2
        assert pricer.meta_data["ticker"] == "TEST"

    def test_latest_price(self):
        from MDP.EventContracts.EventContractsMDP import EventContractPricer
        data = pd.DataFrame({"price": [0.5, 0.65]}, index=pd.to_datetime(["2026-01-01", "2026-01-02"]))
        pricer = EventContractPricer(data=data, meta_data={})
        assert pricer.latest_price() == pytest.approx(0.65)


class TestEventContractsMDP:
    def test_construction_kalshi(self):
        from MDP.EventContracts.EventContractsMDP import EventContractsMDP
        mdp = EventContractsMDP(source="KALSHI")
        assert mdp.source == "KALSHI"

    def test_construction_polymarket(self):
        from MDP.EventContracts.EventContractsMDP import EventContractsMDP
        mdp = EventContractsMDP(source="POLYMARKET")
        assert mdp.source == "POLYMARKET"

    def test_invalid_source(self):
        from MDP.EventContracts.EventContractsMDP import EventContractsMDP
        with pytest.raises(ValueError, match="source must be"):
            EventContractsMDP(source="INVALID")

    def test_kalshi_market_ticker_metadata_resolution(self, monkeypatch):
        from MDP.EventContracts.EventContractsMDP import EventContractsMDP
        from MDP.EventContracts import kalshi_fetcher

        captured = {}

        def _fetch_market_metadata(ticker):
            assert ticker == "FEDHIKE-26DEC31"
            return {"event_ticker": "FEDHIKE"}

        def _fetch_event_metadata(event_ticker):
            assert event_ticker == "FEDHIKE"
            return {"series_ticker": "KXFEDHIKE"}

        def _fetch_live_candlesticks(**kwargs):
            captured.update(kwargs)
            return pd.DataFrame(
                {"close": [0.23], "volume": [1.0], "open_interest": [100.0]},
                index=pd.to_datetime(["2026-03-24T16:00:00Z"]),
            )

        def _fetch_event_candlesticks(**kwargs):
            raise AssertionError("market ticker should not resolve to the event endpoint")

        monkeypatch.setattr(kalshi_fetcher, "fetch_market_metadata", _fetch_market_metadata)
        monkeypatch.setattr(kalshi_fetcher, "fetch_event_metadata", _fetch_event_metadata)
        monkeypatch.setattr(kalshi_fetcher, "fetch_live_candlesticks", _fetch_live_candlesticks)
        monkeypatch.setattr(kalshi_fetcher, "fetch_event_candlesticks", _fetch_event_candlesticks)

        mdp = EventContractsMDP(source="KALSHI")
        pricer = mdp.get_pricer(
            {
                "ticker": "FEDHIKE-26DEC31",
                "start": datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
                "end": datetime.datetime(2026, 3, 24, tzinfo=datetime.timezone.utc),
                "period_interval": 60,
                "api_key_id": "key",
                "private_key_pem": "pem",
            }
        )

        assert captured["series_ticker"] == "KXFEDHIKE"
        assert captured["ticker"] == "FEDHIKE-26DEC31"
        assert pricer.latest_price() == pytest.approx(0.23)


class TestKalshiFetcher:
    def test_parse_candlestick_response_carries_previous_price_for_empty_market_candle(self):
        from MDP.EventContracts.kalshi_fetcher import parse_candlestick_response

        raw = {
            "candlesticks": [
                {
                    "end_period_ts": 1767243600,
                    "price": {"previous_dollars": "0.1300"},
                    "volume_fp": "0.00",
                    "open_interest_fp": "52710.00",
                }
            ]
        }

        df = parse_candlestick_response(raw)
        row = df.iloc[0]

        assert row["open"] == pytest.approx(0.13)
        assert row["high"] == pytest.approx(0.13)
        assert row["low"] == pytest.approx(0.13)
        assert row["close"] == pytest.approx(0.13)
        assert row["mean"] == pytest.approx(0.13)
        assert row["previous"] == pytest.approx(0.13)
        assert row["volume"] == pytest.approx(0.0)
        assert row["open_interest"] == pytest.approx(52710.0)
