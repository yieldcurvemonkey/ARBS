"""Generate econ_release_fade_gridsearch.ipynb -- search the config space honestly."""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "econ_release_fade_gridsearch.ipynb"
REPO = str(HERE.parent.parent.parent)
cells: list = []


def _lines(src): return src.strip("\n").splitlines(keepends=True)
def md(src): cells.append({"cell_type": "markdown", "id": f"md{len(cells):02d}", "metadata": {}, "source": _lines(src)})
def code(src): cells.append({"cell_type": "code", "id": f"cd{len(cells):02d}", "execution_count": None, "metadata": {}, "outputs": [], "source": _lines(src)})


md(r"""
# Fade the release — grid search

`econ_release_fade_backtest.ipynb` reports one configuration and sweeps a knob at a time. This one
runs the **product**: every instrument against every window against every release set against every
move threshold, scored on Sharpe, hit rate and basis points per trade.

That is a dangerous thing to do and the notebook is organised around saying so. With a thousand
configurations, the best Sharpe is a number you would obtain from pure noise. Three things
therefore come **before** the leaderboard:

**§1 ties the fast pricer to the engine.** The grid cannot afford to run `QueryDrivenBacktest` a
thousand times, so it prices arithmetically off the same causal bars. A fast path that is never
checked against the slow one is a second implementation of the strategy rather than an optimisation
of the first, so it is checked here, on the real book, to floating point.

**§4 prices the search.** The Deflated Sharpe discounts the winner by how many configurations were
tried. It is the first column to read, not the last.

**§5 runs the whole grid on the wrong day.** The identical product of configurations, with every
release timestamp shifted onto a minute that had no release. Whatever the leaderboard finds, the
placebo grid finds the same shape if the effect is the clock rather than the release — and comparing
the two *distributions* is far more informative than comparing two single books.

The cost line is drawn on every chart at 0.5 bp, the measured SR3 tick. A configuration whose gross
edge sits below it is not a small opportunity; it is a negative one.
""")

code(rf"""
%load_ext autoreload
%autoreload 2

import sys, json, copy, itertools, time, warnings
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
from econ_fade_prewarm import load_events

RAW = load_events()
n_bars = G.load_bar_cache()
n_dv01 = G.load_dv01()
if n_bars == 0:
    raise RuntimeError("no warm bars -- run `python econ_fade_prewarm.py --stage all` first")

GRID_CSV = G.CACHE / "grid_results.csv"
PLACEBO_CSV = G.CACHE / "grid_results_placebo.csv"

print(f"release book {{len(RAW):,}} minutes   bars {{n_bars:,}} symbol-days   "
      f"DV01 {{n_dv01}} contracts")
""")

# ---------------------------------------------------------------- tie-out
md(r"""
## 1. The fast pricer is the engine

Before a single grid cell is trusted, the closed form is checked against `QueryDrivenBacktest` on
the real book — the same queries, the same position handlers, the same unwinds. They must agree to
floating point, because the engine's realised dollars divided by the position's DV01 *is* the
closed form's basis points, exactly.
""")

code(r"""
BASE = C.spec("base", events={"impacts": ["high", "medium"]})
book = G.build_book(BASE, RAW)
t0 = time.time()
V = G.validate_fast_vs_engine(book, tol=1e-6, show_progress=True)
print(f"engine run took {time.time()-t0:.1f}s for {V['trades_engine']} trades")

checks = [
    ("same trade count", V["trades_engine"] == V["trades_fast"],
     f"{V['trades_engine']} vs {V['trades_fast']}"),
    ("every trade matched by tag", V["matched"] == V["trades_engine"],
     f"{V['matched']}/{V['trades_engine']}"),
    ("P&L agrees to 1e-6 bp", V["n_over_tol"] == 0, f"max |diff| {V['max_abs_diff']:.3e} bp"),
]
display(pd.DataFrame([{"check": c, "result": "PASS" if ok else "FAIL", "value": v}
                      for c, ok, v in checks]).set_index("check"))
assert all(ok for _, ok, _ in checks), "the fast pricer does NOT reproduce the engine"

t0 = time.time()
_ = G.fast_backtest(book)
print(f"closed form took {time.time()-t0:.3f}s for the same book -- which is what makes")
print("a grid of a thousand configurations possible at all.")
""")

