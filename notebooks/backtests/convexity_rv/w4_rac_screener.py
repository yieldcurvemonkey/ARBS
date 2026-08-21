# %% [markdown]
# # W4 — the ultra-long risk-adjusted-carry screen, LIVE
#
# > *"the ratio of the daily breakeven — the daily move in rates that yields a
# > convexity gain offsetting a negative daily carry — to realized daily
# > volatility. **Three most attractive curves by each metric are marked in
# > red.**"*
# >
# > — Citi, *Alert: Taking profits on delta-hedged 15y5y/20y10y flatteners*,
# > close 04-Dec-2019
#
# This is Citi's own table, reproduced on the latest curve this repo holds:
# fifteen USD ultra-long forward pairs by eight columns, with the three most
# attractive by each metric marked.
#
# ## Read this first: the backtest verdict is DEAD
#
# The rule built on this screen was measured in
# `w4_rac_backtest.ipynb` and it does not work. Section 9 **re-derives** the
# numbers here rather than quoting them: gross Sharpe **0.397** against an
# `E[max SR | null]` of **0.462** at twelve trials. The gross number — before a
# cent of cost — sits below what a zero-edge strategy would be expected to
# produce from the search that found it.
#
# So this notebook is **a market read, not a recommendation.** The screen
# reproduces Citi's published cells in rank (section 2) and is worth looking at
# as a description of where the ultra-long curve is. Nothing in it is evidence
# that trading it makes money, and section 9 is evidence that it does not.

# %%
import datetime as dt
import importlib.util
import json
import os
import pathlib
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

REPO = pathlib.Path.cwd()
while not (REPO / "RVUtils").exists() and REPO != REPO.parent:
    REPO = REPO.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import numpy as np
import pandas as pd

import plotly.io as pio
pio.renderers.default = "plotly_mimetype+notebook_connected"

from IPython.display import display

import RVUtils.ConvexityRV.strat3_strikeless_vol as S3
from RVUtils.ConvexityRV import rac_backtest as B
from RVUtils.ConvexityRV import rac_signal as R
from RVUtils.ConvexityRV.strat1_threeway import expected_max_sharpe_under_null

DATA = REPO / "notebooks" / "data" / "convexity_rv"
pd.set_option("display.width", 220, "display.max_columns", 40)
print(f"repo {REPO}")

# %% [markdown]
# ## 1. The config
#
# Every knob, and the reason for its value. This is deliberately the **same**
# `RacConfig` the backtest ran, so "what the rule says today" in section 6 is
# the rule that was measured in section 9 and not a nearby cousin of it.
#
# `enter_pct` / `steepener_pct` are percentiles of the pair's *own* trailing
# `rac`, not Citi's absolute 0.8 / 1.0. Section 5 is the measurement that forced
# that, and it is the single most important cell in this notebook.

# %%
CONFIG = R.RacConfig(
    lookback_days=756,     # 3y, matching Citi's own "3y ZS" column
    enter_pct=0.80,        # flattener when risk-adjusted carry is unusually good
    exit_pct=0.35,         # position-level exit; NOT read by entry_state
    steepener_pct=0.20,    # the other side
    top_n=3,               # Citi marks "three most attractive" in red
    min_carry_bp=None,     # OFF: the carry SIGN is not reliable near zero
    start=dt.date(2021, 1, 1),   # backtest window, used only in §7 and §9
    end=dt.date(2026, 8, 20),
)
MIN_HOLD, MAX_HOLD = 21, 252     # the backtest's episode rules, re-used in §7/§9
print(json.dumps(CONFIG.to_dict(), indent=1, default=str))

# --- the data -------------------------------------------------------------
LEG = pd.read_parquet(DATA / "rac_leg_panel.parquet")
PANEL = pd.read_parquet(DATA / "rac_screen_panel.parquet")
PANEL["date"] = pd.to_datetime(PANEL["date"])

ASOF = PANEL["date"].max()
PANEL_START = PANEL["date"].min()
PAIR_ORDER = [f"{s}/{l}" for s, l in S3.PAIRS_15]

print(f"\nleg panel    {LEG.shape}  {LEG.index.get_level_values('date').min().date()}"
      f" .. {LEG.index.get_level_values('date').max().date()}"
      f"  ({LEG.index.get_level_values('date').nunique()} dates,"
      f" {LEG.index.get_level_values('leg').nunique()} legs)")
print(f"screen panel {PANEL.shape}  {PANEL_START.date()} .. {ASOF.date()}"
      f"  ({PANEL['date'].nunique()} dates, {PANEL['pair'].nunique()} pairs)")
print(f"\nASOF (latest available date in the panel) = {ASOF.date()}")

assert set(PANEL["pair"]) == set(PAIR_ORDER), "the panel is not Citi's 15-pair grid"
assert len(PAIR_ORDER) == 15

# %% [markdown]
# ## 2. Does the machine give the right answer to a question we already know?
#
# Citi's 04-Dec-2019 alert prints all eight columns for all fifteen pairs — **120
# published cells the code was never fitted to**. The published values live in
# `tests/test_convexity_rv_rac_screen.py`; they are loaded from that file here
# rather than retyped, so there is one copy of the answer key.
#
# The verdict is a **split: rank transfers, level does not.** That is not a
# footnote — it is the reason section 5 exists.

# %%
_spec = importlib.util.spec_from_file_location(
    "_rac_screen_key", REPO / "tests" / "test_convexity_rv_rac_screen.py")
_key = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_key)

TIE_DATE = pd.Timestamp(_key.ASOF)
tie = PANEL[PANEL["date"] == TIE_DATE].set_index("pair").loc[PAIR_ORDER]
assert len(tie) == 15, f"the panel does not cover the tie-out date {TIE_DATE.date()}"

