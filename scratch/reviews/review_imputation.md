## DEFECTS — `SDRUtils/dealer_direction/imputation.py`

*(Method note: the mutation battery in §2 temporarily rewrote `imputation.py`, ran the suite, and restored the file byte-for-byte after each mutant — asserted in `scratch/rev_imp_mutate.py`, confirmed by `git status` showing untracked-only and a re-verified green suite. No file was left edited; nothing committed.)*

---

### 1. HIGH — 6 of 18 shipped `ln_mu` values are the box constraint, not the MLE, and the degeneracy detector is structurally blind to it

`imputation.py:220` (`LN_MU_SLACK = 30.0`), enforced at `:707-708`, consumed by `CAP_BANDS` `:264-373`, flag at `:953-954`.

Measured (`scratch/rev_imp_mu_bound.py`): six cells have `ln_mu − (log(cap/4) − LN_MU_SLACK)` ≤ 2e-9:

| cell | ln_mu | log_u − 30 | gap | sigma | multiplier |
|---|---|---|---|---|---|
| V1 3m-6m | −10.480706967 | −10.480706967 | 2.9e-10 | 4.849 | 3.238 |
| V1 5y-10y | −12.434985364 | −12.434985366 | 1.9e-09 | 5.082 | **3.954** |
| V2 <=46d | −7.829815180 | −7.829815180 | 9.5e-11 | 4.621 | 2.746 |
| V2 46d-3m | −8.648125065 | −8.648125504 | 4.4e-07 | 5.028 | 3.763 |
| V2 3m-6m | −9.969881344 | −9.969881344 | 6.2e-11 | 4.656 | 2.810 |
| V2 5y-10y | −11.418051108 | −11.418051108 | 5.4e-10 | 4.533 | 2.593 |

`_ln_negll` returns a flat `1e12` outside the box, so Nelder-Mead lands on the wall. **Why it is wrong:** the multiplier in those cells is a function of an arbitrary numerical guard, not of the tape. Refitting the shipped frequency cache (`scratch/rev_imp_refit_slack.py`, which reproduces the shipped table exactly at slack 30 — 18/18 cells, 0 mismatches, so the tool is validated against a known answer) with `LN_MU_SLACK = 60`:

- V1 5y-10y **3.954 → 4.218** (+6.7%), V1 3m-6m 3.238 → 3.427 (+5.8%), V2 3m-6m 2.810 → 2.944, V2 5y-10y 2.593 → 2.713, V2 <=46d 2.746 → 2.876.

**Concrete failure — the guard that exists for this cannot fire.** `ln_degenerate` (`:953`) tests `sigma` only. The mu wall stops the optimizer *before* sigma reaches `0.98·LN_SIGMA_MAX = 5.88`, so `ln_degenerate` is `False` in all six. Relax mu and 4-5 of them immediately pin at `sigma = 6.000` and `ln_degenerate` becomes `True` — i.e. the flag reports clean precisely because a second, undetected bound bit first. The module docstring at `:216-221` claims "a fit that pins here has collapsed onto a power-law mimic … which is what `ln_degenerate` reports." It reports the opposite. Compounding: `CapBand` (`:224-247`) carries no `ln_degenerate` field at all, so the shipped table could not surface it even if it fired; and `test_every_multiplier_is_above_one_and_not_absurd` (test `:233`) asserts `1.0 < multiplier < 5.0`, which 4.218 passes.

**Honest scoping:** the headline does *not* break. Level-comparable recomputation over `partB_final_imputation_Cdiv4.csv`'s DV01 weights gives 0.1541 → 0.1589 (slack 45) → 0.1597 (slack 60/100), still inside `SENSITIVITY_DV01_SHARE = (0.1058, 0.1603)`. The defect is bound-determined per-cell estimates + a blind degeneracy flag, not a wrong headline. But `SENSITIVITY_DV01_SHARE`'s docstring (`:422-427`) calls itself "within-lognormal-family only" and enumerates threshold choices as the only within-family axis — `LN_MU_SLACK` is a second within-family axis that consumes 74% of the band's remaining headroom and is not disclosed.

