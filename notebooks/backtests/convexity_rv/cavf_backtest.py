# %% [markdown]
# # SOFR futures convexity adjustment vs USD SOFR butterflies — the fresh backtest
#
# > *"Convexity adjustments for 1y SOFR packs are computed as the spread between
# > the pack's rate (the average of 4 SOFR rates in the pack) and
# > matched-maturity forward 1y CME swap rate."* — Citi Research, Rates Vol Lab,
# > 12-Jun-2023 (Fig 58, the SOFR restatement of the Eurodollar screen)
#
# > *"Sell $200k DV01 of Blues CAs … pay the belly of the 2s5s10s swap fly with
# > notional weights $147mm/−$85.6mm/$20.89mm (0.705/−1/0.465 DV01 weights)."*
# > — Citi, 09-Feb-2017, the ticket this family of trades descends from
#
# This block re-measures the whole family from scratch — **outrights, packs and
# CME bundles against spot AND forward-starting butterflies, five signal
# families, 515 pre-registered cells** — on the repaired Q/Q CA path, trusting
# none of the previous results. The pre-registration
# (`docs/convexityrv/cavf-grid-preregistration.md`) was frozen before scoring
# and carries two dated execution amendments, both discovered by this block's
# own machinery:
#
# 1. **Same-day fills harvested the CA mark's own measurement noise** — the
#    first pass printed 100% hit rates over 3–5-day holds. Primary convention
#    is now fills at t+1; the same-day gap is reported as the noise harvest.
# 2. **Constant-rank labels booked the IMM-roll contract switch as P&L** —
#    22 of 33 SR3 rolls are FOMC dates, so the jump is systematically signed.
#    Signals and panel P&L now use roll-spliced series.
#
# **The verdict is negative and it survives both corrections being generous.**
# Every CA-based family's MEDIAN gross is below zero before costs; the single
# best cell of 515 sits below the annualised E[max SR | null]; and the only
# family with a positive median gross is the fly-only CONTROL — which is not a
# convexity trade and dies on its own costs. Sections 7–9 carry the numbers.
#
# One interpretive note the corpus adds (Huggins & Schaller 2022, ch. 6): the
# SR3 contract's payout lands at the END of its reference period, so it has
# **no Jensen convexity of its own** — the measured CA is financing/margin bias
# plus positioning, which is exactly why the fundamental overlays (CFTC dealer
# positioning, CME–LCH basis) were declared. They did not rescue the trade
# either (§7).

# %%
import nest_asyncio
nest_asyncio.apply()

import datetime as dt
import json
import math
import os
import pathlib
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
REPO = pathlib.Path.cwd()
while not (REPO / "RVUtils").exists() and REPO != REPO.parent:
    REPO = REPO.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import numpy as np
import pandas as pd
import statsmodels.api as sm

import plotly.graph_objects as go
import plotly.io as pio
pio.renderers.default = "plotly_mimetype+notebook_connected"

from RVUtils.ConvexityRV import cavf_grid as G
from RVUtils.ConvexityRV import cavf_signals as S
from RVUtils.ConvexityRV import cavf_universe as U
from RVUtils.ConvexityRV import strat2_fly_universe as FU

DATA = REPO / "notebooks" / "data" / "convexity_rv"
pd.set_option("display.width", 220, "display.max_columns", 40)
print(f"repo {REPO}")

# %% [markdown]
# ## 1. CONFIG — every knob, and why it is set where it is
#
# The config mirrors the pre-registration; the assert below refuses to present
# numbers produced under a different one. Change a knob → re-run
# `_cavf_run_grid.py` → the meta file moves with it.

# %%
import dataclasses


