"""Generate usd_fomc_speaker_hawk_dove_backtest.ipynb."""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "usd_fomc_speaker_hawk_dove_backtest.ipynb"

cells: list = []


def _lines(src: str) -> list:
    return src.strip("\n").splitlines(keepends=True)


def md(src: str) -> None:
    cells.append({"cell_type": "markdown", "id": f"md{len(cells):02d}",
                  "metadata": {}, "source": _lines(src)})


def code(src: str) -> None:
    cells.append({"cell_type": "code", "id": f"cd{len(cells):02d}",
                  "execution_count": None, "metadata": {}, "outputs": [],
                  "source": _lines(src)})


# ---------------------------------------------------------------------------
md(r"""
# FOMC Speaker Hawk/Dove — USD Front-End SOFR Futures

USD only. The pooled six-currency study answers "does this work anywhere"; this one asks the
narrower and more useful question — **does it work on the Fed, where the data is deepest and the
committee is large enough for "relative to peers" to mean something.**

The FOMC is the only committee here with 26 scored speakers. The BoJ has 12, the SNB has 4 and
Norges has 2 — with two people there is no committee to be relative to. So the labelling idea
that the global study could only gesture at can actually be tested here.

### What is traded

`rateslib.STIRFuture` outrights on **SR3 (3M SOFR, CME)** through
`Query.STIRFutures.STIRFutureQuery`, priced from Barchart minute bars, run on the same
`QueryDrivenBacktest` / `TimeGrid` / `Trigger` / `AddQueryAction` / `UnwindPositionsAction`
pattern as the original notebook. Hawk → rates higher → **pay fixed = SELL the future**.

### The labelling, which is the point of this notebook

A hawk/dove score is only meaningful **relative to the speaker's own committee at that moment**.
In 2022 every FOMC member sounded hawkish in absolute terms; only some were hawkish *relative to
their peers*, and only that difference can move a price that already embeds the consensus.

| scheme | what it asks | FOMC hawk / dove split |
|---|---|---|
| `absolute` | is the score above ±10/±20 | **55% / 8%** — a standing short-rates bet |
| `percentile` | is this speech hawkish *for this speaker* | 38% / 38% |
| **`peer`** | **is this speaker hawkish *for this committee*** | **37% / 41%** |

### Four things measured rather than assumed

| | finding |
|---|---|
| **Direction** | A negative `bpv` does **not** short on this path — it flips both the risk-weighted price and the PV01 and the two cancel, silently giving a LONG. The only correct short is `bpv=+X` with `risk_weights=[-1.0]`. |
| **Intraday** | Without `market_request={"timestamp": "now"}` every query prices off the *daily* bar and all same-day P&L is exactly zero. |
| **Lookahead** | The MDP serves a **later** bar when the request precedes the session's first bar — up to 335 minutes ahead. Every event is gated on a real causal bar at both ends. |
| **Score vintage** | 60.5% of JPM score rows are published *after* the speech, and JPM re-scores history. Every lookup and every reference distribution is gated on publication date, which deletes the pre-2023 sample entirely. |
""")

code(r"""
%load_ext autoreload
%autoreload 2

import sys, pickle, datetime
from pathlib import Path

REPO = r"C:\Users\chris\clee\ARBS-gcb"
HERE = Path(REPO) / "notebooks" / "backtests" / "intraday_fed_hawk_dove"
sys.path.insert(0, REPO); sys.path.insert(0, str(HERE))

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.pylab as pylab
import seaborn as sns

plt.style.use("ggplot")
pylab.rcParams.update({"figure.figsize": (14, 6), "axes.titlesize": "large",
                       "axes.labelsize": "large"})

import global_hawk_dove_common as G
import global_hawk_dove_grid as GRID
import fomc_extras as FX
from global_hawk_dove_run import (
    SCORES_CSV, BT_START, BT_END, SCORE_METRIC, ENTRY_OFFSET, EXIT_OFFSET,
    BASE_BPV, CONTRACT_RANK, BLACKOUT_BD, MAX_STALENESS_MIN, CACHE,
)
from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP

BANK = "FED"
cfg = G.CB_CONFIGS[BANK]
mdp = STIRFutureMDP(source="BARCHART_STIRF-RL", cache_full_intraday_fetch=True)

print(f"leg          : {BANK}  root={cfg.root}  ccy={cfg.ccy}")
print(f"session      : {cfg.session_start}-{cfg.session_end} {cfg.market_tz}")
print(f"window       : {BT_START} -> {BT_END}")
print(f"entry / exit : T{int(ENTRY_OFFSET.total_seconds()//60):+d}m / T{int(EXIT_OFFSET.total_seconds()//60):+d}m")
print(f"contract     : {CONTRACT_RANK}rd quarterly SR3, base bpv {BASE_BPV:,.0f}")
""")

# ---------------------------------------------------------------------------
md("## 1. The signal")

