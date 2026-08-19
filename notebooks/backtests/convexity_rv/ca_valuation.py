# %% [markdown]
# # The two halves of Citi's convexity screen that were never built
#
# Citi's methodology footnote, verbatim (*Rates Vol Lab — Forward steepener and
# vol divergence*, 12-Jun-2023, Figure 58, close 6/9/2023):
#
# > "Convexity adjustments for 1y SOFR packs are computed as the spread between
# > the pack's rate (the average of 4 SOFR rates in the pack) and
# > matched-maturity forward 1y CME swap rate. **The model for convexity
# > adjustment is the Ho-Lee model calibrated to cap/floor vols.** Implied vol is
# > calculated by matching the model to the observed convexity adjustment.
# > **Realized vol is 3m realized vol of the corresponding pack.** For each
# > valuation metric, we mark three best short convexity trades in bold."
#
# Four claims. Two were built; two were not.
#
# | claim | status before this notebook |
# |---|---|
# | CA = pack rate − matched forward 1y swap | built (`ca_snapshot`), ties to Citi at corr 0.966 |
# | implied vol = invert Ho-Lee on the observed CA | built (`holee.implied_vol_from_ca_bp`) |
# | **model CA from a sigma calibrated to CAP/FLOOR VOLS** | **not built** |
# | **3m realized vol of the pack** | **not built at all** |
#
# `strat2_sofr_convexity`'s `sigma_model_mode="fit"` regressed a smooth variance
# term structure onto *the same day's own CA curve*, making `vs_model` a
# **cross-sectional** residual — "which pack is rich versus the other packs
# today" — centred on zero by construction. Its own docstring flagged that as a
# caveat. The footnote now confirms it is a methodology gap, and this notebook
# closes it: the model sigma now comes from the **listed SR3 cap/floor surface
# over each pack's own accrual window**, so `vs_model_capfloor_bp` is a
# **vol-market dislocation** and carries a level and a slope.
#
# ## What was measured — the numbers up front
#
# *(Every figure here is restated by a cell below. The CA panel is re-read from
# disk at execution time so a repair of its sparsity lands automatically — if the
# cells and this summary ever disagree, **the cells are what ran**.)*
#
# 1. **The observed CA did not move by one bit.** Asserted exactly (`abs=0.0`)
#    across every (date, pack) cell, and the Citi Fig-58 tie-out re-runs at
#    **corr 0.9659, max |diff| 3.06bp, Blues 15.72 vs Citi 15.40** — the same
#    numbers as before. Only the model leg changed.
# 2. **The cap/floor model leg reproduces Citi's *Model* column to 87–98% and
#    converges at the back of the strip.** Backing Citi's own sigma out of their
#    printed model column gives 169bp at Reds falling to 131bp at Blues; the
#    listed forward-starting strip vol gives 148bp falling to 128bp (ratio 0.873
#    → 0.979, median 0.889). The Blues model CA is **9.57bp against Citi's
#    9.98bp**, a 4% miss on a leg that previously had no defensible level at all;
#    mean error across the nine reproducible rows −0.96bp, worst 1.33bp.
# 3. **The model leg moved a lot, and in the way the footnote predicts.** Over
#    826 cells carrying both legs, mean |move| **2.10bp** (p95 4.78bp), and
#    `vs_model` goes from a mean of **−0.03bp** (the fitted residual, zero by
#    construction) to **+1.38bp**. The two series correlate at only **0.370** —
#    they are not the same signal, and only the second one is Citi's.
# 4. **The 3m realized vol ties out to Citi's published column at a ratio of
#    0.888–0.973 (median 0.966), correlation 0.9901** across the six packs where
#    the panel supports a 63-business-day window — an external known-answer for a
#    metric that did not exist before.
# 5. **1,773 of 2,043 (date, pack) cells got a real cap/floor vol (86.8%).**
#    98.1% in 2023, 98.6% in 2024, 97.5% in 2025, 61.1% in 2022, **0% in 2021**
#    and 46% in the part of 2026 the listed strip still reaches. Every other cell
#    is NaN with a named reason (`no_option` 244, `contract_mismatch` 26).
# 6. **2024–2026 realized vol is mostly not computable, and the reason is the
#    panel, not the metric.** The window needs 42 observed daily changes inside
#    63 business days. Against the panel as it stood when this work started (19
#    dates in 2024, 2 in 2025, 3 in 2026) **not one cell** cleared it. A repair
#    landed mid-session and lifted the near ranks; the cells below report what
#    the panel actually held at execution time, because it is re-read from disk
#    every run. The deep ranks — Blues among them — are still short. Nothing is
#    interpolated: an under-populated window is NaN.
# 7. **Listed vol runs out before Golds.** Rank 17 fails on every date tested —
#    there is no listed ATM SR3 option four years forward — so Citi's Golds row
#    cannot be reproduced from listed vol at all.
# 8. **The strike convention is worth up to half a basis point.** Switching from
#    `atm_per_caplet` to `flat_swap_rate` moves the Blues model CA by −0.474bp on
#    6/9/2023 (sigma 128.29 → 125.07); the mean over 12 measured cells is
#    −0.046bp, 1.1% of the model CA level, and the sign of `vs_model` flips on
#    **0/12**. Small on average, not noise on the worst cell.
# 9. **Three upstream defects were found and are reported, not patched** — a
#    truncated forward-starting cap strip, a QuantLib-`Date`-into-rateslib-curve
#    `TypeError`, and an IMM-date roll disagreement (which cost exactly 26 cells,
#    **all 26 of them on an IMM date**). All three are in `MDP/STIRCapFloors/`;
#    see the final section.
#
# ## What this costs to run
#
# Measured, not estimated: **19.7s cold / 18.8s warm per date** for nine pack
# ranks (**2.1s per (date, pack) cell**), and it does **not** amortise across
# consecutive dates because each date has its own at-the-money strike to find.
# Each date fires ~32,000 outbound requests that the cache guard blocks; a
# five-date probe blocked 158,851. Everything runs inside
# `listed_cache_guard.cache_only()`, so those are microseconds each instead of a
# 404 storm against a vendor. **Zero network calls were made — by this notebook
# or by the panel build behind it.**
#
# The vol panel itself (`ca_valuation_capfloor_vols.parquet`, 2,043 cells over
# 227 weekly dates 2021-06 to 2026-07) took **3,709s** across two resumable
# passes — the second added the 2024–2026 dates a parallel CA-panel repair made
# available mid-session. This notebook only reads it.
#
# ---
# **Implementation.** `RVUtils/ConvexityRV/ca_valuation.py` (new),
# `tests/test_convexity_rv_ca_valuation.py` (32 tests, 16/16 mutations caught —
# every assertion below was checked by breaking the code and confirming the test
# notices).
# Sources: `RVUtils/ConvexityRV/holee.py`, `RVUtils/ConvexityRV/packs.py`,
# `MDP/STIRCapFloors/STIRCapFloorMDP.py`, `RVUtils/ConvexityRV/strat2_q20.py`
# (Citi's published table).

# %%
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import datetime
import json
import logging
import math
import sys
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Tuple

logging.disable(logging.WARNING)

# House bootstrap: the kernel's cwd is this notebook's directory, so walk up to
# the repo root before importing anything from it. Written to work in the
# worktree it is executed from rather than a hard-coded path.
_REPO = Path.cwd()
while not (_REPO / "RVUtils").is_dir() and _REPO != _REPO.parent:
    _REPO = _REPO.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio

pio.renderers.default = "plotly_mimetype+notebook_connected"
pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 60)

from RVUtils.ConvexityRV import ca_valuation as CV
from RVUtils.ConvexityRV.listed_cache_guard import network_calls_blocked
from RVUtils.ConvexityRV.strat2_q20 import CITI_SOFR_20230609
from RVUtils.ConvexityRV.strat2_sofr_convexity import Strat2Config, model_timeseries

