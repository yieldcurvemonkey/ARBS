# Fed Funds (ZQ) kink-fade — design

**Date:** 2026-07-30
**Branch:** `feat/sfr-kink-fade-v2`
**Companion:** `2026-07-30-sfr-kink-fade-v2-design.md` / `-findings.md`
**Outcome:** `2026-07-30-zq-kink-fade-findings.md`
**Rulebook:** CBOT Chapter 22, 30-Day Federal Funds Futures (local copy read and
verified; every constant below is quoted from it, not from memory).

## Why Fed Funds

The SR3 kink lab found that the FOMC calendar explains **1–6%** of a butterfly's
variance and that removing it does not make the kink tradeable. The natural
objection is that SR3 is the wrong instrument for the question:

| | SR3 | ZQ |
|---|---|---|
| accrual window | quarterly IMM (~91 days) | **one calendar month** |
| averaging | **compounded** daily SOFR | **arithmetic** average of daily EFFR |
| meeting entry | diluted, several overlapping | a clean two-regime day-count blend |
| $/bp | 25.00 | **41.67** |
| tick | 0.5bp flat | 0.5bp, **halving to 0.25bp** near delivery |

A 2026-12-09 decision takes effect on the 10th, so the December contract is
**9/31 pre and 22/31 post** while the January contract is *entirely* post until
the 2027-01-27 decision clips its last four days. **The January contract is the
clean read on the December meeting**, and "the calendar component" of any FF
spread is exactly computable rather than approximated.

If the kink-fade thesis has a natural habitat, it is here.

## What the rulebook actually says

Read from the local PDF, §-by-§, because three of these decide the cost model:

* **§22101** — each contract is $4,167 times the index.
* **§22102.B** — the index is `100 − R` where `R` is the **arithmetic average of
  the daily effective federal funds rate published by the FRBNY during the
  delivery month**; one basis point is worth **$41.67**.
* **§22102.C** — minimum fluctuation 0.005 index points ($20.835), **except**:
  * delivery month starts **Sat/Sun/Mon** → 0.0025 ($10.4175) from the **first
    Trading Day of the delivery month**;
  * delivery month starts **Tue–Fri** → 0.0025 from the **Trading Day
    immediately following the last Sunday of the preceding month**, i.e. the
    half-tick can begin *before* the delivery month.
* **§22102.F** — trading ends at the close of the **last Business Day of the
  delivery month**.
* **§22103** — for any day the FRBNY does not publish (weekend or US bank
  holiday), the rate is **the last preceding published rate**. The average is
  rounded to the nearest **tenth of a basis point**, ties **up** (the rule's own
  example: 2.5915 → 2.592 → price 97.408).

## The three traps, and how each is handled

### 1. Arithmetic, not compounded

A compounded window overstates the arithmetic average by roughly `r²·n/720` —
**0.69bp on a 31-day month at 4%**, nearly three ZQ half-ticks. That is the size
of the signal being tested, so it is not a rounding detail.

`RVUtils/MeanRev/ff.py::compounding_bias_bp` states the formula and it is tested.
The resolution is that **no analytical correction is needed**: rateslib's
`usd_stir1` spec is already the monthly averaged contract —
`frequency: m`, `roll: som`, `leg2_fixing_method: rfr_payment_delay_avg`,
`bp_value: 41.67`, `nominal: 5e6` — while `usd_stir` is quarterly IMM and
compounded at $25/bp. Measured directly on a curve, the two are **0.658bp**
apart on the same dates, matching the formula.

> ⚠ **The repo has a live trap here.** `is_ser` — the flag that selects
> `ReferenceRate3` (`usd_stir1`) over `ReferenceRate2` (`usd_stir`) — is derived
> from `root in {SR1, SER, SL}` in `RLSTIRFuturePricer.py:276`, `:350` and
> `MDP/IRSwaps/BARCHART_STIRF/rl.py:2521`. **`ZQ` is not in that set.** A ZQ
> routed through those predicates against a curve whose `ReferenceRate2` is
> `usd_stir` silently selects the quarterly compounded contract at $25/bp. Only
> `SDRUtils/stir_flow/ladder.py:37-40` gets it right, by passing `is_ser=True`
> explicitly via `FUTURES_SPACE_SPEC = {"FED_FUNDS": ("ZQ", True)}`. Reported,
> not fixed — it is a shared pricing seam.

### 2. The weekend/holiday carry rule

Exposure weights are computed on **calendar days with the published rate
forward-filled**, so a Friday's print carries Friday, Saturday and Sunday.
`applicable_source_day` makes the mapping explicit and `zq_exposure_vector`
classifies each day by its *source publication day*, not by the day itself.

The rule turns out to matter less than expected and more than nothing:

* Because every FOMC decision lands on a Wednesday or Thursday, its effective
  day (`D+1`) is normally a publication day, and then the carry rule does **not**
  move any weight — a day is post-meeting iff `d ≥ eff` either way.
* **Except once.** Sweeping 2018–2027, exactly one decision's effective day is
  not a publication day: **2025-06-18 → 2025-06-19 is Juneteenth**, a federal
  holiday since 2021. The new rate first reaches the average on Friday the 20th,
  moving one of June 2025's thirty days from post to pre — 3.3% of that
  contract's exposure to the meeting, ~0.8bp on a 25bp move.

This is pinned by `test_juneteenth_delays_the_2025_06_18_decision_by_a_day`, and
a synthetic Friday decision tests the branch that would fire on a projected
calendar.

