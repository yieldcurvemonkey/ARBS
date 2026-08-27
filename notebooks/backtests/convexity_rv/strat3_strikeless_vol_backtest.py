# %% [markdown]
# # Strategy 3 — delta-hedged long-dated forward flatteners ("strikeless vol")
#
# **What is traded.** A DV01-neutral curve flattener between two long-dated
# forward swaps: pay the shorter-dated forward, receive the longer-dated one.
# Citi, *US Rates Vol Lab: Trading long-dated convexity* (Bikbov/Williams,
# 09-May-2019), verbatim:
#
# > "consider 10y10y/20y10y curve flatteners, **structured by receiving 20y10y
# > forward swaps vs paying 10y10y forward swaps, DV01-neutral**."
#
# **Why it is long volatility.**
#
# > "Because convexity is higher at longer maturities, the 20y10y forward
# > should have a greater convexity per a unit of DV01 than 10y10y. As a
# > result, the 10y10y/20y10 flattener must be positively convex."
#
# > "the risk profile of this trade is similar to that of long swaption
# > straddles. In that analogy, the spread between 10y10y and 20y10y rates is
# > akin to implied volatility, i.e. the vega exposure of the trade."
#
# **How the volatility is monetised — this is the whole strategy.**
#
# > "Although we initiate a DV01-neutral flattener, DV01 risks change as the
# > market moves. We therefore delta-hedge the trade by adjusting the notional
# > on the longer leg at each 25bp move in rates."
#
# > "For each pair of forward rates, we enter $100K DV01 of flatteners, rolled
# > every year. We delta-hedge by adjusting the notional on the longer end of
# > the trade at each 25bp move in the longer rate (at market close)."
#
# The PM's version of the identical mechanic (`08-misc-notes-and-pm-chat.md` §1):
#
# > "You just recalc the delta on the trades you do every 25 bp and then resize
# > the notionals back to be dv01 neutral. **Everytime you will be 'taking
# > profit'**. ... That's how you delta hedge and treat 10y10y 20y10y as a vol
# > trade — **I think of it as strikeless vol**."
#
# > "I like looking at **15y5y 20y10y as the pure vega expression** that has a
# > bit less factor exposure than 1010 2010."
#
# ---
#
# ## The objective this notebook is graded against
#
# > "strat 3 is about finding structures that allow us to get **LONG VOL and
# > EARN THETA** via the forward curve structures."
#
# Long gamma is table stakes — every one of these flatteners has it. The thing
# worth finding is a structure that is long gamma **and carries positively**.
# So every screen row and every P&L decomposition below reports **carry
# separately from gamma harvest**, and a book whose total is positive only
# because the market trended is not the same result as one whose gamma bucket
# paid for its own theta. Section 6 keeps those two numbers apart on purpose.
#
# ## Order of operations
#
# ```
#   curves (Citi Velocity, banked, offline)
#        |
#        +-- per-LEG repriced metrics  ------> daily 15-pair SCREEN (constant maturity)
#        |     rate / dv01 / gamma / roll        level, z, carry, breakeven, BE/rv
#        |
#        +-- per-PAIR AGED package  ----------> delta-hedge ledger  ----> TRADE TAPE
#              built once per roll year          resize at each 25bp        |
#              never rebuilt (it must age                                   v
#              or there is no gamma)                    QueryDrivenBacktest, daily MTM
# ```
#
# The screen and the position are deliberately two different objects. The
# screen is a statement about the **market** ("the 20y10y has moved 25bp",
# "this curve is 2 sigma steep") and is priced fresh, constant-maturity, every
# day. The position is an **aged package**: a 20y10y bought today is a 19y10y a
# year later, and that ageing is where the convexity comes from. Rebuilding the
# position constant-maturity each day would reset it to par every morning and
# destroy exactly the P&L this strategy exists to collect.

# %%
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import datetime
import json
import pathlib
import sys
import time

import numpy as np
import pandas as pd

_REPO = pathlib.Path(__file__).resolve().parents[3] if "__file__" in dir() else pathlib.Path.cwd().parents[2]
sys.path.insert(0, str(_REPO))

from BT.data_handler import TimeGrid
from BT.query_actions import AddQueryAction, UnwindPositionsAction
from BT.query_engine import QueryDrivenBacktest
from BT.query_strategy import QueryStrategy
from BT.triggers import DateTrigger, DateTriggerRequirements
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapStructure import IRSwapStructure
from Query.IRSwaps.IRSwapValue import IRSwapValue

import RVUtils.ConvexityRV.strat3_strikeless_vol as S3
from RVUtils.ConvexityRV.curve_ops import payoff_profile
from RVUtils.StrikelessVol.citivelo import stored_dates
from RVUtils.StrikelessVol.costs import FREE
from RVUtils.StrikelessVol.replication import CurvePricer

DATA = _REPO / "notebooks" / "data" / "convexity_rv"
CURVE = "USD-SOFR-1D"
pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 60)

print(f"repo   {_REPO}")
print(f"data   {DATA}  (exists: {DATA.exists()})")
print(f"curve  {CURVE}")

# %% [markdown]
# ## 1. The config
#
# Every knob lives in one frozen dataclass. Edit this cell and re-run; nothing
# below reads anything else. The defaults reproduce Citi's Figure-4 backtest
# specification exactly, on the pair the PM singled out as "the pure vega
# expression".

