# %% [markdown]
# # CvxSuite daily screens — kink ledger + cross-wrapper breakeven board
#
# **Screens demo notebook** (no QDB engine run here, so the backtest
# convention's engine cells d–h are replaced by the screens set d'–h':
# assertion battery, two-book summary, styled board, kink-grid chart, gate
# lines). Pinned integration date **2026-08-21**. Everything runs offline:
# curve store (store-backed asserted), local swaption cube, cached BARCHART
# settles under the listed-cache guard — nothing fetches.
#
# **Frozen config (docs/cvxsuite/DESIGN.md section 6, as implemented):**
# KINK_GRID as `RVUtils/CvxSuite/grids.py` (17 points, spot 1y → 40y10y);
# xsec variant "spline", knots (1, 3, 7, 15, 27); walk-forward PCA n_pcs=2,
# window 756, monthly refit; z/pctl and OU windows 756 computed on the
# **composed micro-fly of adjusted levels** (`FLY_STATS_WEIGHTS = (-1, +2,
# -1)`; section 6's older phrase "on adjusted levels" predates the fly-level
# statistics fix and awaits a doc update); FPT sims 2000, steps 504, dt 1.0,
# seed 20260826; cost 1x = 2.3 bp package RT **on the belly=+2 ruler L =
# 2b − f − k (section 6a item 1)**; book clock `max_hold_bd = 63` — `p_hit =
# P(hit <= 63bd)` and `edge_bp = e_rev·p_hit − |carry|·min(e_fpt, 63) −
# cost` run on the frozen book's own exit clock (section 6a item 2; `e_fpt`
# and the `cens` = frac_censored column stay the uncapped 504-step
# diagnostics); BookGates re-signed for the receive-belly harvest side
# (section 6a item 5): harvest be_over_rv >= 1.17 AND zs >= −0.5 AND
# −rac_net > 0 (the `rac_net` COLUMN stays signed for the level-long,
# pay-belly holder — the harvest side earns −rac_net); dislocation
# |zs| >= 2.0 AND sign-agree AND tag "clean" AND edge >= 1.0 bp. Board
# universes: W1
# pairs {15Yx5Y/20Yx10Y, 10Yx10Y/20Yx10Y, 10Yx10Y/15Yx10Y}; W2 pack ranks
# {1, 5, 9, 13} (Whites/Reds/Greens/Blues, short-CA side); W3 adjacent
# KINK_GRID triples; W5 cube points {1yx10y, 5yx10y, 10yx10y}. All vols
# bp/day at the ledger boundary.
#
# **What this notebook is allowed to claim:** engine-certified reference
# numbers only — **no aliveness claims**. A `book` label is a screen
# classification, never a verdict (L-0088 stands: the dislocation book is
# machinery awaiting non-flow state data). Incumbent nulls, named: F3 xsec
# fade median 63d reversion +0.81..+1.14 bp vs >= 1.0 bp RT (pond equals
# boat); W4 rac harvest gross 0.397 < null 0.446 (duration in disguise);
# strat1 grid E[max SR | null] = 1.599. DSR accounting at the declared
# 4-config suite count lives in the engine notebooks; nothing here consumes
# a trial.
#
# **Integration references (int1_0 / c23_1 handovers as re-measured on the
# section-6a semantics — 2026-08-26 CLI re-run, this date, this machine):**
# screen 17 rows — books 1 harvest (20y5y) + 1 dislocation (15y5y) + 15
# none (the pre-6a harvest set {4y1y, 5y1y, 8y1y, 9y1y} dissolves under the
# re-signed gate: every one fails the receive-side carry floor −rac_net > 0),
# units median 4.30 bp/day, cube-support NaNs exactly {1y, 40y10y},
# PCA cos_prev ~0.9996/0.9994, CA sigma cells ffilled 68, frontiers
# value-carry slope -0.011 r2 0.002 / carry-vol slope -13.282 r2 0.528;
# board 13 rows (3 W1 + 4 W2 + 3 W3 + 3 W5), W1 be_over_rv
# 1.087/1.714/1.976. Printed values below are compared to these in-line;
# material drift is reported, not chased.

# %%
# (b) setup — offline discipline BEFORE any repo import, then paths, then the
# headless guard (nbclient runs under ipykernel, so figures render inline;
# a bare `python cvx_screens_daily.py` falls back to Agg).
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pathlib
import sys

