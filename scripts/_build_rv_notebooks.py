"""Generate the 4 RV-toolkit showcase notebooks under notebooks/rv/.

Run once: conda run -n stir python scripts/_build_rv_notebooks.py
Then execute with nbconvert. This script only assembles the .ipynb files.
"""
import os
import nbformat as nbf
from nbformat.v4 import new_notebook, new_code_cell, new_markdown_cell

OUT = os.path.join(os.path.dirname(__file__), "..", "notebooks", "rv")
os.makedirs(OUT, exist_ok=True)

SETUP = r'''%matplotlib inline
import sys; sys.path.append("../../")
import datetime, pytz, warnings
warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
import matplotlib.pyplot as plt
plt.rcParams["figure.figsize"] = (15, 6); plt.rcParams["axes.grid"] = True
from RVUtils.plt_timeseries import make_secondary_axis_plot

NYC = pytz.timezone("America/New_York")
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from TB.IRSwapsTB import IRSwapsTB
from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP
from TB.FixedRateBondsTB import FixedRateBondsTB
from Query.Unified.UnifiedQuery import UnifiedQuery
from Query.Unified.registry import UnifiedValue
from TB.TimeseriesBuilder import TimeseriesBuilder

curve_mdp = IRSwapsMDP(source="ERIS_EOD_LIVE-RL_BASIC")
usts_mdp = FixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-RL")
ts = TimeseriesBuilder()
start = NYC.localize(datetime.datetime(2025, 6, 2, 17, 0))
end = NYC.localize(datetime.datetime(2026, 6, 17, 17, 0))
ROUTERS = {"IRS": IRSwapsTB(curve_mdp, show_tqdm=False), "FRB": FixedRateBondsTB(usts_mdp, show_tqdm=False)}
YRS = {"2y": 2, "3y": 3, "5y": 5, "7y": 7, "10y": 10, "20y": 20, "30y": 30}
MAT = {"CT2": 2, "CT3": 3, "CT5": 5, "CT7": 7, "CT10": 10, "CT20": 20, "CT30": 30}

def load(queries):
    return ts.get_timeseries(start=start, end=end, queries=queries, n_jobs=8, routers=ROUTERS)

def sofr(tenors):
    df = load([UnifiedQuery(curve="USD-SOFR-1D", tenor=t, value=UnifiedValue.IRS_RATE) for t in tenors])
    return df.rename(columns={f"USD-SOFR-1D {t} OUTRIGHT RATE": t for t in tenors})[list(tenors)]

def ust(cts):
    df = load([UnifiedQuery(cusip=c, value=UnifiedValue.FRB_YTM) for c in cts])
    return df.rename(columns={f"{c} OUTRIGHT YTM": c for c in cts})[list(cts)]

print("Setup OK. Window:", start.date(), "->", end.date())'''