# %%
CONFIG = S3.Strat3Config(
    # --- WHAT IS TRADED ---------------------------------------------------
    short_leg="15Yx5Y",              # PAID   (shorter-dated forward)
    long_leg="20Yx10Y",              # RECEIVED (longer-dated forward)
    curve_name=CURVE,
    market="USD",
    package_dv01_usd=100_000.0,      # Citi Fig-4 size; the live alerts used $50K

    # --- THE DELTA HEDGE --------------------------------------------------
    hedge_threshold_bp=25.0,         # move in the LONGER rate, at close
    beta=1.0,                        # 1.025 = Citi's Oct-2019 reweight
    resize_mode="neutral",           # "neutral" | "always_decrease"
    roll_months=12,                  # "rolled every year"

    # --- COSTS ------------------------------------------------------------
    cost_multiplier=1.0,             # x the Citi Figure-9 schedule

    # --- ENTRY GATE -------------------------------------------------------
    entry_rule="always",             # always | z | be_ratio | z_and_be | carry
    z_window="3y", z_min=1.0, be_ratio_max=0.80, carry_min_bp=0.0,

    # --- SAMPLE -----------------------------------------------------------
    start=datetime.date(2019, 1, 1),
    end=datetime.date(2026, 8, 14),
)
COSTS = S3.cost_schedule_for(CONFIG.short_leg, CONFIG.long_leg,
                             multiplier=CONFIG.cost_multiplier)
SPAN_YEARS = (pd.Timestamp(CONFIG.end) - pd.Timestamp(CONFIG.start)).days / 365.25

print(json.dumps(CONFIG.to_dict(), indent=1))
print(f"\ncost schedule (Citi Fig 9): initiate {COSTS.initiate_bp}bp, "
      f"hedge {COSTS.hedge_bp}bp, roll {COSTS.roll_bp}bp, x{COSTS.multiplier}")
print(f"span_years {SPAN_YEARS:.2f}")

# %% [markdown]
# ### 1.1 Recipes
#
# ```python
# CITI_HEADLINE = CONFIG.with_(short_leg="10Yx10Y", long_leg="20Yx10Y")
# BEST_FIG4     = CONFIG.with_(short_leg="10Yx10Y", long_leg="25Yx10Y")  # Citi Sharpe 0.35
# OCT19_REWEIGHT= CONFIG.with_(beta=1.025, hedge_threshold_bp=20.0)      # the live alert
# SELF_LIQUID   = CONFIG.with_(resize_mode="always_decrease")            # the PM's variant
# GROSS         = CONFIG.with_(cost_multiplier=0.0)
# CAPACITY      = CONFIG.with_(cost_multiplier=2.0)
# FREE_CONVEXITY= CONFIG.with_(entry_rule="carry", carry_min_bp=0.0)     # long gamma AND paid
# ```

# %% [markdown]
# ## 2. The planted-answer sign test, live
#
# Everything in this notebook depends on one measured convention:
#
# ```
# OUTRIGHT bpv > 0  = PAYER
# CURVE    bpv < 0  = FLATTENER (receive the back leg) = LONG convexity
# ```
#
# Two committed artifacts in the repo say the opposite (`IRSwapQuery.
# _format_struct_kwargs` labels `bpv>0` as "REC"; `IRSwapStructure._build_curve`
# has a comment calling `bpv>0` a flattener), and a regression in
# `resolve_pricable` would silently invert every number below without raising.
# So the convention is re-measured on every execution against a week whose
# answer is known — the 2022-09 CPI selloff moved the USD 5Y about 23bp — and
# the notebook refuses to continue if it has moved.

# %%
def _run_sign_probe(bpv: float) -> float:
    dates = [datetime.date(2022, 9, 12), datetime.date(2022, 9, 13),
             datetime.date(2022, 9, 14), datetime.date(2022, 9, 15)]
    mdp_p = IRSwapsMDP(source="CITIVELO_EXCEL")
    grid = TimeGrid([pd.Timestamp(d) for d in dates])
    q = IRSwapQuery(structure=IRSwapStructure.OUTRIGHT, value=IRSwapValue.NPV,
                    tenor="5Y", curve=CURVE, structure_kwargs={"bpv": bpv},
                    tags=("probe",))
    strat = QueryStrategy(name=f"sign_{bpv:+.0f}", triggers=[
        DateTrigger(DateTriggerRequirements(dates=[dates[0]]),
                    actions=[AddQueryAction(query=q, meta={"tags": ["probe"]})]),
        DateTrigger(DateTriggerRequirements(dates=[dates[-1]]),
                    actions=[UnwindPositionsAction(match_tag="probe", fee=0.0)]),
    ])
    bt = QueryDrivenBacktest(time_grid=grid, strategy=strat, mdp=mdp_p, show_progress=False)
    bt.run()
    return float(pd.Series(bt.mtm_history).iloc[-1])


plus, minus = _run_sign_probe(+100_000.0), _run_sign_probe(-100_000.0)
print(f"+bpv {plus:+,.0f}   -bpv {minus:+,.0f}")
assert plus > 0, "payer must gain in the 2022-09 selloff"
assert abs(plus + minus) < 1e-6 * abs(plus), "buy/sell must mirror -- seam regressed?"
print("SIGN TEST PASS: mirror exact, payer gains")

# The flattener direction, on the structure this notebook actually trades.
_mdp = IRSwapsMDP(source="CITIVELO_EXCEL")
_p22 = _mdp.get_pricer({"curve_name": CURVE, "timestamp": datetime.date(2022, 9, 13),
                        "offline": True})
_q = IRSwapQuery(structure=IRSwapStructure.CURVE, value=IRSwapValue.NPV, curve=CURVE,
                 structure_kwargs={"front_tenor": CONFIG.short_leg,
                                   "back_tenor": CONFIG.long_leg, "bpv": -100_000.0})
_pk, _w = _q.resolve_package(pricer_or_curve=_p22)
_pk = [_p22.resolve_pricable(x, rw) for x, rw in zip(_pk, _w)]
_prof = payoff_profile(_p22, _pk, [-100, -50, -25, 0, 25, 50, 100], horizon_date=None)
print(f"\nflattener payoff on 2022-09-13, bp of package: "
      f"{np.round(_prof / 100_000.0, 2).tolist()}")
