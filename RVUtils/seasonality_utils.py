# ABOUTME: Seasonality analysis and decomposition utilities
# ABOUTME: Tools for detecting and modeling seasonal patterns in time series
import polars as pl
import pandas as pd  # Still needed for Timestamp compatibility with QuantLib
import QuantLib as ql
from typing import Optional


def monthend_cumsum_seasonality(
    df: pl.DataFrame,
    *,
    value_col: str | None = None,
    window: int = 5,
    business_month_end: bool = True,
    cal: Optional[ql.Calendar] = ql.UnitedStates(ql.UnitedStates.GovernmentBond),
    relative_to: str = "month_end",
    metric: str = "abs",
    baseline_fallback: str = "first_valid",
) -> pl.DataFrame:
    # Convert polars to pandas for processing (needed for QuantLib integration and index-based operations)
    df_pd = df.to_pandas()

    if value_col is None:
        if df_pd.shape[1] != 1:
            raise ValueError("Provide value_col when df has multiple columns.")
        s = df_pd.iloc[:, 0].copy()
    else:
        s = df_pd[value_col].copy()

    idx = pd.to_datetime(s.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    s.index = idx.normalize()
    s = s[~s.index.duplicated(keep="last")].sort_index()

    if s.empty:
        return pl.from_pandas(pd.DataFrame(index=range(-window, window + 1)))

    def _to_qld(d: pd.Timestamp) -> ql.Date:
        return ql.Date(d.day, int(d.month), d.year)

    def _to_ts(qd: ql.Date) -> pd.Timestamp:
        return pd.Timestamp(qd.year(), int(qd.month()), qd.dayOfMonth())

    start = s.index.min().to_period("M")
    end = s.index.max().to_period("M")

    y, m = start.year, start.month
    anchors_ts: list[pd.Timestamp] = []
    while (y < end.year) or (y == end.year and m <= end.month):
        first_qld = ql.Date(1, int(m), int(y))
        if business_month_end:
            q_end = cal.endOfMonth(first_qld)  # last business day per calendar
        else:
            q_end = ql.Date.endOfMonth(first_qld)  # last calendar day
        anchors_ts.append(_to_ts(q_end))
        # increment month
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1

    if not anchors_ts:
        return pl.from_pandas(pd.DataFrame(index=range(-window, window + 1)))

    rel = list(range(-window, window + 1))

    cols, blocks = [], []
    for a_ts in anchors_ts:
        a_qld = _to_qld(a_ts)
        dates_ts = [_to_ts(cal.advance(a_qld, i, ql.Days)) for i in rel]
        vals = [s.get(d, pd.NA) for d in dates_ts]
        col = a_ts.strftime("%Y-%m")
        cols.append(col)
        blocks.append(pd.Series(vals, index=rel, name=col))

    mat = pd.concat(blocks, axis=1)
    mat.index.name = "bdays_from_month_end"

    base_row = 0 if relative_to == "month_end" else -window
    base = mat.loc[base_row].copy()

    if baseline_fallback == "first_valid":
        for c in mat.columns:
            if pd.isna(base[c]):
                fv = mat[c].dropna()
                if not fv.empty:
                    base[c] = fv.iloc[0]

    if metric == "abs":
        cum = mat.sub(base, axis=1)
    elif metric == "pct":
        cum = mat.div(base, axis=1).subtract(1).multiply(100)  # %
    elif metric == "bps":
        cum = mat.sub(base, axis=1).multiply(10_000)  # bps
    else:
        raise ValueError("metric must be one of {'abs','pct','bps'}")

    avg = cum.mean(axis=1)
    std = cum.std(axis=1, ddof=1)

    # Group columns by month for seasonality calculation
    cum_cols_by_month = {m: [] for m in range(1, 13)}
    for col in cum.columns:
        month = pd.to_datetime(col).month
        cum_cols_by_month[month].append(col)

    # Add by-month seasonality with std columns
    month_seasonality = []
    month_names = {1: "jan", 2: "feb", 3: "mar", 4: "apr", 5: "may", 6: "jun", 7: "jul", 8: "aug", 9: "sep", 10: "oct", 11: "nov", 12: "dec"}
    for month_num, cols in cum_cols_by_month.items():
        if len(cols) > 1:  # Only calculate if there's more than one data point
            month_avg = cum[cols].mean(axis=1)
            month_std = cum[cols].std(axis=1, ddof=1)
            month_name = month_names[month_num]

            month_avg_series = month_avg.rename(f"avg-{month_name}")
            std1_minus = (month_avg - month_std).rename(f"avg-{month_name}-std1")
            std1_plus = (month_avg + month_std).rename(f"avg-{month_name}+std1")
            std2_minus = (month_avg - 2 * month_std).rename(f"avg-{month_name}-std2")
            std2_plus = (month_avg + 2 * month_std).rename(f"avg-{month_name}+std2")

            month_seasonality.extend([month_avg_series, std1_minus, std1_plus, std2_minus, std2_plus])

    # Add by-quarter-end seasonality with std columns
    quarter_end_seasonality = []
    q_end_months = {3: "q1-end", 6: "q2-end", 9: "q3-end", 12: "q4-end"}
    for month_num, q_name in q_end_months.items():
        cols = cum_cols_by_month.get(month_num, [])
        if len(cols) > 1:  # Only calculate if there's more than one data point
            q_end_avg = cum[cols].mean(axis=1)
            q_end_std = cum[cols].std(axis=1, ddof=1)

            q_end_avg_series = q_end_avg.rename(f"avg-{q_name}")
            std1_minus = (q_end_avg - q_end_std).rename(f"avg-{q_name}-std1")
            std1_plus = (q_end_avg + q_end_std).rename(f"avg-{q_name}+std1")
            std2_minus = (q_end_avg - 2 * q_end_std).rename(f"avg-{q_name}-std2")
            std2_plus = (q_end_avg + 2 * q_end_std).rename(f"avg-{q_name}+std2")

            quarter_end_seasonality.extend([q_end_avg_series, std1_minus, std1_plus, std2_minus, std2_plus])

    out = pd.concat(
        [
            avg.rename("avg"),
            (avg - std).rename("avg-std1"),
            (avg + std).rename("avg+std1"),
            (avg - 2 * std).rename("avg-std2"),
            (avg + 2 * std).rename("avg+std2"),
            *month_seasonality,
            *quarter_end_seasonality,
            cum,  # individual month-ends
        ],
        axis=1,
    )
    return pl.from_pandas(out)
