# %% [markdown]
# # Family B — full backtest statistics and the parameter grid
#
# Two jobs: (1) proper statistics for every carry book (Sharpe, NW t, max
# drawdown, skew, worst day — both signs, 0/1/2× costs); (2) a pre-declared
# grid over the intra-quarter richness fade — book × rank × threshold ×
# exit fraction × max hold × direction — with the house discipline:
# n-floored winner, deflated Sharpe at the FULL trial count, neighborhood
# stability, chronological halves, mirrored sign tests, verdict taxonomy.
#
# The sample now includes the backfilled SFRZ24/SFRU24 (the Sep-2024 event
# contract sits in the books natively); older expiries join as the
# background backfill lands — re-execution picks them up automatically.

# %%
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.append("../../")
sys.path.append(".")
import matplotlib
if "ipykernel" not in sys.modules:
    matplotlib.use("Agg")
import matplotlib.pyplot as plt

from famb_common import (
    TreeCtx, book_daily_pnl, build_book, intra_quarter_backtest, load_quotes,
    n_contracts, premium_surface, series_stats, sr3_forwards,
    trades_daily_pnl,
)
from linvol_grid_common import pick_winner
from BT.signals.deflated_sharpe import deflated_sharpe
from RVUtils.SFRRVLab.stats import verdict

DATA = Path("../data/famb")
BOOKS = ["FLY25", "FLY50", "DFLY", "STRG50", "STRG75"]
RANKS = [1, 2, 3]

quotes = load_quotes()
symbols = sorted(quotes["symbol"].unique())
fwd = sr3_forwards(symbols)
fwd["as_of"] = pd.to_datetime(fwd["as_of"])
surface = premium_surface(quotes, fwd)
fwd_idx = fwd.set_index(["as_of", "symbol"])["fwd_rate"].sort_index()
dates = pd.DatetimeIndex(sorted(quotes["as_of"].unique()))
tree = TreeCtx([d.date() for d in dates])
books = {(b, r): build_book(b, r, dates, surface, fwd_idx, tree)
         for b in BOOKS for r in RANKS}
print(f"quotes {len(quotes)} rows, {len(symbols)} symbols "
      f"({', '.join(s for s in symbols if s.endswith('24'))} backfilled), "
      f"{dates[0].date()} -> {dates[-1].date()}")

# %% [markdown]
# ## 1. Carry-book statistics, both signs

# %%
rows = []
for (book, rank), hs in books.items():
    if not hs:
        continue
    for mult, tag in ((0.0, "0x"), (1.0, "1x"), (2.0, "2x")):
        pnl = book_daily_pnl(hs, cost_mult=mult, n_legs=n_contracts(book))
        daily = pnl.groupby("as_of")["pnl_bp"].sum()
        for sign, sname in ((1.0, "long"), (-1.0, "short")):
            # costs are sign-invariant: flip marks/settle, keep costs
            g = pnl.copy()
            m = g["kind"].isin(["mark", "settle"])
            g.loc[m, "pnl_bp"] *= sign
            d = g.groupby("as_of")["pnl_bp"].sum()
            if mult == 1.0:
                st = series_stats(d)
                st.update(book=book, rank=rank, side=sname)
                rows.append(st)
stats = pd.DataFrame(rows)[
    ["book", "rank", "side", "days", "total_bp", "sharpe_ann", "nw_t",
     "max_dd_bp", "worst_day_bp", "skew"]]
print("=== carry books @1x costs ===")
print(stats.to_string(index=False))

# %% [markdown]
# ## 2. The intra-quarter grid (pre-declared, 720 configs)

# %%
GRID = dict(thr=(2.0, 3.0, 4.0, 6.0), exit_frac=(0.25, 0.5),
            max_hold=(5, 10, 15), direction=("fade", "momentum"))
grid_rows, trade_map = [], {}
for (book, rank), hs in books.items():
    if not hs:
        continue
    for thr in GRID["thr"]:
        for ef in GRID["exit_frac"]:
            for mh in GRID["max_hold"]:
                for dirn in GRID["direction"]:
                    tr = intra_quarter_backtest(
                        hs, thr_bp=thr, exit_frac=ef, max_hold=mh,
                        direction=dirn, cost_mult=1.0,
                        n_legs=n_contracts(book))
                    cfg = dict(book=book, rank=rank, thr=thr, exit_frac=ef,
                               max_hold=mh, direction=dirn)
                    if tr:
                        nets = np.array([t["net_bp"] for t in tr])
                        n2 = np.array([t["gross_bp"] - 2 * (t["gross_bp"]
                                       - t["net_bp"]) for t in tr])
                        se = nets.std(ddof=1) / np.sqrt(len(nets)) \
                            if len(nets) > 1 else np.nan
                        cfg.update(
                            n_trades=len(tr),
                            hit=round(float((nets > 0).mean()), 2),
                            total_gross_bp=round(float(sum(
                                t["gross_bp"] for t in tr)), 1),
                            net_1x_bp=round(float(nets.sum()), 1),
                            net_2x_bp=round(float(n2.sum()), 1),
                            avg_net_1x_bp=round(float(nets.mean()), 2),
                            t_stat=round(float(nets.mean() / se), 2)
                            if se and se > 0 else np.nan)
                    else:
                        cfg.update(n_trades=0, hit=np.nan,
                                   total_gross_bp=0.0, net_1x_bp=0.0,
                                   net_2x_bp=0.0, avg_net_1x_bp=np.nan,
                                   t_stat=np.nan)
                    grid_rows.append(cfg)
                    trade_map[len(grid_rows) - 1] = tr
