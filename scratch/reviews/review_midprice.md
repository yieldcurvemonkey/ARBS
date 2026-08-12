## Defects — `SDRUtils/dealer_direction/midprice.py`, `tests/test_dealer_direction_midprice.py`

Worktree `C:\Users\chris\clee\ARBS-dd`. Baseline: 40/40 pass (`python -m pytest tests/test_dealer_direction_midprice.py`, incl. both `slow` tests, 7.5s). Mutation harness validated first against a known-bad control (`structure_dv01 -> sum(|pv01|)` → 6 failures), so surviving mutations below are meaningful. Nothing was edited; mutations were applied by a pytest plugin at `scratch/rv_mut_plugin.py`.

---

### 1. A NaN mark is reported as success — the exact failure the module says it refuses
`midprice.py:574` (`_price_one` return), `midprice.py:499-523` (aggregation), `midprice.py:202` (`structure_dv01` NaN gate).

`LegQuote.ok` is `failure is None`. Nothing checks the *values*. A leg whose `mid_pct`, `pv01` or `npv_pay` comes back NaN instead of raising is `ok`, so `RepricedUnit.failure` stays `None` and the unit goes to the ladder. Measured (`scratch/rv_nan_probe.py`, fake pricer):

| injected | `failure` | `leg_mid_pct` | `structure_dv01` | `gross_pv01` | `npv_pay` |
|---|---|---|---|---|---|
| NaN mid | `None` | `[nan]` | **4000.0** | 4000.0 | — |
| NaN pv01 | `None` | `[4.0]` | `None` | **nan** | — |
| NaN mid + upfront | `None` | `[nan]` | 4000.0 | 4000.0 | **nan** |

Concrete failure: a NaN mid yields `failure=None` *and* a confident `structure_dv01=4000.0`, so downstream `deviation_bps = (traded − nan)` is NaN, `dealer_side(nan)` returns `DEALER_PAID` (`nan > 0` and `nan < 0` are both False → falls through to the `return 0`… actually returns 0, "no call") and the row is counted as a *priced* leg in the stratified success rate — the fixings failure the `START_PAST` stratum exists to expose is counted as a success in that stratum. The NaN-pv01 case is worse in the other direction: `failure=None` with `structure_dv01=None` is "success with no denominator", and `gross_pv01=nan` propagates silently to the PKG-N payer-frame denominator.

Two contract statements are false as a result: `structure_dv01`'s docstring (`midprice.py:199`) — "``None`` when any leg is unpriced, so a partially priced package cannot produce a confident-looking denominator" — gates only `pv01`, never `mid_pct`; and the test-module docstring (`test_…midprice.py:13`) lists "a pricing failure recorded as a silent NaN with no reason attached" as a failure this file exists to prevent, while no test injects a NaN at all.

**Calibration:** the mechanism is confirmed; a *production* NaN is not demonstrated. Deep past-start legs (eff 2015-01-05 and 2020-01-06) priced correctly on the real Citi minute curve, and short/matured legs failed loudly as `PRICING_ERROR`. The rateslib fixings `RuntimeWarning: invalid value encountered in divide` (`rateslib/data/fixings.py:3426`) fires during the legacy slow test, which shows the NaN-producing code path executes — it is not proof a NaN reaches `mid_pct`.

### 2. `_price_one` crashes on a null effective date, and the test that names this case cannot reach it
`midprice.py:552` and `tests/test_dealer_direction_midprice.py:480-487`.

`stratum = start_class(row["effective_date"], snap)` sits **outside** the try/except, and `start_class` does `pd.Timestamp(None).date() - ref` → `TypeError: unsupported operand type(s) for -: 'NaTType' and 'datetime.date'`, which propagates out of `price_unit`. Verified: `scratch/rv_midprice_probe.py` → `RAISES OUT OF price_unit: TypeError`. The `_has_date` guard and `START_UNKNOWN` exist only on the refusal path (`midprice.py:594-595`), so `START_UNKNOWN` is unreachable from a successful pass.

The named test passes `rate_index="BASIS"`, which returns at `midprice.py:461` (`EXCL_UNSUPPORTED_INDEX`) before any leg is priced — so `test_a_leg_with_no_effective_date_gets_a_named_stratum_not_a_default` only ever exercises `_refused`, the one path that already has the guard. It is green against the bug its name describes.

**Latent, not live:** measured against production `arbs_usd_swap_tape_legs_v3` — 2,326,781 legs, **0** null `effective_date`, 0 null `expiration_date`, 0 null/negative/zero-guard-evading `notional`. A crash needs an upstream frame that introduces NaT.

