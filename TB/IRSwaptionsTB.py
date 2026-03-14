from __future__ import annotations

import datetime
import hashlib
import json
import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import DefaultDict, Dict, Iterable, List, Optional, Tuple, Union

import pandas as pd
from tqdm.auto import tqdm as _tqdm

from Caching.LayeredCacheMixin import LayeredCacheMixin
from MDP.IRSwaptions.IRSwaptionMDP import IRSwaptionMDP, IRSwaptionMarketContext
from Query.Base.query_resolution import resolve_query
import Query.IRSwaptions.adapter  # noqa: F401
from Query.IRSwaptions.IRSwaptionQuery import IRSwaptionQuery, IRSwaptionQueryWrapper
from TB.BaseTimeseriesTB import BaseTimeseriesTB
from TB.utils import DateLike, _canonicalize_value, _dt_to_epoch_ns

_LOGGER_NAME = "IRSwaptionsTB"


def _query_fingerprint(q: IRSwaptionQuery) -> str:
    payload = {
        "curve": q.curve,
        "structure": q.structure.name if getattr(q, "structure", None) else None,
        "value": _canonicalize_value(q.value.name if hasattr(q.value, "name") else q.value),
        "structure_kwargs": _canonicalize_value(q.structure_kwargs or {}),
        "value_kwargs": _canonicalize_value(q.value_kwargs or {}),
        "trade_date": _canonicalize_value(q.trade_date),
        "name": q.name,
        "risk_weight": q.risk_weight,
    }
    s = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def _flatten_queries_with_wrappers(
    queries: List[IRSwaptionQuery | List[IRSwaptionQuery] | IRSwaptionQueryWrapper],
) -> tuple[list[IRSwaptionQuery], list[IRSwaptionQueryWrapper]]:
    flat: list[IRSwaptionQuery] = []
    wrappers: list[IRSwaptionQueryWrapper] = []

    def _expand_one(item):
        if isinstance(item, IRSwaptionQueryWrapper):
            wrappers.append(item)
            flat.extend(item.return_query())
            return
        if isinstance(item, list):
            for sub in item:
                _expand_one(sub)
            return
        if hasattr(item, "return_query"):
            expanded = item.return_query()
            if isinstance(expanded, list):
                flat.extend(expanded)
            else:
                flat.append(expanded)
            return
        flat.append(item)

    for q in queries:
        _expand_one(q)

    return flat, wrappers


def _group_queries_by_curve(queries: Iterable[IRSwaptionQuery]) -> Dict[str, List[IRSwaptionQuery]]:
    out: Dict[str, List[IRSwaptionQuery]] = defaultdict(list)
    for q in queries:
        if not q.curve:
            raise ValueError("Each IRSwaptionQuery must set .curve for IRSwaptionsTB.")
        out[q.curve].append(q)
    return dict(out)


def _is_today(d: DateLike) -> bool:
    if isinstance(d, datetime.datetime):
        return d.date() == datetime.date.today()
    if isinstance(d, datetime.date):
        return d == datetime.date.today()
    return False


def _build_row_for_query(
    context: IRSwaptionMarketContext,
    q: IRSwaptionQuery,
    ref_dt: DateLike,
) -> tuple[DateLike, str, float]:
    q_eff = resolve_query(q, timestamp=ref_dt, pricer_or_curve=context)
    if getattr(q, "name", None):
        col = str(q.name)
    else:
        col = q_eff.col_name()
    package, risk_weights = q_eff.resolve_package(pricer_or_curve=context, is_for_timeseries=True)
    vmap = q_eff.build_value_map(pricer_or_curve=context, package=package, risk_weights=risk_weights)
    value = vmap.apply(value=q_eff.value, **(q_eff.value_kwargs or {}))
    return ref_dt, col, float(value)