code(r"""
scores = G.load_global_scores(SCORES_CSV, SCORE_METRIC)
fed = scores[scores.central_bank == BANK].copy()

print(f"{len(fed)} scored FOMC speeches, {fed.speaker.nunique()} speakers, "
      f"{fed.date.min()} -> {fed.date.max()}")
print(f"publication lag (days after the speech): median "
      f"{(pd.to_datetime(fed.pub_date) - pd.to_datetime(fed.date)).dt.days.median():.0f}, "
      f"p90 {(pd.to_datetime(fed.pub_date) - pd.to_datetime(fed.date)).dt.days.quantile(.9):.0f}")

top = (fed.groupby("speaker")
       .agg(speeches=("hawk_dove_score", "count"),
            mean_score=("hawk_dove_score", "mean"),
            first=("date", "min"), last=("date", "max"))
       .sort_values("speeches", ascending=False).round(1))
top["role"] = [FX.role_of(s) for s in top.index]
display(top)

fig, axes = plt.subplots(1, 2, figsize=(15, 4))
axes[0].hist(fed[SCORE_METRIC].dropna(), bins=30, color="steelblue",
             alpha=.8, edgecolor="k", lw=.4)
axes[0].axvline(fed[SCORE_METRIC].median(), color="crimson", lw=2,
                label=f"median {fed[SCORE_METRIC].median():.0f}")
axes[0].axvline(0, color="k", lw=.8)
axes[0].set_title(f"FOMC {SCORE_METRIC}"); axes[0].legend()

m = (fed.assign(ym=pd.to_datetime(fed.date).dt.to_period("Q").astype(str))
     .groupby("ym")[SCORE_METRIC].median())
axes[1].plot(m.index, m.values, marker="o", color="darkslateblue")
axes[1].axhline(0, color="k", lw=.8)
axes[1].set_title("committee median score by quarter — the level drifts, which is\n"
                  "exactly why an absolute cutoff becomes a directional bet")
axes[1].tick_params(axis="x", rotation=60)
plt.tight_layout(); plt.show()
""")

md(r"""
### 1.1 Absolute cutoffs turn the FOMC into a standing short

The committee median drifts with the cycle. A fixed ±10/±20 threshold therefore does not measure
hawkishness — it measures *where we are in the cycle*, and puts most of the book on one side of
the market for years at a time.

`peer` fixes this by scoring each speech against the cross-section of the **other** FOMC members'
most recent scores, using only observations that were both prior and already published.
""")

code(r"""
pct = G.make_percentile_bucketer(scores, BANK, SCORE_METRIC)
peer = G.make_peer_relative_bucketer(scores, BANK, SCORE_METRIC, fallback=pct)
SCHEMES = [("absolute", lambda s, x, d: G.absolute_bucket(x)),
           ("percentile", pct), ("peer", peer)]

rows, splits = [], {}
for name, fn in SCHEMES:
    sp = G.bucket_split(scores, BANK, SCORE_METRIC, fn)
    splits[name] = sp
    h = sum(v for k, v in sp.items() if k > 0)
    d_ = sum(v for k, v in sp.items() if k < 0)
    rows.append({"scheme": name, "hawk": h, "neutral": sp.get(0, 0.0),
                 "dove": d_, "|hawk-dove|": abs(h - d_)})
display(pd.DataFrame(rows).set_index("scheme").style.format("{:.1%}"))

fig, axes = plt.subplots(1, 2, figsize=(15, 4.5))
pd.DataFrame({k: v for k, v in splits.items()}).T[[-2, -1, 0, 1, 2]].plot(
    kind="bar", stacked=True, ax=axes[0], rot=0,
    color=["#1a5276", "#5499c7", "#bdc3c7", "#e59866", "#a93226"])
axes[0].set_title("bucket distribution by scheme"); axes[0].set_ylabel("share of speeches")
axes[0].legend(title="bucket", fontsize=8)

# how the label moves through the cycle
fed2 = fed.dropna(subset=[SCORE_METRIC]).copy()
fed2["q"] = pd.to_datetime(fed2.date).dt.to_period("Q").astype(str)
for name, fn in SCHEMES:
    fed2[name] = [fn(sp, sc_, dt) for sp, sc_, dt in
                  zip(fed2.speaker, fed2[SCORE_METRIC], fed2.date)]
share = fed2.groupby("q")[[n for n, _ in SCHEMES]].apply(lambda g: (g > 0).mean())
share.plot(ax=axes[1], marker="o")
axes[1].axhline(0.5, color="k", ls="--", lw=.8)
axes[1].set_title("hawk share through time — flat is what a label should look like")
axes[1].set_ylabel("share labelled hawk"); axes[1].tick_params(axis="x", rotation=60)
plt.tight_layout(); plt.show()
""")

md(r"""
### 1.2 The committee genuinely rotates

The hand-researched standing table (129 speakers across 8 banks, web-researched with two
adversarial audits per bank) records **13 FOMC members changing side** over this window — Bowman
+1 → +2 → −2 → −1, Waller +1 → +2 → −2 → 0, Kashkari −2 → +2 → 0 → +1 → +2. That is not noise; it
is what a real committee does.

**This table is not tradeable.** It was written in 2026 from sources that postdate these trades,
and its period boundaries are its largest free parameter. It is shown here because it is the
clearest picture of *what the peer-relative label is trying to recover from data alone*, and it is
scored later strictly as an upper bound.
""")

