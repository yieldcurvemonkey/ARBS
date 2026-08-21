# %% [markdown]
# # W2b — SOFR pack convexity against a 2s5s10s swap fly, 2021–2026
#
# > *"Convexity adjustments for 1y SOFR packs are computed as the spread between
# > the pack's rate (the average of 4 SOFR rates in the pack) and
# > matched-maturity forward 1y CME swap rate. The model for convexity
# > adjustment is the Ho-Lee model calibrated to cap/floor vols. Implied vol is
# > calculated by matching the model to the observed convexity adjustment.
# > Realized vol is 3m realized vol of the corresponding pack. For each
# > valuation metric, we mark three best short convexity trades in bold."*
# >
# > — Citi Research, *Rates Vol Lab — Forward steepener and vol divergence*,
# > 12-Jun-2023, Figure 58 (the SOFR restatement of the Eurodollar screen)
#
# and the trade itself, verbatim:
#
# > *"Sell $100k DV01 of Blues convexity adjustment, i.e. buy 1000 of H0-Z0
# > packs (1000 of each of the four contracts) and pay $1bn on a
# > matched-maturity (3/18/20-3/17/21) CME swap."*
# >
# > *"Pay the belly of the 2s5s10s swap fly with notional weights
# > $79mn/-$44.4mn/$10.9mn (0.73/-1/0.46 DV01 weights)."*
#
# **This block is the first time the packs Citi actually traded are inside daily
# reach.** The previous block ran the same engine on a panel whose deep end was
# mostly absent — Blues had 49 usable dates in 2023, Golds had none at all in
# 2026. Section 3 measures the repair.
#
# **The verdict is negative, and it is not primarily about costs.** Gross Sharpe
# is 0.130 over 5.6 years. Section 9 puts that below what a zero-edge strategy
# would be expected to produce from a six-arm search, let alone the 1,569-cell
# grid that produced this family. Costs then take it to zero at 0.5bp and
# negative at 1bp. And the fly hedge — section 8 — removes 0.6% of the variance
# and $88k of the money.

# %%
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

import plotly.io as pio
pio.renderers.default = "plotly_mimetype+notebook_connected"

import RVUtils.ConvexityRV.strat2_sofr_convexity as S2
from RVUtils.ConvexityRV.ca_signals import CITI_FIG4_BLUES
from RVUtils.ConvexityRV.strat1_threeway import expected_max_sharpe_under_null

DATA = REPO / "notebooks" / "data" / "convexity_rv"
pd.set_option("display.width", 200, "display.max_columns", 40)
print(f"repo {REPO}")

# %% [markdown]
# ## 1. The config
#
# Every knob, and the reason for its value. `Strat2Config` carries the same
# defaults and documents each one inline; the three that are *not* defaults are
# the universe knobs, and they are the whole point of this block.
#
# * `n_contracts=20` — pull twenty quarterly SR3 contracts per date, which is
#   what a rank-17 pack window needs (rank 17 spans contracts 17..20).
# * `rank_start=2` — the first pack window that is ranked and tradeable.
# * `n_packs=16` — rank the sixteen windows 2..17, so **Blues (rank 13) and
#   Golds (rank 17) are inside the fitted range** rather than beyond it.
#
# Nothing else is tuned. `cost_bp_per_roundtrip` is varied across arms in
# section 7 rather than chosen.

# %%
START, END = dt.date(2021, 1, 1), dt.date(2026, 8, 20)
CFG = S2.Strat2Config(start=START, end=END,
                      rank_start=2,      # rank 1 is the roll REFERENCE, never traded (§5.1)
                      n_packs=16,        # rank 2..17 -> Blues and Golds are ranked
                      n_contracts=20)    # rank 17 spans contracts 17..20
RUN = json.loads((DATA / "w2b_run.json").read_text())

print(f"rank_start        {CFG.rank_start}")
print(f"n_packs           {CFG.n_packs}   -> ranks "
      f"{CFG.rank_start}..{CFG.rank_start + CFG.n_packs - 1}")
print(f"n_contracts       {CFG.n_contracts}")
print(f"ca_dv01           ${CFG.ca_dv01:,.0f}/bp")
print(f"rebalance_freq    {CFG.rebalance_freq}  (first business day of each month)")
print(f"max_hold_months   {CFG.max_hold_months}")
print(f"hedge_tenors      {CFG.hedge_tenors}   window {CFG.hedge_regression_days}d")
print(f"hedge_min_abs_beta {CFG.hedge_min_abs_beta}   "
      f"require_positive_wings {CFG.hedge_require_positive_wings}")
print(f"sigma_model_mode  {CFG.sigma_model_mode!r}  degree {CFG.sigma_fit_degree}")
print(f"holee_convention  {CFG.holee_convention!r}")
print(f"window            {CFG.start} .. {CFG.end}")
print(f"\nrank_metrics ({len(CFG.rank_metrics)}), top {CFG.top_n_per_metric} each:")
for m in CFG.rank_metrics:
    print(f"   {m}")

# the run artifact must have been produced by THIS config, or the numbers below
# describe a different strategy than the one documented here
for k in ("rank_start", "n_packs", "n_contracts", "ca_dv01", "rebalance_freq",
          "max_hold_months", "hedge_regression_days"):
    assert str(getattr(CFG, k)) == RUN["config"][k], (
        f"config drift on {k}: notebook {getattr(CFG, k)!r} vs run "
        f"{RUN['config'][k]!r}")
print(f"\nOK: the notebook config matches the one the backtest ran with "
      f"({RUN['n_epochs']} epochs, {RUN['dates']} marks).")

# %% [markdown]
# ## 2. Does the machine give the right answer to questions we already know?
#
# Three known answers, none of which this code was fitted to: two published
# Citi tickets with entry and exit marks, and one published regression.

# %% [markdown]
# ### 2.1 The Blues ticket — 09-Feb-2017 to 06-Jun-2017
#
# Citi published entry and exit marks for both legs and a net P&L. The CA leg's
# gross is arithmetic; the interesting part is whether **this module's own
# sizing rule**, applied to those published marks, reproduces Citi's published
# *net*.
#
# The sizing rule, from `hedge_sizing`:
#
# > *"belly_DV01 = CA_DV01 * beta / 100; wings = w2*belly, w10*belly."*
#
# and Citi's own chart annotation on the entry date was
# `CA_fitted = 9.7 + 20.6*(-0.705*2y + 5y - 0.465*10y)`, so `beta = 20.6`.

# %%
TICKET_BLUES = {
    "entry": "2017-02-09", "exit": "2017-06-06",
    "ca_entry_bp": 8.8, "ca_exit_bp": 6.6,
    "fly_entry_bp": -18.2, "fly_exit_bp": -16.5,
    "ca_dv01": 200_000.0,
    "beta": 20.6, "w2": 0.705, "w10": 0.465,
    "published_gross": 440_000.0,
    "published_net": 500_000.0,
}
T = TICKET_BLUES
ca_leg = (T["ca_entry_bp"] - T["ca_exit_bp"]) * T["ca_dv01"]
print(f"CA leg gross   ({T['ca_entry_bp']} - {T['ca_exit_bp']}) x "
      f"${T['ca_dv01']:,.0f} = ${ca_leg:,.0f}")
