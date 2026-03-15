from __future__ import annotations
from typing import Any, Dict, Tuple

from MDP.Spreads.SpreadMDP import SpreadMDP


def _basis_request_splitter(request: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    ts = request.get("timestamp")
    curve_a = request.get("curve_a", "USD-SOFR-1D-Q12STIRT")
    curve_b = request.get("curve_b", "USD-FEDFUNDS")
    req_a = {"curve_name": curve_a, "timestamp": ts}
    req_b = {"curve_name": curve_b, "timestamp": ts}
    return req_a, req_b


class IRBasisSwapsMDP(SpreadMDP):
    """
    SOFR vs OIS/Fed Funds basis spread MDP.
    Default: BARCHART_STIRF-RL source, USD-SOFR-1D-Q12STIRT vs USD-FEDFUNDS curves.

    Request dict:
        timestamp: date/datetime
        curve_a: str (optional, default "USD-SOFR-1D-Q12STIRT")
        curve_b: str (optional, default "USD-FEDFUNDS")
    """

    def __init__(
        self,
        source: str = "BARCHART_STIRF-RL",
        *,
        _mdp_a: Any = None,
        _mdp_b: Any = None,
        **kwargs: Any,
    ):
        if _mdp_a is None:
            from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
            _mdp_a = IRSwapsMDP(source=source)
        if _mdp_b is None:
            from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
            _mdp_b = IRSwapsMDP(source=source)

        super().__init__(
            mdp_a=_mdp_a,
            mdp_b=_mdp_b,
            request_splitter=_basis_request_splitter,
            source=f"IRBASIS_{source}",
            **kwargs,
        )
