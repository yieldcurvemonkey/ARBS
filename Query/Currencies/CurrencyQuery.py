# ABOUTME: Query structure for currency/tenor point instruments
# ABOUTME: Supports fixed income structures (outright, butterfly, spread, calendar)

from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional
from Query.Base.BaseQuery import BaseQuery
from Query.Currencies.CurrencyStructure import CurrencyStructure
from Query.Currencies.CurrencyValue import CurrencyValue


# Valid currencies and tenors
VALID_CURRENCIES = ["USD", "EUR", "GBP", "CHF", "JPY", "AUD", "CAD"]
VALID_TENORS = ["2Y", "5Y", "10Y", "30Y"]


@dataclass(frozen=True)
class CurrencyQuery(BaseQuery):
    """
    Query for currency tenor point data.

    This is the currency equivalent of EquityQuery:
    - Currency (USD, EUR, etc.) ↔ Sector (Tech, Finance, etc.)
    - Tenor (2Y, 5Y, 10Y, 30Y) ↔ Stock (AAPL, MSFT, etc.)

    Attributes:
        currency: Currency code (USD, EUR, GBP, CHF, JPY, AUD, CAD)
        tenor: Tenor point (2Y, 5Y, 10Y, 30Y)
        structure: Portfolio structure type (OUTRIGHT, BUTTERFLY, SPREAD, CALENDAR)
        value: Type of value to retrieve (YIELD, CARRY, RETURN, DV01)
        weight: Portfolio weight (default: 1.0)
        metadata: Additional query metadata

    Example:
        >>> # Outright position
        >>> query = CurrencyQuery(
        ...     currency="USD",
        ...     tenor="10Y",
        ...     structure=CurrencyStructure.OUTRIGHT,
        ...     value=CurrencyValue.YIELD,
        ... )
        >>>
        >>> # Butterfly trade (2s5s10s)
        >>> query = CurrencyQuery(
        ...     currency="EUR",
        ...     tenor="5Y",  # belly
        ...     structure=CurrencyStructure.BUTTERFLY,
        ...     value=CurrencyValue.CARRY,
        ... )
    """

    currency: str = ""
    tenor: str = ""
    structure: CurrencyStructure = CurrencyStructure.OUTRIGHT
    value: CurrencyValue = CurrencyValue.YIELD
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
        return {
            "currency": self.currency,
            "tenor": self.tenor,
            "as_of_date": as_of_date,
            "structure": self.structure.value,
            "value_type": self.value.value,
        }

    def validate(self) -> bool:
        """
        Validate query parameters.

        Returns:
            True if valid

        Raises:
            ValueError: If parameters are invalid
        """
        if not self.currency or len(self.currency) == 0:
            raise ValueError("Currency cannot be empty")

        if not self.tenor or len(self.tenor) == 0:
            raise ValueError("Tenor cannot be empty")

        if self.currency not in VALID_CURRENCIES:
            raise ValueError(
                f"Invalid currency: {self.currency}. "
                f"Valid currencies: {', '.join(VALID_CURRENCIES)}"
            )

        if self.tenor not in VALID_TENORS:
            raise ValueError(
                f"Invalid tenor: {self.tenor}. "
                f"Valid tenors: {', '.join(VALID_TENORS)}"
            )

        return True

    def __post_init__(self):
        """Validate after initialization."""
        self.validate()

    # Abstract method implementations from BaseQuery
    def return_query(self) -> List["CurrencyQuery"]:
        """
        Return list of queries.

        For single query, returns list containing self.
        For complex structures (butterfly), could return constituent queries.
        """
        return [self]

    def col_name(self, cube_name: Optional[str] = None) -> str:
        """
        Human-friendly column name.

        Format: {currency}_{tenor} (e.g., "USD_10Y")
        For butterflies: {currency}_{tenor}_fly (e.g., "EUR_5Y_fly")
        """
        base = f"{self.currency}_{self.tenor}"

        if self.structure == CurrencyStructure.BUTTERFLY:
            return f"{base}_fly"
        elif self.structure == CurrencyStructure.SPREAD:
            return f"{base}_spread"
        elif self.structure == CurrencyStructure.CALENDAR:
            return f"{base}_cal"
        else:
            return base

    def eval_expression(self, cube_name: Optional[str] = None) -> str:
        """
        Return evaluable expression string.

        For OUTRIGHT: Simple reference (e.g., "USD_10Y")
        For BUTTERFLY: 2*(belly) - (wing1) - (wing2)
            E.g., tenor="5Y" → "2*USD_5Y - USD_2Y - USD_10Y"
        For SPREAD: (long_end) - (short_end)
            E.g., tenor="5Y" → "USD_5Y - USD_2Y"
        For CALENDAR: Forward - spot
            E.g., tenor="10Y" → "USD_10Y_3M - USD_10Y"
        """
        if self.structure == CurrencyStructure.OUTRIGHT:
            return f"{self.currency}_{self.tenor}"

        elif self.structure == CurrencyStructure.BUTTERFLY:
            # Butterfly: 2*(belly) - (wing1) - (wing2)
            # Map belly to wings (simplified)
            butterfly_map = {
                "5Y": ("2Y", "5Y", "10Y"),  # 2s5s10s
                "10Y": ("5Y", "10Y", "30Y"),  # 5s10s30s
            }

            if self.tenor in butterfly_map:
                wing1, belly, wing2 = butterfly_map[self.tenor]
                return f"2*{self.currency}_{belly} - {self.currency}_{wing1} - {self.currency}_{wing2}"
            else:
                # Fallback for unsupported belly
                return f"{self.currency}_{self.tenor}_butterfly"

        elif self.structure == CurrencyStructure.SPREAD:
            # Spread: (long_end) - (short_end)
            # Map tenor to spread (simplified)
            spread_map = {
                "5Y": ("2Y", "5Y"),  # 2Y5Y spread
                "10Y": ("5Y", "10Y"),  # 5Y10Y spread
                "30Y": ("10Y", "30Y"),  # 10Y30Y spread
            }

            if self.tenor in spread_map:
                short_end, long_end = spread_map[self.tenor]
                return f"{self.currency}_{long_end} - {self.currency}_{short_end}"
            else:
                return f"{self.currency}_{self.tenor}_spread"

        elif self.structure == CurrencyStructure.CALENDAR:
            # Calendar: forward - spot (simplified)
            return f"{self.currency}_{self.tenor}_fwd - {self.currency}_{self.tenor}"

        else:
            return f"{self.currency}_{self.tenor}"
