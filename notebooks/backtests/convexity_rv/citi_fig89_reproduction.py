# %% [markdown]
# # Citi Vol Lab Figures 8 & 9, reproduced on 2021-01 .. 2026-08
#
# Citi Research, *US Rates Vol Lab*, 17 Jan 2017, p.5:
#
# > **Figure 8. 3y1y implied vol is highly directional with the 2s5s10s fly…**
# > `180 normals 3y1y implied vol`
# > `scaled 2s5s10s fly: 59.7+60.5*(-0.71*2y+5y-0.18*10y)`
# >
# > **Figure 9. … implying that convexity can be hedged with the fly**
# > `20 bp Blues Cvx Adj`
# > `scaled 2s5s10s fly: 10.2+21.4*(-0.73*2y+5y-0.47*10y)`
#
# and the argument the two charts carry (p.5, lines 255–260):
#
# > "3y1y vol is mostly driven by expectations of monetary policy, and therefore
# > should be directional with the valuations of 5s on the curve. Indeed, the
# > 3y1y vol has been historically highly correlated with the 2s5s10s fly with
# > DV01 weights shown in Figure 8 (**the correlation in levels being 90%**). …
# > we regressed Blues CA on 2y, 5y and 10y swap rates. … the fitted value
# > effectively being a 2s5s10s fly with **-0.73/1/-0.47 DV01 weights** (Figure
# > 9). The CA is about 4bp or 2.5 sigmas wide to the fly … **selling the
# > 2s5s10s fly as a hedge has the advantage of positive carry**."
#
# Three deliverables: Figure 8, Figure 9, and — new — the convexity adjustment
# against its **Ho-Lee model level as a timeseries**, per pack colour, with the
# dislocation `vs_model_bp` as its own panel because that is the tradeable
# quantity.
#
# ## The five findings, up front
#
# 1. **Citi's 90% does not reproduce — and what replaces it is not a weaker
#    relationship but an unstable one.** Over the full window with Citi's own
#    published weights, `corr(3y1y ATMF normal vol, scaled fly)` in levels is
#    **−0.61** (n = 1,403) and `corr(Blues CA, scaled fly)` is **−0.33**
#    (n = 607), against the stated **+0.90**. But by calendar year Fig 8 runs
#    **+0.91 / −0.59 / +0.68 / −0.52 / +0.37 / −0.23** (2021…2026) and Fig 9
#    **+0.68 / −0.67 / +0.07 / −0.01**. It held in 2021, broke in 2022 and has
#    flipped sign every year since. The negative full-sample number is that
#    instability plus a level mismatch across the hiking cycle, not a stable
#    inverse relationship you could trade the other way.
#
# 2. **Refitting recovers explanatory power but not a butterfly.** Fig 8 refit on
#    2021–26 gives R² 0.80 and a levels correlation of **+0.89 — essentially
#    Citi's 0.90** — but with weights **0.009 / 1 / 0.956**: the 2y wing has
#    vanished and the structure is a 5s10s spread wearing a fly's name. So a
#    three-rate combination *can* still track 3y1y vol; the specific butterfly
#    Citi specifies cannot. Fig 9 refit gives R² 0.45, weights
#    **0.113 / 1 / 0.663**, and **β = 5.7 against Citi's 21.4**: the Blues CA now
#    moves a quarter as much per unit of fly, so a hedge sized off the 2017 β is
#    ~4× too large.
#
# 3. **Blues coverage is the binding constraint, and as of 2026-08-19 it is
#    partly a repaired defect and partly a real absence.** The coverage table in
#    cell 2 is measured on every run — read it there, not from this paragraph.
#    What changed: the CA panel this notebook reads was rebuilt after
#    `strat2_q20.strip_depth_by_date` was found to discard a whole date whenever
#    its DEFERRED end was cold, and after a 103-date SR3 settle warm
#    (`scripts/warm_sr3_deferred.py`). Blues still needs a contiguous
#    16-contract SR3 strip and Golds needs 20, so wherever the local store stops
#    supplying one the series stops — **and that is now drawn as a hole rather
#    than bridged.** The gap table printed in cell 2 lists every hole with its
#    span; see `notebooks/backtests/convexity_rv/ca_coverage_repair.ipynb` and
#    `docs/convexityrv/ca_coverage_diagnosis.md` Part II.
#
# 4. **The CA level ties out to Citi; the model level does not, by construction.**
#    On 2023-06-09 our 13 CA rows reproduce Citi's Figure 58 at corr **0.966**
#    (Blues 15.72 vs 15.40). The *model* column is systematically higher
#    (+1.5bp at Reds to +7.8bp at Golds) because this repo fits σ to the day's
#    own CA term structure while Citi calibrates it to cap/floor vols. So
#    `vs_model_bp` here is a **cross-sectional** dislocation — this pack against
#    the smooth curve through all of them — not a vol-market one, and it is
#    centred near zero rather than at Citi's +5.4bp.
#
# 5. **Verdict: "convexity can be hedged with the fly" does not survive on
#    2021–26 data.** With Citi's own coefficients the hedge is anti-correlated in
#    levels and uncorrelated in changes. This is consistent with what this
#    codebase already measured on the near packs (2s5s10s hedge R² 0.000–0.010,
#    sign-flipping β), and section 9 quantifies it as a variance-reduction test.

# %%
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import dataclasses
import datetime
import json
import pathlib
import sys
import time

import numpy as np
import pandas as pd

_REPO = (pathlib.Path(__file__).resolve().parents[3] if "__file__" in dir()
         else pathlib.Path.cwd().parents[2])
sys.path.insert(0, str(_REPO))

import plotly.graph_objects as go
import plotly.io as pio

pio.renderers.default = "plotly_mimetype+notebook_connected"

import RVUtils.ConvexityRV.ca_plots as CAP
import RVUtils.ConvexityRV.citi_fig89 as CF
from RVUtils.ConvexityRV.strat2_q20 import CITI_SOFR_20230609

DATA = _REPO / "notebooks" / "data" / "convexity_rv"
DATA.mkdir(parents=True, exist_ok=True)
pd.set_option("display.width", 220)

# %% [markdown]
# ## 1. CONFIG — every knob, and why it is set where it is