### 3. Mutation survivors — six mutations of the implementation leave all 40 tests green

Harness control `control_dv01_sum` → **6 failed**, so the harness bites.

- **`always_strict_pricer` → 40 passed.** `SessionBranchPricer.mark_curve`/`price_leg` (`midprice.py:331,352`) can be rewritten to ignore the session and always use the strict pricer with no test noticing. `_FakePricer.policy_for_instant`/`mark_curve` (`test:97-98,104`) hardcode `POLICY_STRICT`, and **no test calls `price_unit` at an out-of-session instant** — `OUT_OF_SESSION` (test:40) appears only at lines 174 and 188, both against `policy_for_instant`/`policy_for` directly. The module's central design claim ("two pricer objects, not one with a per-call policy") has its dispatch untested end-to-end, and `POLICY_HOLE` is never asserted as a produced row value. The implementation is correct — I verified the real hole branch: a 00:30 ET SOFR unit is served under `ASOF_2H_OUT_OF_SESSION` at lag 5400 s and prices at 3.6656% (`scratch/rv_ff_and_hole.py`). It is unpinned, not wrong.
- **`clock_execution` → 40 passed.** Substituting `unit.clocks.execution` for `unit.clocks.pricing` at `midprice.py:456` changes nothing, because `_unit()` (test:146-148) sets `pricing=execution=event=visibility=ts` in every fixture. The #96-vs-#30 choice is the lookahead-critical decision this package was built around (`snapshot.pricing_timestamp`: a TERM row's #96 can be twenty months stale) and this test file cannot detect its loss.
- **`test_npv_is_the_fixed_payer_frame_summed_over_legs` (test:391) pins the fake, not the implementation.** The payer frame is defined at test:122 inside `_FakePricer.price_leg` (`npv = (mid − fixed) * 1e4 * pv01`); `price_unit` only sums. A receiver-frame `IRSwapValue.NPV` would pass this test unchanged, and no test computes an NPV on the real path (both `slow` tests use `upfront=None`, so `want_npv` is False). Not a sign error — I measured the real frame on the Citi minute curve at 2026-04-01 14:29 ET: fixed 3.1313% → `npv_pay = +227,409`; fixed 3.6313% (= mid) → `−0.0`; fixed 4.1313% → `−227,409`. Payer frame, correct. It is a cannot-fail test for the property it claims to pin.
- **`gross_pv01_unsigned` → 40 passed.** `gross_pv01 = sum(abs(p))` (`midprice.py:522`) can drop the `abs()`; `gross_pv01` is never asserted anywhere in the test file, despite being documented (`midprice.py:159-162`) as the payer-frame denominator for PKG-N.
- **`spot_window_10` → 40 passed.** `_SPOT_WINDOW_DAYS` (`midprice.py:75`) can widen 3 → 10. The parametrised cases (test:464-468) pin the boundary only from below (delta 2 must be SPOT, delta 369 must be FORWARD); nothing sits in 4-10 days.
- **`lag_abs` → 40 passed.** `snapshot_lag_seconds` can be recorded as `abs()`, destroying the sign that `snapshot.snapshot_lag_seconds` deliberately reads from `snapshot_lag_signed_seconds` rather than the absolute key.

Also untested: `FLAG_EOD_CLOCK` and the whole date-only-clock refusal branch (`midprice.py:465-474`) — neither the flag nor `EXCL_NO_CURVE`-via-EOD appears in any test.

### 4. `_assert_telemetry` trusts the boolean and ignores the signed lag it already holds
`midprice.py:528`. `if mark.served_from_future:` — a `None` (metadata absent) is falsy, so a mark with `lag_seconds=-900.0` and `served_from_future=None` passes: verified, `failure=None`, `snapshot_lag_seconds=-900.0`, no flag. `UnitPricing.snapshot_lag_seconds`'s own docstring (`types.py:112`) says "Negative would mean a curve from the future, which the strict policy forbids", two files away from the check that doesn't test it. Low severity in practice: `IRSwapsMDP._wrap_citivelo_excel_minute:3380-3382` always emits both keys together on the minute path, so partial metadata would have to come from a different wrap path or a stand-in MDP.

