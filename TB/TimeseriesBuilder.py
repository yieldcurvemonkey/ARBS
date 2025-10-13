import datetime
from collections import defaultdict
from typing import TYPE_CHECKING, DefaultDict, Dict, Iterable, List, Optional, Tuple, Union

import re
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


def _ct_alias_to_y(tenor: str) -> str:
    """'CT2/CT10' -> '2Y/10Y', 'ct05xCT30' -> '05Yx30Y'"""
    _CT_RE = re.compile(r"(?i)\bct\s*(\d+)\b")
    return _CT_RE.sub(r"\1Y", str(tenor))


def _y_alias_to_ct(tenor: str) -> str:
    """'5Y' -> 'CT5', '2Y/10Y' -> 'CT2/CT10', '2Yx10Y' -> 'CT2xCT10'"""
    _Y_RE = re.compile(r"(?i)\b(\d+)\s*y\b")
    return _Y_RE.sub(r"CT\1", str(tenor))


def _safe_col_name(q, default: str) -> str:
    try:
        return q.col_name()
    except Exception:
        return default


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
            pair_specs = []

            _CT_RE = re.compile(r"(?i)\bct\s*(\d+)\b")
            _Y_RE = re.compile(r"(?i)\b(\d+)\s*y\b")

            for q in irswap_spread_queries:
                if q.value == IRSwapValue.MMSS:
                    q_frb = FixedRateBondQuery(cusip=q.tenor, value=FixedRateBondValue.YTM)
                    q_irs = IRSwapQuery(curve=q.curve, tenor=q.tenor, value=IRSwapValue.RATE)
                    op = "swap_minus_cash"  # spread = IRS - UST
                    mult = 100.0  # report in bps

                elif q.value == IRSwapValue.SPREADOVER:
                    t = str(q.tenor)
                    if _CT_RE.search(t):
                        q_frb = FixedRateBondQuery(cusip=t, value=FixedRateBondValue.YTM)
                        q_irs = IRSwapQuery(curve=q.curve, tenor=_ct_alias_to_y(t), value=IRSwapValue.RATE)
                    elif _Y_RE.search(t):
                        q_frb = FixedRateBondQuery(cusip=_y_alias_to_ct(t), value=FixedRateBondValue.YTM)
                        q_irs = IRSwapQuery(curve=q.curve, tenor=t, value=IRSwapValue.RATE)
                    else:
                        raise NotImplementedError(f"Unrecognized SPREADOVER tenor: {t!r}")
                    op = "swap_minus_cash"  # spreadover = IRS - UST
                    mult = 100.0

                else:
                    raise NotImplementedError(f"Unhandled spread type: {q.value}")

                irss_frb_qs.append(q_frb)
                irrs_irs_qs.append(q_irs)

                # Record robust pairing info using expected column names
                irs_col = _safe_col_name(
                    q_irs,
                    f"{getattr(q_irs,'curve','IRS')}.{getattr(q_irs,'tenor','')}.{IRSwapValue.RATE.name}",
                )
                frb_col = _safe_col_name(
                    q_frb,
                    f"{getattr(q_frb,'cusip','CUSIP')}.{FixedRateBondValue.YTM.name}",
                )
                spread_name = _safe_col_name(
                    q,
                    f"{getattr(q,'curve','IRS')}.{getattr(q,'tenor','')}.{getattr(q,'value',IRSwapValue.MMSS).name}",
                )

                pair_specs.append(
                    {
                        "spread_name": spread_name,
                        "irs_col": irs_col,
                        "frb_col": frb_col,
                        "op": op,  # 'swap_minus_cash' or 'cash_minus_swap'
                        "mult": mult,  # e.g., 100.0 for bps
                    }
                )

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
            idx = irs_df.index.union(cash_df.index)
            for spec in pair_specs:
                a = irs_df[spec["irs_col"]].reindex(idx) if spec["irs_col"] in irs_df.columns else pd.Series(index=idx, dtype="float64")
                b = cash_df[spec["frb_col"]].reindex(idx) if spec["frb_col"] in cash_df.columns else pd.Series(index=idx, dtype="float64")

                # future-proof for 'ASW' and 'CAS'
                if spec["op"] == "swap_minus_cash":
                    if "outright" in spread_name.lower():
                        spread = (a - b) * spec["mult"]
                    else:
                        spread = a - b
                else:
                    raise ValueError(f"Unknown op: {spec['op']}")

                spread_cols[spec["spread_name"]] = spread

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