@dataclasses.dataclass(frozen=True)
class CavfConfig:
    #: signal/z window, rows. The CA panel measured 100% dense, so rows≈days.
    window: int = 252
    #: pre-registered primaries; the 1.5 set is the declared sensitivity.
    z_entry: float = 2.0
    z_exit: float = 0.5
    max_hold_bd: int = 63
    #: fills lag decisions by one mark (amendment 1). 0 = the noise diagnostic.
    exec_lag_bd: int = 1
    #: β gate, bp per bp (Citi's 21.4 in bp-per-percent ≡ 0.214 here).
    beta_abs_min: float = 0.01
    beta_abs_max: float = 1.0
    #: per-leg round-trip costs on leg DV01 (bp): futures package / swap / fly leg.
    cost_fut_bp: float = 0.25
    cost_swap_bp: float = 0.5
    cost_fly_leg_bp: float = 0.5
    #: the declared trial count. Moving it without amending the
    #: pre-registration is the trial-count leak the tests refuse.
    declared_trials: int = 515
    ca_dv01: float = 100_000.0


CFG = CavfConfig()
META = json.loads((DATA / "cavf_grid_meta.json").read_text())
assert META["declared_trials"] == CFG.declared_trials, (
    f"grid ran {META['declared_trials']} trials, config declares "
    f"{CFG.declared_trials} — the pre-registration and the artifacts disagree")
assert META["exec_lag_bd"] == CFG.exec_lag_bd
assert META["roll_spliced"] is True
print(json.dumps({k: v for k, v in dataclasses.asdict(CFG).items()}, indent=1))
print(f"\ngrid ran at {META['ran_at']}  |  {META['n_imm_rolls']} IMM rolls in window")

# %% [markdown]
# ## 2. The panels
#
# CA through the repaired TB path (`sfr_cvx_adj`, Q/Q matched swap, no
# magnitude heuristics, `fill=False`), 31 labels × 1,409 dates, **zero pricing
# failures**; fly legs at 48 tenors (spot + 1/2/3/4/5y forward starts), 100%
# dense. The term structure must be monotone in rank — CA is a variance
# quantity — and that is asserted, not eyeballed.

# %%
ca_wide = pd.read_parquet(DATA / "cavf_ca_panel.parquet")
ca_wide.index = pd.to_datetime(ca_wide.index)
cols = {c.split()[1]: c for c in ca_wide.columns}
failures = json.loads((DATA / "cavf_ca_failures.json").read_text())
assert not failures, f"the CA backfill recorded failures: {failures}"

ROLLS = S.imm_roll_dates(ca_wide.index)
ca_raw = {lab: ca_wide[c].dropna() for lab, c in cols.items()}
ca_spl = {lab: S.roll_splice(s, ROLLS) for lab, s in ca_raw.items()}

COLOURS = ["WHITES", "REDS", "GREENS", "BLUES", "GOLDS"]
med = pd.Series({c: float(ca_raw[c].median()) for c in COLOURS})
print("median CA by colour, bp:")
print(med.round(3).to_string())
assert med.is_monotonic_increasing, (
    "the adjustment is not increasing with rank — a data problem, not a view")

legs = pd.read_parquet(DATA / "cavf_fly_legs.parquet")
wide = FU.legs_wide(legs)
wide.index = pd.to_datetime(wide.index)
FLIES = {f.fly_id: f for f in U.tradeable_fly_specs()}
fly_by_id = {fid: FU.fly_rate_series(wide, f, 0.5, 0.5).dropna()
             for fid, f in FLIES.items()}
print(f"\nCA {ca_wide.shape}  legs {wide.shape}  flies {len(fly_by_id)}  "
      f"rolls {len(ROLLS)}")
neg = pd.Series(META["neg_ca_frac"])
print(f"negative-CA fraction: front noise (WHITES {neg['WHITES']:.2f}, "
      f"SFR2 {neg['SFR2']:.2f}) vs deep (GOLDS {neg['GOLDS']:.2f}) — the front "
      "prints negative on quote noise alone, as measured in previous blocks")

# %% [markdown]
# ## 3. Does the machine give the right answer to questions we already know?
#
# ### 3.1 Citi's published SOFR screen, close 6/9/2023
#
# Our BLUES and GOLDS on 2023-06-09 are the same four-contract windows as
# Citi's printed M6-H7 and M7-H8 rows. The bar is **bp on a level** — the
# correlation-only version of this tie-out was shown to survive ×2, ×100 and
# +10bp mutations, i.e. to grade nothing. The annual-frequency matched swap is
# the negative control and must FAIL by around −4bp.

