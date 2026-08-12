"""Generate notebooks/rv/gss_fly_rv.ipynb — the GSS cash-bond butterfly book on UST."""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "gss_fly_rv.ipynb"
cells: list = []


def _lines(src):
    return src.strip("\n").splitlines(keepends=True)


def md(src):
    cells.append({"cell_type": "markdown", "id": f"md{len(cells):02d}", "metadata": {}, "source": _lines(src)})


def code(src):
    cells.append(
        {"cell_type": "code", "id": f"cd{len(cells):02d}", "execution_count": None,
         "metadata": {}, "outputs": [], "source": _lines(src)}
    )


md(r"""
# GSS cash-bond butterfly — UST

A port of the GSS curve-fitting RV process onto US Treasuries, running on ARBS's
`QueryDrivenBacktest`.

**What the strategy is.** Fit a curve across the coupon complex; a bond's *yield error* against
that curve is its richness. Blend a time-series score (rich versus its own history) with a
cross-sectional score (rich versus its peers today). Rank every eligible bond by |richness|, and
for each one as a **belly**, pick the wings inside a maturity window that maximise the richness
gap. Weight by maturity — belly `+1`, wings summing to `-1`, so the fly is maturity-neutral and
explicitly *not* DV01-neutral. Sign the whole thing by the fly's own z so the position always
faces mean reversion. Enter when the vol-scaled signal `ZSig = |z|·σ_fly` exceeds a basis-point
threshold **and** |z| has already begun to shrink; exit when `ZSig` decays below the repo hurdle.

**Why UST and not EGB.** The original ran on eleven European sovereign curves. ARBS has no non-US
bond reference data and no validated Citi tags for non-US ISINs, so the universe is re-targeted.
Everything else is the original's.

**Three deliberate deviations from the source**, each a config knob, each visible below:

1. `wing_selection` in the original maximises `|Signal_wing − belly.TimeToMaturity|` — it subtracts
   a maturity *in years* from a *z-score*. Almost certainly a typo for `Signal_belly`. The default
   here is the corrected objective; `legacy_ttm_bug` reproduces the original.
2. The original charges its bid/offer on **the belly only** and says so. That flatters a
   three-legged trade, so the default charges all three legs weighted by |w|.
3. Repo is not the original's flat `-(r/360)·days`. ARBS's `FinancedFixedRateBondHandler` already
   prices financing per leg from a GC curve plus per-leg specialness on ACT/360, so the book hands
   it the curve and lets the engine do it.
""")

code(r"""
%load_ext autoreload
%autoreload 2

import os
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import sys, datetime, logging
sys.path.append("../../")

import numpy as np
import pandas as pd

import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio
pio.renderers.default = "vscode"

import matplotlib.pyplot as plt
import matplotlib.pylab as pylab
plt.style.use("seaborn-v0_8-dark")
pylab.rcParams.update({"figure.figsize": (20, 8), "axes.titlesize": "x-large", "axes.labelsize": "large"})

import warnings
warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.ERROR)

from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP
from Query.FixedRateBonds.FixedRateBondQuery import FixedRateBondQuery
from Query.FixedRateBonds.FixedRateBondValue import FixedRateBondValue
from TB.FixedRateBondsTB import FixedRateBondsTB
from TB.TimeseriesBuilder import TimeseriesBuilder

from RVUtils.Interpolation.GeneralCurveInterpolator import GeneralCurveInterpolator
from RVUtils.ust_viz import plot_usts, plot_usts_comparison
from RVUtils.plt_timeseries import make_secondary_axis_plot

from BT.gss_fly import (
    GSSConfig, FlyConfig, CostConfig, BacktestConfig,
    build_curve_panel, build_bond_signals, apply_universe_filter,
    scan_flies, select_wings, build_weights, fly_tcost_bp,
    load_repo_from_workbook, repo_tag_grid,
)
from BT.gss_fly.backtest import run_gss_backtest

usts_mdp = FixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-QL")
tb = TimeseriesBuilder(fixedratebonds_tb=FixedRateBondsTB(usts_mdp))

cfg = GSSConfig()
print(cfg.describe())
""")

md("## 1. The curve, and the spline the richness is measured against")

