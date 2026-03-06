import datetime
import re
from collections import defaultdict
from typing import TYPE_CHECKING, Any, DefaultDict, Dict, Iterable, List, Mapping, Optional, Tuple, Union

import pandas as pd
import tqdm

from MDP.MarketDataProvider import MarketDataProvider
from Query.Base.BaseQuery import BaseQuery
from Query.FixedRateBonds.FixedRateBondQuery import FixedRateBondQuery
from Query.FixedRateBonds.FixedRateBondValue import FixedRateBondValue
from Query.FixedRateBonds._FixedRateBondGenericPricer import _FixedRateBondGenericPricer
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapValue import IRSwapValue
from Query.IRSwaps._IRSwapGenericCurve import _IRSwapGenericCurve
from TB.BaseTimeseriesTB import BaseTimeseriesTB
from TB.utils import DateLike

if TYPE_CHECKING:
    from TB.FixedRateBondsTB import FixedRateBondsTB
    from TB.IRSwaptionsTB import IRSwaptionsTB
    from TB.IRSwapsTB import IRSwapsTB
    from TB.STIRFutureOptionsTB import STIRFutureOptionsTB
    from TB.STIRFuturesTB import STIRFuturesTB
    from TB.USTFutureOptionsTB import USTFutureOptionsTB
    from TB.USTFuturesTB import USTFuturesTB


