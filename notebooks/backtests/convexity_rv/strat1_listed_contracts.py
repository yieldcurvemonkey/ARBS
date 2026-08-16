# %% [markdown]
# # Strategy 1-listed on **real listed contracts** — `USM26`, not `US_30`
#
# **What changed, and why it is not a refinement.** The long-end listed study
# benchmarked the curve against QuikStrike **constant-maturity** UST vol
# (`US_30`, `TY_90`). That series is an *interpolation across the expiry ladder*.
# It is not tradeable, it has no strike dimension and it has no expiry, so it
# cannot support two of the three things J.P. Morgan's note actually does:
#
# > "we initiate a flattener and sell 1Yx30Y ATMF swaption straddles to fund the
# >  carry on the position (i.e., sized such that the initiate premium intake is
# >  equal to the carry over the same 1-year horizon)"
#
# — which needs a **contract with a real expiry and a real premium** — and the
# note's second signal, the expected payoff under the market's own implied
# distribution, which needs **OTM quotes**.
#
# `scripts/harvest_listed_contract_vol.py` harvested the contracts themselves:
# **196,560 rows, 228 contracts, 1,368 series, 2019-01-02 .. 2026-08-14**. This
# notebook rebuilds strategy-1-listed on them.
#
# ---
#
# ## The constant-maturity panel is kept as a **control**, not replaced
#
# Every headline here is produced twice — once against the real contract, once
# against `US_30` on **bit-identical curve rows** — because the difference
# between them *is* a finding. It measures what constant-maturity interpolation
# was doing to the answer, which is the direct answer to "why bother with real
# contracts". §7 is that comparison.
#
# ## Three things a real contract buys, and what each actually delivered
#
# | | what it buys | measured here |
# |---|---|---|
# | §4 | **expiry matching** — pick the contract nearest the curve's own horizon | the ladder gets to **124 days** of a 365-day horizon at best, **232 days** at the median. CM is 335 days short, always. Real contracts *halve* the mismatch; they do not remove it. |
# | §5 | **roll effects** — a real contract ages and rolls | **47 rolls** over 1,901 days (~40-day holds); the benchmark jumps **2.74x** its ordinary daily move on a roll day, and flips the signal on **0** of them. |
# | §6 | **a funded straddle** — premium intake == carry | sized in **contracts**: median **57 contracts** on 5Y/30Y, ~8.6% of the package DV01. And on 30Y/50Y the flattener **carries positively on 86% of days**, so there is nothing to fund at all. |
#
# ## What this notebook does NOT do
#
# * **No engine run, no network.** Everything is a pure function of three stored
#   parquets. The curve side is *reused* from `strat1_signal_panel.parquet`, never
#   recomputed, so this study and strategy 1's differ in exactly one column.
# * **No claim of sector perfection.** `listed_vol.UST_SECTOR_MAP`'s primary
#   benchmark for 30Y/50Y and 20Yx5Y/25Yx5Y is the **Ultra Bond (UL)**, and
#   **UL and TN are not reachable as listed contracts at all** — `ULM26` returns
#   *"Invalid UST option contract token"*. §2 states that and §7 measures what it
#   costs.

# %%
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import dataclasses
import datetime
import json
import math
import pathlib
import sys
import warnings
from dataclasses import dataclass
from typing import Tuple

import numpy as np
import pandas as pd

_REPO = (pathlib.Path(__file__).resolve().parents[3] if "__file__" in dir()
         else pathlib.Path.cwd().parents[2])
sys.path.insert(0, str(_REPO))

import plotly.graph_objects as go
import plotly.io as pio
from plotly.subplots import make_subplots

pio.renderers.default = "plotly_mimetype+notebook_connected"

from RVUtils.ConvexityRV import listed_contracts as lc
from RVUtils.ConvexityRV import listed_vol as lv
from RVUtils.ConvexityRV import strat1_listed as sl
from RVUtils.ConvexityRV import strat1_real_contracts as rc

warnings.filterwarnings("ignore", category=RuntimeWarning)

DATA = _REPO / "notebooks" / "data" / "convexity_rv"
pd.set_option("display.width", 240)
pd.set_option("display.max_columns", 80)
print("repo          ", _REPO)
print("artifacts     ", DATA)
print("real contracts", lc.default_listed_contract_path())
print("CM control    ", lv.default_ust_cm_path())

# %% [markdown]
# ## 1. CONFIG — every knob, documented at the point of use
#
# The strategy knobs live in `rc.RealContractConfig`; this dataclass holds only
# the notebook's own wiring. Nothing here is tuned on an outcome, and the
# headline benchmark (`US@H365`) is fixed in the **module**, not chosen here
# after seeing eight answers.