code(r"""
import json
stances = G.load_researched_stances(HERE / "research_stances.json")
fs = (stances.get(BANK) or {}).get("speakers", {})

years = list(range(2021, 2027))
present = [s for s in top.index if s in fs]
grid_rows = []
for sp in present:
    fn = G.make_researched_bucketer({BANK: {"speakers": {sp: fs[sp]}}}, BANK)
    grid_rows.append([fn(sp, np.nan, datetime.date(y, 7, 1)) for y in years])
mat = pd.DataFrame(grid_rows, index=present, columns=years)

fig, ax = plt.subplots(figsize=(9, max(4, .32 * len(mat))))
sns.heatmap(mat, cmap="RdBu_r", center=0, vmin=-2, vmax=2, annot=True, fmt="d",
            cbar_kws={"label": "researched standing (+hawk / -dove)"}, ax=ax,
            linewidths=.4, linecolor="white")
ax.set_title("Researched standing within the FOMC, by year (NOT point-in-time)")
plt.tight_layout(); plt.show()

movers = {k: v for k, v in fs.items() if len(v) > 1}
print(f"{len(movers)} of {len(fs)} researched FOMC speakers changed side at least once:")
for k, v in list(movers.items())[:12]:
    print(f"  {k:11s} " + "  ".join(f"{p['start']}:{p['stance']:+d}" for p in v))
""")

# ---------------------------------------------------------------------------
md(r"""
## 2. Events, filters and the causal-bar gate

Speaker events come from ForexFactory where it carries a timestamp, and from the JPM reports
where it does not — those trade the whole session (we know the day, not the minute) and are tagged
`synthetic` so every result can be split by whether the timing was real or assumed.

The gate keeps an event only where a genuine bar exists at-or-before **both** entry and exit,
within the staleness bound, on a day that is not a padded grid. That converts pre-session
lookahead, stale marks and fake zeros into logged exclusions instead of silent P&L.
""")

code(r"""
with open(CACHE / "events.pkl", "rb") as f:
    events_by_bank = pickle.load(f)
d = events_by_bank[BANK]
events = d["events"]
f_ = d.get("funnel", {})

row = {"forexfactory rows": f_.get("n_forexfactory_rows", 0),
       "timed events": f_.get("n_timed", 0),
       "synthetic events": f_.get("n_synthetic", 0)}
row.update({f"ff excluded: {k}": v for k, v in (f_.get("forexfactory") or {}).items()})
row.update({f"syn excluded: {k}": v for k, v in (f_.get("synthetic") or {}).items()})
row.update({f"gate: {k}": v for k, v in (d.get("gate_reasons") or {}).items()})
row["TRADEABLE"] = len(events)
row["  of which synthetic"] = sum(1 for e in events
                                  if e.get("timestamp_source") == "synthetic")
display(pd.Series(row).to_frame("FOMC"))

diag = d.get("diag")
if diag is not None and len(diag):
    ok = diag[diag.reason == "ok"]
    print("staleness of the marks actually traded (minutes since the last bar):")
    display(ok[["entry_stale_min", "exit_stale_min"]].describe().round(1).T)
""")

# ---------------------------------------------------------------------------
md("## 3. Performance")

code(r"""
with open(CACHE / "closed.pkl", "rb") as f:
    closed_all = pickle.load(f)
closed = closed_all[BANK].sort_values("opened_at").reset_index(drop=True)
print(f"{len(closed)} closed trades  {closed.opened_at.min()} -> {closed.opened_at.max()}")

rows = []
for lbl, col in [("equal weight (pnl_bp)", "pnl_bp"),
                 ("as sized (x |bucket|)", "pnl_bp_sized")]:
    if col not in closed.columns:
        continue
    s = G.summarize(closed, pnl_col=col)
    rows.append({"book": lbl, "trades": s["trades"], "total_bp": s["total"],
                 "avg_bp": s["avg"], "hit": s["hit_rate"], "sharpe": s["sharpe"],
                 "t_stat": s["t_stat"], "max_dd": s["max_dd"]})
display(pd.DataFrame(rows).set_index("book").round(4))
print("The engine sizes at |bucket| x BASE_BPV, but pnl_bp divides that back out, so the")
print("equal-weight row is a DIFFERENT portfolio from the one actually held. Both are shown.")

fig, axes = plt.subplots(2, 1, figsize=(14, 8), gridspec_kw={"height_ratios": [2, 1]})
ax = axes[0]
ax.plot(closed.opened_at.values, closed.pnl_bp.cumsum().values, lw=1.8,
        color="darkslateblue", label="equal weight")
if "pnl_bp_sized" in closed:
    ax.plot(closed.opened_at.values, closed.pnl_bp_sized.cumsum().values, lw=1.4,
            color="darkorange", ls="--", label="as sized")
ax.axhline(0, color="k", lw=.6); ax.legend(); ax.grid(alpha=.3)
ax.set_ylabel("cumulative bp per unit risk")
ax.set_title("FOMC speaker hawk/dove — SR3 3rd quarterly, committee-relative labels")

ax = axes[1]
c = ["seagreen" if x > 0 else "indianred" for x in closed.pnl_bp]
ax.bar(closed.opened_at.values, closed.pnl_bp.values, color=c, width=2.5, alpha=.7)
ax.axhline(0, color="k", lw=.6); ax.set_ylabel("per-trade bp"); ax.grid(alpha=.3)
plt.tight_layout(); plt.show()
""")