# ---------------------------------------------------------------- the grid
md(r"""
## 2. The grid

Five axes. Each is a genuine degree of freedom a desk would have to pick, and each multiplies the
number of ways to find a good-looking number by accident.

| axis | values | why it is a real choice |
|---|---|---|
| instrument | SR3 ranks 1–8, ZQ 1–4, ZT/ZF/ZN/ZB front | where on the curve the release lands |
| release set | tier 1, tier 1+2, 08:30 block, clustered, CPI, payrolls | which prints are worth trading |
| measurement | 1, 2, 5 minutes | how much of the burst the signal sees |
| holding | 15, 30, 60, 120, 240 minutes | how long the fade is given |
| move filter | ≥ 0, ≥ 1, ≥ 2 bp | whether small prints are worth the cost |

Entry is pinned to one minute **after** the measurement window closes throughout, so a longer look
is always paid for with a later entry and no cell fills at the price it read the signal from.
Every price in the grid is the close of a bar that had fully closed by the timestamp — Barchart
minute bars are start-stamped, so the release itself sits *inside* the bar labelled with the release
minute, and reading that bar's close as a pre-release price would measure the drift after the print
rather than the print.
""")

code(r"""
#: The strip is thinned to every rank up to 4 plus 6 and 8 rather than all
#: eight, and the move filter to two values rather than three. Both are stated
#: rather than silently applied: at ~0.35s a configuration the full product is
#: several hours across three grids, and a grid that gets quietly run at a
#: smaller size than its prose claims is worse than a smaller grid.
INSTRUMENTS = (
    [("SR3 r%d" % n, {"family": "stir", "root": "USD_STIR", "rank": n}) for n in (1, 2, 3, 4, 6, 8)] +
    [("ZQ r%d" % n, {"family": "stir", "root": "ZQ", "rank": n}) for n in (1, 2)] +
    [(k, {"family": "ust", "root": k, "rank": 1}) for k in ("TU", "FV", "TY", "US")]
)
RELEASE_SETS = [
    ("tier1", {"impacts": ["high"]}),
    ("tier1+2", {"impacts": ["high", "medium"]}),
    ("0830", {"impacts": ["high", "medium"], "release_times_ny": ["08:30"]}),
    ("clustered", {"impacts": ["high", "medium"], "min_events_in_minute": 2}),
    ("CPI", {"impacts": ["high", "medium"], "titles_include": [r"\bCPI\b"]}),
    ("payrolls", {"impacts": ["high", "medium"],
                  "titles_include": [r"^Non-Farm Employment Change$", r"^Unemployment Rate$"]}),
]
MEASURE = [1, 2, 5]
HOLD = [15, 30, 60, 120, 240]
MOVE = [0.0, 2.0]

def build_grid(direction="fade"):
    out = []
    for (inm, ispec), (rnm, rspec), m, h, mv in itertools.product(
            INSTRUMENTS, RELEASE_SETS, MEASURE, HOLD, MOVE):
        if h <= m + 1:
            continue
        out.append(C.spec(
            f"{inm}|{rnm}|m{m}|h{h}|mv{mv:g}",
            instrument=ispec, events=rspec,
            # Entry is always one minute AFTER the measurement closes: filling at
            # the price the signal was read from is a zero-latency assumption.
            timing={"measure_end_min": m, "entry_offset_min": m + 1, "exit_offset_min": h},
            signal={"direction": direction, "min_move_bp": mv},
        ))
    return out

GRID = build_grid()
print(f"{len(GRID):,} configurations")
print(f"  {len(INSTRUMENTS)} instruments x {len(RELEASE_SETS)} release sets x "
      f"{len(MEASURE)} measurement x {len(HOLD)} holding x {len(MOVE)} move filters")
print(f"  dropped: SR3 ranks 5 and 7, ZQ ranks 3-4, the 1bp move filter, and every")
print(f"  (measure, hold) pair with hold <= measure + 1 -- see the note above the axes")
""")

