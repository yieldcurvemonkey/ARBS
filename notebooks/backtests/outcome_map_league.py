# %% [markdown]
# # Outcome-map RV — the league
#
# 360 pre-declared configs in the real world and the same 360 in each placebo
# world. Five expressions form a ladder, each rung stripping one component that
# earlier work already showed is not a convergence trade:
#
# | rung | what it trades |
# |---|---|
# | `pair_raw` | the raw cell richness — the control, which should collapse onto the already-dead short-dispersion trade |
# | `pair_odd` | richness with the standing (even) premium projected out |
# | `pair_odd_dev` | that, against the contract's own causal 20-session trailing tilt |
# | `map_full` | the whole odd map as one telescoped book |
# | `reswin` | `pair_odd` entered 1–5 sessions before a decision, exited after it |
#
# crossed with the linear leg {none, ZQ basket, FOMC-swap package} — the axis
# this whole study exists to price.

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
    deflated_for_grid, grid_distribution, verdict)

DATA = Path("../data/outcome_map")
league = pd.read_parquet(DATA / "league.parquet")
real = league[league["world"] == "real"].reset_index(drop=True)
trades = pd.read_parquet(DATA / "trades_real.parquet")
with open(DATA / "dailies_real.pkl", "rb") as fh:
    dailies = pickle.load(fh)

pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 40)
live = real[real["n_trades"] > 0]
print(f"configs: {len(real)} real ({len(live)} produced trades), "
      f"{len(league) - len(real)} placebo")
print(f"trades logged: {len(trades):,}")
print(f"trades per config: median {live['n_trades'].median():.0f}, "
      f"min {live['n_trades'].min():.0f}, max {live['n_trades'].max():.0f}")

# %% [markdown]
# ## 1. Does the expression run at all?
#
# Channel-1 died on five trades in two years. The first thing to establish is
# whether the cell instrument fixes that — because if it does not, nothing else
# in this notebook matters.

# %%
print("=== trade count by expression and threshold ===")
print(real.pivot_table(index="expression", columns="thr_pp",
                       values="n_trades", aggfunc="median")
      .round(0).to_string())
print("\n=== the pre-declared kill criterion on trade count ===")
worst = live.groupby("expression")["n_trades"].median()
print(worst.round(0).to_string())
print(f"\nchannel-1 (PR #375) ran 5 trades in 2 years on the same signal "
      f"family. Median here: {live['n_trades'].median():.0f}.")

# %% [markdown]
# ## 2. The grid distribution — and the answer at 1x costs

# %%
dist = grid_distribution(live, metric="net_1x_bp")
print("=== net at 1x costs across the 360 configs ===")
for k, v in dist.items():
    print(f"  {k:14s} {v:,.2f}" if isinstance(v, float) else f"  {k:14s} {v}")
print("\n=== by expression (net_1x_bp) ===")
print(live.groupby("expression").agg(
    configs=("net_1x_bp", "size"), median=("net_1x_bp", "median"),
    best=("net_1x_bp", "max"), pct_pos=("net_1x_bp", lambda s: (s > 0).mean()),
    gross_med=("gross_bp", "median"),
    n_trades=("n_trades", "median")).round(2).to_string())

# %% [markdown]
# ## 3. The linear leg, priced
#
# The mission's question in one table. Every config exists three times — with no
# linear leg, with the ZQ meeting basket, and with the FOMC-swap package — so
# the leg's contribution and its bill are both matched-pair measurements, not
# comparisons across different trades.

# %%
key = ["expression", "dte", "thr_pp", "exit", "direction"]
wide = live.pivot_table(index=key, columns="linear",
                        values=["gross_bp", "net_1x_bp", "lin_cost_bp",
                                "hedge_bp", "lin_contracts", "n_trades"])
