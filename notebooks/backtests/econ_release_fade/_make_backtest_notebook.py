"""Generate econ_release_fade_backtest.ipynb -- one dict describes one backtest."""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "econ_release_fade_backtest.ipynb"
REPO = str(HERE.parent.parent.parent)
cells: list = []


def _lines(src): return src.strip("\n").splitlines(keepends=True)
def md(src): cells.append({"cell_type": "markdown", "id": f"md{len(cells):02d}", "metadata": {}, "source": _lines(src)})
def code(src): cells.append({"cell_type": "code", "id": f"cd{len(cells):02d}", "execution_count": None, "metadata": {}, "outputs": [], "source": _lines(src)})


md(r"""
# Fade the initial move after a tier-1 / tier-2 economic release

A scheduled release lands at a known minute. Rates futures move within seconds. The question is
whether some of that first move is **liquidity** — a thin book absorbing a one-sided burst — rather
than information, and therefore reverts.

The trade measures the move over a short window after the print, takes the **opposite** side, and
holds for a configured horizon. Every one of those words is a knob, and here the knobs are **a
dict**. One `CONFIG` fully describes one backtest, so changing what is traded is an edit to data
rather than to code, and two configs can be compared without either being privileged.

```python
CONFIG = {
    "instrument": {"family": "stir", "root": "USD_STIR", "rank": 3},
    "events":     {"impacts": ["high"], "require_actual": True},
    "timing":     {"measure_end_min": 1, "entry_offset_min": 2, "exit_offset_min": 60},
    "signal":     {"direction": "fade", "min_move_bp": 0.0},
    "cost_bp":    0.0,
}
```

### The unit of trading is the release MINUTE, not the release

Of the 2,040 distinct USD tier-1/2 release minutes in 2019–2026, **437 carry two events, 223 carry
three, 75 four, 29 five, and two carry six and seven.** CPI prints with Core CPI. Non-farm payrolls
prints with the unemployment rate and average hourly earnings. There is one price move and it
belongs to the minute. A book that booked a trade per *event* would count the same move up to seven
times and report a Sharpe built on replicas.

So `titles_include: ["CPI"]` selects the minutes in which CPI printed — which are also the minutes
in which Core CPI printed. The notebook says so rather than implying a purity it cannot have.

### Order of operations, and why it is not the obvious one

    raw release minutes -> FILTERS -> re-time -> one-at-a-time -> causal gate -> measure -> price

The overlap rule runs **after** the filters, on the filtered book. A CPI-only config therefore
resolves its own overlaps and trades more CPI prints than a CPI-shaped slice of a mixed book does.
Both are legitimate; this one answers *"what if I only traded CPI"*.

### Three things this notebook deliberately cannot do

**It cannot fetch.** Barchart's fetcher calls `asyncio.run`, which inside a Jupyter kernel returns
an un-awaited coroutine instead of data. A config whose bars are not already warm is refused up
front, naming the prewarm command — never half-run, and never quietly reduced to whatever happened
to be cached.

**It cannot mark against a bar that had not finished.** Both shipped MDPs resolve an intraday
timestamp with `get_indexer(method="nearest")`, so a mark can come from the future. Worse, Barchart
minute bars are **start-stamped** — §2 measures this — so even "the last bar at or before T" is a
price from up to a minute *after* T. Here every price is the close of the last bar to have **fully
closed**, enforced in the pricing layer itself (`BarCacheSTIRMDP` / `BarCacheUSTMDP`), so no config
can opt out of it. For a strategy whose entire signal is the first minutes after a print, that is
not a rounding error — it is the signal.

**It cannot search on your behalf.** Every knob multiplies the configurations available, and
ranking a few hundred by Sharpe finds a good one whether or not any edge exists. §11 prices that
directly.

---

> ## What would make this real, and what would make it a mirage
>
> The edge has to survive four things, and each has its own section: a price that could actually
> have been observed (§2), the same book priced by two independent implementations (§3), the same
> trade taken on a day with **no release** (§9), and a cost that a desk would actually pay (§10).
> A number that only exists at zero cost, or that is just as large on the wrong day, is a property
> of the clock and not of the release.
""")

code(rf"""
%load_ext autoreload
%autoreload 2

import sys, json, copy, pickle, datetime, itertools, warnings
from pathlib import Path

REPO = r"{REPO}"
HERE = Path(REPO) / "notebooks" / "backtests" / "econ_release_fade"
sys.path.insert(0, REPO); sys.path.insert(0, str(HERE))

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.pylab as pylab
import seaborn as sns

plt.style.use("ggplot")
pylab.rcParams.update({{"figure.figsize": (14, 6), "axes.titlesize": "large",
                       "axes.labelsize": "large"}})
warnings.filterwarnings("ignore", category=FutureWarning)

import econ_fade_common as G
import econ_fade_config as C
from econ_fade_prewarm import load_events, symbols_needed

RAW = load_events()
n_bars = G.load_bar_cache()
n_dv01 = G.load_dv01()

if n_bars == 0:
    raise RuntimeError("no warm bars -- run `python econ_fade_prewarm.py --stage all` first")

print(f"raw release book : {{len(RAW):,}} release MINUTES, "
      f"{{RAW.date.min()}} -> {{RAW.date.max()}}")
print(f"                   (before any filter, the overlap rule or the data gate)")
print(f"                   {{int(RAW.any_release.sum()):,}} carry a number (a release); "
      f"{{int((~RAW.any_release).sum()):,}} do not (speeches, minutes, projections)")
print(f"bar cache        : {{n_bars:,}} symbol-days, {{len(G.cached_symbols())}} contracts")
print(f"UST DV01 table   : {{n_dv01}} contracts")
print(f"instruments      : {{', '.join(G.INSTRUMENTS)}}")
""")

# ---------------------------------------------------------------- config
md(r"""
## 1. The config

Edit this cell and re-run the notebook. Everything below reads `CONFIG`.
""")

code(r"""
CONFIG = {
    "name": "baseline",

    # WHAT IS TRADED ------------------------------------------------------
    #   {"family": "stir", "root": "USD_STIR", "rank": 3}   Nth quarterly, GE -> SR3
    #   {"family": "stir", "root": "ZQ", "rank": 2}         Nth serial-monthly Fed Funds
    #   {"family": "ust",  "root": "TY", "rank": 1}         front 10y note future
    "instrument": {"family": "stir", "root": "USD_STIR", "rank": 3},

    # WHICH RELEASES ------------------------------------------------------
    "events": {
        "currencies": ["USD"],
        "impacts": ["high"],            # ["high"] tier 1; ["high","medium"] tier 1+2
        "titles_include": None,         # regex, matched against ANY title in the minute
        "titles_exclude": None,
        "require_actual": True,         # a release has a number; a speech does not
        "include_cb_decisions": False,  # FOMC decisions are a committee's choice, not a statistic
        "start": None, "end": None,
        "weekdays": None,
        "surprise": "any",              # any | better | worse | surprised
        "min_events_in_minute": 1,      # 2 -> only clustered prints
        "release_times_ny": None,       # ["08:30"]
    },

    # WHEN, in minutes relative to the release -----------------------------
    # Every offset resolves to the last bar that had FULLY CLOSED by then (see
    # §2), so measure_start_min = 0 is genuinely the pre-release price. Entry
    # defaults one minute after the measurement ends: filling at the price the
    # signal was read from is a zero-latency assumption no desk can make.
    "timing": {
        "measure_start_min": 0,         # the initial move is measured from here...
        "measure_end_min": 1,           # ...to here
        "entry_offset_min": 2,          # and traded from here
        "exit_offset_min": 60,
        "max_staleness_min": 5,
        "same_day_exit": True,
    },

    # THE SIGNAL ----------------------------------------------------------
    "signal": {
        "direction": "fade",            # fade | momentum
        "source": "move",               # move | surprise (ForexFactory's better/worse)
        "min_move_bp": 0.0,
        "max_move_bp": None,
    },

    # HOW MUCH ------------------------------------------------------------
    "sizing": "equal",                  # equal | move
    "contracts": 1,
    "cost_bp": 0.0,                     # round trip, per unit of gross risk
}

RES = C.run_config(CONFIG, RAW, engine=True, show_progress=True)
CLOSED = RES.closed
print(f"{RES.book.instrument.label}  ->  {len(CLOSED)} trades")
""")

