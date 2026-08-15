# %% [markdown]
# # Strategy 2 grid search — short pack convexity against a butterfly, every cell
#
# The companion to `strat2_sofr_convexity_backtest.ipynb` (one config through the
# production engine) and to `strat2_ca_diagnostics.ipynb` (is the convexity
# adjustment itself measured correctly). This notebook runs the whole
# `pack x fly x weighting x sizing x window x entry x hold` space on one ledger
# and ranks it — and then asks whether the winner survives being told how many
# cells were searched and being re-priced by the real engine.
#
# ## What Citi actually said
#
# Verbatim, from `docs/convexityrv/research/01-citi-stir-convexity-vs-butterfly.md`
# (§5.2, [W-JAN13] p.13):
#
# > "One way to hedge this risk is to buy vol, such as a 3y1y swaption or a 3x4
# > cap, against selling Blues CA. But this will obviously reduce the total carry
# > of the package. **Instead, we propose hedging our short Blues CA by selling a
# > 2s5s10s fly.** The motivation for this hedging strategy is that **3y1y vol is
# > mostly driven by expectations of monetary policy, and therefore should be
# > directional with the valuations of 5s on the curve.**"
#
# > "Importantly, **selling the 2s5s10s fly as a hedge has the advantage of
# > positive carry, unlike buying volatility.** The 3m carry/roll on the short
# > 2s5s10s fly is about +4bp over 3m."
#
# > "we regressed Blues CA on 2y, 5y and 10y swap rates ... the fitted value
# > effectively being a 2s5s10s fly with -0.73/1/-0.47 DV01 weights"
#
# and the sizing rule, §5.4: `fly_belly_DV01 = CA_DV01 * beta / 100`.
#
# ## The SOFR port, and what it can and cannot test
#
# Citi's note is Eurodollar-era (Jan-2017, Blues = the 13th–16th contracts,
# `T1 ~ 3.25y`). This is SR3 on `USD-SOFR-1D`, 2019–2023. Three consequences,
# all of them limits rather than choices:
#
# 1. **Depth.** The offline `BARCHART_STIRF-RL` store carries a dense daily strip
#    of 13 quarterly contracts, so pack windows 1..10, `T1` from 0.37y to 2.38y.
#    Citi's own screen runs windows 5..17. **Blues and Golds — where Citi traded
#    this — are not in daily offline reach and are NOT tested here.**
# 2. **Span.** SR3 daily settles collapse after 2023-09 (2019: 252 dates, 2020:
#    253, 2021: 252, 2022: 252, 2023: 183, then 1–2 per year). The panel ends
#    2023-12-27 and the engine certification is cut at 2023-09-15.
# 3. **The convexity adjustment must be measured before it can be traded.** The
#    matched swap is quarterly/quarterly on BOTH legs (Citi: *"both fixed and
#    floating legs of this swap have a quarterly payment frequency"*). The repo's
#    `usd_irs` spec quotes an ANNUAL fixed leg, and the gap is `+3q^2/8` — up to
#    **12.0bp** on this sample. Section 4 shows that the stored
#    `strat2_panel.parquet` is the annual variant and rebuilds the panel from the
#    quarterly one.
#
# ## The hypothesis this grid exists to test
#
# A pack's convexity adjustment is `0.5 * sigma^2 * mean(T1^2)` — driven by
# volatility at the pack's **own** expiry, `T1` years out. A *spot* 2s5s10s is a
# proxy for vol at the front of the curve. So the sharp, falsifiable claim is:
#
# > **A forward-starting fly whose forward start matches the pack's expiry should
# > hedge that pack better than the spot fly, and the improvement should grow
# > with `T1`.**
#
# Section 5 reads that straight off a `(pack T1) x (fly forward start)` matrix.
# The 5Y forward start is carried as a deliberate **over-shoot control**: no pack
# in reach has an expiry near it, so if the hypothesis is real the 5Y column must
# be worse than 2Y/3Y, not better.

# %%
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import dataclasses
import datetime
import json
import math
import pathlib
import sys
import time
import warnings

import numpy as np
import pandas as pd

_REPO = (pathlib.Path(__file__).resolve().parents[3] if "__file__" in dir()
         else pathlib.Path.cwd().parents[2])
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import plotly.io as pio

pio.renderers.default = "plotly_mimetype+notebook_connected"
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from BT.trade_dashboard import compare_curves, trade_dashboard

import RVUtils.ConvexityRV.ca_diagnostics as CAD
from RVUtils.ConvexityRV.packs import DV01_PER_CONTRACT
from RVUtils.ConvexityRV.strat2_fly_universe import (
    DV01_NEUTRAL_WINGS,
    FLY_SHAPES,
    FORWARD_STARTS,
    fly_by_id,
    fly_carry_series,
    fly_rate_series,
    fly_regression,
    fly_universe,
    legs_wide,
)
from RVUtils.ConvexityRV.strat2_grid import (
    COST_MULTIPLIERS,
    Strat2GridConfig,
    constant_contract_dca,
    effectiveness_matrix,
    hypothesis_slope,
    prepare_inputs,
    rank_following_ca,
    run_grid,
    simulate_cell,
)
import RVUtils.ConvexityRV.strat2_sofr_convexity as S2

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 90)
pd.set_option("display.max_rows", 250)
warnings.filterwarnings("ignore", category=FutureWarning)

DATA = _REPO / "notebooks" / "data" / "convexity_rv"
print("repo:", _REPO)
print("data:", DATA, "exists:", DATA.exists())

# %% [markdown]
# ## 1. CONFIG — every knob, documented inline
#
# Nothing below is tuned on its own P&L. The two settings that ARE choices
# rather than reproductions are called out: `CA_FILTER` (a data-quality decision
# forced on us by stale Barchart settles) and `COST_BP_ROUNDTRIP` (Citi excludes
# costs; a strategy scored only at zero cost is not scored).

# %%
@dataclasses.dataclass(frozen=True)
class GridSearchConfig:
    """Every knob in this notebook."""

    # ------------------------------------------------------------------ data
    ca_quality_parquet: str = "strat2_ca_quality.parquet"
    """Per-pack-day CA scan written by `scripts/strat2_ca_quality_scan.py`.
    Carries BOTH conventions (`ca_observed_bp` = quarterly/quarterly, correct;
    `ca_annual_bp` = the annual-fixed variant) plus the zero-convexity control
    `ca_synthetic_bp` and the quality flags. **This, not
    `strat2_panel.parquet`, is the source of truth for CA.**"""

    legacy_panel_parquet: str = "strat2_panel.parquet"
    """The older CA panel. Loaded ONLY as a cross-check that it is the annual
    variant. **Optional** — the annual-vs-quarterly comparison in section 4.1 is
    made from the quality scan's own two columns and does not need this file, so
    the notebook still runs if it has been rebuilt or removed."""

    fly_legs_parquet: str = "strat2_fly_legs.parquet"
    """`date x tenor` par rates (percent) and 3M carry+roll (bp) for the 40 leg
    tenors the fly universe needs. The stored primitive: every fly at every
    weighting is arithmetic on top, which is what makes a 45-fly grid affordable."""

    fly_panel_parquet: str = "strat2_fly_panel.parquet"
    """Derived 45-fly panel at 50/50 wings. Used for the carry cross-section only."""

    curve_break: datetime.date = datetime.date(2019, 7, 8)
    """**Hard start.** Before this, `USD-SOFR-1D` is built on 26 nodes with the
    second at start+735d, so on 520 pack-days a SINGLE node interval swallows the
    whole pack window: the curve's own IMM forwards are then identical to machine
    precision, `CA_synthetic` is exactly 0, and the zero-convexity control passes
    vacuously while `CA_observed` ranges -91.6..+27.6bp. Measured node counts:
    2019-06-20 -> 26, 2019-07-01 -> 33, 2019-07-08 -> 45. Everything before the
    break is discarded, not flagged."""

    ca_filter: str = "survive"
    """Which pack-days may be ENTERED. `"none"` | `"noarb"` (drop CA<0 and
    convention failures) | `"survive"` (all of the diagnostics module's flags:
    negative CA, convention, implausible vol, no control power).

    **Applied as an ENTRY GATE, not as a hole in the return series.** A pack that
    fails on a day cannot be struck that day; a position already on keeps marking
    against the full CA series, because that is what it would have marked at.
    NaN-ing the CA series itself was tried and is not viable: it punches holes
    that a `min_periods=252` rolling window never fills, and every 1-year z-score
    in the screen — including Citi's own `vs model` metric — goes to zero finite
    observations. Section 4 shows both."""

    # ------------------------------------------------------------- universe
    ranks: tuple = (2, 3, 4, 5, 6, 7, 8, 9, 10)
    """Rolling pack windows to search. Rank 1 is excluded: its `T1 ~ 0.12y` makes
    `sigma = sqrt(2*CA/mean(T1^2))` explode, which is why Citi's tables start at
    Reds. Rank 2..10 spans `T1` 0.37y..2.38y."""

    shapes: tuple = tuple(name for name, _ in FLY_SHAPES)
    forward_starts: tuple = tuple(FORWARD_STARTS)
    """9 shapes x 5 forward starts = 45 flies. 5Y is the over-shoot control."""

    citi_fly: str = "2s5s10s"
    """Citi's published hedge — the reference cell, quoted on every table."""

    # ------------------------------------------------------------- the grid
    regression_windows: tuple = (63, 126, 252)
    regression_bases: tuple = ("levels", "changes")
    """`"levels"` is Citi's, verbatim. `"changes"` is the same estimator on first
    differences. On 2019-2023 SOFR the level fit is a textbook spurious
    regression, so both are run and the difference is a result, not a robustness
    check."""

    regression_targets: tuple = ("rank", "label")
    """`"rank"` = the rolling colour (Citi's "Blues CA", years of history, carries
    IMM roll steps). `"label"` = the constant-contract history of the specific
    pack, cleaner but structurally starved at deep ranks."""

    entry_rules: tuple = ("always", "ca_z", "vs_model_z", "carry")
    z_entry: float = 1.0
    holding_days_axis: tuple = (21, 63, 126)
    rebalance_days: int = 21
    holding_days: int = 63
    """~3 months. Citi's realised holds were ~4m (Blues) and ~2m (Greens); carry
    is quoted over 3m."""

    ca_dv01: float = 100_000.0
    """Citi's flagship size: 1000 packs against a $1bn swap."""

    cost_bp_roundtrip: float = 0.25
    """bp of the traded spread, charged once per epoch on `CA_DV01 + |belly|`.
    Citi excludes costs explicitly, so the `0x` column reproduces their
    convention; every cell is also scored at 0.5x / 1x / 2x."""

    primary_cost_multiplier: float = 1.0
    """The multiplier every headline number is quoted at."""

    include_gamma: bool = False
    """Whether the headline P&L folds in the estimated second-order term. It is
    always computed and reported (`gamma_pnl`, `gamma_share`) either way."""

    # ------------------------------------------------------- certification
    futures_cutoff: datetime.date = datetime.date(2023, 9, 15)
    """No engine epoch may END after this: SR3 daily settles collapse to 1-2
    prints a year afterwards and `QueryDrivenBacktest.run()` swallows the
    resulting exceptions silently."""

    n_certify: int = 3
    """How many top cells go through the real engine."""

    top_n: int = 15
    """Rows in the headline table."""


CFG = GridSearchConfig()
print(json.dumps({k: (str(v) if isinstance(v, (datetime.date, tuple)) else v)
                  for k, v in dataclasses.asdict(CFG).items()}, indent=1))

