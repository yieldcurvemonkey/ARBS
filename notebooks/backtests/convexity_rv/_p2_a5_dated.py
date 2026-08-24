r"""GV amendment A5 — the dated, hold-through-the-roll package, on the ENGINE.

**Declared 2026-08-24, before scoring, as an amendment to
``docs/convexityrv/gv-preregistration.md``.  6 cells, trial total 298 -> 304.**

Why this exists.  The block's own measurement says the residual the brief wants
to trade reverts with a half-life of **68-99 business days** on the long-end
curve pairs, against a tradeable segment of only ~56 bd between roll blackouts;
1,738 of the main grid's 2,591 episodes exited at ``segment_end`` rather than on
the signal.  **The trade cannot converge inside a roll-flat window.**

But "flat across the roll" was only ever a proxy for the real requirement: *do
not book a contract-switching jump as P&L*.  A **dated** package -- fixed SR3
contracts, a fixed matched swap, an IMM-pinned fly, all resolved at entry --
has no label to switch, so it can be held straight through a roll and the jump
simply does not exist for it.  What it has instead is the CA's own theta,
which the engine prices because it prices real ageing instruments.

Two things are therefore different here, and both are necessary:

* **Signal on the roll-SPLICED series** (``gv_sizing.roll_spliced``, forward-
  adjusted so it stays causal).  The raw constant-rank series jumps at each
  roll and a z-rule reads that jump as a move.
* **P&L on the ENGINE only.**  A constant-rank panel cannot represent a dated
  hold, and the certification already measured that the par-rate panel
  overstates these books (panel Sharpe 2.141 / 0.867 / 0.414 against engine
  1.409 / 0.151 / 0.131) because it prices par-rate changes rather than struck-
  instrument P&L and the omitted term is carry.  Quoting a panel number for a
  through-roll hold would compound both errors.

Output: notebooks/data/convexity_rv/p2_a5_*.parquet + printed report.
"""
from __future__ import annotations

import json
import math
import os
import pathlib
import sys
import time

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
REPO = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.stdout.reconfigure(line_buffering=True)
pd.set_option("display.width", 240)
pd.set_option("display.max_columns", 60)

from RVUtils.ConvexityRV import gv_engine as GE  # noqa: E402
from RVUtils.ConvexityRV import gv_grid as GG  # noqa: E402
from RVUtils.ConvexityRV import gv_signals as GS  # noqa: E402
from RVUtils.ConvexityRV import gv_sizing as S  # noqa: E402
from RVUtils.ConvexityRV import gv_universe as U  # noqa: E402

DATA = REPO / "notebooks" / "data" / "convexity_rv"
CA = pd.read_parquet(DATA / "cavf_ca_panel.parquet")
LEGS = pd.read_parquet(DATA / "p2_legs.parquet")
LEGS.index = pd.to_datetime(LEGS.index)
IDX = CA.index.intersection(LEGS.index)
CA, LEGS = CA.loc[IDX], LEGS.loc[IDX]
SPAN_Y = (IDX[-1] - IDX[0]).days / 365.25
ALL = list(U.PRIMARY_STRUCTURES) + list(U.SECONDARY_STRUCTURES)
HL = S.fit_denoise_halflives(CA, [U.ca_col(l) for l in ALL])["halflife_bd"].to_dict()
ROLLS = U.ca_roll_dates(IDX)
CA_DV01 = U.CA_DV01_DEFAULT

A5_STRUCTS = list(U.PRIMARY_STRUCTURES)
A5_LEGS = ("immM_2s5s10s", "le_10y10y_15y10y")
MAX_HOLD = 126                    # two quarters: long enough for a 68-99 bd half-life


def sec(t: str) -> None:
    print(f"\n{'=' * 80}\n{t}\n{'=' * 80}")


def sharpe(d: pd.Series) -> float:
    d = pd.Series(d).astype(float)
    if len(d[d != 0]) < 10 or d.std(ddof=1) == 0:
        return float("nan")
    return float(d.mean() / d.std(ddof=1) * math.sqrt(252.0))


