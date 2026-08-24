# %% [markdown]
# # GV — the SOFR convexity adjustment against an IMM-dated swap butterfly
#
# Block 4 of the convexity relative-value programme. The brief, verbatim:
#
# > we need to flush out 3m sofr futures convexity adjustment vs swap butterfly
# > (butterflies should be imm dated forewards e.g. USD-SOFR-1D
# > IMM_1x2y/IMM_1x5y/IMM_1x10y FLY RATE which is as of 08/24/2026 IMM_U26
# > 2s5s10s) (need to take care handling the imm roll in the backtest ideally we
# > dont have a position on during the roll/we are flat). i know that a
# > significant tradable edge is here. we can think of swap butterflies as vol
# > proxies in linear space. convexity adjustments is pure gamma. we are
# > essentially trading gamma vs vega here. explore convexity adjustment vs
# > ultra long fwd curves e.g. 10y10y/20y10y or 10y10y/15y10y
#
# and, mid-session:
#
# > i believe the pervious backtest results look bad bc of sizing issues
#
# The search space was frozen in `docs/convexityrv/gv-preregistration.md` BEFORE
# any scoring, with six dated amendments. This notebook re-derives every number
# in the results doc from the two committed panels.
#
# **This is the third pass over the same convexity-adjustment panel** (block 1
# `strat2`, block 3 `cavf`/PR #492, now `gv`). The cumulative-search caveat
# travels with every number below.

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
from dataclasses import dataclass, field
from typing import Sequence, Tuple

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
from plotly.subplots import make_subplots

pio.renderers.default = "plotly_mimetype+notebook_connected"
pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 80)
pd.set_option("display.max_rows", 400)

from RVUtils.ConvexityRV import gv_engine as GE
from RVUtils.ConvexityRV import gv_grid as GG
from RVUtils.ConvexityRV import gv_signals as GS
from RVUtils.ConvexityRV import gv_sizing as S
from RVUtils.ConvexityRV import gv_universe as U

print(f"pandas {pd.__version__}   numpy {np.__version__}")

# %% [markdown]
# ## CONFIG
#
# Every knob, with why it is set where it is. Nothing below this cell reads a
# hard-coded constant that is not here or in the pre-registration.

# %%
@dataclass(frozen=True)
class Config:
    #: Panel window. 1,409 dates; the CA panel's own span.
    start: str = "2021-01-04"
    end: str = "2026-08-21"

    #: Where the two committed panels live. Both are gitignored and
    #: regenerable: `_p2_build_panel.py` (~36 min) and block 3's
    #: `_cavf_backfill_ca.py` (~4 min).
    data_dir: str = "../../data/convexity_rv"

    #: USD per bp of the convexity adjustment. Scaling this cannot change a
    #: Sharpe -- only the RELATIVE size of the two legs can, which is why the
    #: block is about hedge ratios and not about this number.
    ca_dv01: float = 100_000.0

    #: Roll blackout half-widths, business days. The union of the two MEASURED
    #: roll clocks is {IMM-1, IMM}: the CA rank map advances ON the IMM date and
    #: an IMM_k swap leg advances the business day BEFORE. The buffer is
    #: declared, not fitted.
    blackout_pre_bd: int = 3
    blackout_post_bd: int = 1

    #: Signal thresholds. Two-sided; z_entry 2.0 is the declared primary and
    #: 1.5/2.5 are run on the finalists only, as a sensitivity, not as trials.
    z_entry: float = 2.0
    z_exit: float = 0.5
    max_hold_bd: int = 63
    z_window: int = 252

    #: Fills lag decisions by one mark. exec_lag_bd=0 is the same-day
    #: diagnostic and MUST inflate the hit rate -- that gap is the mark-noise
    #: harvest, and it has a known-answer test.
    exec_lag_bd: int = 1

    #: Cost sweep, per leg, round trip, on that leg's own DV01.
    cost_mults: Tuple[float, ...] = (0.0, 0.5, 1.0, 2.0)

    #: Declared trial counts, for the null bars.
    n_trials_headline: int = 12
    n_trials_grid: int = 298
    n_trials_with_a5: int = 304

    #: The burn-in the denoising half-lives are fitted on, then frozen. A
    #: trailing fit would make the filter time-varying; a full-sample fit would
    #: be look-ahead.
    burn_in_bd: int = 252


CFG = Config()
DATA = pathlib.Path(CFG.data_dir)
assert DATA.exists(), f"panel directory {DATA.resolve()} is missing"
print(CFG)

# %%
CA = pd.read_parquet(DATA / "cavf_ca_panel.parquet")
LEGS = pd.read_parquet(DATA / "p2_legs.parquet")
LEGS.index = pd.to_datetime(LEGS.index)
IDX = CA.index.intersection(LEGS.index)
CA, LEGS = CA.loc[IDX], LEGS.loc[IDX]
SPAN_Y = (IDX[-1] - IDX[0]).days / 365.25
ALL = list(U.PRIMARY_STRUCTURES) + list(U.SECONDARY_STRUCTURES)
print(f"CA panel {CA.shape}   leg panel {LEGS.shape}")
print(f"{len(IDX)} common dates {IDX.min().date()}..{IDX.max().date()} "
      f"({SPAN_Y:.2f} years)")
assert len(IDX) > 1_300, "the panels do not overlap as expected"

# %% [markdown]
# ## Sign probe — every convention this block can silently get wrong
#
# Each assertion below is a convention that has already cost this package a
# wrong number somewhere. They run against live objects, not against comments.

# %%
# 1. The quoted fly and curve conventions, tied out to the timeseries layer.
fly_ours = U.leg_series(LEGS, "immF_2s5s10s")
fly_theirs = LEGS["USD-SOFR-1D IMM_1x2y/IMM_1x5y/IMM_1x10y FLY RATE"]
j = pd.concat([fly_ours.rename("ours"), fly_theirs.rename("theirs")],
              axis=1).dropna()
