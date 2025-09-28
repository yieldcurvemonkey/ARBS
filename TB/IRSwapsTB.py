import datetime
import hashlib
import json
import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from enum import Enum
from typing import DefaultDict, Dict, Iterable, List, Optional, Tuple, Union

import pandas as pd
from tqdm import tqdm

from Caching.ZODBCacheMixin import ZODBCacheMixin
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from Query.IRSwaps._IRSwapGenericCurve import _IRSwapGenericCurve
from Query.IRSwaps.IRSwapQuery import IRSwapQuery, IRSwapQueryWrapper
from Query.IRSwaps.IRSwapStructure import IRSwapStructureFunctionMap
from Query.IRSwaps.IRSwapValue import IRSwapValueFunctionMap

DateLike = Union[datetime.date, datetime.datetime]
_LOGGER_NAME = "IRSwapsTB"


def _to_utc_naive(dt: DateLike) -> datetime.datetime:
    """Return a timezone-naive UTC datetime for both date and datetime inputs."""
    if isinstance(dt, datetime.date) and not isinstance(dt, datetime.datetime):
        dt = datetime.datetime(dt.year, dt.month, dt.day)
    if dt.tzinfo is not None:
        dt = dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return dt  # naive UTC


def _dt_to_epoch_ns(dt: DateLike) -> int:
    """UTC-normalized epoch nanoseconds (stable for keying)."""
    dtu = _to_utc_naive(dt)
    return int(dtu.timestamp() * 1_000_000_000)


def _canonicalize_value(v):
    """Make any value JSON-serializable & stable."""
    if isinstance(v, (datetime.date, datetime.datetime)):
        return _to_utc_naive(v).isoformat()
    if isinstance(v, Enum):  # IRSwapValue is an Enum
        return v.name
    if isinstance(v, (list, tuple)):
        return [_canonicalize_value(x) for x in v]
    if isinstance(v, dict):
        # sort keys to ensure determinism
        return {k: _canonicalize_value(v[k]) for k in sorted(v.keys())}
    return v  # numbers/strings/None


def _query_fingerprint(q: "IRSwapQuery") -> str:
    """Stable hash of the query using canonical JSON."""
    payload = {
        "tenor": str(q.tenor) if q.tenor is not None else None,
        "effective_date": _canonicalize_value(q.effective_date),
        "maturity_date": _canonicalize_value(q.maturity_date),
        "structure": q.structure.name if getattr(q, "structure", None) else None,
        "value": ([_canonicalize_value(v) for v in q.value] if isinstance(q.value, list) else _canonicalize_value(q.value)),
        "structure_kwargs": _canonicalize_value(q.structure_kwargs or {}),
        "name": q.name,
        "risk_weight": q.risk_weight,
        # Note: we purposely DO NOT include q.curve here; it's a separate axis in the key
    }
    s = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def _query_to_key(q: IRSwapQuery) -> tuple:
    tenor = str(q.tenor) if q.tenor is not None else None
    eff = q.effective_date.isoformat() if q.effective_date else None
    mat = q.maturity_date.isoformat() if q.maturity_date else None
    val = tuple(q.value) if isinstance(q.value, list) else q.value
    struct = q.structure.name
    kwargs = tuple(sorted(q.structure_kwargs.items()))
    return (tenor, eff, mat, val, struct, kwargs, q.curve, q.name, q.risk_weight)


def _flatten_queries(queries: List[IRSwapQuery | List[IRSwapQuery] | IRSwapQueryWrapper]) -> List[IRSwapQuery]:
    flat: List[IRSwapQuery] = []
    for q in queries:
        if isinstance(q, list):
            flat.extend(q)
        elif isinstance(q, IRSwapQueryWrapper):
            flat.extend(q.return_query())
        else:
            flat.append(q)
    return flat