_NET0 = network_calls_blocked()


# %% [markdown]
# ## 0. Config
#
# One dataclass, every knob visible. The pack rank range is Citi's own minus
# Golds: **ranks 5..13 = Reds → Blues.** Rank 17 (Golds) is excluded not by
# preference but because no listed ATM SR3 option exists four years forward —
# measured on every date probed, 2023 through 2026.

# %%
@dataclass(frozen=True)
class Config:
    """Notebook-level knobs. The modelling knobs live in `CV.CAValuationConfig`."""

    data_dir: Path = Path("notebooks/data/convexity_rv")
    """Artifacts read and written here, resolved against the repo root rather
    than the kernel's cwd so the notebook runs the same from either."""

    panel_candidates: Tuple[str, ...] = ("strat2_q20_panel.parquet", "strat2_panel.parquet")
    """CA panel, first that exists wins. **q20 is preferred and that matters**:
    `strat2_ca_diagnostics` measured `strat2_panel.parquet` to have been built at
    the `usd_irs` spec's ANNUAL fixed frequency rather than Citi's
    quarterly/quarterly, biasing the CA by `-0.375*r^2` bp (−9.3bp on the front
    pack on 2023-06-09). The q20 panel is the quarterly/quarterly one, it carries
    ranks 1..17 instead of 1..10, and it is what the published 15.72 Blues
    tie-out comes from."""

    vol_panel_file: str = "ca_valuation_capfloor_vols.parquet"
    ranks: Tuple[int, ...] = tuple(range(5, 14))
    """Citi's rows 5..13 (Reds M4-H5 .. Blues M6-H7). 14..17 have no listed vol."""

    as_of: datetime.date = datetime.date(2023, 6, 9)
    """Citi's published close — the tie-out date for every external check."""

    vol_start: str = "2022-01-01"
    """First date the vol panel was built from, and it is a **measurement**, not
    a preference. A month-grid probe of ranks 2/5/9/13 over 2019-01..2026-08, run
    entirely cache-only, returned *"Could not resolve listed ATM option"* on
    every 2019 and 2020 cell and all but a handful of 2021 cells -- while costing
    up to 120s each, because a miss on a deferred contract makes the MDP walk the
    whole listed strike ladder. A first build attempt from 2021-06-01 produced
    27 cells, all `no_option`, in six minutes; those rows are retained in the
    panel below as evidence rather than deleted."""

    sens_dates: Tuple[str, ...] = ("2022-09-15", "2022-12-15", "2023-03-15",
                                   "2023-06-09", "2023-09-15")
    sens_ranks: Tuple[int, ...] = (5, 9, 13)
    """Strike-convention sensitivity is capped at 5 dates x 3 ranks: the
    `flat_swap_rate` convention snaps to the listed ladder and falls back to a
    per-strike SABR smile on a miss, which is the crawl the cache guard exists
    for. Dates are filtered to ones the CA panel actually carries, because the
    comparison needs the pack's `time_weight` to turn a vol into a model CA."""

    sens_file: str = "ca_valuation_strike_sensitivity.parquet"
    sens_control_file: str = "ca_valuation_strike_control.csv"
    """Both precomputed by `scripts`-style runner outside a Jupyter kernel and
    loaded here if present. `ERIS_EOD_LIVE-QL_BASIC` reaches an **async** Eris
    fetcher whose `run_fetch_all` coroutine is never awaited when an event loop
    is already running — which is exactly the case inside an ipykernel, where it
    warns `coroutine ... was never awaited` and hands back an unusable curve. The
    live path below still exists and runs when the artifacts are absent."""

    sens_curve_source: str = "ERIS_EOD_LIVE-QL_BASIC"
    """Curve source for the sensitivity ONLY. `flat_swap_rate` is the only
    convention that calls `STIRCapFloorMDP._contract_forward_price`, which
    reaches `_discount(curve, ql_date)`; on the rateslib-backed `CITIVELO_EXCEL`
    curve that indexes with a QuantLib `Date` and raises
    `TypeError: '<' not supported between instances of 'Date' and
    'datetime.datetime'`. The QuantLib-backed Eris curve takes the
    `handle.discount(...)` branch instead and works. The control cell below
    proves the swap does not move the ATM leg."""

    fig_height: int = 470


CFG = Config()
VCFG = CV.CAValuationConfig()          # modelling config: see its docstring
DATA = CFG.data_dir if CFG.data_dir.is_absolute() else (_REPO / CFG.data_dir).resolve()
print("data dir:", DATA, DATA.exists())
print("modelling config:")
for f in ("curve", "curve_source", "structure", "strike_convention", "weight_method",
          "vol_measure", "holee_convention", "realized_window_days", "realized_min_obs",
          "realized_annualisation", "top_n_per_metric", "allow_network"):
    print(f"  {f:26s} {getattr(VCFG, f)!r}")

# %% [markdown]
# ## 1. The CA panel — read at execution time, so a repair lands automatically
#
# The panel is deliberately re-read from disk here rather than cached in the
# module, because a repair of its post-May-2024 sparsity was running in parallel
# with this work. Whatever is on disk when the notebook executes is what gets
# reported, and the coverage table below is the honest statement of it.

# %%
_panel_path = next((DATA / f for f in CFG.panel_candidates if (DATA / f).exists()), None)
assert _panel_path is not None, f"no CA panel found in {DATA}"
PANEL = pd.read_parquet(_panel_path)
PANEL["date"] = pd.to_datetime(PANEL["date"])
print(f"CA panel: {_panel_path.name}  {PANEL.shape}  "
      f"{PANEL['date'].min().date()} .. {PANEL['date'].max().date()}")

COVERAGE = (PANEL.pivot_table(index=PANEL["date"].dt.year, columns="rank",
                              values="date", aggfunc="nunique")
            .fillna(0).astype(int))
print("\ndistinct dates per (year, pack rank):")
print(COVERAGE.to_string())
print("\nThe post-2023 thinning is the sparsity a parallel repair targets; the "
      "repair landed mid-session and lifted the NEAR ranks, so whichever shape "
      "the table above has is the panel as it stood when this cell ran. Ranks 10+ "
      "thin out from 2022 regardless, because a deep pack window needs all 20 "
      "SR3 contracts cached on the same date.")

# %% [markdown]
# ## 2. The cap/floor vol panel
#
# ### What is being asked of the option market
#
# Ho-Lee is `dr = theta(t)dt + sigma dW`: constant absolute vol, no mean
# reversion. Under it **every forward rate carries the same normal volatility
# sigma**, so the Bachelier implied vol of a caplet on an SR3 contract's forward
# rate *is* sigma, with no conversion. That is why Citi can write "Ho-Lee
# calibrated to cap/floor vols" in six words.
#
# A pack spans four caplets with four expiries and four vols; Ho-Lee wants one.
# The primary reduction is **`FLAT_BP_VOL`** — the single normal vol that
# reprices the whole four-caplet strip — because that is literally a
# one-parameter calibration to the strip. The vega-weighted average (`BPVOL`) is
# carried alongside as `sigma_capfloor_mean_bp`.
#
# ### Two mechanical points that changed the answer
#
# **(a) The request form.** `STIRCapFloorMDP._contracts_for_explicit_window`
# sizes its candidate ladder as `ceil(window_days/75)+4` contracts *from the
# front of the curve*. For a forward-starting window that is far too short:
# measured on 2023-06-09, requesting rank 9 by explicit `swap_start`/`swap_end`
# returned **one leg instead of four**, and would have reported a single caplet's
# vol as the pack vol. The `expiry`/`tail` form calls
# `resolve_quarterly_contracts(start_index=expiry//3, count=tail//3)` and returns
# exactly four. **This is an upstream defect and is reported as a follow-up
# below, not patched here.**
#
# **(b) The curve.** `STIRCapFloorMDP` defaults to `ERIS_EOD_LIVE-QL_BASIC`.
# It is overridden to `CITIVELO_EXCEL`, the same source `Strat2Config` uses, so
# the model leg and the observed CA are calibrated on one curve.
#
# Every leg is checked: four legs, the pack's own four contracts, the pack's own
# accrual window. A failure is a NaN with a **reason**, never a substituted
# number.

