"""Generate econ_release_fade_paramsearch.ipynb -- what ARE the best parameters."""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "econ_release_fade_paramsearch.ipynb"
REPO = str(HERE.parent.parent.parent)
cells: list = []


def _lines(src): return src.strip("\n").splitlines(keepends=True)
def md(src): cells.append({"cell_type": "markdown", "id": f"md{len(cells):02d}", "metadata": {}, "source": _lines(src)})
def code(src): cells.append({"cell_type": "code", "id": f"cd{len(cells):02d}", "execution_count": None, "metadata": {}, "outputs": [], "source": _lines(src)})


md(r"""
# Fade the release — what are the best parameters?

Which instrument, which offsets, which releases are worth trading and which should be ignored. This
notebook searches for them and then tells you what the answer is worth, because those are two
different questions and only the second one is hard.

### A grid returns an order statistic, so it needs a yardstick

Run five thousand configurations on pure noise and the best one will look excellent. So "is the best
cell good?" cannot be answered against zero. It is answered against **the same search run on days
with no release at all** — every instrument, every offset, every release set, every direction,
shifted one business day onto a minute where nothing printed.

If the best real cell does not beat the best placebo cell, the search found the shape of a search,
not an edge. That comparison is §8 and it is the only number in this notebook that decides anything.

### Both directions are searched

The strategy is called a fade, but the honest question is whether there is a tradeable edge in
*either* direction. Searching only the fade would look at half the answer, so `direction` is an axis:
`fade` takes the opposite side of the initial move, `momentum` takes the same side. In the closed
form they are exact mirrors, so this doubles `N` and the family correction is charged for it — which
is correct, because trying both really is two tries.

### Three ways to be wrong about "which releases to ignore"

Picking the releases that worked is the easiest overfit in this notebook, so §2.1 does not pick them
and stop. It picks them on the **first half** of the sample and then trades that selection on the
**second half**, against two controls: trading everything, and trading a random selection of the
same size. A rule you could not have followed in 2019 is not a rule.

---

> **What is already known before this notebook starts.** The fade loses on real releases and the
> wrong-day placebo wins; momentum is the exact mirror of the fade; and across 1,022 grid cells the
> selection-bias adjusted p-value for the best was 0.9995 with Romano-Wolf rejecting nothing. This
> notebook widens the search rather than repeating it. If the widening finds something, that is
> news; if it does not, the size of the search it took to not find it is itself the result.
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
from RVUtils.StatisticalFinance import (
    ras_bound, romano_wolf, selection_bias_pvalue, shared_sign_flip_null, topk_upper_bound,
)

RAW = load_events()
n_bars = G.load_bar_cache()
n_dv01 = G.load_dv01()
RAW_PLACEBO = C.placebo_shift(RAW, days=1)      # business day, real release minutes removed

TICK = 0.5          # the measured SR3 outright tick, in bp of rate
print(f"release book {{len(RAW):,}} minutes   placebo {{len(RAW_PLACEBO):,}}   "
      f"bars {{n_bars:,}} symbol-days   DV01 {{n_dv01}} contracts")
""")

# ---------------------------------------------------------------- search space
md(r"""
## 1. The search space, declared before anything is run

Written down first so the count is not decided by what turns up. Everything below is scored against
this `N`, including the direction axis and the per-release panel.
""")

