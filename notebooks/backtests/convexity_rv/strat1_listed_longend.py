# %% [markdown]
# # Strategy 1-listed on the **long end** — does the curve stay cheap against a *listed* benchmark?
#
# **The question this notebook exists to answer.** J.P. Morgan, *"An option by
# any other name: Sourcing cheap convexity in the long end of the curve"*
# (Younger / Sarkar / Salem, 03-Feb-2017):
#
# > "The same can also be said when the level of volatility priced into the curve
# >  is less than that implied by ATMF swaptions."
#
# `strat1_curve_gamma` ran that comparison over 2019-01..2026-08 and found the
# long-end flatteners cheap against **1Yx30Y swaptions on 100% of days**. That is
# a suspiciously clean result, and it has an obvious alternative explanation:
# swaptions may simply be the *expensive* benchmark. Long-dated OTC vol is bid by
# structured-product and mortgage-convexity hedging flow; exchange-listed vol is
# priced by macro funds and dealer gamma. If the 100% is a statement about
# swaptions rather than about the curve, a listed benchmark should break it.
#
# The earlier `strat1_listed` notebook could not test that. The only listed vol
# available offline was **SFR (3M SOFR) options**, which price the *short end*,
# so it was forced onto SFR-sector structures and a 517-day window — the right
# method in the wrong sector.
#
# **What changed.** `scripts/harvest_ust_listed_vol.py` harvested QuikStrike
# **constant-maturity ATM vol for the whole UST futures complex**, 2019-01-02 ..
# 2026-08-14. The long end now has a listed benchmark over the *same full window*
# strategy 1 was measured on. This is the run that matters.
#
# ---
#
# ## What is hard here, and what is proved before anything is built on it
#
# 1. **§3-§5: the units.** "`ABPV` is a normal bp/yr yield vol" is a claim about a
#    column name. It is proved twice, by paths sharing no inputs — against the
#    swaption cube on matched sectors, and against the panel's own `ATM` column
#    through a CTD DV01 measured from the repo's offline basis store. **If this
#    had failed, the correct output would have been "the benchmark is
#    mis-scaled", and nothing below it.**
# 2. **§6: sector matching by measurement, not by contract name.** The contract
#    called "30-year bond" (`US`) has a cheapest-to-deliver with a median **15.9
#    years** left. The 30Y benchmark is the **Ultra Bond** (`UL`, CTD 25.6 yrs).
#    `TY` (CTD 6.8 yrs) is carried everywhere as a control that *should* score
#    worse.
# 3. **§7: the term structure, stated not assumed.** The curve breakeven is a
#    1-year number; the listed quotes are 30/60/90-day constant maturity. The
#    slope is measured and the verdict is reported at all three.
# 4. **§8-§9: sign probe and an exact payoff-profile regression.** The curve side
#    is *reused* from `strat1_signal_panel.parquet` rather than recomputed, so
#    that strategy 1's breakeven and this study's are the same number. §9 rebuilds
#    a sample of dates from the live curve and asserts the reuse is exact.
#
# **Network.** Nothing here can reach a vendor. The listed panel is a local
# parquet, the swaption cube a local store, the CTD/DV01 data a local cache.
# `USTFutureOptionMDP` is never imported — `sabr_smile` costs one HTTP call per
# strike and has no cached history.

# %%
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import dataclasses
import datetime
import json
import math
import pathlib
import sys
import time
import warnings
from dataclasses import dataclass, field
from typing import Tuple

import numpy as np
import pandas as pd

_REPO = pathlib.Path(__file__).resolve().parents[3] if "__file__" in dir() else pathlib.Path.cwd().parents[2]
sys.path.insert(0, str(_REPO))

import plotly.graph_objects as go
import plotly.io as pio
from plotly.subplots import make_subplots

pio.renderers.default = "plotly_mimetype+notebook_connected"

from BT.data_handler import TimeGrid
from BT.query_actions import AddQueryAction, UnwindPositionsAction
from BT.query_engine import QueryDrivenBacktest
from BT.query_strategy import QueryStrategy
from BT.triggers import DateTrigger, DateTriggerRequirements
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapStructure import IRSwapStructure
from Query.IRSwaps.IRSwapValue import IRSwapValue
from RVUtils.ConvexityRV import listed_vol as lv
from RVUtils.ConvexityRV import strat1_curve_gamma as s1
from RVUtils.ConvexityRV import strat1_listed as sl
from RVUtils.ConvexityRV.swaption_cube import atmf_vol_series, load_vol_panel

warnings.filterwarnings("ignore", category=RuntimeWarning)

DATA = _REPO / "notebooks" / "data" / "convexity_rv"
DATA.mkdir(parents=True, exist_ok=True)
pd.set_option("display.width", 240)
pd.set_option("display.max_columns", 80)
print("repo      ", _REPO)
print("artifacts ", DATA)
print("UST panel ", lv.default_ust_cm_path())
print("CTD store ", lv.default_ust_basis_root())

# %% [markdown]
# ## 1. CONFIG — every knob, documented at the point of use
#
# The strategy knobs live in `sl.Strat1ListedConfig`; this dataclass holds only
# the notebook's own wiring (paths, which dates the regression probes, plot
# choices). Nothing here is tuned on an outcome.

