"""Build the 10s30s flattener desk-pitch notebook -> notebooks/rv/rv_10s30s_flattener_pitch.ipynb"""
import os
import nbformat as nbf
from nbformat.v4 import new_notebook, new_code_cell, new_markdown_cell

OUT = os.path.join(os.path.dirname(__file__), "..", "notebooks", "rv")
os.makedirs(OUT, exist_ok=True)

SETUP = r'''%matplotlib inline
import sys; sys.path.append("../../")
import datetime, pytz, warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, matplotlib.pyplot as plt
plt.rcParams["figure.figsize"] = (15, 6); plt.rcParams["axes.grid"] = True
NYC = pytz.timezone("America/New_York")
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from TB.IRSwapsTB import IRSwapsTB
from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP
from TB.FixedRateBondsTB import FixedRateBondsTB
from Query.Unified.UnifiedQuery import UnifiedQuery
from Query.Unified.registry import UnifiedValue
from TB.TimeseriesBuilder import TimeseriesBuilder
from RVUtils.plt_timeseries import make_secondary_axis_plot
from RVUtils.regression import make_linear_regression_builder, rolling_beta_stability, residual_diagnostics
from RVUtils.carry_roll import make_carry_roll_builder, forward_rate
from RVUtils.screener_rv import make_rv_screener
from RVUtils.pca_rv import make_pca_rv_builder
from RVUtils.seasonality_utils import monthend_cumsum_seasonality

curve_mdp = IRSwapsMDP(source="ERIS_EOD_LIVE-RL_BASIC")
usts_mdp = FixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-RL")
ts = TimeseriesBuilder()
ROUTERS = {"IRS": IRSwapsTB(curve_mdp, show_tqdm=False), "FRB": FixedRateBondsTB(usts_mdp, show_tqdm=False)}
TEN = ["1y", "2y", "3y", "5y", "7y", "10y", "20y", "30y"]
YRS = {"1y": 1, "2y": 2, "3y": 3, "5y": 5, "7y": 7, "10y": 10, "20y": 20, "30y": 30}
INV = {v: k for k, v in YRS.items()}
bp = 100.0
start = NYC.localize(datetime.datetime(2021, 1, 1, 17, 0))
end = NYC.localize(datetime.datetime(2026, 6, 17, 17, 0))
df = ts.get_timeseries(start=start, end=end,
    queries=[UnifiedQuery(curve="USD-SOFR-1D", tenor=t, value=UnifiedValue.IRS_RATE) for t in TEN],
    n_jobs=8, routers=ROUTERS)
df = df.rename(columns={f"USD-SOFR-1D {t} OUTRIGHT RATE": t for t in TEN})[TEN]
df.index = pd.to_datetime(df.index)
curve_yrs = df.rename(columns=YRS)
r_1y1y = curve_yrs.apply(lambda row: forward_rate(row, 1, 1), axis=1)   # reds proxy (1y1y)
r_5y5y = curve_yrs.apply(lambda row: forward_rate(row, 5, 5), axis=1)   # 5y5y forward (nominal)
import urllib.request, io
def _fred(series, s="2021-01-01", e="2026-06-17"):
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}&cosd={s}&coed={e}"
    raw = urllib.request.urlopen(url, timeout=30).read().decode()
    d = pd.read_csv(io.StringIO(raw)); d.columns = ["date", series]
    d["date"] = pd.to_datetime(d["date"]); d = d.set_index("date")
    return pd.to_numeric(d[series], errors="coerce").dropna()
be5y5y = _fred("T5YIFR").reindex(df.index).ffill()        # 5y5y fwd breakeven inflation, %
walcl  = _fred("WALCL").reindex(df.index).ffill()         # Fed total assets, $mn (weekly, ffilled)
gdp    = _fred("GDP").reindex(df.index).ffill()           # nominal GDP, $bn (quarterly, ffilled)
bs_gdp = walcl / (gdp * 1000.0) * 100.0                   # Fed balance sheet as % of GDP
print("Loaded", df.shape, df.index.min().date(), "->", df.index.max().date())
print(f"1y1y {r_1y1y.iloc[-1]:.2f}% | 5y5y_BE {be5y5y.iloc[-1]:.2f}% | Fed BS/GDP {bs_gdp.iloc[-1]:.1f}%")
df.tail(3)'''

