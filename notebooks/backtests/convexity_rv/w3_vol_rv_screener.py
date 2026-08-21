# %% [markdown]
# # W3 screener — front-end vs long-end curve-implied vol, live
#
# ## This is a market read. It is not a recommendation.
#
# The strategy this screen was built for is **rejected**. The W3 backtest work
# concluded, verbatim:
#
# > **THE PREMISE FAILS BEFORE ANY BACKTEST.** Across 16 (colour, pair)
# > combinations, 2021-2026:
# >
# > ```
# > change correlation   max |0.112|, most 0.00-0.08, several negative
# > ADF on the spread    14 of 16 FAIL to reject a unit root at 5%
# > the 2 that reject    half-lives of 1.22 and 1.62 DAYS
# > ```
# >
# > So either the spread does not revert, or it reverts far too fast to pay a
# > 0.5bp round trip. A z-score entry assumes stationarity; on 14 of 16 pairs
# > that assumption is rejected by the data, and a signal built on the z-score
# > of a random walk is fitting the sampling distribution of a unit root.
# >
# > — commit `88f201f7`, *W3 — STIR vs long-end curve vol, rejected at the
# > diagnostic*
#
# **So why keep the screen?** Because the two *levels* are worth looking at even
# though their *spread* is not tradable. Both legs are curve-implied volatility
# on the same ruler — bp per day — and neither is an option price:
#
# * **STIR leg.** A SOFR pack's convexity adjustment is a variance quantity;
#   Ho-Lee gives $CA = \tfrac12 \sigma^2 \cdot \overline{T_1^2}$, so inverting the
#   observed adjustment yields a normal vol with **no fitted parameter in it**.
# * **Long-end leg.** A DV01-neutral ultra-long forward flattener has a convex
#   payoff; the daily move at which its convexity gain offsets its negative carry
#   is Citi's own breakeven column, already in bp/day.
#
# Together they say what the very front and the very back of the curve are
# currently charging for convexity. That is a useful thing to know. The z-score
# is printed **beside its own ADF p-value and half-life** precisely so that no
# reader can mistake a large z for a trade — section 8 is the census, and every
# claim in it is asserted rather than asserted-in-prose.
#
# **What this notebook does not contain:** any P&L, any position, any sizing.

# %%
import dataclasses
import datetime as dt
import json
import math
import os
import pathlib
import re
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
import plotly.graph_objects as go
from plotly.subplots import make_subplots
pio.renderers.default = "plotly_mimetype+notebook_connected"

from RVUtils.ConvexityRV import w3_ca_vs_longend as W3
from RVUtils.ConvexityRV.ca_signals import COLOUR_RANK
from RVUtils.ConvexityRV.holee import pack_ca_bp, implied_vol_from_ca_bp

DATA = REPO / "notebooks" / "data" / "convexity_rv"
pd.set_option("display.width", 250, "display.max_columns", 40, "display.max_rows", 120)
RUN_AT = dt.date.today()
print(f"repo    {REPO}")
print(f"run at  {RUN_AT}")

# %% [markdown]
# ## 1. The config
#
# Every knob and the reason for its value. `W3Config` carries the trade-side
# defaults; they are restated here so the notebook is self-describing, and the
# screener-only knobs are declared alongside them.
#
# **The one deliberate departure from the module default is `end`.**
# `W3Config.end` is pinned to `2026-08-20` because that was the last date of the
# research sample. A *live* screener that inherited that would silently freeze on
# a fixed day forever and go on reporting it as "current", so the screen is built
# with `end = today`. The tie-out in section 3 keeps the module defaults, because
# a tie-out that moves is not a tie-out.

# %%
LIVE = W3.W3Config(
    start=dt.date(2021, 1, 1),   # W3 canon: the sample the diagnostics were run on
    end=RUN_AT,                  # LIVE: not the module's frozen 2026-08-20
    colour="Blues",              # headline cell only; the screen covers all four
    pair="15Yx5Y/20Yx10Y",       # the pair Citi traded and published a round trip for
    z_window=252,                # 1y trailing window for the z-score
    entry_z=1.5,                 # the (rejected) rule's entry threshold, shown for scale
    exit_z=0.5,
    min_periods=120,             # no z emitted on fewer than ~6 months of history
    holee_convention="citi",     # T1^2, pinned against eight published screens
)

# --- screener-only knobs -----------------------------------------------------
COLOURS = ("Reds", "Greens", "Blues", "Golds")   # Whites has no long-end analogue here
ROBUST_MEDIAN_DAYS = 5      # last-print vs 5-day median: the STIR leg is jumpy (S6)
MAX_STALE_DAYS = 14         # calendar days; beyond this the screen is history, not a screen
STIR_UNIT_LO, STIR_UNIT_HI = 0.5, 40.0    # bp/DAY. A bp/YR series lands at ~100-200.
LONG_UNIT_LO, LONG_UNIT_HI = 0.5, 20.0    # bp/DAY.
ADF_ALPHA = 0.05            # unit-root rejection level
HL_TRADABLE_FLOOR = 5.0     # business days; justified from measurement in section 8
JUMP_Z = 2.0                # |z| of a 1-day change in the STIR leg that gets flagged
TIEOUT_ATOL = 1e-6

# The 16 cells the committed W3 diagnostics were run on, for the tie-out.
CANON_PAIRS = ("15Yx5Y/20Yx10Y", "10Yx10Y/20Yx10Y", "15Yx5Y/25Yx10Y", "20Yx5Y/25Yx5Y")

