"""Generate global_cb_hawk_dove_instrument_grid.ipynb."""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "global_cb_hawk_dove_instrument_grid.ipynb"

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


md(r"""
# Which instrument, and which label? — a deflated grid search

Searches the front-end STIR complex for the best expression of the central-bank speaker
hawk/dove signal, across six currencies:

| dimension | values |
|---|---|
| **structure** | outrights `OUT_1..6`, calendar spreads `SPR_n_m`, butterflies `FLY_n_b_k`, packs `PACK_n` — built from the 1st…6th quarterly IMM contracts |
| **labelling** | `peer` (relative to committee), `percentile` (relative to own past), `absolute` (Fed ±10/±20), `researched` (hand-researched standing), `blended` (peer ∧ researched) |
| **timing** | entry T−120…−15m, exit T+60…+240m |

### The thing this notebook is really about

Ranking thousands of configurations by Sharpe **finds a high Sharpe whether or not any signal
exists**. With ~2,000 trials, the best of them will show an annualised Sharpe near 1 even when
every single one is noise. So the headline number here is not the top Sharpe — it is the
**Deflated Sharpe Ratio**, which asks: given that we searched this hard, what is the probability
this strategy's *true* Sharpe is above zero?

DSR uses the spread of Sharpes actually observed across the grid to calibrate what the search
could have produced by chance, and corrects for skew and kurtosis — which matter here, because an
event study is exactly the shape (rare large moves) that inflates a naive Sharpe.

A configuration is only interesting if **DSR > 0.95 with a meaningful trade count**.
""")

code(r"""
%load_ext autoreload
%autoreload 2

import sys, pickle
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
pylab.rcParams.update({"figure.figsize": (14, 6), "axes.titlesize": "large"})

import global_hawk_dove_common as G
import global_hawk_dove_grid as GRID
from global_hawk_dove_run import CACHE, BANKS

with open(CACHE / "grid_panel.pkl", "rb") as f:
    store = pickle.load(f)

MAX_RANK = 6
structures = GRID.build_structures(MAX_RANK)
print(f"{len(structures)} structures, {len(store)} labelling schemes")
for m, blob in store.items():
    tot = sum(len(v) for v in blob["metas"].values())
    print(f"  {m:12s} legs={list(blob['panels'])}  events={tot}")
""")

md("## 1. The grid")

code(r"""
from global_hawk_dove_grid_run import CAUSAL_MODES, NONCAUSAL_MODES, ENTRY_MIN, EXIT_MIN

frames = []
for mode, blob in store.items():
    g = GRID.run_grid(blob["panels"], blob["metas"], structures, cost_bp=0.0)
    if g.empty:
        continue
    g["bucket_mode"] = mode
    g["causal"] = mode in CAUSAL_MODES
    frames.append(g)
allg = pd.concat(frames, ignore_index=True)

# The researched / blended labels were written in 2026 about trades from 2023-2026.
# They are not tradeable, so they are held out of the ranking and deflated on their
# own; mixing a fitted label into the same deflation as honest ones understates the
# hurdle for the honest ones.
grid = allg[allg["causal"]].reset_index(drop=True)
noncausal = allg[~allg["causal"]].reset_index(drop=True)
N_TRIALS = len(grid) * len(ENTRY_MIN) * len(EXIT_MIN)
grid = GRID.add_deflated(grid, n_trials=N_TRIALS)
show = ["structure", "kind", "bucket_mode", "trades", "total_bp", "avg_bp",
        "hit", "sharpe_ann", "t_stat", "dsr"]
print(f"configs scored: {len(grid)}   trials priced into the deflation: {N_TRIALS}")
print(f"selection hurdle SR* (per-trade): {grid['sr_star'].iloc[0]:.4f}")
display(grid[show].head(25).round(4))
""")

md(r"""
## 2. The honest answer

The left panel is what a naive search reports; the right is what survives pricing the search.
""")