CMP = pd.DataFrame({
    "citi_level": _key.PUB_LEVEL,  "our_level": tie["level_bp"].to_numpy(),
    "citi_carry": _key.PUB_CARRY,  "our_carry": tie["carry_1y_bp"].to_numpy(),
    "citi_be":    _key.PUB_BE,     "our_be":    tie["be_daily_analytic"].to_numpy(),
    "citi_rv":    _key.PUB_RV,     "our_rv":    tie["rlzd_vol_bp"].to_numpy(),
    "citi_ratio": _key.PUB_RATIO,  "our_ratio": tie["be_over_rv"].to_numpy(),
}, index=PAIR_ORDER)
print(f"Citi {TIE_DATE.date()}, 15 pairs, graded out of sample:\n")
print(CMP.round(3).to_string())

# %%
from scipy.stats import spearmanr

GRADE = []
for label, a, b, floor in [
    ("level_bp",          "citi_level", "our_level", 0.95),
    ("carry_1y_bp",       "citi_carry", "our_carry", 0.90),
    ("be_daily_analytic", "citi_be",    "our_be",    0.95),
    ("be_over_rv",        "citi_ratio", "our_ratio", 0.95),
]:
    rho = float(spearmanr(CMP[a], CMP[b]).statistic)
    off = float((CMP[b] - CMP[a]).mean())
    GRADE.append({"column": label, "spearman": rho, "mean_offset": off, "floor": floor})
GRADE = pd.DataFrame(GRADE)
print(GRADE.round(4).to_string(index=False))

for r in GRADE.itertuples():
    assert r.spearman > r.floor, (
        f"{r.column}: spearman {r.spearman:.4f} against Citi {TIE_DATE.date()} "
        f"fell below the pinned floor {r.floor}")

_our_max = float(CMP["our_ratio"].max())
_citi_ge1 = int((np.array(_key.PUB_RATIO) >= 1.0).sum())
_our_ge1 = int((CMP["our_ratio"] >= 1.0).sum())
print(f"\nOK: rank transfers (be_over_rv spearman "
      f"{GRADE.set_index('column').at['be_over_rv', 'spearman']:.4f});")
print(f"    level does not (mean offsets above; level "
      f"{GRADE.set_index('column').at['level_bp', 'mean_offset']:+.3f} bp).")
print(f"\non {TIE_DATE.date()}: Citi has {_citi_ge1}/15 pairs at or above her 1.0 "
      f"steepener threshold; we have {_our_ge1}/15, max {_our_max:.4f}.")
assert _citi_ge1 >= 2, "the published table is supposed to show both sides"
assert _our_ge1 == 0 and _our_max < 1.0, (
    f"our max ratio on {TIE_DATE.date()} is now {_our_max:.4f}; this notebook's "
    "section 5 argument is written around it being below 1.0 on this date")
print("\nNOTE ON A NUMBER YOU MAY HAVE SEEN ELSEWHERE: w4_rac_backtest quotes a max")
print(f"ratio of 0.747 on this date; the panel gives {_our_max:.4f}. The difference is")
print("the realised-vol source — screen_frame builds its own trailing vol from the")
print("rate history it is handed, the panel uses add_screen_stats' 252d window on")
print("the leg panel. Both are below 1.0, which is the claim being made.")

# %% [markdown]
# ## 3. The probes
#
# Two things are checked before any screen is printed: that the package sign
# convention is the one the screen assumes, and that the panel's own internal
# identities hold on the date being screened.
#
# ### 3.1 Sign probe
#
# A flattener pays the shorter leg and receives the longer one, so the front
# leg's PV01 must be positive, the back leg's negative, and the two must sum to
# zero. This is **read from the committed backtest run** rather than re-derived
# live: re-deriving it needs `IRSwapsMDP(source="CITIVELO_EXCEL")`, which drives
# Excel over COM, and this notebook has no other reason to touch a pricer.

# %%
RUN = json.loads((DATA / "rac_w4_run.json").read_text())
probe = RUN["sign_probe"]
print(json.dumps(probe, indent=1))
assert probe["is_flattener"], "bpv<0 is not a flattener on this engine"
assert probe["front_pv01"] > 0 > probe["back_pv01"]
assert abs(probe["sum"]) < 1.0, f"package is not DV01-neutral: {probe['sum']}"
print(f"\nOK: bpv<0 = pay front / receive back = FLATTENER, DV01-neutral to "
      f"{probe['sum']:.1e}")
print("PROVENANCE: rac_w4_run.json, the same run whose equity curves section 9 grades.")

# %% [markdown]
# ### 3.2 The panel's own identities, on ASOF
#
# The screen is arithmetic on top of the leg panel. If that arithmetic has
# drifted, every column below is wrong in a way no eyeball catches.

# %%
snap = PANEL[PANEL["date"] == ASOF].set_index("pair").loc[PAIR_ORDER]

_lvl_err = float((snap["level_bp"]
                  - (snap["long_rate_bp"] - snap["short_rate_bp"])).abs().max())
_ratio_err = float((snap["be_over_rv"]
                    - snap["be_daily_analytic"] / snap["rlzd_vol_bp"]).abs().max())
_gamma = snap["gamma_ratio"]
_trunc_ok = bool(((snap["be_daily_analytic"] == 0)
                  == (snap["carry_1y_bp"] >= 0)).all())
_rv_by_long = snap.groupby("long_leg")["rlzd_vol_bp"].nunique()

print(f"level identity   max |level_bp - (long - short)|   {_lvl_err:.3e} bp")
print(f"ratio identity   max |be_over_rv - be/rv|          {_ratio_err:.3e}")
print(f"gamma_ratio      repriced / (2*dM/1e4*DV01)        "
      f"{_gamma.min():.4f} .. {_gamma.max():.4f}")
print(f"breakeven truncates exactly where carry >= 0       {_trunc_ok}")
print(f"realised vol is keyed on the LONG leg              "
      f"{int(_rv_by_long.max())} distinct vol per long leg "
      f"({len(_rv_by_long)} long legs)")

assert _lvl_err < 1e-9, "level_bp is not long - short on ASOF"
assert _ratio_err < 1e-9, "be_over_rv is not be_daily_analytic / rlzd_vol_bp on ASOF"
assert (_gamma - 1.0).abs().max() < 0.10, (
    "the repriced package gamma has drifted more than 10% from the dM/1e4 "
    "reconstruction; the breakeven column is built on that reconstruction")
