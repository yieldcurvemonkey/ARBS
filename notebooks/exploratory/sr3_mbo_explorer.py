# %% [markdown]
# # SR3 market-by-order — 2026-07-15
#
# `glbx-mdp3-20260715.mbo.dbn.zst` is the full CME order book for the SR3
# complex on one day: 72.9 million messages, 1,188 listed instruments, every
# add, cancel, modify and trade with the order id attached.
#
# Every SR3 relative-value study in this repo so far has priced structures off
# **settles** and charged a **2.0 bp round-trip cost** taken on faith — four
# contracts at half a basis point each, which is the cost of *legging* a
# butterfly. Under that charge nothing survives: 0/47 in the RV lab, 0/42 in
# kink-fade v2, 0/360 in outcome-map.
#
# This file contains something those studies never had: the **book of the
# exchange-listed butterflies**, where a fly is one instrument with one bid and
# one ask. 89 of them are quoted and 3,871 trades printed in them on this day.
# So the cost assumption stops being an assumption.
#
# **What it comes to.** The listed butterfly is quoted **one tick wide — 0.506 bp
# round trip, $12.65 a lot** — for 99.8% of the session on the active names. The
# 2.0 bp figure is not wrong; it is the cost of the *outright* route, and this
# file measures that route at 2.000 bp, confirming it. But it is four times the
# cost of trading the instrument the exchange actually lists. Section 4 checks
# the obvious objection — that this is CME implied liquidity wearing a
# butterfly's name — and it is not: the listed book is tighter at 100% of 32,399
# one-second observations and eight times deeper at the touch.
#
# Section 6 verifies the machinery against a source that shares no code with it:
# 48 of 48 four-hour bars reproduce the Barchart closes exactly, at 0.0 bp.
#
# **Sections**
#
# 1. **The map** — what is on the file and when it was busy
# 2. **Book explorer** — replay any instrument: top of book, depth, tape
# 3. **Cost truth** — quoted, effective and realised spread against the 2.0 bp charge
# 4. **Listed vs implied** — the fly's own book against one built from its legs
# 5. **RV panel** — a clean intraday bid/ask/mid/depth panel for `RVUtils`
# 6. **Verification** — tie-out against Barchart, and replay invariants
#
# The engine is `RVUtils/MBO`; design notes in
# `docs/superpowers/specs/2026-08-07-sr3-mbo-explorer-design.md`.

# %%
from __future__ import annotations

import gc
import sys
import time
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

REPO = Path.cwd()
while not (REPO / "RVUtils").exists() and REPO != REPO.parent:
    REPO = REPO.parent
sys.path.insert(0, str(REPO))

from RVUtils.MBO import MboSource, build_price_grid, compare_listed_vs_implied, replay_book
from RVUtils.MBO.metrics import (
    USD_PER_BP_PER_LOT,
    cost_summary,
    effective_spread,
    intraday_profile,
    order_flow_imbalance,
    quoted_spread_summary,
    resample_tob,
    trade_ohlcv,
)
from RVUtils.MBO.symbols import bp_per_price_unit
from RVUtils.MBO import plots

plots.theme()
pd.set_option("display.width", 190)
pd.set_option("display.max_columns", 60)

DBN_PATH = r"C:\Users\chris\Downloads\glbx-mdp3-20260715.mbo.dbn.zst"

# The cache sits OUTSIDE the repo and outside any worktree: it holds a few
# hundred MB of extracts and `git worktree remove` must not be able to eat it.
CACHE_DIR = r"C:\Users\chris\clee\mbo_cache"

# CME trades 17:00-16:00 Chicago; in July that is UTC-5, so the daily settlement
# break falls at 21:00-22:00 UTC.  The file's own message histogram confirms it:
# 13,000 messages in the 21:00 UTC hour against 18.4 million in the 12:00 hour.
RTH = ("2026-07-15 12:00:00+00:00", "2026-07-15 21:00:00+00:00")

src = MboSource(DBN_PATH, CACHE_DIR)
print(f"{src.dataset}  schema={src.schema}")
print(f"session  {src.session_start}  ->  {src.session_end}")
print(f"symbols mapped: {len(src.id_to_symbol):,}")

# %% [markdown]
# ## 1. The map
#
# One vectorised pass over the file gives per-instrument counts, an action
# breakdown and a minute-of-day activity grid. It takes about twenty seconds and
# is cached, so re-running this notebook is free.
#
# Snapshot records are excluded from every timestamp statistic. The file opens
# with 51,658 of them — the resting book carried in from the previous session —
# all stamped at exactly 00:00:00 for every instrument at once. Counting them
# would put a fake spike in the first minute and make all 393 instruments look
# like they started trading at midnight.

