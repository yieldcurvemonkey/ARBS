import datetime
import hashlib
import json
import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import DefaultDict, Dict, Iterable, List, Optional, Tuple, Union
from dataclasses import replace

import re
import pandas as pd
from tqdm import tqdm

import QuantLib as ql

# fmt: off
import Query.IRSwaps.adapter  # noqa: F401
# fmt: on

from Caching.ZODBCacheMixin import ZODBCacheMixin
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from Query.IRSwaps._IRSwapGenericCurve import _IRSwapGenericCurve
from Query.IRSwaps.IRSwapQuery import IRSwapQuery, IRSwapQueryWrapper
from Query.IRSwaps.IRSwapStructure import IRSwapStructure
from TB.utils import DateLike, _canonicalize_value, _dt_to_epoch_ns
from utils.ql_utils import datetime_to_ql_date

_LOGGER_NAME = "IRSwapsTB"


def _query_fingerprint(q: "IRSwapQuery") -> str:
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

    def _norm(tok: str) -> str:
        t = (tok or "").strip().upper().replace(" ", "")
        t = t.replace("X", "x")
        m = re.match(r"^(\d+[DWMY])(\d+[DWMY])$", t)
        if m:
            return f"{m.group(1)}x{m.group(2)}"
        return t

    if q.tenor is not None:
        structure = getattr(q, "structure", None)
        txt = (getattr(q, "tenor", "") or "") or (getattr(q, "node", "") or "") or (getattr(q, "label", "") or "")
        skw = dict(getattr(q, "structure_kwargs", {}) or {})

        x_ct = txt.count("x")
        slash_ct = txt.count("/")

        if x_ct >= 2 or slash_ct >= 2:
            structure = IRSwapStructure.FLY
            tokens = [_norm(t) for t in re.split(r"\s*/\s*", txt) if t.strip()]
            if len(tokens) != 3:
                raise ValueError(f"Expected 3 legs for FLY, got {len(tokens)} in '{txt}'")
            skw["front_tenor"], skw["belly_tenor"], skw["back_tenor"] = tokens

        elif x_ct == 1 or slash_ct == 1:
            structure = IRSwapStructure.CURVE
            tokens = [_norm(t) for t in re.split(r"\s*/\s*", txt) if t.strip()]
            if len(tokens) == 2:
                skw["front_tenor"], skw["back_tenor"] = tokens
            else:
                structure = IRSwapStructure.OUTRIGHT if structure is None else structure
                skw["tenor"] = _norm(txt)

        else:
            structure = IRSwapStructure.OUTRIGHT if structure is None else structure
            skw["tenor"] = _norm(q.tenor)

        skw.setdefault("bpv", 1)
        try:
            q_eff = replace(q, structure=structure, structure_kwargs=skw)
        except TypeError:
            q_eff = replace(q, structure=structure, structure_id=structure, structure_kwargs=skw)

        col_name = q_eff.col_name(curve.id())
        q_eff = q_eff._edited(curve)
    else:
        q_eff = q
        col_name = q_eff.col_name(curve.id())

    pkg, rw = q_eff.resolve_package(pricer_or_curve=curve, is_for_timeseries=True)
    val_map = q_eff.build_value_map(pricer_or_curve=curve, package=pkg, risk_weights=rw)
    value = val_map.apply(value=q_eff.value)
    return ref_dt, col_name, float(value)


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
                if curve_name == "USD-SOFR-1D":
                    if not ql.UnitedStates(ql.UnitedStates.GovernmentBond).isBusinessDay(datetime_to_ql_date(d)):
                        break

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