code(r"""
def run_grid(cfgs, raw, label, csv_path, *, resume=True):
    '''Run every config through the closed form, checkpointing as it goes.

    Resumable by NAME. A grid that has to start over because the kernel died at
    config 900 is a grid that quietly gets run at a smaller size instead.
    '''
    done = {}
    if resume and Path(csv_path).exists():
        prev = pd.read_csv(csv_path)
        done = {r["config"]: r for _, r in prev.iterrows()}
        print(f"resuming {label}: {len(done)} of {len(cfgs)} already scored")

    rows, closed_by = [], {}
    todo = [c for c in cfgs if c["name"] not in done]
    try:
        from tqdm.auto import tqdm
        it = tqdm(todo, desc=label)
    except Exception:
        it = todo

    t0 = time.time()
    n_err, errs = 0, {}
    for cfg in it:
        nm = cfg["name"]
        try:
            r = C.run_config(cfg, raw, engine=False)
        except Exception as ex:
            # Recorded and counted, never swallowed -- a grid that quietly lost
            # an instrument reports a smaller search than it actually ran.
            n_err += 1
            errs.setdefault(f"{type(ex).__name__}: {str(ex)[:90]}", 0)
            errs[f"{type(ex).__name__}: {str(ex)[:90]}"] += 1
            continue
        s = r.stats
        inm, rnm, mm, hh, mv = nm.split("|")
        rows.append({
            "config": nm, "instrument": inm, "release_set": rnm,
            "measure_min": int(mm[1:]), "hold_min": int(hh[1:]), "min_move_bp": float(mv[2:]),
            "trades": s.get("trades", 0), "total_bp": s.get("total_bp", np.nan),
            "avg_bp": s.get("avg_bp", np.nan), "hit_rate": s.get("hit_rate", np.nan),
            "sharpe": s.get("sharpe", np.nan), "sr_per_trade": s.get("sr_per_trade", np.nan),
            "t_stat": s.get("t_stat", np.nan), "max_dd_bp": s.get("max_dd_bp", np.nan),
            "trades_per_year": s.get("trades_per_year", np.nan),
        })
        if not r.closed.empty:
            closed_by[nm] = r.closed.pnl_bp.to_numpy(float)

    new = pd.DataFrame(rows)
    out = pd.concat([pd.DataFrame(list(done.values())), new], ignore_index=True) if done else new
    out.to_csv(csv_path, index=False)
    print(f"{label}: {len(out):,} configs in {time.time()-t0:.0f}s -> {csv_path}")
    if n_err:
        print(f"  {n_err:,} of {len(todo):,} could not be priced and are ABSENT from the table:")
        for msg, k in sorted(errs.items(), key=lambda x: -x[1]):
            print(f"    {k:>5}x  {msg}")
    return out, closed_by

RESULTS, PNL = run_grid(GRID, RAW, "grid", GRID_CSV)
display(RESULTS.describe().round(4))
""")

# ---------------------------------------------------------------- leaderboard
md(r"""
## 3. The leaderboard, with the trade count read first

A configuration with eleven trades and a Sharpe of 3 is not a discovery. The table is filtered to
configurations with enough trades to be an estimate at all, and the gross edge is shown next to the
tick it has to clear.
""")

code(r"""
MIN_TRADES = 50
elig = RESULTS[RESULTS.trades >= MIN_TRADES].copy()
elig["gross_vs_tick"] = elig.avg_bp - 0.5
print(f"{len(elig):,} of {len(RESULTS):,} configurations have >= {MIN_TRADES} trades")

top = elig.sort_values("sharpe", ascending=False).head(25)
display(top[["config", "instrument", "release_set", "measure_min", "hold_min", "min_move_bp",
             "trades", "avg_bp", "hit_rate", "sharpe", "t_stat", "max_dd_bp"]]
        .set_index("config").round(4))

fig, axes = plt.subplots(1, 3, figsize=(20, 4.6))
axes[0].hist(elig.sharpe, bins=60, color="steelblue", edgecolor="k", lw=.3)
axes[0].axvline(0, color="k", lw=.8)
axes[0].axvline(elig.sharpe.max(), color="crimson", lw=2, label=f"best {elig.sharpe.max():.2f}")
axes[0].set_title(f"annualised Sharpe across {len(elig):,} configurations"); axes[0].legend()

axes[1].hist(elig.avg_bp, bins=60, color="darkslateblue", edgecolor="k", lw=.3)
axes[1].axvline(0, color="k", lw=.8)
axes[1].axvline(0.5, color="crimson", lw=2, ls="--", label="SR3 tick 0.5bp")
axes[1].axvline(0.25, color="darkorange", lw=1.6, ls=":", label="half tick")
axes[1].set_xlabel("gross bp per trade"); axes[1].legend()
axes[1].set_title("edge per trade against the tick")

sc = axes[2].scatter(elig.trades, elig.avg_bp, c=elig.sharpe, cmap="RdYlGn",
                     s=14, alpha=.75, vmin=-2, vmax=2)
axes[2].axhline(0, color="k", lw=.7); axes[2].axhline(0.5, color="crimson", ls="--", lw=1.4)
axes[2].set_xscale("log"); axes[2].set_xlabel("trades (log)"); axes[2].set_ylabel("gross bp / trade")
axes[2].set_title("the small-sample corner is where big numbers live")
plt.colorbar(sc, ax=axes[2], label="Sharpe")
plt.tight_layout(); plt.show()

n_clear = int((elig.avg_bp > 0.5).sum())
print(f"\nconfigurations whose GROSS edge clears one SR3 tick (0.5bp): {n_clear} of {len(elig)}")
print(f"configurations with a positive gross edge at all: {int((elig.avg_bp > 0).sum())}")
""")

