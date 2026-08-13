All checks complete. Harness validated in both directions (unmutated copy → 61 pass; `p_customer_paid` sign flip → 6 red).

---

## DEFECTS — `SDRUtils/dealer_direction/probability.py`

### 1. A parent-bucket `h` is labelled an *independent* estimate and buys the anchored sample floor — measured 20× too-narrow `tau`
`probability.py:665-666` (`anchor_h = float(parent_h)`), `:751` (`_anchored_decomposition(xt, anchor_h)` — `external` defaults True), `:873`, `:775-776`, `:1188-1206`.

`_parent_h` returns the parent bucket's `h`. The parent's sample is a **strict superset of the child's rows**, so it is not outside the sample, yet it takes the same code path as the tick lattice: flag `FIT_ANCHORED_H` = `"H_FROM_INDEPENDENT_ESTIMATE"`, and `min_n_required` drops 800 → 400 so `for_key` stops pooling it away.

Measured, same 450-obs sample, true `h=0.07, s=0.20` (`tau_true = 0.286` bp):

| | flags | min_n_req | h | tau |
|---|---|---|---|---|
| no anchor | `N_BELOW_MINIMUM, SEPARATION_BELOW_FLOOR` | 800 | 0.008 | **1.664** (5.8× wide, safe, and excluded) |
| `parent_h=0.20` | `SEPARATION_BELOW_FLOOR, ROBUST_SCALE_FALLBACK, H_FROM_INDEPENDENT_ESTIMATE` | **400** | 0.200 | **0.0143** (20× narrow, admitted to the ladder) |

Failure: a bucket whose own likelihood says there is no spread (`h/s = 0.04`) is handed the parent's `h/s ≈ 1`, producing near-certain `p` from noise, in a bucket that would otherwise have been pooled. The `MIN_BUCKET_N_ANCHORED` docstring's own warning ("an anchor 25% too LOW inflates tau by 4.4x") applies here at 2.9× too high — and `MEASURED_MIN_BUCKET_N_ANCHORED` was measured (`prob06_anchored.py`) with an **exact** anchor only.

Compounding: `probability.py:780-781` builds the cross-check **only when `tick_stats is not None`**, so on the parent-anchored route `FIT_CROSSCHECK_DISAGREES` cannot fire even in principle — the one route with no second opinion is the one with no check.

**No test covers this.** Mutation `_parent_h` → always `return None`: **61/61 still pass.**

### 2. `_anchored_decomposition`'s `b0` is untested, and it is the `b0` every real bucket gets
`probability.py:887` `return float(np.median(xt)), h_fb, s_fb, extra`

Mutation: return `0.0` instead of `np.median(xt)` → **61/61 pass.** The bias term that shifts the whole logistic is unpinned on the code path that, per my `scratch/prob05_real.py` run, **100% of real buckets take** (all 27 buckets flagged `ROBUST_SCALE_FALLBACK`). A `b0` error is a direct `p` inversion for every deviation between the true and assumed bias.

### 3. The module's headline "checked against a number this module did not produce" is circular
`probability.py:46-64`

The table claims `b0` reproduces LEDGER F-20's independently measured medians. I re-ran `scratch/prob05_real.py`: every one of those buckets goes through `ROBUST_SCALE_FALLBACK`, where `b0 := float(np.median(xt))` (`:887`). The docstring's "fitted b0" column (3M −0.129, 1Y −0.228, 2Y −0.395, 3Y −1.114, IMM_2Y −6.584) reproduces exactly, because it **is** the trimmed median of the same data whose raw median is the "known answer". The EM never touched those numbers. The docstring even explains the gap as "the trim removing an asymmetric tail that the raw median keeps" — that is the whole content of the comparison. It validates trim stability, not the estimator; the module docstring presents it as the estimator agreeing with an external measurement.

### 4. `MAX_SE_LOG_TAU` uses the wrong quantile of its own tolerance — gate 28% too loose
`probability.py:203`, docstring `:201-203`

`TAU_RECOVERY_TOLERANCE` is the p90 of the **absolute** relative error (`_tau_errors`, `:1542`, takes `abs(...)`; `tau_recovery_error`, `:1555`, takes `quantile 0.90`). The p90 of `|N(0,σ)|` is `1.6449σ`, not `1.2816σ` (measured: empirical p90 of |Z| = 1.6448). Coded `0.1951`; derived from the stated tolerance `0.1520`, **+28.3%**.

Failure: fits with `se_log_tau ∈ (0.152, 0.195]` keep their own MLE `tau` when the measurement that set the tolerance says they need the anchor or the pool — a systematically over-confident `tau` in exactly the marginal-identifiability band this routing rule exists to police.

### 5. `_bootstrap_q_pvalue` counts skipped replicates as evidence for the null — biases the p-value down
`probability.py:1510-1516`

`if len(ys) < 2: continue` skips a replicate without decrementing `reps`, but the denominator is `(reps + 1)`. Every skipped rep is silently scored "not worse than observed".