# %%
CITI_FIG58 = {"BLUES": 15.40, "GOLDS": 22.29}   # Citi, close 6/9/2023
d0 = pd.Timestamp("2023-06-09")
ours = {lab: float(ca_raw[lab].loc[d0]) for lab in CITI_FIG58}
for lab, printed in CITI_FIG58.items():
    err = ours[lab] - printed
    print(f"{lab}: ours {ours[lab]:6.2f}  Citi {printed:6.2f}  err {err:+.2f}bp")
    assert abs(err) < 1.6, (
        f"{lab} misses Citi's printed screen by {err:+.2f}bp — the shared-path "
        "tie-out holds to ~1bp and this panel should too")

from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from TB.IRSwapsTB import IRSwapsTB

_tb = IRSwapsTB(IRSwapsMDP(source="citivelo_excel_rl"), show_tqdm=False,
                use_ts_cache=False)
_annual = _tb.sfr_cvx_adj(["BLUES"], dt.date(2023, 6, 9), dt.date(2023, 6, 9),
                          matched_frequency=None, matched_leg2_frequency=None)
_tb.close()
ann_val = float(_annual.iloc[0, 0])
gap = ann_val - ours["BLUES"]
print(f"\nnegative control — annual matched swap: {ann_val:.2f}bp "
      f"(gap {gap:+.2f}bp vs Q/Q)")
assert gap < -3.0, (
    "the annual-frequency negative control no longer fails — the Q/Q "
    "convention has been lost somewhere in the path")
print("OK: the annual convention fails by the documented ~4bp, as it must.")

# %% [markdown]
# ### 3.2 The Blues ticket, and the sizing rule
#
# Pure arithmetic against Citi's published marks (09-Feb → 06-Jun-2017):
# the CA leg's gross is exact, and the β-sizing rule reproduces Citi's
# published belly notional to 0.4%.

# %%
ca_leg = (8.8 - 6.6) * 200_000.0
assert ca_leg == 440_000.0
belly_dv01 = 0.214 * 200_000.0            # β=21.4 bp-per-percent ≡ 0.214 bp/bp
CITI_BELLY = 41_088.0                     # published 5y notional × era $/bp
print(f"CA leg gross  (8.8−6.6)×$200k = ${ca_leg:,.0f}   -> matches Citi exactly")
print(f"belly sizing  0.214×$200k = ${belly_dv01:,.0f}/bp vs Citi ${CITI_BELLY:,.0f} "
      f"(ratio {belly_dv01 / CITI_BELLY:.3f})")
assert 0.99 < belly_dv01 / CITI_BELLY < 1.05
hedge_leg = belly_dv01 * (-16.5 - -18.2)
print(f"fly −18.2 → −16.5: paid belly earns ${hedge_leg:+,.0f}; "
      f"reconstruction ${ca_leg + hedge_leg:,.0f} vs Citi net +$500,000 "
      f"({abs(ca_leg + hedge_leg - 500_000) / 500_000:.1%} off)")
assert abs(ca_leg + hedge_leg - 500_000.0) / 500_000.0 < 0.03

# %% [markdown]
# ## 4. Sign probes, live
#
# ### 4.1 The engine, on a five-mark micro-book
#
# A short-spread BLUES × 2s5s10s book (buy the pack, pay the swap, pay the
# belly) and its exact mirror, run through `QueryDrivenBacktest` on five
# marks. The two books must be equal and opposite to the dollar, and the short
# book's P&L must track −ΔCA to the sign.

# %%
from RVUtils.ConvexityRV import cavf_engine as E

_probe_days = [d for d in ca_spl["BLUES"].index
               if dt.date(2024, 7, 1) <= d.date() <= dt.date(2024, 7, 10)]
_specs = {}
for side in (-1, +1):
    _specs[side] = E.spec_from_episode(
        label="BLUES", side=side, entry=_probe_days[0].date(),
        exit=_probe_days[-2].date(), beta_entry=0.2, fly=FLIES["2s5s10s"])
