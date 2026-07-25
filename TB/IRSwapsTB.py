import datetime
import hashlib
import json
import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import DefaultDict, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

import re
import pandas as pd
from tqdm import tqdm
from zoneinfo import ZoneInfo

import logging

import QuantLib as ql

# fmt: off
import Query.IRSwaps.adapter  # noqa: F401
# fmt: on

from Caching.computed_timeseries_store import ComputedTimeseriesStore
from Caching.layered_cache_mixin import LayeredCacheMixin
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
_EOD_FREQ_ZONES: Dict[str, str] = {
    "eod": "America/New_York",
    "nyc_eod": "America/New_York",
    "chi_eod": "America/Chicago",
    "ldn_eod": "Europe/London",
}

_ROLL_ADJ_VALUES = frozenset({
    IRSwapValue.ROLL_ADJ_DIFFERENCE,
    IRSwapValue.ROLL_ADJ_RATIO,
    IRSwapValue.ROLL_ADJ_CALENDAR_WEIGHT,
})

_ROLL_ADJ_METHOD_MAP = {
    IRSwapValue.ROLL_ADJ_DIFFERENCE: "difference",
    IRSwapValue.ROLL_ADJ_RATIO: "ratio",
    IRSwapValue.ROLL_ADJ_CALENDAR_WEIGHT: "calendar_weight",
}


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
    # Only include value_kwargs when non-empty to stay compatible with
    # fingerprints written before this field existed in the payload.
    if q.value_kwargs:
        payload["value_kwargs"] = _canonicalize_value(q.value_kwargs)
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
    def _value_apply_kwargs(q_eff: IRSwapQuery) -> Dict[str, object]:
        apply_kwargs = {
            key: value
            for key, value in dict(getattr(q_eff, "structure_kwargs", {}) or {}).items()
            if value is not None and key not in {"curve", "package", "risk_weights"}
        }
        for key, value in dict(getattr(q_eff, "value_kwargs", {}) or {}).items():
            if value is not None:
                apply_kwargs[key] = value
        return apply_kwargs

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
    value = val_map.apply(value=q_eff.value, **_value_apply_kwargs(q_eff))
    return ref_dt, col_name, float(value)


def _build_rows_for_chunk(
    chunk: List[Tuple[DateLike, IRSwapQuery, _IRSwapGenericCurve, object]],
    date_col: str,
) -> Tuple[
    List[Tuple[Tuple[DateLike, str, float], IRSwapQuery, object]],
    List[Tuple[IRSwapQuery, DateLike, object, Exception]],
]:
    rows: List[Tuple[Tuple[DateLike, str, float], IRSwapQuery, object]] = []
    errors: List[Tuple[IRSwapQuery, DateLike, object, Exception]] = []
    for pricing_ref_point, q, curve, request_ref_point in chunk:
        try:
            row = _build_row_for_query(curve, q, pricing_ref_point, date_col)
            rows.append((row, q, request_ref_point))
        except Exception as e:
            errors.append((q, pricing_ref_point, request_ref_point, e))
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


def _is_eod_frequency(freq: Optional[str]) -> bool:
    return str(freq or "").strip().lower() in _EOD_FREQ_ZONES


def _live_eod_history_end(freq: Optional[str]) -> datetime.date:
    zone_name = _EOD_FREQ_ZONES.get(str(freq or "").strip().lower(), "America/New_York")
    return datetime.datetime.now(ZoneInfo(zone_name)).date() - datetime.timedelta(days=1)


def _live_output_timestamp(
    *,
    start: DateLike,
    freq: Optional[str],
    historical_ref_points: Sequence[DateLike],
) -> datetime.datetime:
    zone_name = _EOD_FREQ_ZONES.get(str(freq or "").strip().lower(), "America/New_York")
    zone = ZoneInfo(zone_name)

    out_tz = None
    for ref_point in historical_ref_points:
        if isinstance(ref_point, datetime.datetime) and ref_point.tzinfo is not None and ref_point.tzinfo.utcoffset(ref_point) is not None:
            out_tz = ref_point.tzinfo
            break
    if out_tz is None and isinstance(start, datetime.datetime) and start.tzinfo is not None and start.tzinfo.utcoffset(start) is not None:
        out_tz = start.tzinfo

    now_local = datetime.datetime.now(zone)
    return now_local.astimezone(out_tz) if out_tz is not None else now_local


def _sorted_request_points(points: Iterable[object]) -> List[object]:
    non_live = [point for point in points if point != "live"]
    live = [point for point in points if point == "live"]
    return sorted(non_live) + live


def _curve_store_source_family(mdp: Optional[IRSwapsMDP]) -> Optional[str]:
    if mdp is None:
        return None
    fn = getattr(mdp, "_curve_store_source_family", None)
    if callable(fn):
        try:
            family = fn()
        except Exception:
            family = None
        if family:
            return str(family)

    source = str(getattr(mdp, "source", "")).upper()
    if source in {"BARCHART_STIRF-RL", "BARCHART_STIRF_RL"}:
        return "barchart_stirf"
    if source in {"ERIS_EOD_LIVE-RL_BASIC", "ERIS_EOD_LIVE_RL_BASIC"}:
        return "eris_eod_rl_basic"
    if source in {"ERIS_EOD_LIVE-RL_BASIC-NOJUMPS", "ERIS_EOD_LIVE_RL_BASIC-NOJUMPS"}:
        return "eris_eod_rl_basic_nojumps"
    return None


