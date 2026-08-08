# Citi Velocity RV loop — distilled reference (sources read 2026-08-08)

Extracted by reader agents from the shelf + Downloads packs; page-cited originals listed in
each section. This is the citable methodology corpus for the loop. **Predecessors:**
`2026-08-08-citivelo-rv-loop-design.md`.

## 1. Citi "Trading long-dated convexity" (Bikbov & Williams, 2019-05-09) — the SV framework

- BE definition (verbal in doc): *"The daily rates breakeven is a parallel shift in rates that
  yields a convexity gain offsetting the negative daily roll. When the roll is positive, the
  breakeven is zero."* Algebra: `BE = sqrt(2·|daily roll|/Γ)`. Cheapness = BE / 1y realized
  vol of the forwards; **< 1 = embedded convexity cheap** (note: one body sentence reads
  inverted — two-column PDF extraction artifact; Figure 3 title + Figure 7 confirm).
- Curve-as-vol regression: 10y10y/20y10y level on 2y10y implied normal LEVEL:
  `y = −0.5x + 19.0, R² = 0.5` (2010–2019).
- Backtest: $100k DV01 flatteners, annual roll, resize the LONGER leg at each 25bp move in the
  longer rate at close. Trigger 25bp = accuracy-vs-cost optimum; *Sharpe flat in 15–30bp,
  declines outside* (asserted, never published — our H-target).
- 8 pairs (10y5y/15y15y … 20y5y/25y10y): Sharpe 0.05–0.35 (best 10y10y/25y10y 0.35), daily
  P&L vol $195–252k per $100k DV01, skew ≈ 0, corr(monthly P&L, Δ1y10y vol) ≈ +26%. Flat
  since 2013. Benchmark short 1m10y straddles: Sharpe 0.84, skew −3.
- **Costs (Fig 9, one-way, bp of rate, $100k DV01)**: initiation 0.75 (short pairs) – 1.0
  (long pairs); delta-hedge and roll 0.3–0.4. Roll priced at the hedge width.
- Pair screen columns: curve bp, 1y/3y z, 1y carry bp, daily BE bp, 1y realized vol bp,
  BE/RV. 2019-05-08 pick: 15y5y/20y10y (BE/RV 0.42, "tighter market").
- Structural mechanism: VA/life receiving concentrated 15–25y keeps >20y curve steeper than
  convexity-fair; flatteners lack a terminal payoff (must unwind in a few years, realizing
  vega).

## 2. Citi 2020/2023 — entry timing and the two-sided switch

- **Free-convexity state (Mar-2020)**: 1y carry ≥ 0 AND positive convexity ⇒ daily BE = 0 —
  *"zero if carry is positive"*. Screen: 15 pairs × USD/EUR/GBP, z-scores 1y/3y/since-2000.
  2020-03-26: USD 15y5y/20y10y at −5.21bp, 1y z +4.21, carry +0.11bp — watch-list only
  (bid/offer gate; 10y swap mid-to-bid ~0.6bp then). VA receiving in equity selloffs is the
  flow that creates the state; Formosa/callable supply cheapens bottom-right vega.
- **Inversion (Jun-2023)**: deeply inverted forward curve flips the positive-carry side to the
  STEEPENER = positive-carry short-vol proxy. 2023-06-08: 10y10y/20y5y carry +10.31bp/y,
  daily BE 7.22bp, BE/RV 1.38 (preferred entry). Divergence overlay: 2y30y vol vs
  20y5y−10y10y spread (no fitted regression published).
- GBP precedent: 15y10y/25y10y flatteners Jan-2020, delta-hedged each 25bp, took profit on
  BoE-QE flattening Mar-2020.

## 3. Citi Rates Vol Lab catalog (2020–2024 weeklies)

- **Gamma-cycle regime**: sell 1m10y straddles daily, delta-hedged 3pm; avg annual P&L by
  ex-post Fed regime (daily-hedged): cuts −2243¢ / hold +716¢ / hikes +3243¢. Ex-ante:
  next-3m short-gamma P&L = 549.1·z(3m/1y3m OIS slope) + 30.2, R² 0.10.