_bt = {side: E.run_backtest([sp], _probe_days) for side, sp in _specs.items()}
eqS = E.assert_ran(_bt[-1], [_specs[-1]], expect_days=len(_probe_days))
eqL = E.assert_ran(_bt[+1], [_specs[+1]], expect_days=len(_probe_days))
mirror = float((eqS + eqL).abs().max())
print(f"short-book terminal ${float(eqS.iloc[-1]):+,.0f}   "
      f"long-book ${float(eqL.iloc[-1]):+,.0f}   max |sum| ${mirror:,.0f}")
assert mirror < 0.01 * max(1.0, float(eqS.abs().max())), (
    "the long and short books are not mirrors — a sign is being dropped")

d_ca = float(ca_raw["BLUES"].loc[_probe_days[-2]] - ca_raw["BLUES"].loc[_probe_days[0]])
d_fly = float(fly_by_id["2s5s10s"].loc[_probe_days[-2]] - fly_by_id["2s5s10s"].loc[_probe_days[0]])
pred = -1 * (d_ca - 0.2 * d_fly) * CFG.ca_dv01
print(f"ΔCA {d_ca:+.2f}bp  Δfly {d_fly:+.2f}bp  panel-predicted short-book "
      f"${pred:+,.0f} vs engine ${float(eqS.iloc[-1]):+,.0f}")
assert np.sign(pred) == np.sign(float(eqS.iloc[-1])), (
    "the engine book and the panel arithmetic disagree on SIGN")
print("OK: short spread = buy pack + pay swap + pay belly, and the mirror is exact.")

# %% [markdown]
# ### 4.2 The execution convention, on pure noise
#
# The known answer is engineered: i.i.d. noise around a constant has no
# tradeable content, yet same-day fills 'earn' it. This is the probe form of
# the test that guards amendment 1.

# %%
_rng = np.random.default_rng(2024)
_idx = pd.bdate_range("2021-01-04", periods=900)
_noise = pd.Series(5.0 + _rng.normal(0, 1.0, len(_idx)), index=_idx)
_spec = G.CellSpec("probe", "A_ca", "ca_only", "X", None,
                   S.SignalConfig(window=252))
_g0 = float(G.run_cell(_spec, {"X": _noise}, {}, exec_lag_bd=0)
            .equity_by_mult[0.0].iloc[-1])
_g1 = float(G.run_cell(_spec, {"X": _noise}, {}, exec_lag_bd=1)
            .equity_by_mult[0.0].iloc[-1])
print(f"pure noise: same-day fills ${_g0:,.0f} vs t+1 fills ${_g1:,.0f}")
assert _g0 > 2_000_000 and _g1 < 0.15 * _g0
print("OK: the convention kills the phantom; anything left at t+1 is candidate real.")

# %% [markdown]
# ## 5. The grid — 515 pre-registered cells
#
# 14 structures (5 packs, 4 CME bundles, 5 outright ranks) × 6 flies each
# (three shapes, spot + matched forward start) × two threshold sets across
# five signal families, plus CA-only / fly-only controls, the pinned
# Citi-Blues fair-value line, the JPM beta-stability variant, and 30
# positioning / CCP-basis / carry overlay cells.

# %%
stats = pd.read_parquet(DATA / "cavf_grid_stats.parquet")
rets = pd.read_parquet(DATA / "cavf_grid_returns.parquet")
eps = pd.read_parquet(DATA / "cavf_grid_episodes.parquet")
assert len(stats) == CFG.declared_trials
traded = stats[stats["n_ep"] > 0]
print(f"{len(traded)}/{len(stats)} cells traded; "
      f"{len(eps):,} episodes; median hold "
      f"{float(traded['mean_hold_bd'].median()):.0f}bd")
print("\nexit reasons:")
print(eps["exit_reason"].value_counts().to_string())

# %%
SHOW = ["family", "structure", "fly", "z_in", "n_ep", "hit", "gross_usd",
        "net_1x", "ann_sharpe", "n_eff"]
