# ABOUTME: Query structure for sector ETF instruments
# ABOUTME: Simplified vs EquityQuery (no fundamentals, pure sector exposure)

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict
from Query.Base.BaseQuery import BaseQuery
from Query.Equities.EquityValue import EquityValue


@dataclass(frozen=True)
class ETFQuery(BaseQuery):
    """
    Query for sector ETF data from Yahoo Finance.

    ETFs don't have fundamentals (P/E, ROE, etc.), so only price/return queries supported.
    Used for sector hedging in market-neutral strategies.

    Attributes:
        ticker: ETF ticker (e.g., "XLK", "XLF")
        sector: Corresponding GICS sector
        value: Type of value to retrieve (PRICE or RETURN only)
        lookback_days: Historical data window
        weight: Portfolio weight
        metadata: Additional query metadata

    Example:
        >>> query = ETFQuery(
        ...     ticker="XLK",
        ...     sector="Information Technology",
        ...     value=EquityValue.RETURN,
        ... )
    """

    ticker: str = ""
    sector: str = ""
    value: EquityValue = EquityValue.PRICE
    lookback_days: int = 252
    weight: float = 1.0
    metadata: Dict = field(default_factory=dict)

    def build_mdp_request(self, as_of_date: date) -> dict:
        """
        Convert to MDP request (simpler than EquityQuery).

        Args:
            as_of_date: Reference date for query

        Returns:
            Dictionary with MDP request parameters
        """
        start_date = as_of_date - timedelta(days=self.lookback_days)

        return {
            "ticker": self.ticker,
            "start_date": start_date,
            "end_date": as_of_date,
            "fields": ["price", "volume"],  # ETFs don't have fundamentals
            "adjusted": True,
        }

    def validate(self) -> bool:
        """
        Validate ETF query parameters.

        Returns:
            True if valid

        Raises:
            ValueError: If parameters are invalid
        """
        if not self.ticker:
            raise ValueError("Ticker cannot be empty")

        if self.value not in [EquityValue.PRICE, EquityValue.RETURN, EquityValue.LOG_RETURN]:
            raise ValueError(
                f"ETFs only support PRICE/RETURN/LOG_RETURN values, got {self.value}"
            )

        if self.lookback_days < 1:
            raise ValueError("Lookback days must be positive")

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
        return f"ETFQuery({self.ticker}, {self.sector})"
