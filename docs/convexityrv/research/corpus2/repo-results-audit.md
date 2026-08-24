# Repo results audit — which convexity numbers survive the 2026-08-20 CA fix

Audit of all 21 files in `docs/convexityrv/results/` plus `ca_coverage_diagnosis.md` and
`midcurve_feasibility.md`, read in worktree `ARBS-cvx3` on 2026-08-24. Purpose: for the
fresh backtest, classify every published number as (a) downstream of the pre-fix shared CA
path (suspect), (b) computed on the `RVUtils/ConvexityRV` Q/Q path (convention-correct but
possibly coverage-superseded), or (c) computed from traded instruments / vendor data
(untouched by the fix) — and pin every known-answer tie-out with its source.

## 0. The fix, precisely — and the fact that decides most classifications

Commit `50e5fb29` (2026-08-20, worktree `ARBS-cvx2`, branch `feat/convexity-rv2`;
recorded in `preflight-2026-08-20.md` §2 and `results/w1-ca-coverage-repair.md` §1) fixed
three defects **in the shared repo path** — `Query/IRSwaps/IRSwapValue.py::CVX_ADJ`
reached by `TB/IRSwapsTB.sfr_cvx_adj` — **not** in `RVUtils/ConvexityRV`:

| # | defect | where | measured error | affected window |
|---|---|---|---|---|
| 1 | matched swap built annual/annual (`usd_irs` spec default), Citi specifies Q/Q | shared path | CA too low by **−4.585 / −5.816 / −5.884 bp** on 3 probe dates; WHITES 2026-08-19 −5.81 shipped vs +0.19 Q/Q | every `CVX_ADJ` ever published by the TB path |
| 2 | `_as_percent` (`x*100 if abs(x)<1`) applied to `rl.STIRFuture.fixed_rate`, already percent | shared path | up to **+9,405 bp**; trips on any SR3 price > 99.00 | ZIRP, 2020-03..2022-06 (Whites/Reds/Greens) + deferred strip into 2021 |
| 3 | `get_barchart_timeseries` unconditional `.bfill().ffill()` | shared path price panel | look-ahead inside the price series | one caller in the repo; preflight records blast radius zero |

Two consequences for reading the corpus:

1. **`RVUtils/ConvexityRV` was always a second, independent implementation** that computes
   `CA = pack_rate − matched_forward_swap_rate` at Q/Q via `curve_ops` and ties out to
   Citi Fig 58. Its numbers are not touched by defects 2–3 at all. **But the annual-swap
   disease had a second, separate outbreak inside strat2**: the original
   `strat2_panel.parquet` (built by the `strat2-sofr-convexity-vs-fly` work) was the
   **annual-frequency variant** — proven by `strat2-ca-correctness.md` (reproduces the
   scan's `ca_annual_bp` to 1.9e-12 on all 11,750 overlapping rows; differs from Q/Q by up
   to **12.0 bp**, bias `−0.375·r²`, −5.46 bp in 2023). Everything computed on that
   artifact before the rebuild is suspect regardless of the 08-20 commit.
2. **The fix orphans, it does not rewrite**: the convention travels in `value_kwargs` →
   `_query_fingerprint` → cache symbol, so old-convention `sfr_cvx_adj` rows are orphaned,
   and W1's panel rebuild proved no ConvexityRV-path CA moved (p95 |Δca_bp| ≤ 0.0553 bp on
   32,540 common rows; `ca_coverage_diagnosis.md` §12.2 later required 23 columns exactly
   equal on every common row — **0 columns moved**).

### The "P&L via QueryDrivenBacktest is unaffected" claim — what the corpus actually says

**No results doc states that sentence.** What is stated, and what it does and does not
license:

* Every engine backtest marks **traded instruments** (SR3 futures legs at settle prices, a
  swap struck at its own fair rate, fly legs), not the CA formula. A par-struck swap has
  zero entry NPV under either frequency convention, so the convention shifts the *strike
  rate* of the instrument traded, not the entry value; daily marks are genuine trade P&L
  for the book actually held.
* `strat2-grid-notebook.md` §9 is the strongest direct evidence: top cells re-run through
  `QueryDrivenBacktest` reproduce the panel's **CA leg** at corr 0.997–0.999, slope
  1.007–1.036 — but this was measured on the **rebuilt Q/Q** panel with Q/Q swaps.
  The full-package engine keeps only 32–49% of panel dollars (aged-swap fly-leg drift), so
  even post-fix, panel-level hedged dollars are not engine-certified.
* The claim does **not** rehabilitate pre-fix backtests: the convention (and the coverage
  trim) chose which instrument was struck, when, and against which signal.
  `w2b-ca-vs-swap-fly.md` §4 is the empirical verdict: the same book quoted at annualised
  Sharpe **0.470** on the accidental pre-repair sample is **0.130** on the complete
  2021–2026 panel — "a strategy whose Sharpe falls by two thirds when you give it the
  data it was missing was never measuring what it appeared to measure."

## 1. Classification summary

