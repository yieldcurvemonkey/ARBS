import datetime
import logging
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple, Union, DefaultDict
from collections import defaultdict

import pandas as pd

from Caching.ZODBCacheMixin import ZODBCacheMixin
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from Query.IRSwaps._IRSwapGenericCurve import _IRSwapGenericCurve
from Query.IRSwaps.IRSwapQuery import IRSwapQuery, IRSwapQueryWrapper
from Query.IRSwaps.IRSwapStructure import IRSwapStructureFunctionMap
from Query.IRSwaps.IRSwapValue import IRSwapValueFunctionMap

# -----------------------------------------------------------------------------
# Types & module‑level constants
# -----------------------------------------------------------------------------
DateLike = Union[datetime.date, datetime.datetime]
_LOGGER_NAME = "IRSwapsTB"


# -----------------------------------------------------------------------------
# Helpers (unchanged semantics)
# -----------------------------------------------------------------------------

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
    """Evaluate a single query on a provided curve at a reference timestamp.

    Returns (date_or_datetime, column_name, value).
    """
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


# -----------------------------------------------------------------------------
# Main TB class
# -----------------------------------------------------------------------------

@dataclass
class _MDPConfig:
    source: str
    force_refresh_fixings: bool
    config: dict


class IRSwapsTB(ZODBCacheMixin):
    """Timeseries builder for IR Swaps using an MDP (market data provider).

    This refactor **delegates all curve building** to `IRSwapsMDP.bulk_get_data`
    to avoid per‑timestamp calls that led to excessive contention and ZODB cache
    write conflicts when pricing in parallel. We keep ZODB writes **only** in the
    parent process and commit them via `self.batched()` to remain concurrency‑safe.
    """

    _CACHE_ATTR = "_irswaps_tb_cache"
    _DEFAULT_PRICING_MESSAGE = "PRICING IRSWAPS."

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

        stem = cache_stem or f"IRSwapsTB_{mdp.source}"
        self._cache_path = self.default_cache_path(stem=stem)

        # mapping cache: key=(iso_date, curve_name, query_key) -> (date, col, val)
        self.zodb_open_cache(cache_attr=self._CACHE_ATTR, path=self._cache_path)

    # ------------------------------------------------------------------
    # ZODB lifecycle
    # ------------------------------------------------------------------
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self):
        if hasattr(self, self._CACHE_ATTR):
            self._logger.debug(f"Closing ZODB connection for cache: {self._CACHE_ATTR}")
            self.close_zodb()

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------
    def _cache_key(self, d: datetime.date | datetime.datetime, curve_name: str, q: IRSwapQuery) -> tuple:
        iso = d.isoformat() if not isinstance(d, datetime.datetime) else d.replace(tzinfo=None).isoformat()
        return (iso, curve_name, _query_to_key(q))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def get_timeseries(
        self,
        start: DateLike,
        end: DateLike,
        queries: List[IRSwapQuery | List[IRSwapQuery] | IRSwapQueryWrapper],
        *,
        n_jobs: Optional[int] = 1,
        use_bdays: Optional[bool] = True,
        tz: Optional[str] = None,
        ignore_cache: Optional[bool] = False,
    ) -> pd.DataFrame:
        """Build a wide DataFrame of requested series.

        Concurrency model:
          • Curves are fetched *per curve* using `mdp.bulk_get_data` (single‑threaded here).
            Any parallelism for curve construction happens **inside** the MDP, where
            caches are properly guarded.
          • Pricing of queries is CPU‑light compared to curve builds; to keep things
            cache‑safe we do it in the parent process without ZODB access in workers.
        """
        start_d = start.date() if isinstance(start, datetime.datetime) else start
        end_d = end.date() if isinstance(end, datetime.datetime) else end

        dates: List[datetime.date]
        if use_bdays:
            dates = pd.bdate_range(start_d, end_d).date.tolist()
        else:
            dates = list(pd.date_range(start_d, end_d).date)

        flat = _flatten_queries(queries)
        by_curve = _group_queries_by_curve(flat)

        # Determine what we already have in the TB cache
        to_fetch: DefaultDict[str, set[datetime.date]] = defaultdict(set)
        cached_rows: List[Tuple[DateLike, str, float]] = []
        for d in dates:
            for curve_name, qs in by_curve.items():
                for q in qs:
                    k = self._cache_key(d, curve_name, q)
                    if (k in getattr(self, self._CACHE_ATTR)) and not ignore_cache:
                        cached_rows.append(getattr(self, self._CACHE_ATTR)[k])
                    else:
                        to_fetch[curve_name].add(d)

        new_rows_with_q: List[Tuple[Tuple[DateLike, str, float], IRSwapQuery, str, datetime.date]] = []

        # Fetch missing curves curve‑by‑curve using bulk_get_data (safe for caches)
        for curve_name, missing_dates in to_fetch.items():
            if not missing_dates:
                continue

            # Delegate curve construction to MDP (which handles its own caching/parallelism)
            built_map: Dict[Union[datetime.date, datetime.datetime], _IRSwapGenericCurve] = self.mdp.bulk_get_data(
                {
                    "curve_name": curve_name,
                    "timestamps": sorted(missing_dates),
                }
            )

            # Price queries against each built curve. No cache writes here.
            qs = by_curve[curve_name]
            for d in sorted(missing_dates):
                curve = built_map.get(d)
                if curve is None:
                    self._logger.warning(f"No curve returned for curve='{curve_name}' on date='{d}'.")
                    continue
                for q in qs:
                    row = _build_row_for_query(curve, q, d, self._date_col)
                    new_rows_with_q.append((row, q, curve_name, d))

        # Persist newly computed rows in one atomic ZODB transaction
        with self.batched():
            mapping = getattr(self, self._CACHE_ATTR)
            for (row, q, curve_name, d) in new_rows_with_q:
                mapping[self._cache_key(d, curve_name, q)] = row

        # Combine cached + new and pivot to a wide frame
        all_rows = cached_rows + [r for (r, _q, _cn, _d) in new_rows_with_q]
        if not all_rows:
            return pd.DataFrame(columns=[self._date_col])

        df = pd.DataFrame(all_rows, columns=[self._date_col, "_col", "_val"])
        out = df.pivot_table(index=self._date_col, columns="_col", values="_val", aggfunc="last").sort_index()
        out = out.reset_index()

        if tz:
            # If index contains datetimes, localize; dates are left as‑is
            if pd.api.types.is_datetime64_any_dtype(out[self._date_col]):
                out[self._date_col] = pd.to_datetime(out[self._date_col], utc=True).dt.tz_convert(tz)

        return out