code(r"""
INSTRUMENTS = (
    [(f"SR3 r{n}", {"family": "stir", "root": "USD_STIR", "rank": n}) for n in (1, 2, 3, 4, 6, 8)] +
    [(f"ZQ r{n}", {"family": "stir", "root": "ZQ", "rank": n}) for n in (1, 2)] +
    [(k, {"family": "ust", "root": k, "rank": 1}) for k in ("TU", "FV", "TY", "US")]
)

#: Release families. Individual titles are grouped by ECONOMIC family rather than
#: taken one at a time, because they co-print: CPI m/m, CPI y/y and Core CPI m/m
#: are one minute and one price move, so three separate rows would be three
#: copies of the same trade. Anchored patterns throughout -- an unanchored
#: "Non-Farm Employment Change" also matches "ADP Non-Farm Employment Change".
RELEASE_FAMILIES = [
    ("CPI",            {"titles_include": [r"\bCPI\b"]}),
    ("PPI",            {"titles_include": [r"\bPPI\b"]}),
    ("PCE",            {"titles_include": [r"PCE"]}),
    ("payrolls",       {"titles_include": [r"^Non-Farm Employment Change$", r"^Unemployment Rate$",
                                           r"^Average Hourly Earnings m/m$"]}),
    ("ADP",            {"titles_include": [r"^ADP Non-Farm Employment Change$"]}),
    ("jobless claims", {"titles_include": [r"^Unemployment Claims$"]}),
    ("JOLTS",          {"titles_include": [r"^JOLTS Job Openings$"]}),
    ("retail sales",   {"titles_include": [r"Retail Sales"]}),
    ("ISM mfg",        {"titles_include": [r"^ISM Manufacturing "]}),
    ("ISM services",   {"titles_include": [r"^ISM Services PMI$"]}),
    ("flash PMI",      {"titles_include": [r"^Flash (Manufacturing|Services) PMI$"]}),
    ("Chicago PMI",    {"titles_include": [r"^Chicago PMI$"]}),
    ("Philly Fed",     {"titles_include": [r"^Philly Fed Manufacturing Index$"]}),
    ("Empire State",   {"titles_include": [r"^Empire State Manufacturing Index$"]}),
    ("Richmond",       {"titles_include": [r"^Richmond Manufacturing Index$"]}),
    ("durable goods",  {"titles_include": [r"Durable Goods Orders"]}),
    ("UoM sentiment",  {"titles_include": [r"UoM Consumer Sentiment"]}),
    ("UoM inflation",  {"titles_include": [r"UoM Inflation Expectations"]}),
    ("CB confidence",  {"titles_include": [r"^CB Consumer Confidence$"]}),
    ("housing",        {"titles_include": [r"Home Sales", r"Building Permits", r"Housing Starts"]}),
    ("GDP",            {"titles_include": [r"GDP"]}),
    # A deliberate NEGATIVE control: a weekly energy print in the same tier-1/2
    # book that has no direct business moving the front end of the SOFR strip.
    # If fading it scores like fading CPI, the score is not about the news.
    ("crude inventories", {"titles_include": [r"^Crude Oil Inventories$"]}),
]

RELEASE_AGGREGATES = [
    ("tier1",       {"impacts": ["high"]}),
    ("tier1+2",     {"impacts": ["high", "medium"]}),
    ("tier2 only",  {"impacts": ["medium"]}),
    ("08:30 block", {"release_times_ny": ["08:30"]}),
    ("10:00 block", {"release_times_ny": ["10:00"]}),
    ("clustered",   {"min_events_in_minute": 2}),
]

BASE_EVENTS = {"impacts": ["high", "medium"]}
ALL_RELEASE_SETS = ([(n, {**BASE_EVENTS, **o}) for n, o in RELEASE_AGGREGATES] +
                    [(n, {**BASE_EVENTS, **o}) for n, o in RELEASE_FAMILIES])

#: The release sets that enter the FULL product. Chosen by trade count, before
#: any P&L is looked at -- picking them by edge would make the product adaptive
#: and the family correction invalid.
PRODUCT_SETS = ["tier1", "tier1+2", "08:30 block", "clustered",
                "CPI", "payrolls", "jobless claims", "ISM mfg", "retail sales", "PCE"]

MEASURE = [1, 5]
HOLD = [15, 30, 60, 120, 240]
DIRECTIONS = ["fade", "momentum"]
MOVE_PANEL = [0.0, 1.0, 2.0, 3.0]

def cfg_of(name, ispec, espec, m, h, direction, move=0.0):
    return C.spec(name, instrument=ispec, events=espec,
                  timing={"measure_end_min": m, "entry_offset_min": m + 1, "exit_offset_min": h},
                  signal={"direction": direction, "min_move_bp": move})

SETS = dict(ALL_RELEASE_SETS)

# --- the three panels, all pre-declared -------------------------------------
PANEL_RELEASE = [cfg_of(f"rel|{rn}|{inm}|{d}", isp, SETS[rn], 1, 60, d)
                 for rn, _ in ALL_RELEASE_SETS
                 for inm, isp in [i for i in INSTRUMENTS if i[0] in ("SR3 r3", "TY")]
                 for d in DIRECTIONS]

PANEL_PRODUCT = [cfg_of(f"grid|{inm}|{rn}|m{m}|h{h}|{d}", isp, SETS[rn], m, h, d)
                 for inm, isp in INSTRUMENTS for rn in PRODUCT_SETS
                 for m in MEASURE for h in HOLD for d in DIRECTIONS if h > m + 1]

PANEL_MOVE = [cfg_of(f"move|{inm}|{mv:g}|{d}", isp, SETS["tier1+2"], 1, 60, d, move=mv)
              for inm, isp in INSTRUMENTS for mv in MOVE_PANEL for d in DIRECTIONS]

ALL_CFGS = PANEL_RELEASE + PANEL_PRODUCT + PANEL_MOVE
N_SEARCHED = len(ALL_CFGS)
print(f"per-release panel : {len(PANEL_RELEASE):>5,}")
print(f"full product      : {len(PANEL_PRODUCT):>5,}   "
      f"({len(INSTRUMENTS)} instruments x {len(PRODUCT_SETS)} release sets x "
      f"{len(MEASURE)} measure x {len(HOLD)} hold x {len(DIRECTIONS)} directions)")
print(f"move-filter panel : {len(PANEL_MOVE):>5,}")
print(f"TOTAL SEARCHED    : {N_SEARCHED:>5,}   and the same again on the placebo book")
""")

