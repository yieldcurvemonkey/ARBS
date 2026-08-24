# %% [markdown]
# # Citi, *Sell Blues convexity adjustments, hedged* — backtested in its own framework
#
# **Sources.** Two Citi notes by Ruslan Bikbov / Jason Williams, the first
# citing the second:
#
# * **`print (12).pdf`** — North America Rates Trade Idea, **09 February 2017**,
#   *"Sell Blues convexity adjustments, hedged"*. The ticket and Figures 1-6.
# * **`print (15/18).pdf`** — US Rates Weekly, **13 January 2017**, *"Swearing in
#   huge expectations"*, §*Smart convexity sells*. Figures 16-22, including the
#   pack-by-pack screen this backtest selects from.
#
# The note's own words:
#
# > We sell \$200k DV01 of Blues convexity adjustments, i.e. buy 2000 of H0-Z0
# > Eurodollar packs (2000 of each of the four contracts) and pay \$2bn on a
# > matched-maturity (3/18/20-3/17/21) CME cleared swap at 8.8bp of spread. …
# > We hedge the trade by paying the belly of the 2s5s10s swap fly with notional
# > weights of \$147mm/-\$85.6mm/\$20.89mm (0.705/-1/0.465 DV01 weights) at
# > -18.2bp in terms of the level of the DV01-weighted fly. … We set the target
# > at +\$600k profit with the stop at -\$350k loss.
#
# > To build a more optimal hedging strategy, we regressed Blues CA on 2y, 5y
# > and 10y swap rates … with the fitted value effectively being a 2s5s10s fly
# > with 0.705/-1/0.465 DV01 weights (Figure 6). The CA is about 3bp (about 2
# > sigmas) wide to the fly … Our trade is constructed as a convergence trade
# > between the Blues CA and the 2s5s10s fly, precisely as illustrated in
# > Figure 6.
#
# ## What this notebook is
#
# A **pre-registered backtest of that rule**, as a rule: the screen across the
# strip, the fitted hedge, the five-condition entry conjunction, the dollar
# target and stop, short only, held through the quarterly rolls on dated
# instruments. The declared cell list is frozen in
# `docs/convexityrv/citi-framework-preregistration.md`, committed before any
# P&L was computed, and the test suite counts the code's cells against that
# document.
#
# It is **not** block 4 again. Block 4 (`gv_grid`, PR #496) scored 298 cells of
# "CA versus a butterfly, z-score in, z-score out" and found nothing; that grid
# used a rolling univariate beta against a fixed 50/50 fly, froze it at entry,
# picked one structure per cell, entered on `|z| ≥ 2`, exited on z, traded both
# sides, and sat flat across every roll. Citi's framework does none of those
# things. The pre-registration's §0 table is the line-by-line difference.
#
# **The standing caveat.** This is the fifth pass over the same CA panel
# (`strat2`, `cavf`/PR #492, `gv`/PR #496, the reproduction/PR #499, now this).
# Declaring one rule today does not undo four prior searches, and every number
# below carries that.
#
# **Everything here reads prebuilt artifacts.** The panel, the grid, the engine
# certification and the control battery are produced by the `_p4_*.py` runners;
# this notebook loads them and does no market-data I/O of its own.

# %%
import os
import sys
import warnings

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.append("../../..")
warnings.filterwarnings("ignore")

import json
import math
import pathlib
from dataclasses import dataclass

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
from plotly.subplots import make_subplots

pio.renderers.default = "plotly_mimetype+notebook_connected"
pd.set_option("display.width", 240)
pd.set_option("display.max_columns", 80)
pd.set_option("display.max_rows", 200)

from BT.trade_dashboard import compare_curves, trade_dashboard
from RVUtils.ConvexityRV import citi_engine as CE
from RVUtils.ConvexityRV import citi_fv as FV
from RVUtils.ConvexityRV import citi_rule as R
from RVUtils.ConvexityRV import citi_screen as SC

print(f"pandas {pd.__version__}   numpy {np.__version__}")

# %% [markdown]
# ## CONFIG
#
# Every knob, and the note's own printed value beside it. These are the
# **declared** values of the pre-registration; the notebook does not re-choose
# any of them.

# %%
@dataclass(frozen=True)
class Config:
    data_dir: str = "../../data/convexity_rv"
    prereg: str = "../../../docs/convexityrv/citi-framework-preregistration.md"

    # ---- the note's printed ticket, verbatim ----------------------------
    #: "We sell $200k DV01 of Blues convexity adjustments"
    ca_dv01: float = 200_000.0
    #: "at 8.8bp of spread" / "at -18.2bp in terms of the level of the fly"
    entry_ca_bp: float = 8.8
    entry_fly_bp: float = -18.2
    #: Figure 6: CA_bp = 9.7 + 20.6 * (-0.705*r2 + r5 - 0.465*r10), rates PERCENT
    fig6_a: float = FV.CITI_FEB2017_A
    fig6_b: float = FV.CITI_FEB2017_B
    fig6_w2: float = FV.CITI_FEB2017_W2
    fig6_w10: float = FV.CITI_FEB2017_W10
    #: "target at +$600k profit with the stop at -$350k loss"
    target_usd: float = 600_000.0
    stop_usd: float = -350_000.0
    #: the note's own exit: closed 6-Jun-2017 at 6.6bp CA / -16.5bp fly, and
    #: Citi's table records +$552k against a +$600k target
    exit_ca_bp: float = 6.6
    exit_fly_bp: float = -16.5
    recorded_pnl_usd: float = 552_000.0
    #: "The CA is about 3bp (about 2 sigmas) wide to the fly"
    fig6_wide_bp: float = 3.0
    #: Figure 20's H0-Z0 row, close of 12-Jan-2017 (Eurodollars)
    fig20_ca_bp: float = 10.02
    fig20_vs_model_bp: float = 4.61
    fig20_roll_bp: float = 1.30
    fig20_implied: float = 125.5
    fig20_realized: float = 95.1

    # ---- the declared rule ----------------------------------------------
    #: the two rungs of the declared threshold ladder (pre-reg §1 M6)
    z_levels: tuple = R.Z_LEVELS
    #: Figure 20 prints Impl/Rlzd 1.3 on the row Citi traded
    impl_rlzd_min: float = 1.3
    #: "historically high" dealer longs
    z_pos_min: float = 1.0
    #: the reproduction's declared fair-value refit window
    fit_window_bd: int = 504
    #: Citi's two published trades ran 82 and 45 business days
    max_hold_bd: int = 126
    #: fills lag decisions by one mark
    exec_lag_bd: int = 1
    #: 23 declared cells (pre-reg §7)
    n_declared: int = 23


