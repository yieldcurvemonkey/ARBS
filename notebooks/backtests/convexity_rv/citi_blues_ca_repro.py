# %% [markdown]
# # Citi, *Sell Blues convexity adjustments, hedged* — reproduced on today's curve
#
# **Sources.** Two Citi notes, both by Ruslan Bikbov / Jason Williams, and the
# first cites the second:
#
# * **`print (12).pdf`** — North America Rates Trade Idea, **09 February 2017**,
#   *"Sell Blues convexity adjustments, hedged"*. Figures 1-6 and the ticket.
# * **`print (18).pdf`** — US Rates Weekly, **13 January 2017**, *"Swearing in
#   huge expectations"*, §*Smart convexity sells*. Figures 16-22, including the
#   positioning regression the February note points back to. (Byte-identical to
#   `print (5/7/15).pdf`, md5 `29e884d6…`; extracted at
#   `docs/convexityrv/research/corpus2/g10-print-files.md` §4 and §8.)
#
# The note's own words:
#
# > We sell \$200k DV01 of Blues convexity adjustments, i.e. buy 2000 of H0-Z0
# > Eurodollar packs (2000 of each of the four contracts) and pay \$2bn on a
# > matched-maturity (3/18/20-3/17/21) CME cleared swap at 8.8bp of spread. The
# > fixed leg on the swap is reset at a quarterly frequency. We hedge the trade by
# > paying the belly of the 2s5s10s swap fly with notional weights of
# > \$147mm/-\$85.6mm/\$20.89mm (0.705/-1/0.465 DV01 weights) at -18.2bp in terms
# > of the level of the DV01-weighted fly. Pricing is as of 8am on 2/9/2017. We
# > set the target at +\$600k profit with the stop at -\$350k loss. The trade
# > carries positively by about \$380k over the next three months.
#
# > To build a more optimal hedging strategy, we regressed Blues CA on 2y, 5y and
# > 10y swap rates. Consistent with the intuition above, the CA are generally well
# > explained by these three rates, with the fitted value effectively being a
# > 2s5s10s fly with 0.705/-1/0.465 DV01 weights (Figure 6). The CA is about 3bp
# > (about 2 sigmas) wide to the fly … Our trade, specified above, is constructed
# > as a convergence trade between the Blues CA and the 2s5s10s fly, precisely as
# > illustrated in Figure 6.
#
# The six published figures, rebuilt on **USD SOFR, 2022-01-03 → 2026-08-21**:
#
# | | the note (ED, 2017) | here (SOFR, 2022-2026) |
# |---|---|---|
# | **1** | Blues CA vs the Ho-Lee model level | same, model calibrated to the swaption ATMF at the pack's own expiry |
# | **2** | CFTC positions in ED futures | CFTC TFF positions in SR3 |
# | **3** | 3m10y 25bp-out risk reversal | same node, same ±25bp absolute offsets |
# | **4** | subsequent 1m Δ10y by RR-change percentile | same table, this window |
# | **5** | 3y1y vol vs the scaled 2s5s10s fly | same, weights refitted |
# | **6** | Blues CA vs the scaled 2s5s10s fly — **the trade** | same, weights refitted |
# | **18** | positioning imbalance in ED futures | CFTC TFF in SR3 (≡ Fig 2) |
# | **19** | Δ(Blues CA − model) on Δ(dealer positioning) | same regression, same LHS |
# | **20** | the pack-by-pack convexity screen | same screen across the SOFR strip |
#
# **What this notebook is and is not.** It is a *reproduction of a published
# rule on current data*: it re-derives the note's own regressions, figures and
# ticket arithmetic and states what does and does not carry over. It is **not** a
# new backtest, it scores no cells, and it adds nothing to the trial count of the
# GV block (`docs/convexityrv/results/gv-ca-vs-imm-fly.md`) — whose verdict on
# CA-vs-fly as a *systematic* strategy stands unchanged.

# %%
import os
import sys
import warnings

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.append("../../..")
warnings.filterwarnings("ignore")

import datetime as dt
import json
import math
import pathlib
from dataclasses import dataclass
from typing import Tuple

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
from plotly.subplots import make_subplots

pio.renderers.default = "plotly_mimetype+notebook_connected"
pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 60)

from RVUtils.ConvexityRV import citi_fv as FV
from RVUtils.ConvexityRV import gv_universe as U
from RVUtils.ConvexityRV.holee import pack_ca_bp, pack_time_weight

print(f"pandas {pd.__version__}   numpy {np.__version__}")

# %% [markdown]
# ## CONFIG
#
# Every knob, and the note's own printed value beside it.

# %%
@dataclass(frozen=True)
class Config:
    #: Reproduction window. The note is Feb-2017 on Eurodollars; this is the
    #: window the brief asked for on SOFR.
    start: str = "2022-01-03"
    end: str = "2026-08-21"

    data_dir: str = "../../data/convexity_rv"

    # ---- the note's printed ticket, verbatim ----------------------------
    #: "$200k DV01 of Blues convexity adjustments"
    ca_dv01: float = 200_000.0
    #: "at 8.8bp of spread"
    entry_ca_bp: float = 8.8
    #: "at -18.2bp in terms of the level of the DV01-weighted fly"
    entry_fly_bp: float = -18.2
    #: Figure 6: CA_bp = 9.7 + 20.6 * (-0.705*r2 + r5 - 0.465*r10), rates PERCENT
    fig6_a: float = 9.7
    fig6_b: float = 20.6
    fig6_w2: float = 0.705
    fig6_w10: float = 0.465
    #: Figure 5: 3y1y_nvol = 59.7 + 60.5 * (-0.71*r2 + r5 - 0.18*r10)
    fig5_a: float = 59.7
    fig5_b: float = 60.5
    fig5_w2: float = 0.71
    fig5_w10: float = 0.18
    #: "notional weights of $147mm/-$85.6mm/$20.89mm"
    notional_2y_mm: float = 147.0
    notional_5y_mm: float = -85.6
    notional_10y_mm: float = 20.89
    #: "target at +$600k profit with the stop at -$350k loss"
    target_usd: float = 600_000.0
    stop_usd: float = -350_000.0
    #: "carries positively by about $380k over the next three months"
    carry_3m_usd: float = 380_000.0
    #: "rolldown on the curve of about +1.3bp over the next three months"
    ca_roll_3m_bp: float = 1.3
    #: "The 3m carry/roll on the short 2s5s10s fly is about +3.2bp over 3m"
    fly_carry_3m_bp: float = 3.2
    #: "roughly 4bp (about two sigmas) wide to the model"
    fig1_wide_bp: float = 4.0
    #: "The CA is about 3bp (about 2 sigmas) wide to the fly"
    fig6_wide_bp: float = 3.0
    #: "the correlation in levels being 90%"
    fig5_corr: float = 0.90

    # ---- print (18).pdf, "Swearing in huge expectations", 13 Jan 2017 -----
    #: Figure 19 fit: "y = 0.00x -0.15", "R2 = 0.32", y = chg in Blues CA vs
    #: model (bp), x = chg in dealer positioning. The axis is labelled "mm's"
    #: but a slope that prints as 0.00 at two decimals against an R2 of 0.32
    #: can only be a fit on RAW CONTRACTS -- see the Figure 19 cell.
    fig19_r2: float = 0.32
    fig19_intercept: float = -0.15
    #: "Monthly changes over 1/1/14 - 1/3/17"
    fig19_window: str = "2014-01-01..2017-01-03"
    #: The sibling print of the same regression ("Sell Eurodollar convexity in
    #: Blues", Fig 4, monthly 2013-01..2017-12) prints the slope explicitly.
    fig19_slope_bp_per_contract: float = 2e-06
    #: Figure 17: "The CA of the Blues pack ... is now about 4.6bp (almost 3
    #: sigmas) wide to the model, the widest dislocation since 2015"
    fig17_wide_bp: float = 4.6
    #: Figure 20, H0-Z0 row (close of 1/12/17): CA 10.02bp, VsModel 4.61bp,
    #: 3m Roll 1.30bp, Implied 125.5, Realized 95.1, Impl/Rlzd 1.3
    fig20_ca_bp: float = 10.02
    fig20_vs_model_bp: float = 4.61
    fig20_roll_bp: float = 1.30
    fig20_implied: float = 125.5
    fig20_realized: float = 95.1

    # ---- reproduction choices, each stated -------------------------------
    #: The note calibrates its model to CAP/FLOOR vols. This machine has the
    #: swaption cube, so the model level uses the ATMF normal vol at the pack's
    #: own mean expiry against a 1y tenor -- 4Yx1Y for Blues. A substitution,
    #: not the same surface, and it is named rather than assumed away.
    model_vol_col: str = "nvol_4y1y"
    #: Rolling window for the "sigmas wide" z-scores the note quotes.
    z_window_bd: int = 252
    #: Figure 4 groups 3m changes in the RR into historical percentiles and
    #: reports the SUBSEQUENT 1m change in the 10y rate.
    rr_lookback_m: int = 3
    rr_horizon_m: int = 1


CFG = Config()
DATA = pathlib.Path(CFG.data_dir)
P = pd.read_parquet(DATA / "p3_citi_repro.parquet")
P = P.loc[(P.index >= CFG.start) & (P.index <= CFG.end)]
META = json.loads((DATA / "p3_citi_repro_meta.json").read_text())
print(META["source_note"])
print(f"\n{len(P)} dates {P.index.min().date()}..{P.index.max().date()}, "
      f"{P.shape[1]} columns, min coverage {P.notna().mean().min():.4f}")
assert len(P) > 1_000 and P.notna().mean().min() > 0.99

# %% [markdown]
# ## Sign probe
#
# The conventions this reproduction can silently get wrong, asserted against
# live objects.

# %%
# 1. The fly combination is in PERCENT inside the regression and BP when quoted.
#    9.7 + 20.6*(-0.182) = 5.951bp against a CA of 8.8bp -> 2.85bp rich, and the
#    note says "about 3bp". That fixes the units at both ends at once.
_fit_at_entry = CFG.fig6_a + CFG.fig6_b * (CFG.entry_fly_bp / 100.0)
_rich_at_entry = CFG.entry_ca_bp - _fit_at_entry
print(f"fly quoted {CFG.entry_fly_bp:+.1f}bp = {CFG.entry_fly_bp / 100:+.4f}%  ->  "
      f"fitted CA {_fit_at_entry:.3f}bp  ->  richness "
      f"{_rich_at_entry:+.3f}bp vs the note's '{CFG.fig6_wide_bp:.0f}bp'")
assert abs(_rich_at_entry - CFG.fig6_wide_bp) < 0.25