assert float((j["ours"] - j["theirs"]).abs().max()) < 1e-8
print(f"FLY RATE  = (2*belly - front - back)*100   max|diff| "
      f"{float((j['ours'] - j['theirs']).abs().max()):.10f} over {len(j)} dates")

cur_ours = U.leg_series(LEGS, "le_10y10y_20y10y")
cur_theirs = LEGS["USD-SOFR-1D 10y10y/20y10y CURVE RATE"]
j2 = pd.concat([cur_ours.rename("ours"), cur_theirs.rename("theirs")],
               axis=1).dropna()
assert float((j2["ours"] - j2["theirs"]).abs().max()) < 1e-8
print(f"CURVE RATE = (back - front)*100            max|diff| "
      f"{float((j2['ours'] - j2['theirs']).abs().max()):.10f} over {len(j2)} dates")

# 2. A fly quoted 2b-f-k costs FOUR times its quoted DV01; a curve costs two.
assert U.leg_cost_dv01("immF_2s5s10s", 10_000.0) == 40_000.0
assert U.leg_cost_dv01("le_10y10y_20y10y", 10_000.0) == 20_000.0
print("fly charged DV01 = 4x quoted;  curve = 2x quoted")

# 3. Direction rides the futures RISK WEIGHT with contracts kept positive.
_sp = GE.spec_from_episode(structure="BLUES", leg_id="immM_2s5s10s", side=-1,
                           entry=IDX[600].date(), exit=IDX[640].date(),
                           beta_entry=0.25, ca_dv01=CFG.ca_dv01)
_qs = GE.build_trade_queries(_sp)
_fut = [q for q in _qs if type(q).__name__ == "STIRFutureQuery"]
assert all(q.structure_kwargs["contracts"] > 0 for q in _fut)
assert all(q.structure_kwargs["risk_weights"] == [+1.0] for q in _fut)
_swap = [q for q in _qs if type(q).__name__ == "IRSwapQuery"][0]
assert _swap.structure_kwargs["bpv"] == +CFG.ca_dv01
print(f"side=-1 (short the CA): {len(_fut)} futures legs LONG at "
      f"{_fut[0].structure_kwargs['contracts']} contracts each, matched swap "
      f"PAYER at bpv {_swap.structure_kwargs['bpv']:+,.0f}")

# 4. The engine's fly bpv is TWICE the quoted leg DV01.
assert _qs[-1].structure_kwargs["bpv"] == 2.0 * _sp.leg.leg_dv01_signed
print(f"quoted leg DV01 {_sp.leg.leg_dv01_signed:+,.0f}/bp  ->  belly bpv "
      f"{_qs[-1].structure_kwargs['bpv']:+,.0f}")

# 5. A negative beta FLIPS the hedge; it does not shrink it.
_neg = GE.spec_from_episode(structure="BLUES", leg_id="immM_2s5s10s", side=-1,
                            entry=IDX[600].date(), exit=IDX[640].date(),
                            beta_entry=-0.25, ca_dv01=CFG.ca_dv01)
assert _neg.leg.leg_dv01_signed == -_sp.leg.leg_dv01_signed
print("beta -0.25 flips the leg:  "
      f"{_sp.leg.leg_dv01_signed:+,.0f} -> {_neg.leg.leg_dv01_signed:+,.0f}")

# %% [markdown]
# ## Known-answer tie-out
#
# Three anchors, each against something computed outside this block.

# %%
# A. The copied CA panel is re-priced through the production TB path.
CERT = json.loads((DATA / "p2_certification.json").read_text()) \
    if (DATA / "p2_certification.json").exists() else {}
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from TB.IRSwapsTB import IRSwapsTB

_rng = np.random.default_rng(20260824)
_sample = sorted(pd.DatetimeIndex(_rng.choice(IDX, size=4, replace=False)))
_tb = IRSwapsTB(IRSwapsMDP(source="citivelo_excel_rl"), show_tqdm=False)
_rows = []
for _d in _sample:
    _got = _tb.sfr_cvx_adj(["GREENS", "BLUES", "GOLDS"], _d.date(), _d.date())
    for _lab in ("GREENS", "BLUES", "GOLDS"):
        _c = U.ca_col(_lab)
        _rows.append({"date": _d.date(), "label": _lab,
                      "panel": float(CA.loc[_d, _c]),
                      "fresh": float(_got[_c].iloc[0])})
_tb.close()
TIE = pd.DataFrame(_rows)
TIE["diff"] = TIE["fresh"] - TIE["panel"]
print(TIE.round(6).to_string(index=False))
assert float(TIE["diff"].abs().max()) < 1e-6, "the copied panel disagrees"
print(f"\npanel confirmed: max |fresh - panel| = "
      f"{float(TIE['diff'].abs().max()):.10f} bp over {len(TIE)} cells")

# %%
# B. The Ho-Lee kernel round-trips, and its vega equals a finite difference.
from RVUtils.ConvexityRV.holee import pack_ca_bp, pack_time_weight

_t1s = [3.25, 3.50, 3.75, 4.00]
_w = pack_time_weight(_t1s)
_ca = pack_ca_bp(118.0, _t1s)
_back = S.ca_implied_vol_bp(pd.Series([_ca]), pd.Series([_w])).iloc[0]
assert abs(_back - 118.0) < 1e-9
_h = 1e-4
_fd = (pack_ca_bp(118.0 + _h, _t1s) - pack_ca_bp(118.0 - _h, _t1s)) / (2 * _h)
_an = S.ca_vega_bp_per_bp(pd.Series([118.0]), pd.Series([_w])).iloc[0]
assert abs(_an - _fd) < 1e-6 * abs(_fd)
print(f"sigma 118.0 bp/yr, w = mean(T1^2) = {_w:.4f}  ->  CA {_ca:.4f} bp")
print(f"round trip back to sigma: {_back:.10f}")
print(f"vega analytic {_an:.6f}  vs finite difference {_fd:.6f}  bp per bp/yr")