CFG = Config()
DATA = pathlib.Path(CFG.data_dir)

P = pd.read_parquet(DATA / "p4_citi.parquet")
P.index = pd.to_datetime(P.index)
PRE = json.loads((DATA / "p4_preflight.json").read_text())
PROBE = json.loads((DATA / "p4_conjunction_probe.json").read_text())
TIE = json.loads((DATA / "p4_tieout_repro.json").read_text())
CERTIN = json.loads((DATA / "p4_input_certification.json").read_text())
STATS = pd.read_parquet(DATA / "p4_grid_stats.parquet")
EPS = pd.read_parquet(DATA / "p4_grid_episodes.parquet")
RET = pd.read_parquet(DATA / "p4_grid_returns.parquet")
BIND = pd.read_parquet(DATA / "p4_grid_binding.parquet")
GMETA = json.loads((DATA / "p4_grid_meta.json").read_text())
ENG = pd.read_parquet(DATA / "p4_engine_stats.parquet")
EQ = pd.read_parquet(DATA / "p4_engine_equity.parquet")
CTRL = json.loads((DATA / "p4_controls.json").read_text())

SPAN = float(PRE["span_tradeable_years"])
BAR = float(GMETA["bar_annualised_23"])
print(f"panel {P.shape}  {P.index.min().date()}..{P.index.max().date()}")
print(f"tradeable span {SPAN:.3f} y from {PRE['first_defined']}")
print(f"{len(STATS)} declared cells; the bar is E[max SR | null] = {BAR:.4f} "
      f"annualised at {CFG.n_declared} trials")
assert len(STATS) == CFG.n_declared == len(R.declared_cells())

# %% [markdown]
# ## Sign probe
#
# The conventions this backtest can silently get wrong, asserted against live
# objects rather than argued about in prose.

# %%
_E = __import__("datetime").date(2024, 3, 5)
_X = __import__("datetime").date(2024, 6, 5)
_sp = CE.spec_from_episode(structure="BLUES", side=-1, entry=_E, exit=_X,
                           ca_dv01=CFG.ca_dv01,
                           hedge_path=[(_E, CFG.fig6_b / 100.0, CFG.fig6_w2,
                                        CFG.fig6_w10)])
_q = CE.build_queries(_sp)

# 1. SELLING the CA is BUYING the futures pack and PAYING the matched swap.
_futs = [x for x in _q[_sp.tag] if type(x).__name__ == "STIRFutureQuery"]
_swap = [x for x in _q[_sp.tag] if type(x).__name__ == "IRSwapQuery"][0]
assert len(_futs) == 4
for _f in _futs:
    _k = _f.structure_kwargs
    assert _k["contracts"] > 0 and _k["risk_weights"] == [1.0]
assert _swap.structure_kwargs["bpv"] == CFG.ca_dv01
print(f"side -1 = SELL the CA:  buy {_futs[0].structure_kwargs['contracts']} of "
      f"each of 4 SR3 contracts (risk weight +1), and PAY "
      f"${_swap.structure_kwargs['bpv']:,.0f}/bp on the matched "
      f"{_sp.swap_start}..{_sp.swap_end} swap")

# 2. The fitted fly goes in at ONE times the quoted DV01, not two. gv_engine
#    quotes 2b-f-k with 50/50 wings and must send 2x; this fly is quoted
#    r5 - w2*r2 - w10*r10 and a [w2, 1, w10] package earns exactly bpv per bp.
_fly = _q[_sp.fly_tag(0)][0].structure_kwargs
assert _fly["risk_weights"] == [CFG.fig6_w2, 1.0, CFG.fig6_w10]
assert abs(_fly["bpv"] - (CFG.fig6_b / 100.0) * CFG.ca_dv01) < 1e-6
print(f"hedge: risk weights {_fly['risk_weights']}, belly bpv "
      f"${_fly['bpv']:,.0f}/bp  (= beta {CFG.fig6_b / 100:.3f} x "
      f"${CFG.ca_dv01:,.0f}) -- POSITIVE is PAY the belly, as the note says")

# 3. A negative fitted scale FLIPS the hedge; it does not shrink it.
_neg = CE.spec_from_episode(structure="BLUES", side=-1, entry=_E, exit=_X,
                            ca_dv01=CFG.ca_dv01,
                            hedge_path=[(_E, -CFG.fig6_b / 100.0, 0.5, 0.5)])
assert (_neg.fly_segments[0].leg_dv01_signed
        * _sp.fly_segments[0].leg_dv01_signed) < 0
print(f"a negative b flips the leg: {_sp.fly_segments[0].leg_dv01_signed:+,.0f} "
      f"-> {_neg.fly_segments[0].leg_dv01_signed:+,.0f} per bp")

# 4. The dollar target and stop ARE the note's printed numbers.
_cfg = R.RuleConfig()
assert _cfg.target_usd == CFG.target_usd and _cfg.stop_usd == CFG.stop_usd
assert _cfg.side == -1
print(f"target {_cfg.target_bp:+.2f}bp = ${_cfg.target_usd:+,.0f}   "
      f"stop {_cfg.stop_bp:+.2f}bp = ${_cfg.stop_usd:+,.0f}   "
      f"on ${_cfg.ca_dv01:,.0f} DV01, short only")

# 5. The traded object is the SPREAD, and its beta is bp per bp.
_fit = FV.FairValueFit(CFG.fig6_a, CFG.fig6_b, CFG.fig6_w2, CFG.fig6_w10, 0.9, 500)
assert abs(_fit.beta_bp_per_bp - 0.206) < 1e-9
print(f"beta {CFG.fig6_b} bp of CA per PERCENT of fly = "
      f"{_fit.beta_bp_per_bp:.4f} bp per bp; the fitted weights sum to "
      f"{_fit.w2 + _fit.w10:.3f}, so Citi's published hedge carries "
      f"{_fit.net_weight:+.3f} of outright duration per unit of belly DV01")