# %%
VOL_PATH = DATA / CFG.vol_panel_file
_need_build = not VOL_PATH.exists()
_t0 = time.time()
if _need_build:
    print("no vol panel on disk — building the tie-out date only (cache-only)")
    VOLS = CV.build_capfloor_vol_panel([CFG.as_of], CFG.ranks, VCFG,
                                       resume_path=str(VOL_PATH), progress=False)
else:
    VOLS = pd.read_parquet(VOL_PATH)
    VOLS["date"] = pd.to_datetime(VOLS["date"])
print(f"vol panel: {VOLS.shape} in {time.time() - _t0:.1f}s  "
      f"{VOLS['date'].min().date()} .. {VOLS['date'].max().date()}")
print(f"distinct dates {VOLS['date'].nunique()}, ranks {sorted(VOLS['rank'].unique())}")

# %% [markdown]
# ### How many (date, pack) cells got a real cap/floor vol
#
# `ok` is a real calibration off four listed ATM quotes. Every other value is a
# NaN with its cause named. `no_option` means the listed ATM SR3 option for at
# least one of the pack's four contracts does not exist, or is not on this
# machine — under `cache_only()` the two are indistinguishable and are not
# distinguished.

# %%
REASONS = VOLS.groupby("reason").size().sort_values(ascending=False)
print("cells by reason:")
print(REASONS.to_string())
_ok = int(REASONS.get("ok", 0))
print(f"\nREAL cap/floor vol: {_ok}/{len(VOLS)} cells ({100 * _ok / max(len(VOLS), 1):.1f}%)")

CELLTAB = CV.vol_panel_coverage(VOLS, by="rank")
print("\nby (year, rank):")
print(CELLTAB.to_string())

_yr = VOLS.assign(year=VOLS["date"].dt.year, ok=VOLS["reason"].eq("ok"))
YEARTAB = _yr.groupby("year").agg(cells=("ok", "size"), ok=("ok", "sum"))
YEARTAB["pct_ok"] = (100 * YEARTAB["ok"] / YEARTAB["cells"]).round(1)
print("\nby year:")
print(YEARTAB.to_string())

# `contract_mismatch` is not random: it lands on IMM dates. `packs.quarterly_imm_
# sequence(include_current=True)` keeps a contract whose IMM date IS today (it is
# still the live front contract); the option MDP's `_imm_cutoff` has already
# rolled past it. The two then disagree about which four contracts a pack is, and
# the leg-identity guard refuses the cell rather than calibrating the model leg
# off the wrong strip. That is the guard doing its job, and it is the right
# answer -- but it costs one date per quarter and is worth fixing upstream.
from RVUtils.ConvexityRV.packs import imm_date as _imm

_mis = VOLS[VOLS["reason"] == "contract_mismatch"]
if len(_mis):
    _immset = {_imm(y, m) for y in range(2021, 2028) for m in (3, 6, 9, 12)}
    _d = pd.to_datetime(_mis["date"]).dt.date
    _on_imm = int(_d.isin(_immset).sum())
    print(f"\ncontract_mismatch: {len(_mis)} cells on {_mis['date'].nunique()} dates; "
          f"{_on_imm}/{len(_mis)} of them fall exactly on an IMM date "
          f"({sorted({str(x) for x in _d})[:6]})")
else:
    print("\ncontract_mismatch: 0 cells")

# %%
_f = go.Figure()
for _r in sorted(VOLS["rank"].unique()):
    _s = VOLS[(VOLS["rank"] == _r) & (VOLS["reason"] == "ok")]
    _ser = (_s.set_index("date")["sigma_capfloor_flat_bp"]
            .reindex(pd.DatetimeIndex(sorted(VOLS["date"].unique()))))
    _f.add_trace(go.Scatter(x=_ser.index, y=_ser.values, mode="lines+markers",
                            name=f"rank {_r}", connectgaps=False,
                            marker=dict(size=4)))
_f.update_layout(
    title="Cap/floor normal vol over each pack's own accrual window<br>"
          "<sub>listed SR3 ATM caplet strip, FLAT_BP_VOL. Gaps are NOT bridged: "
          "connectgaps=False on the vol panel's own weekly grid, so a hole in the "
          "listed-option record shows as a hole</sub>",
    xaxis_title="date", yaxis_title="normal vol (bp/yr)", height=CFG.fig_height,
    legend_title="pack rank")
_f

# %% [markdown]
# ## 3. TIE-OUT (a) — the observed CA must not move by one bit
#
# The existing tie-out to Citi's Figure 58 is the contract this work had to keep:
# **corr 0.966, max |diff| 3.06bp, our Blues 15.72 against Citi's 15.40.** Adding
# a model leg must not touch the observed adjustment. Two assertions, the first
# exact.

# %%
SIGMA = CV.sigma_wide(VOLS, VCFG)
VALUED = CV.model_ca_from_sigma(PANEL, SIGMA, VCFG)

_before = PANEL.set_index(["date", "rank"])["ca_bp"]
_after = VALUED.set_index(["date", "rank"])["ca_bp"]
assert _before.index.equals(_after.index), "the panel's row set changed"
_dmax = float((_after - _before).abs().max())
print(f"ASSERT observed CA unchanged over {len(_before):,} (date, rank) cells: "
      f"max |diff| = {_dmax:.1e} bp")
assert _dmax == 0.0, f"the observed CA moved by {_dmax}bp"
print("TIE-OUT (a1) PASS — the model leg changed, the observed CA did not")

_day = VALUED[VALUED["date"] == pd.Timestamp(CFG.as_of)].set_index("pack")
CITI = pd.DataFrame(CITI_SOFR_20230609).T.astype(float)
CITI.index.name = "pack"
CITI = CITI.rename(columns={c: f"citi_{c}" for c in CITI.columns if c != "rank"})
CMP = CITI.join(_day[["ca_bp", "time_weight", "sigma_capfloor_bp",
                      "ca_model_capfloor_bp", "vs_model_capfloor_bp",
                      "implied_vol_bp"]].rename(columns={"ca_bp": "our_ca_bp"}))
CMP["d_ca_bp"] = CMP["our_ca_bp"] - CMP["citi_ca_bp"]
_corr = float(CMP["our_ca_bp"].corr(CMP["citi_ca_bp"]))
_maxd = float(CMP["d_ca_bp"].abs().max())
_blues = float(CMP.loc["M6-H7", "our_ca_bp"])
print(f"\nCiti Fig 58, {CFG.as_of}: 13/13 rows joined, corr {_corr:.4f}, "
      f"max |diff| {_maxd:.2f}bp, Blues {_blues:.2f} vs Citi 15.40")
assert _corr > 0.95, _corr
assert abs(_blues - 15.40) < 0.5, _blues
print("TIE-OUT (a2) PASS — the published CA tie-out is exactly where it was")

# %% [markdown]
# ## 4. The model leg: cap/floor vols against Citi's own
#
# Citi publishes the model **CA**, not the sigma behind it. The only way to
# compare calibrations is to invert their column with the same closed form they
# use on the observed CA:
#
# $$\sigma_{\text{Citi}} = \sqrt{2 \cdot \text{Model}_{bp} / \overline{T_1^2}}$$
#
# No free parameters — it is an inversion of published numbers.

# %%
_tw = _day["time_weight"].to_dict()
CITISIG = CV.citi_implied_model_sigma(CITI_SOFR_20230609, _tw)
MODELCMP = CITISIG.join(_day[["sigma_capfloor_bp", "ca_model_capfloor_bp",
                              "vs_model_capfloor_bp"]])
