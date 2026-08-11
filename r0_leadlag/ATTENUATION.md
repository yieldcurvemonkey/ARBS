# D1 — attenuation of R0's median-based direction sign

Addendum-1 diagnostic. Computed by `run_d1.py`; machine-readable output in
`out/attenuation.csv`, full log in `out/r0_d1.log`, per-bucket rho in `out/r0_d1_rho.csv`.
The operationalisation was frozen in `r0_deviations.md` R10 / R10a / R10b / R10c **before
any `rho` was read**, and the join's known-answer gate was run and passed before any
correlation was printed (`out/_d1_joincheck.log`, which prints no rho by design).

**Headline: pooled 1-minute `rho` = 0.405, per-print sign agreement = 68.3%. The
addendum's downgrade rule fires on the `rho` limb. R0's FAIL is reported as
UNINFORMATIVE.**

R0 was not re-run, the specification was not changed, and X was not rebuilt.

---

## The two rules

| | definition | role |
|---|---|---|
| `dev_median` | `fixed_rate − trailing same-key rolling median` | **R0's actual input.** Taken from `cache/tape_legs_signed.parquet`, the per-print frame `build_x_tape.py` itself wrote while building X, so the quantity measured here is the quantity R0 used — not a reimplementation of it. |
| `dev_curve` | `fixed_rate − Citi minute-curve par rate of the same tenor at the print's execution minute` | **Reference only.** Never used to build X. |

`X_median = dv01 × sign(dev_median)` and `X_curve = dv01 × sign(dev_curve)`, aggregated to
bucket-minute as `sum(...)` and standardised with R0's own `rolling_scale` (R4), imported
from `run_r0.py` rather than restated. With both series standardised,
`beta_hat = rho × beta_true`, so `rho` **is** the attenuation factor.

Reference read through `MDP/IRSwaps/CITIVELO_EXCEL` (`IRSwapsMDP(source="citivelo_excel_rl")`
— the RL token; a `-QL` spelling never consults the minute store) and `Caching`, curve
`USD-SOFR-1D`, `freq="1min"`. No `SDRUtils.dealer_direction` or `SDRUtils.stir_flow`
import. The addendum states explicitly that this is not an isolation breach: it sizes the
measurement error in R0's own input, which is a property of R0.

Execution minute, not dissemination: the X workstream computed its mid in execution order
for both clocks, so the sign is a property of the print at execution.

## Sample and coverage

Twelve tenors (`1m 2m 3m 6m 1y 2y 3y 5y 7y 10y 20y 30y`), each a complete 97,858–97,861
one-minute series spanning 2026-04-30 23:00 .. 2026-08-07 22:00 UTC, verified row-count,
span, duplicate-free and NaN-free before use (`scratch_d1_refcheck.py`). All twelve of the
R10b set are present, so **no decision bucket is unmeasured** and R10c's
missing-bucket fallback did not have to be invoked.

| coverage stage | retained |
|---|---|
| spot-start, non-MAC, twelve tenors, `dev_median` present, in window | 143,511 prints |
| **inside Citi's published USD session, 01:00–22:59 ET (R10a)** | **140,992 = 98.2%** |
| **join to the reference, `merge_asof` backward, 2-minute tolerance** | **140,992 = 100.0%** |

The 1.8% dropped by the session rule are prints executed 23:00–00:59 ET, where Citi
publishes nothing and the minute store — which has **no lag tolerance** and will serve a
snapshot from the wrong day or from *after* the requested instant — has no real value to
serve. Those minutes are excluded rather than silently filled; a forward-looking reference
would make `dev_curve` circular for a direction diagnostic. Nothing else was dropped for
being hard: within the session the join matches every single print.

| bucket | prints in D1 | share of that bucket's prints | share of its DV01 | reference minutes | days |
|---|---|---|---|---|---|
| SFR_FF | 13,939 | 31.6% | 24.1% | 10,662 | 68 |
| TU | 17,449 | 42.6% | 42.9% | 11,335 | 68 |
| FV | 41,604 | 44.8% | 44.3% | 22,055 | 68 |
| TY_UXY | 42,173 | 53.8% | 53.0% | 21,223 | 68 |
| US | 25,827 | 47.3% | 46.7% | 13,641 | 68 |
| **total** | **140,992** | **45.4% of legs** | **45.8% of DV01** | | 68 |

## Validation — run before any `rho` was believed

