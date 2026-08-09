# MIX23 curve-store data errors — diagnosis, fix, and what was measured

Asset: `USD-OIS-Q12xM12STIRT-SERFFX-MIX23`, source `BARCHART_STIRF-RL`.
Sample: 2026-05-07 → 2026-08-07, 64 trading dates, 83,200 stored minutes.
All evidence read-only from the raw CurveStore parquet.

Triggered by an hourly `fomc_sep26` / `fomc_sep26/fomc_oct26` series showing zeros,
sign flips and 30bp spikes on 2026-06-30, 07-01, 07-21, 07-29 and 07-30.

---

## What was actually wrong

### A — an un-solved curve stored as success (2026-07-01)

All 1,381 stored minutes of trading date 2026-07-01 carry **every discount factor
exactly 1.0** — one distinct value across the whole day. That is rateslib's
pre-solve state, so every forward prices 0.

Mechanism: `_calibrate_chunk` warm-starts each minute from the previous minute's
nodes (`prior_nodes = _extract_nodes(curve_obj)`). One identity solve seeds the
next, and the whole chunk follows. Nothing in the write path rejected it, and
`_curve_store_write_day` returned quietly, so the warm reported success.

Corroborating: the analytics panel for the same day is all NaN. The analytics
writer noticed; the raw writer did not, and pricing reads raw nodes.

### B — an incomplete instrument roster, stored silently (2026-07-21 and four others)

Node dates are derived from whichever pricers came back (`_build_stirf_nodes`).
The last announced FOMC effective date in `_CENTRAL_BANK_DATES` is 2028-01-26, so
every node beyond it comes from an SR3 (`SFRCM*`) maturity. When those quotes are
missing for a minute the tail collapses and `_ensure_mixed_support_nodes`
substitutes generic ref+2Y / ref+3Y boundary nodes.

| 2026-07-21 | nodes | tail | Sep-26 fwd |
|---|---|---|---|
| 08:59 | 21 | 2028-03-15 … 2029-06-20 (SR3 IMM) | 3.8009% |
| **09:00** | **16** | **2028-07-21, 2029-07-21 (generic)** | **4.1056%** |
| 09:01 | 21 | 2028-03-15 … 2029-06-20 | 3.8000% |

+30.5bp round trip in two minutes, and the discount factors differ at *every*
shared front node (−1.0bp of DF at 2026-07-29 growing to −14.7bp at 2027-03-17) —
the whole solve moved, not just the extrapolated tail.

**But shape alone is not the defect.** 123 of 124 outlier minutes across the
sample sit on a non-modal shape, yet only 0.5% of non-modal minutes are outliers.
Whole sessions run on the reduced 16-node shape with perfectly continuous levels
(2026-06-25/26, 07-02, 07-22). The reduced build is normal when it is the
session; it is a defect when it flickers against a dominant one.

### C — a session-opening block at the wrong level (2026-07-30)

The first 450 minutes of the 2026-07-30 session (2026-07-29 18:00 → 01:59 ET) sit
**78bp** away from the rest of their own session on a 1Y reference rate:

| | anchor | nodes | Sep-26 | Oct-26 | Sep/Oct |
|---|---|---|---|---|---|
| prior close (07-29 17:00) | 2026-07-29 | 15 | 3.7719% | 3.8793% | −10.7bp |
| 07-29 18:00 → 07-30 01:59 | 2026-07-29 | 15 | 3.6081% | 3.4089% | **+19.9bp** |
| 07-30 02:00 on | 2026-07-30 | 20 | 3.7854% | 3.8900% | −10.5bp |

A round trip with nothing in between, and the Sep/Oct spread flips sign.

---

## A hypothesis that was wrong, and how it was caught

The original plan blamed **the curve anchor**. `_build_stirf_nodes` uses
`base_date = timestamp.date()`, so the 18:00–23:59 ET Globex block anchors on the
previous calendar day while the store partitions those rows under the next
trading date. On 2026-07-30 that put the reference date on the July FOMC
effective date that had just passed — a tidy story for the 17bp displacement, and
the plan proposed rewriting all seven `timestamp.date()` sites.