# ---------------------------------------------------------------------------
sec("0. The spliced series -- what a dated position's level actually does")
# ---------------------------------------------------------------------------
rows = []
for lab in A5_STRUCTS:
    raw = CA[U.ca_col(lab)].dropna()
    sp = S.roll_spliced(raw, ROLLS)
    nv = LEGS[GG.vol_bench_col(lab)].astype(float).reindex(raw.index)
    t1m = U.mean_t1_series(raw.index, lab)
    theta_y = S.ca_theta_bp_per_year(nv, t1m)
    rows.append({"structure": lab,
                 "raw_first": raw.iloc[0], "raw_last": raw.iloc[-1],
                 "spliced_first": sp.iloc[0], "spliced_last": sp.iloc[-1],
                 "spliced_drift_bp": sp.iloc[-1] - sp.iloc[0],
                 "theta_total_bp": float(theta_y.mean() * SPAN_Y),
                 "n_rolls": len(ROLLS)})
sd = pd.DataFrame(rows).set_index("structure")
print(sd.round(3).to_string())
print("\nread: the spliced series is the level path of a position nobody rolls. "
      "Its drift is the CA's theta, and it should sit near `theta_total_bp` -- "
      "the constant-rank series hides that drift by resetting at every roll.")

# ---------------------------------------------------------------------------
sec("1. Building the A5 episodes on the spliced signal, no blackout")
# ---------------------------------------------------------------------------
cfg = GS.SignalConfig(z_entry=2.0, z_exit=0.5, max_hold_bd=MAX_HOLD, window=252)
whole = [(IDX[0], IDX[-1])]
level = LEGS[GG.LEVEL_COL].astype(float)
slope = (LEGS[GG.SLOPE_COLS[1]].astype(float)
         - LEGS[GG.SLOPE_COLS[0]].astype(float)) * 100.0

plans = {}
for st_ in A5_STRUCTS:
    raw = CA[U.ca_col(st_)].dropna()
    spl = S.roll_spliced(raw, ROLLS)
    spl_dn = S.denoise(spl, HL[U.ca_col(st_)])
    nv = LEGS[GG.vol_bench_col(st_)].astype(float).reindex(raw.index)
    w = U.time_weight_series(raw.index, st_)
    for leg_id in A5_LEGS:
        leg = U.leg_series(LEGS, leg_id, st_).reindex(raw.index)
        inp = S.SizingInputs(ca=spl, ca_denoised=spl_dn, leg=leg, nvol=nv, w=w,
                             level=level.reindex(raw.index),
                             slope=slope.reindex(raw.index))
        b, gate = S.sizing_beta("beta_lvl", inp)
        f = GS.build_signal_frame(spl, spl_dn, leg, b, gate, cfg=cfg)
        eps = GS.episodes_from_signals(f, cfg, whole, ca_dv01=CA_DV01)
        cross = sum(1 for e in eps
                    if any(e.entry < r <= e.exit for r in ROLLS))
        plans[(st_, leg_id)] = eps
        print(f"  {st_:7s} {leg_id:18s} {len(eps):3d} episodes, "
              f"{cross} crossing a roll, mean hold "
              f"{np.mean([np.busday_count(e.entry.date(), e.exit.date()) for e in eps]):.0f} bd"
              if eps else f"  {st_:7s} {leg_id:18s} 0 episodes")

# ---------------------------------------------------------------------------
sec("2. ENGINE P&L of the dated, through-roll package")
# ---------------------------------------------------------------------------
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP  # noqa: E402
from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP  # noqa: E402

fut_mdp = STIRFutureMDP(source="BARCHART_STIRF-RL")
swp_mdp = IRSwapsMDP(source="citivelo_excel_rl")