# %%
@dataclass(frozen=True)
class NBConfig:
    """Notebook wiring. Strategy knobs are in :class:`sl.Strat1ListedConfig`."""

    #: Full window. Both the swap curve and the UST constant-maturity panel run
    #: 2019-01-02..2026-08-14, so unlike the SFR study nothing is truncated —
    #: this is exactly the sample strategy 1 itself was measured on.
    start: datetime.date = datetime.date(2019, 1, 1)
    end: datetime.date = datetime.date(2026, 8, 14)

    #: Strategy 1's stored signal panel. The curve side is REUSED from it, never
    #: recomputed — see §9 for the regression that licenses that.
    strat1_panel: str = "strat1_signal_panel.parquet"

    #: Cached CTD / futures-DV01 frame built from the offline basis store. ~13 s
    #: to rebuild from 6,696 parquets; cached so a re-execute is instant.
    ctd_cache: str = "ust_ctd_fv01.parquet"

    #: Swaption nodes needed for the units check. The 1Yx30Y node the strategy
    #: compares against is already cached as vol_1Yx30Y.parquet; the SHORT-expiry
    #: nodes are what make the units check a matched-maturity comparison (a
    #: 30-day listed option against a 1-year swaption would confound the units
    #: question with the term structure).
    otc_pairs: Tuple[Tuple[str, str], ...] = (
        ("1M", "10Y"), ("1M", "20Y"), ("1M", "30Y"),
        ("2M", "10Y"), ("2M", "20Y"), ("2M", "30Y"),
        ("3M", "10Y"), ("3M", "20Y"), ("3M", "30Y"),
        ("6M", "10Y"), ("6M", "20Y"), ("6M", "30Y"),
        ("1Y", "10Y"), ("1Y", "20Y"), ("1Y", "30Y"),
    )
    otc_cache: str = "vol_shortexp_longtail.parquet"

    #: (listed root, cm days, swaption expiry, swaption tenor) pairs for §3.
    #: Deliberately includes deliberately-mismatched rows (US vs 1Mx10Y) so the
    #: table shows what a WORSE match looks like and the reader can calibrate
    #: "1.10 is a good ratio" against something.
    units_pairs: Tuple[Tuple[str, int, str, str], ...] = (
        ("US", 30, "1M", "30Y"), ("US", 60, "2M", "30Y"), ("US", 90, "3M", "30Y"),
        ("US", 30, "1M", "20Y"), ("US", 30, "1M", "10Y"),
        ("UL", 30, "1M", "30Y"), ("UL", 90, "3M", "30Y"), ("UL", 30, "1M", "20Y"),
        ("TN", 30, "1M", "10Y"), ("TY", 30, "1M", "10Y"), ("TY", 90, "3M", "10Y"),
        ("FV", 30, "1M", "10Y"), ("TU", 30, "1M", "10Y"),
        ("US", 30, "1Y", "30Y"), ("UL", 30, "1Y", "30Y"),
    )

    #: Dates the payoff-profile regression rebuilds from the live curve. Spread
    #: across the sample and chosen to hit every breakeven branch — `root`,
    #: `always_cheap` and `never_cheap` — because a regression that only ever
    #: sees one branch does not test the two that carry the study's headline.
    regression_dates: Tuple[str, ...] = (
        "2019-03-01", "2020-03-25", "2021-06-15", "2022-09-13",
        "2023-11-24", "2024-07-01", "2025-03-03", "2026-06-15",
    )

    #: Date for the live sign probe. 2022-09 is a large, unambiguous selloff, so
    #: a payer's P&L sign is not a coin flip.
    probe_dates: Tuple[str, ...] = ("2022-09-12", "2022-09-13", "2022-09-14", "2022-09-15")

    #: Package DV01 for the probes; matches the strategy config.
    package_dv01: float = 100_000.0
    curve: str = "USD-SOFR-1D"


NB = NBConfig()
CFG = sl.Strat1ListedConfig(
    longend_structures=sl.LONG_END_STRUCTURES,
    longend_cm_days=(30, 60, 90),
    longend_start=NB.start,
    longend_end=NB.end,
)
print(json.dumps({k: str(v) for k, v in dataclasses.asdict(NB).items()}, indent=1)[:1200])
print()
print("structures    ", [lab for lab, _, _ in CFG.longend_structures])
print("cm days       ", CFG.longend_cm_days)
print("OTC benchmark ", f"{CFG.longend_otc_expiry}x{CFG.longend_otc_tenor}")
print("window        ", CFG.longend_start, "..", CFG.longend_end)

# %% [markdown]
# ## 2. The new data — the long-end listed panel
#
# `ust_listed_vol.parquet`: 58,176 rows, 36 series, six roots × {30, 60, 90}-day
# constant maturity × {ABPV, ATM}.
#
# Two value types, and they are **not** the same kind of number:
#
# | column | what it is |
# |---|---|
# | `ABPV` | annualised **normal** vol of the underlying's **yield**, bp/yr |
# | `ATM`  | **lognormal** vol of the futures **price**, a decimal |
#
# `HistVol30D` raises for every root and the 180-day constant maturity is empty
# for every root — so this panel contains **no realised-vol series**. The SFR
# study's realised-vs-implied cross-check has no analogue here, which is exactly
# why §3 and §4 do the work with two *independent* implied-side checks instead.
#
# Constant maturity is a real advantage and not just convenience: a listed
# contract series carries an expiry sawtooth (vol rises into expiry) that would
# be injected into every regression as a fake cycle.

# %%
UST = lv.load_ust_cm_panel(start=NB.start, end=NB.end)
print("rows", f"{len(UST):,}", " series", UST.groupby(['symbol', 'value_type']).ngroups)
cov = lv.ust_coverage_report(UST)
_covdf = pd.DataFrame(cov["series"]).T
_covdf.index.name = "series"
print(_covdf.to_string())

# %%
# ABPV coverage per root, and what each root's option actually prices.
_abpv = UST[UST.value_type == "ABPV"]
_tbl = (_abpv.groupby("root")
        .agg(n_rows=("value", "size"),
             first=("date", "min"), last=("date", "max"),
             median_bp_yr=("value", "median"), median_bp_day=("value_bp_day", "median"))
        .assign(swap_point=lambda d: d.index.map(
            lambda r: lv.UST_CTD_PROFILE[r]["swap_point"]),
                ctd_ttm_yrs=lambda d: d.index.map(
            lambda r: lv.UST_CTD_PROFILE[r]["ctd_ttm_yrs"])))
print(_tbl.round(3).to_string())
assert len(UST), "UST panel is empty"
assert {"ABPV", "ATM"} <= set(UST.value_type.unique())
assert 180 not in set(UST.cm_days.unique()), "180d CM was expected to be absent"
print("\nOK: ABPV + ATM present, no 180d constant maturity, no realised-vol series.")

# %% [markdown]
# ## 3. UNITS CHECK 1a — ABPV against the swaption cube on matched sectors
#
# If `ABPV` is a normal bp/yr vol of a **Treasury yield**, then a 30-day
# constant-maturity quote on the bond future must sit in the same range as the
# **1Mx30Y** OTC normal vol of the swap rate and co-move with it. Anything else —
# a percentage vol, a price vol, a daily rather than annual number — would be out
# by a factor of ~10 or ~16, not by a few percent.
#
# Both the **level** correlation and the **daily-change** correlation are
# reported. They answer different questions: levels can correlate through a
# shared trend while the two markets move independently day to day, and only the
# changes column would expose that.
#
# The table deliberately carries some **mismatched** rows (`US` against 1Mx10Y)
# so "1.10 is a good ratio" can be calibrated against something.

# %%
_t0 = time.time()
OTC = load_vol_panel(list(NB.otc_pairs), cache_path=DATA / NB.otc_cache)
print(f"swaption panel {OTC.shape}  ({time.time() - _t0:.0f}s)")
UNITS_A = lv.ust_units_check_vs_swaptions(UST, OTC, NB.units_pairs)
print(UNITS_A.round(4).to_string(index=False))

# %%
# The matched rows are the ones the verdict rests on.
_matched = UNITS_A[UNITS_A.apply(
    lambda r: (r.listed_symbol.startswith(("US", "UL")) and r.otc_node.endswith(("30Y", "20Y"))
               and not r.otc_node.startswith("1Y"))
    or (r.listed_symbol.startswith(("TY", "TN")) and r.otc_node.endswith("10Y")), axis=1)]
print("matched-sector rows only:")
print(_matched[["listed_symbol", "otc_node", "n", "median_listed_bp_yr",
                "median_otc_bp_yr", "ratio", "r_level", "r_change"]].round(4).to_string(index=False))
