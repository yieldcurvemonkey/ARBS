"""
Futures Query Object

Main query interface for futures backtesting.
Follows the pattern of IRSwapQuery for consistency.

Contract Code Format:
    SFR = 3-Month SOFR futures
    Z = December
    4 = 2024
    => SFRZ4 = December 2024 3-Month SOFR futures

IMM Month Codes:
    H = March
    M = June
    U = September
    Z = December

Pack Colors (4 consecutive contracts):
    WHITE = contracts 1-4
    RED = contracts 2-5
    GREEN = contracts 3-6
    BLUE = contracts 4-7
    GOLD = contracts 5-8

Note: ED (Eurodollar) futures were discontinued in June 2023.
      Use SFR (3-Month SOFR) for current/forward backtests.
"""

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional, Any
from enum import Enum

from Query.Base.BaseQuery import BaseQuery
from Query.Futures.FuturesStructure import FuturesStructure
from Query.Futures.FuturesValue import FuturesValue


# =============================================================================
# Constants
# =============================================================================

# IMM Month codes (quarterly contracts)
IMM_MONTH_CODES = {
    'H': 3,   # March
    'M': 6,   # June
    'U': 9,   # September
    'Z': 12,  # December
}

# Reverse mapping
IMM_MONTHS_TO_CODES = {v: k for k, v in IMM_MONTH_CODES.items()}

# Pack colors for STIR futures
PACK_COLORS = {
    "WHITE": 0,  # Start offset
    "RED": 1,
    "GREEN": 2,
    "BLUE": 3,
    "GOLD": 4,
    "PURPLE": 5,
    "ORANGE": 6,
    "PINK": 7,
}

# Contract specifications (can be extended for other products)
CONTRACT_SPECS = {
    "SFR": {  # 3-Month SOFR (current standard)
        "multiplier": 2500.0,
        "tick_size": 0.0025,       # 0.25bp = $6.25
        "currency": "USD",
        "product_type": "STIR",
    },
    "ED": {  # Eurodollar (discontinued June 2023, kept for historical backtests)
        "multiplier": 2500.0,      # $2500 per bp
        "tick_size": 0.005,        # 0.5bp = $12.50
        "currency": "USD",
        "product_type": "STIR",
    },
    "ZN": {  # 10-Year Treasury Note
        "multiplier": 1000.0,      # $1000 per 1/32
        "tick_size": 0.015625,     # 1/64 of a point
        "currency": "USD",
        "product_type": "BOND",
    },
}


# =============================================================================
# Helper Functions
# =============================================================================

def parse_futures_contract(contract: str) -> Dict[str, Any]:
    """
    Parse futures contract code into components.

    Args:
        contract: Contract code (e.g., "SFRZ4")

    Returns:
        Dict with keys: prefix, month_code, year_digit, year, month

    Examples:
        >>> parse_futures_contract("SFRZ4")
        {'prefix': 'SFR', 'month_code': 'Z', 'year_digit': '4',
         'year': 2024, 'month': 12}
    """
    # Match pattern: 2+ letters, 1 letter (month), 1 digit (year)
    pattern = r'^([A-Z]{2,})([HMUZ])(\d)$'
    match = re.match(pattern, contract.upper())

    if not match:
        raise ValueError(f"Invalid contract code: {contract}")

    prefix, month_code, year_digit = match.groups()

    if month_code not in IMM_MONTH_CODES:
        raise ValueError(f"Invalid month code: {month_code}")

    month = IMM_MONTH_CODES[month_code]

    # Determine year from digit (assume 2020s for now)
    # More sophisticated logic could use current year as reference
    year = 2020 + int(year_digit)

    return {
        'prefix': prefix,
        'month_code': month_code,
        'year_digit': year_digit,
        'year': year,
        'month': month,
    }


def get_contract_expiry(contract: str) -> date:
    """
    Get expiry date from contract code.

    IMM dates are the third Wednesday of Mar/Jun/Sep/Dec.

    Args:
        contract: Contract code (e.g., "SFRZ4")

    Returns:
        Expiry date (third Wednesday of contract month)

    Examples:
        >>> get_contract_expiry("SFRZ4")
        datetime.date(2024, 12, 18)
    """
    parsed = parse_futures_contract(contract)
    year = parsed['year']
    month = parsed['month']

    # Find third Wednesday of the month
    first_day = date(year, month, 1)

    # Find first Wednesday (weekday 2)
    days_until_wed = (2 - first_day.weekday()) % 7
    if days_until_wed == 0 and first_day.weekday() != 2:
        days_until_wed = 7

    first_wed = first_day + timedelta(days=days_until_wed)
    third_wed = first_wed + timedelta(weeks=2)

    return third_wed


