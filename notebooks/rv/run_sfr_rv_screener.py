"""Run the SFRCalSpreadRV screener and output results.

Usage: python run_sfr_rv_screener.py
Must be run from the repo root with the arbs conda env.
"""
import sys
import os

# Use the main repo for imports (worktree __init__.py has issues with some optional deps)
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO_ROOT)

# Direct import of our module (avoid __init__.py chain)
import importlib.util
_mod_path = os.path.join(REPO_ROOT, "BT", "signals", "sfr_cal_spread_rv.py")
_spec = importlib.util.spec_from_file_location("sfr_cal_spread_rv", _mod_path)
rv = importlib.util.module_from_spec(_spec)
rv.__name__ = "sfr_cal_spread_rv"
rv.__package__ = "BT.signals"
# Register it so internal relative imports work
sys.modules["sfr_cal_spread_rv"] = rv
sys.modules["BT.signals.sfr_cal_spread_rv"] = rv
_spec.loader.exec_module(rv)

import datetime
import numpy as np
import pandas as pd
import pytz

NYC = pytz.timezone("America/New_York")


def main():
    config = rv.SFRCalSpreadRVConfig(
        n_contracts=12,
        zscore_window=40,
        vol_window=20,
    )

    print("=" * 70)
    print("SFRCalSpreadRV -- SOFR Futures Calendar Spread RV Screener")
    print("=" * 70)
    print()

    # Load rate panel
    print("Loading rate panel from BARCHART_STIRF-RL (Q12 SOFR)...")
    start = NYC.localize(datetime.datetime(2024, 6, 1, 18, 0))
    end = "live"

    rates = rv.load_rate_panel(config, start=start, end=end)
    print(f"  {rates.shape[0]} dates x {rates.shape[1]} contracts")
    print(f"  Ladder: {list(rates.columns)}")
    print(f"  Range: {rates.index[0]} -> {rates.index[-1]}")
    print()

    print("Latest implied rates (%):")
    print(rates.iloc[-1].round(4).to_string())
    print()

    # Build snapshot
    print("Building full screener snapshot...")
    snap = rv.build_snapshot(config, rates_panel=rates)
    print()

    # Print each structure type
    for st, data in snap.structures.items():
        if not data.labels:
            continue
        label = rv.STRUCTURE_LABELS[st]
        print(f"{'=' * 50}")
        print(f"  {label}")
        print(f"{'=' * 50}")
        df = data.to_dataframe()
        print(df.to_string())
        s = data.summary()
        if "peak" in s and "trough" in s:
            print(f"  Peak: {s['peak']['label']} = {s['peak']['value']:+.1f} bp")
            print(f"  Trough: {s['trough']['label']} = {s['trough']['value']:+.1f} bp")
        if "max_chg" in s and "min_chg" in s:
            print(f"  Max Chg: {s['max_chg']['label']} = {s['max_chg']['value']:+.1f} bp")
            print(f"  Min Chg: {s['min_chg']['label']} = {s['min_chg']['value']:+.1f} bp")
        print()

    # ---- U26 3M Fly Deep Dive ----
    print("=" * 70)
    print("U26 3M FLY DEEP DIVE: M26/U26/Z26")
    print("(Our STIR trader's conviction trade)")
    print("=" * 70)

    ladder = list(rates.columns)
    front, belly, back = "M26", "U26", "Z26"
    if not all(c in ladder for c in [front, belly, back]):
        # Fall back to first available 3M fly
        front, belly, back = ladder[0], ladder[1], ladder[2]
        print(f"  M26/U26/Z26 not in ladder. Using fallback: {front}/{belly}/{back}")

    u6 = rv.analyze_specific_fly(rates, front, belly, back, config)
    print(f"  Trade:          {u6['trade']}")
    print(f"  Level:          {u6['level_bp']:+.2f} bp")
    print(f"  Prev Close:     {u6['prev_close_bp']:+.2f} bp")
    print(f"  1d Change:      {u6['change_bp']:+.2f} bp")
    print(f"  Z-Score:        {u6['zscore']}")
    print(f"  Vol (ann):      {u6['vol_ann']} bp")
    print(f"  Roll/Carry:     {u6['roll_bp']} bp per quarter")
    print(f"  Risk-Adj Roll:  {u6['risk_adj_roll']}")
    print(f"  60d Mean:       {u6['mean_60d']} bp")
    print(f"  60d Std:        {u6['std_60d']} bp")
    print()

    # Conviction assessment
    zs = u6["zscore"]
    roll = u6["roll_bp"]
    radj = u6["risk_adj_roll"]

    print("CONVICTION SIGNALS:")
    if zs is not None:
        if abs(zs) > 2:
            print(f"  * STRONG: Z-score = {zs:+.2f} (extreme)")
        elif abs(zs) > 1:
            print(f"  * MODERATE: Z-score = {zs:+.2f} (elevated)")
        else:
            print(f"  * NEUTRAL: Z-score = {zs:+.2f} (within range)")

    if roll is not None:
        if roll > 0:
            print(f"  * POSITIVE CARRY: Roll = {roll:+.2f} bp/qtr (long belly earns carry)")
        else:
            print(f"  * NEGATIVE CARRY: Roll = {roll:+.2f} bp/qtr (short belly earns carry)")

    if radj is not None:
        if abs(radj) > 1:
            print(f"  * ATTRACTIVE risk-adj roll = {radj:+.2f}")
        else:
            print(f"  * MODERATE risk-adj roll = {radj:+.2f}")

    if zs is not None and roll is not None:
        print()
        if zs < -1.5 and roll > 0:
            print("  VERDICT: BUY the fly -- cheap on z-score + positive carry")
        elif zs > 1.5 and roll < 0:
            print("  VERDICT: SELL the fly -- rich on z-score + negative carry")
        elif abs(zs) < 0.5:
            print("  VERDICT: HOLD / MONITOR -- near fair value")
        else:
            direction = "BUY" if zs < 0 else "SELL"
            carry_align = "aligned" if (zs < 0 and roll > 0) or (zs > 0 and roll < 0) else "opposed"
            print(f"  VERDICT: Lean {direction} -- carry {carry_align}")

    # ---- Top Trades ----
    print()
    print("=" * 70)
    print("TOP TRADES BY RISK-ADJUSTED ROLL")
    print("=" * 70)

    rows = []
    for st, data in snap.structures.items():
        if st == rv.StructureType.STRIP or not data.labels:
            continue
        for i, label in enumerate(data.labels):
            r = data.risk_adj_rolls[i]
            if not np.isnan(r):
                rows.append({
                    "Structure": rv.STRUCTURE_LABELS[st],
                    "Label": label,
                    "Level": round(data.levels[i], 2),
                    "Z-Score": round(data.zscores[i], 2) if not np.isnan(data.zscores[i]) else None,
                    "Roll": round(data.rolls[i], 2) if not np.isnan(data.rolls[i]) else None,
                    "RiskAdj": round(r, 2),
                })

    sdf = pd.DataFrame(rows)
    if sdf.empty:
        print("\n  No trades with valid risk-adj roll (insufficient history for vol/zscore)")
    else:
        print("\nTOP 5 LONG CANDIDATES (positive risk-adj roll):")
        top = sdf.dropna(subset=["RiskAdj"])
        if not top.empty:
            print(top.nlargest(5, "RiskAdj").to_string(index=False))
        print("\nTOP 5 SHORT CANDIDATES (negative risk-adj roll):")
        if not top.empty:
            print(top.nsmallest(5, "RiskAdj").to_string(index=False))
        print("\nMOST EXTREME Z-SCORES:")
        zs_valid = sdf.dropna(subset=["Z-Score"])
        if not zs_valid.empty:
            zs_valid = zs_valid.copy()
            zs_valid["AbsZ"] = zs_valid["Z-Score"].abs()
            print(zs_valid.nlargest(5, "AbsZ").drop(columns=["AbsZ"]).to_string(index=False))

    # ---- Carry Table (Barnes Style) ----
    print()
    print("=" * 70)
    print("3M MICROFLY CARRY TABLE (Barnes Style)")
    print("Positive carry = earn if long belly (buy the fly)")
    print("=" * 70)

    if rv.StructureType.FLY_3M in snap.structures:
        fly3m = snap.structures[rv.StructureType.FLY_3M]
        for i, label in enumerate(fly3m.labels):
            lvl = fly3m.levels[i]
            target = fly3m.labels[i - 1] if i > 0 else "--"
            target_lvl = f"{fly3m.levels[i - 1]:+.1f}" if i > 0 and not np.isnan(fly3m.levels[i - 1]) else "--"
            carry = f"{fly3m.rolls[i]:+.1f}" if not np.isnan(fly3m.rolls[i]) else "--"
            direction = ""
            if not np.isnan(fly3m.rolls[i]):
                direction = "BUY belly" if fly3m.rolls[i] > 0 else "SELL belly"
            print(f"  {label:30s}  Level={lvl:+6.1f}  Rolls->{target:30s}={target_lvl:>6s}  Carry={carry:>6s}  {direction}")


if __name__ == "__main__":
    main()