code(r"""
# Which axis actually moves the answer? A marginal that is flat is a knob that
# was never worth turning, and one that is steep is a knob the search exploited.
fig, axes = plt.subplots(2, 3, figsize=(20, 8))
for ax, col in zip(axes.ravel(),
                   ["instrument", "release_set", "measure_min", "hold_min", "min_move_bp"]):
    g = elig.groupby(col).agg(sharpe=("sharpe", "median"), avg_bp=("avg_bp", "median"),
                              n=("sharpe", "size"))
    ax.bar(g.index.astype(str), g.sharpe,
           color=["seagreen" if v > 0 else "indianred" for v in g.sharpe], alpha=.85)
    for i, (nm, r) in enumerate(g.iterrows()):
        ax.text(i, r.sharpe, f"{int(r.n)}", ha="center", fontsize=7)
    ax.axhline(0, color="k", lw=.7); ax.set_title(f"median Sharpe by {col}")
    ax.tick_params(axis="x", rotation=60)
axes.ravel()[-1].axis("off")
plt.tight_layout(); plt.show()

piv = elig.pivot_table(index="instrument", columns="hold_min", values="avg_bp", aggfunc="median")
piv2 = elig.pivot_table(index="release_set", columns="hold_min", values="avg_bp", aggfunc="median")
fig, axes = plt.subplots(1, 2, figsize=(17, 5))
sns.heatmap(piv, annot=True, fmt=".2f", cmap="RdYlGn", center=0, ax=axes[0],
            cbar_kws={"label": "median gross bp / trade"})
axes[0].set_title("instrument x holding period")
sns.heatmap(piv2, annot=True, fmt=".2f", cmap="RdYlGn", center=0, ax=axes[1],
            cbar_kws={"label": "median gross bp / trade"})
axes[1].set_title("release set x holding period")
plt.tight_layout(); plt.show()
""")

# ---------------------------------------------------------------- DSR
md(r"""
## 4. What the search cost

The Deflated Sharpe compares each configuration against `E[max Sharpe]` under the null that all of
them have zero edge, with the null's variance taken from the spread of Sharpes the grid actually
produced. It is generous here — these configurations overlap heavily in the same release minutes,
so they are nothing like the independent trials the formula assumes, and the true hurdle is higher
than the one printed below.

A configuration is called **ALIVE** only if it clears three bars at once: DSR above 0.95, at least
50 trades, and a gross edge above the 0.5 bp tick. The last is not a statistical test — it is the
difference between a result and a bill.
""")