# ---------------------------------------------------------------- NB1
nb1 = [
    ("md", "# USD Rates RV — PCA curve & fly relative value\n\n"
           "Showcases `RVUtils.pca_rv`: PCA fair-value & residual rich/cheap, PC1/PC2-neutral "
           "fly weights, directionality, and risk buckets — on the SOFR swap curve (last ~1y EOD)."),
    ("code", SETUP),
    ("code", 'TENORS = ["2y","3y","5y","7y","10y","20y","30y"]\n'
             'df_s = sofr(TENORS)\n'
             'df_u = ust(["CT2","CT3","CT5","CT7","CT10","CT20","CT30"])\n'
             'df_s.tail(3)'),
    ("md", "### Fit PCA on the SOFR curve (levels) — level / slope / curvature"),
    ("code", 'from RVUtils.pca_rv import make_pca_rv_builder\n'
             '(fit, fair_value, residual, fly_weights, curve_weights, directionality, risk_buckets, factor_corr_check, get_model) = make_pca_rv_builder(df_s, on="levels", n_factors=3, sort_by_tenor=False)\n'
             'model = fit()\n'
             'ev = model.explained_variance()\n'
             'print("Explained variance PC1-3:", {k: round(float(v),4) for k,v in ev.head(3).items()})\n'
             'model.loadings.iloc[:, :3].round(3)'),
    ("md", "### PC1/PC2-neutral 2s5s10s fly: actual vs PCA fair value + residual z-score"),
    ("code", 'from RVUtils.plt_timeseries import make_secondary_axis_plot\n'
             'w = fly_weights("2y","5y","10y")\n'
             'print("PCA-neutral 2s5s10s weights:", {k: round(v,3) for k,v in w.items()})\n'
             'res = residual(("2y","5y","10y"), weights=w)\n'
             'fv = fair_value(k=3)\n'
             'fly_raw = (w["2y"]*df_s["2y"] + w["5y"]*df_s["5y"] + w["10y"]*df_s["10y"]) * 100\n'
             'fly_fv  = (w["2y"]*fv["2y"]   + w["5y"]*fv["5y"]   + w["10y"]*fv["10y"])   * 100\n'
             'print("Latest residual (+=belly cheap):", round(res.last()*100,2), "bp  | z65:", round(res.zscore(65).iloc[-1],2))\n'
             'plot, fig, ax, ax2, legend = make_secondary_axis_plot(engine="matplotlib", title="PCA-neutral 2s5s10s SOFR fly: actual vs PCA fair value")\n'
             'plot(fly_raw.rename("2s5s10s fly (bp)"), which="left", indicators=[{"kind":"fair_value","series":fly_fv,"label":"PCA fair value"}])\n'
             'plot(res.zscore(65).rename("residual z65"), which="right", indicators=[{"kind":"zbands","entry":2,"stop":3}])\n'
             'legend(show_date=True, loc="upper left"); plt.show()'),
    ("md", "### Directionality (betas to level/slope) and risk-bucket check"),
    ("code", 'dirn = directionality(("2y","5y","10y"), weights=w, drivers=("PC1","PC2"))\n'
             'print("Fly betas to PC1/PC2:", {k: round(float(v),4) for k,v in dirn["betas"].items()})\n'
             'ladder = pd.Series(0.0, index=TENORS); ladder["2y"]=w["2y"]; ladder["5y"]=w["5y"]; ladder["10y"]=w["10y"]\n'
             'print("Fly PC exposures (PC1/PC2 ~ 0 by construction):", {k: round(float(v),4) for k,v in risk_buckets(ladder).head(3).items()})'),
    ("md", "### UST CT2/CT10/CT30 PCA-fly residual (cross-check vs cash curve)"),
    ("code", 'bu = make_pca_rv_builder(df_u.rename(columns={c:c for c in df_u.columns}), on="levels", n_factors=3, sort_by_tenor=False)\n'
             'bu[0]()\n'
             'wu = bu[3]("CT2","CT10","CT30")\n'
             'resu = bu[2](("CT2","CT10","CT30"), weights=wu)\n'
             'print("UST 2s10s30s PCA-neutral weights:", {k: round(v,3) for k,v in wu.items()})\n'
             'print("Latest UST fly residual (+=belly cheap):", round(resu.last()*100,2), "bp | z65:", round(resu.zscore(65).iloc[-1],2))'),
]

