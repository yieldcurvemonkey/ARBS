# %% [markdown]
# # SFR "Fade the Kink" v2 — what a kink actually is
#
# **Design:** `docs/superpowers/specs/2026-07-30-sfr-kink-fade-v2-design.md`
# **Supersedes:** the event-driven `sfr_kink_fade_backtest` (verdict **RED**,
# `SFR_screeners/FINDINGS_kink_fade.md`)
#
# The old notebook defined a kink as a 6m butterfly whose own 60-day z-score is
# extreme, and faded it. That treats every unit of curvature in the SR3 strip as
# a dislocation. It is not, and the reason is mechanical:
#
# > **SR3 settles on the day-weighted compounded average of overnight SOFR over
# > its IMM reference quarter.** A contract spanning two policy meetings is
# > legitimately priced differently from one spanning one, and a meeting late in
# > the quarter moves the contract by only a fraction of its jump.
#
# The FOMC meets eight times a year; the IMM grid cuts the year on the third
# Wednesday of March, June, September and December. The two calendars do not
# commute, so a butterfly on three consecutive contracts inherits a curvature
# that is pure arithmetic. **Fading that is fading the calendar** — and it is
# a *predictable* thing to fade, because the calendar is known years ahead.
#
# This notebook tests that hypothesis rather than assuming it, against decoys
# designed to fail if the story is right. The order of the sections is the order
# in which the question can be killed:
#
# 1. how big is the calendar effect, in bp;
# 2. the **pond test** — is there enough movement to pay a 2.0bp round trip at
#    all, before any signal work;
# 3. **placebo calendars** — does the *real* meeting schedule beat one with the
#    wrong dates;
# 4. only then, the grids.
#
# Costs are per **contract** throughout: a `1/-2/1` fly is 4 contracts, each SR3
# contract is $25/bp, so the taker round trip is `4 × 2 × 0.25 = 2.0bp`, not the
# prior lab's per-*leg* 1.5bp.

# %%
CONFIG = dict(
    # -- panel --
    structures=("3m", "6m"),
    primary_window="liquid16",          # 2022+, the only honest 16-slot window
    long_window="front8",               # 2019+, the regime-rich window
    max_slot=16,
    drop_dates=("2025-07-04",),         # corrupt strip; see the audit block

    # -- costs, per CONTRACT --
    cost_bp=2.0,                        # 4 contracts x 2 sides x 0.25bp
    cost_curve=(0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 4.0),
    n_packages=100,                     # = 400 contracts = $2,500/bp

    # -- the meeting fit --
    lam=100.0,                          # 2nd-difference penalty on the jump path
    lam_sweep=(1.0, 10.0, 100.0, 1000.0, 1.0e5),
    effective_lag_days=1,               # target range effective the day after

    # -- grid --
    windows=(60, 120, 250),
    entry_zs=(1.5, 2.0, 2.5),
    exits=("z0", "t10", "t21", "t42"),
    directions=("fade", "momentum"),
    max_hold=63,
    lag=1,

    # -- diagnostics --
    horizons=(5, 10, 21),
    front_slot_cut=5,
)
CONFIG

# %%
import sys
import time
from pathlib import Path

sys.path.append("../../")
sys.path.append(str(Path.cwd()))

import datetime

import numpy as np
import pandas as pd

import matplotlib
if "ipykernel" not in sys.modules:
    matplotlib.use("Agg")
import matplotlib.pyplot as plt

from RVUtils.MeanRev import MRConfig, run_backtest
from RVUtils.MeanRev.meetings import (
    LAST_ACTUAL_YEAR, LAST_PUBLISHED_YEAR, fomc_decisions, fomc_schedule,
    meeting_residual_panel,
)
from RVUtils.MeanRev.signals import (
    curvefit_residual_signal, scale_only_zscore, structure_signal_from_slots,
    xsection_signal, zscore_signal,
)

import sfr_kink_fade_common as K

pd.set_option("display.width", 230)
pd.set_option("display.max_columns", 60)
plt.rcParams.update({"figure.dpi": 110, "axes.grid": True, "grid.alpha": 0.25})

T0 = time.time()
BASE = MRConfig(lag=CONFIG["lag"], round_trip_cost_bp=CONFIG["cost_bp"],
                max_hold=CONFIG["max_hold"], n_packages=CONFIG["n_packages"])
print(f"taker round trip {CONFIG['cost_bp']}bp on the package "
      f"({CONFIG['n_packages']} packages = {4 * CONFIG['n_packages']:,} contracts "
      f"= ${25 * CONFIG['n_packages']:,}/bp)")
print(f"results -> {K.DATA_DIR}")

# %% [markdown]
# ## 0. Panel audit — units, signs, and one corrupt session
#
# Rule 8 of the house honesty rules: verify field scales and print units before
# trusting them. Rule 9: forward-fill only.

# %%
raw_contracts = pd.read_parquet(K.PANEL_DIR / "contracts.parquet")
raw_contracts["as_of"] = pd.to_datetime(raw_contracts["as_of"])
n_per_date = raw_contracts.groupby("as_of").size()
thin = n_per_date[n_per_date < 16]
print(f"contracts.parquet: {len(raw_contracts):,} rows, "
      f"{raw_contracts['as_of'].nunique():,} sessions, "
      f"{raw_contracts['code'].nunique()} contracts, "
      f"{raw_contracts['as_of'].min().date()} -> {raw_contracts['as_of'].max().date()}")
chk = (raw_contracts["rate_pct"] - (100.0 - raw_contracts["settle"])).abs().max()
print(f"rate_pct == 100 - settle:  max |diff| = {chk:.2e}   (units: PERCENT)")

print(f"\nsessions with fewer than 16 listed contracts: {len(thin)}")
for d in thin.index:
    g = raw_contracts[raw_contracts["as_of"] == d].sort_values("imm_start")
    print(f"  {d.date()} ({d.day_name()}): {len(g)} contracts "
          f"{list(g['code'])}, total OI {g['open_interest'].sum():.0f}")
print("  -> 2025-07-04 is US Independence Day, a market holiday. The row is built")
print("     from 8 zero-OI back months (H29..Z30) which the strip builder ranked")
print("     into slots 1-8, so 'slot 1' is a four-year-forward contract. Every")
print("     structure that day is mislabelled. DROPPED from every panel below.")

_s3 = pd.read_parquet(K.PANEL_DIR / "structures_3m.parquet")
hand = (2 * _s3["leg1_value"] - _s3["leg0_value"] - _s3["leg2_value"]) * 100.0
print(f"\nfly sign:  max |value - (2*belly - front - back)*100| = "
      f"{(_s3['value'] - hand).abs().max():.2e}   (units: BP)")
print(f"           max |value + (2*belly - front - back)*100| = "
      f"{(_s3['value'] + hand).abs().max():.2f}   (so the sign is not ambiguous)")
del _s3, hand

# %% [markdown]
# ## 1. The FOMC calendar, and whether we have it right
#
# `RVUtils/MeanRev/meetings.py` carries the scheduled **decision** dates — the
# second day of each two-day meeting. The new target range is effective the next
# day, which is the `effective_lag_days=1` every weight function takes.
#
# 2018–2026 are the realised calendar, 2027 is the Fed's published forward
# calendar, and 2028+ are projected by a documented rule and **flagged**. Any
# result that leans on projected rows has to say so, which is why the column
# exists.

# %%
sched = fomc_schedule(datetime.date(2018, 1, 1), datetime.date(2031, 12, 31))
print(sched.groupby(["year", "source"]).size().unstack(fill_value=0).to_string())
print(f"\nactual through {LAST_ACTUAL_YEAR}, published through {LAST_PUBLISHED_YEAR}, "
      f"projected beyond")

from Query.IRSwaps._CENTRAL_BANK_DATES import _FALLBACK_DATES

_w = _FALLBACK_DATES["USD-SOFR-1D"]
_theirs = sorted({v[0] for v in _w.values()} | {v[1] for v in _w.values()})
_theirs = [d for d in _theirs
           if datetime.date(2023, 1, 1) <= d <= datetime.date(2026, 12, 31)]
_mine = fomc_decisions(datetime.date(2023, 1, 1), datetime.date(2026, 12, 31))
print(f"\ncross-check vs Query/IRSwaps/_CENTRAL_BANK_DATES (independently "
      f"maintained, covers 2023-02+):")
