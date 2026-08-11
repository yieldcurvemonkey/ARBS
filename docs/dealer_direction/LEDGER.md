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

---

## Open questions

- [ ] What exactly does `opa_sign` solve for, and does it already answer the
      off-market direction question?
- [ ] Cost of a per-unit key-rate DV01: solver bump vs analytic cashflow
      bucketing. Decides whether 1.5M units is feasible.
- [ ] Which unwinds carry a resolvable lineage pointer in the raw slices?
- [ ] `tau` estimator beyond 3y where there is no tick lattice.