# 2. beta is bp of CA per PERCENT of fly; /100 makes it bp per bp.
_beta_bp_per_bp = CFG.fig6_b / 100.0
print(f"beta {CFG.fig6_b} bp per percent = {_beta_bp_per_bp:.4f} bp per bp")
assert 0.15 < _beta_bp_per_bp < 0.30

# 3. SELLING the CA is BUYING the futures pack and PAYING the matched swap; the
#    hedge is PAYING the belly. Both legs are short the thing that is rich.
print("side: sell CA  = buy 2000 H0-Z0 packs + pay $2bn matched 3/18/20-3/17/21 "
      "swap (quarterly fixed);  hedge = PAY the 5y belly, receive the wings")

# 4. The fly weights do NOT sum to one, so this is not a pure curvature trade.
_net = CFG.fig6_w2 - 1.0 + CFG.fig6_w10
print(f"DV01 weights {CFG.fig6_w2}/-1/{CFG.fig6_w10}  ->  net "
      f"{_net:+.3f} per unit of belly DV01")
assert abs(_net) > 0.05, "a 3-rate regression does not constrain the weights"

# %% [markdown]
# ## Known-answer tie-out — the note against itself
#
# Before any SOFR data is touched: four numbers printed in the note must be
# mutually consistent under my reading of its conventions. If they are not, the
# reading is wrong and everything downstream is fitted to a fiction.

# %%
#: Promoted to ``RVUtils/ConvexityRV/citi_fv.py`` so the backtest and this
#: reproduction cannot drift.  The notebook keeps the name.
annuity = FV.annuity


_R = 2.0  # a flat ~2% USD curve, which is where 2017 sat
_A2, _A5, _A10 = (annuity(_R, y) for y in (2, 5, 10))

# (a) The printed NOTIONALS must reproduce the printed DV01 WEIGHTS.
_w2_implied = (CFG.notional_2y_mm * _A2) / (abs(CFG.notional_5y_mm) * _A5)
_w10_implied = (CFG.notional_10y_mm * _A10) / (abs(CFG.notional_5y_mm) * _A5)
print(f"(a) DV01 weights implied by the printed notionals at a flat {_R:.0f}% curve:"
      f"\n    2y {_w2_implied:.4f} vs printed {CFG.fig6_w2}   "
      f"({100 * (_w2_implied / CFG.fig6_w2 - 1):+.2f}%)"
      f"\n    10y {_w10_implied:.4f} vs printed {CFG.fig6_w10}   "
      f"({100 * (_w10_implied / CFG.fig6_w10 - 1):+.2f}%)")
assert abs(_w2_implied / CFG.fig6_w2 - 1) < 0.02
assert abs(_w10_implied / CFG.fig6_w10 - 1) < 0.02

# (b) The regression BETA must be the hedge ratio: belly DV01 = beta * CA DV01.
_belly_from_beta = _beta_bp_per_bp * CFG.ca_dv01
_belly_from_notional = abs(CFG.notional_5y_mm) * _A5 * 100.0
print(f"\n(b) belly DV01 from the Figure-6 beta   ${_belly_from_beta:,.0f}/bp"
      f"\n    belly DV01 from the printed notional ${_belly_from_notional:,.0f}/bp"
      f"   ({100 * (_belly_from_beta / _belly_from_notional - 1):+.1f}%)")
assert abs(_belly_from_beta / _belly_from_notional - 1) < 0.06

# (c) The printed CARRY must be the two printed roll numbers on those DV01s.
_carry = (CFG.ca_roll_3m_bp * CFG.ca_dv01
          + CFG.fly_carry_3m_bp * _belly_from_beta)
print(f"\n(c) carry = {CFG.ca_roll_3m_bp}bp x ${CFG.ca_dv01:,.0f} + "
      f"{CFG.fly_carry_3m_bp}bp x ${_belly_from_beta:,.0f} = ${_carry:,.0f}"
      f"\n    the note prints ${CFG.carry_3m_usd:,.0f}   "
      f"({100 * (_carry / CFG.carry_3m_usd - 1):+.1f}%)")
assert abs(_carry / CFG.carry_3m_usd - 1) < 0.08

# (d) The residual duration the fitted weights leave behind.
print(f"\n(d) the hedge is NOT DV01-neutral: {_net:+.3f} x "
      f"${_belly_from_beta:,.0f} = ${_net * _belly_from_beta:+,.0f}/bp of "
      f"outright duration on a ${CFG.ca_dv01:,.0f} DV01 book")
print("\nAll four tie out. The reading of the note's conventions is confirmed "
      "from the note's own printed numbers, before any market data is used.")

# %% [markdown]
# ### The one thing worth flagging in the original
#
# A regression of the CA on three separate rates does not constrain the weights
# to sum to one, and Citi's do not: `-0.705 + 1 - 0.465 = -0.17`. So the "fly"
# is **17% level by construction**, and the hedge inherits it as outright
# duration. That is not an error in the note — it is what "we regressed Blues CA
# on 2y, 5y and 10y swap rates" produces, and the note calls the result a fly
# because that is what it looks like. It matters for the reproduction because a
# fitted 3-rate hedge is partly a duration position, which is the same mechanism
# the GV block measured when a levels-β hedge *increased* the traded variance.

# %% [markdown]
# ## Figure 1 — Blues CA vs the model level
#
# The note: *"the convexity adjustments (CAs) are off their widest level [but]
# they remain significantly dislocated to the model-implied levels calibrated to
# cap/floor volatilities. The Blues pack CA looks especially attractive being
# roughly 4bp (about two sigmas) wide to the model."*

# %%
SIG = P[CFG.model_vol_col]
P["model_ca_bp"] = SIG ** 2 * P["blues_w"] / 2e4
P["vs_model_bp"] = P["blues_ca_bp"] - P["model_ca_bp"]
P["vs_model_z"] = ((P["vs_model_bp"]
                    - P["vs_model_bp"].rolling(CFG.z_window_bd, min_periods=126).mean())
                   / P["vs_model_bp"].rolling(CFG.z_window_bd, min_periods=126).std(ddof=1))

_f = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.66, 0.34],
                   vertical_spacing=0.06,
                   subplot_titles=("Figure 1 — Blues pack convexity adjustment "
                                   "vs the Ho-Lee model level (SOFR)",
                                   "CA − model, bp"))
_f.add_trace(go.Scatter(x=P.index, y=P["blues_ca_bp"], name="Blues Pack Cvx Adj"),
             row=1, col=1)
_f.add_trace(go.Scatter(x=P.index, y=P["model_ca_bp"], name="Model Level"),
             row=1, col=1)
_f.add_trace(go.Scatter(x=P.index, y=P["vs_model_bp"], name="CA − model",
                        line=dict(color="#888")), row=2, col=1)
_f.add_hline(y=0.0, line_dash="dot", row=2, col=1)
_f.update_yaxes(title_text="bp", row=1, col=1)
_f.update_yaxes(title_text="bp", row=2, col=1)
_f.update_layout(height=620, legend=dict(orientation="h", y=1.06))
_f.show()

_last = P.index[-1]
print(f"as of {_last.date()}:  Blues CA {P['blues_ca_bp'].iloc[-1]:.2f}bp   "
      f"model {P['model_ca_bp'].iloc[-1]:.2f}bp   "
      f"wide by {P['vs_model_bp'].iloc[-1]:+.2f}bp "
      f"({P['vs_model_z'].iloc[-1]:+.2f} sigma)")
print(f"window mean CA − model {P['vs_model_bp'].mean():+.2f}bp, "
      f"sd {P['vs_model_bp'].std(ddof=1):.2f}bp, "
      f"max {P['vs_model_bp'].max():+.2f}bp on "
      f"{P['vs_model_bp'].idxmax().date()}")
print(f"\nthe note's Feb-2017 reading was '{CFG.fig1_wide_bp:.0f}bp (about two "
      "sigmas) wide'. On SOFR the CA is wide to this model on "
      f"{100 * (P['vs_model_bp'] > 0).mean():.0f}% of days -- a standing "
      "pedestal, not an episodic dislocation. The model here is calibrated to "
      "the SWAPTION ATMF, not to Citi's cap/floor surface, and a level "
      "disagreement of a basis point or two is exactly where a different vol "
      "surface lands.")

# %% [markdown]
# ## Figure 2 — positioning
#
# The note: *"Last year both asset managers and leveraged funds increased their
# net short positions in ED futures … Dealers, who were on the other side of
# these trades, had to hedge their long ED positions by paying in swaps and
# therefore were structurally short convexity adjustments."*

# %%
_f = go.Figure()
for _c, _n in (("dealer_net", "Dealers"), ("am_net", "Asset Managers"),
               ("lev_net", "Leveraged Funds")):
    if _c in P.columns:
        _f.add_trace(go.Scatter(x=P.index, y=P[_c] / 1e6, name=_n))
_f.add_hline(y=0.0, line_dash="dot")
_f.update_layout(title="Figure 2 — CFTC TFF net positions in SR3 futures",
                 yaxis_title="mn contracts", height=430,
                 legend=dict(orientation="h", y=1.08))
_f.show()

_pos = P[["dealer_net", "am_net", "lev_net"]].iloc[-1] / 1e6
print(f"as of {_last.date()} (mn contracts): dealers {_pos['dealer_net']:+.2f}, "
      f"asset managers {_pos['am_net']:+.2f}, leveraged {_pos['lev_net']:+.2f}")
_c_da = P["dealer_net"].corr(P["am_net"] + P["lev_net"])
print(f"corr(dealer net, AM + leveraged net) in levels: {_c_da:+.4f}  -- the "
      "note's mechanism is that dealers take the other side, and that is what "
      "a strongly negative number here means.")
print("\nProvenance: CFTC TFF for SOFR-3M, weekly, lagged 3 business days to "
      "publication. The report measures Tuesday and publishes Friday 15:30 ET, "
      "and the raw file carries no release stamp.")

# %% [markdown]
# ## Figure 18 — positioning imbalance in ED futures
#
# `print (18).pdf`, *Swearing in huge expectations*, 13 Jan 2017. This is the
# same chart the February trade idea reprints as its Figure 2, so the panel
# above **is** Figure 18 on SOFR: dealers, asset managers and leveraged funds,
# net, in millions of contracts, from the CFTC's Traders in Financial Futures
# report.
#
# The note's claim: *"Last year both asset managers and leveraged funds
# increased their net short positions in ED futures … Dealers, who were on the
# other side of these trades, had to hedge their long ED positions by paying in
# swaps and therefore were structurally short convexity adjustments. Long
# dealers' positions in futures reached historically high levels pre-election,
# which should have put pressure on dealers' risk limits and therefore
# translated into wider CAs."*

