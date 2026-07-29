# %% [markdown]
# # SR3 RV Lab — Framework 6: curvature vs vol, and the vol surface's own shape
#
# **RV class: A / C.**
#
# Three related questions, all marked on listed prices:
#
# * **6a Fly vs straddle** — the futures butterfly prices the *velocity* of the
#   policy path; the belly straddle prices its *dispersion*. Both are claims on
#   the same random path but neither pins the other, so their relative richness
#   is a real basis. The package is the belly straddle against the `+1/-2/+1`
#   futures fly, delta-hedged daily so the straddle's own direction is removed.
# * **6b Vol butterfly** — `½(hike_iv + cut_iv) - atm_iv`, the smile's curvature
#   in listed normal-vol terms, traded as a strangle against a vega-matched
#   straddle. Bimodal policy pricing bids the wings; a diffuse path bids the ATM.
# * **6c Skew term structure** — the risk reversal *in vol space* differenced
#   across adjacent expiries: does hike/cut skew live in the near window or the
#   far one, and does the spread revert or trend?

# %%
CONFIG = dict(
    wing_offset=0.25,
    strike_tol=0.13,
    min_oi=100,
    min_tte=0.15,
    contracts_per_leg=100,
    cost_bp=2.5,
    mas=(1, 5, 10),
    zscore_windows=(60, 120),
    entry_zs=(1.0, 1.5, 2.0),
    exits=("t5", "t10", "z0"),
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
    Leg, Structure, add_event_distance, atm_premium_panel,
    constant_maturity_slots, contract_pairs, quarterly_sort_key, vol_smile_panel,
)

pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 60)

lab = load_lab()
quotes, contracts = lab["quotes"], lab["contracts"]
tte = constant_maturity_slots(contracts)[["as_of", "symbol", "tte", "cm_slot"]]

atm = atm_premium_panel(quotes, contracts).merge(tte, on=["as_of", "symbol"])
atm = atm[atm["tte"] >= CONFIG["min_tte"]]
vs = vol_smile_panel(quotes, contracts, offset=CONFIG["wing_offset"],
                     tol=CONFIG["strike_tol"], min_oi=CONFIG["min_oi"])
vs = vs.merge(tte, on=["as_of", "symbol"])
vs = vs[vs["tte"] >= CONFIG["min_tte"]]
print(f"atm rows {len(atm)}   vol-smile rows {len(vs)}")
print(vs.groupby("symbol")[["atm_iv_bp", "rr_iv_bp", "fly_iv_bp"]].median()
      .round(2).to_string())

# %% [markdown]
# ## 6a — fly vs straddle
#
# `signal = z(fly_bp) - z(belly straddle premium)`: the futures fly rich against
# the belly's option-implied dispersion. Sign convention is the desk one,
# `fly = 2*belly - front - back` in bp (note `BT/signals/sfr_cal_spread_rv.
# compute_fly_curve` uses the opposite sign).

# %%
SYMS = sorted(contracts["symbol"].unique(), key=quarterly_sort_key)
TRIPLES = [(SYMS[i], SYMS[i + 1], SYMS[i + 2]) for i in range(len(SYMS) - 2)]
fwd = contracts.set_index(["as_of", "symbol"])["forward_rate"]
atm_idx = atm.set_index(["as_of", "symbol"])

rows = []
for a, b, c in TRIPLES:
    dates = sorted(set(atm_idx.xs(b, level="symbol").index))
    for ts in dates:
        try:
            fa, fb, fc = (float(fwd[(ts, a)]), float(fwd[(ts, b)]),
                          float(fwd[(ts, c)]))
            st = atm_idx.loc[(ts, b)]
        except KeyError:
            continue
        rows.append({
            "as_of": ts, "key": f"{a}-{b}-{c}", "front": a, "belly": b, "back": c,
            "fly_bp": (2 * fb - fa - fc) * 100.0,
            "straddle_bp": float(st["atm_straddle_bp"]),
            "belly_strike": float(st["atm_strike"]),
        })
fly = pd.DataFrame(rows)
if not fly.empty:
    g = fly.groupby("key")
    fly["fly_z"] = g["fly_bp"].transform(
        lambda s: (s - s.rolling(120, min_periods=40).mean())
        / s.rolling(120, min_periods=40).std(ddof=0))
    fly["str_z"] = g["straddle_bp"].transform(
        lambda s: (s - s.rolling(120, min_periods=40).mean())
        / s.rolling(120, min_periods=40).std(ddof=0))
    fly["signal"] = fly["fly_z"] - fly["str_z"]
    fly["gate"] = True
    fly = add_event_distance(fly.dropna(subset=["signal"]))
print(f"fly-vs-straddle rows: {len(fly)}  triples: "
      f"{fly['key'].nunique() if len(fly) else 0}")

# %%
FLY_IDX = fly.set_index(["key", "as_of"]).sort_index() if len(fly) else None


def builder_fly_straddle(key, exec_date, direction):
    """Belly straddle against the +1/-2/+1 futures fly, delta-hedged daily."""
    try:
        r = FLY_IDX.loc[(key, exec_date)]
    except (KeyError, AttributeError):
        return None
    if isinstance(r, pd.DataFrame):
        r = r.iloc[0]
    a, b, c = key.split("-")
    k = float(r["belly_strike"])
    return Structure((
        Leg("option", b, -1.0, "C", k), Leg("option", b, -1.0, "P", k),
        Leg("future", b, -2.0), Leg("future", a, 1.0), Leg("future", c, 1.0),
    ), label=f"flyVstraddle {key}")