code(r"""
# PNL holds only the configurations scored in THIS kernel. On a resumed run the
# summary CSV is complete but the per-trade series are not, and a DSR computed
# from a partial set would silently use a smaller trial count -- which flatters
# the winner. Say so rather than quietly deflating by the wrong number.
if len(PNL) < len(RESULTS):
    print(f"WARNING: per-trade series available for {len(PNL):,} of {len(RESULTS):,} "
          f"configurations (the rest were resumed from CSV).")
    print("The deflation below therefore uses a SMALLER trial count than the grid actually")
    print("ran, so it is too generous. Re-run with a fresh grid_results.csv for the honest number.")

sr_pt = {nm: (v.mean() / v.std(ddof=1)) if v.std(ddof=1) > 0 else 0.0
         for nm, v in PNL.items() if len(v) >= MIN_TRADES}
n_trials = max(len(sr_pt), 1)
var_sr = float(np.var(list(sr_pt.values()), ddof=1)) if len(sr_pt) > 1 else 0.0
sr_star = G.expected_max_sharpe(var_sr, n_trials)
print(f"{n_trials:,} configurations scored   selection hurdle sr* = {sr_star:.4f} per trade   "
      f"(variance of observed Sharpes {var_sr:.5f})")

dsr = pd.DataFrame([
    {"config": nm, "trades": len(v), "sr_per_trade": sr_pt[nm], "avg_bp": v.mean(),
     "total_bp": v.sum(), "dsr": G.deflated_sharpe(v, sr_star)}
    for nm, v in PNL.items() if nm in sr_pt
]).sort_values("dsr", ascending=False).set_index("config")
display(dsr.head(20).round(4))

alive = dsr[(dsr.dsr > 0.95) & (dsr.trades >= MIN_TRADES) & (dsr.avg_bp > 0.5)]
print(f"\nALIVE (DSR > 0.95, >= {MIN_TRADES} trades, gross edge > one 0.5bp tick): "
      f"{len(alive)} of {len(dsr)}")
if len(alive):
    display(alive.round(4))
else:
    passes_dsr = int(((dsr.dsr > 0.95) & (dsr.trades >= MIN_TRADES)).sum())
    print(f"  ({passes_dsr} clear the statistical bar but not the cost bar)")

fig, axes = plt.subplots(1, 2, figsize=(16, 4.6))
axes[0].hist(list(sr_pt.values()), bins=60, color="lightgrey", edgecolor="k", lw=.3)
axes[0].axvline(sr_star, color="crimson", lw=2, label=f"hurdle {sr_star:.3f}")
axes[0].set_xlabel("Sharpe per trade"); axes[0].legend()
axes[0].set_title("the search creates its own hurdle")
axes[1].scatter(dsr.avg_bp, dsr.dsr, s=14, alpha=.6, color="darkslateblue")
axes[1].axhline(0.95, color="crimson", ls="--", lw=1.5, label="DSR 0.95")
axes[1].axvline(0.5, color="darkorange", ls="--", lw=1.5, label="SR3 tick")
axes[1].set_xlabel("gross bp / trade"); axes[1].set_ylabel("deflated Sharpe"); axes[1].legend()
axes[1].set_title("the top-right quadrant is the only one that matters")
plt.tight_layout(); plt.show()
""")

# ---------------------------------------------------------------- placebo grid
md(r"""
## 5. The same grid on a day with no release

Every timestamp shifted forward one **business** day. Same instruments, same clock, same windows,
same causal gate — no release.

Business days, not calendar days: a calendar +1 sends every Friday release to a Saturday, where the
gate deletes it, and payrolls is a Friday release. The composition table below has to show the
placebo keeping essentially every weekday, or the two distributions differ because the sample
changed rather than because the news went away.

This is the strongest single test in either notebook, and it is stronger as a **distribution** than
as a single book. If the real grid's Sharpes are drawn from the same distribution as the placebo
grid's, then the release contributes nothing and every number above is a description of what
happens at 08:30 in the Treasury market on any given morning.
""")

