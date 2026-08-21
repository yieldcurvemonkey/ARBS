# %% [markdown]
# # W3 — SOFR pack convexity against ultra-long curve convexity, as a vol RV trade
#
# > *"We continue to favor **shorting Blues convexity adjustment as a short vol
# > proxy**"* … *"shorting Blues convexity adjustment via **long SOFR futures
# > against pay in swaps** as a short vol proxy"*
# >
# > — Citi, *Rates Vol Lab: Forward steepener and vol divergence*, 12-Jun-2023
#
# > *"Because long-dated forward steepeners have net negative convexity, we can
# > back out implied yield breakevens from the carry and compare them to the
# > recent realized yield moves. **Having a breakeven/realized vol ratio allows
# > us to compare the positive carry of various long-dated forward steepeners in
# > a standardized fashion**"*
# >
# > — same note, l.156-160
#
# One Citi note carries both halves: a 13-row SOFR pack convexity screen and an
# ultra-long forward curve screen whose decision column is a **daily breakeven
# vol**. That invites the obvious trade — the pack's convexity adjustment
# inverts through Ho-Lee into a curve-implied vol with no fitted parameter, the
# ultra-long flattener's breakeven is a curve-implied vol on the same ruler, and
# the spread between them is a front-end-versus-back-end vol RV position.
#
# **The verdict is negative, and it is decided in section 5, before any trade.**
# The two legs' *changes* barely correlate (max |ρ| = 0.112 over sixteen
# colour × pair combinations, most between 0.00 and 0.08, several negative), and
# fourteen of the sixteen spreads **fail to reject a unit root**. A z-score entry
# assumes the spread reverts. On fourteen of sixteen that assumption is rejected
# outright; on the two that do reject, the half-lives are **1.22 and 1.62 days**,
# far too fast to pay a round trip.
#
# Sections 7-10 then quantify what the rule would have earned anyway — because a
# rejected premise is a reason to bound the answer, not to skip it — and section
# 9 shows that the headline P&L of the naive version is **manufactured by fading
# one day of noise in its own marks**: a placebo built from two series with *no*
# relationship at all scores a *higher* Sharpe than the real data does.

# %%
import datetime as dt
import json
import math
import os
import pathlib
import sys
import time

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

REPO = pathlib.Path.cwd()
while not (REPO / "RVUtils").exists() and REPO != REPO.parent:
    REPO = REPO.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import numpy as np
import pandas as pd

import plotly.graph_objects as go
import plotly.io as pio
pio.renderers.default = "plotly_mimetype+notebook_connected"

from RVUtils.ConvexityRV import w3_ca_vs_longend as W3
from RVUtils.ConvexityRV.holee import implied_vol_from_ca_bp
from RVUtils.ConvexityRV.strat1_threeway import expected_max_sharpe_under_null

DATA = REPO / "notebooks" / "data" / "convexity_rv"
pd.set_option("display.width", 250, "display.max_columns", 40)
print(f"repo {REPO}")
print(f"data {DATA}   exists={DATA.exists()}")

# %% [markdown]
# ## 1. The config
#
# Every knob and the reason for its value. `W3Config` carries the defaults; they
# are restated here so the notebook is self-describing. The three added below
# `W3Config` govern the **bounded panel simulation** in section 7 and are not
# part of the module, because the module deliberately stops at `entry_state` —
# there is no backtest function in `w3_ca_vs_longend.py`, and section 7 explains
# why one was not written.

# %%
CFG = W3.W3Config()
print(json.dumps(CFG.to_dict(), indent=1, default=str))

#: The 4x4 grid the diagnostics were measured over. Four pack colours spanning
#: the front (Reds, ~1y) to the deferred strip (Golds, ~4y), and four ultra-long
#: DV01-neutral flattener pairs, including the 15Yx5Y/20Yx10Y that Citi actually
#: traded and published a full round trip for.
COLOURS = ("Reds", "Greens", "Blues", "Golds")
PAIRS = ("15Yx5Y/20Yx10Y", "10Yx10Y/20Yx10Y", "15Yx5Y/25Yx10Y", "20Yx5Y/25Yx5Y")
CELLS = [(c, p) for c in COLOURS for p in PAIRS]

#: Round-trip execution charge, in the SAME units as the spread (bp/day of
#: curve-implied vol). Section 8 shows this is generous: the CA leg's bid/offer
#: ALONE maps to about twice the break-even cost.
COST_BP_ROUND_TRIP = 0.5

#: Returns spanning a calendar gap wider than this are dropped rather than
#: booked as one day's P&L. The joint index is far from contiguous — coverage
#: runs 27%-90% of business days with gaps up to 422 calendar days (section 6) —
#: and a single 400-day jump booked as a daily return is a fabricated number.
MAX_GAP_DAYS = 7

#: Reps in the empirical null of section 9. Seeded, so the printed p-values are
#: reproducible.
NULL_REPS = 400

print(f"\n{len(CELLS)} cells   cost {COST_BP_ROUND_TRIP} bp round trip   "
      f"gap mask {MAX_GAP_DAYS}d   null reps {NULL_REPS}")

# %% [markdown]
# ## 2. Does the machine give the right answer to questions we already know?
#
# The whole verdict rests on one statistic — an ADF test on the spread — so the
# checker is graded against **both** of its known answers, live, in this
# notebook. Not a stored number: the test is re-run here.
#
# * Two **independent random walks** must **fail** to reject a unit root. If ADF
#   rejected here, section 5's "fourteen of sixteen fail to reject" would mean
#   nothing.
# * An **OU spread** (two series sharing a common stochastic trend plus
#   independent noise) must **reject**, with a finite half-life. If it did not,
#   the test would be incapable of finding a relationship that is there.
#
# Then the unit conversion, which is section 3's subject, is pinned exactly.

# %%
_idx = pd.bdate_range("2021-01-04", periods=1200)

# (a) two independent random walks -- must NOT reject
_r = np.random.default_rng(19)
_rw_a = pd.Series(np.cumsum(_r.normal(0, 1, 1200)), index=_idx)
_rw_b = pd.Series(np.cumsum(_r.normal(0, 1, 1200)), index=_idx)
_d_rw = W3.link_diagnostics(_rw_a, _rw_b)

# (b) a genuinely cointegrated pair -- must reject
_r2 = np.random.default_rng(23)
_common = np.cumsum(_r2.normal(0, 1, 1200))
_ou_a = pd.Series(_common + _r2.normal(0, 0.3, 1200), index=_idx)
_ou_b = pd.Series(_common + _r2.normal(0, 0.3, 1200), index=_idx)
_d_ou = W3.link_diagnostics(_ou_a, _ou_b)

print(f"two independent random walks : ADF p = {_d_rw['spread_adf_p']:.4f}   "
      f"half-life = {_d_rw['spread_half_life_days']:.2f}")
print(f"a cointegrated (OU) pair     : ADF p = {_d_ou['spread_adf_p']:.2e}   "
      f"half-life = {_d_ou['spread_half_life_days']:.2f}")

assert _d_rw["spread_adf_p"] > 0.05, (
    f"ADF p={_d_rw['spread_adf_p']:.4f} rejected a unit root on the difference of "
    "two INDEPENDENT random walks. The checker is not measuring what it claims "
    "to, and every stationarity verdict below is void.")
