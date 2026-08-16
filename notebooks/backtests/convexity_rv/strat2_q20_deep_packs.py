# %% [markdown]
# # Strategy 2 on the Q20 curve — the deep packs Citi actually traded
#
# Strategy 2 as shipped reaches pack ranks 2–10, first expiry ≤ ~2.4y. Citi's
# published SOFR screen is ranks **5–17**, and the two packs it recommended by
# name are **Blues** (rank 13, T1 ≈ 3.25y) and **Golds** (rank 17, T1 ≈ 4.25y):
#
# > "Sell $100k DV01 of **Blues** convexity adjustment, i.e. buy 1000 of H0-Z0
# > packs (1000 of each of the four contracts) and pay $1bn on a
# > matched-maturity (3/18/20-3/17/21) CME swap."
#
# > "We continue to favor shorting **Blues** convexity adjustment as a short vol
# > proxy." — *Rates Vol Lab*, 12-Jun-2023, p.14
#
# So the part of the strategy the research is actually about had never been
# tested here. This notebook is that test, and its two jobs are (1) to establish
# **where a curve-derived futures rate is allowed to stand in for a settlement
# mark**, and (2) to run the deep-pack backtest and put it next to the near-pack
# result.
#
# ## The five findings, up front
#
# 1. **The premise in the brief is empirically false, and the reason matters.**
#    There is no `USD-SOFR-1D-Q20STIRT` curve store on this machine at all
#    (`curve_store/raw` carries Q12STIRT with 2,061 dates and Q16STIRT with 197).
#    Worse, `IRSwapsMDP.get_pricer` for that curve makes **52–57 Barchart
#    requests per date**, because the production builder's pricer fetcher is
#    wired to `BARCHART_TOS_LIVE_STIRF-RL` — the *intraday* source, which reaches
#    depth 20 on **zero** local dates. The module therefore builds the curve
#    itself from the **17:00 EOD** source and injects the pricers into the
#    production solver. Measured: **0 outbound requests, ~0.15s per date.**
#
# 2. **The earlier rejection of a curve-derived rate was right about the front
#    end and wrong about the deep end.** That work measured a 9.375bp median
#    disagreement in 2019 — *pooled across ranks*. Decomposed by rank it is
#    **15.8bp at ranks 1–4 and 0.26bp at ranks 13–16**. The cause is now
#    identified exactly: every `*STIRT` node grid is built from the central-bank
#    meeting-date map, and this machine's map **starts in April 2021**. Before
#    then the *front* of the curve is one enormous log-linear segment while the
#    deep windows sit in a properly resolved region. **The 2019 degeneracy is a
#    front-end defect.**
#
# 3. **The naive quality criteria select for the failure.** In 2019 the
#    degenerate curve scores *better* on both `CA ≥ 0` and `corr(CA, T1²)`,
#    because a flattened curve manufactures a monotone non-negative profile out
#    of nothing. The gate here is built on node resolution and per-contract
#    settle agreement instead, and `CA ≥ 0` is **reported but never gated on**.
#
# 4. **Gated, the Q20 forward *is* the settlement mark.** On gate-passed deep
#    rows, median |CA(Q20) − CA(settle)| = **0.057bp** and the correlation is
#    **0.9995**; at rank 13 it is 0.028bp and 1.0000. The 6/9/2023 tie-out
#    reproduces all 13 Citi rows including **Blues 15.40 → 15.72 (+0.32bp)** and
#    **Golds 22.29 → 21.73 (−0.56bp)**.
#
# 5. **And that is the case for trading deep packs.** The settle-timing noise
#    barely grows with maturity while the adjustment grows four-fold: noise/CA
#    level is **30.1% at ranks 1–8** and **6.7% at ranks 13–17**, so the
#    CA-implied vol error falls from **15.1% to 3.4%**.
#
# What it does **not** buy: new coverage. The curve is calibrated to the settles,
# so it cannot conjure a contract the store lacks, and it *inherits* a stale
# settle rather than laundering it. The binding constraint is the raw SR3
# diskcache throughout.

# %%
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import dataclasses
import datetime
import math
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

from BT.trade_dashboard import compare_curves, summary_stats, trade_dashboard

import RVUtils.ConvexityRV.strat2_q20 as Q
import RVUtils.ConvexityRV.strat2_sofr_convexity as S2
from RVUtils.ConvexityRV import ca_staleness
from RVUtils.ConvexityRV.ca_diagnostics import vol_sensitivity_bp_per_bp
from RVUtils.ConvexityRV.holee import implied_vol_from_ca_bp
from RVUtils.ConvexityRV.listed_cache_guard import cache_only, network_calls_blocked
from RVUtils.ConvexityRV.packs import imm_date, quarterly_imm_sequence

DATA = _REPO / "notebooks" / "data" / "convexity_rv"
DATA.mkdir(parents=True, exist_ok=True)
pd.set_option("display.width", 220)

# %% [markdown]
# ## 1. CONFIG — every knob, with why it is set where it is
#
# Two config objects, deliberately separate. `Q20Config` describes **how a
# futures rate is obtained and when it may be believed**; `Strat2Config`
# describes **the screen and the trade** and is unchanged from the near-pack
# strategy. `deep_pack_config` derives the second from the first so the pack
# universe and the strip depth cannot drift apart.

# %%
@dataclasses.dataclass(frozen=True)
class NotebookConfig:
    """Everything this notebook chooses, over and above the module defaults."""

    # ---- the deep universe actually backtested -------------------------------
    deep_rank_start: int = 9
    """First RANKED pack window. Window ``rank_start-1`` is still needed (the 3m
    roll of the first ranked pack is measured against it), so the panel is
    filtered from ``rank_start-1``."""

    deep_n_packs: int = 6
    """Ranked windows 9..14 — Greens through one past Blues. Chosen by DATA, not
    by preference: windows 9..14 need 17 contracts and give the longest
    contiguous gate-passed run in the store (743 days). Citi's full 5..17 needs
    20 contracts and its longest run is 192 days, entirely inside ZIRP."""

    # ---- the near-pack comparison -------------------------------------------
    near_rank_start: int = 2
    near_n_packs: int = 9
    """Windows 2..10 — the shipped near-pack strategy, re-run on this panel and
    this gate so the comparison is like-for-like on pipeline as well as window."""

    # ---- the published reference --------------------------------------------
    citi_date: datetime.date = datetime.date(2023, 6, 9)
    citi_rank_start: int = 5
    citi_n_packs: int = 13
    """Citi Figure 58: windows 5..17, Reds M4-H5 through Golds M7-H8."""

    # ---- tolerances used only for the notebook's own assertions --------------
    tieout_max_abs_bp: float = 4.0
    """Per-row |ours − Citi| the tie-out asserts. The published near-pack tie-out
    on the same date was |max| 3.12bp against 13 rows, so 4.0 is that measured
    spread with headroom, not a target."""

    tieout_min_corr: float = 0.95
    iv_ratio_target: float = 0.9973
    """Inverting Citi's OWN CA column reproduces Citi's OWN implied-vol column at
    this median ratio. Uses Citi's numbers on both sides, so it validates the
    Ho-Lee form and the T1 convention with no market data involved."""


