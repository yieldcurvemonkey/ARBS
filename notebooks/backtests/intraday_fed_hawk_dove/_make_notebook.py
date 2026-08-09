"""Generate global_cb_speaker_hawk_dove_intraday_backtest.ipynb."""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "global_cb_speaker_hawk_dove_intraday_backtest.ipynb"

cells: list = []


def _lines(src: str) -> list:
    """nbformat wants a list of lines that KEEP their trailing newline; splitting
    on "\\n" and dropping them makes every cell one unparseable line."""
    return src.strip("\n").splitlines(keepends=True)


def md(src: str) -> None:
    cells.append({"cell_type": "markdown", "id": f"md{len(cells):02d}",
                  "metadata": {}, "source": _lines(src)})


def code(src: str) -> None:
    cells.append({
        "cell_type": "code", "id": f"cd{len(cells):02d}", "execution_count": None,
        "metadata": {}, "outputs": [], "source": _lines(src),
    })


# --------------------------------------------------------------------------
md(r"""
# Sellside Hawk/Dove Label Predictiveness — Global Front-End STIR Futures Around Central Bank Speeches

Extends the Fed-only SOFR study to **ECB (ESTR)**, **BOE (SONIA)** and **BOJ (TONA)**.

**Hypothesis** — if sellside hawk/dove labels carry information, the front end should systematically
misprice around speeches. Hawk → rates higher → **pay fixed = SELL the future**.
Dove → rates lower → **receive fixed = BUY the future**.

**Instrument** — `rateslib.STIRFuture` outrights via `Query.STIRFutures.STIRFutureQuery`
(the `RLSTIRFuturePricer` backend literally constructs `rl.STIRFuture`), priced from
Barchart minute bars through `STIRFutureMDP(source="BARCHART_STIRF-RL")`, run on the same
`QueryDrivenBacktest` / `TimeGrid` / `Trigger` / `AddQueryAction` / `UnwindPositionsAction`
pattern as the Fed notebook.

**Contract** — 3rd quarterly (the contract accruing from the 3rd IMM date), which is the
same instrument the Fed notebook's `IMM_3xIMM_4` swap tenor picked out.

### Four things that were measured, not assumed

| | finding |
|---|---|
| **Direction** | On the STIRFuture path a **negative `bpv` does not short** — it flips both the risk-weighted price and the PV01 and the two cancel, silently giving a LONG. The only correct short is `bpv=+X` with `risk_weights=[-1.0]`. Verified on SR3Z25. |
| **Intraday** | Without `market_request={"timestamp": "now"}` every query prices off the *daily* bar and all same-day P&L is exactly zero. |
| **Lookahead** | `STIRFutureMDP` serves the last bar at-or-before the request *inside* the session, but serves a **later** bar when the request precedes the day's first bar — measured up to 335 minutes of lookahead. Every event is gated on a real causal bar. |
| **Signal scale** | The JPM score is **not comparable across banks** (median `trailing_5_avg`: FED +12, ECB +10, BOE +15, BOJ −23). The Fed's absolute ±10/±20 cutoffs label 74% of BOE speeches hawk and 0% dove. Buckets are therefore assigned by **percentile within each bank's own trailing history**. |
""")

code(r"""
%load_ext autoreload
%autoreload 2

import sys, datetime, pickle
from pathlib import Path

REPO = r"C:\Users\chris\clee\ARBS-gcb"
HERE = Path(REPO) / "notebooks" / "backtests" / "intraday_fed_hawk_dove"
sys.path.insert(0, REPO)
sys.path.insert(0, str(HERE))

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.pylab as pylab
import seaborn as sns

plt.style.use("ggplot")
pylab.rcParams.update({
    "legend.fontsize": "large", "figure.figsize": (14, 7),
    "axes.labelsize": "large", "axes.titlesize": "large",
    "xtick.labelsize": "large", "ytick.labelsize": "large",
})

import global_hawk_dove_common as G
from global_hawk_dove_run import (
    SCORES_CSV, BT_START, BT_END, SCORE_METRIC, ENTRY_OFFSET, EXIT_OFFSET,
    BASE_BPV, CONTRACT_RANK, BLACKOUT_BD, MAX_STALENESS_MIN, BANKS, CACHE,
)
from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP

# cache_full_intraday_fetch: pull each symbol-day ONCE in full and serve every
# timestamp on that day from cache. The §8.4 sweep re-prices the same days at 20
# different entry/exit pairs, so without this it makes tens of thousands of
# per-timestamp requests and risks a rate-limit storm for no new data.
mdp = STIRFutureMDP(source="BARCHART_STIRF-RL", cache_full_intraday_fetch=True)

print(f"Backtest window : {BT_START} -> {BT_END}")
print(f"Entry / exit    : T{int(ENTRY_OFFSET.total_seconds()//60):+d}m / T{int(EXIT_OFFSET.total_seconds()//60):+d}m")
print(f"Contract        : {CONTRACT_RANK}rd quarterly   base bpv = {BASE_BPV:,.0f}")
print(f"Score metric    : {SCORE_METRIC}")
for b in BANKS:
    c = G.CB_CONFIGS[b]
    print(f"  {b:4s} root={c.root:4s} ccy={c.ccy}  session {c.session_start}-{c.session_end} {c.market_tz}")
""")