assert _d_ou["spread_adf_p"] < 0.05, (
    "ADF failed to reject on a genuinely stationary spread; the checker has no "
    "power and 'fails to reject' below would be uninformative.")
assert 0 < _d_ou["spread_half_life_days"] < 60
print("\nOK: the checker misses nothing that is there, and invents nothing that is not.")

# %%
# (c) the unit conversion, pinned exactly. bp/YEAR in, bp/DAY out, factor sqrt(252).
_p = pd.DataFrame({
    "date": pd.bdate_range("2021-01-04", periods=200),
    "rank": 13, "pack": [f"P{i // 63}" for i in range(200)], "colour": "Blues",
    "ca_bp": 12.0, "time_weight": 12.25, "gate_ok": True,
})
_s = W3.stir_implied_vol_series(_p, W3.W3Config())
_annual = implied_vol_from_ca_bp(12.0, [math.sqrt(12.25)], convention="citi")
print(f"CA 12.0bp, time_weight 12.25 -> {_annual:.4f} bp/YEAR "
      f"-> {_s.iloc[0]:.4f} bp/DAY   (ratio {_annual / _s.iloc[0]:.6f})")
assert _s.iloc[0] == float(np.float64(_annual) / math.sqrt(252.0)), "not exactly sqrt(252)"
assert abs(_annual / _s.iloc[0] - math.sqrt(252.0)) < 1e-9

# (d) the guard must FIRE on a series left in annual units
_p_bad = _p.copy()
_p_bad["ca_bp"] = 2500.0                     # implies a vol far above any daily figure
_fired = False
try:
    W3.stir_implied_vol_series(_p_bad, W3.W3Config())
except ValueError as exc:
    _fired = "bp/DAY" in str(exc)
    print(f"\nguard fired: {exc}")
assert _fired, "the 0.5-40 bp/day guard did not fire on a wrong-unit series"
print("\nOK: sqrt(252) is exact and the wrong-unit guard is live.")

# %% [markdown]
# ## 3. The two legs, and the unit trap that nearly ate this notebook
#
# **STIR leg.** A pack's convexity adjustment is a variance quantity. Ho-Lee
# gives `CA = ½·σ²·mean(T1²)`, which inverts in closed form, so
# `σ = sqrt(2·CA / mean(T1²))` is a normal vol with **no fitted parameter
# anywhere in it**. Citi's own definition of the screen it comes from:
#
# > *"Convexity adjustments for 1y SOFR packs are computed as the spread between
# > the pack's rate (the average of 4 SOFR rates in the pack) and matched-maturity
# > forward 1y CME swap rate. The model … is the **Ho-Lee model calibrated to
# > cap/floor vols**. Implied vol is calculated by matching the model to the
# > observed convexity adjustment."*
# >
# > — Citi, Figure 58, close 6/9/23
#
# **Long-end leg.** Citi's daily breakeven on a DV01-neutral ultra-long forward
# flattener:
#
# > *"the daily breakeven (**the daily move in rates that yields a convexity gain
# > offsetting a negative daily carry**)"*
#
# Neither is a traded option price. That is the point — they are two independent
# readings of what the market charges for convexity, one at the very front and
# one at the very back.
#
# ### The trap
#
# `holee.implied_vol_from_ca_bp` returns **bp per YEAR**. `be_daily_analytic` is
# **bp per DAY**. The first run of this module spread them as they came and
# printed a STIR leg averaging 100-135 against a long-end leg averaging 2.5-4.0 —
# a "spread" of about 100bp that was almost entirely `sqrt(252) ≈ 15.9`.
# **Correlation is scale-invariant, so every link diagnostic below was untouched
# by the bug and would have been reported as-is**; every level, spread and
# z-score was wrong. Both legs now leave the module in bp/day and the guard in
# section 2(d) rejects a median outside 0.5-40.

# %%
panel = pd.read_parquet(DATA / "strat2_q20_panel.parquet")
panel["date"] = pd.to_datetime(panel["date"])
panel = panel[panel["gate_ok"]]            # the CA gate; dropping it drifts every number
rac = pd.read_parquet(DATA / "rac_screen_panel.parquet")
rac["date"] = pd.to_datetime(rac["date"])
print(f"CA panel {panel.shape} (gate_ok only)   RAC screen panel {rac.shape}")

STIR = {c: W3.stir_implied_vol_series(panel, W3.W3Config(colour=c)) for c in COLOURS}
LONG = {p: (rac[rac["pair"] == p].set_index("date")["be_daily_analytic"]
            .replace(0.0, np.nan).dropna().sort_index()) for p in PAIRS}

LEGS = pd.DataFrame(
    [{"leg": f"STIR {c}", "n": len(s), "median_bp_day": s.median(),
      "sd": s.std(), "first": s.index.min().date(), "last": s.index.max().date()}
     for c, s in STIR.items()] +
    [{"leg": f"LONG {p}", "n": len(s), "median_bp_day": s.median(),
      "sd": s.std(), "first": s.index.min().date(), "last": s.index.max().date()}
     for p, s in LONG.items()])
print("\nboth legs, in bp/DAY:")
print(LEGS.round(3).to_string(index=False))

for c, s in STIR.items():
    assert 0.5 <= float(s.median()) <= 40.0, f"{c} STIR leg is not in bp/day"
for p, s in LONG.items():
    assert 0.5 <= float(s.median()) <= 40.0, f"{p} long leg is not in bp/day"
print("\nOK: every leg's median is inside the 0.5-40 bp/day band.")
print("The pre-fix STIR leg would have read "
      f"{STIR['Blues'].median() * math.sqrt(252):.1f} against a long leg of "
      f"{LONG['15Yx5Y/20Yx10Y'].median():.1f} -- that is the ~100bp 'spread'.")

# %%
_c, _p = CFG.colour, CFG.pair
fig = go.Figure()
fig.add_trace(go.Scatter(x=STIR[_c].index, y=STIR[_c].to_numpy(),
                         name=f"STIR {_c} (Ho-Lee, bp/day)", mode="lines"))
fig.add_trace(go.Scatter(x=LONG[_p].index, y=LONG[_p].to_numpy(),
                         name=f"long-end {_p} breakeven (bp/day)", mode="lines"))
fig.add_trace(go.Scatter(x=STIR[_c].index, y=(STIR[_c] * math.sqrt(252)).to_numpy(),
                         name="STIR leg IF LEFT IN bp/YEAR (the bug)", mode="lines",
                         line=dict(dash="dot"), opacity=0.45))
fig.update_layout(title="W3 — both legs on the same ruler, and what the unit bug looked like",
                  yaxis_title="curve-implied vol, bp/day", height=430,
                  legend=dict(orientation="h", y=-0.18))
fig.show()

# %% [markdown]
# ## 4. The sign probe
#
# There is no `IRSwapsMDP` package to probe here — this trade's P&L is a spread
# of two computed vols, so the thing that can be backwards is the **simulator's
# sign convention**, not a swap's PV01. It is re-derived from the code on every
# run against two synthetic spreads whose answers are known:
#
# * a **mean-reverting (OU)** spread — a rule that fades a z-score must **make**
#   money on it;
# * an **explosive (trending)** spread — the same rule must **lose** on it.
#
# `entry_state` returns `+1` when the STIR-implied vol is *rich* against the long
# end, i.e. sell the pack convexity and buy the long-end convexity, which profits
# when the spread **falls**. So P&L is `−position × Δspread`. If that were
# inverted, the OU probe would lose and the trending probe would win.