code(r"""
PARAM_CSV = G.CACHE / "paramsearch_real.csv"
PARAM_CSV_P = G.CACHE / "paramsearch_placebo.csv"

def run_panel(cfgs, raw, label, csv_path, resume=True):
    '''Score every configuration, keeping the per-trade series for the family tests.'''
    done = {}
    if resume and Path(csv_path).exists():
        prev = pd.read_csv(csv_path)
        done = {r["config"]: r for _, r in prev.iterrows()}
        print(f"resuming {label}: {len(done):,} already scored")

    rows, series = [], {}
    todo = [c for c in cfgs if c["name"] not in done]
    try:
        from tqdm.auto import tqdm
        it = tqdm(todo, desc=label)
    except Exception:
        it = todo

    t0, n_err, errs = time.time(), 0, {}
    for cfg in it:
        try:
            r = C.run_config(cfg, raw, engine=False)
        except Exception as ex:
            n_err += 1
            k = f"{type(ex).__name__}: {str(ex)[:80]}"
            errs[k] = errs.get(k, 0) + 1
            continue
        s = r.stats
        rows.append({"config": cfg["name"], "panel": cfg["name"].split("|")[0],
                     "trades": s.get("trades", 0), "total_bp": s.get("total_bp", np.nan),
                     "avg_bp": s.get("avg_bp", np.nan), "hit_rate": s.get("hit_rate", np.nan),
                     "sr_per_trade": s.get("sr_per_trade", np.nan),
                     "t_stat": s.get("t_stat", np.nan), "max_dd_bp": s.get("max_dd_bp", np.nan),
                     "span_days": s.get("span_days", np.nan),
                     "trades_per_year": s.get("trades_per_year", np.nan)})
        if not r.closed.empty:
            series[cfg["name"]] = r.closed.set_index("release_ts")["pnl_bp_gross"]

    new = pd.DataFrame(rows)
    out = pd.concat([pd.DataFrame(list(done.values())), new], ignore_index=True) if done else new
    out.to_csv(csv_path, index=False)
    print(f"{label}: {len(out):,} scored in {time.time()-t0:.0f}s -> {csv_path}")
    if n_err:
        print(f"  {n_err:,} could not be priced and are ABSENT:")
        for k, v in sorted(errs.items(), key=lambda x: -x[1]):
            print(f"    {v:>5}x {k}")
    return out, series

REAL, SER = run_panel(ALL_CFGS, RAW, "real", PARAM_CSV)
PLAC, SER_P = run_panel(ALL_CFGS, RAW_PLACEBO, "placebo", PARAM_CSV_P)
REAL = REAL.set_index("config"); PLAC = PLAC.set_index("config")
""")

# ---------------------------------------------------------------- per release
md(r"""
## 2. What is the edge fading each release?

The direct answer. Every release family, both directions, on the 3rd SOFR quarterly and the 10-year
note future, measured T−1 → T, entered T+2, held an hour.

Two columns decide whether a row means anything. **`trades`** — a family with 30 trades is a story.
And **`avg_bp` against the 0.5 bp tick** — an edge below the tick is a cost, not an opportunity, no
matter what the t-statistic says.

`crude inventories` is in the table as a negative control. It is a weekly energy print sitting in
the same tier-1/2 book with no direct business moving the front end of the SOFR strip; if fading it
scores like fading CPI then the score is not measuring news.
""")

code(r"""
rel = REAL[REAL.panel == "rel"].copy()
parts = rel.index.to_series().str.split("|", expand=True)
rel["release"] = parts[1].values; rel["instrument"] = parts[2].values
rel["direction"] = parts[3].values

for inst in ("SR3 r3", "TY"):
    sub = rel[(rel.instrument == inst) & (rel.direction == "fade")]
    sub = sub.sort_values("avg_bp", ascending=False)
    print(f"\n=== FADING each release on {inst} (T-1 -> T measured, T+2 entry, 60 min hold) ===")
    display(sub[["release", "trades", "avg_bp", "total_bp", "hit_rate", "sr_per_trade", "t_stat"]]
            .set_index("release").round(4))

sub = rel[(rel.instrument == "SR3 r3") & (rel.direction == "fade")].sort_values("avg_bp")
sub = sub[sub.trades >= 20]
fig, axes = plt.subplots(1, 2, figsize=(18, max(5, .32 * len(sub))))
colors = ["darkorange" if r == "crude inventories" else ("seagreen" if v > 0 else "indianred")
          for r, v in zip(sub.release, sub.avg_bp)]
axes[0].barh(sub.release, sub.avg_bp, color=colors, alpha=.88)
for i, (_, r) in enumerate(sub.iterrows()):
    axes[0].text(r.avg_bp, i, f"  {int(r.trades)}t", va="center", fontsize=8)
axes[0].axvline(0, color="k", lw=.8)
axes[0].axvline(TICK, color="crimson", ls=":", lw=1.8, label=f"SR3 tick {TICK}bp")
axes[0].axvline(-TICK, color="crimson", ls=":", lw=1.8)
axes[0].legend(fontsize=8); axes[0].set_xlabel("gross bp / trade, FADING")
axes[0].set_title("edge by release family, SR3 rank 3 (orange = negative control)")

both = rel[rel.instrument == "SR3 r3"].pivot_table(index="release", columns="direction",
                                                   values="avg_bp")
both = both.reindex(sub.release)
axes[1].scatter(both["fade"], both["momentum"], s=40, alpha=.8, color="darkslateblue")
for nm, r in both.iterrows():
    axes[1].annotate(nm, (r["fade"], r["momentum"]), fontsize=7, alpha=.75)
lim = [both.min().min(), both.max().max()]
axes[1].plot(lim, [-v for v in lim], color="crimson", lw=1.4, ls="--", label="y = -x")
axes[1].axhline(0, color="k", lw=.6); axes[1].axvline(0, color="k", lw=.6)
axes[1].set_xlabel("fade bp/trade"); axes[1].set_ylabel("momentum bp/trade"); axes[1].legend(fontsize=8)
axes[1].set_title("the two directions are exact mirrors, as they must be")
plt.tight_layout(); plt.show()
""")

md(r"""
### 2.1 "Ignore the bad releases" — a rule, or hindsight?

Picking the releases that worked and reporting their combined P&L is the easiest overfit available
here, and it always produces a good-looking number. So the selection is made on the **first half**
of the sample and traded on the **second half**, against two controls.

The random control is the one that matters. Selecting the best *k* of 28 families on half a sample
gives a number even when every family is identical noise, so the question is not "does the selection
beat trading everything" but "does it beat picking *k* at random".
""")