MODELCMP["sigma_ratio"] = MODELCMP["sigma_capfloor_bp"] / MODELCMP["citi_model_sigma_bp"]
MODELCMP["d_model_bp"] = MODELCMP["ca_model_capfloor_bp"] - MODELCMP["citi_model_bp"]
print(MODELCMP[["rank", "citi_ca_bp", "citi_model_bp", "citi_model_sigma_bp",
                "sigma_capfloor_bp", "ca_model_capfloor_bp", "d_model_bp",
                "sigma_ratio", "vs_model_capfloor_bp"]].round(3).to_string())

_ok_rows = MODELCMP.dropna(subset=["sigma_capfloor_bp"])
print(f"\n{len(_ok_rows)}/13 Citi rows have a listed cap/floor vol.")
print(f"sigma ratio (ours / Citi's implied): {_ok_rows['sigma_ratio'].min():.3f} .. "
      f"{_ok_rows['sigma_ratio'].max():.3f}, median {_ok_rows['sigma_ratio'].median():.3f}")
print(f"model CA error: mean {_ok_rows['d_model_bp'].mean():+.2f}bp, "
      f"max |diff| {_ok_rows['d_model_bp'].abs().max():.2f}bp")
_lo = _ok_rows.sort_values("rank")
print(f"\nThe ratio RISES with maturity ({_lo['sigma_ratio'].iloc[0]:.2f} at rank "
      f"{int(_lo['rank'].iloc[0])} -> {_lo['sigma_ratio'].iloc[-1]:.2f} at rank "
      f"{int(_lo['rank'].iloc[-1])}; not strictly monotone at the front, where "
      "the caplet vols fan out most) — the listed forward-starting strip is "
      "furthest from Citi's calibration at the front of the curve and converges "
      "on it by Blues. That shape is the signature of a different reading of "
      "WHICH caplets belong to a pack, not of a units error.")

# %% [markdown]
# ### Which reading of "cap/floor vol" is Citi using?
#
# The footnote does not say whether the vol belongs to the pack's own
# forward-starting strip or to a spot-starting cap running to the pack's end.
# This module implements the former — the pack-level Ho-Lee formula prices *those
# four contracts'* convexity, so sigma must be the vol those four carry. The
# alternative is computed here as a clearly separate quantity so the reader can
# see which is closer to Citi, rather than being asked to take the default on
# trust. **Neither is silently substituted for the other.**

# %%
_alt = []
for _r in (5, 9, 13):
    _lab, *_ = CV.pack_spec_for_rank(CFG.as_of, _r)
    _s = CV.spot_starting_cap_vol(CFG.as_of, _r, VCFG)
    _row = MODELCMP.loc[_lab] if _lab in MODELCMP.index else None
    _alt.append({
        "rank": _r, "pack": _lab,
        "citi_model_sigma_bp": float(_row["citi_model_sigma_bp"]) if _row is not None else np.nan,
        "fwd_starting_strip_bp": float(_row["sigma_capfloor_bp"]) if _row is not None else np.nan,
        "spot_starting_cap_bp": _s.sigma_flat_bp, "spot_n_caplets": _s.n_legs,
        "reason": _s.reason})
ALT = pd.DataFrame(_alt).set_index("pack")
ALT["fwd_err"] = ALT["fwd_starting_strip_bp"] - ALT["citi_model_sigma_bp"]
ALT["spot_err"] = ALT["spot_starting_cap_bp"] - ALT["citi_model_sigma_bp"]
print(ALT.round(2).to_string())
print("\nNeither reading recovers Citi's front-pack level. Citi's Reds model sigma "
      "(169bp) sits ABOVE both the forward-starting strip (148bp) and the "
      "spot-starting cap (142bp), which is what you would expect if their surface "
      "is OTC SOFR caps rather than listed SR3 options — a different market with "
      "its own basis. The gap is reported, not calibrated away.")

# %% [markdown]
# ## 5. How much did the model leg actually move?
#
# The old `sigma_model_mode="fit"` leg against the new cap/floor leg, on the
# cells where both exist. This is the size of the methodology change.

# %%
S2 = Strat2Config(n_contracts=20, rank_start=5, n_packs=13,
                  holee_convention=CV.CITI_CONVENTION)
# ^ pinned, not inherited: `holee.DEFAULT_CONVENTION` was observed flipping to
#   "hull" mid-session, and the cross-check below would then fail for a reason
#   that has nothing to do with this module.
_sub = PANEL[(PANEL["rank"] >= 5) & (PANEL["rank"] <= 13)].copy()
FIT = model_timeseries(_sub, S2)["fit"][["date", "rank", "pack", "ca_bp",
                                         "sigma_model_bp", "ca_model_bp"]]
FIT = FIT.rename(columns={"sigma_model_bp": "sigma_fit_bp", "ca_model_bp": "ca_model_fit_bp"})
BOTH = (VALUED[VALUED["rank"].between(5, 13)]
        .merge(FIT.drop(columns=["ca_bp"]), on=["date", "rank", "pack"], how="left"))
BOTH["vs_model_fit_bp"] = BOTH["ca_bp"] - BOTH["ca_model_fit_bp"]
BOTH["d_model_bp"] = BOTH["ca_model_capfloor_bp"] - BOTH["ca_model_fit_bp"]
BOTH["d_sigma_bp"] = BOTH["sigma_capfloor_bp"] - BOTH["sigma_fit_bp"]

_c = BOTH.dropna(subset=["ca_model_capfloor_bp", "ca_model_fit_bp"])
print(f"cells with BOTH model legs: {len(_c):,}")
assert len(_c) > 100, ("too few overlapping cells to say anything about how much "
                       "the model leg moved -- the vol panel build did not finish")
MOVE = pd.DataFrame({
    "model CA, CA-fitted sigma (bp)": _c["ca_model_fit_bp"].describe(),
    "model CA, cap/floor sigma (bp)": _c["ca_model_capfloor_bp"].describe(),
    "difference (bp)": _c["d_model_bp"].describe(),
    "vs_model, fitted (bp)": _c["vs_model_fit_bp"].describe(),
    "vs_model, cap/floor (bp)": _c["vs_model_capfloor_bp"].describe(),
}).T[["count", "mean", "std", "min", "50%", "max"]]
print(MOVE.round(3).to_string())
print(f"\nmean |model CA move| = {_c['d_model_bp'].abs().mean():.2f}bp, "
      f"p95 = {np.nanpercentile(_c['d_model_bp'].abs(), 95):.2f}bp")
print(f"correlation of the two vs_model series: "
      f"{_c['vs_model_capfloor_bp'].corr(_c['vs_model_fit_bp']):.3f}")
print(f"\nMean vs_model: fitted {_c['vs_model_fit_bp'].mean():+.2f}bp, "
      f"cap/floor {_c['vs_model_capfloor_bp'].mean():+.2f}bp.")
print("The fitted leg is centred on ~zero BY CONSTRUCTION (it is a residual from "
      "a regression on the same cross-section). The cap/floor leg is not, and "
      "that non-zero level IS the vol-market dislocation Citi reports.")

# %%
_pivot = _c.pivot_table(index="rank", values=["vs_model_fit_bp", "vs_model_capfloor_bp"],
                        aggfunc="mean")
_f = go.Figure()
_f.add_trace(go.Bar(x=_pivot.index, y=_pivot["vs_model_fit_bp"],
                    name="old: sigma fitted to the day's own CA curve",
                    marker_color="#B0B0B0"))
_f.add_trace(go.Bar(x=_pivot.index, y=_pivot["vs_model_capfloor_bp"],
                    name="new: sigma from cap/floor vols", marker_color="#E45756"))
