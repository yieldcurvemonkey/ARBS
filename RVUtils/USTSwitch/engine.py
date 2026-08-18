"""Daily mark-to-market backtest of an olds-vs-currents UST switch.

Position and units
------------------
The book holds **$1 of DV01 per bp on each leg**, long one issue and short another of the
same original-issue tenor but a different rank. For a DV01-matched pair the dollar P&L is

    dP = -D * d(y_long - y_short)

so with ``D = $1/bp`` a dollar IS a basis point and the equity curve is natively in bp,
which is what the trade is quoted in and what the study reports. Two consequences worth
stating rather than discovering later:

* The book is rebalanced to constant $1/bp daily. Holding entry-fixed notionals instead
  lets the two DV01s drift apart (~0.5% over a quarter, since both bonds age together),
  which would make the equity curve a blend of spread P&L and a slow outright position.
  The rebalancing trades are tiny and are not charged; that is an assumption, and
  ``dv01_drift_check`` in the analytics measures how much it is worth.
* The position is duration-neutral but not cash-neutral and not convexity-neutral. Both
  are second order over a one-cycle holding period at these maturities.

Fixed CUSIPs, always
--------------------
Positions are pinned to concrete CUSIPs at entry and never re-resolved. The alias series
``O10/CT10`` SPLICES at every auction: measured on the 2024-02-16 10y refunding it moved
-1.395bp day-over-day while the pair actually held moved -0.358bp. Differencing the alias
would have booked 1.04bp nobody earned, on a trade whose whole premium is 0.1-1.8bp.
``Query/FixedRateBonds/position_handler.py`` has the same hazard from the other side: a
held alias position gets re-marked with the NEW issue's price against the OLD issue's
cashflow schedule. Neither path is used here.

The clock
---------
Everything is indexed to the auction cycle, because that is the mechanism. A tenor's roll
date is the day its rank-0 CUSIP changes -- auction date + 1 business day, per
``_filter_and_rank_ref_df``. The premium a switch harvests is created at one auction and
released at the next, so "days since roll" is the trade's real calendar and calendar-month
seasonality is the secondary one.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from RVUtils.USTSwitch.carry import CarryConfig, daily_carry_bp, specialness_only_carry_bp
from RVUtils.USTSwitch.costs import CostModel, is_stressed

RANK_LABEL = {0: "CT", 1: "O", 2: "OO", 3: "OOO"}


# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SwitchConfig:
    """One cell of the grid."""

    tenor: int = 10
    #: The younger leg (lower rank) and the older leg (higher rank). rank_young < rank_old.
    rank_young: int = 0
    rank_old: int = 1
    #: +1 = LONG the old, SHORT the young. That is the classic switch: buy the cheap
    #: seasoned issue, sell the rich benchmark, and collect the premium when the benchmark
    #: is displaced at the next auction. -1 is the fade.
    direction: int = 1

    #: Business days after the roll to enter. 0 = the roll itself. The premium is created
    #: at the auction, so this is the single most important knob.
    entry_offset: int = 1
    #: "next_roll" exits entry_offset-equivalent days after the FOLLOWING roll;
    #: "fixed" exits after ``hold_days`` business days.
    exit_rule: str = "next_roll"
    exit_offset: int = 1
    hold_days: int = 21

    #: Optional entry filter on the z-score of the spread against its own trailing window.
    #: None disables it. Sign is applied in the direction of the trade.
    z_window: Optional[int] = None
    z_entry: Optional[float] = None

    cost_multiplier: float = 1.0
    financing_mode: str = "modelled"
    #: Control, not a trading choice -- keeps only the specialness term of the carry so the
    #: result can be split into "the part ARBS' flat-GC model already sees" and "the part
    #: only per-issue financing reveals".
    specialness_only_carry: bool = False

    #: Diagnostic: shift every entry by this many business days off the auction clock.
    #: A mechanism that is really about the auction must degrade when this is non-zero.
    placebo_shift: int = 0

    @property
    def name(self) -> str:
        d = "LONGOLD" if self.direction > 0 else "LONGCUR"
        z = f"_z{self.z_window}@{self.z_entry}" if self.z_window else ""
        ex = f"nr+{self.exit_offset}" if self.exit_rule == "next_roll" else f"{self.hold_days}d"
        pl = f"_pl{self.placebo_shift}" if self.placebo_shift else ""
        return (
            f"{self.tenor}Y_{RANK_LABEL[self.rank_young]}v{RANK_LABEL[self.rank_old]}"
            f"_{d}_e{self.entry_offset}_{ex}{z}{pl}_fin{self.financing_mode}"
            f"_c{self.cost_multiplier:g}"
        )

    @property
    def pair_label(self) -> str:
        return f"{RANK_LABEL[self.rank_young]}v{RANK_LABEL[self.rank_old]}"


@dataclass
class SwitchResult:
    config: SwitchConfig
    trades: pd.DataFrame
    daily: pd.DataFrame          # date-indexed: pnl_bp, price_bp, carry_bp, special_bp, equity_bp
    funnel: Dict[str, int] = field(default_factory=dict)

    @property
    def equity_bp(self) -> pd.Series:
        return self.daily["equity_bp"]


# --------------------------------------------------------------------------------------
# universe prep


def roll_dates(amap: pd.DataFrame, tenor: int) -> pd.DatetimeIndex:
    """Dates on which this tenor's on-the-run CUSIP changes -- the auction clock."""
    r0 = amap[(amap["tenor"] == tenor) & (amap["rank"] == 0)].sort_values("date")
    if r0.empty:
        return pd.DatetimeIndex([])
    changed = r0["cusip"] != r0["cusip"].shift(1)
    changed.iloc[0] = False  # the first observation is not a roll, just the window start
    return pd.DatetimeIndex(r0.loc[changed, "date"].values)