# %%
_imb = P[["dealer_net", "am_net", "lev_net"]].dropna()
_client = _imb["am_net"] + _imb["lev_net"]
print("Figure 18, on SOFR 2022-2026 (mn contracts):")
print(f"  dealers      min {_imb['dealer_net'].min()/1e6:+.2f}  "
      f"max {_imb['dealer_net'].max()/1e6:+.2f}  "
      f"last {_imb['dealer_net'].iloc[-1]/1e6:+.2f}")
print(f"  asset mgrs   min {_imb['am_net'].min()/1e6:+.2f}  "
      f"max {_imb['am_net'].max()/1e6:+.2f}  "
      f"last {_imb['am_net'].iloc[-1]/1e6:+.2f}")
print(f"  leveraged    min {_imb['lev_net'].min()/1e6:+.2f}  "
      f"max {_imb['lev_net'].max()/1e6:+.2f}  "
      f"last {_imb['lev_net'].iloc[-1]/1e6:+.2f}")
print(f"\ncorr(dealer, AM+leveraged) in LEVELS  {_imb['dealer_net'].corr(_client):+.4f}")
print(f"corr(dealer, AM+leveraged) in CHANGES {_imb['dealer_net'].diff().corr(_client.diff()):+.4f}")
print("\nThe note's premise -- dealers take the other side -- is the strongly "
      "negative number above. It is a near-identity, not a finding: the four "
      "TFF categories plus non-reportables sum to zero by construction, so "
      "dealers being short what clients are long is close to arithmetic. What "
      "the note actually asserts, and Figure 19 tests, is the step AFTER that: "
      "that the SIZE of the dealer position moves the convexity adjustment.")

# %% [markdown]
# ## Figure 19 — does dealer positioning widen the convexity adjustment?
#
# > *"Figure 19 demonstrates there is indeed a significant correlation between
# > dealers' futures positions and the dislocation of CAs on the model (in
# > monthly changes)."*
#
# The published fit: **y = 0.00x − 0.15, R² = 0.32**, over *"monthly changes,
# 1/1/14 – 1/3/17"*, with **y = chg in Blues CA vs model (bp)** and
# **x = chg in dealer positioning (mm's)**.
#
# **The left-hand side is `Δ(CA − model)`, not `ΔCA`.** That distinction is the
# whole test: the model already absorbs the vol channel, so the residual is what
# positioning is supposed to explain. An earlier pass in this package regressed
# on the raw CA level, found nothing, and was measuring a different thing.
#
# **On the printed slope.** A slope that displays as `0.00` at two decimals
# cannot produce R² = 0.32 against an x-axis that spans ±1 — so the fit is on
# **raw contracts** while the axis is labelled in millions. The sibling print of
# the same regression (*Sell Eurodollar convexity in Blues*, Fig 4) states it
# explicitly: **2e−06 bp per contract**, i.e. ~2 bp per million contracts. Both
# readings are reported below so the units are unambiguous.

# %%
def hac_ols(y: pd.Series, x: pd.Series, lags: int = 4) -> dict:
    """OLS with Newey-West standard errors. Monthly changes in positioning are
    persistent, and an OLS t-stat on overlapping-ish macro series flatters."""
    j = pd.concat([y.rename("y"), x.rename("x")], axis=1).dropna()
    n = len(j)
    X = np.column_stack([np.ones(n), j["x"].to_numpy()])
    b, *_ = np.linalg.lstsq(X, j["y"].to_numpy(), rcond=None)
    e = j["y"].to_numpy() - X @ b
    r2 = 1.0 - e.var(ddof=0) / j["y"].to_numpy().var(ddof=0)
    XtX_inv = np.linalg.pinv(X.T @ X)
    S = (X * e[:, None]).T @ (X * e[:, None])
    for L in range(1, lags + 1):
        w = 1.0 - L / (lags + 1.0)
        G = (X[L:] * e[L:, None]).T @ (X[:-L] * e[:-L, None])
        S += w * (G + G.T)
    V = XtX_inv @ S @ XtX_inv
    se = float(np.sqrt(max(V[1, 1], 0.0)))
    return {"n": n, "intercept": float(b[0]), "slope": float(b[1]),
            "r2": float(r2), "se": se,
            "t_hac": float(b[1] / se) if se > 0 else float("nan")}


_rows = []
for _lab in ("WHITES", "REDS", "GREENS", "BLUES", "GOLDS"):
    _l = _lab.lower()
    _model = P[f"nvol_{ {'WHITES':'1y1y','REDS':'2y1y','GREENS':'3y1y','BLUES':'4y1y','GOLDS':'5y1y'}[_lab] }"] ** 2 * P[f"{_l}_w"] / 2e4
    _vs = P[f"{_l}_ca_bp"] - _model
    _m = pd.concat([_vs.rename("vs"), P["dealer_net"].rename("pos")],
                   axis=1).resample("ME").last().diff().dropna()
    _r = hac_ols(_m["vs"], _m["pos"])
    _rows.append({"pack": _lab, "n_months": _r["n"],
                  "slope_bp_per_contract": _r["slope"],
                  "slope_bp_per_mn": _r["slope"] * 1e6,
                  "intercept_bp": _r["intercept"], "r2": _r["r2"],
                  "t_hac": _r["t_hac"],
                  "sign_agrees": _r["slope"] > 0})
FIG19 = pd.DataFrame(_rows).set_index("pack")
print(FIG19.round(6).to_string())
print(f"\nCiti Figure 19 (ED, monthly {CFG.fig19_window}): "
      f"intercept {CFG.fig19_intercept}, R2 {CFG.fig19_r2}, slope "
      f"{CFG.fig19_slope_bp_per_contract:.0e} bp/contract "
      f"= {CFG.fig19_slope_bp_per_contract * 1e6:.1f} bp per mn contracts")
_b = FIG19.loc["BLUES"]
print(f"SOFR Blues        (monthly, 2022-2026):        "
      f"intercept {_b['intercept_bp']:+.2f}, R2 {_b['r2']:.3f}, slope "
      f"{_b['slope_bp_per_contract']:.2e} bp/contract "
      f"= {_b['slope_bp_per_mn']:+.2f} bp per mn contracts, HAC t "
      f"{_b['t_hac']:+.2f}")

# %%
_l = "blues"
_model_b = P[CFG.model_vol_col] ** 2 * P[f"{_l}_w"] / 2e4
_vs_b = P[f"{_l}_ca_bp"] - _model_b
_m = pd.concat([_vs_b.rename("vs"), P["dealer_net"].rename("pos")],
               axis=1).resample("ME").last().diff().dropna()
_fit = hac_ols(_m["vs"], _m["pos"])
_xs = np.linspace(_m["pos"].min(), _m["pos"].max(), 50)

_f = go.Figure()
_f.add_trace(go.Scatter(x=_m["pos"] / 1e6, y=_m["vs"], mode="markers",
                        name="monthly changes",
                        marker=dict(size=8, color=_m.index.year,
                                    colorscale="Viridis",
                                    colorbar=dict(title="year"))))
_f.add_trace(go.Scatter(x=_xs / 1e6, y=_fit["intercept"] + _fit["slope"] * _xs,
                        mode="lines", name=f"y = {_fit['slope'] * 1e6:.2f}x "
                                           f"{_fit['intercept']:+.2f}   "
                                           f"R² = {_fit['r2']:.2f}",
                        line=dict(color="black", dash="dash")))
_f.update_layout(
    title="Figure 19 — Δ(Blues CA − model) vs Δ(dealer positioning), "
          "monthly, SOFR 2022-2026",
    xaxis_title="Chg in dealer positioning, mm's",
    yaxis_title="chg in Blues CA vs model, bp",
    height=520, legend=dict(orientation="h", y=1.08))
_f.show()

print(f"Citi (ED, 2014-2017):  R² {CFG.fig19_r2:.2f}, slope "
      f"{CFG.fig19_slope_bp_per_contract * 1e6:+.1f} bp/mn, intercept "
      f"{CFG.fig19_intercept:+.2f}")
print(f"Here (SOFR, 2022-2026): R² {_fit['r2']:.2f}, slope "
      f"{_fit['slope'] * 1e6:+.2f} bp/mn, intercept {_fit['intercept']:+.2f}, "
      f"HAC t {_fit['t_hac']:+.2f} on n = {_fit['n']} months")
print(f"\nBlock 3 ran the sibling version of this regression on SOFR 2021-2026 "
      f"and reported BLUES slope +5.28e-07 bp/contract, t +2.59, R² 0.124 -- "
      "the only colour of four that reproduced. The number above is the same "
      "test on a slightly different window and a swaption-calibrated model.")
print("\nRead the SIGN first: the note's mechanism is that a LARGER dealer long "
      "widens the adjustment, so a positive slope is the claim. Then read the "
      f"R²: at n = {_fit['n']} monthly observations this is a weak-evidence "
      "regression whichever way it comes out, and it is a statement about a "
      "MECHANISM, not a tradable signal -- the GV block measured the "
      "positioning overlay keeping 0-1 of 6-9 episodes.")

# %% [markdown]
# ## Figure 3 — the 3m10y 25bp-out risk reversal
#
# The note: *"the flattening of short-dated implied skews observed since December
# may indicate a build-up of short positions … Since then skews have continued to
# flatten suggesting still stretched shorts."*
#
# The vol store carries **exactly** the ±25bp absolute strike offsets this
# figure uses (`skew_measure = NORMALABSOLUTE`), so this is the note's own
# quantity rather than an interpolation off a smile model.

# %%
_f = make_subplots(specs=[[{"secondary_y": True}]])
_f.add_trace(go.Scatter(x=P.index, y=P["rr_3m10y_bp"],
                        name="3m10y 25bp-out risk reversal"), secondary_y=False)
_f.add_trace(go.Scatter(x=P.index, y=P["atm_3m10y_bp"], name="3m10y ATM nvol",
                        line=dict(color="#bbb")), secondary_y=True)
_f.add_hline(y=0.0, line_dash="dot")
_f.update_yaxes(title_text="normals (vol(+25) − vol(−25))", secondary_y=False)
_f.update_yaxes(title_text="ATM normals", secondary_y=True)
_f.update_layout(title="Figure 3 — 3m10y 25bp-out risk reversal, SOFR",
                 height=430, legend=dict(orientation="h", y=1.08))
_f.show()
print(f"as of {_last.date()}: RR {P['rr_3m10y_bp'].iloc[-1]:+.2f} normals, "
      f"ATM {P['atm_3m10y_bp'].iloc[-1]:.1f}")
print(f"window: mean {P['rr_3m10y_bp'].mean():+.2f}, "
      f"sd {P['rr_3m10y_bp'].std(ddof=1):.2f}, "
      f"min {P['rr_3m10y_bp'].min():+.2f}, max {P['rr_3m10y_bp'].max():+.2f}; "
      f"positive on {100 * (P['rr_3m10y_bp'] > 0).mean():.0f}% of days")

