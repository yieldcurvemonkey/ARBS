# %% [markdown]
# # Is the SOFR pack convexity adjustment being calculated correctly?
#
# The adjustment is a **small difference of two large numbers** — a few basis
# points of spread between a ~3–5% pack rate and a ~3–5% swap rate. Every
# convention error and every stale quote lands in it at full size, and Citi
# prints the result to 2dp on values as small as 0.08bp. So "it ties out to
# Citi on one date" is necessary and nowhere near sufficient.
#
# The methodology being reproduced, verbatim (*Rates Vol Lab*, 12-Jun-2023,
# Figure 58, close 6/9/23):
#
# > "Convexity adjustments for 1y SOFR packs are computed as the spread between
# > the pack's rate (the average of 4 SOFR rates in the pack) and
# > matched-maturity forward 1y CME swap rate."
#
# and the matched swap pinned by the trade recommendation ([W-JAN13] p.14):
#
# > "buy 1000 of H0-Z0 packs … and pay $1bn on a **matched-maturity
# > (3/18/20-3/17/21)** CME swap. Consistent with the standard market practice,
# > **both fixed and floating legs of this swap have a quarterly payment
# > frequency**."
#
# This notebook is the correctness report. It runs seven tests over
# **11,900 pack-days** (1,190 dates × 10 rolling pack windows, 2019-01-02 to
# 2023-12-27) and reports what each measured. Nothing here is asserted; the
# numbers come from `notebooks/data/convexity_rv/strat2_ca_quality.parquet`,
# built by `scripts/strat2_ca_quality_scan.py`.
#
# ## The four findings that matter, up front
#
# 1. **The conventions are right, and the evidence is internal, not Citi's.**
#    Substituting the swap curve's own IMM×IMM forwards for the futures rates
#    must return a zero adjustment. Across all 11,900 pack-days it returns
#    **mean −0.053bp, median −0.014bp, |residual| p95 0.59bp** — a median 1.5%
#    of |CA|. Better than that: what it *does* return is the annuity-weighting
#    term (equal-weighted pack rate versus annuity-weighted par rate), predicted
#    from the four forwards with no free parameter; removing it leaves **mean
#    −0.003bp, sd 0.20bp**. The arithmetic, the day-count, the roll and the swap
#    frequency are all verified at once with no external reference.
#
# 2. **But that control has a blind spot, and it is large.** `CA_synthetic`
#    compares an arithmetic mean of four forwards to the par rate of the swap
#    spanning them. If the discount curve has **no node inside the window**, all
#    four forwards are the same interpolated number and the two agree *by
#    construction* — the control returns exactly 0.00bp on a swap leg that is
#    not a market observation at all. `USD-SOFR-1D` ran on 26 nodes with a
#    single 735-day front segment until **2019-07-08**. On **45.5% of
#    pre-2019-07-08 rows** the control had no power (forward spread < 1bp), and
#    on **520 rows it had literally none** (spread 8.9e-12 bp, machine zero,
#    514 of them in 2019) while their adjustments ranged −91.6 to +27.6bp.
#    **49.2% of pre-break rows** print a negative — impossible — adjustment.
#    **The first six months of the sample must be discarded.**
#
# 3. **The stored strategy panel is wrong by up to 12bp.** `strat2_panel.parquet`
#    reproduces this notebook's **annual**-frequency variant to 1.9e-12 on all
#    11,750 overlapping rows — i.e. it was built with the `usd_irs` spec default
#    (annual fixed) rather than Citi's quarterly/quarterly. The bias is
#    `−0.375·r²` bp: **−1.90bp on average, −5.46bp in 2023, −9.34bp on the front
#    pack on 2023-06-09**, which flips that pack from +0.13bp to a no-arbitrage
#    violation. The current `ca_snapshot` code path is correct; the artifact on
#    disk is stale and must be rebuilt.
#
# 4. **The measurement error is 1.7–2.7bp per observation at ranks 1–8.**
#    Estimated two ways (an MA(1)/Roll estimator on daily CA changes and the
#    `sd(ΔCA)/√2` upper bound, which agree to ~2%). That is what sets the
#    minimum tradeable pack rank, and it sets it from this data rather than from
#    Citi's convention of starting at Reds.
#
# ---
# **Sources.** Citi Research, *US Rates Weekly* 13-Jan-2017 / *Rates Vol Lab*
# 12-Jun-2023 (Fig 58) — see
# `docs/convexityrv/research/01-citi-stir-convexity-vs-butterfly.md` §1, §2,
# §7.8, §8. Implementation: `RVUtils/ConvexityRV/ca_diagnostics.py`,
# `RVUtils/ConvexityRV/curve_ops.py`, `RVUtils/ConvexityRV/holee.py`.

# %%
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import datetime as dt
import logging
import pathlib
import sys
from dataclasses import dataclass, field
from typing import Tuple

logging.disable(logging.WARNING)

_REPO = pathlib.Path.cwd()
while not (_REPO / "RVUtils").is_dir() and _REPO != _REPO.parent:
    _REPO = _REPO.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
from plotly.subplots import make_subplots

pio.renderers.default = "plotly_mimetype+notebook_connected"
pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 60)

import RVUtils.ConvexityRV.ca_diagnostics as CAD
from RVUtils.ConvexityRV.holee import (implied_vol_from_ca_bp, pack_ca_bp,
                                       pack_time_weight)
from RVUtils.ConvexityRV.packs import (imm_date, matched_swap_dates, pack_label,
                                       pack_t1s, quarterly_imm_sequence,
                                       year_fraction_act365)

print(f"repo   {_REPO}")
print(f"pandas {pd.__version__}   numpy {np.__version__}")


# %% [markdown]
# ## Config
#
# Every knob the report depends on, with the reason it has that value.

# %%
@dataclass(frozen=True)
class DiagConfig:
    """Knobs for the correctness report. Nothing here is fitted to a P&L."""

    panel: str = "notebooks/data/convexity_rv/strat2_ca_quality.parquet"
    """Output of ``scripts/strat2_ca_quality_scan.py``: one row per (date, pack)
    with the adjustment computed four independent ways."""

    strategy_panel: str = "notebooks/data/convexity_rv/strat2_panel.parquet"
    """The panel the Strategy-2 backtest actually consumes. Cross-checked here
    against this scan; the check is what found the annual-frequency bug."""

    curve_resolution_date: dt.date = dt.date(2019, 7, 8)
    """First date on which ``USD-SOFR-1D`` carries its 45-node grid. Before it
    the curve is 26 nodes with the second at start+735d, so the entire front end
    is one log-linear segment and every IMM forward inside it is the same
    number. MEASURED, not assumed: 2019-06-20 -> 26 nodes, 2019-07-01 -> 33,
    2019-07-08 -> 45. Rows before this date are reported but excluded from every
    conclusion."""

    min_control_power_bp: float = 1.0
    """A pack whose four synthetic forwards spread less than this carries no
    information about the swap-leg convention: ``CA_synthetic`` is zero by
    construction there. Used to gate the zero-convexity control, NOT to filter
    the CA itself."""

    max_convention_bp: float = 1.0
    """``|CA_synthetic|`` above this is a genuine convention failure rather than
    interpolation noise. Chosen at ~2x the measured p95 of 0.57bp."""

    plausible_vol_bp: Tuple[float, float] = CAD.PLAUSIBLE_VOL_BP
    """(40, 350). A SOFR normal vol outside this is an inversion artefact, not a
    market observation. Citi's own 2023 SOFR screen spans 151.9-199.5."""

    citi_as_of: dt.date = dt.date(2023, 6, 9)
    """The external anchor: Figure 58, 13 rows, [VL-SOFR] p.14."""

    citi_tolerance_bp: float = 4.0
    """Row-level tolerance for the Citi tie-out. Loose on purpose -- Citi's swap
    leg is CME-cleared and this curve is not, and Citi's futures snapshot is the
    CME 15:00 ET settle while Barchart's is the bar nearest 17:00 NY. The tight
    statement is the MEAN error and the correlation, not any single row."""

    max_business_day_gap: int = 4
    """Rows whose previous observation is more than this many calendar days back
    are dropped from every daily-difference statistic. A Tue-to-Tue 'daily'
    change across a data hole is not a daily change."""

    vol_noise_budget: float = 0.15
    """The report's proposed rule for the minimum pack rank usable for vol
    inversion: the implied-vol noise induced by the measured CA noise must be
    under this fraction of the vol level. 0.15 = 'the vol is quoted to within
    ~15%'. Citi's convention (start at Reds) corresponds to ~30%."""

    shape_min_rank: int = 5
    """Ho-Lee shape tests are run on rank >= this. Ranks 1-4 have CA of a few
    tenths of a bp against a measured noise of ~1.7bp, so their logs are noise
    and would dominate a log-log slope."""


CFG = DiagConfig()
PANEL = _REPO / CFG.panel
print(CFG)


# %% [markdown]
# ## Sign and convention probe
#
# Known-answer checks on the primitives, before any of them is trusted with a
# measurement. Each one has an inverted control so the assert cannot pass
# vacuously.