# ---------------------------------------------------------------- NB2
nb2 = [
    ("md", "# USD Rates RV — Regression, beta-stability & cointegration\n\n"
           "Showcases `RVUtils.regression` (fair-value vs drivers, beta-stability TLI, residual "
           "diagnostics) and `RVUtils.cointegration` (Engle-Granger / Johansen) on USD swap & UST data."),
    ("code", SETUP),
    ("code", 'df_s = sofr(["2y","5y","10y","30y"])\n'
             'df_u = ust(["CT2","CT5","CT10","CT30"])\n'
             'ust_10s30s  = (df_u["CT30"] - df_u["CT10"]) * 100\n'
             'sofr_10s30s = (df_s["30y"] - df_s["10y"]) * 100\n'
             'df_s.tail(3)'),
    ("md", "### Regression: UST 10s30s on SOFR 10s30s — fitted residual = rich/cheap"),
    ("code", 'from RVUtils.regression import make_linear_regression_builder, rolling_beta_stability, residual_diagnostics\n'
             'reg = pd.concat([ust_10s30s.rename("UST 10s30s"), sofr_10s30s.rename("SOFR 10s30s")], axis=1).dropna()\n'
             'add_indep_var, fitr, pavp, prvp, prts, get_data = make_linear_regression_builder(df=reg, y_col="UST 10s30s")\n'
             'add_indep_var("SOFR 10s30s")\n'
             'res = fitr(model="OLS", verbose=False)\n'
             'print("beta:", {k: round(float(v),3) for k,v in res.params.items()}, " R2:", round(res.rsquared,3))\n'
             'diag = residual_diagnostics(res.resid)\n'
             'print("residual half-life:", round(diag["half_life"],1), "d | ADF p:", round(diag["adf_pvalue"],4))\n'
             'prts(plot_zscores=True, plot_zero=True, stds=[1,2], ou_bands=True)'),
    ("md", "### Beta-stability Traffic-Light Index (TLI) for the 2s5s10s fly (gate >= 3)"),
    ("code", 'df_f = sofr(["2y","5y","10y"])\n'
             'fly = (2*df_f["5y"] - df_f["2y"] - df_f["10y"]) * 100\n'
             'drivers = pd.concat([df_f["5y"].rename("level"), ((df_f["10y"]-df_f["2y"])*100).rename("slope")], axis=1)\n'
             'tli = rolling_beta_stability(fly, drivers, window_beta=63, window_vol=21, window_z=63)\n'
             'plot, fig, ax, ax2, legend = make_secondary_axis_plot(engine="matplotlib", title="2s5s10s SOFR fly beta-stability TLI")\n'
             'plot(fly.rename("2s5s10s (bp)"), which="left")\n'
             'plot(tli["TLI"].rename("TLI"), which="right", indicators=[{"kind":"last"}])\n'
             'legend(show_date=True, loc="upper left"); plt.show()'),
    ("md", "### Cointegration: 10y swap spread (UST CT10 vs SOFR 10y)"),
    ("code", 'from RVUtils.cointegration import engle_granger, johansen\n'
             'eg = engle_granger(df_u["CT10"], df_s["10y"])\n'
             'print("EG beta:", round(eg["beta"],3), " ADF p:", round(eg["pvalue"],4), " half-life:", round(eg["half_life"],1), "d")\n'
             'jo = johansen(pd.concat([df_u["CT10"].rename("CT10"), df_s["10y"].rename("SOFR10")], axis=1).dropna())\n'
             'print("Johansen rank:", jo["rank"], " coint vector:", np.round(jo["coint_vector"],3))\n'
             'sp = eg["spread"] * 100\n'
             'plot, fig, ax, ax2, legend = make_secondary_axis_plot(engine="matplotlib", title="10y swap-spread cointegration residual (bp) with entry/stop bands")\n'
             'plot(sp.rename("EG residual (bp)"), which="left", indicators=[{"kind":"zbands","entry":2,"stop":3}, {"kind":"last"}])\n'
             'legend(show_date=True, loc="upper left"); plt.show()'),
    ("md", "### OU ex-ante Sharpe on the cointegration residual"),
    ("code", 'from RVUtils.signal_backtest import make_signal_backtest_builder\n'
             'sb = make_signal_backtest_builder(eg["spread"])\n'
             'forecast, zsig, position, pnl, stats_fn, ex_ante, fpt, gate, getd = sb\n'
             'print("OU ex-ante Sharpe (21d):", round(ex_ante(horizon=21), 2))'),
]