# %%
t0 = time.perf_counter()
cat = src.catalogue()
scan = src.scan()
print(f"catalogue: {len(cat):,} active instruments from {scan.total_records:,} records "
      f"in {time.perf_counter() - t0:.0f}s")

by_kind = (
    cat.groupby("kind")
    .agg(instruments=("symbol", "size"), messages=("n_msgs", "sum"),
         trades=("n_trades", "sum"), lots=("trade_volume", "sum"))
    .sort_values("messages", ascending=False)
)
by_kind["msgs_per_trade"] = (by_kind["messages"] / by_kind["trades"]).round(0)
by_kind

# %% [markdown]
# The listed spread complex is not a rounding error. Butterflies alone carry 89
# quoted instruments; `msgs_per_trade` says how hard the market makers work to
# keep each book current relative to how often anyone takes it.

# %%
plots.plot_activity_by_kind(cat, metric="n_msgs")
plt.show()
plots.plot_activity_by_kind(cat, metric="trade_volume")
plt.show()

# %%
cols = ["symbol", "kind", "label", "n_msgs", "n_trades", "trade_volume",
        "avg_trade_size", "msgs_per_trade", "n_contracts", "px_min", "px_max"]
print("=== busiest outrights ===")
display(cat[cat["kind"] == "OUTRIGHT"].nlargest(12, "n_msgs")[cols])

print("=== busiest listed butterflies ===")
display(cat[cat["kind"] == "BUTTERFLY"].nlargest(12, "trade_volume")[cols])

print("=== busiest calendars ===")
display(cat[cat["kind"] == "CALENDAR"].nlargest(8, "trade_volume")[cols])

# %% [markdown]
# ### The unit trap, up front
#
# Look at `px_min`/`px_max` in the two tables above. Outrights sit near 96;
# butterflies sit near zero and go negative. That is not a small price — it is a
# **different unit**. CME quotes outrights and bundles in index points
# (96.040, tick 0.005) and every differential instrument **directly in basis
# points** (6.500, tick 0.5).
#
# Check it against the file's own numbers: SR3Z6 96.040, SR3H7 95.970,
# SR3M7 95.960 give a fly of `96.040 − 2(95.970) + 95.960 = 0.060` index points
# `= 6.0 bp`, and the listed `SR3:BF Z6-H7-M7` closed at **6.500**.
#
# Treating a butterfly price as index points inflates every spread by 100×: a
# one-tick market reads as 50 bp wide. `RVUtils/MBO` derives the scale from the
# parsed symbol *and* from the tick the instrument actually printed, and raises
# if the two disagree rather than guessing.

# %%
unit_check = cat[cat["n_trades"] > 100].copy()
unit_check["bp_per_price_unit"] = unit_check["kind"].map(
    lambda k: bp_per_price_unit(k)
)
unit_check.groupby(["kind", "bp_per_price_unit"]).agg(
    instruments=("symbol", "size"),
    px_lo=("px_min", "min"), px_hi=("px_max", "max"),
)

# %% [markdown]
# ### When the book was busy
#
# The vertical rules mark 12:30 UTC — a scheduled release slot; the file says
# only that the complex went from a few thousand messages a minute to a
# multiple of that — and 21:00 UTC, the settlement break.

# %%
mf = scan.minute_frame("msgs")
watch = ["SR3Z6", "SR3H7", "SR3M7", "SR3Z7", "SR3:BF Z6-H7-M7", "SR3:AB 01Y U6"]
plots.plot_intraday_message_rate(
    mf, [src.symbol_to_id[s] for s in watch],
    labels={src.symbol_to_id[s]: s for s in watch},
    annotate_minutes={12 * 60 + 30: "12:30 UTC release", 21 * 60: "settlement break"},
)
plt.show()

# %% [markdown]
# ## 2. Book explorer
#
# `replay_book` turns one instrument's messages into a top-of-book event stream
# and, optionally, an N-deep ladder on a time grid. The rules that make it
# correct are documented in `RVUtils/MBO/book.py`; the two that matter most:
#
# * **`T` and `F` never touch the book.** A match prints as `T`, then `F` on the
#   resting order, then an explicit `C` — applying the `F` as well would
#   decrement the level twice.
# * **Top of book is only read at `F_LAST` packet boundaries.** Inside a packet
#   the book is momentarily inconsistent, and a mid taken from one of those
#   states poisons every effective-spread number computed off it.
#
# Extraction is batched: pulling one instrument costs a full pass over the file,
# so pulling forty costs one pass too.

