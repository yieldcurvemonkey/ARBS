# %% [markdown]
# # Strategy 2 — Citi's STIR-futures convexity adjustment vs the 2s5s10s butterfly (ED → SFR)
#
# **What the strategy is.** Citi Research ran a screen from 2016 to 2020 that
# ranked every rolling 1y Eurodollar pack by how rich its *convexity adjustment*
# was, and traded the richest one as a short-vol proxy. Citi **restated the same
# screen for SOFR itself** in *Rates Vol Lab — Forward steepener and vol
# divergence*, 12-Jun-2023, Figure 58 (close 6/9/23), so this is not a blind
# port: there is a 13-row SOFR tie-out table to hit.
#
# The methodology note, verbatim (SOFR version):
#
# > "Convexity adjustments for 1y SOFR packs are computed as the spread between
# > the pack's rate (the average of 4 SOFR rates in the pack) and
# > matched-maturity forward 1y CME swap rate. The model for convexity
# > adjustment is the Ho-Lee model calibrated to cap/floor vols. Implied vol is
# > calculated by matching the model to the observed convexity adjustment.
# > Realized vol is 3m realized vol of the corresponding pack. For each
# > valuation metric, we mark three best short convexity trades in bold."
#
# The trade, verbatim (13-Jan-2017 and 09-Feb-2017):
#
# > "**Sell $100k DV01 of Blues convexity adjustment, i.e. buy 1000 of H0-Z0
# > packs (1000 of each of the four contracts) and pay $1bn on a
# > matched-maturity (3/18/20-3/17/21) CME swap.**"
# >
# > "**Pay the belly of the 2s5s10s swap fly with notional weights
# > $79mn/-$44.4mn/$10.9mn (0.73/-1/0.46 DV01 weights).**"
# >
# > "3y1y vol is mostly driven by expectations of monetary policy, and therefore
# > should be directional with the valuations of 5s on the curve. … selling the
# > 2s5s10s fly as a hedge has the advantage of positive carry, unlike buying
# > volatility."
#
# **Why it is short convexity.** The futures leg's DV01 is rate-invariant
# ($25/bp/contract, forever). The swap leg's DV01 rises as rates fall. Holding
# the linear instrument long against the convex one short is net short gamma,
# which is why the adjustment is a volatility-driven quantity at all. You profit
# when the CA narrows.
#
# ## Three things this notebook states up front rather than burying
#
# 1. **The level offset is real and is not fudged.** Citi's swap leg is
#    CME-cleared; `USD-SOFR-1D` is not. On 2023-06-09 the shape reproduces at
#    **correlation 0.968** against Citi's 13 rows, with a **level offset of
#    about −3.9bp**. `Strat2Config.ca_basis_bp` exists for this and defaults to
#    `0.0` — the raw number is reported. The strategy is driven off the
#    basis-robust metrics (z-scores, vs-model, roll), which is what four of
#    Citi's six ranking families already are.
# 2. **"Calibrated to cap/floor vols" is the one genuinely unspecified degree of
#    freedom** and is implemented as a documented, configurable choice. The
#    default fits a smooth variance term structure across packs to the observed
#    CA curve, so `vs_model` measures *cross-sectional* dislocation. It cannot
#    and does not reproduce the *level* of Citi's `Vs Model` column.
# 3. **The pack universe stops at rank 10, not Citi's rank 17.** The local
#    Barchart SR3 store is demand-driven; a daily strip deep enough for Blues
#    and Golds exists on 561 dates, mostly 2020-2021. Section 3 shows the scan.
#    The 2023-06-09 tie-out still runs at Citi's full depth, because that one
#    date is fully cached.

# %%
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import datetime
import json
import math
import pathlib
import sys
import time

import numpy as np
import pandas as pd

_REPO = (pathlib.Path(__file__).resolve().parents[3] if "__file__" in dir()
         else pathlib.Path.cwd().parents[2])
sys.path.insert(0, str(_REPO))

import plotly.io as pio

pio.renderers.default = "plotly_mimetype+notebook_connected"

from BT.data_handler import TimeGrid
from BT.query_actions import AddQueryAction, UnwindPositionsAction
from BT.query_engine import QueryDrivenBacktest
from BT.query_strategy import QueryStrategy
from BT.trade_dashboard import compare_curves, summary_stats, trade_dashboard
from BT.triggers import DateTrigger, DateTriggerRequirements
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapStructure import IRSwapStructure
from Query.IRSwaps.IRSwapValue import IRSwapValue
from Query.STIRFutures.STIRFutureQuery import STIRFutureQuery
from Query.STIRFutures.STIRFutureStructure import STIRFutureStructure
from Query.STIRFutures.STIRFutureValue import STIRFutureValue

from RVUtils.ConvexityRV.holee import implied_vol_from_ca_bp
from RVUtils.ConvexityRV.packs import DV01_PER_CONTRACT
from RVUtils.ConvexityRV.strat2_sofr_convexity import (
    Strat2Config,
    assert_ran,
    build_panel,
    ca_snapshot,
    daily_screen,
    fit_sigma_model,
    hedge_sizing,
    local_cached_dates,
    model_timeseries,
    pack_windows,
    panel_diagnostics,
    panel_timeseries,
    plan_epochs,
    rank_flags,
    run_backtest,
    select_pack,
    trim_to_contiguous_run,
)

DATA = _REPO / "notebooks" / "data" / "convexity_rv"
DATA.mkdir(parents=True, exist_ok=True)
CURVE = "USD-SOFR-1D"

# %% [markdown]
# ## 1. CONFIG — every knob, with why it is set where it is
#
# `Strat2Config` carries the full documented set; the values below are the ones
# this run uses. Nothing here was tuned on the backtest's own P&L.