assert (_matched["ratio"] > 0.8).all() and (_matched["ratio"] < 1.25).all(), \
    "a matched-sector ratio outside 0.8-1.25 would mean ABPV is not a bp/yr normal vol"
assert (_matched["r_level"] > 0.85).all(), "matched-sector level correlation must be high"
assert (_matched["r_change"] > 0.3).all(), "daily changes must co-move"
print(f"\nUNITS 1a PASS: {len(_matched)} matched pairs, ratio "
      f"{_matched.ratio.min():.3f}-{_matched.ratio.max():.3f}, "
      f"r_level {_matched.r_level.min():.3f}-{_matched.r_level.max():.3f}, "
      f"r_change {_matched.r_change.min():.3f}-{_matched.r_change.max():.3f}")

# %%
# Scatter + time series for the three headline pairs.
_pairs_plot = [("US_30", "1M", "30Y"), ("US_90", "3M", "30Y"), ("UL_30", "1M", "30Y")]
fig = make_subplots(rows=2, cols=3, vertical_spacing=0.13,
                    subplot_titles=[f"{s} vs {e}x{t}" for s, e, t in _pairs_plot]
                                   + [f"{s} / {e}x{t} — daily" for s, e, t in _pairs_plot])
for i, (sym, exp, ten) in enumerate(_pairs_plot, start=1):
    root, cm = sym.split("_")
    _l = lv.ust_cm_series(UST, root, int(cm))
    _o = atmf_vol_series(OTC, exp, ten)
    _j = pd.concat([_l.rename("listed"), _o.rename("otc")], axis=1).dropna()
    fig.add_trace(go.Scattergl(x=_j.otc, y=_j.listed, mode="markers",
                               marker=dict(size=3, opacity=0.45, color="#2b6cb0"),
                               name=sym, showlegend=False), row=1, col=i)
    _lo, _hi = float(min(_j.min())), float(max(_j.max()))
    fig.add_trace(go.Scatter(x=[_lo, _hi], y=[_lo, _hi], mode="lines",
                             line=dict(color="#888", dash="dash", width=1),
                             showlegend=False), row=1, col=i)
    fig.add_trace(go.Scatter(x=_j.index, y=_j.listed, name=f"{sym} listed",
                             line=dict(color="#2b6cb0", width=1),
                             showlegend=(i == 1)), row=2, col=i)
    fig.add_trace(go.Scatter(x=_j.index, y=_j.otc, name=f"{exp}x{ten} OTC",
                             line=dict(color="#c05621", width=1),
                             showlegend=(i == 1)), row=2, col=i)
    fig.update_xaxes(title_text="OTC bp/yr", row=1, col=i)
    fig.update_yaxes(title_text="listed bp/yr" if i == 1 else None, row=1, col=i)
fig.update_layout(height=680, title="Units check 1a — listed ABPV vs matched swaption ATMF "
                                    "(dashed = 45°)", template="plotly_white")
fig.show()

# %% [markdown]
# ## 4. UNITS CHECK 1b — ABPV against the panel's own `ATM`, through the CTD DV01
#
# The second check shares no inputs with the first. The two value types in this
# panel are related by the futures DV01 and nothing else:
#
# $$\sigma_{price}(\text{points}) = \text{ATM}\times P_{fut}
# \qquad
# \text{ABPV(bp)} = \frac{\sigma_{price}}{FV01}
# \qquad
# FV01 = \frac{ModDur_{ctd}\times Dirty_{ctd}}{10^4 \times CF_{ctd}}$$
#
# That `FV01` definition is **the repo's own** — `USTFutureOptionMDP._compute_fv01`
# line for line — so this is measured against the codebase's definition of a
# futures DV01, not a new one.
#
# Every input is available **offline** from the repo's UST basis-report store
# (`futures_price`, the `is_ctd` bond's `clean_price` / `ytm` / `invoice_cf`).
# Only `ModDur` has to be computed, by `lv.bond_price_and_duration`.
#
# **The check on the check.** That bond maths is not trusted: for every CTD row it
# re-prices the bond from its own quoted yield and compares to the quoted clean
# price. If the label parse, the coupon schedule or the discounting were wrong,
# the residual would be large. It is not.

# %%
# Closed-form self-test first: a 10y 4% semiannual bond at 4% must price at par
# with Macaulay 8.3393 and modified 8.1757 years.
_d, _c, _m = lv.bond_price_and_duration(4.0, datetime.date(2030, 1, 15),
                                        datetime.date(2020, 1, 15), 4.0)
print(f"par-bond self-test: clean={_c:.8f} (expect 100)  moddur={_m:.5f} (expect 8.17572)")
assert abs(_c - 100.0) < 1e-8
assert abs(_m - 8.175716) < 1e-5
assert lv.parse_treasury_label("T 4 1/2 Aug 39") == (4.5, 8, 2039)
assert lv.parse_treasury_label("T 2 Nov 22") == (2.0, 11, 2022)
assert lv.ust_abpv_from_price_vol(0.10, 120.0, 0.12) == 100.0
# 0.14 is not representable in binary, so this one needs a tolerance.
assert abs(lv.ust_abpv_from_price_vol(0.14, 150.0, 0.25) - 84.0) < 1e-12
print("bond maths + label parse + ABPV identity: hand-computed answers PASS")

# %%
_p = DATA / NB.ctd_cache
if _p.exists():
    CTD = pd.read_parquet(_p)
    print(f"CTD frame from cache {_p.name}  {CTD.shape}")
else:
    _t0 = time.time()
    CTD = lv.load_ctd_basis_frame()
    CTD.to_parquet(_p, index=False)
    print(f"CTD frame built from the offline basis store  {CTD.shape}  ({time.time() - _t0:.0f}s)")
CTD["date"] = pd.to_datetime(CTD["date"])

_err = CTD["price_err_pts"]
print(f"\nCTD repricing residual (|calc - quoted| clean price, points):")
print(f"  median {_err.median():.5f}   p90 {_err.quantile(.9):.5f}   "
      f"p99 {_err.quantile(.99):.5f}   max {_err.max():.5f}")
print(f"  median in 32nds: {_err.median() * 32:.3f}")
assert _err.median() < 0.01, "bond maths does not reproduce the store's own prices"
print("\nper-root CTD state (median):")
print(CTD[CTD.root.isin(lv.UST_CM_ROOTS)].groupby("root")[
    ["ctd_mod_duration", "ctd_dirty_price", "invoice_cf", "futures_price",
     "fv01_points_per_bp", "price_err_pts"]].median().round(5).to_string())

# %%
# The comparison itself, date-matched, at all three constant maturities.
UNITS_B = pd.concat([lv.ust_units_check_dv01(UST, CTD, cm_days=cm)
                     for cm in CFG.longend_cm_days], ignore_index=True)
