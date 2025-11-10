"""
Futures Value Function Map

Calculates value metrics for futures positions.

Tier 1 (Essential):
- PRICE: Futures price (e.g., 94.50)
- IMPLIED_RATE: 100 - Price (e.g., 5.50%)
- NPV: Mark-to-market in dollars
- DV01: Dollar value of 1bp move ($25 per contract for SFR)
"""

from typing import Any, Callable, Dict, List

from Query.Base.BaseValue import BaseValueFunctionMap
from Query.Futures.FuturesValue import FuturesValue
from Query.Futures.FuturesStructureFunctionMap import MockFuture


class FuturesValueFunctionMap(BaseValueFunctionMap[FuturesValue, float]):
    """
    Maps FuturesValue enum to calculation functions.

    Takes a curve/pricer, package of futures objects, and risk weights,
    and calculates requested metrics.
    """

    def __init__(
        self,
        curve: Any,
        package: List[MockFuture],
        risk_weights: List[float],
    ):
        """
        Initialize value map.

        Args:
            curve: Pricing curve/pricer with futures_price() method
            package: List of futures objects
            risk_weights: Risk weight for each future
        """
        super().__init__(
            FuturesValue,
            curve=curve,
            package=package,
            risk_weights=risk_weights,
        )

    def _create_map(self) -> Dict[FuturesValue, Callable[..., float]]:
        """Create mapping from value type to calculation function."""
        return {
            FuturesValue.PRICE: self._price,
            FuturesValue.IMPLIED_RATE: self._implied_rate,
            FuturesValue.NPV: self._npv,
            FuturesValue.DV01: self._dv01,
            # FuturesValue.CARRY: self._carry,  # TODO: Phase 3.4
            # FuturesValue.MARGIN: self._margin,  # TODO: Phase 3.4
        }

    def _get_contract_price(self, fut: MockFuture, curve: Any) -> float:
        """
        Get price for a single futures contract.

        Args:
            fut: Futures object
            curve: Pricer with futures_price() method

        Returns:
            Price (e.g., 94.50)
        """
        # Try to get price from pricer
        if hasattr(curve, 'futures_price'):
            return curve.futures_price(fut.contract)
        # Fallback: derive from curve rate
        elif hasattr(curve, 'rate'):
            # Implied rate = curve rate, price = 100 - rate
            rate_pct = curve.rate("3M") * 100  # Convert to %
            return 100.0 - rate_pct
        else:
            # Last fallback: 95.0 default
            return 95.0

    def _price(self, **kwargs) -> float:
        """
        Calculate PRICE.

        For single contract: returns price
        For calendar spread: returns front - back (weighted sum)
        For pack: returns average of 4 prices (optionally rounded)

        Returns:
            Price in points (e.g., 94.50)
        """
        curve = kwargs["curve"]
        package = kwargs["package"]
        risk_weights = kwargs["risk_weights"]

        # Single contract
        if len(package) == 1:
            return self._get_contract_price(package[0], curve)

        # Pack (4 contracts with equal weights)
        if len(package) == 4 and all(abs(rw - 0.25) < 0.001 for rw in risk_weights):
            prices = [self._get_contract_price(fut, curve) for fut in package]
            avg_price = sum(prices) / 4.0

            # Round to tick if requested
            if kwargs.get("round_pack_to_tick", True):
                tick = kwargs.get("pack_tick", 0.0025)
                from decimal import Decimal, ROUND_HALF_UP
                q = Decimal(str(tick))
                avg_price = float(
                    (Decimal(str(avg_price)) / q).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * q
                )

            return avg_price

        # General weighted sum (calendar spreads, butterflies, etc.)
        weighted_sum = 0.0
        for fut, rw in zip(package, risk_weights):
            price = self._get_contract_price(fut, curve)
            weighted_sum += rw * price

        return weighted_sum

    def _implied_rate(self, **kwargs) -> float:
        """
        Calculate IMPLIED_RATE.

        Formula: 100 - Price

        Returns:
            Implied rate in percent (e.g., 5.50 for 5.50%)
        """
        price = self._price(**kwargs)
        return 100.0 - price

    def _npv(self, **kwargs) -> float:
        """
        Calculate NPV (mark-to-market).

        For futures: P&L from price change × multiplier × quantity
        Assumes entry price is stored or provided in kwargs.

        Returns:
            NPV in dollars
        """
        curve = kwargs["curve"]
        package = kwargs["package"]
        entry_price = kwargs.get("entry_price", None)

        # If no entry price, use curve NPV method if available
        if entry_price is None:
            if hasattr(curve, 'npv'):
                return sum(curve.npv(fut) for fut in package)
            else:
                # Fallback: return 0 (no P&L from entry)
                return 0.0

        # Calculate P&L from entry
        current_price = self._price(**kwargs)
        price_change = current_price - entry_price

        # For single contract: simple calculation
        if len(package) == 1:
            fut = package[0]
            return price_change * fut.multiplier * fut.quantity

        # For spreads: weighted sum
        total_pnl = 0.0
        for fut in package:
            # Each contract contributes based on its quantity
            contract_pnl = price_change * fut.multiplier * fut.quantity
            total_pnl += contract_pnl

        return total_pnl

    def _dv01(self, **kwargs) -> float:
        """
        Calculate DV01 (dollar value of 1bp move).

        Formula: multiplier × quantity × 0.01 per contract
        For SFR: $2500 × qty × 0.01 = $25 per contract

        For spreads: net DV01 (long legs positive, short legs negative)
        For packs: gross DV01 (sum of all legs, all positive)

        Returns:
            DV01 in dollars per basis point
        """
        package = kwargs["package"]
        risk_weights = kwargs["risk_weights"]

        total_dv01 = 0.0

        for fut, rw in zip(package, risk_weights):
            # DV01 per contract = multiplier / 100
            # (1bp = 0.01 price change, price change × multiplier = $ change)
            contract_dv01 = fut.multiplier / 100.0  # $25 for SFR ($2500/100)

            # Scale by quantity and risk weight sign
            # Risk weight gives direction: +1 for long, -1 for short, 0.25 for pack leg
            # For packs: rw=0.25, qty=0.25, so 0.25 * 25 * 0.25 = 1.5625... wait that's wrong
            #
            # Actually: risk weights represent the ALLOCATION in pricing
            # But for DV01, we want position size
            #
            # If qty already reflects allocation (0.25 for pack), then:
            # DV01 = sum of (contract_dv01 * qty) for all legs, ignoring risk_weight
            #
            # But for calendar spread with qty=1.0 on both legs and rw=[+1,-1]:
            # We need net DV01 = +25 - 25 = 0
            #
            # So: use sign(rw) * contract_dv01 * qty

            # Get sign from risk weight (-1, 0, +1)
            sign = 1.0 if rw >= 0 else -1.0

            total_dv01 += sign * contract_dv01 * fut.quantity

        return total_dv01