def get_next_imm_contract(contract: str) -> str:
    """
    Get the next quarterly IMM contract.

    Args:
        contract: Current contract (e.g., "SFRZ4")

    Returns:
        Next contract (e.g., "SFRH5")

    Examples:
        >>> get_next_imm_contract("SFRZ4")
        "SFRH5"
        >>> get_next_imm_contract("SFRU5")
        "SFRZ5"
    """
    parsed = parse_futures_contract(contract)
    prefix = parsed['prefix']
    year = parsed['year']
    month = parsed['month']

    # Next IMM month
    imm_months = sorted(IMM_MONTH_CODES.values())
    current_idx = imm_months.index(month)

    if current_idx == len(imm_months) - 1:
        # Roll to next year
        next_month = imm_months[0]
        next_year = year + 1
    else:
        next_month = imm_months[current_idx + 1]
        next_year = year

    next_month_code = IMM_MONTHS_TO_CODES[next_month]
    next_year_digit = str(next_year)[-1]

    return f"{prefix}{next_month_code}{next_year_digit}"


def get_contract_chain(contract: str, count: int) -> List[str]:
    """
    Get a chain of consecutive quarterly contracts.

    Args:
        contract: Starting contract
        count: Number of contracts to return

    Returns:
        List of contract codes

    Examples:
        >>> get_contract_chain("SFRZ4", 4)
        ["SFRZ4", "SFRH5", "SFRM5", "SFRU5"]
    """
    chain = [contract]
    current = contract

    for _ in range(count - 1):
        current = get_next_imm_contract(current)
        chain.append(current)

    return chain


def get_pack_contracts(
    base_contract: str,
    color: str = "WHITE"
) -> List[str]:
    """
    Get contracts for a pack (4 consecutive quarters).

    Args:
        base_contract: First contract in the series
        color: Pack color (WHITE, RED, GREEN, BLUE, GOLD)

    Returns:
        List of 4 contract codes

    Examples:
        >>> get_pack_contracts("SFRH5", "RED")
        ["SFRM5", "SFRU5", "SFRZ5", "SFRH6"]  # Skip first, take next 4
    """
    offset = PACK_COLORS.get(color.upper(), 0)

    # Get enough contracts for offset + 4
    chain = get_contract_chain(base_contract, offset + 4)

    # Return 4 contracts starting from offset
    return chain[offset:offset + 4]


# =============================================================================
# FuturesQuery Dataclass
# =============================================================================

