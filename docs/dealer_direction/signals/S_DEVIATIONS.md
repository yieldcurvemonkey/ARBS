# Signal search — deviations from `S_PREREG.md`

`S_PREREG.md` is committed at `5ec6a7dd` and **has not been edited**. Everything
the data forced, and every error found in the pre-registration itself, is
recorded here instead.

Written by the coordinator, not by the agents that ran the tests — they
correctly declined to write it, since a runner amending its own pre-registration
is the manoeuvre the file exists to prevent.

---

## D1 — THE PRE-REGISTRATION CONTAINS A SIGN ERROR IN S1. Mine.

`S_PREREG.md:86-90` states:

> Customer **pays** the spread → dealer **receives** the spread → dealer is
> **long the spread** → the pending trade is **selling** it → the spread should
> **fall**.

The third step is wrong. Paying a swap spread is paying fixed on the swap and
buying the Treasury; that position gains when the spread **widens**, so the
customer is long the spread and **the dealer is short it**. A short must be
bought back, and buying pushes the spread **up**. Under the same inventory
mechanism the pre-registration intended, S1's predicted sign is therefore
**β > 0**, not β < 0.

S2's chain has no such error — dealer receives fixed → long duration → must
sell → rate rises → β > 0 — which is why the two, as written, could not both
follow from one mechanism. That inconsistency is what surfaced the bug.

**What this does and does not change.**

- It does **not** change the verdict. **Zero cells were significant in either
  direction**: the largest |t| anywhere is **1.66** against size-corrected
  criticals of 2.51–2.63, and the best edge anywhere is **0.174 bp/trade at 20Y
  k=5 against its own 1.332 bp hurdle — 7.7x short**. (An earlier draft quoted
  0.117 against 0.659 as "the best edge"; that is the **10Y k=3** cell, not the
  maximum. Both readings give DEAD.) A sign error cannot rescue a result that is not
  significant either way.
- It **does** withdraw a characterisation I reported: that "the deepest buckets
  go the wrong way, 5Y and 30Y β positive where the hypothesis predicts
  negative". Under the corrected direction those are the *expected* sign. They
  are still insignificant and their realised edge is still negative, so nothing
  is rescued — but the "wrong way" reading was produced by my own error and is
  retracted.
- An earlier draft said, on the review's word, that the DEAD-vs-AMBIGUOUS split
  is "convention-dependent for 11 of 35 cells". **That does not reproduce — it is
  0 of 35**, and the correction strengthens the conclusion rather than weakening
  it. Re-running S1's own frozen verdict ladder
  (`s1_spread_flow.py:728-739`, `MIN_BUCKET_DAYS = 200`) over `s1_results.csv`
  reproduces the file **35/35** under the pre-registered sign and changes **0**
  verdicts under the corrected one. The structural reason: `sign_ok` reaches the
  ladder only through `(not sign_ok) and sig_beta -> WRONG_SIGN`, and `sig_beta`
  is False in all 35 cells. What *does* flip on all 35 is the `sign_ok` flag
  itself — a different quantity, and not a verdict.
  Measured by the research notebook, `notebooks/dealer_direction/`, cell 65.

**I am not re-reading the results under the corrected sign to look for a
finding.** The correction is recorded, the verdict stands on the criterion that
does not depend on it (nothing significant, nothing near the cost line), and the
next pre-registration on this infrastructure must hand-trace both directions
against the pinned convention before it is committed. That check took the
reviewer one paragraph and would have caught this.

## D2 — S2 is reported UNINFORMATIVE, not as a powered null

The S2 run reported the pooled cell as "the first cell in the programme with the
power to have seen a hurdle-sized effect". **That claim is withdrawn**, on three
independent grounds, any one of which is sufficient:

1. **The hurdle it is powered against is not a cost.** Pooled MDE 1.847 bp
   against a kill threshold of 2.154 bp — so the cell is "powered" only if the
   true outright SOFR round trip exceeds **0.92 bp of rate**. `COSTS.md` says of
   its own S2 column that it is "not a bid-offer; it is mostly the T−1min
   curve's own error", and its ceiling-free estimate is **0.71 bp** with D2D
   ceilings at 0.28–0.61 bp. Under any of those, kill < MDE.
2. **The size correction S1 applied was not applied to S2, and it flips the
   verdict.** `MDE_Z = 3.083` is the *normal* multiplier, while the module's own
   validation measured Driscoll–Kraay rejecting a true null at **7.8%** against
   a nominal 5%. Re-simulated under the module's own null DGP: corrected
   critical 2.896, pooled MDE **2.239 > 2.154** → UNINFORMATIVE_POWER. Under a
   DGP recalibrated to the measured panel it survives by 0.03 bp. Either way the
   claim is not robust.
3. **The pooled panel is not the pre-registered unit.** `S_PREREG.md:126-130`
   says *"Within-bucket only … no curve or cross-bucket structure is tested
   here."* The run made the pooled nine-bucket panel primary and demoted the
   per-bucket cells to diagnostics. **The pre-registered cells are 8 of 9
   `UNINFORMATIVE_POWER`.** The deviation converts nine underpowered
   pre-registered tests into one un-pre-registered test that is the only
   "powered" cell in the programme, which is precisely the shape the
   pre-registration exists to forbid.

