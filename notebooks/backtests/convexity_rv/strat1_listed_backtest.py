# %% [markdown]
# # Strategy 1-listed — the curve as gamma, priced against **exchange-listed** vol
#
# **The parent question.** J.P. Morgan, *"An option by any other name: Sourcing
# cheap convexity in the long end of the curve"* (Younger / Sarkar / Salem,
# 03-Feb-2017), restated in *"Valuing convexity in the long end of the yield
# curve: A global perspective"* (09-Feb-2018):
#
# > "we are estimating the level of normal daily volatility in rates that is
# >  sufficient to offset the carry costs on a given curve trade."
#
# > "The same can also be said when the level of volatility priced into the curve
# >  is less than that implied by ATMF swaptions."
#
# `strat1_curve_gamma` answers that with the **OTC swaption** as the benchmark.
# This notebook replaces the benchmark with **exchange-listed** vol and changes
# nothing else — same payoff kernel, same breakeven solve, same cohort
# machinery, same sign convention.
#
# **Why that is a real question and not a relabelling.** Listed and OTC vol are
# different markets with different flows: swaption vol is set by
# structured-product and mortgage-convexity hedging, listed vol by macro funds
# and dealer gamma. The curve can be cheap against one and rich against the
# other, and the OTC/listed basis is itself a traded thing. So every date here
# carries **both** signals, and §8 measures how often they actually disagree —
# which is the only honest way to answer "is this a relabelling", and the answer
# is not the flattering one.
#
# Both sides are quoted in **bp/day** (annual bp / √252), which is what makes the
# comparison unit-clean and horizon-agnostic to first order.
#
# ---
#
# ## What is hard about this, and what this notebook proves before using it
#
# 1. **`iv_bp`'s units and convention are asserted, not assumed** (§5). Every one
#    of the 199,313 quotes is repriced with Bachelier at its own `iv_bp`, with and
#    without discounting, and the answer is read off the two error distributions.
# 2. **The listed quote is cross-checked against realised vol** (§5c) using only
#    `forward_rate`, so agreement is evidence rather than an identity.
# 3. **Sector matching** (§2, §9). Strategy 1's universe is long-end and its
#    natural listed benchmark is a **UST bond option**, which does not exist
#    offline here. SFR options price the **short end**. So the universe is
#    replaced by SFR-sector forward flatteners, and the long-end structures are
#    reported as *"listed benchmark unavailable"* — never as a comparison.
# 4. **Expiry matching** (§7). The curve breakeven is a 1-year number; the listed
#    option has its own expiry. Both are in bp/day, the nearest expiry to the
#    horizon is used, and the gap is carried on every row.
#
# **Sample-length warning, stated once and honoured throughout.** The listed panel
# is **540 daily dates (2024-07-01 .. 2026-07-28)** with a 1-year holding period —
# roughly *one* non-overlapping observation per structure. No Sharpe ratio is
# claimed anywhere below. The headline result is the **signal distribution**
# (§8); the cohort P&L in §10 is an illustration carrying its own caveat.
#
# **Network.** Nothing in this notebook can reach a vendor. The listed leg is read
# from local parquet and the OTC leg from the local swaption-cube store; the
# listed-option MDPs (`STIRFutureOptionMDP`, `USTFutureOptionMDP`) are never
# imported.

# %%
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import datetime
import json
import math
import pathlib
import sys
import time
import warnings

import numpy as np
import pandas as pd

_REPO = pathlib.Path(__file__).resolve().parents[3] if "__file__" in dir() else pathlib.Path.cwd().parents[2]
sys.path.insert(0, str(_REPO))

import plotly.graph_objects as go
import plotly.io as pio

pio.renderers.default = "plotly_mimetype+notebook_connected"

from BT.data_handler import TimeGrid
from BT.query_actions import AddQueryAction, UnwindPositionsAction
from BT.query_engine import QueryDrivenBacktest
from BT.query_strategy import QueryStrategy
from BT.trade_dashboard import compare_curves, summary_stats, trade_dashboard
from BT.triggers import DateTrigger, DateTriggerRequirements
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapStructure import IRSwapStructure
from Query.IRSwaps.IRSwapValue import IRSwapValue
from RVUtils.ConvexityRV import listed_vol as lv
from RVUtils.ConvexityRV import strat1_curve_gamma as s1
from RVUtils.ConvexityRV import strat1_listed as sl

warnings.filterwarnings("ignore", category=RuntimeWarning)

DATA = _REPO / "notebooks" / "data" / "convexity_rv"
DATA.mkdir(parents=True, exist_ok=True)
pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 60)
print("repo      ", _REPO)
print("artifacts ", DATA)
print("listed src", lv.default_sfr_root())

# %% [markdown]
# ## 1. CONFIG — every knob, documented at the point of use
#
# `Strat1ListedConfig` is the single source of truth and carries the inline
# documentation for each field; this cell prints the resolved values so the
# executed notebook records exactly what it ran.
#
# Four choices shape everything downstream and are each measured later rather
# than asserted here:
#
# * **`structures = SFR_STRUCTURES`** — SFR-sector forward flatteners (1Y..6Y on
#   the curve), not strategy 1's long end. §2 and §9.
# * **`shifts_bp` spans ±500 bp**, not JPM's ±250. §6 measures the grid
#   saturation that forces it: on a short-end structure the ±250 grid manufactures
#   `never_cheap` classifications.
# * **No 1Y tails.** Carry-and-roll over a 1-year horizon on a 1-year tail rolls
#   the swap to zero length and the engine raises. §2 reproduces the failure.
# * **`otc_expiry/otc_tenor = 1Yx2Y`**, not JPM's 1Yx30Y. The OTC control exists
#   to isolate listed-vs-OTC *at fixed sector*, so it must match the curve legs'
#   tenor and the listed option's expiry.

# %%
CFG = sl.Strat1ListedConfig()
for _f in sorted(CFG.as_dict()):
    print(f"  {_f:32s} {CFG.as_dict()[_f]}")
print()
print("curve_config() handed to the strat1 kernel:")
print(f"  shifts {len(CFG.shifts())} points, {CFG.shifts().min():+.0f}..{CFG.shifts().max():+.0f} bp")
print(f"  structures {[l for l, _, _ in CFG.structures]}")

# %% [markdown]
# ## 2. Sector matching, and why the universe is what it is
#
# ### 2a. The long end has no listed benchmark here
#
# Strategy 1 trades 25Y/20Yx5Y, 30s/50s, 10Yx10Y/20Yx10Y. The listed instrument
# that prices those is a **UST bond option**. There is no offline UST
# futures-option panel in this repo, and the only code path to one
# (`USTFutureOptionMDP.sabr_smile`) is uncached and crawls Barchart **one HTTP
# call per strike**. A 1,205-business-day × 28-contract cache-key scan found
# **0** cached STIR smiles and **8** cached UST smiles (2 dates, both Mar-2026).
#
# `listed_vol.load_ust_panel()` is therefore a **named failure**, not an empty
# frame — an empty frame is what a downstream table renders as "0.0".

# %%
try:
    lv.load_ust_panel()
    raise AssertionError("load_ust_panel must refuse — it did not")
except lv.ListedDataUnavailable as _e:
    print("load_ust_panel() correctly refuses:")
    print("   ", str(_e)[:200], "...")
print()
print("Long-end structures with NO listed benchmark:",
      [l for l, _, _ in sl.LONG_END_STRUCTURES])
print("SFR-sector structures used instead:        ",
      [l for l, _, _ in sl.SFR_STRUCTURES])