code(r"""
fig, axes = plt.subplots(1, 2, figsize=(16, 5))

ax = axes[0]
ax.hist(grid["sharpe_ann"], bins=40, color="steelblue", alpha=.8, edgecolor="k", lw=.3)
ax.axvline(0, color="k", lw=.8)
ax.set_xlabel("annualised Sharpe"); ax.set_ylabel("configs")
ax.set_title(f"Sharpe across {len(grid)} configurations")

ax = axes[1]
ax.scatter(grid["sharpe_ann"], grid["dsr"], s=14, alpha=.6,
           c=np.where(grid["dsr"] > 0.95, "seagreen", "grey"))
ax.axhline(0.95, color="crimson", ls="--", lw=1.2, label="DSR = 0.95")
ax.set_xlabel("annualised Sharpe"); ax.set_ylabel("Deflated Sharpe (P[true SR > 0])")
ax.set_title("Sharpe vs DSR — height, not width, is what counts")
ax.legend()
plt.tight_layout(); plt.show()

alive = grid[(grid["dsr"] > 0.95) & (grid["trades"] >= 50)]
print(f"configs with DSR > 0.95 and >= 50 trades: {len(alive)} / {len(grid)}")
display(alive[show].round(4).head(20) if len(alive) else "NONE")

if len(noncausal):
    nc = GRID.add_deflated(noncausal, n_trials=len(noncausal) * len(ENTRY_MIN) * len(EXIT_MIN))
    print(chr(10) + "NON-CAUSAL UPPER BOUND - researched / blended labels.")
    print("Written in 2026 about these very trades, so NOT tradeable. Shown only to bound")
    print("what perfect knowledge of who was a hawk would have been worth:")
    display(nc.sort_values("sharpe_ann", ascending=False)[
        ["structure", "bucket_mode", "trades", "avg_bp", "sharpe_ann", "t_stat"]].head(8).round(4))
""")

md("## 3. Which structure family, and which label?")

code(r"""
fig, axes = plt.subplots(1, 2, figsize=(16, 5))
sns.boxplot(data=grid, x="kind", y="sharpe_ann", ax=axes[0])
axes[0].axhline(0, color="k", lw=.8); axes[0].set_title("Sharpe by structure family")
sns.boxplot(data=grid, x="bucket_mode", y="sharpe_ann", ax=axes[1])
axes[1].axhline(0, color="k", lw=.8); axes[1].set_title("Sharpe by labelling scheme")
axes[1].tick_params(axis="x", rotation=20)
plt.tight_layout(); plt.show()

print("by structure family:")
display(grid.groupby("kind")[["sharpe_ann", "avg_bp", "trades", "dsr"]]
        .agg({"sharpe_ann": ["count", "median", "max"], "avg_bp": "median",
              "trades": "median", "dsr": "max"}).round(4))
print("by labelling scheme:")
display(grid.groupby("bucket_mode")[["sharpe_ann", "avg_bp", "trades", "dsr"]]
        .agg({"sharpe_ann": ["count", "median", "max"], "avg_bp": "median",
              "trades": "median", "dsr": "max"}).round(4))
""")

md(r"""
### Structure vs contract rank

Outrights only, so the comparison is like-for-like: does the signal live at the very front of the
strip or further out? A monotone rise with rank is a warning sign, not a discovery — it usually
means duration beta rather than anything about the speech.
""")

code(r"""
out = grid[grid.kind == "outright"].copy()
out["rank"] = out["structure"].str.split("_").str[1].astype(int)
piv = out.pivot_table(index="rank", columns="bucket_mode", values="sharpe_ann")
fig, ax = plt.subplots(figsize=(10, 5))
piv.plot(marker="o", ax=ax)
ax.axhline(0, color="k", lw=.8)
ax.set_xlabel("quarterly contract rank (1 = front)"); ax.set_ylabel("annualised Sharpe")
ax.set_title("Outright Sharpe by contract rank")
plt.tight_layout(); plt.show()
display(piv.round(3))
""")

md("## 4. Cost sensitivity of the best configurations")