assert abs(ca_leg - T["published_gross"]) < 1e-6, ca_leg
print(f"  Citi published ${T['published_gross']:,.0f}  -> EXACT")

fit = S2.HedgeFit(alpha=9.7, b2=-T["w2"] * T["beta"], b5=T["beta"],
                  b10=-T["w10"] * T["beta"], beta=T["beta"],
                  w2=T["w2"], w10=T["w10"], r2=np.nan, n_obs=252, ok=True)
size = S2.hedge_sizing(fit, T["ca_dv01"])
print(f"\nhedge_sizing(beta={T['beta']}, ${T['ca_dv01']:,.0f}) -> "
      f"belly ${size['belly_dv01']:,.0f}/bp, "
      f"wings ${size['wing_2y_dv01']:,.0f} / ${size['wing_10y_dv01']:,.0f}")
CITI_BELLY_IMPLIED = 41_088.0     # published 5y notional x the era's ~$480/mn
ratio = size["belly_dv01"] / CITI_BELLY_IMPLIED
print(f"  vs Citi's published 5y notional (${CITI_BELLY_IMPLIED:,.0f}/bp): "
      f"ratio {ratio:.3f}")
assert abs(size["belly_dv01"] - 41_200.0) < 1e-6, size
assert 0.99 < ratio < 1.01, ratio

d_fly = T["fly_exit_bp"] - T["fly_entry_bp"]
hedge_leg = size["belly_dv01"] * d_fly        # bpv>0 = pay the belly = long the fly rate
recon = ca_leg + hedge_leg
print(f"\nfly {T['fly_entry_bp']} -> {T['fly_exit_bp']} = {d_fly:+.1f}bp; "
      f"paying the belly at ${size['belly_dv01']:,.0f}/bp = ${hedge_leg:+,.0f}")
print(f"reconstruction  ${ca_leg:,.0f} + ${hedge_leg:+,.0f} = ${recon:,.0f}")
print(f"Citi published net                              ${T['published_net']:,.0f}")
err = abs(recon - T["published_net"]) / T["published_net"]
print(f"error {err:.2%}")
assert err < 0.03, f"reconstruction is {err:.1%} off Citi's published net"
print("\nOK: the module's sizing rule + Citi's own published marks reproduce")
print("Citi's published net to 2%. NB this is a RECONSTRUCTION, not Citi's own")
print("decomposition — the note gives one net number and states that")
print("'Calculations do not include transaction costs and other fees'.")
print("Note also what it says about the hedge: BOTH legs made money. The fly")
print("did not offset the CA move on this trade, it added to it.")

# %% [markdown]
# ### 2.2 The Greens ticket — 06-Jun-2017, and its 13-Jul-2017 unwind of the hedge
#
# A smaller ticket, published with a target and a stop, which pins the
# $/bp arithmetic in the other direction.

# %%
TICKET_GREENS = {
    "entry": "2017-06-06", "ca_entry_bp": 4.3, "ca_dv01": 300_000.0,
    "target": 450_000.0, "stop": -225_000.0,
    "roll_3m_bp": 0.7,
    "takeoff": "2017-07-13", "ca_mid_bp": 3.35, "published_mtm": 285_000.0,
}
G = TICKET_GREENS
tgt_bp = G["target"] / G["ca_dv01"]
stp_bp = G["stop"] / G["ca_dv01"]
print(f"target +${G['target']:,.0f} on ${G['ca_dv01']:,.0f}/bp = {tgt_bp:+.2f}bp of CA")
print(f"stop   -${abs(G['stop']):,.0f} on ${G['ca_dv01']:,.0f}/bp = {stp_bp:+.2f}bp of CA")
assert abs(tgt_bp - 1.5) < 1e-9 and abs(stp_bp + 0.75) < 1e-9
print("  -> a symmetric 2:1 payoff on a 1.5bp / 0.75bp CA move")

mtm = (G["ca_entry_bp"] - G["ca_mid_bp"]) * G["ca_dv01"]
print(f"\ntake-off-hedge {G['takeoff']}: CA {G['ca_entry_bp']} -> {G['ca_mid_bp']} mid")
print(f"  CA-leg MTM ({G['ca_entry_bp']} - {G['ca_mid_bp']}) x "
      f"${G['ca_dv01']:,.0f} = ${mtm:,.0f}")
assert abs(mtm - G["published_mtm"]) < 1e-6, mtm
print(f"  Citi published ${G['published_mtm']:,.0f} -> EXACT")
print(f"\nAnd the 3m roll was published at {G['roll_3m_bp']:+.1f}bp — the carry the")
print("screen's `roll_3m_bp` column measures, and one of the eight ranking metrics.")

# %% [markdown]
# ### 2.3 The third known answer: Citi's Figure 4 on dealer positioning
#
# `ca_signals.py` carries a **published, dated, out-of-sample target**: Citi's
# *Sell Eurodollar convexity in Blues*, Figure 4 — monthly changes,
# 2013-01-01 → 2017-12-26, Eurodollars:
#
# > d(Blues CA − model) on d(dealer positioning): `y = 2e−06·x − 0.1053`,
# > R² = 0.2724
#
# The reproduction is on **SOFR, 2021–2026** — a different market, a different
# decade and a different rate regime — with our own `vs_model` residual (which
# is a cross-sectional shape dislocation, not Citi's externally-calibrated
# column; the module says so at length). Dealer positioning is CFTC TFF
# Dealer/Intermediary net for SOFR-3M, lagged 3 business days to publication.
#
# Numbers are read from the artifact `ca_positioning_regression.csv` rather than
# recomputed here.

# %%
FIG4 = pd.read_csv(DATA / "ca_positioning_regression.csv").set_index("colour")
print("Citi's published Figure 4 (Eurodollars, 2013-01..2017-12):")
print(f"   slope {CITI_FIG4_BLUES['slope']:.3g}   "
      f"intercept {CITI_FIG4_BLUES['intercept']}   R2 {CITI_FIG4_BLUES['r2']}")
print(f"\nOur reproduction on SOFR, {FIG4['window'].iloc[0]}, "
      f"{int(FIG4['n'].iloc[0])} monthly changes, HAC t:")
print(FIG4[["n", "slope", "tstat", "pvalue", "r2"]].to_string(
    float_format=lambda v: f"{v:>12.4g}"))

EXPECT = {"Reds":   (-8.336e-07, -1.66, 0.097, 0.030),
          "Greens": (-9.319e-08, -0.23, 0.815, 0.001),
          "Blues":  (+5.280e-07, +2.59, 0.010, 0.124),
          "Golds":  (-6.435e-08, -0.29, 0.770, 0.002)}
for c, (sl, t_, p_, r2_) in EXPECT.items():
    assert np.isclose(FIG4.at[c, "slope"], sl, rtol=1e-3), c
    assert np.isclose(FIG4.at[c, "tstat"], t_, atol=1e-2), c
    assert np.isclose(FIG4.at[c, "pvalue"], p_, atol=1e-3), c
    assert np.isclose(FIG4.at[c, "r2"], r2_, atol=1e-3), c

