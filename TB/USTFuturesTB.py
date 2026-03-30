import datetime
import hashlib
import json
import logging
from collections import defaultdict
from typing import Dict, List, Mapping, Optional, Sequence, Tuple, Union

import pandas as pd
import QuantLib as ql
from tqdm import tqdm

from Caching.computed_timeseries_store import ComputedTimeseriesStore
from Caching.layered_cache_mixin import LayeredCacheMixin
from MDP.USTFutures.USTFuturesMDP import USTFuturesMDP
from Query.Base.BaseQuery import BaseQuery
from Query.Base.query_resolution import resolve_query
from Query.USTFutures.USTFutureQuery import USTFutureQuery
from TB.BaseTimeseriesTB import BaseTimeseriesTB
from TB.utils import DateLike, _canonicalize_value, _dt_to_epoch_ns
from utils.ql_utils import datetime_to_ql_date

_LOGGER_NAME = "USTFuturesTB"


def _query_fingerprint(q: USTFutureQuery) -> str:
    payload = {
        "symbol": getattr(q, "symbol", None),
        "tenor": getattr(q, "tenor", None),
        "contract": getattr(q, "contract", None),
        "value": (
            [_canonicalize_value(v) for v in q.value]
            if isinstance(getattr(q, "value", None), list)
            else _canonicalize_value(getattr(q, "value", None))
        ),
        "structure": getattr(q, "structure", None).name if getattr(q, "structure", None) else None,
        "structure_kwargs": _canonicalize_value(getattr(q, "structure_kwargs", {}) or {}),
        "name": getattr(q, "name", None),
        "risk_weight": getattr(q, "risk_weight", None),
    }
    s = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def _flatten_queries(queries: List[Union[USTFutureQuery, List[USTFutureQuery]]]) -> List[USTFutureQuery]:
    flat: List[USTFutureQuery] = []
    for q in queries:
        if isinstance(q, list):
            flat.extend(q)
        else:
            flat.append(q)
    return flat


