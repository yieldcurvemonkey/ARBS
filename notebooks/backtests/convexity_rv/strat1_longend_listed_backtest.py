# %% [markdown]
# # Strategy 1, long end — the listed-benchmark variation, actually backtested
#
# **What was missing.** The signal side of this question is finished and it is
# good. `strat1_real_contracts` built the real dated UST futures-option
# benchmark — `US@H365`, the contract whose expiry sits nearest one year out,
# rolled — and `strat1_threeway` ranked the curve's breakeven vol against it and
# against the 1Yx30Y swaption. Neither ran a backtest: `grep -c
# QueryDrivenBacktest` over `strat1_real_contracts.py` and both of its notebooks
# returns **0**, and no P&L claim appears in either. This notebook closes that
# gap — daily mark-to-market, equity curves, and the honest arithmetic about
# whether any of it means anything.
#
# **The books.** Four, on identical cohort dates, at strategy 1's own committed
# configuration ($100k package DV01, monthly cohorts, 1-year hold, 0.5 bp
# one-way, 2019-01-02..2026-08-14), so they are directly comparable to the
# committed base run:
#
# | book | enters when |
# |---|---|
# | `always` | always. **The control** — an always-on long-end flattener, no vol benchmark consulted at all. |
# | `swaption_only` | curve breakeven < 1Yx30Y ATMF. Strategy 1's committed signal. |
# | `listed_only` | curve breakeven < the **real listed contract** (`US@H365`). |
# | `both` | cheap (or rich) against both; mixed stands aside. |
#
# The constant-maturity control `US_30` is run through `listed_only` too, so the
# real-contract-versus-interpolated-surface difference shows up in P&L and not
# only in the signal counts.
#
# ## Read this before any number below
#
# Three things are true of this sample and all three limit what can be claimed.
# They are stated here rather than discovered in section 9.
#
# 1. **Three of the four structures are saturated.** The curve is cheap gamma
#    against *every* benchmark on 100% of usable days for `30Y/50Y`,
#    `20Yx5Y/25Yx5Y` and `10Yx10Y/20Yx10Y`. Their `swaption_only`, `listed_only`
#    and `both` books are therefore the `always` book with holes punched in it
#    wherever a benchmark is missing — **not four results, one result and three
#    copies**. `5Y/30Y` is the only structure on which any gate can differ.
#    Section 4 measures this instead of asserting it.
# 2. **~7.5 independent observations per structure.** One-year holds over 7.6
#    years. Pooling the four does not give 30: their measured pairwise
#    unit-cohort P&L correlation is 0.698, so `k_eff = 4/(1+3·0.698) = 1.29` and
#    the pooled count is ~9.7. Every Sharpe is quoted against
#    `expected_max_sharpe_under_null` at that count and at four trials.
# 3. **The prior signal-only run did not clear that bar.** Its stored verdict
#    records a best-gate Sharpe of 0.2423 against an E[max|null] of 0.3327 at
#    n_eff 9.70 — read out of the file in section 10 rather than retyped here,
#    so the comparison cannot drift. Nothing in this notebook is set up to
#    reverse that; the point is to measure it with an equity curve attached.

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
from RVUtils.ConvexityRV import strat1_longend_listed as ll
from RVUtils.ConvexityRV import strat1_threeway as tw

warnings.filterwarnings("ignore", category=RuntimeWarning)
pd.set_option("display.width", 220)

DATA = _REPO / "notebooks" / "data" / "convexity_rv"
DATA.mkdir(parents=True, exist_ok=True)
print("repo     ", _REPO)
print("artifacts", DATA)

# %% [markdown]
# ## 1. CONFIG — every knob, documented at the point of use
#
# Two objects, deliberately not merged:
#
# * `S1` is **strategy 1's own `Strat1Config`**, restated unchanged. Every
#   backtest knob lives there — package DV01, cohort cadence, horizon, cost,
#   window, and `force_close_at_end=False` so cohorts still open at the sample
#   end are **marked, never force-closed**. Duplicating any of it into a
#   study-local config is how two configs drift and how "directly comparable to
#   the committed base run" quietly stops being true.
# * `CFG` is `LongEndListedConfig` — the knobs that belong to *this* study
#   alone: which books to run, which benchmark is real and which is the control,
#   the cost multiples, and which (structure, gate) pair gets a genuine engine
#   run for certification.
#
# The one knob worth arguing about is `cohort_freq="monthly"`. JPM initiate
# **daily** and hold a year. Measured cost in this engine is ~0.03 s per cohort
# per mark for the 5Y-tail forwards and ~0.09 s for the spot structures, over
# ~1,900 marks — daily is ~40 h per structure, monthly ~35 min. It is a budget
# decision and nothing else. The statistical cost is small: 1-year cohorts
# opened a month apart share ~92% of their holding window, so the extra entries
# would not supply the independent observations their count implies. Either way
# the sample holds ~7.6 non-overlapping years.

# %%
S1 = ll.strat1_config()
CFG = ll.LongEndListedConfig()
TW = ll.threeway_config()

print("--- Strat1Config (strategy 1's own, unchanged) ---")
for k, v in S1.as_dict().items():
    print(f"  {k:28s} {v}")
print("\n--- LongEndListedConfig (this study) ---")
for k, v in CFG.as_dict().items():
    print(f"  {k:28s} {v}")

STRUCTURES = list(S1.structures)
LABELS = [l for (l, _, _) in STRUCTURES]
SAFE = {l: ll.safe_label(l) for l in LABELS}
DV01 = float(S1.package_dv01)

# The two configs must not disagree about the things they share, or every
# gate book is scored on a different trade from the one the engine ran.
assert S1.cost_bp_one_way == TW.cost_bp_one_way
assert S1.package_dv01 == TW.package_dv01
assert S1.horizon_years == TW.horizon_years
assert S1.force_close_at_end is False, "live cohorts must be MARKED, not force-closed"
assert tuple(l for (l, _, _) in S1.structures) == CFG.labels()
print("\nCONFIG CONSISTENCY PASS")

# %% [markdown]
# ## 2. The sign probe, live
#
# Everything here rests on one convention that is **established empirically, not
# read off the risk-weight code**:
#
# ```
# OUTRIGHT bpv > 0  =  PAYER
# CURVE    bpv < 0  =  FLATTENER (pay front, receive back)  =  LONG convexity
# ```
#
# A regressed `resolve_pricable` would invert every number below with no other
# symptom — the equity curves would still be smooth, the payoff profiles still
# U-shaped, and the strategy would simply be the opposite one. The 2022-09 CPI
# week moved 5Y rates ~23 bp, so a payer must gain and the two directions must
# mirror exactly. This runs on every execution.

# %%
def _run_sign_probe(bpv: float) -> float:
    dates = [datetime.date(2022, 9, 12), datetime.date(2022, 9, 13),
             datetime.date(2022, 9, 14), datetime.date(2022, 9, 15)]
    mdp = IRSwapsMDP(source="CITIVELO_EXCEL")
    q = IRSwapQuery(structure=IRSwapStructure.OUTRIGHT, value=IRSwapValue.NPV,
                    tenor="5Y", curve=S1.curve, structure_kwargs={"bpv": bpv},
                    tags=("probe",))
    strat = QueryStrategy(name=f"sign_{bpv:+.0f}", triggers=[
        DateTrigger(DateTriggerRequirements(dates=[dates[0]]),
                    actions=[AddQueryAction(query=q, meta={"tags": ["probe"]})]),
        DateTrigger(DateTriggerRequirements(dates=[dates[-1]]),
                    actions=[UnwindPositionsAction(match_tag="probe", fee=0.0)]),
    ])
    bt = QueryDrivenBacktest(time_grid=TimeGrid([pd.Timestamp(d) for d in dates]),
                             strategy=strat, mdp=mdp, show_progress=False)
    bt.run()
    assert bt.mtm_history, "sign probe produced no mtm_history -- run() failed"
    return float(pd.Series(bt.mtm_history).iloc[-1])


_plus, _minus = _run_sign_probe(+DV01), _run_sign_probe(-DV01)
print(f"+bpv {_plus:+,.0f}   -bpv {_minus:+,.0f}")
assert _plus > 0, "payer must gain in the 2022-09 selloff"
assert abs(_plus + _minus) < 1e-6 * abs(_plus), "buy/sell must mirror — seam regressed?"
print("SIGN TEST PASS: mirror exact, payer gains")

# %%
_mdp = IRSwapsMDP(source="CITIVELO_EXCEL")
_pricer = _mdp.get_data({"curve_name": S1.curve, "timestamp": datetime.date(2022, 9, 13)})
_raw_f, _w_f, _flat = s1.resolve_package(_pricer, "5Y", "30Y", package_dv01=DV01,
                                         direction=s1.FLATTENER, curve=S1.curve)
_raw_s, _w_s, _steep = s1.resolve_package(_pricer, "5Y", "30Y", package_dv01=DV01,
                                          direction=s1.STEEPENER, curve=S1.curve)
assert _w_f == [1.0, -1.0] and _w_s == [-1.0, 1.0]
for _a, _b in zip(_flat, _steep):
    assert abs(abs(_pricer.pv01(_a)) - DV01) < 1e-6 * DV01
    assert abs(_pricer.notional(_a) + _pricer.notional(_b)) < 1e-6 * abs(_pricer.notional(_a))