---

### 2. HIGH — the module ships the double-count vector it claims not to expose

`imputation.py:631` (`out["notional_expected"] = out[notional].astype(float) * factors`) vs `:168-170`: *"`apply_to_signed_krd` is the only application helper in this module, and there is deliberately no notional-scaling counterpart."*

There is one: `impute_frame` hands every consumer a column that **is** `notional × multiplier`. The stated hazard ("Scaling notional up front and then pricing runs the multiplier through the pricing path a second time") is one column selection away, with nothing marking it as unusable for pricing.

The test that claims to guard this — `tests/test_dealer_direction_imputation.py:500-505`, *"A helper that rewrote `notional` would be used, and would double-count"* — only greps public names for the literals `scale_notional` and `apply_to_notional`. It cannot fail for any plausible implementation, and it does not fail on the one that exists.

---

### 3. HIGH — 12 of 17 mutations survive the suite; the whole fitter-calibration seam is untested

`scratch/rev_imp_mutate.py`, full suite per mutant. **GREEN (undetected):**

| mutation | test that claims to cover it |
|---|---|
| `LN_MU_SLACK 30 → 60` | none — nothing refits from data |
| `LN_SIGMA_MAX 6 → 60` | none |
| `THRESHOLD_DIVISOR 4 → 10` | none — the shipped threshold is untested |
| `MIN_TAIL_POINTS 5 → 0` | `test_fit_cell_refuses_a_sample_too_small_to_fit` (:159) trips `MIN_TAIL_WEIGHT` only |
| `ln_degenerate` hard-wired `False` | none |
| `weighted_ks`: drop the lower-edge arm | `test_the_two_families_fail_about_equally…` (:254) asserts frozen constants |
| `lognormal_cdf_truncated`: `return F` (no renormalisation) | same — a total gut, undetected |
| `pareto_cdf_truncated`: drop the truncation denominator | same |
| `pareto_tail_ratio` inverted | none |
| `pareto_truncated_mle` → naive Hill | **`test_pareto_censored_mle_recovers_alpha_where_naive_hill_is_biased` (:112)** — it recomputes Hill inline and never calls `pareto_truncated_mle`, the function whose docstring (`:793-799`) advertises the "+53%/+23%/+6%" measurement |
| `fit_frequency_table` keys every cell as `"V1"` | none — `fit_frequency_table` is never called by any test |
| `tail_mean_exists`: `> 1.0` → `>= 1.0` | `test_every_band_reports_a_tail_index…` (:192) |

Only 5 mutations went red (`apply_to_signed_krd` bound, `lognormal_mean_above` sigma shift, censored-likelihood cap-mass sign, vintage boundary `<`→`<=`, vintage-blind band lookup).

**Tests that cannot fail, individually:**
- test `:192` `assert band.tail_mean_exists == (band.tail_index > 1.0)` — restates the property body at `:250-252`.
- test `:234` `assert band.expected_notional == approx(band.multiplier * band.cap)` — restates `:255-256`.
- test `:488-490` sign-preservation loop over factors 1.0/1.7/4.0 — arithmetically impossible to fail for any positive multiply.
- test `:500-505` — name grep, see defect 2.
- test `:412-413` `assert r.tail_mean_exists in (True, False)` — true of every bool.
- `test_direction_neutrality_is_recorded_as_unresolved_not_as_neutral` (:275) and `test_headline_shares_sit_inside_the_quoted_sensitivity_band` (:247) compare module constants to module constants; they pin a story, they measure nothing. `IMPUTED_SHARE_BY_BUCKET` and `SENSITIVITY_DV01_SHARE_BY_BUCKET` have no assertion at all.