md(r"""
### 1.1 Recipes

Ready-made configs. Paste one over `CONFIG`, or pass a list to `C.compare`.

```python
TIER_12      = {"name": "tier 1+2",   "events": {"impacts": ["high", "medium"]}}
CPI_ONLY     = {"name": "CPI",        "events": {"titles_include": [r"\bCPI\b"]}}
PAYROLLS     = {"name": "payrolls",   "events": {"titles_include": ["Non-Farm Employment Change"]}}
THE_830      = {"name": "08:30 only", "events": {"release_times_ny": ["08:30"]}}
CLUSTERED    = {"name": "2+ prints",  "events": {"min_events_in_minute": 2}}
SURPRISES    = {"name": "surprises",  "events": {"surprise": "surprised"}}
FAST         = {"name": "T+1/T+15",   "timing": {"exit_offset_min": 15}}
BIG_MOVES    = {"name": ">= 2bp",     "signal": {"min_move_bp": 2.0}}
MOMENTUM     = {"name": "momentum",   "signal": {"direction": "momentum"}}
TEN_YEAR     = {"name": "10y future", "instrument": {"family": "ust", "root": "TY", "rank": 1}}
NET_OF_COST  = {"name": "0.5bp cost", "cost_bp": 0.5}
```
""")

# ---------------------------------------------------------------- bar stamping
md(r"""
## 2. Where the price comes from

Before any P&L, the one measurement everything else rests on: **a Barchart minute bar is stamped at
the START of its interval.** The bar labelled 07:30 America/Chicago covers 07:30:00–07:30:59, and
its close is a print from 07:31.

That single fact decides what this strategy measures. If "the price at the release" is read as the
close of the bar stamped at the release minute, then the pre-release reference is *itself* a
post-release price, the measured move is only whatever drift happened afterwards, and the fade is
being taken against the wrong number.

The cell below shows the release sitting inside that bar, on the largest payrolls surprise in the
sample. Read the volume column.
""")

code(r"""
# Non-farm payrolls, 2019-01-04: 312K against a 179K forecast. 08:30 New York
# is 07:30 America/Chicago, which is how these bars are stamped.
probe_day = datetime.date(2019, 1, 4)
probe = None
for cand in ("FVH19", "TYH19", "GEH19", "TUH19"):
    if (cand, probe_day) in G._BAR_CACHE:
        probe = cand; break

if probe is None:
    print("payrolls probe day not in the cache -- skipping the illustration")
else:
    bars = G._BAR_CACHE[(probe, probe_day)]
    base = bars.index.normalize()[0]
    win = bars.loc[base + pd.Timedelta(hours=7, minutes=26):base + pd.Timedelta(hours=7, minutes=34)]
    display(win.style.format("{:.5f}", subset=[c for c in win.columns if c != "Volume"])
            .background_gradient(subset=["Volume"], cmap="Reds"))

    rel = base + pd.Timedelta(hours=7, minutes=30)
    naive = G.px_at(probe, rel)      # what "last bar at or before T" gives
    right = G.px_before(probe, rel)  # what a bar that had actually closed gives
    inst_p = G.INSTRUMENTS["FV" if probe.startswith("FV") else
                           ("TY" if probe.startswith("TY") else
                            ("TU" if probe.startswith("TU") else "USD_STIR"))]
    ppb = G.px_per_bp(inst_p, probe) if inst_p.family == "stir" or probe in G._DV01 else None
    print(f"\n{probe}  release minute {rel:%H:%M} local")
    print(f"  bar stamped at the release  : {naive[0]:%H:%M} close {naive[1]:.6f}  <- INSIDE the release")
    print(f"  last bar to have CLOSED     : {right[0]:%H:%M} close {right[1]:.6f}  <- genuinely before it")
    m1 = G.px_before(probe, rel + pd.Timedelta(minutes=1))
    if ppb:
        print(f"\n  move measured correctly     : {-(m1[1] - right[1]) / ppb:+.3f} bp")
        print(f"  move measured from the bar  : {-(m1[1] - naive[1]) / ppb:+.3f} bp"
              f"   <- the release, measured after it happened")
    print("\nEvery price in this notebook is the second one. The first is available as")
    print("G.px_at() for exactly this comparison and is never used to price anything.")
""")

# ---------------------------------------------------------------- known answer
md(r"""
## 3. Two implementations, one book

A configurable backtest is a measuring instrument, and an instrument that is itself wrong reports
success while hiding the thing it was built to find. There is no published baseline to reproduce
here, so the check is stronger than a tie-out to a prior number: the same book is priced twice, by
two implementations that share nothing but the bars.

The **engine** builds a real `STIRFutureQuery` / `USTFutureQuery`, resolves it against a pricer,
hands it to the shipped position handler, and unwinds it — the full `QueryDrivenBacktest` path,
including the handler's `(Δprice / tick) × tick_value × contracts × weight` arithmetic. The
**closed form** takes the two cached bar prices and multiplies. If they disagree, one of them is
wrong, and the difference is reported per trade rather than averaged away.

They must agree to floating point. They are not two approximations of the same thing — the engine's
dollars divided by the position's DV01 *is* the closed form's basis points, exactly, and any gap is
a defect.
""")

code(r"""
V = G.validate_fast_vs_engine(RES.book, tol=1e-6, show_progress=False)
checks = [
    ("engine and closed form book the same trades",
     V["trades_engine"] == V["trades_fast"], f"{V['trades_engine']} vs {V['trades_fast']}"),
    ("every trade matched by tag", V["matched"] == V["trades_engine"],
     f"{V['matched']}/{V['trades_engine']}"),
    ("P&L agrees to 1e-6 bp everywhere", V["n_over_tol"] == 0,
     f"max |diff| {V['max_abs_diff']:.3e} bp"),
    ("no directional bias in the residual", abs(V["mean_diff"]) < 1e-9,
     f"mean {V['mean_diff']:+.3e} bp"),
    ("every gated event became a trade", len(CLOSED) == len(RES.book.events),
     f"{len(CLOSED)}/{len(RES.book.events)}"),
]
display(pd.DataFrame([{"check": c, "result": "PASS" if ok else "FAIL", "value": v}
                      for c, ok, v in checks]).set_index("check"))
assert all(ok for _, ok, _ in checks), "the two implementations disagree -- do not read on"

if V["n_over_tol"]:
    print("\nevery disagreement, individually:")
    display(V["detail"])

print("\nThe closed form is therefore safe to use for the grid search, where running the")
print("engine for every one of several hundred configurations would not be.")
""")

# ---------------------------------------------------------------- funnel
md(r"""
## 4. What this config actually trades

Every release minute that does not become a trade is counted under a reason. A book that shrinks is
a book that should be explainable, and two of these exclusions are load-bearing rather than
cosmetic:

`entry_before_first_bar` is an 08:30 ET release on a contract whose session had not opened. Without
the exclusion it would be marked against a bar from later in the morning — the whole trade leaking
backwards in time.

`move_window_same_bar` and `entry_exit_same_bar` are prints where the measurement window or the
holding period resolved to a single bar. Both would book a clean, guaranteed zero, inflating the
trade count and diluting every statistic with observations that could not have had an outcome.
""")

