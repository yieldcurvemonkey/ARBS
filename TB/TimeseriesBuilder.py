import datetime
from collections import defaultdict
from typing import TYPE_CHECKING, DefaultDict, Dict, Iterable, List, Optional, Tuple, Union

import re
import polars as pl
import pandas as pd  # Keep for bdate_range utility
import tqdm

from Query.Base.BaseQuery import BaseQuery
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
    ) -> pl.DataFrame:
        assert start <= end, "must have end > start"
        flat = _flatten_base_queries(queries)

        by_product: DefaultDict[str, List[BaseQuery]] = defaultdict(list)
        for q in flat:
            if not getattr(q, "product", None):
                raise ValueError(f"Query missing 'product': {q!r}")
            by_product[q.product].append(q)

        per_product_frames: List[Tuple[str, pl.DataFrame]] = []
        irswap_spread_queries: List[IRSwapQuery] = []
        irswap_asw_queries: List[IRSwapQuery] = []

        for product, qs in by_product.items():
            tb = self._routers.get(product)
            if tb is None:
                raise KeyError(f"No timeseries router registered for product '{product}'")

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
            elif product == "FRB":
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
            else:
                raise NotImplementedError()
                # # Future products can be registered via register_router and handled here
                # df = tb.get_timeseries(  # type: ignore[attr-defined]
                #     start,
                #     end,
                #     qs,
                #     n_jobs=n_jobs,
                #     ignore_cache=ignore_cache,
                #     freq=freq,
                #     timestamps=timestamps,
                # )

            if df is None or (hasattr(df, 'is_empty') and df.is_empty()) or (hasattr(df, 'empty') and df.empty):
                continue

            # Convert pandas to polars if needed, handling index properly
            if isinstance(df, pd.DataFrame):
                # If date is in index, reset it before converting
                if self._date_col not in df.columns and df.index.name == self._date_col:
                    df = pl.from_pandas(df.reset_index())
                else:
                    df = pl.from_pandas(df)

            # Now df is polars - check if date column exists
            if self._date_col not in df.columns:
                continue

            # Add product level to columns
            renamed_cols = {col: f"{product}.{col}" for col in df.columns if col != self._date_col}
            df = df.rename(renamed_cols)
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

            irs_df = self._routers["IRS"].get_timeseries(  # type: ignore[attr-defined]
                start,
                end,
                irrs_irs_qs,
                n_jobs=n_jobs,
                ignore_cache=ignore_cache,
                freq=freq,
                timestamps=timestamps,
            )
            cash_df = self._routers["FRB"].get_timeseries(  # type: ignore[attr-defined]
                start,
                end,
                irss_frb_qs,
                n_jobs=n_jobs,
                ignore_cache=ignore_cache,
                freq=freq,
                timestamps=timestamps,
            )

            # Convert to polars if needed
            if isinstance(irs_df, pd.DataFrame):
                irs_df = pl.from_pandas(irs_df)
            if isinstance(cash_df, pd.DataFrame):
                cash_df = pl.from_pandas(cash_df)

            # Get union of dates from both DataFrames
            irs_dates = set(irs_df[self._date_col].to_list() if self._date_col in irs_df.columns else [])
            cash_dates = set(cash_df[self._date_col].to_list() if self._date_col in cash_df.columns else [])
            all_dates = sorted(irs_dates | cash_dates)

            spread_data = {self._date_col: all_dates}
            for spec in pair_specs:
                # Extract columns and align to all_dates
                irs_col = spec["irs_col"]
                frb_col = spec["frb_col"]

                # Create full-indexed series for each column
                if irs_col in irs_df.columns:
                    a_df = irs_df.select([self._date_col, irs_col])
                    a_dict = dict(zip(a_df[self._date_col].to_list(), a_df[irs_col].to_list()))
                else:
                    a_dict = {}

                if frb_col in cash_df.columns:
                    b_df = cash_df.select([self._date_col, frb_col])
                    b_dict = dict(zip(b_df[self._date_col].to_list(), b_df[frb_col].to_list()))
                else:
                    b_dict = {}

                # Calculate spread for each date
                spread_vals = []
                for d in all_dates:
                    a_val = a_dict.get(d)
                    b_val = b_dict.get(d)

                    if a_val is not None and b_val is not None:
                        if spec["op"] == "swap_minus_cash":
                            if "outright" in str(spec["irs_col"]).lower():
                                spread_vals.append((a_val - b_val) * 100)
                            else:
                                spread_vals.append(a_val - b_val)
                        else:
                            raise ValueError(f"Unknown op: {spec['op']}")
                    else:
                        spread_vals.append(None)

                spread_data[spec["spread_name"]] = spread_vals

            if len(spread_data) > 1:  # More than just date column
                spread_df = pl.DataFrame(spread_data).sort(self._date_col)
                # Add SWAPSPREADS prefix to all columns except date
                renamed_cols = {col: f"SWAPSPREADS.{col}" for col in spread_df.columns if col != self._date_col}
                spread_df = spread_df.rename(renamed_cols)
                per_product_frames.append(("SWAPSPREADS", spread_df))

        if irswap_asw_queries:
            irs_mdp = tb.mdp
            frb_mdp = self._routers["FRB"].mdp

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
                # Create DataFrame and pivot using polars
                df = pl.DataFrame(rows, schema=[self._date_col, "Column", "Value"], orient="row")
                df = df.pivot(index=self._date_col, columns="Column", values="Value", aggregate_function="last").sort(self._date_col)
                per_product_frames.append(("IRS__ASW", df))

        if not per_product_frames:
            return pl.DataFrame({self._date_col: []})

        # Join all DataFrames on the date column
        out = per_product_frames[0][1]
        for _, df in per_product_frames[1:]:
            out = out.join(df, on=self._date_col, how="outer")

        out = out.sort(self._date_col)

        # data errors
        # Filter for data quality (commented out as in original)
        # numeric_cols = [col for col in out.columns if col != self._date_col]
        # out = out.filter(
        #     pl.all_horizontal([pl.col(col).is_between(-200_000, 200_000) for col in numeric_cols])
        # )

        if drop_multilevel_cols:
            # Remove product prefix from column names (e.g., "IRS.curve.tenor.RATE" -> "curve.tenor.RATE")
            new_names = {}
            for col in out.columns:
                if col != self._date_col and '.' in col:
                    # Split on first dot to remove product prefix
                    parts = col.split('.', 1)
                    if len(parts) > 1:
                        new_names[col] = parts[1]
            if new_names:
                out = out.rename(new_names)

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