print(UNITS_B.round(4).to_string(index=False))

_long = UNITS_B[UNITS_B.root.isin(["US", "UL"])]
assert (_long["ratio"] > 0.95).all() and (_long["ratio"] < 1.05).all(), \
    "the DV01 identity must reproduce ABPV to within 5% for the long-end roots"
print(f"\nUNITS 1b PASS on the long-end roots: implied/actual ABPV "
      f"{_long.ratio.min():.4f}-{_long.ratio.max():.4f} "
      f"(US, UL at 30/60/90d CM, n={int(_long.n.sum())} root-days)")

# %% [markdown]
# ### 4b. The same identity with the futures price algebraically removed
#
# $FV01 \approx ModDur \times P/10^4$, so $P$ cancels out of
# $\text{ABPV} = \text{ATM}\times P / FV01$ and
#
# $$ModDur = \frac{10^4 \times \text{ATM}}{\text{ABPV}}$$
#
# This needs **no price, no DV01 and no external data at all** — only the two
# columns of the panel itself. It is therefore the cheapest possible regression
# test that the panel has not been silently rescaled, and it has three properties
# that a coincidence would not: the ratio must be a duration in years, it must be
# stable through time, and it must **not** move with the option's constant
# maturity, because duration is a property of the bond and not of the option.

# %%
IMPL_DUR = lv.ust_implied_ctd_duration(UST)
_meas = (CTD[CTD.root.isin(lv.UST_CM_ROOTS)].groupby("root")["ctd_mod_duration"]
         .median().rename("measured_from_basis_store"))
IMPL_DUR = IMPL_DUR.merge(_meas, on="root", how="left")
IMPL_DUR["ratio_to_measured"] = IMPL_DUR["implied_mod_duration"] / IMPL_DUR["measured_from_basis_store"]
print(IMPL_DUR.round(4).to_string(index=False))

_bycm = lv.ust_implied_ctd_duration(UST, by_cm=True).pivot(
    index="root", columns="cm_days", values="implied_mod_duration")
_bycm["spread"] = _bycm.max(axis=1) - _bycm.min(axis=1)
print("\nimplied duration by constant maturity (must be flat — duration is a bond property):")
print(_bycm.round(4).to_string())
assert (_bycm["spread"] < 0.2).all(), "implied duration must not depend on the option's CM tenor"
assert (IMPL_DUR["ratio_to_measured"].between(0.85, 1.15)).all(), \
    "implied duration must match the duration measured from the basis store"
print(f"\nprice-free identity PASS: implied/measured duration "
      f"{IMPL_DUR.ratio_to_measured.min():.3f}-{IMPL_DUR.ratio_to_measured.max():.3f}, "
      f"CM spread max {_bycm['spread'].max():.3f} yrs")

# %% [markdown]
# ## 5. UNITS VERDICT
#
# **PASS.** Two independent measurements agree that `ABPV` is an annualised
# normal (Bachelier) volatility of the underlying's yield, quoted in basis points
# per year, exactly as the harvest documents it.
#
# **The residual, stated plainly.** Listed UST vol runs a few percent **above**
# the matched swaption vol. That is a real basis with the expected sign, not a
# units error:
#
# 1. a **Treasury** yield is more volatile than the **swap** rate of the same
#    tenor — the swap-spread component adds variance to the Treasury leg;
# 2. a bond-future option carries the **delivery / CTD switch option**, which is
#    itself long vol and is inside the quoted implied number but not inside the
#    DV01 used to convert it.
#
# Both push the same way, and both make listed vol the **harder** benchmark to
# look cheap against — which is the conservative direction for the question being
# asked below.

# %%
UNITS_VERDICT = {
    "pass": True,
    "check_1a_vs_swaptions": {
        "n_matched_pairs": int(len(_matched)),
        "ratio_range": [float(_matched.ratio.min()), float(_matched.ratio.max())],
        "r_level_range": [float(_matched.r_level.min()), float(_matched.r_level.max())],
        "r_change_range": [float(_matched.r_change.min()), float(_matched.r_change.max())],
    },
    "check_1b_dv01": {
        "long_end_ratio_range": [float(_long.ratio.min()), float(_long.ratio.max())],
        "all_roots_ratio": {r: float(v) for r, v in
                            UNITS_B[UNITS_B.cm_days == 30].set_index("root")["ratio"].items()},
        "ctd_reprice_median_err_pts": float(_err.median()),
    },
    "check_1b_price_free": {
        "implied_vs_measured_duration": {
            r: [float(a), float(b)] for r, a, b in zip(
                IMPL_DUR.root, IMPL_DUR.implied_mod_duration,
                IMPL_DUR.measured_from_basis_store)},
    },
    "residual": ("listed UST vol runs 4-13% above matched swaption vol; sign is "
                 "consistent with (a) Treasury-vs-swap yield vol and (b) the "
                 "delivery/CTD switch option inside the futures option. Makes "
                 "listed the HARDER benchmark, not the easier one."),
}
print(json.dumps(UNITS_VERDICT, indent=1))

# %% [markdown]
# ## 6. SECTOR MATCHING — by measured CTD, not by contract name
#
# A contract's *name* is a poor guide to what rate its option prices. Measured
# from the offline basis store over 2019-01-01 onward:
#
# | root | contract | CTD maturity | CTD ModDur | swap point it prices |
# |---|---|---|---|---|
# | TU | 2y note | 1.94 yrs | 1.85 | 2Y |
# | FV | 5y note | 4.39 yrs | 4.01 | 5Y |
# | TY | 10y note | 6.80 yrs | 5.85 | **7Y** |
# | TN | Ultra 10y | 9.61 yrs | 8.12 | 10Y |
# | US | **"30y bond"** | **15.86 yrs** | 11.58 | **15-20Y** |
# | UL | Ultra Bond | 25.59 yrs | 17.14 | 25-30Y |
#
# So the "30-year bond" contract is a vol quote on a **~16-year** Treasury yield.
# The primary benchmark for 30Y/50Y is the **Ultra Bond**, and `US` is the alt.
#
# `TY` (CTD 6.8 yrs) is carried on every structure as the **control that should
# score worse**. Its purpose is to make one specific failure visible: if a
# 7-year benchmark ranks a 30s/50s structure as well as a 30-year one, the
# comparison is not measuring sector.

# %%
_ctdw = CTD[(CTD.root.isin(lv.UST_CM_ROOTS)) & (CTD.date >= pd.Timestamp(NB.start))].copy()
_prof = pd.DataFrame([{"root": r, **v} for r, v in lv.UST_CTD_PROFILE.items()])
_meas2 = _ctdw.groupby("root").agg(n=("ctd_mod_duration", "size"),
                                   moddur_measured=("ctd_mod_duration", "median"))
print(_prof.merge(_meas2, on="root").round(3).to_string(index=False))

