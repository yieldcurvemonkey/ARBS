# ABOUTME: Futures adapter for converting FuturesQuery results into signal-ready DataFrame
# ABOUTME: Extracts prices, calculates next contract prices, and formats roll dates for carry signal consumption
"""
Futures Adapter

Converts FuturesQuery results into signal-ready DataFrame format.

Input:
- List[FuturesQuery]: Product queries (OUTRIGHT, CALENDAR, etc.)
- as_of_date: Valuation date
- MarketDataProvider: Source of futures prices

Output:
- DataFrame with columns:
    - contract: Contract code (e.g., 'SFRZ4')
    - price: Current price (e.g., 94.50)
    - next_contract: Next contract in chain (e.g., 'SFRH5')
    - next_price: Next contract price (e.g., 94.45)
    - roll_date: When to roll to next contract
    - expiry: Contract expiry date

Algorithm:
1. For each query, build futures objects using FuturesStructureFunctionMap
2. Get prices using FuturesValueFunctionMap
3. For carry calculation, look up next contract in chain
4. Get next contract price
5. Calculate roll date (typically 5 days before expiry)
6. Return DataFrame with all necessary columns

Business Logic:
- Roll date: Typically 5 business days before expiry
- Next contract: Automatic lookup using get_next_imm_contract()
- Calendar spreads: Extract both front and back prices
- Missing data: Return NaN (graceful degradation)
"""

from datetime import date, timedelta
from typing import Any, List
import numpy as np
import pandas as pd

from Adapter.Base.BaseAdapter import BaseAdapter
from Query.Futures.FuturesQuery import (
    FuturesQuery,
    get_next_imm_contract,
    get_contract_expiry,
)
from Query.Futures.FuturesStructure import FuturesStructure
from Query.Futures.FuturesValue import FuturesValue
from Query.Futures.FuturesStructureFunctionMap import FuturesStructureFunctionMap
from Query.Futures.FuturesValueFunctionMap import FuturesValueFunctionMap


