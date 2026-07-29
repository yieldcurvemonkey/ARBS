# %% [markdown]
# # SR3 RV Lab — Framework 9: mid-curve options (the coupling dimension, executable)
#
# **RV class: B — cross-contract coupling, for the first time tradeable.**
#
# A 1-year mid-curve (`0QZ26`, Barchart root `MMA`) is an option **expiring
# Dec-2026** on the **`SFRZ27` future**. The quarterly `SFRZ27` option expires
# Dec-2027 on the same underlying. Two listed options, one underlying, two
# observation dates — which is exactly the object the quarterly-only work could
# measure but never execute.
#
# ### Repo status (checked, not assumed)
#
# The mid-curve plumbing already exists and works end to end:
# `MDP/STIRFutures/_sofr_option_contracts.py::_BBG_TO_BARCHART` maps
# `0Q→MMA, 2Q→MMB, 3Q→MMC, 4Q→MMD, 5Q→MME`; `_UNDERLYING_RULES` gives the
# +1/+2/+3/+4/+5-year underlying offsets; and quarterly mid-curve roots are
# inside `_PRE_IMM_FRIDAY_OPTION_ROOTS`, so `sofr_option_last_trade_date`
# returns real dates for them (only *weekly* mid-curves, `S01..S35`, return
# `None`). Verified live: `0QZ26 → SFRZ27` expiring 2026-12-11, `2QZ26 → SFRZ28`,
# `3QZ26 → SFRZ29`, all fetching smiles.
#
# ### Frameworks
#
# * **9a Forward vol** — the mid-curve and the quarterly on the same underlying
#   differ only in observation date, so their vol spread is listed forward vol.
# * **9b Coupling digitals** — same rate strike, same underlying, two expiries:
#   the term structure of `P(>=K)` between two real observation dates.
# * **9c Skew term structure** — does hike/cut skew live in the near window or
#   the far one?
#
# Liquidity is thinner than the quarterlies, so the OI floor is higher and the
# cost assumption wider (0.75–1bp per option leg). Coverage is stated per series
# rather than glossed.

# %%
CONFIG = dict(
    mc_dir="../data/sfr_rv_lab_mc",
    min_oi=500,               # mid-curve chains are thin — a real floor
    wing_offset=0.25,
    strike_tol=0.13,
    digital_tol=0.10,
    contracts_per_leg=100,
    cost_bp=4.0,              # 4 option legs at ~1bp/leg taker, wider than SR3
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

from sfr_rv_lab_common import DATA_DIR, LabConfig, load_lab, run_framework
from RVUtils.SFRRVLab import (
    Leg, MarkBook, Structure, add_event_distance, load_panels,
    pick_listed_strike, vertical_digital,
)
from RVUtils.SFRRVLab.signals import digital_legs
from MDP.STIRFutures._sofr_option_contracts import (
    _option_contract_to_underlying_contract, sofr_option_last_trade_date,
)

pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 60)

MC_DIR = Path(CONFIG["mc_dir"]).resolve()
mc = load_panels(MC_DIR)
q_mc, c_mc = mc.get("quotes"), mc.get("contracts")
print(f"mid-curve quotes: {0 if q_mc is None else len(q_mc)} rows")

# %% [markdown]
# ## Coverage — stated honestly, per series

# %%
if q_mc is not None and len(q_mc):
    cov = (c_mc.groupby("symbol")
           .agg(first=("as_of", "min"), last=("as_of", "max"),
                days=("as_of", "nunique"),
                med_quotes=("n_quotes", "median"),
                med_oi=("oi_total", "median"))
           .sort_values("first"))
    cov["underlying"] = [_option_contract_to_underlying_contract(s)
                         for s in cov.index]
    cov["last_trade"] = [sofr_option_last_trade_date(s) for s in cov.index]
    print(cov.to_string())
    liq = q_mc[q_mc["oi"] >= CONFIG["min_oi"]]
    print(f"\nquotes with OI >= {CONFIG['min_oi']}: {len(liq)} "
          f"({len(liq) / len(q_mc):.1%} of all mid-curve quotes)")
    print("usable days per series (>= 6 strikes over the OI floor):")
    usable = (liq.groupby(["symbol", "as_of"]).size()
              .rename("n").reset_index())
    usable = usable[usable["n"] >= 6]
    print(usable.groupby("symbol")["as_of"].nunique().to_string())
else:
    print("no mid-curve data — the rest of this notebook is skipped")

# %% [markdown]
# ## Join to the quarterly panel on the shared underlying

# %%
lab = load_lab(DATA_DIR)
q_sr, c_sr = lab["quotes"], lab["contracts"]