print("top 12 by annualised Sharpe (zero cost, t+1 fills, roll-spliced):")
print(stats.nlargest(12, "ann_sharpe")[SHOW].round(3).to_string())
print("\nfamily medians:")
FAM = stats.groupby("family")[["n_ep", "gross_usd", "net_0p5x", "net_1x",
                               "net_2x", "ann_sharpe"]].median().round(0)
print(FAM.to_string())

# every CA-based family's median gross is negative; the sole positive-median
# family is the fly-only CONTROL — asserted so the prose cannot drift from the
# artifact
for fam in ("A", "A_ca", "B"):
    assert float(FAM.loc[fam, "gross_usd"]) < 0, (
        f"family {fam} median gross turned positive — §9's verdict text is stale")
assert float(FAM.loc[A_FLY := "A_fly", "gross_usd"]) > 0
assert float(FAM.loc["A_fly", "net_1x"]) < 0, (
    "the fly-only control now survives its own costs — re-derive the verdict")

# %% [markdown]
# ### 5.1 What the two amendments were worth — the artifact ledger
#
# The same-day-fill diagnostic and the roll splice each removed a *specific,
# measured* phantom. This section is the receipt.

# %%
diag = META["same_day_diag"]
print(f"median hit rate: primary {diag['median_hit_primary']:.3f} vs "
      f"same-day fills {diag['median_hit_same_day']:.3f}")
print("\nmedian mark-noise harvest by family (same-day gross − t+1 gross, USD):")
print(pd.Series(diag["median_noise_harvest_by_family"]).round(0).to_string())
print(f"\nsplice magnitude (cumulative |raw − spliced|, bp): "
      f"{ {k: round(v, 1) for k, v in META['splice_max_gap_bp'].items()} }")
print("\nThe first pass — before either amendment — printed hit rates of 1.000")
print("and per-episode P&L an order of magnitude above the CA level itself.")
print("Neither phantom is tradeable: one is the mark's own measurement noise,")
print("the other is the IMM-roll label switch (22 of 33 rolls are FOMC dates).")

# %% [markdown]
# ## 6. The null, the deflated Sharpe, and the placebo
#
# Both clocks, per the house discipline: per-hold (n_eff from holding periods)
# and annualised (1/√span). The deflated Sharpe of the best cell uses the
# actual cross-cell correlation (Bailey's effective-N, the direction that makes
# the test harsher).

# %%
from RVUtils.StatisticalFinance.deflated_sharpe import (
    deflated_sharpe_of_best, expected_max_sharpe)

med_neff = float(traded["n_eff"].median())
span_y = float(traded["span_y"].median())
bars = {
    "per-hold": expected_max_sharpe(CFG.declared_trials, 1.0 / med_neff),
    "annualised": expected_max_sharpe(CFG.declared_trials, 1.0 / span_y),
}
best = stats["ann_sharpe"].idxmax()
best_sr = float(stats.loc[best, "ann_sharpe"])
print(f"median n_eff {med_neff:.1f}   span {span_y:.2f}y")
print(f"E[max SR | null, {CFG.declared_trials} trials]: "
      f"per-hold {bars['per-hold']:.3f}   annualised {bars['annualised']:.3f}")
print(f"best cell: {best}  ann Sharpe {best_sr:.3f}")
assert best_sr < bars["annualised"], (
    "the best cell now clears the annualised null — re-derive the verdict")

trial_cols = [c for c in rets.columns if rets[c].abs().sum() > 0]
dsr = deflated_sharpe_of_best([rets[c].to_numpy() for c in trial_cols])
print(f"\ndeflated Sharpe of the best of {len(trial_cols)} traded cells "
      f"(effective N {dsr['n_trials_effective']:.0f}, method "
      f"{dsr['effective_n_method']}): DSR {dsr['dsr']:.3f}")
assert dsr["dsr"] < 0.95, (
    "the winner clears DSR 0.95 — the verdict below is stale")

