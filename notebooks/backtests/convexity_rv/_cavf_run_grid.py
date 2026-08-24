r"""CA-vs-fly block: run the pre-registered 515-cell grid on the real panels.

Inputs (all built by the two backfill scripts, all regenerable):
    cavf_ca_panel.parquet    1,409 dates x 31 labels, TB path, Q/Q, 0 failures
    cavf_fly_legs.parquet    1,407 dates x 48 leg tenors, spot + fwd starts

Outputs (gitignored, regenerable):
    cavf_grid_stats.parquet      one row per cell, the verdict numbers
    cavf_grid_returns.parquet    daily zero-cost P&L per cell (for DSR)
    cavf_grid_episodes.parquet   every episode of every cell
    cavf_fs_matrix.parquet       the forward-start hypothesis measurement
    cavf_grid_meta.json          declared trial count, null bars, panel spans,
                                 negative-CA fractions, placebo results
"""
from __future__ import annotations

import datetime as dt
import json
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

from RVUtils.ConvexityRV import cavf_grid as G  # noqa: E402
from RVUtils.ConvexityRV import cavf_signals as S  # noqa: E402
from RVUtils.ConvexityRV import cavf_universe as U  # noqa: E402
from RVUtils.ConvexityRV import strat2_fly_universe as FU  # noqa: E402

DATA = REPO / "notebooks" / "data" / "convexity_rv"
t0 = time.time()

# --- CA panel: column -> label map --------------------------------------------
ca_wide = pd.read_parquet(DATA / "cavf_ca_panel.parquet")
ca_wide.index = pd.to_datetime(ca_wide.index)
ca_raw_by_label = {}
for col in ca_wide.columns:
    parts = col.split()
    ca_raw_by_label[parts[1]] = ca_wide[col].dropna()
print(f"CA panel {ca_wide.shape}, labels {len(ca_raw_by_label)}")

# Roll-splice amendment: every label is a constant-RANK series that switches
# contracts at the front IMM roll; the jump across the roll is not P&L. Both
# the signal and the panel P&L consume the spliced series; the raw level is
# the screener's display quantity only.
ROLLS = S.imm_roll_dates(ca_wide.index)
print(f"IMM rolls inside the window: {len(ROLLS)} "
      f"({ROLLS[0].date()} .. {ROLLS[-1].date()})")
ca_by_label = {lab: S.roll_splice(s, ROLLS) for lab, s in ca_raw_by_label.items()}
splice_shift = {lab: float((ca_raw_by_label[lab] - ca_by_label[lab]).abs().max())
                for lab in ("WHITES", "GOLDS", "SFR12")}
print(f"cumulative splice magnitude (raw vs spliced, max |gap| bp): {splice_shift}")

neg_frac = {lab: float((s < 0).mean()) for lab, s in ca_raw_by_label.items()}
print("negative-CA fraction (front noise vs stale-settle diagnostic):")
print("  " + "  ".join(f"{l}:{v:.2f}" for l, v in list(neg_frac.items())[:8]))

# --- fly rates from the leg panel --------------------------------------------
legs = pd.read_parquet(DATA / "cavf_fly_legs.parquet")
wide = FU.legs_wide(legs)
wide.index = pd.to_datetime(wide.index)
missing = ca_wide.index.difference(wide.index)
print(f"legs wide {wide.shape}; CA dates absent from legs: "
      f"{[d.date() for d in missing]}")

fly_by_id = {}
for f in U.tradeable_fly_specs():
    fly_by_id[f.fly_id] = FU.fly_rate_series(wide, f, 0.5, 0.5).dropna()
print(f"{len(fly_by_id)} flies composed; e.g. 2s5s10s tail:")
print(fly_by_id["2s5s10s"].tail(2).round(3).to_string())

# --- overlay inputs -----------------------------------------------------------
from BT.signals.cftc_positioning import (  # noqa: E402
    build_positioning_panel, fetch_cftc_financial_futures, positioning_zscore)

raw = fetch_cftc_financial_futures(
    cache_path=str(REPO / "BT" / "results" / "tfp_screener" / "cftc_raw.parquet"))