REPO = pathlib.Path.cwd()
while not (REPO / "RVUtils").exists() and REPO != REPO.parent:
    REPO = REPO.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import matplotlib

if "ipykernel" not in sys.modules:
    matplotlib.use("Agg")

import dataclasses
import json
import time

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from IPython.display import display

pd.set_option("display.width", 260)
pd.set_option("display.max_columns", 60)
print(f"repo {REPO}")
print(f"ARBS_SUPABASE_ENABLED={os.environ['ARBS_SUPABASE_ENABLED']}")

# %% [markdown]
# ## Config — the frozen section-6 screen config and the pinned date

# %%
ASOF = pd.Timestamp("2026-08-21")  # pinned integration date

from RVUtils.CvxSuite import grids
from RVUtils.CvxSuite.kink_screen import (
    FLY_STATS_WEIGHTS,
    KinkScreenCfg,
    build_kink_screen,
)

CFG = KinkScreenCfg()
print(f"asof = {ASOF.date()}   FLY_STATS_WEIGHTS = {FLY_STATS_WEIGHTS}")
print(json.dumps(dataclasses.asdict(CFG), indent=1, default=str))

# %% [markdown]
# ## Inputs — leg history, offline store-backed pricer, swaption cube
#
# The pricer asserts are load-bearing: an offline `get_data` for a
# non-stored day silently BUILDS a curve (observed on a Saturday probe), so
# `from_curve_store is True` and `reference_date == asof` are checked HERE
# because the board receives this pricer by injection and its own
# `_build_pricer` checks are then bypassed.

# %%
LEG_PARQUET = REPO / "docs" / "cvxsuite" / "leg_history.parquet"
leg_hist = pd.read_parquet(LEG_PARQUET)
if not isinstance(leg_hist.index, pd.DatetimeIndex):
    leg_hist.index = pd.DatetimeIndex(pd.to_datetime(leg_hist.index))
print(f"leg history: {leg_hist.shape[0]} days x {leg_hist.shape[1]} legs, "
      f"{leg_hist.index[0].date()}..{leg_hist.index[-1].date()}")
assert ASOF in leg_hist.index, f"pinned asof {ASOF.date()} is not a leg-history date"

from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

t0 = time.perf_counter()
pricer = IRSwapsMDP(source="CITIVELO_EXCEL").get_data(
    {"curve_name": "USD-SOFR-1D", "timestamp": ASOF.date(), "offline": True})
assert pricer is not None, f"curve store miss for {ASOF.date()} (get_data returned None)"
meta = pricer.meta()
assert meta.get("from_curve_store") is True, (
    f"pricer for {ASOF.date()} is not store-backed (from_curve_store="
    f"{meta.get('from_curve_store')!r}); offline discipline forbids using it")
ref = pd.Timestamp(pricer.reference_date()).date()
assert ref == ASOF.date(), (
    f"pricer reference date {ref} != asof {ASOF.date()} - a substituted curve "
    "day would silently shift every number")
print(f"pricer: store-backed CITIVELO_EXCEL USD-SOFR-1D @ {ref} "
      f"({time.perf_counter() - t0:.1f}s)")

from Caching.swaption_cube_store import SwaptionCubeStore

store = SwaptionCubeStore.default()
print(f"cube store: {type(store).__name__} (default machine store)")

# %% [markdown]
# ## (c) The kink-ledger screen — built ONCE, reused by every display
#
# The CA sigma-panel build dominates the runtime (~25s: one
# `cube_atm_panel` read over the whole leg history). The frame below feeds
# the two-book summary AND the chart — `build_kink_screen` is never called
# twice. `df.attrs` are copied IMMEDIATELY after the build: pandas attrs are
# not guaranteed to survive sorts/slices/styles.

# %%
t0 = time.perf_counter()
screen = build_kink_screen(ASOF, leg_hist_bp=leg_hist, pricer=pricer,
                           cube_store=store, cfg=CFG)
t_screen = time.perf_counter() - t0

ATTRS = dict(screen.attrs)  # read IMMEDIATELY - attrs do not survive pandas ops

print(f"kink screen built in {t_screen:.1f}s - {len(screen)} rows, "
      f"ca_mode={ATTRS['ca_mode']}, sigma cells ffilled={ATTRS['ca_cells_ffilled']} "
      f"(int1_0 reference: 68)")