# --------------------------------------------------------------------------
md(r"""
## 1. Signal — JPM NLP hawk/dove scores for all four banks

`global_hawk_dove_scores.csv` is produced by `extract_global_hawk_dove_scores.py`, which parses the
same JPM PDF corpus as the Fed script. Its FED subset reproduces `fed_hawk_dove_scores.csv`
**exactly** (700 rows, 700 shared keys, zero value mismatches).
""")

code(r"""
scores = G.load_global_scores(SCORES_CSV, SCORE_METRIC)

cov = (scores.groupby("central_bank")
       .agg(speakers=("speaker", "nunique"), rows=("speaker", "count"),
            first=("date", "min"), last=("date", "max"),
            median_score=(SCORE_METRIC, "median")))
display(cov)

fig, axes = plt.subplots(1, 4, figsize=(18, 3.6), sharey=True)
for ax, b in zip(axes, BANKS):
    s = scores.loc[scores.central_bank == b, SCORE_METRIC].dropna()
    ax.hist(s, bins=30, color="steelblue", alpha=.75, edgecolor="k", linewidth=.4)
    ax.axvline(s.median(), color="crimson", lw=2, label=f"median {s.median():.0f}")
    ax.axvline(0, color="k", lw=.8)
    ax.set_title(f"{b}  (n={len(s)})"); ax.legend(fontsize=9)
axes[0].set_ylabel("speeches")
fig.suptitle(f"{SCORE_METRIC} by central bank — the scale is NOT comparable across banks", y=1.04)
plt.tight_layout(); plt.show()
""")

md(r"""
### 1.1 Why the buckets must be scaled per bank

A qualitative hawk/dove read should split roughly evenly within a bank. Applying the Fed's
absolute ±10/±20 cutoffs to every bank does the opposite — it turns the BOE leg into a
permanent short-rates bet and the BOJ leg into a permanent long-rates bet, which is a bet on
the sample period, not on the label.

The percentile bucketer ranks each score inside that bank's **trailing 60 observations**
(strictly before the speech date, so no lookahead) and buckets on the rank. The window is
trailing rather than expanding because an expanding window compares 2025-26 speeches to the
very hawkish 2022-23 era and leaks the drift back in as a directional tilt. **60 was chosen on
label balance alone, before any P&L was computed.**
""")

code(r"""
rows = []
for b in BANKS:
    pct_fn = G.make_percentile_bucketer(scores, b, SCORE_METRIC)
    abs_split = G.bucket_split(scores, b, SCORE_METRIC, lambda s, x, d: G.absolute_bucket(x))
    pct_split = G.bucket_split(scores, b, SCORE_METRIC, pct_fn)
    for name, sp in [("absolute ±10/±20", abs_split), ("percentile (trailing 60)", pct_split)]:
        rows.append({
            "bank": b, "scheme": name,
            "hawk": sum(v for k, v in sp.items() if k > 0),
            "neutral": sp.get(0, 0.0),
            "dove": sum(v for k, v in sp.items() if k < 0),
        })
split = pd.DataFrame(rows)
split["|hawk-dove|"] = (split["hawk"] - split["dove"]).abs()
display(split.style.format({"hawk": "{:.1%}", "neutral": "{:.1%}",
                            "dove": "{:.1%}", "|hawk-dove|": "{:.3f}"}))

fig, axes = plt.subplots(1, 2, figsize=(15, 4), sharey=True)
for ax, scheme in zip(axes, ["absolute ±10/±20", "percentile (trailing 60)"]):
    sub = split[split.scheme == scheme].set_index("bank")[["hawk", "neutral", "dove"]]
    sub.plot(kind="bar", stacked=True, ax=ax, rot=0,
             color=["#c0392b", "#bdc3c7", "#2471a3"], legend=(ax is axes[0]))
    ax.set_title(scheme); ax.set_ylabel("share of speeches")
plt.tight_layout(); plt.show()
""")