assert (np.diff(_prof, 2) > 0).all(), "bpv<0 CURVE is not the convex leg -- sign inverted"
print("CONVEXITY SIGN PASS: bpv<0 CURVE is the long-gamma (flattener) direction")

# %% [markdown]
# ## 3. Data
#
# Two artifacts, both built by `scripts/strat3_build_panels.py` and both pure
# market measurement — no strategy decision is taken in either:
#
# * **`strat3_screen.parquet`** — the daily 15-pair screen, constant maturity,
#   from 2013 (the pre-2019 years exist only to seed the z-score and realized-
#   vol windows; no P&L is earned there).
# * **`strat3_ledgers.parquet`** — the zero-cost unit delta-hedge ledgers, one
#   per (pair, roll_months, threshold, beta, resize_mode), over the P&L window.
#
# Costs are applied downstream from recorded traded RISK, never baked into a
# ledger, so a cost assumption can be changed without re-pricing anything.

# %%
SCREEN = pd.read_parquet(DATA / "strat3_screen.parquet")
LEDGERS = pd.read_parquet(DATA / "strat3_ledgers.parquet")
LEG_PANEL = pd.read_parquet(DATA / "strat3_leg_panel.parquet")

DAYS = [d for d in stored_dates("USD", CONFIG.start, CONFIG.end)]
print(f"screen  {SCREEN.shape}  {SCREEN.index.get_level_values('date').min().date()} .. "
      f"{SCREEN.index.get_level_values('date').max().date()}  "
      f"{SCREEN.index.get_level_values('pair').nunique()} pairs")
print(f"ledgers {LEDGERS.shape}  variants "
      f"{LEDGERS.reset_index()[['roll_months','threshold_bp','beta','resize_mode']].drop_duplicates().shape[0]}")
print(f"P&L window {DAYS[0]} .. {DAYS[-1]}  ({len(DAYS)} business days)")

PAIR_SCREEN = SCREEN.xs(CONFIG.pair_name, level="pair").sort_index()
LEDGER = (LEDGERS.xs((CONFIG.pair_name, CONFIG.roll_months, CONFIG.hedge_threshold_bp,
                      CONFIG.beta, CONFIG.resize_mode),
                     level=("pair", "roll_months", "threshold_bp", "beta", "resize_mode"))
          .sort_index())
print(f"\nactive pair {CONFIG.pair_name}: screen {PAIR_SCREEN.shape}, ledger {LEDGER.shape}, "
      f"{int(LEDGER['n_hedges'].sum())} hedges, {int(LEDGER['n_rolls'].sum())} rolls")

# %% [markdown]
# ## 4. Does the machine give the right answer to a question we already know?
#
# Five checks. Four of them are **external** known answers — numbers printed in
# a Citi note this repo did not produce — and one is the shared regression
# table for the repricing kernel.
#
# **(a) Citi Figure 7**, the entry screen at the close of 2019-05-08: eight
# published curve levels, eight 1y carries, eight daily breakevens and the
# realized vols behind them.
#
# **(b) DV01 neutrality at initiation.** The package's repriced delta must be
# zero — not the analytic annuity's, the repriced one, since that is what the
# legs are sized off.
#
# **(c) The payoff profile must be convex**, and the shared regression table
# for `curve_ops.payoff_profile` must reproduce to the published decimal.
#
# **(d) The sign probe** — already run in section 2.
#
# **(e) Resize mechanics.** After a large move the *un*-resized package must
# carry a non-zero delta of the sign a growing received leg implies.
#
# ### A convention that had to be measured, not assumed
#
# Citi never states how "1y carry" is computed (the note's own gap list). The
# brief nominated `IRSwapValue.CARRY_AND_ROLL_BPS_RUNNING` at horizon 1Y. When
# this notebook was written that was the wrong field and Figure 7 said so; the
# defect has since been fixed at the source:
#
# | measure | corr with Citi's 8 published carries | MAE |
# |---|---|---|
# | repriced 1y roll of the aged package / package DV01 | **+0.991** | **0.35bp** |
# | `CARRY_AND_ROLL_BPS_RUNNING`, horizon 1Y (now) | **+0.991** | **0.34bp** |
# | `CARRY_AND_ROLL_BPS_RUNNING`, horizon 1Y (before 2026-08-27) | −0.136 | 1.28bp |
#
# The query value aged a forward-starting leg by shortening its TAIL instead of
# bringing its START nearer, so a 10Yx10Y aged 1Y became 10Yx9Y rather than
# 9Yx10Y; `Query/IRSwaps/_carry_roll.py` is now the single kernel behind both
# backends. `_query_carry_1y` also asked for the opposite trade direction.
#
# Both are computed and printed below. The repriced roll is still what every
# signal downstream uses; the two agreeing is now the cross-check.

# %%
P0508 = _mdp.get_pricer({"curve_name": CURVE, "timestamp": datetime.date(2019, 5, 8),
                         "offline": True})
FIG7 = S3.screen_frame(P0508, list(S3.CITI_FIG7_SCREEN), asof=datetime.date(2019, 5, 8),
                       include_query_carry=True).set_index("pair")

_pub = pd.DataFrame(
    [{"pair": f"{a}/{b}", "citi_level": v[0], "citi_carry": v[3],
      "citi_be": v[4], "citi_rv": v[5], "citi_be_rv": v[6]}
     for (a, b), v in S3.CITI_FIG7_SCREEN.items()]).set_index("pair")
_rv = (LEG_PANEL["rate_bp"].unstack("leg").diff()
       .rolling(252, min_periods=120).std(ddof=1).loc[pd.Timestamp("2019-05-08")])
FIG7["rlzd_vol_bp"] = [_rv[l] for l in FIG7["long_leg"]]
FIG7["be_over_rv"] = FIG7["be_daily_analytic"] / FIG7["rlzd_vol_bp"]