print(json.dumps(LIVE.to_dict(), indent=1, default=str))
print(f"\nscreener knobs: colours={COLOURS} robust_median={ROBUST_MEDIAN_DAYS}d "
      f"max_stale={MAX_STALE_DAYS}d adf_alpha={ADF_ALPHA} hl_floor={HL_TRADABLE_FLOOR}")

# %% [markdown]
# ## 2. The two legs, and how stale they are
#
# The STIR leg is rebuilt from the CA panel on every run (gate-filtered), keyed
# on **pack rank** rather than on a pack label — a colour is a constant-maturity
# slot and its label rolls with the strip.
#
# The long-end leg is `be_daily_analytic` out of the RAC screen panel. **Zeros
# there are truncations, not readings**: Citi's breakeven is defined only where
# carry is negative, and the column is written as exactly `0.0` whenever
# `carry >= 0`. Reading those as "a breakeven of zero" would drag every mean and
# every z-score toward zero on precisely the pairs that spend the most time with
# positive carry (`20Yx5Y/25Yx5Y` truncates on 54% of days). They are mapped to
# NaN and dropped.

# %%
_q20 = pd.read_parquet(DATA / "strat2_q20_panel.parquet")
_q20["date"] = pd.to_datetime(_q20["date"])
PANEL = _q20[_q20["gate_ok"]].copy()

RAC = pd.read_parquet(DATA / "rac_screen_panel.parquet")
RAC["date"] = pd.to_datetime(RAC["date"])
PAIRS = tuple(sorted(RAC["pair"].unique()))

print(f"CA panel   {len(_q20):,} rows, {int(_q20['gate_ok'].sum()):,} gate_ok "
      f"({_q20['date'].min().date()} .. {_q20['date'].max().date()})")
print(f"RAC panel  {len(RAC):,} rows, {len(PAIRS)} pairs "
      f"({RAC['date'].min().date()} .. {RAC['date'].max().date()})")

# dataclasses.replace, NOT W3Config(**cfg.to_dict()): to_dict() stringifies the
# two date fields, so round-tripping through it hands the module `str` where it
# expects `datetime.date` and every window comparison then compares wrong types.
STIR = {c: W3.stir_implied_vol_series(PANEL, dataclasses.replace(LIVE, colour=c))
        for c in COLOURS}

_trunc = {}
LONG = {}
for q in PAIRS:
    s = RAC[RAC["pair"] == q].set_index("date")["be_daily_analytic"].sort_index()
    s = s[(s.index >= pd.Timestamp(LIVE.start)) & (s.index <= pd.Timestamp(LIVE.end))]
    _trunc[q] = float((s == 0.0).mean())
    LONG[q] = s.replace(0.0, np.nan).dropna()

LEGS = pd.DataFrame(
    [{"leg": "STIR", "key": c, "n": len(s), "first": s.index.min().date(),
      "last": s.index.max().date(), "median_bp_day": float(s.median()),
      "last_bp_day": float(s.iloc[-1]), "trunc_frac": np.nan}
     for c, s in STIR.items()]
    + [{"leg": "LONG", "key": q, "n": len(s), "first": s.index.min().date(),
        "last": s.index.max().date(), "median_bp_day": float(s.median()),
        "last_bp_day": float(s.iloc[-1]), "trunc_frac": _trunc[q]}
       for q, s in LONG.items()])
print("\n" + LEGS.round(4).to_string(index=False))

# %%
# --- requirement 4: non-empty, in-unit, and how stale ------------------------
for c, s in STIR.items():
    assert len(s) > 0, f"STIR leg {c} is empty"
    med = float(s.median())
    assert STIR_UNIT_LO <= med <= STIR_UNIT_HI, (
        f"STIR {c} median {med:.2f} is outside {STIR_UNIT_LO}-{STIR_UNIT_HI} bp/DAY. "
        "holee.implied_vol_from_ca_bp returns bp/YEAR; a series that skipped the "
        "/sqrt(252) conversion lands near 100-200 and every spread built on it is "
        "sqrt(252) wrong while still looking plausible in isolation.")
for q, s in LONG.items():
    assert len(s) > 0, f"long-end leg {q} is empty"
    med = float(s.median())
    assert LONG_UNIT_LO <= med <= LONG_UNIT_HI, (
        f"long-end {q} median {med:.2f} is outside {LONG_UNIT_LO}-{LONG_UNIT_HI} bp/DAY")

ASOF = max(max(s.index.max() for s in STIR.values()),
           max(s.index.max() for s in LONG.values()))
STIR_ASOF = max(s.index.max() for s in STIR.values())
LONG_ASOF = max(s.index.max() for s in LONG.values())
STALE_DAYS = (pd.Timestamp(RUN_AT) - ASOF).days

print(f"latest STIR observation      {STIR_ASOF.date()}")
print(f"latest long-end observation  {LONG_ASOF.date()}")
print(f"screen as of                 {ASOF.date()}")
print(f"run at                       {RUN_AT}")
print(f"STALENESS                    {STALE_DAYS} calendar day(s)")
print(f"\nboth legs non-empty; STIR medians "
      f"{[round(float(s.median()), 2) for s in STIR.values()]} bp/day, all inside "
      f"{STIR_UNIT_LO}-{STIR_UNIT_HI}")

assert STALE_DAYS <= MAX_STALE_DAYS, (
    f"the screen is {STALE_DAYS} calendar days stale (limit {MAX_STALE_DAYS}). "
    "This is a LIVE screener: at this age the tables below are history, not a "
    "market read. Rebuild strat2_q20_panel.parquet and rac_screen_panel.parquet.")