_LEDGER_COLS = ["tag", "adj_bp", "fly_bp", "residual_xsec", "residual_pca",
                "sign_agree", "zs", "pctl_3y", "carry_bp_day", "e_fpt_d",
                "p_hit", "frac_censored", "e_rev_bp", "rac_net",
                "gamma_usd_per_bp2",
                "sigma_be_bp_day", "be_status", "sigma_impl_bp_day",
                "sigma_rlzd_bp_day", "be_over_rv", "off_value_carry",
                "off_carry_vol", "edge_bp", "book"]
_REN = {"residual_xsec": "res_x", "residual_pca": "res_pca",
        "sign_agree": "agree", "carry_bp_day": "carry/d", "e_fpt_d": "e_fpt",
        "frac_censored": "cens",
        "e_rev_bp": "e_rev", "gamma_usd_per_bp2": "gamma",
        "sigma_be_bp_day": "sig_be", "be_status": "be_st",
        "sigma_impl_bp_day": "sig_impl", "sigma_rlzd_bp_day": "sig_rlzd",
        "off_value_carry": "off_vc", "off_carry_vol": "off_cv"}
ledger = screen[_LEDGER_COLS].copy()
ledger = ledger.loc[ledger["edge_bp"].abs()
                    .sort_values(ascending=False, na_position="last").index]
ledger.rename(columns=_REN).round(2)

# %% [markdown]
# ## The cross-wrapper breakeven board
#
# Same pricer / leg history / cube store injected (no rebuild). W2 walks the
# cached SR3 settle history under the listed-cache guard — a miss never
# fetches. Skip/note lines print inline; `board.attrs` copied immediately.

# %%
from RVUtils.CvxSuite.board import (
    CITI_ANCHOR_LINES,
    BoardConfig,
    board_priced,
    build_breakeven_board,
)

BCFG = BoardConfig(leg_hist=leg_hist, pricer=pricer, cube_store=store)
t0 = time.perf_counter()
board = build_breakeven_board(ASOF.date(), cfg=BCFG)
t_board = time.perf_counter() - t0

BOARD_ATTRS = dict(board.attrs)  # read IMMEDIATELY, same warning as the screen

wrapper_counts = board["wrapper"].value_counts().to_dict()
print(f"board built in {t_board:.1f}s - {len(board)} rows by wrapper: "
      f"{wrapper_counts} (c23_1 reference: 3 W1 + 4 W2 + 3 W3 + 3 W5)")

# %% [markdown]
# ## (d') Assertion battery
#
# The screens-notebook battery: the screen returned one row per KINK_GRID
# point with finite `sigma_rlzd` sitting inside the units guard, and the
# board priced at least W1.

# %%
from RVUtils.CvxSuite.vols import units_median_guard

# screen shape: one row per grid point, in grid order
grid_labels = [grids.leg_label(p) for p in grids.KINK_GRID]
assert len(screen) == len(grids.KINK_GRID), (
    f"screen returned {len(screen)} rows, expected {len(grids.KINK_GRID)}")
assert list(screen.index) == grid_labels, "screen index is not KINK_GRID order"

# sigma_rlzd: finite everywhere (endpoints included) and inside the units guard
rlzd = screen["sigma_rlzd_bp_day"].astype(float)
assert np.isfinite(rlzd).all(), (
    f"non-finite sigma_rlzd at {list(screen.index[~np.isfinite(rlzd)])}")
units_median_guard(rlzd)  # raises ValueError naming the median on a breach

# the board priced at least W1
w1 = board[board["wrapper"] == "W1"]
assert len(w1) > 0, "board priced no W1 rows"
assert np.isfinite(w1["sigma_be"].astype(float)).all(), "W1 sigma_be not finite"
assert board_priced(board), "board_priced is False - nothing priced"

n_theta = int(screen["theta_usd_day"].notna().sum())
assert n_theta > 0, "every fly theta is NaN - the curve expressed no package"
print(f"PASS: screen {len(screen)}/{len(grids.KINK_GRID)} rows in grid order; "
      f"sigma_rlzd finite 17/17, median {np.nanmedian(rlzd):.2f} bp/day in [0.5, 40] "
      f"(int1_0 reference: 4.30)")
print(f"PASS: {n_theta} interior flies priced theta (expected 15); "
      f"board priced {len(w1)} W1 rows, board_priced=True")