| results doc | CA path used | suspect numbers | traded-instrument / vendor numbers | status |
|---|---|---|---|---|
| ca-approach-taxonomy-and-tieouts | ConvexityRV Q/Q (post-fix) | none | n/a | CURRENT — the canonical CA statement |
| jpm-package-parser | none | none | all (JPM PDFs) | CURRENT |
| jpm-package-tieout | none | none | all (JPM vs our panels) | CURRENT |
| strat1-jpm-curve-as-gamma | none | none | QDB cohort P&L on swaps | CURRENT (own caveats) |
| strat1-listed-longend-cm | none | none | all | CURRENT |
| strat1-listed | none | none | all | CURRENT (backtest = illustration) |
| strat1-midcurve-feasibility | none | none | all | CURRENT |
| strat1-real-contract-panel | none | none | all | CURRENT |
| strat1-rebuild-real-contracts | none | none | all | CURRENT (fails own null) |
| strat1-threeway-longend | none | none | QDB-derived cohorts | CURRENT (DEAD vs null) |
| strat1-threeway | none | none | QDB-derived cohorts | CURRENT (DEAD, illustration) |
| strat2-ca-correctness | ConvexityRV, both conventions deliberately | none (it *defines* the suspicion) | n/a | CURRENT — diagnosis doc |
| strat2-fly-grid-engine | **annual `strat2_panel.parquet`** | ALL CA-dependent results (R² tables, rank-5 spike, VR, gamma/carry vs CA) | fly-leg panel, engine-identity tie-outs | **SUPERSEDED** by strat2-grid-notebook |
| strat2-grid-notebook | rebuilt Q/Q panel | none on convention; hedged dollar levels un-certified (§9) | engine certification of CA leg | CURRENT convention; coverage pre-W1; verdict: not alive (DSR 0.924) |
| strat2-q20-deep-packs | ConvexityRV Q/Q (Q20 curve + settles) | none on convention; **backtest windows are trim artifacts** (743/301 days) | QDB deep/near backtests | CA values CURRENT (bit-identical after repair); P&L windows SUPERSEDED by coverage repair + w2b |
| strat2-sofr-convexity-vs-fly | **annual matched swap** (built `strat2_panel.parquet`) | CA panel, screen, `vs_model`, the −3.89/−4.31 bp offset **misattributed to CME–LCH clearing basis** (it was the frequency), Sharpe 0.191/0.070 | QDB leg marks are real trades; kernel tie-outs (b)(c)(d) convention-free | **SUSPECT / SUPERSEDED** (by strat2-ca-correctness, grid-notebook, W1, w2b) |
| strat3-strikeless-vol-flatteners | none | none | QDB + ledger engine (corr 0.9997) | CURRENT (winner fails DSR) |
| w1-ca-coverage-repair | ConvexityRV Q/Q, post-fix | none | n/a | CURRENT — the fix record |
| w2b-ca-vs-swap-fly | repaired Q/Q panel, post-fix | none | QDB arms | CURRENT — DEAD |
| w3-ca-vs-longend-vol-rv | repaired panel (Ho-Lee inversion), post-fix | none | no engine spent (premise dead) | CURRENT — DEAD at diagnostic |
| w4-ultra-long-risk-adjusted-carry | none (long-end swaps only) | none | QDB episodes | CURRENT — DEAD |

Extra docs: `ca_coverage_diagnosis.md` — CURRENT (coverage diagnosis + repair, Q/Q path
throughout, `annual_qq_gap_bp` recorded per row); `midcurve_feasibility.md` — CURRENT (no
CA dependence).