code(r"""
f_ = RES.funnel
row = {"raw release minutes": f_["raw"]}
row.update({f"filtered: {k}": v for k, v in sorted(f_["filter_drops"].items(), key=lambda x: -x[1])})
row["after filters"] = f_["after_filters"]
row["overlap rule"] = f_["overlap_dropped"]
row["after overlap"] = f_["after_overlap"]
for k, v in sorted(f_["gate_reasons"].items(), key=lambda x: -x[1]):
    if k != "ok":
        row[f"gate: {k}"] = v
row["after causal gate"] = f_["after_gate"]
for k, v in sorted(f_["signal_drops"].items(), key=lambda x: -x[1]):
    row[f"signal: {k}"] = v
row["TRADEABLE"] = f_["TRADEABLE"]
display(pd.Series(row).to_frame(CONFIG.get("name", "config")))

if not CLOSED.empty:
    print(f"window     {CLOSED.release_ts.min()}  ->  {CLOSED.release_ts.max()}")
    print(f"contracts  {CLOSED.symbol.nunique()}   "
          f"distinct release titles {len(set(t for ts in CLOSED.titles for t in ts))}   "
          f"clustered minutes {(CLOSED.n_events > 1).sum()} of {len(CLOSED)}")
    print(f"initial move  mean |move| {CLOSED.abs_move_bp.mean():.2f}bp   "
          f"median {CLOSED.abs_move_bp.median():.2f}bp   "
          f"p95 {CLOSED.abs_move_bp.quantile(.95):.2f}bp")
""")

# ---------------------------------------------------------------- performance
md(r"""
## 5. How this config performed

`pnl_bp` is **basis points of favourable rate move per unit of gross risk** — the engine's realised
dollars divided by the position's own DV01. It is the only unit in which a 2-year note future and a
SOFR future belong in the same book, and it is the unit the cost in §9 is charged in.
""")

code(r"""
def perf(df, label):
    if df is None or df.empty:
        return {"book": label, "trades": 0}
    s = G.summarize(df)
    return {"book": label, "trades": s["trades"], "total_bp": s["total_bp"],
            "avg_bp": s["avg_bp"], "hit": s["hit_rate"], "sharpe": s["sharpe"],
            "t_stat": s["t_stat"], "max_dd_bp": s["max_dd_bp"]}

rows = [perf(CLOSED, CONFIG.get("name", "config"))]
if not CLOSED.empty:
    rows.append(perf(CLOSED[CLOSED.n_events > 1], "  clustered prints only"))
    rows.append(perf(CLOSED[CLOSED.abs_move_bp >= CLOSED.abs_move_bp.median()], "  bigger half of moves"))
    rows.append(perf(CLOSED[CLOSED.abs_move_bp < CLOSED.abs_move_bp.median()], "  smaller half of moves"))
display(pd.DataFrame(rows).set_index("book").round(4))

if not CLOSED.empty:
    lo, hi = G.bootstrap_ci(CLOSED.pnl_bp.to_numpy(float))
    print(f"mean {CLOSED.pnl_bp.mean():+.4f} bp/trade    "
          f"bootstrap 95% CI [{lo:+.4f}, {hi:+.4f}]    "
          f"{'EXCLUDES zero' if lo * hi > 0 else 'INCLUDES zero'}")

    fig, axes = plt.subplots(3, 1, figsize=(14, 11),
                             gridspec_kw={"height_ratios": [2, 1, 1]})
    ax = axes[0]
    ax.plot(CLOSED.release_ts.values, CLOSED.pnl_bp.cumsum().values, lw=1.8,
            color="darkslateblue", label=CONFIG.get("name", "config"))
    ax.plot(CLOSED.release_ts.values, CLOSED.pnl_bp_gross.cumsum().values, lw=1.0,
            color="grey", ls="--", label="gross of cost")
    ax.axhline(0, color="k", lw=.6); ax.legend(); ax.grid(alpha=.3)
    ax.set_ylabel("cumulative bp per unit gross risk")
    ax.set_title(f"{CONFIG.get('name')} — {RES.book.instrument.label}, "
                 f"measure T+{CONFIG['timing']['measure_start_min']}..T+{CONFIG['timing']['measure_end_min']}, "
                 f"hold T+{CONFIG['timing']['entry_offset_min']}..T+{CONFIG['timing']['exit_offset_min']}")

    ax = axes[1]
    # Width must be a real duration: a bare int is read as NANOSECONDS against a
    # datetime64 x and collapses every bar to zero width.
    _span = CLOSED.release_ts.max() - CLOSED.release_ts.min()
    _w = _span / max(1, min(len(CLOSED), 400))
    ax.bar(CLOSED.release_ts.values, CLOSED.pnl_bp.values, width=_w, alpha=.75,
           color=["seagreen" if x > 0 else "indianred" for x in CLOSED.pnl_bp])
    ax.axhline(0, color="k", lw=.6); ax.set_ylabel("per-trade bp"); ax.grid(alpha=.3)

    ax = axes[2]
    cum = CLOSED.pnl_bp.cumsum()
    ax.fill_between(CLOSED.release_ts.values, (cum - cum.cummax()).values, 0,
                    color="indianred", alpha=.5)
    ax.set_ylabel("drawdown (bp)"); ax.grid(alpha=.3)
    plt.tight_layout(); plt.show()
""")

code(r"""
if not CLOSED.empty:
    fig, axes = plt.subplots(1, 3, figsize=(19, 4.4))

    axes[0].hist(CLOSED.pnl_bp, bins=60, color="steelblue", edgecolor="k", lw=.3)
    axes[0].axvline(0, color="k", lw=.8)
    axes[0].axvline(CLOSED.pnl_bp.mean(), color="crimson", lw=2,
                    label=f"mean {CLOSED.pnl_bp.mean():+.3f}")
    axes[0].set_title("per-trade P&L (bp)"); axes[0].legend()

    # Does the size of the initial move predict the size of the fade? If the
    # move is liquidity, a bigger burst should revert more.
    axes[1].scatter(CLOSED.move_bp, CLOSED.pnl_bp, s=12, alpha=.45, color="darkslateblue")
    axes[1].axhline(0, color="k", lw=.6); axes[1].axvline(0, color="k", lw=.6)
    if len(CLOSED) > 3 and CLOSED.move_bp.std() > 0:
        b, a = np.polyfit(CLOSED.move_bp, CLOSED.pnl_bp, 1)
        xs = np.linspace(CLOSED.move_bp.min(), CLOSED.move_bp.max(), 50)
        r = np.corrcoef(CLOSED.move_bp, CLOSED.pnl_bp)[0, 1]
        axes[1].plot(xs, a + b * xs, color="crimson", lw=1.6,
                     label=f"slope {b:+.3f}  r={r:+.3f}")
        axes[1].legend()
    axes[1].set_xlabel("initial move (bp of rate)"); axes[1].set_ylabel("trade P&L (bp)")
    axes[1].set_title("does a bigger burst revert more?")

    q = pd.qcut(CLOSED.abs_move_bp, min(5, CLOSED.abs_move_bp.nunique()), duplicates="drop")
    byq = CLOSED.groupby(q, observed=True).pnl_bp.agg(["mean", "count"])
    axes[2].bar(range(len(byq)), byq["mean"],
                color=["seagreen" if v > 0 else "indianred" for v in byq["mean"]], alpha=.85)
    axes[2].set_xticks(range(len(byq)))
    axes[2].set_xticklabels([f"{i.left:.1f}-{i.right:.1f}" for i in byq.index],
                            rotation=30, fontsize=8)
    for i, (m, n) in enumerate(zip(byq["mean"], byq["count"])):
        axes[2].text(i, m, f" {int(n)}t", ha="center", fontsize=8)
    axes[2].axhline(0, color="k", lw=.6)
    axes[2].set_title("avg bp by size of the initial move")
    axes[2].set_xlabel("|initial move| (bp)")
    plt.tight_layout(); plt.show()
""")

# ---------------------------------------------------------------- instruments
md(r"""
## 6. The instrument knob

The same releases, expressed along the curve. The SOFR strip out to eight quarterly contracts, the
Fed Funds strip, and the four liquid Treasury futures — all scored on the same event set, in the
same unit, so the rows differ by **instrument** and not by which days each one happened to be able
to price.

Two caveats are in the data rather than in the prose. USD STIR splices Eurodollar to SR3 at
2022-01-01 because SR3 barely traded before then. ZQ minute bars begin around 2024-11, so its rows
are a short recent sub-sample and its trade count says so.
""")