# %%
@dataclass(frozen=True)
class NBConfig:
    """Notebook wiring. Strategy knobs are in :class:`rc.RealContractConfig`."""

    #: Artifacts written by ``_strat1_contracts_build.py``. This notebook is a
    #: report over them, not a second implementation of the study.
    panel: str = "strat1_contracts_panel.parquet"
    cm_control: str = "strat1_contracts_cm_control.parquet"
    selection: str = "strat1_contracts_selection.csv"
    roll: str = "strat1_contracts_roll.csv"
    ageing: str = "strat1_contracts_ageing.csv"
    cm_vs_real: str = "strat1_contracts_cm_vs_real.csv"
    straddle: str = "strat1_contracts_straddle.parquet"
    straddle_summary: str = "strat1_contracts_straddle_summary.csv"
    smile: str = "strat1_contracts_smile.parquet"
    expected_payoff: str = "strat1_contracts_expected_payoff.parquet"
    verdict: str = "strat1_contracts_verdict.json"

    #: The PRE-SPECIFIED headline benchmark and its constant-maturity control.
    #: Same ROOT on both sides, so §7 isolates "real contract vs interpolation"
    #: rather than confounding it with "US vs UL".
    headline: str = f"{rc.HEADLINE_ROOT}@{rc.HEADLINE_TARGET}"
    cm_headline: str = f"{rc.HEADLINE_ROOT}_30"
    #: Structure the plots zoom into. 5Y/30Y because it is the only one of the
    #: four whose cheap/rich verdict is not saturated, i.e. the only one on which
    #: the choice of benchmark can change anything.
    focus: str = "5Y/30Y"
    #: Date the ladder snapshot is drawn on. Mid-sample, no other criterion.
    ladder_day: str = "2023-07-26"


NB = NBConfig()
CFG = rc.RealContractConfig()
print(json.dumps({k: str(v) for k, v in dataclasses.asdict(CFG).items()}, indent=1)[:1400])

# %% [markdown]
# ## 2. What is reachable as a real contract — and what is not
#
# This is the honesty section and it comes before any result. The sector map
# assigns each structure a primary benchmark by **measured CTD maturity**. For
# two of the four long-end structures that primary is the **Ultra Bond**, which
# has no listed option series in this vendor at all.
#
# So the real-contract study runs on **US** (the longest Treasury yield reachable
# as a contract, CTD ~15.9 years) and **TY** (CTD ~6.8 years, the deliberately
# wrong-sector control). On 30Y/50Y and 20Yx5Y/25Yx5Y, US is the sector map's
# *alt*, not its primary — and §7 measures what that substitution is worth.

# %%
notes = pd.DataFrame([rc.real_sector_note(l) for l, _f, _b in CFG.structures])
print(notes[["structure", "sector_primary", "sector_alt", "sector_control",
             "sector_matched", "best_available_real"]].to_string(index=False))
print()
for root, d in rc.UNAVAILABLE_REAL_ROOTS.items():
    print(f"{root} ({d['name']}, CTD {d['ctd_ttm_yrs']}y): {d['failure']}")
    print(f"     available as: {d['available_as']};  sector primary for "
          f"{d['sector_primary_for'] or '-'}")

assert set(rc.REAL_ROOTS) == {"US", "TY"}
assert not notes.loc[notes.structure == "30Y/50Y", "sector_matched"].iloc[0], (
    "30Y/50Y's sector primary is UL, which has no listed contract -- if this "
    "ever becomes True the sector limitation section is stale")
print("\nsector limitation: STATED, and quantified in section 7.")

# %% [markdown]
# ## 3. The panel — real contracts, and the CM control on identical curve rows

# %%
panel = pd.read_parquet(DATA / NB.panel)
cm_panel = pd.read_parquet(DATA / NB.cm_control)
contracts = lc.load_listed_contract_panel(roots=list(rc.REAL_ROOTS))
cm_raw = lv.load_ust_cm_panel()
for df in (panel, cm_panel):
    df["date"] = pd.to_datetime(df["date"])

print(f"real panel      {panel.shape}   benchmarks {sorted(set(panel.listed_symbol))}")
print(f"CM control      {cm_panel.shape}")
print(f"contract panel  {contracts.shape}  "
      f"{contracts.date.min().date()}..{contracts.date.max().date()}")
print()
print(pd.DataFrame(lc.contract_coverage_report(contracts)["per_root"]).T[
    ["n_contracts", "n_quarterly", "n_serial", "first_date", "last_date", "n_dates",
     "contracts_alive_per_date_median", "tte_years_max"]].to_string())

# ---- TIE-OUT: the curve side must be strategy 1's own, byte for byte ----------
s1 = pd.read_parquet(DATA / "strat1_signal_panel.parquet")
s1["date"] = pd.to_datetime(s1["date"])
j = panel.merge(s1, on=["date", "structure"], suffixes=("", "_s1"))
for c in ("breakeven_vol_bp_day", "carry_roll_bp", "atmf_vol_bp_day"):
    a, b = j[c].to_numpy(float), j[f"{c}_s1"].to_numpy(float)
    ok = np.isfinite(a) & np.isfinite(b)
    assert np.array_equal(a[ok], b[ok]), f"{c} was NOT reused verbatim"
    assert np.array_equal(np.isfinite(a), np.isfinite(b)), f"{c} finiteness differs"