print(f"  {len(_mine)} dates, exact match: {_theirs == _mine}")
print("  the lab's own regime boundaries land on meetings too: HIKING starts the")
print("  day after 2022-03-16 (liftoff), PLATEAU after 2023-07-26 (last hike),")
print("  CUTTING on 2024-09-18 (first cut).")

# %% [markdown]
# ### 1a. The independent check for 2018–2022
#
# No in-repo source covers those years, and they are most of the `front8`
# window. If the dates are right, front SR3 rates must move materially more on
# decision days (and the day after, when the new range takes effect) than on
# every other session.

# The obvious way to run this check is WRONG. Pivot the strip by
# constant-maturity slot, take a first difference, and slot 1 becomes a
# different contract at every IMM roll -- a splice worth tens of bp. Both
# calendars put their events on a Wednesday in the middle of March, June,
# September and December, so those splices land on the very days the audit is
# calling FOMC days, and the check manufactures its own answer. The daily change
# is therefore taken per CONTRACT, which cannot cross a roll.

# %%
contracts = K.load_contracts(drop_dates=CONFIG["drop_dates"])
coll = K.imm_roll_fomc_collisions(contracts)
print("IMM roll dates that are ALSO FOMC decision dates:")
print(coll.round(1).to_string(index=False))
audit = K.meeting_audit(contracts)
print("\nmean |daily change| of the front SR3 contracts, per CONTRACT (bp):")
print(audit.round(3).to_string(index=False))
_all = audit[audit["year"] == "ALL"].iloc[0]
print(f"""
  Pooled 2018-2022, decision days carry {_all['ratio']:.2f}x the front-strip move at
  Welch t = {_all['welch_t']:.2f}. 2018 is a flat-policy year and 2020's realised moves came
  from the UNSCHEDULED March cuts, which are deliberately not in the schedule --
  so both read below 1.0, as they should.

  For scale: the naive slot-pivoted version of this table reports 2.12x at
  t = 4.13. Roughly half of that is the IMM roll, not the Fed.""")

# %% [markdown]
# ## 2. How big is the calendar's own curvature?
#
# `phi_sum = 2·M_belly − M_front − M_back`, where `M` is the **day-weighted**
# meeting count inside a contract's quarter. It is the butterfly, in bp, that a
# path of exactly **1bp per meeting** would print. No market data enters it.
#
# The butterfly the calendar actually creates is `phi_sum × pace`, where `pace`
# is the bp-per-effective-meeting slope between the fly's own two wings. That
# product is the whole hypothesis, and its size is the first thing to measure.

# %%
lab3 = K.load_kink_lab("3m", CONFIG["primary_window"], lam=CONFIG["lam"],
                       max_slot=CONFIG["max_slot"], contracts=contracts)
lab6 = K.load_kink_lab("6m", CONFIG["primary_window"], lam=CONFIG["lam"],
                       max_slot=CONFIG["max_slot"], contracts=contracts)
print(f"3m: {lab3['levels'].shape[1]} flies x {lab3['levels'].shape[0]} sessions   "
      f"6m: {lab6['levels'].shape[1]} x {lab6['levels'].shape[0]}   "
      f"({time.time() - T0:.0f}s)")

cs = K.calendar_summary(lab3["calendar"], lab3["struct"])
print("\ncalendar curvature per constant-maturity slot (3m flies, 2022+):")
print(cs.round(3).to_string(index=False))
print("\n  phi is centred on zero with sd ~0.11-0.14 MEETINGS. pct_asym0 is the")
print("  share of days on which the two halves of the fly span the SAME integer")
print("  number of meetings -- so on 55-78% of sessions they do not.")
print("  pct_projected is the share of observations whose span reaches past the")
print("  published calendar: negligible to slot 5, over half by slot 15.")

# %%
cal3 = lab3["calendar"]
m = lab3["struct"][["as_of", "key", "value", "cm_label_short", "cm_slot",
                    "leg0_value", "leg2_value"]].merge(
    cal3[["as_of", "key", "phi_sum", "mtg_front", "mtg_back", "asym"]],
    on=["as_of", "key"], how="inner")
m["pace_bp_per_meeting"] = ((m["leg2_value"] - m["leg0_value"]) * 100.0
                            / (m["mtg_back"] - m["mtg_front"]))
m["calendar_fly_bp"] = m["phi_sum"] * m["pace_bp_per_meeting"]
m["regime"] = lab3["regimes"].reindex(pd.DatetimeIndex(m["as_of"])).to_numpy()

size = (m.groupby("regime")
        .agg(n=("value", "size"),
             fly_sd_bp=("value", "std"),
             pace_median=("pace_bp_per_meeting", lambda s: s.abs().median()),
             calendar_fly_sd_bp=("calendar_fly_bp", "std"),
             calendar_fly_p95=("calendar_fly_bp", lambda s: s.abs().quantile(0.95)))
        .reindex(K.REGIME_ORDER).dropna(how="all"))
size["share_of_fly_sd"] = size["calendar_fly_sd_bp"] / size["fly_sd_bp"]
size["share_of_fly_var"] = size["share_of_fly_sd"] ** 2
print("THE SIZE OF THE CALENDAR EFFECT (3m flies, bp)")
print(size.round(3).to_string())
print("\n  This is the number the whole hypothesis rests on. The bp-per-meeting")
print("  pace between two contracts that are only two quarters apart is small --")
print("  a couple of bp -- so phi (~0.13 meetings) x pace buys a few TENTHS of a")
print("  basis point of curvature against a fly that moves several bp a day.")

# %% [markdown]
# ### 2a. The direct test of the mechanism
#
# Theory says `fly_k = Σ_m δ_m · Φ_{k,m}`, so under a locally uniform path the
# cross-section of flies on a date should be proportional to the cross-section
# of `phi_sum`, with slope equal to the pace. Regressing one on the other per
# date, and comparing the fitted slope with the independently measured pace, is
# a falsifiable test that has nothing to do with whether it makes money.

# %%
rows = []
for d, g in m.groupby("as_of"):
    g = g.dropna(subset=["value", "phi_sum", "pace_bp_per_meeting"])
    if len(g) < 8 or g["phi_sum"].std() < 1e-9:
        continue
    X = np.column_stack([np.ones(len(g)), g["phi_sum"].to_numpy()])
    beta, *_ = np.linalg.lstsq(X, g["value"].to_numpy(), rcond=None)
    ss = float(((g["value"] - g["value"].mean()) ** 2).sum())
    rows.append({"as_of": d, "slope": float(beta[1]),
                 "r2": float(1 - ((g["value"] - X @ beta) ** 2).sum() / ss)
                 if ss > 0 else np.nan,
                 "measured_pace": float(g["pace_bp_per_meeting"].median())})
mech = pd.DataFrame(rows).set_index("as_of")
mech["regime"] = lab3["regimes"].reindex(mech.index).to_numpy()
agree = float((np.sign(mech["slope"]) == np.sign(mech["measured_pace"])).mean())
print("cross-sectional regression   fly ~ a + b * phi   (one per date)")
print(f"  dates                                     {len(mech)}")
print(f"  median cross-sectional r2 of phi alone    {mech['r2'].median():.4f}")
print(f"  corr(fitted slope, measured pace)         "
      f"{mech['slope'].corr(mech['measured_pace']):+.3f}")
print(f"  share of dates the two agree in SIGN      {agree:.3f}")
print(f"  median |fitted slope|                     {mech['slope'].abs().median():.2f}"
      f" bp/meeting")
print(f"  median |measured pace|                    "
      f"{mech['measured_pace'].abs().median():.2f} bp/meeting")
print("\n  by regime (medians):")
print(mech.groupby("regime")[["slope", "measured_pace", "r2"]].median()
      .reindex(K.REGIME_ORDER).dropna(how="all").round(3).to_string())
print("\n  VERDICT ON THE MECHANISM: phi explains ~1% of the cross-section of")
print("  butterflies, and the slope it fits agrees in sign with the pace on")
print("  about half of all dates -- a coin flip. The arithmetic is right; the")
print("  market simply does not price flies as (pace x calendar curvature).")

