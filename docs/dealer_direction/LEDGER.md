# Dealer direction on the USD swap SDR tape — working ledger

Branch `feat/dealer-direction`, worktree `C:\Users\chris\clee\ARBS-dd`.
Started 2026-08-11. Long-running; this file is the durable memory.

**Scope**: per-trade direction inference with calibrated confidence + the
aggregated signed key-rate DV01 ladder. NOT: futures hedge mapping,
inventory decay, MBO, trading signal, backtest.

---

## Sign convention (fixed once, everything agrees)

```
customer pays fixed  ->  dealer RECEIVED fixed
                     ->  dealer is long duration
                     ->  pending hedge is SELLING futures
```

Persisted ladder convention, inherited unchanged from
`SDRUtils/stir_flow/ladder_conventions.py`:

```
delta_dv01 > 0   <=>   dealer long futures-equivalent   <=>   dealer RECEIVED fixed
```

`p` is always **p(customer paid fixed)** = p(dealer received fixed).
So `p > 0.5` pushes the ladder positive.

---

## Phase log

### Phase 0 — orientation (2026-08-11)

Worktree created off `origin/main` @ `5675ac73`.

### Phase 1 — tie-out surface vs the existing short-end classifier (2026-08-11)

Probes: `scratch/probe_direction_table.py`, `scratch/probe_universe_v2_v3.py`,
`scratch/compare_0717.py`, `scratch/inspect_flips.py`,
`scratch/probe_tieout_universe.py`. Prod Supabase, read-only.

**T-1. The old pipeline still runs on today's main.** Production command,
`--dry-run`, exit 0:

```
ARBS_SUPABASE_ENABLED=0 python -u -m SDRUtils._swappulse_scripts.backfill_stir_direction \
  --classify-date 2026-07-17 --calib-start 2026-06-01 --calib-end 2026-06-30 \
  --warm-jobs 8 --dry-run
```

484 units (persisted count for that day: 484, same unit_keys), calibration 4,548
tick rows in 32.7 s, classification 9.2 s against a warm CurveStore.

**T-2. `arbs_stir_direction_v1` state.** 84,586 rows · 2026-01-12 → 2026-07-29 ·
138 days. Vintages: `468474ca6f84` 84,439 (all 138 days) and NULL 147 (07/02,
07/09, 07/10). Direction PAID 71.33% / RECEIVED 28.38% / UNKNOWN 0.29% (242).
Confidence LOW 57.76% / HIGH 34.30% / MEDIUM 7.65% / NULL 0.29%.
`curve_suspect_trade` TRUE on 31,614 (37.4%). Method: RATE_VS_MID 49,858 ·
NPV_VS_UPFRONT 19,543 · TICK_RULE 11,185 · SPREAD_VS_MID 3,459 · FLY_VS_MID 392.
`arbs_stir_tick_size_v1`: 32,075 rows, 2025-12-12 → 2026-07-21.

**T-3. Persisted rows came off the _v2_ tape; today's code reads _v3_.**
`trade_selection.py` hardcoded `arbs_usd_swap_tape_*_v2` until 570da074
(2026-08-08). Measured kept-unit overlap (v3 today vs persisted): identical
unit-for-unit on 01-13, 02-11, 03-11, 04-08, 05-13, 06-10, 07-17; 549/551 on
07-09; then it breaks — 07-22 674 of 1,078, 07-24 200 of 294, 07-29 699 of 1,450.
**Clean tie-out window = 2026-01-12 .. 2026-07-20** (77,418 rows, 131 days).
The 7,168 rows after 07-20 sit on a tape the v3 regeneration has since replaced.

**T-4. Re-running 2026-07-17 today reproduces 482/484 directions (99.59%).**
Numeric drift is float-noise (`curve_mid` max 8.8e-14, `repriced_pv01` 2.9e-11,
`repriced_npv` 4.6e-07). Both disagreements are explained:

- `4263694900000000201` — persisted UNKNOWN (`PRICING_ERROR: fixings contain more
  fixings than expected`, 2026-07-03) now prices under rateslib 2.7.1 → PAID.
  A repair, not a disagreement.
- `PTP_4266133321000000101` — `spread_to_mid_bps` moved +1.33e-13 → 0.0, and
  `classifier.classify_unit` ends `RECEIVED if s2m > 0 else PAID`. **There is no
  zero branch**, so the sign of a 1e-13 float picks the side. 3 of 376 on-market
  units on 07-17 have s2m exactly 0.0, all labelled PAID.

**T-5. The tick-rule fallback can never fire for a package.**
`_onmarket_prints` filters `n_package_legs <= 1` and hardcodes
`structure_type = "OUTRIGHT"`, so `prev_rate_lookup(bucket, unit.kind, ts)` keyed
on `(tenor_bucket, kind)` misses for every CURVE / FLY / PKG unit. Those units
get `confidence=LOW, use_tick_rule=True` and keep the knife-edge sign.

**T-6. `_stir_direction_golden.py` pins nothing and is imported by nothing.**
No test, notebook or script references it; there is no stored fixture. It is a
live A/B comparator (`capture_golden` runs the classifier against prod and
returns the frame; `diff_against_golden` diffs a later run). It still works —
self-diff 0 rows on 07-17 — but its default `stats=None` means **no calibration**,
which is not the production row set: vs the prod-calibrated run for 07-17 it
differs on 4/484 `dealer_direction`, 6/484 `classification_method` and 81/484
`direction_confidence`.

**T-7. `code_vintage` cannot see the change that actually moved the numbers.**
Current tree hashes to `870c71f0698b` vs persisted `468474ca6f84`. But the
rateslib 2.1.1 → 2.7.1 upgrade (2529fee8) is not in `VINTAGE_SOURCES` and is the
change that repaired T-4's UNKNOWN. Neither is the tape generation. The stamp is
necessary, not sufficient. Never reason "same vintage ⇒ same rows".

---

## Tie-out design (D6)

**Reference is a FRESH dry-run of frozen `stir_flow` on today's stack, not the
persisted table.** T-3 and T-4 force it: the persisted rows carry a dead tape and
a dead rateslib. The persisted table is a *cross-check* only. Cost is known —
9.2 s/day warm + 32.7 s per monthly calibration — so a 131-day reference costs
well under an hour using the chunk windows in
`scripts/backfill_dealer_ladder_window.sh` (calibration window ends the day
before the chunk, no lookahead).

| | |
|---|---|
| window | 2026-01-12 .. 2026-07-20 · 131 days · 77,418 persisted rows |
| universe | `is_excluded_unit`-surviving units of `ELIGIBLE_LEGS_SQL`: `economic_class='ECONOMIC_FLOW'`, `contributes_to_flow`, `venue='D2C'`, `rate_index_clean IN ('SOFR','FED_FUNDS')`, `fixed_rate NOT NULL`, every leg maturity ≤ `as_of_date + 1105d`, no MAC / SPREADOVER* / MATCHED_MATURITY* / INVOICE* `trade_type`, no `CME Term` / `Amortizing` in `leg_tape_label` |
| key | `unit_key` — `trade_id` for singletons, `package_id` for packages. Deterministic (self-diff 0 rows). The new per-leg output must be aggregated onto the old unit definition. |
| exclusions | the 147 NULL-vintage rows (07/02, 07/09, 07/10) |