blues_slope = float(FIG4.at["Blues", "slope"])
ratio = CITI_FIG4_BLUES["slope"] / blues_slope
assert blues_slope > 0, "Blues must agree in SIGN with the published figure"
assert 1.0 < ratio <= 4.0, f"slope ratio {ratio:.2f} is outside a factor of four"
assert float(FIG4.at["Blues", "pvalue"]) < 0.05
for c in ("Greens", "Golds"):
    assert abs(float(FIG4.at[c, "tstat"])) < 2.0

print(f"\nBlues slope ratio vs Citi: {CITI_FIG4_BLUES['slope']:.3g} / "
      f"{blues_slope:.3g} = {ratio:.2f}x")
print("\nOK, and this is the headline of the section: BLUES — the colour the")
print("published figure is ABOUT — agrees in sign, is within a factor of four on")
print("slope, and is significant (t +2.59, p 0.010) on a different market a")
print("decade later. Reds is marginal with the WRONG sign; Greens and Golds are")
print("indistinguishable from nothing. One colour out of four reproduces, and it")
print("is the right one. That is evidence for the mechanism, not for a trade.")

# %% [markdown]
# ## 3. The panel: what the coverage repair bought
#
# The CA panel is the repaired one. Both panels are on disk, so the before/after
# is measured here rather than quoted: the pre-warm baseline is
# `_baseline_prewarm/strat2_q20_panel.parquet` (built before the deferred-strip
# warm and before the terminal-node fix), the rebuilt one is
# `strat2_q20_panel.parquet`.
#
# A date is *usable* for a colour when it passes the three-condition gate —
# resolution, settle agreement (max over the four contracts ≤ 2.0bp) and
# coverage. `gate_ok` is that conjunction.

# %%
base = pd.read_parquet(DATA / "_baseline_prewarm" / "strat2_q20_panel.parquet")
new = pd.read_parquet(DATA / "strat2_q20_panel.parquet")
for _df in (base, new):
    _df["date"] = pd.to_datetime(_df["date"])
    _df["year"] = _df["date"].dt.year
RANKS = [(1, "Whites"), (5, "Reds"), (9, "Greens"), (13, "Blues"), (17, "Golds")]


def coverage(df: pd.DataFrame) -> pd.DataFrame:
    d = df[df["gate_ok"]]
    rows = []
    for y in sorted(set(new["year"])):
        row = {"year": int(y)}
        for rank, colour in RANKS:
            row[colour] = int(d[(d["rank"] == rank) &
                                (d["year"] == y)]["date"].nunique())
        rows.append(row)
    return pd.DataFrame(rows).set_index("year")


B, N = coverage(base), coverage(new)
print(f"baseline {len(base):,} rows / {base['date'].nunique():,} dates   ->   "
      f"rebuilt {len(new):,} rows / {new['date'].nunique():,} dates")
print("\ngate-applied usable dates per colour per year:")
print(pd.concat({"before": B, "after": N, "delta": N - B}, axis=1).to_string())

for colour, year, before, after in (("Blues", 2023, 49, 229),
                                    ("Golds", 2023, 28, 244),
                                    ("Golds", 2026, 0, 159)):
    assert int(B.at[year, colour]) == before, (colour, year, B.at[year, colour])
    assert int(N.at[year, colour]) == after, (colour, year, N.at[year, colour])
    print(f"  {colour} {year}: {before} -> {after} usable dates")

# %% [markdown]
# ### 3.1 What was binding, and it was Golds
#
# The gate condition that moved is **settle agreement** — the Q20 forward pack
# rate against the four SR3 settles — and it moved at rank 17 and essentially
# nowhere else. That is the signature of a real fix rather than a loosened test:
# ranks the change was not supposed to touch did not move.

# %%
rows = []
for rank, colour in RANKS:
    b_, n_ = base[base["rank"] == rank], new[new["rank"] == rank]
    rows.append({"rank": rank, "colour": colour,
                 "median |diff| bp before": round(float(b_["max_settle_diff_bp"].median()), 3),
                 "median |diff| bp after": round(float(n_["max_settle_diff_bp"].median()), 3),
                 "pass rate before": round(float(b_["gate_settle_agrees"].mean()), 3),
                 "pass rate after": round(float(n_["gate_settle_agrees"].mean()), 3)})
GATE = pd.DataFrame(rows).set_index("colour")
print(GATE.to_string())

assert np.isclose(GATE.at["Golds", "median |diff| bp before"], 2.239, atol=1e-9)
assert np.isclose(GATE.at["Golds", "median |diff| bp after"], 0.669, atol=1e-9)
assert np.isclose(GATE.at["Golds", "pass rate before"], 0.446, atol=1e-9)
assert np.isclose(GATE.at["Golds", "pass rate after"], 0.990, atol=1e-9)
assert abs(GATE.at["Blues", "median |diff| bp after"]
           - GATE.at["Blues", "median |diff| bp before"]) < 0.05
print("\nOK: Golds 2.239 -> 0.669bp median, pass rate 0.446 -> 0.990.")
print("Blues, Greens and Reds moved by less than 0.05bp — the fix landed where")
print("it was aimed. THIS is why the deep packs are tradable at all now.")

# %% [markdown]
# ### 3.2 The panel this notebook actually uses
#
# Gate-filtered, 2021-01-01 .. 2026-08-20.

# %%
panel = new[new["gate_ok"]
            & (new["date"] >= pd.Timestamp(START))
            & (new["date"] <= pd.Timestamp(END))].copy()
rates = pd.read_parquet(DATA / "strat2_q20_rates.parquet")
rates.index = pd.to_datetime(rates.index)
assert bool(panel["gate_ok"].all()), "an ungated row survived the filter"
print(f"panel {panel.shape}, {panel['date'].nunique():,} dates "
      f"{panel['date'].min().date()} .. {panel['date'].max().date()}")
print(f"rates {rates.shape}, columns {list(rates.columns)}")
print("\nusable dates per colour, this window:")
print(panel.groupby("colour")["date"].nunique().to_string())
assert panel["date"].nunique() == RUN["dates"], (
    f"panel has {panel['date'].nunique()} dates, the run marked {RUN['dates']}")

# %% [markdown]
# ## 4. The sign probe
#
# Re-derived from the measured book on every run rather than trusted from a
# comment, and computed **offline** — the exemplar's live-MDP probe is replaced
# here by a probe against the equity curve the backtest actually produced,
# because that tests the traded book rather than a re-priced replica of it.
#
# Short convexity is *buy the pack, pay the matched swap*. Long the future gains
# when the pack rate falls; paying the swap gains when the swap rate rises. With
# `CA = pack_rate − swap_rate` and a DV01-neutral package:
#
# $$\mathrm{P\&L} \approx -\Delta \mathrm{CA(bp)} \times \mathrm{CA\_DV01}$$
#
# So the book must **make money when the CA falls**. Each epoch's realised P&L
# is the change in the unhedged zero-cost equity curve between its entry and
# exit marks (the book holds exactly one epoch at a time).