def _group_queries_by_curve(queries: Iterable[IRSwapQuery]) -> Dict[str, List[IRSwapQuery]]:
    buckets: Dict[str, List[IRSwapQuery]] = {}
    for q in queries:
        curve_name = q.curve
        if not curve_name:
            raise ValueError("Each IRSwapQuery must specify .curve for IRSwapsTB.")
        buckets.setdefault(curve_name, []).append(q)
    return buckets


def _build_row_for_query(
    curve: _IRSwapGenericCurve,
    q: IRSwapQuery,
    ref_dt: DateLike,
    date_col: str,
) -> Tuple[DateLike, str, float]:
    ss_map = IRSwapStructureFunctionMap(curve=curve)  # structure → package
    pkg, rw = ss_map.apply(
        tenor=q.tenor,
        effective_date=q.effective_date,
        maturity_date=q.maturity_date,
        value=q.value,
        structure=q.structure,
        is_for_timeseries=True,
        **q.structure_kwargs,
    )

    val_map = IRSwapValueFunctionMap(package=pkg, risk_weights=rw, curve=curve)
    value = val_map.apply(q.value)
    return ref_dt, q.col_name(curve.id()), float(value)


@dataclass
class _MDPConfig:
    source: str
    force_refresh_fixings: bool
    config: dict


