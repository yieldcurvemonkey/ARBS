# %% [markdown]
# # SR3 RV Lab — Framework 5: the meeting lattice (curve-implied vs listed digitals)
#
# **RV class: D / B — what the options know that the curve does not.**
#
# This is the one framework where the comparison is genuinely between the two
# markets rather than between an option surface and itself.
#
# 1. From the **futures strip alone**, least-squares solve a per-meeting jump for
#    every FOMC date, using the exact day-weight matrix (SR3 settles on the
#    day-weighted average of its reference quarter, so a meeting inside the
#    quarter counts fractionally — a Dec-9 hike moves a Dec contract by roughly a
#    sixth of its size, not by 25bp).
# 2. Turn each jump into the FedWatch two-point lattice (`mantissa_probs`), couple
#    the meetings **independently**, and day-weight them into each contract's
#    settlement. That gives `P_null(rate >= K)` — a distribution that reproduces
#    the futures market by construction and contains no option information.
# 3. Compare with the **listed** `P(rate >= K)` read off the traded vertical.
#
# The gap is the price of everything the null throws away: marginal shape, tails,
# non-25bp outcomes, intermeeting risk and meeting-to-meeting coupling. It is a
# risk premium, so its *level* is not a trade — its **deviation from its own
# history** is what gets tested here, and the trade is the listed vertical.

# %%
CONFIG = dict(
    offsets_bp=(-25.0, 0.0, 25.0),   # strikes relative to each contract's forward
    strike_tol=0.10,
    min_oi=100,
    min_tte=0.15,
    contracts_per_leg=100,
    cost_bp=1.5,                      # 2 option legs -> a vertical is cheap
    mas=(1, 5, 10),
    zscore_windows=(60, 120),
    entry_zs=(1.0, 1.5, 2.0),
    exits=("t5", "t10", "z0"),
    directions=("fade", "momentum"),
)
CONFIG

# %%
import datetime
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.append("../../")
sys.path.append(str(Path.cwd()))

import matplotlib
if "ipykernel" not in sys.modules:
    matplotlib.use("Agg")
import matplotlib.pyplot as plt

from sfr_rv_lab_common import LabConfig, load_lab, run_framework
from RVUtils.SFRRVLab import (
    FOMC_DATES, Leg, Structure, add_event_distance, constant_maturity_slots,
    quarterly_sort_key, vertical_digital,
)
from RVUtils.SFRRVLab.lattice import (
    day_weight_matrix, meeting_null_distribution, null_prob_ge,
    solve_meeting_jumps,
)
from RVUtils.SFRRVLab.signals import digital_legs
from MDP.STIRFutures._sofr_option_contracts import quarterly_reference_window

pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 60)

lab = load_lab()
quotes, contracts = lab["quotes"], lab["contracts"]
# `contracts` already carries tte from the panel builder; only the slot is new
contracts = contracts.merge(
    constant_maturity_slots(contracts)[["as_of", "symbol", "cm_slot"]],
    on=["as_of", "symbol"], how="left")

WINDOWS = {s: quarterly_reference_window(s)
           for s in sorted(contracts["symbol"].unique(), key=quarterly_sort_key)}
for s, w in WINDOWS.items():
    print(f"  {s}: reference quarter {w[0]} .. {w[1]}")

# %% [markdown]
# ## Step 1-2 — the curve-only null, per date
#
# The base rate is the front contract's own forward: with the front quarter
# largely already fixed, it anchors the level the meeting jumps move away from.

# %%
fwd = contracts.set_index(["as_of", "symbol"])["forward_rate"]
fwd_px = contracts.set_index(["as_of", "symbol"])["forward_price"]
QDAY = {k: v for k, v in quotes.groupby(["as_of", "symbol"], sort=False)}

rows = []
for ts, day in contracts.groupby("as_of"):
    day = day[day["tte"] >= CONFIG["min_tte"]].sort_values("expiry_date")
    syms = [s for s in day["symbol"] if s in WINDOWS]
    if len(syms) < 3:
        continue
    wins = [WINDOWS[s] for s in syms]
    d0 = ts.date()
    meetings = [m for m in FOMC_DATES if d0 < m <= max(w[1] for w in wins)]
    if not meetings:
        continue
    W = day_weight_matrix(wins, meetings)
    fwd_bp = np.array([float(fwd[(ts, s)]) * 100.0 for s in syms])
    base_bp = float(fwd_bp[0])
    jumps = solve_meeting_jumps(fwd_bp, W, base_bp)
    for i, sym in enumerate(syms):
        off, p = meeting_null_distribution(jumps, W[i], merge_bp=0.5)
        g = QDAY.get((ts, sym))
        if g is None:
            continue
        if CONFIG["min_oi"] > 0:
            g = g[g["oi"] >= CONFIG["min_oi"]]
        f_rate = float(fwd[(ts, sym)])
        f_px = float(fwd_px[(ts, sym)])
        for o in CONFIG["offsets_bp"]:
            k_rate = f_rate + o / 100.0
            d = vertical_digital(g, k_rate, tol=CONFIG["strike_tol"],
                                 forward_price=f_px)
            if d is None:
                continue
            p_null = null_prob_ge(off, p, base_bp, k_rate * 100.0)
            rows.append({
                "as_of": ts, "symbol": sym, "offset_bp": o,
                "key": f"{sym}@{o:+.0f}",
                "p_listed": d["prob"], "p_null": p_null,
                "signal": d["prob"] - p_null,
                "k_lo": d["k_lo"], "k_hi": d["k_hi"], "right": d["right"],
                "n_meetings": len(meetings), "gate": True,
            })
