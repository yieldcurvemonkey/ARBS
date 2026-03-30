import datetime
import inspect
import json
from abc import ABC
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

import pandas as pd
from tqdm import tqdm as _tqdm

from MDP.MarketDataProvider import MarketDataProvider
from Query.Base.BaseQuery import BaseQuery
from Query.Base.query_resolution import resolve_for_request, resolve_query
from TB.utils import DateLike, _canonicalize_value, build_reference_points


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
        return build_reference_points(
            start=start,
            end=end,
            freq=freq,
            timestamps=timestamps,
        )

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
        _ = n_jobs, ignore_cache
        if not reference_points or not queries:
            return None

        bulk_fn = self._select_bulk_fetcher()
        if bulk_fn is None:
            return None

        prefetched_by_request_key: Dict[str, Any] = {}
        query_request_keys: Dict[Tuple[int, DateLike], str] = {}
        exact_requests: Dict[str, Dict[str, Any]] = {}
        bulk_groups: Dict[str, Dict[str, Any]] = {}
        single_request_keys: set[str] = set()

        for ref_point in reference_points:
            now = self._to_now(ref_point)
            for q in queries:
                seed_req = dict(q.build_mdp_request(now))
                request_key = self._request_cache_key(seed_req)
                query_request_keys[(id(q), ref_point)] = request_key
                if request_key in exact_requests:
                    continue

                exact_requests[request_key] = seed_req

                time_key = str(getattr(q, "mdp_time_key", "timestamp") or "timestamp")
                if time_key not in seed_req:
                    single_request_keys.add(request_key)
                    continue

                time_value = seed_req.get(time_key)
                if not self._is_bulkable_time_value(time_value):
                    single_request_keys.add(request_key)
                    continue

                bulk_time_key = self._bulk_time_collection_key(time_key)
                if bulk_time_key is None:
                    single_request_keys.add(request_key)
                    continue

                base_req = dict(seed_req)
                base_req.pop(time_key, None)
                group_key = self._request_cache_key({**base_req, "__bulk_time_key__": bulk_time_key})
                grp = bulk_groups.get(group_key)
                if grp is None:
                    grp = {
                        "bulk_request": {**base_req, bulk_time_key: []},
                        "time_values": [],
                        "exact_keys_by_time": defaultdict(list),
                    }
                    bulk_groups[group_key] = grp

                time_fp = self._request_cache_key({"__time__": time_value})
                if time_fp not in grp["exact_keys_by_time"]:
                    grp["time_values"].append(time_value)
                    grp["bulk_request"][bulk_time_key].append(time_value)
                grp["exact_keys_by_time"][time_fp].append(request_key)

        for grp in bulk_groups.values():
            bulk_request = dict(grp["bulk_request"])
            try:
                bulk_result = bulk_fn(bulk_request)
            except Exception:
                for request_keys in grp["exact_keys_by_time"].values():
                    single_request_keys.update(request_keys)
                continue

            if not isinstance(bulk_result, Mapping):
                for request_keys in grp["exact_keys_by_time"].values():
                    single_request_keys.update(request_keys)
                continue

            for time_value in grp["time_values"]:
                prefetched = self._lookup_bulk_result_value(bulk_result, time_value)
                if prefetched is None:
                    time_fp = self._request_cache_key({"__time__": time_value})
                    single_request_keys.update(grp["exact_keys_by_time"].get(time_fp, []))
                    continue

                time_fp = self._request_cache_key({"__time__": time_value})
                for request_key in grp["exact_keys_by_time"].get(time_fp, []):
                    prefetched_by_request_key[request_key] = prefetched

        for request_key in single_request_keys:
            if request_key in prefetched_by_request_key:
                continue
            seed_req = exact_requests.get(request_key)
            if seed_req is None:
                continue
            try:
                prefetched_by_request_key[request_key] = self.mdp.get_pricer(dict(seed_req))
            except Exception:
                continue

        if not prefetched_by_request_key:
            return None

        return {
            "prefetched_by_request_key": prefetched_by_request_key,
            "query_request_keys": query_request_keys,
        }

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
        pricer = None

        if isinstance(bulk_data, dict):
            prefetched = bulk_data.get("prefetched_by_request_key") or {}
            query_request_keys = bulk_data.get("query_request_keys") or {}
            request_key = query_request_keys.get((id(q), ref_point))
            if request_key is not None:
                pricer = prefetched.get(request_key)

        if pricer is None:
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

    @staticmethod
    def _request_cache_key(request: Mapping[str, Any]) -> str:
        return json.dumps(_canonicalize_value(dict(request)), sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _bulk_time_collection_key(time_key: str) -> Optional[str]:
        key = str(time_key or "").strip()
        if not key:
            return None
        if key.endswith("s"):
            return key
        return f"{key}s"

    @staticmethod
    def _is_bulkable_time_value(value: Any) -> bool:
        return isinstance(value, (datetime.date, datetime.datetime))

    def _select_bulk_fetcher(self):
        for attr in ("get_bulk_pricer", "get_bulk_data", "bulk_get_pricer", "bulk_get_data"):
            fn = getattr(self.mdp, attr, None)
            if callable(fn):
                return self._wrap_bulk_fetcher(fn)
        return None

    @staticmethod
    def _wrap_bulk_fetcher(fn):
        sig = inspect.signature(fn)
        params = [
            p
            for p in sig.parameters.values()
            if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        ]
        has_var_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())

        if len(params) == 1 and not has_var_kwargs:
            return lambda request: fn(request)
        return lambda request: fn(**request)

    @staticmethod
    def _lookup_bulk_result_value(bulk_result: Mapping[Any, Any], time_value: Any) -> Any:
        if time_value in bulk_result:
            return bulk_result[time_value]

        target = _canonicalize_value(time_value)
        if isinstance(time_value, datetime.date) and not isinstance(time_value, datetime.datetime):
            live_value = bulk_result.get("live")
            if live_value is not None and time_value == datetime.date.today():
                return live_value

        for key, value in bulk_result.items():
            if _canonicalize_value(key) == target:
                return value
        return None

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
        # groupby + last + unstack is faster than pivot_table for mostly-unique keys
        out = df.groupby([self._date_col, "_col"])["_val"].last().unstack("_col")
        out.index.name = self._date_col
        out.columns.name = None
        return out

    def _iter_reference_points(self, reference_points: List[DateLike], queries: List[BaseQuery]):
        return _tqdm(
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