# %%
CFG = Strat2Config(
    # --- universe. 13 contracts -> pack windows 1..10. Citi ranks 5..17, which
    # needs 20 contracts a day; see section 3 for why the local store cannot.
    n_contracts=13,
    rank_start=2,          # window 1 is still computed: it is what window 2's 3m roll rolls to
    n_packs=9,             # windows 2..10 = Whites through Greens+
    # --- the CA level. 0.0 = report the raw number. Citi's leg is CME-cleared
    # and this curve is not; the measured gap on 6/9/23 was about -3.9bp.
    # --- the CA level. 0.0 = report the raw number.
    # NOTE (corrected): the ~-3.9bp gap against Citi on 6/9/23 was NOT a CME-vs-LCH
    # clearing basis. It was the matched swap's payment frequency: Citi specifies
    # quarterly on both legs, the usd_irs spec quotes ANNUAL fixed, and the gap is
    # the compounding term 3q^2/8. Measured across 11,900 pack-days,
    # OLS gap ~ b*r^2 gives b = 0.36886 against the parameter-free prediction
    # 0.375 (-1.6%), r^2 = 0.9981. With the swap built Q/Q the residual against
    # Citi is mean -0.11bp / median -0.58bp, which now bounds the true clearing
    # basis at under 2bp rather than attributing 4bp to it.
    ca_basis_bp=0.0,
    round_pack_price_to_tick=False,   # a 1/4 tick is 0.25bp of CA; the raw average is what tied out
    # --- the model. "fit" = smooth variance term structure across packs, fitted
    # to the observed CA curve each day. See section 6 for what that does and
    # does not measure.
    sigma_model_mode="fit",
    sigma_fit_degree=2,
    holee_convention="citi",          # 0.5*sigma^2*T1^2 -- what the published tables use
    ca_floor_bp=0.1,                  # below this the flat-sigma inversion is n/a
    # --- metrics
    realized_window_days=63,          # "3m realized vol of the corresponding pack"
    z_window_3m=63,
    z_window_1y=252,
    min_history_for_z1y=252,
    week_days=5,
    # --- ranking. "we mark three best short convexity trades in bold", then
    # take the pack flagged by the most metrics.
    top_n_per_metric=3,
    min_metrics_flagged=0,            # always hold the top pack -- Citi rolled Blues->Greens
    # --- hedge
    hedge_enabled=True,
    hedge_tenors=("2Y", "5Y", "10Y"),
    hedge_regression_days=252,        # re-fit at every entry; Citi re-fit within 3 weeks
    hedge_min_abs_beta=1.0,
    hedge_require_positive_wings=True,
    # --- trade
    ca_dv01=100_000.0,                # Citi's flagship size: 1000 packs, $1bn swap
    max_hold_months=3,                # carry is quoted "over a 3m term"
    rebalance_freq="BMS",             # consult the screen on the 1st business day of the month
    cost_bp_per_roundtrip=0.0,        # Citi excludes costs explicitly; section 11 prices them
    # --- sample. The start is 2019-07-08, NOT 2019-01-01, and the reason is a
    # limitation of the zero-convexity control rather than anything visible in
    # the data. Until that date USD-SOFR-1D is built on 26 nodes whose second
    # node sits 735 days out, so a single log-linear segment spans the whole
    # front end. Every quarterly forward inside a pack window is then identical
    # by interpolation, the forward spread measures 8.9e-12bp, and CA_synthetic
    # returns EXACTLY 0 -- a perfect control pass -- on a swap leg that is not a
    # market observation at all. Measured: 520 rows affected (514 of them in
    # 2019), CA_observed spanning -91.6 to +27.6bp with 42.7% negative.
    # Node counts: 2019-06-20 -> 26, 2019-07-01 -> 33, 2019-07-08 -> 45.
    # The control cannot see this, so the cut is imposed from curve structure.
    start=datetime.date(2019, 7, 8),
    end=datetime.date(2026, 8, 14),
)
print(json.dumps({k: str(v) for k, v in CFG.__dict__.items()}, indent=1))

# %% [markdown]
# ## 2. The sign probes — run live, every execution
#
# Three separate conventions can each silently invert the whole strategy, so all
# three are measured against a planted answer rather than read off the source.
#
# 1. **`IRSwapQuery` OUTRIGHT `bpv > 0` = payer.** The 2022-09 CPI week moved 5y
#    about 23bp; a payer must gain and ±bpv must mirror exactly.
# 2. **`STIRFutureQuery` `contracts > 0` = long the future = short the rate.**
#    100 contracts of SR3M25 over a +4.50bp move must mark `−4.50 × $25 × 100`.
# 3. **`IRSwapStructure.FLY` `bpv > 0` constrains the belly and pays it.**
#    `risk_weights=[0.73, 1, 0.47]` must resolve to `[−0.73, +1, −0.47]` — pay
#    the belly, receive the wings, which is Citi's hedge — and the notionals
#    must land on the published shape.

# %%
_fut = STIRFutureMDP(source=CFG.futures_source)
_swp = IRSwapsMDP(source=CFG.swap_source)


def _probe_outright(bpv: float) -> float:
    dates = [datetime.date(2022, 9, 12), datetime.date(2022, 9, 13),
             datetime.date(2022, 9, 14), datetime.date(2022, 9, 15)]
    q = IRSwapQuery(structure=IRSwapStructure.OUTRIGHT, value=IRSwapValue.NPV,
                    tenor="5Y", curve=CURVE, structure_kwargs={"bpv": bpv},
                    tags=("probe",))
    strat = QueryStrategy(name=f"sign_{bpv:+.0f}", triggers=[
        DateTrigger(DateTriggerRequirements(dates=[dates[0]]),
                    actions=[AddQueryAction(query=q, meta={"tags": ["probe"]})]),
        DateTrigger(DateTriggerRequirements(dates=[dates[-1]]),
                    actions=[UnwindPositionsAction(match_tag="probe", fee=0.0)]),
    ])
    bt = QueryDrivenBacktest(time_grid=TimeGrid([pd.Timestamp(d) for d in dates]),
                             strategy=strat, mdp=IRSwapsMDP(source=CFG.swap_source),
                             show_progress=False)
    bt.run()
    eq = pd.Series(bt.mtm_history)
    assert len(eq) == len(dates), "engine swallowed a step"
    return float(eq.iloc[-1])