**The only two results docs with numbers that are outright suspect on the matched-swap
convention are `strat2-sofr-convexity-vs-fly.md` and `strat2-fly-grid-engine.md`** — both
built on the annual-frequency `strat2_panel.parquet`, both explicitly superseded inside
the corpus itself. The `_as_percent` ZIRP defect (defect 2) contaminates **no** results
doc: strat2 explicitly did not reuse `IRSwapValue.CVX_ADJ` ("deliberately not reused: it
asserts a single-element package … and rounds the pack price to ¼ tick"), and no results
doc consumed the pre-fix `TB.IRSwapsTB.sfr_cvx_adj` timeseries. The bfill defect (3) had
one caller, blast radius zero. The pre-fix shared path's only known consumers are outside
`results/` (e.g. any historical use of `sfr_cvx_adj` — its cache rows are orphaned by
fingerprint).

## 2. Per-document audit

### 2.1 ca-approach-taxonomy-and-tieouts.md — CURRENT
**Measured**: which of the four CA approaches the repo implements (approach 4: implied
from futures strip vs IRS curve, Q/Q both legs, convention in `value_kwargs`); two
corrections (A: shipped `ca_bp` ≡ `ca_bp_q20` to 0.000e+00 on 29,643 rows, NOT the settle
column, which differs by up to 1.139 bp; B: negative Whites CA is quote noise, not curve
degeneracy — observed 42.35% negative vs 45.05% predicted by |median|/sd = 0.124), plus a
rateslib hazard (over-parameterised spread curve: LM vs GN 2,233 bp apart, both `SUCCESS`,
f_val ~1e-17 — pin free-DF count vs quote count).
**Harness**: `IRSwapValue._convexity_adjustment`, `TB/IRSwapsTB.sfr_cvx_adj[_intraday]`,
`RVUtils/ConvexityRV/strat2_q20.py`, `ca_swap_leg_gate.py`, `holee.py` (inversion only).
**Suspect**: none — written post-fix, all identities on the Q/Q panel.
**Tie-outs**: identity `(pack−swap)×100 − ca_bp = 0.000e+00` on 29,643 gated rows;
`ca_bp` vs `ca_bp_q20` corr 1.000000/0 diff; vs `ca_bp_settle` 0.999774/max 1.139 bp;
**Citi Fig 58 (Rates Vol Lab, 12-Jun-2023, close 6/9/2023, 13 rows)**: median |err|
0.99 bp, worst 3.06, mean −0.04, slope 0.850, intercept +1.76 bp; Ho-Lee shape CA/T1²
≈1.0 (Reds/Greens) → 0.79 (Golds).

### 2.2 jpm-package-parser.md — CURRENT, no CA
**Measured**: parse of 1,716 JPM U.S. Futures & Options Package PDFs (as_of 2019-08-26..
2026-08-12) into 7 parquets + coverage JSON; date convention (join on `as_of`, filename
disagrees on 273/1,306 legacy files); units (JPM `bp_*` is DAILY bp vol — `ABPV/(bp·√252)`
SFR median 0.9977; `pct_*` MM = lognormal yield vol, Treasuries = lognormal price vol ≡
our ATM at median 0.9996; v2025 MM futures prices print in 32nds); expiry-rule grading
(corrected `ust_expiry` 99.986% vs repo rule 96.350%, 780-row disagreement set decided
99.62% for the corrected rule); ED midcurve implied vol dies 2019-12..2022-12 by tenor,
5Yr never populated; no SOFR midcurve page ever appears.
**Harness**: `RVUtils/ConvexityRV/jpm_package.py`, `scripts/parse_jpm_packages.py`,
35 tests mutation-checked (10 caught, 2 proven equivalent).
**Suspect**: none. **Tie-outs**: 3 PDF-vs-parquet spot checks (2023-06-09 p26, 2019-08-27
p31, 2026-08-13 p31, all exact); `Chg(1d) == Cur(t)−Cur(t−1)` 98.0–99.6%; midcurve bp
reproduction `(100−F)·pct/100/√252` median ratio 1.0020.

### 2.3 jpm-package-tieout.md — CURRENT, no CA
**Measured**: six tests of our vol panels against the JPM package. 1: date convention
CONFIRMED (`as_of + DtE == our expiry` 100.000% of 12,880). 2: ATM units CONFIRMED
(ours×100/JPM median 0.99967 US / 0.99971 TY). 3: ABPV duration bridge CONFIRMED (implied
ModDur 0.9957×/0.9824× store CTD) with a JPM-internal disagreement (their own bp column
implies 1.0696× CTD ModDur for US). 4: OTC-listed basis CONFIRMED in sign (listed 4.9–7.8%
above matched OTC on JPM's own pages; our OTC leg is the wider one — re-examine the
swaption cube). 5: expiry rule 263/263 corrected vs 253/263 repo. 6: midcurves REFUTED as
a replacement (ED-only, last populated 2022-12-15; overlap with our SOFR probe = 0 dates).
Defects flagged: `ust_listed_vol` TY 90-day CM node (change corr 0.107 — quarantine); a
165-row >1-vol-pt tail in `listed_contract_vol`; archive re-publishes stale pages (dedupe
on `(as_of, product, expiry_ym)`).
**Harness**: `jpm_tieout.py`, `parse_jpm_swaptions.py`, notebook `jpm_package_tieout.ipynb`
(31 cells, 0 errors), 39+35 tests, 17 mutations (13 killed, 4 proven equivalent).
**Suspect**: none.

### 2.4 strat1-jpm-curve-as-gamma.md — CURRENT, no CA; engine P&L
**Measured**: JPM "curve-as-gamma" — long-end forward flatteners vs 1Yx30Y swaption
breakeven, 2019-01-02..2026-08-14, monthly cohorts, 1-y hold, QDB engine. Headline:
20Yx5Y/25Yx5Y Sharpe/trade 0.933 (t 8.13), annualised 2.95 **overlapping-sample**;
signal degeneracy is the real finding — breakeven never fires rich on the three long-end
structures (book = permanent flattener); 5Y/30Y is the only two-sided control.
**Harness**: `strat1_curve_gamma.py`, `strat1_curve_gamma_backtest.ipynb`, 33 tests.
**Suspect**: none re the CA fix. P&L is QDB cohort MTM on traded swaps. Internal caveats:
`rateslib.Curve.translate` ageing defective (refused; carry from
`CARRY_AND_ROLL_BPS_RUNNING`), overlapping cohorts, monthly not daily.
**Tie-outs**: payoff regression table 2022-09-13, 3 structures × 13 shifts, max 0.049 bp;
convexity 1.000 on 7,632 rows; sign probe payer **+$2,303,346** over 2022-09 selloff,
mirror to 1e-6 (this value is the corpus-wide engine-liveness pin); carry pins to 3.8e-5 bp.

### 2.5 strat1-listed-longend-cm.md — CURRENT, no CA
**Measured**: long-end curve-as-gamma against constant-maturity **UST listed** vol
(62,333 rows, 2019-2026). Units PASS two ways (vs swaption cube ratios 1.009–1.127; vs CTD
DV01 via basis reports — CTD reprice to median 0.00155 price pts). Sector matching from
measured CTD (US prices a ~16y point → UL primary for 30Y/50Y). Verdict: flatteners cheap
gamma on 100% of days vs every listed benchmark; listed prices 0.20–0.86 bp/day MORE than
swaptions (basis negative on all 12 benchmarks) — the hypothesis was backwards; cheap-share
saturated, so 5Y/30Y carries the information.
**Harness**: `listed_vol.py` (extended), `strat1_listed.py` longend fields,
`strat1_listed_longend.ipynb`, 56 tests, 9/9 mutations caught.
**Suspect**: none. **Tie-outs**: sign probe vs measured 2022-09-12..15 move (−$128,366 vs
−$126,100 expected); 32 payoff profiles rebuilt live, max diff 0.0.

### 2.6 strat1-listed.md — CURRENT, no CA
**Measured**: SFR-sector curve-as-gamma vs listed SFR options (sfr_rv_lab quotes,
199,313 rows, 540 dates 2024-07..2026-07). `iv_bp` proven an annualised Bachelier bp/yr
RATE vol, `premium_bp` discounted (median |err| 0.0133 bp repriced); realised/implied
1.011. Curve cheaper gamma on 18.7–44.4% of days by structure; OTC−listed basis
+0.251 bp/day (+4.0%), flips verdicts on only 1.6% of rows (gap dwarfs basis, factor 10).
Backtest labelled **illustration only** (54 weekly cohorts sharing ~98% of window).
**Harness**: `listed_vol.py`, `strat1_listed.py`, `strat1_listed_backtest.ipynb`, 36
tests, 7/7 mutations. **Suspect**: none. **Tie-outs**: 2022-09-13 regression exact
(diff 0.0 on 13 points); Bachelier reprice; strike-convention identity exact.

### 2.7 strat1-midcurve-feasibility.md — CURRENT, no CA
**Measured**: SOFR midcurve vol obtainable via Barchart per-strike EOD (~1 call/leg buys
whole history); "682 keys all empty" premise false (poisoned `no_data` cache markers,
`STIRFutureOptionMDP.py:5335`); forward-vol term structure at one expiry (2026-12-11):
spot 75.04, +1y 91.60, +2y 88.24, +3y 85.49 bp/yr — humped, forward > spot everywhere.
**Harness**: `scripts/harvest_sofr_midcurve_vol.py` with `NetGuard`.
**Suspect**: none. **Tie-outs**: engine vs QuikStrike ABPV — SFRM26 45.01 vs 44.74
(+0.6%), SFRZ26 69.08 vs 68.45 (+0.9%); mutation-tested (τ, price scalings all >±7%).
**Hazards pinned**: `cache_only()` does not patch httpx (later fixed per
`ca_coverage_diagnosis.md` §11.7); stale 1/16 strike rule for 0Q/2Q.

### 2.8 strat1-real-contract-panel.md — CURRENT, no CA
**Measured**: real listed-contract vol panel — 196,560 rows, 228 contracts, 2019-2026.
`ABPV` = annualised Bachelier bp/yr yield vol (3 ways, incl. cross-vendor QuikStrike vs
sfr_rv_lab ratio median **0.9998**, |Δtte| = 0.00 days); `ATM` differs by asset class
(SFR: ABPV/ATM = 100.0000 exact on 80.7%; US 860.6 → ModDur 11.62y; TY 1703.9 → 5.87y);
`25D_BF` unusable as independent quantity; ageing table real/CM 1.002→1.066 with TTE.
Data findings: `definitions/USTFutureOptions.option_expiry_date` defective (Memorial-Day
and Christmas-Day cases — independently confirmed by the JPM tie-out); QuikStrike SR3
history starts 2022-01-21; UST listing horizon 4–8 months.
**Harness**: `harvest_listed_contract_vol.py`, `listed_contracts.py`, 21 tests, 10/11
mutations (11th proven no-op). **Suspect**: none.

### 2.9 strat1-rebuild-real-contracts.md — CURRENT, no CA
**Measured**: strat1-listed + threeway rebuilt on real contracts (8 real benchmarks).
CM was adequate for the verdict, biased for the level (+0.116 bp/day), incapable of expiry
matching/roll/smile sections; long-end OTC-listed basis on real contract 0.818 median
(ratio-to-flip 2.34 vs short end's 10.02 — 4.3× compression, still not enough: veto moved
−0.043 bp/cohort). Honesty: n_eff 9.70 pooled; best gate Sharpe 0.2495 < E[max|null]
0.333 — **does not clear its own null**; UL/TN not listed as real contracts (bias measured
−0.345 bp/day toward the existing conclusion); three of four structures saturated.
**Harness**: `strat1_real_contracts.py` (1,556 lines), 2 executed notebooks, 28 tests,
12/12 mutations. **Suspect**: none. **Tie-out**: caught cross-join bug (17% → 0.59%
disagreement), pinned by test.

### 2.10 strat1-threeway-longend.md — CURRENT, no CA — DEAD vs null
**Measured**: curve vs swaption vs listed on the long end, 1,854 dates. Basis negative at
all 12 benchmarks; persistence AR(1) 0.893–0.984; factor-of-10 (short end) becomes 3.45;
disagreement 1.59%→3.34%; gates on identical cohorts: best `swaption_only` Sharpe/cohort
0.2423 vs E[max|null at n_eff=10] 0.3327 — **FAILS**, deflated Sharpe 0.3946. Listed veto
worth −0.046 bp/cohort vs σ 29.3.
**Harness**: `strat1_threeway.py` extended, `strat1_threeway_longend.ipynb`, 36 tests,
11/11 mutations. **Suspect**: none. **Tie-outs**: replay known-answer ≤7.11e-15 bp; fresh
1,624 s engine pass on 5Y/30Y max_abs_err 0.0 over 76 cohorts; 3 skipped cohorts each
explained (missing swaption quote on lagged date).

### 2.11 strat1-threeway.md — CURRENT, no CA — DEAD, illustration
**Measured**: three-way in the SFR short end, 517 dates. Cheapest source: listed 48.7% /
curve 31.1% / swaption 20.1%; basis +0.251 bp/day, factor-of-10 to flip; every gate lost
money; best Sharpe/trade −0.271 vs E[max|null] +0.744 at n_eff 2.05. `both` ≡ `cheapest`
proven (0 differing rows of 2,700 + randomised sweep) → 4 trials not 5.
**Harness**: `strat1_threeway.py`, executed notebook, 42 tests, 9/10 mutations (10th
proven inert and pinned). **Suspect**: none. **Tie-outs**: linearity identity vs fresh
engine pass max |err| 0.0 bp over 54 cohorts; `apply_gate` replay to 7.1e-15 bp.

### 2.12 strat2-ca-correctness.md — CURRENT; the doc that created the strat2 suspicion
**Measured**: CA quality scan, 11,900 pack-days 2019-2023 (ranks 1–10). **Action item 1:
`strat2_panel.parquet` is the ANNUAL-frequency variant** (matches scan's `ca_annual_bp`
to 1.9e-12; up to 12.0 bp off Q/Q; 2023-06-09 front pack +0.13 → −9.34 bp; 5 of 10 packs
pushed into no-arb violation by the frequency alone; the live `ca_snapshot` code was
already correct — a stale artifact). **Action item 2: discard pre-2019-07-08** (node
starvation: 520 rows where `CA_synthetic` is machine-zero while `CA_observed` spans −91.6
..+27.6 bp — the zero-convexity control is structurally blind there). Also: annual-vs-Q/Q
gap `b·r²` with b = 0.36886 vs predicted 0.375; CA<0 is 99.6% data-not-convention;
2019 Q12 curve degenerate (12 nodes, second at +2y) — "the curve is wrong, not the
settles"; timing noise 0.89–2.55 bp/pack-day; vol-error budget makes rank 8 the first
15%-budget rank.
**Harness**: `ca_diagnostics.py`, `scripts/strat2_ca_quality_scan.py`,
`strat2_ca_diagnostics.ipynb`, 30 tests, 7/7 mutations.
**Suspect**: none of its own numbers (it computes both conventions deliberately; Q/Q
column is the corrected one). **Tie-outs**: **Citi Fig 58 Q/Q: mean −0.108 bp, corr
0.9667, |max| 3.123, 0/13 negative; the ANNUAL negative control reproduces the documented
−3.89/−4.31 bp offset — proving the earlier "CME clearing basis" attribution wrong**;
zero-convexity control |p95| 0.573 bp with residual = the annuity-weighting term (slope
1.149, no free parameter).

### 2.13 strat2-fly-grid-engine.md — SUPERSEDED (annual panel)
**Measured**: 45-fly universe × pack-rank effectiveness grid on `strat2_panel.parquet` —
**the annual-frequency artifact**, so every CA-dependent number is pre-fix-convention and
was re-measured by strat2-grid-notebook. Notable deltas after the Q/Q rebuild: the
"1s2s3s spot rank-5 spike" (R² 0.792, slope −1.547) becomes a **broad** R² 0.42–0.55
plateau over ranks 2–8; hypothesis rejection (forward-start tracking) survives in both.
**Still valid (not CA-dependent)**: the fly leg panel (`strat2_fly_legs.parquet`, 1,901
dates, zero missing tenors), the paid-belly **sign correction** to the brief (three
independent proofs; per-leg PV01 = `w_i·bpv` exact), fly-engine rate identity ≤1e-13 bp,
`belly_DV01 = CA_DV01·β/100` vs Citi's published notionals at 1.004/1.003,
`annuity_duration` vs `rl.IRS.analytic_delta` ≤2.1%.
**Harness**: `strat2_fly_universe.py`, `strat2_grid.py`, 69 tests, 2 live mutation checks.
No notebook, no QDB run (panel simulation, DV01s frozen at entry).
**Suspect**: all R²/VR/β/gamma/carry-vs-CA cells; superseded within the corpus itself.

### 2.14 strat2-grid-notebook.md — CURRENT convention (Q/Q rebuild); verdict not alive
**Measured**: 1,890-cell grid on the **rebuilt Q/Q panel**, hard-cut 2019-07-08,
10,620 pack-days. §4.1: annual-vs-Q/Q gap = `0.375·r²` exactly (slope 1.00000, residual sd
0.0000 on 11,900 rows). §5: forward-starting flies do NOT help (slope −0.018 vs predicted
+1.0); mechanism flips with rank — beyond rank 5 the swap leg is the larger beta, so the
"hedge" is a curve-shape bet, not Citi's vol story. §6–8: 7 survivors of 1,569 scored
cells, all `1s2s3s/changes/regression/short_ca` at ranks 5 & 8; winner Sharpe 1.329 but
**deflated Sharpe p(true SR>0) = 0.924 < 0.95 — does not clear**; E[max|null] 0.692.
§9 **engine certification**: CA leg panel≡engine corr 0.997–0.999, slope 1.007–1.036;
full package keeps 32–49% of panel dollars (aged-swap vs constant-maturity fly pricing —
measured −1.44/−2.97 bp drift cases). Citi's own 2s5s10s cell: hedge R² 0.000–0.010,
β sign flips, carry −0.67 bp vs their +4 bp claim.
**Harness**: `strat2_convexity_vs_fly_gridsearch.ipynb` (30 cells, 0 errors), 270
convexity tests. **Suspect**: none on convention; hedged-cell dollar levels explicitly
not trustworthy (§9); coverage is pre-W1 (window ends 2023-12, ranks ≤10).
**Tie-outs**: `decompose_ca` recompute max |diff| 0.0; fly mirror/long-short exact zeros;
INP_STRICT hole-punching shown to zero out z-scores (filter applied as entry gate).

### 2.15 strat2-q20-deep-packs.md — CA values CURRENT; backtest windows superseded
**Measured**: Q20-curve CA for deep packs (Blues/Golds). Found the brief's premise false
(no Q20 store; `get_pricer` makes 52–57 network calls/date with `offline=True` ignored);
built `build_q20_pricer` from 17:00 EOD settles (0 requests, ~0.15 s/date). 2019 rejection
decomposed: front ranks disagree 10–17 bp (meeting-map starts 2021-04), deep ranks agree
to 0.27 bp. Gate (resolution + settle-agreement ≤2.0 bp + coverage): gated deep ranks,
median |CA_q20 − CA_settle| = 0.0366 bp, corr 0.99990 — "gated, the Q20 forward IS the
settlement mark". Deep backtest (ranks 9–13, 743 days): unhedged −$421k, hedged +$1.04m
(settle variant +$2.30m hedged); **selection fragility dominant** (sources agree to
0.03 bp yet pick the same pack on only 89.9% of screen days → ~2× P&L spread).
**Harness**: `strat2_q20.py`, `scripts/strat2_q20_build.py`, `strat2_q20_deep_packs.ipynb`
(0 errors, 0 network), 30 tests, 8/8 mutations.
**Suspect**: none on convention (Q/Q throughout via `matched_forward_swap_rate`; annual
gap regression b = 0.37195 vs 0.375 confirms). **But the equity windows (743-day deep,
301-day near) are `trim_to_contiguous_run` artifacts** (`ca_coverage_diagnosis.md` §3.5),
and the published near-pack reference (+$5.05m, Sharpe 0.470, 2020-08..2024-05) is the
number w2b later showed collapses to 0.130 on repaired coverage. CA values themselves were
proven bit-identical across the repair (§12.2).
**Tie-outs**: Citi Fig 58 all 13 rows on Q20 (mean −0.008 bp, corr 0.9659; **Blues M6-H7
15.72 vs Citi 15.40; Golds M7-H8 21.73 vs 22.29**); implied-vol inversion of Citi's own CA
vs their IV column median 0.9973.

### 2.16 strat2-sofr-convexity-vs-fly.md — SUSPECT / SUPERSEDED (the annual-panel origin)
**Measured**: the original Strategy-2 build — `strat2_sofr_convexity.py`, the Citi
13-column screen, hedge regression, and a QDB backtest 2020-02-03..2023-09-20 (904 marks,
35 epochs): unhedged +$3.21m Sharpe 0.191, hedged +$1.26m Sharpe 0.070; fly hedge made it
worse; 8/35 epochs inexpressible as a fly; COVID pair (−$3.10m/+$2.85m) dominates.
**Suspect numbers**: everything derived from `strat2_panel.parquet` — the panel it built
is the **annual-frequency variant** (proven by strat2-ca-correctness). Specifically the
tie-out (a) "level offset mean −3.89 bp / median −4.31 bp (the CME-vs-LCH clearing
basis)" is a **misattribution — that offset was the annual/quarterly frequency gap**,
exactly reproduced as the negative control post-fix; the 0.9682 correlation passed anyway
because correlation grades nothing on a rank-linear table (w2b §7). The CA panel, screen,
`vs_model`, and both Sharpes are superseded (w2b on repaired Q/Q data: 0.130 gross, DEAD).
**What survives**: the convention-free kernel tie-outs — (b) roll identity
`CA(p)−CA(p−1)` vs Citi's own table max err 0.0100 bp on 12/12 with a reversed-column
negative control; (c) DV01 arithmetic `1000×4×$25 = $100,000/bp` and
`belly_DV01 = CA_DV01·β/100` at ratio 1.004/1.003 vs Citi's published notionals; (d) sign
probes (+$2,303,346 mirror-exact; futures marks −$11,250 = −4.50 bp × $25 × 100); implied
vol from Citi's CA reproduces Citi's IV column median 0.9973; the landmine that
`IRSwapStructure._build_fly` mutates `risk_weights` in place (pinned by test); the
coverage scan (windows 5..17 daily-reachable on 77/253/187/40/2/1/1/0 dates by year) —
later obsoleted by W1's warm; the Q12STIRT rejection (median 9.3 bp disagreement in 2019),
later refined by strat2-q20 (front-end only).
**On QDB P&L**: the doc claims every leg ran through `QueryDrivenBacktest` — leg marks are
traded-instrument prices, so the dollars are genuine for the book traded; but the matched
swap struck carried the annual convention's fair rate, and every entry was screened
against the biased CA series, so the *strategy* measured is not Citi's and its headline
does not survive the repaired data. Treat the whole backtest as superseded.