# %% [markdown]
# ## 3. Known-answer tie-out
#
# Three checks whose right answers are known independently of this notebook.
#
# **(a) The Ho-Lee inversion is an exact algebraic round trip.** Forward and
# inverse are $CA = \tfrac12\sigma^2 \overline{T_1^2}$ and
# $\sigma = \sqrt{2\,CA/\overline{T_1^2}}$, so a vol pushed through both must
# return to machine precision. If it does not, the convention or the accrual has
# been changed underneath.
#
# **(b) The unit conversion is exactly $\sqrt{252}$.** This is the defect the W3
# module was built around: `implied_vol_from_ca_bp` returns **bp/year**,
# `be_daily_analytic` is **bp/day**, and the first W3 run spread them as they came
# and printed a ~100bp "spread" that was almost entirely the mismatch. Correlation
# is scale-invariant, so the diagnostics survived it untouched and would have been
# published as-is.
#
# **(c) The 16 canonical cells reproduce the committed diagnostics.** Not fitted
# to anything here: `w3_link_diagnostics.csv` was written by
# `_w3_ca_vs_longend_run.py` and is graded against, cell by cell.

# %%
_t1s = [3.25, 3.50, 3.75, 4.00]     # a representative 4-contract pack; (a) is algebraic
rt = []
for sig in (60.0, 110.0, 180.0):
    ca = pack_ca_bp(sig, _t1s, convention=LIVE.holee_convention)
    back = implied_vol_from_ca_bp(ca, _t1s, convention=LIVE.holee_convention)
    rt.append({"sigma_bp_yr": sig, "ca_bp": ca, "recovered": back,
               "abs_err": abs(back - sig)})
    assert abs(back - sig) < 1e-9, f"Ho-Lee round trip broken at {sig}"
print("(a) Ho-Lee round trip, CITI convention (T1^2):")
print(pd.DataFrame(rt).to_string(index=False))

# Read the live row out of the panel rather than transcribing it: a hand-copied
# t1 rounded to 6dp reproduces the vol to 4dp and fails a 1e-9 identity check,
# which is a fact about the transcription and not about the module.
_bd = STIR["Blues"].index.max()
_brow = PANEL[(PANEL["rank"] == COLOUR_RANK["Blues"]) & (PANEL["date"] == _bd)].iloc[0]
_ca_live, _w = float(_brow["ca_bp"]), float(_brow["time_weight"])
_yr = implied_vol_from_ca_bp(_ca_live, [math.sqrt(_w)], convention=LIVE.holee_convention)
_day = float(STIR["Blues"].loc[_bd])
print(f"\n(b) unit identity on the live Blues print ({_bd.date()}, pack "
      f"{_brow['pack']}, CA {_ca_live:.6f} bp, mean(T1^2) {_w:.6f}):")
print(f"    holee -> {_yr:.4f} bp/YEAR")
print(f"    /sqrt(252) -> {_yr / math.sqrt(252.0):.4f} bp/day")
print(f"    module emitted -> {_day:.4f} bp/day")
assert abs(_yr / math.sqrt(252.0) - _day) < 1e-9, (
    "the module's STIR leg is not the annual vol divided by sqrt(252)")
assert 90.0 < _yr < 250.0, "sanity: a SOFR normal vol should be ~100-200 bp/yr"
print(f"    OK: the two legs differ by exactly sqrt(252) = {math.sqrt(252.0):.4f}")

# %%
CSV = DATA / "w3_link_diagnostics.csv"
if not CSV.exists():
    print(f"MISSING {CSV}: the 16-cell tie-out cannot be run. Regenerate with "
          "_w3_ca_vs_longend_run.py. No tie-out number is reported below.")
    TIEOUT = None
else:
    ref = pd.read_csv(CSV)
    got = []
    for c in COLOURS:
        # module defaults, NOT the live config: a tie-out that moves is not one.
        s_canon = W3.stir_implied_vol_series(PANEL, W3.W3Config(colour=c))
        for q in CANON_PAIRS:
            lb = (RAC[RAC["pair"] == q].set_index("date")["be_daily_analytic"]
                  .replace(0.0, np.nan).dropna().sort_index())
            d = W3.link_diagnostics(s_canon, lb)
            got.append({"colour": c, "pair": q, **d})
    got = pd.DataFrame(got)
    cmp_cols = ["n", "corr_levels", "corr_changes", "beta_changes",
                "spread_adf_p", "spread_half_life_days"]
    M = ref.merge(got, on=["colour", "pair"], suffixes=("_ref", "_now"))
    devs = {k: float((M[f"{k}_ref"] - M[f"{k}_now"]).abs().max()) for k in cmp_cols}
    TIEOUT = devs
    print(f"(c) 16-cell tie-out against {CSV.name} ({len(M)} cells matched)")
    for k, v in devs.items():
        print(f"    max |ref - now|  {k:24} {v:.3e}")
    assert len(M) == 16, f"expected 16 canonical cells, matched {len(M)}"
    assert max(devs.values()) < TIEOUT_ATOL, (
        f"the 16 canonical cells no longer reproduce w3_link_diagnostics.csv "
        f"(max deviation {max(devs.values()):.3e} > {TIEOUT_ATOL}). This is a "
        "VINTAGE mismatch, not necessarily a bug: the CA or RAC panel has been "
        "rebuilt since the CSV was written. Re-run _w3_ca_vs_longend_run.py and "
        "compare the two verdicts before trusting either.")
    print("\n    OK: every canonical cell reproduces to <1e-6.")

