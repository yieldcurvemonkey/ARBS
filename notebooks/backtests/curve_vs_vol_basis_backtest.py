"""Curve-vs-vol basis mean-reversion backtest (pairs), three honesty stages.

Stage ``stats``  : mean-reversion diagnostics of the pair_rent basis
                   (AR1 half-life raw + 5dMA, diff autocorr, VR(5)).
Stage ``grid``   : z-score fade grid on BASIS marks (model marks — upper bound,
                   never a tradeability verdict). ``--lag 1`` executes entries
                   and exits at the next day's marks (default; lag 0 reproduces
                   the same-bar inflation for comparison).
Stage ``replay`` : replays a config's trades as Ticket-A packages (futures
                   steepener + two wings) marked on LISTED settle premiums.
Stage ``premnat``: premium-native RR-spread basis — signal and marks are the
                   same executable object (4-leg risk-reversal spread between
                   the legs), lag-1 execution, fixed entry strikes.

Findings on 2025-06..2026-07 (documented in the spec): the basis-marked grid
is inflated by same-bar execution (-56..-72% at lag 1) and its profits are
anti-correlated with listed-premium marks (corr -0.13..-0.51); the strategy is
not tradeable as constructed at daily EOD frequency. Keep this runner as the
harness for event-window / intraday variants.

Usage:
  conda run -n stir python notebooks/backtests/curve_vs_vol_basis_backtest.py \
      --stage stats|grid --in-dir notebooks/data/fly_vs_vol
"""
from __future__ import annotations

import argparse
import itertools
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from RVUtils.FlyVsVol.pairs import build_pair_history
from RVUtils.FlyVsVol.screener import series_half_life

CFG = dict(
    signals=("pair_rent_skew_bp", "pair_rent_bp"),
    mas=(1, 5, 10),
    zscore_windows=(60, 120),
    entry_zs=(1.5, 2.0, 2.5),
    exits=("z0", "half", "t10"),
    max_holding_days=20,
    round_trip_cost_bp=2.5,
)


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--stage", choices=["stats", "grid"], default="stats")
    p.add_argument("--in-dir", type=Path, default=Path("notebooks/data/fly_vs_vol"))
    p.add_argument("--out-dir", type=Path, default=Path("notebooks/data/fly_vs_vol"))
    p.add_argument("--lag", type=int, default=1,
                   help="execution lag in days (1 = next-day marks, honest)")
    return p.parse_args(argv)


def load_pairs(in_dir: Path) -> pd.DataFrame:
    panel = pd.read_parquet(in_dir / "contracts.parquet")
    return build_pair_history(panel)


def run_stats(hist: pd.DataFrame) -> None:
    print("=" * 88)
    print("CURVE-VS-VOL BASIS | mean-reversion diagnostics (pair_rent_skew_bp)")
    print("=" * 88)
    for label, sub in hist.groupby("label"):
        s = sub.sort_values("as_of")["pair_rent_skew_bp"].reset_index(drop=True)
        d = s.diff().dropna()
        vr5 = (s.diff(5).dropna().var() / (5 * d.var())) if d.var() > 0 else np.nan
        print(f"  {label}: n={len(s)} std={s.std():.2f}bp "
              f"hl_raw={series_half_life(s):.1f}d "
              f"hl_5dma={series_half_life(s.rolling(5).mean()):.1f}d "
              f"ac1(diff)={d.autocorr():.2f} VR(5)={vr5:.2f}")


def run_grid(hist: pd.DataFrame, out_dir: Path, lag: int) -> None:
    frames = {l: s.sort_values("as_of").reset_index(drop=True)
              for l, s in hist.groupby("label")}
    results, all_trades = [], []
    for sig, ma, zwin, ez, ex in itertools.product(
            CFG["signals"], CFG["mas"], CFG["zscore_windows"],
            CFG["entry_zs"], CFG["exits"]):
        trades = []
        for label, sub in frames.items():
            s = sub[sig].rolling(ma).mean()
            mu = s.rolling(zwin, min_periods=max(20, zwin // 3)).mean()
            sd = s.rolling(zwin, min_periods=max(20, zwin // 3)).std(ddof=0)
            z = ((s - mu) / sd.where(sd > 1e-9)).to_numpy()
            mark = sub["pair_rent_skew_bp"].to_numpy()
            ok = sub["quality_ok"].to_numpy()
            pos, ei = 0, None
            for i in range(len(sub)):
                if pos == 0:
                    if np.isfinite(z[i]) and abs(z[i]) >= ez and ok[i]:
                        pos, ei = -int(np.sign(z[i])), i
                else:
                    days = i - ei
                    if ex == "z0":
                        hit = np.isfinite(z[i]) and (z[i] * (-pos) <= 0)
                    elif ex == "half":
                        hit = np.isfinite(z[i]) and abs(z[i]) <= 0.5
                    else:
                        hit = days >= 10
                    if hit or days >= CFG["max_holding_days"] or i == len(sub) - 1:
                        j0 = min(ei + lag, len(sub) - 1)
                        j1 = min(i + lag, len(sub) - 1)
                        trades.append({
                            "label": label, "dir": pos, "days": days,
                            "entry": sub["as_of"].iloc[j0],
                            "exit": sub["as_of"].iloc[j1],
                            "gross": pos * (mark[j1] - mark[j0]),
                            "z_in": z[ei],
                        })
                        pos, ei = 0, None
        if not trades:
            continue
        t = pd.DataFrame(trades)
        g = t["gross"]
        cfg_label = f"{sig}|ma{ma}|w{zwin}|z{ez}|{ex}"
        results.append({
            "signal": sig, "ma": ma, "zwin": zwin, "entry_z": ez, "exit": ex,
            "n": len(t), "hit": (g > 0).mean(), "avg_gross": g.mean(),
            "tot_gross": g.sum(),
            "tot_net": (g - CFG["round_trip_cost_bp"]).sum(),
            "t_stat": (g.mean() / (g.std(ddof=1) / np.sqrt(len(t)))
                       if len(t) > 2 else np.nan),
            "avg_hold": t["days"].mean(), "worst": g.min(),
        })
        t["config"] = cfg_label
        all_trades.append(t)

    res = pd.DataFrame(results)
    out_dir.mkdir(parents=True, exist_ok=True)
    res.to_csv(out_dir / f"basis_grid_lag{lag}.csv", index=False)
    pd.concat(all_trades, ignore_index=True).to_csv(
        out_dir / f"basis_grid_trades_lag{lag}.csv", index=False)
    with pd.option_context("display.width", 220):
        print("=" * 88)
        print(f"CURVE-VS-VOL BASIS GRID | lag={lag} | "
              f"cost={CFG['round_trip_cost_bp']}bp | {len(res)} configs")
        print("=" * 88)
        print(f"  median tot_net: {res['tot_net'].median():+.2f}bp | "
              f"net-positive configs: {(res['tot_net'] > 0).mean():.0%}")
        print("\n  top 10 by tot_net (SELECTION-INFLATED — see deflated view):")
        print(res.sort_values("tot_net", ascending=False).head(10)
              .round(2).to_string(index=False))
        print("\n  parameter sensitivity (median tot_net per value):")
        for k in ("signal", "ma", "zwin", "entry_z", "exit"):
            print(f"    {k}: "
                  f"{res.groupby(k)['tot_net'].median().round(2).to_dict()}")


def main(argv=None):
    a = parse_args(argv)
    hist = load_pairs(a.in_dir)
    if a.stage == "stats":
        run_stats(hist)
    else:
        run_grid(hist, a.out_dir, a.lag)
    return 0


if __name__ == "__main__":
    sys.exit(main())