class USTFuturesTB(LayeredCacheMixin, BaseTimeseriesTB):
    _CACHE_ATTR_BASE = "_ustfutures_tb_cache"
    _DEFAULT_PRICING_MESSAGE = "PRICING UST FUTURES."
    _CACHE_VERSION = "v1"

    def __init__(
        self,
        mdp: USTFuturesMDP,
        *,
        date_col: str = "Date",
        cache_stem: Optional[str] = None,
        force_refresh: bool = False,
        use_btree: bool = True,
        show_tqdm: bool = True,
        logger: Optional[logging.Logger] = None,
        skip_non_business: bool = True,
        calendar: Optional[ql.Calendar] = None,
        use_ts_cache: bool = True,
        ts_base_dir: Optional[str] = "./data/ts",
        ts_row_group_size: int = 256_000,
        ts_compression: str = "zstd",
        use_duckdb: bool = True,
        duckdb_path: Optional[str] = None,
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
        self._skip_non_business = skip_non_business
        self._cal = calendar or ql.UnitedStates(ql.UnitedStates.GovernmentBond)

        stem = cache_stem or f"USTFuturesTB_{self._CACHE_VERSION}_{mdp.source}"
        self._cache_path = self.default_cache_path(stem=stem)
        self._cache_attr = f"{self._CACHE_ATTR_BASE}_{self._CACHE_VERSION}"
        self.open_cache(cache_attr=self._cache_attr, path=self._cache_path)

        self._use_ts_cache = bool(use_ts_cache)
        self._computed_ts_store = ComputedTimeseriesStore(
            base_dir=ts_base_dir or "./data/ts",
            compression=ts_compression,
            row_group_size=int(ts_row_group_size),
            use_duckdb=use_duckdb,
            duckdb_path=duckdb_path,
        )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self):
        if hasattr(self, self._cache_attr):
            self._logger.debug(f"Closing cache: {self._cache_attr}")
            self.close_cache()

    def _cache_key(self, d: DateLike, q: USTFutureQuery) -> str:
        ns = _dt_to_epoch_ns(d)
        qh = _query_fingerprint(q)
        return f"{self._CACHE_VERSION}|{ns}|{qh}"

    def _flatten_queries(
        self,
        queries: List[Union[BaseQuery, List[BaseQuery]]],
    ) -> List[USTFutureQuery]:
        flat: List[USTFutureQuery] = []
        for q in queries:
            if isinstance(q, list):
                for qq in q:
                    if not isinstance(qq, USTFutureQuery):
                        raise TypeError(f"USTFuturesTB requires USTFutureQuery inputs, got: {type(qq).__name__}")
                    flat.append(qq)
            else:
                if not isinstance(q, USTFutureQuery):
                    raise TypeError(f"USTFuturesTB requires USTFutureQuery inputs, got: {type(q).__name__}")
                flat.append(q)
        return flat

    def _ts_symbol_for_query(self, q: USTFutureQuery) -> str:
        return f"USTF::{self.mdp.source}::{_query_fingerprint(q)}"

    def get_timeseries(
        self,
        start: DateLike,
        end: DateLike,
        queries: List[Union[USTFutureQuery, List[USTFutureQuery]]],
        *,
        n_jobs: Optional[int] = 1,
        ignore_cache: Optional[bool] = False,
        freq: Optional[str] = None,
        timestamps: Optional[List[datetime.datetime]] = None,
        _prefetched_ts_rows_by_symbol: Optional[Mapping[str, Sequence[Tuple[DateLike, str, float]]]] = None,
    ) -> pd.DataFrame:
        has_timestamps = timestamps is not None and len(timestamps) > 0
        is_intraday = isinstance(start, datetime.datetime) and isinstance(end, datetime.datetime) and (freq is not None)

        if has_timestamps:
            ref_points = self._build_reference_points(start=start, end=end, freq=freq, timestamps=timestamps)
            is_intraday = True
        elif is_intraday:
            assert start.tzinfo is not None, "Must pass in timezone-aware datetime.datetime"
            eff_freq = freq or "1T"
            ref_points = self._build_reference_points(start=start, end=end, freq=eff_freq, timestamps=None)
        else:
            if self._skip_non_business:
                ref_points = []
                for d in pd.date_range(start=start, end=end, freq="D"):
                    qld = datetime_to_ql_date(d.date())
                    if self._cal.isBusinessDay(qld):
                        ref_points.append(d.date())
            else:
                ref_points = pd.date_range(start, end, freq="D").date.tolist()

        flat = self._flatten_queries(queries)
        cached_rows: List[Tuple[DateLike, str, float]] = []
        cached_row_keys: set[Tuple[DateLike, str]] = set()
        today = datetime.date.today()
        prefetched_ts_rows_by_symbol = {
            str(symbol): list(rows)
            for symbol, rows in (_prefetched_ts_rows_by_symbol or {}).items()
        }

        # ---- Stage 1: Read from computed TS cache ----
        _skip_ts_cache = is_intraday and len(ref_points) > 50
        if self._use_ts_cache and not ignore_cache and flat and not _skip_ts_cache:
            for q in flat:
                symbol = self._ts_symbol_for_query(q)
                prefetched_rows = prefetched_ts_rows_by_symbol.get(symbol)
                if prefetched_rows is not None:
                    rows = list(prefetched_rows)
                else:
                    try:
                        rows = self._computed_ts_store.read_rows(
                            symbol=symbol,
                            reference_points=ref_points,
                            intraday=is_intraday,
                            skip_current_eod=True,
                            fallback_column_name=q.col_name(),
                            allow_partial=True,
                        )
                    except Exception as ex:
                        self._logger.debug(f"[TS cache] read failed for symbol={symbol}: {ex}")
                        rows = []
                cached_rows.extend(rows)
                cached_row_keys.update((row_d, row_c) for row_d, row_c, _ in rows)

        # ---- Stage 2: Determine which dates need pricing ----
        to_price_dates: List[DateLike] = []
        cache_map = getattr(self, self._cache_attr)

        for d in ref_points:
            all_cached = True
            for q in flat:
                hit_ts = (d, q.col_name()) in cached_row_keys
                k = self._cache_key(d, q)
                hit_row = (k in cache_map) and not (d == today or d == "live") and not bool(ignore_cache)
                if hit_row and not hit_ts:
                    row = cache_map[k]
                    cached_rows.append(row)
                    cached_row_keys.add((row[0], row[1]))
                if not hit_ts and not hit_row:
                    all_cached = False
            if not all_cached:
                to_price_dates.append(d)

        if not to_price_dates and cached_rows:
            return self._rows_to_frame(cached_rows)

        # ---- Stage 3: Collect symbols needed ----
        needed_symbols: List[str] = []
        for q in flat:
            skw = q.structure_kwargs or {}
            for key in ("front_symbol", "back_symbol", "belly_symbol", "symbol"):
                val = skw.get(key)
                if val and val not in needed_symbols:
                    needed_symbols.append(val)

        # ---- Stage 4: Bulk fetch pricers ----
        try:
            bulk_map: Dict[DateLike, dict] = self.mdp.bulk_get_data(
                timestamps=to_price_dates,
                symbols=needed_symbols,
                show_tqdm=True,
            )
        except Exception as e:
            self._logger.exception(f"bulk_get_data failed: {e}")
            bulk_map = {}

        # ---- Stage 5: Price queries from fetched pricers ----
        new_rows_with_q: List[Tuple[Tuple[DateLike, str, float], USTFutureQuery]] = []
        total_tasks = sum(1 for _ in to_price_dates for _ in flat)
        pbar_disable = not self._show_tqdm

        with tqdm(total=total_tasks, disable=pbar_disable, desc=self._DEFAULT_PRICING_MESSAGE, leave=True) as pbar:
            for d in to_price_dates:
                pricer_map = bulk_map.get(d, {})
                if not pricer_map:
                    pbar.update(len(flat))
                    continue

                for q in flat:
                    try:
                        q_eff = resolve_query(q, timestamp=d, pricer_or_curve=pricer_map)
                        pkg, rw = q_eff.resolve_package(pricer_or_curve=pricer_map, is_for_timeseries=True)
                        vmap = q_eff.build_value_map(pricer_or_curve=pricer_map, package=pkg, risk_weights=rw)
                        value_key = getattr(q_eff, "value", None) or q_eff.default_mtm_value_id()
                        value_kwargs = getattr(q_eff, "value_kwargs", {}) or {}
                        value = vmap.apply(value=value_key, **value_kwargs)

                        col_name = q.col_name() if getattr(q, "name", None) else q_eff.col_name()
                        row = (d, col_name, float(value))
                        new_rows_with_q.append((row, q))
                    except Exception as e:
                        self._logger.debug(f"Pricing failed for date={d}, query={q}: {e}")
                    finally:
                        pbar.update(1)

        # ---- Stage 6: Write to caches ----
        with self.batched():
            mapping = getattr(self, self._cache_attr)
            for row, q in new_rows_with_q:
                ref_date = row[0]
                if ref_date == today or ref_date == "live":
                    continue
                mapping[self._cache_key(ref_date, q)] = row

        if self._use_ts_cache and new_rows_with_q:
            grouped: Dict[str, List[Tuple[DateLike, str, float]]] = defaultdict(list)
            for (dt_like, col, val), q in new_rows_with_q:
                if dt_like == today or dt_like == "live":
                    continue
                grouped[self._ts_symbol_for_query(q)].append((dt_like, col, float(val)))
            if grouped:
                try:
                    self._computed_ts_store.append_many_rows(rows_by_symbol=grouped)
                except Exception as ex:
                    self._logger.warning(f"[TS cache] bulk append failed: {ex}")

        # ---- Stage 7: Combine and return ----
        all_rows = cached_rows + [r for r, _q in new_rows_with_q]
        if not all_rows:
            return pd.DataFrame(columns=[self._date_col])

        return self._rows_to_frame(all_rows)
