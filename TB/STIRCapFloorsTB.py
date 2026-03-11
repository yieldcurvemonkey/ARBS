from __future__ import annotations

from typing import List, Union

from Query.Base.BaseQuery import BaseQuery
from Query.STIRCapFloors.STIRCapFloorQuery import STIRCapFloorQuery
from TB.BaseTimeseriesTB import BaseTimeseriesTB


class STIRCapFloorsTB(BaseTimeseriesTB):
    _DEFAULT_PRICING_MESSAGE = "PRICING STIR CAP/FLOORS."

    def _flatten_queries(
        self,
        queries: List[Union[BaseQuery, List[BaseQuery]]],
    ) -> List[STIRCapFloorQuery]:
        flat = super()._flatten_queries(queries)
        bad = [q for q in flat if not isinstance(q, STIRCapFloorQuery)]
        if bad:
            raise TypeError(
                f"STIRCapFloorsTB requires STIRCapFloorQuery inputs, got: {type(bad[0]).__name__}"
            )
        return flat
