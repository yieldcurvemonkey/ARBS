148 tests pass, all artifacts written.

## FILES WRITTEN (absolute paths)

**Modules**
- `C:/Users/chris/clee/ARBS-cvx/RVUtils/ConvexityRV/strat2_fly_universe.py` — 45-fly catalogue, weighting modes, regression, gamma, MP panel builder
- `C:/Users/chris/clee/ARBS-cvx/RVUtils/ConvexityRV/strat2_grid.py` — `Strat2GridConfig`, panel simulation, scoring, `effectiveness_matrix`, `hypothesis_slope`

**Tests** — `C:/Users/chris/clee/ARBS-cvx/tests/test_convexity_rv_strat2_grid.py` (69 tests)

**Scripts** — `C:/Users/chris/clee/ARBS-cvx/scripts/strat2_build_fly_panel.py`, `C:/Users/chris/clee/ARBS-cvx/scripts/strat2_run_grid.py`

**Data** (all in `C:/Users/chris/clee/ARBS-cvx/notebooks/data/convexity_rv/`)
- `strat2_fly_panel.parquet` (85,545 rows = 1901 dates × 45 flies; fly_bp + 3M carry, 50/50 wings)
- `strat2_fly_legs.parquet` (76,040 = 1901 × 40 tenors; rate_pct + carry_roll_bp) — **the stored primitive**
- `strat2_grid_results.csv` (438 cells), `strat2_effectiveness.csv`, `strat2_fly_weights.csv`

## DELIBERATE DEVIATION FROM THE BRIEF — the fly P&L sign

The brief says the paid-belly leg earns `-(d fly_bp) * belly_DV01`. **It is `+`.** Three independent proofs:
1. Resolved package PV01 per leg is *exactly* `w_i * bpv` (measured 2023-06-09, 2s5s10s @0.73/1/0.47, bpv $21,400: `-15,622 / +21,400 / -10,058` vs expected, exact). Hence `ΣPV01·Δr = belly_DV01 · Δfly_bp`.
2. Shifted-handle repricing: +1bp parallel moves fly by `1−0.73−0.47 = −0.20bp`; package NPV moved **−$4,489** vs −$4,280 predicted (the 5% gap is zero-shift/par-shift mapping — linear in shift, not convexity).
3. Economics: β=+21.4 ⇒ CA and fly co-move; short-CA loses when the fly rises, a paid belly gains. The brief's sign would double the exposure.

Implemented `+`, with negative-control tests asserting the opposite sign fails.

## THE HYPOTHESIS — REJECTED, with numbers

Prediction: pack T1 at which a fly is most effective tracks its forward start 1:1.

| pooled over 45 (shape × start) cells | measured | predicted |
|---|---|---|
| slope, argmax-T1 on forward start | **+0.020 y/y** | +1.0 |
| corr | **+0.088** | ≈1 |

Mean peak R² **falls** monotonically with forward start: **0.151 (spot) / 0.117 (1Y) / 0.045 (2Y) / 0.018 (3Y) / 0.018 (5Y)**. For 2s5s10s specifically, corr(T1, argmax start) = **−0.274**; spot wins outright at only 1 of 9 ranks and the whole family sits at R² 0.000–0.092.

`R²` of constant-contract ΔCA on Δfly, 50/50 wings, full 1,178-day sample (`2s5s10s`):

| rank | T1 | spot | 1Y | 2Y | 3Y | 5Y |
|---|---|---|---|---|---|---|
| 2 | 0.37 | .0007 | .0202 | .0000 | .0002 | .0007 |
| 5 | 1.12 | .0062 | .0916 | .0041 | .0011 | .0050 |
| 8 | 1.87 | .0345 | .0005 | .0154 | .0012 | .0042 |
| 10 | 2.37 | .0444 | .0918 | .0858 | .0076 | .0083 |

## THE ONE REAL RELATIONSHIP — and what it actually is

**1s2s3s SPOT vs the rank-5 pack (T1=1.12y): R² 0.792, corr −0.890, slope −1.547 bp CA per bp fly** (n=1,177, verified in raw numpy independent of module code). Peak by rank: .081/.167/.365/**.792**/.637/.426/.196/.0003/.0001 — it peaks exactly where the matched swap window sits inside the fly's legs and dies when it leaves.

**Not a stale-settle artifact.** Staleness would give ΔCA ≈ −Δswap (slope −1.0). Measured slope of ΔCA on Δ(matched swap) at rank 5 is **−0.191, R² 0.191**; days with pack_rate literally unchanged are only **3.4–7.6%**.

**But the mechanism is the swap leg, not vol.** Exact decomposition at rank 5:
- Δpack_rate ~ Δfly: slope **+1.088**, R² 0.092
- Δmatched-swap ~ Δfly: slope **+2.635**, R² 0.438
- ΔCA ~ Δfly: **−1.547 = 1.088 − 2.635**, R² 0.792

