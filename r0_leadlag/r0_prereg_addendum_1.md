# R0 — pre-registration, addendum 1: proxy attenuation

**Written 2026-08-11, BEFORE any beta was estimated.** Verified at the time of
writing: `r0_leadlag/out/` does not exist, no chart, table, or result file
exists anywhere under `r0_leadlag/`, and `r0_prereg.md` is unmodified since
commit `f37bef33`. The X and Y builders were still constructing inputs. The
ordering is checkable from the git log against the mtimes of `out/`.

`r0_prereg.md` itself is **not edited**. This file adds a diagnostic and one
downgrade rule.

---

## Why this addendum exists

X's direction sign comes from a **tape-internal rolling median** of same-tenor
prints, because the isolation rule forbids using the curve stack. That
satisfies isolation, but it is more fragile than merely "crude":

- **It is a high-pass filter on the flow.** The rolling median tracks the
  window's own prints, so a persistently one-directional stretch pulls the
  median toward the flow and the residual `rate − median` is driven back toward
  zero *by construction*. The window length sets the cutoff frequency.
- **The damping is worst exactly in the regime being hunted.** A burst of
  same-direction customer flow — the thing that should generate a hedge — is
  the thing the median absorbs.

The error is in the safe direction: attenuation shrinks `beta`, so it biases
toward **FAIL**, never toward a false PASS. But that asymmetry is precisely why
it must be quantified. **Under this X, a PASS is stronger evidence than a FAIL**,
and an unquantified FAIL cannot distinguish "no signal" from "no power".

## Diagnostic D1 — measure the attenuation, do not correct for it

For a sample of prints spanning the R0 window, compute the per-print deviation
two ways:

- `dev_median` — `rate − rolling same-tenor median`. This is R0's actual input.
- `dev_curve` — `rate − Citi minute curve mid` at the print's snapped minute.
  **Reference only.** It is never used to build X, and R0's X is not changed.

Reading the Citi minute curve here is not an isolation breach: it is market
data, read directly through `MDP/IRSwaps/CITIVELO_EXCEL` and `Caching`, with no
import of `SDRUtils.dealer_direction` or `SDRUtils.stir_flow`. Its role is to
size the measurement error in R0's own input, which is a property of R0.

Report, per bucket:

| quantity | why |
|---|---|
| `rho` = `corr(X_median, X_curve)` on the 1-minute standardized series | with both series standardized, `beta_hat = rho * beta_true`, so `rho` **is** the attenuation factor |
| sign-agreement rate between the two per-print rules | the most interpretable form: 50% is a coin flip, 85% is a decent proxy |
| `rho` at print level, at 1-minute level, and at daily level | if `rho` collapses under aggregation, that confirms the median is high-passing the flow rather than merely adding noise |
| implied MDE = `1.96 * SE(sum beta_k, k>=1) / rho` | the smallest true post-print effect this test could have detected |

## The downgrade rule

Applied **only** to a FAIL, and it can never create a PASS:

> If the verdict is FAIL **and** (`rho < 0.5` in the deciding buckets **or**
> sign-agreement < 60%), the verdict is reported as **UNINFORMATIVE** under the
> existing "uninformative rather than negative" clause of `r0_prereg.md`, not as
> FAIL.

Thresholds fixed now and not tuned. `rho = 0.5` means under a quarter of the
variance is shared and `beta` is halved — a real effect could hide. Sign
agreement of 60% is barely above the 50% coin flip. A PASS is unaffected by this
rule in either direction.

## Diagnostic D2 — an attenuation-invariant comparison

Both clock panels use the same X, so `rho` cancels in any ratio or shift between
them. Report the **centroid of the `|beta_k|` mass on each clock** and the
difference. That statistic is robust to attenuation even when the levels are not.

## Interpreting the two panels — stated now, so it is not chosen later

The two panels answer different questions and the distinction decides what a
result means:

- **Execution clock, mass at `k > 0`** — the hedge *mechanism* exists: the
  dealer trades futures after taking the swap on.
- **Dissemination clock, mass at `k > 0`** — the hedge is still *available* when
  the print becomes public, i.e. it is tradeable. This is what the decision rule
  is evaluated on, and rightly so: flow that is finished before the print is
  public is not an opportunity.
- **Execution clock, mass at `k < 0`** — leakage, pre-hedging, or a common
  driver. **Attenuation cannot manufacture this**, because damping shrinks
  magnitudes and does not move mass across lags. It is therefore the one finding
  that cannot be blamed on the crude X.

Note the mechanical consequence of the ~5.23 min median publication lag: a hedge
executed shortly after the trade can land **before** dissemination, appearing at
negative `k` on the dissemination panel. That is a real property of the
opportunity, not a specification error — but it means a dissemination-clock FAIL
alongside an execution-clock `k > 0` mass should be read as *"the mechanism is
real but exhausted before the public print"*, which is a different and more
useful statement than *"no hedging happens"*.

## What this addendum does not change

The specification, the regression, the bucket map, the `k` range, the clustering,
and the PASS/FAIL/AMBIGUOUS rule in `r0_prereg.md` are all unchanged. Nothing
here alters what is estimated — only what is reported alongside it, and the one
downgrade of a negative result.