A diagnostic that is itself inverted makes a good proxy look useless, or the reverse. Four
checks, all stated with their results.

**1. Units and timezone.** Median ratio `ref_rate / fixed_rate` = **100.013**, i.e. the
reference is in percent and the tape in decimal — detected from the data, not assumed.

**2. The reference must sit on top of the tape, not drift against it.** Per-day median
`dev_curve` over 68 days: p5 **−0.13 bp**, p50 **−0.06 bp**, p95 **−0.01 bp**, worst day
**−0.35 bp**. And `corr(dev_curve, level of the reference rate)` = **−0.008**. A timezone
or units error would make `dev_curve` track the day's rate drift and drive that correlation
toward ±1. It does not.

**3. Hand-check: a rate above the curve mid must give a positive `dev_curve`.** Eight
prints drawn at a fixed seed, raw numbers printed, sign read off by eye:

| tenor | exec minute (UTC) | fixed_rate % | curve mid % | dev_curve bp | dev_median bp | expected | got |
|---|---|---|---|---|---|---|---|
| 5y | 2026-07-08 01:54 | 3.99092 | 3.99102 | −0.01 | −0.10 | − | − |
| 10y | 2026-06-01 14:13 | 4.02000 | 4.10409 | −8.41 | −8.31 | − | − |
| 10y | 2026-05-08 11:10 | 3.95943 | 3.95788 | +0.16 | +0.92 | + | + |
| 30y | 2026-06-09 20:23 | 4.18674 | 4.27317 | −8.64 | −4.67 | − | − |
| 20y | 2026-05-18 11:51 | 4.40400 | 4.41152 | −0.75 | −2.11 | − | − |
| 1y | 2026-06-04 12:24 | 3.84050 | 3.84519 | −0.47 | −0.65 | − | − |
| 10y | 2026-05-18 18:58 | 6.56000 | 4.18884 | **+237.12** | +236.31 | + | + |
| 3y | 2026-05-29 14:35 | 3.76955 | 3.86018 | −9.06 | **+35.50** | − | − |

**8 / 8** correct by eye; vectorised over the whole sample, **140,992 / 140,992 =
100.0000%**. The rule is oriented the way the formula says.

Two rows are worth noticing on their own. The 10y at 6.56% is 237 bp off any plausible
mid — both rules flag it identically, as they must. The 3y row is the interesting failure
mode: the curve says the print is 9 bp **through** the mid while the trailing median says
it is 35 bp **above** it. The two rules disagree on the sign of a 35 bp print. That is the
attenuation this diagnostic exists to measure, seen in a single row.

**4. The two rules must agree on obviously off-market prints — and agreement must RISE
with the size of the deviation.** This is the check an inverted or mis-joined reference
fails, and the per-day-median gate above cannot catch it.

| agreement by decile of | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
|---|---|---|---|---|---|---|---|---|---|---|
| `abs(dev_median)` | 53% | 57% | 59% | 61% | 63% | 69% | 72% | 76% | 82% | **91%** |
| `abs(dev_curve)` | 50% | 52% | 54% | 56% | 61% | 72% | 83% | 82% | 81% | **92%** |

| both deviations at least | agreement | n |
|---|---|---|
| 5 bp | 90.3% | 36,034 |
| 10 bp | 93.8% | 26,238 |
| 20 bp | 97.9% | 16,292 |
| 50 bp | **99.5%** | 6,457 |

Monotone in both directions, and 99.5% on prints that are off-market by either rule. The
reference is sound; where the two rules disagree it is because the *median* is uninformative
on small deviations, not because the join is wrong.

## The measured attenuation

| bucket | `rho` print | **`rho` 1-minute** | `rho` 1-min, unstandardised | `rho` daily | sign agreement | SE(`sum beta_k, k>=1`) | **MDE** |
|---|---|---|---|---|---|---|---|
| SFR_FF | 0.397 | **0.345** | 0.359 | 0.023 | 64.1% | 0.04639 | 0.263 |
| TU | 0.456 | **0.379** | 0.376 | 0.173 | 68.6% | 0.02973 | 0.154 |
| FV | 0.489 | **0.414** | 0.386 | 0.208 | 69.9% | 0.01880 | 0.089 |
| TY_UXY | 0.553 | **0.490** | 0.489 | 0.418 | 68.6% | 0.02041 | 0.082 |
| US | 0.473 | **0.317** | 0.384 | 0.241 | 67.3% | 0.02998 | 0.185 |
| **pooled, DV01-weighted** | **0.499** | **0.405** | 0.416 | **0.274** | **68.3%** | **0.01280** | **0.062** |