code(r"""
INSTS = ([{"family": "stir", "root": "USD_STIR", "rank": n} for n in range(1, 9)] +
         [{"family": "stir", "root": "ZQ", "rank": n} for n in (1, 2, 3, 4)] +
         [{"family": "ust", "root": r, "rank": 1} for r in ("TU", "FV", "TY", "US")])
inst_cfgs = []
for i in INSTS:
    nm = (f"SR3 rank {i['rank']}" if i["root"] == "USD_STIR" else
          f"ZQ rank {i['rank']}" if i["root"] == "ZQ" else
          G.INSTRUMENTS[i["root"]].label.split(" (")[0])
    inst_cfgs.append(C.variant(CONFIG, nm, instrument=i))

inst_tbl, inst_res = C.compare(inst_cfgs, RAW, engine=False)
display(inst_tbl.round(4))

ok = inst_tbl[inst_tbl.trades > 0].copy()
if len(ok):
    fam = {n: ("ust" if inst_res[n].book.instrument.family == "ust"
               else ("zq" if inst_res[n].book.instrument.key == "ZQ" else "sr3")) for n in ok.index}
    colors = {"sr3": "steelblue", "zq": "darkorange", "ust": "seagreen"}
    fig, axes = plt.subplots(1, 3, figsize=(19, 4.6))
    axes[0].bar(ok.index, ok.sharpe, color=[colors[fam[n]] for n in ok.index], alpha=.9)
    axes[0].axhline(0, color="k", lw=.6); axes[0].set_ylabel("annualised Sharpe")
    axes[0].set_title("Sharpe by instrument"); axes[0].tick_params(axis="x", rotation=70)
    axes[1].bar(ok.index, ok.avg_bp, color=[colors[fam[n]] for n in ok.index], alpha=.9)
    axes[1].axhline(0, color="k", lw=.6); axes[1].set_ylabel("avg bp / trade")
    axes[1].set_title("edge per trade"); axes[1].tick_params(axis="x", rotation=70)
    for i, n in enumerate(ok.index):
        axes[1].text(i, ok.avg_bp[n], f"{int(ok.trades[n])}t", ha="center", fontsize=7)
    for nm in ok.sort_values("sharpe", ascending=False).index[:6]:
        c = inst_res[nm].closed
        axes[2].plot(c.release_ts.values, c.pnl_bp.cumsum().values, lw=1.5, label=nm)
    axes[2].axhline(0, color="k", lw=.6); axes[2].legend(ncol=2, fontsize=8)
    axes[2].set_title("cumulative bp — best six"); axes[2].set_ylabel("bp")
    plt.tight_layout(); plt.show()
    print("Trade counts differ across instruments because the causal gate is re-applied per")
    print("contract. Compare the per-trade column before the total.")
""")

# ---------------------------------------------------------------- timing
md(r"""
## 7. The timing knob

Two windows, not one. **Measurement** is how much of the initial move the signal gets to see;
**holding** is how long the fade is given to work. They trade off against each other: measuring
longer makes the signal cleaner and leaves less move left to revert.

Both are searched here, and both are exactly the kind of knob §11 exists to discount — the entry
and exit minutes are fitted to this sample, unlike the release calendar itself, which is published
years ahead and known at trade time.
""")

code(r"""
# Starts at 2, not 1: with a one-minute measurement window an entry at T+1
# fills at the exact price the signal was read from, and the bid-ask bounce
# that set the side also supplies the entry. build_book refuses it.
ENTRY = [2, 3, 5, 10, 15]
EXIT = [5, 15, 30, 60, 120, 240]
tim_cfgs = [C.variant(CONFIG, f"{e}|{x}",
                      timing={"entry_offset_min": e, "exit_offset_min": x})
            for e in ENTRY for x in EXIT if x > e]
tim_tbl, tim_res = C.compare(tim_cfgs, RAW, engine=False)

grid_sr = pd.DataFrame(index=ENTRY, columns=EXIT, dtype=float)
grid_bp = pd.DataFrame(index=ENTRY, columns=EXIT, dtype=float)
grid_n = pd.DataFrame(index=ENTRY, columns=EXIT, dtype=float)
for e in ENTRY:
    for x in EXIT:
        k = f"{e}|{x}"
        if k in tim_tbl.index:
            grid_sr.loc[e, x] = tim_tbl.loc[k, "sharpe"]
            grid_bp.loc[e, x] = tim_tbl.loc[k, "avg_bp"]
            grid_n.loc[e, x] = tim_tbl.loc[k, "trades"]

fig, axes = plt.subplots(1, 3, figsize=(20, 4.6))
sns.heatmap(grid_sr.astype(float), annot=True, fmt=".2f", cmap="RdYlGn", center=0,
            ax=axes[0], cbar_kws={"label": "annualised Sharpe"})
axes[0].set_title("Sharpe — entry (rows) x exit (cols), minutes after the release")
sns.heatmap(grid_bp.astype(float), annot=True, fmt=".2f", cmap="RdYlGn", center=0,
            ax=axes[1], cbar_kws={"label": "bp / trade"})
axes[1].set_title("edge per trade (bp)")
sns.heatmap(grid_n.astype(float), annot=True, fmt=".0f", cmap="Blues", ax=axes[2],
            cbar_kws={"label": "trades"})
axes[2].set_title("trades — a wider window is not free, the gate clamps it")
for ax in axes:
    ax.set_xlabel("exit"); ax.set_ylabel("entry")
plt.tight_layout(); plt.show()
display(tim_tbl.sort_values("sharpe", ascending=False).head(8).round(4))
""")

code(r"""
MEAS = [1, 2, 3, 5, 10]
HOLD = [15, 30, 60, 120, 240]
mh_cfgs = [C.variant(CONFIG, f"m{m}|h{h}",
                     timing={"measure_end_min": m, "entry_offset_min": m + 1,
                             "exit_offset_min": h})
           for m in MEAS for h in HOLD if h > m + 1]
mh_tbl, mh_res = C.compare(mh_cfgs, RAW, engine=False)

g_sr = pd.DataFrame(index=MEAS, columns=HOLD, dtype=float)
g_bp = pd.DataFrame(index=MEAS, columns=HOLD, dtype=float)
for m in MEAS:
    for h in HOLD:
        k = f"m{m}|h{h}"
        if k in mh_tbl.index:
            g_sr.loc[m, h] = mh_tbl.loc[k, "sharpe"]
            g_bp.loc[m, h] = mh_tbl.loc[k, "avg_bp"]

fig, axes = plt.subplots(1, 2, figsize=(16, 4.6))
sns.heatmap(g_sr.astype(float), annot=True, fmt=".2f", cmap="RdYlGn", center=0, ax=axes[0],
            cbar_kws={"label": "Sharpe"})
axes[0].set_title("measurement window (rows) x holding period (cols) — Sharpe")
sns.heatmap(g_bp.astype(float), annot=True, fmt=".2f", cmap="RdYlGn", center=0, ax=axes[1],
            cbar_kws={"label": "bp / trade"})
axes[1].set_title("bp per trade — entry follows the measurement window")
for ax in axes:
    ax.set_xlabel("hold (min)"); ax.set_ylabel("measure (min)")
plt.tight_layout(); plt.show()
print("Entry is pinned to one minute AFTER the measurement window closes, so a longer look")
print("is always paid for with a later entry -- and no cell here fills at the price it read")
print("the signal from.")
""")

# ---------------------------------------------------------------- releases
md(r"""
## 8. The release knob

Which prints. Each row re-runs the whole pipeline with one filter changed, so the overlap rule is
resolved **within** that book rather than inherited from a mixed one.

One cut here is economically motivated rather than searched: tier is ForexFactory's own
ex-ante impact rating, published before the print, so selecting on it is not selecting on the
outcome. `surprise` is not in that class — `ActualOutcome` is known only after the number lands,
so a `surprises only` row is a *conditional* result and not a tradeable rule.
""")