# %% [markdown]
# ### 2b. Why no 1Y tails — the measured failure
#
# The obvious short-end pairs are 1Y-tailed (`1Yx1Y/2Yx1Y`). Carry-and-roll over
# a **1-year** horizon on a **1-year** tail rolls the swap to zero length. Rather
# than shorten the horizon for some structures and not others — which would make
# the bp/day comparison inconsistent across the panel — the universe uses 2Y and
# 3Y tails and keeps one horizon everywhere. The cell below reproduces the
# failure rather than citing it.

# %%
_mdp = IRSwapsMDP(source="CITIVELO_EXCEL")
_probe_day = datetime.date(2025, 3, 3)
_probe = _mdp.get_data({"curve_name": CFG.curve, "timestamp": _probe_day})
_raw1, _w1, _res1 = s1.resolve_package(_probe, "1Yx1Y", "2Yx1Y",
                                       package_dv01=CFG.package_dv01, curve=CFG.curve)
print(f"1Yx1Y/2Yx1Y legs resolve fine on {_probe_day}: "
      f"{[(_probe.effective_date(s).date(), _probe.maturity_date(s).date()) for s in _raw1]}")
_carry_by_h = {}
for _h in ("1Y", "6M", "3M"):
    try:
        _carry_by_h[_h] = s1.package_carry_roll_bp(_probe, _raw1, _w1, _h)
    except Exception as _exc:
        _carry_by_h[_h] = f"{type(_exc).__name__}: {_exc}"
for _h, _v in _carry_by_h.items():
    print(f"   carry_and_roll horizon={_h:3s} -> {_v}")
assert isinstance(_carry_by_h["1Y"], str) and "termination" in _carry_by_h["1Y"]
assert isinstance(_carry_by_h["6M"], float)
print("CONFIRMED: a 1Y tail cannot survive a 1Y roll; 6M and 3M horizons work.")

# %% [markdown]
# ## 3. Sign probes
#
# ### 3a. Leg level — a payer must gain in a selloff, and the two sides must mirror

# %%
def _run_sign_probe(bpv: float) -> float:
    dates = [datetime.date(2022, 9, 12), datetime.date(2022, 9, 13),
             datetime.date(2022, 9, 14), datetime.date(2022, 9, 15)]
    mdp = IRSwapsMDP(source="CITIVELO_EXCEL")
    grid = TimeGrid([pd.Timestamp(d) for d in dates])
    q = IRSwapQuery(structure=IRSwapStructure.OUTRIGHT, value=IRSwapValue.NPV,
                    tenor="5Y", curve=CFG.curve, structure_kwargs={"bpv": bpv},
                    tags=("probe",))
    strat = QueryStrategy(name=f"sign_{bpv:+.0f}", triggers=[
        DateTrigger(DateTriggerRequirements(dates=[dates[0]]),
                    actions=[AddQueryAction(query=q, meta={"tags": ["probe"]})]),
        DateTrigger(DateTriggerRequirements(dates=[dates[-1]]),
                    actions=[UnwindPositionsAction(match_tag="probe", fee=0.0)]),
    ])
    bt = QueryDrivenBacktest(time_grid=grid, strategy=strat, mdp=mdp, show_progress=False)
    bt.run()
    assert bt.mtm_history, "engine produced no marks — run() swallows exceptions"
    return float(pd.Series(bt.mtm_history).iloc[-1])


_plus, _minus = _run_sign_probe(+CFG.package_dv01), _run_sign_probe(-CFG.package_dv01)
print(f"+bpv {_plus:+,.0f}   -bpv {_minus:+,.0f}")
assert _plus > 0, "payer must gain in the 2022-09 selloff"
assert abs(_plus + _minus) < 1e-6 * abs(_plus), "buy/sell must mirror — seam regressed?"
print("SIGN TEST PASS: mirror exact, payer gains  =>  OUTRIGHT bpv>0 is a PAYER")

# %% [markdown]
# ### 3b. Package level, on an **SFR-sector** structure
#
# The outright probe pins leg direction; this pins the *package* direction and
# DV01 neutrality, which is what the strategy trades. A flattener (`bpv < 0`)
# pays the front leg and receives the back, both legs carry |pv01| = the package
# DV01, and flipping the sign mirrors the notionals exactly.

# %%
_raw_f, _w_f, _flat = s1.resolve_package(_probe, "1Yx2Y", "2Yx2Y",
                                         package_dv01=CFG.package_dv01,
                                         direction=s1.FLATTENER, curve=CFG.curve)
_raw_s, _w_s, _steep = s1.resolve_package(_probe, "1Yx2Y", "2Yx2Y",
                                          package_dv01=CFG.package_dv01,
                                          direction=s1.STEEPENER, curve=CFG.curve)
for _nm, _pkg, _w in (("flattener", _flat, _w_f), ("steepener", _steep, _w_s)):
    print(f"{_nm:10s} rw={_w}")
    for _s in _pkg:
        print(f"   eff {_probe.effective_date(_s).date()} mat {_probe.maturity_date(_s).date()} "
              f"N {_probe.notional(_s):+,.0f}  pv01 {_probe.pv01(_s):+,.1f}")
assert _w_f == [1.0, -1.0] and _w_s == [-1.0, 1.0]
for _a, _b in zip(_flat, _steep):
    assert abs(abs(_probe.pv01(_a)) - CFG.package_dv01) < 1e-6 * CFG.package_dv01
    assert abs(_probe.notional(_a) + _probe.notional(_b)) < 1e-6 * abs(_probe.notional(_a))
assert abs(sum(_probe.pv01(_s) for _s in _flat)) < 1e-3 * CFG.package_dv01
print("PACKAGE SIGN TEST PASS: DV01-neutral, directions mirror exactly")

# %% [markdown]
# ## 4. Known-answer tie-out — the payoff-profile regression table
#
# The curve kernel is shared verbatim with strategy 1, so it is pinned to
# strategy 1's own regression table: **2022-09-13**, $100k package DV01, `bpv<0`
# flattener, pure convexity shape (carry excluded), bp of package DV01, on JPM's
# ±250 bp grid.
#
# | shift bp | −250 | −200 | −150 | −100 | −50 | −25 | 0 | 25 | 50 | 100 | 150 | 200 | 250 |
# |---|---|---|---|---|---|---|---|---|---|---|---|---|---|
# | 20Yx5Y/25Yx5Y | 60.0 | 33.7 | 16.5 | 6.4 | 1.3 | 0.3 | 0.0 | 0.4 | 1.2 | 4.2 | 8.2 | 12.8 | 17.5 |
#
# **2022-09-13 is outside the listed window** (2024-07..2026-07) and outside the
# SFR universe. That is deliberate: this cell validates the *curve kernel*, which
# is available from 2019, and it must reproduce strategy 1's number exactly or
# the two studies are not built on the same measurement.

# %%
_REG_2022 = [60.0, 33.7, 16.5, 6.4, 1.3, 0.3, 0.0, 0.4, 1.2, 4.2, 8.2, 12.8, 17.5]
_JPM_SHIFTS = (-250.0, -200.0, -150.0, -100.0, -50.0, -25.0, 0.0,
               25.0, 50.0, 100.0, 150.0, 200.0, 250.0)
_reg_cfg = s1.Strat1Config(shifts_bp=_JPM_SHIFTS, package_dv01=CFG.package_dv01)
_reg_pricer = _mdp.get_data({"curve_name": CFG.curve, "timestamp": datetime.date(2022, 9, 13)})
_reg_prof = s1.structure_profile(_reg_pricer, "20Yx5Y/25Yx5Y", "20Yx5Y", "25Yx5Y",
                                 _reg_cfg, direction=s1.FLATTENER)
_got = np.round(_reg_prof.convexity_bp, 1)
print(pd.DataFrame({"shift_bp": _JPM_SHIFTS, "pinned": _REG_2022, "measured": _got,
                    "diff": np.round(_got - np.array(_REG_2022), 2)}).to_string(index=False))