rows = []
for (st_, leg_id), eps in plans.items():
    if not eps:
        continue
    specs = [GE.spec_from_episode(structure=st_, leg_id=leg_id, side=e.side,
                                  entry=e.entry.date(), exit=e.exit.date(),
                                  beta_entry=e.beta_entry, ca_dv01=e.ca_dv01)
             for e in eps]
    lo, hi = min(s.entry for s in specs), max(s.exit for s in specs)
    days = [d for d in IDX if lo <= d.date() <= hi]
    t0 = time.time()
    try:
        bt = GE.run_backtest(specs, days, futures_mdp=fut_mdp, swaps_mdp=swp_mdp)
        eq = GE.assert_ran(bt, specs)
    except Exception as exc:                                    # noqa: BLE001
        print(f"  {st_} x {leg_id}: ENGINE {type(exc).__name__}: {exc}")
        rows.append({"structure": st_, "leg_id": leg_id, "n_ep": len(eps),
                     "status": f"{type(exc).__name__}"})
        continue
    d = eq.diff().fillna(0.0)
    # the SPLICED panel, as the closest panel analogue (the label jump removed)
    spl = S.roll_spliced(CA[U.ca_col(st_)].dropna(), ROLLS)
    leg = U.leg_series(LEGS, leg_id, st_).reindex(spl.index)
    pan = GS.book_daily(eps, spl, leg, leg_id=leg_id,
                        index=pd.DatetimeIndex(days), cost_mult=0.0)
    j = pd.concat([d.rename("e"), pan.rename("p")], axis=1).dropna()
    rows.append({
        "structure": st_, "leg_id": leg_id, "n_ep": len(eps), "status": "ok",
        "n_cross_roll": sum(1 for e in eps
                            if any(e.entry < r <= e.exit for r in ROLLS)),
        "engine_net": float(j["e"].sum()), "engine_sharpe": sharpe(j["e"]),
        "panel_spliced_net": float(j["p"].sum()),
        "panel_spliced_sharpe": sharpe(j["p"]),
        "corr": float(j["e"].corr(j["p"])),
        "elapsed_s": round(time.time() - t0, 1)})
    print(f"  {st_:7s} {leg_id:18s} engine {rows[-1]['engine_net']:>13,.0f} "
          f"(SR {rows[-1]['engine_sharpe']:+.3f})   spliced-panel "
          f"{rows[-1]['panel_spliced_net']:>13,.0f} "
          f"(SR {rows[-1]['panel_spliced_sharpe']:+.3f})   corr "
          f"{rows[-1]['corr']:+.3f}   ({rows[-1]['elapsed_s']}s)")

a5 = pd.DataFrame(rows)
a5.to_parquet(DATA / "p2_a5_engine.parquet")

# ---------------------------------------------------------------------------
sec("3. A5 verdict inputs")
# ---------------------------------------------------------------------------
ok = a5[a5["status"] == "ok"] if "status" in a5 else a5
if len(ok):
    print(ok.round(3).to_string(index=False))
    from RVUtils.StatisticalFinance.deflated_sharpe import expected_max_sharpe
    n_tr = 304                       # 298 declared + the 6 A5 cells
    bar = expected_max_sharpe(n_tr, 1.0 / SPAN_Y)
    print(f"\nE[max SR | null, {n_tr} trials, annualised] = {bar:.4f}")
    best = ok.sort_values("engine_sharpe", ascending=False).iloc[0]
    print(f"best A5 engine Sharpe {best['engine_sharpe']:.4f} "
          f"({best['structure']} x {best['leg_id']}, {int(best['n_ep'])} episodes) "
          f"-- clears: {bool(best['engine_sharpe'] > bar)}")
    summary = {"n_cells": int(len(ok)),
               "best_engine_sharpe": float(best["engine_sharpe"]),
               "best_cell": f"{best['structure']}|{best['leg_id']}",
               "bar_ann_304": float(bar),
               "clears": bool(best["engine_sharpe"] > bar),
               "n_positive_engine": int((ok["engine_net"] > 0).sum()),
               "median_engine_sharpe": float(ok["engine_sharpe"].median())}
    (DATA / "p2_a5_summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))
else:
    print("no A5 cell ran")