Measured on `h/s = 0.75, n = 400` fits: **4 of 60 reps skipped** → 6.7% downward bias. Degenerate case: if every rep skips, `p = 1/(reps+1) = 0.0164 < alpha=0.05` and `TauStability(moves=True)` is returned from **zero valid replicates** — a "tau moves" verdict manufactured from total estimation failure. This is the module's own SE-independent cross-check on `tau_stability` (`:1461-1465`), so it fails in the direction of agreeing with a bad SE.

### 6. Silent degradation: paths that report success with zero rows
- `probability.py:1432-1433` — `rolling_calibrations` `continue`s any date whose window is thin, returning a dict that is short by an unreported number of days. Measured: 200 rows / 10 days → `{}`, **no exception, no warning, no flag**. A caller that iterates the returned dict classifies nothing and sees success.
- `probability.py:1468-1470` — `tau_stability` silently discards every fit with `se_log_tau is None` (i.e. every fallback fit, which on real data is all of them) and reports `k` without saying how many were dropped.
- `probability.py:1348-1368` — `Calibration.report()` on an empty `fits` returns a column-less `pd.DataFrame([])`; downstream column access raises far from the cause.

### 7. `crosscheck_against_tick`'s `s` arm is dead in every test
`probability.py:1116-1117`

Mutation `s_ind = 7.0 * sigma_mid(stats)` → **61/61 pass.** Every test constructs `TickStats(disp_jns=None)`, so `s_ind` is always `None`, `ratio_s` is always `None`, and the `s` half of `agrees` is never evaluated. Half of the module's "second independent check" is unexercised.

### 8. `FIT_CROSSCHECK_DISAGREES` is never emitted under test, and is structurally silent on real data
`probability.py:786-787`

Mutation: replace `if xcheck.comparable and not xcheck.agrees:` with `if False:` → **61/61 pass.** `test_crosscheck_flags_a_fit_that_disagrees_with_the_tick` (test:350-363) calls `crosscheck_against_tick` directly and never goes through `fit_mixture`, so the flag-emission path has no coverage.

On real data the flag is unreachable: `comparable = mle_reliable = not imprecise`, and the anchored route is taken *because* `imprecise` is True. My `prob05_real.py` run shows `ratio_h` of 0.022–0.34 (MLE 3×–45× below the tick) on all 7 sub-3y buckets, every one `comparable=False, agrees=False`, **none flagged**.

### 9. The EM label-swap branch has never executed
`probability.py:829-832`

Mutation: `raise AssertionError` inside the branch → **61/61 pass**, so it is never reached. A second mutation breaking its arithmetic (`b0_new = xbar - h_new * ubar`, dropping the compensating negation the docstring at `:200-214` calls "the trap") also passes 61/61. The one place in the module where a sign genuinely cancels twice is untested dead code.

### 10. `for_key`'s trimmed-vs-raw `n` distinction is untested
`probability.py:1332`

Mutation `fit.n_trimmed` → `fit.n` → **61/61 pass.** On the legacy tape the trim removes real mass (the 1e4 bp pathologies), so this is the difference between admitting and pooling a bucket.

### 11. `tenor_band` silently maps a zero or negative tenor into the shortest band
`probability.py:1145` — `return TENOR_BAND_LABELS[0] if y <= 0 else TENOR_BAND_LABELS[-1]`

`tenor_band(0.0)` and `tenor_band(-3.0)` return `"0-1M"`, not `"UNKNOWN"`. A bad or mis-signed tenor is calibrated against the 0–1M half-spread instead of being refused. Test:542-550 checks only 0.02, 2.0, 2.0001, 45.0.

### 12. `report()` prints `separation` and `tau_bps` computed from different `h`
`probability.py:1352-1353` — `separation` (`:434`) uses raw `h`; `tau` (`:427-430`) uses `max(h, _h_floor(s))`. In the probe, `SOFR|2Y`: `separation = 0.014` but `tau = 4.879` implies `h/s = 0.05`. A reviewer reading the artefact cannot reconstruct `tau` from the columns next to it.

---

## DEFECTS — tests

### 13. `test_min_bucket_n_is_the_measured_floor_not_a_round_number` cannot fail
`tests/test_dealer_direction_probability.py:432-433` against `probability.py:153-154` and `:181-182`:
```python
MEASURED_MIN_BUCKET_N = 800
MIN_BUCKET_N = MEASURED_MIN_BUCKET_N          # probability.py:153-154
...
assert prob.MIN_BUCKET_N == prob.MEASURED_MIN_BUCKET_N   # test:432
```
Same symbol on both sides. Both asserts are tautologies; only the third clause (`> ... > 100`) has content. The test's name claims the floor is the measured one — nothing here checks that.

