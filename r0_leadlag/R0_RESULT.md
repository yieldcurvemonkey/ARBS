# R0 — result

**Verdict under `r0_prereg.md`, verbatim, on the dissemination clock: FAIL.**
**Verdict as reported, after the `r0_prereg_addendum_1.md` downgrade rule fired:
UNINFORMATIVE.**

Both labels are stated because the pre-registration and its addendum require different
things of the same run. The pre-registered decision rule returns FAIL. The addendum's
downgrade rule — written before any beta was estimated, and able only to soften a FAIL,
never to create a PASS — then applies, because the measured attenuation of R0's direction
proxy is `rho = 0.405`, below its 0.50 threshold, in **all five** decision buckets.

**In one sentence:** customer swap flow as inferred from the public SDR tape shows *no*
detectable relationship with subsequent futures aggressor volume, and what relationship
there is sits entirely *before* the print — but the direction proxy R0 was required to use
is too weak (`rho = 0.405`) for that null to be trusted, so the premise is **untested, not
dead**.

Run once, one specification, on 2026-08-11. Estimator: `r0_leadlag/run_r0.py`.
Outputs: `out/r0_betas.png`, `out/r0_table.csv`, `out/r0_betas.csv`, `out/r0_run.log`.

---

## The headline

```
N_days = 67   (distinct CME session dates in the estimation sample)
N_bins = 402,946 bucket-minute observations
          (of 421,666 on Y's grid; 18,720 dropped as session edges)
```

| bucket | N_days | N_bins |
|---|---|---|
| SFR_FF | 44 | 57,600 |
| TU | 67 | 86,331 |
| FV | 67 | 86,336 |
| TY_UXY | 67 | 86,340 |
| US | 67 | 86,339 |

**Pooled, dissemination clock, all flow — the panel the decision rule is read off:**

| quantity | value | day-clustered SE | day-clustered t | Newey-West t (60) |
|---|---|---|---|---|
| `sum(beta_k, k <= -1)` | **−0.10746** | 0.01823 | **−5.90** | −9.03 |
| `sum(beta_k, k >= +1)` | **+0.00761** | 0.01280 | **+0.59** | +0.64 |
| difference (pos − neg) | +0.11508 | 0.02220 | **+5.18** | +6.36 |
| `beta_(k=0)` | −0.00135 | 0.00216 | −0.63 | — |

- `|S_pos| / |S_neg|` = **0.071**. PASS needs ≥ 2.0.
- post-print share = **0.066**.
- Day-clustered and Newey-West **agree** on every significance call in this panel.

Against the pre-registered rule:

> FAIL = mass concentrated at `k < 0`, **or** post-print mass indistinguishable from zero
> under day-clustered standard errors.

**Both** FAIL conditions hold. The post-print sum is indistinguishable from zero
(t = +0.59), and the mass is concentrated at `k < 0` (t = −5.90). It is not a marginal
call in either direction.

Note also that the small post-print sum that does exist has the **wrong sign**
(+0.0076, i.e. positive X → positive Y). The prereg fixes the sign in advance —
`customer pays fixed → dealer received → dealer long duration → dealer SELLS futures`,
so the hedge channel is `beta_k < 0`. A positive `beta` "is not a pass, it is a different
phenomenon". It is in any case not significant.

## The chart

![beta_k against k, two clocks](out/r0_betas.png)

`out/r0_betas.png`. Two panels, execution clock above, dissemination clock below;
day-clustered 95% bands; vertical line at `k = 0`. `k > 0` means X precedes Y, i.e. the
post-print hedge window.

The dissemination panel is the whole result in one picture: a coherent trough of negative
`beta_k` running from about `k = −20` to `k = −2`, and nothing at all to the right of
zero.

## Where the mass actually sits

Pooled, share of total `|beta_k|`:

| window | exec: sum | exec: mass share | diss: sum | diss: mass share |
|---|---|---|---|---|
| `k` −30..−18 | −0.00396 | 16.8% | −0.03588 | 24.6% |
| **`k` −17..−2** | **−0.01063** | **40.7%** | **−0.07075** | **48.0%** |
| `k` −1 | −0.00058 | 2.2% | −0.00083 | 0.5% |
| `k` 0 | −0.00081 | 3.0% | −0.00135 | 0.9% |
| `k` +1 | −0.00021 | 0.8% | −0.00181 | 1.2% |
| `k` +2..+17 | −0.00218 | 27.9% | +0.00792 | 15.3% |
| `k` +18..+30 | −0.00046 | 8.7% | +0.00151 | 9.5% |

Most negative lags on the dissemination clock: **k = −7, −11, −6, −5, −9**.