dealer = build_positioning_panel(raw=raw, tenors=["SOFR3M"], metric="dealer_net")
dealer_z = positioning_zscore(dealer, window=52)["SOFR3M"].dropna()
print(f"dealer_net z: {dealer_z.index.min().date()}..{dealer_z.index.max().date()}")

from MDP.IRClearingHouseBasisSwaps.ccp_basis_cache import basis_panel  # noqa: E402

basis = basis_panel(dt.date(2020, 12, 1), dt.date(2026, 8, 21), tenors=("5y",))
basis5 = basis["5y"].copy()
basis5.index = pd.to_datetime(basis5.index) + pd.tseries.offsets.BDay(1)  # market lag
print(f"ccp basis 5y (lagged 1bd): {basis5.index.min().date()}..{basis5.index.max().date()}")

# 3m roll proxy per structure from outright ranks, lagged one day:
# roll(window at rank r) ~ (CA_out(r+3) - CA_out(r-1)) / 4. WHITES (r=1) has no
# nearer window -- structural, matches Strat2Config's rank_start >= 2 rule --
# so its carry overlay can never fire and that is recorded, not hidden.
# RAW levels, deliberately: carry is a same-day cross-rank difference, and the
# splice shifts each label's level by its own cumulative adjustment.
rolls = {}
for lab in ("WHITES", "REDS", "GREENS", "BLUES", "GOLDS"):
    spec = U.structure_by_label(lab)
    r0 = spec.ranks[0]
    if r0 < 2:
        rolls[lab] = pd.Series(dtype=float)
        continue
    hi = ca_raw_by_label.get(f"SFR{spec.ranks[-1]}")
    lo = ca_raw_by_label.get(f"SFR{r0 - 1}")
    rolls[lab] = (((hi - lo) / 4.0).dropna()).shift(1)

masks_by_structure = {}
for lab in ("WHITES", "REDS", "GREENS", "BLUES", "GOLDS"):
    masks_by_structure[lab] = {
        "positioning": S.positioning_mask(dealer_z, z_min=1.0),
        "basis": S.basis_mask(basis5, chg_bd=20, min_abs_bp=0.25),
        "carry": S.carry_mask(rolls[lab]),
    }

# --- run ----------------------------------------------------------------------
cells = G.declared_cells()
print(f"\n{len(cells)} declared cells")

def _run_all(exec_lag_bd: int) -> dict:
    out = {}
    base_first = sorted(cells, key=lambda c: c.overlay is not None)
    for i, spec in enumerate(base_first):
        base_eps = out[spec.base_cell].episodes if spec.base_cell else None
        masks = masks_by_structure.get(spec.structure) if spec.overlay else None
        out[spec.cell_id] = G.run_cell(
            spec, ca_by_label, fly_by_id, masks=masks, base_episodes=base_eps,
            exec_lag_bd=exec_lag_bd)
        if (i + 1) % 200 == 0:
            print(f"  lag{exec_lag_bd}: {i + 1}/{len(base_first)} "
                  f"({time.time() - t0:.0f}s)")
    return out


# PRIMARY: fills at t+1 (the 2026-08-24 execution-convention amendment).
results = _run_all(exec_lag_bd=1)
# DIAGNOSTIC: same-day fills. The gap to the primary measures the mark-noise
# harvest -- the first pass printed 100% hit rates through it.
results_lag0 = _run_all(exec_lag_bd=0)

stats = G.grid_stats_frame(results)
stats["neg_ca_frac"] = stats["structure"].map(neg_frac)
stats.to_parquet(DATA / "cavf_grid_stats.parquet")

rets = pd.DataFrame({cid: r.daily_zero_cost for cid, r in results.items()}).fillna(0.0)
rets.to_parquet(DATA / "cavf_grid_returns.parquet")

ep_rows = []
for cid, r in results.items():
    for ep in r.episodes:
        ep_rows.append({"cell_id": cid, "entry": ep.entry, "exit": ep.exit,
                        "side": ep.side, "beta_entry": ep.beta_entry,
                        "z_at_entry": ep.z_at_entry, "exit_reason": ep.exit_reason,
                        "hold_bd": ep.hold_bd})
