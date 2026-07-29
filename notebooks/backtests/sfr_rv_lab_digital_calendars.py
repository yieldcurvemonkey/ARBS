# %% [markdown]
# # SR3 RV Lab — Framework 2: same-strike calendar digitals (the coupling basis)
#
# **RV class: B — cross-contract coupling.**
#
# For two expiries and one common *rate* strike `K`, price the listed vertical
# on each contract and normalise it to `P(rate >= K)`. The **digital calendar**
# is `cal(K) = P_back(>=K) - P_front(>=K)`: the listed price of "the rate crosses
# K between the front expiry and the back expiry".
#
# ### What is pinned, and what is free
#
# For a non-negative rate, `E[f] = ∫_0^∞ P(f >= K) dK`, so
#
# ```
# ∫ [P_back(>=K) - P_front(>=K)] dK  =  E[f_back] - E[f_front]  =  the futures calendar spread
# ```
#
# The **level** of the calendar-digital profile is therefore pinned by the linear
# market — exactly the "no mean-level RV" rule. What is *not* pinned is **where
# across strikes that spread sits**. That shape is the coupling content, and it
# is what this notebook trades. The first analysis cell verifies the identity
# numerically on real data rather than asserting it.
#
# The tradeable object at a single strike is a 4-leg package (one vertical per
# contract), scaled to one unit of probability: a 6.25bp vertical trades 16 lots
# a side, a 25bp vertical 4 lots — always whole CME lots — so the package marks
# at `100 x cal` bp.

# %%
CONFIG = dict(
    offsets=(-0.25, 0.0, 0.25),   # rate offsets from the front contract's forward
    strike_tol=0.10,              # max |target - bracket midpoint|, percent
    min_oi=100,
    pair_gaps=(1, 2),
    contracts_per_leg=100,
    cost_bp=2.5,                  # 4 option legs -> taker cost is generous here
    mas=(1, 5, 10),
    zscore_windows=(60, 120),
    entry_zs=(1.5, 2.0, 2.5),
    exits=("z0", "half", "t10"),
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

from sfr_rv_lab_common import (
    LabConfig, config_from_row, cost_block, exit_comparison, grid_block,
    header_block, league_row, load_lab, marks_x_lag_panel, median_row,
    stability_block, three_panel_equity,
)
from RVUtils.SFRRVLab import (
    Leg, Structure, add_event_distance, contract_pairs, digital_calendar_panel,
    digital_legs, grid_search, hedge_each_contract, mark_structure,
    package_contracts, run_backtest, vertical_digital,
)

pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 80)

lab = load_lab()
quotes, contracts = lab["quotes"], lab["contracts"]

# %% [markdown]
# ## Step 1 — verify the level constraint on real data
#
# Integrate the listed digital profile across the whole quoted strike ladder and
# compare with the futures calendar spread. Agreement is the proof that only the
# *shape* of this profile can carry relative value.

# %%
PAIRS = contract_pairs(sorted(contracts["symbol"].unique()), gaps=(1,))
fwd = contracts.set_index(["as_of", "symbol"])["forward_rate"]
fwd_px = contracts.set_index(["as_of", "symbol"])["forward_price"]
by_day = {k: v for k, v in quotes.groupby(["as_of", "symbol"], sort=False)}

