"""Generate econ_release_fade_exits_backtest.ipynb -- exit at a LEVEL, not at a clock."""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "econ_release_fade_exits_backtest.ipynb"
REPO = str(HERE.parent.parent.parent)
cells: list = []


def _lines(src): return src.strip("\n").splitlines(keepends=True)
def md(src): cells.append({"cell_type": "markdown", "id": f"md{len(cells):02d}", "metadata": {}, "source": _lines(src)})
def code(src): cells.append({"cell_type": "code", "id": f"cd{len(cells):02d}", "execution_count": None, "metadata": {}, "outputs": [], "source": _lines(src)})


md(r"""
# Fade the release, exit at a level

Every other notebook in this folder unwinds on a **clock**: enter at T+2, leave at T+60, whatever the
price did in between. This one unwinds on a **level** — a take-profit, a stop, an optional trailing
stop, and a time stop only as the backstop. That is a different strategy, not a different report, and
it needs its own book because the exit is now path-dependent.

### Why the exit rule has to go through the engine

A clock exit can be priced by arithmetic: two timestamps, two prices, done. A level exit cannot. The
question "did this trade touch −1.5 bp before it touched +0.25 bp" is answered by walking the path
minute by minute, and the answer depends on market state at each step. That is exactly the job
`QueryDrivenBacktest` exists to do, so the headline book here is built by the **real
`USTFuturesMDP` + engine**, with the fetcher disarmed for the whole run.

The fast path exists too, because a sweep over hundreds of brackets cannot afford an engine build per
cell. It is only trustworthy because §4 ties it back to the engine and **asserts** they agree.

### `mode="close"` is not a detail

`ExitRule` defaults to `mode="intrabar"`, which triggers off the bar's High/Low. The engine cannot see
inside a bar — it polls once a minute and sees closes. So an intrabar rule and the engine disagree by
construction, and every tie-out in this study that passed did so in `"close"` mode. This notebook
defaults to `"close"` throughout: a desk polling the screen once a minute, which is both what the
engine can verify and the more conservative of the two.

### The two ways this strategy flatters itself

**A stop is a cost, not a saving.** A stop fill crosses the spread *and* slips, so a stop-heavy rule
is charged roughly twice a round trip. `stop_slip_ticks` is set to a full tick for that reason.

**A fractional bracket is scale-free and an absolute one is not.** A 12 bp CPI burst and a 1 bp burst
do not deserve the same absolute target, so `tp_frac`/`sl_frac` scale with the trade's own move. Both
parameterisations are swept in §6 and the family correction in §8 is charged for both.

---

> **Known before this notebook starts.** The clock-exit fade on raw releases loses. This notebook asks
> whether a *level* exit rescues it, on the one release (CPI) and one instrument (TY) where the raw
> study was least hopeless. If it does not, that is the answer.
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
import matplotlib.dates as mdates

warnings.filterwarnings("ignore")
pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 50)
plt.rcParams.update({{"figure.dpi": 110, "axes.grid": True, "grid.alpha": 0.25,
                     "axes.spines.top": False, "axes.spines.right": False,
                     "font.size": 9, "figure.autolayout": True}})

import econ_fade_common as G
import econ_fade_config as C
import econ_fade_exits as X
import econ_fade_mdp_exits as MX
import econ_fade_plotly as P
from econ_fade_prewarm import load_events

from RVUtils.StatisticalFinance import (
    ras_bound, romano_wolf, selection_bias_pvalue, shared_sign_flip_null, timer_pvalue,
)

print("modules loaded")
""")

md(r"""
## 1. The configuration

Everything the strategy does is in this cell. `EVENTS` selects which releases, `SIGNAL` decides the
side and how big a burst is worth trading, `BRACKET` is the exit, and `COST_BP` is what a round trip
costs.

One ZN tick is 1/64 of a point, about **0.2389 bp** of yield on the 10-year, and the bid-ask is a tick
wide — so a round trip that crosses it costs about one tick. That is the number every P&L in this
notebook is net of.
""")