# %% [markdown]
# ## (e') Two-book summary
#
# A `book` label is a screen classification — never an aliveness claim.
# Section-6a reference at this date: harvest {20y5y}, dislocation {15y5y},
# 15 none. On a fly, harvest = RECEIVING the belly = SHORT the level, so the
# re-signed gate (6a item 5) wants a CHEAP belly (zs >= −0.5) that PAYS the
# receive side (−rac_net > 0): 20y5y qualifies (zs +1.65, −rac_net +6.25bp)
# and is also the one real-data row where the 63bd hold cap bites (e_fpt
# 64.3 > 63, so carry is charged over 63bd). The pre-6a harvest set {4y1y,
# 5y1y, 8y1y, 9y1y} — rows where the receive side BLEEDS — all fail the
# carry floor (−rac_net ≤ 0; 5y1y also fails zs >= −0.5). 9y1y's
# be_over_rv = inf (the never_cheap tenor-break package; the recorded
# books-layer question, shown unedited) still passes the be gate but no
# longer books harvest: the receive side bleeds 0.30bp.

# %%
_SUMMARY_COLS = ["tag", "zs", "pctl_3y", "be_over_rv", "rac_net", "e_rev_bp",
                 "p_hit", "e_fpt_d", "carry_bp_day", "edge_bp"]
picked = screen[screen["book"].isin(["harvest", "dislocation"])]
two_book = (picked[["book"] + _SUMMARY_COLS]
            .sort_values(["book", "edge_bp"], ascending=[True, False]))
n_none = int((screen["book"] == "none").sum())
print(f"harvest rows: {int((screen['book'] == 'harvest').sum())}   "
      f"dislocation rows: {int((screen['book'] == 'dislocation').sum())}   "
      f"none: {n_none}   (section-6a reference: 1 / 1 / 15 — pre-6a 4/1/12 "
      f"superseded by the re-signed harvest gate)")
two_book.round(2)

# %% [markdown]
# ## (f') Breakeven board, styled against the reference anchors
#
# Citi's published thresholds are CURVE-PAIR anchors: be_over_rv <= 0.80
# buys convexity (green), >= 1.17 sells it (orange). They were derived on
# DV01-neutral forward-curve pairs with the longer rate as ruler — **not
# validated on micro-flies**, and W3's ratio is not even the same units
# (parallel-shift breakeven over the fly's OWN level vol), so W3 highlights
# are expected to scream and mean nothing.

# %%
_NUM_COLS = ["theta_bp_yr", "gamma_usd_bp2", "sigma_be", "sigma_impl",
             "sigma_rlzd", "be_over_rv", "impl_over_rv", "z"]


def _anchor_style(col: pd.Series) -> list:
    out = []
    for v in col:
        if pd.isna(v):
            out.append("")
        elif v <= 0.80:
            out.append("background-color: #c8e6c9")   # buys convexity
        elif v >= 1.17:
            out.append("background-color: #ffe0b2")   # sells convexity
        else:
            out.append("")
    return out


for line in CITI_ANCHOR_LINES:
    print(line)
print("W3 caveat: be_over_rv mixes a PARALLEL-shift breakeven with the fly's own "
      "level vol; near-zero-gamma flies (15y5y/20y5y/25y5y) make it explosive - "
      "not comparable to W1's like-for-like ratio (c23_1 open risk 3)")
print("W2 caveat: the Whites CA-implied vol is inflated by its tiny time-weight "
      "window; Citi's own screen starts at rank 5 (c23_1 open risk 2)")

(board.style
 .format({c: "{:.3f}" for c in _NUM_COLS}, na_rep="")
 .apply(_anchor_style, subset=["be_over_rv"]))

# %% [markdown]
# ## (g') The kink grid — adjusted forward curve, residual bars, book labels
#
# Left axis: the convexity-adjusted forward curve (quoted + Ho-Lee CA)
# against the fit abscissa `k = fwd + tenor/2`; the quoted curve is dashed
# underneath, so the widening wedge at the long end IS the CA. Right axis:
# per-point cross-sectional spline residual (`res_x`, bp; > 0 = cheap), bars
# coloured by book. Shaded zones: meeting (fwd < 2y) and convexity
# (fwd >= 20y) — points the books refuse by tag.

# %%
from matplotlib.patches import Patch

fig, ax = plt.subplots(figsize=(13, 6.5))
k = screen["k_coord"].to_numpy(dtype=float)