# %% [markdown]
# ## 4. The sign probe
#
# Re-derived from the module on every run rather than trusted from a comment.
# There is no position here, so what needs pinning down is the **polarity of the
# reading**:
#
# $$\text{spread} = \sigma^{\text{STIR}}_{\text{bp/day}}
#                  - \text{BE}^{\text{long-end}}_{\text{bp/day}}$$
#
# so a **positive** spread (and a positive z) means **front-end curve-implied vol
# is rich against the long end**. The probe feeds the module a synthetic pair of
# series with a known answer: a flat long-end leg, a noisy STIR leg, and a bump at
# the end in each direction.

# %%
_rng = np.random.default_rng(0)
_n = 400
_idx = pd.bdate_range("2024-01-01", periods=_n)
_base = pd.Series(5.0 + _rng.normal(0.0, 1.0, _n), index=_idx)
_flat = pd.Series(5.0, index=_idx)

probe = {}
for tag, bump in (("STIR rich (+8bp/day)", +8.0), ("STIR cheap (-8bp/day)", -8.0)):
    s = _base.copy()
    s.iloc[-3:] = 5.0 + bump                      # 3 days so the LAGGED z sees it
    sp = W3.build_vol_spread_panel(s, _flat, LIVE)
    st = W3.entry_state(sp, LIVE)
    probe[tag] = {"spread": float(sp["spread"].iloc[-1]),
                  "z": float(sp["z"].iloc[-1]),
                  "state": int(st.iloc[-1])}
print(pd.DataFrame(probe).T.to_string())

assert probe["STIR rich (+8bp/day)"]["spread"] > 0
assert probe["STIR rich (+8bp/day)"]["z"] > LIVE.entry_z
assert probe["STIR rich (+8bp/day)"]["state"] == +1
assert probe["STIR cheap (-8bp/day)"]["spread"] < 0
assert probe["STIR cheap (-8bp/day)"]["z"] < -LIVE.entry_z
assert probe["STIR cheap (-8bp/day)"]["state"] == -1
print("\nOK: spread > 0 and z > 0 means the STIR (front-end) leg is RICH against")
print("the long end. The module's state +1 is the sell-front-end-convexity side.")
print("NOTE: state is shown only to pin the polarity. It is not traded here.")

# %% [markdown]
# ## 5. The one-day lag, and what it costs a live reader
#
# `build_vol_spread_panel` lags everything the rule reads by one day, so that a
# backtest cannot rank on same-day information by accident. A screener wants the
# opposite: today's reading. So the screen computes `z_now` on the **unlagged**
# spread with identical window parameters, and shows the module's lagged `z`
# beside it.
#
# The two must be the same statistic one day apart, and that is checkable exactly:
# a rolling window over a shifted series is the shift of the rolling window, so
# `z_now.shift(1)` must equal the module's `z` to the bit.

# %%
def screen_cell(colour: str, pair: str) -> dict:
    """One (colour, pair) cell of the screen. No fitted parameter anywhere."""
    s, lb = STIR[colour], LONG[pair]
    cfg = dataclasses.replace(LIVE, colour=colour, pair=pair)
    sp = W3.build_vol_spread_panel(s, lb, cfg)
    if sp.empty or len(sp) < LIVE.min_periods:
        return {}
    roll = sp["spread"].rolling(cfg.z_window, min_periods=cfg.min_periods)
    sp["z_now"] = (sp["spread"] - roll.mean()) / roll.std(ddof=0)
    shift_err = float((sp["z_now"].shift(1) - sp["z"]).abs().max())

    d = W3.link_diagnostics(s, lb)
    last = sp.iloc[-1]
    tail = sp.tail(ROBUST_MEDIAN_DAYS)
    sd_ratio = float(sp["spread"].diff().std() / sp["spread"].std())
    return {
        "colour": colour, "pair": pair, "asof": sp.index[-1].date(), "n": int(len(sp)),
        "stir": float(last["stir_iv"]), "long": float(last["long_be"]),
        "spread": float(last["spread"]),
        "spread_med5": float(tail["spread"].median()),
        "z_now": float(last["z_now"]), "z_med5": float(tail["z_now"].median()),
        "z_lag": float(last["z"]),
        "corr_ch": d["corr_changes"], "adf_p": d["spread_adf_p"],
        "half_life": d["spread_half_life_days"], "sd_ratio": sd_ratio,
        "_shift_err": shift_err,
    }


SCREEN = pd.DataFrame([r for c in COLOURS for q in PAIRS
                       if (r := screen_cell(c, q))])
print(f"{len(SCREEN)} cells = {len(COLOURS)} colours x {len(PAIRS)} pairs")

_se = float(SCREEN["_shift_err"].max())
print(f"max |z_now.shift(1) - module z| over all cells: {_se:.3e}")
assert _se < 1e-12, (
    "the screen's z is not the module's z shifted by a day; the two are then "
    "different statistics and the table below cannot be read against the rule")
print("OK: the screen's z_now is exactly the rule's z, one day earlier.")
SCREEN = SCREEN.drop(columns=["_shift_err"])

# %% [markdown]
# ## 6. Is today's print trustworthy?
#
# The STIR leg is jumpy and the CA panel's own gate does not catch everything.
# The relevant precedent is in this package already: `ca_staleness` was written
# because *"a deferred contract whose settle is a day old will usually leave the
# pack's adjustment positive, pass the sign filter, and still be wrong"*, and a
# stale quote that catches up in one print books **"zero P&L for k days and the
# whole accumulated move as a one-day gain or loss"**.
#
# A screener has a lighter version of the same problem: the reading it prints is
# one day's number. Two checks, both generic (no date is hardcoded):
#
# 1. **Sign.** A negative CA is a no-arbitrage violation. `stir_implied_vol_series`
#    drops those days silently, which means the "previous print" behind a
#    one-day change may not be the previous business day.
# 2. **Jump.** The z-score of the latest one-day change in the STIR leg against
#    that leg's own full-sample change distribution.
#
# Where either fires, read `spread_med5` and `z_med5` in the screen instead of the
# last print. Neither is asserted on — a jumpy day is a fact about the market as
# often as about the data, and this notebook does not have the evidence to say
# which.