check = []
for front, back in PAIRS:
    dates = sorted({t for (t, s) in by_day if s == front}
                   & {t for (t, s) in by_day if s == back})
    for ts in dates[::10]:                      # every 10th day keeps this cheap
        gf, gb = by_day[(ts, front)], by_day[(ts, back)]
        ladder = np.sort(np.unique(np.concatenate([
            gf["strike_rate"].to_numpy(), gb["strike_rate"].to_numpy()])))
        ladder = ladder[(ladder > 0) & (ladder < 12)]
        if ladder.size < 8:
            continue
        pf, pb, ks = [], [], []
        for k in ladder:
            a = vertical_digital(gf, float(k), tol=0.20,
                                 forward_price=float(fwd_px.get((ts, front), np.nan)))
            b = vertical_digital(gb, float(k), tol=0.20,
                                 forward_price=float(fwd_px.get((ts, back), np.nan)))
            if a is None or b is None:
                continue
            pf.append(a["prob"]); pb.append(b["prob"]); ks.append(float(k))
        if len(ks) < 8:
            continue
        integral = np.trapezoid(np.array(pb) - np.array(pf), np.array(ks)) * 100.0
        spread = (float(fwd.get((ts, back))) - float(fwd.get((ts, front)))) * 100.0
        check.append({"as_of": ts, "pair": f"{front}-{back}",
                      "integral_bp": integral, "futures_spread_bp": spread,
                      "gap_bp": integral - spread, "n_strikes": len(ks),
                      "strike_span": ks[-1] - ks[0]})
check = pd.DataFrame(check)
print(f"n checks: {len(check)}")
if not check.empty:
    print(check[["integral_bp", "futures_spread_bp", "gap_bp", "strike_span"]]
          .describe().round(2).to_string())
    print(f"\ncorrelation(integral, futures spread) = "
          f"{check['integral_bp'].corr(check['futures_spread_bp']):.4f}")
    print("The residual gap is the mass outside the quoted strike ladder "
          "(truncation), not tradeable slack.")

# %%
if not check.empty:
    fig, ax = plt.subplots(figsize=(6, 5.5))
    ax.scatter(check["futures_spread_bp"], check["integral_bp"], s=12, alpha=0.6)
    lim = [min(check["futures_spread_bp"].min(), check["integral_bp"].min()),
           max(check["futures_spread_bp"].max(), check["integral_bp"].max())]
    ax.plot(lim, lim, color="grey", lw=1, ls="--")
    ax.set_xlabel("futures calendar spread (bp)")
    ax.set_ylabel("∫ listed digital calendar dK (bp)")
    ax.set_title("The LEVEL of the digital-calendar profile is pinned\n"
                 "by the linear market — only its shape is free", fontsize=10)
    ax.grid(alpha=0.25)
    fig.tight_layout()
    plt.show()

# %% [markdown]
# ## Step 2 — the signal panel

# %%
dc = digital_calendar_panel(
    quotes, contracts, offsets=CONFIG["offsets"],
    pairs=contract_pairs(sorted(contracts["symbol"].unique()),
                         gaps=CONFIG["pair_gaps"]),
    tol=CONFIG["strike_tol"], min_oi=CONFIG["min_oi"])
print(f"rows: {len(dc)}   pairs: {dc['key'].nunique() if len(dc) else 0}")
if not dc.empty:
    print(dc.groupby("key")[["cal_atm", "fly"]].describe().round(3).to_string())

# %%
gate = lab["gate"].set_index(["as_of", "symbol"])["gate"]


def _attach(df, signal_col):
    out = df.copy()
    out["signal"] = out[signal_col]
    gf = gate.reindex(pd.MultiIndex.from_arrays([out["as_of"], out["front"]]))
    gb = gate.reindex(pd.MultiIndex.from_arrays([out["as_of"], out["back"]]))
    out["gate"] = True                     # legs are listed and OI-screened
    out["gate_bl"] = (gf.fillna(False).to_numpy() & gb.fillna(False).to_numpy())
    return add_event_distance(out.dropna(subset=["signal"]))


sig_atm = _attach(dc, "cal_atm")
sig_fly = _attach(dc, "fly")
print(f"cal_atm rows {len(sig_atm)}  |  fly rows {len(sig_fly)}")

# %% [markdown]
# ## Step 3 — the tradeable packages
#
# `cal(K)` is one vertical per contract (4 option legs). `fly` is the strike
# butterfly of calendars: six verticals, twelve legs — so it is reported with
# the leg count made explicit, because cost, not signal, decides its fate.