NB = NotebookConfig()
QCFG = Q.Q20Config()
DEEP = Q.deep_pack_config(rank_start=NB.deep_rank_start, n_packs=NB.deep_n_packs)
NEAR = Q.deep_pack_config(rank_start=NB.near_rank_start, n_packs=NB.near_n_packs)
CITI = Q.deep_pack_config(rank_start=NB.citi_rank_start, n_packs=NB.citi_n_packs)

for _n, _c in (("deep", DEEP), ("near", NEAR), ("citi", CITI)):
    print(f"{_n:5s}: windows {_c.rank_start}..{_c.rank_start + _c.n_packs - 1}, "
          f"n_contracts={_c.n_contracts}")
print(f"\ngate: max |settle - Q20 fwd| {QCFG.gate_max_settle_diff_bp}bp per CONTRACT, "
      f"min nodes inside {QCFG.gate_min_nodes_inside}, "
      f"min control power {QCFG.gate_min_control_power_bp}bp")

# %% [markdown]
# ## 2. Sign probe — asserted, not assumed
#
# The convexity adjustment is `pack_rate − matched_forward_swap_rate`, and it is
# **positive** when the futures rate exceeds the forward — the no-arbitrage
# direction. This runs the shipped `ca_snapshot` against a curve pinned at a
# known rate, so the sign checked is the one the production code produces.

# %%
class _PinnedCurve:
    """A swap curve whose matched forward rate is always 4.00%."""

    _rl_curve_handle = None

    def _curve_definition(self):
        return {"ReferenceRate": "usd_irs"}


_orig_par = S2._swap_par_rate
try:
    S2._swap_par_rate = lambda *a, **k: 4.00
    _seq = quarterly_imm_sequence(NB.citi_date, CITI.n_contracts)
    for _fut_rate, _want in ((4.10, +10.0), (3.90, -10.0), (4.00, 0.0)):
        _snap = S2.ca_snapshot(NB.citi_date, CITI,
                               futures_prices=Q.forwards_to_prices({k: _fut_rate for k in _seq}),
                               swap_pricer=_PinnedCurve())
        assert len(_snap) > 0, "sign probe produced no rows"
        assert np.allclose(_snap["ca_bp"].to_numpy(float), _want, atol=1e-9), (
            f"futures {_fut_rate}% vs swap 4.00% should give {_want:+.1f}bp, "
            f"got {_snap['ca_bp'].unique()}")
        print(f"  futures {_fut_rate:.2f}% - swap 4.00%  ->  CA {_want:+6.1f}bp  OK "
              f"({len(_snap)} windows)")
finally:
    S2._swap_par_rate = _orig_par

# futures DV01 is rate-invariant and identical for ED and SR3
from RVUtils.ConvexityRV.packs import DV01_PER_CONTRACT

assert DV01_PER_CONTRACT == 25.0
assert int(round(100_000.0 / (4.0 * DV01_PER_CONTRACT))) == 1000, "1000 packs = $100k/bp"
print(f"  $100k DV01 = {int(round(100_000.0/(4*DV01_PER_CONTRACT)))} packs "
      f"x 4 legs x ${DV01_PER_CONTRACT:.0f}/bp  OK")

# roll-date off-by-one: the SFRCM ladder rolls, the pack universe does not
_roll = imm_date(2019, 6)
assert Q.is_imm_roll_date(_roll) and Q.instrument_count(_roll, 20) == 19
assert Q.instrument_count(NB.citi_date, 20) == 20
print(f"  IMM roll {_roll}: strip depth 20 -> {Q.instrument_count(_roll, 20)} SFRCM "
      f"instruments  OK")

# %% [markdown]
# ## 3. Universe — measured off the diskcache, not assumed
#
# `strip_depth_by_date` reads the SR3 store's sqlite shards read-only and returns
# the length of the **contiguous** front strip per date. Contiguity is required
# rather than mere presence: a pack is four consecutive contracts and the curve
# calibrates to an unbroken `SFRCM1..k` prefix, so "17 of the first 20 present"
# would overstate what is buildable.

# %%
_t0 = time.time()
DEPTHS = Q.strip_depth_by_date(QCFG)
print(f"{len(DEPTHS)} dates {min(DEPTHS)}..{max(DEPTHS)}  ({time.time()-_t0:.0f}s)")

_d = pd.Series(DEPTHS, name="depth")
_d.index = pd.to_datetime(list(DEPTHS))
_u = pd.DataFrame({"n_dates": _d.groupby(_d.index.year).size()})
for _r in (5, 9, 13, 17):
    _u[f"rank{_r}"] = (_d >= Q.depth_for_rank(_r)).groupby(_d.index.year).sum()
_u.loc["TOTAL"] = _u.sum()
print("\ndates able to quote each pack rank (rank 13 = Blues, 17 = Golds):")
print(_u.to_string())
assert int(_u.loc["TOTAL", "rank13"]) > 1000, "Blues should be reachable on >1000 dates"
assert int(_u.loc["TOTAL", "rank17"]) > 500, "Golds should be reachable on >500 dates"

# %% [markdown]
# ## 4. The panel
#
# Built by `scripts/strat2_q20_build.py` (6 workers, ~2 min for 1,410 dates).
# Every row carries **both** rate sources, their two adjustments, the three gate
# conditions and every measurement the gate was derived from — the gate travels
# *with* the panel so a filter applied in one notebook is not a filter the next
# reader silently omits.

