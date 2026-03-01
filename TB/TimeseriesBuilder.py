import datetime
from collections import defaultdict
from typing import TYPE_CHECKING, Any, DefaultDict, Dict, Iterable, List, Mapping, Optional, Tuple, Union

import re
import pandas as pd
import tqdm

from MDP.MarketDataProvider import MarketDataProvider
from Query.Base.BaseQuery import BaseQuery
from Query.Base.query_resolution import resolve_for_request, resolve_query
from Query.FixedRateBonds.FixedRateBondQuery import FixedRateBondQuery
from Query.FixedRateBonds.FixedRateBondValue import FixedRateBondValue
from Query.FixedRateBonds._FixedRateBondGenericPricer import _FixedRateBondGenericPricer
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapValue import IRSwapValue
from Query.IRSwaps._IRSwapGenericCurve import _IRSwapGenericCurve

from TB.utils import DateLike

# Avoid hard import cycles for optional type checking
if TYPE_CHECKING:
    from TB.FixedRateBondsTB import FixedRateBondsTB
    from TB.IRSwapsTB import IRSwapsTB


def _flatten_base_queries(queries: Iterable[Union[BaseQuery, List[BaseQuery]]]) -> List[BaseQuery]:
    flat: List[BaseQuery] = []
    for q in queries:
        if isinstance(q, list):
            for qq in q:
                flat.extend(qq.return_query())
        else:
            flat.extend(q.return_query())
    return flat


def _ct_alias_to_y(tenor: str) -> str:
    """'CT2/CT10' -> '2Y/10Y', 'ct05xCT30' -> '05Yx30Y'"""
    _CT_RE = re.compile(r"(?i)\bct\s*(\d+)\b")
    return _CT_RE.sub(r"\1Y", str(tenor))


def _y_alias_to_ct(tenor: str) -> str:
    """'5Y' -> 'CT5', '2Y/10Y' -> 'CT2/CT10', '2Yx10Y' -> 'CT2xCT10'"""
    _Y_RE = re.compile(r"(?i)\b(\d+)\s*y\b")
    return _Y_RE.sub(r"CT\1", str(tenor))


def _safe_col_name(q, default: str) -> str:
    try:
        return q.col_name()
    except Exception:
        return default


