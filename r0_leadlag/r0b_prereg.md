# R0b — pre-registration

**The one authorized re-run.** Written and committed **before R0b was executed**;
verifiable from the git log against the mtimes of `out/r0b_*`.

Triggered by R0's D1: pooled 1-minute `rho = 0.405` against a 0.50 threshold,
all five decision buckets below it individually, so R0's FAIL was downgraded to
**UNINFORMATIVE**. The authorization is explicit and bounded: *"ρ < 0.5:
UNINFORMATIVE, and you authorize exactly one re-run with the Citi minute curve
as X, pre-registered before execution."*

**Exactly one.** If R0b is itself uninformative, that is the answer. There is no
R0c. Chasing a third specification is the forking path this whole design exists
to avoid.

---

## The single change from R0

X's direction sign comes from **`rate − Citi minute curve mid`** at the print's
snapped minute, instead of `rate − trailing same-key median`.

**This deliberately breaks R0's isolation rule, under authorization.** What is
imported is the *curve* — market data plus a repricing call. What is **not**
imported is the ladder's direction inference: no probability model, no `tau`, no
dead zone, no `signed_weight`. The sign is `+1` if the rate is above the curve
mid and `-1` if below, full stop. Re-coupling R0 to the ladder's own inference
would make it evaluate the thing it exists to evaluate.

**Everything else is byte-identical to R0**: the same bucket map, the same
`k = -30..+30`, the same bin-of-day fixed effects and five lags of Y, the same
day-clustered inference with Newey-West reported alongside, the same two clocks,
the same Y. `r0_prereg.md`'s PASS/FAIL/AMBIGUOUS rule applies verbatim on the
dissemination clock.

**Y is not touched.** The combo-exclusion and passive-aggression limitations
(below) are Y-side and survive R0b unchanged. R0b resolves the X-attenuation
axis only, and its verdict is bounded accordingly.

## Power — the informativeness gate, fixed now

`rho` is ~1 by construction, so addendum 1's downgrade rule cannot apply and is
not reused. It is replaced by a benchmark that is non-arbitrary because it is
measured in the same run:

> **R0b is informative iff its MDE is below the magnitude of the pre-print mass
> it measures** — i.e. the test must be able to detect an effect as large as the
> one effect it can actually see. Where that fails, the bucket is reported
> UNINFORMATIVE rather than FAIL, as in R0.

This is exactly the criterion R0 failed: three of five buckets could not have
detected an effect as large as their own pre-print mass. `MDE = 1.96 * SE / rho`,
with `rho` measured for R0b as it was for R0.

## The second payoff — the `k < 0` discriminator, fixed in advance

R0's sharpest caveat was that its significant `k < 0` mass has exactly the sign a
**stale trailing median** produces mechanically: futures are bought, yields fall,
the next swap prints sit below a median still holding older higher rates, so
`X < 0` follows `Y > 0` with no information content whatsoever.

A real-time curve mid removes that channel by construction. So R0b discriminates,
and the reading is pre-registered:

| R0b outcome at `k < 0` | reading |
|---|---|
| the trough **survives**, still spanning roughly `k = -20..-2` | genuine pre-dissemination futures activity associated with the print — pre-hedging, leakage, or a common driver |
| the trough **collapses to `\|k\| <= 1`** | it was the stale-median artifact, as R0's caveat 1 hypothesised |
| the trough **vanishes entirely** | same conclusion, more strongly |

The collapse-to-`|k| <= 1` case is the sharp one and deserves saying why: the
curve is read at `T-1min`, so sub-minute staleness remains and would show at
`k = -1` alone. A **spread** trough cannot be produced by a one-minute lag.

**Neither outcome is tradeable.** Pre-dissemination activity is by definition not
actionable from the public print. The value is knowing which of the two the data
contains, which the R0 design could not distinguish.

## What R0b cannot fix, stated now so it is not discovered later

1. **Combo instruments are excluded from Y**, and bucket-specifically: 24.66% of
   `sr3` and 20.67% of `zq` traded volume against 10–15% for the Treasury roots.
   Front-end hedging is substantially done in packs and bundles, which are
   exactly those discarded instruments — so this is **selective removal of a
   component of Y**, not classical measurement error, and it is plausibly where
   the front-end hedge lives. **R0b's verdict is therefore decisive for the belly
   and long end (TU/FV/TY_UXY/US) and provisional for SFR_FF**, pending
   leg-level combo reconstruction, which is a scoped follow-up and is not run
   here.
2. **Y is aggressor-signed, and a passively worked hedge enters with the opposite
   sign.** A dealer who is long duration and sells futures by resting offers is
   lifted by a buyer, contributing **positive** Y where the registered prediction
   is negative. A hedge executed as a mix of aggressive and passive therefore
   partially self-cancels in Y, and the limit of that cancellation is a null. No
   version of R0 or R0b can separate this, because MBO carries no counterparty.
   It is recorded as a bound on what any aggressor-signed test can conclude.

## Discipline

One specification, run once, reported — including if it looks wrong. No variant
re-runs. If a data issue blocks R0b, stop and report rather than substituting a
workaround that changes the test.