# %% [markdown]
# ## 2. Sign probes — measured live, every execution
#
# Four signs decide whether this whole notebook is a hedge or a doubled
# exposure. Each is re-measured against the pricing engine on every run, and
# each assertion exists because getting it wrong produces a plausible-looking
# P&L rather than an error.
#
# 1. **A paid fly belly is `+belly_DV01 * d(fly_bp)`.** The resolved package's
#    per-leg PV01 is exactly `sign_mapped_w_i * bpv`, so
#    `dP&L = sum_i PV01_i * dr_i = belly_DV01 * d(fly_bp)`. Sign `+`, not `-`.
# 2. **`bpv < 0` on a FLY is the exact mirror of `bpv > 0`.** Most cells in this
#    grid come back with a NEGATIVE fitted beta — i.e. a *received* belly — and
#    that path has to be verified before any of them can be certified.
# 3. **The fly rate is linear in the leg rates** at machine precision, which is
#    what licences the whole panel simulation.
#
# A fourth — **`direction="long_ca"` is the exact negative of `"short_ca"`**, the
# clean negative control on the ledger itself — needs the panel inputs and is
# therefore asserted in §6.1, at the first point in the notebook where it can be.

# %%
from BT.data_handler import TimeGrid
from BT.query_actions import AddQueryAction
from BT.query_engine import QueryDrivenBacktest
from BT.query_strategy import QueryStrategy
from BT.triggers import DateTrigger, DateTriggerRequirements
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapStructure import IRSwapStructure
from Query.IRSwaps.IRSwapValue import IRSwapValue

CURVE = "USD-SOFR-1D"
_SWAPS_MDP = IRSwapsMDP(source=S2.Strat2Config().swap_source)
_PROBE_DATES = [datetime.date(2022, 9, 12), datetime.date(2022, 9, 13),
                datetime.date(2022, 9, 14), datetime.date(2022, 9, 15)]


def _fly_probe(bpv: float, tenors=("1Y", "2Y", "3Y"), w=(0.5, 0.5)) -> pd.Series:
    """Hold one FLY package over four dates and return its daily MTM."""
    q = IRSwapQuery(
        structure=IRSwapStructure.FLY, value=IRSwapValue.NPV, curve=CURVE,
        structure_kwargs={"front_tenor": tenors[0], "belly_tenor": tenors[1],
                          "back_tenor": tenors[2],
                          # fresh list: _build_fly REWRITES risk_weights in place
                          "risk_weights": [float(w[0]), 1.0, float(w[1])],
                          "bpv": float(bpv)},
        tags=("probe",))
    strat = QueryStrategy(name=f"fly_{bpv:+.0f}", triggers=[
        DateTrigger(DateTriggerRequirements(dates=[_PROBE_DATES[0]]),
                    actions=[AddQueryAction(query=q, meta={"tags": ["probe"]})])])
    strat.mdps = {"IRS": _SWAPS_MDP}
    strat.default_mdp = _SWAPS_MDP
    bt = QueryDrivenBacktest(time_grid=TimeGrid([pd.Timestamp(d) for d in _PROBE_DATES]),
                             strategy=strat, mdp=_SWAPS_MDP, show_progress=False)
    bt.run()
    s = pd.Series(bt.mtm_history)
    s.index = pd.to_datetime(s.index)
    return s


_t0 = time.time()
_pos = _fly_probe(+21_400.0)
_neg = _fly_probe(-21_400.0)
_mirror = float((_pos + _neg).abs().max())
print(f"FLY bpv=+21400 MTM: {_pos.round(1).to_dict()}")
print(f"FLY bpv=-21400 MTM: {_neg.round(1).to_dict()}")
print(f"max |pos + neg| = {_mirror:.6g}   ({time.time() - _t0:.1f}s)")
assert _mirror < 1e-6, "a FLY with bpv<0 is NOT the mirror of bpv>0 -- received-belly cells are unsafe"
assert float(_pos.abs().max()) > 0, "the FLY probe never priced"

# forward-start legs must price at all, or the whole forward-start axis is fiction
_fwd = _fly_probe(+21_400.0, tenors=("2Yx1Y", "2Yx2Y", "2Yx3Y"))
assert np.isfinite(_fwd).all() and float(_fwd.abs().max()) > 0, "forward-start fly did not price"
print(f"forward-start FLY (2Yx1Y/2Yx2Y/2Yx3Y) terminal MTM: {float(_fwd.iloc[-1]):,.0f}")

# %%
# Probe 1 (continued): the paid belly moves WITH the fly, and the panel's linear
# proxy has the same sign day by day.
_legs_long = pd.read_parquet(DATA / CFG.fly_legs_parquet)
LEGS = legs_wide(_legs_long, "rate_pct")
LEG_CARRY = legs_wide(_legs_long, "carry_roll_bp")
_sp = fly_by_id("1s2s3s")
_dfly = fly_rate_series(LEGS, _sp, 0.5, 0.5).reindex(_pos.index).diff()
_pred = (_dfly * 21_400.0).dropna()
_eng = _pos.diff().dropna()
_cmp = pd.DataFrame({"d_fly_bp": _dfly.reindex(_pred.index),
                     "panel +belly*dfly ($)": _pred,
                     "engine d(NPV) ($)": _eng})
display(_cmp.round(1))
assert (np.sign(_cmp["panel +belly*dfly ($)"]) ==
        np.sign(_cmp["engine d(NPV) ($)"])).all(), \
    "paid-belly sign disagrees with the engine -- the fly leg would DOUBLE the exposure"
print("paid belly: engine and panel agree in sign on every probe day (the '+' convention holds)")

# fly rate is linear in the legs, to machine precision -- the licence for the panel sim
_manual = 100.0 * (-0.5 * LEGS["1Y"] + LEGS["2Y"] - 0.5 * LEGS["3Y"])
_lin = float((fly_rate_series(LEGS, _sp, 0.5, 0.5) - _manual).abs().max())
print(f"max |fly_rate_series - manual| over {len(LEGS)} dates = {_lin:.3g} bp")
assert _lin < 1e-9

# %% [markdown]
# ## 3. The CA convention tie-out — the zero-convexity control
#
# **A notebook that computes a convexity adjustment must prove its own
# conventions before it reports a single dollar of P&L.**
#
# The control: substitute the CURVE's own IMM-to-IMM forward rates for the
# futures rates. Those forwards carry no convexity adjustment by construction,
# so the resulting `CA_synthetic` must be ~0. Anything it is not is OUR error —
# wrong swap frequency, wrong dates, wrong day count — not the market's.
#
# **The control has a blind spot, and it is the single most important caveat in
# the CA work.** Where the discount curve has no node inside the pack window,
# the four "forwards" are the same number to machine precision and
# `CA_synthetic` is *exactly* zero — a perfect pass that tests nothing. That is
# why the probe dates below are drawn from the post-break era AND required to
# have real control power (`fwd_spread_bp` large): a control run on a
# node-starved date is vacuous.

# %%
QUAL = pd.read_parquet(DATA / CFG.ca_quality_parquet)
QUAL["date"] = pd.to_datetime(QUAL["date"])
print(f"CA quality scan: {QUAL.shape}  "
      f"{QUAL['date'].min():%Y-%m-%d}..{QUAL['date'].max():%Y-%m-%d}  "
      f"{QUAL['date'].nunique()} dates, ranks {sorted(QUAL['rank'].unique())}")

_post = QUAL[QUAL["date"] >= pd.Timestamp(CFG.curve_break)]
_powerful = _post[(_post["fwd_spread_bp"] > 50.0) & _post["rank"].isin(CFG.ranks)]
_probe_days = sorted(_powerful["date"].drop_duplicates().sample(
    6, random_state=20230609).tolist())
print("tie-out dates (post-break, control power > 50bp of forward spread):",
      [f"{d:%Y-%m-%d}" for d in _probe_days])

_s2cfg = S2.Strat2Config()
_rows = []
for _d in _probe_days:
    _asof = _d.date()
    _pricer = _SWAPS_MDP.get_pricer({"curve_name": CURVE, "timestamp": _asof,
                                     "offline": True})
    _ref = _pricer.reference_date()
    _ref = _ref.date() if hasattr(_ref, "date") else _ref
    assert _ref == _asof, (f"the store served a {_ref} curve for {_asof} -- marking a "
                           "stale curve against live settles manufactures a CA move")
    _specs = {s.label: s for s in S2.pack_windows(_asof, _s2cfg)}
    _day = _post[_post["date"] == _d].set_index("pack")
    _fwd = CAD.imm_forward_map(_pricer, sorted({c for s in _specs.values()
                                                for c in s.contracts}))
    for _lbl, _sp2 in _specs.items():
        if (_lbl not in _day.index or _sp2.rank not in CFG.ranks
                or _day.at[_lbl, "fwd_spread_bp"] <= 50.0):
            continue
        # the zero-convexity counterfactual, rebuilt from the curve, not read back
        _syn = CAD.synthetic_pack_rate(_pricer, _sp2.contracts)
        _swap = S2._swap_par_rate(_pricer, CURVE, effective_date=_sp2.swap_start,
                                  maturity_date=_sp2.swap_end)   # QUARTERLY/QUARTERLY
        _f4 = [_fwd[c] for c in _sp2.contracts]
        _rows.append({
            "date": _asof, "pack": _lbl, "rank": _sp2.rank,
            "ca_synthetic_recomputed_bp": (_syn - _swap) * 100.0,
            "ca_synthetic_stored_bp": float(_day.at[_lbl, "ca_synthetic_bp"]),
            "annuity_weight_prediction_bp": CAD.annuity_weight_residual_bp(_f4, _swap),
            "ca_observed_bp": float(_day.at[_lbl, "ca_observed_bp"]),
            "control_power_bp": CAD.control_power_bp(_f4),
            "n_nodes_inside": float(_day.at[_lbl, "n_nodes_inside"]),
        })
TIEOUT = pd.DataFrame(_rows)
TIEOUT["delta_vs_stored_bp"] = (TIEOUT["ca_synthetic_recomputed_bp"]
                               - TIEOUT["ca_synthetic_stored_bp"])
TIEOUT["unexplained_bp"] = (TIEOUT["ca_synthetic_recomputed_bp"]
                            - TIEOUT["annuity_weight_prediction_bp"])
display(TIEOUT.round(6))

_max_delta = float(TIEOUT["delta_vs_stored_bp"].abs().max())
_max_syn = float(TIEOUT["ca_synthetic_recomputed_bp"].abs().max())
_max_unexp = float(TIEOUT["unexplained_bp"].abs().max())
print(f"\nmax |recomputed - stored CA_synthetic| = {_max_delta:.3g} bp   "
      f"(the scan is reproduced from the curve, not read back)")
print(f"max |CA_synthetic| on control-powered, TRADED ranks = {_max_syn:.4f} bp "
      f"vs |CA_observed| median {TIEOUT['ca_observed_bp'].abs().median():.2f} bp")
print(f"max |CA_synthetic - annuity-weighting prediction| = {_max_unexp:.4f} bp -- the "
      f"residual is a KNOWN second-order term (equal-weighted pack rate vs "
      f"annuity-weighted par rate), predicted with no free parameter, not a "
      f"convention error")
assert _max_delta < 1e-6, "the stored quality scan does not reproduce"
assert _max_syn < 1.5, f"convention residual {_max_syn:.3f}bp is too large to trade on"
assert _max_unexp < 1.0, (f"{_max_unexp:.3f}bp of the control residual is NOT the "
                          "annuity-weighting term -- that would be a real convention bug")
assert (TIEOUT["n_nodes_inside"] > 0).all(), "a probe date had no curve node in the window"