code(r"""
RAW_PLACEBO = C.placebo_shift(RAW, days=1)   # business day; real release minutes removed
display(C.placebo_composition(RAW, RAW_PLACEBO).rename_axis("release weekday"))
print(f"real {len(RAW):,} release minutes -> placebo {len(RAW_PLACEBO):,}\n")

PLACEBO, PNL_P = run_grid(build_grid(), RAW_PLACEBO, "placebo", PLACEBO_CSV)

pe = PLACEBO[PLACEBO.trades >= MIN_TRADES]
rows = []
for nm, d in (("REAL releases", elig), ("wrong day (+1)", pe)):
    rows.append({"grid": nm, "configs": len(d),
                 "median sharpe": d.sharpe.median(), "mean sharpe": d.sharpe.mean(),
                 "best sharpe": d.sharpe.max(),
                 "median bp/trade": d.avg_bp.median(), "best bp/trade": d.avg_bp.max(),
                 "% positive": float((d.avg_bp > 0).mean()),
                 "% clearing a tick": float((d.avg_bp > 0.5).mean())})
display(pd.DataFrame(rows).set_index("grid").round(4))

from scipy.stats import mannwhitneyu, ks_2samp
if len(pe) and len(elig):
    u = mannwhitneyu(elig.avg_bp.dropna(), pe.avg_bp.dropna(), alternative="two-sided")
    k = ks_2samp(elig.sharpe.dropna(), pe.sharpe.dropna())
    print(f"\nreal against placebo, bp per trade: Mann-Whitney p = {u.pvalue:.4g}")
    print(f"real against placebo, Sharpe:        KS p = {k.pvalue:.4g}")
    if u.pvalue > 0.05:
        print("\nThe two grids are indistinguishable. Whatever the leaderboard found, a day with")
        print("no release finds the same thing -- this is the clock, not the release.")
    else:
        better = elig.avg_bp.median() - pe.avg_bp.median()
        print(f"\nThe grids differ. Real releases pay {better:+.4f} bp/trade more at the median.")
        print("That gap, not the leaderboard's best cell, is the size of the effect.")

fig, axes = plt.subplots(1, 3, figsize=(20, 4.6))
axes[0].hist(pe.sharpe, bins=50, alpha=.6, label="wrong day", color="grey", density=True)
axes[0].hist(elig.sharpe, bins=50, alpha=.6, label="real releases", color="seagreen", density=True)
axes[0].axvline(0, color="k", lw=.8); axes[0].legend(); axes[0].set_xlabel("Sharpe")
axes[0].set_title("Sharpe: real against placebo")
axes[1].hist(pe.avg_bp, bins=50, alpha=.6, label="wrong day", color="grey", density=True)
axes[1].hist(elig.avg_bp, bins=50, alpha=.6, label="real releases", color="seagreen", density=True)
axes[1].axvline(0, color="k", lw=.8); axes[1].axvline(0.5, color="crimson", ls="--", lw=1.5,
                                                      label="SR3 tick")
axes[1].legend(); axes[1].set_xlabel("gross bp / trade")
axes[1].set_title("edge per trade: real against placebo")

m = elig[["config", "avg_bp"]].merge(pe[["config", "avg_bp"]], on="config",
                                     suffixes=("_real", "_placebo"))
if len(m):
    axes[2].scatter(m.avg_bp_placebo, m.avg_bp_real, s=12, alpha=.5, color="darkslateblue")
    lim = [min(m.avg_bp_placebo.min(), m.avg_bp_real.min()),
           max(m.avg_bp_placebo.max(), m.avg_bp_real.max())]
    axes[2].plot(lim, lim, color="crimson", lw=1.4, ls="--", label="y = x")
    axes[2].axhline(0, color="k", lw=.6); axes[2].axvline(0, color="k", lw=.6)
    axes[2].set_xlabel("wrong day, bp/trade"); axes[2].set_ylabel("real, bp/trade"); axes[2].legend()
    axes[2].set_title("config by config — above the line is release-specific")
plt.tight_layout(); plt.show()
""")

# ---------------------------------------------------------------- momentum grid
md(r"""
## 6. The same grid, faded the other way

`momentum` is the identical set of trades with the sign reversed. Gross of cost the two grids must
be near mirror images of each other, and a scatter of one against the other must sit on the line
`y = -x`. If it does not, the P&L is not coming from the direction of the initial move — it is
coming from the sizing, the gate, or the marking, and none of those is the strategy.

This is a check on the machinery rather than on the idea. Because the closed form negates exactly —
same events, same prices, flipped side — it verifies one function, `apply_signal`'s flip, and a
sample of the grid proves that as well as the whole grid would. **Every fifth configuration is run**,
and the count is printed so the sample is not mistaken for the full product. It is also the check
that catches a sign error, which is the single most common way a fade backtest becomes a momentum
backtest without anyone noticing.
""")