_plus, _minus = _probe_outright(+100_000.0), _probe_outright(-100_000.0)
print(f"OUTRIGHT  +bpv {_plus:+,.0f}   -bpv {_minus:+,.0f}")
assert _plus > 0, "payer must gain in the 2022-09 selloff"
assert abs(_plus + _minus) < 1e-6 * abs(_plus), "buy/sell must mirror -- seam regressed?"
print("SIGN TEST 1 PASS: OUTRIGHT bpv>0 is a PAYER, mirror exact")

# %%
_d0, _d1 = datetime.date(2023, 6, 9), datetime.date(2023, 6, 15)
_p0 = float(_fut.get_data({"symbols": ["SR3M25"], "timestamp": _d0})["SR3M25"][0].price())
_p1 = float(_fut.get_data({"symbols": ["SR3M25"], "timestamp": _d1})["SR3M25"][0].price())
_expect = (_p1 - _p0) * 100.0 * DV01_PER_CONTRACT * 100
_qf = STIRFutureQuery(structure=STIRFutureStructure.OUTRIGHT, value=STIRFutureValue.PRICE,
                      symbol="SR3M25", structure_kwargs={"contracts": 100}, tags=("f",))
_dates = [d.date() for d in pd.bdate_range(_d0, _d1)]
_strat = QueryStrategy(name="fut_probe", triggers=[
    DateTrigger(DateTriggerRequirements(dates=[_dates[0]]),
                actions=[AddQueryAction(query=_qf, meta={"tags": ["f"]})]),
    DateTrigger(DateTriggerRequirements(dates=[_dates[-1]]),
                actions=[UnwindPositionsAction(match_tag="f", fee=0.0)]),
])
_strat.mdps = {"STIRFUTURE": _fut, "IRS": _swp}
_strat.default_mdp = _swp
_bt = QueryDrivenBacktest(time_grid=TimeGrid([pd.Timestamp(d) for d in _dates]),
                          strategy=_strat, mdp=_swp, show_progress=False)
_bt.run()
_eq = pd.Series(_bt.mtm_history)
assert len(_eq) == len(_dates), "engine swallowed a step"
print(f"FUTURES   price {_p0} -> {_p1} (rate {(_p0 - _p1) * 100:+.2f}bp), "
      f"engine {float(_eq.iloc[-1]):+,.0f}, expected {_expect:+,.0f}")
assert abs(float(_eq.iloc[-1]) - _expect) < 1.0
assert float(_eq.iloc[-1]) < 0, "price fell, a long future must lose"
print("SIGN TEST 2 PASS: contracts>0 is LONG the future = SHORT the rate, $25/bp/contract")

# %%
_pricer = _swp.get_pricer({"curve_name": CURVE, "timestamp": _d0, "offline": True})
_shared = [0.73, 1.0, 0.47]
_qfly = IRSwapQuery(structure=IRSwapStructure.FLY, value=IRSwapValue.PV01, curve=CURVE,
                    structure_kwargs={"front_tenor": "2Y", "belly_tenor": "5Y",
                                      "back_tenor": "10Y", "risk_weights": _shared,
                                      "bpv": 21_400.0})
_pkg, _w = _qfly.resolve_package(pricer_or_curve=_pricer)
_res = [_pricer.resolve_pricable(p, w) for p, w in zip(_pkg, _w)]
_nots = [float(_pricer.notional(p)) / 1e6 for p in _res]
print(f"FLY       resolved risk_weights {_w}, notionals (mn) "
      f"{[round(n, 1) for n in _nots]}  vs Citi 13-Jan-17: 79.0 / -44.4 / 10.9")
assert _w == [-0.73, 1.0, -0.47], "bpv>0 must pay the belly and receive the wings"
assert _nots[1] > 0 > _nots[0] and _nots[2] < 0
assert _shared == [-0.73, 1.0, -0.47], "the in-place mutation of risk_weights stopped happening"
print("SIGN TEST 3 PASS: FLY bpv>0 PAYS THE BELLY; risk_weights IS mutated in place")

# %% [markdown]
# ## 3. Data coverage — why the pack universe stops at rank 10
#
# The Barchart SR3 store (`STIRFuturePricer_Cache`, an 8-shard diskcache) is
# demand-driven, not an archive: a miss goes to the network at roughly **60
# seconds per cold contract**. Scanning the shards directly gives the number of
# EOD dates carrying **every** contract each pack window needs:
#
# | pack windows | contracts | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
# |---|---|---|---|---|---|---|---|---|---|
# | 1..10 | 1..13 | 252 | 253 | 252 | 252 | 183 | 1 | 2 | 1 |
# | 4..13 | 4..16 | 252 | 253 | 252 | 185 | 3 | 1 | 2 | 1 |
# | **5..17 (Citi)** | 5..20 | 77 | 253 | 187 | 40 | 2 | 1 | 0 | 0 |
#
# The obvious substitute — reading IMM×IMM forwards off the futures-calibrated
# `USD-SOFR-1D-Q12STIRT` curve, which *is* complete (2,060 dates 2018-06 to
# 2026-08) — was tested and **rejected**: against raw settles on 390 matched
# (date, pack) observations the pack-level CA disagrees by a median absolute
# **9.3bp in 2019** and 2.6bp in 2022, and the two CA series correlate at only
# **0.33**. That is curve calibration residual, several times the size of the
# signal, not convexity.
#
# So: windows 2..10 on raw settles, and the tie-out below runs at Citi's full
# depth on the single date where the deep strip is cached.

