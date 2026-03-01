from typing import TYPE_CHECKING, List, Union

from Query.Base.BaseQuery import BaseQuery
from Query.USTFutures.USTFutureQuery import USTFutureQuery
from TB.BaseTimeseriesTB import BaseTimeseriesTB

if TYPE_CHECKING:
    from MDP.USTFutures.USTFuturesMDP import USTFuturesMDP


class USTFuturesTB(BaseTimeseriesTB):
    _DEFAULT_PRICING_MESSAGE = "PRICING UST FUTURES."

    def __init__(
        self,
        mdp: "USTFuturesMDP",
        *,
        date_col: str = "Date",
        show_tqdm: bool = True,
    ):
        super().__init__(mdp=mdp, date_col=date_col, show_tqdm=show_tqdm)

    def _flatten_queries(
        self,
        queries: List[Union[BaseQuery, List[BaseQuery]]],
    ) -> List[USTFutureQuery]:
        flat = super()._flatten_queries(queries)
        bad = [q for q in flat if not isinstance(q, USTFutureQuery)]
        if bad:
            raise TypeError(f"USTFuturesTB requires USTFutureQuery inputs, got: {type(bad[0]).__name__}")
        return flat