# %% [markdown]
# ## Known-answer tie-out
#
# Four numbers the note prints must be mutually consistent under this reading of
# its conventions, and the one trade whose outcome Citi published must fall out
# of the identity this backtest books P&L on. If they do not, the reading is
# wrong and everything downstream is fitted to a fiction.

# %%
_A2, _A5, _A10 = (FV.annuity(2.0, y) for y in (2, 5, 10))

# (a) the printed NOTIONALS reproduce the printed DV01 WEIGHTS
_w2i = (147.0 * _A2) / (85.6 * _A5)
_w10i = (20.89 * _A10) / (85.6 * _A5)
print(f"(a) DV01 weights implied by $147mm/-$85.6mm/$20.89mm at a flat 2% curve: "
      f"2y {_w2i:.4f} vs {CFG.fig6_w2} ({100 * (_w2i / CFG.fig6_w2 - 1):+.2f}%), "
      f"10y {_w10i:.4f} vs {CFG.fig6_w10} ({100 * (_w10i / CFG.fig6_w10 - 1):+.2f}%)")
assert abs(_w2i / CFG.fig6_w2 - 1) < 0.02 and abs(_w10i / CFG.fig6_w10 - 1) < 0.02

# (b) the regression BETA is the hedge ratio
_belly = _fit.beta_bp_per_bp * CFG.ca_dv01
_belly_n = 85.6 * _A5 * 100.0
print(f"(b) belly DV01 from the Figure-6 beta ${_belly:,.0f}/bp vs from the "
      f"printed notional ${_belly_n:,.0f}/bp ({100 * (_belly / _belly_n - 1):+.1f}%)")
assert abs(_belly / _belly_n - 1) < 0.06

# (c) the printed CARRY is the two printed roll numbers on those DV01s
_carry = 1.3 * CFG.ca_dv01 + 3.2 * _belly
print(f"(c) carry = 1.3bp x ${CFG.ca_dv01:,.0f} + 3.2bp x ${_belly:,.0f} = "
      f"${_carry:,.0f} vs the note's $380,000 "
      f"({100 * (_carry / 380_000 - 1):+.1f}%)")
assert abs(_carry / 380_000 - 1) < 0.08

# (d) the printed RICHNESS falls out of the printed fit
_fitted_at_entry = CFG.fig6_a + CFG.fig6_b * (CFG.entry_fly_bp / 100.0)
_rich = CFG.entry_ca_bp - _fitted_at_entry
print(f"(d) fly {CFG.entry_fly_bp:+.1f}bp -> fitted CA {_fitted_at_entry:.3f}bp, "
      f"CA {CFG.entry_ca_bp}bp -> rich {_rich:+.3f}bp vs 'about "
      f"{CFG.fig6_wide_bp:.0f}bp'")
assert abs(_rich - CFG.fig6_wide_bp) < 0.25

# (e) THE PUBLISHED TRADE'S OWN P&L, from the identity this backtest books on
_pnl = -1 * ((CFG.exit_ca_bp - CFG.entry_ca_bp)
             - _fit.beta_bp_per_bp * (CFG.exit_fly_bp - CFG.entry_fly_bp)) \
       * CFG.ca_dv01
print(f"(e) side*(dCA - beta*dfly)*DV01 = -1 * (("
      f"{CFG.exit_ca_bp}-{CFG.entry_ca_bp}) - {_fit.beta_bp_per_bp:.3f}*("
      f"{CFG.exit_fly_bp}-({CFG.entry_fly_bp}))) * {CFG.ca_dv01:,.0f} = "
      f"${_pnl:,.0f}")
print(f"    Citi's own table records ${CFG.recorded_pnl_usd:,.0f} and the alert "
      f"says 'net +$500k' ({100 * (_pnl / CFG.recorded_pnl_usd - 1):+.1f}% vs "
      "the table)")
assert 4.7e5 < _pnl < 5.6e5

# (f) the promoted fair-value module reproduces the reproduction's own path
print(f"\n(f) citi_fv against the reproduction it was lifted from "
      f"({TIE['window'][0]}..{TIE['window'][1]}, {TIE['fit_window_bd']} bd):")
print(f"    b sign flips {TIE['refit']['b_sign_flips']} at the "
      f"{TIE['refit']['flip_at']} refit;  w2 {TIE['refit']['w2_first']:.2f} -> "
      f"{TIE['refit']['w2_last']:.2f};  b {TIE['refit']['b_first']:+.1f} -> "
      f"{TIE['refit']['b_last']:+.1f}")
print(f"    OOS residual sd: IMM refit {TIE['residuals']['sd_refit']:.3f} bp, "
      f"Citi's fixed 2017 weights {TIE['residuals']['sd_citi']:.3f} bp")
print(f"    fly starts: best {TIE['fly_starts']['best']} at "
      f"{TIE['fly_starts']['best_sd']:.3f} bp; the matched-expiry IMM_13 ranks "
      f"{TIE['fly_starts']['matched_rank']} of {TIE['fly_starts']['n_starts']}")
assert TIE["refit"]["b_sign_flips"] == 1
assert abs(TIE["residuals"]["sd_refit"] - 2.232) < 0.005

# (g) the carried panels re-priced before anything was built on them
print(f"\n(g) inputs: CA panel re-price max |diff| "
      f"{CERTIN['ca_reprice_max_abs_diff_bp']:.10f} bp over "
      f"{CERTIN['ca_reprice_cells']} cells; {CERTIN['rolls']['ca']} CA rolls and "
      f"{CERTIN['rolls']['leg']} leg rolls with {CERTIN['rolls']['common']} in "
      "common")
assert CERTIN["ca_reprice_max_abs_diff_bp"] < 1e-9
assert CERTIN["rolls"]["common"] == 0
print("\nAll seven tie out. The reading of the note's conventions is confirmed "
      "from the note's own printed numbers, and the promoted module from the "
      "reproduction's own recorded path, before any backtest number is read.")

# %% [markdown]
# ## Figure 20 — the screen, on every date
#
# > *"Figure 20 offers a systematic analysis of the valuation in convexity
# > adjustments across the curve. We analyze 1y packs (four consecutive
# > contracts) because individual ED/FRA spreads are noisy and hard to trade."*
#
# The note prints one date; the backtest needs it on every date, because the
# screen is what chooses which structure to trade.

