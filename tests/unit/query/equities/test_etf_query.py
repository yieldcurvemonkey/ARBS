# ABOUTME: Unit tests for ETFQuery class
# ABOUTME: Tests ETF query construction, validation, and value type restrictions

import pytest
from datetime import date, timedelta
from Query.Equities.ETFQuery import ETFQuery
from Query.Equities.EquityValue import EquityValue


class TestETFQuery:
    """Test suite for ETFQuery."""

    def test_create_basic_etf_query(self):
        """Test creating a basic ETF query."""
        query = ETFQuery(
            ticker="XLK",
            sector="Information Technology",
            value=EquityValue.PRICE,
        )

        assert query.ticker == "XLK"
        assert query.sector == "Information Technology"
        assert query.value == EquityValue.PRICE
        assert query.lookback_days == 252  # default
        assert query.weight == 1.0  # default

    def test_create_query_with_returns(self):
        """Test creating ETF query with RETURN value type."""
        query = ETFQuery(
            ticker="XLF",
            sector="Financials",
            value=EquityValue.RETURN,
            lookback_days=126,
        )

        assert query.ticker == "XLF"
        assert query.value == EquityValue.RETURN
        assert query.lookback_days == 126

    def test_build_mdp_request(self):
        """Test building MDP request for ETF."""
        query = ETFQuery(
            ticker="XLK",
            sector="Information Technology",
            value=EquityValue.PRICE,
        )

        as_of_date = date(2024, 12, 31)
        request = query.build_mdp_request(as_of_date)

        assert request["ticker"] == "XLK"
        assert request["end_date"] == as_of_date
        assert request["start_date"] == as_of_date - timedelta(days=252)
        assert request["fields"] == ["price", "volume"]  # ETFs don't have fundamentals
        assert request["adjusted"] is True

    def test_validation_rejects_fundamentals(self):
        """Test ETF query rejects fundamental value types."""
        with pytest.raises(ValueError, match="ETFs only support PRICE/RETURN/LOG_RETURN"):
            ETFQuery(
                ticker="XLK",
                sector="Information Technology",
                value=EquityValue.DIVIDEND_YIELD,
            )

    def test_validation_rejects_earnings_yield(self):
        """Test ETF query rejects earnings yield."""
        with pytest.raises(ValueError, match="ETFs only support PRICE/RETURN/LOG_RETURN"):
            ETFQuery(
                ticker="XLK",
                sector="Information Technology",
                value=EquityValue.EARNINGS_YIELD,
            )

    def test_validation_accepts_price(self):
        """Test ETF query accepts PRICE value type."""
        query = ETFQuery(
            ticker="XLK",
            sector="Information Technology",
            value=EquityValue.PRICE,
        )
        assert query.value == EquityValue.PRICE

    def test_validation_accepts_return(self):
        """Test ETF query accepts RETURN value type."""
        query = ETFQuery(
            ticker="XLK",
            sector="Information Technology",
            value=EquityValue.RETURN,
        )
        assert query.value == EquityValue.RETURN

    def test_validation_accepts_log_return(self):
        """Test ETF query accepts LOG_RETURN value type."""
        query = ETFQuery(
            ticker="XLK",
            sector="Information Technology",
            value=EquityValue.LOG_RETURN,
        )
        assert query.value == EquityValue.LOG_RETURN

    def test_validation_empty_ticker(self):
        """Test validation fails for empty ticker."""
        with pytest.raises(ValueError, match="Ticker cannot be empty"):
            ETFQuery(
                ticker="",
                sector="Information Technology",
                value=EquityValue.PRICE,
            )

    def test_validation_negative_lookback(self):
        """Test validation fails for negative lookback days."""
        with pytest.raises(ValueError, match="Lookback days must be positive"):
            ETFQuery(
                ticker="XLK",
                sector="Information Technology",
                value=EquityValue.PRICE,
                lookback_days=-5,
            )

    def test_sector_etf_examples(self):
        """Test creating queries for all sector ETFs."""
        sector_etfs = [
            ("XLK", "Information Technology"),
            ("XLF", "Financials"),
            ("XLV", "Health Care"),
            ("XLE", "Energy"),
            ("XLY", "Consumer Discretionary"),
            ("XLP", "Consumer Staples"),
            ("XLI", "Industrials"),
            ("XLB", "Materials"),
            ("XLRE", "Real Estate"),
            ("XLC", "Communication Services"),
            ("XLU", "Utilities"),
        ]

        for ticker, sector in sector_etfs:
            query = ETFQuery(
                ticker=ticker,
                sector=sector,
                value=EquityValue.RETURN,
            )
            assert query.ticker == ticker
            assert query.sector == sector

    def test_custom_weight(self):
        """Test ETF query with custom weight."""
        query = ETFQuery(
            ticker="XLK",
            sector="Information Technology",
            value=EquityValue.PRICE,
            weight=-1.0,  # Short position
        )
        assert query.weight == -1.0

    def test_metadata_field(self):
        """Test metadata field works for ETFs."""
        query = ETFQuery(
            ticker="XLK",
            sector="Information Technology",
            value=EquityValue.RETURN,
            metadata={"hedge": True, "sector_neutral": True},
        )

        assert query.metadata["hedge"] is True
        assert query.metadata["sector_neutral"] is True
