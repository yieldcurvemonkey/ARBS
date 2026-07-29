# %% [markdown]
# # SFR Fly Mean-Reversion — 7. Cross-sectional rank
#
# **Formulation: rank the flies against each other, not against their own past.**
#
# This is the framework the prior work says should win. `FINDINGS_kink_fade.md`
# (250 dates, 2025-05 → 2026-05, 44 flies) measured a within-gap cross-sectional
# IC of the fly level against the forward change of **−0.27 (t = −8.3)** at
# h = 21, with a naive long/short fade at IR ≈ **+1.35** and a non-overlapping
# Sharpe of **+1.97** — while the options-implied signal added nothing. That was
# one regime, one year, and gross of costs (`QueryDrivenBacktest` charges
# `fee = 0.0`). This notebook re-runs it on 4.6 and 7.6 years, with costs.
#
# Two accountings are reported side by side, because they are not the same claim:
#
# * **`ls_fade`** — the prior-art function reproduced faithfully: daily
#   cross-sectional terciles, forward Δfly at horizon `h`, cost charged *per
#   date*, IR annualised, plus the non-overlapping Sharpe. This is the number
#   comparable to the prior verdict.
# * **the engine** — discrete trades with lag-1 fills, a round trip charged once
#   per completed trade, and the same verdict machinery as every other framework.
#
# Standardisation is **within pack** (whites 1-4, reds 5-8, greens 9-12, blues
# 13-16). Pooling raw levels across the strip would rank maturity, not richness:
# `SFR123` has a 15.7bp standard deviation and `SFR-14-15-16` has 0.5bp.

# %%
CONFIG = dict(
    primary_structure="3m",
    primary_window="liquid16",
    long_window="front8",
    cost_bp=1.5,
    n_packages=100,
    horizons=(5, 21, 63),
    frac=0.33,
    xs_windows=(0, 60, 120),         # 0 = rank the RAW LEVEL (the prior art)
    methods=("zscore", "rank"),
    entry_zs=(0.8, 1.2, 1.6),
    exits=("z0", "t5", "t21"),
    directions=("fade", "momentum"),
    max_hold=30,
    lag=1,
)
CONFIG

# %%
import sys
from pathlib import Path

sys.path.append("../../")
sys.path.append(str(Path.cwd()))

import math

import numpy as np
import pandas as pd

import matplotlib
if "ipykernel" not in sys.modules:
    matplotlib.use("Agg")
import matplotlib.pyplot as plt

from RVUtils.MeanRev import MRConfig
from RVUtils.MeanRev.signals import xsection_signal
from sfr_fly_meanrev_common import load_lab, per_slot_table, run_family

pd.set_option("display.width", 230)
pd.set_option("display.max_columns", 60)

BASE = MRConfig(lag=CONFIG["lag"], round_trip_cost_bp=CONFIG["cost_bp"],
                max_hold=CONFIG["max_hold"], n_packages=CONFIG["n_packages"])
lab = load_lab(CONFIG["primary_structure"], CONFIG["primary_window"])
levels, st = lab["levels"], lab["struct"]
packs = st.drop_duplicates("key").set_index("key")["pack"]
packs = packs.reindex(levels.columns)
print(f"{levels.shape[1]} flies, {levels.shape[0]} sessions")
print(f"packs: {packs.value_counts().to_dict()}")


# %% [markdown]
# ## 1. Prior-art functions, reproduced
#
# `nw_t` and `ls_fade` are the versions from
# `notebooks/backtests/SFR_screeners/kink_fade_backtest.py`, kept bug-for-bug so
# the numbers are comparable: the Bartlett kernel uses population gammas, `ir`
# mixes the overlapping mean with the non-overlapping standard deviation, and
# `cost_bps` is charged as `2 * cost_bps` on **every date**.

# %%
def nw_t(x, lag):
    """Newey-West t-stat of the mean (kink_fade_backtest.py:124)."""
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 3:
        return np.nan
    e = x - x.mean()
    var = (e @ e) / n
    for l in range(1, min(lag, n - 1) + 1):
        w = 1 - l / (lag + 1)
        var += 2 * w * (e[l:] @ e[:-l]) / n
    return x.mean() / (math.sqrt(var / n) + 1e-12)


def build_panel(levels, packs, horizons):
    """Long panel with forward changes, built on a per-key business-day ordinal
    so Delta at t+h is the SAME fixed-contract fly h sessions later."""
    frames = []
    for c in levels.columns:
        s = levels[c].dropna()
        d = pd.DataFrame({"date": s.index, "key": c, "fly": s.to_numpy(),
                          "pack": packs.get(c)})
        for h in horizons:
            d[f"dfly_{h}"] = s.shift(-h).to_numpy() - s.to_numpy()
        frames.append(d)
    return pd.concat(frames, ignore_index=True)


def zwithin(df, col, by):
    g = df.groupby(by)[col]
    return (df[col] - g.transform("mean")) / (g.transform("std") + 1e-12)