# %%
ts = S2.panel_timeseries(panel, CFG)
model = S2.model_timeseries(panel, CFG)
SPECS = S2.plan_epochs(panel, rates, CFG, ts=ts, model=model, verbose=False)
print(f"{len(SPECS)} epochs planned")
assert len(SPECS) == RUN["n_epochs"], (
    f"plan_epochs is not reproducing the run: {len(SPECS)} vs {RUN['n_epochs']}")

ARMS = {}
MISSING = []
for tag in ("unhedged_zero_cost", "unhedged_base", "unhedged_cost_1bp",
            "hedged_zero_cost", "hedged_base", "hedged_cost_1bp"):
    f = DATA / f"w2b_equity_{tag}.parquet"
    if f.exists():
        e = pd.read_parquet(f)["equity"].sort_index()
        e.index = pd.to_datetime(e.index)
        ARMS[tag] = e
    else:
        MISSING.append(tag)
print(f"loaded arms: {list(ARMS)}")
if MISSING:
    print(f"ABSENT (not run / still in flight): {MISSING}")
assert "unhedged_zero_cost" in ARMS and "hedged_zero_cost" in ARMS, (
    "the zero-cost arms are the ones every comparison below is built on")

U, H = ARMS["unhedged_zero_cost"], ARMS["hedged_zero_cost"]
assert U.index.equals(H.index)
ca_wide = ts["ca"]
rows = []
for s in SPECS:
    e, x = pd.Timestamp(s.entry), pd.Timestamp(s.exit)
    if e not in U.index or x not in U.index or s.pack not in ca_wide.columns:
        continue
    ce, cx = ca_wide.at[e, s.pack], ca_wide.at[x, s.pack]
    rows.append({"pack": s.pack, "rank": s.rank, "entry": e, "exit": x,
                 "ca_entry_bp": ce, "ca_exit_bp": cx, "d_ca_bp": cx - ce,
                 "predicted": -(cx - ce) * s.ca_dv01,
                 "realised": float(U.loc[x] - U.loc[e])})
EP = pd.DataFrame(rows).dropna(subset=["d_ca_bp"])
corr = float(EP["realised"].corr(EP["predicted"]))
agree = float((np.sign(EP["realised"]) == np.sign(EP["predicted"])).mean())
slope, icept = np.polyfit(EP["predicted"], EP["realised"], 1)
print(f"\n{len(EP)} epochs   corr(realised, -dCA x DV01) {corr:+.4f}   "
      f"sign agreement {agree:.3f}")
print(f"slope {slope:+.3f}   intercept ${icept:+,.0f}")
print(f"sum predicted ${EP['predicted'].sum():,.0f}   "
      f"sum realised ${EP['realised'].sum():,.0f}")
print(EP.head(6).to_string(index=False))

assert corr > 0.80, f"the book does not track -dCA: corr {corr:.3f}"
assert agree > 0.85, f"sign agreement only {agree:.3f}"
assert slope > 0, "the book is the WRONG WAY ROUND on the convexity adjustment"
print("\nOK: the traded book is short the convexity adjustment — it makes money")
print("when CA falls, on 93% of epochs and at correlation 0.84.")
print("\nThe slope is 0.90, not 1.00, and the module docstring says why:")
print("  'the measured adjustment now uses the Q/Q swap, but the swap leg that")
print("   is actually traded in the backtest is built as an IRSwapQuery and")
print("   therefore still prices at the curve spec's annual-fixed convention.'")
print("Add DV01-neutrality that holds only at entry, plus roll and carry inside")
print("the hold, and a slope near but below 1 is the expected reading.")

# %% [markdown]
# ## 5. What this config actually trades

# %%
holds = pd.Series([int(np.busday_count(s.entry, s.exit)) for s in SPECS])

# the rebalance calendar, snapped forward onto available panel days exactly as
# plan_epochs does it
days = pd.DatetimeIndex(sorted(panel["date"].unique()))
MARKS = []
for c in pd.date_range(days[0], days[-1], freq=CFG.rebalance_freq):
    nxt = days[days >= c]
    if len(nxt) and (not MARKS or nxt[0] != MARKS[-1]):
        MARKS.append(nxt[0])

funnel = pd.DataFrame({
    "panel rows (gate_ok)": [len(panel)],
    "panel dates": [int(panel["date"].nunique())],
    "ranked packs per date": [CFG.n_packs],
    "rebalance marks": [len(MARKS)],
    "epochs": [len(SPECS)],
    "epochs with a usable fly": [sum(1 for s in SPECS
                                     if s.hedge is not None and s.hedge.ok)],
    "epochs the fly was skipped": [sum(1 for s in SPECS
                                       if s.hedge is None or not s.hedge.ok)],
    "daily marks": [len(U)],
}).T.rename(columns={0: "n"})
print(funnel.to_string())
print(f"\nhold bdays: median {holds.median():.0f}  mean {holds.mean():.1f}  "
      f"max {holds.max()}")

COLOURS = {5: "Reds", 9: "Greens", 13: "Blues", 17: "Golds"}
LOG = pd.DataFrame([{
    "entry": pd.Timestamp(s.entry), "exit": pd.Timestamp(s.exit),
    "pack": s.pack, "rank": s.rank,
    "colour": COLOURS.get(s.rank, "(between colours)"),
    "n_flags": s.n_flags, "ca_entry_bp": s.ca_entry_bp,
    "beta": s.hedge.beta if s.hedge else np.nan,
    "hedge_r2": s.hedge.r2 if s.hedge else np.nan,
    "hedge_ok": bool(s.hedge.ok) if s.hedge else False,
    "hedge_reason": s.hedge.reason if s.hedge else "",
    "belly_dv01": (s.hedge_dv01 or {}).get("belly_dv01", np.nan),
    "bdays": int(np.busday_count(s.entry, s.exit)),
} for s in SPECS])
LOG["year"] = LOG["entry"].dt.year

print("\nselected rank, by year:")
print(LOG.groupby("year")["rank"].agg(["count", "mean", "min", "max"]).round(2).to_string())
print("\nselected colour:")
print(LOG["colour"].value_counts().to_string())
assert int(LOG["rank"].min()) >= CFG.rank_start

# %% [markdown]
# ### 5.1 Whites cannot be modelled, and that is structural
#
# `Strat2Config` refuses `rank_start < 2`:
#
# > *"1-indexed rank of the FIRST pack window that is ranked and tradeable.
# > Windows below this are still computed: window `rank_start-1` is what the
# > 3m roll of the first ranked pack is measured against, so `rank_start` can
# > never be 1."*
#
# The 3m roll is one of the eight ranking metrics and it is defined as
# `CA(p) − CA(p−1)`. Rank 1 has no nearer pack to difference against, so it has
# no roll, so it cannot be ranked. **This is not a coverage gap** — the Whites
# window is built, priced and carried on every date in the panel; it is the
# reference the roll of rank 2 is measured against. The constraint is enforced
# in `__post_init__` and is asserted live below.

# %%
try:
    S2.Strat2Config(start=START, end=END, rank_start=1, n_packs=16, n_contracts=20)
    raise AssertionError("rank_start=1 was accepted; the roll has no reference")