print("\nsector map (listed_vol.UST_SECTOR_MAP):")
for lab, _, _ in CFG.longend_structures:
    b = lv.ust_benchmarks_for(lab)
    print(f"  {lab:<18} primary={b['primary']:<3} alt={b['alt']:<3} control={b['control']:<3}")
    print(f"       {b['why']}")
assert lv.UST_SECTOR_MAP["30Y/50Y"]["primary"] == "UL", \
    "the 30Y benchmark must be the Ultra Bond, not the contract merely NAMED 30-year"
assert all(lv.ust_benchmarks_for(l)["control"] == "TY" for l, _, _ in CFG.longend_structures)

# %% [markdown]
# ## 7. TERM STRUCTURE — stated, not assumed
#
# The curve breakeven is a **1-year-horizon** number. The listed quotes are
# **30/60/90-day** constant maturity. Both sides are annualised and divided by
# √252, which removes the horizon to first order — but only exactly if the listed
# term structure is flat, and it is not. So the slope is measured here, and §12
# reports how far each structure's verdict actually moves across the three
# tenors rather than asserting that it does not.

# %%
TS = lv.ust_cm_term_structure(UST)
print(TS.round(4).to_string(index=False))

# The OTC term structure over the same tail, for scale: it runs the OTHER way.
_otc_ts = pd.DataFrame([{
    "node": f"{e}x30Y",
    "median_bp_yr": float(atmf_vol_series(OTC, e, "30Y").reindex(
        pd.DatetimeIndex(sorted(UST.date.unique()))).dropna().median()),
} for e in ("1M", "2M", "3M", "6M", "1Y")])
_otc_ts["bp_day"] = _otc_ts.median_bp_yr / math.sqrt(252.0)
_otc_ts["vs_1M_pct"] = 100 * (_otc_ts.median_bp_yr / _otc_ts.median_bp_yr.iloc[0] - 1)
print("\nOTC 30Y-tail term structure over the same dates:")
print(_otc_ts.round(4).to_string(index=False))

print(f"\nlisted 30->90d slope: US {TS.set_index('root').loc['US','slope_90_30_pct']:+.2f}%  "
      f"UL {TS.set_index('root').loc['UL','slope_90_30_pct']:+.2f}%  "
      f"TY {TS.set_index('root').loc['TY','slope_90_30_pct']:+.2f}%")
print(f"OTC 1M->1Y slope on the 30Y tail: {_otc_ts.vs_1M_pct.iloc[-1]:+.2f}%")
print("\nThe two slopes have OPPOSITE signs and are both single-digit percent, so "
      "extrapolating the listed CM points out to a 1-year expiry moves the "
      "benchmark by a few percent AT MOST — and upward, i.e. towards the curve "
      "looking cheaper still.")

# %%
fig = make_subplots(rows=1, cols=2, subplot_titles=(
    "Listed ABPV constant-maturity term structure (median, bp/day)",
    "US_30 / US_90 daily, bp/day"))
for r in ["UL", "US", "TN", "TY", "FV", "TU"]:
    _row = TS[TS.root == r]
    if _row.empty:
        continue
    fig.add_trace(go.Scatter(x=[30, 60, 90],
                             y=[float(_row[f"median_{c}_bp_day"].iloc[0]) for c in (30, 60, 90)],
                             mode="lines+markers", name=r), row=1, col=1)
_w = lv.ust_cm_wide(UST) / math.sqrt(252.0)
for s, c in (("US_30", "#2b6cb0"), ("US_90", "#c05621")):
    fig.add_trace(go.Scatter(x=_w.index, y=_w[s], name=s, line=dict(width=1, color=c)),
                  row=1, col=2)
fig.update_xaxes(title_text="constant maturity (days)", row=1, col=1)
fig.update_yaxes(title_text="bp/day", row=1, col=1)
fig.update_layout(height=420, template="plotly_white",
                  title="Term structure — the residual the bp/day bridge leaves behind")
fig.show()

# %% [markdown]
# ## 8. Sign probes — re-verified live, not inherited
#
# The whole study hangs on one convention:
#
# ```
# OUTRIGHT bpv > 0  =  PAYER
# CURVE    bpv < 0  =  FLATTENER (pay front, receive back)  =  LONG convexity
# signal +1 = curve is CHEAP gamma -> FLATTENER
# ```
#
# ### 8a. Leg level — a payer must gain when its own rate rises, and the two sides must mirror
#
# The test is written against the **measured** move in the 30Y rate over the
# probe window rather than against a remembered market narrative. 2022-09-13 was
# the CPI shock, which sold the front end off hard and *rallied* the 30Y — so a
# probe that asserted "a payer gains in September 2022" would fail for a reason
# that has nothing to do with the sign convention. Reading the rate change off
# the curve and asserting the P&L matches it in **sign and in magnitude** tests
# the convention itself, and additionally confirms the leg is struck to the DV01
# it was asked for.

# %%
def _run_sign_probe(bpv: float) -> float:
    dates = [datetime.date.fromisoformat(d) for d in NB.probe_dates]
    mdp = IRSwapsMDP(source="CITIVELO_EXCEL")
    grid = TimeGrid([pd.Timestamp(d) for d in dates])
    q = IRSwapQuery(structure=IRSwapStructure.OUTRIGHT, value=IRSwapValue.NPV,
                    tenor="30Y", curve=NB.curve, structure_kwargs={"bpv": bpv},
                    tags=("probe",))
    strat = QueryStrategy(name=f"sign_{bpv:+.0f}", triggers=[
        DateTrigger(DateTriggerRequirements(dates=[dates[0]]),
                    actions=[AddQueryAction(query=q, meta={"tags": ["probe"]})]),
        DateTrigger(DateTriggerRequirements(dates=[dates[-1]]),
                    actions=[UnwindPositionsAction(match_tag="probe", fee=0.0)]),
    ])
    bt = QueryDrivenBacktest(time_grid=grid, strategy=strat, mdp=mdp, show_progress=False)
    bt.run()
    # run() SWALLOWS exceptions -- an empty mtm_history is the only way a failed
    # engine run announces itself.
    assert bt.mtm_history, "engine produced no marks — run() swallows exceptions"
    return float(pd.Series(bt.mtm_history).iloc[-1])


def _rate_30y_bp(day: str) -> float:
    """Fair 30Y par swap rate on *day*, in bp — read off the curve itself."""
    _pr = IRSwapsMDP(source="CITIVELO_EXCEL").get_data(
        {"curve_name": NB.curve, "timestamp": datetime.date.fromisoformat(day)})
    _q = IRSwapQuery(structure=IRSwapStructure.OUTRIGHT, value=IRSwapValue.NPV,
                     tenor="30Y", curve=NB.curve,
                     structure_kwargs={"bpv": NB.package_dv01})
    _raw, _w = _q.resolve_package(pricer_or_curve=_pr)
    return float(_pr.fair_rate(_raw[0])) * 1e4


