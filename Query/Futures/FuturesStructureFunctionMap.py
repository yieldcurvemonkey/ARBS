# ABOUTME: Futures structure function map for building priceable futures objects
# ABOUTME: Maps FuturesStructure enum to builders for OUTRIGHT/CALENDAR/PACK/BUNDLE with risk weights
"""
Futures Structure Function Map

Maps FuturesStructure enum values to builder functions that create
priceable STIR futures objects.

Pattern:
- OUTRIGHT → single contract
- CALENDAR → front and back contracts [+1, -1]
- PACK → 4 consecutive contracts [+0.25, +0.25, +0.25, +0.25]
- BUNDLE → 8 consecutive contracts [+0.125, ...]
- BASIS → futures + swap [+1, -1]
"""

from dataclasses import dataclass
from datetime import date
from functools import partial
from typing import Any, Callable, Dict, List, Optional, Tuple

from Query.Base.BaseStructure import BaseStructureFunctionMap
from Query.Futures.FuturesStructure import FuturesStructure
from Query.Futures.FuturesQuery import (
    parse_futures_contract,
    get_contract_expiry,
    get_contract_chain,
    get_pack_contracts,
    CONTRACT_SPECS,
)


# =============================================================================
# Futures Contract Representation
# =============================================================================

@dataclass
class MockFuture:
    """
    Futures contract with metadata for pricing and risk calculations.
    Contains contract specifications needed by value calculators.
    """
    contract: str
    expiry: date
    multiplier: float
    tick_size: float
    currency: str
    quantity: float
    product_type: str = "STIR"


# =============================================================================
# Futures Structure Function Map
# =============================================================================