# %%
S = SC.build_screen(P)
_ids = SC.verify_identities(S, P)
print(f"identity  CA - Model - VsModel  max |err| "
      f"{_ids['ca_minus_model_minus_vsmodel']:.3e} bp "
      f"({_ids['n_cells_skipped_vsmodel']} cells skipped: two dates carry no "
      "vol mark)")
print(f"identity  implied^2*w/2e4 == CA  max |err| "
      f"{_ids['implied_reconstructs_ca']:.3e} bp "
      f"({_ids['n_cells_skipped_implied']} skipped: a non-positive CA has no "
      "real implied vol, and the front packs go negative often)")
assert _ids["ca_minus_model_minus_vsmodel"] < 1e-9
assert _ids["implied_reconstructs_ca"] < 1e-6

_last = P.index[-1]
print(f"\nFigure 20 analogue, close of {_last.date()}:\n")
print(SC.screen_table(S, _last).round(2).to_string())
print(f"\nCiti's H0-Z0 row (12-Jan-2017, ED): CA {CFG.fig20_ca_bp}, VsModel "
      f"{CFG.fig20_vs_model_bp}, 3m Roll {CFG.fig20_roll_bp}, Implied "
      f"{CFG.fig20_implied}, Realized {CFG.fig20_realized}, Impl/Rlzd "
      f"{CFG.fig20_implied / CFG.fig20_realized:.1f}")

# %% [markdown]
# ### The roll column, two ways
#
# The note's `3m Roll` is `CA(p) − CA(p one contract nearer)`. Colour packs are
# four contracts — one year — apart, so the adjacent-quarter neighbour does not
# exist in the tradeable set. The declared column is the analytic equivalent,
# one quarter of the CA's own decay `dCA/dt = −σ²·mean(T1)/1e4`; the
# term-structure form `[CA(p) − CA(p one YEAR nearer)]/4` is measured beside it
# rather than asserted equal to it.

# %%
print(SC.roll_identity(S).round(4).to_string())
_rj = pd.DataFrame(PRE["roll_jump"]).set_index("structure")
print("\nand the same quantity a third way -- the measured IMM-roll JUMP, which "
      "is the theta being paid back:")
print(_rj[["n_rolls", "mean_dCA_on_roll", "t_on_roll", "quarter_theta_bp",
           "jump_over_quarter_theta"]].round(4).to_string())
print("\nGREENS / BLUES / GOLDS agree to 2-11%. WHITES and REDS do not, and "
      "they are the two structures whose daily marks sit at or past the -0.5 "
      "pure-noise bound -- which is why they are out of the primary selection "
      "universe.")

# %% [markdown]
# ## Figure 6 — the fitted fair value, and whether it is stable enough to hedge with
#
# Citi's method: regress the CA on 2y/5y/10y and read the hedge weights off the
# fit. Here it is fly-constrained (`w₂ + w₁₀ = 1`, so the fitted object is a
# real butterfly), refit at every quarterly SR3 IMM roll on a trailing 504 bd
# window ending strictly before the roll, and applied out of sample until the
# next roll.

# %%
_fvrows = []
for _lab, _d in PRE["fair_value"].items():
    _fvrows.append({"structure": _lab, "n_refits": _d["n_refits"],
                    "w2_median": _d["w2_median"], "w2_range": _d["w2_range"],
                    "b_median": _d["b_median"],
                    "b_sign_flips": _d["b_sign_flips"],
                    "w2_at_a_boundary": _d["n_boundary_w2"],
                    "oos_resid_sd_bp": _d["oos_resid_sd_bp"],
                    "oos_resid_mae_bp": _d["oos_resid_mae_bp"]})
FVT = pd.DataFrame(_fvrows).set_index("structure")
print(FVT.round(3).to_string())
print(f"\nOn the reproduction's narrower window (2022 start) BLUES has ONE sign "
      f"flip and a residual sd of {TIE['residuals']['sd_refit']:.3f} bp. Adding "
      "2021 doubles both. The window was not narrowed to hide that: the panel "
      "is the full CA panel and the instability is a result.")

_f = go.Figure()
for _lab, _d in PRE["fair_value"].items():
    _f.add_trace(go.Scatter(x=pd.to_datetime(_d["in_force_from"]), y=_d["b_path"],
                            name=_lab, mode="lines+markers"))
_f.add_hline(y=0.0, line_dash="dash", line_color="black")
_f.update_layout(title="The fitted scale b, refit at every IMM roll — crossing "
                       "zero is the failure mode",
                 yaxis_title="b (bp of CA per percent of fly)", height=430,
                 legend=dict(orientation="h", y=1.10))
_f.show()
print("A hedge ratio whose SIGN changes inside its own sample cannot be hedged "
      "with, however well it fits on average: the hedge would have to be turned "
      "upside down mid-trade and nothing in the fit says in advance which side "
      "of the flip it is on.")

# %% [markdown]
# ## The entry conjunction — and the headline finding
#
# The note's entry is five conditions at once. Each threshold below is the
# note's own printed value, frozen in the pre-registration before anything was
# scored.

# %%
CTX = R.build_contexts(P, S, R.RuleConfig(), structures=SC.SCREEN_STRUCTURES)
CTXP = {k: v for k, v in CTX.items() if k in R.PRIMARY_UNIVERSE}
B = R.condition_binding(CTXP, R.RuleConfig())
print(B[[f"pass_{k}" for k in R.CONDITIONS] + ["pass_all"]].round(4).to_string())
_nest = pd.DataFrame(PROBE["nested"]).set_index("structure")
print("\nnested, one condition at a time (days surviving):")
print(_nest.to_string())
_days = PROBE["days_open_raw"]
print(f"\n**The five-way conjunction is satisfied on {_days} of {len(P)} dates "
      "across the whole primary universe.**")

# %% [markdown]
# ### Why: two of the note's own conditions fight the first one
#
# The pairwise **lift** is the observed joint pass rate divided by the rate
# under independence. Above one, two conditions agree; below one, they fight.

# %%
LIFT = pd.DataFrame(PROBE["pair_lift_blues"])
LIFT = LIFT.loc[list(R.CONDITIONS), list(R.CONDITIONS)]
print(LIFT.round(3).to_string())
print("\n* `wide_to_model` x `implied_rich` = "
      f"{LIFT.loc['wide_to_model', 'implied_rich']:.2f}: a CA that is unusually "
      "wide to the Ho-Lee model tends to occur when realised vol has been HIGH, "
      "so implied/realised is low at exactly the moment the model says the "
      "adjustment is rich.")