# C. NEGATIVE CONTROL that must fail: the textbook T1*T2 form is NOT Citi's.
_hull_w = pack_time_weight(_t1s, convention="hull")
assert abs(_hull_w - _w) > 0.5, "the two conventions must differ materially"
print(f"negative control -- Hull T1*T2 weight {_hull_w:.4f} vs Citi T1^2 "
      f"{_w:.4f}: a {100 * (_hull_w / _w - 1):.1f}% difference, which is why "
      "the convention is a named constant and not a default")

# %% [markdown]
# ## 1. The mark, before the trade
#
# `observed = true(random walk) + iid noise` inverts from the first-order
# autocorrelation of the daily change: `AC1 = −ν/(τ+2ν)`, bounded below by −0.5
# and attaining it only when `τ = 0`. The half-life below is the steady-state
# Kalman gain of that model — for a random walk observed with noise, the optimal
# filter **is** an EWMA — fitted on the first 252 dates and then frozen.

# %%
NOISE = S.fit_denoise_halflives(CA, [U.ca_col(l) for l in ALL],
                                burn_in=CFG.burn_in_bd)
NOISE.index = [c.split()[1] for c in NOISE.index]
HL = {U.ca_col(k): float(v) for k, v in NOISE["halflife_bd"].items()}
show = NOISE[["ac1_burn", "ac1_full", "sigma_true_burn", "sigma_noise_burn",
              "noise_ratio_burn", "noise_ratio_full", "snr_burn",
              "halflife_bd", "pure_noise_full"]]
print(show.round(4).to_string())
print("\nWHITES and REDS sit AT the -0.5 pure-noise bound on the full sample: "
      "their daily marks carry no measurable signal. They are demoted to the "
      "secondary tier rather than excluded (amendment A2), because the -0.5 "
      "reading is a full-sample statistic and the burn-in reading is not.")

# %%
_f = go.Figure()
for _lab in ("GREENS", "BLUES", "GOLDS", "WHITES", "REDS"):
    _f.add_trace(go.Scatter(x=IDX, y=CA[U.ca_col(_lab)], name=_lab, mode="lines"))
_f.update_layout(title="SOFR pack convexity adjustment, 2021-2026 "
                       "(constant rank, raw marks)",
                 yaxis_title="bp", height=430,
                 legend=dict(orientation="h", y=1.08))
_f.show()

# %% [markdown]
# ## 2. The two roll clocks, and what they are worth
#
# The CA rank map advances **on** the IMM date; an `IMM_k` swap leg advances the
# business day **before** (`resolve_imm_token` searches from `d + 1 day`). Over
# 1,409 dates each produces 22 roll dates and **none coincide**, so a blackout
# on either clock alone leaves the other jumping unhedged.

# %%
ROLLS_CA = U.ca_roll_dates(IDX)
ROLLS_LEG = U.leg_roll_dates(IDX)
BO = U.blackout_mask(IDX, pre_bd=CFG.blackout_pre_bd,
                     post_bd=CFG.blackout_post_bd)
SEGS = U.roll_segments(IDX, pre_bd=CFG.blackout_pre_bd,
                       post_bd=CFG.blackout_post_bd)
_seglen = [IDX.get_loc(b) - IDX.get_loc(a) + 1 for a, b in SEGS]
assert len(ROLLS_CA) == len(ROLLS_LEG) == 22
assert not (set(ROLLS_CA) & set(ROLLS_LEG))
print(f"CA rolls {len(ROLLS_CA)}   IMM_k leg rolls {len(ROLLS_LEG)}   "
      f"in common {len(set(ROLLS_CA) & set(ROLLS_LEG))}")
print(f"blackout {int(BO.sum())}/{len(IDX)} dates ({100 * BO.mean():.2f}%), "
      f"{len(SEGS)} tradeable segments, median {int(np.median(_seglen))} bd "
      f"(min {min(_seglen)}, max {max(_seglen)})")

_rows = []
_rs = set(ROLLS_CA)
for _lab in ALL:
    _d = CA[U.ca_col(_lab)].dropna().diff().dropna()
    _on = _d[[t in _rs for t in _d.index]]
    _off = _d[[t not in _rs for t in _d.index]]
    _t = float(_on.mean() / (_on.std(ddof=1) / np.sqrt(len(_on))))
    _rows.append({"structure": _lab, "n_roll": len(_on),
                  "mean_on_roll_bp": _on.mean(), "t": _t,
                  "abs_on": _on.abs().mean(), "abs_off": _off.abs().mean(),
                  "ratio": _on.abs().mean() / _off.abs().mean()})
ROLL = pd.DataFrame(_rows).set_index("structure")
print()
print(ROLL.round(3).to_string())
print("\nA long-CA book held through every roll books +0.95 bp per quarter on "
      "BLUES for free -- 22 rolls on a structure whose entire level is 9 bp.")

# %% [markdown]
# ## 3. The roll jump IS the theta
#
# `w = mean_i(T1_i²)` and every `T1_i` shortens with calendar time, so
# `dw/dt = −2·mean_i(T1_i)` and
#
# $$\frac{d\,\mathrm{CA}_{bp}}{dt} = -\frac{\sigma_{bp}^{2}\cdot \overline{T_1}}{10^{4}}\quad\text{bp per year.}$$
#
# One quarter of that decay, against the measured roll jump, is the same number.

# %%
_rows = []
for _lab in ALL:
    _ca = CA[U.ca_col(_lab)].dropna()
    _w = U.time_weight_series(_ca.index, _lab)
    _t1m = U.mean_t1_series(_ca.index, _lab)
    _nv = LEGS[GG.vol_bench_col(_lab)].astype(float).reindex(_ca.index)
    _theta = S.ca_theta_bp_per_year(_nv, _t1m)
    _rows.append({
        "structure": _lab, "bench": GG.VOL_BENCH[_lab],
        "ca_mean_bp": _ca.mean(), "ca_sd_bp": _ca.std(ddof=1),
        "w_mean": _w.mean(), "t1_mean": _t1m.mean(),
        "sigma_ca_bp": S.ca_implied_vol_bp(_ca, _w).mean(),
        "sigma_bench_bp": _nv.mean(),
        "ca_neg_frac": float((_ca <= 0).mean()),
        "vega_bp_per_bpyr": S.ca_vega_bp_per_bp(_nv, _w).mean(),
        "theta_bp_per_month": _theta.mean() / 12.0,
        "theta_bp_per_quarter": _theta.mean() / 4.0,
        "roll_jump_bp": ROLL.loc[_lab, "mean_on_roll_bp"]})
