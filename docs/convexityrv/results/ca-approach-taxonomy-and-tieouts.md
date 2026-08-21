# Which convexity adjustment do we compute, and what does it tie out to?

There are four ways to put a number on the SOFR-futures convexity adjustment,
and they are not four approximations to one calculation — they answer different
questions and can disagree without either being wrong. This records **which one
this repo implements**, what it ties out to, and two corrections to earlier
statements made in this programme.

## The four approaches

Following the standard taxonomy (as laid out in the quant.stackexchange thread
on STIR futures convexity):

1. **Fit a short-rate model** — Hull-White, Ho-Lee — and read the adjustment out
   of the model's own futures-versus-forward difference.
2. **A heuristic formula driven by a swaption covariance matrix.**
3. **The same heuristic driven by historic realised vol.**
4. **Imply it directly** from the observed futures strip against the observed
   IRS curve.

Approaches 1–3 *produce* an adjustment from a vol input. Approach 4 *measures*
one from two market observables and can then be inverted to back out the vol
the market is charging.

## We implement approach 4

`Query/IRSwaps/IRSwapValue.py::_convexity_adjustment` computes

```
CA = pack_rate − matched_forward_swap_rate      (in bp)
```

where `pack_rate` is the strip-implied rate over the pack's own window and
`matched_forward_swap_rate` prices a swap over *exactly* that window. Both legs
are quarterly-quarterly, and the convention travels in `value_kwargs` so it
enters `_query_fingerprint` and cannot silently differ between two calls that
look the same.

The identity holds exactly on the shipped panel:

```
max | (pack_rate − swap_rate) × 100 − ca_bp |  =  0.000e+00 bp   over 29,643 gate-passing rows
```

Ho-Lee (`CA = ½·σ²·mean(T1²)`) appears in this repo only as an **inversion** — a
way to express a measured `ca_bp` as an implied bp/yr vol so it can be compared
with a swaption or an option surface. It is not the source of the number.

### A note on the reference implementations

Demonstrations of approach 1 that build a `CompositeCurve` and read a
futures-versus-forward gap out of it are **mechanism demonstrations, not market
measurements**. Where the "STIR proxy instruments" in such a demo are plain
`IRS` objects, they carry no convexity of their own, so what comes back is the
model's assumption made visible — useful for showing what the adjustment *is*,
not for pricing one. Our approach 4 measurement and their approach 1 demo are
answering different questions, and a disagreement between them is not a defect
in either.

## Internal tie-outs

| pair | n | corr | max abs diff |
|---|---:|---:|---:|
| `ca_bp` vs `ca_bp_q20` | 29,643 | **1.000000** | **0.000e+00 bp** |
| `ca_bp` vs `ca_bp_settle` | 29,643 | 0.999774 | 1.139 bp |

### Correction A — `ca_bp` *is* `ca_bp_q20`, not the settle-based column

An earlier statement in this programme described the shipped `ca_bp` as
settle-based. It is not. `ca_bp` and `ca_bp_q20` are the **same number to
0.000e+00 bp on every one of 29,643 rows** — they are one column under two
names, both built off the Q20 curve. `ca_bp_settle` is a genuinely different
column, built from the raw settles, and it differs by up to **1.139 bp**.

This matters for anything that quotes a CA level. A 1.1 bp discrepancy is large
next to Whites (median 0.12 bp) and small next to Golds (median 13.49 bp), so
which column a figure came from changes what it means at the front and not at
the back — exactly the pattern that makes the confusion survive a spot check.

## External tie-out: Citi Figure 58, 2023-06-09

13 published rows, graded in bp on a level rather than by correlation (see
`w2b-ca-vs-swap-fly.md` §7 for why a correlation grades nothing here):

| | |
|---|---:|
| rows resolved | 13 / 13 |
| median absolute error | 0.99 bp |
| worst | 3.06 bp |
| mean error | −0.04 bp |
| slope of ours on theirs | **0.850** |
| intercept | **+1.76 bp** |

The slope is the interesting part: our CA curve is ~15 % flatter across rank than
Citi's. Citi price off a cap surface; we invert the futures-versus-swap identity,
so a difference in the term structure of vol lands exactly there.

## The shape is Ho-Lee's, measured

Median CA by colour on the fully gated panel, against the median time to the
pack's first contract:

| colour | n | median CA (bp) | IQR | median T1 (yr) | CA / T1² |
|---|---:|---:|---:|---:|---:|
| Whites | 987 | 0.12 | 0.92 | 0.13 | — |
| Reds | 1,376 | 1.28 | 3.06 | 1.13 | 1.01 |
| Greens | 1,369 | 4.50 | 2.91 | 2.13 | 0.99 |
| Blues | 1,355 | 8.75 | 4.69 | 3.13 | 0.89 |
| Golds | 1,345 | 13.49 | 8.26 | 4.12 | 0.79 |

`CA / T1²` is flat at ≈1.0 for Reds and Greens and falls to 0.79 by Golds —
a downward-sloping vol term structure, read straight off the measurement. The
Whites cell is omitted because T1² there is ~0.017 and the ratio is noise.

### Correction B — the negative Whites readings are *not* a front-end degeneracy

An earlier statement attributed negative Whites CA to degeneracy in the swap
curve at very short forward starts. That explanation is unnecessary, and the
arithmetic says so:

```
Whites, fully gated:  median  0.1175 bp
                      sd      0.9451 bp
                      |median| / sd = 0.124

P(X < 0) for a Normal with that mean and sd     = 45.05 %
observed fraction negative                      = 42.35 %
```

The observed negative rate is *below* what symmetric noise around a 0.12 bp
quantity would produce. There is nothing left for a curve defect to explain. The
true adjustment at the front is simply small compared with quote noise, and a
small positive number measured with ±0.9 bp of noise is negative about half the
time.

This is why the swap-leg gate's backstop is on **magnitude, not sign** (see
`ca_swap_leg_gate.py`). Dropping every negative reading would have been fitting
the theory, and it would have removed 42 % of Whites for being correct.

## A rateslib hazard worth recording

Give a convexity spread curve **one extra node** — 3 free degrees of freedom
against 2 calibrating swap quotes — and Levenberg-Marquardt and Gauss-Newton
return curves **2,233 bp apart**. Both print `SUCCESS`, both report `f_val` on
the order of 1e-17, and both reprice **every calibrating instrument to 3e-7 bp**.

Under-determination is completely invisible from the solver's own report. `f_val`
measures how well the curve reprices the quotes it was fitted to, which an
over-parameterised spline does perfectly while oscillating between them, so the
residual cannot distinguish a determined system from an undetermined one — the
optimizer artifact fits just as well as the answer.

The guard: wherever a `CompositeCurve` spread is fitted against a `Solver`, **pin
and assert the spread curve's free-DF count against the calibrating-quote
count**, and sanity-check the resulting *level*. Never treat convergence as
correctness.

## Where the code is

| what | where |
|---|---|
| the measurement | `Query/IRSwaps/IRSwapValue.py::_convexity_adjustment` |
| the daily series | `TB/IRSwapsTB.py::sfr_cvx_adj` |
| the minute series | `TB/IRSwapsTB.py::sfr_cvx_adj_intraday` |
| the panel and its gates | `RVUtils/ConvexityRV/strat2_q20.py` |
| the swap-leg gate | `RVUtils/ConvexityRV/ca_swap_leg_gate.py` |
| Ho-Lee, as an inversion only | `RVUtils/ConvexityRV/holee.py` |
