# scripts/sv_static_long_control.py
"""The Citi-style static-long reproduction, and the control on the greeks.

Buys the flattener, rebalances at the trigger, rolls annually, holds throughout.

**What this control did and did not establish (Task 13, read this before
quoting it).** It runs end to end on real curves, it is directionally correct
(measured, not asserted: P&L regresses on the pair's slope at -$89,910/bp
against a -$100,000 design, R^2 0.956), its levels reproduce the desk anchors
(spread -57bp, roll -$2,400/day, Gamma 204 $/bp^2), and its Sharpe SPREAD
across pairs reproduces the published 0.05-0.35 band (+0.247 / +0.046 /
-0.279 on the three USD pairs).

It did **not** reproduce a distributional signature that identifies long
convexity, because no such signature was available from the criteria
originally specified. Daily P&L skew, the monthly correlation to changes in
implied vol, and the Sharpe were each measured against two null models --
the short-convexity steepener and the DV01-matched zero-convexity twin
(:class:`replication.ZeroConvexityPricer`) -- and **all three criteria are
cleared by books with no long convexity in them**, the twin scoring better
than the real package on every one. ``vol_corr`` in particular is a property
of the market's slope/vol comovement that anything carrying this DV01
inherits; it is not a property of gamma.

The statistics that do separate them, and the ones downstream work should
rank on, are :func:`report.residual_stats`' ``resid_skew`` (the shape left
after the linear slope term is removed), the SIGN OF CARRY, and the harvest
flow ratio. See the Task 13 report for the five-way comparison.

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
from RVUtils.StrikelessVol.conventions import slope_bp
from RVUtils.StrikelessVol.replication import (
    CurvePricer,
    ReplicationConfig,
    ZeroConvexityPricer,
    reconcile,
    simulate,
)
from RVUtils.StrikelessVol.report import (
    distribution_stats,
    residual_stats,
    vol_beta,
)
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


def constant_maturity_spread(curve_map: dict, dates: Sequence, pair) -> pd.Series:
    """The pair's constant-maturity slope in bp, one point per date.

    This is the linear term :func:`report.residual_stats` removes, and it must
    be the PAIR'S OWN slope -- a placebo pair regressed against the study
    pair's slope would have most of its variance left in the residual and the
    comparison would mean nothing.
    """
    return pd.Series(
        [
            float(slope_bp(
                short_rate=curve_map[d].fair_rate(
                    curve_map[d].build_irswap(fwd=pair.short.fwd, tenor=pair.short.tail)),
                long_rate=curve_map[d].fair_rate(
                    curve_map[d].build_irswap(fwd=pair.long.fwd, tenor=pair.long.tail)),
            ))
            for d in dates
        ],
        index=list(dates),
        name="spread_bp",
    )


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
    roll_charge_kind: str = "roll",
    zero_convexity: bool = False,
) -> dict:
    """Run the static-long control and report its distribution.

    ``curve_map`` may be supplied to reuse an already-fetched set of curves
    (the fetch dominates the runtime); otherwise it is pulled from GSQUANT-RL.
    ``pair`` defaults to the headline 10Y10Y/20Y10Y slope for ``market``.

    ``roll_charge_kind`` selects what an annual roll is charged as. The default
    ``"roll"`` (0.35bp) follows the research brief's cost prior, but a roll
    unwinds two legs and strikes two new ones, which is strictly more trading
    than the single ``"initiate"`` (0.875bp) charge -- and the difference is
    not academic: 9 rolls x 0.525bp x $100k is $472,500, i.e. **67% of the
    headline lifetime P&L**. Both conventions are reported side by side rather
    than one being picked silently.

    ``zero_convexity=True`` swaps :class:`CurvePricer` for
    :class:`ZeroConvexityPricer`, giving the DV01-matched null model with no
    aging, no gamma and no carry. Use it to check whether a statistic detects
    convexity or merely the slope exposure that both books share. The twin
    does not age, so it runs as a single segment regardless of ``roll_months``
    and is charged only the initial trade.
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
    # The twin does not age, so there is nothing to roll: one segment.
    segments = ([(0, len(all_dates) - 1)] if zero_convexity
                else roll_segments(all_dates, roll_months))
    frames: List[pd.DataFrame] = []
    rates: dict = {}
    for k, (i, j) in enumerate(segments):
        seg_dates = all_dates[i:j + 1]
        maker = ZeroConvexityPricer if zero_convexity else CurvePricer
        ctx = maker(
            {d: curve_map[d] for d in seg_dates}, pair,
            package_dv01_usd=package_dv01_usd, sign=sign,
        )
        led = simulate(ctx, seg_dates, cfg, costs)
        if k:
            # Not a fresh trade: the previous package is unwound into this one.
            led.iloc[0, led.columns.get_loc("cost")] = -costs.cost_usd(
                roll_charge_kind, abs(package_dv01_usd)
            )
        frames.append(led)
        # Read the constant-maturity rates off the pricer rather than
        # rebuilding them afterwards: the long leg's are already cached there
        # (simulate asks for one per date to run the trigger), so only the
        # short leg is new work. Rebuilding both from the curves afterwards
        # doubled the runtime of every call for an identical answer.
        for d in seg_dates:
            rates[d] = (ctx.rate(d, "short"), ctx.rate(d, "long"))
    led = _stitch(frames)

    spread_bp = pd.Series(
        {d: float(slope_bp(short_rate=s, long_rate=l)) for d, (s, l) in rates.items()},
        name="spread_bp",
    ).sort_index()

    out = {
        "pair": pair.name,
        "market": market,
        "start": all_dates[0].date(),
        "end": all_dates[-1].date(),
        "n_days": int(len(led)),
        "n_segments": len(frames),
        "daily_pnl": led["total"],
        "ledger": led,
        "spread_bp": spread_bp,
        "stats": distribution_stats(led["total"]),
        "residual": residual_stats(led["total"], spread_bp.diff()),
        "reconciliation": reconcile(led),
        # NOT a share of P&L -- a ratio of GROSS DAILY ABSOLUTE FLOWS, i.e. how
        # much of the book's daily movement comes from the resize increments
        # relative to the base position. Renamed from "harvest_to_mtm" after
        # review, which correctly pointed out that the old name read as a
        # contribution share and this is not one. Both are reported.
        "harvest_flow_ratio": float(
            led["harvest"].abs().sum() / max(led["mtm"].abs().sum(), 1e-9)
        ),
        "harvest_usd": float(led["harvest"].sum()),
        # A genuine contribution share: harvest against the summed magnitudes
        # of the three P&L buckets, so it is bounded and signed.
        "harvest_pnl_share": float(
            led["harvest"].sum()
            / max(abs(led["carry"].sum()) + abs(led["harvest"].sum())
                  + abs(led["mtm"].sum()), 1e-9)
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


def _print(res: dict, label: str = "") -> None:
    print(f"{label}{res['pair']}", f"{res['start']}..{res['end']}",
          f"n={res['n_days']} days, {res['n_segments']} roll periods")
    print(pd.Series(res["stats"]))
    print("monthly P&L corr to d(1y10y vol):", round(res["vol_corr"], 4),
          f"(beta {res['vol_beta']:,.0f} $/bp-of-vol, n={res['vol_n']} months)")
    r = res["residual"]
    print(f"residual (P&L less its linear d(spread) term): skew {r['resid_skew']:+.4f} "
          f"kurt {r['resid_kurtosis']:.2f} beta {r['beta']:,.0f} $/bp R2 {r['r2']:.4f}")
    print("harvest flow ratio (gross flows, NOT a P&L share):",
          round(res["harvest_flow_ratio"], 4),
          "| harvest $", f"{res['harvest_usd']:,.0f}",
          "| harvest share of |P&L| buckets:", round(res["harvest_pnl_share"], 4))
    print("ledger totals ($):")
    print(res["ledger"][["carry", "harvest", "mtm", "cross", "cost", "total"]].sum())
    print("hedges:", int(res["ledger"]["n_hedges"].sum()))
    print("reconciliation:", res["reconciliation"])


if __name__ == "__main__":
    START, END = dt.date(2017, 1, 3), dt.date(2026, 8, 3)
    res = run_control(market="USD", start=START, end=END)
    _print(res)
    # The null model, printed alongside on purpose: every distributional
    # criterion the original gate used is cleared by this book, which has no
    # convexity in it at all. Only the residual separates them.
    twin = run_control(market="USD", start=START, end=END, zero_convexity=True,
                       curve_map=None)
    _print(twin, label="ZERO-CONVEXITY TWIN | ")