# %%
LOOKBACK = 10
qual = []
for c in COLOURS:
    rank = COLOUR_RANK[c]
    tail = (PANEL[PANEL["rank"] == rank].sort_values("date")
            .tail(LOOKBACK)[["date", "pack", "ca_bp", "time_weight"]])
    s = STIR[c]
    ch = s.diff().dropna()
    lastch = float(ch.iloc[-1])
    zch = (lastch - float(ch.mean())) / float(ch.std())
    prev = s.index[-2]
    qual.append({
        "colour": c,
        "last_print": s.index[-1].date(),
        "prev_print": prev.date(),
        "gap_cal_days": int((s.index[-1] - prev).days),
        "last_bp_day": float(s.iloc[-1]),
        f"median_{ROBUST_MEDIAN_DAYS}d": float(s.tail(ROBUST_MEDIAN_DAYS).median()),
        "chg_1d": lastch,
        "chg_1d_z": float(zch),
        f"neg_CA_in_last_{LOOKBACK}": int((tail["ca_bp"] <= 0).sum()),
        "neg_CA_dates": ", ".join(d.date().isoformat()
                                  for d in tail.loc[tail["ca_bp"] <= 0, "date"]) or "-",
        "FLAG": ("JUMP " if abs(zch) > JUMP_Z else "") +
                ("NEGCA" if (tail["ca_bp"] <= 0).any() else ""),
    })
QUAL = pd.DataFrame(qual)
print(QUAL.round(3).to_string(index=False))

_flagged = QUAL[QUAL["FLAG"].str.strip() != ""]
if len(_flagged):
    print(f"\n{len(_flagged)} of {len(QUAL)} colours FLAGGED. On those rows the "
          "single-day reading in section 7 is not the best estimate of the level; "
          f"the {ROBUST_MEDIAN_DAYS}-day median columns are.")
    print("A negative CA inside the lookback means the CA panel admitted a "
          "no-arbitrage violation with gate_ok=True and the vol series silently "
          "dropped that day, so the 1-day change spans a gap.")
else:
    print("\nNo colour flagged: no non-positive CA in the lookback and no "
          f"one-day change beyond {JUMP_Z} sigma.")

# %% [markdown]
# ## 7. The screen
#
# Requirement: **the current spread and its z-score per (colour, pair), with the
# ADF p-value and half-life alongside so a reader can see immediately that the
# z-score is not tradable.**
#
# * `stir`, `long`, `spread` — bp/day, latest common observation.
# * `z_now` — z of today's spread on a 252-day trailing window.
# * `z_med5` — the same z on the 5-day median spread; the robust read (§6).
# * `z_lag` — the module's own lagged z, i.e. what the rejected rule would see.
# * `adf_p` — p-value of an ADF test on the spread. **> 0.05 means a unit root
#   cannot be rejected**, i.e. the spread is a random walk and its z-score is the
#   sampling distribution of one, not a dislocation.
# * `half_life` — OU half-life in business days from the AR(1) coefficient.
#   Reported for every cell, but it only *means* anything where `adf_p` is small.
# * `sd_ratio` — sd of the one-day change over sd of the level. Section 8.

# %%
COLS = ["colour", "pair", "asof", "n", "stir", "long", "spread", "spread_med5",
        "z_now", "z_med5", "z_lag", "adf_p", "half_life", "sd_ratio", "corr_ch"]
VIEW = SCREEN[COLS].copy()
VIEW["revert?"] = np.where(VIEW["adf_p"] <= ADF_ALPHA, "yes", "NO")
print(f"as of {ASOF.date()}  ({STALE_DAYS} calendar day(s) stale)\n")
print(VIEW.round(3).to_string(index=False))

# %%
print("SORTED BY |z_now| -- the cells a naive screen reader would look at first.")
print("Read the adf_p and half_life columns on the SAME row before anything else.\n")
top = VIEW.reindex(VIEW["z_now"].abs().sort_values(ascending=False).index).head(12)
print(top.round(3).to_string(index=False))

_big = VIEW[VIEW["z_now"].abs() >= LIVE.entry_z]
print(f"\n{len(_big)} of {len(VIEW)} cells are beyond the rejected rule's |z| = "
      f"{LIVE.entry_z} entry threshold.")
if len(_big):
    print(f"  of those, {int((_big['adf_p'] > ADF_ALPHA).sum())} cannot reject a "
          "unit root, so their z is not a dislocation measurement at all.")
print(f"\nsign census: {int((VIEW['spread'] > 0).sum())} of {len(VIEW)} cells have "
      "the FRONT END richer than the long end today.")

assert VIEW["spread"].notna().all(), "a cell reported no current spread"
assert (VIEW["asof"] == ASOF.date()).mean() > 0.9, (
    "more than 10% of cells are not current as of the panel's last date; the two "
    "legs are not landing on the same days and the screen is comparing vintages")