### 5. Minor / interface
- `midprice.py:583-584`: on the EOD-clock refusal `UnitPricing.curve_timestamp` is a `datetime.date`, against the `pd.Timestamp` annotation in `types.py:106` and `types.py:157`; a provenance frame gets a mixed-dtype column.
- `midprice.py:587`: `snapshot_policy=policy or ""` — every refusal except `SnapshotMiss` records the empty string, including on the legacy source where the module docstring insists `POLICY_NONE` is "named on every row rather than left to be inferred".
- `midprice.py:597` / `_refused`: `FLAG_LEG_FAILURE` is never appended on the refusal path even though every `LegQuote` carries a failure, so a health count keyed on that flag undercounts.
- `tests/test_dealer_direction_midprice.py:538`: "Only ever run on fakes." is false — the test calls `UnitRepricer.for_source(LEGACY_CURVE_SOURCE)`, constructs a real `IRSwapsMDP` and prices against a real Barchart curve (it ran and passed here in 0.55 s).

---

## Clean areas

**Signs — no defects.** Hand-traced, SOFR 5Y outright on the real 2026-04-01 14:29 ET Citi minute curve: mid `3.6312863809922797`%. A print 5 bp above at 3.68129% → `conventions.structure_price([3.68129], OUTRIGHT, 1, RULE_RATE)` = `+1 × 3.68129 × 100 = 368.129` bp vs mid `363.129` bp → deviation `+5.0` bp → `dealer_side(+5.0) = +1 = DEALER_RECEIVED` → `dealer_received_signs = +1 × (+1,) = (+1,)` = dealer received fixed = long duration = `delta_dv01 > 0`, and `p = p(customer paid fixed) > 0.5`. Matches the pinned convention. `midprice` supplies `leg_mid_pct` in **percent** (verified on the real path: 3.63 for a 3.63% swap), which is what `structure_price` multiplies by 100 — the same boundary the frozen `classifier._rate_pct` uses. `quote_weights` reproduces the frozen `s2m` formulas exactly: CURVE `(-1,+1)` → `R_back − R_front` = `classifier.py:92`; FLY `(-1,+2,-1)` → `2·belly − front − back` = `classifier.py:98`. `structure_dv01`'s max-|weight| generalisation reproduces `classifier.structure_dv01` on all five parametrised cases (that test is a genuine cross-implementation check). `pv01` is positive on the real path (4548.19 for 1e7 5Y); `upfront.py:529` negates `npv_pay` correctly (`dev = -npv_pay/dv01`) to land back in the price-paid frame.

**Lookahead — none found.** `price_unit` snaps to `snapshot.snap_instant(clocks.pricing)` = floor-to-minute-in-NY minus one minute, so the curve minute is strictly before the print (verified: a 14:30:41 print asks for 14:29:00). The hole branch is backward-only (`allow_future=False`, real 00:30 ET probe served at +5400 s, i.e. 23:00 ET the prior day). `CircularCurve` fires on `served_from_future` (subject to §4). The date-only clock is refused rather than degraded to an EOD curve that postdates the print. `in_session` raises `UnknownSessionError` on unmodelled curve names rather than guessing, and the legacy path short-circuits before reaching it.

**Interface drift** from `types.py`/`conventions.py`: clean apart from the `curve_timestamp` dtype above. All five seam members named in `UnitRepricer`'s docstring exist and are the ones actually called.

**Docstring claims are backed.** LEDGER F-15 carries the session-branch measurement verbatim (2026-06-01 in-session gap served at 15 min stale by a global 2 h bound; 7/7 hour-00 prints; whole-day 2026-04-01 sweep 873/919 → 919/919), F-16 the 55 × `notional = 1e20` / 54 × `fixed_rate = 9.9` sentinels, D11 the two-measurement tie-out, F-8 the 1,465 `|fixed_rate| ≥ 1.0` legs. The cited scratch scripts (`dd04_session_branch.py`, `dd18_one_full_day.py`, `dd19_legacy_source.py`, `dd12_coverage.py`) all exist. The 14.6% / 339,497 past-start figure is not in the LEDGER but is consistent with my independent unfiltered count (367,644 / 2,326,781 = 15.8%, a wider denominator than "eligible flow legs").

**Pricing at the printed (capped) notional is correct, not a defect** — `imputation.py:165` states the multiplier is applied "to the signed KRD, after direction inference. Never to notional", and `impute_frame` writes `notional_expected` as a separate column by design.

Scratch files written (none in the package): `scratch/rv_midprice_probe.py`, `rv_midprice_npvsign.py`, `rv_nan_probe.py`, `rv_real_nan.py`, `rv_ff_session.py`, `rv_ff_and_hole.py`, `rv_tape_probe.py`, `rv_mut_plugin.py`. No files edited, no git writes.