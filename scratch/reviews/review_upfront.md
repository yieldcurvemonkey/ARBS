Verified `classifier.py:77` — the cited anchor is exactly right (`res.dealer_bought = upfront < abs(npv_pay)`; `itm_side = "PAID" if npv_pay > 0`; `dealer_direction = itm_side if dealer_bought`), so `U < |f| ⇒ dealer holds the ITM side` on entry, and lineage's unwind rule is genuinely its reverse.

---

# lineage — adversarial review

**Tooling validated before use.** Mutation harness (`scratch/lin_review/mut.py`) loads a mutated copy of `lineage.py` into `sys.modules` without touching the repo file; validated on `identity` → 30 passed (green) and `tz_utc` → 1 failed (red, the mutation `test_the_zip_member_mtime_is_eastern_and_comes_back_as_utc` names). CLI probe (`scratch/lin_review/probe_cli.py`) validated on the no-limit control (rc=0, 4/4 days written) before the `--limit` case. Baseline: **30 passed**. All writes confined to `C:\Users\chris\clee\ARBS-dd\scratch\lin_review\`; DB reads only; no git writes.

## 1. Sign: the implementation is right, but half the sign table is untested — a mutant that inverts every `npv_pay > 0` termination passes all 30 tests

`SDRUtils/dealer_direction/lineage.py:769-773`, `tests/test_dealer_direction_lineage.py:366-397`

Hand-traced the convention end to end. `conventions.py:23` pins `p = p(customer paid fixed) = p(dealer received fixed)`; `conventions.py:78` `DEALER_RECEIVED = 1`. The boolean chain is correct in all four quadrants, and its cited anchor `stir_flow/classifier.py:77` says what the docstring claims (entry: `U < |f| ⇒ dealer holds ITM`; unwind: `U < |f| ⇒ customer is ITM` — a genuine reverse).

The defect is coverage. Both sign tests use the **same single point**, `npv_pay = -1e6`:

| `npv_pay` | `U` | correct | mutant `customer_paid_fixed = u > abs(f)` | |
|---|---|---|---|---|
| −1,000,000 | 1,020,000 | +1 | +1 | tested |
| −1,000,000 | 980,000 | −1 | −1 | tested |
| **+1,000,000** | **1,020,000** | **−1** | **+1** | **untested, INVERTED** |
| **+1,000,000** | **980,000** | **+1** | **−1** | **untested, INVERTED** |

Mutant `sign_drop_f` (deletes lines 769-771, substitutes `customer_paid_fixed = u > abs(f)`) → **30 passed, GREEN**. `test_the_hand_worked_pair_agrees` is not a second example: it reuses `(-1e6, 1.02e6)` and its second assertion (`unwind_dealer_sign == -original`) is a tautology given the first. Failure this produces: every termination where the fixed payer is in the money gets a complete, plausible, exactly-inverted dealer side, and the direction-agreement rate stays near its correct value because both quadrants flip together. For contrast, `sign_flip_all` (flipping the final return) is caught by 2 tests — the suite catches the *global* flip and misses the *half*-flip, which is the harder one.

## 2. The walk stops on a self-pointing node and reports it as resolved lineage — handing the consumer a TERM as "the original"

`lineage.py:353` (self-pointers excluded from `parent`) → `lineage.py:418-420` (`elif terminal in known → ST_RESOLVED_RAW_ONLY`)

`ST_SELF_POINTER` (`:117`) guards a row that points at *itself*, and its docstring says the failure is handing "the consumer the unwind row in place of the trade it tears up". But a row that points at a self-pointer walks one hop onto it, finds no entry in `parent`, finds the id in `known`, and is labelled `RESOLVED_RAW_ONLY` with `original_execution_timestamp` = the termination's frozen `#96`.

Measured on the real unfiltered union 2026-06-15..18 (17,305 pointer rows): **every one of the 30 `RESOLVED_RAW_ONLY` rows whose terminal is not a NEWT terminated on a self-pointer** — 17 MODI, 11 TERM, 2 CORR; 5 of 2,255 TERM-keyed rows. Example: `3708520052000000101` → `3704229160000000601`, `hops=1`, `RESOLVED_TAPE`-eligible, `terminal_action='TERM'`, `event_type='EXER'` — and that same id appears in the output at index 6190 correctly flagged `SELF_POINTER`. So the module labels one id both ways in the same frame. Downstream, `direction_agreement` compares a termination against a termination, and `reach_back_days` is measured against the wrong execution.