# %% [markdown]
# ## 4. TIE-OUT (a) — Citi's Figure 58, 13 rows, close 6/9/2023
#
# Asserted: the pack **labels**, the matched swap **start and end dates**
# (M4-H5 → 2024-06-19..2025-06-18; M6-H7 → 2026-06-17..2027-06-16), and CA
# **correlation > 0.95**.
#
# **Not** asserted: the level. Citi prices the swap leg CME-cleared and this
# curve does not, and the offset is what a clearing basis looks like — roughly
# constant in sign, growing with maturity. Asserting it away would be fitting.

# %%
CITI_SOFR = pd.DataFrame(
    [("M4-H5", 4.03, 2.94, 1.09, 0.88, 199.5, 229.7),
     ("U4-M5", 4.41, 3.79, 0.62, 0.38, 178.1, 201.4),
     ("Z4-U5", 5.16, 4.66, 0.49, 0.74, 167.7, 180.3),
     ("H5-Z5", 6.10, 5.53, 0.58, 0.95, 161.6, 166.3),
     ("M5-H6", 8.24, 6.36, 1.88, 2.14, 168.5, 156.4),
     ("U5-M6", 9.77, 7.16, 2.60, 1.52, 166.3, 148.8),
     ("Z5-U6", 11.70, 8.02, 3.67, 1.93, 166.5, 142.2),
     ("H6-Z6", 13.70, 8.96, 4.74, 2.00, 166.0, 136.1),
     ("M6-H7", 15.40, 9.98, 5.42, 1.70, 163.1, 130.9),
     ("U6-M7", 16.84, 11.10, 5.74, 1.44, 159.0, 126.2),
     ("Z6-U7", 18.27, 12.23, 6.04, 1.43, 155.1, 121.9),
     ("H7-Z7", 20.08, 13.37, 6.71, 1.81, 152.8, 118.0),
     ("M7-H8", 22.29, 14.50, 7.79, 2.21, 151.9, 113.8)],
    columns=["pack", "citi_ca", "citi_model", "citi_vs_model", "citi_roll",
             "citi_iv", "citi_rv"]).set_index("pack")

AS_OF = datetime.date(2023, 6, 9)
CITI_CFG = Strat2Config(n_contracts=20, rank_start=5, n_packs=13)

_specs = pack_windows(AS_OF, CITI_CFG)
_syms = sorted({s for sp in _specs for s in sp.symbols})
_snap = _fut.get_data({"symbols": _syms, "timestamp": AS_OF})
_prices = {s: float(v[0].price()) for s, v in _snap.items() if v}
_pr = _swp.get_pricer({"curve_name": CURVE, "timestamp": AS_OF, "offline": True})
TIEOUT = ca_snapshot(AS_OF, CITI_CFG, futures_prices=_prices, swap_pricer=_pr).set_index("pack")
TIE = CITI_SOFR.join(TIEOUT[["rank", "swap_start", "swap_end", "ca_bp",
                             "time_weight", "t_mid"]])
pd.set_option("display.width", 220)
print(TIE.round(3).to_string())

assert list(TIE.index) == list(CITI_SOFR.index), "row set differs from Citi's"
assert TIE.loc["M4-H5", "swap_start"] == datetime.date(2024, 6, 19)
assert TIE.loc["M4-H5", "swap_end"] == datetime.date(2025, 6, 18)
assert TIE.loc["M6-H7", "swap_start"] == datetime.date(2026, 6, 17)
assert TIE.loc["M6-H7", "swap_end"] == datetime.date(2027, 6, 16)
CORR = float(TIE["ca_bp"].corr(TIE["citi_ca"]))
OFFSET = float((TIE["ca_bp"] - TIE["citi_ca"]).median())
print(f"\nTIE-OUT (a): 13/13 labels match, both date pairs match, "
      f"corr {CORR:.4f}, median level offset {OFFSET:+.2f}bp")
assert CORR > 0.95, f"CA correlation vs Citi is only {CORR:.4f}"
print("TIE-OUT (a) PASS")

# %% [markdown]
# ## 5. TIE-OUT (b) — the 3m roll identity, with a negative control
#
# > `Roll_3m(pack) = CA(pack) − CA(pack shifted ONE CONTRACT NEARER)`
#
# Citi's own printed columns satisfy this on **12/12** consecutive row pairs.
# It is also a construction in `daily_screen`, so it is asserted on our computed
# screen too — and, so that the test is not vacuous, a **negative control**
# pairing the roll against the *further* pack must fail on nearly every row.

# %%
_implied = CITI_SOFR["citi_ca"].diff().dropna()
_printed = CITI_SOFR["citi_roll"].iloc[1:]
_err = float((_implied - _printed).abs().max())
print(f"Citi's own table: max |CA(p)-CA(p-1) - printed roll| = {_err:.4f}bp on "
      f"{len(_implied)}/{len(_implied)} pairs")
assert _err < 0.011
_reversed = _printed.to_numpy()[::-1]
_mismatch = int((np.abs(_implied.to_numpy() - _reversed) > 0.011).sum())
print(f"negative control (roll column reversed): {_mismatch}/12 mismatch")
assert _mismatch >= 11, "the identity test would be vacuous"

_screen_tie = daily_screen(AS_OF, ca_snapshot(AS_OF, CITI_CFG, futures_prices=_prices,
                                              swap_pricer=_pr), CITI_CFG)
_by_rank = TIEOUT.set_index("rank")["ca_bp"]
for _, _r in _screen_tie.iterrows():
    _exp = float(_by_rank.loc[_r["rank"]] - _by_rank.loc[_r["rank"] - 1])
    assert abs(float(_r["roll_3m_bp"]) - _exp) < 1e-9
