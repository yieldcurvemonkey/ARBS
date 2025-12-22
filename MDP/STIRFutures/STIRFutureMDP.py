from __future__ import annotations

from typing import Any

from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from Query.Base._GenericPricable import _GenericPricable


class STIRFutureMDP(IRSwapsMDP):
    """Market data provider for STIR futures backed by IR swap curves."""

    def get_pricer(self, request: dict) -> _GenericPricable:  # type: ignore[override]
        return super().get_pricer(request)

    def get_data(self, request: dict) -> Any:  # type: ignore[override]
        return super().get_data(request)
