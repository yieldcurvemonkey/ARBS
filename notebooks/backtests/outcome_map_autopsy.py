# %% [markdown]
# # Outcome-map RV — autopsy
#
# The league named a best row. This notebook tries to break it: chronological
# halves, the one-parameter-at-a-time neighbourhood, the two placebo worlds
# (Gaussian tree, wrong calendar) re-derived from atoms up, the trade log, and
# the five pre-declared kill criteria answered one at a time.

# %%
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.append("../../")
sys.path.append(".")
from linvol_grid_common import pick_winner                  # noqa: E402
from RVUtils.SFRRVLab.stats import (                        # noqa: E402
    deflated_for_grid, neighbourhood_stability, nw_tstat)

DATA = Path("../data/outcome_map")
league = pd.read_parquet(DATA / "league.parquet")
real = league[league["world"] == "real"].reset_index(drop=True)
trades = pd.read_parquet(DATA / "trades_real.parquet")
with open(DATA / "dailies_real.pkl", "rb") as fh:
    dailies = pickle.load(fh)

pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 40)
live = real[real["n_trades"] > 0]
w = pick_winner(live)
i = int(w.name)
tr = trades[trades["config"] == i].sort_values("entry").reset_index(drop=True)
d = dailies.get(i, pd.Series(dtype=float))
print(f"winner: {w['expression']} | dte {w['dte']} | thr {w['thr_pp']}pp | "
      f"exit {w['exit']} | linear {w['linear']} | {w['direction']}")
print(f"{int(w['n_trades'])} trades, gross {w['gross_bp']:+.1f}bp, "
      f"net {w['net_1x_bp']:+.1f} @1x / {w['net_2x_bp']:+.1f} @2x")

# %% [markdown]
# ## 1. Chronological halves
#
# The single most useful robustness check in a one-cycle sample: does the second
# half of the history look anything like the first?

# %%
if len(tr):
    mid = tr["entry"].quantile(0.5)
    rows = []
    for label, m in (("first half", tr["entry"] <= mid),
                     ("second half", tr["entry"] > mid)):
        g = tr[m]
        rows.append({"half": label, "n": len(g),
                     "from": str(g["entry"].min().date()) if len(g) else "-",
                     "to": str(g["entry"].max().date()) if len(g) else "-",
                     "gross_bp": round(float(g["gross_bp"].sum()), 1),
                     "net_1x_bp": round(float(g["net_1x_bp"].sum()), 1),
                     "per_trade_gross": round(float(g["gross_bp"].mean()), 3),
                     "hit_1x": round(float((g["net_1x_bp"] > 0).mean()), 3)})
    print(pd.DataFrame(rows).to_string(index=False))

# %%
print("=== by calendar year (gross, so the cost model cannot mask a regime) ===")
if len(tr):
    yr = tr.groupby(tr["entry"].dt.year).agg(
        n=("gross_bp", "size"), gross_bp=("gross_bp", "sum"),
        per_trade=("gross_bp", "mean"), net_1x=("net_1x_bp", "sum"))
    print(yr.round(2).to_string())

# %% [markdown]
# ## 2. Neighbourhood
#
# A knife-edge optimum is visible as a knife edge. Every row below holds the
# winner's parameters fixed except one.

# %%
params = ["expression", "dte", "thr_pp", "exit", "linear", "direction"]
nb = neighbourhood_stability(live, w, params, metric="net_1x_bp")
print(nb.to_string(index=False))
pos = int((nb["net_1x_bp"] > 0).sum())
print(f"\nneighbourhood: {pos}/{len(nb)} positive at 1x, "
      f"median {nb['net_1x_bp'].median():+.1f}bp")

# %% [markdown]
# ## 3. The placebos
#
# **P1 Gaussian tree** — the fair value is a moment-matched Gaussian at the
# forward and the cells are placed on a lattice-free 25bp grid, so neither the
# prices nor the atom locations borrow anything from the FOMC lattice; only the
# map's size (a calendar fact) is kept.
# **P2 wrong calendar** — every meeting wears the next meeting's jump, support
# and mantissa, and the atoms, cells, fair values and hedge ratios are all
# re-derived inside that world.
#
# If the edge survives either, it was never lattice information.

