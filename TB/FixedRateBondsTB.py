import copy
import datetime
import hashlib
import json
import logging
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from typing import Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd
import QuantLib as ql
from tqdm import tqdm

# fmt: off
import Query.FixedRateBonds.adapter  # noqa: F401  # ensure pricer adapters are registered
# fmt: on
from Caching.timeseries_cache import WriteOptions, append_timeseries, read_timeseries
from Caching.ZODBCacheMixin import ZODBCacheMixin
from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP
from Query.FixedRateBonds._FixedRateBondGenericPricer import _FixedRateBondGenericPricer
from Query.FixedRateBonds.FixedRateBondQuery import FixedRateBondQuery
from Query.FixedRateBonds.FixedRateBondStructure import FixedRateBondStructure
from TB.utils import DateLike, _canonicalize_value, _dt_to_epoch_ns
from utils.ql_utils import datetime_to_ql_date


_LOGGER_NAME = "FixedRateBondsTB"


def _query_fingerprint(q: "FixedRateBondQuery") -> str:
    payload = {
        "cusip": getattr(q, "cusip", None),
        "value": ([_canonicalize_value(v) for v in q.value] if isinstance(getattr(q, "value", None), list) else _canonicalize_value(getattr(q, "value", None))),
        "structure": getattr(q, "structure", None).name if getattr(q, "structure", None) else None,
        "structure_kwargs": _canonicalize_value(getattr(q, "structure_kwargs", {}) or {}),
        "name": getattr(q, "name", None),
        "risk_weight": getattr(q, "risk_weight", None),
        # NB: we purposely exclude execution terms and MDP source here (market/time axes)
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
    structure = q.structure
    txt = q.cusip or ""
    if "x" in txt or "/" in txt:
        if txt.count("x") == 1 or txt.count("/") == 1:
            structure = FixedRateBondStructure.CURVE
        elif txt.count("x") == 2 or txt.count("/") == 2:
            structure = FixedRateBondStructure.FLY
    else:
        structure = FixedRateBondStructure.OUTRIGHT

    skw = dict(getattr(q, "structure_kwargs", {}) or {})
    skw.setdefault("cusip", q.cusip)
    skw.setdefault("bpv", 1)

    user_passed_rws = _clone_risk_weights(skw.get("risk_weights", None))
    user_passed_col_name = q.col_name()

    try:
        q_eff = replace(q, structure=structure, structure_kwargs=skw)
    except TypeError:
        q_eff = replace(q, structure=structure, structure_id=structure, structure_kwargs=skw)

    pkg, rw = q_eff.resolve_package(pricer_or_curve=pricer_for_cusip, is_for_timeseries=True)

    vmap = q_eff.build_value_map(pricer_or_curve=pricer_for_cusip, package=pkg, risk_weights=user_passed_rws if user_passed_rws is not None else rw)
    value = vmap.apply(value=q_eff.value)
    return ref_dt, user_passed_col_name, float(value)


class FixedRateBondsTB(ZODBCacheMixin):
    _CACHE_ATTR_BASE = "_fixedratebonds_tb_cache"
    _DEFAULT_PRICING_MESSAGE = "PRICING FIXED-RATE BONDS."
    _CACHE_VERSION = "v1"

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
        # >>> added (timeseries cache controls)
        use_ts_cache: bool = True,
        ts_base_dir: Optional[str] = "./data/ts",
        ts_row_group_size: int = 256_000,
        ts_compression: str = "zstd",
    ):
        super().__init__(use_btree=use_btree, force_refresh=force_refresh)

        self.mdp = mdp
        self._date_col = date_col
        self._show_tqdm = show_tqdm
        self._logger = logger or logging.getLogger(_LOGGER_NAME)

        self._skip_non_business = skip_non_business
        self._cal = calendar or ql.UnitedStates(ql.UnitedStates.GovernmentBond)

        stem = cache_stem or f"FixedRateBondsTB_{self._CACHE_VERSION}_{mdp.source}"
        self._cache_path = self.default_cache_path(stem=stem)
        self._cache_attr = f"{self._CACHE_ATTR_BASE}_{self._CACHE_VERSION}"

        # mapping cache: key=(iso_date, query_fingerprint) -> (date, col, val)
        self.zodb_open_cache(cache_attr=self._cache_attr, path=self._cache_path)

        # >>> added
        self._use_ts_cache = bool(use_ts_cache)
        self._ts_write_opts = WriteOptions(
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
            self._logger.debug(f"Closing ZODB connection for cache: {self._cache_attr}")
            self.close_zodb()

    def _cache_key(self, d: DateLike, q: FixedRateBondQuery) -> str:
        ns = _dt_to_epoch_ns(d)
        qh = _query_fingerprint(q)
        return f"{self._CACHE_VERSION}|{ns}|{qh}"

    # >>> added
    def _ts_symbol_for_query(self, q: FixedRateBondQuery) -> str:
        """
        Stable, unique symbol for the timeseries cache (content-addressed by query fingerprint).
        Namespaced by source to avoid cross-source collisions.
        """
        return f"FRB::{self.mdp.source}::{_query_fingerprint(q)}"

    # >>> added
    @staticmethod
    def _to_timestamp(d: DateLike) -> pd.Timestamp:
        if isinstance(d, datetime.datetime):
            return pd.Timestamp(d)
        if isinstance(d, datetime.date):
            return pd.Timestamp(d)
        return pd.Timestamp(d)

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
        if timestamps is not None and len(timestamps) > 0:
            ref_points = sorted(pd.to_datetime(pd.Index(timestamps)).to_pydatetime().tolist())
            is_intraday = True
        else:
            is_intraday = isinstance(start, datetime.datetime) and isinstance(end, datetime.datetime) and (freq is not None)
            if is_intraday:
                assert start.tzinfo is not None, "Must pass in timezone-aware datetime.datetime"
                eff_freq = freq or "1T"
                rng = pd.date_range(start=start, end=end, freq=eff_freq, tz=start.tzinfo)
                ref_points = rng.to_pydatetime().tolist()
            else:
                if self._skip_non_business:
                    bd = []
                    for d in pd.date_range(start=start, end=end, freq="D"):
                        qld = datetime_to_ql_date(d.date())
                        if self._cal.isBusinessDay(qld):
                            bd.append(d.date())
                    ref_points = bd
                else:
                    ref_points = pd.date_range(start, end, freq="D").date.tolist()

        flat: List[FixedRateBondQuery] = _flatten_queries(queries)

        cached_rows: List[Tuple[DateLike, str, float]] = []
        ref_points_set = set(ref_points)
        today = datetime.date.today()

        if self._use_ts_cache and not ignore_cache and flat:
            ts_root = getattr(self, self._cache_attr)

            for q in flat:
                symbol = self._ts_symbol_for_query(q)

                try:
                    df_ts = read_timeseries(
                        ts_root,
                        symbol,
                        start=min(ref_points) if ref_points else None,
                        end=max(ref_points) if ref_points else None,
                        columns=None,
                        base_dir=self._ts_write_opts.base_dir,
                    )
                except Exception as ex:
                    self._logger.debug(f"[TS cache] read failed for symbol={symbol}: {ex}")
                    df_ts = pd.DataFrame()

                if df_ts.empty:
                    continue

                # Normalize index to naive timestamps/dates comparable to ref_points
                # If '_index_ts' handling happened, read_timeseries already restored index.
                if not isinstance(df_ts.index, (pd.DatetimeIndex, pd.Index)):
                    df_ts.index = pd.to_datetime(df_ts.index)

                # Allow either single 'value' column or multi-column; take the first numeric
                col_candidates = [c for c in df_ts.columns if pd.api.types.is_numeric_dtype(df_ts[c])]
                if not col_candidates:
                    continue
                c0 = col_candidates[0]

                # For date-only schedules, cast to .date() for matching
                if not is_intraday:
                    present = {ts_ts.date(): float(v) for ts_ts, v in df_ts[c0].items()}
                else:
                    present = {pd.Timestamp(ts_ts): float(v) for ts_ts, v in df_ts[c0].items()}

                # Add rows for dates/timestamps we have, but skip "today" to avoid staleness
                for rp in ref_points:
                    if (not is_intraday) and (isinstance(rp, datetime.date)) and (rp == today):
                        continue
                    if rp in present:
                        cached_rows.append((rp, q.col_name(), present[rp]))

        qs_per_date: Dict[Union[datetime.date, datetime.datetime], List[FixedRateBondQuery]] = {d: list(flat) for d in ref_points}
        to_price_dates: List[Union[datetime.date, datetime.datetime]] = []

        cache_map = getattr(self, self._cache_attr)

        for d in ref_points:
            all_cached = True

            for q in flat:
                # prefer TS cache hit first
                hit_ts = any((row_d == d and row_c == q.col_name()) for (row_d, row_c, _v) in cached_rows)

                # fall back to old ZODB row cache
                k = self._cache_key(d, q)
                hit_row = (k in cache_map) and not (d == today or d == "live") and not bool(ignore_cache)
                if hit_row and not hit_ts:
                    cached_rows.append(cache_map[k])

                if not hit_ts and not hit_row:
                    all_cached = False

            if not all_cached:
                to_price_dates.append(d)

        if not to_price_dates and cached_rows:
            df = pd.DataFrame(cached_rows, columns=[self._date_col, "_col", "_val"])
            out = df.pivot_table(index=self._date_col, columns="_col", values="_val", aggfunc="last").sort_index()
            out = out.reset_index()
            out.index.name = None
            out.columns.name = None
            return out.set_index(self._date_col)

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

        seen = set()
        uniq_symbols: List[str] = []
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
        desc = f"{self._DEFAULT_PRICING_MESSAGE}"

        with tqdm(total=total_tasks, disable=pbar_disable, desc=desc, leave=True) as pbar:

            def _build_task_inputs(d, q) -> Optional[Tuple[DateLike, FixedRateBondQuery, Dict[str, _FixedRateBondGenericPricer]]]:
                pr_map_all = bulk_map.get(d, {})
                if not isinstance(pr_map_all, dict):
                    return None

                parts = _split_components(str(q.cusip))
                missing = [k for k in parts if k not in pr_map_all]
                if missing:
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
                    t = _build_task_inputs(d, q)
                    if t is not None:
                        tasks.append(t)
                    else:
                        pbar.update(1)

            if (n_jobs or 1) > 1:
                max_workers = int(n_jobs) if n_jobs and n_jobs > 1 else None
                with ThreadPoolExecutor(max_workers=max_workers) as ex:
                    fut_map = {ex.submit(_build_row_for_query, pr_map, q, d, self._date_col): (q, d) for (d, q, pr_map) in tasks}
                    for fut in as_completed(fut_map):
                        q, d0 = fut_map[fut]
                        try:
                            row = fut.result()
                            new_rows_with_q.append((row, q, d0))
                        except Exception as e:
                            self._logger.exception(f"Pricing failed for cusip='{q.cusip}', date='{d0}', query='{q}'. Error: {e}")
                        finally:
                            pbar.update(1)
            else:
                for d0, q, pr_map in tasks:
                    try:
                        row = _build_row_for_query(pr_map, q, d0, self._date_col)
                        new_rows_with_q.append((row, q, d0))
                    except Exception as e:
                        self._logger.exception(f"Pricing failed for cusip='{q.cusip}', date='{d0}', query='{q}'. Error: {e}")
                    finally:
                        pbar.update(1)

        with self.batched():
            mapping = getattr(self, self._cache_attr)
            for row, q, d in new_rows_with_q:
                mapping[self._cache_key(d, q)] = row

        if self._use_ts_cache and new_rows_with_q:
            ts_root = getattr(self, self._cache_attr)  # persistent mapping works as “root” for catalog
            # Group rows by query (symbol)
            grouped: Dict[str, List[Tuple[pd.Timestamp, float, str]]] = defaultdict(list)
            for (dt_like, col, val), q, _d in new_rows_with_q:
                sym = self._ts_symbol_for_query(q)
                ts = self._to_timestamp(dt_like)
                grouped[sym].append((ts, float(val), col))
            # Write one symbol at a time
            for sym, rows in grouped.items():
                if not rows:
                    continue
                rows_sorted = sorted(rows, key=lambda x: x[0])
                ts_index = pd.DatetimeIndex([t for (t, _v, _c) in rows_sorted])
                df_sym = pd.DataFrame({"value": [v for (_t, v, _c) in rows_sorted]}, index=ts_index)
                # append_timeseries partitions by calendar date
                try:
                    append_timeseries(
                        ts_root,
                        sym,
                        df_sym,
                        opts=self._ts_write_opts,
                    )
                except Exception as ex:
                    self._logger.warning(f"[TS cache] append failed for symbol={sym}: {ex}")

        all_rows = cached_rows + [r for (r, _q, _d) in new_rows_with_q]
        if not all_rows:
            return pd.DataFrame(columns=[self._date_col])

        df = pd.DataFrame(all_rows, columns=[self._date_col, "_col", "_val"])
        out = df.pivot_table(index=self._date_col, columns="_col", values="_val", aggfunc="last").sort_index()
        out = out.reset_index()
        out.index.name = None
        out.columns.name = None
        return out.set_index(self._date_col)