# %%
@dataclasses.dataclass(frozen=True)
class Fig89Config:
    """Everything this notebook chooses over and above the module defaults."""

    # ---- window ------------------------------------------------------------
    start: datetime.date = datetime.date(2021, 1, 1)
    end: datetime.date = datetime.date(2026, 8, 31)
    """The REQUESTED window. Every series reports its own effective span, which
    differs: the swap curve store runs to 2026-08-24, the swaption cube to
    2026-08-15, and the Q20 CA panel to 2026-07-27."""

    # ---- the published coefficients ----------------------------------------
    # Frozen in RVUtils.ConvexityRV.citi_fig89 as CITI_FIG8 / CITI_FIG9 /
    # CITI_TI_FEB9. Repeated here only so the notebook's config is complete:
    #   Fig 8  3y1y implied vol :  59.7 + 60.5 * (-0.71*2y + 5y - 0.18*10y)
    #   Fig 9  Blues Cvx Adj    :  10.2 + 21.4 * (-0.73*2y + 5y - 0.47*10y)
    #   TI Fig 6 (9-Feb-2017)   :   9.7 + 20.6 * (-0.705*2y + 5y - 0.465*10y)
    refit: bool = True
    """Produce the re-estimated version alongside the published one. Citi
    re-estimates at every publication (0.73/0.47/21.4 on 13-Jan became
    0.705/0.465/20.6 on 9-Feb — 27 days), so the printed constants are one
    sample of a procedure, and the gap between published and refitted is a
    RESULT, not an error."""

    # ---- the vol node ------------------------------------------------------
    vol_expiry: str = "3Y"
    vol_tenor: str = "1Y"
    """Citi's Fig-8 left-hand series. ATMF = ``offset_bp == 0``, NORMAL vol in
    bp — the "normals" the chart's axis is labelled with."""

    # ---- the pack ----------------------------------------------------------
    colour: str = "Blues"
    """Fig 9's left-hand series. In the 2017 ED note "Blues" is the 4th ED pack,
    contracts 13–16 (on 1/12/17: H0-Z0). Here it is the SOFR rank-13 pack
    window — contracts 13..16 of the quarterly SR3 strip, first expiry ≈3.25y.
    Same position on the curve, different underlying."""

    extra_colours: tuple = ("Greens", "Golds")
    """Chart 3 adds these where the strip reaches. Greens = rank 9 (needs a
    12-contract strip, best coverage), Golds = rank 17 (needs 20, worst)."""

    ca_rank_start: int = 5
    ca_n_packs: int = 13
    """The cross-section the Ho-Lee σ is fitted over. 5..17 is EXACTLY Citi's
    published SOFR screen (Figure 58, 12-Jun-2023: Reds M4-H5 .. Golds M7-H8).
    Dates whose strip is shallower contribute fewer rows to that day's fit; they
    are not dropped."""

    ca_col: str = "ca_bp_q20"
    """Which futures rate the CA is computed off. ``q20`` = the Q20 STIR curve's
    IMM×IMM forward (the screen's number); ``ca_bp_settle`` = raw SR3 settles
    (the control). On gate-passed deep rows the two agree to a median 0.057bp,
    so this choice is immaterial and is asserted in section 4."""

    gate: bool = True
    """Apply ``strat2_q20.apply_gate`` BEFORE the σ fit. The fit is a least
    squares across the day's ranked packs, so one inadmissible row moves every
    other pack's model value that day; filtering afterwards would leave
    contaminated numbers on rows that passed."""

    # ---- statistics --------------------------------------------------------
    roll_window: int = 126
    """Business days in the rolling correlation. ≈6 months. Exists so a
    relationship that DECAYS is visible instead of averaged away."""

    roll_min_periods: int = 63

    # ---- tolerances used only by this notebook's asserts -------------------
    fly_identity_tol: float = 1e-12
    """The fly recomputed from the TB panel must equal ``-w2*r2 + r5 - w10*r10``
    to here. It is an identity, so the tolerance is machine noise."""

    ti_feb9_tol_bp: float = 0.5
    """[TI-FEB9] says "about 3bp"; half a bp either side."""

    citi_tieout_max_abs_bp: float = 3.5
    """Per-row |ours − Citi| on the 2023-06-09 CA column. The published deep-pack
    tie-out on this date measured max 3.06bp; this is that with headroom, not a
    target."""

    citi_tieout_min_corr: float = 0.95


CFG = Fig89Config()
print(f"window requested      {CFG.start} .. {CFG.end}")
print(f"Fig 8 published       {CF.CITI_FIG8.annotation()}")
print(f"Fig 9 published       {CF.CITI_FIG9.annotation()}")
print(f"TI Fig 6 (9-Feb-2017) {CF.CITI_TI_FEB9.annotation()}")
print(f"vol node              {CFG.vol_expiry}x{CFG.vol_tenor} ATMF normal (bp)")
print(f"pack                  {CFG.colour} = SOFR rank {CF.COLOUR_RANK[CFG.colour]} "
      f"(contracts {CF.COLOUR_RANK[CFG.colour]}..{CF.COLOUR_RANK[CFG.colour] + 3})")

# %% [markdown]
# ## 2. The three data paths, and which one was chosen where
#
# ### 2a. 2y / 5y / 10y par swap rates — `TimeseriesBuilder` + `IRSwapsTB`
#
# The house call shape, `UnifiedQuery(value=IRS_RATE)` on `USD-SOFR-1D` off
# `IRSwapsMDP(source="CITIVELO_EXCEL")`, routed through
# `routers={"IRS": IRSwapsTB(curve_mdp)}` with `ignore_cache_miss=True`.
#
# **One measured deviation from the brief's example call: `freq` is left unset.**
# `freq="nyc_eod"` builds tz-aware 17:00 New York reference points, and the local
# CITIVELO store is keyed by plain date — it logs *"CITIVELO_EXCEL: no curve for
# 12 of 12 requested point(s) on 'USD-SOFR-1D'"* and returns an **empty frame**.
# The default (`pd.bdate_range`) resolves every date. Section 4 asserts the
# result against the independently built `strat2_q20_rates.parquet`.
#
# The fly is built as an explicit weighted combination of three par rates — which
# is exactly what Citi's annotation specifies — not via
# `IRSwapQuery(structure=FLY)`, which hard-codes a −1/2/−1 shape *and* mutates
# the `risk_weights` list it is handed.