def xs_ic(panel, sig, h, within=True):
    rows = []
    for d, g in panel.dropna(subset=[sig, f"dfly_{h}"]).groupby("date"):
        if within:
            vals = []
            for _, gg in g.groupby("pack"):
                if len(gg) >= 3 and gg[sig].nunique() >= 3:
                    vals.append(gg[[sig, f"dfly_{h}"]].corr(method="spearman").iloc[0, 1])
            if vals:
                rows.append(np.mean(vals))
        else:
            if len(g) >= 5 and g[sig].nunique() >= 5:
                rows.append(g[[sig, f"dfly_{h}"]].corr(method="spearman").iloc[0, 1])
    a = np.asarray(rows, float)
    a = a[np.isfinite(a)]
    if a.size < 3:
        return {}
    return {"IC": a.mean(), "t": a.mean() / (a.std(ddof=1) + 1e-12) * math.sqrt(a.size),
            "n_dates": a.size, "hit": float((a < 0).mean())}


def ls_fade(panel, sig, h, frac=0.33, within_pack=True, cost_bps=0.0):
    """Daily cross-sectional fade: short the top-frac signal, long the bottom."""
    df = panel.dropna(subset=[sig, f"dfly_{h}"]).copy()

    def one_book(g):
        if len(g) < 3 or g[sig].nunique() < 3:
            return None
        k = max(1, int(len(g) * frac))
        order = g[sig].rank(method="first")
        longs, shorts = g[order <= k], g[order > len(g) - k]
        return (longs[f"dfly_{h}"].mean() - shorts[f"dfly_{h}"].mean())

    recs = []
    for d, g in df.groupby("date"):
        if within_pack:
            books = [b for b in (one_book(gg) for _, gg in g.groupby("pack"))
                     if b is not None]
            if not books:
                continue
            pnl = float(np.mean(books))
        else:
            pnl = one_book(g)
            if pnl is None:
                continue
        recs.append({"date": d, "pnl": pnl - cost_bps * 2.0})
    if len(recs) < 3:
        return None
    s = pd.DataFrame(recs).set_index("date").sort_index()
    ppy = 252.0 / h
    nonover = s.iloc[::h]
    mean = s["pnl"].mean()
    sd = nonover["pnl"].std(ddof=1) if len(nonover) > 2 else s["pnl"].std(ddof=1)
    cum = s["pnl"].cumsum()
    return {"series": s, "n": len(s), "mean": mean,
            "ir": mean * ppy / (sd * math.sqrt(ppy) + 1e-12),
            "hit": float((s["pnl"] > 0).mean()),
            "maxdd": float((cum - cum.cummax()).min()),
            "nonover": (float(nonover["pnl"].mean() / (nonover["pnl"].std(ddof=1) + 1e-12)
                              * math.sqrt(ppy)) if len(nonover) > 2 else np.nan),
            "nw_t": nw_t(s["pnl"].to_numpy(), h)}


panel = build_panel(levels, packs, CONFIG["horizons"])
print(f"panel {panel.shape}, {panel['date'].nunique()} dates")

# %% [markdown]
# ## 2. Does the fly level predict its own forward change?
#
# The prior verdict to reproduce: within-gap IC of −0.27 (t = −8.3) at h = 21.

# %%
rows = []
for h in CONFIG["horizons"]:
    r = xs_ic(panel, "fly", h, within=True)
    if r:
        rows.append({"h": h, "scope": "within pack", **r})
    r = xs_ic(panel, "fly", h, within=False)
    if r:
        rows.append({"h": h, "scope": "pooled", **r})
ic = pd.DataFrame(rows)
print("cross-sectional IC of the fly LEVEL vs its forward change:")
print(ic.round(4).to_string(index=False))
print("\n  a NEGATIVE IC is mean reversion: a rich fly subsequently falls.")

# %% [markdown]
# ## 3. `ls_fade` — the prior-art long/short book, with and without costs
#
# `cost_bps` is per side per date in this accounting, so `0.75` is the 1.5bp
# package round trip charged on every date the book is held.

# %%
rows = []
for h in CONFIG["horizons"]:
    for cost in (0.0, 0.25, 0.75):
        r = ls_fade(panel, "fly", h, frac=CONFIG["frac"], cost_bps=cost)
        if r is None:
            continue
        rows.append({"h": h, "cost_bps_per_side": cost, "n_dates": r["n"],
                     "mean_bp": r["mean"], "IR": r["ir"], "hit": r["hit"],
                     "maxdd_bp": r["maxdd"], "nonover_sharpe": r["nonover"],
                     "nw_t": r["nw_t"]})
lsf = pd.DataFrame(rows)
print(lsf.round(3).to_string(index=False))
print("\n  IR at cost 0 is the prior-art comparable; the 0.75 row is the honest one.")