# ---------------------------------------------------------------- NB3
nb3 = [
    ("md", "# USD Rates RV — Carry / roll-down & cross-structure screener\n\n"
           "Showcases `RVUtils.carry_roll`, `RVUtils.screener_rv` (composite rank + RV dislocation "
           "index) and the ING PC1-residual vs carry/roll 'double-alpha' scatter on the SOFR curve."),
    ("code", SETUP),
    ("code", 'TEN = ["2y","3y","5y","7y","10y","20y","30y"]\n'
             'df_s = sofr(TEN)\n'
             'curve_ts = df_s.rename(columns=YRS)   # float tenor columns for carry/roll\n'
             'curve_ts.tail(3)'),
    ("md", "### 3-month carry + roll-down for a curve and a fly"),
    ("code", 'from RVUtils.carry_roll import make_carry_roll_builder\n'
             'roll_ts, carry_ts, total_ts, be_ts, ctv_ts, getd = make_carry_roll_builder(curve_ts, horizon=0.25)\n'
             'cr_curve = total_ts(("curve", 2, 10)) * 100\n'
             'cr_fly   = total_ts(("fly", [2,5,10], [-1,2,-1])) * 100\n'
             'print("2s10s 3m carry+roll:", round(cr_curve.iloc[-1],2), "bp | 2s5s10s fly:", round(cr_fly.iloc[-1],2), "bp")'),
    ("md", "### Cross-structure composite screener + RV dislocation index"),
    ("code", 'from RVUtils.screener_rv import make_rv_screener\n'
             'S = {}\n'
             'S["2s5s10s"]  = (2*df_s["5y"]  - df_s["2y"] - df_s["10y"]) * 100\n'
             'S["5s10s30s"] = (2*df_s["10y"] - df_s["5y"] - df_s["30y"]) * 100\n'
             'S["3s7s10s"]  = (2*df_s["7y"]  - df_s["3y"] - df_s["10y"]) * 100\n'
             'S["2s10s"]    = (df_s["10y"] - df_s["2y"]) * 100\n'
             'S["5s30s"]    = (df_s["30y"] - df_s["5y"]) * 100\n'
             'S["10s30s"]   = (df_s["30y"] - df_s["10y"]) * 100\n'
             'structs = pd.DataFrame(S)\n'
             'cmap = {"2s5s10s":("fly",[2,5,10],[-1,2,-1]), "5s10s30s":("fly",[5,10,30],[-1,2,-1]), "3s7s10s":("fly",[3,7,10],[-1,2,-1]), "2s10s":("curve",2,10), "5s30s":("curve",5,30), "10s30s":("curve",10,30)}\n'
             'carry_df = pd.DataFrame({k: total_ts(v)*100 for k, v in cmap.items()})\n'
             'build, rank, to_df, di_fn, getd2 = make_rv_screener(structs, carry_df=carry_df, zscore_window=65, vol_window=20)\n'
             'rank(6)[["level","zscore","percentile","vol","carry","carry_to_vol","half_life","composite","direction"]].round(2)'),
    ("code", 'di = di_fn()\n'
             'plot, fig, ax, ax2, legend = make_secondary_axis_plot(engine="matplotlib", title="USD RV dislocation index (10D MA of sum z^2 across flies/curves)")\n'
             'plot(di.rename("RV dislocation index"), which="left", indicators=[{"kind":"last"}])\n'
             'legend(show_date=True, loc="upper left"); plt.show()'),
    ("md", "### ING 'double-alpha' scatter: PCA residual (rich/cheap) vs 3m roll-down per tenor"),
    ("code", 'from RVUtils.pca_rv import make_pca_rv_builder\n'
             'bp = make_pca_rv_builder(curve_ts, on="levels", n_factors=3, sort_by_tenor=False)\n'
             'bp[0]()\n'
             'fvtab = bp[1](k=3)\n'
             'resid_latest = (curve_ts.iloc[-1] - fvtab.iloc[-1]) * 100\n'
             'roll_latest = pd.Series({t: roll_ts(("outright", t)).iloc[-1]*100 for t in curve_ts.columns})\n'
             'fig2, axx = plt.subplots(figsize=(9,6))\n'
             'axx.scatter(resid_latest.values, roll_latest.values)\n'
             'for t in curve_ts.columns: axx.annotate(f"{int(t)}y", (resid_latest[t], roll_latest[t]))\n'
             'axx.axhline(0, color="grey", ls="--"); axx.axvline(0, color="grey", ls="--")\n'
             'axx.set_xlabel("PCA residual (bp, + = cheap)"); axx.set_ylabel("3m roll-down (bp)")\n'
             'axx.set_title("ING double-alpha: PCA residual vs carry/roll (latest)"); plt.show()'),
]

