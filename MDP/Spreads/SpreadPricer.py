from __future__ import annotations
from typing import Any, Dict


class SpreadPricer:
    """
    Holds two pricers (leg A, leg B) for spread computations.

    The SpreadPricer itself does not compute spreads — it is a container
    that the SpreadValueFunctionMap uses to access both underlying pricers.
    """

    def __init__(self, pricer_a: Any, pricer_b: Any, meta_data: Dict[str, Any]):
        self.pricer_a = pricer_a
        self.pricer_b = pricer_b
        self._meta_data = meta_data

    @property
    def meta_data(self) -> Dict[str, Any]:
        return self._meta_data

    def id(self) -> str:
        """Return curve identifier; required by IRSwapsTB._build_row_for_query."""
        req = self._meta_data.get("request", {})
        return (
            self._meta_data.get("curve_name")
            or req.get("curve_name")
            or getattr(self.pricer_a, "id", lambda: "spread")()
        )