assert _trunc_ok, "Citi's truncation rule (be = 0 when carry >= 0) does not hold"
assert int(_rv_by_long.max()) == 1, (
    "pairs sharing a long leg must show the same realised vol — that convention "
    "is how the column was pinned against Citi's published tables")
print("\nOK: the four identities the screen rests on all hold on ASOF.")

# %% [markdown]
# ## 4. Citi's screen, on the latest curve we hold
#
# Eight columns, fifteen pairs, **three most attractive by each metric marked**.
#
# One column is not Citi's. She prints a **"ZS since 2000"**; this cannot be
# reproduced and section 8 gives the two independent reasons why. The column
# below is labelled by the window it actually uses.
#
# ### Which direction is "attractive"
#
# | column | attractive | source of the polarity |
# |---|---|---|
# | curve bp | **high** (less negative) | documented: `level_from_rates` — *"A HIGHER (less negative) level is a steeper curve and a more attractive flattener entry"* |
# | ZS 1y / 3y / long | **high** | documented: same, *"which is why the z-score's polarity is 'high = attractive'"* |
# | 1y carry bp | **high** | RECONSTRUCTION — less negative carry is less to pay for the convexity |
# | daily BE bp | **low** | RECONSTRUCTION — a smaller move is needed for convexity to cover the carry |
# | 1y rlzd vol bp | **high** | RECONSTRUCTION — more vol makes a given breakeven easier to clear |
# | BE / rlzd vol | **low** | documented: `screen_frame` — *"the decision statistic. Lower = the embedded convexity is cheaper = more attractive flattener"* |
#
# Four of the eight polarities are reconstructions, not published rules. The
# marks are therefore **reported and not asserted on**; what is asserted is that
# exactly three pairs are marked per column, which checks this code and not
# Citi's intent.

# %%
LONG_Z_LABEL = f"ZS s{PANEL_START.year}"

SCREEN_COLS = {                    # display name -> (panel column, polarity)
    "curve bp":     ("level_bp", +1),
    "ZS 1y":        ("zs_1y", +1),
    "ZS 3y":        ("zs_3y", +1),
    LONG_Z_LABEL:   ("zs_full", +1),
    "carry 1y bp":  ("carry_1y_bp", +1),
    "BE daily bp":  ("be_daily_analytic", -1),
    "rlzd vol bp":  ("rlzd_vol_bp", +1),
    "BE/vol":       ("be_over_rv", -1),
}

SCREEN = pd.DataFrame({disp: snap[col] for disp, (col, _) in SCREEN_COLS.items()},
                      index=PAIR_ORDER)


def _marks(frame: pd.DataFrame, top_n: int) -> pd.DataFrame:
    """Boolean mask of the ``top_n`` most attractive cells in each column."""
    out = pd.DataFrame(False, index=frame.index, columns=frame.columns)
    for disp, (_col, pol) in SCREEN_COLS.items():
        s = frame[disp].astype(float) * pol
        winners = s.nlargest(top_n).index
        out.loc[winners, disp] = True
    return out


MARK = _marks(SCREEN, CONFIG.top_n)

assert SCREEN.notna().all().all(), (
    f"the screen has NaNs on {ASOF.date()}:\n{SCREEN.isna().sum()}")
for c in SCREEN.columns:
    assert int(MARK[c].sum()) == CONFIG.top_n, (
        f"column {c!r} marked {int(MARK[c].sum())} pairs, expected {CONFIG.top_n}")

TXT = pd.DataFrame({c: [f"{v:8.2f}" + ("*" if m else " ")
                        for v, m in zip(SCREEN[c], MARK[c])]
                    for c in SCREEN.columns}, index=SCREEN.index)
print(f"Citi's screen, USD ultra-long forward pairs, close {ASOF.date()}")
print(f"(* = one of the three most attractive by that metric; "
      f"'{LONG_Z_LABEL}' = expanding z-score since {PANEL_START.date()})\n")
print(TXT.to_string())

# %% [markdown]
# The same table with the marks **in red**, which is how Citi prints it.

# %%
try:
    def _red(df: pd.DataFrame) -> pd.DataFrame:
        return MARK.map(lambda b: "color: #c1121f; font-weight: 600" if b else "")

    display(SCREEN.style
            .apply(_red, axis=None)
            .format("{:.2f}")
            .set_caption(f"Three most attractive by each metric, {ASOF.date()}"))
except Exception as exc:                                            # noqa: BLE001
    print(f"Styler unavailable ({type(exc).__name__}: {exc}); "
          "the plain-text table above carries the same marks.")

# %%
print("the three most attractive by each metric:\n")
for c in SCREEN.columns:
    picks = list(MARK.index[MARK[c]])
    order = SCREEN.loc[picks, c].sort_values(
        ascending=(SCREEN_COLS[c][1] < 0))
    print(f"{c:>12}   " + ",  ".join(f"{p} ({v:.2f})" for p, v in order.items()))

# %% [markdown]
# ### 4.1 The columns disagree, and that is what the screen is for
#
# Citi prints eight columns rather than one because they measure different
# things: the level columns say how steep the curve is against its own history,
# the carry columns say what it costs to hold the flattener. When they point at
# different pairs, the screen is showing a trade-off and not a signal.

# %%
n_marks = MARK.sum(axis=1).sort_values(ascending=False)
print("how many of the eight columns mark each pair:\n")
print(n_marks[n_marks > 0].to_string())

_lvl_set = set(MARK.index[MARK["curve bp"]]) | set(MARK.index[MARK["ZS 3y"]])
_cry_set = set(MARK.index[MARK["carry 1y bp"]]) | set(MARK.index[MARK["BE/vol"]])
print(f"\nlevel columns (curve bp, ZS 3y) mark : {sorted(_lvl_set)}")
print(f"carry columns (carry, BE/vol)  mark : {sorted(_cry_set)}")
print(f"overlap                              : {sorted(_lvl_set & _cry_set)}")