code(r"""
as_of = datetime.date(2026, 8, 11)

ref_df = (
    usts_mdp.get_bond_reference_data(as_of_date=as_of)
    .drop(columns=["record_date"])
    .rename(columns={"label": "ust_label"})
)
ref_df = ref_df[ref_df["ttm"] >= 1]

pricers = usts_mdp.get_pricer(
    request=dict(cusips=ref_df["cusip"].to_list(),
                 timestamp="live" if as_of == datetime.date.today() else as_of,
                 show_tqdm=True)
)
ref_df["mdur"] = ref_df["cusip"].apply(lambda c: pricers[c].mod_duration() if c in pricers else np.nan)
market_df = pd.DataFrame([{"cusip": c, "ytm": p.ytm()} for c, p in pricers.items()]).merge(ref_df, on="cusip")

# The GSS universe excludes the on-the-runs: their specialness in repo is not priced by a GC
# hurdle, so a rich OTR is not a tradeable richness.
cusips_to_fit = ref_df[~ref_df["rank"].isin([0, 1, 2])]["cusip"].to_list()
ttm = [pricers[c].time_to_maturity() for c in cusips_to_fit if c in pricers]
ytm = [pricers[c].ytm() for c in cusips_to_fit if c in pricers]

# The spline build from usts_rv.ipynb, unchanged.
ytm_bspline = GeneralCurveInterpolator(x=ttm, y=ytm).b_spline_with_knots_interpolation(
    knots=[2, 3, 5, 7, 10, 20, 25], k=3, return_func=True
)
ytm_loess = GeneralCurveInterpolator(x=ttm, y=ytm).loess_interpolation(frac=0.15, it=50, delta=0, return_func=True)

plot_usts(
    curve_set_df=market_df,
    ttm_col="ttm",
    ytm_col="ytm",
    label_col="oi",
    cusip_col="cusip",
    hover_data=ref_df.columns.to_list(),
    splines=[(ytm_bspline, "BSpline", "red"), (ytm_loess, "LOESS", "orange")],
    title=f"UST complex and the fitted curve — {as_of}",
)
""")

md(r"""
### 1.1 The same curve a month earlier

`plot_usts_comparison` overlays two dates on one colour map, which is how a dislocation that has
*persisted* is told from one that has just appeared — the entry gate cares about the difference.
""")

code(r"""
compare = as_of - datetime.timedelta(days=30)

old_ref = (
    usts_mdp.get_bond_reference_data(as_of_date=compare)
    .drop(columns=["record_date"]).rename(columns={"label": "ust_label"})
)
old_ref = old_ref[old_ref["ttm"] >= 1]
old_pricers = usts_mdp.get_pricer(request=dict(cusips=old_ref["cusip"].to_list(), timestamp=compare, show_tqdm=True))
old_market = pd.DataFrame([{"cusip": c, "ytm": p.ytm()} for c, p in old_pricers.items()]).merge(old_ref, on="cusip")

old_fit = old_ref[~old_ref["rank"].isin([0, 1, 2])]["cusip"].to_list()
old_bspline = GeneralCurveInterpolator(
    x=[old_pricers[c].time_to_maturity() for c in old_fit if c in old_pricers],
    y=[old_pricers[c].ytm() for c in old_fit if c in old_pricers],
).b_spline_with_knots_interpolation(knots=[2, 3, 5, 7, 10, 20, 25], k=3, return_func=True)

fig, cmap = plot_usts_comparison(
    curve_set_df=old_market, ttm_col="ttm", ytm_col="ytm", label_col="oi", cusip_col="cusip",
    hover_data=old_ref.columns.to_list(), splines=[(old_bspline, "BSpline", "lightcoral")],
    opacity=0.45, name_suffix=str(compare), show=False, return_color_map=True,
)
plot_usts_comparison(
    curve_set_df=market_df, ttm_col="ttm", ytm_col="ytm", label_col="oi", cusip_col="cusip",
    hover_data=ref_df.columns.to_list(), splines=[(ytm_bspline, "BSpline", "red")],
    title=f"UST complex: {compare} vs {as_of}",
    fig=fig, opacity=1.0, name_suffix=str(as_of), color_discrete_map=cmap, show=True,
)
""")

