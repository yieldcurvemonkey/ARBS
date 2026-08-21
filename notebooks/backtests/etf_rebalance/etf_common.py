"""Loading, plotting and reporting helpers for the ETF-rebalance notebook.

Everything here is presentation. The measurement lives in ``RVUtils/ETFRebalance`` and in
``BT/signals/etf_rebalance.py``; this module exists so the notebook reads as a sequence of
questions rather than as a wall of pandas.
"""

from __future__ import annotations

import datetime
import os
import pathlib
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

#: The holdings store lives in the PRIMARY checkout, not in whichever worktree is running.
#: A worktree is removed when its branch merges and ``git worktree remove`` on Windows
#: deletes straight through a junction, so 20,000 scraped documents must not sit inside
#: one. Set before any ARBS import that reaches the store.
DEFAULT_HOLDINGS_DIR = r"C:\Users\chris\clee\ARBS\MDP\ETFHoldings\etf_holdings_cache"


def use_holdings_dir(path: str = DEFAULT_HOLDINGS_DIR) -> str:
    os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
    os.environ["ARBS_ETF_HOLDINGS_DIR"] = path
    return path


def load_all(funds: Sequence[str]):
    """The combined price+float panel and the holdings join, in one call."""
    from RVUtils.ETFRebalance import bond_panel as BP
    from RVUtils.ETFRebalance import float_panel as FP
    from RVUtils.ETFRebalance import holdings_panel as HP

    panel = FP.asof_join(BP.load(), FP.load())
    joined = HP.build(list(funds), panel=panel)
    return panel, joined


# ------------------------------------------------------------------ provenance

def holdings_coverage(tickers: Sequence[str]) -> pd.DataFrame:
    """Per fund: what was attempted, what came back, and what the gaps are.

    Reported before any result, because a scrape that quietly recorded refusals as
    absence is the failure mode this project actually hit: an early six-worker run was
    WAF-blocked after 143 documents and wrote 2,515 days of "no file", exiting 0.
    ``dup_content`` and ``asof_mismatch`` are the two columns that would show a stale
    document being re-served or mis-dated; both are zero in the shipped dataset.
    """
    from MDP.ETFHoldings import store

    rows = []
    for t in tickers:
        m = store.read_manifest(t)
        if m.empty:
            rows.append({"ticker": t, "attempted": 0, "files": 0, "no_file": 0})
            continue
        m = m.copy()
        m["requested_date"] = pd.to_datetime(m["requested_date"])
        got = m[m["as_of"].notna()]
        rows.append({
            "ticker": t,
            "attempted": len(m),
            "files": len(got),
            "no_file": int(m["as_of"].isna().sum()),
            "dup_content": int(got["content_sha1"].duplicated().sum()),
            "asof_mismatch": int((pd.to_datetime(got["as_of"]).dt.date
                                  != got["requested_date"].dt.date).sum()),
            "first": got["requested_date"].min(),
            "last": got["requested_date"].max(),
        })
    return pd.DataFrame(rows).set_index("ticker")


def holdings_gaps(ticker: str, *, min_run: int = 5) -> pd.DataFrame:
    """Runs of consecutive requested business days with no published document."""
    from MDP.ETFHoldings import store

    m = store.read_manifest(ticker)
    if m.empty:
        return pd.DataFrame()
    m = m.copy()
    m["requested_date"] = pd.to_datetime(m["requested_date"])
    m = m.sort_values("requested_date")
    miss = m["as_of"].isna().to_numpy()
    runs, start = [], None
    for i, bad in enumerate(miss):
        if bad and start is None:
            start = i
        elif not bad and start is not None:
            runs.append((start, i - 1))
            start = None
    if start is not None:
        runs.append((start, len(miss) - 1))
    out = [{"from": m["requested_date"].iloc[a].date(),
            "to": m["requested_date"].iloc[b].date(),
            "business_days": b - a + 1}
           for a, b in runs if b - a + 1 >= min_run]
    return pd.DataFrame(out)


# ------------------------------------------------------------------ reporting

#: Statistics that come from the DAILY equity curve rather than from the trade log.
#: They are only meaningful for a whole book: a subset of trades does not have its own
#: daily curve, and reporting the parent's would attribute the full book's Sharpe and
#: drawdown to a slice of it.
_DAILY_STATS = ("sharpe_daily", "max_dd_bp", "active_days")


def perf_row(res, label: str) -> Dict[str, Any]:
    from RVUtils.ETFRebalance import engine as EN

    if res is None or res.closed is None or res.closed.empty:
        return {"book": label, "trades": 0}
    s = EN.summarize(res)
    return {"book": label, **{k: s[k] for k in (
        "trades", "total_bp", "avg_bp", "hit", "gross_avg_bp", "cost_avg_bp",
        "t_stat", "sharpe_daily", "sr_per_trade", "max_dd_bp", "breakeven_cost_mult")}}


