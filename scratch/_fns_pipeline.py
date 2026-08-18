"""Full walk-forward pipeline, validated before it becomes the notebook."""
from __future__ import annotations
import os, pathlib, sys, time, json
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
_REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))
import numpy as np, pandas as pd

from RVUtils.ConvexityRV import factor_neutral_sizing as fns
from RVUtils.ConvexityRV import factor_attribution as fa
from RVUtils.ConvexityRV import strat1_longend_listed as ll

DATA = _REPO / "notebooks" / "data" / "convexity_rv"
pd.set_option("display.width", 250); pd.set_option("display.max_columns", 80)
t0 = time.time()

CFG = fns.FactorNeutralConfig(); S1 = ll.strat1_config(); FCFG = fa.FactorConfig()
DV01 = float(S1.package_dv01)
PANEL = pd.read_parquet(DATA / "factor_rate_panel.parquet"); PANEL.index = pd.to_datetime(PANEL.index)
FM = fa.fit_factor_model(PANEL, FCFG)
CAL = FM.scores.index
LEGS, IDX = fns.load_leg_runs(DATA, log=print)
SCHED = LEGS["5Y"].cohorts
GREEKS = fns.load_leg_greeks(DATA)
GAMMA = fns.leg_gamma_bp(GREEKS); CARRY = fns.leg_carry_bp(GREEKS)

ENTRIES = list(pd.to_datetime(SCHED["entry"]))
LBD, DIAG, VBD = fns.walk_forward_loadings(
    PANEL, FCFG, ENTRIES, fns.LEG_UNIVERSE,
    min_fit_days=CFG.min_fit_days, hard_floor=CFG.hard_fit_floor)
W = fns.cohort_weights(SCHED, fa.STRAT1_STRUCTURES, LBD, hedge_leg=CFG.hedge_leg,
                       dv01=DV01, neutralize=CFG.neutralize, sizings=fns.STATIC_SIZINGS)
W_CACHE = pd.read_parquet(DATA / "fns_cohort_weights.parquet")
gap = float(np.abs(W.sort_values(["structure", "sizing", "cohort", "leg"])["dv01"].to_numpy()
                   - W_CACHE.sort_values(["structure", "sizing", "cohort", "leg"])["dv01"].to_numpy()).max())
print(f"walk-forward weights reproduce the cached table to {gap:.3e} $ of DV01")
assert gap < 1e-6

# ---------------------------------------------------------------- static books
EQ, BK, CARRY_USD = {}, {}, {}
for (lab, sz), g in W.groupby(["structure", "sizing"], sort=False):
    EQ[(lab, sz)], BK[(lab, sz)] = fns.compose_book(LEGS, g, cfg=S1)
    # package 1-year carry in $ at each cohort entry: sum_L r_L * carry_bp_L
    ck = {}
    for k, gk in g.groupby("cohort"):
        d = pd.Timestamp(gk["entry"].iloc[0])
        cb = fns.leg_carry_bp(GREEKS, on=d)
        ck[d] = float(sum(float(r) * float(cb.get(l, np.nan))
                          for l, r in zip(gk["leg"], gk["dv01"])))
    CARRY_USD[(lab, sz)] = pd.Series(ck).sort_index()

# ---------------------------------------------------------------- the overlay
print("\n--- slope-beta overlay (walk-forward beta AND walk-forward factor) ---")
NLIVE = fns.live_packages(SCHED, IDX)
SCORES_AT = {d: fns.walk_forward_scores(PANEL, FCFG, VBD[d], d, window=CFG.beta_window)
             for d in ENTRIES}