# %%
OUTRIGHTS = ["SR3M6", "SR3U6", "SR3Z6", "SR3H7", "SR3M7", "SR3U7", "SR3Z7",
             "SR3H8", "SR3M8", "SR3U8", "SR3Z8", "SR3M9"]
FLIES = ["SR3:BF Z6-H7-M7", "SR3:BF U6-Z6-H7", "SR3:BF H7-M7-U7", "SR3:BF M7-U7-Z7",
         "SR3:BF U7-Z7-H8", "SR3:BF Z7-H8-M8", "SR3:BF M7-M8-M9", "SR3:BF Z6-M7-Z7",
         "SR3:BF U6-H7-U7", "SR3:BF M7-Z7-M8"]
CALENDARS = ["SR3H7-SR3M7", "SR3M7-SR3U7", "SR3Z6-SR3Z7", "SR3U6-SR3Z6", "SR3Z6-SR3H7"]
PACKS = ["SR3:AB 01Y U6", "SR3:AB 02Y U6"]

UNIVERSE = [s for s in OUTRIGHTS + FLIES + CALENDARS + PACKS if s in src.symbol_to_id]
t0 = time.perf_counter()
written = src.extract([src.symbol_to_id[s] for s in UNIVERSE])
print(f"{len(UNIVERSE)} instruments in the working set; {len(written)} newly extracted "
      f"in {time.perf_counter() - t0:.0f}s")


def replay(symbol: str, grid_freq: str | None = None, n_levels: int = 10):
    """Replay one instrument, with the price scale checked two ways.

    Deliberately *not* cached. The busiest outright changes its touch fifteen
    million times in a day; holding all twelve at full resolution is several
    gigabytes. Everything below either keeps one book at a time or immediately
    reduces to a one-second panel.
    """
    rec = src.records(symbol)
    grid = None
    if grid_freq:
        g = pd.date_range(src.session_start, src.session_end, freq=grid_freq,
                          inclusive="left")
        grid = g.to_numpy(dtype="datetime64[ns]").astype("int64")
    pg = build_price_grid(rec["price"].astype("int64"))
    scale = bp_per_price_unit(src.parsed[symbol].kind, pg.tick_float)
    return replay_book(rec, grid_ts=grid, n_levels=n_levels, grid=pg, bp_per_unit=scale)


# %%
t0 = time.perf_counter()
front = replay("SR3Z6", grid_freq="1s", n_levels=10)
print(f"SR3Z6: {front.n_records:,} records replayed in {time.perf_counter() - t0:.1f}s")
print(f"  snapshot rows      {front.n_snapshot:,}")
print(f"  top-of-book events {len(front.tob):,}")
print(f"  trades             {len(front.trades):,}  ({front.trades['size'].sum():,} lots)")
print(f"  price ladder       tick {front.grid.tick_float:g} "
      f"({front.grid.tick_float * front.bp_per_unit:g} bp), {front.grid.n_slots} slots")
print(f"  price scale        {front.bp_per_unit:g} bp per price unit")
print(f"  crossed at a packet boundary: {front.crossed_events:,}")
front.tob.head()

# %%
WINDOW = ("2026-07-15 12:25:00+00:00", "2026-07-15 12:40:00+00:00")
plots.plot_top_of_book(front.tob, front.trades, session=WINDOW,
                       title="SR3Z6 top of book through the 12:30 UTC release")
plt.show()

# %% [markdown]
# The depth ladder shows what the touch chart cannot: how much size rests behind
# the best price, and whether it leaves before or after the print.

# %%
gts = pd.to_datetime(front.depth["ts"], utc=True)
sel = (gts >= pd.Timestamp(WINDOW[0])) & (gts < pd.Timestamp(WINDOW[1]))
plots.plot_depth_heatmap({k: v[sel] for k, v in front.depth.items()}, front.trades,
                         title="SR3Z6 resting size by price, 12:25-12:40 UTC")
plt.show()

# %%
# %% [markdown]
# ### Does the flow move the price?
#
# Two measures of pressure against the move that came with it. **Signed trade
# flow** is aggressor buys minus aggressor sells; **order-flow imbalance** is
# the Cont-Kukanov-Stoikov measure built from top-of-book transitions, which
# counts resting size that never traded.
#
# Signed trade flow works at any horizon. OFI does not work at one minute in
# this book and does at five — which is a property of the instrument, not a
# defect: the touch holds thousands of lots and the mid only moves when a whole
# level clears, so a single minute of queue churn is mostly noise around an
# unmoved price. That the *trade* relation is positive is also the check that
# the aggressor convention and the mid are consistent.