**Probability → side.** `p` = p(customer paid fixed) = p(dealer RECEIVED).
`side_new = RECEIVED if p > 0.5 else PAID`; `|p − 0.5| < τ` is `ABSTAIN`, reported
not counted. Where old `p_flip` is populated (only 32,563 of 84,586 rows), the
old implied p(received) is `1 − p_flip` when old side is RECEIVED and `p_flip`
when PAID — a probability-vs-probability check on that subset (Brier / rank
correlation), not just a side check.

**Metric must be stratified. A flat agreement number is floored at 71.3% by
"always PAID".** Report side agreement per (`direction_confidence` ×
`classification_method` × old side), plus Cohen's κ on the 2×2, over
*decisive* rows only. Reported separately, never counted as agreement:
old `UNKNOWN` (242), `TICK_RULE` (11,185), `curve_suspect_trade` (31,614),
and knife-edge rows `|spread_to_mid_bps| ≤ half the futures tick`
(45 of 376 on-market units within 0.5 bp on 07-17 alone).

**Acceptance.** The measured ceiling for same-logic reproducibility across a
stack change is 99.59% (T-4), with both residuals named. So:
≥99% on old-HIGH decisive rows; ≥97% on all decisive rows; κ ≥ 0.90 on
old-HIGH. **And every disagreement must fall in a named class** — knife-edge
(|s2m| ≤ half tick), tick-rule, pricing-error repair, curve difference. An
unexplained residue is the failure signal; the percentage is not.

**When the NEW one is the wrong one.** A disagreement counts against the new
classifier when the old row is HIGH confidence, not `curve_suspect_trade`,
`|spread_to_mid_bps| > 2 ×` the bucket median tick, and the new `p` is decisively
opposite (>0.7 on the other side) **after repricing on the same curve**
(`BARCHART_STIRF-RL`, `snap_timestamp` minute). The same-curve control is what
separates a logic error from a curve-basis effect — if the new system prices on
citivelo minute curves, near-mid flips are expected and prove nothing.
Two aggregate gates first: (a) near-100% inversion ⇒ sign-convention bug in the
new code, not a tie-out result; (b) mean new `p` over old-PAID must be < 0.5 <
mean new `p` over old-RECEIVED.

Conversely the OLD one is wrong where the new one flips a knife-edge s2m
(T-4/T-5) or a package that the old tick-rule could never reach.

---

## Measured facts (v3 tape, `arbs_usd_swap_tape_*_v3`)

Probe: `scratch/probe_tape_facts.py`. Prod Supabase, read-only.

| fact | value |
|---|---|
| coverage | 2024-03-01 → 2026-08-07, 610 days, 2,326,781 legs |
| legs columns / packages columns | 143 / 88 |
| economic_class | ECONOMIC_FLOW 2,289,646 · ECONOMIC_UNWIND 36,828 · ADMINISTRATIVE 307 |
| lifecycle_type | NEW_TRADE 2,256,825 · TERMINATION 50,926 · OTHER 19,030 |
| rate_index_clean (flow) | SOFR 2,198,209 · FED_FUNDS 70,413 · BASIS 15,182 · OTHER 5,842 |
| beyond 3.02y (current cutoff) | **1,595,321 of 2,289,646 flow legs = 69.7%** |
| ptp_group_id populated (flow) | 1,222,903 / 2,289,646 = 53.4% |
| capped legs (flow) | 68,946 = 3.0% (`is_capped` == `is_notional_capped` exactly) |
| block legs (flow) | 55,110 = 2.4% |

### F-1. Lineage is ABSENT from the tape but PRESENT in raw SDR

- No `original_dissemination_identifier` / `prior_uti` / `prior_usi`
  column on `arbs_usd_swap_tape_legs_v3`. The 2026-07-14 finding recorded
  in `stir_flow/unwinds.py` **is still true**.
