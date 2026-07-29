"""Shared plumbing for the SR3 RV lab notebooks.

Every framework notebook loads the same panels, prints the same header block,
draws the same three-panel equity chart, runs the same honesty panels
(exit comparison, marks x lag, cost curve, grid distribution) and appends the
same league-table row. Keeping it here means the notebooks stay short enough to
execute cleanly and the league table is comparable across frameworks by
construction.
"""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from RVUtils.SFRRVLab import (  # noqa: E402
    COST_SCENARIOS,
    DOLLARS_PER_BP,
    LabConfig,
    MarkBook,
    attach_parity_flag,
    grid_search,
    load_panels,
    run_backtest,
)
from RVUtils.SFRRVLab.stats import (  # noqa: E402
    cost_curve,
    deflated_for_grid,
    grid_distribution,
    neighbourhood_stability,
    nonoverlapping_sharpe,
    nw_tstat,
    verdict,
)

DATA_DIR = REPO / "notebooks" / "data" / "sfr_rv_lab"
LEAGUE_CSV = REPO / "notebooks" / "data" / "sfr_rv_lab" / "league_table.csv"

#: BL surface-quality gates (spec section "Non-negotiable honesty rules")
MAX_ABS_FWD_RESID_BP = 2.5
MAX_PRE_NORM_MASS = 1.02


# ---------------------------------------------------------------------------
def load_lab(data_dir: Path = DATA_DIR, *, parity_tol_bp: float = 2.0) -> Dict[str, object]:
    """Panels + MarkBook + per-(as_of, symbol) quality gate, loaded once."""
    p = load_panels(data_dir)
    quotes, contracts = p["quotes"], p["contracts"]
    quotes = attach_parity_flag(quotes, contracts, tol_bp=parity_tol_bp)
    gate = contracts[["as_of", "symbol"]].copy()
    resid_ok = contracts["fwd_resid_bp"].abs() <= MAX_ABS_FWD_RESID_BP
    mass_ok = (contracts["pre_norm_mass"].isna()
               | (contracts["pre_norm_mass"] <= MAX_PRE_NORM_MASS))
    gate["gate"] = (resid_ok & mass_ok).fillna(False).to_numpy()
    return {
        "quotes": quotes, "contracts": contracts, "cdf": p.get("cdf"),
        "book": MarkBook(quotes, contracts), "gate": gate,
    }


def coverage_report(lab: Dict[str, object]) -> pd.DataFrame:
    """Per symbol: date span, quote count, share passing the quality gate."""
    c, g = lab["contracts"], lab["gate"]
    m = c.merge(g, on=["as_of", "symbol"], how="left")
    out = (m.groupby("symbol")
           .agg(first=("as_of", "min"), last=("as_of", "max"),
                days=("as_of", "nunique"), gate_ok=("gate", "mean"),
                med_resid=("fwd_resid_bp", lambda s: s.abs().median()))
           .sort_values("first"))
    q = lab["quotes"].groupby("symbol").size().rename("quotes")
    return out.join(q).round(3)