print(f"\nTIE-OUT ok: {len(j):,} rows -- curve breakeven, carry and 1Yx30Y ATMF are "
      "strategy 1's own numbers, not re-derived.")

# ---- TIE-OUT: the two panels share their curve rows ---------------------------
k = panel[panel.listed_symbol == NB.headline][["date", "structure", "breakeven_vol_bp_day"]] \
    .merge(cm_panel[cm_panel.listed_symbol == NB.cm_headline][
        ["date", "structure", "breakeven_vol_bp_day"]], on=["date", "structure"],
        suffixes=("_r", "_c"))
a, b = k.breakeven_vol_bp_day_r.to_numpy(float), k.breakeven_vol_bp_day_c.to_numpy(float)
ok = np.isfinite(a) & np.isfinite(b)
assert np.array_equal(a[ok], b[ok])
print(f"TIE-OUT ok: {len(k):,} rows shared between the real run and the CM control, "
      "identical curve column -- the ONLY difference between them is the benchmark.")

# %% [markdown]
# ## 4. Expiry matching — what the ladder can actually reach
#
# **Item 1 of the brief.** Constant maturity answers "what is 30-day vol" by
# interpolating; a real contract answers "which tradeable thing is closest to my
# horizon" and then has to admit how close that was.
#
# Read `median_gap_days` against `cm_gap_days`. The curve breakeven is a
# **one-year** number and the longest-dated listed UST option in the entire
# sample expires in **241 days**, so the best possible match is **124 days short**
# and the median is **232 days short**. The constant-maturity control is 335 days
# short by construction, every single day.
#
# `frac_selected_is_longest` is measured against the *full* ladder, not asserted:
# at the 365-day target it comes back **1.000**, because the target is beyond
# every listed expiry and "nearest" degenerates to "longest". That degeneracy is
# real and is why the row is here.

# %%
sel = pd.read_csv(DATA / NB.selection)
print(sel[["listed_symbol", "n_days", "median_tte_days", "max_tte_days",
           "median_gap_days", "best_gap_days", "cm_control_days", "cm_gap_days",
           "gap_improvement_days", "frac_selected_is_longest", "n_contracts",
           "median_hold_days", "frac_quarterly"]].to_string(index=False))

h = sel.set_index("listed_symbol").loc[NB.headline]
assert h["best_gap_days"] < 0 and h["median_gap_days"] < 0, (
    "every listed expiry must fall BEFORE the one-year horizon")
assert h["frac_selected_is_longest"] == 1.0
assert abs(h["gap_improvement_days"]) > 100
print(f"\n{NB.headline}: median gap {h['median_gap_days']:+.0f} d against the "
      f"{int(h['cm_control_days'])}-day CM control's constant {h['cm_gap_days']:+.0f} d -- "
      f"{h['gap_improvement_days']:.0f} days CLOSER to the horizon, and still "
      f"{abs(h['best_gap_days']):.0f} days short at the very best. "
      "(There is no 365-day constant-maturity series to compare against: the vendor "
      "quotes 30, 60 and 90 days only, which is itself part of the answer.)")

# %%
hp = (panel[panel.listed_symbol == NB.headline]
      .drop_duplicates("date").sort_values("date").set_index("date"))
fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.07,
                    row_heights=[0.55, 0.45],
                    subplot_titles=("Selected contract's time to expiry vs the 1-year horizon",
                                    "Which deliverable was held"))
fig.add_trace(go.Scatter(x=hp.index, y=hp.listed_tte * 365.0, mode="lines",
                         name="real contract TTE", line=dict(color="#1f77b4", width=1.4)),
              row=1, col=1)
fig.add_hline(y=365.0, line=dict(color="#d62728", dash="dash"), row=1, col=1,
              annotation_text="curve horizon (365 d)", annotation_position="top left")
fig.add_hline(y=30.0, line=dict(color="#7f7f7f", dash="dot"), row=1, col=1,
              annotation_text="CM control (30 d)", annotation_position="bottom left")
codes = hp.listed_contract_code.astype(str)
fig.add_trace(go.Scatter(x=hp.index, y=pd.factorize(codes)[0], mode="lines",
                         name="contract", line=dict(color="#2ca02c", width=1.2, shape="hv")),
              row=2, col=1)
fig.update_yaxes(title_text="days", row=1, col=1)
fig.update_yaxes(title_text="contract # (sawtooth = roll)", row=2, col=1)
fig.update_layout(height=620, title=f"{NB.headline}: the expiry a tradeable benchmark "
                                    "actually offers", template="plotly_white")
fig.show()

# %% [markdown]
# ## 5. Roll effects — the one thing an interpolation never has
#
# **Item 3.** `roll_jump_multiple` is the number to read: the benchmark's median
# absolute move **on a roll day** divided by its median absolute move on an
# ordinary day. 1.0 would mean the roll is invisible in the series.