code(r"""
# ---------------------------------------------------------------- the knobs
NAME       = "cpi_ty"
INSTRUMENT = {"family": "ust", "root": "TY", "rank": 1}

EVENTS = {"currencies": ["USD"], "impacts": ["high", "medium"], "require_actual": True,
          "include_cb_decisions": False, "titles_include": [r"\bCPI\b"]}

TIMING = {"measure_start_min": 0, "measure_end_min": 1, "entry_offset_min": 2,
          "exit_offset_min": 60}

SIGNAL = {"direction": "fade",      # fade | momentum
          "min_move_bp": 3.0}       # only trade a burst at least this big

BRACKET = dict(tp_frac=0.25,        # target = 25% of THIS trade's own burst
               sl_frac=1.5,         # stop   = 150% of it
               tp_bp=None, sl_bp=None,
               trail_bp=None,       # None | bp; a trail forces the slow path
               time_stop_min=118,   # backstop only
               min_hold_min=0,
               stop_slip_ticks=1.0,
               mode="close")        # "close" is what the ENGINE can see -- see the intro

COST_BP = 0.2389                    # one ZN tick, one round trip

# ------------------------------------------------------------- derived once
CFG  = C.spec(NAME, instrument=INSTRUMENT, events=EVENTS, timing=TIMING, signal=SIGNAL)
RULE = X.ExitRule(name="headline", **BRACKET)

print(json.dumps(CFG, indent=1, default=str))
print()
print("bracket:", RULE)
""")

md(r"""
## 2. Data, book, and the funnel

`load_events` reads the ForexFactory calendar; `bars.pkl` is the warmed Barchart minute cache;
`dv01.json` is the measured per-contract DV01 that converts price into basis points.

The **funnel** is the part worth reading. It accounts for every calendar event that did not become a
trade, so a book that looks clean because it quietly dropped two thirds of its events cannot hide.
""")

code(r"""
t0 = time.time()
G.load_bar_cache()
G.load_dv01()
raw = load_events()
print(f"loaded in {time.time()-t0:.1f}s   {len(raw):,} release minutes, "
      f"{raw['release_ts'].min()} .. {raw['release_ts'].max()}")

book = X.build_base_book(CFG, raw)
print(f"\nbook: {len(book.events):,} tradeable events on {book.instrument.root}")
print("\n--- funnel: why every other event is not here ---")
for k, v in book.funnel.items():
    print(f"  {k:28s} {v}")
""")

code(r"""
ev = book.events.copy()
ev["ny"] = pd.to_datetime(ev["release_ts"], utc=True).dt.tz_convert("America/New_York")
print("the book, by year and by contract")
print(pd.crosstab(ev["ny"].dt.year, ev["symbol"]).to_string())
print(f"\nburst size (bp):  mean {ev.move_bp.abs().mean():.2f}   "
      f"median {ev.move_bp.abs().median():.2f}   max {ev.move_bp.abs().max():.2f}")
ev[["release_ts", "symbol", "move_bp", "side", "entry_px", "px_per_bp"]].head(8)
""")

md(r"""
## 3. The engine run

`prime_ust_cache` writes the warmed bars into the MDP's **own** DiskCache under its exact key
contract, then `open_ust_mdp(armed=False)` replaces the Barchart fetcher with a raise. From that point
"no network was used" is a property the run *enforces* rather than a claim — if the cache misses a
minute the run raises `NetworkForbidden` instead of quietly reaching out.

Note the prime covers **every minute of the holding window**, not just entry and exit: the engine
marks the open position to market at each step of the grid, so any gap is a real hole.
""")

code(r"""
mdp = MX.open_ust_mdp(armed=False)          # fetcher disarmed for the whole notebook
wanted = MX.wanted_minutes(book.events, RULE.time_stop_min)
print(f"{len(wanted):,} (symbol, minute) pairs the engine may ask for")

t0 = time.time()
stats = MX.prime_ust_cache(mdp, wanted, show_progress=False)
print(f"primed in {time.time()-t0:.1f}s: {stats}")
print(f"  coverage: {stats['written'] / max(1, len(wanted)) * 100:.1f}% of requested minutes had a real bar")
print("  (a minute with no print stays a MISS -- the MDP resolves to the nearest bar, so writing")
print("   a neighbour's price would fabricate one)")
""")

code(r"""
t0 = time.time()
engine = MX.run_bracket_engine(book, RULE, mdp, cost_bp=COST_BP, show_progress=False)
print(f"engine booked {len(engine):,} trades in {time.time()-t0:.1f}s")
# the engine returns the PORTFOLIO's closed-position log, so its columns are the
# engine's own -- entry_px, realized_pnl, holding_period_steps -- not the fast
# path's bar-level bookkeeping.
engine[["release_ts", "symbol", "move_bp", "side", "entry_px", "exit_reason",
        "hold_min", "dv01_usd", "realized_pnl", "pnl_bp_gross", "pnl_bp"]].head(10)
""")