print("=== the linear leg's contribution and bill (per config, medians) ===")
rows = []
for leg in ("zq", "swap"):
    if ("hedge_bp", leg) not in wide.columns:
        continue
    d_gross = (wide[("gross_bp", leg)] - wide[("gross_bp", "none")]).dropna()
    bill = wide[("lin_cost_bp", leg)].dropna()
    base_gross = wide[("gross_bp", "none")].dropna()
    rows.append({
        "leg": leg,
        "hedge_pnl_median_bp": round(float(wide[("hedge_bp", leg)].median()), 2),
        "gross_change_median_bp": round(float(d_gross.median()), 2),
        "bill_median_bp": round(float(bill.median()), 2),
        "bill_over_|gross|": round(float(
            (bill / base_gross.abs().replace(0, np.nan)).median()), 2),
        "contracts_median": round(float(
            wide[("lin_contracts", leg)].median()), 2),
        "configs_improved": round(float((d_gross > 0).mean()), 3),
    })
print(pd.DataFrame(rows).to_string(index=False))
print("\nThe 'bill' is the FedWatch convention of 3 ZQ legs per meeting.")
print("At 1 leg per meeting the bill is one third of the number above:")
print(live.groupby("linear")[["lin_cost_bp", "lin_cost_1leg_bp"]]
      .median().round(2).to_string())

# %%
print("=== net at 1x by linear leg ===")
print(live.groupby("linear").agg(
    configs=("net_1x_bp", "size"), median_net=("net_1x_bp", "median"),
    best_net=("net_1x_bp", "max"), median_gross=("gross_bp", "median"),
    best_gross=("gross_bp", "max")).round(2).to_string())
print("\nThe all-config median gross is exactly zero because fade and momentum "
      "mirror: that IS the sign test passing, and it means the kill criterion "
      "has to be read on the fade half.")

# %%
fade = live[live["direction"] == "fade"]
med_gross_none = float(fade[fade["linear"] == "none"]["gross_bp"].median())
med_bill_zq = float(fade[fade["linear"] == "zq"]["lin_cost_bp"].median())
ratio = med_bill_zq / abs(med_gross_none) if med_gross_none else np.inf
print("PRE-DECLARED KILL CRITERION 1: the linear leg fails if its costs "
      "exceed half the gross of the paired expression.")
print(f"  median unhedged FADE gross {med_gross_none:+.1f}bp "
      f"vs median ZQ bill {med_bill_zq:.1f}bp -> ratio {ratio:.2f}x "
      f"({'FIRES' if med_bill_zq > 0.5 * abs(med_gross_none) else 'does not fire'})")
per = fade.copy()
per["per_trade_gross"] = per["gross_bp"] / per["n_trades"].replace(0, np.nan)
per["per_trade_optc"] = per["opt_cost_bp"] / per["n_trades"].replace(0, np.nan)
per["per_trade_linc"] = per["lin_cost_bp"] / per["n_trades"].replace(0, np.nan)
per["per_trade_hedge"] = per["hedge_bp"] / per["n_trades"].replace(0, np.nan)
per["per_trade_opt_gross"] = (per["opt_gross_bp"]
                              / per["n_trades"].replace(0, np.nan))
print("\n=== per-trade anatomy, fade only (bp per trade, medians) ===")
print(per.groupby(["expression", "linear"])[
    ["per_trade_opt_gross", "per_trade_hedge", "per_trade_gross",
     "per_trade_optc", "per_trade_linc"]].median().round(3).to_string())
print("\nThe option leg's P&L is identical across the three linear legs by "
      "construction (same signal, same trades, same marks), so every number in "
      "the hedge columns is a matched-pair measurement.")

# %% [markdown]
# ## 4. The sign test
#
# Both directions run on every config. A real edge shows as a mirror on gross:
# whatever fade earns, momentum loses.

# %%
sign = live.pivot_table(index=["expression", "linear"], columns="direction",
                        values="gross_bp", aggfunc="median")
sign["mirror_error"] = (sign["fade"] + sign["momentum"]).abs()
print("=== median gross by direction (a mirror means the sign test passes) ===")
print(sign.round(2).to_string())

# %% [markdown]
# ## 5. The winner, deflated
#
# `pick_winner` applies the n >= 10 floor before taking a maximum, so a
# one-trade row cannot headline. DSR is computed at the FULL trial count.

# %%
w = pick_winner(live)
i = int(w.name)
d = dailies.get(i, pd.Series(dtype=float))
print("=== best n-floored config ===")
for k in ("expression", "dte", "thr_pp", "exit", "linear", "direction"):
    print(f"  {k:11s} {w[k]}")