# ---------------------------------------------------------------- NB4
nb4 = [
    ("md", "# USD Rates RV — Fitted-curve rich/cheap & signal backtest\n\n"
           "Showcases `RVUtils.curve_fit_rv` (NSS cross-sectional rich/cheap on the UST CT curve) "
           "and `RVUtils.signal_backtest` (z-score strategy on a PCA-fly residual signal)."),
    ("code", SETUP),
    ("code", 'CTS = ["CT2","CT3","CT5","CT7","CT10","CT20","CT30"]\n'
             'df_u = ust(CTS)\n'
             'snap = pd.DataFrame({"id": CTS, "maturity": [MAT[c] for c in CTS], "yield": [df_u[c].iloc[-1] for c in CTS]})\n'
             'snap'),
    ("md", "### NSS fit of the latest UST CT curve — residual = rich/cheap"),
    ("code", 'from RVUtils.curve_fit_rv import make_curve_fit_builder\n'
             'fit, residual, rank, rmse, otr, getd = make_curve_fit_builder(snap, id_col="id", form="nss")\n'
             'res_df = fit()\n'
             'print("Cross-sectional fit RMSE:", round(rmse()*100, 2), "bp")\n'
             'fig, axx = plt.subplots(figsize=(11,6))\n'
             'axx.scatter(res_df["maturity"], res_df["yield"], zorder=3, label="actual")\n'
             'order = res_df.sort_values("maturity")\n'
             'axx.plot(order["maturity"], order["fitted"], "r--", label="NSS fit")\n'
             'for _, r in res_df.iterrows(): axx.annotate(r["id"], (r["maturity"], r["yield"]))\n'
             'axx.legend(); axx.set_xlabel("maturity (y)"); axx.set_ylabel("yield (%)")\n'
             'axx.set_title("UST CT curve NSS fit & rich/cheap (latest)"); plt.show()\n'
             'res_df.assign(residual_bp=(res_df["residual"]*100).round(2))[["id","maturity","yield","fitted","residual_bp"]]'),
    ("md", "### Rich/cheap ranking (most cheap first)"),
    ("code", 'rank()[["id","residual"]].assign(residual_bp=lambda d: (d["residual"]*100).round(2))'),
    ("md", "### Backtest: z-score strategy on the SOFR 2s5s10s PCA-fly residual"),
    ("code", 'from RVUtils.pca_rv import make_pca_rv_builder\n'
             'from RVUtils.signal_backtest import make_signal_backtest_builder\n'
             'df_f = sofr(["2y","5y","10y"])\n'
             'b = make_pca_rv_builder(df_f, on="levels", n_factors=2, sort_by_tenor=False)\n'
             'b[0]()\n'
             'w = b[3]("2y","5y","10y")\n'
             'sig = b[2](("2y","5y","10y"), weights=w).series\n'
             'forecast, zsig, position, pnl, stats_fn, ex_ante, fpt, gate, getd = make_signal_backtest_builder(sig)\n'
             'pos = zsig(window=65, entry=1.5, exit=0.5, stop=4.0)\n'
             'p = pnl(pos, cost_bps=0.0)\n'
             'st = stats_fn(pos)\n'
             'shp = st["sharpe"]; mdd = st["max_dd"]\n'
             'print({k: round(v,3) for k,v in st.items()})\n'
             'cum = p.cumsum()\n'
             'fig, axx = plt.subplots(figsize=(14,5))\n'
             'axx.plot(cum.index, cum.values)\n'
             'axx.set_title(f"2s5s10s PCA-fly residual z-strategy: cum PnL (Sharpe {shp:.2f}, maxDD {mdd:.3f})")\n'
             'axx.set_ylabel("cumulative P&L (rate units)"); plt.show()'),
]

NBS = {
    "rv_pca_curve_fly.ipynb": nb1,
    "rv_statistical_regression_cointegration.ipynb": nb2,
    "rv_carry_roll_screener.ipynb": nb3,
    "rv_fitted_curve_and_backtest.ipynb": nb4,
}

for name, cells in NBS.items():
    nb = new_notebook()
    nb.cells = [new_markdown_cell(s) if t == "md" else new_code_cell(s) for t, s in cells]
    nb.metadata = {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}}
    path = os.path.join(OUT, name)
    with open(path, "w", encoding="utf-8") as f:
        nbf.write(nb, f)
    print("wrote", os.path.normpath(path), f"({len(cells)} cells)")