md(r"""
## 4. Tie-out — the fast path must reproduce the engine exactly

Everything after this section uses `run_bracket_fast`, which is the same fill model without the
engine build. That is only legitimate if the two agree, so this cell **asserts** it: same trade count,
same exit reason on every trade, and P&L identical to floating point.

This tie-out is not ceremony. It failed the first time it was run — max |diff| 13.5 bp and exit
reasons matching on only 73 of 84 trades — and the four bugs it exposed are recorded in the PR. A
check that has never failed is a check you have not tested.
""")

code(r"""
fast = MX.run_bracket_fast(book, RULE, cost_bp=COST_BP)
print(f"engine {len(engine):,} trades   fast {len(fast):,} trades")

a = engine.set_index("tag").sort_index()
b = fast.set_index("tag").sort_index()
shared = a.index.intersection(b.index)
assert len(shared) == len(a) == len(b), (
    f"trade sets differ: engine {len(a)}, fast {len(b)}, shared {len(shared)}")

dpnl = (a.loc[shared, "pnl_bp"] - b.loc[shared, "pnl_bp"]).abs()
same_reason = int((a.loc[shared, "exit_reason"] == b.loc[shared, "exit_reason"]).sum())
print(f"max |pnl_bp diff|   : {dpnl.max():.3e}")
print(f"exit reasons agree  : {same_reason} / {len(shared)}")

assert dpnl.max() < 1e-9, f"fast path disagrees with the engine by {dpnl.max():.4f} bp"
assert same_reason == len(shared), "fast path picks a different exit reason"
print("\nTIE-OUT PASSED -- the fast path is the engine, and the sweeps below are legitimate")
""")

md(r"""
## 5. What the headline configuration is worth
""")

code(r"""
def stats_of(df, label="book"):
    p = df["pnl_bp"].to_numpy(float)
    wins, losses = p[p > 0], p[p <= 0]
    sd = p.std(ddof=1) if len(p) > 1 else 0.0
    return {
        "label": label, "trades": len(p), "hit_rate": float((p > 0).mean()),
        "gross_bp": float(df["pnl_bp_gross"].mean()), "net_bp": float(p.mean()),
        "total_net_bp": float(p.sum()),
        "avg_win": float(wins.mean()) if len(wins) else np.nan,
        "avg_loss": float(losses.mean()) if len(losses) else np.nan,
        "payoff": float(wins.mean() / abs(losses.mean())) if len(wins) and len(losses) else np.nan,
        "sr_per_trade": float(p.mean() / sd) if sd > 0 else 0.0,
        "t_stat": float(p.mean() / (sd / np.sqrt(len(p)))) if sd > 0 else 0.0,
        "avg_hold_min": float(df["hold_min"].mean()),
        "pct_target": float((df.exit_reason == "target").mean()),
        "pct_stop": float(df.exit_reason.isin(["stop", "trail"]).mean()),
        "pct_time": float((df.exit_reason == "time_stop").mean()),
    }

hl = stats_of(engine, "headline (engine)")
print(pd.Series(hl).to_frame("value").to_string())
print()
print("read it as: a", f"{hl['hit_rate']*100:.1f}%", "hit rate paying", f"{hl['net_bp']:+.4f}",
      "bp per trade net of one tick, t =", f"{hl['t_stat']:.2f}")
""")