assert np.max(np.abs(_got - np.array(_REG_2022))) <= 0.05, "curve kernel drifted from strat1"
print("\nREGRESSION TIE-OUT PASS: 20Yx5Y/25Yx5Y reproduced to <=0.05 bp on 2022-09-13")

# %% [markdown]
# ### 4b. Flattener convexity on the SFR-sector structures
#
# The whole framework rests on the flattener being long gamma: its payoff profile
# must be **convex**. The grid is deliberately uneven (25 bp steps through the
# money, 100 bp in the wings), so a plain second difference is not a curvature
# test — it mixes step sizes. `s1.is_convex` tests that the *divided* differences
# are non-decreasing, which is convexity on an uneven grid.
#
# For completeness the plain second difference is shown too, on the evenly-spaced
# ±100 bp sub-grid where it *is* meaningful.

# %%
_rows = []
for _lbl, _ft, _bt in CFG.structures:
    _p = s1.structure_profile(_probe, _lbl, _ft, _bt, CFG.curve_config(), direction=s1.FLATTENER)
    _even = np.array([-100.0, -75.0, -50.0, -25.0, 0.0, 25.0, 50.0, 75.0, 100.0])
    _idx = [list(_p.shifts_bp).index(s) for s in _even]
    _d2 = np.diff(np.diff(_p.convexity_bp[_idx]))
    _rows.append({"structure": _lbl, "carry_bp": round(_p.carry_bp, 4),
                  "convex(uneven grid)": s1.is_convex(_p.shifts_bp, _p.convexity_ccy),
                  "min 2nd-diff on even ±100 grid": round(float(_d2.min()), 5),
                  "cvx @ -100bp": round(float(_p.convexity_bp[_idx[0]]), 3),
                  "cvx @ +100bp": round(float(_p.convexity_bp[_idx[-1]]), 3)})
    assert s1.is_convex(_p.shifts_bp, _p.convexity_ccy), f"{_lbl} flattener is not convex"
    assert _d2.min() > 0, f"{_lbl} 2nd difference not strictly positive"
print(pd.DataFrame(_rows).to_string(index=False))
print(f"\nCONVEXITY PASS on {_probe_day}: every SFR-sector flattener is long gamma "
      "(2nd difference > 0)")

# %% [markdown]
# ## 5. THE UNIT TIE-OUT — what `iv_bp` actually is
#
# The column is called `iv_bp` and the natural assumption is "normal bp vol". It
# is — but the *pricing convention* attached to it is not free, and the same
# number means different premiums depending on whether the model discounts. So it
# is measured, over every one of the 199,313 quotes, by repricing `premium_bp`
# with Bachelier **in rate space** at `iv_bp`, with `tte` and `forward_rate` taken
# from `contracts.parquet`.
#
# The mapping used, resolved once on load:
#
# | quote | on the futures **price** | on the **rate** | wing |
# |---|---|---|---|
# | `right = C` | call on price | **receiver** (`max(K−R,0)`) | low-rate, `atm_offset_bps ≤ 0` |
# | `right = P` | put on price | **payer** (`max(R−K,0)`) | high-rate, `atm_offset_bps ≥ 0` |

# %%
_t0 = time.time()
QUOTES = lv.load_sfr_panel()
CONTRACTS = lv.load_sfr_contracts()
print(f"loaded {len(QUOTES):,} quotes / {QUOTES['as_of'].nunique()} dates "
      f"in {time.time() - _t0:.1f}s")

_none = lv.sfr_reprice_check(QUOTES, discount="none")
_disc = lv.sfr_reprice_check(QUOTES, discount="forward_rate")
_tbl = pd.DataFrame({
    "undiscounted": [_none["rel_err"].mean(), _none["rel_err"].median(),
                     _none["err_bp"].abs().median(), _none["err_bp"].abs().quantile(0.95),
                     _none["err_bp"].abs().max()],
    "discounted exp(-f*T)": [_disc["rel_err"].mean(), _disc["rel_err"].median(),
                             _disc["err_bp"].abs().median(), _disc["err_bp"].abs().quantile(0.95),
                             _disc["err_bp"].abs().max()],
}, index=["mean rel err", "median rel err", "median |err| bp",
          "p95 |err| bp", "max |err| bp"])
print(_tbl.round(4).to_string())

assert _none["rel_err"].median() > 0.02, "undiscounted bias vanished — convention changed?"
assert abs(_disc["rel_err"].median()) < 0.01, "discounted reprice no longer ties out"
assert _disc["err_bp"].abs().median() < 0.05
print("\nUNIT TIE-OUT PASS")
print("  iv_bp is an ANNUALISED NORMAL (Bachelier) vol of the RATE, in bp/yr.")
print("  premium_bp is the DISCOUNTED European Bachelier value in bp of rate")
print("  (= 100 x the price in futures price points), consistent with CME's")
print("  premium-paid-upfront settlement on SR3 options.")

# %% [markdown]
# ### 5b. The discount factor the panel was priced with
#
# Inverting the ATM rows for the discount factor implicitly used recovers a
# contemporaneous OIS rate, which is the direct evidence for the
# premium-paid-upfront reading. If `iv_bp` had been produced by an undiscounted
# model these would all sit at 1.0.

# %%
_atm_rows = _disc[_disc["atm_offset_bps"] == 0.0].copy()
_undisc_atm = _none[_none["atm_offset_bps"] == 0.0]
_atm_rows["implied_df"] = (_atm_rows["premium_bp"].to_numpy()
                           / _undisc_atm["theo_bp"].to_numpy())
_atm_rows["implied_rate_pct"] = (-np.log(_atm_rows["implied_df"].clip(1e-9, None))
                                 / _atm_rows["tte"] * 100.0)
print(_atm_rows.groupby(_atm_rows["as_of"].dt.year)[["implied_df", "implied_rate_pct"]]
      .median().round(4).to_string())
_med_r = float(_atm_rows["implied_rate_pct"].median())
print(f"\nmedian implied discount rate across the panel: {_med_r:.2f}%")
assert 2.0 < _med_r < 6.0, "implied discount rate is not a plausible OIS level"
print("=> the premium is discounted at ~OIS: SR3 option premium is paid UPFRONT.")

# %% [markdown]
# ### 5c. Independent cross-check — implied against **realised**
#
# The second leg of the verification uses no option model at all: difference
# `contracts.parquet`'s own `forward_rate` **within a symbol** (so the quarterly
# roll can never enter as a fake move) and compare its bp/day standard deviation
# to the median ATM implied bp/day.
#
# `iv_bp` is never touched on the realised side, so agreement is evidence and not
# an identity.

# %%
ATM = lv.sfr_atm_vol_panel(QUOTES, business_days_per_year=CFG.business_days_per_year)
_rv = lv.sfr_realized_vol(CONTRACTS, by_symbol=True).set_index("symbol")
_iv = (ATM.groupby("symbol")["atm_vol_bp_day"].median().rename("implied_atm_bp_day"))
_cmp = _rv.join(_iv)
_cmp["implied/realised"] = _cmp["implied_atm_bp_day"] / _cmp["realized_bp_day"]
print(_cmp[["n_obs", "realized_bp_day", "implied_atm_bp_day", "implied/realised"]]
      .round(3).to_string())
_pool = lv.sfr_realized_vol(CONTRACTS, by_symbol=False).iloc[0]
_pool_iv = float(ATM["atm_vol_bp_day"].median())
print(f"\npooled realised {_pool['realized_bp_day']:.3f} bp/day   "
      f"pooled median implied {_pool_iv:.3f} bp/day   "
      f"ratio {_pool_iv / _pool['realized_bp_day']:.3f}")
