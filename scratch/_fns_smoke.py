"""Smoke: full composition path on FULL-SAMPLE loadings only (no engine, seconds)."""
from __future__ import annotations
import os, pathlib, sys, time
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
_REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))
import numpy as np, pandas as pd

from RVUtils.ConvexityRV import factor_neutral_sizing as fns
from RVUtils.ConvexityRV import factor_attribution as fa
from RVUtils.ConvexityRV import strat1_longend_listed as ll

DATA = _REPO / "notebooks" / "data" / "convexity_rv"
pd.set_option("display.width", 220)

t0 = time.time()
CFG = fns.FactorNeutralConfig()
S1 = ll.strat1_config()
FCFG = fa.FactorConfig()
PANEL = pd.read_parquet(DATA / "factor_rate_panel.parquet")
PANEL.index = pd.to_datetime(PANEL.index)
FM = fa.fit_factor_model(PANEL, FCFG)
print("fm:", FM.rates_bp.shape, "scores", FM.scores.shape,
      "ev", FM.explained_variance.head(3).round(4).to_dict())
print(fa.classify_pcs(FM.loadings, FM.tenors).to_string())

LEGS, IDX = fns.load_leg_runs(DATA, log=print)
print("legs:", list(LEGS), "index", len(IDX))

CERT = fns.certify_dv01_neutral(LEGS, DATA, cfg=S1)
print("\n--- certify dv01_neutral composition vs stored engine runs ---")
print(CERT[["structure", "terminal_gap_pct", "corr_daily_changes",
            "max_abs_daily_gap_usd", "n_marks_common"]].to_string(index=False))

DOM = fns.dominant_factor_table(FM)
print("\n--- dominant factor, re-measured ---")
print(DOM[["structure", "var_level", "var_slope", "var_curv", "prior_var_level",
           "prior_var_slope", "prior_var_curv", "max_abs_prior_gap", "dominant",
           "headline_sizing", "pc1_leakage_vs_outright"]].to_string(index=False))

# --- full-sample loadings for every cohort (smoke only; real run walks forward)
SCHED = LEGS["5Y"].cohorts
L_full = fns.full_sample_loadings(PANEL, FCFG, fns.LEG_UNIVERSE)
print("\nleg loadings (full sample):\n", L_full.round(4).to_string())
LBD = {pd.Timestamp(e): L_full for e in SCHED["entry"]}
W = fns.cohort_weights(SCHED, fa.STRAT1_STRUCTURES, LBD, hedge_leg=CFG.hedge_leg,
                       dv01=S1.package_dv01, sizings=fns.STATIC_SIZINGS)
print("weights frame", W.shape, sorted(W["sizing"].unique()))

print("\n--- residual exposures on measurement basis ---")
RES = fns.residual_exposure_table(W, FM)
print(RES[["structure", "sizing", "n_legs", "gross_dv01_mean", "f_level_mean",
           "f_slope_mean", "var_level", "var_slope", "var_curv"]].to_string(index=False))

rows = []
for (lab, sz), g in W.groupby(["structure", "sizing"], sort=False):
    eq, bk = fns.compose_book(LEGS, g, cfg=S1)
    st = fns.book_stats(eq, bk, cfg=S1)
    st.update({"structure": lab, "sizing": sz,
               "breakeven_cost_bp_leg": fns.breakeven_cost_bp(bk, cfg=S1)})
    rows.append(st)
ST = pd.DataFrame(rows).set_index(["structure", "sizing"])
print("\n--- book stats (full-sample weights; SMOKE) ---")
print(ST[["n_closed", "total_net_bp", "mean_net_bp", "hit_rate", "sharpe_per_trade",
          "t_stat_overlap_adj", "mtm_final_bp", "mtm_sharpe_ann",
          "breakeven_cost_bp_leg"]].round(4).to_string())

print(f"\nsmoke ok in {time.time()-t0:.1f}s")