# %%
# --- 1. Ho-Lee shape: synthetic CA = 1/2 sigma^2 T1^2 must invert to slope 2.0
_t1 = np.arange(1.0, 5.01, 0.25)
_probe = pd.DataFrame({"t1_first": _t1, "ca_bp": 0.5 * (0.015 ** 2) * _t1 ** 2 * 1e4})
_sh = CAD.shape_diagnostics(_probe)
assert abs(_sh["loglog_slope"] - 2.0) < 1e-9, _sh
assert abs(_sh["corr_t1_squared"] - 1.0) < 1e-12, _sh
# control: a LINEAR-in-T1 adjustment must NOT return slope 2
_lin = pd.DataFrame({"t1_first": _t1, "ca_bp": 3.0 * _t1})
assert abs(CAD.shape_diagnostics(_lin)["loglog_slope"] - 2.0) > 0.9
print(f"1. shape probe   slope={_sh['loglog_slope']:.6f} (target 2)  "
      f"corr={_sh['corr_t1_squared']:.6f} (target 1)   linear control "
      f"slope={CAD.shape_diagnostics(_lin)['loglog_slope']:.4f}")

# --- 2. the 3/8 q^2 compounding identity against exact compounding
for _q in (0.005, 0.02, 0.034, 0.05):
    _exact = ((1 + _q / 4) ** 4 - 1 - _q) * 1e4
    _approx = CAD.compounding_gap_bp(_q * 100.0)
    assert abs(_exact - _approx) < 0.05 + 0.02 * _exact, (_q, _exact, _approx)
print(f"2. compounding   q=5%: exact {((1.0125)**4 - 1 - 0.05)*1e4:.4f}bp  "
      f"3/8q^2 {CAD.compounding_gap_bp(5.0):.4f}bp")

# --- 3. pack_time_weight([sqrt(M)]) == M  (the pseudo-T1 identity strat2 relies on)
_t1s = pack_t1s(dt.date(2023, 6, 9), [(2024, 6), (2024, 9), (2024, 12), (2025, 3)])
_M = pack_time_weight(_t1s)
assert abs(pack_time_weight([np.sqrt(_M)]) - _M) < 1e-12
# and the inversion round-trips
assert abs(implied_vol_from_ca_bp(pack_ca_bp(160.0, _t1s), _t1s) - 160.0) < 1e-9
print(f"3. Ho-Lee        M={_M:.6f}  sigma->CA->sigma round trip exact")

# --- 4. a negative adjustment must invert to NaN, not to a number
assert not np.isfinite(implied_vol_from_ca_bp(-1.0, _t1s))
assert np.isfinite(implied_vol_from_ca_bp(+1.0, _t1s))
print("4. no-arb        CA<0 -> NaN implied vol; CA>0 -> finite")

# --- 5. window_resolution must detect a curve that spans the window
_nodes_coarse = [dt.date(2019, 3, 15), dt.date(2021, 3, 19), dt.date(2022, 3, 21)]
_nodes_fine = [dt.date(2019, 3, 15) + dt.timedelta(days=30 * k) for k in range(40)]
_w = (dt.date(2019, 6, 19), dt.date(2020, 6, 17))
assert CAD.window_resolution(_nodes_coarse, *_w)["n_nodes_inside"] == 0
assert CAD.window_resolution(_nodes_coarse, *_w)["spans_window"] == 1.0
assert CAD.window_resolution(_nodes_fine, *_w)["n_nodes_inside"] >= 10
assert CAD.window_resolution(_nodes_fine, *_w)["spans_window"] == 0.0
print("5. resolution    coarse grid -> 0 nodes inside / spans=1; fine -> >=10 / spans=0")

# --- 6. flag_quality must fire on the thing it exists to catch
_fq = CAD.flag_quality(pd.DataFrame({
    "ca_bp": [5.0, -2.0, 5.0, 5.0],
    "ca_synthetic_bp": [0.0, 0.0, 3.0, 0.0],
    "implied_vol_bp": [160.0, np.nan, 160.0, 900.0],
    "t1_first": [2.0, 2.0, 2.0, 2.0]}))
assert list(_fq["flag_negative_ca"]) == [False, True, False, False]
assert list(_fq["flag_convention"]) == [False, False, True, False]
assert list(_fq["flag_implausible_vol"]) == [False, False, False, True]
assert list(_fq["ok"]) == [True, False, False, False]
print("6. flags         negative-CA / convention / implausible-vol each fire alone")


# %% [markdown]
# ## The panel
#
# One row per (date, pack window). Ten rolling windows per date, from the four
# front quarterlies (rank 1, Whites) out to the window starting at the 10th
# quarterly (~2.4y). Deeper windows would need 20 contracts and the deferred SR3
# settles are not in the local store daily — Citi's own table is windows 5–17,
# so this sample is the near half of it. Say so rather than extrapolate.

# %%
def describe_bp(s, name=""):
    """Distribution summary in bp — the same shape everywhere so rows stack."""
    s = pd.Series(s).replace([np.inf, -np.inf], np.nan).dropna()
    q = s.quantile([0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99])
    return pd.Series({"n": len(s), "mean": s.mean(), "median": s.median(),
                      "sd": s.std(), "p1": q.iloc[0], "p5": q.iloc[1],
                      "p25": q.iloc[2], "p75": q.iloc[4], "p95": q.iloc[5],
                      "p99": q.iloc[6], "abs_mean": s.abs().mean(),
                      "abs_p95": s.abs().quantile(0.95),
                      "abs_max": s.abs().max()}, name=name)


df = pd.read_parquet(PANEL)
df["year"] = df["date"].dt.year
df["curve_ok"] = df["date"] >= pd.Timestamp(CFG.curve_resolution_date)
df["has_power"] = df["fwd_spread_bp"] >= CFG.min_control_power_bp

print(f"{len(df):,} pack-days | {df['date'].nunique():,} dates | "
      f"{df['date'].min():%Y-%m-%d} .. {df['date'].max():%Y-%m-%d}")
cover = df.groupby("year").agg(
    rows=("ca_observed_bp", "size"), dates=("date", "nunique"),
    curve_nodes=("n_curve_nodes", "median"),
    ca_med=("ca_observed_bp", "median"),
    frac_no_control_power=("has_power", lambda s: float((~s).mean())),
    frac_negative_ca=("ca_observed_bp", lambda s: float((s < 0).mean())))
print("\ncoverage and regime by year")
print(cover.round(4).to_string())
print(f"\ncolumns: {list(df.columns)}")


# %% [markdown]
# ## Test 0 — curve resolution, the blind spot the other tests cannot see
#
# Run first because it decides which rows the other tests are allowed to speak
# about.
#
# The matched swap is priced off the discount curve's node grid. A par rate for
# a window that contains no node is an *interpolation*, not a market
# observation — and worse, under log-linear discount-factor interpolation every
# forward inside the segment is the same constant, so the arithmetic mean of
# four of them equals the par rate of the swap spanning them **identically**.
# `CA_synthetic` returns 0.00 and the control looks like it passed.

# %%
res = df.groupby("year").agg(
    n=("fwd_spread_bp", "size"),
    nodes=("n_curve_nodes", "median"),
    fwd_spread_med=("fwd_spread_bp", "median"),
    frac_zero_power=("fwd_spread_bp", lambda s: float((s < CFG.min_control_power_bp).mean())),
    frac_no_node_inside=("n_nodes_inside", lambda s: float((s == 0).mean())),
    syn_absmax=("ca_synthetic_bp", lambda s: float(s.abs().max())))
print("curve resolution by year")
print(res.round(4).to_string())

blocks = []
for lab, g in [("pre 2019-07-08", df[~df.curve_ok]), ("2019-07-08 onward", df[df.curve_ok])]:
    blocks.append({
        "block": lab, "rows": len(g), "dates": g["date"].nunique(),
        "curve_nodes_med": g["n_curve_nodes"].median(),
        "fwd_spread_med_bp": g["fwd_spread_bp"].median(),
        "frac_control_powerless": float((g["fwd_spread_bp"] < CFG.min_control_power_bp).mean()),
        "median_|CA_synthetic|": float(g["ca_synthetic_bp"].abs().median()),
        "frac_CA_negative": float((g["ca_observed_bp"] < 0).mean())})
print("\nthe break")
print(pd.DataFrame(blocks).set_index("block").round(4).to_string())

deg = df[df["node_spans_window"] == 1.0]
print(f"\nDEGENERATE ROWS — a single node interval swallows the whole pack window, "
      f"so all four forwards are one interpolated constant:")
print(f"   n = {len(deg):,} of {len(df):,}   "
      f"({int((deg.year == 2019).sum()):,} of them in 2019)")
print(f"   forward spread, max        {deg['fwd_spread_bp'].max():.3e} bp   "
      f"(2019 subset: {deg[deg.year == 2019]['fwd_spread_bp'].max():.3e} — machine zero)")
print(f"   |CA_synthetic|, max        {deg['ca_synthetic_bp'].abs().max():.3e} bp   "
      f"(the control scores a PERFECT PASS)")
print(f"   CA_observed spans          {deg['ca_observed_bp'].min():+.2f} .. "
      f"{deg['ca_observed_bp'].max():+.2f} bp")
print(f"   of which negative          {float((deg['ca_observed_bp'] < 0).mean()):.3f}   "
      f"(a no-arbitrage impossibility)")
print(deg.groupby("year").agg(n=("ca_observed_bp", "size"),
                              fwd_spread_max=("fwd_spread_bp", "max"),
                              syn_absmax=("ca_synthetic_bp", lambda s: float(s.abs().max())),
                              ca_min=("ca_observed_bp", "min"),
                              ca_max=("ca_observed_bp", "max")).to_string())
print("\nA perfect control score on rows where the control CANNOT fail. This is the "
      "single most important caveat in the report: test (a) below is necessary, it "
      "is not sufficient, and its sufficiency has to be argued from `fwd_spread_bp` "
      "every single time.")


# %% [markdown]
# ### Test 0, read the other way: control power vs control residual
#
# Bucket every post-break pack-day by how much curvature its four synthetic
# forwards actually contained. If the residual were a real convention error it
# would be flat across the buckets. It is not — it grows with the curvature,
# which is the signature of a *interpolation* residual, and it stays small in
# absolute terms even in the highest bucket.