# %%
ATM_TAG = f"{0.0:+.3f}"
IDX_ATM = sig_atm.set_index(["key", "as_of"]).sort_index()
IDX_FLY = sig_fly.set_index(["key", "as_of"]).sort_index()


def _row(idx, key, date):
    try:
        r = idx.loc[(key, date)]
    except KeyError:
        return None
    return r.iloc[0] if isinstance(r, pd.DataFrame) else r


def builder_atm(key, exec_date, direction):
    r = _row(IDX_ATM, key, exec_date)
    if r is None:
        return None
    front, back = key.split("-")
    legs = (digital_legs(back, r[f"b_lo{ATM_TAG}"], r[f"b_hi{ATM_TAG}"],
                         r[f"b_r{ATM_TAG}"], weight=1.0)
            + digital_legs(front, r[f"f_lo{ATM_TAG}"], r[f"f_hi{ATM_TAG}"],
                           r[f"f_r{ATM_TAG}"], weight=-1.0))
    return Structure(legs, label=f"digcal {key}")


def builder_fly(key, exec_date, direction):
    r = _row(IDX_FLY, key, exec_date)
    if r is None:
        return None
    front, back = key.split("-")
    legs = ()
    for o, w in zip(CONFIG["offsets"], (1.0, -2.0, 1.0)):
        tag = f"{o:+.3f}"
        legs = legs + digital_legs(back, r[f"b_lo{tag}"], r[f"b_hi{tag}"],
                                   r[f"b_r{tag}"], weight=w)
        legs = legs + digital_legs(front, r[f"f_lo{tag}"], r[f"f_hi{tag}"],
                                   r[f"f_r{tag}"], weight=-w)
    return Structure(legs, label=f"digcalfly {key}")


def builder_futures_only(key, exec_date, direction):
    """Benchmark: the same signal traded as a plain futures calendar spread."""
    front, back = key.split("-")
    return Structure((Leg("future", back, 1.0), Leg("future", front, -1.0)),
                     label=f"futcal {key}")


BASE = LabConfig(lag=1, round_trip_cost_bp=CONFIG["cost_bp"],
                 contracts_per_leg=CONFIG["contracts_per_leg"])
# The class-B object: each contract's option delta re-hedged DAILY with its own
# future. A digital scaled to one unit of probability is a tight vertical with
# enormous gamma, so a hedge set once at entry stops matching within a day and
# degenerates into a large outright futures position — which is why the engine
# walks the hedge instead of stamping it.
BASE_HEDGED = dataclasses.replace(BASE, delta_hedge="daily", future_leg_bp=0.25)

# check the mark identity: package mark should equal 100 x cal
if not sig_atm.empty:
    k0 = sig_atm.iloc[0]
    st = builder_atm(k0["key"], k0["as_of"], 1)
    m, _ = mark_structure(lab["book"], st, [k0["as_of"]])
    print(f"mark check: package {m[0]:.4f}bp vs 100*cal "
          f"{k0['cal_atm'] * 100:.4f}bp  (legs={len(st.legs)}, "
          f"{package_contracts(st):.0f} contracts per package)")
    sth = hedge_each_contract(lab["book"], st, k0["as_of"])
    print(f"with an entry-day delta hedge: {len(sth.legs)} legs, "
          f"{package_contracts(sth):.0f} contracts "
          f"(the engine re-hedges this DAILY, not once)")

# %% [markdown]
# ### How much of this is just the futures calendar spread?
#
# The level identity above guarantees `cal` inherits the futures calendar
# spread. Before believing any P&L, measure the contamination directly: the
# correlation of the signal with the linear market, and the same strategy run on
# a plain futures calendar spread. If the futures version does as well, the
# options are decoration.

# %%
spread = ((fwd.reindex(pd.MultiIndex.from_arrays([sig_atm["as_of"], sig_atm["back"]])).to_numpy()
           - fwd.reindex(pd.MultiIndex.from_arrays([sig_atm["as_of"], sig_atm["front"]])).to_numpy())
          * 100.0)