**Verdict as it stands: S2 is UNINFORMATIVE.** Its edge is *negative* (−0.32 bp),
so the cost caveat is not what binds — a negative edge clears no cost of any
size — but the honest label is that this test could not have found a
hurdle-sized effect in the unit it was registered on.

## D3 — the S2 cost hurdle is not measurable by the named route; the kill rule is one-sided

`S_PREREG.md:1` assumes a measurable round-trip cost for both instruments. For
S1 it exists and is model-free: **99.7–100% of interdealer spreadover spreads
print on a 0.125 bp lattice**, and p90 of consecutive-print moves is exactly one
grid step, so bid and offer are at least one increment apart.

For S2 there is **no lattice for a negotiated par rate**, and the ceiling
estimator `2·sqrt(m2)` is dominated by our own curve error rather than by any
bid-offer. So the kill rule applies to S2 **one-sided only**:

- an edge **above** the ceiling hurdle clears under any reading;
- an edge **below** it is **UNINFORMATIVE_COST**, never DEAD.

Reporting S2 dead against a 1.06–2.79 bp hurdle would report a curve-error
artefact as a market fact.

**A better S2 cost estimator exists and was not used** (recorded for the next
run): the same-minute, same-tenor difference between a D2C print and a D2D
print differences the curve out entirely, leaving the client-vs-interdealer
spread. That is a direct bid-offer proxy and does not depend on a lattice.

## D4 — scope reductions, all measured

- **S1 is SPREADOVER only.** `S_PREREG.md`'s own reconciliation clause fired for
  MATCHED_MATURITY and INVOICE: `b0` to **+16.7 bp**, `s` to **17.9 bp** against
  MI01, because an invoice spread is quoted to a **futures CTD forward**, not to
  the swap-spread series. About one third of the 198k named legs were tested.
  This is the caveat most able to limit S1's scope.
  Spreadover itself reconciles decisively: median printed − MI01 inside 0.05 bp
  at every tenor × venue, **+0.001 bp overall on 61,476 packages**.
- **S2 is SOFR only** (FED_FUNDS dropped, ~3% of universe DV01) and **FLOW
  only** (LIFECYCLE is a separate series by design).
- **S2 uses a 15:00 ET availability cut** `(D−1 15:00, D 15:00]`, matching S1,
  rather than the ladder's NY-calendar-date grain. Moves 13.4% of priced units
  off their `as_of_date`.
- **S2 borrowed the upfront-rule `tau`** from the same bucket's rate-rule
  mixture fit. Bounded by a rate-only diagnostic: β +0.029, edge +0.008 bp, same
  null, *smaller* SE.

## D5 — two estimator specifications in the pre-registration did not survive validation

Both were replaced **before** the real pass, and both corrections moved results
**against** the hypotheses:

- **"Newey-West lag = k with normal criticals" rejects a true null at 5–7%**
  (plain OLS: 29%) under a persistent regressor with overlapping horizons.
  Wider bandwidths and a block bootstrap did not fix it. Criticals are now
  simulated per cell from (n, k, ρ_F); corrected size 0.4–2.3%, power 0.77–0.81.
  One cell was load-bearing: 10Y D2D k=3 would have been "significant" at 2.241
  and is not at 2.667.
- **The placebo was mis-designed as a null.** Re-signing against the previous
  session's mid makes it a spread-*reversal* signal, which earns **0.21 bp** at
  10Y — more than the primary. Reported as a miss and replaced by an oracle
  plumbing test: planting `−sign(close(t+1) − close(t))` returns β = −0.53 to
  −0.73 with hit rate exactly **1.000**, collapsing to 0.08 one day stale.

## D6 — a structural fact that reframes every k=1 verdict

**At k = 1 a perfect one-day-ahead oracle earns 0.78–0.90× the D2C hurdle** —
i.e. the required hit rate exceeds 100%. The instrument cannot pay at that
horizon *with perfect foresight*, so a k=1 DEAD verdict is a statement about the
trade, not about the flow. At k ≥ 2 the oracle clears (1.13–2.08×, needing
74–94% accuracy) and those cells are genuine powered tests.

Any future search on this infrastructure should compute the oracle ceiling
**before** running the test, and not run cells where it is below 1.

## D7 — a defect in the probability module, found by the cost work

`probability._independent_half_spread`'s `median_tick / 2` is **degenerate on a
two-sided book**: consecutive-print `|Δp|` is 0 or 2h with probability ½ each,
so its median is a coin flip — returning 0.000–0.216 for a true h of 0.25 in
simulation. It applies to clip-heavy populations like this one, where 5–83% of
consecutive differences are exactly zero. Roll (1984) is unbiased there.

Recorded against the module; the mixture fit's own gate already refuses these
buckets, so nothing shipped on it.

## What the pre-registration got right, for the next one

The mixture fit **refused to resolve `h`** on every spreadover bucket. `costs.csv`
carries **21** of them (7 tenors x {ALL, D2C, D2D}) with separation
**0.013–0.050**; the 14 non-`ALL` rows are the 0.025–0.050 subset an earlier
draft quoted as the whole. All are flagged `SEPARATION_BELOW_FLOOR`
and `LEPTOKURTIC`) — and validation showed the fit is unbiased only above that
gate and biased **−80% downward** below it. Had the gate not existed, `2h` would
have argued the cost **down by 5–20×** and both hypotheses would have "cleared".

The gate was written before any of this and it is the single thing that stopped
a false positive.