# %%
ok = df[df.curve_ok].copy()
ok["power_bucket"] = pd.cut(ok["fwd_spread_bp"], [-1e-6, 1, 10, 25, 50, 100, 1e9],
                            labels=["<1bp", "1-10", "10-25", "25-50", "50-100", ">100"])
pw = ok.groupby("power_bucket", observed=True).agg(
    n=("ca_synthetic_bp", "size"),
    syn_mean=("ca_synthetic_bp", "mean"),
    syn_sd=("ca_synthetic_bp", "std"),
    syn_absp95=("ca_synthetic_bp", lambda s: float(s.abs().quantile(0.95))),
    ca_obs_med=("ca_observed_bp", "median"))
print("control residual by control power (post-break)")
print(pw.round(4).to_string())
print("\nRead: the control is only informative in the bottom rows of this table, "
      "and where it IS informative it still returns <0.8bp at the 95th percentile.")


# %% [markdown]
# ### Test 0, third reading: the residual is not an error, it is a *known term*
#
# The residual grows with the forward dispersion, and that is exactly what
# theory says it must do. The pack rate is an **equally weighted** mean of four
# quarterly forwards; the matched swap's par rate is the **annuity-weighted**
# one, `par = Σ w_i f_i` with `w_i ∝ DF_i·τ_i`. Later quarters discount harder
# and carry slightly less than 1/4, so on an inverted strip the arithmetic mean
# sits *below* par and the residual is negative — which is the sign the sample
# shows, because the SOFR strip was inverted through 2022-2023.
#
# `ca_diagnostics.annuity_weight_residual_bp` predicts that term from the four
# forwards and the swap rate alone, with no fitting. Comparing the prediction
# against the measurement converts "the residual is small" into "the residual is
# the term it should be, and what is left over is smaller still".

# %%
pred_ok = df[df.curve_ok]
_c = float(np.corrcoef(pred_ok["ca_synthetic_bp"], pred_ok["ca_synthetic_pred_bp"])[0, 1])
_slope, _icept = np.polyfit(pred_ok["ca_synthetic_pred_bp"], pred_ok["ca_synthetic_bp"], 1)
left = pred_ok["ca_synthetic_bp"] - pred_ok["ca_synthetic_pred_bp"]
print(f"predicted annuity-weighting term vs measured CA_synthetic (post-break, "
      f"n={len(pred_ok):,})")
print(f"   correlation {_c:.4f}   regression slope {_slope:.4f} (ideal 1.0), "
      f"intercept {_icept:+.5f}bp")
print(pd.DataFrame([
    describe_bp(pred_ok["ca_synthetic_bp"], "CA_synthetic (measured)"),
    describe_bp(pred_ok["ca_synthetic_pred_bp"], "annuity term (predicted)"),
    describe_bp(left, "what is LEFT OVER"),
]).round(4).to_string())
print(f"\nRemoving a term with no free parameters takes the mean residual from "
      f"{pred_ok.ca_synthetic_bp.mean():+.4f}bp to {left.mean():+.4f}bp and the sd from "
      f"{pred_ok.ca_synthetic_bp.std():.4f} to {left.std():.4f}. The slope of "
      f"{_slope:.2f} rather than exactly 1.00 is the crude exp(-r·t) discount-factor "
      f"approximation inside the predictor, not a residual convention error.")
print("\nSo the honest statement of test (a) is not 'the control returns zero'. It is: "
      "the control returns the annuity-weighting term, correctly signed by the slope of "
      "the strip and correctly sized by r·tau, and nothing else above ~0.45bp at p95.")


# %% [markdown]
# ## (a) The zero-convexity control at scale
#
# **The headline evidence.** Recompute the identical arithmetic with the four
# quarterly rates taken from the swap curve's own IMM×IMM forwards instead of
# from futures. Those forwards come off the same discount curve the swap leg is
# priced on, so they carry no convexity adjustment by construction:
#
# ```
# CA_synthetic = mean(fwd_OIS[IMM_i, IMM_i+1]) - par_rate(matched 1y swap)
# ```
#
# must be zero. Whatever it returns is our own convention error — arithmetic
# mean versus the annuity-weighted average a par rate actually is, plus any
# day-count, frequency or date-roll mismatch — measured with **no external
# reference at all**.

# %%
ctrl = pd.DataFrame([
    describe_bp(df["ca_synthetic_bp"], "all 11,900 rows"),
    describe_bp(df[df.curve_ok]["ca_synthetic_bp"], "post-break"),
    describe_bp(df[df.curve_ok & df.has_power]["ca_synthetic_bp"], "post-break, control has power"),
    describe_bp(df[df.curve_ok & (df.fwd_spread_bp > 25)]["ca_synthetic_bp"], "post-break, power >25bp"),
    describe_bp(df["ca_observed_bp"], "CA_OBSERVED (for scale)"),
])
print("CA_synthetic — the convention residual, bp")
print(ctrl.round(4).to_string())

h = df[df.curve_ok & (df["ca_observed_bp"].abs() > 1.0)]
share = (h["ca_synthetic_bp"].abs() / h["ca_observed_bp"].abs())
print(f"\nresidual as a share of |CA_observed| (post-break, |CA|>1bp, n={len(h):,}):")
print(f"   median {share.median():.4f}   mean {share.mean():.4f}   "
      f"p95 {share.quantile(0.95):.4f}   p99 {share.quantile(0.99):.4f}")

# %%
print("CA_synthetic by pack rank (post-break)")
by_rank = df[df.curve_ok].groupby("rank").agg(
    n=("ca_synthetic_bp", "size"), mean=("ca_synthetic_bp", "mean"),
    median=("ca_synthetic_bp", "median"), sd=("ca_synthetic_bp", "std"),
    abs_p95=("ca_synthetic_bp", lambda s: float(s.abs().quantile(0.95))),
    control_power_bp=("fwd_spread_bp", "median"),
    ca_observed_med=("ca_observed_bp", "median"))
by_rank["residual_share"] = (by_rank["abs_p95"] / by_rank["ca_observed_med"].abs())
print(by_rank.round(4).to_string())

print("\nCA_synthetic by year")
by_year = df.groupby("year").agg(
    n=("ca_synthetic_bp", "size"), mean=("ca_synthetic_bp", "mean"),
    median=("ca_synthetic_bp", "median"), sd=("ca_synthetic_bp", "std"),
    abs_p95=("ca_synthetic_bp", lambda s: float(s.abs().quantile(0.95))),
    control_power_bp=("fwd_spread_bp", "median"),
    ca_observed_med=("ca_observed_bp", "median"))
print(by_year.round(4).to_string())
print("\nNOTE the 2019-2020 rows: a residual near zero there is mostly the flat-curve "
      "artefact of Test 0, not a stronger result. The 2022-2023 rows, where the median "
      "control power is 33-55bp, are the ones that carry the evidence.")

# %%
_g = df[df.curve_ok]
fig = make_subplots(rows=1, cols=2, subplot_titles=(
    "CA_synthetic distribution (post-break)",
    "control residual vs control power"))
fig.add_trace(go.Histogram(x=_g["ca_synthetic_bp"].clip(-1.5, 1.5), nbinsx=90,
                           name="CA_synthetic", marker_color="#3b6ea5"), row=1, col=1)
_s = _g.sample(min(4000, len(_g)), random_state=0)
fig.add_trace(go.Scatter(x=_s["fwd_spread_bp"], y=_s["ca_synthetic_bp"], mode="markers",
                         marker=dict(size=3, opacity=0.35, color="#a5553b"),
                         name="pack-day"), row=1, col=2)
fig.update_xaxes(title_text="bp", row=1, col=1)
fig.update_xaxes(title_text="spread of the pack's 4 synthetic forwards, bp", type="log", row=1, col=2)
fig.update_yaxes(title_text="CA_synthetic, bp", row=1, col=2)
fig.update_layout(height=380, showlegend=False,
                  title_text="(a) the zero-convexity control, and how much it was allowed to see")
fig.show()


# %% [markdown]
# ## (b) Quarterly versus annual matched swap
#
# Citi specifies the matched swap's frequency verbatim. The `usd_irs` rateslib
# spec this curve carries quotes **annual** fixed. The gap is not a rounding
# detail — it is a *prediction* with no free parameter.
#
# A 1y swap paying `a` annually is equivalent to one paying `q` quarterly when
# `(1 + q/4)^4 = 1 + a`, so `a = q + (6/16)q² + O(q³)` and
#
# ```
# gap_bp = 0.375 * (rate in percent)^2
# ```
#
# 9.38bp at 5%, 4.34bp at 3.4%. Regressed, not asserted.

# %%
reg = CAD.regress_gap_on_rate_squared(df["annual_qq_gap_bp"], df["swap_rate_qq"])
print("OLS   annual_qq_gap_bp  ~  b * (swap_rate_pct)^2")
print(f"   slope (no intercept) {reg['slope_no_intercept']:.6f}   "
      f"PREDICTED {CAD.COMPOUNDING_GAP_SLOPE}   "
      f"error {100*(reg['slope_no_intercept']/CAD.COMPOUNDING_GAP_SLOPE - 1):+.2f}%")
print(f"   with intercept: slope {reg['slope']:.6f}  intercept {reg['intercept']:+.6f}bp  "
      f"r2 {reg['r2']:.6f}   n {int(reg['n']):,}")

