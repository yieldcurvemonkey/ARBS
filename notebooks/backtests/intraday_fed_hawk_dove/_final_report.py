"""Print every headline table from the executed notebook's cached results as text."""

from __future__ import annotations

import sys
import io
import pickle
import datetime
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\chris\clee\ARBS-gcb")
sys.path.insert(0, str(Path(__file__).parent))

import numpy as np
import pandas as pd

import global_hawk_dove_common as G
from global_hawk_dove_run import (
    SCORES_CSV, SCORE_METRIC, BASE_BPV, CACHE, BANKS,
)

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 50)


def hdr(s):
    print("\n" + "=" * 96)
    print(s)
    print("=" * 96)


events_by_bank = pickle.load(open(CACHE / "events.pkl", "rb"))
closed_by_bank = pickle.load(open(CACHE / "closed.pkl", "rb"))
pooled = (pd.concat([c for c in closed_by_bank.values() if c is not None and not c.empty],
                    ignore_index=True).sort_values("opened_at").reset_index(drop=True))

# ---------------------------------------------------------------- funnel
hdr("EVENT FUNNEL")
rows = []
for b in BANKS:
    d = events_by_bank[b]
    r = {"bank": b, "forexfactory": d["n_raw"]}
    r.update({f"x:{k}": v for k, v in d["excluded"].items()})
    r.update({f"gate:{k}": v for k, v in d["gate_reasons"].items()})
    r["TRADEABLE"] = len(d["events"])
    rows.append(r)
print(pd.DataFrame(rows).set_index("bank").fillna(0).T.to_string())

# ---------------------------------------------------------------- performance
hdr("CORE PERFORMANCE  (bp per unit of risk = realized_pnl / bpv)")
rows = []
for b in BANKS:
    cl = closed_by_bank.get(b)
    if cl is None or cl.empty:
        rows.append({"bank": b, "trades": 0}); continue
    s = G.summarize(cl); s["bank"] = b; s["ccy"] = cl["ccy"].iloc[0]
    s["local_pnl"] = cl["realized_pnl"].sum()
    rows.append(s)
s = G.summarize(pooled); s["bank"] = "POOLED"; s["ccy"] = "bp"
s["local_pnl"] = np.nan
rows.append(s)
perf = pd.DataFrame(rows).set_index("bank")
cols = ["ccy", "trades", "total", "avg", "std", "hit_rate", "sharpe", "t_stat",
        "max_dd", "trades_per_year", "local_pnl"]
print(perf[[c for c in cols if c in perf.columns]].round(4).to_string())
print("\ndate ranges:")
print(perf[["first", "last"]].to_string())

# ---------------------------------------------------------------- direction
hdr("DIRECTION CHECK — on trades where the PRICE ROSE (rates fell)")
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
up = d[d.d_px > 0].copy()
up["lost"] = up.pnl_bp < 0
print(up.groupby(["bank", "side"])["lost"].agg(["count", "mean"])
      .rename(columns={"count": "price_up_trades", "mean": "share_that_lost"}).to_string())
print("\nside=-1 is the hawk/short, which MUST lose when the price rises.")

# ---------------------------------------------------------------- buckets
hdr("SIGNAL RESPONSE — pooled, by signed bucket")
print(pooled.groupby("bucket").agg(
    trades=("pnl_bp", "count"), total_bp=("pnl_bp", "sum"),
    avg_bp=("pnl_bp", "mean"), hit=("profitable", "mean")).round(4).to_string())

print("\nhawk vs dove:")
print(pooled.groupby("direction").agg(
    trades=("pnl_bp", "count"), total_bp=("pnl_bp", "sum"),
    avg_bp=("pnl_bp", "mean"), hit=("profitable", "mean")).round(4).to_string())

print("\nby conviction |bucket|:")
print(pooled.groupby("abs_bucket").agg(
    trades=("pnl_bp", "count"), total_bp=("pnl_bp", "sum"),
    avg_bp=("pnl_bp", "mean"), hit=("profitable", "mean")).round(4).to_string())

# ---------------------------------------------------------------- permutation
hdr("SIGN-FLIP PERMUTATION TEST (2000 draws)")
rows = []
for b in BANKS + ["POOLED"]:
    cl = pooled if b == "POOLED" else closed_by_bank.get(b)
    if cl is None or cl.empty or len(cl) < 10:
        continue
    r = G.sign_flip_permutation(cl, n_perm=2000)
    rows.append({"bank": b, "realized_sharpe": r["realized_sharpe"],
                 "null_mean": r["perm_mean"], "null_std": r["perm_std"],
                 "p_value": r["p_value"]})
