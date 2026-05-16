"""
TFP Swap Spread Backtest — Grid Search over signal parameters.

Vectorized P&L: no QueryDrivenBacktest needed per combo.
Daily P&L (bp) = signal × ΔMMSS for each tenor, then aggregate.
"""
import datetime, os, sys, time, itertools, warnings
import numpy as np
import pandas as pd
sys.stdout.reconfigure(line_buffering=True)
warnings.filterwarnings("ignore")

from BT.signals.tfp_swap_spread import (
    BENCHMARK_TENORS, REGRESSION_TENORS,
    build_tfp_history, compute_tfp_regression,
)

# ── Load cached TFP history ────────────────────────────────────────────
CACHE_PATH = os.path.join("BT", "results", "tfp_screener", "tfp_history.parquet")
history = pd.read_parquet(CACHE_PATH)
history.index = pd.to_datetime(history.index)
print(f"Loaded {len(history)} rows ({history.index.min().date()} to {history.index.max().date()})", flush=True)

BT_START = pd.Timestamp("2021-01-04")
BT_END = pd.Timestamp("2026-05-12")
h = history.loc[BT_START:BT_END].copy()
print(f"Backtest window: {h.index.min().date()} to {h.index.max().date()} ({len(h)} days)", flush=True)

# ── Vectorized backtest engine ─────────────────────────────────────────

