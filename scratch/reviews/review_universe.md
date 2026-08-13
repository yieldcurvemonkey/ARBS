## Adversarial review — `universe` module (`universe.py`, `sanity.py`, `tests/test_dealer_direction_universe.py`)

Worktree `C:\Users\chris\clee\ARBS-dd`. Baseline **90 passed**. Evidence scripts left in `C:\Users\chris\clee\ARBS-dd\scratch\`: `rev_universe_repro.py` (R1–R10), `rev_universe_mutate.py` (mutation sweep), `rev_universe_db{,2,3,4}.py` (Q0–Q42, read-only prod), `rev_sign_trace.py`. **No thresholds relaxed, no exemptions added, no file left modified** — the sweep snapshots bytes, patches, runs pytest, restores and asserts sha256 equality; post-restore run is 90 green and `git status` shows the three files untracked-new only.

---

### 1. Sign errors — CLEAN

Traced by hand with numbers (`scratch/rev_sign_trace.py`). 2s5s10s FLY fed to `build_universe` in the wrong row order (BACK, BELLY, FRONT):

- `annotate_legs` orders it `['FRONT','BELLY','BACK']`, `iloc[1]` = BELLY ✓ (the assumption `conventions.base_orientation` documents at `conventions.py:118`).
- `o = base_orientation(FLY,3,RULE_RATE) = (-1,+1,-1)`; `q = (-1,2,-1)`; `sign(q)==o` ✓.
- traded (3.90, 4.06, 4.20)% → `P = 2.0000` bp; mid (3.90, 4.05, 4.20)% → `P = 0.0000` bp; deviation **+2.0000 bp**.
- `dealer_side(+2.0) = +1 = DEALER_RECEIVED`.
- `dealer_received_signs(FLY,3,RULE_RATE,+1) = (-1,+1,-1)` — identical to frozen `ladder_conventions.dealer_leg_signs("FLY",…,"RECEIVED",3) = [-1,1,-1]`.
- Reading: customer paid the belly 1bp above mid → dealer received the belly → dealer long belly duration → `delta_dv01 > 0`. Matches the pinned convention, and `signed_weight(0.5)=+0.00`, `(0.8)=+0.60`, `(0.2)=-0.60`.

CURVE (`(-1,+1)`, dev +1bp → side +1 → `(-1,+1)`) and the upfront frame (`(1,)*n` for n=1,2,3,5) also reproduce the frozen function exactly. The universe module's only sign surface is the leg ordering that fixes `iloc[0]`/`iloc[1]`, and that is correct and pinned (removing `_eff` or `leg_order` from `_SORT_KEYS` goes red). **No sign defect found.**

---

### 2. Tests that cannot fail

**26 mutations listed, 25 run (1 anchor skip), 18 stayed GREEN.**

**2.1 `universe.py:626` — the UWIN-outranks-UFRO-on-lifecycle rule is unpinned.** `take = (uwin > 0) & (u["is_lifecycle"] | (ufro <= 0))` → `(uwin > 0) & (ufro <= 0)` stays green (M6). `resolve_upfront`'s docstring spends a paragraph on this precedence; no test builds a lifecycle unit carrying *both* components, so the branch the rule exists for is never exercised. LIVE-latent: Q10b measures 0 such rows today.

**2.2 `universe.py:526-532` — every gate `any()` can become `all()` undetected.** M35 (`not_flow`), M36 (`exer_nova`), M37 (`nonconstant`), M38 (`risk_bad`), M43 (`no_rate`), M44 (`bad_index`) all green; only `is_block/is_capped` (M39) goes red. `test_dealer_direction_universe.py:228 test_exclusion_is_a_unit_property_not_a_leg_property` names the invariant ("one bad leg condemns the package") but covers only `bad_index` — and it passes with `bad_index` on `all()` because the `n_index > 1` gate catches its case instead; M1 shows dropping `n_index > 1` is *also* green because `bad_index` catches it. Two redundant gates, neither pinned, and the test cannot tell which fired. **LIVE reachability:** Q20 finds 136 multi-leg packages where some-but-not-all legs carry a NULL `fixed_rate`, and 107 where some-but-not-all carry a NULL `risk` (populations may overlap); an `any→all` slip silently admits those and prices them with a missing rate/risk.

**2.3 `universe.py:240-255` — `on_facility` is untested except incidentally.** M2 (off-facility codes → `True`) green: BILT 325,595 + XXXX 51,674 + XOFF 29,051 legs would move from +30 min to +1 min visibility with nothing red. M24 (unrecognised → `False` instead of `None`) green, defeating the exact `None` behaviour the docstring at `:240-247` argues for. No test calls `on_facility` at all.

**2.4 `universe.py:746-756` — `_pybool` reducible to `bool(v)` (M32, green)**, losing the `None` the docstring exists to preserve.

**2.5 `sanity.py:92` — `FLAT_YIELD 0.04 → 0.02` is green (M42).** The single calibration constant the whole `sanity.py` docstring justifies with a measured tenor-band table (1.009/1.000/0.999/1.006/1.003/1.001) is pinned by nothing.

**2.6 `sanity.py:194` — `RISK_ZERO_MATERIAL`'s `3.0 * quantum → 300.0 * quantum` is green (M9).** That threshold governs the 17,020 zero-`risk` admitted legs (Q29) and `3.0` is the one constant in the file with no measurement behind it.

**2.7 `universe.py:369-378` — precedence between `EXCL_PRICING_ERROR` and `EXCL_RISK_IMPLAUSIBLE` is swappable (M4b, green).** Only the top of the tuple (`NOT_FLOW`) and the BASIS/`NO_FIXED_RATE` pair are pinned.

**2.8 `universe.py:301` — dropping `"Custom"` from `NON_CONSTANT_SCHEDULES` is green (M25).** 11,960 flow legs; the parametrised test (`test:198-199`) covers only `Amortizing` and `Accreting`.

**2.9 Also green, but no-ops on today's tape (LATENT):** M3 (swap the `CME_TERM_SOFR`/`MIXED_INDEX` detail strings — no test asserts a detail except the sentinel one), M5 (delete the mixed-platform venue guard at `:539` — Q12 measures 0 packages mixing platform), M7 (drop `.abs()` from PTP at `:611`), M1 (drop the `n_index > 1` gate — Q12 measures 0 packages mixing index).

**2.10 `tests/test_dealer_direction_universe.py:628` — `test_the_briefs_own_bound_catches_none_of_the_sentinels` pins nothing.** It computes `abs(r)/(n*t*1e-4)` on three literals and asserts `0.5 < naive < 2.0`. It imports nothing from `sanity` and passes under every mutation of the module. It is documentation wearing a test's clothes.

**2.11 `sanity.py:379-402` — `_validate` section 4a is a tautology.** The query is `WHERE notional >= 1e11`; `NOTIONAL_SENTINEL` is defined at `:191` as `|n| >= NOTIONAL_ABS_MAX` with `NOTIONAL_ABS_MAX = 1e11` (`:95`). "flagged implausible: 55 (100.0%)" and the `not fb["is_risk_implausible"].all()` failure check cannot come out any other way; the `missed_by_tape` assertion at `:401` inherits the same circularity. The only non-circular content in 4a is the median-ratio line and the 4d head-to-head.

**2.12 `sanity.py:342-353` — `_validate` section 3 is mis-titled.** Headed "SCALAR vs VECTORISED (one predicate, two call shapes)", it compares `scalar` against `want` (the expected list), not against the vectorised `got`. It re-runs section 1 through a second entry point rather than comparing the two shapes to each other.

**Mutations that correctly went red** (so these areas *are* pinned): M8 (drop `INVOICE_SWITCH`), M10 (`RISK_QUANTUM → 0`), M11 (`BAND_HI → 50`), M12 (visibility from raw #96 instead of the pricing instant), M39 (`is_block/is_capped` any→all), M40 (`INPUTS_MISSING` disabled), M41 (`RISK_NULL` disabled).

---

### 3. Claims no measurement supports

**3.1 `universe.py:11-14` — the headline number measures a different filter.** "``config.SUB3Y_HORIZON_DAYS = 1105`` discards **69.7% of flow legs** (1,595,321 of 2,289,646)." The filter named is `stir_flow/trade_selection.py:65,79`: `expiration_date > as_of_date + 1105 days`. Measured on `economic_class='ECONOMIC_FLOW' AND contributes_to_flow` (Q30): that filter discards **1,671,827 = 73.0%**. `1,595,321` reproduces exactly as `tenor_years > 3.02` — a proxy, not the cutoff. Understated by 76,506 legs / 3.3pp, in the module's opening sentence and in `_RELAXATIONS` (`:1051`).

**3.2 `universe.py:35-37` and `:1055-1056` — the stated evidence for replacing the label token is false.** "REPLACED the ``Amortizing`` label token with ``upi_notional_schedule`` (the token caught 15,527 of 35,470)." Measured (Q40), `leg_tape_label LIKE '%Amortizing%'` vs `upi_notional_schedule='Amortizing'`: **35,470 / 35,470** on `contributes_to_flow`, 35,471/35,471 on all rows, 34,656/34,656 on `ECONOMIC_FLOW` — a perfect 1:1 in every population. The token misses no amortiser. The replacement is still the right call (the schedule column additionally catches Custom 11,960 and Accreting 1,507), but the measurement quoted for it does not exist. Tape drift is not an excuse: every other quoted number in the module reproduces to the digit (2,289,646; 1,595,321; TREU 25,192; BMTF 20,678; 98.85% MAC; 55 sentinels; 15,026 MAC packages; the whole `rate_index_clean` table).

**3.3 `universe.py:148-152` — "none appears on this tape" is false.** Of the FX/NDF codes deliberately not pre-loaded, **`CBNL` is on the tape with 2 legs** (Q14). The docstring's own stated consequence ("if one ever did, an unrecognised FX venue on a USD IRS tape is something to look at rather than to silently absorb") is exactly what happens: it falls to `VENUE_UNKNOWN` and nothing looks at it.

**3.4 `universe.py:25-27` — wrong population.** "32,842 flow legs carry ``leg_tape_label`` containing ``"CME Term"`` while ``rate_index_clean`` reads ``'SOFR'``". Measured (Q42): that pair is 32,842 over **all rows**; over `ECONOMIC_FLOW` it is 32,573. The gate at `:456` fires on the label alone regardless of index, so it actually catches 33,217 flow legs.

**3.5 `universe.py:117-118` vs `:451` — the evidence table's population is not the code's.** The venue counts reproduce *exactly* — but only under `economic_class='ECONOMIC_FLOW' AND contributes_to_flow` (Q32: TREU 25,192, BMTF 20,678, RTXF 7,476, ISWE 6,880, TWEM 4,775, BTFE 3,012, GSEF 2,658, BGCO 237, TRWB 7). The code gates on `contributes_to_flow` alone (TREU 25,224, BMTF 20,699). Same for the fingerprint table at `:122-136`, which reproduces to 0.1pp on the narrower population. See 4.1 — this is the corroboration that the module measures one universe and admits another.

**3.6 `universe.py:493-497` — "Vectorised because the report has to run over 610 days and 1.44M units."** True of `unit_frame` (0.24 s for 40,000 legs), false of `build_universe`, the path that actually produces the `Unit` objects. Profiled: **16.8 s for 10,000 units**, of which 7.2 s is `by_group[key].reset_index(drop=True)` (`:795`) and 4.3 s + 3.3 s is `u.loc[key]` / `.iloc[0]` (`:792-796`). Linear extrapolation to the tape's 1,437,838 units is ~40 minutes. `build_universe` also calls `annotate_legs` twice (`:781` and again inside `unit_frame` at `:498`).

**3.7 `sanity.py:54-56` and `types.py:17` — `RATE_SENTINEL` is not a sentinel for 96% of what it flags.** `EXCL_RISK_IMPLAUSIBLE` is documented as "the 1e20 / 9.9 spec sentinels" and `sanity.py:54` says "Only ``NOTIONAL_SENTINEL`` and ``RATE_SENTINEL`` are corruption in the strict sense." Measured (Q13/Q24): `|fixed_rate| >= 1.0` hits **1,469 legs, of which 1,415 carry a perfectly ordinary notional**, with rates concentrated at 1.07–5.74 (837) and 5.75–10.0 (574), consistent with percent-scaled rates in a fraction column (flow median 0.038) rather than the spec's 9.9. Excluding them is defensible; naming them a spec sentinel misattributes 1,415 legs in the coverage accounting the module exists to make add up.

**3.8 Minor:** `EXCLUDED_TRADE_TYPES` (`:353`) contains `"INVOICE_SWAP"`, which does not exist on the tape (Q8) — a harmless no-op in a list that reads as measured. (`BASIS_CURVE`/`BASIS_FLY`, 1,360 legs, are absent from the list but *are* caught by the index gate — Q22 confirms all carry `rate_index_clean='BASIS'`. No gap.)

---

### 4. Silent degradation

**4.1 LIVE — `universe.py:451` + `:536`: 36,763 unwind legs are routed into the primary customer-flow series.** `_not_flow = ~contributes_to_flow` gates on one column. Measured (Q3): `contributes_to_flow = True` covers `ECONOMIC_FLOW` (2,289,646) **and `ECONOMIC_UNWIND` (36,828)**. Of those 36,828, **36,763 are stamped `lifecycle_type = 'NEW_TRADE'`** (Q28), so `is_lifecycle = ~all_new_trade` at `:536` evaluates **False** and they are not held out. `types.py:91-94` states the reason lifecycle prints are a separate series: "the sign is right but it is driven by seasoned P&L rather than by bid-offer, so the confidence model does not transfer." An economic unwind is precisely that population, and it enters the primary series as fresh customer bid-offer. It is also invisible in the accounting: `EXCL_NOT_FLOW` fires on only the 307 `ADMINISTRATIVE` rows, and every measured denominator in the module (2,289,646) excludes these 36,828 legs, so no quoted coverage number describes what the code actually admits.

**4.2 LATENT — `universe.py:783-823` vs its own docstring at `:769-771`: the builder and the report disagree, and the test that names the agreement cannot see it.** Demonstrated (R2): a `TERMINATION` leg with `event_timestamp = None` → `unit_frame` returns `exclusion = None` and `summarise` reports `kept_units: 1, excluded_units: 0`, while `build_universe` raises `NoPricingInstant` and aborts the **entire day**. The docstring claims "Both come off the same `unit_frame`, so a unit cannot be counted in one and missing from the other", and there is no `EXCL_*` constant for the condition. `test_report_agrees_with_the_builder_on_the_same_day` (`test:585`) is the test that names this property and cannot fail on the divergent case, because all six of its synthetic legs carry event timestamps. Unreachable on v3 today: Q5b measures **0** rows with a NULL `event_timestamp`.

**4.3 LATENT — `universe.py:729`: the EOD-fallback clock produces a tz-naive visibility stamp that precedes the print.** When `pricing_timestamp` returns a `datetime.date`, `pd.Timestamp(instant)` is midnight, so (R1) `visibility = Timestamp('2026-06-16 00:01:00')`, **tz-naive**, 00:01 on the trade date. Two concrete failures: (i) `clocks.visibility > clocks.execution` raises `TypeError: Cannot compare tz-naive and tz-aware timestamps` — every other Clocks stamp is tz-aware; (ii) `Clocks.visibility` is documented at `types.py:56` as "when the print could first have been acted on… Every aggregation stamps on this", and this one stamps the start of the day for a print that happened during it, while `pricing` means end-of-day — visibility precedes pricing. `visibility_source` carries `:EOD`, so it is flagged, but the value and the dtype are silently wrong. Unreachable on v3: `event_timestamp_granularity` is `'second'` on all 2,326,781 rows (Q7), which is what suppresses the wall-clock test for the 35 flow rows stamped exactly `00:00:00Z` (Q7b). The only thing holding it shut is one column being present — `annotate_legs:436` defaults it to `None` when absent, so any caller not using `LEG_COLUMNS` takes the path.

**4.4 `universe.py:1007-1026` — `_report` reports success on zero rows.** No non-empty gate anywhere: a month whose query returns nothing prints `… 0 legs -> 0 units`, the loop continues, and `_report` returns `0` unconditionally. Conversely `_print_report:1071/1079/1085` divides by `n` and by `dv01_proxy_total` with no zero guard, so a genuinely empty range fails with `ZeroDivisionError` only at the very end, after all the DB work.

**4.5 `universe.py:887-905` — two different denominators under one column name.** `by_reason["dv01_share_pct"]` and `by_constant["dv01_share_pct"]` are shares of `total_dv01` (the whole universe); `by_venue["dv01_share_pct"]` at `:903` is a share of the **kept** venue total. All three are printed in the same report under the same header.

**4.6 LATENT — `universe.py:613-614`: `.abs()` is applied after the leg sum, not per leg.** Demonstrated (R9): a package with `other_payment_ufro` of +100,000 on one leg and −100,000 on the other resolves `upfront = None` and routes to the rate rule with no fee, despite both legs carrying a $100k payment; a single −250,000 resolves to +250,000. Unreachable today — Q10 finds **0** negative `other_payment_ufro` rows on the whole tape and Q10b finds 0 both-sign packages.

---

### 5. Lookahead — CLEAN

Nothing in this module reads a curve, and no path uses execution time where availability time is required. Visibility is derived from the **pricing** instant, not from raw #96 — mutation M12 (visibility from `row['execution_timestamp']`) goes red, so that is genuinely pinned. The only availability-time defect is 4.3, and it errs by dating visibility too *early*, currently unreachable.

Informational, **out of module**: `snapshot.py:86` prefers `original_execution_timestamp` over `execution_timestamp` for a `NEW_TRADE`, so a NEWT whose original stamp differs would price *and* date its visibility at the original — R7 demonstrates visibility landing 2.4 years before the print. Measured at **0 divergent rows** on v3 (Q6: 2,256,825 NEW_TRADE rows, 0 with a differing original, max delta 0.0 s). Root is in `snapshot.py`; `build_clocks` merely wires it.

---

### 6. Interface drift

**6.1 `universe.py:804` — the pricing-clock provenance is computed and thrown away.** `clocks, _field = build_clocks(...)`. `types.Provenance.pricing_clock_field` (`types.py:160`) requires that value and `Clocks` has no field for it, so a provenance builder must recompute `pricing_timestamp` a third time or guess. `visibility_source` preserves only the `:EOD` case, not the EXECUTION-vs-EVENT distinction.

**6.2 `types.py:160` vs `snapshot.py:50` — vocabulary drift.** `pricing_clock_field` is declared `"execution_timestamp | event_timestamp"`; `build_clocks` can return a third value, `CLOCK_EOD_FALLBACK = "event_timestamp_date_only"`. LATENT (unreachable per Q7).

**6.3 `types.py:49` vs `universe.py:736`** — `Clocks.pricing` is annotated `pd.Timestamp` but receives a `datetime.date` on the EOD path (R1). Same root as 4.3; LATENT.

**6.4 `universe.py:240-255` vs `ladder_conventions.py:29` — `on_facility` silently supersedes `SEF_PLATFORM_CODES`.** The frozen set is the 8 incumbent codes; this module treats every entry of `VENUE_EVIDENCE` outside `OFF_FACILITY_PLATFORMS` as on-facility, so TREU/TWEM/BMTF/BTFE/TRWB/ISWE/GSEF/BGCO/RTXF (≈70,700 legs) move from `INDETERMINATE` (+60 min) to `ON_FACILITY_NON_BLOCK` (+1 min) — verified in R4. The change is substantively defensible (they are MTFs/SEFs), but `_RELAXATIONS` at `:1049` claims to state *every* deviation from the frozen behaviour and this one is not in it, and it is untested (see 2.3).

**6.5 Minor, deliberate but unremarked:** every row on the tape carries a `package_id` (Q0: 0 nulls) and **1,065,787 of 1,437,838 packages are single-leg** (Q27). `unit_frame:535` and `build_universe:811` set `Unit.package_id = None` whenever `n_legs <= 1`, so ~1.07M units drop their package linkage. `test:328` pins this, but the tie-out join the test's own docstring invokes is keyed on `unit_key`, and nothing records that the package identity was discarded.