# %%
_t = time.time()
RATES = CF.load_rate_panel(CFG.start, CFG.end,
                           cache_path=DATA / "citi_fig89_rates.parquet")
print(f"rates {RATES.shape}  {RATES.index.min().date()} .. {RATES.index.max().date()}"
      f"  ({time.time() - _t:.1f}s)")
print(RATES.describe().round(3).to_string())

# %% [markdown]
# ### 2b. 3y1y implied vol — the swaption cube store, **not** `IRSwaptionsTB`
#
# `IRSwaptionsTB` *does* serve this node offline. It is simply unusable at this
# horizon, and both halves of that were measured on this machine rather than
# assumed:
#
# | path | 5 dates, 3Yx1Y ATMF NVOL | implied cost for 1,404 dates |
# |---|---|---|
# | `IRSwaptionsTB` (`CITIVELO-RL`, cold) | **633.3 s** = 126.7 s/date | **≈49 hours** |
# | `swaption_cube.load_vol_panel` | 52.6 s **for the whole store** (2,705 days) | one-off, then a parquet read |
#
# Its warmed value grid is 3Mx10Y / 1Yx10Y / 5Yx5Y
# (`scripts/citivelo_swaption_ts_warm.py::DEFAULT_SHORTHANDS`), so **3Yx1Y is not
# in it**, and an unwarmed date falls through to the Citi Velocity Excel add-in
# over COM — a network round trip this run is not allowed to make.
#
# The decisive point is that the two paths return the **same numbers**: the
# router builds a QuantLib cube from the same Citi Velocity store this reader
# opens directly, and on the five probe dates the ATMF values agree **exactly**.
# Those five measured values are hard-coded below and asserted in section 4.

# %%
#: Measured 2026-08-18, `IRSwaptionsTB(IRSwaptionMDP(source="CITIVELO-RL",
#: curve_source="CITIVELO_EXCEL"))`, query `3Yx1Y / ATMF / STRADDLE / NVOL`,
#: elapsed 633.3 s for these five dates. Excel COM entry point tripwired to
#: raise for the duration, and it did not fire.
IRSWAPTIONSTB_PROBE = {
    datetime.date(2022, 6, 13): 138.597,
    datetime.date(2022, 6, 14): 139.702,
    datetime.date(2022, 6, 15): 134.066,
    datetime.date(2022, 6, 16): 140.373,
    datetime.date(2022, 6, 17): 139.348,
}

_t = time.time()
VOL = CF.load_vol_3y1y(CFG.start, CFG.end, expiry=CFG.vol_expiry, tenor=CFG.vol_tenor,
                       cache_path=DATA / "citi_fig89_vol_cube_3Y1Y.parquet")
VOL.to_frame("vol_bp").to_parquet(DATA / "citi_fig89_vol_3y1y.parquet")
print(f"{CFG.vol_expiry}x{CFG.vol_tenor} ATMF normal vol: {len(VOL)} days  "
      f"{VOL.index.min().date()} .. {VOL.index.max().date()}  ({time.time() - _t:.1f}s)")
print(f"  min {VOL.min():.1f}bp  median {VOL.median():.1f}bp  max {VOL.max():.1f}bp")

# %% [markdown]
# ### 2c. The convexity adjustment and its model — the Q20 deep-pack panel
#
# `strat2_q20` is the only path in this repo that reaches Blues. The near-pack
# code stops at rank 10 and **Blues is ranks 13–16**. The panel
# (`strat2_q20_panel.parquet`, built offline by `scripts/strat2_q20_build.py`)
# carries the matched swap at **quarterly/quarterly**
# (`curve_ops.matched_forward_swap_rate`) — the `usd_irs` spec's annual default
# biases every CA by `0.375·r²`, up to 12bp, which is the same order as the
# signal.
#
# Gate first, then fit. Model via
# `strat2_sofr_convexity.model_timeseries(panel, deep_pack_config(5, 13))`.

# %%
_t = time.time()
PANEL, FIT = CF.load_ca_panel(
    DATA / "strat2_q20_panel.parquet",
    start=CFG.start, end=CFG.end,
    rank_start=CFG.ca_rank_start, n_packs=CFG.ca_n_packs,
    gated=CFG.gate, ca_col=CFG.ca_col,
)
FIT.to_parquet(DATA / "citi_fig89_ca_fit.parquet", index=False)
print(f"gated panel {PANEL.shape}, model fit {FIT.shape}  ({time.time() - _t:.1f}s)")

COLOURS = {}
for _c in (CFG.colour,) + tuple(CFG.extra_colours):
    _f = CF.colour_frame(FIT, _c)
    if len(_f):
        COLOURS[_c] = _f
BLUES = COLOURS[CFG.colour]

# %% [markdown]
# ### Coverage — measured, and reported before anything is plotted
#
# This is the binding constraint and it is a finding in its own right. A pack
# window at rank `r` needs a contiguous SR3 strip of `r+3` contracts on that
# date; the local store's contiguous depth collapses after 2022.

# %%
_cov_rows = []
for _c, _f in COLOURS.items():
    _y = _f.groupby(_f.index.year).size()
    _cov_rows.append({"colour": _c, "rank": CF.COLOUR_RANK[_c],
                      "strip_needed": CF.COLOUR_RANK[_c] + 3,
                      "n_days": len(_f), "first": _f.index.min().date(),
                      "last": _f.index.max().date(),
                      **{str(k): int(v) for k, v in _y.items()}})
COVERAGE = pd.DataFrame(_cov_rows).set_index("colour")
print("gate-passed pack-days by year, 2021-01 .. 2026-08:")
print(COVERAGE.fillna(0).to_string())

_bdays = pd.bdate_range(max(CFG.start, BLUES.index.min().date()),
                        min(CFG.end, RATES.index.max().date()))
print(f"\n{CFG.colour}: {len(BLUES)} gate-passed days out of {len(_bdays)} business days "
      f"in its own span = {100 * len(BLUES) / len(_bdays):.1f}%")