# %%
# The control across the WHOLE sample, and its blind spot made explicit.
_syn_all = _post["ca_synthetic_bp"]
_stat = pd.Series({
    "rows (post-break)": len(_post),
    "CA_synthetic mean (bp)": float(_syn_all.mean()),
    "CA_synthetic median (bp)": float(_syn_all.median()),
    "CA_synthetic sd (bp)": float(_syn_all.std(ddof=1)),
    "CA_synthetic |p95| (bp)": float(_syn_all.abs().quantile(0.95)),
    "CA_observed mean (bp)": float(_post["ca_observed_bp"].mean()),
    "CA_observed sd (bp)": float(_post["ca_observed_bp"].std(ddof=1)),
    "residual / |CA_observed| median (|CA|>1bp)": float(
        (_post.loc[_post["ca_observed_bp"].abs() > 1, "ca_synthetic_bp"].abs()
         / _post.loc[_post["ca_observed_bp"].abs() > 1, "ca_observed_bp"].abs()).median()),
    "rows with node spanning whole window (control blind)": int(_post["node_spans_window"].sum()),
    "same, PRE-break (discarded)": int(QUAL.loc[QUAL["date"] < pd.Timestamp(CFG.curve_break),
                                                "node_spans_window"].sum()),
})
display(_stat.to_frame("value").round(4))

_pw = _post.copy()
_pw["power_bucket"] = pd.cut(_pw["fwd_spread_bp"], [-0.01, 1, 10, 50, 100, 1e9],
                             labels=["<1bp", "1-10", "10-50", "50-100", ">100"])
_by_power = _pw.groupby("power_bucket", observed=True).agg(
    n=("ca_synthetic_bp", "size"),
    syn_abs_p95=("ca_synthetic_bp", lambda s: float(s.abs().quantile(0.95))),
    obs_mean=("ca_observed_bp", "mean"))
print("\nControl residual conditioned on control POWER "
      "(|p95| near zero at low power is the blind spot, not a pass):")
display(_by_power.round(3))

# %% [markdown]
# ## 4. Data — the CA panel, and what the swap frequency is worth
#
# ### 4.1 Annual fixed vs quarterly/quarterly
#
# The matched swap must be quarterly on **both** legs — Citi states it verbatim:
# *"both fixed and floating legs of this swap have a quarterly payment
# frequency"*. The repo's `usd_irs` spec quotes an ANNUAL fixed leg, and the
# difference is the compounding gap: a 1y swap paying `a` annually matches one
# paying `q` quarterly when `(1 + q/4)^4 = 1 + a`, so `a = q + (3/8)q^2 + O(q^3)`
# and, with `q` in percent and the gap in bp, the scalings cancel to a bare
# **`gap_bp = 0.375 * r^2`** — no free parameter.
#
# This is not a rounding question. The bias is worst exactly where rates are
# highest, i.e. 2022–23, i.e. the only part of this sample with enough clean
# pack-days to trade.

# %%
_gap = (QUAL["ca_annual_bp"] - QUAL["ca_observed_bp"])
_pred = CAD.compounding_gap_bp(QUAL["swap_rate_qq"].to_numpy(float))
_x = np.asarray(_pred, dtype=float)
_y = (-_gap).to_numpy(float)                    # observed - annual = +0.375 r^2
_ok2 = np.isfinite(_x) & np.isfinite(_y)
_b = float(np.linalg.lstsq(_x[_ok2].reshape(-1, 1), _y[_ok2], rcond=None)[0][0])
print(f"annual-vs-QQ gap on {int(_ok2.sum()):,} pack-days:")
print(f"  mean {float(_gap.mean()):+.3f} bp, worst {float(_gap.abs().max()):.3f} bp")
print(f"  regression of the measured gap on the 0.375*r^2 prediction (no intercept): "
      f"slope {_b:.5f}  (1.0 = the prediction is exactly right)")
print(f"  residual sd {float(np.std(_y[_ok2] - _b * _x[_ok2])):.4f} bp")
assert abs(_b - 1.0) < 0.05, "the compounding gap is not 3q^2/8 -- the CA convention is unresolved"

_mm = QUAL.assign(year=QUAL["date"].dt.year, bias=_gap)
_by_year = _mm.groupby("year").agg(
    n=("bias", "size"),
    mean_annual_minus_QQ_bp=("bias", "mean"),
    worst_bp=("bias", lambda s: float(s.abs().max())),
    mean_QQ_CA_bp=("ca_observed_bp", "mean"),
    pct_negative_on_QQ=("ca_observed_bp", lambda s: 100 * float((s < 0).mean())),
    pct_negative_on_annual=("ca_annual_bp", lambda s: 100 * float((s < 0).mean())))
display(_by_year.round(3))
print("The last two columns are the practical cost: on the ANNUAL convention a further "
      "slice of the strip prints a NEGATIVE convexity adjustment, which is a "
      "no-arbitrage impossibility, purely because of the swap frequency.")

# cross-check the stored legacy panel, if it is still on disk
_legacy_path = DATA / CFG.legacy_panel_parquet
if _legacy_path.exists():
    LEGACY = pd.read_parquet(_legacy_path)
    LEGACY["date"] = pd.to_datetime(LEGACY["date"])
    _m = LEGACY.merge(QUAL[["date", "pack", "ca_annual_bp", "ca_observed_bp"]],
                      on=["date", "pack"], how="inner")
    print(f"\nlegacy {CFG.legacy_panel_parquet}: {len(_m):,} overlapping rows")
    print(f"  max |ca_bp - ca_ANNUAL_bp|    = "
          f"{float((_m['ca_bp'] - _m['ca_annual_bp']).abs().max()):.3g} bp")
    print(f"  max |ca_bp - ca_QUARTERLY_bp| = "
          f"{float((_m['ca_bp'] - _m['ca_observed_bp']).abs().max()):.3f} bp")
else:
    print(f"\n{CFG.legacy_panel_parquet} is not on disk -- cross-check skipped. "
          "Nothing below depends on it.")
print("\nEverything below is built on ca_observed_bp (quarterly/quarterly).")

# %% [markdown]
# ### 4.2 The rebuilt panel, the curve break, and the quality filter
#
# Rejection counts are shown, not summarised. `flag_negative_ca` is the
# important one: a negative convexity adjustment is a no-arbitrage
# impossibility, and on this data it fires on stale Barchart settles for
# deferred contracts, **not** on anything a convention could explain — 99.6% of
# the violations have `|CA_synthetic| <= 1bp`.

# %%
def quality_to_panel(q: pd.DataFrame) -> pd.DataFrame:
    """Quality-scan rows -> the long panel schema `prepare_inputs` expects."""
    return pd.DataFrame({
        "date": q["date"], "rank": q["rank"].astype(int), "pack": q["pack"],
        "colour": q["colour"], "swap_start": q["swap_start"], "swap_end": q["swap_end"],
        "pack_rate": q["pack_rate_futures"],      # mean(100 - SR3 price), percent
        "swap_rate": q["swap_rate_qq"],           # QUARTERLY/QUARTERLY matched swap
        "ca_bp": q["ca_observed_bp"],             # the correct convention
        "time_weight": q["time_weight"], "t_mid": q["t_mid"],
    }).reset_index(drop=True)


_FLAGS = ["flag_negative_ca", "flag_convention", "flag_implausible_vol",
          "flag_no_control_power", "flag_vol_ill_conditioned"]
_pre = QUAL[QUAL["date"] < pd.Timestamp(CFG.curve_break)]
print(f"pack-days before the curve break {CFG.curve_break} : {len(_pre):,}  "
      f"({100 * len(_pre) / len(QUAL):.1f}%)  -- DISCARDED, not flagged")
print(f"  of which the control was structurally blind on: "
      f"{int(_pre['node_spans_window'].sum()):,}")
print(f"pack-days retained for the search: {len(_post):,}\n")

_rej = pd.DataFrame({
    "rejected": {f: int(_post[f].sum()) for f in _FLAGS},
    "% of post-break": {f: 100 * float(_post[f].mean()) for f in _FLAGS},
})
_rej.loc["-- ok (neg|conv|vol)"] = [int((~_post["ok"]).sum()), 100 * float((~_post["ok"]).mean())]
_rej.loc["-- survive (all flags)"] = [int((~_post["survive"]).sum()),
                                      100 * float((~_post["survive"]).mean())]
print("REJECTION COUNTS, post-break:")
display(_rej.round(2))

_yr = _post.assign(year=_post["date"].dt.year).groupby("year")[
    _FLAGS + ["ok", "survive"]].mean().mul(100).round(1)
_yr["n_pack_days"] = _post.assign(year=_post["date"].dt.year).groupby("year").size()
print("by year (% of pack-days flagged; `survive` is % PASSING):")
display(_yr)

_byrank = _post.groupby("rank")[["flag_negative_ca", "survive"]].mean().mul(100).round(1)
_byrank["mean_T1_y"] = _post.groupby("rank")["t1_first"].mean().round(2)
_byrank["mean_CA_bp"] = _post.groupby("rank")["ca_observed_bp"].mean().round(2)
print("by rank:")
display(_byrank)

# %%
_gate_mask = {
    "none": pd.Series(True, index=_post.index),
    "noarb": ~(_post["flag_negative_ca"] | _post["flag_convention"]),
    "survive": _post["survive"].astype(bool),
}[CFG.ca_filter]
print(f'CA_FILTER = "{CFG.ca_filter}"  ->  {int(_gate_mask.sum()):,} of {len(_post):,} '
      f'pack-days are ENTERABLE ({100 * _gate_mask.mean():.1f}%)')

PANEL_RAW = quality_to_panel(_post)                     # marks: continuous
PANEL_GATE = quality_to_panel(_post[_gate_mask])        # entries: gated
PANEL_STRICT = quality_to_panel(_post[_post["survive"].astype(bool)])

_s2 = S2.Strat2Config()
_t0 = time.time()
INP_RAW = prepare_inputs(PANEL_RAW, LEGS, carry=LEG_CARRY, strat2_cfg=_s2)
INP = dataclasses.replace(INP_RAW, panel=PANEL_GATE)      # HEADLINE: gated entries
INP_STRICT = prepare_inputs(PANEL_STRICT, LEGS, carry=LEG_CARRY, strat2_cfg=_s2)
print(f"prepare_inputs x2: {time.time() - _t0:.1f}s")
print(f"common date axis: {len(INP.dates)} days "
      f"{INP.dates.min():%Y-%m-%d}..{INP.dates.max():%Y-%m-%d}")

_z = pd.DataFrame({
    "finite ca_z1y": [int(np.isfinite(x.ca_z1y.to_numpy()).sum()) for x in (INP_RAW, INP, INP_STRICT)],
    "finite vs_model_z1y": [int(np.isfinite(x.vs_model_z1y.to_numpy()).sum()) for x in (INP_RAW, INP, INP_STRICT)],
    "finite roll_3m": [int(np.isfinite(x.roll_3m.to_numpy()).sum()) for x in (INP_RAW, INP, INP_STRICT)],
    "enterable days at rank 5": [int(x.rank_labels(5).notna().sum()) for x in (INP_RAW, INP, INP_STRICT)],
}, index=["INP_RAW (no gate)", "INP (entry gate, headline)", "INP_STRICT (holes in CA)"])
display(_z)
print("\nThis is why the filter is an ENTRY GATE. Punching holes in the CA series "
      "(INP_STRICT) takes every 1-year z-score to ZERO finite observations, which "
      "silently disables the `ca_z` and `vs_model_z` entry rules -- Citi's own "
      "'almost three sigmas wide to the model' metric. INP_STRICT is kept as a "
      "robustness run, not as the headline.")

# %% [markdown]
# ### 4.3 The fly panel

# %%
FLY_PANEL = pd.read_parquet(DATA / CFG.fly_panel_parquet)
FLY_PANEL["date"] = pd.to_datetime(FLY_PANEL["date"])
SPECS = {s.fly_id: s for s in fly_universe()}
print(f"fly panel {FLY_PANEL.shape}: {FLY_PANEL['fly_id'].nunique()} flies, "
      f"{FLY_PANEL['date'].nunique()} dates; leg panel {LEGS.shape}")
assert len(SPECS) == len(CFG.shapes) * len(CFG.forward_starts) == 45
assert not LEGS.reindex(INP.dates).isna().any().any(), "a leg tenor is missing on a panel date"

_carry_x = (FLY_PANEL[FLY_PANEL["date"].isin(INP.dates)]
            .pivot_table(index="shape", columns="forward_start_y",
                         values="carry_roll_3m_bp", aggfunc="mean"))