ax.plot(k, screen["adj_bp"], "-o", color="tab:blue", lw=1.8, ms=4,
        label="adjusted forward (quoted + CA), bp", zorder=3)
ax.plot(k, screen["level_bp"], "--", color="tab:blue", lw=1.0, alpha=0.45,
        label="quoted forward, bp", zorder=2)
ax.set_xlabel("k = fwd + tenor/2 (years)")
ax.set_ylabel("forward par rate (bp)")
ax.set_xticks(k)
ax.set_xticklabels(screen.index, rotation=75, fontsize=8)

for tag, colr in (("meeting", "tab:cyan"), ("convexity", "tab:purple")):
    kk = screen.loc[screen["tag"] == tag, "k_coord"]
    if len(kk):
        ax.axvspan(kk.min() - 0.6, kk.max() + 0.6, color=colr, alpha=0.07)
        ax.text((kk.min() + kk.max()) / 2, ax.get_ylim()[1], tag, ha="center",
                va="top", fontsize=8, color=colr, alpha=0.9)

_BOOK_COLOR = {"harvest": "tab:orange", "dislocation": "tab:red", "none": "0.78"}
ax2 = ax.twinx()
ax2.bar(k, screen["residual_xsec"], width=0.9,
        color=[_BOOK_COLOR[b] for b in screen["book"]], alpha=0.75, zorder=1)
ax2.axhline(0.0, color="0.4", lw=0.8)
ax2.set_ylabel("cross-sectional spline residual res_x (bp; > 0 = cheap)")
for lab, r in screen.iterrows():
    if r["book"] != "none":
        y = r["residual_xsec"]
        ax2.annotate(f"{lab}\n{r['book']}", (r["k_coord"], y), fontsize=8,
                     ha="center", va="bottom" if y >= 0 else "top",
                     color=_BOOK_COLOR[r["book"]], fontweight="bold")

handles, labels_ = ax.get_legend_handles_labels()
handles += [Patch(color=_BOOK_COLOR["harvest"], alpha=0.75, label="res_x - harvest"),
            Patch(color=_BOOK_COLOR["dislocation"], alpha=0.75, label="res_x - dislocation"),
            Patch(color=_BOOK_COLOR["none"], alpha=0.75, label="res_x - none")]
ax.legend(handles=handles, loc="upper left", fontsize=8)
ax.set_title(f"KINK_GRID {ASOF.date()} - adjusted forward curve, spline residual "
             "bars, book labels (screen classification, not a verdict)")
fig.tight_layout()
plt.show()

# %% [markdown]
# ## (h') Gate lines
#
# The CLI's `=== GATE ... ===` lines, rebuilt from the LIBRARY gate
# functions and the immediately-captured `ATTRS` — plus the eigenvector
# continuity gate on the walk-forward PCA (the thresholded check the recon
# found missing everywhere), and the board's skip/note ledger.

# %%
from RVUtils.CvxSuite import gates as G

try:
    units_median_guard(rlzd)
    print(f"=== GATE units_median_guard(sigma_rlzd) === PASS  "
          f"median={np.nanmedian(rlzd):.2f} bp/day in [0.5, 40]")
except ValueError as exc:
    print(f"=== GATE units_median_guard(sigma_rlzd) === FAIL  {exc}")

dg = G.degeneracy_gate(rlzd)
fails = list(screen.index[~dg])
print(f"=== GATE degeneracy (sigma_rlzd >= 0.25 bp/day) === "
      f"{int(dg.sum())}/{len(screen)} pass" + (f"  FAILING: {fails}" if fails else ""))

nan_impl = sorted(screen.index[screen["sigma_impl_bp_day"].isna()])
expected_nan = {"1y", "40y10y"}
note = ("as designed (1y: expiry 0 < 1M axis; 40y10y: expiry 40 > 30Y axis)"
        if set(nan_impl) == expected_nan
        else f"UNEXPECTED (design expects exactly {sorted(expected_nan)})")
print(f"=== GATE cube support === {len(nan_impl)} NaN sigma_impl of {len(screen)}: "
      f"{nan_impl} - {note}")

lev = ATTRS["fit_diag"]["leverage"]
hi = ", ".join(f"k={kk:g}: h={v:.3f}" for kk, v in sorted(lev.items()) if kk >= 27.0)
print(f"=== GATE spline leverage (k >= 27, cubic extension) === {hi}  "
      f"(model_dof={ATTRS['fit_diag']['model_dof']:.2f})")

