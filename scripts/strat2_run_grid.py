"""Run the Strategy-2 butterfly grid and print every measured number.

    C:/Users/chris/anaconda3/envs/stir/python.exe scripts/strat2_run_grid.py

Reads ``strat2_panel.parquet`` (the CA panel) and ``strat2_fly_legs.parquet``
(par rates + 3M carry per leg tenor), and writes:

``strat2_grid_results.csv``       one row per grid cell
``strat2_effectiveness.csv``      the (pack T1) x (fly forward start) matrix
``strat2_fly_weights.csv``        rolling regression weights vs Citi's anchors
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pathlib
import sys

_REPO = pathlib.Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import numpy as np
import pandas as pd

pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 60)

OUT = _REPO / "notebooks" / "data" / "convexity_rv"


def main() -> None:
    from RVUtils.ConvexityRV.strat2_fly_universe import (
        fly_by_id,
        fly_regression,
        fly_universe,
        legs_wide,
    )
    from RVUtils.ConvexityRV.strat2_grid import (
        Strat2GridConfig,
        constant_contract_dca,
        effectiveness_matrix,
        prepare_inputs,
        run_grid,
        simulate_cell,
    )
    from RVUtils.ConvexityRV.strat2_sofr_convexity import Strat2Config

    panel = pd.read_parquet(OUT / "strat2_panel.parquet")
    legs_long = pd.read_parquet(OUT / "strat2_fly_legs.parquet")
    rates = legs_wide(legs_long, "rate_pct")
    carry = legs_wide(legs_long, "carry_roll_bp")

    print("=" * 100)
    print("0. DATA")
    print("=" * 100)
    print(f"CA panel      {panel.shape}  {panel['date'].min():%Y-%m-%d}..{panel['date'].max():%Y-%m-%d}"
          f"  {panel['date'].nunique()} dates, ranks {sorted(panel['rank'].unique())}")
    print(f"leg panel     {rates.shape}  {rates.index.min():%Y-%m-%d}..{rates.index.max():%Y-%m-%d}"
          f"  {rates.shape[1]} tenors")
    nan_by_tenor = rates.isna().sum()
    bad = nan_by_tenor[nan_by_tenor > 0]
    print(f"tenors with any missing rate: {dict(bad) if len(bad) else 'none'}")
    ca_years = panel.groupby(panel["date"].dt.year)["date"].nunique()
    print("CA panel dates per year:", dict(ca_years))

    cfg2 = Strat2Config()
    inp = prepare_inputs(panel, rates, carry=carry, strat2_cfg=cfg2)
    print(f"COMMON date axis: {len(inp.dates)} days "
          f"{inp.dates.min():%Y-%m-%d}..{inp.dates.max():%Y-%m-%d}")
    dense = inp.dates[inp.dates <= pd.Timestamp("2023-10-01")]
    print(f"  of which <= 2023-10-01 (the dense SR3 region): {len(dense)}")

    # ------------------------------------------------------------------ 1
    print()
    print("=" * 100)
    print("1. THE HYPOTHESIS TABLE -- R^2 of constant-contract dCA on d(fly), 50/50 wings")
    print("=" * 100)
    frames = {}
    for shape in ("2s5s10s", "2s3s5s", "1s2s3s", "3s5s7s", "2s7s30s", "5s10s30s",
                  "10s20s30s", "5s7s10s", "2s10s30s"):
        m = effectiveness_matrix(inp, shape=shape, ranks=tuple(range(2, 11)),
                                 weighting="dv01_neutral")
        frames[shape] = m
        print(f"\n--- {shape} ---")
        print(m.round(4).to_string())
        cols = [c for c in m.columns if c.startswith("fs_")]
        best = m[cols].idxmax(axis=1)
        print("best forward start per rank:", dict(zip(m.index, best)))
    from RVUtils.ConvexityRV.strat2_grid import hypothesis_slope

    hs = hypothesis_slope(frames)
    print("
*** THE HYPOTHESIS TEST ***")
    print(f"  argmax-T1 regressed on fly forward start over {hs['n']} (shape, start) cells:")
    print(f"    slope = {hs['slope']:+.3f} years of pack T1 per year of forward start "
          f"(hypothesis predicts ~+1.0)")
    print(f"    corr  = {hs['corr']:+.3f}")
    print(f"    mean peak R^2 by forward start: "
          f"{ {k: round(v, 4) for k, v in hs['peak_r2_by_start'].items()} }")

    eff = pd.concat(frames, names=["shape"])
    eff.to_csv(OUT / "strat2_effectiveness.csv")
    print(f"\nwrote {OUT / 'strat2_effectiveness.csv'}")

    # correlation between T1 and the best forward start, for 2s5s10s
    m = frames["2s5s10s"]
    cols = [c for c in m.columns if c.startswith("fs_")]
    fs_vals = np.array([float(c[3:-1]) for c in cols])
    best_fs = np.array([fs_vals[np.nanargmax(m.loc[r, cols].to_numpy(float))]
                        if np.isfinite(m.loc[r, cols].to_numpy(float)).any() else np.nan
                        for r in m.index])
    ok = np.isfinite(best_fs) & np.isfinite(m["T1_years"].to_numpy())
    if ok.sum() > 2:
        print(f"\ncorr(T1, argmax forward start) on 2s5s10s = "
              f"{np.corrcoef(m['T1_years'].to_numpy()[ok], best_fs[ok])[0, 1]:.3f}")
    print("spot-minus-best gap per rank (2s5s10s):")
    for r in m.index:
        v = m.loc[r, cols].to_numpy(float)
        if np.isfinite(v).any():
            print(f"  rank {r:2d} T1={m.loc[r,'T1_years']:.2f}  spot={v[0]:.4f} "
                  f"best={np.nanmax(v):.4f} at fs={fs_vals[np.nanargmax(v)]:.0f}Y "
                  f"lift={np.nanmax(v)-v[0]:+.4f}")

    # ------------------------------------------------------------------ 2
    print()
    print("=" * 100)
    print("2. REGRESSION WEIGHTS ON OUR OWN SAMPLE vs CITI'S 2017 ANCHORS")
    print("=" * 100)
    print("Citi: 13-Jan-2017  alpha 10.2  beta 21.4  w2 0.73  w10 0.47")
    print("      09-Feb-2017  alpha  9.7  beta 20.6  w2 0.705 w10 0.465")
    from RVUtils.ConvexityRV.strat2_grid import rank_following_ca

    rows = []
    spec = fly_by_id("2s5s10s")
    for rank in range(2, 11):
        ca_rank = rank_following_ca(inp, rank)
        for basis in ("levels", "changes"):
            for window in (63, 126, 252):
                fits = []
                for d in inp.dates[window::21]:
                    f = fly_regression(ca_rank.loc[:d].dropna(), inp.legs.loc[:d], spec,
                                       window_days=window, basis=basis)
                    if np.isfinite(f.beta):
                        fits.append((f.beta, f.w_front, f.w_back, f.r2))
                if not fits:
                    continue
                a = np.array(fits, float)
                rows.append({"rank": rank, "basis": basis, "window": window,
                             "n_fits": len(fits),
                             "beta_med": np.nanmedian(a[:, 0]),
                             "beta_iqr": float(np.nanpercentile(a[:, 0], 75)
                                               - np.nanpercentile(a[:, 0], 25)),
                             "w2_med": np.nanmedian(a[:, 1]),
                             "w10_med": np.nanmedian(a[:, 2]),
                             "r2_med": np.nanmedian(a[:, 3]),
                             "frac_beta_pos": float(np.mean(a[:, 0] > 0)),
                             "frac_both_wings_pos": float(
                                 np.mean((a[:, 1] > 0) & (a[:, 2] > 0)))})
    w = pd.DataFrame(rows)
    for basis in ("levels", "changes"):
        print(f"\n--- basis = {basis} (rolling-rank CA series, Citi's 'Blues CA') ---")
        print(w[w.basis == basis].drop(columns=["basis"]).round(4).to_string(index=False))
    w.to_csv(OUT / "strat2_fly_weights.csv", index=False)
    print(f"wrote {OUT / 'strat2_fly_weights.csv'}")

    # ------------------------------------------------------------------ 3
    print()
    print("=" * 100)
    print("3. FLY 3M CARRY+ROLL (bp, paid belly, 50/50 wings) -- Citi claims ~+4bp on 2s5s10s")
    print("=" * 100)
    fp = pd.read_parquet(OUT / "strat2_fly_panel.parquet")
    fp = fp[fp["date"].isin(inp.dates)]
    cs = (fp.groupby(["shape", "forward_start_y"])["carry_roll_3m_bp"]
          .agg(["mean", "median", "std"]).round(3))
    print(cs.to_string())

    # ------------------------------------------------------------------ 4
    print()
    print("=" * 100)
    print("4. THE GRID")
    print("=" * 100)
    RANKS = [3, 5, 7, 9]
    base = Strat2GridConfig(pack_rank=8, fly_id="2s5s10s", fly_weighting="regression",
                            hedge_sizing="regression_beta", regression_window=252,
                            regression_basis="changes", regression_target="rank",
                            entry_rule="always", rebalance_days=21, holding_days=63,
                            ca_dv01=100_000.0, cost_bp_roundtrip=0.25)
    all_ids = [s.fly_id for s in fly_universe()]

    print("\n4a. every fly x pack rank, regression weights + Citi beta sizing (CHANGES basis)")
    g1, _ = run_grid(inp, base, axes={"fly_id": all_ids, "pack_rank": RANKS},
                     progress=True)
    g1["cell"] = "fly_x_rank_changes"

    print("\n4a'. the same on Citi's LEVELS basis")
    g1b, _ = run_grid(inp, base, axes={"fly_id": all_ids, "pack_rank": RANKS,
                                       "regression_basis": ["levels"]}, progress=True)
    g1b["cell"] = "fly_x_rank_levels"

    print("\n4b. unhedged baseline per rank")
    g0, _ = run_grid(inp, base, axes={"hedge_sizing": ["unhedged"],
                                      "pack_rank": RANKS}, progress=False)
    g0["cell"] = "unhedged"

    print("\n4c. weighting / sizing / basis / window / entry rule, on Citi's own fly")
    g2, _ = run_grid(inp, base, axes={
        "fly_weighting": ["regression", "dv01_neutral"],
        "hedge_sizing": ["regression_beta", "dv01_ratio"],
        "regression_basis": ["levels", "changes"],
        "regression_window": [63, 126, 252],
        "entry_rule": ["always", "ca_z", "vs_model_z", "carry"],
    }, progress=True)
    g2["cell"] = "knobs"

    print("\n4d. holding period x direction")
    g3, _ = run_grid(inp, base, axes={"holding_days": [21, 63, 126],
                                      "direction": ["short_ca", "long_ca"]},
                     progress=False)
    g3["cell"] = "hold_dir"

    grid = pd.concat([g1, g1b, g0, g2, g3], ignore_index=True)
    grid.to_csv(OUT / "strat2_grid_results.csv", index=False)
    print(f"\nwrote {OUT / 'strat2_grid_results.csv'} {grid.shape}")

    cols = ["cell", "fly_id", "pack_rank", "fly_weighting", "hedge_sizing",
            "regression_window", "regression_basis", "regression_target",
            "entry_rule", "holding_days", "direction",
            "n_epochs", "total_pnl", "sharpe", "max_drawdown", "hit_rate",
            "hedge_r2", "variance_reduction", "corr_dca_dfly", "fly_carry_3m_bp",
            "gamma_pnl", "gamma_share", "mean_beta", "mean_w_front", "mean_w_back",
            "pnl_cost_0x", "pnl_cost_0.5x", "pnl_cost_1x", "pnl_cost_2x"]
    cols = [c for c in cols if c in grid.columns]

    print("\n--- unhedged baseline ---")
    print(g0[cols].round(3).to_string(index=False))

    print("\n--- top 20 by variance reduction (fly x rank) ---")
    print(g1.sort_values("variance_reduction", ascending=False).head(20)[cols]
          .round(3).to_string(index=False))

    print("\n--- 2s5s10s family across ranks (Citi's fly and its forward variants) ---")
    fam = g1[g1["fly_id"].str.startswith("2s5s10s")].sort_values(["pack_rank", "fly_id"])
    print(fam[cols].round(3).to_string(index=False))

    print("\n--- knobs on Citi's own cell ---")
    print(g2.sort_values("sharpe", ascending=False)[cols].round(3).to_string(index=False))

    print("\n--- holding period x direction ---")
    print(g3[cols].round(3).to_string(index=False))

    # ------------------------------------------------------------------ 5
    print()
    print("=" * 100)
    print("5. GAMMA CORRECTION -- how big is the omitted second order?")
    print("=" * 100)
    for rank in RANKS:
        for gamma in (False, True):
            c = Strat2GridConfig(pack_rank=rank, fly_id="2s5s10s",
                                 fly_weighting="regression",
                                 hedge_sizing="regression_beta", include_gamma=gamma,
                                 regression_basis="changes", regression_target="rank",
                                 rebalance_days=21, holding_days=63,
                                 cost_bp_roundtrip=0.0)
            r = simulate_cell(inp, c)
            m = r.metrics
            print(f"  rank {rank:2d} gamma={str(gamma):5s}  total=${m['total_pnl']:>12,.0f} "
                  f"ca=${m['ca_leg_pnl']:>12,.0f} fly=${m['fly_leg_pnl']:>11,.0f} "
                  f"gamma=${m['gamma_pnl']:>11,.0f} share={m['gamma_share']:+.3f} "
                  f"sharpe={m['sharpe']:.2f}")


if __name__ == "__main__":
    main()