print("\nMean 3m carry+roll (bp) of a PAID belly at 50/50 wings, over the sample. "
      f"Citi claims about +4bp for a SOLD (received-belly) spot 2s5s10s, i.e. "
      f"{-_carry_x.loc[CFG.citi_fly, 0.0]:+.2f}bp here:")
display(_carry_x.round(2))

# %% [markdown]
# ## 5. The hedge-effectiveness surface — does matching the forward start help?
#
# For every (pack rank, fly forward start) pair: regress the pack's
# **constant-contract daily `dCA`** on the fly's daily change and report `R^2`.
# Constant-contract matters — the naive rank-following `diff()` jumps on every
# IMM roll and those jumps would enter as unexplained CA variance, biasing each
# rank's `R^2` down by a different amount.
#
# Wings are pinned at 50/50 so the columns compare *instruments*, not *fits*.
#
# **In-sample OLS variance reduction is identically `R^2`**, which is why the
# second surface below is the REALISED variance reduction from the traded
# ledger: rolling regression weights fitted only on history, Citi's `beta/100`
# sizing, epoch weights frozen at entry. That number can be — and mostly is —
# negative.

# %%
_t0 = time.time()
EFF = {}
for _shape in CFG.shapes:
    EFF[_shape] = effectiveness_matrix(INP_RAW, shape=_shape, ranks=CFG.ranks,
                                       forward_starts=CFG.forward_starts,
                                       weighting="dv01_neutral")
print(f"effectiveness matrices: {time.time() - _t0:.1f}s")
_fs_cols = [c for c in EFF[CFG.citi_fly].columns if c.startswith("fs_")]
#: rank -> mean first-expiry T1 in years, the axis every table is read on
_t1map = {r: float(EFF[CFG.citi_fly].loc[r, "T1_years"]) for r in CFG.ranks}

print(f"\n--- {CFG.citi_fly} (Citi's published hedge) : R^2 of constant-contract dCA on d(fly) ---")
display(EFF[CFG.citi_fly].round(4))

_peak = pd.DataFrame({s: m[_fs_cols].max(axis=1) for s, m in EFF.items()})
_best_shape = _peak.mean().idxmax()
print(f"--- {_best_shape} (the best shape on this sample) ---")
display(EFF[_best_shape].round(4))

EFF_ALL = pd.concat(EFF, names=["shape"])
display(EFF_ALL[_fs_cols].groupby(level="shape").mean().round(4)
        .sort_values("fs_0Y", ascending=False)
        .rename_axis("mean R^2 over ranks, by shape"))

# %%
HYP = hypothesis_slope(EFF)
print("*** THE HYPOTHESIS TEST ***")
print("  prediction: the pack T1 at which a fly is most effective tracks its")
print("              forward start one-for-one, i.e. slope ~ +1.0")
print(f"  measured over {HYP['n']} (shape, forward-start) cells:")
print(f"    slope = {HYP['slope']:+.4f} years of pack T1 per year of forward start")
print(f"    corr  = {HYP['corr']:+.4f}")
print(f"  mean PEAK R^2 by forward start: "
      f"{ {k: round(v, 4) for k, v in HYP['peak_r2_by_start'].items()} }")

_m = EFF[CFG.citi_fly]
_fs_vals = np.array([float(c[3:-1]) for c in _fs_cols])
_argmax_fs = np.array([_fs_vals[np.nanargmax(_m.loc[r, _fs_cols].to_numpy(float))]
                       if np.isfinite(_m.loc[r, _fs_cols].to_numpy(float)).any() else np.nan
                       for r in _m.index])
_ok = np.isfinite(_argmax_fs) & np.isfinite(_m["T1_years"].to_numpy())
print(f"\n  corr(pack T1, argmax forward start) on {CFG.citi_fly} alone = "
      f"{np.corrcoef(_m['T1_years'].to_numpy()[_ok], _argmax_fs[_ok])[0, 1]:+.3f}")
print("  spot-minus-best lift per rank:")
for _r in _m.index:
    _v = _m.loc[_r, _fs_cols].to_numpy(float)
    if np.isfinite(_v).any():
        print(f"    rank {_r:2d}  T1={_m.loc[_r, 'T1_years']:.2f}y  spot={_v[0]:.4f}  "
              f"best={np.nanmax(_v):.4f} at {_fs_vals[np.nanargmax(_v)]:.0f}Y  "
              f"lift={np.nanmax(_v) - _v[0]:+.4f}")

# %%
_pooled = EFF_ALL[_fs_cols].groupby(level=1).mean()
_pooled.index = [f"rank {r} (T1 {EFF[CFG.citi_fly].loc[r, 'T1_years']:.2f}y)"
                 for r in _pooled.index]
_panels = [(CFG.citi_fly, EFF[CFG.citi_fly][_fs_cols]),
           (_best_shape, EFF[_best_shape][_fs_cols]),
           ("mean over all 9 shapes", _pooled)]
fig = make_subplots(rows=1, cols=3, subplot_titles=[f"{n}: R²" for n, _ in _panels],
                    horizontal_spacing=0.07)
for i, (nm, mat) in enumerate(_panels, start=1):
    y = [f"{r}" for r in mat.index] if i == 3 else [
        f"r{r} · T1 {EFF[CFG.citi_fly].loc[r, 'T1_years']:.2f}y" for r in mat.index]
    fig.add_trace(go.Heatmap(z=mat.to_numpy(float), x=[c[3:] for c in _fs_cols], y=y,
                             coloraxis="coloraxis",
                             hovertemplate="fwd start %{x}<br>%{y}<br>R²=%{z:.4f}<extra></extra>"),
                  row=1, col=i)
fig.update_layout(template="plotly_dark", height=460, coloraxis=dict(colorscale="Viridis"),
                  title=("hedge effectiveness: pack expiry (rows, deepest at the bottom) "
                         "× fly forward start (cols).<br>"
                         "The hypothesis predicts a bright DIAGONAL. "
                         f"Measured slope {HYP['slope']:+.3f} vs predicted +1.0."))
fig.update_xaxes(title_text="fly forward start")
fig.show()

# %%
fig = go.Figure()
for _shape, _m2 in EFF.items():
    fig.add_trace(go.Scatter(x=_m2["T1_years"], y=_m2["fs_0Y"], mode="lines+markers",
                             name=f"{_shape} spot", opacity=0.55))
fig.add_trace(go.Scatter(x=EFF[CFG.citi_fly]["T1_years"], y=EFF[CFG.citi_fly]["fs_0Y"],
                         mode="lines+markers", name=f"{CFG.citi_fly} SPOT (Citi)",
                         line=dict(color="#ff5c5c", width=4)))
fig.add_trace(go.Scatter(x=EFF[CFG.citi_fly]["T1_years"], y=EFF[CFG.citi_fly]["fs_3Y"],
                         mode="lines+markers", name=f"{CFG.citi_fly} @3Y forward",
                         line=dict(color="#4dabf7", width=4, dash="dash")))
fig.update_layout(template="plotly_dark", height=520,
                  xaxis_title="pack first-expiry T1 (years)",
                  yaxis_title="R² of constant-contract dCA on d(fly), 50/50 wings",
                  title="If vol at the pack's own expiry drove CA, the dashed forward "
                        "line would overtake the solid spot line as T1 grows")
fig.show()

# %% [markdown]
# ### 5.1 What the correlation actually is — the exact decomposition
#
# `CA = pack_rate - matched_swap_rate`, so `dCA = d(pack_rate) - d(swap_rate)`
# **identically**. Any regression of `dCA` on a fly therefore decomposes with no
# residual into the two legs' own betas. That matters because Citi's rationale is
# a claim about the FUTURES side (*"3y1y vol is mostly driven by expectations of
# monetary policy"* — vol enters through the futures' convexity), so a hedge that
# works entirely through the SWAP leg is hedging curve shape at the pack's
# maturity, not volatility.
#
# The units are made explicit: rates are in percent in the panel, so every slope
# below is bp of leg per bp of fly.

# %%
_pack_wide = PANEL_RAW.pivot_table(index="date", columns="pack", values="pack_rate",
                                   aggfunc="last").reindex(INP.dates)
_dec_rows = []
for _shape in ("1s2s3s", CFG.citi_fly):
    for _fs in (0.0, 1.0):
        _fid = _shape if _fs <= 0 else f"{_shape}@{int(_fs)}Y"
        _sp3 = SPECS[_fid]
        _dfly = fly_rate_series(INP.legs, _sp3, *DV01_NEUTRAL_WINGS).diff()
        for _rk in CFG.ranks:
            _lab = INP_RAW.rank_labels(_rk)
            _dca = constant_contract_dca(INP.ca, _lab)                       # bp
            _dpk = constant_contract_dca(_pack_wide, _lab) * 100.0           # % -> bp
            _dsw = constant_contract_dca(INP.swap_rate, _lab) * 100.0        # % -> bp
            _row = {"fly": _fid, "rank": _rk, "T1_years": round(_t1map[_rk], 2)}
            for _nm, _y in (("dCA", _dca), ("d_pack_rate", _dpk), ("d_swap_rate", _dsw)):
                _j2 = pd.concat([_y.rename("y"), _dfly.rename("x")], axis=1).dropna()
                if len(_j2) < 30:
                    _row[f"slope_{_nm}"] = _row[f"r2_{_nm}"] = np.nan
                    continue
                _X = np.column_stack([np.ones(len(_j2)), _j2["x"].to_numpy(float)])
                _c2 = np.linalg.lstsq(_X, _j2["y"].to_numpy(float), rcond=None)[0]
                _res2 = _j2["y"].to_numpy(float) - _X @ _c2
                _sst = float(((_j2["y"] - _j2["y"].mean()) ** 2).sum())
                _row[f"slope_{_nm}"] = float(_c2[1])
                _row[f"r2_{_nm}"] = 1.0 - float((_res2 ** 2).sum()) / _sst if _sst > 0 else np.nan
            _row["identity_check"] = (_row["slope_dCA"] - _row["slope_d_pack_rate"]
                                      + _row["slope_d_swap_rate"])
            _dec_rows.append(_row)
DECOMP = pd.DataFrame(_dec_rows)
display(DECOMP[DECOMP["fly"].isin(["1s2s3s", CFG.citi_fly])].round(4).to_string(index=False))
_idmax = float(DECOMP["identity_check"].abs().max())
print(f"\nmax |slope_dCA - (slope_pack - slope_swap)| = {_idmax:.3g}  "
      "-- the decomposition is an identity, not a fit")
assert _idmax < 1e-8, "dCA != d(pack) - d(swap): the panel's own columns disagree"
_best = DECOMP[(DECOMP["fly"] == "1s2s3s")].sort_values("r2_dCA", ascending=False).iloc[0]
print(f"\nStrongest cell: 1s2s3s spot vs rank {int(_best['rank'])} (T1 {_best['T1_years']}y), "
      f"R2(dCA) = {_best['r2_dCA']:.3f}")
print(f"  d(pack_rate) ~ d(fly):  slope {_best['slope_d_pack_rate']:+.3f}  R2 {_best['r2_d_pack_rate']:.3f}")
print(f"  d(swap_rate) ~ d(fly):  slope {_best['slope_d_swap_rate']:+.3f}  R2 {_best['r2_d_swap_rate']:.3f}")
print(f"  dCA          ~ d(fly):  slope {_best['slope_dCA']:+.3f} "
      f"= {_best['slope_d_pack_rate']:+.3f} - ({_best['slope_d_swap_rate']:+.3f})")
print("\nRead the two component R^2s. If the swap leg's beta is the larger one, the "
      "'hedge' is a bet on curve shape at the pack's own maturity -- which is a real, "
      "tradeable relationship, but it is NOT the volatility exposure Citi's note is "
      "about, and it does not become one by being profitable.")