print("\nplacebo (signal lagged +20bd) on the top cells:")
for k, v in META["placebo_lag20"].items():
    print(f"  {k}: live ${v['gross_live']:,.0f} -> lag20 ${v['gross_lag20']:,.0f}")

# %% [markdown]
# ## 7. The overlays — positioning, CME–LCH basis, carry
#
# Declared as conditioning overlays with pre-registered weak expectations
# (the positioning mechanism reproduces on Blues only; the basis mechanism is
# IM non-nettability, not the level). They gate entries of the pack ×
# 2s5s10s books.

# %%
ov = stats[stats["family"].isin(["C_posit", "D_basis", "E_carry"])]
base = stats.loc[[c for c in stats.index
                  if any(c == o.split("|", 1)[1] for o in ov.index)]]
print("overlay cells:")
print(ov[SHOW].round(3).to_string())
print("\ntheir base books:")
print(base[["family", "structure", "n_ep", "gross_usd", "ann_sharpe"]]
      .round(3).to_string())
print("\nOverlays mostly cut episode counts to single digits without turning")
print("a negative-median family positive — conditioning cannot rescue a")
print("spread that does not revert tradably in the first place.")

# %% [markdown]
# ## 8. The headline measurement: does the matched-start fly hedge better?
#
# The forward-start hypothesis — a fly starting at the structure's expiry
# should co-move with its CA more than the spot fly — was previously REJECTED,
# but only on ranks ≤10 (T1 ≤ 2.5y); Blues and Golds were out of reach. This
# is the first measurement at full depth.

# %%
fsm = pd.read_parquet(DATA / "cavf_fs_matrix.parquet")
best_per = (fsm.loc[fsm.groupby(["structure", "start_y"])["r2"].idxmax()]
            .pivot(index="structure", columns="start_y", values="r2"))
order = [s.label for s in U.STRUCTURES if s.label in best_per.index]
best_per = best_per.loc[order]
print("hedge R² of ΔCA on Δfly (best of 3 shapes), structure × forward start:")
print(best_per.round(3).to_string())

peaks = []
for s in U.STRUCTURES:
    sub = fsm[fsm["structure"] == s.label]
    if sub.empty:
        continue
    by_start = sub.groupby("start_y")["r2"].max()
    peaks.append({"structure": s.label, "t1": s.t1_mean_y,
                  "peak_start": float(by_start.idxmax()),
                  "peak_r2": float(by_start.max())})
PK = pd.DataFrame(peaks)
slope = np.polyfit(PK["t1"], PK["peak_start"], 1)[0]
print(f"\npeak-R² forward start regressed on structure T1: slope {slope:+.3f} "
      f"(the hypothesis predicts +1.0; the shallow-only rejection measured "
      f"−0.018)")
print(f"max R² anywhere in the matrix: {fsm['r2'].max():.3f}")

fig = go.Figure(go.Heatmap(
    z=best_per.to_numpy(), x=[f"{c:.0f}Y" for c in best_per.columns],
    y=best_per.index, colorscale="Viridis", zmin=0,
    colorbar={"title": "R²"}))
fig.update_layout(title="Hedge R² of ΔCA on Δfly — structure × fly forward start",
                  height=430)
fig.show()

# %% [markdown]
# ## 9. Engine certification — decomposed, because the blend hides the answer
#
# Representative books ran end-to-end through `QueryDrivenBacktest` — real
# futures legs, a date-pinned matched swap, a date-pinned fly — on the panel's
# own fill dates. Three effects separate engine from panel and each is shown
# on its own: (a) the **CA package itself** (the `__nofly` variant, non-roll
# episodes) is the hard gate; (b) episodes **crossing an IMM roll** differ by
# construction (the engine holds the original contracts, the panel rolls at
# zero cost); (c) the **fly leg ages** in the engine while the panel's is
# constant-maturity — the same drift that kept only 32–49% of panel dollars
# in the previous grid's hedged cells.
#
# The certification also caught two live defects on its first pass (corr
# −0.005): negative `contracts` on a `STIRFutureQuery` silently going LONG
# (the builder's weight flip cancels against the leg's own sign), and an
# `abs()` on the pair β that flipped the fly leg whenever β < 0. Both are
# pinned by tests now; the numbers below are the post-fix state.

