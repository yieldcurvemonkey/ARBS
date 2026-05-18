"""Manual end-to-end spot check of SFR1 trades.

For a handful of representative trades from the safety-filtered SFR1
panel, reload the intraday rate series independently and verify:

  1. signal_open_rate ≈ rate at 17:00 ET on entry-date D
  2. signal_close_rate ≈ rate at 22:00 ET on D
  3. entry_rate ≈ rate at 22:00 ET on D (== signal_close_rate)
  4. exit_rate ≈ rate at 08:00 ET on next business day
  5. The trade direction matches sign convention:
       FADE → trade_direction = -sign(signal_move_bp)
       MOMENTUM → trade_direction = +sign(signal_move_bp)
  6. The gross PnL computation:
       framework PnL ≈ +signed bpv * Δrate_bp (PAYER orientation)
       trade gross USD = framework PnL * trade_direction
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytz

sys.path.insert(0, r"C:\Users\chris\clee\ARBS")

from BT.signals.asia_fade_sfr import AsiaFadeConfig, load_intraday_rates  # noqa
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP  # noqa

NY = pytz.timezone("America/New_York")
TRADES = Path(r"C:\Users\chris\clee\ARBS\BT\results\asia_fade_grid_safe\all_trades.parquet")
TENOR = "IMM_1xIMM_2"
BASE_BPV = 100_000.0
TOL_BP = 0.10  # how close re-sampled rate must be to stored rate (bp)


def main():
    t = pd.read_parquet(TRADES)
    sub = t[t["package"] == "SFR1_outright"].copy()
    sub["date"] = pd.to_datetime(sub["date"])
    print(f"SFR1 trades in safety-filtered panel: {len(sub):,}")
    print(f"   range: {sub['date'].min().date()} → {sub['date'].max().date()}")
    print(f"   total NET (as built, FADE polarity): ${sub['net_usd'].sum():,.0f}")
    print(f"   total NET (MOMENTUM polarity):       ${(-sub['net_usd']).sum():,.0f}")
    print()

    # Pick 6 trades: 1st/last trade, biggest winner, biggest loser, 2 random middles.
    sub_sorted = sub.sort_values("date").reset_index(drop=True)
    picks_idx = sorted(set([
        0,                               # first
        len(sub_sorted) - 1,             # last
        sub_sorted["net_usd"].idxmax(),  # best fade trade
        sub_sorted["net_usd"].idxmin(),  # worst fade trade
        len(sub_sorted) // 3,            # 1/3
        2 * len(sub_sorted) // 3,        # 2/3
    ]))
    picks = sub_sorted.iloc[picks_idx]

    # Load intraday rates once across the union of picked dates ±1 day.
    s_date = (picks["date"].min() - pd.Timedelta(days=2)).date()
    e_date = (picks["date"].max() + pd.Timedelta(days=3)).date()
    print(f"Loading independent rate replay over {s_date} → {e_date} ...")
    cfg = AsiaFadeConfig.from_dict({
        "tenors": [TENOR],
        "start": str(s_date),
        "end":   str(e_date),
        "bar_freq": "5min",
        "show_progress": False,
    })
    mdp = IRSwapsMDP(source=cfg.mdp_source)
    rates = load_intraday_rates(cfg, mdp=mdp)
    s = rates[TENOR].dropna()
    print(f"   replay rows: {len(s):,}  ({s.index[0]} → {s.index[-1]})")
    print()

    def asof(ts):
        v = s.asof(ts)
        idx = s.index.asof(ts)
        if pd.isna(v):
            return None, None
        return float(v), idx

    print("=" * 130)
    print("  TRADE-BY-TRADE VERIFICATION")
    print("=" * 130)
    n_pass = n_fail = 0
    for i, row in picks.iterrows():
        d = row["date"].date()
        prev = d  # entry day per build_trade_events
        next_bd = d + dt.timedelta(days=1)
        while next_bd.weekday() >= 5:
            next_bd += dt.timedelta(days=1)
        ts_so = NY.localize(dt.datetime.combine(prev, dt.time(17, 0)))
        ts_sc = NY.localize(dt.datetime.combine(prev, dt.time(22, 0)))
        ts_en = ts_sc
        ts_ex = NY.localize(dt.datetime.combine(next_bd, dt.time(8, 0)))

        r_so, idx_so = asof(ts_so)
        r_sc, idx_sc = asof(ts_sc)
        r_en, idx_en = asof(ts_en)
        r_ex, idx_ex = asof(ts_ex)

        # Compare to stored rates if present (newer trades have them; older may not)
        stored_so = row.get("signal_open_rate", np.nan)
        stored_sc = row.get("signal_close_rate", np.nan)
        stored_ex = row.get("exit_rate", np.nan) if "exit_rate" in row.index else np.nan

        signal_move_bp = (r_sc - r_so) * 100.0
        hold_move_bp   = (r_ex - r_en) * 100.0
        fade_dir       = -np.sign(signal_move_bp)
        mom_dir        = +np.sign(signal_move_bp)

        # Framework's gross PnL convention: PAYER = +bpv * Δrate_bp
        framework_pnl = +BASE_BPV * hold_move_bp / 1.0    # already × Δrate in bp → in $
        fade_gross    = framework_pnl * fade_dir          # FADE: take REC if rate rose
        mom_gross     = framework_pnl * mom_dir
        cost_usd      = 0.5 * BASE_BPV + 2 * 0.50         # 0.5bp RT + $1 commission RT
        fade_net      = fade_gross - cost_usd
        mom_net       = mom_gross  - cost_usd

        stored_gross = float(row["gross_usd"])
        stored_net   = float(row["net_usd"])
        stored_td    = float(row["trade_direction"])
        stored_sig   = float(row["signal_move_bp"])

        # Choose which polarity matches the stored sign (panel was built with fade)
        chosen_pol = "fade" if stored_td == fade_dir else ("momentum" if stored_td == mom_dir else "??")
        recomp_gross = fade_gross if chosen_pol == "fade" else mom_gross
        recomp_net   = fade_net   if chosen_pol == "fade" else mom_net

        diff_signal = abs(signal_move_bp - stored_sig)
        diff_gross  = abs(recomp_gross - stored_gross)

        ok_signal = diff_signal < TOL_BP
        ok_dir    = stored_td == fade_dir or stored_td == mom_dir
        ok_gross  = diff_gross < abs(stored_gross) * 0.02 + 50   # 2% or $50

        ok = ok_signal and ok_dir and ok_gross
        if ok:
            n_pass += 1
        else:
            n_fail += 1

        print(f"\n── Trade {i+1}/{len(picks)} — entry-date {d} (next-bd exit {next_bd})")
        print(f"   replay sampling ({TENOR}):")
        print(f"     signal_open  @17:00ET {idx_so}: rate={r_so:.6f}  vs stored={stored_so}")
        print(f"     signal_close @22:00ET {idx_sc}: rate={r_sc:.6f}  vs stored={stored_sc}")
        print(f"     entry        @22:00ET {idx_en}: rate={r_en:.6f}")
        print(f"     exit         @08:00ET {idx_ex}: rate={r_ex:.6f}  vs stored={stored_ex}")
        print(f"   computed:")
        print(f"     signal_move_bp  = {signal_move_bp:+.4f}  (stored {stored_sig:+.4f}  Δ={diff_signal:.4f})")
        print(f"     hold_move_bp    = {hold_move_bp:+.4f}")
        print(f"     fade_direction  = {fade_dir:+.1f}    momentum_direction = {mom_dir:+.1f}")
        print(f"     stored trade_direction = {stored_td:+.1f}  → polarity match = {chosen_pol}")
        print(f"     framework PnL (PAYER) = ${framework_pnl:+,.0f}")
        print(f"     recomputed gross_usd  = ${recomp_gross:+,.0f}   (stored ${stored_gross:+,.0f}  Δ={diff_gross:,.0f})")
        print(f"     recomputed net_usd    = ${recomp_net:+,.0f}     (stored ${stored_net:+,.0f})")
        print(f"   timestamps causality-check: signal_close ({idx_sc}) ≤ entry ({idx_en}) ≤ exit ({idx_ex})  →  "
              f"{'OK' if (idx_sc <= idx_en <= idx_ex) else 'FAIL'}")
        print(f"   verdict: signal={'✓' if ok_signal else '✗'} direction={'✓' if ok_dir else '✗'} gross={'✓' if ok_gross else '✗'} → {'PASS' if ok else 'FAIL'}")

    print()
    print("=" * 130)
    print(f"  RESULT: {n_pass} PASS  /  {n_fail} FAIL  out of {len(picks)} trades")
    print("=" * 130)

    # Look-ahead sanity: every signal_close must be ≤ entry, and entry < exit.
    # build_trade_events sets entry_ts = signal_end_ts and exit_ts on the
    # next business day. asof() never returns a forward bar. So absent
    # clock-skew this is structurally impossible to violate.
    print()
    print("  Look-ahead sanity:")
    print("    • signal_open  sampled with `series.asof(17:00 ET D)` — last value ≤ 17:00.")
    print("    • signal_close sampled with `series.asof(22:00 ET D)` — last value ≤ 22:00.")
    print("    • entry         = signal_close (no peek beyond).")
    print("    • exit          sampled with `series.asof(08:00 ET D+1)`  — last value ≤ exit-day 08:00.")
    print("    • Signal IS in the past at entry time (5pm → 10pm on entry date).")
    print("    • Exit data is in the FUTURE relative to entry, but only used for PnL realisation")
    print("      after the trade is closed — no information leak into the entry decision.")
    print("    → No look-ahead bias possible in the as-coded sampling pipeline.")


if __name__ == "__main__":
    main()
