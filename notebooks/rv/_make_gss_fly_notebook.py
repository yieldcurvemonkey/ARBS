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

# Required, not decorative. `FixedRateBondsMDP._get_multi_pricers` falls back to
# `WSJFetcher.ust_intraday_timeseries` for any CUSIP FedInvest has not published, and that fetcher
# calls `asyncio.run()` — which raises "cannot be called from a running event loop" inside a Jupyter
# kernel. The fallback is reachable on ANY date (coverage is per-CUSIP, not per-day), so pinning
# `as_of` to an older date does not avoid it.
import nest_asyncio
nest_asyncio.apply()

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
    load_repo_from_workbook, resolve_repo_curve, repo_tag_grid,
)
from BT.gss_fly.backtest import run_gss_backtest
from BT.gss_fly.data import citi_curve_quotes, ust_business_days

usts_mdp = FixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-QL")
tb = TimeseriesBuilder(fixedratebonds_tb=FixedRateBondsTB(usts_mdp))

cfg = GSSConfig()
print(cfg.describe())
""")

md(r"""
## 1. The curve, and the spline the richness is measured against

**The spline is fitted on Citi Velocity's own yields**, pulled through the CVSNAP path
(`citi_curve_quotes`). Three reasons this is the better input, all measured rather than assumed:

* **It is the vendor's own mark, not a re-derivation.** Citi publishes `YIELD` per ISIN; the
  alternative re-solves a yield from a FedInvest clean price through QuantLib, adding a second
  place for conventions to disagree. Where both work they agree to **0.60bp median, 1.04bp p95**.