# %% [markdown]
# ## Figure 4 — does a flattening skew predict a rally?
#
# The note's table, its own construction: *"We group 3m changes in the 3m10y
# 25-out risk reversal into historical percentiles. We then compute the average
# and median changes in the 10y rate and frequency of positive changes over a
# subsequent one month horizon. Monthly data from Jan 2006 to Nov 2016."*
#
# Its published result:
#
# | Δ3m in 3m10y RR | avg, bp | median, bp | frequency > 0, % |
# |---|---:|---:|---:|
# | <25 | −11.5 | −5.0 | 36 |
# | 25-50 | −2.1 | −1.1 | 48 |
# | 50-75 | 0.2 | −4.2 | 45 |
# | >75 | 8.8 | 11.1 | 69 |

# %%
_m = P[["rr_3m10y_bp", "r10y_pct"]].resample("ME").last().dropna()
_m["d_rr_3m"] = _m["rr_3m10y_bp"].diff(CFG.rr_lookback_m)
_m["fwd_d10y_bp"] = _m["r10y_pct"].shift(-CFG.rr_horizon_m).sub(
    _m["r10y_pct"]) * 100.0
_g = _m.dropna(subset=["d_rr_3m", "fwd_d10y_bp"]).copy()
_q = _g["d_rr_3m"].rank(pct=True)
_g["bucket"] = pd.cut(_q, [0, .25, .50, .75, 1.0],
                      labels=["<25", "25-50", "50-75", ">75"])
FIG4 = _g.groupby("bucket", observed=True)["fwd_d10y_bp"].agg(
    n="size", avg_bp="mean", median_bp="median",
    freq_gt0_pct=lambda s: 100.0 * (s > 0).mean()).round(2)
print(FIG4.to_string())
print(f"\nn = {len(_g)} monthly observations against the note's ~130 "
      "(Jan-2006..Nov-2016). At this sample size the monotone ramp the note "
      "reports is not something this window can confirm or deny, and the "
      "reproduction says so rather than reading a pattern into four buckets of "
      f"{len(_g) // 4}.")

# %% [markdown]
# ## Figures 5 and 6 — Citi's *method*, rebalanced on the IMM dates
#
# The note's method, in its own words:
#
# > *"To build a more optimal hedging strategy, we regressed Blues CA on 2y, 5y
# > and 10y swap rates. Consistent with the intuition above, the CA are generally
# > well explained by these three rates, **with the fitted value effectively
# > being a 2s5s10s fly with 0.705/-1/0.465 DV01 weights**."*
#
# So the weights are an **output** of the regression, not an input. The point of
# the reproduction is the method, not the 2017 numbers — those were fitted to
# Eurodollars on a different curve and there is no reason for SOFR 2022-2026 to
# return them.
#
# **The weights are refitted on every quarterly SR3 IMM date**, on a trailing
# window ending strictly before the roll, and stay in force until the next roll.
# Two reasons for that boundary rather than a calendar quarter: the CA structure
# itself switches contracts there, so the hedge should be re-struck with it; and
# a constant-rank CA carries a **sawtooth** — it decays within the quarter at
# `dCA/dt = −σ²·mean(T1)/1e4` and jumps back up at the roll — so a window that
# ends at a roll never straddles a contract switch. It makes the richness
# genuinely out-of-sample and it makes the drift in the weights — the
# mis-weighting the method is there to find — visible instead of averaged away.
#
# Three fits are carried side by side, because the third one misbehaves and
# saying so is the point:
#
# 1. **`free`** — Citi's own unconstrained 3-rate regression, renormalised to
#    `a + b·(−w₂·r2 + r5 − w₁₀·r10)`.
# 2. **`fly`** — the same fit with the weights constrained to sum to one, so the
#    fitted object is guaranteed to be a real butterfly. One shape parameter.
# 3. **`citi`** — Citi's published 0.705 / −1 / 0.465 held fixed, level and scale
#    refitted. A reference line, not the reproduction.

# %%
_RC = P[["r2y_pct", "r5y_pct", "r10y_pct"]]
print("correlation of the three spot rates, SOFR 2022-2026:")
print(_RC.corr().round(4).to_string())
_cond = float(np.linalg.cond(np.column_stack([np.ones(len(_RC)), _RC.to_numpy()])))
print(f"\ncondition number of [1, r2, r5, r10]: {_cond:,.0f}")
print("The three rates are nearly collinear on this window, so the individual "
      "coefficients are weakly identified even where the JOINT fit is good -- "
      "and the normalisation w = -beta/beta5 then divides by a small, noisy "
      "number. That is what the `free` path below shows.")


#: Fly START conventions, the combination, and the three fits all now live in
#: ``RVUtils/ConvexityRV/citi_fv.py``.  A backtest cannot import from a
#: notebook, so the machinery was promoted to a module with its own test suite
#: and its own mutation harness; this notebook imports it so the two can never
#: drift.  ``_p4_tieout_repro.py`` pins the module against the numbers this
#: notebook printed when the machinery still lived in these cells.
SPOT_COLS = FV.SPOT_COLS
FLY_STARTS = FV.FLY_STARTS


def _combo(p: pd.DataFrame, w2: float, w10: float,
           cols: Tuple[str, str, str] = SPOT_COLS) -> pd.Series:
    return FV.fly_combo(p, w2, w10, cols)


def _fit_on(y: pd.Series, p: pd.DataFrame, kind: str,
            cols: Tuple[str, str, str] = SPOT_COLS) -> dict:
    """One fit on one window. `kind` in {'free', 'fly', 'citi'}."""
    fit = FV.fit_fair_value(y, p, kind, cols, fixed_w2=CFG.fig6_w2,
                            fixed_w10=CFG.fig6_w10)
    return fit.as_dict() if fit is not None else {}


IMM_ROLLS = U.ca_roll_dates(P.index)
print(f"{len(IMM_ROLLS)} quarterly SR3 IMM rolls in the window: "
      f"{IMM_ROLLS[0].date()} .. {IMM_ROLLS[-1].date()}")
print("The CA rank map advances ON the IMM date; an IMM_k swap leg advances the "
      "business day BEFORE. Each fit therefore ends at the last mark strictly "
      "before the roll, and its weights come into force ON the roll -- so no "
      "window straddles a contract switch and no fit sees the jump it is about "
      "to be applied across.")

# The sawtooth, made explicit. A constant-rank CA decays within the quarter at
# dCA/dt = -sigma^2*mean(T1)/1e4 and jumps back up at the roll; over 2021-2026
# a quarter of that decay equals the measured jump to within 2-11%. Left in, it
# lands in the regression residual as "where are we in the quarter".
_theta_yr = -(P[CFG.model_vol_col] ** 2) * P["blues_t1mean"] / 1e4
_since = pd.Series(0.0, index=P.index)
_bd = 0
_last_roll = None
for _d in P.index:
    if _d in set(IMM_ROLLS):
        _bd, _last_roll = 0, _d
    _since.loc[_d] = _bd
    _bd += 1
P["theta_bp_per_year"] = _theta_yr
P["bd_since_roll"] = _since
P["ca_deseasoned_bp"] = P["blues_ca_bp"] - _theta_yr * (_since / 252.0)
print(f"\nBlues theta {_theta_yr.mean():.3f} bp/yr = "
      f"{_theta_yr.mean() / 12:.3f} bp/month; accrued decay reaches "
      f"{(_theta_yr * _since / 252.0).min():.2f} bp by the end of a quarter")


def imm_refit(y: pd.Series, p: pd.DataFrame, kind: str, window_bd: int,
              cols: Tuple[str, str, str] = SPOT_COLS
              ) -> Tuple[pd.DataFrame, pd.Series]:
    """Refit at every quarterly IMM roll; apply until the next one.

    Causal by construction: the parameters in force on date t were estimated on
    marks ending strictly before the roll that put them in force.  Promoted to
    ``citi_fv.imm_refit``; this is the same call.
    """
    return FV.imm_refit(y, p, kind, window_bd, cols, fixed_w2=CFG.fig6_w2,
                        fixed_w10=CFG.fig6_w10)


# %% [markdown]
# ### The weight path — "finding the mis-weightings for the fly"
#
# Refit window declared at **504 business days (two years)**; 252 and 756 are
# reported beside it so the choice is visible rather than tuned.

# %%
FIT_WINDOW_BD = 504
W6, FIT6 = imm_refit(P["blues_ca_bp"], P, "free", FIT_WINDOW_BD)
W6D, FIT6D = imm_refit(P["ca_deseasoned_bp"], P, "fly", FIT_WINDOW_BD)
W6F, FIT6F = imm_refit(P["blues_ca_bp"], P, "fly", FIT_WINDOW_BD)
W6C, FIT6C = imm_refit(P["blues_ca_bp"], P, "citi", FIT_WINDOW_BD)
print(f"{len(W6)} refits at IMM rolls, {W6.index[0].date()}.."
      f"{W6.index[-1].date()}, each in force until the next roll\n")
print("UNCONSTRAINED (Citi's own specification):")
print(W6[["in_force_from", "w2", "w10", "a", "b", "r2", "n"]].round(3).to_string())
print(f"\n  w2  median {W6['w2'].median():+.3f}  range "
      f"[{W6['w2'].min():+.3f}, {W6['w2'].max():+.3f}]  sign flips "
      f"{int((np.sign(W6['w2']).diff().abs() > 0).sum())}")
print(f"  w10 median {W6['w10'].median():+.3f}  range "
      f"[{W6['w10'].min():+.3f}, {W6['w10'].max():+.3f}]  sign flips "
      f"{int((np.sign(W6['w10']).diff().abs() > 0).sum())}")
print(f"  weights sum to one on 0 of {len(W6)} refits "
      f"(median sum {(-W6['w2'] + 1 - W6['w10']).median():+.3f})")

print("\nFLY-CONSTRAINED (w2 + w10 = 1, so it is genuinely a butterfly):")
print(W6F[["in_force_from", "w2", "w10", "a", "b", "r2"]].round(3).to_string())
_edge = int(((W6F["w2"] <= 0.01) | (W6F["w2"] >= 0.99)).sum())
print(f"\n  w2 median {W6F['w2'].median():.3f}  range "
      f"[{W6F['w2'].min():.3f}, {W6F['w2'].max():.3f}]  -- "
      f"Citi's published w2 was {CFG.fig6_w2}")
print(f"  b (scale) median {W6F['b'].median():+.2f}, range "
      f"[{W6F['b'].min():+.2f}, {W6F['b'].max():+.2f}], sign flips "
      f"{int((np.sign(W6F['b']).diff().abs() > 0).sum())}")
print(f"  w2 sits AT a boundary (0 or 1) on {_edge} of {len(W6F)} refits")
_flip = W6F.index[int(np.argmax(np.sign(W6F["b"]).diff().abs().fillna(0).to_numpy()))]
print("\nThe constrained fit is well behaved -- w2 is INTERIOR on "
      f"{len(W6F) - _edge} of {len(W6F)} refits, so this is a real butterfly "
      "and not a curve wearing the label. What it does instead is worse:")