# %% [markdown]
# ## 8. Why the z-score in that table is not tradable
#
# This is the census, and it is the reason this notebook is a screen and not a
# strategy. Three measurements, each asserted.
#
# **(i) The legs barely move together.** The change correlation is the one that
# matters; two trending series correlate in levels for reasons that are not
# tradable.
#
# **(ii) Most spreads have a unit root.** An ADF p-value above 0.05 means the
# spread is indistinguishable from a random walk. A z-score entry *assumes* the
# answer to that question.
#
# **(iii) The ones that do revert, revert inside the noise.** For an OU process
# with half-life $h$, the ratio of one-day-change volatility to level volatility
# is $\sqrt{2(1-\phi)}$ with $\phi = e^{-\ln 2 / h}$. That identity is checked
# against the measured ratio below — and it is what fixes the tradability floor:
# a half-life of ~1.5 days implies a spread whose single-day noise is ~86% of its
# entire standard deviation. There is nothing to fill against at that ratio,
# whatever the round-trip cost happens to be.

# %%
print("(i) change correlation between the two legs:")
print(f"    max |corr_changes| over {len(SCREEN)} cells : "
      f"{SCREEN['corr_ch'].abs().max():.4f}")
print(f"    median |corr_changes|                  : "
      f"{SCREEN['corr_ch'].abs().median():.4f}")
print(f"    cells with |corr_changes| > 0.20       : "
      f"{int((SCREEN['corr_ch'].abs() > 0.20).sum())}")
assert SCREEN["corr_ch"].abs().max() < 0.30, (
    "a cell now shows a change-correlation above 0.30; the W3 premise ('the two "
    "legs have nothing to do with each other') would need re-deriving")

n_fail = int((SCREEN["adf_p"] > ADF_ALPHA).sum())
print(f"\n(ii) ADF census at alpha = {ADF_ALPHA}:")
print(f"    {n_fail} of {len(SCREEN)} cells FAIL to reject a unit root "
      f"({n_fail / len(SCREEN):.1%})")
assert n_fail / len(SCREEN) > 0.5, (
    "fewer than half the spreads are now random walks; the W3 verdict rests on "
    "this and would need re-deriving")

# %%
OU = SCREEN[["colour", "pair", "adf_p", "half_life", "sd_ratio"]].copy()
_phi = np.exp(-np.log(2.0) / OU["half_life"])
OU["sd_ratio_ou"] = np.sqrt(2.0 * (1.0 - _phi))
_ok = OU[["sd_ratio", "sd_ratio_ou"]].dropna()
_corr = float(_ok["sd_ratio"].corr(_ok["sd_ratio_ou"]))
print(f"(iii) OU identity check: measured sd(dS)/sd(S) vs sqrt(2(1-phi)) from the "
      f"fitted half-life\n      correlation over {len(_ok)} cells = {_corr:.4f}")
assert _corr > 0.95, (
    "the fitted half-lives no longer imply the measured one-day noise ratio; one "
    "of the two is wrong and the tradability argument below rests on both")

REV = OU[OU["adf_p"] <= ADF_ALPHA].sort_values("half_life")
print(f"\nthe {len(REV)} cells that DO reject a unit root:")
print(REV.round(3).to_string(index=False))

n_tradable = int(((SCREEN["adf_p"] <= ADF_ALPHA)
                  & (SCREEN["half_life"] >= HL_TRADABLE_FLOOR)).sum())
print(f"\ncells that both revert AND have a half-life >= {HL_TRADABLE_FLOOR} "
      f"business days: {n_tradable}")
assert n_tradable == 0, (
    f"{n_tradable} cell(s) now reject a unit root with a half-life of at least "
    f"{HL_TRADABLE_FLOOR} business days. That combination did not exist when this "
    "screener was written, and it is the one case in which the W3 rejection would "
    "have to be revisited rather than restated. Do not silence this assert.")
print("\nVERDICT (restated, not re-derived): every spread here is either a random")
print("walk or reverts so fast that one day of noise is most of its own standard")
print("deviation. Read the LEVELS in section 7 and 9. Do not read the z-score as")
print("a signal.")

# %% [markdown]
# ## 9. Term structure: where front-end and long-end vol sit today
#
# Requirement: **current STIR implied vol by pack colour and current long-end
# breakeven by pair, both in bp/day, on one chart.**
#
# The x-axis is a reading aid, not a computed maturity point: packs are placed at
# `t_mid` (the pack's own mid, in years), pairs at the mean forward-start of their
# two legs. Pairs that collide on that axis are nudged apart by a fixed offset so
# every one of the 15 is visible; the hover carries the true name.

# %%
def _last_tmid(colour: str) -> float:
    sub = PANEL[PANEL["rank"] == COLOUR_RANK[colour]].sort_values("date")
    sub = sub[sub["t_mid"].notna()]
    if sub.empty:
        raise AssertionError(f"no t_mid for {colour}; the x-axis cannot be placed")
    return float(sub["t_mid"].iloc[-1])


TMID = {c: _last_tmid(c) for c in COLOURS}


def mean_fwd_start(pair: str) -> float:
    starts = []
    for leg in pair.split("/"):
        m = re.match(r"^(\d+)Yx(\d+)Y$", leg)
        if m is None:
            return float("nan")
        starts.append(float(m.group(1)))
    return float(np.mean(starts))


TS_STIR = pd.DataFrame([{"key": c, "x": TMID[c],
                         "y": float(STIR[c].iloc[-1]),
                         "y_med": float(STIR[c].tail(ROBUST_MEDIAN_DAYS).median()),
                         "asof": STIR[c].index[-1].date()} for c in COLOURS])
TS_LONG = pd.DataFrame([{"key": q, "x": mean_fwd_start(q),
                         "y": float(LONG[q].iloc[-1]),
                         "y_med": float(LONG[q].tail(ROBUST_MEDIAN_DAYS).median()),
                         "asof": LONG[q].index[-1].date()} for q in PAIRS])
