from datetime import datetime, date
from typing import Annotated, Dict, List, Literal, Optional

import numpy as np
import pandas as pd
import QuantLib as ql

from Query.IRSwaps.backends.quantlib.utils import datetime_to_ql_date, ql_date_to_pydate


def build_ql_discount_curve(
    datetime_series: pd.Series,
    discount_factor_series: pd.Series,
    ql_dc: ql.DayCounter,
    ql_cal: ql.Calendar,
    interpolation_algo: Optional[
        Literal[
            "df_log_linear",
            "df_mono_log_cubic",
            "df_natural_cubic",
            "df_kruger_log",
            "df_natural_log_cubic",
            "df_log_mixed_linear",
            "df_log_parabolic_cubic",
            "df_mono_log_parabolic_cubic",
        ]
    ] = "df_log_linear",
) -> ql.DiscountCurve:
    curve_mapping = {
        "df_log_linear": ql.DiscountCurve,
        "df_mono_log_cubic": ql.MonotonicLogCubicDiscountCurve,
        "df_natural_cubic": ql.NaturalCubicDiscountCurve,
        "df_kruger_log": ql.KrugerLogDiscountCurve,
        "df_natural_log_cubic": ql.NaturalLogCubicDiscountCurve,
        "df_log_mixed_linear": ql.LogMixedLinearCubicDiscountCurve,
        "df_log_parabolic_cubic": ql.LogParabolicCubicDiscountCurve,
        "df_mono_log_parabolic_cubic": ql.MonotonicLogParabolicCubicDiscountCurve,
    }
    try:
        curve_class = curve_mapping[interpolation_algo]
    except KeyError:
        raise ValueError(f"QuantLib has no discount curve with {interpolation_algo} interpolation")

    ql_dates = datetime_series.apply(datetime_to_ql_date).to_list()
    discount_factors = discount_factor_series.to_list()

    ql_curve: ql.DiscountCurve = curve_class(ql_dates, discount_factors, ql_dc, ql_cal)
    ql_curve.enableExtrapolation()
    return ql_curve


def build_piecewise_ql_discount_curve(
    swap_rate_helpers: List[ql.RateHelper],
    ql_dc: ql.DayCounter,
    ql_cal: ql.Calendar,
    settlement_day: int,
    interpolation_algo: Optional[
        Literal[
            "pdf_log_linear",
            "pdf_mono_log_cubic",
            "pdf_natural_cubic",
            "pdf_kruger_log",
            "pdf_natural_log_cubic",
            "pdf_log_mixed_linear",
            "pdf_log_parabolic_cubic",
            "pdf_spline_cubic_discount",
            "pdf_mono_log_parabolic_cubic",
        ]
    ] = "pdf_log_linear",
) -> ql.DiscountCurve:
    curve_mapping = {
        "pdf_log_linear": ql.PiecewiseLogLinearDiscount,
        "pdf_mono_log_cubic": ql.PiecewiseLogCubicDiscount,
        "pdf_natural_cubic": ql.PiecewiseNaturalCubicZero,
        "pdf_kruger_log": ql.PiecewiseKrugerLogDiscount,
        "pdf_natural_log_cubic": ql.PiecewiseNaturalLogCubicDiscount,
        "pdf_log_mixed_linear": ql.PiecewiseLogMixedLinearCubicDiscount,
        "pdf_log_parabolic_cubic": ql.PiecewiseLogParabolicCubicDiscount,
        "pdf_spline_cubic_discount": ql.PiecewiseSplineCubicDiscount,
        "pdf_mono_log_parabolic_cubic": ql.PiecewiseMonotonicLogParabolicCubicDiscount,
    }
    try:
        curve_class = curve_mapping[interpolation_algo]
    except KeyError:
        raise ValueError(f"QuantLib has no discount curve with {interpolation_algo} interpolation")

    ql_curve: ql.DiscountCurve = curve_class(settlement_day, ql_cal, swap_rate_helpers, ql_dc)
    ql_curve.enableExtrapolation()
    return ql_curve