# %%
def simulate(stir: pd.Series, long_be: pd.Series, cfg: W3.W3Config, *,
             exec_lag: int = 1, cost: float = COST_BP_ROUND_TRIP,
             max_gap: int = MAX_GAP_DAYS) -> dict | None:
    """Bounded panel simulation of the spread rule, in spread units (bp/day of vol).

    Not a `QueryDrivenBacktest`. See section 7 for why one was not run.

    ``exec_lag=0`` books the move from ``t-1`` to ``t`` against the state decided
    from the mark at ``t-1``, i.e. it assumes execution AT the mark that produced
    the signal. ``exec_lag=1`` waits one day. Section 9 shows the difference is
    the whole result.

    Costs are charged ``0.5 * cost * |Δposition|``, so a full open-and-close round
    trip costs exactly ``cost``.
    """
    sp = W3.build_vol_spread_panel(stir, long_be, cfg)
    if sp.empty or sp["z"].notna().sum() < 30:
        return None
    st = W3.entry_state(sp, cfg)

    ret = sp["spread"].diff()
    gap = sp.index.to_series().diff().dt.days
    masked = int(((gap > max_gap) & ret.notna()).sum())
    masked_bp = float(ret.where(gap > max_gap).abs().sum())
    ret = ret.where(gap <= max_gap)

    pos = st.shift(exec_lag) if exec_lag else st
    pnl = (-pos * ret).fillna(0.0)
    turn = pos.diff().abs().fillna(0.0)
    cst = 0.5 * cost * turn
    net = pnl - cst

    # Episode holds are counted on the JOINT index, not on either leg's own
    # index. On a 27%-90% covered join those differ by a factor of several, and
    # an earlier draft of this cell counted them on the STIR leg's index and
    # reported holds of 469-587 observations for episodes whose true hold is 62.
    loc = {d: i for i, d in enumerate(st.index)}
    eps, cur, s0 = [], 0, None
    for t, v in st.items():
        if v != cur:
            if cur != 0:
                eps.append((s0, t, cur, loc[t] - loc[s0]))
            cur, s0 = v, t
    if cur != 0:
        eps.append((s0, st.index[-1], cur, loc[st.index[-1]] - loc[s0]))
    lens = [e[3] for e in eps]

    return {
        "n_obs": int(len(sp)), "days_on": int((st != 0).sum()),
        "frac_on": float((st != 0).mean()), "episodes": len(eps),
        "median_hold": float(np.median(lens)) if lens else np.nan,
        "mean_hold": float(np.mean(lens)) if lens else np.nan,
        "gross": float(pnl.sum()), "cost": float(cst.sum()), "net": float(net.sum()),
        "gross_sr": float(pnl.mean() / pnl.std() * math.sqrt(252)) if pnl.std() > 0 else np.nan,
        "net_sr": float(net.mean() / net.std() * math.sqrt(252)) if net.std() > 0 else np.nan,
        "t_gross": float(pnl.mean() / pnl.std() * math.sqrt(len(pnl))) if pnl.std() > 0 else np.nan,
        "bp_per_trade": float(pnl.sum() / len(eps)) if eps else np.nan,
        "be_cost": float(pnl.sum() / (turn.sum() / 2.0)) if turn.sum() > 0 else np.nan,
        "years": (sp.index[-1] - sp.index[0]).days / 365.25,
        "masked_returns": masked, "masked_bp": masked_bp,
        "episodes_list": eps,
    }


_n = 1500
_pidx = pd.bdate_range("2021-01-04", periods=_n)
_flat = pd.Series(np.full(_n, 3.0), index=_pidx)

_rg = np.random.default_rng(7)
_ou = np.zeros(_n)
for _i in range(1, _n):
    _ou[_i] = 0.97 * _ou[_i - 1] + _rg.normal(0, 1.0)     # half-life ~23 days
PROBE_OU = simulate(pd.Series(6.5 + _ou, index=_pidx), _flat, W3.W3Config(),
                    exec_lag=1, cost=0.0, max_gap=10_000)

_rg2 = np.random.default_rng(11)
_mom = np.zeros(_n)
for _i in range(1, _n):
    _mom[_i] = float(np.clip(1.02 * _mom[_i - 1] + _rg2.normal(0, 1.0), -60, 60))
PROBE_MOM = simulate(pd.Series(6.5 + _mom, index=_pidx), _flat, W3.W3Config(),
                     exec_lag=1, cost=0.0, max_gap=10_000)

print(f"OU (must WIN)        gross {PROBE_OU['gross']:+8.2f} bp   "
      f"SR {PROBE_OU['gross_sr']:+.3f}   t {PROBE_OU['t_gross']:+.2f}   "
      f"{PROBE_OU['episodes']} episodes, median hold {PROBE_OU['median_hold']:.0f}")
print(f"explosive (must LOSE) gross {PROBE_MOM['gross']:+8.2f} bp   "
      f"SR {PROBE_MOM['gross_sr']:+.3f}   t {PROBE_MOM['t_gross']:+.2f}   "
      f"{PROBE_MOM['episodes']} episodes, median hold {PROBE_MOM['median_hold']:.0f}")

assert PROBE_OU["gross"] > 0 and PROBE_OU["gross_sr"] > 0.5, (
    "the rule LOSES on a spread that genuinely mean-reverts; the P&L sign is "
    "inverted and every number below has the wrong sign")
assert PROBE_OU["t_gross"] > 2.0
assert PROBE_MOM["gross"] < 0, (
    "the rule MAKES money fading an explosive spread; the sign convention is "
    "not what the docstring says")
print("\nOK: +1 = STIR rich = short the spread, and P&L = -position x d(spread).")

# %% [markdown]
# ## 5. The link diagnostics — and this is where the verdict is decided
#
# **This section runs before any trade on purpose.** The honest failure mode for
# a spread trade is that the two legs have nothing to do with each other, in
# which case their "spread" is two random walks and any mean-reversion signal on
# it is fitting the sampling distribution of a unit root. From the module's own
# docstring:
#
# > *"`link_diagnostics` reports the correlation of levels **and of changes**,
# > and the changes number is the one that matters — two trending series
# > correlate in levels for reasons that have nothing to do with a tradable
# > relationship. This module reports it whether or not it is flattering."*
#
# The table is recomputed live below and then asserted against the stored
# artifact `w3_link_diagnostics.csv`, so a drift in either the panel or the code
# fails here rather than being quietly absorbed.

# %%
DIAG = pd.DataFrame([{"colour": c, "pair": p,
                      **W3.link_diagnostics(STIR[c], LONG[p])} for c, p in CELLS])
_cols = ["colour", "pair", "n", "corr_levels", "corr_changes", "beta_changes",
         "stir_mean", "long_mean", "spread_adf_p", "spread_half_life_days"]
print(DIAG[_cols].round(4).to_string(index=False))