# %%
rows = []
for world, g in league.groupby("world"):
    gl = g[g["n_trades"] > 0]
    if gl.empty:
        continue
    gw = pick_winner(gl)
    rows.append({
        "world": world, "configs": len(g), "with_trades": len(gl),
        "best_gross": round(float(gl["gross_bp"].max()), 1),
        "best_net_1x": round(float(gl["net_1x_bp"].max()), 1),
        "median_gross": round(float(gl["gross_bp"].median()), 1),
        "winner_expr": gw["expression"], "winner_n": int(gw["n_trades"]),
        "winner_gross": round(float(gw["gross_bp"]), 1),
    })
pl = pd.DataFrame(rows).set_index("world")
print(pl.to_string())

# %%
print("=== the winner's OWN coordinates, in each world ===")
coords = {k: w[k] for k in params}
rows = []
for world, g in league.groupby("world"):
    m = np.ones(len(g), dtype=bool)
    for k, v in coords.items():
        m &= (g[k] == v).to_numpy()
    if not m.any():
        rows.append({"world": world, "found": False})
        continue
    r = g[m].iloc[0]
    rows.append({"world": world, "found": True, "n": int(r["n_trades"]),
                 "gross_bp": round(float(r["gross_bp"]), 1),
                 "net_1x_bp": round(float(r["net_1x_bp"]), 1),
                 "per_trade_gross": round(
                     float(r["gross_bp"] / max(r["n_trades"], 1)), 3)})
same = pd.DataFrame(rows)
print(same.to_string(index=False))
if len(same) > 1 and same["found"].all():
    base = float(same[same["world"] == "real"]["gross_bp"].iloc[0])
    for _, r in same[same["world"] != "real"].iterrows():
        keep = float(r["gross_bp"]) / base if base else np.nan
        print(f"  {r['world']}: retains {keep:.0%} of the real gross")
    print("\nA placebo that retains most of the gross means the signal was "
          "never lattice information — the pre-declared kill criterion 3.")

# %% [markdown]
# ## 4. The trade log
#
# Individual trades, so a single episode carrying the result is visible as a
# single episode.

# %%
if len(tr):
    # measured against GROSS: this winner's net is ~0, so a share-of-net
    # ratio would be a meaningless large number
    conc = float(tr["gross_bp"].abs().max() / max(abs(tr["gross_bp"].sum()),
                                                  1e-9))
    top3 = float(tr["gross_bp"].nlargest(3).sum() / max(tr["gross_bp"].sum(),
                                                        1e-9))
    print(f"largest single trade is {conc:.0%} of total gross; "
          f"the top 3 are {top3:.0%} of it")
    show = tr[["symbol", "entry", "exit", "side", "n_contracts",
               "entry_signal_bp", "exit_signal_bp", "opt_gross_bp",
               "hedge_bp", "opt_cost_bp", "lin_cost_bp", "net_1x_bp",
               "exit_reason"]]
    print(show.head(15).round(3).to_string(index=False))
    print("\n=== exit reasons ===")
    print(tr["exit_reason"].value_counts().to_string())
    print("\n=== signal decay: did the thing we entered on actually converge? "
          "===")
    conv = (tr["exit_signal_bp"].abs() / tr["entry_signal_bp"].abs())
    print(f"  |exit signal| / |entry signal|: median {conv.median():.2f}, "
          f"share below 1: {(conv < 1).mean():.1%}")
    print(f"  mean holding: {(tr['exit'] - tr['entry']).dt.days.mean():.1f} "
          f"calendar days")

# %% [markdown]
# ## 5. The linear leg, trade by trade
#
# The hedge is supposed to remove the package's exposure to each meeting's
# priced jump. Whether it earns its bill is the whole point of the study.