# %%
roll = pd.read_csv(DATA / NB.roll)
hr = roll[roll.listed_symbol == NB.headline]
print(hr[["structure", "n_days", "n_rolls", "median_hold_days",
          "median_abs_vol_jump_bp_day", "median_abs_daily_move_bp_day",
          "roll_jump_multiple", "n_signal_flips_total", "n_signal_flips_on_roll",
          "frac_rolls_that_flip_signal"]].to_string(index=False))

r0 = hr.iloc[0]
assert int(r0.n_rolls) > 30, "the horizon-matched benchmark must actually roll"
assert r0.roll_jump_multiple > 1.0, (
    "a roll must move the benchmark more than an ordinary day, or the selection "
    "is not really changing contract")
print(f"\nThe benchmark jumps {r0.roll_jump_multiple:.2f}x its ordinary daily move on a "
      f"roll day ({r0.median_abs_vol_jump_bp_day:.3f} vs "
      f"{r0.median_abs_daily_move_bp_day:.3f} bp/day) -- a real discontinuity that "
      "constant maturity smooths away.")
flips = hr[hr.structure == NB.focus].iloc[0]
print(f"On {NB.focus} the cheap/rich verdict flipped {int(flips.n_signal_flips_total)} "
      f"times in {int(flips.n_days)} days and NONE of those flips fell on a roll day "
      f"({int(flips.n_signal_flips_on_roll)} of {int(flips.n_rolls)} rolls). "
      "The roll is visible in the benchmark and invisible in the signal.")

# %% [markdown]
# ## 6. The funded straddle — JPM's own sizing, on a contract that exists
#
# **Item 2.** `strat1_curve_gamma` already implements the sizing (Bachelier at
# the forward, `sqrt(2/pi) * sigma * sqrt(T)`); this supplies it with a listed
# contract instead of a swaption node, and then does the thing only a real
# contract permits — converts the required DV01 into a **number of deliverable
# contracts**, using the CTD FV01 measured out of the repo's own basis store
# (`0.1388` price points per bp on US, i.e. **$138.8 of DV01 per contract**,
# which ties out against the market).
#
# **Two approximations, both named on the frame.** The option expires long before
# the horizon (median 133 days), so the carry it funds is pro-rated linearly to
# the option's own life — `straddle_dv01_full_carry` is carried beside it so the
# size of that choice is visible. And where the flattener **carries positively**
# there is nothing to fund; those rows are flagged rather than sized off `|carry|`.

# %%
strad = pd.read_parquet(DATA / NB.straddle)
ssum = pd.read_csv(DATA / NB.straddle_summary)
print(ssum[["structure", "n_days", "frac_carry_negative", "n_fundable",
            "median_tte_days", "median_premium_bp", "median_carry_scaled_bp",
            "median_straddle_dv01", "median_straddle_dv01_ratio",
            "median_n_contracts", "p95_n_contracts",
            "median_premium_usd_per_contract"]].to_string(index=False))

f = ssum.set_index("structure").loc[NB.focus]
assert np.isfinite(f.median_n_contracts) and f.median_n_contracts > 0, (
    "a real contract must give a contract COUNT -- this is the number constant "
    "maturity could never produce")
print(f"\n{NB.focus}: the flattener carries negatively on {f.frac_carry_negative:.1%} of "
      f"days; funding that carry needs a median of {f.median_n_contracts:.0f} straddles "
      f"(p95 {f.p95_n_contracts:.0f}), i.e. {f.median_straddle_dv01_ratio:.1%} of the "
      "package DV01, at a premium of "
      f"${f.median_premium_usd_per_contract:,.0f} per contract.")
z = ssum.set_index("structure").loc["30Y/50Y"]
print(f"30Y/50Y: carry is negative on only {z.frac_carry_negative:.1%} of days -- the "
      "flattener PAYS to hold on 86% of the sample, so the note's funding leg is not "
      "applicable there at all. That is a result, not a gap.")

# %%
sf = strad[strad.structure == NB.focus].sort_values("date")
fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08,
                    subplot_titles=(f"{NB.focus}: carry to fund vs straddle premium intake",
                                    "Straddle size, in deliverable contracts"))
fig.add_trace(go.Scatter(x=sf.date, y=-sf.carry_scaled_bp, name="carry to fund (bp, +ve = a cost)",
                         line=dict(color="#d62728", width=1.2)), row=1, col=1)
fig.add_trace(go.Scatter(x=sf.date, y=sf.premium_bp, name="straddle premium (bp per unit DV01)",
                         line=dict(color="#1f77b4", width=1.2)), row=1, col=1)
nn = sf.where(sf.carry_negative)
fig.add_trace(go.Scatter(x=sf.date, y=nn.n_contracts, name="contracts (carry negative only)",
                         line=dict(color="#2ca02c", width=1.1)), row=2, col=1)