print(f"\n{CFG.colour} coverage: {CAP.coverage_note(BLUES['ca_bp'])}")
_gaps = CAP.gap_table(BLUES.index)
if len(_gaps):
    print(f"gaps longer than {CAP.GAP_DAYS} days in the {CFG.colour} series:")
    print(_gaps.to_string(index=False))
else:
    print(f"no gap longer than {CAP.GAP_DAYS} days in the {CFG.colour} series.")
print("\nEvery chart below reindexes onto the business-day grid FIRST and then "
      "sets connectgaps=False, so the holes above are drawn as holes.")
print("(This cell used to print the same claim while the charts drew straight "
      "lines across a 502-day hole: the frames are inner-joined, so they carried "
      "no NaN rows and the flag had nothing to break on. Audited on the rendered "
      "traces 2026-08-19 and fixed.)")

_ungated = CF.load_ca_panel(DATA / "strat2_q20_panel.parquet", start=CFG.start,
                            end=CFG.end, rank_start=CFG.ca_rank_start,
                            n_packs=CFG.ca_n_packs, gated=False, ca_col=CFG.ca_col)[1]
_ug = CF.colour_frame(_ungated, CFG.colour)
print(f"\ngate cost: {len(_ug)} {CFG.colour} rows exist ungated, {len(BLUES)} pass "
      f"({100 * len(BLUES) / len(_ug):.1f}%). The gate is NOT what kills the series "
      f"after 2023 — the SR3 strip depth is.")

COVERAGE.to_csv(DATA / "citi_fig89_coverage.csv")

# %% [markdown]
# ## 3. Aligned frames
#
# The cube index carries a Saturday echo (2026-08-15 repeats Friday's print), so
# every join is an **inner** join against the business-day rate panel and it
# drops naturally.

# %%
F8 = pd.DataFrame({"vol_bp": VOL}).join(RATES, how="inner").dropna()
F9 = BLUES[["ca_bp", "ca_model_bp", "vs_model_bp"]].join(RATES, how="inner").dropna(
    subset=list(CF.RATE_TENORS) + ["ca_bp"])
print(f"Fig 8 frame: {len(F8)} rows  {F8.index.min().date()} .. {F8.index.max().date()}")
print(f"Fig 9 frame: {len(F9)} rows  {F9.index.min().date()} .. {F9.index.max().date()}")

# %% [markdown]
# ## 4. TIE-OUT — asserts, not prose
#
# Four independent checks. The first is an algebraic identity, the second and
# third use Citi's own printed numbers with no market data at all, and the fourth
# is the 13-row published SOFR screen.

# %%
# (i) the fly computed from the TB panel IS -w2*r2 + r5 - w10*r10, to 1e-12.
for _spec in (CF.CITI_FIG8, CF.CITI_FIG9, CF.CITI_TI_FEB9):
    _lhs = CF.fly_level(RATES, _spec.w2, _spec.w10).to_numpy(float)
    _rhs = (-_spec.w2 * RATES["2Y"] + RATES["5Y"] - _spec.w10 * RATES["10Y"]).to_numpy(float)
    _err = float(np.nanmax(np.abs(_lhs - _rhs)))
    assert _err <= CFG.fly_identity_tol, f"{_spec.label}: fly identity off by {_err:.3e}"
    _sc = CF.scaled_fly(RATES, _spec).to_numpy(float)
    _err2 = float(np.nanmax(np.abs(_sc - (_spec.alpha + _spec.beta * _rhs))))
    assert _err2 <= 1e-9, f"{_spec.label}: scaling off by {_err2:.3e}"
    print(f"  OK  {_spec.annotation():48s}  fly identity {_err:.2e}, scaling {_err2:.2e}")

# %%
# (ii) the PUBLISHED alpha/beta reproduce Citi's own fitted line on a sample date.
#      [TI-FEB9] prints every term of its own entry, so this needs no market data:
#         CA 8.8bp, fly -18.2bp, line 9.7 + 20.6*fly  ->  "about 3bp ... wide".
_gap = CF.ti_feb9_dislocation_bp()
_want = CF.TI_FEB9_TIEOUT["stated_gap_bp"]
print(f"[TI-FEB9] 9-Feb-2017: CA {CF.TI_FEB9_TIEOUT['ca_entry_bp']}bp, "
      f"fly {CF.TI_FEB9_TIEOUT['fly_entry_bp']}bp, line {CF.CITI_TI_FEB9.annotation()}")
print(f"  fitted = {CF.CITI_TI_FEB9.alpha + CF.CITI_TI_FEB9.beta * (-0.182):.3f}bp,  "
      f"CA - fitted = {_gap:.4f}bp   vs the note's stated \"about {_want:g}bp\"")
assert abs(_gap - _want) <= CFG.ti_feb9_tol_bp, (
    f"published alpha/beta give {_gap:.3f}bp of richness, note says ~{_want}bp")

# The 13-Jan version is consistent but not self-contained: Blues CA was 9.96bp
# ([VL-JAN17] Fig 48) and the text says "about 4bp ... wide", implying the fly
# stood at about (9.96 - 4 - 10.2)/21.4 = -0.198% = -19.8bp, 1.6bp from the
# -18.2bp printed 27 days later. Reported, not asserted.
_implied_fly_bp = 100.0 * (9.96 - 4.0 - CF.CITI_FIG9.alpha) / CF.CITI_FIG9.beta
print(f"  [VL-JAN17] 13-Jan implied fly level {_implied_fly_bp:.1f}bp vs the "
      f"{CF.TI_FEB9_TIEOUT['fly_entry_bp']}bp printed 27 days later")

# %%
# (iii) the cube ATMF read IS the IRSwaptionsTB value, on the five probe dates.
for _d, _v in IRSWAPTIONSTB_PROBE.items():
    _ours = float(VOL.loc[pd.Timestamp(_d)])
    assert abs(_ours - _v) < 1e-3, f"{_d}: cube {_ours} vs IRSwaptionsTB {_v}"
    print(f"  OK  {_d}  cube {_ours:.3f}  ==  IRSwaptionsTB {_v:.3f}")
print("=> the fallback path is not an approximation of the router; it is the "
      "same number, from the same store, ~2,500x faster.")

