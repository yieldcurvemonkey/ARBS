import datetime
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, DefaultDict, Dict, Iterable, List, Mapping, Optional, Tuple, Union

import pandas as pd
import pytz
from tqdm.auto import tqdm as _tqdm

from MDP.IRSwapSpreads.IRSwapSpreadsMDP import IRSwapSpreadsMDP
from MDP.MarketDataProvider import MarketDataProvider
from Query.Base.BaseQuery import BaseQuery
from Query.FixedRateBonds.FixedRateBondQuery import FixedRateBondQuery
from Query.FixedRateBonds.FixedRateBondValue import FixedRateBondValue
from Query.FixedRateBonds._FixedRateBondGenericPricer import _FixedRateBondGenericPricer
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


def _analytics_rate_components(q: IRSwapQuery) -> Optional[list[tuple[float, str]]]:
    if q.value != IRSwapValue.RATE:
        return None

    tenor_text = str(getattr(q, "tenor", "") or "").strip().upper().replace(" ", "")
    if not tenor_text:
        return None

    tokens = [tok for tok in tenor_text.split("/") if tok]
    tenor_re = re.compile(r"^\d+[DWMY]$")
    if not tokens or any((not tenor_re.match(tok)) or ("X" in tok) for tok in tokens):
        return None

    if len(tokens) == 1 and q.structure == IRSwapStructure.OUTRIGHT:
        return [(1.0, tokens[0])]
    if len(tokens) == 2 and q.structure == IRSwapStructure.CURVE:
        return [(-1.0, tokens[0]), (1.0, tokens[1])]
    if len(tokens) == 3 and q.structure == IRSwapStructure.FLY:
        return [(-1.0, tokens[0]), (2.0, tokens[1]), (-1.0, tokens[2])]
    return None


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
        if self._date_col in df.columns:
            df = df.set_index(self._date_col)
        per_product_frames.append((product, pd.concat({product: df}, axis=1)))

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
                    if q.value in [IRSwapValue.MMSS, IRSwapValue.SPREADOVER]:
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
        analytics_tenors = sorted({tenor for _idx, _q, components in eligible for _weight, tenor in components})
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
                    component_value = None
                    for metric_name in ("par_rate", "rate"):
                        col_name = f"{metric_name}_{tenor}"
                        if col_name in row.index and pd.notna(row[col_name]):
                            component_value = float(row[col_name]) * float(weight)
                            break
                    if component_value is None:
                        component_values = []
                        break
                    component_values.append(component_value)
                if not component_values:
                    continue
                default = f"{requested_curve_name}.{getattr(q, 'tenor', '')}.{IRSwapValue.RATE.name}"
                rows.append((ref_point, _safe_col_name(q, default), float(sum(component_values))))
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
            rows.extend(q_rows)
            covered.update((ref_point, idx) for ref_point, _col, _value in q_rows)
        return rows, covered

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

        for idx, rows in rows_by_query_idx.items():
            if not rows:
                continue
            q = queries[idx]
            try:
                computed_store.append_rows(
                    symbol=symbol_builder(requested_curve_name, q),
                    rows=rows,
                )
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
        curves_by_ts = store.reconstruct_curves_batch(
            filtered_df,
            cfg=cfg,
            max_workers=max(1, int(n_jobs or 1)),
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

        date_points = [
            point if isinstance(point, datetime.date) and not isinstance(point, datetime.datetime) else point.date()
            for point in missing_points
        ]
        fallback_df = fallback_tb.get_timeseries(  # type: ignore[attr-defined]
            min(date_points),
            max(date_points),
            queries,
            n_jobs=n_jobs,
            ignore_cache=ignore_cache,
            freq=None,
            timestamps=None,
        )
        return fallback_df.reindex(pd.Index(sorted(date_points), name=fallback_df.index.name or self._date_col))

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
            anchor_req = dict(curve_queries[0].build_mdp_request(
                reference_points[0] if isinstance(reference_points[0], datetime.datetime) else datetime.datetime.combine(reference_points[0], datetime.time())
            ))
            anchor_req.pop(str(getattr(curve_queries[0], "mdp_time_key", "timestamp") or "timestamp"), None)
            anchor_req.pop("curve_name", None)
            resolved_curve_name = mdp._resolve_curve_store_curve_name(
                requested_curve_name=requested_curve_name,
                kwargs=anchor_req,
                builder=builder,
            )

            requested_key_by_ref: Dict[DateLike, datetime.datetime] = {}
            for ref_point in reference_points:
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
                    missing_points=reference_points,
                    n_jobs=n_jobs,
                    ignore_cache=ignore_cache,
                    freq=freq,
                )
                if not fallback_df.empty:
                    curve_frames.append(fallback_df)
                continue

            cached_rows, covered = _run_stage(
                desc=f"READING {requested_curve_name} computed cache...",
                total=len(curve_queries),
                fn=lambda: self._read_irs_computed_cache_rows(
                    router=plan.router,
                    requested_curve_name=requested_curve_name,
                    queries=curve_queries,
                    reference_points=reference_points,
                    intraday=use_intraday_cache,
                ),
            )
            analytics_rows: List[Tuple[DateLike, str, float]] = []
            analytics_covered: set[Tuple[DateLike, int]] = set()
            if _supports_irs_curve_store_analytics_fast_path(mdp):
                analytics_rows, analytics_covered = _run_stage(
                    desc=f"READING {requested_curve_name} curve analytics...",
                    total=len(reference_points),
                    fn=lambda: self._read_irs_curve_store_analytics_rows(
                        mdp=mdp,
                        store=store,
                        resolved_curve_name=resolved_curve_name,
                        requested_curve_name=requested_curve_name,
                        queries=curve_queries,
                        requested_key_by_ref=requested_key_by_ref,
                    ),
                )
            rows = list(cached_rows) + list(analytics_rows)
            covered.update(analytics_covered)

            if all((ref_point, idx) in covered for idx in range(len(curve_queries)) for ref_point in reference_points):
                curve_df = generic_tb._rows_to_frame(rows)
                if not curve_df.empty:
                    curve_frames.append(curve_df)
                continue

            curve_map: Dict[DateLike, Any] = {}
            if _supports_irs_curve_store_raw_curve_fast_path(mdp):
                curve_map = _run_stage(
                    desc=f"LOADING {requested_curve_name} raw curves...",
                    total=len(reference_points),
                    fn=lambda: self._build_irs_curve_store_curve_map(
                        mdp=mdp,
                        store=store,
                        builder=builder,
                        requested_curve_name=requested_curve_name,
                        resolved_curve_name=resolved_curve_name,
                        reference_points=reference_points,
                        requested_key_by_ref=requested_key_by_ref,
                        n_jobs=n_jobs,
                    ),
                )

            newly_computed_rows: Dict[int, List[Tuple[DateLike, str, float]]] = defaultdict(list)
            tasks = [
                (idx, ref_point, q, curve_map[ref_point])
                for idx, q in enumerate(curve_queries)
                for ref_point in reference_points
                if (ref_point, idx) not in covered and ref_point in curve_map
            ]
            worker_count = max(1, int(n_jobs or 1))
            with _tqdm(
                total=len(tasks),
                disable=pbar_disable,
                desc=f"PRICING {requested_curve_name} IRSWAPS [curve-store, workers={worker_count}]...",
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

            _run_stage(
                desc=f"WRITING {requested_curve_name} computed cache...",
                total=max(1, sum(len(v) for v in newly_computed_rows.values())),
                fn=lambda: self._write_irs_computed_cache_rows(
                    router=plan.router,
                    requested_curve_name=requested_curve_name,
                    rows_by_query_idx=newly_computed_rows,
                    queries=curve_queries,
                ),
            )

            direct_df = generic_tb._rows_to_frame(rows)
            missing_points = [
                ref_point
                for ref_point in reference_points
                if sum((ref_point, idx) in covered for idx in range(len(curve_queries))) < len(curve_queries)
            ]
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
            curve_df = direct_df.combine_first(fallback_df) if not fallback_df.empty else direct_df
            if not curve_df.empty:
                curve_frames.append(curve_df)

        if not curve_frames:
            return pd.DataFrame().set_index(pd.Index([], name=self._date_col))
        out = pd.concat(curve_frames, axis=1).sort_index()
        out.index.name = self._date_col
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
    ) -> pd.DataFrame:
        assert start <= end, "must have end > start"
        flat = _flatten_base_queries(queries)

        merged_routers: Dict[str, Any] = dict(self._routers)
        if routers:
            merged_routers.update(routers)
        merged_mdps: Dict[str, MarketDataProvider] = dict(mdps or {})

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
        ):
            self._append_product_frame(per_product_frames, product=product, df=df)

        irs_router = merged_routers.get("IRS")
        frb_router = merged_routers.get("FRB")
        spread_mdp = self._get_irswap_spreads_mdp(merged_mdps)

        if request_plan.irswap_spread_queries:
            if spread_mdp is not None:
                spread_df = self._price_irswap_spread_queries_with_mdp(
                    mdp=spread_mdp,
                    queries=list(request_plan.irswap_spread_queries),
                    start=start,
                    end=end,
                    freq=freq,
                    timestamps=timestamps,
                    desc="PRICING SWAP SPREADS...",
                )
                if not spread_df.empty:
                    per_product_frames.append(("SWAPSPREADS", pd.concat({"SWAPSPREADS": spread_df}, axis=1)))
            else:
                if irs_router is None or frb_router is None:
                    raise KeyError("IRS/FRB routers must be registered for MMSS/SPREADOVER evaluation.")

                irss_frb_qs = []
                irrs_irs_qs = []
                pair_specs = []

                _CT_RE = re.compile(r"(?i)\bct\s*(\d+)\b")
                _Y_RE = re.compile(r"(?i)\b(\d+)\s*y\b")

                for q in request_plan.irswap_spread_queries:
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
                if irs_intraday_timestamps is not None:
                    if not irs_intraday_timestamps:
                        irs_df = pd.DataFrame().set_index(pd.Index([], name=self._date_col))
                        cash_df = pd.DataFrame().set_index(pd.Index([], name=self._date_col))
                    else:
                        irs_df = irs_router.get_timeseries(  # type: ignore[attr-defined]
                            start,
                            end,
                            irrs_irs_qs,
                            n_jobs=n_jobs,
                            ignore_cache=ignore_cache,
                            freq=None,
                            timestamps=irs_intraday_timestamps,
                        )
                        cash_df = frb_router.get_timeseries(  # type: ignore[attr-defined]
                            start,
                            end,
                            irss_frb_qs,
                            n_jobs=n_jobs,
                            ignore_cache=ignore_cache,
                            freq=None,
                            timestamps=irs_intraday_timestamps,
                        )
                else:
                    irs_df = irs_router.get_timeseries(  # type: ignore[attr-defined]
                        start,
                        end,
                        irrs_irs_qs,
                        n_jobs=n_jobs,
                        ignore_cache=ignore_cache,
                        freq=freq,
                        timestamps=timestamps,
                    )
                    cash_df = frb_router.get_timeseries(  # type: ignore[attr-defined]
                        start,
                        end,
                        irss_frb_qs,
                        n_jobs=n_jobs,
                        ignore_cache=ignore_cache,
                        freq=freq,
                        timestamps=timestamps,
                    )

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