- **Era cost table** (10y swap b/o bp | 1m10y vol mid-to-bid, normal bp): 2005–07 0.6|0.75;
  2010–12 0.7|0.75; 2013–16 0.4|0.625; **2017–20 0.3|0.5**.
- **Expiry-kink vol flies**: 3m2y/6m2y/1y2y fly vs (i) belly vol level 3y: slope −0.2173,
  R² 0.455; (ii) expiry slope 10y: 0.0568, R² 0.214. Trade 50/50 vega-flat.
- **Tail vol fly anchor**: 6m2y/6m10y/6m30y 50/50 vol fly tracks realized 1m beta of 6m-fwd
  2s10s30s on 6m10y (5y regression).
- **Rolldown fair value**: 3m2y vol on 3m2y fwd-spot rolldown, 1y window: R² 0.89 (2022).
- **Vol ratio band**: 6m2y/6m10y fade outside 110–130%.

## 4. Aug-2026 desk pack (current state)

- 2026-07-31 SOFR swaps: 2Y 4.15, 5Y 4.18, 10Y 4.33, **20Y 4.56, 30Y 4.52** (20s30s spot
  inverted). Fed 3.50–3.75%, held 9–3; modal 1 hike by YE26.
- JPM IV/21d-RV grid 7/23: ALL cells > 1; 1M–1Y expiries 1.25–1.40; **10Y-expiry row richest
  1.55–1.64** — long vega rich vs delivered.
- JPM book: long 10Yx10Y straddles delta-hedged daily since 2025-12 (+0.6abp); 3Mx30Y
  premium-neutral payer 1x2 (ATMF 4.526, +20 wing; bpvols 4.63 vs 4.80/day).
- TFP/ZDS swap-spread fair-value model: TFP on deposits/vol/WAM/net-debt R² 83%.
- Implied bp/day 7/31: 6Mx2Y 6.19, 6Mx10Y 5.20, 6Mx30Y 4.74, 3Yx10Y 5.45.

## 5. ING "Deconstructing the EUR yield curve" (2020-01-15) — F-ING spec

- Re-express curve as non-overlapping 1y forwards 1F1Y…30F1Y; rolling ~3y PCA on LEVELS
  (inferred); signal = PC1 residual bp vs own 3y percentile bands; typical reversion ~3m.
- Value-vs-carry frontier: residual on 3m roll-down across 2F1Y–15F1Y only: slope −1.27
  (R² 0.927); **direction-neutral version slope −2.70 (R² 0.862)** — value per carry ~2×
  better with zero-PC1 packages. Carry-breakeven filter: require dislocation/carry >> the
  3m reversion horizon (ING accepted 23bp vs 2bp/3m; rejected 14bp vs 15.5bp/3m).
- Forward-to-spot substitution: implement whichever of the forward fly / spot-space
  direction-neutral fly (1F1Y-6F1Y-9F1Y ↔ 2s7s10s) carries better.
- Long forwards (20F1Y+) excluded — hard to value/trade; carry-vs-vol line breaks down there.

## 6. Swaption cost line (see design doc §Cost line)

- BofA primer 2024: 3-leg 300m 1y10y package residual ≈ $44k ≈ **1.9 normal bp of package
  vega** "in the context of the bid/offer". Grid mostly dealer extrapolation outside liquid
  cells. Gamma sector = expiries ≤ 1y (convention).
- Citi era table (§3): 1m10y vol mid-to-bid 0.5 normal bp post-2017.
- Nordea 2021 (prior-killer, EUR 2005–21, GROSS): long 10Y10Y ATMF straddles delta-hedged
  monthly = POSITIVE (+14.5% of notional cumulative); convexity beats theta; vol-level entry
  timing worthless. Kills long-expiry vol selling; costs strengthen the kill.
- HPCA (BofA, arXiv:1910.02310): 5 static clusters; raw vol-PC residual RV is a RATES trade
  — regress vol PCs on forward PCs first (the F1 prior-killer).
- Skew ticket 2025-10-08: template spec — 4 legs ($100mm RR ± $9.71mm ATM straddle + swap),
  vega+delta neutral, 50bp RR percentile-vs-1y-history signal, rebalance at |ΔNetVega| > 5
  abpv or |Δrate| > 5bp, positive vomma asymmetry, entry marked at model mid.