# ---------------------------------------------------------------------------
md(r"""
## 4. Who moves the market

This is the cut the pooled study cannot make. Two features of the FOMC are known at trade time
and cost nothing to condition on:

* **whether the speaker votes this year.** Governors always vote; regional presidents rotate on a
  published schedule fixed years in advance — New York every year, then
  (Boston, Philadelphia, Richmond), (Cleveland, Chicago), (Atlanta, St. Louis, Dallas),
  (Minneapolis, Kansas City, San Francisco).
* **their role** — Chair, Governor, or regional President.

Neither is fitted to the outcome, and both are the kind of thing a desk would condition on
anyway, which is what makes them worth more than a grid cell.
""")

code(r"""
ann = FX.annotate(closed)

def block(g, by):
    t = g.groupby(by, observed=False).agg(
        trades=("pnl_bp", "size"), total_bp=("pnl_bp", "sum"),
        avg_bp=("pnl_bp", "mean"), hit=("profitable", "mean"))
    t["t_stat"] = g.groupby(by, observed=False)["pnl_bp"].apply(
        lambda x: x.mean() / (x.std(ddof=1) / np.sqrt(len(x))) if len(x) > 2 and x.std() else np.nan)
    return t.round(4)

print("by voting status:")
display(block(ann, ann["is_voter"].map({True: "votes this year", False: "does not vote"})
              .fillna("unknown")))
print("by role:")
display(block(ann, "role"))

fig, axes = plt.subplots(1, 2, figsize=(15, 4.5))
v = ann.dropna(subset=["is_voter"]).copy()
for lab, sub in v.groupby(v.is_voter.map({True: "votes", False: "no vote"})):
    sub = sub.sort_values("opened_at")
    axes[0].plot(sub.opened_at.values, sub.pnl_bp.cumsum().values, lw=1.8, label=lab)
axes[0].axhline(0, color="k", lw=.6); axes[0].legend()
axes[0].set_title("cumulative bp — voters vs non-voters"); axes[0].set_ylabel("bp")

r = ann.groupby("role")["pnl_bp"].mean().sort_values()
axes[1].barh(r.index, r.values,
             color=["indianred" if x < 0 else "seagreen" for x in r.values], alpha=.8)
axes[1].axvline(0, color="k", lw=.6); axes[1].set_xlabel("avg bp / trade")
axes[1].set_title("by role")
plt.tight_layout(); plt.show()
""")

md(r"""
### 4.1 Is the voter split real, or just a cut that happened to work?

Two checks. A **permutation test** shuffles the voter flag across trades and asks how often a gap
this large appears by chance; a **split-half** check asks whether the gap is there in both halves
of the sample or only one. A cut that only survives in one half is a story about that half.
""")

code(r"""
v = ann.dropna(subset=["is_voter"]).copy()
obs = v[v.is_voter].pnl_bp.mean() - v[~v.is_voter].pnl_bp.mean()

rng = np.random.default_rng(7)
flags = v.is_voter.to_numpy()
vals = v.pnl_bp.to_numpy()
perm = np.empty(5000)
for i in range(5000):
    f = rng.permutation(flags)
    perm[i] = vals[f].mean() - vals[~f].mean()
p = float((np.abs(perm) >= abs(obs)).mean())

print(f"voter minus non-voter, avg bp/trade : {obs:+.4f}")
print(f"two-sided permutation p-value       : {p:.4f}  ({'significant' if p < 0.05 else 'NOT significant'} at 5%)")

fig, axes = plt.subplots(1, 2, figsize=(15, 4))
axes[0].hist(perm, bins=60, color="lightgrey", edgecolor="k", lw=.3)
axes[0].axvline(obs, color="crimson", lw=2, label=f"observed {obs:+.3f}")
axes[0].set_title(f"voter-status permutation, p={p:.3f}"); axes[0].legend()

mid = len(v) // 2
rows = []
for name, sub in [("1st half", v.iloc[:mid]), ("2nd half", v.iloc[mid:])]:
    rows.append({"half": name,
                 "voter avg": sub[sub.is_voter].pnl_bp.mean(),
                 "non-voter avg": sub[~sub.is_voter].pnl_bp.mean(),
                 "gap": sub[sub.is_voter].pnl_bp.mean() - sub[~sub.is_voter].pnl_bp.mean(),
                 "n voter": int(sub.is_voter.sum()),
                 "n non": int((~sub.is_voter).sum())})
sh = pd.DataFrame(rows).set_index("half")
display(sh.round(4))
sh[["voter avg", "non-voter avg"]].plot(kind="bar", ax=axes[1], rot=0)
axes[1].axhline(0, color="k", lw=.6); axes[1].set_ylabel("avg bp / trade")
axes[1].set_title("does the split hold in both halves?")
plt.tight_layout(); plt.show()
""")

md(r"""
### 4.1b Removing the governor confound — the closest thing here to a natural experiment

Governors vote at every meeting, so "voters" and "governors" overlap heavily and the split above
could just be saying *governors matter more than presidents*.

The clean test restricts to **regional presidents only**. Same population, same kind of speaker,
same job — differing only by whether the published rotation happens to give them a vote in that
calendar year. The rotation is fixed years in advance and has nothing to do with what they say or
what the market does, which is what makes this close to a natural experiment rather than a cut.
""")