REF = pd.read_csv(DATA / "w3_link_diagnostics.csv")
_m = DIAG.merge(REF, on=["colour", "pair"], suffixes=("", "_ref"))
assert len(_m) == len(CELLS), "the stored artifact does not cover the same 16 cells"
for _c2 in ("n", "corr_levels", "corr_changes", "beta_changes", "spread_adf_p",
            "spread_half_life_days", "stir_mean", "long_mean"):
    _dmax = float((_m[_c2] - _m[_c2 + "_ref"]).abs().max())
    assert _dmax < 1e-6, f"{_c2} does not reproduce the stored artifact ({_dmax:.2e})"
print(f"\nOK: all 16 cells reproduce {DATA / 'w3_link_diagnostics.csv'} to <1e-6.")

# %%
_nonstat = int((DIAG["spread_adf_p"] > 0.05).sum())
_maxcorr = float(DIAG["corr_changes"].abs().max())
_medcorr = float(DIAG["corr_changes"].abs().median())
_neg = int((DIAG["corr_changes"] < 0).sum())

print(f"change correlation : max |rho| {_maxcorr:.4f}   median |rho| {_medcorr:.4f}   "
      f"{_neg} of {len(DIAG)} NEGATIVE")
print(f"stationarity       : {_nonstat} of {len(DIAG)} FAIL to reject a unit root at 5%")
print("\nthe two that DO reject:")
print(DIAG.loc[DIAG["spread_adf_p"] <= 0.05,
               ["colour", "pair", "n", "spread_adf_p", "spread_half_life_days"]]
      .round(4).to_string(index=False))

assert _nonstat == 14, f"expected 14 of 16 non-stationary, got {_nonstat}"
assert _maxcorr < 0.12, f"max |change correlation| {_maxcorr:.4f} is no longer < 0.12"
assert _medcorr < 0.05
assert (DIAG.loc[DIAG["spread_adf_p"] <= 0.05, "spread_half_life_days"] < 2.0).all(), (
    "a rejecting cell now has a half-life over 2 days, which would change the "
    "verdict in section 5.2")

print("\nVERDICT (this is the result): the two legs' CHANGES are uncorrelated,")
print(f"and {_nonstat}/16 spreads are indistinguishable from a random walk. A z-score")
print("entry ASSUMES the spread reverts. That assumption is rejected here.")

# %% [markdown]
# ### 5.1 The two that reject are not a reprieve
#
# Both are **Reds** — and Reds is the shallowest colour, carrying the smallest
# convexity adjustment of the four. A small CA makes the Ho-Lee inversion noisy,
# because `σ = sqrt(2·CA/w)` has `dσ/dCA = σ/(2·CA)`, which blows up as CA falls.
# Measurement noise in a level looks exactly like one-day mean reversion, and ADF
# rejects on that bounce rather than on any tradable relationship.
#
# Both also have the **thinnest joint coverage** in the grid, so their "days" are
# observation steps stitched across months-long holes.

# %%
COV = []
for c, p in CELLS:
    df = pd.concat([STIR[c].rename("s"), LONG[p].rename("l")], axis=1).dropna()
    span = pd.bdate_range(df.index.min(), df.index.max())
    gaps = df.index.to_series().diff().dt.days.dropna()
    COV.append({"colour": c, "pair": p, "n": len(df), "span_bdays": len(span),
                "coverage": len(df) / len(span), "max_gap_days": float(gaps.max()),
                "adf_p": float(DIAG.loc[(DIAG.colour == c) & (DIAG.pair == p),
                                        "spread_adf_p"].iloc[0])})
COV = pd.DataFrame(COV)
print(COV.round(3).to_string(index=False))

_rej = COV[COV["adf_p"] <= 0.05]
print(f"\nthe two rejecting cells have coverage {_rej['coverage'].min():.2f}-"
      f"{_rej['coverage'].max():.2f} of business days, with gaps up to "
      f"{_rej['max_gap_days'].max():.0f} calendar days.")
assert (_rej["coverage"] < 0.40).all(), (
    "a rejecting cell now has dense coverage, so the 'stitched across holes' "
    "caveat no longer applies to it and 5.1 needs re-deriving")
print("A half-life quoted in 'days' on that index is a half-life in OBSERVATIONS.")

# %%
print("daily-change autocorrelation. For a random walk observed with iid")
print("measurement error, rho1(delta) has a hard FLOOR of -0.5, reached only")
print("when the underlying does not move at all:\n")
AC = pd.DataFrame(
    [{"series": f"STIR {c}", "level_sd": s.std(), "dchg_sd": s.diff().std(),
      "rho1_dchg": s.diff().dropna().autocorr(1)} for c, s in STIR.items()] +
    [{"series": f"LONG {p}", "level_sd": s.std(), "dchg_sd": s.diff().std(),
      "rho1_dchg": s.diff().dropna().autocorr(1)} for p, s in LONG.items()])
print(AC.round(4).to_string(index=False))

_st_ac = AC[AC["series"].str.startswith("STIR")]["rho1_dchg"]
assert (_st_ac < -0.4).all(), "the STIR legs no longer bounce; section 9 needs re-deriving"
print(f"\nEvery STIR leg sits at or past the floor ({_st_ac.min():+.4f} to "
      f"{_st_ac.max():+.4f}).")
print("Greens and Blues are PAST -0.5, which no random-walk-plus-iid-noise model")
print("can produce: the daily mark bounces harder than measurement error alone.")
print("Section 9 shows this is what the naive P&L is actually harvesting.")

# %%
_c, _p = CFG.colour, CFG.pair
_j = pd.concat([STIR[_c].rename("stir"), LONG[_p].rename("long")], axis=1).dropna().diff().dropna()
fig = go.Figure()
fig.add_trace(go.Scatter(x=_j["long"], y=_j["stir"], mode="markers",
                         marker=dict(size=4, opacity=0.5), name="daily changes"))
_b = np.polyfit(_j["long"], _j["stir"], 1)
_xs = np.linspace(_j["long"].min(), _j["long"].max(), 20)
fig.add_trace(go.Scatter(x=_xs, y=np.polyval(_b, _xs), mode="lines",
                         name=f"beta {_b[0]:+.3f}"))
_rho = float(_j["stir"].corr(_j["long"]))
fig.update_layout(
    title=f"W3 — the link that is not there: {_c} vs {_p}, daily changes, rho = {_rho:+.4f}",
    xaxis_title="d(long-end breakeven), bp/day", yaxis_title="d(STIR implied vol), bp/day",
    height=430)
fig.show()

# %% [markdown]
# ## 6. What the rule trades, and why its clock is wrong
#
# A funnel, per cell: how many joint observations exist, how many days the rule
# is on, how many episodes it takes, and how long it holds them.
#
# The mismatch to look for: the two spreads that *do* revert have half-lives of
# **1.22 and 1.62 days**, while a 252-day z-window with 1.5/0.5 hysteresis holds
# positions for a median of one to seven observations and is on the trade
# 15%-48% of the time. Even on the two cells where reversion exists, this rule is
# not built to harvest it.

# %%
SIM1 = pd.DataFrame([{"colour": c, "pair": p,
                      **{k: v for k, v in simulate(STIR[c], LONG[p],
                                                   W3.W3Config(colour=c, pair=p),
                                                   exec_lag=1).items()
                         if k != "episodes_list"}} for c, p in CELLS])
_f = SIM1[["colour", "pair", "n_obs", "days_on", "frac_on", "episodes",
           "median_hold", "mean_hold", "masked_returns", "masked_bp"]]