class IRSwapsTB(ZODBCacheMixin):
    _CACHE_ATTR_BASE = "_irswaps_tb_cache"
    _DEFAULT_PRICING_MESSAGE = "PRICING IRSWAPS."
    _CACHE_VERSION = "v2"

    def __init__(
        self,
        mdp: IRSwapsMDP,
        *,
        date_col: str = "Date",
        cache_stem: Optional[str] = None,
        force_refresh: bool = False,
        use_btree: bool = True,
        show_tqdm: bool = True,
        logger: Optional[logging.Logger] = None,
    ):
        super().__init__(use_btree=use_btree, force_refresh=force_refresh)

        self.mdp = mdp
        self._date_col = date_col
        self._show_tqdm = show_tqdm
        self._logger = logger or logging.getLogger(_LOGGER_NAME)

        # stem = cache_stem or f"IRSwapsTB_{mdp.source}"
        # self._cache_path = self.default_cache_path(stem=stem)
        stem = cache_stem or f"IRSwapsTB_{self._CACHE_VERSION}_{mdp.source}"
        self._cache_path = self.default_cache_path(stem=stem)
        self._cache_attr = f"{self._CACHE_ATTR_BASE}_{self._CACHE_VERSION}"

        # mapping cache: key=(iso_date, curve_name, query_key) -> (date, col, val)
        self.zodb_open_cache(cache_attr=self._cache_attr, path=self._cache_path)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self):
        if hasattr(self, self._CACHE_ATTR):
            self._logger.debug(f"Closing ZODB connection for cache: {self._CACHE_ATTR}")
            self.close_zodb()

    def _cache_key(self, d: DateLike, curve_name: str, q: IRSwapQuery) -> str:
        ns = _dt_to_epoch_ns(d)
        qh = _query_fingerprint(q)
        return f"{self._CACHE_VERSION}|{curve_name}|{ns}|{qh}"

    def get_timeseries(
        self,
        start: DateLike,
        end: DateLike,
        queries: List[IRSwapQuery | List[IRSwapQuery] | IRSwapQueryWrapper],
        *,
        n_jobs: Optional[int] = 1,
        ignore_cache: Optional[bool] = False,
        freq: Optional[str] = None,
        timestamps: Optional[List[datetime.datetime]] = None,
    ) -> pd.DataFrame:
        if timestamps is not None and len(timestamps) > 0:
            ref_points = sorted(pd.to_datetime(pd.Index(timestamps)).to_pydatetime().tolist())
        else:
            is_intraday = isinstance(start, datetime.datetime) and isinstance(end, datetime.datetime) and (freq is not None)
            if is_intraday:
                assert start.tzinfo is not None, "Must pass in timezone-aware datetime.datetime"
                eff_freq = freq or "1T"  # default to 1-minute resolution
                rng = pd.date_range(start=start, end=end, freq=eff_freq, tz=start.tzinfo)
                ref_points = rng.to_pydatetime().tolist()
            else:
                ref_points = pd.bdate_range(start, end).date.tolist()

        flat = _flatten_queries(queries)
        by_curve = _group_queries_by_curve(flat)

        to_fetch: DefaultDict[str, set] = defaultdict(set)
        cached_rows: List[Tuple[DateLike, str, float]] = []

        cache_map = getattr(self, self._cache_attr)

        for d in ref_points:
            for curve_name, qs in by_curve.items():
                for q in qs:
                    k = self._cache_key(d, curve_name, q)
                    if (k in cache_map) and not ignore_cache:
                        cached_rows.append(cache_map[k])
                    else:
                        to_fetch[curve_name].add(d)

        new_rows_with_q: List[Tuple[Tuple[DateLike, str, float], IRSwapQuery, str, datetime.date]] = []
        for curve_name, missing_points in to_fetch.items():
            if not missing_points:
                continue

            built_map: Dict[Union[datetime.date, datetime.datetime], _IRSwapGenericCurve] = self.mdp.bulk_get_data(
                {
                    "curve_name": curve_name,
                    "timestamps": sorted(missing_points),
                    "ignore_cache": ignore_cache,
                    "n_jobs": n_jobs,
                }
            )

            qs = by_curve[curve_name]
            total_tasks = len(missing_points) * len(qs)
            pbar_disable = not self._show_tqdm
            with tqdm(total=total_tasks, disable=pbar_disable, desc=f"PRICING {curve_name} IRSWAPS...", leave=True) as pbar:
                tasks: List[Tuple[datetime.datetime | datetime.date, IRSwapQuery, _IRSwapGenericCurve]] = []
                for d in sorted(missing_points):
                    curve = built_map.get(d)
                    if curve is None:
                        self._logger.warning(f"No curve returned for curve='{curve_name}' on date='{d}'.")
                        pbar.update(len(qs))
                        continue
                    for q in qs:
                        tasks.append((d, q, curve))

                if tasks:
                    if (n_jobs or 1) > 1:
                        max_workers = int(n_jobs) if n_jobs and n_jobs > 1 else None
                        with ThreadPoolExecutor(max_workers=max_workers) as ex:
                            fut_map = {ex.submit(_build_row_for_query, curve, q, d, self._date_col): (q, d) for (d, q, curve) in tasks}
                            for fut in as_completed(fut_map):
                                q, d = fut_map[fut]
                                try:
                                    row = fut.result()
                                    new_rows_with_q.append((row, q, curve_name, d))
                                except Exception as e:
                                    self._logger.exception(f"Pricing failed for curve='{curve_name}', date='{d}', query='{q}'. Error: {e}")
                                finally:
                                    pbar.update(1)
                    else:
                        for d, q, curve in tasks:
                            try:
                                row = _build_row_for_query(curve, q, d, self._date_col)
                                new_rows_with_q.append((row, q, curve_name, d))
                            except Exception as e:
                                self._logger.exception(f"Pricing failed for curve='{curve_name}', date='{d}', query='{q}'. Error: {e}")
                            finally:
                                pbar.update(1)

        with self.batched():
            mapping = getattr(self, self._cache_attr)
            for row, q, curve_name, d in new_rows_with_q:
                mapping[self._cache_key(d, curve_name, q)] = row

        all_rows = cached_rows + [r for (r, _q, _cn, _d) in new_rows_with_q]
        if not all_rows:
            return pd.DataFrame(columns=[self._date_col])

        df = pd.DataFrame(all_rows, columns=[self._date_col, "_col", "_val"])
        out = df.pivot_table(index=self._date_col, columns="_col", values="_val", aggfunc="last").sort_index()
        out = out.reset_index()
        out.index.name = None
        out.columns.name = None
        out = out.set_index(self._date_col)

        return out
