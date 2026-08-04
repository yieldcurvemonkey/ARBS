# %% [markdown]
# # ZQ vs SR3 — the channel-1 backtest (boundary digitals vs the ZQ ladder)
#
# The only two-sided trade this framework admits: on days classified
# **channel 1** with a clean gate (tie-out inside tolerance, no stale ZQ print,
# refit unsaturated) and an identification-cleared gap (|t| against the
# half-tick bootstrap), fade the listed boundary digital against the
# tree-delta-weighted ZQ ladder, rebalanced at meeting resolutions, exit at
# resolution.
#
# Marks: LISTED vertical premiums (both legs, fixed strikes from entry) and ZQ
# settles through the same ladder used for the signal. Costs per contract per
# side on both legs. Both directions are run — the sign test is a house rule.

# %%
CONFIG = dict(
    entry_min_gaps=(0.04, 0.06, 0.08),
    entry_min_ts=(0.0, 2.0),
    directions=("fade", "momentum"),
    lag=1,
    cost_multipliers=(0.0, 1.0, 2.0),   # maker / base / defensive taker
)
CONFIG

# %%
import datetime
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.append("../../")

import matplotlib
if "ipykernel" not in sys.modules:
    matplotlib.use("Agg")
import matplotlib.pyplot as plt

from RVUtils.MeetingProb import meeting_ladder, split_meetings, zq_settle_panel
from RVUtils.MeetingProb.backtest import run_channel1_backtest
from RVUtils.SFRRVLab.stats import verdict
from SDRUtils.analytics.fomc import load_fomc_schedule

DATA = Path("../data/meeting_prob")
MAIN = Path("C:/Users/chris/clee/ARBS/notebooks/data/sfr_rv_lab")

mon = pd.read_parquet(DATA / "monitor.parquet")
mon["as_of"] = pd.to_datetime(mon["as_of"])
bd = pd.read_parquet(DATA / "boundaries.parquet")
bd["as_of"] = pd.to_datetime(bd["as_of"])
gate = pd.read_parquet(DATA / "tieout_gate.parquet")
gate["as_of"] = pd.to_datetime(gate["as_of"])
quotes = pd.read_parquet(MAIN / "quotes.parquet")
quotes["as_of"] = pd.to_datetime(quotes["as_of"])
contracts = pd.read_parquet(MAIN / "contracts.parquet")
contracts["as_of"] = pd.to_datetime(contracts["as_of"])
fwd_idx = contracts.set_index(["as_of", "symbol"])["forward_rate"]
print(f"monitor {len(mon)}  boundaries {len(bd)}  gate {len(gate)}")

# %% [markdown]
# ## Daily ladders (signal AND hedge come from the same object)

# %%
_M = "FGHJKMNQUVXZ"
zq = zq_settle_panel([f"ZQ{c}{y}" for y in (23, 24, 25, 26, 27) for c in _M])
fomc = load_fomc_schedule("USD-SOFR-1D")
dates = sorted(mon["as_of"].dt.date.unique())
ladders = {d: meeting_ladder(d, zq, fomc) for d in dates}
jrows = [{"as_of": pd.Timestamp(d), "effective": m.effective, "jump_bp": m.jump_bp}
         for d, lad in ladders.items() for m in lad]
jumps = pd.DataFrame(jrows)
print(f"jump rows: {len(jumps)} over {len(ladders)} days")

# %% [markdown]
# ## Signal frame: best boundary per (day, contract), fully gated

# %%
tstat_cols = [c for c in mon.columns if c.startswith("tstat_")]
mon["gap_t"] = mon[tstat_cols].abs().max(axis=1) if tstat_cols else np.nan
best_bd = (bd.reindex(bd.groupby(["as_of", "symbol"])["gap"]
                      .apply(lambda s: s.abs().idxmax()).to_numpy())
           [["as_of", "symbol", "boundary_rate", "gap", "k_lo", "k_hi",
             "right", "width_bp"]])
sig = best_bd.merge(
    mon[["as_of", "symbol", "channel", "saturated", "any_stale", "smear_bp",
         "gap_t", "days_to_expiry", "n_resolved"]],
    on=["as_of", "symbol"], how="inner",
).merge(gate.rename(columns={"any_stale": "zq_stale_day"}), on="as_of",
        how="left")
sig["gate"] = (sig["tieout_ok"].fillna(False) & ~sig["saturated"]
               & ~sig["any_stale"])
print(f"signal rows: {len(sig)}  gate pass: {sig['gate'].mean():.1%}  "
      f"channel1 & gated: {((sig['channel'] == 'channel1') & sig['gate']).mean():.2%}")
print(sig.groupby("channel")["gate"].agg(["size", "mean"]).to_string())

# %% [markdown]
# ## Vertical marks at fixed entry strikes

# %%
q_idx = quotes.set_index(["symbol", "right", "strike_price", "as_of"])[
    "premium_bp"].sort_index()


def unit_series(sym, right, k_lo, k_hi):
    """Daily digital in unit_bp from the two LISTED legs at fixed strikes."""
    try:
        lo = q_idx.loc[(sym, right, round(k_lo, 4))]
        hi = q_idx.loc[(sym, right, round(k_hi, 4))]
    except KeyError:
        return None
    j = pd.concat([lo.rename("lo"), hi.rename("hi")], axis=1).dropna()
    if j.empty:
        return None
    w = (k_hi - k_lo) * 100.0
    if right == "P":
        prob = (j["hi"] - j["lo"]) / w
    else:
        prob = 1.0 - (j["lo"] - j["hi"]) / w
    return prob * 100.0


