# R0 — pre-registration

**Written and committed BEFORE any regression was run. Not edited after seeing
results.** Any deviation forced by the data is recorded in a separate
`r0_deviations.md`, never by editing this file.

Branch `r0-leadlag`, worktree `C:\Users\chris\clee\ARBS-r0`.
Date: 2026-08-11.

---

## The question

Does customer-to-dealer swap flow, as inferred from the public SDR tape, lead
signed aggressor volume in the corresponding futures contract?

The premise under test is the intraday front-running story: a dealer who takes
on duration from a customer must hedge it, and the hedge shows up as aggressive
futures flow shortly afterwards. If that is real, flow observed on the
**dissemination** clock should predict futures flow at positive lags.

## Why this is deliberately independent of the risk ladder

R0 must not import, wait on, or borrow from the KRD engine, the projection
matrix, or any change-of-basis code. The moment it depends on the ladder it
stops being a fast independent test and inherits every bug in the thing it is
meant to evaluate. A crude fixed tenor→bucket map is the *requirement*, not a
compromise — if R0 needed the ladder to work, a negative R0 would be
uninterpretable.

## Decision rule

Evaluated on the **dissemination clock**.

| verdict | condition |
|---|---|
| **PASS** | `sum(beta_k for k >= 1)` is significant under day-clustered standard errors **AND** at least **2x** the magnitude of `sum(beta_k for k <= -1)` |
| **FAIL** | mass concentrated at `k < 0`, **or** post-print mass indistinguishable from zero under day-clustered standard errors |
| **AMBIGUOUS** | both significant — the post-print share is reported explicitly |

"Significant" means the day-clustered t-statistic on the relevant sum exceeds
1.96 in absolute value.

Where day-clustered and Newey-West (60-bin bandwidth) disagree, **the
day-clustered result governs**. The effective sample size is roughly 60 trading
days, not roughly 50,000 prints, and treating prints as independent would
manufacture significance.

## The specification, fixed in advance

### Buckets — fixed map, boundaries documented and NOT optimised

| tenor | futures bucket |
|---|---|
| <= 1.5y | SFR strip (first 12 contracts, aggregated) + FF |
| 1.5 - 3y | TU |
| 3 - 7y | FV |
| 7 - 12y | TY + UXY |
| 12y+ | US |

These boundaries are round numbers chosen to sit near the CTD of each contract.
They are not tuned and will not be revisited after seeing results.

### X — signed customer DV01 from the SDR tape, 1-minute bins, per bucket

Sign convention, asserted in exactly one place and unit-tested:

```
customer pays fixed -> dealer received -> dealer long duration -> dealer SELLS futures
```

So **positive X predicts NEGATIVE signed futures flow**, and a working hedge
channel appears as `beta_k < 0` for small positive `k`. The sign of the
prediction is part of the pre-registration: a positive `beta_k` of the same
magnitude is not a pass, it is a different phenomenon.

Built twice:
- `X_diss` — indexed by dissemination timestamp (D3)
- `X_exec` — indexed by execution timestamp (#96)

All timestamps UTC.

### Y — signed aggressor volume in contracts, from L3 MBO, 1-minute bins

Buyer-initiated minus seller-initiated.

### Standardisation

X and Y are standardised within bucket by rolling standard deviation, so
buckets pool.

### The regression

```
Y_{b,t} = alpha_b + sum_{k=-30}^{+30} beta_k * X_{b,t-k}
          + bin-of-day fixed effects
          + 5 lags of Y
          + eps
```

Run pooled with bucket fixed effects, and separately per bucket. Run once on
`X_diss` and once on `X_exec`. **No tuning.**

### Inference

Cluster standard errors **by day**. Not optional. Also report Newey-West with a
60-bin bandwidth; where they disagree, trust day-clustered.

### Outputs

- Chart: `beta_k` against `k`, two panels (execution clock / dissemination
  clock), day-clustered confidence bands, vertical line at `k = 0`.
- Table: `sum(beta_k)` for `k < 0` against `k > 0`, the difference and its test,
  per bucket.
- Splits: block-election flag (#93) True/False; D2C against IDB by platform
  identifier MIC.
- `N_days` and `N_bins` printed at the top of the output.
- The verdict, stated as PASS / FAIL / AMBIGUOUS against this file verbatim.

## What would make this test uninformative rather than negative

Recorded in advance so it cannot be invoked selectively afterwards:

- Fewer than ~20 trading days of overlap between the MBO data and the tape.
- A bucket with no measurable futures flow in the sample.
- A dissemination clock that is not actually recoverable, forcing `X_diss` to
  fall back to a legal-delay estimate — in which case the dissemination panel
  tests the estimate, not the clock, and must be labelled as such.

Any of these is reported as a caveat on the run. **None of them licenses
re-running a different specification.**

## Discipline

One specification, run once, reported. If something looks wrong it is reported
as a caveat rather than silently re-run as a variant. If a data issue blocks R0
outright, stop and ask rather than substituting a workaround that changes the
test.