code(r"""
pres = ann[ann.role.isin(["President", "President (NY)"])].dropna(subset=["is_voter"])
a = pres[pres.is_voter].pnl_bp
b = pres[~pres.is_voter].pnl_bp
obs_p = a.mean() - b.mean()

rng = np.random.default_rng(11)
f = pres.is_voter.to_numpy(); x = pres.pnl_bp.to_numpy()
perm_p = np.empty(5000)
for i in range(5000):
    ff = rng.permutation(f)
    perm_p[i] = x[ff].mean() - x[~ff].mean()
pval = float((np.abs(perm_p) >= abs(obs_p)).mean())

display(pd.DataFrame([
    {"group": "regional president, VOTING this year", "trades": len(a),
     "total_bp": a.sum(), "avg_bp": a.mean(), "hit": (a > 0).mean()},
    {"group": "regional president, NOT voting", "trades": len(b),
     "total_bp": b.sum(), "avg_bp": b.mean(), "hit": (b > 0).mean()},
]).set_index("group").round(4))
print(f"gap {obs_p:+.4f} bp/trade   two-sided permutation p = {pval:.4f}")

# does it hold year by year, and in both halves?
rows = []
pres = pres.copy(); pres["year"] = pd.to_datetime(pres.opened_at).dt.year
for y, sub in pres.groupby("year"):
    aa, bb = sub[sub.is_voter].pnl_bp, sub[~sub.is_voter].pnl_bp
    rows.append({"year": y, "voting avg": aa.mean(), "n voting": len(aa),
                 "non-voting avg": bb.mean(), "n non": len(bb),
                 "gap": aa.mean() - bb.mean()})
display(pd.DataFrame(rows).set_index("year").round(4))

fig, axes = plt.subplots(1, 2, figsize=(15, 4.2))
axes[0].hist(perm_p, bins=60, color="lightgrey", edgecolor="k", lw=.3)
axes[0].axvline(obs_p, color="crimson", lw=2, label=f"observed {obs_p:+.3f}")
axes[0].set_title(f"presidents only — rotation permutation, p={pval:.4f}"); axes[0].legend()
for lab, sub in pres.groupby(pres.is_voter.map({True: "voting", False: "not voting"})):
    sub = sub.sort_values("opened_at")
    axes[1].plot(sub.opened_at.values, sub.pnl_bp.cumsum().values, lw=1.8, label=lab)
axes[1].axhline(0, color="k", lw=.6); axes[1].legend()
axes[1].set_title("cumulative bp, regional presidents only"); axes[1].set_ylabel("bp")
plt.tight_layout(); plt.show()

vb = ann.dropna(subset=["is_voter"])
vb = vb[vb.is_voter]
print(chr(10) + "A voters-only book, after a 0.25bp round-trip cost:")
print(f"  n={len(vb)}  gross {vb.pnl_bp.sum():+.1f}bp  net {vb.pnl_bp.sum() - .25*len(vb):+.1f}bp"
      f"  ({vb.pnl_bp.mean():+.4f} bp/trade gross)")
""")

md("### 4.2 Speaker attribution")

code(r"""
sp = (ann.groupby("speaker")
      .agg(trades=("pnl_bp", "size"), total_bp=("pnl_bp", "sum"),
           avg_bp=("pnl_bp", "mean"), hit=("profitable", "mean"),
           avg_score=("raw_score", "mean"))
      .sort_values("total_bp", ascending=False).round(4))
sp["role"] = [FX.role_of(s) for s in sp.index]
display(sp)

t = sp[sp.trades >= 6].sort_values("total_bp")
fig, ax = plt.subplots(figsize=(12, max(4, .34 * len(t))))
ax.barh(t.index, t.total_bp,
        color=["seagreen" if x > 0 else "indianred" for x in t.total_bp], alpha=.85)
ax.axvline(0, color="k", lw=.6); ax.set_xlabel("total bp per unit risk")
ax.set_title("speaker attribution (>= 6 trades)")
for i, (nm, r) in enumerate(t.iterrows()):
    ax.text(r.total_bp, i, f"  {int(r.trades)}t {r.hit:.0%}", va="center", fontsize=8)
plt.tight_layout(); plt.show()
""")

# ---------------------------------------------------------------------------
md(r"""
## 5. Where in the FOMC cycle

The meeting calendar is published years ahead, so distance-to-meeting is known at trade time.
Speeches inside the blackout are already excluded; what remains is whether a speech carries more
information early in the inter-meeting period, when the committee is genuinely re-forming its
view, than late, when the next decision is largely priced.
""")

code(r"""
print("by phase of the inter-meeting cycle:")
display(block(ann, "cycle_phase"))

ann["dtm_bucket"] = pd.cut(ann.days_to_fomc, bins=[-1, 7, 14, 21, 28, 99],
                           labels=["<=7d", "8-14d", "15-21d", "22-28d", "29d+"])
print("by days to the NEXT decision:")
display(block(ann, "dtm_bucket"))

fig, axes = plt.subplots(1, 2, figsize=(15, 4.5))
c = ann.groupby("cycle_phase", observed=False)["pnl_bp"].mean()
axes[0].bar(c.index.astype(str), c.values,
            color=["seagreen" if x > 0 else "indianred" for x in c.values], alpha=.85)
axes[0].axhline(0, color="k", lw=.6); axes[0].set_ylabel("avg bp / trade")
axes[0].set_title("days SINCE the last decision")

b = ann.groupby("dtm_bucket", observed=False)["pnl_bp"].mean()
axes[1].bar(b.index.astype(str), b.values,
            color=["seagreen" if x > 0 else "indianred" for x in b.values], alpha=.85)
axes[1].axhline(0, color="k", lw=.6); axes[1].set_title("days UNTIL the next decision")
plt.tight_layout(); plt.show()
""")