except ValueError as exc:
    print(f"Strat2Config(rank_start=1) -> ValueError: {exc}")
    assert "rank_start must be >= 2" in str(exc)

whites = panel[panel["rank"] == 1]
print(f"\nWhites rows in the gated panel: {len(whites):,} over "
      f"{whites['date'].nunique():,} dates — built and priced, never ranked.")
assert len(whites) > 0, "Whites is absent from the panel, which WOULD be a gap"
assert (LOG["rank"] != 1).all()

# %% [markdown]
# ### 5.2 The deep packs are reachable now — and the screen still rarely picks them
#
# This is the finding that section 3's repair makes possible to state. On every
# rebalance mark the screen is recomputed and its reach recorded.

# %%
rows = []
for m in MARKS:
    sc = S2.daily_screen(m.date(), panel, CFG, ts=ts, model=model)
    if sc.empty:
        continue
    rows.append({"date": m, "n_packs": len(sc), "max_rank": int(sc["rank"].max()),
                 "reaches_Blues": bool((sc["rank"] >= 13).any()),
                 "reaches_Golds": bool((sc["rank"] == 17).any()),
                 "z1y_usable": bool(np.isfinite(sc["vs_model_z1y"]).any())})
SCREENS = pd.DataFrame(rows)
print(f"{len(SCREENS)} rebalance marks")
print(SCREENS.groupby(SCREENS["date"].dt.year)[
    ["reaches_Blues", "reaches_Golds", "z1y_usable"]].mean().round(3).to_string())
print(f"\noverall: Blues rank reachable on {SCREENS['reaches_Blues'].mean():.1%} of "
      f"marks, Golds on {SCREENS['reaches_Golds'].mean():.1%}, "
      f"1Y z-score usable on {SCREENS['z1y_usable'].mean():.1%}")

n_blues = int((LOG["rank"] == 13).sum())
n_golds = int((LOG["rank"] == 17).sum())
n_between = int((LOG["colour"] == "(between colours)").sum())
print(f"\nand yet, of {len(LOG)} epochs: Blues selected {n_blues}x, "
      f"Golds {n_golds}x, {n_between} land BETWEEN the named colours.")

assert SCREENS["reaches_Blues"].mean() == 1.0, "Blues must be reachable everywhere"
assert SCREENS["reaches_Golds"].mean() > 0.95
assert n_golds == 0, "the text below has to change if Golds is ever selected"
print("\nThe repair restored REACHABILITY, not selection. Rank 17 is on the")
print("screen on 97% of marks and is never the winner; the eight metrics are")
print("z-scores, model residuals and rolls, all cross-sectional, and they keep")
print("choosing ranks 2-8. 2021 selects nothing at all: the 1Y z-score needs")
print("252 observations and the panel is filtered from 2021-01-01, so the first")
print("epoch enters 2022-02-01.")

# %% [markdown]
# ## 6. How this config performed
#
# Priced by `QueryDrivenBacktest`, daily mark-to-market, every leg through the
# engine: four SR3 outright futures legs + the matched-maturity swap
# (+ the 2s5s10s fly on the hedged arms). `run()` swallows exceptions and
# prints them, so a failing backtest is indistinguishable from a flat equity
# curve; the run script asserted on the artifacts through `assert_ran`.

# %%
def perf(eq: pd.Series, label: str) -> dict:
    r = eq.diff().dropna()
    span = (eq.index[-1] - eq.index[0]).days / 365.25
    return {"arm": label,
            "terminal": float(eq.iloc[-1]),
            "ann_sharpe": float(r.mean() / r.std() * np.sqrt(252)) if r.std() > 0 else np.nan,
            "ann_pnl": float(eq.iloc[-1] / span),
            "max_dd": float((eq - eq.cummax()).min()),
            "span_years": span}


PERF = pd.DataFrame([perf(e, k) for k, e in ARMS.items()]).set_index("arm")
print(PERF.to_string(float_format=lambda v: f"{v:>15,.3f}"))

CSV = pd.read_csv(DATA / "w2b_arms.csv").set_index("arm")
for arm in PERF.index:
    assert np.isclose(PERF.at[arm, "terminal"], CSV.at[arm, "terminal"], rtol=1e-9), arm
    assert np.isclose(PERF.at[arm, "ann_sharpe"], CSV.at[arm, "sharpe"], rtol=1e-9), arm
print("\nOK: recomputed from the equity parquets, ties out to w2b_arms.csv on "
      "every arm.")

SPAN = float(PERF.at["unhedged_zero_cost", "span_years"])
GROSS_SR = float(PERF.at["unhedged_zero_cost", "ann_sharpe"])
assert PERF["max_dd"].max() < 0, "a book with no drawdown has not been marked"
print(f"\nGross (zero-cost, unhedged): ${PERF.at['unhedged_zero_cost', 'terminal']:,.0f} "
      f"over {SPAN:.2f}y, Sharpe {GROSS_SR:.3f}, "
      f"max drawdown ${PERF.at['unhedged_zero_cost', 'max_dd']:,.0f}.")
print(f"Drawdown is {abs(PERF.at['unhedged_zero_cost', 'max_dd']) / PERF.at['unhedged_zero_cost', 'terminal']:.2f}x "
      "the terminal P&L, before a single basis point of cost.")

# %%
Y = pd.DataFrame({
    "unhedged": ARMS["unhedged_zero_cost"].resample("YE").last().diff(),
    "hedged": ARMS["hedged_zero_cost"].resample("YE").last().diff()})
Y.iloc[0] = [ARMS["unhedged_zero_cost"].resample("YE").last().iloc[0],
             ARMS["hedged_zero_cost"].resample("YE").last().iloc[0]]
print("P&L by year, zero cost:")
print(Y.to_string(float_format=lambda v: f"{v:>14,.0f}"))
assert abs(float(Y.loc[Y.index[0], "unhedged"])) < 1.0, (
    "2021 should be exactly flat — no epoch is entered until the 1Y z-score warms")
print("\n2021 is EXACTLY flat by construction (§5.2). One year, 2024, supplies")
print(f"${float(Y['unhedged'].max()):,.0f} of a ${float(ARMS['unhedged_zero_cost'].iloc[-1]):,.0f} "
      "total — the book is one good year and four indifferent ones.")

# %% [markdown]
# ## 7. Costs
#
# The cost model here is **one fee per epoch, charged at the unwind**:
# `fee = cost_bp_per_roundtrip x ca_dv01`, applied by `UnwindPositionsAction`.
# That is a round-trip charge on the CA leg's DV01 and it does **not** scale
# with the number of legs — so it is the *cheap* convention, and the futures
# legs and the fly ride free.
#
# Citi excludes costs explicitly (*"Calculations do not include transaction
# costs and other fees"*), so the zero-cost arm reproduces their convention and
# the other two price it honestly.

# %%
NEED = ("unhedged_zero_cost", "unhedged_base", "unhedged_cost_1bp")
assert all(a in ARMS for a in NEED), (
    f"this section needs {NEED}; missing {[a for a in NEED if a not in ARMS]} — "
    "re-run _w2b_ca_vs_fly_run.py rather than reading a partial comparison")