# %%
# (iv) the TB rate panel reproduces the independently built strat2_q20 rates.
_q20r = pd.read_parquet(DATA / "strat2_q20_rates.parquet")
_q20r.index = pd.to_datetime(_q20r.index)
_j = RATES.join(_q20r, rsuffix="_q20", how="inner")
for _t in CF.RATE_TENORS:
    _e = float((_j[_t] - _j[f"{_t}_q20"]).abs().max())
    assert _e < 1e-9, f"{_t}: TB panel differs from strat2_q20_rates by {_e}"
    print(f"  OK  {_t:4s} max |TB - strat2_q20_rates| = {_e:.2e} %  (n={len(_j)})")

# %%
# (v) the CA panel against Citi's published SOFR screen, close 6/9/2023.
_day = FIT[FIT["date"] == pd.Timestamp("2023-06-09")]
_rows = []
for _, _r in _day.iterrows():
    _c = CITI_SOFR_20230609.get(_r["pack"])
    if _c is None:
        continue
    _rows.append({"pack": _r["pack"], "rank": int(_r["rank"]),
                  "ca_ours": _r["ca_bp"], "ca_citi": _c["ca_bp"],
                  "d_ca": _r["ca_bp"] - _c["ca_bp"],
                  "model_ours": _r["ca_model_bp"], "model_citi": _c["model_bp"],
                  "d_model": _r["ca_model_bp"] - _c["model_bp"],
                  "vs_ours": _r["vs_model_bp"], "vs_citi": _c["vs_model_bp"]})
TIEOUT = pd.DataFrame(_rows)
print(TIEOUT.round(2).to_string(index=False))
_maxabs = float(TIEOUT["d_ca"].abs().max())
_corr = float(TIEOUT["ca_ours"].corr(TIEOUT["ca_citi"]))
print(f"\nCA:    max|ours - Citi| {_maxabs:.2f}bp, corr {_corr:.4f}   "
      f"({CFG.colour} {TIEOUT.loc[TIEOUT['rank'] == 13, 'ca_ours'].iloc[0]:.2f} "
      f"vs Citi 15.40)")
print(f"MODEL: max|ours - Citi| {float(TIEOUT['d_model'].abs().max()):.2f}bp, "
      f"corr {float(TIEOUT['model_ours'].corr(TIEOUT['model_citi'])):.4f}")
assert _maxabs <= CFG.citi_tieout_max_abs_bp
assert _corr >= CFG.citi_tieout_min_corr
assert (TIEOUT["d_model"] > 0).all(), "the fitted-sigma model should sit ABOVE Citi's"

# %% [markdown]
# **Read the model row carefully — it is a documented deviation, not a failure.**
# Citi's model is *"the Ho-Lee model calibrated to cap/floor vols"*. This repo
# has no cap/floor surface, so `strat2_sofr_convexity` fits the Ho-Lee variance
# term structure to **the day's own observed CA curve** (`sigma_model_mode="fit"`,
# a degree-2 polynomial in T). That is a smooth curve *through* the CAs, so:
#
# * it necessarily sits near them — hence +1.5bp at Reds rising to +7.8bp at
#   Golds against Citi's cap-floor-calibrated level, and
# * `vs_model_bp` here measures **this pack against the smooth curve through all
#   the packs** — a cross-sectional dislocation — while Citi's measures the pack
#   against the *options market*. Citi's Blues sat +5.42bp rich on 6/9/2023; ours
#   sits +1.91bp rich *relative to its own neighbours*. Both are real numbers;
#   they are not the same number, and chart 3 is labelled accordingly.

# %% [markdown]
# ## 5. FIGURE 8 — 3y1y implied vol vs the scaled 2s5s10s fly
#
# Exactly as published first: Citi's printed α, β and DV01 weights, applied to
# 2021–26 SOFR rates, on one axis with the vol — which is the whole point of the
# scaling.

# %%
def _line(fig, s, name, color, dash=None, width=1.7, axis="y"):
    """One gap-honest trace.

    `connectgaps=False` was here from the start and was **inert**: it only breaks
    a line where `y` is null, and `F8`/`F9` are built by an INNER join (cell 3),
    so they carry zero NaN rows for it to act on. Measured on the rendered
    notebook before this fix: the Blues CA trace held 503 points and drew
    straight lines across gaps of **301 and 502 days**.

    `bday_reindex` is the missing half — it puts the series back on a business-day
    grid so the holes become NaN rows and the flag finally has something to break
    on. Neither works alone.
    """
    s = CAP.bday_reindex(s)
    fig.add_trace(go.Scatter(
        x=list(s.index), y=s.to_numpy(float), name=name, yaxis=axis,
        mode="lines", connectgaps=False,
        line=dict(color=color, width=width, dash=dash)))


PALETTE = {"lhs": "#1f4e79", "pub": "#c0392b", "refit": "#2e8b57",
           "model": "#d98b00", "zero": "#888888"}

FLY8_PUB = CF.scaled_fly(F8, CF.CITI_FIG8)
FIT8 = CF.refit(F8["vol_bp"], F8, label=f"Fig 8 refit {F8.index.min().year}-{F8.index.max().year}")
FLY8_REFIT = CF.scaled_fly(F8, FIT8)

fig8 = go.Figure()
_line(fig8, F8["vol_bp"], f"{CFG.vol_expiry}{CFG.vol_tenor} ATMF implied vol (normals)",
      PALETTE["lhs"], width=2.1)
_line(fig8, FLY8_PUB, f"published: {CF.CITI_FIG8.annotation()}", PALETTE["pub"], dash="dot")
if CFG.refit:
    _line(fig8, FLY8_REFIT, f"refitted: {FIT8.annotation()}", PALETTE["refit"], dash="dash")
fig8.update_layout(
    title=("<b>Figure 8 reproduced — 3y1y implied vol vs the scaled 2s5s10s fly</b>"
           "<br><sub>Citi's claim: 90% correlation in levels. "
           f"Measured 2021–26 with Citi's own weights: "
           f"{CF.corr_table(F8['vol_bp'], FLY8_PUB)['corr_levels']:+.2f}</sub>"),
    yaxis=dict(title="normal vol / scaled fly (bp)"),
    xaxis=dict(title=None), template="plotly_white", height=470,
    legend=dict(orientation="h", yanchor="bottom", y=-0.30, x=0))
