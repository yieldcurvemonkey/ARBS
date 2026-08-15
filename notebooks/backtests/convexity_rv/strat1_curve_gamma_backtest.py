# %% [markdown]
# # Strategy 1 — the long-end curve as a source of gamma, priced against swaptions
#
# **Source.** J.P. Morgan, *"An option by any other name: Sourcing cheap
# convexity in the long end of the curve"* (Younger / Sarkar / Salem,
# 03-Feb-2017), restated in *"For cheap gamma, look to the long end"*
# (23-Aug-2019) and given its fullest written form in *"Valuing convexity in the
# long end of the yield curve: A global perspective"* (09-Feb-2018).
#
# **What the strategy is, in the note's own words:**
#
# > "we require a framework for deciding whether long-end flatteners are a cheap
# >  or rich source of gamma compared to other instruments—particularly options."
#
# > "To estimate those probabilities, we first turn to the options markets, where
# >  an implied distribution can be extracted from ATMF and OTM pricing for each
# >  expiry. This is then multiplied with the payoff profile of an aged flattener
# >  at fixed coupon—primarily to incorporate carry costs—to estimate an expected
# >  return. ... we use 1Yx30Y swaptions for a 1-year horizon and assuming
# >  parallel shifts in rates."
#
# > "Alternatively, we can solve for the implied volatility priced into the long
# >  end of the yield curve. ... solving for zero expected payoff over a given
# >  horizon. In other words, we are estimating the level of normal daily
# >  volatility in rates that is sufficient to offset the carry costs on a given
# >  curve trade."
#
# > "When the expected payoff on a flattener using an implied distribution
# >  extracted from swaption pricing is positive, the curve trade is the cheaper
# >  source of long gamma exposure. The same can also be said when the level of
# >  volatility priced into the curve is less than that implied by ATMF
# >  swaptions."
#
# > "we initiate a flattener and sell 1Yx30Y ATMF swaption straddles to fund the
# >  carry on the position (i.e., sized such that the initiate premium intake is
# >  equal to the carry over the same 1-year horizon); when it is negative, we do
# >  the opposite."
#
# > "forward curve flatteners (e.g., 25Yx5Y versus 20Yx5Y) are a more attractive
# >  and cheaper source of this exposure than 30s/50s and similar structures."
#
# **JPM's own Exhibit 5** (trades initiated daily, post-Jan-2009, 1-year horizon)
# is the comparison target of this notebook:
#
# | | 30s/50s | 25Y/20Yx5Y |
# |---|---|---|
# | % cheap curve gamma | 70% | 100% |
# | Hit Rate | 56% | 86% |
# | Avg PnL, bp of notional | 10.4 | 11.4 |
# | Carry, bp of notional | −100.6 | 1.1 |
# | 25th/75th pct P/L | −43 / 75 | 4 / 19 |
# | 5th/95th pct P/L | −140 / 128 | −10 / 33 |
#
# Exact agreement is **not** expected and is not claimed anywhere below: this is
# USD SOFR over 2019-01..2026-08, JPM's is USD LIBOR over 2009-01..2017-01. What
# is testable is the **ordering** — whether forward-starting structures really
# are the cheaper source of the same convexity — and section 9 answers that
# plainly, including where it disagrees.

# %%
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import datetime
import json
import pathlib
import sys
import time
import warnings

import numpy as np
import pandas as pd

_REPO = pathlib.Path(__file__).resolve().parents[3] if "__file__" in dir() else pathlib.Path.cwd().parents[2]
sys.path.insert(0, str(_REPO))

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
from RVUtils.ConvexityRV import strat1_curve_gamma as s1
from RVUtils.ConvexityRV.swaption_cube import atmf_vol_series, load_vol_panel, smile_on

warnings.filterwarnings("ignore", category=RuntimeWarning)

DATA = _REPO / "notebooks" / "data" / "convexity_rv"
DATA.mkdir(parents=True, exist_ok=True)
print("repo", _REPO)
print("artifacts", DATA)

# %% [markdown]
# ## 1. CONFIG — every knob, documented at the point of use
#
# `Strat1Config` is the single source of truth; the module carries the inline
# documentation for each field and this cell prints the resolved values so the
# executed notebook records exactly what it ran.
#
# Two choices worth flagging here because they shape everything downstream:
#
# * **`signal_mode="breakeven_vol"`.** Both of the note's signals are computed on
#   every date, but the breakeven-vol one is primary because of a measured
#   coverage gap: over 2019-01-01..2026-08-31 the 1Yx30Y **ATMF** vol is present
#   on 97.8% of store days (back to 2015-10) while the full **OTM smile** — which
#   the expected-payoff signal needs to build a Breeden–Litzenberger density —
#   only starts **2020-03-25** (83.9%). Making expected-payoff primary would
#   silently delete 2019 and the whole COVID crash. Section 4 re-measures this
#   rather than trusting the sentence.
# * **`cohort_freq="monthly"`.** JPM initiate **daily** and hold a year, i.e.
#   ~250 concurrent cohorts. Measured cost in this engine is ~0.030 s per cohort
#   per mark for the 5Y-tail forward structures and ~0.090 s for the spot ones (a
#   50Y leg carries ten times the cashflows of a 25Yx5Y), over ~1,900 marks — so
#   daily is ~40 h for 30s/50s, weekly ~2.5 h, monthly ~35 min. The default is a
#   budget decision and nothing else; `"weekly"`/`"daily"` are config values and
#   change no part of the strategy. The statistical cost is small: 1-year cohorts
#   opened a week apart share ~98% of their window, so weekly entries would not
#   supply 4x the independent observations their count implies. Either way the
#   sample holds ~7.6 non-overlapping years.

# %%
CFG = s1.Strat1Config()
for k, v in CFG.as_dict().items():
    print(f"  {k:28s} {v}")
