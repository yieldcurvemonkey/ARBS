"""Runner for the query-driven Asia Fade SFR backtest.

Usage (from repo root):
    conda run -n stir python BT/signals/asia_fade_run.py
    conda run -n stir python BT/signals/asia_fade_run.py --start 2024-01-01 --end 2026-05-14
    conda run -n stir python BT/signals/asia_fade_run.py --polarity momentum
    conda run -n stir python BT/signals/asia_fade_run.py --tenors IMM_1xIMM_2,IMM_5xIMM_6,IMM_9xIMM_10

Outputs land under BT/results/asia_fade/.

The backtest is driven by ``BT.signals.asia_fade_sfr.run_asia_fade(config)``
which consumes a ``dict``-shaped config — so all tenor/curve/timing/cost
knobs can be set without code changes.
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pandas as pd

# Force UTF-8 stdout on Windows
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except Exception:
    pass

sys.path.insert(0, r"C:\Users\chris\clee\ARBS")

from BT.signals.asia_fade_sfr import (  # noqa: E402
    SECTORS,
    AsiaFadeConfig,
    metrics_by_fomc,
    metrics_by_signal_size,
    metrics_by_vol_regime,
    metrics_for_group,
    metrics_per_sector,
    metrics_per_tenor,
    run_asia_fade,
    trading_dates,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)
logger = logging.getLogger("asia_fade_run")


# ────────────────────────────── Plotting ────────────────────────────────


def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.style.use("ggplot")
    return plt


def plot_equity_curve(trades: pd.DataFrame, out: Path) -> None:
    plt = _plt()
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13, 9), sharex=True)
    daily = trades.groupby("date")["net_usd"].sum().sort_index()
    ax1.plot(daily.index, daily.cumsum().values, lw=1.6, color="#2c5aa0")
    ax1.set_title("Asia Fade SFR — Cumulative Net P&L (USD)")
    ax1.set_ylabel("Cum P&L ($)")
    ax1.axhline(0, color="k", lw=0.5)
    ax1.grid(True, alpha=0.4)
    for name, color in zip(SECTORS, ["#1f77b4", "#d62728", "#2ca02c", "#9467bd"]):
        s = trades[trades["sector"] == name].groupby("date")["net_usd"].sum().sort_index()
        if not s.empty:
            ax2.plot(s.index, s.cumsum().values, lw=1.4, label=name, color=color)
    ax2.set_title("Cumulative Net P&L by Sector")
    ax2.set_ylabel("Cum P&L ($)")
    ax2.set_xlabel("Date")
    ax2.legend(loc="best")
    ax2.axhline(0, color="k", lw=0.5)
    ax2.grid(True, alpha=0.4)
    fig.tight_layout()
    fig.savefig(out, dpi=130)
    plt.close(fig)


def plot_signal_size(trades: pd.DataFrame, cfg: AsiaFadeConfig, n_days: int, out: Path) -> None:
    plt = _plt()
    df = metrics_by_signal_size(trades, cfg, n_days)
    if df.empty:
        return
    fig, axes = plt.subplots(1, 3, figsize=(16, 5))
    axes[0].bar(df["size_bin"], df["sharpe"], color="#2c5aa0")
    axes[0].set_title("Sharpe vs Asia move size")
    axes[0].axhline(0, color="k", lw=0.6); axes[0].grid(True, alpha=0.3)
    axes[1].bar(df["size_bin"], df["hit_rate"], color="#2ca02c")
    axes[1].set_title("Hit rate vs Asia move size")
    axes[1].axhline(0.5, color="k", lw=0.6, ls="--"); axes[1].grid(True, alpha=0.3)
    axes[2].bar(df["size_bin"], df["avg_usd"], color="#d62728")
    axes[2].set_title("Avg P&L ($) vs Asia move size")
    axes[2].axhline(0, color="k", lw=0.6); axes[2].grid(True, alpha=0.3)
    for ax in axes:
        ax.tick_params(axis="x", rotation=20)
    fig.tight_layout()
    fig.savefig(out, dpi=130)
    plt.close(fig)


def plot_sector_bars(trades: pd.DataFrame, n_days: int, out: Path) -> None:
    plt = _plt()
    df = metrics_per_sector(trades, n_days)
    if df.empty:
        return
    fig, axes = plt.subplots(2, 2, figsize=(13, 9))
    axes = axes.flatten()
    for ax, col, title in zip(
        axes,
        ["sharpe", "hit_rate", "avg_usd", "total_usd"],
        ["Sharpe", "Hit rate", "Avg P&L ($)", "Total P&L ($)"],
    ):
        ax.bar(df["sector"], df[col], color=["#1f77b4", "#d62728", "#2ca02c", "#9467bd"])
        ax.set_title(title)
        ax.grid(True, alpha=0.3); ax.axhline(0, color="k", lw=0.6)
    fig.suptitle("Per-Sector Metrics — Asia Fade SFR", y=1.02)
    fig.tight_layout()
    fig.savefig(out, dpi=130, bbox_inches="tight")
    plt.close(fig)


def plot_tenor_bars(trades: pd.DataFrame, n_days: int, out: Path) -> None:
    plt = _plt()
    df = metrics_per_tenor(trades, n_days)
    if df.empty:
        return
    df = df.sort_values("rank")
    fig, axes = plt.subplots(2, 1, figsize=(13, 8), sharex=True)
    axes[0].bar(df["tenor"], df["sharpe"], color="#2c5aa0")
    axes[0].set_title("Sharpe per Tenor")
    axes[0].axhline(0, color="k", lw=0.6); axes[0].grid(True, alpha=0.3)
    axes[1].bar(df["tenor"], df["avg_usd"], color="#d62728")
    axes[1].set_title("Avg P&L ($) per Tenor")
    axes[1].axhline(0, color="k", lw=0.6); axes[1].grid(True, alpha=0.3)
    axes[1].tick_params(axis="x", rotation=30)
    fig.tight_layout()
    fig.savefig(out, dpi=130)
    plt.close(fig)


def plot_calendar_heatmap(trades: pd.DataFrame, out: Path) -> None:
    plt = _plt()
    if trades.empty:
        return
    df = trades.copy()
    df["ym"] = df["date"].dt.to_period("M")
    monthly = df.groupby("ym")["net_usd"].sum().to_timestamp()
    if monthly.empty:
        return
    m = monthly.reset_index()
    m.columns = ["date", "pnl"]
    m["year"] = m["date"].dt.year
    m["month"] = m["date"].dt.month
    piv = m.pivot(index="year", columns="month", values="pnl").reindex(columns=range(1, 13))
    fig, ax = plt.subplots(figsize=(13, max(3, 0.6 * len(piv))))
    vmax = max(abs(np.nanmin(piv.values)), abs(np.nanmax(piv.values))) if piv.size else 1
    im = ax.imshow(piv.values, aspect="auto", cmap="RdYlGn", vmin=-vmax, vmax=vmax)
    ax.set_yticks(range(len(piv)))
    ax.set_yticklabels(piv.index)
    ax.set_xticks(range(12))
    ax.set_xticklabels(["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"])
    ax.set_title("Monthly Net P&L ($) — Asia Fade SFR")
    for y in range(piv.shape[0]):
        for x in range(piv.shape[1]):
            v = piv.values[y, x]
            if not np.isnan(v):
                ax.text(x, y, f"{v/1000:+.0f}k", ha="center", va="center", fontsize=8)
    fig.colorbar(im, ax=ax, label="$")
    fig.tight_layout()
    fig.savefig(out, dpi=130)
    plt.close(fig)


def plot_conditioning(
    trades: pd.DataFrame, fomc_dates: List[dt.date], cfg: AsiaFadeConfig, n_days: int, out: Path,
) -> None:
    plt = _plt()
    fomc_df = metrics_by_fomc(trades, fomc_dates, cfg, n_days)
    vol_df  = metrics_by_vol_regime(trades, n_days)
    if fomc_df.empty and vol_df.empty:
        return
    fig, axes = plt.subplots(2, 2, figsize=(13, 9))
    if not fomc_df.empty:
        ord_ = ["pre_FOMC", "FOMC_day", "post_FOMC", "non_FOMC"]
        fomc_df = fomc_df.set_index("fomc_bucket").reindex(ord_).reset_index()
        axes[0, 0].bar(fomc_df["fomc_bucket"], fomc_df["sharpe"], color="#2c5aa0")
        axes[0, 0].set_title("Sharpe vs FOMC bucket"); axes[0, 0].axhline(0, color="k", lw=0.6)
        axes[0, 1].bar(fomc_df["fomc_bucket"], fomc_df["avg_usd"], color="#d62728")
        axes[0, 1].set_title("Avg P&L ($) vs FOMC bucket"); axes[0, 1].axhline(0, color="k", lw=0.6)
    if not vol_df.empty:
        vol_df = vol_df.set_index("vol_bucket").reindex(["low_vol", "mid_vol", "high_vol"]).reset_index().dropna(subset=["vol_bucket"])
        axes[1, 0].bar(vol_df["vol_bucket"], vol_df["sharpe"], color="#2ca02c")
        axes[1, 0].set_title("Sharpe vs Vol regime"); axes[1, 0].axhline(0, color="k", lw=0.6)
        axes[1, 1].bar(vol_df["vol_bucket"], vol_df["avg_usd"], color="#9467bd")
        axes[1, 1].set_title("Avg P&L ($) vs Vol regime"); axes[1, 1].axhline(0, color="k", lw=0.6)
    for r in axes:
        for ax in r:
            ax.grid(True, alpha=0.3)
    fig.suptitle("Conditioning Analysis — Asia Fade SFR", y=1.02)
    fig.tight_layout()
    fig.savefig(out, dpi=130, bbox_inches="tight")
    plt.close(fig)


# ────────────────────────────── Summary ─────────────────────────────────


def _fmt(df: pd.DataFrame, cols: List[str]) -> str:
    if df.empty:
        return "(empty)"
    fmt = {
        "sharpe":           lambda v: f"{v:+.2f}" if pd.notna(v) else "n/a",
        "hit_rate":         lambda v: f"{v:.1%}"  if pd.notna(v) else "n/a",
        "avg_usd":          lambda v: f"{v:+,.0f}" if pd.notna(v) else "n/a",
        "avg_win_usd":      lambda v: f"{v:+,.0f}" if pd.notna(v) else "n/a",
        "avg_loss_usd":     lambda v: f"{v:+,.0f}" if pd.notna(v) else "n/a",
        "total_usd":        lambda v: f"{v:+,.0f}" if pd.notna(v) else "n/a",
        "max_dd_usd":       lambda v: f"{v:+,.0f}" if pd.notna(v) else "n/a",
        "avg_signal_size_bp": lambda v: f"{v:.2f}"  if pd.notna(v) else "n/a",
        "n_trades":         lambda v: f"{int(v):,}",
        "rank":             lambda v: f"{int(v) if pd.notna(v) else '-'}",
    }
    return df[cols].to_string(index=False, formatters={c: fmt[c] for c in cols if c in fmt})


def write_summary(
    trades: pd.DataFrame, cfg: AsiaFadeConfig,
    fomc_dates: List[dt.date], n_days: int, out_path: Path,
) -> str:
    buf = io.StringIO()
    p = lambda *a, **k: print(*a, **k, file=buf)

    p("=" * 100)
    p("Asia Fade SFR — Backtest Summary  (Query-driven / event-based)")
    p(f"Window: {cfg.start} → {cfg.end}   ({n_days} trading days)")
    p(f"Source: {cfg.mdp_source}   Curve: {cfg.curve}   Tenors: {len(cfg.tenors)}")
    p(f"Polarity: {cfg.signal_polarity}   Base BPV: ${cfg.base_bpv_usd:,.0f}/bp")
    p(f"Signal window ET: {cfg.signal_start_hhmm[0]:02d}:{cfg.signal_start_hhmm[1]:02d} → "
      f"{cfg.signal_end_hhmm[0]:02d}:{cfg.signal_end_hhmm[1]:02d}   "
      f"Entry: {cfg.entry_hhmm[0]:02d}:{cfg.entry_hhmm[1]:02d}   "
      f"Exit: {cfg.exit_hhmm[0]:02d}:{cfg.exit_hhmm[1]:02d} (+{cfg.exit_day_offset}bd)")
    p(f"Costs: bid-ask {cfg.bid_ask_bp_rt}bp RT  + commission ${cfg.commission_per_side_usd}/side  "
      f"+ slippage {cfg.slippage_bp_rt}bp RT")
    p(f"Total trades: {len(trades):,}")
    p("")

    overall = metrics_for_group(trades, n_days)
    p("--- OVERALL ---")
    p(f"  n_trades   : {overall['n_trades']:,}")
    p(f"  hit_rate   : {overall['hit_rate']:.1%}")
    p(f"  avg_usd    : ${overall['avg_usd']:+,.0f}")
    p(f"  Sharpe     : {overall['sharpe']:+.2f}")
    p(f"  total_usd  : ${overall['total_usd']:+,.0f}")
    p(f"  max_dd_usd : ${overall['max_dd_usd']:+,.0f}")
    p("")

    p("--- PER SECTOR ---")
    sec = metrics_per_sector(trades, n_days)
    p(_fmt(sec, ["sector","n_trades","hit_rate","avg_usd","avg_win_usd","avg_loss_usd",
                 "sharpe","total_usd","max_dd_usd","avg_signal_size_bp"]))
    p("")

    p("--- PER TENOR ---")
    ten = metrics_per_tenor(trades, n_days)
    p(_fmt(ten, ["tenor","rank","sector","n_trades","hit_rate","avg_usd",
                 "sharpe","total_usd","max_dd_usd","avg_signal_size_bp"]))
    p("")

    p("--- BY ASIA SIGNAL SIZE ---")
    p(_fmt(metrics_by_signal_size(trades, cfg, n_days),
           ["size_bin","n_trades","hit_rate","avg_usd","sharpe","total_usd"]))
    p("")

    p("--- BY FOMC BUCKET ---")
    p(_fmt(metrics_by_fomc(trades, fomc_dates, cfg, n_days),
           ["fomc_bucket","n_trades","hit_rate","avg_usd","sharpe","total_usd"]))
    p("")

    p("--- BY VOL REGIME ---")
    p(_fmt(metrics_by_vol_regime(trades, n_days),
           ["vol_bucket","n_trades","hit_rate","avg_usd","sharpe","total_usd"]))
    p("")

    p("--- BREAKEVEN ANALYSIS (bid-ask sensitivity, bp RT) ---")
    if not trades.empty:
        for bp in [0.0, 0.125, 0.25, 0.5, 1.0]:
            new_cost = bp * abs(cfg.base_bpv_usd) + 2.0 * cfg.commission_per_side_usd
            net = trades["gross_usd"] - new_cost
            total = float(net.sum())
            hr = float((net > 0).mean())
            sr = (net.mean() / net.std() * np.sqrt(252)) if net.std() > 0 else 0.0
            p(f"  bid_ask={bp:.3f}bp  total=${total:+,.0f}  hit={hr:.1%}  per-trade SR≈{sr:+.2f}")

    text = buf.getvalue()
    out_path.write_text(text, encoding="utf-8")
    return text


# ────────────────────────────── Main ─────────────────────────────────


def _fomc_dates() -> List[dt.date]:
    try:
        from SDRUtils.analytics.seasonality import get_fomc_dates
        return get_fomc_dates()
    except Exception as e:
        logger.warning("FOMC dates unavailable: %s — using empty list", e)
        return []


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=str, default="2023-05-01")
    ap.add_argument("--end",   type=str, default="2026-05-14")
    ap.add_argument("--curve", type=str, default="USD-SOFR-1D-Q12STIRT")
    ap.add_argument("--mdp-source", type=str, default="BARCHART_STIRF-RL")
    ap.add_argument("--tenors", type=str, default="",
                    help="comma-separated, e.g. IMM_1xIMM_2,IMM_5xIMM_6 (empty = ranks 1-12)")
    ap.add_argument("--polarity", type=str, choices=["fade", "momentum"], default="fade")
    ap.add_argument("--bar-freq", type=str, default="5min")
    ap.add_argument("--base-bpv", type=float, default=100_000.0)
    ap.add_argument("--bid-ask-bp", type=float, default=0.5)
    ap.add_argument("--commission", type=float, default=0.50)
    ap.add_argument("--slippage-bp", type=float, default=0.0)
    ap.add_argument("--min-signal-bp", type=float, default=0.0)
    args = ap.parse_args(argv)

    tenors = [t.strip() for t in args.tenors.split(",") if t.strip()]
    cfg_dict: Dict[str, Any] = {
        "start": args.start,
        "end":   args.end,
        "curve": args.curve,
        "mdp_source": args.mdp_source,
        "bar_freq": args.bar_freq,
        "base_bpv_usd": args.base_bpv,
        "bid_ask_bp_rt": args.bid_ask_bp,
        "commission_per_side_usd": args.commission,
        "slippage_bp_rt": args.slippage_bp,
        "min_signal_move_bp": args.min_signal_bp,
        "signal_polarity": args.polarity,
    }
    if tenors:
        cfg_dict["tenors"] = tenors

    logger.info("Running with config: %s", cfg_dict)

    out = run_asia_fade(cfg_dict)
    cfg: AsiaFadeConfig = out["config"]
    trades: pd.DataFrame = out["trades"]

    cfg.results_path.mkdir(parents=True, exist_ok=True)
    cfg.plots_path.mkdir(parents=True, exist_ok=True)

    if trades.empty:
        logger.error("No trades produced.")
        return 2

    # Save artefacts
    trades.to_parquet(cfg.results_path / "trades.parquet")
    trades.to_csv(cfg.results_path / "trades.csv", index=False)

    n_days = len(trading_dates(cfg.start_date, cfg.end_date))
    fomc = _fomc_dates()

    metrics_per_tenor(trades, n_days).to_csv(cfg.results_path / "metrics_per_tenor.csv", index=False)
    metrics_per_sector(trades, n_days).to_csv(cfg.results_path / "metrics_per_sector.csv", index=False)
    metrics_by_signal_size(trades, cfg, n_days).to_csv(cfg.results_path / "metrics_by_signal_size.csv", index=False)
    metrics_by_fomc(trades, fomc, cfg, n_days).to_csv(cfg.results_path / "metrics_by_fomc.csv", index=False)
    metrics_by_vol_regime(trades, n_days).to_csv(cfg.results_path / "metrics_by_vol_regime.csv", index=False)

    logger.info("Plotting...")
    plot_equity_curve(trades, cfg.plots_path / "equity_curve.png")
    plot_sector_bars(trades, n_days, cfg.plots_path / "sector_metrics.png")
    plot_tenor_bars(trades, n_days, cfg.plots_path / "tenor_metrics.png")
    plot_signal_size(trades, cfg, n_days, cfg.plots_path / "signal_size.png")
    plot_calendar_heatmap(trades, cfg.plots_path / "calendar_heatmap.png")
    plot_conditioning(trades, fomc, cfg, n_days, cfg.plots_path / "conditioning.png")

    print(write_summary(trades, cfg, fomc, n_days, cfg.results_path / "summary.txt"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