code(r"""
fig, ax = plt.subplots(2, 2, figsize=(11.5, 7))

d = engine.sort_values("release_ts")
ts = pd.to_datetime(d["release_ts"], utc=True).dt.tz_convert("America/New_York")
ax[0, 0].plot(ts, d["pnl_bp"].cumsum(), lw=1.6, color="#1f77b4")
ax[0, 0].axhline(0, color="k", lw=0.8)
ax[0, 0].set_title(f"cumulative net bp  ({len(d)} trades)")
ax[0, 0].xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

ax[0, 1].hist(d["pnl_bp"], bins=25, color="#4c72b0", edgecolor="white")
ax[0, 1].axvline(0, color="k", lw=0.8)
ax[0, 1].axvline(d["pnl_bp"].mean(), color="crimson", lw=1.4,
                 label=f"mean {d['pnl_bp'].mean():+.3f}")
ax[0, 1].legend(); ax[0, 1].set_title("net bp per trade")

mix = d["exit_reason"].value_counts()
ax[1, 0].bar(range(len(mix)), mix.values, color="#55a868")
ax[1, 0].set_xticks(range(len(mix))); ax[1, 0].set_xticklabels(mix.index, rotation=20)
ax[1, 0].set_title("how trades ended")
for i, v in enumerate(mix.values):
    ax[1, 0].text(i, v, str(v), ha="center", va="bottom", fontsize=8)

ax[1, 1].scatter(d["move_bp"].abs(), d["pnl_bp"], s=18, alpha=0.7, color="#c44e52")
ax[1, 1].axhline(0, color="k", lw=0.8)
ax[1, 1].set_xlabel("|burst| bp"); ax[1, 1].set_ylabel("net bp")
ax[1, 1].set_title("does a bigger burst pay more?")
plt.show()
""")

code(r"""
print("by exit reason -- where the money actually comes from")
g = engine.groupby("exit_reason").agg(
    trades=("pnl_bp", "size"), net_bp=("pnl_bp", "mean"), total_bp=("pnl_bp", "sum"),
    avg_hold=("hold_min", "mean")).round(4)
g["share"] = (g.trades / g.trades.sum()).round(3)
print(g.to_string())

print("\nby year")
d = engine.copy()
d["year"] = pd.to_datetime(d["release_ts"], utc=True).dt.tz_convert("America/New_York").dt.year
print(d.groupby("year").agg(trades=("pnl_bp", "size"), net_bp=("pnl_bp", "mean"),
                            hit=("pnl_bp", lambda s: float((s > 0).mean()))).round(4).to_string())
""")

md(r"""
### 5.1 The book, interactively

Every trade with its whole record attached: the release that triggered it, the size of the burst,
which way it went, both prices, the hold, why it ended, and what it paid gross and net. The crosshair
runs through all four panels, so a trade on the equity curve lines up against its own drawdown and
its own signal.

For a **level** exit the panel to read first is the per-trade bar coloured by `exit_reason`. A book
that mostly hits its target and a book that mostly times out can post the same mean and are not the
same strategy — one is being paid for the level and the other is being paid for the clock.
""")

code(r"""
SPAN_YEARS = (pd.Timestamp("2026-08-07") - pd.Timestamp("2019-01-03")).days / 365.25
fig = P.trade_dashboard(engine, title=f"CPI x {book.instrument.root} bracket | {RULE.name}",
                        span_years=SPAN_YEARS, signal_col="move_bp")
fig.show()
""")

md(r"""
### 5.2 The bracket against the alternatives it has to beat

Three books on the same trades: the configured bracket, the same trades held to the time stop with
no levels at all, and the pure clock exit the rest of this study uses. If the bracket is doing
something, the gap between these curves is where it is.
""")

code(r"""
alts = {
    RULE.name: engine,
    "no levels, time stop only": MX.run_bracket_fast(
        book, X.ExitRule(name="time only", time_stop_min=RULE.time_stop_min, mode="close"),
        cost_bp=COST_BP),
    "target only, no stop": MX.run_bracket_fast(
        book, X.ExitRule(name="tp only", tp_frac=BRACKET["tp_frac"],
                         time_stop_min=RULE.time_stop_min, mode="close"), cost_bp=COST_BP),
}
print(pd.DataFrame([stats_of(v, k) for k, v in alts.items() if v is not None and not v.empty])
      .set_index("label")[["trades", "net_bp", "hit_rate", "payoff", "sr_per_trade",
                           "t_stat", "pct_target", "pct_stop", "pct_time"]].round(4).to_string())

fig = P.compare_curves(alts, title="does the bracket beat simply holding to the clock?")
fig.show()
""")

md(r"""
## 6. Sweeping the bracket

Two parameterisations, both swept and both counted. A **fractional** bracket scales with the burst; an
**absolute** one is what a desk with a fixed risk budget would actually run. Neither is obviously
right, so §8 charges the family correction for both.

The heatmap shows net bp per trade. Read the *shape* rather than the maximum — a single bright cell in
an otherwise dark grid is a coincidence, whereas a bright region means the knob is doing something.
""")