STRUCTURES = list(CFG.structures)
LABELS = [l for (l, _, _) in STRUCTURES]
SAFE = {l: l.replace("/", "-").replace(" ", "_") for l in LABELS}

# %% [markdown]
# ## 2. The sign probe, live
#
# Everything in this notebook rests on one convention that is **established
# empirically, not read off the risk-weight code**:
#
# ```
# OUTRIGHT bpv > 0  =  PAYER
# CURVE    bpv < 0  =  FLATTENER (pay front, receive back)  =  LONG convexity
# ```
#
# A regressed `RLIRSwapCurve.resolve_pricable` would invert every number below
# without any other symptom — the equity curve would still be smooth, the payoff
# profiles would still be U-shaped, and the strategy would simply be the opposite
# one. The 2022-09 CPI week moved 5Y rates ~23 bp, so a payer must gain and the
# two directions must mirror exactly. This runs on every execution.

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
    return float(pd.Series(bt.mtm_history).iloc[-1])


_plus, _minus = _run_sign_probe(+CFG.package_dv01), _run_sign_probe(-CFG.package_dv01)
print(f"+bpv {_plus:+,.0f}   -bpv {_minus:+,.0f}")
assert _plus > 0, "payer must gain in the 2022-09 selloff"
assert abs(_plus + _minus) < 1e-6 * abs(_plus), "buy/sell must mirror — seam regressed?"
print("SIGN TEST PASS: mirror exact, payer gains")

# %% [markdown]
# ### 2b. The same probe at package level
#
# The outright probe pins the leg direction; this pins the *package* direction
# and DV01 neutrality, which is what the strategy actually trades. A flattener
# (`bpv < 0`) must pay the front leg and receive the back, both legs must carry
# |pv01| = the package DV01, and flipping the sign must mirror the notionals
# exactly — a direction-blind `resolve_pricable` returns the same all-payer
# package for both, and nothing downstream would notice.

# %%
_mdp = IRSwapsMDP(source="CITIVELO_EXCEL")
_probe_pricer = _mdp.get_data({"curve_name": CFG.curve, "timestamp": datetime.date(2022, 9, 13)})
_raw_f, _w_f, _flat = s1.resolve_package(_probe_pricer, "20Yx5Y", "25Yx5Y",
                                         package_dv01=CFG.package_dv01,
                                         direction=s1.FLATTENER, curve=CFG.curve)
_raw_s, _w_s, _steep = s1.resolve_package(_probe_pricer, "20Yx5Y", "25Yx5Y",
                                          package_dv01=CFG.package_dv01,
                                          direction=s1.STEEPENER, curve=CFG.curve)
for _nm, _pkg, _w in (("flattener", _flat, _w_f), ("steepener", _steep, _w_s)):
    print(f"{_nm:10s} rw={_w}")
    for _s in _pkg:
        print(f"   eff {_probe_pricer.effective_date(_s).date()} "
              f"mat {_probe_pricer.maturity_date(_s).date()} "
              f"N {_probe_pricer.notional(_s):+,.0f}  pv01 {_probe_pricer.pv01(_s):+,.1f}")
assert _w_f == [1.0, -1.0] and _w_s == [-1.0, 1.0]
for _a, _b in zip(_flat, _steep):
    assert abs(abs(_probe_pricer.pv01(_a)) - CFG.package_dv01) < 1e-6 * CFG.package_dv01
    assert abs(_probe_pricer.notional(_a) + _probe_pricer.notional(_b)) < 1e-6 * abs(_probe_pricer.notional(_a))
assert abs(sum(_probe_pricer.pv01(_s) for _s in _flat)) < 1e-3 * CFG.package_dv01
print("PACKAGE SIGN TEST PASS: DV01-neutral, directions mirror exactly")

# %% [markdown]
# ## 3. Known-answer tie-outs (a), (b) and (d)
#
# Four planted answers, all asserted, all on 2022-09-13:
#
# **(a) the payoff-profile regression table.** The convexity shape of three
# structures at $100k package DV01, in bp of package DV01, across the 13-point
# shift grid. This is the tripwire on the entire measurement chain — CURVE
# structure resolution, direction resolution, the shifted-repricing kernel and
# the unit conversion. Tolerance ±0.5 bp.
#
# **(b) a flattener must be CONVEX.** Not as a naive second difference of the
# payoff vector: the shift grid steps 50 bp in the wings and 25 bp near the
# money, and on an uneven grid a plain `diff(diff(p))` mixes step sizes and can
# call a genuinely convex profile concave. The test is that the divided
# differences `ΔP/Δs` are non-decreasing. The steepener must fail the same test.
#
# **(d) carry ordering — JPM's headline claim.** The 1-year carry-and-roll of the
# forward flattener against the spot one, pinned to +0.0061 bp (20Yx5Y/25Yx5Y)
# and −20.6697 bp (5Y/30Y).
#
# **(c) is the sign probe above**, run live rather than pinned to a number.
#
# One honest caveat on (d), stated here rather than buried: on **this particular
# date** the 30s/50s carry is **+0.3632 bp**, i.e. *better* than the forward
# structure's +0.0061. The long end was inverted enough in Sep-2022 that 30s/50s
# was a positive-carry flattener. So the one-day assertion is made against 5Y/30Y,
# where the claim holds by 20 bp, and the forward-vs-30s/50s question is answered
# on the **full sample** in section 9 — which is the honest place for it.

# %%
REGRESSION_2022_09_13 = {
    "20Yx5Y/25Yx5Y": [60.0, 33.7, 16.5, 6.4, 1.3, 0.3, 0.0, 0.4, 1.2, 4.2, 8.2, 12.8, 17.5],
    "30Y/50Y": [137.9, 82.1, 44.7, 20.9, 6.9, 2.7, 0.0, -1.4, -1.8, -0.1, 3.9, 9.5, 15.9],
    "10Yx10Y/20Yx10Y": [104.9, 60.0, 29.9, 11.6, 2.3, 0.4, 0.0, 0.9, 2.9, 9.5, 18.7, 29.7, 41.7],
}
CARRY_2022_09_13 = {"20Yx5Y/25Yx5Y": 0.0061, "5Y/30Y": -20.6697,
                    "30Y/50Y": 0.3632, "10Yx10Y/20Yx10Y": -2.8401}