df["gap_predicted_bp"] = CAD.compounding_gap_bp(df["swap_rate_qq"])
resid = df["annual_qq_gap_bp"] - df["gap_predicted_bp"]
print("\nresidual  gap - 0.375*r^2  (bp)")
print(describe_bp(resid, "residual").round(4).to_string())

buck = df.copy()
buck["rate_bucket"] = pd.cut(buck["swap_rate_qq"], [-1, 0.5, 1, 2, 3, 4, 5, 10])
print("\nby rate level")
print(buck.groupby("rate_bucket", observed=True).agg(
    n=("annual_qq_gap_bp", "size"), rate_med=("swap_rate_qq", "median"),
    gap_measured=("annual_qq_gap_bp", "median"),
    gap_predicted=("gap_predicted_bp", "median")).round(4).to_string())

print("\nwhat using the spec default would do to the adjustment")
print(df.groupby("year").apply(
    lambda x: pd.Series({"mean_bias_bp": (x.ca_annual_bp - x.ca_observed_bp).mean(),
                         "median_bias_bp": (x.ca_annual_bp - x.ca_observed_bp).median(),
                         "worst_bias_bp": (x.ca_annual_bp - x.ca_observed_bp).min()}),
    include_groups=False).round(3).to_string())
print(f"\nfull sample mean bias {float((df.ca_annual_bp - df.ca_observed_bp).mean()):+.3f}bp, "
      f"worst {float((df.ca_annual_bp - df.ca_observed_bp).min()):+.3f}bp.")
print("The gap SCALES WITH THE RATE LEVEL, so it is invisible in 2020-2021 "
      "(rates near zero) and 5-12bp in 2023. A convention error that hides in "
      "the calm regime and detonates in the live one.")

# %%
_s = df.sample(min(6000, len(df)), random_state=0)
_x = np.linspace(0, float(df["swap_rate_qq"].max()) * 1.02, 100)
fig = go.Figure()
fig.add_trace(go.Scatter(x=_s["swap_rate_qq"], y=_s["annual_qq_gap_bp"], mode="markers",
                         marker=dict(size=3, opacity=0.3, color="#3b6ea5"), name="pack-day"))
fig.add_trace(go.Scatter(x=_x, y=CAD.compounding_gap_bp(_x), mode="lines",
                         line=dict(color="#c0392b", width=2.5),
                         name="0.375·r²  (predicted, no free parameter)"))
fig.update_layout(height=400, xaxis_title="matched swap rate, %",
                  yaxis_title="annual − quarterly par rate, bp",
                  title_text="(b) the annual/quarterly gap is r², predicted not fitted")
fig.show()


# %% [markdown]
# ## (c) No-arbitrage violations
#
# The futures rate must exceed the matched forward: the convexity adjustment is
# a variance and cannot be negative. `CA < 0` is not a tolerance breach, it is
# an impossibility, and it is the single most useful automatic filter.
#
# The question this section answers is **whether the violations are convention
# or data**. The discriminator is the synthetic control on the same rows: if a
# violating row's control is ~0, our arithmetic was fine and the inputs were
# not.

# %%
print(f"CA < 0 overall: {float((df.ca_observed_bp < 0).mean()):.4f}  "
      f"({int((df.ca_observed_bp < 0).sum()):,} rows)")
print(f"CA < 0 post-break: {float((df[df.curve_ok].ca_observed_bp < 0).mean()):.4f}")
print("\nfraction of pack-days with CA < 0, by year x rank")
print(df.pivot_table(index="year", columns="rank", values="ca_observed_bp",
                     aggfunc=lambda s: float((s < 0).mean())).round(3).to_string())

neg = df[df.ca_observed_bp < 0]
print(f"\nOn the {len(neg):,} violating rows, what does the control say?")
print(f"   median |CA_synthetic| = {float(neg.ca_synthetic_bp.abs().median()):.4f} bp")
print(f"   share with |CA_synthetic| < 0.1bp : "
      f"{float((neg.ca_synthetic_bp.abs() < 0.1).mean()):.4f}")
print(f"   share with |CA_synthetic| > 1bp (i.e. convention COULD explain it): "
      f"{float((neg.ca_synthetic_bp.abs() > CFG.max_convention_bp).mean()):.4f} "
      f"({int((neg.ca_synthetic_bp.abs() > CFG.max_convention_bp).sum())} rows)")
print("\n=> 99.6% of no-arbitrage violations sit on rows where our own arithmetic "
      "is verified clean. They are data, not convention.")

# %%
print("worst 12 violations (post-break) — and what the control says on each")
worst = df[df.curve_ok & (df.ca_observed_bp < 0)].nsmallest(12, "ca_observed_bp")
print(worst[["date", "pack", "rank", "ca_observed_bp", "ca_synthetic_bp",
             "fwd_spread_bp", "pack_rate_futures", "swap_rate_qq"]]
      .round(4).to_string(index=False))
print("\nThe cluster is 2020-03-03/04/05 — the emergency 50bp FOMC cut and the "
      "COVID repricing week. SR3 settles ~48bp below the swap curve is not a "
      "convexity sign error; it is two legs snapped hours apart on a day the "
      "market moved 50bp. See test (f2).")

# %%
flags = CAD.flag_quality(df, ca_col="ca_observed_bp", syn_col="ca_synthetic_bp",
                         vol_col="implied_vol_bp", t1_col="t1_first",
                         max_convention_bp=CFG.max_convention_bp)
flags["flag_no_control_power"] = ~df["has_power"].to_numpy()
flags["survive"] = flags["ok"] & ~flags["flag_no_control_power"]
print("filter incidence over all 11,900 pack-days")
for c in ["flag_negative_ca", "flag_convention", "flag_implausible_vol",
          "flag_vol_ill_conditioned", "flag_no_control_power", "ok", "survive"]:
    print(f"   {c:26s} {float(flags[c].mean()):.4f}   ({int(flags[c].sum()):,})")

print("\nsurvival rate by year x rank")
print(flags.pivot_table(index="year", columns="rank", values="survive",
                        aggfunc="mean").round(3).to_string())
print(f"\noverall survival           {float(flags.survive.mean()):.4f}  "
      f"({int(flags.survive.sum()):,}/{len(flags):,})")
print(f"2022-2023 only             {float(flags[flags.year >= 2022].survive.mean()):.4f}")
print(f"2022-2023, rank >= 5       "
      f"{float(flags[(flags.year >= 2022) & (flags['rank'] >= CFG.shape_min_rank)].survive.mean()):.4f}")
print("\nThe filter is not throwing away a third of the sample because it is "
      "strict. It is throwing away 2019-2021, where the curve had no front-end "
      "resolution and rates were pinned at zero so the true adjustment was "
      "genuinely ~0 and its sign was decided by noise.")


# %% [markdown]
# ## (d) Term-structure shape
#
# Ho-Lee makes the adjustment quadratic in expiry, so a log-log regression of CA
# on T1 has slope 2 **under a flat vol**. That last clause matters and is
# usually dropped: a downward-sloping vol term structure flattens the observed
# slope, and Citi's own published table shows exactly that.
#
# So the benchmark is not 2.0 in the abstract — it is **Citi's own printed
# slope**, computed here from Figure 58.

# %%
CITI_FIG58 = {"M4-H5": (4.03, 199.5), "U4-M5": (4.41, 178.1), "Z4-U5": (5.16, 167.7),
              "H5-Z5": (6.10, 161.6), "M5-H6": (8.24, 168.5), "U5-M6": (9.77, 166.3),
              "Z5-U6": (11.70, 166.5), "H6-Z6": (13.70, 166.0), "M6-H7": (15.40, 163.1),
              "U6-M7": (16.84, 159.0), "Z6-U7": (18.27, 155.1), "H7-Z7": (20.08, 152.8),
              "M7-H8": (22.29, 151.9)}
_seq = quarterly_imm_sequence(CFG.citi_as_of, 21)
_rows = [(pack_label(_seq[k], _seq[k + 3]),
          year_fraction_act365(CFG.citi_as_of, imm_date(*_seq[k])))
         for k in range(len(_seq) - 3)]
_citi = [(t1, CITI_FIG58[lab][0]) for lab, t1 in _rows if lab in CITI_FIG58]
_ct1 = np.array([a for a, _ in _citi]); _cca = np.array([b for _, b in _citi])
citi_slope = float(np.polyfit(np.log(_ct1), np.log(_cca), 1)[0])
citi_corr = float(np.corrcoef(_ct1 ** 2, _cca)[0, 1])
print(f"Citi's OWN Figure 58 (13 rows, T1 {_ct1.min():.2f}-{_ct1.max():.2f}y):")
print(f"   log-log slope {citi_slope:.4f}   corr(CA, T1^2) {citi_corr:.4f}")
print(f"   over its first 6 rows (our rank range): "
      f"{float(np.polyfit(np.log(_ct1[:6]), np.log(_cca[:6]), 1)[0]):.4f}")
print("Ho-Lee's flat-vol prediction is 2.0; Citi prints 1.38 because its own "
      "implied vols fall 199.5 -> 151.9 across the table. The shape test is a "
      "test against ~1.2-1.4, not against 2.0.")

# %%
def shape_per_date(g):
    return pd.Series(CAD.shape_diagnostics(g, ca_col="ca_observed_bp", t1_col="t1_first"))


sub = df[df.curve_ok & (df["rank"] >= CFG.shape_min_rank)]
sh = sub.groupby("date").apply(shape_per_date, include_groups=False)
sh["year"] = sh.index.year
print(f"per-date shape on rank >= {CFG.shape_min_rank}, post-break "
      f"({len(sh):,} dates)")