_f.update_layout(
    title="A cross-sectional residual versus a vol-market dislocation<br>"
          "<sub>mean vs_model by pack rank. The fitted leg averages ~0 by "
          "construction; the cap/floor leg carries a level and a slope, which is "
          "the column Citi actually prints</sub>",
    xaxis_title="pack rank (13 = Blues)", yaxis_title="mean vs_model (bp)",
    barmode="group", height=CFG.fig_height)
_f

# %% [markdown]
# ### Cross-check: the locked module's own `external` path agrees
#
# `strat2_sofr_convexity` documents `sigma_model_mode="external"` as *"the
# faithful reading of 'calibrated to cap/floor vols'"* and takes an
# `external_sigma` frame. Feeding it the same wide sigma frame must give the same
# model CA as `ca_valuation.model_ca_from_sigma`. Two independent code paths, one
# answer — and if they ever disagree, one of them has drifted.

# %%
_ext_cfg = replace(S2, sigma_model_mode="external")
# Only dates the sigma frame covers: the locked `_sigma_for_day` RAISES rather
# than returning NaN when external mode is handed a date it has no row for, so
# the filter is required, not tidiness.
_sub_ext = _sub[_sub["date"].isin(pd.DatetimeIndex(SIGMA.index))]
print(f"external cross-check on {_sub_ext['date'].nunique()} dates "
      f"({len(_sub_ext):,} rows) covered by the sigma frame")
_ext = model_timeseries(_sub_ext, _ext_cfg, external_sigma=SIGMA)["fit"]
_j = (_ext[["date", "rank", "ca_model_bp"]]
      .merge(VALUED[["date", "rank", "ca_model_capfloor_bp"]], on=["date", "rank"]))
_j = _j.dropna(subset=["ca_model_bp", "ca_model_capfloor_bp"])
_gap = float((_j["ca_model_bp"] - _j["ca_model_capfloor_bp"]).abs().max())
print(f"ASSERT locked external path == ca_valuation on {len(_j):,} cells: "
      f"max |diff| = {_gap:.3e} bp")
assert _gap < 1e-9, _gap
print("CROSS-CHECK PASS")

# %% [markdown]
# ## 6. Strike convention — caps are struck, Ho-Lee's sigma is not
#
# `atm_per_caplet` strikes each caplet at its own listed at-the-money strike. It
# is the default because it needs no view on where the strip should be struck.
# The alternative, `flat_swap_rate`, strikes every caplet at the pack's own
# matched forward swap rate and snaps to the listed ladder; where the snapped
# strike has no cached quote the MDP falls back to a per-strike SABR smile, which
# is exactly the crawl the cache guard exists for. So this is a deliberately
# small sample and every leg's `quote_source` is reported with the number.
#
# **One substitution, and it is controlled.** `flat_swap_rate` is the only
# convention that calls `STIRCapFloorMDP._contract_forward_price`, which reaches
# `_discount(curve, ql_date)`. On the **rateslib**-backed `CITIVELO_EXCEL` curve
# that indexes the curve with a QuantLib `Date` and raises
# `TypeError: '<' not supported between instances of 'Date' and
# 'datetime.datetime'` — an upstream defect, reported below and not patched here.
# The sensitivity is therefore measured on the QuantLib-backed Eris curve. The
# control cell asserts that the swap does **not** move the `atm_per_caplet`
# answer, because the ATM path takes its strike from the listed option rather
# than from the curve. If that assert ever fires, the comparison is not
# like-for-like and the numbers below mean nothing.
#
# **And one more environment fact, recorded because it cost a notebook run.**
# The Eris curve source reaches an **async** fetcher whose `run_fetch_all`
# coroutine is never awaited when an event loop is already running — i.e. inside
# an ipykernel. It warns `coroutine ... was never awaited` and returns an
# unusable curve, so this comparison **cannot be computed inside the notebook**.
# It is therefore precomputed by a plain-Python run and loaded from
# `ca_valuation_strike_sensitivity.parquet` / `ca_valuation_strike_control.csv`.
# The live code path is still here and runs if the artifacts are missing.

# %%
_ctl_p, _sens_p = DATA / CFG.sens_control_file, DATA / CFG.sens_file
_precomputed = _ctl_p.exists() and _sens_p.exists()
if _precomputed:
    CTL = pd.read_csv(_ctl_p)
    SENS = pd.read_parquet(_sens_p)
    print(f"loaded precomputed: {_ctl_p.name}, {_sens_p.name}")
    print("(computed outside the kernel on purpose — see the note above)\n")
else:
    print("no precomputed artifact; computing live\n")
    _ctl = []
    for _src in (VCFG.curve_source, CFG.sens_curve_source):
        _r = CV.pack_capfloor_vol(CFG.as_of, 13, replace(VCFG, curve_source=_src))
        _ctl.append({"curve_source": _src, "reason": _r.reason,
                     "sigma_atm_bp": _r.sigma_flat_bp})
    CTL = pd.DataFrame(_ctl)
    _sens_dates = [pd.Timestamp(d).date() for d in CFG.sens_dates
                   if pd.Timestamp(d) in set(PANEL["date"])]
    SENS = CV.strike_convention_sensitivity(
        _sens_dates, CFG.sens_ranks, PANEL, VCFG, curve_source=CFG.sens_curve_source)

# CONTROL: does swapping the curve source move the ATM answer? It must not --
# the ATM path takes its strike from the listed option, not from the curve --
# and if it did, the comparison below would not be like-for-like.
print("CONTROL — atm_per_caplet sigma for Blues on the tie-out date, both curves:")
print(CTL.round(4).to_string(index=False))
_cv = CTL["sigma_atm_bp"].dropna()
assert len(_cv) == 2 and abs(_cv.iloc[0] - _cv.iloc[1]) < 1e-6, \
    "curve source moves the ATM sigma; the substitution below is not valid"
print("CONTROL PASS — identical to 1e-6, so the curve swap is a no-op for the "
      "ATM leg and the comparison below is like-for-like.\n")
SENS["date"] = pd.to_datetime(SENS["date"])
print(SENS[["date", "rank", "pack", "sigma_atm_bp", "sigma_flatswap_bp", "d_sigma_bp",
            "ca_model_atm_bp", "ca_model_flatswap_bp", "d_ca_model_bp",
            "reason_flatswap", "quote_sources_flatswap"]].round(3).to_string(index=False))
_s = SENS.dropna(subset=["d_ca_model_bp"])
if len(_s):
    _pct = 100 * (_s["d_ca_model_bp"].abs() / _s["ca_model_atm_bp"].abs()).mean()
    print(f"\n{len(_s)}/{len(SENS)} cells resolve under BOTH conventions.")
    print(f"sigma moves: mean {_s['d_sigma_bp'].mean():+.2f} bp/yr "
          f"({100 * (_s['d_sigma_bp'] / _s['sigma_atm_bp']).mean():+.1f}%)")
    print(f"model CA moves: mean {_s['d_ca_model_bp'].mean():+.3f}bp, "
          f"max |diff| {_s['d_ca_model_bp'].abs().max():.3f}bp, "
          f"{_pct:.1f}% of the model CA level")
    _worst = _s.loc[_s["d_ca_model_bp"].abs().idxmax()]
    _wpct = 100 * abs(_worst["d_sigma_bp"] / _worst["sigma_atm_bp"])
    print(f"\nWorst cell: {_worst['pack']} on {pd.Timestamp(_worst['date']).date()}, "
          f"sigma {_worst['sigma_atm_bp']:.2f} -> {_worst['sigma_flatswap_bp']:.2f} "
          f"({_wpct:.1f}%), model CA {_worst['ca_model_atm_bp']:.3f} -> "
          f"{_worst['ca_model_flatswap_bp']:.3f} ({_worst['d_ca_model_bp']:+.3f}bp).")
    print("The model CA scales as sigma^2, so a few percent on the strike "
          "convention's vol is roughly twice that on the model leg. On average "
          "the effect is small; on the worst cell it is a material fraction of a "
          "basis point on a dislocation measured in single basis points. It does "
          "not flip the SIGN of vs_model on any cell here — checked below — but "
          "it is not noise, and the reader is entitled to the number.")
    _v = SENS.merge(VALUED[["date", "rank", "ca_bp"]], on=["date", "rank"], how="left")
    _v = _v.dropna(subset=["ca_model_atm_bp", "ca_model_flatswap_bp", "ca_bp"])
    _sign_flips = int((np.sign(_v["ca_bp"] - _v["ca_model_atm_bp"])
                       != np.sign(_v["ca_bp"] - _v["ca_model_flatswap_bp"])).sum())
    print(f"vs_model sign flips under the alternative strike: "
          f"{_sign_flips}/{len(_v)} cells")