code(r"""
REL_BOOKS = {}
for rn, espec in ALL_RELEASE_SETS:
    nm = f"rel|{rn}|SR3 r3|fade"
    if nm in SER and len(SER[nm]) >= 20:
        REL_BOOKS[rn] = SER[nm]

allts = pd.concat(REL_BOOKS.values()).sort_index()
split = allts.index[len(allts) // 2]
print(f"{len(REL_BOOKS)} release families with >= 20 trades   split at {split.date()}")

first = {k: v[v.index <= split] for k, v in REL_BOOKS.items()}
second = {k: v[v.index > split] for k, v in REL_BOOKS.items()}

# Only families with enough trades in BOTH halves can enter: a family that
# vanishes after the split would be "selected" on the first half and then score
# nothing on the second, which reads as a failed selection rather than as an
# absent instrument.
usable = [k for k in REL_BOOKS if len(first[k]) >= 10 and len(second[k]) >= 10]
rank1 = pd.Series({k: first[k].mean() for k in usable}).sort_values(ascending=False)
print(f"{len(usable)} families have >= 10 trades in both halves")
rng = np.random.default_rng(20260811)
rows = []
for k in (3, 5, 8, 12):
    chosen = list(rank1.index[:k])
    oos = pd.concat([second[c] for c in chosen if len(second[c])])
    rand = []
    for _ in range(400):
        pick = rng.choice(list(rank1.index), size=k, replace=False)
        r_ = pd.concat([second[c] for c in pick if len(second[c])])
        rand.append(r_.mean())
    rand = np.array(rand)
    rows.append({"k": k, "in-sample avg_bp": rank1.iloc[:k].mean(),
                 "OOS trades": len(oos), "OOS avg_bp": oos.mean(),
                 "random pick mean": rand.mean(), "random pick p95": np.quantile(rand, .95),
                 "beats random": float((rand < oos.mean()).mean())})
sel = pd.DataFrame(rows).set_index("k")
everything = pd.concat(list(second.values()))
print(f"\ntrading EVERYTHING out of sample: {len(everything)} trades, "
      f"{everything.mean():+.4f} bp/trade")
display(sel.round(4))
print("'beats random' is the fraction of random k-subsets the selection beat out of sample.")
print("Near 0.5 means the selection carried no information the coin toss did not.")

fig, axes = plt.subplots(1, 2, figsize=(16, 4.4))
axes[0].scatter([first[k].mean() for k in rank1.index],
                [second[k].mean() if len(second[k]) else np.nan for k in rank1.index],
                s=45, alpha=.8, color="darkslateblue")
for k in rank1.index:
    axes[0].annotate(k, (first[k].mean(), second[k].mean() if len(second[k]) else 0),
                     fontsize=7, alpha=.75)
axes[0].axhline(0, color="k", lw=.6); axes[0].axvline(0, color="k", lw=.6)
lo = min(axes[0].get_xlim()[0], axes[0].get_ylim()[0]); hi = max(axes[0].get_xlim()[1], axes[0].get_ylim()[1])
axes[0].plot([lo, hi], [lo, hi], color="crimson", ls="--", lw=1.3, label="persistence would sit here")
axes[0].set_xlabel("1st half bp/trade"); axes[0].set_ylabel("2nd half bp/trade"); axes[0].legend(fontsize=8)
r_ = np.corrcoef([first[k].mean() for k in rank1.index],
                 [second[k].mean() for k in rank1.index])[0, 1]
axes[0].set_title(f"does a release's edge persist? r = {r_:+.3f}")
axes[1].bar(sel.index.astype(str), sel["OOS avg_bp"], color="darkslateblue", alpha=.85,
            label="selected top-k")
axes[1].plot(range(len(sel)), sel["random pick mean"], "o--", color="grey", label="random k")
axes[1].axhline(everything.mean(), color="seagreen", lw=1.6, ls=":", label="trade everything")
axes[1].axhline(0, color="k", lw=.7); axes[1].set_xlabel("k releases kept")
axes[1].set_ylabel("out-of-sample bp/trade"); axes[1].legend(fontsize=8)
axes[1].set_title("selecting on the 1st half, trading the 2nd")
plt.tight_layout(); plt.show()
""")

# ---------------------------------------------------------------- instrument
md(r"""
## 3. The best instrument

The marginal over the whole product: for each instrument, the distribution of edge across every
release set, offset and direction it was tried with. The median is the honest summary — the maximum
is what a search finds by looking.
""")

code(r"""
prod = REAL[REAL.panel == "grid"].copy()
p = prod.index.to_series().str.split("|", expand=True)
prod["instrument"] = p[1].values; prod["release"] = p[2].values
prod["measure"] = p[3].str[1:].astype(int).values
prod["hold"] = p[4].str[1:].astype(int).values
prod["direction"] = p[5].values
prod = prod[prod.trades >= 50]
print(f"{len(prod):,} product cells with >= 50 trades")

by_inst = prod.groupby(["instrument", "direction"]).agg(
    cells=("avg_bp", "size"), median_bp=("avg_bp", "median"), best_bp=("avg_bp", "max"),
    median_sr=("sr_per_trade", "median"), best_sr=("sr_per_trade", "max"),
    median_trades=("trades", "median")).round(4)
display(by_inst)

fig, axes = plt.subplots(1, 3, figsize=(20, 4.6))
order = [i[0] for i in INSTRUMENTS]
for d, col in [("fade", "steelblue"), ("momentum", "darkorange")]:
    sub = prod[prod.direction == d].groupby("instrument").avg_bp.median().reindex(order)
    axes[0].plot(range(len(order)), sub.values, "o-", color=col, label=d, lw=2)
axes[0].axhline(0, color="k", lw=.7)
axes[0].axhline(TICK, color="crimson", ls=":", lw=1.6, label=f"tick {TICK}bp")
axes[0].set_xticks(range(len(order))); axes[0].set_xticklabels(order, rotation=60, fontsize=8)
axes[0].set_ylabel("median gross bp / trade"); axes[0].legend(fontsize=8)
axes[0].set_title("median edge by instrument")

sns.boxplot(data=prod[prod.direction == "fade"], x="instrument", y="avg_bp", order=order,
            ax=axes[1], color="steelblue", fliersize=1)
axes[1].axhline(0, color="k", lw=.7); axes[1].tick_params(axis="x", rotation=60)
axes[1].set_title("spread of FADE edge across every cell")

piv = prod[prod.direction == "fade"].pivot_table(index="instrument", columns="release",
                                                 values="avg_bp", aggfunc="median").reindex(order)
sns.heatmap(piv, annot=True, fmt=".2f", cmap="RdYlGn", center=0, ax=axes[2],
            cbar_kws={"label": "median bp/trade"})
axes[2].set_title("instrument x release set, fading")
plt.tight_layout(); plt.show()
""")