# ---------------------------------------------------------------------------
md(r"""
## 6. Does the signal scale with conviction?

The single most informative diagnostic in the whole study. A label that carries information should
earn **more** when it is more confident. If the strongest bucket is not the best bucket, the
"signal" is not ordered — which is very hard to reconcile with it being real.
""")

code(r"""
print("by signed bucket:")
display(block(ann, "bucket"))
print("by conviction |bucket|:")
display(block(ann, "abs_bucket"))
print("hawk vs dove:")
display(block(ann, "direction"))

b = ann.groupby("bucket")["pnl_bp"].mean()
fig, ax = plt.subplots(figsize=(9, 4.5))
ax.bar(b.index.astype(str), b.values,
       color=["#1a5276", "#5499c7", "#e59866", "#a93226"][:len(b)], alpha=.9)
ax.axhline(0, color="k", lw=.6)
ax.set_xlabel("signal bucket  (- dove / + hawk)"); ax.set_ylabel("avg bp / trade")
ax.set_title("signal response curve — a real signal slopes upward across the whole range")
plt.tight_layout(); plt.show()
""")

# ---------------------------------------------------------------------------
md("## 7. Calendar year, and the decay")

code(r"""
ann["year"] = pd.to_datetime(ann.opened_at).dt.year
yr = block(ann, "year")
display(yr)

fig, ax = plt.subplots(figsize=(10, 4.5))
ax.bar(yr.index.astype(str), yr.total_bp,
       color=["seagreen" if x > 0 else "indianred" for x in yr.total_bp], alpha=.85)
ax.axhline(0, color="k", lw=.6); ax.set_ylabel("total bp")
for i, (y, r) in enumerate(yr.iterrows()):
    ax.text(i, r.total_bp, f"n={int(r.trades)}", ha="center",
            va="bottom" if r.total_bp >= 0 else "top", fontsize=9)
ax.set_title("annual P&L")
plt.tight_layout(); plt.show()
""")

# ---------------------------------------------------------------------------
md("## 8. Robustness")

code(r"""
print("sign-flip permutation — the null is that the LABEL carried no direction:")
r = G.sign_flip_permutation(closed, n_perm=5000)
print(f"  realized Sharpe {r['realized_sharpe']:.3f}   null {r['perm_mean']:.3f}"
      f" +- {r['perm_std']:.3f}   p={r['p_value']:.4f}")

fig, axes = plt.subplots(1, 3, figsize=(18, 4))
axes[0].hist(r["perm"], bins=60, color="lightgrey", edgecolor="k", lw=.3)
axes[0].axvline(r["realized_sharpe"], color="crimson", lw=2)
axes[0].set_title(f"sign-flip permutation p={r['p_value']:.3f}")

mid = len(closed) // 2
rows = []
for name, sub in [("1st half", closed.iloc[:mid]), ("2nd half", closed.iloc[mid:])]:
    s = G.summarize(sub)
    rows.append({"half": name, "trades": s["trades"], "total_bp": s["total"],
                 "avg_bp": s["avg"], "hit": s["hit_rate"], "sharpe": s["sharpe"],
                 "range": f"{s['first'].date()} -> {s['last'].date()}"})
display(pd.DataFrame(rows).set_index("half").round(4))

costs = [0.0, 0.125, 0.25, 0.5, 1.0]
tot = [closed.pnl_bp.sum() - c * len(closed) for c in costs]
axes[1].plot(costs, tot, marker="o", color="darkslateblue")
axes[1].axhline(0, color="k", lw=.8)
axes[1].set_xlabel("round-trip cost (bp)"); axes[1].set_ylabel("total bp")
axes[1].set_title(f"cost sensitivity — break-even {closed.pnl_bp.mean():.3f}bp")

prov = closed.groupby("timestamp_source")["pnl_bp"].agg(["size", "sum", "mean"])
axes[2].bar(prov.index, prov["mean"],
            color=["steelblue", "grey"][:len(prov)], alpha=.85)
axes[2].axhline(0, color="k", lw=.6); axes[2].set_ylabel("avg bp / trade")
axes[2].set_title("real vs synthetic timestamps")
plt.tight_layout(); plt.show()
display(prov.round(4))
""")

md(r"""
### 8.1 Entry / exit window

Re-times every event, re-clamps it to the session and **re-gates** it, then re-prices. Re-gating
matters: a wider exit can walk past the last bar of the day, and an ungated re-run would mark it
against a lookahead bar instead of dropping it.

The baseline (−45, +180) is **inherited from the original Fed notebook, not chosen here** — but it
is also the argmax of this table, so treat the level with suspicion and read the *shape* instead.
""")