class FuturesStructureFunctionMap(BaseStructureFunctionMap[FuturesStructure, MockFuture]):
    """
    Maps FuturesStructure to builder functions.

    Takes a curve/pricer and returns priceable futures objects
    with risk weights for each structure type.
    """

    def __init__(self, curve: Any):
        """
        Initialize with a curve that can build STIR futures.

        Args:
            curve: Pricing curve with build_stirf() method
        """
        super().__init__(
            FuturesStructure,
            curve=curve,
        )

    def _create_map(self) -> Dict[FuturesStructure, Callable[..., Tuple[List[MockFuture], List[float]]]]:
        """Create mapping from structure to builder function."""
        return {
            FuturesStructure.OUTRIGHT: partial(self._build_outright),
            FuturesStructure.CALENDAR: partial(self._build_calendar),
            FuturesStructure.PACK: partial(self._build_pack),
            FuturesStructure.BUNDLE: partial(self._build_bundle),
        }

    def _build_single_contract(
        self,
        contract: str,
        quantity: float = 1.0,
    ) -> MockFuture:
        """
        Build a single futures contract.

        Args:
            contract: Contract code (e.g., "SFRZ4")
            quantity: Number of contracts

        Returns:
            MockFuture object with contract specs
        """
        parsed = parse_futures_contract(contract)
        prefix = parsed['prefix']

        # Look up contract specs
        if prefix in CONTRACT_SPECS:
            specs = CONTRACT_SPECS[prefix]
            multiplier = specs['multiplier']
            tick_size = specs['tick_size']
            currency = specs['currency']
            product_type = specs['product_type']
        else:
            # Default to SFR specs
            multiplier = 2500.0
            tick_size = 0.0025
            currency = "USD"
            product_type = "STIR"

        expiry = get_contract_expiry(contract)

        return MockFuture(
            contract=contract,
            expiry=expiry,
            multiplier=multiplier,
            tick_size=tick_size,
            currency=currency,
            quantity=quantity,
            product_type=product_type,
        )

    def _build_outright(
        self,
        *,
        contract: str,
        quantity: float = 1.0,
        **_,
    ) -> Tuple[List[MockFuture], List[float]]:
        """
        Build OUTRIGHT structure (single contract).

        Args:
            contract: Contract code (e.g., "SFRZ4")
            quantity: Number of contracts

        Returns:
            ([MockFuture], [+1.0 or -1.0])
        """
        fut = self._build_single_contract(contract, abs(quantity))

        # Risk weight: +1 for long, -1 for short
        risk_weight = 1.0 if quantity >= 0 else -1.0

        return ([fut], [risk_weight])

    def _build_calendar(
        self,
        *,
        front_contract: str,
        back_contract: str,
        quantity: float = 1.0,
        risk_weights: Optional[List[float]] = None,
        **_,
    ) -> Tuple[List[MockFuture], List[float]]:
        """
        Build CALENDAR structure (front - back spread).

        Args:
            front_contract: Near contract (e.g., "SFRZ4")
            back_contract: Far contract (e.g., "SFRH5")
            quantity: Number of spreads
            risk_weights: Custom risk weights (default [+1, -1])

        Returns:
            ([front_future, back_future], [+1, -1])
        """
        if risk_weights is None:
            risk_weights = [1.0, -1.0]

        assert len(risk_weights) == 2, "CALENDAR requires 2 risk weights"

        front_fut = self._build_single_contract(front_contract, abs(quantity))
        back_fut = self._build_single_contract(back_contract, abs(quantity))

        # Apply sign from quantity to risk weights
        sign = 1.0 if quantity >= 0 else -1.0
        adjusted_rw = [sign * rw for rw in risk_weights]

        return ([front_fut, back_fut], adjusted_rw)

    def _build_pack(
        self,
        *,
        contract: str,
        pack_color: str = "WHITE",
        quantity: float = 1.0,
        **_,
    ) -> Tuple[List[MockFuture], List[float]]:
        """
        Build PACK structure (4 consecutive contracts).

        Args:
            contract: Base contract (e.g., "SFRZ4")
            pack_color: Pack color (WHITE, RED, GREEN, BLUE, GOLD)
            quantity: Number of packs

        Returns:
            ([4 futures], [+0.25, +0.25, +0.25, +0.25])
        """
        # Get 4 contracts for the pack
        pack_contracts = get_pack_contracts(contract, pack_color)
        assert len(pack_contracts) == 4, f"Pack must have 4 contracts, got {len(pack_contracts)}"

        # Build each contract with equal weighting
        futures = []
        for contract_code in pack_contracts:
            fut = self._build_single_contract(contract_code, abs(quantity) / 4.0)
            futures.append(fut)

        # Equal risk weights for pack (each leg is 25% of pack)
        risk_weights = [0.25, 0.25, 0.25, 0.25]

        # Apply sign from quantity
        sign = 1.0 if quantity >= 0 else -1.0
        adjusted_rw = [sign * rw for rw in risk_weights]

        return (futures, adjusted_rw)

    def _build_bundle(
        self,
        *,
        bundle_start_contract: str,
        quantity: float = 1.0,
        **_,
    ) -> Tuple[List[MockFuture], List[float]]:
        """
        Build BUNDLE structure (8 consecutive contracts).

        Args:
            bundle_start_contract: First contract in bundle (e.g., "SFRZ4")
            quantity: Number of bundles

        Returns:
            ([8 futures], [+0.125, +0.125, ...])
        """
        # Get 8 consecutive contracts
        bundle_contracts = get_contract_chain(bundle_start_contract, 8)
        assert len(bundle_contracts) == 8, f"Bundle must have 8 contracts, got {len(bundle_contracts)}"

        # Build each contract with equal weighting
        futures = []
        for contract_code in bundle_contracts:
            fut = self._build_single_contract(contract_code, abs(quantity) / 8.0)
            futures.append(fut)

        # Equal risk weights for bundle (each leg is 12.5% of bundle)
        risk_weights = [0.125] * 8

        # Apply sign from quantity
        sign = 1.0 if quantity >= 0 else -1.0
        adjusted_rw = [sign * rw for rw in risk_weights]

        return (futures, adjusted_rw)