code(r"""
REL_CFGS = [
    ("all tier 1", {"impacts": ["high"]}),
    ("all tier 1+2", {"impacts": ["high", "medium"]}),
    ("tier 2 only", {"impacts": ["medium"]}),
    ("08:30 block", {"impacts": ["high", "medium"], "release_times_ny": ["08:30"]}),
    ("10:00 block", {"impacts": ["high", "medium"], "release_times_ny": ["10:00"]}),
    ("clustered (2+ prints)", {"impacts": ["high", "medium"], "min_events_in_minute": 2}),
    ("single print only", {"impacts": ["high", "medium"], "min_events_in_minute": 1,
                           "titles_exclude": None}),
    ("CPI", {"impacts": ["high", "medium"], "titles_include": [r"\bCPI\b"]}),
    ("payrolls", {"impacts": ["high", "medium"],
                  "titles_include": [r"^Non-Farm Employment Change$", r"^Unemployment Rate$"]}),
    ("PPI", {"impacts": ["high", "medium"], "titles_include": [r"\bPPI\b"]}),
    ("retail sales", {"impacts": ["high", "medium"], "titles_include": ["Retail Sales"]}),
    ("ISM / PMI", {"impacts": ["high", "medium"], "titles_include": ["ISM", "PMI"]}),
    ("jobless claims", {"impacts": ["high", "medium"], "titles_include": ["Unemployment Claims"]}),
    ("PCE", {"impacts": ["high", "medium"], "titles_include": ["PCE"]}),
    ("beat forecast", {"impacts": ["high", "medium"], "surprise": "better"}),
    ("missed forecast", {"impacts": ["high", "medium"], "surprise": "worse"}),
    ("any surprise", {"impacts": ["high", "medium"], "surprise": "surprised"}),
    ("incl. FOMC decisions", {"impacts": ["high", "medium"], "include_cb_decisions": True}),
]
rel_cfgs = [C.variant(CONFIG, nm, events=ov) for nm, ov in REL_CFGS]
rel_tbl, rel_res = C.compare(rel_cfgs, RAW, engine=False)
display(rel_tbl.round(4))

ok = rel_tbl[rel_tbl.trades >= 10]
fig, axes = plt.subplots(1, 2, figsize=(17, max(4.6, .34 * len(ok))))
axes[0].barh(ok.index, ok.avg_bp,
             color=["seagreen" if x > 0 else "indianred" for x in ok.avg_bp], alpha=.85)
axes[0].axvline(0, color="k", lw=.6); axes[0].set_xlabel("avg bp / trade")
axes[0].set_title("edge per trade by release set (>= 10 trades)")
for i, (nm, r) in enumerate(ok.iterrows()):
    axes[0].text(r.avg_bp, i, f"  {int(r.trades)}t  t={r.t_stat:+.1f}", va="center", fontsize=8)
for nm in ok.sort_values("sharpe", ascending=False).index[:5]:
    c = rel_res[nm].closed
    axes[1].plot(c.release_ts.values, c.pnl_bp.cumsum().values, lw=1.6, label=nm)
axes[1].axhline(0, color="k", lw=.6); axes[1].legend(fontsize=9)
axes[1].set_title("cumulative bp — best five release sets"); axes[1].set_ylabel("bp")
plt.tight_layout(); plt.show()
""")

md(r"""
### 8.1 Release by release

The per-title breakdown is where a "signal" most often turns out to be one or two prints. A row
with eight trades and a large mean is a story, not a result — the trade-count column is there to be
read first.
""")

code(r"""
if not CLOSED.empty:
    ex = CLOSED.explode("titles")
    by = (ex.groupby("titles")
            .agg(trades=("pnl_bp", "size"), avg_bp=("pnl_bp", "mean"),
                 total_bp=("pnl_bp", "sum"), hit=("profitable", "mean"),
                 avg_move=("abs_move_bp", "mean"))
            .sort_values("trades", ascending=False))
    display(by[by.trades >= 5].round(4).head(25))

    top = by[by.trades >= 10].sort_values("avg_bp")
    if len(top):
        fig, ax = plt.subplots(figsize=(12, max(4, .3 * len(top))))
        ax.barh(top.index, top.avg_bp,
                color=["seagreen" if v > 0 else "indianred" for v in top.avg_bp], alpha=.85)
        for i, (nm, r) in enumerate(top.iterrows()):
            ax.text(r.avg_bp, i, f"  {int(r.trades)}t", va="center", fontsize=8)
        ax.axvline(0, color="k", lw=.7)
        ax.set_xlabel("avg bp / trade"); ax.set_title("edge per trade by release title (>= 10 trades)")
        plt.tight_layout(); plt.show()

    fig, axes = plt.subplots(1, 2, figsize=(16, 4.2))
    bt = CLOSED.groupby("release_time_ny").pnl_bp.agg(["mean", "size"])
    bt = bt[bt["size"] >= 5]
    axes[0].bar(bt.index, bt["mean"],
                color=["seagreen" if v > 0 else "indianred" for v in bt["mean"]], alpha=.85)
    for i, (nm, r) in enumerate(bt.iterrows()):
        axes[0].text(i, r["mean"], f"{int(r['size'])}t", ha="center", fontsize=8)
    axes[0].axhline(0, color="k", lw=.6); axes[0].set_title("avg bp by release time (NY)")
    axes[0].tick_params(axis="x", rotation=45)

    bn = CLOSED.groupby("n_events").pnl_bp.agg(["mean", "size"])
    axes[1].bar(bn.index.astype(str), bn["mean"],
                color="darkslateblue", alpha=.85)
    for i, (nm, r) in enumerate(bn.iterrows()):
        axes[1].text(i, r["mean"], f"{int(r['size'])}t", ha="center", fontsize=8)
    axes[1].axhline(0, color="k", lw=.6)
    axes[1].set_title("avg bp by how many prints shared the minute")
    axes[1].set_xlabel("events in the release minute")
    plt.tight_layout(); plt.show()
""")

# ---------------------------------------------------------------- placebo
md(r"""
## 9. Is it the release, or is it the clock?

08:30 New York is not only when CPI prints. It is also an hour before the cash equity open, the
start of the most liquid stretch of the Treasury session, and the moment a lot of overnight risk
gets recycled. A mean-reversion effect that lives at 08:30 every day would show up in this backtest
as a release effect and would be nothing of the kind.

So the same trade is taken on the **wrong day**: every release timestamp is shifted onto a minute
that had no release. Time of day, instrument, contract, measurement window, holding period and the
entire causal gate are unchanged. The only thing removed is the reason.

The shift is in **business** days, and this is not a detail. A calendar shift of +1 moves every
Friday release to a Saturday, where the gate deletes it as `no_bars_that_day` — and payrolls is a
Friday release. At +2 Thursday goes too, taking jobless claims, the single most frequent print in
the book. A calendar placebo is therefore not the same book on a quiet day; it is the book with its
two largest families removed, and it would differ from the real one because of the composition
change rather than because of the absence of news. The weekday table below is there so that can be
checked rather than trusted.

Shifted minutes that land on a **real** release are dropped, so a weekly print moved by a week
cannot quietly become a second copy of itself.

The momentum flip is the second control. `fade` and `momentum` are the same trades with the sign
reversed, so gross of cost they must be near mirror images. If both make money the P&L is coming
from somewhere other than the direction of the initial move — which would mean the sizing, the
gate, or the marking, and not the idea.
""")

