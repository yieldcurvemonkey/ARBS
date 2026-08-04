# %% [markdown]
# # Family B — does the premium mean-revert intra-quarter?
#
# The question that decides whether dispersion is a POSITION (held to
# resolution) or a TRADE (richness fades intra-quarter): per (book, rank),
# the daily richness `market premium − tree-fair premium` (fair via the
# strict smeared ZQ tree through the MeetingProb pricer), its OU half-life,
# and an intra-quarter fade rule that never holds to expiry.
#
# Pre-declared kill: half-life ≥ ~40 sessions ⇒ terminal-only confirmed.

# %%
import sys

import numpy as np
import pandas as pd

sys.path.append("../../")
sys.path.append(".")
import matplotlib
if "ipykernel" not in sys.modules:
    matplotlib.use("Agg")
import matplotlib.pyplot as plt

from famb_common import (
    TreeCtx, build_book, intra_quarter_backtest, load_quotes, n_contracts,
    ou_half_life, premium_surface, richness_frame, sr3_forwards,
)
from RVUtils.SFRRVLab.stats import nw_tstat

BOOKS = ["FLY25", "STRG50", "DFLY"]
RANKS = [1, 2, 3]

quotes = load_quotes()
symbols = sorted(quotes["symbol"].unique())
fwd = sr3_forwards(symbols)
fwd["as_of"] = pd.to_datetime(fwd["as_of"])
surface = premium_surface(quotes, fwd)
fwd_idx = fwd.set_index(["as_of", "symbol"])["fwd_rate"].sort_index()
dates = pd.DatetimeIndex(sorted(quotes["as_of"].unique()))
tree = TreeCtx([d.date() for d in dates])

books = {}
for book in BOOKS:
    for rank in RANKS:
        books[(book, rank)] = build_book(book, rank, dates, surface,
                                         fwd_idx, tree)

# %% [markdown]
# ## The richness level and its persistence
#
# `mean(rich)` IS the standing premium vs the lattice (the triangle's
# channel-2 object, now in premium bp); the half-life says whether
# deviations around it trade.

# %%
rows = []
for (book, rank), hs in books.items():
    if not hs:
        continue
    rf = richness_frame(hs)
    if rf.empty:
        continue
    hl, phi, n = ou_half_life(rf)
    rows.append({
        "book": book, "rank": rank, "days": n,
        "mean_rich_bp": round(float(rf["rich_bp"].mean()), 2),
        "sd_rich_bp": round(float(rf["rich_bp"].std()), 2),
        "ar1_phi": round(phi, 3), "half_life_d": round(hl, 1),
    })
persist = pd.DataFrame(rows)
print(persist.to_string(index=False))
terminal_only = persist["half_life_d"].dropna().ge(40).all() \
    if len(persist) else True
print(f"\nall half-lives >= 40 sessions: {terminal_only} -> "
      + ("terminal-only CONFIRMED — intra-quarter trading has nothing to "
         "revert on." if terminal_only else
         "richness DOES revert inside the quarter — the intra-quarter rule "
         "below is a legitimate trade shape."))

# %%
fig, ax = plt.subplots(figsize=(11, 4))
for (book, rank), hs in books.items():
    if book != "FLY25" or not hs:
        continue
    rf = richness_frame(hs)
    s = rf.groupby("as_of")["rich_bp"].mean()
    ax.plot(s.index, s.values, lw=0.9, label=f"FLY25 Q{rank}")
ax.axhline(0, color="gray", lw=0.6)
ax.set_title("FLY25 richness (market − tree-fair, bp) by rank")
ax.legend(fontsize=8)
plt.tight_layout()
plt.show()

# %% [markdown]
# ## The intra-quarter rule — trade the deviation, never hold to expiry
#
# Small, pre-declared grid: 3 books × 3 ranks × thr {2,4,6} × both
# directions; lag-1, exit at half the entry richness or 15 sessions or the
# holding's end. NW t on per-trade nets is optimistic (overlaps across
# ranks share days) — read totals and mirrors, not significance.

# %%
grid = []
for (book, rank), hs in books.items():
    if not hs:
        continue
    for thr in (2.0, 4.0, 6.0):
        for dirn in ("fade", "momentum"):
            tr = intra_quarter_backtest(
                hs, thr_bp=thr, direction=dirn,
                cost_mult=1.0, n_legs=n_contracts(book))
            if not tr:
                grid.append({"book": book, "rank": rank, "thr": thr,
                             "direction": dirn, "n": 0})
                continue
            nets = np.array([t["net_bp"] for t in tr])
            gross = np.array([t["gross_bp"] for t in tr])
            grid.append({
                "book": book, "rank": rank, "thr": thr, "direction": dirn,
                "n": len(tr), "hit": round(float((nets > 0).mean()), 2),
                "gross_bp": round(float(gross.sum()), 1),
                "net_1x_bp": round(float(nets.sum()), 1),
                "avg_sessions": round(float(np.mean(
                    [t["sessions"] for t in tr])), 1),
            })
g = pd.DataFrame(grid)
live = g[g["n"] > 0]
print(live.sort_values("net_1x_bp", ascending=False).head(14)
      .to_string(index=False))
print("\nsign test (median net@1x by direction): "
      f"{live.groupby('direction')['net_1x_bp'].median().round(1).to_dict()}")
print(f"configs run (for trial accounting): {len(g)}")

# %% [markdown]
# ## Computed answer
#
# The persistence table and the rule grid above answer the question the
# spec asked: whether the dispersion premium must be held to quarterly
# resolution or reverts tradeably inside the quarter. The findings doc
# quotes these numbers.