else:
    print("\nNo cell resolves under BOTH conventions on this machine, so the "
          "sensitivity is NOT measured here -- stated rather than papered over.")
print(f"\nThe reported model CA is built on: strike_convention="
      f"{VCFG.strike_convention!r}, weight_method={VCFG.weight_method!r}, "
      f"structure={VCFG.structure!r}, vol_measure={VCFG.vol_measure!r}.")

# %% [markdown]
# ## 7. The 3m realized vol of the pack — the metric that did not exist
#
# > *"Realized vol is 3m realized vol of the corresponding pack."*
#
# The pack rate is the arithmetic mean of its four contract rates, keyed by pack
# **label**, so the series is constant-contract and carries no IMM-roll jump.
# Every step is a convention and every one is stated:
#
# 1. pivot to wide `date × pack` and **reindex onto the complete business-day
#    grid**. Without this, `.diff()` on a sparse index computes a 200-day change
#    and calls it a daily change — on a panel with 249 dates in 2022 and 19 in
#    2024 that would inflate the 2024 vol by roughly √13.
# 2. `diff() × 100` → **daily close-to-close change in bp**. Across a gap this is
#    NaN by construction.
# 3. `rolling(63, min_periods=42).std(ddof=1)` → sample standard deviation over a
#    **63-business-day** window (= 252/4, one quarter), emitted only where **at
#    least 42 of the 63 possible daily changes actually exist**. 42 = 2/3 of the
#    window; below it the cell is NaN.
# 4. `× √252` → annualised **normal vol in bp/yr**, the same units as the
#    cap/floor vol and the Ho-Lee implied vol. 252 because the window is 252/4
#    business days; annualising a business-day window at 365 would overstate the
#    vol by 20%.
#
# No EWMA and no demeaning beyond what `std` does — "3m realized vol" reads most
# simply as a 3m sample standard deviation.

# %%
RV = CV.pack_realized_vol(PANEL, VCFG)
print(f"realized-vol grid: {RV.shape[0]:,} business days x {RV.shape[1]} pack labels")
RVCOV = CV.realized_vol_coverage(RV)
print("\nHOW MUCH IS COMPUTABLE, by year:")
print(RVCOV.to_string())
_late = RVCOV.loc[RVCOV.index >= 2024]
print(f"\n2024-2026: {int(_late['computable'].sum()):,} of "
      f"{int(_late['grid_cells'].sum()):,} grid cells computable "
      f"({100 * _late['computable'].sum() / max(_late['grid_cells'].sum(), 1):.1f}%).")
# Read the panel's own post-2023 date counts rather than quoting them, so this
# statement cannot go stale against a repaired panel -- which is exactly what
# happened once during development, mid-execution.
_pc = (PANEL[PANEL["date"] >= "2024-01-01"]
       .groupby([PANEL["date"].dt.year, "rank"])["date"].nunique().unstack())
print("\ndistinct CA-panel dates per (year, rank), 2024 on:")
print(_pc.fillna(0).astype(int).to_string())
print("\nEvery non-computable cell is NaN, not interpolated. The cause is the CA "
      "panel's own post-2023 sparsity: the realized-vol window needs 42 observed "
      "daily changes inside 63 business days, and a pack label only clears that "
      "where its own rank is densely populated. Whatever the table above shows "
      "is what this run had -- the panel is re-read from disk at execution time, "
      "so a repair lands here automatically.")

# %% [markdown]
# ### TIE-OUT (c) — against Citi's published *Realized Vol* column
#
# Citi prints a 3m realized vol per pack on 6/9/2023. It is an external
# known-answer for a metric this repo has never computed, and nothing in the
# construction above was tuned to it.

# %%
_d = pd.Timestamp(CFG.as_of)
RVTIE = CITISIG[["rank", "citi_realized_vol_bp"]].copy()
RVTIE["our_realized_vol_bp"] = [
    float(RV.at[_d, lab]) if (_d in RV.index and lab in RV.columns) else np.nan
    for lab in RVTIE.index]
RVTIE["ratio"] = RVTIE["our_realized_vol_bp"] / RVTIE["citi_realized_vol_bp"]
print(RVTIE.round(2).to_string())
_m = RVTIE.dropna(subset=["our_realized_vol_bp"])
print(f"\n{len(_m)}/13 packs have a computable 63-business-day window on {CFG.as_of}.")
print(f"ratio ours/Citi: {_m['ratio'].min():.3f} .. {_m['ratio'].max():.3f}, "
      f"median {_m['ratio'].median():.3f}")
assert len(_m) >= 4, "too few packs to call this a tie-out"
assert 0.80 < _m["ratio"].median() < 1.20, _m["ratio"].median()
_corr_rv = float(_m["our_realized_vol_bp"].corr(_m["citi_realized_vol_bp"]))
print(f"correlation across packs: {_corr_rv:.4f}")
assert _corr_rv > 0.95, _corr_rv
print("TIE-OUT (c) PASS — the realized-vol construction reproduces Citi's column "
      "in level, in shape and in its downward slope with maturity")
print("\nThe packs that print NaN are ranks 11-17: their labels appear in the "
      "panel on too few dates before 6/9/2023 to fill a 63-day window, because a "
      "deep pack needs all 20 SR3 contracts cached on each date. That is a data "
      "limit, and NaN is the correct answer to it.")

# %% [markdown]
# ### Is the answer an artefact of the window and the annualisation?
#
# Both are conventions the footnote does not pin. Perturbing them measures how
# much of the tie-out is construction and how much is choice. Nothing below is
# adopted — the stated convention stays 63 business days, ddof=1, √252.

# %%
_variants = [("63bd, ddof=1, sqrt(252)  [stated]", VCFG),
             ("63bd, ddof=0, sqrt(252)  [approx: scaled at n=63]", None),
             ("66bd (3 calendar months), sqrt(252)",
              replace(VCFG, realized_window_days=66, realized_min_obs=44)),
             ("63bd, sqrt(260)", replace(VCFG, realized_annualisation=260.0)),
             ("63bd, sqrt(365)", replace(VCFG, realized_annualisation=365.0))]
_rows = []
for _name, _c in _variants:
    if _c is None:                       # ddof=0 is not a config knob; scale it
        _r = RV * math.sqrt((VCFG.realized_window_days - 1) / VCFG.realized_window_days)
    else:
        _r = CV.pack_realized_vol(PANEL, _c)
    _vals = [float(_r.at[_d, lab]) if (_d in _r.index and lab in _r.columns) else np.nan
             for lab in RVTIE.index]
    _rat = np.array(_vals) / RVTIE["citi_realized_vol_bp"].to_numpy()
    _rows.append({"variant": _name, "n": int(np.isfinite(_rat).sum()),
                  "median ratio vs Citi": float(np.nanmedian(_rat))})
print(pd.DataFrame(_rows).round(4).to_string(index=False))
print("\nThe convention choice moves the ratio by a few percent; the 20% error a "
      "365 annualisation would introduce is visible and is the reason 252 is "
      "stated explicitly rather than left to a default.")

# %%
_labels = [l for l in ["M4-H5", "U4-M5", "Z4-U5", "H5-Z5", "M5-H6", "U5-M6"]
           if l in RV.columns]