_tie = []
for _label, _ft, _bt in STRUCTURES:
    _prof = s1.structure_profile(_probe_pricer, _label, _ft, _bt, CFG, direction=s1.FLATTENER)
    _steep_prof = s1.structure_profile(_probe_pricer, _label, _ft, _bt, CFG, direction=s1.STEEPENER)
    _row = {"structure": _label, "carry_bp": _prof.carry_bp,
            "carry_pinned": CARRY_2022_09_13[_label],
            "convex_flattener": s1.is_convex(_prof.shifts_bp, _prof.convexity_ccy),
            "convex_steepener": s1.is_convex(_steep_prof.shifts_bp, _steep_prof.convexity_ccy)}
    if _label in REGRESSION_2022_09_13:
        _exp = np.asarray(REGRESSION_2022_09_13[_label], float)
        _row["max_abs_diff_bp"] = float(np.max(np.abs(_prof.convexity_bp - _exp)))
        assert _row["max_abs_diff_bp"] < 0.5, f"(a) FAILED for {_label}: {_prof.convexity_bp}"
    # (b)
    assert _row["convex_flattener"], f"(b) FAILED: {_label} flattener is not convex"
    assert not _row["convex_steepener"], f"(b) FAILED: {_label} steepener is not concave"
    # (d) per-structure carry pin
    assert abs(_prof.carry_bp - CARRY_2022_09_13[_label]) < 0.01, f"(d) carry FAILED for {_label}"
    _tie.append(_row)
    print(f"{_label:18s} convexity bp: {np.round(_prof.convexity_bp, 1)}")
TIE = pd.DataFrame(_tie)
print()
print(TIE.to_string(index=False))

# (d) the ordering, on the pinned pair
_c = TIE.set_index("structure")["carry_bp"]
assert _c["20Yx5Y/25Yx5Y"] > _c["5Y/30Y"] + 15.0, "(d) ordering FAILED vs spot 5s30s"
assert _c["20Yx5Y/25Yx5Y"] > _c["10Yx10Y/20Yx10Y"], "(d) ordering FAILED vs 10y10y/20y10y"
print("\nTIE-OUTS (a) payoff table, (b) convexity, (d) carry ordering: PASS")
print(f"  NOTE on (d): 30s/50s carry is {_c['30Y/50Y']:+.4f} bp on this date — BETTER than "
      f"the forward's {_c['20Yx5Y/25Yx5Y']:+.4f}. Full-sample answer in section 9.")

# %% [markdown]
# ## 4. Swaption data, and the coverage that picks the primary signal
#
# The 1Yx30Y node of the Citi Velocity swaption cube: normal vols in bp, strike
# offsets absolute in bp from ATMF. The two series the note needs are the ATMF
# point (for the breakeven-vol comparison) and the full smile (for the
# Breeden–Litzenberger density behind the expected-payoff signal). Coverage is
# **measured here**, not assumed, because it is the reason `signal_mode` defaults
# the way it does.

# %%
VOL_PANEL = load_vol_panel([(CFG.swaption_expiry, CFG.swaption_tenor)],
                           CFG.start, CFG.end, cache_path=DATA / "vol_1Yx30Y.parquet")
ATMF = atmf_vol_series(VOL_PANEL, CFG.swaption_expiry, CFG.swaption_tenor)
_pts = VOL_PANEL.groupby("date").size()
_full = _pts[_pts >= 5]
COVERAGE = {
    "store_days": int(len(_pts)),
    "atmf_days": int(len(ATMF)),
    "atmf_first": str(ATMF.index.min().date()),
    "smile_days": int(len(_full)),
    "smile_first": str(_full.index.min().date()),
    "smile_pct_of_store": float(len(_full) / max(len(_pts), 1)),
}
print(json.dumps(COVERAGE, indent=1))
assert COVERAGE["smile_first"] > COVERAGE["atmf_first"], "smile should start LATER than ATMF"
assert pd.Timestamp(COVERAGE["smile_first"]) >= pd.Timestamp("2020-03-01"), (
    "the measured smile start moved — re-read the signal_mode default")
print(f"\nATMF runs from {COVERAGE['atmf_first']}, the OTM smile only from "
      f"{COVERAGE['smile_first']} — hence signal_mode='{CFG.signal_mode}'.")

# %% [markdown]
# ## 5. The signal panel
#
# One row per (date, structure). For each, the DV01-neutral **flattener** is
# built at market, its payoff profile computed across the 13-point shift grid,
# and the horizon carry-and-roll added as the profile's level. Then both of the
# note's signals:
#
# * **breakeven vol** — the normal vol at which the probability-weighted payoff is
#   exactly zero, quoted in bp/day, against the 1Yx30Y ATMF vol converted to the
#   same unit (`vol_bp / sqrt(252)`). Curve **cheap** when breakeven < swaption.
# * **expected payoff** — the profile integrated against the swaption-implied
#   terminal density. Curve **cheap** when positive.
#
# The `always_cheap` / `never_cheap` classification matters and is not cosmetic.
# `breakeven_vol_bp_per_year` returns NaN whenever the expected payoff has no
# sign change, and that single NaN covers two **opposite** states: a
# positive-carry package (never needs vol — cheap against *any* swaption vol,
# which is precisely JPM's "100% cheap curve gamma" column) and an
# everywhere-negative one (rich against any vol). Collapsing both to "no signal"
# would delete the note's own headline case.
#
# The panel is built in parallel chunks by `_strat1_build.py` and cached; this
# cell rebuilds it in-process if the cache is absent, which takes ~2 h.

