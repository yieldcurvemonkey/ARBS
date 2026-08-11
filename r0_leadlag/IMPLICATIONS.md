# R0 — implications

**A recommendation to be surfaced, not acted on. No ladder code was changed.**

R0's verdict is **FAIL** on the dissemination clock, which selects the pre-registered
FAIL branch:

> **FAIL** → retarget the ladder to a DAILY street-positioning indicator: drop the
> intraday hedge-trigger and max-pain components, keep the tape reconstruction, direction
> inference, and change-of-basis.

That is the recommendation. What follows is why it is the right branch and, more usefully,
what R0 measured that sharpens it.

## Why the FAIL is the branch and not the downgrade

None of the prereg's three "uninformative rather than negative" conditions fired: 67
session dates (44 for SFR_FF) against a ~20-day floor, substantial futures flow in every
bucket, and a dissemination clock that was **100.00% recovered** rather than estimated.
Addendum-1's downgrade rule is the only remaining path, and its outcome is recorded in
`R0_RESULT.md`.

The failure is also not marginal or a single-bucket artefact. `sum(beta_k, k>=1)` is
+0.0076 with t = +0.59 pooled; **five of five decision buckets** show significant
pre-print mass and **zero of five** show significant post-print mass; and the estimator
was demonstrated, on this same code path and this same grid, to recover an injected effect
of similar size at k = +7 with t = −41.9.

## The finding that matters more than the verdict

The premise being tested was that a hedge is *observable and tradeable after the print*.
R0 says something sharper than "no":

1. **On the dissemination clock the mass is at `k < 0`**, concentrated at k = −5 to −11,
   with 48% of the `|beta|` mass in k = −17..−2. The independently measured publication
   lag is p5 2.77 / p50 4.70 / p95 17.23 minutes. The futures flow associated with a print
   is, on average, **already finished by the time that print is public**. D2 confirms it
   attenuation-invariantly: the `|beta|` centroid moves 3.20 bins earlier when you switch
   from the execution clock to the dissemination clock.

2. **On the execution clock there is no significant post-execution mass either**
   (pooled `sum(beta_k, k>=1)` = −0.0029, t = −1.51). Addendum 1 fixed in advance that
   execution-clock `k > 0` mass is what "the hedge mechanism exists" would look like. At
   pooled level it is not there. This is the more damning of the two panels: it is not
   only that the opportunity closes before the print, it is that R0 cannot see the
   mechanism at all at one-minute resolution with a crude tape-internal direction sign.

3. **The significant `k < 0` mass should not be read as leakage or pre-hedging.** A stale
   trailing median produces exactly that sign mechanically: futures bought → yields fall →
   later prints sit below a median holding older, higher rates → classified
   customer-received. This is a price-impact chain with no information content, and it
   predicts precisely the measured pattern on both clocks. It is a caveat on the `k < 0`
   finding, not on the FAIL — the FAIL rests on `k >= 1` being zero, which no staleness
   artefact manufactures.

## What this recommends, concretely

**Drop.** The intraday hedge-trigger component and the max-pain component. Both are
premised on a post-print window in which dealer hedging is observable and can be traded
against. R0 measured that window at one-minute resolution across 67 sessions and five
tenor buckets and found nothing in it. Sizing them "small" is not the answer here — the
AMBIGUOUS branch, which is what sizing-to-the-measured-share belongs to, was not selected,
and the measured post-print share is 0.066 with a t-statistic of 0.59, which is not a
share to size to but an estimate consistent with zero.

**Keep.** The tape reconstruction, the direction inference, and the change of basis. R0
tested none of them — it deliberately used a crude, ladder-free direction sign precisely
so that a negative result would not implicate them. Nothing here is evidence against the
KRD engine, the projection matrix, or the probability model.

**Retarget.** A daily street-positioning indicator. R0's negative result is specifically
about a *one-minute, thirty-bin* horizon. Two things in the measurement point the same
way:

- The publication lag alone (p50 4.70 min, p95 17.23 min) consumes a large fraction of a
  30-minute window. At a daily horizon it is irrelevant.
- The pre-print mass, whatever its cause, says the tape and the futures book are
  genuinely coupled — the relationship exists, it is just not *forecastable from the
  public print* at intraday resolution. A cumulative daily positioning measure does not
  need the print to lead the hedge; it needs the day's flow to describe the day's
  inventory.

**One thing worth knowing before the retarget.** If the daily indicator keeps a
tape-internal rolling-median direction sign, the staleness channel described above will
contaminate it in the same way and at a lower frequency it may be worse, not better,
because a longer window is a staler median. The direction sign should be taken from the
curve stack the ladder already owns, not from a tape-internal median — the median was
R0's isolation requirement, not a design recommendation.

## What R0 does not license

It does not license a claim that dealers do not hedge swaps with futures. It licenses the
narrower claim that **the public SDR print is not a usable intraday trigger for that
hedge** — because the hedge is largely done before the print is public, and because what
remains after the print is statistically indistinguishable from zero under standard errors
clustered at the only sample size that matters here, roughly 67 trading days.