fig8.show()

# %% [markdown]
# ## 6. FIGURE 9 — Blues convexity adjustment vs the scaled 2s5s10s fly
#
# Same treatment. Note the gaps: wherever the SR3 strip stops reaching 16
# contiguous contracts the Blues series simply stops. Every trace is reindexed
# onto the business-day grid before `connectgaps=False` is applied, so those
# stretches are drawn as holes rather than bridged by a straight line — the gap
# table printed in cell 2 lists each one with its span.

# %%
FLY9_PUB = CF.scaled_fly(F9, CF.CITI_FIG9)
FIT9 = CF.refit(F9["ca_bp"], F9, label=f"Fig 9 refit {F9.index.min().year}-{F9.index.max().year}")
FLY9_REFIT = CF.scaled_fly(F9, FIT9)

fig9 = go.Figure()
_line(fig9, F9["ca_bp"], f"{CFG.colour} Cvx Adj (bp) — SOFR rank {CF.COLOUR_RANK[CFG.colour]}",
      PALETTE["lhs"], width=2.1)
_line(fig9, FLY9_PUB, f"published: {CF.CITI_FIG9.annotation()}", PALETTE["pub"], dash="dot")
if CFG.refit:
    _line(fig9, FLY9_REFIT, f"refitted: {FIT9.annotation()}", PALETTE["refit"], dash="dash")
fig9.update_layout(
    title=("<b>Figure 9 reproduced — Blues convexity adjustment vs the scaled 2s5s10s fly</b>"
           f"<br><sub>{len(F9)} gate-passed pack-days; the series ends where the "
           f"16-contract SR3 strip does. Levels corr with Citi's weights: "
           f"{CF.corr_table(F9['ca_bp'], FLY9_PUB)['corr_levels']:+.2f}</sub>"),
    yaxis=dict(title="bp"), xaxis=dict(title=None),
    template="plotly_white", height=470,
    legend=dict(orientation="h", yanchor="bottom", y=-0.30, x=0))
fig9.show()

# %% [markdown]
# ## 7. Correlations — levels and daily changes, against Citi's 90%

# %%
CORR = pd.DataFrame([
    CF.corr_table(F8["vol_bp"], FLY8_PUB, name="Fig 8 — vol vs PUBLISHED fly"),
    CF.corr_table(F8["vol_bp"], FLY8_REFIT, name="Fig 8 — vol vs REFITTED fly"),
    CF.corr_table(F9["ca_bp"], FLY9_PUB, name="Fig 9 — Blues CA vs PUBLISHED fly"),
    CF.corr_table(F9["ca_bp"], FLY9_REFIT, name="Fig 9 — Blues CA vs REFITTED fly"),
]).set_index("series")
print("Citi's stated Figure-8 correlation in levels: +0.90\n")
print(CORR.round(4).to_string())
CORR.to_csv(DATA / "citi_fig89_correlations.csv")

# %%
# By calendar year, so a full-sample number cannot hide a regime.
_rows = []
for _lbl, _y, _x in (("Fig 8 published", F8["vol_bp"], FLY8_PUB),
                     ("Fig 9 published", F9["ca_bp"], FLY9_PUB)):
    for _yr, _idx in _y.groupby(_y.index.year).groups.items():
        _r = CF.corr_table(_y.loc[_idx], _x.loc[_idx], name=f"{_lbl} {_yr}")
        _r["year"] = int(_yr)
        _r["which"] = _lbl
        _rows.append(_r)
BY_YEAR = pd.DataFrame(_rows).set_index(["which", "year"])[
    ["corr_levels", "n_levels", "corr_changes", "n_changes"]]
print(BY_YEAR.round(3).to_string())

# %% [markdown]
# ### Rolling 6-month correlation
#
# A single full-sample correlation cannot distinguish "the relationship decayed"
# from "the relationship was never there". This can.

# %%
RC8 = CF.rolling_corr(F8["vol_bp"], FLY8_PUB, window=CFG.roll_window,
                      min_periods=CFG.roll_min_periods)
RC9 = CF.rolling_corr(F9["ca_bp"], FLY9_PUB, window=CFG.roll_window,
                      min_periods=CFG.roll_min_periods)

figrc = go.Figure()
_line(figrc, RC8, "Fig 8 — 3y1y vol vs published fly", PALETTE["lhs"], width=2.0)
_line(figrc, RC9, "Fig 9 — Blues CA vs published fly", PALETTE["pub"], width=2.0)
figrc.add_hline(y=0.90, line=dict(color=PALETTE["refit"], width=1.4, dash="dash"),
                annotation_text="Citi: 90% in levels", annotation_position="top left")
figrc.add_hline(y=0.0, line=dict(color=PALETTE["zero"], width=1))
figrc.update_layout(
    title=(f"<b>Rolling {CFG.roll_window}-day correlation in levels, published weights</b>"
           "<br><sub>The relationship is unstable, not merely weak: both cross "
           "zero repeatedly and neither holds Citi's 90% for a sustained stretch</sub>"),
    yaxis=dict(title="correlation", range=[-1.05, 1.05]),
    template="plotly_white", height=430,
    legend=dict(orientation="h", yanchor="bottom", y=-0.28, x=0))
figrc.show()

print(f"Fig 8 rolling corr: median {RC8.median():+.2f}, "
      f"{100 * (RC8 > 0.9).mean():.1f}% of days above +0.90, "
      f"{100 * (RC8 < 0).mean():.1f}% below zero")
print(f"Fig 9 rolling corr: median {RC9.median():+.2f}, "
      f"{100 * (RC9 > 0.9).mean():.1f}% of days above +0.90, "
      f"{100 * (RC9 < 0).mean():.1f}% below zero")

# %% [markdown]
# ## 8. The regression table — published vs re-fitted
#
# `w2`/`w10` are DV01 weights with the belly normalised to 1, `alpha`/`beta` are
# the printed scaling, `beta` in units of the left-hand series per **percent** of
# fly. Published rows carry no R² because Citi does not print one.