assert int(n_marks.max()) < len(SCREEN.columns), (
    "one pair is now the most attractive on all eight metrics; the trade-off "
    "this section describes has collapsed and section 12 should say so")
print(f"\nNo pair is marked on all eight columns (the most any pair gets is "
      f"{int(n_marks.max())}).")
print("The level columns point at the 10Yx10Y family — steep against its own")
print("history, i.e. an attractive place to PUT ON a flattener. The carry columns")
print("point at the 15Yx5Y family — the cheapest place to HOLD one. Section 6's")
print("rule reads only the carry side, which is why it ends up SHORT the pairs")
print("the level columns like most. Both readings are in the table; only one is")
print("in the rule.")

# %% [markdown]
# ## 5. The continuous statistic — and why Citi's thresholds do not transfer
#
# Citi keys her decisions on **absolute levels** of `BE/vol`: exit the flattener
# around **0.8**, enter the steepener above **1.0**. Two measurements say those
# numbers cannot be carried onto this curve.
#
# **(a) The published ratio is truncated.** Citi sets the breakeven to zero
# whenever carry is non-negative, so `BE/vol` is exactly 0 on a large fraction of
# the sample — and a time-series percentile of a flat-zero series is undefined
# exactly where a carry-keyed rule wants to fire.
#
# **(b) Her threshold is a regime dial on our curve, not a screen.** On
# 2019-12-04 *none* of the fifteen pairs reached 1.0. Today almost all of them
# do. A rule reading "steepener above 1.0" would have fired on **nothing** then
# and on **nearly everything** now. That is the same degeneracy that made strat 1
# *"a permanently-on flattener, not a timing rule"*, arriving from the other end.
#
# The traded statistic is therefore the continuous one underneath the ratio:
#
# $$\mathrm{rac} = \frac{\text{carry}_{1y}\ (\mathrm{bp})}
#                        {\sigma_{\text{realised}}\ (\mathrm{bp/day}) \times \sqrt{252}}$$
#
# signed, smooth through zero, never truncated — and it is on a **different
# scale entirely**: it never comes near 1.0 anywhere in this sample.

# %%
sat = R.saturation_table(PANEL)
print("saturation of the PUBLISHED ratio, and where it sits vs Citi's 1.0:\n")
reg = PANEL.assign(year=PANEL["date"].dt.year).groupby("year").agg(
    cells=("be_over_rv", "size"),
    ratio_ge_0p8=("be_over_rv", lambda s: float((s >= 0.8).mean())),
    ratio_ge_1p0=("be_over_rv", lambda s: float((s >= 1.0).mean())),
    ratio_max=("be_over_rv", "max"),
    rac_min=("rac", "min"),
    rac_max=("rac", "max"),
)
print(sat[["cells", "carry>=0", "be_truncated_to_0", "rac_exactly_0"]]
      .join(reg[["ratio_ge_0p8", "ratio_ge_1p0", "ratio_max", "rac_min", "rac_max"]])
      .round(4).to_string())

assert float(sat["be_truncated_to_0"].max()) > 0.40, (
    "the published ratio's truncation should be material in at least one year")
assert (sat["rac_exactly_0"].fillna(0.0) == 0).all(), (
    "the continuous statistic must never be exactly zero")
print(f"\n(a) OK: the published ratio is truncated on up to "
      f"{sat['be_truncated_to_0'].max():.1%} of a year; rac never is.")

# %%
ratio_today = snap["be_over_rv"]
n_ge1_today = int((ratio_today >= 1.0).sum())
n_ge08_today = int((ratio_today >= 0.8).sum())

print(f"Citi's steepener threshold (BE/vol >= 1.0), applied literally:")
print(f"  {TIE_DATE.date()}   {_our_ge1:>2}/15 pairs fire   (max {_our_max:.3f})")
print(f"  {ASOF.date()}   {n_ge1_today:>2}/15 pairs fire   "
      f"(min {ratio_today.min():.3f}, max {ratio_today.max():.3f})")
print(f"Citi's exit level     (BE/vol >= 0.8):")
print(f"  {ASOF.date()}   {n_ge08_today:>2}/15 pairs are already past it")

assert n_ge1_today >= 8, (
    f"only {n_ge1_today}/15 pairs clear Citi's 1.0 today; the be/rv regime has "
    "moved again and section 5's 'all-off then, all-on now' framing needs "
    "re-deriving on the current sample")
assert n_ge08_today == 15, (
    f"{n_ge08_today}/15 pairs clear Citi's 0.8 exit level today; this section "
    "claims the whole cross-section is past it")
print(f"\n(b) OK: 0/15 then, {n_ge1_today}/15 now. The printed threshold is an "
      "all-or-nothing\n    regime dial on this curve, in both directions.")

# %%
_rac_max = float(PANEL["rac"].max())
_rac_absmax = float(PANEL["rac"].abs().max())
print(f"the CONTINUOUS statistic, all {len(PANEL):,} cells "
      f"({PANEL_START.date()} .. {ASOF.date()}):")
print(f"  min {PANEL['rac'].min():+.4f}   max {_rac_max:+.4f}   "
      f"|max| {_rac_absmax:.4f}")
print(f"  cells with rac >= 1.0 : {int((PANEL['rac'] >= 1.0).sum())}")
print(f"  cells with |rac| >= 1.0: {int((PANEL['rac'].abs() >= 1.0).sum())}")

assert int((PANEL["rac"] >= 1.0).sum()) == 0, (
    "some cell's rac now reaches Citi's 1.0")
assert int((snap["rac"] >= 1.0).sum()) == 0, (
    "some pair's rac reaches Citi's 1.0 on ASOF")
assert _rac_absmax < 0.5, (
    f"|rac| now reaches {_rac_absmax:.4f}; it has been under 0.25 on this sample "
    "and section 5 leans on the scale gap")