class TimeseriesBuilder:
    def __init__(
        self,
        *,
        irswaps_tb: "IRSwapsTB",
        fixedratebonds_tb: "FixedRateBondsTB",
        date_col: str = "Date",
    ):
        self._date_col = date_col
        self._routers: Dict[str, object] = {
            "IRS": irswaps_tb,
            "FRB": fixedratebonds_tb,
        }

    def register_router(self, product: str, tb_obj: object) -> None:
        self._routers[product] = tb_obj

    # ------------------------------------------------------------------
    # Generic fallback for products without a dedicated TB router
    # ------------------------------------------------------------------
    def _generic_fallback_timeseries(
        self,
        product: str,
        qs: List[BaseQuery],
        mdp: MarketDataProvider,
        start: DateLike,
        end: DateLike,
        freq: Optional[str],
        timestamps: Optional[List[datetime.datetime]],
    ) -> pd.DataFrame:
        """Evaluate queries via their BaseQuery pipeline (adapter → structure → value)."""
        # Build reference points
        if timestamps is not None:
            ref_points = sorted(timestamps)
        elif freq is not None and isinstance(start, datetime.datetime) and isinstance(end, datetime.datetime):
            ref_points = pd.date_range(start, end, freq=freq).tolist()
        else:
            ref_points = pd.bdate_range(start, end).date.tolist()

        rows: List[Tuple[Any, str, float]] = []
        for ts in tqdm.tqdm(ref_points, desc=f"Generic TB [{product}]"):
            now = ts if isinstance(ts, datetime.datetime) else datetime.datetime.combine(ts, datetime.time())
            for q in qs:
                try:
                    # 1. Build initial MDP request and fetch pricer
                    seed_req = q.build_mdp_request(now)
                    pricer = mdp.get_pricer(dict(seed_req))

                    # 2. Resolve query request (may hydrate/expand aliases)
                    q_resolved = resolve_for_request(q, timestamp=now, pricer_or_curve=pricer)

                    # 3. Re-fetch pricer if resolved request differs
                    resolved_req = q_resolved.build_mdp_request(now)
                    if resolved_req != seed_req:
                        pricer = mdp.get_pricer(dict(resolved_req))

                    # 4. Final query resolution
                    q_eff = resolve_query(q_resolved, timestamp=now, pricer_or_curve=pricer)

                    # 5. Resolve package (pricables + weights)
                    package, risk_weights = q_eff.resolve_package(
                        pricer_or_curve=pricer, is_for_timeseries=True
                    )

                    # 6. Build value map and evaluate
                    vmap = q_eff.build_value_map(
                        pricer_or_curve=pricer,
                        package=package,
                        risk_weights=risk_weights,
                    )
                    value_key = getattr(q_eff, "value", None) or q_eff.default_mtm_value_id()
                    value_kwargs = getattr(q_eff, "value_kwargs", {}) or {}
                    result = vmap.apply(value=value_key, **value_kwargs)

                    # 7. Column naming
                    col = q_eff.name if q_eff.name else _safe_col_name(q_eff, f"{product}_{id(q_eff)}")

                    # 8. Date for index
                    date_val = ts.date() if isinstance(ts, datetime.datetime) else ts
                    rows.append((date_val, col, float(result)))
                except Exception:
                    continue

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows, columns=[self._date_col, "Column", "Value"])
        df = df.pivot(index=self._date_col, columns="Column", values="Value").sort_index()
        df.columns.name = None
        return df

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

        # Merge routers: per-call overrides take precedence over instance routers
        merged_routers: Dict[str, Any] = dict(self._routers)
        if routers:
            merged_routers.update(routers)
        merged_mdps: Dict[str, MarketDataProvider] = dict(mdps or {})

        per_product_frames: List[Tuple[str, pd.DataFrame]] = []
        irswap_spread_queries: List[IRSwapQuery] = []
        irswap_asw_queries: List[IRSwapQuery] = []

        for product, qs in by_product.items():
            tb = merged_routers.get(product)

            if tb is not None and product == "IRS":
                irs_qs_unfiltered: List[IRSwapQuery] = [q for q in qs if isinstance(q, IRSwapQuery)]

                irs_qs: List[IRSwapQuery] = []

                for q in irs_qs_unfiltered:
                    if q.value in [IRSwapValue.MMSS, IRSwapValue.SPREADOVER]:
                        irswap_spread_queries.append(q)
                    elif q.value in [IRSwapValue.PAR_PAR_ASW, IRSwapValue.PAR_PAR_ASW, IRSwapValue.TRUE_ASW, IRSwapValue.PROCEEDS_ASW, IRSwapValue.MARKET_ASW]:
                        irswap_asw_queries.append(q)
                    else:
                        irs_qs.append(q)

                # if len(irs_qs) != len(qs):
                #     raise TypeError("Mixed/non-IRS queries encountered in IRS bucket")
                df = tb.get_timeseries(  # type: ignore[attr-defined]
                    start,
                    end,
                    irs_qs,
                    n_jobs=n_jobs,
                    ignore_cache=ignore_cache,
                    freq=freq,
                    timestamps=timestamps,
                )
            elif tb is not None and product == "FRB":
                frb_qs: List[FixedRateBondQuery] = [q for q in qs if isinstance(q, FixedRateBondQuery)]
                if len(frb_qs) != len(qs):
                    raise TypeError("Mixed/non-FRB queries encountered in FixedRateBond bucket")
                df = tb.get_timeseries(  # type: ignore[attr-defined]
                    start,
                    end,
                    frb_qs,
                    n_jobs=n_jobs,
                    ignore_cache=ignore_cache,
                    freq=freq,
                    timestamps=timestamps,
                )
            elif tb is not None:
                # Registered router for other products – delegate directly
                df = tb.get_timeseries(  # type: ignore[attr-defined]
                    start,
                    end,
                    qs,
                    n_jobs=n_jobs,
                    ignore_cache=ignore_cache,
                    freq=freq,
                    timestamps=timestamps,
                )
            elif product in merged_mdps:
                # Generic MDP fallback path
                df = self._generic_fallback_timeseries(
                    product=product,
                    qs=qs,
                    mdp=merged_mdps[product],
                    start=start,
                    end=end,
                    freq=freq,
                    timestamps=timestamps,
                )
            else:
                available = sorted(set(merged_routers.keys()) | set(merged_mdps.keys()))
                raise KeyError(
                    f"No timeseries router or MDP registered for product '{product}'. "
                    f"Available: {available}"
                )

            if df is None or df.empty:
                continue
            if self._date_col in df.columns:
                df = df.set_index(self._date_col)

            df = pd.concat({product: df}, axis=1)
            per_product_frames.append((product, df))

        if irswap_spread_queries:
            irss_frb_qs = []
            irrs_irs_qs = []
            pair_specs = []

            _CT_RE = re.compile(r"(?i)\bct\s*(\d+)\b")
            _Y_RE = re.compile(r"(?i)\b(\d+)\s*y\b")

            for q in irswap_spread_queries:
                if q.value == IRSwapValue.MMSS:
                    q_frb = FixedRateBondQuery(cusip=q.tenor, value=FixedRateBondValue.YTM)
                    q_irs = IRSwapQuery(curve=q.curve, tenor=q.tenor, value=IRSwapValue.RATE)
                    op = "swap_minus_cash"  # spread = IRS - UST
                    # mult = 100.0  # report in bps

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
                    op = "swap_minus_cash"  # spreadover = IRS - UST
                    # mult = 100.0

                else:
                    raise NotImplementedError(f"Unhandled spread type: {q.value}")

                irss_frb_qs.append(q_frb)
                irrs_irs_qs.append(q_irs)

                # Record robust pairing info using expected column names
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
                        "op": op,  # 'swap_minus_cash' or 'cash_minus_swap'
                        # "mult": mult,  # e.g., 100.0 for bps
                    }
                )

            irs_df = merged_routers["IRS"].get_timeseries(  # type: ignore[attr-defined]
                start,
                end,
                irrs_irs_qs,
                n_jobs=n_jobs,
                ignore_cache=ignore_cache,
                freq=freq,
                timestamps=timestamps,
            )
            cash_df = merged_routers["FRB"].get_timeseries(  # type: ignore[attr-defined]
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

                # future-proof for 'ASW' and 'CAS'
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
            irs_mdp = merged_routers["IRS"].mdp  # type: ignore[attr-defined]
            frb_mdp = merged_routers["FRB"].mdp  # type: ignore[attr-defined]

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

                        idx = getattr(ql_curve, "index")() if hasattr(ql_curve, "index") else None
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
        
        # data errors
        # out = out[((out < 200_000).all(axis=1)) & (out > -200_000).all(axis=1)]
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