print(f"  {'n_trades':11s} {int(w['n_trades'])}")
for k in ("gross_bp", "opt_gross_bp", "hedge_bp", "opt_cost_bp",
          "lin_cost_bp", "net_1x_bp", "net_2x_bp", "hit", "nw_t", "sharpe",
          "n_contracts", "hold_sessions", "converged"):
    print(f"  {k:11s} {w[k]:+.3f}" if np.isfinite(w[k]) else
          f"  {k:11s} n/a")

dsr = deflated_for_grid(d, real, sharpe_col="sharpe")
print(f"\nDSR at {dsr['n_trials']} trials: prob {dsr['dsr_prob']:.3f}, "
      f"annualised SR {dsr['sr_annualised']:.2f}")

med_cfg = float(live["net_1x_bp"].median())
v = verdict(net_bp_at_taker=float(w["net_1x_bp"]),
            net_bp_at_maker=float(w["gross_bp"]),
            dsr_prob=float(dsr["dsr_prob"]),
            median_net_bp=med_cfg, n_trades=int(w["n_trades"]))
print(f"median config {med_cfg:+.1f}bp -> HOUSE VERDICT: {v}")

# %% [markdown]
# ## 6. Verdict per expression
#
# The same taxonomy applied to each rung of the ladder, so the question "did the
# decomposition buy anything?" gets a per-rung answer rather than an impression.

# %%
rows = []
for expr, g in live.groupby("expression"):
    gw = pick_winner(g)
    gd = dailies.get(int(gw.name), pd.Series(dtype=float))
    gdsr = deflated_for_grid(gd, real, sharpe_col="sharpe")
    rows.append({
        "expression": expr, "configs": len(g), "n": int(gw["n_trades"]),
        "gross": round(float(gw["gross_bp"]), 1),
        "per_trade_gross": round(float(gw["gross_bp"] / max(gw["n_trades"], 1)),
                                 3),
        "net_1x": round(float(gw["net_1x_bp"]), 1),
        "net_2x": round(float(gw["net_2x_bp"]), 1),
        "median_cfg": round(float(g["net_1x_bp"].median()), 1),
        "nw_t": round(float(gw["nw_t"]), 2),
        "dsr": round(float(gdsr["dsr_prob"]), 3),
        "linear": gw["linear"],
        "verdict": verdict(net_bp_at_taker=float(gw["net_1x_bp"]),
                           net_bp_at_maker=float(gw["gross_bp"]),
                           dsr_prob=float(gdsr["dsr_prob"]),
                           median_net_bp=float(g["net_1x_bp"].median()),
                           n_trades=int(gw["n_trades"])),
    })
ladder = pd.DataFrame(rows).set_index("expression").loc[
    [e for e in ("pair_raw", "pair_odd", "pair_odd_dev", "map_full", "reswin")
     if e in [r["expression"] for r in rows]]]
print("=== the ladder, per rung ===")
print(ladder.to_string())
ladder.to_csv(DATA / "verdicts.csv")

# %% [markdown]
# ## 7. Cost curve — where, if anywhere, this clears
#
# One backtest, the whole maker-to-taker curve: the gross is fixed and the
# round-trip charge is swept, so the answer to "what execution would this need?"
# is read rather than argued.

# %%
best_tr = trades[trades["config"] == i]
if len(best_tr):
    rt = float(best_tr["opt_cost_bp"].mean() + best_tr["lin_cost_bp"].mean())
    rows = []
    for mult in (0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0):
        net = best_tr["gross_bp"] - mult * (best_tr["opt_cost_bp"]
                                            + best_tr["lin_cost_bp"])
        rows.append({"cost_mult": mult,
                     "round_trip_bp": round(mult * rt, 2),
                     "total_net_bp": round(float(net.sum()), 1),
                     "avg_net_bp": round(float(net.mean()), 3),
                     "hit": round(float((net > 0).mean()), 3)})
    print(f"=== cost curve for the winner ({len(best_tr)} trades, "
          f"1x round trip {rt:.2f}bp) ===")
    print(pd.DataFrame(rows).to_string(index=False))
    be = best_tr["gross_bp"].mean() / rt if rt > 0 else np.nan
    print(f"\nbreak-even cost multiple: {be:.2f}x "
          f"(1.0 = the house half-tick model)")