print(f"\n  ONE REGIME CHANGE, at the {pd.Timestamp(_flip).date()} refit, in "
      "which two things happen together --")
print(f"    * w2 jumps from {W6F['w2'].iloc[0]:.2f} (a 10y-heavy fly, nearly "
      f"5s10s) to {W6F['w2'].iloc[-1]:.2f} (a 2y-heavy fly, nearly 2s5s): the "
      "weight moves from one wing to the other;")
print(f"    * the scale b flips sign, from {W6F['b'].iloc[0]:+.1f} to "
      f"{W6F['b'].iloc[-1]:+.1f}. Before it, a higher fly meant a higher CA; "
      "after it, the opposite.")
print("\n  That is not drift a rebalance smooths out -- it is the relationship "
      "reversing. It lands in mid-2023, next to this window's widest CA "
      f"dislocation (+{P['vs_model_bp'].max():.2f} bp on "
      f"{P['vs_model_bp'].idxmax().date()}). A hedge ratio whose SIGN changes "
      "inside its own sample is the same defect the GV block measured on 20 of "
      "21 (structure x leg) pairs, arriving here through Citi's own method.")

# %%
_f = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.09,
                   subplot_titles=("Unconstrained weights, refit quarterly "
                                   "(Citi's own specification)",
                                   "Fly-constrained weights (w2 + w10 = 1)"))
for _c, _n in (("w2", "w2 (2y wing)"), ("w10", "w10 (10y wing)")):
    _f.add_trace(go.Scatter(x=W6["in_force_from"], y=W6[_c], name=_n,
                            mode="lines+markers"), row=1, col=1)
    _f.add_trace(go.Scatter(x=W6F["in_force_from"], y=W6F[_c],
                            name=f"{_n}, constrained", mode="lines+markers",
                            showlegend=True), row=2, col=1)
_f.add_hline(y=CFG.fig6_w2, line_dash="dot", row=2, col=1,
             annotation_text=f"Citi w2 {CFG.fig6_w2}")
_f.update_layout(height=620, title="The mis-weighting, quarter by quarter",
                 legend=dict(orientation="h", y=1.07))
_f.show()
print("The unconstrained path is the note's own specification and it does not "
      "stay inside butterfly territory on this curve; the constrained path is "
      "well-behaved in its WEIGHTS and is what the ticket below uses -- but it "
      "carries the sign change described above, which no amount of "
      "rebalancing repairs.")

# %% [markdown]
# ### Does the IMM-roll rebalance matter?
#
# The direct test of it: residual standard deviation of the **out-of-sample**
# richness under each scheme, over the common dates.

# %%
_STATIC = _fit_on(P["blues_ca_bp"], P, "fly")
_static_fitted = _STATIC["a"] + _STATIC["b"] * _combo(P, _STATIC["w2"],
                                                      _STATIC["w10"])
_cmp = pd.DataFrame({
    "IMM refit, free": P["blues_ca_bp"] - FIT6,
    "IMM refit, fly-constrained": P["blues_ca_bp"] - FIT6F,
    "IMM refit, Citi weights": P["blues_ca_bp"] - FIT6C,
    "IMM refit, fly-constrained, theta-adjusted":
        P["ca_deseasoned_bp"] - FIT6D,
    "static fly, full sample (in-sample)": P["blues_ca_bp"] - _static_fitted,
}).dropna()
_tab = pd.DataFrame({
    "resid_sd_bp": _cmp.std(ddof=1),
    "resid_mean_bp": _cmp.mean(),
    "resid_mae_bp": _cmp.abs().mean(),
    "oos": [True, True, True, True, False],
}).round(3)
print(f"over {len(_cmp)} common dates:\n")
print(_tab.to_string())
_q = float(_cmp["IMM refit, fly-constrained"].std(ddof=1))
_s = float(_cmp["static fly, full sample (in-sample)"].std(ddof=1))
_c = float(_cmp["IMM refit, Citi weights"].std(ddof=1))
_qm = float(_cmp["IMM refit, fly-constrained"].abs().mean())
_cm = float(_cmp["IMM refit, Citi weights"].abs().mean())
print("\nRead this table carefully, because it does not say what one would "
      "expect it to say.")
print(f"\n* By residual SD the best scheme is Citi's published 2017 Eurodollar "
      f"weights held COMPLETELY FIXED ({_c:.3f} bp), ahead of the IMM-roll "
      f"fly-constrained refit ({_q:.3f} bp) and of a static fly fitted on the "
      f"whole window with hindsight ({_s:.3f} bp). Re-estimating the weights "
      "does not beat just using Citi's number.")
print(f"* By MEAN ABSOLUTE residual the ordering reverses: the refit is "
      f"{_qm:.3f} bp against {_cm:.3f} bp for the fixed weights. The refit is "
      "better on a typical day and worse in the tails, which is what "
      "re-estimating on a trailing window does when the relationship breaks.")
print(f"* The fixed-weight scheme carries much the largest mean residual "
      f"({_cmp['IMM refit, Citi weights'].mean():+.3f} bp against "
      f"{_cmp['IMM refit, fly-constrained'].mean():+.3f}): it is biased, and "
      "the refit removes most of that bias.")
print(f"* Subtracting the CA's own theta accrual makes it slightly WORSE "
      f"({_cmp['IMM refit, fly-constrained, theta-adjusted'].std(ddof=1):.3f} "
      "bp), so on this window the intra-quarter sawtooth is not the part the "
      "regression is failing to explain.")
print("\nThe honest summary: rebalancing changes WHERE the error sits rather "
      "than how big it is -- it removes bias and typical error and gives back "
      "tail error. That is worth knowing before sizing anything off this "
      "residual, and it is not the result I expected to write.")

# %% [markdown]
# ### Figure 5 — 3y1y implied vol vs the scaled fly, same method

# %%
W5, FIT5 = imm_refit(P["nvol_3y1y"], P, "fly", FIT_WINDOW_BD)
_j5 = pd.concat([P["nvol_3y1y"].rename("y"), FIT5.rename("f")], axis=1).dropna()
print(f"fly-constrained, refit quarterly: w2 median {W5['w2'].median():.3f} "
      f"[{W5['w2'].min():.3f}, {W5['w2'].max():.3f}], "
      f"b median {W5['b'].median():.1f}")
print(f"Citi 2017 (ED): {CFG.fig5_a} + {CFG.fig5_b} * "
      f"(-{CFG.fig5_w2}*r2 + r5 - {CFG.fig5_w10}*r10), level corr "
      f"{CFG.fig5_corr:.2f}")
print(f"\nout-of-sample level correlation here: {_j5['y'].corr(_j5['f']):+.4f} "
      f"on {len(_j5)} dates")

_f = go.Figure()
_f.add_trace(go.Scatter(x=P.index, y=P["nvol_3y1y"], name="3y1y implied vol"))
_f.add_trace(go.Scatter(x=FIT5.dropna().index, y=FIT5.dropna(),
                        name="scaled 2s5s10s fly, IMM-roll refit (OOS)"))
_f.update_layout(title="Figure 5 — 3y1y implied vol vs the scaled 2s5s10s fly, "
                       "SOFR 2022-2026, weights rebalanced at the IMM rolls",
                 yaxis_title="normals", height=430,
                 legend=dict(orientation="h", y=1.10))
_f.show()

# %% [markdown]
# ### Figure 6 — Blues CA vs the scaled fly. **This is the trade.**
#
# > *"Our trade … is constructed as a convergence trade between the Blues CA and
# > the 2s5s10s fly, precisely as illustrated in Figure 6."*
#
# The fitted line below is **out of sample**: every point uses weights, level and
# scale estimated on data ending at the previous quarter end.

# %%
F6 = W6F.iloc[-1].to_dict()
P["fitted_ca_bp"] = FIT6F
P["rich_bp"] = P["blues_ca_bp"] - P["fitted_ca_bp"]
P["rich_z"] = ((P["rich_bp"] - P["rich_bp"].rolling(CFG.z_window_bd, min_periods=126).mean())
               / P["rich_bp"].rolling(CFG.z_window_bd, min_periods=126).std(ddof=1))
P["fly_bp"] = _combo(P, F6["w2"], F6["w10"]) * 100.0

_f = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.64, 0.36],
                   vertical_spacing=0.07,
                   subplot_titles=("Figure 6 — Blues CA vs the scaled 2s5s10s "
                                   "fly, refit at each IMM roll (SOFR); the trade is "
                                   "the gap",
                                   "CA − fitted, bp (out of sample)"))
_f.add_trace(go.Scatter(x=P.index, y=P["blues_ca_bp"], name="Blues Cvx Adj"),
             row=1, col=1)
_f.add_trace(go.Scatter(x=P["fitted_ca_bp"].dropna().index,
                        y=P["fitted_ca_bp"].dropna(),
                        name="scaled 2s5s10s fly, weights refit at each IMM roll"),
             row=1, col=1)
_f.add_trace(go.Scatter(x=P.index, y=P["rich_bp"], name="CA − fitted",
                        line=dict(color="#888")), row=2, col=1)
_sd2 = P["rich_bp"].std(ddof=1) * 2
for _s_, _d_ in ((0.0, "dot"), (_sd2, "dash"), (-_sd2, "dash")):
    _f.add_hline(y=_s_, line_dash=_d_, row=2, col=1)
# NB: not `_q` -- that name holds a residual sd used in the summary cell, and a
# Timestamp formatted with ":.2f" does not raise, it falls through to strftime
# and returns the literal string ".2f".
for _rb in W6F["in_force_from"]:
    _f.add_vline(x=_rb, line_width=1, line_dash="dot",
                 line_color="rgba(150,150,150,0.35)", row=1, col=1)
_f.update_yaxes(title_text="bp", row=1, col=1)
_f.update_yaxes(title_text="bp", row=2, col=1)
_f.update_layout(height=660, legend=dict(orientation="h", y=1.06))
_f.show()
print("(the faint vertical lines are the IMM-roll rebalance dates)")

print(f"\nas of {_last.date()}: Blues CA {P['blues_ca_bp'].iloc[-1]:.2f}bp, "
      f"fitted {P['fitted_ca_bp'].iloc[-1]:.2f}bp, "
      f"rich by {P['rich_bp'].iloc[-1]:+.2f}bp "
      f"({P['rich_z'].iloc[-1]:+.2f} sigma)")
print(f"current weights {F6['w2']:.3f}/-1/{F6['w10']:.3f}, fitted "
      f"{W6F.index[-1].date()}, in force since "
      f"{pd.Timestamp(F6['in_force_from']).date()}")