VT = pd.DataFrame(_rows).set_index("structure")
VT["theta_vs_jump"] = -VT["roll_jump_bp"] / VT["theta_bp_per_quarter"]
print(VT.round(4).to_string())
for _lab in ("GREENS", "BLUES", "GOLDS"):
    assert 0.9 < VT.loc[_lab, "theta_vs_jump"] < 1.2, _lab
_ratios = " / ".join(f"{VT.loc[_l, 'theta_vs_jump']:.3f}"
                     for _l in ("GREENS", "BLUES", "GOLDS"))
print("\nGREENS / BLUES / GOLDS: measured roll jump divided by a quarter of the "
      f"analytic theta = {_ratios}. They are the same quantity. A roll blackout "
      "therefore leaves the decay one-sided, and a two-sided book acquires a "
      "systematic short-CA CARRY that is not alpha.")

# %% [markdown]
# ## 4. Is a swap butterfly a volatility proxy at all?
#
# This is the brief's premise, and it is testable. `vega_match` divides by
# `∂leg/∂σ`, so a noise-sized slope there is an *unbounded* hedge, not a small
# one. The regression is run with **level and slope controls**, because the CA's
# vega `σ·w/1e4` is a pure volatility derivative by construction and a fly that
# loads on level and not on vol is a duration bet wearing a vol costume.

# %%
LEVEL = LEGS[GG.LEVEL_COL].astype(float)
SLOPE = (LEGS[GG.SLOPE_COLS[1]].astype(float)
         - LEGS[GG.SLOPE_COLS[0]].astype(float)) * 100.0

_rows = []
for _leg_id, _spec in U.LEGS.items():
    _structs = U.PRIMARY_STRUCTURES if _spec.start == "immM" else ("BLUES",)
    for _st in _structs:
        _lg = U.leg_series(LEGS, _leg_id, _st).dropna()
        _nv = LEGS[GG.vol_bench_col(_st)].astype(float).reindex(_lg.index)
        _j = pd.concat([_lg.rename("y"), _nv.rename("x")], axis=1).dropna()
        _r = float(_j["y"].corr(_j["x"]))
        _b = float(_j["y"].cov(_j["x"]) / _j["x"].var(ddof=1))
        _bc, _tc, _pr2 = S.rolling_vol_beta_controlled(
            _lg, _nv, LEVEL, SLOPE, window=len(_lg), min_periods=250)
        _bcr, _tcr, _pr2r = S.rolling_vol_beta_controlled(
            _lg, _nv, LEVEL, SLOPE, window=252)
        _gate = ((_tcr.abs() >= S.VOL_BETA_T_MIN)
                 & (_pr2r >= S.VOL_BETA_PARTIAL_R2_MIN))
        _rows.append({
            "leg_id": _leg_id, "struct": _st if _spec.start == "immM" else "-",
            "leg_sd_bp": float(_lg.std(ddof=1)),
            "beta_raw_lvl": _b, "r2_raw_lvl": _r ** 2,
            "beta_ctrl": float(_bc.dropna().iloc[-1]),
            "t_ctrl": float(_tc.dropna().iloc[-1]),
            "partial_r2": float(_pr2.dropna().iloc[-1]),
            "gate_full": bool((abs(float(_tc.dropna().iloc[-1])) >= S.VOL_BETA_T_MIN)
                              and (float(_pr2.dropna().iloc[-1])
                                   >= S.VOL_BETA_PARTIAL_R2_MIN)),
            "roll_gate_pass": float(_gate[_tcr.notna()].mean())})
VOLPROXY = pd.DataFrame(_rows)
print(VOLPROXY.round(4).to_string(index=False))
print(f"\nlegs clearing the controlled partial-R2 gate ({S.VOL_BETA_PARTIAL_R2_MIN}) "
      f"at full sample: {int(VOLPROXY['gate_full'].sum())}/{len(VOLPROXY)}; "
      f"median rolling gate-pass {VOLPROXY['roll_gate_pass'].median():.3f}")
print("\nThe RAW level relation is strong and correctly signed -- "
      "10y10y/20y10y on ATMF nvol has R2 "
      f"{float(VOLPROXY.loc[VOLPROXY['leg_id'] == 'le_10y10y_20y10y', 'r2_raw_lvl'].iloc[0]):.3f} "
      "with a NEGATIVE beta, i.e. a flatter long end IS higher vol, which is "
      "the desk's own framing. It is a co-trend, and a hedge ratio needs an "
      "incremental response.")

# %%
_f = make_subplots(specs=[[{"secondary_y": True}]])
_f.add_trace(go.Scatter(x=IDX, y=U.leg_series(LEGS, "le_10y10y_20y10y"),
                        name="10y10y/20y10y curve, bp"), secondary_y=False)
_f.add_trace(go.Scatter(x=IDX, y=LEGS["USD-SOFR-1D 10Yx10Y STRADDLE BUY ATMF NVOL"],
                        name="10Yx10Y ATMF nvol, bp/yr"), secondary_y=True)
_f.update_layout(title="The raw co-trend the premise rests on "
                       f"(level R2 {float(VOLPROXY.loc[VOLPROXY['leg_id'] == 'le_10y10y_20y10y', 'r2_raw_lvl'].iloc[0]):.2f}, "
                       "controlled partial R2 "
                       f"{float(VOLPROXY.loc[VOLPROXY['leg_id'] == 'le_10y10y_20y10y', 'partial_r2'].iloc[0]):.3f})",
                 height=420, legend=dict(orientation="h", y=1.10))