fig.update_yaxes(title_text="bp", row=1, col=1)
fig.update_yaxes(title_text="contracts", row=2, col=1)
fig.update_layout(height=620, template="plotly_white",
                  title="The note's funding leg, priced off a contract that exists")
fig.show()

# %% [markdown]
# ## 7. **The control question**: was constant maturity an adequate proxy?
#
# Both panels carry the identical curve breakeven and the identical 1Yx30Y
# swaption on the same dates; only `listed_atm_bp_day` differs. So every number
# in this table is the substitution and nothing else.
#
# `frac_signal_differs` is the answer.

# %%
cvr = pd.read_csv(DATA / NB.cm_vs_real)
print(cvr[["structure", "n_days", "cheap_share_cm", "cheap_share_real",
           "cheap_share_diff", "frac_signal_differs", "n_signal_differs",
           "median_listed_cm_bp_day", "median_listed_real_bp_day",
           "median_listed_diff_bp_day", "corr_level", "corr_change",
           "median_basis_cm_bp_day", "median_basis_real_bp_day"]].to_string(index=False))

pool = cvr.set_index("structure").loc["POOLED"]
foc = cvr.set_index("structure").loc[NB.focus]
assert pool.median_listed_diff_bp_day > 0, (
    "the selected contract sits at a median 133 days, where the ABPV term structure "
    "is ABOVE the 30-day point -- a negative sign here would contradict the harvest's "
    "own measured ageing table")
print(f"\nThe real benchmark prices {pool.median_listed_diff_bp_day:+.3f} bp/day MORE vol "
      f"than {NB.cm_headline} (correlation of daily changes {pool.corr_change:.3f}), so the "
      "curve looks CHEAPER against it -- and the verdict still changes on "
      f"{pool.frac_signal_differs:.2%} of pooled rows "
      f"({int(pool.n_signal_differs)} of {int(pool.n_days)}), all of them on "
      f"{NB.focus} ({foc.frac_signal_differs:.2%}).")

# %% [markdown]
# ### Why the two benchmarks differ: the term structure CM was smoothing away
#
# Real ABPV against the same-day `US_30`, bucketed by the contract's time to
# expiry. At ~30 days they are the same number to 0.2%; by 150-250 days — where
# the horizon-matched contract actually lives — they differ by **6%**.

# %%
age = pd.read_csv(DATA / NB.ageing)
print(age.to_string(index=False))
assert abs(age.ratio_median.iloc[0] - 1.0) < 0.01, "at ~30 days the two must agree"
assert age.ratio_median.iloc[-1] > 1.03, "and diverge as the contract ages"
print(f"\nAt 25-35 days the real contract and US_30 agree to "
      f"{abs(age.ratio_median.iloc[0] - 1) * 100:.2f}%; at 150-250 days the real contract "
      f"prices {(age.ratio_median.iloc[-1] - 1) * 100:.1f}% MORE vol. "
      "That gap is the whole of the difference in section 7.")

# %%
sub = contracts[(contracts.root == "US") & (contracts.value_type == "ABPV")]
lad = lc.expiry_ladder(sub, NB.ladder_day, root="US")
cm_day = cm_raw[(cm_raw.root == "US") & (cm_raw.value_type == "ABPV")
                & (cm_raw.date == pd.Timestamp(NB.ladder_day))]
fig = go.Figure()
fig.add_trace(go.Scatter(x=lad.tte_days, y=lad.value, mode="markers+lines",
                         name="real contracts (the ladder)",
                         marker=dict(size=11, color="#1f77b4"),
                         text=lad.contract_code, hovertemplate="%{text}<br>%{x:.0f} d, %{y:.2f} bp/yr"))
fig.add_trace(go.Scatter(x=cm_day.cm_days, y=cm_day.value, mode="markers",
                         name="constant maturity (the interpolation)",
                         marker=dict(size=15, color="#d62728", symbol="x")))
sel_row = panel[(panel.listed_symbol == NB.headline)
                & (panel.date == pd.Timestamp(NB.ladder_day))]
if len(sel_row):
    fig.add_trace(go.Scatter(x=[sel_row.listed_tte.iloc[0] * 365.0],
                             y=[sel_row.listed_atm_bp_yr.iloc[0]], mode="markers",
                             name=f"{NB.headline} selects", marker=dict(size=19, color="#2ca02c",
                                                                        symbol="circle-open",
                                                                        line=dict(width=3))))
fig.update_layout(height=460, template="plotly_white",
                  title=f"US expiry ladder on {NB.ladder_day} — what CM interpolates, "
                        "and what the horizon rule picks",
                  xaxis_title="days to expiry", yaxis_title="ABPV, bp/yr")
fig.show()

# %% [markdown]
# ### What the missing Ultra Bond would have been worth
#
# UL has no listed contract, but both roots exist in the **constant-maturity**
# panel, so the size of the substitution is measurable even though one side of it
# is not tradeable.