def build_leg_frames(panel: pd.DataFrame, tenor: int) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """(by_cusip_date, by_date_rank) views of one tenor's slice, both indexed for speed."""
    p = panel[panel["tenor"] == tenor].copy()
    p["date"] = pd.to_datetime(p["date"])
    by_cd = p.set_index(["cusip", "date"]).sort_index()
    by_dr = p.set_index(["date", "rank"]).sort_index()
    return by_cd, by_dr


# --------------------------------------------------------------------------------------
# the backtest


def run_switch(
    panel: pd.DataFrame,
    amap: pd.DataFrame,
    cfg: SwitchConfig,
    *,
    cost_model: Optional[CostModel] = None,
) -> SwitchResult:
    """Run one config. Returns per-trade rows and a daily bp equity curve."""
    cm = cost_model or CostModel(multiplier=cfg.cost_multiplier)
    carry_cfg = CarryConfig(
        mode=cfg.financing_mode, specialness_only=cfg.specialness_only_carry
    )

    by_cd, by_dr = build_leg_frames(panel, cfg.tenor)
    if by_dr.empty:
        return SwitchResult(cfg, pd.DataFrame(), _empty_daily(), {"no_panel_rows": 1})

    all_dates = pd.DatetimeIndex(sorted(by_dr.index.get_level_values(0).unique()))
    rolls = roll_dates(amap, cfg.tenor)
    rolls = rolls[(rolls >= all_dates.min()) & (rolls <= all_dates.max())]

    funnel = {
        "cycles": max(len(rolls) - 1, 0),
        "no_entry_date": 0,
        "leg_missing_at_entry": 0,
        "no_exit_date": 0,
        "short_history": 0,
        "z_filtered": 0,
        "traded": 0,
    }

    def bd_offset(d: pd.Timestamp, n: int) -> Optional[pd.Timestamp]:
        """n business days after d, on the panel's own date grid."""
        pos = all_dates.searchsorted(d, side="left")
        pos += n
        if pos < 0 or pos >= len(all_dates):
            return None
        return all_dates[pos]

    trades: List[dict] = []
    daily_parts: List[pd.DataFrame] = []

    for i in range(len(rolls) - 1):
        roll, next_roll = rolls[i], rolls[i + 1]
        entry = bd_offset(roll, cfg.entry_offset + cfg.placebo_shift)
        if entry is None or entry >= next_roll:
            funnel["no_entry_date"] += 1
            continue

        # pin the two CUSIPs at entry
        try:
            row_y = by_dr.loc[(entry, cfg.rank_young)]
            row_o = by_dr.loc[(entry, cfg.rank_old)]
        except KeyError:
            funnel["leg_missing_at_entry"] += 1
            continue
        if isinstance(row_y, pd.DataFrame):
            row_y = row_y.iloc[0]
        if isinstance(row_o, pd.DataFrame):
            row_o = row_o.iloc[0]
        cusip_y, cusip_o = str(row_y["cusip"]), str(row_o["cusip"])

        if cfg.exit_rule == "next_roll":
            exit_d = bd_offset(next_roll, cfg.exit_offset + cfg.placebo_shift)
        else:
            exit_d = bd_offset(entry, cfg.hold_days)
        if exit_d is None or exit_d <= entry:
            funnel["no_exit_date"] += 1
            continue
        exit_d = min(exit_d, all_dates[-1])

        try:
            leg_y = by_cd.loc[cusip_y].loc[entry:exit_d]
            leg_o = by_cd.loc[cusip_o].loc[entry:exit_d]
        except KeyError:
            funnel["leg_missing_at_entry"] += 1
            continue

        idx = leg_y.index.intersection(leg_o.index)
        if len(idx) < 3:
            funnel["short_history"] += 1
            continue
        leg_y, leg_o = leg_y.loc[idx], leg_o.loc[idx]

        # spread, in bp: OLD yield minus YOUNG yield. Positive = old is cheap (normal).
        s = (leg_o["YTM"] - leg_y["YTM"]) * 100.0

        if cfg.z_window and cfg.z_entry is not None:
            zs = _entry_zscore(by_dr, cfg, entry, all_dates)
            if zs is None or not np.isfinite(zs):
                funnel["z_filtered"] += 1
                continue
            # direction +1 (long old) wants the old to be CHEAP relative to its own
            # history, i.e. a HIGH spread. direction -1 wants the opposite.
            if cfg.direction > 0 and zs < cfg.z_entry:
                funnel["z_filtered"] += 1
                continue
            if cfg.direction < 0 and zs > -cfg.z_entry:
                funnel["z_filtered"] += 1
                continue

        # ---- daily P&L -------------------------------------------------------------
        # direction +1 = long old / short young. P&L = -D * d(y_long - y_short) with
        # long = old: pnl = -(ds). direction -1 flips it.
        price_bp = -cfg.direction * s.diff()

        long_leg = leg_o if cfg.direction > 0 else leg_y
        short_leg = leg_y if cfg.direction > 0 else leg_o
        # Carry is quoted per YEAR (bp of yield). Accrue it over the ACTUAL calendar gap
        # between marks on an ACT/360 money-market basis -- so a Friday-to-Monday mark
        # accrues three days of financing, not one. Getting this wrong biases every
        # long-weekend and holiday, which is a systematic ~40% of the calendar.
        yearfrac = pd.Series(idx, index=idx).diff().dt.days.astype(float) / 360.0
        carry_rate = daily_carry_bp(long_leg, short_leg, carry_cfg)
        special_rate = specialness_only_carry_bp(long_leg, short_leg)
        carry_bp = (carry_rate * yearfrac).fillna(0.0)
        special_bp = (special_rate * yearfrac).fillna(0.0)
        if carry_cfg.mode == "none":
            carry_bp = pd.Series(0.0, index=idx)
            special_bp = pd.Series(0.0, index=idx)

        # ---- costs -----------------------------------------------------------------
        md_y = float(leg_y["MOD_DURATION"].iloc[0])
        md_o = float(leg_o["MOD_DURATION"].iloc[0])
        rt = cm.round_trip_yield_bp(
            cfg.tenor, cfg.rank_old, cfg.rank_young, md_o, md_y,
            stressed=is_stressed(entry) or is_stressed(exit_d),
        )
        cost = pd.Series(0.0, index=idx)
        cost.iloc[0] = rt / 2.0
        cost.iloc[-1] = cost.iloc[-1] + rt / 2.0

        pnl = price_bp.fillna(0.0) + carry_bp - cost
        daily_parts.append(
            pd.DataFrame(
                {
                    "pnl_bp": pnl,
                    "price_bp": price_bp.fillna(0.0),
                    "carry_bp": carry_bp,
                    "special_bp": special_bp,
                    "cost_bp": cost,
                    "in_position": 1.0,
                },
                index=idx,
            )
        )

        funnel["traded"] += 1
        trades.append(
            {
                "cycle": i,
                "roll": roll,
                "next_roll": next_roll,
                "entry": idx[0],
                "exit": idx[-1],
                "held_days": (idx[-1] - idx[0]).days,
                "held_obs": len(idx),
                "cusip_young": cusip_y,
                "cusip_old": cusip_o,
                "spread_entry_bp": float(s.iloc[0]),
                "spread_exit_bp": float(s.iloc[-1]),
                "d_spread_bp": float(s.iloc[-1] - s.iloc[0]),
                "price_bp": float(price_bp.sum()),
                "carry_bp": float(carry_bp.sum()),
                "special_bp": float(special_bp.sum()),
                "cost_bp": float(rt),
                "gross_bp": float(price_bp.sum() + carry_bp.sum()),
                "net_bp": float(pnl.sum()),
                "mod_dur_young": md_y,
                "mod_dur_old": md_o,
                "financing_actual_frac": float(
                    pd.concat([leg_y["has_actual_financing"], leg_o["has_actual_financing"]]).mean()
                ) if "has_actual_financing" in leg_y.columns else np.nan,
            }
        )

    if not daily_parts:
        return SwitchResult(cfg, pd.DataFrame(), _empty_daily(), funnel)

    daily = pd.concat(daily_parts).groupby(level=0).sum()
    daily = daily.reindex(all_dates).fillna(0.0)
    daily["equity_bp"] = daily["pnl_bp"].cumsum()
    return SwitchResult(cfg, pd.DataFrame(trades), daily, funnel)