if q_mc is not None and len(q_mc):
    pairs = []
    for s in sorted(c_mc["symbol"].unique()):
        try:
            und = _option_contract_to_underlying_contract(s)
        except Exception:
            continue
        if und in set(c_sr["symbol"]):
            pairs.append((s, und))
    print(f"mid-curve / quarterly pairs on a shared underlying: {pairs}")
else:
    pairs = []

# %%
# one MarkBook over BOTH panels so a package can hold legs from each
if pairs:
    all_quotes = pd.concat([q_sr, q_mc], ignore_index=True)
    all_contracts = pd.concat([c_sr, c_mc], ignore_index=True)
    book = MarkBook(all_quotes, all_contracts)
    QDAY = {k: v for k, v in all_quotes.groupby(["as_of", "symbol"], sort=False)}
    FWD = all_contracts.set_index(["as_of", "symbol"])["forward_rate"]
    FWD_PX = all_contracts.set_index(["as_of", "symbol"])["forward_price"]
    TTE = all_contracts.set_index(["as_of", "symbol"])["tte"]
    print(f"combined book: {len(all_quotes)} quotes, "
          f"{all_contracts['symbol'].nunique()} symbols")

# %% [markdown]
# ## 9a — listed forward vol (mid-curve vs quarterly, same underlying)
#
# Both options settle on the same future; the mid-curve simply observes it a year
# earlier. The ATM vol spread is therefore the listed price of forward
# volatility over the window between the two expiries.

# %%
rows = []
for mcs, und in pairs:
    dates = sorted({t for (t, s) in QDAY if s == mcs}
                   & {t for (t, s) in QDAY if s == und})
    for ts in dates:
        gm, gq = QDAY[(ts, mcs)], QDAY[(ts, und)]
        gm = gm[gm["oi"] >= CONFIG["min_oi"]]
        gq = gq[gq["oi"] >= CONFIG["min_oi"]]
        f = FWD.get((ts, und))
        if f is None or not np.isfinite(f) or gm.empty or gq.empty:
            continue
        am_c = pick_listed_strike(gm, "C", float(f), tol=CONFIG["strike_tol"])
        am_p = pick_listed_strike(gm, "P", float(f), tol=CONFIG["strike_tol"])
        aq_c = pick_listed_strike(gq, "C", float(f), tol=CONFIG["strike_tol"])
        aq_p = pick_listed_strike(gq, "P", float(f), tol=CONFIG["strike_tol"])
        if any(x is None for x in (am_c, am_p, aq_c, aq_p)):
            continue
        iv_m = float(np.nanmean([am_c["iv_bp"], am_p["iv_bp"]]))
        iv_q = float(np.nanmean([aq_c["iv_bp"], aq_p["iv_bp"]]))
        t_m, t_q = float(TTE.get((ts, mcs), np.nan)), float(TTE.get((ts, und), np.nan))
        fwd_var = iv_q ** 2 * t_q - iv_m ** 2 * t_m
        rows.append({
            "as_of": ts, "key": f"{mcs}|{und}", "mc": mcs, "qtr": und,
            "iv_mc_bp": iv_m, "iv_qtr_bp": iv_q, "iv_spread_bp": iv_q - iv_m,
            "tte_mc": t_m, "tte_qtr": t_q,
            "fwd_vol_bp": float(np.sqrt(fwd_var / max(t_q - t_m, 1e-6)))
            if fwd_var > 0 else np.nan,
            "k_mc_c": float(am_c["strike_price"]), "k_mc_p": float(am_p["strike_price"]),
            "k_q_c": float(aq_c["strike_price"]), "k_q_p": float(aq_p["strike_price"]),
            "gate": True,
        })
fv = pd.DataFrame(rows)
print(f"forward-vol panel: {len(fv)} rows, {fv['key'].nunique() if len(fv) else 0} pairs")
if len(fv):
    print(fv.groupby("key")[["iv_mc_bp", "iv_qtr_bp", "iv_spread_bp", "fwd_vol_bp"]]
          .describe().round(2).to_string())
    fv = add_event_distance(fv)

# %%
if len(fv):
    fig, ax = plt.subplots(figsize=(9, 4))
    for k, sub in fv.groupby("key"):
        s = sub.sort_values("as_of")
        ax.plot(s["as_of"], s["iv_mc_bp"], lw=1.1, label=f"{k} mid-curve")
        ax.plot(s["as_of"], s["iv_qtr_bp"], lw=1.1, ls="--", label=f"{k} quarterly")
    ax.set_ylabel("listed ATM normal vol (bp)")
    ax.set_title("Same underlying, two observation dates: the listed forward-vol "
                 "pair", fontsize=10)
    ax.legend(fontsize=7, ncol=2)
    ax.grid(alpha=0.25)
    fig.autofmt_xdate()
    fig.tight_layout()
    plt.show()