_f.show()

# %% [markdown]
# ## 5. THE SIZING ANSWER
#
# The objection was that the previous results looked bad because of sizing.
# Scaling a whole book cannot change its Sharpe, so the objection can only be
# about the **relative** size of the two legs. It is right, and here is the
# size of the error.

# %%
_rows = []
for _st in U.PRIMARY_STRUCTURES:
    _ca = CA[U.ca_col(_st)].dropna()
    _w = U.time_weight_series(_ca.index, _st)
    _nv = LEGS[GG.vol_bench_col(_st)].astype(float).reindex(_ca.index)
    _dn = S.denoise(_ca, HL[U.ca_col(_st)])
    for _leg_id in U.LEGS:
        _lg = U.leg_series(LEGS, _leg_id, _st).reindex(_ca.index)
        _inp = S.SizingInputs(ca=_ca, ca_denoised=_dn, leg=_lg, nvol=_nv, w=_w,
                              level=LEVEL.reindex(_ca.index),
                              slope=SLOPE.reindex(_ca.index),
                              window=CFG.z_window)
        _o = {}
        for _rule in S.SIZING_RULES:
            _b, _ok = S.sizing_beta(_rule, _inp)
            _bb = _b.where(_ok)
            _o[_rule] = float(_bb.abs().median()) if _bb.notna().any() else np.nan
            _o[_rule + "_gate"] = float(_ok.mean())
        _rows.append({"structure": _st, "leg_id": _leg_id,
                      "beta_lvl": _o["beta_lvl"], "beta_chg": _o["beta_chg"],
                      "vega_match": _o["vega_match"], "vol_ratio": _o["vol_ratio"],
                      "vega_gate_pass": _o["vega_match_gate"],
                      "dv01_incumbent": _o["beta_lvl"] * CFG.ca_dv01,
                      "dv01_vega_matched": _o["vega_match"] * CFG.ca_dv01,
                      "ratio": _o["vega_match"] / _o["beta_lvl"]
                      if _o["beta_lvl"] else np.nan})
SIZING = pd.DataFrame(_rows)
print(SIZING.round(4).to_string(index=False))
print("\nmedian |beta| over all (structure, leg) pairs:")
print(SIZING[["beta_lvl", "beta_chg", "vega_match", "vol_ratio"]]
      .median().round(4).to_string())
print(f"\nvega-matched / incumbent hedge notional: median "
      f"{SIZING['ratio'].median():.2f}x, range "
      f"{SIZING['ratio'].min():.2f}x .. {SIZING['ratio'].max():.2f}x")
print(f"BUT the vega_match gate refuses "
      f"{100 * (1 - SIZING['vega_gate_pass']).median():.0f}% of days at the "
      "median cell -- the fix is UNDEFINED where the leg has no measurable "
      "vega, which is the same finding as section 4 arriving from the other "
      "direction. `vol_ratio` is the tractable rule of the same size.")

# %%
_m = SIZING.melt(id_vars=["structure", "leg_id"],
                 value_vars=["beta_lvl", "beta_chg", "vol_ratio", "vega_match"],
                 var_name="rule", value_name="beta")
_f = go.Figure()
for _r in ("beta_lvl", "beta_chg", "vol_ratio", "vega_match"):
    _s = _m[_m["rule"] == _r]
    _f.add_trace(go.Box(y=_s["beta"], name=_r, boxpoints="all", jitter=0.4))
_f.update_layout(title="Hedge ratio by declared sizing rule, all 21 "
                       "(structure x leg) pairs",
                 yaxis_title="|beta|, bp of CA per bp of leg", height=420)
_f.show()

# %% [markdown]
# ## 6. The declared grid — 298 cells

# %%
CELLS = GG.declared_cells()
assert len(CELLS) == CFG.n_trials_grid
assert sum(c.headline for c in CELLS) == CFG.n_trials_headline
RES = GG.run_grid(CELLS, CA, LEGS, halflives=HL, ca_dv01=CFG.ca_dv01)
ST = GG.grid_stats_frame(RES, span_years=SPAN_Y)
EP = pd.DataFrame([
    {"cell_id": r.spec.cell_id, "entry": e.entry, "exit": e.exit,
     "side": e.side, "beta": e.beta_entry, "ca_dv01": e.ca_dv01,
     "reason": e.exit_reason, "pnl_usd": p}
    for r in RES for e, p in zip(r.episodes, r.per_episode_usd)])
print(f"{len(CELLS)} cells, {len(EP)} episodes")
print(f"exit reasons: {EP['reason'].value_counts().to_dict()}")
print(f"\n{100 * (EP['reason'] == 'segment_end').mean():.0f}% of episodes are "
      "force-closed by the roll blackout rather than by the signal -- the "
      "first sign that the trade cannot converge inside a roll-flat window.")

# %%
HEAD = ST[ST["headline"]].copy()
print("THE HEADLINE 12 -- the brief's own trade at the incumbent sizing and at "
      "the fix:\n")
print(HEAD[["structure", "leg_id", "sizing", "n_episodes", "mean_abs_beta",
            "mean_leg_dv01", "gate_refusal_frac", "hit_rate", "net_0.0",
            "sharpe_0.0", "net_1.0", "carry_usd", "residual_usd"]]
      .sort_values(["structure", "leg_id", "sizing"]).round(3).to_string(index=False))
print("\nFive of the six vega_match headline cells produce ZERO episodes: the "
      "gate refuses 83-100% of days. The fix cannot be evaluated on its own "
      "terms, and that is the answer to the sizing objection.")

# %%
PRIM = ST[(ST["tier"] == "primary") & (ST["signal"] == "z_resid")]
BYRULE = PRIM.groupby("sizing").agg(
    n_cells=("cell_id", "size"),
    med_net_0=("net_0.0", "median"), med_net_1=("net_1.0", "median"),
    med_sharpe_0=("sharpe_0.0", "median"), max_sharpe_0=("sharpe_0.0", "max"),
    med_episodes=("n_episodes", "median"), med_beta=("mean_abs_beta", "median"),
    med_leg_dv01=("mean_leg_dv01", "median"),
    med_gate_refusal=("gate_refusal_frac", "median"))