- `trade_id` IS the Dissemination Identifier (`SDRUtils/config.py::TRADE_ID`).
- Raw SDR slices carry `Original Dissemination Identifier` (#2) —
  `SDRUtils/core/lifecycle.py`, `core/graph_resolver.py`,
  `data/builder.py::_SDR_ID_COLUMNS` all read it.
- **Decision**: build a lineage *sidecar* from the raw slices rather than
  re-generating 610 prod days of tape. Reversible, out of the prod write path.

### F-2. The tape's own unwind/lifecycle enrichment is empty

Across all 2,326,781 rows:

| column | populated |
|---|---|
| `lc_was_partially_terminated` | 0 |
| `lc_has_partial_unwind` | 0 |
| `lc_inception_notional` | 0 |
| `lc_current_notional` | 0 |
| `d2_missing` | 0 |
| `rc_timeline_json` | 2,326,781 rows, **every one an empty `[]`** |
| `xd_status` | NULL 2,035,177 · ACTIVE 291,467 · TERMINATED **89** · ERRORED 35 · PARTIAL_UNWIND **13** |

This is a v3 enrichment defect. Reported, not fixed here (out of scope).

### F-3. `event_timestamp` is NOT a usable availability clock

`report_lag_seconds` = event − execution, over all 2,289,646 flow legs:

| is_block | n | p50 | p90 | p99 | max |
|---|---|---|---|---|---|
| False | 2,234,536 | 0.0 | 0.0 | 1091 s | 2,402,886 s |
| True | 55,110 | 0.0 | 0.0 | 911 s | 1,352,256 s |

Event ≈ execution for >90% of rows, blocks included. The tape has no
dissemination timestamp. **The honest availability clock is the Part 43
Appendix C legal-delay estimate** already implemented in
`ladder_conventions.visibility_timestamp`. Carry all three columns.

### F-4. The tape's `risk` column has catastrophic outliers — never sum it

`sum(abs(risk))` by rate index gives FED_FUNDS 1.166e17 and SOFR 2.590e16.
Those exact totals reappear as single platforms (BILT, XXXX), so a handful
of corrupt rows dominate every aggregate. **The ladder is built from our own
repriced KRD only**; tape `risk` is used for nothing that is summed.

### F-5. An other-payment sign solver already exists

`arbs_usd_swap_tape_packages_v3`: `opa_sign`, `opa_signed_amount`,
`opa_sign_confidence`, `opa_constrained_net`, `opa_ptp_residual`,
`dealer_spread_est`, `dealer_spread_bps`.

| opa_sign_confidence | n packages | mean abs residual | mean dealer_spread_bps |
|---|---|---|---|
| EXACT | 39,821 | 17.3 | 0.0025 |
| TIGHT | 37,365 | 456 | 0.033 |
| LOOSE | 98,796 | 8,794 | 0.302 |
| UNRESOLVED | 175,528 | 180,448 | 0.534 |

`dealer_spread_est` on 351,510 of 1,437,838 packages; leg `opa_sign`
populated on 711,210 legs (+1: 361,270 / −1: 349,940).

### F-6. Structure mix (ECONOMIC_FLOW legs)

OUTRIGHT 1,265,450 · CURVE 286,152 · FLY 228,428 · IMM 195,400 ·
SPREADOVER 106,121 · MATCHED_MATURITY 60,270 · SPREADOVER_CURVE 35,642 ·
INVOICE 32,058 · FOMC 30,934 · SPREADOVER_FLY 21,558 · MAC 14,953 ·
MATCHED_MATURITY_CURVE 4,972 · INVOICE_SWITCH 4,914 · BASIS_CURVE 1,150 ·
INVOICE_CALENDAR 792 · MATCHED_MATURITY_FLY 642 · BASIS_FLY 210

Package leg counts run 1 → 30+.

### F-7. Platform mix (ECONOMIC_FLOW legs)

D2C-whitelisted today: TWSF 1,174,416 · BBSF 405,081 · BILT 321,545.
D2D: DWSF 71,469 · TSEF 55,260 · ISWV 50,505 · BGCD 38,684 · TPSE 21,600.
Currently `VENUE_UNKNOWN`: XXXX 51,260 · XOFF 28,401 · TREU 25,192 ·
BMTF 20,678 · RTXF 7,476 · ISWE 6,880 · TWEM 4,775 · BTFE 3,012 · GSEF 2,658
and a long tail.

### F-8. What the "unwind" rows actually are — and why flipping matters less than assumed

Probes `scratch/probe_unwinds.py`, `scratch/probe_unwinds2.py`.

`economic_class = ECONOMIC_UNWIND` and `lifecycle_type = TERMINATION` are
**two disjoint populations**, and neither is what the plan assumed:

| lifecycle_type | economic_class | n | contributes_to_flow |
|---|---|---|---|
| NEW_TRADE | ECONOMIC_FLOW | 2,219,906 | yes |
| TERMINATION | ECONOMIC_FLOW | 50,752 | yes |
| NEW_TRADE | **ECONOMIC_UNWIND** | **36,763** | yes |
| OTHER | ECONOMIC_FLOW | 18,988 | yes |
| TERMINATION | ECONOMIC_UNWIND | 38 | yes |

- The 36,763 `ECONOMIC_UNWIND` rows are `lifecycle_type = NEW_TRADE`. Every
  single one has `effective_date` more than 5 days before `as_of_date`. They
  are the **unwind-as-a-new-offsetting-trade** signature, not TERM actions.
- **97% of them fall in 2024-03..2024-07** (35,689 of 36,828), then the
  detector all but stops: 3–34/month thereafter, with one 746 spike in
  2026-04. `lifecycle_type = TERMINATION` is **exactly zero before 2024-07**
  and 1,600–2,800/month after. The two families are temporally
  complementary — this is an ingest/source regime change around 2024-07,
  not a market change. **Pre-2024-07 tape has no termination events at all.**
- `economic_class_reason` is the same literal string (`§43.2; [Example 1]`)
  for ECONOMIC_FLOW terminations and ECONOMIC_UNWIND alike, so it cannot be
  used to tell them apart.

**Why the missing lineage costs less than the plan feared.** When a customer
unwinds by executing an offsetting swap, the dealer genuinely takes that risk
on at that moment — so counting the offsetting print as new flow is *correct*,
not a bug. And per the ISDA best-practice note, the netting leg is a bilateral
compression, which is **not real-time reported**, so the tape does not
double-count it either. Lineage would buy two things only: sizing partial
unwinds (§43 footnote 41 reports *remaining* notional on a partial, so the
transferred size is `prior − reported` and is unrecoverable from the row), and
a cross-check.

**And a termination can be direction-classified without lineage.** A TERM
print carries the original trade's fixed rate plus the settlement fee, so
repricing the residual swap and comparing NPV to the fee *is* the inference.
Full terminations report the full terminated notional, so they are sizeable.

### F-9. Lineage confirmed absent, three independent ways

- `original_execution_source` = `newt` for **all 2,326,781 rows**;
  `alpha_lag_seconds > 0` for **zero** rows — `alpha_join` never resolves.
- `d2_missing` is NULL on every row; the flag was never populated.
- `canonical_underlier_key` has **30 distinct values** across 2.33M rows —
  it is a coarse product key, not a trade identity. Not a lineage route.

Partially working: `lc_was_amended` 59,260, `lc_was_null_filled` 49,731,
`lc_has_economics_change` 67,144. Not working: everything cross-day.

### F-10. `is_off_market` is itself a crude direction heuristic — do not route on it

`off_market_reason` has exactly three values:

| off_market_reason | n |
|---|---|
| `rate_outlier` | 587,216 |
| `past_effective_with_ufro,rate_outlier` | 194,962 |
| `past_effective_with_ufro` | 113,463 |

So `is_off_market` is largely "the printed rate is far from where we think the
market is" — a coarser version of the quantity being built here. Worse, it does
not agree with the presence of an upfront (flow legs):

| is_off_market | has ufro | n |
|---|---|---|
| False | False | 1,142,183 |
| True | True | 612,132 |
| False | **True** | **275,540** |
| True | **False** | **248,469** |

**Decision D6**: route rate-rule vs upfront-rule on the *presence of an
other-payment amount*, never on `is_off_market`. Carry `is_off_market` as a
provenance flag only.

### F-11. `notional` has outliers too, not just `risk`

`avg(notional)` over TERMINATION rows is 1.96e15 against a median of 61 MM.
The sanity gate must cover notional as well as risk.

---

## Phase 3 — build (2026-08-11)

Interfaces pinned first, then implementations fanned out against them.

| module | state |
|---|---|
| `conventions.py` | done — 35 tests, 17 failed before the polarity fix |
| `types.py` | done — the data contract |
| `snapshot.py` | done — 17 tests, two silent bugs caught while writing |
| `universe.py` / `sanity.py`, `midprice.py`, `probability.py`, `upfront.py`, `krd.py`, `imputation.py`, `lineage.py`, `ladder.py` / `health.py` / `provenance.py` | in build |
| runner + tie-out + written note | after the above |

**The `conventions.py` inversion is worth recording**, because it is the exact
failure mode the module exists to prevent. Going from the base party to the
dealer is one negation; going from pay-polarity to received-polarity is a
second. Two negations are the identity, so
`dealer_received_signs = dealer_sign * o`. The first draft wrote the first
negation and forgot that the second undid it, which inverted **every leg of
every structure at once** — and produced a perfectly plausible result. Caught
only by the frozen-predecessor test.

**Pilot before backfill**: 15–20 days inside 2026-06..07-17, run on *both*
curve sources, then logic tie-out → curve effect → only then 610 days.

## Phase 2 — parallel deep orientation (2026-08-11)

Seven independent probes. Scripts durable in `scratch/`.

### F-12. On a TERM row, `#96 Execution timestamp` is FROZEN at the ORIGINAL trade

From the Part 43/45 Tech Spec, Appendix F Example 3 (PDF p.68), verified against
the rendered page:

| row | Action | Event | `#30` event ts | `#96` execution ts | D1 | D2 |
|---|---|---|---|---|---|---|
| 1 | NEWT | TRAD | 2018-04-01T14:15:36Z | 2018-04-01T14:15:36Z | ABCD006 | — |
| 2 | TERM | ETRM | **2019-12-12T14:57:10Z** | **2018-04-01T14:15:36Z** | ABCD007 | ABCD006 |

`#96` is defined to "remain unchanged throughout the life of the UTI". **So for a
lifecycle print, `#96` is 20 months stale and `#30` carries the unwind time.**
The current snapshot rule (`snap_timestamp(original_execution_timestamp,
execution_timestamp)`) would price a termination against a curve from years
before the event.

Independently confirmed on live data: for the 613 raw TERMs that resolve to a
tape row, the TERM's own Execution Timestamp equals the *original's* execution
timestamp to **<1 s in 95.3%**, <60 s in 99.7%, <1 day in 100%.

**Decision D10**: the pricing clock is `#96` for `NEWT` rows and **`#30` for any
row minting no new UTI** (`TERM`, `MODI`, `CORR`, `EROR`, `REVI`). Rows that mint
a new UTI (`NEWT-NOVA/COMP/CLRG/EXER`) keep `#96`, which equals the event time
for them anyway.

### F-13. The other-payment payer and receiver are genuinely not disseminated

Spec, PDF p.31–32, visually verified:

- `#58 Other payment amount` — "Any value greater than or equal to zero",
  disseminated. **Unsigned.**
- `#61 Other payment payer`, `#62 Other payment receiver` — P43 Reported **N**,
  dissemination cell **empty**. Not disseminated.
- `#100 Prior USI` / `#101 Prior UTI` — reported N. `#102 USI` / `#103 UTI` and
  `#97 Reporting timestamp` — "Do not disseminate". `#29 Event identifier`
  (the compression linker) — reported N.

So `D2` is the **only** public linkage mechanism, and §2.1 of DESIGN.md stands:
the fee magnitude alone cannot give a direction.

**And an absent fee does not mean an at-market trade.** `#57 Other payment type`
is `C` (conditional, required) for **credit** but `O` (optional) for **IR**. This
is a real limit on D6 and is now recorded as such.

Two further D2 traps: it points at the **original**, not the immediately-prior,
dissemination (Example 1: the CORR row's D2 is `ABCD001`, not `ABCD002`) — chains
are a star, not a linked list. And D2 is **blank on every NEWT row including
`NEWT-NOVA`**, so a novation's step-in leg is publicly unlinkable to the
terminated leg.

### F-14. `opa_sign` is direction-blind *by symmetry*, and `dealer_spread_est` is a residual

`SDRUtils/packages/opa_sign_solver.py`. The solver minimises
`min(|Σ sᵢ·opaᵢ − PTP|, |Σ sᵢ·opaᵢ + PTP|)` (`:97`, `:125`, `:147`), so **a sign
vector and its global complement score identically** — the `_select_best`
docstring says so outright (`:56-62`). Global orientation is settled by a
tie-break, not by economics. Verified: `solve_opa_signs([100k, 40k], +60k)` and
the same with `ptp=-60k` both give residual 0 / EXACT.

- `dealer_spread_est` = `result["residual"]` (`:340`) — literally the dollar
  residual, identical to `opa_ptp_residual`. **Not an edge.** The name comes from
  a spec gloss.
- `dealer_spread_bps` = residual ÷ Σ`estimated_pv01`, with `fillna(0)` on the
  denominator, so missing pv01s *inflate* it.
- Across all 351,510 populated rows: `dealer_spread_bps < 0` → **0**;
  `dealer_spread_est < 0` → **0**. And mean bps by `sign(opa_signed_net)` is flat
  (EXACT 0.00233 vs 0.00267). **No directional information at all.**
- No curve, no discounting, no pricer import anywhere in the module.

**So it is an adjacent problem — accounting tie-out, not direction.** The rule
the brief asked for already exists at `stir_flow/classifier.py:75-82` and is
algebraically the two-hypothesis test. DESIGN.md §2.2 confirmed independently.

One real gap: the existing rule reads only `other_payment_ufro`
(`classifier.py:64`), ignoring `_uwin` (unwind settlement) and `_pexh`. Since
`UWIN` is exactly the termination-settlement fee, **terminations currently have
no upfront to compare against.** Fixing that is in scope.

### F-15. Curve repricing works, and there is NO convention bias

200 on-market SOFR outrights over 164 distinct days spanning 2024-03..2026-08,
sampled reproducibly (`hashtext(trade_id) mod 1999 = 7`), strict policy, 200/200
priced:

- **(printed − mid) median +0.0210 bp**, IQR [−0.0956, +0.1700], 40.5% within
  ±0.1 bp, 55.5% above mid.
- Bootstrap 95% CI on the median (25k resamples): **[−0.0015, +0.0463] —
  includes zero.** Sign test 111/200, p = 0.137.
- **No growth with tenor** (−0.021 to +0.057 bp across ≤1Y…10-30Y) — which is
  the signature a day-count/roll/spot-lag error would leave.
- Control at one minute earlier shifts the median by −0.001 bp, so the offset is
  a convention statement, not timing.
- **Placebo**: the same 200 prints against the same wall-minute 7 days earlier
  give median +1.167 bp and IQR width 12.89 bp — an **IQR ratio of 48.8×**. The
  statistic genuinely reads the curve.

The `printed > mid ⇒ dealer received` convention is safe against this curve.
Measured on SOFR in-session on-market outrights only.

**Source string**: `IRSwapsMDP(source="CITIVELO_EXCEL")`, which must be an **RL**
token — `_build_citivelo_excel_curve` gates `_store_eligible` on `backend=="rl"`,
so a `-QL` token never consults the minute store and a strict policy then misses
on *every* request, indistinguishable from a cold store. Curve names are
`USD-SOFR-1D` / `USD-FEDFUNDS-1D`; `config.CURVE_FOR` holds Barchart names and is
not usable here.

**Session branch works** (`scratch/dd04_session_branch.py`), two `CurvePricer`
instances rather than a per-call policy, because the handle cache is keyed on
`(curve_name, ts)` alone. Demonstrated: in-session mids bit-identical to pure
strict; 7/7 hour-00 prints served at 1–97 min lag, none from the future; and on
2026-06-01 a 30-minute *in-session* gap that a global `max_lag=2h` **served at 15
minutes stale while the branch refused it** — the proof the global bound is
wrong. Whole-day sweep of 2026-04-01: strict alone 873/919 minutes, branch
919/919, zero legs lost.

Two traps: `RLIRSwapCurve` exposes `.meta()`, **not** `.meta_data`, so
`getattr(handle, "meta_data", None)` silently returns None and every lag reads as
missing while prices look fine. And **do not normalise snapped instants to UTC** —
an ordinary 20:00 ET snap is 00:00 UTC and trips the midnight guard.

### F-16. The corrupt rows are a `notional = 1e20` sentinel — 55 of them

Not a `risk` defect. All 55 have `notional = 1e20` exactly; 54 also have
`fixed_rate = 9.9` (=990%, a second sentinel). `risk` was computed *correctly
from* the sentinel.

| rate index | n legs | Σ\|risk\| all | Σ\|risk\| ex-sentinel | n sentinel |
|---|---|---|---|---|
| FED_FUNDS | 70,413 | 1.16633e17 | **2.797e9** | 54 |
| SOFR | 2,198,209 | 2.58997e16 | **7.574e10** | 1 |
| total | 2,289,646 | 1.42533e17 | **7.949e10** | 55 |

Dates: 17 `as_of_date`s, 2025-08-11 → 2025-10-17, plus one recurrence
2026-04-15. The tape's own `quality_flags` misses 2 of the 55.

The brief's suggested bound (`|risk|/notional ≈ tenor·1e-4` within 2×) **catches
0 of 55** — their scaled ratio is 1.004–1.006 — and mis-flags 58% of deep
forward-start legs, because `tenor·1e-4` is not the DV01 scale when 37% of legs
are forward-starting. The annuity form `E = N·(A(f+T) − A(f))·1e-4` gives a
median ratio flat at 1.00 in every tenor band. `risk` is also quantised to $100.

Predicate at `scratch/risk_sanity.py`, `--validate` passes: 14 known-answer
synthetic cases, 5 mutation tests, **55/55 known-broken flagged**, 0.260% false
positive on 50k random legs, and 0.000% on deep forward-starts where the naive
bound gives 58.08%.

### F-17. The cap schedule: nine bands, two vintages, changeover 2024-10-07

Derived from the capped prints themselves (their `notional` **is** the cap), then
checked against the regulation afterwards.

| tenor band | V1 cap (→2024-10-04) | V2 cap (2024-10-07→) |
|---|---|---|
| ≤46d | $6.4bn | $17bn |
| 46d–3m | $2.1bn | $7.5bn |
| 3–6m | $1.2bn | $2.0bn |
| 6m–1y | $1.1bn | $1.7bn |
| 1–2y | $460mm | $1.1bn |
| 2–5y | $240mm | $650mm |
| 5–10y | $170mm | $470mm |
| 10–30y | $120mm | $250mm |
| >30y | $75mm | $160mm |

p10 = p50 = p90 = the cap in every band, purity 96.3–100%. Last V1 print
2024-10-04, first V2 print 2024-10-07, simultaneous across all nine bands, zero
overlap — which is the CFTC Division of Data's recalibrated block-and-cap sizes
taking effect 2024-10-07, to the day.

Tail fit: **censored MLE** (sub-cap observations plus the observed capped count
as mass at the cap), lognormal, threshold `u = C/4`. It reproduces the observed
capped count to ±19% in every cell; truncation-only MLE is off by −72% to
+2400%. The infinite-mean trap **did fire** — Pareto gives α < 1 in 10 of 18
cells at `u = C/10` — and was correctly diagnosed as `[C/10, C)` being the *body*
of the distribution, not a monstrous tail; at defensible thresholds median α is
1.32–1.44. KS favours lognormal in 13 of 18 cells; AIC cannot discriminate over a
single decade.

### F-18. Unwind lineage IS recoverable — but the production cache is unusable for it

`SDRUtils/data/builder.py::DTCCFetcher`, DTCC PPD over HTTP. Measured on the
unfiltered week 2026-06-15..18 (100,079 rows):

- **Pointer presence 17,305 / 100,079 = 17.29%.** By action: NEWT 0.00%, and
  MODI / CORR / TERM / EROR / REVI all **100%**. (Counter validated against a
  known answer first: corrections must reference what they correct.)
- Resolution to `arbs_usd_swap_tape_legs_v3`, funnelled to the population that
  matters: all TERM 613/3,659 = 16.8% → ETRM 16.6% → +USD 45.7% → +USD-swap UPI
  70.6% → +own exec ≥ tape start **428/508 = 84.25%**. By product,
  **`NA/Swap OIS USD` 382/415 = 92.0%**. Ceiling is the tape's own NEWT ingestion
  rate on the same week (OIS 98.97%).
- These are **single-hop lower bounds**: of 80 unresolved addressable pointers,
  43 point at another TERM (chained partials) and 24 at NEWT prints the tape
  never ingested.
- **Reach-back**: ≤1 d 75.5%, ≤63 d 90.7%, ≤252 d 95.6%. A ~90-day store holds
  90% of the flippable population, ~1 year ~96%; the tail is unbounded (max 25
  years, and 5.6% of TERMs reference a print older than the tape — which
  resolved 0/206, a clean internal consistency check).

**The blocking defect**: `fetch_historical_reports` masks each day's frame on
`Execution Timestamp.dt.date` **before** persisting
(`builder.py:422-424`, `:1141`), and the daily service runs `start==end==D`. So
the cached parquet keeps only rows whose *execution* date equals the file date —
and lifecycle rows carry the **original's** execution date (F-12). Measured over
the same four days: **8,210 of 100,079 rows lost (8.20%), including 1,489 of
3,659 terminations = 40.7%**, and 93.3% of exercises. `ignore_cache=True` does
not recover them — the mask is inside the function the ignore-cache path still
calls. **Those rows were never written; the existing `sdr_cache` cannot be used
for lineage.** Fetch the zips directly.

Also: a full termination restates almost nothing — on 428 resolved TERMs,
`Notional amount-Leg 1` is present on only **3.7%**, `Fixed rate-Leg 1` on 57.2%,
`Other payment amount` on 15.7%. The original's notional must come from the tape.

### F-19. A REAL dissemination timestamp is recoverable

The cumulative daily CSV has no publication column, but:

- **The intraday slice ZIP member's mtime is the publication clock.**
  Known-answer validated against the slice listing's `dissemDTM` on 10 live
  slices: zip mtime (ET→UTC) sits 2–4 s before `dissemDTM`, median |Δ| 3.0 s,
  max 4.0 s, **10/10**.
- Slices are ~10 s apart, ~1,333/day, and **historical slices are still served**,
  so the ~10-second publication clock is recoverable for past dates by
  enumerating `CFTC_SLICE_RATES_YYYY_MM_DD_<seq>.zip` even though the listing API
  only shows 24 h.

**This upgrades the availability clock from a legal-delay estimate to a measured
bound** — the thing D3 assumed was impossible. Revising D3 accordingly.

---

## F-20. THE HEADLINE: the existing classifier's 71% PAID is a CURVE ARTEFACT

The adversarial pass ran the one query nobody else had, on
`arbs_stir_direction_v1`, `RATE_VS_MID`, n = 49,765:

| | Barchart `Q12xM12STIRT` (old pipeline) | Citi minute (F-15) |
|---|---|---|
| % printed above mid | **21.70%** | 55.5% |
| median s2m | **−0.4836 bp** | +0.021 bp |
| median \|s2m\| (SOFR) | **0.7071 bp** | ~0.13 bp |
| within ±0.1 bp (SOFR) | **5.43%** | 40.5% |

**The old mid is biased high by ~0.5 bp and its dispersion is ~7× wider.** Four
independent internal controls in the same table confirm the instrument, not the
flow:

1. **Monotone tenor gradient**: 3M −0.136 → 1Y −0.246 → 2Y −0.524 → **3Y
   −1.237 bp**. Sign and shape are the uncorrected futures→forward convexity of
   a STIR-futures-built curve. F-15 used "no growth with tenor" as Citi's
   all-clear; Barchart fails that exact test over the *overlapping* tenors.
2. **The fly cancels it.** `FLY_VS_MID` median s2m = **0.0000**, split 198 PAID /
   194 RECEIVED. `SPREAD_VS_MID` (one difference) median −0.245, 70% PAID.
   `RATE_VS_MID` (no difference) median −0.484, 78% PAID. Level bias ~0.5 bp,
   slope ~0.25 bp, curvature ~0. Textbook.
3. **The one method that never touches the curve is balanced.** `TICK_RULE` =
   5,940 RECEIVED / 5,245 PAID (**53/47**). Every curve-using method is 69–78%
   PAID.
4. **IMM buckets are broken outright**: `IMM_2Y` median **−6.84 bp** (4.07% above
   mid), `IMM_3Y` −6.83, `IMM_1Y` −5.57 — ~3,600 rows labelled PAID with
   deviations large enough to score HIGH confidence. Fed Funds meeting buckets
   flip sign across meetings (`FOMC_APR26` +1.32 / 82.4% above vs `FOMC_JUL26`
   −0.68 / 18.1% above), so the MIX23 meeting steps are misplaced.

**Consequences.**

- The 37.4% `curve_suspect_trade` rate and 57.8% LOW confidence are symptoms of
  the bias, not of hard trades. Excluding those rows from a tie-out metric
  removes exactly the rows where the old curve is worst, which *inflates*
  measured agreement.
- `NPV_VS_UPFRONT` is 69.1% PAID off the same curve's NPV, so off-market rows are
  contaminated through a second channel.
- Any downstream conclusion drawn from `arbs_stir_direction_v1` — including the
  dealer-ladder programme's "no signal" verdict — rests on labels that are 78%
  one-way from a half-basis-point curve error. **This is worth telling the desk
  regardless of what this task produces.**

### The tie-out design has to change (supersedes the earlier D6 gate)

The earlier plan was "reference = a fresh dry-run of frozen `stir_flow` on
today's stack", gated at ≥97% agreement. That reference uses the same Barchart
curve. Moving from 78.3% PAID to ~44.5% PAID is a **≥34 pp label shift on the
`RATE_VS_MID` population alone** — so the gate cannot be met by a correct system,
only by one that reproduces the bias.

**D11 — decompose the tie-out into two measurements that vary one thing each:**

| measurement | holds constant | varies | expectation |
|---|---|---|---|
| **logic tie-out** | the curve (Barchart `Q12xM12STIRT`, old snapshot rule) | old code → new code | ≥99% on decisive rows. A disagreement here is a **bug**. |
| **curve effect** | the code (new) | Barchart → Citi minute | a large, *quantified* label shift. This is a **finding**, not a failure. |

The new package therefore has to be able to run on the old curve source. It can:
`CurvePricer` already takes the `mdp` and the curve name, so both are
constructor arguments and neither is baked in.

**And the tie-out key is only valid for OUTRIGHTs.** The old system assigns one
direction per *unit*; a per-leg model gives the two legs of a curve trade
opposite signs, which is economically right and makes the join undefined for the
9,165 multi-leg units. Keeping the **unit** as the primary inference object (one
inferred bit, leg signs derived — DESIGN.md §3) is what preserves the join;
per-leg KRD hangs off the unit, it does not replace it.

## F-21. Further items the adversarial pass surfaced

- **`1e20` is spec-defined, not corrupt.** `#31` is `Num(25,5)` and footnote 42
  says `'99999999999999999999.99999'` is accepted "when the value is not
  available at the time of reporting"; `fixed_rate = 9.9` is the same idea. So
  the 55 rows are **placeholder prints whose economics arrive later in a CORR or
  MODI** — and the tape ingests NEWT only. Bigger version of the same point:
  in one raw week, **CORR 4,810 + EROR 1,242 = 6,052 prints against 82,774 NEWT
  (~7.3%), all 100% pointer-bearing, and the v3 tape applies neither.** `EROR`
  means the trade legally never existed. Out of scope to fix; in scope to
  measure and exclude.
- **`NPV_VS_UPFRONT` may invert on capped prints.** Capping understates notional
  by 1.6–4.0×. The spec requires the SDR to "proportionally scale other
  applicable fields" but does not enumerate them, delegating to the SDR's own
  procedures. If `#58` is *not* scaled, `|NPV|` shrinks 1.6–4× while `U` stays
  fixed and `upfront < |npv|` **flips**. Deterministic, not noise, on the
  capped ∩ off-market intersection (order 500–600 units). One query settles it:
  `|NPV|/U` capped vs uncapped.
- **`NEWT-EXER` is off-market by construction with no upfront.** A swaption
  exercising into a swap prints at the **strike**, arbitrarily far from mid, and
  carries no fee — so an upfront-presence test calls it on-market and
  `RATE_VS_MID` produces a large, confident, meaningless deviation. ~374/week.
  Same argument for `NEWT-NOVA` (~435/week), which is a dealer-to-dealer risk
  transfer counted as customer flow.
- **Publication lag is measurable and is ~5 minutes.** NEWT/OIS/USD median
  **5.23 min**, p95 **11.3 min** — against a tape `report_lag_seconds` of 0,
  which is Event−Execution and not a publication delay at all.
- **PB mirror de-duplication is unavailable where it is needed.** `#99 Prime
  brokerage transaction indicator` is `NR` when `[Cleared] = 'Y'`, and most of
  the tape is cleared. PB double-counting is therefore **unbounded**, not
  merely unmeasured.
- **Compression and allocation are invisible**, so a ladder accumulated from
  tape flow carries an unbounded, monotone error with no offsetting print. The
  ladder needs a decay or reconciliation term, or an explicit statement that it
  is a *flow* series and not an inventory.
- **Remedy-1 unwinds can never be seen.** The 92% lineage coverage is coverage of
  ISDA Remedy 2 only; a Remedy-1 unwind prints as an ordinary at-market
  offsetting trade with no TERM and no pointer.
- **Both cost projections are needed, and repricing is the binding one**:
  19.4 min for risk vs **8.7 h for mid/NPV**, so the end-to-end single-thread
  cost is ~8.7 h, not 19 minutes.

---

## Decisions

| # | decision | why | reversible? |
|---|---|---|---|
| D1 | New package `SDRUtils/dealer_direction/`; `stir_flow` frozen | the tie-out needs the old classifier runnable unchanged | yes |
| D2 | Lineage from a raw-SDR sidecar, not a tape column | avoids delete+rewrite of 610 prod days | yes |
| D3 | Availability = `visibility_timestamp` (Appendix C); event+exec both carried | F-3: event ≈ execution, so event time is not an availability bound | yes |
| D4 | Ladder built from repriced KRD; tape `risk` never summed | F-4 | yes |
| D5 | `p` is p(customer paid fixed) = p(dealer received fixed) everywhere | one convention, matches persisted ladder sign | no (pinned) |
| D6 | Route rate-rule vs upfront-rule on the presence of an other-payment amount, never on `is_off_market` | F-10: `is_off_market` is a rate-outlier heuristic that disagrees with upfront presence on 524k legs | yes |
| D7 | Unwind-as-new-trade prints are classified as ordinary flow, not netted away | F-8: the dealer really takes that risk on, and the offsetting compression is not publicly reported | yes |
| D8 | Terminations classified by the upfront rule and kept as a **separate series** | F-8: sign is right but is driven by seasoned P&L, not by bid-offer, so the confidence model does not transfer | yes |
| D9 | **KRD comes from rateslib's own delta ladder** — `Solver` + `Portfolio(...).delta(solver=...)`. No hand-rolled cashflow bucketing. | user instruction, 2026-08-11. Also the right call on the merits: rateslib's delta is risk to the *calibrating instruments*, so the bucket set is defined by the instruments we choose and the Jacobian comes out of the calibration for free — which is exactly the transformation a desk wants, and it reuses `MDP/IRSwaps/BARCHART_STIRF/risk.py::build_delta_risk_ladder`. | no (instructed) |

### D9 in practice

`instrument.delta(solver=...)` returns sensitivity **to the solver's calibrating
instruments**, so the bucket set *is* the instrument set. Consequences that shape
the runner:

- **One solver per (rate_index, as_of_date)** — *not* per curve-minute, and not
  because delta amortises. **Correction to the first statement of D9**, which
  said `Portfolio.delta` "amortises over arbitrarily many positions": measured,
  it does not. 2.2 ms for one swap, 0.59 ms/swap at 100, and *degrading* to
  1.04 ms/swap at 500 (pandas concat per instrument). Batching buys ~2×, not an
  order of magnitude, so chunk at ~100 and stop.

  The real fix is the solver count. There are 547,338 distinct
  (index, exec-minute) pairs — about **4.25 legs per curve-minute** — so a
  per-minute solver pays the 42.2 ms build essentially *per trade* (~6.4 h).
  The Jacobian was measured as a per-**day** object (`max|dJ|` 0.0030 within a
  day, 0.0022 over two weeks), which collapses ~547k builds to ~1,220. Mids and
  NPVs still come per-minute through `CurvePricer`; only the risk basis is
  daily. The per-day approximation is re-verified across an FOMC date and a
  curve-shape break, which the original measurement did not cover.
- **Bucket set**: the Basel GIRR vertices (0.25, 0.5, 1, 2, 3, 5, 10, 15, 20,
  30y) as the spine, extended with the short-end structure the tape actually
  carries (1M, 2M, 3M, 6M, 9M) and a coarse 20–30y+ bucket, since the brief
  accepts coarseness at the long end rather than implied precision.
- **No PCA.** It reduces dimension against a historical covariance, is not
  stable out of sample, and a single PC bucket is not hedgeable with one
  instrument. The consumer wants a hedge-ratio projection, which is a Jacobian
  change of basis — and rateslib gives that directly.

---

## F-6. The corrupt `risk` column is really a corrupt `notional` (55 rows)

Probes `scratch/probe_risk_orient*.py`, `scratch/probe_risk_partA*.py`.
Predicate + validation harness: **`scratch/risk_sanity.py --validate`**.

`sum(abs(risk))` over ECONOMIC_FLOW legs, before and after removing the
55 rows that carry `notional = 1e20`:

| rate index | n legs | sum abs(risk) all | ex-sentinel | n sentinel |
|---|---|---|---|---|
| FED_FUNDS | 70,413 | 1.16633e17 | **2.797e9** | 54 |
| SOFR | 2,198,209 | 2.58997e16 | **7.574e10** | 1 |
| BASIS | 15,182 | 9.027e8 | 9.027e8 | 0 |
| OTHER | 5,842 | 5.233e7 | 5.233e7 | 0 |
| **total** | 2,289,646 | **1.42533e17** | **7.949e10** | 55 |

55 rows are **99.99994%** of the aggregate. `platform_identifier = 'BILT'`
reproduces the FED_FUNDS total exactly and `XXXX` reproduces the SOFR total
exactly, which is why the platform breakdown looked like two bad venues.

**The defect is in `notional`, not in `risk`.** All 55 rows have
`notional = 1e20` exactly, and `risk` is computed *correctly* from it: the
ratio `abs(risk)/(notional*A(T)*1e-4)` on those rows is 1.004-1.006. A ratio
test of the form `abs(risk)/notional ~ tenor*1e-4 within 2x` therefore catches
**0 of 55**. Measured, not argued.

54 of the 55 carry a **second** sentinel, `fixed_rate = 9.9` (=990%), all on
BILT / FED_FUNDS. The 55th is XXXX / SOFR with a plausible 3.59% rate.
The tape's own `quality_flags` flags 53 as OFF_MARKET and misses 2.

**Ongoing, not a one-off.** 17 as_of_dates: 2025-08-11 to 2025-10-17 (16 days,
1-8 rows each, ~0.1% of that day's legs) then a single recurrence on
2026-04-15. Nothing before 2025-08-11 across 610 days.
Chart: `scratch/risk_sentinel_by_date.png`; rows: `scratch/risk_sentinel_rows.csv`.

### Two calibration facts the predicate is built on

1. **`risk` is quantised to $100.** All 2,289,189 non-null flow values are
   integer multiples of 100; the smallest non-zero value is exactly 100. A
   purely multiplicative band therefore flags every small print whose true
   DV01 is under ~$50. With an additive $100 allowance, rows above the
   2x band go from 253 to **0**.
2. **`tenor_years * 1e-4` is the wrong scale.** DV01 per unit notional is an
   annuity, and 37% of flow legs are forward-starting. Using
   `E = notional * (A(f+T) - A(f)) * 1e-4` with `A(x) = (1-exp(-0.04x))/0.04`,
   the median ratio is flat at 1.00 across every tenor band instead of sliding
   0.99 -> 0.59. The naive bound flags **58.1%** of forward-start legs and
   1.9% of >25y legs; the annuity bound flags 0.000% and 0.005%.

### Residual defect classes after the sentinel

| class | n | note |
|---|---|---|
| `notional >= 1e11` (sentinel) | 55 | largest legitimate notional on tape is 2.86e10 |
| `abs(fixed_rate) >= 1.0` | 1,465 | see F-8 |
| `risk IS NULL` | 402 | |
| `risk = 0` with E[DV01] > $300 | **0** | all 16,605 zeros are sub-quantisation |
| `abs(risk) > 2E + 100` | **0** | |
| `abs(risk) < 0.5E - 100` | 4,878 | 0.21%; mechanism NOT identified |

`risk_sanity.py --validate` passes: 55/55 known-broken flagged (including both
rows the tape's own flags missed), 0.260% false positive on 50k random flow
legs, 0.000% on deep-forward-start legs.

**Consequence for the ladder**: unchanged from F-4 - never sum tape `risk`.
Use `risk_sanity.flag_risk_implausible` as the exclusion gate on any tape-risk
aggregate, and drop the 55 sentinel rows from the trade universe outright,
since their notional is unusable for a repriced KRD too.

---

## F-7. Notional right-censoring: the cap schedule has TWO vintages

Probes: `scratch/partB_cap_schedule.py`, `partB_tail_fit.py`,
`partB_sensitivity.py`, `partB_final.py`.

`is_capped` == `is_notional_capped` exactly, on 68,946 of 2,289,646 flow legs
(3.01%). `notional_source` is **NULL on all 2,326,781 rows** - confirmed, it
never says anything.

The cap is a function of tenor at **nine** Part 43 bands, not the four the
brief assumed, and **the whole schedule was re-set during the sample**. Last
day of the old values 2024-10-04, first day of the new 2024-10-07 (the
weekend between); the switch is simultaneous across all nine bands and
completely clean - see `scratch/partB_cap_schedule.py` output S3.

The date was derived from the data alone and then checked externally: the
CFTC Division of Data's updated post-initial Part 43 block and cap sizes,
recalibrated on calendar-2023 data, took effect **2024-10-07**
([CFTC release 8913-24](https://www.cftc.gov/PressRoom/PressReleases/8913-24)).
The measured switch is that rule change, to the day.

| tenor band (empirical edges) | V1 cap (to 2024-10-04) | V2 cap (from 2024-10-07) |
|---|---|---|
| 0 - 0.12y (<=46d) | $6.4bn | $17bn |
| 0.12 - 0.30y (46d-3m) | $2.1bn | $7.5bn |
| 0.30 - 0.54y (3-6m) | $1.2bn | $2.0bn |
| 0.54 - 1.04y (6m-1y) | $1.1bn | $1.7bn |
| 1.04 - 2.25y (1-2y) | $460mm | $1.1bn |
| 2.25 - 5.25y (2-5y) | $240mm | $650mm |
| 5.25 - ~10.5/11y (5-10y) | $170mm | $470mm |
| ~10.75 - 31y (10-30y) | $120mm | $250mm |
| 31 - 41/45y (>30y) | $75mm | $160mm |

Band purity 96.3-100% (fraction of capped prints sitting *exactly* on the
band cap). Capped prints pile up on a single discrete value per cell: p10 =
p50 = p90 = the cap in every band. Cap enforcement is imperfect but tiny -
~730 uncapped prints (0.03%) exceed their band cap, the worst a $28.6bn
1.5y print on 2024-03-11.

### Tail fits

`partB_tail_fit.py --selftest` recovers a known alpha to <1% for
alpha in {0.8, 1.2, 1.8, 2.5} where the naive Hill estimator is +53%/+23%/+6%
biased; recovers lognormal (mu, sigma); reproduces E[X|X>C] to <6% and the
capped count to <3%; and proves the grouped-frequency path used on the tape is
identical to the raw path.

Two findings that decide which model feeds the headline:

* **Pareto returns alpha < 1 - an infinite mean - in 10 of 18 cells at
  u = C/10.** That is not a monstrous tail, it is evidence that [C/10, C) is
  the *body* of the notional distribution. At defensible thresholds
  (u = C/2, C/4, cell-q0.90, q0.95) the median alpha is 1.32-1.44 and the mean
  exists in 16-17 of 18 cells. The Pareto is reported as a band, not the
  headline.
* Over the single decade [u, C) the two families are near
  likelihood-equivalent (AIC gap 11 on a loglik of 3.7e6 in the selftest);
  **KS is the discriminating statistic, and it favours the lognormal in 13 of
  18 cells.** Absolute KS is large (0.07-0.28) for everything because notional
  is rounded onto a round-number lattice.

The **censored** MLE (sub-cap observations plus the observed capped count as
mass at C) is the estimator used: it reproduces the observed capped count to
within +-19% in every cell, where the truncation-only MLE is off by -72% to
+2400%.

### The headline number

Lognormal censored, u = C/4, E[notional | notional > C] / C = 1.6-4.0 by cell:

| coarse bucket | n capped | imputed share of NOTIONAL | imputed share of DV01 proxy |
|---|---|---|---|
| <=2y | 22,340 | 30.3% | 21.8% |
| 2-10y | 36,170 | 15.0% | 16.6% |
| 10-30y | 9,006 | 10.3% | 9.2% |
| >30y | 103 | 8.4% | 8.2% |
| **overall** | **68,946** | **27.2%** | **15.4%** |

Sensitivity across six thresholds (u = C/2, C/4, C/10, C/20, q0.90, q0.95):
imputed DV01 share **10.6% - 16.0%**, imputed notional share 16.3% - 27.2%.
Individual cells swing much more than the aggregate (the 5-10y V1 cell moves
1.8x-4.0x); the aggregate is the number to quote.

**Model-free cross-check**: capped prints carry 1.165e10 of the 7.948e10 sane
`sum(abs(risk))` = **14.66% of DV01 at the cap value**. With a multiplier of
2.0-2.1 that alone implies an imputed share of 12.8-13.9%, which brackets the
fitted 14-15.4% without using the fit at all.

### What else the cap censors

* **`risk` is computed FROM the capped notional, so it is right-censored too.**
  The annuity ratio is identical capped vs uncapped (p05/p50/p95 =
  0.978/1.003/1.033 vs 0.968/1.003/1.039). Any DV01 built from tape `risk`
  inherits the same 3.0%-of-legs / ~14.7%-of-DV01 censoring.
* `cap_band_violation` is TRUE on 68,880 of 68,946 capped legs and FALSE on
  every uncapped leg. It is a **degenerate synonym for `is_capped`**, not a
  defect signal.
* Capped legs are **5x more likely to have a NULL `fixed_rate`** (5.9% vs
  1.2%) - the direction inference loses those outright.
* `other_payment_amount` populated 40.5% capped vs 39.1% uncapped - no effect.
  `schedule_truncated` 0 everywhere. Censoring is not venue-selective
  (D2C 3.00%, D2D 3.11%). Cap is NOT block: 32,947 capped legs are not blocks
  and 19,111 blocks are not capped.

---

## F-8. INCIDENTAL: 1,465 flow legs carry a `fixed_rate` that cannot be a rate

`abs(fixed_rate) >= 1.0` (i.e. >= 100%) on 1,465 of 2,289,646 flow legs,
ranging -40.05 to 785.5, concentrated on XXXX (1,134), XOFF (224) and
BILT (83). The tape already flags 1,445 of them `rate_outlier`; ~20 it does
not. `fixed_rate` is otherwise a decimal fraction (flow median 0.0394).
These rows cannot be repriced against mid and must be excluded from the
direction inference, not merely down-weighted.

---

## Open questions

- [ ] What exactly does `opa_sign` solve for, and does it already answer the
      off-market direction question?
- [ ] Cost of a per-unit key-rate DV01: solver bump vs analytic cashflow
      bucketing. Decides whether 1.5M units is feasible.
- [ ] Which unwinds carry a resolvable lineage pointer in the raw slices?
- [ ] `tau` estimator beyond 3y where there is no tick lattice.