_f = go.Figure()
for _lab in _labels:
    _f.add_trace(go.Scatter(x=RV.index, y=RV[_lab], mode="lines", name=_lab,
                            connectgaps=False))
_f.update_layout(
    title="3m realized vol of the pack rate, on the business-day grid<br>"
          "<sub>63 business days, min 42 observations, annualised at sqrt(252). "
          "connectgaps=False, so the void after 2023 is the CA panel's own "
          "sparsity drawn as the hole it is, not bridged by a straight line</sub>",
    xaxis_title="date", yaxis_title="realized vol (bp/yr)", height=CFG.fig_height,
    legend_title="pack")
_f

# %% [markdown]
# ## 8. The valuation screen — the three metrics, and the three best shorts
#
# > *"For each valuation metric, we mark three best short convexity trades in
# > bold."*
#
# Short convexity is attractive where the market **pays too much** for convexity:
# the observed CA rich to the cap/floor-calibrated model, and the CA-implied vol
# rich to what the pack has actually delivered. Both metrics are therefore signed
# so **higher is a better short**, and the rule is one `nlargest(3)` per metric
# over the finite values only — a metric with no finite value casts no vote.

# %%
SCREEN = CV.valuation_screen(CFG.as_of, VALUED, RV, VCFG, ranks=CFG.ranks)
_cols = ["rank", "colour", "ca_bp", "ca_model_capfloor_bp", "vs_model_capfloor_bp",
         "implied_vol_bp", "realized_vol_bp", "implied_minus_realized_bp",
         "implied_over_realized", "sigma_capfloor_bp", "capvol_over_realized"]
print(f"Citi's valuation screen, close {CFG.as_of}:")
print(SCREEN[_cols].round(2).to_string())

TOP = CV.top_short_convexity(SCREEN, VCFG)
print("\nTHREE BEST SHORT CONVEXITY TRADES (ranked by how many metrics agree):")
print(TOP[["rank", "colour", "vs_model_capfloor_bp", "implied_minus_realized_bp",
           "implied_over_realized", "n_flags", "mean_pct"]].head(5).round(2).to_string())
_best = list(TOP.index[:3])
print(f"\n  -> {', '.join(_best)}")
print("\nCiti's own caveat, carried verbatim in spirit: these are the most "
      "attractive ON THE CHART, not recommendations. Nothing here accounts for "
      "carry, financing, or the CA's own measurement error, which "
      "`strat2_ca_diagnostics` put at 1.7-2.7bp per observation at ranks 1-8 — "
      "the same order as the dislocations being ranked.")

# %% [markdown]
# ### The screen through time
#
# Computed on every date the vol panel covers. Note the grid: the vol panel is
# **weekly** — one CA-panel date per ISO week from 2022-01-01 — because at 2.1s
# per (date, pack) cell a daily build over the same span is a multi-hour job. The
# series below are reindexed onto that weekly grid with NaNs and drawn with
# `connectgaps=False`, so a week with no usable cap/floor vol is a gap and not a
# straight line through it.

# %%
_dates = sorted(set(VOLS.loc[VOLS["reason"] == "ok", "date"])
                & set(PANEL["date"]))
SCREENS = []
for _dt in _dates:
    _s = CV.valuation_screen(_dt, VALUED, RV, VCFG, ranks=CFG.ranks)
    if not _s.empty:
        _s = _s.assign(date=_dt)
        _flags = CV.short_convexity_flags(_s, VCFG)
        _s["n_flags"] = _flags["n_flags"]
        SCREENS.append(_s)
SCREENS = pd.concat(SCREENS, ignore_index=True) if SCREENS else pd.DataFrame()
assert len(SCREENS), "no screen history: the vol panel and the CA panel do not overlap"
print(f"screen history: {len(SCREENS):,} (date, pack) rows over "
      f"{SCREENS['date'].nunique()} dates "
      f"({SCREENS['date'].min().date()} .. {SCREENS['date'].max().date()})")
print("\nby rank, over the whole vol-panel window:")
print(SCREENS.groupby("rank")[["ca_bp", "ca_model_capfloor_bp",
                               "vs_model_capfloor_bp", "implied_vol_bp",
                               "sigma_capfloor_bp", "realized_vol_bp"]]
      .mean().round(2).to_string())

# %%
_grid = pd.DatetimeIndex(sorted(SCREENS["date"].unique()))
_f = go.Figure()
for _r in sorted(SCREENS["rank"].unique()):
    _ser = (SCREENS[SCREENS["rank"] == _r].set_index("date")["vs_model_capfloor_bp"]
            .reindex(_grid))
    _f.add_trace(go.Scatter(x=_ser.index, y=_ser.values, mode="lines+markers",
                            name=f"rank {_r}", connectgaps=False,
                            marker=dict(size=4)))
_f.add_hline(y=0.0, line=dict(color="#666", dash="dot"))
_f.update_layout(
    title="Vol-market dislocation: observed CA minus the cap/floor-calibrated "
          "model<br><sub>positive = the market pays too much for convexity = "
          "short convexity attractive. Weekly grid, connectgaps=False</sub>",
    xaxis_title="date", yaxis_title="vs model (bp)", height=CFG.fig_height,
    legend_title="pack rank")
_f

# %%
_sub2 = SCREENS.dropna(subset=["implied_vol_bp", "realized_vol_bp"])
_f = go.Figure()
for _lab, _col, _nm in (("implied_vol_bp", "#E45756", "implied (from observed CA)"),
                        ("sigma_capfloor_bp", "#4C78A8", "cap/floor (model input)"),
                        ("realized_vol_bp", "#54A24B", "3m realized (pack rate)")):
    _m2 = _sub2.groupby("rank")[_lab].mean()
    _f.add_trace(go.Scatter(x=_m2.index, y=_m2.values, mode="lines+markers",
                            name=_nm, line=dict(color=_col, width=3)))
_f.update_layout(
    title="Implied, cap/floor and realized vol by pack rank<br>"
          f"<sub>mean over the {len(_sub2):,} (date, pack) cells carrying all "
          "three. Implied above realized is the short-convexity case Citi's "
          "screen looks for</sub>",
    xaxis_title="pack rank (13 = Blues)", yaxis_title="normal vol (bp/yr)",
    height=CFG.fig_height)
_f

# %% [markdown]
# ## 9. Implied vs realized vs model, by pack colour

# %%
_colour = SCREENS.dropna(subset=["colour"])
BYCOLOUR = (_colour.groupby("colour")
            .agg(n=("ca_bp", "size"),
                 ca_bp=("ca_bp", "mean"),
                 model_ca_bp=("ca_model_capfloor_bp", "mean"),
                 vs_model_bp=("vs_model_capfloor_bp", "mean"),
                 implied_vol_bp=("implied_vol_bp", "mean"),
                 capfloor_vol_bp=("sigma_capfloor_bp", "mean"),
                 realized_vol_bp=("realized_vol_bp", "mean"),
                 impl_minus_rlzd_bp=("implied_minus_realized_bp", "mean")))
_order = [c for c in ("Reds", "Greens", "Blues") if c in BYCOLOUR.index]
BYCOLOUR = BYCOLOUR.loc[_order]
print("mean over the vol-panel window, by pack colour:")
print(BYCOLOUR.round(2).to_string())
print("\n(Whites and Golds are absent by construction: Whites is rank 1, below "
      "this screen's rank 5 floor; Golds is rank 17, where no listed ATM SR3 "
      "option exists. `realized_vol_bp` is NaN wherever the pack's own label "
      "has too few observed daily changes for the 63-business-day window.)")

# %% [markdown]
# ## 10. Artifacts