print(_f.round(3).to_string(index=False))

print(f"\ntotal cells {len(SIM1)}   total episodes {int(SIM1['episodes'].sum())}   "
      f"median hold {SIM1['median_hold'].median():.1f} obs   "
      f"frac_on {SIM1['frac_on'].min():.2f}-{SIM1['frac_on'].max():.2f}")
print(f"gap-masked returns dropped: {int(SIM1['masked_returns'].sum())} "
      f"({SIM1['masked_bp'].sum():.1f} bp of |move| not booked as daily P&L)")

_hl = DIAG.loc[DIAG["spread_adf_p"] <= 0.05, "spread_half_life_days"]
assert SIM1["median_hold"].median() > _hl.max(), (
    "the rule now holds for less than the fastest measured half-life; the "
    "clock-mismatch argument in section 6 no longer holds")
print(f"\nrule holds a median of {SIM1['median_hold'].median():.1f} observations; the only")
print(f"measured half-lives are {_hl.min():.2f} and {_hl.max():.2f}. The clock is wrong")
print("even where reversion exists.")

# %% [markdown]
# ### 6.1 The holding period is bimodal, and it is not measured in days
#
# The median hold hides the shape. Most episodes are one-to-three-observation
# flickers; a small number run for months. And because the joint index is sparse,
# an episode's **calendar** span and its **observation** count are different
# quantities — a position can sit open across two calendar years while being
# sixty-odd marks. That is not a stylistic point: it means the rule holds risk
# through long stretches in which neither leg is priced at all.

# %%
ALL_EPS = []
for c, p in CELLS:
    for _a, _b, _side, _h in simulate(STIR[c], LONG[p],
                                      W3.W3Config(colour=c, pair=p),
                                      exec_lag=1)["episodes_list"]:
        ALL_EPS.append({"colour": c, "pair": p, "side": _side,
                        "entry": _a, "exit": _b, "obs_held": _h,
                        "calendar_days": int((_b - _a).days)})
ALL_EPS = pd.DataFrame(ALL_EPS)

print("hold, in OBSERVATIONS of the joint index:")
print(ALL_EPS["obs_held"].describe(percentiles=[.25, .5, .75, .9, .95, .99]).round(2).to_string())
print(f"\nepisodes held <= 3 observations : {(ALL_EPS['obs_held'] <= 3).mean():.1%}")
print(f"longest episode                 : {ALL_EPS['obs_held'].max()} observations")
_worst = ALL_EPS.loc[ALL_EPS["calendar_days"].idxmax()]
print(f"widest calendar span            : {_worst['calendar_days']} days "
      f"({_worst['entry'].date()} -> {_worst['exit'].date()}) but only "
      f"{_worst['obs_held']} observations "
      f"[{_worst['colour']} {_worst['pair']}]")

assert float((ALL_EPS["obs_held"] <= 3).mean()) > 0.5, (
    "the book is no longer dominated by very short episodes")
assert int(_worst["calendar_days"]) > 365 and int(_worst["obs_held"]) < 200, (
    "calendar span and observation count no longer diverge; the sparse-index "
    "caveat in 6.1 needs re-deriving")
print("\nSo 'median hold 2' and 'one position open for two years' are both true,")
print("of the same book. Neither clock matches a 1.2-day half-life.")

# %% [markdown]
# ## 7. The bounded panel simulation
#
# ### Why this is not a `QueryDrivenBacktest`
#
# **An engine certification is not spent on a strategy whose stationarity test
# has already rejected it.** A QDB run for this trade means pricing two live
# packages — a futures-versus-swaps convexity package and a DV01-neutral
# ultra-long forward flattener — daily for 5.6 years across 16 cells, with sign
# probes, `assert_ran` guards and a cost model per package. That is days of work
# and a large cache burn to put a dollar figure on a spread that section 5 says
# is two random walks. What is owed instead is a **bounded** answer: run the rule
# exactly as specified, in the spread's own units, and show what it earns.
#
# The unit of P&L below is **bp/day of curve-implied vol** — the spread's own
# unit — not dollars. The trade is not sized, and that limitation is real: these
# numbers say whether the *spread* moves the right way, not how many dollars a
# desk would have made.
#
# ### The one convention that decides the answer
#
# `entry_state` at date *t* is decided from the spread at *t−1*. Two executions
# are possible and they give completely different answers:
#
# | | position | earns | implementable? |
# |---|---|---|---|
# | `exec_lag=0` | state at *t* | spread *t−1* → *t* | only if you can trade AT the settle-time mark that generated the signal |
# | `exec_lag=1` | state at *t* | spread *t* → *t+1* | yes |
#
# Both are reported. Section 9 shows `exec_lag=0` has a null distribution centred
# on a Sharpe of about **5**, and `exec_lag=1` a null centred on **zero** — so
# only the second supports any inference at all.

# %%
SIM0 = pd.DataFrame([{"colour": c, "pair": p,
                      **{k: v for k, v in simulate(STIR[c], LONG[p],
                                                   W3.W3Config(colour=c, pair=p),
                                                   exec_lag=0).items()
                         if k != "episodes_list"}} for c, p in CELLS])

_show = ["colour", "pair", "episodes", "gross", "cost", "net", "gross_sr", "net_sr",
         "t_gross", "bp_per_trade", "be_cost"]
print("=== exec_lag = 0 : execution AT the mark that produced the signal ===")
print(SIM0[_show].round(3).to_string(index=False))
print(f"total gross {SIM0['gross'].sum():+.1f} bp   total net {SIM0['net'].sum():+.1f} bp")
print(f"cells gross>0 {int((SIM0['gross'] > 0).sum())}/16   "
      f"net>0 {int((SIM0['net'] > 0).sum())}/16   "
      f"median gross SR {SIM0['gross_sr'].median():.3f}   best {SIM0['gross_sr'].max():.3f}")

print("\n=== exec_lag = 1 : one day to execute ===")
print(SIM1[_show].round(3).to_string(index=False))
print(f"total gross {SIM1['gross'].sum():+.1f} bp   total net {SIM1['net'].sum():+.1f} bp")
print(f"cells gross>0 {int((SIM1['gross'] > 0).sum())}/16   "
      f"net>0 {int((SIM1['net'] > 0).sum())}/16   "
      f"median gross SR {SIM1['gross_sr'].median():.3f}   best {SIM1['gross_sr'].max():.3f}")

_removed = 1.0 - SIM1["gross"].sum() / SIM0["gross"].sum()
print(f"\nONE DAY of execution lag removes {_removed:.1%} of the gross P&L "
      f"({SIM0['gross'].sum():.0f} -> {SIM1['gross'].sum():.0f} bp).")

assert (SIM0["gross"] > 0).all(), "the lag-0 arm is no longer uniformly positive"
assert _removed > 0.80, (
    f"one day of lag now removes only {_removed:.1%}; the noise-fade diagnosis "
    "in section 9 needs re-deriving")
assert SIM1["net"].sum() < 0, "the implementable arm is no longer net-negative"
print("\nA 95% collapse from one day of delay is the signature of a signal that")
print("fades one-day noise in its own mark. Section 9 proves it with a placebo.")