It is wrong. **2026-06-18's evening block anchors on 2026-06-17 — the June FOMC
effective date, the worst case for this hypothesis — with a complete 20-node
roster, and reads 3.8364% / 3.8373% / 3.8213% through the evening against 3.8341%
after the anchor rolls.** Continuous. The anchor is innocent; 07-30's evening was
a roster problem wearing the anchor's clothes.

Two further reasons the change would have been a mistake:

* `tests/test_barchart_stirf_node_anchor.py` deliberately encodes the current
  convention. Anchoring on a non-business day puts the curve after the last SOFR
  fixing and the front SR1 future fails to price — that was the original blocker
  for backfilling holiday-adjacent overnight sessions.
* It changes historical values on every evening block ever written, for a defect
  that does not exist.

`anchor_mismatch` is therefore reported and never actioned. The 07-30 block is
caught instead by a measured predicate (below).

---

## What was built

### `Caching/curve_sanity.py`

One module of predicates, shared by the write gate, the read filter and the audit
so they cannot drift. Every predicate is kept only because it separates
known-bad rows from known-good ones on the 64-day sample.

Quarantined: `degenerate_identity`, `non_finite_df`, `non_positive_df`,
`empty_nodes`, `off_modal_shape`, `anchor_block_jump`.
Reported only: `negative_forward`, `anchor_mismatch`.

Two normalisations make the shape rule usable rather than a scythe:

* the shape signature excludes node[0] and the ref+2Y / ref+3Y spline boundary
  nodes, which move with the anchor;
* shapes are compared only within the same `(trading date, anchor)` block,
  because crossing a calendar day legitimately rolls one IMM or FOMC node in or
  out. Skipping either normalisation flagged the entire evening block of four
  clean sessions — 420 rows each, all false.

And a shape mismatch must also *cost something*: an off-modal snapshot is only
quarantined if its 1Y reference rate is more than 2bp from the nearest 40 modal
snapshots. Of 60 hourly points the shape rule removed before that condition, 19
sat within 1bp of their clean neighbours — different instrument sets that priced
the same, not worth a gap.

`anchor_block_jump` fires when a minority anchor block's median reference rate is
more than 15bp from its session's. Across all 64 days that statistic is 1.45bp
median, 8.0bp at the worst clean day, and 78.0bp on 2026-07-30 — the threshold
flags one day in 64 and it is the one with independent evidence.

### Write gate — `MDP/IRSwaps/BARCHART_STIRF/rl.py`

* `_curve_store_write_day` runs every candidate snapshot through the gate and
  refuses to persist a failure. If a whole day fails it **raises** rather than
  returning quietly — a day that produced nothing believable is a failure, not a
  no-op. The merge-base read is explicitly unfiltered, or quarantined rows would
  be silently deleted from the partition by the next write.
* `_calibrate_chunk` refuses to warm-start the next minute from a curve that
  fails the gate. This is what stops an A-class cascade at source.

### Read quarantine — `Caching/curve_store.py`

`read_raw_day` / `read_raw_nodes` filter on the way out, so history already on
disk cannot reach pricing. `apply_sanity_filter=False` for the writer's merge
base; `ARBS_CURVE_STORE_SANITY_FILTER=0` disables it entirely; a filter that
raises never takes the read down.

Single-day reads filter the **full day** before subsetting to the requested
timestamps, so the shape rule sees the session's modal node set rather than a
sampled grid.

### `scripts/audit_curve_store_health.py`

Per asset per trading date: snapshot count, distinct shapes and anchors,
quarantined/degenerate/negative-forward counts, rolling-median outliers, worst
deviation, and the anchor-block gap. Also flags thin sessions — 2026-07-13…07-17
hold 622–975 minutes against a 1,381 median, which is a coverage gap rather than
corruption but silently thins an intraday grid.