_r0, _r1 = _rate_30y_bp(NB.probe_dates[0]), _rate_30y_bp(NB.probe_dates[-1])
_d_rate_bp = _r1 - _r0
_plus, _minus = _run_sign_probe(+NB.package_dv01), _run_sign_probe(-NB.package_dv01)
print(f"30Y rate {NB.probe_dates[0]} {_r0:.2f} bp -> {NB.probe_dates[-1]} {_r1:.2f} bp"
      f"   move {_d_rate_bp:+.2f} bp")
# |pv01| is package_dv01 CURRENCY PER BP, so the first-order P&L of a bpv>0 leg
# is simply (rate move in bp) x package_dv01. The residual is 3 days of carry
# plus convexity.
_expected = _d_rate_bp * NB.package_dv01
print(f"+bpv {_plus:+,.0f}   -bpv {_minus:+,.0f}   expected ~ {_expected:+,.0f}"
      f"   residual {100 * (_plus - _expected) / abs(_expected):+.1f}% (carry + convexity)")
assert _plus * _d_rate_bp > 0, \
    "a bpv>0 leg must make money in the direction its own rate moved"
assert abs(_plus - _expected) < 0.15 * abs(_expected), \
    "P&L magnitude must match rate move x DV01 (carry/2nd-order aside)"
assert abs(_plus + _minus) < 1e-6 * abs(_plus), "buy/sell must mirror — seam regressed?"
print("SIGN TEST PASS: mirror exact, P&L tracks the measured rate move in sign and "
      "size  =>  OUTRIGHT bpv>0 is a PAYER")

# %% [markdown]
# ### 8b. Package level, on the actual long-end structure
#
# The outright probe pins leg direction; this pins the *package* direction and
# DV01 neutrality, which is what the strategy trades — and it does it on
# `30Y/50Y`, the headline structure, not a proxy.

# %%
_mdp = IRSwapsMDP(source="CITIVELO_EXCEL")
_probe = _mdp.get_data({"curve_name": NB.curve, "timestamp": datetime.date(2022, 9, 13)})
_raw_f, _w_f, _flat = s1.resolve_package(_probe, "30Y", "50Y",
                                         package_dv01=NB.package_dv01,
                                         direction=s1.FLATTENER, curve=NB.curve)
_raw_s, _w_s, _steep = s1.resolve_package(_probe, "30Y", "50Y",
                                          package_dv01=NB.package_dv01,
                                          direction=s1.STEEPENER, curve=NB.curve)
for _nm, _pkg, _w in (("flattener", _flat, _w_f), ("steepener", _steep, _w_s)):
    print(f"{_nm:10s} rw={_w}")
    for _s in _pkg:
        print(f"   eff {_probe.effective_date(_s).date()} mat {_probe.maturity_date(_s).date()} "
              f"N {_probe.notional(_s):+,.0f}  pv01 {_probe.pv01(_s):+,.1f}")
assert _w_f == [1.0, -1.0] and _w_s == [-1.0, 1.0]
for _a, _b in zip(_flat, _steep):
    assert abs(abs(_probe.pv01(_a)) - NB.package_dv01) < 1e-6 * NB.package_dv01
    assert abs(_probe.notional(_a) + _probe.notional(_b)) < 1e-6 * abs(_probe.notional(_a))
assert abs(sum(_probe.pv01(_s) for _s in _flat)) < 1e-3 * NB.package_dv01
print("PACKAGE SIGN TEST PASS: DV01-neutral, directions mirror exactly")

# %%
# And the flattener must be LONG convexity: the payoff profile is convex.
_prof = s1.structure_profile(_probe, "30Y/50Y", "30Y", "50Y",
                             CFG.longend_curve_config(), direction=s1.FLATTENER)
print(pd.DataFrame({"shift_bp": _prof.shifts_bp, "payoff_bp": _prof.payoff_bp,
                    "convexity_bp": _prof.convexity_bp}).round(4).to_string(index=False))
assert s1.is_convex(_prof.shifts_bp, _prof.convexity_ccy), \
    "CURVE bpv<0 must be the LONG-convexity side"
print("\nCONVEXITY SIGN PASS: CURVE bpv<0 = FLATTENER = LONG convexity")

# %% [markdown]
# ## 9. TIE-OUT — the payoff-profile regression table
#
# The curve side of this study is **reused** from `strat1_signal_panel.parquet`
# rather than recomputed. That is a deliberate choice, not a shortcut: strategy
# 1's breakeven and this study's breakeven must be the *same number*, and
# re-deriving it would create a second one that could disagree for reasons having
# nothing to do with the listed benchmark.
#
# The licence for that reuse is this cell. It rebuilds the package from the live
# curve on eight dates spread across the sample, reprices it across the ±250 bp
# grid, re-solves the breakeven, and asserts every payoff point, the carry and
# the breakeven status match the stored row.
#
# The dates are chosen to hit **every breakeven branch** — `root`,
# `always_cheap` and `never_cheap` — because a regression that only ever sees one
# branch does not test the two that carry this study's headline.

# %%
S1 = pd.read_parquet(DATA / NB.strat1_panel)
print("stored strat1 panel", S1.shape)
_t0 = time.time()
REG = sl.longend_curve_regression(_mdp, S1, CFG, [pd.Timestamp(d) for d in NB.regression_dates])
print(f"rebuilt {len(REG)} (date, structure) profiles in {time.time() - _t0:.0f}s\n")
print(REG.round(10).to_string(index=False))

# %%
assert len(REG) == len(NB.regression_dates) * len(CFG.longend_structures), \
    "regression did not cover every date x structure"
assert (REG.n_shifts_compared == len(CFG.longend_shifts_bp)).all()
assert REG.max_payoff_diff_bp.max() == 0.0, \
    f"payoff profile does not reproduce: max diff {REG.max_payoff_diff_bp.max()}"
assert REG.carry_diff_bp.max() == 0.0
assert REG.breakeven_diff_bp_day.max() == 0.0
assert REG.status_match.all()
assert set(REG.status_rebuilt) >= {"root", "always_cheap", "never_cheap"}, \
    "the regression must exercise all three breakeven branches"
print(f"REGRESSION PASS — {len(REG)} profiles rebuilt from the live curve, "
      f"max payoff diff {REG.max_payoff_diff_bp.max():.1e} bp, "
      f"max carry diff {REG.carry_diff_bp.max():.1e} bp, all statuses match.\n"
      f"branches exercised: {sorted(set(REG.status_rebuilt))}\n"
      "=> reusing strat1_signal_panel.parquet is EXACT, not approximate.")

# %% [markdown]
# ## 10. THE RUN — strat1-listed on the long end, full 2019-01 .. 2026-08
#
# One row per (date, structure, benchmark), where a benchmark is a
# (root, constant maturity) pair from the sector map — so the primary, the alt
# and the deliberately-mismatched control appear side by side and the reader
# cannot see one without the others.
#
# Both comparisons come off the **same** curve breakeven on every row, which is
# the single most likely way a "listed vs OTC" study fools itself.