def _zscore_roll(series, window):
    mu = series.rolling(window, min_periods=max(window // 2, 10)).mean()
    sigma = series.rolling(window, min_periods=max(window // 2, 10)).std()
    return (series - mu) / sigma.replace(0, np.nan)


def _generate_signal_vec(z, z_entry, z_exit):
    """Vectorized signal: +1 receive, -1 pay, 0 flat."""
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
    return sig


def run_single_config(h, tenors, z_window, z_entry, z_exit, reg_tenors=None):
    """Run one parameter config, return metrics dict."""
    if reg_tenors is None:
        reg_tenors = REGRESSION_TENORS

    # Recompute deviations with given regression tenors
    dev_cols = {}
    mmss_cols = {}
    for t in tenors:
        dc = f"dev_{t}"
        mc = f"mmss_{t}"
        if dc in h.columns and mc in h.columns:
            dev_cols[t] = dc
            mmss_cols[t] = mc

    if not dev_cols:
        return None

    # Aggregate daily P&L across tenors
    daily_pnl = pd.Series(0.0, index=h.index)
    total_trades = 0
    total_winners = 0
    total_hold_days = 0
    tenor_results = {}

    for t in tenors:
        if t not in dev_cols:
            continue

        dev = h[dev_cols[t]]
        mmss = h[mmss_cols[t]]
        z = _zscore_roll(dev, z_window)
        sig = _generate_signal_vec(z.values, z_entry, z_exit)

        # Daily spread P&L (bp): signal * ΔMMSS
        # Receive spread (+1) profits when MMSS increases (narrows)
        d_mmss = mmss.diff()
        tenor_daily = pd.Series(sig, index=h.index, dtype=float) * d_mmss
        tenor_daily = tenor_daily.fillna(0)
        daily_pnl += tenor_daily

        # Trade stats
        sig_s = pd.Series(sig, index=h.index)
        entries = ((sig_s != 0) & (sig_s.shift(1).fillna(0) == 0))
        exits = ((sig_s == 0) & (sig_s.shift(1).fillna(0) != 0))
        n_trades = entries.sum()

        # Per-trade P&L
        trade_pnls = []
        in_trade = False
        trade_start = None
        cum = 0.0
        for i in range(len(sig)):
            if not in_trade and sig[i] != 0:
                in_trade = True
                trade_start = i
                cum = 0.0
            elif in_trade:
                cum += tenor_daily.iloc[i]
                if sig[i] == 0:
                    trade_pnls.append((cum, i - trade_start))
                    in_trade = False
        if in_trade:
            trade_pnls.append((cum, len(sig) - trade_start))

        wins = sum(1 for p, _ in trade_pnls if p > 0)
        hold = np.mean([d for _, d in trade_pnls]) if trade_pnls else 0

        total_trades += len(trade_pnls)
        total_winners += wins
        total_hold_days += hold * len(trade_pnls)

        tenor_results[t] = {
            "trades": len(trade_pnls),
            "hit_rate": wins / len(trade_pnls) if trade_pnls else 0,
            "total_bp": sum(p for p, _ in trade_pnls),
            "avg_hold": hold,
        }

    # Portfolio metrics
    cum_pnl = daily_pnl.cumsum()
    if daily_pnl.std() == 0 or len(daily_pnl.dropna()) < 20:
        return None

    sharpe = daily_pnl.mean() / daily_pnl.std() * np.sqrt(252)
    max_dd = (cum_pnl - cum_pnl.cummax()).min()
    total_bp = cum_pnl.iloc[-1]
    ann_ret = daily_pnl.mean() * 252
    calmar = ann_ret / abs(max_dd) if max_dd != 0 else 0
    hit_rate = total_winners / total_trades if total_trades > 0 else 0
    avg_hold = total_hold_days / total_trades if total_trades > 0 else 0

    return {
        "tenors": "+".join(tenors),
        "z_window": z_window,
        "z_entry": z_entry,
        "z_exit": z_exit,
        "sharpe": round(sharpe, 3),
        "total_bp": round(total_bp, 1),
        "ann_ret_bp": round(ann_ret, 1),
        "max_dd_bp": round(max_dd, 1),
        "calmar": round(calmar, 3),
        "n_trades": total_trades,
        "hit_rate": round(hit_rate, 3),
        "avg_hold_d": round(avg_hold, 0),
        "daily_vol_bp": round(daily_pnl.std(), 3),
        "tenor_detail": tenor_results,
    }


# ── Parameter grid ─────────────────────────────────────────────────────
Z_WINDOWS = [30, 45, 60, 90, 120]
Z_ENTRIES = [1.0, 1.25, 1.5, 1.75, 2.0, 2.5]
Z_EXITS = [-0.5, 0.0, 0.5]

TENOR_COMBOS = [
    ["2Y"],
    ["5Y"],
    ["10Y"],
    ["30Y"],
    ["2Y", "5Y"],
    ["2Y", "10Y"],
    ["5Y", "10Y"],
    ["10Y", "30Y"],
    ["2Y", "5Y", "10Y"],
    ["5Y", "10Y", "30Y"],
    ["2Y", "5Y", "10Y", "30Y"],
    ["2Y", "3Y", "5Y", "7Y", "10Y", "30Y"],
]

n_combos = len(Z_WINDOWS) * len(Z_ENTRIES) * len(Z_EXITS) * len(TENOR_COMBOS)
print(f"\nGrid: {len(Z_WINDOWS)} windows × {len(Z_ENTRIES)} entries × {len(Z_EXITS)} exits × {len(TENOR_COMBOS)} tenor combos = {n_combos} configs", flush=True)

# ── Run grid search ────────────────────────────────────────────────────
t0 = time.time()
results = []

for tenors in TENOR_COMBOS:
    for zw in Z_WINDOWS:
        for ze in Z_ENTRIES:
            for zx in Z_EXITS:
                r = run_single_config(h, tenors, zw, ze, zx)
                if r is not None:
                    results.append(r)

elapsed = time.time() - t0
print(f"Completed {len(results)}/{n_combos} valid configs in {elapsed:.1f}s", flush=True)

df = pd.DataFrame(results)
df_no_detail = df.drop(columns=["tenor_detail"])

# ── Top configs by Sharpe ──────────────────────────────────────────────
print(f"\n{'='*90}")
print(f"  TOP 20 CONFIGS BY SHARPE RATIO")
print(f"{'='*90}")
top = df_no_detail.sort_values("sharpe", ascending=False).head(20)
print(top.to_string(index=False))

# ── Top configs by Calmar ──────────────────────────────────────────────
print(f"\n{'='*90}")
print(f"  TOP 20 CONFIGS BY CALMAR RATIO")
print(f"{'='*90}")
top_c = df_no_detail.sort_values("calmar", ascending=False).head(20)
print(top_c.to_string(index=False))

# ── Best per tenor combo ───────────────────────────────────────────────
print(f"\n{'='*90}")
print(f"  BEST SHARPE PER TENOR COMBINATION")
print(f"{'='*90}")
best_per = df_no_detail.loc[df_no_detail.groupby("tenors")["sharpe"].idxmax()]
best_per = best_per.sort_values("sharpe", ascending=False)
print(best_per.to_string(index=False))

# ── Sensitivity: fix best tenor combo, vary params ─────────────────────
best_row = df_no_detail.sort_values("sharpe", ascending=False).iloc[0]
best_tenors = best_row["tenors"]
print(f"\n{'='*90}")
print(f"  PARAMETER SENSITIVITY — best tenor combo: {best_tenors}")
print(f"{'='*90}")

mask = df_no_detail["tenors"] == best_tenors
sub = df_no_detail[mask].copy()

print(f"\n  By z_window (median Sharpe):")
for w in Z_WINDOWS:
    s = sub[sub["z_window"] == w]["sharpe"]
    print(f"    {w:>3d}d: median={s.median():.3f}  mean={s.mean():.3f}  n={len(s)}")

print(f"\n  By z_entry (median Sharpe):")
for e in Z_ENTRIES:
    s = sub[sub["z_entry"] == e]["sharpe"]
    print(f"    {e:.2f}: median={s.median():.3f}  mean={s.mean():.3f}  n={len(s)}")

print(f"\n  By z_exit (median Sharpe):")
for x in Z_EXITS:
    s = sub[sub["z_exit"] == x]["sharpe"]
    print(f"    {x:+.1f}: median={s.median():.3f}  mean={s.mean():.3f}  n={len(s)}")

# ── Distribution stats ─────────────────────────────────────────────────
print(f"\n{'='*90}")
print(f"  OVERALL DISTRIBUTION")
print(f"{'='*90}")
print(f"  Sharpe:  mean={df['sharpe'].mean():.3f}  median={df['sharpe'].median():.3f}  >0: {(df['sharpe']>0).mean():.0%}")
print(f"  Total configs with Sharpe > 0.3: {(df['sharpe']>0.3).sum()}")
print(f"  Total configs with Sharpe > 0.5: {(df['sharpe']>0.5).sum()}")
print(f"  Total configs with Sharpe > 0.7: {(df['sharpe']>0.7).sum()}")