Sign agreement is over prints where both rules are non-zero (n = 139,168). Per-bucket SEs
are that bucket's own day-clustered SE on the dissemination clock, all-flow, read from
`out/r0_table.csv`; its POOLED row reproduces the 0.01280 fixed by the run.

`rho` at the unstandardised minute level is reported so the deciding number does not rest
on R4's rolling-standardisation choice: 0.416 against 0.405, same call.

### `rho` collapses under aggregation

**print 0.499 → 1-minute 0.405 → daily 0.274.** The addendum named this in advance as the
signature that distinguishes the worse failure from the milder one:

> if `rho` collapses under aggregation, that confirms the median is high-passing the flow
> rather than merely adding noise

It collapses, monotonically, in every bucket. In SFR_FF the daily `rho` is **0.023** —
at one-day horizon the median-based sign carries essentially no information about the
curve-based one. A persistently one-directional stretch of flow pulls the rolling median
toward the flow and drives the residual back toward zero by construction; that is exactly
what a falling `rho` with aggregation looks like, and daily is the horizon a *street
positioning* indicator would use.

### Damping, pre-standardisation

| bucket | `sd(dev_median)/sd(dev_curve)` | IQR ratio, same | `sd(X_med)/sd(X_cur)` print | `sd(X_med)/sd(X_cur)` bucket-minute |
|---|---|---|---|---|
| SFR_FF | 0.998 | 0.981 | 1.027 | 0.685 |
| TU | 1.000 | 0.520 | 1.009 | 0.708 |
| FV | 0.998 | 0.600 | 1.006 | 0.637 |
| TY_UXY | 1.000 | 0.388 | 0.999 | 0.709 |
| US | 0.982 | 0.424 | 0.996 | 0.685 |
| **pooled** | **1.000** | **0.511** | **1.000** | 0.64 – 0.71 |

Three of these are near 1.0 and one is near 0.5, and the reason matters.

- `sd(X_med)/sd(X_cur)` at **print** level is 1.000 *by construction*: both are `±dv01`,
  so only the sign differs and the standard deviations are identical whatever the signs
  are. It is reported because the task names it, not because it can be informative.
- `sd(dev_median)/sd(dev_curve)` is also 1.000 — but for a different and more interesting
  reason. The deviation distribution is enormously fat-tailed (one print in the hand-check
  is 237 bp off), so a Pearson standard deviation, and equally the continuous
  `corr(dev_median, dev_curve) = +0.999`, are set almost entirely by a handful of grossly
  off-market prints on which both rules trivially agree.
- The **IQR ratio, 0.511**, is the same comparison taken over the *body* of the
  distribution: `dev_curve` has an IQR of 4.11 bp against `dev_median`'s 2.10 bp. The
  rolling median absorbs about half the deviation amplitude where the mass of prints
  actually is.
- `sd(X_med)/sd(X_cur)` at **bucket-minute**, 0.64–0.71, is the damping that reaches the
  regression: once signs are summed across the prints in a minute, the median rule's
  disagreements cancel flow that the curve rule keeps.

The reconciliation is the whole point of D1. `corr = +0.999` on raw deviations and
`rho = 0.405` on the signed series are both true and not in tension: X throws away
magnitude and keeps only the **sign**, and the sign is decided in the body of the
distribution, where the two rules agree 53–61% of the time.

## Minimum detectable effect

```
MDE = 1.96 × SE(sum beta_k, k>=1) / rho = 1.96 × 0.01280 / 0.405 = 0.0620
```

R0 rejects at `|beta_hat| > 1.96 × SE`, and `beta_hat = rho × beta_true`, so the smallest
**true** post-print effect this test could have detected is `|sum beta_k| ≈ 0.062`
standardised units — units of a standard deviation of Y per standard deviation of X.

The measured post-print sum is **+0.0076**, an eighth of that. Inverting the interval,
the attenuation-corrected 95% interval on the **true** post-print sum is

```
(+0.00761 ± 1.96 × 0.01280) / 0.405  =  (−0.043, +0.081)
```

A true hedge channel of **−0.043** — in the pre-registered direction, and two-thirds the
size of the pre-print mass that R0 *did* detect — is not excluded.

