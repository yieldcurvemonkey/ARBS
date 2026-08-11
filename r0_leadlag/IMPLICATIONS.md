# R0 — implications

**A recommendation to be surfaced, not acted on. No ladder code was changed.**

## The branch question comes first

R0 returns **FAIL** under `r0_prereg.md`'s rule, and **UNINFORMATIVE** as reported, because
`r0_prereg_addendum_1.md`'s downgrade rule fired: the attenuation of R0's direction proxy
measured `rho = 0.405`, below the pre-registered 0.50, in **all five** decision buckets.

The three pre-registered branches are PASS, FAIL and AMBIGUOUS. **UNINFORMATIVE is not one
of them** — the addendum that created it was written after those branches were set. So:

> **The FAIL branch should not be executed on this evidence.** R0 did not establish the
> null; it established that it lacked the power to test it. The premise is **untested, not
> dead**. Which branch to take is the orchestrator's call, not one to make by picking the
> nearest available label.

## Why executing the FAIL branch would be wrong

Dropping the intraday hedge-trigger and max-pain components is a one-way door justified by
a null. This null cannot bear it:

- **Implied MDE = 0.062** standardised units — the smallest true post-print effect R0 could
  have seen.
- Attenuation-corrected, the 95% interval on the **true** post-print sum is
  **(−0.043, +0.081)**. A real hedge channel of −0.043 — the pre-registered direction, and
  two-thirds the size of the pre-print mass that *was* detected — is not excluded.
- The addendum's specific worry is confirmed, not merely possible: `rho` falls from 0.499
  at print level to 0.405 at one minute to **0.274 daily** (0.023 in SFR_FF). The rolling
  median is high-passing the flow, which is exactly what damps a burst of same-direction
  customer flow — the thing that should generate a hedge.

Attenuation runs one way: it hides real effects and never manufactures them. "Not seen",
not "not there".

## What R0 did establish (attenuation-proof)

Damping shrinks magnitudes without moving mass between lags, so these survive: the mass
sits at `k = −5..−11`, **inside** the measured 2.77–17.23 min publication lag, with 48% of
it in `k = −17..−2`; D2's centroid shift of −3.20 bins between clocks is a ratio and so is
invariant; and `k < 0` is significant (t = −5.90) while `k > 0` is not (t = +0.59), a
contrast unaffected by a common scale factor.

*Caveat on reading the `k < 0` mass as leakage:* a stale trailing median produces it
mechanically — futures bought → yields fall → later prints sit below a median holding
older, higher rates → classified customer-received. At 68.3% per-print sign agreement that
channel is live, so this is not evidence of pre-hedging.

## Recommendation

**Do not execute the FAIL branch yet. Re-test with a curve-based direction sign.** The one
defect that produced UNINFORMATIVE is the proxy, and it exists only because R0's isolation
rule forbade the curve stack — the right call for a first independent test, and the thing
that capped the power. The fix is already scoped: `cache_d1_ref/` holds the 12 tenors ×
~97,861 one-minute par rates D1 built, joining the tape at **100.0%** with a per-day median
deviation of −0.06 bp. Substituting `dev_curve` for `dev_median` should push `rho` towards
1 and the MDE from 0.062 towards ~0.025. Y, the grid, the estimator and the chart are built
and validated. **This needs a new pre-registration** — re-estimating with a better X after
seeing R0's result is precisely the variant R0's own prereg forbids.

**And it is a _later, different_ test, not a rerun of this one.** D1 was allowed to read the
Citi minute curve because it only *sizes the measurement error* in R0's own input, which is
a property of R0. **Rebuilding X on that curve is a different thing entirely: it breaks
R0's isolation rule**, which is the constraint that made R0 an independent test of the
premise rather than a check of the curve stack against itself. So the re-test does not
inherit R0's status, its prereg, or its claim to independence — it is a new experiment with
a new question, and it must be labelled and pre-registered as one. What it would need: the
same Y, grid, estimator and clock machinery (all built and validated), X rebuilt with
`dev_curve` in place of `dev_median`, and a fresh prereg written before the first beta.
**The cost of not doing it is now measured, not guessed:** `rho = 0.405` and
**MDE = 0.062**, against a measured post-print sum of +0.0076 — so the present test can
only exclude true effects larger than about eight times what it saw, and a curve-based X
would be expected to pull the MDE down toward ~0.025.