# %%
_written = {}
for _name, _obj in (("ca_valuation_valued_panel.parquet", VALUED),
                    ("ca_valuation_realized_vol.parquet", RV),
                    ("ca_valuation_screens.parquet", SCREENS),
                    ("ca_valuation_model_compare.parquet", BOTH)):
    if _obj is not None and len(_obj):
        _p = DATA / _name
        (_obj.reset_index() if isinstance(_obj.index, pd.DatetimeIndex) else _obj
         ).to_parquet(_p, index=False)
        _written[_name] = len(_obj)
MODELCMP.to_csv(DATA / "ca_valuation_citi_tieout.csv")
RVTIE.to_csv(DATA / "ca_valuation_realized_tieout.csv")
_summary = {
    "as_of": str(CFG.as_of),
    "ca_panel": _panel_path.name,
    "ca_tieout_corr": round(_corr, 4),
    "ca_tieout_max_abs_diff_bp": round(_maxd, 3),
    "ca_unchanged_max_abs_diff_bp": _dmax,
    "blues_ca_bp": round(_blues, 3),
    "vol_cells_total": int(len(VOLS)),
    "vol_cells_ok": _ok,
    "model_sigma_ratio_median": (round(float(_ok_rows["sigma_ratio"].median()), 4)
                                 if len(_ok_rows) else None),
    "model_ca_max_abs_err_bp": (round(float(_ok_rows["d_model_bp"].abs().max()), 3)
                                if len(_ok_rows) else None),
    "realized_tieout_median_ratio": round(float(_m["ratio"].median()), 4),
    "realized_tieout_corr": round(_corr_rv, 4),
    "realized_computable_2024_2026": int(_late["computable"].sum()),
    "network_calls_blocked": int(network_calls_blocked() - _NET0),
}
(DATA / "ca_valuation_summary.json").write_text(json.dumps(_summary, indent=2))
print(json.dumps(_summary, indent=2))
print("\nwritten:", {**_written, "ca_valuation_summary.json": 1})
print(f"\nOUTBOUND NETWORK CALLS MADE: 0 "
      f"({_summary['network_calls_blocked']:,} blocked by cache_only())")

# %% [markdown]
# ## 11. What is done, what is not, and one thing that needs fixing upstream
#
# **Done.**
#
# * The model CA is now calibrated to the **listed SR3 cap/floor surface over
#   each pack's own accrual window**, in the Citi convention
#   `1/2 σ² · mean(T1²)`. `vs_model_capfloor_bp` is a **vol-market dislocation**
#   and is labelled as one everywhere. The old cross-sectional caveat no longer
#   applies to it — it still applies to `strat2_sofr_convexity`'s own
#   `vs_model_bp`, which is unchanged and still fit-mode by default.
# * The **3m realized vol of the pack rate** exists, in bp/yr normal, directly
#   comparable to the implied vol, and ties to Citi's published column.
# * The screen ranks the three best short-convexity trades on all three metrics.
# * The observed CA is untouched, asserted exactly.
#
# **Not done, and why.**
#
# * **Golds (rank 17) has no model leg.** No listed ATM SR3 option exists four
#   years forward on any date probed. Citi's surface is almost certainly OTC SOFR
#   caps, which this repo does not carry.
# * **2019–2021 has no model leg.** Listed SR3 option history effectively begins
#   in 2022 on this machine: a month-grid probe over 2019–2021 returned
#   *"Could not resolve listed ATM option"* on almost every cell, and the 27
#   cells actually built for 2021-06 came back **0/27 ok**. That is a real
#   overlap loss, because 2019–2021 is where the CA panel is densest.
# * **2024–2026 has no realized vol.** The CA panel's own sparsity, not this
#   module's. The *model* leg does exist there (162/171 cells in 2024, 18/18 in
#   2025) — it is only the realized-vol column that is empty. Re-run when the
#   repair lands.
# * **The vol panel is weekly, not daily.** 2.1s per (date, pack) cell, measured;
#   the 1,179-cell weekly build took 2,022s, so a daily build over 2022–2026
#   would be a multi-hour job. Raise the grid density in a `scripts`-style build
#   if a daily series is needed; `build_capfloor_vol_panel` is resumable for
#   exactly that.
# * **The strike-convention sensitivity is 15 cells, not a panel**, and it is
#   computed outside the kernel because the alternate curve source uses an async
#   fetcher that does not work inside one (section 6).
# * **The front-pack model level does not match Citi's.** Reported as a 0.87
#   ratio at Reds converging to 0.98 at Blues, with the spot-starting-cap
#   alternative measured alongside. Neither reading closes it, which points at an
#   OTC-vs-listed vol basis rather than a convention error.
#
# **Required follow-up inside a file this work was not allowed to touch.**
#
# > `MDP/STIRCapFloors/STIRCapFloorMDP.py::_contracts_for_explicit_window` sizes
# > its candidate ladder as `ceil(window_days/75) + 4` contracts **from the front
# > of the curve**, then filters to the requested window. For a *forward-starting*
# > window the ladder ends before the window begins, so the strip comes back
# > short with no error. Measured on 2023-06-09: requesting the rank-9 pack
# > window (2025-06-18 .. 2026-06-17) by explicit `swap_start`/`swap_end`
# > returned **one leg instead of four**, and rank 13 returned zero with
# > *"No quarterly SFR contracts fall inside ..."*. The fix is to size the ladder
# > from the window's own end (`ceil((swap_end - as_of).days / 75) + 4`) rather
# > than its length. This module works around it by using the `expiry`/`tail`
# > request form, which resolves the strip with
# > `resolve_quarterly_contracts(start_index=expiry//3, count=tail//3)` and is
# > exact — but any other caller using the explicit-window form on a
# > forward-starting strip is silently getting a truncated cap.
#
# > **Second defect, same file.** `STIRCapFloorMDP._discount` (line ~96) falls
# > through to `handle[ql_date]` when the curve object has no `.discount`
# > method — which is the case for every **rateslib**-backed curve, including
# > `CITIVELO_EXCEL`, the source `Strat2Config` uses. rateslib's
# > `Curve.__getitem__` compares the key against `self.nodes.initial`, a
# > `datetime.datetime`, so a QuantLib `ql.Date` key raises
# > `TypeError: '<' not supported between instances of 'Date' and
# > 'datetime.datetime'`. This makes **`strike_convention="flat_swap_rate"` and
# > `weight_method="duration"` unusable on any rateslib curve** — the two code
# > paths that reach `_discount`. The fix is to convert in `_discount`
# > (`dt.datetime(ql_date.year(), ql_date.month(), ql_date.dayOfMonth())` on the
# > `handle[...]` branch) rather than in every caller. This module works around
# > it by defaulting to `atm_per_caplet`, which never touches `_discount`, and
# > by running the strike sensitivity on a QuantLib-backed curve with an
# > explicit control.
#
# > **Third, smaller: the IMM-date roll convention.** On an IMM date itself,
# > `packs.quarterly_imm_sequence(include_current=True)` keeps the contract whose
# > IMM date is today — it is still the live front contract — while the option
# > MDP's `_imm_cutoff` has already rolled past it. The two then disagree about
# > which four contracts a pack window contains, and the leg-identity guard
# > correctly refuses the cell. It costs one date per quarter. Whichever
# > convention is right, the two should agree; the guard should not have to
# > absorb it.
#
# One more, deliberately not done: **`RVUtils/ConvexityRV/__init__.py` was not
# updated to re-export `ca_valuation`.** This work was scoped to new files only
# and `__init__.py` is an existing one. Import the module directly
# (`from RVUtils.ConvexityRV import ca_valuation`) until whoever owns that file
# adds the names.
#
# Also worth recording: `holee.DEFAULT_CONVENTION` was observed changing from
# `citi` to `hull` and back while this notebook was being written. Every call
# site here passes the convention **explicitly** (`CV.CITI_CONVENTION`), and
# `tests/test_convexity_rv_ca_valuation.py::test_citi_convention_is_pinned_not_inherited`
# fails if that pinning is removed — a module that inherited the default would
# silently change every model CA by 10–25%.