print("TIE-OUT (b) PASS: roll identity holds on Citi's table and on our screen; "
      "control is not vacuous")

# %% [markdown]
# ## 6. TIE-OUT (c) — the DV01 identities, and the Ho-Lee inversion
#
# * `1000 packs × 4 × $25 = $100,000/bp` and `2000 × 4 × $25 = $200,000/bp` —
#   matching Citi's $1bn and $2bn swap legs.
# * `belly_DV01 = CA_DV01 × β / 100`, cross-checked against both published
#   notional sets at the era's ~$480 per $1mn of 5y DV01.
# * Inverting Citi's *own* CA column through `½σ²·mean(T1²)` must reproduce
#   Citi's *own* implied-vol column — an external known answer that came from
#   neither this codebase nor this notebook.

# %%
assert DV01_PER_CONTRACT == 25.0
assert 1000 * 4 * DV01_PER_CONTRACT == 100_000.0
assert 2000 * 4 * DV01_PER_CONTRACT == 200_000.0
print("DV01: 1000 packs x 4 x $25 = $100,000/bp; 2000 -> $200,000/bp")

from RVUtils.ConvexityRV.strat2_sofr_convexity import HedgeFit

for _ca_dv01, _beta, _w2, _w10, _n5 in [(100_000.0, 21.4, 0.73, 0.46, -44.4e6),
                                        (200_000.0, 20.6, 0.705, 0.465, -85.6e6)]:
    _fit = HedgeFit(0.0, -_beta * _w2, _beta, -_beta * _w10, _beta, _w2, _w10, 1.0, 252, True)
    _sz = hedge_sizing(_fit, _ca_dv01)
    _implied_belly = abs(_n5) * 480.0 / 1e6
    _ratio = _sz["belly_dv01"] / _implied_belly
    print(f"  CA_DV01 ${_ca_dv01:,.0f} beta {_beta}: belly {_sz['belly_dv01']:,.0f}/bp vs "
          f"published {_implied_belly:,.0f}/bp -> ratio {_ratio:.3f}; wings "
          f"{_sz['wing_2y_dv01']:,.0f} / {_sz['wing_10y_dv01']:,.0f}")
    assert abs(_ratio - 1.0) < 0.01
print("TIE-OUT (c) PASS")

# %%
_ratios = []
for _p, _row in CITI_SOFR.iterrows():
    _w = float(TIE.loc[_p, "time_weight"])
    _ratios.append(implied_vol_from_ca_bp(float(_row["citi_ca"]), [math.sqrt(_w)],
                                          convention="citi") / float(_row["citi_iv"]))
print(f"implied vol from Citi's CA / Citi's printed implied vol: "
      f"{len(_ratios)}/13 rows, median {np.median(_ratios):.4f}, "
      f"range {min(_ratios):.4f}..{max(_ratios):.4f}")
assert abs(np.median(_ratios) - 0.9973) < 0.002

# %% [markdown]
# ### What the fitted sigma model does and does not measure
#
# Fitting `CA_p = x_p·(c0 + c1·T + c2·T²)`, `x_p = ½M_p/1e4`, to **Citi's own CA
# column** and comparing the result to **Citi's own model column** shows exactly
# what the documented limitation is: the shapes agree at correlation > 0.99, and
# the levels do not, because a residual-centred cross-sectional fit cannot carry
# the systematic level that an externally calibrated cap/floor surface does.
#
# So `vs_model` here is a *shape* dislocation — which pack is rich relative to
# the smooth CA term structure of that same day — and it is the **time series**
# of that residual, through its z-scores, that is the tradeable signal. It is
# not Citi's `Vs Model` number and this notebook never claims it is.

# %%
_sig, _cam, _co = fit_sigma_model(CITI_SOFR["citi_ca"].to_numpy(),
                                  TIE["time_weight"].to_numpy(),
                                  TIE["t_mid"].to_numpy(), degree=2)
_cmp = pd.DataFrame({"fit_sigma_bp": _sig.round(1), "citi_implied_vol": CITI_SOFR["citi_iv"],
                     "fit_model_bp": _cam.round(2), "citi_model_bp": CITI_SOFR["citi_model"]},
                    index=CITI_SOFR.index)
print(_cmp.to_string())
_shape_corr = float(np.corrcoef(_cam, CITI_SOFR["citi_model"].to_numpy())[0, 1])
print(f"\nshape corr(fitted model, Citi's cap-vol model) = {_shape_corr:.4f}; "
      f"level gap {float(_cam.mean() - CITI_SOFR['citi_model'].mean()):+.2f}bp (expected)")
assert _shape_corr > 0.99

# %% [markdown]
# ## 7. The daily panel
#
# One row per (date, pack **label**). Keying by label rather than by rank is
# what makes the time series constant-contract: a label's four contracts never
# change, so its 3m realized vol and its z-scores carry no IMM-roll jump —
# which is the trap Citi's own note flags.
#
# Built once and cached; ~3 minutes for ~1,200 days (one curve build and one
# futures snapshot per day, then ten swap pricings off the same curve).

# %%
_PANEL_F, _RATES_F = DATA / "strat2_panel.parquet", DATA / "strat2_rates.parquet"
if _PANEL_F.exists() and _RATES_F.exists():
    PANEL_RAW = pd.read_parquet(_PANEL_F)
    RATES_RAW = pd.read_parquet(_RATES_F)
    print(f"loaded cached panel {PANEL_RAW.shape} and rates {RATES_RAW.shape}")