# %% [markdown]
# ### 5.2 The realised variance reduction surface
#
# `R^2` above is an in-sample ceiling. This is what a desk actually got: rolling
# weights fitted on trailing history only, Citi's `belly = CA_DV01 * beta/100`
# sizing, frozen at entry, over the traded epochs. Negative means **the hedge
# made the P&L noisier than leaving the CA leg naked.**

# %%
_t0 = time.time()
BASE = Strat2GridConfig(
    pack_rank=8, fly_id=CFG.citi_fly, fly_weighting="regression",
    hedge_sizing="regression_beta", regression_window=252,
    regression_basis="changes", regression_target="rank", entry_rule="always",
    z_entry=CFG.z_entry, rebalance_days=CFG.rebalance_days,
    holding_days=CFG.holding_days, ca_dv01=CFG.ca_dv01,
    cost_bp_roundtrip=CFG.cost_bp_roundtrip, include_gamma=CFG.include_gamma)
ALL_FLY_IDS = [s.fly_id for s in fly_universe()]

G_FLY, _ = run_grid(INP, BASE, axes={"fly_id": ALL_FLY_IDS,
                                     "pack_rank": list(CFG.ranks),
                                     "regression_basis": list(CFG.regression_bases)},
                    progress=True)
G_FLY["block"] = "fly_x_rank"
print(f"fly x rank x basis: {len(G_FLY)} cells in {time.time() - _t0:.0f}s")

G_FLY["T1_years"] = G_FLY["pack_rank"].map(_t1map)

_vr = (G_FLY[(G_FLY["regression_basis"] == "changes") & (G_FLY["shape"] == CFG.citi_fly)]
       .pivot_table(index="pack_rank", columns="forward_start_y",
                    values="variance_reduction"))
_vr2 = (G_FLY[(G_FLY["regression_basis"] == "changes") & (G_FLY["shape"] == _best_shape)]
        .pivot_table(index="pack_rank", columns="forward_start_y",
                     values="variance_reduction"))
print(f"\nREALISED variance reduction, {CFG.citi_fly} (Citi's fly), changes basis:")
display(_vr.round(3))
print(f"REALISED variance reduction, {_best_shape}:")
display(_vr2.round(3))

_chg = G_FLY[G_FLY["regression_basis"] == "changes"]
_lvl = G_FLY[G_FLY["regression_basis"] == "levels"]
print(f"\nfraction of (fly x rank) cells with POSITIVE realised variance reduction:")
print(f"    changes basis: {float((_chg['variance_reduction'] > 0).mean()):.3f} "
      f"(median {float(_chg['variance_reduction'].median()):+.3f})")
print(f"    levels  basis: {float((_lvl['variance_reduction'] > 0).mean()):.3f} "
      f"(median {float(_lvl['variance_reduction'].median()):+.3f})")

fig = make_subplots(rows=1, cols=2, horizontal_spacing=0.12,
                    subplot_titles=(f"{CFG.citi_fly}: realised VR", f"{_best_shape}: realised VR"))
for i, mat in enumerate((_vr, _vr2), start=1):
    fig.add_trace(go.Heatmap(z=mat.to_numpy(float),
                             x=[f"{c:g}Y" for c in mat.columns],
                             y=[f"r{r} · T1 {_t1map[r]:.2f}y" for r in mat.index],
                             zmid=0.0, coloraxis="coloraxis",
                             hovertemplate="fwd %{x}<br>%{y}<br>VR=%{z:.3f}<extra></extra>"),
                  row=1, col=i)
fig.update_layout(template="plotly_dark", height=460,
                  coloraxis=dict(colorscale="RdBu", cmid=0.0),
                  title="realised variance reduction of the traded ledger "
                        "(blue = hedge helped, red = hedge made it worse)")
fig.show()

# %% [markdown]
# ## 6. The grid
#
# Everything on one ledger. `run_grid` emits a row even for a cell that produced
# no epochs (`n_epochs=0`), because a silently dropped cell is
# indistinguishable from a cell that lost money.

# %%
_t0 = time.time()
_top_flies = (_chg.groupby("fly_id")["variance_reduction"].median()
              .sort_values(ascending=False).head(2).index.tolist())
_focus_flies = sorted(set(_top_flies + [CFG.citi_fly]))
_focus_ranks = [3, 5, 8]
print("focus flies for the knob sweep:", _focus_flies, " ranks:", _focus_ranks)

G_KNOB, _ = run_grid(INP, BASE, axes={
    "fly_id": _focus_flies, "pack_rank": _focus_ranks,
    "fly_weighting": ["regression", "dv01_neutral"],
    "hedge_sizing": ["regression_beta", "dv01_ratio"],
    "regression_window": list(CFG.regression_windows),
    "regression_basis": list(CFG.regression_bases),
    "entry_rule": list(CFG.entry_rules),
}, progress=True)
G_KNOB["block"] = "knobs"
print(f"knobs: {len(G_KNOB)} cells, {time.time() - _t0:.0f}s")

# %%
_t0 = time.time()
G_HOLD, _ = run_grid(INP, BASE, axes={
    "fly_id": _focus_flies, "pack_rank": list(CFG.ranks),
    "holding_days": list(CFG.holding_days_axis), "direction": ["short_ca", "long_ca"],
}, progress=True)
G_HOLD["block"] = "hold_direction"

G_TGT, _ = run_grid(INP, BASE, axes={
    "fly_id": _focus_flies, "pack_rank": _focus_ranks,
    "regression_target": list(CFG.regression_targets),
    "regression_basis": list(CFG.regression_bases),
}, progress=False)
G_TGT["block"] = "regression_target"

G_UNH, _ = run_grid(INP, BASE, axes={
    "hedge_sizing": ["unhedged"], "pack_rank": list(CFG.ranks),
    "direction": ["short_ca", "long_ca"]}, progress=False)
G_UNH["block"] = "unhedged_baseline"

GRID = pd.concat([G_FLY, G_KNOB, G_HOLD, G_TGT, G_UNH], ignore_index=True)
GRID["T1_years"] = GRID["pack_rank"].map(_t1map)
print(f"hold/target/unhedged: {time.time() - _t0:.0f}s")
print(f"TOTAL GRID: {len(GRID):,} cells, {int(GRID['n_epochs'].fillna(0).eq(0).sum())} of them empty")
GRID.to_csv(DATA / "strat2_gridsearch_cells.csv", index=False)
print(f"wrote {DATA / 'strat2_gridsearch_cells.csv'}")

# %% [markdown]
# ### 6.1 The unhedged baseline — the denominator for every variance reduction
#
# This is also where the fourth sign probe lands: at zero cost, `long_ca` must be
# the **exact** negative of `short_ca`, every day, including the gamma term. If
# it is not, the direction switch is a different strategy rather than a mirror,
# and every `long_ca` row in the grid is uninterpretable.

# %%
_probe_cfg = dataclasses.replace(BASE, pack_rank=5, hedge_sizing="unhedged",
                                 cost_bp_roundtrip=0.0)
_ps = simulate_cell(INP, dataclasses.replace(_probe_cfg, direction="short_ca"))
_pl = simulate_cell(INP, dataclasses.replace(_probe_cfg, direction="long_ca"))
_mir = float((_ps.daily["pnl"] + _pl.daily["pnl"]).abs().max())
_mir_g = float((_ps.daily["gamma_pnl"] + _pl.daily["gamma_pnl"]).abs().max())
print(f"long_ca vs short_ca at zero cost, rank 5 unhedged: "
      f"max |daily P&L sum| = {_mir:.6g}, max |daily gamma sum| = {_mir_g:.6g}")
assert _mir < 1e-6 and _mir_g < 1e-6, (
    "long_ca is not the exact mirror of short_ca -- the direction switch is a "
    "different strategy, and every long_ca row in the grid is uninterpretable")
assert len(_ps.epochs) == len(_pl.epochs) > 0, "the mirror probe traded nothing"
print(f"exact mirror over {len(_ps.daily)} days and {len(_ps.epochs)} epochs "
      f"-- `long_ca` is a negative control, not a second strategy")

# %%
_bcols = ["pack_rank", "T1_years", "direction", "n_epochs", "total_pnl", "sharpe",
          "sharpe_active", "max_drawdown", "hit_rate", "gamma_pnl", "gamma_share"]
_unh_block = GRID[GRID["block"] == "unhedged_baseline"]
display(_unh_block[_bcols].sort_values(["direction", "pack_rank"]).round(3).to_string(index=False))
print("At the grid's 0.25bp cost the two directions do NOT sum to zero: they sum to "
      "-2 x (n_epochs x 0.25bp x CA_DV01), the round trip charged to both sides. "
      "Rank 2, 9 epochs: -881,997.69 + 431,997.69 = -450,000 = 2 x 9 x 0.25 x 100,000.")
print("\nThe CA leg alone. `gamma_share` is the size of the second-order term the "
      "panel's first-order ledger omits from the headline -- a cell whose share is "
      "large is a cell whose headline should not be believed.")

# %% [markdown]
# ### 6.2 Top cells — Sharpe is never quoted alone
#
# Every row carries, next to the Sharpe: the hedge's realised effectiveness
# (`variance_reduction`, `hedge_r2`), the **position's** ex-ante 3m carry in
# dollars, and the P&L at 0x / 0.5x / 1x / 2x cost with the break-even cost in
# bp. A cell that only works at zero cost, or whose hedge raises variance, is
# labelled as such in `verdict` rather than crowned.
#
# **The carry column is signed for the POSITION.** `fly_carry_3m_bp` from the
# cell metrics is the quote for a *paid* belly at that fly's weights. Most
# winning cells here have a NEGATIVE fitted beta and therefore a *received*
# belly, so quoting the raw number would report the carry of a trade nobody put
# on. `fly_carry_3m_usd = direction_sign * belly_DV01 * quote`.

# %%
def enrich(row_cfg: Strat2GridConfig, inp=INP) -> dict:
    """Re-simulate one cell and derive the columns the metrics dict cannot carry."""
    res = simulate_cell(inp, row_cfg)
    m = dict(res.metrics)
    s = row_cfg.sign
    belly = m.get("mean_belly_dv01", np.nan)
    # ex-ante 3m carry OF THE POSITION, in dollars
    m["fly_carry_3m_usd"] = (s * belly * m["fly_carry_3m_bp"]
                             if np.isfinite(belly) and np.isfinite(m["fly_carry_3m_bp"])
                             else np.nan)
    rolls = []
    for ep in res.epochs:
        v = (inp.roll_3m.at[ep.entry, ep.pack]
             if ep.pack in inp.roll_3m.columns else np.nan)
        if np.isfinite(v):
            rolls.append(float(v))
    m["ca_roll_3m_bp"] = float(np.mean(rolls)) if rolls else np.nan
    m["ca_carry_3m_usd"] = (s * row_cfg.ca_dv01 * m["ca_roll_3m_bp"]
                            if np.isfinite(m["ca_roll_3m_bp"]) else np.nan)
    m["carry_3m_usd"] = np.nansum([m["ca_carry_3m_usd"], m["fly_carry_3m_usd"]])
    # cost sensitivity
    unit = sum(row_cfg.cost_bp_roundtrip * (e.ca_dv01 + abs(e.belly_dv01))
               for e in res.epochs)
    gross = m["pnl_cost_0x"]
    notional_bp = sum(e.ca_dv01 + abs(e.belly_dv01) for e in res.epochs)
    m["breakeven_cost_bp"] = gross / notional_bp if notional_bp > 0 else np.nan
    m["cost_at_1x"] = unit
    # in-position CA marks that are actually finite (the filter's blast radius)
    tot = fin = 0
    for ep in res.epochs:
        w = inp.dates[(inp.dates > ep.entry) & (inp.dates <= ep.exit)]
        d = inp.ca[ep.pack].reindex(
            inp.dates[(inp.dates >= ep.entry) & (inp.dates <= ep.exit)]).diff().reindex(w)
        tot += len(d)
        fin += int(np.isfinite(d).sum())
    m["frac_days_finite_dca"] = fin / tot if tot else np.nan
    # flagged pack-days inside the hold
    flagged = held = 0
    for ep in res.epochs:
        sub = _post[(_post["pack"] == ep.pack) & (_post["date"] >= ep.entry)
                    & (_post["date"] <= ep.exit)]
        held += len(sub)
        flagged += int((~sub["survive"].astype(bool)).sum())
    m["frac_held_days_flagged"] = flagged / held if held else np.nan
    verdict = []
    if not (m["variance_reduction"] > 0):
        verdict.append("hedge RAISES variance")
    if not (m["carry_3m_usd"] > 0):
        verdict.append("negative carry")
    if not (m["pnl_cost_2x"] > 0):
        verdict.append("dies at 2x cost")
    if m["n_epochs"] < 8:
        verdict.append(f"only {m['n_epochs']} epochs")
    m["verdict"] = "; ".join(verdict) if verdict else "clears every screen"
    return m


