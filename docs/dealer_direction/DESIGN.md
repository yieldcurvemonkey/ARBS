# Dealer direction inference on the USD swap SDR tape — design

Branch `feat/dealer-direction`. Companion to `LEDGER.md` (measurements) —
this file is the *reasoning*, including the options rejected.

---

## 0. The one convention everything obeys

```
customer pays fixed  ->  dealer RECEIVED fixed  ->  dealer long duration
                     ->  the pending hedge is SELLING futures
                     ->  delta_dv01 > 0  in the persisted ladder
```

`p` always means **p(customer paid fixed) = p(dealer received fixed)**.
Inherited unchanged from `SDRUtils/stir_flow/ladder_conventions.py` so the
tie-out is meaningful.

---

## 1. The probability model, derived rather than chosen

The brief specifies `p = sigma((rate - mid) / tau)` with `tau ≈ the rolling
dealer-to-client half-spread`. The functional form is right; **the
identification of `tau` with the half-spread is not**, and the difference
matters because it changes what has to be estimated.

### 1.1 Derivation

Let `h > 0` be the dealer-to-client half-spread for a bucket and `s` the
standard deviation of our *mid measurement error* (curve fitting error,
convention mismatch, the T−1min timing gap). Let `b0` be a systematic bias in
our mid. For a print with observed deviation `x = P_traded - P_mid`:

```
x | customer paid fixed      ~  N(b0 + h, s^2)
x | customer received fixed  ~  N(b0 - h, s^2)
```

With a symmetric prior, Bayes gives exactly a logistic:

```
p(customer paid | x) = sigma( 2h(x - b0) / s^2 ) = sigma( (x - b0) / tau )

                    tau = s^2 / (2h)
```

So **`tau` is the measurement variance over twice the half-spread**, not the
half-spread. Two consequences the half-spread reading would miss:

- A bucket with a *wide* spread is **more** decidable, not less — `tau`
  shrinks as `h` grows. Using `tau = h` gets the comparative static backwards.
- Mid quality enters *quadratically*. Halving `s` quarters `tau`. This is why
  the curve work was the blocker, and why a per-bucket bias `b0` has to be
  estimated rather than assumed zero.

### 1.2 Estimation — a symmetric two-component mixture

The unconditional distribution of `x` in a bucket is

```
0.5 * N(b0 + h, s^2)  +  0.5 * N(b0 - h, s^2)
```

Three free parameters `(b0, h, s)`, fitted per bucket by maximum likelihood on
a trimmed sample. Equal weights are *imposed*, not fitted: a free weight is not
separately identifiable from `b0` at realistic separations, and letting it
float would silently absorb a curve bias into an apparent flow imbalance —
which is precisely the error that would invert calls rather than degrade them.

Two independent checks on every fit, because a fitted `tau` that is wrong is
invisible:

1. **Moment closed form.** With `m2`, `m4` the central moments,
   `s^2 = m2 - sqrt(m2^2 - (m4 - m2^2)/2)` and `h^2 = m2 - s^2`. This has a
   real solution only when the excess kurtosis is negative (a separated
   mixture is platykurtic). A bucket whose sample is leptokurtic is telling
   us the two-component model does not hold there — that is a **diagnostic
   that fires**, not a fit that quietly degrades. Such buckets fall back to a
   robust scale and are flagged in provenance.
2. **`h` against an independent spread estimate.** Sub-3y, `stir_flow`'s
   `tick_size.py` measures a consecutive-print tick; `confidence.py::sigma_mid`
   already does the same variance decomposition
   (`sqrt(disp_jns^2 - half^2)`) by hand. The new fit must reproduce it where
   both exist. Beyond 3y there is no tick lattice, so the mixture fit is the
   only estimator — which is exactly why it has to be validated where a second
   opinion exists.

### 1.3 Why not just a dead zone

The brief asks for a dead zone below ~0.05–0.1 bp and for `p` to multiply the
DV01. Those two do not compose: at `p = 0.5` a `p`-weighted contribution is
`0.5 * DV01`, a **half-size long**, not a coin flip. The expected signed DV01
is