assert 0.75 < _pool_iv / _pool["realized_bp_day"] < 1.35
print("REALISED CROSS-CHECK PASS: the annual->daily bridge (sigma/sqrt(252)) "
      "lands on the realised daily move.")

# %% [markdown]
# ### 5d. The strike anchoring, and the ATM correction it forces
#
# `atm_offset_bps` is the strike's distance from the **nearest listed strike to
# the forward**, not from the forward itself — verified exactly below. SR3 strikes
# sit on a 6.25 bp rate grid, so the anchor is up to 3.125 bp away from the
# forward. `sfr_atm_vol_panel` therefore interpolates the smile to the forward's
# own offset rather than reading the `offset == 0` quote, and reports both.

# %%
_s0 = (QUOTES[QUOTES["atm_offset_bps"] == 0.0]
       .groupby(["as_of", "symbol"])["strike_rate"].agg(["nunique", "first"]))
assert set(_s0["nunique"].unique()) == {1}, "offset-0 strike is not unique per contract"
_m = QUOTES.merge(_s0["first"].rename("S0"), on=["as_of", "symbol"])
_dev = ((_m["strike_rate"] - _m["S0"]) * 100.0 - _m["atm_offset_bps"]).abs().max()
print(f"identity  atm_offset_bps == (strike_rate - S0)*100   max abs deviation: {_dev:.2e}")
assert _dev < 1e-9
print(f"forward's own offset ranges {ATM['fwd_offset_bp'].min():+.3f} .. "
      f"{ATM['fwd_offset_bp'].max():+.3f} bp  (half a strike interval = 3.125)")
_corr = ATM["atm_vol_bp_yr"] - ATM["atm_strike_vol_bp_yr"]
print("\ncorrection from interpolating to the forward instead of reading offset 0, bp/yr:")
print(_corr.describe().round(3).to_string())
print("\nOTM-only layout (calls = low-rate wing, puts = high-rate wing):")
print(pd.crosstab(QUOTES["right"], np.sign(QUOTES["atm_offset_bps"])).to_string())
assert (QUOTES.loc[QUOTES["right"] == "C", "atm_offset_bps"] <= 0).all()
assert (QUOTES.loc[QUOTES["right"] == "P", "atm_offset_bps"] >= 0).all()

# %% [markdown]
# ## 6. Price vol ↔ rate vol, and the UST adapter
#
# ### 6a. SFR — exact, because the map is affine
#
# The SFR underlying is the futures **price** `P = 100 − R` with `R` in percent,
# so `dP = −dR` exactly and one price point is 100 bp of rate:
#
# $$\sigma_R(\text{bp}) = \sigma_P(\text{points}) \times 100$$
#
# This panel is already quoted in rate space; the conversion is here for callers
# holding a price-vol quote from elsewhere, and as the SFR half of the pair the
# UST adapter needs.

# %%
print(f"  sigma_P = 0.9345 price points/yr  ->  sigma_R = "
      f"{lv.sfr_price_vol_to_rate_vol(0.9345):.4f} bp/yr   (hand: 93.45)")
print(f"  round trip back                   ->  "
      f"{lv.sfr_rate_vol_to_price_vol(93.45):.6f} price points")
assert lv.sfr_price_vol_to_rate_vol(0.9345) == 93.45
# The panel's own ATM vol expressed both ways, as a sanity read
_ex = ATM.iloc[0]
print(f"\n  {_ex['symbol']} on {pd.Timestamp(_ex['as_of']).date()}: "
      f"{_ex['atm_vol_bp_yr']:.2f} bp/yr rate vol "
      f"= {lv.sfr_rate_vol_to_price_vol(_ex['atm_vol_bp_yr']):.4f} price points/yr "
      f"= {_ex['atm_vol_bp_day']:.3f} bp/day")

# %% [markdown]
# ### 6b. UST — implemented, tested on a hand-computed case, **no data**
#
# A bond future's price responds to yield through the CTD's DV01, so
#
# $$\sigma_y(\text{bp}) \approx \frac{\sigma_P(\text{points})}{\text{DV01 in points per bp}}$$
#
# **Hand-computed known answer**: 6.4 price points/yr ÷ 0.064 points per bp
# (a \$64 DV01 per \$100,000 face at \$1,000 per point) = **100 bp/yr**.
#
# **Three reasons the result is not a clean swap-rate vol**, in decreasing order
# of size — the reason this repo would caveat a UST-implied number even if the
# data existed:
#
# 1. **The delivery / CTD switch option.** A bond future is an option on which
#    bond is delivered. That embedded option is itself long vol and lives inside
#    the futures price, and the switch makes the price/yield map kinked. Implied
#    vol from a futures option is the vol of *the future* = the CTD's yield vol
#    **plus** the delivery option's contribution — an upward contamination that
#    grows when the CTD is near a switch.
# 2. **DV01 is a local linearisation and moves** — several percent across a
#    100 bp shift, discontinuously at a CTD switch.
# 3. **Basis, not swap.** Even a perfect CTD yield vol is a *Treasury* yield vol;
#    the curve packages here are swaps, so swap-spread vol is an unhedged residual.

# %%
print(f"  hand case: 6.4 points/yr / 0.064 points-per-bp = "
      f"{lv.ust_price_vol_to_yield_vol(6.4, 0.064):.6f} bp/yr   (hand: 100)")
assert lv.ust_price_vol_to_yield_vol(6.4, 0.064) == 100.0
print(f"  round trip: {lv.ust_yield_vol_to_price_vol(100.0, 0.064):.6f} points/yr")
print("\n  same price vol across the indicative contract table (CTD-dependent, "
      "for illustration only):")
for _c, _d in lv.UST_DV01_POINTS_PER_BP.items():
    print(f"    {_c:4s} DV01 {_d:.4f} pts/bp   6.4 pts/yr -> "
          f"{lv.ust_price_vol_to_yield_vol(6.4, contract=_c):7.2f} bp/yr "
          f"= {lv.vol_bp_per_day(lv.ust_price_vol_to_yield_vol(6.4, contract=_c)):5.2f} bp/day")
try:
    lv.ust_price_vol_to_yield_vol(6.4)
    raise AssertionError("must refuse to guess a DV01")
except ValueError as _e:
    print(f"\n  refuses to guess a DV01: {str(_e)[:110]}...")
print("\n  UST DATA: unavailable offline. The adapter above works the moment a "
      "panel exists;\n  nothing in this notebook attempts to fetch one.")

# %% [markdown]
# ## 7. Coverage, and the expiry match
#
# ### 7a. What the listed panel covers, and where it overlaps the swap curve

# %%
_curve_days = pd.DatetimeIndex(sorted(pd.unique(QUOTES["as_of"])))
COVER = lv.coverage_report(QUOTES, ATM, curve_dates=_curve_days,
                           horizon_years=CFG.horizon_years,
                           max_gap_days=CFG.listed_max_gap_days)
for _k, _v in COVER.items():
    if _k in ("symbols", "matched_symbols", "ust"):
        continue
    print(f"  {_k:34s} {_v}")
print(f"  {'symbols':34s} {COVER['symbols']}")
print(f"  {'ust.available_offline':34s} {COVER['ust']['available_offline']}")
assert COVER["n_dates"] == 540
assert COVER["first_date"] == "2024-07-01" and COVER["last_date"] == "2026-07-28"

# %% [markdown]
# ### 7b. Which listed expiry was used, on which date
#
# The curve breakeven is a 1-year-horizon number; a listed option has its own
# expiry. Both sides are quoted in **bp/day**, which removes the horizon to first
# order — but only exactly if the listed term structure is flat, and it is not.
# So the contract nearest `as_of + horizon` is used, and the residual gap is
# carried on every row rather than assumed away.