# %% [markdown]
# ## 8. Costs
#
# `COST_BP_ROUND_TRIP = 0.5` is charged **in the spread's own units** (bp/day of
# vol) for a full open-and-close. That is a mapping, not a measurement, so it has
# to be justified rather than asserted — and it is **generous**.
#
# The STIR leg's cost *does* convert exactly. `σ = sqrt(2·CA/w)`, so
# `dσ/dCA = σ/(2·CA)`, and a bid/offer quoted in bp of CA maps straight into
# bp/day of vol. Below, the CA leg's bid/offer **alone**, at a tight 0.5bp round
# trip on the futures-versus-swaps package, is compared with the break-even the
# simulation actually needs.
#
# The long-end leg's cost does **not** convert — it is a one-off rate-bp P&L on
# a flattener package (Citi booked **+$187K gross → +$155K net on $50K DV01**,
# i.e. about **0.64bp** round trip), and there is no defensible map from that
# into a breakeven-vol unit. It is therefore charged at **zero**, which is the
# conservative direction for the conclusion being drawn.

# %%
_sub = panel[panel["rank"] == 13]                       # Blues
_ca_med = float(_sub["ca_bp"].replace(0.0, np.nan).dropna().median())
_sig_med = float(STIR["Blues"].median())
_dsig_dca = _sig_med / (2.0 * _ca_med)
_ca_leg_cost = 0.5 * _dsig_dca

print(f"Blues median CA        {_ca_med:.3f} bp")
print(f"Blues median vol       {_sig_med:.3f} bp/day")
print(f"dsigma/dCA = s/(2 CA)  {_dsig_dca:.4f} bp-vol per bp-CA")
print(f"-> a 0.5bp CA round trip alone costs {_ca_leg_cost:.4f} bp of SPREAD")

_be_med = float(SIM1["be_cost"].median())
_be_best = float(SIM1["be_cost"].max())
print(f"\nbreak-even round trip the rule can afford (exec_lag=1):")
print(f"   median cell {_be_med:.4f} bp     best cell {_be_best:.4f} bp")
print(f"   charged     {COST_BP_ROUND_TRIP:.4f} bp")
print(f"   CA leg alone{_ca_leg_cost:>9.4f} bp   ({_ca_leg_cost / _be_med:.1f}x the median break-even)")

print(f"\ntotal cost charged  {SIM1['cost'].sum():>9.1f} bp")
print(f"total gross         {SIM1['gross'].sum():>9.1f} bp")
print(f"total net           {SIM1['net'].sum():>9.1f} bp")

assert _be_med < _ca_leg_cost, (
    "the median break-even cost now exceeds what the CA leg's own bid/offer "
    "consumes; the cost argument in section 8 needs re-deriving")
print("\nThe median cell cannot pay the CA leg's OWN bid/offer, before the")
print("long-end flattener's round trip is charged at all. The 0.5bp figure is")
print("not what kills it -- a 0.24bp charge on one leg already does.")

# %% [markdown]
# ## 9. What the search cost, and where the naive P&L came from
#
# Sixteen cells were measured. The usual deflation is Bailey & Lopez de Prado's
# `E[max Sharpe | null]`, and it is reported below — but it assumes the null is a
# zero-mean strategy on independent observations, and **that assumption is the
# thing that fails here.** So an empirical null is built instead.
#
# **The placebo.** For each cell, the spread is decomposed into a random walk
# plus iid measurement noise, calibrated from its own variance and first
# autocovariance (`γ₁(Δ) = −s²` under that model). A synthetic spread with those
# same two variances and the same length — and with **no relationship whatsoever
# between two legs, because it has no legs** — is generated and the identical
# rule is run on it, 400 times.
#
# For **eight** of the sixteen cells the calibration returns a signal variance of
# **exactly zero**: the measured `ρ₁(Δ)` is past −0.5, so under this model the
# entire daily change is bounce. Those placebos are literally iid noise around a
# constant. That is what the data says; it is not a choice.

# %%
def calibrate(spread: pd.Series) -> tuple[float, float]:
    """(sigma_rw, sigma_noise) for ``x_t = m_t + e_t``, m a random walk, e iid.

    ``Var(dx) = sigma_m^2 + 2 s^2`` and ``Cov(dx_t, dx_{t-1}) = -s^2``, so both
    fall out of the first two sample moments of the differences.
    """
    d = spread.diff().dropna()
    v, g1 = float(d.var()), float(d.cov(d.shift(1)))
    s2 = max(-g1, 1e-12)
    return math.sqrt(max(v - 2.0 * s2, 0.0)), math.sqrt(s2)


SPREADS = {}
for c, p in CELLS:
    df = pd.concat([STIR[c].rename("s"), LONG[p].rename("l")], axis=1).dropna()
    SPREADS[(c, p)] = df["s"] - df["l"]

CAL = pd.DataFrame([{"colour": c, "pair": p, "n": len(SPREADS[(c, p)]),
                     "sigma_rw": calibrate(SPREADS[(c, p)])[0],
                     "sigma_noise": calibrate(SPREADS[(c, p)])[1]} for c, p in CELLS])
print(CAL.round(4).to_string(index=False))
print(f"\ncells whose calibrated signal variance is exactly zero: "
      f"{int((CAL['sigma_rw'] == 0).sum())} of {len(CAL)}")

# %%
_t0 = time.time()
_rows = []
for _rep in range(NULL_REPS):
    _rng = np.random.default_rng(90000 + _rep)
    for c, p in CELLS:
        _s = SPREADS[(c, p)]
        _n2 = len(_s)
        _sm, _sn = calibrate(_s)
        _m = np.cumsum(_rng.normal(0, _sm, _n2)) if _sm > 0 else np.zeros(_n2)
        _obs = pd.Series(_m + _rng.normal(0, _sn, _n2) + 5.0,
                         index=pd.bdate_range("2021-01-04", periods=_n2))
        _zero = pd.Series(np.zeros(_n2), index=_obs.index)
        for _lag in (0, 1):
            _r3 = simulate(_obs, _zero, W3.W3Config(), exec_lag=_lag, max_gap=10_000)
            if _r3:
                _rows.append({"rep": _rep, "lag": _lag, "gross": _r3["gross"],
                              "net": _r3["net"], "gross_sr": _r3["gross_sr"],
                              "episodes": _r3["episodes"]})
NULL = pd.DataFrame(_rows)
print(f"placebo: {NULL_REPS} reps x {len(CELLS)} cells x 2 lags in {time.time() - _t0:.0f}s")

SUMMARY = []
for _lag, _real in ((0, SIM0), (1, SIM1)):
    q = NULL[NULL["lag"] == _lag]
    mx = q.groupby("rep")["gross_sr"].max()
    tg = q.groupby("rep")["gross"].sum()
    SUMMARY.append({
        "exec_lag": _lag,
        "null median cell SR": q["gross_sr"].median(),
        "null E[max SR]": mx.mean(),
        "null max SR p95": mx.quantile(0.95),
        "real best SR": _real["gross_sr"].max(),
        "p(null max >= real max)": float((mx >= _real["gross_sr"].max()).mean()),
        "null total gross bp": tg.mean(),
        "real total gross bp": _real["gross"].sum(),
        "p(null tot >= real tot)": float((tg >= _real["gross"].sum()).mean()),
        "null episodes/cell": q["episodes"].mean(),
        "real episodes/cell": _real["episodes"].mean(),
    })