code(r"""
FRAC_TP = [0.25, 0.5, 0.75, 1.0, 1.5]
FRAC_SL = [0.5, 1.0, 1.5, 2.0, None]
ABS_TP  = [1.0, 2.0, 3.0, 5.0]
ABS_SL  = [2.0, 4.0, 8.0, None]

def sweep(book, shapes, cost_bp=COST_BP, time_stop=None, trail=None):
    rows, series = [], {}
    ts = RULE.time_stop_min if time_stop is None else time_stop
    for kw, nm in shapes:
        r = X.ExitRule(name=nm, trail_bp=trail, time_stop_min=ts,
                       min_hold_min=RULE.min_hold_min, stop_slip_ticks=RULE.stop_slip_ticks,
                       mode="close", **kw)
        df = MX.run_bracket_fast(book, r, cost_bp=cost_bp)
        if df.empty:
            continue
        rows.append(stats_of(df, nm))
        series[nm] = df.set_index("tag")["pnl_bp"]
    # An empty sweep is a real outcome, not an error -- a gated placebo book can
    # legitimately produce no tradeable event at all. Returning a typed empty
    # frame keeps the caller's `.net_bp` working instead of raising on set_index.
    if not rows:
        return pd.DataFrame(columns=["label", "trades", "net_bp", "hit_rate",
                                     "sr_per_trade", "t_stat"]).set_index("label"), series
    return pd.DataFrame(rows).set_index("label"), series

frac_shapes = [(dict(tp_frac=tp, sl_frac=sl),
                f"tp{tp:g}f|sl{'inf' if sl is None else format(sl, 'g')}f")
               for tp, sl in itertools.product(FRAC_TP, FRAC_SL)]
abs_shapes  = [(dict(tp_bp=tp, sl_bp=sl),
                f"tp{tp:g}b|sl{'inf' if sl is None else format(sl, 'g')}b")
               for tp, sl in itertools.product(ABS_TP, ABS_SL)]

t0 = time.time()
sw_frac, ser_frac = sweep(book, frac_shapes)
sw_abs,  ser_abs  = sweep(book, abs_shapes)
print(f"{len(sw_frac) + len(sw_abs)} brackets in {time.time()-t0:.1f}s")
print("\nbest 10 by net bp/trade")
print(pd.concat([sw_frac, sw_abs]).sort_values("net_bp", ascending=False).head(10)[
    ["trades", "net_bp", "hit_rate", "payoff", "sr_per_trade", "t_stat",
     "pct_target", "pct_stop", "pct_time"]].round(4).to_string())
""")

code(r"""
fig, axes = plt.subplots(1, 2, figsize=(12, 4.4))

for ax, (sw, tps, sls, tag) in zip(axes, [
        (sw_frac, FRAC_TP, FRAC_SL, "fractional (x own burst)"),
        (sw_abs,  ABS_TP,  ABS_SL,  "absolute (bp)")]):
    suffix = "f" if tag.startswith("frac") else "b"
    M = np.full((len(sls), len(tps)), np.nan)
    for i, sl in enumerate(sls):
        for j, tp in enumerate(tps):
            nm = f"tp{tp:g}{suffix}|sl{'inf' if sl is None else format(sl, 'g')}{suffix}"
            if nm in sw.index:
                M[i, j] = sw.loc[nm, "net_bp"]
    v = np.nanmax(np.abs(M)) or 1.0
    im = ax.imshow(M, cmap="RdYlGn", vmin=-v, vmax=v, aspect="auto")
    ax.set_xticks(range(len(tps))); ax.set_xticklabels([f"{t:g}" for t in tps])
    ax.set_yticks(range(len(sls))); ax.set_yticklabels(["none" if s is None else f"{s:g}" for s in sls])
    ax.set_xlabel("take profit"); ax.set_ylabel("stop")
    ax.set_title(f"net bp/trade -- {tag}"); ax.grid(False)
    for i in range(len(sls)):
        for j in range(len(tps)):
            if np.isfinite(M[i, j]):
                ax.text(j, i, f"{M[i, j]:+.2f}", ha="center", va="center", fontsize=7)
    plt.colorbar(im, ax=ax, fraction=0.046)
plt.show()
""")

md(r"""
### 6.1 The other three knobs

The burst threshold, the trailing stop and the time stop, each swept with everything else held at the
headline. A knob whose marginal is flat is a knob that is not doing anything, and saying so is more
useful than reporting its best cell.
""")

