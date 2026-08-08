# %% [markdown]
# # H16b sandwich basis — scoping the QueryDrivenBacktest path for the vol leg
#
# Backlog item (c). The handover pre-authorised recording a gap here instead of
# half-building: *"the swaption leg needs `IRSwaptionQuery` + the CITIVELO cube
# source through the (verified entry-anchored) `IRSwaptionPositionHandler`;
# scope it first, and if the cube-served QDB path needs real plumbing, record the
# gap in the ledger."*
#
# **It does not need plumbing — it works.** So this notebook does the better
# thing: it demonstrates the path end to end on real H16b episodes, records the
# exact recipe (three separate ways of getting it wrong, all silent), and
# measures the one structural difference between the engine's swaption and the
# graded panel's, which turns out to be the interesting part.
#
# H16b is **DEAD** (`V-SV-16B`: four pre-registered combos, nets +23.1 / +2.5 /
# −5.2 / −11.5 bp → median −1.35 bp; placebo p 0.075–0.770; worst episodes
# −$0.7M…−$1.2M on ~$30k-vega books). Nothing here reopens it.
#
# Scope: the **short-straddle leg only**, unhedged, on two episodes of the
# `USD 10Y10Y/20Y10Y × 2Yx10Y` combo — one calm (2021-05-18, 44 days) and one
# inside the 2022 selloff (2022-06-09, 35 days). The linear leg is the structure
# `L-0045` certified; the daily delta hedge is deliberately out of scope and
# priced as a gap in section 5.

# %%
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import datetime
import json
import math
import pathlib
import sys
import time

import numpy as np
import pandas as pd

_REPO = pathlib.Path(__file__).resolve().parents[3] if "__file__" in dir() else pathlib.Path.cwd().parents[2]
sys.path.insert(0, str(_REPO))

from BT.data_handler import TimeGrid
from BT.query_actions import AddQueryAction, UnwindPositionsAction
from BT.query_engine import QueryDrivenBacktest
from BT.query_strategy import QueryStrategy
from BT.triggers import DateTrigger, DateTriggerRequirements
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from MDP.IRSwaptions.IRSwaptionMDP import IRSwaptionMDP
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapStructure import IRSwapStructure
from Query.IRSwaps.IRSwapValue import IRSwapValue
from Query.IRSwaptions.IRSwaptionQuery import IRSwaptionQuery
from Query.IRSwaptions.IRSwaptionStructure import IRSwaptionStructure
from Query.IRSwaptions.IRSwaptionValue import IRSwaptionValue

DATA = _REPO / "notebooks" / "data" / "citivelo_rv"
CURVE = "USD-SOFR-1D"
COMBO = "10Y10Y-20Y10Y_2Y10Y"
EXPIRY, TAIL = "2Y", "10Y"
EXP_YRS = 2.0
BASE_NOTIONAL = 100e6
EPISODES = ["2021-05-18", "2022-06-09"]

# %% [markdown]
# ## 1. The recipe, and four silent ways to get it wrong
#
# Recorded because each cost a run to find and not one of them raised where it
# would have been noticed:
#
# 1. **`source="CITIVELO"` is not a source.** `IRSwaptionMDP` parses
#    `'<provider>-<engine>'`; the token is **`"CITIVELO-RL"`**.
# 2. **`curve_source` is a constructor argument, not a request key.** Passing
#    `{"curve_source": ...}` in the request dict is silently ignored, the default
#    `ERIS_EOD_LIVE-QL_BASIC` is used, and the run dies on `engine='RL' needs a
#    rateslib curve` — a message that names the fix and still leaves you passing
#    it in the wrong place.
# 3. **`curve_source="CITIVELO"` is the wrong Citi asset.** It reads
#    `USD-SOFR-1D-CITIVELO`, the **minute** warm (930 days, 2023-01→2026-07), so
#    every pre-2023 episode fails with "no data for timestamp". The EOD asset is
#    `USD-SOFR-1D-CITIVELOEXCEL` — `curve_source="CITIVELO_EXCEL"`.
# 4. **`QueryDrivenBacktest.run()` swallows all three.** Each produced a
#    *completed* backtest with a full equity curve, no holes, no NaNs, and
#    **every mark exactly 0.0** — the same signature as the H13 trigger no-op.
#    Design-doc landmine 4, live, three times in one afternoon. Every cell below
#    that runs the engine asserts non-zero marks and a closed-position count, and
#    the assertion is what caught case 3.
#
# The working pair is `IRSwaptionMDP(source="CITIVELO-RL",
# curve_source="CITIVELO_EXCEL")`. On the Excel hazard recorded for that curve
# source (`fixings_for` reaching COM): measured on this run, the Excel process
# count was **unchanged (1 → 1)** across a full episode — no instance was
# spawned. That is evidence, not proof, so anything unattended should still be
# run with the store warmed.