def build_ql_zero_curve(
    datetime_series: pd.Series,
    zero_rate_series: pd.Series,
    ql_dc: ql.DayCounter,
    ql_cal: ql.Calendar,
    interpolation_algo: Optional[
        Literal[
            "z_linear",
            "z_log_linear",
            "z_cubic",
            "z_natural_cubic",
            "z_log_cubic",
            "z_monotonic_cubic",
            "z_kruger",
            "z_parabolic_cubic",
            "z_monotonic_parabolic_cubic",
        ]
    ] = "z_log_linear",
) -> ql.ZeroCurve:
    curve_mapping = {
        "z_linear": ql.ZeroCurve,
        "z_log_linear": ql.LogLinearZeroCurve,
        "z_cubic": ql.CubicZeroCurve,
        "z_natural_cubic": ql.NaturalCubicZeroCurve,
        "z_log_cubic": ql.LogCubicZeroCurve,
        "z_monotonic_cubic": ql.MonotonicCubicZeroCurve,
        "z_kruger": ql.KrugerZeroCurve,
        "z_parabolic_cubic": ql.ParabolicCubicZeroCurve,
        "z_monotonic_parabolic_cubic": ql.MonotonicParabolicCubicZeroCurve,
    }
    try:
        curve_class = curve_mapping[interpolation_algo]
    except KeyError:
        raise ValueError(f"QuantLib has no zero curve with {interpolation_algo} interpolation.")

    ql_dates = datetime_series.apply(datetime_to_ql_date).to_list()
    rates = zero_rate_series.to_list()

    ql_curve: ql.ZeroCurve = curve_class(ql_dates, rates, ql_dc, ql_cal)
    ql_curve.enableExtrapolation()
    return ql_curve


def extract_fitted_curve_nodes(fitted_curve: ql.YieldTermStructure, num_points: Optional[int] = 10000) -> Dict[datetime, float]:
    start_date: ql.Date = fitted_curve.referenceDate()
    end_date: ql.Date = fitted_curve.maxDate()
    grid_serials = np.linspace(start_date.serialNumber(), end_date.serialNumber(), num_points).astype(int)
    grid_dates = [ql.Date(int(s)) for s in grid_serials]
    return {ql_date_to_pydate(date): fitted_curve.discount(date) for date in grid_dates}


def get_nodes_dict(
    ql_curve: ql.YieldTermStructure | ql.DiscountCurve | ql.PiecewiseLogLinearDiscount | ql.FittedBondDiscountCurve,
    to_ttm: Optional[bool] = False,
    to_iso: Optional[bool] = False,
) -> Dict[datetime, float]:
    try:
        if hasattr(ql_curve, "nodes"):
            nodes = ql_curve.nodes()
        elif hasattr(ql_curve, "dates") and hasattr(ql_curve, "discounts"):
            nodes = list(zip(ql_curve.dates(), ql_curve.discounts()))
        else:
            return extract_fitted_curve_nodes(fitted_curve=ql_curve)

        if to_ttm:
            ref_date: ql.Date = ql_curve.referenceDate()
            day_counter: ql.DayCounter = ql_curve.dayCounter()
            nodes_dict = {day_counter.yearFraction(ref_date, node[0]): node[1] for node in nodes}
        elif to_iso:
            nodes_dict = {ql_date_to_pydate(node[0]).isoformat(): node[1] for node in nodes}
        else:
            nodes_dict = {ql_date_to_pydate(node[0]): node[1] for node in nodes}

        return nodes_dict
    except Exception as e:
        print(f"Couldn't Extract Curve Nodes: {e}")
        return None


def build_discount_curve_from_nodes(
    ql_curve_nodes: Dict[datetime | Annotated[str, "isoformat"], float], ql_dc: ql.DayCounter, ql_cal: ql.Calendar, interpolation_algo: str
):
    try:
        dates = []
        for k in ql_curve_nodes.keys():
            if isinstance(k, datetime) or isinstance(k, date):
                dates.append(k)
            elif isinstance(k, str):
                try:
                    dates.append(pd.Timestamp(k))
                except Exception as e:
                    raise ValueError(f"Bad date string {k!r}: {e}") from None
            else:
                raise TypeError(f"Unsupported key type {type(k)}: {k!r}")

        return build_ql_discount_curve(
            datetime_series=pd.Series(dates),
            discount_factor_series=pd.Series(ql_curve_nodes.values()),
            ql_dc=ql_dc,
            ql_cal=ql_cal,
            interpolation_algo=interpolation_algo,
        )
    except Exception as e:
        print(f"Couldn't Build Curve: {e}")
        return None


def get_fixings_dict(swap_index: ql.SwapIndex) -> Dict[datetime, float]:
    ts = swap_index.timeSeries()
    return {ql_date_to_pydate(d): v for d, v in zip(ts.dates(), ts.values()) if not np.isnan(v)}