# --------------------------------------------------------------------------
md(r"""
## 2. Events, filters and the empirical data gate

Per bank: pull ForexFactory speaker events, map the title to a speaker, look up the most recent
score **strictly before** the speech date (the `trailing_5_avg` stamped on date X already contains
speech X's own score), drop policy-blackout days using that bank's own decision dates, size by
bucket, then run the **data gate**.

The gate keeps an event only if a genuine bar exists at-or-before both entry and exit, within
`MAX_STALENESS_MIN`, and the two are different bars. That converts three silent failure modes —
pre-session lookahead, stale marks, and same-bar fake zeros — into logged exclusions.
""")

code(r"""
# Stage 1 is expensive (calendar fetch + one minute-bar fetch per symbol-day), so it is
# cached to disk by global_hawk_dove_run.py. Run that script to rebuild.
with open(CACHE / "events.pkl", "rb") as f:
    events_by_bank = pickle.load(f)

funnel = []
for b in BANKS:
    d = events_by_bank[b]
    row = {"bank": b, "forexfactory": d["n_raw"]}
    row.update({f"excl:{k}": v for k, v in d["excluded"].items()})
    row.update({f"gate:{k}": v for k, v in d["gate_reasons"].items()})
    row["TRADEABLE"] = len(d["events"])
    funnel.append(row)
funnel = pd.DataFrame(funnel).set_index("bank").fillna(0).astype(int, errors="ignore")
display(funnel.T)
""")

code(r"""
# What the gate actually caught — the lookahead and staleness it removed.
diag = pd.concat([events_by_bank[b]["diag"] for b in BANKS
                  if len(events_by_bank[b]["diag"])], ignore_index=True)
if len(diag):
    display(pd.crosstab(diag["bank"], diag["reason"]))
    ok = diag[diag.reason == "ok"]
    print("\nStaleness of the marks that WERE traded (minutes since last bar):")
    display(ok.groupby("bank")[["entry_stale_min", "exit_stale_min"]]
            .describe().round(1).loc[:, (slice(None), ["mean", "50%", "max"])])
""")

# --------------------------------------------------------------------------
md(r"""
## 3. Run the backtest — one `QueryDrivenBacktest` per central bank

Separate runs per bank keep each book independent (no cross-currency stacking) and avoid a
mixed-timezone `TimeGrid`. Every query is a `rateslib.STIRFuture` outright sized in bpv with the
direction carried in `risk_weights`.
""")

code(r"""
with open(CACHE / "closed.pkl", "rb") as f:
    closed_by_bank = pickle.load(f)

for b in BANKS:
    cl = closed_by_bank.get(b)
    print(f"{b:4s} closed trades: {0 if cl is None or cl.empty else len(cl)}")

pooled = pd.concat([c for c in closed_by_bank.values() if c is not None and not c.empty],
                   ignore_index=True).sort_values("opened_at").reset_index(drop=True)
print(f"\npooled: {len(pooled)} trades  {pooled['opened_at'].min()} -> {pooled['opened_at'].max()}")
""")

md(r"""
### A note on units

`realized_pnl` is in each instrument's **own currency**, so USD, EUR and GBP P&L cannot be added.
Every pooled statistic below uses

$$\text{pnl\_bp} = \frac{\text{realized\_pnl}}{\text{bpv}}$$

which is literally the number of basis points the position moved in its favour — currency-free and
comparable across banks. Per-bank tables also show raw local-currency P&L.
""")

# --------------------------------------------------------------------------
md("## 4. Core performance")

code(r"""
rows = []
for b in BANKS:
    cl = closed_by_bank.get(b)
    if cl is None or cl.empty:
        rows.append({"bank": b, "trades": 0}); continue
    s = G.summarize(cl); s["bank"] = b; s["ccy"] = cl["ccy"].iloc[0]
    s["local_pnl"] = cl["realized_pnl"].sum()
    rows.append(s)
s = G.summarize(pooled); s["bank"] = "POOLED"; s["ccy"] = "bp"; s["local_pnl"] = np.nan
rows.append(s)

perf = pd.DataFrame(rows).set_index("bank")
cols = ["ccy", "trades", "total", "avg", "std", "hit_rate", "sharpe", "t_stat",
        "max_dd", "trades_per_year", "local_pnl", "first", "last"]
display(perf[[c for c in cols if c in perf.columns]].style.format({
    "total": "{:+.1f}bp", "avg": "{:+.3f}bp", "std": "{:.3f}", "hit_rate": "{:.1%}",
    "sharpe": "{:.2f}", "t_stat": "{:.2f}", "max_dd": "{:.1f}bp",
    "trades_per_year": "{:.0f}", "local_pnl": "{:,.0f}",
}, na_rep="—"))
""")

