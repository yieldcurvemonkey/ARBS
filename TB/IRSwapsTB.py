# core/TimeseriesBuilding/IRSwapsTB.py

import datetime
import logging
from dataclasses import dataclass
from functools import partial
from typing import Dict, Iterable, List, Optional, Tuple, Union

import pandas as pd
import tqdm
from joblib import Parallel, delayed

from Caching.ZODBCacheMixin import ZODBCacheMixin
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from Query.IRSwaps._IRSwapGenericCurve import _IRSwapGenericCurve
from Query.IRSwaps.IRSwapQuery import IRSwapQuery, IRSwapQueryWrapper
from Query.IRSwaps.IRSwapStructure import IRSwapStructureFunctionMap
from Query.IRSwaps.IRSwapValue import IRSwapValueFunctionMap

DateLike = Union[datetime.date, datetime.datetime]
_LOGGER_NAME = "IRSwapsTB"


def _query_to_key(q: IRSwapQuery) -> tuple:
    """
    Stable, hashable identity for a single query (copied from your prior usage).
    """
    tenor = str(q.tenor) if q.tenor is not None else None
    eff = q.effective_date.isoformat() if q.effective_date else None
    mat = q.maturity_date.isoformat() if q.maturity_date else None
    val = tuple(q.value) if isinstance(q.value, list) else q.value
    struct = q.structure.name
    kwargs = tuple(sorted(q.structure_kwargs.items()))
    return (tenor, eff, mat, val, struct, kwargs, q.name, q.risk_weight)


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
    """
    We let each IRSwapQuery carry which curve it belongs to (IRSwapsTB is backend agnostic).
    If your IRSwapQuery doesn’t carry a curve id, you can infer it externally and attach before calling.
    """
    buckets: Dict[str, List[IRSwapQuery]] = {}
    for q in queries:
        curve_name = q.curve  # expect IRSwapQuery has this; if not, add where you construct queries
        if not curve_name:
            raise ValueError("Each IRSwapQuery must specify .curve_name for IRSwapsTB.")
        buckets.setdefault(curve_name, []).append(q)
    return buckets


@dataclass
class _MDPConfig:
    source: str
    force_refresh_fixings: bool
    config: dict


def _build_row_for_query(
    curve: _IRSwapGenericCurve,
    q: IRSwapQuery,
    ref_dt: DateLike,
    date_col: str,
) -> Tuple[DateLike, str, float]:
    """
    Evaluate one query on one curve. This stays fully generic using your FunctionMaps.
    """
    # package & weights (structure) – works with either QL or RL curve implementations
    ss_map = IRSwapStructureFunctionMap(curve=curve)  # generic mapping over structures (outright/curve/fly/spread)
    is_for_ts = True  # signal lighter path where allowed
    pkg, rw = ss_map.apply(
        tenor=q.tenor,
        effective_date=q.effective_date,
        maturity_date=q.maturity_date,
        value=q.value,
        structure=q.structure,
        is_for_timeseries=is_for_ts,
        **q.structure_kwargs,
    )  # :contentReference[oaicite:0]{index=0}

    # value mapping – RATE / NPV / PV01 / DV01 / carry/roll, etc.
    val_map = IRSwapValueFunctionMap(package=pkg, risk_weights=rw, curve=curve)
    value = val_map.apply(q.value)  # returns a scalar for the requested IRSwapValue(s)
    return ref_dt, q.col_name(curve.id()), float(value)  # col_name can optionally use curve context  :contentReference[oaicite:1]{index=1}


def _worker_for_date(
    mdp_cfg: _MDPConfig,
    ref_dt: DateLike,
    queries_by_curve: Dict[str, List[IRSwapQuery]],
    date_col: str,
) -> List[Tuple[DateLike, str, float]]:
    logger = logging.getLogger(_LOGGER_NAME)
    mdp = IRSwapsMDP(mdp_cfg.source, force_refresh_fixings=mdp_cfg.force_refresh_fixings, **mdp_cfg.config)

    rows: List[Tuple[DateLike, str, float]] = []
    for curve_name, qs in queries_by_curve.items():
        try:
            curve = mdp.get_data({"curve_name": curve_name, "timestamp": ref_dt})
            if curve is None:
                logger.warning(f"No curve returned for curve='{curve_name}' on date='{ref_dt}'.")
                continue
            for q in qs:
                try:
                    rows.append(_build_row_for_query(curve, q, ref_dt, date_col))
                except Exception as e:
                    logger.exception(
                        f"Failed evaluating query for curve='{curve_name}' on date='{ref_dt}'. " f"Query={q}",
                        exc_info=e,
                    )
        except Exception as e:
            logger.exception(
                f"Worker failed for curve='{curve_name}' on date='{ref_dt}'.",
                exc_info=e,
            )

    return rows