print(sh.groupby("year").agg(
    dates=("loglog_slope", "size"),
    slope_p25=("loglog_slope", lambda s: s.quantile(0.25)),
    slope_med=("loglog_slope", "median"),
    slope_p75=("loglog_slope", lambda s: s.quantile(0.75)),
    corr_med=("corr_t1_squared", "median"),
    pts_med=("n", "median")).round(3).to_string())
print(f"\nALL post-break dates: slope median {sh.loglog_slope.median():.3f} "
      f"(IQR {sh.loglog_slope.quantile(.25):.3f} - {sh.loglog_slope.quantile(.75):.3f}), "
      f"corr(CA,T1^2) median {sh.corr_t1_squared.median():.4f}")

shp = df[~df.curve_ok].groupby("date").apply(shape_per_date, include_groups=False)
print(f"PRE-break dates ({len(shp)}): slope median {shp.loglog_slope.median():.3f}, "
      f"corr median {shp.corr_t1_squared.median():.3f}   <- no Ho-Lee shape at all")
_citi6 = float(np.polyfit(np.log(_ct1[:6]), np.log(_cca[:6]), 1)[0])
print(f"\nLIKE FOR LIKE. Our rank 5-10 spans T1 {sub.t1_first.min():.2f}-"
      f"{sub.t1_first.max():.2f}y; Citi's first six rows span {_ct1[0]:.2f}-{_ct1[5]:.2f}y. "
      f"Over that matched span Citi's own printed slope is {_citi6:.3f} and our 2023 "
      f"median is {sh[sh.year == 2023].loglog_slope.median():.3f} — a difference of "
      f"{abs(sh[sh.year == 2023].loglog_slope.median() - _citi6):.3f}.")
print(f"Compared against the FULL 13-row Citi slope of {citi_slope:.3f} (T1 out to "
      f"{_ct1.max():.2f}y) it would look like a miss; it is a maturity-range artefact. "
      "The slope steepens with T1 because the vol term structure flattens out there.")
print("\n2020-2021 is a different matter: rates were pinned near zero, the true "
      "adjustment was ~0, and its cross-sectional shape was decided by noise "
      f"(2021 slope median {sh[sh.year == 2021].loglog_slope.median():.2f}). Those "
      "years are not a shape failure of the implementation; they are a period in "
      "which there was no shape to measure.")

# %%
fig = make_subplots(rows=1, cols=2, subplot_titles=(
    "per-date log-log slope of CA on T1", "per-date corr(CA, T1²)"))
for lab, gg, col in [("post-break", sh, "#3b6ea5"), ("pre-break", shp, "#c0392b")]:
    fig.add_trace(go.Histogram(x=gg["loglog_slope"].clip(-4, 6), nbinsx=70, name=lab,
                               opacity=0.65, marker_color=col), row=1, col=1)
    fig.add_trace(go.Histogram(x=gg["corr_t1_squared"], nbinsx=50, name=lab,
                               opacity=0.65, marker_color=col, showlegend=False), row=1, col=2)
fig.add_vline(x=citi_slope, line=dict(color="black", dash="dash"), row=1, col=1)
fig.add_vline(x=2.0, line=dict(color="grey", dash="dot"), row=1, col=1)
fig.update_layout(height=380, barmode="overlay",
                  title_text="(d) Ho-Lee shape — dashed = Citi's own printed slope, "
                             "dotted = flat-vol 2.0")
fig.show()


# %% [markdown]
# ## (e) Implied-vol conditioning — where the inversion stops working
#
# `sigma = sqrt(2·CA/M)` so `dsigma/dCA = sigma/(2·CA)`. The inversion's gain is
# inversely proportional to the size of the thing being inverted. Near packs are
# unusable not because `T1` is small in itself but because **CA is tiny there**,
# so a fraction of a basis point of settle noise becomes hundreds of basis
# points of vol.
#
# This section derives the minimum usable pack rank from the measured noise
# (section f2) rather than from Citi's convention of starting at Reds.

# %%
def daily_diff_frames(g):
    """Wide (date x pack) daily differences, gap-aware."""
    ca = g.pivot_table(index="date", columns="pack", values="ca_observed_bp", aggfunc="last")
    pr = g.pivot_table(index="date", columns="pack", values="pack_rate_futures",
                       aggfunc="last") * 100.0
    rk = g.pivot_table(index="date", columns="pack", values="rank", aggfunc="last")
    gap = pd.Series(ca.index).diff().dt.days.to_numpy()
    keep = pd.DataFrame(np.repeat((gap <= CFG.max_business_day_gap).reshape(-1, 1),
                                  ca.shape[1], axis=1), index=ca.index, columns=ca.columns)
    return ca.diff().where(keep), pr.diff().where(keep), rk


def noise_table(g, label):
    """Per-rank CA measurement noise, two estimators, plus its vol consequence.

    ``ub``   sd(dCA)/sqrt(2). Valid upper bound: Var(dCA) = Var(dTrue) + 2Var(e).
    ``roll`` the MA(1)/Roll estimator, sqrt(-gamma_1) of the daily change --
             a point estimate rather than a bound, degenerate (NaN) when the
             lag-1 autocovariance is positive.
    """
    dca, _, rk = daily_diff_frames(g)
    rows = []
    for r in range(1, int(g["rank"].max()) + 1):
        sel = rk == r
        flat = dca.where(sel).stack().dropna()
        g1 = []
        for col in dca.columns:
            s = dca[col].where(rk[col] == r).dropna()
            if len(s) > 30:
                g1.append(np.cov(s.to_numpy()[1:], s.to_numpy()[:-1])[0, 1])
        gam = float(np.nanmean(g1)) if g1 else np.nan
        roll = float(np.sqrt(-gam)) if (gam == gam and gam < 0) else np.nan
        var_true = flat.var() + 2 * gam if gam == gam else np.nan
        rows.append({"rank": r, "sd_dCA_bp": flat.std(), "noise_ub_bp": flat.std() / np.sqrt(2),
                     "noise_roll_bp": roll,
                     "sd_true_daily_bp": np.sqrt(var_true) if (var_true == var_true and var_true > 0) else 0.0})
    t = pd.DataFrame(rows).set_index("rank")
    t["t1_first"] = g.groupby("rank")["t1_first"].median()
    t["ca_med_bp"] = g.groupby("rank")["ca_observed_bp"].median()
    t["iv_med_bp"] = g.groupby("rank")["implied_vol_bp"].median()
    t["dsigma_dca"] = g.groupby("rank")["dsigma_dca"].median()
    t["noise"] = t["noise_roll_bp"].fillna(t["noise_ub_bp"])
    t["vol_noise_bp"] = t["noise"] * t["dsigma_dca"]
    t["vol_noise_pct"] = t["vol_noise_bp"] / t["iv_med_bp"]
    t["noise_over_ca"] = t["noise"] / t["ca_med_bp"]
    print(f"\n--- {label}")
    print(t.drop(columns=["noise"]).round(3).to_string())
    return t


nt_all = noise_table(df[df.curve_ok], "post-break, full sample")
nt_live = noise_table(df[df.curve_ok & (df.year >= 2022)],
                      "post-break, 2022-2023 (rates off the floor — the live regime)")

# %%
budget = CFG.vol_noise_budget
elig = nt_live[nt_live["vol_noise_pct"] <= budget]
print(f"Minimum pack rank for vol inversion, derived from THIS data")
print(f"   criterion: induced vol noise <= {budget:.0%} of the vol level")
print(f"   2022-2023 measurement: rank 1 = {nt_live.loc[1,'vol_noise_pct']:.1%}, "
      f"rank 5 = {nt_live.loc[5,'vol_noise_pct']:.1%}, "
      f"rank 8 = {nt_live.loc[8,'vol_noise_pct']:.1%}")
print(f"   -> first rank meeting the budget: "
      f"{int(elig.index.min()) if len(elig) else 'none'} "
      f"(T1 ~ {nt_live.loc[int(elig.index.min()), 't1_first']:.2f}y)"
      if len(elig) else "   -> no rank in this window meets the budget")
print(f"\n   Citi starts its published table at Reds = rank 5, T1 ~ "
      f"{nt_live.loc[5, 't1_first']:.2f}y, which on this data is a "
      f"{nt_live.loc[5, 'vol_noise_pct']:.0%} vol-noise budget. Its convention is "
      f"the loose end of what the data supports, not the tight end.")
print("\n   CAVEAT, stated because it flatters the deep packs otherwise: ranks 9-10 "
      "show much smaller sd(dCA) than ranks 5-8. Their matched swap sits inside a "
      "single ~367-day node segment (see segment_days below), so the swap leg is a "
      "smooth interpolation of two annual nodes and cannot move independently. That "
      "is reduced independent information, not a better measurement.")
print(df[df.curve_ok & (df.year >= 2022)].groupby("rank")[
    ["n_nodes_inside", "segment_days"]].median().round(1).to_string())

# %%
fig = make_subplots(specs=[[{"secondary_y": True}]])
fig.add_trace(go.Bar(x=nt_live.index, y=nt_live["vol_noise_bp"],
                     name="induced vol noise, bp", marker_color="#c0392b", opacity=0.8))
fig.add_trace(go.Scatter(x=nt_live.index, y=nt_live["iv_med_bp"], name="median implied vol, bp",
                         mode="lines+markers", line=dict(color="#3b6ea5", width=2.5)))
fig.add_trace(go.Scatter(x=nt_live.index, y=nt_live["vol_noise_pct"], name="noise / vol",
                         mode="lines+markers", line=dict(color="black", dash="dash")),
              secondary_y=True)