# %%
FV_IDX = fv.set_index(["key", "as_of"]).sort_index() if len(fv) else None


def builder_fwdvol(key, exec_date, direction):
    """Long the quarterly straddle, short the mid-curve straddle (vega-ratioed)."""
    try:
        r = FV_IDX.loc[(key, exec_date)]
    except (KeyError, AttributeError):
        return None
    if isinstance(r, pd.DataFrame):
        r = r.iloc[0]
    mcs, und = key.split("|")
    # vega of an ATM normal straddle scales with sqrt(T); ratio the near leg up
    ratio = float(np.sqrt(max(r["tte_qtr"], 1e-6) / max(r["tte_mc"], 1e-6)))
    ratio = float(np.clip(ratio, 0.25, 4.0))
    return Structure((
        Leg("option", und, 1.0, "C", float(r["k_q_c"])),
        Leg("option", und, 1.0, "P", float(r["k_q_p"])),
        Leg("option", mcs, -ratio, "C", float(r["k_mc_c"])),
        Leg("option", mcs, -ratio, "P", float(r["k_mc_p"])),
    ), label=f"fwdvol {key}")


BASE = LabConfig(lag=1, round_trip_cost_bp=CONFIG["cost_bp"],
                 contracts_per_leg=CONFIG["contracts_per_leg"],
                 delta_hedge="daily", future_leg_bp=0.25)
GRID = {"direction": list(CONFIG["directions"]), "ma": list(CONFIG["mas"]),
        "zscore_window": list(CONFIG["zscore_windows"]),
        "entry_min_zscore": list(CONFIG["entry_zs"]),
        "exit_style": list(CONFIG["exits"])}
PARAMS = ["direction", "ma", "zscore_window", "entry_min_zscore", "exit_style"]

if len(fv) > 60:
    sig_fv = fv.copy()
    sig_fv["signal"] = sig_fv["iv_spread_bp"]
    out_fv = run_framework(
        "9a. Mid-curve forward vol", signals=sig_fv, book=book,
        builder=builder_fwdvol, base=BASE, grid_spec=GRID, params=PARAMS, cls="B",
        note="quarterly straddle vs sqrt(T)-ratioed mid-curve straddle, "
             "same underlying, delta-hedged daily")
else:
    print("not enough forward-vol history to backtest")

# %% [markdown]
# ## 9b — coupling digitals: the SAME strike on the SAME underlying, two expiries
#
# This is the cleanest coupling object in the whole lab. Both digitals are
# `P(the SFRZ27 rate >= K)`; the only difference is *when* it is observed. Their
# spread is the listed price of "the rate gets there later rather than sooner" —
# with no futures-spread level constraint contaminating it, because there is only
# one future.

# %%
rows = []
for mcs, und in pairs:
    dates = sorted({t for (t, s) in QDAY if s == mcs}
                   & {t for (t, s) in QDAY if s == und})
    for ts in dates:
        gm = QDAY[(ts, mcs)]
        gq = QDAY[(ts, und)]
        gm = gm[gm["oi"] >= CONFIG["min_oi"]]
        gq = gq[gq["oi"] >= CONFIG["min_oi"]]
        f = FWD.get((ts, und))
        fp = FWD_PX.get((ts, und))
        if f is None or not np.isfinite(f) or gm.empty or gq.empty:
            continue
        for o in (-0.25, 0.0, 0.25):
            k = float(f) + o
            dm = vertical_digital(gm, k, tol=CONFIG["digital_tol"],
                                  forward_price=float(fp))
            dq = vertical_digital(gq, k, tol=CONFIG["digital_tol"],
                                  forward_price=float(fp))
            if dm is None or dq is None:
                continue
            if not (-0.02 <= dm["prob"] <= 1.02) or not (-0.02 <= dq["prob"] <= 1.02):
                continue
            rows.append({
                "as_of": ts, "key": f"{mcs}|{und}@{o:+.2f}", "mc": mcs, "qtr": und,
                "offset": o, "p_mc": dm["prob"], "p_qtr": dq["prob"],
                "signal": dq["prob"] - dm["prob"],
                "mc_lo": dm["k_lo"], "mc_hi": dm["k_hi"], "mc_r": dm["right"],
                "q_lo": dq["k_lo"], "q_hi": dq["k_hi"], "q_r": dq["right"],
                "gate": True})