The publication lag for exactly these prints, measured first-hand from
`cache/tape_legs_signed.parquet`, is **p5 2.77 / p50 4.70 / p95 17.23 minutes** (min 1.10,
zero negative lags, 292,525/292,525 recovered). The `beta_k` trough sits exactly inside it, and 48% of the mass falls
in `k = −17..−2`. That is not a coincidence and it is not a specification error — the
addendum anticipated it in writing:

> a hedge executed shortly after the trade can land **before** dissemination, appearing at
> negative `k` on the dissemination panel. That is a real property of the opportunity, not
> a specification error.

**D2, the attenuation-invariant statistic** (centroid of the `|beta_k|` mass):
exec **−3.26** bins, diss **−6.46** bins, difference **−3.20** bins. Moving from the
execution clock to the dissemination clock shifts the mass 3.2 minutes further into the
past — the right order of magnitude for a ~5-minute median publication lag, and derived
from the betas alone, so it is immune to the attenuation discussed below.

## Per bucket — the same result five times

Dissemination clock, all flow:

| bucket | `sum(beta_k, k<=-1)` | t (day-clust) | `sum(beta_k, k>=1)` | t (day-clust) | post-print share |
|---|---|---|---|---|---|
| SFR_FF | −0.1325 | **−3.37** | −0.0085 | −0.18 | 0.061 |
| TU | −0.0508 | **−2.48** | −0.0044 | −0.15 | 0.079 |
| FV | −0.1179 | **−4.48** | +0.0356 | +1.90 | 0.232 |
| TY_UXY | −0.1538 | **−4.84** | −0.0162 | −0.79 | 0.095 |
| US | −0.1066 | **−3.59** | +0.0339 | +1.13 | 0.241 |

**Five of five decision buckets** show significant pre-print mass and **zero of five**
show significant post-print mass. There is no bucket carrying the pooled result and no
bucket dissenting from it.

## The execution clock says the mechanism is not there either

This is the more damning of the two panels, and the addendum fixed its interpretation in
advance: *"Execution clock, mass at `k > 0` — the hedge mechanism exists: the dealer
trades futures after taking the swap on."*

Pooled, execution clock: `sum(beta_k, k>=1)` = **−0.0029, t = −1.51**. Not significant.
`sum(beta_k, k<=-1)` = −0.0152, t = −1.31. Also not significant.

So it is not merely that the hedge is exhausted before the print is public: on the
execution clock, at pooled level, no post-execution futures hedge is **detectable at this
power** either. This panel uses the same X and carries the same `rho = 0.405`, so its null
is downgraded exactly as the dissemination panel's is — read it as "not seen", not "not
there". The only place the registered sign appears significantly at `k >= 1` anywhere in
the all-flow runs is **TU on the execution clock** (−0.0183, t = −2.14) — and Newey-West
puts it at −1.92, below the threshold. Day-clustered governs per the prereg, so it stands
as a lone weakly-significant cell out of twelve; it is not the basis for anything.

## Splits (block / non-block, D2C / IDB)

Full grid in `out/r0_table.csv` (60 rows: 2 clocks x 5 splits x pooled + 5 buckets).
No verdict is read off a split, and every split inherits the same attenuated X, so none of
them can establish absence either. Nothing in them points the other way.

Cells where `sum(beta_k, k>=1)` is significant with the **pre-registered (negative)** sign:

| clock | split | bucket | `sum(beta_k,k>=1)` | t |
|---|---|---|---|---|
| exec | all | TU | −0.0183 | −2.14 |
| exec | D2C | TU | −0.0190 | −2.26 |
| diss | block | US | −0.0342 | −2.59 |

Cells where it is significant with the **wrong** sign:

| clock | split | bucket | `sum(beta_k,k>=1)` | t |
|---|---|---|---|---|
| exec | IDB | US | +0.0600 | +4.86 |
| diss | IDB | US | +0.0588 | +3.66 |
| diss | nonblock | FV | +0.0593 | +3.05 |
| diss | nonblock | US | +0.0605 | +2.16 |

Three cells the registered way and four the other way, out of 48 split cells, is what
noise looks like — and at `rho = 0.405` a real but modest channel would be invisible in
these cells regardless. The pre-print mass, by contrast, is significant and negative in
essentially every non-block and D2C cell on both clocks — the same finding as the
headline, not a new one.

The block split is the one place with an interpretable structure: **block flow shows no
pre-print mass at all** (diss pooled block `S_neg` = −0.0017, t = −0.18, against
non-block −0.1245, t = −6.16). Blocks carry a statutory 15-minute publication delay, so
by the time a block prints, a 30-minute window either side is mostly outside the relevant
horizon. Consistent with the clock story; not independent evidence for it.

## Do any of the prereg's "uninformative rather than negative" conditions apply?

The prereg lists three, recorded in advance so they cannot be invoked selectively.
**None of them fired.**