fig.add_hline(y=budget, line=dict(color="grey", dash="dot"), secondary_y=True)
fig.update_xaxes(title_text="pack rank (1 = Whites, 5 = Reds)")
fig.update_yaxes(title_text="bp of normal vol", secondary_y=False)
fig.update_yaxes(title_text="fraction", secondary_y=True, range=[0, 0.8])
fig.update_layout(height=400, title_text="(e) the vol inversion's signal-to-noise by rank, 2022-2023")
fig.show()


# %% [markdown]
# ## (f1) Cross-source — Barchart settles versus the futures-bootstrapped curve
#
# `USD-SOFR-1D-Q12STIRT` is bootstrapped **from SOFR futures** with
# `rl.STIRFuture` instruments carrying **no convexity adjustment** and a solver
# weight of 1e6, so its IMM×IMM forwards should reproduce the settles almost
# exactly. Where they do not, one of the two is broken — and this test says
# which.

# %%
q = df.dropna(subset=["pack_rate_q12"]).copy()
print("futures pack rate − Q12STIRT forward pack rate, bp")
print(q.groupby("year").agg(
    n=("futures_vs_q12_bp", "size"), median=("futures_vs_q12_bp", "median"),
    mean=("futures_vs_q12_bp", "mean"), sd=("futures_vs_q12_bp", "std"),
    abs_median=("futures_vs_q12_bp", lambda s: float(s.abs().median())),
    q12_nodes_inside=("n_q12_nodes_inside", "median")).round(3).to_string())

for lab, g in [("2019", q[q.year == 2019]), ("2020", q[q.year == 2020]),
               ("2021-2023", q[q.year >= 2021])]:
    print(f"  {lab:10s} corr(pack_fut, pack_q12) = "
          f"{np.corrcoef(g.pack_rate_futures, g.pack_rate_q12)[0,1]:.4f}   "
          f"corr(CA_obs, CA_q12) = {np.corrcoef(g.ca_observed_bp, g.ca_q12_bp)[0,1]:.3f}   "
          f"median |disagreement| = {g.futures_vs_q12_bp.abs().median():.3f}bp")

print("\nWHY 2019 disagrees by ~9.4bp — the mechanism, not a hand-wave:")
print(q[q.year == 2019].groupby("rank").agg(
    q12_nodes_inside=("n_q12_nodes_inside", "median"),
    sofr1d_nodes_inside=("n_nodes_inside", "median"),
    fut_minus_q12_bp=("futures_vs_q12_bp", "median")).round(2).to_string())
print("\nThe Q12STIRT curve inherits its node grid from USD-SOFR-1D, which in "
      "H1-2019 is 26 nodes with the second at start+735d. On 2019-03-15 that "
      "curve has TWELVE nodes and its second is 2021-03-17: it has zero degrees "
      "of freedom in the first two years and physically cannot fit thirteen "
      "quarterly futures however hard the solver is weighted. Its front-end "
      "forwards print a constant 2.3147% while the SR3 strip declines "
      "2.4300 -> 2.1450.")
print("\nWHICH IS WRONG: the curve, and the argument is mechanical, not statistical.")
print("  1. The Q12STIRT bootstrap's calibration instruments ARE these settles "
      "(SFRCM1..13 as rl.STIRFuture, no convexity term, solver weight 1e6). "
      "Reproducing them is its job, not a coincidence.")
print(f"  2. In 2021-2023 it does the job: corr(pack_fut, pack_q12) = "
      f"{np.corrcoef(q[q.year>=2021].pack_rate_futures, q[q.year>=2021].pack_rate_q12)[0,1]:.4f}, "
      f"median disagreement {float(q[q.year>=2021].futures_vs_q12_bp.abs().median()):.2f}bp.")
print("  3. In 2019 it misses by 9.4bp on rows where it has ZERO nodes inside the "
      "window (table above). A curve with no degrees of freedom cannot price its "
      "own calibration instruments however hard the solver is weighted.")
print("  => the settles are the primary observable; the curve is a derived object "
      "that failed to fit them. The 2019 disagreement is a curve-construction "
      "artefact, and it is the SAME artefact Test 0 found.")

print("\nA WARNING about the two criteria one is tempted to use instead — they do "
      "NOT discriminate here, and it is worth showing why:")
for lab, g in [("2019", q[q.year == 2019]), ("2021-2023", q[q.year >= 2021])]:
    sf = g.groupby("date").apply(
        lambda x: pd.Series(CAD.shape_diagnostics(x, ca_col="ca_observed_bp", t1_col="t1_first")),
        include_groups=False)
    sq = g.groupby("date").apply(
        lambda x: pd.Series(CAD.shape_diagnostics(x, ca_col="ca_q12_bp", t1_col="t1_first")),
        include_groups=False)
    print(f"  {lab:10s} CA<0 rate: futures {float((g.ca_observed_bp<0).mean()):.3f} vs "
          f"q12 {float((g.ca_q12_bp<0).mean()):.3f}   |   "
          f"corr(CA,T1^2) median: futures {sf.corr_t1_squared.median():+.3f} vs "
          f"q12 {sq.corr_t1_squared.median():+.3f}")
print("\nIn 2019 the Q12 version scores BETTER on both — fewer sign violations and a "
      "far cleaner T1^2 shape (+0.83 vs -0.21). That is not evidence it is right. A "
      "curve flattened by missing nodes produces a CA that is ~0 at the front (where "
      "it is flat) and tracks the futures at the back (where it has nodes), which "
      "manufactures a monotone, non-negative profile out of nothing. "
      "**Sign and shape criteria reward a degenerate curve.** Only the node count "
      "and the fit-to-instrument test settle it.")


# %% [markdown]
# ## (f2) Timing sensitivity — how much noise the snapshot mismatch injects
#
# The Barchart "EOD" bar is the one **nearest 17:00 New York**, not the CME
# settle at 15:00 ET, and the Citi Velocity curve is a separate snapshot again.
# Two legs of a small difference marked at different instants is a measurement
# error, and this bounds it.
#
# Two estimates, deliberately: a crude hard bound and a sharp one.

# %%
_ok = df[df.curve_ok]
w = _ok.pivot_table(index="date", columns="pack", values="pack_rate_futures", aggfunc="last")
s = _ok.pivot_table(index="date", columns="pack", values="swap_rate_qq", aggfunc="last")
rkw = _ok.pivot_table(index="date", columns="pack", values="rank", aggfunc="last")
base = (w - s) * 100.0
parts = []
for k in (-1, 1):
    d_ = ((w.shift(-k) - s) * 100.0 - base)
    parts.append(d_.stack().rename("d").reset_index()
                 .merge(rkw.stack().rename("rank").reset_index(), on=["date", "pack"]))
shifted = pd.concat(parts)
print("HARD BOUND — futures snapshot moved a full business day against a fixed curve")
print(shifted.groupby("rank")["d"].agg(
    n="size", sd="std", abs_median=lambda x: float(x.abs().median()),
    abs_p95=lambda x: float(x.abs().quantile(0.95))).round(3).to_string())
print(f"   pooled sd {float(shifted.d.std()):.3f} bp")
_, dpr, _ = daily_diff_frames(_ok)
print(f"   this is simply one day of pack-rate volatility: sd(daily pack-rate change) "
      f"= {float(dpr.stack().std()):.3f} bp. A 24h desynchronisation is a gross "
      f"over-statement of a ~2h one.")

print("\nSHARP BOUND — from the CA's own daily change (2022-2023, the live regime)")
print(nt_live[["sd_dCA_bp", "noise_ub_bp", "noise_roll_bp", "sd_true_daily_bp",
               "ca_med_bp"]].round(3).to_string())
print("\n   sd(dCA)/sqrt(2) is a valid upper bound on the per-observation noise "
      "because Var(dCA) = Var(dTrue) + 2Var(e). The Roll/MA(1) estimator agrees "
      "with it to ~2-5%, which means the observed daily CA change is nearly all "
      "measurement noise: the true adjustment moves "
      f"{float(nt_live.sd_true_daily_bp.median()):.2f}bp/day against a noise of "
      f"{float(nt_live.noise_roll_bp.median()):.2f}bp/day.")
print(f"\n   INDUCED CA MEASUREMENT ERROR, ranks 1-8: "
      f"{float(nt_live.loc[1:8, 'noise_roll_bp'].min()):.2f} - "
      f"{float(nt_live.loc[1:8, 'noise_roll_bp'].max()):.2f} bp per pack-day "
      f"(mean {float(nt_live.loc[1:8, 'noise_roll_bp'].mean()):.2f}bp), against median CA "
      f"levels of {float(nt_live.loc[1:8, 'ca_med_bp'].min()):.2f}-"
      f"{float(nt_live.loc[1:8, 'ca_med_bp'].max()):.2f}bp.")
print(f"   Ranks 9-10 read lower ({float(nt_live.loc[9:10, 'noise_roll_bp'].min()):.2f}-"
      f"{float(nt_live.loc[9:10, 'noise_roll_bp'].max()):.2f}bp) but see the caveat in (e): "
      f"their swap leg is interpolated across one ~365-day node segment and cannot "
      f"move independently, so that is less information, not less error.")
print("   That is the number that decides tradeability, and it is why the "
      "2020-03-03 cluster of -48bp violations is a timing artefact rather than "
      "a broken formula: on a day the market moved 50bp, a two-hour mismatch IS "
      "tens of basis points.")

# %%
fig = go.Figure()
fig.add_trace(go.Bar(x=nt_live.index, y=nt_live["noise_ub_bp"],
                     name="noise upper bound  sd(ΔCA)/√2", marker_color="#c0392b", opacity=0.55))
fig.add_trace(go.Bar(x=nt_live.index, y=nt_live["noise_roll_bp"],
                     name="noise, Roll MA(1) estimator", marker_color="#a5553b"))