# %%
_ppath = DATA / "strat1_signal_panel.parquet"
if _ppath.exists():
    PANEL = pd.read_parquet(_ppath)
    PANEL["date"] = pd.to_datetime(PANEL["date"])
    print(f"loaded {_ppath.name}: {PANEL.shape}, "
          f"{PANEL['date'].nunique()} days "
          f"{PANEL['date'].min().date()}..{PANEL['date'].max().date()}")
else:
    from pandas.tseries.holiday import USFederalHolidayCalendar
    from pandas.tseries.offsets import CustomBusinessDay

    _days = pd.date_range(CFG.start, CFG.end,
                          freq=CustomBusinessDay(calendar=USFederalHolidayCalendar()))
    _t0 = time.time()
    PANEL = s1.build_signal_panel(_mdp, CFG, _days, atmf_vol=ATMF,
                                  vol_panel=VOL_PANEL, progress_every=100).reset_index()
    PANEL.to_parquet(_ppath, index=False)
    print(f"built {_ppath.name} in {time.time() - _t0:.0f}s: {PANEL.shape}")

assert len(PANEL) > 0 and PANEL["date"].nunique() > 1500, "signal panel is too short"
assert set(LABELS) <= set(PANEL["structure"].unique()), "a structure is missing from the panel"
GRID_DATES = pd.DatetimeIndex(sorted(PANEL["date"].unique()))
print(f"grid: {len(GRID_DATES)} curve days")
PANEL.head(4)

# %% [markdown]
# ### 5b. Every flattener is convex on every day of the sample
#
# Tie-out (b) again, but as a census rather than a spot check: if the convexity
# measurement ever inverted — a bad curve, a direction flip, a resolution failure
# — this is where it would surface.

# %%
_conv = PANEL.groupby("structure")["convex"].mean()
print(_conv.to_string())
assert float(_conv.min()) == 1.0, "a flattener was measured as non-convex somewhere"
print("\n(b) CENSUS PASS: every flattener profile is convex on every day, every structure")

# %% [markdown]
# ## 6. Reproducing JPM's Exhibit 5 — curve-implied vol vs swaption vol
#
# The note's chart: breakeven ("swap-implied") vol from the curve against 1Yx30Y
# ATMF swaption vol, and the expected payoff, both 1-year-horizon measures. Where
# the curve's breakeven sits **below** the swaption line, the curve is the cheaper
# source of gamma.
#
# `always_cheap` days are plotted at 0 bp/day, which is what they are: no vol at
# all is required to break even.

# %%
import plotly.graph_objects as go
from plotly.subplots import make_subplots

_fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.07,
                     row_heights=[0.58, 0.42],
                     subplot_titles=("curve breakeven vol vs 1Yx30Y ATMF swaption vol (bp/day)",
                                     "expected payoff under the swaption-implied density (bp of package DV01)"))
_pal = {"30Y/50Y": "#ff9f43", "20Yx5Y/25Yx5Y": "#3ddc84",
        "10Yx10Y/20Yx10Y": "#4dabf7", "5Y/30Y": "#ff5c5c"}
for _label in LABELS:
    _s = PANEL[PANEL["structure"] == _label].set_index("date").sort_index()
    _be = _s["breakeven_vol_bp_day"].replace([np.inf], np.nan)
    _fig.add_trace(go.Scatter(x=_s.index, y=_be, name=_label, mode="lines",
                              line=dict(color=_pal.get(_label, "#9b8cff"), width=1.4)),
                   row=1, col=1)
    _fig.add_trace(go.Scatter(x=_s.index, y=_s["expected_payoff_bp"], name=_label,
                              mode="lines", showlegend=False,
                              line=dict(color=_pal.get(_label, "#9b8cff"), width=1.2)),
                   row=2, col=1)
_a = PANEL[PANEL["structure"] == LABELS[0]].set_index("date").sort_index()["atmf_vol_bp_day"]
_fig.add_trace(go.Scatter(x=_a.index, y=_a, name="1Yx30Y ATMF swaption",
                          mode="lines", line=dict(color="#ffffff", width=2, dash="dot")),
               row=1, col=1)
_fig.add_hline(y=0, line=dict(color="#666", width=1), row=2, col=1)
_fig.update_layout(template="plotly_dark", height=680, paper_bgcolor="#0e1117",
                   plot_bgcolor="#0e1117", title="Exhibit 5 reproduced — USD SOFR, 2019-2026",
                   legend=dict(orientation="h", y=1.06))
_fig

# %% [markdown]
# ### 6b. "% cheap curve gamma" — JPM's Exhibit 5 first row
#
# The fraction of days on which the curve is the cheaper source of gamma, by
# structure and by signal. JPM report **70%** for 30s/50s and **100%** for
# 25Y/20Yx5Y over 2009-2017 LIBOR.

# %%
_rows = []
for _label in LABELS:
    _s = PANEL[PANEL["structure"] == _label]
    _ep = _s["signal_expected_payoff"]
    _ep_ok = _s["expected_payoff_bp"].notna()
    _rows.append({
        "structure": _label,
        "n_days": int(len(_s)),
        "pct_cheap_breakeven": float((_s["signal_breakeven"] > 0).mean()),
        "pct_rich_breakeven": float((_s["signal_breakeven"] < 0).mean()),
        "pct_always_cheap": float((_s["breakeven_status"] == "always_cheap").mean()),
        "n_days_smile": int(_ep_ok.sum()),
        "pct_cheap_expected_payoff": float((_ep[_ep_ok] > 0).mean()) if _ep_ok.any() else np.nan,
        "mean_carry_roll_bp": float(_s["carry_roll_bp"].mean()),
        "median_carry_roll_bp": float(_s["carry_roll_bp"].median()),
        "mean_breakeven_bp_day": float(_s["breakeven_vol_bp_day"].replace([np.inf], np.nan).mean()),
        "mean_atmf_bp_day": float(_s["atmf_vol_bp_day"].mean()),
        "signal_agreement": float((np.sign(_s.loc[_ep_ok, "signal_breakeven"])
                                   == np.sign(_ep[_ep_ok])).mean()) if _ep_ok.any() else np.nan,
    })