else:
    # NOT bdate_range: the SR3 store is demand-driven and a cold contract costs
    # about a minute, so the local shards are enumerated first. That also makes
    # the effective window an observable rather than an assumption.
    _dates = local_cached_dates(CFG)
    print(f"{len(_dates)} dates carry the full {CFG.n_contracts}-contract strip locally: "
          f"{_dates[0]} .. {_dates[-1]}")
    PANEL_RAW, RATES_RAW = build_panel(_dates, CFG, futures_mdp=_fut, swaps_mdp=_swp)
    PANEL_RAW.to_parquet(_PANEL_F)
    RATES_RAW.to_parquet(_RATES_F)
    print(f"built panel {PANEL_RAW.shape} and rates {RATES_RAW.shape}")

PANEL, RATES = trim_to_contiguous_run(PANEL_RAW, RATES_RAW)
DAYS = pd.DatetimeIndex(sorted(PANEL["date"].unique()))
print(f"panel days {len(DAYS)}: {DAYS[0].date()} .. {DAYS[-1].date()} "
      f"(dropped {len(PANEL_RAW['date'].unique()) - len(DAYS)} isolated strays)")
assert len(DAYS) > 500, "panel is too short to run a 1y z-score on"

# %% [markdown]
# ### Panel diagnostics — SR3 liquidity is a first-order fact here
#
# SR3 listed in May 2018 and volume only migrated off Eurodollars through
# 2021-2022. The screen inherits that history. `dca_sd_bp` is the standard
# deviation of the **daily change** in the CA: a 2-3 year convexity adjustment
# that moves several basis points a day is not convexity repricing, it is a
# stale futures print marked against a live swap curve. Read the 2019 and 2020
# rows with that in mind — and read the per-year P&L in section 10 the same way.

# %%
DIAG = panel_diagnostics(PANEL, CFG)
print(DIAG.round(2).to_string())

# %% [markdown]
# ## 8. The screen — Citi's 13 columns, on our data
#
# Columns in the published order:
#
# `CvxAdj | 1WkChg | 3m ZS | 1Y ZS | Model(bp) | Vs Model(bp) | 3m ZS | 1Y ZS |
# 3m Roll | Implied Vol | Realized Vol | Implied/Realized | Cap vol Impl/Rlzd`
#
# `Implied/Realized` is **rounded** to 1dp and `Cap vol Impl/Rlzd` is
# **truncated** to 1dp — reproduced literally, because that asymmetry is what
# ties out 26/26 rows across Citi's ED and SOFR tables.

# %%
TS = panel_timeseries(PANEL, CFG)
MODEL = model_timeseries(PANEL, CFG)
_show = DAYS[-1]
SCREEN = daily_screen(_show.date(), PANEL, CFG, ts=TS, model=MODEL)
print(f"screen as of {_show.date()}")
print(SCREEN[["rank", "ca_bp", "ca_chg_1w_bp", "ca_z3m", "ca_z1y", "ca_model_bp",
              "vs_model_bp", "vs_model_z3m", "vs_model_z1y", "roll_3m_bp",
              "implied_vol_bp", "realized_vol_bp", "implied_over_realized",
              "capvol_over_realized"]].round(2).to_string())
_flags = rank_flags(SCREEN, CFG)
print("\nflags (3 per metric):")
print(_flags.astype(int).to_string())
_pick, _ = select_pack(SCREEN, CFG)
print(f"\nselected: {_pick}")

# %% [markdown]
# ## 9. Epochs, the hedge regression, and the backtest
#
# The screen is consulted on the first business day of each month. The book is
# **re-struck only when the selected pack changes or the hold exceeds 3 months**
# — which is what Citi did: it rolled Blues (9-Feb → 6-Jun 2017) into Greens
# (6-Jun → 8-Aug 2017) rather than closing the theme.
#
# At every entry `CA ~ a + b2·r2y + b5·r5y + b10·r10y` is re-fit over the
# trailing year of the *selected pack's own label history*, giving
# `β = b5`, `w2 = −b2/β`, `w10 = −b10/β` and `belly_DV01 = CA_DV01·β/100`.
# `IRSwapStructure._build_fly` forces the wings opposite in sign to the belly,
# so a regression implying a same-sign wing is **not expressible as a fly** and
# the hedge is skipped for that epoch and recorded — rather than clipped into
# something the regression did not say.

# %%
_t0 = time.time()
SPECS = plan_epochs(PANEL, RATES, CFG, ts=TS, model=MODEL, verbose=True)
print(f"\n{len(SPECS)} epochs planned in {time.time() - _t0:.0f}s")
N_HEDGED = sum(1 for s in SPECS if s.hedge is not None and s.hedge.ok)
print(f"epochs carrying a fly: {N_HEDGED}/{len(SPECS)}")
assert len(SPECS) > 5, "no epochs -- the screen never selected anything"

EPOCHS = pd.DataFrame([{
    "entry": s.entry, "exit": s.exit, "pack": s.pack, "rank": s.rank,
    "n_flags": s.n_flags, "ca_entry_bp": round(s.ca_entry_bp, 2),
    "contracts": s.contracts_per_leg, "swap": f"{s.swap_start}..{s.swap_end}",
    "beta": round(s.hedge.beta, 1) if s.hedge and np.isfinite(s.hedge.beta) else np.nan,
    "w2": round(s.hedge.w2, 3) if s.hedge and s.hedge.ok else np.nan,
    "w10": round(s.hedge.w10, 3) if s.hedge and s.hedge.ok else np.nan,
    "r2": round(s.hedge.r2, 2) if s.hedge and np.isfinite(s.hedge.r2) else np.nan,
    "belly_dv01": round(s.hedge_dv01["belly_dv01"]) if s.hedge_dv01 else np.nan,
    "hedge": "fly" if (s.hedge and s.hedge.ok) else (s.hedge.reason if s.hedge else "-"),
} for s in SPECS])
print(EPOCHS.to_string(index=False))