print("BY SIZING RULE (primary structures, z_resid):\n")
print(BYRULE.round(3).to_string())
_none = float(BYRULE.loc["none", "med_sharpe_0"])
_lvl = float(BYRULE.loc["beta_lvl", "med_sharpe_0"])
_vr = float(BYRULE.loc["vol_ratio", "med_sharpe_0"])
print(f"\nNo hedge ({_none:.3f}) beats the incumbent hedge ({_lvl:.3f}) beats "
      f"the correctly-sized hedge ({_vr:.3f}). Re-sizing the hedge to its "
      "vega-equivalent makes the book WORSE, and removing it entirely is best. "
      "`none` is also the only family still positive at 1x its own costs.")

# %%
print("BY LEG (primary, z_resid):\n")
print(PRIM.groupby("leg_id").agg(
    n=("cell_id", "size"), med_net_0=("net_0.0", "median"),
    med_sharpe_0=("sharpe_0.0", "median"), max_sharpe_0=("sharpe_0.0", "max"),
    med_beta=("mean_abs_beta", "median")).round(3).to_string())

# %% [markdown]
# ## 7. Null bars, on the honest clock
#
# `n_eff = min(n_episodes, span × 252 / mean_hold)`. The span clock assumes an
# always-invested book; a roll-blackout book with 9 episodes over 5.6 years has
# made 9 bets, not 48, and quoting the larger number understates every bar.

# %%
SCORED = ST[ST["n_episodes"] >= 5].copy()
_neff = float(SCORED["n_eff"].median())
for _name, _n in (("headline", CFG.n_trials_headline),
                  ("full grid", CFG.n_trials_grid),
                  ("grid + A5", CFG.n_trials_with_a5)):
    _nb = GG.null_bars(_n, n_eff=_neff, span_years=SPAN_Y)
    print(f"{_name:11s} trials {_n:4d}   E[max SR|null] per-hold "
          f"{_nb['emax_perhold']:.4f}   annualised {_nb['emax_annualised']:.4f}")
print(f"\nmedian honest n_eff {_neff:.2f} (span-clock median "
      f"{float(SCORED['n_eff_hold_clock'].median()):.1f}), span {SPAN_Y:.2f}y")

BEST = SCORED.sort_values("sharpe_0.0", ascending=False).head(10)
print("\ntop 10 cells by gross annualised Sharpe:\n")
print(BEST[["cell_id", "n_episodes", "mean_abs_beta", "net_0.0", "sharpe_0.0",
            "net_1.0", "carry_usd", "residual_usd", "breakeven_bp"]]
      .round(3).to_string(index=False))
_bar = GG.null_bars(CFG.n_trials_grid, n_eff=_neff,
                    span_years=SPAN_Y)["emax_annualised"]
print(f"\ncells clearing the annualised {CFG.n_trials_grid}-trial bar "
      f"({_bar:.4f}): {int((SCORED['sharpe_0.0'] > _bar).sum())} of "
      f"{len(SCORED)}, and the best PRIMARY cell is "
      f"{float(PRIM['sharpe_0.0'].max()):.3f}.")

# %% [markdown]
# ## 8. The adversarial pass
#
# The controls that decide whether the survivors are trades.

# %%
TOP = list(BEST["cell_id"].head(6))
CELLMAP = {c.cell_id: c for c in CELLS}


def _sharpe(d):
    d = pd.Series(d).astype(float)
    if len(d[d != 0]) < 10 or d.std(ddof=1) == 0:
        return float("nan")
    return float(d.mean() / d.std(ddof=1) * math.sqrt(252.0))


def _hold(structure, leg_id, beta, side):
    _ca = CA[U.ca_col(structure)].dropna()
    _lg = (U.leg_series(LEGS, leg_id, structure).reindex(_ca.index)
           if leg_id else pd.Series(0.0, index=_ca.index))
    _eps = [GS.Episode(a, b, side, beta, CFG.ca_dv01, 0.0, "hold", i)
            for i, (a, b) in enumerate(SEGS)]
    return GS.book_daily(_eps, _ca, _lg, leg_id=leg_id, index=_ca.index)


_rows = []
for _cid in TOP:
    _sp = CELLMAP[_cid]
    _b = float(ST.loc[ST["cell_id"] == _cid, "mean_abs_beta"].iloc[0])
    _b = 0.0 if not np.isfinite(_b) else _b
    _net = float(ST.loc[ST["cell_id"] == _cid, "net_0.0"].iloc[0])
    _sh = float(_hold(_sp.structure, _sp.leg_id, _b, -1).sum())
    _rows.append({"cell_id": _cid, "cell_net": _net, "always_short_net": _sh,
                  "signal_adds_usd": _net - _sh,
                  "signal_share": 1.0 - _sh / _net if _net else np.nan})
CTRL = pd.DataFrame(_rows)
print("ALWAYS-SHORT control -- same structure, leg and beta, signal off:\n")
print(CTRL.round(3).to_string(index=False))

# %%
from dataclasses import replace as _replace

_rows = []
for _cid in TOP[:5]:
    _sp = CELLMAP[_cid]
    _row = {"cell_id": _cid}
    for _lag in (0, 10, 20, 40, 60):
        _r = GG.run_cell(_replace(_sp, cfg=GS.SignalConfig(
            **{**_sp.cfg.__dict__, "signal_lag_bd": _lag})), CA, LEGS,
            halflives=HL, ca_dv01=CFG.ca_dv01)
        _row[f"sr_{_lag}"] = _sharpe(_r.daily_by_mult[0.0])
    _rows.append(_row)