# %%
def flow_panel(res, freq):
    ofi = order_flow_imbalance(res.tob, freq=freq, bp_per_unit=res.bp_per_unit)
    t = res.trades.copy()
    t["signed"] = np.where(t["aggressor"] == "B", 1, -1) * t["size"]
    sv = t.set_index("ts_recv")["signed"].resample(freq).sum()
    d = ofi.join(sv.rename("signed_vol")).dropna()
    return d[(d.index >= pd.Timestamp(RTH[0])) & (d.index < pd.Timestamp(RTH[1]))]


rows_flow = []
for freq in ("1min", "5min", "15min"):
    d = flow_panel(front, freq)
    rows_flow.append({
        "freq": freq, "bars": len(d),
        "r_signed_trade": d["signed_vol"].corr(d["mid_change_bp"]),
        "r_ofi": d["ofi"].corr(d["mid_change_bp"]),
        "bp_per_1000_lots_trade": np.polyfit(d["signed_vol"], d["mid_change_bp"], 1)[0] * 1000,
        "bp_per_1000_lots_ofi": np.polyfit(d["ofi"], d["mid_change_bp"], 1)[0] * 1000,
    })
display(pd.DataFrame(rows_flow).set_index("freq").round(4))

d5 = flow_panel(front, "5min")
fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
for ax, col, name, i in ((axes[0], "signed_vol", "signed trade flow", 0),
                         (axes[1], "ofi", "order-flow imbalance", 2)):
    ax.scatter(d5[col], d5["mid_change_bp"], s=20, color=plots.series_color(i),
               alpha=0.6, edgecolor="none", label="5-minute bar")
    slope, intercept = np.polyfit(d5[col], d5["mid_change_bp"], 1)
    xs = np.linspace(d5[col].min(), d5[col].max(), 50)
    ax.plot(xs, intercept + slope * xs, color=plots.SERIES[1], lw=2.0,
            label=f"{slope * 1000:+.3f} bp / 1,000 lots  "
                  f"(r = {d5[col].corr(d5['mid_change_bp']):+.2f})")
    ax.axhline(0, color=plots.BASELINE, lw=1.0)
    ax.axvline(0, color=plots.BASELINE, lw=1.0)
    ax.set_xlabel(f"{name} (lots)")
    ax.legend(loc="upper left")
axes[0].set_ylabel("mid change over the bar (bp)")
fig.suptitle("SR3Z6 — pressure against the move it came with", x=0.09, y=1.0,
             ha="left", fontsize=12, fontweight="600", color=plots.INK)
plt.show()

# %% [markdown]
# ### The same machinery on a listed butterfly
#
# This is the object the repo has never been able to look at: a fly with its own
# book, its own tick, and its own resting size.

# %%
del front
gc.collect()

FLY = "SR3:BF Z6-H7-M7"
fly = replay(FLY, grid_freq="5s", n_levels=6)   # 5s over nine hours stays legible
print(f"{FLY}: {fly.n_records:,} records, {len(fly.tob):,} top-of-book events, "
      f"{len(fly.trades):,} trades ({fly.trades['size'].sum():,} lots)")
print(f"  tick {fly.grid.tick_float:g} price units = "
      f"{fly.grid.tick_float * fly.bp_per_unit:g} bp")
plots.plot_top_of_book(fly.tob, fly.trades, session=RTH,
                       title=f"{FLY} top of book, RTH", price_label="fly price (bp)")
plt.show()

# %%
gts = pd.to_datetime(fly.depth["ts"], utc=True)
sel = (gts >= pd.Timestamp(RTH[0])) & (gts < pd.Timestamp(RTH[1]))
plots.plot_depth_heatmap({k: v[sel] for k, v in fly.depth.items()}, fly.trades,
                         title=f"{FLY} resting size by price, RTH",
                         price_label="fly price (bp)")
plt.show()

# %%
prof = intraday_profile(fly.tob, fly.trades, freq="15min", bp_per_unit=fly.bp_per_unit)
plots.plot_intraday_profile(prof, title=f"{FLY} through the day")
plt.show()

