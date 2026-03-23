import datetime
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, Any, Callable, DefaultDict, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

import pandas as pd
import numpy as np
import pytz
from tqdm.auto import tqdm as _tqdm

from MDP.IRSwapSpreads.IRSwapSpreadsMDP import IRSwapSpreadsMDP
from MDP.MarketDataProvider import MarketDataProvider
from Query.Base.BaseQuery import BaseQuery
from Query.FixedRateBonds.FixedRateBondQuery import FixedRateBondQuery
from Query.FixedRateBonds.FixedRateBondValue import FixedRateBondValue
from Query.FixedRateBonds._FixedRateBondGenericPricer import _FixedRateBondGenericPricer
from Query.IRSwaps.adapter import _looks_like_alias_or_cusip
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapStructure import IRSwapStructure
from Query.IRSwaps.IRSwapValue import IRSwapValue
from Query.IRSwaps._IRSwapGenericCurve import _IRSwapGenericCurve
from Query.Unified.UnifiedQuery import UnifiedQuery
from TB.BaseTimeseriesTB import BaseTimeseriesTB
from TB.utils import DateLike, build_reference_points

if TYPE_CHECKING:
    from TB.FixedRateBondsTB import FixedRateBondsTB
    from TB.STIRCapFloorsTB import STIRCapFloorsTB
    from TB.IRSwaptionsTB import IRSwaptionsTB
    from TB.IRSwapsTB import IRSwapsTB
    from TB.STIRFutureOptionsTB import STIRFutureOptionsTB
    from TB.STIRFuturesTB import STIRFuturesTB
    from TB.USTFutureOptionsTB import USTFutureOptionsTB
    from TB.USTFuturesTB import USTFuturesTB


_LOGGER = logging.getLogger(__name__)
_IRSWAP_ADJUSTED_SPREAD_VALUES = {
    value
    for value in (
        getattr(IRSwapValue, "MMSS_CARRY_ADJUSTED", None),
        getattr(IRSwapValue, "SPREADOVER_CARRY_ADJUSTED", None),
        getattr(IRSwapValue, "MMSS_ROLL_ADJUSTED", None),
        getattr(IRSwapValue, "SPREADOVER_ROLL_ADJUSTED", None),
        getattr(IRSwapValue, "MMSS_CR_ADJUSTED", None),
        getattr(IRSwapValue, "SPREADOVER_CR_ADJUSTED", None),
    )
    if value is not None
}


def _normalize_query_like(query: BaseQuery) -> List[BaseQuery]:
    if isinstance(query, UnifiedQuery):
        return [legacy for item in query.return_query() for legacy in _normalize_query_like(item.to_legacy())]

    if hasattr(query, "return_query"):
        out = query.return_query()
        items = out if isinstance(out, list) else [out]
        flat: List[BaseQuery] = []
        for item in items:
            if isinstance(item, UnifiedQuery):
                flat.extend(_normalize_query_like(item))
            else:
                flat.append(item)
        return flat

    return [query]


def _flatten_base_queries(queries: Iterable[Union[BaseQuery, List[BaseQuery]]]) -> List[BaseQuery]:
    flat: List[BaseQuery] = []
    for q in queries:
        if isinstance(q, list):
            for qq in q:
                flat.extend(_normalize_query_like(qq))
        else:
            flat.extend(_normalize_query_like(q))
    return flat


def _build_reference_points(
    start: DateLike,
    end: DateLike,
    *,
    freq: Optional[str],
    timestamps: Optional[List[datetime.datetime]],
) -> List[DateLike]:
    return build_reference_points(
        start=start,
        end=end,
        freq=freq,
        timestamps=timestamps,
    )


def _timestamp_utc_key(value: Any) -> Optional[datetime.datetime]:
    if value is None:
        return None
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if isinstance(value, datetime.date) and not isinstance(value, datetime.datetime):
        value = datetime.datetime.combine(value, datetime.time())
    if not isinstance(value, datetime.datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=datetime.timezone.utc)
    else:
        value = value.astimezone(datetime.timezone.utc)
    return value.replace(microsecond=0)


def _is_barchart_stirf_rl_source(mdp: Optional[MarketDataProvider]) -> bool:
    source = str(getattr(mdp, "source", "")).upper()
    return source in {"BARCHART_STIRF-RL", "BARCHART_STIRF_RL"}


def _irs_curve_store_source_family(mdp: Optional[MarketDataProvider]) -> Optional[str]:
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


def _uses_legacy_eris_eod_decimal_store_rates(mdp: Optional[MarketDataProvider]) -> bool:
    return _irs_curve_store_source_family(mdp) in {
        "eris_eod_rl_basic",
        "eris_eod_rl_basic_nojumps",
    }


def _supports_irs_curve_store_fast_path(mdp: Optional[MarketDataProvider]) -> bool:
    if mdp is None:
        return False
    fn = getattr(mdp, "_supports_curve_store_fast_path", None)
    if callable(fn):
        try:
            return bool(fn())
        except Exception:
            return False
    return _is_barchart_stirf_rl_source(mdp)


def _supports_irs_curve_store_raw_curve_fast_path(mdp: Optional[MarketDataProvider]) -> bool:
    if mdp is None:
        return False
    fn = getattr(mdp, "_supports_curve_store_raw_curve_fast_path", None)
    if callable(fn):
        try:
            return bool(fn())
        except Exception:
            return False
    return _is_barchart_stirf_rl_source(mdp)


def _supports_irs_curve_store_analytics_fast_path(mdp: Optional[MarketDataProvider]) -> bool:
    if mdp is None:
        return False
    fn = getattr(mdp, "_supports_curve_store_analytics_fast_path", None)
    if callable(fn):
        try:
            return bool(fn())
        except Exception:
            return False
    return _is_barchart_stirf_rl_source(mdp)


def _supports_irs_curve_store_session_minute_filter(mdp: Optional[MarketDataProvider]) -> bool:
    if mdp is None:
        return False
    fn = getattr(mdp, "_supports_curve_store_session_minute_filter", None)
    if callable(fn):
        try:
            return bool(fn())
        except Exception:
            return False
    return _is_barchart_stirf_rl_source(mdp)


def _matches_irs_curve_store_on_trading_date(mdp: Optional[MarketDataProvider]) -> bool:
    if mdp is None:
        return False
    fn = getattr(mdp, "_curve_store_match_on_trading_date", None)
    if callable(fn):
        try:
            return bool(fn())
        except Exception:
            return False
    return False


def _is_cme_rates_session_timestamp(ref_point: DateLike) -> bool:
    if not isinstance(ref_point, datetime.datetime):
        return True
    if ref_point.tzinfo is None or ref_point.tzinfo.utcoffset(ref_point) is None:
        return True

    # CME rates futures trade Sunday 17:00 CT through Friday 16:00 CT,
    # with the regular 16:00-17:00 CT maintenance break Monday-Thursday.
    ts_chi = ref_point.astimezone(pytz.timezone("America/Chicago"))
    tod = ts_chi.time()
    weekday = ts_chi.weekday()

    if weekday == 5:
        return False
    if weekday == 6:
        return tod >= datetime.time(17, 0)
    if weekday == 4:
        return tod <= datetime.time(16, 0)
    return tod <= datetime.time(16, 0) or tod >= datetime.time(17, 0)


def _filter_irs_reference_points_for_mdp(
    reference_points: List[DateLike],
    *,
    mdp: Optional[MarketDataProvider],
) -> List[DateLike]:
    if not _is_barchart_stirf_rl_source(mdp):
        return reference_points
    if not any(isinstance(point, datetime.datetime) for point in reference_points):
        return reference_points
    return [point for point in reference_points if _is_cme_rates_session_timestamp(point)]


def _curve_store_trading_date(timestamp: datetime.datetime) -> datetime.date:
    ts_chi = timestamp.astimezone(pytz.timezone("America/Chicago"))
    if ts_chi.hour >= 17:
        return (ts_chi + datetime.timedelta(days=1)).date()
    return ts_chi.date()


