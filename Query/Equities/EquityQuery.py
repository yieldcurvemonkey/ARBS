# ABOUTME: Query structure for individual equity instruments
# ABOUTME: Supports GICS sector classification and fundamental data retrieval

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, Optional
from Query.Base.BaseQuery import BaseQuery
from Query.Equities.EquityStructure import EquityStructure
from Query.Equities.EquityValue import EquityValue


@dataclass(frozen=True)
class EquityQuery(BaseQuery):
    """
    Query for individual stock data from Yahoo Finance.

    Attributes:
        ticker: Stock ticker symbol (e.g., "AAPL", "MSFT")
        sector: GICS Level 1 sector (11 sectors)
        structure: Portfolio structure type
        value: Type of value to retrieve
        lookback_days: Historical data window (default: 252 trading days = 1 year)
        weight: Portfolio weight (default: 1.0)
        metadata: Additional query metadata

    Example:
        >>> query = EquityQuery(
        ...     ticker="AAPL",
        ...     sector="Information Technology",
        ...     structure=EquityStructure.SINGLE,
        ...     value=EquityValue.RETURN,
        ...     lookback_days=252,
        ... )
    """

    ticker: str = ""
    sector: str = ""
    structure: EquityStructure = EquityStructure.SINGLE
    value: EquityValue = EquityValue.PRICE
    lookback_days: int = 252
    weight: float = 1.0
    metadata: Dict = field(default_factory=dict)

    def build_mdp_request(self, as_of_date: date) -> dict:
        """
        Convert to market data provider request format.

        Args:
            as_of_date: Reference date for query

        Returns:
            Dictionary with MDP request parameters
        """
        start_date = as_of_date - timedelta(days=self.lookback_days)

        # Determine required fields based on value type
        fields = ["price", "volume"]
        if self.value in [EquityValue.DIVIDEND_YIELD, EquityValue.EARNINGS_YIELD]:
            fields.extend(["dividend", "earnings"])

        return {
            "ticker": self.ticker,
            "start_date": start_date,
            "end_date": as_of_date,
            "fields": fields,
            "adjusted": True,  # Adjust for splits/dividends
        }

    def validate(self) -> bool:
        """
        Validate query parameters.

        Returns:
            True if valid

        Raises:
            ValueError: If parameters are invalid
        """
        if not self.ticker or len(self.ticker) == 0:
            raise ValueError("Ticker cannot be empty")

        if self.lookback_days < 1:
            raise ValueError("Lookback days must be positive")

        if not self.sector:
            raise ValueError("Sector must be specified")

        return True

    def __post_init__(self):
        """Validate after initialization."""
        self.validate()

    # Abstract method implementations from BaseQuery
    def return_query(self):
        """Return list of queries."""
        return [self]

    def col_name(self, cube_name=None):
        """Human-friendly column name."""
        return f"{self.ticker}"

    def eval_expression(self, cube_name=None):
        """Return evaluable expression string."""
        return f"EquityQuery({self.ticker}, {self.sector})"