The consequence is specific: `fit_frequency_table`'s own docstring (`:970-975`) instructs a future refitter to validate with `pytest -k "recovers or grouped"`. Those two tests do not touch `fit_frequency_table`, `weighted_ks`, either `cdf_truncated`, `pareto_tail_ratio`, `pareto_truncated_mle`, `CellFit`, or any fit constant. A refit can be wrong in any of those and pass the check the module tells you to run.

---

### 4. MEDIUM — three silent-degradation paths in the refit

- **`:982-996` — success with zero rows.** `fit_frequency_table` returns `{}` when no cell clears `MIN_TAIL_WEIGHT`, with no exception, no warning, no record of which cells were dropped. Probe: a 6-row table returns `dict` of len 0. A partial refit (16 of 18 cells) is indistinguishable from a complete one. This directly contradicts `:411-414`, which insists *"'no fit' must never be read as 'no imputation'"* — an absent dict key is exactly that unreadable signal.
- **`:990` — `n_cap` silently 0.** `n_cap` counts only capped rows at `notional == C` exactly; the code at `:987-989` acknowledges capped prints land off `C`. If they all do, `n_cap = 0`, the "censored" MLE degenerates to a zero-censoring fit and still returns a confident multiplier (probe: 900 capped prints one dollar off `C` → `n_cap = 0.0`, `multiplier = 1.2376`). The falsification diagnostic then does not report the problem — `CellFit.capped_count_error` (`:911-912`) raises `ZeroDivisionError` on `predicted / 0.0`.
- **`:738-747` — `r.success` never inspected.** On the shipped calibration 14 of 576 Nelder-Mead runs hit maxiter. *Honest downgrade:* the run selected as `best` converged in all 18 cells, so the shipped numbers are not affected. But this is the exact failure `:973-975` names ("A censored MLE that has silently stopped converging still returns numbers") and there is no guard for it.

---

### 5. MEDIUM — lookahead: the multipliers are in-sample for every day they are applied to

`CAP_BANDS` (`:264`) is fitted over 2024-03-01..2026-08-07 (`:964-966`) and applied by `impute` / `impute_frame` to every leg inside that window. A ladder for 2024-06-01 carries a DV01 uplift estimated from prints through 2026-08. That is legitimate for a descriptive note and disqualifying for a backtest; the module docstring caveats family risk, threshold risk and directional neutrality at length and never mentions this one.

---

### 6. MEDIUM — interface drift from `types.py`

- **`None` vs `NaN` for the same field.** `impute()` returns `notional_impute_factor = None` (`:558`, `:579`); `impute_frame` writes `np.float64(nan)` (`:630`). `types.Provenance.notional_impute_factor` is declared `float | None` (`types.py:163`). A consumer testing `factor is not None` — the natural read of that annotation — passes NaN straight through; `apply_to_signed_krd` then raises rather than skipping. `notional_expected` is likewise NaN, not None, on uncapped legs. The two paths are cross-checked by test `:466-469` on `notional_imputed` and `reason` only, never on the factor.
- **Untyped date parameter.** `impute(notional, as_of_date, …)` and `vintage_for` take a bare date. The package has `types.Clocks` (`types.py:37-62`) built specifically so no module has to guess which of pricing / execution / event / visibility it holds — and `Clocks.execution`'s own docstring warns field #96 "can be years stale" on non-UTI-minting rows. For a backloaded print straddling `CAP_SCHEDULE_SWITCH`, execution-date and report-date give different vintages and therefore a different cap table; nothing in the signature or docstring says which is required.

---

### 7. LOW