OVL: dict = {}
for lab, front, back in fa.STRAT1_STRUCTURES:
    wsub = W[(W["structure"] == lab) & (W["sizing"] == "dv01_neutral")]
    gross, _gb = fns.compose_book(LEGS, wsub, cfg=S1, cost_bp_one_way=0.0)
    betas = fns.slope_beta_path(gross, NLIVE, SCORES_AT, ENTRIES, window=CFG.beta_window)
    sched_l = SCHED.assign(structure=lab)
    ov_eq, ov_bk, hpath = fns.compose_overlay(LEGS, sched_l, betas, LBD, cfg=S1)
    eq, bk = fns.add_overlay(EQ[(lab, "dv01_neutral")], BK[(lab, "dv01_neutral")],
                             ov_eq, ov_bk, cfg=S1)
    EQ[(lab, "slope_beta_hedged")] = eq
    BK[(lab, "slope_beta_hedged")] = bk
    CARRY_USD[(lab, "slope_beta_hedged")] = CARRY_USD[(lab, "dv01_neutral")]
    OVL[lab] = (betas, ov_bk, hpath)
    cs = fns.overlay_cost_sensitivity(ov_bk, hpath, sched_l, cfg=S1)
    print(f"{lab:16s} beta mean {betas['beta_usd_per_pc2'].mean():>10,.0f} "
          f"hedge/leg mean {hpath['hedge_dv01_per_leg'].mean():>9,.0f}  "
          f"overlay gross ${ov_bk['overlay_gross_usd'].sum():>13,.0f}  "
          f"cost ${ov_bk['overlay_cost_usd'].sum():>12,.0f}  "
          f"churn {float(cs.loc[2, 'total_cost_usd']):.2f}x")

# ---------------------------------------------------------------- stats
rows = []
for (lab, sz), eq in EQ.items():
    st = fns.book_stats(eq, BK[(lab, sz)], cfg=S1,
                        carry_bp=float(CARRY_USD[(lab, sz)].mean() / DV01))
    gross, _ = fns.compose_book(LEGS, W[(W["structure"] == lab) & (W["sizing"] == sz)],
                                cfg=S1, cost_bp_one_way=0.0) if sz != "slope_beta_hedged" else (None, None)
    st.update({"structure": lab, "sizing": sz,
               "gross_bp_total": float(BK[(lab, sz)].loc[BK[(lab, sz)]["closed"], "gross_bp"].sum()),
               "cost_bp_total": float(BK[(lab, sz)].loc[BK[(lab, sz)]["closed"], "cost_bp"].sum()),
               "breakeven_cost_bp_leg": fns.breakeven_cost_bp(BK[(lab, sz)], cfg=S1)})
    rows.append(st)
ST = pd.DataFrame(rows).set_index(["structure", "sizing"]).sort_index()
print("\n--- book stats, WALK-FORWARD weights, net of each sizing's own cost ---")
print(ST[["n_closed", "gross_bp_total", "cost_bp_total", "total_net_bp", "mean_net_bp",
          "hit_rate", "sharpe_per_trade", "t_stat_overlap_adj", "mtm_final_bp",
          "mtm_sharpe_ann", "mtm_max_dd_bp", "mean_carry_bp",
          "breakeven_cost_bp_leg"]].round(4).to_string())

# ---------------------------------------------------------------- residual exposure
print("\n--- residual exposures (walk-forward weights, measured on the shared basis) ---")
RES = fns.residual_exposure_table(W, FM)
print(RES[["structure", "sizing", "n_legs", "gross_dv01_mean", "abs_f_level_mean",
           "abs_f_slope_mean", "var_level", "var_slope", "var_curv"]].round(4).to_string(index=False))

# ---------------------------------------------------------------- n_eff + scoreboard
for sz in fns.SIZINGS:
    books = {lab: BK[(lab, sz)] for lab, _f, _b in fa.STRAT1_STRUCTURES}
    ne = fns.n_eff_report(books, cfg=S1)
    print(f"\nn_eff {sz}: per-structure {ne['n_eff_per_structure_mean']:.3f}  "
          f"rbar {ne['mean_pairwise_r']:.3f}  k_eff {ne['k_eff_structures']:.3f}  "
          f"pooled {ne['n_eff_pooled']:.3f}")

print(f"\n{time.time()-t0:.1f}s")