league = pd.DataFrame(grid_rows)
league.to_parquet(DATA / "famb_grid_league.parquet", index=False)
live = league[league["n_trades"] > 0]
print(f"{len(league)} configs, {len(live)} produced trades")
cols = ["book", "rank", "thr", "exit_frac", "max_hold", "direction",
        "n_trades", "hit", "net_1x_bp", "net_2x_bp", "t_stat"]
print("\n=== top 12 by net@1x among n>=10 ===")
solid = live[live["n_trades"] >= 10]
print(solid.sort_values("net_1x_bp", ascending=False).head(12)[cols]
      .round(2).to_string(index=False))
print("\nsign test (median net@1x): "
      f"{live.groupby('direction')['net_1x_bp'].median().round(1).to_dict()}")

# %% [markdown]
# ## 3. The winner — full statistics, DSR, neighborhood, halves

# %%
w = pick_winner(live)
wi = int(w.name)
wt = trade_map[wi]
print("WINNER:", {k: w[k] for k in cols})
hs_w = books[(w["book"], int(w["rank"]))]
daily_w = trades_daily_pnl(wt, hs_w, cost_mult=1.0,
                           n_legs=n_contracts(w["book"]))
st = series_stats(daily_w)
print("daily-series stats @1x:", st)

nets = np.array([t["net_bp"] for t in wt])
sr_pp = (live["t_stat"] / np.sqrt(live["n_trades"].clip(lower=1))).dropna()
dsr = deflated_sharpe(nets, n_trials=len(league),
                      sr_variance=float(sr_pp.var(ddof=1))
                      if len(sr_pp) > 2 else None,
                      annualisation=1.0)
print(f"DSR at n_trials={len(league)}: dsr_prob={dsr['dsr_prob']:.3f}")

nb = league[(league["book"] == w["book"]) & (league["rank"] == w["rank"])
            & (league["direction"] == w["direction"])]
n_pos = int((nb["net_1x_bp"] > 0).sum())
print(f"neighborhood (same book/rank/direction, all thr x exit x hold): "
      f"{n_pos}/{len(nb)} positive, median "
      f"{nb['net_1x_bp'].median():+.1f}bp -> "
      + ("SUPPORTED" if n_pos > len(nb) / 2 else "ISLAND"))

tl = pd.DataFrame(wt)
mid = tl["entry"].min() + (tl["entry"].max() - tl["entry"].min()) / 2
for name, seg in (("H1", tl[tl["entry"] <= mid]),
                  ("H2", tl[tl["entry"] > mid])):
    print(f"  {name}: {len(seg)} trades  net {seg['net_bp'].sum():+.1f}bp  "
          f"hit {(seg['net_bp'] > 0).mean():.0%}" if len(seg)
          else f"  {name}: 0 trades")

med = float(league["net_1x_bp"].fillna(0.0).median())
v = verdict(net_bp_at_taker=float(w["net_2x_bp"]),
            net_bp_at_maker=float(w["total_gross_bp"]),
            dsr_prob=float(dsr["dsr_prob"]) if np.isfinite(
                dsr["dsr_prob"]) else 0.0,
            median_net_bp=med, n_trades=int(w["n_trades"]))
print(f"\nVERDICT (house taxonomy): {v}   "
      f"(median config net {med:+.1f}bp across {len(league)} trials)")

# %%
fig, ax = plt.subplots(figsize=(10, 4))
ax.step(daily_w.index, daily_w.cumsum().values, where="post")
ax.axhline(0, color="gray", lw=0.6)
ax.set_title(f"winner equity @1x: {w['book']} Q{int(w['rank'])} "
             f"thr{w['thr']} exit{w['exit_frac']} hold{int(w['max_hold'])} "
             f"{w['direction']}")
ax.set_ylabel("cum net bp")
plt.tight_layout()
plt.show()

# %% [markdown]
# ## 4. Per-trade distribution of the winner

# %%
print(tl[["symbol", "entry", "exit", "entry_rich", "side", "sessions",
          "gross_bp", "net_bp"]].round(2).to_string(index=False))
print(f"\nper-trade: mean {tl['net_bp'].mean():+.2f}  median "
      f"{tl['net_bp'].median():+.2f}  sd {tl['net_bp'].std():.2f}  "
      f"min {tl['net_bp'].min():+.2f}  max {tl['net_bp'].max():+.2f}")
top_share = tl["net_bp"].max() / tl["net_bp"].sum() \
    if tl["net_bp"].sum() > 0 else np.nan
print(f"largest trade / total: {top_share:.0%}"
      if np.isfinite(top_share) else "")