SUMMARY = pd.DataFrame(SUMMARY).set_index("exec_lag").T
print("\n" + SUMMARY.round(4).to_string())

# %%
_n0 = NULL[NULL["lag"] == 0]
_n1 = NULL[NULL["lag"] == 1]
_p0 = float((_n0.groupby("rep")["gross_sr"].max() >= SIM0["gross_sr"].max()).mean())
_p1 = float((_n1.groupby("rep")["gross_sr"].max() >= SIM1["gross_sr"].max()).mean())

assert abs(float(_n1["gross_sr"].median())) < 0.10, (
    "the exec_lag=1 placebo is not centred on zero, so it is not a valid null")
assert float(_n0["gross_sr"].median()) > 2.0, (
    "the exec_lag=0 placebo no longer manufactures a large Sharpe from nothing; "
    "the noise-fade diagnosis needs re-deriving")
assert _p0 > 0.5, (
    "the lag-0 arm now beats its own zero-edge null; section 9 needs re-deriving")

print(f"exec_lag=0: a placebo with NO relationship scores a median cell Sharpe of")
print(f"            {float(_n0['gross_sr'].median()):.2f}, and beats the real data's best cell in")
print(f"            {_p0:.0%} of reps. The real numbers are WORSE than pure noise.")
print(f"exec_lag=1: the same placebo is centred on {float(_n1['gross_sr'].median()):+.3f}, i.e. the")
print(f"            noise-fade is gone. Real best cell {SIM1['gross_sr'].max():.3f}, p = {_p1:.3f}.")
print("\nThe placebo also trades MORE than the real data "
      f"({_n1['episodes'].mean():.0f} vs {SIM1['episodes'].mean():.0f} episodes/cell),")
print("so only the GROSS comparison is apples-to-apples; the net one is not used.")

# %%
mean_hold = float(SIM1["mean_hold"].mean())
span = float(SIM1["years"].mean())
n_eff = span * 252.0 / mean_hold
print(f"mean hold {mean_hold:.1f} obs over {span:.2f}y -> n_eff ~ {n_eff:.0f} independent holds")
# Two clocks. `n_obs=n_eff` makes sr_std the standard error of a PER-HOLD
# Sharpe; the Sharpes in this notebook are ANNUALISED, whose null standard
# error is 1/sqrt(span_years). Both are printed because quoting the smaller
# one alone understates the bar -- and here neither matters, because the
# EMPIRICAL placebo below dwarfs both.
print("\nBailey & Lopez de Prado, for reference (both clocks):")
for N in (1, 4, 16, 64):
    _ph = expected_max_sharpe_under_null(N, sr_std=1.0 / np.sqrt(n_eff))
    _an = expected_max_sharpe_under_null(N, sr_std=1.0 / np.sqrt(span))
    print(f"  E[max SR | null], {N:3} trials: {_ph:.3f} per-hold, "
          f"{_an:.3f} annualised")
print(f"\nempirical E[max SR | null] from the placebo, 16 trials, exec_lag=1: "
      f"{float(_n1.groupby('rep')['gross_sr'].max().mean()):.3f}")
print("The empirical figure is an order of magnitude larger than the analytic one,")
print("because the analytic version assumes iid observations and this rule's P&L")
print("is anything but. That is why the placebo, not the formula, is the bar this")
print("notebook actually holds the result to: the gap between the two analytic")
print("clocks is small next to the gap between either of them and the placebo.")

# %%
fig = go.Figure()
for _lag, _col, _real in ((0, "exec_lag=0 (execute at the signal's own mark)", SIM0),
                          (1, "exec_lag=1 (one day to execute)", SIM1)):
    _mx = NULL[NULL["lag"] == _lag].groupby("rep")["gross_sr"].max()
    fig.add_trace(go.Histogram(x=_mx.to_numpy(), name=f"null, {_col}",
                               opacity=0.55, nbinsx=40))
    fig.add_vline(x=float(_real["gross_sr"].max()), line_dash="dash",
                  annotation_text=f"real best, lag={_lag}: {_real['gross_sr'].max():.2f}",
                  annotation_position="top")
fig.update_layout(
    title="W3 — best-of-16 gross Sharpe: real vs a placebo with no relationship at all",
    xaxis_title="max gross Sharpe across the 16 cells", yaxis_title="placebo reps",
    barmode="overlay", height=430, legend=dict(orientation="h", y=-0.2))
fig.show()

# %% [markdown]
# ## 10. Robustness
#
# Two ways the verdict could be an artefact of a knob, both closed here.
#
# * **The entry threshold.** If 1.5σ were simply the wrong z, a sweep would show
#   it. It does not — every threshold is net-negative at the implementable lag.
# * **The execution lag.** Already shown in section 7; restated in the sweep so
#   the two arms sit side by side at every threshold.

# %%
SWEEP = []
for _ez in (1.0, 1.5, 2.0, 2.5, 3.0):
    for _lag in (0, 1):
        _g = _n3 = _e = 0.0
        _alive = 0
        for c, p in CELLS:
            _r4 = simulate(STIR[c], LONG[p],
                           W3.W3Config(colour=c, pair=p, entry_z=_ez), exec_lag=_lag)
            if _r4:
                _g += _r4["gross"]
                _n3 += _r4["net"]
                _e += _r4["episodes"]
                _alive += int(_r4["net"] > 0)
        SWEEP.append({"entry_z": _ez, "exec_lag": _lag, "episodes": int(_e),
                      "gross_bp": _g, "net_bp": _n3, "cells_net_positive": _alive})
SWEEP = pd.DataFrame(SWEEP)
print(SWEEP.round(2).to_string(index=False))

_impl = SWEEP[SWEEP["exec_lag"] == 1]
assert (_impl["net_bp"] < 0).all(), (
    "an entry threshold now produces a net-positive book at the implementable "
    "lag; the verdict is threshold-dependent and needs re-deriving")
print(f"\nAt exec_lag=1 every threshold from {_impl['entry_z'].min()} to "
      f"{_impl['entry_z'].max()} is net-NEGATIVE.")
print("The verdict is not a threshold artefact. Note also that raising the")
print("threshold does not rescue it -- it only trades less of the same nothing.")

# %%
fig = go.Figure()
for _lag, _nm in ((0, "exec_lag=0 (not implementable)"), (1, "exec_lag=1")):
    _s2 = SWEEP[SWEEP["exec_lag"] == _lag]
    fig.add_trace(go.Bar(x=_s2["entry_z"], y=_s2["net_bp"], name=_nm))
fig.add_hline(y=0.0, line_dash="dash")
fig.update_layout(title="W3 — net P&L across all 16 cells, by entry threshold",
                  xaxis_title="entry z", yaxis_title="net, bp/day of vol summed",
                  height=400, barmode="group", legend=dict(orientation="h", y=-0.2))
fig.show()

# %% [markdown]
# ## 11. The book, cell by cell
#
# Every episode the default config would have taken at the implementable lag,
# and the per-cell result behind the totals. Holds are counted on the joint
# index, per section 6.1.
#
# The book is two-sided, as `entry_state` is designed to be — but it is heavily
# skewed toward **long STIR vol**, i.e. the spread spent much more of the sample
# below its trailing mean than above it. That asymmetry is itself what a
# non-stationary spread looks like: it wandered to one side and the 252-day
# trailing mean followed it down rather than pulling it back.