LADDER = pd.DataFrame(_rows)
print("PLACEBO LADDER -- a timing signal must decay as the lag grows:\n")
print(LADDER.round(3).to_string(index=False))
print("\nAt 9 episodes the per-rung standard error is ~0.4, so read this as "
      "'does it fall below the noise floor', not rung by rung. The long-end "
      "curve cells DO; the deferred-outright cells do NOT.")

# %%
_rows = []
for _cid in TOP:
    _sp = CELLMAP[_cid]
    _ca = CA[U.ca_col(_sp.structure)].dropna()
    _dn = S.denoise(_ca, HL[U.ca_col(_sp.structure)])
    _lg = U.leg_series(LEGS, _sp.leg_id, _sp.structure).reindex(_ca.index)
    _nv = LEGS[GG.vol_bench_col(_sp.structure)].astype(float).reindex(_ca.index)
    _w = U.time_weight_series(_ca.index, _sp.structure)
    _b, _ = S.sizing_beta(_sp.sizing, S.SizingInputs(
        ca=_ca, ca_denoised=_dn, leg=_lg, nvol=_nv, w=_w,
        level=LEVEL.reindex(_ca.index), slope=SLOPE.reindex(_ca.index)))
    _spread = (_dn - _b.fillna(0.0) * _lg).dropna()
    for _freq, _x in (("daily", _spread),
                      ("weekly", _spread.resample("W-WED").last().dropna())):
        _y = _x.diff().dropna()
        _xx = _x.shift(1).reindex(_y.index)
        _j = pd.concat([_y.rename("y"), _xx.rename("x")], axis=1).dropna()
        _bb = float(_j["y"].cov(_j["x"]) / _j["x"].var(ddof=1))
        _hl = float(-math.log(2) / math.log(1 + _bb)) if -2 < _bb < 0 else np.nan
        _rows.append({"cell_id": _cid, "freq": _freq, "ar1": 1 + _bb,
                      "halflife_periods": _hl})
HALFLIFE = pd.DataFrame(_rows)
print("RESIDUAL HALF-LIFE of the traded spread:\n")
print(HALFLIFE.round(3).to_string(index=False))
print(f"\nThe tradeable segment between roll blackouts is a median "
      f"{int(np.median(_seglen))} business days. Any spread whose daily "
      "half-life exceeds that CANNOT converge inside one -- which is exactly "
      "what the segment_end exit share said.")

# %% [markdown]
# ## 9. Engine certification, and the SFR12 adjudication
#
# The grid's only cell that clears its annualised 298-trial bar is
# `S|SFR12|immM_2s5s10s|beta_lvl`. Its AC1 of −0.056 says "no i.i.d. noise" —
# but `noise_fit` detects i.i.d. (MA(1)) error only, so it is structurally blind
# to a **multi-day dislocation**, which is what a deferred single contract does.

# %%
from RVUtils.ConvexityRV.ca_diagnostics import flag_quality

_rows = []
for _lab in ("SFR12", "SFR16", "SFR20", "GREENS", "BLUES", "GOLDS"):
    _ca = CA[U.ca_col(_lab)].dropna()
    _w = U.time_weight_series(_ca.index, _lab)
    _q = flag_quality(pd.DataFrame({
        "ca_bp": _ca, "implied_vol_bp": S.ca_implied_vol_bp(_ca, _w),
        "t1_first": U.mean_t1_series(_ca.index, _lab)}), syn_col=None)
    _dev = _ca - S.denoise(_ca, 10.0)
    _rows.append({"structure": _lab,
                  "frac_negative_ca": float(_q["flag_negative_ca"].mean()),
                  "frac_implausible_vol": float(_q["flag_implausible_vol"].mean()),
                  "frac_ok": float(_q["ok"].mean()),
                  "sd_dev_10d_ewma_bp": float(_dev.std(ddof=1)),
                  "ac1_dev": float(_dev.autocorr(1)),
                  "ac5_dev": float(_dev.autocorr(5)),
                  "frac_dev_gt_2bp": float((_dev.abs() > 2).mean())})
QUAL = pd.DataFrame(_rows).set_index("structure")
print(QUAL.round(4).to_string())
print("\nSFR12's mark wanders 4.0 bp from its own 10-day trend, with AC1 +0.86 "
      "and AC5 +0.45, on 38% of days. An 8.5-day residual half-life is what one "
      "of those snapping back looks like. GREENS is 0.56 bp and 1.1%.")

# %%
if CERT:
    _rows = [{"cell_id": k, **{kk: vv for kk, vv in v.items()
                               if kk in ("n_specs", "engine_terminal",
                                         "panel_terminal", "terminal_gap_pct",
                                         "daily_change_corr", "engine_sharpe",
                                         "panel_sharpe")}}
             for k, v in CERT.items() if v.get("status") == "ok"]
    CERTDF = pd.DataFrame(_rows)
    print("ENGINE CERTIFICATION (QueryDrivenBacktest, real contracts, dated "
          "instruments):\n")
    print(CERTDF.round(4).to_string(index=False))
    print("\nThe pre-registered bar is a daily-change correlation >= 0.99. "
          "None of the three reaches it, and every one comes back LOWER on the "
          "engine than on the panel. The par-rate panel prices rate CHANGES; "
          "the engine prices struck instruments that age, and the omitted term "
          "is carry.")
else:
    print("certification artifact absent -- run "
          "`python notebooks/backtests/convexity_rv/_p2_certify.py` (~2 min)")

# %% [markdown]
# ## 10. A5 — the dated, hold-through-the-roll package
#
# "Flat across the roll" was only ever a proxy for *do not book a
# contract-switching jump as P&L*. A **dated** package has no label to switch,
# so it can be held straight through. Signal on the causal forward-adjusted roll
# splice; P&L on the engine only.