code(r"""
fig, axes = plt.subplots(2, 1, figsize=(14, 9), gridspec_kw={"height_ratios": [2, 1]})

ax = axes[0]
for b in BANKS:
    cl = closed_by_bank.get(b)
    if cl is None or cl.empty:
        continue
    cl = cl.sort_values("opened_at")
    ax.plot(cl["opened_at"].values, cl["pnl_bp"].cumsum().values, lw=1.6, label=f"{b} (n={len(cl)})")
ax.plot(pooled["opened_at"].values, pooled["pnl_bp"].cumsum().values,
        lw=2.4, color="k", ls="--", label=f"POOLED (n={len(pooled)})")
ax.axhline(0, color="k", lw=.6)
ax.set_ylabel("cumulative bp per unit risk")
ax.set_title("Cumulative P&L — global CB speaker hawk/dove, front-end STIR futures")
ax.legend(); ax.grid(alpha=.3)

ax = axes[1]
c = ["seagreen" if x > 0 else "indianred" for x in pooled["pnl_bp"]]
ax.bar(pooled["opened_at"].values, pooled["pnl_bp"].values, color=c, width=3, alpha=.7)
ax.axhline(0, color="k", lw=.6); ax.set_ylabel("per-trade bp"); ax.grid(alpha=.3)
plt.tight_layout(); plt.show()
""")

# --------------------------------------------------------------------------
md("## 5. P&L attribution by speaker")

code(r"""
sp = (pooled.groupby(["bank", "speaker"])
      .agg(trades=("pnl_bp", "count"), total_bp=("pnl_bp", "sum"),
           avg_bp=("pnl_bp", "mean"), hit=("profitable", "mean"),
           avg_score=("raw_score", "mean"))
      .sort_values("total_bp", ascending=False))
display(sp.style.format({"total_bp": "{:+.2f}", "avg_bp": "{:+.3f}",
                         "hit": "{:.1%}", "avg_score": "{:.1f}"}))

top = sp[sp.trades >= 5].sort_values("total_bp")
fig, ax = plt.subplots(figsize=(13, max(4, .32 * len(top))))
lbl = [f"{b}:{s}" for b, s in top.index]
ax.barh(lbl, top["total_bp"], color=["seagreen" if x > 0 else "indianred" for x in top["total_bp"]], alpha=.8)
ax.axvline(0, color="k", lw=.6); ax.set_xlabel("total bp per unit risk")
ax.set_title("Speaker attribution (≥5 trades)")
for i, (_, r) in enumerate(top.iterrows()):
    ax.text(r["total_bp"], i, f"  {int(r['trades'])}t {r['hit']:.0%}", va="center", fontsize=8)
plt.tight_layout(); plt.show()
""")

# --------------------------------------------------------------------------
md("## 6. Bucket response and hawk/dove asymmetry")

code(r"""
bk = (pooled.groupby("bucket")
      .agg(trades=("pnl_bp", "count"), total_bp=("pnl_bp", "sum"),
           avg_bp=("pnl_bp", "mean"), hit=("profitable", "mean")).sort_index())
print("By signed bucket (monotonicity in the signal is the thing to look for):")
display(bk.style.format({"total_bp": "{:+.2f}", "avg_bp": "{:+.3f}", "hit": "{:.1%}"}))

print("\nHawk vs dove:")
display(pooled.groupby("direction")
        .agg(trades=("pnl_bp", "count"), total_bp=("pnl_bp", "sum"),
             avg_bp=("pnl_bp", "mean"), hit=("profitable", "mean"))
        .style.format({"total_bp": "{:+.2f}", "avg_bp": "{:+.3f}", "hit": "{:.1%}"}))

print("\nBy conviction |bucket|:")
display(pooled.groupby("abs_bucket")
        .agg(trades=("pnl_bp", "count"), total_bp=("pnl_bp", "sum"),
             avg_bp=("pnl_bp", "mean"), hit=("profitable", "mean"))
        .style.format({"total_bp": "{:+.2f}", "avg_bp": "{:+.3f}", "hit": "{:.1%}"}))

fig, ax = plt.subplots(figsize=(9, 4.5))
ax.bar(bk.index.astype(str), bk["avg_bp"],
       color=["#2471a3" if i < 0 else "#c0392b" for i in bk.index], alpha=.85)
ax.axhline(0, color="k", lw=.6)
ax.set_xlabel("signal bucket (− dove / + hawk)"); ax.set_ylabel("avg bp per trade")
ax.set_title("Signal response curve — a real signal should slope upward")
plt.tight_layout(); plt.show()
""")