print("* `wide_to_model` x `positioning_stretched` = "
      f"{LIFT.loc['wide_to_model', 'positioning_stretched']:.2f}: the note's "
      "causal chain -- dealers long futures -> structurally short CA -> wider "
      "CA -- runs the OTHER WAY on SOFR. Measured separately: "
      f"corr(BLUES CA-vs-model, dealer 1Y z) = "
      f"{CERTIN['cftc']['corr_vsmodel_vs_dealerz']:+.3f}.")
print("* `wide_to_model` x `wide_to_fly` = "
      f"{LIFT.loc['wide_to_model', 'wide_to_fly']:.2f}: better than "
      "independence, but the two 'wideness' measures the note treats as saying "
      "the same thing pass 2.3% of days each and only 0.14% jointly.")

# %% [markdown]
# ### The declared threshold ladder
#
# A rule with two entry days cannot be graded, so the pre-registration declares
# **two rungs** — the note's own 2.0σ and a widened 1.0σ — and prints the rungs
# it does not walk so a reader can see the ladder rather than wonder about it.

# %%
LAD = pd.DataFrame(PROBE["ladder"])
print(LAD.pivot(index="z_min", columns="impl_rlzd_min",
                values="days_any_structure").to_string())
print("\nrows are the z threshold on BOTH wideness conditions, columns the "
      "impl/rlzd floor; the cell is the number of dates on which SOME primary "
      f"structure passes all five. **Scored: z = {CFG.z_levels[0]} and "
      f"z = {CFG.z_levels[1]} at impl/rlzd {CFG.impl_rlzd_min}. NOT scored: "
      "1.5, 0.5 and 0.0.**")

# %%
_f = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.62, 0.38],
                   vertical_spacing=0.07,
                   subplot_titles=("BLUES convexity adjustment, its Ho-Lee "
                                   "model level and its fitted fly",
                                   "the two wideness z-scores, and the 2σ line"))
_f.add_trace(go.Scatter(x=P.index, y=CTX["BLUES"].ca_pnl * 0
                        + P["blues_ca_bp"], name="Blues CA"), row=1, col=1)
_f.add_trace(go.Scatter(x=P.index, y=S["model"]["BLUES"], name="Ho-Lee model"),
             row=1, col=1)
_f.add_trace(go.Scatter(x=CTX["BLUES"].fitted.dropna().index,
                        y=CTX["BLUES"].fitted.dropna(),
                        name="fitted 2s5s10s fly (OOS)"), row=1, col=1)
_f.add_trace(go.Scatter(x=P.index, y=CTX["BLUES"].z_model, name="z vs model",
                        line=dict(color="#4dabf7")), row=2, col=1)
_f.add_trace(go.Scatter(x=P.index, y=CTX["BLUES"].z_fly, name="z vs fly",
                        line=dict(color="#ff9f43")), row=2, col=1)
_f.add_hline(y=2.0, line_dash="dot", row=2, col=1)
_f.add_hline(y=1.0, line_dash="dash", row=2, col=1)
_f.update_yaxes(title_text="bp", row=1, col=1)
_f.update_yaxes(title_text="sigma", row=2, col=1)
_f.update_layout(height=640, legend=dict(orientation="h", y=1.06))
_f.show()

# %% [markdown]
# ## The declared grid
#
# 23 cells, one headline. The bar is `E[max SR | null]` at 23 trials on the
# **tradeable** span, not the panel span: a book that cannot open until its fair
# value and its z-scores exist has not been running for the whole panel.

# %%
_cols = ["cell_id", "tier", "headline", "hedge", "selection", "n_conditions",
         "n_episodes", "mean_hold_bd", "n_eff", "hit_rate", "exit_target",
         "exit_stop", "exit_max_hold", "exit_end_of_sample", "net_0.0",
         "sharpe_0.0", "net_1.0", "sharpe_1.0", "net_2.0", "sharpe_2.0",
         "breakeven_bp", "carry_share"]
print(STATS[_cols].round(4).to_string(index=False))
_alive = STATS[STATS["sharpe_1.0"] > BAR]
print(f"\nE[max SR | null] at {CFG.n_declared} trials, span {SPAN:.3f} y: "
      f"**{BAR:.4f}** annualised "
      f"({GMETA['null_bars']['23']['emax_perhold']:.4f} per-hold)")
print(f"cells clearing it at 1x costs: **{len(_alive)} of {len(STATS)}**")
print(f"best net Sharpe on the panel: {STATS['sharpe_1.0'].max():+.4f} "
      f"({STATS.loc[STATS['sharpe_1.0'].idxmax(), 'cell_id']})")
print(f"best GROSS Sharpe: {STATS['sharpe_0.0'].max():+.4f} "
      f"({STATS.loc[STATS['sharpe_0.0'].idxmax(), 'cell_id']})")
assert len(_alive) == GMETA["n_alive_1x"]
assert STATS["sharpe_0.0"].max() < BAR, (
    "a cell clears the bar even GROSS -- the verdict prose below is wrong")

# %% [markdown]
# ### The headline — the note's own trade at the note's own thresholds

# %%
_h = STATS[STATS["headline"]].iloc[0]
_he = EPS[EPS.cell_id == _h["cell_id"]]
print(f"{_h['cell_id']}\n")
print(_he[["structure", "entry_decision", "entry_fill", "exit_fill", "hold_bd",
           "beta_entry", "w2_entry", "exit_reason", "z_model", "z_fly",
           "rich_bp", "impl_rlzd", "z_pos", "gross_usd"]].round(3).to_string(index=False))
print(f"\ntwo episodes in {SPAN:.1f} years. Net at 1x costs "
      f"${_h['net_1.0']:,.0f}, annualised Sharpe {_h['sharpe_1.0']:+.4f} "
      f"against a bar of {BAR:.4f}.")
print("\nThe first is the March-2023 regional-bank week: the Blues CA was "
      f"{_he.iloc[0]['rich_bp']:.1f}bp rich to its own fitted fly at "
      f"{_he.iloc[0]['z_model']:.2f} sigma to the model -- exactly the setup the "
      "note describes -- and it widened further. The stop did its job and the "
      "trade lost "
      f"${abs(_he.iloc[0]['gross_usd']):,.0f} in {int(_he.iloc[0]['hold_bd'])} "
      "business days. The second opened two weeks before the end of the sample "
      "and is still open.")