For contrast, the pre-print mass had a detectability threshold of
`1.96 × 0.01823 / 0.405 = 0.088`, and `|S_neg| = 0.107` clears it. **R0 had the power to
see the `k < 0` mass. It did not have the power to rule out a moderate `k > 0` one.**

## Applying the downgrade rule

`r0_prereg_addendum_1.md`, committed at `cd894ab8` before any beta was estimated:

> If the verdict is FAIL **and** (`rho < 0.5` in the deciding buckets **or**
> sign-agreement < 60%), the verdict is reported as **UNINFORMATIVE** under the existing
> "uninformative rather than negative" clause of `r0_prereg.md`, not as FAIL.

| limb | measured | threshold | fires |
|---|---|---|---|
| verdict is FAIL | FAIL | — | yes |
| `rho < 0.5` in the deciding buckets | pooled 1-minute **0.405**; **5 of 5** decision buckets below 0.50 individually | 0.50 | **yes** |
| sign agreement < 60% | **68.3%** | 60% | no |

The rule is an **or** over the two diagnostics, so the `rho` limb alone triggers it.
Sign agreement clears its threshold comfortably and is reported as clearing it; it is not
the reason for the downgrade.

**Verdict: UNINFORMATIVE.** Two labels, both stated:

- Under `r0_prereg.md`'s decision rule, verbatim: **FAIL**.
- As reported, after the addendum-1 downgrade: **UNINFORMATIVE**.

Neither threshold was adjusted. The rule was applied in the direction it can only ever
run: it weakened a FAIL, and it cannot and did not create a PASS. The premise is
**untested, not dead**.

### How robust is the call to the frozen conventions?

R10 fixed "the DV01-weighted pooled 1-minute `rho`" as the deciding quantity before any
number existed. In the event the choice is nearly immaterial:

| alternative reading | value | same call? |
|---|---|---|
| pooled 1-minute (**frozen**) | 0.405 | — |
| pooled 1-minute, unstandardised | 0.416 | yes |
| all five decision buckets below 0.50 individually | 5 / 5 | yes, under any pooling rule |
| pooled daily | 0.274 | yes |
| pooled **print** level | 0.499 | yes, but by 0.001 |

Four of the five readings clear the threshold with room. The exception is print-level
`rho` at 0.499, which would have been a coin toss — and four of five buckets are below
0.50 at print level too, so even there the majority clause fires. The margin is recorded
because it is narrow enough to matter, and the level that governs was fixed in advance
precisely so it could not be chosen afterwards.

## Limitations of this diagnostic, stated plainly

1. **`rho` is a lower bound on the median rule's true attenuation, not a point estimate.**
   `dev_curve` is itself a proxy with its own error — snapshot staleness within the minute,
   tenor interpolation, and the fact that a print can legitimately trade away from mid for
   size or credit. If the two proxies' errors are independent then
   `corr(X_med, X_cur) = rho_median × rho_curve ≤ rho_median`, so the median rule may be
   less attenuated than 0.405 suggests. This cuts *toward* the FAIL standing. It is
   disclosed rather than acted on: the addendum fixed `rho = corr(X_median, X_curve)` as
   the attenuation factor and fixed the threshold at 0.50 in advance, and the rule is
   binding as written.
2. **D1 measures 45.4% of the legs and assumes they characterise the rest.** The excluded
   prints are forward-starting, MAC, outside the twelve tenors, or outside Citi's session.
   Forward-starting and MAC prints have thinner mid keys, so a tape-internal median should
   sign them *worse*; that direction would strengthen the downgrade, not reverse it. Not
   measured, so marked as inferred.
3. **SFR_FF has the thinnest coverage** (31.6% of prints, 24.1% of DV01) and also the
   lowest daily `rho` (0.023). Its DV01 weight in the pooled figure is small (3.7%), so it
   is not driving the call — but the bucket in which the proxy looks worst is also the one
   measured on the least data.
4. **The 01:00–22:59 ET restriction removes 1.8% of otherwise-eligible prints**, and those
   are plausibly the illiquid minutes where the median is worst. Excluding them, if
   anything, flatters `rho`. Reported as coverage rather than papered over.
5. **No second specification was run.** The addendum licenses `rho` and the sign-agreement
   rate, not a re-estimation with a different X. D1 did not re-run the regression, did not
   change the specification, and did not rebuild X.