sig_atm = sig_atm.assign(fut_spread_bp=spread)
lv, dv = [], []
for k, sub in sig_atm.groupby("key"):
    s = sub.sort_values("as_of")
    lv.append(s["cal_atm"].corr(s["fut_spread_bp"]))
    dv.append(s["cal_atm"].diff().corr(s["fut_spread_bp"].diff()))
print(f"corr(cal_atm, futures calendar spread)  levels : "
      f"median {np.nanmedian(lv):+.3f}  range [{np.nanmin(lv):+.3f}, {np.nanmax(lv):+.3f}]")
print(f"                                        changes: "
      f"median {np.nanmedian(dv):+.3f}  range [{np.nanmin(dv):+.3f}, {np.nanmax(dv):+.3f}]")

# %% [markdown]
# ## Step 4 — grid, both directions

# %%
PARAMS = ["direction", "ma", "zscore_window", "entry_min_zscore", "exit_style"]
GRID = {"direction": list(CONFIG["directions"]), "ma": list(CONFIG["mas"]),
        "zscore_window": list(CONFIG["zscore_windows"]),
        "entry_min_zscore": list(CONFIG["entry_zs"]),
        "exit_style": list(CONFIG["exits"])}

print("A) UNHEDGED digital calendar — contains the linear component")
grid_atm = grid_search(GRID, signals=sig_atm, book=lab["book"],
                       builder=builder_atm, base=BASE, show_progress=True)
best_atm = grid_block(grid_atm, PARAMS)

# %%
print("\nB) FUTURES-ONLY benchmark — the same signal, no options at all")
grid_fut = grid_search(GRID, signals=sig_atm, book=lab["book"],
                       builder=builder_futures_only, base=BASE)
best_fut = grid_block(grid_fut, PARAMS, top=4)

# %%
print("\nC) DELTA-HEDGED digital calendar — the actual class-B object")
grid_hdg = grid_search(GRID, signals=sig_atm, book=lab["book"],
                       builder=builder_atm, base=BASE_HEDGED, show_progress=True)
best_hdg = grid_block(grid_hdg, PARAMS)
_ = stability_block(grid_hdg, best_hdg, PARAMS)

# %%
cmp = pd.DataFrame([
    {"variant": "A unhedged options", **grid_atm[["total_net_bp"]].agg(
        ["median", "max"]).to_dict()["total_net_bp"],
     "pct_pos": float((grid_atm["total_net_bp"] > 0).mean())},
    {"variant": "B futures only", **grid_fut[["total_net_bp"]].agg(
        ["median", "max"]).to_dict()["total_net_bp"],
     "pct_pos": float((grid_fut["total_net_bp"] > 0).mean())},
    {"variant": "C delta-hedged options", **grid_hdg[["total_net_bp"]].agg(
        ["median", "max"]).to_dict()["total_net_bp"],
     "pct_pos": float((grid_hdg["total_net_bp"] > 0).mean())},
])
print("\nDECOMPOSITION — does the option package beat its own futures shadow?")
print(cmp.round(2).to_string(index=False))
print("\nIf A ~ B, the 'options' result is a futures calendar trade in disguise.")
print("C is the part that survives killing both contracts' deltas.")

# %%
print("\nSIGN TEST")
print(grid_atm.groupby("direction")
      .agg(n_configs=("total_net_bp", "size"),
           median_net_bp=("total_net_bp", "median"),
           pct_positive=("total_net_bp", lambda s: (s > 0).mean()),
           best_net_bp=("total_net_bp", "max"),
           median_trades=("n_trades", "median")).round(3).to_string())

# %% [markdown]
# ### The headline is the DELTA-HEDGED variant
#
# The unhedged and futures-only rows follow it as diagnostics, because only the
# hedged package is an options-vs-futures statement.

