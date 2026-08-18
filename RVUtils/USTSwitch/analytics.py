"""Metrics, decomposition and seasonality for the olds-vs-currents switch study.

Reuses ``RVUtils/BasisVsVol/analytics.py`` for the statistics (Newey-West t, PSR,
expected-max-Sharpe, deflated Sharpe, block bootstrap, regime split) rather than adding a
fourth incompatible ``deflated_sharpe`` to a repo that already has three with different
argument conventions. The BasisVsVol family works in ANNUALISED-from-daily units, which is
what this study produces, so it is the one that fits without a conversion step.

Seasonality is computed on two clocks and they are not interchangeable:

* **auction-cycle day** -- days since the tenor's last roll. This is the MECHANISM clock.
  The on-the-run premium is created at an auction and released at the next one, so if the
  trade works at all its P&L must be concentrated in specific parts of this cycle. A flat
  profile here means whatever is being measured is not the auction effect.
* **calendar month / day-of-week** -- the conventional clock, reported because it is what
  "seasonality" usually means and because a result that is really a January or a
  month-end effect should be visible as one.

The two can disagree, and the disagreement is informative: the front-end tenors roll
monthly, so their auction clock and the calendar month are nearly the same axis, while
10y/20y/30y roll quarterly and the two axes separate cleanly.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from RVUtils.BasisVsVol.analytics import (  # noqa: F401
    ANN,
    block_bootstrap_ci,
    concentration,
    deflated_sharpe,
    expected_max_sharpe,
    max_drawdown,
    newey_west_tstat,
    probabilistic_sharpe,
    sharpe,
)


# --------------------------------------------------------------------------------------
# headline metrics


def summarize_switch(res, *, ann: float = ANN) -> Dict[str, float]:
    """One row of headline statistics for a SwitchResult."""
    daily, trades = res.daily, res.trades
    out: Dict[str, float] = {"name": res.config.name, "tenor": res.config.tenor,
                             "pair": res.config.pair_label, "direction": res.config.direction,
                             "entry_offset": res.config.entry_offset,
                             "exit_rule": res.config.exit_rule,
                             "exit_offset": res.config.exit_offset,
                             "hold_days": res.config.hold_days,
                             "z_window": res.config.z_window, "z_entry": res.config.z_entry,
                             "financing_mode": res.config.financing_mode,
                             "cost_multiplier": res.config.cost_multiplier,
                             "placebo_shift": res.config.placebo_shift}
    if daily is None or daily.empty or trades is None or trades.empty:
        out.update({"n_trades": 0, "net_bp": np.nan, "sharpe": np.nan})
        return out

    pnl = daily["pnl_bp"]
    # Trading days only -- days flat are not observations of the strategy, and padding
    # with zeros deflates the vol and inflates the Sharpe.
    live = pnl[daily["in_position"] > 0]

    t_nw, se = newey_west_tstat(live)
    eq = daily["equity_bp"]

    years = max((daily.index[-1] - daily.index[0]).days / 365.25, 1e-9)
    out.update(
        {
            "n_trades": int(len(trades)),
            "n_days_live": int(len(live)),
            "years": round(years, 2),
            "trades_per_year": round(len(trades) / years, 2),
            "net_bp": float(trades["net_bp"].sum()),
            "net_bp_per_trade": float(trades["net_bp"].mean()),
            "net_bp_median": float(trades["net_bp"].median()),
            "gross_bp_per_trade": float(trades["gross_bp"].mean()),
            "price_bp_per_trade": float(trades["price_bp"].mean()),
            "carry_bp_per_trade": float(trades["carry_bp"].mean()),
            "special_bp_per_trade": float(trades["special_bp"].mean()),
            "cost_bp_per_trade": float(trades["cost_bp"].mean()),
            "net_bp_per_year": float(trades["net_bp"].sum() / years),
            "hit_rate": float((trades["net_bp"] > 0).mean()),
            "gross_hit_rate": float((trades["gross_bp"] > 0).mean()),
            "sharpe": float(sharpe(live, ann=ann)),
            "sharpe_gross": float(
                sharpe(daily.loc[live.index, "price_bp"] + daily.loc[live.index, "carry_bp"], ann=ann)
            ),
            "t_stat_nw": float(t_nw),
            "max_dd_bp": float(max_drawdown(eq)),
            "avg_hold_days": float(trades["held_days"].mean()),
            "financing_actual_frac": float(trades["financing_actual_frac"].mean())
            if "financing_actual_frac" in trades else np.nan,
        }
    )
    c = concentration(trades["net_bp"], top=3)
    out.update({f"conc_{k}": v for k, v in c.items()})
    # Break-even cost multiple: at what multiple of the assumed cost does net go to zero?
    gross = float(trades["gross_bp"].sum())
    cost = float(trades["cost_bp"].sum())
    out["breakeven_cost_mult"] = float(gross / cost) if cost > 0 else np.nan
    return out


def pnl_decomposition(res) -> pd.DataFrame:
    """Where the money came from -- price, carry (of which specialness), cost."""
    t = res.trades
    if t is None or t.empty:
        return pd.DataFrame()
    n = len(t)
    rows = [
        ("price (spread move)", t["price_bp"].sum(), t["price_bp"].mean()),
        ("carry (total)", t["carry_bp"].sum(), t["carry_bp"].mean()),
        ("  of which specialness", t["special_bp"].sum(), t["special_bp"].mean()),
        ("cost (execution)", -t["cost_bp"].sum(), -t["cost_bp"].mean()),
        ("NET", t["net_bp"].sum(), t["net_bp"].mean()),
    ]
    return pd.DataFrame(rows, columns=["component", "total_bp", "per_trade_bp"]).assign(n_trades=n)


# --------------------------------------------------------------------------------------
# seasonality


def auction_cycle_profile(res, *, max_day: int = 130) -> pd.DataFrame:
    """Mean P&L in bp by business day since the tenor's last roll -- the MECHANISM clock.

    Built from the trade ledger's own roll stamps rather than re-deriving the calendar, so
    it cannot drift from the dates the backtest actually used.
    """
    if res.trades is None or res.trades.empty:
        return pd.DataFrame()
    daily = res.daily
    rows = []
    for _, tr in res.trades.iterrows():
        seg = daily.loc[tr["entry"] : tr["exit"]]
        if seg.empty:
            continue
        # business-day distance from the roll that OPENED this cycle
        dist = np.arange(len(seg)) + int(
            np.busday_count(tr["roll"].date(), tr["entry"].date())
        )
        for k, v, pv, cv in zip(dist, seg["pnl_bp"].values, seg["price_bp"].values, seg["carry_bp"].values):
            if 0 <= k <= max_day:
                rows.append({"cycle_day": int(k), "pnl_bp": v, "price_bp": pv, "carry_bp": cv})
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    g = df.groupby("cycle_day").agg(
        n=("pnl_bp", "size"),
        mean_pnl_bp=("pnl_bp", "mean"),
        mean_price_bp=("price_bp", "mean"),
        mean_carry_bp=("carry_bp", "mean"),
        sum_pnl_bp=("pnl_bp", "sum"),
    )
    g["cum_mean_pnl_bp"] = g["mean_pnl_bp"].cumsum()
    return g.reset_index()


def calendar_seasonality(res) -> Dict[str, pd.DataFrame]:
    """Month-of-year, day-of-week and year breakdowns of daily bp P&L."""
    d = res.daily
    if d is None or d.empty:
        return {}
    live = d[d["in_position"] > 0].copy()
    if live.empty:
        return {}
    live["month"] = live.index.month
    live["dow"] = live.index.dayofweek
    live["year"] = live.index.year
    live["dom"] = live.index.day

    def agg(by):
        g = live.groupby(by)["pnl_bp"].agg(["size", "sum", "mean"])
        g.columns = ["n_days", "total_bp", "mean_bp_per_day"]
        # t-stat per bucket so a big-looking month with 4 observations reads as such
        g["t"] = live.groupby(by)["pnl_bp"].apply(
            lambda x: float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))) if len(x) > 2 and x.std(ddof=1) > 0 else np.nan
        )
        return g.reset_index()

    return {
        "month": agg("month"),
        "dow": agg("dow"),
        "year": agg("year"),
        "dom": agg("dom"),
    }


def spread_term_structure(panel: pd.DataFrame, tenor: int) -> pd.DataFrame:
    """Mean yield pickup of each rank over the on-the-run, by days since that rank's issue.

    This is the raw object the strategy trades, shown without any trading rule on top: if
    the on-the-run premium does not decay along this axis there is nothing to harvest and
    no configuration can rescue it.
    """
    p = panel[panel["tenor"] == tenor].copy()
    if p.empty:
        return pd.DataFrame()
    piv = p.pivot_table(index="date", columns="rank", values="YTM", aggfunc="first")
    if 0 not in piv.columns:
        return pd.DataFrame()
    rows = []
    for r in sorted(c for c in piv.columns if c != 0):
        d = ((piv[r] - piv[0]) * 100.0).dropna()
        rows.append({"rank": r, "n": len(d), "mean_pickup_bp": d.mean(),
                     "median_pickup_bp": d.median(), "std_bp": d.std(ddof=1)})
    return pd.DataFrame(rows)


def dv01_drift_check(panel: pd.DataFrame, tenor: int, rank_a: int, rank_b: int) -> Dict[str, float]:
    """How far apart the two legs' DV01s drift over a quarter.

    The engine rebalances to constant $1/bp daily; this measures what that assumption is
    worth. A ratio that moves 0.5% over a holding period makes the entry-fixed book a
    0.5%-of-DV01 outright position, which at 10y is ~0.005bp per bp of yield move -- small,
    but it should be a measured smallness and not an assumed one.
    """
    p = panel[panel["tenor"] == tenor]
    piv = p.pivot_table(index="date", columns="rank", values="DV01", aggfunc="first").dropna()
    if rank_a not in piv.columns or rank_b not in piv.columns or piv.empty:
        return {}
    ratio = piv[rank_b] / piv[rank_a]
    chg = ratio.pct_change(63).dropna()  # ~one quarter
    return {
        "mean_ratio": float(ratio.mean()),
        "quarterly_drift_mean_pct": float(chg.mean() * 100),
        "quarterly_drift_p95_pct": float(chg.abs().quantile(0.95) * 100),
    }


# --------------------------------------------------------------------------------------
# grid-level


def league_table(summaries: Sequence[Dict], *, min_trades: int = 8) -> pd.DataFrame:
    df = pd.DataFrame(list(summaries))
    if df.empty:
        return df
    df = df[df["n_trades"].fillna(0) >= min_trades].copy()
    return df.sort_values("sharpe", ascending=False).reset_index(drop=True)


def deflate_league(
    league: pd.DataFrame, daily_by_name: Dict[str, pd.Series], *, n_trials: Optional[int] = None
) -> pd.DataFrame:
    """Deflated Sharpe against the variance of Sharpes actually observed in the grid.

    ``n_trials`` defaults to the number of rows, which is the RAW count. For a grid of 42
    heavily overlapping structures (the same seven tenors re-paired) that over-deflates,
    and the honest number is the EFFECTIVE trial count -- see
    ``RVUtils/StatisticalFinance/deflated_sharpe.effective_trials``. Both are reported by
    the notebook so the reader can see which side of the line the result falls on.
    """
    out = league.copy()
    if out.empty:
        return out
    sr = out["sharpe"].astype(float)
    sr_var = float(np.nanvar(sr.values, ddof=1)) if sr.notna().sum() > 1 else np.nan
    n = int(n_trials or len(out))
    out["sr_star"] = expected_max_sharpe(n, sr_var) if np.isfinite(sr_var) else np.nan
    probs = []
    for nm in out["name"]:
        d = daily_by_name.get(nm)
        probs.append(
            deflated_sharpe(d, n, sr_var) if d is not None and np.isfinite(sr_var) else np.nan
        )
    out["dsr_prob"] = probs
    out["n_trials_used"] = n
    out["sr_variance"] = sr_var
    return out


def verdict_row(row: pd.Series, *, dsr_threshold: float = 0.95) -> str:
    """The repo's ALIVE / SELECTION-ARTIFACT / DEAD taxonomy, applied to a league row."""
    if not np.isfinite(row.get("n_trades", np.nan)) or row.get("n_trades", 0) < 10:
        return "DEAD (too few trades)"
    net = row.get("net_bp_per_trade", np.nan)
    dsr = row.get("dsr_prob", np.nan)
    if not np.isfinite(net) or net <= 0:
        return "DEAD (negative net)"
    if np.isfinite(dsr) and dsr >= dsr_threshold:
        return "ALIVE"
    if np.isfinite(dsr) and dsr < dsr_threshold:
        return "SELECTION-ARTIFACT"
    return "UNKNOWN"