### `scripts/purge_computed_timeseries.py`

The computed-timeseries cache is read **before** the curve store, so neither the
quarantine nor a rebuild changes anything a caller sees until the rows derived
from bad snapshots are gone. Dry-run by default.

---

## Measured effect

Store-level, 64 days: **2,068 of 83,200 snapshots quarantined (2.49%)**, 54 of 64
days untouched.

End-to-end on the original query (2026-05-07 07:00 → 2026-08-07 17:00, hourly):

* 40 of 1,523 hourly points removed;
* the surviving 1,483 are **bit-identical** to before (max |change| = 0.00e+00) —
  the filter only removes, it never alters a value;
* all 24 zeros of the 2026-07-01 session gone;
* 2026-07-21's four hourly spikes gone;
* 2026-07-29 18:00 → 07-30 01:00 gone;
* 2026-07-22 (clean reduced-shape day), 2026-06-17 20:00 (evening anchored on the
  June FOMC date) and 2026-07-29 14:00 (the genuine FOMC repricing) all kept.

Points removed become NaN, which is the honest answer: those minutes have no
believable curve until the days are rebuilt.

---

## Not done, and why

* **Phase 0 (rebuild four stamps with roster logging).** Needs live Schwab/
  Barchart fetches. Deferred rather than run unattended on a loaded box against a
  source with a documented 429 history. It is still the right confirm-then-tighten
  step, and it decides whether the roster gap is a fetch failure (retry-or-gap
  belongs on the fetch) or a build problem.
* **The computed-cache purge.** Built and dry-run — 2 symbols, 56 partitions,
  0.2 MB for 2026-06-29…07-31 — but not applied. `computed_ts.duckdb` is locked by
  a running kernel and refuses even a read-only open, so the DuckDB mirror cannot
  be purged in the same pass. A parquet-only purge would look fixed while a later
  session could still serve stale mirror rows. Run this with the kernel closed:

  ```
  python scripts/purge_computed_timeseries.py \
      --symbol "IRS::BARCHART_STIRF-RL::USD-OIS-Q12xM12STIRT-SERFFX-MIX23::ba9ff2a494c8231fda56d7f5de006051fed316b0" \
      --symbol "IRS::BARCHART_STIRF-RL::USD-OIS-Q12xM12STIRT-SERFFX-MIX23::4628cde90ba152922ca95f1fb0e8fa925b78d50f" \
      --start 2026-06-29 --end 2026-07-31 --apply
  ```

  Those two symbols are the fingerprints of the `fomc_sep26` outright and the
  `fomc_sep26/fomc_oct26` spread. Other queries against the same curve have
  different fingerprints; `--list` enumerates directories and `--dir-contains
  IRS__BARCHART_STIRF-RL__` takes every query against the source.
* **Rebuilding the affected sessions.** 2026-06-01, 07-01, 07-13, 07-15, 07-20,
  07-21, 07-30 need a re-warm now that the gates exist. Network-bound and hours
  long; not started unattended.
* **2026-05-29's spline overshoot** (34 minutes, implied forward −0.2512% between
  the 2Y and 3Y boundary nodes) is reported, not quarantined. It is a
  mixed-interpolation modelling question, not corruption.

---

## Verification

* `tests/test_curve_sanity.py` — 22 tests, each carrying the trading date its
  case came from. Mutation-checked: disabling the identity check, the shape rule
  and the block-jump threshold fails 5 tests.
* `tests/test_curve_store_sanity_filter.py` — 6 tests over a real temporary
  store, including "a raising filter never takes the read down" and "the merge
  base can still see the unfiltered truth".
* `tests/test_barchart_stirf_bulk_persistence.py` — 2 new tests for the write
  gate; the three existing stubs were updated to carry node data and to accept
  the merge-base keyword.
* A known-answer harness over the real store checks nine trading dates with exact
  expected drop counts, including four clean controls that must come back at
  exactly zero.