## 3. The whole "MULTI-HOP IS NOT AN OPTIMISATION" justification does not reproduce; multi-hop resolved **zero** rows

`lineage.py:39-46`

The docstring's case is "43 TERM->TERM pointers in a single week, which is a chain of partial terminations and which a star topology cannot represent". Measured:

- filtered `sdr_cache` week 06-15..18: 31 TERM→TERM, **31 of 31 self-pointers**, 0 genuine.
- unfiltered union (this module's own reader), same week: 197 TERM→TERM, **193 self-pointers, 4 genuine** — and all 4 point at self-pointers, so they terminate at one hop.
- `coverage_summary` over the full 17,305-row union with the live tape: `"multi_hop": 0, "max_hops": 1`.

So neither the module's "43" nor the test's "42 of those 43" reproduces on either base, and the decisive number is that the transitive walk with `DEFAULT_MAX_HOPS = 16` and a cycle guard resolved **not one row** a single hop would have missed. The test at `tests:165-181` already contradicts the module docstring in the same PR ("42 of those 43 point at themselves") and the docstring was never updated. Cost of the unsupported claim: the `hops`/`CYCLE`/`MAX_HOPS` machinery, and finding #2 above, exist entirely to serve it.

## 4. `24.5% of terminations` is a reach-back statistic being used as a window-coverage statistic

`lineage.py:51-52`, repeated at `tests:289`

"When the original is outside the loaded window -- 24.5% of terminations by the measured reach-back" — 24.5% is `100 − 75.5`, the fraction with reach-back **> 1 day**. That is not the fraction outside the loaded window; the window is the 60-day union / 90-day trailing default. By the module's own adjacent figure (90.7% ≤ 63 days), a 63-day window leaves ~9% outside, and my measurement gives 3.7%. The justification for not using `core/graph_resolver` overstates its own support by 3–7×. (The 75.5/90.7/95.6 numbers themselves I measured as 89.8/96.3/98.1 on all resolved rows and 93.0/97.0/98.3 on TERM only — a different window, so I am **not** claiming those as wrong; the conflation stands either way.)

## 5. `build --limit N` always exits 2 on a successful partial pass

`scripts/build_dd_lineage_store.py:196-198` slices `todo`; `:220` then re-checks `store.days_needing_work(days)` — **`days`, not `todo`**.

Probe (control first, known answer): no limit → `rc=0`, all 4 days written. `--limit 2` → both target days written correctly (`rows=1` each), then `FAIL: 2 day(s) still have no rows on disk` and **`rc=2`**. The flag's own help text is "days per pass; resume handles the rest" (`:300`), and the module docstring defines exit 2 as "a day failed". Any chunked/unattended driver reads the documented chunking mode as a hard failure every pass. Related dead code at `:212-213`: `zero = [d for d, n in written.items() if n == 0]` can never be non-empty because `write_day` raises first.

## 6. Silent degradation: a slice scan that fails on every slice reports success with zero rows

`lineage.py:641-643` (`except Exception → logger.warning; return None`) and `:658-659` (`if not got: return pd.DataFrame(columns=[DI, "published_at", "slice"])`)

Verified: `fetch_slice_publications(day, [1,2,3], slice_source=lambda ds: None)` returns a 0-row DataFrame, no exception. `PublicationClock.from_frame` on it gives `len == 0`, so **every** row silently falls back to Appendix C — a 60-minute indeterminate legal delay in place of the measured 5.23-min median the class docstring contrasts it against, with `visibility_source` the only trace. `cmd_slices` then prints `0 distinct ids` and returns 0. This is exactly the pattern `EmptyDTCCDay`/`EmptyLineageDay` were written to forbid, in the one function that has no such guard and **no test at all**.

## 7. The measured publication clock cannot reach any consumer through the store

`lineage.py:308-311` (`LINEAGE_SCHEMA`) / `build_dd_lineage_store.py:138-170` (`resolve_and_write`)

`LINEAGE_SCHEMA` has no `published_at` or visibility column, and `resolve_and_write` never calls `fetch_slice_publications`. The `slices` subcommand only times the scan and optionally dumps to a throwaway `--out` parquet nothing reads. `types.Clocks.visibility` (`types.py:53-56`) promises "a measured publication time where the lineage sidecar has one" — that is unsatisfiable from this sidecar as built: the store, the only durable artifact, cannot carry one. Supporting fact, not the defect itself: nothing in this tree calls `PublicationClock`, `fetch_slice_publications`, `unwind_implied_original_sign`, `unwind_dealer_sign`, `direction_agreement` or `coverage_summary` as of this review (other agents may be building the consumers).

## 8. Tests that pass on mutated code

| test | mutant | result |
|---|---|---|
| `tests:366-397` (both sign tests) | `customer_paid_fixed = u > abs(f)` | **GREEN** — see #1 |
| `tests:268-279` `..._round_tripped_through_a_float_still_join` | delete the `.0` strip (`lineage.py:303-304`) | **GREEN**. The named bug happens — status flips `RESOLVED_RAW_ONLY` → `UNRESOLVED`, i.e. "the join simply misses and the row is booked as a tape ingestion gap", verbatim from `normalise_id`'s docstring — but the test asserts only `resolved_original_id == "300"` and `hops == 1`, and the *pointer* side still normalises via `.strip()`. It never asserts `status`. |
| `tests:412-420` `..._is_symmetric_under_relabelling` | `agree = called & (u == o)` | **GREEN**. `u == -o` and `u == o` are both invariant under `(o,u) → (-o,-u)`, so the test is a tautology for any odd-symmetric comparison. Its docstring claims it detects "reading an absolute side somewhere". (The mutant is caught, but by `tests:400-409`.) |
| `tests:487` `assert date(2026,7,4) not in days` — "Independence Day, not a business day" | `business_days` → `freq="B"` (holiday calendar removed) | **GREEN**. 2026-07-04 is a **Saturday**. The three federal holidays actually in the window — 2026-05-25, 2026-06-19, observed 2026-07-03 — are never asserted on, so removing `USFederalHolidayCalendar` entirely passes the test that exists to pin it. |
| `tests:317-320` `..._names_the_files_dtcc_actually_serves` | — | Checks string formatting on 3 hand-picked sequences. Never touches the ~1,970-vs-1,333 bound that `slice_date_strings`' docstring devotes a paragraph to and that the "73.7% of a day" failure depends on. |

Untested public surface: `coverage_summary` (the function that "the backfill prints and the report quotes"), `fetch_slice_publications`, `load_raw_days`, `read_range`, `cumulative_url`, `_unresolved_status`, `tape_exec_ts_lookup`, `tape_id_range`, `cmd_report`, `cmd_slices`.

## 9. `max_hops` off-by-one throws away a fully resolved chain

`lineage.py:376-378` tests `hops >= max_hops` *after* incrementing, before checking whether the walk was already finished; `:411-413` then discards `original_execution_timestamp` for any non-`None` status. Proved: a 3-hop chain terminating on a NEWT, run with `max_hops=3`, returns `status=MAX_HOPS`, `resolved_original_id='n0'` (correct), `original_execution_timestamp=NaT`. A chain that resolves in exactly `max_hops` hops is reported as a pathology and its reach-back is lost. Low frequency today (max observed 1), but it is the failure the guard is supposed to *not* cause.

## 10. Latent hazards (no live caller yet, but the interface invites them)

- **`lineage.py:759-769` — `upfront = 0.0` returns a confident side.** Only `None`/NaN return 0. Measured: `unwind_implied_original_sign(-1e6, 0.0) == -1`, `(+1e6, 0.0) == +1`. `types.Unit.upfront` (`types.py:85-90`) is "the **sum** of the legs' other-payment amounts", and ~86% of terminations carry no fee, so any `.sum()`/`.fillna(0)` path delivers `0.0` rather than `None` — and `u = 0` always yields `customer_is_itm = True`, a call determined entirely by `sign(f)`. The frozen `classifier.py` avoids this via `resolve_upfront(...)` returning `None`; this module has no equivalent.
- **`lineage.py:721` — the lookahead guard is vacuous for exactly the rows this module is about.** `if ts is not None and ts >= exec_ts` bounds the measured publication time against **execution** (`#96`), which `types.py:46-48` documents as "frozen at the ORIGINAL trade's execution and can be years stale" on every non-NEWT row. For a TERM whose `#96` is 2024, any `published_at` in 2026 passes trivially. The bound that cannot be violated is the **event** timestamp `#30`; a mis-sequenced or clock-skewed slice mtime that precedes the dissemination is admitted as a tighter availability bound, which is the one error the class exists to prevent. `test_a_measured_time_before_the_execution_is_refused` (`tests:350-359`) pins the guard as written and so cannot see this.

## 11. Minor

- `lineage.py:350-354` — `resolve_lineage` raises `ValueError: The truth value of a Series is ambiguous` on a frame with a duplicated index (`pointers.get(i)` returns a Series). Reproduced with `pd.concat([a, b])` — i.e. any caller that concatenates without `ignore_index=True`. `load_raw_days` happens to use it, so the public entry point is a trap for everyone else.
- `lineage.py:427-428` — no invariant check on `reach_back_days`. 6 rows in the measured week are **negative** (min −4.71 days: an "original" executed after the unwind that tears it up), silently included in the percentiles `coverage_summary` reports.
- `lineage.py:830-841` — `__all__` omits `ST_SELF_POINTER`, the only `ST_*` constant missing and the one v2 added (`CODE_VINTAGE` at `build_dd_lineage_store.py:44` names it as the v1→v2 change). A consumer doing `from ...lineage import *` and filtering on the exported vocabulary sees self-pointers as an unknown status. Also missing: `LINEAGE_SUBDIR`, `DEFAULT_MAX_HOPS`, `SLICE_MEMBER_TZ`.
- `lineage.py:437-439` — a **non-numeric** terminal id returns `ST_MISSING_IN_RANGE`, whose docstring (`:108-109`) reads "Inside the tape's id range and genuinely absent". An unparseable id is neither; it should be `ST_UNRESOLVED`.
- `build_dd_lineage_store.py:230-231` — `days = target_days(args) or store.covered_days()` then `min(days)`: `ValueError: min() arg is an empty sequence` when the store is empty and no range is given, before the `df.empty` guard on the next line can report it.
- `build_dd_lineage_store.py:214-216` — `print("FAIL: ...", file=sys.stderr)` at `:216` is preceded by the stdout summary; observed interleaved out of order in the probe. Cosmetic, but the runbook reads these logs.
- `lineage.py:585-587` — cross-reference `:data:`~scripts.build_dd_lineage_store.CODE_VINTAGE` runbook notes` points at a version string; there are no runbook notes there.
- `lineage.py:611` — `tz_localize(SLICE_MEMBER_TZ)` with the default `ambiguous='raise'` will raise on a member stamped inside the November DST fall-back hour. Swallowed by `:641`, so it costs one slice, not the day — noting it only because the loss would be invisible.
- `build_dd_lineage_store.py:190,207` — with `--limit`, days written in pass 1 are resolved against a smaller universe than pass 2's, and `days_needing_work` never revisits them, so a row's `status` depends on which pass wrote it. Mild here (days are ascending and originals point backward), and not visible in the ledger.

## Clean

- **The unfiltered-reader claim reproduces exactly.** Re-fetched 2026-08-06 and diffed against `ARBS/sdr_cache`: 18,520 in zip / 16,601 kept / **1,919 lost (10.4%)**; TERM 624 / 367 kept / **257 lost (41.2%)**; TERM/ETRM **39.9%**; TERM/EXER 67 in zip, 4 kept (**94.0%**); MODI 2,014 / 993 kept (**50.7%**). Every number in the docstring table. `builder.py` `ts_col` defaults to `"Execution Timestamp"` (`:383`) and the mask is at `:423`, matching the cited `:422-424`.
- **The tape interface is right.** `LEGS_TABLE.trade_id` **is** the 19-digit Dissemination Identifier (verified against a real DTCC parquet: `3689383416000000101`…). `tape_exec_ts_lookup` and `tape_id_range` both run live against prod (`range (918310324, 4653139938000000201)`, 6.7 s; 17,305 pointer rows resolved in 2.3 s, 2,941 `RESOLVED_TAPE`). Table names come from `_tape_tables.py`; `conn.set_session(readonly=True)` is set. No hardcoded suffix.
- **Convention interface is clean.** `DEALER_RECEIVED`/`DEALER_PAID` imported from `conventions.py`, never redefined; the polarity matches `stir_flow.ladder_conventions.dealer_leg_signs`; `visibility_timestamp`'s keyword-only signature is honoured. No use of `p` vs `2p−1` in this module to get wrong. `ST_*` vocabulary is disjoint from `types.EXCL_*` and does not collide.
- **Atomicity and empty-day discipline** in `fetch_raw_day` / `LineageStore.write_day` are real: `tmp.replace(path)`, and both mutants that soften the empty-day exceptions go red.
- **No curve is read anywhere in this module**, so the classic snapshot lookahead is not available to it; the only availability-clock issue is #10.

Evidence: `C:\Users\chris\clee\ARBS-dd\scratch\lin_review\` — `mut.py` (mutation harness), `probe_cli.py` (CLI exit-code probe), `resolved.parquet` / `resolved_tape.parquet` (17,305-row resolutions of 2026-06-15..18), `raw_dtcc_unfiltered/` (the five fetched days), `findings.txt`.