# %%
pen = rc.unavailable_root_penalty(cm_raw)
print(json.dumps(pen, indent=1))
assert pen["median_bp_day"] < 0
print(f"\nUL_30 prices {abs(pen['median_bp_day']):.3f} bp/day LESS vol than US_30 "
      f"({pen['n']} common dates). Substituting US for the unavailable UL therefore "
      "RAISES the listed benchmark and makes the curve look CHEAPER -- i.e. the missing "
      "contract biases the headline TOWARDS the conclusion already reached, by about a "
      "third of a bp/day. That is the size of the sector limitation, not a hand-wave.")

# %% [markdown]
# ## 8. The signal distribution — the headline
#
# **Question (a): against a real listed contract, what is the cheap-share?**
#
# Read `frac_cheap_vs_listed` next to `frac_cheap_vs_otc`. The three forward
# structures are saturated at 1.00 against *both* benchmarks — on those, no
# benchmark can change anything, and the saturation is the finding. **5Y/30Y is
# the only structure on which the comparison binds.**

# %%
dist = sl.longend_signal_distribution(panel.set_index(["date", "structure", "listed_symbol"]))
hd = dist[dist.listed_symbol == NB.headline]
print(hd[["structure", "listed_symbol", "n_days", "first", "last",
          "frac_cheap_vs_listed", "frac_cheap_vs_otc", "frac_never_cheap",
          "median_breakeven_bp_day", "median_listed_bp_day", "median_otc_bp_day",
          "median_otc_minus_listed_bp_day", "frac_signals_disagree"]].to_string(index=False))

sat = hd[hd.frac_cheap_vs_listed >= 0.999].structure.tolist()
assert NB.focus not in sat and len(sat) == 3, (
    "three structures saturate at 100% and 5Y/30Y does not -- if that changes, the "
    "'binding structure' argument below has to be rewritten")
b = hd.set_index("structure").loc[NB.focus]
print(f"\nANSWER (a): against a REAL listed contract the long-end flatteners are cheap "
      f"gamma on {', '.join(f'{s} 100%' for s in sat)} and on "
      f"{b.frac_cheap_vs_listed:.1%} of days for {NB.focus} -- i.e. the 100% survives "
      "the substitution on the three saturated structures and the one unsaturated "
      f"structure moves from {b.frac_cheap_vs_otc:.1%} (vs swaptions) to "
      f"{b.frac_cheap_vs_listed:.1%} (vs the contract).")

# %%
pf = (panel[(panel.listed_symbol == NB.headline) & (panel.structure == NB.focus)]
      .sort_values("date"))
cf = (cm_panel[(cm_panel.listed_symbol == NB.cm_headline) & (cm_panel.structure == NB.focus)]
      .sort_values("date"))
fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08,
                    row_heights=[0.6, 0.4],
                    subplot_titles=(f"{NB.focus}: the three vols, bp/day",
                                    "Real contract minus constant maturity"))
fig.add_trace(go.Scatter(x=pf.date, y=pf.breakeven_vol_bp_day.replace(np.inf, np.nan),
                         name="curve breakeven", line=dict(color="#111", width=1.3)), row=1, col=1)
fig.add_trace(go.Scatter(x=pf.date, y=pf.otc_atmf_bp_day, name="1Yx30Y swaption ATMF",
                         line=dict(color="#d62728", width=1.2)), row=1, col=1)
fig.add_trace(go.Scatter(x=pf.date, y=pf.listed_atm_bp_day, name=f"listed {NB.headline}",
                         line=dict(color="#1f77b4", width=1.2)), row=1, col=1)
fig.add_trace(go.Scatter(x=cf.date, y=cf.listed_atm_bp_day, name=f"listed {NB.cm_headline} (control)",
                         line=dict(color="#7f7f7f", width=1.0, dash="dot")), row=1, col=1)
m = pf[["date", "listed_atm_bp_day"]].merge(cf[["date", "listed_atm_bp_day"]], on="date",
                                            suffixes=("_r", "_c"))
fig.add_trace(go.Scatter(x=m.date, y=m.listed_atm_bp_day_r - m.listed_atm_bp_day_c,
                         name="real - CM", line=dict(color="#9467bd", width=1.1)), row=2, col=1)
fig.add_hline(y=0.0, line=dict(color="#999", dash="dash"), row=2, col=1)
fig.update_yaxes(title_text="bp/day", row=1, col=1)
fig.update_yaxes(title_text="bp/day", row=2, col=1)
fig.update_layout(height=640, template="plotly_white",
                  title="Curve, swaption and listed — real contract against the CM control")
fig.show()

# %% [markdown]
# ## 9. The smile — the second thing constant maturity could not carry
#
# A listed UST option gives three points: 25-delta call, at the money, 25-delta
# put. The conversion to bp/yr is the **panel's own** — each quote is scaled by
# that row's measured `ABPV / ATM`, which for UST is the CTD's `1e4 / ModDur`.
# No external DV01 and no assumption that the scale is constant, because it is
# not: the CTD changes.
#
# The vendor's own `25D_BF` column is deliberately **not used** — the harvest
# measured it as a fly against an at-the-money anchor this panel does not carry
# (residual 51% of BF's own size on US) — so the fly is rebuilt from the three
# quoted vols.