```
E[sign] * DV01 = (p * (+1) + (1-p) * (-1)) * DV01 = (2p - 1) * DV01
```

so the ladder aggregates `(2p - 1)`, which is zero at `p = 0.5` and makes a
dead zone almost redundant. Both `p` and `signed_weight = 2p - 1` are exposed
per trade; the dead-zone flag is retained for health monitoring and for
consumers who want a hard filter, but it is not what the aggregation depends
on.

---

## 2. The upfront rule — and a sign contradiction in the brief

### 2.1 The brief's statement is not decidable as written

> Off-market / PV: reprice the swap. If the NPV is higher than the reported
> other-payment amount, the dealer received fixed / customer paid fixed.

The payer and receiver of the other payment are not disseminated, so an
unsigned amount cannot be compared to a signed NPV. The brief recognises this
and asks for an edge-capture formulation instead. **A naive edge-capture rule
is also not identified**: with the fee sign free, both direction hypotheses can
always be made to imply non-negative dealer edge, by choosing the fee sign.

### 2.2 What makes it identified

The missing constraint is physical: **the fee flows from the party receiving
value to the party giving it up.** The party taking the in-the-money side pays
for it. That ties the fee sign to the hypothesis and closes the system.

Let `A` be the annuity (dV/dR), `R` the printed fixed rate, `m` the mid, and
`f = (m - R) * A` the NPV to the fixed *payer*. Let `U >= 0` be the observed
other-payment amount.

- If the dealer takes the ITM side, it pays `U` and the edge is `|f| - U`.
- If the dealer gives up the ITM side, it receives `U` and the edge is `U - |f|`.

Exactly one is non-negative. So:

```
dealer holds the ITM side   <=>   U < |f|
ITM side is PAY fixed       <=>   f > 0   (i.e. R < m)
```

which is **precisely what `stir_flow/classifier.py:77-80` already implements**
(`dealer_bought = upfront < abs(npv_pay)`). The brief asked for a second
solver; the correct answer is that the existing hard rule is right and needs
only to be made probabilistic.

### 2.3 The contradiction, and how it gets settled empirically

Take the brief's rule literally with `NPV` meaning the payer-frame NPV: `NPV >
U` with `NPV > 0` gives ITM = pay-fixed and dealer-holds-ITM, i.e. **dealer
PAID fixed** — the opposite of what the brief says. The two are reconcilable
only if the brief's `NPV` is in the receiver frame or is the customer's NPV.

This is not settled by argument. It is settled by a test that exists because
of F-10: **275,540 flow legs carry an upfront while not being rate outliers**,
so for those the rate rule and the upfront rule *both* apply and must agree.
Their agreement rate is a direct, self-contained measurement of whether the
upfront rule's sign is right. Under the derivation above they agree; if the
measurement says otherwise, the derivation is wrong and gets fixed. Either way
the answer is a number, not an opinion.

Worked consistency check for the derivation: suppose `R > m`, so the rate rule
says the customer paid fixed above mid and the dealer received. Then
`f = (m - R) * A < 0`, the ITM side is *receive* fixed, and the dealer holds
it — so `U < |f|`, with the dealer paying the customer slightly less than the
customer's position is worth. Consistent.

### 2.4 Confidence on the upfront rule

`edge_bps = (|f| - U) / structure_DV01`, signed towards the H1 hypothesis, then
the same logistic with a **separately calibrated** `tau_upfront`. Separate
because the noise is different in kind: NPV error grows with duration, and the
fee carries its own rounding and its own currency/notation hazards.

---

## 3. Packages — one binary, then the whole vector

A package has one price. Classifying legs and voting produces confident
nonsense on curves and flies. The generalisation that actually works:

Each unit gets a **base orientation** `o` (a per-leg `±1`, `+1` = pay fixed)
and **quote weights** `q` from its structure convention, so that the unit's
price is `P = Σ q_i R_i` and the base-orientation holder is the party who
*pays* `P`. Then the single general rule is:

```
P_traded > P_mid   =>   the base-orientation holder overpaid
                   =>   the base holder is the CUSTOMER
                   =>   the dealer holds -o