def _curve_store_session_minute(timestamp: datetime.datetime) -> int:
    ts_chi = timestamp.astimezone(pytz.timezone("America/Chicago"))
    session_open = ts_chi.replace(hour=6, minute=0, second=0, microsecond=0)
    return int((ts_chi - session_open).total_seconds() // 60)


def _normalize_trading_date(value: Any) -> Optional[datetime.date]:
    if value is None:
        return None
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    return None


def _ordered_unique_reference_points(reference_points: Iterable[DateLike]) -> List[DateLike]:
    return list(dict.fromkeys(reference_points))


@lru_cache(maxsize=1)
def _get_us_govt_bond_calendar():
    import QuantLib as ql

    return ql.UnitedStates(ql.UnitedStates.GovernmentBond)


def _is_us_govt_bond_business_day(ref_point: DateLike) -> bool:
    date_value = ref_point.date() if isinstance(ref_point, datetime.datetime) else ref_point
    try:
        from utils.ql_utils import datetime_to_ql_date
    except Exception:
        return True
    return bool(_get_us_govt_bond_calendar().isBusinessDay(datetime_to_ql_date(date_value)))


def _filter_irs_curve_store_reference_points(
    reference_points: Iterable[DateLike],
    *,
    requested_curve_name: str,
) -> List[DateLike]:
    filtered = _ordered_unique_reference_points(reference_points)
    if requested_curve_name == "USD-SOFR-1D":
        return [ref_point for ref_point in filtered if _is_us_govt_bond_business_day(ref_point)]
    return filtered


def _filter_fixed_rate_bond_reference_points(
    reference_points: Iterable[DateLike],
    *,
    router: Optional[object],
) -> List[DateLike]:
    filtered = _ordered_unique_reference_points(reference_points)
    if not filtered or any(isinstance(ref_point, datetime.datetime) for ref_point in filtered):
        return filtered

    if not bool(getattr(router, "_skip_non_business", False)):
        return filtered

    calendar = getattr(router, "_cal", None)
    if calendar is None or not hasattr(calendar, "isBusinessDay"):
        return filtered

    try:
        from utils.ql_utils import datetime_to_ql_date
    except Exception:
        return filtered

    return [
        ref_point
        for ref_point in filtered
        if bool(calendar.isBusinessDay(datetime_to_ql_date(ref_point)))
    ]


def _is_curve_coverage_complete(
    *,
    reference_points: Sequence[DateLike],
    query_count: int,
    covered: set[Tuple[DateLike, int]],
) -> bool:
    if query_count <= 0:
        return True
    expected_coverage = len(reference_points) * int(query_count)
    return expected_coverage == 0 or len(covered) >= expected_coverage


@dataclass(frozen=True)
class _ProductTimeseriesPlan:
    product: str
    queries: Tuple[BaseQuery, ...]
    strategy: str
    router: Optional[object] = None
    mdp: Optional[MarketDataProvider] = None


@dataclass(frozen=True)
class _TimeseriesRequestPlan:
    product_plans: Tuple[_ProductTimeseriesPlan, ...]
    irswap_spread_queries: Tuple[IRSwapQuery, ...] = ()
    irswap_asw_queries: Tuple[IRSwapQuery, ...] = ()


def _ct_alias_to_y(tenor: str) -> str:
    _CT_RE = re.compile(r"(?i)\bct\s*(\d+)\b")
    return _CT_RE.sub(r"\1Y", str(tenor))


def _y_alias_to_ct(tenor: str) -> str:
    _Y_RE = re.compile(r"(?i)\b(\d+)\s*y\b")
    return _Y_RE.sub(r"CT\1", str(tenor))


def _safe_col_name(q: Any, default: str) -> str:
    try:
        return q.col_name()
    except Exception:
        return default


def _resolve_irs_curve_store_reconstruction_workers(
    n_jobs: Optional[int],
    *,
    task_count: int,
) -> int:
    requested_workers = max(1, int(n_jobs or 1))
    if requested_workers > 1 or task_count < 64:
        return requested_workers
    return max(2, min(int(task_count), int(os.cpu_count() or 4), 8))


def _normalize_legacy_eris_eod_cached_rows(
    *,
    mdp: Optional[MarketDataProvider],
    requested_curve_name: str,
    query: IRSwapQuery,
    rows: Sequence[Tuple[DateLike, str, float]],
) -> List[Tuple[DateLike, str, float]]:
    if not rows or not _uses_legacy_eris_eod_decimal_store_rates(mdp):
        return list(rows)
    if query.value != IRSwapValue.RATE:
        return list(rows)
    if getattr(query, "structure", None) != IRSwapStructure.OUTRIGHT:
        return list(rows)

    expected_col_name = query.col_name(requested_curve_name)
    tenor_token = str(getattr(query, "tenor", "") or "").strip()
    if not tenor_token:
        return list(rows)

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
    return normalized_rows if used_legacy_alias else list(rows)


def _ref_point_date(ref_point: DateLike) -> datetime.date:
    return ref_point.date() if isinstance(ref_point, datetime.datetime) else ref_point


def _next_imm_dates(ref_date: datetime.date, *, count: int) -> list[datetime.date]:
    from rateslib.scheduling import next_imm

    imm = datetime.datetime.combine(ref_date + datetime.timedelta(days=1), datetime.time())
    out: list[datetime.date] = []
    for _ in range(max(0, int(count))):
        imm = next_imm(imm)
        imm_date = imm.date() if isinstance(imm, datetime.datetime) else imm
        out.append(imm_date)
        imm = datetime.datetime.combine(imm_date, datetime.time())
    return out


def _resolve_imm_tenor_date(token: str, *, ref_date: datetime.date) -> Optional[datetime.date]:
    from rateslib.scheduling import get_imm

    imm_token = str(token or "").strip().upper()
    if not imm_token.startswith("IMM_"):
        return None
    suffix = imm_token.split("IMM_", 1)[1]
    if suffix.isnumeric():
        rank = int(suffix)
        if rank <= 0:
            return None
        upcoming = _next_imm_dates(ref_date, count=rank)
        return upcoming[rank - 1] if len(upcoming) >= rank else None
    try:
        imm_value = get_imm(code=suffix)
    except Exception:
        return None
    if isinstance(imm_value, datetime.datetime):
        return imm_value.date()
    return imm_value


def _map_explicit_imm_pair_to_relative(
    token: str,
    *,
    ref_date: datetime.date,
    max_rank: int,
) -> Optional[str]:
    imm_pair = str(token or "").strip().upper()
    if not imm_pair.startswith("IMM_") or "XIMM_" not in imm_pair:
        return None
    left_token, right_token = imm_pair.split("X", 1)
    effective_date = _resolve_imm_tenor_date(left_token, ref_date=ref_date)
    maturity_date = _resolve_imm_tenor_date(right_token, ref_date=effective_date or ref_date)
    if effective_date is None or maturity_date is None:
        return None

    upcoming = _next_imm_dates(ref_date, count=max_rank + 1)
    try:
        left_rank = upcoming.index(effective_date) + 1
        right_rank = upcoming.index(maturity_date) + 1
    except ValueError:
        return None

    if right_rank != left_rank + 1 or left_rank > max_rank:
        return None
    return f"IMM_{left_rank}xIMM_{right_rank}"


def _map_explicit_cb_tenor_to_rank(
    curve_name: str,
    token: str,
    *,
    ref_date: datetime.date,
    max_rank: int,
) -> Optional[str]:
    from Query.IRSwaps._CENTRAL_BANK_DATES import resolve_central_bank_tenor

    tenor_token = str(token or "").strip()
    if not tenor_token:
        return None
    if re.fullmatch(r"(?i)FOMC_\d+", tenor_token):
        rank = int(tenor_token.split("_", 1)[1])
        return f"FOMC_{rank}" if 1 <= rank <= max_rank else None

    try:
        target_dates = resolve_central_bank_tenor(curve_name, tenor_token, as_of=ref_date)
    except Exception:
        return None
    if target_dates is None:
        return None

    for rank in range(1, max_rank + 1):
        try:
            rank_dates = resolve_central_bank_tenor(curve_name, f"fomc_{rank}", as_of=ref_date)
        except Exception:
            continue
        if rank_dates == target_dates:
            return f"FOMC_{rank}"
    return None


def _analytics_token_for_query_tenor(
    *,
    requested_curve_name: str,
    token: str,
    ref_point: DateLike,
) -> Optional[str]:
    from Caching.curve_analytics import analytics_tenors_for_curve

    normalized = str(token or "").strip().upper().replace(" ", "")
    if not normalized:
        return None

    supported = {item.upper(): item for item in analytics_tenors_for_curve(requested_curve_name)}
    if normalized in supported:
        return supported[normalized]

    ref_date = _ref_point_date(ref_point)
    if normalized.startswith("IMM_") and "XIMM_" in normalized:
        mapped = _map_explicit_imm_pair_to_relative(normalized, ref_date=ref_date, max_rank=12)
        if mapped is not None and mapped.upper() in supported:
            return supported[mapped.upper()]

    if normalized.startswith("FOMC_") or normalized.startswith("FOMC"):
        mapped = _map_explicit_cb_tenor_to_rank(requested_curve_name, normalized, ref_date=ref_date, max_rank=7)
        if mapped is not None and mapped.upper() in supported:
            return supported[mapped.upper()]

    return None


def _analytics_rate_components(q: IRSwapQuery) -> Optional[list[tuple[float, str]]]:
    if q.value != IRSwapValue.RATE:
        return None

    tenor_text = str(getattr(q, "tenor", "") or "").strip().upper().replace(" ", "")
    if not tenor_text:
        return None

    tokens = [tok for tok in tenor_text.split("/") if tok]
    if not tokens:
        return None

    if len(tokens) == 1 and q.structure == IRSwapStructure.OUTRIGHT:
        return [(1.0, tokens[0])]
    if len(tokens) == 2 and q.structure == IRSwapStructure.CURVE:
        return [(-1.0, tokens[0]), (1.0, tokens[1])]
    if len(tokens) == 3 and q.structure == IRSwapStructure.FLY:
        return [(-1.0, tokens[0]), (2.0, tokens[1]), (-1.0, tokens[2])]
    return None


def _uses_alias_backed_irs_tenor(q: IRSwapQuery) -> bool:
    tenor_text = str(getattr(q, "tenor", "") or "").strip()
    if not tenor_text:
        return False
    tokens = [token.strip().upper() for token in tenor_text.split("/") if token.strip()]
    return any(_looks_like_alias_or_cusip(token) for token in tokens)


class _GenericTimeseriesTB(BaseTimeseriesTB):
    def __init__(
        self,
        *,
        product: str,
        mdp: MarketDataProvider,
        date_col: str,
    ):
        self._product = product
        super().__init__(mdp=mdp, date_col=date_col, show_tqdm=True)

    def _pricing_message(self, queries: List[BaseQuery]) -> str:
        _ = queries
        return f"Generic TB [{self._product}]"


class TimeseriesBuilder:
    def __init__(
        self,
        *,
        irswaps_tb: Optional["IRSwapsTB"] = None,
        irswaptions_tb: Optional["IRSwaptionsTB"] = None,
        fixedratebonds_tb: Optional["FixedRateBondsTB"] = None,
        stirfutures_tb: Optional["STIRFuturesTB"] = None,
        ustfutures_tb: Optional["USTFuturesTB"] = None,
        stircapfloors_tb: Optional["STIRCapFloorsTB"] = None,
        stirfutureoptions_tb: Optional["STIRFutureOptionsTB"] = None,
        ustfutureoptions_tb: Optional["USTFutureOptionsTB"] = None,
        fxforwards_tb: Optional[object] = None,
        date_col: str = "Date",
    ):
        self._date_col = date_col
        self._routers: Dict[str, object] = {
            "IRS": irswaps_tb,
            "FRB": fixedratebonds_tb,
        }
        if irswaptions_tb is not None:
            self._routers["IRSWAPTION"] = irswaptions_tb
            self._routers["IRSWAPTIONS"] = irswaptions_tb
        if stirfutures_tb is not None:
            self._routers["STIRFUTURE"] = stirfutures_tb
        if ustfutures_tb is not None:
            self._routers["USTFUTURE"] = ustfutures_tb
        if stircapfloors_tb is not None:
            self._routers["STIRCAPFLOOR"] = stircapfloors_tb
            self._routers["STIRCAPFLOORS"] = stircapfloors_tb
        if stirfutureoptions_tb is not None:
            self._routers["STIRFUTUREOPTION"] = stirfutureoptions_tb
        if ustfutureoptions_tb is not None:
            self._routers["USTFUTUREOPTION"] = ustfutureoptions_tb
        if fxforwards_tb is not None:
            self._routers["FXFORWARD"] = fxforwards_tb

        self._generic_router_cache: Dict[str, _GenericTimeseriesTB] = {}
        self._specialized_router_cache: Dict[str, object] = {}

    def register_router(self, product: str, tb_obj: object) -> None:
        self._routers[product] = tb_obj

    def _get_generic_router(self, product: str, mdp: MarketDataProvider) -> _GenericTimeseriesTB:
        existing = self._generic_router_cache.get(product)
        if existing is not None and existing.mdp is mdp:
            return existing
        generic_tb = _GenericTimeseriesTB(product=product, mdp=mdp, date_col=self._date_col)
        self._generic_router_cache[product] = generic_tb
        return generic_tb

    def _get_specialized_router(self, product: str, mdp: MarketDataProvider) -> Optional[object]:
        canonical_product = {"IRSWAPTIONS": "IRSWAPTION", "STIRCAPFLOORS": "STIRCAPFLOOR"}.get(product, product)
        existing = self._specialized_router_cache.get(canonical_product)
        if existing is not None and getattr(existing, "mdp", None) is mdp:
            return existing

        router_cls = None
        if canonical_product == "FRB":
            from TB.FixedRateBondsTB import FixedRateBondsTB

            router_cls = FixedRateBondsTB
        elif canonical_product == "IRSWAPTION":
            from TB.IRSwaptionsTB import IRSwaptionsTB

            router_cls = IRSwaptionsTB
        elif canonical_product == "IRS":
            from TB.IRSwapsTB import IRSwapsTB

            router_cls = IRSwapsTB

        if router_cls is None:
            return None

        router = router_cls(mdp=mdp, date_col=self._date_col, show_tqdm=True)
        self._specialized_router_cache[canonical_product] = router
        return router

    def _route_product_timeseries(
        self,
        *,
        product: str,
        qs: List[BaseQuery],
        merged_routers: Dict[str, Any],
        merged_mdps: Dict[str, MarketDataProvider],
        start: DateLike,
        end: DateLike,
        n_jobs: Optional[int],
        ignore_cache: Optional[bool],
        freq: Optional[str],
        timestamps: Optional[List[datetime.datetime]],
    ) -> pd.DataFrame:
        canonical_product, tb, mdp = self._resolve_product_handles(
            product=product,
            merged_routers=merged_routers,
            merged_mdps=merged_mdps,
        )
        route_freq = freq
        route_timestamps = timestamps
        if canonical_product == "IRS":
            intraday_timestamps = self._prepare_product_intraday_timestamps(
                product=canonical_product,
                mdp=mdp,
                start=start,
                end=end,
                freq=freq,
                timestamps=timestamps,
            )
            if intraday_timestamps is not None:
                if not intraday_timestamps:
                    return pd.DataFrame().set_index(pd.Index([], name=self._date_col))
                route_freq = None
                route_timestamps = intraday_timestamps

        if tb is not None:
            cached_df = self._try_routed_product_computed_cache_hit(
                product=canonical_product,
                queries=qs,
                router=tb,
                mdp=mdp,
                start=start,
                end=end,
                freq=route_freq,
                timestamps=route_timestamps,
                ignore_cache=ignore_cache,
            )
            if cached_df is not None:
                return cached_df
            return tb.get_timeseries(  # type: ignore[attr-defined]
                start,
                end,
                qs,
                n_jobs=n_jobs,
                ignore_cache=ignore_cache,
                freq=route_freq,
                timestamps=route_timestamps,
            )

        if mdp is not None:
            generic_tb = self._get_generic_router(canonical_product, mdp)
            return generic_tb.get_timeseries(
                start,
                end,
                qs,
                n_jobs=n_jobs,
                ignore_cache=ignore_cache,
                freq=route_freq,
                timestamps=route_timestamps,
            )

        if canonical_product in {"FXFORWARD", "FXFORWARDS"}:
            raise NotImplementedError(
                "FX forward timeseries queries are not supported yet: no FX-forward BaseQuery implementation is available."
            )

        available = sorted(set(merged_routers.keys()) | set(merged_mdps.keys()))
        raise KeyError(
            f"No timeseries router or MDP registered for product '{product}'. "
            f"Available: {available}"
        )

    @staticmethod
    def _get_irswap_spreads_mdp(merged_mdps: Mapping[str, MarketDataProvider]) -> Optional[MarketDataProvider]:
        for key in ("IRSWAPSPREADS", "IRSWAPSPREAD", "SWAPSPREADS"):
            mdp = merged_mdps.get(key)
            if mdp is not None:
                return mdp
        return None

    def _price_irswap_spread_queries_with_mdp(
        self,
        *,
        mdp: MarketDataProvider,
        queries: List[IRSwapQuery],
        start: DateLike,
        end: DateLike,
        freq: Optional[str],
        timestamps: Optional[List[datetime.datetime]],
        desc: str,
    ) -> pd.DataFrame:
        if not queries:
            return pd.DataFrame().set_index(pd.Index([], name=self._date_col))

        generic_tb = self._get_generic_router("IRSWAPSPREAD", mdp)
        reference_points = generic_tb._build_reference_points(
            start=start,
            end=end,
            freq=freq,
            timestamps=timestamps,
        )

        rows = []
        for ref_point in _tqdm(reference_points, desc=desc):
            for q in queries:
                try:
                    pricer = mdp.get_pricer(IRSwapSpreadsMDP.build_request_from_query(q, ref_point))
                    default = (
                        f"{getattr(q, 'curve', 'IRS')}."
                        f"{getattr(q, 'tenor', '')}."
                        f"{getattr(getattr(q, 'value', None), 'name', 'SPREAD')}"
                    )
                    rows.append((ref_point, _safe_col_name(q, default), float(pricer.value_bps())))
                except Exception:
                    continue

        if not rows:
            return pd.DataFrame().set_index(pd.Index([], name=self._date_col))

        df = (
            pd.DataFrame(rows, columns=[self._date_col, "Column", "Value"])
            .pivot(index=self._date_col, columns="Column", values="Value")
            .sort_index()
        )
        df.index.name = self._date_col
        return df

    def _append_product_frame(
        self,
        per_product_frames: List[Tuple[str, pd.DataFrame]],
        *,
        product: str,
        df: pd.DataFrame,
    ) -> None:
        if df is None or df.empty:
            return
        df = self._strip_redundant_date_column(df)
        if self._date_col in df.columns:
            df = df.set_index(self._date_col)
        per_product_frames.append((product, pd.concat({product: df}, axis=1)))

    def _strip_redundant_date_column(self, df: pd.DataFrame) -> pd.DataFrame:
        if df is None or df.empty or self._date_col not in df.columns:
            return df
        if df.index.name != self._date_col:
            return df

        date_series = pd.to_datetime(df[self._date_col], errors="coerce")
        index_series = pd.to_datetime(pd.Index(df.index), errors="coerce")
        if len(date_series) != len(index_series):
            return df
        if date_series.isna().all():
            return df.drop(columns=[self._date_col])
        aligned = date_series.where(date_series.notna(), index_series)
        if aligned.equals(pd.Series(index_series, index=df.index)):
            return df.drop(columns=[self._date_col])
        return df

    def _coerce_date_index(self, df: pd.DataFrame) -> pd.DataFrame:
        if df is None or df.empty:
            return df

        if isinstance(df.index, pd.DatetimeIndex):
            out = df.copy()
            out.index = pd.Index(out.index.date, name=out.index.name or self._date_col)
            return out

        raw_index = list(df.index)
        if raw_index and all(isinstance(point, datetime.datetime) for point in raw_index):
            out = df.copy()
            out.index = pd.Index([point.date() for point in raw_index], name=df.index.name or self._date_col)
            return out

        return df

    def _group_business_date_ranges(self, date_points: List[datetime.date]) -> List[Tuple[datetime.date, datetime.date]]:
        ordered_points = sorted({point for point in date_points})
        if not ordered_points:
            return []

        ranges: List[Tuple[datetime.date, datetime.date]] = []
        range_start = ordered_points[0]
        range_end = ordered_points[0]
        for current in ordered_points[1:]:
            if len(pd.bdate_range(range_end, current).date.tolist()) == 2:
                range_end = current
                continue
            ranges.append((range_start, range_end))
            range_start = current
            range_end = current
        ranges.append((range_start, range_end))
        return ranges

    def _resolve_product_handles(
        self,
        *,
        product: str,
        merged_routers: Mapping[str, Any],
        merged_mdps: Mapping[str, MarketDataProvider],
    ) -> Tuple[str, Optional[object], Optional[MarketDataProvider]]:
        alias_map = {"IRSWAPTIONS": "IRSWAPTION", "STIRCAPFLOORS": "STIRCAPFLOOR"}
        canonical_product = alias_map.get(product, product)
        router = merged_routers.get(product) or merged_routers.get(canonical_product)
        mdp = merged_mdps.get(product) or merged_mdps.get(canonical_product)
        if mdp is None and router is not None and hasattr(router, "mdp"):
            mdp = getattr(router, "mdp")
        if router is None and mdp is not None:
            router = self._get_specialized_router(canonical_product, mdp)
        return canonical_product, router, mdp

    @staticmethod
    def _parallel_product_workers(plan_count: int, n_jobs: Optional[int]) -> int:
        if plan_count <= 1 or not n_jobs or n_jobs <= 1:
            return 1
        return max(1, min(plan_count, int(n_jobs)))

    @staticmethod
    def _route_job_budget(n_jobs: Optional[int], worker_count: int) -> int:
        if not n_jobs or n_jobs <= 1:
            return 1
        return max(1, int(n_jobs) // max(1, worker_count))

    def _prepare_product_intraday_timestamps(
        self,
        *,
        product: str,
        mdp: Optional[MarketDataProvider],
        start: DateLike,
        end: DateLike,
        freq: Optional[str],
        timestamps: Optional[List[datetime.datetime]],
    ) -> Optional[List[datetime.datetime]]:
        if product != "IRS" or not _is_barchart_stirf_rl_source(mdp):
            return None

        reference_points = _build_reference_points(
            start=start,
            end=end,
            freq=freq,
            timestamps=timestamps,
        )
        if not any(isinstance(point, datetime.datetime) for point in reference_points):
            return None

        return [
            point
            for point in _filter_irs_reference_points_for_mdp(reference_points, mdp=mdp)
            if isinstance(point, datetime.datetime)
        ]

    def _can_use_irs_curve_store_fast_path(
        self,
        *,
        queries: List[IRSwapQuery],
        mdp: Optional[MarketDataProvider],
        start: DateLike,
        end: DateLike,
        ignore_cache: Optional[bool],
        freq: Optional[str],
        timestamps: Optional[List[datetime.datetime]],
    ) -> bool:
        if not queries or mdp is None or ignore_cache:
            return False

        if not _supports_irs_curve_store_fast_path(mdp):
            return False

        required_attrs = (
            "_get_curve_store",
            "_resolve_curve_store_curve_name",
            "_to_curve_store_timestamp",
        )
        if not all(hasattr(mdp, attr) for attr in required_attrs):
            return False

        ref_points = _build_reference_points(start=start, end=end, freq=freq, timestamps=timestamps)
        if _is_barchart_stirf_rl_source(mdp):
            ref_points = _filter_irs_reference_points_for_mdp(ref_points, mdp=mdp)
        if not ref_points:
            return False

        for q in queries:
            if not isinstance(q, IRSwapQuery):
                return False
            req = dict(q.market_request or {})
            time_key = str(getattr(q, "mdp_time_key", "timestamp") or "timestamp")
            if str(req.get(time_key, "")).lower() == "live":
                return False
            if _uses_alias_backed_irs_tenor(q):
                return False

        return True

    def _build_request_plan(
        self,
        *,
        flat_queries: List[BaseQuery],
        merged_routers: Mapping[str, Any],
        merged_mdps: Mapping[str, MarketDataProvider],
        start: DateLike,
        end: DateLike,
        ignore_cache: Optional[bool],
        freq: Optional[str],
        timestamps: Optional[List[datetime.datetime]],
    ) -> _TimeseriesRequestPlan:
        by_product: DefaultDict[str, List[BaseQuery]] = defaultdict(list)
        for q in flat_queries:
            if not getattr(q, "product", None):
                raise ValueError(f"Query missing 'product': {q!r}")
            by_product[q.product].append(q)

        product_plans: List[_ProductTimeseriesPlan] = []
        irswap_spread_queries: List[IRSwapQuery] = []
        irswap_asw_queries: List[IRSwapQuery] = []

        for product, qs in by_product.items():
            canonical_product, router, mdp = self._resolve_product_handles(
                product=product,
                merged_routers=merged_routers,
                merged_mdps=merged_mdps,
            )

            if canonical_product == "IRS":
                irs_qs_unfiltered: List[IRSwapQuery] = [q for q in qs if isinstance(q, IRSwapQuery)]
                irs_qs: List[IRSwapQuery] = []
                for q in irs_qs_unfiltered:
                    if q.value in ({IRSwapValue.MMSS, IRSwapValue.SPREADOVER} | _IRSWAP_ADJUSTED_SPREAD_VALUES):
                        irswap_spread_queries.append(q)
                    elif q.value in [
                        IRSwapValue.PAR_PAR_ASW,
                        IRSwapValue.PAR_PAR_ASW,
                        IRSwapValue.TRUE_ASW,
                        IRSwapValue.PROCEEDS_ASW,
                        IRSwapValue.MARKET_ASW,
                    ]:
                        irswap_asw_queries.append(q)
                    else:
                        irs_qs.append(q)

                if not irs_qs:
                    continue

                strategy = "irs_curve_store" if self._can_use_irs_curve_store_fast_path(
                    queries=irs_qs,
                    mdp=mdp,
                    start=start,
                    end=end,
                    ignore_cache=ignore_cache,
                    freq=freq,
                    timestamps=timestamps,
                ) else "route"
                product_plans.append(
                    _ProductTimeseriesPlan(
                        product="IRS",
                        queries=tuple(irs_qs),
                        strategy=strategy,
                        router=router,
                        mdp=mdp,
                    )
                )
                continue

            if canonical_product == "FRB":
                frb_qs: List[FixedRateBondQuery] = [q for q in qs if isinstance(q, FixedRateBondQuery)]
                if len(frb_qs) != len(qs):
                    raise TypeError("Mixed/non-FRB queries encountered in FixedRateBond bucket")
                product_plans.append(
                    _ProductTimeseriesPlan(
                        product="FRB",
                        queries=tuple(frb_qs),
                        strategy="route",
                        router=router,
                        mdp=mdp,
                    )
                )
                continue

            if router is None and mdp is None:
                if canonical_product in {"FXFORWARD", "FXFORWARDS"}:
                    raise NotImplementedError(
                        "FX forward timeseries queries are not supported yet: no FX-forward BaseQuery implementation is available."
                    )
                available = sorted(set(merged_routers.keys()) | set(merged_mdps.keys()))
                raise KeyError(
                    f"No timeseries router or MDP registered for product '{product}'. "
                    f"Available: {available}"
                )

            product_plans.append(
                _ProductTimeseriesPlan(
                    product=product,
                    queries=tuple(qs),
                    strategy="route",
                    router=router,
                    mdp=mdp,
                )
            )

        return _TimeseriesRequestPlan(
            product_plans=tuple(product_plans),
            irswap_spread_queries=tuple(irswap_spread_queries),
            irswap_asw_queries=tuple(irswap_asw_queries),
        )

    def _execute_product_plan(
        self,
        *,
        plan: _ProductTimeseriesPlan,
        merged_routers: Dict[str, Any],
        merged_mdps: Dict[str, MarketDataProvider],
        start: DateLike,
        end: DateLike,
        n_jobs: Optional[int],
        ignore_cache: Optional[bool],
        freq: Optional[str],
        timestamps: Optional[List[datetime.datetime]],
        use_irs_vectorized_pricing: bool,
    ) -> pd.DataFrame:
        if plan.strategy == "irs_curve_store":
            return self._execute_irs_curve_store_plan(
                plan=plan,
                start=start,
                end=end,
                n_jobs=n_jobs,
                ignore_cache=ignore_cache,
                freq=freq,
                timestamps=timestamps,
                use_irs_vectorized_pricing=use_irs_vectorized_pricing,
            )

        return self._route_product_timeseries(
            product=plan.product,
            qs=list(plan.queries),
            merged_routers=merged_routers,
            merged_mdps=merged_mdps,
            start=start,
            end=end,
            n_jobs=n_jobs,
            ignore_cache=ignore_cache,
            freq=freq,
            timestamps=timestamps,
        )

    def _execute_product_plans(
        self,
        *,
        plan: _TimeseriesRequestPlan,
        merged_routers: Dict[str, Any],
        merged_mdps: Dict[str, MarketDataProvider],
        start: DateLike,
        end: DateLike,
        n_jobs: Optional[int],
        ignore_cache: Optional[bool],
        freq: Optional[str],
        timestamps: Optional[List[datetime.datetime]],
        use_irs_vectorized_pricing: bool,
    ) -> List[Tuple[str, pd.DataFrame]]:
        if not plan.product_plans:
            return []

        worker_count = self._parallel_product_workers(len(plan.product_plans), n_jobs)
        route_jobs = self._route_job_budget(n_jobs, worker_count)

        results: List[Optional[pd.DataFrame]] = [None] * len(plan.product_plans)
        if worker_count <= 1:
            for idx, product_plan in enumerate(plan.product_plans):
                results[idx] = self._execute_product_plan(
                    plan=product_plan,
                    merged_routers=merged_routers,
                    merged_mdps=merged_mdps,
                    start=start,
                    end=end,
                    n_jobs=route_jobs,
                    ignore_cache=ignore_cache,
                    freq=freq,
                    timestamps=timestamps,
                    use_irs_vectorized_pricing=use_irs_vectorized_pricing,
                )
        else:
            with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="ts-builder") as pool:
                future_map = {
                    pool.submit(
                        self._execute_product_plan,
                        plan=product_plan,
                        merged_routers=merged_routers,
                        merged_mdps=merged_mdps,
                        start=start,
                        end=end,
                        n_jobs=route_jobs,
                        ignore_cache=ignore_cache,
                        freq=freq,
                        timestamps=timestamps,
                        use_irs_vectorized_pricing=use_irs_vectorized_pricing,
                    ): idx
                    for idx, product_plan in enumerate(plan.product_plans)
                }
                for future in as_completed(future_map):
                    idx = future_map[future]
                    results[idx] = future.result()

        return [
            (product_plan.product, results[idx] if results[idx] is not None else pd.DataFrame())
            for idx, product_plan in enumerate(plan.product_plans)
        ]

    def _read_irs_curve_store_analytics_rows(
        self,
        *,
        mdp: Optional[Any],
        store: Any,
        resolved_curve_name: str,
        requested_curve_name: str,
        queries: List[IRSwapQuery],
        requested_key_by_ref: Mapping[DateLike, datetime.datetime],
    ) -> Tuple[List[Tuple[DateLike, str, float]], set[Tuple[DateLike, int]]]:
        eligible: List[Tuple[int, IRSwapQuery, list[tuple[float, str]]]] = []
        for idx, q in enumerate(queries):
            components = _analytics_rate_components(q)
            if components:
                eligible.append((idx, q, components))

        if not eligible:
            return [], set()

        ref_keys = list(requested_key_by_ref.values())
        start_bound = min(ref_keys).date()
        end_bound = max(ref_keys).date()
        from Caching.curve_analytics import analytics_tenors_for_curve

        analytics_tenors = list(analytics_tenors_for_curve(requested_curve_name))
        use_trading_date_match = _matches_irs_curve_store_on_trading_date(mdp)
        try:
            analytics_kwargs = {
                "start": start_bound,
                "end": end_bound,
                "tenors": analytics_tenors,
                "metrics": ["par_rate", "rate"],
            }
            if not use_trading_date_match:
                analytics_kwargs["timestamps_utc"] = ref_keys
            analytics_df = store.read_analytics(resolved_curve_name, **analytics_kwargs)
        except TypeError:
            analytics_df = store.read_analytics(
                resolved_curve_name,
                start=start_bound,
                end=end_bound,
                tenors=analytics_tenors,
                metrics=["par_rate", "rate"],
            )
        if analytics_df.empty or "timestamp_utc" not in analytics_df.columns:
            return [], set()

        rows_by_key: Dict[Any, Any] = {}
        if use_trading_date_match and "trading_date" in analytics_df.columns:
            for _, row in analytics_df.iterrows():
                trading_date = _normalize_trading_date(row.get("trading_date"))
                if trading_date is not None:
                    rows_by_key[trading_date] = row
        else:
            for _, row in analytics_df.iterrows():
                ts_key = _timestamp_utc_key(row.get("timestamp_utc"))
                if ts_key is not None:
                    rows_by_key[ts_key] = row

        rows: List[Tuple[DateLike, str, float]] = []
        covered: set[Tuple[DateLike, int]] = set()
        for ref_point, ts_key in requested_key_by_ref.items():
            lookup_key: Any = _curve_store_trading_date(ts_key) if use_trading_date_match else ts_key
            row = rows_by_key.get(lookup_key)
            if row is None:
                continue
            for idx, q, components in eligible:
                component_values: list[float] = []
                for weight, tenor in components:
                    analytics_token = _analytics_token_for_query_tenor(
                        requested_curve_name=requested_curve_name,
                        token=tenor,
                        ref_point=ref_point,
                    )
                    if analytics_token is None:
                        component_values = []
                        break
                    component_value = None
                    for metric_name in ("par_rate", "rate"):
                        col_name = f"{metric_name}_{analytics_token}"
                        if col_name in row.index and pd.notna(row[col_name]):
                            component_value = float(row[col_name]) * float(weight)
                            if (
                                metric_name == "rate"
                                and _uses_legacy_eris_eod_decimal_store_rates(mdp)
                                and pd.isna(row.get(f"par_rate_{analytics_token}"))
                            ):
                                component_value *= 100.0
                            break
                    if component_value is None:
                        component_values = []
                        break
                    component_values.append(component_value)
                if not component_values:
                    continue
                default = f"{requested_curve_name}.{getattr(q, 'tenor', '')}.{IRSwapValue.RATE.name}"
                query_value = float(sum(component_values))
                if len(components) > 1:
                    query_value *= 100.0
                rows.append((ref_point, _safe_col_name(q, default), query_value))
                covered.add((ref_point, idx))
        return rows, covered

    def _read_irs_computed_cache_rows(
        self,
        *,
        router: Optional[object],
        requested_curve_name: str,
        queries: List[IRSwapQuery],
        reference_points: List[DateLike],
        intraday: bool,
    ) -> Tuple[List[Tuple[DateLike, str, float]], set[Tuple[DateLike, int]]]:
        if router is None:
            return [], set()
        computed_store = getattr(router, "_computed_ts_store", None)
        symbol_builder = getattr(router, "_ts_symbol_for_query", None)
        if computed_store is None or not callable(symbol_builder):
            return [], set()

        rows: List[Tuple[DateLike, str, float]] = []
        covered: set[Tuple[DateLike, int]] = set()
        for idx, q in enumerate(queries):
            try:
                q_rows = computed_store.read_rows(
                    symbol=symbol_builder(requested_curve_name, q),
                    reference_points=reference_points,
                    intraday=intraday,
                    skip_current_eod=True,
                    fallback_column_name=q.col_name(requested_curve_name),
                )
            except Exception:
                q_rows = []
            q_rows = _normalize_legacy_eris_eod_cached_rows(
                mdp=getattr(router, "mdp", None),
                requested_curve_name=requested_curve_name,
                query=q,
                rows=q_rows,
            )
            rows.extend(q_rows)
            covered.update((ref_point, idx) for ref_point, _col, _value in q_rows)
        return rows, covered

    def _read_frb_computed_cache_rows(
        self,
        *,
        router: Optional[object],
        queries: List[FixedRateBondQuery],
        reference_points: List[DateLike],
        intraday: bool,
    ) -> Tuple[List[Tuple[DateLike, str, float]], set[Tuple[DateLike, int]]]:
        if router is None:
            return [], set()
        computed_store = getattr(router, "_computed_ts_store", None)
        symbol_builder = getattr(router, "_ts_symbol_for_query", None)
        if computed_store is None or not callable(symbol_builder):
            return [], set()

        rows: List[Tuple[DateLike, str, float]] = []
        covered: set[Tuple[DateLike, int]] = set()
        for idx, q in enumerate(queries):
            try:
                q_rows = computed_store.read_rows(
                    symbol=symbol_builder(q),
                    reference_points=reference_points,
                    intraday=intraday,
                    skip_current_eod=True,
                    fallback_column_name=q.col_name(),
                )
            except Exception:
                q_rows = []
            rows.extend(q_rows)
            covered.update((ref_point, idx) for ref_point, _col, _value in q_rows)
        return rows, covered

    def _frame_from_cached_rows(
        self,
        *,
        product: str,
        router: Optional[object],
        mdp: Optional[MarketDataProvider],
        rows: List[Tuple[DateLike, str, float]],
    ) -> pd.DataFrame:
        if router is not None and hasattr(router, "_rows_to_frame"):
            return router._rows_to_frame(rows)  # type: ignore[attr-defined]
        if mdp is not None:
            return self._get_generic_router(product, mdp)._rows_to_frame(rows)
        return pd.DataFrame().set_index(pd.Index([], name=self._date_col))

    def _try_routed_product_computed_cache_hit(
        self,
        *,
        product: str,
        queries: List[BaseQuery],
        router: Optional[object],
        mdp: Optional[MarketDataProvider],
        start: DateLike,
        end: DateLike,
        freq: Optional[str],
        timestamps: Optional[List[datetime.datetime]],
        ignore_cache: Optional[bool],
    ) -> Optional[pd.DataFrame]:
        if ignore_cache or router is None:
            return None

        computed_store = getattr(router, "_computed_ts_store", None)
        if computed_store is None:
            return None

        reference_points = _ordered_unique_reference_points(
            _build_reference_points(start=start, end=end, freq=freq, timestamps=timestamps)
        )
        if not reference_points:
            return pd.DataFrame().set_index(pd.Index([], name=self._date_col))

        intraday = any(isinstance(ref_point, datetime.datetime) for ref_point in reference_points)

        if product == "IRS":
            from TB.IRSwapsTB import _group_queries_by_curve as _group_irs_queries_by_curve

            irs_queries = [q for q in queries if isinstance(q, IRSwapQuery)]
            if len(irs_queries) != len(queries):
                return None

            rows: List[Tuple[DateLike, str, float]] = []
            any_reference_points = False
            for requested_curve_name, curve_queries in _group_irs_queries_by_curve(irs_queries).items():
                curve_reference_points = _filter_irs_curve_store_reference_points(
                    reference_points,
                    requested_curve_name=requested_curve_name,
                )
                if not curve_reference_points:
                    continue
                any_reference_points = True
                curve_rows, covered = self._read_irs_computed_cache_rows(
                    router=router,
                    requested_curve_name=requested_curve_name,
                    queries=curve_queries,
                    reference_points=curve_reference_points,
                    intraday=intraday,
                )
                if not _is_curve_coverage_complete(
                    reference_points=curve_reference_points,
                    query_count=len(curve_queries),
                    covered=covered,
                ):
                    return None
                rows.extend(curve_rows)

            if not any_reference_points:
                return pd.DataFrame().set_index(pd.Index([], name=self._date_col))
            return self._frame_from_cached_rows(product=product, router=router, mdp=mdp, rows=rows)

        if product == "FRB":
            frb_queries = [q for q in queries if isinstance(q, FixedRateBondQuery)]
            if len(frb_queries) != len(queries):
                return None

            filtered_reference_points = _filter_fixed_rate_bond_reference_points(
                reference_points,
                router=router,
            )
            if not filtered_reference_points:
                return pd.DataFrame().set_index(pd.Index([], name=self._date_col))

            rows, covered = self._read_frb_computed_cache_rows(
                router=router,
                queries=frb_queries,
                reference_points=filtered_reference_points,
                intraday=intraday,
            )
            if not _is_curve_coverage_complete(
                reference_points=filtered_reference_points,
                query_count=len(frb_queries),
                covered=covered,
            ):
                return None
            return self._frame_from_cached_rows(product=product, router=router, mdp=mdp, rows=rows)

        return None

    def _write_irs_computed_cache_rows(
        self,
        *,
        router: Optional[object],
        requested_curve_name: str,
        rows_by_query_idx: Mapping[int, List[Tuple[DateLike, str, float]]],
        queries: List[IRSwapQuery],
    ) -> None:
        if router is None:
            return
        computed_store = getattr(router, "_computed_ts_store", None)
        symbol_builder = getattr(router, "_ts_symbol_for_query", None)
        if computed_store is None or not callable(symbol_builder):
            return

        grouped: Dict[str, List[Tuple[DateLike, str, float]]] = {}
        for idx, rows in rows_by_query_idx.items():
            if not rows:
                continue
            q = queries[idx]
            grouped[symbol_builder(requested_curve_name, q)] = list(rows)
        if not grouped:
            return
        try:
            append_many = getattr(computed_store, "append_many_rows", None)
            if callable(append_many):
                append_many(rows_by_symbol=grouped)
                return
        except Exception:
            pass

        for symbol, rows in grouped.items():
            try:
                computed_store.append_rows(symbol=symbol, rows=rows)
            except Exception:
                continue

    def _read_irs_curve_store_raw_df(
        self,
        *,
        mdp: Optional[Any],
        store: Any,
        resolved_curve_name: str,
        requested_keys: List[datetime.datetime],
    ) -> pd.DataFrame:
        if not requested_keys:
            return pd.DataFrame()

        trading_dates = sorted({_curve_store_trading_date(ts_key) for ts_key in requested_keys})
        session_minutes = sorted({_curve_store_session_minute(ts_key) for ts_key in requested_keys})
        use_session_filter = _supports_irs_curve_store_session_minute_filter(mdp)

        raw_df = pd.DataFrame()
        if hasattr(store, "read_raw_nodes") and trading_dates:
            try:
                raw_kwargs = {
                    "start": trading_dates[0],
                    "end": trading_dates[-1],
                }
                if not _matches_irs_curve_store_on_trading_date(mdp):
                    raw_kwargs["timestamps_utc"] = requested_keys
                if use_session_filter and len(session_minutes) <= 3:
                    raw_kwargs["session_minute_min"] = session_minutes[0]
                    raw_kwargs["session_minute_max"] = session_minutes[-1]
                raw_df = store.read_raw_nodes(
                    resolved_curve_name,
                    **raw_kwargs,
                )
            except TypeError:
                raw_df = store.read_raw_nodes(
                    resolved_curve_name,
                    start=trading_dates[0],
                    end=trading_dates[-1],
                )

        if raw_df is not None and not raw_df.empty:
            return raw_df

        if hasattr(store, "read_raw_day"):
            day_frames: List[pd.DataFrame] = []
            for trading_date in trading_dates:
                try:
                    day_df = store.read_raw_day(resolved_curve_name, trading_date)
                except Exception:
                    continue
                if day_df is not None and not day_df.empty:
                    day_frames.append(day_df)
            if day_frames:
                return pd.concat(day_frames, ignore_index=True, sort=False)

        return pd.DataFrame()

    def _read_irs_curve_store_vectorized_rows(
        self,
        *,
        mdp: Optional[Any],
        store: Any,
        resolved_curve_name: str,
        requested_curve_name: str,
        queries: List[IRSwapQuery],
        candidate_ref_points: Sequence[DateLike],
        requested_key_by_ref: Mapping[DateLike, datetime.datetime],
        covered: set[Tuple[DateLike, int]],
        allow_multi_leg: bool,
    ) -> Tuple[
        List[Tuple[DateLike, str, float]],
        set[Tuple[DateLike, int]],
        Dict[int, List[Tuple[DateLike, str, float]]],
    ]:
        if not candidate_ref_points or not _matches_irs_curve_store_on_trading_date(mdp):
            return [], set(), {}

        try:
            from Caching.eod_vectorized_engine import compute_eod_rate_panel, parse_tenor
        except ImportError:
            return [], set(), {}

        eligible: List[Tuple[int, IRSwapQuery, list[tuple[float, str]]]] = []
        required_tenors: set[str] = set()
        for idx, q in enumerate(queries):
            if all((ref_point, idx) in covered for ref_point in candidate_ref_points):
                continue
            components = _analytics_rate_components(q)
            if not components:
                continue
            if not allow_multi_leg and len(components) > 1:
                continue

            normalized_components: list[tuple[float, str]] = []
            skip_query = False
            for weight, token in components:
                tenor_token = str(token or "").strip().upper()
                if not tenor_token:
                    skip_query = True
                    break
                try:
                    parse_tenor(tenor_token)
                except Exception:
                    skip_query = True
                    break
                normalized_components.append((float(weight), tenor_token))
                required_tenors.add(tenor_token)
            if skip_query or not normalized_components:
                continue
            eligible.append((idx, q, normalized_components))

        if not eligible or not required_tenors:
            return [], set(), {}

        requested_keys = [
            requested_key_by_ref[ref_point]
            for ref_point in candidate_ref_points
            if ref_point in requested_key_by_ref
        ]
        raw_df = self._read_irs_curve_store_raw_df(
            mdp=mdp,
            store=store,
            resolved_curve_name=resolved_curve_name,
            requested_keys=requested_keys,
        )
        if raw_df.empty:
            return [], set(), {}

        panel = compute_eod_rate_panel(
            raw_nodes_df=raw_df,
            tenors=sorted(required_tenors),
        )
        if panel.empty:
            return [], set(), {}

        rows: List[Tuple[DateLike, str, float]] = []
        vectorized_covered: set[Tuple[DateLike, int]] = set()
        rows_by_query_idx: Dict[int, List[Tuple[DateLike, str, float]]] = defaultdict(list)
        for ref_point in candidate_ref_points:
            panel_key = pd.Timestamp(_ref_point_date(ref_point))
            if panel_key not in panel.index:
                continue
            for idx, q, components in eligible:
                if (ref_point, idx) in covered or (ref_point, idx) in vectorized_covered:
                    continue
                total = 0.0
                for weight, tenor_token in components:
                    if tenor_token not in panel.columns:
                        total = float("nan")
                        break
                    rate_value = panel.at[panel_key, tenor_token]
                    if pd.isna(rate_value):
                        total = float("nan")
                        break
                    total += float(weight) * float(rate_value)
                if np.isnan(total):
                    continue
                scale = 100.0 if len(components) == 1 else 10_000.0
                default = f"{requested_curve_name}.{getattr(q, 'tenor', '')}.{IRSwapValue.RATE.name}"
                row = (ref_point, _safe_col_name(q, default), total * scale)
                rows.append(row)
                rows_by_query_idx[idx].append(row)
                vectorized_covered.add((ref_point, idx))

        return rows, vectorized_covered, rows_by_query_idx

    def _build_irs_curve_store_curve_map(
        self,
        *,
        mdp: Any,
        store: Any,
        builder: Any,
        requested_curve_name: str,
        resolved_curve_name: str,
        reference_points: List[DateLike],
        requested_key_by_ref: Mapping[DateLike, datetime.datetime],
        n_jobs: Optional[int],
        progress_callback: Optional[Callable[[int], None]] = None,
    ) -> Dict[DateLike, Any]:
        if not reference_points:
            return {}

        raw_df = self._read_irs_curve_store_raw_df(
            mdp=mdp,
            store=store,
            resolved_curve_name=resolved_curve_name,
            requested_keys=list(requested_key_by_ref.values()),
        )
        if raw_df.empty or "timestamp_utc" not in raw_df.columns:
            return {}

        if _matches_irs_curve_store_on_trading_date(mdp) and "trading_date" in raw_df.columns:
            requested_trading_dates = {
                _curve_store_trading_date(ts_key)
                for ts_key in requested_key_by_ref.values()
            }
            trading_dates = raw_df["trading_date"].map(_normalize_trading_date)
            filtered_df = raw_df.loc[trading_dates.isin(requested_trading_dates)].copy()
        else:
            requested_keys = set(requested_key_by_ref.values())
            ts_keys = raw_df["timestamp_utc"].map(_timestamp_utc_key)
            filtered_df = raw_df.loc[ts_keys.isin(requested_keys)].copy()
        if filtered_df.empty:
            return {}

        cfg = getattr(builder, "_STIRF_CURVE_CONFIGS", {}).get(resolved_curve_name)
        reconstruct_workers = _resolve_irs_curve_store_reconstruction_workers(
            n_jobs,
            task_count=len(filtered_df),
        )
        reconstruct_kwargs = {
            "cfg": cfg,
            "max_workers": reconstruct_workers,
        }
        if progress_callback is not None:
            reconstruct_kwargs["progress_callback"] = progress_callback
        try:
            curves_by_ts = store.reconstruct_curves_batch(
                filtered_df,
                **reconstruct_kwargs,
            )
        except TypeError:
            reconstruct_kwargs.pop("progress_callback", None)
            curves_by_ts = store.reconstruct_curves_batch(
                filtered_df,
                **reconstruct_kwargs,
            )
        curves_by_key = {
            key: curve
            for key, curve in (
                (_timestamp_utc_key(ts_val), curve_val)
                for ts_val, curve_val in curves_by_ts.items()
            )
            if key is not None
        }

        wrapped_by_key: Dict[Any, Any] = {}
        fixings_cache: Dict[tuple, pd.Series] = {}
        use_trading_date_match = _matches_irs_curve_store_on_trading_date(mdp)
        trading_date_by_ts_key = {}
        if use_trading_date_match and "trading_date" in filtered_df.columns:
            for row in filtered_df.itertuples(index=False):
                ts_key = _timestamp_utc_key(getattr(row, "timestamp_utc", None))
                trading_date = _normalize_trading_date(getattr(row, "trading_date", None))
                if ts_key is not None and trading_date is not None:
                    trading_date_by_ts_key[ts_key] = trading_date
        for ref_point in reference_points:
            ts_key = requested_key_by_ref.get(ref_point)
            if ts_key is None:
                continue
            cache_key: Any = _curve_store_trading_date(ts_key) if use_trading_date_match else ts_key
            if cache_key not in wrapped_by_key:
                rl_curve_handle = None
                if use_trading_date_match:
                    requested_trading_date = _curve_store_trading_date(ts_key)
                    for candidate_ts_key, candidate_curve in curves_by_key.items():
                        if trading_date_by_ts_key.get(candidate_ts_key) == requested_trading_date:
                            rl_curve_handle = candidate_curve
                            break
                else:
                    rl_curve_handle = curves_by_key.get(ts_key)
                if rl_curve_handle is None:
                    continue
                wrapped_by_key[cache_key] = mdp._wrap_curve_store_curve(
                    requested_curve_name=requested_curve_name,
                    resolved_curve_name=resolved_curve_name,
                    request_timestamp=ref_point,
                    rl_curve_handle=rl_curve_handle,
                    builder=builder,
                    fixings_cache=fixings_cache,
                )
        return {
            ref_point: wrapped_by_key[(_curve_store_trading_date(ts_key) if use_trading_date_match else ts_key)]
            for ref_point, ts_key in requested_key_by_ref.items()
            if (_curve_store_trading_date(ts_key) if use_trading_date_match else ts_key) in wrapped_by_key
        }

    def _fallback_timeseries_for_missing_points(
        self,
        *,
        product: str,
        queries: List[BaseQuery],
        router: Optional[object],
        mdp: Optional[MarketDataProvider],
        start: DateLike,
        end: DateLike,
        missing_points: List[DateLike],
        n_jobs: Optional[int],
        ignore_cache: Optional[bool],
        freq: Optional[str],
    ) -> pd.DataFrame:
        if not missing_points:
            return pd.DataFrame().set_index(pd.Index([], name=self._date_col))

        fallback_tb = router if router is not None else (self._get_generic_router(product, mdp) if mdp is not None else None)
        if fallback_tb is None:
            return pd.DataFrame().set_index(pd.Index([], name=self._date_col))

        if all(isinstance(point, datetime.datetime) for point in missing_points):
            return fallback_tb.get_timeseries(  # type: ignore[attr-defined]
                start,
                end,
                queries,
                n_jobs=n_jobs,
                ignore_cache=ignore_cache,
                freq=freq,
                timestamps=sorted(missing_points),
            )

        date_points = sorted(set(
            point if isinstance(point, datetime.date) and not isinstance(point, datetime.datetime) else point.date()
            for point in missing_points
        ))

        # Group consecutive dates into tight ranges so the fallback router
        # doesn't re-process the entire original date span for a few gaps.
        ranges: List[Tuple[datetime.date, datetime.date]] = []
        range_start = date_points[0]
        prev = range_start
        for d in date_points[1:]:
            if (d - prev).days > 5:
                ranges.append((range_start, prev))
                range_start = d
            prev = d
        ranges.append((range_start, prev))

        frames: List[pd.DataFrame] = []
        for rs, re in ranges:
            try:
                chunk = fallback_tb.get_timeseries(  # type: ignore[attr-defined]
                    rs, re, queries,
                    n_jobs=n_jobs, ignore_cache=ignore_cache, freq=None, timestamps=None,
                )
                if not chunk.empty:
                    frames.append(chunk)
            except Exception:
                continue
        if not frames:
            return pd.DataFrame().set_index(pd.Index([], name=self._date_col))
        fallback_df = pd.concat(frames, axis=0).sort_index()
        fallback_df = fallback_df[~fallback_df.index.duplicated(keep="last")]
        return fallback_df.reindex(pd.Index(date_points, name=fallback_df.index.name or self._date_col))

    def _execute_irs_curve_store_plan(
        self,
        *,
        plan: _ProductTimeseriesPlan,
        start: DateLike,
        end: DateLike,
        n_jobs: Optional[int],
        ignore_cache: Optional[bool],
        freq: Optional[str],
        timestamps: Optional[List[datetime.datetime]],
        use_irs_vectorized_pricing: bool,
    ) -> pd.DataFrame:
        if plan.mdp is None:
            return pd.DataFrame().set_index(pd.Index([], name=self._date_col))

        from TB.IRSwapsTB import _build_row_for_query as _build_irs_row_for_query
        from TB.IRSwapsTB import _group_queries_by_curve as _group_irs_queries_by_curve

        mdp = plan.mdp
        queries = [q for q in plan.queries if isinstance(q, IRSwapQuery)]
        reference_points = _filter_irs_reference_points_for_mdp(
            _build_reference_points(start=start, end=end, freq=freq, timestamps=timestamps),
            mdp=mdp,
        )
        if not queries or not reference_points:
            return pd.DataFrame().set_index(pd.Index([], name=self._date_col))
        use_intraday_cache = any(isinstance(point, datetime.datetime) for point in reference_points)

        store = mdp._get_curve_store()
        builder = mdp._get_curve_store_builder() if hasattr(mdp, "_get_curve_store_builder") else None
        generic_tb = self._get_generic_router("IRS", mdp)
        curve_frames: List[pd.DataFrame] = []
        pbar_disable = not getattr(plan.router, "_show_tqdm", True)

        def _run_stage(desc: str, total: int, fn):
            with _tqdm(total=max(1, int(total)), disable=pbar_disable, desc=desc, leave=True) as pbar:
                result = fn()
                pbar.update(max(1, int(total)))
                return result

        for requested_curve_name, curve_queries in _group_irs_queries_by_curve(queries).items():
            curve_reference_points = _filter_irs_curve_store_reference_points(
                reference_points,
                requested_curve_name=requested_curve_name,
            )
            if not curve_reference_points:
                continue

            def _log_curve_stage(stage_name: str, started_at: float, **metrics: Any) -> None:
                if not _LOGGER.isEnabledFor(logging.DEBUG):
                    return
                metric_items = [f"{key}={value}" for key, value in metrics.items()]
                metric_suffix = f" ({', '.join(metric_items)})" if metric_items else ""
                _LOGGER.debug(
                    "IRS curve-store %s for %s took %.3fs%s",
                    stage_name,
                    requested_curve_name,
                    time.perf_counter() - started_at,
                    metric_suffix,
                )

            def _curve_for_ref_point(curves_by_ref: Mapping[Any, Any], ref_point: DateLike) -> Any:
                curve = curves_by_ref.get(ref_point)
                if curve is None and isinstance(ref_point, datetime.date) and not isinstance(ref_point, datetime.datetime):
                    if ref_point == datetime.date.today():
                        curve = curves_by_ref.get("live")
                return curve

            rows: List[Tuple[DateLike, str, float]] = []
            newly_computed_rows: Dict[int, List[Tuple[DateLike, str, float]]] = defaultdict(list)

            def _price_curve_map(
                *,
                candidate_ref_points: Sequence[DateLike],
                curves_by_ref: Mapping[Any, Any],
                source_desc: str,
            ) -> int:
                tasks: List[Tuple[int, DateLike, IRSwapQuery, Any]] = []
                for ref_point in candidate_ref_points:
                    curve = _curve_for_ref_point(curves_by_ref, ref_point)
                    if curve is None:
                        continue
                    for idx, q in enumerate(curve_queries):
                        if (ref_point, idx) in covered:
                            continue
                        tasks.append((idx, ref_point, q, curve))

                if not tasks:
                    return 0

                worker_count = _resolve_irs_curve_store_reconstruction_workers(
                    n_jobs,
                    task_count=len(tasks),
                )
                with _tqdm(
                    total=len(tasks),
                    disable=pbar_disable,
                    desc=f"PRICING {requested_curve_name} IRSWAPS [{source_desc}, workers={worker_count}]...",
                    leave=True,
                ) as pbar:
                    if worker_count > 1 and len(tasks) > 1:
                        with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="ts-irs-curve-store") as pool:
                            future_map = {
                                pool.submit(_build_irs_row_for_query, curve, q, ref_point, self._date_col): (ref_point, idx)
                                for idx, ref_point, q, curve in tasks
                            }
                            for future in as_completed(future_map):
                                ref_point, idx = future_map[future]
                                try:
                                    row = future.result()
                                    rows.append(row)
                                    covered.add((ref_point, idx))
                                    newly_computed_rows[idx].append(row)
                                except Exception:
                                    continue
                                finally:
                                    pbar.update(1)
                    else:
                        for idx, ref_point, q, curve in tasks:
                            try:
                                row = _build_irs_row_for_query(curve, q, ref_point, self._date_col)
                                rows.append(row)
                                covered.add((ref_point, idx))
                                newly_computed_rows[idx].append(row)
                            except Exception:
                                continue
                            finally:
                                pbar.update(1)

                return len(tasks)

            cached_started = time.perf_counter()
            cached_rows, covered = _run_stage(
                desc=f"READING {requested_curve_name} computed cache...",
                total=len(curve_queries),
                fn=lambda: self._read_irs_computed_cache_rows(
                    router=plan.router,
                    requested_curve_name=requested_curve_name,
                    queries=curve_queries,
                    reference_points=curve_reference_points,
                    intraday=use_intraday_cache,
                ),
            )
            rows.extend(cached_rows)
            _log_curve_stage(
                "computed cache read",
                cached_started,
                rows=len(cached_rows),
                covered=len(covered),
                ref_points=len(curve_reference_points),
                queries=len(curve_queries),
            )
            if _is_curve_coverage_complete(
                reference_points=curve_reference_points,
                query_count=len(curve_queries),
                covered=covered,
            ):
                frame_started = time.perf_counter()
                curve_df = generic_tb._rows_to_frame(rows)
                _log_curve_stage("frame assembly", frame_started, rows=len(rows), shape=getattr(curve_df, "shape", None))
                if not curve_df.empty:
                    curve_frames.append(curve_df)
                continue

            anchor_req = dict(curve_queries[0].build_mdp_request(
                curve_reference_points[0]
                if isinstance(curve_reference_points[0], datetime.datetime)
                else datetime.datetime.combine(curve_reference_points[0], datetime.time())
            ))
            anchor_req.pop(str(getattr(curve_queries[0], "mdp_time_key", "timestamp") or "timestamp"), None)
            anchor_req.pop("curve_name", None)
            resolved_curve_name = mdp._resolve_curve_store_curve_name(
                requested_curve_name=requested_curve_name,
                kwargs=anchor_req,
                builder=builder,
            )

            requested_key_by_ref: Dict[DateLike, datetime.datetime] = {}
            for ref_point in curve_reference_points:
                rl_timestamp = mdp._to_curve_store_timestamp(ref_point)
                if rl_timestamp == "live":
                    continue
                ts_key = _timestamp_utc_key(rl_timestamp)
                if ts_key is None:
                    continue
                requested_key_by_ref[ref_point] = ts_key

            if not requested_key_by_ref:
                fallback_df = self._fallback_timeseries_for_missing_points(
                    product="IRS",
                    queries=curve_queries,
                    router=plan.router,
                    mdp=mdp,
                    start=start,
                    end=end,
                    missing_points=curve_reference_points,
                    n_jobs=n_jobs,
                    ignore_cache=ignore_cache,
                    freq=freq,
                )
                if not fallback_df.empty:
                    curve_frames.append(fallback_df)
                continue

            analytics_rows: List[Tuple[DateLike, str, float]] = []
            analytics_covered: set[Tuple[DateLike, int]] = set()
            if _supports_irs_curve_store_analytics_fast_path(mdp):
                analytics_started = time.perf_counter()
                analytics_rows, analytics_covered = _run_stage(
                    desc=f"READING {requested_curve_name} curve analytics...",
                    total=len(curve_reference_points),
                    fn=lambda: self._read_irs_curve_store_analytics_rows(
                        mdp=mdp,
                        store=store,
                        resolved_curve_name=resolved_curve_name,
                        requested_curve_name=requested_curve_name,
                        queries=curve_queries,
                        requested_key_by_ref=requested_key_by_ref,
                    ),
                )
                _log_curve_stage(
                    "analytics read",
                    analytics_started,
                    rows=len(analytics_rows),
                    covered=len(analytics_covered),
                )
            rows.extend(analytics_rows)
            covered.update(analytics_covered)

            if _is_curve_coverage_complete(
                reference_points=curve_reference_points,
                query_count=len(curve_queries),
                covered=covered,
            ):
                frame_started = time.perf_counter()
                curve_df = generic_tb._rows_to_frame(rows)
                _log_curve_stage("frame assembly", frame_started, rows=len(rows), shape=getattr(curve_df, "shape", None))
                if not curve_df.empty:
                    curve_frames.append(curve_df)
                continue

            # Only load raw curves for reference points that still need pricing
            uncovered_ref_points = [
                rp for rp in curve_reference_points
                if any((rp, idx) not in covered for idx in range(len(curve_queries)))
            ]
            uncovered_key_by_ref = {
                rp: ts_key for rp, ts_key in requested_key_by_ref.items()
                if rp in set(uncovered_ref_points)
            }

            # --- Vectorized EOD fast path for uncovered tenors ---
            if (
                uncovered_ref_points
                and _matches_irs_curve_store_on_trading_date(mdp)
            ):
                try:
                    vec_start = time.perf_counter()
                    vectorized_rows, vectorized_covered, vectorized_rows_by_query_idx = _run_stage(
                        desc=f"VECTOR PRICING {requested_curve_name} IRS...",
                        total=len(uncovered_ref_points),
                        fn=lambda: self._read_irs_curve_store_vectorized_rows(
                            mdp=mdp,
                            store=store,
                            resolved_curve_name=resolved_curve_name,
                            requested_curve_name=requested_curve_name,
                            queries=curve_queries,
                            candidate_ref_points=uncovered_ref_points,
                            requested_key_by_ref=uncovered_key_by_ref,
                            covered=covered,
                            allow_multi_leg=use_irs_vectorized_pricing,
                        ),
                    )
                    rows.extend(vectorized_rows)
                    covered.update(vectorized_covered)
                    for idx, idx_rows in vectorized_rows_by_query_idx.items():
                        newly_computed_rows[idx].extend(idx_rows)
                    _log_curve_stage(
                        "vectorized EOD",
                        vec_start,
                        rows=len(vectorized_rows),
                        covered=len(vectorized_covered),
                    )
                except Exception:
                    _LOGGER.debug("Vectorized EOD fallback failed", exc_info=True)

            # Recompute uncovered after vectorized path
            uncovered_ref_points = [
                rp for rp in curve_reference_points
                if any((rp, idx) not in covered for idx in range(len(curve_queries)))
            ]

            curve_map: Dict[DateLike, Any] = {}
            if _supports_irs_curve_store_raw_curve_fast_path(mdp) and uncovered_ref_points:
                raw_curve_started = time.perf_counter()
                raw_curve_total = len(uncovered_ref_points)
                with _tqdm(
                    total=max(1, raw_curve_total),
                    disable=pbar_disable,
                    desc=f"LOADING {requested_curve_name} raw curves...",
                    leave=True,
                ) as pbar:
                    raw_curve_progress = 0

                    def _update_raw_curve_progress(step: int = 1) -> None:
                        nonlocal raw_curve_progress
                        step = max(0, int(step or 0))
                        remaining = max(0, raw_curve_total - raw_curve_progress)
                        applied = min(step, remaining)
                        if applied <= 0:
                            return
                        raw_curve_progress += applied
                        pbar.update(applied)

                    curve_map = self._build_irs_curve_store_curve_map(
                        mdp=mdp,
                        store=store,
                        builder=builder,
                        requested_curve_name=requested_curve_name,
                        resolved_curve_name=resolved_curve_name,
                        reference_points=uncovered_ref_points,
                        requested_key_by_ref=uncovered_key_by_ref,
                        n_jobs=n_jobs,
                        progress_callback=_update_raw_curve_progress,
                    )
                    if raw_curve_progress < raw_curve_total:
                        pbar.update(raw_curve_total - raw_curve_progress)
                _log_curve_stage(
                    "raw curve reconstruction",
                    raw_curve_started,
                    requested=len(uncovered_ref_points),
                    recovered=len(curve_map),
                )

            curve_store_pricing_started = time.perf_counter()
            curve_store_priced = _price_curve_map(
                candidate_ref_points=uncovered_ref_points,
                curves_by_ref=curve_map,
                source_desc="curve-store",
            )
            _log_curve_stage(
                "curve-store pricing",
                curve_store_pricing_started,
                tasks=curve_store_priced,
                covered=len(covered),
            )

            missing_points = [
                ref_point
                for ref_point in curve_reference_points
                if any((ref_point, idx) not in covered for idx in range(len(curve_queries)))
            ]

            direct_recovery_curves: Dict[DateLike, Any] = {}
            if missing_points:
                direct_recovery_started = time.perf_counter()
                recovered_curve_map: Mapping[Any, Any]
                try:
                    recovered_curve_map = mdp.bulk_get_data(
                        {
                            "curve_name": requested_curve_name,
                            "timestamps": sorted(missing_points),
                            "ignore_cache": ignore_cache,
                            "n_jobs": n_jobs,
                        }
                    )
                except Exception:
                    recovered_curve_map = {}
                    _LOGGER.debug(
                        "IRS curve-store direct miss recovery fetch failed for %s",
                        requested_curve_name,
                        exc_info=True,
                    )

                for ref_point in missing_points:
                    curve = _curve_for_ref_point(recovered_curve_map, ref_point)
                    if curve is not None:
                        direct_recovery_curves[ref_point] = curve

                _log_curve_stage(
                    "direct miss recovery fetch",
                    direct_recovery_started,
                    requested=len(missing_points),
                    recovered=len(direct_recovery_curves),
                )

            if direct_recovery_curves:
                direct_pricing_started = time.perf_counter()
                direct_priced = _price_curve_map(
                    candidate_ref_points=missing_points,
                    curves_by_ref=direct_recovery_curves,
                    source_desc="mdp-direct",
                )
                _log_curve_stage(
                    "direct miss recovery",
                    direct_pricing_started,
                    tasks=direct_priced,
                    covered=len(covered),
                )

            new_row_count = sum(len(v) for v in newly_computed_rows.values())
            if new_row_count > 0:
                write_started = time.perf_counter()
                _run_stage(
                    desc=f"WRITING {requested_curve_name} computed cache...",
                    total=new_row_count,
                    fn=lambda: self._write_irs_computed_cache_rows(
                        router=plan.router,
                        requested_curve_name=requested_curve_name,
                        rows_by_query_idx=newly_computed_rows,
                        queries=curve_queries,
                    ),
                )
                _log_curve_stage("computed cache write", write_started, rows=new_row_count)

            missing_points = [
                ref_point
                for ref_point in curve_reference_points
                if any((ref_point, idx) not in covered for idx in range(len(curve_queries)))
            ]
            fallback_started = time.perf_counter()
            fallback_df = self._fallback_timeseries_for_missing_points(
                product="IRS",
                queries=curve_queries,
                router=plan.router,
                mdp=mdp,
                start=start,
                end=end,
                missing_points=missing_points,
                n_jobs=n_jobs,
                ignore_cache=ignore_cache,
                freq=freq,
            )
            _log_curve_stage(
                "final router fallback",
                fallback_started,
                missing=len(missing_points),
                fallback_shape=getattr(fallback_df, "shape", None),
            )
            frame_started = time.perf_counter()
            direct_df = generic_tb._rows_to_frame(rows)
            curve_df = direct_df.combine_first(fallback_df) if not fallback_df.empty else direct_df
            _log_curve_stage(
                "frame assembly",
                frame_started,
                rows=len(rows),
                direct_shape=getattr(direct_df, "shape", None),
                fallback_shape=getattr(fallback_df, "shape", None),
                final_shape=getattr(curve_df, "shape", None),
            )
            if not curve_df.empty:
                curve_frames.append(curve_df)

        if not curve_frames:
            return pd.DataFrame().set_index(pd.Index([], name=self._date_col))
        final_frame_started = time.perf_counter()
        out = pd.concat(curve_frames, axis=1).sort_index()
        out.index.name = self._date_col
        out = self._strip_redundant_date_column(out)
        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug(
                "IRS curve-store final frame assembly took %.3fs (curve_frames=%d, shape=%s)",
                time.perf_counter() - final_frame_started,
                len(curve_frames),
                getattr(out, "shape", None),
            )
        return out

    def get_timeseries(
        self,
        start: DateLike,
        end: DateLike,
        queries: List[Union[BaseQuery, List[BaseQuery]]],
        *,
        n_jobs: Optional[int] = 1,
        ignore_cache: Optional[bool] = False,
        freq: Optional[str] = None,
        timestamps: Optional[List[datetime.datetime]] = None,
        drop_multilevel_cols: Optional[bool] = True,
        routers: Optional[Mapping[str, Any]] = None,
        mdps: Optional[Mapping[str, MarketDataProvider]] = None,
        use_irs_vectorized_pricing: bool = False,
        use_duckdb: Optional[bool] = None,
        duckdb_path: Optional[str] = None,
    ) -> pd.DataFrame:
        assert start <= end, "must have end > start"
        flat = _flatten_base_queries(queries)

        merged_routers: Dict[str, Any] = dict(self._routers)
        if routers:
            merged_routers.update(routers)
        merged_mdps: Dict[str, MarketDataProvider] = dict(mdps or {})

        if (
            (use_duckdb is not None or duckdb_path is not None)
            and merged_routers.get("IRS") is None
            and merged_mdps.get("IRS") is not None
            and any(isinstance(q, IRSwapQuery) for q in flat)
        ):
            from TB.IRSwapsTB import IRSwapsTB

            merged_routers["IRS"] = IRSwapsTB(
                mdp=merged_mdps["IRS"],  # type: ignore[arg-type]
                date_col=self._date_col,
                show_tqdm=True,
                use_duckdb=True if use_duckdb is None else bool(use_duckdb),
                duckdb_path=duckdb_path,
            )

        per_product_frames: List[Tuple[str, pd.DataFrame]] = []
        request_plan = self._build_request_plan(
            flat_queries=flat,
            merged_routers=merged_routers,
            merged_mdps=merged_mdps,
            start=start,
            end=end,
            ignore_cache=ignore_cache,
            freq=freq,
            timestamps=timestamps,
        )

        for product, df in self._execute_product_plans(
            plan=request_plan,
            merged_routers=merged_routers,
            merged_mdps=merged_mdps,
            start=start,
            end=end,
            n_jobs=n_jobs,
            ignore_cache=ignore_cache,
            freq=freq,
            timestamps=timestamps,
            use_irs_vectorized_pricing=use_irs_vectorized_pricing,
        ):
            self._append_product_frame(per_product_frames, product=product, df=df)

        irs_router = merged_routers.get("IRS")
        frb_router = merged_routers.get("FRB")
        spread_mdp = self._get_irswap_spreads_mdp(merged_mdps)

        if request_plan.irswap_spread_queries:
            mdp_spread_queries = [
                q
                for q in request_plan.irswap_spread_queries
                if spread_mdp is not None or q.value in _IRSWAP_ADJUSTED_SPREAD_VALUES
            ]
            fallback_spread_queries = [
                q for q in request_plan.irswap_spread_queries
                if q not in mdp_spread_queries
            ]

            effective_spread_mdp = spread_mdp
            if mdp_spread_queries and effective_spread_mdp is None:
                if irs_router is None or frb_router is None:
                    raise KeyError("IRS/FRB routers must be registered for adjusted swap spread evaluation.")
                from MDP.IRSwapSpreads.IRSwapSpreadsMDP import IRSwapSpreadsMDP

                effective_spread_mdp = IRSwapSpreadsMDP(
                    _irs_mdp=getattr(irs_router, "mdp", None),
                    _frb_mdp=getattr(frb_router, "mdp", None),
                )

            if mdp_spread_queries and effective_spread_mdp is not None:
                spread_df = self._price_irswap_spread_queries_with_mdp(
                    mdp=effective_spread_mdp,
                    queries=list(mdp_spread_queries),
                    start=start,
                    end=end,
                    freq=freq,
                    timestamps=timestamps,
                    desc="PRICING SWAP SPREADS...",
                )
                if not spread_df.empty:
                    per_product_frames.append(("SWAPSPREADS", pd.concat({"SWAPSPREADS": spread_df}, axis=1)))
            if fallback_spread_queries:
                if irs_router is None or frb_router is None:
                    raise KeyError("IRS/FRB routers must be registered for MMSS/SPREADOVER evaluation.")

                irss_frb_qs = []
                irrs_irs_qs = []
                pair_specs = []

                _CT_RE = re.compile(r"(?i)\bct\s*(\d+)\b")
                _Y_RE = re.compile(r"(?i)\b(\d+)\s*y\b")

                for q in fallback_spread_queries:
                    if q.value == IRSwapValue.MMSS:
                        q_frb = FixedRateBondQuery(cusip=q.tenor, value=FixedRateBondValue.YTM)
                        q_irs = IRSwapQuery(curve=q.curve, tenor=q.tenor, value=IRSwapValue.RATE)
                        op = "swap_minus_cash"
                    elif q.value == IRSwapValue.SPREADOVER:
                        t = str(q.tenor)
                        if _CT_RE.search(t):
                            q_frb = FixedRateBondQuery(cusip=t, value=FixedRateBondValue.YTM)
                            q_irs = IRSwapQuery(curve=q.curve, tenor=_ct_alias_to_y(t), value=IRSwapValue.RATE)
                        elif _Y_RE.search(t):
                            q_frb = FixedRateBondQuery(cusip=_y_alias_to_ct(t), value=FixedRateBondValue.YTM)
                            q_irs = IRSwapQuery(curve=q.curve, tenor=t, value=IRSwapValue.RATE)
                        else:
                            raise NotImplementedError(f"Unrecognized SPREADOVER tenor: {t!r}")
                        op = "swap_minus_cash"
                    else:
                        raise NotImplementedError(f"Unhandled spread type: {q.value}")

                    irss_frb_qs.append(q_frb)
                    irrs_irs_qs.append(q_irs)

                    irs_col = _safe_col_name(
                        q_irs,
                        f"{getattr(q_irs,'curve','IRS')}.{getattr(q_irs,'tenor','')}.{IRSwapValue.RATE.name}",
                    )
                    frb_col = _safe_col_name(
                        q_frb,
                        f"{getattr(q_frb,'cusip','CUSIP')}.{FixedRateBondValue.YTM.name}",
                    )
                    spread_name = _safe_col_name(
                        q,
                        f"{getattr(q,'curve','IRS')}.{getattr(q,'tenor','')}.{getattr(q,'value',IRSwapValue.MMSS).name}",
                    )
                    pair_specs.append(
                        {
                            "spread_name": spread_name,
                            "irs_col": irs_col,
                            "frb_col": frb_col,
                            "op": op,
                        }
                    )

                irs_intraday_timestamps = self._prepare_product_intraday_timestamps(
                    product="IRS",
                    mdp=getattr(irs_router, "mdp", None),
                    start=start,
                    end=end,
                    freq=freq,
                    timestamps=timestamps,
                )
                if irs_intraday_timestamps is not None and not irs_intraday_timestamps:
                    irs_df = pd.DataFrame().set_index(pd.Index([], name=self._date_col))
                    cash_df = pd.DataFrame().set_index(pd.Index([], name=self._date_col))
                else:
                    component_freq = None if irs_intraday_timestamps is not None else freq
                    component_timestamps = irs_intraday_timestamps if irs_intraday_timestamps is not None else timestamps

                    def _fetch_component_frame(router: Any, component_queries: List[BaseQuery]) -> pd.DataFrame:
                        return router.get_timeseries(  # type: ignore[attr-defined]
                            start,
                            end,
                            component_queries,
                            n_jobs=n_jobs,
                            ignore_cache=ignore_cache,
                            freq=component_freq,
                            timestamps=component_timestamps,
                        )

                    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="ts-swap-spread") as pool:
                        future_to_component = {
                            pool.submit(_fetch_component_frame, irs_router, irrs_irs_qs): "IRS",
                            pool.submit(_fetch_component_frame, frb_router, irss_frb_qs): "FRB",
                        }
                        component_frames: Dict[str, pd.DataFrame] = {}
                        for future in as_completed(future_to_component):
                            component_frames[future_to_component[future]] = future.result()

                    irs_df = component_frames["IRS"]
                    cash_df = component_frames["FRB"]

                spread_cols: Dict[str, pd.Series] = {}
                idx = irs_df.index.union(cash_df.index)
                for spec in pair_specs:
                    a = irs_df[spec["irs_col"]].reindex(idx) if spec["irs_col"] in irs_df.columns else pd.Series(index=idx, dtype="float64")
                    b = cash_df[spec["frb_col"]].reindex(idx) if spec["frb_col"] in cash_df.columns else pd.Series(index=idx, dtype="float64")
                    if spec["op"] == "swap_minus_cash":
                        if "outright" in str(spec["irs_col"]).lower():
                            spread = (a - b) * 100
                        else:
                            spread = a - b
                    else:
                        raise ValueError(f"Unknown op: {spec['op']}")
                    spread_cols[spec["spread_name"]] = spread

                if spread_cols:
                    spread_df = pd.DataFrame(spread_cols).sort_index()
                    spread_df.index.name = self._date_col
                    per_product_frames.append(("SWAPSPREADS", pd.concat({"SWAPSPREADS": spread_df}, axis=1)))

        if request_plan.irswap_asw_queries:
            if spread_mdp is not None:
                df = self._price_irswap_spread_queries_with_mdp(
                    mdp=spread_mdp,
                    queries=list(request_plan.irswap_asw_queries),
                    start=start,
                    end=end,
                    freq=freq,
                    timestamps=timestamps,
                    desc="PRICING ASSET SWAPS...",
                )
                if not df.empty:
                    self._append_product_frame(per_product_frames, product="IRS__ASW", df=df)
            else:
                if irs_router is None or frb_router is None:
                    raise KeyError("IRS/FRB routers must be registered for ASW evaluation.")

                irs_mdp = irs_router.mdp  # type: ignore[attr-defined]
                frb_mdp = frb_router.mdp  # type: ignore[attr-defined]

                ref_points = pd.bdate_range(start, end).date.tolist()
                rows = []
                for d in _tqdm(ref_points, desc="PRICING ASSET SWAPS..."):
                    for q in request_plan.irswap_asw_queries:
                        try:
                            curve = irs_mdp.get_pricer({"curve_name": q.curve, "timestamp": d})
                            ql_curve = curve

                            alias = str(q.tenor)
                            frb_pricers = frb_mdp.get_pricer({"cusips": [alias], "timestamp": d})
                            if not frb_pricers:
                                continue
                            frb_pricer = next(iter(frb_pricers.values()))

                            _ = getattr(ql_curve, "index")() if hasattr(ql_curve, "index") else None
                            asw_bps = _fair_asw_spread_bps(ql_curve, frb_pricer, par_par_asw=q.value == IRSwapValue.PAR_PAR_ASW)
                            col = _safe_col_name(q, default=f"ASW[{q.curve}:{alias}]")
                            rows.append((d, col, float(asw_bps)))
                        except Exception:
                            continue

                if rows:
                    df = pd.DataFrame(rows, columns=[self._date_col, "Column", "Value"]).pivot(index=self._date_col, columns="Column", values="Value").sort_index()
                    self._append_product_frame(per_product_frames, product="IRS__ASW", df=df)

        if not per_product_frames:
            return pd.DataFrame().set_index(pd.Index([], name=self._date_col))

        out = per_product_frames[0][1]
        for _, df in per_product_frames[1:]:
            out = out.join(df, how="outer")

        out = out.sort_index()
        out.index.name = self._date_col

        if drop_multilevel_cols:
            out.columns = out.columns.droplevel()

        return out

    def spline_spread_builder(
        self,
    ):
        pass


