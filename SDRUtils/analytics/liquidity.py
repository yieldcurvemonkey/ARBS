"""
Liquidity scoring: price dispersion, tick size, venue analysis, and composite scores.

Higher dispersion = worse liquidity. The composite score normalizes
multiple metrics to 0-100 (higher = more liquid) per tenor.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Sequence

import numpy as np
import pandas as pd

from ._base import SDRAnalyzer
from .filters import BENCHMARK_TENORS, D2D_PLATFORMS, vwap


# ---------------------------------------------------------------------------
# Price dispersion
# ---------------------------------------------------------------------------


def price_dispersion(
    df: pd.DataFrame,
    tenor_col: str = "tenor_label",
    rate_col: str = "fixed_rate",
    date_col: str = "execution_date",
) -> pd.DataFrame:
    """Daily price dispersion (std dev of fixed rate) per tenor, in bps.

    For each combination of *date_col* and *tenor_col*, computes the
    standard deviation of *rate_col* and scales to basis points
    (``* 10_000``).

    Args:
        df: DataFrame with rate, tenor, and date columns.
        tenor_col: Column containing tenor labels.
        rate_col: Column containing the fixed rate.
        date_col: Column containing execution dates.

    Returns:
        Pivot table with dates as index and tenors as columns, values
        being daily dispersion in bps.
    """
    rate = pd.to_numeric(df[rate_col], errors="coerce")
    daily = (
        df.assign(_rate=rate)
        .groupby([date_col, tenor_col])["_rate"]
        .std()
        .reset_index()
    )
    daily.columns = [date_col, tenor_col, "dispersion_bps"]
    daily["dispersion_bps"] = daily["dispersion_bps"] * 10_000

    pivot = daily.pivot_table(
        index=date_col,
        columns=tenor_col,
        values="dispersion_bps",
    )
    pivot.index = pd.to_datetime(pivot.index)
    return pivot


# ---------------------------------------------------------------------------
# Tick size statistics
# ---------------------------------------------------------------------------


def tick_size_stats(
    df: pd.DataFrame,
    tenor_col: str = "tenor_label",
    rate_col: str = "fixed_rate",
    ts_col: str = "execution_timestamp",
) -> pd.DataFrame:
    """Per-tenor tick-size statistics (consecutive rate deltas).

    For each tenor, sorts trades by *ts_col*, computes the absolute
    difference of consecutive rates in bps, and excludes zero ticks.

    Args:
        df: DataFrame with rate, tenor, and timestamp columns.
        tenor_col: Column containing tenor labels.
        rate_col: Column containing the fixed rate.
        ts_col: Column containing execution timestamps.

    Returns:
        DataFrame indexed by tenor with columns ``[median, p25, p75,
        count]`` describing the tick-size distribution in bps.
    """
    rate = pd.to_numeric(df[rate_col], errors="coerce")
    tmp = df.assign(_rate=rate).copy()
    tmp["_ts"] = pd.to_datetime(tmp[ts_col])

    records = []
    for tenor, grp in tmp.groupby(tenor_col):
        grp = grp.sort_values("_ts")
        if len(grp) < 2:
            continue
        diffs = grp["_rate"].diff().dropna().abs() * 10_000
        diffs = diffs[diffs > 0]
        if diffs.empty:
            continue
        records.append(
            {
                "tenor": tenor,
                "median": diffs.median(),
                "p25": diffs.quantile(0.25),
                "p75": diffs.quantile(0.75),
                "count": len(diffs),
            }
        )

    if not records:
        return pd.DataFrame(columns=["tenor", "median", "p25", "p75", "count"])

    return pd.DataFrame(records).set_index("tenor")


# ---------------------------------------------------------------------------
# Venue analysis (D2D vs D2C)
# ---------------------------------------------------------------------------


def venue_analysis(
    df: pd.DataFrame,
    platform_col: str = "platform_identifier",
    rate_col: str = "fixed_rate",
    date_col: str = "execution_date",
    d2d_platforms: Optional[Sequence[str]] = None,
) -> pd.DataFrame:
    """Compare D2D vs D2C pricing dispersion by venue.

    Splits trades into dealer-to-dealer (D2D) and dealer-to-client (D2C)
    using *d2d_platforms* (defaults to the standard IDB SEF set), then
    computes per-venue median daily price dispersion in bps.

    Args:
        df: DataFrame with platform, rate, and date columns.
        platform_col: Column containing platform identifiers.
        rate_col: Column containing the fixed rate.
        date_col: Column containing execution dates.
        d2d_platforms: Set of D2D platform codes.  Defaults to
            :data:`~SDRUtils.analytics.filters.D2D_PLATFORMS`.

    Returns:
        DataFrame with columns ``[venue, venue_type,
        median_daily_dispersion_bps, trade_count]``.
    """
    if d2d_platforms is None:
        d2d_platforms = D2D_PLATFORMS

    d2d_set = {str(p).upper() for p in d2d_platforms}

    tmp = df[df[platform_col].notna()].copy()
    rate = pd.to_numeric(tmp[rate_col], errors="coerce")
    tmp = tmp.assign(_rate=rate)
    tmp["venue_type"] = tmp[platform_col].apply(
        lambda x: "D2D" if str(x).upper() in d2d_set else "D2C"
    )

    records = []
    for (venue, vtype), grp in tmp.groupby([platform_col, "venue_type"]):
        daily_disp = grp.groupby(date_col)["_rate"].std() * 10_000
        records.append(
            {
                "venue": venue,
                "venue_type": vtype,
                "median_daily_dispersion_bps": daily_disp.median(),
                "trade_count": len(grp),
            }
        )

    if not records:
        return pd.DataFrame(
            columns=["venue", "venue_type", "median_daily_dispersion_bps", "trade_count"]
        )

    return pd.DataFrame(records).sort_values(
        "median_daily_dispersion_bps", ascending=True
    )


# ---------------------------------------------------------------------------
# Composite liquidity scorer
# ---------------------------------------------------------------------------

_EPS = 1e-10  # avoid division by zero in normalisation


class LiquidityScorer(SDRAnalyzer):
    """Composite liquidity score per benchmark tenor, normalised 0-100.

    For each tenor computes four raw metrics:

    - **dispersion_bps** -- median daily std-dev of fixed rate (bps)
    - **median_tick_bps** -- median absolute consecutive-rate delta (bps)
    - **median_daily_dv01** -- median daily total DV01
    - **median_daily_count** -- median daily trade count

    Metrics are normalised across tenors:

    - *Lower-is-better* (dispersion, tick): ``100 * (1 - (x - min) / (max - min))``
    - *Higher-is-better* (DV01, count): ``100 * (x - min) / (max - min)``

    The composite score is the unweighted mean of the four normalised
    scores.

    Args:
        df: DataFrame with trade data (should already be filtered to
            new-risk trades with valid rates).
        benchmark_tenors: Tenors to score.
        rate_col: Column containing the fixed rate.
        tenor_col: Column containing tenor labels.
        date_col: Column containing execution dates.
        ts_col: Column containing execution timestamps.
        value_col: Column containing DV01 (or similar value metric).
        min_trades: Minimum trades required per tenor to produce a score.
    """

    def __init__(
        self,
        df: pd.DataFrame,
        *,
        benchmark_tenors: Sequence[str] = BENCHMARK_TENORS,
        rate_col: str = "fixed_rate",
        tenor_col: str = "tenor_label",
        date_col: str = "execution_date",
        ts_col: str = "execution_timestamp",
        value_col: str = "dv01",
        min_trades: int = 10,
    ) -> None:
        super().__init__(df)
        self._benchmark_tenors = list(benchmark_tenors)
        self._rate_col = rate_col
        self._tenor_col = tenor_col
        self._date_col = date_col
        self._ts_col = ts_col
        self._value_col = value_col
        self._min_trades = min_trades

    # -- public API ----------------------------------------------------------

    def compute(self) -> pd.DataFrame:
        """Compute per-tenor liquidity scores.

        Returns:
            DataFrame indexed by tenor with raw metrics, normalised
            sub-scores, and a ``composite_score`` column.
        """
        records = []
        rate = pd.to_numeric(self._df[self._rate_col], errors="coerce")
        tmp = self._df.assign(_rate=rate)

        for tenor in self._benchmark_tenors:
            t = tmp[tmp[self._tenor_col] == tenor]
            if len(t) < self._min_trades:
                continue

            disp = (
                t.groupby(self._date_col)["_rate"].std().median() * 10_000
            )

            t_sorted = t.sort_values(self._ts_col)
            tick_data = t_sorted["_rate"].diff().abs() * 10_000
            tick_data = tick_data[tick_data > 0]
            tick_med = tick_data.median() if len(tick_data) > 0 else np.nan

            avg_daily_dv01 = (
                t.groupby(self._date_col)[self._value_col].sum().median()
            )
            daily_count = t.groupby(self._date_col).size().median()

            records.append(
                {
                    "tenor": tenor,
                    "dispersion_bps": disp,
                    "median_tick_bps": tick_med,
                    "median_daily_dv01": avg_daily_dv01,
                    "median_daily_count": daily_count,
                }
            )

        if not records:
            self._result = pd.DataFrame(
                columns=[
                    "tenor",
                    "dispersion_bps",
                    "median_tick_bps",
                    "median_daily_dv01",
                    "median_daily_count",
                    "composite_score",
                ]
            )
            return self._result

        score_df = pd.DataFrame(records).set_index("tenor")

        # Normalise: lower-is-better metrics
        for col in ("dispersion_bps", "median_tick_bps"):
            if col in score_df.columns:
                cmin = score_df[col].min()
                cmax = score_df[col].max()
                score_df[f"{col}_score"] = 100 * (
                    1 - (score_df[col] - cmin) / (cmax - cmin + _EPS)
                )

        # Normalise: higher-is-better metrics
        for col in ("median_daily_dv01", "median_daily_count"):
            if col in score_df.columns:
                cmin = score_df[col].min()
                cmax = score_df[col].max()
                score_df[f"{col}_score"] = 100 * (
                    (score_df[col] - cmin) / (cmax - cmin + _EPS)
                )

        score_cols = [c for c in score_df.columns if c.endswith("_score")]
        score_df["composite_score"] = score_df[score_cols].mean(axis=1)

        self._result = score_df
        return self._result

    def summary(self) -> Dict[str, Any]:
        """Return key liquidity metrics.

        Returns:
            Dict with ``most_liquid``, ``least_liquid``, and
            ``median_score``.
        """
        if self._result is None:
            self._result = self.compute()

        if self._result.empty or "composite_score" not in self._result.columns:
            return {
                "most_liquid": None,
                "least_liquid": None,
                "median_score": np.nan,
            }

        scores = self._result["composite_score"]
        return {
            "most_liquid": scores.idxmax(),
            "least_liquid": scores.idxmin(),
            "median_score": float(scores.median()),
        }