md(r"""
## 2. The curveset at an instant — CVSNAP

`build_curve_panel` marks on the FedInvest/WSJ close, which is what the backtest wants. When the
question is instead *what did the whole complex look like at 10:35 on the day of the auction*,
that is a snapshot, and it comes from Citi Velocity's `CVSNAP`.

The guard matters more than the call. Citi resolves **as-of**, so a request for an instant the
wire never published silently returns an earlier one. `fetch_curveset_snapshot` attaches the stamp
it actually resolved to and refuses a resolution staler than the tolerance.

This needs a signed-in Excel with the Velocity add-in; the cell reports and moves on if not.
""")

code(r"""
from BT.gss_fly import fetch_curveset_snapshot, warm_bond_snapshots, BOND_SNAPSHOT_VALUES

snap_when = pd.Timestamp(f"{as_of} 15:00:00")
try:
    snap = fetch_curveset_snapshot(
        snap_when,
        reference=ref_df.head(60),          # widen once the warm below has been run
        values=BOND_SNAPSHOT_VALUES,
        max_staleness=datetime.timedelta(days=1),
        strict=True,
    )
    print(f"resolved {len(snap)} bonds at {snap['snap_stamp'].iloc[0]} (requested {snap_when})")
    display(snap[["isin", "yield", "price", "duration", "ttm", "oi"]].head(12))
except Exception as exc:
    print(f"CVSNAP unavailable: {type(exc).__name__}: {exc}")
    print("Run scripts/warm_citivelo_xccy_repo.py with Excel signed in, then retry.")

# Cache warm — pull the history once so later snapshots resolve from disk rather than the wire.
# warm_bond_snapshots(ref_df["cusip"].tolist(), start="2024-01-01", end=str(as_of))
""")

md("## 3. The panel, the signal, and the flies")

code(r"""
from pathlib import Path

PANEL_CACHE = Path("../data/gss_fly/panel_2024_2026")   # built once, reused thereafter
start, end = datetime.date(2024, 9, 2), as_of
days = [d.date() for d in pd.bdate_range(start, end)]

panel = build_curve_panel(days, usts_mdp, cache_path=PANEL_CACHE)
print(panel.summary())

sig = build_bond_signals(panel.s2c, cfg.signal)
print(f"signal: {sig['signal'].shape[1]} bonds x {sig['signal'].shape[0]} dates, "
      f"{int(sig['signal'].notna().sum().sum()):,} observations")
""")

code(r"""
asof = panel.dates[-1]
curve = panel.curve_on(asof)
curve["signal"] = sig["signal"].loc[asof].reindex(curve.index)
elig = apply_universe_filter(curve, cfg.universe)
print(f"{len(curve)} bonds -> {len(elig)} eligible "
      f"(coupon<{cfg.universe.max_coupon:g}, ttm>={cfg.universe.min_ttm:g}, "
      f"seasoning>={cfg.universe.min_seasoning_days:g}d, ex-OTR)")

flies = scan_flies(elig, s2c_panel=panel.s2c, yield_panel=panel.ytm, asof=asof, cfg=cfg.fly)
top = sorted(flies, key=lambda f: -f.zsig_bp)[:15]
display(pd.DataFrame([{
    "fly": f.fly_id, "z": round(f.z, 2), "sigma_bp": round(f.std_bp, 2),
    "ZSig_bp": round(f.zsig_bp, 2), "d|z|": round(f.d_abs_z, 3),
    "weights": [round(w, 3) for w in f.weights], "ttms": [round(t, 1) for t in f.ttms],
    "rt_cost_bp": round(2 * fly_tcost_bp(f.ttms, f.weights, cfg.costs), 3),
} for f in top]))
print(f"\nentry gate: ZSig > {cfg.backtest.entry_zsig_bp:g}bp AND d|z| < 0  "
      f"-> {sum(1 for f in flies if f.zsig_bp > cfg.backtest.entry_zsig_bp and f.d_abs_z < 0)} of {len(flies)} qualify")
""")

md(r"""
### 3.1 The wing-selection deviation, side by side

The corrected objective and the original's are run on the same curve. Where they disagree, the
original is picking the wing whose *signal* is furthest from the belly's *time to maturity* — a
comparison between two different quantities.
""")