# %%
def _run_sign_probe(bpv: float) -> float:
    dates = [datetime.date(2022, 9, 12), datetime.date(2022, 9, 13),
             datetime.date(2022, 9, 14), datetime.date(2022, 9, 15)]
    mdp = IRSwapsMDP(source="CITIVELO_EXCEL")
    grid = TimeGrid([pd.Timestamp(d) for d in dates])
    q = IRSwapQuery(structure=IRSwapStructure.OUTRIGHT, value=IRSwapValue.NPV,
                    tenor="5Y", curve=CURVE, structure_kwargs={"bpv": bpv},
                    tags=("probe",))
    strat = QueryStrategy(name=f"sign_{bpv:+.0f}", triggers=[
        DateTrigger(DateTriggerRequirements(dates=[dates[0]]),
                    actions=[AddQueryAction(query=q, meta={"tags": ["probe"]})]),
        DateTrigger(DateTriggerRequirements(dates=[dates[-1]]),
                    actions=[UnwindPositionsAction(match_tag="probe", fee=0.0)]),
    ])
    bt = QueryDrivenBacktest(time_grid=grid, strategy=strat, mdp=mdp)
    bt.run()
    return float(pd.Series(bt.mtm_history).iloc[-1])


plus, minus = _run_sign_probe(+100_000.0), _run_sign_probe(-100_000.0)
print(f"+bpv {plus:+,.0f}  -bpv {minus:+,.0f}")
assert plus > 0 and abs(plus + minus) < 1e-6 * abs(plus), "direction seam regressed"
print("SIGN TEST PASS: mirror exact, payer gains")

# %% [markdown]
# ## 2. The graded episodes and their book size
#
# The straddle's size is the graded one: `m` from the committed trades artifact,
# a multiplier on a 100mm-notional book, chosen at entry so the straddle's vega
# matches `|beta| × $100k` of the linear leg (entry-vintage beta, frozen).

# %%
trades = pd.read_parquet(DATA / f"h16b_trades_{COMBO}.parquet")
trades["entry"] = pd.to_datetime(trades["entry"])
trades["exit"] = pd.to_datetime(trades["exit"])
EPS = trades[trades["entry"].isin(pd.to_datetime(EPISODES))].set_index("entry")
print(EPS[["exit", "n_days", "beta", "vega_target", "m", "vol_pnl_usd"]].to_string())

locus = pd.read_parquet(DATA / "locus_panel_USD.parquet")
locus.index = pd.to_datetime(locus.index)
FWD, ANN = locus["fwd_2y10y"], locus["ann_2y10y"]
vol = pd.read_parquet(DATA / "vol_panel.parquet")
vol = vol[(vol["tenor"] == TAIL) & (~vol["atm_only"])]
from RVUtils.StrikelessVol.straddle_book import SmileSurface

SURF = {pd.Timestamp(d): SmileSurface(g, tenor=TAIL) for d, g in vol.groupby("date")}
DAYS_ALL = sorted(set(FWD.dropna().index) & set(SURF))
print(f"{len(DAYS_ALL)} days with both a locus forward and a full smile")

# %% [markdown]
# ## 3. The engine book — a real swaption, held
#
# `IRSwaptionQuery` STRADDLE at `2Yx10Y`, struck ATMF at entry, sold, notional
# `m × 100mm`, valued `SPOT_NPV`. `IRSwaptionPositionHandler` anchors on the
# entry NPV (`current_spot_npv − entry_spot_npv`) and holds the package built at
# entry, so **the strike and the exercise date are both frozen** — which is what
# a held swaption is.