# %%
cert = json.loads((DATA / "cavf_certification.json").read_text())
CERT = pd.DataFrame(cert).T
print(CERT.to_string())

_gate = cert.get("A|BLUES|2s5s10s|p__nofly", {})
_g = _gate.get("corr_daily_nonroll_median", np.nan)
print(f"\nHARD GATE — CA package alone, non-roll episodes, median per-episode "
      f"daily corr: {_g:+.4f}")
assert np.isfinite(_g) and _g > 0.90, (
    f"the CA package does not certify ({_g}) — the panel's CA leg is not "
    "describing the tradeable book and every number above is suspect")
for cell, row in cert.items():
    if cell.endswith("__nofly") or not row.get("n_episodes", 0):
        continue
    print(f"{cell}: blended corr {row['corr_daily']:+.3f}, non-roll median "
          f"{row['corr_daily_nonroll_median']:+.3f}, engine "
          f"${row['engine_terminal']:,.0f} vs panel ${row['panel_terminal']:,.0f}")
print("\nWith the fly attached the blend degrades exactly as the previous")
print("grid measured: the fly leg's ageing dominates episodes where the CA is")
print("quiet. The panel's verdict needs no rescue from this — it is already")
print("negative — but any POSITIVE panel cell would have to be re-derived")
print("through the engine before being believed, per inheritance ban #7.")

# %% [markdown]
# ## 10. The books, visually

# %%
from BT.trade_dashboard import compare_curves

pick = {
    "best cell (fly-only control)": stats.nlargest(1, "ann_sharpe").index[0],
    "best CA cell": stats[~stats["family"].isin(["A_fly"])]
        .nlargest(1, "ann_sharpe").index[0],
    "Citi-pinned Blues FV": "Bpin|BLUES|2s5s10s",
    "Citi structure, pairs": "A|BLUES|2s5s10s|p",
}
curves = {name: rets[cid].cumsum() for name, cid in pick.items()
          if cid in rets.columns}
fig = compare_curves(curves, title="CA-vs-fly — representative books, "
                                   "zero cost, t+1 fills, roll-spliced")
fig.show()

# %%
from BT.trade_dashboard import trade_dashboard

_best_ca = pick["best CA cell"]
book = eps[eps.cell_id == _best_ca].copy()
if len(book):
    per_ep_ret = rets[_best_ca]
    rows = []
    for _, r in book.iterrows():
        idx2 = per_ep_ret.index
        w = per_ep_ret.loc[r["entry"]:r["exit"]]
        rows.append({"closed_at": r["exit"], "pnl": float(w.sum()),
                     "side": "short spread" if r["side"] < 0 else "long spread",
                     "structure": _best_ca, "z": float(r["z_at_entry"]),
                     "exit_reason": r["exit_reason"],
                     "holding_period_days": int(r["hold_bd"])})
    bdf = pd.DataFrame(rows)
    span = (bdf["closed_at"].max() - bdf["closed_at"].min()).days / 365.25
    fig = trade_dashboard(bdf, title=f"best CA cell — {_best_ca}",
                          span_years=max(span, 0.5), signal_col="z")
    fig.show()

# %% [markdown]
# ## 11. Robustness on the best CA cell

# %%
eq_best = rets[_best_ca].cumsum()
d = rets[_best_ca]
by_year = d.resample("YE").sum()
print("P&L by year, best CA cell (zero cost):")
print(by_year.round(0).to_string())
loo = {}
for y in sorted(set(d.index.year)):
    keep = d[d.index.year != y]
    sd = keep.std(ddof=1)
    loo[y] = {"terminal_ex": float(keep.sum()),
              "sharpe_ex": float(keep.mean() / sd * math.sqrt(252)) if sd > 0 else np.nan}
print("\nleave-one-year-out:")
print(pd.DataFrame(loo).T.round(2).to_string())