# %%
cfg_hdg = config_from_row(BASE_HEDGED, best_hdg, PARAMS)
res_hdg = run_backtest(cfg_hdg, signals=sig_atm, book=lab["book"],
                       builder=builder_atm)
_ = header_block("Digital calendar, DELTA-HEDGED — best config", res_hdg,
                 grid=grid_hdg,
                 note="both contracts' option deltas re-hedged daily on their "
                      "own futures")
if not res_hdg.daily_bp.empty:
    fig = three_panel_equity(res_hdg, "Digital calendar (delta-hedged)")
    plt.show()

# %%
cfg_atm = config_from_row(BASE, best_atm, PARAMS)
res_atm = run_backtest(cfg_atm, signals=sig_atm, book=lab["book"],
                       builder=builder_atm)
_ = header_block("Digital calendar, UNHEDGED — diagnostic only", res_atm,
                 grid=grid_atm,
                 note="carries the futures calendar spread; NOT an "
                      "options-vs-futures result")
res_fut = run_backtest(config_from_row(BASE, best_fut, PARAMS), signals=sig_atm,
                       book=lab["book"], builder=builder_futures_only)
_ = header_block("Futures calendar spread — same signal, no options", res_fut,
                 grid=grid_fut)

# %%
print("EXIT COMPARISON (hedged)")
print(exit_comparison(cfg_hdg, signals=sig_atm, book=lab["book"],
                      builder=builder_atm).to_string(index=False))
print("\nMARKS x LAG (hedged)")
print(marks_x_lag_panel(cfg_hdg, signals=sig_atm, book=lab["book"],
                        builder=builder_atm).to_string(index=False))
_ = cost_block(res_hdg)

# %%
if not res_hdg.trades.empty:
    print(res_hdg.trades.sort_values("entry").head(40).to_string(index=False))

# %% [markdown]
# ## Step 5 — the shape (strike-butterfly of calendars)
#
# This is the part of the profile that the futures market cannot pin at all.
# Twelve option legs, so the per-leg cost model matters more than the flat one.

# %%
grid_fly = grid_search(GRID, signals=sig_fly, book=lab["book"],
                       builder=builder_fly, base=BASE, show_progress=True)
best_fly = grid_block(grid_fly, PARAMS)
cfg_fly = config_from_row(BASE, best_fly, PARAMS)
res_fly = run_backtest(cfg_fly, signals=sig_fly, book=lab["book"],
                       builder=builder_fly)
_ = header_block("Digital-calendar shape (strike fly) — best config", res_fly,
                 grid=grid_fly, note="12 option legs; per-leg round trip = 12bp")
if not res_fly.daily_bp.empty:
    fig = three_panel_equity(res_fly, "Digital-calendar shape fly")
    plt.show()
_ = cost_block(res_fly)

# %% [markdown]
# ## League rows

# %%
med_hdg = median_row(grid_hdg)
res_med = run_backtest(config_from_row(BASE_HEDGED, med_hdg, PARAMS),
                       signals=sig_atm, book=lab["book"], builder=builder_atm)
_ = header_block("Digital calendar hedged — median config", res_med, grid=grid_hdg)

# %%
league_row("2. Digital calendar (delta-hedged)", "best-config", res_hdg,
           grid=grid_hdg, cls="B", note="4 option legs + daily futures hedge")
league_row("2. Digital calendar (delta-hedged)", "median-config", res_med,
           grid=grid_hdg, cls="B", note="median of the sweep, not selected")
league_row("2. Digital calendar (UNHEDGED)", "diagnostic", res_atm,
           grid=grid_atm, cls="B",
           note="DIAGNOSTIC: carries the futures calendar spread, not RV")
league_row("2b. Futures calendar spread", "same-signal-benchmark", res_fut,
           grid=grid_fut, cls="linear",
           note="the benchmark the options must beat to mean anything")
league_row("2c. Digital-calendar shape fly", "best-config", res_fly,
           grid=grid_fly, cls="B", note="12 option legs — cost-dominated")