### 2.17 strat3-strikeless-vol-flatteners.md — CURRENT, no CA
**Measured**: delta-hedged ultra-long forward flatteners, 15 pairs, 2013/2019–2026.
Backtest 15Yx5Y/20Yx10Y via QDB (+$6.34m; ledger engine +$6.02m, daily-change corr
0.9997); direction dominates (mtm share ≥0.88 on every pair); only 8/15 profitable
ex-direction; grid winner Sharpe 0.765 vs E[max|null] 1.599 — **deflated Sharpe
p = 0.011, fails**; only `15Yx5Y/20Yx5Y` has non-negative mean carry; Citi's 15-30 bp
threshold claim only half-confirmed.
**Harness**: `strat3_strikeless_vol.py`, 2 executed notebooks, 57 tests, mutation checked.
**Suspect**: none. **Tie-outs**: **Citi Fig 7, close 2019-05-08, 8 pairs** (curve max
Δ 1.305 bp; 1y carry corr +0.991 — after replacing the brief's wrong carry field
`CARRY_AND_ROLL_BPS_RUNNING`, corr −0.136, with repriced `rl.Curve.roll`); Citi Fig 4
cross-sectional Spearman +0.714 on 7 overlapping pairs across disjoint samples; DV01
neutrality 1.5e-11; gamma reconstruction ratio 0.947–1.058; sign probe ±$2,303,346.
Known blocked path: `translate` gives exactly zero carry on par-struck forwards (pinned).