| condition | status |
|---|---|
| Fewer than ~20 trading days of overlap between MBO and tape | **No.** 67 session dates for four buckets, 44 for SFR_FF. Both well above the floor. |
| A bucket with no measurable futures flow in the sample | **No.** The smallest decision bucket, US, still carries 25.7m contracts of gross aggressor volume and 2.3m trades; every bucket has substantial flow. |
| A dissemination clock not actually recoverable, forcing a legal-delay estimate | **No.** Verified first-hand: `dissem_is_real` is true for **292,525 / 292,525** execution-in-window legs (100.00%), with **0** negative lags and a minimum lag of 1.10 min. The dissemination panel tests the clock, not an estimate, and needs no such label. |

So on the prereg's **own three conditions** the result is a negative one, not an
uninformative one: the sample is long enough, every bucket has flow, and the clock is
real. The fourth path to "uninformative" was added later by `r0_prereg_addendum_1.md`,
and it is that one — the attenuation downgrade — which fires. See the next section.

## Addendum-1 D1 — is this a real null, or no power?  →  **no power**

Addendum 1 requires the attenuation of R0's median-based direction sign to be quantified
before a FAIL can be reported as a FAIL rather than as UNINFORMATIVE. Computed by
`run_d1.py`; the operationalisation was frozen in `r0_deviations.md` R10 / R10a / R10b /
R10c **before any `rho` was read**, and the join's known-answer check was run and passed
before any correlation was printed.

`dev_curve = fixed_rate − Citi minute-curve par rate at the print's execution minute`.
Reference only: it is never used to build X, and X was not changed. Read through
`MDP/IRSwaps/CITIVELO_EXCEL` and `Caching`, which the addendum states explicitly is not an
isolation breach; no `SDRUtils.dealer_direction` or `SDRUtils.stir_flow` import.

**Sample and join.** 140,992 prints (45.4% of legs, 45.8% of DV01), spot-starting,
non-MAC, twelve tenors covering all five decision buckets, inside Citi's published
01:00–22:59 ET session. **Join match rate 100.0%** at a 2-minute backward tolerance.
Known-answer check passed: per-day median `dev_curve` is −0.06 bp (p5 −0.13, p95 −0.01,
worst day −0.35 bp), and `corr(dev_curve, rate level)` = **−0.008**, so there is no
timezone or units error in the reference.

**Coverage, reported rather than assumed.** Citi publishes nothing 23:00–00:59 ET, and the
minute store has no lag tolerance of its own — it will serve a snapshot from the wrong day,
or from *after* the requested instant, which for a direction diagnostic would be circular.
Prints in that window are therefore excluded rather than silently filled: the session rule
retains **140,992 of 143,511 = 98.2%** of otherwise-eligible prints, and inside the session
the join then matches **every single one**. The 1.8% dropped are plausibly illiquid minutes
where the median is at its worst, so this restriction if anything flatters `rho`. All
twelve R10b tenors were pulled complete (97,858–97,861 minutes each, span, duplicates and
NaNs checked before use), so **no decision bucket is unmeasured** and R10c's
missing-bucket fallback was never invoked.

**The diagnostic was itself validated before any `rho` was believed.** A `dev_curve` rule
that is inverted or mis-joined would make a sound proxy look useless, and the per-day-median
gate above cannot detect that on its own. Three further checks, with results:

- **Units detected, not assumed.** Median `ref_rate / fixed_rate` = **100.013**: the
  reference is percent, the tape decimal.
- **Orientation, hand-checked.** A rate above the curve mid must give a positive
  `dev_curve`. Eight prints at a fixed seed had their raw numbers printed and the sign read
  off by eye: **8 / 8** correct — including a 10y at 6.56% against a 4.19% mid
  (`dev_curve` = +237.12 bp) and a 3y where the curve says −9.06 bp while the median says
  +35.50 bp, the disagreement this diagnostic exists to measure, in a single row.
  Vectorised over the whole sample the rule holds on **140,992 / 140,992 = 100.0000%**.
- **The two rules must agree on obviously off-market prints, and agreement must _rise_ with
  the size of the deviation** — an inverted join makes it fall. It rises monotonically:
  53 → 91% across deciles of `|dev_median|`, 50 → 92% across deciles of `|dev_curve|`, and
  **90.3% / 93.8% / 97.9% / 99.5%** on prints at least 5 / 10 / 20 / 50 bp off-market by
  *both* rules. Where the rules disagree it is because the median is uninformative on small
  deviations, not because the reference is wrong.

Full D1 record, including the per-bucket damping ratios and the hand-check table, is in
`ATTENUATION.md`; machine-readable output in `out/attenuation.csv` and `out/r0_d1_rho.csv`;
console log in `out/r0_d1.log`.