lat = pd.DataFrame(rows)
print(f"\nlattice panel (raw): {len(lat)} rows")

# Hygiene: a normalised vertical is a probability. Values outside [0, 1] mean a
# stale settle or a bracket that straddles the OTM boundary with mismatched
# widths — not information. Drop them and say how many.
if len(lat):
    bad = ~lat["p_listed"].between(-0.02, 1.02)
    print(f"dropping {int(bad.sum())} rows ({bad.mean():.2%}) whose listed "
          f"vertical implies a probability outside [0, 1]")
    lat = lat[~bad].copy()
print(f"lattice panel: {len(lat)} rows, {lat['key'].nunique() if len(lat) else 0} keys")
if len(lat):
    lat = add_event_distance(lat)
    print(lat.groupby("offset_bp")[["p_listed", "p_null", "signal"]]
          .describe().round(3).to_string())

# %% [markdown]
# ### The gap is a premium, not an arbitrage
#
# If the options systematically price more tail than the two-point lattice, the
# gap has a persistent sign. That level is the price of the information the null
# discards; only the deviation from it is a candidate trade.

# %%
if len(lat):
    print("mean gap (listed - null) by strike offset:")
    print(lat.groupby("offset_bp")["signal"].agg(["mean", "std", "count"])
          .round(4).to_string())
    print("\nHow much of the gap's VARIATION is the options side rather than the "
          "null? If the null is near-degenerate at a strike, the 'gap' signal is "
          "just the listed digital wearing a different name:")
    print(lat.groupby("offset_bp")[["p_listed", "p_null"]].std().round(4).to_string())
    fig, axes = plt.subplots(1, 2, figsize=(13, 4))
    for o, sub in lat.groupby("offset_bp"):
        s = sub.groupby("as_of")["signal"].mean()
        axes[0].plot(s.index, s.to_numpy(), lw=1.1, label=f"{o:+.0f}bp")
    axes[0].axhline(0, color="grey", lw=0.8)
    axes[0].legend(fontsize=8)
    axes[0].set_title("listed P(>=K) minus curve-only lattice null", fontsize=10)
    axes[0].grid(alpha=0.25)
    axes[1].scatter(lat["p_null"], lat["p_listed"], s=4, alpha=0.3)
    axes[1].plot([0, 1], [0, 1], color="grey", ls="--", lw=1)
    axes[1].set_xlabel("null P(>=K)")
    axes[1].set_ylabel("listed P(>=K)")
    axes[1].set_title("options vs the FedWatch-style null", fontsize=10)
    axes[1].grid(alpha=0.25)
    fig.autofmt_xdate()
    fig.tight_layout()
    plt.show()

# %% [markdown]
# ## Step 3 — trade the deviation, as the listed vertical

# %%
LAT_IDX = lat.set_index(["key", "as_of"]).sort_index() if len(lat) else None


def builder(key, exec_date, direction):
    try:
        r = LAT_IDX.loc[(key, exec_date)]
    except (KeyError, AttributeError):
        return None
    if isinstance(r, pd.DataFrame):
        r = r.iloc[0]
    sym = key.split("@")[0]
    return Structure(digital_legs(sym, float(r["k_lo"]), float(r["k_hi"]),
                                  str(r["right"]), weight=1.0),
                     label=f"digital {key}")


BASE = LabConfig(lag=1, round_trip_cost_bp=CONFIG["cost_bp"],
                 contracts_per_leg=CONFIG["contracts_per_leg"],
                 delta_hedge="daily", future_leg_bp=0.25)
GRID = {"direction": list(CONFIG["directions"]), "ma": list(CONFIG["mas"]),
        "zscore_window": list(CONFIG["zscore_windows"]),
        "entry_min_zscore": list(CONFIG["entry_zs"]),
        "exit_style": list(CONFIG["exits"])}
PARAMS = ["direction", "ma", "zscore_window", "entry_min_zscore", "exit_style"]

if len(lat):
    out = run_framework(
        "5. Meeting lattice (listed vs FedWatch null)", signals=lat,
        book=lab["book"], builder=builder, base=BASE, grid_spec=GRID,
        params=PARAMS, cls="D/B",
        note="listed vertical, delta-hedged daily; null solved from the strip")

# %% [markdown]
# ## FOMC-window variant
#
# The null is a *meeting* model, so if it carries information at all it should
# carry it around meetings.

# %%
if len(lat):
    ev = lat.copy()
    ev["eligible"] = ev["days_to_fomc"].between(-7, -1)
    print(f"eligible bars: {ev['eligible'].mean():.1%}")
    out_ev = run_framework(
        "5b. Meeting lattice (FOMC window)", signals=ev, book=lab["book"],
        builder=builder, base=BASE,
        grid_spec={"direction": list(CONFIG["directions"]), "ma": [1, 5],
                   "entry_min_zscore": [1.0, 1.5], "exit_style": ["t5", "t10"]},
        params=["direction", "ma", "entry_min_zscore", "exit_style"], cls="D/B",
        note="entries limited to 7 business days pre-FOMC", show_trades=0)