# %%
PANEL = pd.read_parquet(DATA / "strat2_q20_panel.parquet")
RATES = pd.read_parquet(DATA / "strat2_q20_rates.parquet")
SETTLES = pd.read_parquet(DATA / "strat2_q20_settles.parquet")
PANEL["year"] = pd.to_datetime(PANEL["date"]).dt.year
PANEL["band"] = pd.cut(PANEL["rank"], [0, 4, 8, 12, 16, 20],
                       labels=["1-4", "5-8", "9-12", "13-16", "17-20"])
print(f"panel {PANEL.shape[0]:,} rows x {PANEL['date'].nunique():,} dates "
      f"{PANEL['date'].min().date()}..{PANEL['date'].max().date()}, "
      f"ranks {PANEL['rank'].min()}..{PANEL['rank'].max()}")
assert PANEL["rank"].max() >= 17, "the panel must reach Golds"
print(f"rows reaching Blues (rank 13): {int((PANEL['rank']==13).sum()):,} on "
      f"{PANEL[PANEL['rank']==13]['date'].nunique():,} dates")
print(f"rows reaching Golds (rank 17): {int((PANEL['rank']==17).sum()):,} on "
      f"{PANEL[PANEL['rank']==17]['date'].nunique():,} dates")

# %% [markdown]
# ## 5. Node resolution — the test the zero-convexity control cannot do
#
# `CA_synthetic` compares the arithmetic mean of four quarterly forwards with the
# par rate of the swap spanning them. If the curve has **no node inside the
# window**, log-linear interpolation makes all four forwards identical and the
# two agree *by construction*: the control returns exactly 0.00bp however wrong
# the leg is. A passing control on a flat segment is not evidence, it is an
# absence of evidence, and it looks identical.
#
# `spans_window` is that condition. Read the table by row and by column: the
# defect is **entirely in the near ranks and entirely before 2021**, which is
# when the central-bank meeting map begins.

# %%
_res = PANEL.groupby("year").agg(
    n_dates=("date", "nunique"), q20_nodes_med=("q20_n_nodes", "median"),
    nodes_inside_med=("q20_n_nodes_inside", "median"),
    segment_days_med=("q20_segment_days", "median"))
print("Q20 node grid by year:")
print(_res.to_string())

print("\nspans_window %% — a single node interval swallows the whole pack window:")
_sw = (PANEL.pivot_table(index="year", columns="band", values="q20_spans_window",
                         aggfunc="mean", observed=True) * 100).round(1)
print(_sw.to_string())
assert _sw.loc[2019, "1-4"] > 50, "2019 near packs must be degenerate"
assert float(_sw.loc[2019, "13-16"]) == 0.0, "2019 deep packs must be resolved"

# %%
_fig = go.Figure()
for _b in ["1-4", "5-8", "9-12", "13-16", "17-20"]:
    if _b in _sw.columns:
        _fig.add_trace(go.Scatter(x=_sw.index, y=_sw[_b], mode="lines+markers", name=f"ranks {_b}"))
_fig.update_layout(
    title="Node-resolution failure is a FRONT-END defect, not a deep-end one<br>"
          "<sub>share of pack-days whose whole window sits inside one Q20 node "
          "interval — the failure the zero-convexity control cannot see</sub>",
    xaxis_title="year", yaxis_title="% of pack-days degenerate", height=430,
    legend_title="pack rank")
_fig

# %% [markdown]
# ## 6. Settle agreement — "ensure we correctly get the settlement marks"
#
# The direct test. For every pack window, the **maximum over its four contracts**
# of |SR3 settle − Q20 IMM forward|. Max, not mean: two legs wrong by +6bp and
# two by −6bp average to a clean-looking pack.
#
# This is the decomposition of the earlier 9.375bp-in-2019 rejection.

# %%
print("median max|settle - Q20 fwd| (bp), by year x rank band:")
_ag = PANEL.pivot_table(index="year", columns="band", values="max_settle_diff_bp",
                        aggfunc="median", observed=True).round(3)
print(_ag.to_string())
print("\np95 of the same:")
print(PANEL.pivot_table(index="year", columns="band", values="max_settle_diff_bp",
                        aggfunc=lambda s: s.quantile(.95), observed=True).round(3).to_string())
print(f"\n2019, ranks 1-4 : {_ag.loc[2019,'1-4']:.2f}bp  <- the pooled 9.375bp rejection "
      f"lives here")
print(f"2019, ranks 13-16: {_ag.loc[2019,'13-16']:.2f}bp  <- and NOT here")
assert _ag.loc[2019, "1-4"] > 5.0 and _ag.loc[2019, "13-16"] < 1.0

# %% [markdown]
# ### The admissibility rule, and why it is set where it is
#
# `gate_max_settle_diff_bp = 2.0`. Not a round number chosen for looks: Barchart's
# "EOD" is the 1-minute bar nearest 17:00 New York while SR3 settles at ~15:00
# ET, and the CA noise that mismatch induces was measured on near packs at
# **0.89–2.55bp per pack-day (mean 1.82)**. A tolerance below that rejects rows
# for carrying noise the settles themselves carry.

# %%
print("gate incidence by year (share of rows passing each condition):")
print(Q.gate_summary(PANEL).round(4).to_string())
print("\ngate pass rate %% by year x rank band:")
_gp = (PANEL.pivot_table(index="year", columns="band", values="gate_ok",
                         aggfunc="mean", observed=True) * 100).round(1)
print(_gp.to_string())
GATED = Q.apply_gate(PANEL)
print(f"\n{len(GATED):,} of {len(PANEL):,} rows pass ({100*len(GATED)/len(PANEL):.1f}%)")
assert _gp.loc[2019, "1-4"] < 5 and _gp.loc[2019, "13-16"] > 95, (
    "the gate must invert between near and deep packs in 2019")

# %% [markdown]
# ## 7. The vanity metrics — reported, and deliberately NOT gated on
#
# The earlier investigation established that `CA ≥ 0` and `corr(CA, T1²)` **do
# not discriminate**: in 2019 the degenerate curve scored *better* on both,
# because a flattened curve manufactures a monotone non-negative profile out of
# nothing. Building a gate on them selects for the failure it is meant to catch.
# They are reported here so a reader can see they carry no signal.

