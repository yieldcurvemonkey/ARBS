import datetime
import hashlib
import json
import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import DefaultDict, Dict, Iterable, List, Optional, Tuple, Union

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
from Query.IRSwaps.IRSwapValue import IRSwapValue
from Query.Base.query_resolution import resolve_query
from TB.BaseTimeseriesTB import BaseTimeseriesTB
from TB.utils import DateLike, _canonicalize_value, _dt_to_epoch_ns
from utils.ql_utils import datetime_to_ql_date
from BT.misc import ql_cal_date_range

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
    q_eff = resolve_query(q, timestamp=ref_dt, pricer_or_curve=curve)
    if getattr(q, "name", None):
        # Explicit labels should be preserved verbatim so callers can disambiguate queries.
        col_name = str(q.name)
    else:
        col_name = q_eff.col_name(curve.id())
        tenor_txt = str(getattr(q, "tenor", "") or "")
        if ("CT" in tenor_txt) or ("9128" in tenor_txt):
            col_name = q.col_name()
    pkg, rw = q_eff.resolve_package(pricer_or_curve=curve, is_for_timeseries=True)
    val_map = q_eff.build_value_map(pricer_or_curve=curve, package=pkg, risk_weights=rw)
    value = val_map.apply(value=q_eff.value, **q.value_kwargs)
    return ref_dt, col_name, float(value)


def _build_rows_for_chunk(
    chunk: List[Tuple[DateLike, IRSwapQuery, _IRSwapGenericCurve]],
    date_col: str,
) -> Tuple[
    List[Tuple[Tuple[DateLike, str, float], IRSwapQuery, DateLike]],
    List[Tuple[IRSwapQuery, DateLike, Exception]],
]:
    rows: List[Tuple[Tuple[DateLike, str, float], IRSwapQuery, DateLike]] = []
    errors: List[Tuple[IRSwapQuery, DateLike, Exception]] = []
    for d, q, curve in chunk:
        try:
            row = _build_row_for_query(curve, q, d, date_col)
            rows.append((row, q, d))
        except Exception as e:
            errors.append((q, d, e))
    return rows, errors


def _is_today(d: DateLike) -> bool:
    if d == "live":
        return True
    if isinstance(d, datetime.datetime):
        tz = d.tzinfo
        if tz is None:
            return d.date() == datetime.date.today()
        return d.date() == datetime.datetime.now(tz).date()
    elif isinstance(d, datetime.date):
        return d == datetime.date.today()
    return False


