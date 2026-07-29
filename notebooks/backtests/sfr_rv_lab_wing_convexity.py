# %% [markdown]
# # SR3 RV Lab — Framework 4: wing convexity harvest
#
# **RV class: A — within-contract shape.**
#
# Sell the OTM wing the market is paying up for, delta-hedge it daily, and keep
# the premium if the tail does not arrive. Three constructions, in increasing
# order of how much of the disaster you keep:
#
# 1. **naked wing + daily delta hedge** — the pure short-tail expression.
# 2. **wing vertical (disaster buyback)** — sell the near wing, buy the far one,
#    so the loss is capped at the strike distance. This is the `convergence.py`
#    "sell the meat / own the disaster" package in listed form.
# 3. **strangle** — both wings at once, delta-hedged, which removes the
#    directional tilt and leaves the smile's wing level.
#
# Signals are **premium-native**: the z-score of the listed wing premium itself
# (and of the wing-vertical price), never a model tail probability. The prior
# session's measurement stands — model-implied tail bases have sub-1-day
# half-lives and their P&L is anti-correlated with executable P&L.

# %%
CONFIG = dict(
    near_offset=0.25,         # near wing, percent from the forward
    far_offset=0.50,          # far wing (the disaster buyback)
    strike_tol=0.13,
    min_oi=100,
    min_tte=0.15,
    contracts_per_leg=100,
    cost_bp=2.5,
    mas=(1, 5, 10),
    zscore_windows=(60, 120),
    entry_zs=(1.0, 1.5, 2.0),
    exits=("t5", "t10", "t20"),
    directions=("fade", "momentum"),
)
CONFIG

# %%
import dataclasses
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
    Leg, Structure, add_event_distance, constant_maturity_slots, wing_panel,
)

pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 60)

lab = load_lab()
quotes, contracts = lab["quotes"], lab["contracts"]

# %%
wings = wing_panel(quotes, contracts,
                   offsets=(CONFIG["near_offset"], CONFIG["far_offset"]),
                   tol=CONFIG["strike_tol"], min_oi=CONFIG["min_oi"])
tte = constant_maturity_slots(contracts)[["as_of", "symbol", "tte", "cm_slot"]]
wings = wings.merge(tte, on=["as_of", "symbol"], how="left")
wings = wings[wings["tte"] >= CONFIG["min_tte"]]
n, f = f"{CONFIG['near_offset']:g}", f"{CONFIG['far_offset']:g}"
need = [f"hk{n}_bp", f"ct{n}_bp", f"hk{f}_bp", f"ct{f}_bp",
        f"hk{n}_K", f"ct{n}_K", f"hk{f}_K", f"ct{f}_K"]
wings = wings.dropna(subset=need)
wings = add_event_distance(wings)
print(f"wing panel: {len(wings)} rows, {wings['symbol'].nunique()} symbols")
print(wings.groupby("symbol")[[f"hk{n}_bp", f"ct{n}_bp", f"hk{f}_bp", f"ct{f}_bp"]]
      .median().round(2).to_string())

# %% [markdown]
# ## Signals
#
# * `hike_wing` / `cut_wing`: the listed premium of the single wing.
# * `wing_vertical`: the price of the near-minus-far wing spread — what the
#   disaster buyback actually costs.
# * `strangle`: both wings summed, the smile's wing level.

# %%
W = wings.rename(columns={"symbol": "key"}).copy()
W["hike_wing"] = W[f"hk{n}_bp"]
W["cut_wing"] = W[f"ct{n}_bp"]
W["wing_vertical"] = W[f"hk{n}_bp"] - W[f"hk{f}_bp"]
W["strangle"] = W[f"hk{n}_bp"] + W[f"ct{n}_bp"]
W["gate"] = True
print(W[["hike_wing", "cut_wing", "wing_vertical", "strangle"]]
      .describe().round(2).to_string())

KCOLS = W.set_index(["key", "as_of"])[
    [f"hk{n}_K", f"ct{n}_K", f"hk{f}_K", f"ct{f}_K"]].sort_index()