# ---------------------------------------------------------------------------
def header_block(name: str, res, *, grid: Optional[pd.DataFrame] = None,
                 note: str = "") -> Dict[str, float]:
    """The standard stats header. Returns the dict it printed."""
    m = dict(res.metrics)
    m["nonoverlap_sharpe"] = nonoverlapping_sharpe(res.trades) if not res.trades.empty else np.nan
    m["nw_t"] = nw_tstat(res.daily_bp.to_numpy(), lags=5) if len(res.daily_bp) else np.nan
    if grid is not None and not res.daily_bp.empty:
        d = deflated_for_grid(res.daily_bp, grid)
        m["dsr_prob"] = d.get("dsr_prob", np.nan)
        m["sr_annualised"] = d.get("sr_annualised", np.nan)
        m["n_trials"] = d.get("n_trials", np.nan)
    print("=" * 92)
    print(f"{name}  |  {res.config.label()}  |  {res.config.contracts_per_leg} "
          f"contracts/leg (${DOLLARS_PER_BP * res.config.contracts_per_leg:,.0f}/bp)")
    if note:
        print(f"  {note}")
    print("=" * 92)
    if np.isfinite(m.get("pkg_contracts", np.nan)):
        print(f"  1 package = {m['pkg_contracts']:.0f} contracts "
              f"-> position = {m['pkg_contracts'] * res.config.contracts_per_leg:,.0f} "
              f"contracts across all legs")
    print(f"  trades {m['n_trades']:>5d}   skipped {m.get('n_skipped', 0):>4d}   "
          f"hit {m['hit_rate']:.0%}   avg {m['avg_net_bp']:+.3f}bp   "
          f"avg hold {m['avg_hold_days']:.1f}d   stale {m.get('avg_stale', float('nan')):.1%}")
    print(f"  total  {m['total_net_bp']:+9.2f}bp   ${m['total_net_usd']:>+12,.0f}   "
          f"gross {m.get('total_gross_bp', float('nan')):+.2f}bp")
    print(f"  daily-MTM Sharpe {m['sharpe']:+.2f}   maxDD {m['max_dd_bp']:+.2f}bp "
          f"(${m['max_dd_usd']:+,.0f})   worst trade {m['worst_bp']:+.2f}bp")
    print(f"  t(trade) {m['t_stat']:+.2f}   NW t(daily) {m['nw_t']:+.2f}   "
          f"non-overlap SR {m['nonoverlap_sharpe']:+.2f}", end="")
    if "dsr_prob" in m:
        print(f"   DSR p={m['dsr_prob']:.3f} over {m['n_trials']} trials")
    else:
        print()
    return m


def three_panel_equity(res, title: str, *, ax=None):
    """bp equity | dollar equity | drawdown, the house layout."""
    import matplotlib.pyplot as plt
    if res.daily_bp.empty:
        print(f"  (no P&L to plot for {title})")
        return None
    cum = res.daily_bp.cumsum()
    usd = res.daily_usd.cumsum()
    dd = cum - cum.cummax()
    fig, axes = plt.subplots(1, 3, figsize=(16, 3.8))
    axes[0].plot(cum.index, cum.to_numpy(), lw=1.4, color="#1f4e79")
    axes[0].set_title(f"{title}\ncumulative net P&L (bp)", fontsize=10)
    axes[0].axhline(0, color="grey", lw=0.6)
    axes[1].plot(usd.index, usd.to_numpy(), lw=1.4, color="#2e7d32")
    axes[1].set_title(f"cumulative net P&L ($, "
                      f"{res.config.contracts_per_leg} lots/leg)", fontsize=10)
    axes[1].axhline(0, color="grey", lw=0.6)
    axes[2].fill_between(dd.index, dd.to_numpy(), 0, color="#c62828", alpha=0.35)
    axes[2].set_title("drawdown (bp)", fontsize=10)
    for a in axes:
        a.grid(alpha=0.25)
        a.tick_params(labelsize=8)
    fig.autofmt_xdate()
    fig.tight_layout()
    return fig


def exit_comparison(base: LabConfig, *, signals, book, builder,
                    exits: Sequence[str] = ("z0", "half", "t5", "t10", "t20")) -> pd.DataFrame:
    rows = []
    for ex in exits:
        cfg = dataclasses.replace(base, exit_style=ex)
        r = run_backtest(cfg, signals=signals, book=book, builder=builder)
        rows.append({"exit": ex, **{k: r.metrics[k] for k in
                                    ("n_trades", "hit_rate", "avg_net_bp",
                                     "total_net_bp", "total_net_usd", "sharpe",
                                     "max_dd_bp", "avg_hold_days")}})
    return pd.DataFrame(rows).round(3)