```

For an outright (`o = (+1)`, `q = (1)`) this reduces to `R > mid => dealer
received`. For a curve (`o = (-1, +1)`, `q = (-1, +1)`, legs sorted by
maturity) it reduces to the traded-spread-vs-mid-spread rule. For a fly
(`q = (-1, +2, -1)`) it reduces to the fly rule. The choice of base orientation
is arbitrary *provided* `P` is defined as the price paid by the base holder —
the inferred global sign absorbs it. Only that consistency has to be right, and
it is unit-testable per structure.

The **KRD vector then follows from the same binary**: the dealer's position is
`dealer_sign * o` applied to the printed leg notionals, so one inferred bit
yields the entire signed key-rate profile. There is no separate "direction" to
name for a 17-leg package.

For `PKG-N` with `N >= 4` there is no standard quote convention and the base
orientation is not determined by the structure. Those units are **not
force-classified**: they are marked unclassifiable, excluded from the ladder,
and their DV01 share is reported. Deciding that share is a measurement, not a
guess — it is an open item.

---

## 4. Two clocks, and a third that is the honest one

| clock | field | used for |
|---|---|---|
| execution | `execution_timestamp` (#96), `original_execution_timestamp` | **pricing** — the curve snapshot |
| event | `event_timestamp` (#30) | carried, transparency only |
| visibility | derived, Part 43 Appendix C | **availability** — every aggregation |

F-3 measured `report_lag_seconds` at p90 = 0 for blocks and non-blocks alike,
so `event_timestamp` is not an availability bound; the tape has no
dissemination timestamp at all. The Appendix C legal-delay estimate in
`ladder_conventions.visibility_timestamp` is the only defensible availability
clock, and it is *more* conservative than event time. All three go on every
row so a consumer can disagree.

---

## 5. Module layout

New package `SDRUtils/dealer_direction/`. `stir_flow` is **frozen** — the
tie-out needs the old classifier runnable unchanged.

```
conventions.py   the sign convention, base orientations, quote weights
universe.py      unit construction, filters, D2C/D2D, capped handling
snapshot.py      curve instant + session-branched SnapshotPolicy
midprice.py      reprice a unit -> P_mid, per-leg mid, NPV, annuity
probability.py   mixture fit, tau, p, signed_weight, dead zone
upfront.py       the edge-capture rule, made probabilistic
krd.py           signed key-rate DV01 profile
lifecycle.py     terminations / unwind-as-new-trade handling
imputation.py    capped-notional tail model
ladder.py        aggregation; D2C and D2D kept separate
health.py        D2D hit-rate monitor + the coverage fractions
provenance.py    per-row: curve, snapshot, realised lag, rule, imputation
```

---

## 6. Options rejected

| option | why rejected |
|---|---|
| `tau` = the half-spread, as briefed | derivation gives `s^2/(2h)`; the half-spread reading inverts the comparative static in `h` |
| hard dead zone as the only marginal-call handling | `(2p-1)` weighting makes a coin flip contribute zero automatically; a dead zone alone leaves `p=0.5` contributing half a position |
| a second other-payment sign solver | the existing hard rule in `classifier.py` is the identified formulation; it needs a probability, not a replacement |
| adding a lineage column to the tape | 610 prod days delete-and-rewrite for a flip that F-8 shows is mostly not needed |
| `event_timestamp` as the availability clock, as briefed | measured p90 lag = 0; it is not a bound |
| routing on `is_off_market` | F-10: it is a rate-outlier heuristic, disagreeing with upfront presence on 524k legs |
| free mixture weight | not identifiable from `b0`; would absorb curve bias as flow imbalance |
| leg-by-leg classification with a vote | confident nonsense on curves and flies |
| hand-rolled analytic KRD by cashflow bucketing | instructed against, and rateslib's `Solver` + `Portfolio.delta` gives risk to the calibrating instruments directly — the bucket set is the instrument set and the Jacobian is a by-product of the calibration |
| PCA to reduce the ladder | unstable out of sample, and a PC bucket is not hedgeable with one instrument; the consumer wants a Jacobian change of basis, which rateslib already provides |
| force-classifying `PKG-N`, N>=4 | no quote convention determines the base orientation; exclusion with a reported DV01 share is the honest answer |