# --------------------------------------------------------------------------
md("## 7. Calendar-year breakdown")

code(r"""
yr = (pooled.groupby(["year"])
      .agg(trades=("pnl_bp", "count"), total_bp=("pnl_bp", "sum"),
           avg_bp=("pnl_bp", "mean"), std=("pnl_bp", "std"), hit=("profitable", "mean")))
yr["sharpe"] = yr["avg_bp"] / yr["std"] * np.sqrt(yr["trades"])
display(yr.style.format({"total_bp": "{:+.2f}", "avg_bp": "{:+.3f}", "std": "{:.3f}",
                         "hit": "{:.1%}", "sharpe": "{:.2f}"}))

yb = pooled.pivot_table(index="year", columns="bank", values="pnl_bp", aggfunc="sum")
fig, ax = plt.subplots(figsize=(11, 5))
yb.plot(kind="bar", ax=ax, rot=0, alpha=.85)
ax.axhline(0, color="k", lw=.6); ax.set_ylabel("total bp per unit risk")
ax.set_title("Annual P&L by central bank"); plt.tight_layout(); plt.show()
""")

# --------------------------------------------------------------------------
md(r"""
## 8. Robustness

### 8.0 Direction check, and the closed form used by the sweeps

Two things are established here before any robustness number is read.

**Direction.** Hawk must SELL. Reconciling every trade's engine P&L against the bar prices
the gate recorded shows hawks lost money on ~100% of price-up trades and doves on ~0% — so
`bpv=+X, risk_weights=[-1.0]` really does short. (A negative `bpv` would have gone long and
this table is what would have caught it.)

**Closed form.** `STIRFutureHandler.value_position` is exactly `(Δprice/0.01) × side × bpv`,
so the gate's own bar prices reproduce the engine to the tick. The sensitivity sweeps below
use that closed form instead of 21 more engine passes at ~15 minutes each. The headline
numbers in §4–§7 all come from the engine.
""")

code(r"""
val = G.validate_fast_vs_engine(events_by_bank, closed_by_bank)
display(val.style.format({"max_abs_diff_bp": "{:.6f}",
                          "total_closed_form_bp": "{:+.2f}",
                          "total_engine_bp": "{:+.2f}"}))

rows = []
for b in BANKS:
    cl = closed_by_bank.get(b)
    if cl is None or cl.empty:
        continue
    evs = {e["tag"]: e for e in events_by_bank[b]["events"]}
    for _, r in cl.iterrows():
        tag = next(iter(r["source_query"].tags), None)
        ev = evs.get(tag)
        if ev is None or "entry_bar_px" not in ev:
            continue
        rows.append({"bank": b, "side": ev["side"],
                     "d_px": ev["exit_bar_px"] - ev["entry_bar_px"],
                     "pnl_bp": r["pnl_bp"]})
d = pd.DataFrame(rows)
up = d[d.d_px > 0]
chk = (up.assign(lost=up.pnl_bp < 0)
       .groupby(["bank", "side"])["lost"].agg(["count", "mean"])
       .rename(columns={"count": "price_up_trades", "mean": "share_that_lost"}))
print("On trades where the PRICE ROSE (rates fell):")
print("  side=-1 is the hawk/short — it MUST lose.   side=+1 is the dove/long — it must NOT.")
display(chk.style.format({"share_that_lost": "{:.1%}"}))
""")

md(r"""
### 8.1 Sign-flip permutation test

Null hypothesis: the labels carried no direction. Each trade's realised move is preserved and only
the side is randomised, so the test asks exactly whether the hawk/dove call — not the market's
volatility — produced the result.
""")