assert abs(sum(_pricer.pv01(_s) for _s in _flat)) < 1e-3 * DV01
print("PACKAGE SIGN TEST PASS: DV01-neutral, directions mirror exactly")

# %% [markdown]
# ## 3. Tie-outs — the measurement chain, pinned
#
# Three planted answers on 2022-09-13, all asserted:
#
# **(a) the payoff-profile regression table** — the convexity shape across the
# 13-point shift grid, in bp of package DV01. This is the tripwire on the whole
# chain: CURVE resolution, direction resolution, the shifted-repricing kernel,
# the unit conversion. Tolerance ±0.5 bp.
#
# **(b) a flattener must be CONVEX** — and not as a naive second difference:
# the shift grid steps 50 bp in the wings and 25 bp near the money, and on an
# uneven grid `diff(diff(p))` mixes step sizes and can call a genuinely convex
# profile concave. The test is that the divided differences `ΔP/Δs` are
# non-decreasing, and the steepener must fail it.
#
# **(d) carry ordering** — the 1-year carry-and-roll of the forward flattener
# against the spot one, pinned to +0.0061 bp (`20Yx5Y/25Yx5Y`) and −20.6697 bp
# (`5Y/30Y`).

# %%
REGRESSION_2022_09_13 = {
    "20Yx5Y/25Yx5Y": [60.0, 33.7, 16.5, 6.4, 1.3, 0.3, 0.0, 0.4, 1.2, 4.2, 8.2, 12.8, 17.5],
    "30Y/50Y": [137.9, 82.1, 44.7, 20.9, 6.9, 2.7, 0.0, -1.4, -1.8, -0.1, 3.9, 9.5, 15.9],
    "10Yx10Y/20Yx10Y": [104.9, 60.0, 29.9, 11.6, 2.3, 0.4, 0.0, 0.9, 2.9, 9.5, 18.7, 29.7, 41.7],
}
CARRY_2022_09_13 = {"20Yx5Y/25Yx5Y": 0.0061, "5Y/30Y": -20.6697,
                    "30Y/50Y": 0.3632, "10Yx10Y/20Yx10Y": -2.8401}

_tie = []
for _label, _ft, _bk in STRUCTURES:
    _p = s1.structure_profile(_pricer, _label, _ft, _bk, S1, direction=s1.FLATTENER)
    _q = s1.structure_profile(_pricer, _label, _ft, _bk, S1, direction=s1.STEEPENER)
    _row = {"structure": _label, "carry_bp": _p.carry_bp,
            "carry_pinned": CARRY_2022_09_13[_label],
            "convex_flattener": s1.is_convex(_p.shifts_bp, _p.convexity_ccy),
            "convex_steepener": s1.is_convex(_q.shifts_bp, _q.convexity_ccy)}
    if _label in REGRESSION_2022_09_13:
        _exp = np.asarray(REGRESSION_2022_09_13[_label], float)
        _row["max_abs_diff_bp"] = float(np.max(np.abs(_p.convexity_bp - _exp)))
        assert _row["max_abs_diff_bp"] < 0.5, f"(a) FAILED for {_label}"
    assert _row["convex_flattener"], f"(b) FAILED: {_label} flattener not convex"
    assert not _row["convex_steepener"], f"(b) FAILED: {_label} steepener not concave"
    assert abs(_p.carry_bp - CARRY_2022_09_13[_label]) < 0.01, f"(d) carry FAILED for {_label}"
    _tie.append(_row)
TIE = pd.DataFrame(_tie)
print(TIE.to_string(index=False, float_format=lambda v: f"{v:,.4f}"))
_c = TIE.set_index("structure")["carry_bp"]
assert _c["20Yx5Y/25Yx5Y"] > _c["5Y/30Y"] + 15.0, "(d) ordering FAILED vs spot 5s30s"
print("\nTIE-OUTS (a) payoff table, (b) convexity, (d) carry ordering: PASS")

# %% [markdown]
# ## 4. The two benchmarks, and the saturation that governs everything
#
# `US@H365` is the **real dated contract**: for every date, the listed option
# whose expiry sits nearest one year out, rolled as contracts expire (47
# contracts, 47 roll events, median 133 days to expiry — it cannot actually
# reach a year, which is a fact about the listed ladder, not a modelling
# choice). `US_30` is the **constant-maturity control**: the same root's surface
# interpolated to a fixed 30 days. Same curve column, same swaption column, same
# `(date, structure)` key — the *only* difference between the two frames is
# `listed_atm_bp_day`, which is exactly the experiment.
#
# Both go through `strat1_threeway.threeway_frame` unmodified, so the gates and
# the usable mask are the signal study's and not a second implementation.
#
# **This is the cell that governs how the rest of the notebook must be read.**

# %%
THREE = {"real": ll.load_threeway(DATA, benchmark="real"),
         "cm": ll.load_threeway(DATA, benchmark="cm")}
for _k, _t in THREE.items():
    assert not _t.index.duplicated().any(), f"{_k}: duplicated (date, structure) key"
    print(f"{_k:5s} {_t.shape}  {_t.index.get_level_values('date').min().date()}"
          f"..{_t.index.get_level_values('date').max().date()}")

SAT = {k: ll.saturation_table(t) for k, t in THREE.items()}
print("\n--- REAL contract benchmark (US@H365) ---")
print(SAT["real"].to_string(index=False, float_format=lambda v: f"{v:,.4f}"))
print("\n--- CONSTANT-MATURITY control (US_30) ---")
print(SAT["cm"].to_string(index=False, float_format=lambda v: f"{v:,.4f}"))

_s = SAT["real"].set_index("structure")
SATURATED = [l for l in LABELS if bool(_s.loc[l, "saturated"])]
BINDING = [l for l in LABELS if l not in SATURATED]
assert BINDING == ["5Y/30Y"], f"the binding set moved: {BINDING}"
print(f"\nSATURATED (gate == always on every usable day): {SATURATED}")
print(f"BINDING   (the gate can differ):                {BINDING}")
print(f"\nOn the saturated three, a gated book differs from `always` ONLY where a\n"
      f"benchmark is MISSING — {_s.loc[SATURATED[0], 'frac_days_unusable']:.2%} of days, "
      f"{int(_s.loc[SATURATED[0], 'n_days'] - _s.loc[SATURATED[0], 'n_days_usable'])} of "
      f"{int(_s.loc[SATURATED[0], 'n_days'])}. That is a coverage hole, not a signal.")

# %% [markdown]
# ### 4b. Real contract against constant maturity — the signal difference
#
# Before any P&L: on how many days does swapping the interpolated surface for a
# real dated contract change what the gate says? If the answer is ~zero the two
# books will be identical and that is a **result**, not a failure — it is the
# measurement the study exists to make.

# %%
_rows = []
for _label in LABELS:
    _a = THREE["real"].xs(_label, level="structure")
    _b = THREE["cm"].xs(_label, level="structure")
    _i = _a.index.intersection(_b.index)
    _u = (_a.loc[_i, "usable"].to_numpy(bool) & _b.loc[_i, "usable"].to_numpy(bool))
    _row = {"structure": _label, "n_common_usable": int(_u.sum())}
    for _m in ("swaption_only", "listed_only", "both"):
        _d = (_a.loc[_i, f"gate_{_m}"].to_numpy(float)[_u]
              != _b.loc[_i, f"gate_{_m}"].to_numpy(float)[_u])
        _row[f"frac_differs_{_m}"] = float(_d.mean()) if _u.any() else np.nan
        _row[f"n_differs_{_m}"] = int(_d.sum())
    _row["median_listed_real_bp_day"] = float(_a.loc[_i, "listed_bp_day"][_u].median())
    _row["median_listed_cm_bp_day"] = float(_b.loc[_i, "listed_bp_day"][_u].median())
    _rows.append(_row)
CM_VS_REAL = pd.DataFrame(_rows)
print(CM_VS_REAL.to_string(index=False, float_format=lambda v: f"{v:,.4f}"))
# swaption_only never touches the listed leg: a non-zero value there means the
# two frames are misaligned and every other column is suspect.
assert float(CM_VS_REAL["frac_differs_swaption_only"].abs().max()) == 0.0, (
    "the two benchmark frames are not aligned")
print("\nALIGNMENT PASS: swaption_only is identical across the two frames, as it must be.")

# %% [markdown]
# ## 5. The engine runs — one UNIT pass per structure
#
# `strat1_curve_gamma.build_backtest` is driven unmodified. Each pass opens
# every monthly cohort as a **pure flattener** (`signal = +1` everywhere, lagged
# one day) and holds it a year, so the run is simultaneously:
#
# * the **`always` book** — daily mark-to-market straight from the engine, with
#   no composition anywhere in it; and
# * the source of **per-cohort daily marks**, which is what lets every other
#   gate's equity curve be composed from this one pass.
#
# **Why not one engine pass per (structure, gate)?** Twenty passes at 25–90
# minutes each, and it is also the *worse* experiment. Swap NPV is linear in
# `bpv`, `build_backtest` opens each cohort at `+dv01·s` / `−dv01·s`, and the
# unwind fee does not depend on `s` — so composing from one pass scores every
# gate on **bit-identical cohort P&L** and the only thing that differs between
# two curves is the gate. `strat1_threeway` proves and pins that identity at the
# cohort level; section 6 certifies the daily-level version of it against a real
# engine run rather than assuming it.
#
# `QueryDrivenBacktest.run()` **swallows exceptions and prints them**, so a
# silently-failing pass looks exactly like a flat equity curve. Every run is
# asserted for grid coverage, non-zero equity, both legs closing, and a live
# tail that was never force-closed.