code(r"""
THRESHOLDS = [0.0, 0.5, 1.0, 2.0, 3.0, 5.0]
rows = []
for thr in THRESHOLDS:
    cfg = C.spec(f"{NAME}|mv{thr:g}", instrument=INSTRUMENT, events=EVENTS, timing=TIMING,
                 signal={**SIGNAL, "min_move_bp": thr})
    bk = X.build_base_book(cfg, raw)
    if bk.events.empty:
        continue
    df = MX.run_bracket_fast(bk, RULE, cost_bp=COST_BP)
    if df.empty:
        continue
    rows.append({**stats_of(df, f"min_move >= {thr:g}bp"), "threshold": thr})
thr_tbl = pd.DataFrame(rows).set_index("label")
print("-- burst threshold --")
print(thr_tbl[["trades", "net_bp", "hit_rate", "sr_per_trade", "t_stat"]].round(4).to_string())

rows = []
for ts in [30, 58, 118, 238]:
    for tr in [None, 2.0, 4.0]:
        r = X.ExitRule(name=f"t{ts}|tr{'-' if tr is None else format(tr, 'g')}",
                       tp_frac=BRACKET["tp_frac"], sl_frac=BRACKET["sl_frac"],
                       trail_bp=tr, time_stop_min=ts, mode="close")
        # the HEADLINE book, not the threshold loop's leftover `bk`
        df = MX.run_bracket_fast(book, r, cost_bp=COST_BP)
        if not df.empty:
            rows.append({**stats_of(df, r.name), "time_stop": ts,
                         "trail": np.nan if tr is None else tr})
tt = pd.DataFrame(rows).set_index("label")
print("\n-- time stop x trailing stop --")
print(tt[["trades", "net_bp", "hit_rate", "sr_per_trade", "pct_stop", "pct_time"]].round(4).to_string())
""")

code(r"""
fig, ax = plt.subplots(1, 2, figsize=(11.5, 3.8))
ax[0].bar(range(len(thr_tbl)), thr_tbl["net_bp"], color="#4c72b0")
ax[0].set_xticks(range(len(thr_tbl)))
ax[0].set_xticklabels([f"{t:g}" for t in thr_tbl["threshold"]], rotation=0)
ax[0].axhline(0, color="k", lw=0.8); ax[0].set_xlabel("min |burst| bp")
ax[0].set_title("net bp/trade by burst threshold")
for i, (v, n) in enumerate(zip(thr_tbl["net_bp"], thr_tbl["trades"])):
    ax[0].text(i, v, f"n={n}", ha="center", va="bottom" if v >= 0 else "top", fontsize=7)

piv = tt.pivot_table(index="trail", columns="time_stop", values="net_bp", dropna=False)
v = np.nanmax(np.abs(piv.to_numpy())) or 1.0
im = ax[1].imshow(piv.to_numpy(), cmap="RdYlGn", vmin=-v, vmax=v, aspect="auto")
ax[1].set_xticks(range(piv.shape[1])); ax[1].set_xticklabels(piv.columns)
ax[1].set_yticks(range(piv.shape[0])); ax[1].set_yticklabels(["none" if np.isnan(i) else f"{i:g}" for i in piv.index])
ax[1].set_xlabel("time stop (min)"); ax[1].set_ylabel("trail bp"); ax[1].grid(False)
ax[1].set_title("net bp/trade")
for i in range(piv.shape[0]):
    for j in range(piv.shape[1]):
        if np.isfinite(piv.to_numpy()[i, j]):
            ax[1].text(j, i, f"{piv.to_numpy()[i, j]:+.2f}", ha="center", va="center", fontsize=7)
plt.colorbar(im, ax=ax[1], fraction=0.046)
plt.show()
""")

md(r"""
## 7. The yardstick — the same sweep on days with no CPI

A grid returns an order statistic. Run enough brackets on noise and the best one looks excellent, so
"is the best cell good?" is answered against **the same sweep on the wrong day**, not against zero.

The placebo shifts each release by one business day onto a minute where nothing printed — business
days because CPI is never on a weekend, and shifted in New York time so the time of day survives DST.
""")