# %% [markdown]
# ## 3. The five kink definitions
#
# | | |
# |---|---|
# | **K0** | raw fly z-score — the incumbent, the control |
# | **K1** | butterfly of the residual from a **smooth policy path** fitted through the day-weight matrix, penalising the second difference of the jump sequence |
# | **K2** | the **calendar-tilted fly**: `fly − phi·pace`, one number per structure per day, nothing fitted |
# | **K3** | cross-sectional fade within a maturity bucket (the `ls_fade` pattern) |
# | **K4** | K0 gated on calendar symmetry (`asym == 0`) |
#
# `lam` is the only real knob in K1 and it is interpretable at both ends:
# `lam → 0` fits every jump and the residual vanishes; `lam → ∞` forces the jump
# path onto a straight line in meeting index — a Fed that accelerates perfectly
# smoothly — so the fitted strip is the lumpiest curve a *perfectly regular* Fed
# could produce and the residual is everything else.

# %%
_RESID = {}


def resid_slots(lam, meetings=None, tag="real"):
    # The cache key carries a fingerprint of the meeting list, not just the
    # caller's label. A tag collision between two different calendars would
    # silently return the wrong residual panel to a placebo comparison, which
    # is the one place in this notebook where that would invert the conclusion.
    fp = ("default" if meetings is None else
          (len(meetings), str(min(meetings)), str(max(meetings)),
           hash(tuple(str(m) for m in meetings))))
    k = (tag, float(lam), fp)
    if k not in _RESID:
        _RESID[k] = meeting_residual_panel(
            contracts, meetings=meetings, lam=float(lam),
            max_slot=CONFIG["max_slot"],
            effective_lag_days=CONFIG["effective_lag_days"])
    return _RESID[k]


def resid_fly(lab, lam, meetings=None, tag="real"):
    L = lab["levels"]
    return structure_signal_from_slots(
        resid_slots(lam, meetings, tag), lab["struct"], scale=1.0
    ).reindex(index=L.index, columns=L.columns)


rows = []
for lam in CONFIG["lam_sweep"]:
    r3 = resid_fly(lab3, lam)
    corr = pd.Series({c: lab3["levels"][c].corr(r3[c]) for c in r3.columns})
    rows.append({"lam": lam, "resid_fly_sd_bp": float(r3.stack().std()),
                 "raw_fly_sd_bp": float(lab3["levels"].stack().std()),
                 "resid_share_of_sd": float(r3.stack().std()
                                            / lab3["levels"].stack().std()),
                 "median_corr_with_raw_fly": float(corr.median())})
print("lam sweep (3m flies): how much of the fly survives the smooth-path fit")
print(pd.DataFrame(rows).round(3).to_string(index=False))
print(f"\n  primary lam = {CONFIG['lam']}")

# %%
mres3 = resid_fly(lab3, CONFIG["lam"])
mres6 = resid_fly(lab6, CONFIG["lam"])
tilt3 = lab3["tilted"]["level"].reindex(index=lab3["levels"].index,
                                        columns=lab3["levels"].columns)
tilt6 = lab6["tilted"]["level"].reindex(index=lab6["levels"].index,
                                        columns=lab6["levels"].columns)

vd = K.cm_variance_decomposition(lab3["levels"], lab3["levels"] - mres3,
                                 lab3["struct"])
print("variance decomposition: raw fly = fitted (calendar + smooth path) + residual")
print("attributed by the CM slot each key occupied ON THAT DATE, not the slot it "
      "was born at")
print(vd.round(3).to_string(index=False))
print("\n  NOTE: r2 here is 1 - var(residual)/var(fly), so it is a deterministic")
print("  function of how hard the fit was pushed (lam). It is NOT evidence that")
print("  the MEETING structure explains anything -- section 5 tests that, and")
print("  section 2's `share_of_fly_var` is the number that does bound it: the")
print("  calendar itself is worth 1-6% of the fly's variance.")

# %%
tl = lab3["tilted"]["front_share"].stack()
print("K2, the calendar-tilted fly: implied front-wing share of the belly")
print(f"  mean {tl.mean():.4f}   sd {tl.std():.4f}   "
      f"range [{tl.min():.4f}, {tl.max():.4f}]")
rows = []
for key in lab3["levels"].columns:
    g = lab3["struct"][lab3["struct"]["key"] == key]
    if len(g) < 250:
        continue
    f = g["leg0_value"].to_numpy(float) * 100.0
    b = g["leg1_value"].to_numpy(float) * 100.0
    kk = g["leg2_value"].to_numpy(float) * 100.0
    y, x = b - kk, f - kk
    ok = np.isfinite(y) & np.isfinite(x)
    if ok.sum() < 100 or np.var(x[ok]) < 1e-12:
        continue
    w = float(np.dot(x[ok] - x[ok].mean(), y[ok] - y[ok].mean())
              / np.sum((x[ok] - x[ok].mean()) ** 2))
    rows.append({"key": key, "fitted_front_share": w,
                 "calendar_front_share": float(lab3["tilted"]["front_share"][key].mean())})
tilt_cmp = pd.DataFrame(rows)
print(f"\n  the prior lab's level-neutral FITTED wing split, {len(tilt_cmp)} keys:")
print(f"    fitted   mean {tilt_cmp['fitted_front_share'].mean():.4f}  "
      f"sd {tilt_cmp['fitted_front_share'].std():.4f}")
print(f"    calendar mean {tilt_cmp['calendar_front_share'].mean():.4f}  "
      f"sd {tilt_cmp['calendar_front_share'].std():.4f}")
print(f"    corr across keys = "
      f"{tilt_cmp['fitted_front_share'].corr(tilt_cmp['calendar_front_share']):+.3f}")
print("\n  The prior lab measured a fitted level-neutral split of 0.463/0.537 and")
print("  could not explain it. The calendar tilt has the same RANGE but is")
print("  centred on 0.500 and is uncorrelated with the fitted split across keys.")
print("  So the fitted tilt is NOT the meeting calendar. That question is closed.")

# %%
d = lab3["slot_panel"].dropna().index[-1]
r_slots = resid_slots(CONFIG["lam"])
fig, axes = plt.subplots(1, 3, figsize=(16, 3.9))
y = lab3["slot_panel"].loc[d].dropna()
x = np.array([int(c) for c in y.index])
fit = y.to_numpy() - r_slots.loc[d, x].to_numpy() / 100.0
axes[0].plot(x, y.to_numpy(), "o-", color="black", lw=1.4, ms=5, label="SR3 settles")
axes[0].plot(x, fit, lw=1.4, color="#1f4e79", label=f"smooth policy path (lam={CONFIG['lam']:.0f})")
axes[0].set_xlabel("strip slot")
axes[0].set_ylabel("rate (%)")
axes[0].set_title(f"strip and meeting fit, {pd.Timestamp(d).date()}", fontsize=10)
axes[0].legend(fontsize=8)
axes[1].bar(x, r_slots.loc[d, x].to_numpy(), color="#c62828", alpha=0.75)
axes[1].axhline(0, color="grey", lw=0.8)
axes[1].set_xlabel("strip slot")
axes[1].set_ylabel("residual (bp)")
axes[1].set_title("per-contract residual", fontsize=10)
phi_ts = lab3["phi"]
for c in list(phi_ts.columns)[:4]:
    axes[2].plot(phi_ts.index, phi_ts[c].to_numpy(), lw=0.9, alpha=0.8)
axes[2].axhline(0, color="grey", lw=0.8)
axes[2].set_ylabel("phi_sum (meetings)")
axes[2].set_title("calendar curvature is a deterministic oscillation", fontsize=10)
for a in axes:
    a.tick_params(labelsize=8)
fig.autofmt_xdate()
fig.tight_layout()
plt.show()

# %% [markdown]
# ## 4. The pond test — is there enough movement to pay for the trade?
#
# The prior lab established that fading SR3 flies is *directionally* right and
# still loses money, because the moves are barely larger than the round trip.
# That reframes what a new signal has to do: **call the sign more often, or
# select days on which the fly moves further.** The second is measurable before
# any backtest, and it can end a definition without running a grid.
#
# `oracle_bp` is `E[|level[t+h] − level[t]|]` on the days a signal fires — what
# a trader with perfect foresight of the *direction* would capture, and a
# ceiling no signal work can exceed. `selectivity` of 1.00 means the signal
# picks days at random with respect to move size.