# ---------------------------------------------------------------- offsets
md(r"""
## 4. The best timestamp offsets

`measure` is how many minutes of the burst the signal is allowed to see; entry is always one minute
after that, so a longer look is paid for with a later fill and nothing here trades at the price it
read its signal from. `hold` is how long the position is given.
""")

code(r"""
for d in DIRECTIONS:
    sub = prod[prod.direction == d]
    g_bp = sub.pivot_table(index="measure", columns="hold", values="avg_bp", aggfunc="median")
    g_sr = sub.pivot_table(index="measure", columns="hold", values="sr_per_trade", aggfunc="median")
    g_n = sub.pivot_table(index="measure", columns="hold", values="trades", aggfunc="median")
    fig, axes = plt.subplots(1, 3, figsize=(20, 3.6))
    sns.heatmap(g_bp, annot=True, fmt=".3f", cmap="RdYlGn", center=0, ax=axes[0],
                cbar_kws={"label": "bp/trade"})
    axes[0].set_title(f"{d}: median gross bp per trade")
    sns.heatmap(g_sr, annot=True, fmt=".3f", cmap="RdYlGn", center=0, ax=axes[1],
                cbar_kws={"label": "Sharpe/trade"})
    axes[1].set_title(f"{d}: median Sharpe per trade")
    sns.heatmap(g_n, annot=True, fmt=".0f", cmap="Blues", ax=axes[2], cbar_kws={"label": "trades"})
    axes[2].set_title(f"{d}: median trade count")
    for ax in axes:
        ax.set_xlabel("hold (min)"); ax.set_ylabel("measure (min)")
    plt.tight_layout(); plt.show()

best_off = (prod.groupby(["direction", "measure", "hold"])
              .agg(cells=("avg_bp", "size"), median_bp=("avg_bp", "median"),
                   median_sr=("sr_per_trade", "median"))
              .sort_values("median_sr", ascending=False).round(4))
display(best_off.head(10))
""")

# ---------------------------------------------------------------- move filter
md(r"""
## 5. The move filter — is it worth skipping the small prints?

A release that moved the strip a quarter of a tick has told you almost nothing, and trading it pays
a full round trip anyway. `min_move_bp` skips those. If the edge is liquidity, filtering to the
larger bursts should concentrate it; if it is information, it should make things worse.
""")

code(r"""
mv = REAL[REAL.panel == "move"].copy()
q = mv.index.to_series().str.split("|", expand=True)
mv["instrument"] = q[1].values; mv["move"] = q[2].astype(float).values; mv["direction"] = q[3].values
mv = mv[mv.trades >= 30]
tbl = (mv.groupby(["direction", "move"])
         .agg(cells=("avg_bp", "size"), median_trades=("trades", "median"),
              median_bp=("avg_bp", "median"), best_bp=("avg_bp", "max"),
              median_sr=("sr_per_trade", "median")).round(4))
display(tbl)

fig, axes = plt.subplots(1, 2, figsize=(16, 4.2))
for d, col in [("fade", "steelblue"), ("momentum", "darkorange")]:
    s = mv[mv.direction == d].groupby("move").avg_bp.median()
    axes[0].plot(s.index, s.values, "o-", lw=2, color=col, label=d)
axes[0].axhline(0, color="k", lw=.7); axes[0].axhline(TICK, color="crimson", ls=":", lw=1.6,
                                                      label=f"tick {TICK}bp")
axes[0].set_xlabel("min |initial move| (bp)"); axes[0].set_ylabel("median gross bp / trade")
axes[0].legend(fontsize=8); axes[0].set_title("does filtering to bigger bursts help?")
s = mv[mv.direction == "fade"].groupby("move").trades.median()
axes[1].bar(s.index.astype(str), s.values, color="darkslateblue", alpha=.85)
axes[1].set_xlabel("min |initial move| (bp)"); axes[1].set_ylabel("median trades")
axes[1].set_title("what the filter costs in sample size")
plt.tight_layout(); plt.show()
""")

# ---------------------------------------------------------------- leaderboard
md(r"""
## 6. The leaderboard

The best cells of the whole search, ranked on Sharpe per trade — the same statistic §7's corrections
score, so the winner is not chosen on one number and judged on another.

Read `trades` and `avg_bp` before `sr_per_trade`. A cell with 51 trades at the top of a five-thousand
cell search is the definition of an order statistic.
""")

