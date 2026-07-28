# Fly-vs-Vol RV Framework — Design

**Date:** 2026-07-28
**Status:** Approved (worked example U26-Z26-H27 @ 2026-07-27 validated the metric stack end-to-end)
**Branch:** `feat/fly-vs-vol-rv`

## Problem

SOFR butterflies price the *velocity* of the policy path: a +7.5bp U26-Z26-H27 fly is read by
practitioners as "+30% probability of one extra hike in the U26→Z26 window vs the Z26→H27
window" (fly / 25bp). SOFR option implied distributions price the *probability of the short
rate actually getting to* any given level. Both markets price the same random path; the fly is
the risk-neutral **mean** of a path functional, the options carry its **shape**. This framework
compares the two systematically to find relative value.

## Core identity and conventions

- Contract rate `f_i` = quarterly SR3 futures rate (`100 − price`), percent.
- Window changes `Δ1 = f_belly − f_front`, `Δ2 = f_back − f_belly` (positive = hikes).
- **Fly (bp) = 2·f_belly − f_front − f_back = Δ1 − Δ2** — identical to the CME price fly
  (+1/−2/+1), identical to the Query layer `FLY RATE`, identical to desk quotes.
  (`BT/signals/sfr_cal_spread_rv.compute_fly_curve` is the *opposite* sign; not used here.)
- Per contract `i`, BL RND `Q_i` with CDF `F_i` from `SFRImpliedDistribution(anchor_wings=True)`
  (JPM raw-premium BL, OTM, OI ≥ 100). `mean(Q_i) ≈ f_i` up to fit error (`forward_residual_bp`).
- Expectation is linear ⇒ **E[φ] = traded fly for any coupling of the marginals**, where
  `φ = Δ1 − Δ2` is the fly's settlement value. There is no naive "options-implied fair fly";
  all RV content lives in the shape of `φ`, in scenario decompositions, and in history.

## Metric stack

**Tier 1 — marginal-only (assumption-free).** Per contract: mean/median/mode/std/skew, tail
ladders `P(f_i ≤ K)`. Per fly: `fly_median_path = 2·med₂ − med₁ − med₃` (median-path fly),
`fly_mode_path` analog, **tail_rent = fly − fly_median_path** (portion of the fly paid for
asymmetric tails rather than the central path).

**Tier 2 — comonotone path model (core).** One policy factor: `f_i = F_i⁻¹(U)`, U on a
midpoint quantile grid (default n=20001). Produces: full distribution of `φ(U)` (quantiles,
`P(φ>0)`, PnL vs entry), discrete move counts `N_k = round(Δ_k/25bp)`, the table
`P(N1−N2=j)`, **prob_delta = P(N1>N2) − P(N1<N2)** vs the desk heuristic `fly/25`, payoff
conditioning `E[φ|N1−N2=j]` (tests the 25bp-per-move assumption), conditional flies by
common-factor decile, and tail slopes `dφ/df_back` in each wing (what the fly *is* in the tails).

**Tier 3 — alternative couplings.** (a) Gaussian copula on a historically calibrated
correlation matrix of daily contract-rate changes (ρ→1 must recover comonotone — tested);
(b) the existing option-implied FOMC-path joint (`SFRImpliedDistribution.extract_joint` +
`FOMCPathStateConfig`) with fly distribution via `linear_combination_distribution({front:−1,
belly:+2, back:−1})`. Divergence from comonotone ≈ reversal-risk premium. Copula runs in the
screener at the reference date; the joint stack runs in the notebook (expensive).

**Rich/cheap layer.** Daily history per fly triple of: fly, fly_median_path, tail_rent,
heuristic − prob_delta gap, φ IQR/p05/p95, tail slopes, per-leg quality diagnostics.
Z-scores (rolling window, default 120d min 40, plus full-sample) on the *gap* series. The
persistent mean gap is risk premium; the deviation from it is the signal.

## Architecture

`RVUtils/FlyVsVol/` — data-agnostic core; only the adapter knows about
`BreedenLitzenbergerResult` (duck-typed):