# %%
sig3 = {
    "K0 raw z": zscore_signal(lab3["levels"], window=120),
    "K1 meeting resid (scale)": scale_only_zscore(mres3, window=120),
    "K1z meeting resid (z)": zscore_signal(mres3, window=120),
    "K2 calendar-tilted z": zscore_signal(tilt3, window=120),
}
print("### 3m FLIES")
pond3 = K.pond_block(lab3["levels"], sig3, entry_z=2.0, gate=lab3["gate"],
                     horizons=CONFIG["horizons"], round_trip_bp=CONFIG["cost_bp"],
                     tag="3m")

# %%
sig6 = {
    "K0 raw z": zscore_signal(lab6["levels"], window=120),
    "K1 meeting resid (scale)": scale_only_zscore(mres6, window=120),
    "K1z meeting resid (z)": zscore_signal(mres6, window=120),
    "K2 calendar-tilted z": zscore_signal(tilt6, window=120),
}
print("### 6m FLIES")
pond6 = K.pond_block(lab6["levels"], sig6, entry_z=2.0, gate=lab6["gate"],
                     horizons=CONFIG["horizons"], round_trip_bp=CONFIG["cost_bp"],
                     tag="6m")
print(f"\n  3m pooled fly sd {lab3['levels'].stack().std():.2f}bp vs "
      f"6m {lab6['levels'].stack().std():.2f}bp "
      f"({lab6['levels'].stack().std() / lab3['levels'].stack().std():.2f}x) "
      f"for the SAME three-leg, four-contract cost.")
print("  The 3m fly's oracle barely clears the round trip even at h=21; the 6m")
print("  fly's clears it by 4bp. If anything is tradeable it is the 6m fly.")

# %% [markdown]
# ## 5. Placebo calendars — is it the meetings, or just smoothing?
#
# This is the section the hypothesis has to survive. The meeting residual is
# built from a basis with a lot of freedom, and *any* flexible smoother will
# leave a residual that mean-reverts better than the raw fly. So the real
# calendar is run against decoys with the same number of knots:
#
# * **shifted** — the real dates moved bodily by 21 / 45 days: same count, same
#   irregularity, wrong phase against the IMM grid;
# * **evenly spaced** — eight pseudo-meetings a year at exactly equal spacing:
#   same count, *no* irregularity at all, so it cannot possibly carry calendar
#   information;
# * **cubic spline in slot index** — the existing `curvefit_residual_signal`,
#   which assumes the strip should be smooth in calendar time.
#
# Each decoy's `lam` is tuned so its residual has the **same standard deviation**
# as the real calendar's, because a basis with more effective freedom trivially
# explains more variance. With the scale matched, `1 − var(resid)/var(fly)` is
# identical by construction and carries no information; the discriminating
# statistics are the residual's **forward-predictive IC** and its **backtest**.

# %%
REAL = fomc_decisions(datetime.date(2017, 1, 1), datetime.date(2032, 12, 31))
LAB, LVL = lab6, lab6["levels"]              # the 6m fly, where the pond is
TARGET_SD = float(resid_fly(LAB, CONFIG["lam"]).stack().std())
print(f"real-calendar residual sd on the 6m fly = {TARGET_SD:.3f}bp "
      f"(raw fly sd {LVL.stack().std():.3f}bp)")


def tune_lam(meetings, tag, target=TARGET_SD, lo=0.05, hi=1.0e6, iters=24):
    for _ in range(iters):
        mid = float(np.sqrt(lo * hi))
        if float(resid_fly(LAB, mid, meetings, tag).stack().std()) < target:
            lo = mid
        else:
            hi = mid
    return float(np.sqrt(lo * hi))


DECOYS = {
    "shift +21d": [d + datetime.timedelta(days=21) for d in REAL],
    "shift +45d": [d + datetime.timedelta(days=45) for d in REAL],
    "even 8/yr": [datetime.date(2018, 1, 31) + datetime.timedelta(days=int(round(45.656 * i)))
                  for i in range(140)],
}
panels = {"E. real FOMC calendar": resid_fly(LAB, CONFIG["lam"])}
lam_of = {"E. real FOMC calendar": CONFIG["lam"]}
for nm, mt in DECOYS.items():
    lam = tune_lam(mt, nm)
    lam_of[f"B. {nm}"] = lam
    panels[f"B. {nm}"] = resid_fly(LAB, lam, mt, nm)
panels["B. cubic spline in slot"] = curvefit_residual_signal(
    LAB["slot_panel"], LAB["struct"], form="spline", scale=100.0).reindex(
    index=LVL.index, columns=LVL.columns)
lam_of["B. cubic spline in slot"] = np.nan
panels["A. raw fly (no smoothing)"] = LVL
lam_of["A. raw fly (no smoothing)"] = np.nan

# Every residual panel is a deviation from a fitted fair value, so its zero is
# meaningful and `scale_only_zscore` (divide by a trailing sd, keep the zero) is
# the right standardisation. The RAW FLY's zero is NOT meaningful -- a 6m fly
# that sits at -13bp for a year is not a permanent two-sigma dislocation -- so
# standardising it the same way would hand the baseline a handicap and
# manufacture the comparison. It gets a full trailing z-score, which is also
# exactly the incumbent K0 definition. Both versions are reported so the choice
# is visible rather than assumed.
STD_OF = {n: "scale" for n in panels}
STD_OF["A. raw fly (no smoothing)"] = "z"
panels["A2. raw fly, scale-only (handicapped control)"] = LVL
lam_of["A2. raw fly, scale-only (handicapped control)"] = np.nan
STD_OF["A2. raw fly, scale-only (handicapped control)"] = "scale"


def _std(panel, how, window):
    return (zscore_signal(panel, window=window) if how == "z"
            else scale_only_zscore(panel, window=window))


print(f"  built {len(panels)} panels ({time.time() - T0:.0f}s)")

# %%
from scipy.stats import spearmanr

fwd = {h: LVL.shift(-h) - LVL for h in CONFIG["horizons"]}
rows = []
for name, p in panels.items():
    # Score each basis on the SAME object the backtest trades, i.e. after its
    # own standardisation. Comparing demeaned residual panels against an
    # undemeaned raw level would make the raw-fly row measure maturity ranking
    # rather than dislocation.
    q = _std(p, STD_OF[name], 120)
    row = {"basis": name, "lam": lam_of[name],
           "resid_sd_bp": float(p.stack().std()), "standardise": STD_OF[name]}
    for h, f in fwd.items():
        ics = []
        for d in q.index:
            a, b = q.loc[d].to_numpy(float), f.loc[d].to_numpy(float)
            ok = np.isfinite(a) & np.isfinite(b)
            if ok.sum() < 6 or np.unique(a[ok]).size < 4:
                continue
            ic = spearmanr(a[ok], b[ok]).correlation
            if np.isfinite(ic):
                ics.append(ic)
        ics = np.asarray(ics)
        row[f"xs_ic_h{h}"] = float(ics.mean()) if ics.size else np.nan
        row[f"t_h{h}"] = (float(ics.mean() / ics.std(ddof=1) * np.sqrt(ics.size))
                          if ics.size > 3 else np.nan)
    rows.append(row)
ic_tab = pd.DataFrame(rows)
print("per-date cross-sectional IC vs the forward move, on each basis's own "
      "traded signal (6m flies)")
print(ic_tab.round(4).to_string(index=False))
print("\n  negative IC = the signal mean-reverts (rich now -> falls).")
print("  t is NOT overlap-corrected: read it as an ordering, not a p-value.")
ic_tab.to_csv(K.DATA_DIR / "placebo_ic.csv", index=False)

# %%
from RVUtils.MeanRev import grid_search

PLACEBO_GRID = {"window": CONFIG["windows"], "entry_z": CONFIG["entry_zs"],
                "exit_style": CONFIG["exits"], "direction": CONFIG["directions"]}