assert TS_STIR["x"].notna().all() and TS_LONG["x"].notna().all(), \
    "a pair name did not parse as <n>Yx<m>Y/<n>Yx<m>Y"
TS_LONG = TS_LONG.sort_values(["x", "key"]).reset_index(drop=True)
TS_LONG["x_plot"] = TS_LONG["x"] + TS_LONG.groupby("x").cumcount() * 0.55

print("STIR leg (bp/day):")
print(TS_STIR.round(3).to_string(index=False))
print("\nlong-end leg (bp/day):")
print(TS_LONG.drop(columns=["x_plot"]).round(3).to_string(index=False))
print(f"\nfront-end mean {TS_STIR['y'].mean():.2f} bp/day   "
      f"long-end mean {TS_LONG['y'].mean():.2f} bp/day   "
      f"gap {TS_STIR['y'].mean() - TS_LONG['y'].mean():+.2f}")

# %%
fig = go.Figure()
fig.add_trace(go.Scatter(
    x=TS_STIR["x"], y=TS_STIR["y"], mode="markers+lines+text", name="STIR pack CA -> Ho-Lee vol",
    text=TS_STIR["key"], textposition="top center",
    marker=dict(size=13, symbol="circle", color="#1f77b4"),
    line=dict(color="#1f77b4", width=2),
    hovertemplate="%{text}<br>%{y:.3f} bp/day<extra></extra>"))
fig.add_trace(go.Scatter(
    x=TS_STIR["x"], y=TS_STIR["y_med"], mode="markers", name=f"STIR, {ROBUST_MEDIAN_DAYS}d median",
    marker=dict(size=9, symbol="line-ew-open", color="#1f77b4",
                line=dict(width=3, color="#1f77b4")),
    hovertemplate="%{y:.3f} bp/day<extra></extra>"))
fig.add_trace(go.Scatter(
    x=TS_LONG["x_plot"], y=TS_LONG["y"], mode="markers", name="long-end flattener breakeven",
    text=TS_LONG["key"],
    marker=dict(size=12, symbol="diamond", color="#d62728"),
    hovertemplate="%{text}<br>%{y:.3f} bp/day<extra></extra>"))
fig.add_trace(go.Scatter(
    x=TS_LONG["x_plot"], y=TS_LONG["y_med"], mode="markers",
    name=f"long-end, {ROBUST_MEDIAN_DAYS}d median",
    text=TS_LONG["key"],
    marker=dict(size=9, symbol="line-ew-open", color="#d62728",
                line=dict(width=3, color="#d62728")),
    hovertemplate="%{text}<br>%{y:.3f} bp/day<extra></extra>"))
fig.update_layout(
    title=(f"Curve-implied volatility, front end vs long end -- {ASOF.date()} "
           f"({STALE_DAYS}d stale)"),
    xaxis_title="point on the curve (years forward; a reading aid, not a duration point)",
    yaxis_title="curve-implied vol (bp / day)",
    height=470, hovermode="closest",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0))
fig.show()

# %%
_bar = pd.concat([
    TS_STIR.assign(leg="STIR pack (front end)")[["key", "y", "leg"]],
    TS_LONG.assign(leg="long-end pair")[["key", "y", "leg"]]])
fig2 = go.Figure()
for leg, colr in (("STIR pack (front end)", "#1f77b4"), ("long-end pair", "#d62728")):
    sub = _bar[_bar["leg"] == leg]
    fig2.add_trace(go.Bar(x=sub["key"], y=sub["y"], name=leg, marker_color=colr,
                          hovertemplate="%{x}<br>%{y:.3f} bp/day<extra></extra>"))
fig2.update_layout(title=f"Same numbers, exact values -- {ASOF.date()}",
                   yaxis_title="curve-implied vol (bp / day)", height=430,
                   xaxis_tickangle=-45, barmode="group",
                   legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0))
fig2.show()

# %% [markdown]
# ## 10. The headline cell through time
#
# `Blues` against `15Yx5Y/20Yx10Y` — the colour whose positioning regression
# reproduced and the pair Citi published a full round trip for. Both legs, then
# the spread with its own trailing 1-sigma band. The band is drawn so the level
# can be read in context; the ADF p-value on this cell is printed with it so the
# band is not mistaken for a mean-reversion envelope.

# %%
_s, _lb = STIR[LIVE.colour], LONG[LIVE.pair]
H = W3.build_vol_spread_panel(_s, _lb, LIVE)
_roll = H["spread"].rolling(LIVE.z_window, min_periods=LIVE.min_periods)
H["mu"], H["sd"] = _roll.mean(), _roll.std(ddof=0)
_row = SCREEN[(SCREEN["colour"] == LIVE.colour) & (SCREEN["pair"] == LIVE.pair)].iloc[0]
print(f"{LIVE.colour} vs {LIVE.pair}: n={int(_row['n'])}  "
      f"adf_p={_row['adf_p']:.4f}  half_life={_row['half_life']:.2f} bdays  "
      f"corr_changes={_row['corr_ch']:+.4f}")
print(f"current: STIR {_row['stir']:.3f} - long {_row['long']:.3f} = "
      f"{_row['spread']:+.3f} bp/day   z_now {_row['z_now']:+.3f}  "
      f"z_med5 {_row['z_med5']:+.3f}  z_lag {_row['z_lag']:+.3f}")

fig3 = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.07,
                     row_heights=[0.5, 0.5],
                     subplot_titles=("both legs, bp/day",
                                     "spread = STIR - long end, with trailing +/-1 sigma"))
fig3.add_trace(go.Scatter(x=H.index, y=H["stir_iv"], name=f"STIR {LIVE.colour}",
                          line=dict(color="#1f77b4", width=1)), row=1, col=1)