print(f"window: residual sd {P['rich_bp'].std(ddof=1):.2f}bp, "
      f"|residual| > 2 sigma on {100 * (P['rich_z'].abs() > 2).mean():.1f}% of days")
print(f"fly level today {P['fly_bp'].iloc[-1]:+.1f}bp; the note's ED entry was "
      f"{CFG.entry_fly_bp:+.1f}bp on a differently-weighted fly and a different "
      "curve, so the levels are not comparable and are not meant to be")

# %% [markdown]
# ### Sensitivity: the refit window

# %%
_rows = []
for _wbd in (252, 504, 756):
    _W, _F = imm_refit(P["blues_ca_bp"], P, "fly", _wbd)
    _r = (P["blues_ca_bp"] - _F).dropna()
    _rows.append({"window_bd": _wbd, "n_refits": len(_W),
                  "w2_median": _W["w2"].median(),
                  "w2_range": _W["w2"].max() - _W["w2"].min(),
                  "oos_resid_sd_bp": _r.std(ddof=1),
                  "oos_dates": len(_r)})
print(pd.DataFrame(_rows).round(3).to_string(index=False))
print("\nThe declared window is 504 bd. The residual sd moves little across the "
      "three, so the choice is not load-bearing -- which is the only reason it "
      "is safe to have made one.")

# %% [markdown]
# ## Figure 20 — the pack-by-pack convexity screen
#
# > *"Figure 20 offers a systematic analysis of the valuation in convexity
# > adjustments across the curve. We analyze 1y packs (four consecutive
# > contracts) because individual ED/FRA spreads are noisy and hard to trade. We
# > compute z-scores of CAs and rich/cheap on the fair value model (based on
# > cap/floor vols), together with the z-scores of the dislocations from the
# > model. We also compute volatilities implied from CAs and compare them to the
# > recent realized volatilities."*
#
# The note's own column definitions, and how each is built here:
#
# | column | definition | here |
# |---|---|---|
# | CA (bp) | pack rate − matched fwd 1y swap | `sfr_cvx_adj`, Q/Q matched swap |
# | Model (bp) | Ho-Lee `½σ²·mean(T1²)·1e4` on cap/floor vols | same, on the swaption ATMF at the pack's own expiry |
# | VsModel (bp) | identity `CA − Model` | identity |
# | 3m Roll (short cvx) | `CA(p) − CA(p one contract nearer)` | the analytic equivalent, `−θ/4`, since a colour is 4 contracts wide |
# | Implied vol | Ho-Lee inverted on the observed CA | `sqrt(2e4·CA/w)` |
# | Realized vol | 3m realized of the pack rate, close-to-close, ×√252 | same, **excluding IMM-roll returns on both clocks** |
#
# The note's H0-Z0 (Blues) row, close of 12-Jan-2017, for scale: CA **10.02bp**,
# VsModel **4.61bp**, 3m Roll **1.30bp**, Implied **125.5**, Realized **95.1**,
# Impl/Rlzd **1.3**.

# %%
_VOLMAP = {"WHITES": "nvol_1y1y", "REDS": "nvol_2y1y", "GREENS": "nvol_3y1y",
           "BLUES": "nvol_4y1y", "GOLDS": "nvol_5y1y"}