# %% [markdown]
# ## 3. Cost truth
#
# Three numbers, all in **bp of the structure** ($25 per bp per lot):
#
# * **quoted spread** — time-weighted, so a wide state that stood for ten
#   minutes counts for ten minutes and not for one event
# * **effective spread** — `2 × direction × (price − prevailing mid)`: what the
#   trades that actually happened paid
# * **realised spread** at 60 s, and the difference, which is impact
#
# `two_sided_frac` is the guard: a tight spread that exists only 4% of the day
# is not a spread you can trade, and an average would hide that.
#
# Each instrument is replayed, summarised and discarded, plus its one-second
# panel kept for the leg-implied comparison in section 4.

# %%
rows, leg_panels, invariants, all_trades = [], {}, [], {}

for sym in UNIVERSE:
    r = replay(sym)
    p = src.parsed[sym]

    q = quoted_spread_summary(r.tob, n_contracts=p.n_contracts, session=RTH,
                              tick=r.grid.tick_float, bp_per_unit=r.bp_per_unit)
    eff = effective_spread(r.tob, r.trades, horizons_s=(1.0, 60.0), session=RTH,
                           bp_per_unit=r.bp_per_unit)
    rows.append(dict(
        symbol=sym, kind=p.kind, label=p.label, n_contracts=p.n_contracts,
        usd_per_bp=p.usd_per_bp_per_lot,
        tick_bp=r.grid.tick_float * r.bp_per_unit,
        n_trades=int(len(eff)), lots=int(eff["size"].sum()) if len(eff) else 0,
        **{k: q.get(k) for k in ("spread_bp", "spread_bp_median", "two_sided_frac",
                                 "bid_sz_at_touch", "ask_sz_at_touch",
                                 "orders_at_touch", "frac_time_one_tick")},
        eff_bp=float(eff["eff_bp"].median()) if len(eff) else np.nan,
        realised_bp_60s=float(eff["realised_bp_60s"].median()) if len(eff) else np.nan,
        impact_bp_60s=float(eff["impact_bp_60s"].median()) if len(eff) else np.nan,
    ))

    full = effective_spread(r.tob, r.trades, horizons_s=(),
                            bp_per_unit=r.bp_per_unit).dropna(subset=["bid_px", "ask_px"])
    outside = (full["price"] > full["ask_px"] + 1e-12) | (full["price"] < full["bid_px"] - 1e-12)
    invariants.append(dict(
        symbol=sym, kind=p.kind, records=r.n_records, snapshot=r.n_snapshot,
        tob_events=len(r.tob), crossed_at_boundary=r.crossed_events,
        trades_checked=int(len(full)), trades_outside_book=int(outside.sum()),
        frac_outside=float(outside.mean()) if len(full) else np.nan,
    ))

    panel = resample_tob(r.tob, freq="1s", session=RTH, bp_per_unit=r.bp_per_unit)
    if not panel.empty:
        leg_panels[sym] = panel.reset_index()
    all_trades[sym] = r.trades

    del r, eff, full
    gc.collect()

cost = cost_summary(rows, legged_bp_per_contract=0.5)
show = ["symbol", "kind", "n_contracts", "usd_per_bp", "tick_bp", "spread_bp",
        "spread_bp_median", "eff_bp", "impact_bp_60s", "two_sided_frac",
        "frac_time_one_tick", "bid_sz_at_touch", "ask_sz_at_touch",
        "orders_at_touch", "n_trades", "lots",
        "legged_roundtrip_bp", "listed_roundtrip_bp", "cost_ratio",
        "listed_roundtrip_usd", "legged_roundtrip_usd"]
cost.sort_values(["kind", "cost_ratio"])[show]

# %% [markdown]
# `legged_roundtrip_bp` is the repo's standing assumption applied to the
# structure: `n_contracts × 0.5 bp`, which is **2.0 bp for a butterfly**.
# `listed_roundtrip_bp` is what crossing the instrument's own book costs.
# `cost_ratio` below 1 means the listed book is cheaper than what every backtest
# in this repo has been charging.

# %%
structures = cost[cost["kind"].isin(["BUTTERFLY", "CALENDAR", "BUNDLE"])]
plots.plot_cost_comparison(structures, top=len(structures))
plt.show()

headline = cost[cost["kind"] == "BUTTERFLY"]
print(f"listed butterflies (n={len(headline)}):")
print(f"  median quoted round trip   {headline['listed_roundtrip_bp'].median():.3f} bp "
      f"(${headline['listed_roundtrip_usd'].median():.2f} per lot)")
print(f"  legged assumption          {headline['legged_roundtrip_bp'].median():.3f} bp "
      f"(${headline['legged_roundtrip_usd'].median():.2f} per lot)")