def _uses_legacy_eris_eod_decimal_store_rates(mdp: Optional[IRSwapsMDP]) -> bool:
    return _curve_store_source_family(mdp) in {
        "eris_eod_rl_basic",
        "eris_eod_rl_basic_nojumps",
    }


def _normalize_legacy_eod_cached_rows(
    *,
    mdp: Optional[IRSwapsMDP],
    curve_name: str,
    query: IRSwapQuery,
    rows: List[Tuple[DateLike, str, float]],
) -> List[Tuple[DateLike, str, float]]:
    if not rows or not _uses_legacy_eris_eod_decimal_store_rates(mdp):
        return rows
    if query.value != IRSwapValue.RATE:
        return rows
    if getattr(query, "structure", None) != IRSwapStructure.OUTRIGHT:
        return rows

    expected_col_name = query.col_name(curve_name)
    tenor_token = str(getattr(query, "tenor", "") or "").strip()
    if not tenor_token:
        return rows

    tenor_aliases = {tenor_token, tenor_token.upper(), tenor_token.lower()}
    normalized_rows: List[Tuple[DateLike, str, float]] = []
    used_legacy_alias = False
    for ref_point, column_name, value in rows:
        column_text = str(column_name)
        if column_text in tenor_aliases:
            normalized_rows.append((ref_point, expected_col_name, float(value) * 100.0))
            used_legacy_alias = True
        else:
            normalized_rows.append((ref_point, column_text, float(value)))
    return normalized_rows if used_legacy_alias else rows


def _decompose_rate_into_outright_legs(q: IRSwapQuery) -> Optional[List[Tuple[float, str]]]:
    if q.value != IRSwapValue.RATE:
        return None
    tenor_text = str(getattr(q, "tenor", "") or "").strip()
    if not tenor_text:
        return None
    slash_ct = tenor_text.count("/")
    tokens = [t.strip() for t in tenor_text.split("/") if t.strip()]
    if slash_ct == 1 and len(tokens) == 2:
        return [(-1.0, tokens[0]), (1.0, tokens[1])]
    if slash_ct == 2 and len(tokens) == 3:
        return [(-1.0, tokens[0]), (2.0, tokens[1]), (-1.0, tokens[2])]
    return None


def _parse_imm_relative_tokens(tenor: str) -> Optional[List[str]]:
    """Parse a tenor like 'IMM_1xIMM_2' into relative IMM tokens ['IMM_1', 'IMM_2'].
    Returns None if tenor doesn't use relative IMM ranks."""
    tenor_upper = (tenor or "").strip().upper()
    if "XIMM_" not in tenor_upper or not tenor_upper.startswith("IMM_"):
        return None
    tokens = [t.strip() for t in tenor_upper.split("X")]
    for t in tokens:
        if not t.startswith("IMM_"):
            return None
        suffix = t.split("IMM_", 1)[1]
        if not suffix.isdigit():
            return None
    return tokens


def _resolve_imm_tenor_date_local(token: str, *, ref_date: datetime.date) -> Optional[datetime.date]:
    """Resolve a relative IMM token (e.g. 'IMM_1') to a specific date."""
    from rateslib.scheduling import next_imm

    imm_token = str(token or "").strip().upper()
    if not imm_token.startswith("IMM_"):
        return None
    suffix = imm_token.split("IMM_", 1)[1]
    if not suffix.isdigit():
        return None
    rank = int(suffix)
    if rank <= 0:
        return None
    imm = datetime.datetime.combine(ref_date + datetime.timedelta(days=1), datetime.time())
    for _ in range(rank):
        imm = next_imm(imm)
    return imm.date() if isinstance(imm, datetime.datetime) else imm


def _detect_roll_indices(
    tokens: List[str],
    ref_dates: List[DateLike],
) -> List[Tuple[int, Tuple[Optional[datetime.date], ...], Tuple[Optional[datetime.date], ...]]]:
    """Identify indices where the resolved IMM dates change (roll points).
    Returns list of (index, old_resolved_dates, new_resolved_dates)."""
    resolved = []
    for rd in ref_dates:
        d = rd.date() if isinstance(rd, datetime.datetime) else rd
        dates = tuple(_resolve_imm_tenor_date_local(t, ref_date=d) for t in tokens)
        resolved.append(dates)

    roll_points = []
    for i in range(1, len(resolved)):
        if resolved[i] != resolved[i - 1]:
            if None not in resolved[i] and None not in resolved[i - 1]:
                roll_points.append((i, resolved[i - 1], resolved[i]))
    return roll_points