_rows = []
for _lab in ("WHITES", "REDS", "GREENS", "BLUES", "GOLDS"):
    _l = _lab.lower()
    _ca = P[f"{_l}_ca_bp"]
    _w = P[f"{_l}_w"]
    _t1m = P[f"{_l}_t1mean"]
    _sig = P[_VOLMAP[_lab]]
    _model = _sig ** 2 * _w / 2e4
    _vs = _ca - _model
    # 3m roll for a SHORT convexity position: one quarter of the CA's own decay
    _roll = (_sig ** 2 * _t1m / 1e4) * 0.25
    # implied vol, Ho-Lee inverted; NaN where the adjustment is non-positive
    _v = 2e4 * _ca / _w
    _impl = np.sqrt(_v.where(_v > 0))
    # realized vol of the PACK RATE, excluding roll-date returns on both clocks
    _pack_rate_bp = (_ca / 100.0 + P[f"{_l}_fwd1y_pct"]) * 100.0
    _d = _pack_rate_bp.diff()
    _d = _d.where(~P["is_roll"].astype(bool))
    _rlzd = _d.rolling(63, min_periods=40).std(ddof=1) * math.sqrt(252.0)

    def _z(s, win):
        return ((s - s.rolling(win, min_periods=win // 2).mean())
                / s.rolling(win, min_periods=win // 2).std(ddof=1)).iloc[-1]

    _rows.append({
        "Pack": f"{_lab} (ranks {U.structure_by_label(_lab).ranks[0]}-"
                f"{U.structure_by_label(_lab).ranks[-1]})",
        "CA (bp)": _ca.iloc[-1],
        "1wk chg": _ca.iloc[-1] - _ca.iloc[-6],
        "CA 3m Z": _z(_ca, 63), "CA 1Y Z": _z(_ca, 252),
        "Model (bp)": _model.iloc[-1],
        "VsModel (bp)": _vs.iloc[-1],
        "VsMdl 3m Z": _z(_vs, 63), "VsMdl 1Y Z": _z(_vs, 252),
        "3m Roll": _roll.iloc[-1],
        "Implied": _impl.iloc[-1], "Realized": _rlzd.iloc[-1],
        "Impl/Rlzd": _impl.iloc[-1] / _rlzd.iloc[-1]
        if np.isfinite(_rlzd.iloc[-1]) and _rlzd.iloc[-1] > 0 else np.nan,
    })
FIG20 = pd.DataFrame(_rows).set_index("Pack")
print(f"Figure 20 analogue, close of {_last.date()}:\n")
print(FIG20.round(2).to_string())

# identity checks the note's own table satisfies
_id = (FIG20["CA (bp)"] - FIG20["Model (bp)"] - FIG20["VsModel (bp)"]).abs().max()
print(f"\nidentity CA - Model - VsModel = {_id:.10f} (must be 0)")
assert _id < 1e-9
print(f"identity sqrt(2e4*CA/w) reproduces the CA: max err "
      f"{float((FIG20['Implied'] ** 2 * P[[c + '_w' for c in ['whites', 'reds', 'greens', 'blues', 'golds']]].iloc[-1].to_numpy() / 2e4 - FIG20['CA (bp)']).abs().max()):.8f} bp")

print(f"\nCiti's H0-Z0 row (12-Jan-2017, ED): CA {CFG.fig20_ca_bp}, VsModel "
      f"{CFG.fig20_vs_model_bp}, 3m Roll {CFG.fig20_roll_bp}, Implied "
      f"{CFG.fig20_implied}, Realized {CFG.fig20_realized}, Impl/Rlzd "
      f"{CFG.fig20_implied / CFG.fig20_realized:.1f}")
_bl = FIG20.loc[[i for i in FIG20.index if i.startswith("BLUES")][0]]
print(f"SOFR BLUES today:                   CA {_bl['CA (bp)']:.2f}, VsModel "
      f"{_bl['VsModel (bp)']:.2f}, 3m Roll {_bl['3m Roll']:.2f}, Implied "
      f"{_bl['Implied']:.1f}, Realized {_bl['Realized']:.1f}, Impl/Rlzd "
      f"{_bl['Impl/Rlzd']:.1f}")
print(f"\nThe 3m roll column is the same quantity this package derived "
      f"independently as the CA's THETA: dCA/dt = -sigma^2*mean(T1)/1e4, one "
      f"quarter of which is {_bl['3m Roll']:.2f}bp for Blues against Citi's "
      f"printed {CFG.fig20_roll_bp}bp for the ED equivalent. That number is "
      "also, to within 2-11%, the size of the quarterly IMM-roll jump in the "
      "constant-rank series -- see gv-ca-vs-imm-fly.md section 4.")

# %% [markdown]
# ## Which fly START explains the CA? — forward-start and IMM-dated flies
#
# Citi's Figure 6 regresses the Blues CA on **spot** 2y/5y/10y. But the CA is a
# *forward* object — the Blues pack expires 3¼ to 4 years out — so a spot fly is
# the one start guaranteed **not** to sit where the risk is. The brief's own
# example is the IMM-dated form:
#
# ```python
# UnifiedQuery(curve="USD-SOFR-1D",
#              tenor="IMM_1x2y/IMM_1x5y/IMM_1x10y",
#              value=UnifiedValue.IRS_RATE)
# ```
#
# The same method — fly-constrained weights, refit at every IMM roll, applied
# out of sample — is run across ten start conventions. `IMM_13` starts at the
# Blues pack's own front contract, so it is the matched-expiry case.

# %%
_rows = []
_fits = {}
for _name, _cols in FLY_STARTS.items():
    _miss = [c for c in _cols if c not in P.columns]
    if _miss:
        print(f"  skipping {_name}: missing {_miss}")
        continue
    _W, _F = imm_refit(P["blues_ca_bp"], P, "fly", FIT_WINDOW_BD, _cols)
    if _W.empty:
        continue
    _res = (P["blues_ca_bp"] - _F).dropna()
    _fits[_name] = (_W, _F)
    _rows.append({
        "start": _name,
        "insample_r2_med": _W["r2"].median(),
        "oos_resid_sd_bp": _res.std(ddof=1),
        "oos_resid_mae_bp": _res.abs().mean(),
        "oos_resid_mean_bp": _res.mean(),
        "w2_med": _W["w2"].median(),
        "w2_range": _W["w2"].max() - _W["w2"].min(),
        "b_med": _W["b"].median(),
        "b_sign_flips": int((np.sign(_W["b"]).diff().abs() > 0).sum()),
        "n_refits": len(_W),
    })
STARTS = pd.DataFrame(_rows).set_index("start").sort_values("oos_resid_sd_bp")
print(STARTS.round(3).to_string())

_best = STARTS.index[0]
_spot = "spot (Citi's own)"
_matched = "IMM_13 (Blues front)"
print("")
print(f"BEST by out-of-sample residual sd: {_best} "
      f"({STARTS.loc[_best, 'oos_resid_sd_bp']:.3f} bp), "
      f"WORST: {STARTS.index[-1]} "
      f"({STARTS.loc[STARTS.index[-1], 'oos_resid_sd_bp']:.3f} bp).")
print("")
print("Read the ordering, not the winner. It is MONOTONE in how far forward the "
      "fly starts: spot, then IMM_1, then IMM_2, then 1y forward, and so on out "
      "to IMM_17. The further forward the fly, the worse it explains the CA.")
_rank = list(STARTS.index).index(_matched) + 1
print("")
print(f"The MATCHED-EXPIRY case is the point of the exercise, and it fails. "
      f"{_matched} starts at the Blues pack's own front contract -- the fly "
      f"sitting exactly where the convexity is -- and it ranks {_rank} of "
      f"{len(STARTS)}, with in-sample R2 "
      f"{STARTS.loc[_matched, 'insample_r2_med']:.3f} against "
      f"{STARTS.loc[_spot, 'insample_r2_med']:.3f} for Citi's spot fly and an "
      f"out-of-sample residual sd "
      f"{100 * (STARTS.loc[_matched, 'oos_resid_sd_bp'] / STARTS.loc[_spot, 'oos_resid_sd_bp'] - 1):+.0f}% "
      "larger. Putting the fly where the risk is makes the fit worse, not "
      "better.")
print("")
print("That is not in conflict with block 3, which found the peak hedge R2 "
      "RISING with structure depth: block 3 measured dCA on dfly in daily "
      "CHANGES, this measures the LEVEL relationship out of sample in Citi's "
      "own framework. Two different quantities, and the level one says the "
      "opposite -- which is itself the tell that the level relationship is a "
      "co-trend rather than a risk match.")
_stable = STARTS[STARTS["b_sign_flips"] == 0]
print("")
print("And the column that decides it: starts whose fitted scale b NEVER "
      f"changes sign -- {list(_stable.index) if len(_stable) else 'NONE OF THE TEN'}. "
      f"The fitted weight range is {STARTS['w2_range'].median():.2f} of the "
      "admissible [0,1] at the median start, i.e. essentially the whole of it. "
      "A start whose b flips sign inside the sample cannot be hedged with, "
      "however well it fits on average: the hedge would have to be turned "
      "upside down mid-trade, and the notebook has no way to know in advance "
      "which side of the flip it is on.")

# %%
_f = go.Figure()
for _n in STARTS.index:
    _W, _ = _fits[_n]
    _f.add_trace(go.Scatter(x=_W["in_force_from"], y=_W["b"], name=_n,
                            mode="lines+markers"))
_f.add_hline(y=0.0, line_dash="dash", line_color="black")
_f.update_layout(title="The fitted scale b by fly start, refit at each IMM roll "
                       "-- crossing zero is the failure mode",
                 yaxis_title="b (bp of CA per percent of fly)", height=470,
                 legend=dict(orientation="h", y=-0.22))
_f.show()

# %%
_Wb, _Fb = _fits[_best]
_f = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08,
                   subplot_titles=(f"Blues CA vs the {_best} fly, "
                                   "out of sample", "residual, bp"))
_f.add_trace(go.Scatter(x=P.index, y=P["blues_ca_bp"], name="Blues Cvx Adj"),
             row=1, col=1)
_f.add_trace(go.Scatter(x=_Fb.dropna().index, y=_Fb.dropna(),
                        name=f"{_best} fly, IMM-roll refit"), row=1, col=1)
_f.add_trace(go.Scatter(x=P.index, y=P["blues_ca_bp"] - _Fb, name="residual",
                        line=dict(color="#888")), row=2, col=1)
_f.add_hline(y=0.0, line_dash="dot", row=2, col=1)
_f.update_yaxes(title_text="bp", row=1, col=1)
_f.update_yaxes(title_text="bp", row=2, col=1)
_f.update_layout(height=620, legend=dict(orientation="h", y=1.07))
_f.show()

# %% [markdown]
# ## The clearing venue — CME vs LCH
#
# The note closes its convexity section on the choice of clearing house:
#
# > *"Our analysis is based on the CME FRA/swap curve. Although convexity
# > adjustments will appear wider if clearing the swap leg on LCH, we recommend
# > clearing on CME as the CME-LCH basis has well retraced from its recent wide
# > levels in January. In addition, clearing on CME is more capital-efficient
# > since it allows netting ED and swap positions for margin calculations."*
#
# That is a quantitative claim about the CA and it can be checked. The basis is
# pulled through the **Query + TimeseriesBuilder** path like every other series
# in this notebook — `CHBASIS` queries routed to `IRClearingHouseBasisTB` —
# rather than by reaching past the query layer into the cache.
#
# **Sign, derived not assumed.** `basis_bps` is `clearing_house_a − clearing_house_b`
# = **LCH − CME**, in bp. The CA is `pack rate − matched swap rate`, so moving
# the swap leg to LCH changes it by `−(LCH − CME)`:
#
# $$\mathrm{CA}_{LCH} - \mathrm{CA}_{CME} = -\,\mathrm{basis}_{bp}$$
#
# A **negative** LCH−CME basis therefore makes the adjustment look **wider** on
# LCH, which is exactly what the note says.

# %%
from MDP.IRClearingHouseBasisSwaps.IRClearingHouseBasisSwapsMDP import (
    IRClearingHouseBasisSwapsMDP)
from Query.IRClearingHouseBasis import (IRClearingHouseBasisQuery,
                                        IRClearingHouseBasisValue)
from TB.IRClearingHouseBasisTB import IRClearingHouseBasisTB
from TB.TimeseriesBuilder import TimeseriesBuilder

CCP_TENORS = ("2y", "3y", "4y", "5y", "7y", "10y", "30y")
#: The Blues matched swap starts at the pack's front IMM (~3.25y) and runs one
#: year, so its ~3.75y average maturity sits between the 3y and 4y nodes. 4y is
#: the declared choice; the sensitivity across 3y/4y/5y is printed below.
CCP_TENOR_FOR_BLUES = "4y"

_ccp_tb = IRClearingHouseBasisTB(IRClearingHouseBasisSwapsMDP(), show_tqdm=False)
CCP = TimeseriesBuilder().get_timeseries(
    start=P.index.min(), end=P.index.max(),
    queries=[IRClearingHouseBasisQuery(tenor=t, ccy="USD", index="SOFR",
                                       clearing_house_a="LCH",
                                       clearing_house_b="CME",
                                       value=IRClearingHouseBasisValue.BASIS_BPS)
             for t in CCP_TENORS],
    n_jobs=4, routers={"CHBASIS": _ccp_tb})
CCP.index = pd.to_datetime(CCP.index)
CCP = CCP.reindex(P.index)
CCP.columns = [c.split()[1] for c in CCP.columns]
CCP = CCP[[t.upper() for t in CCP_TENORS]]

print(f"CME-LCH basis via Query + TimeseriesBuilder: {CCP.shape}, "
      f"{CCP.index.min().date()}..{CCP.index.max().date()}")
print(f"router failures: {_ccp_tb.failures or 'none'}")
print("")
print(CCP.describe().loc[["mean", "std", "min", "max"]].round(3).to_string())

# A column that never moves is not a measurement. Say so before plotting it.
_flat = [c for c in CCP.columns if float(CCP[c].std(ddof=1) or 0.0) < 1e-9]
if _flat:
    print("")
    print(f"DEGENERATE: {_flat} have zero variance over the whole window "
          f"(constant {CCP[_flat[0]].dropna().iloc[0]:+.2f} bp). The vendor "
          "serves the same rate for both houses at those tenors, so the column "
          "carries no information and is excluded from what follows.")
CCP_USE = CCP[[c for c in CCP.columns if c not in _flat]]

# %%
_f = go.Figure()
for _ccol in CCP_USE.columns:
    _f.add_trace(go.Scatter(x=CCP_USE.index, y=CCP_USE[_ccol],
                            name=_ccol))
_f.add_hline(y=0.0, line_dash="dot")
_f.update_layout(title="CME-LCH basis (LCH minus CME), USD SOFR, by tenor",
                 yaxis_title="bp", height=440,
                 legend=dict(orientation="h", y=1.08))
_f.show()

# %%
_bt = CCP_TENOR_FOR_BLUES.upper()
_b = CCP[_bt]
P["ca_lch_bp"] = P["blues_ca_bp"] - _b
print(f"Effect of clearing the Blues matched swap on LCH instead of CME, "
      f"using the {_bt} basis node:")
print("")
print(f"  basis (LCH-CME)      mean {_b.mean():+.2f} bp   "
      f"last {_b.iloc[-1]:+.2f} bp   range [{_b.min():+.2f}, {_b.max():+.2f}]")
print(f"  Blues CA on CME      mean {P['blues_ca_bp'].mean():+.2f} bp   "
      f"last {P['blues_ca_bp'].iloc[-1]:+.2f} bp")
print(f"  Blues CA on LCH      mean {P['ca_lch_bp'].mean():+.2f} bp   "
      f"last {P['ca_lch_bp'].iloc[-1]:+.2f} bp")
print(f"  LCH minus CME on CA  mean {(P['ca_lch_bp'] - P['blues_ca_bp']).mean():+.2f} bp")
_wider = float(((P["ca_lch_bp"] - P["blues_ca_bp"]) > 0).mean())
print("")
print(f"The adjustment is WIDER on LCH on {100 * _wider:.0f}% of days, which is "
      "the note's claim. On this window it is worth "
      f"{abs((P['ca_lch_bp'] - P['blues_ca_bp']).mean()):.2f} bp on average "
      f"against a Blues CA of {P['blues_ca_bp'].mean():.2f} bp -- i.e. "
      f"{100 * abs((P['ca_lch_bp'] - P['blues_ca_bp']).mean()) / P['blues_ca_bp'].mean():.0f}% "
      "of the level, entirely from where the swap leg clears.")

print("")
print("Sensitivity to the tenor node (the matched swap sits between 3y and 4y):")
for _ttag in ("3Y", "4Y", "5Y"):
    if _ttag in CCP.columns:
        print(f"  {_ttag}: mean basis {CCP[_ttag].mean():+.3f} bp, "
              f"last {CCP[_ttag].iloc[-1]:+.3f} bp")

# %%
# The identity the sign derivation rests on, checked rather than asserted.
_chk = (P["ca_lch_bp"] - P["blues_ca_bp"] + _b).abs().max()
print(f"identity  CA_LCH - CA_CME + basis == 0   ->  max |err| {_chk:.12f} bp")
assert _chk < 1e-9

# And the CCP basis against the CA, since the note offers it as a reason the CA
# moved. It is a LEVEL comparison, with the same caveat as everything else here.
_j = pd.concat([P["blues_ca_bp"].rename("ca"), _b.rename("basis")],
               axis=1).dropna()
_dj = _j.diff().dropna()
print("")
print(f"corr(Blues CA, {_bt} CME-LCH basis)  levels {_j['ca'].corr(_j['basis']):+.4f}"
      f"   daily changes {_dj['ca'].corr(_dj['basis']):+.4f}   n {len(_j)}")
print("A level correlation here is the same co-trend this notebook has been "
      "reporting throughout; the change correlation is the one that would have "
      "to be there for the basis to be moving the adjustment day to day.")

# %% [markdown]
# ## The ticket, in the note's own format, as of the last date

# %%
_r2, _r5, _r10 = P[["r2y_pct", "r5y_pct", "r10y_pct"]].iloc[-1]
_A2n, _A5n, _A10n = (annuity(_r2, 2), annuity(_r5, 5), annuity(_r10, 10))
_net_w = -F6["w2"] + 1.0 - F6["w10"]
_ranks = U.structure_by_label("BLUES").ranks
_contracts = int(round(CFG.ca_dv01 / (len(_ranks) * 25.0)))

# Direction is DERIVED, not assumed. The traded spread is S = CA - (a + b*fly)
# and we sell it when it is rich; dS/d(fly_bp) = -b/100, so the fly leg earns
# -side*b/100*ca_dv01 per bp of the quoted combination. With b NEGATIVE, as it
# is after the mid-2023 reversal, selling a rich CA means being LONG the fly --
# the opposite side from Citi's 2017 ticket, and the ticket has to say so.
_rich_now = float(P["rich_bp"].iloc[-1])
_side_ca = -1 if _rich_now > 0 else 1
_belly_dv01 = -_side_ca * (F6["b"] / 100.0) * CFG.ca_dv01
_n5 = _belly_dv01 / (_A5n * 100.0)
_n2 = F6["w2"] * _belly_dv01 / (_A2n * 100.0)
_n10 = F6["w10"] * _belly_dv01 / (_A10n * 100.0)
_ca_verb = "SELL" if _side_ca < 0 else "BUY"
_fut_verb = "buy" if _side_ca < 0 else "sell"
_swap_verb = "pay" if _side_ca < 0 else "receive"
_belly_verb = "PAY" if _belly_dv01 > 0 else "RECEIVE"
_wing_verb = "receive" if _belly_dv01 > 0 else "pay"

print(f"TICKET as of {_last.date()}, in the note's own format")
print("=" * 72)
print(f"{_ca_verb} ${CFG.ca_dv01:,.0f} DV01 of Blues convexity adjustments:")
print(f"  {_fut_verb} {_contracts:,} of each of the four SR3 contracts at "
      f"ranks {_ranks} ({len(_ranks) * _contracts:,} contracts, "
      f"${len(_ranks) * _contracts * 25:,.0f}/bp)")
print(f"  {_swap_verb} the matched-maturity quarterly/quarterly swap")
print(f"  at {P['blues_ca_bp'].iloc[-1]:.2f}bp of spread "
      f"(the note's entry was {CFG.entry_ca_bp}bp on ED)")
print("")
print(f"HEDGE: {_belly_verb} the belly of the 2s5s10s fly at the fitted DV01 "
      f"weights {F6['w2']:.3f}/-1/{F6['w10']:.3f}, {_wing_verb} the wings")
print(f"  weights fitted {W6F.index[-1].date()}, in force since the "
      f"{pd.Timestamp(F6['in_force_from']).date()} IMM roll; next rebalance at "
      "the next roll")
print(f"  notionals  ${abs(_n2):,.0f}mm 2y {_wing_verb} / "
      f"${abs(_n5):,.0f}mm 5y {_belly_verb.lower()} / "
      f"${abs(_n10):,.0f}mm 10y {_wing_verb}")
print(f"  P&L per bp of the quoted fly ${_belly_dv01:,.0f}   fly level "
      f"{P['fly_bp'].iloc[-1]:+.1f}bp")
print("")
print(f"RICHNESS  {_rich_now:+.2f}bp = {P['rich_z'].iloc[-1]:+.2f} sigma "
      f"(the note entered at {CFG.fig6_wide_bp:.0f}bp / 2 sigma)")
_res_dur = _net_w * abs(_belly_dv01)
print(f"RESIDUAL DURATION of the hedge {_res_dur:+,.0f}/bp "
      f"({_net_w:+.3f} x belly DV01) -- zero by construction under the fly "
      "constraint, which is why the constrained fit is the one that produces a "
      "tradeable ticket")
print("=" * 72)
print(f"NOTE THE DIRECTION. The fitted scale b is {F6['b']:+.2f} -- NEGATIVE, "
      "after the mid-2023 reversal -- so a rich CA is now hedged by being LONG "
      "the fly, the opposite side from Citi's 2017 ticket. That is not a "
      "transcription slip; it is the sign change in the relationship, and it "
      "is the single most important thing this reproduction found.")

# %% [markdown]
# ## What reproduces, and what does not

# %%
# Re-derived here, NOT carried in from the cell that first computed them. A
# single-underscore name is a scratch name, and this notebook has now had two
# of them clobbered by a later loop variable -- one raised, one silently
# printed the literal string ".2f". The frame is the source of truth.
_sd = _cmp.std(ddof=1)
_mae = _cmp.abs().mean()
_mu = _cmp.mean()
_KEY_REFIT = "IMM refit, fly-constrained"
_KEY_CITI = "IMM refit, Citi weights"
_KEY_STATIC = "static fly, full sample (in-sample)"
_resid_q, _resid_c, _resid_s = (float(_sd[_KEY_REFIT]), float(_sd[_KEY_CITI]),
                                float(_sd[_KEY_STATIC]))
_mae_q, _mae_c = float(_mae[_KEY_REFIT]), float(_mae[_KEY_CITI])
assert all(isinstance(v, float) for v in
           (_resid_q, _resid_c, _resid_s, _mae_q, _mae_c))

print("REPRODUCES")
print("-" * 72)
print(f"* The note's internal arithmetic, all four checks: notionals -> DV01 "
      f"weights (<2%), Figure-6 beta -> belly DV01 ({100 * (_belly_from_beta / _belly_from_notional - 1):+.1f}%), "
      f"the two roll numbers -> the printed $380k carry "
      f"({100 * (_carry / CFG.carry_3m_usd - 1):+.1f}%), and the printed "
      f"richness ({_rich_at_entry:.2f}bp vs 'about 3bp').")
print(f"* Figure 6's METHOD. Regressing Blues CA on (2y, 5y, 10y) and reading "
      f"the weights off the fit works on SOFR: the fly-constrained quarterly "
      f"refit runs at w2 median {W6F['w2'].median():.3f} and holds an "
      f"out-of-sample residual sd of {P['rich_bp'].std(ddof=1):.2f}bp.")
print(f"* The IMM-roll REBALANCE, but only in part: it beats a static fly "
      f"fitted on the whole window with hindsight ({_resid_q:.3f} vs "
      f"{_resid_s:.3f} bp OOS "
      f"residual sd) and it beats every scheme on mean absolute residual "
      f"({_mae_q:.3f} bp) and on bias. It does NOT beat Citi's fixed 2017 weights "
      f"on residual sd -- see the corresponding entry below.")
print(f"* Figure 1's SIGN. The CA sits wide to a vol-calibrated Ho-Lee level on "
      f"{100 * (P['vs_model_bp'] > 0).mean():.0f}% of days, mean "
      f"{P['vs_model_bp'].mean():+.2f}bp.")
print(f"* Figure 2's MECHANISM. corr(dealer net, AM+leveraged) = {_c_da:+.3f}: "
      "dealers are the other side, as the note describes.")
print(f"* Figure 3 exactly -- the store carries the note's own +/-25bp absolute "
      f"offsets on {100 * P['rr_3m10y_bp'].notna().mean():.0f}% of dates.")
print()
print("DOES NOT REPRODUCE, AND WHY")
print("-" * 72)
print(f"* Figure 5's headline number. The out-of-sample level correlation of "
      f"3y1y vol with its own IMM-roll-refit fly is "
      f"{_j5['y'].corr(_j5['f']):+.3f} here against the note's "
      f"{CFG.fig5_corr:.2f} -- and the note's is over Jan-1999..Jan-2017, an "
      "18-year window spanning several regimes, against 4.6 years here and out "
      "of sample rather than in.")
print(f"* Figure 4's ramp. {len(_g)} monthly observations against the note's "
      f"~130; four buckets of {len(_g) // 4} cannot confirm or deny it.")
print(f"* Citi's PUBLISHED weights. 0.705/-1/0.465 was a 2017 Eurodollar fit; "
      f"the SOFR quarterly refit lands at w2 median {W6F['w2'].median():.3f}, "
      "and there is no reason it should have matched. The method reproduces; "
      "the 2017 numbers were never the thing to reproduce.")
print(f"* Citi's own SPECIFICATION, unconstrained, on this curve. With a "
      f"condition number of {_cond:,.0f} the 3-rate fit does not stay inside "
      f"butterfly territory: w2 ranges [{W6['w2'].min():+.2f}, "
      f"{W6['w2'].max():+.2f}] across the {len(W6)} IMM-roll refits and the "
      "weights sum to one on none of them. The fly constraint is what makes "
      f"the output tradeable -- w2 is interior on {len(W6F) - _edge} of "
      f"{len(W6F)} refits -- but the constrained fit then reverses in "
      f"mid-2023: w2 moves from {W6F['w2'].iloc[0]:.2f} to "
      f"{W6F['w2'].iloc[-1]:.2f} and the scale b flips from "
      f"{W6F['b'].iloc[0]:+.1f} to {W6F['b'].iloc[-1]:+.1f}.")
print(f"* The REBALANCE, as a variance reduction. Citi's fixed 2017 weights "
      f"give the lowest out-of-sample residual sd ({_resid_c:.3f} bp) of any scheme "
      f"tried, including the IMM-roll refit ({_resid_q:.3f} bp). The refit wins on "
      f"mean absolute residual ({_mae_q:.3f} vs {_mae_c:.3f} bp) and on bias, and "
      "loses in the tails. It moves the error around; it does not shrink it.")
print("* The trade's own P&L is NOT shown from these level series. This package "
      "measured that a par-rate panel is a signal tool and not a P&L model: on "
      "five convexity books it overstated three hedged Sharpes by 1.5-6x and "
      "understated an unhedged book's dollars by 2-3.8x. See "
      "docs/convexityrv/results/gv-ca-vs-imm-fly.md section 7 and 6b.")
print()
print("THE ORIGINAL'S OWN OUTCOME, for the record (not reproducible here -- it "
      "is Eurodollars in 2017)")
print("-" * 72)
print("* Entered 9-Feb-2017 at 8.8bp CA / -18.2bp fly. Closed 6-Jun-2017 at "
      "6.6bp CA / -16.5bp fly, net +$500k against a +$600k target and a -$350k "
      "stop; Citi's own table records +$552k.")
print()
print("STANDING CAVEAT")
print("-" * 72)
print("This is a reproduction of a published rule on current data. It scores no "
      "cells and adds nothing to the GV block's trial count. That block's "
      "verdict -- CA-vs-fly is dead as a systematic strategy, best primary cell "
      "0.851 against an annualised null bar of 1.2198 -- stands unchanged, and "
      "the reason is now visible in Figure 6 itself: the fitted scale REVERSES "
      "SIGN in mid-2023, so the hedge that was right for the first half of "
      "this window is exactly wrong for the second.")
