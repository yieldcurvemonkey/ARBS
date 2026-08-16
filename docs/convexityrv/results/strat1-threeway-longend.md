# STRAT1 THREE-WAY ON THE LONG END — curve vs swaption vs LISTED

## 0. THE INTERSECTION, FIRST

| | SFR / short end (prior) | **UST / long end (this run)** |
|---|---|---|
| intersection | **517** dates, 2024-07-01..2026-07-28 | **1,854** dates, **2019-01-02..2026-08-11** |
| structures | SFR-sector stand-ins | strategy 1's **own** long-end four |
| swaption node | 1Yx2Y (proxy) | **1Yx30Y** (the note's node) |
| n_eff / structure | 2.05 | **7.50** |

Per structure (each statistic below uses **that structure's own** intersection): 5Y/30Y and 10Yx10Y/20Yx10Y **1,854** days (US-benchmarked); 30Y/50Y and 20Yx5Y/25Yx5Y **1,614** (UL-benchmarked); **1,614 common** to all four. Pooled usable rows **6,936 / 7,098**.

**The binding constraint is the swaption, not the exchange** — 47 of 1,901 days carry no 1Yx30Y ATMF; the listed panel is complete on all 1,901. That is the reverse of the short-end study.

## 1. THE THREE SERIES, AND THE RANKING

Medians bp/day at the pre-specified benchmark (`primary`@30d — primary fixed per structure by `UST_SECTOR_MAP` from measured CTD maturity, so **UL** for 30Y/50Y and 20Yx5Y/25Yx5Y, **US** for the other two):

| structure | listed | n | curve | swaption | listed | curve cheapest | swpn | listed | winner changes |
|---|---|---|---|---|---|---|---|---|---|
| 30Y/50Y | UL_30 | 1,614 | 0.000 | 5.214 | 5.322 | **1.0000** | 0 | 0 | **0.0000** (1 regime) |
| 20Yx5Y/25Yx5Y | UL_30 | 1,614 | 0.412 | 5.214 | 5.322 | **1.0000** | 0 | 0 | **0.0000** (1 regime) |
| 10Yx10Y/20Yx10Y | US_30 | 1,854 | 1.065 | 5.020 | 5.627 | **1.0000** | 0 | 0 | **0.0000** (1 regime) |
| 5Y/30Y | US_30 | 1,854 | 2.416 | 5.020 | 5.627 | 0.5076 | 0.4229 | 0.0696 | **0.0486** (91 regimes, 20.4 d) |

Listed is the **richest** of the three on 61.5% of pooled days. Three structures are saturated (`always_cheap` 34.2/42.3/84.9% of days); **5Y/30Y is the only one whose ranking moves**.

## 2. THE OTC−LISTED BASIS, AND THE FLIP-THRESHOLD RETEST

**Negative at all twelve benchmarks** — median bp/day: UL_30 −0.195, UL_60 −0.233, UL_90 −0.244, TN_30 −0.555, US_30 −0.545, US_60 −0.626, US_90 −0.706, TY_30 −0.802, TY_60 −0.859, TY_90 −0.826. The basis grows as the CTD gets *shorter*, i.e. as the sector match worsens. **The hypothesis is backwards: swaptions were the *cheap* comparison.**

Persistence: AR(1) ρ₁ 0.893–0.984, half-life **6.2–42.3** business days, but ρ₆₃ = 0.166–0.738 — a slow component AR(1) cannot see. Sign runs average **7.4–37.8 days**. This is a position, not a bid/offer.

Regime (median bp/day): US_30 −0.055 (2019) / −0.150 / −0.257 / **−1.573 (2022)** / −1.416 (2023) / −0.700 / −0.439 / −0.107 (2026) — negative on 100.0% of days in 2022 and 2023. UL_30's **sign flips**: +0.024 (2019) → −1.131 (2022) → +0.163 (2024) → **+0.376 (2026)**, positive on 82.2% of 2026 days. Driver: through 2022 listed reached 7.53 bp/day while the swaption only reached 5.95.

**The retest, identical expression** (`np.nanpercentile(|curve−swaption|, 25)`, `never_cheap` `+inf` days **included**, exactly as the short-end 2.721 was computed):

| structure | n | med \|basis\| | flip p25 | **ratio** | disagree | saturated |
|---|---|---|---|---|---|---|
| **5Y/30Y** | 1,854 | **0.5557** | **1.9165** | **3.449** | **3.34%** | **0.514** |
| 10Yx10Y/20Yx10Y | 1,854 | 0.5557 | 2.9358 | 5.283 | 0.00% | 1.000 |
| 20Yx5Y/25Yx5Y | 1,614 | 0.4244 | 4.1772 | 9.844 | 0.00% | 1.000 |
| 30Y/50Y | 1,614 | 0.4244 | 4.2426 | 9.998 | 0.00% | 1.000 |
| *SFR short end (prior)* | 2,585 | 0.2715 | 2.7206 | **10.021** | 1.59% | n/a |

**The factor of 10 becomes a factor of 3.4 — a 2.91× compression** — moving from both ends at once: basis **×2.05**, threshold **×0.70**. Disagreement **×2.11** (1.59% → 3.34%), exactly as that arithmetic predicts. Finite-only variant carried alongside: 2.397.

The bottom three rows are **saturation, not agreement**: with breakeven pinned at 0.0, `|curve−swaption|` degenerates to the swaption level (~4–5 bp/day). Selecting the binding structure must use `frac_verdict_saturated`, **not** sentinel share — those rank the universe differently (10Yx10Y has *fewer* sentinel days than 5Y/30Y, 0.342 vs 0.578, yet its verdict is unanimous). The module selects on saturation; a mutation test pins it.

## 3. SIGNAL AGREEMENT

Pooled **0.89%** (62/6,936). **All 62 disagreements come from 5Y/30Y (3.34%)**; the other three are exactly **0.0000**. Asymmetric: 2.70% "swaption rich / listed cheap" vs 0.65% the reverse — follows directly from the basis sign.

Across the 12 benchmarks 5Y/30Y runs **3.24%–5.34%**. The only two crossing the 5% bar are **TY control @60d (5.29%) and @90d (5.34%)** — the deliberately-wrong root, which has the largest basis *because* it is the worst sector match. That **strengthens** the verdict: the sector-matched benchmarks disagree least.

## 4. GATES ON IDENTICAL COHORTS

`both == cheapest` re-verified on the long end: **0 differences in 7,098 daily rows and 0 across 352 cohorts** — the identity holds, so **4** distinct gates. Newly measured: `listed_only` vs `either` differ on **12 of 7,098** daily rows but **0 of 352** cohort entries — they *coincide on this cohort grid* without being the same gate. **4 ex-ante trials, 3 realized books**; the correction uses 4 (using 3 would lower the bar on an accident of the calendar).

| gate | n_traded | n_closed | net_bp_mean | hit | Sharpe/cohort | t nominal | **t overlap-adj** |
|---|---|---|---|---|---|---|---|
| swaption_only | 338 | 290 | **+7.1036** | 0.6414 | **0.2423** | 4.126 | **0.664** |
| both / cheapest | 334 | 286 | +7.0573 | 0.6434 | 0.2405 | 4.067 | 0.659 |
| listed_only / either | 338 | 290 | +6.7889 | 0.6414 | 0.2309 | 3.932 | 0.632 |

The listed veto stood aside on **4 of 352** cohorts and moved the mean by **−0.046 bp/cohort**, against a per-cohort σ of **29.3**.

## 5. SAMPLE SIZE AND THE NULL

n_eff per structure = 2,740 d / 365.25 = **7.50** (short end 2.05 → **3.7×**). Measured pairwise unit-cohort-P&L correlation **r̄ = 0.698** (0.489 for 20Yx5Y/25Yx5Y vs 5Y/30Y, 0.862 for 30Y/50Y vs 10Yx10Y/20Yx10Y, 76 commonly-closed cohorts) → `k_eff = 4/(1+3·0.698) = 1.29` → **n_eff pooled = 9.70**, not 352.

E[max Sharpe | null], 4 trials: **0.0618 at nominal n=290** (the flattering version) vs **0.3327 at n_eff=10** (the honest one). Best gate **0.2423 < 0.3327 → FAILS**. Deflated Sharpe **0.3946** — worse than a coin flip. **No gate mode is recommended.**

## 6. TIE-OUTS (all asserted)

- `gate_swaption_only` == strategy 1's stored signal: **0 differ of 6,936** usable rows.
- Replay known-answer, stored direction → stored `net_pnl_bp`: max err **≤ 7.11e-15 bp**, all four structures.
- **Linearity, fresh 1,624 s engine pass on 5Y/30Y** (the only mixed book: 45 flatteners / 43 steepeners): **max_abs_err_bp = 0.0** over 76 matched closed cohorts.
- Cohort coverage: unit run 91 vs stored 88. **All three skipped entries explained by a missing swaption quote on the lagged date** (2020-01-31, 2020-02-28, and **Good Friday 2024-03-29**). Two carry gate 0. One (2024-04-01) a gate would have traded, worth **+29.696 bp gross** — omitted **identically from every gate**, so the gate comparison is unaffected; only absolute levels are, equally. Same date omitted from the other three books, unmeasured magnitude, identically across gates.
- Selected primary roots asserted equal to `UST_SECTOR_MAP`; unique `(date, structure)` key asserted.

## 7. VERDICT

**Listed is measurably closer to mattering on the long end than in the short end — and still decides nothing.** The shortfall multiple falls **10.02 → 3.45** (2.91×) and disagreement rises **1.59% → 3.34%** (2.11×), a real difference in kind between the sectors. But 3.34% is below the 5% materiality bar the short-end study set; three of four structures disagree on **exactly 0.00%** of days and their ranking never changes once in 1,854 days; the veto is worth **−0.046 bp/cohort** against σ 29.3; and the only benchmarks crossing 5% are the deliberately-wrong control. **The listed benchmark makes the long-end flatteners look cheaper, not richer** — the basis is negative at all twelve benchmarks.

What would change it: a **strike-level** UST futures-option panel. This compares ATM to ATM; wing basis could be several times the 0.556 bp/day ATM basis, which is the regime where the multiple falls below 1. No offline UST smile history exists (8 cached smiles on 2 dates).

## 8. VERIFICATION

36 new tests, **11/11 planted mutations CAUGHT** (module restored byte-identical, suite re-run green); 78 passing across both three-way suites including **9 slow data-backed tie-outs**; **482 passed** on the convexity fast gate; notebook **0 unrun, 0 errors, 5 figures**.

## 9. FILES

- `C:/Users/chris/clee/ARBS-cvx/RVUtils/ConvexityRV/strat1_threeway.py` — extended (SFR path untouched; `basis_frame` gained a guard that raises on a long-end panel while still accepting SFR shape)
- `C:/Users/chris/clee/ARBS-cvx/tests/test_convexity_rv_threeway_longend.py`
- `C:/Users/chris/clee/ARBS-cvx/notebooks/backtests/convexity_rv/strat1_threeway_longend.py`
- `C:/Users/chris/clee/ARBS-cvx/notebooks/backtests/convexity_rv/strat1_threeway_longend.ipynb` (executed)
- `C:/Users/chris/clee/ARBS-cvx/notebooks/backtests/convexity_rv/_strat1_threeway_longend_build.py`
- `C:/Users/chris/clee/ARBS-cvx/notebooks/backtests/convexity_rv/_longend_unit_run.py`
- Data: `notebooks/data/convexity_rv/strat1_threeway_longend_{panel,basis,books}.parquet`, `_sweep.csv`, `_linearity.json`, `_verdict.json`, `_unit_cohorts_5Y-30Y.parquet`

New public API: `longend_config`, `select_longend_benchmark`, `longend_threeway_frames`, `longend_intersection_report`, `longend_basis_frame`, `basis_persistence`, `basis_regime_table`, `flip_threshold_table`, `benchmark_sweep_table`, `gate_distinctness_table`, `cohort_pnl_correlation`, `effective_independent_n_pooled`, `longend_verdict`, `SHORT_END_REFERENCE`.