# %%
_neg = pd.DataFrame({
    "CA_q20<0 %": PANEL.groupby("year")["ca_bp_q20"].apply(lambda s: 100 * (s < 0).mean()),
    "CA_settle<0 %": PANEL.groupby("year")["ca_bp_settle"].apply(lambda s: 100 * (s < 0).mean()),
    "gated CA_q20<0 %": GATED.groupby("year")["ca_bp_q20"].apply(lambda s: 100 * (s < 0).mean()),
}).round(1)
print(_neg.to_string())
print("\nBoth sources violate CA>=0 at essentially the SAME rate, and gating barely")
print("moves it: the violations are a property of the MARKET DATA (ZIRP, where the")
print("adjustment is ~0 and its sign is noise), not of the rate source. A gate on")
print("CA>=0 would therefore discard good deep rows and keep degenerate 2019 ones.")

# %% [markdown]
# ## 7b. The zero-convexity control on the deep windows — and its blind spot
#
# Replace the four futures rates with the **swap curve's own IMM×IMM forwards**.
# Those carry no convexity by construction — they come off the very discount
# curve the swap leg is priced on — so the adjustment must be ~0. Whatever it
# returns instead is our own convention error, measured with no external
# reference. The matched swap is **quarterly/quarterly** throughout; the
# `usd_irs` spec default is annual fixed and biases every adjustment by
# `0.375·r²`, which is up to 12bp and the same order as the signal.
#
# **But the control must be read against the curvature it was allowed to see.**
# `CA_synthetic` is an arithmetic-mean-minus-annuity-weighted-mean discrepancy,
# and that is identically zero when the four forwards are identical. This is
# where deep packs are *weaker* than near ones: `USD-SOFR-1D` thins toward annual
# nodes past ~2y, so a deep window contains about **one** node and its four
# quarterly forwards barely differ.

# %%
_ctl = PANEL.groupby("rank").agg(
    n=("ca_synthetic_bp", "size"),
    ca_syn_med=("ca_synthetic_bp", "median"),
    ca_syn_p95=("ca_synthetic_bp", lambda s: float(np.nanpercentile(np.abs(s), 95))),
    pred_med=("ca_synthetic_pred_bp", "median"),
    swap_spread_bp=("swap_fwd_spread_bp", "median"),
    swap_nodes_in=("swap_n_nodes_inside", "median"),
    annual_gap_bp=("annual_qq_gap_bp", "median"))
_ctl["resid_after_pred"] = (
    PANEL.assign(r=PANEL["ca_synthetic_bp"] - PANEL["ca_synthetic_pred_bp"])
    .groupby("rank")["r"].median())
print("zero-convexity control by rank (bp):")
print(_ctl.round(4).to_string())

_all = PANEL["ca_synthetic_bp"].to_numpy(float)
print(f"\nall {len(_all):,} rows: mean {np.nanmean(_all):+.4f}bp  median "
      f"{np.nanmedian(_all):+.4f}bp  |p95| {np.nanpercentile(np.abs(_all),95):.4f}bp")
assert abs(float(np.nanmedian(_all))) < 0.5, "the conventions do not tie out"

# the residual IS the predicted annuity-weighting term, with no free parameter
_ok = PANEL[["ca_synthetic_bp", "ca_synthetic_pred_bp"]].dropna()
print(f"corr(control, no-free-parameter prediction) = "
      f"{np.corrcoef(_ok['ca_synthetic_bp'], _ok['ca_synthetic_pred_bp'])[0,1]:.4f}")
_res = (_ok["ca_synthetic_bp"] - _ok["ca_synthetic_pred_bp"])
print(f"control minus prediction: mean {_res.mean():+.4f}bp  sd {_res.std():.4f}bp")

# the annual/quarterly gap is a PREDICTION: 0.375 * r^2, no free parameter
from RVUtils.ConvexityRV.ca_diagnostics import (COMPOUNDING_GAP_SLOPE,
                                                regress_gap_on_rate_squared)

_g = regress_gap_on_rate_squared(PANEL["annual_qq_gap_bp"], PANEL["swap_rate"])
print(f"\nannual-vs-Q/Q gap ~ b*r^2 (no intercept): b = {_g['slope_no_intercept']:.5f} "
      f"vs predicted {COMPOUNDING_GAP_SLOPE}  "
      f"({100*(_g['slope_no_intercept']/COMPOUNDING_GAP_SLOPE-1):+.2f}%), "
      f"r2 = {_g['r2']:.4f}, intercept {_g['intercept']:+.3f}bp, n={int(_g['n']):,}")
assert abs(_g["slope_no_intercept"] - COMPOUNDING_GAP_SLOPE) < 0.05

print("\nCAVEAT, stated rather than buried: at ranks >= 9 the swap curve carries")
print("~1 node per pack window and the four forwards spread only a few bp, so the")
print("control has LITTLE POWER there -- its ~0.00bp is close to an absence of")
print("evidence. It confirms the conventions where it CAN see (ranks 1-8, forward")
print("spreads of 16-117bp); for the deep windows the weight is carried by the")
print("per-contract settle-agreement gate in section 6, not by this control.")

# %%
_f = go.Figure()
_f.add_trace(go.Scatter(x=_ctl.index, y=_ctl["swap_spread_bp"], name="swap-curve forward spread (bp)",
                        mode="lines+markers", line=dict(color="#4C78A8", width=3)))
_f.add_trace(go.Scatter(x=_ctl.index, y=_ctl["ca_syn_p95"].abs(),
                        name="|control residual| p95 (bp)", mode="lines+markers",
                        line=dict(color="#E45756", width=3), yaxis="y2"))
_f.update_layout(
    title="The zero-convexity control loses power exactly where the deep packs live"
          "<br><sub>USD-SOFR-1D thins to ~annual nodes past 2y, so a deep window's four "
          "quarterly forwards barely differ and the control returns ~0 by construction</sub>",
    xaxis_title="pack rank (first contract)",
    yaxis_title="control power: forward spread (bp)",
    yaxis2=dict(title="|residual| p95 (bp)", overlaying="y", side="right"),
    height=440)
_f

# %% [markdown]
# ## 8. Known-answer tie-out — Citi Figure 58, close 6/9/2023
#
# 13 rows, windows 5..17, **including Blues (15.40bp) and Golds (22.29bp)** —
# the rows the rank-2..10 strategy can never reach. All 24 contracts are cached
# on this date, so both rate sources are available and the comparison is clean.

# %%
_depth = DEPTHS[NB.citi_date]
_n0 = network_calls_blocked()
_rows = Q.day_rows(NB.citi_date, _depth, cfg=QCFG, s2cfg=CITI)
assert network_calls_blocked() == _n0, "the tie-out reached for the network"
_t = pd.DataFrame(_rows)
_t = _t[(_t["rank"] >= 5) & (_t["rank"] <= 17)].sort_values("rank")

