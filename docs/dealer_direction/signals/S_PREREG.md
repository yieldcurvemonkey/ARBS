# Signal search on the dealer-direction infra — pre-registration

**Written and committed before any signal was estimated.** Verifiable from the
git log against the mtimes of `BT/dd_signals/out/`.

R0 tested the intraday premise and did not find a tradeable channel. This is the
search for what else the infrastructure supports. The point of writing it down
first is that I am about to run several tests on one dataset of 2.3M prints,
where everything is significant and nothing is true.

---

## 0. What this infra uniquely provides

Not "a dataset" — these five things together, which is a combination nobody
outside has:

1. **Per-trade direction with a calibrated probability**, 2024-03-01..2026-08-07,
   on a mid with **no measured convention bias** (median printed − mid
   = +0.021 bp, bootstrap CI includes zero, placebo IQR 48.8× wider).
2. **Signed key-rate DV01**, 28 pillars, tied out against an independent analytic
   route to 0.0001% of total DV01.
3. **A real dissemination clock** — 100% recovery, median 4.70 min.
4. **Citi minute curves** — SOFR 1,535 days, Fed Funds 2,708 days, and an
   already-warmed **intraday swap-spread series (MI01, 4 years × 11 tenors,
   1.255M rows)**.
5. **Package structure**: the tape *labels* spreadovers (106,121 legs),
   matched-maturity (60,270) and invoice swaps (32,058) — trades whose economic
   content is a **swap spread**, not a swap rate.

Point 5 against point 4 is the observation this search is built on: **the tape
tells you who transacted swap spreads, and the target series for swap spreads is
already warmed at minute resolution.**

## 1. The cost hurdle, stated BEFORE any result

This repo has a long run of edges that were real and too small: the SR3 fly
reverts but earns +0.75 bp against a 2.0 bp round trip; SR3 RV 0/47 alive;
linvol 0/272; outcome-map 0/360. The failure mode is always the same — a
statistically significant edge below the cost line, discovered after the fact.

So the cost is measured first, from this repo's own executed-cost evidence, and
**a test that cannot clear it is not run**:

| instrument | round-trip cost | source |
|---|---|---|
| swap spread (matched-maturity / invoice) | **to be measured before the test**, from the tape's own printed spreads and the MI01 mid | measured, not assumed |
| outright SOFR swap, liquid tenor | as above | measured |

**Kill rule, fixed now:** if the *in-sample gross* edge per trade is below
**2× the measured round-trip cost**, the test is declared dead and the hold-out
is **not** opened. An edge that barely clears in-sample does not survive
out-of-sample, and burning the hold-out to confirm that wastes the only clean
sample there is.

## 2. Sample split, fixed now

| | window |
|---|---|
| **design / in-sample** | 2024-03-01 .. 2025-08-31 |
| **hold-out — not opened until the specification is frozen** | 2025-09-01 .. 2026-08-07 |

The hold-out is opened **once**, for whichever candidates survive §1's kill rule,
and the specification is not adjusted afterwards.

## 3. Multiplicity

Two hypotheses are pre-registered below. Both are reported whatever they show,
and significance is assessed at **p < 0.025** (Bonferroni over two). Any
candidate not on this list that gets tested later is a **new** pre-registration,
not a variant of this one.

---

## S1 — Signed swap-spread flow predicts the swap spread

**Hypothesis.** Spreadover, matched-maturity and invoice packages are swap-spread
trades. Their net signed customer flow in a tenor bucket predicts that bucket's
swap spread over the following 1–5 business days.

**Mechanism.** A customer paying the spread leaves the dealer receiving it; the
dealer holds spread risk it must lay off, and the price moves against the
inventory before reverting. This is the same inventory logic R0 tested
intraday — at a horizon R0 says nothing about.

**Direction, fixed in advance.** Customer **pays** the spread → dealer
**receives** the spread → dealer is long the spread → the pending trade is
**selling** it → the spread should **fall** over the horizon. A positive signed
customer flow predicts a **negative** spread change. A positive coefficient of
the same size is a different phenomenon, not a pass.

**Why this is not what the ladder excludes.** These families are currently
`EXCL_UNORIENTABLE` because a swap-spread package cannot be oriented from the
*swap* rate alone — the bond is not priced on this tape. But
`package_transaction_spread` **is** the traded spread, in bp, and MI01 is the
model spread. The deviation is directly available without the repricing that
blocked the ladder. **Establish the units against a known answer before using
them** — the tape's printed spread must reconcile to MI01 on the population
where both exist, or nothing downstream means anything.

**Target.** Change in the Citi MI01 swap spread for the matching tenor.

## S2 — Daily dealer positioning predicts multi-day reversal

**Hypothesis.** The net signed customer DV01 a dealer absorbs in a bucket on day
*t* predicts a partial reversal of that bucket's rate over days *t+1..t+5*.

**Why re-test something already called dead.** The dealer-ladder programme
concluded "no signal" (gross −0.046 bp, t = −0.79). That verdict was reached on
labels that are **78% one-directional because of a half-basis-point curve bias**,
measured four independent ways. A classifier that one-sided cannot produce a
meaningful positioning series — the integral is a drift term plus noise — so the
prior verdict is **uninformative, not null**. Three things are now different:
the labels are unbiased, the risk is a signed KRD vector rather than a scalar,
and the coverage is 610 days rather than 138.

**Direction, fixed in advance.** Dealer **receives** fixed (long duration) →
dealer must sell → the rate should **rise** over the horizon. Positive dealer
DV01 predicts a **positive** rate change.

**Conditioning, declared now so it is not chosen later.** One conditioner only:
the **D2D/D2C volume ratio** in the same bucket, as a proxy for the dealer being
at a risk limit and therefore forced. The unconditional test is primary; the
conditional test is secondary and reported alongside, not instead.

**Within-bucket only.** The package-skew measurement forbids cross-sectional
comparison (1.54× retention distortion across buckets), so no curve or
cross-bucket structure is tested here. If the recovery route lands (retention
56.96% → 79.12%, distortion halved), a cross-sectional test becomes possible and
is a **new** pre-registration.

**The 1–2Y bucket is excluded from S2** — its exclusion rate drifts at
+5.07 pp/yr (t = +3.21), which contaminates the level in exactly the way a
positioning signal would read as information.

---

## 4. What would make either test uninformative rather than negative

Recorded in advance so it cannot be invoked selectively — the same discipline
that turned R0's FAIL into an honest UNINFORMATIVE:

- **Power.** As in R0: the test must be able to detect an effect as large as the
  smallest effect that would clear §1's cost hurdle. Report that MDE. If the MDE
  exceeds the hurdle, the answer is UNINFORMATIVE, not "no signal".
- **Fewer than ~200 usable bucket-days** in a bucket.
- **The S1 units failing to reconcile** against MI01 on the overlap population.
- Standard errors are clustered **by day**, as in R0. `N_eff` is trading days,
  not prints.

## 5. Discipline

One specification per hypothesis, run once on the design sample, then once on
the hold-out if and only if the kill rule is cleared. Anything that looks wrong
is reported as a caveat rather than re-run as a variant. Neither result is
acted on without being surfaced first.