| bucket | `rho` print | `rho` 1-minute | `rho` daily | sign agreement | n prints |
|---|---|---|---|---|---|
| SFR_FF | 0.397 | 0.345 | 0.023 | 64.1% | 13,939 |
| TU | 0.456 | 0.379 | 0.173 | 68.6% | 17,449 |
| FV | 0.489 | 0.414 | 0.208 | 70.0% | 41,604 |
| TY_UXY | 0.553 | 0.490 | 0.418 | 68.6% | 42,173 |
| US | 0.473 | 0.317 | 0.241 | 67.3% | 25,827 |
| **DV01-weighted pooled** | **0.499** | **0.405** | **0.274** | **68.3%** | 140,992 |

**The downgrade rule fires.** The pooled 1-minute `rho` is **0.405**, below the
pre-registered 0.50, and **all five** decision buckets are below it individually. (Sign
agreement, 68.3%, clears its 60% threshold; the rule is an OR, so `rho` alone triggers it.)
Because **all five buckets sit below 0.50 individually**, the frozen "DV01-weighted pooled
1-minute" convention of R10 is immaterial to the call — any pooling rule over the decision
buckets returns the same answer.

> If the verdict is FAIL **and** (`rho < 0.5` in the deciding buckets **or**
> sign-agreement < 60%), the verdict is reported as **UNINFORMATIVE** under the existing
> "uninformative rather than negative" clause of `r0_prereg.md`, not as FAIL.

**So two labels must be stated, and both are:**

- **Under `r0_prereg.md`'s decision rule, verbatim: FAIL.**
- **As reported, after the addendum-1 downgrade: UNINFORMATIVE.**

This is emphatically **not** "the premise survives". It is "this test could not have seen
the effect at the size it would plausibly have". Concretely:

- **Implied MDE = 1.96 × 0.01280 / 0.405 = 0.0620.** The smallest true post-print effect
  R0 could have detected is `|sum beta_k| ≈ 0.062` standardised units. Per bucket, using
  each bucket's own day-clustered SE and its own `rho`: TY_UXY **0.082**, FV **0.089**,
  TU **0.154**, US **0.185**, SFR_FF **0.263**. Set against each bucket's own `|S_neg|`,
  **three of the five — SFR_FF (0.263 vs 0.133), TU (0.154 vs 0.051) and US (0.185 vs
  0.107) — could not have detected a post-print effect even as large as the pre-print mass
  they did detect on the other side of zero.** FV (0.089 vs 0.118) and TY_UXY (0.082 vs
  0.154) could have — and in those two the measured post-print sums are +0.0356
  (t = +1.90, the *wrong* sign) and −0.0162 (t = −0.79, the registered sign), both
  insignificant and both comfortably inside their own MDEs.
- Correcting the measurement for attenuation, the 95% interval on the **true** post-print
  sum is **(−0.043, +0.081)**. A true hedge channel of −0.043 — in the pre-registered
  direction, and two-thirds the size of the pre-print mass actually observed — is **not
  excluded** by this test.
- For scale, the pre-print sum's own detectability threshold is
  `1.96 x 0.01823 / 0.405` = **0.088**, and `|S_neg|` = 0.107 clears it.

> **WITHDRAWN on review.** The sentence that stood here — "R0 had the power to see the
> `k < 0` mass; it did not have the power to rule out a moderate `k > 0` one" — is
> contradicted by this document's own caveat 1. If the `k < 0` mass is the mechanical
> stale-median artifact, it is produced by a channel in which X is by construction a
> lagged function of price, i.e. effective correlation ≈ 1 — **not** by the attenuated
> true-direction channel. It therefore demonstrates nothing about power at `k > 0`, and
> the contrast between the two is artifact-versus-signal rather than one attenuation
> applied twice. Caveat 1 is the correct statement; this was not.

### `rho` is a LOWER BOUND on the attenuation factor, and that cuts toward FAIL

This is the most consequential correction to this document and it is against its own
headline. Addendum 1 and `ATTENUATION.md:27` both assert that `rho` **is** the attenuation
factor. That identity holds only if the reference `X_curve` is error-free. It is not. With
`X_med = a·X* + u` and `X_cur = c·X* + v`,

```
rho = corr(X_med, X_cur) = corr(X_med, X*) · corr(X*, X_cur)  <=  corr(X_med, X*)
```

and `corr(X_med, X*)` is the actual attenuation factor. So **the true attenuation is no
worse than 0.405 and is probably better**, which means:

- **`MDE = 0.0620` is an upper bound on blindness, not a measurement.**
- The `(−0.043, +0.081)` interval on the true post-print sum is **wider than the truth**.
- Every statement in this document of the form "a hedge channel of size X is not excluded"
  is an upper bound presented as a measurement.

**The earned label may well be FAIL.** `ATTENUATION.md:264-270` states this correctly and
says it "cuts *toward* the FAIL standing"; §27 of the same file and this document
contradicted it. That is now recorded here, where the label is set.