def cfg_from_row(row: pd.Series) -> Strat2GridConfig:
    fields = {f.name for f in dataclasses.fields(Strat2GridConfig)}
    kw = {k: v for k, v in row.items() if k in fields and pd.notna(v)}
    for k in ("pack_rank", "regression_window", "rebalance_days", "holding_days"):
        if k in kw:
            kw[k] = int(kw[k])
    return dataclasses.replace(BASE, **kw)


SCORED = GRID[(GRID["n_epochs"].fillna(0) >= 5)
              & GRID["sharpe"].notna()
              & (GRID["hedge_sizing"] != "unhedged")].copy()
SCORED = SCORED.sort_values("sharpe", ascending=False).reset_index(drop=True)
print(f"scored cells (>=5 epochs, hedged): {len(SCORED):,}")

_rows = []
for _, r in SCORED.head(CFG.top_n).iterrows():
    _rows.append({**{k: r[k] for k in ("fly_id", "pack_rank", "T1_years",
                                       "fly_weighting", "hedge_sizing",
                                       "regression_window", "regression_basis",
                                       "regression_target", "entry_rule",
                                       "holding_days", "direction", "block")},
                  **enrich(cfg_from_row(r))})
TOP = pd.DataFrame(_rows)
_show = ["fly_id", "pack_rank", "T1_years", "regression_basis", "fly_weighting",
         "hedge_sizing", "regression_window", "entry_rule", "holding_days",
         "direction", "n_epochs", "sharpe", "sharpe_active", "total_pnl",
         "max_drawdown", "hit_rate", "hedge_r2", "variance_reduction",
         "corr_dca_dfly", "mean_beta", "mean_belly_dv01", "ca_roll_3m_bp",
         "fly_carry_3m_bp", "carry_3m_usd", "pnl_cost_0x", "pnl_cost_1x",
         "pnl_cost_2x", "breakeven_cost_bp", "gamma_share",
         "frac_days_finite_dca", "frac_held_days_flagged", "verdict"]
display(TOP[_show].round(3))

# %% [markdown]
# ### 6.3 Citi's own cell, and what the knobs do to it

# %%
_citi = GRID[(GRID["fly_id"] == CFG.citi_fly) & (GRID["block"] == "knobs")
             & (GRID["fly_weighting"] == "regression")
             & (GRID["hedge_sizing"] == "regression_beta")
             & (GRID["entry_rule"] == "always")]
_ccols = ["pack_rank", "T1_years", "regression_basis", "regression_window",
          "n_epochs", "total_pnl", "sharpe", "hedge_r2", "variance_reduction",
          "corr_dca_dfly", "mean_beta", "mean_w_front", "mean_w_back",
          "fly_carry_3m_bp", "pnl_cost_1x"]
print("Citi's specification (2s5s10s, regression weights, beta/100 sizing, always on) "
      "across ranks, both bases and all three windows:")
display(_citi[_ccols].sort_values(["pack_rank", "regression_basis", "regression_window"])
        .round(3).to_string(index=False))
print("\nCiti's published anchors: alpha 10.2, beta 21.4, wings 0.73/1/0.47 (13-Jan-2017); "
      "alpha 9.7, beta 20.6, wings 0.705/1/0.465 (09-Feb-2017).")

_axis = []
for _ax in ("regression_basis", "fly_weighting", "hedge_sizing", "entry_rule",
            "regression_window", "regression_target"):
    _sub = GRID[GRID[_ax].notna() & (GRID["hedge_sizing"] != "unhedged")
                & (GRID["n_epochs"].fillna(0) >= 5)]
    for _v, _g in _sub.groupby(_ax):
        _axis.append({"axis": _ax, "value": _v, "cells": len(_g),
                      "median sharpe": float(_g["sharpe"].median()),
                      "median VR": float(_g["variance_reduction"].median()),
                      "median R2": float(_g["hedge_r2"].median()),
                      "frac sharpe>0": float((_g["sharpe"] > 0).mean()),
                      "median pnl @1x": float(_g["pnl_cost_1x"].median())})
print("\nWHAT EACH AXIS IS WORTH (median over every cell that varies it):")
display(pd.DataFrame(_axis).round(3).to_string(index=False))

# %% [markdown]
# ## 7. Stability — the neighbourhood, not the cell
#
# A cell whose Sharpe collapses when the fly shape, the forward start, the
# regression window or the pack rank moves one notch is a fitted artefact. The
# neighbourhood is re-simulated around the winner on each axis separately.

# %%
WIN = SCORED.iloc[0]
WIN_CFG = cfg_from_row(WIN)
print("winning cell:", WIN_CFG.key())

_nb = []
_win_spec = SPECS[WIN_CFG.fly_id]
_neighbourhoods = {
    "fly shape (same forward start)": ("fly_id", [
        (f"{sh}" if _win_spec.forward_start_y <= 0 else
         f"{sh}@{int(_win_spec.forward_start_y)}Y") for sh in CFG.shapes]),
    "forward start (same shape)": ("fly_id", [
        (_win_spec.shape if f <= 0 else f"{_win_spec.shape}@{int(f)}Y")
        for f in CFG.forward_starts]),
    "pack rank": ("pack_rank", list(CFG.ranks)),
    "regression window": ("regression_window", list(CFG.regression_windows)),
    "holding days": ("holding_days", list(CFG.holding_days_axis)),
    "regression basis": ("regression_basis", list(CFG.regression_bases)),
    "fly weighting": ("fly_weighting", ["regression", "dv01_neutral"]),
    "hedge sizing": ("hedge_sizing", ["regression_beta", "dv01_ratio", "unhedged"]),
    "entry rule": ("entry_rule", list(CFG.entry_rules)),
}
for _name, (_field, _vals) in _neighbourhoods.items():
    for _v in _vals:
        try:
            _c = dataclasses.replace(WIN_CFG, **{_field: _v})
            _r = simulate_cell(INP, _c)
        except Exception as _e:                                   # noqa: BLE001
            _nb.append({"axis": _name, "value": _v, "error": type(_e).__name__})
            continue
        _nb.append({"axis": _name, "value": str(_v), "n_epochs": _r.metrics["n_epochs"],
                    "sharpe": _r.metrics["sharpe"],
                    "total_pnl": _r.metrics["total_pnl"],
                    "VR": _r.metrics["variance_reduction"],
                    "hedge_r2": _r.metrics["hedge_r2"],
                    "pnl_cost_2x": _r.metrics["pnl_cost_2x"],
                    "is_winner": (_v == getattr(WIN_CFG, _field))})
NB = pd.DataFrame(_nb)
display(NB.round(3).to_string(index=False))

_stab = NB.dropna(subset=["sharpe"]).groupby("axis").agg(
    n=("sharpe", "size"), median_sharpe=("sharpe", "median"),
    min_sharpe=("sharpe", "min"), max_sharpe=("sharpe", "max"),
    frac_positive=("sharpe", lambda s: float((s > 0).mean())))
print("\nSharpe across each neighbourhood (the winner is one point in each row):")
display(_stab.round(3))

fig = go.Figure()
for _ax_name, _g in NB.dropna(subset=["sharpe"]).groupby("axis"):
    fig.add_trace(go.Box(y=_g["sharpe"], name=_ax_name, boxpoints="all",
                         jitter=0.4, pointpos=0, marker=dict(size=7)))
fig.add_hline(y=float(WIN["sharpe"]), line=dict(color="#ff5c5c", dash="dash"),
              annotation_text="winning cell")
fig.add_hline(y=0.0, line=dict(color="#888", width=1))
fig.update_layout(template="plotly_dark", height=520, showlegend=False,
                  yaxis_title="annualised Sharpe",
                  title="stability: one axis moved at a time from the winning cell")
fig.show()

# %% [markdown]
# ## 8. What the search cost — the deflated Sharpe
#
# The best Sharpe out of several thousand tries is not the Sharpe to expect out
# of sample. The deflated Sharpe ratio (Bailey & López de Prado) discounts the
# maximum by the expected maximum of that many draws under a null of zero skill,
# using the winning cell's OWN daily return moments for the non-normality
# correction — not the cross-section's.

# %%
from scipy import stats as _st

_win_res = simulate_cell(INP, WIN_CFG)
_r = _win_res.daily["pnl_net"]
_r = _r.loc[_win_res.epochs[0].entry:_win_res.epochs[-1].exit]
_T = int(len(_r))
_s_cs = SCORED["sharpe"].dropna()
_n_trials = int(len(SCORED))
_sr = float(_r.mean() / _r.std(ddof=1))              # per-day, the DSR's unit
_g3, _g4 = float(_r.skew()), float(_r.kurt() + 3.0)
_sr_std_cs = float(_s_cs.std(ddof=1) / np.sqrt(252.0))
_e_max = _sr_std_cs * ((1 - np.euler_gamma) * _st.norm.ppf(1 - 1.0 / _n_trials)
                       + np.euler_gamma * _st.norm.ppf(1 - 1.0 / (_n_trials * np.e)))
_z = ((_sr - _e_max) * np.sqrt(_T - 1)
      / np.sqrt(1 - _g3 * _sr + (_g4 - 1) / 4.0 * _sr ** 2))
DSR = pd.Series({
    "cells searched (scored, >=5 epochs)": _n_trials,
    "total grid cells run": int(len(GRID)),
    "winning cell": " ".join(f"{k}={v}" for k, v in WIN_CFG.key().items()
                             if k in ("fly_id", "pack_rank", "regression_basis",
                                      "fly_weighting", "hedge_sizing",
                                      "regression_window", "entry_rule",
                                      "holding_days", "direction")),
    "sample days (entry..last exit)": _T,
    "winner annualised Sharpe": _sr * np.sqrt(252.0),
    "winner daily skew": _g3,
    "winner daily kurtosis": _g4,
    "cross-sectional Sharpe sd (annualised)": float(_s_cs.std(ddof=1)),
    "expected max Sharpe under the null (annualised)": _e_max * np.sqrt(252.0),
    "deflated Sharpe p(true SR > 0)": float(_st.norm.cdf(_z)),
    "median cell Sharpe": float(_s_cs.median()),
    "% of cells with Sharpe > 0": float(100 * (_s_cs > 0).mean()),
    "% of cells with positive variance reduction": float(
        100 * (SCORED["variance_reduction"] > 0).mean()),
})
display(DSR.to_frame("value"))

_p = float(DSR["deflated Sharpe p(true SR > 0)"])
print(f"\nREAD: the deflated Sharpe is a HYPOTHESIS TEST, and {_p:.3f} is the p-value "
      f"for a true Sharpe above zero AFTER discounting the search. At the conventional "
      f"0.95 bar the winning cell "
      f"{'CLEARS' if _p >= 0.95 else 'DOES NOT CLEAR'} it. A number close to 1 that is "
      "not above 0.95 is a failure, not a near-miss to be rounded up: with "
      f"{_n_trials:,} cells searched, the best Sharpe out of the draw is expected to be "
      f"{float(DSR['expected max Sharpe under the null (annualised)']):.3f} on skill of "
      "exactly zero.")

