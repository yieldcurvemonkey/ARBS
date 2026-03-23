import copy
import datetime
import hashlib
import json
import logging
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd
import QuantLib as ql
from tqdm import tqdm

# fmt: off
import Query.FixedRateBonds.adapter  # noqa: F401  # ensure pricer adapters are registered
# fmt: on
from Caching.computed_timeseries_store import ComputedTimeseriesStore
from Caching.layered_cache_mixin import LayeredCacheMixin
from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP
from Query.Base.query_resolution import resolve_query
from Query.FixedRateBonds._FixedRateBondGenericPricer import _FixedRateBondGenericPricer
from Query.FixedRateBonds.FixedRateBondQuery import FixedRateBondQuery
from Query.FixedRateBonds.FixedRateBondStructure import FixedRateBondStructure
from Query.FixedRateBonds.FixedRateBondValue import FixedRateBondValue
from TB.BaseTimeseriesTB import BaseTimeseriesTB
from TB.utils import DateLike, _canonicalize_value, _dt_to_epoch_ns
from utils.ql_utils import datetime_to_ql_date


_LOGGER_NAME = "FixedRateBondsTB"


def _query_fingerprint(q: "FixedRateBondQuery") -> str:
    payload = {
        "cusip": getattr(q, "cusip", None),
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


def _flatten_queries(queries: List[FixedRateBondQuery | List[FixedRateBondQuery]]) -> List[FixedRateBondQuery]:
    flat: List[FixedRateBondQuery] = []
    for q in queries:
        if isinstance(q, list):
            flat.extend(q)
        else:
            flat.append(q)
    return flat


def _clone_risk_weights(rws):
    if rws is None:
        return None
    if isinstance(rws, np.ndarray):
        return rws.copy()
    if isinstance(rws, (pd.Series, pd.DataFrame)):
        return rws.copy(deep=True)
    if isinstance(rws, (list, tuple, set, dict)):
        return copy.deepcopy(rws)
    if hasattr(rws, "copy") and callable(rws.copy):
        try:
            return rws.copy()
        except Exception:
            pass
    return copy.deepcopy(rws)


def _build_row_for_query(
    pricer_for_cusip: Dict[str, _FixedRateBondGenericPricer],
    q: FixedRateBondQuery,
    ref_dt: DateLike,
    date_col: str,
) -> Tuple[DateLike, str, float]:
    simple_cusip = str(getattr(q, "cusip", "") or "").strip()
    simple_structure_kwargs = dict(getattr(q, "structure_kwargs", {}) or {})
    if (
        getattr(q, "structure", None) == FixedRateBondStructure.OUTRIGHT
        and getattr(q, "value", None) == FixedRateBondValue.YTM
        and simple_cusip
        and simple_cusip in pricer_for_cusip
        and not any(
            simple_structure_kwargs.get(key) is not None
            for key in (
                "issue_date",
                "maturity_date",
                "cpn",
                "coupon",
                "notional",
                "bpv",
            )
        )
    ):
        return ref_dt, q.col_name(), float(pricer_for_cusip[simple_cusip].ytm())

    q_eff = resolve_query(q, timestamp=ref_dt, pricer_or_curve=pricer_for_cusip)
    skw = dict(getattr(q_eff, "structure_kwargs", {}) or {})
    user_passed_rws = _clone_risk_weights(skw.get("risk_weights", None))
    user_passed_col_name = q_eff.col_name()

    pkg, rw = q_eff.resolve_package(pricer_or_curve=pricer_for_cusip, is_for_timeseries=True)
    vmap = q_eff.build_value_map(
        pricer_or_curve=pricer_for_cusip,
        package=pkg,
        risk_weights=user_passed_rws if user_passed_rws is not None else rw,
    )
    value = vmap.apply(value=q_eff.value)
    return ref_dt, user_passed_col_name, float(value)


class FixedRateBondsTB(LayeredCacheMixin, BaseTimeseriesTB):
    _CACHE_ATTR_BASE = "_fixedratebonds_tb_cache"
    _DEFAULT_PRICING_MESSAGE = "PRICING FIXED-RATE BONDS."
    _CACHE_VERSION = "v1"
    _ROW_CACHE_L2_SCAN_SUPPRESS_THRESHOLD = 64

    def __init__(
        self,
        mdp: FixedRateBondsMDP,
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

        stem = cache_stem or f"FixedRateBondsTB_{self._CACHE_VERSION}_{mdp.source}"
        self._cache_path = self.default_cache_path(stem=stem)
        self._cache_attr = f"{self._CACHE_ATTR_BASE}_{self._CACHE_VERSION}"
        self.open_cache(cache_attr=self._cache_attr, path=self._cache_path)

        self._use_ts_cache = bool(use_ts_cache)
        self._computed_ts_store = ComputedTimeseriesStore(
            base_dir=ts_base_dir or "./data/ts",
            compression=ts_compression,
            row_group_size=int(ts_row_group_size),
        )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self):
        if hasattr(self, self._cache_attr):
            self._logger.debug(f"Closing cache: {self._cache_attr}")
            self.close_cache()

    def _cache_key(self, d: DateLike, q: FixedRateBondQuery) -> str:
        ns = _dt_to_epoch_ns(d)
        qh = _query_fingerprint(q)
        return f"{self._CACHE_VERSION}|{ns}|{qh}"

    def _flatten_queries(
        self,
        queries: List[FixedRateBondQuery | List[FixedRateBondQuery]],
    ) -> List[FixedRateBondQuery]:
        return _flatten_queries(queries)

    def _ts_symbol_for_query(self, q: FixedRateBondQuery) -> str:
        return f"FRB::{self.mdp.source}::{_query_fingerprint(q)}"

    @classmethod
    def _should_suppress_row_cache_l2(
        cls,
        *,
        reference_point_count: int,
        query_count: int,
    ) -> bool:
        probe_count = max(0, int(reference_point_count)) * max(1, int(query_count))
        return probe_count > cls._ROW_CACHE_L2_SCAN_SUPPRESS_THRESHOLD

    def get_timeseries(
        self,
        start: DateLike,
        end: DateLike,
        queries: List[FixedRateBondQuery | List[FixedRateBondQuery]],
        *,
        n_jobs: Optional[int] = 1,
        ignore_cache: Optional[bool] = False,
        freq: Optional[str] = None,
        timestamps: Optional[List[datetime.datetime]] = None,
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

        # Skip computed TS cache for large intraday runs — the Postgres/DuckDB
        # sync is too slow for hundreds of timestamps and the MDP pricer cache
        # is the authoritative source for intraday data.
        _skip_ts_cache = is_intraday and len(ref_points) > 50
        if self._use_ts_cache and not ignore_cache and flat and not _skip_ts_cache:
            for q in flat:
                symbol = self._ts_symbol_for_query(q)
                try:
                    rows = self._computed_ts_store.read_rows(
                        symbol=symbol,
                        reference_points=ref_points,
                        intraday=is_intraday,
                        skip_current_eod=True,
                        fallback_column_name=q.col_name(),
                    )
                except Exception as ex:
                    self._logger.debug(f"[TS cache] read failed for symbol={symbol}: {ex}")
                    rows = []
                cached_rows.extend(rows)
                cached_row_keys.update((row_d, row_c) for row_d, row_c, _ in rows)

        qs_per_date: Dict[Union[datetime.date, datetime.datetime], List[FixedRateBondQuery]] = {d: list(flat) for d in ref_points}
        to_price_dates: List[Union[datetime.date, datetime.datetime]] = []
        cache_map = getattr(self, self._cache_attr)

        # For large runs, temporarily suppress row-cache L2 probes during the
        # scan loop to avoid one remote round-trip per (date, query) miss.
        # bulk_get_data handles misses much more efficiently.
        _suppress_l2 = self._should_suppress_row_cache_l2(
            reference_point_count=len(ref_points),
            query_count=len(flat),
        )
        _prev_l2_read = None
        if _suppress_l2 and hasattr(cache_map, '_l2_read'):
            _prev_l2_read = cache_map._l2_read
            cache_map._l2_read = False

        try:
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
        finally:
            if _prev_l2_read is not None:
                cache_map._l2_read = _prev_l2_read

        if not to_price_dates and cached_rows:
            return self._rows_to_frame(cached_rows)

        def _split_components(txt: str) -> List[str]:
            s = (txt or "").strip()
            if ("x" in s) and ("Ox" not in s):
                return [p for p in s.split("x") if p]
            if ("/" in s) and (not re.match(r"^\d{2}\d{2}/\d{1,2}$", s)):
                return [p for p in s.split("/") if p]
            return [s] if s else []

        needed_symbols: List[str] = []
        for q in flat:
            needed_symbols.extend(_split_components(str(q.cusip)))

        uniq_symbols: List[str] = []
        seen = set()
        for s in needed_symbols:
            if s not in seen:
                seen.add(s)
                uniq_symbols.append(s)

        bulk_workers = int(n_jobs) if (n_jobs and n_jobs > 0) else 8
        try:
            bulk_map: Dict[DateLike, Dict[str, _FixedRateBondGenericPricer]] = self.mdp.bulk_get_data(
                timestamps=to_price_dates,
                cusips=uniq_symbols,
                show_tqdm=True,
                force_refresh=bool(ignore_cache),
                max_workers=bulk_workers,
            )
        except Exception as e:
            self._logger.exception(f"bulk_get_data failed. Falling back per-date. Error: {e}")
            bulk_map = {}

        new_rows_with_q: List[Tuple[Tuple[DateLike, str, float], FixedRateBondQuery, datetime.date | datetime.datetime]] = []
        total_tasks = sum(len(qs_per_date[d]) for d in to_price_dates)
        pbar_disable = not self._show_tqdm

        with tqdm(total=total_tasks, disable=pbar_disable, desc=self._DEFAULT_PRICING_MESSAGE, leave=True) as pbar:

            def _build_task_inputs(
                d: DateLike,
                q: FixedRateBondQuery,
            ) -> Optional[Tuple[DateLike, FixedRateBondQuery, Dict[str, _FixedRateBondGenericPricer]]]:
                pr_map_all = bulk_map.get(d, {})
                if not isinstance(pr_map_all, dict):
                    return None

                parts = _split_components(str(q.cusip))
                missing = [k for k in parts if k not in pr_map_all]
                if missing:
                    # For large intraday runs, skip expensive per-timestamp
                    # on-demand fetches — missing timestamps likely have no
                    # market data (e.g. before market open, gaps).
                    if _skip_ts_cache:
                        pass  # skip on-demand fetch for intraday fast path
                    else:
                        try:
                            fetched = self.mdp.get_pricer({"cusips": missing, "timestamp": d, "ignore_cache": ignore_cache})
                            pr_map_all = pr_map_all | (fetched or {})
                        except Exception as ex:
                            self._logger.warning(f"On-demand pricer fetch failed for date={d}, parts={missing}: {ex}")

                pr_map = {k: pr_map_all[k] for k in parts if k in pr_map_all}
                if not pr_map:
                    return None
                return (d, q, pr_map)

            tasks: List[Tuple[DateLike, FixedRateBondQuery, Dict[str, _FixedRateBondGenericPricer]]] = []
            for d in to_price_dates:
                for q in qs_per_date[d]:
                    task = _build_task_inputs(d, q)
                    if task is not None:
                        tasks.append(task)
                    else:
                        pbar.update(1)

            if (n_jobs or 1) > 1:
                max_workers = int(n_jobs) if n_jobs and n_jobs > 1 else None
                with ThreadPoolExecutor(max_workers=max_workers) as ex:
                    fut_map = {
                        ex.submit(_build_row_for_query, pr_map, q, d, self._date_col): (q, d)
                        for d, q, pr_map in tasks
                    }
                    for fut in as_completed(fut_map):
                        q, d0 = fut_map[fut]
                        try:
                            row = fut.result()
                            new_rows_with_q.append((row, q, d0))
                        except Exception as e:
                            self._logger.exception(
                                f"Pricing failed for cusip='{q.cusip}', date='{d0}', query='{q}'. Error: {e}"
                            )
                        finally:
                            pbar.update(1)
            else:
                for d0, q, pr_map in tasks:
                    try:
                        row = _build_row_for_query(pr_map, q, d0, self._date_col)
                        new_rows_with_q.append((row, q, d0))
                    except Exception as e:
                        self._logger.exception(
                            f"Pricing failed for cusip='{q.cusip}', date='{d0}', query='{q}'. Error: {e}"
                        )
                    finally:
                        pbar.update(1)

        with self.batched():
            mapping = getattr(self, self._cache_attr)
            # Suppress L2 writes for large intraday to avoid write storm
            _prev_l2_write = None
            if _suppress_l2 and hasattr(mapping, '_l2_write'):
                _prev_l2_write = mapping._l2_write
                mapping._l2_write = False
            try:
                for row, q, d in new_rows_with_q:
                    mapping[self._cache_key(d, q)] = row
            finally:
                if _prev_l2_write is not None:
                    mapping._l2_write = _prev_l2_write

        if self._use_ts_cache and new_rows_with_q and not _skip_ts_cache:
            grouped: Dict[str, List[Tuple[DateLike, str, float]]] = defaultdict(list)
            for (dt_like, col, val), q, _d in new_rows_with_q:
                grouped[self._ts_symbol_for_query(q)].append((dt_like, col, float(val)))
            try:
                self._computed_ts_store.append_many_rows(rows_by_symbol=grouped)
            except Exception as ex:
                self._logger.warning(f"[TS cache] bulk append failed: {ex}")

        all_rows = cached_rows + [r for (r, _q, _d) in new_rows_with_q]
        if not all_rows:
            return pd.DataFrame(columns=[self._date_col])

        return self._rows_to_frame(all_rows)