# %%
_missing = [l for l in LABELS
            if not (DATA / f"strat1_le_unit_equity_{SAFE[l]}.parquet").exists()]
if _missing:
    raise SystemExit(
        "unit engine runs are missing for "
        f"{_missing}. Build them first (they take ~25-90 min each):\n"
        "  python notebooks/backtests/convexity_rv/_strat1_longend_listed_build.py unit")

UNIT = {}
for _label in LABELS:
    _sf = SAFE[_label]
    _eq = pd.read_parquet(DATA / f"strat1_le_unit_equity_{_sf}.parquet")["equity_usd"]
    _eq.index = pd.to_datetime(_eq.index)
    _co = pd.read_parquet(DATA / f"strat1_le_unit_cohorts_{_sf}.parquet")
    _mk = pd.read_parquet(DATA / f"strat1_le_unit_marks_{_sf}.parquet")
    _raw, _step, _err = ll.cohort_contributions(_eq, _co, _mk, cfg=S1)
    UNIT[_label] = {"equity": _eq, "cohorts": _co, "marks": _mk,
                    "raw": _raw, "step": _step, "decomp_err_usd": _err}

# The engine's own mark count is checked against the SIGNAL-PANEL grid it was
# driven off, never against another run's — a self-referential grid would make
# the coverage assertion below trivially true and hide a run that lost days.
_pg = pd.read_parquet(DATA / "strat1_signal_panel.parquet")
PANEL_GRID = pd.DatetimeIndex(sorted(pd.to_datetime(_pg["date"]).unique()))
GRID = UNIT[LABELS[0]]["equity"].index
SPAN_YEARS = float((GRID[-1] - GRID[0]).days / 365.25)
print(f"panel grid {len(PANEL_GRID)} days   engine grid {len(GRID)} marks  "
      f"{GRID[0].date()}..{GRID[-1].date()}  span {SPAN_YEARS:.2f}y")
print(f"marks the engine did not produce (no curve resolved): "
      f"{[str(d.date()) for d in PANEL_GRID.difference(GRID)]}\n")

for _label in LABELS:
    _u = UNIT[_label]
    _co, _eq = _u["cohorts"], _u["equity"]
    _cl = _co[_co["closed"].to_numpy(bool)]
    print(f"{_label:18s} marks {len(_eq):5d}  cohorts {len(_co):3d} "
          f"(closed {len(_cl):3d}, live {int((~_co['closed']).sum()):3d})  "
          f"nonzero {int((_eq.abs() > 1e-9).sum()):5d}  "
          f"decomp err ${_u['decomp_err_usd']:.2e}")
    assert (_co["direction"] == 1.0).all(), f"{_label}: unit run is not a pure flattener"
    assert len(_eq) > 0.95 * len(PANEL_GRID), f"{_label}: equity-curve holes"
    assert int((_eq.abs() > 1e-9).sum()) > 0.5 * len(_eq), f"{_label}: equity ~identically zero"
    assert (_cl["n_legs_closed"] == 2).all(), f"{_label}: a cohort did not close both legs"
    assert len(_cl) > 60, f"{_label}: too few closed cohorts to grade ({len(_cl)})"
    assert int((~_co["closed"]).sum()) >= 10, f"{_label}: the live tail was force-closed"
    assert _u["decomp_err_usd"] <= 1e-6 * float(_eq.abs().max()), \
        f"{_label}: daily decomposition failed"
print("\nENGINE INTEGRITY PASS — and the daily decomposition is an identity to "
      "floating-point noise on every mark of every run.")

# %% [markdown]
# ### 5b. Regression against an independently stored unit run
#
# `strat1_threeway` stored its own `5Y/30Y` unit pass earlier and separately.
# Two engine runs, built by different scripts on different days, must agree
# cohort for cohort. Free evidence that nothing in this study's plumbing moved
# the trade.

# %%
_prior_p = DATA / "strat1_threeway_longend_unit_cohorts_5Y-30Y.parquet"
if _prior_p.exists():
    _a = UNIT["5Y/30Y"]["cohorts"].set_index(
        pd.to_datetime(UNIT["5Y/30Y"]["cohorts"]["entry"])).sort_index()
    _b = pd.read_parquet(_prior_p)
    _b = _b.set_index(pd.to_datetime(_b["entry"])).sort_index()
    assert _a.index.equals(_b.index), "cohort entry dates diverged from the stored run"
    _m = _a["closed"].to_numpy(bool) & _b["closed"].to_numpy(bool)
    _d = np.abs(_a.loc[_m, "gross_pnl_bp"].to_numpy(float)
                - _b.loc[_m, "gross_pnl_bp"].to_numpy(float))
    print(f"5Y/30Y unit vs stored unit: {len(_a)} cohorts, {int(_m.sum())} commonly closed, "
          f"max |diff| {_d.max():.3e} bp")
    assert _d.max() < 1e-6, "this run disagrees with the stored one"
    print("REGRESSION PASS: two independent engine runs agree exactly")
else:
    print(f"stored prior unit run absent ({_prior_p.name}) — regression check skipped")

# %% [markdown]
# ## 6. Composition, certified against the engine
#
# Every gate's daily equity is composed from its structure's one unit pass::
#
# ```
# raw_c(t)   = value_c(t) while open;  gross_c once closed   (fee stripped out)
# gated_c(t) = g_c · raw_c(t)  −  |g_c| · fee_new · 1{closed by t}
# ```
#
# `|g_c|` and not `g_c` is the load-bearing character: a steepener pays the same
# round trip as a flattener, and writing `g` there would *pay* the trader for
# every short — flattering exactly the structure whose gates are two-sided.
# Standing aside (`g = 0`) costs nothing, because charging for it would flatter
# whichever gate trades least.
#
# Three checks, in increasing strength:
#
# 1. **the composed `always` book must reproduce the engine's own
#    `mtm_history`** — same run, so any error is pure composition arithmetic;
# 2. **composed cohort P&L must equal `strat1_threeway.apply_gate`'s** —
#    separately tested code reached by a different expression;
# 3. **a genuine, independent `QueryDrivenBacktest` of one gated book**
#    (`5Y/30Y` under `listed_only`) against its composition, reporting the
#    terminal gap and the **daily-change correlation**. A composition can hit
#    the terminal number by luck while taking a completely different path; the
#    daily correlation is what refuses to let that pass.

# %%
ALL_MODES = list(CFG.gate_modes) + ["listed_only_cm"]

GATES = {}
for _label in LABELS:
    _g = {}
    # `always` must live on the COHORT grid (1,908 days), not the contracts grid
    # (1,901): it consults no benchmark, so it has to trade on the cohort dates a
    # gated book cannot reach. That difference is the control's whole point.
    _g[ll.ALWAYS] = ll.gate_series(THREE["real"], _label, ll.ALWAYS,
                                   index=UNIT[_label]["equity"].index)
    for _m in CFG.gate_modes:
        if _m != ll.ALWAYS:
            _g[_m] = ll.gate_series(THREE["real"], _label, _m)
    # the constant-maturity control, reported alongside listed_only
    _g["listed_only_cm"] = ll.gate_series(THREE["cm"], _label, "listed_only")
    GATES[_label] = _g

EQUITY, BOOKS = ll.compose_all_books(UNIT, GATES, cfg=S1)
BOOKS["gate_mode"] = BOOKS["gate_mode"].astype(str)
print(f"composed {len(EQUITY)} books  "
      f"({len(LABELS)} structures x {len(GATES[LABELS[0]])} gates)")

# --- check 1: the composed `always` book IS the engine's own curve
_c1 = []
for _label in LABELS:
    _e = float((EQUITY[(_label, ll.ALWAYS)] - UNIT[_label]["equity"]).abs().max())
    _c1.append({"structure": _label, "max_abs_gap_usd": _e,
                "rel": _e / float(UNIT[_label]["equity"].abs().max())})
    assert _e < 1e-6 * float(UNIT[_label]["equity"].abs().max()), \
        f"{_label}: composed `always` != engine mtm_history"
print("\ncheck 1 — composed `always` vs engine mtm_history:")
print(pd.DataFrame(_c1).to_string(index=False, float_format=lambda v: f"{v:.3e}"))

# --- check 2: composed cohort P&L vs strat1_threeway.apply_gate
_c2 = []
for _label in LABELS:
    for _m in ("swaption_only", "listed_only", "both"):
        _mine = BOOKS[(BOOKS["structure"] == _label) & (BOOKS["gate_mode"] == _m)]
        _theirs = tw.apply_gate(UNIT[_label]["cohorts"], GATES[_label][_m], cfg=TW)
        _a = _mine.loc[_mine["gate_closed"].to_numpy(bool), "net_bp"].to_numpy(float)
        _b = _theirs.loc[_theirs["gate_closed"].to_numpy(bool), "gate_net_bp"].to_numpy(float)
        assert len(_a) == len(_b) and np.allclose(_a, _b, atol=1e-9), \
            f"{_label}/{_m}: composed cohort P&L != apply_gate"
        _c2.append({"structure": _label, "gate": _m, "n_closed": len(_a),
                    "max_abs_diff_bp": float(np.max(np.abs(_a - _b))) if len(_a) else 0.0})