print(pd.DataFrame(rows).set_index("bank").round(4).to_string())

# ---------------------------------------------------------------- subsample
hdr("SUBSAMPLE STABILITY")
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
                     "total_bp": round(s["total"], 2), "avg_bp": round(s["avg"], 4),
                     "hit": round(s["hit_rate"], 3), "sharpe": round(s["sharpe"], 2),
                     "range": f"{s['first'].date()}->{s['last'].date()}"})
print(pd.DataFrame(rows).set_index(["bank", "half"]).to_string())

# ---------------------------------------------------------------- costs
hdr("TRANSACTION-COST SENSITIVITY (bp round trip, charged per trade)")
rows = []
for cost in [0.0, 0.125, 0.25, 0.5, 1.0]:
    r = {"cost_bp_rt": cost}
    for b in BANKS + ["POOLED"]:
        cl = pooled if b == "POOLED" else closed_by_bank.get(b)
        if cl is None or cl.empty:
            continue
        adj = cl["pnl_bp"] - cost
        r[f"{b}_total"] = round(adj.sum(), 1)
    rows.append(r)
print(pd.DataFrame(rows).set_index("cost_bp_rt").to_string())
be = pooled["pnl_bp"].mean()
print(f"\nPooled break-even round-trip cost = mean bp/trade = {be:.4f} bp")
print(f"At 0.25bp round trip the pooled book pays {0.25*len(pooled):.0f}bp of cost "
      f"against {pooled['pnl_bp'].sum():+.1f}bp of gross.")

# ---------------------------------------------------------------- years
hdr("CALENDAR YEAR (pooled)")
yr = pooled.groupby("year").agg(
    trades=("pnl_bp", "count"), total_bp=("pnl_bp", "sum"),
    avg_bp=("pnl_bp", "mean"), std=("pnl_bp", "std"), hit=("profitable", "mean"))
yr["sharpe"] = yr["avg_bp"] / yr["std"] * np.sqrt(yr["trades"])
print(yr.round(4).to_string())
print("\nby bank x year (total bp):")
print(pooled.pivot_table(index="year", columns="bank", values="pnl_bp",
                         aggfunc="sum").round(2).to_string())

# ---------------------------------------------------------------- speakers
hdr("TOP / BOTTOM SPEAKERS (>=8 trades)")
sp = (pooled.groupby(["bank", "speaker"]).agg(
    trades=("pnl_bp", "count"), total_bp=("pnl_bp", "sum"),
    avg_bp=("pnl_bp", "mean"), hit=("profitable", "mean")).round(4))
sp = sp[sp.trades >= 8].sort_values("total_bp", ascending=False)
print(sp.head(12).to_string())
print("...")
print(sp.tail(8).to_string())

# ---------------------------------------------------------------- sweeps
hdr("ENTRY/EXIT SENSITIVITY (pooled Sharpe, closed form)")
G.load_bar_cache(CACHE / "bars.pkl")
from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP
mdp = STIRFutureMDP(source="BARCHART_STIRF-RL", cache_full_intraday_fetch=True)
ev_only = {b: events_by_bank[b]["events"] for b in BANKS if events_by_bank[b]["events"]}

variants = {}
for eo in [-120, -60, -45, -15]:
    for xo in [60, 120, 180, 240, 360]:
        variants[f"{eo}|{xo}"] = (
            lambda bank, evs, _e=eo, _x=xo: G.rebuild_with_offsets(
                evs, G.CB_CONFIGS[bank],
                datetime.timedelta(minutes=_e), datetime.timedelta(minutes=_x))
        )
grid = G.sweep(ev_only, mdp, variants)
grid[["entry", "exit"]] = grid["variant"].str.split("|", expand=True).astype(int)
print("Sharpe:")
print(grid.pivot(index="entry", columns="exit", values="sharpe").round(2).to_string())
print("\navg bp/trade:")
print(grid.pivot(index="entry", columns="exit", values="avg").round(4).to_string())
print("\ntrades:")
print(grid.pivot(index="entry", columns="exit", values="trades").to_string())

hdr("CONTRACT SELECTION (1st..5th quarterly)")
variants = {f"{r}Q": (lambda bank, evs, _r=r: G.rebuild_with_contract(
    evs, G.CB_CONFIGS[bank], _r)) for r in [1, 2, 3, 4, 5]}
ten = G.sweep(ev_only, mdp, variants)
print(ten[["variant", "trades", "total", "avg", "hit_rate", "sharpe", "t_stat"]]
      .round(4).to_string(index=False))

print("\nDONE")