### 2.18 w1-ca-coverage-repair.md — CURRENT; the fix record
**Measured**: (1) the three shared-path defects (this is the primary in-results record of
the 2026-08-20 fix; commit `50e5fb29`, mutation-checked 4/4 — including the
default-frequency mutant that survived the first draft because every tie-out passed
`matched_frequency="Q"` explicitly); (2) Q12/Q16 node-horizon fix (short 6 quarters;
7 mixed curves allowlisted, not changed); (3) the SR3 deferred-settle warm (486 dates,
451 to depth 20, 1.66 h; 2018-19 tail measured unrecoverable — vendor serves nothing for
expired deep contracts, and the job's own acceptance check refused to call 313 empty
cells a win); (4) panel rebuild: Golds usable dates 28→244 (2023), 0→159 (2026);
**no published CA moved** (median Δca_bp −0.0000, p95 ≤0.0553 bp on 32,540 common rows) —
what moved is the gate diagnostic (Golds settle-diff 2.239→0.669 bp).
**Suspect**: none — this defines post-fix. **Tie-outs**: all three defects pinned to Citi
Fig 58; the annual variant retained as a negative control that must fail; the inverted
"2023 collapse" coverage test (a coverage number on a demand-driven cache is not a
finding). Residual known-not-fixed: Whites gate pass 0.572 (meeting-map degeneracy);
scheduled warm on primary checkout still pre-fix until merge; `sfr_cvx_adj` cache
orphaned, backfill not yet run.