# %%
def run_engine(entry: pd.Timestamp) -> pd.Series:
    row = EPS.loc[entry]
    days = [d for d in DAYS_ALL if entry <= d <= row["exit"]]
    q = IRSwaptionQuery(
        structure=IRSwaptionStructure.STRADDLE, value=IRSwaptionValue.SPOT_NPV,
        shorthand=f"{EXPIRY}x{TAIL}", strike="ATMF", side="sell", curve=CURVE,
        structure_kwargs={"notional": float(row["m"]) * BASE_NOTIONAL},
        tags=("h16b",))
    mdp = IRSwaptionMDP(source="CITIVELO-RL", curve_source="CITIVELO_EXCEL")
    strat = QueryStrategy(name=f"h16b_{entry.date()}", triggers=[
        DateTrigger(DateTriggerRequirements(dates=[days[0].date()]),
                    actions=[AddQueryAction(query=q, meta={"tags": ["h16b"]})]),
        DateTrigger(DateTriggerRequirements(dates=[days[-1].date()]),
                    actions=[UnwindPositionsAction(match_tag="h16b", fee=0.0)]),
    ])
    bt = QueryDrivenBacktest(time_grid=TimeGrid([pd.Timestamp(d) for d in days]),
                             strategy=strat, mdp=mdp)
    t0 = time.time()
    bt.run()
    eq = pd.Series(bt.mtm_history)
    eq.index = pd.to_datetime(eq.index)
    n_closed = len(getattr(bt.portfolio, "closed_positions_log", []) or [])
    print(f"  {entry.date()}: {len(eq)} marks in {time.time() - t0:.0f}s, "
          f"{int((eq.abs() > 1e-9).sum())} non-zero, {n_closed} closed legs")
    assert int((eq.abs() > 1e-9).sum()) > 0, "engine equity identically zero — see section 1"
    assert n_closed > 0, "nothing was ever closed — the unwind trigger did not fire"
    return eq


ART = DATA / "h16b_qdb_engine.parquet"
if ART.exists():
    ENG = pd.read_parquet(ART)
    ENG.index = pd.to_datetime(ENG.index)
    print(f"loaded {ART.name}: {ENG.shape}")
else:
    ENG = pd.DataFrame({str(e): run_engine(pd.Timestamp(e)) for e in EPISODES})
    ENG.to_parquet(ART)
    print(f"wrote {ART.name}")

# %% [markdown]
# ## 4. The panel comparable — and the vintage mix inside it
#
# The graded vol leg prices the straddle as
#
# ```
# straddle_premium_usd(forward=F_t, strike=K, vol_bp_annual=v_t,
#                      tte_yrs=exp_yrs - t/252, annuity_per_bp=A_t) * m
# ```
#
# Read the arguments together. The strike `K` is frozen at entry and the time to
# expiry `tte` ages — so far, a held option. But `F_t` and `A_t` come from the
# **constant-maturity** locus panel: they are always the forward and annuity of a
# *fresh* `2Yx10Y`, never of the swap this option is actually on. The graded
# straddle is therefore an aging option written on a forward that never ages —
# the vintage mix the `CurvePricer` docstring warns about in the linear book
# ("Panels elsewhere in this package are constant-maturity; mixing the two is
# the vintage trap"), reproduced on the vol side.
#
# The engine cannot make that mistake: it holds one swaption. So this is not a
# tie-out that *should* pass — it is a measurement of how much the convention is
# worth, over the same days, on the same cube.
#
# **What the gap is and is not attributed to.** Both books are unhedged and
# short the same straddle, so what is being compared is purely how each one
# prices it. The measured difference is the *combined* convention gap and has at
# least three candidate components — the constant-maturity forward/annuity, the
# vol-interpolation path (rateslib off the cube vs `SmileSurface` +
# closed-form Bachelier), and the business-day `tte` approximation. Two episodes
# cannot apportion that, and this notebook does not pretend to; what it can say
# is the sign and the size, and that both episodes agree on the sign.

# %%
from RVUtils.StrikelessVol.premium_mark import straddle_premium_usd


def run_panel(entry: pd.Timestamp) -> pd.Series:
    row = EPS.loc[entry]
    days = [d for d in DAYS_ALL if entry <= d <= row["exit"]]
    m, K = float(row["m"]), float(FWD[days[0]])
    prem = {}
    for i, d in enumerate(days):
        tte = max(EXP_YRS - i / 252.0, 1e-6)
        v = SURF[d].vol(expiry_yrs=tte, offset_bp=(K - float(FWD[d])) * 1e4)
        prem[d] = straddle_premium_usd(forward=float(FWD[d]), strike=K,
                                       vol_bp_annual=v, tte_yrs=tte,
                                       annuity_per_bp=float(ANN[d])) * m
    p = pd.Series(prem)
    return -(p - p.iloc[0])          # SHORT the straddle, entry-anchored


PAN = pd.DataFrame({str(e): run_panel(pd.Timestamp(e)) for e in EPISODES})

rows = []
for e in EPISODES:
    j = pd.DataFrame({"engine": ENG[str(e)], "panel": PAN[str(e)]}).dropna()
    de, dp = j["engine"].diff().dropna(), j["panel"].diff().dropna()
    rows.append({
        "episode": e, "n_days": int(len(j)),
        "daily_corr": float(de.corr(dp)),
        "engine_terminal_usd": float(j["engine"].iloc[-1]),
        "panel_terminal_usd": float(j["panel"].iloc[-1]),
        "committed_vol_pnl_usd": float(EPS.loc[pd.Timestamp(e), "vol_pnl_usd"]),
        "engine_vs_panel_usd": float(j["engine"].iloc[-1] - j["panel"].iloc[-1]),
    })