code(r"""
MOM_SAMPLE = build_grid("momentum")[::5]
print(f"momentum grid: running {len(MOM_SAMPLE):,} of {len(build_grid('momentum')):,} "
      f"configurations (every 5th) -- the closed form negates exactly, so this checks the")
print("sign flip rather than searching a second config space.")
MOM, PNL_M = run_grid(MOM_SAMPLE, RAW, "momentum",
                      G.CACHE / "grid_results_momentum.csv")
me = MOM[MOM.trades >= MIN_TRADES]

j = elig[["config", "avg_bp", "trades"]].merge(
    me[["config", "avg_bp"]], on="config", suffixes=("_fade", "_mom"))
j["sum"] = j.avg_bp_fade + j.avg_bp_mom
print(f"{len(j):,} configurations present in both grids")
print(f"fade + momentum, per trade: mean {j['sum'].mean():+.6f} bp, "
      f"max |{j['sum'].abs().max():.6f}| bp")
print("(both books pay the same zero cost here, so the pair must sum to zero within the")
print(" rounding of the tick lattice -- a systematic offset would be a marking bug)")

fig, axes = plt.subplots(1, 2, figsize=(16, 4.6))
axes[0].scatter(j.avg_bp_mom, j.avg_bp_fade, s=12, alpha=.5, color="darkslateblue")
lim = [j.avg_bp_mom.min(), j.avg_bp_mom.max()]
axes[0].plot(lim, [-v for v in lim], color="crimson", lw=1.5, ls="--", label="y = -x")
axes[0].set_xlabel("momentum bp/trade"); axes[0].set_ylabel("fade bp/trade"); axes[0].legend()
axes[0].set_title("fade against momentum, config by config")
axes[1].hist(j["sum"], bins=60, color="steelblue", edgecolor="k", lw=.3)
axes[1].axvline(0, color="crimson", lw=2)
axes[1].set_xlabel("fade + momentum (bp/trade)")
axes[1].set_title("the residual — should be a spike at zero")
plt.tight_layout(); plt.show()
""")

# ---------------------------------------------------------------- costs
md(r"""
## 7. The whole grid, net of a real cost

Every configuration re-scored at a round trip a desk would actually pay. This strategy trades once
per release and holds for minutes, so cost is not a haircut on the answer — at this frequency it
*is* the answer.

The count that matters is the last column: how many of a thousand configurations are still standing
at each cost. If that number goes to zero by half a tick, the search found nothing tradeable no
matter how the leaderboard looked at zero.
""")

code(r"""
rows = []
for c in [0.0, 0.1, 0.25, 0.5, 0.75, 1.0]:
    net_avg = elig.avg_bp - c
    # Sharpe scales with the mean, so the net Sharpe is the gross one shifted by
    # the cost in units of the per-trade standard deviation.
    sd = elig.avg_bp / elig.sr_per_trade.replace(0, np.nan)
    net_sr = (elig.avg_bp - c) / sd * np.sqrt(elig.trades_per_year)
    rows.append({"cost_bp_rt": c, "median bp/trade": net_avg.median(),
                 "best bp/trade": net_avg.max(), "median sharpe": net_sr.median(),
                 "best sharpe": net_sr.max(),
                 "configs profitable": int((net_avg > 0).sum()),
                 "configs w/ sharpe > 1": int((net_sr > 1).sum())})
cost_tbl = pd.DataFrame(rows).set_index("cost_bp_rt")
display(cost_tbl.round(4))

fig, axes = plt.subplots(1, 2, figsize=(16, 4.4))
axes[0].plot(cost_tbl.index, cost_tbl["configs profitable"], marker="o", lw=2,
             color="seagreen", label="profitable")
axes[0].plot(cost_tbl.index, cost_tbl["configs w/ sharpe > 1"], marker="s", lw=2,
             color="darkslateblue", label="Sharpe > 1")
axes[0].axvline(0.5, color="crimson", ls="--", lw=1.5, label="SR3 tick")
axes[0].set_xlabel("round-trip cost (bp)"); axes[0].set_ylabel("configurations")
axes[0].set_title(f"survivors out of {len(elig):,}"); axes[0].legend()
axes[1].plot(cost_tbl.index, cost_tbl["median bp/trade"], marker="o", lw=2, label="median")
axes[1].plot(cost_tbl.index, cost_tbl["best bp/trade"], marker="s", lw=2, label="best")
axes[1].axhline(0, color="k", lw=.8); axes[1].axvline(0.5, color="crimson", ls="--", lw=1.5)
axes[1].set_xlabel("round-trip cost (bp)"); axes[1].set_ylabel("bp / trade"); axes[1].legend()
axes[1].set_title("edge per trade net of cost")
plt.tight_layout(); plt.show()
""")

