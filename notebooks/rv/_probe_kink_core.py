"""Probe: does the meeting residual differ from the raw fly, and does it pay?

Runs the decisive blocks before the notebook is written, so the notebook is
built around whatever the answer turns out to be rather than the other way
round.
"""
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "notebooks" / "backtests"))

import numpy as np
import pandas as pd

pd.set_option("display.width", 240, "display.max_columns", 60)

import sfr_kink_fade_common as K
from RVUtils.MeanRev import MRConfig, run_backtest
from RVUtils.MeanRev.signals import (
    meeting_residual_signal, scale_only_zscore, zscore_signal,
)
from RVUtils.MeanRev.meetings import meeting_residual_panel
from RVUtils.MeanRev.signals import structure_signal_from_slots

t0 = time.time()
lab = K.load_kink_lab("3m", "liquid16", lam=10.0)
levels, st, regimes = lab["levels"], lab["struct"], lab["regimes"]
print(f"loaded in {time.time() - t0:.1f}s  {levels.shape}", flush=True)

cm = st.drop_duplicates("key").set_index("key")["cm_label_short"]
cm_slot = st.drop_duplicates("key").set_index("key")["cm_slot"]

# ---------------------------------------------------------------- lam sweep
print("\n=== residual fly sd (bp) by lam, per CM slot ===", flush=True)
c = lab["contracts"]
rows = []
for lam in (1.0, 10.0, 100.0, 1000.0, 1e5):
    r = meeting_residual_panel(c, lam=lam, max_slot=16)
    sig = structure_signal_from_slots(r, st, scale=1.0)
    sig = sig.reindex(index=levels.index, columns=levels.columns)
    corr = pd.Series({k: levels[k].corr(sig[k]) for k in levels.columns})
    rows.append({"lam": lam, "resid_fly_sd": float(sig.stack().std()),
                 "raw_fly_sd": float(levels.stack().std()),
                 "median_corr_with_raw": float(corr.median()),
                 "r2_vs_raw": float(1 - (levels - sig).stack().var()
                                    / levels.stack().var())})
print(pd.DataFrame(rows).round(3).to_string(index=False), flush=True)

LAM = 100.0
resid = meeting_residual_panel(c, lam=LAM, max_slot=16)
mres = structure_signal_from_slots(resid, st, scale=1.0).reindex(
    index=levels.index, columns=levels.columns)
explained = levels - mres

print(f"\n=== variance decomposition at lam={LAM} (per CM slot) ===", flush=True)
vd = K.variance_decomposition(levels, explained, groups=cm)
vd["cm_slot"] = vd["group"].map(
    st.drop_duplicates("cm_label_short").set_index("cm_label_short")["cm_slot"])
print(vd.sort_values("cm_slot").round(3).to_string(index=False), flush=True)

print("\n=== variance decomposition by regime (pooled) ===", flush=True)
for reg in ("HIKING", "PLATEAU", "CUTTING"):
    m = regimes.reindex(levels.index) == reg
    if m.sum() < 30:
        continue
    d = K.variance_decomposition(levels[m.to_numpy()], explained[m.to_numpy()])
    if not d.empty:
        r = d.iloc[0]
        print(f"  {reg:8s} n={int(r['n']):6d}  sd_fly={r['sd_actual_bp']:6.2f}  "
              f"sd_calendar_model={r['sd_model_bp']:6.2f}  "
              f"sd_resid={r['sd_resid_bp']:6.2f}  r2={r['r2']:+.3f}", flush=True)

# ---------------------------------------------------------------- pond test
tilt_lvl = lab["tilted"]["level"].reindex(index=levels.index,
                                          columns=levels.columns)
sigs = {
    "K0 raw z": zscore_signal(levels, window=120),
    "K1 meeting resid (scale)": scale_only_zscore(mres, window=120),
    "K1z meeting resid (z)": zscore_signal(mres, window=120),
    "K2 calendar-tilted fly z": zscore_signal(tilt_lvl, window=120),
}
print("\n=== POND TEST ===", flush=True)
t = K.selectivity_table(levels, sigs, entry_z=2.0, gate=lab["gate"],
                        horizons=(5, 10, 21), round_trip_bp=2.0)
print(t.round(3).to_string(index=False), flush=True)

# ------------------------------------------------------------- quick backtest
print("\n=== quick backtest, matched config (fade, z2, t10, hold 30) ===",
      flush=True)
base = MRConfig(lag=1, round_trip_cost_bp=2.0, max_hold=30, n_packages=100,
                entry_z=2.0, exit_style="t10", direction="fade")
for name, s in sigs.items():
    res = run_backtest(base, levels=levels, signal=s, gate=lab["gate"])
    m = res.metrics
    if m["n_trades"] == 0:
        print(f"  {name:28s} no trades", flush=True)
        continue
    gross = m["total_gross_bp"] / m["n_trades"]
    print(f"  {name:28s} n={m['n_trades']:4d}  gross/trade {gross:+.3f}bp  "
          f"net {m['total_net_bp']:+8.1f}bp  hit {m['hit_rate']:.0%}  "
          f"SR {m['sharpe']:+.2f}", flush=True)

print("\n=== front slots only (cm_slot <= 5) ===", flush=True)
front_keys = [k for k in levels.columns if cm_slot.get(k, 99) <= 5]
for name, s in sigs.items():
    res = run_backtest(MRConfig(lag=1, round_trip_cost_bp=2.0, max_hold=30,
                                n_packages=100, entry_z=2.0, exit_style="t10",
                                direction="fade", keys=front_keys),
                       levels=levels, signal=s, gate=lab["gate"])
    m = res.metrics
    if m["n_trades"] == 0:
        print(f"  {name:28s} no trades", flush=True)
        continue
    print(f"  {name:28s} n={m['n_trades']:4d}  "
          f"gross/trade {m['total_gross_bp'] / m['n_trades']:+.3f}bp  "
          f"net {m['total_net_bp']:+8.1f}bp  hit {m['hit_rate']:.0%}", flush=True)

print(f"\nDONE in {time.time() - t0:.0f}s", flush=True)