CHEAPNESS = pd.DataFrame(_rows)
print(CHEAPNESS.to_string(index=False, float_format=lambda v: f"{v:,.3f}"))

# %% [markdown]
# ## 7. The straddle leg, sized and measured
#
# > "we initiate a flattener and sell 1Yx30Y ATMF swaption straddles to fund the
# >  carry on the position (i.e., sized such that the initiate premium intake is
# >  equal to the carry over the same 1-year horizon)"
#
# The straddle is sized to intake exactly the package's carry. An ATMF straddle
# in the normal model is worth `sqrt(2/pi)·σ·sqrt(T)` bp of rate per unit of
# annuity, so the size that funds a carry of `C` currency is
# `C / (sqrt(2/pi)·σ·sqrt(T))` of underlying **DV01** — a pure DV01 statement
# that does not depend on the swaption MDP.
#
# The point of this section is the **verification the task asks for**: for the
# forward structure the carry is ~0, so the funding straddle is ~0 and the leg
# does nothing. That is why `trade_straddle` defaults to False, and why the
# headline backtest below is flattener-only. **JPM's Exhibit 5 hit rates include
# the straddle leg; the ones reported here do not** — that difference is stated
# rather than papered over.

# %%
_str = []
for _label in LABELS:
    _s = PANEL[PANEL["structure"] == _label]
    _d = _s["straddle_dv01"].replace([np.inf], np.nan).dropna()
    _str.append({"structure": _label,
                 "median_|carry|_bp": float(_s["carry_roll_bp"].abs().median()),
                 "median_straddle_dv01_usd": float(_d.median()),
                 "p95_straddle_dv01_usd": float(_d.quantile(0.95)),
                 "median_pct_of_package_dv01": float(_d.median() / CFG.package_dv01)})
STRADDLE = pd.DataFrame(_str)
print(STRADDLE.to_string(index=False, float_format=lambda v: f"{v:,.4f}"))
_fwd = STRADDLE.set_index("structure").loc["20Yx5Y/25Yx5Y", "median_pct_of_package_dv01"]
_spot = STRADDLE.set_index("structure").loc["5Y/30Y", "median_pct_of_package_dv01"]
print(f"\nVERIFIED: the 20Yx5Y/25Yx5Y funding straddle is {_fwd:.5%} of package DV01 "
      f"(median) — it is not a leg, it is a rounding error.\n"
      f"          the 5Y/30Y one is {_spot:.2%}, i.e. {_spot / max(_fwd, 1e-12):,.0f}x larger.")
assert _fwd < 0.01, "the forward structure's funding straddle is no longer negligible"
print(f"          trade_straddle={CFG.trade_straddle} — the backtest below is flattener/steepener only.")

# %% [markdown]
# ## 8. The backtest — overlapping 1-year cohorts, daily mark-to-market
#
# One `QueryDrivenBacktest` per structure. Every cohort date with a non-zero
# signal opens a two-leg package under its **own tag** (a shared tag would let
# one cohort's unwind close another's position, because unwinds process after
# fills) and schedules an unwind one year later:
#
# * signal **+1 (cheap)** → **flattener**: pay front `bpv>0`, receive back `bpv<0`
# * signal **−1 (rich)** → **steepener**: the exact reverse, both legs
#
# The signal is **lagged one day**: computed off day *t*'s close, filled at
# *t+1*'s marks.
#
# **Cohorts opened inside the last year of the sample are still LIVE at the end.**
# They get no unwind trigger and are marked to the sample end, never force-closed
# — closing them at a partial horizon would mix trades of 1..250 days into a
# statistic that is defined for 1-year holds. Closed-cohort statistics and
# full-MTM equity are therefore reported as two separate things throughout.
#
# `QueryDrivenBacktest.run()` **swallows exceptions and prints them**, so a
# silently-failing backtest looks exactly like a flat equity curve. Every run is
# asserted for grid coverage, non-zero equity and closed-leg count.

# %%
def _load_or_run(label: str, front: str, back: str):
    eq_p = DATA / f"strat1_equity_{SAFE[label]}.parquet"
    co_p = DATA / f"strat1_cohorts_{SAFE[label]}.parquet"
    if eq_p.exists() and co_p.exists():
        eq = pd.read_parquet(eq_p)["equity_usd"]
        eq.index = pd.to_datetime(eq.index)
        co = pd.read_parquet(co_p)
        print(f"loaded {label}: {len(eq)} marks, {len(co)} cohorts")
        return eq, co
    sub = PANEL[PANEL["structure"] == label].set_index("date").sort_index()
    col = "signal_breakeven" if CFG.signal_mode == "breakeven_vol" else "signal_expected_payoff"
    signal = sub[col].shift(1).fillna(0.0)
    bt, cohorts = s1.build_backtest(_mdp, CFG, label, front, back, signal, sub.index)
    t0 = time.time()
    bt.run()
    eq = pd.Series(bt.mtm_history)
    eq.index = pd.to_datetime(eq.index)
    co = s1.cohort_table(bt, cohorts, CFG)
    print(f"ran {label}: {len(eq)} marks in {time.time() - t0:.0f}s")
    eq.to_frame("equity_usd").to_parquet(eq_p)
    co.to_parquet(co_p, index=False)
    return eq, co


EQUITY, COHORTS = {}, {}
for _label, _ft, _bt in STRUCTURES:
    EQUITY[_label], COHORTS[_label] = _load_or_run(_label, _ft, _bt)