pd.DataFrame(ep_rows).to_parquet(DATA / "cavf_grid_episodes.parquet")

fsm = G.fs_hypothesis_matrix(ca_by_label, fly_by_id)
fsm.to_parquet(DATA / "cavf_fs_matrix.parquet")

# --- summary + nulls ----------------------------------------------------------
traded = stats[stats["n_ep"] > 0]
med_neff = float(traded["n_eff"].median())
med_span = float(traded["span_y"].median())
bars = G.null_bars(len(cells), n_eff=med_neff, span_years=med_span)

print(f"\ncells that traded: {len(traded)}/{len(stats)}")
print(f"median n_eff {med_neff:.1f}  median span {med_span:.2f}y")
print(f"E[max SR | null, {len(cells)} trials]: "
      f"per-hold {bars['emax_perhold']:.3f}  annualised {bars['emax_annualised']:.3f}")
print("\ntop 12 by ann_sharpe (zero cost):")
cols = ["family", "structure", "fly", "z_in", "n_ep", "hit", "gross_usd",
        "net_1x", "ann_sharpe", "n_eff"]
print(stats.nlargest(12, "ann_sharpe")[cols].round(3).to_string())
print("\nfamily medians (PRIMARY, t+1 fills):")
print(stats.groupby("family")[["n_ep", "gross_usd", "net_1x", "ann_sharpe"]]
      .median().round(3).to_string())

stats0 = G.grid_stats_frame(results_lag0)
noise_harvest = (stats0["gross_usd"] - stats["gross_usd"]).rename("noise_harvest_usd")
print("\nsame-day-fill diagnostic — the mark-noise harvest by family "
      "(median gross gap, USD):")
gap = pd.concat([stats["family"], noise_harvest], axis=1)
print(gap.groupby("family")["noise_harvest_usd"].median().round(0).to_string())
print(f"\nmedian hit rate: primary {float(stats.loc[stats['n_ep']>0,'hit'].median()):.3f} "
      f"vs same-day {float(stats0.loc[stats0['n_ep']>0,'hit'].median()):.3f}")

# placebo on the top 3 non-control cells
top3 = stats[~stats["family"].isin(["A_ca", "A_fly"])].nlargest(3, "ann_sharpe")
placebo = {}
for cid in top3.index:
    spec = next(c for c in cells if c.cell_id == cid)
    if spec.overlay:
        continue
    r = G.run_cell(spec, ca_by_label, fly_by_id, signal_lag_bd=20)
    placebo[cid] = {
        "gross_live": float(results[cid].equity_by_mult[0.0].iloc[-1]),
        "gross_lag20": float(r.equity_by_mult[0.0].iloc[-1]),
    }
print("\nplacebo (signal lagged +20bd):")
for k, v in placebo.items():
    print(f"  {k}: live {v['gross_live']:,.0f} -> lag20 {v['gross_lag20']:,.0f}")

meta = {
    "declared_trials": len(cells),
    "exec_lag_bd": 1,
    "roll_spliced": True,
    "n_imm_rolls": int(len(ROLLS)),
    "splice_max_gap_bp": splice_shift,
    "null_bars": bars,
    "median_n_eff": med_neff,
    "median_span_y": med_span,
    "neg_ca_frac": neg_frac,
    "legs_missing_dates": [str(d.date()) for d in missing],
    "placebo_lag20": placebo,
    "same_day_diag": {
        "median_hit_primary": float(stats.loc[stats["n_ep"] > 0, "hit"].median()),
        "median_hit_same_day": float(stats0.loc[stats0["n_ep"] > 0, "hit"].median()),
        "median_noise_harvest_by_family": {
            k: float(v) for k, v in gap.groupby("family")["noise_harvest_usd"]
            .median().items()},
    },
    "ran_at": dt.datetime.now().isoformat(timespec="seconds"),
}
(DATA / "cavf_grid_meta.json").write_text(json.dumps(meta, indent=1))
print(f"\nwrote 5 artifacts to {DATA}  total {time.time() - t0:.0f}s")