# ---------------------------------------------------------------- winner
md(r"""
## 8. The winner, run properly

Whatever the grid picked, it is picked on the closed form. Here it is re-run through the real
engine and given the full robustness treatment — because a grid winner is a hypothesis, and the
one thing that is certain about it is that it was selected for looking good.
""")

code(r"""
best_name = elig.sort_values("sharpe", ascending=False).index[0] if elig.index.name == "config" \
    else elig.sort_values("sharpe", ascending=False).iloc[0]["config"]
best_cfg = next(c for c in GRID if c["name"] == best_name)
print("grid winner:", json.dumps({k: v for k, v in best_cfg.items()
                                  if k in ("name", "instrument", "events", "timing", "signal")},
                                 indent=1, default=str))

BEST = C.run_config(best_cfg, RAW, engine=True, show_progress=True)
B = BEST.closed
display(pd.Series(G.summarize(B)).to_frame("engine run").T.round(4))

perm = G.sign_flip_permutation(B, n_perm=5000)
lo, hi = G.bootstrap_ci(B.pnl_bp.to_numpy(float))
print(f"sign-flip permutation p = {perm['p_value']:.4f}   "
      f"bootstrap 95% CI on the mean [{lo:+.4f}, {hi:+.4f}] bp")
print(f"break-even round trip: {B.pnl_bp_gross.mean():+.4f} bp "
      f"({'clears' if B.pnl_bp_gross.mean() > 0.5 else 'does NOT clear'} one SR3 tick)")

pl = C.run_config(best_cfg, C.placebo_shift(RAW, days=1), engine=False)
print(f"same config on the wrong day: {pl.stats.get('trades', 0)} trades, "
      f"{pl.stats.get('avg_bp', float('nan')):+.4f} bp/trade")

fig, axes = plt.subplots(1, 3, figsize=(20, 4.4))
axes[0].plot(B.release_ts.values, B.pnl_bp.cumsum().values, lw=2, color="darkslateblue",
             label="grid winner (engine)")
if not pl.closed.empty:
    axes[0].plot(pl.closed.release_ts.values, pl.closed.pnl_bp.cumsum().values, lw=1.2,
                 ls="--", color="grey", label="wrong day")
axes[0].axhline(0, color="k", lw=.6); axes[0].legend(); axes[0].set_ylabel("cumulative bp")
axes[0].set_title(best_name, fontsize=9)
axes[1].hist(perm["perm"], bins=60, color="lightgrey", edgecolor="k", lw=.3)
axes[1].axvline(perm["realized_sharpe"], color="crimson", lw=2)
axes[1].set_title(f"sign-flip permutation p={perm['p_value']:.4f}")
y = B.groupby("year").pnl_bp.sum()
axes[2].bar(y.index.astype(str), y.values,
            color=["seagreen" if v > 0 else "indianred" for v in y.values], alpha=.85)
axes[2].axhline(0, color="k", lw=.6); axes[2].set_title("total bp by year")
plt.tight_layout(); plt.show()
""")

md(r"""
## 9. Reading this notebook

**The leaderboard is the least informative table here.** With a thousand configurations its top row
is an order statistic. §4 tells you what that order statistic is worth, and §5 tells you whether the
whole distribution it came from is any different from noise.

**The placebo grid is the result.** Not the winner — the *gap* between the two distributions. If
real releases and wrong days produce the same spread of Sharpes, there is nothing here, and no
amount of further slicing will change that. If they differ, the size of the difference at the
median is the honest estimate of the effect, and it will be much smaller than the best cell.

**The tick line is not decoration.** A configuration trading a hundred times a year at 0.3 bp gross
is losing 20 bp a year against a 0.5 bp round trip. Half the panels here draw that line because it
is the constraint the whole idea has to beat, and it does not care how significant the t-statistic
is.

**Reruns are resumable and the CSVs are the record.** `grid_results.csv`, `grid_results_placebo.csv`
and `grid_results_momentum.csv` hold every configuration scored, so a claim made from this notebook
can be checked against the row that produced it.
""")

nb = {"cells": cells,
      "metadata": {"kernelspec": {"display_name": "stir", "language": "python", "name": "python3"},
                   "language_info": {"name": "python", "version": "3.12"}},
      "nbformat": 4, "nbformat_minor": 5}
OUT.write_text(json.dumps(nb, indent=1), encoding="utf-8")
print(f"wrote {OUT}  ({len(cells)} cells)")