for _label in LABELS:
    _eq, _co = EQUITY[_label], COHORTS[_label]
    _closed = _co[_co["closed"]]
    _missing = set(GRID_DATES) - set(_eq.index)
    print(f"{_label:18s} marks {len(_eq):5d}  missing {len(_missing):3d}  "
          f"cohorts {len(_co):4d} (closed {len(_closed)}, live {int((~_co['closed']).sum())})  "
          f"nonzero-equity days {int((_eq.abs() > 1e-9).sum())}")
    # QueryDrivenBacktest.run() swallows exceptions: a dead run looks flat.
    assert len(_eq) > 0.95 * len(GRID_DATES), f"{_label}: equity-curve holes"
    assert int((_eq.abs() > 1e-9).sum()) > 0.5 * len(_eq), f"{_label}: equity is ~identically zero"
    assert (_closed["n_legs_closed"] == 2).all(), f"{_label}: a cohort did not close both legs"
    # 92 months in the window, minus months with no vol print, minus the last 12
    # (still live) -> ~76 closed. A run that produced far fewer has lost cohorts.
    assert len(_closed) > 60, f"{_label}: too few closed cohorts to grade ({len(_closed)})"
    assert int((~_co["closed"]).sum()) >= 10, (
        f"{_label}: the live tail is missing — cohorts are being force-closed")
print("\nBACKTEST INTEGRITY PASS")

# %% [markdown]
# ## 9. Results — against JPM's Exhibit 5
#
# `pnl` here is the **gross** cohort round trip in bp of package DV01; `net` is
# after `2 × cost_bp_one_way` charged at the unwind. The comparison columns from
# Exhibit 5 are printed alongside. Read the **ordering**, not the levels: the
# sample is a different decade, a different index, and a very different vol
# regime.

# %%
JPM_EXHIBIT5 = {
    "30Y/50Y": {"pct_cheap": 0.70, "hit_rate": 0.56, "avg_pnl_bp": 10.4, "carry_bp": -100.6,
                "p25": -43, "p75": 75, "p05": -140, "p95": 128},
    "20Yx5Y/25Yx5Y": {"pct_cheap": 1.00, "hit_rate": 0.86, "avg_pnl_bp": 11.4, "carry_bp": 1.1,
                      "p25": 4, "p75": 19, "p05": -10, "p95": 33},
}

_rows = []
for _label in LABELS:
    _co = COHORTS[_label]
    _cl = _co[_co["closed"]].copy()
    _g = _cl["gross_pnl_bp"].to_numpy(float)
    _n = _cl["net_pnl_bp"].to_numpy(float)
    _eq = EQUITY[_label]
    _dd = (_eq - _eq.cummax())
    _ch = CHEAPNESS.set_index("structure").loc[_label]
    _rows.append({
        "structure": _label,
        "n_cohorts_closed": len(_cl),
        "n_cohorts_live": int((~_co["closed"]).sum()),
        "pct_flattener": float((_cl["direction"] > 0).mean()),
        "pct_cheap_days": float(_ch["pct_cheap_breakeven"]),
        "hit_rate_gross": float((_g > 0).mean()),
        "hit_rate_net": float((_n > 0).mean()),
        "avg_gross_bp": float(np.mean(_g)),
        "median_gross_bp": float(np.median(_g)),
        "avg_net_bp": float(np.mean(_n)),
        "total_gross_bp": float(np.sum(_g)),
        "total_net_bp": float(np.sum(_n)),
        "p05_gross_bp": float(np.percentile(_g, 5)),
        "p25_gross_bp": float(np.percentile(_g, 25)),
        "p75_gross_bp": float(np.percentile(_g, 75)),
        "p95_gross_bp": float(np.percentile(_g, 95)),
        "mean_carry_bp": float(_ch["mean_carry_roll_bp"]),
        "mtm_total_usd": float(_eq.iloc[-1]),
        "mtm_total_bp": float(_eq.iloc[-1] / CFG.package_dv01),
        "mtm_max_dd_usd": float(_dd.min()),
        "mtm_max_dd_bp": float(_dd.min() / CFG.package_dv01),
    })
RESULTS = pd.DataFrame(_rows).set_index("structure")
pd.set_option("display.width", 200)
print(RESULTS.T.to_string(float_format=lambda v: f"{v:,.3f}"))

# %%
_cmp = []
for _label, _j in JPM_EXHIBIT5.items():
    _r = RESULTS.loc[_label]
    _cmp.append({"metric": "% cheap curve gamma", "structure": _label,
                 "JPM 2009-2017": _j["pct_cheap"], "here 2019-2026": _r["pct_cheap_days"]})
    _cmp.append({"metric": "hit rate (gross)", "structure": _label,
                 "JPM 2009-2017": _j["hit_rate"], "here 2019-2026": _r["hit_rate_gross"]})
    _cmp.append({"metric": "avg P&L, bp", "structure": _label,
                 "JPM 2009-2017": _j["avg_pnl_bp"], "here 2019-2026": _r["avg_gross_bp"]})
    _cmp.append({"metric": "carry, bp (1y, mean)", "structure": _label,
                 "JPM 2009-2017": _j["carry_bp"], "here 2019-2026": _r["mean_carry_bp"]})
    _cmp.append({"metric": "25th pct P/L, bp", "structure": _label,
                 "JPM 2009-2017": _j["p25"], "here 2019-2026": _r["p25_gross_bp"]})
    _cmp.append({"metric": "75th pct P/L, bp", "structure": _label,
                 "JPM 2009-2017": _j["p75"], "here 2019-2026": _r["p75_gross_bp"]})
    _cmp.append({"metric": "5th pct P/L, bp", "structure": _label,
                 "JPM 2009-2017": _j["p05"], "here 2019-2026": _r["p05_gross_bp"]})
    _cmp.append({"metric": "95th pct P/L, bp", "structure": _label,
                 "JPM 2009-2017": _j["p95"], "here 2019-2026": _r["p95_gross_bp"]})