def _ks(key, date):
    try:
        r = KCOLS.loc[(key, date)]
    except KeyError:
        return None
    return r.iloc[0] if isinstance(r, pd.DataFrame) else r


def builder_naked(key, exec_date, direction):
    r = _ks(key, exec_date)
    if r is None:
        return None
    return Structure((Leg("option", key, 1.0, "P", float(r[f"hk{n}_K"])),),
                     label=f"hikewing {key}")


def builder_vertical(key, exec_date, direction):
    """Sell the near wing, own the far one — the disaster is bought back."""
    r = _ks(key, exec_date)
    if r is None:
        return None
    return Structure((Leg("option", key, 1.0, "P", float(r[f"hk{n}_K"])),
                      Leg("option", key, -1.0, "P", float(r[f"hk{f}_K"]))),
                     label=f"wingvert {key}")


def builder_strangle(key, exec_date, direction):
    r = _ks(key, exec_date)
    if r is None:
        return None
    return Structure((Leg("option", key, 1.0, "P", float(r[f"hk{n}_K"])),
                      Leg("option", key, 1.0, "C", float(r[f"ct{n}_K"]))),
                     label=f"strangle {key}")


BASE = LabConfig(lag=1, round_trip_cost_bp=CONFIG["cost_bp"],
                 contracts_per_leg=CONFIG["contracts_per_leg"],
                 delta_hedge="daily", future_leg_bp=0.25)
GRID = {"direction": list(CONFIG["directions"]), "ma": list(CONFIG["mas"]),
        "zscore_window": list(CONFIG["zscore_windows"]),
        "entry_min_zscore": list(CONFIG["entry_zs"]),
        "exit_style": list(CONFIG["exits"])}
PARAMS = ["direction", "ma", "zscore_window", "entry_min_zscore", "exit_style"]


def _sig(col):
    s = W[["key", "as_of", "gate", "days_to_fomc", col]].copy()
    s["signal"] = s[col]
    return s.dropna(subset=["signal"])


# %% [markdown]
# ## 4a — naked hike wing, delta-hedged daily

# %%
out_naked = run_framework(
    "4a. Wing harvest (naked, hedged)", signals=_sig("hike_wing"),
    book=lab["book"], builder=builder_naked, base=BASE, grid_spec=GRID,
    params=PARAMS, cls="A",
    note=f"single {CONFIG['near_offset']*100:.0f}bp hike wing, daily delta hedge")

# %% [markdown]
# ## 4b — wing vertical (sell the meat, own the disaster)

# %%
out_vert = run_framework(
    "4b. Wing vertical (disaster buyback)", signals=_sig("wing_vertical"),
    book=lab["book"], builder=builder_vertical, base=BASE, grid_spec=GRID,
    params=PARAMS, cls="A",
    note=f"sell {CONFIG['near_offset']*100:.0f}bp / own "
         f"{CONFIG['far_offset']*100:.0f}bp, loss capped at the strike distance")

# %% [markdown]
# ## 4c — strangle (wing level, no directional tilt)

# %%
out_str = run_framework(
    "4c. Strangle (wing level)", signals=_sig("strangle"), book=lab["book"],
    builder=builder_strangle, base=BASE, grid_spec=GRID, params=PARAMS, cls="A",
    note="both wings, delta-hedged daily")

# %% [markdown]
# ## FOMC conditioning
#
# Does the wing premium behave differently into a meeting? Entries restricted to
# the run-up, everything else unchanged.

# %%
ev = _sig("hike_wing")
ev["eligible"] = ev["days_to_fomc"].between(-7, -1)
print(f"eligible bars: {ev['eligible'].mean():.1%}")
out_ev = run_framework(
    "4d. Wing harvest (FOMC window)", signals=ev, book=lab["book"],
    builder=builder_naked, base=BASE,
    grid_spec={"direction": list(CONFIG["directions"]), "ma": [1, 5],
               "entry_min_zscore": [1.0, 1.5], "exit_style": ["t5", "t10"]},
    params=["direction", "ma", "entry_min_zscore", "exit_style"], cls="A",
    note="entries limited to 7 business days pre-FOMC", show_trades=0)