TIE = FIG7.join(_pub)
TIE["d_level"] = TIE["level_bp"] - TIE["citi_level"]
TIE["d_carry"] = TIE["carry_1y_bp"] - TIE["citi_carry"]
TIE["d_be"] = TIE["be_daily_analytic"] - TIE["citi_be"]
TIE["d_rv"] = TIE["rlzd_vol_bp"] - TIE["citi_rv"]
display(TIE[["level_bp", "citi_level", "d_level",
             "carry_1y_bp", "citi_carry", "d_carry", "carry_query_bp",
             "be_daily_analytic", "be_daily_exact", "citi_be", "d_be",
             "rlzd_vol_bp", "citi_rv", "d_rv",
             "be_over_rv", "citi_be_rv"]].round(3))

from scipy.stats import spearmanr

_ours = TIE["carry_1y_bp"].to_numpy()
_pubc = TIE["citi_carry"].to_numpy()
_qc = TIE["carry_query_bp"].to_numpy()

checks = [
    ("(a) Fig 7 levels within 1.5bp", TIE.d_level.abs().max() < 1.5, TIE.d_level.abs().max()),
    ("(a) Fig 7 carry within 1.0bp", TIE.d_carry.abs().max() < 1.0, TIE.d_carry.abs().max()),
    ("(a) Fig 7 realized vol within 0.3bp", TIE.d_rv.abs().max() < 0.3, TIE.d_rv.abs().max()),
    # The breakeven is sqrt(|carry|), so a 0.3bp carry gap on a pair whose carry
    # is ~0 (15y5y/20y10y: ours -0.01, Citi's -0.31) becomes a ~1.1bp breakeven
    # gap. That is the same single discrepancy as the carry row, amplified --
    # not an independent error -- so the band is set where it actually lands.
    ("(a) Fig 7 breakeven within 1.2bp", TIE.d_be.abs().max() < 1.2, TIE.d_be.abs().max()),
    ("(a) repriced carry corr > 0.95", np.corrcoef(_ours, _pubc)[0, 1] > 0.95,
     np.corrcoef(_ours, _pubc)[0, 1]),
    ("(a) query carry is the WRONG field", np.corrcoef(_qc, _pubc)[0, 1] < 0.5,
     np.corrcoef(_qc, _pubc)[0, 1]),
    ("(a) carry RANK order survives (Spearman)", spearmanr(_ours, _pubc).statistic > 0.95,
     spearmanr(_ours, _pubc).statistic),
    ("(b) package PV01 ~ 0 at initiation",
     FIG7.package_dv01_usd.abs().max() < 1e-6 * CONFIG.package_dv01_usd,
     FIG7.package_dv01_usd.abs().max()),
    ("(c) every pair is long convexity", (FIG7.gamma_usd_bp2 > 0).all(),
     FIG7.gamma_usd_bp2.min()),
    ("(c) repriced gamma == dM/1e4 within 5%", FIG7.gamma_ratio.between(0.95, 1.05).all(),
     f"{FIG7.gamma_ratio.min():.4f}..{FIG7.gamma_ratio.max():.4f}"),
    ("BE analytic vs repriced within 2%",
     (FIG7.be_daily_exact / FIG7.be_daily_analytic).between(0.98, 1.02).all(),
     f"{(FIG7.be_daily_exact/FIG7.be_daily_analytic).min():.4f}.."
     f"{(FIG7.be_daily_exact/FIG7.be_daily_analytic).max():.4f}"),
]
display(pd.DataFrame(checks, columns=["check", "ok", "value"]))
assert all(ok for _, ok, _ in checks), "Citi Figure-7 tie-out FAILED"
print("TIE-OUT (a)/(b)/(c) PASS")

# %% [markdown]
# **Reading the residual.** Every level is uniformly ~0.8bp more negative than
# Citi's and every carry uniformly ~0.4bp less negative. That is a curve-build
# difference, not a convention error: this repo rebuilds a SOFR curve from
# banked par rates while Citi quoted its own. The decision the screen exists to
# make is a **ranking** — which pair is the cheapest convexity — and that
# survives at Spearman 0.98, with the three trades the note actually
# recommended (15y5y/20y10y, 15y5y/20y15y, 20y5y/25y10y) still the three
# best-carrying pairs on our numbers.

# %% [markdown]
# ### 4.1 The shared regression table for the repricing kernel (tie-out c)
#
# `curve_ops.payoff_profile` on the CURVE-query package, 2022-09-13, $100k
# DV01, flattener (`bpv<0`), P&L in bp of package. These are committed
# reference numbers; a change in the query layer's risk-weight resolution would
# move them.

# %%
_shifts = [-250, -200, -150, -100, -50, -25, 0, 25, 50, 100, 150, 200, 250]
_expected = {
    "20Yx5Y/25Yx5Y": [60.0, 33.7, 16.5, 6.4, 1.3, 0.3, 0.0, 0.4, 1.2, 4.2, 8.2, 12.8, 17.5],
    "30Y/50Y": [137.9, 82.1, 44.7, 20.9, 6.9, 2.7, 0.0, -1.4, -1.8, -0.1, 3.9, 9.5, 15.9],
    "10Yx10Y/20Yx10Y": [104.9, 60.0, 29.9, 11.6, 2.3, 0.4, 0.0, 0.9, 2.9, 9.5, 18.7, 29.7, 41.7],
}
_rows = []
for name, want in _expected.items():
    front, back = name.split("/")
    q = IRSwapQuery(structure=IRSwapStructure.CURVE, value=IRSwapValue.NPV, curve=CURVE,
                    structure_kwargs={"front_tenor": front, "back_tenor": back,
                                      "bpv": -100_000.0})
    pk, w = q.resolve_package(pricer_or_curve=_p22)
    pk = [_p22.resolve_pricable(x, rw) for x, rw in zip(pk, w)]
    got = np.round(payoff_profile(_p22, pk, _shifts, horizon_date=None) / 100_000.0, 1)
    _rows.append(pd.Series(got, index=_shifts, name=name))
    assert np.allclose(got, want, atol=0.05), f"{name}: {got.tolist()} != {want}"