# %% [markdown]
# ## The second clock — per-hold, not annualised
#
# The pre-registration requires `E[max SR | null]` on **both** clocks (§6, §11)
# and the grid above grades only the annualised one. For a book that is flat on
# 99% of its dates the two are not interchangeable:
#
# * the **annualised daily** Sharpe divides by the sd of a series that is mostly
#   zeros, so it measures the equity curve an investor would actually hold, idle
#   capital included. Four trades over 1,409 dates score low almost by
#   construction;
# * the **per-hold** Sharpe is `mean / sd` over the EPISODES and measures the
#   quality of the trades that were taken. Its null sd is `1/sqrt(n_eff)`, which
#   is exactly what `null_bars(..., n_eff=...)["emax_perhold"]` returns.
#
# Grading either against the other's bar is the "which column is the claim true
# in" error. Amendment A1 of the pre-registration records that this grading was
# computed after the grid ran; it adds no cells and no trials.

# %%
PH = pd.read_parquet(DATA / "p4_perhold.parquet")
_pc = ["cell_id", "tier", "headline", "n", "n_eff", "trades_per_year",
       "perhold_sharpe_gross", "perhold_sharpe_net", "bar_perhold",
       "clears_perhold_gross", "clears_perhold_net", "p_signflip_gross",
       "p_signflip_net"]
print(PH[_pc].round(4).to_string(index=False))
_cg = PH[PH["clears_perhold_gross"].astype("boolean").fillna(False).astype(bool)]
_cn = PH[PH["clears_perhold_net"].astype("boolean").fillna(False).astype(bool)]
print(f"\ncells clearing their own per-hold bar GROSS: {len(_cg)} of {len(PH)}")
print(f"cells clearing it NET of 1x costs:          {len(_cn)} of {len(PH)}")
print(f"best per-hold Sharpe gross {PH['perhold_sharpe_gross'].max():+.4f}, "
      f"net {PH['perhold_sharpe_net'].max():+.4f}")
print(f"best shared-sign-flip p on NET per-episode P&L: "
      f"{PH['p_signflip_net'].min():.4f}")
assert len(_cn) == 0, "a cell clears the per-hold bar NET -- the verdict changes"

# %% [markdown]
# ### Read the two clocks together
#
# Apart they say different things and both are true. The framework selects
# trades that are better than chance *gross* and cannot pay for them; and the
# book it produces is far too sparse to run whatever the trades are worth.

# %%
_join = STATS[["cell_id", "sharpe_0.0", "sharpe_1.0"]].merge(
    PH[["cell_id", "n", "perhold_sharpe_gross", "perhold_sharpe_net",
        "bar_perhold"]], on="cell_id", how="left")
_join["bar_annualised"] = BAR
_join["clears_annualised_gross"] = _join["sharpe_0.0"] > BAR
_join["clears_perhold_gross"] = (_join["perhold_sharpe_gross"]
                                 > _join["bar_perhold"])
print(_join.round(4).to_string(index=False))
print(f"\nannualised clock: {int(_join['clears_annualised_gross'].sum())} of "
      f"{len(_join)} clear GROSS, "
      f"{int((STATS['sharpe_1.0'] > BAR).sum())} clear NET")
print(f"per-hold clock:   {int(_join['clears_perhold_gross'].fillna(False).sum())} "
      f"of {len(_join)} clear GROSS, {len(_cn)} clear NET")
_a = float(PH.loc[PH.cell_id == "D|z1.0|drop_positive_roll", "net_usd"].iloc[0])
_b = float(PH.loc[PH.cell_id == "P|z1.0|screen_best|fitted_refit",
                  "net_usd"].iloc[0])
assert abs(_a - _b) < 1e-6, "the drop_positive_roll claim below is wrong"
print(f"\nThree of the {len(_cg)} gross-clearing cells are drop-one "
      "DIAGNOSTICS, and D|z1.0|drop_positive_roll is IDENTICAL to "
      f"P|z1.0|screen_best|fitted_refit (both ${_a:,.0f} net) because the "
      "positive-roll condition passes on 99.86% of dates and the days it "
      "refuses never coincide with the other four passing. What is left is the "
      "screen_best z=1.0 family, on four trades, whose own per-hold null sd is "
      "0.5 -- which is why its bar is 0.98.")

# %% [markdown]
# ## Engine certification
#
# The panel decides WHEN; the engine says what it was worth. Every reported book
# is replayed through `QueryDrivenBacktest` on dated instruments — four SR3
# contracts, a matched-maturity quarterly/quarterly swap, and a spot 2s5s10s fly
# at the fitted weights re-struck at each quarterly refit inside the hold — with
# `assert_ran` afterwards, because `run()` swallows exceptions and a failed
# backtest looks like a flat equity curve.

# %%
_ec = ["cell_id", "n_episodes", "n_closed_positions", "n_marks",
       "panel_gross_usd", "engine_gross_usd", "panel_net_usd", "engine_net_usd",
       "panel_sharpe_net", "engine_sharpe_net", "daily_corr_engine_panel",
       "carry_usd", "engine_residual_usd"]
E = ENG[_ec].copy()
E["engine_over_panel_gross"] = E["engine_gross_usd"] / E["panel_gross_usd"]
print(E.round(4).to_string(index=False))
print(f"\nbest ENGINE net Sharpe of any certified book: "
      f"{ENG['engine_sharpe_net'].max():+.4f} "
      f"({ENG.loc[ENG['engine_sharpe_net'].idxmax(), 'cell_id']}), against a "
      f"bar of {BAR:.4f}.")
print("\nThe gap between the two columns is the point of running both. It is "
      "not noise and it does not have one sign: on "
      f"{(E['engine_over_panel_gross'] < 0).sum()} of {len(E)} books the engine "
      "and the panel disagree on the SIGN of the gross P&L, and the largest "
      "single disagreement is "
      f"{E.loc[E['engine_over_panel_gross'].abs().idxmax(), 'cell_id']} at a "
      f"ratio of {E['engine_over_panel_gross'].abs().max():.2f}. A par-rate "
      "panel prices par-rate changes; the engine prices struck instruments that "
      "age, and the omitted term is carry.")