fig.add_trace(go.Scatter(x=nt_live.index, y=nt_live["ca_med_bp"], mode="lines+markers",
                         name="median CA level", line=dict(color="#3b6ea5", width=3)))
fig.update_layout(height=400, barmode="overlay",
                  xaxis_title="pack rank", yaxis_title="bp",
                  title_text="(f2) measured CA noise against the CA level, 2022-2023")
fig.show()


# %% [markdown]
# ## (g) The Citi tie-out — the external anchor
#
# Figure 58, [VL-SOFR] p.14, close **6/9/2023**, all 13 rows. This date needs
# contracts out to H8, i.e. a 21-contract strip, so it is computed here directly
# rather than read from the 13-contract daily scan.
#
# Tolerance is deliberately loose on any single row: Citi's swap leg is
# CME-cleared and `USD-SOFR-1D` is not, and Citi's futures snapshot is the CME
# 15:00 ET settle against Barchart's 17:00 NY bar. The tight statements are the
# **mean error** and the **correlation**.

# %%
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP
from RVUtils.ConvexityRV.curve_ops import matched_forward_swap_rate
from RVUtils.ConvexityRV.strat2_sofr_convexity import futures_symbol

_d = CFG.citi_as_of
_seq21 = quarterly_imm_sequence(_d, 21)
_syms = [futures_symbol(y, m) for y, m in _seq21]
_snap = STIRFutureMDP(source="BARCHART_STIRF-RL").get_data(
    {"symbols": _syms, "timestamp": _d})
_px = {ym: float(_snap[sy][0].price()) for ym, sy in zip(_seq21, _syms) if _snap.get(sy)}
_pricer = IRSwapsMDP(source="CITIVELO_EXCEL").get_pricer(
    {"curve_name": "USD-SOFR-1D", "timestamp": _d, "offline": True})
_fwd = CAD.imm_forward_map(_pricer, _seq21)
_nodes = CAD.curve_nodes(_pricer)

_tie = []
for k in range(len(_seq21) - 3):
    cts = tuple(_seq21[k:k + 4])
    lab = pack_label(cts[0], cts[-1])
    if lab not in CITI_FIG58:
        continue
    st, en = matched_swap_dates(cts)
    qq = matched_forward_swap_rate(_pricer, st, en)
    an = matched_forward_swap_rate(_pricer, st, en, frequency=None, leg2_frequency=None)
    pf = float(np.mean([100.0 - _px[c] for c in cts]))
    ps = float(np.mean([_fwd[c] for c in cts]))
    t1s = pack_t1s(_d, cts)
    ca, syn = (pf - qq) * 100.0, (ps - qq) * 100.0
    cca, civ = CITI_FIG58[lab]
    _tie.append({"pack": lab, "citi_CA": cca, "our_CA_qq": ca, "delta_qq": ca - cca,
                 "our_CA_annual": (pf - an) * 100.0, "delta_annual": (pf - an) * 100.0 - cca,
                 "CA_synthetic": syn, "citi_IV": civ,
                 "our_IV": implied_vol_from_ca_bp(ca, t1s),
                 "IV_ratio": implied_vol_from_ca_bp(ca, t1s) / civ,
                 "nodes_inside": CAD.window_resolution(_nodes, st, en)["n_nodes_inside"]})
tie = pd.DataFrame(_tie).set_index("pack")
print(f"Citi Figure 58 tie-out, {_d}, {len(tie)}/13 rows")
print(tie.round(3).to_string())

# %%
print(f"\nQUARTERLY/QUARTERLY (Citi's stated convention)")
print(f"   mean delta {tie.delta_qq.mean():+.3f}bp   median {tie.delta_qq.median():+.3f}bp   "
      f"sd {tie.delta_qq.std():.3f}   |max| {tie.delta_qq.abs().max():.3f}")
print(f"   correlation with Citi's 13 rows: {np.corrcoef(tie.citi_CA, tie.our_CA_qq)[0,1]:.4f}")
print(f"   rows within +/-{CFG.citi_tolerance_bp}bp: "
      f"{int((tie.delta_qq.abs() <= CFG.citi_tolerance_bp).sum())}/{len(tie)}")
print(f"   no-arbitrage violations: {int((tie.our_CA_qq < 0).sum())}/{len(tie)}")
print(f"\nANNUAL (the usd_irs spec default — the NEGATIVE CONTROL)")
print(f"   mean delta {tie.delta_annual.mean():+.3f}bp   median {tie.delta_annual.median():+.3f}bp")
print(f"   rows within +/-{CFG.citi_tolerance_bp}bp: "
      f"{int((tie.delta_annual.abs() <= CFG.citi_tolerance_bp).sum())}/{len(tie)}")
print(f"\nZERO-CONVEXITY CONTROL on the tie-out date: mean {tie.CA_synthetic.mean():+.4f}bp, "
      f"|max| {tie.CA_synthetic.abs().max():.4f}bp")
print(f"IMPLIED VOL ours/Citi: min {tie.IV_ratio.min():.4f}  median {tie.IV_ratio.median():.4f}  "
      f"max {tie.IV_ratio.max():.4f}")

assert abs(tie.delta_qq.mean()) < 1.0, tie.delta_qq.mean()
assert np.corrcoef(tie.citi_CA, tie.our_CA_qq)[0, 1] > 0.95
assert int((tie.our_CA_qq < 0).sum()) == 0
assert abs(tie.delta_annual.mean()) > 3.0, "annual control must FAIL — else the test is vacuous"
assert tie.CA_synthetic.abs().max() < CFG.max_convention_bp
print("\nASSERTS PASSED — including the negative control: the annual variant must "
      "and does fail by ~4bp, so the quarterly result is not a coincidence.")

# %%
fig = go.Figure()
fig.add_trace(go.Scatter(x=tie.citi_CA, y=tie.our_CA_qq, mode="markers+text",
                         text=tie.index, textposition="top left",
                         marker=dict(size=9, color="#3b6ea5"), name="quarterly/quarterly"))
fig.add_trace(go.Scatter(x=tie.citi_CA, y=tie.our_CA_annual, mode="markers",
                         marker=dict(size=8, color="#c0392b", symbol="x"),
                         name="annual (spec default — the bug)"))
_lim = [0, float(tie.citi_CA.max()) * 1.1]
fig.add_trace(go.Scatter(x=_lim, y=_lim, mode="lines", line=dict(color="black", dash="dash"),
                         name="y = x"))
fig.update_layout(height=440, xaxis_title="Citi Figure 58 CA, bp",
                  yaxis_title="our CA, bp",
                  title_text="(g) Citi tie-out, 2023-06-09 — and what the annual "
                             "swap frequency does to it")
fig.show()


# %% [markdown]
# ## The bug this report found: the stored strategy panel is the annual variant
#
# `strat2_panel.parquet` is the panel the Strategy-2 backtest consumes. It is
# cross-checked here against this scan — and it reproduces the **annual**
# variant, not the quarterly one, to floating-point exactness on every
# overlapping row.
#
# The current `ca_snapshot` code path is correct. The artifact on disk is stale
# and must be rebuilt before any Strategy-2 number is quoted.

# %%
pan = pd.read_parquet(_REPO / CFG.strategy_panel)
mg = df.merge(pan[["date", "pack", "ca_bp", "swap_rate", "pack_rate"]],
              on=["date", "pack"], how="inner")
print(f"overlapping rows: {len(mg):,}")
print(f"   max |pack_rate_futures − panel pack_rate|  = "
      f"{float((mg.pack_rate_futures - mg.pack_rate).abs().max()):.3e}   (same futures)")
print(f"   max |ca_observed_bp   − panel ca_bp|       = "
      f"{float((mg.ca_observed_bp - mg.ca_bp).abs().max()):.4f} bp   <-- NOT zero")
print(f"   max |ca_annual_bp     − panel ca_bp|       = "
      f"{float((mg.ca_annual_bp - mg.ca_bp).abs().max()):.3e} bp   <-- exact match")
print(f"   max |swap_rate_annual − panel swap_rate|   = "
      f"{float((mg.swap_rate_annual - mg.swap_rate).abs().max()):.3e}")
assert float((mg.ca_annual_bp - mg.ca_bp).abs().max()) < 1e-9
assert float((mg.ca_observed_bp - mg.ca_bp).abs().max()) > 1.0
print("\nThe stored panel IS the annual-frequency computation. Bias by year:")
print(mg.groupby(mg.date.dt.year).apply(
    lambda x: pd.Series({"rows": len(x),
                         "panel_minus_correct_mean_bp": (x.ca_bp - x.ca_observed_bp).mean(),
                         "panel_minus_correct_worst_bp": (x.ca_bp - x.ca_observed_bp).min()}),
    include_groups=False).round(3).to_string())
print("\nAnd what it does on the tie-out date specifically:")
_chk = mg[mg.date == pd.Timestamp(CFG.citi_as_of)][
    ["pack", "rank", "ca_observed_bp", "ca_bp"]].copy()
_chk["bias_bp"] = _chk.ca_bp - _chk.ca_observed_bp
_chk["flips_negative"] = (_chk.ca_observed_bp >= 0) & (_chk.ca_bp < 0)
print(_chk.round(4).to_string(index=False))
print(f"\n{int(_chk.flips_negative.sum())} of {len(_chk)} packs are pushed from a valid "
      "adjustment into a no-arbitrage violation by the frequency alone.")