display(pd.DataFrame(_rows))
print("REGRESSION TABLE PASS: payoff_profile reproduces the committed values exactly")

# %% [markdown]
# ### 4.2 Resize mechanics (tie-out e)
#
# The 2020 Covid rally, held **unhedged**. The received longer leg's DV01 grows
# faster than the paid shorter leg's, so the package must go net-received —
# long duration, gaining if rates fall further. In the measured convention
# ("positive = gains when rates rise") that means a **negative** residual
# delta. Running the 25bp trigger must take it back out.
#
# The second half of the cell is the mechanic itself over the full year, and it
# is the single most important number in this notebook: the same package, same
# dates, hedged versus not.

# %%
_cm = _mdp.bulk_get_data({"curve_name": CURVE,
                          "timestamps": stored_dates("USD", datetime.date(2020, 1, 2),
                                                     datetime.date(2020, 12, 31)),
                          "offline": True})
_cm = {pd.Timestamp(k): v for k, v in _cm.items() if v is not None and k != "live"}
_ctx = CurvePricer(_cm, S3.forward_pair(CONFIG.short_leg, CONFIG.long_leg),
                   package_dv01_usd=CONFIG.package_dv01_usd)
_d = _ctx.dates()
_rate = pd.Series({d: _ctx.rate(d, "long") * 1e4 for d in _d})

_rally = [d for d in _d if pd.Timestamp("2020-02-19") <= d <= pd.Timestamp("2020-03-09")]
_naked = S3.simulate_strat3(_ctx, _rally, CONFIG.with_(hedge_threshold_bp=1e6), FREE)
_move = _rate[_rally[-1]] - _rate[_rally[0]]
_resid = _naked["package_dv01_usd"].iloc[-1]

_hedged_y = S3.simulate_strat3(_ctx, _d, CONFIG, FREE)
_naked_y = S3.simulate_strat3(_ctx, _d, CONFIG.with_(hedge_threshold_bp=1e6), FREE)

e_checks = [
    ("(e) package starts DV01-neutral", abs(_naked["package_dv01_usd"].iloc[0]) < 1.0,
     _naked["package_dv01_usd"].iloc[0]),
    (f"(e) {_move:+.0f}bp rally builds a NEGATIVE residual delta", _resid < -500.0, _resid),
    ("(e) no hedge fired in the naked run", _naked["n_hedges"].sum() == 0,
     int(_naked["n_hedges"].sum())),
    ("(e) hedging removes >75% of that delta",
     abs(_hedged_y["package_dv01_usd"].loc[_rally[-1]]) < 0.25 * abs(_resid),
     _hedged_y["package_dv01_usd"].loc[_rally[-1]]),
    ("2020 round trip: hedging harvests > $0.5mn", _hedged_y["harvest"].sum() > 0.5e6,
     _hedged_y["harvest"].sum()),
    ("2020: hedged beats unhedged 5x", _hedged_y["total"].sum() > 5 * _naked_y["total"].sum(),
     f"{_hedged_y['total'].sum():,.0f} vs {_naked_y['total'].sum():,.0f}"),
]
display(pd.DataFrame(e_checks, columns=["check", "ok", "value"]))
assert all(ok for _, ok, _ in e_checks), "resize mechanics FAILED"
print(f"\n20y10y rate 2020: start {_rate.iloc[0]:.0f}bp, low {_rate.min():.0f}bp, "
      f"high {_rate.max():.0f}bp, end {_rate.iloc[-1]:.0f}bp")
display(pd.DataFrame({
    "hedged @25bp": _hedged_y[["carry", "harvest", "mtm", "total"]].sum(),
    "never hedged": _naked_y[["carry", "harvest", "mtm", "total"]].sum(),
}).round(0))
print("TIE-OUT (e) PASS")

# %% [markdown]
# **The one-way leg does the opposite, and it is worth saying out loud.** Over
# 2020-02-19..2020-03-09 alone — a monotone rally — the resizes *lose* money:
# each one sells delta the market then keeps rewarding. Long gamma pays for
# **round trips**, not for trends. Any claim that "every resize books a profit"
# is a claim about the entry strike, not about the mark-to-market path.

# %% [markdown]
# ## 5. What this config actually trades — the tape
#
# The trade tape is produced by the same engine that produces the ledger, so
# the two cannot disagree about what happened. Each row is an order the
# `QueryDrivenBacktest` will actually submit.
#
# **How a resize is expressed in the engine.** Citi's backtest adjusts the
# notional of the original off-market swap. A backtest engine holds positions,
# not notionals, so the increment is booked as a separate **at-market swap on
# the aged leg's own effective and maturity dates** — which Citi names as the
# practical implementation of the same trade:
#
# > "we adjust the notional of the initial off-market swap, although
# > **delta-hedging with ATM swaps may be easier for the practical
# > implementation** of this strategy."

# %%
t0 = time.time()
CURVE_MAP = _mdp.bulk_get_data({"curve_name": CURVE, "timestamps": DAYS, "offline": True})
CURVE_MAP = {pd.Timestamp(k): v for k, v in CURVE_MAP.items()
             if v is not None and k != "live"
             and pd.Timestamp(v.reference_date()).date() == pd.Timestamp(k).date()}
print(f"{len(CURVE_MAP)} curves in {time.time()-t0:.0f}s")

TAPE = S3.hedge_schedule(CURVE_MAP, CONFIG)
print(f"\ntape: {len(TAPE)} orders, {TAPE.segment.nunique()} roll segments, "
      f"{(TAPE.kind=='hedge').sum()} hedges")
