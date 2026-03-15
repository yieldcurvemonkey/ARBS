from __future__ import annotations
from typing import Any, Dict, Optional, Tuple

from MDP.Spreads.SpreadMDP import SpreadMDP


def _default_request_splitter(request: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    ts = request.get("timestamp")
    req_a = {"curve_name": request["curve_a"], "timestamp": ts}
    req_b = {"curve_name": request["curve_b"], "timestamp": ts}
    for k, v in request.items():
        if k not in ("curve_a", "curve_b", "timestamp", "source_a", "source_b"):
            req_a[k] = v
            req_b[k] = v
    return req_a, req_b


class IRSwapSpreadsMDP(SpreadMDP):
    """
    Generic swap-vs-benchmark spread MDP.
    Wraps two IRSwapsMDP instances with potentially different curves or sources.
    Does NOT break existing IRSwapValue.MMSS (that remains single-curve).

    Request dict:
        curve_a: str       - first curve name
        curve_b: str       - second curve name
        timestamp: date/datetime
    """

    def __init__(
        self,
        source_a: str = "BARCHART_STIRF-RL",
        source_b: str = "BARCHART_STIRF-RL",
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
            mdp_a=_mdp_a,
            mdp_b=_mdp_b,
            request_splitter=_default_request_splitter,
            source="IRSWAP_SPREAD",
            **kwargs,
        )