code(r"""
rows = []
for belly in elig.dropna(subset=["signal"]).reindex(
        elig["signal"].abs().sort_values(ascending=False).index).dropna(subset=["signal"]).index[:12]:
    fixed = select_wings(elig, belly, FlyConfig(wing_objective="signal_gap"))
    legacy = select_wings(elig, belly, FlyConfig(wing_objective="legacy_ttm_bug"))
    if len(fixed) == 3 and len(legacy) == 3:
        rows.append({"belly": belly, "belly_ttm": round(elig.loc[belly, "ttm"], 1),
                     "signal_gap": "-".join(fixed), "legacy": "-".join(legacy),
                     "same": fixed == legacy})
cmp_df = pd.DataFrame(rows)
display(cmp_df)
print(f"the two objectives disagree on {int((~cmp_df['same']).sum())} of {len(cmp_df)} bellies")
""")

md("## 4. Repo — the hurdle the exit is measured against")

code(r"""
from pathlib import Path
REPO_XLSX = Path(r"C:/Users/chris/Downloads/gc_repo_hist_example.xlsx")
repo = None
if REPO_XLSX.exists():
    repo = load_repo_from_workbook(REPO_XLSX, collateral="USTREASGC")
    print(repo)
    display(repo.frame.tail(5)[["ON", "1W", "1M", "3M", "1Y"]])
    # The OTR specials are why the universe drops rank 0: a 10y OTR finances well below GC.
    otr = load_repo_from_workbook(REPO_XLSX, collateral="USD10YOTR")
    spread = (repo.frame["ON"] - otr.frame["ON"]).dropna()
    print(f"\n10y OTR special vs GC, overnight: median {spread.median()*100:.1f}bp, "
          f"max {spread.max()*100:.1f}bp over {len(spread)} days")
else:
    print(f"{REPO_XLSX} not found — the book will fall back to a flat GC rate.")
    print("Online path: scripts/warm_citivelo_xccy_repo.py --what repo")
print("\nrepo tag grid:", repo_tag_grid()[:4], "...", len(repo_tag_grid()), "tags")
""")

md("## 5. The backtest — QueryDrivenBacktest")

code(r"""
res = run_gss_backtest(
    panel, usts_mdp,
    cfg=cfg,
    repo_curve=repo,
    repo_tenor="ON",
    leg_specialness_bps={"belly": 0.0, "front": 0.0, "back": 0.0},
    show_progress=True,
)
print("diagnostics:", res.diagnostics)
print()
for k, v in res.summary().items():
    print(f"  {k:22s} {v}")
""")

code(r"""
eq = res.equity
fig = go.Figure()
fig.add_trace(go.Scatter(x=eq.index, y=eq.values, mode="lines", name="account value",
                         line=dict(color="#2F4B7C", width=2)))
fig.add_hline(y=0, line_dash="dash", line_color="grey")
fig.update_layout(template="plotly_dark", height=520,
                  title=f"GSS UST butterfly book — {len(eq)} marked days, net of costs and repo",
                  xaxis_title="", yaxis_title="USD")
fig.show()

if not res.closed.empty:
    c = res.closed.copy()
    p = c["realized_pnl"].astype(float)
    fig2 = go.Figure(go.Bar(x=pd.to_datetime(c["closed_at"]), y=p,
                            marker_color=["#2ca02c" if v > 0 else "#d62728" for v in p]))
    fig2.add_hline(y=0, line_color="white", line_dash="dash", opacity=0.5)
    fig2.update_layout(template="plotly_dark", height=380, title="Realised P&L per closed fly",
                       yaxis_title="USD")
    fig2.show()
    display(c[["opened_at", "closed_at", "holding_period_days", "realized_pnl",
               "gross_realized_pnl", "fee_allocated"]].head(15))
""")

md(r"""
### 5.1 The trade log, and what the gates actually did

Every entry and exit the signal engine emitted, with the state that triggered it. The exit reason
is the interesting column: `zsig_below_repo` is the position decaying into the financing hurdle,
`z_rollover` is it turning back through the band.
""")

code(r"""
log = res.trade_log
if not log.empty:
    display(log.tail(20))
    print("\nby event:"); display(log.groupby("event").size().to_frame("n"))
    ex = log[log["event"] == "EXIT"]
    if not ex.empty:
        print("by exit reason:")
        display(ex.groupby("reason").agg(n=("reason", "size"), median_held=("held_days", "median")))
    en = log[log["event"] == "ENTER"]
    if not en.empty:
        print(f"entry ZSig: median {en['zsig_bp'].median():.2f}bp, max {en['zsig_bp'].max():.2f}bp")
""")