# %%
smile = pd.read_parquet(DATA / NB.smile)
print(smile.groupby("root")[["atm_bp_yr", "call25_bp_yr", "put25_bp_yr",
                             "rr25_bp_yr", "bf25_bp_yr", "bf25_pct_of_atm"]]
      .median().to_string())
us = smile[smile.root == "US"]
print(f"\nUS: 25d risk reversal median {us.rr25_bp_yr.median():+.2f} bp/yr, negative on "
      f"{(us.rr25_bp_yr < 0).mean():.1%} of {len(us):,} rows; fly "
      f"{us.bf25_bp_yr.median():+.2f} bp/yr, positive on {(us.bf25_bp_yr > 0).mean():.1%}.")
assert us.rr25_bp_yr.median() < 0, (
    "on Treasury options the 25d PUT (a payer in yield space) should be bid -- a "
    "positive median RR would mean the strike geometry is mirrored")
assert us.bf25_bp_yr.median() > 0, "a 25-delta fly should be positive"
print("SIGN PROBE ok: puts bid, fly positive -- the smile has the shape a Treasury "
      "option smile should have, which is the check that the strike geometry is not "
      "mirrored.")

# %%
day = pd.Timestamp(NB.ladder_day)
snap = smile[(smile.root == "US") & (smile.date == day)].sort_values("tte_years")
fig = go.Figure()
for _, r in snap.iterrows():
    sm = rc.three_point_smile(r.atm_bp_yr, r.call25_bp_yr, r.put25_bp_yr, r.tte_years)
    if sm is None:
        continue
    fig.add_trace(go.Scatter(x=sm.offset_bp, y=sm.vol_bp, mode="lines",
                             name=f"{r.contract_code} ({r.tte_years * 365:.0f} d)"))
    kc, kp = rc.smile_strike_offsets(r.atm_bp_yr, r.call25_bp_yr, r.put25_bp_yr, r.tte_years)
    fig.add_trace(go.Scatter(x=[kc, 0.0, kp], y=[r.call25_bp_yr, r.atm_bp_yr, r.put25_bp_yr],
                             mode="markers", showlegend=False,
                             marker=dict(size=9, symbol="diamond")))
fig.update_layout(height=440, template="plotly_white",
                  title=f"US listed smiles on {NB.ladder_day} — the three quotes (diamonds) "
                        "and the quadratic through them",
                  xaxis_title="strike offset from forward, bp of yield (+ = higher yields)",
                  yaxis_title="normal vol, bp/yr")
fig.show()

# %% [markdown]
# ### The note's second signal, and its two honest caveats
#
# The expected payoff integrates strategy 1's own stored payoff profile against
# the contract's implied density. **Two mismatches are carried on every row
# rather than argued away**: the density is at the *option's* expiry (median 133
# days), not the profile's one-year horizon; and only ±~39 bp of strike is
# quoted, so beyond that the wings are a flat-vol extrapolation. The
# breakeven-vol signal remains the headline.

# %%
epp = DATA / NB.expected_payoff
if epp.exists():
    ep = pd.read_parquet(epp)
    print("density status shares:",
          {k: round(v, 4) for k, v in ep.ep_status.value_counts(normalize=True).items()})
    print(f"median quoted half-width: {np.nanmedian(ep.ep_quoted_halfwidth_bp):.1f} bp "
          f"of yield  (the shift grid runs to +/-250 bp)")
    ok = ep[ep.ep_status == "ok"]
    t = ok.groupby("structure").apply(lambda g: pd.Series({
        "n": len(g),
        "median_ep_bp": float(np.nanmedian(g.expected_payoff_bp)),
        "frac_ep_positive": float((g.expected_payoff_bp > 0).mean()),
        "agrees_with_breakeven": float((np.sign(g.expected_payoff_bp) == g.signal_listed).mean()),
    }), include_groups=False)
    print()
    print(t.to_string())
    assert (ep.ep_status == "ok").mean() > 0.9, (
        "if most densities fail, this signal should be dropped, not reported")
    print(f"\nThe two signals agree on {t.loc[NB.focus, 'agrees_with_breakeven']:.1%} of "
          f"{NB.focus} rows and 99-100% elsewhere. The expected-payoff signal is a "
          "genuine second reading of the same comparison -- and it exists only because "
          "the benchmark is a real contract with strikes.")
else:
    print(f"{NB.expected_payoff} not built -- run `_strat1_contracts_build.py payoff`")

# %% [markdown]
# ## 10. Robustness — the answer at all eight benchmarks
#
# Two roots x four expiry targets. `US@H365` is the pre-specified headline; the
# other seven are **robustness, not extra trials** — they score the same
# comparison against a different benchmark.

# %%
allb = dist.pivot_table(index="structure", columns="listed_symbol",
                        values="frac_cheap_vs_listed")