print(f"\nOK: NO pair, on ANY date in this sample, reaches 1.0 on rac — the")
print(f"    largest value anywhere is {_rac_max:+.4f}. Citi's 0.8 / 1.0 are numbers")
print("    about a DIFFERENT quantity (a bp/bp ratio); rac is carry over annualised")
print("    vol. They are not comparable, which is exactly why the rule below is")
print("    keyed on rac's own trailing PERCENTILE and not on her levels.")

# %% [markdown]
# ### 5.1 `rac` and its trailing percentile, today
#
# `rac_lag` is the value the rule actually reads on ASOF — information through
# **t−1**, per the house rule enforced inside `build_signal_panel`. `rac_pct` is
# that lagged value's percentile within the pair's own trailing
# `lookback_days`-day window, so it is comparable across pairs in a way the raw
# level is not.

# %%
SIG = R.build_signal_panel(PANEL, CONFIG)
STATE_ALL = R.entry_state(SIG, CONFIG)

today = SIG.xs(ASOF, level="date").loc[PAIR_ORDER]
state_today = STATE_ALL.xs(ASOF, level="date").loc[PAIR_ORDER]
ranks_today = R.side_ranks(SIG, CONFIG).xs(ASOF, level="date").loc[PAIR_ORDER]

CONT = pd.DataFrame({
    "rac (t)": today["rac"],
    "rac_lag (t-1)": today["rac_lag"],
    "rac_pct": today["rac_pct"],
    "x-rank": today["rac_xrank"],
    "BE/vol": snap["be_over_rv"],
}).sort_values("rac_pct")
print(f"rac and its {CONFIG.lookback_days}-day trailing percentile, {ASOF.date()}\n")
print(CONT.round(4).to_string())

assert int(today["rac_pct"].notna().sum()) == 15, (
    "some pair has no trailing percentile on ASOF; the rule cannot read it")
print(f"\nrac_pct range today: {today['rac_pct'].min():.4f} .. "
      f"{today['rac_pct'].max():.4f}")
assert float(today["rac_pct"].max()) <= CONFIG.steepener_pct, (
    "not every pair is below the steepener bar today; section 6's reading that "
    "the ENTIRE cross-section sits at its own 3y low needs re-deriving")
print(f"Every one of the fifteen pairs is at or below the {CONFIG.steepener_pct:.0%}"
      " percentile of its OWN\n3y history. The whole cross-section is at a "
      "risk-adjusted-carry low.")

# %% [markdown]
# ## 6. What the rule says today
#
# `entry_state` needs **both** axes: a percentile that says whether and which
# side, and a within-side cross-sectional rank that says which pair. Today the
# percentile axis admits all fifteen pairs to the steepener side, so the rank is
# doing all of the selection.

# %%
n_flat = int((state_today == 1).sum())
n_steep = int((state_today == -1).sum())
n_off = int((state_today == 0).sum())

READ = pd.DataFrame({
    "state": state_today.map({1: "FLATTENER", -1: "steepener", 0: "-"}),
    "rac_pct": today["rac_pct"],
    "rank_in_steep": ranks_today["rank_in_steep"],
    "rank_in_flat": ranks_today["rank_in_flat"],
    "carry 1y bp": snap["carry_1y_bp"],
    "curve bp": snap["level_bp"],
}).sort_values("rank_in_steep")
print(f"THE RULE ON {ASOF.date()}:  {n_flat} flattener(s), {n_steep} steepener(s), "
      f"{n_off} flat\n")
print(READ.round(4).to_string())

live = list(state_today.index[state_today == -1])
print("\nlive steepeners:" if live else "\nno live positions")
for p in live:
    print(f"  {p:20} rac_pct {today.at[p, 'rac_pct']:.4f}   "
          f"carry {snap.at[p, 'carry_1y_bp']:+.2f} bp   "
          f"curve {snap.at[p, 'level_bp']:+.1f} bp")

assert n_flat + n_steep + n_off == 15
assert n_steep == CONFIG.top_n and n_flat == 0, (
    f"the rule reads {n_flat} flatteners / {n_steep} steepeners on {ASOF.date()}; "
    "this section is written around 0 and top_n")

_one_sided = set(R.ONE_SIDED_FAMILY)
assert set(live) <= _one_sided, (
    "a live steepener sits outside the structurally one-sided family; that is a "
    "different reading from the one section 7.1 gives")
print(f"\nAll {len(live)} live positions are in ONE_SIDED_FAMILY — see 7.1. That is")
print("not a coincidence: those are the pairs whose carry is almost never positive,")
print("so they sit at the bottom of the rac cross-section by construction, and the")
print("within-side rank picks the bottom three.")

# %% [markdown]
# ## 7. Two structural facts the screen does not print
#
# ### 7.1 The `10Yx10Y` family is structurally one-sided
#
# > *"The `10Yx10Y` family is **structurally one-sided** on this sample: a rule
# > keyed on carry can only ever say 'flattener' for it. It is retained and
# > reported, not silently traded as though two-sided."*
# >
# > — `RVUtils/ConvexityRV/rac_signal.py` module docstring

# %%
cpf = R.carry_positive_fraction(PANEL)
tbl = pd.DataFrame({"carry>0 frac": cpf})
tbl["one_sided"] = [p in _one_sided for p in tbl.index]
print(f"fraction of the {PANEL['date'].nunique():,} days each pair carries "
      f"POSITIVELY:\n")
print(tbl.round(4).to_string())

_os_vals = cpf[list(R.ONE_SIDED_FAMILY)]
print(f"\nONE_SIDED_FAMILY ({len(R.ONE_SIDED_FAMILY)} pairs): "
      f"{_os_vals.min():.2%} .. {_os_vals.max():.2%} of days")
print(f"everything else            : {cpf[~cpf.index.isin(_one_sided)].min():.2%}"
      f" .. {cpf[~cpf.index.isin(_one_sided)].max():.2%}")

assert float(_os_vals.max()) < 0.05, (
    f"the one-sided family now carries positively on up to {_os_vals.max():.1%} "
    "of days; it is no longer structurally one-sided and the rule's coverage of "
    "it should be revisited")