# %%
_t0 = time.time()
PANEL = sl.build_longend_listed_panel(S1, UST, CFG)
print(f"panel {PANEL.shape}  ({time.time() - _t0:.0f}s)")
print("index:", PANEL.index.names)
print("\nrows per structure x benchmark:")
print(PANEL.reset_index().groupby(["structure", "listed_symbol"]).size().unstack(fill_value=0).to_string())
PANEL.reset_index().to_parquet(DATA / "strat1_listed_longend_panel.parquet", index=False)

# %%
DIST = sl.longend_signal_distribution(PANEL)
_show = ["structure", "listed_symbol", "listed_role", "listed_swap_point", "n_days",
         "first", "last", "frac_cheap_vs_listed", "frac_cheap_vs_otc",
         "frac_always_cheap", "frac_never_cheap", "median_breakeven_bp_day",
         "median_listed_bp_day", "median_otc_bp_day",
         "median_gap_vs_listed_bp_day", "median_gap_vs_otc_bp_day",
         "median_otc_minus_listed_bp_day", "frac_signals_disagree"]
print(DIST[_show].round(4).to_string(index=False))
DIST.to_csv(DATA / "strat1_listed_longend_distribution.csv", index=False)

# %% [markdown]
# ### 10b. The headline — cheap-share against listed, next to the swaption number

# %%
_head = (DIST[DIST.listed_cm_days == 30]
         .pivot_table(index="structure", columns="listed_symbol",
                      values="frac_cheap_vs_listed"))
_head["SWAPTION_1Yx30Y"] = DIST.groupby("structure")["frac_cheap_vs_otc"].max()
print("fraction of days the curve is CHEAP gamma, by benchmark (30d CM):")
print(_head.round(4).to_string())

_lev = (DIST[DIST.listed_cm_days == 30]
        .pivot_table(index="structure", columns="listed_symbol", values="median_listed_bp_day"))
_lev["SWAPTION_1Yx30Y"] = DIST.groupby("structure")["median_otc_bp_day"].median()
_lev["curve_breakeven"] = DIST[DIST.listed_cm_days == 30].groupby(
    "structure")["median_breakeven_bp_day"].median()
print("\nmedian vol level, bp/day (what the cheap-share is comparing):")
print(_lev.round(4).to_string())

# %%
fig = make_subplots(rows=2, cols=2, vertical_spacing=0.16, horizontal_spacing=0.09,
                    subplot_titles=[lab for lab, _, _ in CFG.longend_structures])