def _apply_difference_adjustment(
    series: pd.Series,
    roll_gaps: List[Tuple[int, float]],
) -> pd.Series:
    """Backward additive (Panama Canal) adjustment.
    Shifts all pre-roll data by the gap (new - old) so the series is continuous.
    Latest data matches market; historical data is adjusted."""
    adjusted = series.values.copy().astype(float)
    for idx, gap in reversed(roll_gaps):
        adjusted[:idx] += gap
    return pd.Series(adjusted, index=series.index, name=series.name)


def _apply_ratio_adjustment(
    series: pd.Series,
    roll_gaps: List[Tuple[int, float]],
    raw_values: pd.Series,
) -> pd.Series:
    """Backward multiplicative adjustment.
    Scales all pre-roll data by the ratio of new/old contract at each roll."""
    adjusted = series.values.copy().astype(float)
    for idx, _gap in reversed(roll_gaps):
        old_val = raw_values.iloc[idx - 1] if idx > 0 else None
        new_val = raw_values.iloc[idx]
        if old_val is None or old_val == 0.0 or pd.isna(old_val) or pd.isna(new_val):
            continue
        ratio = new_val / old_val
        adjusted[:idx] *= ratio
    return pd.Series(adjusted, index=series.index, name=series.name)


def _apply_calendar_weight_adjustment(
    raw_series: pd.Series,
    roll_indices: List[int],
    old_rates_at_rolls: Dict[int, pd.Series],
    window: int = 5,
) -> pd.Series:
    """Calendar-weighted (perpetual) method.
    Blends old and new contracts over a roll window."""
    adjusted = raw_series.values.copy().astype(float)
    half = window // 2

    for roll_idx in roll_indices:
        old_rates = old_rates_at_rolls.get(roll_idx)
        if old_rates is None or old_rates.empty:
            continue

        blend_start = max(0, roll_idx - half)
        blend_end = min(len(adjusted), roll_idx + half + 1)

        for i in range(blend_start, blend_end):
            dt = raw_series.index[i]
            if dt not in old_rates.index:
                continue
            old_val = old_rates.loc[dt]
            new_val = adjusted[i]
            if pd.isna(old_val) or pd.isna(new_val):
                continue
            progress = (i - blend_start) / max(1, blend_end - blend_start - 1)
            adjusted[i] = (1.0 - progress) * old_val + progress * new_val

    return pd.Series(adjusted, index=raw_series.index, name=raw_series.name)