- **`:950-952`** — `CapBand.ks_lognormal` / `ks_pareto` are computed from the **truncated** fits (`mu_t, sigma_t, alpha_t`), i.e. from the estimator the module explicitly rejects, while `ln_mu` / `ln_sigma` are the censored ones. Nothing in `CapBand`'s field comments (`:245-246`) or the docstring's family discussion (`:44-56`) says so. Recomputed against the shipped censored parameters, the max KS becomes 0.2802 — which would break `test_the_two_families_fail_about_equally…`'s own `max(series) <= 0.276` bound (test `:268`).
- **`:16`** — "probes in `scratch/partB_*.py`" is the wrong pointer for the direction-neutrality section; those numbers come from `scratch/imp07_neutrality.py`, `imp08_neutrality_ci.py`, `imp09_mh_curve_only.py`.
- **`:16`** — the citation "LEDGER F-7/F-17" is ambiguous: `docs/dealer_direction/LEDGER.md` uses the label `F-7` twice, at line 253 ("Platform mix") and line 839 ("Notional right-censoring").
- **`:474`** — `band_for_tenor(None)` raises `TypeError` from `np.isfinite`, not the `ValueError` the guard on the next line intends.
- **`:866-881`** — `weighted_ks` returns NaN (with two `RuntimeWarning`s) on zero total weight rather than raising.
- **`:180`** — the module docstring says the fitter "is validated against simulated data whose parameters are known before it is allowed near the tape — sections 1-2." True of `lognormal_censored_mle` and `pareto_censored_mle`; not true of `pareto_truncated_mle`, `weighted_ks`, either cdf, `pareto_tail_ratio`, or `fit_frequency_table`, which is the function that actually produces a calibration (see defect 3).

---

### CLEAN

- **Sign area — clean.** The module imports nothing from `conventions.py` and infers no direction. The only sign-adjacent surface is `apply_to_signed_krd` (`:648-675`): it rejects `factor < 1.0`, `None`, and NaN (`:662`), preserves sign for every accepted factor, and does not mutate its input. Traced by hand: `customer pays fixed → dealer RECEIVED → delta_dv01 > 0`, `p = p(customer paid fixed)`, `signed_weight = 2p−1` — a scalar ≥ 1 applied post-inference cannot touch any of it, and no path here computes `p`, `dealer_sign`, or a leg orientation. Separately verified by hand against the math: the censored log-likelihood `:718-723` is the correct left-truncated + right-censored form, `lognormal_mean_above` `:784-790` is `exp(mu+σ²/2)·Φ(σ−z)/Φ(−z)`, the truncated-Pareto score `:807-809` is the correct derivative of `log(1−e^{−αρ})`, and `pareto_censored_mle` `:828-829` is the correct closed form. `pareto_truncated_mle` reproduces its advertised correction (naive Hill +53.4%/+22.7%/+7.0% at α = 0.8/1.2/1.8; the truncated MLE within 0.4%).
- **Schedule lookup — clean.** Vintage boundary, band contiguity over holes, notional-over-tenor keying, and the unrecognised-cap path all behave as documented and are the parts the mutation battery does catch.
- **Frame mechanics — clean.** `impute_frame` is fully positional; verified correct on a non-default index (`[17, 4]`), a duplicate index (`[3, 3]`), integer `notional` dtype, and NaN notional.
- **Docstring arithmetic — reproduces.** `sum(n_capped)` over `CAP_BANDS` = 67,619, exactly the stated calibration population; `>30y` = 103; 68,946/2,289,646 = 3.01%; 1,326/68,945 = 1.92%; 68,945 − 1,326 = 67,619; 1,326/67,619 = 1.96%; 5.87/1.21 = 4.85×; the flat-multiplier cross-check `(k−1)·0.142/(1+(k−1)·0.142)` gives 12.4% at k=2.0 and 13.5% at k=2.1 as claimed, and the capped-at-cap DV01 share recomputes to 0.1417 against the quoted 0.142 with effective k = 2.314 against the quoted 2.31. The odds-ratio block is internally coherent: 34.4%/28.1% → OR 1.342 (quoted 1.344), and the `is_block` homogeneity z back-computes to 5.73 from the two stated CIs against the quoted −5.72.