assert float(cpf[~cpf.index.isin(_one_sided)].min()) > 0.20, (
    "a pair outside the named family has become one-sided too")
print("\nOK: the six named pairs carry positively on under 3% of days. A "
      "carry-keyed\nrule is one-sided on them whatever it is told to do.")

# %% [markdown]
# ### 7.2 2024 and 2025 fired **zero** flatteners
#
# Risk-adjusted carry declined monotonically, so on a 3y trailing window every
# pair sits near the bottom of its own history and the *flattener* side — which
# needs a **high** percentile — simply never opens. The book is steepener-only
# for two full years. Episodes are re-derived here on the backtest window so the
# claim is measured, not quoted.

# %%
_d = SIG.index.get_level_values("date")
SIGW = SIG[(_d >= pd.Timestamp(CONFIG.start)) & (_d <= pd.Timestamp(CONFIG.end))]
STATEW = R.entry_state(SIGW, CONFIG)
EPS = B.episodes_from_state(STATEW, exit_pct=CONFIG.exit_pct,
                            rac_pct=SIGW["rac_pct"],
                            max_hold_days=MAX_HOLD, min_hold_days=MIN_HOLD)
BYYEAR = (pd.DataFrame({"date": [e.entry for e in EPS], "side": [e.side for e in EPS]})
          .assign(year=lambda d: d["date"].dt.year)
          .groupby("year")["side"]
          .agg(flatteners=lambda s: int((s == 1).sum()),
               steepeners=lambda s: int((s == -1).sum())))
print(f"episodes ENTERED, by year and side "
      f"({CONFIG.start} .. {CONFIG.end}, {len(EPS)} total):\n")
print(BYYEAR.to_string())

_flat_days = STATE_ALL[STATE_ALL == 1].index.get_level_values("date")
print(f"\nlast day any flattener was ON, over the whole panel: "
      f"{_flat_days.max().date()}")

assert int(BYYEAR.at[2024, "flatteners"]) == 0, "2024 entered a flattener"
assert int(BYYEAR.at[2025, "flatteners"]) == 0, "2025 entered a flattener"
assert int(BYYEAR.at[2024, "steepeners"]) > 0 and int(BYYEAR.at[2025, "steepeners"]) > 0
print("\nOK: 2024 and 2025 entered ZERO flatteners and "
      f"{int(BYYEAR.at[2024, 'steepeners']) + int(BYYEAR.at[2025, 'steepeners'])} "
      "steepeners between them.")
print(f"SCOPE: the drought is 2024-2025 exactly. 2026 entered "
      f"{int(BYYEAR.at[2026, 'flatteners'])} flatteners,")
print(f"the last flattener day being {_flat_days.max().date()}. Do not read this as "
      '"no\nflatteners since 2023".')

# %% [markdown]
# ## 8. The column that cannot be reproduced
#
# Citi's screen prints a **"ZS since 2000"**. This repo cannot produce it, for
# two independent reasons, and the column above is therefore labelled by the
# window it actually uses rather than by the one Citi uses.
#
# 1. **The leg panel starts in 2018.** `zs_full` is an expanding z-score over
#    exactly the panel it is given.
# 2. **Even rebuilt from scratch, the curve store does not reach 2000.** The
#    earliest Citi Velocity partition on disk is measured below.
#
# Neither is fixable from here, so the honest thing is to relabel, which is what
# `LONG_Z_LABEL` does.

# %%
_zfull = PANEL.dropna(subset=["zs_full"])
print(f"leg panel first date             {LEG.index.get_level_values('date').min().date()}")
print(f"screen panel first date          {PANEL_START.date()}")
print(f"first date zs_full is defined    {_zfull['date'].min().date()}"
      f"   (expanding, min_periods=60)")
print(f"column printed in section 4      {LONG_Z_LABEL!r}")

STORE_FLOOR = None
try:
    from Caching.curve_store import CurveStore

    _dates = CurveStore.default().available_dates("USD-SOFR-1D-CITIVELOEXCEL")
    if _dates:
        STORE_FLOOR = _dates[0]
        print(f"\ncurve store USD-SOFR-1D-CITIVELOEXCEL: {len(_dates):,} day "
              f"partitions, {_dates[0]} .. {_dates[-1]}")
except Exception as exc:                                            # noqa: BLE001
    print(f"\ncurve store not readable here ({type(exc).__name__}: {exc})")

if STORE_FLOOR is None:
    print("\nNOT MEASURED: the curve store floor could not be read in this "
          "environment,\nso reason 2 above is stated without a number. Reason 1 "
          "stands on its own —\nthe panel in hand starts in 2018.")
else:
    assert STORE_FLOOR > dt.date(2000, 1, 1), (
        f"the curve store now reaches {STORE_FLOOR}, at or before 2000 — Citi's "
        "'ZS since 2000' column may be reproducible after all")
    print(f"\nOK: the deepest Citi Velocity partition is {STORE_FLOOR}, "
          f"{STORE_FLOOR.year - 2000} years after\nthe start of Citi's window. "
          "'ZS since 2000' is out of reach on both counts.")

# %% [markdown]
# ## 9. The verdict this screen sits under: DEAD
#
# Re-derived here from the committed equity curves and the episodes rebuilt in
# section 7.2, so the number at the top of this notebook is one it computed
# rather than one it quoted.
#
# Positions are held ~100 business days, so 117 episodes over 5.6 years are
# **not** 117 independent observations.

# %%
ARMS = {}
for tag in ("base", "zero_cost"):
    f = DATA / f"rac_w4_equity_{tag}.parquet"
    if f.exists():
        e = pd.read_parquet(f)["equity"]
        e.index = pd.to_datetime(e.index)
        ARMS[tag] = e
assert set(ARMS) == {"base", "zero_cost"}, (
    f"expected both equity arms in {DATA}; found {sorted(ARMS)}")