# %%
lin_tr = trades[trades["lin_contracts"] > 0]
if len(lin_tr):
    print(f"trades carrying a linear leg: {len(lin_tr):,}")
    print(f"  hedge P&L   : total {lin_tr['hedge_bp'].sum():+.1f}bp, "
          f"per trade {lin_tr['hedge_bp'].mean():+.3f}bp, "
          f"std {lin_tr['hedge_bp'].std():.3f}")
    print(f"  linear bill : total {lin_tr['lin_cost_bp'].sum():.1f}bp, "
          f"per trade {lin_tr['lin_cost_bp'].mean():.3f}bp")
    print(f"  option bill : per trade {lin_tr['opt_cost_bp'].mean():.3f}bp")
    print(f"  basket size : {lin_tr['lin_contracts'].mean():.2f} contracts "
          f"(3 legs per meeting)")
    print(f"  rebalances  : {lin_tr['n_rebalances'].mean():.2f} per trade")
    # does the hedge reduce dispersion? that is what a hedge is FOR
    j = trades.drop(columns=["expression"]).merge(
        real[["expression", "dte", "thr_pp", "exit", "linear", "direction"]]
        .reset_index().rename(columns={"index": "config"}), on="config")
    piv = j.groupby(["expression", "linear"])["opt_gross_bp"].std()
    tot = j.groupby(["expression", "linear"])["gross_bp"].std()
    print("\n=== std of per-trade P&L: option leg alone vs option+hedge ===")
    print(pd.DataFrame({"opt_only_std": piv, "with_hedge_std": tot,
                        "ratio": (tot / piv)}).round(3).to_string())
    print("\nA hedge that RAISES the standard deviation is adding a position, "
          "not removing risk.")

# %% [markdown]
# ### The two-linear-source consistency test
#
# This is the sharpest available check on whether the hedge leg is replicating
# anything. The ZQ ladder and the meeting-dated swap ladder measure the *same*
# per-meeting jumps and (per the atlas) tie out to a couple of bp. The hedge
# ratios are identical — the same `h` vector, the same package, the same trades;
# only the market the jump is marked in differs. A hedge that is replicating the
# package's meeting exposure must therefore produce nearly the same P&L in both.
# If the two disagree materially, the "hedge P&L" is measurement noise wearing a
# hedge's clothes, and its sign in this sample is an accident of one rate cycle.

# %%
key = ["expression", "dte", "thr_pp", "exit", "direction"]
hp = real.pivot_table(index=key, columns="linear", values="hedge_bp")
if {"zq", "swap"}.issubset(hp.columns):
    both = hp.dropna(subset=["zq", "swap"])
    both = both[(both["zq"].abs() > 1e-9) | (both["swap"].abs() > 1e-9)]
    ratio = (both["swap"] / both["zq"].replace(0, np.nan)).dropna()
    corr = float(both["zq"].corr(both["swap"]))
    print(f"configs with a hedge on both markets: {len(both)}")
    print(f"  correlation of hedge P&L across the two markets : {corr:.3f}")
    print(f"  swap / ZQ hedge P&L ratio: median {ratio.median():.2f}, "
          f"IQR [{ratio.quantile(.25):.2f}, {ratio.quantile(.75):.2f}]")
    print(f"  median |ZQ hedge| {both['zq'].abs().median():.1f}bp vs "
          f"|swap hedge| {both['swap'].abs().median():.1f}bp")
    print("\nTwo markets that agree about the jumps to a couple of bp, marking "
          "the SAME hedge ratios on the SAME trades, should produce the same "
          "hedge P&L. The gap between them is the honest error bar on any "
          "claim that the linear leg contributed.")