_pos = {lab: (i // 2 + 1, i % 2 + 1) for i, (lab, _, _) in enumerate(CFG.longend_structures)}
_col = {"UL": "#2b6cb0", "US": "#2f855a", "TN": "#805ad5", "TY": "#c05621"}
_pr = PANEL.reset_index()
for lab, _, _ in CFG.longend_structures:
    r, c = _pos[lab]
    g = _pr[(_pr.structure == lab) & (_pr.listed_cm_days == 30)]
    _be = g.drop_duplicates("date").set_index("date")["breakeven_vol_bp_day"].replace(
        [np.inf, -np.inf], np.nan)
    fig.add_trace(go.Scatter(x=_be.index, y=_be, name="curve breakeven",
                             line=dict(color="#1a202c", width=1.2),
                             showlegend=(lab == CFG.longend_structures[0][0])), row=r, col=c)
    for root in sorted(g.listed_root.unique()):
        h = g[g.listed_root == root].set_index("date")["listed_atm_bp_day"]
        fig.add_trace(go.Scatter(x=h.index, y=h, name=f"listed {root}_30",
                                 line=dict(color=_col.get(root, "#888"), width=1),
                                 showlegend=(lab == CFG.longend_structures[0][0])), row=r, col=c)
    _o = g.drop_duplicates("date").set_index("date")["otc_atmf_bp_day"]
    fig.add_trace(go.Scatter(x=_o.index, y=_o, name="1Yx30Y swaption",
                             line=dict(color="#e53e3e", width=1, dash="dot"),
                             showlegend=(lab == CFG.longend_structures[0][0])), row=r, col=c)
    fig.update_yaxes(title_text="bp/day" if c == 1 else None, row=r, col=c)
fig.update_layout(height=760, template="plotly_white",
                  title="Curve breakeven vs listed UST vol vs 1Yx30Y swaptions — "
                        "below the benchmark = curve is CHEAP gamma")
fig.show()

# %% [markdown]
# ## 11. Is the control doing its job? Benchmark separation
#
# `TY` (CTD 6.8 yrs) is the deliberate mismatch. The naive test — "does the
# control give a different cheap/rich verdict?" — **cannot fail here**, and that
# is worth stating rather than hiding: on the three forward structures the
# cheap-share is 1.00 against *every* benchmark, so a 0.00 difference is
# saturation, not evidence that the control is a good match.
#
# So the separation is measured where it can actually appear: in the benchmark
# **levels**, in the size of the cheapness **gap**, and in the correlation of the
# two roots' **daily changes**.

# %%
SEP = sl.longend_benchmark_separation(PANEL)
print(SEP.round(4).to_string(index=False))

_s30 = SEP[SEP.listed_cm_days == 30]
print(f"\nlevel separation primary-vs-control, 30d CM: "
      f"{_s30.level_diff_bp_day.min():+.3f} to {_s30.level_diff_bp_day.max():+.3f} bp/day")
print(f"daily-change correlation primary vs control: "
      f"{_s30.r_change.min():.3f}-{_s30.r_change.max():.3f}")
assert (_s30.r_change < 0.98).all(), "primary and control must not be the same series"
print("\nREADING: the control's level is systematically HIGHER (a 7-year Treasury "
      "yield is more volatile than a 25-year one), which is the sector signal. "
      "The cheap-share difference is ~0 because the verdict is saturated — that "
      "is a property of the result, not a defect in the control.")

# %% [markdown]
# ## 12. Term-structure effect — where does 30 vs 60 vs 90 change the answer?
#
# Step 3 of the brief, answered rather than asserted.

# %%
TSE = sl.longend_term_structure_effect(PANEL)
print(TSE.round(4).to_string(index=False))
print(f"\nmax cheap-share spread across 30/60/90d: {TSE.cheap_share_spread.max():.4f}")
_moved = TSE[TSE.cheap_share_spread > 0.005]
if len(_moved):
    print("\nstructures where the constant maturity MATERIALLY moves the verdict:")
    print(_moved[["structure", "listed_root", "cheap_share_30", "cheap_share_60",
                  "cheap_share_90", "cheap_share_spread"]].round(4).to_string(index=False))
else:
    print("\nno structure's verdict moves by more than 0.5pp across the term structure.")
print("\nSTATED: on the three forward structures the verdict is saturated and the "
      "slope cannot move it at all. On 5Y/30Y — the only unsaturated structure — "
      f"the cheap-share moves by up to {_moved.cheap_share_spread.max() if len(_moved) else 0:.3f} "
      "across 30->90d, always in the direction of MORE cheap, because the listed "
      "term structure is upward-sloping.")

# %% [markdown]
# ## 13. The vol basis — was the swaption the expensive comparison?
#
# `otc_minus_listed_bp_day` = 1Yx30Y swaption vol − listed vol, in bp/day.
# **Positive** means swaptions price more vol than the exchange (the hypothesis
# under test). **Negative** means the opposite.

# %%
BASIS = sl.longend_vol_basis(PANEL)
print(BASIS.describe().round(4).to_string())
BASIS.to_parquet(DATA / "strat1_listed_longend_basis.parquet")

_bs = pd.DataFrame({
    "median_bp_day": BASIS.drop(columns=["otc_atmf_bp_day"]).median(),
    "frac_days_otc_richer": (BASIS.drop(columns=["otc_atmf_bp_day"]) > 0).mean(),
    "n": BASIS.drop(columns=["otc_atmf_bp_day"]).notna().sum(),
}).sort_values("median_bp_day")
print("\nOTC minus listed, per benchmark:")
print(_bs.round(4).to_string())

# %%
fig = go.Figure()
for s in ["UL_30", "US_30", "TN_30", "TY_30"]:
    if s in BASIS.columns:
        fig.add_trace(go.Scatter(x=BASIS.index, y=BASIS[s], name=f"1Yx30Y − {s}",
                                 line=dict(width=1, color=_col.get(s.split('_')[0], "#888"))))
fig.add_hline(y=0.0, line=dict(color="#1a202c", width=1, dash="dash"))
fig.update_layout(height=420, template="plotly_white",
                  yaxis_title="bp/day",
                  title="Swaption minus listed vol basis — above zero = swaptions "
                        "were the expensive comparison")
fig.show()

# %% [markdown]
# ## 14. VERDICT

# %%
_head30 = DIST[DIST.listed_cm_days == 30]
VERDICT = {
    "question": ("Strat 1's long-end flatteners were cheap vs 1Yx30Y swaptions on "
                 "100% of days. Does that survive a LISTED benchmark, or were "
                 "swaptions simply the expensive comparison?"),
    "window": [str(NB.start), str(NB.end)],
    "units_check": UNITS_VERDICT,
    "curve_side_reused_exactly": {
        "profiles_rebuilt": int(len(REG)),
        "max_payoff_diff_bp": float(REG.max_payoff_diff_bp.max()),
        "max_carry_diff_bp": float(REG.carry_diff_bp.max()),
        "branches": sorted(set(REG.status_rebuilt)),
    },
    "cheap_share": {
        lab: {
            "vs_listed": {r.listed_symbol: round(float(r.frac_cheap_vs_listed), 4)
                          for r in _head30[_head30.structure == lab].itertuples()},
            "vs_swaption_1Yx30Y": round(float(
                _head30[_head30.structure == lab].frac_cheap_vs_otc.max()), 4),
        } for lab, _, _ in CFG.longend_structures},
    "median_vol_bp_day": {
        lab: {
            **{r.listed_symbol: round(float(r.median_listed_bp_day), 4)
               for r in _head30[_head30.structure == lab].itertuples()},
            "SWAPTION_1Yx30Y": round(float(
                _head30[_head30.structure == lab].median_otc_bp_day.median()), 4),
            "curve_breakeven": round(float(
                _head30[_head30.structure == lab].median_breakeven_bp_day.median()), 4),
        } for lab, _, _ in CFG.longend_structures},
    "otc_minus_listed_bp_day_median": {k: round(float(v), 4)
                                       for k, v in _bs.median_bp_day.items()},
    "term_structure_max_cheap_share_spread": float(TSE.cheap_share_spread.max()),
    "listed_slope_30_to_90_pct": {r: round(float(v), 3) for r, v in
                                  TS.set_index("root")["slope_90_30_pct"].items()},
}
(DATA / "strat1_listed_longend_verdict.json").write_text(json.dumps(VERDICT, indent=1),
                                                         encoding="utf-8")
print(json.dumps(VERDICT, indent=1))

# %% [markdown]
# ## 15. The one-sentence answer
#
# *(printed from the measured numbers below, not typed)*

# %%
_fwd = ["30Y/50Y", "20Yx5Y/25Yx5Y", "10Yx10Y/20Yx10Y"]
_fwd_listed = _head30[_head30.structure.isin(_fwd)].frac_cheap_vs_listed
_fwd_otc = _head30[_head30.structure.isin(_fwd)].frac_cheap_vs_otc
_basis_med = float(_bs.median_bp_day.median())

print(f"""
ANSWER
------
The 100%-of-days cheap verdict SURVIVES the listed benchmark: across the three
long-end forward structures the curve is cheap gamma on
{_fwd_listed.min():.1%}-{_fwd_listed.max():.1%} of days against every listed UST
benchmark and every constant maturity, identical to the
{_fwd_otc.min():.1%}-{_fwd_otc.max():.1%} it scored against 1Yx30Y swaptions --
and swaptions were NOT the expensive comparison, they were the CHEAP one: listed
UST vol prices a median {abs(_basis_med):.2f} bp/day MORE than 1Yx30Y swaptions
(otc_minus_listed median {_basis_med:+.3f} bp/day), so replacing the OTC
benchmark with the exchange makes the curve look cheaper, not richer.
""")

assert (_fwd_listed > 0.99).all(), "headline claim must match the measured panel"
assert _basis_med < 0, "the basis sign is the crux of the answer — check it"

# %% [markdown]
# ### What this does and does not establish
#
# **Does.** The 100% is not an artifact of the swaption benchmark. Two structurally
# different vol markets — OTC swaptions and CME bond-future options — both price
# more volatility than the long-end curve's carry implies, on essentially every
# day of a 7½-year sample, and the listed one prices *more* of it than the OTC one.
#
# **Does not.** The cheap-share is **saturated**, and a saturated statistic is
# weak evidence about a benchmark. On 30Y/50Y the breakeven is `always_cheap` on
# 86% of days — the package carries *positively*, so it is cheap against any
# vol whatsoever and the comparison never binds. The informative quantities on
# these structures are the *gap* and the *basis*, not the share, and §10-§13
# report those. `5Y/30Y` is the only structure in the universe whose verdict is
# not saturated, which is why it is carried despite not being one of the note's
# forward structures.
#
# **Not tested here.** Whether the cheapness is *harvestable*. Cohort P&L is not
# re-run: on the three saturated structures the listed signal equals the swaption
# signal on ~100% of days, so the cohorts would be identical by construction to
# strategy 1's own — see `strat1_equity_*.parquet` and
# `strat1_curve_gamma_backtest.ipynb`. Nothing here is a Sharpe ratio, and the
# 1-year overlapping cohorts in that study contain ~7.6 independent years.