# %%
LOG = ALL_EPS.assign(
    side=lambda d: np.where(d["side"] == 1, "short STIR vol", "long STIR vol"),
    entry=lambda d: d["entry"].dt.date, exit=lambda d: d["exit"].dt.date,
).sort_values(["entry", "colour"])
print(f"{len(LOG)} episodes across {len(CELLS)} cells")
print(LOG.head(20).to_string(index=False))
print("...")

_by_side = LOG["side"].value_counts()
print(f"\nshort STIR vol {int(_by_side.get('short STIR vol', 0))}   "
      f"long STIR vol {int(_by_side.get('long STIR vol', 0))}")
print("\nepisodes by cell and side:")
print(LOG.groupby(["colour", "pair", "side"]).size().unstack(fill_value=0).to_string())

assert (LOG["side"] == "short STIR vol").sum() > 0
assert (LOG["side"] == "long STIR vol").sum() > 0, (
    "the book is one-sided; a one-sided spread trade is a directional position "
    "on one of its legs, which is the degeneracy this package has unpicked before")
assert LOG["obs_held"].max() == ALL_EPS["obs_held"].max()

# %%
print("per-cell result at exec_lag=1, sorted worst net first:")
print(SIM1[["colour", "pair", "n_obs", "episodes", "gross", "cost", "net",
            "gross_sr", "net_sr", "t_gross"]]
      .sort_values("net").round(3).to_string(index=False))
print(f"\ncells with net > 0: {int((SIM1['net'] > 0).sum())} of {len(SIM1)}")
print(f"best cell by |t| on gross: {SIM1.loc[SIM1['t_gross'].abs().idxmax(), 'colour']} "
      f"{SIM1.loc[SIM1['t_gross'].abs().idxmax(), 'pair']}, "
      f"t = {SIM1['t_gross'].abs().max():.2f}")
assert SIM1["t_gross"].abs().max() < 2.0, (
    "a cell's gross t-statistic now clears 2; the verdict needs re-deriving")

# %% [markdown]
# ## 12. Reading this notebook
#
# * **The result is negative and it is decided in section 5, not section 7.**
#   Over sixteen (colour, pair) combinations from 2021 to 2026 the two legs'
#   *changes* have a maximum |correlation| of **0.112**, a median of **0.030**,
#   and seven of sixteen are negative. **Fourteen of sixteen spreads fail to reject
#   a unit root at 5%.** A z-score entry assumes the spread reverts; on fourteen
#   of sixteen cells that assumption is rejected. That is the whole finding, and
#   it is why the diagnostics run before the trade — so a backtest is not spent
#   on two random walks.
#
# * **The two cells that do reject are not an exception worth trading.** Their
#   half-lives are **1.22 and 1.62 days**. Both are Reds, the shallowest colour,
#   where `dσ/dCA = σ/(2·CA)` is largest and the inversion is noisiest, and both
#   have the thinnest joint coverage in the grid (27% and 32% of business days,
#   gaps to 272 days). ADF is rejecting on bounce, not on a relationship — and a
#   rule that holds for a median of two observations cannot pay a round trip out
#   of a 1.2-day half-life anyway.
#
# * **The naive P&L looked spectacular, and that was the trap.** At `exec_lag=0`
#   all sixteen cells are gross-positive with Sharpes to 3.9. One day of
#   execution lag removes **95%** of it. The placebo settles it: a synthetic
#   spread with *no relationship at all*, calibrated only to each cell's own
#   variance and bounce, produces a **higher** median Sharpe than the real data
#   — the real best cell is beaten by the zero-edge null in **100%** of reps. The
#   `exec_lag=0` P&L is the rule fading one day of noise in its own mark, and
#   the daily-change autocorrelations (−0.46 to −0.54, past the −0.5 floor for
#   iid measurement error) say where that noise lives.
#
# * **At the implementable lag there is a residue, and it is far too small.**
#   Gross across all sixteen cells is **+112.5 bp** over 5.6 years — about
#   **0.12 bp per round trip** against a **0.5 bp** charge. Taken entirely at
#   face value (its p-value against the placebo is 0.043 on best-cell Sharpe and
#   0.025 on total gross, from a sixteen-cell search on two chosen statistics),
#   it still cannot pay the **CA leg's own bid/offer**, which maps to **0.24 bp**
#   of spread — twice the median break-even — before the ultra-long flattener's
#   ~0.64 bp round trip is charged at all. Net is **−191.5 bp**, 4 of 16 cells
#   positive, no cell's gross t-statistic reaches 2, and every entry threshold
#   from 1.0 to 3.0 is net-negative.
#
# * **What would have to change.** Not the threshold and not the cost
#   assumption — the premise. A spread trade needs the legs to co-move, and these
#   do not: the front-end convexity adjustment and the ultra-long curve's
#   breakeven are pricing genuinely different things, which is the honest reading
#   of a max change-correlation of 0.112. The direction with any prospect is the
#   one `ca_vol_link` already takes — grade the CA against *matched-expiry
#   swaption* vol, where a link is at least plausible — not against a curve
#   thirty years further out.
#
# * **A limitation to state plainly.** Section 7 is a bounded panel simulation in
#   the spread's own units, not a `QueryDrivenBacktest`, and it is not sized in
#   dollars. It was deliberately not certified through the engine, because
#   section 5 had already rejected the premise. If anyone wants the dollar
#   figure, the missing pieces are a package build for each leg and a per-package
#   cost model — but the number it would produce is bounded above by a gross edge
#   of 0.12 bp per round trip.

# %%
print("=" * 78)
print("W3 SUMMARY")
print("=" * 78)
print(f"cells                              {len(CELLS)}  (4 pack colours x 4 ultra-long pairs)")
print(f"window                             {CFG.start} .. {CFG.end}")
print(f"max |change correlation|           {_maxcorr:.4f}")
print(f"median |change correlation|        {_medcorr:.4f}")
print(f"spreads failing to reject ADF      {_nonstat} / {len(DIAG)}")
print(f"half-lives of the two that reject  "
      f"{_hl.min():.2f} and {_hl.max():.2f} days")
print(f"gross, exec_lag=0 (uninterpretable){SIM0['gross'].sum():>10.1f} bp")
print(f"gross, exec_lag=1 (implementable)  {SIM1['gross'].sum():>10.1f} bp")
print(f"  removed by one day of lag        {_removed:>10.1%}")
print(f"cost charged                       {SIM1['cost'].sum():>10.1f} bp")
print(f"NET, exec_lag=1                    {SIM1['net'].sum():>10.1f} bp")
print(f"cells net positive                 {int((SIM1['net'] > 0).sum())} / {len(SIM1)}")
print(f"break-even round trip (median)     {_be_med:.4f} bp   vs CA leg alone "
      f"{_ca_leg_cost:.4f} bp")
print(f"placebo beats real best, lag 0     {_p0:.0%} of {NULL_REPS} reps")
print("\nVERDICT: DEAD. The premise -- that front-end and ultra-long curve-implied")
print("vol co-move well enough for their spread to revert -- is rejected by the")
print("stationarity test on 14 of 16 cells, and the P&L that survived the test")
print("was a noise fade that one day of execution lag removes.")
print("=" * 78)