# %% [markdown]
# ### Is the hedge the right SIZE?
#
# `hedge_bp = -side * sum_m h_m * d(jump_m)`, so `-hedge_bp` is exactly what the
# lattice predicted the option package would earn from the meetings repricing.
# Regressing the option leg's realised P&L on that prediction, through the
# origin, measures the hedge ratio the market actually wants. A beta of 1 means
# the frame-frozen ratios are right-sized; a beta well under 1 means the hedge
# is scaled to a distribution the market does not use.
#
# The reason to expect a miss here — and the reason the channel-1 study did not
# see one — is that a digital's lattice sensitivity is a difference of CDFs
# (bounded, smooth) while a butterfly's is a DENSITY. The lattice's density is a
# sum of near-atoms; the market's is the same mass smeared by the off-lattice
# premium the atlas measures at 15–29pp. For a density-like payoff that
# difference is first-order.

# %%
cal = trades[(trades["lin_contracts"] > 0) & (trades["hedge_bp"].abs() > 1e-9)]
if len(cal) > 30:
    pred = -cal["hedge_bp"].to_numpy()          # what the lattice predicted
    real_pnl = cal["opt_gross_bp"].to_numpy()   # what the option leg did
    beta = float(np.dot(pred, real_pnl) / np.dot(pred, pred))
    resid = real_pnl - beta * pred
    r2 = 1.0 - float(np.var(resid) / np.var(real_pnl))
    print(f"n = {len(cal):,} hedged trades")
    print(f"  realised option P&L on lattice-predicted P&L: "
          f"beta = {beta:.3f}, R^2 = {r2:.3f}")
    print(f"  std of prediction {pred.std():.2f}bp vs std of realisation "
          f"{real_pnl.std():.2f}bp  (ratio {real_pnl.std() / pred.std():.2f})")
    print(f"\n  -> the frame-frozen ratios are "
          f"{1 / beta:.1f}x too large for this payoff"
          if 0 < beta < 1 else "")

    print("\n=== net P&L if the basket were scaled by k (IN-SAMPLE, post-hoc) "
          "===")
    rows = []
    for k in (0.0, 0.25, beta, 0.5, 1.0):
        net1 = (cal["opt_gross_bp"] + k * cal["hedge_bp"]
                - cal["opt_cost_bp"] - k * cal["lin_cost_bp"])
        rows.append({"k": round(k, 3),
                     "gross_bp": round(float((cal["opt_gross_bp"]
                                              + k * cal["hedge_bp"]).sum()), 1),
                     "net_1x_bp": round(float(net1.sum()), 1),
                     "per_trade_net": round(float(net1.mean()), 3),
                     "std_per_trade": round(float(
                         (cal["opt_gross_bp"] + k * cal["hedge_bp"]).std()), 2)})
    print(pd.DataFrame(rows).to_string(index=False))
    print("\nThis is a post-hoc, in-sample rescaling — it cannot certify a "
          "strategy. It answers one question only: is the linear leg the wrong "
          "SIZE, or the wrong IDEA?")

# %% [markdown]
# There are two candidate explanations for a beta well under one, and they have
# opposite implications. **Staleness**: the ratios are frozen at entry, so a
# large move over a long hold walks the package away from the frame they were
# computed in — a fixable execution problem (rebalance more). **Geometry**: a
# butterfly's lattice sensitivity is a density and the market's density is the
# lattice's smeared by the off-lattice premium — an unfixable model problem.
#
# They separate cleanly: if staleness dominates, beta rises toward 1 for short
# holds and small realised moves; if geometry dominates, beta is flat.