### 14. `test_a_flagged_bucket_falls_back_to_a_robust_scale` checks the implementation against itself
`tests/…:261-262` asserts `fit.s == sqrt(prob.trimmed_dispersion(kept)**2 - 0.20**2)` using `prob.trimmed_dispersion` — the very function `_anchored_decomposition` calls at `:875`. Any change to `trimmed_dispersion` changes both sides identically. Confirmed: mutating it to an RMS-about-zero left this test **green** (it was caught only incidentally, by the degenerate-shape tests). Since the frozen predecessor's documented bug is precisely an RMS about zero (`probability.py:1075-1078`), this is the one test that should have been able to see it.

### 15. `test_pooling_walks_the_ladder_and_always_terminates_at_a_global_fit` asserts nothing the code can violate
`tests/…:426-427`. `for_key` always sets `FIT_POOLED` on any non-exact match, so the second disjunct is unconditionally true and the first is dead. Verified: the exotic key returns `pooled_from='GLOBAL'`, but the test would pass identically if it pooled to any wrong donor — `pooled_from` is never asserted.

---

## INTERFACE DRIFT

### 16. The fit-flag vocabulary has nowhere to live in the pinned data contract
`probability.py:241-251` defines ten `FIT_*` constants "so the provenance accounting adds up", and `ProbabilityCall.flags` (`:1017`) carries them. Neither `types.DirectionCall` (`types.py:126-147`) nor `types.Provenance` (`types.py:149-170`) has a field for them — `Provenance` carries `tau_bucket` and `code_vintage` only. Every real bucket in my probe carries `LEPTOKURTIC_MOMENT_CHECK_FAILED, SEPARATION_BELOW_FLOOR, ROBUST_SCALE_FALLBACK`; all three are dropped at the boundary, so a consumer cannot gate on the thing the module spent most of its machinery producing.

### 17. `p` subtracts `b0`; `conventions.dealer_side` does not, and nothing reconciles them
`probability.py:943` (`z = (x - fit.b0) / fit.tau`) vs `conventions.py:171-187` (`dealer_side(price_to_mid_bps)`, no bias term). `ProbabilityCall` exposes no `dealer_sign`, so the rate-rule producer must remember to bias-correct before calling `dealer_side`.

Measured with the module's own `b0 = -0.4836`:

| x (bp) | `p` implies | `conv.dealer_side(x)` |
|---|---|---|
| −0.60 | −1 | −1 |
| −0.30 | **+1** | **−1** |
| −0.20 | **+1** | **−1** |
| −0.05 | **+1** | **−1** |

**28.3% of the 49,765 real `RATE_VS_MID` rows** fall in that band. `ladder._assert_weight_agrees_with_side` (`ladder.py:305-313`) raises on exactly this disagreement, so the natural implementation hard-fails on 28% of the tape. `upfront.py:528-551` avoids it by bias-correcting `edge` first; there is no rate-rule producer yet, so this is a live hazard rather than a live bug — but `test_the_sign_convention_survives_the_probability_layer` (test:942-950) uses `b0 = 0.0` and structurally cannot see it.

---

## CLEAN AREAS

**Sign convention (item 1) — correct.** Worked example through the real functions, OUTRIGHT / rate rule: traded 5.0050% vs mid 5.0000% → `structure_price` 500.50 vs 500.00 bp → `x = +0.50` bp → `tau = 0.15²/(2·0.25) = 0.045` → `p = 0.999985` → `signed_weight = +0.99997` → `conv.dealer_side(+0.5) = +1 (DEALER_RECEIVED)` → `dealer_received_signs = (+1,)` → receiver leg, raw rateslib delta < 0, `× RL_DELTA_TO_FUTURES_EQ(−1)` → `delta_dv01 > 0`. Matches the pinned convention exactly. CURVE case: `x = +1.0` bp → `dealer_side = +1`, legs `(−1, +1)` (dealer receives the back leg, pays the front) — consistent with `base_orientation(CURVE) = (−1, +1)`. The sign flip is caught: mutating `(x - b0)` → `(b0 - x)` turns 6 tests red. The `h > 0` convention and the EM's label-swap invariance are algebraically correct (I re-derived the M step).

**Lookahead (item 5) — clean.** `rolling_calibrations` (`:1426-1428`) sets `hi = as_of − min_gap_days` with `min_gap_days ≥ 1` enforced at `:1413`, selects `d <= hi`, and `as_of` is only stamped on the fit. Nothing in the module reads a curve, a clock, or an execution timestamp; `Calibration.fit` touches only the frame handed to it.

## Files

- Reviewed: `C:\Users\chris\clee\ARBS-dd\SDRUtils\dealer_direction\probability.py`, `C:\Users\chris\clee\ARBS-dd\tests\test_dealer_direction_probability.py`
- Review scratch (new, mine): `C:\Users\chris\clee\ARBS-dd\scratch\rev_prob_mutplug.py`, `rev_prob_mutate.py`, `rev_prob_signtrace.py`, `rev_prob_parent.py`, `scratch\_mut\`
- Nothing under `SDRUtils/` was edited; no git write commands were run.