class IRSwaptionsTB(LayeredCacheMixin, BaseTimeseriesTB):
    _CACHE_ATTR_BASE = "_irswaptions_tb_cache"
    _CACHE_VERSION = "v1"
    _DEFAULT_PRICING_MESSAGE = "PRICING IRSWAPTIONS."

    def __init__(
        self,
        mdp: IRSwaptionMDP,
        *,
        date_col: str = "Date",
        cache_stem: Optional[str] = None,
        force_refresh: bool = False,
        use_btree: bool = True,
        show_tqdm: bool = True,
        logger: Optional[logging.Logger] = None,
    ):
        LayeredCacheMixin.__init__(
            self,
            use_btree=use_btree,
            force_refresh=force_refresh,
            mdp=mdp,
            date_col=date_col,
            show_tqdm=show_tqdm,
        )
        self._logger = logger or logging.getLogger(_LOGGER_NAME)
        stem = cache_stem or f"IRSwaptionsTB_{self._CACHE_VERSION}_{mdp.source}"
        self._cache_path = self.default_cache_path(stem=stem)
        self._cache_attr = f"{self._CACHE_ATTR_BASE}_{self._CACHE_VERSION}"
        self.open_cache(cache_attr=self._cache_attr, path=self._cache_path)

    def close(self):
        if hasattr(self, self._cache_attr):
            self.close_cache()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def _cache_key(self, d: DateLike, curve_name: str, q: IRSwaptionQuery) -> str:
        ns = _dt_to_epoch_ns(d)
        qh = _query_fingerprint(q)
        return f"{self._CACHE_VERSION}|{curve_name}|{ns}|{qh}"

    def _flatten_queries(
        self,
        queries: List[IRSwaptionQuery | List[IRSwaptionQuery] | IRSwaptionQueryWrapper],
    ) -> List[IRSwaptionQuery]:
        flat, _ = _flatten_queries_with_wrappers(queries)
        return flat

    def get_timeseries(
        self,
        start: DateLike,
        end: DateLike,
        queries: List[IRSwaptionQuery | List[IRSwaptionQuery] | IRSwaptionQueryWrapper],
        *,
        n_jobs: Optional[int] = 1,
        ignore_cache: Optional[bool] = False,
        freq: Optional[str] = None,
        timestamps: Optional[List[datetime.datetime]] = None,
    ) -> pd.DataFrame:
        assert start <= end, "must have end >= start"
        ref_points = self._build_reference_points(start=start, end=end, freq=freq, timestamps=timestamps)
        if not ref_points:
            return pd.DataFrame(columns=[self._date_col]).set_index(pd.Index([], name=self._date_col))

        flat, wrappers = _flatten_queries_with_wrappers(queries)
        if not flat:
            return pd.DataFrame(columns=[self._date_col]).set_index(pd.Index([], name=self._date_col))

        by_curve = _group_queries_by_curve(flat)
        cache_map = getattr(self, self._cache_attr)

        cached_rows: list[tuple[DateLike, str, float]] = []
        to_fetch: DefaultDict[str, set] = defaultdict(set)
        for d in ref_points:
            for curve_name, qs in by_curve.items():
                for q in qs:
                    if _is_today(d):
                        to_fetch[curve_name].add(d)
                        continue
                    k = self._cache_key(d, curve_name, q)
                    if (k in cache_map) and not ignore_cache:
                        cached_rows.append(cache_map[k])
                    else:
                        to_fetch[curve_name].add(d)

        new_rows_with_meta: list[tuple[tuple[DateLike, str, float], IRSwaptionQuery, str, DateLike]] = []

        curve_iter = _tqdm(
            list(to_fetch.items()),
            desc=self._pricing_message(flat),
            disable=not self._show_tqdm,
        )
        for curve_name, missing_dates in curve_iter:
            if not missing_dates:
                continue

            built_map = self.mdp.bulk_get_data(
                {
                    "endpoint": "swaption_snapshot",
                    "curve_name": curve_name,
                    "timestamps": sorted(missing_dates),
                    "ignore_cache": bool(ignore_cache),
                }
            )
            qs = by_curve[curve_name]
            tasks: list[tuple[DateLike, IRSwaptionQuery, IRSwaptionMarketContext]] = []
            for d in sorted(missing_dates):
                ctx = built_map.get(d)
                if ctx is None and d == datetime.date.today():
                    ctx = built_map.get(datetime.date.today())
                if ctx is None:
                    self._logger.warning(f"No swaption context for curve='{curve_name}', date='{d}'.")
                    continue
                for q in qs:
                    tasks.append((d, q, ctx))

            if not tasks:
                continue

            if (n_jobs or 1) > 1:
                max_workers = int(n_jobs) if n_jobs and n_jobs > 1 else 1
                with ThreadPoolExecutor(max_workers=max_workers) as ex:
                    fut_map = {ex.submit(_build_row_for_query, ctx, q, d): (d, q, ctx) for d, q, ctx in tasks}
                    for fut in _tqdm(
                        as_completed(fut_map),
                        total=len(fut_map),
                        desc=f"VALUING IRSWAPTIONS [{curve_name}]",
                        disable=not self._show_tqdm,
                        leave=False,
                    ):
                        d, q, _ctx = fut_map[fut]
                        try:
                            row = fut.result()
                            new_rows_with_meta.append((row, q, curve_name, d))
                        except Exception as exc:
                            self._logger.exception(f"Swaption pricing failed for curve='{curve_name}', date='{d}', query='{q}'. Error: {exc}")
            else:
                for d, q, ctx in _tqdm(
                    tasks,
                    desc=f"VALUING IRSWAPTIONS [{curve_name}]",
                    disable=not self._show_tqdm,
                    leave=False,
                ):
                    try:
                        row = _build_row_for_query(ctx, q, d)
                        new_rows_with_meta.append((row, q, curve_name, d))
                    except Exception as exc:
                        self._logger.exception(f"Swaption pricing failed for curve='{curve_name}', date='{d}', query='{q}'. Error: {exc}")

        with self.batched():
            mapping = getattr(self, self._cache_attr)
            for row, q, curve_name, d in new_rows_with_meta:
                if _is_today(d):
                    continue
                mapping[self._cache_key(d, curve_name, q)] = row

        all_rows = cached_rows + [r for (r, _q, _cn, _d) in new_rows_with_meta]
        if not all_rows:
            return pd.DataFrame(columns=[self._date_col]).set_index(pd.Index([], name=self._date_col))

        out = self._rows_to_frame(all_rows)

        if wrappers:
            for w in wrappers:
                expr = w.eval_expression()
                try:
                    out[w.col_name()] = out.eval(expr, engine="python")
                except Exception as exc:
                    self._logger.warning(f"Wrapper expression failed for '{w.col_name()}': {exc}")

        return out.sort_index()