**The label nevertheless stays UNINFORMATIVE, and that is deliberate.** The
pre-registered rule was mechanical — `rho < 0.5` on the pre-registered statistic — and
`rho` measured 0.405. Re-interpreting a rule after seeing which way it fell is precisely
the manoeuvre this whole design exists to forbid, and it does not become acceptable
because the re-interpretation would produce the *stronger* conclusion. The rule fired; the
label is UNINFORMATIVE; the bound is recorded so nobody mistakes the downgrade for
evidence that a hedge channel exists.

**Stated before R0b lands, so it cannot be claimed afterwards:** because `rho` is a lower
bound, R0b — which makes `rho ≈ 1` by construction — is **expected to return FAIL rather
than PASS**. If it returns PASS, something other than X attenuation is going on and this
prediction was wrong.

Two measurements would resolve the magnitude of the bound directly: a dense-grid `rho`,
and a within-`(tenor, minute)`-cell variance decomposition separating reference error from
median damping. Both were attempted during review and lost when a concurrent process —
**this session's own disk cleanup, moving caches off a drive that had reached 1 MB free** —
removed `cache/` and `cache_d1_ref/` mid-run. They are folded into R0b.

**The addendum's specific fear is confirmed, not merely possible.** It predicted that if
the median were high-passing the flow rather than just adding noise, `rho` would *collapse
under aggregation*. It does: pooled `rho` falls from **0.499 at print level to 0.405 at
one minute to 0.274 daily**, and in SFR_FF it collapses to **0.023**. The same signature
appears in the raw deviations — `dev_curve` has an IQR of 4.11 bp against `dev_median`'s
2.10 bp, so the rolling median absorbs roughly half the deviation amplitude by
construction.

**What survives the downgrade.** Three findings do not depend on `rho`, because
attenuation shrinks magnitudes without moving mass across lags:

1. The **location** of the mass — a trough at `k = −5..−11`, the modal lags sitting inside
   the measured 2.77–17.23 minute publication window. **Corrected on review:** an earlier
   draft said the trough sits "exactly inside" that window and called the fit "not a
   coincidence". That is false as written and contradicted by this document's own table:
   individually significant negative diss lags run out to **`k = −26` (t = −3.36)**, and
   24.6% of the diss mass sits at `k = −30..−18`, outside p95. The modal location is
   consistent with the lag; the tail is not, and the tail was not disclosed.
2. **D2**, the `|beta_k|` centroid shift of −3.20 bins between the clocks. **Corrected on
   review: this is NOT "attenuation-invariant by construction".** Under the global null,
   `E[Σ|β̂_k|] = Σ se_k·√(2/π)` — measured at **0.0928 of the 0.1532 observed on diss
   (61%)** and **0.0173 of 0.0267 on exec (65%)**. `|β̂|` is a biased estimator of `|β|`,
   the bias sits roughly uniformly across `k` whose centroid is zero, so **both centroids
   are shrunk toward zero, and by different amounts** because the two panels carry
   different noise shares. The −3.20 bin shift is therefore biased by an unquantified,
   panel-dependent factor and its agreement with a ~5-minute lag is **not** the clean
   confirmation claimed. The same defect voids the mass-share table above: its exec column
   in particular is largely a decomposition of noise, with only 8 of 61 exec lags
   individually significant. No de-noised centroid is published, because
   `E|β̂| ≠ |β| + se√(2/π)` when `β ≠ 0`; the direction of the bias is solid, the
   corrected number is not.
3. ~~The contrast between significant `k < 0` and insignificant `k > 0`.~~ **Withdrawn** —
   see the boxed correction above.

**And the per-lag inference is unreliable in both directions.** With `G = 67` clusters
against 66 lag regressors plus fixed effects and five `Y` lags, the cluster meat matrix has
rank at most 67. Per-lag standard errors — and therefore the chart's per-lag bands, the
"coherent trough" language, and any individual-lag claim below — cannot be relied on. This
cuts against the report's own narrative as much as against any counter-example to it. **The
one-dimensional sums that decide the verdict are unaffected**, because they are single
linear combinations.

**The exec panel's strongest registered-sign cells, which the narrative omitted.** The two
largest-magnitude significant exec lags are `k = +3` (β = −0.00112, **t = −5.22**) and
`k = +7` (β = −0.00110, **t = −3.93**) — both the **pre-registered negative sign**, both at
hedge-plausible latencies. Reported here because their absence was an omission. Reported
*with* their counterweight, which is required: `k = +12` is **+0.00089 at t = +5.80**, the
wrong sign and larger; with 61 lags × 2 clocks roughly 6 cells at `|t| > 1.96` are expected
by chance and 8 are observed on exec; and the rank deficiency above makes every one of
these per-lag statistics unreliable. They do not amount to a finding. They should still
have been in the document.

What does **not** survive is the strength of the negative conclusion about `k > 0`.