_survivors = SCORED[(SCORED["sharpe"] > DSR["expected max Sharpe under the null (annualised)"])
                    & (SCORED["variance_reduction"] > 0)
                    & (SCORED["pnl_cost_2x"] > 0)]
print(f"\ncells that beat the expected-max-under-the-null Sharpe AND reduce variance "
      f"AND survive 2x cost: {len(_survivors)} of {_n_trials} ({100 * len(_survivors) / _n_trials:.1f}%)")
display(_survivors.head(12)[["fly_id", "pack_rank", "regression_basis", "fly_weighting",
                             "hedge_sizing", "regression_window", "entry_rule",
                             "holding_days", "direction", "n_epochs", "sharpe",
                             "variance_reduction", "pnl_cost_2x"]].round(3))

fig = go.Figure()
fig.add_trace(go.Histogram(x=_s_cs, nbinsx=70, name="all scored cells",
                           marker=dict(color="#4dabf7")))
for _v, _c, _lbl in ((0.0, "#888", "zero"),
                     (float(DSR["expected max Sharpe under the null (annualised)"]),
                      "#f6c744", "E[max Sharpe | no skill]"),
                     (float(WIN["sharpe"]), "#ff5c5c", "winner")):
    fig.add_vline(x=_v, line=dict(color=_c, dash="dash"), annotation_text=_lbl)
fig.update_layout(template="plotly_dark", height=430, xaxis_title="annualised Sharpe",
                  yaxis_title="cells",
                  title=f"the whole search: {_n_trials:,} scored cells")
fig.show()

# %% [markdown]
# ## 9. Engine certification — the panel simulation against a real backtest
#
# The grid is a **panel simulation**: fixed DV01s struck at entry, P&L linear in
# `dCA` and `d(fly_bp)` plus an explicit second-order term. That is the only way
# a few thousand cells are affordable at all. It is not the same thing as
# repricing an aged package on a fresh curve every day.
#
# So the top cells are re-run through `strat2_sofr_convexity.run_backtest` — a
# real `QueryDrivenBacktest` with daily mark-to-market over
# 4 SR3 futures legs + the matched swap + the fly — with the epochs, weights and
# DV01s taken **verbatim from the grid's own `Epoch` objects**, so the only
# difference between the two ledgers is the pricing, not the trade.
#
# Constraints, all of them data:
# * an epoch may not end after `futures_cutoff` (SR3 settles collapse);
# * certification runs at ZERO cost on both sides (the engine charges its fee at
#   unwind, the panel charges it at entry — comparing them would compare fee
#   conventions, not prices);
# * `QueryDrivenBacktest.run()` swallows exceptions, so `assert_ran` is called
#   after every run.
#
# **Every cell is certified twice: once with the fly and once without.** A single
# aggregate gap tells you the panel and the engine disagree; it does not tell you
# *where*, and the two legs are not equally trustworthy. The CA leg is four
# futures at a genuinely rate-invariant \$25/bp plus a swap struck DV01-matched
# to them; the fly leg is three par swaps that AGE, and the panel prices them off
# constant-maturity par rates that never age. Running the unhedged package
# separates the two.

# %%
def epoch_to_spec(ep, spec_fly, s2cfg) -> S2.TradeSpec:
    """One grid `Epoch` -> the `TradeSpec` the production engine consumes."""
    row = INP_RAW.panel[(INP_RAW.panel["date"] == ep.entry)
                        & (INP_RAW.panel["pack"] == ep.pack)].iloc[0]
    syms = tuple(S2.futures_symbol(y, m, s2cfg.futures_root)
                 for y, m in S2._contracts_for(ep.pack, ep.entry.date(), s2cfg))
    fit = S2.HedgeFit(alpha=float(ep.fit.alpha), b2=np.nan, b5=float(ep.fit.beta),
                      b10=np.nan, beta=float(ep.fit.beta),
                      w2=abs(float(ep.w_front)), w10=abs(float(ep.w_back)),
                      r2=float(ep.fit.r2), n_obs=int(ep.fit.n_obs), ok=True)
    return S2.TradeSpec(
        entry=ep.entry.date(), exit=ep.exit.date(), pack=ep.pack, rank=int(ep.rank),
        symbols=syms, swap_start=row["swap_start"], swap_end=row["swap_end"],
        contracts_per_leg=int(round(ep.ca_dv01 / (4.0 * DV01_PER_CONTRACT))),
        ca_dv01=float(ep.ca_dv01), n_flags=0, ca_entry_bp=float(ep.ca_entry_bp),
        hedge=fit,
        hedge_dv01={"belly_dv01": float(ep.belly_dv01),
                    "wing_2y_dv01": abs(float(ep.w_front)) * float(ep.belly_dv01),
                    "wing_10y_dv01": abs(float(ep.w_back)) * float(ep.belly_dv01)},
        tag=f"cert_{ep.pack}_{ep.entry:%Y%m%d}")


def certify(grid_cfg: Strat2GridConfig, label: str) -> dict:
    """Run one grid cell through the real engine and compare the two ledgers."""
    res = simulate_cell(INP, dataclasses.replace(grid_cfg, cost_bp_roundtrip=0.0))
    spec_fly = SPECS[grid_cfg.fly_id]
    eligible = [e for e in res.epochs
                if e.exit <= pd.Timestamp(CFG.futures_cutoff) and e.belly_dv01 != 0.0]
    out = {"cell": label, "fly_id": grid_cfg.fly_id, "pack_rank": grid_cfg.pack_rank,
           "epochs_in_cell": len(res.epochs), "epochs_certified": len(eligible)}
    if not eligible:
        out["status"] = "NOT EXPRESSIBLE: no epoch ends before the SR3 coverage cutoff"
        return out
    s2cfg = dataclasses.replace(S2.Strat2Config(), hedge_tenors=spec_fly.tenors,
                                ca_dv01=grid_cfg.ca_dv01, cost_bp_per_roundtrip=0.0,
                                hedge_require_positive_wings=False)
    try:
        specs = [epoch_to_spec(e, spec_fly, s2cfg) for e in eligible]
    except KeyError as exc:
        out["status"] = f"NOT EXPRESSIBLE: {exc}"
        return out
    lo = min(s.entry for s in specs)
    hi = max(s.exit for s in specs)
    days = [d for d in INP.dates if lo <= d.date() <= hi]
    t0 = time.time()
    bt = S2.run_backtest(specs, s2cfg, hedged=True, swaps_mdp=_SWAPS_MDP,
                         trading_days=days, name=f"cert_{label}")
    eq = S2.assert_ran(bt, specs, hedged=True)
    # panel side: gross, and ONLY the days one of the CERTIFIED epochs is on
    mask = pd.Series(False, index=res.daily.index)
    for e in eligible:
        mask |= (res.daily.index > e.entry) & (res.daily.index <= e.exit)
    pan = res.daily.loc[mask, "pnl"]
    eng_d = eq.diff().fillna(0.0)
    j = pd.concat([eng_d.rename("engine"), pan.rename("panel")], axis=1).dropna()
    if grid_cfg.sign < 0:
        # the engine builds the short-CA package; long_ca is its exact mirror
        j["engine"] = -j["engine"]
    out.update({
        "status": "certified",
        "seconds": round(time.time() - t0, 1),
        "marks": int(len(eq)),
        "engine_terminal_usd": float(j["engine"].sum()),
        "panel_terminal_usd": float(j["panel"].sum()),
        "terminal_gap_usd": float(j["engine"].sum() - j["panel"].sum()),
        "terminal_gap_pct": (100 * (j["engine"].sum() - j["panel"].sum())
                             / abs(j["panel"].sum()) if j["panel"].sum() else np.nan),
        "corr_daily_changes": float(j.corr().iloc[0, 1]),
        "slope_engine_on_panel": float(np.linalg.lstsq(
            np.column_stack([np.ones(len(j)), j["panel"]]),
            j["engine"].to_numpy(float), rcond=None)[0][1]),
        "intercept_usd_per_day": float(np.linalg.lstsq(
            np.column_stack([np.ones(len(j)), j["panel"]]),
            j["engine"].to_numpy(float), rcond=None)[0][0]),
        "resid_sd_usd": float((j["engine"] - j["panel"]).std(ddof=1)),
        "panel_sd_usd": float(j["panel"].std(ddof=1)),
    })
    # ---- attribution: the CA leg ALONE (4 futures + the matched swap) --------
    # If the gap lives here, the strategy itself is mis-modelled. If it lives in
    # the fly, only the hedge is.
    bt0 = S2.run_backtest(specs, s2cfg, hedged=False, swaps_mdp=_SWAPS_MDP,
                          trading_days=days, name=f"cert_ca_{label}")
    eq0 = S2.assert_ran(bt0, specs, hedged=False)
    j0 = pd.concat([eq0.diff().fillna(0.0).rename("engine"),
                    res.daily.loc[mask, "ca_pnl"].rename("panel")], axis=1).dropna()
    if grid_cfg.sign < 0:
        j0["engine"] = -j0["engine"]
    out.update({
        "ca_leg_engine_usd": float(j0["engine"].sum()),
        "ca_leg_panel_usd": float(j0["panel"].sum()),
        "ca_leg_gap_usd": float(j0["engine"].sum() - j0["panel"].sum()),
        "ca_leg_corr": float(j0.corr().iloc[0, 1]),
        "ca_leg_slope": float(np.linalg.lstsq(
            np.column_stack([np.ones(len(j0)), j0["panel"]]),
            j0["engine"].to_numpy(float), rcond=None)[0][1]),
    })
    out["_bt"] = bt
    out["_bt_ca"] = bt0
    out["_joint"] = j
    out["_joint_ca"] = j0
    out["_eq"] = eq
    return out


_cands = SCORED.drop_duplicates(subset=["fly_id", "pack_rank", "regression_basis",
                                        "fly_weighting", "hedge_sizing",
                                        "regression_window", "entry_rule",
                                        "holding_days", "direction"])
CERT_ROWS, CERT = [], {}
for _i in range(min(CFG.n_certify, len(_cands))):
    _r2 = _cands.iloc[_i]
    _lbl = (f"#{_i + 1} {_r2['fly_id']} r{int(_r2['pack_rank'])} "
            f"{_r2['regression_basis']} w{int(_r2['regression_window'])} "
            f"{_r2['entry_rule']} {_r2['direction']}")
    print(f"\ncertifying {_lbl} ...", flush=True)
    _c = certify(cfg_from_row(_r2), _lbl)
    CERT[_lbl] = _c
    CERT_ROWS.append({k: v for k, v in _c.items() if not k.startswith("_")})
CERT_DF = pd.DataFrame(CERT_ROWS)
display(CERT_DF.round(3))