code(r"""
elig = REAL[(REAL.trades >= 50) & REAL.sr_per_trade.notna()].copy()
elig["clears_tick"] = elig.avg_bp > TICK
print(f"{len(elig):,} of {len(REAL):,} configurations have >= 50 trades")
print(f"positive gross edge : {int((elig.avg_bp > 0).sum()):,}")
print(f"gross edge > one tick: {int(elig.clears_tick.sum()):,}")

top = elig.sort_values("sr_per_trade", ascending=False).head(30)
display(top[["panel", "trades", "span_days", "avg_bp", "hit_rate", "sr_per_trade",
             "t_stat", "max_dd_bp"]].round(4))

fig, axes = plt.subplots(1, 3, figsize=(20, 4.4))
axes[0].hist(elig.sr_per_trade, bins=70, color="steelblue", edgecolor="k", lw=.3)
axes[0].axvline(0, color="k", lw=.8)
axes[0].axvline(elig.sr_per_trade.max(), color="crimson", lw=2,
                label=f"best {elig.sr_per_trade.max():.3f}")
axes[0].set_xlabel("Sharpe per trade"); axes[0].legend(fontsize=8)
axes[0].set_title(f"{len(elig):,} configurations")
axes[1].hist(elig.avg_bp, bins=70, color="darkslateblue", edgecolor="k", lw=.3)
axes[1].axvline(0, color="k", lw=.8)
axes[1].axvline(TICK, color="crimson", lw=2, ls="--", label=f"tick {TICK}bp")
axes[1].set_xlabel("gross bp / trade"); axes[1].legend(fontsize=8)
axes[1].set_title("edge against the tick it has to clear")
sc = axes[2].scatter(elig.trades, elig.avg_bp, c=elig.sr_per_trade, cmap="RdYlGn",
                     s=12, alpha=.7, vmin=-0.3, vmax=0.3)
axes[2].axhline(0, color="k", lw=.7); axes[2].axhline(TICK, color="crimson", ls="--", lw=1.4)
axes[2].set_xscale("log"); axes[2].set_xlabel("trades (log)"); axes[2].set_ylabel("gross bp / trade")
axes[2].set_title("big numbers live in the small-sample corner")
plt.colorbar(sc, ax=axes[2], label="Sharpe per trade")
plt.tight_layout(); plt.show()
""")

# ---------------------------------------------------------------- correction
md(r"""
## 7. What the search cost

`RVUtils.StatisticalFinance`, on the whole family at once. The null is a **shared** Rademacher sign
flip aligned on the release timestamp: configurations that traded the same prints the same way flip
together, so the family maximum keeps the real correlation of the grid instead of pretending
thousands of near-duplicates were independent experiments.
""")

code(r"""
X = pd.DataFrame({nm: SER[nm] for nm in elig.index if nm in SER}).sort_index()
print(f"family matrix: {X.shape[1]:,} configurations x {X.shape[0]:,} release timestamps")

obs = np.array([X[c].dropna().mean() / X[c].dropna().std(ddof=1)
                if X[c].notna().sum() > 1 else 0.0 for c in X.columns])
NULL = shared_sign_flip_null(X, draws=2000, rng=np.random.default_rng(20260811))

p_best = selection_bias_pvalue(obs, NULL)
RW = romano_wolf(obs, NULL, alpha=0.05, names=list(X.columns))
RAS = ras_bound(X.fillna(0.0), delta=0.05, draws=2000, rng=np.random.default_rng(99),
                names=list(X.columns))

print(f"\nselection-bias adjusted p for the BEST configuration: {p_best:.4f}")
print(f"Romano-Wolf rejects {RW.n_rejected:,} of {RW.n_strategies:,} at a 5% familywise level")
print(f"Rademacher positive: {int((RAS.bound > 0).sum()):,} of {RAS.N:,}")
display(RW.table.head(15).round(4))
display(RAS.terms().to_frame("value").round(5))

fig, axes = plt.subplots(1, 3, figsize=(20, 4.2))
axes[0].hist(np.nanmax(NULL, axis=1), bins=60, color="lightgrey", edgecolor="k", lw=.3)
axes[0].axvline(obs.max(), color="crimson", lw=2, label=f"best observed {obs.max():+.4f}")
axes[0].set_xlabel("max Sharpe/trade across the family"); axes[0].legend(fontsize=8)
axes[0].set_title(f"best-of-{X.shape[1]:,} null, p={p_best:.4f}")
axes[1].scatter(RW.table["observed"], RW.table["p_adjusted"], s=8, alpha=.45, color="darkslateblue")
axes[1].axhline(0.05, color="crimson", ls="--", lw=1.5, label="FWER 5%")
axes[1].set_xlabel("Sharpe per trade"); axes[1].set_ylabel("Romano-Wolf adjusted p")
axes[1].legend(fontsize=8); axes[1].set_title("familywise-adjusted significance")
t = RAS.table()
axes[2].scatter(t["sharpe"], t["ras_lower_bound"], s=8, alpha=.45, color="seagreen")
axes[2].axhline(0, color="crimson", ls="--", lw=1.5, label="Rademacher positive above")
axes[2].set_xlabel("empirical Sharpe/trade"); axes[2].set_ylabel("RAS lower bound")
axes[2].legend(fontsize=8)
axes[2].set_title(f"R_hat={RAS.rademacher:.4f}, haircut {RAS.haircut:.4f}")
plt.tight_layout(); plt.show()
""")