md(r"""
## 6. Timeseries — the fly, and the spline behind it

`FixedRateBondQuery` takes a slash-joined package, so a butterfly is a first-class timeseries
object. `SPLINE_SPREAD` is the same per-bond yield error the signal is built on, which means the
signal can be read straight off the same machinery that trades it.
""")

code(r"""
if not res.trade_log.empty and (res.trade_log["event"] == "ENTER").any():
    best = res.trade_log[res.trade_log["event"] == "ENTER"].sort_values("zsig_bp").iloc[-1]
    legs = best["fly_id"].split("-")
    ts_start, ts_end = start, end

    q_fly = FixedRateBondQuery(cusip="/".join(legs), value=FixedRateBondValue.YTM)
    q_belly = FixedRateBondQuery(cusip=legs[1], value=FixedRateBondValue.SPLINE_SPREAD)

    df = tb.get_timeseries(start=ts_start, end=ts_end, queries=[q_fly, q_belly],
                           n_jobs=8, drop_multilevel_cols=True)
    print(f"fly {best['fly_id']} entered {best['date']} at ZSig {best['zsig_bp']:.2f}bp")

    plot, fig, ax, ax2, legend = make_secondary_axis_plot()
    plot(df[df.columns[0]], which="left", indicators=[
        {"kind": "last", "show_date": True, "style": {"linestyle": "--", "color": "tab:purple"}},
        {"kind": "simple_avg", "label": "mean", "style": {"linestyle": "--", "color": "red"}},
        {"kind": "half_life", "method": "ou", "demean": True, "hide": True},
    ])
    if len(df.columns) > 1:
        plot(df[df.columns[1]], which="right")
    legend(); plt.show()
else:
    print("no entries in this window — nothing to plot")
""")

md(r"""
## 7. Verdict

The questions worth asking of this book, in the order they kill it:

1. **Does it trade at all?** `run_gss_backtest` asserts it does; a flat equity curve from a book
   that never entered is the failure mode this strategy is most prone to, because the entry gate
   is a product of two things that are each rarely large.
2. **Does the vol-scaled signal clear the round trip?** `ZSig` at entry against `rt_cost_bp` in the
   candidate table is the whole economic argument. If the median entry `ZSig` is not comfortably
   above the round trip, the rest is noise.
3. **Does the cost assumption carry the result?** Re-run with `CostConfig(cost_legs="belly_only")`
   — the original's rule. If the verdict flips, the strategy is an artefact of charging two legs
   at zero.
4. **Does the wing-selection fix matter?** Re-run with `FlyConfig(wing_objective="legacy_ttm_bug")`.
   A result that only survives under the typo is not a result.
""")

code(r"""
variants = {
    "default (all legs, fixed wings)": cfg,
    "belly-only costs (the original's rule)": GSSConfig(costs=CostConfig(cost_legs="belly_only")),
    "legacy wing objective (the typo)": GSSConfig(fly=FlyConfig(wing_objective="legacy_ttm_bug")),
}
rows = []
for name, c in variants.items():
    try:
        r = run_gss_backtest(panel, usts_mdp, cfg=c, repo_curve=repo, show_progress=False, strict=False)
        s = r.summary()
        rows.append({"variant": name, **{k: s.get(k) for k in
                     ("closed_trades", "end_equity_usd", "net_realized_usd", "avg_per_trade_usd",
                      "hit_rate", "median_hold_days")}})
    except Exception as exc:
        rows.append({"variant": name, "closed_trades": f"FAILED: {type(exc).__name__}"})
display(pd.DataFrame(rows).set_index("variant"))
""")

nb = {
    "cells": cells,
    "metadata": {
        "kernelspec": {"display_name": "stir", "language": "python", "name": "python3"},
        "language_info": {"name": "python", "version": "3.12"},
    },
    "nbformat": 4,
    "nbformat_minor": 5,
}
OUT.write_text(json.dumps(nb, indent=1), encoding="utf-8")
print(f"wrote {OUT}  ({len(cells)} cells)")