code(r"""
print(f"bar cache: {G.load_bar_cache(CACHE / 'bars.pkl')} symbol-days")
ENTRY_MIN = [-120, -60, -45, -15]
EXIT_MIN = [60, 120, 180, 240, 360]

variants = {f"{e}|{x}": (lambda bank, evs, _e=e, _x=x: G.rebuild_with_offsets(
    evs, cfg, datetime.timedelta(minutes=_e), datetime.timedelta(minutes=_x)))
    for e in ENTRY_MIN for x in EXIT_MIN}

sweep = G.sweep({BANK: events}, mdp, variants)
sweep[["entry", "exit"]] = sweep["variant"].str.split("|", expand=True).astype(int)

fig, axes = plt.subplots(1, 3, figsize=(19, 4.2))
for ax, (val, fmt, ttl) in zip(axes, [("sharpe", ".2f", "Sharpe"),
                                      ("avg", ".3f", "avg bp/trade"),
                                      ("trades", ".0f", "trades")]):
    sns.heatmap(sweep.pivot(index="entry", columns="exit", values=val).astype(float),
                annot=True, fmt=fmt, cmap="RdYlGn" if val != "trades" else "Blues",
                center=0 if val != "trades" else None, ax=ax)
    ax.set_title(ttl); ax.set_xlabel("exit offset (min)"); ax.set_ylabel("entry offset (min)")
plt.tight_layout(); plt.show()
display(sweep.sort_values("sharpe", ascending=False).head(8)[
    ["variant", "trades", "total", "avg", "hit_rate", "sharpe", "t_stat"]].round(4))
""")

# ---------------------------------------------------------------------------
md(r"""
## 9. The SOFR strip — a deflated instrument search

USD is the only leg where the strip stays liquid far enough out to search properly, so this goes
to the **8th quarterly contract** where the pooled study stopped at 6.

22+ structures — outrights, calendar spreads, butterflies and packs of four — times three causal
labelling schemes, times 16 entry/exit timings. Ranking that many configurations by Sharpe finds a
high Sharpe **whether or not any signal exists**, so the number that matters is the **Deflated
Sharpe Ratio**: given that we searched this hard, what is the probability the true Sharpe is above
zero? A configuration is interesting only at **DSR > 0.95**.
""")

code(r"""
usd = pd.read_csv(CACHE / "usd_grid_results.csv")
show = ["structure", "kind", "bucket_mode", "trades", "total_bp", "avg_bp",
        "hit", "sharpe_ann", "t_stat", "dsr"]
print(f"{len(usd)} causal configs, selection hurdle SR* = {usd.sr_star.iloc[0]:.4f} per trade")
display(usd.sort_values("sharpe_ann", ascending=False)[show].head(20).round(4))

fig, axes = plt.subplots(1, 3, figsize=(19, 4.5))
axes[0].hist(usd.sharpe_ann, bins=35, color="steelblue", alpha=.85, edgecolor="k", lw=.3)
axes[0].axvline(0, color="k", lw=.8); axes[0].set_xlabel("annualised Sharpe")
axes[0].set_title(f"Sharpe across {len(usd)} configurations")

axes[1].scatter(usd.sharpe_ann, usd.dsr, s=16, alpha=.65,
                c=np.where(usd.dsr > .95, "seagreen", "grey"))
axes[1].axhline(.95, color="crimson", ls="--", lw=1.2)
axes[1].set_xlabel("annualised Sharpe"); axes[1].set_ylabel("Deflated Sharpe")
axes[1].set_title("height, not width, is what counts")

o = usd[usd.kind == "outright"].copy()
o["rank"] = o.structure.str.split("_").str[1].astype(int)
piv = o.pivot_table(index="rank", columns="bucket_mode", values="sharpe_ann")
piv.plot(marker="o", ax=axes[2])
axes[2].axhline(0, color="k", lw=.8)
axes[2].set_xlabel("quarterly contract rank (1 = front)"); axes[2].set_ylabel("Sharpe")
axes[2].set_title("outright Sharpe along the SOFR strip")
plt.tight_layout(); plt.show()

alive = usd[(usd.dsr > .95) & (usd.trades >= 50)]
print(f"configs clearing DSR > 0.95 with >= 50 trades: {len(alive)} of {len(usd)}")
display(alive[show].round(4) if len(alive) else "NONE")

print(chr(10) + "by structure family:")
display(usd.groupby("kind")[["sharpe_ann", "avg_bp", "dsr"]]
        .agg({"sharpe_ann": ["count", "median", "max"], "avg_bp": "median",
              "dsr": "max"}).round(4))
print("by labelling scheme:")
display(usd.groupby("bucket_mode")[["sharpe_ann", "avg_bp", "trades", "dsr"]]
        .agg({"sharpe_ann": ["median", "max"], "avg_bp": "median",
              "trades": "median", "dsr": "max"}).round(4))
""")

# ---------------------------------------------------------------------------
md(r"""
### 9.1 What perfect knowledge of the committee would have been worth

The hand-researched standing table is not tradeable — it was written in 2026 about these very
trades. But scoring it answers a question worth knowing the answer to: **if you had known,
contemporaneously, exactly where each speaker sat on the committee, how much would that have been
worth?** That is the ceiling on the whole messenger-matters idea, and everything causal has to be
read against it.

`blended` takes the position only where the speech AND the speaker's standing agree — a known hawk
sounding hawkish, rather than any hawkish-sounding speech.
""")

