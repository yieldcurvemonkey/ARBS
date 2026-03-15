from __future__ import annotations
from typing import Any, Dict, Tuple
from MDP.Spreads.SpreadMDP import SpreadMDP


def _cvx_request_splitter(request: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    ts = request.get("timestamp")
    curve_name = request.get("curve_name", "USD-SOFR-1D")
    curve_name_a = request.get("curve_name_a", f"{curve_name}-Q12STIRT")
    curve_name_b = request.get("curve_name_b", curve_name)
    req_a = {"curve_name": curve_name_a, "timestamp": ts}
    req_b = {"curve_name": curve_name_b, "timestamp": ts}
    return req_a, req_b


class STIRConvexityAdjustmentMDP(SpreadMDP):
    """
    STIR Convexity Adjustment MDP.

    Empirical mode: difference between BARCHART_STIRF-RL (no cvx) and ERIS_EOD_LIVE-RL_BASIC-NOJUMPS (with cvx).
    Analytical mode: use hw1f_model.hw1f_convexity_adjustment() directly.

    Request dict:
        curve_name: str (default "USD-SOFR-1D")
        curve_name_a: str (optional override for no-cvx leg)
        curve_name_b: str (optional override for with-cvx leg)
        timestamp: datetime
    """

    def __init__(
        self,
        source_a: str = "BARCHART_STIRF-RL",
        source_b: str = "ERIS_EOD_LIVE-RL_BASIC-NOJUMPS",
        *,
        _mdp_a: Any = None,
        _mdp_b: Any = None,
        **kwargs: Any,
    ):
        if _mdp_a is None:
            from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
            _mdp_a = IRSwapsMDP(source=source_a)
        if _mdp_b is None:
            from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
            _mdp_b = IRSwapsMDP(source=source_b)

        super().__init__(
            mdp_a=_mdp_a, mdp_b=_mdp_b,
            request_splitter=_cvx_request_splitter,
            source="STIRCVX_EMPIRICAL",
            **kwargs,
        )