* **The FedInvest path is not reliable on recent dates.** Running the previous version of this cell
  unchanged: 2025-06-16, 2025-11-14 and 2026-01-02 give 290/291/292 sane yields out of 290/291/292,
  but **2026-07-10 gives 0 of 295** and **2026-08-07 gives 7 of 295** — medians of 1172 and 1433
  percent. Nothing raises; the spline just fits to noise. (The backtest range ends 2026-01-02 and is
  unaffected, which is why the port's numbers stand.)
* **It runs offline.** No Excel, no add-in, no sign-in — `citi_curve_quotes` resolves from the
  Velocity disk cache. It reads the wire only when the cache is cold.

`citi_curve_quotes` returns `(frame, report)` and the report is worth reading every time: it names
every bond dropped and why, because on this data what fell out is usually the interesting part.
""")

code(r"""
as_of = datetime.date(2026, 8, 7)

ref_df = (
    usts_mdp.get_bond_reference_data(as_of_date=as_of)
    .drop(columns=["record_date"])
    .rename(columns={"label": "ust_label"})
)
ref_df = ref_df[ref_df["ttm"] >= 1]

# Citi's own yields. `exclude_ranks` drops the on-the-runs, matching the backtest universe: their
# specialness in repo is not priced by a GC hurdle, so a rich OTR is not a tradeable richness.
# Note the fit set and the DISPLAY set differ deliberately — the OTRs are plotted, just not fitted.
market_df, snap_report = citi_curve_quotes(
    pd.Timestamp(as_of), ref_df, exclude_ranks=(), values=("YIELD", "PRICE", "DURATION"),
)
fit_df, fit_report = citi_curve_quotes(
    pd.Timestamp(as_of), ref_df, exclude_ranks=(0, 1, 2), values=("YIELD",),
)
market_df = market_df.rename(columns={"yield": "ytm", "duration": "mdur"})

for k, v in fit_report.items():
    print(f"  {k:22s} {v}")

# The spline build from usts_rv.ipynb — same knots, same call, Citi's yields underneath.
ytm_bspline = GeneralCurveInterpolator(x=fit_df["ttm"].to_list(), y=fit_df["yield"].to_list()) \
    .b_spline_with_knots_interpolation(knots=[2, 3, 5, 7, 10, 20, 25], k=3, return_func=True)
ytm_loess = GeneralCurveInterpolator(x=fit_df["ttm"].to_list(), y=fit_df["yield"].to_list()) \
    .loess_interpolation(frac=0.15, it=50, delta=0, return_func=True)

plot_usts(
    curve_set_df=market_df,
    ttm_col="ttm",
    ytm_col="ytm",
    label_col="oi",
    cusip_col="cusip",
    hover_data=[c for c in ("ust_label", "cpn", "rank", "maturity_date", "mdur") if c in market_df.columns],
    splines=[(ytm_bspline, "BSpline", "red"), (ytm_loess, "LOESS", "orange")],
    title=f"UST complex and the fitted curve — {as_of} (Citi Velocity)",
)
""")

md(r"""
### 1.0 The two vendors against each other

The check that makes the swap verifiable rather than an act of faith. FedInvest clean prices are
re-solved to yield through QuantLib and differenced against Citi's published yield, bond by bond.

Read the **count** first, not the spread: `sane` below is how many FedInvest yields land in a
believable band at all. When that number collapses, the difference column is meaningless and the
FedInvest curve for that date is the broken one.
""")

code(r"""
fed = usts_mdp.get_pricer(request=dict(cusips=fit_df["cusip"].astype(str).to_list(),
                                       timestamp=as_of, show_tqdm=False))
rows = []
for c, p in fed.items():
    try:
        rows.append({"cusip": c, "fed_ytm": p.ytm()})
    except Exception:
        pass                                     # a bill QuantLib cannot bracket is not a finding
fed_df = pd.DataFrame(rows)
cmp_df = fit_df[["cusip", "ttm", "yield"]].merge(fed_df, on="cusip", how="inner")
sane = cmp_df[cmp_df["fed_ytm"].between(0.0, 20.0)]
print(f"matched {len(cmp_df)} bonds; FedInvest yields in a believable band: {len(sane)}")

if len(sane) < 0.5 * len(cmp_df):
    print(f"\n  >>> FedInvest is UNUSABLE on {as_of}: only {len(sane)} of {len(cmp_df)} yields are")
    print("  >>> believable. The Citi curve above stands; a FedInvest-fitted curve for this date")
    print("  >>> would be noise, and nothing in that path raises to tell you so.")
else:
    d_bp = (sane["yield"] - sane["fed_ytm"]) * 100.0
    print(f"  median |Citi - FedInvest|  {d_bp.abs().median():.3f} bp")
    print(f"  p95    |Citi - FedInvest|  {d_bp.abs().quantile(.95):.3f} bp")
    print(f"  mean signed                {d_bp.mean():+.3f} bp")
""")

md(r"""
### 1.1 The same curve a month earlier

`plot_usts_comparison` overlays two dates on one colour map, which is how a dislocation that has
*persisted* is told from one that has just appeared — the entry gate cares about the difference.
""")

code(r"""
# NOT `as_of - timedelta(days=30)` on its own: that landed on Sunday 2026-07-12, no snapshot exists
# for it, every one of the 295 pricers failed, and the empty frame then died in a merge with
# `KeyError: 'cusip'` — a calendar bug wearing a pandas error. Snap back to the last UST trading day
# on or before the target. Same landmine as `pd.bdate_range` vs `ust_business_days`.
_target = as_of - datetime.timedelta(days=30)
compare = ust_business_days(_target - datetime.timedelta(days=10), _target)[-1]

old_ref = (
    usts_mdp.get_bond_reference_data(as_of_date=compare)
    .drop(columns=["record_date"]).rename(columns={"label": "ust_label"})
)
old_ref = old_ref[old_ref["ttm"] >= 1]

# Same Citi path as `as_of`. This window currently resolves to 2026-07-08, a week before the dates
# on which Citi published an impossible -0.679% for the May-2046 bond (07-14/15) — and the window
# MOVES with `as_of`, so it can land on them. `citi_curve_quotes` reports anything it drops, which
# is why the drop count is printed here rather than being bent silently into the curve.
old_market, _ = citi_curve_quotes(pd.Timestamp(compare), old_ref, exclude_ranks=(),
                                  values=("YIELD", "PRICE"))
old_fit, old_report = citi_curve_quotes(pd.Timestamp(compare), old_ref, exclude_ranks=(0, 1, 2),
                                        values=("YIELD",))
old_market = old_market.rename(columns={"yield": "ytm"})
print(f"{compare}: {old_report['fittable']} fittable, "
      f"dropped {old_report['band_dropped']} out-of-band + {old_report['outlier_dropped']} outlier "
      f"{old_report['band_cusips'] + old_report['outlier_cusips']}")

old_bspline = GeneralCurveInterpolator(
    x=old_fit["ttm"].to_list(), y=old_fit["yield"].to_list(),
).b_spline_with_knots_interpolation(knots=[2, 3, 5, 7, 10, 20, 25], k=3, return_func=True)

_hover = [c for c in ("ust_label", "cpn", "rank", "maturity_date") if c in old_market.columns]
fig, cmap = plot_usts_comparison(
    curve_set_df=old_market, ttm_col="ttm", ytm_col="ytm", label_col="oi", cusip_col="cusip",
    hover_data=_hover, splines=[(old_bspline, "BSpline", "lightcoral")],
    opacity=0.45, name_suffix=str(compare), show=False, return_color_map=True,
)
plot_usts_comparison(
    curve_set_df=market_df, ttm_col="ttm", ytm_col="ytm", label_col="oi", cusip_col="cusip",
    hover_data=_hover, splines=[(ytm_bspline, "BSpline", "red")],
    title=f"UST complex: {compare} vs {as_of} (Citi Velocity)",
    fig=fig, opacity=1.0, name_suffix=str(as_of), color_discrete_map=cmap, show=True,
)
""")

md(r"""
## 2. The curveset at an instant — CVSNAP, and what needs the bridge

Section 1 already used this path, and used it **offline**. That is worth stating plainly, because
until recently this cell reported *"CVSNAP unavailable — run with Excel signed in"* on every run and
the reason was never Excel: `fetch_curveset_snapshot` was building its tags from **CUSIPs** while
Citi keys bonds by the 12-character **ISIN**, so it asked for `RATES.BOND.912810EX2.YIELD` against a
wire that answers to `RATES.BOND.US912810EX29.YIELD`. Nothing matched, and the `except` blamed the
bridge. A key-format bug read as a missing spreadsheet.

So the honest split is per **value**, not per section:

* `YIELD` and `PRICE` are warmed for the UST complex and resolve **from disk** — this is what the
  curve in section 1 is fitted on, and it needs no Excel at all;
* the richer analytics (`ASW`, `ZSPREAD`, `DV01`, `DURATION`) are warmed for far fewer bonds, so
  asking for them generally **does** go to the wire, and the wire needs a human-authenticated Excel
  with the Velocity add-in signed in. It cannot spawn one; a spawned instance never registers the
  `CV*` UDFs.

The guard still matters more than the call. Citi resolves **as-of**, so a request for an instant the
wire never published silently returns an earlier one. Every snapshot carries the stamp it actually
resolved to, and a resolution staler than the tolerance is refused rather than quietly served.
""")

code(r"""
from BT.gss_fly import fetch_curveset_snapshot, warm_bond_snapshots, BOND_SNAPSHOT_VALUES

snap_when = pd.Timestamp(f"{as_of} 15:00:00")

# The cached values, so this resolves offline like section 1 did.
snap = fetch_curveset_snapshot(
    snap_when,
    reference=ref_df.head(60),
    values=("YIELD", "PRICE"),
    max_staleness=datetime.timedelta(days=1),
    strict=True,
)
print(f"offline: resolved {len(snap)} bonds at {snap['snap_stamp'].iloc[0]} (requested {snap_when})")
display(snap[["isin", "cusip", "yield", "price", "ttm", "rank"]].head(12))

# The full value set, which normally needs the bridge. Reported rather than raised — its absence is
# a statement about this machine, not about the code.
try:
    rich = fetch_curveset_snapshot(
        snap_when, reference=ref_df.head(60), values=BOND_SNAPSHOT_VALUES,
        max_staleness=datetime.timedelta(days=1), strict=True,
    )
    print(f"\nwith analytics: {len(rich)} bonds, columns {sorted(rich.columns)}")
except Exception as exc:
    print(f"\nanalytics ({', '.join(BOND_SNAPSHOT_VALUES)}) need the Excel bridge: {type(exc).__name__}")
    print("Warm them once with warm_bond_snapshots below and they resolve from disk thereafter.")

# Cache warm — pull the history once so later snapshots resolve from disk rather than the wire.
# warm_bond_snapshots(ref_df["cusip"].tolist(), start="2024-01-01", end=str(as_of))
""")

md("## 3. The panel, the signal, and the flies")

code(r"""
from pathlib import Path

PANEL_CACHE = Path("../data/gss_fly/panel_2024_2026")   # built once, reused thereafter

# `end` is PINNED, and deliberately not `as_of`. The panel below fits on FedInvest, and FedInvest
# serves unusable yields on some dates after this boundary — 0 of 295 believable on 2026-07-10, 7 of
# 295 on 2026-08-07 (see section 1.0). Running to `as_of` pulled those in and the book reported an
# entry signal of **323,332bp**, which is what corruption looks like once it reaches a z-score.
# 2026-01-02 is the last date verified clean and is the range every published GSS number uses.
start, end = datetime.date(2024, 9, 2), datetime.date(2026, 1, 2)

# NOT `pd.bdate_range`: that yields weekdays, which includes market holidays. The source never
# serves a holiday and its fetcher HANGS rather than refusing, so one Labor Day is enough to stall
# the whole build — this is the landmine `ust_business_days` was written for, and this cell was
# still stepping on it.
days = ust_business_days(start, end)

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

# `resolve_repo_curve` returns the basis as well as the curve, and prints it either way. There is
# NO flat-rate fallback: `CostConfig.fallback_repo_pct` is declared and read by nothing (it is one
# of the harness's planted nulls, pinned dead in tests/gss_fly/test_conditioning.py). Without a
# workbook the run is simply UNFINANCED — carry is not charged at all — so `basis` has to be
# carried into every number below rather than assumed.
repo, basis = resolve_repo_curve(REPO_XLSX, collateral="USTREASGC")
if repo is not None:
    display(repo.frame.tail(5)[["ON", "1W", "1M", "3M", "1Y"]])
    # The OTR specials are why the universe drops rank 0: a 10y OTR finances well below GC.
    otr = load_repo_from_workbook(REPO_XLSX, collateral="USD10YOTR")
    spread = (repo.frame["ON"] - otr.frame["ON"]).dropna()
    print(f"\n10y OTR special vs GC, overnight: median {spread.median()*100:.1f}bp, "
          f"max {spread.max()*100:.1f}bp over {len(spread)} days")
else:
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
                  title=f"GSS UST butterfly book — {len(eq)} marked days [{basis}]",
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
