from typing import TYPE_CHECKING, List, Union

from Query.Base.BaseQuery import BaseQuery
from Query.STIRFutures.STIRFutureQuery import STIRFutureQuery
from TB.BaseTimeseriesTB import BaseTimeseriesTB

if TYPE_CHECKING:
    from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP


class STIRFuturesTB(BaseTimeseriesTB):
    _DEFAULT_PRICING_MESSAGE = "PRICING STIR FUTURES."

    def __init__(
        self,
        mdp: "STIRFutureMDP",
        *,
        date_col: str = "Date",
        show_tqdm: bool = True,
    ):
        super().__init__(mdp=mdp, date_col=date_col, show_tqdm=show_tqdm)

    def _flatten_queries(
        self,
        queries: List[Union[BaseQuery, List[BaseQuery]]],
    ) -> List[STIRFutureQuery]:
        flat = super()._flatten_queries(queries)
        bad = [q for q in flat if not isinstance(q, STIRFutureQuery)]
        if bad:
            raise TypeError(f"STIRFuturesTB requires STIRFutureQuery inputs, got: {type(bad[0]).__name__}")
        return flat