code(r"""
RAW_P1 = C.placebo_shift(RAW, days=1)
comp = C.placebo_composition(RAW, RAW_P1).rename_axis("original weekday")
display(comp)
print(f"{len(RAW):,} release minutes -> {len(RAW_P1):,} placebo minutes "
      f"({len(RAW) - len(RAW_P1):,} landed on a minute that had a REAL release and were dropped)")
print("Grouped on the ORIGINAL weekday, so 'kept %' answers 'did payrolls survive the shift'.")
print("A calendar shift would look fine in this table and then lose every Friday event in the")
print("gate instead -- which is why the traded books are compared again below.\n")

placebo_rows, placebo_res = [], {}
for shift in (1, 2, 3, -1, -2):
    RAW_P = C.placebo_shift(RAW, days=shift)          # business days, real minutes removed
    r = C.run_config(C.variant(CONFIG, f"shift {shift:+d}bd"), RAW_P, engine=False)
    placebo_res[f"{shift:+d}bd"] = r
    s = r.stats
    placebo_rows.append({"book": f"wrong day {shift:+d}bd", "trades": s.get("trades", 0),
                         "avg_bp": s.get("avg_bp", np.nan), "total_bp": s.get("total_bp", np.nan),
                         "hit": s.get("hit_rate", np.nan), "sharpe": s.get("sharpe", np.nan),
                         "t_stat": s.get("t_stat", np.nan)})

mom = C.run_config(C.variant(CONFIG, "momentum", signal={"direction": "momentum"}),
                   RAW, engine=False)
s0 = G.summarize(CLOSED)
rows = [{"book": "THE REAL BOOK", "trades": s0["trades"], "avg_bp": s0["avg_bp"],
         "total_bp": s0["total_bp"], "hit": s0["hit_rate"], "sharpe": s0["sharpe"],
         "t_stat": s0["t_stat"]}] + placebo_rows
sm = mom.stats
rows.append({"book": "momentum (sign flipped)", "trades": sm.get("trades", 0),
             "avg_bp": sm.get("avg_bp", np.nan), "total_bp": sm.get("total_bp", np.nan),
             "hit": sm.get("hit_rate", np.nan), "sharpe": sm.get("sharpe", np.nan),
             "t_stat": sm.get("t_stat", np.nan)})
display(pd.DataFrame(rows).set_index("book").round(4))

# The composition check that actually matters: the books as TRADED, after the gate.
p1 = placebo_res.get("+1bd")
if p1 is not None and not p1.closed.empty and not CLOSED.empty:
    wd = lambda d: d.release_ts.dt.tz_convert("America/New_York").dt.strftime("%a")  # noqa: E731
    tc = pd.concat([wd(CLOSED).value_counts().rename("real trades"),
                    wd(p1.closed).value_counts().rename("placebo trades")], axis=1).fillna(0).astype(int)
    tc["ratio"] = (tc["placebo trades"] / tc["real trades"].replace(0, np.nan)).round(2)
    display(tc.rename_axis("traded weekday"))
    print("These are the books after the causal gate. A weekday missing here and present above")
    print("would mean the shift moved it onto a day with no session.\n")

pl_avg = np.array([r["avg_bp"] for r in placebo_rows if r["trades"] > 0], dtype=float)
if len(pl_avg):
    print(f"\nreal edge {s0['avg_bp']:+.4f} bp/trade   "
          f"placebo mean {pl_avg.mean():+.4f}   "
          f"placebo range [{pl_avg.min():+.4f}, {pl_avg.max():+.4f}]")
    if s0["avg_bp"] > 0 and pl_avg.max() >= s0["avg_bp"]:
        print("A DAY WITH NO RELEASE PAYS AS WELL. This is a clock effect, not a release effect.")
    elif s0["avg_bp"] > 0:
        print("The placebo days do not reproduce it -- the edge is tied to the release.")

fig, axes = plt.subplots(1, 2, figsize=(16, 4.6))
axes[0].plot(CLOSED.release_ts.values, CLOSED.pnl_bp.cumsum().values, lw=2.2,
             color="darkslateblue", label="real releases")
for k, r in placebo_res.items():
    if not r.closed.empty:
        axes[0].plot(r.closed.release_ts.values, r.closed.pnl_bp.cumsum().values,
                     lw=1.0, alpha=.75, ls="--", label=f"wrong day {k}")
axes[0].axhline(0, color="k", lw=.6); axes[0].legend(fontsize=8)
axes[0].set_title("the same trade on a day with no release"); axes[0].set_ylabel("cumulative bp")

if not mom.closed.empty:
    axes[1].plot(CLOSED.release_ts.values, CLOSED.pnl_bp_gross.cumsum().values,
                 lw=1.8, color="seagreen", label="fade (gross)")
    axes[1].plot(mom.closed.release_ts.values, mom.closed.pnl_bp_gross.cumsum().values,
                 lw=1.8, color="indianred", label="momentum (gross)")
    axes[1].axhline(0, color="k", lw=.6); axes[1].legend()
    axes[1].set_title("fade against momentum — same trades, opposite sign")
plt.tight_layout(); plt.show()
""")

# ---------------------------------------------------------------- costs
md(r"""
## 10. Costs

`cost_bp` is charged per unit of gross risk, round trip. The reference points are measured rather
than assumed: the SR3 outright tick is 0.5 bp and the listed SR3 butterfly trades one tick — 0.506
bp round trip — while Treasury futures quote in 32nds and half-32nds, which on a 10-year is roughly
0.26 bp of yield per half-tick.

A strategy that turns over this fast is a cost story before it is an alpha story. The break-even
round trip below is the number to read first: if it is under a tick, there is nothing here
regardless of how the Sharpe looks at zero cost.
""")

code(r"""
COSTS = [0.0, 0.1, 0.25, 0.5, 0.75, 1.0]
books = {CONFIG.get("name", "config"): CLOSED}
for nm in list(rel_tbl.sort_values("sharpe", ascending=False).index[:3]):
    if nm in rel_res and not rel_res[nm].closed.empty:
        books[nm] = rel_res[nm].closed
for nm in list(inst_tbl.sort_values("sharpe", ascending=False).index[:2]):
    if nm in inst_res and not inst_res[nm].closed.empty:
        books[f"inst: {nm}"] = inst_res[nm].closed

rows = []
for c in COSTS:
    r = {"cost_bp_rt": c}
    for nm, df in books.items():
        r[nm] = df.pnl_bp_gross.sum() - c * len(df)
    rows.append(r)
cost_df = pd.DataFrame(rows).set_index("cost_bp_rt")
display(cost_df.round(1))

be = {nm: df.pnl_bp_gross.mean() for nm, df in books.items()}
print("break-even round-trip cost (bp per unit gross risk):")
for nm, v in sorted(be.items(), key=lambda x: -x[1]):
    verdict = "clears an SR3 tick" if v >= 0.5 else ("clears half a tick" if v >= 0.25 else "below half a tick")
    print(f"  {nm:<28} {v:+.4f}   {verdict}")

fig, axes = plt.subplots(1, 2, figsize=(16, 4.4))
cost_df.plot(marker="o", ax=axes[0])
axes[0].axhline(0, color="k", lw=.8); axes[0].set_ylabel("total bp"); axes[0].set_xlabel("round-trip cost (bp)")
axes[0].set_title("cost sensitivity"); axes[0].legend(fontsize=8)
axes[1].bar(list(be), list(be.values()),
            color=["seagreen" if v > 0 else "indianred" for v in be.values()], alpha=.85)
axes[1].axhline(0.5, color="crimson", ls=":", lw=1.6, label="SR3 tick, 0.5bp")
axes[1].axhline(0.25, color="darkorange", ls=":", lw=1.4, label="half tick")
axes[1].axhline(0, color="k", lw=.7)
axes[1].set_ylabel("break-even round trip (bp)"); axes[1].legend(fontsize=8)
axes[1].set_title("gross edge against the tick"); axes[1].tick_params(axis="x", rotation=30)
plt.tight_layout(); plt.show()
""")

# ---------------------------------------------------------------- search cost
md(r"""
## 11. What the search cost

This notebook ran a lot of configurations. Ranking them by Sharpe finds a good one whether or not
any edge exists, so the best number here has to be discounted by how many were tried.

The Deflated Sharpe compares the winner against `E[max Sharpe]` under the null that every
configuration has zero edge, using the spread of Sharpes the notebook actually observed as the
null's variance. It is the honest way to price the search — and it is **generous** here, because
these configurations are far from independent: they overlap heavily in the same release minutes.
""")