def _flatten_base_queries(queries: Iterable[Union[BaseQuery, List[BaseQuery]]]) -> List[BaseQuery]:
    flat: List[BaseQuery] = []
    for q in queries:
        if isinstance(q, list):
            for qq in q:
                out = qq.return_query() if hasattr(qq, "return_query") else [qq]
                flat.extend(out if isinstance(out, list) else [out])
        else:
            out = q.return_query() if hasattr(q, "return_query") else [q]
            flat.extend(out if isinstance(out, list) else [out])
    return flat


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
        irswaps_tb: "IRSwapsTB",
        irswaptions_tb: Optional["IRSwaptionsTB"] = None,
        fixedratebonds_tb: "FixedRateBondsTB",
        stirfutures_tb: Optional["STIRFuturesTB"] = None,
        ustfutures_tb: Optional["USTFuturesTB"] = None,
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
        if stirfutureoptions_tb is not None:
            self._routers["STIRFUTUREOPTION"] = stirfutureoptions_tb
        if ustfutureoptions_tb is not None:
            self._routers["USTFUTUREOPTION"] = ustfutureoptions_tb
        if fxforwards_tb is not None:
            self._routers["FXFORWARD"] = fxforwards_tb

        self._generic_router_cache: Dict[str, _GenericTimeseriesTB] = {}

    def register_router(self, product: str, tb_obj: object) -> None:
        self._routers[product] = tb_obj

    def _get_generic_router(self, product: str, mdp: MarketDataProvider) -> _GenericTimeseriesTB:
        existing = self._generic_router_cache.get(product)
        if existing is not None and existing.mdp is mdp:
            return existing
        generic_tb = _GenericTimeseriesTB(product=product, mdp=mdp, date_col=self._date_col)
        self._generic_router_cache[product] = generic_tb
        return generic_tb

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
        alias_map = {"IRSWAPTIONS": "IRSWAPTION"}
        canonical_product = alias_map.get(product, product)

        tb = merged_routers.get(product) or merged_routers.get(canonical_product)
        if tb is not None:
            return tb.get_timeseries(  # type: ignore[attr-defined]
                start,
                end,
                qs,
                n_jobs=n_jobs,
                ignore_cache=ignore_cache,
                freq=freq,
                timestamps=timestamps,
            )

        mdp_key = product if product in merged_mdps else canonical_product
        if mdp_key in merged_mdps:
            generic_tb = self._get_generic_router(canonical_product, merged_mdps[mdp_key])
            return generic_tb.get_timeseries(
                start,
                end,
                qs,
                n_jobs=n_jobs,
                ignore_cache=ignore_cache,
                freq=freq,
                timestamps=timestamps,
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

        by_product: DefaultDict[str, List[BaseQuery]] = defaultdict(list)
        for q in flat:
            if not getattr(q, "product", None):
                raise ValueError(f"Query missing 'product': {q!r}")
            by_product[q.product].append(q)

        merged_routers: Dict[str, Any] = dict(self._routers)
        if routers:
            merged_routers.update(routers)
        merged_mdps: Dict[str, MarketDataProvider] = dict(mdps or {})

        per_product_frames: List[Tuple[str, pd.DataFrame]] = []
        irswap_spread_queries: List[IRSwapQuery] = []
        irswap_asw_queries: List[IRSwapQuery] = []

        for product, qs in by_product.items():
            if product == "IRS":
                irs_qs_unfiltered: List[IRSwapQuery] = [q for q in qs if isinstance(q, IRSwapQuery)]
                irs_qs: List[IRSwapQuery] = []
                for q in irs_qs_unfiltered:
                    if q.value in [IRSwapValue.MMSS, IRSwapValue.SPREADOVER]:
                        irswap_spread_queries.append(q)
                    elif q.value in [IRSwapValue.PAR_PAR_ASW, IRSwapValue.PAR_PAR_ASW, IRSwapValue.TRUE_ASW, IRSwapValue.PROCEEDS_ASW, IRSwapValue.MARKET_ASW]:
                        irswap_asw_queries.append(q)
                    else:
                        irs_qs.append(q)

                if irs_qs:
                    df = self._route_product_timeseries(
                        product="IRS",
                        qs=irs_qs,
                        merged_routers=merged_routers,
                        merged_mdps=merged_mdps,
                        start=start,
                        end=end,
                        n_jobs=n_jobs,
                        ignore_cache=ignore_cache,
                        freq=freq,
                        timestamps=timestamps,
                    )
                    self._append_product_frame(per_product_frames, product="IRS", df=df)
                continue

            if product == "FRB":
                frb_qs: List[FixedRateBondQuery] = [q for q in qs if isinstance(q, FixedRateBondQuery)]
                if len(frb_qs) != len(qs):
                    raise TypeError("Mixed/non-FRB queries encountered in FixedRateBond bucket")
                df = self._route_product_timeseries(
                    product="FRB",
                    qs=frb_qs,
                    merged_routers=merged_routers,
                    merged_mdps=merged_mdps,
                    start=start,
                    end=end,
                    n_jobs=n_jobs,
                    ignore_cache=ignore_cache,
                    freq=freq,
                    timestamps=timestamps,
                )
                self._append_product_frame(per_product_frames, product="FRB", df=df)
                continue

            df = self._route_product_timeseries(
                product=product,
                qs=qs,
                merged_routers=merged_routers,
                merged_mdps=merged_mdps,
                start=start,
                end=end,
                n_jobs=n_jobs,
                ignore_cache=ignore_cache,
                freq=freq,
                timestamps=timestamps,
            )
            self._append_product_frame(per_product_frames, product=product, df=df)

        irs_router = merged_routers.get("IRS")
        frb_router = merged_routers.get("FRB")

        if irswap_spread_queries:
            if irs_router is None or frb_router is None:
                raise KeyError("IRS/FRB routers must be registered for MMSS/SPREADOVER evaluation.")

            irss_frb_qs = []
            irrs_irs_qs = []
            pair_specs = []

            _CT_RE = re.compile(r"(?i)\bct\s*(\d+)\b")
            _Y_RE = re.compile(r"(?i)\b(\d+)\s*y\b")

            for q in irswap_spread_queries:
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

        if irswap_asw_queries:
            if irs_router is None or frb_router is None:
                raise KeyError("IRS/FRB routers must be registered for ASW evaluation.")

            irs_mdp = irs_router.mdp  # type: ignore[attr-defined]
            frb_mdp = frb_router.mdp  # type: ignore[attr-defined]

            ref_points = pd.bdate_range(start, end).date.tolist()
            rows = []
            for d in tqdm.tqdm(ref_points, desc="PRICING ASSET SWAPS..."):
                for q in irswap_asw_queries:
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
                per_product_frames.append(("IRS__ASW", df))

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
