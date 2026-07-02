from __future__ import annotations
from typing import Any, Callable, Dict, Tuple

from MDP.MarketDataProvider import MarketDataProvider
from MDP.Spreads.SpreadPricer import SpreadPricer


class SpreadMDP(MarketDataProvider):
    """
    Composable MDP that wraps two child MDPs and returns a SpreadPricer.

    Args:
        mdp_a: First leg market data provider
        mdp_b: Second leg market data provider
        request_splitter: Callable that splits a single request dict into (req_a, req_b)
        source: Source identifier string
    """

    def __init__(
        self,
        mdp_a: MarketDataProvider,
        mdp_b: MarketDataProvider,
        request_splitter: Callable[[Dict[str, Any]], Tuple[Dict[str, Any], Dict[str, Any]]],
        source: str,
        **kwargs: Any,
    ):
        super().__init__(source=source, **kwargs)
        self.mdp_a = mdp_a
        self.mdp_b = mdp_b
        self.request_splitter = request_splitter

    def get_pricer(self, request: Any) -> SpreadPricer:
        req_a, req_b = self.request_splitter(request)
        pricer_a = self.mdp_a.get_pricer(req_a)
        pricer_b = self.mdp_b.get_pricer(req_b)
        return SpreadPricer(
            pricer_a=pricer_a,
            pricer_b=pricer_b,
            meta_data={
                "source": self.source,
                "request": request,
            },
        )

    def bulk_get_data(self, request: Any) -> Dict:
        """Iterate over timestamps and call get_pricer for each, compatible with IRSwapsTB."""
        timestamps = request.get("timestamps", [])
        base_req = {k: v for k, v in request.items() if k != "timestamps"}
        result: Dict[Any, SpreadPricer] = {}
        for ts in timestamps:
            result[ts] = self.get_pricer({**base_req, "timestamp": ts})
        return result