display(TAPE.groupby("kind").agg(n=("kind", "size"),
                                 mean_abs_bpv=("bpv", lambda s: s.abs().mean())).round(0))
display(TAPE.head(12))

# %% [markdown]
# ## 6. The backtest — QueryDrivenBacktest, daily mark-to-market
#
# The tape goes to the production engine. Signals stay strategy-side (the tape
# is precomputed); the engine owns marks and P&L, and `bt.mtm_history` is a
# **daily** mark of the whole book including open positions.
#
# `QueryDrivenBacktest.run()` swallows exceptions and prints them, so a silently
# failing backtest looks exactly like a flat equity curve. The cell asserts the
# history is non-empty and the right length before anything is plotted.
#
# Costs are charged as a lump on each segment's unwind, at the Citi Figure-9
# schedule applied to the risk actually traded in that segment. That places the
# fee at the segment end rather than as incurred — the total is exact, the
# intra-year path is not, and the ledger comparison below prices it both ways.

# %%
def build_strategy(tape: pd.DataFrame, cfg: S3.Strat3Config, costs) -> QueryStrategy:
    """One DateTrigger per traded date, plus one unwind per roll segment."""
    triggers = []
    adds = tape[tape.kind.isin(("initiate", "roll", "hedge"))]
    for d, day_rows in adds.groupby("date"):
        actions = []
        for _, r in day_rows.iterrows():
            tag = f"s3-seg{int(r.segment)}"
            q = IRSwapQuery(
                structure=IRSwapStructure.OUTRIGHT, value=IRSwapValue.NPV, curve=cfg.curve_name,
                effective_date=r.effective, maturity_date=r.maturity,
                structure_kwargs={"bpv": float(r.bpv)},
                tags=(tag, f"leg-{r.leg}", r.kind),
            )
            actions.append(AddQueryAction(query=q, meta={"tags": [tag, r.kind]}))
        triggers.append(DateTrigger(DateTriggerRequirements(dates=[d]), actions=actions))

    for seg, rows in tape.groupby("segment"):
        # Citi Figure 9 quotes the initiation cost for the PACKAGE, not per leg
        # ("our bid/offer assumptions for 1) initiating $100K DV01-neutral
        # flatteners"), so 0.75bp on a $100k/bp package is $75,000 once -- which
        # is also exactly how the ledger's row-0 charge is defined. Charging it
        # per leg would double-bill every open and every roll, ~$285k over eight
        # segments, and section 6.1 would then read a fee-convention mismatch as
        # a difference between the two trades.
        fee = costs.cost_usd("initiate" if seg == 0 else "roll", cfg.package_dv01_usd)
        fee += sum(costs.cost_usd("hedge", abs(b))
                   for b in rows.loc[rows.kind == "hedge", "bpv"])
        close = rows.loc[rows.kind == "unwind", "date"].iloc[0]
        triggers.append(DateTrigger(
            DateTriggerRequirements(dates=[close]),
            actions=[UnwindPositionsAction(match_tag=f"s3-seg{int(seg)}", fee=float(fee))]))
    return QueryStrategy(name=f"strat3 {cfg.pair_name} @{cfg.hedge_threshold_bp:g}bp",
                         triggers=triggers)


GRID_DAYS = sorted(CURVE_MAP)
t0 = time.time()
BT = QueryDrivenBacktest(time_grid=TimeGrid([pd.Timestamp(d) for d in GRID_DAYS]),
                         strategy=build_strategy(TAPE, CONFIG, COSTS),
                         mdp=_mdp, show_progress=False)
BT.run()
EQUITY = pd.Series(BT.mtm_history).sort_index()
print(f"backtest ran in {time.time()-t0:.0f}s")
assert len(EQUITY) > 0, "mtm_history is EMPTY -- run() swallowed an exception"
assert len(EQUITY) == len(GRID_DAYS), f"{len(EQUITY)} marks for {len(GRID_DAYS)} grid days"
assert np.isfinite(EQUITY.to_numpy()).all(), "non-finite marks in mtm_history"
assert len(BT.portfolio.closed_positions_log) > 0, "nothing ever closed"
print(f"marks {len(EQUITY)}, closed positions {len(BT.portfolio.closed_positions_log)}, "
      f"terminal MTM {EQUITY.iloc[-1]:+,.0f}")

# %% [markdown]
# ### 6.1 Does the engine agree with the ledger?
#
# Two completely separate implementations of the same trade: the aged-package
# ledger (`simulate_strat3` + `CurvePricer`, which reprices the *original*
# off-market swaps) and the `QueryDrivenBacktest` (which books each resize as a
# fresh at-market swap on the same dates and marks the whole book daily).
#
# They should not agree to the dollar — they are different trades in exactly
# the way Citi's own note flags (off-market notional adjustment vs ATM swaps) —
# but they must agree on the level and on the shape, or one of them is wrong.

# %%
LED_NET = LEDGER[["carry", "harvest", "mtm", "cross"]].sum(axis=1) - S3.recost(LEDGER, COSTS)
LED_EQ = LED_NET.cumsum()
STATS = S3.book_stats(LEDGER, costs=COSTS, package_dv01_usd=CONFIG.package_dv01_usd)

_join = pd.DataFrame({"engine": EQUITY, "ledger": LED_EQ}).dropna()
_corr_d = _join.diff().dropna().corr().iloc[0, 1]
_gap = _join.engine.iloc[-1] - _join.ledger.iloc[-1]
display(pd.DataFrame([
    ("terminal engine MTM ($)", _join.engine.iloc[-1]),
    ("terminal ledger net ($)", _join.ledger.iloc[-1]),
    ("gap ($)", _gap),
    ("gap (% of ledger)", 100 * _gap / abs(_join.ledger.iloc[-1])),
    ("corr of DAILY changes", _corr_d),
], columns=["metric", "value"]).round(4))
assert _corr_d > 0.95, f"engine and ledger daily P&L only correlate {_corr_d:.3f}"
print("ENGINE/LEDGER TIE-OUT PASS")