gross = float(ARMS["unhedged_zero_cost"].iloc[-1])
net05 = float(ARMS["unhedged_base"].iloc[-1])
net10 = float(ARMS["unhedged_cost_1bp"].iloc[-1])
costs = gross - net05
n_ep = len(SPECS)
fee = 0.5 * CFG.ca_dv01
print(f"gross (0.0bp)             {gross:>15,.0f}")
print(f"net   (0.5bp)             {net05:>15,.0f}")
print(f"net   (1.0bp)             {net10:>15,.0f}")
print(f"costs at 0.5bp            {costs:>15,.0f}   ({costs / gross:.1%} of gross)")
print(f"  = {n_ep} epochs x ${fee:,.0f}")
assert abs(costs - n_ep * fee) < 1.0, (costs, n_ep * fee)
be = 0.5 * gross / costs
print(f"\nbreak-even round trip     {be:.4f} bp of the ${CFG.ca_dv01:,.0f} CA DV01")
print(f"charged in the base arm   0.5000 bp   -> {0.5 / be:.2f}x the break-even")
assert net05 > 0 > net10, "the 0.5/1.0bp arms should straddle zero"
print("\nThe strategy pays for itself at 0.55bp round trip and is negative at")
print("1bp. Block 1 measured the same crossing point on a different panel:")
print("'at 1bp both do [go negative]'. Costs are not what kills this — section")
print("9 is — but they leave nothing standing either way.")

for arm in ("hedged_zero_cost", "hedged_base", "hedged_cost_1bp"):
    if arm in ARMS:
        print(f"  {arm:22} {float(ARMS[arm].iloc[-1]):>15,.0f}")

# %% [markdown]
# ## 8. Does the fly hedge anything?
#
# The brief for this block is explicit that it should not be assumed to. Block 1
# of this workstream measured this hedge at **R² 0.000–0.010 with a
# sign-flipping β, losing $606k** (carried from the brief; a different window
# and a different panel, not re-measured here), and the factor attribution said
# the tight pairs need a PC1 hedge and this is a PC2 one.
#
# Below is the measurement on **this** book.

# %%
du = U.diff().dropna()
dh = H.diff().dropna()
hedge_pnl = (H - U).diff().dropna()
vr = 1.0 - float(dh.var() / du.var())
r2 = float(du.corr(hedge_pnl)) ** 2
X = sm.add_constant(hedge_pnl.to_numpy())
hfit = sm.OLS(du.to_numpy(), X).fit(cov_type="HAC", cov_kwds={"maxlags": 5})

print(f"terminal unhedged      {float(U.iloc[-1]):>15,.0f}")
print(f"terminal hedged        {float(H.iloc[-1]):>15,.0f}")
print(f"the fly leg contributed{float(H.iloc[-1] - U.iloc[-1]):>15,.0f}")
print(f"\ndaily sd unhedged      {float(du.std()):>15,.0f}")
print(f"daily sd hedged        {float(dh.std()):>15,.0f}")
print(f"variance reduction     {vr:>15.4f}")
print(f"R2 of the fly leg against the unhedged P&L      {r2:.4f}")
print(f"OLS unhedged ~ fly leg: slope {float(hfit.params[1]):+.3f}  "
      f"t {float(hfit.tvalues[1]):+.2f}  R2 {float(hfit.rsquared):.4f}")

n_ok = int(LOG["hedge_ok"].sum())
n_pos = int((LOG["beta"] > 0).sum())
n_neg = int((LOG["beta"] < 0).sum())
print(f"\nof {len(LOG)} epochs the trailing regression was expressible as a fly on "
      f"{n_ok}; {len(LOG) - n_ok} were skipped and recorded:")
why = LOG.loc[~LOG["hedge_ok"], "hedge_reason"]
n_wing = int(why.str.startswith("wing weight").sum())
n_beta = int(why.str.startswith("|beta|").sum())
print(f"   wing weight not expressible as a fly   {n_wing:>3}")
print(f"   |beta| below {CFG.hedge_min_abs_beta}                      {n_beta:>3}")
assert n_wing + n_beta == len(why), "an unclassified skip reason"
sgn = np.sign(LOG["beta"].to_numpy())
n_flip = int((sgn[1:] != sgn[:-1]).sum())
print(f"\nbeta sign: {n_pos} positive, {n_neg} negative, reversing at {n_flip} of "
      f"{len(sgn) - 1} epoch-to-epoch\nhandovers ({n_flip / (len(sgn) - 1):.0%})")
print(f"beta range {LOG['beta'].min():+.1f} .. {LOG['beta'].max():+.1f}")
print(f"trailing-regression R2: min {LOG['hedge_r2'].min():.3f}  "
      f"median {LOG['hedge_r2'].median():.3f}  max {LOG['hedge_r2'].max():.3f}")

assert abs(vr) < 0.05, f"variance reduction {vr:.4f} is larger than 'nothing'"
assert r2 < 0.05, r2
assert n_pos > 5 and n_neg > 5, "beta is supposed to be sign-unstable here"
print("\nVERDICT: the 2s5s10s fly removes 0.6% of the variance and $88k of the")
print("money. It is not a hedge on this book. The mechanism is visible in the")
print("betas: Citi fitted Blues at beta ~20.6 with a stable sign and reported")
print("90% correlation in levels; the packs this screen selects give a beta")
print(f"spanning {LOG['beta'].min():+.0f} to {LOG['beta'].max():+.0f}, reversing "
      f"sign at {n_flip} of {len(sgn) - 1} handovers, and a wing weight")
print(f"that cannot be expressed as a fly at all on {n_wing} epochs.")

# %% [markdown]
# ### 8.1 What the P&L is actually exposed to
#
# Daily P&L on the level / slope / curvature of the 2s-5s-10s rates the hedge
# is built from, plus a squared-level term as a crude convexity proxy. HAC
# t-stats, flat days dropped.

# %%
r = rates.reindex(U.index).ffill()
F = pd.DataFrame({"level": r.mean(axis=1) * 100.0,
                  "slope": (r["10Y"] - r["2Y"]) * 100.0,
                  "curv": (2 * r["5Y"] - r["2Y"] - r["10Y"]) * 100.0}).diff()
F["level_sq"] = F["level"] ** 2
ATTR_DF = pd.concat([U.diff().rename("pnl"), F], axis=1).dropna()
ATTR_DF = ATTR_DF[ATTR_DF["pnl"] != 0]
rows = []
for cols in (["level"], ["slope"], ["curv"], ["level_sq"],
             ["level", "slope", "curv"], ["level", "slope", "curv", "level_sq"]):
    X = sm.add_constant(ATTR_DF[cols].to_numpy())
    fit_ = sm.OLS(ATTR_DF["pnl"].to_numpy(), X).fit(cov_type="HAC",
                                                    cov_kwds={"maxlags": 5})
    row = {"factors": "+".join(cols), "R2": round(float(fit_.rsquared), 4)}
    for i, c in enumerate(cols):
        row[f"t({c})"] = round(float(fit_.tvalues[i + 1]), 2)
    rows.append(row)
