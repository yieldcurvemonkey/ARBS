"""
Generic accounting abstractions for backtesting.

This module provides abstract base classes and concrete implementations for:
- Settlement conventions (T+2, daily settlement, etc.)
- Margin conventions (no margin, futures margin, etc.)
- Roll conventions (days before expiry, quarterly, etc.)
- Cash flow tracking

These abstractions enable product-agnostic backtesting that works across
swaps, futures, bonds, and other instruments.

Design principles:
1. Abstract base classes define contracts
2. Concrete implementations are composable
3. Conventions can be mixed and matched per product
4. Easy to extend with new conventions
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import List, Optional, Any


# =============================================================================
# Cash Flow
# =============================================================================

@dataclass
class CashFlow:
    """
    Represents a cash flow on a specific date.

    Used to track all cash movements:
    - Variation margin
    - Initial margin
    - Settlement payments
    - Coupons
    - Principal repayments
    """
    date: date
    amount: float
    description: str = ""

    def __repr__(self) -> str:
        return f"CashFlow({self.date}, ${self.amount:,.2f}, '{self.description}')"


# =============================================================================
# Settlement Convention
# =============================================================================

class SettlementConvention(ABC):
    """
    Abstract base class for settlement conventions.

    Settlement conventions define when and how cash flows occur for a position.
    Different products have different settlement patterns:
    - Swaps: Net payments at coupon dates
    - Futures: Daily mark-to-market settlement
    - Bonds: Coupon payments and principal at maturity
    """

    @abstractmethod
    def calculate_cash_flows(
        self,
        position: Any,
        pricer: Any,
        t0: date,
        t1: date
    ) -> List[CashFlow]:
        """
        Calculate cash flows between t0 and t1.

        Args:
            position: The position (must have relevant pricing info)
            pricer: Pricer for valuation
            t0: Start date
            t1: End date

        Returns:
            List of CashFlow objects occurring between t0 and t1
        """
        pass


@dataclass
class StandardSettlement(SettlementConvention):
    """
    Standard T+N settlement (typical for swaps and bonds).

    Cash flows only occur at coupon dates and maturity.
    No daily settlement.
    """
    days: int = 2  # T+2 is standard

    def calculate_cash_flows(
        self,
        position: Any,
        pricer: Any,
        t0: date,
        t1: date
    ) -> List[CashFlow]:
        """
        For standard settlement, cash flows are discrete (coupons, maturity).
        Between arbitrary dates, typically no cash flows.

        In a full implementation, this would check if any coupon dates
        fall between t0 and t1 and calculate those payments.
        """
        # Simplified: No cash flows between arbitrary dates
        # A full implementation would check coupon schedule
        return []


@dataclass
class DailySettlement(SettlementConvention):
    """
    Daily mark-to-market settlement (typical for futures).

    Variation margin is paid/received daily based on price changes.
    """

    def calculate_cash_flows(
        self,
        position: Any,
        pricer: Any,
        t0: date,
        t1: date
    ) -> List[CashFlow]:
        """
        Calculate daily variation margin.

        For futures: VM = (Price_t1 - Price_t0) * Multiplier * Quantity
        """
        cash_flows = []

        # Check if position has price data
        if not hasattr(position, 'prev_price') or not hasattr(position, 'curr_price'):
            return cash_flows

        if not hasattr(position, 'multiplier'):
            # Default multiplier
            multiplier = getattr(position, 'multiplier', 1.0)
        else:
            multiplier = position.multiplier

        if not hasattr(position, 'quantity'):
            quantity = 1.0
        else:
            quantity = position.quantity

        # Calculate variation margin
        price_change = position.curr_price - position.prev_price
        vm = price_change * multiplier * quantity

        if abs(vm) > 1e-10:  # Only record if non-zero
            cash_flows.append(
                CashFlow(
                    date=t1,
                    amount=vm,
                    description=f"Daily settlement (variation margin)"
                )
            )

        return cash_flows


# =============================================================================
# Margin Convention
# =============================================================================

class MarginConvention(ABC):
    """
    Abstract base class for margin conventions.

    Margin conventions define how much collateral is required:
    - Initial margin (IM): Posted when opening a position
    - Variation margin (VM): Daily settlement based on price changes
    - Maintenance margin (MM): Minimum margin to keep position open
    """

    @abstractmethod
    def initial_margin(self, position: Any, pricer: Any) -> float:
        """
        Calculate initial margin required to open position.

        Args:
            position: The position
            pricer: Pricer for valuation

        Returns:
            Initial margin amount (always positive)
        """
        pass

    @abstractmethod
    def variation_margin(
        self,
        position: Any,
        pricer: Any,
        prev_price: float
    ) -> float:
        """
        Calculate variation margin based on price change.

        Args:
            position: The position
            pricer: Pricer for current valuation
            prev_price: Previous price/value

        Returns:
            Variation margin (positive = receive, negative = pay)
        """
        pass


@dataclass
class NoMargin(MarginConvention):
    """
    No margin required (typical for swaps, CSA agreements).

    Used for:
    - Plain vanilla swaps (no collateral)
    - Positions under CSA with zero threshold
    - Bonds (unless financing)
    """

    def initial_margin(self, position: Any, pricer: Any) -> float:
        """No initial margin."""
        return 0.0

    def variation_margin(
        self,
        position: Any,
        pricer: Any,
        prev_price: float
    ) -> float:
        """No variation margin."""
        return 0.0


@dataclass
class SimpleMargin(MarginConvention):
    """
    Simple percentage-of-notional margin.

    Simplified margin model:
    - IM = |Notional| * initial_rate
    - VM = Price change * Notional

    Good for backtesting when exact margin rules are not critical.
    """
    initial_rate: float = 0.03  # 3% of notional
    maintenance_rate: float = 0.02  # 2% of notional

    def initial_margin(self, position: Any, pricer: Any) -> float:
        """Calculate initial margin as % of notional."""
        # Get notional from position
        notional = abs(getattr(position, 'quantity', 1_000_000))
        return notional * self.initial_rate

    def variation_margin(
        self,
        position: Any,
        pricer: Any,
        prev_price: float
    ) -> float:
        """Calculate variation margin from price change."""
        # Simple approach: current NPV - previous NPV
        curr_npv = pricer.npv(position.package if hasattr(position, 'package') else position)

        # Estimate previous NPV (simplified)
        # In practice, this should be tracked
        notional = getattr(position, 'quantity', 1_000_000)

        # VM is the P&L
        # For simplicity, assume linear relationship
        # This is a mock - real implementation would track previous NPV
        return 0.0  # Placeholder


@dataclass
class FuturesMargin(MarginConvention):
    """
    Futures-style margin (initial + daily variation).

    Futures margin:
    - IM: Percentage of contract value (e.g., 3%)
    - VM: Daily settlement = (Price_t - Price_t-1) * Multiplier * Quantity

    This is a simplified model. Real futures margin uses SPAN or similar.
    """
    initial_rate: float = 0.03  # 3% of contract value

    def initial_margin(self, position: Any, pricer: Any) -> float:
        """
        Calculate initial margin for futures.

        IM = Price * Multiplier * Quantity * initial_rate
        """
        # Try to get current price
        if hasattr(position, 'curr_price'):
            price = position.curr_price
        elif hasattr(position, 'contract'):
            price = pricer.futures_price(position.contract)
        else:
            # Fallback: use NPV
            price = 95.0  # Default for STIR futures

        multiplier = getattr(position, 'multiplier', 2500.0)
        quantity = abs(getattr(position, 'quantity', 1.0))

        # Contract value
        contract_value = price * multiplier * quantity

        return contract_value * self.initial_rate

    def variation_margin(
        self,
        position: Any,
        pricer: Any,
        prev_price: float
    ) -> float:
        """
        Calculate variation margin for futures.

        VM = (Price_t - Price_t-1) * Multiplier * Quantity
        """
        # Get current price
        if hasattr(position, 'curr_price'):
            curr_price = position.curr_price
        elif hasattr(position, 'contract'):
            curr_price = pricer.futures_price(position.contract)
        else:
            curr_price = 95.0  # Fallback

        multiplier = getattr(position, 'multiplier', 2500.0)
        quantity = getattr(position, 'quantity', 1.0)

        # Price change in points
        price_change = curr_price - prev_price

        # VM (positive = receive, negative = pay)
        vm = price_change * multiplier * quantity

        return vm


# =============================================================================
# Roll Convention
# =============================================================================

class RollConvention(ABC):
    """
    Abstract base class for roll conventions.

    Roll conventions define when and how to roll positions:
    - Futures: Roll before expiry to next contract
    - Constant maturity: Roll to maintain constant maturity
    - Hold to maturity: No rolling

    Rolling is critical for:
    - Maintaining long-term exposure (e.g., continuous front contract)
    - Avoiding physical delivery
    - Rebalancing strategies
    """

    @abstractmethod
    def should_roll(self, position: Any, current_date: date) -> bool:
        """
        Determine if position should be rolled.

        Args:
            position: The position (must have expiry or maturity info)
            current_date: Current date

        Returns:
            True if position should be rolled, False otherwise
        """
        pass

    @abstractmethod
    def get_roll_target(self, position: Any, current_date: date) -> Optional[Any]:
        """
        Get the target to roll into.

        Args:
            position: Current position
            current_date: Current date

        Returns:
            New position/query to roll into, or None if no roll
        """
        pass


@dataclass
class NoRoll(RollConvention):
    """
    No rolling - hold position to maturity/expiry.

    Used for:
    - Buy-and-hold strategies
    - Positions held to maturity
    - Testing without roll complexity
    """

    def should_roll(self, position: Any, current_date: date) -> bool:
        """Never roll."""
        return False

    def get_roll_target(self, position: Any, current_date: date) -> Optional[Any]:
        """No roll target."""
        return None


@dataclass
class DaysBeforeExpiryRoll(RollConvention):
    """
    Roll N days before expiry.

    Common pattern:
    - Futures: Roll 5 days before expiry
    - Options: Roll 7 days before expiry
    - Bonds: Don't roll (use NoRoll instead)
    """
    days_before_expiry: int = 5

    def should_roll(self, position: Any, current_date: date) -> bool:
        """
        Roll if within N days of expiry.

        Returns True if:
        - current_date >= expiry - days_before_expiry
        """
        if not hasattr(position, 'expiry'):
            return False

        expiry = position.expiry
        if expiry is None:
            return False

        days_to_expiry = (expiry - current_date).days

        return days_to_expiry <= self.days_before_expiry

    def get_roll_target(self, position: Any, current_date: date) -> Optional[Any]:
        """
        Get next contract to roll into.

        This is a placeholder - actual implementation depends on product type.
        For futures, this would return the next quarterly contract.
        """
        # This is product-specific and would be implemented in subclasses
        # or handled by the backtest engine
        return None


@dataclass
class QuarterlyRoll(DaysBeforeExpiryRoll):
    """
    Roll to next quarterly contract (IMM dates).

    Used for:
    - STIR futures (SOFR, SOFR, etc.)
    - Quarterly bond futures
    - Other IMM-traded contracts

    IMM dates are the third Wednesday of March, June, September, December.
    """

    def get_roll_target(self, position: Any, current_date: date) -> Optional[Any]:
        """
        Get next quarterly IMM contract.

        This would construct a new query/position for the next quarterly
        contract (e.g., SFRH5 -> SFRM5).

        Actual implementation depends on product query structure.
        """
        # Placeholder - actual implementation would:
        # 1. Parse current contract code (e.g., "SFRH5")
        # 2. Determine next IMM month
        # 3. Construct new contract code
        # 4. Return new query/position

        # For now, return a marker that roll is needed
        if self.should_roll(position, current_date):
            return "NEXT_QUARTERLY"  # Placeholder

        return None


# =============================================================================
# Helper Functions
# =============================================================================

def get_next_imm_date(current_date: date) -> date:
    """
    Get the next IMM date (third Wednesday of Mar/Jun/Sep/Dec) after current_date.

    Args:
        current_date: Starting date

    Returns:
        Next IMM date
    """
    # IMM months
    imm_months = [3, 6, 9, 12]

    # Start from current month
    year = current_date.year
    month = current_date.month

    # Find next IMM month
    next_imm_months = [m for m in imm_months if m >= month]

    if not next_imm_months:
        # Roll to next year
        year += 1
        next_imm_month = imm_months[0]
    else:
        next_imm_month = next_imm_months[0]

    # Find third Wednesday of that month
    first_day = date(year, next_imm_month, 1)
    days_until_wed = (2 - first_day.weekday()) % 7  # Wednesday is 2
    first_wed = first_day + timedelta(days=days_until_wed)
    third_wed = first_wed + timedelta(weeks=2)

    # If we're already past this date, get next IMM
    if third_wed <= current_date:
        # Try next IMM month
        next_month_idx = (imm_months.index(next_imm_month) + 1) % 4
        if next_month_idx == 0:
            year += 1
        next_imm_month = imm_months[next_month_idx]

        first_day = date(year, next_imm_month, 1)
        days_until_wed = (2 - first_day.weekday()) % 7
        first_wed = first_day + timedelta(days=days_until_wed)
        third_wed = first_wed + timedelta(weeks=2)

    return third_wed


def get_contract_expiry(contract: str) -> date:
    """
    Get expiry date from contract code.

    Args:
        contract: Contract code (e.g., "SFRZ4" = Dec 2024 SOFR)

    Returns:
        Expiry date (third Wednesday of contract month)

    Contract codes:
    - Month codes: H=Mar, M=Jun, U=Sep, Z=Dec
    - Year: Last digit (e.g., 4=2024, 5=2025)
    """
    month_codes = {
        'H': 3,  # March
        'M': 6,  # June
        'U': 9,  # September
        'Z': 12,  # December
    }

    if len(contract) < 3:
        raise ValueError(f"Invalid contract code: {contract}")

    # Parse month code (e.g., 'Z' from 'SFRZ4')
    month_code = contract[-2]
    if month_code not in month_codes:
        raise ValueError(f"Invalid month code: {month_code}")

    month = month_codes[month_code]

    # Parse year (e.g., '4' from 'SFRZ4' = 2024)
    year_digit = contract[-1]
    if not year_digit.isdigit():
        raise ValueError(f"Invalid year digit: {year_digit}")

    # Assume 2020s for now (would need more context for actual year)
    year = 2020 + int(year_digit)

    # Return third Wednesday of that month (IMM date)
    first_day = date(year, month, 1)
    days_until_wed = (2 - first_day.weekday()) % 7
    first_wed = first_day + timedelta(days=days_until_wed)
    third_wed = first_wed + timedelta(weeks=2)

    return third_wed