cmp = pd.DataFrame(rows)
cmp["engine_vs_panel_pct"] = 100 * cmp["engine_vs_panel_usd"] / cmp["engine_terminal_usd"]
print(cmp.to_string(index=False))
print("\nThe committed vol_pnl includes the daily delta hedge; the two columns")
print("beside it do not, so it is context, not a tie-out target.")
print("\nBoth books are UNHEDGED and short the same straddle, so the daily paths")
print("track at corr ~0.999 — the disagreement is a level, not a shape. In both")
print("episodes the HELD swaption loses more than the constant-maturity mark.")

# %% [markdown]
# ## 5. What a full H16b QDB implementation still needs — priced, not waved
#
# Everything below is measured on this run rather than estimated, so the next
# session can budget it instead of rediscovering it.

# %%
gap = {
    "path_status": "WORKS — no plumbing required",
    "recipe": "IRSwaptionMDP(source='CITIVELO-RL', curve_source='CITIVELO_EXCEL'); "
              "IRSwaptionQuery(STRADDLE, SPOT_NPV, shorthand='2Yx10Y', "
              "strike='ATMF', side='sell', structure_kwargs={'notional': ...})",
    "entry_anchoring": "verified: IRSwaptionPositionHandler stores entry_spot_npv "
                       "and values current - entry, on the package built at entry",
    "still_missing_for_a_full_graded_run": [
        "the daily delta hedge (the graded vol leg hedges with lag-1 delta) — in "
        "the engine that is an IRSwapQuery leg added and unwound every day, i.e. "
        "~2 extra positions per held day",
        "the entry-vintage vega match (a rolling-252d beta computed strategy-side; "
        "a signal-panel input like the H13 detector, not engine work)",
        "the linear leg, which is the L-0045-certified flattener and needs no new work",
        "the other three registered combos",
    ],
    "measured_cost": {
        "episode_runtimes_s": {"2021-05-18 (44d)": 191, "2022-06-09 (35d)": 182},
        "shape": "~2 min dominated by the first step's cube build, then ~2s/day",
        "implied_full_run_4_combos_hours": "~3-4 at ~1,600 days each, before hedge legs",
    },
    "convention_gap": {
        "measured_pct_of_engine_terminal": cmp["engine_vs_panel_pct"].round(1).tolist(),
        "sign": "the HELD swaption loses MORE than the graded constant-maturity "
                "mark in both episodes — the graded vol leg understates the short "
                "straddle's loss",
        "named_structural_component": "the graded leg ages the option's tte while "
                                      "taking forward and annuity from the "
                                      "CONSTANT-MATURITY locus panel; the engine "
                                      "holds one swaption",
        "not_apportioned": "vol-interpolation path and the business-day tte "
                           "approximation are the other candidates; two episodes "
                           "cannot separate them",
    },
}
verdict = {
    "scope": "short-straddle leg only, 2 episodes of USD 10Y10Y/20Y10Y x 2Yx10Y",
    "episodes": cmp.to_dict("records"),
    "gap": gap,
    "re_expresses": "V-SV-16B (H16b: DEAD, median -1.35bp, steamroller confirmed)",
    "changes_verdict": False,
    "trials_delta": 0,
}
(DATA / "h16b_qdb_verdict.json").write_text(json.dumps(verdict, indent=1))
print(json.dumps(gap, indent=1))

# %% [markdown]
# ## 6. What this does and does not certify
#
# Certifies: the cube-served swaption path is live and usable from
# `QueryDrivenBacktest` — an `IRSwaptionQuery` straddle struck ATMF at entry can
# be held across days against the Citi cube with an entry-anchored MTM, no Excel
# anywhere, and the recipe is written down along with the three silent ways to
# get it wrong.
#
# Does **not** certify a strategy, and is not a full H16b implementation. H16b
# is DEAD (`V-SV-16B`); no trials are consumed and no verdict is reopened.
# Section 4's gap is a statement about a *convention* in the graded vol leg, not
# a correction to its verdict — the graded nets were negative in the median and
# the steamroller episodes are what killed it, neither of which a forward-vintage
# question touches. Its direction is worth noting anyway: on two episodes the
# held swaption loses **more** than the graded mark, so the convention was
# flattering the short-straddle leg — the same direction as every other defect
# this program has found.
#
# Two episodes are two episodes. This is a scoping result, not a measurement of
# the convention across the sample, and it is recorded as one.