def _sharpe(eq: pd.Series) -> float:
    r = eq.diff().dropna()
    return float(r.mean() / r.std() * np.sqrt(252)) if r.std() > 0 else np.nan


gross_sr = _sharpe(ARMS["zero_cost"])
net_sr = _sharpe(ARMS["base"])
holds = pd.Series([e.days for e in EPS], dtype=float)
mean_hold = float(holds.mean())
span = (ARMS["base"].index[-1] - ARMS["base"].index[0]).days / 365.25
n_eff = span * 252.0 / mean_hold

print(f"episodes          {len(EPS)}")
print(f"mean hold         {mean_hold:.1f} business days "
      f"(median {holds.median():.0f}, max {holds.max():.0f})")
print(f"span              {span:.2f} years")
print(f"n_eff             {n_eff:.2f} independent holds")
print(f"\ngross Sharpe      {gross_sr:.4f}   (zero-cost arm)")
print(f"net Sharpe        {net_sr:.4f}   (base arm)")

# THREE numbers, not one, and the spread between them is the point. `n_obs=k`
# sets sr_std = 1/sqrt(k), the standard error of a PER-HOLD Sharpe, and the
# floor-vs-round choice moves it a little. `gross_sr` is ANNUALISED, and an
# annualised Sharpe has null standard error 1/sqrt(span_years) -- with holds
# this long, the LARGER of the two, so the per-hold clock is the flattering
# one. The verdict has to hold on the strictest of them.
NULL = pd.DataFrame([{"trials": N,
                      "per-hold, floor(n_eff)":
                          expected_max_sharpe_under_null(N, n_obs=int(n_eff)),
                      "per-hold, round(n_eff)":
                          expected_max_sharpe_under_null(N, n_obs=int(round(n_eff))),
                      "annualised, 1/sqrt(span)":
                          expected_max_sharpe_under_null(
                              N, sr_std=1.0 / np.sqrt(span))}
                     for N in (1, 6, 12, 24, 48)])
print("\n" + NULL.round(4).to_string(index=False))

null_lo = float(NULL.loc[NULL["trials"] == 12].iloc[0, 1:].min())
null_hi = float(NULL.loc[NULL["trials"] == 12].iloc[0, 1:].max())
null_ann = float(NULL.loc[NULL["trials"] == 12, "annualised, 1/sqrt(span)"].iloc[0])
print(f"\nat 12 trials the null expectation spans {null_lo:.4f} .. {null_hi:.4f} "
      "across the\nthree clocks; the gross Sharpe is "
      f"{gross_sr:.4f}.")
assert gross_sr < null_ann, (
    f"the gross Sharpe {gross_sr:.4f} now clears the ANNUALISED 12-trial null "
    f"{null_ann:.4f}, the clock that matches how it is measured")
assert null_ann >= null_hi, (
    "the annualised clock is no longer the strictest of the three, so the "
    "comment above about which one flatters is wrong for this book")

assert gross_sr < null_lo, (
    f"the gross Sharpe {gross_sr:.4f} now clears the 12-trial null {null_lo:.4f}; "
    "the DEAD verdict at the top of this notebook needs re-deriving")
assert net_sr < gross_sr, "costs did not reduce the Sharpe"
print("\nVERDICT: DEAD. The GROSS Sharpe is below the null expectation for a")
print("12-cell search, and the exit-rule x minimum-hold sweep alone was 12 cells.")
print("No cost assumption rescues this, because the failure is in the gross number.")
print("\nA NUMBER YOU MAY HAVE SEEN: the workflow write-up quotes 0.445 for this")
print(f"null. That is n_obs = {int(round(n_eff))} (n_eff rounded); flooring n_eff "
      f"gives {int(n_eff)} and")
print(f"{expected_max_sharpe_under_null(12, n_obs=int(n_eff)):.4f}.")
print("w4_rac_backtest computes n_eff from its own episode series and its own")
print("span_years, so it lands a fraction away and prints 0.446. The two do not")
print("have to agree to the digit; what matters is that the whole range does.")
print(f"The annualised clock -- the one that matches an annualised Sharpe -- is "
      f"stricter still at {null_ann:.4f}.")
print(f"All three exceed the {gross_sr:.3f} gross Sharpe, which is why the verdict")
print("does not turn on the choice.")

# %% [markdown]
# ## 10. The picture
#
# One figure, two rows. The top row is the measurement in section 5(b) — the
# published `BE/vol` ratio across all fifteen pairs against Citi's own 0.8 and
# 1.0 lines, showing the whole cross-section walking through both. The bottom
# row is today's rule input: each pair's `rac` percentile against its own 3y
# history, with the entry bands.

# %%
import plotly.graph_objects as go
from plotly.subplots import make_subplots

wide = PANEL.pivot(index="date", columns="pair", values="be_over_rv").sort_index()
fig = make_subplots(rows=2, cols=1, row_heights=[0.58, 0.42],
                    vertical_spacing=0.13,
                    subplot_titles=(
                        "BE / realised vol across the 15 pairs "
                        "(Citi's own decision column)",
                        f"rac percentile vs own {CONFIG.lookback_days}d history, "
                        f"{ASOF.date()}"))

fig.add_trace(go.Scatter(x=wide.index, y=wide.max(axis=1), name="max of 15",
                         line=dict(width=0, color="rgba(31,119,180,0.0)"),
                         showlegend=False, hoverinfo="skip"), row=1, col=1)
fig.add_trace(go.Scatter(x=wide.index, y=wide.min(axis=1), name="min-max range",
                         fill="tonexty", fillcolor="rgba(31,119,180,0.18)",
                         line=dict(width=0, color="rgba(31,119,180,0.0)")),
              row=1, col=1)
fig.add_trace(go.Scatter(x=wide.index, y=wide.median(axis=1), name="median of 15",
                         line=dict(width=1.6, color="#1f77b4")), row=1, col=1)
for y, lab in ((0.8, "Citi exit 0.8"), (1.0, "Citi steepener 1.0")):
    fig.add_hline(y=y, line=dict(color="#c1121f", width=1, dash="dash"),
                  annotation_text=lab, annotation_position="top left", row=1, col=1)