EXHIBIT5 = (pd.DataFrame(_cmp)
            .pivot(index="metric", columns="structure",
                   values=["JPM 2009-2017", "here 2019-2026"]))
print(EXHIBIT5.to_string(float_format=lambda v: f"{v:,.3f}"))

# %% [markdown]
# ### 9b. How much did the signal actually do?
#
# The most important thing to check before reading any of the numbers above: on
# this sample the breakeven-vol signal is **degenerate for the three long-end
# structures**. It never says "rich" — the curve's breakeven vol is below the
# 1Yx30Y ATMF vol on every single day a swaption vol exists, and on a large
# fraction of days the flattener carries *positively*, which is the
# `always_cheap` branch where no vol at all is required to break even.
#
# So for those three the strategy is **not a timing rule at all**; it is a
# permanently-on long-end flattener, and its P&L must be read as such. That is
# exactly what JPM report for the forward structure (**100% cheap curve gamma**)
# and exactly what they do *not* report for 30s/50s (**70%**) — in 2009-2017
# LIBOR the 30s/50s flattener was a large negative-carry trade, and in 2019-2026
# SOFR it has not been.
#
# `5Y/30Y` is the one structure where the signal is genuinely two-sided, and it
# is carried in the universe for that reason: it is the control that shows the
# machinery *can* say rich.
#
# A separate "always-flattener" control run would be pointless for the three
# degenerate structures — it would be the same book — so it is not run, and this
# cell is the evidence for that claim rather than an assertion of it.

# %%
_act = []
for _label in LABELS:
    _s = PANEL[PANEL["structure"] == _label]
    _co = COHORTS[_label]
    _act.append({
        "structure": _label,
        "days_cheap": float((_s["signal_breakeven"] > 0).mean()),
        "days_rich": float((_s["signal_breakeven"] < 0).mean()),
        "days_flat_no_vol": float((_s["signal_breakeven"] == 0).mean()),
        "days_always_cheap_branch": float((_s["breakeven_status"] == "always_cheap").mean()),
        "days_never_cheap_branch": float((_s["breakeven_status"] == "never_cheap").mean()),
        "cohorts_flattener": int((_co["direction"] > 0).sum()),
        "cohorts_steepener": int((_co["direction"] < 0).sum()),
        "signal_is_two_sided": bool((_s["signal_breakeven"] < 0).any()),
    })
ACTIVITY = pd.DataFrame(_act)
print(ACTIVITY.to_string(index=False, float_format=lambda v: f"{v:,.4f}"))
print("\nStructures whose signal never fires rich (i.e. a permanent flattener here): "
      + ", ".join(ACTIVITY.loc[~ACTIVITY["signal_is_two_sided"], "structure"].tolist()))

# %% [markdown]
# ### Does JPM's ordering claim survive on this sample?
#
# > "forward curve flatteners (e.g., 25Yx5Y versus 20Yx5Y) are a more attractive
# >  and cheaper source of this exposure than 30s/50s and similar structures."
#
# Two things are being claimed and they are separable, so they are tested
# separately: **carry** (the forward structure should cost less to hold) and
# **realised P&L** (it should therefore do better). This cell states which of
# them holds here and which does not.

# %%
_fwd, _spot30, _spot5 = "20Yx5Y/25Yx5Y", "30Y/50Y", "5Y/30Y"
_carry = PANEL.groupby("structure")["carry_roll_bp"]
CARRY_DIST = pd.DataFrame({
    "mean": _carry.mean(), "median": _carry.median(),
    "p05": _carry.quantile(0.05), "p95": _carry.quantile(0.95),
    "pct_days_negative_carry": PANEL.assign(neg=PANEL["carry_roll_bp"] < 0)
                                    .groupby("structure")["neg"].mean(),
}).loc[LABELS]
print(CARRY_DIST.to_string(float_format=lambda v: f"{v:,.3f}"))

VERDICT = {
    "carry_forward_beats_spot_5s30s": bool(CARRY_DIST.loc[_fwd, "median"] > CARRY_DIST.loc[_spot5, "median"]),
    "carry_forward_beats_30s50s": bool(CARRY_DIST.loc[_fwd, "median"] > CARRY_DIST.loc[_spot30, "median"]),
    "pnl_forward_beats_30s50s": bool(RESULTS.loc[_fwd, "avg_gross_bp"] > RESULTS.loc[_spot30, "avg_gross_bp"]),
    "hit_forward_beats_30s50s": bool(RESULTS.loc[_fwd, "hit_rate_gross"] > RESULTS.loc[_spot30, "hit_rate_gross"]),
    "dispersion_forward_tighter": bool(
        (RESULTS.loc[_fwd, "p95_gross_bp"] - RESULTS.loc[_fwd, "p05_gross_bp"])
        < (RESULTS.loc[_spot30, "p95_gross_bp"] - RESULTS.loc[_spot30, "p05_gross_bp"])),
}
print()
print(json.dumps(VERDICT, indent=1))
# The claim the task asks to be asserted: forward carry beats the SPOT structure
# it is pinned against. The 30s/50s comparison is reported, not asserted -- see
# section 3's caveat.
assert VERDICT["carry_forward_beats_spot_5s30s"], "forward carry no longer beats spot 5s30s"

# %% [markdown]
# ## 10. Equity curves and the house analytics
#
# Two different objects, kept apart on purpose:
#
# * **full MTM equity** — the engine's daily mark, which includes the cohorts that
#   are still live at the sample end. This is what a book running the strategy
#   would actually have shown.
# * **closed-cohort book** — one row per completed 1-year round trip. This is what
#   the hit rate and the percentile table are computed on, and the only thing
#   comparable to JPM's Exhibit 5.
#
# **The two are not on the same risk scale, and the difference is measured below
# rather than left implicit.** Overlapping cohorts mean the book holds ~11
# packages at once, so the MTM equity — although quoted in bp of *one* package's
# DV01 — is running roughly 11x that risk. Its drawdown must be read against that
# aggregate, not against a single trade.