### 2.19 w2b-ca-vs-swap-fly.md — CURRENT — DEAD
**Measured**: pack CA vs 2s5s10s swap fly on the repaired panel, 2021–2026, 1,406 days,
45 epochs, ranks 2–17 (Blues/Golds inside the fitted range for the first time). Gross
Sharpe **0.130 < E[max|null] 0.177** at six trials (and 0.548 on the annualised clock —
both reported, both failed); costs then remove 90% of gross. Hedge worse than no hedge
again (0.125 vs 0.130). §4: **the repaired data made the pre-repair result worse — the
0.470 pre-repair Sharpe was an accidental-sample artifact.** §5: Citi's dealer-positioning
mechanism REPRODUCES on Blues specifically (slope +5.28e-07, t 2.59, R² 0.124, HAC) — the
mechanism is real, the trade is not; the label-vs-rank trap documented (11-point
regression at opposite sign was an artifact). Dealers currently max-long (1,719,008
contracts) while leveraged money is min-short.
**Harness**: `w2b_ca_screener` + engine arms. **Suspect**: none.
**Tie-outs**: Citi Fig 58 re-graded **in bp on a level** (13/13, median 0.99 bp, worst
3.06, slope 0.850, +1.76 bp pedestal) after showing corr 0.966 survives ×2, ×100, +10 bp,
÷√252 mutations — the correlation-based check graded nothing. CFTC lagged 3 business days
to publication.