- `_types.py` — `ContractMarginal` (symbol, rate grid, CDF, forward, quality diags;
  `from_bl_result()`), `FlyDefinition(front, belly, back)`, `FlyVsVolConfig`
  (move_size_bp=25, n_quantiles=20001, tail thresholds, quality gates), `FlySnapshot`
  (all Tier-1/2 metrics + quality flags for one triple, one date).
- `coupling.py` — `comonotone_grid(marginals, n)`, `gaussian_copula_sample(marginals, corr,
  n_sim, rng)`, `historical_rank_corr(rates_panel)`.
- `metrics.py` — `path_metrics(rates_matrix, weights)` (coupling-agnostic core),
  `build_fly_snapshot(front, belly, back, ...)` (main entry).
- `screener.py` — `run_fly_screener(marginals_by_symbol, triples, ...)`,
  `screener_table(snapshots)`, `history_zscores(df, ...)`, `adjacent_triples(symbols)`.
- `plotting.py` — φ distribution + move-table + history panels (matplotlib, repo style).

Data plumbing lives outside the module:
- `notebooks/rv/run_fly_vs_vol_screener.py` — runnable EOD screener: resolves the live strip
  (`resolve_strip_symbols("2y", as_of)`), fetches daily smiles via
  `STIRFutureOptionMDP(source="BARCHART_STIRFO-QL").fetch_bulk_sabr_smile` (EOD caches make
  reruns local), extracts BL per (symbol, date), builds history + z-scores, writes
  `notebooks/data/fly_vs_vol/history.parquet` + prints the monitor.
- `notebooks/rv/fly_vs_vol_screener.ipynb` — narrative: snapshot monitor, U26-Z26-H27
  deep-dive, history z-scores, copula + joint comparisons, findings.

The futures leg of every fly comes from the option-side forwards (same futures feed), so the
screener has a single data dependency. The linear `IRSwapsMDP(BARCHART_STIRF-RL)` path
(`tenor="IMM_U26xIMM_Z26/IMM_Z26xIMM_H27/IMM_H27xIMM_M27"`, `FLY RATE`) is a cross-check in
the notebook, not a screener dependency.

## Quality gates

Per leg, from BL diagnostics: `|forward_residual_bp| ≤ 2.5`, `pre_normalization_mass ≤ 1.02`,
`ghost_mass_fraction ≤ 0.02`, warnings surfaced. A triple with a failing leg is reported with
`quality_ok=False`, never silently dropped.

## Testing

Fast, synthetic, no network (`-m "not slow and not network and not db"`):
- Normal marginals ⇒ comonotone `φ = fly + (2σ₂−σ₁−σ₃)z` closed form: E, median,
  `P(φ>0) = Φ(fly/|2σ₂−σ₁−σ₃|)`, quantiles; equal σ ⇒ φ degenerate at the fly.
- Copula ρ=1 ≈ comonotone (quantile agreement); ρ=0 widens φ.
- Move tables sum to 1; `mean(N1−N2)` consistent with the table; symmetric marginals ⇒
  tail_rent ≈ 0; `E[φ] = fly_mean` tie-out; tail-slope recovery
  (`dφ/df_back = (2σ₂−σ₁−σ₃)/σ₃` under Normals).
- Adapter from a stub BL result; screener table shape/ranking; z-score math on synthetic
  history; quality-gate behaviour.

## Caveats (documented in module docstring)

Risk-neutral ≠ real-world (persistent gaps are premium, not free money); comonotonicity
cannot represent path reversals (the comonotone-vs-joint spread measures that premium);
SR3 settlement-rate bins ≠ Fed target probabilities (quarter averaging; the joint stack
day-weights properly); each `Q_i` is the distribution *at that contract's option expiry*
(≈ reference-quarter start), so the coupled vector spans different observation dates —
comonotonicity is an assumption on that joint law; transaction costs (fly ~0.5bp, option
wings wider) swamp sub-1bp "edges".

## Worked-example validation (2026-07-27)

Fly +7.50bp; heuristic +30.0% vs model prob_delta +29.4%; composition 59% no-difference /
30.6% one-extra-hike; `E[φ|j=+1] = 12.6bp` (not 25); fly_median_path +11.3bp,
tail_rent −3.8bp ≈ cost of hedging the H27 blowout wing (0.62 × 5.0bp) — curve and options
internally consistent that day; U26 surface flagged (mass 1.013, fwd resid −1.2bp).