def perf_row_trades(closed: pd.DataFrame, label: str) -> Dict[str, Any]:
    """Trade-level statistics only, for a SUBSET of a book.

    A slice of the trade log has no daily equity curve of its own, so the daily-derived
    statistics are omitted rather than inherited from the parent -- inheriting them would
    report the whole book's Sharpe and drawdown against a third of its trades.
    """
    if closed is None or closed.empty:
        return {"book": label, "trades": 0}
    p = closed["pnl_bp"].to_numpy(float)
    sd = float(np.std(p, ddof=1)) if len(p) > 1 else np.nan
    return {
        "book": label, "trades": len(closed),
        "total_bp": float(p.sum()), "avg_bp": float(p.mean()),
        "hit": float((p > 0).mean()),
        "gross_avg_bp": float(closed["gross_bp"].mean()),
        "cost_avg_bp": float(closed["cost_bp"].mean()),
        "t_stat": float(p.mean() / (sd / np.sqrt(len(p)))) if sd and sd > 0 else np.nan,
        "sr_per_trade": float(p.mean() / sd) if sd and sd > 0 else np.nan,
        "breakeven_cost_mult": float(closed["gross_bp"].mean() / closed["cost_bp"].mean())
        if closed["cost_bp"].mean() > 0 else np.inf,
    }


def funnel_series(funnel: Mapping[str, Any], name: str = "config") -> pd.DataFrame:
    order = [k for k in funnel if not k.startswith("gate_") and not k.startswith("drop_")]
    gates = [k for k in funnel if k.startswith("gate_")]
    drops = [k for k in funnel if k.startswith("drop_")]
    keys = order[:2] + sorted(gates, key=lambda k: -float(funnel[k] or 0)) + order[2:] \
        + sorted(drops, key=lambda k: -float(funnel[k] or 0))
    keys += [k for k in funnel if k not in keys]
    return pd.Series({k: funnel[k] for k in keys}).to_frame(name)


# ------------------------------------------------------------------ plots

def equity_panel(res, *, title: str = "", ax=None, figsize=(14, 8)):
    """Daily mark-to-market equity in bp, with the per-trade bars underneath."""
    import matplotlib.pyplot as plt

    d, c = res.daily, res.closed
    fig, axes = plt.subplots(2, 1, figsize=figsize, gridspec_kw={"height_ratios": [2, 1]})

    ax = axes[0]
    ax.plot(d["date"].values, d["mtm_bp"].values, lw=1.7, color="darkslateblue",
            label="net of measured cost")
    if not c.empty:
        gross = d.copy()
        gross_cost = c.groupby("closed_at")["cost_bp"].sum().reindex(
            pd.DatetimeIndex(d["date"])).fillna(0.0).cumsum().to_numpy()
        ax.plot(d["date"].values, d["mtm_bp"].values + gross_cost, lw=1.1,
                color="grey", ls="--", label="gross")
    ax.axhline(0, color="k", lw=.6)
    ax.set_ylabel("cumulative bp per unit belly DV01")
    ax.legend()
    ax.grid(alpha=.3)
    if title:
        ax.set_title(title, fontsize=11, pad=10)

    ax = axes[1]
    if not c.empty:
        span = c["opened_at"].max() - c["opened_at"].min()
        # A datetime axis takes bar widths in DAYS, not in points: `width=3` against
        # datetime64 means three NANOSECONDS and the bars vanish.
        w = span / max(1, min(len(c), 400)) if span else pd.Timedelta(days=1)
        ax.bar(c["opened_at"].values, c["pnl_bp"].values, width=w, alpha=.75,
               color=["seagreen" if x > 0 else "indianred" for x in c["pnl_bp"]])
    ax.axhline(0, color="k", lw=.6)
    ax.set_ylabel("per-trade bp")
    ax.grid(alpha=.3)
    import matplotlib.pyplot as _plt
    _plt.tight_layout()
    return fig


def ic_heatmap(ic_tab: pd.DataFrame, value: str = "ic_mean", *, ax=None,
               title: str = "", fmt: str = ".3f"):
    import matplotlib.pyplot as plt
    import seaborn as sns

    piv = ic_tab.pivot_table(index="signal", columns="horizon", values=value)
    if ax is None:
        _, ax = plt.subplots(figsize=(9, max(3, 0.42 * len(piv))))
    sns.heatmap(piv.astype(float), annot=True, fmt=fmt, cmap="RdYlGn", center=0, ax=ax,
                cbar_kws={"label": value})
    ax.set_title(title or f"{value} by signal and forward horizon (business days)")
    ax.set_xlabel("forward horizon (business days)")
    return ax


def cost_curve(res_by_name: Mapping[str, Any], multipliers=(0.0, 0.25, 0.5, 1.0, 1.5, 2.0, 3.0)):
    """Total bp against the measured-cost multiplier -- the break-even picture.

    The x-axis is a MULTIPLE of the measured FedInvest spread rather than an absolute
    cost, because the level of that spread is the one number a reader might reasonably
    dispute. A strategy that breaks even at 3x is a different object from one that
    breaks even at 0.4x, and the multiple says which without anyone having to agree on
    the level.
    """
    rows = []
    for m in multipliers:
        r = {"cost_mult": m}
        for nm, res in res_by_name.items():
            if res is None or res.closed is None or res.closed.empty:
                r[nm] = np.nan
                continue
            c = res.closed
            r[nm] = float((c["gross_bp"] - m * c["cost_bp"]).sum())
        rows.append(r)
    return pd.DataFrame(rows).set_index("cost_mult")