def _fair_asw_spread_bps(swap_pricer: _IRSwapGenericCurve, frb_pricer: _FixedRateBondGenericPricer, par_par_asw: bool = True) -> float:
    import QuantLib as ql
    from Query.IRSwaps.backends.quantlib.ql_curve_definitions_map import QUANTLIB_CURVE_DEFINITIONS
    from Query.IRSwaps.backends.quantlib.utils import datetime_to_ql_date
    from Query.IRSwaps.backends.quantlib.ql_curve_building_utils import build_discount_curve_from_nodes

    ql.Settings.instance().evaluationDate = datetime_to_ql_date(swap_pricer.reference_date())

    ql_aug55 = frb_pricer.build_fixed_rate_bond(
        issue_date=frb_pricer.issue_date(),
        maturity_date=frb_pricer.maturity_date(),
        coupon=frb_pricer.coupon(),
        notional=100,
    )

    ql_curve_handle = ql.YieldTermStructureHandle(
        build_discount_curve_from_nodes(
            swap_pricer.nodes(), ql_dc=ql.Actual360(), ql_cal=ql.UnitedStates(ql.UnitedStates.GovernmentBond), interpolation_algo="df_log_linear"
        )
    )
    ql_index: ql.SwapIndex = QUANTLIB_CURVE_DEFINITIONS["USD-SOFR-1D"]["ReferenceRate"](ql_curve_handle)
    fixings_dict = swap_pricer.index().to_dict()
    for d, f in fixings_dict.items():
        try:
            ql_index.addFixing(fixingDate=datetime_to_ql_date(d), fixing=f, forceOverwrite=True)
        except:
            continue

    swap = ql.AssetSwap(
        True,
        ql_aug55,
        frb_pricer.clean_price(),
        ql_index,
        0.0,
        ql.Schedule(
            datetime_to_ql_date(frb_pricer.issue_date()),
            datetime_to_ql_date(frb_pricer.maturity_date()),
            ql.Period(6, ql.Months),
            ql.UnitedStates(ql.UnitedStates.GovernmentBond),
            ql.ModifiedFollowing,
            ql.ModifiedFollowing,
            ql.DateGeneration.Forward,
            False,
        ),
        ql_index.dayCounter(),
        par_par_asw,
    )
    swap.setPricingEngine(ql.DiscountingSwapEngine(ql_curve_handle))

    fair = float(swap.fairSpread())
    return fair * 10_000