def marks_x_lag_panel(base: LabConfig, *, signals, book, builder,
                      model_signals: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """The honesty panel: listed vs model signal, lag 0 vs lag 1.

    Same tradeable structure and the same LISTED P&L marks in every cell — only
    the *signal source* and the execution lag change. A framework whose model
    row beats its listed row is being driven by fit noise, and a lag-0 row far
    above lag-1 is same-bar inflation.
    """
    rows = []
    variants = [("listed", signals)]
    if model_signals is not None:
        variants.append(("model", model_signals))
    for src, sig in variants:
        for lag in (0, 1):
            cfg = dataclasses.replace(base, lag=lag)
            r = run_backtest(cfg, signals=sig, book=book, builder=builder)
            rows.append({"signal_source": src, "lag": lag,
                         "n_trades": r.metrics["n_trades"],
                         "total_gross_bp": r.metrics.get("total_gross_bp", np.nan),
                         "total_net_bp": r.metrics["total_net_bp"],
                         "sharpe": r.metrics["sharpe"],
                         "hit_rate": r.metrics["hit_rate"]})
    out = pd.DataFrame(rows)
    l0 = out[(out["signal_source"] == "listed") & (out["lag"] == 0)]["total_gross_bp"]
    l1 = out[(out["signal_source"] == "listed") & (out["lag"] == 1)]["total_gross_bp"]
    if len(l0) and len(l1) and abs(float(l0.iloc[0])) > 1e-9:
        out.attrs["lag_inflation"] = 1.0 - float(l1.iloc[0]) / float(l0.iloc[0])
    return out.round(3)


def grid_block(grid: pd.DataFrame, params: Sequence[str], *,
               metric: str = "total_net_bp", top: int = 8) -> pd.Series:
    """Print the distribution + top rows + per-parameter medians; return the best row."""
    d = grid_distribution(grid, metric)
    print(f"  {d['n_configs']} configs | median {d['median']:+.2f}bp | "
          f"IQR [{d['q25']:+.2f}, {d['q75']:+.2f}] | "
          f"{d['pct_positive']:.0%} net-positive | best {d['best']:+.2f}bp")
    show = [c for c in list(params) + ["n_trades", "hit_rate", "avg_net_bp",
                                       "total_net_bp", "total_net_usd", "sharpe",
                                       "max_dd_bp"] if c in grid.columns]
    print("\n  top rows (SELECTION-INFLATED — read the distribution above first):")
    print(grid.sort_values(metric, ascending=False).head(top)[show]
          .round(3).to_string(index=False))
    print("\n  median net bp per parameter value:")
    for p in params:
        if p in grid.columns:
            print(f"    {p}: {grid.groupby(p)[metric].median().round(2).to_dict()}")
    return grid.loc[grid[metric].idxmax()]


def config_from_row(base: LabConfig, row: pd.Series, params: Sequence[str]) -> LabConfig:
    """Rebuild the LabConfig a grid row came from."""
    kw = {p: row[p] for p in params if p in row.index}
    for k, v in list(kw.items()):
        if isinstance(v, (np.integer,)):
            kw[k] = int(v)
        elif isinstance(v, (np.floating,)):
            kw[k] = float(v)
    return dataclasses.replace(base, **kw)


def median_row(grid: pd.DataFrame, metric: str = "total_net_bp") -> pd.Series:
    """The grid row closest to the sweep's median — the un-cherry-picked config."""
    i = (grid[metric] - grid[metric].median()).abs().idxmin()
    return grid.loc[i]


def stability_block(grid: pd.DataFrame, best: pd.Series, params: Sequence[str],
                    *, metric: str = "total_net_bp") -> pd.DataFrame:
    nb = neighbourhood_stability(grid, best, [p for p in params if p in grid.columns],
                                 metric=metric)
    print("\n  neighbourhood (one parameter moved at a time):")
    for p, sub in nb.groupby("param"):
        vals = ", ".join(f"{v}{'*' if b else ''}={x:+.2f}"
                         for v, x, b in zip(sub["value"], sub[metric], sub["is_best"]))
        print(f"    {p}: {vals}")
    return nb


def gate_sensitivity(base: LabConfig, *, signals, book, builder,
                     gates: Sequence[str] = ("gate", "gate_bl")) -> pd.DataFrame:
    """What each entry gate costs: trades and P&L under every gate definition.

    The headline gate is the leg-level one (the traded strikes are listed and
    OI-screened). ``gate_bl`` is the stricter BL surface rule from the spec; on
    this panel it mostly rejects days when the listed chain is too narrow for the
    density to integrate to one, so it is reported rather than assumed.
    """
    rows = []
    variants: List[tuple] = [("none", None)]
    variants += [(g, g) for g in gates if g in signals.columns]
    if all(g in signals.columns for g in gates):
        variants.append(("all", "__all__"))
    for name, col in variants:
        s = signals.copy()
        if col is None:
            s["gate"] = True
        elif col == "__all__":
            s["gate"] = np.logical_and.reduce([s[g].to_numpy() for g in gates])
        else:
            s["gate"] = s[col].to_numpy()
        r = run_backtest(base, signals=s, book=book, builder=builder)
        rows.append({"gate": name, "pass_rate": float(s["gate"].mean()),
                     **{k: r.metrics[k] for k in
                        ("n_trades", "hit_rate", "avg_net_bp", "total_net_bp",
                         "total_net_usd", "sharpe", "max_dd_bp")}})
    return pd.DataFrame(rows).round(3)


def cost_block(res) -> pd.DataFrame:
    if res.trades.empty:
        return pd.DataFrame()
    cc = cost_curve(res.trades, [0.0, 0.5, 1.0, 1.5, 2.5, 4.0])
    cc["total_net_usd"] = cc["total_net_bp"] * DOLLARS_PER_BP * res.config.contracts_per_leg
    print("\n  cost curve (round-trip bp charged on the package):")
    print(cc.round(3).to_string(index=False))
    return cc


# ---------------------------------------------------------------------------
def sign_test(grid: pd.DataFrame, metric: str = "total_net_bp") -> pd.DataFrame:
    """Fade vs momentum across the whole sweep — the house rule, never assumed."""
    if "direction" not in grid.columns:
        return pd.DataFrame()
    out = (grid.groupby("direction")
           .agg(n_configs=(metric, "size"), median_net_bp=(metric, "median"),
                pct_positive=(metric, lambda s: (s > 0).mean()),
                best_net_bp=(metric, "max"), median_trades=("n_trades", "median"))
           .round(3))
    print("\nSIGN TEST (both directions, whole sweep)")
    print(out.to_string())
    return out


def run_framework(
    name: str, *, signals, book, builder, base: LabConfig,
    grid_spec: Dict[str, Sequence], params: Sequence[str], cls: str,
    note: str = "", model_signals=None, plot: bool = True,
    league: bool = True, show_trades: int = 30,
) -> Dict[str, object]:
    """The standard framework sequence, identical for every notebook.

    grid + distribution + stability + sign test, then the best config's header,
    equity, trade log and honesty panels (exit comparison, marks x lag, cost
    curve, gate sensitivity), then the median config, then the league rows.
    Returning the pieces lets a notebook add framework-specific analysis after.
    """
    import matplotlib.pyplot as plt

    grid = grid_search(grid_spec, signals=signals, book=book, builder=builder,
                       base=base, show_progress=True)
    print(f"\n=== {name} — grid ===")
    best = grid_block(grid, params)
    stability_block(grid, best, params)
    sign_test(grid)

    cfg = config_from_row(base, best, params)
    res = run_backtest(cfg, signals=signals, book=book, builder=builder)
    print()
    header_block(f"{name} — best config", res, grid=grid, note=note)
    if plot and not res.daily_bp.empty:
        three_panel_equity(res, name)
        plt.show()
    if show_trades and not res.trades.empty:
        print("\nTRADE LOG (first rows)")
        print(res.trades.sort_values("entry").head(show_trades).to_string(index=False))

    print("\nEXIT COMPARISON")
    print(exit_comparison(cfg, signals=signals, book=book,
                          builder=builder).to_string(index=False))
    print("\nMARKS x LAG")
    mxl = marks_x_lag_panel(cfg, signals=signals, book=book, builder=builder,
                            model_signals=model_signals)
    print(mxl.to_string(index=False))
    if "lag_inflation" in mxl.attrs:
        print(f"same-bar (lag 0) gross inflation: {mxl.attrs['lag_inflation']:.1%}")
    cost_block(res)
    if "gate_bl" in getattr(signals, "columns", []):
        print("\nGATE SENSITIVITY")
        print(gate_sensitivity(cfg, signals=signals, book=book,
                               builder=builder).to_string(index=False))

    med = median_row(grid)
    res_med = run_backtest(config_from_row(base, med, params), signals=signals,
                           book=book, builder=builder)
    print()
    header_block(f"{name} — median config (not selected)", res_med, grid=grid)

    if league:
        league_row(name, "best-config", res, grid=grid, cls=cls, note=note)
        league_row(name, "median-config", res_med, grid=grid, cls=cls,
                   note="median of the sweep, not selected")
    return {"grid": grid, "best": best, "config": cfg, "result": res,
            "median_result": res_med}


def league_row(framework: str, variant: str, res, *, grid: Optional[pd.DataFrame],
               cls: str, note: str = "", write: bool = True) -> Dict[str, object]:
    """Build (and append) one league-table row with the uniform verdict."""
    m = dict(res.metrics)
    cc = (cost_curve(res.trades, [0.0, 2.5]).set_index("round_trip_bp")
          if not res.trades.empty else None)
    maker = float(cc.loc[0.0, "total_net_bp"]) if cc is not None else 0.0
    taker = float(cc.loc[2.5, "total_net_bp"]) if cc is not None else 0.0
    dsr = (deflated_for_grid(res.daily_bp, grid).get("dsr_prob", np.nan)
           if grid is not None and not res.daily_bp.empty else np.nan)
    median_net = (float(grid["total_net_bp"].median())
                  if grid is not None and len(grid) else np.nan)
    row = {
        "framework": framework, "variant": variant, "class": cls,
        "config": res.config.label(),
        "n_trades": m["n_trades"], "hit_rate": m["hit_rate"],
        "avg_net_bp": m["avg_net_bp"],
        "total_gross_bp": m.get("total_gross_bp", np.nan),
        "total_net_bp": m["total_net_bp"], "total_net_usd": m["total_net_usd"],
        "net_bp_maker": maker, "net_bp_taker": taker,
        "net_usd_taker": taker * DOLLARS_PER_BP * res.config.contracts_per_leg,
        "sharpe": m["sharpe"], "max_dd_bp": m["max_dd_bp"],
        "max_dd_usd": m["max_dd_usd"], "avg_hold_days": m["avg_hold_days"],
        "dsr_prob": dsr, "grid_median_net_bp": median_net,
        "nonoverlap_sharpe": nonoverlapping_sharpe(res.trades) if not res.trades.empty else np.nan,
        "verdict": verdict(net_bp_at_taker=taker, net_bp_at_maker=maker,
                           dsr_prob=dsr if np.isfinite(dsr) else 0.0,
                           median_net_bp=median_net if np.isfinite(median_net) else -1.0,
                           n_trades=m["n_trades"]),
        "note": note,
    }
    if write:
        LEAGUE_CSV.parent.mkdir(parents=True, exist_ok=True)
        df = pd.DataFrame([row])
        if LEAGUE_CSV.exists():
            old = pd.read_csv(LEAGUE_CSV)
            old = old[~((old["framework"] == framework) & (old["variant"] == variant))]
            df = pd.concat([old, df], ignore_index=True)
        df.to_csv(LEAGUE_CSV, index=False)
    print(f"\n  LEAGUE ROW  {framework} / {variant}: {row['verdict']}  "
          f"(taker {taker:+.2f}bp, maker {maker:+.2f}bp, "
          f"DSR p={dsr if np.isfinite(dsr) else float('nan'):.3f})")
    return row