### 2.20 w3-ca-vs-longend-vol-rv.md — CURRENT — DEAD at diagnostic
**Measured**: STIR CA-implied vol (Ho-Lee inversion, parameter-free) vs ultra-long
flattener daily breakeven, 2021–2026, 16 combinations. Max |corr of daily changes|
0.112; level corr mostly negative (economically interesting, not tradable); 14/16 fail ADF
(the 2 rejections have 1.2–1.6-day half-lives). No engine run spent, deliberately.
Unit error caught and recorded: bp/yr spread against bp/day (factor √252) — correlation
was scale-invariant so the link diagnostics stood; a 0.5–40 bp/day median guard added.
ADF checker validated against both known answers (random walks must not reject; OU must).
**Suspect**: none (post-fix panel). **Tie-outs**: the checker's known-answer controls;
the screen retained with ADF p-value and half-life displayed beside the z-score.

### 2.21 w4-ultra-long-risk-adjusted-carry.md — CURRENT — DEAD; no CA dependence
**Measured**: ultra-long curve pairs on risk-adjusted carry, 2021–2026, 117 episodes,
mean hold 102 bd → n_eff ≈ 14. Gross Sharpe 0.397 < E[max|null] 0.446 (per-hold) and
0.702 (annualised) at 12 trials; net 0.180; drawdown −$20.2m gross. Factor attribution:
**level, not convexity** — level t = −4.85, incremental R² 0.1226 of a total 0.1244 (the
daily convexity t = −0.67 is the expected unidentified reading at daily frequency,
per DESIGN.md, not evidence of absence). Signal degenerated steepener-only for the last
three years. Four harness defects found by guards, none by a number looking wrong
(`exit_pct` wired to nothing; `min_hold_days` deleting episodes; `DateTrigger`
`pd.Timestamp` vs `date` never firing — flat equity reported as success; relative tenors
re-resolving daily → NPV ~0). `classify_pcs` mislabel (12 tenors vs 11 loadings) fixed.
**Suspect**: none. **Tie-outs**: rac screen vs Citi's 2019-12-04 table, 120 cells,
Spearman 0.988 on the decision statistic.

### 2.22 ca_coverage_diagnosis.md — CURRENT; coverage diagnosis + repair (2026-08-19)
**Measured (Part I)**: the coverage funnel with root causes ranked by dates lost —
`min_instruments=12` floor (463 rank-1 dates 2024-26; 15/15 discarded dates priced
cleanly offline at depth 7–10), `trim_to_contiguous_run` keeping longest-not-latest run
(truncation at exactly 2024-05-08 — "the ~May-2024 in the complaint"; 217/518 dates on the
Q20 near path), the 2.0 bp settle gate straddling the 2023 rank-1 distribution (median
2.22 bp), the `n_contracts=4`-unrepresentable config, row-based rolling windows (a
"252-day" window spanning up to 1,289 calendar days); settle/live separation a measured
zero (0 of 130,044 cells off the live feed; live source reaches depth 20 on zero dates
ever); warm cost re-measured (30 contract codes, ~64 min, not 10,230/170 h);
interpolation audit **on rendered plotly arrays** (152 bridging traces in 11 notebooks;
`connectgaps=False` inert because inner joins leave 0 NaN rows; checker self-tested
against a known 301/502-day gap after `bdata` decoding blinded the first version).
**Measured (Part II — the repair)**: floors separated (`min_instruments=4` +
`min_strip_depth=4`, the 12-floor rationale tested and refuted, 6/6 shallow solves at
median 0.31 bp), `day_rows` degrades instead of dropping, the **UTC-offset key defect**
(1,963 wrongly-stamped 17:00 keys; 51 dates scanned deeper than they resolve; 906 blocked
requests before the filter, 4 after), serial retry for shard contention, trim now a
`keep=` argument, `assert_settle_source` raises by name, `cache_only()` now patches httpx,
warm refuses today's session. Rebuild: rank-1 dates 1,410→1,946 (636 (date,rank) pairs by
code alone, 505 by fetching 103 `get_data` calls / 68 min, newest-first); near-pack
1,084→1,479. **Invariant: 23 columns exactly equal on every common row — 0 moved**;
16 rows lost to genuine cache decay (2018-12-06, vendor no longer serves it).
**Golds finding**: all 103 warmed dates reach depth 20 yet rank 17 gate-passes 0% at
median 3.17 bp settle diff — an edge-of-calibration effect (rank 17 spans the last four of
the twenty fitted instruments); the gate was deliberately left alone — honest fix is a
curve calibrated past rank 17. Charts: `ca_plots.py` (reindex + flag); `ca_vol_link.ipynb`
source-fixed, not re-executed; `BT/trade_dashboard.py` bridges deferred with reasoning.
**Suspect**: none — Q/Q throughout (`annual_qq_gap_bp` recorded on every row; §9.3
re-confirms the matched swap stays Q/Q). **Tie-outs**: Citi Fig 58 post-repair corr
0.9659 / max 3.06 bp / Blues 15.72; trim reproduces all three shipped artifacts exactly;
brief's evidence table reproduced 9/9 years; `strat2_q20` docstring table reproduced;
2023-06-09 canary 24/24; interpolation checker self-tests.

### 2.23 midcurve_feasibility.md — CURRENT, no CA
Full-length version of §2.7 (strat1-midcurve-feasibility is its results summary). Adds:
scope note that `option_snapshot`/`option_timeseries` were not run end-to-end (they
consume the proven raw-EOD layer but inherit the stale strike rule); per-run HTTP
accounting (~278 of 400 cap); reproduce commands; the parquet-is-regenerable warning
(each harvest run rewrites the panel to only the named contracts).
**Tie-outs**: QuikStrike ABPV +0.6%/+0.9% on two contracts spanning a 50% level gap,
mutation-tested; 20 `--verify` asserts; the wrong-underlying negative control honestly
reported as uninformative.

## 3. Cross-cutting register of pinned known answers (source → where asserted)