print("\ncheck 2 — composed cohort P&L vs strat1_threeway.apply_gate:")
print(pd.DataFrame(_c2).to_string(index=False, float_format=lambda v: f"{v:.2e}"))

# %% [markdown]
# ### 6c. Check 3 — a genuine engine run of a gated book
#
# `5Y/30Y` under `listed_only`: the only structure whose gates bind at all
# (certifying a saturated one would certify the identity `g ≡ 1` and prove
# nothing), and the book this study exists to produce. The engine run consumes
# the **exact same pre-lagged direction series** the composition uses —
# `build_backtest` does not lag and `apply_gate` lags internally, so lagging
# twice is the error that would make the backtest look better and leave no trace.
#
# **The order of shift and reindex is load-bearing, and this was measured rather
# than assumed.** The gate lives on the 1,901-day contracts grid and the engine
# on the 1,908-day signal grid. Seven signal days carry no contracts row
# (2019-04-19, 2020-04-10, 2021-04-02, 2022-04-15, 2024-03-29, 2025-04-18,
# 2026-04-03). Reindexing *first* and shifting after reads "no benchmark printed
# yesterday" as "stand aside" — and on **2024-04-01** that flips exactly one
# 5Y/30Y cohort from a steepener to no trade. The first version of the build
# script did that, and the certification would have failed for a reason that is
# not a composition error at all. Both sides now shift on the gate's own grid
# first, which is what `apply_gate` does, what the test suite pins, and the right
# trading semantic: you act on the last observation the benchmark actually made.
# The cell below asserts the two direction vectors are identical before it
# compares any P&L.

# %%
_cl, _cm = CFG.certify_structure, CFG.certify_gate
_ep = DATA / f"strat1_le_engine_equity_{SAFE[_cl]}_{_cm}.parquet"
if not _ep.exists():
    raise SystemExit(
        f"the certification engine run is missing. Build it (~35 min):\n"
        f'  python notebooks/backtests/convexity_rv/_strat1_longend_listed_build.py '
        f'gate "{_cl}" {_cm}')
_engine_eq = pd.read_parquet(_ep)["equity_usd"]
_engine_eq.index = pd.to_datetime(_engine_eq.index)
_engine_co = pd.read_parquet(DATA / f"strat1_le_engine_cohorts_{SAFE[_cl]}_{_cm}.parquet")

# Same trades first, same P&L second. The engine opened a cohort exactly where
# its pre-lagged signal was non-zero; the composition must have gated the same
# entries the same way, or the P&L comparison below is comparing two strategies.
_eng_entries = set(pd.to_datetime(_engine_co["entry"]))
_cmp_book = BOOKS[(BOOKS["structure"] == _cl) & (BOOKS["gate_mode"] == _cm)]
_cmp_entries = set(pd.to_datetime(_cmp_book.loc[_cmp_book["traded"].to_numpy(bool), "entry"]))
print(f"engine traded {len(_eng_entries)} cohorts, composition traded {len(_cmp_entries)}; "
      f"symmetric difference {len(_eng_entries ^ _cmp_entries)}")
assert _eng_entries == _cmp_entries, (
    "engine and composition disagree about WHICH cohorts trade — check the "
    f"shift/reindex order: {sorted(str(d.date()) for d in _eng_entries ^ _cmp_entries)}")

CERT = ll.certify_composition(_engine_eq, EQUITY[(_cl, _cm)], label=_cl, mode=_cm, cfg=S1)
CERT_DF = pd.DataFrame([CERT])
print(CERT_DF.T.to_string(header=False, float_format=lambda v: f"{v:,.6f}"))

# Cohort level too. Matched on ENTRY DATE, never on tag: `build_backtest`
# numbers tags over the cohorts it actually opens, so the gated run's `c0000`
# is a different trade from the unit run's `c0000` and a tag join would compare
# unrelated cohorts while looking perfectly well-formed.
_ec = _engine_co[_engine_co["closed"].to_numpy(bool)].copy()
_ec = _ec.set_index(pd.to_datetime(_ec["entry"])).sort_index()
_cc = BOOKS[(BOOKS["structure"] == _cl) & (BOOKS["gate_mode"] == _cm)
            & BOOKS["gate_closed"].to_numpy(bool)].copy()
_cc = _cc.set_index(pd.to_datetime(_cc["entry"])).sort_index()
assert not _ec.index.duplicated().any() and not _cc.index.duplicated().any()
_common = _ec.index.intersection(_cc.index)
assert len(_common) == len(_ec) == len(_cc), (
    f"cohort sets differ: engine {len(_ec)}, composed {len(_cc)}, common {len(_common)}")
_gap = (_ec.loc[_common, "net_pnl_bp"].to_numpy(float)
        - _cc.loc[_common, "net_bp"].to_numpy(float))
print(f"\ncohort-level: {len(_common)} commonly-closed cohorts, "
      f"max |diff| {np.abs(_gap).max():.3e} bp")

print(f"\nCERTIFICATION: terminal gap {CERT['terminal_gap_pct']:+.4f}% of the engine's "
      f"terminal, daily-change correlation {CERT['corr_daily_changes']:.6f}")
assert abs(CERT["terminal_gap_pct"]) < 1.0, (
    f"composition and engine disagree by {CERT['terminal_gap_pct']:.2f}% — "
    "PREFER THE ENGINE and re-run every book through it")
assert CERT["corr_daily_changes"] > 0.999, (
    f"composed path does not track the engine's (r={CERT['corr_daily_changes']:.4f})")
assert float(np.abs(_gap).max()) < 1e-6, "cohort-level certification failed"
print("CERTIFICATION PASS — the composition is the engine, to floating-point noise.")

# %% [markdown]
# ## 7. What each gate actually traded
#
# Before P&L: how many cohorts each book entered, and in which direction. On the
# saturated three every gated book is `always` minus the cohorts whose entry
# date had no benchmark; on `5Y/30Y` the gates are genuinely two-sided.

# %%
_act = []
for _label in LABELS:
    for _m in ALL_MODES:
        _b = BOOKS[(BOOKS["structure"] == _label) & (BOOKS["gate_mode"] == _m)]
        _t = _b[_b["traded"].to_numpy(bool)]
        _act.append({
            "structure": _label, "gate": _m,
            "n_cohorts": int(len(_b)), "n_traded": int(len(_t)),
            "n_flattener": int((_t["gate_direction"] > 0).sum()),
            "n_steepener": int((_t["gate_direction"] < 0).sum()),
            "n_stood_aside": int((~_b["traded"]).sum()),
            "n_closed_traded": int(_b["gate_closed"].sum()),
            "n_live_traded": int(((~_b["closed"]) & _b["traded"]).sum()),
        })
ACTIVITY = pd.DataFrame(_act)
print(ACTIVITY.to_string(index=False))

_same = []
for _label in LABELS:
    _a = BOOKS[(BOOKS["structure"] == _label) & (BOOKS["gate_mode"] == ll.ALWAYS)] \
        .set_index("tag")["gate_direction"]
    for _m in ("swaption_only", "listed_only", "both", "listed_only_cm"):
        _b = BOOKS[(BOOKS["structure"] == _label) & (BOOKS["gate_mode"] == _m)] \
            .set_index("tag")["gate_direction"]
        _same.append({"structure": _label, "gate": _m,
                      "n_cohorts_differing_from_always": int((_a != _b).sum()),
                      "identical_to_always": bool((_a == _b).all())})
VS_ALWAYS = pd.DataFrame(_same)
print()
print(VS_ALWAYS.to_string(index=False))

# %% [markdown]
# ### 7a. The real contract against the constant-maturity control, in the BOOK
#
# `strat1_real_contracts` measured the two benchmarks' signals and found them
# differing on 45 daily rows, all of them `5Y/30Y`. Section 4b re-measures it on
# the three-way usable intersection and gets **44 of 1,854 days (2.37%)**, again
# only on `5Y/30Y` — the small difference is the 47 unusable days the earlier
# count included. The question neither study could answer and this one can:
# **does any of that reach a trade?**
#
# Cohorts open monthly, so a daily disagreement only matters if it lands on the
# day before a cohort date. The cell below counts how many of the 91 monthly
# entries actually see a different direction.

# %%
_rc = []
for _label in LABELS:
    _a = BOOKS[(BOOKS["structure"] == _label) & (BOOKS["gate_mode"] == "listed_only")] \
        .set_index("tag")
    _b = BOOKS[(BOOKS["structure"] == _label) & (BOOKS["gate_mode"] == "listed_only_cm")] \
        .set_index("tag")
    _d = _a["gate_direction"] != _b["gate_direction"]
    _rc.append({
        "structure": _label,
        "n_cohorts": int(len(_a)),
        "n_entries_where_real_differs_from_cm": int(_d.sum()),
        "real_total_net_bp": float(_a.loc[_a["gate_closed"], "net_bp"].sum()),
        "cm_total_net_bp": float(_b.loc[_b["gate_closed"], "net_bp"].sum()),
        "books_identical": bool(not _d.any()),
    })