# %%
REG8 = CF.regression_table([CF.CITI_FIG8, FIT8])
REG9 = CF.regression_table([CF.CITI_FIG9, CF.CITI_TI_FEB9, FIT9])
print("FIGURE 8 — 3y1y implied vol (bp normal) on 2y/5y/10y")
print(REG8.round(4).to_string(index=False))
print("\nFIGURE 9 — Blues convexity adjustment (bp) on 2y/5y/10y")
print(REG9.round(4).to_string(index=False))
REG = pd.concat([REG8.assign(figure=8), REG9.assign(figure=9)])
REG.to_csv(DATA / "citi_fig89_regressions.csv", index=False)

print(f"\nraw OLS coefficients, Fig 8 refit: a={FIT8.alpha:.3f}  b2={FIT8.b2:.3f}  "
      f"b5={FIT8.b5:.3f}  b10={FIT8.b10:.3f}  resid sd {FIT8.resid_sd:.2f}bp")
print(f"raw OLS coefficients, Fig 9 refit: a={FIT9.alpha:.3f}  b2={FIT9.b2:.3f}  "
      f"b5={FIT9.b5:.3f}  b10={FIT9.b10:.3f}  resid sd {FIT9.resid_sd:.2f}bp")
for _f in (FIT8, FIT9):
    if min(_f.w2, _f.w10) < 0:
        print(f"  !! {_f.label}: a NEGATIVE DV01 weight — the fitted value is not "
              f"expressible as a butterfly at all")

# %% [markdown]
# ## 9. Does the fly actually hedge? A variance-reduction test
#
# Correlation is the note's own metric, but the operational question is whether
# holding `-beta` of fly against the CA reduces the daily variance of the
# package. Citi sizes the hedge at exactly the regression β
# (`fly_belly_DV01 = CA_DV01 * beta/100`), so this is that trade's daily P&L
# variance against the unhedged leg's.

# %%
def _variance_reduction(y, rates, spec, label):
    d_y = y.diff()
    d_f = CF.fly_level(rates, spec.w2, spec.w10).reindex(y.index).diff()
    ok = d_y.notna() & d_f.notna()
    resid = d_y[ok] - spec.beta * d_f[ok]
    v0, v1 = float(d_y[ok].var(ddof=1)), float(resid.var(ddof=1))
    return {"hedge": label, "n": int(ok.sum()), "sd_unhedged": float(np.sqrt(v0)),
            "sd_hedged": float(np.sqrt(v1)),
            "variance_reduction_pct": 100.0 * (1.0 - v1 / v0) if v0 > 0 else np.nan}


VR = pd.DataFrame([
    _variance_reduction(F9["ca_bp"], F9, CF.CITI_FIG9, "Blues CA, Citi published β/weights"),
    _variance_reduction(F9["ca_bp"], F9, CF.CITI_TI_FEB9, "Blues CA, Citi 9-Feb-2017 β/weights"),
    _variance_reduction(F9["ca_bp"], F9, FIT9, "Blues CA, refitted on 2021–26 (in-sample)"),
    _variance_reduction(F8["vol_bp"], F8, CF.CITI_FIG8, "3y1y vol, Citi published β/weights"),
    _variance_reduction(F8["vol_bp"], F8, FIT8, "3y1y vol, refitted on 2021–26 (in-sample)"),
]).set_index("hedge")
print("daily-change variance of (series - beta*fly) vs the series alone:")
print(VR.round(3).to_string())
print("\nA NEGATIVE variance_reduction_pct means the 'hedge' ADDS risk.")
print("The refitted rows are IN-SAMPLE and still fail, which is the strongest")
print("form of the result: beta is estimated on LEVELS (that is what Citi's")
print("charts and annotations are), and a levels beta is not a daily-change")
print("hedge ratio. The Fig-8 refit is the extreme case -- beta 73.5 fits the")
print("level path well (R^2 0.80) and multiplies daily fly noise by 73.5.")
VR.to_csv(DATA / "citi_fig89_variance_reduction.csv")

# %% [markdown]
# ## 10. NEW CHART — convexity adjustment vs the MODEL level, as a timeseries
#
# Observed CA and the Ho-Lee model CA on the same axis, per pack colour, with the
# dislocation `vs_model_bp = CA − model` as its own panel underneath because that
# is the tradeable quantity: the trade is *"sell the convexity adjustment"* when
# it is rich to the model, not when it is high.
#
# **The model here is the σ fitted to the day's own CA term structure, not
# calibrated to cap/floor vols** (section 4). So the dislocation is
# cross-sectional and is centred near zero by construction; what it tells you is
# whether one pack is out of line with its neighbours, not whether the pack is
# rich to the options market.

# %%
_ORDER = [c for c in (CFG.colour,) + tuple(CFG.extra_colours) if c in COLOURS]
_COL = {"Blues": "#1f4e79", "Greens": "#2e8b57", "Golds": "#b8860b", "Reds": "#c0392b"}

figca = go.Figure()
for _c in _ORDER:
    _f = COLOURS[_c]
    _line(figca, _f["ca_bp"], f"{_c} CA observed (rank {CF.COLOUR_RANK[_c]})",
          _COL.get(_c, "#333"), width=2.0)
    _line(figca, _f["ca_model_bp"], f"{_c} Ho-Lee model", _COL.get(_c, "#333"),
          dash="dot", width=1.5)
figca.update_layout(
    title=("<b>Convexity adjustment vs the Ho-Lee model level</b>"
           "<br><sub>solid = observed, dotted = model (σ fitted to the day's own CA "
           "term structure). Gaps are missing SR3 strip depth, not interpolated.</sub>"),
    yaxis=dict(title="bp"), template="plotly_white", height=500,
    legend=dict(orientation="h", yanchor="bottom", y=-0.32, x=0))
figca.show()

# %%
figdis = go.Figure()
for _c in _ORDER:
    _line(figdis, COLOURS[_c]["vs_model_bp"], f"{_c} CA − model", _COL.get(_c, "#333"),
          width=1.8)