_out = []
for _, _r in _t.iterrows():
    _c = Q.CITI_SOFR_20230609.get(_r["pack"])
    if _c is None:
        continue
    _w = float(_r["time_weight"])
    _out.append({
        "rank": int(_r["rank"]), "pack": _r["pack"], "colour": _r["colour"] or "",
        "citi_CA": _c["ca_bp"],
        "settle_CA": round(float(_r["ca_bp_settle"]), 2),
        "q20_CA": round(float(_r["ca_bp_q20"]), 2),
        "d_settle": round(float(_r["ca_bp_settle"]) - _c["ca_bp"], 2),
        "d_q20": round(float(_r["ca_bp_q20"]) - _c["ca_bp"], 2),
        "citi_IV": _c["implied_vol_bp"],
        "IV_from_citi_CA": round(implied_vol_from_ca_bp(_c["ca_bp"], [math.sqrt(_w)]), 1),
        "IV_q20": round(implied_vol_from_ca_bp(float(_r["ca_bp_q20"]), [math.sqrt(_w)]), 1),
        "nodes_in": int(_r["q20_n_nodes_inside"]),
        "maxdiff_bp": round(float(_r["max_settle_diff_bp"]), 2),
        "gate": bool(_r["gate_ok"]),
    })
TIEOUT = pd.DataFrame(_out)
print(TIEOUT.to_string(index=False))

assert len(TIEOUT) == 13, f"expected Citi's 13 rows, got {len(TIEOUT)}"
for _src in ("d_q20", "d_settle"):
    _v = TIEOUT[_src].to_numpy(float)
    _lv = TIEOUT["q20_CA" if _src == "d_q20" else "settle_CA"].to_numpy(float)
    _corr = float(np.corrcoef(TIEOUT["citi_CA"], _lv)[0, 1])
    print(f"\n{_src}: mean {_v.mean():+.3f}  median {np.median(_v):+.3f}  "
          f"sd {_v.std(ddof=1):.3f}  |max| {np.abs(_v).max():.3f}  corr {_corr:.4f}")
    assert np.abs(_v).max() < NB.tieout_max_abs_bp, f"{_src} worst row {np.abs(_v).max():.2f}bp"
    assert _corr > NB.tieout_min_corr

_iv = (TIEOUT["IV_from_citi_CA"] / TIEOUT["citi_IV"])
print(f"\nimplied-vol inversion of Citi's OWN CA vs Citi's OWN IV column: "
      f"median ratio {_iv.median():.4f} (target {NB.iv_ratio_target}), "
      f"range {_iv.min():.4f}-{_iv.max():.4f}")
assert abs(float(_iv.median()) - NB.iv_ratio_target) < 0.004
assert bool(TIEOUT["gate"].all()), "every Citi row should pass the gate on this date"

print("\n*** THE PAYOFF ***")
for _p, _n in (("M6-H7", "BLUES"), ("M7-H8", "GOLDS")):
    _r = TIEOUT[TIEOUT["pack"] == _p].iloc[0]
    print(f"  {_n:6s} {_p}: Citi {_r['citi_CA']:6.2f}bp   ours(Q20) {_r['q20_CA']:6.2f}bp   "
          f"delta {_r['d_q20']:+.2f}bp   [rank {int(_r['rank'])}, unreachable at rank<=10]")

# %% [markdown]
# ## 9. The rate-source control
#
# The whole design demands this: if the gate works, the Q20 forward **is** the
# settlement mark, and the two adjustments must agree to well inside a basis
# point. A material divergence would mean the gate failed, not that the curve is
# adding information.

# %%
_deep = GATED[GATED["rank"] >= NB.deep_rank_start]
_d = (_deep["ca_bp_q20"] - _deep["ca_bp_settle"]).abs()
print(f"gate-passed, ranks >= {NB.deep_rank_start} (n={len(_deep):,}): "
      f"median |CA_q20 - CA_settle| = {_d.median():.4f}bp, p95 = {_d.quantile(.95):.4f}bp, "
      f"corr = {np.corrcoef(_deep['ca_bp_q20'], _deep['ca_bp_settle'])[0,1]:.5f}")
assert float(_d.median()) < 0.1 and float(_d.quantile(.95)) < 1.0

_by = GATED.groupby("rank").agg(
    n=("ca_diff_bp", "size"), CA_q20=("ca_bp_q20", "median"), CA_settle=("ca_bp_settle", "median"),
    absdiff_med=("ca_diff_bp", lambda s: float(np.nanmedian(np.abs(s)))),
    absdiff_p95=("ca_diff_bp", lambda s: float(np.nanpercentile(np.abs(s), 95))))
_by["corr"] = [float(np.corrcoef(x["ca_bp_q20"], x["ca_bp_settle"])[0, 1])
               for _, x in GATED.groupby("rank")]
print("\nby rank (gate-passed):")
print(_by.round(4).to_string())

# %% [markdown]
# ## 10. Why deep packs are the right place to trade this
#
# The core quantitative argument, and it is a ratio rather than a level.
# Barchart's EOD stamp is ~2h after the CME settle, and the resulting CA noise is
# estimated two ways: the **Roll / MA(1)** estimator `σ_e = sqrt(−cov(Δ_t, Δ_{t−1}))`
# (sharp) and `sd(Δ)/√2` (the upper bound, which assumes *all* variance is noise).
#
# The noise barely grows with maturity while the adjustment grows four-fold —
# so the same absolute measurement error is a third as damaging at Blues as at
# Whites.