The 1y forward swap at 1.1y is ~2.6× as sensitive to 1–3y curvature as the futures strip is. The hedge is real and tradeable, but it hedges curve shape at the pack's own maturity — **the opposite of Citi's "3y1y vol is directional with 5s" rationale**. I cannot separate "the futures genuinely carry a curvature basis" from "the `USD-SOFR-1D` build amplifies curvature into the 1–2y forward"; both are risks to the trade.

Direction: to hedge short-CA at rank 5 you **RECEIVE** the belly of spot 1s2s3s at ~**1.5× CA DV01** — opposite direction and ~7× the size of Citi's paid 2s5s10s at 0.21×. (`fly_carry_3m_bp` is quoted paid-belly; flip its sign for this position.)

## CITI'S ESTIMATOR FAILS ON THIS SAMPLE

- Variance reduction positive in only **14.4%** of 180 fly×rank cells; median **−0.206** (changes basis) / **−0.399** (levels).
- Level-regression β sign-flips: `frac(β>0)` by rank 3..9 at 63d = **0.50, 0.48, 0.56, 0.52, 0.54, 0.43, 0.43** — a coin flip, while level R² looks respectable (median 0.12–0.60). Classic spurious regression; β IQR 13–65.
- Best single cell overall: **1s2s3s spot, rank 5, changes basis — VR 0.600, Sharpe 1.30, +$12.4m on $100k DV01, hit rate 0.40**.
- `regression_target="label"` starves deep ranks (a label enters a 13-contract strip at window 10 with ~0 history) — pinned as a test; hence `"rank"` (Citi's rolling colour) is the default.

## TIE-OUTS — all asserted, with deltas

| tie-out | result |
|---|---|
| FLY engine rate == `100·(−w_f r_f + r_b − w_k r_k)` | **≤1e-13 bp** on 5 flies incl. forward-starting (required <1e-6) |
| Per-leg PV01 == `w_i · bpv` | exact |
| `belly_DV01 = CA_DV01·β/100` vs published notionals | **1.004** ($100k, β21.4) / **1.003** ($200k, β20.6) |
| Citi's fly SHAPE on my own sample (levels, 362 rolling fits, ranks 3–9) | **w_front 0.511, w_back 0.535** vs Citi 0.73/0.47 — same sign, within 1.5× |
| `annuity_duration` vs `rl.IRS.analytic_delta` | ≤**2.1%** (naive `s+n/2+.125` is 19.1% out at 30Y) |
| Sign probes (payer, paid belly, short-CA gamma ≤ 0) | pass, each with a failing negative control |

**Mutation checks actually run** (not just written): flipped the paid-belly sign in `strat2_grid.py` → **3 tests failed**; reverted; flipped the short-CA gamma sign → **2 tests failed**; reverted. Both restored, 148 tests pass.

## GAMMA — the omitted second order is the size of the whole carry

Unhedged short CA, $100k DV01, 63-day epochs:

| rank | gamma/epoch | 3m roll income/epoch |
|---|---|---|
| 3 | −$46,699 | +$39,923 (0.40bp) |
| 5 | −$63,485 | −$37,299 (−0.37bp) |
| 7 | −$87,497 | +$108,252 (1.08bp) |
| 9 | −$92,106 | +$3,953 (0.04bp) |

`gamma_share` of headline P&L runs −0.15 to −0.39 on hedged cells. **The short-CA carry does not obviously clear its own gamma bleed in a sample containing 2022.**

## CARRY vs CITI'S CLAIM

2s5s10s spot paid-belly 3M carry+roll: **mean +0.43bp, median +1.08bp, sd 3.55** vs Citi's "+4bp over 3m". Positive but a quarter of their level and very noisy. Forward variants are tighter and smaller (2s5s10s@1Y: +0.75/+0.83, sd 0.70). Highest-carry shapes: 2s7s30s spot (+1.51/+2.23) and 2s10s30s spot (+1.69/+2.40).

## SCOPE LIMITS (stated, not hidden)

- Usable window **2019-01-02 .. 2023-09**: 1,175 of 1,179 CA dates are ≤2023-10-01; SR3 coverage collapses after (2024:1, 2025:2, 2026:1 dates). The leg panel itself is complete to 2026-08-12 (1,901 dates, **zero missing tenors** — all 40 priced).
- Packs 1–10 only ⇒ **T1 ≤ ~2.4y**. Citi traded Blues (T1≈3.25y) and Golds (≈4.25y); **the hypothesis is NOT tested at that depth** — deep packs are not in daily offline reach.
- The 5Y forward start is an over-shoot control: no reachable pack matches it.
- P&L is a first-order panel simulation (DV01s frozen at entry); financing/margin, CME–LCH basis and intra-epoch re-striking are not modelled.

**No notebook was built** — the deliverables listed modules + tests only; the two `scripts/` drivers reproduce every number above.