# %%
if len(cal) > 30:
    c = cal.copy()
    c["hold_days"] = (c["exit"] - c["entry"]).dt.days
    c["pred"] = -c["hedge_bp"]
    c["move"] = c["pred"].abs()
    rows = []
    for label, grp in (("hold <= 7d", c[c["hold_days"] <= 7]),
                       ("hold 8-16d", c[(c["hold_days"] > 7)
                                        & (c["hold_days"] <= 16)]),
                       ("hold > 16d", c[c["hold_days"] > 16]),
                       ("|predicted| < 2bp", c[c["move"] < 2]),
                       ("|predicted| 2-8bp", c[(c["move"] >= 2)
                                               & (c["move"] < 8)]),
                       ("|predicted| >= 8bp", c[c["move"] >= 8])):
        if len(grp) < 30:
            continue
        p, y = grp["pred"].to_numpy(), grp["opt_gross_bp"].to_numpy()
        b = float(np.dot(p, y) / np.dot(p, p))
        rows.append({"subset": label, "n": len(grp), "beta": round(b, 3),
                     "median_hold_d": int(grp["hold_days"].median()),
                     "median_|pred|_bp": round(float(grp["move"].median()), 2)})
    print("=== hedge-ratio beta by holding period and by realised move ===")
    print(pd.DataFrame(rows).to_string(index=False))
    print("\nA beta that does not climb toward 1 for short holds and small "
          "moves is not a staleness problem.")

# %% [markdown]
# ## 6. The pre-declared kill criteria, answered

# %%
fade = live[live["direction"] == "fade"]
med_gross_none = float(fade[fade["linear"] == "none"]["gross_bp"].median())
med_bill = float(fade[fade["linear"] == "zq"]["lin_cost_bp"].median())
k1 = med_bill > 0.5 * abs(med_gross_none)
k2 = float(live["n_trades"].median()) <= 5
# placebo retention is read on the BEST n-floored row in each world, not on the
# winner's own coordinates: a placebo world gets the same 360 trials, so the
# honest comparison is best-of-360 against best-of-360
best_by_world = {}
for world, g in league.groupby("world"):
    gl = g[g["n_trades"] > 0]
    if len(gl):
        best_by_world[world] = float(pick_winner(gl)["gross_bp"])
base_gross = best_by_world.get("real", np.nan)
placebo_keep = np.nan
if np.isfinite(base_gross) and base_gross != 0:
    others = [v for k, v in best_by_world.items() if k != "real"]
    placebo_keep = max(others) / base_gross if others else np.nan
k3 = bool(np.isfinite(placebo_keep) and placebo_keep > 0.5)
raw_best = float(live[live["expression"] == "pair_raw"]["net_1x_bp"].max())
odd_best = float(live[live["expression"].isin(
    ["pair_odd", "pair_odd_dev"])]["net_1x_bp"].max())
k4 = odd_best <= raw_best
dsr = deflated_for_grid(d, real, sharpe_col="sharpe")
k5 = (int(w["n_trades"]) >= 10 and float(w["net_2x_bp"]) > 0
      and float(dsr["dsr_prob"]) > 0.5
      and float(live["net_1x_bp"].median()) >= 0)

print("1. linear leg costs > half the gross of the paired expression?")
print(f"     median unhedged FADE gross {med_gross_none:+.1f}bp, median ZQ bill "
      f"{med_bill:.1f}bp -> {'FIRES' if k1 else 'does not fire'}")
print("2. collapses to 1-5 trades / 2y like channel-1?")
print(f"     median config runs {live['n_trades'].median():.0f} trades "
      f"-> {'FIRES' if k2 else 'does not fire'}")
print("3. placebos retain the edge?")
print(f"     best-of-360 gross by world: "
      + ", ".join(f"{k} {v:+.1f}bp" for k, v in best_by_world.items()))
print(f"     best placebo retains {placebo_keep:.0%} of the real gross "
      f"-> {'FIRES' if k3 else 'does not fire'}")
print("4. the odd rungs fail to separate from pair_raw?")
print(f"     best raw {raw_best:+.1f}bp vs best odd {odd_best:+.1f}bp "
      f"-> {'FIRES' if k4 else 'does not fire'}")
print("5. ALIVE (n>=10, positive at 2x, DSR>0.5, median config >= 0)?")
print(f"     n={int(w['n_trades'])}, net2x {w['net_2x_bp']:+.1f}, "
      f"DSR {dsr['dsr_prob']:.3f}, median config "
      f"{live['net_1x_bp'].median():+.1f} -> {'YES' if k5 else 'NO'}")