figdis.add_hline(y=0.0, line=dict(color=PALETTE["zero"], width=1.2))
figdis.update_layout(
    title=("<b>The dislocation — <code>vs_model_bp</code>, the tradeable quantity</b>"
           "<br><sub>positive = the adjustment is rich to the model = the short-convexity "
           "signal. Cross-sectional, see section 4.</sub>"),
    yaxis=dict(title="bp"), template="plotly_white", height=430,
    legend=dict(orientation="h", yanchor="bottom", y=-0.30, x=0))
figdis.show()

# %%
DIS = pd.DataFrame([CF.dislocation_stats(COLOURS[c]["vs_model_bp"], name=c)
                    for c in _ORDER]).set_index("series")
print("distribution of CA - model, by pack colour:")
print(DIS.round(3).to_string())
DIS.to_csv(DATA / "citi_fig89_dislocation_stats.csv")
print("\n'sign_changes' counts consecutive observations whose signs differ — how "
      "often the trade would have flipped from short-convexity to long-convexity.")

# %% [markdown]
# ## 11. Verdict
#
# > **Numbers below recomputed 2026-08-19** on the rebuilt CA panel — Blues goes
# > from 503 to **607** gate-passed pack-days and Greens from 739 to **825**, via
# > the coverage repair (`docs/convexityrv/ca_coverage_diagnosis.md` Part II) plus
# > a 103-date SR3 settle warm. Every figure quoted here is printed by a cell
# > above; read those, not this paragraph, if the two ever disagree.
#
# **The claim "convexity can be hedged with the fly" does not survive on 2021–26
# SOFR data.**
#
# * With Citi's own printed coefficients the two relationships are **negatively**
#   correlated in levels over the full window — Fig 8 −0.61 (n = 1,403), Fig 9
#   −0.33 (n = 607) — against the stated +0.90. Year by year they flip sign
#   repeatedly (Fig 8 +0.91 in 2021 to −0.59 in 2022; Fig 9 +0.68 to −0.67 over
#   the same pair). The rolling 6-month correlation sits below zero on **28%** of
#   days for Fig 8 and **54%** for Fig 9, and clears +0.90 on **6.7%** and
#   **0.0%** respectively. Unstable, not merely weak — and an unstable hedge
#   ratio is worse than a small one, because it cannot be corrected by resizing.
# * In daily changes, which is what a hedge lives on, Fig 9 is **+0.01**. Sizing
#   the fly at Citi's β = 21.4 *increases* the daily standard deviation of the
#   Blues CA package by **9.1%** (section 9) — and the refitted β still
#   increases it by 1.9%, in-sample.
# * Refitting restores fit but destroys the structure: the Fig-8 2y DV01 weight
#   collapses from 0.71 to ~0.01 — a combination of 5s and 10s *does* still track
#   3y1y vol at +0.89 in levels, which is the interesting half of the result, but
#   it is not the butterfly Citi specifies. The Fig-9 β falls from 21.4 to ~4.8,
#   so a hedge sized on the 2017 note is roughly 4× too big.
# * None of this is surprising. The 2017 relationship is a **ZIRP-era, Eurodollar,
#   1999–2017** artefact in which 5s valuations and 3y1y vol were both proxies for
#   the same thing — the expected pace of a *slow* hiking cycle. 2021–26 contains
#   the fastest hiking cycle since 1980 followed by a cutting cycle; vol was
#   driven by the level and speed of policy, not by the belly's curve valuation.
# * It is also **consistent with what this codebase already measured**: Citi's
#   2s5s10s hedge on the near packs scored R² 0.000–0.010 with a sign-flipping β.
#   A negative answer at Blues was the expected result, and it reproduces.
#
# **What is NOT a negative result:** the convexity adjustment itself reproduces
# Citi's published SOFR screen at corr 0.966 on 6/9/2023 (Blues 15.72 vs 15.40).
# The measurement is sound; it is the 2017 hedge relationship that has expired.
#
# **Caveats that bound all of the above**, stated so they are not discovered later:
# The Blues pack-day count printed above, concentrated in 2021 .. 2023-mid with a
# recovered 2026 block, is a short and regime-
# specific sample; the model σ is fitted to the CA cross-section rather than
# calibrated to cap/floor vols; and the matched swap is `USD-SOFR-1D` rather than
# CME-cleared, which puts every CA level here about 3.9bp below Citi's (it shifts
# α and cancels out of β, the weights and every correlation).

# %%
_summary = {
    "window_requested": [str(CFG.start), str(CFG.end)],
    "fig8": {"n": int(len(F8)),
             "span": [str(F8.index.min().date()), str(F8.index.max().date())],
             "corr_levels_published": float(CORR.loc["Fig 8 — vol vs PUBLISHED fly", "corr_levels"]),
             "corr_changes_published": float(CORR.loc["Fig 8 — vol vs PUBLISHED fly", "corr_changes"]),
             "refit": {"w2": FIT8.w2, "w10": FIT8.w10, "alpha": FIT8.alpha,
                       "beta": FIT8.beta, "r_squared": FIT8.r_squared, "n": FIT8.n}},
    "fig9": {"n": int(len(F9)),
             "span": [str(F9.index.min().date()), str(F9.index.max().date())],
             "corr_levels_published": float(CORR.loc["Fig 9 — Blues CA vs PUBLISHED fly", "corr_levels"]),
             "corr_changes_published": float(CORR.loc["Fig 9 — Blues CA vs PUBLISHED fly", "corr_changes"]),
             "refit": {"w2": FIT9.w2, "w10": FIT9.w10, "alpha": FIT9.alpha,
                       "beta": FIT9.beta, "r_squared": FIT9.r_squared, "n": FIT9.n}},
    "citi_stated_corr_levels": 0.90,
    "coverage": json.loads(COVERAGE.reset_index().to_json(orient="records")),
    "tieout_20230609": {"ca_max_abs_bp": _maxabs, "ca_corr": _corr},
    "dislocation": json.loads(DIS.reset_index().to_json(orient="records")),
    "variance_reduction": json.loads(VR.reset_index().to_json(orient="records")),
}
(DATA / "citi_fig89_summary.json").write_text(json.dumps(_summary, indent=2, default=str))
print(json.dumps(_summary["fig8"], indent=2, default=str))
print(json.dumps(_summary["fig9"], indent=2, default=str))
print(f"\nwrote {DATA / 'citi_fig89_summary.json'}")