# %% [markdown]
# ## 7. How this config performed
#
# `book_stats` reports Citi's own Figure-4 convention: **Sharpe = mean(daily $)
# / std(daily $) x sqrt(252)**, verified to 2dp against all eight of their
# published columns. That is what makes the number below comparable to their
# 0.05..0.35.
#
# The decomposition is the part that answers the brief. `carry` is the repriced
# roll — the theta line. `harvest` is the P&L of the resizes — the gamma line.
# `mtm` is the curve move on the base position — the vega/direction line. A
# structure that is "long vol and earns theta" needs `harvest > 0` **and**
# `carry >= 0`; anything else is a different trade wearing this one's name.

# %%
_summary = {
    "pair": CONFIG.pair_name,
    "hedge threshold (bp)": CONFIG.hedge_threshold_bp,
    "resize mode": CONFIG.resize_mode,
    "beta": CONFIG.beta,
    "roll (months)": CONFIG.roll_months,
    "days": STATS["n_days"],
    "years": round(STATS["n_days"] / 252.0, 2),
    "n hedges": int(STATS["n_hedges"]),
    "n rolls": int(STATS["n_rolls"]),
    "TOTAL NET ($)": STATS["total_net_usd"],
    "  carry ($)": STATS["carry_usd"],
    "  gamma harvest ($)": STATS["harvest_usd"],
    "  curve mtm ($)": STATS["mtm_usd"],
    "  costs ($)": -STATS["cost_usd"],
    "TOTAL NET (bp of DV01)": STATS["net_bp"],
    "NET EX-DIRECTION ($)": STATS["net_ex_mtm_usd"],
    "NET EX-DIRECTION (bp)": STATS["net_ex_mtm_bp"],
    "avg daily ($)": STATS["avg_daily_usd"],
    "daily vol ($)": STATS["daily_vol_usd"],
    "ANNUALISED SHARPE": STATS["sharpe"],
    "SHARPE EX-DIRECTION": STATS["sharpe_ex_mtm"],
    "daily skew": STATS["skew"],
    "hit rate": STATS["hit_rate"],
    "max drawdown ($)": STATS["max_dd_usd"],
    "worst day ($)": STATS["worst_day_usd"],
    "Citi Fig-4 Sharpe (2013-2019)": S3.CITI_FIG4_SHARPE.get(CONFIG.pair, np.nan),
}
display(pd.Series(_summary).to_frame(CONFIG.pair_name))

_scr = PAIR_SCREEN[(PAIR_SCREEN.index >= pd.Timestamp(CONFIG.start))
                   & (PAIR_SCREEN.index <= pd.Timestamp(CONFIG.end))]
display(pd.Series({
    "mean level (bp)": _scr.level_bp.mean(),
    "mean 1y carry (bp)": _scr.carry_1y_bp.mean(),
    "% days carry >= 0": 100 * (_scr.carry_1y_bp >= 0).mean(),
    "mean gamma ($/bp^2)": _scr.gamma_usd_bp2.mean(),
    "mean daily breakeven (bp)": _scr.be_daily_analytic.mean(),
    "mean 1y realized vol (bp/day)": _scr.rlzd_vol_bp.mean(),
    "mean BE / realized vol": _scr.be_over_rv.mean(),
}).to_frame("ex-ante screen, sample average").round(3))

# %% [markdown]
# ## 8. Charts

# %%
import plotly.io as pio

pio.renderers.default = "plotly_mimetype+notebook_connected"
from BT.trade_dashboard import compare_curves, summary_stats, trade_dashboard

fig = trade_dashboard(BT, title=f"strat3 {CONFIG.pair_name} delta-hedged @ "
                                f"{CONFIG.hedge_threshold_bp:g}bp, ${CONFIG.package_dv01_usd:,.0f} DV01",
                      span_years=SPAN_YEARS)
fig.show()

# %% [markdown]
# ### 8.1 The counterfactual that isolates the strategy
#
# The same aged package on the same dates, hedged at four thresholds and **not
# hedged at all**. The never-hedged book is not in the cached grid (it is not a
# strategy anyone would run), so it is priced here off the curves already
# loaded in section 5. If the delta hedge is where the money is, this chart is
# where that shows.

# %%
def _as_book(series: pd.Series) -> pd.DataFrame:
    """An equity series as the trade-log shape ``compare_curves`` reads."""
    d = series.diff().fillna(series.iloc[0])
    return pd.DataFrame({"timestamp": series.index, "pnl": d.to_numpy()})


def _ledger_over_sample(cfg: S3.Strat3Config) -> pd.DataFrame:
    """Run the ledger engine over the whole sample, one segment per roll."""
    pair = S3.forward_pair(cfg.short_leg, cfg.long_leg, market=cfg.market,
                           curve_name=cfg.curve_name)
    days = sorted(CURVE_MAP)
    frames = []
    for (i, j) in S3.roll_segments(days, cfg.roll_months):
        sd = days[i:j + 1]
        ctx = CurvePricer({d: CURVE_MAP[d] for d in sd}, pair,
                          package_dv01_usd=cfg.package_dv01_usd)
        frames.append(S3.simulate_strat3(ctx, sd, cfg, FREE))
    return S3.stitch_segments(frames)


t0 = time.time()
NEVER = _ledger_over_sample(CONFIG.with_(hedge_threshold_bp=1e6))
print(f"never-hedged counterfactual priced in {time.time()-t0:.0f}s; "
      f"{int(NEVER['n_hedges'].sum())} hedges (must be 0)")
