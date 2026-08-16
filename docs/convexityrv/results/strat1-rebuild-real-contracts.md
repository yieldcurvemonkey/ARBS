All verified: re-exports live in both shared modules, CM APIs intact, both `.ipynb` newer than their sources.

# STRAT1-LISTED + THREEWAY REBUILT ON REAL LISTED CONTRACTS

**1,901 curve dates · 2019-01-02..2026-08-14 · 8 real benchmarks (US, TY × 4 expiry rules) · zero engine runs, zero network.** 28/28 tests pass (24 fast + 4 data-backed); **12/12 mutations caught**, module restored byte-for-byte; full `convexity_rv` fast suite **484 passed**.

## THE THREE ANSWERS

**(a) Cheap-share against a REAL contract.** Against `US@H365` the long-end flatteners are cheap gamma on **100.0% of days on three of the four structures** (30Y/50Y, 20Yx5Y/25Yx5Y, 10Yx10Y/20Yx10Y) and on **54.8%** of 1,901 days on **5Y/30Y** — against **51.4%** for the same structure vs 1Yx30Y swaptions. The premise survives: the 100% is a property of the **curve's own carry** (breakeven pinned at the `always_cheap` sentinel on 100% of days there), not of swaptions being the expensive benchmark. Note the premise as stated is only true for three of four — 5Y/30Y was never at 100% against swaptions either.

**(b) Did CM change any verdict? Adequate for the VERDICT, biased for the LEVEL — and incapable of two whole sections.** Same curve rows, same swaption, only `listed_atm_bp_day` differs:

| structure | n | cheap CM | cheap real | verdict differs | `both` gate differs |
|---|---|---|---|---|---|
| 3 saturated | 1,901 ea | 1.000 | 1.000 | **0.00%** (0 days) | 0.00% |
| 5Y/30Y | 1,901 | 0.5334 | 0.5476 | **2.37%** (45 days) | **2.37%** (44 rows) |
| POOLED | 7,604 | 0.8834 | 0.8869 | 0.59% | 0.59% |

Real prices **+0.116 bp/day** more vol (level corr 0.940, change corr 0.735). Cause is measured, not asserted — the ageing table: ratio real/CM **1.002 at 25–35d → 0.997 at 50–75d → 1.030 at 105–150d → 1.061 at 150–250d**, and the horizon-matched contract sits at a median **133 days**. `swaption_only` differs on **exactly 0** rows between the two runs (the alignment check that licenses the rest).

**(c) Long-end OTC-listed basis, like-for-like with the short end's factor of 10:**

| | median \|basis\| | flip p25 | **ratio** | disagree |
|---|---|---|---|---|
| SFR short end (prior) | 0.271 | 2.721 | **10.02** | 1.59% |
| long end, CM control (`US_30`) | 0.556 | 1.917 | **3.45** | 3.34% |
| long end, **REAL** (`US@H365`) | **0.818** | 1.917 | **2.34** | **3.88%** |

The flip threshold is **identical** across the two long-end rows (it never reads the listed benchmark), so the whole move is the basis widening **+47%**. Net: a **4.3-fold compression** vs the short end — the basis is materially closer to mattering on a real contract — and still **not big enough**: the listed veto stood aside on **4 of 352 cohorts** and moved the mean by **−0.043 bp/cohort**.

## THE THREE EXPLOITATIONS

1. **Expiry matching.** Longest listed UST option expiry in the whole sample is **241 days** vs a 365-day horizon → best gap **−124 d**, median **−232 d**, against the CM control's constant **−335 d**: **103 days closer, not matched.** `frac_selected_is_longest = 1.000` — measured against the full ladder — i.e. at a 365-day target "nearest" degenerates to "longest listed" (stated, not hidden). There is no 365-day CM series at all; the vendor quotes 30/60/90 only.
2. **Funded straddle** (`sqrt(2/pi)·σ·√T`, reusing `strat1_curve_gamma`'s kernel, carry pro-rated to the option's own 133-day life). 5Y/30Y: carry negative on **63.9%** of days, median **57 contracts** (p95 200), **$7,378 premium/contract**, **8.6% of package DV01**. **30Y/50Y carries positively on 86.3% of days — nothing to fund.** Contract count uses CTD FV01 $138.8/contract (US), which ties out to market.
3. **Roll.** **47 rolls** over 1,901 days (~40-day holds, 47 distinct deliverables). Benchmark jumps **2.74×** its ordinary daily move on a roll day (0.241 vs 0.088 bp/day) — a real discontinuity CM smooths away — and flips the signal on **0 of 47** rolls.