ATTR = pd.DataFrame(rows).set_index("factors")
print(f"{len(ATTR_DF)} non-flat days")
print(ATTR.to_string())

full_r2 = float(ATTR.at["level+slope+curv+level_sq", "R2"])
t_curv_alone = float(ATTR.at["curv", "t(curv)"])
t_curv_joint = float(ATTR.at["level+slope+curv+level_sq", "t(curv)"])
assert full_r2 < 0.05, full_r2
assert abs(t_curv_alone) > abs(t_curv_joint)
print(f"\nThe four factors together explain {full_r2:.1%} of the daily P&L.")
print(f"Curvature is the only one significant on its own (t {t_curv_alone:+.2f}) "
      f"and it falls\nto t {t_curv_joint:+.2f} once level and slope are in. A "
      "2s5s10s fly is a bet on that\ncurvature factor — so section 8's result is "
      "not a surprise: the fly cannot\nhedge a P&L that does not load on the "
      "curve it is built from.")

# %% [markdown]
# ### 8.2 The short-gamma signature, which is NOT identified here
#
# A short-convexity book should lose when the underlying realises. Measured at
# epoch level on 45 observations.

# %%
rows = []
for s in SPECS:
    e, x = pd.Timestamp(s.entry), pd.Timestamp(s.exit)
    if e not in U.index or x not in U.index or s.pack not in ts["pack_rate"].columns:
        continue
    pr = ts["pack_rate"][s.pack].loc[e:x].dropna()
    if len(pr) < 5:
        continue
    rows.append({"pack": s.pack, "pnl": float(U.loc[x] - U.loc[e]),
                 "rv_epoch_bp": float(pr.diff().dropna().std() * 100.0 * math.sqrt(252))})
GAM = pd.DataFrame(rows)
X = sm.add_constant(GAM["rv_epoch_bp"].to_numpy())
fg = sm.OLS(GAM["pnl"].to_numpy(), X).fit()
print(f"{len(GAM)} epochs   corr(epoch P&L, realised vol over the epoch) "
      f"{float(GAM['pnl'].corr(GAM['rv_epoch_bp'])):+.4f}")
print(f"slope ${float(fg.params[1]):,.0f} per bp/yr of realised vol   "
      f"t {float(fg.tvalues[1]):+.2f}   R2 {float(fg.rsquared):.4f}")
assert float(fg.params[1]) < 0, "the sign is at least the right way round"
print("\nThe SIGN is right — more realised vol, less money — and the t-stat is")
print("-0.71 on 45 epochs, so it is NOT identified. State it that way: this is")
print("an underpowered test, not evidence that the book is not short gamma.")

# %% [markdown]
# ## 9. What the search cost — and why this is dead
#
# **Read this before section 6.** Positions are held a mean of ~26 business
# days, so 1,406 daily marks are not 1,406 independent observations and 45
# epochs are not 45 independent bets on 45 different things.

# %%
mean_hold = float(holds.mean())
n_eff = SPAN * 252.0 / mean_hold
N_OBS = int(round(n_eff))           # rounded, not truncated, to match the write-up
print(f"span {SPAN:.2f}y   mean hold {mean_hold:.1f} bdays   "
      f"-> n_eff ~ {n_eff:.1f} -> {N_OBS} independent holds")
print(f"(sanity check: the book planned {len(SPECS)} epochs, so n_eff and the "
      "epoch count agree to within 20%)")

NULL = pd.DataFrame([{"trials": N,
                      "E[max SR | null]": expected_max_sharpe_under_null(
                          N, n_obs=N_OBS)}
                     for N in (1, 2, 6, 12, 24, 48, 1569)])
print("\n" + NULL.round(3).to_string(index=False))

null_6 = float(NULL.loc[NULL["trials"] == 6, "E[max SR | null]"].iloc[0])
null_grid = float(NULL.loc[NULL["trials"] == 1569, "E[max SR | null]"].iloc[0])
net_sr = float(PERF.at["unhedged_base", "ann_sharpe"])
print(f"\ngross Sharpe (zero cost, unhedged)  {GROSS_SR:.3f}")
print(f"net Sharpe   (0.5bp,     unhedged)  {net_sr:.3f}")
print(f"E[max SR | null], 6 trials          {null_6:.3f}")
print(f"E[max SR | null], 1,569 trials      {null_grid:.3f}")

assert GROSS_SR < null_6, (
    "the gross Sharpe now clears the 6-trial null; the verdict needs re-deriving")
assert GROSS_SR < null_grid
print("\nSix trials is this notebook alone — two hedge modes x three cost")
print("levels. The honest count is far larger: the same family was grid-searched")
print("at 1,890 cells / 1,569 scored (strat2_gridsearch_verdict.json), whose own")
print("winner was reported at Sharpe 1.329 against E[max SR|no skill] 0.692.")
print(f"At 1,569 trials a zero-edge strategy is EXPECTED to produce "
      f"{null_grid:.3f} here.")
print(f"This one produces {GROSS_SR:.3f} gross, before costs.")

# %%
# the same computation restricted to the window in which the book actually held
# a position: fewer independent holds, so a HIGHER null. It fails there too.
t0 = pd.Timestamp(min(s.entry for s in SPECS))
sub_u = U.loc[t0:]
span_traded = (sub_u.index[-1] - t0).days / 365.25
n_eff_traded = span_traded * 252.0 / mean_hold
sr_traded = float(sub_u.diff().dropna().mean() / sub_u.diff().dropna().std() * np.sqrt(252))
sr_traded_h = float(H.loc[t0:].diff().dropna().mean()
                    / H.loc[t0:].diff().dropna().std() * np.sqrt(252))
null_6_traded = expected_max_sharpe_under_null(6, n_obs=int(round(n_eff_traded)))
print(f"traded window {t0.date()} .. {sub_u.index[-1].date()}  "
      f"({span_traded:.2f}y, {len(sub_u)} marks)")
print(f"  Sharpe unhedged {sr_traded:.4f}   hedged {sr_traded_h:.4f}")
print(f"  n_eff {n_eff_traded:.1f}  ->  E[max SR | null] at 6 trials "
      f"{null_6_traded:.3f}")
assert sr_traded < null_6_traded, "the traded-window Sharpe clears its own null"
print("\nDropping the flat year RAISES the Sharpe to 0.144 and raises the null")
print("it has to clear to 0.198, because there are fewer independent holds in a")
print("shorter window. It fails on both windows.")

# %% [markdown]
# ## 10. Robustness
#
# The equity paths, and the drawdown that the Sharpe alone does not convey.

# %%
try:
    from BT.trade_dashboard import compare_curves
    fig = compare_curves({k: v for k, v in ARMS.items()},
                         title="W2b — CA vs 2s5s10s fly")
    fig.show()
except Exception as exc:                                          # noqa: BLE001
    print(f"compare_curves unavailable ({type(exc).__name__}: {exc}); "
          "plotting directly")
    import plotly.graph_objects as go
    fig = go.Figure()
    for k, v in ARMS.items():
        dash = "dot" if k.startswith("hedged") else "solid"
        fig.add_trace(go.Scatter(x=v.index, y=v.to_numpy(), name=k, mode="lines",
                                 line={"dash": dash}))
    fig.add_hline(y=0, line_width=1, line_color="#888")
    fig.update_layout(title="W2b — pack CA vs 2s5s10s fly, six arms",
                      yaxis_title="cumulative MTM, USD", height=460,
                      legend={"orientation": "h", "y": -0.18})
    fig.show()