## Caveats

Reported as caveats, per the discipline. None of them was allowed to change the
specification, and the run was not repeated under a variant.

**1. The significant `k < 0` mass has exactly the sign a stale trailing median produces
mechanically.** This is the sharpest caveat on the result and it is worth stating
precisely. X's direction sign is `fixed_rate − trailing same-key median`. Suppose futures
are bought aggressively at time `t` (`Y_t > 0`). Futures price rises, yields fall, and
swap prints over the next few minutes sit **below** a median that still contains the older,
higher rates — so they are classified customer-received, `X < 0`. A pure price-impact
chain with no information content therefore produces `Y_t > 0` followed by `X_{t+j} < 0`,
which is a **negative `beta` at `k < 0`** — precisely what is measured, on both clocks.

The addendum is right that *attenuation* cannot manufacture pre-print mass, because
damping shrinks magnitudes without moving mass across lags. But the median's *staleness*
can, and its sign prediction matches the measurement. So the `k < 0` finding must **not**
be read as evidence of leakage or pre-hedging without further work. D1's sign-agreement
rate is the quantifier of that channel, and no second specification was run to test it —
the addendum licenses `rho` and sign agreement, not another regression.

**Crucially, the FAIL does not rest on the `k < 0` mass.** It rests on `sum(beta_k, k>=1)`
being indistinguishable from zero, and no staleness artifact manufactures a zero.

**But attenuation does manufacture a zero, and that is the whole point of D1.** An earlier
draft of this section over-claimed by saying the two-clock design meant attenuation could
not be blamed for a null on both panels. It cannot: **the same X feeds both panels**, so
attenuation shrinks every `beta` on both equally. What the two-clock design rules out is a
**timing** alternative — it says nothing about power. Nor does the `k < 0` significance
demonstrate power, because on this section's own reading that mass may be generated
entirely by the staleness channel, with no correlation between X and true customer
direction at all. D1 is therefore load-bearing rather than a formality, and the verdict is
conditional in exactly that one respect. It duly fired.

**2. Combo instruments are excluded from Y — and this is NOT classical measurement error.**
Discarded share of traded futures volume: **sr3 24.66%, zq 20.67%** (both in SFR_FF),
against 10–15% for the Treasury roots.

An earlier draft called this "attenuating, not sign-flipping". That is the right
description of classical measurement error and the wrong description of what this is:
**selective removal of a component of Y**. Front-end hedging is substantially done in
**packs and bundles**, which are exactly the combo instruments discarded — so for SFR_FF
this is plausibly not noise around the hedge, it is the removal of *where the hedge lives*.
Treasury futures hedging is mostly outright, so TU/FV/TY_UXY/US are not exposed the same
way.

**Scope the verdict accordingly: decisive for the belly and long end, provisional for
SFR/ZQ** pending leg-level combo reconstruction. That matters disproportionately here,
because the meeting-dated front-end is the part of the wider programme that is furthest
along. Noted as a scoped follow-up; not run.

**2b. Y is aggressor-signed, and a passively worked hedge enters with the OPPOSITE sign.**
Every trade has one aggressor and one passive side. A dealer who is long duration and
sells futures by resting offers is *lifted by a buyer* — so that hedge contributes
**positive** Y where the registered prediction is negative. A hedge executed as a mix of
aggressive and passive therefore partially self-cancels in Y, and the limit of that
cancellation is precisely a null.

This is a third mechanism, alongside attenuation and the combo exclusion, that can produce
the observed zero, and unlike attenuation it is **not** covered by D1. It also offers a
reading of the split table that the noise interpretation does not: the four significant
*wrong-sign* cells include IDB US on **both** clocks at t = +4.86 and +3.66 — the largest
`t` statistics anywhere in the table, same bucket, same sign, both clocks. Three cells one
way and four the other is what noise looks like on a count; that particular pattern is not
obviously noise. It is flagged, not claimed: MBO carries no counterparty, so no version of
this test can separate passive dealer hedging from aggressive customer buying. It is a
bound on what any aggressor-signed test can conclude.

**3. `side = 'N'` volume is unsigned, not dropped:** 9.54% (sr3) and 9.87% (zq) of
outright volume, 0.55–1.89% for Treasuries. Attenuating.

**4. 6.5–8.4% of X's DV01 does not land on Y's grid** (exec 92.1% on grid, diss 91.6%),
and for **SFR_FF only 69.8% / 68.9%** does. Two causes: X spans 2026-05-01..08-07 while Y
spans 05-07..08-06, and SFR_FF's Y grid is 44 sessions against X's 68 days. Swap flow that
arrives when the bucket's futures book is outside its session cannot be tested.

**5. SFR_FF carries 44 sessions against 67 for the others**, because the `sr3` MBO extract
is 53 UTC days, not the 79 the brief assumed. Above the prereg's ~20-day floor, but the
SFR_FF panel is two-thirds the length of the others.