class IRSwapsTB(ZODBCacheMixin, BaseTimeseriesTB):
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
        ZODBCacheMixin.__init__(
            self,
            use_btree=use_btree,
            force_refresh=force_refresh,
            mdp=mdp,
            date_col=date_col,
            show_tqdm=show_tqdm,
        )

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
        if hasattr(self, self._cache_attr):
            self._logger.debug(f"Closing ZODB connection for cache: {self._cache_attr}")
            self.close_zodb()

    def _cache_key(self, d: DateLike, curve_name: str, q: IRSwapQuery) -> str:
        ns = _dt_to_epoch_ns(d)
        qh = _query_fingerprint(q)
        return f"{self._CACHE_VERSION}|{curve_name}|{ns}|{qh}"

    def _flatten_queries(
        self,
        queries: List[IRSwapQuery | List[IRSwapQuery] | IRSwapQueryWrapper],
    ) -> List[IRSwapQuery]:
        return _flatten_queries(queries)

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
        has_timestamps = timestamps is not None and len(timestamps) > 0
        is_intraday = (not has_timestamps) and isinstance(start, datetime.datetime) and isinstance(end, datetime.datetime) and (freq is not None)
        if is_intraday:
            assert start.tzinfo is not None, "Must pass in timezone-aware datetime.datetime"
        eff_freq = (freq or "1T") if is_intraday else freq
        ref_points = self._build_reference_points(start=start, end=end, freq=eff_freq, timestamps=timestamps)

        flat = self._flatten_queries(queries)
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
                    if _is_today(d):
                        to_fetch[curve_name].add(d)
                        continue

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
            worker_count = int(n_jobs) if n_jobs and n_jobs > 1 else 1
            with tqdm(
                total=total_tasks,
                disable=pbar_disable,
                desc=f"PRICING {curve_name} IRSWAPS [workers={worker_count}]...",
                leave=True,
            ) as pbar:
                tasks: List[Tuple[datetime.datetime | datetime.date, IRSwapQuery, _IRSwapGenericCurve]] = []
                for d in sorted(missing_points):
                    curve = built_map.get(d)
                    if curve is None and d == datetime.date.today():
                        curve = built_map.get("live")
                    if curve is None:
                        self._logger.warning(f"No curve returned for curve='{curve_name}' on date='{d}'.")
                        pbar.update(len(qs))
                        continue
                    for q in qs:
                        tasks.append((d, q, curve))

                if tasks:
                    if (n_jobs or 1) > 1:
                        max_workers = int(n_jobs) if n_jobs and n_jobs > 1 else None
                        mw = int(max_workers or 1)
                        chunk_size = max(16, len(tasks) // max(1, mw * 4))
                        task_chunks: List[List[Tuple[datetime.datetime | datetime.date, IRSwapQuery, _IRSwapGenericCurve]]] = [
                            tasks[i : i + chunk_size]
                            for i in range(0, len(tasks), chunk_size)
                        ]
                        with ThreadPoolExecutor(max_workers=max_workers) as ex:
                            fut_map = {
                                ex.submit(_build_rows_for_chunk, chunk, self._date_col): chunk
                                for chunk in task_chunks
                            }
                            for fut in as_completed(fut_map):
                                chunk = fut_map[fut]
                                try:
                                    rows, errs = fut.result()
                                    for row, q, d in rows:
                                        new_rows_with_q.append((row, q, curve_name, d))
                                    for q, d, e in errs:
                                        self._logger.exception(
                                            f"Pricing failed for curve='{curve_name}', date='{d}', query='{q}'. Error: {e}"
                                        )
                                finally:
                                    pbar.update(len(chunk))
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
                if _is_today(d):
                    continue
                mapping[self._cache_key(d, curve_name, q)] = row

        all_rows = cached_rows + [r for (r, _q, _cn, _d) in new_rows_with_q]
        if not all_rows:
            return pd.DataFrame(columns=[self._date_col])

        return self._rows_to_frame(all_rows)

    def sfr_cvx_adj(
        self,
        items: list[str],
        start: DateLike,
        end: DateLike,
        *,
        ignore_cache: bool = False,
        use_globex: bool = False,
    ) -> pd.DataFrame:
        import rateslib as rl

        from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils.stir_curve_building_utils import (
            build_rl_stirf,
            get_barchart_timeseries,
            get_short_end_curve_tickers,
        )

        curve: str = "USD-SOFR-1D"
        _date_col = getattr(self, "_date_col", "date")
        mapping = getattr(self, self._cache_attr)
        leg_prefix = "/SR3" if use_globex else "SFR"

        _IMM_PAT = re.compile(r"^[FGHJKMNQUVXZ]\d{2}$")
        _CM_PAT = re.compile(r"^SFR(\d{1,2})$")
        _BUNDLE_PAT = re.compile(r"^BUNDLE(\d+)$")

        PACK_MAP = {
            "WHITES": (1, 4),
            "REDS": (5, 8),
            "GREENS": (9, 12),
            "BLUES": (13, 16),
            "GOLDS": (17, 20),
            "SILVERS": (21, 24),
        }

        def _is_imm(x: str) -> bool:
            return bool(_IMM_PAT.match(x))

        def _cm_rank(x: str) -> Optional[int]:
            m = _CM_PAT.match(x)
            return int(m.group(1)) if m else None

        def _pack_span(x: str) -> Optional[tuple[int, int]]:
            X = x.upper()
            if X in PACK_MAP:
                return PACK_MAP[X]
            m = _BUNDLE_PAT.match(X)
            if m:
                b = int(m.group(1))
                start_rank = 1 + 4 * (b - 1)
                return (start_rank, start_rank + 16 - 1)
            return None

        def _structure_tag(label: str) -> str:
            if _is_imm(label) or _cm_rank(label):
                return "OUTRIGHT"
            if label.upper() in PACK_MAP:
                return "PACKS"
            if _BUNDLE_PAT.match(label.upper()):
                return "BUNDLES"
            return "OUTRIGHT"

        def _col_name(label: str) -> str:
            return f"{curve} {label} {_structure_tag(label)} CVX_ADJ"

        def _front_imm_code(d: datetime.date) -> str:
            sym = next(
                s for s in get_short_end_curve_tickers(as_of=d, first_n_sr1=0, first_n_sr3=1, use_globex=use_globex) if ("/SR3" in s if use_globex else "SFR" in s)
            )
            return sym.replace(leg_prefix, "")

        def _imm_code_from_date_rank(d: datetime.date, n: int) -> str:
            front = _front_imm_code(d)
            imm_dt = rl.get_imm(code=front)
            for _ in range(max(0, n - 1)):
                imm_dt = rl.next_imm(imm_dt)
            letter = {3: "H", 6: "M", 9: "U", 12: "Z"}[imm_dt.month]
            return f"{letter}{imm_dt.year % 100:02d}"

        def _span_ranks(label: str) -> Optional[list[int]]:
            sp = _pack_span(label)
            if not sp:
                return None
            a, b = sp
            return list(range(a, b + 1))

        def _ranks_for_label(label: str) -> Optional[list[int]]:
            r = _cm_rank(label)
            if r:
                return [r]
            sp = _span_ranks(label)
            if sp:
                return sp
            return None  # IMM handled separately

        if not items:
            return pd.DataFrame()

        start_ts = pd.to_datetime(start).normalize()
        end_ts = pd.to_datetime(end).normalize()
        eval_index = ql_cal_date_range(ql.UnitedStates(ql.UnitedStates.GovernmentBond), start_ts, end_ts)
        today_date = datetime.date.today()

        out_frames_cached: list[pd.DataFrame] = []
        need_fetch_labels: list[str] = []

        partial_missing_dates: dict[str, set[pd.Timestamp]] = {}
        missing_today_dates: dict[str, set[pd.Timestamp]] = {}
        pre_cached_rows: dict[str, list[dict]] = {}

        pending_writes: list[tuple[str, dict]] = []

        for raw_label in items:
            label = raw_label.strip().upper()
            colname = _col_name(label)

            rows: list[dict] = []
            miss_pre: set[pd.Timestamp] = set()
            miss_today: set[pd.Timestamp] = set()

            for dts in eval_index:
                ts = dts.to_pydatetime()

                if ignore_cache:
                    if dts.date() < today_date:
                        miss_pre.add(dts)
                    else:
                        miss_today.add(dts)
                    continue

                if _is_imm(label):
                    eff = rl.get_imm(code=label)
                    mat = rl.next_imm(eff)
                else:
                    ranks = _ranks_for_label(label)
                    if not ranks:
                        (miss_pre if dts.date() < today_date else miss_today).add(dts)
                        continue
                    codes = [_imm_code_from_date_rank(ts.date(), r) for r in ranks]
                    eff = rl.get_imm(code=codes[0])
                    mat = rl.next_imm(rl.get_imm(code=codes[-1]))

                q = IRSwapQuery(
                    curve=curve,
                    effective_date=eff.date(),
                    maturity_date=mat.date(),
                    structure=IRSwapStructure.OUTRIGHT,
                    structure_kwargs={"bpv": 1},
                    value=IRSwapValue.CVX_ADJ,
                )

                key = self._cache_key(ts, curve, q)
                rec = mapping.get(key)
                if rec is None:
                    (miss_pre if dts.date() < today_date else miss_today).add(dts)
                    continue

                if isinstance(rec, dict):
                    date_keys = {_date_col, _date_col.lower(), _date_col.upper(), "Date", "date", "DATE"}
                    dk = next((k for k in date_keys if k in rec), None)
                    if dk is None:
                        (miss_pre if dts.date() < today_date else miss_today).add(dts)
                        continue
                    dt_val = pd.Timestamp(rec[dk])

                    cand = [k for k in rec.keys() if k != dk]
                    if not cand:
                        (miss_pre if dts.date() < today_date else miss_today).add(dts)
                        continue
                    cvx_keys = [k for k in cand if "CVX" in k.upper()]
                    vk = cvx_keys[0] if cvx_keys else cand[0]

                    try:
                        val = float(rec[vk])
                    except Exception:
                        try:
                            val = float(getattr(rec[vk], "item", lambda: rec[vk])())
                        except Exception:
                            (miss_pre if dts.date() < today_date else miss_today).add(dts)
                            continue

                    rows.append({_date_col: dt_val, colname: val})
                else:
                    try:
                        dt_val, _orig_col, val = rec
                        dt_val = pd.Timestamp(dt_val)
                        val = float(val)
                    except Exception:
                        (miss_pre if dts.date() < today_date else miss_today).add(dts)
                        continue
                    rows.append({_date_col: dt_val, colname: val})

            if rows and not (miss_pre or miss_today):
                # fully cached
                df_cached = pd.DataFrame(rows).sort_values(_date_col, kind="mergesort").set_index(_date_col)[[colname]]
                out_frames_cached.append(df_cached)
            else:
                if rows:
                    pre_cached_rows[label] = rows
                if miss_pre:
                    partial_missing_dates[label] = miss_pre
                if miss_today:
                    missing_today_dates[label] = miss_today
                if miss_pre or miss_today:
                    need_fetch_labels.append(label)

        # nothing left to compute → avoid any barchart call
        if not need_fetch_labels:
            if not out_frames_cached:
                return pd.DataFrame()
            return pd.concat(out_frames_cached, axis=1).sort_index(kind="mergesort")

        needed_tickers: set[str] = set()
        needed_dates: list[pd.Timestamp] = []
        for label in need_fetch_labels:
            pre = partial_missing_dates.get(label, set())
            tod = missing_today_dates.get(label, set())
            miss_all = sorted(pre | tod)
            if not miss_all:
                continue

            needed_dates.extend(miss_all)
            if _is_imm(label):
                needed_tickers.add(f"{leg_prefix}{label}")
            else:
                ranks = _ranks_for_label(label) or []
                for dts in miss_all:
                    d = dts.date()
                    for r in ranks:
                        code = _imm_code_from_date_rank(d, r)
                        needed_tickers.add(f"{leg_prefix}{code}")

        if not needed_tickers:
            if not out_frames_cached:
                return pd.DataFrame()
            return pd.concat(out_frames_cached, axis=1).sort_index(kind="mergesort")

        fetch_start = min(needed_dates).to_pydatetime()
        fetch_end = max(needed_dates).to_pydatetime()

        px_df = get_barchart_timeseries(
            start=fetch_start,
            end=fetch_end,
            interval=None,  # daily settles
            tickers=sorted(needed_tickers),
            use_globex=use_globex,
        )
        if px_df.empty:
            return pd.concat(out_frames_cached, axis=1).sort_index(kind="mergesort") if out_frames_cached else pd.DataFrame()

        px_df = px_df.sort_index()
        for c in px_df.columns:
            px_df[c] = pd.to_numeric(px_df[c], errors="coerce")

        # Curve handle cache per date
        curve_by_day: dict[datetime.date, object] = {}

        out_frames: list[pd.DataFrame] = out_frames_cached[:]  # include fully cached labels

        def _get_curve_for_day(day: datetime.date):
            ch = curve_by_day.get(day)
            if ch is None:
                ch = self.mdp._get_curve(curve_name=curve, timestamp=day)
                curve_by_day[day] = ch
            return ch

        for label in tqdm(need_fetch_labels, desc="SFR CVX...", disable=not self._show_tqdm, leave=True):
            colname = _col_name(label)
            rows = list(pre_cached_rows.get(label, []))
            miss_all = partial_missing_dates.get(label, set()) | missing_today_dates.get(label, set())

            def _iter_eval_dates_for_label() -> Iterable[pd.Timestamp]:
                for dts in sorted(miss_all):
                    if dts in px_df.index:
                        yield dts

            if _is_imm(label):
                leg = f"{leg_prefix}{label}"
                if leg not in px_df.columns:
                    if rows:
                        df_i = pd.DataFrame(rows).sort_values(_date_col, kind="mergesort").set_index(_date_col)[[colname]]
                        out_frames.append(df_i)
                    continue

                eff_dt = rl.get_imm(code=label)
                mat_dt = rl.next_imm(eff_dt)
                q = IRSwapQuery(
                    curve=curve,
                    effective_date=eff_dt.date(),
                    maturity_date=mat_dt.date(),
                    structure=IRSwapStructure.OUTRIGHT,
                    structure_kwargs={"bpv": 1},
                    value=IRSwapValue.CVX_ADJ,
                )

                for dts in _iter_eval_dates_for_label():
                    try:
                        ts = pd.Timestamp(dts).to_pydatetime()
                        price = px_df.at[dts, leg]
                        if pd.isna(price):
                            continue

                        ch = _get_curve_for_day(dts.date())
                        pkg, rws = q.resolve_package(pricer_or_curve=ch, is_for_timeseries=True)
                        vmap = q.build_value_map(pricer_or_curve=ch, package=pkg, risk_weights=rws)

                        _, rl_sfr = build_rl_stirf(ticker=leg, curve_id=ch.id(), price=float(price), use_globex=use_globex)
                        cvx = float(vmap.apply(value=IRSwapValue.CVX_ADJ, **{"sfr": [rl_sfr]}))

                        record = {_date_col: pd.Timestamp(dts).to_pydatetime(), colname: cvx}
                        rows.append(record)

                        if not _is_today(ts):
                            pending_writes.append((self._cache_key(ts, curve, q), {_date_col: ts, q.col_name(curve): cvx}))
                    except Exception:
                        pass

            else:
                # CM / PACKS / BUNDLES
                ranks = _ranks_for_label(label) or []
                if not ranks:
                    continue

                q_cache: dict[str, IRSwapQuery] = {}

                for dts in _iter_eval_dates_for_label():
                    try:
                        d = pd.Timestamp(dts).date()
                        codes = [_imm_code_from_date_rank(d, r) for r in ranks]
                        legs_here = [f"{leg_prefix}{c}" for c in codes]
                        if not all((leg in px_df.columns) and pd.notna(px_df.at[dts, leg]) for leg in legs_here):
                            continue

                        anchor_code = codes[0]
                        end_code = codes[-1]
                        q_key = f"{anchor_code}->{end_code}"

                        q = q_cache.get(q_key)
                        if q is None:
                            eff_dt = rl.get_imm(code=anchor_code)
                            mat_dt = rl.next_imm(rl.get_imm(code=end_code))
                            q = IRSwapQuery(
                                curve=curve,
                                effective_date=eff_dt.date(),
                                maturity_date=mat_dt.date(),
                                structure=IRSwapStructure.OUTRIGHT,
                                structure_kwargs={"bpv": 1},
                                value=IRSwapValue.CVX_ADJ,
                            )
                            q_cache[q_key] = q

                        ch = _get_curve_for_day(d)
                        pkg, rws = q.resolve_package(pricer_or_curve=ch, is_for_timeseries=True)
                        vmap = q.build_value_map(pricer_or_curve=ch, package=pkg, risk_weights=rws)

                        rl_sfrs = []
                        for leg in legs_here:
                            price = float(px_df.at[dts, leg])
                            _, rl_sfr = build_rl_stirf(ticker=leg, curve_id=ch.id(), price=price, use_globex=use_globex)
                            rl_sfrs.append(rl_sfr)

                        cvx = float(vmap.apply(value=IRSwapValue.CVX_ADJ, **{"sfr": rl_sfrs}))
                        rows.append({_date_col: pd.Timestamp(dts).to_pydatetime(), colname: cvx})

                        ts = pd.Timestamp(dts).to_pydatetime()
                        if not _is_today(ts):
                            pending_writes.append((self._cache_key(ts, curve, q), {_date_col: ts, q.col_name(curve): cvx}))
                    except Exception:
                        pass

            if rows:
                df_i = pd.DataFrame(rows).sort_values(_date_col, kind="mergesort").drop_duplicates(subset=[_date_col], keep="last").set_index(_date_col)[[colname]]
                out_frames.append(df_i)

        if pending_writes:
            with self.batched():
                mapping = getattr(self, self._cache_attr)  # re-grab in case of ConnectionProxy refresh
                for k, rec in pending_writes:
                    mapping[k] = rec

        if not out_frames:
            return pd.DataFrame()

        return pd.concat(out_frames, axis=1).sort_index(kind="mergesort")