@dataclass(frozen=True)
class FuturesQuery(BaseQuery):
    """
    Futures-specific Query entry point.

    User-facing args for different structures:

    OUTRIGHT:
        contract: Contract code (e.g., "SFRZ4")
        quantity: Number of contracts (default 1.0)

    CALENDAR:
        front_contract: Near contract
        back_contract: Far contract
        quantity: Number of spreads

    PACK:
        pack_color: "WHITE", "RED", "GREEN", "BLUE", "GOLD"
        or first_contract: Explicit first contract
        quantity: Number of packs

    BUNDLE:
        bundle_start_contract: First contract in bundle
        quantity: Number of bundles

    BASIS:
        contract: Futures contract
        swap_tenor: Matched swap tenor (e.g., "3M")
        quantity: Number of basis positions
    """

    structure: FuturesStructure = FuturesStructure.OUTRIGHT
    value: FuturesValue = FuturesValue.PRICE

    # Common fields
    contract: Optional[str] = None
    currency: str = "USD"
    quantity: float = 1.0

    # Contract specifications (auto-populated from contract code)
    product_type: str = "STIR"
    multiplier: float = 2500.0  # Default for SFR/SOFR
    tick_size: float = 0.0025   # Default for SFR (0.25bp = $6.25)
    expiry: Optional[date] = None

    # Calendar spread fields
    front_contract: Optional[str] = None
    back_contract: Optional[str] = None

    # Pack/Bundle fields
    pack_color: Optional[str] = None
    bundle_start_contract: Optional[str] = None

    # Basis fields
    swap_tenor: Optional[str] = None

    # Metadata
    label: Optional[str] = None
    tags: List[str] = field(default_factory=list)

    def __post_init__(self):
        """
        Post-initialization to set derived fields.

        - Parse contract specs
        - Calculate expiry if not provided
        - Validate structure-specific fields
        """
        # Use object.__setattr__ since dataclass is frozen
        if self.contract:
            try:
                parsed = parse_futures_contract(self.contract)
                prefix = parsed['prefix']

                # Look up contract specs
                if prefix in CONTRACT_SPECS:
                    specs = CONTRACT_SPECS[prefix]
                    if self.multiplier == 2500.0:  # Only override if still default
                        object.__setattr__(self, 'multiplier', specs['multiplier'])
                    if self.tick_size == 0.0025:  # SFR default
                        object.__setattr__(self, 'tick_size', specs['tick_size'])
                    if self.currency == "USD":
                        object.__setattr__(self, 'currency', specs['currency'])
                    object.__setattr__(self, 'product_type', specs['product_type'])

                # Calculate expiry if not provided
                if self.expiry is None:
                    expiry = get_contract_expiry(self.contract)
                    object.__setattr__(self, 'expiry', expiry)

            except ValueError:
                # Invalid contract code - let it pass, will be caught later
                pass

    def __add__(self, other: 'FuturesQuery') -> 'FuturesQuery':
        """
        Add two futures queries.

        Creates a composite position (both legs positive).
        """
        # For now, just return self (basic implementation)
        # Full implementation would create a composite query
        return self

    def __sub__(self, other: 'FuturesQuery') -> 'FuturesQuery':
        """
        Subtract two futures queries.

        Creates a spread (first positive, second negative).
        """
        # For now, just return self (basic implementation)
        # Full implementation would create a calendar spread query
        return self

    def __mul__(self, scalar: float) -> 'FuturesQuery':
        """
        Multiply futures query by scalar.

        Scales the quantity.
        """
        from dataclasses import replace
        return replace(self, quantity=self.quantity * scalar)

    def __repr__(self) -> str:
        """String representation."""
        if self.structure == FuturesStructure.OUTRIGHT:
            return f"FuturesQuery(OUTRIGHT, {self.contract}, qty={self.quantity})"
        elif self.structure == FuturesStructure.CALENDAR:
            return f"FuturesQuery(CALENDAR, {self.front_contract}-{self.back_contract})"
        elif self.structure == FuturesStructure.PACK:
            return f"FuturesQuery(PACK, {self.pack_color})"
        elif self.structure == FuturesStructure.BUNDLE:
            return f"FuturesQuery(BUNDLE, from {self.bundle_start_contract})"
        elif self.structure == FuturesStructure.BASIS:
            return f"FuturesQuery(BASIS, {self.contract} vs {self.swap_tenor})"
        return f"FuturesQuery({self.structure}, {self.value})"

    # =============================================================================
    # Abstract method implementations from BaseQuery
    # =============================================================================

    def return_query(self) -> List['FuturesQuery']:
        """
        Return list of queries.

        For single-valued queries, returns [self].
        For list-valued queries, expands into separate queries.
        """
        # Simple implementation: just return self wrapped in list
        # Could be extended to handle multiple values
        return [self]

    def col_name(self, cube_name: Optional[str] = None) -> str:
        """
        Human-friendly label for dataframes/plots.

        Returns a readable name for this query, used in:
        - DataFrame column names
        - Plot labels
        - Export files
        """
        if self.label:
            return self.label

        # Build name from structure and contract
        if self.structure == FuturesStructure.OUTRIGHT:
            if self.contract:
                return f"{self.contract}"
            return "Future"
        elif self.structure == FuturesStructure.CALENDAR:
            return f"{self.front_contract}-{self.back_contract}"
        elif self.structure == FuturesStructure.PACK:
            return f"{self.pack_color}Pack"
        elif self.structure == FuturesStructure.BUNDLE:
            return f"Bundle({self.bundle_start_contract})"
        elif self.structure == FuturesStructure.BASIS:
            return f"{self.contract}vSwap"

        return "FuturesQuery"

    def eval_expression(self, cube_name: Optional[str] = None, ignore_risk_weight: bool = False) -> str:
        """
        Return an evaluable expression string for this query.

        Used for:
        - Building computation graphs
        - Generating formulas for exports
        - Documentation

        Args:
            cube_name: Optional cube name for context
            ignore_risk_weight: If True, don't include risk weighting

        Returns:
            String expression like "`EDZ4`" or "2.0 * `EDZ4`"
        """
        col = self.col_name(cube_name=cube_name)

        # Include quantity scaling if significant
        if self.quantity != 1.0 and not ignore_risk_weight:
            return f"{self.quantity} * `{col}`"

        return f"`{col}`"