# %%
_rows = []
for _lab in U.PRIMARY_STRUCTURES:
    _raw = CA[U.ca_col(_lab)].dropna()
    _sp = S.roll_spliced(_raw, ROLLS_CA)
    _nv = LEGS[GG.vol_bench_col(_lab)].astype(float).reindex(_raw.index)
    _theta = S.ca_theta_bp_per_year(_nv, U.mean_t1_series(_raw.index, _lab))
    _rows.append({"structure": _lab, "raw_last": _raw.iloc[-1],
                  "spliced_last": _sp.iloc[-1],
                  "spliced_drift_bp": _sp.iloc[-1] - _sp.iloc[0],
                  "predicted_theta_bp": float(_theta.mean() * SPAN_Y)})
SPLICE = pd.DataFrame(_rows).set_index("structure")
print(SPLICE.round(3).to_string())
print("\nThe spliced series is the level path of a position nobody rolls, and "
      "its drift IS the theta. The constant-rank series looks stable only "
      "because the roll reset pays the decay back -- a third confirmation of "
      "the same identity.")

_f = go.Figure()
for _lab in ("GREENS", "BLUES", "GOLDS"):
    _raw = CA[U.ca_col(_lab)].dropna()
    _f.add_trace(go.Scatter(x=_raw.index, y=_raw, name=f"{_lab} constant rank"))
    _f.add_trace(go.Scatter(x=_raw.index, y=S.roll_spliced(_raw, ROLLS_CA),
                            name=f"{_lab} spliced (dated)", line=dict(dash="dot")))
_f.update_layout(title="Constant-rank vs roll-spliced convexity adjustment: "
                       "the gap is 22 rolls of theta",
                 yaxis_title="bp", height=440,
                 legend=dict(orientation="h", y=1.10))
_f.show()

# %%
_a5 = DATA / "p2_a5_engine.parquet"
if _a5.exists():
    A5 = pd.read_parquet(_a5)
    print(A5.round(3).to_string(index=False))
    _ok = A5[A5["status"] == "ok"]
    _bar5 = GG.null_bars(CFG.n_trials_with_a5, n_eff=_neff,
                         span_years=SPAN_Y)["emax_annualised"]
    print(f"\nbest A5 engine Sharpe {_ok['engine_sharpe'].max():.4f} against a "
          f"{CFG.n_trials_with_a5}-trial annualised bar of {_bar5:.4f}; median "
          f"{_ok['engine_sharpe'].median():+.4f}; "
          f"{int((_ok['engine_net'] > 0).sum())} of {len(_ok)} positive.")
else:
    print("A5 artifact absent -- run "
          "`python notebooks/backtests/convexity_rv/_p2_a5_dated.py` (~4 min)")

# %% [markdown]
# ## 11. Overlays C and D — positioning and the CME–LCH basis

# %%
for _name, _f_ in (("C, CFTC positioning", DATA / "p2_overlay_C.parquet"),
                   ("D, CME-LCH basis", DATA / "p2_overlay_D.parquet")):
    if _f_.exists():
        print(f"{_name}:")
        print(pd.read_parquet(_f_).round(1).to_string(index=False))
        print()
print("Both overlays keep 0-1 of 6-9 episodes. An overlay that keeps one "
      "episode cannot be distinguished from noise, and that -- not the sign of "
      "its P&L -- is the reportable fact.")

# %% [markdown]
# ## 12. Verdict
#
# 1. **The premise fails its own measurement.** 0 of 11 declared legs clear a
#    level-and-slope-controlled partial-R² gate against ATMF normal vol. The raw
#    level relation is strong (R² up to 0.88) and correctly signed, but it is a
#    co-trend, not the incremental response a hedge ratio needs.
# 2. **The sizing objection is right, and unfixable in the obvious way.** The
#    incumbent hedge was 2–8× too small to be a vol hedge. The vega-matched fix
#    is undefined on 72–100% of days *because* of point 1. The tractable rule of
#    the same size, `vol_ratio`, makes the book worse, and **no hedge at all
#    beats every hedge**.
# 3. **The roll jump is the theta**, confirmed three ways (quarter-of-decay vs
#    jump 1.02–1.11; spliced drift vs predicted theta within 8–17%).
# 4. **The only bar-clearing cell is a mark.** SFR12 fails quality on a third of
#    its own trading dates, wanders 4 bp from its own trend on 38% of days with
#    AC1 +0.86, does not decay under a 60 bd placebo, and certifies at a daily
#    correlation of 0.53 against a 0.99 bar.
# 5. **The panel overstates; the engine is the number.** Panel Sharpe
#    2.14/0.87/0.41 → engine 1.41/0.15/0.13.
# 6. **The structural finding worth keeping**: the long-end residual reverts in
#    68–99 business days against a ~56 bd roll-flat window, so the trade cannot
#    converge inside one — and the dated, hold-through-roll version that removes
#    that constraint is dead on the engine (best 0.18 vs a bar of 1.22).

# %%
print("GV block, verdict inputs")
print("=" * 60)
print(f"panel dates                       {len(IDX)}  "
      f"{IDX.min().date()}..{IDX.max().date()}")
print(f"declared cells                    {len(CELLS)} (+6 A5 = "
      f"{CFG.n_trials_with_a5})")
print(f"episodes                          {len(EP)}")
print(f"segment_end exit share            "
      f"{100 * (EP['reason'] == 'segment_end').mean():.1f}%")
print(f"vol-proxy legs clearing the gate  "
      f"{int(VOLPROXY['gate_full'].sum())}/{len(VOLPROXY)}")
print(f"vega-matched / incumbent hedge    {SIZING['ratio'].median():.2f}x median")
print(f"best PRIMARY gross ann Sharpe     {float(PRIM['sharpe_0.0'].max()):.4f}")
print(f"E[max SR|null, {CFG.n_trials_grid} trials, ann]  {_bar:.4f}")
print(f"best cell overall                 "
      f"{SCORED.sort_values('sharpe_0.0', ascending=False).iloc[0]['cell_id']} "
      f"({float(SCORED['sharpe_0.0'].max()):.4f}), a secondary structure whose "
      "marks fail quality on 33% of its own trading dates")
print("=" * 60)
print("VERDICT: DEAD. The mechanism the brief names is real and measurable; "
      "the trade is not.")