code(r"""
fig, axes = plt.subplots(1, len(BANKS) + 1, figsize=(19, 3.4))
perm_rows = []
for ax, b in zip(axes, BANKS + ["POOLED"]):
    cl = pooled if b == "POOLED" else closed_by_bank.get(b)
    if cl is None or cl.empty or len(cl) < 10:
        ax.set_title(f"{b}: n/a"); ax.axis("off"); perm_rows.append({"bank": b}); continue
    r = G.sign_flip_permutation(cl, n_perm=2000)
    perm_rows.append({"bank": b, "realized_sharpe": r["realized_sharpe"],
                      "null_mean": r["perm_mean"], "null_std": r["perm_std"],
                      "p_value": r["p_value"]})
    ax.hist(r["perm"], bins=45, color="lightgrey", edgecolor="k", linewidth=.3)
    ax.axvline(r["realized_sharpe"], color="crimson", lw=2)
    ax.set_title(f"{b}  p={r['p_value']:.3f}", fontsize=11)
    ax.set_xlabel("Sharpe")
plt.tight_layout(); plt.show()

display(pd.DataFrame(perm_rows).set_index("bank").style.format(
    {"realized_sharpe": "{:.3f}", "null_mean": "{:.3f}",
     "null_std": "{:.3f}", "p_value": "{:.4f}"}, na_rep="—"))
""")

md("### 8.2 Subsample stability")

code(r"""
rows = []
for b in BANKS + ["POOLED"]:
    cl = pooled if b == "POOLED" else closed_by_bank.get(b)
    if cl is None or cl.empty or len(cl) < 8:
        continue
    cl = cl.sort_values("opened_at").reset_index(drop=True)
    mid = len(cl) // 2
    for name, sub in [("1st half", cl.iloc[:mid]), ("2nd half", cl.iloc[mid:])]:
        s = G.summarize(sub)
        rows.append({"bank": b, "half": name, "trades": s["trades"],
                     "total_bp": s["total"], "avg_bp": s["avg"],
                     "hit": s["hit_rate"], "sharpe": s["sharpe"],
                     "range": f"{s['first'].date()} → {s['last'].date()}"})
display(pd.DataFrame(rows).set_index(["bank", "half"]).style.format(
    {"total_bp": "{:+.2f}", "avg_bp": "{:+.3f}", "hit": "{:.1%}", "sharpe": "{:.2f}"}))
""")

md(r"""
### 8.3 Transaction-cost sensitivity

Cost is charged in bp of round-trip per unit of risk, which in `pnl_bp` units is a flat subtraction.
The listed SR3 outright is roughly a quarter-tick wide (~0.25bp round trip); the ESTR and SONIA
strips are wider.
""")

code(r"""
rows = []
for cost in [0.0, 0.125, 0.25, 0.5, 1.0, 2.0]:
    for b in BANKS + ["POOLED"]:
        cl = pooled if b == "POOLED" else closed_by_bank.get(b)
        if cl is None or cl.empty:
            continue
        adj = cl["pnl_bp"] - cost
        n = len(adj); std = adj.std()
        years = max((cl["opened_at"].max() - cl["opened_at"].min()).days / 365.25, 1e-9)
        sr = adj.mean() / std * np.sqrt(n / years) if std > 0 else 0.0
        rows.append({"cost_bp_rt": cost, "bank": b, "total_bp": adj.sum(),
                     "avg_bp": adj.mean(), "hit": (adj > 0).mean(), "sharpe": sr})
cost_df = pd.DataFrame(rows).pivot(index="cost_bp_rt", columns="bank",
                                   values=["avg_bp", "sharpe"])
display(cost_df.style.format("{:+.3f}"))

fig, ax = plt.subplots(figsize=(9, 4.5))
for b in BANKS + ["POOLED"]:
    if ("sharpe", b) in cost_df.columns:
        ax.plot(cost_df.index, cost_df[("sharpe", b)], marker="o", label=b)
ax.axhline(0, color="k", lw=.6); ax.set_xlabel("round-trip cost (bp)")
ax.set_ylabel("Sharpe"); ax.set_title("Cost sensitivity"); ax.legend()
plt.tight_layout(); plt.show()
""")

md(r"""
### 8.4 Entry / exit window sensitivity

Each cell is a full re-run: events are re-timed, **re-clamped to the session and re-gated**, then
re-priced. Re-gating matters — a wider exit offset can walk past the last bar of the day, and an
ungated re-run would mark it against a lookahead bar instead of dropping it.
""")