code(r"""
runs = {}
for src in (inst_res, tim_res, mh_res, rel_res):
    for nm, r in src.items():
        if not r.closed.empty and len(r.closed) >= 20:
            runs[nm] = r.closed.pnl_bp.to_numpy(float)
runs[CONFIG.get("name", "config")] = CLOSED.pnl_bp.to_numpy(float)

sr_pt = {nm: (v.mean() / v.std(ddof=1)) if v.std(ddof=1) > 0 else 0.0 for nm, v in runs.items()}
n_trials = len(runs)
var_sr = float(np.var(list(sr_pt.values()), ddof=1))
sr_star = G.expected_max_sharpe(var_sr, n_trials)

tbl = pd.DataFrame([
    {"config": nm, "trades": len(v), "sr_per_trade": sr_pt[nm],
     "avg_bp": v.mean(), "total_bp": v.sum(), "dsr": G.deflated_sharpe(v, sr_star)}
    for nm, v in runs.items()
]).sort_values("sr_per_trade", ascending=False).set_index("config")
print(f"{n_trials} configurations scored   selection hurdle sr* = {sr_star:.4f} per trade   "
      f"(variance of observed Sharpes {var_sr:.5f})")
display(tbl.head(15).round(4))

alive = tbl[(tbl.dsr > 0.95) & (tbl.trades >= 50)]
print(f"\nconfigs with DSR > 0.95 and >= 50 trades: {len(alive)} of {len(tbl)}")
if len(alive):
    display(alive.round(4))
else:
    print("Nothing here survives the search it took to find it.")

fig, ax = plt.subplots(figsize=(11, 4.2))
ax.hist(list(sr_pt.values()), bins=40, color="lightgrey", edgecolor="k", lw=.3)
ax.axvline(sr_star, color="crimson", lw=2, label=f"selection hurdle {sr_star:.3f}")
ax.axvline(sr_pt[CONFIG.get("name", "config")], color="darkslateblue", lw=2,
           label="the active config")
ax.set_xlabel("Sharpe per trade"); ax.legend()
ax.set_title(f"{n_trials} configurations against the hurdle the search created")
plt.tight_layout(); plt.show()
""")

# ---------------------------------------------------------------- robustness
md(r"""
## 12. Robustness of the active config

The sign-flip permutation randomises which way round each trade was taken while keeping the
magnitude distribution exactly. The null it tests is that the **direction** carried no information
— which is the strategy's actual claim — rather than the much weaker null that rates futures do not
move.
""")

code(r"""
if not CLOSED.empty:
    r = G.sign_flip_permutation(CLOSED, n_perm=5000)
    print("sign-flip permutation — the null is that the DIRECTION carried nothing:")
    print(f"  realised {r['realized_sharpe']:.4f}   null {r['perm_mean']:.4f} "
          f"+- {r['perm_std']:.4f}   p = {r['p_value']:.4f}")

    mid = len(CLOSED) // 2
    halves = []
    for nm, sub in [("1st half", CLOSED.iloc[:mid]), ("2nd half", CLOSED.iloc[mid:])]:
        s = G.summarize(sub)
        halves.append({"half": nm, "trades": s["trades"], "total_bp": s["total_bp"],
                       "avg_bp": s["avg_bp"], "hit": s["hit_rate"], "sharpe": s["sharpe"],
                       "range": f"{pd.Timestamp(s['first']).date()} -> {pd.Timestamp(s['last']).date()}"})
    display(pd.DataFrame(halves).set_index("half").round(4))

    fig, axes = plt.subplots(1, 4, figsize=(21, 4))
    axes[0].hist(r["perm"], bins=60, color="lightgrey", edgecolor="k", lw=.3)
    axes[0].axvline(r["realized_sharpe"], color="crimson", lw=2)
    axes[0].set_title(f"sign-flip permutation, p={r['p_value']:.4f}")

    y = CLOSED.groupby("year").pnl_bp.agg(["sum", "size"])
    axes[1].bar(y.index.astype(str), y["sum"],
                color=["seagreen" if v > 0 else "indianred" for v in y["sum"]], alpha=.85)
    for i, (nm, rr) in enumerate(y.iterrows()):
        axes[1].text(i, rr["sum"], f"{int(rr['size'])}t", ha="center", fontsize=8)
    axes[1].axhline(0, color="k", lw=.6); axes[1].set_title("total bp by year")

    roll = CLOSED.pnl_bp.rolling(50)
    rs = (roll.mean() / roll.std()).values
    axes[2].plot(CLOSED.release_ts.values, rs, color="darkslateblue", lw=1.4)
    axes[2].axhline(0, color="k", lw=.6)
    axes[2].set_title("rolling 50-trade Sharpe per trade")

    d = CLOSED.groupby(CLOSED.release_ts.dt.tz_convert("America/New_York").dt.dayofweek).pnl_bp.mean()
    axes[3].bar(["Mon", "Tue", "Wed", "Thu", "Fri"][:len(d)], d.values,
                color="darkslateblue", alpha=.85)
    axes[3].axhline(0, color="k", lw=.6); axes[3].set_title("avg bp by weekday")
    plt.tight_layout(); plt.show()
""")

md(r"""
### 12.1 The permutation null: the same days, the minutes reordered

Every test so far compares this book against a book taken somewhere else — a different day, the
opposite sign, a different configuration. This one compares it against **the same days with their
minutes shuffled**.

`RVUtils.StatisticalFinance.permute_price` reorders a day's minute log-returns and rebuilds the
price path. The day's open, its close, its realised volatility and its entire set of one-minute
moves are all preserved exactly; only *when inside the day* each move happened is destroyed. Then
the whole pipeline re-runs — filters, gate, measurement, side, pricing — on that day.

This is the strongest control in the notebook, and it is strictly stronger than §9's wrong-day
placebo, which changes the day and therefore also changes the volatility regime, the contract and
what other news was around. Here nothing changes except that the release minute stops being special.

Two numbers come out of it and they answer different questions. The **trade count** under the null
measures whether the release moves the market at all: a release minute that moved gets counted, and
on permuted bars the big move has been relocated somewhere else in the session. The **p-value**
measures whether the fade's edge survives, and it is computed on Sharpe per trade rather than
anything annualised, because the permuted books have different trade counts and an annualised figure
would compare two differently-scaled numbers.

Method after [quantpylib's Statistical Finance notes](https://quantpylib.hangukquant.com/learn/statistical_finance/),
following Masters, *Permutation and Randomization Tests for Trading System Development*.
""")

code(r"""
from RVUtils.StatisticalFinance import (
    ras_bound, romano_wolf, selection_bias_pvalue, shared_sign_flip_null, timer_pvalue,
)

MC = G.mcpt_overfit(CONFIG, RAW, draws=200, seed=20260811, show_progress=True)
print("in-sample overfit test -- the null is that this release calendar marks nothing:")
print(f"  observed Sharpe/trade {MC.observed:+.5f} over {MC.meta['observed_trades']} trades")
print(f"  permuted null {MC.null_mean:+.5f} +- {MC.null_std:.5f} "
      f"over {MC.meta['null_trades_mean']:.0f} trades on average")
print(f"  p = {MC.p_value:.4f}   observed sits at the {MC.percentile:.1f}th percentile")
print(f"  {MC.n_failed} draws failed")

shrink = 1 - MC.meta["null_trades_mean"] / max(1, MC.meta["observed_trades"])
print(f"\nTHE TRADE COUNT is the release effect, measured without reference to direction:")
print(f"  reordering each day's minutes removes {shrink:.0%} of the tradeable events, because a")
print(f"  minute that is not the release minute usually did not move.")

tp = timer_pvalue(CLOSED.pnl_bp_gross.to_numpy(float), CLOSED.side.to_numpy(float),
                  draws=4999, rng=np.random.default_rng(7), label="timer")
print(f"\ntimer's p-value (permute which release each side received): {tp.p_value:.4f}")

fig, axes = plt.subplots(1, 2, figsize=(16, 4.4))
axes[0].hist(MC.null, bins=50, color="lightgrey", edgecolor="k", lw=.3)
axes[0].axvline(MC.observed, color="crimson", lw=2, label=f"observed {MC.observed:+.4f}")
axes[0].set_xlabel("Sharpe per trade"); axes[0].legend(fontsize=8)
axes[0].set_title(f"minutes reordered within the day, p={MC.p_value:.4f}")
axes[1].hist(tp.null, bins=60, color="lightgrey", edgecolor="k", lw=.3)
axes[1].axvline(tp.observed, color="crimson", lw=2)
axes[1].set_xlabel("Sharpe per trade")
axes[1].set_title(f"timer's permutation null, p={tp.p_value:.4f}")
plt.tight_layout(); plt.show()
""")

