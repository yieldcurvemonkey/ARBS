import datetime
from collections import defaultdict
from typing import TYPE_CHECKING, DefaultDict, Dict, Iterable, List, Optional, Tuple, Union

import pandas as pd

from Query.Base.BaseQuery import BaseQuery
from Query.FixedRateBonds.FixedRateBondQuery import FixedRateBondQuery
from Query.FixedRateBonds.FixedRateBondValue import FixedRateBondValue
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapValue import IRSwapValue

from TB.utils import DateLike

# Avoid hard import cycles for optional type checking
if TYPE_CHECKING:
    from TB.FixedRateBondsTB import FixedRateBondsTB
    from TB.IRSwapsTB import IRSwapsTB


def _flatten_base_queries(queries: Iterable[Union[BaseQuery, List[BaseQuery]]]) -> List[BaseQuery]:
    flat: List[BaseQuery] = []
    for q in queries:
        if isinstance(q, list):
            for qq in q:
                flat.extend(qq.return_query())
        else:
            flat.extend(q.return_query())
    return flat


class TimeseriesBuilder:
    def __init__(
        self,
        *,
        irswaps_tb: "IRSwapsTB",
        fixedratebonds_tb: "FixedRateBondsTB",
        date_col: str = "Date",
    ):
        self._date_col = date_col
        self._routers: Dict[str, object] = {
            "IRS": irswaps_tb,
            "FRB": fixedratebonds_tb,
        }

    def register_router(self, product: str, tb_obj: object) -> None:
        self._routers[product] = tb_obj

    def get_timeseries(
        self,
        start: DateLike,
        end: DateLike,
        queries: List[Union[BaseQuery, List[BaseQuery]]],
        *,
        n_jobs: Optional[int] = 1,
        ignore_cache: Optional[bool] = False,
        freq: Optional[str] = None,
        timestamps: Optional[List[datetime.datetime]] = None,
    ) -> pd.DataFrame:
        flat = _flatten_base_queries(queries)

        by_product: DefaultDict[str, List[BaseQuery]] = defaultdict(list)
        for q in flat:
            if not getattr(q, "product", None):
                raise ValueError(f"Query missing 'product': {q!r}")
            by_product[q.product].append(q)

        per_product_frames: List[Tuple[str, pd.DataFrame]] = []
        irswap_spread_queries: List[IRSwapQuery] = []

        for product, qs in by_product.items():
            tb = self._routers.get(product)
            if tb is None:
                raise KeyError(f"No timeseries router registered for product '{product}'")

            if product == "IRS":
                irs_qs_unfiltered: List[IRSwapQuery] = [q for q in qs if isinstance(q, IRSwapQuery)]

                irs_qs = []
                for q in irs_qs_unfiltered:
                    if q.value in [IRSwapValue.MMSS, IRSwapValue.SPREADOVER]:
                        irswap_spread_queries.append(q)
                    elif q.value in [IRSwapValue.ASW]:
                        raise NotImplementedError()
                    else:
                        irs_qs.append(q)

                # if len(irs_qs) != len(qs):
                #     raise TypeError("Mixed/non-IRS queries encountered in IRS bucket")
                df = tb.get_timeseries(  # type: ignore[attr-defined]
                    start,
                    end,
                    irs_qs,
                    n_jobs=n_jobs,
                    ignore_cache=ignore_cache,
                    freq=freq,
                    timestamps=timestamps,
                )
            elif product == "FRB":
                frb_qs: List[FixedRateBondQuery] = [q for q in qs if isinstance(q, FixedRateBondQuery)]
                if len(frb_qs) != len(qs):
                    raise TypeError("Mixed/non-FRB queries encountered in FixedRateBond bucket")
                df = tb.get_timeseries(  # type: ignore[attr-defined]
                    start,
                    end,
                    frb_qs,
                    n_jobs=n_jobs,
                    ignore_cache=ignore_cache,
                    freq=freq,
                    timestamps=timestamps,
                )
            else:
                raise NotImplementedError()
                # # Future products can be registered via register_router and handled here
                # df = tb.get_timeseries(  # type: ignore[attr-defined]
                #     start,
                #     end,
                #     qs,
                #     n_jobs=n_jobs,
                #     ignore_cache=ignore_cache,
                #     freq=freq,
                #     timestamps=timestamps,
                # )

            if df is None or df.empty:
                continue
            if self._date_col in df.columns:
                df = df.set_index(self._date_col)

            df = pd.concat({product: df}, axis=1)
            per_product_frames.append((product, df))

        if irswap_spread_queries:
            irss_frb_qs = []
            irrs_irs_qs = []
            for q in irswap_spread_queries:
                if q.value == IRSwapValue.MMSS:
                    irss_frb_qs.append(FixedRateBondQuery(cusip=q.tenor, value=FixedRateBondValue.YTM))
                    irrs_irs_qs.append(IRSwapQuery(curve=q.curve, tenor=q.tenor, value=IRSwapValue.RATE))
                elif q.value == IRSwapValue.SPREADOVER:
                    if "ct" in str(q.tenor).lower():
                        irss_frb_qs.append(FixedRateBondQuery(cusip=q.tenor, value=FixedRateBondValue.YTM))
                        irrs_irs_qs.append(IRSwapQuery(curve=q.curve, tenor=f"{str(q.tenor)[2:]}Y", value=IRSwapValue.RATE))
                    elif "y" in str(q.tenor).lower():
                        irss_frb_qs.append(FixedRateBondQuery(cusip=f"CT{str(q.tenor)[:-1]}", value=FixedRateBondValue.YTM))
                        irrs_irs_qs.append(IRSwapQuery(curve=q.curve, tenor=q.tenor, value=IRSwapValue.RATE))
                    else:
                        raise NotImplementedError()
                else:
                    raise NotImplementedError()

            irs_df = self._routers["IRS"].get_timeseries(  # type: ignore[attr-defined]
                start,
                end,
                irrs_irs_qs,
                n_jobs=n_jobs,
                ignore_cache=ignore_cache,
                freq=freq,
                timestamps=timestamps,
            )
            cash_df = self._routers["FRB"].get_timeseries(  # type: ignore[attr-defined]
                start,
                end,
                irss_frb_qs,
                n_jobs=n_jobs,
                ignore_cache=ignore_cache,
                freq=freq,
                timestamps=timestamps,
            )

            spread_cols: Dict[str, pd.Series] = {}
            for q_spread, q_frb, q_irs in zip(irswap_spread_queries, irss_frb_qs, irrs_irs_qs):
                try:
                    irs_col = q_irs.col_name()
                except Exception:
                    irs_col = f"{getattr(q_irs, 'curve', 'IRS')}.{getattr(q_irs, 'tenor', '')}.{IRSwapValue.RATE.name}"

                try:
                    frb_col = q_frb.col_name()
                except Exception:
                    frb_col = f"{getattr(q_frb, 'cusip', 'CUSIP')}.{FixedRateBondValue.YTM.name}"

                try:
                    spread_name = q_spread.col_name()
                except Exception:
                    vname = q_spread.value.name if getattr(q_spread, "value", None) else "SPREAD"
                    spread_name = f"{getattr(q_spread, 'curve', 'IRS')}.{getattr(q_spread, 'tenor', '')}.{vname}"

                idx = irs_df.index.union(cash_df.index)
                a = irs_df[irs_col].reindex(idx) if irs_col in irs_df.columns else pd.Series(index=idx, dtype="float64")
                b = cash_df[frb_col].reindex(idx) if frb_col in cash_df.columns else pd.Series(index=idx, dtype="float64")
                spread_cols[spread_name] = (a - b) * 100.0

            if spread_cols:
                spread_df = pd.DataFrame(spread_cols).sort_index()
                spread_df.index.name = self._date_col
                per_product_frames.append(("SWAPSPREADS", pd.concat({"SWAPSPREADS": spread_df}, axis=1)))

        if not per_product_frames:
            return pd.DataFrame().set_index(pd.Index([], name=self._date_col))

        out = per_product_frames[0][1]
        for _, df in per_product_frames[1:]:
            out = out.join(df, how="outer")

        out = out.sort_index()
        out.index.name = self._date_col
        return out