# %%
_g = GATED[GATED["year"].isin([2021, 2022, 2023])]
_rows = []
for _rk, _gr in _g.groupby("rank"):
    _w = _gr.pivot_table(index="date", columns="pack", values="ca_bp_q20", aggfunc="last")
    _dd = _w.diff()
    _roll, _ub, _sd, _lv, _tw = [], [], [], [], []
    for _c in _w.columns:
        _s = _dd[_c].dropna()
        if len(_s) < 40:
            continue
        _v = _s.var(ddof=1)
        _cov = _s.autocorr(lag=1) * _v
        _roll.append(math.sqrt(-_cov) if _cov < 0 else np.nan)
        _ub.append(math.sqrt(_v / 2)); _sd.append(math.sqrt(_v))
        _lv.append(_w[_c].dropna().median())
        _tw.append(_gr.loc[_gr["pack"] == _c, "time_weight"].median())
    if not _sd:
        continue
    _se, _sdm, _lvm = np.nanmedian(_roll), np.nanmedian(_sd), np.nanmedian(_lv)
    _M = np.nanmedian(_tw)
    _sig = implied_vol_from_ca_bp(_lvm, [math.sqrt(_M)]) if _lvm > 0 else np.nan
    _ds = vol_sensitivity_bp_per_bp(_lvm, [math.sqrt(_M)]) if _lvm > 0 else np.nan
    _rows.append({"rank": int(_rk), "T1_yrs": round(float(_gr["t1_first"].median()), 2),
                  "CA_level_bp": _lvm, "noise_roll_bp": _se, "noise_ub_bp": np.nanmedian(_ub),
                  "true_move_bp": math.sqrt(max(_sdm**2 - 2*_se**2, 0.0)) if np.isfinite(_se) else np.nan,
                  "noise/level %": 100*_se/_lvm if _lvm > 0 else np.nan,
                  "sigma_bp": _sig, "dsigma_dCA": _ds,
                  "vol_err %": 100*_ds*_se/_sig if np.isfinite(_ds) and _sig else np.nan})
NOISE = pd.DataFrame(_rows)
print(NOISE.round(3).to_string(index=False))
_near = NOISE[NOISE["rank"].between(1, 8)]
_dp = NOISE[NOISE["rank"] >= 13]
print(f"\nranks 1-8  : noise/level {_near['noise/level %'].median():5.1f}%   "
      f"CA-implied vol error {_near['vol_err %'].median():5.1f}%")
print(f"ranks 13-17: noise/level {_dp['noise/level %'].median():5.1f}%   "
      f"CA-implied vol error {_dp['vol_err %'].median():5.1f}%")
assert _dp["noise/level %"].median() < _near["noise/level %"].median(), (
    "the deep-pack case rests on this ratio falling with maturity")

# %%
_f = go.Figure()
_f.add_trace(go.Bar(x=NOISE["rank"], y=NOISE["CA_level_bp"], name="CA level (bp)",
                    marker_color="#4C78A8"))
_f.add_trace(go.Bar(x=NOISE["rank"], y=NOISE["noise_roll_bp"],
                    name="settle-timing noise, Roll/MA(1) (bp)", marker_color="#E45756"))
_f.add_trace(go.Scatter(x=NOISE["rank"], y=NOISE["noise/level %"], name="noise / level (%)",
                        yaxis="y2", mode="lines+markers", line=dict(color="#54A24B", width=3)))
_f.update_layout(
    title="The signal grows with maturity; the measurement noise does not<br>"
          "<sub>2021–2023, gate-passed. Rank 13 = Blues, 17 = Golds</sub>",
    xaxis_title="pack rank (first contract)", yaxis_title="bp",
    yaxis2=dict(title="noise / level (%)", overlaying="y", side="right", rangemode="tozero"),
    barmode="group", height=460)
_f

# %% [markdown]
# ## 11. Staleness on the raw settle panel
#
# `ca_staleness` runs on the **price** panel, not the adjustment, because that is
# where the defect lives. One trap, found and fixed here: its default reference
# rule picks the column with the fewest unchanged prints, and on a *rolling*
# strip that is a contract present on only 117 of 1,410 dates — so "the market
# moved" is almost never established and nothing is flagged. An always-present
# front-contract reference is supplied explicitly.

# %%
_S = SETTLES.copy()
_S["FRONT"] = 100.0 - (PANEL[PANEL["rank"] == 1].set_index("date")["pack_rate_settle"]
                       .reindex(_S.index))
_auto = ((_S.drop(columns="FRONT").diff().abs() < 1e-9).sum()).idxmin()
print(f"default (auto) reference would be {_auto}, present on "
      f"{int(_S[_auto].notna().sum())}/{len(_S)} dates -- unusable")
FLAGS = ca_staleness.flag_stale_prices(_S, reference="FRONT")
print("flag incidence:", {c: round(float(FLAGS[c].mean()), 5) for c in
                          ("repeat_price", "stale_run", "jump_after_stale", "any_flag")})
CATCHUP = sorted(pd.DatetimeIndex(FLAGS.loc[FLAGS["jump_after_stale"], "date"].unique()))
print(f"catch-up (accumulate-then-jump) dates: {len(CATCHUP)} "
      f"{[str(d.date()) for d in CATCHUP]}")
print("\nworst contracts:")
print(ca_staleness.staleness_summary(FLAGS).head(6).round(5).to_string())

# %% [markdown]
# ### Verifying the detector before believing a near-zero answer
#
# A checking tool that is itself broken reports success and hides the thing it
# was built to find. So: inject a 5-print stale run and a 10bp catch-up into a
# real contract, on a date **where the reference actually moved** — a repeat
# print on a day the market did not move is not staleness, and in ZIRP the front
# contract moves <0.5bp for months, which is how the first attempt at this check
# silently "passed".