vm_rows = []
cand = sig[(sig["channel"] == "channel1") & sig["gate"]]
for _, r in cand.drop_duplicates(["symbol", "boundary_rate"]).iterrows():
    s = unit_series(r["symbol"], r["right"], float(r["k_lo"]), float(r["k_hi"]))
    if s is None:
        continue
    f = pd.DataFrame({"as_of": s.index, "unit_bp": s.to_numpy()})
    f["symbol"], f["boundary_rate"] = r["symbol"], r["boundary_rate"]
    vm_rows.append(f)
vert_marks = (pd.concat(vm_rows, ignore_index=True) if vm_rows
              else pd.DataFrame(columns=["as_of", "symbol", "boundary_rate",
                                         "unit_bp"]))
print(f"vertical mark series: {len(vm_rows)} structures, {len(vert_marks)} rows")


def cm_lookup(d, sym):
    lad = ladders.get(d)
    return split_meetings(d, sym, lad) if lad else None


def fwd_lookup(ts, sym):
    return float(fwd_idx.loc[(pd.Timestamp(ts), sym)])

# %% [markdown]
# ## The grid — entries, identification thresholds, both signs

# %%
rows, all_trades = [], {}
for d in CONFIG["directions"]:
    for g in CONFIG["entry_min_gaps"]:
        for t in CONFIG["entry_min_ts"]:
            trades = run_channel1_backtest(
                sig, vert_marks, jumps, cm_lookup, fwd_lookup,
                entry_min_gap=g, entry_min_t=t, lag=CONFIG["lag"], direction=d)
            key = f"{d}|g{g}|t{t}"
            all_trades[key] = trades
            if trades:
                nets = np.array([x.net_bp for x in trades])
                gross = np.array([x.gross_bp for x in trades])
                costs = np.array([x.cost_bp for x in trades])
                daily = pd.concat([x.daily for x in trades]).groupby(level=0).sum()
                sd = daily.std(ddof=1)
                rows.append({
                    "direction": d, "min_gap": g, "min_t": t,
                    "n_trades": len(trades),
                    "hit": float((nets > 0).mean()),
                    "avg_net_bp": float(nets.mean()),
                    "total_gross_bp": float(gross.sum()),
                    "total_cost_bp": float(costs.sum()),
                    "total_net_bp": float(nets.sum()),
                    "sharpe": (float(daily.mean() / sd * np.sqrt(252))
                               if sd > 0 else np.nan),
                    "avg_reb": float(np.mean([x.n_rebalances for x in trades])),
                })
            else:
                rows.append({"direction": d, "min_gap": g, "min_t": t,
                             "n_trades": 0, "hit": np.nan, "avg_net_bp": np.nan,
                             "total_gross_bp": 0.0, "total_cost_bp": 0.0,
                             "total_net_bp": 0.0, "sharpe": np.nan,
                             "avg_reb": np.nan})
grid = pd.DataFrame(rows)
print(grid.round(3).to_string(index=False))
print(f"\nSIGN TEST — median total_net_bp: "
      f"{grid.groupby('direction')['total_net_bp'].median().round(2).to_dict()}")

# %% [markdown]
# ## Cost scenarios and the trade log

# %%
best_key = None
if grid["n_trades"].max() > 0:
    gi = grid[grid["n_trades"] > 0].sort_values("total_net_bp").iloc[-1]
    best_key = f"{gi['direction']}|g{gi['min_gap']}|t{gi['min_t']}"
    trades = all_trades[best_key]
    tl = pd.DataFrame([{
        "symbol": x.symbol, "entry": x.entry.date(), "exit": x.exit.date(),
        "dir": x.direction, "entry_gap": round(x.entry_gap, 3),
        "gross_bp": round(x.gross_bp, 2), "hedge_bp": round(x.hedge_bp, 2),
        "cost_bp": round(x.cost_bp, 2), "net_bp": round(x.net_bp, 2),
        "reb": x.n_rebalances, "exit_reason": x.exit_reason,
        "outcomes": x.outcomes} for x in trades])
    print(f"BEST CONFIG {best_key} — trade log:")
    print(tl.to_string(index=False))
    print("\ncost scenarios (multiplier on the per-contract model):")
    for m in CONFIG["cost_multipliers"]:
        nets = np.array([x.gross_bp - m * x.cost_bp for x in trades])
        print(f"  x{m}: total {nets.sum():+8.2f}bp  avg {nets.mean():+6.2f}  "
              f"hit {(nets > 0).mean():.0%}")
else:
    print("NO TRADES under any config — record that as the finding, "
          "not a failure of the harness.")

# %% [markdown]
# ## Verdict

# %%
if best_key is not None and len(all_trades[best_key]):
    trades = all_trades[best_key]
    maker = float(sum(x.gross_bp for x in trades))
    taker = float(sum(x.gross_bp - 2.0 * x.cost_bp for x in trades))
    med = float(grid["total_net_bp"].median())
    v = verdict(net_bp_at_taker=taker, net_bp_at_maker=maker,
                dsr_prob=0.0, median_net_bp=med, n_trades=len(trades))
    print(f"verdict (best config, DSR conservatively 0 given {len(grid)} "
          f"configs and n={len(trades)}): {v}")
else:
    print("verdict: DEAD (no qualifying entries at any threshold)")
pd.DataFrame(grid).to_parquet(DATA / "channel1_grid.parquet", index=False)
print("wrote channel1_grid.parquet")