### 3. The tick onset

`half_tick_onset` encodes §22102.C's two branches exactly. Measured consequence:
across the tradeable (pre-accrual) window the reduced tick applies to **0.6% of
live contract-days**, because the discount only begins once a contract is days
from ceasing to be a forward read. So the cost model is 0.5bp per contract in
practice — but the rule is encoded rather than approximated, and `zq_cost_panel`
reports the panel so the claim is visible.

The cost panel is **masked to live cells**. An unmasked one reports the cheap
tick on every long-expired contract (trivially "past its onset") and grossly
overstates the discount.

## Data

`notebooks/rv/build_zq_panel.py` — the monthly twin of `build_sfr_fly_panel.py`,
one Barchart EOD history request per contract symbol. Barchart's root for Fed
Funds is already `ZQ` (`STIRFutureMDP._to_barchart_symbol`: `SR3→SQ`, `SR1→SL`,
`ZQ→ZQ`), so only the contract-code generation changes — monthly, all twelve CME
month codes.

Built: **2018-01-02 → 2026-07-30, 2,159 sessions, 132 contracts, 103,483
contract-days**, median 47 pre-accrual contracts per session. The study uses
ranks 1–12; per-rank zero-volume and open-interest tables are printed rather than
a depth assumption being made.

`imm_start` / `imm_end` keep those names so the panel is a drop-in for the
MeanRev toolkit, but they are the **calendar month**: first day to first day of
the next month, so `(imm_end − imm_start).days` is exactly the settlement day
count (28/29/30/31).

## Definitions under test

**F1 — the raw M1-M2 spread.** The control, and as it turns out the only FF
structure whose oracle clears its round trip. Restricted to the
high-differential-exposure bucket.

**F2 — the FF kink.** Solve the strip for per-meeting jumps through the exposure
matrix, penalising the **second difference** of the jump sequence (the same
construction as the SR3 kink lab, so a linearly accelerating policy path is
fitted for free), then trade the residual spread. `lam` swept from saturated to
maximally stiff.

**F3 — the FF kink fly.** The same residual on a `1/-2/1` three-month package.

**Degeneracy.** A structure is pinned only when its legs have *identical*
exposure vectors, i.e. `max_m |Σ_j w_j·W[leg_j,m]| = 0`. The obvious alternative
— "is there a meeting between the two delivery-month starts" — is wrong, and the
first pass of this work measured it being wrong: the "no meeting between" spreads
moved *further* (sd 9.5bp against 8.8bp), because a meeting inside *either* month
splits the pair.

## The stop rule

The brief is explicit and it is the right rule: **measure the oracle ceiling
first**. A structure whose `E[|forward move|]` does not exceed its round trip
cannot be rescued by a better signal, because that expectation is precisely what
a trader with perfect foresight of the direction would capture. If the FF oracle
cannot clear cost, that is a complete answer and the grids are not run in hope.

## Honesty rules

Inherited verbatim from the SR3 labs — lag-1 fills, deterministic exits not
lagged twice, costs per **contract** once per completed trade, grid distribution
plus deflated Sharpe plus neighbourhood stability, sign-test both directions,
beat the linear shadow, split by regime, forward-fill only, and the same
`verdict` function.

Two adaptations the instrument forces:

* **Cost is not one number.** A ZQ spread is 2 contracts (1.0bp) and a fly is 4
  (2.0bp), so league rows carry a `taker_bp` column and `set_taker` is called per
  family. SR3 rows and ZQ rows in the same table are comparable on `avg_net_bp`
  and on verdict, and **not** on `net_bp_taker` without reading that column.
* **The shadow test differs.** A calendar spread's linear shadows are its two
  outright legs (1 contract, 0.5bp each), not a butterfly's belly and wings.
  `zq_shadow_block` runs those; every other reporting block is imported unchanged
  from `sfr_fly_meanrev_common` so all three labs are graded by identical code.

## Verification culture

The dealer-ladder harness shipped 23 defects across four review rounds with a
green suite before every one, and the SR3 kink lab found 12 more in its own
finished notebook — **every one of which flattered the hypothesis**. So for each
new statistic here, what *should* be true independently of the code was written
down first and tested:

* exposure vectors are bounded in [0,1] and monotone in meeting order;
* regime weights **sum to exactly 1** (a partition of the month's days cannot do
  otherwise);
* a month containing no meeting has a single regime and integer exposures;
* December-2026 is 9/31 pre and 22/31 post, hand-computed;
* January-2027 reads the December meeting at exactly 1.0 and the January meeting
  at 4/31;
* the rulebook's own rounding example reproduces, and the tie-up rule survives
  the float case (2.5925) that naive arithmetic gets wrong;
* the compounding bias matches `r²n/720`;
* the half-tick onset is before the 1st for Tue–Fri starts and on/after it for
  Sat/Sun/Mon starts;
* a full-tick `1/-2/1` package costs exactly the 2.0bp the SR3 lab uses.

## Deliverables

1. This spec and a findings doc answering: **does the FF complex, with its
   cleaner meeting capture, pay the kink-fade where SR3 did not — or does the
   coarser tick lattice kill it first?**
2. `RVUtils/MeanRev/ff.py` with 27 synthetic no-network tests.
3. `notebooks/rv/build_zq_panel.py`, `notebooks/backtests/zq_kink_fade_common.py`,
   and the executed `zq_kink_fade_backtest.ipynb`.
4. League rows in the same schema as the SR3 tables.