# ---------------------------------------------------------------- yardstick
md(r"""
## 8. The yardstick — the identical search on days with no release

The same configurations, the same instruments, the same offsets, the same directions, on timestamps
shifted one business day onto a minute where nothing printed.

**This is the number that decides the notebook.** If the best real cell does not beat the best
placebo cell, the search found the shape of a search.

> ### Why the pooled distribution comparison is vacuous here, and the fix
>
> `direction` is an axis, and in the closed form `momentum` is the **exact** mirror of `fade`. So
> every cell in this family has a twin whose edge is its negative, which forces the pooled
> distribution to be symmetric about zero: the median is 0, "% positive" is 50%, and "real beats its
> own placebo twin" is 50% — for **both** grids, whatever the data says. A Mann-Whitney or KS test on
> the pooled set is comparing two distributions that were constructed to be symmetric, and it will
> return p ≈ 1 on any input.
>
> That is a property of the search design, not a result, and it is why the grid-search notebook —
> which searches one direction — found the two distributions overwhelmingly different while this one
> cannot. The comparison below is therefore done **within a direction**, where nothing is forced, and
> the pooled version is shown next to it only to make the artefact visible rather than hidden.
""")

code(r"""
eligp = PLAC[(PLAC.trades >= 50) & PLAC.sr_per_trade.notna()]
rows = []
for nm, d in (("REAL releases", elig), ("wrong day (+1bd)", eligp)):
    rows.append({"grid": nm, "cells": len(d),
                 "median bp/trade": d.avg_bp.median(), "best bp/trade": d.avg_bp.max(),
                 "median Sharpe/trade": d.sr_per_trade.median(),
                 "BEST Sharpe/trade": d.sr_per_trade.max(),
                 "% positive": float((d.avg_bp > 0).mean()),
                 "% clearing a tick": float((d.avg_bp > TICK).mean())})
display(pd.DataFrame(rows).set_index("grid").round(4))

from scipy.stats import mannwhitneyu, ks_2samp

def _dir(df, d):
    return df[df.index.to_series().str.contains(fr"\|{d}$", regex=True)]

print("\nPOOLED (both directions) -- symmetric by construction, so this cannot say anything:")
u = mannwhitneyu(elig.avg_bp.dropna(), eligp.avg_bp.dropna(), alternative="two-sided")
print(f"  Mann-Whitney p = {u.pvalue:.3e}   "
      f"(real median {elig.avg_bp.median():+.4f}, placebo {eligp.avg_bp.median():+.4f} "
      f"-- both forced to 0)")

print("\nWITHIN A DIRECTION -- where nothing is forced:")
for d in ("fade", "momentum"):
    a, b = _dir(elig, d), _dir(eligp, d)
    if not len(a) or not len(b):
        continue
    u = mannwhitneyu(a.avg_bp.dropna(), b.avg_bp.dropna(), alternative="two-sided")
    k = ks_2samp(a.sr_per_trade.dropna(), b.sr_per_trade.dropna())
    pair = a[["avg_bp"]].join(b[["avg_bp"]], how="inner", lsuffix="_real", rsuffix="_plac")
    print(f"  {d:<9} real median {a.avg_bp.median():+.4f} vs placebo {b.avg_bp.median():+.4f}   "
          f"MW p = {u.pvalue:.3e}   KS p = {k.pvalue:.3e}   "
          f"real beats its twin {float((pair.avg_bp_real > pair.avg_bp_plac).mean()):.1%} "
          f"of {len(pair):,}")

best_real, best_plac = elig.sr_per_trade.max(), eligp.sr_per_trade.max()
print(f"\nBEST real cell    {best_real:+.4f} Sharpe/trade")
print(f"BEST placebo cell {best_plac:+.4f} Sharpe/trade")
if best_real <= best_plac:
    print("\nThe best cell of a search over days with NO RELEASE is at least as good as the best")
    print("cell of the same search over real releases. The winner is a property of the search.")
else:
    print(f"\nThe real search beats the placebo search by {best_real - best_plac:+.4f} Sharpe/trade")
    print("at the maximum -- which is the most this parameter search can honestly claim.")

# Every panel below is FADE-ONLY. Pooling both directions makes the distribution
# symmetric by construction, so the histograms would coincide and the scatter
# would be symmetric about the origin no matter what the data said.
_fr, _fp = _dir(elig, "fade"), _dir(eligp, "fade")
pair = _fr[["avg_bp"]].join(_fp[["avg_bp"]], how="inner", lsuffix="_real", rsuffix="_plac")
print(f"\n{len(pair):,} FADE configurations present in both grids; "
      f"real beats its own placebo twin in {float((pair.avg_bp_real > pair.avg_bp_plac).mean()):.1%}")

fig, axes = plt.subplots(1, 3, figsize=(20, 4.4))
axes[0].hist(_fp.sr_per_trade, bins=60, alpha=.6, density=True, color="grey", label="wrong day")
axes[0].hist(_fr.sr_per_trade, bins=60, alpha=.6, density=True, color="seagreen", label="real")
axes[0].axvline(0, color="k", lw=.8); axes[0].legend(fontsize=8)
axes[0].set_xlabel("Sharpe per trade")
axes[0].set_title("FADE cells only — pooling directions would force symmetry")
axes[1].hist(_fp.avg_bp, bins=60, alpha=.6, density=True, color="grey", label="wrong day")
axes[1].hist(_fr.avg_bp, bins=60, alpha=.6, density=True, color="seagreen", label="real")
axes[1].axvline(TICK, color="crimson", ls="--", lw=1.5, label=f"tick {TICK}bp")
axes[1].axvline(0, color="k", lw=.8); axes[1].legend(fontsize=8); axes[1].set_xlabel("gross bp / trade")
axes[1].set_title("edge per trade, fade only")
if len(pair):
    axes[2].scatter(pair.avg_bp_plac, pair.avg_bp_real, s=8, alpha=.4, color="darkslateblue")
    lim = [pair.min().min(), pair.max().max()]
    axes[2].plot(lim, lim, color="crimson", ls="--", lw=1.4, label="y = x")
    axes[2].axhline(0, color="k", lw=.6); axes[2].axvline(0, color="k", lw=.6)
    axes[2].set_xlabel("wrong day bp/trade"); axes[2].set_ylabel("real bp/trade"); axes[2].legend(fontsize=8)
    axes[2].set_title("config by config -- above the line is release-specific")
plt.tight_layout(); plt.show()
""")