pinfo = ATTRS["pca_info"]
cos_prev = pinfo.get("cos_prev", {})
print(f"=== CA === mode={ATTRS['ca_mode']}  sigma cells ffilled="
      f"{ATTRS['ca_cells_ffilled']}  pca refits={pinfo.get('n_refits')}  "
      f"last refit={pinfo.get('last_refit')}")
if cos_prev:
    egg = G.eigenvector_gap_gate(cos_prev)
    print(f"=== GATE eigenvector continuity (|cos| >= {egg['min_cos']:.2f}) === "
          f"{'PASS' if egg['pass'] else 'FAIL'}  per_pc={egg['per_pc']}  "
          f"worst={egg['worst_pc']} |cos|={egg['worst_cos']:.4f} "
          f"(int1_0 reference: 0.9996/0.9994)")
else:
    print("=== GATE eigenvector continuity === no refit history (first month)")

fvc, fcv = ATTRS["frontier_value_carry"], ATTRS["frontier_carry_vol"]
print(f"=== frontiers === value-carry slope={fvc['slope']:.3f} r2={fvc['r2']:.3f} "
      f"n={fvc['n']:.0f} | carry-vol slope={fcv['slope']:.3f} r2={fcv['r2']:.3f} "
      f"n={fcv['n']:.0f}  (int1_0 reference: -0.011/0.002 and -13.282/0.528)")
if ATTRS.get("leg_roll_errors"):
    print(f"=== WARN leg_roll errors === {ATTRS['leg_roll_errors']}")

print(f"=== board === skips={BOARD_ATTRS.get('skips') or '(none)'}")
for n in BOARD_ATTRS.get("notes", []):
    print(f"    note: {n}")
print("board units guard: enforced INSIDE build_breakeven_board (split "
      "populations - sigma_impl all rows, sigma_rlzd W1/W2/W5 only; a breach "
      "raises, so a returned board has passed)")

# %% [markdown]
# ## Diagnostics — `df.attrs`, read immediately
#
# Pandas `attrs` are not guaranteed to survive derived frames (sorts,
# slices, styles), so both builds copied them into plain dicts in the SAME
# cell that built the frame. Below: what a derived frame actually carries in
# this pandas version (an empty or version-dependent set — the reason for
# the immediate copy), then the three diagnostic payloads as frames.

# %%
derived = screen.sort_values("edge_bp")
print(f"pandas {pd.__version__}: screen ATTRS keys (copied at build): {sorted(ATTRS)}")
print(f"derived (sorted) frame attrs keys: {sorted(derived.attrs.keys()) or '(empty)'}")

print("\nfit_diag: per-k spline leverage (trace H = model dof "
      f"{ATTRS['fit_diag']['model_dof']:.2f}, resid dof "
      f"{ATTRS['fit_diag']['resid_dof']:.2f}, knots {ATTRS['fit_diag']['knots_used']})")
lev_df = pd.DataFrame({"k_coord": list(lev.keys()), "leverage": list(lev.values())})
lev_df["point"] = grid_labels
display(lev_df.set_index("point").round(3).T)

print("pca_info: last refit "
      f"{pinfo.get('last_refit')} of {pinfo.get('n_refits')} refits; "
      f"cos_prev={ {kk: round(v, 4) for kk, v in cos_prev.items()} }; "
      f"explained={ {kk: round(v, 4) for kk, v in pinfo.get('explained', {}).items()} }")

frontiers = pd.DataFrame([fvc, fcv],
                         index=["value-carry (res_x on leg roll)",
                                "carry-vol (leg roll on sigma_impl)"])
display(frontiers.round(3))

axes = ATTRS.get("cube_axes_asof")
if axes is not None:
    print(f"cube axes at asof: expiries {len(axes[0])} nodes "
          f"{axes[0][0]:g}..{axes[0][-1]:g}y, "
          f"tenors {len(axes[1])} nodes {axes[1][0]:g}..{axes[1][-1]:g}y")
else:
    print("cube axes at asof: NONE (cube day absent - sigma_impl degraded to NaN)")
print(f"total runtime: screen {t_screen:.1f}s + board {t_board:.1f}s "
      f"(budget: < 3 min)")