md(r"""
### 12.2 What the sweeps cost, priced properly

§11 deflates the best Sharpe with the Deflated Sharpe Ratio, which prices the search by its *size*.
Two better instruments are available now.

**Romano-Wolf stepdown** controls the familywise error rate across every configuration this notebook
ran, walking down the ranking and shrinking the competing set as hypotheses are rejected. Unlike the
DSR it needs no distributional assumption, and unlike a Bonferroni it does not treat 90 heavily
overlapping configurations as 90 independent experiments.

**The Rademacher Anti-Serum** returns a lower bound on the true Sharpe that holds with 95%
probability in finite samples. Its complexity penalty is *measured on this family*: configurations
that trade nearly the same releases the same way are charged almost nothing extra, which is exactly
right here, where the sweeps differ by a knob rather than by an idea.

The null for both is a **shared** Rademacher sign flip across configurations — shared so that
correlated configurations flip together and the family maximum is not inflated by pretending they
were independent.
""")

code(r"""
BOOKS = {}
for src in (inst_res, tim_res, mh_res, rel_res):
    for nm, res_ in src.items():
        if not res_.closed.empty and len(res_.closed) >= 30:
            BOOKS[nm] = res_.closed
BOOKS[CONFIG.get("name", "config")] = CLOSED

X = G.pnl_matrix(BOOKS)
print(f"{X.shape[1]} configurations x {X.shape[0]} distinct release timestamps")

obs_sr = np.array([X[c].dropna().mean() / X[c].dropna().std(ddof=1)
                   if X[c].notna().sum() > 1 else 0.0 for c in X.columns])
NULL = shared_sign_flip_null(X, draws=2000, rng=np.random.default_rng(11))

p_best = selection_bias_pvalue(obs_sr, NULL)
RW = romano_wolf(obs_sr, NULL, alpha=0.05, names=list(X.columns))
print(f"selection-bias adjusted p for the BEST configuration: {p_best:.4f}")
print(f"Romano-Wolf rejects {RW.n_rejected} of {RW.n_strategies} at a 5% familywise level")
display(RW.table.head(15).round(4))

RAS = ras_bound(X.fillna(0.0), delta=0.05, draws=3000, rng=np.random.default_rng(12),
                names=list(X.columns))
display(RAS.terms().to_frame("value").round(5))
alive = RAS.table()[RAS.table()["rademacher_positive"]]
print(f"Rademacher-positive configurations: {len(alive)} of {RAS.N}")
if len(alive):
    display(alive.round(5).head(10))

fig, axes = plt.subplots(1, 3, figsize=(20, 4.4))
axes[0].hist(np.nanmax(NULL, axis=1), bins=60, color="lightgrey", edgecolor="k", lw=.3)
axes[0].axvline(obs_sr.max(), color="crimson", lw=2, label=f"best observed {obs_sr.max():+.4f}")
axes[0].set_title(f"best-of-{len(X.columns)} null, p={p_best:.4f}"); axes[0].legend(fontsize=8)
axes[0].set_xlabel("max Sharpe per trade")
axes[1].scatter(RW.table["observed"], RW.table["p_adjusted"], s=14, alpha=.7, color="darkslateblue")
axes[1].axhline(0.05, color="crimson", ls="--", lw=1.5, label="FWER 5%")
axes[1].set_xlabel("Sharpe per trade"); axes[1].set_ylabel("Romano-Wolf adjusted p")
axes[1].legend(fontsize=8); axes[1].set_title("adjusted p against the statistic it adjusts")
t = RAS.table()
axes[2].scatter(t["sharpe"], t["ras_lower_bound"], s=14, alpha=.7, color="seagreen")
axes[2].axhline(0, color="crimson", ls="--", lw=1.5, label="Rademacher positive above this")
axes[2].set_xlabel("empirical Sharpe per trade"); axes[2].set_ylabel("RAS lower bound")
axes[2].legend(fontsize=8); axes[2].set_title(f"a flat {RAS.haircut:.4f} haircut for the search")
plt.tight_layout(); plt.show()
""")

# ---------------------------------------------------------------- log
md("## 13. Trade log")

code(r"""
if not CLOSED.empty:
    log = CLOSED[["release_ts", "opened_at", "closed_at", "lead_title", "n_events", "impact",
                  "lead_outcome", "symbol", "side", "contracts", "dv01_usd", "move_bp",
                  "entry_px", "exit_px", "hold_min", "pnl_bp_gross", "pnl_bp"]].copy()
    log["cum_bp"] = log.pnl_bp.cumsum()
    display(log.head(60).style.format({"pnl_bp": "{:+.3f}", "pnl_bp_gross": "{:+.3f}",
                                       "cum_bp": "{:+.2f}", "move_bp": "{:+.3f}",
                                       "dv01_usd": "{:,.1f}"})
            .bar(subset=["pnl_bp"], color=["#d65f5f", "#5fba7d"], align="zero"))

    nm = CONFIG.get("name", "config").replace(" ", "_")
    out = G.CACHE / f"econ_fade_{nm}.csv"
    log.to_csv(out, index=False)
    summary = {"config": json.dumps(CONFIG, default=str),
               **{k: (round(float(v), 5) if isinstance(v, (int, float, np.floating)) else str(v))
                  for k, v in G.summarize(CLOSED).items()}}
    pd.Series(summary).to_frame("value").to_csv(G.CACHE / f"econ_fade_{nm}_summary.csv")
    print(f"wrote {out}  ({len(log)} trades)")
""")

md(r"""
## 14. Reading this notebook

**The config is the claim.** A number here is only meaningful alongside the dict that produced it,
which is why the trade log is written out with its config attached.

**Read §9 before §5.** The wrong-day placebo is the single most informative panel in the notebook.
08:30 New York is a liquid, mean-reverting minute whether or not anything printed, and a fade
strategy is exactly the shape that picks that up. If the placebo pays, the release is decoration.

**Read the break-even before the Sharpe.** This strategy turns over once per release and holds for
minutes. At that frequency the cost is not a haircut on the answer, it *is* the answer: an edge of
0.2 bp per trade against a 0.5 bp tick is not a small edge, it is a negative one.

**A knob that looks good is a hypothesis, not a result.** §11 exists because this notebook makes it
cheap to try hundreds of configurations, and the cheapest way to manufacture a Sharpe is to try
enough of them. Read the DSR column before the Sharpe column.

**The tier is ex ante; the surprise is not.** ForexFactory's impact rating is published before the
print, so filtering on it is a rule a desk could have followed. `ActualOutcome` is known only after
the number lands — the `beat forecast` and `missed forecast` rows in §8 describe the sample, they
are not a strategy.
""")

nb = {"cells": cells,
      "metadata": {"kernelspec": {"display_name": "stir", "language": "python", "name": "python3"},
                   "language_info": {"name": "python", "version": "3.12"}},
      "nbformat": 4, "nbformat_minor": 5}
OUT.write_text(json.dumps(nb, indent=1), encoding="utf-8")
print(f"wrote {OUT}  ({len(cells)} cells)")