# %%
_ok = [c for c in CERT.values() if c.get("status") == "certified"]
if _ok:
    fig = make_subplots(rows=1, cols=len(_ok), horizontal_spacing=0.08,
                        subplot_titles=[c["cell"] for c in _ok])
    for _i, _c in enumerate(_ok, start=1):
        for _key, _nm, _col in (("_joint", "full package", "#4dabf7"),
                                ("_joint_ca", "CA leg only", "#3ddc84")):
            _j = _c[_key]
            fig.add_trace(go.Scatter(x=_j.index, y=_j["engine"].cumsum(), mode="lines",
                                     name=f"{_nm} engine", legendgroup=_nm,
                                     showlegend=(_i == 1),
                                     line=dict(color=_col, width=2)), row=1, col=_i)
            fig.add_trace(go.Scatter(x=_j.index, y=_j["panel"].cumsum(), mode="lines",
                                     name=f"{_nm} panel", legendgroup=_nm,
                                     showlegend=(_i == 1),
                                     line=dict(color=_col, width=2, dash="dot")), row=1, col=_i)
        fig.update_yaxes(title_text="cumulative $" if _i == 1 else None, row=1, col=_i)
    fig.update_layout(template="plotly_dark", height=470,
                      title="QueryDrivenBacktest (solid) vs the panel simulation (dotted), "
                            "gross, over the certified epochs")
    fig.show()
    _cd = pd.DataFrame([{k: v for k, v in c.items() if not k.startswith("_")}
                        for c in _ok])
    print("\nFULL PACKAGE (4 futures + matched swap + fly):")
    print(_cd[["cell", "epochs_certified", "engine_terminal_usd", "panel_terminal_usd",
               "terminal_gap_usd", "terminal_gap_pct", "corr_daily_changes",
               "slope_engine_on_panel", "intercept_usd_per_day"]]
          .round(3).to_string(index=False))
    print("\nCA LEG ALONE (4 futures + matched swap, the strategy itself):")
    print(_cd[["cell", "ca_leg_engine_usd", "ca_leg_panel_usd", "ca_leg_gap_usd",
               "ca_leg_corr", "ca_leg_slope"]].round(3).to_string(index=False))
    _ca_c = _cd["ca_leg_corr"]
    _pk_c = _cd["corr_daily_changes"]
    _keep = (_cd["engine_terminal_usd"] / _cd["panel_terminal_usd"]).round(3)
    print(f"""
THE ATTRIBUTION, and it is not subtle.

  CA leg alone   corr of daily changes {_ca_c.min():.3f}..{_ca_c.max():.3f},
                 slope {_cd['ca_leg_slope'].min():.3f}..{_cd['ca_leg_slope'].max():.3f},
                 terminal gap ${_cd['ca_leg_gap_usd'].abs().min():,.0f}..${_cd['ca_leg_gap_usd'].abs().max():,.0f}
                 on ${_cd['ca_leg_panel_usd'].abs().min():,.0f}..${_cd['ca_leg_panel_usd'].abs().max():,.0f}.
  Full package   corr {_pk_c.min():.3f}..{_pk_c.max():.3f}, slope
                 {_cd['slope_engine_on_panel'].min():.3f}..{_cd['slope_engine_on_panel'].max():.3f},
                 and the engine keeps only {_keep.min():.0%}..{_keep.max():.0%} of the panel's headline.

**The panel's model of the STRATEGY is right to three decimal places. The whole
disagreement is the HEDGE.** That is exactly the leg where the approximation is
known to bite: the panel prices the fly as `belly_DV01 * d(fly_bp)` on
constant-maturity par rates, while the engine holds the struck swaps and
reprices them as they age. Measured on a single held 2Y payer (bpv $100k) that
drift is -1.44bp over 2022-09-12..12-12 and -2.97bp over 2021-03-01..06-01 --
and it does NOT equal the quoted carry+roll (-3.58bp and +3.33bp), so it is
aged-swap repricing, not carry.

Two consequences, both binding:
  1. No P&L number from the grid should be quoted for a HEDGED cell without this
     haircut. The three cells certified here kept their relative order under the
     engine -- but three is three. Sharpe and variance reduction for a hedged cell
     both depend on the fly leg, whose daily moves the engine prices 1.2-1.4x
     larger than the panel, so any ordering that turns on the HEDGE rather than
     on the CA leg is inference until it is certified too.
  2. Neither ledger contains carry. `carry_3m_usd` in section 6.2 is an EX-ANTE
     curve-implied quote, not a realised P&L component of either.""")
else:
    print("no cell was certifiable -- see `status` above")

# %% [markdown]
# ## 10. Equity curves and the trade dashboard

# %%
def _book(daily: pd.Series) -> pd.DataFrame:
    return pd.DataFrame({"timestamp": daily.index, "pnl": daily.to_numpy(float)})


_curves = {}
for _i in range(min(4, len(_cands))):
    _r2 = _cands.iloc[_i]
    _c = cfg_from_row(_r2)
    _res = simulate_cell(INP, _c)
    _curves[f"#{_i + 1} {_c.fly_id} r{_c.pack_rank} {_c.regression_basis}"] = \
        _book(_res.daily["pnl_net"])
_unh = simulate_cell(INP, dataclasses.replace(WIN_CFG, hedge_sizing="unhedged"))
_curves["unhedged CA leg (same rank/dir)"] = _book(_unh.daily["pnl_net"])
_citi_cell = simulate_cell(INP, dataclasses.replace(
    BASE, pack_rank=WIN_CFG.pack_rank, fly_id=CFG.citi_fly,
    regression_basis="levels", direction=WIN_CFG.direction))
_curves[f"Citi's cell ({CFG.citi_fly}, levels, r{WIN_CFG.pack_rank})"] = \
    _book(_citi_cell.daily["pnl_net"])
fig = compare_curves(_curves, title=f"top cells vs the unhedged leg vs Citi's own cell "
                                    f"(net of {CFG.cost_bp_roundtrip}bp round trip)")
fig.show()

# %%
_win_spec_fly = SPECS[WIN_CFG.fly_id]
_curves2 = {}
for _f in CFG.forward_starts:
    _fid = _win_spec_fly.shape if _f <= 0 else f"{_win_spec_fly.shape}@{int(_f)}Y"
    _curves2[f"{_fid}"] = _book(
        simulate_cell(INP, dataclasses.replace(WIN_CFG, fly_id=_fid)).daily["pnl_net"])
fig = compare_curves(_curves2, title=f"{_win_spec_fly.shape}: the forward-start axis at "
                                     f"rank {WIN_CFG.pack_rank} "
                                     f"(the hypothesis says the forward legs should win)")
fig.show()

# %%
_span = (INP.dates.max() - INP.dates.min()).days / 365.25
for _lbl, _c in CERT.items():
    if _c.get("status") != "certified":
        continue
    fig = trade_dashboard(_c["_bt"], title=f"ENGINE-CERTIFIED {_lbl}", span_years=_span)
    fig.show()

# %% [markdown]
# ## 11. Verdict

# %%
_verdict = {
    "sample": f"{INP.dates.min():%Y-%m-%d}..{INP.dates.max():%Y-%m-%d} "
              f"({len(INP.dates)} days, {_span:.2f}y), pack ranks {CFG.ranks[0]}..{CFG.ranks[-1]} "
              f"(T1 {min(_t1map.values()):.2f}..{max(_t1map.values()):.2f}y)",
    "cells run / scored": f"{len(GRID):,} / {len(SCORED):,}",
    "hypothesis slope (argmax-T1 on fly forward start)": round(float(HYP["slope"]), 4),
    "hypothesis corr": round(float(HYP["corr"]), 4),
    "mean peak R2 by forward start": {k: round(v, 4) for k, v in HYP["peak_r2_by_start"].items()},
    "winning cell": WIN_CFG.key(),
    "winner sharpe / VR / hedge R2": [round(float(WIN["sharpe"]), 3),
                                      round(float(WIN["variance_reduction"]), 3),
                                      round(float(WIN["hedge_r2"]), 3)],
    "E[max sharpe | no skill]": round(float(DSR["expected max Sharpe under the null (annualised)"]), 3),
    "deflated sharpe p(SR>0)": round(float(DSR["deflated Sharpe p(true SR > 0)"]), 4),
    "cells clearing null + VR>0 + 2x cost": int(len(_survivors)),
    "survivor cells": _survivors[["fly_id", "pack_rank", "regression_basis",
                                  "fly_weighting", "hedge_sizing",
                                  "regression_window", "entry_rule", "direction",
                                  "n_epochs", "sharpe", "variance_reduction",
                                  "hedge_r2", "pnl_cost_2x"]].round(3).to_dict("records"),
    "frac of fly x rank cells with VR>0 (changes basis)": round(
        float((_chg["variance_reduction"] > 0).mean()), 3),
    "frac of fly x rank cells with VR>0 (levels basis)": round(
        float((_lvl["variance_reduction"] > 0).mean()), 3),
    "engine certification": CERT_DF[[c for c in ("cell", "status", "epochs_certified",
                                                 "terminal_gap_pct", "corr_daily_changes",
                                                 "slope_engine_on_panel", "ca_leg_corr",
                                                 "ca_leg_slope", "ca_leg_gap_usd")
                                     if c in CERT_DF.columns]].round(3).to_dict("records"),
}
print(json.dumps(_verdict, indent=1, default=str))
with open(DATA / "strat2_gridsearch_verdict.json", "w", encoding="utf-8") as _f:
    json.dump(_verdict, _f, indent=1, default=str)
print(f"\nwrote {DATA / 'strat2_gridsearch_verdict.json'}")

# %% [markdown]
# ### Reading this notebook
#
# **What won, and what it depends on.** The ranking table in 6.2 is ordered on
# Sharpe but is never read on Sharpe: the `verdict` column is the read. A cell
# that tops the Sharpe column while raising the P&L variance above the unhedged
# leg has not hedged anything — it has taken a second position that happened to
# make money, and the honest description of it is a curve trade, not a hedge.
#
# **The forward-start hypothesis is the point of the whole grid, and it is
# settled by section 5, not by any P&L.** The prediction is a bright diagonal in
# the effectiveness surface and a slope near +1.0 in `hypothesis_slope`. Both are
# printed above with no discretion in between.
#
# **A shape that hedges well is not the same as a hedge that works for Citi's
# reason.** Read section 5's shape ranking against 5.1's realised variance
# reduction and section 6.2's `mean_beta` together. A fly whose fitted beta is
# large and NEGATIVE is not the trade Citi describes — Citi's beta is `+21.4`, a
# *paid* belly of about a fifth of the CA DV01. A large negative beta is a
# *received* belly several times the CA leg, i.e. a curve-shape position that
# happens to correlate with CA, and the correlation's mechanism deserves its own
# section before anyone sizes it.
#
# **What would break every number here.**
#
# 1. *The CA convention.* Every dollar in this notebook is `pack_rate - matched
#    swap` with the swap quarterly on both legs. Section 4.1 shows what the
#    annual variant does: up to 12bp of level error, worst in 2022-23, enough to
#    push half the strip into a false no-arbitrage violation on a single day.
#    The tie-out in section 3 is the only thing standing between this notebook
#    and that error, and it is vacuous on dates with no curve node inside the
#    pack window — which is exactly why everything before 2019-07-08 is thrown
#    away rather than flagged.
# 2. *Stale settles.* 30% of post-break pack-days print a NEGATIVE convexity
#    adjustment, which is impossible, and 99.6% of those have a control residual
#    under 1bp — so it is the Barchart settle on deferred contracts, not the
#    model. The entry gate keeps them out of the strike decision but a held
#    position still marks against them; `frac_held_days_flagged` in 6.2 is the
#    exposure and it is not small.
# 3. *Depth.* Citi traded Blues, `T1 ~ 3.25y`. The deepest pack here is
#    `T1 ~ 2.4y`. Every statement about "the hedge fails" is a statement about
#    the near half of the strip. A forward-starting fly might still earn its keep
#    against a pack whose expiry is genuinely 3-4 years out; this data cannot
#    say, and no cell above should be read as if it could.
# 4. *The hedge leg is the part the panel gets wrong.* Section 9 certifies each
#    top cell twice, with and without the fly. The CA leg — the strategy itself —
#    reproduces the real engine at a daily-change correlation of ~0.997-0.999 and
#    a slope of ~1.01, with a terminal gap of a few thousand dollars on over a
#    million. Add the fly and the correlation falls to ~0.85-0.93 and the engine
#    keeps roughly a third to a half of the panel's headline dollars. The three
#    certified cells kept their relative order under the engine; that is evidence
#    about three cells, not about the ranking. The dollar level of any HEDGED
#    cell is not trustworthy without the haircut. Cost, carry and financing on
#    the futures leg are outside both ledgers.
# 5. *Multiple testing.* Section 8 is not a footnote. With this many cells the
#    expected maximum Sharpe under a null of zero skill is printed next to the
#    winner's, and the count of cells that beat it while also reducing variance
#    and surviving 2x cost is the number that matters.