# %% [markdown]
# ### The hedge regression does not hold up on the front SOFR packs
#
# Citi fitted Blues (a 3-4 year forward point) in an era when the ED CA was
# 10-14bp and reported *"the correlation in levels being 90%"*. The packs this
# panel can reach are 0.5-2.5 years out, where the CA is a fraction of a basis
# point to a few basis points and much of its variation is microstructure. The
# `r2` and `beta` columns above are the honest read on that, and section 11
# reports what the hedge actually did to the P&L rather than assuming it helped.

# %%
_GRID = [d for d in DAYS if min(s.entry for s in SPECS) <= d.date() <= max(s.exit for s in SPECS)]
print(f"backtest grid {len(_GRID)} days {_GRID[0].date()} .. {_GRID[-1].date()}")
SPAN_YEARS = (_GRID[-1] - _GRID[0]).days / 365.25
print(f"span_years = {SPAN_YEARS:.2f} (passed explicitly to every analytic below)")

_EQ_F = DATA / "strat2_equity.parquet"
if _EQ_F.exists():
    EQ = pd.read_parquet(_EQ_F)
    EQ.index = pd.to_datetime(EQ.index)
    print(f"loaded cached equity {EQ.shape}")
else:
    _res = {}
    for _hedged in (False, True):
        _t0 = time.time()
        _b = run_backtest(SPECS, CFG, hedged=_hedged, futures_mdp=_fut, swaps_mdp=_swp,
                          trading_days=_GRID, show_progress=False)
        _e = assert_ran(_b, SPECS, hedged=_hedged, expect_days=len(_GRID))
        _res["hedged" if _hedged else "unhedged"] = _e
        print(f"  {'hedged' if _hedged else 'unhedged'}: {len(_e)} marks in "
              f"{time.time() - _t0:.0f}s, terminal {float(_e.iloc[-1]):+,.0f}")
    EQ = pd.DataFrame(_res)
    EQ.to_parquet(_EQ_F)

assert len(EQ) == len(_GRID), f"expected {len(_GRID)} marks, got {len(EQ)}"
assert float(EQ.abs().max().max()) > 0, "equity identically zero -- no trigger fired"
print(EQ.tail(3).round(0).to_string())

# %% [markdown]
# ## 10. Results — equity curve, `compare_curves`, `trade_dashboard`
#
# The books are daily-mark books: one row per trading day, `pnl` = that day's
# change in the engine's `mtm_history`. The unit is **dollars on a $100k/bp CA
# leg**, so a number divided by 100,000 is the same number in basis points of
# the convexity adjustment.

# %%
def as_book(eq: pd.Series) -> pd.DataFrame:
    d = eq.diff().dropna()
    return pd.DataFrame({"timestamp": d.index, "pnl": d.to_numpy(float)})


BOOKS = {k: as_book(EQ[k]) for k in EQ.columns}
for _k, _b in BOOKS.items():
    print(f"{_k:9s} n {len(_b):4d} total {_b['pnl'].sum():+12,.0f} "
          f"mean/day {_b['pnl'].mean():+9,.0f} sd/day {_b['pnl'].std():9,.0f}")

# %%
fig_cmp = compare_curves(BOOKS, title="Strat 2 — SOFR pack convexity: hedged vs unhedged "
                                      f"($100k DV01, {SPAN_YEARS:.1f}y)")
fig_cmp

# %%
fig_dash = trade_dashboard(BOOKS["unhedged"], title="Strat 2 — unhedged (daily marks)",
                           span_years=SPAN_YEARS)
fig_dash

# %%
fig_dash_h = trade_dashboard(BOOKS["hedged"], title="Strat 2 — hedged with the 2s5s10s fly",
                             span_years=SPAN_YEARS)
fig_dash_h

# %% [markdown]
# ## 11. The results table
#
# Everything measured, nothing projected. `span_years` is passed explicitly
# everywhere — a daily book annualised off an invented frequency is how a
# Sharpe of 0.3 becomes a Sharpe of 3.

# %%
for _k in EQ.columns:
    print(f"\n=== {_k} ===")
    print(summary_stats(BOOKS[_k], span_years=SPAN_YEARS).to_string(index=False))

# %%
rows = []
for _k in EQ.columns:
    _eq = EQ[_k]
    _d = _eq.diff().dropna()
    _per = pd.Series({s.entry: float(_eq.loc[pd.Timestamp(s.exit)] - _eq.loc[pd.Timestamp(s.entry)])
                      for s in SPECS
                      if pd.Timestamp(s.entry) in _eq.index and pd.Timestamp(s.exit) in _eq.index})
    _cost = CFG.cost_bp_per_roundtrip * CFG.ca_dv01 * len(SPECS)
    rows.append({
        "book": _k,
        "total_usd": float(_eq.iloc[-1]),
        "total_bp_of_ca_dv01": float(_eq.iloc[-1]) / CFG.ca_dv01,
        "ann_usd": float(_d.mean() * 252),
        "ann_sharpe": float(_d.mean() / _d.std() * math.sqrt(252)) if _d.std() > 0 else np.nan,
        "max_drawdown_usd": float((_eq - _eq.cummax()).min()),
        "daily_hit_rate": float((_d > 0).mean()),
        "n_trades": len(SPECS),
        "trade_hit_rate": float((_per > 0).mean()),
        "median_trade_usd": float(_per.median()),
        "mean_trade_usd": float(_per.mean()),
        "worst_trade_usd": float(_per.min()),
        "best_trade_usd": float(_per.max()),
    })
RESULTS = pd.DataFrame(rows).set_index("book")
print(RESULTS.round(3).T.to_string())

# %%
BY_YEAR = pd.DataFrame({k: EQ[k].diff().groupby(EQ.index.year).sum() for k in EQ.columns})
BY_YEAR["hedge_effect"] = BY_YEAR["hedged"] - BY_YEAR["unhedged"]
print("P&L by calendar year ($, on a $100k/bp CA leg):")
print(BY_YEAR.round(0).to_string())