print(f"  ratio                      {headline['cost_ratio'].median():.2f}x")
print(f"  median effective spread    {headline['eff_bp'].median():.3f} bp")
print(f"  two-sided share of RTH     {headline['two_sided_frac'].min():.1%} "
      f"- {headline['two_sided_frac'].max():.1%}")

# %% [markdown]
# Read that against the cost line every SR3 study in this repo carries. The
# listed butterfly is quoted **one tick wide** — the same one tick as an
# outright — so a round trip costs the tick, not four times it. Section 4
# checks the obvious objection: that this is CME's implied liquidity in
# disguise, and the fly is really only as good as its legs.

# %%
def width_share(symbols):
    """Share of RTH seconds at 1 / 2 / 3+ ticks, per instrument."""
    out = {}
    for sym in symbols:
        p = leg_panels.get(sym)
        if p is None:
            continue
        tick = cost.loc[cost["symbol"] == sym, "tick_bp"].iloc[0]
        n = (p["spread_bp"] / tick).round().dropna()
        out[sym] = pd.Series({
            "1 tick": float((n <= 1).mean()),
            "2 ticks": float((n == 2).mean()),
            "3+ ticks": float((n >= 3).mean()),
        })
    return pd.DataFrame(out).T


shares = width_share(FLIES + CALENDARS + ["SR3Z6", "SR3Z7", "SR3:AB 01Y U6"])
plots.plot_spread_time_share(shares.sort_values("1 tick"))
plt.show()

# %% [markdown]
# ## 4. Listed against implied
#
# A butterfly can be bought two ways: cross its own book, or cross the three
# outright books. To *buy* the structure you lift the ask on positive legs and
# hit the bid on negative ones, so the leg-implied **ask** uses the **bid** of
# the doubled belly. Getting that backwards makes the synthetic look tighter
# than it is, which is the conclusion this comparison exists to test.
#
# Both sides are converted to basis points first — the legs quote in index
# points and the listed structure quotes in bp, so a raw comparison would be
# meaningless. The sign convention is not assumed either: the comparison fits
# both orientations against the listed mid and reports which it used.

# %%
cmp_fly = compare_listed_vs_implied(
    fly.tob, leg_panels, src.parsed[FLY].legs, src.parsed[FLY].weights,
    freq="1s", session=RTH, listed_bp_per_unit=fly.bp_per_unit,
)
print(cmp_fly)
pd.Series(cmp_fly.stats)

# %%
plots.plot_listed_vs_implied(cmp_fly.frame.dropna(subset=["listed_mid"]),
                             title=f"{FLY}: its own book against its three legs (bp)")
plt.show()

# %%
imp_rows = []
for sym in FLIES + CALENDARS:
    p = src.parsed[sym]
    if any(l not in leg_panels for l in p.legs):
        continue
    r = replay(sym)
    c = compare_listed_vs_implied(r.tob, leg_panels, p.legs, p.weights, freq="1s",
                                  session=RTH, listed_bp_per_unit=r.bp_per_unit)
    imp_rows.append({"symbol": sym, "kind": p.kind, "label": p.label, **c.stats})
    del r, c
    gc.collect()

implied = pd.DataFrame(imp_rows)
implied.sort_values(["kind", "listed_spread_bp"])

# %% [markdown]
# The column that settles the question is `listed_spread_bp` against
# `implied_spread_bp`. Crossing three outright books to build a fly costs each
# leg's half-spread weighted by its ratio — `0.5 + 2(0.5) + 0.5 = 2.0 bp`, which
# is exactly the legged assumption, now measured rather than assumed.
#
# ### The third route
#
# Outrights are not the only way to leg a fly. `Z6-H7-M7` is also the difference
# of two listed calendars, `(Z6−H7) − (H7−M7)`, and both of those are quoted at
# half a basis point — so the calendar route costs `2 × 0.5 = 1.0 bp`, half the
# outright route. It is the fairest comparison available, and the listed fly
# still wins it.