# NOTE: marked with a scatter trace rather than add_vline. This plotly version
# raises inside `add_vline` when x is a pandas Timestamp AND an annotation is
# attached (it averages the x-values to place the label, and Timestamps do not
# sum). Markers avoid the code path entirely and label the same two dates.
_marks_x = [TIE_DATE, ASOF]
_marks_y = [float(wide.median(axis=1).asof(x)) for x in _marks_x]
fig.add_trace(go.Scatter(x=_marks_x, y=_marks_y, mode="markers+text",
                         text=[f"tie-out {TIE_DATE.date()}", f"ASOF {ASOF.date()}"],
                         textposition="top center", name="reference dates",
                         marker=dict(size=9, color="#c1121f", symbol="diamond")),
              row=1, col=1)

pct = today["rac_pct"].sort_values()
colours = ["#c1121f" if state_today[p] == -1 else
           ("#2a9d8f" if state_today[p] == 1 else "#999999") for p in pct.index]
fig.add_trace(go.Bar(x=pct.to_numpy(), y=list(pct.index), orientation="h",
                     marker_color=colours, name="rac_pct", showlegend=False),
              row=2, col=1)
for x, lab in ((CONFIG.steepener_pct, "steepener bar"),
               (CONFIG.enter_pct, "flattener bar")):
    fig.add_vline(x=x, line=dict(color="#444", width=1, dash="dash"),
                  annotation_text=lab, annotation_position="top",
                  row=2, col=1)

fig.update_xaxes(title_text="BE / rlzd vol", row=1, col=1)
fig.update_xaxes(title_text="percentile of own trailing rac", range=[0, 1],
                 row=2, col=1)
fig.update_layout(height=760, title=f"W4 risk-adjusted-carry screen, {ASOF.date()}"
                                    "  —  BACKTEST VERDICT: DEAD",
                  legend=dict(orientation="h", y=1.06))
fig.show()

# %% [markdown]
# ## 11. Coverage and staleness
#
# What this screen is standing on, and how old it is. "Latest available date" is
# the panel's latest date; nothing here fetches, so the gap to the wall clock is
# reported and not closed.

# %%
WALL = dt.date.today()
gap_cal = (WALL - ASOF.date()).days
gap_bd = int(np.busday_count(ASOF.date(), WALL))
print(f"panel ASOF            {ASOF.date()}")
print(f"wall clock at run     {WALL}")
print(f"staleness             {gap_cal} calendar days / {gap_bd} business days")
if gap_bd > 5:
    print("  ^ MORE THAN A WEEK STALE. Re-run the leg-panel build before reading "
          "section 6\n    as a live position.")

_recent = PANEL[PANEL["date"] >= ASOF - pd.Timedelta(days=30)]
print(f"\nlast 30 calendar days: {_recent['date'].nunique()} dates, "
      f"{len(_recent)} cells, "
      f"{int(_recent[['level_bp', 'carry_1y_bp', 'rlzd_vol_bp']].isna().sum().sum())}"
      " NaNs across the three core columns")
print(f"legs priced on ASOF   : "
      f"{sorted(LEG.xs(ASOF, level='date').index.tolist())}")
assert LEG.xs(ASOF, level="date").shape[0] == 9, (
    "the leg panel does not carry all nine forward legs on ASOF")
assert gap_cal >= 0, "the panel is stamped in the future"

# %% [markdown]
# ## 12. Reading this notebook
#
# * **This is a market read, not a recommendation.** Section 9 re-derives the
#   verdict on the rule built from this screen: gross Sharpe 0.397 against a
#   12-trial null of 0.462. That is a failure in the *gross* number, so no cost
#   assumption rescues it. The screen is still worth printing — it reproduces
#   Citi's published cells in rank — but "attractive" here means "cheap on this
#   metric", not "a trade".
#
# * **The rank is what transferred; the level never did.** Section 2 grades 120
#   published cells: spearman 0.988 on the decision statistic, with a −0.19
#   offset on the ratio and −0.81 bp on the curve. Section 5 is the consequence,
#   and it is sharper than a constant offset: Citi's 1.0 steepener threshold
#   fired on **0 of 15** pairs on the tie-out date and fires on **14 of 15**
#   today. It is a regime dial on this curve, not a screen, which is why the rule
#   reads a trailing percentile instead.
#
# * **Today's reading is one-sided by construction.** Every one of the fifteen
#   pairs is below the steepener bar, so the percentile axis selects nothing and
#   the within-side rank picks the bottom three — all of which are in the
#   `10Yx10Y` family that carries positively on under 3 % of days. The rule's
#   only live positions sit on the pairs it can only ever have one opinion about.
#   That is a property of the universe (7.1) meeting a monotone decline in
#   risk-adjusted carry (7.2), not a signal.
#
# * **One column is not Citi's.** She prints "ZS since 2000". The leg panel
#   starts 2018-01-01 and the deepest Citi Velocity partition on disk is
#   2005-01-03, so the column is labelled by the window it actually uses.
#
# * **Four of the eight "most attractive" polarities are reconstructions.** Curve
#   level, the z-scores and `BE/vol` have their direction documented in the
#   module; carry, breakeven and realised vol do not, and the marks on those
#   three columns are this notebook's reading of Citi's intent. They are reported
#   and never asserted on.
#
# * **The eight columns do not agree, by design.** Section 4.1: the level columns
#   mark the `10Yx10Y` family (steep against its own history — a good place to
#   put a flattener on), the carry columns mark the `15Yx5Y` family (the cheapest
#   place to hold one), and no pair is marked on all eight — the cell prints how
#   many the best-marked pair gets. The rule reads only the carry side, so it
#   ends up short the pairs the level
#   columns like most. Both readings are in the table; only one is in the rule.
#
# Backtest: `w4_rac_backtest.ipynb`.
# Full write-up: `docs/convexityrv/results/w4-ultra-long-risk-adjusted-carry.md`.