# %%
fig = go.Figure()
for r, colr in [(1, "#c0392b"), (5, "#3b6ea5"), (10, "#2e7d32")]:
    g = mg[mg["rank"] == r]
    fig.add_trace(go.Scatter(x=g.date, y=g.ca_bp - g.ca_observed_bp, mode="lines",
                             name=f"rank {r}", line=dict(width=1.4, color=colr)))
fig.update_layout(height=360, xaxis_title="", yaxis_title="stored panel − correct CA, bp",
                  title_text="the stored panel's frequency bias through time "
                             "(zero when rates are zero, −9bp when they are 5%)")
fig.show()


# %% [markdown]
# ## (h) What would make this wrong
#
# Ranked by how much CA error each can produce. The first three are measured
# here; the rest are bounded or open.
#
# | # | Failure mode | CA error it can produce | Status |
# |---|---|---|---|
# | 1 | **Swap-leg frequency** — annual instead of quarterly/quarterly | `0.375·r²` bp: **0 at 0%, 4.3bp at 3.4%, 9.4bp at 5%, max 12.0bp measured** | **FOUND LIVE in `strat2_panel.parquet`.** Code path is correct; artifact is stale. Rebuild. Regression-tested by `tests/test_convexity_rv_matched_swap.py`. |
# | 2 | **Discount-curve resolution** — no node inside the pack window | Unbounded. Pre-2019-07-08 the front end is one 735-day log-linear segment; CAs of −7.7 to +10.2bp are pure interpolation, and **the zero-convexity control cannot see it** (returns exactly 0.00). | **FOUND.** Excluded by date; flagged per row by `fwd_spread_bp` / `n_nodes_inside`. |
# | 3 | **Snapshot timing** — Barchart 17:00 NY bar vs CME 15:00 ET settle vs the Citi curve's own snap | **1.7–2.7bp per pack-day** at ranks 1–8 (Roll estimator, 2022-23), rising to **tens of bp on fast days** — the 2020-03-03/04/05 cluster prints −48bp. Hard bound from a 24h desync: 7.3bp. | **MEASURED.** Irreducible without intraday alignment. Sets the minimum tradeable rank. |
# | 4 | **Stale deferred settles** | A stale leg biases the pack rate by the whole missed move / 4. Detected by `CA < 0` on rows whose control is clean — **99.6% of the 3,844 violations**. | Filtered. `flag_negative_ca` is the operative test. |
# | 5 | **CME vs non-CME clearing basis** | Citi's swap leg is CME-cleared; `USD-SOFR-1D` is not. Bounded by the tie-out residual after the frequency fix: **mean −0.11bp, sd 1.68bp over 13 rows** — i.e. under 2bp, not the −3.9bp previously attributed to it. | Bounded. The −3.9bp was the frequency, not the clearing basis. |
# | 6 | **Deep-pack curve smoothing** | Ranks 9–10 sit inside a single ~367-day node segment, so their swap leg is an interpolation of two annual nodes. Their apparent 0.2–0.5bp precision is reduced independent information, not accuracy. | Flagged via `segment_days`; do not read low ΔCA variance there as quality. |
# | 7 | **Ho-Lee itself** — flat normal vol, no mean reversion | Shape error, not level error. Citi's own table prints a log-log slope of **1.38**, not the flat-vol 2.0, because its implied vols fall 199.5→151.9. Anyone testing against 2.0 will "fail" a correct implementation. | Understood; the benchmark is Citi's slope, not the textbook one. |
# | 8 | **`T1` convention** — as-of→IMM ACT/365 | The 2023 table implies Citi's effective `T1` is ~0.3% shorter (3–5 days on a 3–4y horizon): T+2 spot start, business-day counting or the SR3 last-trade-day rule. Worth **−0.2% to −0.6% on implied vol**, nothing on CA. | Open, immaterial for RV ranking. |
# | 9 | **Universe truncation** | The daily SR3 cache supports pack windows 1–10 (T1 ≤ 2.4y). Citi's table is 5–17 (T1 ≤ 4.0y), where the CA is 15–22bp and the signal-to-noise is far better. **Every conclusion here is about the near half of Citi's screen.** | Data limit. Do not extrapolate the survival rates to Blues/Golds. |
# | 10 | **Pack price rounding** | CME quotes packs to a quarter tick (0.0025 = 0.25bp of CA). Not applied here; `round_pack_price_to_tick` defaults False because the unrounded number is what tied out. | Sub-noise (0.25bp vs 1.7bp measured noise). |
#
# ### What to do with this
#
# 1. **Rebuild `strat2_panel.parquet`.** It is biased by up to 12bp and the bias
#    is largest exactly where the strategy is live.
# 2. **Start the sample at 2019-07-08**, not 2019-01-02.
# 3. **Trade nothing below rank 5**, and quote implied vol only from rank 8 out
#    if you want it good to 15%.
# 4. **Keep `CA < 0` as a hard filter** — it caught a data problem the other
#    three tests could not, on 99.6% of the rows where it fired.
# 5. **Re-run this notebook against any curve change.** Tests 0 and 1 together
#    are cheap and they are the only two that need no external reference.

# %%
summary = pd.DataFrame([
    {"test": "(a) zero-convexity control", "statistic": "mean CA_synthetic, all rows",
     "value": f"{df.ca_synthetic_bp.mean():+.4f} bp", "verdict": "PASS"},
    {"test": "(a) zero-convexity control", "statistic": "|residual| p95, post-break",
     "value": f"{df[df.curve_ok].ca_synthetic_bp.abs().quantile(.95):.4f} bp", "verdict": "PASS"},
    {"test": "(a) zero-convexity control", "statistic": "residual / |CA_observed|, median",
     "value": f"{share.median():.4f}", "verdict": "PASS"},
    {"test": "(b) frequency", "statistic": "regression slope vs predicted 0.375",
     "value": f"{reg['slope_no_intercept']:.4f} (r2 {reg['r2']:.4f})", "verdict": "PASS"},
    {"test": "(b) frequency", "statistic": "bias from using the spec default",
     "value": f"{float((df.ca_annual_bp - df.ca_observed_bp).mean()):+.3f} bp mean, "
              f"{float((df.ca_annual_bp - df.ca_observed_bp).min()):+.3f} worst",
     "verdict": "MATERIAL"},
    {"test": "(c) no-arbitrage", "statistic": "CA < 0 rate, post-break",
     "value": f"{float((df[df.curve_ok].ca_observed_bp < 0).mean()):.4f}", "verdict": "DATA"},
    {"test": "(c) no-arbitrage", "statistic": "violations with a clean control",
     "value": f"{1 - float((neg.ca_synthetic_bp.abs() > 1).mean()):.4f}", "verdict": "DATA"},
    {"test": "(c) filter", "statistic": "pack-days surviving all filters",
     "value": f"{float(flags.survive.mean()):.4f} overall, "
              f"{float(flags[(flags.year >= 2022) & (flags['rank'] >= 5)].survive.mean()):.4f} 2022-23 rank>=5",
     "verdict": "OK"},
    {"test": "(a) control residual", "statistic": "after removing the annuity term",
     "value": f"mean {left.mean():+.4f} bp, sd {left.std():.4f}, "
              f"|p95| {left.abs().quantile(.95):.4f}", "verdict": "PASS"},
    {"test": "(d) shape", "statistic": "log-log slope 2023, rank>=5 (T1 1.1-2.4y)",
     "value": f"{sh[sh.year == 2023].loglog_slope.median():.3f} (Citi over the same "
              f"T1 span: {float(np.polyfit(np.log(_ct1[:6]), np.log(_cca[:6]), 1)[0]):.3f})",
     "verdict": "PASS"},
    {"test": "(d) shape", "statistic": "corr(CA, T1^2), 2023",
     "value": f"{sh[sh.year == 2023].corr_t1_squared.median():.4f} "
              f"(Citi's own: {citi_corr:.4f})", "verdict": "PASS"},
    {"test": "(e) vol conditioning", "statistic": "min rank for <=15% vol error",
     "value": f"{int(elig.index.min()) if len(elig) else '>10'}", "verdict": "RULE"},
    {"test": "(f1) cross-source", "statistic": "median |futures − Q12 fwd|, 2021-23",
     "value": f"{float(q[q.year >= 2021].futures_vs_q12_bp.abs().median()):.3f} bp",
     "verdict": "PASS"},
    {"test": "(f1) cross-source", "statistic": "median |futures − Q12 fwd|, 2019",
     "value": f"{float(q[q.year == 2019].futures_vs_q12_bp.abs().median()):.3f} bp",
     "verdict": "CURVE"},
    {"test": "(f2) timing", "statistic": "CA noise per pack-day, 2022-23 ranks 1-8",
     "value": f"{float(nt_live.loc[1:8,'noise_roll_bp'].min()):.2f}-"
              f"{float(nt_live.loc[1:8,'noise_roll_bp'].max()):.2f} bp", "verdict": "BOUND"},
    {"test": "(g) Citi tie-out", "statistic": "mean delta, 13 rows, Q/Q",
     "value": f"{tie.delta_qq.mean():+.3f} bp (corr "
              f"{np.corrcoef(tie.citi_CA, tie.our_CA_qq)[0,1]:.4f})", "verdict": "PASS"},
    {"test": "(g) negative control", "statistic": "mean delta, 13 rows, annual",
     "value": f"{tie.delta_annual.mean():+.3f} bp", "verdict": "FAILS (as it must)"},
    {"test": "stored artifact", "statistic": "strat2_panel.parquet vs ca_annual_bp",
     "value": f"max diff {float((mg.ca_annual_bp - mg.ca_bp).abs().max()):.2e} bp",
     "verdict": "STALE — REBUILD"},
]).set_index("test")
print("VERDICT TABLE")
print(summary.to_string())