code(r"""
ENTRY_MIN = [-120, -60, -45, -15]
EXIT_MIN = [60, 120, 180, 240, 360]

# Every cell re-gates the SAME symbol-days, so warm the shared bar cache once.
print(f"bar cache: {G.load_bar_cache(CACHE / 'bars.pkl')} symbol-days preloaded")

ev_only = {b: events_by_bank[b]["events"] for b in BANKS if events_by_bank[b]["events"]}

variants = {}
for eo in ENTRY_MIN:
    for xo in EXIT_MIN:
        variants[f"{eo}|{xo}"] = (
            lambda bank, evs, _e=eo, _x=xo: G.rebuild_with_offsets(
                evs, G.CB_CONFIGS[bank],
                datetime.timedelta(minutes=_e), datetime.timedelta(minutes=_x))
        )

grid = G.sweep(ev_only, mdp, variants)
grid[["entry", "exit"]] = grid["variant"].str.split("|", expand=True).astype(int)

sh = grid.pivot(index="entry", columns="exit", values="sharpe")
av = grid.pivot(index="entry", columns="exit", values="avg")
nt = grid.pivot(index="entry", columns="exit", values="trades")

fig, axes = plt.subplots(1, 3, figsize=(19, 4.2))
sns.heatmap(sh.astype(float), annot=True, fmt=".2f", cmap="RdYlGn", center=0, ax=axes[0])
axes[0].set_title("Sharpe (pooled)")
sns.heatmap(av.astype(float), annot=True, fmt=".3f", cmap="RdYlGn", center=0, ax=axes[1])
axes[1].set_title("Avg bp / trade")
sns.heatmap(nt.astype(float), annot=True, fmt=".0f", cmap="Blues", ax=axes[2])
axes[2].set_title("Trade count")
for a in axes:
    a.set_xlabel("exit offset (min)"); a.set_ylabel("entry offset (min)")
plt.tight_layout(); plt.show()
display(grid.sort_values("sharpe", ascending=False).head(10))
""")

md(r"""
### 8.5 Contract selection (1st through 5th quarterly)

Unlike the entry/exit sweep, this asks for **different contracts**, so it needs minute bars
that the baseline never fetched. A Jupyter kernel cannot fetch them — the Barchart fetcher
hits the already-running event loop and hands back a coroutine — so the bar cache must be
pre-warmed from a plain process first:

```
python global_hawk_dove_run.py --stage prewarm
```

`_day_bars` now raises rather than returning an empty frame in that situation. That matters:
silently treating a failed fetch as "no bars that day" is exactly how a sensitivity table
gets computed from no data at all and still prints numbers.
""")

code(r"""
variants = {
    f"{r}Q": (lambda bank, evs, _r=r: G.rebuild_with_contract(evs, G.CB_CONFIGS[bank], _r))
    for r in [1, 2, 3, 4, 5]
}

# Fail loudly if the cache is cold rather than reporting a sweep over nothing.
missing = 0
for b, evs in ev_only.items():
    for r in [1, 2, 4, 5]:
        for e in G.rebuild_with_contract(evs, G.CB_CONFIGS[b], r):
            if (e["symbol"], e["entry_ts"].date()) not in G._BAR_CACHE:
                missing += 1
if missing:
    raise RuntimeError(
        f"{missing} symbol-days are not in the bar cache. Run "
        "`python global_hawk_dove_run.py --stage prewarm` first — this sweep cannot "
        "fetch from inside a kernel and would otherwise report an empty grid."
    )
print("bar cache covers every contract rank — sweeping")
ten = G.sweep(ev_only, mdp, variants)
display(ten[["variant", "trades", "total", "avg", "hit_rate", "sharpe", "t_stat"]]
        .style.format({"total": "{:+.2f}", "avg": "{:+.3f}", "hit_rate": "{:.1%}",
                       "sharpe": "{:.2f}", "t_stat": "{:.2f}"}))

fig, ax = plt.subplots(figsize=(9, 4.2))
ax.bar(ten["variant"], ten["sharpe"], color="steelblue", alpha=.85)
ax.axhline(0, color="k", lw=.6); ax.set_ylabel("Sharpe (pooled)")
ax.set_title("Contract selection sensitivity"); plt.tight_layout(); plt.show()
""")

md(r"""
### 8.6 Does the per-bank scaling matter?

Re-runs the whole thing with the Fed's **absolute** ±10/±20 cutoffs applied to every bank. This is
the faithful naive extension, and the comparison shows how much of any result comes from the
signal versus from a constant directional tilt.
""")