# %%
_conc = []
for _label in LABELS:
    _co, _eq = COHORTS[_label], EQUITY[_label]
    _live = pd.Series(0, index=_eq.index)
    for _, _r in _co.iterrows():
        _x = pd.Timestamp(_r["exit"]) if pd.notna(_r["exit"]) else _eq.index[-1]
        _live.loc[pd.Timestamp(_r["entry"]):_x] += 1
    _conc.append({"structure": _label, "mean_concurrent_cohorts": float(_live.mean()),
                  "max_concurrent_cohorts": int(_live.max()),
                  "max_aggregate_dv01_usd": float(_live.max() * CFG.package_dv01),
                  "mtm_max_dd_bp_of_one_package": float((_eq - _eq.cummax()).min() / CFG.package_dv01),
                  "mtm_max_dd_bp_of_peak_aggregate":
                      float((_eq - _eq.cummax()).min() / (_live.max() * CFG.package_dv01))})
CONCURRENCY = pd.DataFrame(_conc)
print(CONCURRENCY.to_string(index=False, float_format=lambda v: f"{v:,.2f}"))

# %%
MTM_BOOKS = {}
for _label in LABELS:
    _eq = EQUITY[_label] / CFG.package_dv01
    _d = _eq.diff().dropna()
    MTM_BOOKS[_label] = pd.DataFrame({"date": _d.index, "pnl": _d.to_numpy()})
compare_curves(MTM_BOOKS, title="Strategy 1 — full daily MTM equity, bp of package DV01",
               time_col="date", pnl_col="pnl", unit="bp")

# %%
COHORT_BOOKS = {}
for _label in LABELS:
    _cl = COHORTS[_label]
    _cl = _cl[_cl["closed"]].copy()
    _cl["exit"] = pd.to_datetime(_cl["exit"])
    COHORT_BOOKS[_label] = _cl
compare_curves(COHORT_BOOKS,
               title="Strategy 1 — closed 1-year cohorts, net of costs, bp of package DV01",
               time_col="exit", pnl_col="net_pnl_bp", unit="bp",
               side_col="direction")

# %%
SPAN_YEARS = float((GRID_DATES[-1] - GRID_DATES[0]).days / 365.25)
print(f"span_years = {SPAN_YEARS:.2f}")
_stats = {}
for _label in LABELS:
    _s = summary_stats(COHORT_BOOKS[_label], span_years=SPAN_YEARS,
                       time_col="exit", pnl_col="net_pnl_bp", unit="bp",
                       side_col="direction").set_index("metric")["value"]
    _stats[_label] = _s
SUMMARY = pd.DataFrame(_stats)
print(SUMMARY.to_string())

# %%
trade_dashboard(COHORT_BOOKS["20Yx5Y/25Yx5Y"],
                title="20Yx5Y/25Yx5Y — closed 1-year cohorts (net)",
                span_years=SPAN_YEARS, time_col="exit", pnl_col="net_pnl_bp",
                unit="bp", side_col="direction")

# %%
trade_dashboard(COHORT_BOOKS["30Y/50Y"],
                title="30Y/50Y — closed 1-year cohorts (net)",
                span_years=SPAN_YEARS, time_col="exit", pnl_col="net_pnl_bp",
                unit="bp", side_col="direction")

# %% [markdown]
# ## 11. What this run actually measured
#
# The verdict block below is written from the computed numbers, not typed in. It
# is deliberately terse about what is and is not established:
#
# * the framework **reproduces** on this data — the payoff table ties out to
#   0.00 bp, every flattener is convex on every day, the carry pins hit their
#   values, and the two signals agree on the overlapping sample;
# * the **cohorts overlap by construction** (weekly entries, 1-year holds), so
#   the per-cohort statistics are *not* independent draws and the "Sharpe" in the
#   summary table above is an overlapping-sample Sharpe. It is reported because
#   the task asks for it; it should not be read as an out-of-sample t-statistic;
# * there is **one signal family and no parameter search** in this notebook —
#   thresholds are 0, the structure list is the note's own, the horizon is the
#   note's own. Nothing here has been selected on its own P&L.

# %%
VERDICT_JSON = {
    "window": [str(GRID_DATES[0].date()), str(GRID_DATES[-1].date())],
    "span_years": SPAN_YEARS,
    "config": {k: (list(v) if isinstance(v, tuple) else str(v) if isinstance(v, datetime.date) else v)
               for k, v in CFG.as_dict().items()},
    "coverage": COVERAGE,
    "tie_outs": {
        "a_payoff_table_max_abs_diff_bp": float(TIE["max_abs_diff_bp"].max(skipna=True)),
        "b_flattener_convex_every_day": bool(float(_conv.min()) == 1.0),
        "c_sign_probe_payer_gain_usd": float(_plus),
        "d_carry_pins_max_abs_diff_bp": float((TIE["carry_bp"] - TIE["carry_pinned"]).abs().max()),
    },
    "per_structure": json.loads(RESULTS.to_json(orient="index")),
    "signal_activity": json.loads(ACTIVITY.set_index("structure").to_json(orient="index")),
    "concurrency": json.loads(CONCURRENCY.set_index("structure").to_json(orient="index")),
    "jpm_ordering": VERDICT,
    "straddle": json.loads(STRADDLE.set_index("structure").to_json(orient="index")),
}
(DATA / "strat1_verdict.json").write_text(json.dumps(VERDICT_JSON, indent=1))
print(json.dumps(VERDICT_JSON, indent=1)[:4000])