**6. Block notionals are capped by rule**, so block-bucket DV01 is understated by
construction (1.91% of in-window prints flagged `is_notional_capped`). No filter applied;
`is_block` is carried as a split.

**7. Y is in contracts, unweighted.** TY_UXY adds ZN and TN contracts and SFR_FF adds SR3
and ZQ contracts without DV01 weighting, as specified. The rolling-standard-deviation
standardisation absorbs the scale but not the relative weighting inside a bucket.

**8. Two marginal Newey-West / day-clustered disagreements**, both in the all-flow runs:
`exec TU k>=1` (cluster −2.14, NW −1.92) and `exec FV k<=-1` (cluster −1.74, NW −1.97).
Both straddle the threshold. Day-clustered governs, per the prereg. Neither affects the
verdict.

**9. D1's own sample is 45.4% of the tape legs, not all of them.** It is restricted to
spot-starting, non-MAC prints in twelve tenors inside Citi's 01:00–22:59 ET session
(`r0_deviations.md` R10/R10a/R10b/R10c, all declared before any `rho` was read). Per-bucket
retention runs 31.6% (SFR_FF) to 53.8% (TY_UXY) of prints. `rho` is measured on that
sample and assumed to characterise the rest. Forward-starting and MAC prints, which are
excluded, are if anything *harder* for a tape-internal median to sign correctly — the mid
key is thinner — so the true pooled `rho` is more likely below 0.405 than above it, which
would strengthen the downgrade rather than reverse it.

**10. The `rho < 0.5` threshold was met by a margin, not decisively.** Pooled 1-minute
`rho` is 0.405 against a threshold of 0.50, and the highest single bucket, TY_UXY, reaches
0.490 — just under. Had the deciding level been the *print*-level `rho` (0.499) rather than
the 1-minute one, the call would have been a coin toss. Which level governs was fixed in
`r0_deviations.md` R10 before any `rho` existed, precisely so this could not be chosen
afterwards; it is recorded here because the margin is narrow enough to matter.

**11. A cluster-label defect was caught by the runner's own known-answer gate, fixed, and
the run repeated.** Disclosed in full because it means the script executed twice. The
first execution derived the CME session date as "the date of the session's last minute in
Chicago", which mislabels the four evening-only 2026-08-07 sessions as 2026-08-06 and
merges them into the previous day's cluster (238 of 402,946 observations; 66 clusters
instead of 67). The gate compared the reconstruction against `data/y_sessions.csv`,
reported the mismatch, and — a defect in itself — continued. The fix takes the session
date from `y_sessions.csv`, which is authoritative, and makes the gate hard-fail. The
headline moved by nothing: `S_neg` t **−5.8963 → −5.8963**, `S_pos` t **+0.5947 →
+0.5947**, verdict FAIL both times. The pre-fix log is kept at
`out/_prefix_clusterlabel_run.log`.

## How the estimator itself was validated, before it saw the real data

A lead-lag estimator that is silently transposed reports a clean null and hides exactly
what it was built to find. `run_r0.py` refuses to touch the real inputs until all of the
following pass, and prints them at the top of every run:

| check | result |
|---|---|
| Known effect injected at `k = +3` with the pre-registered negative sign | recovered `beta(+3)` = −0.2106 against **an a-priori prediction of −0.2067** (the prereg standardises both series, so the estimand is `true_b * scale_X / scale_Y`, not `true_b`); rel err +1.9%, t = −68.6; max abs beta at every other lag 0.0092; `beta(−3)` = −0.0044 |
| Mirror: effect injected at `k = −3` | recovered at −3 (−0.2021, t = −60.8); `beta(+3)` = +0.0003, t = +0.11. **Lag orientation is not transposed** |
| Null DGP | `sum(k>=1)` t = −0.26, `sum(k<=-1)` t = +0.34. No manufactured significance |
| Two-way FE absorption vs explicit dummies | max abs diff **4.2e-15** |
| Day-clustered SE vs `statsmodels` `cov_type='cluster'` | max rel diff **3.6e-15** |
| Newey-West vs `statsmodels` HAC | max rel diff 7.5e-04 (small-sample factor differs by design) |
| **Plumbing check on the REAL grid and REAL X** — Y replaced by `−0.25 * Xstd_(t−7) + noise`, same sessions, same sparse-X reindex, same keep mask | `beta(+7)` = −0.2304 against a prediction of −0.2382, t = −41.9; `beta(−7)` = −0.0001; max abs beta at every other lag 0.0025 |
| Session reconstruction vs `data/y_sessions.csv` | session counts **and** session dates match exactly (hard gate) |

The estimator can see a real effect of this size at this lag, in this data, on this code
path. It did not see one at `k > 0`.

