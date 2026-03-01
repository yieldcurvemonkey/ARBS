from typing import TYPE_CHECKING, List, Union

from Query.Base.BaseQuery import BaseQuery
from Query.STIRFutureOptions.STIRFutureOptionQuery import STIRFutureOptionQuery
from TB.BaseTimeseriesTB import BaseTimeseriesTB

if TYPE_CHECKING:
    from MDP.STIRFutures.STIRFutureOptionMDP import STIRFutureOptionMDP


class STIRFutureOptionsTB(BaseTimeseriesTB):
    _DEFAULT_PRICING_MESSAGE = "PRICING STIR FUTURE OPTIONS."

    def __init__(
        self,
        mdp: "STIRFutureOptionMDP",
        *,
        date_col: str = "Date",
        show_tqdm: bool = True,
    ):
        super().__init__(mdp=mdp, date_col=date_col, show_tqdm=show_tqdm)

    def _flatten_queries(
        self,
        queries: List[Union[BaseQuery, List[BaseQuery]]],
    ) -> List[STIRFutureOptionQuery]:
        flat = super()._flatten_queries(queries)
        bad = [q for q in flat if not isinstance(q, STIRFutureOptionQuery)]
        if bad:
            raise TypeError(
                f"STIRFutureOptionsTB requires STIRFutureOptionQuery inputs, got: {type(bad[0]).__name__}"
            )
        return flat