code(r"""
real_sw = pd.concat([sw_frac, sw_abs])

placebo_raw = C.placebo_shift(raw, days=1, business_days=True, avoid_real=True)
pb_book = X.build_base_book(C.spec(f"{NAME}|placebo", instrument=INSTRUMENT, events=EVENTS,
                                   timing=TIMING, signal=SIGNAL), placebo_raw)
print(f"placebo book, SAME gate (min_move >= {SIGNAL['min_move_bp']:g}bp): "
      f"{len(pb_book.events):,} events   vs real {len(book.events):,}")
print()
print("That collapse is not a failure of the placebo -- it IS the release effect.")
print("A 3bp burst in a given minute is ordinary after CPI and rare without it, so holding")
print("the burst gate fixed leaves the control with almost nothing to trade.")

# Which also means the gated placebo cannot supply a sweep to compare against, so
# the yardstick is run a SECOND time with the burst gate opened. That is a
# different question -- "is a bracket on a quiet minute worth anything" rather
# than "is a bracket on a quiet 3bp minute worth anything" -- and it is labelled
# as such rather than quietly substituted for the first.
pb_open = X.build_base_book(
    C.spec(f"{NAME}|placebo|open", instrument=INSTRUMENT, events=EVENTS, timing=TIMING,
           signal={**SIGNAL, "min_move_bp": 0.0}), placebo_raw)
print(f"\nplacebo book, gate OPENED to 0bp: {len(pb_open.events):,} events")

sw_frac_p, ser_frac_p = sweep(pb_open, frac_shapes)
sw_abs_p,  ser_abs_p  = sweep(pb_open, abs_shapes)
pb_sw = pd.concat([sw_frac_p, sw_abs_p])
assert len(pb_sw), "the opened placebo produced no cells either -- check the bar cache"

cmp_ = pd.DataFrame([
    {"grid": "REAL CPI", "cells": len(real_sw), "median net_bp": real_sw.net_bp.median(),
     "BEST net_bp": real_sw.net_bp.max(), "BEST sr/trade": real_sw.sr_per_trade.max(),
     "% net positive": float((real_sw.net_bp > 0).mean())},
    {"grid": "placebo +1bd (0bp gate)", "cells": len(pb_sw), "median net_bp": pb_sw.net_bp.median(),
     "BEST net_bp": pb_sw.net_bp.max(), "BEST sr/trade": pb_sw.sr_per_trade.max(),
     "% net positive": float((pb_sw.net_bp > 0).mean())},
]).set_index("grid")
print()
print(cmp_.round(4).to_string())
print()
if real_sw.net_bp.max() <= pb_sw.net_bp.max():
    print("The best REAL bracket does not beat the best PLACEBO bracket.")
    print("The sweep found the shape of a sweep, not an edge.")
else:
    print(f"Best real exceeds best placebo by {real_sw.net_bp.max() - pb_sw.net_bp.max():+.4f} bp/trade")
    print("-- which is one draw against one draw. Section 8 prices how much that is worth.")
""")

code(r"""
fig, ax = plt.subplots(figsize=(7.5, 4))
ax.hist(real_sw.net_bp, bins=22, alpha=0.75, label=f"real ({len(real_sw)})", color="#4c72b0")
ax.hist(pb_sw.net_bp, bins=22, alpha=0.6, label=f"placebo ({len(pb_sw)})", color="#c44e52")
ax.axvline(0, color="k", lw=0.9)
ax.axvline(real_sw.net_bp.max(), color="#4c72b0", ls="--", lw=1.2)
ax.axvline(pb_sw.net_bp.max(), color="#c44e52", ls="--", lw=1.2)
ax.set_xlabel("net bp per trade"); ax.set_ylabel("brackets")
ax.set_title("every bracket, real vs wrong-day (dashed = each grid's best)")
ax.legend()
plt.show()
""")

md(r"""
## 8. What the search cost

Every cell above is a try, and trying is not free. Three corrections, all from
`RVUtils.StatisticalFinance`:

- **Selection-bias p** — how often a null family of this size and correlation produces a maximum this
  good. This is the number that prices the search.
- **Romano–Wolf** — a stepdown that controls the familywise error rate across all cells at once.
- **Rademacher Anti-Serum** — a high-probability lower bound on true performance after the search.

The null is a **shared** sign flip across cells, which preserves the correlation between brackets. An
independent flip per cell would pretend they were separate experiments and produce a p-value that is
far too kind.
""")