# %%
_f = go.Figure()
for _c in EQ.columns:
    _f.add_trace(go.Scatter(x=pd.to_datetime(EQ.index), y=EQ[_c], name=_c,
                            mode="lines"))
_f.add_hline(y=0.0, line_dash="dot")
_f.update_layout(title="Engine equity, net of the declared costs — every "
                       "certified book",
                 yaxis_title="USD", height=520,
                 legend=dict(orientation="h", y=-0.25))
_f.show()

# %% [markdown]
# ## The control battery
#
# None of these is a scored cell; each is a control on a cell already scored,
# and every one is declared in the pre-registration.

# %% [markdown]
# ### 1. Same-day fills — the mark-noise harvest

# %%
_sd = pd.DataFrame(CTRL["same_day"])
_w = _sd.pivot(index="cell_id", columns="exec_lag_bd", values="gross_usd")
_w["harvest_usd"] = _w[0] - _w[1]
print(_w.round(0).to_string())
print(f"\nEvery one of the {len(_w)} cells is worth "
      f"${_w['harvest_usd'].min():,.0f} to ${_w['harvest_usd'].max():,.0f} MORE "
      "when it is filled at the mark its own signal was computed from, and the "
      f"harvest is positive on {int((_w['harvest_usd'] > 0).sum())} of "
      f"{len(_w)}. That gap is not a strategy: the CA mark is a composite of a "
      "futures bar and a separately-timed swap curve, and a rule that shorts a "
      "rich mark AT that mark banks a reversion nobody can trade. It is the "
      "single best argument for the `exec_lag_bd = 1` convention, which every "
      "number in this notebook uses.")
assert (_w["harvest_usd"] > 0).all()

# %% [markdown]
# ### 2. The placebo ladder — a timing signal must die under lag

# %%
_pl = pd.DataFrame(CTRL["placebo"])
print(_pl.pivot(index="cell_id", columns="signal_lag_bd",
                values="sharpe_gross").round(4).to_string())
print("\ngross $ at each lag:")
print(_pl.pivot(index="cell_id", columns="signal_lag_bd",
                values="gross_usd").round(0).to_string())
_pw = _pl.pivot(index="cell_id", columns="signal_lag_bd", values="sharpe_gross")
_live = _pw[_pw[0] > 0]
print(f"\nOf the {len(_pw)} cells, {len(_live)} make money unlagged. Every "
      f"one of those {len(_live)} is NEGATIVE by 40 bd of lag "
      f"(max {_live[40].max():+.4f}), and the median decay from lag 0 to lag "
      f"60 is {float((_live[0] - _live[60]).median()):+.4f} of Sharpe. So the "
      "small edge that is there is genuinely about WHEN rather than a slow "
      "level effect -- it is just an order of magnitude below the bar.")
assert (_live[40] < 0).all()

# %% [markdown]
# ### 3. The always-short control — how much of the book is a static position?

# %%
_as = pd.DataFrame(CTRL["always_short"])
print(_as.round(0).to_string(index=False))
_sd2 = pd.DataFrame(CTRL["always_short"])
_raw = pd.read_parquet(DATA / "p4_controls_static.parquet")
print(f"\nThe static short is profitable on its own on "
      f"{int((_raw['per_trade_usd'] > 0).sum())} of {len(_raw)} "
      f"(cell, structure) pairs, at ${_raw['per_trade_usd'].min():,.0f} to "
      f"${_raw['per_trade_usd'].max():,.0f} per trade: a short-convexity book "
      "collects the CA's theta whether or not a signal fired. The signal's "
      "own contribution is the last column above, and it is positive on "
      f"{int((_sd2['signal_edge_usd'] > 0).sum())} of {len(_sd2)} cells -- on "
      "four trades each.")

# %% [markdown]
# ### 4. β = 0 — does the fly leg contribute?

# %%
print(pd.DataFrame(CTRL["beta_zero"]).round(4).to_string(index=False))
_b0 = pd.DataFrame(CTRL["beta_zero"])
_worst = _b0.loc[_b0["hedge_adds_sharpe"].idxmin()]
print(f"\nThe fly adds Sharpe on {int((_b0['hedge_adds_sharpe'] > 0).sum())} "
      f"of {len(_b0)} and removes it on "
      f"{int((_b0['hedge_adds_sharpe'] < 0).sum())}. The worst is "
      f"{_worst['cell_id']} at {_worst['hedge_adds_sharpe']:+.4f} of Sharpe "
      "against the same book with the hedge removed -- and that is Citi's "
      "own published fixed weights, held fixed.")

# %% [markdown]
# ### 5. The splice control

# %%
print(pd.DataFrame(CTRL["splice"]["roll_artifact"]).round(6).to_string(index=False))
_sp2 = pd.DataFrame(CTRL["splice"]["books"])
print("\nthe same books with the P&L splice off (i.e. booking the roll jump):")
print(_sp2.pivot(index="cell_id", columns="splice_pnl",
                 values="gross_usd").round(0).to_string())
print("\nThe splice is switched on: the raw series carries +0.95 bp per roll on "
      "BLUES and the spliced one carries exactly zero. Booking that jump would "
      "cost a short-CA book real money 22 times -- and it would be an artifact, "
      "because a DATED position has no label to switch.")

# %% [markdown]
# ### 6. The sign-flip null

# %%
print(pd.DataFrame(CTRL["signflip"]).round(4).to_string(index=False))
print("\nA row permutation leaves a Sharpe unchanged, so the null is 20,000 "
      "SHARED SIGN FLIPS on the per-episode P&L. At 4-23 episodes the smallest "
      "attainable one-sided p is 2^-n, so these are bounds on the evidence "
      "rather than measurements of it. One cell -- the secondary "
      "`screen_best_all5 x citi_2017` -- reads p = 0.024 one-sided. It is "
      "16-of-22 WHITES episodes, on the marks this package has measured at or "
      "past the pure-noise bound, and its Sharpe is still less than a quarter "
      "of the bar. It is recorded rather than promoted.")

# %% [markdown]
# ### 7. The convexity signature, as a point prediction