| known answer | value | source | asserted in |
|---|---|---|---|
| Citi Fig 58 CA screen (Rates Vol Lab 12-Jun-2023, close 6/9/2023, 13 rows, ranks 5–17) | Q/Q: median err 0.99 bp, worst 3.06, slope 0.850, intercept +1.76; corr 0.966–0.968; Blues 15.72 vs 15.40, Golds 21.73 vs 22.29; annual negative control −3.89/−4.31 must fail | Citi published table | ca-approach-taxonomy, strat2-ca-correctness, strat2-q20, strat2-sofr-cvx (pre-fix, misread offset), w1, w2b, ca_coverage_diagnosis |
| Citi Fig 58 roll identity `CA(p)−CA(p−1)` | max err 0.0100 bp on 12/12; reversed-column control 12/12 mismatch | same note | strat2-sofr-convexity-vs-fly |
| Citi implied-vol column from Citi's own CA | median ratio 0.9973 (13/13) | same note | strat2-sofr-cvx, strat2-q20 |
| Citi 5y fly notionals | `belly_DV01 = CA_DV01·β/100` ratio 1.004 ($100k, β21.4) / 1.003 ($200k, β20.6) | Citi note | strat2-sofr-cvx, strat2-fly-grid-engine |
| Citi Fig 7 (2019-05-08, 8 ultra-long pairs) | curve ≤1.305 bp, carry corr +0.991 (repriced roll), realized vol ≤0.228 bp | Citi note | strat3 |
| Citi Fig 4 pair Sharpes (2013-19) | cross-sectional Spearman +0.714 on 7 pairs, disjoint samples | Citi note | strat3 |
| Citi 2019-12-04 RAC table | 120 cells, rank Spearman 0.988 | Citi note | w4 |
| Citi "Sell ED convexity in Blues" Fig 4 positioning regression | reproduces on SOFR Blues only: slope +5.28e-07, t 2.59, R² 0.124 | Citi note (2013-17 original) | w2b |
| Engine sign probe (5Y payer, 2022-09-12..15) | **+$2,303,346**, mirror residual exactly 0 | live curve, reproduced in ≥4 docs | strat1-jpm-curve-as-gamma, strat1-listed-longend-cm, strat2-sofr-cvx, strat3, preflight G1 |
| Futures mark arithmetic | −$11,250 = −4.50 bp × $25 × 100 contracts | CME contract spec | strat2-sofr-cvx |
| CA identity on shipped panel | `(pack−swap)×100 − ca_bp` = 0.000e+00 on 29,643 rows | internal identity | ca-approach-taxonomy |
| Annual-vs-Q/Q gap | `0.375·r²` (3q²/8): measured b 0.36886 / 0.37195 / 1.00000 across three panels | closed-form prediction | strat2-ca-correctness, strat2-q20, strat2-grid-notebook |
| QuikStrike ABPV | SFRM26 44.74, SFRZ26 68.45 (ours +0.6/+0.9%); cross-vendor panel ratio median 0.9998 | CME QuikStrike | midcurve_feasibility, strat1-real-contract-panel |
| JPM package spot checks | 2023-06-09 p26 / 2019-08-27 p31 / 2026-08-13 p31 cell-exact; `as_of+DtE == expiry` 100.000% of 12,880 | JPM PDFs | jpm-package-parser, jpm-package-tieout |
| UST option expiry rule | corrected `ust_expiry` 263/263 vs repo `option_expiry_date` 253/263 (Christmas-Day/Memorial-Day defects) | CME rule + JPM printed DtE + vendor last-quote | strat1-real-contract-panel, jpm-package-parser, jpm-package-tieout |
| DESIGN.md §0 payoff table | 3 structures × 13 shifts reproduced ≤0.05 bp, repeatedly (incl. exact 0.0 replays) | pinned regression table, 2022-09-13 | strat1-jpm-curve-as-gamma, strat1-listed, strat1-listed-longend-cm, strat3, preflight |
| CME Jun-25 convexity P&L scenarios | 8/8 verified (−100→$22,292 … +100→$21,226) | CME publication | preflight synthesis (W1 kernel) |

## 4. What the fresh backtest must NOT inherit

1. **`strat2_panel.parquet`-era numbers** (strat2-sofr-convexity-vs-fly, strat2-fly-grid-
   engine): annual convention, misattributed −3.9 bp "clearing basis", the rank-5 fly
   spike, Sharpe 0.191/0.070, and the +$5.05m/0.470 near-pack reference — all superseded
   in-corpus. Any number quoting a CA level from before the Q/Q rebuild is suspect.
2. **Trim-artifact windows**: 2020-08..2024-05 (near), 743/301-day Q20 windows. Use
   `keep="latest"`/`"none"` + `window_span_tolerance`; the row-based rolling-window defect
   otherwise silently corrupts z-scores on sparse stretches (a "1Y" window spanning
   1,363 calendar days).
3. **Correlation-only tie-outs against rank-linear tables** — corr 0.966 survived ×2,
   ×100, +10 bp and ÷√252 mutations. Grade in bp on a level (median/max abs error, slope,
   intercept), with negative controls that must fail.
4. **Coverage numbers as findings** on a demand-driven cache, and `no_data` markers on
   the Barchart option cache (poisoned-batch writes).
5. **Unit seams**: bp/yr vs bp/day (silent √252 — three prior instances on record);
   `ABPV/ATM` differing by asset class; `delta_abs` percent; SFR price = 100 − rate.
6. **Golds at rank 17** gate-fails 100% post-warm for a real reason (edge of the 20-
   instrument calibration) — do not buy it back by loosening the 2.0 bp gate.
7. **Engine-certification scope**: panel CA legs certify at ~0.999; panel **hedged
   dollars do not** (aged-swap drift, −51% to −68% of the panel's headline). Certify any
   winning cell through `QueryDrivenBacktest` with `assert_ran` before quoting dollars.
8. **Null bars at the effective sample size, on both clocks** (per-hold and annualised) —
   the w2b/w4 discipline. Every strategy verdict in this corpus that cleared a nominal
   t-stat failed at n_eff.
