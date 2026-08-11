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