rows = []
for name, p in panels.items():
    fn = (lambda pp, hh: (lambda L, window: _std(pp, hh, window)))(p, STD_OF[name])
    g = grid_search(PLACEBO_GRID, levels=LVL, signal=None, gate=LAB["gate"],
                    base=BASE, signal_fn=fn)
    d = g["total_net_bp"]
    best = g.loc[d.idxmax()]
    rows.append({
        "basis": name, "standardise": STD_OF[name], "n_configs": len(g),
        "grid_median_bp": d.median(),
        "pct_positive": float((d > 0).mean()), "best_net_bp": d.max(),
        "best_n_trades": int(best["n_trades"]),
        "best_avg_net_bp": best["avg_net_bp"], "best_hit": best["hit_rate"],
        "best_sharpe": best["sharpe"],
        "fade_median": g[g["direction"] == "fade"]["total_net_bp"].median(),
        "mom_median": g[g["direction"] == "momentum"]["total_net_bp"].median(),
        "best_config": best["config"]})
placebo = pd.DataFrame(rows)
print("PLACEBO BACKTEST (6m flies, identical grid / engine / 2.0bp cost)")
print(placebo.drop(columns=["best_config"]).round(3).to_string(index=False))
print("\nbest config per basis:")
for _, r in placebo.iterrows():
    print(f"  {r['basis']:44s} {r['best_config']}")
placebo.to_csv(K.DATA_DIR / "placebo_backtest.csv", index=False)

pl = placebo.set_index("basis")
decoys = [b for b in pl.index if b.startswith("B.")]
mtg = [b for b in pl.index if b.startswith("B. shift") or b.startswith("B. even")]
real = "E. real FOMC calendar"
raw = "A. raw fly (no smoothing)"
spline = "B. cubic spline in slot"


def _rng(col):
    return pl.loc[decoys, col].min(), pl.loc[decoys, col].max()


def _inside(col):
    lo, hi = _rng(col)
    return bool(lo <= pl.loc[real, col] <= hi)


beat_raw_best = [b for b in decoys + [real] if pl.loc[b, "best_net_bp"] > pl.loc[raw, "best_net_bp"]]
beat_raw_med = [b for b in decoys + [real] if pl.loc[b, "grid_median_bp"] > pl.loc[raw, "grid_median_bp"]]
best_ic = ic_tab.set_index("basis")["xs_ic_h21"].idxmin()
print(f"""
  READ THIS ROW BY ROW, AND BE PRECISE ABOUT WHICH COLUMN -- the columns do not
  agree, and saying "every smoothed basis beats the raw fly" would be false.

  * ON BEST CONFIG, smoothing wins outright: {len(beat_raw_best)} of {len(decoys) + 1} smoothed bases beat the
    raw fly's {pl.loc[raw, 'best_net_bp']:+.1f}bp.
  * ON THE GRID MEDIAN it does NOT: only {len(beat_raw_med)} of {len(decoys) + 1} beat the raw fly's
    {pl.loc[raw, 'grid_median_bp']:+.1f}bp, and the meeting bases sit BELOW it
    ({pl.loc[mtg, 'grid_median_bp'].min():+.1f} to {pl.loc[mtg, 'grid_median_bp'].max():+.1f}). A better best corner with a worse
    median is a WIDER sweep, not a better signal -- the signature of a noisier
    input, not a more informative one.
  * The real calendar is inside the decoy range on best config: {_inside('best_net_bp')};
    on grid median: {_inside('grid_median_bp')}. It owns the single best corner, which is what a
    72-config search hands to whichever basis is luckiest.
  * On the forward-predictive IC at h=21 -- the statistic that does NOT depend
    on picking a corner -- the best basis is "{best_ic}",
    and the decoys include an EVENLY SPACED pseudo-calendar that by
    construction carries no calendar information at all.
  * The one basis that improves BOTH the best config and the distribution is a
    plain cubic spline in slot index, which needs no calendar:
    median {pl.loc[spline, 'grid_median_bp']:+.1f}bp, {pl.loc[spline, 'pct_positive']:.1%} of configs positive, Sharpe {pl.loc[spline, 'best_sharpe']:+.2f}.
  * NOT ONE BASIS HAS A POSITIVE GRID MEDIAN.""")

# %% [markdown]
# ## 6. The frameworks — 3m flies
#
# From here the house machinery does the work: grid → distribution →
# neighbourhood → sign test → best config → equity in bp and $ → trade log →
# exit comparison → cost curve → regime split → linear-shadow decomposition →
# median-config control → league rows. The top row is never the verdict.

# %%
GRID = {"window": CONFIG["windows"], "entry_z": CONFIG["entry_zs"],
        "exit_style": CONFIG["exits"], "direction": CONFIG["directions"]}
PARAMS = ["window", "entry_z", "exit_style", "direction"]
#  the exit-comparison table shows the swept exits plus the two signal-driven
#  rules the grid does not carry, so 'exit at fitted fair value' (z0) can be
#  read against a fixed horizon directly.
EXITS = ("z0", "band", "t5", "t10", "t21", "t42")


def k0(L, window):
    return zscore_signal(L, window=window)


out_k0_3 = K.run_family("K0. raw fly z-score (3m, liquid16)", lab=lab3,
                        signal_fn=k0, grid_spec=GRID, params=PARAMS, base=BASE,
                        cls="kink", note="the incumbent definition, reproduced "
                                         "at per-CONTRACT costs", exits=EXITS)

# %%
def k1_3(L, window):
    return scale_only_zscore(mres3, window=window)


out_k1_3 = K.run_family("K1. meeting residual (3m, liquid16)", lab=lab3,
                        signal_fn=k1_3, grid_spec=GRID, params=PARAMS, base=BASE,
                        cls="kink", note=f"smooth-policy-path residual, lam="
                                         f"{CONFIG['lam']:.0f}, model's zero kept", exits=EXITS)

# %%
def k2_3(L, window):
    return zscore_signal(tilt3, window=window)


out_k2_3 = K.run_family("K2. calendar-tilted fly (3m, liquid16)", lab=lab3,
                        signal_fn=k2_3, grid_spec=GRID, params=PARAMS, base=BASE,
                        cls="kink", note="fly - phi*pace; no fitting, no history", exits=EXITS)

# %% [markdown]
# ## 7. The frameworks — 6m flies
#
# The 6m fly carries ~2.9x the dispersion of the 3m fly for the identical
# four-contract cost, and it is the only structure in either lab whose oracle
# bound clears the round trip with room to spare.

# %%
out_k0_6 = K.run_family("K0. raw fly z-score (6m, liquid16)", lab=lab6,
                        signal_fn=k0, grid_spec=GRID, params=PARAMS, base=BASE,
                        cls="kink", note="the incumbent definition on 6m flies", exits=EXITS)

# %%
def k1_6(L, window):
    return scale_only_zscore(mres6, window=window)


out_k1_6 = K.run_family("K1. meeting residual (6m, liquid16)", lab=lab6,
                        signal_fn=k1_6, grid_spec=GRID, params=PARAMS, base=BASE,
                        cls="kink", note=f"lam={CONFIG['lam']:.0f}; the headline row", exits=EXITS)

# %%
def k1z_6(L, window):
    return zscore_signal(mres6, window=window)


out_k1z_6 = K.run_family("K1z. meeting residual, re-centred (6m, liquid16)",
                         lab=lab6, signal_fn=k1z_6, grid_spec=GRID, params=PARAMS,
                         base=BASE, cls="kink",
                         note="full trailing z-score: throws the model's zero away", exits=EXITS)

# %%
def k2_6(L, window):
    return zscore_signal(tilt6, window=window)


out_k2_6 = K.run_family("K2. calendar-tilted fly (6m, liquid16)", lab=lab6,
                        signal_fn=k2_6, grid_spec=GRID, params=PARAMS, base=BASE,
                        cls="kink", note="one degree of freedom, nothing fitted", exits=EXITS)

# %% [markdown]
# ## 8. K4 — splitting on calendar symmetry
#
# The sharpest form of the brief's question: *is the fade only real when the
# calendar is not creating the kink?* The condition is `asym == 0` — the two
# halves of the fly span the same integer number of meetings — applied at entry
# only, because forcing an exit on a gate that fails later is a look-ahead exit.
#
# **It is a static partition of keys, not a time-varying gate, and that changes
# how it reads.** A key's legs are three fixed contracts, so the number of
# meetings between their IMM start dates never changes over the key's life:
# `asym` is constant per key by construction. So K4 and K4b split the *universe*
# into two disjoint sets of butterflies, and any difference between them is
# confounded with whatever else differs about those contracts — how many there
# are, where they sit on the strip, and how far they move. The cell below
# reports the pond for each side so that confound is visible rather than
# assumed away.