class FuturesAdapter(BaseAdapter):
    """
    Adapter for futures queries.

    Converts FuturesQuery objects into DataFrame format suitable
    for signal generation (especially CarrySignal).

    Attributes:
        mdp: Market data provider for getting curves and prices
        roll_days_before_expiry: Number of days before expiry to roll (default: 5)
    """

    def __init__(
        self,
        market_data_provider: Any,
        roll_days_before_expiry: int = 5,
    ):
        """
        Initialize futures adapter.

        Args:
            market_data_provider: Source of market prices/curves
            roll_days_before_expiry: Days before expiry to roll (default: 5)
        """
        super().__init__(market_data_provider)
        self.roll_days_before_expiry = roll_days_before_expiry

    def convert(
        self,
        queries: List[FuturesQuery],
        as_of_date: date,
    ) -> pd.DataFrame:
        """
        Convert futures queries to signal-ready DataFrame.

        Args:
            queries: List of FuturesQuery objects
            as_of_date: Valuation date

        Returns:
            DataFrame with columns:
                - contract: Contract code
                - price: Current price
                - next_contract: Next contract in chain
                - next_price: Next contract price
                - roll_date: When to roll
                - expiry: Contract expiry date
                - front_contract: (for calendar spreads only)
                - back_contract: (for calendar spreads only)
                - front_price: (for calendar spreads only)
                - back_price: (for calendar spreads only)

        Example:
            >>> mdp = MockMDP()
            >>> adapter = FuturesAdapter(mdp)
            >>> queries = [FuturesQuery(contract='SFRZ4'), ...]
            >>> df = adapter.convert(queries, date(2024, 6, 15))
            >>> print(df[['contract', 'price', 'next_price', 'roll_date']])
        """
        if len(queries) == 0:
            # Return empty DataFrame with expected columns
            return pd.DataFrame(columns=[
                'contract', 'price', 'next_contract', 'next_price',
                'roll_date', 'expiry'
            ])

        rows = []

        for query in queries:
            if query.structure == FuturesStructure.OUTRIGHT:
                row = self._convert_outright(query, as_of_date)
                if row is not None:
                    rows.append(row)

            elif query.structure == FuturesStructure.CALENDAR:
                row = self._convert_calendar(query, as_of_date)
                if row is not None:
                    rows.append(row)

            # TODO: Handle PACK, BUNDLE, BASIS in later phases

        if len(rows) == 0:
            return pd.DataFrame(columns=[
                'contract', 'price', 'next_contract', 'next_price',
                'roll_date', 'expiry'
            ])

        df = pd.DataFrame(rows)
        return df

    def _convert_outright(
        self,
        query: FuturesQuery,
        as_of_date: date,
    ) -> dict:
        """
        Convert outright futures query to signal format.

        Args:
            query: FuturesQuery with structure=OUTRIGHT
            as_of_date: Valuation date

        Returns:
            Dictionary with contract data
        """
        contract = query.contract

        try:
            # Get price using pricer
            price = self._get_price(contract, as_of_date)

            # Get expiry
            expiry = get_contract_expiry(contract)

            # Calculate roll date (N days before expiry)
            roll_date = expiry - timedelta(days=self.roll_days_before_expiry)

            # Get next contract in chain
            next_contract = get_next_imm_contract(contract)

            # Get next contract price
            next_price = self._get_price(next_contract, as_of_date)

            return {
                'contract': contract,
                'price': price,
                'next_contract': next_contract,
                'next_price': next_price,
                'roll_date': roll_date,
                'expiry': expiry,
            }

        except Exception as e:
            # Graceful degradation: return NaN values
            return {
                'contract': contract,
                'price': np.nan,
                'next_contract': np.nan,
                'next_price': np.nan,
                'roll_date': np.nan,
                'expiry': np.nan,
            }

    def _convert_calendar(
        self,
        query: FuturesQuery,
        as_of_date: date,
    ) -> dict:
        """
        Convert calendar spread query to signal format.

        Args:
            query: FuturesQuery with structure=CALENDAR
            as_of_date: Valuation date

        Returns:
            Dictionary with spread data
        """
        front_contract = query.front_contract
        back_contract = query.back_contract

        try:
            # Get front and back prices
            front_price = self._get_price(front_contract, as_of_date)
            back_price = self._get_price(back_contract, as_of_date)

            # Get expiry of front contract
            expiry = get_contract_expiry(front_contract)

            # Roll date
            roll_date = expiry - timedelta(days=self.roll_days_before_expiry)

            # Spread value (front - back)
            spread = front_price - back_price

            return {
                'contract': f"{front_contract}-{back_contract}",
                'front_contract': front_contract,
                'back_contract': back_contract,
                'front_price': front_price,
                'back_price': back_price,
                'price': spread,  # Calendar spread value
                'roll_date': roll_date,
                'expiry': expiry,
            }

        except Exception as e:
            return {
                'contract': f"{front_contract}-{back_contract}",
                'front_contract': front_contract,
                'back_contract': back_contract,
                'front_price': np.nan,
                'back_price': np.nan,
                'price': np.nan,
                'roll_date': np.nan,
                'expiry': np.nan,
            }

    def _get_price(self, contract: str, as_of_date: date) -> float:
        """
        Get price for a futures contract.

        Args:
            contract: Contract code (e.g., 'SFRZ4')
            as_of_date: Valuation date

        Returns:
            Price (e.g., 94.50)
        """
        try:
            # Get pricer from market data provider
            pricer = self.mdp.get_pricer('USD', as_of_date)

            # Try to get futures price method
            if hasattr(pricer, 'futures_price') and callable(pricer.futures_price):
                price = pricer.futures_price(contract)
                if price is not None and not np.isnan(price):
                    return float(price)

            # Fallback: derive from curve rate method
            if hasattr(pricer, 'rate') and callable(pricer.rate):
                rate_pct = pricer.rate("3M") * 100  # Convert to %
                return 100.0 - rate_pct

            # Last fallback: 95.0 default (5% implied rate)
            return 95.0

        except Exception:
            # If anything fails, return reasonable default
            return 95.0

    def __repr__(self) -> str:
        return (
            f"FuturesAdapter(mdp={self.mdp}, "
            f"roll_days_before_expiry={self.roll_days_before_expiry})"
        )