REAL_VS_CM_BOOK = pd.DataFrame(_rc)
REAL_VS_CM_BOOK["delta_net_bp"] = (REAL_VS_CM_BOOK["real_total_net_bp"]
                                   - REAL_VS_CM_BOOK["cm_total_net_bp"])
print(REAL_VS_CM_BOOK.to_string(index=False, float_format=lambda v: f"{v:,.3f}"))
if bool(REAL_VS_CM_BOOK["books_identical"].all()):
    print("\nRESULT: at monthly cohort cadence the real dated contract and the\n"
          "constant-maturity surface produce the IDENTICAL book on every structure.\n"
          "The 2.4% of days on which they disagree never land on a cohort entry.\n"
          "That is a real answer to the question the real-contract rebuild posed,\n"
          "and it is a negative one: the contract-level detail does not reach a trade\n"
          "at this cadence. It would need daily or weekly entries to have a chance.")
else:
    print(f"\nThe two benchmarks differ on "
          f"{int(REAL_VS_CM_BOOK['n_entries_where_real_differs_from_cm'].sum())} "
          f"cohort entries; the P&L difference is in delta_net_bp above.")

# %% [markdown]
# ### 7b. Why `swaption_only` here is NOT the committed base run's book
#
# The obvious question, answered on the page rather than left to be asked: the
# committed strategy-1 run traded the same signal on the same structures at the
# same configuration, so why do the terminals differ?
#
# Two reasons, both deliberate:
#
# 1. **`require_all_three=True`.** Every gated book here stands aside on days
#    where *any* of the three vols is missing — 2.5% of days, because the listed
#    benchmark has holes the swaption does not. Without it, `swaption_only`
#    would trade on dates `listed_only` cannot and the gate comparison would be
#    measuring **coverage** rather than information. That is the whole reason
#    the flag exists, and it necessarily moves `swaption_only` away from the
#    base run.
# 2. **The cohort set is the unit run's 91**, not the base run's 88. The base
#    run opened no cohort on three dates where the swaption ATMF was NaN on the
#    lagged day; here those cohorts exist and are simply gated to zero, which
#    keeps all five books on **identical cohort dates** — the thing that makes
#    them comparable to each other.
#
# So the base run is the right comparison for *this notebook's `always` control*
# in spirit and for nothing else. The gap is printed rather than described.

# %%
_base = []
for _label in LABELS:
    _p = DATA / f"strat1_equity_{SAFE[_label]}.parquet"
    if not _p.exists():
        continue
    _s = pd.read_parquet(_p)["equity_usd"]
    _s.index = pd.to_datetime(_s.index)
    _bc = pd.read_parquet(DATA / f"strat1_cohorts_{SAFE[_label]}.parquet")
    _mine = BOOKS[(BOOKS["structure"] == _label) & (BOOKS["gate_mode"] == "swaption_only")]
    _base.append({
        "structure": _label,
        "base_run_cohorts": int(len(_bc)),
        "here_cohorts": int(len(_mine)),
        "here_traded": int(_mine["traded"].sum()),
        "base_run_terminal_bp": float(_s.iloc[-1] / DV01),
        "swaption_only_terminal_bp": float(EQUITY[(_label, "swaption_only")].iloc[-1] / DV01),
        "always_terminal_bp": float(EQUITY[(_label, ll.ALWAYS)].iloc[-1] / DV01),
    })
if _base:
    BASE_CMP = pd.DataFrame(_base)
    BASE_CMP["gap_vs_base_bp"] = (BASE_CMP["swaption_only_terminal_bp"]
                                  - BASE_CMP["base_run_terminal_bp"])
    print(BASE_CMP.to_string(index=False, float_format=lambda v: f"{v:,.2f}"))
    print("\nThe gap is the coverage gate and the three extra cohort dates, not a\n"
          "disagreement about any trade both books took.")
else:
    BASE_CMP = pd.DataFrame()
    print("committed base-run equity curves not present — comparison skipped")

# %% [markdown]
# ## 8. Results — per structure and per gate
#
# Two objects, kept apart on purpose:
#
# * **closed 1-year round trips** — one row per completed hold. Hit rate,
#   Sharpe-per-trade and the t-statistic are computed on these, and they are the
#   only things comparable to strategy 1's own base run.
# * **daily MTM equity** — the engine's mark, including cohorts still live at
#   the sample end (marked, never force-closed). Its drawdown is what a book
#   running this would actually have shown. It is quoted in bp of **one**
#   package's DV01 while the book holds ~12 packages at once, so read the
#   drawdown against that aggregate, not against a single trade.
#
# `t_stat_overlap_adj` divides the nominal t by `sqrt(n_closed / n_eff)`:
# monthly cohorts held a year share ~92% of their window, so the nominal count
# is an upper bound on the evidence and never the evidence itself.

# %%
CARRY = (pd.read_parquet(DATA / "strat1_signal_panel.parquet")
         .groupby("structure")["carry_roll_bp"].mean())

_stats = []
for _label in LABELS:
    for _m in ALL_MODES:
        _b = BOOKS[(BOOKS["structure"] == _label) & (BOOKS["gate_mode"] == _m)]
        _st = ll.book_stats(EQUITY[(_label, _m)], _b, cfg=S1,
                            carry_bp=float(CARRY.get(_label, np.nan)),
                            business_days_per_year=CFG.business_days_per_year)
        _st.update({"structure": _label, "gate": _m})
        _st["breakeven_cost_bp_one_way"] = ll.breakeven_cost_bp(_b)
        _stats.append(_st)
STATS = pd.DataFrame(_stats)
_cols = ["structure", "gate", "n_traded", "n_closed", "n_live_marked", "n_eff_independent",
         "total_net_bp", "mean_net_bp", "hit_rate", "sharpe_per_trade", "mtm_sharpe_ann",
         "t_stat_nominal", "t_stat_overlap_adj", "mtm_final_bp", "mtm_max_dd_bp",
         "mean_carry_bp", "breakeven_cost_bp_one_way"]
print(STATS[_cols].to_string(index=False, float_format=lambda v: f"{v:,.3f}"))

# %% [markdown]
# ### 8b. Pooled across the four structures
#
# The pooled daily equity is the sum of the four structures' curves — a book
# running all four at $100k package DV01 each — and the cohort statistics pool
# the four books equal-weighted.
#
# **Two different `n_eff`s appear in this notebook and they are not the same
# number.** The `n_eff_independent` column here is the **time-overlap** haircut
# only: calendar span divided by the holding period, ~7.5, and it is what
# `t_stat_overlap_adj` divides by. Section 10 reports `n_eff_pooled` ≈ 9.7,
# which applies the time haircut *and* the measured cross-structure correlation
# haircut, and it is what the Sharpe scoreboard is evaluated at. Neither is
# wrong; they answer different questions.
#
# **And read `mtm_max_dd_bp` against the right denominator.** Every figure is
# quoted in bp of ONE $100k package's DV01, but the pooled book runs four
# structures at once and each holds ~12 overlapping cohorts, so the pooled curve
# carries roughly **48 packages** at steady state. A pooled drawdown of −900 bp
# of one package is ~−19 bp of the risk actually on. The concurrency cell below
# measures it rather than leaving the reader to guess the multiplier.

# %%
# The four engine runs do not all cover the identical set of marks (a day on
# which one structure's curve failed to resolve is missing from that run only),
# so the curves are aligned on the UNION and forward-filled before adding.
# Equity is a LEVEL: a missing mark means "no new mark", which is what ffill
# says; a plain `sum` would return NaN there and silently delete the day, and
# `fillna(0)` would assert the book was flat on it.
POOL_GRID = GRID
for _l in LABELS:
    POOL_GRID = POOL_GRID.union(EQUITY[(_l, ll.ALWAYS)].index)


def _pooled_equity(mode: str) -> pd.Series:
    out = pd.Series(0.0, index=POOL_GRID)
    for lb in LABELS:
        out = out + EQUITY[(lb, mode)].reindex(POOL_GRID).ffill().fillna(0.0)
    return out


POOLED_EQUITY = {m: _pooled_equity(m) for m in ALL_MODES}
print(f"pooled grid {len(POOL_GRID)} marks; per-structure marks "
      f"{[len(EQUITY[(l, ll.ALWAYS)]) for l in LABELS]}")

_pool = []
for _m in ALL_MODES:
    _b = BOOKS[BOOKS["gate_mode"] == _m]
    _st = ll.book_stats(POOLED_EQUITY[_m], _b, cfg=S1, carry_bp=float(CARRY.mean()),
                        business_days_per_year=CFG.business_days_per_year)
    _st.update({"gate": _m, "breakeven_cost_bp_one_way": ll.breakeven_cost_bp(_b)})
    _pool.append(_st)
POOLED = pd.DataFrame(_pool).set_index("gate")
print()
print(POOLED[[c for c in _cols if c not in ("structure", "gate")]]
      .to_string(float_format=lambda v: f"{v:,.3f}"))