code(r"""
top = grid.sort_values("sharpe_ann", ascending=False).head(8)
rows = []
for cost in [0.0, 0.125, 0.25, 0.5, 1.0]:
    for _, r in top.iterrows():
        ret = r["_returns"] - cost
        sd = ret.std(ddof=1)
        rows.append({
            "cost_bp": cost, "config": f"{r['structure']}|{r['bucket_mode']}",
            "avg_bp": ret.mean(),
            "sharpe": (ret.mean() / sd * np.sqrt(len(ret) / max(
                (r['trades'] / max(r['trades'], 1)), 1))) if sd > 0 else 0.0,
            "total_bp": ret.sum(),
        })
cost_df = pd.DataFrame(rows).pivot(index="cost_bp", columns="config", values="total_bp")
display(cost_df.round(1))

fig, ax = plt.subplots(figsize=(11, 5))
cost_df.plot(ax=ax, marker="o")
ax.axhline(0, color="k", lw=.8); ax.set_ylabel("total bp"); ax.set_xlabel("round-trip cost (bp)")
ax.set_title("Do the best configurations survive costs?")
ax.legend(fontsize=8, ncol=2)
plt.tight_layout(); plt.show()
""")

md("## 5. Per-leg contribution of the best configuration")

code(r"""
best = grid.sort_values("sharpe_ann", ascending=False).iloc[0]
st = next(s for s in structures if s.name == best["structure"])
blob = store[best["bucket_mode"]]
print(f"best by Sharpe: {best['structure']} / {best['bucket_mode']}  "
      f"SR={best['sharpe_ann']:.2f}  DSR={best['dsr']:.3f}  n={int(best['trades'])}")

rows = []
for bank, panel in blob["panels"].items():
    m = blob["metas"][bank]
    d = GRID.structure_pnl_bp(panel, st)
    if d.empty:
        continue
    j = m.join(d.rename("d"), how="inner").dropna(subset=["d"])
    if j.empty:
        continue
    pnl = j["side_rate"] * j["d"] / (st.gross or 1.0)
    rows.append({"bank": bank, "trades": len(pnl), "total_bp": pnl.sum(),
                 "avg_bp": pnl.mean(), "hit": float((pnl > 0).mean())})
display(pd.DataFrame(rows).set_index("bank").round(4))

print("\nby timestamp provenance (does the signal live in the REAL timings?):")
rows = []
for bank, panel in blob["panels"].items():
    m = blob["metas"][bank]; d = GRID.structure_pnl_bp(panel, st)
    if d.empty: continue
    j = m.join(d.rename("d"), how="inner").dropna(subset=["d"])
    j["pnl"] = j["side_rate"] * j["d"] / (st.gross or 1.0)
    for src, sub in j.groupby("timestamp_source"):
        rows.append({"bank": bank, "src": src, "n": len(sub),
                     "total_bp": sub["pnl"].sum(), "avg_bp": sub["pnl"].mean()})
prov = pd.DataFrame(rows)
display(prov.groupby("src")[["n", "total_bp", "avg_bp"]].sum().round(3) if len(prov) else "n/a")
""")

md(r"""
## 6. Verdict

Read in this order:

1. **How many configurations cleared DSR > 0.95?** If none, the grid found nothing that survives
   the cost of having searched — the top Sharpe is what this many trials produces from noise.
2. **Does the best configuration survive costs?** Break-even round-trip is `avg_bp`; the listed
   SR3 outright is roughly a quarter-tick, and the ESTR/SONIA/CORRA/SARON strips are wider.
3. **Where does the P&L come from?** If it is concentrated in synthetic-timestamp events, the
   result is about holding a session on a speech day, not about the speech.
4. **Is the outright rank profile monotone?** If Sharpe rises steadily with contract rank, that is
   duration exposure, not a speech effect.
""")

code(r"""
summary = {
    "configs": int(len(grid)),
    "trials_priced_in": int(N_TRIALS),
    "sr_star_per_trade": float(grid["sr_star"].iloc[0]),
    "best_sharpe": float(grid["sharpe_ann"].max()),
    "best_dsr": float(grid["dsr"].max()),
    "alive_dsr_gt_95": int(((grid["dsr"] > 0.95) & (grid["trades"] >= 50)).sum()),
}
for k, v in summary.items():
    print(f"  {k:22s} {v}")

grid.drop(columns=["_returns"]).to_csv(CACHE / "grid_results.csv", index=False)
print(f"\nwrote {CACHE / 'grid_results.csv'}")
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