assert NEVER["n_hedges"].sum() == 0
NEVER_STATS = S3.book_stats(NEVER, costs=COSTS, package_dv01_usd=CONFIG.package_dv01_usd)

_books = {"engine (QueryDrivenBacktest)": _as_book(EQUITY),
          f"ledger @{CONFIG.hedge_threshold_bp:g}bp": _as_book(LED_EQ)}
for th in (10.0, 20.0, 40.0):
    if th == CONFIG.hedge_threshold_bp:
        continue
    try:
        led = LEDGERS.xs((CONFIG.pair_name, CONFIG.roll_months, th, CONFIG.beta,
                          CONFIG.resize_mode),
                         level=("pair", "roll_months", "threshold_bp", "beta", "resize_mode"))
    except KeyError:
        continue
    st = S3.book_stats(led.sort_index(), costs=COSTS,
                       package_dv01_usd=CONFIG.package_dv01_usd)
    _books[f"ledger @{th:g}bp"] = _as_book(st["equity"])
_books["NEVER hedged (same package)"] = _as_book(NEVER_STATS["equity"])

fig = compare_curves(_books, title=f"{CONFIG.pair_name}: the delta hedge IS the strategy")
fig.show()

display(pd.DataFrame({
    f"hedged @{CONFIG.hedge_threshold_bp:g}bp": {
        k: STATS[k] for k in ("total_net_usd", "carry_usd", "harvest_usd", "mtm_usd",
                              "cost_usd", "sharpe", "skew", "max_dd_usd", "n_hedges")},
    "never hedged": {k: NEVER_STATS[k] for k in
                     ("total_net_usd", "carry_usd", "harvest_usd", "mtm_usd",
                      "cost_usd", "sharpe", "skew", "max_dd_usd", "n_hedges")},
}).round(3))

# %%
display(summary_stats(BT, span_years=SPAN_YEARS))

# %% [markdown]
# ## 9. Decomposition through time — where the money came from
#
# The three buckets, cumulated. This is the picture the brief asks for: if the
# strategy really is "long vol earning theta", the gamma line rises and the
# carry line does not fall.

# %%
_dec = LEDGER[["carry", "harvest", "mtm"]].cumsum()
_dec["cost"] = -S3.recost(LEDGER, COSTS).cumsum()
_dec["net"] = _dec.sum(axis=1)
display(_dec.iloc[[0, len(_dec) // 4, len(_dec) // 2, 3 * len(_dec) // 4, -1]].round(0))

_yearly = pd.DataFrame({
    "carry": LEDGER["carry"], "harvest": LEDGER["harvest"], "mtm": LEDGER["mtm"],
    "cost": -S3.recost(LEDGER, COSTS),
}).groupby(LEDGER.index.year).sum()
_yearly["net"] = _yearly.sum(axis=1)
_yearly["n_hedges"] = LEDGER.groupby(LEDGER.index.year)["n_hedges"].sum()
display(_yearly.round(0))

import plotly.graph_objects as go

_f = go.Figure()
for col, colour in (("carry", "#ff9f43"), ("harvest", "#3ddc84"),
                    ("mtm", "#4dabf7"), ("cost", "#ff5c5c"), ("net", "#d8dee9")):
    _f.add_trace(go.Scatter(x=_dec.index, y=_dec[col], name=col,
                            line=dict(color=colour, width=3 if col == "net" else 2)))
_f.update_layout(template="plotly_dark", height=520, hovermode="x unified",
                 title=f"{CONFIG.pair_name}: carry (theta) vs harvest (gamma) vs curve mtm",
                 yaxis_title="cumulative $")
_f.show()

# %% [markdown]
# ## 10. Reading this notebook
#
# **The number to look at first is `harvest`, not `net`.** `net` mixes three
# economically different things: the roll the position pays to exist (`carry`),
# the money the resizes book (`harvest`), and where the curve happened to go
# (`mtm`). Only the middle one is the strategy. A flattener that made money
# because the long end flattened is a directional trade that happened to be
# convex; a flattener whose `harvest` paid for its `carry` is the trade Citi
# and the PM are both describing.
#
# **And over this sample the direction was enormous.** The 10y10y/20y10y level
# went from about −14bp in May 2019 to about −56bp in August 2026 — the
# ultra-long forward curve inverted by more than 40bp. A DV01-neutral flattener
# held through that was long the single biggest move in the sample. Every
# headline P&L below therefore comes with `NET EX-DIRECTION` = `carry +
# harvest − costs`, which removes it, and `SHARPE EX-DIRECTION` alongside. Read
# the pair. If the two disagree, the ex-direction number is the one that says
# something about convexity.
#
# **The carry column is the binding constraint, not the Sharpe.** The brief's
# objective is "long vol AND earn theta". Over 2019-2026 the `10y10y/*` family
# bleeds 3.4-4.2bp a year of carry and is positive-carry on ~2% of days; the
# `15y5y/*` and `20y5y/*` families sit near zero and are positive-carry on
# 28-59% of days. That difference is structural (`dM` is the same order for
# both, so the gamma is comparable while the roll is not) and it is what the
# grid-search notebook ranks on.
#
# **A gated book is an approximation.** Section 7 runs always-on. The grid
# notebook's gated cells scale an always-on **aged** ledger by a {0,1} state
# rather than striking a fresh package at each entry, and charges an
# initiation on every flip. That is the same approximation
# `scripts/sv_citivelo_h13.py` documents; it is defensible because the position
# is an aged package while the signal is a market property, but it is not the
# same as a book that re-enters at market.
#
# **The engine and the ledger are different trades on purpose.** The ledger
# resizes the original off-market swap (Citi's backtest convention); the engine
# books each resize as an at-market swap on the same dates (Citi's stated
# practical convention). Section 6.1 measures the gap rather than hiding it.