# %%
# How much risk is actually on, so the drawdowns above have a denominator.
_conc = []
for _m in ALL_MODES:
    _live = pd.Series(0, index=POOL_GRID)
    for _label in LABELS:
        _b = BOOKS[(BOOKS["structure"] == _label) & (BOOKS["gate_mode"] == _m)]
        for _, _r in _b[_b["traded"].to_numpy(bool)].iterrows():
            _x = (pd.Timestamp(_r["exit"]) if pd.notna(_r["exit"]) else POOL_GRID[-1])
            _live.loc[pd.Timestamp(_r["entry"]):_x] += 1
    _dd = POOLED_EQUITY[_m] - POOLED_EQUITY[_m].cummax()
    _peak = max(int(_live.max()), 1)
    _conc.append({
        "gate": _m,
        "mean_concurrent_packages": float(_live.mean()),
        "max_concurrent_packages": int(_live.max()),
        "peak_aggregate_dv01_usd": float(_peak * DV01),
        "mtm_max_dd_bp_of_one_package": float(_dd.min() / DV01),
        "mtm_max_dd_bp_of_peak_aggregate": float(_dd.min() / (_peak * DV01)),
    })
CONCURRENCY = pd.DataFrame(_conc)
print()
print(CONCURRENCY.to_string(index=False, float_format=lambda v: f"{v:,.2f}"))

# %% [markdown]
# ### 8c. What did the signal add over simply being long the flattener?
#
# The only question that matters, asked directly: every gated book minus the
# always-on control, on the same structures over the same window. A positive
# `delta_total_net_bp` means the gate earned its existence; a negative one means
# the benchmark comparison cost money relative to doing nothing clever.
#
# Note what a *negative* delta means on the three saturated structures
# specifically: the gate never disagreed with the control about direction, so
# the entire difference is the cohorts it skipped because a benchmark was
# missing. That is the price of `require_all_three`, not a signal.

# %%
_delta = []
for _label in LABELS + ["POOLED"]:
    _ref = (POOLED.loc[ll.ALWAYS] if _label == "POOLED"
            else STATS[(STATS["structure"] == _label) & (STATS["gate"] == ll.ALWAYS)].iloc[0])
    for _m in ALL_MODES:
        if _m == ll.ALWAYS:
            continue
        _r = (POOLED.loc[_m] if _label == "POOLED"
              else STATS[(STATS["structure"] == _label) & (STATS["gate"] == _m)].iloc[0])
        _delta.append({
            "structure": _label, "gate": _m,
            "always_total_net_bp": float(_ref["total_net_bp"]),
            "gate_total_net_bp": float(_r["total_net_bp"]),
            "delta_total_net_bp": float(_r["total_net_bp"] - _ref["total_net_bp"]),
            "delta_sharpe_per_trade": float(_r["sharpe_per_trade"] - _ref["sharpe_per_trade"]),
            "delta_mtm_sharpe_ann": float(_r["mtm_sharpe_ann"] - _ref["mtm_sharpe_ann"]),
            "delta_hit_rate": float(_r["hit_rate"] - _ref["hit_rate"]),
            "delta_n_traded": int(_r["n_traded"] - _ref["n_traded"]),
        })
SIGNAL_VALUE = pd.DataFrame(_delta)
print(SIGNAL_VALUE.to_string(index=False, float_format=lambda v: f"{v:,.3f}"))

_pool_d = SIGNAL_VALUE[SIGNAL_VALUE["structure"] == "POOLED"]
_helped = _pool_d.loc[_pool_d["delta_total_net_bp"] > 0, "gate"].tolist()
print(f"\nPooled: gates that BEAT the always-on control on total net P&L: "
      f"{_helped if _helped else 'NONE'}")

# %% [markdown]
# ## 9. Cost sensitivity, and the break-even cost
#
# Only the fee term moves across these rows — the gate, the cohorts and the
# gross P&L are bit-identical — which is what makes this a sensitivity rather
# than four backtests. `cost_multiple` scales the headline **0.5 bp one way**,
# so `2.0` is 1.0 bp one way / 2.0 bp round trip.
#
# `breakeven_cost_bp_one_way` is exact rather than searched: total net is
# `sum(gross) − 2·c·n_closed`, linear in `c`. A **negative** value means the book
# loses money gross and no cost level rescues it — reported as such rather than
# clipped to zero.

# %%
_cs = []
for _label in LABELS:
    for _m in ALL_MODES:
        _t = ll.cost_sensitivity(UNIT[_label]["raw"], UNIT[_label]["step"],
                                 UNIT[_label]["cohorts"], GATES[_label][_m],
                                 cfg=S1, multipliers=CFG.cost_multipliers)
        _t.insert(0, "gate", _m)
        _t.insert(0, "structure", _label)
        _cs.append(_t)
COST = pd.concat(_cs, ignore_index=True)
print(COST.pivot_table(index=["structure", "gate"], columns="cost_multiple",
                       values="total_net_bp")
      .to_string(float_format=lambda v: f"{v:,.2f}"))
print("\n(total net P&L, bp of package DV01, by cost multiple of 0.5 bp one way)")

_be = STATS.pivot_table(index="structure", columns="gate",
                        values="breakeven_cost_bp_one_way")
print("\nbreak-even one-way cost, bp of package DV01:")
print(_be.to_string(float_format=lambda v: f"{v:,.3f}"))

# A sensitivity that does not fall with cost is not a sensitivity. Books with no
# closed traded cohort are skipped rather than asserted on -- their total is NaN
# by definition, and NaN is not a monotonicity failure.
_checked = 0
for (_l, _m), _g in COST.groupby(["structure", "gate"]):
    _v = _g.sort_values("cost_multiple")["total_net_bp"]
    if not _v.notna().all():
        print(f"  skipped {_l}/{_m}: nothing closed under this gate")
        continue
    assert _v.is_monotonic_decreasing, f"{_l}/{_m}: net P&L does not fall as costs rise"
    _checked += 1
print(f"\nCOST MONOTONICITY PASS ({_checked} books)")

# %% [markdown]
# ## 10. The sample size, measured — and what it does to every Sharpe above
#
# Two haircuts, applied in sequence, because the nominal cohort count overstates
# the evidence twice over:
#
# * **overlap in time** — monthly cohorts held a year share ~92% of their
#   window, so a structure's ~78 cohorts are `span/365.25/horizon`
#   non-overlapping observations, not 78;
# * **overlap across structures** — the four long-end flatteners are overlapping
#   segments of the same curve. At mean pairwise unit-cohort P&L correlation
#   `rbar`, `k_eff = k/(1+(k−1)·rbar)`.
#
# `rbar` is **measured** by `cohort_pnl_correlation`, never assumed.

# %%
NEFF = tw.effective_independent_n_pooled({l: UNIT[l]["cohorts"] for l in LABELS}, cfg=TW)
CORR, _cs_summ = tw.cohort_pnl_correlation({l: UNIT[l]["cohorts"] for l in LABELS}, cfg=TW)
print(CORR.to_string(float_format=lambda v: f"{v:,.3f}"))
print()
print(json.dumps({k: (v if not isinstance(v, dict) else
                      {kk: round(vv, 3) for kk, vv in v.items()})
                  for k, v in NEFF.items()}, indent=1, default=str))

N_EFF_POOLED = float(NEFF["n_eff_pooled"])
N_TRIALS = len(CFG.distinct_gate_modes)
BAR = tw.expected_max_sharpe_under_null(N_TRIALS, n_obs=int(round(N_EFF_POOLED)))
print(f"\nE[max Sharpe | null] over {N_TRIALS} distinct gates at n_eff = "
      f"{N_EFF_POOLED:.2f}: {BAR:.4f} per observation")
print("The CM control is NOT counted as a trial: it is `listed_only` against a\n"
      "differently-built version of the same benchmark, so counting it would\n"
      "inflate the trial count without adding a degree of freedom.")

# %%
SCORE = ll.sharpe_scoreboard(
    POOLED.reset_index()[["gate", "sharpe_per_trade", "n_closed", "total_net_bp",
                          "hit_rate", "mtm_sharpe_ann", "skew", "kurtosis"]],
    N_EFF_POOLED, n_trials=N_TRIALS)
print(SCORE.to_string(index=False, float_format=lambda v: f"{v:,.4f}"))
CLEARS = SCORE.loc[SCORE["clears_max_null"], "gate"].tolist()
print(f"\nGates clearing E[max|null] = {BAR:.4f}: "
      f"{CLEARS if CLEARS else 'NONE'}")

# The prior, signal-only study's own numbers -- READ from its stored verdict, not
# retyped, so the "did this change anything?" comparison cannot drift as either
# side is re-run.
_prior_v = DATA / "strat1_threeway_longend_verdict.json"
PRIOR = {}
if _prior_v.exists():
    _pv = json.loads(_prior_v.read_text())
    PRIOR = {
        "n_eff_pooled": _pv.get("sample_size", {}).get("n_eff_pooled"),
        "n_trials": _pv.get("n_trials_used_for_correction"),
        "e_max_sharpe_null": _pv.get("expected_max_sharpe_under_null_effective"),
        "best_gate_sharpe_per_trade": _pv.get("best_gate_sharpe_per_trade"),
        "best_gate_deflated_sharpe": _pv.get("best_gate_deflated_sharpe"),
    }
    print("\nprior signal-only run (strat1_threeway_longend_verdict.json):")
    print(json.dumps(PRIOR, indent=1, default=str))
    print(f"\nthis run: n_eff_pooled {N_EFF_POOLED:.4f}, bar {BAR:.4f}, "
          f"best gate Sharpe/trade {float(SCORE['sharpe_per_trade'].max()):.4f} "
          f"({str(SCORE.loc[SCORE['sharpe_per_trade'].idxmax(), 'gate'])})")
    print("The bar and the sample size agree with the prior run because they are\n"
          "the same cohorts; what is new is that the Sharpes now come off an\n"
          "engine-marked equity curve rather than a cohort table alone.")
