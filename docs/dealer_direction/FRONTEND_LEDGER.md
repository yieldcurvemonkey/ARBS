# Dealer direction in the tape front end — working ledger

Branch `feat/tape-direction-frontend`, worktree `C:\Users\chris\clee\ARBS-fe`.
Started 2026-08-12. Long-running; this file is the durable memory.

**Scope**: materialise the dealer-direction inference and the signed risk-bucket
ladder into Postgres, and surface both in the USD swap tape front end. NOT:
improving the inference, extending coverage, hedge-ratio projection, any signal.

---

## D0. Branch point — branch from `main`, not from PR #441

The brief said PR #441 "is not merged; you will need to branch from it or
cherry-pick". **It was merged** — `c0c866eb Merge pull request #441` is an
ancestor of `origin/main` (`4a71d1bf`), which also carries #442 (`r0-leadlag`)
and #443. `docs/dealer_direction/`, `SDRUtils/dealer_direction/`,
`BT/dd_signals/` and `notebooks/dealer_direction/` are all present on
`origin/main`.

So: **branched from `origin/main`**. No cherry-pick, no rebase onto a feature
branch, and the R0 result (#442) — which is what retargets this to a *daily*
indicator rather than an intraday trigger — comes along for free.

## D1. Worktree is on `C:`, caches on `D:`

`C:` had 1.9 GB free at start, and `SDRUtils/dashboard/node_modules` measures
746 MB. `D:` has 287 GB but is **exFAT** — `git worktree add D:/ARBS-fe` gets
`fatal: detected dubious ownership … file system that does not record
ownership`, and exFAT has no symlinks or file modes. A worktree there is a bad
idea, so it stays at `C:\Users\chris\clee\ARBS-fe` as briefed.

Freed instead: the global npm cache was **4,799 MB on C:**. Moved to
`D:\npm-cache` (`npm config set cache D:\npm-cache --global`). Reversible with
`npm config delete cache`. Python/analysis caches go to `D:\ddfe_cache`.

---

## Phase log

### Phase 0 — orientation (2026-08-12)

Read `WHAT_THE_LADDER_SUPPORTS.md`, `INDICATOR.md`, `DESIGN.md`, `LEDGER.md`.

### G-1. The brief's join key is WRONG. The grain is right; the key is `package_id`.

Probes `scratch/ddfe01_join_probe.py`, `scratch/ddfe02_join_on_package_id.py`.
Prod Supabase, read-only.

The brief says the display view's primary key `package_id` *is* the direction
feature's `unit_key`. Measured on 2026-04-01: the two agree on the **grain**
exactly — 2,752 view rows, 2,752 units, no nulls — and on only **27.47% of the
keys**.

The cause is `universe.py:614`:

```python
u["unit_key"] = np.where(u["n_legs"] <= 1, u["first_trade_id"], u.index)
```

A **single-leg print that still carries a package id** — `MATCHED_MATURITY_…`,
`SPREADOVER_…` and the rest — is keyed by that package id in the view and by
its raw `trade_id` in `unit_key`. Roughly three quarters of the tape's rows are
in that class, which is why the mismatch is so large rather than a rounding
edge.

**The join that works is `package_id`, which `unit_frame` also carries.**
Measured over five days spanning the whole tape:

| day | view rows | units | `package_id` match | view-only | unit-only | `unit_key` match |
|---|---:|---:|---:|---:|---:|---:|
| 2024-07-01 | 2,364 | 2,364 | **100.0000%** | 0 | 0 | 29.27% |
| 2025-01-15 | 2,817 | 2,817 | **100.0000%** | 0 | 0 | 28.36% |
| 2025-10-17 | 2,502 | 2,502 | **100.0000%** | 0 | 0 | 21.70% |
| 2026-04-01 | 2,752 | 2,752 | **100.0000%** | 0 | 0 | 27.47% |
| 2026-08-07 | 2,341 | 2,341 | **100.0000%** | 0 | 0 | 25.89% |

Exactly one-to-one, both directions, on every day tried.

**Decision D2: the per-unit table carries BOTH keys.** `unit_key` is the
backend's identity and every `dealer_direction` frame is keyed on it, so
dropping it would break the audit trail back to the ladder. `package_id` is the
join key the front end actually uses. Storing one and deriving the other at
read time would put the `n_legs <= 1` branch in a SQL `CASE` on the web tier,
which is precisely where it would be got wrong.

This was worth measuring on day one: every table key, API contract and grid
join in the rest of this work would have been built on the wrong column.

### G-2. The curve store is warm for the whole window

`USD-SOFR-1D-CITIVELOEXCELMIN` and `USD-FEDFUNDS-1D-CITIVELOEXCELMIN` each hold
**659 day-partitions over 2024-07-01 .. 2026-08-07 with zero weekday gaps**
(`C:\Users\chris\AppData\Local\ARBS\Cache\curve_store\raw`). Directory
presence is not a content test; the runner reports a priced fraction per day
and the pilot below is the real check.

### G-3. A day costs 57 s, not the 180 s the estimates implied

Pilot on **2026-04-01**, chosen because `LEDGER.md` pins it: 4,329 eligible
flow legs, 100% priced.

| | |
|---|---|
| units | 2,752 (= the display view's row count for that day, exactly) |
| kept by `universe` | 2,098 |
| priced, no failure | **2,098 — all of them** |
| KRD rows | 58,520 = **28.0 per unit**, i.e. every pillar is non-zero |
| wall | **57 s** single process |

The backend's own numbers were 115 s repricing + 65 s key-rate = 180 s. The
difference is that those were measured separately, each paying its own curve
acquisition; run together against a fully warm minute store, with the
projector taking the repricer's own pricer, the day costs a third of the sum.

**610 days therefore cost ~9.7 h single-process, and ~1.2 h at 8 workers**
(32 cores, 64 GB on this box).

### D3. Store the ten-bucket roll-up, not the 28 pillars

28.0 KRD rows per unit is not a sampling artefact — rateslib's delta is
sensitivity to every calibrating instrument, so a single 5y swap has a
non-zero entry at all 28. Across the tape that is ~35 M rows.

`arbs_dd_unit_bucket_v1` stores the **`TENOR10` roll-up** instead (~12 M
rows), because:

* no published number needs more. `ladder.aggregate`, `indicator.daily_levels`
  and every column of `arbs_dd_ladder_v1` are computed from `TENOR10` rows, so
  the roll-up is a **sufficient statistic for the whole published surface** —
  the re-aggregation insurance the pillar frame would buy is already bought;
* the front end reads a ten-bucket profile, never a pillar;
* the pillar frame is written un-lossy to parquet on `D:` by `price` anyway,
  which is where any future pillar question is answered — and it is a local
  file the web tier could not reach in any case.

No dust threshold is applied. The backend measured that an absolute floor of
0.05 USD/bp removes 53% of rows and that one of them was 95.4% of its own
unit's risk; only exact zeros are dropped.

### D4. Two stages, split on the cost line

`price` (per day, parallel, ~57 s/day) writes parquet. `publish` (whole
window, one process, minutes) writes Postgres. A defect in the calibration,
any of the three rules, the ladder or the indicator is repaired by re-running
`publish` — not by re-pricing for a day.

`price` runs from **2024-03-01**, `publish` from `indicator.SAMPLE_FLOOR`
(**2024-07-01**). The tau calibration is a trailing 60-day window that must end
*strictly* before the day it calibrates, so a calibrated first published day
needs a quarter of priced history in front of it. Those ~85 days are priced
and never published.

### D5. The calibration is refitted, not borrowed

`dd_nb`'s default mode unpickles `D:\dd_signals_cache\s2_pos\calibrations.pkl`.
That pickle exists and is usable, but its fits stop at **2025-08-22** — it was
built for s2's design window — so it cannot serve a window ending 2026-08-07.
`publish` refits `probability.rolling_calibrations` over its own priced
deviations with the same parameters the backend used (60-day window, 1-day
minimum gap, 5-day step) and picks, per day, the most recent fit whose window
ends strictly before that day.

`D:\dd_signals_cache\s2_pos` also holds **371 days** of already-priced units,
KRD and coverage from the backend work, 288 of them inside this window. They
are **not** reused: s2's population is SOFR-only, flow-only and has no
package-price branch (`s2_positioning.py:283`), so reusing it would silently
narrow the published product to a different question. It is kept as an
independent cross-check on the overlapping days instead.

### G-4. `if nan:` is `True`, and it excluded every package unit

The first `publish` run stopped on its own guard:

```
RuntimeError: 2024-07-01: 15 coverage leg(s) belong to a unit with no reason;
the coverage accounting would not sum
```

Probes `ddfe04_coverage_orphans.py` and `ddfe05_reason_nan.py`. The first
ruled out the obvious explanation: the two frames agree on **2,364 unit keys
with zero orphans in either direction**, so `.map()` was not missing a key — it
was mapping to a NaN.

The cause: `pkg_exclusion` is only ever assigned on a `PKG` unit. On a day
where no package is refused, no row assigns it, and
`DataFrame.reindex(columns=UNIT_COLS)` creates it as an **all-NaN `float64`**
column. Parquet round-trips that as `float64`, `r.get("pkg_exclusion")` returns
`nan` — and **`bool(nan)` is `True`**. So

```python
if r.get("pkg_exclusion"):        # fires on EVERY package unit
    out["exclusion"] = r["pkg_exclusion"]   # ... with the reason `nan`
```

Every package-price unit was marked excluded, with a reason that is neither a
reason nor a null.

**It had no symptom of its own.** The units would have shipped as abstentions
with a blank tooltip; the ladder would have been quietly short 15 units a day;
the coverage percentage would have been slightly wrong in the direction that
flatters nothing in particular. It surfaced only because the coverage
accounting is required to be a partition and refuses a unit with no reason.

Fixed by `_s()` — one reader for every string field coming back out of the
stage cache — plus two assertions that state the invariant rather than relying
on the next guard downstream: `classify_day` refuses a non-string exclusion,
and `publish_day` refuses a non-string reason. Pinned by
`test_a_string_field_that_came_back_as_nan_reads_as_absent`, which asserts
`bool(nan) is True` alongside it so the premise is in the test rather than in a
comment, and by a test that reproduces the parquet round-trip rather than
asserting it from memory.

### G-5. The calibration is the only slow thing in `publish`, so it is cached

Measured: **22 rolling fits over 112 priced days cost ~14 minutes** (longer
with 8 pricing workers competing for the CPU). The full 610-day window is ~120
fits, i.e. a couple of hours of mixture MLEs.

That would have taken back the whole point of splitting `price` from
`publish`. `build_calibrations` now caches to
`D:\ddfe_cache\calibrations\<key>.pkl`.

**The key is a hash of the deviation values, not their count.** A count is a
weak checksum in the wrong direction: a re-price that changes what the
deviations *are* without changing how many there are — a curve fix, a
snapshot-policy change, exactly the class of edit that motivates a re-price —
would hit a stale cache and publish a calibration fitted to numbers that no
longer exist, with nothing anywhere to say so. `--refresh-calibration` forces
a refit.

**And the cost, measured rather than inferred** (`ddfe08_calib_cost.py`):

| | |
|---|---|
| one `Calibration.fit`, 60-day window, 59,520 deviations | **42.1 s** |
| buckets fitted | **550** (287 leaf `BucketKey`s + pooled parents), 77 ms each |
| leaf buckets clearing `MIN_BUCKET_N = 800` | 17, holding 41,628 of 59,520 rows |
| smoke window, 22 rolling fits | 15 min, measured under contention |
| **full tape, 121 rolling fits, box free** | **41.5 min** |

**The projection was 2× too pessimistic, and the reason is the measurement's
own conditions.** The 42.1 s/fit came from a probe run *while eight pricing
workers were saturating the box*; with the box free the real cost is 20.6
s/fit. So the estimate was not wrong about the arithmetic, it was wrong about
what it had measured — the same shape of error as the per-day-solver
correction in the backend's own LEDGER, where a stable Jacobian was measured
correctly and licensed the wrong conclusion.

Practical consequence, and it is the useful half: **run the full-window
calibration after `price` finishes, not beside it.** Same for the per-day
publish loop, which runs at ~4 s/day on a free box against 6.5 s/day
contended.

### G-6. Three defects on the first live `publish`, all caught by a guard

**(a) The two clocks do not share a day boundary.** The tape's `as_of` day
runs 20:00 ET the previous evening to 19:59 ET; the ladder stamps a New York
*availability* date. So for `as_of = D` the visibility dates are `{D-1, D}`,
and publishing `as_of >= SAMPLE_FLOOR` produced 1,050 unit-bucket rows stamped
**2024-06-30** — built only from the sliver of 07-01's prints that executed
the previous evening. `indicator.build` refused the entire run over it, which
is how it was found.

Dropped. Nothing that belongs to a published day goes with them: a FLOOR-1
cell would need `as_of = FLOOR-1`, which is outside the window by
construction. **The other end is different and is left alone**: the most
recent visibility day is missing the 20:00–23:59 ET prints that arrive with
the next tape day's `as_of`, so it is *provisional* rather than wrong and tops
itself up on the next run. Dropping it would throw away the freshest cell in
the series to fix an under-read in the thinnest hours of the session. Stated
in the consumer note instead.

**(b) The level and the coverage are on two different grids.** INDICATOR.md §2
says so; this is where it bites. The level is key-rate risk — rateslib's delta
is non-zero at **all 28 pillars** for a single swap (measured: 28.0 rows per
unit), so one 10Y trade publishes a level cell in 0-1Y as well as in 7-10Y.
Coverage is a maturity-point allocation of gross |DV01|, and it has to be,
because an excluded unit has no key-rate profile *by construction* — that is
why it was excluded. So the two grids have different cell sets and
`indicator.build` requires one coverage row per published cell.

**Nothing had exercised this before.** `ddind_coverage.py` built the coverage
frame alone, and INDICATOR §6 records that no composed pipeline existed to put
a KRD-derived level beside it.

187 of 1,420 cells had a level and no denominator. Dropped, at a measured cost
of **0.253% of |delta_dv01|**. The alternative — numerator on the KRD grid,
denominator on the maturity grid — makes the ratio cell-consistent by putting
two different populations inside one fraction, which is the incoherence §2
exists to name. `coverage_fraction` refuses a ratio over no size and it is
right to.

**(c) The coverage headline was 22 points too flattering.** `summarySql`
summed `coverage_dv01_kept / coverage_dv01_total` over `arbs_dd_ladder_v1`. A
ladder cell only exists where at least one unit was oriented, so that average
**conditions on the very thing it measures**: a bucket-day whose units were
all excluded contributes its whole DV01 to the true denominator and nothing at
all to the average.

| D2C / FLOW, 2024-07-01 … 2024-08-09 | |
|---|---:|
| over ladder cells | **67.0%** |
| over `arbs_dd_coverage_v1`, the complete partition | **44.8%** |

On the one number whose entire job is to stop the panel reading as complete.
Fixed to read the coverage table; verified live at 44.84% D2C / 57.02% D2D,
matching the table to the digit.

The exclusion breakdown over the window, all series:

| reason | DV01 share | units |
|---|---:|---:|
| `IN_LADDER` | 48.01% | 20,917 |
| `UNORIENTABLE_PKG` | **44.15%** | 8,476 |
| `UNSUPPORTED_INDEX` | 4.07% | 2,351 |
| `PRICING_ERROR` | 1.90% | 955 |
| `NO_FIXED_RATE` | 1.66% | 581 |
| `RISK_IMPLAUSIBLE` | 0.09% | 100 |
| everything else | < 0.15% | 61 |

### G-6b. The published split is balanced — the strongest evidence the wiring is right

The single best check available, and it is independent of every test: the old
short-end classifier came out **78.3% PAID** because the Barchart
`Q12xM12STIRT` mid it priced against runs ~0.5 bp high with ~7× the dispersion
(F-20). If anything in this pipeline — the curve token, the sign convention,
the bias correction, the probability model — were wrong in the same way, the
published directions would lean the same way.

Measured over the 29-day published window, called units only:

| rule | PAID | RECEIVED |
|---|---:|---:|
| `RATE_VS_MID` | 17,222 (**49.97%**) | 17,245 (**50.03%**) |
| `NPV_VS_UPFRONT` | 6,051 (47.35%) | 6,728 (52.65%) |
| `PACKAGE_PRICE_VS_MODEL` | 136 (49.64%) | 138 (50.36%) |

and on the deviations themselves, 34,467 `RATE_VS_MID` calls:

| | this run | backend's F-15, sampled independently |
|---|---:|---:|
| share printed above mid | **52.3%** | 55.5% |
| median (printed − mid) | **+0.012 bp** | +0.021 bp, 95% CI [−0.0015, +0.0463] |
| IQR | [−0.167, +0.205] bp | [−0.096, +0.170] bp |

Mean conviction `|2p−1|` is **0.129** — most calls are marginal, which is what
the mixture model should say about prints inside a half-spread, and is exactly
why the ladder weights by `2p−1` rather than by `p`.

Net over the window, D2C / FLOW: **+81.2 MM/bp against 981.7 MM/bp gross**.

### G-6c. `dealer_sign` orients the STRUCTURE, not its net duration

`scratch/ddfe10_published_sanity.py` is a gate on the published rows with
eight thresholds fixed before running. Two failed on the first run and **both
were the check, not the data** — worth recording because the second one looked
exactly like a sign bug.

**"signed KRD points the way the call does" — 3,840 units disagreed (8%).**
The breakdown is the whole answer:

| kind | called | disagree | |
|---|---:|---:|---:|
| OUTRIGHT | 34,684 | **1** | **0.0%** |
| CURVE | 8,505 | 2,295 | 27.0% |
| FLY | 4,057 | 1,442 | 35.5% |
| PKG | 274 | 102 | 37.2% |

A 2s10s curve the dealer "received" has legs of opposite sign, so its **net**
DV01 across buckets may point either way. `dealer_sign` is the orientation of
the structure; the net duration is a different quantity. For an OUTRIGHT the
two must coincide — and they do on 34,683 of 34,684, the one exception having
a negative net received DV01 (a forward-start).

So the OUTRIGHT population is the sharp form of the check and is where an
inverted convention would show. The gate now asserts that, **plus a companion
asserting that multi-leg units DO net the other way** — otherwise the first
check could pass by every unit being effectively an outright, which is a
vacuous pass rather than a result.

**"every unit has exactly one of (p, reason)"** was never an invariant the
design claimed: `ladder.unit_ladder_rows` names a called unit with no risk
profile `PRICING_ERROR`, so the probability exists and the unit still did not
reach the ladder. Measured: 86 such units, every one a `CURVE` whose KRD
projection failed. *Both* is legal and honest; *neither* is the thing that
must never happen.

### G-6d. FOMC-dated swaps are priced against a curve with no meeting steps

Prompted by the question "did you properly distinguish the SOFR and Fed Funds
curves — this is especially important for the FOMC swaps". The routing is
clean; the answer underneath it is not.

**The routing is provably correct.** `midprice.SessionBranchPricer.curve_for`
does `self._curve_for[rate_index]` and raises `UnsupportedIndex` on a miss —
there is no silent default in the pricing path — and `krd.model_for` keys its
solver on `(rate_index, curve_name, block)`. On the published rows:

| rate_index | curve_name | units |
|---|---|---:|
| SOFR | `USD-SOFR-1D` | 45,551 |
| FED_FUNDS | `USD-FEDFUNDS-1D` | 2,087 |
| **mismatched** | | **0** |

and Fed Funds deviations sit at a median **+0.068 bp** — centred, not shifted
by a basis, which is what pricing FF on a SOFR curve would produce.

**But the FOMC-dated population is a different story.** Median |deviation|,
same days, same rules:

| | FOMC-dated | everything else | ratio |
|---|---:|---:|---:|
| FED_FUNDS | **1.994 bp** | 0.295 bp | **6.8×** |
| SOFR | **0.697 bp** | 0.174 bp | **4.0×** |

and per meeting the median **flips sign by 1–2 bp**:

| meeting | index | n | median bp | % above mid |
|---|---|---:|---:|---:|
| JUL24 | FED_FUNDS | 363 | **+1.600** | 83.7% |
| JUL24 | SOFR | 62 | **+2.206** | 95.2% |
| NOV24 | FED_FUNDS | 181 | +1.353 | 65.2% |
| SEP24 | FED_FUNDS | 328 | **−1.230** | 33.5% |
| SEP24 | SOFR | 35 | **−1.491** | 37.1% |
| DEC24 | FED_FUNDS | 102 | −0.540 | 41.2% |

This is the F-20 signature — the exact statistic that condemned the Barchart
curve ("Fed Funds meeting buckets flip sign across meetings … the MIX23
meeting steps are misplaced"). **The decisive detail is that SOFR and Fed
Funds flip TOGETHER, in the same direction, by a similar magnitude.** A
routing fault would make them disagree. Both moving together says the fault is
in what the curve is, not in which one was chosen: the Citi minute curve is a
smooth par curve with no discrete FOMC steps, so a meeting-to-meeting swap is
repriced against a model that averages across the very step it trades.

Controls run before believing it: `fomc_meeting_label` is populated on **2,111
of 3,116 FOMC legs and on zero legs of every other structure type**, so it is
a structure tag rather than a proximity tag; and de-duplicating the leg join
moved the numbers by less than 0.1 bp.

**Size.** 1,918 units, **3.33% of the ladder's gross DV01** — but concentrated:

| bucket | FOMC share of gross DV01 |
|---|---:|
| **0-1Y** | **28.17%** |
| 2-3Y | 3.25% |
| everything else | < 2.1% |

So more than a quarter of the **0-1Y** bucket — the meeting-dated front end,
the bucket a positioning read cares about most — comes from units whose
direction is driven by curve model error rather than by bid-offer.

**What was done about it.** Nothing to the inference: the brief puts improving
it out of scope, and this is a property of the curve the backend chose, not a
defect in this branch. What this branch does is stop it being invisible —
`special_tenor_type` is now persisted per unit and joined onto the tape row,
an FOMC-dated row says so in its tooltip and calls its own direction
unreliable, and the 0-1Y bucket carries a pinned caveat with the measurement,
in the same spirit as the module's `PINNED_DRIFT_BUCKETS`.

**Recommendation for the backend owners**, stated and not acted on: FOMC-dated
units are a candidate for their own exclusion reason, or for a meeting-step
curve. `WHAT_THE_LADDER_SUPPORTS` §3 already lists Fed Funds as a low-
confidence condition; on this evidence the sharper statement is that
*meeting-dated structures on either index* are the low-confidence population,
and Fed Funds looks worse mainly because it is 66% of them.

### G-9. The full publish was killed mid-ladder, and the tables stayed consistent

Both the publish and the dev server were killed together partway through the
final ladder build — no OOM (no system events, 21 GB free of 64 GB), two
unrelated processes dying at the same instant, so an external reap rather than
anything the job did.

**The state it left behind is the design working.** Every per-day write
commits its own day, so:

| table | rows | range |
|---|---:|---|
| `arbs_dd_unit_v1` | 1,283,522 | 2024-07-01 … 2026-08-07 ✓ |
| `arbs_dd_unit_bucket_v1` | 9,571,690 | complete ✓ |
| `arbs_dd_coverage_v1` | 66,895 | complete ✓ |
| `arbs_dd_ladder_v1` | 2,006 | **stale — still the 29-day version** |

The kill landed before the ladder's `TRUNCATE`, so nothing was half-written and
nothing was lost. Re-running `publish` is the whole repair, and it costs the
day loop (~35 min) rather than the 26 hours of re-pricing — which is the split
the two stages exist for.

**The refinement worth stating**: a defect in the *ladder alone* still pays the
full 527-day loop, because `publish` has no ladder-only entry point. The unit
and coverage tables are already correct and sufficient to rebuild it. That is
listed as unfinished rather than built, because the cheap fix is to have
`publish` also drop its per-day `tenor_rows` to local parquet and add a
`ladder` stage over that directory — about thirty lines, and it would also
remove the ~10 GB concat this build does in memory.

**Operational note**: long unattended runs are launched detached
(`Start-Process -WindowStyle Hidden`) rather than as harness background tasks,
so a session-level reap cannot take them.

### G-7. Measured read cost

`scratch/ddfe06_read_cost.py`, 5 reps each, against prod over the pooler.

| query | median | p95 | rows |
|---|---:|---:|---:|
| tape grid, 200 rows, **no** direction join | 133.2 ms | 337.4 ms | 200 |
| tape grid, 200 rows, **with** the join | **128.0 ms** | 141.7 ms | 200 |
| tape grid, filtered to dealer RECEIVED | 334.9 ms | **3,845 ms** | 200 |
| `/direction/bucket`, one bucket, whole history | 13.4 ms | 17.2 ms | 34 |
| `/direction/standardised`, ten buckets | 17.2 ms | 18.3 ms | 340 |
| `/direction/coverage`, breakdown by bucket | 17.0 ms | 20.6 ms | 85 |
| `/direction/summary` | 40.8 ms | 43.7 ms | 1 |
| per-trade drill-down by `package_id` | 15.9 ms | 18.5 ms | 10 |

**The join is free.** `EXPLAIN (ANALYZE, BUFFERS)` on the tape grid shows
`Index Scan using arbs_dd_unit_v1_pkey`, **0.004 ms per row over 200 loops**;
the joined query is if anything faster than the baseline, which is noise on a
133 ms query.

**The one number to watch is the filtered query**, and it is an artefact of a
*partial* backfill rather than of the design: with only 2024-07/08 populated,
`WHERE dealer_direction = 'RECEIVED' ORDER BY execution_start DESC` walks
backward through ten months of unmatched packages before it finds 200 that
match. Re-measured after the full backfill.

### G-8. The tape's day set is not stable during a long run

`price` launched against `tape_days(2024-03-01, 2026-08-07)` = **609** days.
Four hours later the same query over the same fixed range returned **610** —
the tape had backfilled a day inside a window that does not move.

This is exactly why `assert_priced_complete` re-derives the day set from the
tape at `publish` time and refuses rather than publishing what it happens to
have. A run that took its day list once at the start and trusted it would have
published 609 of 610 days and reported success. `price` resumes by file
presence, so the fix is a second pass that costs one day.

### G-10. THE FULL BACKFILL, and what it says

`price` 609 days in 114.4 min at 8 workers, 0 errors. `publish` **527 days,
9,571,690 unit-bucket rows, 37,740 ladder cells over 629 sessions, 62.1 min**
— on the fourth attempt, the first three lost to a transient read-only
database and two OOMs, both now fixed rather than worked around.

The probability clip fired **16 times over 1.28M units, worst 2.2e-16** — one
machine epsilon, exactly the boundary it exists for and nothing else.

**Every check in `ddfe10_published_sanity.py` passes over the full history**,
and the headline numbers are stronger at scale than on the pilot window:

| check | 1,283,522 units |
|---|---|
| `RATE_VS_MID` split | **50.67% PAID over 673,038 calls** (frozen classifier: 78.3%) |
| median (printed − mid) | **−0.0011 bp**, 49.7% above mid |
| OUTRIGHT sign agreement | 18 of **695,738** disagree, **all 18** explained by a negative net received DV01 |
| multi-leg control | 67,195 of 256,483 CURVE/FLY net the other way |
| coverage | 50.42% of DV01 oriented |
| join to the display view | **1,283,522 = 1,283,522 = 1,283,522** |

A median of −0.0011 bp over 673,038 prints is the strongest statement
available that the mid is unbiased, and it is measured against a curve the
old classifier's 78.3% one-way label set could not have produced.

### G-11. Read cost on the full history — and one regression I chose to keep

| query | median | p95 |
|---|---:|---:|
| tape grid, 200 rows, no join | 140.8 ms | 229.0 ms |
| tape grid, 200 rows, **with** the join | **140.5 ms** | 142.0 ms |
| tape grid, filtered to dealer RECEIVED | **121.9 ms** | 182.7 ms |
| `/direction/bucket`, 629 rows | 19.8 ms | 23.0 ms |
| `/direction/standardised`, 6,290 rows | 48.1 ms | 51.9 ms |
| `/direction/coverage` | 35.4 ms | 43.3 ms |
| `/direction/summary` | **435.4 ms** | 488.2 ms |
| per-trade drill-down | 17.1 ms | 18.9 ms |

**The filtered query's 3,845 ms p95 was a partial-backfill artefact and is
gone** — 182.7 ms now, and the median is *faster* than the unfiltered
baseline because the predicate shrinks the working set. That was the
prediction; this is the measurement.

**`/direction/summary` regressed 40.8 ms → 435 ms, and it is my doing.** It
now reads `arbs_dd_coverage_v1`, the complete partition, instead of averaging
over ladder cells — which is what fixed the 67%-versus-44.8% overstatement. The
cost is a scan of 1.28M unit rows for the called-count. Kept: the route is
cached for 300 s and fires once per panel load, and trading a correct headline
back for 400 ms would be the wrong way round. Noted rather than hidden.

### D6. Chrome verification used `chrome-devtools`, not `claude-in-chrome`

`claude-in-chrome` found two connected browsers and requires the user to
choose one before any action. The user is away for the duration of this task,
so that could not be answered. `mcp__chrome-devtools__*` drives the same
browser without the ambiguity and produced the screenshots. One constraint
worth recording: it will only write files under `C:\Users\chris\clee\ARBS`, so
screenshots are saved there and copied into the worktree.

## G-12. The chart's mid line, wired to the real grid

`prints.logic.ts` reconstructed the mid per print because it was specced before
`arbs_dd_curve_mid_v1` existed. Four things had to be measured before the swap,
not argued (`scratch/mid21_grid_vs_reconstructed.py`):

1. **Coverage.** SOFR carries all 8 chart tenors; **FED_FUNDS carries 12 and is
   missing 7Y, 20Y, 30Y**. So the fallback is a real path, not a formality —
   though *no FF day in the tape has >=12 prints at those tenors*, so it does
   not fire on today's data.
2. **The join is an equality.** 0 of 22.7M grid rows carry a non-zero second.
3. **Agreement.** Median residual EXACTLY 0.000000 bp on SOFR STANDARD (n=2,850),
   p95 0.132 bp, max 15.62 bp. Section 4 of the probe explains the tail: of the
   9 prints beyond 0.5 bp the median maturity gap is 6 days, the median
   effective gap 4 days, and **0% are exact instrument matches** against 62.5%
   in the sub-0.5bp group. The mid is right; the swap is different.
4. **The hole.** ET hours 0 and 23 have **zero** grid coverage — 102 of 5,401
   prints (1.9%).

### The LOCF plan was wrong and I dropped it

The prior write-up said to carry the last point across the 23:00-00:59 ET hole
with a documented <=0.42 bp residual. That is a flat line asserting the mid did
not move through a two-hour window where no curve exists. The panel's rule
everywhere else is that a blank carries its reason. **The line breaks; the gap
is disclosed.**

### The break threshold is measured, not chosen

SOFR 10Y, 7 days: intra-day consecutive gaps are 1 min (8,293x), 2 (170), 3 (17),
4 (1), 5 (1). **Intra-day gaps over 5 minutes: zero, on every one of the seven
days.** Every larger gap in the distribution is a jump between grid days. The
overnight hole is ~2 h. `MID_GRID_GAP_MINUTES = 10` is two orders of magnitude
clear of both sides. (Distinct from `GAP_MINUTES = 20`, which governs gaps
between *prints* — p50 5.0, p90 23.0, max 177.8 min — a different process.)

### A second round trip, deliberately

The window could be a CTE inside the grid statement, saving ~20 ms. It would
also restate `printsSql`'s twelve-clause driving predicate in a second place,
where it drifts the first time a filter is added and silently draws the line
over the wrong span. The window comes from the rows actually drawn, so it cannot
disagree with them. Measured: 175-211 ms warm for the whole endpoint.

### Verified end to end, not just in unit tests

Through the running API: median residual **+0.000000 bp** at 2Y / 5Y / 10Y /
30Y (p95 0.009-0.055 bp). FED_FUNDS 5Y served `USD-FEDFUNDS-1D`, SOFR served
`USD-SOFR-1D`, band mode used the canonical grid.

**12 mutants, 12 killed** (`scratch/ddfe12_mid_mutants.py`) — including
residual-on-the-execution-clock, the line sold as a quote, the grid looked up by
the band column, and the fallback going silent.

---

## G-13. Looking at the page found a defect the tests could not

The Chrome MCP was unusable (see D6; `chrome-devtools` later disconnected too),
so `scratch/shot_dealer_direction.mjs` drives puppeteer — already a dependency
of this package, already driving the e2e suite — and asserts on page errors,
console errors and file size as well as writing the images.

**The z heatmap screenshotted BLANK.** Ten labelled bucket rows, empty strips,
an em-dash where z goes — pixel-for-pixel what "nothing could be oriented here"
looks like. The data was fine (34,176 of 37,740 cells carry `z_raw`; the latest
session carries all 10 at `z_n_obs = 250`). A DOM probe
(`scratch/ddfe13_zheatmap_dom.mjs`) showed the strip container 746 px wide with
**zero children**: `/standardised` returns 6,290 rows and the fixed 2.5 s sleep
fired while it was still in flight.

Two fixes, because the timing bug hid a real one:

- **The harness now waits for content**, not a clock. A fixed sleep is exactly
  what would have banked a picture of a defect as evidence the feature works.
- **The panel no longer renders an unlabelled empty ladder.** `heatmapState()`
  separates `ready` / `loading` / `empty` — a bare `loading` boolean cannot,
  since loading=false with no dates is a genuinely empty window and needs a
  different sentence. On a panel whose governing rule is that an abstention is
  information rather than a blank, an in-flight fetch rendering as an empty
  ladder was the same defect wearing a different hat.

Also fixed while looking: the **onboarding modal** ("How to use the USD swaps
tape") overlays every panel, so the first capture photographed the tour; and the
**legend swatch** still described the reconstruction — a dashed key captioned
"at print times" beside a solid modelled curve is a legend for a different
chart, and the reader believes the legend.

Eight views captured, no page errors, no console errors:
`fe-01`..`fe-07` in `docs/dealer_direction/img/`.

---

## G-14. `git worktree remove` deleted through a `node_modules` junction

To *verify* rather than assume that the 4 failing dashboard tests are
pre-existing, I checked `origin/main` out into a throwaway worktree and
junctioned its `node_modules` at this one's. `git worktree remove --force` then
followed the junction: it errored with `Invalid argument` **after** removing 27
top-level packages from the real tree (799 -> 772). Every direct dependency
still resolved, so nothing looked broken.

Recovered with `npm install --legacy-peer-deps` (back to 799), suite re-run
clean. The safe order is `[System.IO.Directory]::Delete(link, $false)` first —
that removes a reparse point and never its target — then `Remove-Item -Recurse`,
then `worktree prune`. Note `git worktree list` had already dropped the entry
even though the delete failed, so the listing is not evidence of a clean
removal.

The check was still worth it: **the same 4 tests fail at `origin/main`**, which
is now a measurement rather than an inference from "those files aren't in my
diff".