def _empty_daily() -> pd.DataFrame:
    return pd.DataFrame(
        columns=["pnl_bp", "price_bp", "carry_bp", "special_bp", "cost_bp", "in_position", "equity_bp"],
        index=pd.DatetimeIndex([], name="date"),
    )


def _entry_zscore(by_dr, cfg: SwitchConfig, entry: pd.Timestamp, all_dates) -> Optional[float]:
    """z-score of the CURRENT rank-pair spread against its own trailing window.

    Uses the RANK-indexed (alias) series deliberately: as a *signal* the question is
    "is the old cheap versus where a bond of this age normally trades", which is a
    statement about the rank slot, not about one CUSIP -- and a single CUSIP has no
    history at that rank before it reached it. The splice that makes the alias unusable
    for P&L is harmless for a level z-score, which never differences across it.
    """
    pos = all_dates.searchsorted(entry, side="left")
    lo = max(0, pos - cfg.z_window)
    win = all_dates[lo : pos + 1]
    if len(win) < max(20, cfg.z_window // 3):
        return None
    try:
        # `rank` is an INDEX level here, not a column -- asking for it in the column
        # selector raises KeyError. Select the value only and recover the level via
        # reset_index.
        sub = by_dr.loc[(win, slice(None)), ["YTM"]].reset_index()
    except KeyError:
        return None
    sub = sub[sub["rank"].isin([cfg.rank_young, cfg.rank_old])]
    if sub.empty:
        return None
    piv = sub.pivot_table(index="date", columns="rank", values="YTM", aggfunc="first")
    if cfg.rank_young not in piv.columns or cfg.rank_old not in piv.columns:
        return None
    ser = (piv[cfg.rank_old] - piv[cfg.rank_young]) * 100.0
    ser = ser.dropna()
    if len(ser) < 20:
        return None
    mu, sd = ser.iloc[:-1].mean(), ser.iloc[:-1].std(ddof=1)
    if not sd or not np.isfinite(sd) or sd == 0:
        return None
    return float((ser.iloc[-1] - mu) / sd)
