"""
Term Funding Premium (TFP) and SOFR Swap Spread Term Structure Analytics.

Implements the JPM framework from "Term Funding Premium and the Term Structure
of SOFR Swap Spreads" (Apr 2024) and Dallas Fed WP 2613 (May 2026).

On each day, regress maturity-matched swap spreads at benchmark tenors
(2Y, 3Y, 5Y, 7Y, 10Y, 20Y, 30Y) against modified durations:

    swap_spread_m = slope * mod_dur_m + intercept + epsilon_m

    TFP  = -slope     (bp per year of modified duration)
    ZDS  = intercept  (zero-duration swap spread, bp)
    baseline_m = slope * mod_dur_m + intercept
    deviation_m = actual_m - baseline_m  (mean-reverting residual)
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

BENCHMARK_TENORS: List[str] = ["2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y"]

REGRESSION_TENORS: List[str] = ["2Y", "3Y", "5Y", "7Y", "10Y", "30Y"]

CT_MAP: Dict[str, str] = {
    "2Y": "CT2",
    "3Y": "CT3",
    "5Y": "CT5",
    "7Y": "CT7",
    "10Y": "CT10",
    "20Y": "CT20",
    "30Y": "CT30",
}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class TFPSnapshot:
    """Single-date cross-sectional TFP analysis."""

    date: Optional[datetime.date]
    tfp: float
    zds: float
    slope: float
    r_squared: float
    tenors: List[str]
    swap_spreads: Dict[str, float]
    mod_durations: Dict[str, float]
    baselines: Dict[str, float]
    deviations: Dict[str, float]

    def baseline_spread(self, mod_dur: float) -> float:
        return self.slope * mod_dur + self.zds

    def to_dict(self) -> dict:
        rec: dict = {
            "date": self.date,
            "tfp": self.tfp,
            "zds": self.zds,
            "slope": self.slope,
            "r_squared": self.r_squared,
        }
        for t in self.tenors:
            rec[f"mmss_{t}"] = self.swap_spreads.get(t)
            rec[f"dur_{t}"] = self.mod_durations.get(t)
            rec[f"baseline_{t}"] = self.baselines.get(t)
            rec[f"dev_{t}"] = self.deviations.get(t)
        return rec


# ---------------------------------------------------------------------------
# Core computation (pure math, no data dependencies)
# ---------------------------------------------------------------------------

def compute_tfp_regression(
    swap_spreads: Dict[str, float],
    mod_durations: Dict[str, float],
    tenors: Optional[List[str]] = None,
) -> TFPSnapshot:
    """Cross-sectional OLS: swap_spread = slope * mod_dur + intercept.

    Parameters
    ----------
    swap_spreads : dict
        Tenor -> maturity-matched swap spread (bp).
    mod_durations : dict
        Tenor -> modified duration (years).
    tenors : list, optional
        Subset of tenors to use.  Defaults to the intersection of both dicts.

    Returns
    -------
    TFPSnapshot with TFP = -slope, ZDS = intercept, baselines, deviations.
    """
    if tenors is None:
        tenors = sorted(set(swap_spreads) & set(mod_durations))
    if len(tenors) < 3:
        raise ValueError(f"Need >=3 tenors for regression, got {len(tenors)}")

    x = np.array([mod_durations[t] for t in tenors], dtype=np.float64)
    y = np.array([swap_spreads[t] for t in tenors], dtype=np.float64)

    A = np.column_stack([x, np.ones_like(x)])
    coeffs, *_ = np.linalg.lstsq(A, y, rcond=None)
    slope, intercept = coeffs

    y_hat = A @ coeffs
    ss_res = float(np.sum((y - y_hat) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r_sq = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

    baselines = {t: slope * mod_durations[t] + intercept for t in tenors}
    devs = {t: swap_spreads[t] - baselines[t] for t in tenors}

    return TFPSnapshot(
        date=None,
        tfp=-slope,
        zds=intercept,
        slope=slope,
        r_squared=r_sq,
        tenors=list(tenors),
        swap_spreads=dict(swap_spreads),
        mod_durations=dict(mod_durations),
        baselines=baselines,
        deviations=devs,
    )


# ---------------------------------------------------------------------------
# Data fetching via TimeseriesBuilder + UnifiedQuery (batch, parallel, cached)
# ---------------------------------------------------------------------------

def build_tfp_history(
    start_date: datetime.date,
    end_date: datetime.date,
    curve_mdp=None,
    usts_mdp=None,
    *,
    cache_path: Optional[str] = None,
    tenors: Optional[List[str]] = None,
    regression_tenors: Optional[List[str]] = None,
    curve_name: str = "USD-SOFR-1D",
    n_jobs: int = 12,
    show_progress: bool = True,
) -> pd.DataFrame:
    """Build historical TFP time-series using TimeseriesBuilder.

    Parameters
    ----------
    curve_mdp : IRSwapsMDP
        E.g. ``IRSwapsMDP(source="ERIS_EOD_LIVE-RL_BASIC")``.
    usts_mdp : FixedRateBondsMDP
        E.g. ``FixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-RL")``.
    cache_path : str, optional
        Parquet path for caching the computed TFP DataFrame.
    tenors : list, optional
        Tenors to **fetch** data for. Defaults to BENCHMARK_TENORS (all 7).
    regression_tenors : list, optional
        Subset of *tenors* used in the cross-sectional regression.
        Defaults to REGRESSION_TENORS (ex-20Y).  Data for excluded tenors
        is still fetched; baselines and deviations are computed for all.

    Returns
    -------
    DataFrame indexed by date with columns:
        tfp, zds, slope, r_squared,
        mmss_{tenor}, dur_{tenor}, baseline_{tenor}, dev_{tenor}
    """
    if cache_path and Path(cache_path).exists():
        cached_df = pd.read_parquet(cache_path)
        cached_df.index = pd.to_datetime(cached_df.index)
        if not cached_df.empty:
            last_cached = cached_df.index.max()
            if last_cached >= pd.Timestamp(end_date):
                return cached_df.loc[:pd.Timestamp(end_date)].sort_index()
            start_date = last_cached.date() + datetime.timedelta(days=1)
    else:
        cached_df = None

    import pytz
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP
    from TB.IRSwapsTB import IRSwapsTB
    from TB.FixedRateBondsTB import FixedRateBondsTB
    from TB.TimeseriesBuilder import TimeseriesBuilder
    from Query.Unified.UnifiedQuery import UnifiedQuery
    from Query.Unified.registry import UnifiedValue

    if curve_mdp is None:
        curve_mdp = IRSwapsMDP(source="ERIS_EOD_LIVE-RL_BASIC")
    if usts_mdp is None:
        usts_mdp = FixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-RL")

    if tenors is None:
        tenors = BENCHMARK_TENORS
    if regression_tenors is None:
        regression_tenors = REGRESSION_TENORS

    NYC = pytz.timezone("America/New_York")
    ts_start = NYC.localize(
        datetime.datetime.combine(start_date, datetime.time(17, 0))
    )
    ts_end = NYC.localize(
        datetime.datetime.combine(end_date, datetime.time(17, 0))
    )

    queries: list = []
    for t in tenors:
        ct = CT_MAP[t]
        queries.append(
            UnifiedQuery(curve=curve_name, tenor=ct, value=UnifiedValue.IRS_MMSS)
        )
        queries.append(
            UnifiedQuery(cusip=ct, value=UnifiedValue.FRB_MOD_DURATION)
        )

    ts_builder = TimeseriesBuilder()
    routers = {
        "IRS": IRSwapsTB(curve_mdp, show_tqdm=show_progress),
        "FRB": FixedRateBondsTB(usts_mdp, show_tqdm=show_progress),
    }

    raw = ts_builder.get_timeseries(
        start=ts_start,
        end=ts_end,
        queries=queries,
        n_jobs=n_jobs,
        routers=routers,
    )

    if raw.empty:
        logger.warning("TimeseriesBuilder returned empty DataFrame")
        return cached_df if cached_df is not None else pd.DataFrame()

    mmss_cols = {
        t: [c for c in raw.columns if CT_MAP[t] in c and "MMSS" in c]
        for t in tenors
    }
    dur_cols = {
        t: [c for c in raw.columns if CT_MAP[t] in c and "MOD_DURATION" in c]
        for t in tenors
    }

    records: list[dict] = []
    for idx in raw.index:
        row = raw.loc[idx]
        spreads: Dict[str, float] = {}
        durations: Dict[str, float] = {}
        for t in tenors:
            mc = mmss_cols.get(t, [])
            dc = dur_cols.get(t, [])
            if mc and pd.notna(row[mc[0]]):
                spreads[t] = float(row[mc[0]])
            if dc and pd.notna(row[dc[0]]):
                durations[t] = abs(float(row[dc[0]]))

        reg_available = sorted(
            set(regression_tenors) & set(spreads) & set(durations)
        )
        if len(reg_available) < 3:
            continue

        try:
            snap = compute_tfp_regression(
                spreads, durations, tenors=reg_available
            )
        except ValueError:
            continue

        for t in tenors:
            if t not in reg_available and t in durations and t in spreads:
                snap.baselines[t] = snap.slope * durations[t] + snap.zds
                snap.deviations[t] = spreads[t] - snap.baselines[t]
                snap.swap_spreads[t] = spreads[t]
                snap.mod_durations[t] = durations[t]
                if t not in snap.tenors:
                    snap.tenors.append(t)

        d = idx.date() if hasattr(idx, "date") else idx
        snap.date = d
        records.append(snap.to_dict())

    if not records:
        return cached_df if cached_df is not None else pd.DataFrame()

    new_df = pd.DataFrame(records).set_index("date")
    new_df.index = pd.to_datetime(new_df.index)

    if cached_df is not None:
        cached_df.index = pd.to_datetime(cached_df.index)
        df = pd.concat([cached_df, new_df]).sort_index()
        df = df[~df.index.duplicated(keep="last")]
    else:
        df = new_df.sort_index()

    if cache_path:
        Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(cache_path)

    return df


# ---------------------------------------------------------------------------
# Z-score and signal generation
# ---------------------------------------------------------------------------

def deviation_columns(
    df: pd.DataFrame,
    tenors: Optional[List[str]] = None,
) -> List[str]:
    if tenors is None:
        tenors = BENCHMARK_TENORS
    return [f"dev_{t}" for t in tenors if f"dev_{t}" in df.columns]


def compute_deviation_zscores(
    history_df: pd.DataFrame,
    window: int = 60,
    tenors: Optional[List[str]] = None,
) -> pd.DataFrame:
    """Rolling z-scores of deviations from the fitted term structure."""
    dev_cols = deviation_columns(history_df, tenors)
    devs = history_df[dev_cols]

    mu = devs.rolling(window, min_periods=max(window // 2, 10)).mean()
    sigma = devs.rolling(window, min_periods=max(window // 2, 10)).std()

    z = (devs - mu) / sigma.replace(0, np.nan)
    z.columns = [c.replace("dev_", "z_") for c in z.columns]
    return z


def generate_signals(
    zscores: pd.DataFrame,
    z_entry: float = 1.5,
    z_exit: float = 0.0,
    tenors: Optional[List[str]] = None,
) -> pd.DataFrame:
    """Mean-reversion signals from deviation z-scores.

    Output per tenor:
        -1  pay spread   (deviation too positive, expect widening)
        +1  receive spread (deviation too negative, expect narrowing)
         0  flat
    """
    if tenors is None:
        tenors = BENCHMARK_TENORS

    sigs = pd.DataFrame(index=zscores.index)

    for tenor in tenors:
        zcol = f"z_{tenor}"
        if zcol not in zscores.columns:
            continue
        z = zscores[zcol].values
        n = len(z)
        sig = np.zeros(n, dtype=np.int8)
        pos = 0
        for i in range(n):
            v = z[i]
            if np.isnan(v):
                sig[i] = 0
                pos = 0
                continue
            if pos == 0:
                if v > z_entry:
                    pos = -1
                elif v < -z_entry:
                    pos = 1
            elif pos == -1 and v <= z_exit:
                pos = 0
            elif pos == 1 and v >= -z_exit:
                pos = 0
            sig[i] = pos
        sigs[f"sig_{tenor}"] = sig

    return sigs


# ---------------------------------------------------------------------------
# Trigger / backtest helpers
# ---------------------------------------------------------------------------

def extract_entry_exit_events(
    signals: pd.DataFrame,
    tenor: str,
) -> List[dict]:
    """Convert signal series into a list of entry/exit event dicts.

    Each dict: {entry_date, exit_date, direction, tenor, tag}
    direction: +1 = receive spread (buy bond + receive fixed)
               -1 = pay spread    (sell bond + pay fixed)
    """
    col = f"sig_{tenor}"
    if col not in signals.columns:
        return []

    sig = signals[col]
    raw_dates = sig.index
    dates = [
        d.date() if hasattr(d, "date") else d for d in raw_dates
    ]
    events: list[dict] = []

    prev = 0
    entry_date = None
    direction = 0

    for i in range(len(sig)):
        cur = int(sig.iloc[i])
        if prev == 0 and cur != 0:
            entry_date = dates[i]
            direction = cur
        elif prev != 0 and cur == 0:
            events.append(
                {
                    "entry_date": entry_date,
                    "exit_date": dates[i],
                    "direction": direction,
                    "tenor": tenor,
                    "tag": f"tfp-{tenor}-{entry_date}",
                }
            )
            entry_date = None
            direction = 0
        elif prev != 0 and cur != 0 and cur != prev:
            events.append(
                {
                    "entry_date": entry_date,
                    "exit_date": dates[i],
                    "direction": direction,
                    "tenor": tenor,
                    "tag": f"tfp-{tenor}-{entry_date}",
                }
            )
            entry_date = dates[i]
            direction = cur
        prev = cur

    if entry_date is not None:
        events.append(
            {
                "entry_date": entry_date,
                "exit_date": dates[-1],
                "direction": direction,
                "tenor": tenor,
                "tag": f"tfp-{tenor}-{entry_date}",
            }
        )
    return events


def build_backtest_triggers(
    events: List[dict],
    risk_bpv: float = 100_000,
    unwind_fee_bps: float = 0.5,
    gc_fixing_pct: Optional[pd.Series] = None,
    specialness_bps: float = 10.0,
):
    """Build DateTrigger pairs (entry + exit) for QueryDrivenBacktest.

    Each entry trigger fires an AddQueryFactoryAction that creates two legs:
      1. FixedRateBondQuery  (bond leg, with GC repo financing)
      2. IRSwapQuery         (swap leg, opposite direction)

    Returns list of Trigger objects.
    """
    from BT.triggers import DateTrigger, DateTriggerRequirements
    from BT.query_actions import (
        AddQueryAction,
        AddQueryFactoryAction,
        UnwindPositionsAction,
    )
    from Query.FixedRateBonds.FixedRateBondQuery import FixedRateBondQuery
    from Query.FixedRateBonds.FixedRateBondValue import FixedRateBondValue
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapValue import IRSwapValue

    triggers = []

    for ev in events:
        tenor = ev["tenor"]
        direction = ev["direction"]
        tag = ev["tag"]
        entry_d = ev["entry_date"]
        exit_d = ev["exit_date"]
        ct = CT_MAP.get(tenor, tenor)

        bond_bpv = risk_bpv * direction
        swap_bpv = -risk_bpv * direction

        def _make_factory(ct_=ct, bond_bpv_=bond_bpv, swap_bpv_=swap_bpv,
                          tag_=tag, entry_d_=entry_d,
                          gc_fixing_=gc_fixing_pct,
                          spec_bps_=specialness_bps):
            def factory(now, backtest, info):
                from BT.query_actions import BuiltQuery

                gc_rate = 0.0
                if gc_fixing_ is not None:
                    d = now.date() if isinstance(now, datetime.datetime) else now
                    if d in gc_fixing_.index:
                        gc_rate = gc_fixing_[d] / 100.0
                    else:
                        idx = gc_fixing_.index.get_indexer([d], method="ffill")
                        if idx[0] >= 0:
                            gc_rate = gc_fixing_.iloc[idx[0]] / 100.0

                financing_config = {
                    "mode": "gc_plus_specialness",
                    "gc_rate": gc_rate,
                    "leg_specialness_bps": {"outright": spec_bps_},
                    "day_count": "ACT/360",
                    "haircut": 0.0,
                }

                bond_q = FixedRateBondQuery(
                    cusip=ct_,
                    value=FixedRateBondValue.NPV,
                    structure_kwargs={"bpv": bond_bpv_},
                )

                swap_q = IRSwapQuery(
                    curve="USD-SOFR-1D",
                    tenor=ct_.replace("CT", "") + "Y" if ct_.startswith("CT") else ct_,
                    value=IRSwapValue.NPV,
                    structure_kwargs={"bpv": swap_bpv_},
                )

                return [
                    BuiltQuery(
                        query=bond_q,
                        meta={
                            "tags": [tag_],
                            "leg": "bond",
                            "financing": financing_config,
                        },
                    ),
                    BuiltQuery(
                        query=swap_q,
                        meta={"tags": [tag_], "leg": "swap"},
                    ),
                ]
            return factory

        entry_trigger = DateTrigger(
            DateTriggerRequirements(dates=[entry_d]),
            actions=[
                AddQueryFactoryAction(
                    query_factory=_make_factory(),
                    risk=f"tfp_{tenor}",
                )
            ],
        )

        exit_trigger = DateTrigger(
            DateTriggerRequirements(dates=[exit_d]),
            actions=[
                UnwindPositionsAction(
                    match_tag=tag,
                    fee=unwind_fee_bps * risk_bpv,
                    risk=f"tfp_{tenor}",
                )
            ],
        )

        triggers.extend([entry_trigger, exit_trigger])

    return triggers


# ---------------------------------------------------------------------------
# CUSIP diagnostics
# ---------------------------------------------------------------------------

def diagnose_bond_resolution(
    date: datetime.date,
    usts_mdp=None,
    tenors: Optional[List[str]] = None,
) -> pd.DataFrame:
    """Show which CUSIPs resolve for each CT alias and their characteristics."""
    from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP

    if usts_mdp is None:
        usts_mdp = FixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-RL")
    if tenors is None:
        tenors = BENCHMARK_TENORS

    rows = []
    for t in tenors:
        ct = CT_MAP[t]
        try:
            pricers = usts_mdp.get_pricer({"cusips": [ct], "timestamp": date})
            for cusip, p in pricers.items():
                rows.append({
                    "Tenor": t,
                    "CT Alias": ct,
                    "CUSIP": cusip,
                    "Coupon": getattr(p, "coupon", None),
                    "Maturity": getattr(p, "maturity_date", None),
                    "Mod Dur": round(abs(p.mod_duration()), 2),
                    "YTM": round(p.ytm() * 100, 3) if hasattr(p, "ytm") else None,
                })
        except Exception as exc:
            rows.append({"Tenor": t, "CT Alias": ct, "CUSIP": f"ERROR: {exc}"})

    return pd.DataFrame(rows).set_index("Tenor")


# ---------------------------------------------------------------------------
# Screener helpers
# ---------------------------------------------------------------------------

def current_snapshot_table(snap: TFPSnapshot) -> pd.DataFrame:
    """Format a TFPSnapshot into a summary DataFrame for display."""
    rows = []
    for t in snap.tenors:
        rows.append(
            {
                "Tenor": t,
                "MMSS (bp)": round(snap.swap_spreads[t], 1),
                "Mod Dur (yr)": round(snap.mod_durations[t], 1),
                "Baseline (bp)": round(snap.baselines[t], 1),
                "Deviation (bp)": round(snap.deviations[t], 1),
            }
        )
    df = pd.DataFrame(rows).set_index("Tenor")
    return df


def deviation_heatmap_data(
    history_df: pd.DataFrame,
    tenors: Optional[List[str]] = None,
    resample: Optional[str] = "W",
) -> pd.DataFrame:
    """Pivot deviation columns into a (time x tenor) matrix for heatmaps."""
    dev_cols = deviation_columns(history_df, tenors)
    df = history_df[dev_cols].copy()
    df.columns = [c.replace("dev_", "") for c in df.columns]
    if resample:
        df = df.resample(resample).last()
    return df


def zscore_heatmap_data(
    zscores: pd.DataFrame,
    tenors: Optional[List[str]] = None,
    resample: Optional[str] = "W",
) -> pd.DataFrame:
    z_cols = [f"z_{t}" for t in (tenors or BENCHMARK_TENORS) if f"z_{t}" in zscores.columns]
    df = zscores[z_cols].copy()
    df.columns = [c.replace("z_", "") for c in df.columns]
    if resample:
        df = df.resample(resample).last()
    return df
