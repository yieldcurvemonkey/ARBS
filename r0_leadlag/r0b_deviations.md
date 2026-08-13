# R0b — deviations and runner choices, FROZEN BEFORE EXECUTION

`r0b_prereg.md` is the binding specification and is **not edited**. This file records
everything the data forced, and every runner choice the prereg left open, **written
before `run_r0b.py` was written and before any R0b beta, rho or coverage number existed
beyond the two counts quoted in R0b-4 below**. Ordering is checkable from the git log
against the mtimes of `out/r0b_*`.

R0's own `r0_deviations.md` (R1–R10c) is inherited verbatim wherever it is not
contradicted here. R0b changes exactly one thing — where X's direction sign comes from —
and every consequence of that one change is listed below.

---

## R0b-1 — the sign rule

```
customer_sign_curve = +1  if fixed_rate >  curve_mid
                      -1  if fixed_rate <  curve_mid
                       0  if exactly equal, or no curve_mid available
```

`curve_mid` is the Citi minute-curve par swap rate of the print's own tenor,
curve `USD-SOFR-1D`, read through `IRSwapsMDP(source="citivelo_excel_rl")` — the **RL**
token; a `-QL` spelling silently never consults the minute store.

No probability model, no `tau`, no dead zone, no `signed_weight`. No import of
`SDRUtils.dealer_direction` or `SDRUtils.stir_flow`. The downstream mapping to predicted
futures flow is R0's, unchanged: `predicted_futures_sign = -customer_sign`, so the hedge
channel is still `beta_k < 0` at small positive `k`, and a positive `beta_k` of the same
magnitude is a different phenomenon, not a pass.

## R0b-2 — the curve is read at the EXECUTION minute, on both clocks

The prereg says "at the print's snapped minute". That is operationalised as the
**execution** minute for both the execution-clock and the dissemination-clock panel.

Two independent reasons, both of which point the same way:

1. **Byte-identity with R0 requires it.** `build_x_tape.attach_mid_sign` sorts by
   `execution_timestamp` and computes the trailing median in execution order; the
   resulting `customer_sign` is then applied unchanged to both clock panels. R0b changes
   the sign *source*, not when the sign is taken.
2. **It is the correct economics.** Whether the customer paid or received is a property
   of the trade at the moment it was struck. Comparing a print to a curve mid from
   several minutes later — after the market has moved — would mismeasure the direction
   of the very trade being signed.

The clocks continue to differ only in which timestamp the print is *binned* on, exactly
as in R0.

## R0b-3 — coverage: a print with no curve is dropped, not defaulted

A print is **curve-signed** only if all of the following hold:

| condition | why |
|---|---|
| `fwd_key == "spot"` | the reference is a spot-starting par rate; a forward-start print is not comparable to it, and `fwd_key` is a *bucketed* label (`0-3M`, `3-6M`, …) from which no exact forward start can be recovered |
| `is_mac == False` | a MAC coupon is not a par rate |
| `tenor_label` in the pulled reference set (R0b-4) | no series, no mid |
| execution minute inside Citi's published USD session, **01:00–22:59 ET** | R10a. Citi publishes nothing 23:00–00:59 ET and the minute store has **no lag tolerance**: it will serve a snapshot from the wrong day or from *after* the requested instant. The pull logs record both hazards firing at exactly the ET-midnight boundary. For a rule that *infers direction* from a print, a forward-looking reference is circular, so those minutes are excluded rather than filled |
| the `merge_asof` (backward, 2-minute tolerance) matches | R10, unchanged |

Everything else gets `customer_sign_curve = 0` and therefore contributes **zero** to
`signed_dv01`. This is estimation-identical to deleting the print, because
`run_r0.x_series` reads `signed_dv01` and nothing else; `gross_dv01` and `n_prints`
continue to count **all** in-scope prints so the signed share is readable from the file
itself. Coverage is reported, per bucket, in prints and in DV01, against R0's own
91.1% / 91.7% signed share.

This is the single largest limitation R0b imports and it is stated in advance: R0b's X
measures the *spot, non-MAC, curve-covered, in-session* subset of the same tape R0's X
measured almost all of.

## R0b-4 — the reference tenor set: D1's twelve, extended

D1's twelve tenors were a **diagnostic sample** — a sample is sufficient to *measure*
rho. R0b's reference is the **input**, and inheriting a diagnostic's sampling restriction
when more coverage is already warm and local would attenuate X for no reason.

**Frozen rule:** the reference set is every tenor label that (a) appears among spot,
non-MAC, in-window prints and (b) is in `scripts.citivelo_intraday_ts_warm.SPOT_TENORS`,
**intersected with the pulls that actually complete**. A tenor whose pull fails is
excluded and disclosed by name, exactly as R10c provided for; it is never grounds for
re-specifying the set.

Measured before the rule was written, and the reason for it:

| set | spot non-MAC in-window prints | share of ALL in-window DV01 |
|---|---|---|
| D1's twelve | 144,688 | **49.0%** |
| + the 16 further `SPOT_TENORS` labels present | 169,219 | **58.2%** |

Pull order is descending DV01 (`4y 15y 9y 6y 8y 25y 12y 11y 18m 9m 4m 40y 5m 21m 15m
50y`) so that a forced stop banks the largest tenors first. The gains concentrate in
**US** and **SFR_FF** — two of the three buckets R0's informativeness gate killed.

No tenor was added or dropped after any correlation, beta or verdict was computed.

## R0b-5 — everything else is imported from `run_r0.py`, not restated

