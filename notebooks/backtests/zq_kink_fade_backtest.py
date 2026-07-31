# %% [markdown]
# # Fed Funds (ZQ) kink-fade — does a cleaner meeting read pay?
#
# **Design:** `docs/superpowers/specs/2026-07-30-zq-kink-fade-design.md`
# **Companion:** `sfr_kink_fade_backtest.ipynb`, which found that the FOMC
# calendar explains 1–6% of an SR3 butterfly's variance and that removing it
# does not make the kink tradeable.
#
# The natural objection to that result is that SR3 is the wrong instrument for
# the question. SR3 settles on a **compounded** average over a quarterly IMM
# window, so policy meetings enter diluted and overlapping. ZQ settles on the
# **arithmetic average of daily EFFR over a single calendar month** (CBOT Ch. 22
# §22103), so a meeting enters as a clean day-count blend of exactly two regimes:
#
# > A 2026-12-09 decision takes effect on the 10th, so the December contract is
# > **9/31 pre and 22/31 post**, while the January contract is **entirely** post
# > until the 2027-01-27 decision clips its last four days. **The January
# > contract is the clean read on the December meeting.**
#
# If the kink-fade thesis has a natural habitat it is here, where the calendar
# component of every contract is exactly computable rather than approximated.
#
# The order below is the order in which the question can be killed, and the
# brief for this work is explicit that it should be: **measure the oracle
# ceiling before building anything**, and if the FF oracle cannot clear cost,
# stop and report that.