BASE = LabConfig(lag=1, round_trip_cost_bp=CONFIG["cost_bp"],
                 contracts_per_leg=CONFIG["contracts_per_leg"],
                 delta_hedge="daily", future_leg_bp=0.25)
GRID = {"direction": list(CONFIG["directions"]), "ma": list(CONFIG["mas"]),
        "zscore_window": list(CONFIG["zscore_windows"]),
        "entry_min_zscore": list(CONFIG["entry_zs"]),
        "exit_style": list(CONFIG["exits"])}
PARAMS = ["direction", "ma", "zscore_window", "entry_min_zscore", "exit_style"]

if len(fly):
    out_fly = run_framework(
        "6a. Fly vs belly straddle", signals=fly, book=lab["book"],
        builder=builder_fly_straddle, base=BASE, grid_spec=GRID, params=PARAMS,
        cls="A/C", note="futures fly against the belly straddle, hedged daily")

# %% [markdown]
# ## 6b — vol butterfly (smile curvature)
#
# Strangle against a vega-matched straddle. With both wings at the same offset
# and near-equal vega, a 1:1 strangle-vs-straddle is the listed approximation;
# the residual vega is small relative to the cost of refining it.

# %%
V = vs.rename(columns={"symbol": "key"}).copy()
V["gate"] = True
V = add_event_distance(V)
sig_flyiv = V[["key", "as_of", "gate", "days_to_fomc", "fly_iv_bp",
               "forward_rate"]].copy()
sig_flyiv["signal"] = sig_flyiv["fly_iv_bp"]

# strikes: re-derive from the forward exactly as vol_smile_panel did
from RVUtils.SFRRVLab import pick_listed_strike
QDAY = {k: v for k, v in quotes.groupby(["as_of", "symbol"], sort=False)}


def _smile_strikes(key, date):
    g = QDAY.get((pd.Timestamp(date), key))
    if g is None:
        return None
    f = fwd.get((pd.Timestamp(date), key))
    if f is None or not np.isfinite(f):
        return None
    atm_c = pick_listed_strike(g, "C", f, tol=CONFIG["strike_tol"])
    atm_p = pick_listed_strike(g, "P", f, tol=CONFIG["strike_tol"])
    hk = pick_listed_strike(g, "P", f + CONFIG["wing_offset"],
                            tol=CONFIG["strike_tol"])
    ct = pick_listed_strike(g, "C", f - CONFIG["wing_offset"],
                            tol=CONFIG["strike_tol"])
    if any(x is None for x in (atm_c, atm_p, hk, ct)):
        return None
    return (float(atm_c["strike_price"]), float(atm_p["strike_price"]),
            float(hk["strike_price"]), float(ct["strike_price"]))


def builder_vol_fly(key, exec_date, direction):
    ks = _smile_strikes(key, exec_date)
    if ks is None:
        return None
    kc, kp, khk, kct = ks
    return Structure((
        Leg("option", key, 1.0, "P", khk), Leg("option", key, 1.0, "C", kct),
        Leg("option", key, -1.0, "C", kc), Leg("option", key, -1.0, "P", kp),
    ), label=f"volfly {key}")


out_volfly = run_framework(
    "6b. Vol butterfly (smile curvature)", signals=sig_flyiv, book=lab["book"],
    builder=builder_vol_fly, base=BASE, grid_spec=GRID, params=PARAMS, cls="A",
    note="strangle vs straddle, delta-hedged daily")

# %% [markdown]
# ## 6c — skew term structure (risk reversal in vol space, across expiries)

# %%
vidx = V.set_index(["as_of", "key"])["rr_iv_bp"].sort_index()
rows = []
for front, back in contract_pairs(SYMS, gaps=(1, 2)):
    try:
        f = vidx.xs(front, level="key")
        b = vidx.xs(back, level="key")
    except KeyError:
        continue
    j = pd.concat([f.rename("f"), b.rename("b")], axis=1).dropna()
    if j.empty:
        continue
    rows.append(pd.DataFrame({
        "as_of": j.index, "key": f"{front}-{back}", "front": front, "back": back,
        "signal": (j["b"] - j["f"]).to_numpy(), "gate": True}))
skew_ts = (pd.concat(rows, ignore_index=True) if rows else pd.DataFrame())
if len(skew_ts):
    skew_ts = add_event_distance(skew_ts)
print(f"skew term-structure rows: {len(skew_ts)}")


def builder_skew_ts(key, exec_date, direction):
    """Back-expiry risk reversal against the front's, delta-hedged daily."""
    front, back = key.split("-")
    kf = _smile_strikes(front, exec_date)
    kb = _smile_strikes(back, exec_date)
    if kf is None or kb is None:
        return None
    return Structure((
        Leg("option", back, 1.0, "P", kb[2]), Leg("option", back, -1.0, "C", kb[3]),
        Leg("option", front, -1.0, "P", kf[2]), Leg("option", front, 1.0, "C", kf[3]),
    ), label=f"skewTS {key}")


if len(skew_ts):
    out_skew = run_framework(
        "6c. Skew term structure (vol space)", signals=skew_ts, book=lab["book"],
        builder=builder_skew_ts, base=BASE, grid_spec=GRID, params=PARAMS,
        cls="A/B", note="RR(back) - RR(front) in listed normal vol, hedged daily")