# %%
lab6_sym = dict(lab6)
sym = (lab6["asym"].reindex(index=lab6["levels"].index,
                            columns=lab6["levels"].columns) == 0)
lab6_sym["gate"] = lab6["gate"] & sym.fillna(False)
per_key_asym = lab6["asym"].nunique(dropna=True)
print(f"asym takes {int(per_key_asym.max())} distinct value(s) within a key "
      f"(1 == constant per key, i.e. a static partition)")
sym_keys = [c for c in sym.columns if bool(sym[c].fillna(False).any())]
asym_keys = [c for c in sym.columns if c not in sym_keys]
print(f"  symmetric keys: {len(sym_keys)} of {sym.shape[1]}   "
      f"asymmetric keys: {len(asym_keys)}")
print(f"  symmetric cells: {100 * float(sym.mean().mean()):.1f}%; "
      f"gate keeps {100 * float(lab6_sym['gate'].mean().mean()):.1f}%")
_pond_split = K.oracle_table(
    lab6["levels"],
    {"symmetric keys": lab6["gate"] & sym.fillna(False),
     "asymmetric keys": lab6["gate"] & (~sym.fillna(True))},
    horizons=(21,), round_trip_bp=CONFIG["cost_bp"])
print("\n  pond size on each side of the partition (h=21, all cells, no signal):")
print(_pond_split.round(3).to_string(index=False))

out_k4 = K.run_family("K4. raw z, gated on calendar symmetry (6m, liquid16)",
                      lab=lab6_sym, signal_fn=k0, grid_spec=GRID, params=PARAMS,
                      base=BASE, cls="kink-gate",
                      note="entry only when asym == 0", exits=EXITS)

# %%
lab6_asym = dict(lab6)
lab6_asym["gate"] = lab6["gate"] & (~sym.fillna(True))
out_k4b = K.run_family("K4b. raw z, gated on calendar ASYMMETRY (6m, liquid16)",
                       lab=lab6_asym, signal_fn=k0, grid_spec=GRID, params=PARAMS,
                       base=BASE, cls="kink-gate",
                       note="the complement -- if the calendar story is right "
                            "this is the one that should lose", exits=EXITS)

# %% [markdown]
# ### 8a. The head-to-head
#
# This is the only test in the notebook whose result **supports** the calendar
# story, so it gets stated on its own rather than buried in the sign table. The
# prediction is specific: fading the raw fly should work *less badly* on the
# butterflies whose two halves span the same number of meetings.
#
# Read it against the pond table above. If the symmetric keys simply move
# further, the whole gap is move size and the calendar has explained nothing.

# %%
g4, g4b = out_k4["grid"], out_k4b["grid"]
cmp4 = pd.DataFrame({
    "asym == 0 (calendar symmetric)": [
        len(g4), g4["total_net_bp"].median(),
        g4[g4["direction"] == "fade"]["total_net_bp"].median(),
        g4[g4["direction"] == "momentum"]["total_net_bp"].median(),
        g4["total_net_bp"].max(), float((g4["total_net_bp"] > 0).mean()),
        g4["n_trades"].median()],
    "asym != 0 (calendar asymmetric)": [
        len(g4b), g4b["total_net_bp"].median(),
        g4b[g4b["direction"] == "fade"]["total_net_bp"].median(),
        g4b[g4b["direction"] == "momentum"]["total_net_bp"].median(),
        g4b["total_net_bp"].max(), float((g4b["total_net_bp"] > 0).mean()),
        g4b["n_trades"].median()],
}, index=["n_configs", "grid_median_bp", "fade_median_bp", "momentum_median_bp",
          "best_net_bp", "pct_positive", "median_trades"])
print("K4 vs K4b — the same raw-fly fade, split on whether the calendar is "
      "symmetric")
print(cmp4.round(1).to_string())
sym_fade = float(g4[g4["direction"] == "fade"]["total_net_bp"].median())
asym_fade = float(g4b[g4b["direction"] == "fade"]["total_net_bp"].median())
sym_wins = (float(g4[g4["direction"] == "fade"]["total_net_bp"].median())
            > float(g4[g4["direction"] == "momentum"]["total_net_bp"].median()))
asym_wins = (float(g4b[g4b["direction"] == "fade"]["total_net_bp"].median())
             > float(g4b[g4b["direction"] == "momentum"]["total_net_bp"].median()))
print(f"\n  fade median: symmetric {sym_fade:+.1f}bp vs asymmetric "
      f"{asym_fade:+.1f}bp   (per trade, normalised by median trade count: "
      f"{sym_fade / max(float(g4['n_trades'].median()), 1):+.3f} vs "
      f"{asym_fade / max(float(g4b['n_trades'].median()), 1):+.3f} bp)")
print(f"  fade is the winning SIGN on symmetric keys: {sym_wins};  "
      f"on asymmetric keys: {asym_wins}")
_ps = _pond_split.set_index("signal")
_sym_pond = float(_ps.loc["symmetric keys", "mean_abs_bp"])
_asym_pond = float(_ps.loc["asymmetric keys", "mean_abs_bp"])
_pond_ratio = _sym_pond / _asym_pond
_pnl_ratio = abs(asym_fade / max(float(g4b["n_trades"].median()), 1)) / \
    abs(sym_fade / max(float(g4["n_trades"].median()), 1))
print(f"""
  CONFOUND CHECK. This is a STATIC partition of {len(sym_keys)} keys against {len(asym_keys)}, not a
  day-by-day gate, so before reading it as a calendar effect it has to survive
  the obvious alternative: that the symmetric bucket simply contains
  bigger-moving flies.

    mean |21d move|      symmetric {_sym_pond:5.2f}bp   asymmetric {_asym_pond:5.2f}bp   ratio {_pond_ratio:.2f}x
    loss per trade       symmetric {abs(sym_fade / max(float(g4['n_trades'].median()), 1)):5.2f}bp   asymmetric {abs(asym_fade / max(float(g4b['n_trades'].median()), 1)):5.2f}bp   ratio {_pnl_ratio:.2f}x

  A fixed 2.0bp round trip is a SMALLER fraction of a bigger move, so a bucket
  that moves {_pond_ratio:.2f}x further loses less per trade for reasons that have nothing to
  do with the Fed. The two ratios are {_pond_ratio:.2f} and {_pnl_ratio:.2f}: {'the pond explains essentially the whole gap' if abs(_pond_ratio - _pnl_ratio) < 0.35 else 'the pond does NOT fully explain the gap'}.

  VERDICT ON THE LAST PIECE OF SUPPORT: {'the symmetry split is a move-size effect wearing a calendar label.' if abs(_pond_ratio - _pnl_ratio) < 0.35 else 'part of the split survives the move-size control and is worth another look.'}
  Both sides lose money at 2.0bp either way.""")
cmp4.to_csv(K.DATA_DIR / "symmetry_gate.csv")
_pond_split.to_csv(K.DATA_DIR / "symmetry_pond.csv", index=False)

# %% [markdown]
# ## 9. K3 — cross-sectional fade
#
# The prior work's one genuinely positive result was the naive within-bucket
# `ls_fade` (IR ≈ +1.35 gross, non-overlapping Sharpe ≈ +1.97) — gross of costs,
# one regime, one year. Reproduced here through the same engine, so it pays the
# same per-contract round trip as everything else, on the raw fly and on the
# meeting residual.

# %%
# `xsection_signal` buckets by a per-COLUMN label, and a key's pack colour
# ROLLS with its constant-maturity slot -- a fly born in the blues arrives in
# the whites four years later. Labelling columns by the pack a key was born in
# is prior-lab bug 11 and would put most of the strip in one bucket. The
# `window` argument already converts each key to its own trailing z-score before
# the cross-section is taken, so the ranking is over dislocation in units of
# each key's own volatility and is scale-free across maturities. That is what
# the bucketing was there to achieve, so a single bucket is the correct choice
# here rather than a wrong one.
groups6 = None


def k3_raw(L, window):
    return xsection_signal(L, groups=groups6, method="zscore", window=window)