# %%
_col = _S.notna().sum().drop("FRONT").idxmax()
_mut = _S.copy()
_moved = (_mut["FRONT"].diff().abs() * 100.0) >= 0.5
_live = _mut.index[_mut[_col].notna() & _moved]
_live = _live[(_live > pd.Timestamp("2022-03-01")) & (_live < pd.Timestamp("2022-10-01"))]
_idx = list(_mut.index[_mut[_col].notna()])
_i0 = _idx.index(_live[len(_live) // 2])
_frozen = _mut.loc[_idx[_i0], _col]
for _k in range(1, 6):
    _mut.loc[_idx[_i0 + _k], _col] = _frozen
_mut.loc[_idx[_i0 + 6], _col] = _frozen + 0.10
_fm = ca_staleness.flag_stale_prices(_mut, reference="FRONT")
_sub = _fm[(_fm["contract"] == _col) & (_fm["date"].isin(_idx[_i0:_i0 + 8]))]
print(f"injected into {_col} at {_idx[_i0].date()}: 5 repeats + a 10bp catch-up")
print(_sub.to_string(index=False))
assert _sub["stale_run"].sum() >= 3, "detector missed the injected stale run"
assert _sub["jump_after_stale"].sum() >= 1, "detector missed the injected catch-up"
print("\n=> the detector fires on injected staleness, so the near-zero rate on the")
print("   real panel is a real measurement: these deep SR3 settles are NOT stale.")

# %% [markdown]
# ## 12. The backtest
#
# Windows 9..14 (Greens through one past Blues), the longest contiguous
# gate-passed run in the store. Four runs: the Q20 rate source and the raw-settle
# control, each hedged and unhedged.
#
# **The book is marked off settles in every run.** The screen may be computed off
# Q20 forwards, but a settle is what you can transact at and a curve forward is
# not.

# %%
def prep(lo, hi, source):
    """Gate -> require every rank present -> longest contiguous run."""
    sub = Q.apply_gate(PANEL)
    sub = sub[(sub["rank"] >= lo) & (sub["rank"] <= hi)].copy()
    _full = sub.groupby("date")["rank"].nunique()
    sub = sub[sub["date"].isin(_full[_full == (hi - lo + 1)].index)]
    sub["ca_bp"] = sub[f"ca_bp_{source}"]
    sub["pack_rate"] = sub[f"pack_rate_{source}"]
    return S2.trim_to_contiguous_run(
        sub, RATES.loc[RATES.index.isin(sub["date"].unique())])


_lo, _hi = DEEP.rank_start - 1, DEEP.rank_start + DEEP.n_packs - 1
for _src in ("q20", "settle"):
    _p, _r = prep(_lo, _hi, _src)
    _dd = pd.DatetimeIndex(sorted(_p["date"].unique()))
    print(f"deep/{_src:6s}: {len(_p):,} rows, {len(_dd)} days "
          f"{_dd[0].date()}..{_dd[-1].date()}")
DEEP_PANEL, DEEP_RATES = prep(_lo, _hi, "q20")
DEEP_DAYS = pd.DatetimeIndex(sorted(DEEP_PANEL["date"].unique()))
SPAN_YEARS = (DEEP_DAYS[-1] - DEEP_DAYS[0]).days / 365.25
print(f"\nspan_years = {SPAN_YEARS:.2f} (passed explicitly to every analytic below)")

# %%
_EQF = DATA / "strat2_q20_equity.parquet"
if _EQF.exists():
    EQ = pd.read_parquet(_EQF)
    EQ.index = pd.to_datetime(EQ.index)
    print(f"loaded cached equity {EQ.shape}")
else:
    _series, _meta = {}, {}
    for _src in ("q20", "settle"):
        _p, _r = prep(_lo, _hi, _src)
        _days = pd.DatetimeIndex(sorted(_p["date"].unique()))
        _ts, _mo = S2.panel_timeseries(_p, DEEP), S2.model_timeseries(_p, DEEP)
        _specs = S2.plan_epochs(_p, _r, DEEP, ts=_ts, model=_mo, verbose=False)
        for _h in (False, True):
            _t = time.time()
            with cache_only():
                _bt = S2.run_backtest(_specs, DEEP, hedged=_h, trading_days=_days,
                                      name=f"deep_{_src}", show_progress=False)
            _e = S2.assert_ran(_bt, _specs, hedged=_h, expect_days=len(_days))
            _k = f"deep_{_src}_{'hedged' if _h else 'unhedged'}"
            _series[_k] = _e
            _meta[_k] = {"epochs": len(_specs),
                         "packs": sorted({s.pack for s in _specs}),
                         "ranks": sorted({s.rank for s in _specs})}
            print(f"  {_k:26s} {len(_e)} marks in {time.time()-_t:.0f}s, "
                  f"terminal {float(_e.iloc[-1]):+,.0f}")
    EQ = pd.DataFrame(_series)
    EQ.to_parquet(_EQF)
    import json

    (DATA / "strat2_q20_epochs.json").write_text(json.dumps(_meta, indent=2))

assert float(EQ.abs().max().max()) > 0, "equity identically zero -- no trigger fired"
print(EQ.tail(2).round(0).to_string())

# %% [markdown]
# ### Near packs on the SAME panel and the SAME gate
#
# The shipped near-pack result (windows 2..10, raw settles) is
# **2020-08-03..2024-05-08, unhedged +$5,054,411 Sharpe 0.470 / hedged
# +$4,448,142 Sharpe 0.409**. That window is not this one, and most of its P&L
# comes from the 2023–24 narrowing that lies outside the deep window entirely.
# So it is quoted as the reference and the near strategy is *also* re-run here on
# the gate this notebook applies, which is a much shorter window — itself a
# finding: the gate rejects a large share of near-pack rows.

# %%
_NEQF = DATA / "strat2_q20_equity_near.parquet"
if _NEQF.exists():
    EQN = pd.read_parquet(_NEQF)
    EQN.index = pd.to_datetime(EQN.index)
else:
    _p, _r = prep(NEAR.rank_start - 1, NEAR.rank_start + NEAR.n_packs - 1, "settle")
    _days = pd.DatetimeIndex(sorted(_p["date"].unique()))
    _specs = S2.plan_epochs(_p, _r, NEAR, verbose=False)
    _s = {}
    for _h in (False, True):
        with cache_only():
            _bt = S2.run_backtest(_specs, NEAR, hedged=_h, trading_days=_days,
                                  name="near_settle", show_progress=False)
        _s[f"near_settle_{'hedged' if _h else 'unhedged'}"] = S2.assert_ran(
            _bt, _specs, hedged=_h, expect_days=len(_days))
    EQN = pd.DataFrame(_s)
    EQN.to_parquet(_NEQF)
_nd = EQN.index
print(f"near packs, gated: {len(EQN)} days {_nd[0].date()}..{_nd[-1].date()}")

# %% [markdown]
# ## 13. Results

# %%
def as_book(eq: pd.Series) -> pd.DataFrame:
    d = eq.diff().dropna()
    return pd.DataFrame({"timestamp": d.index, "pnl": d.to_numpy(float)})


BOOKS = {k: as_book(EQ[k]) for k in EQ.columns}
BOOKS_NEAR = {k: as_book(EQN[k]) for k in EQN.columns}


def _stats(name, eq, drop=()):
    d = eq.diff().dropna()
    keep = ~d.index.normalize().isin(pd.DatetimeIndex(drop))
    d2 = d[keep]
    sh = lambda x: float(x.mean() / x.std(ddof=1) * math.sqrt(252)) if x.std(ddof=1) > 0 else np.nan
    return {"run": name, "days": len(eq), "start": eq.index[0].date(), "end": eq.index[-1].date(),
            "pnl": float(eq.iloc[-1]), "sharpe": sh(d),
            "maxDD": float((eq - eq.cummax()).min()),
            "pnl_ex_catchup": float(d2.sum()), "sharpe_ex_catchup": sh(d2),
            "n_dropped": int((~keep).sum())}


RESULTS = pd.DataFrame([_stats(k, EQ[k], CATCHUP) for k in EQ.columns]
                       + [_stats(k, EQN[k], CATCHUP) for k in EQN.columns])
print(RESULTS.to_string(index=False, float_format=lambda v: f"{v:,.3f}"))

# %%
fig_cmp = compare_curves(BOOKS, title="Strat 2 deep packs (windows 9–14, incl. Blues): "
                                      f"Q20 forwards vs raw settles, hedged vs unhedged "
                                      f"($100k DV01, {SPAN_YEARS:.1f}y)")
fig_cmp

# %%
fig_dash = trade_dashboard(BOOKS["deep_q20_unhedged"],
                           title="Deep packs, Q20 rate source — unhedged (daily marks)",
                           span_years=SPAN_YEARS)
fig_dash

# %%
fig_dash_h = trade_dashboard(BOOKS["deep_q20_hedged"],
                             title="Deep packs, Q20 rate source — hedged with the 2s5s10s fly",
                             span_years=SPAN_YEARS)
fig_dash_h

# %%
for _k in EQ.columns:
    print(f"--- {_k}")
    print(summary_stats(BOOKS[_k], span_years=SPAN_YEARS).to_string(index=False))

# %% [markdown]
# ## 14. Selection stability — the honest caveat
#
# The two rate sources agree on the *level* of the adjustment to 0.03bp and
# correlate at 1.0000. They nonetheless produce materially different P&L, and the
# reason is worth stating plainly: the trade is chosen by a **cross-sectional
# ranking of nearly identical numbers**, so a 0.03bp difference can flip which
# pack is top-ranked and change an entire epoch.
#
# This is a statement about the strategy's fragility, not about the rate source's
# accuracy — and it bounds how much any of the P&L numbers above should be
# trusted to two significant figures.

# %%
_pa, _ra = prep(_lo, _hi, "q20")
_pb, _rb = prep(_lo, _hi, "settle")
_tsa, _ma = S2.panel_timeseries(_pa, DEEP), S2.model_timeseries(_pa, DEEP)
_tsb, _mb = S2.panel_timeseries(_pb, DEEP), S2.model_timeseries(_pb, DEEP)
_common = sorted(set(_pa["date"]).intersection(_pb["date"]))
_same = _tot = 0
for _d in _common[::5]:
    _sa = S2.daily_screen(pd.Timestamp(_d).date(), _pa, DEEP, ts=_tsa, model=_ma)
    _sb = S2.daily_screen(pd.Timestamp(_d).date(), _pb, DEEP, ts=_tsb, model=_mb)
    if _sa.empty or _sb.empty:
        continue
    _ka, _ = S2.select_pack(_sa, DEEP)
    _kb, _ = S2.select_pack(_sb, DEEP)
    _tot += 1
    _same += int(_ka == _kb)
print(f"same pack selected on {_same}/{_tot} screen days ({100*_same/max(_tot,1):.1f}%)")
print("=> the ~10% of days where the two disagree is what produces the P&L gap above.")

# %% [markdown]
# ## 15. What would make this wrong
#
# Ranked by size of the error each could introduce, all measured rather than
# asserted.
#
# | # | risk | size | status |
# |---|------|------|--------|
# | 1 | **Node degeneracy** — a pack window inside one log-linear segment. The zero-convexity control is structurally blind to it and `CA≥0` / `corr(CA,T1²)` *reward* it. | unbounded; 15.8bp median at 2019 ranks 1–4 | **gated out** (`spans_window`, `n_nodes_inside`) |
# | 2 | **Wrong futures source.** The production builder fetches from `BARCHART_TOS_LIVE_STIRF-RL` (22:xx intraday, depth 20 on zero local dates), not the 17:00 EOD settle. | would be a 52–57-request-per-date crawl AND the wrong mark | **fixed by injection**; guard asserts 0 requests |
# | 3 | **Settle-timing.** Barchart "EOD" is ~2h after the CME settle. | 0.6–1.6bp/pack-day; **30.1%** of the CA level at ranks 1–8, **6.7%** at 13–17 | irreducible; the reason to trade deep |
# | 4 | **Selection fragility.** A 0.03bp CA difference flips the ranked winner on ~10% of screen days. | ~2× on total P&L | **reported, not fixed** — the dominant caveat |
# | 5 | **IMM roll off-by-one.** The `SFRCM` ladder rolls on the IMM date; the pack universe does not. | 8 of 10 network reaches in a full build | fixed (`instrument_count`) |
# | 6 | **Swap-leg frequency.** `usd_irs` quotes annual fixed; Citi specifies Q/Q. | up to 12bp (`0.375·r²`) | fixed upstream (`matched_forward_swap_rate`) |
# | 7 | **Stale deferred settles.** | `stale_run` 0.055%, 4 catch-up dates; removing them moves deep hedged P&L by ~$0.8mn | **reported both ways** |
# | 8 | **Universe truncation.** Golds needs depth 20 → 681 dates whose longest contiguous run (309 days) is entirely inside ZIRP. | Golds cannot be backtested daily | **documented gap** |
#
# ### The gap, stated plainly
#
# Golds (rank 17) is **reproduced on the tie-out date to −0.56bp** but **cannot
# be backtested**: it needs a 20-contract strip, which exists on 681 dates whose
# longest gap-free run is 2019-09-13..2020-12-16 — 309 days, entirely inside
# ZIRP, where the adjustment is ~0 and a 252-day z-score leaves ~57 tradeable
# days. That is a data-coverage limit, not a modelling one; the code produces
# Citi's exact 13 rows the moment the strip is warm, as section 8 demonstrates.

# %%
print("network calls blocked over the whole notebook:", network_calls_blocked())
print("\nCoverage summary")
print(f"  panel            {len(PANEL):,} rows x {PANEL['date'].nunique():,} dates")
print(f"  gate-passed      {len(GATED):,} rows ({100*len(GATED)/len(PANEL):.1f}%)")
print(f"  deep backtest    {len(DEEP_DAYS)} days {DEEP_DAYS[0].date()}..{DEEP_DAYS[-1].date()}")
print(f"  Blues reachable  {PANEL[PANEL['rank']==13]['date'].nunique():,} dates")
print(f"  Golds reachable  {PANEL[PANEL['rank']==17]['date'].nunique():,} dates")