code(r"""
ser_all = {**ser_frac, **ser_abs}
Xm = pd.DataFrame(ser_all).sort_index()
obs = np.array([Xm[c].dropna().mean() / Xm[c].dropna().std(ddof=1)
                if Xm[c].notna().sum() > 1 else 0.0 for c in Xm.columns])

null = shared_sign_flip_null(Xm, draws=2000, rng=np.random.default_rng(20260811))
p_best = selection_bias_pvalue(obs, null)
rw = romano_wolf(obs, null, alpha=0.05, names=list(Xm.columns))
ras = ras_bound(Xm.fillna(0.0), delta=0.05, draws=2000,
                rng=np.random.default_rng(7), names=list(Xm.columns))

print(f"family matrix: {Xm.shape[1]:,} brackets x {Xm.shape[0]:,} CPI prints")
print(f"selection-bias adjusted p for the BEST cell : {p_best:.4f}")
print(f"Romano-Wolf rejects at 5% FWER              : {rw.n_rejected:,} of {rw.n_strategies:,}")
print(f"Rademacher positive                         : {int((ras.bound > 0).sum()):,} of {ras.N:,}")
print()
print(ras.terms().round(5).to_string())
""")

code(r"""
best_nm = real_sw.sr_per_trade.idxmax()
s = Xm[best_nm].dropna().to_numpy(float)
tp = timer_pvalue(s, np.sign(s + 1e-12), draws=4999, rng=np.random.default_rng(3))
print(f"best cell by Sharpe/trade: {best_nm}")
print(real_sw.loc[[best_nm]][["trades", "net_bp", "hit_rate", "payoff", "sr_per_trade",
                              "t_stat", "pct_target", "pct_stop", "pct_time"]].round(4).to_string())
print(f"\ntimer p-value (is the TIMING of this rule better than a random reshuffle?): "
      f"{tp.p_value:.4f}   [observed {tp.observed:+.4f} vs null mean {tp.null_mean:+.4f}, "
      f"{tp.n_draws:,} draws]")
rw_row = rw.table[rw.table.strategy == best_nm]
if len(rw_row):
    print(f"Romano-Wolf adjusted p for this cell: {float(rw_row.iloc[0]['p_adjusted']):.4f}")
""")

md(r"""
## 9. Where this sits in the full committed search

The sweep above is a slice — one threshold, one direction, one time stop family. `cpi_ty_exit_search.py`
ran the whole product (4,920 eligible cells) and its results are committed, so the headline can be
placed against every bracket that was actually tried rather than against the handful re-run here.
""")

code(r"""
p = G.CACHE / "cpi_ty_exit_search_real.csv"
if p.exists():
    full = pd.read_csv(p)
    full = full[full.trades >= 30]
    print(f"committed search: {len(full):,} eligible cells")
    print("\ntop 10 by net bp/trade")
    print(full.sort_values("net_bp", ascending=False).head(10)[
        ["config", "trades", "net_bp", "hit_rate", "sr_per_trade", "t_stat"]].round(4).to_string(index=False))
    print("\nmarginals -- median net bp by knob")
    for col in ("direction", "threshold", "trail", "time_stop"):
        if col in full.columns:
            g = full.groupby(col, dropna=False).agg(
                cells=("net_bp", "size"), median_net=("net_bp", "median"),
                best_net=("net_bp", "max")).round(4)
            print(f"\n-- {col} --"); print(g.to_string())
else:
    print(f"{p.name} not present -- run cpi_ty_exit_search.py to regenerate")
""")

md(r"""
## 10. Verdict

Read this notebook in the order the numbers were produced, not in the order they flatter:

1. The **tie-out** in §4 is what makes anything after it admissible. It passed here; it did not the
   first time it ran.
2. The **placebo** in §7 is the only comparison that can say the sweep found something. The best real
   bracket has to beat the best wrong-day bracket, and one draw against one draw is weak evidence
   either way.
3. The **selection-bias p** in §8 is what the search cost. A grid this size produces a good-looking
   maximum on noise, and that p-value is how often.

The exit rule is a genuine improvement in *shape* — a level exit ends most trades at a target rather
than at a bell, and the hold time collapses. Whether that shape is worth a round trip is what §7 and
§8 answer, and neither of them is impressed by a heatmap.
""")

nb = {"cells": cells,
      "metadata": {"kernelspec": {"display_name": "stir", "language": "python", "name": "python3"},
                   "language_info": {"name": "python", "version": "3.13"}},
      "nbformat": 4, "nbformat_minor": 5}
OUT.write_text(json.dumps(nb, indent=1), encoding="utf-8")
print(f"wrote {OUT}  ({len(cells)} cells)")