**The headline number was then recomputed by a second implementation**
(`scratch_verify_headline.py`): same design matrix, but estimated with `statsmodels`
`OLS(cov_type='cluster')` and the sums formed by `t_test` rather than by the hand-rolled
`c'Vc`.

| | run_r0.py | statsmodels |
|---|---|---|
| `sum(beta_k, k<=-1)` | −0.10746 | −0.10746 |
| `sum(beta_k, k>=+1)` | +0.00761 | +0.00761 |
| difference | +0.11508 | +0.11508 |
| SE on `k<=-1` | 0.01823 | 0.01820 |
| t on `k<=-1` | −5.8963 | −5.9061 |

Point estimates are identical. The standard errors differ by exactly one known factor:
`run_r0.py` counts the **1,324 absorbed fixed effects** in the small-sample correction,
`(n−1)/(n−k−k_fe)`, while `statsmodels` cannot see them and uses `(n−1)/(n−k)`. The
predicted ratio is **1.001647**, which maps 0.018201 → 0.018231 (reported 0.01823) and
−5.9061 → −5.8964 (reported −5.8963). **R0's standard errors are the more conservative of
the two.**

## Inputs, verified first-hand before use

Both upstream deliverables were loaded and checked against their reports before the
regression was written. Everything material reconciled exactly:

- **X** — 281,197 rows; exec 145,143 cells / 58,220 minutes / 292,525 prints; diss 136,054
  / 52,678 / 292,547; 68 UTC days 2026-05-01..08-07; per-bucket prints, gross DV01 and
  minute counts match the report to the digit; 0 rows with `|signed| > gross`, 0 negative
  or zero gross, 0 nulls, 0 duplicate grain keys.
- **Y** — 512,019 rows; per-bucket bins, sessions, gross/signed volume and trade counts
  match `y_coverage.csv` and the report exactly; 0 duplicate `(bucket, minute)`, 0 rows
  with `|signed| > gross`, 0 nulls; gap-derived session counts reproduce
  `y_sessions.csv` (67 / 44) exactly.

One immaterial discrepancy: the X workstream's `r0_deviations.md` says "292,528 of
292,528 in-window prints" while its report and the parquet say 292,525 (exec) and 292,547
(diss). A wording slip in the prose, not a data defect — the file matches the report.

## Provenance note — concurrent activity in this worktree

Recorded because a reader must know which files this agent produced and which it did not.

- **This agent ran no git write command.** A commit nonetheless exists on `r0-leadlag`,
  `2a66b957` "r0: FAIL — the hedge is already done by the time the print is public",
  authored 16:40:14 under the repository's own identity, containing this workstream's files
  in their state at that moment. It was not made by this agent, and nothing was done to
  undo it — reverting someone else's commit would be a second unrequested git write.
- **`run_d1.py` was edited by a concurrent process at ~16:47 and re-run**, after this
  agent's own D1 run at ~16:43. That overwrote `out/r0_d1.log` and `out/r0_d1_rho.csv` and
  added `out/attenuation.csv`. The edit added diagnostics only; it did not touch the `rho`
  computation, and **every deciding number is identical** to this agent's run
  (per-bucket 1-minute `rho` 0.345 / 0.379 / 0.414 / 0.490 / 0.317, pooled 0.405, sign
  agreement 68.3%, MDE 0.0620, downgrade True). The numbers reported above come from this
  agent's own console output and are corroborated, not contradicted, by that re-run.
- The added diagnostics are worth keeping, because they close a gap this agent's D1 left
  open — that the per-day-median gate alone cannot detect an *inverted* join:
  orientation (`rate > mid` ⟹ `dev_curve > 0`) holds on **140,992 / 140,992 = 100.0000%**
  of the sample, and sign agreement **rises monotonically** with the size of the deviation
  (53% in the smallest `|dev_median|` decile to 91% in the largest, and **99.5%** on the
  6,457 prints more than 50 bp off-market by both rules). An inverted or mis-scaled join
  makes that fall, not rise. It also reports `corr(dev_median, dev_curve) = +0.999` on the
  *continuous* deviations against an IQR ratio of **0.511** — the two rules agree almost
  perfectly on the large off-market prints and disagree on the bulk near zero, which is
  precisely why the *sign*, which is what X actually uses, only agrees 68.3% of the time.
- **The regression outputs were not touched by any of this.** `run_r0.py`,
  `out/r0_betas.png`, `out/r0_betas.csv`, `out/r0_table.csv` and `out/r0_verdict.txt` all
  carry their 15:49–15:50 timestamps from this agent's single run.

---

*The estimator, the selftest, and all outputs are in `r0_leadlag/`. `r0_prereg.md` was not
edited. Everything the data forced is in `r0_deviations.md`, including the runner's own
choices, which were frozen there before `run_r0.py` was written.*