fig3.add_trace(go.Scatter(x=H.index, y=H["long_be"], name=f"long end {LIVE.pair}",
                          line=dict(color="#d62728", width=1.6)), row=1, col=1)
fig3.add_trace(go.Scatter(x=H.index, y=H["mu"] + H["sd"], name="+1 sigma",
                          line=dict(color="rgba(128,128,128,0.5)", width=1),
                          showlegend=False), row=2, col=1)
fig3.add_trace(go.Scatter(x=H.index, y=H["mu"] - H["sd"], name="+/-1 sigma",
                          line=dict(color="rgba(128,128,128,0.5)", width=1),
                          fill="tonexty", fillcolor="rgba(128,128,128,0.15)"), row=2, col=1)
fig3.add_trace(go.Scatter(x=H.index, y=H["spread"], name="spread",
                          line=dict(color="#2ca02c", width=1.2)), row=2, col=1)
fig3.update_yaxes(title_text="bp/day", row=1, col=1)
fig3.update_yaxes(title_text="bp/day", row=2, col=1)
_verdict = ("a unit root is NOT rejected" if _row["adf_p"] > ADF_ALPHA
            else f"a unit root IS rejected; half-life {_row['half_life']:.2f} bdays")
fig3.update_layout(height=620, hovermode="x unified",
                   title=(f"{LIVE.colour} vs {LIVE.pair} -- ADF p = "
                          f"{_row['adf_p']:.3f} ({_verdict})"),
                   legend=dict(orientation="h", yanchor="bottom", y=1.04, x=0))
fig3.show()

assert len(H) > LIVE.min_periods, "the headline cell has too little history to plot"
assert H["spread"].notna().iloc[-1], "the headline cell has no current spread"

# %% [markdown]
# ## 11. The screen, as a saved artifact
#
# Written next to the panels so the reading can be diffed against tomorrow's.
# The file is stamped with the as-of date and the staleness, because a screen
# without those is indistinguishable from history.

# %%
OUT = DATA / "w3_screen_latest.csv"
SAVE = SCREEN.copy()
SAVE.insert(0, "run_at", RUN_AT.isoformat())
SAVE.insert(1, "stale_days", STALE_DAYS)
SAVE.to_csv(OUT, index=False)
print(f"wrote {OUT}  ({len(SAVE)} cells)")
print(f"columns: {list(SAVE.columns)}")
assert OUT.exists() and OUT.stat().st_size > 0

_summary = {
    "run_at": RUN_AT.isoformat(),
    "asof": ASOF.date().isoformat(),
    "stale_days": STALE_DAYS,
    "cells": int(len(SCREEN)),
    "front_end_mean_bp_day": round(float(TS_STIR["y"].mean()), 4),
    "long_end_mean_bp_day": round(float(TS_LONG["y"].mean()), 4),
    "cells_front_end_rich": int((SCREEN["spread"] > 0).sum()),
    "cells_beyond_entry_z": int((SCREEN["z_now"].abs() >= LIVE.entry_z).sum()),
    "cells_failing_adf": int((SCREEN["adf_p"] > ADF_ALPHA).sum()),
    "cells_tradable_by_hl": int(n_tradable),
    "max_abs_corr_changes": round(float(SCREEN["corr_ch"].abs().max()), 4),
    "flagged_colours": _flagged["colour"].tolist(),
}
print("\n" + json.dumps(_summary, indent=1))

# %% [markdown]
# ## 12. Reading this notebook
#
# * **It is a screen, not a signal.** The strategy it was cut from is rejected,
#   and section 8 re-derives the reason on live data every run rather than citing
#   it: the change-correlation between the legs is tiny, most spreads cannot
#   reject a unit root, and the ones that can revert so fast that a single day's
#   noise is most of their standard deviation. The assert in section 8 is written
#   so that it **fails loudly** if a cell ever becomes both stationary and slow —
#   that is the one condition under which the W3 rejection would need revisiting.
#
# * **What is worth reading is the LEVELS.** Sections 7 and 9 say where front-end
#   and long-end curve-implied vol sit against each other today, in the same unit,
#   from two markets that never have to agree. Neither number is an option price.
#
# * **Read `z_med5` before `z_now`.** The STIR leg is jumpy, and section 6 checks
#   the last print for the two failure modes this package has already been bitten
#   by: a non-positive CA (dropped silently, so the "one-day" change may span a
#   gap) and an outsized one-day move. Where a colour is flagged, the single-day
#   z is a statement about one print.
#
# * **`z_lag` is not a second opinion.** It is the same statistic one day earlier
#   — asserted to the bit in section 5. Where `z_now` and `z_lag` disagree
#   sharply, that disagreement *is* one day of the STIR leg's noise, which is the
#   quantitative content of section 8.
#
# * **The unit is bp/day on both legs and that is load-bearing.** `holee`
#   returns bp/**year**; `be_daily_analytic` is bp/**day**. Section 3 checks the
#   $\sqrt{252}$ identity on the live print, and section 2 asserts each leg's
#   median lands in a range a wrong-unit series could not reach.
#
# * **Zeros in `be_daily_analytic` are truncations, not readings.** They are the
#   `carry >= 0` case and are dropped, not averaged in — see the `trunc_frac`
#   column in section 2, which reaches 54% on `20Yx5Y/25Yx5Y`.
#
# Source module: `RVUtils/ConvexityRV/w3_ca_vs_longend.py`.
# Diagnostics run: `notebooks/backtests/convexity_rv/_w3_ca_vs_longend_run.py`.