# %%
fig, ax = plt.subplots(figsize=(12, 4))
for h in CONFIG["horizons"]:
    r = ls_fade(panel, "fly", h, frac=CONFIG["frac"], cost_bps=0.0)
    if r is None:
        continue
    ax.plot(r["series"].index, r["series"]["pnl"].cumsum().to_numpy(), lw=1.3,
            label=f"h={h}, gross")
    r2 = ls_fade(panel, "fly", h, frac=CONFIG["frac"], cost_bps=0.75)
    if r2 is not None:
        ax.plot(r2["series"].index, r2["series"]["pnl"].cumsum().to_numpy(),
                lw=1.0, ls="--", alpha=0.8, label=f"h={h}, net 1.5bp/day")
ax.axhline(0, color="grey", lw=0.8)
ax.set_title("cross-sectional fade book — cumulative bp (overlapping, so the "
             "level is not a tradeable equity curve)", fontsize=11)
ax.legend(fontsize=8, ncol=2)
ax.grid(alpha=0.25)
fig.tight_layout()
plt.show()

# %% [markdown]
# ## 4. Regime split of the cross-sectional book
#
# The prior work covered one mild-easing year. This is the same book across four
# policy regimes.

# %%
reg = lab["regimes"]
rows = []
for h in CONFIG["horizons"]:
    r = ls_fade(panel, "fly", h, frac=CONFIG["frac"], cost_bps=0.0)
    if r is None:
        continue
    s = r["series"]["pnl"]
    rr = reg.reindex(s.index).ffill()
    for name in ["ZIRP", "HIKING", "PLATEAU", "CUTTING"]:
        sub = s[rr == name]
        if len(sub) < 20:
            continue
        ppy = 252.0 / h
        non = sub.iloc[::h]
        sd = non.std(ddof=1) if len(non) > 2 else sub.std(ddof=1)
        rows.append({"h": h, "regime": name, "n_dates": len(sub),
                     "mean_bp": sub.mean(),
                     "IR": sub.mean() * ppy / (sd * math.sqrt(ppy) + 1e-12),
                     "hit": float((sub > 0).mean())})
print(pd.DataFrame(rows).round(3).to_string(index=False))

# %% [markdown]
# ## 5. The same idea through the engine, with per-trade costs

# %%
def xs_sig(L, xs_window, method):
    return xsection_signal(L, groups=packs, method=method, window=xs_window,
                           min_names=3)


GRID = {"xs_window": CONFIG["xs_windows"], "method": CONFIG["methods"],
        "entry_z": CONFIG["entry_zs"], "exit_style": CONFIG["exits"],
        "direction": CONFIG["directions"]}
PARAMS = ["xs_window", "method", "entry_z", "exit_style", "direction"]
out = run_family("7. Cross-sectional rank (3m, liquid16)", lab=lab,
                 signal_fn=xs_sig, grid_spec=GRID, params=PARAMS, base=BASE,
                 cls="xsection",
                 note="within-pack standardisation, then pooled; per-trade costs")

# %%
per = per_slot_table(out["result"], lab)
if not per.empty:
    print(per.round(3).to_string(index=False))

# %% [markdown]
# ## 6. Long window — the sample-composition test

# %%
lab8 = load_lab(CONFIG["primary_structure"], CONFIG["long_window"])
packs8 = (lab8["struct"].drop_duplicates("key").set_index("key")["pack"]
          .reindex(lab8["levels"].columns))
panel8 = build_panel(lab8["levels"], packs8, CONFIG["horizons"])
rows = []
for h in CONFIG["horizons"]:
    for cost in (0.0, 0.75):
        r = ls_fade(panel8, "fly", h, frac=CONFIG["frac"], cost_bps=cost)
        if r is None:
            continue
        rows.append({"h": h, "cost_bps_per_side": cost, "n_dates": r["n"],
                     "mean_bp": r["mean"], "IR": r["ir"],
                     "nonover_sharpe": r["nonover"], "nw_t": r["nw_t"]})
print("ls_fade on the 2019+ front-8 panel:")
print(pd.DataFrame(rows).round(3).to_string(index=False))

# %%
out8 = run_family("7b. Cross-sectional rank (3m, front8, 2019+)", lab=lab8,
                  signal_fn=lambda L, xs_window, method: xsection_signal(
                      L, groups=packs8, method=method, window=xs_window,
                      min_names=3),
                  grid_spec=GRID, params=PARAMS, base=BASE, cls="xsection",
                  note="long history")

# %% [markdown]
# ## 7. 6m flies

# %%
lab6 = load_lab("6m", CONFIG["primary_window"])
packs6 = (lab6["struct"].drop_duplicates("key").set_index("key")["pack"]
          .reindex(lab6["levels"].columns))
out6 = run_family("7c. Cross-sectional rank (6m, liquid16)", lab=lab6,
                  signal_fn=lambda L, xs_window, method: xsection_signal(
                      L, groups=packs6, method=method, window=xs_window,
                      min_names=3),
                  grid_spec=GRID, params=PARAMS, base=BASE, cls="xsection",
                  note="6m flies")