else:
    print("\nprior signal-only verdict absent — cross-run comparison skipped")

# %% [markdown]
# ## 11. Equity curves and the house analytics
#
# `compare_curves` across the gate modes, on the pooled daily MTM and on the
# closed-cohort books; `trade_dashboard` on the best book; `summary_stats` with
# `span_years` passed explicitly, because a book of ~78 event-driven 1-year
# holds has no natural frequency and inventing one is how a Sharpe of 0.3 per
# trade becomes a Sharpe of 3.

# %%
MTM_BOOKS = {}
for _m in ALL_MODES:
    _d = (POOLED_EQUITY[_m] / DV01).diff().dropna()
    MTM_BOOKS[_m] = pd.DataFrame({"date": _d.index, "pnl": _d.to_numpy()})
compare_curves(MTM_BOOKS,
               title="Strategy 1 long end — pooled daily MTM by gate, bp of package DV01",
               time_col="date", pnl_col="pnl", unit="bp")

# %%
COHORT_BOOKS = {}
for _m in ALL_MODES:
    _b = BOOKS[(BOOKS["gate_mode"] == _m) & BOOKS["gate_closed"].to_numpy(bool)].copy()
    _b["exit"] = pd.to_datetime(_b["exit"])
    COHORT_BOOKS[_m] = _b.sort_values("exit")
compare_curves(COHORT_BOOKS,
               title="Strategy 1 long end — closed 1-year cohorts by gate, net of costs (bp)",
               time_col="exit", pnl_col="net_bp", unit="bp", side_col="gate_direction")

# %%
_binding = {}
for _m in ALL_MODES:
    _b = BOOKS[(BOOKS["structure"] == "5Y/30Y") & (BOOKS["gate_mode"] == _m)
               & BOOKS["gate_closed"].to_numpy(bool)].copy()
    _b["exit"] = pd.to_datetime(_b["exit"])
    _binding[_m] = _b.sort_values("exit")
compare_curves(_binding,
               title="5Y/30Y — the ONLY structure where the gates differ (closed cohorts, net, bp)",
               time_col="exit", pnl_col="net_bp", unit="bp", side_col="gate_direction")

# %%
print(f"span_years = {SPAN_YEARS:.2f}")
SUMMARY = pd.DataFrame({
    _m: summary_stats(COHORT_BOOKS[_m], span_years=SPAN_YEARS, time_col="exit",
                      pnl_col="net_bp", unit="bp", side_col="gate_direction")
        .set_index("metric")["value"]
    for _m in ALL_MODES})
print(SUMMARY.to_string())
print("""
READ THE 'annualised Sharpe' ROW WITH CARE -- it is the single most
over-quotable number this notebook produces and it is wrong for this book.
`summary_stats` annualises by scaling the per-trade Sharpe by
sqrt(trades / year), which is correct for independent trades. These trades are
NOT independent: they are one-year holds opened monthly, so ~20 "trades per
year" are about ONE non-overlapping observation, and the sqrt(20) it multiplies
by is very nearly all of the number. The honest annualised figure is
`mtm_sharpe_ann` in section 8 -- computed off daily marks of the actual book --
and the honest evidence test is the scoreboard in section 10, which nothing
clears.""")

# %%
BEST = str(POOLED["total_net_bp"].astype(float).idxmax())
print(f"best book by total net P&L: {BEST}")
trade_dashboard(COHORT_BOOKS[BEST],
                title=f"BEST BOOK — {BEST}, pooled closed 1-year cohorts (net)",
                span_years=SPAN_YEARS, time_col="exit", pnl_col="net_bp",
                unit="bp", side_col="gate_direction")

# %%
trade_dashboard(COHORT_BOOKS[ll.ALWAYS],
                title="CONTROL — always-on flattener, pooled closed 1-year cohorts (net)",
                span_years=SPAN_YEARS, time_col="exit", pnl_col="net_bp",
                unit="bp", side_col="gate_direction")

# %% [markdown]
# ## 12. Direction against convexity, measured
#
# Every book above mixes two returns. A DV01-neutral flattener is neutral to
# **parallel** shifts but not to the spread it is built on: pay the front leg at
# $100k/bp and receive the back at $100k/bp, and a 1 bp widening of
# `back − front` costs exactly 1 bp of package DV01. So to first order
#
# ```
# gross_bp  =  direction_bp  +  everything_else,      direction_bp ≡ −Δspread_bp
# ```
#
# and `Δspread` is **measured, not proxied**: both legs' par rates are re-priced
# off the curve store on every cohort entry and exit date
# (`_strat1_longend_listed_build.py rates`, ~170 dates, each leg verified struck
# at par by `npv == 0`).
#
# `everything_else` is carry, convexity and higher-order terms together, and it
# is deliberately **not** split further here. The obvious next step — subtract
# the entry carry-and-roll — would double count, because carry-and-**roll**
# already contains an expected spread change and `Δspread` contains the realised
# one. Mean carry is printed alongside as context, not as a subtracted term.
#
# The diagnostic is the regression of gross P&L on `−Δspread`. A slope near
# **1** with a high R² says the book is a directional curve trade wearing a
# convexity argument; a low R² says the curve move does not explain it. This
# cell reports which it is.

# %%
_rates_p = DATA / "strat1_le_cohort_rates.parquet"
if not _rates_p.exists():
    raise SystemExit(
        "par-rate cache missing. Build it (~5 min):\n"
        "  python notebooks/backtests/convexity_rv/_strat1_longend_listed_build.py rates")
RATES = pd.read_parquet(_rates_p)
RATES["date"] = pd.to_datetime(RATES["date"])
_sp = RATES.pivot_table(index="date", columns="structure", values="spread_bp").sort_index()

_panel = pd.read_parquet(DATA / "strat1_signal_panel.parquet")
_panel["date"] = pd.to_datetime(_panel["date"])
_carry = _panel.pivot_table(index="date", columns="structure",
                            values="carry_roll_bp").sort_index()

def _dirsplit(mode: str) -> pd.DataFrame:
    """Closed cohorts of one gate, with the realised curve move attached.

    ``direction_bp`` is signed by the GATE, not by the structure: a steepener
    profits when the spread widens, so the first-order term is
    ``gate_direction * (-Δspread)``. Getting that sign wrong would make the
    two-sided 5Y/30Y book look like it had no directional exposure at all.
    """
    out = []
    for lb in LABELS:
        b = BOOKS[(BOOKS["structure"] == lb) & (BOOKS["gate_mode"] == mode)
                  & BOOKS["gate_closed"].to_numpy(bool)].copy()
        if b.empty:
            continue
        e, x = pd.to_datetime(b["entry"]), pd.to_datetime(b["exit"])
        b["spread_entry_bp"] = _sp[lb].reindex(e).to_numpy(float)
        b["spread_exit_bp"] = _sp[lb].reindex(x).to_numpy(float)
        b["d_spread_bp"] = b["spread_exit_bp"] - b["spread_entry_bp"]
        b["carry_at_entry_bp"] = _carry[lb].reindex(e).to_numpy(float)
        b["direction_bp"] = b["gate_direction"].to_numpy(float) * (-b["d_spread_bp"])
        # everything the first-order curve move does NOT explain: carry,
        # convexity and higher-order terms together. Not split further.
        b["residual_bp"] = b["gross_bp"] - b["direction_bp"]
        out.append(b)
    return pd.concat(out, ignore_index=True).dropna(subset=["d_spread_bp"])


def _decomp(df: pd.DataFrame, mode: str) -> pd.DataFrame:
    rows = []
    for lb in LABELS + ["POOLED"]:
        g = df if lb == "POOLED" else df[df["structure"] == lb]
        y, x = g["gross_bp"].to_numpy(float), g["direction_bp"].to_numpy(float)
        ok = np.isfinite(y) & np.isfinite(x)
        y, x = y[ok], x[ok]
        slope = float(np.polyfit(x, y, 1)[0]) if len(y) > 2 else np.nan
        r = float(np.corrcoef(x, y)[0, 1]) if len(y) > 2 else np.nan
        rows.append({
            "gate": mode, "structure": lb, "n": int(len(y)),
            "mean_gross_bp": float(np.mean(y)) if len(y) else np.nan,
            "mean_carry_bp": float(g["carry_at_entry_bp"].mean()),
            "mean_direction_bp": float(np.mean(x)) if len(x) else np.nan,
            "mean_residual_bp": float(g["residual_bp"].mean()),
            "slope_on_direction": slope,
            "r2": float(r ** 2) if np.isfinite(r) else np.nan,
        })
    return pd.DataFrame(rows)