out_k3 = K.run_family("K3. cross-sectional fade, raw fly (6m, liquid16)",
                      lab=lab6, signal_fn=k3_raw, grid_spec=GRID, params=PARAMS,
                      base=BASE, cls="xsection",
                      note="rank each key's own trailing dislocation across the "
                           "strip", exits=EXITS)

# %%
_mres6_pack = mres6


def k3_resid(L, window):
    return xsection_signal(_mres6_pack, groups=groups6, method="zscore",
                           window=window)


out_k3r = K.run_family("K3r. cross-sectional fade, meeting residual (6m)",
                       lab=lab6, signal_fn=k3_resid, grid_spec=GRID,
                       params=PARAMS, base=BASE, cls="xsection",
                       note="same, on the calendar-adjusted level", exits=EXITS)

# %% [markdown]
# ## 10. Front slots only, attributed by date
#
# A key's constant-maturity slot **rolls** — a fly born at slot 15 arrives at
# slot 2 four years later — so restricting by a key's birth slot tags every key
# with the wrong bucket (bug 11 of the prior lab). The restriction is applied
# through the `(date, key)` gate instead.

# %%
lab6_front = dict(lab6)
front_mask = (lab6["cm_slot_at"].reindex(index=lab6["levels"].index,
                                         columns=lab6["levels"].columns)
              <= CONFIG["front_slot_cut"])
lab6_front["gate"] = lab6["gate"] & front_mask.fillna(False)
print(f"front-slot cells (cm_slot <= {CONFIG['front_slot_cut']}): "
      f"{100 * float(front_mask.fillna(False).mean().mean()):.1f}%")
out_front = K.run_family(
    f"K1f. meeting residual, belly in slot <= {CONFIG['front_slot_cut']} (6m)",
    lab=lab6_front, signal_fn=k1_6, grid_spec=GRID, params=PARAMS, base=BASE,
    cls="kink", note="where the liquidity and the dispersion both are", exits=EXITS)

# %%
per = K.per_slot_table(out_k1_6["result"], lab6)
if not per.empty:
    print("K1 (6m) net P&L by the CM slot each trade was ENTERED in:")
    print(per.round(3).to_string(index=False))

# %% [markdown]
# ## 11. The long window — 2019+, which buys ZIRP and the hiking cycle
#
# Nothing is believed on one window. `front8` restricts the back leg to slot 8
# but starts in 2019, so it is the only window containing a full policy cycle.

# %%
lab6_long = K.load_kink_lab("6m", CONFIG["long_window"], lam=CONFIG["lam"],
                            max_slot=CONFIG["max_slot"], contracts=contracts)
mres6_long = resid_fly(lab6_long, CONFIG["lam"])
print(f"{lab6_long['levels'].shape[1]} flies x {lab6_long['levels'].shape[0]} "
      f"sessions, {lab6_long['window_why']}")


def k1_long(L, window):
    return scale_only_zscore(mres6_long, window=window)


out_long = K.run_family("K1L. meeting residual (6m, front8, 2019+)",
                        lab=lab6_long, signal_fn=k1_long, grid_spec=GRID,
                        params=PARAMS, base=BASE, cls="kink",
                        note="the regime-rich window", exits=EXITS)

# %%
out_k0_long = K.run_family("K0L. raw fly z-score (6m, front8, 2019+)",
                           lab=lab6_long, signal_fn=k0, grid_spec=GRID,
                           params=PARAMS, base=BASE, cls="kink",
                           note="control on the same window", exits=EXITS)

# %% [markdown]
# ## 12. Sensitivity to the projected calendar
#
# 2028+ meeting dates do not exist yet. They are projected by a documented rule
# and every projected row is flagged. This shifts the projection by a week in
# each direction and reports how much the signal moves — rather than asking
# anyone to take the projection on trust.

# %%
rows = []
base_sig = mres6
touched = lab6["calendar"].groupby("key")["proj_any"].any()
for shift in (-1, 0, 1):
    mt = fomc_decisions(datetime.date(2017, 1, 1), datetime.date(2032, 12, 31),
                        shift_weeks=shift)
    p = resid_fly(lab6, CONFIG["lam"], mt, f"shift{shift}")
    corr = pd.Series({c: base_sig[c].corr(p[c]) for c in base_sig.columns})
    # the median key never sees a projected meeting, so the median correlation
    # is 1.000 whatever the shift does. The binding number is the worst key,
    # and the worst key among those that DO reach past the published calendar.
    hit = [c for c in corr.index if bool(touched.get(c, False))]
    rows.append({"projection_shift_weeks": shift,
                 "resid_sd_bp": float(p.stack().std()),
                 "median_corr": float(corr.median()),
                 "min_corr": float(corr.min()),
                 "min_corr_projected_keys": float(corr[hit].min()) if hit else np.nan,
                 "n_keys_projected": len(hit)})
sens = pd.DataFrame(rows)
print(sens.round(4).to_string(index=False))
proj = lab6["resid_extras"]["proj_share"]
print(f"\n  share of each date's fitted jump magnitude on PROJECTED meetings: "
      f"median {proj.median():.3f}, p95 {proj.quantile(0.95):.3f}")
print(f"  structures whose span reaches a projected meeting: "
      f"{100 * float(lab6['calendar']['proj_any'].mean()):.1f}% of rows, "
      f"{int(touched.sum())} of {len(touched)} keys")
worst = float(sens.loc[sens["projection_shift_weeks"] != 0,
                       "min_corr_projected_keys"].min())
print(f"""
  READ THE min_corr COLUMN, NOT THE MEDIAN. The median key never reaches a
  projected meeting, so its correlation is 1.000 whatever the shift does -- the
  median is uninformative by construction. The binding number is the worst key
  among the {int(sens['n_keys_projected'].iloc[0])} that DO span a projected meeting, and it is {worst:+.3f}.

  So a single week of projection error DESTROYS the meeting residual on the
  back of the strip. That is a real limitation of K1 on deep keys, and it cuts
  the same way as everything else in this notebook: the part of the signal that
  depends on the meeting calendar is the part that is least reliable, while the
  headline rows (front8, and belly in slot <= 5) barely touch it. Section 4
  already showed the back of the strip cannot pay a 2.0bp round trip on move
  size alone, so nothing tradeable rests on it -- but any future work that
  reaches past the published calendar has to carry this number.""")

# %% [markdown]
# ## 13. Verdict

# %%
league = pd.read_csv(K.DATA_DIR / "league_table.csv")
print(f"LEAGUE TABLE — {len(league)} rows, taker = {K.TAKER_BP}bp per contract "
      f"round trip\n")
show = ["framework", "variant", "structure", "window", "n_trades", "hit_rate",
        "avg_net_bp", "total_gross_bp", "total_net_bp", "net_bp_maker",
        "net_bp_taker", "grid_median_net_bp", "dsr_prob", "nonoverlap_sharpe",
        "verdict"]
print(league.sort_values("total_net_bp", ascending=False)[
    [c for c in show if c in league.columns]].round(3).to_string(index=False))
league.sort_values("total_net_bp", ascending=False).to_csv(
    K.DATA_DIR / "league_table_sorted.csv", index=False)

# %%
print("verdict distribution:")
print(league["verdict"].value_counts().to_string())
n = len(league)
print(f"\n  rows net positive GROSS               "
      f"{int((league['total_gross_bp'] > 0).sum())} / {n}")
print(f"  rows net positive at maker (0.0bp)    "
      f"{int((league['net_bp_maker'] > 0).sum())} / {n}")
print(f"  rows net positive at taker ({K.TAKER_BP}bp)   "
      f"{int((league['net_bp_taker'] > 0).sum())} / {n}")
print(f"  rows with a positive GRID MEDIAN      "
      f"{int((league['grid_median_net_bp'] > 0).sum())} / {n}")
print(f"  median DSR probability                "
      f"{league['dsr_prob'].median():.4f}   (threshold 0.5)")
print(f"  ALIVE                                 "
      f"{int((league['verdict'] == 'ALIVE').sum())}")
_n_fam = league["framework"].nunique()
print(f"""
  ONE CAVEAT ON THE DSR, IN THE DIRECTION THAT MATTERS. Each row is deflated by
  its OWN family's {int(league['n_trades'].notna().sum() and 72)} configs, but {_n_fam} families were searched -- most of them
  on the identical liquid16 level panel. The honest trial count is closer to
  {_n_fam} x 72 = {_n_fam * 72}, so every DSR printed here is TOO GENEROUS. It does not change a
  verdict, because the median is already {league['dsr_prob'].median():.4f}.""")