# ---------------------------------------------------------------- recommend
md(r"""
## 9. The recommended parameters, and what they are worth

The best cell of the search, stated plainly, with every discount attached. The two numbers to read
together are its **gross edge against the 0.5 bp tick** and its **selection-bias adjusted p-value**:
the first says whether it could be traded, the second says whether it is there.
""")

code(r"""
best = elig.sort_values("sr_per_trade", ascending=False).iloc[0]
best_name = best.name
best_cfg = next(c for c in ALL_CFGS if c["name"] == best_name)
rw_row = RW.table[RW.table.strategy == best_name].iloc[0]
ras_row = RAS.table().loc[best_name]

print("BEST CONFIGURATION")
print(json.dumps({k: v for k, v in best_cfg.items()
                  if k in ("name", "instrument", "events", "timing", "signal")},
                 indent=1, default=str))

rec = {
    "configuration": best_name,
    "trades": int(best.trades),
    "trades per year": round(float(best.trades_per_year), 1),
    "gross bp / trade": round(float(best.avg_bp), 4),
    "SR3 tick (bp)": TICK,
    "clears one tick": bool(best.avg_bp > TICK),
    "net bp / trade at one tick": round(float(best.avg_bp - TICK), 4),
    "hit rate": round(float(best.hit_rate), 4),
    "Sharpe per trade": round(float(best.sr_per_trade), 4),
    "t-stat": round(float(best.t_stat), 4),
    "configurations searched": int(N_SEARCHED),
    "selection-bias adjusted p": round(float(p_best), 4),
    "Romano-Wolf adjusted p": round(float(rw_row.p_adjusted), 4),
    "Romano-Wolf rejects at 5%": bool(rw_row.reject),
    "RAS lower bound": round(float(ras_row.ras_lower_bound), 4),
    "Rademacher positive": bool(ras_row.rademacher_positive),
    "best placebo cell (Sharpe/trade)": round(float(best_plac), 4),
    "beats the placebo search": bool(best.sr_per_trade > best_plac),
}
display(pd.Series(rec).to_frame("value"))

print()
if not rec["clears one tick"]:
    print(f"The best cell's GROSS edge is {best.avg_bp:+.4f} bp against a {TICK} bp round trip, so it")
    print(f"loses {best.avg_bp - TICK:+.4f} bp every time it trades. No correction is needed to")
    print("reject it -- it does not survive the spread.")
if rec["selection-bias adjusted p"] > 0.05:
    print(f"And the best of {N_SEARCHED:,} configurations has an adjusted p of {p_best:.4f}: a family")
    print("of worthless strategies produces a best-of at least this good essentially always.")
if not rec["beats the placebo search"]:
    print("The same search on days with NO RELEASE finds a better cell than this one.")
print("\nRECOMMENDATION: none of these parameters is tradeable. The search is reported so the")
print("absence is a measured result rather than an untried possibility.")

out = G.CACHE / "paramsearch_recommendation.csv"
pd.Series(rec).to_frame("value").to_csv(out)
elig.sort_values("sr_per_trade", ascending=False).to_csv(G.CACHE / "paramsearch_leaderboard.csv")
print(f"wrote {out}")
""")

md(r"""
## 10. Reading this notebook

**§8 outranks §6.** The leaderboard is an order statistic over thousands of cells; the placebo
search is the only thing that says whether the order statistic means anything. If they overlap, no
amount of slicing inside §6 will change that.

**The tick line is the first filter, not the last.** At roughly a hundred trades a year, a cell with
a 0.2 bp gross edge against a 0.5 bp round trip loses 30 bp a year with certainty. Statistical
significance is a question you only get to ask about a configuration that clears the spread.

**The per-release table is descriptive, and §2.1 says so.** Fading CPI has whatever number it has;
the question a desk asks is whether "trade these releases and ignore those" is a rule that survives
into the next half of the sample, and the random-selection control is what answers it.

**The negative control is doing work.** `crude inventories` has no business moving the front end of
the SOFR strip. Where it scores like a rates release, the score is measuring the measurement.

**Both directions were searched, so both were paid for.** `momentum` is the exact mirror of `fade`,
which means the family contains a perfectly anti-correlated twin of every cell — and the best of a
set that includes both signs of everything is a higher bar than the best of one sign.
""")

nb = {"cells": cells,
      "metadata": {"kernelspec": {"display_name": "stir", "language": "python", "name": "python3"},
                   "language_info": {"name": "python", "version": "3.12"}},
      "nbformat": 4, "nbformat_minor": 5}
OUT.write_text(json.dumps(nb, indent=1), encoding="utf-8")
print(f"wrote {OUT}  ({len(cells)} cells)")