F = pd.DataFrame({
    "level": wide[["2Y", "5Y", "10Y"]].mean(axis=1) * 100.0,
    "slope": (wide["10Y"] - wide["2Y"]) * 100.0,
    "curv": (2 * wide["5Y"] - wide["2Y"] - wide["10Y"]) * 100.0}).diff()
F["level_sq"] = F["level"] ** 2
A = pd.concat([d.rename("pnl"), F], axis=1).dropna()
A = A[A["pnl"] != 0]
if len(A) > 30:
    X = sm.add_constant(A[["level", "slope", "curv", "level_sq"]].to_numpy())
    fit = sm.OLS(A["pnl"].to_numpy(), X).fit(cov_type="HAC",
                                             cov_kwds={"maxlags": 5})
    print(f"\nfactor attribution ({len(A)} non-flat days): "
          f"R² {float(fit.rsquared):.4f}; t(level) {float(fit.tvalues[1]):+.2f} "
          f"t(slope) {float(fit.tvalues[2]):+.2f} "
          f"t(curv) {float(fit.tvalues[3]):+.2f} "
          f"t(level²) {float(fit.tvalues[4]):+.2f}")
    print("A P&L this size with no curve loading is residual noise, not a")
    print("factor bet — consistent with the spread never reverting tradably.")

# %% [markdown]
# ## 12. Reading this notebook
#
# * **The family is dead, measured honestly at its own declared size.** Across
#   515 pre-registered cells on repaired data: every CA-based family (pairs,
#   fair-value, CA-only, JPM-threshold, the pinned Citi line) has a NEGATIVE
#   median gross before a basis point of cost; the best single cell fails the
#   annualised E[max SR | null] and the deflated Sharpe; the placebo kills the
#   top cells; the overlays (positioning, CME–LCH basis, carry) thin the books
#   without changing the sign.
#
# * **The two most valuable numbers in the block are the phantoms.** Same-day
#   fills add ~$0.4–0.9M of un-tradeable "profit" per median cell (hit rates
#   0.93 vs 0.45 real); the IMM-roll label switch adds signed jumps 22 of 33
#   of which land on FOMC dates. Any CA mean-reversion result that does not
#   state its fill convention and roll handling should be assumed to be
#   harvesting one or both.
#
# * **The forward-start-matched fly hypothesis stays rejected at full depth.**
#   With Blues and Golds finally daily 2021–2026, the peak-R² forward start
#   does not track the structure's expiry (§8), and no cell of the matrix
#   reaches an R² that would size a hedge. Citi's own 2s5s10s is a fair-value
#   REGRESSOR at monthly horizons, not a daily hedge — consistent with w2b's
#   independent verdict on the repaired panel.
#
# * **What survives is measurement, not a trade.** The CA panel itself (31
#   structures, zero failures, tied to Citi's printed screen at ~1bp with the
#   annual convention failing by −4bp as a negative control), the fly-leg
#   panel, the certification path, and the screener these feed.

# %%
summary = {
    "declared_trials": CFG.declared_trials,
    "cells_traded": int(len(traded)),
    "best_cell": best,
    "best_ann_sharpe": round(best_sr, 3),
    "null_annualised": round(bars["annualised"], 3),
    "null_perhold": round(bars["per-hold"], 3),
    "dsr_best": round(float(dsr["dsr"]), 3),
    "median_gross_A": float(FAM.loc["A", "gross_usd"]),
    "median_gross_B": float(FAM.loc["B", "gross_usd"]),
    "median_gross_A_ca": float(FAM.loc["A_ca", "gross_usd"]),
    "median_hit_primary": round(diag["median_hit_primary"], 3),
    "median_hit_same_day": round(diag["median_hit_same_day"], 3),
    "fs_hypothesis_slope": round(float(slope), 3),
    "fs_hypothesis_max_r2": round(float(fsm["r2"].max()), 3),
}
for k, v in summary.items():
    print(f"{k:24} {v}")
pd.Series(summary).to_csv(DATA / "cavf_backtest_summary.csv")
print(f"\nwrote {DATA / 'cavf_backtest_summary.csv'}")