# %%
print(pd.DataFrame(CTRL["convexity_signature"]).round(4).to_string(index=False))
print("\nThe CA is exactly quadratic in sigma, so a convexity claim has a "
      "NUMBER attached: the fitted quadratic coefficient must equal "
      "`CA_DV01 * w / 2e4` USD per (bp/yr)^2. At four to twenty-two episodes "
      "this is a three-parameter regression on a handful of points and the "
      "fitted coefficients run 9-51x the prediction with the wrong sign half "
      "the time. The test cannot confirm or deny the claim at this sample size, "
      "and the honest reading is that the book never got large enough to have "
      "a convexity signature to test.")

# %% [markdown]
# ### 8. Sub-period split, and the sensitivities

# %%
_sub = pd.DataFrame(CTRL["subperiod"])
print(_sub.pivot(index="cell_id", columns="half",
                 values=["n_episodes", "gross_usd"]).round(0).to_string())
print("\nsensitivities on P|z1.0|screen_best|fitted_refit (reported, not scored):")
print(pd.DataFrame(CTRL["sensitivity"]).round(4).to_string(index=False))

# %% [markdown]
# ## The book, as a book
#
# `BT.trade_dashboard` on the episodes of the two cells worth looking at, and
# the equity curves side by side. `span_years` is passed explicitly — without
# it the annualised Sharpe is wrong.

# %%
_HEAD = "P|z1.0|screen_best|fitted_refit"
_bk = EPS[EPS.cell_id == _HEAD].copy()
if len(_bk):
    trade_dashboard(_bk, title=f"{_HEAD} — gross, per episode",
                    span_years=SPAN, time_col="exit_fill", pnl_col="gross_usd",
                    signal_col="z_model", colour_col="exit_reason",
                    label_col="structure", side_col="side", unit="USD").show()

# %%
_books = {}
for _c in ("P|z2.0|screen_best|fitted_refit", "P|z1.0|screen_best|fitted_refit",
           "P|z1.0|screen_best|unhedged", "S|z1.0|screen_best_all5|citi_2017"):
    _b = EPS[EPS.cell_id == _c]
    if len(_b):
        _books[_c] = _b
if _books:
    compare_curves(_books, title="declared cells — cumulative gross P&L per "
                                 "episode", time_col="exit_fill",
                   pnl_col="gross_usd", unit="USD").show()

# %% [markdown]
# ## Verdict

# %%
_best_panel = STATS["sharpe_1.0"].max()
_best_eng = ENG["engine_sharpe_net"].max()
print("VERDICT")
print("=" * 78)
print(f"* The rule AS PUBLISHED does not trade. At the note's own thresholds "
      f"the five-way conjunction is satisfied on {_days} of {len(P)} dates "
      f"across GREENS/BLUES/GOLDS, and the headline cell opens twice in "
      f"{SPAN:.1f} years for a net of ${_h['net_1.0']:,.0f}.")
print(f"* The reason is measurable and it is in the note's own conditions. "
      f"'Wide to the model' fights 'implied rich' (lift "
      f"{LIFT.loc['wide_to_model', 'implied_rich']:.2f}) and 'positioning "
      f"stretched' (lift "
      f"{LIFT.loc['wide_to_model', 'positioning_stretched']:.2f}) on SOFR, and "
      "the note's own positioning mechanism runs the other way here "
      f"(corr {CERTIN['cftc']['corr_vsmodel_vs_dealerz']:+.3f}).")
print(f"* Widened to 1 sigma the framework trades 4-23 times. On the "
      f"ANNUALISED clock it still fails: best net Sharpe on the panel "
      f"{_best_panel:+.4f}, best on the ENGINE {_best_eng:+.4f}, against "
      f"E[max SR | null] = {BAR:.4f} at {CFG.n_declared} declared trials over "
      f"{SPAN:.2f} tradeable years, and {len(_alive)} of {len(STATS)} cells "
      "clear it at any cost level.")
print(f"* On the PER-HOLD clock it is not nothing GROSS and is nothing NET. "
      f"{len(_cg)} of {len(PH)} cells clear their own per-hold bar gross -- "
      f"best {PH['perhold_sharpe_gross'].max():+.4f} against a bar of "
      f"{float(PH.loc[PH['perhold_sharpe_gross'].idxmax(), 'bar_perhold']):.4f} "
      f"on four trades -- and {len(_cn)} of {len(PH)} clear it net of 1x costs. "
      f"The best shared-sign-flip p on NET per-episode P&L in the whole block "
      f"is {PH['p_signflip_net'].min():.3f}. So the framework selects trades "
      "that are better than chance and cannot pay for them.")
print(f"* Costs ARE the marginal issue on the per-hold clock -- they take "
      f"{len(_cg)} cells to {len(_cn)} on their own. Break-even runs "
      f"{STATS['breakeven_bp'].abs().median():.2f} bp of gross DV01 traded at "
      "the median, against a declared 0.75 bp on the CA package alone before "
      "the fly's three legs are charged at all.")
print("* Citi's own fair value is not stable enough to hedge with on this "
      f"window: {int(FVT['b_sign_flips'].max())} sign reversals of b in "
      f"{int(FVT['n_refits'].max())} refits, and w2 pinned at a grid boundary "
      f"on {int(FVT['w2_at_a_boundary'].max())} of them.")
_pos = STATS.loc[STATS["net_0.0"] > 0, "carry_share"]
print(f"* What the trade IS, when it works, is short-convexity carry. The "
      f"always-short control is profitable on "
      f"{int((_raw['per_trade_usd'] > 0).sum())} of {len(_raw)} "
      f"(cell, structure) pairs with the signal switched OFF, up to "
      f"${_raw['per_trade_usd'].max():,.0f} per trade, and the declared carry "
      f"share of the {len(_pos)} cells with a positive gross runs "
      f"{_pos.median():.2f} at the median.")
print("=" * 78)
print("\nSTANDING CAVEAT")
print("-" * 78)
print("This is the fifth pass over the same CA panel. The nominal bar quoted "
      f"above is the honest one for 23 declared cells, but the STRUCTURE being "
      "tested was chosen after four prior searches over the same data, and no "
      "single-rule null bar can undo that. Block 4's verdict -- CA-vs-fly is "
      "dead as a systematic strategy -- stands, and this block adds the reason "
      "the published version of it does not rescue the idea: the entry "
      "conditions the note treats as one signal are, on SOFR, three different "
      "signals that rarely agree.")