**If that spend is refused,** treat it as AMBIGUOUS rather than FAIL: keep the intraday
component, sized to the measured post-print share of **0.066**. That discards nothing on
evidence that cannot bear it, and sizes nothing as though the premise were confirmed.

**Keep unconditionally:** the tape reconstruction, direction inference, and change of
basis. R0 tested none of them, deliberately.

**True on any branch:** the ladder's direction sign should not be a tape-internal rolling
median. A *daily* street-positioning indicator — the FAIL branch's own retarget — would use
a longer and therefore staler window, inheriting the defect that made R0 uninformative.

## What R0 does not license

Not a claim that dealers do not hedge swaps with futures, and not dismantling the intraday
components. One narrow, well-measured claim only: **the futures flow associated with a swap
print is mostly finished before that print is public.** Anything stronger needs a direction
sign this test was not allowed to use.

---

# R0b — implications

**The re-test recommended above was authorized, pre-registered (`r0b_prereg.md`), and run
once. This section supersedes the recommendation above, which was written not knowing its
result. Still a recommendation to be surfaced, not acted on. No ladder code was changed.**

## The branch

**R0b returns FAIL under `r0_prereg.md`'s rule, and the branch its verdict implies is the
FAIL branch — now supportable on the X axis, for TU / FV / TY_UXY / US only.**

What changed, in one line each:

- **The defect that produced UNINFORMATIVE is gone.** `rho` is 1 by construction. The
  pooled MDE falls from **0.0620 to 0.0177**, better than the ~0.025 this file predicted,
  and improves by 2.4×–13.6× in **every** bucket.
- **The interval that blocked the branch now closes.** R0's attenuation-corrected 95%
  interval on the true post-print sum was `(-0.043, +0.081)`, and −0.043 "is not excluded"
  was the sentence that stopped the one-way door. R0b's is **`(-0.0188, +0.0165)`**. A hedge
  channel of −0.043 is excluded. So is one of −0.02.
- **The one significant finding R0 had was an artifact.** The `k < 0` trough — the thing
  this file listed under "what R0 did establish (attenuation-proof)" — **does not survive
  the change of mid rule**. `sum(beta_k, k<=-1)` goes from −0.1075 (t = −5.90) to +0.0159
  (t = +1.955, insignificant, *opposite sign*), and 88% of R0b's whole `|beta_k|` profile is
  what pure noise would produce. The caveat in this file's own "What R0 did establish"
  section was right, and it is now measured rather than hypothesised.

**Two things in this file must therefore be struck.** The claim that the mass "sits at
`k = -5..-11`, inside the measured publication lag" and the D2 centroid shift of −3.20 bins
were labelled attenuation-proof. They are attenuation-proof and they are still **not**
mid-rule-proof: under a real-time curve the centroid moves from −6.46 to −0.570 bins and
the trough is gone. Nothing in R0 survives as evidence of pre-dissemination activity.

## The gate says UNINFORMATIVE, and why that does not restore the R0 situation

`r0b_prereg.md`'s informativeness gate — MDE below the pre-print mass it measures — returns
**UNINFORMATIVE in all six scopes**, and that label is reported, not argued away. But the
degeneracy was pre-declared in `r0b_deviations.md` R0b-6 before the estimator was written:
when the discriminator fires, `|S_neg| -> 0` and the gate fails *by construction* however
good the power is.

The two situations are opposites and the branch decision turns on the difference:

| | R0 | R0b |
|---|---|---|
| why the gate failed | the test was **blind** — MDE 0.062 against a real, significant 0.107 pre-print mass | the **yardstick evaporated** — MDE 0.0177 against a 0.0159 residue that is insignificant and 88% noise |
| could it exclude a −0.043 channel? | **no** | **yes** |
| what to do | do not walk through the one-way door | the X-side objection is resolved |

R0 lacked the power to test the premise. R0b has it, and finds nothing. Those license
different actions, and treating them as the same label would be the error the gate exists
to prevent, run backwards.

## Scope — what the FAIL branch may be executed on

**Decisive for TU / FV / TY_UXY / US. Provisional for SFR_FF**, per `r0b_prereg.md`, and
doubly so: the front end loses 24.66% (`sr3`) and 20.67% (`zq`) of traded volume to the
excluded combo instruments on the **Y** side, and R0b's X covers only **30.1%** of its DV01
on the **X** side, because front-end swaps are disproportionately forward-starting and a
forward-start print cannot be signed against a spot par rate. Do not retire the front-end
intraday component on this evidence; the scoped follow-up that would settle it is
**leg-level combo reconstruction**, which was named in `r0b_prereg.md` and deliberately not
run here.

## What survives R0b unchanged, and bounds any dismantling

`r0b_prereg.md` fixed these in advance as things R0b cannot fix, and it did not fix them:

1. **Combo exclusion from Y is selective removal, not classical measurement error.** A
   dealer hedging with a futures *spread* is invisible to Y, and packs and bundles are
   exactly where front-end hedging lives.
2. **Y is aggressor-signed.** A passively worked hedge enters with the *opposite* sign, so
   a mixed aggressive/passive execution partially self-cancels in Y and the limit of that
   cancellation is a null. **No aggressor-signed test can separate this**, R0b included.

So the honest statement of what is now established is narrower than "dealers do not hedge":
**tape-print-triggered futures flow in the belly and long end, measured as aggressor
volume, is not detected at a resolution of ~0.018 standardised units on the dissemination
clock (95% interval −0.0188 to +0.0165) or ~0.016 on the execution clock.** That is enough to
retire an intraday component whose premise is "the print predicts the hedge". It is not
enough to claim the hedge does not happen.

## Recommendation

1. **Execute the FAIL branch for TU / FV / TY_UXY / US**: retire the intraday
   hedge-trigger and max-pain components whose premise is that a public swap print predicts
   subsequent aggressive futures flow. The evidence is now a measured exclusion, not an
   absence of power.
2. **Hold SFR_FF.** Retire it only after leg-level combo reconstruction, or retire it on a
   separate rationale that does not depend on R0/R0b.
3. **Keep unconditionally:** the tape reconstruction, direction inference, and change of
   basis. Neither R0 nor R0b tested them.
4. **True on any branch, and now with a measured price:** the ladder's direction sign should
   not be a tape-internal rolling median. Its sign agreement with a real-time curve is
   **67.6%**, its attenuation is **~0.42** at print level after correcting for the
   reference's own error, and — the sharpest finding — a trailing median **manufactures a
   significant, coherent, entirely spurious lead-lag trough**. A daily street-positioning
   indicator would use a longer, staler window and inherit that defect amplified.
5. **There is no R0c.** `r0b_prereg.md` is explicit. If the residual questions matter, they
   are Y-side questions — combo reconstruction and passive-fill signing — and they need
   their own design, not a third X.

## What R0b does not license

R0b reads the Citi curve stack, so it is **not** the independent test R0 was designed to be;
it cannot be used to validate that stack, and it says nothing about the ladder. It does not
show that dealers fail to hedge — only that no such flow is visible in aggressor-signed,
outright-only futures volume around the print, at a resolution 3.5× finer than R0's. And
its X sees 57.7% of in-window DV01, so it is silent about the forward-starting and MAC flow
it cannot sign.
