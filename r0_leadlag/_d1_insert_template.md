<!-- scratch: the two possible D1 sections. Delete after the real one is pasted in. -->

## VARIANT A — downgrade does NOT fire (verdict stays FAIL)

Addendum 1 requires the attenuation of R0's median-based direction sign to be quantified
before a FAIL can be reported as a FAIL rather than as UNINFORMATIVE. Computed by
`run_d1.py`; operationalisation frozen in `r0_deviations.md` R10/R10a/R10b/R10c before any
`rho` was read.

`dev_curve = fixed_rate − Citi minute-curve par rate at the print's execution minute`,
reference only. It is never used to build X and X was not changed.

| quantity | value |
|---|---|
| D1 sample | {N} prints ({P}% of legs, {D}% of DV01) |
| join match rate | {M}% |
| per-print sign agreement | **{A}%** (threshold 60%) |
| pooled DV01-weighted `rho`, 1-minute — **the deciding quantity** | **{R}** (threshold 0.50) |
| decision buckets with `rho < 0.5` | {B} of {T} |
| implied MDE = 1.96 × 0.01280 / rho | **{E}** |

Downgrade does not trigger. The verdict stands as **FAIL**.

The MDE is the number to carry: the smallest true post-print effect this test could have
detected is |sum beta_k| ≈ {E}. The measured value is +0.0076.

## VARIANT B — downgrade FIRES (reported as UNINFORMATIVE)

... same table ...

**The downgrade rule fires.** Under `r0_prereg_addendum_1.md`:

> If the verdict is FAIL and (`rho < 0.5` in the deciding buckets or sign-agreement < 60%),
> the verdict is reported as **UNINFORMATIVE** under the existing "uninformative rather
> than negative" clause of `r0_prereg.md`, not as FAIL.

So there are two labels and both must be stated:

- **Under `r0_prereg.md`'s decision rule, verbatim: FAIL.**
- **As reported, after the addendum-1 downgrade: UNINFORMATIVE.**

This is not "the premise survives". It is "this test could not have seen the effect even
if it were there". The distinction matters for what happens next: an UNINFORMATIVE R0 does
not license the FAIL branch's retarget, because the null was never established.