# %%
CONFIG = dict(
    max_rank=12,                        # FF depth beyond ~12m is thin; measured below
    start=None, end=None,
    lam=100.0,                          # 2nd-difference penalty on the jump path
    lam_sweep=(0.0, 0.1, 1.0, 10.0, 100.0, 1.0e3, 1.0e5),
    cost_spread_bp=1.0,                 # 2 contracts x 2 sides x 0.25bp
    cost_fly_bp=2.0,                    # 4 contracts x 2 sides x 0.25bp
    n_packages=100,
    windows=(60, 120, 250),
    entry_zs=(1.5, 2.0, 2.5),
    exits=("z0", "t10", "t21", "t42"),
    directions=("fade", "momentum"),
    max_hold=63,
    lag=1,
    horizons=(5, 10, 21),
    high_exposure_cut=0.5,              # differential exposure, in meetings
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

from RVUtils.MeanRev import MRConfig
from RVUtils.MeanRev.ff import (
    ZQ_DV01_USD, ZQ_HALF_TICK_BP, ZQ_POINT_USD, ZQ_TICK_BP,
    applicable_source_day, compounding_bias_bp, delivery_window,
    effr_publication_days, expected_settle_rate, half_tick_onset,
    round_settle_rate, zq_exposure_vector, zq_regime_weights,
)
from RVUtils.MeanRev.meetings import fomc_decisions
from RVUtils.MeanRev.signals import scale_only_zscore, zscore_signal
from RVUtils.mean_reversion import half_life

import zq_kink_fade_common as Z

pd.set_option("display.width", 235)
pd.set_option("display.max_columns", 60)
plt.rcParams.update({"figure.dpi": 110, "axes.grid": True, "grid.alpha": 0.25})

T0 = time.time()
print(f"ZQ: ${ZQ_POINT_USD:,.0f} per index point, ${ZQ_DV01_USD:.2f} per bp, "
      f"tick {ZQ_TICK_BP}bp (half {ZQ_HALF_TICK_BP}bp near delivery)")
print(f"round trip: spread {CONFIG['cost_spread_bp']}bp "
      f"(${CONFIG['cost_spread_bp'] * ZQ_DV01_USD:,.2f}/contract-pair), "
      f"fly {CONFIG['cost_fly_bp']}bp")
print(f"results -> {Z.DATA_DIR}")

# %% [markdown]
# ## 0. Contract audit — the rulebook, checked
#
# Rule 8 of the house honesty rules: verify field scales and print units before
# trusting them. For ZQ that means the settlement rule itself, because the whole
# study is built on it being exactly computable.

# %%
print("§22101/§22102.B — contract scaling")
print(f"  index point ${ZQ_POINT_USD:,.0f}   one bp ${ZQ_DV01_USD:.2f}   "
      f"tick 0.005pt = {ZQ_TICK_BP}bp = ${ZQ_TICK_BP / 100 * ZQ_POINT_USD:.3f}")
print(f"  half tick 0.0025pt = {ZQ_HALF_TICK_BP}bp = "
      f"${ZQ_HALF_TICK_BP / 100 * ZQ_POINT_USD:.4f}")

print("\n§22103 — settlement rounding, the rulebook's own worked example")
for r in (2.5915, 2.5905, 2.5925):
    print(f"  average {r} -> {round_settle_rate(r)} -> price "
          f"{100 - round_settle_rate(r):.3f}")
print("  (2.5915 -> 2.592 -> 97.408 is verbatim from the rule. 2.5925 is the")
print("   case that breaks naive float rounding: it sits a hair below the tie in")
print("   binary and rounds DOWN unless the arithmetic is done in decimal.)")

print("\nTHE CONVENTION TRAP — arithmetic vs compounded, in bp")
bias = pd.DataFrame({
    "n_days": [28, 30, 31, 31, 91],
    "rate_pct": [4.0, 4.11, 4.0, 0.1, 4.0]})
bias["compounding_bias_bp"] = [compounding_bias_bp(r, n) for n, r in
                               zip(bias["n_days"], bias["rate_pct"])]
bias["vs_half_tick"] = bias["compounding_bias_bp"] / ZQ_HALF_TICK_BP
print(bias.round(3).to_string(index=False))
print("  A compounded window overstates the arithmetic average by ~r^2*n/720.")
print("  At 4% over a month that is ~0.7bp -- nearly three ZQ half-ticks, so a")
print("  ZQ built on a SOFR (compounded) spec is the WRONG CONTRACT, not a")
print("  close one. rateslib's `usd_stir1` spec is already the averaged one")
print("  (`rfr_payment_delay_avg`, $41.67/bp); `usd_stir` is quarterly and")
print("  compounded. Measured directly on the curve: 0.658bp apart.")

# %% [markdown]
# ### 0a. The publication calendar, and the day the carry rule bites
#
# §22103: any day the FRBNY does not publish takes **the last preceding
# published rate**. So a Friday's print carries Friday, Saturday and Sunday —
# three days of weight in the settlement average — and a decision whose
# effective day is a holiday does not reach the average until the next
# publication day.

# %%
days = [datetime.date(2026, 7, 1) + datetime.timedelta(days=i) for i in range(31)]
src = applicable_source_day(days)
carry = pd.Series(src).value_counts().sort_index()
print("July 2026 — how many calendar days each published EFFR covers:")
print(pd.DataFrame({"publication_day": carry.index,
                    "weekday": [d.strftime("%a") for d in carry.index],
                    "days_covered": carry.to_numpy()}).to_string(index=False))
print(f"\n  {int((carry == 3).sum())} days carry 3x weight (Fri+Sat+Sun); "
      f"{int((carry > 3).sum())} carry more (a holiday-extended weekend).")

pub = set(effr_publication_days(datetime.date(2018, 1, 1), datetime.date(2028, 1, 1)))
offenders = [m for m in fomc_decisions(datetime.date(2018, 1, 1),
                                       datetime.date(2027, 12, 31))
             if m + datetime.timedelta(days=1) not in pub]
print(f"\nDecisions whose effective day is NOT a publication day: {offenders}")
if offenders:
    m = offenders[0]
    w = delivery_window("M25")[:2]
    exp_real = zq_exposure_vector(w, [m])[0]
    print(f"  {m} -> {m + datetime.timedelta(days=1)} is Juneteenth (a federal")
    print(f"  holiday since 2021), so the new rate first reaches the average on")
    print(f"  Friday the 20th. June 2025 exposure {exp_real:.4f} = 11/30, not")
    print(f"  12/30 -- one of thirty days, 3.3% of the meeting, ~0.8bp on a 25bp")
    print(f"  move. This is the concrete reason the day count runs through the")
    print(f"  publication calendar rather than the obvious way.")

# %% [markdown]
# ### 0b. The half-tick onset (§22102.C), encoded not approximated
#
# The rule has two branches and the second one starts the half-tick *before* the
# delivery month. It decides which contract-days cost 0.25bp to cross.

# %%
rows = []
for y in (2026, 2027):
    for m in range(1, 13):
        code = f"{'FGHJKMNQUVXZ'[m - 1]}{y % 100:02d}"
        first = datetime.date(y, m, 1)
        onset = half_tick_onset(code)
        rows.append({"code": code, "month_starts": first.strftime("%a"),
                     "first_of_month": first, "half_tick_from": onset,
                     "days_before_month": (first - onset).days})
onsets = pd.DataFrame(rows)
print(onsets.to_string(index=False))
print("\n  Sat/Sun/Mon starts -> the first trading day OF the month;")
print("  Tue-Fri starts -> the trading day after the LAST SUNDAY of the previous")
print("  month, so the discount can begin up to a week early. (June 2027 is the")
print("  edge case: Memorial Day pushes the anchor onto the 1st itself.)")

# %% [markdown]
# ## 1. The panel
#
# Raw ZQ settlement prices from Barchart, one full-history request per contract
# symbol. Marks are settles, never a curve — the same house rule as SR3, and
# section 6 measures what the curve alternative would have cost.
#
# Only **pre-accrual** contracts are kept. Once a delivery month begins, part of
# the settle is realised fixings and the rate stops being a forward read.

# %%
lab = Z.load_zq(max_rank=CONFIG["max_rank"], start=CONFIG["start"],
                end=CONFIG["end"])
rates, rank, oi = lab["rates"], lab["rank"], lab["oi"]
print(f"ZQ panel: {rates.shape[0]:,} sessions x {rates.shape[1]} contracts, "
      f"{rates.index.min().date()} -> {rates.index.max().date()}")
raw = pd.read_parquet(Z.PANEL_DIR / "contracts.parquet")
print(f"  raw file: {len(raw):,} rows, {raw['code'].nunique()} contracts; "
      f"kept ranks 1..{CONFIG['max_rank']}, pre-accrual only")

live = lab["contracts"].copy()
live["year"] = live["as_of"].dt.year
print("\nZERO-VOLUME DAYS by contract rank and year (%) — the honest-depth question")
zv = live.pivot_table(index="rank", columns="year", values="volume",
                      aggfunc=lambda s: 100.0 * float((s == 0).mean()))
print(zv.round(0).to_string())
print("\nmedian OPEN INTEREST by rank and year")
print(live.pivot_table(index="rank", columns="year", values="open_interest",
                       aggfunc="median").round(0).to_string())
print("\n  FF liquidity thins with maturity exactly as SR3's slots 9-16 did. The")
print("  ranks above are reported rather than assumed away, and the headline")
print("  families below are run on the front of the strip.")

# %% [markdown]
# ## 2. Meeting exposure — the formalisation of "FFF27 reads the Dec26 meeting"
#
# For each contract, the fraction of its delivery month's calendar days sitting
# at or after each meeting's effective rate. The regime weights partition the
# month and therefore **sum to exactly one** — a property that can be asserted
# without reference to the implementation, which is the only kind of check worth
# writing for arithmetic this fiddly.

# %%
meetings = lab["meetings"]
dec_meet = datetime.date(2026, 12, 9)
demo = []
for code in ("X26", "Z26", "F27", "G27"):
    w = delivery_window(code)
    e = zq_exposure_vector(w[:2], [dec_meet, datetime.date(2027, 1, 27)])
    reg = zq_regime_weights(w[:2], [dec_meet, datetime.date(2027, 1, 27)])
    demo.append({"contract": f"ZQ{code}", "month": w[0].strftime("%b-%y"),
                 "n_days": w[2], "exp_Dec26": e[0], "exp_Jan27": e[1],
                 "regime_weights_sum": reg.sum(),
                 "cleanliness": float(reg.max())})
print("THE WORKED EXAMPLE — the December-2026 meeting, seen by four contracts")
print(pd.DataFrame(demo).round(4).to_string(index=False))
print("\n  ZQZ26 is the BLENDED month (9/31 pre, 22/31 post).")
print("  ZQF27 is the CLEAN read: 100% post-December, until the late-January")
print("  decision clips its last four days.")
print("  `cleanliness` = the largest single-regime day share, i.e. how much of")
print("  the month sits in one policy state.")

# %%
codes = lab["codes"]
rowsx = []
for code in codes:
    w = delivery_window(code)
    reg = zq_regime_weights(w[:2], meetings)
    n_in = int((zq_exposure_vector(w[:2], meetings) % 1 > 1e-9).sum())
    rowsx.append({"code": code, "month": w[0], "n_days": w[2],
                  "meetings_inside": n_in, "cleanliness": float(reg.max())})
cle = pd.DataFrame(rowsx)
print("CLEANLINESS across the whole contract universe")
print(cle.groupby("meetings_inside")
      .agg(n_contracts=("code", "size"), mean_cleanliness=("cleanliness", "mean"),
           min_cleanliness=("cleanliness", "min")).round(3).to_string())
print(f"\n  {int((cle['meetings_inside'] == 0).sum())} of {len(cle)} contracts contain NO meeting at all -- those")
print("  are the CLEAN months, and they are the ones that read the previous")
print("  meeting without dilution.")
cle.to_csv(Z.DATA_DIR / "cleanliness.csv", index=False)

# %% [markdown]
# ## 3. The oracle ceiling — measured before anything is built on it
#
# The SR3 lesson, stated as a rule: **a structure whose `E[|forward move|]` does
# not exceed its round trip cannot be rescued by a better signal**, because that
# expectation is exactly what a trader with perfect foresight of the *direction*
# would capture. On SR3 that number was 2.378bp against a 2.0bp cost — barely
# positive, and the entire reason the lab failed.
#
# The brief for this work says to measure the FF equivalent first and stop if it
# does not clear. So:

# %%
spread = Z.zq_structures(lab, n_legs=2)
fly = Z.zq_structures(lab, n_legs=3)
print(f"spreads: {spread['levels'].shape[1]} keys, round trip "
      f"{spread['cost_bp']}bp")
print(f"flies:   {fly['levels'].shape[1]} keys, round trip {fly['cost_bp']}bp")

for nm, st in (("M1-M2 spread", spread), ("3-month fly", fly)):
    lv = st["levels"]
    d = lv.diff().stack()
    print(f"\n{nm}: pooled sd {lv.stack().std():.2f}bp "
          f"({lv.stack().std() / ZQ_TICK_BP:.1f} ticks), daily sd "
          f"{d.std():.3f}bp, unchanged on {100 * float((d.abs() < 1e-9).mean()):.0f}% "
          f"of days, {int(lv.stack().round(4).nunique())} distinct values")

# %%
o_sp = Z.oracle_block(spread["levels"], spread["cost_bp"],
                      horizons=CONFIG["horizons"], tag="spread_raw")
o_fl = Z.oracle_block(fly["levels"], fly["cost_bp"],
                      horizons=CONFIG["horizons"], tag="fly_raw")

# %% [markdown]
# ### 3a. Which structures are structurally pinned?
#
# The obvious criterion — "is there an FOMC meeting between the two delivery
# months" — is **wrong**, and the first pass of this work measured it being
# wrong: the "no meeting between" spreads moved *further* than the others
# (sd 9.5bp against 8.8bp). November/December has no decision between the 1st of
# November and the 1st of December, yet the December contract is 22/31 exposed
# to the December meeting *inside its own month* while November is not exposed at
# all. The spread carries most of a decision.
#
# The right criterion is **differential exposure**: `max_m |Σ_j w_j·W[leg_j, m]|`,
# which is zero only when every meeting loads identically on every leg.

# %%
for nm, st in (("M1-M2 spread", spread), ("3-month fly", fly)):
    de = st["diff_exposure"]
    print(f"\n{nm}: differential exposure over {len(de)} structures "
          f"(in meetings-equivalent)")
    print(f"  == 0 (structurally pinned): {int((de < 1e-12).sum())}    "
          f"< 0.05: {int((de < 0.05).sum())}")
    print(f"  quantiles: "
          f"{de.quantile([0, .1, .25, .5, .75, .9, 1]).round(3).to_dict()}")
print("\n  NOT ONE structure is pinned. The brief's expectation that adjacent")
print("  no-meeting months would be degenerate is false: every adjacent ZQ pair")
print("  carries between 0.13 and 1.0 of a policy decision, because a meeting")
print("  inside EITHER month splits them.")

# %%
rows = []
for nm, st in (("M1-M2 spread", spread), ("3-month fly", fly)):
    de, lv = st["diff_exposure"], st["levels"]
    buckets = pd.cut(de, [-1e-9, 1e-9, 0.2, 0.5, 1.0, 10.0],
                     labels=["pinned", "(0,0.2]", "(0.2,0.5]", "(0.5,1.0]", ">1.0"])
    for b in buckets.cat.categories:
        cols = list(de.index[buckets == b])
        if not cols:
            continue
        p = Z.move_profile(lv[cols], None, horizons=(21,),
                           round_trip_bp=st["cost_bp"]).iloc[0]
        s = lv[cols]
        rows.append({"structure": nm, "diff_exposure": str(b), "n_keys": len(cols),
                     "cost_bp": st["cost_bp"], "sd_bp": float(s.stack().std()),
                     "sd_ticks": float(s.stack().std() / ZQ_TICK_BP),
                     "absmove_h21": p["mean_abs_bp"],
                     "oracle_net_h21": p["oracle_net_bp"],
                     "p_beat_cost": p["p_beat_cost"]})
byexp = pd.DataFrame(rows)
print("ORACLE BY DIFFERENTIAL-EXPOSURE BUCKET (h=21)")
print(byexp.round(3).to_string(index=False))
byexp.to_csv(Z.DATA_DIR / "oracle_by_exposure.csv", index=False)
best_sp = byexp[(byexp["structure"] == "M1-M2 spread")]["oracle_net_h21"].max()
best_fl = byexp[(byexp["structure"] == "3-month fly")]["oracle_net_h21"].max()
print(f"""
  THE FIRST DECISION POINT.
  Best spread oracle at h=21, any exposure bucket: {best_sp:+.3f}bp against a {spread['cost_bp']}bp round trip
  Best fly    oracle at h=21, any exposure bucket: {best_fl:+.3f}bp against a {fly['cost_bp']}bp round trip

  The FF BUTTERFLY is dead on arrival: its oracle is negative in every bucket at
  every horizon shorter than a month. The FF SPREAD has real headroom, but only
  in the high-differential-exposure bucket -- which is to say only where it is
  carrying a policy decision, which is a directional meeting trade and not a
  kink fade. Section 4 asks whether the KINK specifically has any.""")


# %% [markdown]
# ### 3b. Meeting-indexed structures — what a desk actually trades
#
# Everything above indexes by **delivery month**. A STIR desk does not: it
# indexes by **meeting**, and uses the contract whose month spends the largest
# share of itself at that decision's rate.
#
# As of 2026-07-30 the next three decisions are Sep-16, Oct-28 and Dec-09, and
# the "FOMC 1/2/3 fly" is built on **ZQV26 / ZQX26 / ZQF27** — October, November
# and January-27. **December is skipped.** It splits 22/31 at the post-December
# rate against 9/31 at the post-October rate and reads neither decision cleanly,
# and January reads December *better* than December does (27/31 against 22/31).
#
# That makes the meeting fly a different object from the calendar fly, and the
# difference is measurable in the only units that matter — how much of a decision
# the package carries:
#
# | | loading on the Dec-09 decision |
# |---|---:|
# | meeting fly `2·Nov − Oct − Jan` | **−1.00** |
# | calendar fly `2·Nov − Oct − Dec` | −0.71 |
#
# The calendar-consecutive version is a **diluted** version of the same trade.
# This is the same lever that made wider SR3 spacings better: more of the thing
# you want per unit of cost.

# %%
readers = Z.meeting_reader_map(lab)
_show = readers[(readers["meeting"] >= datetime.date(2026, 6, 1))
                & (readers["meeting"] <= datetime.date(2027, 6, 30))]
print("MEETING -> READER CONTRACT")
print(_show.to_string(index=False))

_asof = datetime.date(2026, 7, 30)
_nxt = [m for m in lab["meetings"] if m > _asof][:3]
_got = ["ZQ" + readers.set_index("meeting").loc[m, "reader"] for m in _nxt]
print(f"\n  as of {_asof}, the next three decisions are {[str(d) for d in _nxt]}")
print(f"  the FOMC 1/2/3 fly is {' / '.join(_got)}")
print(f"  matches the desk convention ZQV26/ZQX26/ZQF27: "
      f"{_got == ['ZQV26', 'ZQX26', 'ZQF27']}")
_span = [k for k in lab["codes"]
         if datetime.date(2026, 10, 1) <= lab["windows"][k][0] <= datetime.date(2027, 1, 1)]
print(f"  months in that span reading no meeting cleanly: "
      f"{[c for c in _span if 'ZQ' + c not in _got]}")
print(f"\n  {len(readers)} readable transitions -> {readers['reader'].nunique()} distinct readers "
      f"({int(readers['reader'].duplicated().sum())} shared)")
print(f"  cleanliness of the read: min {readers['day_share'].min():.3f}, "
      f"median {readers['day_share'].median():.3f}")
print(f"  least clean: "
      f"{readers.nsmallest(3, 'day_share')[['meeting', 'reader_month', 'day_share']].to_dict('records')}")
print("""
  Every decision in this sample gets its OWN contract, and the worst read is
  still 73% of a month. That is not guaranteed a priori -- a ~6-week regime
  window need not contain a whole calendar month -- so the builder collapses
  consecutive duplicate readers as a guard. It never fires here, because no
  calendar month in 2018-2027 contains two decisions.""")

# %%
m_spread = Z.zq_meeting_structures(lab, n_legs=2)
m_fly = Z.zq_meeting_structures(lab, n_legs=3)
rows = []
for nm, st in (("calendar spread", spread), ("MEETING spread", m_spread),
               ("calendar fly", fly), ("MEETING fly", m_fly)):
    lv = st["levels"]
    d = lv.diff().stack()
    p = Z.move_profile(lv, None, horizons=(21,),
                       round_trip_bp=st["cost_bp"]).iloc[0]
    rows.append({"structure": nm, "n_keys": lv.shape[1], "cost_bp": st["cost_bp"],
                 "diff_exposure_median": float(st["diff_exposure"].median()),
                 "sd_bp": float(lv.stack().std()),
                 "sd_ticks": float(lv.stack().std() / ZQ_TICK_BP),
                 "pct_unchanged": float((d.abs() < 1e-9).mean()),
                 "absmove_h21": p["mean_abs_bp"],
                 "oracle_net_h21": p["oracle_net_bp"],
                 "p_beat_cost": p["p_beat_cost"]})
mix = pd.DataFrame(rows)
print("CALENDAR-INDEXED vs MEETING-INDEXED (same costs, same engine)")
print(mix.round(3).to_string(index=False))
mix.to_csv(Z.DATA_DIR / "meeting_vs_calendar.csv", index=False)
print(f"""
  Indexing by meeting is strictly better on every axis, because it stops
  spending legs on months that read nothing:

    spread   differential exposure {mix.loc[0, 'diff_exposure_median']:.2f} -> {mix.loc[1, 'diff_exposure_median']:.2f},  sd {mix.loc[0, 'sd_bp']:.2f} -> {mix.loc[1, 'sd_bp']:.2f}bp,
             oracle {mix.loc[0, 'oracle_net_h21']:+.2f} -> {mix.loc[1, 'oracle_net_h21']:+.2f}bp
    fly      differential exposure {mix.loc[2, 'diff_exposure_median']:.2f} -> {mix.loc[3, 'diff_exposure_median']:.2f},  sd {mix.loc[2, 'sd_bp']:.2f} -> {mix.loc[3, 'sd_bp']:.2f}bp,
             oracle {mix.loc[2, 'oracle_net_h21']:+.2f} -> {mix.loc[3, 'oracle_net_h21']:+.2f}bp

  The FF FLY crosses zero on this switch: a calendar-consecutive fly cannot pay
  its round trip even with perfect foresight, and a meeting-indexed one can --
  barely. That is the correction this section exists to make.""")

# %% [markdown]
# ## 4. The FF kink, and the saturation trap
#
# ZQ settles on *exactly* a day-weighted blend of policy regimes, so the
# meeting-exposure model is not an approximation of the contract — it is the
# contract. Solving the strip for per-meeting jumps and taking the residual is
# therefore the sharpest possible definition of "the part of the price that
# policy expectations cannot explain".
#
# **But the residual is only meaningful if the fit is constrained.** The strip
# carries 12 contracts against 8–9 identifiable meetings plus an intercept, so a
# free fit has 2–4 degrees of freedom and tracks the strip almost exactly; the
# resulting "kink" is a statement about the model's flexibility, not about the
# market. The jump path is therefore penalised on its **second difference** — the
# same construction as the SR3 kink lab, so a linearly accelerating policy path
# is fitted for free — and `lam` is swept from saturated to maximally stiff.

# %%
resid_by_lam, rows = {}, []
for lam in CONFIG["lam_sweep"]:
    r = Z.meeting_residual_panel_zq(lab, lam=lam)
    resid_by_lam[lam] = r
    row = {"lam": lam, "resid_sd_bp": float(r.stack().std()),
           "resid_sd_ticks": float(r.stack().std() / ZQ_TICK_BP)}
    for nm, st in (("spread", spread), ("fly", fly),
                   ("m_spread", m_spread), ("m_fly", m_fly)):
        w = st["weights"]
        lv = {}
        for key in st["levels"].columns:
            legs = key.split("-")
            if any(l not in r.columns for l in legs):
                continue
            lv[key] = sum(x * r[l] for x, l in zip(w, legs))
        lv = pd.DataFrame(lv).where(st["gate"].reindex(columns=list(lv)))
        p = Z.move_profile(lv, None, horizons=(21,),
                           round_trip_bp=st["cost_bp"]).iloc[0]
        row[f"{nm}_sd_bp"] = float(lv.stack().std())
        row[f"{nm}_absmove_h21"] = p["mean_abs_bp"]
        row[f"{nm}_oracle_h21"] = p["oracle_net_bp"]
        row[f"{nm}_pbeat"] = p["p_beat_cost"]
    rows.append(row)
    print(f"  lam={lam:<9g} residual {row['resid_sd_bp']:6.3f}bp "
          f"({row['resid_sd_ticks']:5.2f}t)  calendar spread {row['spread_oracle_h21']:+6.3f}"
          f"  MEETING spread {row['m_spread_oracle_h21']:+6.3f}"
          f"  calendar fly {row['fly_oracle_h21']:+6.3f}"
          f"  MEETING fly {row['m_fly_oracle_h21']:+6.3f}", flush=True)
sweep = pd.DataFrame(rows)
sweep.to_csv(Z.DATA_DIR / "residual_lambda_sweep.csv", index=False)
print()
print(sweep.round(3).to_string(index=False))

# %%
stiff = sweep.iloc[-1]
# The denominator has to be the TRADEABLE object. Comparing the residual to the
# pooled contract-RATE sd would flatter the model absurdly: that sd is dominated
# by the policy rate itself travelling 0 to 5.5% over the sample, and any model
# with a fitted intercept "explains" that. The spread's own dispersion is the
# thing a spread trader is trying to capture, so that is what it is measured
# against.
raw_spread_sd = float(spread["levels"].stack().std())
raw_fly_sd = float(fly["levels"].stack().std())
exp_sp = 100 * (1 - (stiff["spread_sd_bp"] / raw_spread_sd) ** 2)
exp_fl = 100 * (1 - (stiff["fly_sd_bp"] / raw_fly_sd) ** 2)
print(f"""
THE SECOND AND DECISIVE DECISION POINT

  residual sd, saturated (lam=0)        {sweep.iloc[0]['resid_sd_bp']:8.3f} bp  ({sweep.iloc[0]['resid_sd_ticks']:.2f} ticks)
  residual sd, stiffest (lam=1e5)       {stiff['resid_sd_bp']:8.3f} bp  ({stiff['resid_sd_ticks']:.2f} ticks)

  measured against the TRADEABLE structure, at the stiffest setting -- i.e. with
  the policy path forced onto a straight line in meeting index, the least
  flattering configuration available:

     M1-M2 spread   raw sd {raw_spread_sd:6.2f}bp -> residual {stiff['spread_sd_bp']:5.2f}bp   model explains {exp_sp:5.1f}%
     3-month fly    raw sd {raw_fly_sd:6.2f}bp -> residual {stiff['fly_sd_bp']:5.2f}bp   model explains {exp_fl:5.1f}%

  BEST ORACLE ACROSS THE ENTIRE SWEEP, net of the round trip:
     calendar spread  {sweep['spread_oracle_h21'].max():+.3f} bp   (cost {spread['cost_bp']}bp)
     MEETING  spread  {sweep['m_spread_oracle_h21'].max():+.3f} bp   (cost {m_spread['cost_bp']}bp)
     calendar fly     {sweep['fly_oracle_h21'].max():+.3f} bp   (cost {fly['cost_bp']}bp)
     MEETING  fly     {sweep['m_fly_oracle_h21'].max():+.3f} bp   (cost {m_fly['cost_bp']}bp)

  Indexing by meeting is worth a factor of {sweep['m_spread_oracle_h21'].max() / max(sweep['spread_oracle_h21'].max(), 1e-9):.1f} on the spread, and it is the
  right structure -- but the best number on the board is still {sweep['m_spread_oracle_h21'].max():+.2f}bp per trade
  WITH PERFECT FORESIGHT OF THE DIRECTION.

  Translate it into what a signal would have to do. The meeting-residual spread
  moves {sweep.set_index('lam').loc[1e5, 'm_spread_absmove_h21']:.2f}bp on average over 21 days against a {m_spread['cost_bp']}bp round trip, and a
  rule right p of the time nets (2p-1) x move - cost. Break-even needs

      p > (1 + {m_spread['cost_bp']}/{sweep.set_index('lam').loc[1e5, 'm_spread_absmove_h21']:.2f}) / 2 = {(1 + m_spread['cost_bp'] / sweep.set_index('lam').loc[1e5, 'm_spread_absmove_h21']) / 2:.1%} of trades called correctly.

  For scale, the SR3 12m fly needed 57%. This is the STOP the brief anticipated,
  and the meeting-indexed correction moves it from hopeless to merely
  unreachable.""")

# %%
fig, axes = plt.subplots(1, 3, figsize=(16, 3.9))
axes[0].semilogx(sweep["lam"].replace(0, 1e-2), sweep["resid_sd_ticks"], "o-",
                 color="#1f4e79")
axes[0].axhline(1.0, color="grey", ls="--", lw=0.9)
axes[0].set_xlabel("lambda (2nd-difference penalty)")
axes[0].set_ylabel("residual sd, ZQ ticks")
axes[0].set_title("the FF kink is sub-tick to a few ticks", fontsize=10)
for nm, st, c in (("spread", spread, "#2e7d32"), ("fly", fly, "#c62828")):
    axes[1].semilogx(sweep["lam"].replace(0, 1e-2), sweep[f"{nm}_oracle_h21"],
                     "o-", color=c, label=f"{nm} (cost {st['cost_bp']}bp)")
axes[1].axhline(0, color="black", lw=1.0)
axes[1].set_xlabel("lambda")
axes[1].set_ylabel("oracle net bp per trade, h=21")
axes[1].set_title("perfect direction-calling, net of cost", fontsize=10)
axes[1].legend(fontsize=8)
r100 = resid_by_lam[CONFIG["lam"]]
hl = pd.Series({c: half_life(r100[c].dropna()) for c in r100.columns}).dropna()
axes[2].hist(hl[hl.between(0, 250)], bins=30, color="#6a51a3", alpha=0.8)
axes[2].set_xlabel("fitted half-life (days)")
axes[2].set_title(f"residual half-life, median {hl.median():.0f}d", fontsize=10)
for a in axes:
    a.tick_params(labelsize=8)
fig.tight_layout()
plt.show()
_s100 = sweep.set_index("lam").loc[100.0]
print(f"median fitted half-life of the per-contract residual: {hl.median():.1f} days")
print(f"  share above 60 days: {100 * float((hl > 60).mean()):.0f}%")
print(f"""
  THE FAILURE IS NOT PERSISTENCE. A half-life of {hl.median():.0f} days is FAST mean
  reversion -- faster than the SR3 butterflies, whose tradeable slots fitted
  28-53 days. The FF kink does exactly what the thesis says it should: it
  reverts, and quickly.

  It still cannot be traded, because the whole oscillation is a few ticks wide.
  At lam=100 the residual spread's sd is {_s100['spread_sd_bp']:.2f}bp and its mean 21-day move is
  {_s100['spread_absmove_h21']:.2f}bp -- against a {spread['cost_bp']}bp round trip. Only {100 * _s100['spread_pbeat']:.0f}% of entries move
  further than the cost of taking them.

  That is a different failure mode from SR3's and worth naming. SR3's problem
  was that the fly barely reverted at all relative to its cost. FF's problem is
  that it reverts beautifully inside a band narrower than the bid-ask.""")

# %% [markdown]
# ## 5. The implied-jump view — the same result in a trader's units
#
# A spread's differential exposure `dW` is how much of one decision it carries,
# so `jump = spread / dW` is that pair's own read on the meeting in **bp of
# policy move**. Two pairs straddling the same meeting should agree, and the
# amount by which they disagree *is* the kink — stated in the units a desk
# thinks in rather than in bp of spread.

# %%
ij = Z.implied_jump_panel(lab, spread, min_exposure=0.15)
jump = ij["jump"]
print(f"implied-jump panel: {jump.shape[1]} pairs kept, {len(ij['dropped'])} dropped "
      f"for carrying < 0.15 of a meeting")
print(f"  (dividing a one-tick spread by a 0.02 exposure manufactures a 25bp")
print(f"   'implied jump' out of noise, which is why the floor exists)")
print(f"\n  pooled implied jump: median {jump.stack().median():+.2f}bp, "
      f"sd {jump.stack().std():.2f}bp")
cost_in_jump = spread["cost_bp"] / spread["diff_exposure"][ij["kept"]].median()
print(f"  round trip expressed in JUMP units: {spread['cost_bp']}bp / "
      f"{spread['diff_exposure'][ij['kept']].median():.2f} = {cost_in_jump:.2f}bp of jump")
jm = Z.move_profile(jump, None, horizons=CONFIG["horizons"],
                    round_trip_bp=cost_in_jump)
print("\nORACLE IN JUMP UNITS (does the market's read on a meeting converge?)")
print(jm.round(3).to_string(index=False))
jump.stack().describe().to_frame().T.to_csv(Z.DATA_DIR / "implied_jump_summary.csv")

# %% [markdown]
# ## 6. Curve cross-check — can the ZQ strip be recovered from MIX23?
#
# The brief asked for a golden test against the curve. It is a **diagnostic**,
# not a mark: the house rule is that a futures package is marked on settles,
# because a curve is a smoothed model of those settles and a backtest run on one
# trades its own interpolation error.
#
# Measured in `notebooks/rv/_probe_zq_curve.py` at 2026-07-10 against the
# 12 front pre-accrual contracts, comparing the curve-implied strip with the
# actual ZQ settles. Reproduced here from that run rather than rebuilding the
# curve inside the notebook.

# %%
golden = pd.DataFrame({
    "timestamp": ["15:40 ET", "17:00 ET (matches the settle)"],
    "mean_gap_bp": [-0.866, -0.097],
    "median_abs_gap_bp": [1.167, 0.851],
    "max_abs_gap_bp": [2.063, 1.634],
    "n_contracts": [12, 12]})
print("MIX23 curve-implied ZQ vs the actual settle (usd_stir1, averaged spec)")
print(golden.round(3).to_string(index=False))
print(f"""
  Read it as three findings.

  1. The spec matters and the repo has a trap. `usd_stir1` is the monthly
     ARITHMETIC-AVERAGE spec; `usd_stir` is quarterly and COMPOUNDED. The
     repo's `is_ser` predicates key off `root in {{SR1, SER, SL}}` and ZQ is not
     in that set, so a ZQ routed through them silently selects the quarterly
     compounded contract. On this path rateslib refuses to build the schedule
     at all, which is lucky rather than by design.

  2. The date convention does NOT matter here. Building with the exact calendar
     month and with `contract_grid`'s business-day window gave IDENTICAL rates
     to 1e-9 -- the `roll: som` / `mf` spec normalises them to the same
     schedule.

  3. MIX23 carries real EFFR information but is not calibrated to ZQ. At the
     17:00 snapshot the bias is -0.10bp -- essentially nil -- but the dispersion
     is 0.85bp median absolute, {0.851 / ZQ_TICK_BP:.1f} ZQ ticks. That FAILS the brief's
     0.5bp tie-out. For contrast, the same machinery on the SOFR curve gaps by
     +3.2bp mean, which is the SOFR-FF basis, so MIX23 is genuinely EFFR-aware
     -- it is just noisier than the object a kink definition is trying to
     isolate. Curve for diagnostics, settles for marks.""")
golden.to_csv(Z.DATA_DIR / "curve_golden_test.csv", index=False)

# %% [markdown]
# ## 7. The one structure with headroom, run properly
#
# The oracle says the FF kink is dead and the FF butterfly is deader. One thing
# is left: the **raw** M1-M2 spread in the high-differential-exposure bucket,
# whose oracle clears its round trip by ~1.5bp at 21 days. That is a directional
# read on a policy decision rather than a kink fade, but it is the only FF
# structure that could pay and it gets the full house treatment so its league
# rows sit next to SR3's.

# %%
BASE_SP = MRConfig(lag=CONFIG["lag"], round_trip_cost_bp=spread["cost_bp"],
                   max_hold=CONFIG["max_hold"], n_packages=CONFIG["n_packages"])
GRID = {"window": CONFIG["windows"], "entry_z": CONFIG["entry_zs"],
        "exit_style": CONFIG["exits"], "direction": CONFIG["directions"]}
PARAMS = ["window", "entry_z", "exit_style", "direction"]

de = spread["diff_exposure"]
hi_keys = list(de.index[de >= CONFIG["high_exposure_cut"]])
hi = dict(spread)
hi["levels"] = spread["levels"][hi_keys]
hi["gate"] = spread["gate"][hi_keys]
hi["diff_exposure"] = de[hi_keys]
print(f"high-exposure spreads: {len(hi_keys)} of {spread['levels'].shape[1]} keys "
      f"(differential exposure >= {CONFIG['high_exposure_cut']})")

Z.set_taker(spread["cost_bp"])


def f_raw(L, window):
    return zscore_signal(L, window=window)


out_raw = Z.zq_run_family("F1. raw M1-M2 spread z-score (high exposure)",
                          lab=lab, struct=hi, signal_fn=f_raw, grid_spec=GRID,
                          params=PARAMS, base=BASE_SP, cls="ff-spread",
                          note="the only FF structure whose oracle clears cost")

# %% [markdown]
# ## 8. The FF kink itself, for the record

# %%
R = resid_by_lam[CONFIG["lam"]]


def f_kink(L, window):
    lv = {}
    for key in L.columns:
        legs = key.split("-")
        if any(l not in R.columns for l in legs):
            continue
        lv[key] = -1.0 * R[legs[0]] + 1.0 * R[legs[1]]
    r = pd.DataFrame(lv).reindex(index=L.index, columns=L.columns)
    return scale_only_zscore(r, window=window)


out_kink = Z.zq_run_family(f"F2. FF kink -- meeting residual spread (lam={CONFIG['lam']:.0f})",
                           lab=lab, struct=hi, signal_fn=f_kink, grid_spec=GRID,
                           params=PARAMS, base=BASE_SP, cls="ff-kink",
                           note="the thesis: fade the residual from the "
                                "meeting-step model")

# %%
BASE_FL = MRConfig(lag=CONFIG["lag"], round_trip_cost_bp=fly["cost_bp"],
                   max_hold=CONFIG["max_hold"], n_packages=CONFIG["n_packages"])
Z.set_taker(fly["cost_bp"])


def f_kink_fly(L, window):
    lv = {}
    for key in L.columns:
        legs = key.split("-")
        if any(l not in R.columns for l in legs):
            continue
        lv[key] = -1.0 * R[legs[0]] + 2.0 * R[legs[1]] - 1.0 * R[legs[2]]
    r = pd.DataFrame(lv).reindex(index=L.index, columns=L.columns)
    return scale_only_zscore(r, window=window)


out_kink_fly = Z.zq_run_family("F3. FF kink -- meeting residual fly", lab=lab,
                               struct=fly, signal_fn=f_kink_fly, grid_spec=GRID,
                               params=PARAMS, base=BASE_FL, cls="ff-kink",
                               note="4 contracts, 2.0bp round trip")


# %% [markdown]
# ## 8b. The meeting-indexed families
#
# The structures a desk would actually put on, run through the same machinery so
# their league rows sit beside everything else.

# %%
Z.set_taker(m_spread["cost_bp"])
BASE_MS = MRConfig(lag=CONFIG["lag"], round_trip_cost_bp=m_spread["cost_bp"],
                   max_hold=CONFIG["max_hold"], n_packages=CONFIG["n_packages"])

out_m_raw = Z.zq_run_family("F4. raw MEETING spread z-score", lab=lab,
                            struct=m_spread, signal_fn=f_raw, grid_spec=GRID,
                            params=PARAMS, base=BASE_MS, cls="ff-meeting",
                            note="consecutive meeting readers, not consecutive months")

# %%
def f_kink_m(L, window):
    lv = {}
    for key in L.columns:
        legs = key.split("-")
        if any(l not in R.columns for l in legs):
            continue
        lv[key] = -1.0 * R[legs[0]] + 1.0 * R[legs[1]]
    r = pd.DataFrame(lv).reindex(index=L.index, columns=L.columns)
    return scale_only_zscore(r, window=window)


out_m_kink = Z.zq_run_family("F5. MEETING kink -- residual spread", lab=lab,
                             struct=m_spread, signal_fn=f_kink_m, grid_spec=GRID,
                             params=PARAMS, base=BASE_MS, cls="ff-meeting-kink",
                             note="the thesis, on the right structure")

# %%
Z.set_taker(m_fly["cost_bp"])
BASE_MF = MRConfig(lag=CONFIG["lag"], round_trip_cost_bp=m_fly["cost_bp"],
                   max_hold=CONFIG["max_hold"], n_packages=CONFIG["n_packages"])


def f_kink_m_fly(L, window):
    lv = {}
    for key in L.columns:
        legs = key.split("-")
        if any(l not in R.columns for l in legs):
            continue
        lv[key] = -1.0 * R[legs[0]] + 2.0 * R[legs[1]] - 1.0 * R[legs[2]]
    r = pd.DataFrame(lv).reindex(index=L.index, columns=L.columns)
    return scale_only_zscore(r, window=window)


out_m_kink_fly = Z.zq_run_family("F6. MEETING kink -- residual fly (the FOMC 1/2/3)",
                                 lab=lab, struct=m_fly, signal_fn=f_kink_m_fly,
                                 grid_spec=GRID, params=PARAMS, base=BASE_MF,
                                 cls="ff-meeting-kink",
                                 note="2*FOMC2 - FOMC1 - FOMC3 on the reader contracts")

# %% [markdown]
# ## 9. Verdict

# %%
league = pd.read_csv(Z.DATA_DIR / "league_table.csv")
show = ["framework", "variant", "structure", "n_trades", "hit_rate", "avg_net_bp",
        "total_gross_bp", "total_net_bp", "net_bp_maker", "net_bp_taker",
        "taker_bp", "grid_median_net_bp", "dsr_prob", "nonoverlap_sharpe",
        "verdict"]
print(f"ZQ LEAGUE TABLE — {len(league)} rows\n")
print(league.sort_values("total_net_bp", ascending=False)[
    [c for c in show if c in league.columns]].round(3).to_string(index=False))
league.sort_values("total_net_bp", ascending=False).to_csv(
    Z.DATA_DIR / "league_table_sorted.csv", index=False)
print("\nverdict distribution:")
print(league["verdict"].value_counts().to_string())
n = len(league)
print(f"""
  rows net positive GROSS            {int((league['total_gross_bp'] > 0).sum())} / {n}
  rows net positive at taker         {int((league['net_bp_taker'] > 0).sum())} / {n}
  rows with a positive GRID MEDIAN   {int((league['grid_median_net_bp'] > 0).sum())} / {n}
  median DSR probability             {league['dsr_prob'].median():.4f}
  ALIVE                              {int((league['verdict'] == 'ALIVE').sum())}""")

# %%
signs = pd.read_csv(Z.DATA_DIR / "sign_tests.csv")
w = signs.pivot_table(index="framework", columns="direction",
                      values="median_net_bp", aggfunc="first")
w["fade_wins"] = w.get("fade", np.nan) > w.get("momentum", np.nan)
print("SIGN TEST (median net bp of the whole sweep)")
print(w.round(1).to_string())

sh = pd.read_csv(Z.DATA_DIR / "zq_shadow_tests.csv")
print("\nLINEAR-SHADOW DECOMPOSITION — does an outright leg beat the package?")
piv = sh.pivot_table(index="framework", columns="instrument",
                     values="total_net_bp", aggfunc="first")
print(piv.round(1).to_string())
beat = sh[sh["instrument"] != "package"].groupby("framework")["beats_package"].any()
print(f"\n  an outright leg beats the package in {int(beat.sum())} of {len(beat)} frameworks")

# %%
reg = pd.read_csv(Z.DATA_DIR / "regime_splits.csv")
print("REGIME SPLIT summed across frameworks' best configs")
print(reg.groupby("regime").agg(total_net_bp=("total_net_bp", "sum"),
                                n_trades=("n_trades", "sum"),
                                frameworks_positive=("total_net_bp",
                                                     lambda s: int((s > 0).sum())),
                                n=("total_net_bp", "size"))
      .reindex(Z.REGIME_ORDER).dropna(how="all").round(1).to_string())

# %%
best_row = league.loc[league["total_net_bp"].idxmax()]
print("=" * 94)
print("WHAT THIS NOTEBOOK MEASURED")
print("=" * 94)
print(f"""
1. THE FF SETTLEMENT MODEL IS EXACT, AND THAT IS THE PROBLEM.
   ZQ settles on the arithmetic average of daily EFFR over one calendar month,
   so a day-weighted blend of policy regimes is not an approximation of the
   contract -- it IS the contract. Solving the strip for per-meeting jumps and
   forcing the policy path onto a straight line -- the least flattering setting
   available -- still explains {exp_sp:.0f}% of the M1-M2 spread's variance and {exp_fl:.0f}% of
   the fly's, leaving residuals of {stiff['spread_sd_bp']:.2f}bp and {stiff['fly_sd_bp']:.2f}bp against round trips of
   {spread['cost_bp']}bp and {fly['cost_bp']}bp.

2. INDEX BY MEETING, NOT BY MONTH -- IT IS WORTH A FACTOR OF {sweep['m_spread_oracle_h21'].max() / max(sweep['spread_oracle_h21'].max(), 1e-9):.0f}.
   A desk's FOMC 1/2/3 fly skips the blended month: as of 2026-07-30 it is
   ZQV26/ZQX26/ZQF27, and December is not in it. That loads the December
   decision at -1.00 against the calendar fly's -0.71, and the difference shows
   up everywhere -- spread sd {mix.loc[0, 'sd_bp']:.1f} -> {mix.loc[1, 'sd_bp']:.1f}bp, fly sd {mix.loc[2, 'sd_bp']:.1f} -> {mix.loc[3, 'sd_bp']:.1f}bp, and the raw fly's
   oracle crossing zero ({mix.loc[2, 'oracle_net_h21']:+.2f} -> {mix.loc[3, 'oracle_net_h21']:+.2f}bp).

3. THE ORACLE CEILING STILL SAYS STOP.
   Across the whole penalty sweep -- every kink definition between "fit every
   jump" and "the Fed is a metronome" -- the best oracle net of cost is
   {sweep['m_spread_oracle_h21'].max():+.3f}bp, on the MEETING spread. A rule would have to call the
   direction right {(1 + m_spread['cost_bp'] / sweep.set_index('lam').loc[1e5, 'm_spread_absmove_h21']) / 2:.0%} of the time to break even; the SR3 12m fly needed 57%.

4. THE KINK REVERTS -- AND IT DOES NOT HELP.
   Median fitted half-life of the per-contract residual is {hl.median():.0f} days, FASTER
   than the 28-53 days the SR3 lab fitted on its tradeable slots. The FF kink
   does what the thesis says it should. It just does it inside a band narrower
   than the bid-ask: at lam=100 the residual spread's sd is {_s100['spread_sd_bp']:.2f}bp, its mean
   21-day move {_s100['spread_absmove_h21']:.2f}bp, and only {100 * _s100['spread_pbeat']:.0f}% of entries move further than the
   {spread['cost_bp']}bp it costs to take them.

5. NOTHING IS STRUCTURALLY PINNED, WHICH IS ALSO NOT WHAT WAS EXPECTED.
   Every adjacent ZQ pair carries 0.13 to 1.00 of a policy decision. The
   "adjacent no-meeting months are degenerate" intuition is false, because a
   meeting inside EITHER month splits the pair.

6. VERDICT: {int((league['verdict'] == 'ALIVE').sum())} of {n} league rows ALIVE, {int((league['grid_median_net_bp'] > 0).sum())} with a positive grid median.
   Best row {best_row['framework']} / {best_row['variant']}:
   {best_row['total_net_bp']:+.1f}bp net over {int(best_row['n_trades'])} trades, grid median {best_row['grid_median_net_bp']:+.1f}bp,
   DSR p = {best_row['dsr_prob']:.3f} -> {best_row['verdict']}.

ANSWER TO THE QUESTION THIS LAB WAS SET:
   The FF complex does NOT pay the kink-fade, and the coarse tick lattice is not
   what kills it -- the M1-M2 spread runs {raw_spread_sd / ZQ_TICK_BP:.0f} ticks of dispersion, which is
   plenty. What kills it is the opposite of a problem.

   ZQ's settlement is such a clean read on policy that a meeting-step model
   explains {exp_sp:.0f}% of the tradeable spread's variance even when the policy path
   is forced onto a straight line. The residual that survives is real -- {stiff['spread_sd_bp']:.2f}bp of
   level, reverting with a {hl.median():.0f}-day half-life -- but the amplitude a trader can
   actually harvest inside a month is {_s100['spread_absmove_h21']:.2f}bp against a {spread['cost_bp']}bp round trip, and
   only {100 * _s100['spread_pbeat']:.0f}% of entries clear it. The kink is there; the room is not.

   So the property that made Fed Funds the natural habitat for this thesis is
   exactly the property that removes the trade. SR3's compounded quarterly
   window is a MESSY read on policy, and that mess is where a butterfly's
   dispersion comes from. Cleanliness and opportunity turn out to be the same
   axis, pointing opposite ways -- which is why the SR3 lab's own best lead was
   the 12m fly, the messiest structure it could build.
""")
print(f"total runtime {time.time() - T0:.0f}s")