**Bonus (smile — impossible under CM):** 25D quotes converted via the panel's own `ABPV/ATM`; US RR median **−3.08 bp/yr** (puts bid, 70.1% of rows), fly **+1.39 bp/yr** (positive 87.6%). Expected-payoff signal: **100% valid densities**, agrees with breakeven on **89.1%** (5Y/30Y) and 99–100% elsewhere. Caveat carried per row: density is at the option's expiry, and only **±39.5 bp** of strike is quoted against a ±250 bp grid.

## HONESTY

- **True intersection: 1,854 dates (2019-01-02..2026-08-11)**, bound by the **swaption cube** (7,416 of 7,604 rows), not the contracts, which cover all 1,901 curve dates.
- **n_eff = 7.50/structure; 9.70 pooled** (measured r̄ = 0.698, k_eff = 1.29 of 4). Best gate `swaption_only` Sharpe **0.2495** vs **E[max|null] = 0.333** at 4 distinct gate modes → **does not clear its own null**; deflated Sharpe 0.403. No P&L claim made.
- **UL and TN are NOT available as real contracts** (`ULM26` → *"Invalid UST option contract token"*). UL is the sector primary for 30Y/50Y and 20Yx5Y/25Yx5Y, so on half the universe the best available real benchmark is the map's *alt*. Measured cost: **UL_30 − US_30 = −0.345 bp/day** (1,662 dates), i.e. substituting US **raises** the benchmark and makes the curve look cheaper — the missing contract biases the headline **towards** the conclusion already reached.
- **Three of four structures cannot answer the question** — saturated at 100% against every one of the 8 benchmarks, so their 0.00% disagreement is arithmetic. The study rests on 5Y/30Y. The TY wrong-sector control does separate (prices 0.06–0.14 bp/day more vol, disagreement 4.9–5.4% vs US's 3.2–4.0%).

## FILES

Modules: `C:/Users/chris/clee/ARBS-cvx/RVUtils/ConvexityRV/strat1_real_contracts.py` (new, 1,556 lines); `.../strat1_listed.py` and `.../strat1_threeway.py` extended by an **appended lazy re-export block** (PEP-562 `__getattr__` — an eager import closes the cycle `strat1_listed → strat1_real_contracts → strat1_threeway → strat1_listed`). All existing CM APIs verified intact.

Notebooks (executed, 0 unrun / 0 errors): `.../notebooks/backtests/convexity_rv/strat1_listed_contracts.py|.ipynb` (22 cells) and `.../strat1_threeway_contracts.py|.ipynb` (19 cells). Builder: `.../notebooks/backtests/convexity_rv/_strat1_contracts_build.py` (`panels` 30 s / `payoff` 214 s / `threeway` 1 s).

Tests: `C:/Users/chris/clee/ARBS-cvx/tests/test_convexity_rv_real_contracts.py`.

Artifacts in `C:/Users/chris/clee/ARBS-cvx/notebooks/data/convexity_rv/`: `strat1_contracts_panel.parquet` (60,340×50), `strat1_contracts_cm_control.parquet` (62,333×43), `strat1_contracts_{selection,roll,ageing,cm_vs_real,straddle_summary}.csv`, `strat1_contracts_{straddle,smile,expected_payoff}.parquet`, `strat1_threeway_contracts_{basis,books}.parquet`, `strat1_threeway_contracts_sweep.csv`, `strat1_{contracts,threeway_contracts}_verdict.json`.

**One caught bug worth flagging:** the CM-vs-real POOLED row initially cross-joined four structures on `date` alone, reporting 17% disagreement where the truth is 0.59%. Fixed, and pinned by `test_pooled_join_is_by_date_and_structure` (mutation-verified).