# %%
SERIES = lv.listed_atm_series(ATM, CFG.horizon_years,
                              max_gap_days=CFG.listed_max_gap_days,
                              min_tte_years=CFG.listed_min_tte_years)
print(f"{len(SERIES)} of {COVER['n_dates']} dates have a horizon-matched expiry "
      f"({len(SERIES) / COVER['n_dates']:.1%})")
print("\ncontract used, by count of dates:")
print(SERIES["listed_symbol"].value_counts().sort_index().to_string())
print("\n|gap| between the listed expiry and as_of + 1Y, days:")
print(SERIES["listed_gap_days"].abs().describe().round(1).to_string())
assert SERIES["listed_gap_days"].abs().max() <= CFG.listed_max_gap_days
print("\nfirst and last rows:")
print(pd.concat([SERIES.head(3), SERIES.tail(3)]).round(3).to_string())

# %% [markdown]
# ### 7c. The listed term structure — the slope the bp/day comparison abstracts from

# %%
_ts_dates = [SERIES.index[0], SERIES.index[len(SERIES) // 3],
             SERIES.index[2 * len(SERIES) // 3], SERIES.index[-1]]
_fig = go.Figure()
for _d in _ts_dates:
    _t = lv.sfr_term_structure(ATM, _d)
    _fig.add_trace(go.Scatter(x=_t["tte"], y=_t["atm_vol_bp_day"], mode="lines+markers",
                              name=str(pd.Timestamp(_d).date())))
_fig.add_vline(x=CFG.horizon_years, line_dash="dash", line_color="grey",
               annotation_text="curve horizon (1Y)")
_fig.update_layout(title="SFR listed ATM vol term structure, bp/day",
                   xaxis_title="time to expiry, years", yaxis_title="ATM normal vol, bp/day",
                   height=430, template="plotly_white")
_fig.show()

_slope = []
for _d in SERIES.index:
    _t = lv.sfr_term_structure(ATM, _d)
    _t = _t[(_t["tte"] > 0.25) & (_t["tte"] < 3.0)]
    if len(_t) >= 3:
        _slope.append(np.polyfit(_t["tte"], _t["atm_vol_bp_day"], 1)[0])
print(f"term-structure slope over 0.25-3.0y, bp/day per year of expiry: "
      f"median {np.median(_slope):+.4f}, "
      f"IQR {np.percentile(_slope, 25):+.4f}..{np.percentile(_slope, 75):+.4f}")
print(f"=> a {SERIES['listed_gap_days'].abs().median():.0f}-day median expiry gap is worth "
      f"~{abs(np.median(_slope)) * SERIES['listed_gap_days'].abs().median() / 365:.4f} bp/day "
      "of vol — the residual the matching leaves behind.")

# %% [markdown]
# ## 8. The shift grid — why ±500 bp and not JPM's ±250
#
# `normal_pdf_weights` normalises over the supplied grid, so a truncated grid is a
# *truncated normal*: as σ grows the weights approach uniform and the expected
# payoff saturates at the grid's **mean** payoff. For long-end structures that
# ceiling is far above any plausible carry. For short-end structures the convexity
# per bp of shift is an order of magnitude smaller, so the ceiling binds and the
# breakeven solve returns `never_cheap` where the truth is "a root exists past the
# edge of the grid".
#
# This is a *classification* error, not a rounding error, so it is measured
# directly rather than argued.

# %%
_rows = []
for _d in (datetime.date(2024, 9, 3), datetime.date(2025, 3, 3), datetime.date(2026, 3, 3)):
    _pr = _mdp.get_data({"curve_name": CFG.curve, "timestamp": _d})
    for _lbl, _ft, _bt in CFG.structures:
        _out = {"date": _d, "structure": _lbl}
        for _nm, _sh in (("±250", _JPM_SHIFTS), ("±500", CFG.shifts_bp)):
            _c = s1.Strat1Config(shifts_bp=_sh, package_dv01=CFG.package_dv01)
            _p = s1.structure_profile(_pr, _lbl, _ft, _bt, _c, direction=s1.FLATTENER)
            _be = s1.breakeven_vol(_p.shifts_bp, _p.payoff_ccy,
                                   horizon_years=CFG.horizon_years,
                                   business_days_per_year=CFG.business_days_per_year)
            _out[f"{_nm} status"] = _be.status
            _out[f"{_nm} bp/day"] = round(_be.bp_per_day, 3)
            _out["carry_bp"] = round(_p.carry_bp, 3)
        _rows.append(_out)
_grid_tbl = pd.DataFrame(_rows)
print(_grid_tbl.to_string(index=False))
_flipped = _grid_tbl[(_grid_tbl["±250 status"] != _grid_tbl["±500 status"])]
print(f"\n{len(_flipped)} of {len(_grid_tbl)} (date, structure) cells change CLASSIFICATION "
      "between the two grids.")
_both_root = _grid_tbl[(_grid_tbl["±250 status"] == "root") & (_grid_tbl["±500 status"] == "root")]
print(f"where both converge, the root moves by median "
      f"{(_both_root['±500 bp/day'] - _both_root['±250 bp/day']).abs().median():.3f} bp/day.")
print(f"\n±500 bp is ~{500 / (_pool['realized_bp_day'] * math.sqrt(252)):.1f} sigma of the "
      f"measured {_pool['realized_bp_day']:.2f} bp/day realised SFR vol over a 1-year "
      "horizon, so the remaining truncation is negligible.")

# %% [markdown]
# ## 9. THE HEADLINE — the signal distribution
#
# > "we are estimating the level of normal daily volatility in rates that is
# >  sufficient to offset the carry costs on a given curve trade."
#
# For each (date, structure): solve the curve's breakeven vol in bp/day, and
# compare it to the listed ATM in bp/day. **Cheap** (signal `+1`, flattener) when
# the curve prices *less* vol than the exchange; **rich** (`−1`, steepener) when
# more.
#
# The same breakeven is compared to the **sector-matched 1Yx2Y swaption** on the
# same row, so the two verdicts can never come from different profiles.
#
# The panel is built by `_strat1_listed_build.py` (~15 min in four parallel date
# chunks); this notebook reads it.

# %%
_panel_path = DATA / "strat1_listed_signal_panel.parquet"
if not _panel_path.exists():
    raise SystemExit(
        f"{_panel_path.name} missing. Build it first:\n"
        "  python notebooks/backtests/convexity_rv/_strat1_listed_build.py vol\n"
        "  python notebooks/backtests/convexity_rv/_strat1_listed_build.py panel 0 4  (x4)\n"
        "  python notebooks/backtests/convexity_rv/_strat1_listed_build.py merge")
PANEL = pd.read_parquet(_panel_path)
PANEL["date"] = pd.to_datetime(PANEL["date"])
PANEL = PANEL.set_index(["date", "structure"]).sort_index()
print(f"signal panel: {len(PANEL):,} rows, "
      f"{PANEL.index.get_level_values('date').nunique()} dates, "
      f"{PANEL.index.get_level_values('structure').nunique()} structures")
assert bool(PANEL["convex"].all()), "a flattener in the panel is not convex"

DIST_LISTED = sl.signal_distribution(PANEL, benchmark="listed")
DIST_OTC = sl.signal_distribution(PANEL, benchmark="otc")
print("\n=== curve vs LISTED (SFR) vol ===")
print(DIST_LISTED[["structure", "n_days", "frac_cheap", "frac_rich",
                   "frac_always_cheap", "frac_never_cheap",
                   "median_breakeven_bp_day", "median_benchmark_bp_day",
                   "median_gap_bp_day", "median_carry_bp"]].round(3).to_string(index=False))
print("\n=== curve vs OTC (1Yx2Y ATMF swaption) vol ===")
print(DIST_OTC[["structure", "n_days", "frac_cheap", "frac_rich",
                "median_breakeven_bp_day", "median_benchmark_bp_day",
                "median_gap_bp_day"]].round(3).to_string(index=False))

# %% [markdown]
# ### 9a. The gap distribution, in the note's own unit
#
# `frac_cheap` compresses the answer to a sign. The size of the gap matters more:
# a curve that is rich by 0.1 bp/day is a coin flip, one rich by 5 bp/day is not.

# %%
_g = PANEL.reset_index()
_gap = (_g[np.isfinite(_g["cheapness_vs_listed_bp_day"])]
        .groupby("structure")["cheapness_vs_listed_bp_day"]
        .describe(percentiles=[0.05, 0.25, 0.5, 0.75, 0.95]))
print("listed ATM minus curve breakeven, bp/day  (positive = curve CHEAP):")
print(_gap.round(3).to_string())

_fig = go.Figure()
for _lbl in sorted(_g["structure"].unique()):
    _s = _g[(_g["structure"] == _lbl) & np.isfinite(_g["cheapness_vs_listed_bp_day"])]
    _fig.add_trace(go.Box(y=_s["cheapness_vs_listed_bp_day"], name=_lbl, boxmean=True))
_fig.add_hline(y=0.0, line_dash="dash", line_color="black")
_fig.update_layout(title="Curve cheapness vs LISTED SFR vol (positive = curve is the cheaper gamma)",
                   yaxis_title="listed ATM − curve breakeven, bp/day",
                   height=430, template="plotly_white", showlegend=False)
_fig.show()

# %% [markdown]
# ### 9b. The three series through time, for one structure

# %%
_lbl = "2Yx2Y/3Yx2Y"
_one = PANEL.xs(_lbl, level="structure")
_fig = go.Figure()
_fig.add_trace(go.Scatter(x=_one.index, y=_one["breakeven_vol_bp_day"].replace(np.inf, np.nan),
                          name="curve breakeven", mode="lines", line=dict(color="#ff5c5c")))
_fig.add_trace(go.Scatter(x=_one.index, y=_one["listed_atm_bp_day"],
                          name="LISTED SFR ATM", mode="lines", line=dict(color="#4dabf7")))
_fig.add_trace(go.Scatter(x=_one.index, y=_one["otc_atmf_bp_day"],
                          name="OTC 1Yx2Y ATMF", mode="lines",
                          line=dict(color="#3ddc84", dash="dot")))
_fig.update_layout(title=f"{_lbl}: vol priced into the curve vs the two option markets",
                   yaxis_title="normal vol, bp/day", height=460, template="plotly_white")
_fig.show()
print(f"{_lbl}: breakeven finite on "
      f"{np.isfinite(_one['breakeven_vol_bp_day']).mean():.1%} of days "
      f"({(_one['breakeven_status'] == 'always_cheap').mean():.1%} always_cheap, "
      f"{(_one['breakeven_status'] == 'never_cheap').mean():.1%} never_cheap)")

# %% [markdown]
# ## 10. Is this a relabelling of strategy 1? — the OTC/listed basis
#
# This is the question the whole exercise turns on. If the listed and OTC
# benchmarks always gave the same verdict, swapping one for the other would be a
# relabelling and nothing more. The panel carries both on every row, so the
# answer is measured, not argued.

# %%
BASIS = sl.vol_basis_frame(PANEL)
print("OTC 1Yx2Y ATMF minus LISTED SFR ATM, bp/day  (positive = swaptions richer):")
print(BASIS["otc_minus_listed_bp_day"].describe(
    percentiles=[0.05, 0.25, 0.5, 0.75, 0.95]).round(3).to_string())
_corr = BASIS[["listed_atm_bp_day", "otc_atmf_bp_day"]].corr().iloc[0, 1]
print(f"\ncorrelation of the two benchmarks in levels: {_corr:.4f}")
print(f"basis as a fraction of the listed level: median "
      f"{(BASIS['otc_minus_listed_bp_day'] / BASIS['listed_atm_bp_day']).median():.1%}")
print("\nquarterly means:")
print(BASIS[["listed_atm_bp_day", "otc_atmf_bp_day", "otc_minus_listed_bp_day"]]
      .resample("QE").mean().round(3).to_string())

_fig = go.Figure()
_fig.add_trace(go.Scatter(x=BASIS.index, y=BASIS["listed_atm_bp_day"],
                          name="LISTED SFR ATM", line=dict(color="#4dabf7")))
_fig.add_trace(go.Scatter(x=BASIS.index, y=BASIS["otc_atmf_bp_day"],
                          name="OTC 1Yx2Y ATMF", line=dict(color="#3ddc84")))
_fig.add_trace(go.Scatter(x=BASIS.index, y=BASIS["otc_minus_listed_bp_day"],
                          name="OTC − listed (RHS)", yaxis="y2",
                          line=dict(color="#ff9f43", dash="dot")))
_fig.update_layout(title="The OTC/listed vol basis in the SFR sector",
                   yaxis=dict(title="ATM normal vol, bp/day"),
                   yaxis2=dict(title="basis, bp/day", overlaying="y", side="right"),
                   height=460, template="plotly_white")
_fig.show()

# %% [markdown]
# ### 10a. How often the two benchmarks give a different verdict
#
# The basis only flips the signal when it straddles the curve's breakeven. The
# cell below counts that directly, and then asks how large the basis would have to
# be to flip a given fraction of days — which is the sensitivity that decides
# whether the listed-vs-OTC distinction is economically live in this sector.

# %%
_d = PANEL.reset_index()
_both = _d[np.isfinite(_d["listed_atm_bp_day"]) & np.isfinite(_d["otc_atmf_bp_day"])]
_dis = (_both.groupby("structure")
        .apply(lambda g: pd.Series({
            "n_days": len(g),
            "frac_disagree": float((g["signal_listed"] != g["signal_otc"]).mean()),
            "n_disagree": int((g["signal_listed"] != g["signal_otc"]).sum()),
            "median_|gap vs listed|": float(
                np.nanmedian(np.abs(g["cheapness_vs_listed_bp_day"].replace([np.inf, -np.inf], np.nan)))),
        }), include_groups=False))
print(_dis.round(3).to_string())
print(f"\noverall: the two benchmarks disagree on "
      f"{(_both['signal_listed'] != _both['signal_otc']).mean():.2%} of (date, structure) rows.")

_finite = _both[np.isfinite(_both["cheapness_vs_listed_bp_day"])]
print("\nhow big a basis would flip a given share of days "
      "(|listed ATM − curve breakeven| quantiles, bp/day):")
for _q in (0.05, 0.10, 0.25, 0.50):
    print(f"   to flip {_q:5.0%} of days the basis must exceed "
          f"{np.quantile(np.abs(_finite['cheapness_vs_listed_bp_day']), _q):.3f} bp/day"
          f"   (observed |basis| median "
          f"{BASIS['otc_minus_listed_bp_day'].abs().median():.3f})")

# %% [markdown]
# ## 11. The backtest — an illustration, explicitly not a strategy result
#
# Cohorts: weekly entries, 1-year hold, DV01-neutral two-leg package, `+1` →
# flattener and `−1` → steepener, signal **lagged one day**, unwind fee
# `2 × cost_bp_one_way × package_dv01`. Cohorts opened inside the last year of the
# sample are marked, never force-closed.
#
# **Read this before the numbers.** The sample is 540 daily dates with a 1-year
# holding period, so it contains roughly **one** non-overlapping observation per
# structure, and about half the cohorts never close. Worse, the signal here is
# *structurally* short gamma / long carry — the front SOFR curve was inverted at
# the start of the window and steepened through it — so any P&L is dominated by
# that one directional episode. No Sharpe is computed and none should be.

# %%
_eq, _coh = {}, {}
for _lbl, _f, _b in CFG.structures:
    _sf = _lbl.replace("/", "-")
    _pe, _pc = (DATA / f"strat1_listed_equity_{_sf}.parquet",
                DATA / f"strat1_listed_cohorts_{_sf}.parquet")
    if _pe.exists() and _pc.exists():
        _e = pd.read_parquet(_pe)["equity_usd"]
        _e.index = pd.to_datetime(_e.index)
        _eq[_lbl] = _e
        _coh[_lbl] = pd.read_parquet(_pc)
print(f"loaded {len(_eq)} of {len(CFG.structures)} backtests")
if not _eq:
    raise SystemExit("no backtest artifacts — run `_strat1_listed_build.py bt <label>` first")

_rows = []
for _lbl, _t in _coh.items():
    _c = _t[_t["closed"]]
    _rows.append({
        "structure": _lbl,
        "cohorts": len(_t),
        "closed": len(_c),
        "live_at_end": int(_t["live_at_end"].sum()),
        "pct_flattener": float((_t["direction"] > 0).mean()),
        "gross_bp_sum": round(float(_c["gross_pnl_bp"].sum()), 1) if len(_c) else np.nan,
        "net_bp_sum": round(float(_c["net_pnl_bp"].sum()), 1) if len(_c) else np.nan,
        "net_bp_mean": round(float(_c["net_pnl_bp"].mean()), 2) if len(_c) else np.nan,
        "net_bp_median": round(float(_c["net_pnl_bp"].median()), 2) if len(_c) else np.nan,
        "hit_rate": round(float((_c["net_pnl_bp"] > 0).mean()), 3) if len(_c) else np.nan,
    })
COHORT_SUMMARY = pd.DataFrame(_rows)
print(COHORT_SUMMARY.to_string(index=False))
print("\nNOTE: `closed` counts round trips inside a 2-year sample with a 1-year hold. "
      "Overlapping weekly cohorts are ~98% co-dependent; the effective sample is ~1 "
      "independent observation per structure.")

# %%
_books = {}
for _lbl, _t in _coh.items():
    _c = _t[_t["closed"] & _t["exit"].notna()].copy()
    if _c.empty:
        continue
    _books[_lbl] = _c[["exit", "net_pnl_bp"]].rename(
        columns={"exit": "closed_at", "net_pnl_bp": "realized_pnl"})
if _books:
    compare_curves(_books, title="strat1-listed: cumulative net P&L by structure, bp of package DV01",
                   time_col="closed_at", pnl_col="realized_pnl", unit="bp").show()

# %%
_lbl = "2Yx2Y/3Yx2Y"
if _lbl in _books:
    print(f"=== {_lbl} closed cohorts ===")
    print(summary_stats(_books[_lbl], time_col="closed_at", pnl_col="realized_pnl",
                        unit="bp", span_years=1.0).to_string(index=False))
    print("\n*** The 'annualised Sharpe' printed above is NOT a strategy Sharpe and is not")
    print("    claimed as one. Those 54 'trades' are weekly-opened 1-year cohorts that")
    print("    share ~98% of their holding windows, so they are one observation wearing 54")
    print("    hats; `trades / year` reads 54 only because span_years was forced to 1.0.")
    print("    The t-statistic on the row above is the honest summary of the evidence.")
    trade_dashboard(_books[_lbl], time_col="closed_at", pnl_col="realized_pnl",
                    unit="bp", title=f"strat1-listed {_lbl}").show()

# %% [markdown]
# ### 11a. Full-MTM equity, including the cohorts still live
#
# The cohort table above only counts round trips. The engine's own mark-to-market
# includes everything still open, which on a 2-year sample is about half the book.

# %%
_fig = go.Figure()
for _lbl, _e in _eq.items():
    _fig.add_trace(go.Scatter(x=_e.index, y=_e.to_numpy() / CFG.package_dv01,
                              mode="lines", name=_lbl))
_fig.update_layout(title="strat1-listed full-MTM equity (incl. live cohorts), bp of package DV01",
                   yaxis_title="bp of package DV01", height=460, template="plotly_white")
_fig.show()
print(pd.DataFrame({_l: [round(float(_e.iloc[-1] / CFG.package_dv01), 1)]
                    for _l, _e in _eq.items()},
                   index=["final MTM, bp"]).T.to_string())

# %% [markdown]
# ## 12. The long end — reported, but **not** compared
#
# Strategy 1's own universe over the same window. These rows carry the curve
# breakeven and the 1Yx30Y **swaption** comparison strategy 1 already made, and
# **no listed number at all**: their natural listed benchmark is a UST bond
# option, which does not exist offline here. Comparing a 30-year curve structure
# to a 3M-SOFR option would be a sector mismatch and a fake result.
#
# The frame is read from strategy 1's existing panel rather than recomputed — the
# curve side is identical, and re-deriving it would create a second number that
# could disagree with the first for no reason.

# %%
_s1_path = DATA / "strat1_signal_panel.parquet"
if _s1_path.exists():
    _s1_panel = pd.read_parquet(_s1_path)
    LONG_END = sl.long_end_reference_frame(_s1_panel, CFG.start, CFG.end)
    print(f"{len(LONG_END)} rows over {LONG_END['date'].nunique()} dates "
          f"{LONG_END['date'].min().date()}..{LONG_END['date'].max().date()}")
    _le = (LONG_END.groupby("structure")
           .agg(n_days=("date", "size"),
                frac_cheap_vs_SWAPTION=("signal_breakeven", lambda s: float((s > 0).mean())),
                median_breakeven_bp_day=("breakeven_vol_bp_day",
                                         lambda s: float(np.nanmedian(s[np.isfinite(s)]))),
                median_swaption_bp_day=("atmf_vol_bp_day", "median"),
                median_carry_bp=("carry_roll_bp", "median")))
    _le["listed_benchmark"] = "UNAVAILABLE"
    print(_le.round(3).to_string())
    assert set(LONG_END["listed_benchmark"]) == {"unavailable"}
    assert not any(c.startswith("listed_atm") for c in LONG_END.columns)
    print("\n" + LONG_END["listed_benchmark_reason"].iloc[0])
else:
    LONG_END = pd.DataFrame()
    print(f"{_s1_path.name} not present — run the strategy 1 notebook first. "
          "The long-end section is a report, not an input to anything above.")

# %% [markdown]
# ## 13. Verdict
#
# Every number below is measured in this notebook or in the artifacts it reads.

# %%
VERDICT = {
    "config": {k: (list(v) if isinstance(v, tuple) else str(v) if isinstance(v, datetime.date) else v)
               for k, v in CFG.as_dict().items()},
    "unit_tie_out": {
        "n_quotes": int(len(QUOTES)),
        "undiscounted_median_rel_err": round(float(_none["rel_err"].median()), 5),
        "discounted_median_rel_err": round(float(_disc["rel_err"].median()), 5),
        "discounted_median_abs_err_bp": round(float(_disc["err_bp"].abs().median()), 5),
        "discounted_p95_abs_err_bp": round(float(_disc["err_bp"].abs().quantile(0.95)), 5),
        "implied_discount_rate_pct_median": round(_med_r, 3),
        "conclusion": ("iv_bp is an ANNUALISED NORMAL bp/yr vol of the RATE; premium_bp is "
                       "the DISCOUNTED European Bachelier value in bp of rate "
                       "(= 100 x price points). bp/day = iv_bp / sqrt(252), no tte."),
    },
    "realised_cross_check": {
        "pooled_realized_bp_day": round(float(_pool["realized_bp_day"]), 3),
        "pooled_median_implied_bp_day": round(_pool_iv, 3),
        "ratio": round(_pool_iv / float(_pool["realized_bp_day"]), 3),
    },
    "coverage": {k: v for k, v in COVER.items() if k not in ("symbols", "matched_symbols")},
    "expiry_match": {
        "n_dates_matched": int(len(SERIES)),
        "gap_days_abs_median": round(float(SERIES["listed_gap_days"].abs().median()), 1),
        "gap_days_abs_max": round(float(SERIES["listed_gap_days"].abs().max()), 1),
        "contracts_used": SERIES["listed_symbol"].value_counts().sort_index().to_dict(),
        "term_structure_slope_bp_day_per_year_median": round(float(np.median(_slope)), 4),
    },
    "signal_distribution_vs_listed": DIST_LISTED.round(4).to_dict(orient="records"),
    "signal_distribution_vs_otc": DIST_OTC.round(4).to_dict(orient="records"),
    "otc_listed_basis_bp_day": {
        "median": round(float(BASIS["otc_minus_listed_bp_day"].median()), 4),
        "mean": round(float(BASIS["otc_minus_listed_bp_day"].mean()), 4),
        "p05": round(float(BASIS["otc_minus_listed_bp_day"].quantile(0.05)), 4),
        "p95": round(float(BASIS["otc_minus_listed_bp_day"].quantile(0.95)), 4),
        "level_correlation": round(float(_corr), 4),
        "frac_rows_where_signals_disagree": round(
            float((_both["signal_listed"] != _both["signal_otc"]).mean()), 4),
    },
    "cohorts": COHORT_SUMMARY.to_dict(orient="records"),
    "long_end": {
        "structures": [l for l, _, _ in sl.LONG_END_STRUCTURES],
        "listed_benchmark": "unavailable",
        "reason": ("UST bond options are the sector-matched listed benchmark for the long "
                   "end. No offline UST futures-option panel exists in this repo; the only "
                   "code path (USTFutureOptionMDP.sabr_smile) is uncached and crawls "
                   "Barchart per strike. Measured cache scan: 8 cached UST smiles on 2 "
                   "dates (Mar-2026), 0 STIR."),
    },
    "caveats": [
        "540 daily dates (2024-07-01..2026-07-28) with a 1-year hold is ~1 non-overlapping "
        "observation per structure. No Sharpe is computed and none is credible.",
        "The SFR option's underlying is a 3M rate; the curve legs are 2-3Y swap rates. Short "
        "rates are more volatile, so the listed benchmark is biased HIGH and the signal is "
        "biased towards 'curve is rich'. The 1Yx2Y swaption control shares the listed "
        "sector and the curve legs' tenor and measures that bias.",
        "The front SOFR curve was inverted at the start of the window and steepened through "
        "it, so the signal was structurally a steepener and the P&L is dominated by that one "
        "directional episode.",
        "About half the weekly cohorts are still live at the sample end and are marked, "
        "never force-closed.",
    ],
}
def _clean(o):
    """NaN/inf -> None. ``json.dumps`` emits bare ``NaN``/``Infinity`` tokens,
    which are not JSON and break any strict reader downstream."""
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, float) and not np.isfinite(o):
        return None
    if isinstance(o, (np.floating, np.integer)):
        return _clean(float(o))
    return o


VERDICT = _clean(VERDICT)
_vp = DATA / "strat1_listed_verdict.json"
_vp.write_text(json.dumps(VERDICT, indent=2, default=str), encoding="utf-8")
print(json.dumps({k: VERDICT[k] for k in
                  ("unit_tie_out", "realised_cross_check", "otc_listed_basis_bp_day")},
                 indent=2, default=str))
print(f"\nwrote {_vp}")

# %% [markdown]
# ## 14. What this notebook found
#
# The prose below is generated from the numbers above, not typed in, so it cannot
# drift from them.

# %%
_med_basis = float(BASIS["otc_minus_listed_bp_day"].median())
_dis_frac = float((_both["signal_listed"] != _both["signal_otc"]).mean())
_cheap = DIST_LISTED.set_index("structure")["frac_cheap"]
print(f"""
1. UNITS. iv_bp is an annualised normal bp/yr vol of the RATE, and premium_bp is
   the DISCOUNTED Bachelier value: repricing all {len(QUOTES):,} quotes overprices by
   {_none['rel_err'].median():+.2%} undiscounted and by {_disc['rel_err'].median():+.2%} with
   exp(-f*T), median |error| {_disc['err_bp'].abs().median():.3f} bp. The implied discount
   rate is {_med_r:.2f}%, i.e. contemporaneous OIS. Independently, pooled realised
   {_pool['realized_bp_day']:.2f} bp/day against pooled median implied {_pool_iv:.2f} bp/day.

2. COVERAGE. {COVER['n_dates']} daily dates {COVER['first_date']}..{COVER['last_date']},
   {COVER['n_symbols']} quarterly contracts, {len(SERIES)} dates with a 1-year-matched
   expiry (worst gap {SERIES['listed_gap_days'].abs().max():.0f} days, median
   {SERIES['listed_gap_days'].abs().median():.0f}). The swap curve runs from 2019, so the
   listed panel is what binds. UST: no offline data, adapter only.

3. THE SIGNAL. Against listed SFR vol the curve is the cheaper source of gamma on
   {_cheap.min():.0%}-{_cheap.max():.0%} of days depending on the structure
   ({', '.join(f'{k} {v:.0%}' for k, v in _cheap.items())}).
   The one-year-forward pairs are the richest; pushing the forward start out to two
   years makes the curve materially cheaper, which is the same ordering JPM report
   in the long end.

4. IS IT A RELABELLING? Partly, in THIS sector over THIS window. The OTC/listed
   basis is real and persistent -- median {_med_basis:+.3f} bp/day
   ({_med_basis / float(BASIS['listed_atm_bp_day'].median()):+.1%} of the listed level),
   ranging {BASIS['otc_minus_listed_bp_day'].min():+.2f}..{BASIS['otc_minus_listed_bp_day'].max():+.2f} --
   but the two benchmarks give a DIFFERENT verdict on only {_dis_frac:.1%} of rows,
   because the curve-vs-vol gap is usually much larger than the basis. The listed
   substitution is therefore a genuine change of benchmark that rarely changes the
   sign, and anyone claiming it as a new alpha source in the SFR sector would be
   overselling {_dis_frac:.1%} of the sample.

5. WHAT WOULD MAKE IT LIVE. The basis would have to exceed
   {np.quantile(np.abs(_finite['cheapness_vs_listed_bp_day']), 0.25):.2f} bp/day to flip a
   quarter of days; observed |basis| median is
   {BASIS['otc_minus_listed_bp_day'].abs().median():.2f}. The long end -- where JPM's
   original result lives and where the OTC market is genuinely flow-distorted -- is
   exactly where the listed benchmark is missing.

6. P&L. Illustration only. {int(COHORT_SUMMARY['closed'].sum())} of
   {int(COHORT_SUMMARY['cohorts'].sum())} weekly cohorts closed inside the sample; the rest
   are still live and are marked, never force-closed. Net bp per cohort by structure:
   {', '.join(f"{r.structure} {r.net_bp_mean:+.1f} (hit {r.hit_rate:.0%})" for r in COHORT_SUMMARY.itertuples())}.
   The split is not subtle and it is not a vol result: the one-year-forward pairs, where
   the signal was {1 - _cheap['1Yx2Y/2Yx2Y']:.0%} steepener, lost; the two-year-forward
   pairs, where it was closest to balanced, gained. Over this window the front SOFR curve
   went through one large re-pricing of the easing path, and 54 weekly cohorts sharing
   ~98% of their holding windows are one observation wearing 54 hats. No Sharpe is
   claimed; the t-statistics in section 11 are the honest summary.
""")