# %%
signs = pd.read_csv(K.DATA_DIR / "sign_tests.csv")
w = signs.pivot_table(index="framework", columns="direction",
                      values="median_net_bp", aggfunc="first")
w["fade_wins"] = w.get("fade", np.nan) > w.get("momentum", np.nan)
print("SIGN TEST across every framework (median net bp of the whole sweep)")
print(w.round(1).to_string())
print(f"\n  fade beats momentum in {int(w['fade_wins'].sum())} of {len(w)} "
      f"frameworks -- mean reversion is the right DIRECTION; it is the cost and "
      f"the packaging that fail.")

# %%
shadows = pd.read_csv(K.DATA_DIR / "shadow_tests.csv")
beat = (shadows[shadows["instrument"] != "fly"]
        .groupby("framework")["beats_fly_net"].any())
print("LINEAR-SHADOW DECOMPOSITION — does a simpler instrument beat the fly?")
print(f"  frameworks where some shadow beats the fly on net bp: "
      f"{int(beat.sum())} / {len(beat)}")
belly = shadows[shadows["instrument"] == "belly"].set_index("framework")["total_net_bp"]
fly = shadows[shadows["instrument"] == "fly"].set_index("framework")["total_net_bp"]
cmp_ = pd.DataFrame({"fly": fly, "outright_belly": belly})
cmp_["belly_wins"] = cmp_["outright_belly"] > cmp_["fly"]
print(cmp_.round(1).to_string())
print(f"\n  the OUTRIGHT BELLY on the identical signal beats the fly in "
      f"{int(cmp_['belly_wins'].sum())} of {len(cmp_)} frameworks.")
res_rows = [i for i in cmp_.index if i.startswith(("K1", "K3r"))]
raw_rows = [i for i in cmp_.index if i.startswith(("K0", "K2", "K4", "K3."))]
if res_rows and raw_rows:
    print(f"\n  split by definition -- the belly beats the fly on "
          f"{int(cmp_.loc[raw_rows, 'belly_wins'].sum())} of {len(raw_rows)} "
          f"RAW-fly frameworks but only "
          f"{int(cmp_.loc[res_rows, 'belly_wins'].sum())} of {len(res_rows)} "
          f"RESIDUAL frameworks.")
    print("  That is the one structural point in the residual's favour: a raw fly")
    print("  z-score is substantially a rates-direction signal wearing three legs,")
    print("  and removing the smooth component removes most of that leak. It does")
    print("  not make the fly pay -- it makes it an honest fly.")

# %%
reg = pd.read_csv(K.DATA_DIR / "regime_splits.csv")
tot = reg.groupby("regime").agg(total_net_bp=("total_net_bp", "sum"),
                                n_trades=("n_trades", "sum"),
                                frameworks_positive=("total_net_bp",
                                                     lambda s: int((s > 0).sum())),
                                n_frameworks=("total_net_bp", "size"))
print("REGIME SPLIT summed across every framework's best config")
print(tot.reindex(K.REGIME_ORDER).dropna(how="all").round(1).to_string())

# %%
print("=" * 92)
print("WHAT THIS NOTEBOOK MEASURED")
print("=" * 92)
best_row = league.loc[league["total_net_bp"].idxmax()]
n_raw = len(raw_rows)
n_res = len(res_rows)
w_raw = int(cmp_.loc[raw_rows, "belly_wins"].sum()) if raw_rows else 0
w_res = int(cmp_.loc[res_rows, "belly_wins"].sum()) if res_rows else 0
print(f"""
1. THE CALENDAR EFFECT IS REAL ARITHMETIC AND EMPIRICALLY NEGLIGIBLE.
   phi_sum -- the butterfly a 1bp-per-meeting path prints -- has sd
   {cs['phi_sd'].median():.3f} meetings, and the measured pace between a 3m fly's own
   wings has median |{mech['measured_pace'].abs().median():.2f}| bp per meeting. The product is a
   few tenths of a basis point against a fly whose daily sd is several bp.
   Per date, phi explains a median {mech['r2'].median():.1%} of the cross-section of flies,
   and the slope it fits agrees in sign with the measured pace on {agree:.1%}
   of dates -- a coin flip.

2. REMOVING A SMOOTH COMPONENT DOES HELP -- BUT NOT BECAUSE IT IS THE CALENDAR.
   The raw 6m fly has essentially no cross-sectional mean reversion
   (IC {float(ic_tab.set_index('basis').loc[raw, 'xs_ic_h21']):+.3f} at h=21); every smoothed basis is at
   {ic_tab.set_index('basis').loc[decoys + [real], 'xs_ic_h21'].min():+.3f} to {ic_tab.set_index('basis').loc[decoys + [real], 'xs_ic_h21'].max():+.3f}. But the best of them on that statistic is
   "{best_ic}", the real calendar is inside the decoy
   range on the grid median ({_inside('grid_median_bp')}), and the meeting bases have a WORSE grid
   median than the plain raw-fly z-score. Only a cubic spline in slot index --
   which needs no calendar at all -- improves both the best config and the
   distribution. See section 5.

3. THE BINDING CONSTRAINT IS THE POND, NOT THE SIGN.
   Fade beats momentum in {int(w['fade_wins'].sum())} of {len(w)} frameworks. The 3m fly's oracle bound
   barely clears a 2.0bp round trip even at a 21-day horizon; the 6m fly's
   clears it by ~4bp, which is why every live-looking row is a 6m row.

4. ONE THING THE NEW DEFINITION DOES EARN, AND ONE THAT DID NOT SURVIVE.
   (a) EARNED: it stops the fly being a directional trade in disguise. The
       outright belly on the identical signal beats the butterfly on {w_raw} of {n_raw}
       RAW-fly frameworks but only {w_res} of {n_res} meeting-residual ones -- removing the
       smooth component removes most of the rates-direction leak the prior lab
       found. It does not make the fly pay; it makes it an honest fly.
   (b) DID NOT SURVIVE: the calendar-symmetry split. Fading the raw fly is the
       winning SIGN on symmetric keys ({sym_fade:+.1f}bp median) and the losing sign on
       asymmetric ones ({asym_fade:+.1f}bp) -- but `asym` is constant per key, so this is a
       static partition of {len(sym_keys)} keys against {len(asym_keys)}, and the symmetric bucket moves
       {_pond_ratio:.2f}x further over 21 days. A fixed round trip is a smaller fraction of a
       bigger move, and that alone accounts for the gap.

5. NOTHING IS ALIVE.
   {int((league['verdict'] == 'ALIVE').sum())} of {len(league)} league rows. Best row: {best_row['framework']} / {best_row['variant']},
   {best_row['total_net_bp']:+.1f}bp net at taker over {int(best_row['n_trades'])} trades, but a grid median of
   {best_row['grid_median_net_bp']:+.1f}bp and DSR p = {best_row['dsr_prob']:.3f} -- the best corner of a negative
   sweep, which the verdict function calls {best_row['verdict']}.
   {int((league['grid_median_net_bp'] > 0).sum())} of {len(league)} rows have a positive grid median.

ANSWER TO THE QUESTION THIS LAB WAS SET:
   Removing the FOMC meeting structure does NOT turn the kink into a real
   signal, and the prior RED verdict was right -- but not for the reason it
   gave. The kink is not mostly calendar (1-6% of variance). What the
   meeting fit actually does is remove a SMOOTH component, and any smoothing
   does that: a calendar with the wrong dates, an evenly-spaced pseudo-calendar
   and a cubic spline all land in the same place. The residual of any smoothing
   is a genuinely better mean-reversion signal than the raw fly -- and it is
   still too small to pay a 2.0bp per-contract round trip.

   FOUR TESTS WERE RUN AGAINST THE HYPOTHESIS AND IT FAILED ALL FOUR: the size
   (section 2), the mechanism (section 2a), the placebos (section 5) and the
   calendar-symmetry conditioning (section 8a), which looked like the one win
   until the move sizes on each side of the split were measured.
""")
print(f"total runtime {time.time() - T0:.0f}s")
