# scripts/sv_static_long_control.py
"""The Citi-style static-long reproduction. This is the gate on the greeks.

Buys the flattener, rebalances at the trigger, rolls annually, holds throughout.
Reports the DISTRIBUTION -- skew, correlation of monthly P&L to changes in
implied vol -- because that, not the Sharpe, is what a long-vol position must
look like.

The roll is implemented by SEGMENTATION: one ``CurvePricer`` and one
``simulate`` call per roll period, each holding one package aged from its own
inception curve, with consecutive periods sharing their boundary date. That is
what "rolls annually" means physically -- on the roll date the old package is
unwound at its mark and a new one is struck at par -- and it keeps the aging
inside ``CurvePricer``, whose contract is "these legs, aged", instead of asking
it to swap its legs mid-flight. P&L is a flow, so concatenating the periods
loses nothing: the old package's accumulated mark was already banked day by day
before the roll, and the boundary date's P&L comes from the period that still
held the old package while the new period contributes only the roll cost.

``ReplicationConfig.roll_months`` is therefore set out of reach inside each
segment (``_NEVER_ROLL_MONTHS``): its notional-reset-plus-fee is not a roll on
real curves, because ``CurvePricer`` would go on pricing the same aged legs
afterwards.
"""
from __future__ import annotations

import datetime as dt
from typing import List, Sequence, Tuple

import pandas as pd

from RVUtils.StrikelessVol.conventions import FLATTENER
from RVUtils.StrikelessVol.costs import CostSchedule
from RVUtils.StrikelessVol.panels import vol_panel
from RVUtils.StrikelessVol.replication import (
    CurvePricer,
    ReplicationConfig,
    reconcile,
    simulate,
)
from RVUtils.StrikelessVol.report import distribution_stats, vol_beta
from RVUtils.StrikelessVol.universe import ALL_PAIRS, MARKET_CURVES

# Long enough that simulate's internal roll can never fire inside a segment.
_NEVER_ROLL_MONTHS = 12_000

VOL_CURVE_KEYS = {
    "USD": "USD-SOFR-1D",
    "EUR": "EUR-ESTR",
    "JPY": "JPY-TONAR",
    "GBP": "GBP-SONIA",
}

_FLOW_COLS = ["carry", "harvest", "mtm", "cross", "cost", "n_hedges"]
_STATE_COLS = ["long_notional", "short_notional", "position_age_years"]


def roll_segments(dates: Sequence, roll_months: int = 12) -> List[Tuple[int, int]]:
    """Inclusive index ranges of the roll periods, overlapping by one date.

    Segment ``k`` ends on the same date segment ``k+1`` starts, because that
    date is the roll: the old package is held through it (so its P&L belongs
    to segment ``k``) and the new one is struck on its curve (so it prices
    from segment ``k+1``'s second row onward). Without the overlap the roll
    date would contribute no P&L at all -- one lost business day per year.
    """
    dates = list(dates)
    if len(dates) < 2:
        return [(0, len(dates) - 1)] if dates else []
    bounds: List[Tuple[int, int]] = []
    i = 0
    last = len(dates) - 1
    while i < last:
        due = pd.Timestamp(dates[i]) + pd.DateOffset(months=roll_months)
        j = i + 1
        while j < last and pd.Timestamp(dates[j]) < due:
            j += 1
        bounds.append((i, j))
        i = j
    return bounds


def _stitch(frames: Sequence[pd.DataFrame]) -> pd.DataFrame:
    """Concatenate segment ledgers, summing flows on the shared roll dates."""
    if not frames:
        return pd.DataFrame()
    stacked = pd.concat(frames)
    out = stacked.groupby(level=0)[_FLOW_COLS].sum()
    out[_STATE_COLS] = stacked.groupby(level=0)[_STATE_COLS].last()
    out["total"] = out[["carry", "harvest", "mtm", "cross", "cost"]].sum(axis=1)
    return out.sort_index()