# %%
CAL_ROUTE = ("SR3Z6-SR3H7", "SR3H7-SR3M7")      # (Z6-H7) - (H7-M7) == Z6 - 2H7 + M7
cmp_cal = compare_listed_vs_implied(
    fly.tob, leg_panels, CAL_ROUTE, (1, -1), freq="1s", session=RTH,
    listed_bp_per_unit=fly.bp_per_unit,
    leg_bp_per_unit=1.0,                        # calendars already quote in bp
)
routes = pd.DataFrame([
    {"route": "listed butterfly", "width_bp": cmp_fly.stats["listed_spread_bp"],
     "size_at_touch": cmp_fly.stats["listed_sz_at_touch"]},
    {"route": "two listed calendars", "width_bp": cmp_cal.stats["implied_spread_bp"],
     "size_at_touch": cmp_cal.stats["implied_sz_at_touch"]},
    {"route": "three outrights", "width_bp": cmp_fly.stats["implied_spread_bp"],
     "size_at_touch": cmp_fly.stats["implied_sz_at_touch"]},
])
routes["usd_per_lot"] = routes["width_bp"] * USD_PER_BP_PER_LOT
routes["vs_listed"] = routes["width_bp"] / routes["width_bp"].iloc[0]
print(f"{FLY} — three ways to trade the same structure, RTH medians")
print(f"calendar route mid agrees with the listed mid to "
      f"{cmp_cal.stats['mid_abs_err_bp']:.2f} bp")
routes

# %%
plots.plot_paired_dots(
    implied.sort_values(["kind", "listed_spread_bp"]),
    "symbol", "listed_spread_bp", "implied_spread_bp",
    "listed book", "built from its legs",
    "Quoted width: the listed instrument against its own legs",
    "median over RTH, one-second grid; both sides in bp of the structure",
    "quoted width (bp)",
)
plt.show()

# %% [markdown]
# ## 5. RV panel
#
# The touch on a regular grid, forward-filled from its own events and already in
# basis points — the shape `RVUtils` wants. Written to the cache so downstream
# work never re-replays.

# %%
panels = []
for sym, p in leg_panels.items():
    panels.append(p.assign(symbol=sym, kind=src.parsed[sym].kind,
                           n_contracts=src.parsed[sym].n_contracts))
panel = pd.concat(panels, ignore_index=True)

out = Path(CACHE_DIR) / "sr3_mbo_panel_1s_20260715.parquet"
panel.to_parquet(out, index=False)
print(f"{len(panel):,} rows x {panel['symbol'].nunique()} instruments -> {out}")
print(f"{out.stat().st_size / 1e6:.1f} MB on disk")
panel.head()

# %% [markdown]
# ## 6. Verification
#
# ### 6a. Tie-out against an independent source
#
# The repo already holds a Barchart four-hour bar panel covering this day
# (`notebooks/data/stir_intraday/contracts.parquet`, built for the intraday-kink
# study). Reconstructing the same bars from the MBO trade prints and comparing
# closes is a known-answer check: the two paths share no code and no vendor.
#
# The bars are stamped in Chicago time, UTC-5 in July. **Both** labelling
# conventions are tested and both results reported, so the alignment is a
# finding rather than something fitted to make the check pass.

# %%
REL = Path("notebooks") / "data" / "stir_intraday" / "contracts.parquet"
candidates = [REPO / REL] + [p / REL for p in sorted(REPO.parent.glob("ARBS*"))]
bc_path = next((p for p in candidates if p.exists()), None)
if bc_path is None:
    raise FileNotFoundError(
        "Barchart tie-out panel not found. Looked in:\n  "
        + "\n  ".join(str(p) for p in candidates)
    )
print(f"tie-out reference: {bc_path}")

bc = pd.read_parquet(bc_path)
bc = bc[bc["as_of"].dt.date == pd.Timestamp("2026-07-15").date()]
print(f"{len(bc)} Barchart bars on 2026-07-15 across {bc['code'].nunique()} contracts")

MONTH_LETTER = {1: "F", 2: "G", 3: "H", 4: "J", 5: "K", 6: "M",
                7: "N", 8: "Q", 9: "U", 10: "V", 11: "X", 12: "Z"}
CT_OFFSET = pd.Timedelta(hours=5)          # July: America/Chicago is UTC-5

tie = []
for convention, shift in (("labelled by start", pd.Timedelta(0)),
                          ("labelled by end", pd.Timedelta(hours=-4))):
    for sym in OUTRIGHTS:
        trades = all_trades.get(sym)
        if trades is None or trades.empty:
            continue
        m = src.parsed[sym].months[0]
        code = f"SR3{MONTH_LETTER[m.month]}{m.year % 100:02d}"
        ref = bc[bc["code"] == code]
        for _, row in ref.iterrows():
            start = pd.Timestamp(row["as_of"], tz="UTC") + CT_OFFSET + shift
            end = start + pd.Timedelta(hours=4)
            if start < src.session_start or end > src.session_end:
                continue                    # bar not fully inside the file's window
            seg = trades[(trades["ts_recv"] >= start) & (trades["ts_recv"] < end)]
            if seg.empty:
                continue
            tie.append(dict(
                convention=convention, symbol=sym, code=code, bar_start_utc=start,
                mbo_close=float(seg["price"].iloc[-1]), bc_close=float(row["settle"]),
                mbo_volume=int(seg["size"].sum()), bc_volume=int(row["volume"]),
            ))

