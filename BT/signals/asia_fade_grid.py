"""Asia Fade SFR — grid search over packages × filter rules.

Executes the query-driven backtest from ``asia_fade_sfr.py`` for many
packages (outrights, calendar spreads, butterflies) and post-processes
each trade panel through a grid of filter rules:

  - min signal size (in package-relative σ units)
  - drop low-vol / mid-vol days
  - drop ±N business days around FOMC
  - drop economic data release days (NFP / CPI)

Results are written to ``BT/results/asia_fade_grid/`` with one CSV per
package, plus consolidated rankings.

Each backtest is run ONCE per package (full 5-year window). Filter
combinations are applied to the resulting trade panel as cheap post-
processing — orders of magnitude faster than re-running each combo.

Usage:
    conda run -n stir python BT/signals/asia_fade_grid.py
    conda run -n stir python BT/signals/asia_fade_grid.py --start 2024-01-01

Outputs:
    BT/results/asia_fade_grid/all_trades.parquet      — per-pkg trades cache
    BT/results/asia_fade_grid/grid_results.csv        — every cell
    BT/results/asia_fade_grid/best_per_package.csv    — top filter per pkg
    BT/results/asia_fade_grid/top_by_sharpe.csv       — top 25 across all
    BT/results/asia_fade_grid/top_by_total_usd.csv    — top 25 by P&L
    BT/results/asia_fade_grid/summary.txt             — pretty-printed
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import logging
import sys
from dataclasses import dataclass, field
from itertools import product
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except Exception:
    pass

sys.path.insert(0, r"C:\Users\chris\clee\ARBS")

from BT.signals.asia_fade_sfr import (  # noqa: E402
    AsiaFadeConfig,
    _annualized_sharpe,
    build_trade_events,
    build_strategy,
    load_intraday_rates,
    trades_dataframe,
    trading_dates,
)
from BT.data_handler import TimeGrid  # noqa: E402
from BT.query_engine import QueryDrivenBacktest  # noqa: E402
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP  # noqa: E402

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s | %(message)s")
logger = logging.getLogger("asia_fade_grid")


# ─────────────────────────── Package universe ────────────────────────────


@dataclass
class Package:
    label: str
    tenor: str
    structure: str  # "outright" | "spread" | "fly"


PACKAGES: List[Package] = [
    # --- outrights ---
    Package("SFR1_outright",  "IMM_1xIMM_2",   "outright"),
    Package("SFR3_outright",  "IMM_3xIMM_4",   "outright"),
    Package("SFR5_outright",  "IMM_5xIMM_6",   "outright"),
    Package("SFR8_outright",  "IMM_8xIMM_9",   "outright"),
    Package("SFR12_outright", "IMM_12xIMM_13", "outright"),
    # --- calendar spreads (curves) ---
    Package("SFR1Q5Q_curve", "IMM_1xIMM_2/IMM_5xIMM_6",   "spread"),
    Package("SFR4Q8Q_curve", "IMM_4xIMM_5/IMM_8xIMM_9",   "spread"),
    Package("SFR5Q9Q_curve", "IMM_5xIMM_6/IMM_9xIMM_10",  "spread"),
    Package("SFR8Q12Q_curve","IMM_8xIMM_9/IMM_12xIMM_13", "spread"),
    # --- flies (butterflies) ---
    Package("SFR4_5_6_fly",  "IMM_4xIMM_5/IMM_5xIMM_6/IMM_6xIMM_7",   "fly"),
    Package("SFR3_5_7_fly",  "IMM_3xIMM_4/IMM_5xIMM_6/IMM_7xIMM_8",   "fly"),
    Package("SFR5_7_9_fly",  "IMM_5xIMM_6/IMM_7xIMM_8/IMM_9xIMM_10",  "fly"),
    Package("SFR8_10_12_fly","IMM_8xIMM_9/IMM_10xIMM_11/IMM_12xIMM_13","fly"),
]


# ─────────────────────────── Calendars helpers ───────────────────────────


def _fomc_dates() -> List[dt.date]:
    try:
        from SDRUtils.analytics.seasonality import get_fomc_dates
        return get_fomc_dates()
    except Exception as e:
        logger.warning("FOMC dates unavailable: %s", e)
        return []


def _nfp_dates(start: dt.date, end: dt.date) -> List[dt.date]:
    """First Friday of each month — US Non-Farm Payrolls."""
    out: List[dt.date] = []
    d = dt.date(start.year, start.month, 1)
    while d <= end:
        first_fri = d + dt.timedelta(days=(4 - d.weekday()) % 7)
        if start <= first_fri <= end:
            out.append(first_fri)
        d = dt.date(d.year + (d.month == 12), 1 if d.month == 12 else d.month + 1, 1)
    return out


def _cpi_dates(start: dt.date, end: dt.date) -> List[dt.date]:
    """Approximate US CPI release dates (~2nd Wednesday of each month).

    BLS schedule actually drifts between Tue–Thu in the 10-15 day range;
    using 2nd Wednesday as a robust proxy for filter purposes.
    """
    out: List[dt.date] = []
    d = dt.date(start.year, start.month, 1)
    while d <= end:
        first_wed = d + dt.timedelta(days=(2 - d.weekday()) % 7)
        second_wed = first_wed + dt.timedelta(days=7)
        if start <= second_wed <= end:
            out.append(second_wed)
        d = dt.date(d.year + (d.month == 12), 1 if d.month == 12 else d.month + 1, 1)
    return out


def _expand_window(dates: List[dt.date], window_days: int) -> set:
    """Returns set of all dates within ±window_days of any date in input."""
    out: set = set()
    for d in dates:
        for off in range(-window_days, window_days + 1):
            out.add(d + dt.timedelta(days=off))
    return out


# ─────────────────────────── Filter grid ─────────────────────────────────


@dataclass
class FilterCombo:
    min_size_sigma: float       # multiples of per-package mean abs signal
    vol_keep: str               # "all" | "drop_low" | "high_only"
    drop_fomc: bool             # ±fomc_window business days
    fomc_window: int            # days around FOMC to drop (only if drop_fomc)
    drop_data_days: bool        # NFP + CPI release days
    polarity: str               # "fade" | "momentum"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "polarity":         self.polarity,
            "min_size_sigma":   self.min_size_sigma,
            "vol_keep":         self.vol_keep,
            "drop_fomc":        self.drop_fomc,
            "fomc_window":      self.fomc_window if self.drop_fomc else 0,
            "drop_data_days":   self.drop_data_days,
        }


def filter_grid() -> List[FilterCombo]:
    grid: List[FilterCombo] = []
    for size, vol, fomc, data, polarity in product(
        [0.0, 0.5, 1.0, 1.5, 2.0, 3.0],          # 6 size thresholds
        ["all", "drop_low", "high_only"],         # 3 vol options
        [False, True],                            # 2 FOMC options
        [False, True],                            # 2 data options
        ["fade", "momentum"],                     # 2 polarities
    ):
        grid.append(FilterCombo(
            min_size_sigma=size,
            vol_keep=vol,
            drop_fomc=fomc,
            fomc_window=2,
            drop_data_days=data,
            polarity=polarity,
        ))
    return grid


# ─────────────────────────── Tag computations ────────────────────────────


def tag_vol_regime(trades: pd.DataFrame, vol_window: int = 21) -> pd.DataFrame:
    """Tag each trade with low/mid/high vol bucket using rolling std of
    signal_move_bp on this package only."""
    if trades.empty:
        trades = trades.copy()
        trades["vol_regime"] = pd.Series(dtype=object)
        return trades
    s = trades.sort_values("date").copy()
    rv = s["signal_move_bp"].rolling(vol_window, min_periods=5).std()
    cat = pd.qcut(rv, 3, labels=["low_vol", "mid_vol", "high_vol"], duplicates="drop")
    s["vol_regime"] = cat.astype(object).fillna("mid_vol")
    return s


def apply_filter(
    trades: pd.DataFrame,
    f: FilterCombo,
    sigma_pkg: float,
    fomc_blackout: set,
    data_dates: set,
) -> pd.DataFrame:
    if trades.empty:
        return trades

    df = trades

    # Polarity flip: framework gives PAYER PnL, our trade_direction column was
    # set with the configured polarity at build time (default "fade").  To
    # also run "momentum" without re-running the engine we flip net_usd sign.
    if f.polarity == "momentum":
        df = df.copy()
        df["net_usd"] = -df["net_usd"]
        df["gross_usd"] = -df["gross_usd"]

    # 1. signal size threshold
    if f.min_size_sigma > 0:
        df = df[df["abs_signal_move_bp"] >= f.min_size_sigma * sigma_pkg]

    # 2. vol regime
    if f.vol_keep == "drop_low":
        df = df[df["vol_regime"] != "low_vol"]
    elif f.vol_keep == "high_only":
        df = df[df["vol_regime"] == "high_vol"]
    # else: keep all

    # 3. FOMC blackout
    if f.drop_fomc and fomc_blackout:
        df = df[~df["date"].dt.date.isin(fomc_blackout)]

    # 4. economic data days
    if f.drop_data_days and data_dates:
        df = df[~df["date"].dt.date.isin(data_dates)]

    return df


# ─────────────────────────── Per-cell metrics ────────────────────────────


def cell_metrics(trades: pd.DataFrame, n_trading_days: int) -> Dict[str, Any]:
    if trades.empty or len(trades) < 2:
        return {
            "n_trades": int(len(trades)),
            "hit_rate": float("nan"),
            "avg_usd":  float("nan"),
            "total_usd": float(trades["net_usd"].sum()) if len(trades) else 0.0,
            "sharpe":   float("nan"),
            "max_dd_usd": float("nan"),
        }
    cum = trades.sort_values("date")["net_usd"].cumsum()
    dd = (cum - cum.cummax()).min()
    return {
        "n_trades":   int(len(trades)),
        "hit_rate":   float((trades["net_usd"] > 0).mean()),
        "avg_usd":    float(trades["net_usd"].mean()),
        "total_usd":  float(trades["net_usd"].sum()),
        "sharpe":     _annualized_sharpe(trades["net_usd"], n_trading_days),
        "max_dd_usd": float(dd) if not np.isnan(dd) else 0.0,
    }


# ─────────────────────────── Per-package backtest ────────────────────────


def run_one_package(cfg_template: Dict[str, Any], pkg: Package, mdp: IRSwapsMDP,
                    rates: Optional[pd.DataFrame] = None) -> Tuple[pd.DataFrame, AsiaFadeConfig]:
    """Build trades for a single package using the FADE polarity (we'll flip
    in post-processing for momentum).  Reuses pre-loaded rates if provided."""
    cfg = AsiaFadeConfig.from_dict({
        **cfg_template,
        "tenors": [pkg.tenor],
        "show_progress": False,
        "signal_polarity": "fade",
    })
    if rates is None:
        rates = load_intraday_rates(cfg, mdp=mdp)
    elif pkg.tenor not in rates.columns:
        # Need to load this package's rates
        rates = load_intraday_rates(cfg, mdp=mdp)

    events = build_trade_events(cfg, rates)
    if not events:
        return pd.DataFrame(), cfg

    strategy, time_grid = build_strategy(cfg, events)
    bt = QueryDrivenBacktest(
        time_grid=time_grid, mdp=mdp, strategy=strategy,
        show_progress=False, progress_desc=f"GRID {pkg.label}",
    )
    bt.run()
    trades = trades_dataframe(bt, events)
    trades["package"] = pkg.label
    trades["tenor"]   = pkg.tenor
    trades["structure"] = pkg.structure
    return trades, cfg


# ─────────────────────────── Main grid runner ────────────────────────────


def run_grid(
    start: str,
    end: str,
    out_dir: Path,
    bid_ask_bp_rt: float = 0.5,
    base_bpv_usd: float = 100_000.0,
    bar_freq: str = "5min",
    min_trades_per_cell: int = 30,
) -> pd.DataFrame:
    out_dir.mkdir(parents=True, exist_ok=True)

    cfg_template = {
        "start": start, "end": end,
        "curve": "USD-SOFR-1D-Q12STIRT",
        "mdp_source": "BARCHART_STIRF-RL",
        "bar_freq": bar_freq,
        "base_bpv_usd": base_bpv_usd,
        "bid_ask_bp_rt": bid_ask_bp_rt,
        "commission_per_side_usd": 0.50,
        "slippage_bp_rt": 0.0,
        "min_signal_move_bp": 0.0,
    }
    mdp = IRSwapsMDP(source=cfg_template["mdp_source"])

    # Load all rates in ONE TimeseriesBuilder call (much faster than per-pkg)
    cfg_all = AsiaFadeConfig.from_dict({
        **cfg_template,
        "tenors": [p.tenor for p in PACKAGES],
        "show_progress": True,
    })
    logger.info("Loading rates for %d packages in one batch...", len(PACKAGES))
    all_rates = load_intraday_rates(cfg_all, mdp=mdp)
    logger.info("Got rate panel: shape=%s, columns=%s", all_rates.shape, list(all_rates.columns))

    start_d = dt.date.fromisoformat(start)
    end_d   = dt.date.fromisoformat(end)
    n_days  = len(trading_dates(start_d, end_d))

    # Calendars
    fomc        = _fomc_dates()
    nfp         = _nfp_dates(start_d, end_d)
    cpi         = _cpi_dates(start_d, end_d)
    fomc_window = _expand_window(fomc, 2)
    data_dates  = set(nfp) | set(cpi)
    logger.info("Calendars: FOMC=%d (±2d window=%d), NFP=%d, CPI=%d",
                len(fomc), len(fomc_window), len(nfp), len(cpi))

    # Run each package once and tag vol regime
    trades_by_pkg: Dict[str, pd.DataFrame] = {}
    sigma_by_pkg:  Dict[str, float] = {}
    for pkg in PACKAGES:
        if pkg.tenor not in all_rates.columns:
            logger.warning("Package %s tenor %s not in rates panel — skipping",
                           pkg.label, pkg.tenor)
            continue
        logger.info("Backtesting %s [%s, %s]", pkg.label, pkg.tenor, pkg.structure)
        trades, cfg_pkg = run_one_package(cfg_template, pkg, mdp, rates=all_rates)
        if trades.empty:
            logger.warning("  → 0 trades, skipping")
            continue
        trades = tag_vol_regime(trades)
        trades_by_pkg[pkg.label] = trades
        sigma_by_pkg[pkg.label]  = float(trades["abs_signal_move_bp"].mean())
        logger.info("  → %d trades, σ_pkg = %.3f bp",
                    len(trades), sigma_by_pkg[pkg.label])

    # Persist combined trades for re-use
    if trades_by_pkg:
        all_trades_df = pd.concat(trades_by_pkg.values(), ignore_index=True)
        all_trades_df.to_parquet(out_dir / "all_trades.parquet")
        logger.info("Wrote %s (%d rows)", out_dir / "all_trades.parquet", len(all_trades_df))

    # Run filter grid
    grid = filter_grid()
    logger.info("Evaluating %d filter combos × %d packages = %d cells",
                len(grid), len(trades_by_pkg), len(grid) * len(trades_by_pkg))

    rows: List[Dict[str, Any]] = []
    for pkg_label, trades in trades_by_pkg.items():
        sigma = sigma_by_pkg[pkg_label]
        pkg_meta = next(p for p in PACKAGES if p.label == pkg_label)
        for f in grid:
            filtered = apply_filter(trades, f, sigma, fomc_window, data_dates)
            m = cell_metrics(filtered, n_days)
            if m["n_trades"] < min_trades_per_cell:
                continue
            rows.append({
                "package":   pkg_label,
                "structure": pkg_meta.structure,
                "tenor":     pkg_meta.tenor,
                "sigma_pkg_bp": sigma,
                **f.as_dict(),
                **m,
            })

    if not rows:
        logger.error("No grid cells passed the min_trades_per_cell=%d gate",
                     min_trades_per_cell)
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df.to_csv(out_dir / "grid_results.csv", index=False)

    # Best per package (by Sharpe)
    best_per_pkg = df.loc[df.groupby("package")["sharpe"].idxmax()].sort_values(
        "sharpe", ascending=False)
    best_per_pkg.to_csv(out_dir / "best_per_package.csv", index=False)

    # Top by Sharpe and by total $
    top_sharpe = df.sort_values("sharpe", ascending=False).head(25)
    top_sharpe.to_csv(out_dir / "top_by_sharpe.csv", index=False)

    top_total = df.sort_values("total_usd", ascending=False).head(25)
    top_total.to_csv(out_dir / "top_by_total_usd.csv", index=False)

    # Pretty summary
    summary = build_summary(df, best_per_pkg, top_sharpe, top_total,
                            cfg_template, n_days, sigma_by_pkg)
    (out_dir / "summary.txt").write_text(summary, encoding="utf-8")
    print(summary)
    return df


# ─────────────────────────── Reporting ───────────────────────────────────


def _fmt(df: pd.DataFrame, cols: List[str], top: int = 25) -> str:
    if df.empty:
        return "(empty)"
    fmts = {
        "sharpe":         lambda v: f"{v:+.2f}" if pd.notna(v) else "n/a",
        "hit_rate":       lambda v: f"{v:.1%}"  if pd.notna(v) else "n/a",
        "avg_usd":        lambda v: f"{v:+,.0f}" if pd.notna(v) else "n/a",
        "total_usd":      lambda v: f"{v:+,.0f}" if pd.notna(v) else "n/a",
        "max_dd_usd":     lambda v: f"{v:+,.0f}" if pd.notna(v) else "n/a",
        "sigma_pkg_bp":   lambda v: f"{v:.2f}"  if pd.notna(v) else "n/a",
        "min_size_sigma": lambda v: f"{v:.1f}",
        "fomc_window":    lambda v: f"{int(v)}",
        "n_trades":       lambda v: f"{int(v):,}",
        "drop_fomc":      lambda v: "Y" if v else "n",
        "drop_data_days": lambda v: "Y" if v else "n",
    }
    return df[cols].head(top).to_string(
        index=False,
        formatters={c: fmts[c] for c in cols if c in fmts},
    )


def build_summary(
    df: pd.DataFrame,
    best_per_pkg: pd.DataFrame,
    top_sharpe: pd.DataFrame,
    top_total: pd.DataFrame,
    cfg: Dict[str, Any],
    n_days: int,
    sigma_by_pkg: Dict[str, float],
) -> str:
    buf = io.StringIO()
    p = lambda *a, **k: print(*a, **k, file=buf)
    cols = ["package", "structure", "polarity", "min_size_sigma", "vol_keep",
            "drop_fomc", "fomc_window", "drop_data_days",
            "n_trades", "hit_rate", "avg_usd", "sharpe", "total_usd", "max_dd_usd"]

    p("=" * 110)
    p("Asia Fade SFR — GRID SEARCH SUMMARY")
    p(f"Window: {cfg['start']} → {cfg['end']}   ({n_days} trading days)")
    p(f"Curve: {cfg['curve']}   Bar freq: {cfg['bar_freq']}")
    p(f"Costs: bid-ask {cfg['bid_ask_bp_rt']}bp RT  + commission ${cfg['commission_per_side_usd']}/side")
    p(f"Cells (after min_trades gate): {len(df):,}   Packages: {df['package'].nunique()}")
    p("")

    p("--- PACKAGE σ (mean abs signal_move_bp, 5pm→10pm) ---")
    for pkg, sig in sorted(sigma_by_pkg.items(), key=lambda x: x[1], reverse=True):
        p(f"  {pkg:24s} σ={sig:.3f} bp")
    p("")

    p("--- BEST FILTER COMBO PER PACKAGE (ranked by Sharpe) ---")
    p(_fmt(best_per_pkg, cols, top=len(best_per_pkg)))
    p("")

    p("--- TOP 25 BY SHARPE (across all packages × filter combos) ---")
    p(_fmt(top_sharpe, cols, top=25))
    p("")

    p("--- TOP 25 BY TOTAL P&L ---")
    p(_fmt(top_total, cols, top=25))
    p("")

    # Headline rules
    p("--- HEADLINE RULES (positive Sharpe AND ≥150 trades) ---")
    headline = df[(df["sharpe"] > 0) & (df["n_trades"] >= 150)] \
                .sort_values("sharpe", ascending=False).head(15)
    p(_fmt(headline, cols, top=15))
    return buf.getvalue()


# ─────────────────────────── CLI ─────────────────────────────────────────


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=str, default="2021-05-01")
    ap.add_argument("--end",   type=str, default="2026-05-14")
    ap.add_argument("--bid-ask-bp", type=float, default=0.5)
    ap.add_argument("--base-bpv", type=float, default=100_000.0)
    ap.add_argument("--bar-freq", type=str, default="5min")
    ap.add_argument("--min-trades", type=int, default=30,
                    help="ignore filter cells with fewer trades than this")
    ap.add_argument("--out", type=str,
                    default=str(Path(r"C:\Users\chris\clee\ARBS\BT\results\asia_fade_grid")))
    args = ap.parse_args(argv)

    out_dir = Path(args.out)
    df = run_grid(
        start=args.start, end=args.end,
        out_dir=out_dir,
        bid_ask_bp_rt=args.bid_ask_bp,
        base_bpv_usd=args.base_bpv,
        bar_freq=args.bar_freq,
        min_trades_per_cell=args.min_trades,
    )
    return 0 if not df.empty else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
