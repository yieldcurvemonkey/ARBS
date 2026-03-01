import datetime
from abc import ABC
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

import pandas as pd
import tqdm

from MDP.MarketDataProvider import MarketDataProvider
from Query.Base.BaseQuery import BaseQuery
from Query.Base.query_resolution import resolve_for_request, resolve_query
from TB.utils import DateLike


class BaseTimeseriesTB(ABC):
    _DEFAULT_PRICING_MESSAGE = "PRICING TIMESERIES."

    def __init__(
        self,
        mdp: MarketDataProvider,
        *,
        date_col: str = "Date",
        show_tqdm: bool = True,
    ):
        self.mdp = mdp
        self._date_col = date_col
        self._show_tqdm = show_tqdm

    def _expand_query_like(self, q: Any) -> List[Any]:
        if hasattr(q, "return_query"):
            out = q.return_query()
            if isinstance(out, list):
                return list(out)
            return [out]
        return [q]

    def _flatten_queries(
        self,
        queries: Sequence[Union[BaseQuery, List[BaseQuery]]],
    ) -> List[BaseQuery]:
        flat: List[BaseQuery] = []
        for q in queries:
            if isinstance(q, list):
                for qq in q:
                    for expanded in self._expand_query_like(qq):
                        flat.append(expanded)
            else:
                for expanded in self._expand_query_like(q):
                    flat.append(expanded)
        return flat

    def _build_reference_points(
        self,
        start: DateLike,
        end: DateLike,
        *,
        freq: Optional[str],
        timestamps: Optional[List[datetime.datetime]],
    ) -> List[DateLike]:
        if timestamps is not None and len(timestamps) > 0:
            return sorted(pd.to_datetime(pd.Index(timestamps)).to_pydatetime().tolist())

        is_intraday = isinstance(start, datetime.datetime) and isinstance(end, datetime.datetime) and (freq is not None)
        if is_intraday:
            if start.tzinfo is not None:
                rng = pd.date_range(start=start, end=end, freq=freq, tz=start.tzinfo)
            else:
                rng = pd.date_range(start=start, end=end, freq=freq)
            return rng.to_pydatetime().tolist()

        return pd.bdate_range(start, end).date.tolist()

    def _to_now(self, ref_point: DateLike) -> datetime.datetime:
        if isinstance(ref_point, datetime.datetime):
            return ref_point
        return datetime.datetime.combine(ref_point, datetime.time())

    def _index_value(self, ref_point: DateLike) -> DateLike:
        if isinstance(ref_point, datetime.datetime):
            return ref_point.date()
        return ref_point

    def _bulk_fetch(
        self,
        *,
        reference_points: List[DateLike],
        queries: List[BaseQuery],
        n_jobs: Optional[int],
        ignore_cache: Optional[bool],
    ) -> Any:
        return None

    def _price_one(
        self,
        q: BaseQuery,
        *,
        ref_point: DateLike,
        now: datetime.datetime,
        bulk_data: Any,
        n_jobs: Optional[int],
        ignore_cache: Optional[bool],
    ) -> Optional[Tuple[BaseQuery, float]]:
        _ = ref_point, bulk_data, n_jobs, ignore_cache

        seed_req = q.build_mdp_request(now)
        pricer = self.mdp.get_pricer(dict(seed_req))

        q_resolved = resolve_for_request(q, timestamp=now, pricer_or_curve=pricer)
        resolved_req = q_resolved.build_mdp_request(now)
        if resolved_req != seed_req:
            pricer = self.mdp.get_pricer(dict(resolved_req))

        q_eff = resolve_query(q_resolved, timestamp=now, pricer_or_curve=pricer)
        package, risk_weights = q_eff.resolve_package(
            pricer_or_curve=pricer,
            is_for_timeseries=True,
        )
        vmap = q_eff.build_value_map(
            pricer_or_curve=pricer,
            package=package,
            risk_weights=risk_weights,
        )

        value_key = getattr(q_eff, "value", None) or q_eff.default_mtm_value_id()
        value_kwargs = getattr(q_eff, "value_kwargs", {}) or {}
        value = vmap.apply(value=value_key, **value_kwargs)
        return q_eff, float(value)

    def _column_name(
        self,
        q: BaseQuery,
        *,
        effective_query: Optional[BaseQuery] = None,
    ) -> str:
        q_eff = effective_query or q
        if getattr(q_eff, "name", None):
            return str(q_eff.name)
        try:
            return str(q_eff.col_name())
        except Exception:
            try:
                return str(q.col_name())
            except Exception:
                return f"{getattr(q_eff, 'product', 'QUERY')}_{id(q_eff)}"

    def _pricing_message(self, queries: List[BaseQuery]) -> str:
        _ = queries
        return self._DEFAULT_PRICING_MESSAGE

    def _rows_to_frame(self, rows: List[Tuple[DateLike, str, float]]) -> pd.DataFrame:
        if not rows:
            return pd.DataFrame().set_index(pd.Index([], name=self._date_col))

        df = pd.DataFrame(rows, columns=[self._date_col, "_col", "_val"])
        out = df.pivot_table(index=self._date_col, columns="_col", values="_val", aggfunc="last").sort_index()
        out.index.name = self._date_col
        out.columns.name = None
        return out

    def _iter_reference_points(self, reference_points: List[DateLike], queries: List[BaseQuery]):
        return tqdm.tqdm(
            reference_points,
            desc=self._pricing_message(queries),
            disable=not self._show_tqdm,
        )

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
        assert start <= end, "must have end >= start"
        flat = self._flatten_queries(queries)
        if not flat:
            return pd.DataFrame().set_index(pd.Index([], name=self._date_col))

        reference_points = self._build_reference_points(
            start=start,
            end=end,
            freq=freq,
            timestamps=timestamps,
        )

        bulk_data = self._bulk_fetch(
            reference_points=reference_points,
            queries=flat,
            n_jobs=n_jobs,
            ignore_cache=ignore_cache,
        )

        rows: List[Tuple[DateLike, str, float]] = []
        for ref_point in self._iter_reference_points(reference_points, flat):
            now = self._to_now(ref_point)
            idx = self._index_value(ref_point)
            for q in flat:
                try:
                    priced = self._price_one(
                        q,
                        ref_point=ref_point,
                        now=now,
                        bulk_data=bulk_data,
                        n_jobs=n_jobs,
                        ignore_cache=ignore_cache,
                    )
                    if priced is None:
                        continue
                    q_eff, value = priced
                    rows.append((idx, self._column_name(q, effective_query=q_eff), float(value)))
                except Exception:
                    continue

        return self._rows_to_frame(rows)