code(r"""
# Rebuild the whole event set under the Fed's absolute cutoffs. The bar cache is
# already warm, so the gate is cheap and no new data is fetched.
abs_by_bank, abs_frames = {}, []
for b in BANKS:
    # A bank with no tradeable baseline has no book under either scheme. BOJ is
    # the case: its contracts do not exist on Barchart, so a fetch raises rather
    # than returning an empty day and no amount of pre-warming can satisfy it.
    if not events_by_bank[b]["events"]:
        print(f"  {b}: no tradeable book under either scheme — skipped")
        continue
    cfg = G.CB_CONFIGS[b]
    raw = G.fetch_events(cfg, BT_START, BT_END)
    lookup = G.ScoreLookup(scores, b, SCORE_METRIC)
    evs, _excl = G.build_trade_events(
        cfg, raw, lookup,
        entry_offset=ENTRY_OFFSET, exit_offset=EXIT_OFFSET,
        base_bpv=BASE_BPV, contract_rank=CONTRACT_RANK,
        bucket_fn=lambda _s, x, _d: G.absolute_bucket(x),
        blackout_fn=G.make_blackout_fn(cfg, BLACKOUT_BD),
    )
    evs, _ = G.drop_overlaps(evs)
    evs, _r, _d = G.gate_events(evs, cfg, mdp, max_staleness_min=MAX_STALENESS_MIN,
                                show_progress=False)
    # The absolute cutoffs select a DIFFERENT subset of speeches, on days the
    # percentile run never gated. If those bars are not cached this cell cannot
    # fetch them (kernel), and they would be logged as "no bars that day" — a
    # failed fetch quietly impersonating a quiet market. Refuse to report that.
    if _r.get("fetch_failed"):
        raise RuntimeError(
            f"{b}: {_r['fetch_failed']} bar fetches FAILED (not empty days). "
            "Run `python global_hawk_dove_run.py --stage prewarm` — this cell "
            "cannot fetch from inside a kernel and would under-count."
        )
    abs_by_bank[b] = evs
    f = G.fast_backtest(evs)
    if not f.empty:
        abs_frames.append(f)
    print(f"  {b}: {len(evs)} tradeable under absolute cutoffs  (gate: {_r})")

pooled_abs = (pd.concat(abs_frames, ignore_index=True).sort_values("opened_at")
              if abs_frames else pd.DataFrame())

# Compare like with like: the percentile book re-priced with the same closed form.
pooled_pct_fast = pd.concat(
    [G.fast_backtest(events_by_bank[b]["events"]) for b in BANKS
     if events_by_bank[b]["events"]], ignore_index=True).sort_values("opened_at")

rows = []
for lbl, p in [("percentile (per-bank, trailing 60)", pooled_pct_fast),
               ("absolute ±10/±20 (Fed cutoffs)", pooled_abs)]:
    if p.empty:
        continue
    s = G.summarize(p)
    s["scheme"] = lbl
    s["hawk_share"] = (p["bucket"] > 0).mean()
    rows.append(s)
display(pd.DataFrame(rows).set_index("scheme")[
    ["trades", "total", "avg", "hit_rate", "sharpe", "t_stat", "hawk_share"]]
    .style.format({"total": "{:+.2f}", "avg": "{:+.3f}", "hit_rate": "{:.1%}",
                   "sharpe": "{:.2f}", "t_stat": "{:.2f}", "hawk_share": "{:.1%}"}))

if not pooled_abs.empty:
    print("\nPer-bank hawk share — the tell that absolute cutoffs are a level bet:")
    display(pd.DataFrame({
        "absolute": pooled_abs.groupby("bank").apply(lambda d: (d.bucket > 0).mean()),
        "percentile": pooled_pct_fast.groupby("bank").apply(lambda d: (d.bucket > 0).mean()),
    }).style.format("{:.1%}"))
""")

# --------------------------------------------------------------------------
md("## 9. Full trade log")

code(r"""
log = pooled[["bank", "ccy", "opened_at", "closed_at", "speaker", "symbol", "direction",
              "bucket", "raw_score", "bpv", "realized_pnl", "pnl_bp", "profitable"]].copy()
log["cum_bp"] = log["pnl_bp"].cumsum()
display(log.style.format({"raw_score": "{:.1f}", "bpv": "{:,.0f}",
                          "realized_pnl": "{:,.0f}", "pnl_bp": "{:+.3f}",
                          "cum_bp": "{:+.2f}"})
        .bar(subset=["pnl_bp"], color=["#d65f5f", "#5fba7d"], align="zero"))

log.to_csv(HERE / "_global_cache" / "global_trade_log.csv", index=False)
print(f"wrote {HERE / '_global_cache' / 'global_trade_log.csv'}")
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