def run_control(
    *,
    market: str = "USD",
    start: dt.date,
    end: dt.date,
    trigger_bp: float = 25.0,
    roll_months: int = 12,
    package_dv01_usd: float = 100_000.0,
    sign: int = FLATTENER,
    costs: CostSchedule | None = None,
    curve_map: dict | None = None,
    pair=None,
    with_vol: bool = True,
) -> dict:
    """Run the static-long control and report its distribution.

    ``curve_map`` may be supplied to reuse an already-fetched set of curves
    (the fetch dominates the runtime); otherwise it is pulled from GSQUANT-RL.
    ``pair`` defaults to the headline 10Y10Y/20Y10Y slope for ``market``.
    """
    costs = costs or CostSchedule()
    if pair is None:
        pair = next(p for p in ALL_PAIRS if p.market == market
                    and p.short.label == "10Y10Y" and p.long.label == "20Y10Y")

    requested = None
    if curve_map is None:
        from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

        dates = pd.bdate_range(start, end).date.tolist()
        requested = len(dates)
        mdp = IRSwapsMDP(source="GSQUANT-RL")
        curve_map = mdp.bulk_get_data(
            {"curve_name": MARKET_CURVES[market], "timestamps": dates}
        )
    curve_map = {pd.Timestamp(k): v for k, v in curve_map.items()
                 if v is not None and k != "live"}
    # A ``bdate_range`` legitimately contains ~10 market holidays a year that no
    # provider serves (~4%), so a small shortfall is normal. A large one is a
    # provider failure, and reporting a distribution on the sample that
    # survived it would be reporting a different strategy than the one asked
    # for -- mirrors ``panels.forward_rate_panel``'s ``max_missing_frac``.
    if not curve_map or (requested and len(curve_map) < 0.8 * requested):
        raise ValueError(
            f"Only {len(curve_map)}/{requested} {MARKET_CURVES[market]} curves for "
            f"{start}..{end}. That is a systemic provider failure, not a holiday "
            "calendar; refusing to report a control on a silently shrunk sample."
        )
    all_dates = sorted(curve_map)

    cfg = ReplicationConfig(
        trigger_bp=trigger_bp,
        roll_months=_NEVER_ROLL_MONTHS,
        package_dv01_usd=package_dv01_usd,
        sign=sign,
    )
    frames: List[pd.DataFrame] = []
    for k, (i, j) in enumerate(roll_segments(all_dates, roll_months)):
        seg_dates = all_dates[i:j + 1]
        ctx = CurvePricer(
            {d: curve_map[d] for d in seg_dates}, pair,
            package_dv01_usd=package_dv01_usd, sign=sign,
        )
        led = simulate(ctx, seg_dates, cfg, costs)
        if k:
            # Not a fresh trade: the previous package is unwound into this one.
            led.iloc[0, led.columns.get_loc("cost")] = -costs.cost_usd(
                "roll", abs(package_dv01_usd)
            )
        frames.append(led)
    led = _stitch(frames)

    out = {
        "pair": pair.name,
        "market": market,
        "start": all_dates[0].date(),
        "end": all_dates[-1].date(),
        "n_days": int(len(led)),
        "n_segments": len(frames),
        "daily_pnl": led["total"],
        "ledger": led,
        "stats": distribution_stats(led["total"]),
        "reconciliation": reconcile(led),
        "harvest_to_mtm": float(
            led["harvest"].abs().sum() / max(led["mtm"].abs().sum(), 1e-9)
        ),
        "vol_corr": float("nan"),
        "vol_beta": float("nan"),
        "vol_n": 0,
    }
    if not with_vol:
        return out

    vols = vol_panel(VOL_CURVE_KEYS[market], ["1y 10y"], start, end)
    monthly_pnl = led["total"].resample("ME").sum()
    monthly_dvol = vols["1y10y"].resample("ME").last().diff()
    vb = vol_beta(monthly_pnl, monthly_dvol)
    out["vol_corr"] = vb["corr"]
    out["vol_beta"] = vb["beta"]
    out["vol_n"] = vb["n"]
    out["monthly_pnl"] = monthly_pnl
    out["monthly_dvol"] = monthly_dvol
    return out


def _print(res: dict) -> None:
    print(res["pair"], f"{res['start']}..{res['end']}",
          f"n={res['n_days']} days, {res['n_segments']} roll periods")
    print(pd.Series(res["stats"]))
    print("monthly P&L corr to d(1y10y vol):", round(res["vol_corr"], 3),
          f"(beta {res['vol_beta']:,.0f} $/bp-of-vol, n={res['vol_n']} months)")
    print("harvest / |mtm|:", round(res["harvest_to_mtm"], 4))
    print("ledger totals ($):")
    print(res["ledger"][["carry", "harvest", "mtm", "cross", "cost", "total"]].sum())
    print("hedges:", int(res["ledger"]["n_hedges"].sum()))
    print("reconciliation:", res["reconciliation"])


if __name__ == "__main__":
    res = run_control(market="USD", start=dt.date(2017, 1, 3), end=dt.date(2026, 8, 3))
    _print(res)