tiedf = pd.DataFrame(tie)
tiedf["close_diff_bp"] = (tiedf["mbo_close"] - tiedf["bc_close"]) * 100.0
tiedf["volume_ratio"] = tiedf["mbo_volume"] / tiedf["bc_volume"]

summary = (
    tiedf.groupby("convention")
    .agg(bars=("close_diff_bp", "size"),
         exact=("close_diff_bp", lambda s: float((s.abs() < 1e-6).mean())),
         within_half_tick=("close_diff_bp", lambda s: float((s.abs() <= 0.25).mean())),
         median_abs_bp=("close_diff_bp", lambda s: float(s.abs().median())),
         volume_ratio_median=("volume_ratio", "median"),
         volume_ratio_max=("volume_ratio", "max"),
         bars_volume_exact=("volume_ratio", lambda s: float((s == 1.0).mean())))
)
summary

# %%
best = summary["median_abs_bp"].idxmin()
print(f"closest convention: {best}\nall bars under it, worst close difference first:")
tiedf[tiedf["convention"] == best].sort_values("close_diff_bp", key=abs,
                                               ascending=False).head(12)

# %% [markdown]
# Where volume does not tie exactly it is the MBO that is *higher*, and only in
# the 13:00 UTC bar. The likely cause is spread-leg executions: a calendar or
# butterfly fill delivers contracts into the outright books and prints there,
# and a vendor daily bar may or may not include them. The direction is
# consistent with that and the closes are unaffected.

# %% [markdown]
# ### 6b. Replay invariants
#
# Three properties a wrong replay breaks and a right one does not:
#
# * **the book is never crossed at a packet boundary** — a filled order left
#   resting shows up here immediately
# * **trades print at or inside the prevailing book** — the residue is implied
#   matching, where a spread leg executes against the outright book at a price
#   the outright's own book never showed
# * **the leg-implied mid tracks the listed mid** — three independently replayed
#   outright books must agree with a fourth instrument on an arithmetic identity
#   none of them knows about

# %%
invdf = pd.DataFrame(invariants)
print(f"crossed-at-boundary events across the working set: "
      f"{invdf['crossed_at_boundary'].sum():,} "
      f"of {invdf['tob_events'].sum():,} top-of-book states")
print(f"trades outside the prevailing book: {invdf['trades_outside_book'].sum():,} "
      f"of {invdf['trades_checked'].sum():,} "
      f"({invdf['trades_outside_book'].sum() / max(1, invdf['trades_checked'].sum()):.3%})")
invdf.sort_values("crossed_at_boundary", ascending=False)

# %% [markdown]
# Both residues are real market behaviour, not replay defects.
#
# **The crossed states are all pre-open.** They belong to one instrument,
# SR3M6, and the timestamps put every one of them between 21:46 and 21:53 UTC —
# after the 21:00 settlement break and inside the pre-open of the *next*
# session, where CME accepts orders but does not match them, so a locked or
# crossed book is the expected state. The raw records show the pattern plainly:
# a mass cancel at 21:00:00.189, forty-five minutes of nothing, then orders
# building up from 21:45. None of it is inside RTH.
#
# **Trades outside the book are implied matching.** They appear only on
# outrights and bundles, never on a listed spread, at rates of 0.01–0.10%. A
# spread order can execute against the outright book at a price the outright's
# own book never displayed, and the print lands outside it.

# %%
front_cross = replay("SR3M6").tob
front_cross = front_cross[front_cross["bid_px"] >= front_cross["ask_px"]]
front_cross.assign(cross_bp=(front_cross["bid_px"] - front_cross["ask_px"]) * 100.0)[
    ["ts_recv", "bid_px", "bid_sz", "ask_px", "ask_sz", "cross_bp"]
]

# %%
print("median |listed mid - leg-implied mid|, bp "
      "(one tick is 0.5 bp, so anything at or below that is agreement):")
implied[["symbol", "kind", "mid_abs_err_bp", "listed_spread_bp", "implied_spread_bp",
         "orientation", "n"]].sort_values("mid_abs_err_bp")