# %%
dd = U - U.cummax()
print(f"time in drawdown        {float((dd < 0).mean()):.1%} of marks")
print(f"worst drawdown          ${float(dd.min()):,.0f}")
print(f"terminal (gross)        ${float(U.iloc[-1]):,.0f}")
print(f"drawdown / terminal      {abs(float(dd.min()) / float(U.iloc[-1])):.2f}x")

# leave-one-year-out on the gross arm
rows = []
for y in sorted(set(U.index.year)):
    keep = U.diff().dropna()
    keep = keep[keep.index.year != y]
    rows.append({"drop": y, "terminal_ex": float(keep.sum()),
                 "sharpe_ex": float(keep.mean() / keep.std() * np.sqrt(252))})
LOO = pd.DataFrame(rows).set_index("drop")
print("\nleave-one-year-out, gross arm:")
print(LOO.to_string(float_format=lambda v: f"{v:>14,.3f}"))
worst = LOO["terminal_ex"].idxmin()
print(f"\nDropping {worst} alone takes the gross book from "
      f"${float(U.iloc[-1]):,.0f} to ${LOO.at[worst, 'terminal_ex']:,.0f} — "
      f"{1 - LOO.at[worst, 'terminal_ex'] / float(U.iloc[-1]):.0%} of the P&L "
      "is in one year.")
assert LOO["sharpe_ex"].min() < GROSS_SR, "no year can be dropped without effect"
assert abs(LOO.at[2021, "terminal_ex"] - float(U.iloc[-1])) < 1.0, (
    "2021 is flat, so dropping it must not move the terminal")
print("Dropping the flat 2021 leaves the terminal untouched by construction and")
print(f"RAISES the Sharpe to {LOO.at[2021, 'sharpe_ex']:.3f}, which is the "
      f"traded-window figure of §9 ({sr_traded:.3f})")
print(f"to within {abs(LOO.at[2021, 'sharpe_ex'] - sr_traded):.3f} — the same "
      "statement made two ways. Every other year")
print("moves the terminal, and one of them is the result.")

# %% [markdown]
# ## 11. Trade log
#
# Every epoch, with the hedge the trailing regression asked for and whether it
# could be expressed as a fly.

# %%
SHOW = LOG[["entry", "exit", "bdays", "pack", "rank", "colour", "n_flags",
            "ca_entry_bp", "beta", "hedge_r2", "hedge_ok", "belly_dv01"]].copy()
SHOW["entry"] = SHOW["entry"].dt.date
SHOW["exit"] = SHOW["exit"].dt.date
print(f"{len(SHOW)} epochs")
print(SHOW.to_string(index=False, float_format=lambda v: f"{v:>10.3f}"))

# %%
EPX = EP.merge(LOG[["entry", "colour", "hedge_ok"]], on="entry", how="left")
print("realised P&L by selected colour (unhedged, zero cost):")
print(EPX.groupby("colour")["realised"].agg(
    ["count", "sum", "median"]).to_string(float_format=lambda v: f"{v:>14,.0f}"))
print("\nbest and worst five epochs:")
print(EPX.nlargest(5, "realised")[
    ["pack", "rank", "entry", "exit", "d_ca_bp", "realised"]].to_string(index=False))
print(EPX.nsmallest(5, "realised")[
    ["pack", "rank", "entry", "exit", "d_ca_bp", "realised"]].to_string(index=False))

# %% [markdown]
# ## 12. Reading this notebook
#
# * **The result is negative and the failure is in the gross number.** Gross
#   Sharpe 0.130 over 5.62 years; a zero-edge strategy searched over six arms is
#   expected to produce 0.177, and over the 1,569 scored cells this family was
#   actually searched at, 0.460. Costs then take the book to +$233k at 0.5bp and
#   −$2.0mn at 1bp, with a break-even of 0.55bp round trip on the CA DV01 —
#   under a cost convention that charges **one fee per epoch** and lets the four
#   futures legs and the fly ride free.
#
# * **The panel repair is real and it is the reason this block exists.** Blues
#   went from 49 usable dates in 2023 to 229; Golds from 28 to 244, and from 0
#   to 159 in 2026. The binding condition was settle agreement at rank 17, whose
#   median disagreement fell 2.239 → 0.669bp and whose pass rate rose 0.446 →
#   0.990, while the ranks the fix was not aimed at moved by less than 0.05bp.
#
# * **Reachability is not selection.** With ranks 2–17 all ranked, the Blues
#   rank is on the screen on 100% of rebalance marks and Golds on 97% — and the
#   screen selects Blues twice, Greens once and Golds *never*, with 35 of 45
#   selections landing between the named colours. The packs Citi traded are now
#   reachable; this ranking rule does not go there.
#
# * **Whites cannot be modelled, and that is structural, not a gap.** The 3m
#   roll is `CA(p) − CA(p−1)`; rank 1 has no nearer pack. `Strat2Config` refuses
#   `rank_start < 2` and the Whites window is built and priced on every panel
#   date as the roll's reference.
#
# * **The fly is not a hedge on this book.** It removes 0.6% of the variance
#   (R² 0.008 against the unhedged P&L) and $88k of the money; β spans −67 to
#   +81 and reverses sign at 14 of 44 epoch handovers, and 17 of 45 epochs could
#   not be expressed as a fly at all.
#   The reason is in §8.1: level, slope, curvature and a squared-level term
#   explain 2.4% of the daily P&L in total. There is no curve exposure there for
#   a curve trade to remove. This agrees with Block 1's independent measurement
#   on a different panel (R² 0.000–0.010, sign-flipping β, −$606k).
#
# * **What the tie-outs establish, and what they do not.** The module's own
#   sizing rule applied to Citi's published marks reproduces Citi's published
#   net P&L to 2% on the Blues ticket and its CA-leg MTM exactly on the Greens
#   one, and Citi's Figure 4 regression reproduces on SOFR a decade later *in
#   Blues, the colour the figure is about* (t +2.59, slope within a factor of
#   3.8), and in no other colour. The port is faithful. What does not survive is
#   the trade.
#
# * **What would have to change.** Not the cost assumption and not the hedge
#   tenors. §8.1 says the P&L has almost no linear curve exposure, so a
#   different fly will not help; and §9 says the gross number is already below
#   its own null, so no variance reduction rescues it. If a hedge is wanted at
#   all, the factor attribution points at **PC1, not curvature** —
#   `factor_neutral_sizing.curve_weights(..., neutralize=("PC1",))` computes it,
#   and a 2s5s10s fly is not it. Beyond that a live version would need a
#   selection rule that actually reaches the deep packs the repair has now made
#   available, and far fewer, larger, longer holds so that `n_eff` rises.
#
# Full write-up: `docs/convexityrv/results/w2b-ca-vs-swap-fly.md`.