code(r"""
rows = []
for name, fname, causal in [("peer", "events.pkl", True),
                            ("percentile", "events_percentile.pkl", True),
                            ("absolute", "events_absolute.pkl", True),
                            ("researched", "events_researched.pkl", False),
                            ("blended", "events_blended.pkl", False)]:
    path = CACHE / fname
    if not path.exists():
        continue
    with open(path, "rb") as f:
        ev = pickle.load(f)
    evs = (ev.get(BANK) or {}).get("events") or []
    if not evs:
        continue
    fb = G.fast_backtest(evs)
    if fb.empty:
        continue
    s = G.summarize(fb)
    rows.append({"scheme": name, "tradeable": causal, "trades": s["trades"],
                 "total_bp": s["total"], "avg_bp": s["avg"], "hit": s["hit_rate"],
                 "sharpe": s["sharpe"], "t_stat": s["t_stat"],
                 "hawk_share": float((fb.bucket > 0).mean())})
lab = pd.DataFrame(rows).set_index("scheme")
display(lab.round(4))

fig, axes = plt.subplots(1, 2, figsize=(15, 4.5))
c = ["seagreen" if t else "indianred" for t in lab.tradeable]
axes[0].bar(lab.index, lab.avg_bp, color=c, alpha=.85)
axes[0].axhline(0, color="k", lw=.6); axes[0].set_ylabel("avg bp / trade")
axes[0].set_title("green = tradeable, red = hindsight (upper bound only)")
axes[1].bar(lab.index, lab.hawk_share, color="steelblue", alpha=.85)
axes[1].axhline(.5, color="k", ls="--", lw=.8)
axes[1].set_ylabel("share of trades labelled hawk")
axes[1].set_title("hawk share — absolute cutoffs put the book on one side")
for ax in axes:
    ax.tick_params(axis="x", rotation=20)
plt.tight_layout(); plt.show()

print("An adversarial audit measured an ORACLE version of this table at t=5.8 (one period per")
print("speaker) and t=10.5 (speaker x year), while making its estimation window causal collapsed")
print("it to t=0.9. Read the two red bars as a ceiling, not a strategy.")
""")

md(r"""
## 10. Verdict

Read in this order.

1. **Did anything clear DSR > 0.95?** If not, the best Sharpe in the grid is what searching this
   many times produces from noise, and there is no instrument choice that rescues it.
2. **Does it clear costs?** Break-even is `avg_bp`; a listed SR3 outright is roughly a
   quarter-tick round trip.
3. **Is the response ordered in conviction?** If the strongest bucket is not the best bucket, the
   label is not measuring what it claims to.
4. **Is the voter split real?** This is the one conditioning variable here that is economically
   motivated rather than searched, so it is the finding most likely to survive contact with
   another sample.
5. **Does the edge persist?** Check the annual table and the second half.
""")

code(r"""
real = closed[closed.timestamp_source == "forexfactory"]
v = ann.dropna(subset=["is_voter"])
summary = {
    "trades": int(len(closed)),
    "total_bp": round(float(closed.pnl_bp.sum()), 2),
    "avg_bp_per_trade": round(float(closed.pnl_bp.mean()), 4),
    "hit_rate": round(float(closed.profitable.mean()), 4),
    "sharpe": round(float(G.summarize(closed)["sharpe"]), 3),
    "t_stat": round(float(G.summarize(closed)["t_stat"]), 3),
    "sign_flip_p": round(float(r["p_value"]), 4),
    "break_even_rt_cost_bp": round(float(closed.pnl_bp.mean()), 4),
    "total_at_0.25bp_cost": round(float(closed.pnl_bp.sum() - .25 * len(closed)), 1),
    "real_timestamp_avg_bp": round(float(real.pnl_bp.mean()), 4),
    "voter_minus_nonvoter_bp": round(float(
        v[v.is_voter].pnl_bp.mean() - v[~v.is_voter].pnl_bp.mean()), 4),
    "grid_configs": int(len(usd)),
    "grid_best_sharpe": round(float(usd.sharpe_ann.max()), 3),
    "grid_best_dsr": round(float(usd.dsr.max()), 3),
    "grid_alive_dsr_gt_95": int(((usd.dsr > .95) & (usd.trades >= 50)).sum()),
}
for k, val in summary.items():
    print(f"  {k:26s} {val}")

pd.Series(summary).to_frame("value").to_csv(CACHE / "usd_fomc_summary.csv")
print(chr(10) + f"wrote {CACHE / 'usd_fomc_summary.csv'}")
""")

md("## 11. Trade log")

code(r"""
log = ann[["opened_at", "closed_at", "speaker", "role", "district", "is_voter",
           "symbol", "direction", "bucket", "raw_score", "days_to_fomc",
           "timestamp_source", "pnl_bp"]].copy()
log["cum_bp"] = log.pnl_bp.cumsum()
display(log.style.format({"raw_score": "{:.1f}", "pnl_bp": "{:+.3f}",
                          "cum_bp": "{:+.2f}"})
        .bar(subset=["pnl_bp"], color=["#d65f5f", "#5fba7d"], align="zero"))
log.to_csv(CACHE / "usd_fomc_trade_log.csv", index=False)
print(f"wrote {CACHE / 'usd_fomc_trade_log.csv'}")
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