DIRSPLIT = _dirsplit(ll.ALWAYS)
_BEST = str(POOLED["total_net_bp"].astype(float).idxmax())
DECOMP = pd.concat([_decomp(DIRSPLIT, ll.ALWAYS),
                    _decomp(_dirsplit(_BEST), _BEST)] if _BEST != ll.ALWAYS
                   else [_decomp(DIRSPLIT, ll.ALWAYS)], ignore_index=True)
print("closed cohorts: gross = direction + residual")
print("  direction = gate_direction * -d(spread);  residual = carry + convexity + higher order")
print(f"  reported for the CONTROL ({ll.ALWAYS}) and for the best book ({_BEST})")
print(DECOMP.to_string(index=False, float_format=lambda v: f"{v:,.3f}"))

for _mm in DECOMP["gate"].unique():
    _p = DECOMP[(DECOMP["gate"] == _mm) & (DECOMP["structure"] == "POOLED")].iloc[0]
    print(f"\n{_mm}: pooled gross P&L regressed on the gated curve move has slope "
          f"{_p['slope_on_direction']:.3f}, R^2 {_p['r2']:.3f}; "
          f"mean gross {_p['mean_gross_bp']:+.2f} bp of which "
          f"{_p['mean_direction_bp']:+.2f} bp is the curve move and "
          f"{_p['mean_residual_bp']:+.2f} bp is everything else.")
print("A slope near 1 with a high R^2 says the book is a DIRECTIONAL curve trade;")
print("the residual column is the part any convexity story has to live in.")
print("mean_carry_bp is printed as CONTEXT -- it sits INSIDE the residual and is")
print("not subtracted from it, because carry-and-ROLL and the realised spread")
print("move both contain the roll, and subtracting would double count it.")

# %%
# qcut on the RANK, not on the raw values: ties would collapse a bin edge and
# raise on the fixed label list, which would kill the cell for a reason that has
# nothing to do with the measurement.
DIRSPLIT["spread_bucket"] = pd.qcut(DIRSPLIT["d_spread_bp"].rank(method="first"), 5,
                                    labels=["big flattening", "q2", "middle", "q4",
                                            "big steepening"])
_t = DIRSPLIT.groupby("spread_bucket", observed=True).agg(
    n=("net_bp", "size"),
    mean_d_spread_bp=("d_spread_bp", "mean"),
    mean_net_bp=("net_bp", "mean"),
    mean_residual_bp=("residual_bp", "mean"),
    hit=("net_bp", lambda s: float((s > 0).mean())))
print("closed cohorts bucketed by REALISED curve move over the hold:")
print(_t.to_string(float_format=lambda v: f"{v:,.3f}"))
print("\nA pure convexity trade is a SMILE in this table — money in both tails,\n"
      "least in the middle. A directional one is monotone across it.")

# %% [markdown]
# ## 13. Verdict — written from the computed numbers, not typed in

# %%
VERDICT = {
    "what_was_missing": ("strat1_real_contracts ran zero QueryDrivenBacktest passes and "
                         "made no P&L claim; this notebook supplies the engine runs, the "
                         "daily mark-to-market and the equity curves."),
    "window": [str(GRID[0].date()), str(GRID[-1].date())],
    "span_years": SPAN_YEARS,
    "engine_runs": {
        "unit_passes": len(LABELS),
        "certification_passes": 1,
        "books_composed": len(EQUITY),
        "marks_per_run": int(len(GRID)),
    },
    "config": {
        "strat1": {k: (list(v) if isinstance(v, tuple) else
                       str(v) if isinstance(v, datetime.date) else v)
                   for k, v in S1.as_dict().items()},
        "study": {k: (list(v) if isinstance(v, tuple) else v)
                  for k, v in CFG.as_dict().items()},
    },
    "saturation": {
        "saturated_structures": SATURATED,
        "binding_structures": BINDING,
        "note": ("on the saturated three the curve is cheap gamma against BOTH "
                 "benchmarks on 100% of usable days, so their gated books are the "
                 "always-on control with coverage holes and nothing else."),
        "table": json.loads(SAT["real"].set_index("structure").to_json(orient="index")),
    },
    "cm_vs_real_signal": json.loads(CM_VS_REAL.set_index("structure").to_json(orient="index")),
    "certification": CERT,
    "per_structure_gate": json.loads(
        STATS.set_index(["structure", "gate"])[_cols[2:]].reset_index()
        .to_json(orient="records")),
    "pooled": json.loads(POOLED.to_json(orient="index")),
    "sample_size": {k: v for k, v in NEFF.items() if k != "n_eff_per_structure"},
    "n_eff_per_structure": NEFF["n_eff_per_structure"],
    "multiple_testing": {
        "n_trials": N_TRIALS,
        "trials": list(CFG.distinct_gate_modes),
        "cm_control_counted_as_trial": False,
        "e_max_sharpe_under_null": BAR,
        "gates_clearing": CLEARS,
        "prior_signal_only_run": PRIOR,
    },
    "cost": {
        "headline_bp_one_way": S1.cost_bp_one_way,
        "breakeven_bp_one_way": json.loads(_be.to_json(orient="index")),
    },
    "what_the_signal_added_over_the_control": json.loads(
        SIGNAL_VALUE.to_json(orient="records")),
    "gates_beating_the_always_control_pooled": _helped,
    "real_contract_vs_cm_in_the_book": json.loads(
        REAL_VS_CM_BOOK.set_index("structure").to_json(orient="index")),
    "concurrency": json.loads(CONCURRENCY.set_index("gate").to_json(orient="index")),
}
if len(BASE_CMP):
    VERDICT["vs_committed_base_run"] = json.loads(
        BASE_CMP.set_index("structure").to_json(orient="index"))
VERDICT["direction_vs_convexity"] = json.loads(DECOMP.to_json(orient="records"))
# default=str: one leaked numpy.bool_ or float64 would kill this cell after an
# hour of engine time, and there is no upside to finding out which one.
(DATA / "strat1_longend_listed_verdict.json").write_text(
    json.dumps(VERDICT, indent=1, default=str))

# --- persist per (structure, gate): daily equity, cohort table, summary row
_written = 0
for (_label, _m), _eq in EQUITY.items():
    _eq.to_frame("equity_usd").to_parquet(
        DATA / f"strat1_le_equity_{SAFE[_label]}_{_m}.parquet")
    (BOOKS[(BOOKS["structure"] == _label) & (BOOKS["gate_mode"] == _m)]
     .to_parquet(DATA / f"strat1_le_cohorts_{SAFE[_label]}_{_m}.parquet", index=False))
    _written += 2
# pooled curves too -- the tables in section 8b are quoted off these
for _m in ALL_MODES:
    POOLED_EQUITY[_m].to_frame("equity_usd").to_parquet(
        DATA / f"strat1_le_equity_POOLED_{_m}.parquet")
    _written += 1
BOOKS.to_parquet(DATA / "strat1_le_cohort_books.parquet", index=False)
STATS.to_parquet(DATA / "strat1_le_summary.parquet", index=False)
POOLED.reset_index().to_parquet(DATA / "strat1_le_summary_pooled.parquet", index=False)
COST.to_parquet(DATA / "strat1_le_cost_sensitivity.parquet", index=False)
SIGNAL_VALUE.to_parquet(DATA / "strat1_le_signal_value.parquet", index=False)
print(f"wrote {_written} per-book parquets plus the combined cohort book, the "
      f"per-structure and pooled summaries, the cost table and the signal-value "
      f"table to {DATA}")

# %% [markdown]
# ### What this run actually established
#
# Written against the numbers above, deliberately terse about the difference
# between "measured" and "shown to work":
#
# * **The engine ran.** Four unit passes plus one certification pass, ~1,900
#   daily marks each, every cohort marked to market and cohorts still open at
#   the sample end marked rather than force-closed. That is the thing that was
#   missing and it is now present.
# * **The composition is the engine.** Certified against an independent
#   `QueryDrivenBacktest` of a gated book — terminal gap and daily-change
#   correlation both reported above — and tied to `strat1_threeway.apply_gate`
#   at the cohort level for every (structure, gate) pair.
# * **Three of the four structures carry no information about the gate.** They
#   are saturated; their four books are one book. Presenting four equity curves
#   there as four results would be the most misleading thing this study could
#   do, which is why section 4 runs before section 8.
# * **The sample is ~9.7 independent observations, pooled.** Read the
#   scoreboard in section 10 before any Sharpe in section 8, and read the
#   `always` control next to every gated book: the question is never "did this
#   make money" but "did the signal add anything over simply being long the
#   flattener".
# * **What the books do NOT establish.** The long-end flattener made money over
#   2019-2026 on every gate, and section 12 says how much of that is the curve
#   move rather than the convexity. None of it clears the multiple-testing bar,
#   and the control beating the gates (section 8c) is the cleanest statement of
#   the result: on this sample the vol benchmark's only effect was to remove
#   cohorts, and removing cohorts from a book that was making money cost money.

# %%
print(json.dumps({k: VERDICT[k] for k in
                  ("window", "span_years", "engine_runs", "certification",
                   "multiple_testing", "gates_beating_the_always_control_pooled")},
                 indent=1, default=str))