print(allb.to_string())
print()
print(dist.pivot_table(index="structure", columns="listed_symbol",
                       values="median_otc_minus_listed_bp_day").round(3).to_string())
rng = allb.loc[NB.focus]
print(f"\n{NB.focus} cheap-share across all eight benchmarks: "
      f"{rng.min():.3f} .. {rng.max():.3f} (headline {rng[NB.headline]:.3f}). "
      "The three saturated structures are 1.000 against every one of the eight.")
assert (allb.drop(index=NB.focus) >= 0.999).all().all(), (
    "the saturation is benchmark-independent; if it is not, the headline needs a "
    "benchmark-selection caveat")

# %% [markdown]
# ## 11. Verdict
#
# Written by `rc.real_contract_verdict` and stored as JSON, so the notebook and
# any downstream consumer read the same numbers.

# %%
verdict = json.loads((DATA / NB.verdict).read_text())
print("mode      ", verdict["mode"])
print("benchmark ", json.dumps(verdict["headline_benchmark"], indent=1))
print("coverage  ", json.dumps(verdict["coverage"], indent=1))
print()
print("expiry match (headline):")
print(json.dumps({k: v for k, v in (verdict["expiry_match"]["headline"] or {}).items()
                  if k in ("median_tte_days", "max_tte_days", "median_gap_days",
                           "best_gap_days", "cm_gap_days", "frac_selected_is_longest",
                           "n_contracts", "median_hold_days")}, indent=1))
print()
print("sector limitation:", json.dumps(
    verdict["sector_limitation"]["substitution_penalty"], indent=1))

# %% [markdown]
# ### The three answers, in one place

# %%
pool = cvr.set_index("structure").loc["POOLED"]
foc = cvr.set_index("structure").loc[NB.focus]
b = hd.set_index("structure").loc[NB.focus]
print(f"""
(a) CHEAP-SHARE AGAINST A REAL CONTRACT
    Three of the four long-end structures are cheap gamma against the real
    listed contract on 100.0% of days -- identical to the constant-maturity
    answer and to the 1Yx30Y swaption answer -- and 5Y/30Y, the only
    unsaturated structure, is cheap on {b.frac_cheap_vs_listed:.1%} of
    {int(b.n_days):,} days against {b.frac_cheap_vs_otc:.1%} versus swaptions.
    The 100% is a property of the CURVE, not of the benchmark.

(b) DID CONSTANT MATURITY CHANGE THE ANSWER?
    No verdict moves on the three saturated structures (0 of {int(cvr.iloc[0].n_days):,}
    days each). On {NB.focus} the verdict differs on {foc.frac_signal_differs:.2%} of days
    ({int(foc.n_signal_differs)} of {int(foc.n_days):,}), {pool.frac_signal_differs:.2%} pooled.
    The real benchmark prices {pool.median_listed_diff_bp_day:+.3f} bp/day more vol
    (change-correlation {pool.corr_change:.3f}) because the horizon-matched contract
    sits at a median {pool.median_tte_days_real:.0f} days, where the ABPV term
    structure runs {(age.ratio_median.iloc[-1] - 1) * 100:.1f}% above the 30-day point.
    CM was an adequate proxy for the CHEAP/RICH VERDICT and a biased proxy for
    the LEVEL -- and it could not have produced sections 6 or 9 at all.

(c) IS THE OTC-LISTED BASIS BIG ENOUGH TO MATTER?  -- see the three-way notebook
    median |basis| widens from {abs(pool.median_basis_cm_bp_day):.3f} bp/day (CM) to
    {abs(pool.median_basis_real_bp_day):.3f} bp/day (real), against an unchanged
    flip threshold. Full like-for-like retest in strat1_threeway_contracts.
""")

# %% [markdown]
# ## 12. Honest limits
#
# * **The expiry match is halved, not closed.** 232 days short at the median,
#   124 at the very best, against a 365-day horizon. Every bp/day comparison in
#   this notebook still rests on the listed term structure being close to flat
#   over that gap, and §7's ageing table shows it is **not** flat — it runs ~6%
#   from 30 to 200 days. The direction of that error makes the curve look
#   cheaper, i.e. it flatters the conclusion.
# * **UL and TN do not exist as contracts.** On 30Y/50Y and 20Yx5Y/25Yx5Y the
#   sector-correct benchmark is only available as constant maturity. Measured
#   cost of the substitution: **0.345 bp/day**, in the direction that flatters
#   the conclusion.
# * **The horizon rule is degenerate.** At a 365-day target "nearest expiry"
#   is always "longest listed", which is also the least liquid contract on the
#   board. §10's `D30`/`D60`/`D90` benchmarks exist so the answer can be read at
#   a target where the selection is not degenerate.
# * **Sample size.** 1,901 daily dates is ~7.5 independent one-year observations
#   per structure. Every distributional statement here survives that; no P&L
#   statement does, and none is made in this notebook.

# %%
print("done.")