`run_r0b.py` imports `rolling_scale`, `shift_global`, `build_grid`, `make_design`,
`run_one`, `ols_with_ses`, `lincomb`, `diffcomb`, `FEAbsorber`, `selftest`, and the frozen
constants (`KMIN/KMAX`, `N_YLAGS`, `NW_BANDWIDTH`, `TSTAT_CRIT`, `DECISION_BUCKETS`,
`ROLL_WIN/ROLL_MINP`, `EDGE`, `REGCOLS/IPOS/INEG`) from `run_r0.py` rather than copying
them. Same bucket map, same `k = -30..+30`, same bin-of-day fixed effects, same five Y
lags, same day-clustered inference with Newey-West alongside, same two clocks, same five
splits, **same Y file, untouched**. The verdict ladder is R0's, applied verbatim.

## R0b-6 — the informativeness gate

`r0b_prereg.md` replaces addendum 1's downgrade rule with:

> R0b is informative iff its MDE is below the magnitude of the pre-print mass it
> measures.

Operationalised, per bucket and pooled, on the dissemination clock, all flow:

```
rho_R0b = corr(X_R0b, X_curve)            (= 1.000 by construction; computed, not assumed)
MDE     = 1.96 * SE_daycluster(sum beta_k, k>=1) / rho_R0b
bucket is UNINFORMATIVE  iff  MDE >= |sum beta_k, k<=-1|   for that bucket
bucket is FAIL/PASS/AMBIGUOUS per r0_prereg.md otherwise
```

`rho` is computed and printed rather than asserted, so the division is done as the
addendum did it.

**Declared in advance, because it is foreseeable and must not be improvised afterwards:**
if the `k < 0` trough collapses — which is one of the two pre-registered discriminator
outcomes — then `|S_neg| -> 0` and this gate fails *by construction*, in every bucket,
however good R0b's power actually is. The gate is applied verbatim regardless, the
degeneracy is reported as a caveat, and the absolute MDE is reported alongside R0's
0.0620 so the reader can see whether power improved. The discriminator payoff does not
depend on the gate.

## R0b-7 — the `rho`-equivalent, and what it is not

`corr(X_curve, X_curve)` is 1, so the task asks instead for `corr(X_R0, X_R0b)`: how far
the input actually moved. Frozen definition:

- **Headline**: Pearson correlation of the two standardised bucket-minute series that the
  two regressions actually consume — dissemination clock, all flow, on Y's grid, after
  `rolling_scale` (R4). Pooled over the grid, and per bucket.
- Reported alongside on the **execution** clock, and at print level as the sign-agreement
  rate on the intersection where both rules sign the print.

It confounds two things and is labelled as doing so: sign *disagreement* on prints both
rules sign (D1 measured 68.3% agreement), and *coverage difference* (R0 signs 91.7% of
in-window DV01; R0b signs the R0b-3 subset). It is a description of how much the input
moved, not an attenuation factor.

## R0b-8 — the `k < 0` discriminator, read from fixed windows

The windows are R0's, so the two results are directly comparable:
`k -30..-18`, `k -17..-2`, `k -1`, `k 0`, `k +1`, `k +2..+17`, `k +18..+30`, each with its
sum and its share of total `|beta_k|`, plus the five most negative lags. The reading is
`r0b_prereg.md`'s table, applied to those numbers:

- mass still spanning roughly `-20..-2` → genuine pre-dissemination activity;
- mass collapsed to `|k| <= 1` → the stale-median artifact;
- mass gone → the same, more strongly.

Join staleness is reported with it — the distribution of `exec_min - ref_min` on matched
joins — because the sharp reading of the collapse case rests on the curve being at most
one minute stale, and a 2-minute `merge_asof` tolerance can reach `k = -2` wherever a
reference minute is missing.

## R0b-9 — validation gates, hard-fail, before the estimator sees anything

`run_r0b.py` refuses to report a verdict unless all of these pass, and prints them:

1. R0's full `selftest()` — injected effect at `k = +3` recovered against an a-priori
   prediction, the `k = -3` mirror, the null DGP, FE absorption, cluster SEs vs
   `statsmodels`.
2. The plumbing check on the **real** grid with **R0b's** X: Y replaced by
   `-0.25 * Xstd_(t-7) + noise`, recovered at `k = +7` and nowhere else.
3. The session reconstruction hard gate against `data/y_sessions.csv` (R0's caveat 11).
4. The reference join gates, re-run on R0b's larger sample: units detected from the data
   (median `ref_rate/fixed_rate`), vectorised orientation (`rate > mid` ⟹ `dev_curve > 0`),
   per-day median `dev_curve` near zero, `corr(dev_curve, rate level)` near zero, and
   sign agreement with `dev_median` rising with `|dev|`.
5. Every reference series re-verified after the move to `D:` — row count, span,
   duplicate-free, NaN-free.

## R0b-10 — mechanical

- All caches under `D:\r0b_cache\` (`ref/`, `ts/`) plus the twelve D1 series already at
  `D:\r0_cache_moved\cache_d1_ref\`. `C:` had 3.7 GB free at the start of R0b.
- Python invoked directly as `C:/Users/chris/anaconda3/envs/stir/python.exe`; never
  `conda run` (parallel invocations collide on a temp file and return empty output with
  exit code 0).
- `ARBS_SUPABASE_ENABLED=0` before anything importing `Caching`. Tape DB read-only;
  nothing written to it. Nothing is fetched at estimation time — the reference pull is a
  separate, resumable step.
- **No git write command is run by this workstream**, and no prereg file is edited.
- The script is invoked twice by design: once as `--selftest` (preflight, no real data)
  and once for the single real run. Any further execution is disclosed in
  `R0B_RESULT.md`, as R0 disclosed its cluster-label re-run.