cells = [
    ("md", "# USD SOFR 10s30s Flattener — desk pitch (steelman)\n\n"
           "**One-line pitch.** Front end is a no-trade (guidance gone, distribution widened, SFR fly went directional — no edge). The one thing I'd put on is a **10s30s flattener**: it screens rich on the full **1y1y / 5y5y-breakeven / tariff / Fed-BS-%GDP** fair-value model (FRED-sourced, JPM's driver set), it's a **valuation + regime-convergence** trade (not a carry trade), and I chose 10s30s over 2s30s deliberately to keep it **clean of the front end I just said I won't trade**. It needs no directional call — it works on Warsh-credibility bull-flattening *and* on a front-led hawkish bear-flattening; the only thing that breaks it is a **30y-led term-premium / supply steepener**. Balance sheet is parked in a task force until the year-end review, so the ~3m window is clean.\n\n"
           "All analytics use `RVUtils`: `regression` (fair value + beta-stability TLI), `carry_roll` (forwards + carry/roll), `screener_rv` (cross-structure rank), `pca_rv` (factor exposure), `seasonality_utils`."),
    ("code", SETUP),
    ("code", 's10s30 = (df["30y"] - df["10y"]) * bp\n'
             's2s30 = (df["30y"] - df["2y"]) * bp\n'
             's2s10 = (df["10y"] - df["2y"]) * bp\n'
             'print("10s30s:", round(s10s30.iloc[-1], 1), "bp  (range 2021+:", round(s10s30.min(),0), "to", round(s10s30.max(),0), ")")\n'
             'print("2s30s :", round(s2s30.iloc[-1], 1), "bp")'),
    ("md", "## 1) Fair value — JPM's regressors, sourced from FRED\n"
           "10s30s regressed on JPM's named drivers: **1y1y OIS** (from the SOFR curve), **5y5y forward breakeven** (FRED `T5YIFR`), and **Fed balance sheet as % of GDP** (FRED `WALCL`/`GDP`). Residual > 0 ⇒ steeper than fair ⇒ **rich to flatten**. (JPM's tariff dummy is omitted — a persistent regime dummy mostly just absorbs the recent level and isn't cleanly replicable.)"),
    ("code", 'reg_df = pd.concat([s10s30.rename("10s30s"), r_1y1y.rename("1y1y"), be5y5y.rename("5y5y_BE"), bs_gdp.rename("BS/GDP")], axis=1).dropna()\n'
             'add_indep_var, fitr, pavp, prvp, prts, getd = make_linear_regression_builder(df=reg_df, y_col="10s30s")\n'
             'for d in ["1y1y", "5y5y_BE", "BS/GDP"]: add_indep_var(d)\n'
             'res = fitr(model="OLS", verbose=False)\n'
             'resid = res.resid\n'
             'z = (resid - resid.rolling(252).mean()) / resid.rolling(252).std()\n'
             'diag = residual_diagnostics(resid)\n'
             'print("R2", round(res.rsquared, 3), "| betas", {k: round(float(v),2) for k,v in res.params.items()})\n'
             'print("current residual", round(resid.iloc[-1], 1), "bp (>0 => steep vs model) | rolling z252", round(z.iloc[-1], 2), "| half-life", round(diag["half_life"],0), "d | ADF p", round(diag["adf_pvalue"], 3))\n'
             'prts(plot_zscores=True, plot_zero=True, stds=[1, 2], ou_bands=True)'),
    ("md", "**Beta-stability (the live regime gauge).** A Warsh regime re-rating would destabilise the betas; TLI ≥ 3 = stand down."),
    ("code", 'tli = rolling_beta_stability(s10s30, pd.concat([r_1y1y.rename("1y1y"), be5y5y.rename("5y5y_BE"), bs_gdp.rename("BS/GDP")], axis=1), window_beta=126, window_vol=63, window_z=126)\n'
             'plot, fig, ax, ax2, legend = make_secondary_axis_plot(engine="matplotlib", title="10s30s driver beta-stability TLI (>=3 = unstable / regime shift)")\n'
             'plot(s10s30.rename("10s30s (bp)"), which="left")\n'
             'plot(tli["TLI"].rename("TLI"), which="right", indicators=[{"kind": "last"}])\n'
             'legend(show_date=True, loc="upper left"); plt.show()'),
    ("md", "## 2) Signal vs carry — this is a convergence trade; the carry is the cheap bleed\n"
           "Carry+roll is **against** the flattener but small (negative = against). What matters is richness ÷ quarterly bleed."),
    ("code", 'roll_ts, carry_ts, total_ts, be_ts, ctv_ts, _ = make_carry_roll_builder(curve_yrs, horizon=0.25)\n'
             'def flattener_cr(a, b): return total_ts(("curve", a, b)) * bp   # DV01-neutral a/b flattener carry+roll, bp/3m (<0 = against)\n'
             'sig = abs(resid.iloc[-1])\n'
             'c10 = flattener_cr(10, 30).iloc[-1]; c2 = flattener_cr(2, 30).iloc[-1]\n'
             'print(f"10s30s: richness ~{sig:.1f}bp vs fair value | flattener carry+roll ~{c10:.2f}bp/q (<0 = against) | signal:carry ~{sig/abs(c10):.1f} : 1")\n'
             'print(f"2s30s : flattener carry+roll ~{c2:.2f}bp/q (worse, and reintroduces the 2y).")\n'
             'print("NB: this data-agnostic carry understates front-end carry; it ties out at the long end (10s30s ~-1.7bp = JPM table) but JPM shows 2s30s ~-5.7bp.")'),
    ("md", "## 3) PCA — a 10s30s flattener is mostly a slope (PC2) trade"),
    ("code", 'bpca = make_pca_rv_builder(df, on="changes", n_factors=3, sort_by_tenor=False)\n'
             'bpca[0]()\n'
             'risk_buckets = bpca[6]\n'
             'ladder = pd.Series(0.0, index=TEN); ladder["10y"] = 1.0; ladder["30y"] = -1.0   # DV01-neutral 10s30s flattener\n'
             'exp = risk_buckets(ladder)\n'
             'print("10s30s flattener PC exposures:", {k: round(float(v), 3) for k, v in exp.head(3).items()})'),
    ("md", "## 4) Screen long-end flatteners (incl 2s30s): carry + beta to 10s30s\n"
           "Candidates are spreads (steepener orientation, bp). `flat_carry_3m` is the **flattener** carry+roll (<0 = against); `beta_to_10s30s` (daily changes) confirms it moves with 10s30s. `level_z_own` is each spread's *own-history* z (mean-reversion lens) — distinct from the rich/cheap-vs-fair-value signal, which is the **regression residual in section 1**. Goal: improve the bleed while keeping 10s30s exposure, *without* re-adding the 2y."),
    ("code", 'cands = [(2,30),(3,30),(5,30),(7,30),(10,30),(10,20),(20,30),(7,20),(5,20)]\n'
             'structs, betas = {}, {}\n'
             'for a, b in cands:\n'
             '    name = f"{a}s{b}s"\n'
             '    sp = (df[INV[b]] - df[INV[a]]) * bp\n'
             '    structs[name] = sp\n'
             '    rd = pd.concat([sp.rename("sp"), s10s30.rename("x")], axis=1).dropna()\n'
             '    aiv, fiv, _, _, _, _ = make_linear_regression_builder(df=rd, y_col="sp", on_diff=True)\n'
             '    aiv("x"); rr = fiv(model="OLS"); betas[name] = float(rr.params["x"])\n'
             'build, rank, to_df, di_fn, _ = make_rv_screener(pd.DataFrame(structs), zscore_window=252, vol_window=63, percentile_window=252, halflife_window=252)\n'
             'tbl = to_df().copy().rename(columns={"zscore": "level_z_own"})\n'
             'tbl["beta_to_10s30s"] = pd.Series(betas)\n'
             'tbl["flat_carry_3m"] = pd.Series({f"{a}s{b}s": flattener_cr(a, b).iloc[-1] for a, b in cands})\n'
             'tbl[["level","level_z_own","percentile","vol","flat_carry_3m","half_life","beta_to_10s30s"]].sort_values("flat_carry_3m", ascending=False).round(2)'),
    ("md", "## 5) The pick — 10s30s is the clean expression; the screen quantifies the trade-off\n"
           "All long-end flatteners carry against you (small). Among those with real 10s30s beta, 10s30s itself is the cleanest (beta 1.0, ~-1.7bp/q). Longer-dated (e.g. 20s30s) bleeds a touch less but barely tracks 10s30s; the 30y-enders carry worse and/or re-add the front end."),
    ("code", 'best_alt = tbl[tbl["beta_to_10s30s"] > 0.6].sort_values("flat_carry_3m", ascending=False)\n'
             'print("Clean expression = 10s30s | flattener carry+roll", round(flattener_cr(10,30).iloc[-1],2), "bp/q | beta 1.0 | half-life", round(tbl.loc["10s30s","half_life"],0), "d")\n'
             'print("Best-carry alt (beta>0.6 to 10s30s):", best_alt.index[0], "-> carry", round(best_alt.iloc[0]["flat_carry_3m"],2), "bp/q, beta", round(best_alt.iloc[0]["beta_to_10s30s"],2))\n'
             'sp = s10s30\n'
             'zsp = (sp - sp.rolling(252).mean()) / sp.rolling(252).std()\n'
             'plot, fig, ax, ax2, legend = make_secondary_axis_plot(engine="matplotlib", title="10s30s spread (bp), own-history z, entry/stop bands")\n'
             'plot(sp.rename("10s30s (bp)"), which="left", indicators=[{"kind": "last"}])\n'
             'plot(zsp.rename("z252 (own history)"), which="right", indicators=[{"kind": "zbands", "entry": 1.5, "stop": 3}, {"kind": "last"}])\n'
             'legend(show_date=True, loc="upper left"); plt.show()'),
    ("md", "## 6) Seasonality — *context only* (small N); the real driver is the credibility mechanism\n"
           "The 'curve flattens into a new chair' leg is weak as an n≈5 seasonal and the first-meeting 2y selloff (~6bp, Citi) is already realised (6/17). The durable mechanism is: a credibly hawkish chair compresses **long-end inflation premium** → flatten. Charts below for completeness (use `seasonality_utils`)."),
    ("code", 'seas = monthend_cumsum_seasonality(s10s30.to_frame("10s30s"), value_col="10s30s", window=5, metric="abs")\n'
             'fig, axx = plt.subplots(figsize=(13, 6))\n'
             'for col in ["avg", "avg-jun", "avg-jul", "avg-aug"]:\n'
             '    if col in seas.columns: axx.plot(seas.index, seas[col], marker=".", label=col)\n'
             'axx.axvline(0, color="grey", ls=":"); axx.axhline(0, color="grey", ls=":")\n'
             'axx.set_xlabel("business days from month-end"); axx.set_ylabel("cum change 10s30s (bp)")\n'
             'axx.set_title("10s30s seasonality around month-end, by month (down = flattening)"); axx.legend(); plt.show()'),
    ("code", 'mc = s10s30.resample("ME").last().diff()\n'
             'by_month = mc.groupby(mc.index.month).agg(["mean", "median", "count"])\n'
             'by_month.index = ["jan","feb","mar","apr","may","jun","jul","aug","sep","oct","nov","dec"]\n'
             'print("Avg month-over-month change in 10s30s by calendar month (bp; negative = flattening):")\n'
             'by_month.round(1)'),
    ("md", "## Takeaways for the desk\n"
           "- **Front end = no trade, and lead with it.** Guidance gone, statement shortest in decades, 2026 median dot up to 3.8%, ~half the Committee penciling hikes, FedWatch ~60% Oct hike, SFR fly directional. No edge → don't force it. That selectivity is *why* the one trade I do pitch is credible.\n"
           "- **The trade = 10s30s flattener as a valuation+regime convergence trade**, not a carry trade. On JPM's named drivers (1y1y / 5y5y-BE / Fed-BS/%GDP, FRED-sourced) the model fits R² ~0.9 and screens 10s30s rich (residual in §1), corroborating the direction of JPM's ~14bp screen. Carry is ~1.7bp/q against — cheap relative to the convergence. (Summer-carry rationale dropped.)\n"
           "- **Why 10s30s not 2s30s:** similar standardized richness, but 2s30s carries worse and re-adds the 2y front-end I have no edge in. The front-end discipline *is* the reason for the expression.\n"
           "- **No directional call needed:** wins on Warsh-credibility bull-flatten or a front-led hawkish bear-flatten. **Single underwrite = the next shock is not a 30y-led term-premium/supply cheapening.** That is also the squeeze risk if the flattener is crowded.\n"
           "- **Calendar:** balance sheet parked to year-end task force (3m window clean). Real dates: **Aug 5 QRA** (if they pull 'at least', expect a steepening knee-jerk = stop test) and the **30y auctions (~Jul 9, ~Aug 13)** as the demand tell on the leg you're long (June 30y was soft; June 20y stopped 1bp through). Supply *quantity* is regular cadence, already in forwards; 20s/30s sizes frozen.\n"
           "- **Pre-empt 'it's the house trade / crowded':** that's valuation corroboration, but check CFTC / desk flow — if flattener positioning is one-sided, the pain trade is exactly the 30y-led steepener. Size as value-convergence, not conviction macro.\n"
           "- **Risk monitors:** beta-stability TLI (regime), realized CPI/PCE (4.2%/3.8% — credibility asserted, not yet in data; if inflation doesn't cooperate the bull-flatten channel flips to a term-premium steepener = stop), and the 30y auction tone."),
]

nb = new_notebook()
nb.cells = [new_markdown_cell(s) if t == "md" else new_code_cell(s) for t, s in cells]
nb.metadata = {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}}
path = os.path.join(OUT, "rv_10s30s_flattener_pitch.ipynb")
with open(path, "w", encoding="utf-8") as f:
    nbf.write(nb, f)
print("wrote", os.path.normpath(path), f"({len(cells)} cells)")