class IRSwapsTB(ZODBCacheMixin):
    """
    Thin timeseries builder that is:
      • backend-agnostic (only uses IRSwapMDP + generic curve protocol),
      • multiprocessing across dates,
      • ZODB-cached at (date, curve, query_key) granularity.
    """

    _CACHE_ATTR = "_irswaps_tb_cache"
    _DEFAULT_PRICING_MESSAGE = "PRICING IRSWAPS..."

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
        self.zodb_open_cache(cache_attr=self._CACHE_ATTR, path=self._cache_path)

    def get_timeseries(
        self,
        start: DateLike,
        end: DateLike,
        queries: List[IRSwapQuery | List[IRSwapQuery] | IRSwapQueryWrapper],
        *,
        n_jobs: int = 4,
        use_bdays: bool = True,
        tz: Optional[str] = None,
        ignore_cache: bool = False,
    ) -> pd.DataFrame:

        start_d = start.date() if isinstance(start, datetime.datetime) else start
        end_d = end.date() if isinstance(end, datetime.datetime) else end

        if use_bdays:
            dates: List[datetime.date] = pd.bdate_range(start_d, end_d).date.tolist()
        else:
            dates = list(pd.date_range(start_d, end_d).date)

        # flatten & bucket queries by curve so each worker can fetch each curve once
        flat = _flatten_queries(queries)
        by_curve = _group_queries_by_curve(flat)

        # prepare work: only run tasks that aren't already cached
        to_compute: Dict[datetime.date, Dict[str, List[IRSwapQuery]]] = {}
        cached_rows: List[Tuple[DateLike, str, float]] = []
        for d in dates:
            missing_for_date: Dict[str, List[IRSwapQuery]] = {}
            for curve_name, qs in by_curve.items():
                for q in qs:
                    key = self._cache_key(d, curve_name, q)
                    if (key in getattr(self, self._CACHE_ATTR)) and not ignore_cache:
                        cached_rows.append(getattr(self, self._CACHE_ATTR)[key])
                    else:
                        missing_for_date.setdefault(curve_name, []).append(q)
            if missing_for_date:
                to_compute[d] = missing_for_date

        # parallel compute per-date (multiprocessing / loky)
        results: List[List[Tuple[DateLike, str, float]]] = []
        if to_compute:
            mdp_cfg = _MDPConfig(self.mdp.source, getattr(self.mdp, "force_refresh_fixings", False), dict(self.mdp.config))
            tasks = list(to_compute.items())
            tasks_iter = tqdm.tqdm(tasks, desc=self._DEFAULT_PRICING_MESSAGE) if self._show_tqdm else tasks

            try:
                results = Parallel(n_jobs=n_jobs, backend="loky")(delayed(_worker_for_date)(mdp_cfg, d, curve_qs, self._date_col) for d, curve_qs in tasks_iter)
            except Exception as e:
                self._logger.exception("Parallel execution failed in IRSwapsTB.get_timeseries.", exc_info=e)  # <-- NEW
                results = []

        # persist newly computed rows
        new_rows = [r for chunk in results for r in chunk]
        if new_rows:
            try:
                with self.batched():
                    for row in new_rows:
                        d, col, val = row
                        curve_name = self._extract_curve_from_col(col, by_curve.keys())  # best-effort (optional)
                        if not curve_name:
                            self._logger.debug(f"Could not infer curve from column name '{col}'. Skipping cache write.")  # <-- NEW
                            continue
                        for q in by_curve.get(curve_name, []):
                            if q.col_name(curve_name) == col:
                                key = self._cache_key(d, curve_name, q)
                                getattr(self, self._CACHE_ATTR)[key] = row
                                break
            except Exception as e:
                self._logger.exception("Failed while writing results to ZODB cache.", exc_info=e)  # <-- NEW

        all_rows = cached_rows + new_rows
        if not all_rows:
            self._logger.error("IRSwapsTB.get_timeseries produced no rows (both cache and compute empty).")  # <-- NEW
            return pd.DataFrame([], index=pd.DatetimeIndex([], name=self._date_col))

        # assemble DataFrame
        rows_df = pd.DataFrame(all_rows, columns=[self._date_col, "col", "val"]).drop_duplicates(subset=[self._date_col, "col"], keep="last")
        df = rows_df.pivot(index=self._date_col, columns="col", values="val").sort_index()
        df.columns.name = None

        if tz:
            try:
                df.index = pd.DatetimeIndex(pd.to_datetime(df.index)).tz_localize("UTC").tz_convert(tz)
            except Exception as e:
                self._logger.error(f"Timezone conversion to '{tz}' failed.", exc_info=e)  # <-- NEW

        return df

    def _cache_key(self, d: datetime.date, curve_name: str, q: IRSwapQuery) -> Tuple[str, str, tuple]:
        return (datetime.datetime.combine(d, datetime.time()).isoformat(timespec="seconds"), curve_name, _query_to_key(q))

    @staticmethod
    def _extract_curve_from_col(col: str, curve_names: Iterable[str]) -> Optional[str]:
        # Optional: if your IRSwapQuery.col_name embeds curve id; adjust logic as needed.
        for c in curve_names:
            if c in col:
                return c
        return None