class IRSwapsTB(LayeredCacheMixin, BaseTimeseriesTB):
    _CACHE_ATTR_BASE = "_irswaps_tb_cache"
    _DEFAULT_PRICING_MESSAGE = "PRICING IRSWAPS."
    _CACHE_VERSION = "v2"
    # EOD swap rates settle quickly, but keep a small window so same-day
    # partial caches are refreshed on the next run.
    _STALE_THRESHOLD_DAYS = 2

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

        # stem = cache_stem or f"IRSwapsTB_{mdp.source}"
        # self._cache_path = self.default_cache_path(stem=stem)
        stem = cache_stem or f"IRSwapsTB_{self._CACHE_VERSION}_{mdp.source}"
        self._cache_path = self.default_cache_path(stem=stem)
        self._cache_attr = f"{self._CACHE_ATTR_BASE}_{self._CACHE_VERSION}"

        # mapping cache: key=(iso_date, curve_name, query_key) -> (date, col, val)
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

    def _cache_key(self, d: DateLike, curve_name: str, q: IRSwapQuery) -> str:
        ns = _dt_to_epoch_ns(d)
        qh = _query_fingerprint(q)
        return f"{self._CACHE_VERSION}|{curve_name}|{ns}|{qh}"

    def _flatten_queries(
        self,
        queries: List[IRSwapQuery | List[IRSwapQuery] | IRSwapQueryWrapper],
    ) -> List[IRSwapQuery]:
        return _flatten_queries(queries)

    def _ts_symbol_for_query(self, curve_name: str, q: IRSwapQuery) -> str:
        return f"IRS::{self.mdp.source}::{curve_name}::{_query_fingerprint(q)}"

    def _filter_reference_points_for_curve(
        self,
        reference_points: Iterable[DateLike],
        curve_name: str,
    ) -> List[DateLike]:
        filtered = list(dict.fromkeys(reference_points))

        filter_fn = getattr(self.mdp, "filter_reference_points_for_curve", None)
        if callable(filter_fn):
            try:
                filtered = list(filter_fn(curve_name=curve_name, reference_points=filtered))
            except TypeError:
                filtered = list(filter_fn(curve_name, filtered))
            except Exception:
                pass

        if curve_name == "USD-SOFR-1D":
            filtered = [
                ref_point
                for ref_point in filtered
                if ref_point == "live" or ql.UnitedStates(ql.UnitedStates.GovernmentBond).isBusinessDay(datetime_to_ql_date(ref_point))
            ]

        return filtered

    def _get_roll_adjusted_timeseries(
        self,
        start: DateLike,
        end: DateLike,
        queries: List[IRSwapQuery | List[IRSwapQuery] | IRSwapQueryWrapper],
        *,
        n_jobs: Optional[int] = 1,
        ignore_cache: Optional[bool] = False,
        ignore_cache_miss: Optional[bool] = False,
        freq: Optional[str] = None,
        timestamps: Optional[List[datetime.datetime]] = None,
        _prefetched_ts_rows_by_symbol: Optional[Mapping[str, Sequence[Tuple[DateLike, str, float]]]] = None,
    ) -> pd.DataFrame:
        from dataclasses import replace

        flat = self._flatten_queries(queries)
        roll_adj_infos: List[Tuple[IRSwapQuery, str]] = []
        passthrough: List[IRSwapQuery] = []

        for q in flat:
            if q.value in _ROLL_ADJ_VALUES:
                method = _ROLL_ADJ_METHOD_MAP[q.value]
                roll_adj_infos.append((q, method))
            else:
                passthrough.append(q)

        ts_kwargs = dict(
            n_jobs=n_jobs,
            ignore_cache=ignore_cache,
            ignore_cache_miss=ignore_cache_miss,
            freq=freq,
            timestamps=timestamps,
            _prefetched_ts_rows_by_symbol=_prefetched_ts_rows_by_symbol,
        )

        result_frames: List[pd.DataFrame] = []

        if passthrough:
            pass_df = self.get_timeseries(
                start=start, end=end, queries=passthrough, **ts_kwargs,
            )
            if not pass_df.empty:
                result_frames.append(pass_df)

        for orig_q, method in roll_adj_infos:
            adj_col = orig_q.col_name(orig_q.curve)

            rate_q = replace(orig_q, value=IRSwapValue.RATE, name=None, value_kwargs={})
            rate_df = self.get_timeseries(
                start=start, end=end, queries=[rate_q], **ts_kwargs,
            )

            if rate_df.empty or rate_df.shape[1] == 0:
                continue

            rate_col = rate_df.columns[0]
            raw_series = rate_df[rate_col].dropna()
            if raw_series.empty:
                continue

            tenor = orig_q.tenor
            tokens = _parse_imm_relative_tokens(tenor)
            if not tokens:
                result_frames.append(raw_series.to_frame(adj_col))
                continue

            ref_dates = list(raw_series.index)
            roll_points = _detect_roll_indices(tokens, ref_dates)

            if not roll_points:
                result_frames.append(raw_series.to_frame(adj_col))
                continue

            if method == "difference":
                roll_gaps = self._compute_roll_gaps(
                    roll_points=roll_points,
                    ref_dates=ref_dates,
                    raw_series=raw_series,
                    curve_name=orig_q.curve,
                    n_jobs=n_jobs,
                    ignore_cache_miss=ignore_cache_miss,
                    freq=freq,
                )
                adjusted = _apply_difference_adjustment(raw_series, roll_gaps)
                result_frames.append(adjusted.to_frame(adj_col))

            elif method == "ratio":
                roll_gaps = self._compute_roll_gaps(
                    roll_points=roll_points,
                    ref_dates=ref_dates,
                    raw_series=raw_series,
                    curve_name=orig_q.curve,
                    n_jobs=n_jobs,
                    ignore_cache_miss=ignore_cache_miss,
                    freq=freq,
                )
                adjusted = _apply_ratio_adjustment(raw_series, roll_gaps, raw_series)
                result_frames.append(adjusted.to_frame(adj_col))

            elif method == "calendar_weight":
                window = int((orig_q.value_kwargs or {}).get("roll_window", 5))
                old_rates_at_rolls = self._compute_old_contract_series_around_rolls(
                    roll_points=roll_points,
                    ref_dates=ref_dates,
                    curve_name=orig_q.curve,
                    window=window,
                    n_jobs=n_jobs,
                    ignore_cache_miss=ignore_cache_miss,
                    freq=freq,
                )
                roll_indices_only = [rp[0] for rp in roll_points]
                adjusted = _apply_calendar_weight_adjustment(
                    raw_series, roll_indices_only, old_rates_at_rolls, window
                )
                result_frames.append(adjusted.to_frame(adj_col))

        if not result_frames:
            return pd.DataFrame()
        return pd.concat(result_frames, axis=1).sort_index()

    def _compute_roll_gaps(
        self,
        roll_points: List[Tuple[int, Tuple, Tuple]],
        ref_dates: List[DateLike],
        raw_series: pd.Series,
        curve_name: str,
        **kwargs,
    ) -> List[Tuple[int, float]]:
        """Compute the gap (new_rate - old_rate) at each roll point."""
        gaps: List[Tuple[int, float]] = []

        for idx, old_dates, new_dates in roll_points:
            roll_date = ref_dates[idx]
            new_rate = raw_series.iloc[idx]
            if pd.isna(new_rate):
                continue

            old_effective = old_dates[0]
            old_maturity = old_dates[-1]
            try:
                old_q = IRSwapQuery(
                    curve=curve_name,
                    effective_date=old_effective,
                    maturity_date=old_maturity,
                    value=IRSwapValue.RATE,
                    structure=IRSwapStructure.OUTRIGHT,
                    structure_kwargs={"bpv": 1},
                )
                old_df = self.get_timeseries(
                    start=roll_date,
                    end=roll_date,
                    queries=[old_q],
                    n_jobs=kwargs.get("n_jobs", 1),
                    freq=kwargs.get("freq"),
                    ignore_cache_miss=kwargs.get("ignore_cache_miss", False),
                )
                if old_df.empty:
                    continue
                old_rate = float(old_df.iloc[0, 0])
                gap = float(new_rate) - old_rate
            except Exception as e:
                self._logger.debug(f"Roll gap computation failed at {roll_date}: {e}")
                continue

            gaps.append((idx, gap))

        return gaps

    def _compute_old_contract_series_around_rolls(
        self,
        roll_points: List[Tuple[int, Tuple, Tuple]],
        ref_dates: List[DateLike],
        curve_name: str,
        window: int,
        **kwargs,
    ) -> Dict[int, pd.Series]:
        """For calendar-weight method: get old contract rates around each roll window."""
        old_rates_by_roll: Dict[int, pd.Series] = {}
        half = window // 2

        for idx, old_dates, _new_dates in roll_points:
            blend_start = max(0, idx - half)
            blend_end = min(len(ref_dates), idx + half + 1)
            window_dates = ref_dates[blend_start:blend_end]

            if not window_dates:
                continue

            old_effective = old_dates[0]
            old_maturity = old_dates[-1]
            try:
                old_q = IRSwapQuery(
                    curve=curve_name,
                    effective_date=old_effective,
                    maturity_date=old_maturity,
                    value=IRSwapValue.RATE,
                    structure=IRSwapStructure.OUTRIGHT,
                    structure_kwargs={"bpv": 1},
                )
                old_df = self.get_timeseries(
                    start=window_dates[0],
                    end=window_dates[-1],
                    queries=[old_q],
                    n_jobs=kwargs.get("n_jobs", 1),
                    freq=kwargs.get("freq"),
                    ignore_cache_miss=kwargs.get("ignore_cache_miss", False),
                )
                if not old_df.empty:
                    old_rates_by_roll[idx] = old_df.iloc[:, 0]
            except Exception as e:
                self._logger.debug(f"Calendar-weight old contract failed at roll {idx}: {e}")

        return old_rates_by_roll

    def get_timeseries(
        self,
        start: DateLike,
        end: DateLike,
        queries: List[IRSwapQuery | List[IRSwapQuery] | IRSwapQueryWrapper],
        *,
        n_jobs: Optional[int] = 1,
        ignore_cache: Optional[bool] = False,
        ignore_cache_miss: Optional[bool] = False,
        freq: Optional[str] = None,
        timestamps: Optional[List[datetime.datetime]] = None,
        _prefetched_ts_rows_by_symbol: Optional[Mapping[str, Sequence[Tuple[DateLike, str, float]]]] = None,
    ) -> pd.DataFrame:
        flat_check = self._flatten_queries(queries)
        if any(q.value in _ROLL_ADJ_VALUES for q in flat_check):
            return self._get_roll_adjusted_timeseries(
                start=start,
                end=end,
                queries=queries,
                n_jobs=n_jobs,
                ignore_cache=ignore_cache,
                ignore_cache_miss=ignore_cache_miss,
                freq=freq,
                timestamps=timestamps,
                _prefetched_ts_rows_by_symbol=_prefetched_ts_rows_by_symbol,
            )

        has_timestamps = timestamps is not None and len(timestamps) > 0
        live_eod_mode = end == "live"
        live_output_index: Optional[datetime.datetime] = None
        if live_eod_mode:
            if has_timestamps:
                raise NotImplementedError("IRSwapsTB end='live' does not support explicit timestamps.")
            if not _is_eod_frequency(freq):
                raise NotImplementedError("IRSwapsTB end='live' is currently supported only for EOD frequencies.")
            start_date = start.date() if isinstance(start, datetime.datetime) else start
            historical_ref_points: List[DateLike] = []
            history_end = _live_eod_history_end(freq)
            if start_date <= history_end:
                historical_ref_points = self._build_reference_points(
                    start=start,
                    end=history_end,
                    freq=freq,
                    timestamps=None,
                )
            live_output_index = _live_output_timestamp(
                start=start,
                freq=freq,
                historical_ref_points=historical_ref_points,
            )
            ref_points = [*historical_ref_points, "live"]
            use_intraday_cache = False
        else:
            is_intraday = (not has_timestamps) and isinstance(start, datetime.datetime) and isinstance(end, datetime.datetime) and (freq is not None)
            if is_intraday:
                assert start.tzinfo is not None, "Must pass in timezone-aware datetime.datetime"
            if has_timestamps:
                # Same contract as the start/end+freq form above. A naive intraday
                # timestamp is read as ET by IRSwapsMDP but keyed as UTC by the
                # computed-timeseries store, so the two disagree by the UTC offset:
                # naive 14:30 is priced as 14:30 ET yet shares a cache key with
                # tz-aware 14:30 UTC (= 10:30 ET), four hours away. Rather than
                # pick a winner and silently serve one instant's value for the
                # other, refuse the ambiguity.
                _naive = [
                    t for t in timestamps
                    if isinstance(t, datetime.datetime) and t.tzinfo is None
                ]
                if _naive:
                    raise ValueError(
                        "IRSwapsTB.get_timeseries(timestamps=...) requires timezone-aware "
                        f"datetimes; got {len(_naive)} naive value(s), e.g. {_naive[0]!r}. "
                        "Localize them (e.g. pytz.timezone('America/New_York').localize(ts))."
                    )
            eff_freq = (freq or "1T") if is_intraday else freq
            ref_points = self._build_reference_points(start=start, end=end, freq=eff_freq, timestamps=timestamps)
            use_intraday_cache = has_timestamps or is_intraday

        flat = self._flatten_queries(queries)
        by_curve = _group_queries_by_curve(flat)
        ref_points_by_curve = {
            curve_name: self._filter_reference_points_for_curve(ref_points, curve_name)
            for curve_name in by_curve
        }

        to_fetch: DefaultDict[str, set] = defaultdict(set)
        cached_rows: List[Tuple[DateLike, str, float]] = []
        cached_row_keys: set[Tuple[DateLike, str]] = set()
        prefetched_ts_rows_by_symbol = {
            str(symbol): list(rows)
            for symbol, rows in (_prefetched_ts_rows_by_symbol or {}).items()
        }

        use_mapping_cache = not self._use_ts_cache
        cache_map = getattr(self, self._cache_attr) if use_mapping_cache else None

        today = datetime.date.today()
        _stale_cutoff = today - datetime.timedelta(days=self._STALE_THRESHOLD_DAYS)

        def _as_date(d: DateLike) -> datetime.date:
            if isinstance(d, datetime.datetime):
                return d.date()
            if isinstance(d, datetime.date):
                return d
            return d  # type: ignore[return-value]

        # Determine if the entire request is purely historical (all dates
        # before the staleness window). When true we can skip stale eviction
        # and avoid forcing ignore_cache on the MDP.
        _all_ref_dates = [
            _as_date(d)
            for curve_ref_points in ref_points_by_curve.values()
            for d in curve_ref_points
            if d != "live" and isinstance(d if not isinstance(d, datetime.datetime) else d.date(), datetime.date)
        ]
        _is_purely_historical = bool(_all_ref_dates) and max(_all_ref_dates) <= _stale_cutoff

        if self._use_ts_cache and not ignore_cache:
            # --- Batch DuckDB read: collect all symbols first, read in one query ---
            _symbols_by_curve: Dict[str, Dict[str, IRSwapQuery]] = {}
            _fallback_cols: Dict[str, str] = {}
            _cacheable_ref_by_curve: Dict[str, list] = {}
            for curve_name, qs in by_curve.items():
                curve_ref_points = ref_points_by_curve.get(curve_name, [])
                cacheable_ref_points = [rp for rp in curve_ref_points if rp != "live"]
                if not cacheable_ref_points:
                    continue
                _cacheable_ref_by_curve[curve_name] = cacheable_ref_points
                _symbols_by_curve[curve_name] = {}
                for q in qs:
                    symbol = self._ts_symbol_for_query(curve_name, q)
                    _symbols_by_curve[curve_name][symbol] = q
                    _fallback_cols[symbol] = q.col_name(curve_name)

            for curve_name, sym_q_map in _symbols_by_curve.items():
                cacheable_ref_points = _cacheable_ref_by_curve[curve_name]
                # Separate prefetched symbols from those that need a store read
                need_read_symbols = []
                for symbol, q in sym_q_map.items():
                    prefetched = prefetched_ts_rows_by_symbol.get(symbol)
                    if prefetched is not None:
                        try:
                            norm = _normalize_legacy_eod_cached_rows(mdp=self.mdp, curve_name=curve_name, query=q, rows=list(prefetched))
                        except Exception:
                            norm = []
                        cached_rows.extend(norm)
                        cached_row_keys.update((rd, rc) for rd, rc, _ in norm)
                    else:
                        need_read_symbols.append(symbol)

                if need_read_symbols and not use_intraday_cache:
                    try:
                        batch_result = self._computed_ts_store.read_many_symbols(
                            symbols=need_read_symbols,
                            reference_points=cacheable_ref_points,
                            intraday=use_intraday_cache,
                            skip_current_eod=True,
                            fallback_column_names={s: _fallback_cols.get(s) for s in need_read_symbols},
                            allow_partial=True,
                        )
                    except Exception as ex:
                        self._logger.debug("Batch TS cache read failed for curve='%s': %s", curve_name, ex)
                        batch_result = {s: [] for s in need_read_symbols}
                    for symbol in need_read_symbols:
                        q = sym_q_map[symbol]
                        rows = batch_result.get(symbol, [])
                        try:
                            rows = _normalize_legacy_eod_cached_rows(mdp=self.mdp, curve_name=curve_name, query=q, rows=rows)
                        except Exception:
                            rows = []
                        cached_rows.extend(rows)
                        cached_row_keys.update((rd, rc) for rd, rc, _ in rows)
                elif need_read_symbols:
                    for symbol in need_read_symbols:
                        q = sym_q_map[symbol]
                        try:
                            rows = self._computed_ts_store.read_rows(
                                symbol=symbol, reference_points=cacheable_ref_points,
                                intraday=use_intraday_cache, skip_current_eod=True,
                                fallback_column_name=q.col_name(curve_name),
                                allow_partial=True, skip_if_symbol_absent=False,
                            )
                        except Exception:
                            rows = []
                        try:
                            rows = _normalize_legacy_eod_cached_rows(mdp=self.mdp, curve_name=curve_name, query=q, rows=rows)
                        except Exception:
                            rows = []
                        cached_rows.extend(rows)
                        cached_row_keys.update((rd, rc) for rd, rc, _ in rows)

        # Stale eviction: skip entirely for purely historical queries.
        if not _is_purely_historical and cached_rows and not ignore_cache:
            cached_rows = [(d, c, v) for d, c, v in cached_rows if _as_date(d) <= _stale_cutoff]
            cached_row_keys = {(d, c) for d, c in cached_row_keys if _as_date(d) <= _stale_cutoff}

        # --- Synthesize multi-leg RATE queries from cached outright legs ---
        if self._use_ts_cache and not ignore_cache:
            for curve_name, qs in by_curve.items():
                curve_ref_points = ref_points_by_curve.get(curve_name, [])
                cacheable_ref_points = [rp for rp in curve_ref_points if rp != "live"]
                if not cacheable_ref_points:
                    continue

                decomposable: list = []
                for q in qs:
                    col = q.col_name(curve_name)
                    missing = [
                        d for d in cacheable_ref_points
                        if (d, col) not in cached_row_keys
                        and not _is_today(d)
                        and (_is_purely_historical or _as_date(d) <= _stale_cutoff)
                    ]
                    if not missing:
                        continue
                    components = _decompose_rate_into_outright_legs(q)
                    if components is None:
                        continue
                    decomposable.append((q, col, missing, components))

                if not decomposable:
                    continue

                tenor_to_symbol: Dict[str, str] = {}
                leg_queries: Dict[str, IRSwapQuery] = {}
                for _q, _col, _missing, components in decomposable:
                    for _w, tenor in components:
                        if tenor not in tenor_to_symbol:
                            leg_q = IRSwapQuery(curve=curve_name, tenor=tenor, value=IRSwapValue.RATE)
                            sym = self._ts_symbol_for_query(curve_name, leg_q)
                            tenor_to_symbol[tenor] = sym
                            leg_queries[sym] = leg_q

                all_missing = sorted(set(d for _, _, m, _ in decomposable for d in m))
                try:
                    leg_batch = self._computed_ts_store.read_many_symbols(
                        symbols=list(leg_queries.keys()),
                        reference_points=all_missing,
                        intraday=use_intraday_cache,
                        skip_current_eod=True,
                        fallback_column_names={s: leg_queries[s].col_name(curve_name) for s in leg_queries},
                        allow_partial=True,
                    )
                except Exception:
                    leg_batch = {}

                leg_values: Dict[str, Dict] = {}
                for sym, leg_q in leg_queries.items():
                    rows = leg_batch.get(sym, [])
                    try:
                        rows = _normalize_legacy_eod_cached_rows(mdp=self.mdp, curve_name=curve_name, query=leg_q, rows=rows)
                    except Exception:
                        pass
                    leg_values[sym] = {dt: float(val) for dt, _c, val in rows}

                synthesized = 0
                for q, col, missing, components in decomposable:
                    for d in missing:
                        vals = []
                        for weight, tenor in components:
                            dv = leg_values.get(tenor_to_symbol[tenor], {}).get(d)
                            if dv is None:
                                break
                            vals.append(weight * abs(dv))
                        else:
                            spread = sum(vals) * 100.0
                            cached_rows.append((d, col, spread))
                            cached_row_keys.add((d, col))
                            synthesized += 1
                if synthesized:
                    self._logger.debug("Synthesized %d spread values from cached outright legs for %s", synthesized, curve_name)

        for curve_name, qs in by_curve.items():
            curve_ref_points = ref_points_by_curve.get(curve_name, [])
            if not curve_ref_points:
                continue
            for d in curve_ref_points:
                for q in qs:
                    col_name = q.col_name(curve_name)
                    if (d, col_name) in cached_row_keys:
                        continue

                    if _is_today(d):
                        to_fetch[curve_name].add(d)
                        continue

                    if not _is_purely_historical:
                        _d_date = d.date() if isinstance(d, datetime.datetime) else d
                        if _d_date != "live" and isinstance(_d_date, datetime.date) and _d_date > _stale_cutoff:
                            to_fetch[curve_name].add(d)
                            continue

                    if use_mapping_cache:
                        k = self._cache_key(d, curve_name, q)
                        if (k in cache_map) and not ignore_cache:
                            row = cache_map[k]
                            cached_rows.append(row)
                            cached_row_keys.add((row[0], row[1]))
                        else:
                            to_fetch[curve_name].add(d)
                    else:
                        to_fetch[curve_name].add(d)

        new_rows_with_q: List[Tuple[Tuple[DateLike, str, float], IRSwapQuery, str, object]] = []
        for curve_name, missing_points in to_fetch.items():
            if not missing_points:
                continue

            request_points = _sorted_request_points(missing_points)

            def _is_stale_point(d: DateLike) -> bool:
                if _is_purely_historical or d == "live":
                    return False
                dd = d.date() if isinstance(d, datetime.datetime) else d
                return isinstance(dd, datetime.date) and dd > _stale_cutoff

            hist_points = [d for d in request_points if d != "live" and not _is_stale_point(d)]
            stale_points = [d for d in request_points if _is_stale_point(d)]
            has_live = "live" in request_points

            _base_request: dict = {
                "curve_name": curve_name,
                "n_jobs": n_jobs,
            }
            if ignore_cache_miss:
                _base_request["ignore_cache_miss"] = True

            built_map: Dict[Union[datetime.date, datetime.datetime], _IRSwapGenericCurve] = {}
            if hist_points:
                hist_req = {**_base_request, "timestamps": hist_points, "ignore_cache": ignore_cache}
                built_map.update(self.mdp.bulk_get_data(hist_req))
            if stale_points:
                stale_req = {**_base_request, "timestamps": stale_points, "ignore_cache": True}
                built_map.update(self.mdp.bulk_get_data(stale_req))
            if has_live:
                live_req = {**_base_request, "timestamps": ["live"], "ignore_cache": ignore_cache}
                built_map.update(self.mdp.bulk_get_data(live_req))

            qs = by_curve[curve_name]
            total_tasks = len(missing_points) * len(qs)
            pbar_disable = not self._show_tqdm
            worker_count = int(n_jobs) if n_jobs and n_jobs > 1 else 1
            with tqdm(
                total=total_tasks,
                disable=pbar_disable,
                desc=f"PRICING {curve_name} IRSWAPS [workers={worker_count}]...",
                leave=False,
            ) as pbar:
                tasks: List[Tuple[DateLike, IRSwapQuery, _IRSwapGenericCurve, object]] = []
                for d in request_points:
                    curve = built_map.get(d)
                    if curve is None and d == datetime.date.today():
                        curve = built_map.get("live")
                    if curve is None:
                        self._logger.warning(f"No curve returned for curve='{curve_name}' on date='{d}'.")
                        pbar.update(len(qs))
                        continue
                    pricing_ref_point: DateLike = live_output_index if (d == "live" and live_output_index is not None) else d
                    for q in qs:
                        tasks.append((pricing_ref_point, q, curve, d))

                if tasks:
                    if (n_jobs or 1) > 1:
                        max_workers = int(n_jobs) if n_jobs and n_jobs > 1 else None
                        mw = int(max_workers or 1)
                        chunk_size = max(16, len(tasks) // max(1, mw * 4))
                        task_chunks: List[List[Tuple[DateLike, IRSwapQuery, _IRSwapGenericCurve, object]]] = [
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
                                    for row, q, request_ref_point in rows:
                                        new_rows_with_q.append((row, q, curve_name, request_ref_point))
                                    for q, _pricing_ref_point, request_ref_point, e in errs:
                                        self._logger.exception(
                                            f"Pricing failed for curve='{curve_name}', date='{request_ref_point}', query='{q}'. Error: {e}"
                                        )
                                finally:
                                    pbar.update(len(chunk))
                    else:
                        for pricing_ref_point, q, curve, request_ref_point in tasks:
                            try:
                                row = _build_row_for_query(curve, q, pricing_ref_point, self._date_col)
                                new_rows_with_q.append((row, q, curve_name, request_ref_point))
                            except Exception as e:
                                self._logger.exception(
                                    f"Pricing failed for curve='{curve_name}', date='{request_ref_point}', query='{q}'. Error: {e}"
                                )
                            finally:
                                pbar.update(1)

        if use_mapping_cache:
            with self.batched():
                mapping = getattr(self, self._cache_attr)
                for row, q, curve_name, d in new_rows_with_q:
                    if _is_today(d):
                        continue
                    mapping[self._cache_key(d, curve_name, q)] = row

        if self._use_ts_cache and new_rows_with_q:
            grouped: Dict[str, List[Tuple[DateLike, str, float]]] = defaultdict(list)
            for (dt_like, col, val), q, curve_name, request_ref_point in new_rows_with_q:
                if _is_today(request_ref_point):
                    continue
                grouped[self._ts_symbol_for_query(curve_name, q)].append((dt_like, col, float(val)))
            if grouped:
                try:
                    self._computed_ts_store.append_many_rows(
                        rows_by_symbol=grouped, intraday=use_intraday_cache
                    )
                except Exception as ex:
                    self._logger.warning(f"[TS cache] bulk append failed: {ex}")

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

        for label in tqdm(need_fetch_labels, desc="SFR CVX...", disable=not self._show_tqdm, leave=False):
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