cd = pd.DataFrame(rows)
print(f"coupling-digital panel: {len(cd)} rows, "
      f"{cd['key'].nunique() if len(cd) else 0} keys")
if len(cd):
    cd = add_event_distance(cd)
    print(cd.groupby("offset")[["p_mc", "p_qtr", "signal"]].describe()
          .round(3).to_string())

# %%
CD_IDX = cd.set_index(["key", "as_of"]).sort_index() if len(cd) else None


def builder_coupling(key, exec_date, direction):
    try:
        r = CD_IDX.loc[(key, exec_date)]
    except (KeyError, AttributeError):
        return None
    if isinstance(r, pd.DataFrame):
        r = r.iloc[0]
    mcs, rest = key.split("|")
    und = rest.split("@")[0]
    return Structure(
        digital_legs(und, float(r["q_lo"]), float(r["q_hi"]), str(r["q_r"]), 1.0)
        + digital_legs(mcs, float(r["mc_lo"]), float(r["mc_hi"]), str(r["mc_r"]), -1.0),
        label=f"coupdig {key}")


if len(cd) > 60:
    out_cd = run_framework(
        "9b. Mid-curve coupling digitals", signals=cd, book=book,
        builder=builder_coupling, base=BASE, grid_spec=GRID, params=PARAMS,
        cls="B", note="same strike, same underlying, two expiries — "
                      "no futures-spread level constraint")
else:
    print("not enough coupling-digital history to backtest")

# %% [markdown]
# ## 9c — skew term structure on one underlying
#
# The risk reversal at the mid-curve expiry against the risk reversal at the
# quarterly expiry: is the hike/cut asymmetry priced into the near observation
# window or the far one?

# %%
rows = []
for mcs, und in pairs:
    dates = sorted({t for (t, s) in QDAY if s == mcs}
                   & {t for (t, s) in QDAY if s == und})
    for ts in dates:
        gm = QDAY[(ts, mcs)][lambda d: d["oi"] >= CONFIG["min_oi"]]
        gq = QDAY[(ts, und)][lambda d: d["oi"] >= CONFIG["min_oi"]]
        f = FWD.get((ts, und))
        if f is None or not np.isfinite(f) or gm.empty or gq.empty:
            continue
        legs = {}
        ok = True
        for tag, g in (("mc", gm), ("q", gq)):
            hk = pick_listed_strike(g, "P", float(f) + CONFIG["wing_offset"],
                                    tol=CONFIG["strike_tol"])
            ct = pick_listed_strike(g, "C", float(f) - CONFIG["wing_offset"],
                                    tol=CONFIG["strike_tol"])
            if hk is None or ct is None:
                ok = False
                break
            legs[f"{tag}_hk_K"] = float(hk["strike_price"])
            legs[f"{tag}_ct_K"] = float(ct["strike_price"])
            legs[f"{tag}_rr"] = float(hk["premium_bp"] - ct["premium_bp"])
        if not ok:
            continue
        rows.append({"as_of": ts, "key": f"{mcs}|{und}", "mc": mcs, "qtr": und,
                     "signal": legs["q_rr"] - legs["mc_rr"], "gate": True, **legs})
sk = pd.DataFrame(rows)
print(f"skew-TS panel: {len(sk)} rows")
if len(sk):
    sk = add_event_distance(sk)
    print(sk.groupby("key")[["mc_rr", "q_rr", "signal"]].describe()
          .round(2).to_string())

SK_IDX = sk.set_index(["key", "as_of"]).sort_index() if len(sk) else None


def builder_skewts(key, exec_date, direction):
    try:
        r = SK_IDX.loc[(key, exec_date)]
    except (KeyError, AttributeError):
        return None
    if isinstance(r, pd.DataFrame):
        r = r.iloc[0]
    mcs, und = key.split("|")
    return Structure((
        Leg("option", und, 1.0, "P", float(r["q_hk_K"])),
        Leg("option", und, -1.0, "C", float(r["q_ct_K"])),
        Leg("option", mcs, -1.0, "P", float(r["mc_hk_K"])),
        Leg("option", mcs, 1.0, "C", float(r["mc_ct_K"])),
    ), label=f"mcskewTS {key}")


if len(sk) > 60:
    out_sk = run_framework(
        "9c. Mid-curve skew term structure", signals=sk, book=book,
        builder=builder_skewts, base=BASE, grid_spec=GRID, params=PARAMS,
        cls="B", note="RR(quarterly expiry) - RR(mid-curve expiry), one underlying")
else:
    print("not enough skew-TS history to backtest")