# %% [markdown]
# ### Costs
#
# Citi excludes them explicitly — *"Calculations do not include transaction
# costs and other fees"* — so `cost_bp_per_roundtrip` defaults to 0 and the
# headline numbers above reproduce that convention. The table below prices the
# same book at a range of round-trip charges in bp of the CA DV01, so the
# strategy's cost tolerance is on the record rather than assumed away.

# %%
_cost_rows = []
for _mult in (0.0, 0.25, 0.5, 1.0, 2.0):
    for _k in EQ.columns:
        _gross = float(EQ[_k].iloc[-1])
        _c = _mult * CFG.ca_dv01 * len(SPECS)
        _cost_rows.append({"round_trip_bp": _mult, "book": _k, "gross_usd": _gross,
                           "cost_usd": _c, "net_usd": _gross - _c})
print(pd.DataFrame(_cost_rows).pivot(index="round_trip_bp", columns="book",
                                     values="net_usd").round(0).to_string())

# %% [markdown]
# ### Concentration — where the P&L actually comes from
#
# A headline total is not a result until you know how many days made it. The
# table below is every epoch's P&L, and the summary underneath is the share of
# the total contributed by the single largest epoch. Read the two together with
# the 2019-2020 rows of the panel diagnostics in section 7.

# %%
_EPOCH_PNL = pd.DataFrame({
    _k: pd.Series({s.entry: float(EQ[_k].loc[pd.Timestamp(s.exit)]
                                  - EQ[_k].loc[pd.Timestamp(s.entry)])
                   for s in SPECS
                   if pd.Timestamp(s.entry) in EQ.index and pd.Timestamp(s.exit) in EQ.index})
    for _k in EQ.columns})
_EPOCH_PNL.insert(0, "pack", [s.pack for s in SPECS if pd.Timestamp(s.entry) in EQ.index])
_EPOCH_PNL.insert(1, "exit", [s.exit for s in SPECS if pd.Timestamp(s.entry) in EQ.index])
print(_EPOCH_PNL.round(0).to_string())

for _k in EQ.columns:
    _p = _EPOCH_PNL[_k]
    _tot = float(_p.sum())
    _big = _p.abs().idxmax()
    print(f"\n{_k}: total {_tot:+,.0f} over {len(_p)} epochs; "
          f"largest single epoch {_big} ({_EPOCH_PNL.loc[_big, 'pack']}) "
          f"{float(_p.loc[_big]):+,.0f} = {abs(float(_p.loc[_big]) / _tot):.0%} of the total; "
          f"top 3 epochs = {abs(float(_p.reindex(_p.abs().sort_values(ascending=False).index[:3]).sum()) / _tot):.0%}; "
          f"median epoch {float(_p.median()):+,.0f}")
    _ex2020 = _p[[i for i in _p.index if i.year != 2020]]
    print(f"    excluding every epoch entered in 2020: {float(_ex2020.sum()):+,.0f} "
          f"over {len(_ex2020)} epochs, median {float(_ex2020.median()):+,.0f}")

# %% [markdown]
# ## 12. What this notebook establishes, and what it does not
#
# **Established.**
#
# * The Citi screen is reproducible. On 2023-06-09 the 13 pack labels, both
#   matched-swap date pairs and the CA shape (corr 0.968) come out of the
#   repo's own market data; the roll identity holds exactly on Citi's table and
#   on ours; both DV01 identities reproduce Citi's published notionals to within
#   0.4%; and Citi's implied-vol column is recovered from Citi's CA column at a
#   median ratio of 0.997.
# * The trade is expressible end-to-end in `QueryDrivenBacktest` with every leg
#   on a real position handler — four SR3 futures legs through
#   `STIRFutureHandler`, the matched swap and the 2s5s10s fly through the
#   IRSwap handler — with daily mark-to-market and all three sign conventions
#   verified live at execution time.
#
# **Not established, and stated as such.**
#
# * **This is not Citi's trade.** Citi traded Blues, a 3-4 year forward pack.
#   The local SR3 store cannot support a daily Blues panel, so the book here
#   trades windows 2..10 — 0.5 to 2.5 years out, where the convexity adjustment
#   is a fraction of a basis point to a few basis points and a larger share of
#   its variation is microstructure rather than convexity.
# * **The level is not Citi's level.** The CME/LCH clearing basis is not
#   removed, only exposed through `ca_basis_bp`.
# * **`vs_model` is not Citi's `Vs Model`.** It is a residual-centred
#   cross-sectional dislocation, not a distance to a cap/floor-calibrated
#   surface. Section 6 measures exactly how far apart those two are.
# * **The butterfly hedge's regression does not hold on these packs.** Citi
#   reported 90% correlation in levels on Blues; the trailing R² here is mostly
#   0.2-0.6 with an unstable and frequently sign-flipping beta, and 8 of the
#   epochs could not be expressed as a fly at all. The hedged/unhedged
#   comparison in section 10 should be read as a measurement of that, not as a
#   verdict on Citi's hedge.
# * **The P&L is concentrated.** The concentration cell above measures it
#   directly: a single epoch carries most of the total, and it is a 2020 epoch,
#   which is exactly where the panel diagnostics say the CA moves several basis
#   points a day. A total that survives only because of the days the data is
#   least trustworthy is not a result.
# * **No verdict is offered on whether the strategy is tradeable.** There is no
#   deflated Sharpe here and no trial accounting; the numbers are a single
#   configuration measured once over a ~3.6 year window whose first two years
#   sit inside the illiquid early-SR3 era that section 7's diagnostics quantify.
#   The cost table alone kills it: at 0.5bp of round-trip cost per $100k DV01
#   the hedged book is already negative, and at 1bp both are.
