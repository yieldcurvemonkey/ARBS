# R0 — deviations and interpretations, X (tape) workstream

`r0_prereg.md` is committed and **must not be edited**. Everything the data forced,
and every place the prereg left a choice open that had to be closed, is recorded
here instead. Written by the agent that built `build_x_tape.py`; covers X only.

Nothing here changes the decision rule, the bucket map, the sign convention, or the
regression specification.

---

## 1. The dissemination clock was fully recovered — no fallback was used

The prereg lists, as a condition that would make the test *uninformative rather than
negative*:

> A dissemination clock that is not actually recoverable, forcing `X_diss` to fall
> back to a legal-delay estimate — in which case the dissemination panel tests the
> estimate, not the clock, and must be labelled as such.

**This condition did not trigger.** Measured: **292,528 of 292,528 in-window prints
(100.00%) carry a real, recovered dissemination time.** The estimated-lag fallback is
implemented in `build_x_tape.py` but was never exercised on a single row. The
dissemination panel tests the clock, not an estimate, and needs no such label.

Supporting measurements (all first-hand, this workstream):

| check | result |
|---|---|
| `trade_id` joins the slice `Dissemination Identifier` | **3,320 / 3,320 = 100.00%** on the 2026-08-06 probe day |
| matched dissemination time earlier than execution | **0 violations**, min lag 67 s |
| slice ZIP member mtime vs the S3 object `Last-Modified` | offset **14,401–14,404 s** across all 2,168 slices of 2026-08-06 = exactly 4 h (EDT) plus a 1–4 s write-to-upload latency (p50 2 s) |
| duplicate dissemination ids across slices | **0** of 34,148 |
| slice sequence holes | **0** across all 101 harvested UTC days (every seq past the day's max returns 403 out to +500) |

The member mtime is a **naive America/New_York** stamp. The whole R0 window sits
inside EDT (US DST 2026 runs Mar 8 – Nov 1), so the conversion is a constant +4 h and
no DST edge arises. This would need revisiting for any window crossing early November.

**Known-answer validation of the recovered clock.** Publication lag splits by
block-election exactly as the regulation requires: **non-block p50 = 2.20 min,
block p50 = 15.28 min** on the probe day — the statutory 15-minute block reporting
delay, recovered from ZIP mtimes without being told about it. Full-sample lag is
p5 2.80 / p50 4.72 / p95 17.27 min, consistent with the independently supplied prior
(p50 5.23 min, p95 11.3 min); the single probe day was faster than typical.

**Two DTCC-side gaps, noted and immaterial.** 2026-05-01's slices stop at 21:18 UTC
and 2026-06-08's at 22:56 UTC (other days run to ~23:59). These are gaps in DTCC's
publication, not in the harvest. They cost nothing: the dissemination map is built
globally across all harvested days, so trades that spilled into the next UTC day's
file still matched — hence 100% coverage.

## 2. Filter added: `notional > 0`

**Forced by the data.** Beyond the documented `notional = 1e20` sentinel, the tape
carries **3 legs of 310,859 (0.001%)** with `notional = 0.0` and
`fixed_rate = 0.0001` — the same class of degenerate placeholder row
(trade_ids `3821455397000000301`, `3628969956000000101`, `3113425324000000201`).

They contribute exactly **zero** DV01 to both `signed_dv01` and `gross_dv01`, so
dropping them changes no aggregate. They were dropped anyway because they produced
two output cells with `gross_dv01 = 0.0` and `n_prints = 1`, which hands any
consumer that normalises by gross DV01 a silent 0/0.

## 3. Interpretations the prereg left open

Recorded because they were choices, not because the prereg forbade them.

**(a) The mid is keyed at fine tenor granularity, not at futures-bucket granularity.**
The task described the mid as a rolling median over "nearby same-tenor-bucket prints".
Taken literally at the *futures-bucket* level (e.g. all of 7–12y pooled), an
upward-sloping curve would put every 12y print above the bucket median and every 7y
print below it, making the sign a **proxy for tenor rather than for direction** — the
exact failure mode that disqualified `arbs_stir_direction_v1`. The mid key is
therefore `(rate_index_clean, tenor_label, forward_start_key, is_mac)`, all four of
them tape columns. Still entirely tape-internal; no curve.

**(b) `is_mac` is part of the mid key.** MAC swaps print a *standardised* coupon, not
the traded level (the economics sit in `other_payment_amount`). Pooled with vanilla
prints of the same tenor they would sit systematically on one side of the median.
Keyed separately they compare to each other, tie, and fall out as unsigned.

**(c) `forward_start_key` is derived from `forward_start_years`, not from the tape's
`forward_bucket` column.** `forward_bucket` is not usable for this — see
`SHARED_BUGS.md`; its `3Y+` label covers `forward_start_years` from 0.0219 to 35.03
with a **median of 0.2247**, i.e. it is a catch-all, not a bucket.

**(d) Ties are unsigned (0), not inherited from the previous print.** Classic
tick-rule tie inheritance would propagate one stale sign across long runs of
identical standardised coupons on a rate lattice.

**(e) The mid is computed in execution order for both clocks**, so a print carries
the *same* sign on both panels and the two clocks differ only in the timestamp they
are indexed by — which is what the prereg's "built twice" asks for. The window is
strictly trailing (never centred): a centred window would leak post-print tape
information into the sign precisely where the regression looks for post-print mass.

**(f) The frozen mid window** — median of up to the last **10** same-key prints,
strictly earlier, within a trailing **24 h**, requiring at least **3** — was written
into the module docstring **before** the direction split was computed, and has not
been revisited. Resulting split: **51.00% customer-paid**, which needs no defending.

## 4. Not a deviation, recorded so it is not mistaken for one

* **`X` is sparse.** Only cells containing at least one print are emitted. A consumer
  needing a regular grid must reindex onto the full
  (bucket x minute x clock x is_block x venue_class) product and fill 0.
* **Block notionals are capped by rule**, so block-bucket DV01 is understated by
  construction. `is_notional_capped` is true for 1.91% of in-window prints. No filter
  was applied; `is_block` is carried as a column for the prereg's split.
* **`X_diss` carries 22 more prints than `X_exec`** (292,547 vs 292,525). This is
  window-edge truncation at the emit boundary in both directions — chiefly prints
  executed late on 2026-04-30 that published on 05-01, plus prints executed late on
  08-07 that published past `EMIT_END`. It is not a join error; the join matched
  100% of in-window prints.

## 5. Artifacts for addendum-1 diagnostic D1

`r0_prereg_addendum_1.md` (written by the orchestrator after this workstream began)
adds diagnostics D1/D2 quantifying the attenuation of the median-based sign.

**D1 and D2 are NOT computed here**, and they do not block or change X — the addendum
says so itself ("Nothing here alters what is estimated"). D1's headline quantity,
`implied MDE = 1.96 * SE(sum beta_k, k>=1) / rho`, needs regression standard errors
that only the runner can produce, and the downgrade rule is applied at verdict time.

What this workstream hands over so D1's owner need not re-derive the mid:

`r0_leadlag/cache/tape_legs_signed.parquet` — the exact signed per-print frame X was
aggregated from, one row per in-scope leg, carrying `fixed_rate`, `mid`,
**`dev_median` (= `fixed_rate - mid`, which is precisely D1's `dev_median`)**,
`customer_sign`, `mid_key`, `bucket`, `dv01`, both timestamps, `dissem_is_real`,
`is_block` and `venue_class`. Computing `rho` and the sign-agreement rate against a
curve reference needs only this file plus the curve.

---
---

# R0 — deviations and interpretations, Y (MBO) workstream

Written by the agent that built `build_y_mbo.py`; covers **Y only**. Appended, not
edited over the X section above. Nothing here changes the decision rule, the bucket
map, the sign convention, or the regression specification.

---

## Y1. SR3 covers 53 UTC days, not 79 — SFR_FF is a 44-session bucket

**Forced by the data.** The task brief said the MBO extract was "2026-05-07 .. 2026-08-06,
79 files" for every root. Measured member counts inside the zips:

| root | dbn members | UTC-day range |
|---|---|---|
| **sr3** | **53** | **2026-06-07 .. 2026-08-06** |
| zq | 81 | 2026-05-06 .. 2026-08-07 |
| zt, zf, zn, tn, zb, ub | 79 each | 2026-05-07 .. 2026-08-06 |

`SFR_FF` pools `sr3` + `zq`. Emitting it over zq's full range would make the bucket
**zq-only for the first 23 sessions and zq+sr3 thereafter** — a composition break in the
middle of a series the prereg then standardises by a rolling standard deviation. So
`SFR_FF` is emitted only on sessions where **both** roots are present *and equally
complete*: **44 sessions, 2026-06-08 .. 2026-08-06**. The other five buckets keep their
full **67 sessions, 2026-05-07 .. 2026-08-07**.

44 sessions is above the prereg's "fewer than ~20 trading days of overlap" floor, so this
is a coverage note, **not** an uninformativeness trigger. It does mean the SFR_FF panel
carries ~2/3 the days of the others.

## Y2. Session completeness, not just session presence

A CME Globex session for trade date D runs **D-1 17:00 CT -> D 16:00 CT**, i.e. it spans
**two** Databento UTC-day files. A root whose file for D-1 *or* D is missing therefore
covers only part of that session. This bites once: sr3's last file (2026-08-06) contains
only the **evening open** of session 2026-08-07, while zq has a full 2026-08-07 file — so
pooling them would have made SFR_FF zq-only for 21 of that session's 23 hours. Session
2026-08-07 is dropped from SFR_FF for that reason (44 sessions, not 45).

Sessions that are *equally* partial for every root of a bucket are **kept and flagged**,
not dropped: `data/y_sessions.csv` carries `session_complete` per bucket-session. Five
bucket-sessions are partial — all of them 2026-08-07 for the single-root Treasury buckets,
118–120 bins each (the Thursday evening open only). Session 2026-05-07 is also short at
the front (its 2026-05-06 evening is outside the extract).

## Y3. Decisions the prereg did not specify

**(a) Only `action == 'T'` records count.** GLBX MBO emits, per match event, one `T`
record for the aggressing order plus one `F` record per resting order filled, with
`size(T) == sum(size(F))`. Measured `F_volume / T_volume` over the whole sample: 0.984 to
1.071 by root — one-to-one, not two-to-one, confirming `F` is the resting side. Counting
both inflates volume ~1.9x against exchange-published volume (measured 1.77–1.94).

**(b) `T.side` is the AGGRESSOR side** — validated three ways, see the run report. `B` is
buyer-initiated (+), `A` seller-initiated (−).

**(c) `side == 'N'` is unsigned, not dropped.** CME reports no aggressor on some prints.
Those contribute **0** to `signed_volume` but are still counted in `gross_volume` and
`n_trades`, so a consumer normalising by gross sees the true denominator. Share of
outright volume: **9.54% (sr3), 9.87% (zq)**, 0.55–1.89% for the Treasury roots. Left
unsigned deliberately — signing them by a tick rule or by book position would be an
inference the prereg does not fix. Per-bucket unsigned volume is carried in
`data/y_signed_volume_unsigned_side.parquet`. The error is attenuating, not sign-flipping.

**(d) Combo instruments are EXCLUDED; implied fills of resting outright orders are
INCLUDED.** A combo's aggressor side is defined on the combo, not on a leg, so signing it
per-outright needs a leg-decomposition convention that is not pre-registered — and for
`SR3:AB` packs / `SR3:BF` butterflies the legs are not even literal symbols. Measured
combo share of traded volume: **sr3 24.66%, zq 20.67%**, ub 15.48%, tn 14.34%, zt 14.07%,
zn 11.30%, zf 10.99%, zb 10.40%. This is the largest single caveat on Y and it is worst
exactly in `SFR_FF`.

**(e) SR3 "first 12 contracts" = the 12 nearest QUARTERLY outrights, resolved per session
from the CME calendar,** not from what happened to trade. Serial SR3 months
(J/K/N/Q/V/X/F/G) are excluded — 259 of 1,432,498 outright contracts (0.018%) on the
2026-07-07 probe day. The set is H6…Z8 through 2026-06-16 and M6…H9 from 2026-06-17, i.e.
it rolls exactly at SR3H6's last trading day. The calendar rule and a traded-universe rule
**agree on all 45 candidate sessions**. The restriction keeps **92.26%** of SR3 outright
volume.

**(f) ZQ is not restricted.** The prereg says "SFR strip (first 12 contracts, aggregated)
+ FF" and puts no limit on FF, so **all** ZQ outright contracts are included (15 traded on
the probe day, monthly).

**(g) Clock = `ts_event`** (CME matching-engine transact time), floored to the UTC minute.
`ts_recv` differs by well under a second and is immaterial at 1-minute bins.

**(h) The minute grid is dense within a session, with zeros, and breaks between
sessions.** Per bucket per session the grid runs from the **first to the last traded
minute of that bucket in that session**, every minute present, missing minutes filled with
`signed_volume = gross_volume = n_trades = 0`. Data-driven bounds rather than a holiday
table, so early closes and the Sunday open need no calendar. Verified: the number of
non-1-minute steps in each bucket's series equals exactly `n_sessions - 1`.

**(i) The roll needs no handling.** Each bucket aggregates **all** outright contracts of
its roots (SR3 aside, per (e)), so the series is continuous through every contract roll by
construction. The only thing the roll changes is where volume sits inside the bucket. It
is visible in the data: on 2026-05-29 the expiring ZNM6 printed only 21,450 contracts in
its own book against 194,723 as the leg of a calendar spread.

## Y4. A sixth bucket, `WN` (ub), is present and is NOT part of the decision rule

The prereg's map stops at `US`. `ub` was extracted anyway and is emitted as bucket `WN`
for reference. `data/y_coverage.csv` carries `in_decision_rule = False` for it. It must
not enter the pooled regression or the verdict.

## Y5. Not a deviation, recorded so it is not mistaken for one

* **Y is in contracts, unweighted.** `TY_UXY` adds ZN and TN contracts, and `SFR_FF` adds
  SR3 and ZQ contracts, without DV01 weighting — that is what the task specified. The
  prereg's standardisation by rolling within-bucket standard deviation absorbs the scale.
* **The sample's net signed volume is small and mostly negative** (e.g. zn −221,753 on
  111.7M gross = −0.20%). That is the expected shape: aggression is close to balanced over
  a quarter, and it is a useful null — a large systematic imbalance would have indicated a
  sign bug.
* **Exchange-published volume is 4–15% above outright-book T volume on ordinary days** and
  far above it for a contract in its roll. That gap is spread-leg allocation, not missing
  data; see the reconciliation in the run report.

---
---

# R0 — runner choices, FROZEN BEFORE ESTIMATION

Written by the agent that owns `run_r0.py`, **before `run_r0.py` was written and before
any beta was estimated**. Verified at the time of writing: `r0_leadlag/out/` does not
exist. Covers only choices `r0_prereg.md` left open that the runner had to close.
Nothing here changes the decision rule, the bucket map, the sign convention, the `k`
range, the clustering unit's role, or the regression specification.

## R1. Lag orientation

The prereg's `sum_{k=-30}^{+30} beta_k * X_{b,t-k}` is implemented as the design column
`X.shift(k)` on the bucket's time-sorted minute grid. So **`k > 0` means X precedes Y**
(post-print futures flow, the hedge channel) and `k < 0` means Y precedes X. This is the
reading the decision rule assumes.

## R2. Which regression the verdict reads

The prereg's decision rule speaks of a single `sum(beta_k)` without naming the
regression. The verdict is read off the **pooled, dissemination-clock, all-flow
regression** (bucket FE, the five decision buckets). Per-bucket and split regressions
are supporting evidence and carry no verdict.

## R3. Verdict sign logic, enforced in code

Per the prereg, positive X predicts **negative** Y. Therefore PASS requires
`S_pos = sum(beta_k, k>=1)` to be significantly **negative** (day-clustered
`t < -1.96`) **and** `|S_pos| >= 2 * |S_neg|`. A significantly *positive* `S_pos` is
recorded as "the pre-registered channel is absent; a different phenomenon of opposite
sign is present" and is **not** a PASS.

## R4. Standardisation window

The prereg says "standardised within bucket by rolling standard deviation" without a
window. Chosen and frozen: **trailing rolling standard deviation over the previous
1,440 bins (one day of minutes), `min_periods = 240`, strictly trailing (shifted one
bin, no look-ahead)**, computed per bucket over that bucket's time-sorted series; where
undefined or zero, the bucket's full-sample standard deviation is used. Series are
**scaled, not de-meaned** — `alpha_b` and the bin-of-day fixed effects absorb the means,
which is what the prereg's own equation does. Splits are standardised by their own
rolling standard deviation, on the same rule.

## R5. Cluster unit = CME session date

"Cluster by day" is implemented as the **CME session (trade) date**, not the UTC
calendar date: a Globex session spans two UTC dates, so clustering on UTC dates would
split one session's residuals across two clusters. Sessions are derived from gaps in Y's
own dense grid and validated against `data/y_sessions.csv` (67 / 44 sessions per bucket,
first and last minute per session). In the pooled regression a session date is **one
cluster across all buckets**, so same-day cross-bucket correlation sits inside the
cluster. The `1.96` threshold is used verbatim as the prereg states it.

## R6. Bin-of-day fixed effects

"Bin-of-day" = **minute of the UTC day**, 1,440 levels. Pooled runs carry additive
bucket FE **and** bin-of-day FE (not their interaction), absorbed by alternating
projections; per-bucket runs carry bin-of-day FE only. Absorption is validated against
explicit dummy variables on a subsample.

## R7. Sample and session edges

The regression runs on **Y's dense grid**. X is sparse and is reindexed onto that grid
and filled with 0 (absence of a print is zero flow), per the X workstream's own consumer
note. All lags are taken **within a session**: an observation enters only if all 61 X
lags (`k = -30 .. +30`) and all 5 Y lags exist inside the same session, i.e. the first 30
and last 30 bins of every session are dropped. `WN` (ub) is excluded everywhere — it is
not in the prereg's bucket map.

## R8. Newey-West

Bartlett kernel, bandwidth 60 bins, computed on the same absorbed design; the kernel is
applied in time order within a bucket and does not cross bucket boundaries. Session gaps
inside a bucket are treated as adjacent. Reported alongside, and where the two disagree
the day-clustered result governs, exactly as the prereg states.

## R9. Addendum-1 diagnostics

D2 (centroid of the `|beta_k|` mass per clock) is computed unconditionally from the
fitted betas. D1 (`rho`, sign agreement, implied MDE) is computed **if and only if the
verdict is FAIL**, because that is the only branch on which the addendum's downgrade rule
can act; on a FAIL it is blocking — `R0_RESULT.md` may not state FAIL rather than
UNINFORMATIVE until `rho` and the sign-agreement rate are measured, or, failing that,
until it says outright that the attenuation is unquantified.

## R10. Addendum-1 D1, operationalised — FROZEN BEFORE ANY RHO WAS COMPUTED

The verdict is FAIL, so the addendum's downgrade rule is live and D1 is blocking. The
addendum fixes the quantities but not the sample; those choices are closed here, before
the first number.

**Reference series.** `dev_curve = fixed_rate - par swap rate of the same tenor on the
Citi minute curve, at the print's EXECUTION minute`. Served from the already-warmed
ComputedTimeseriesStore (`IRS_RATE`, `freq="1min"`, curve `USD-SOFR-1D`, source
`citivelo_excel_rl`), which is market data read through `MDP/IRSwaps/CITIVELO_EXCEL`
and `Caching` — the addendum states explicitly that this is not an isolation breach. No
`SDRUtils.dealer_direction` or `SDRUtils.stir_flow` import.

**Execution minute, not dissemination**: the X workstream computed its mid in execution
order for both clocks, so the sign is a property of the print at execution and the
reference must be taken there.

**D1 sample.** `fwd_key == 'spot'`, `is_mac == False`, `tenor_label` in the warmed spot
tenor set, and `dev_median` present. The share of prints and of DV01 this retains is
reported per bucket, so the sample is visible rather than assumed.

**Both series are built from the SAME restricted print set.** Otherwise `rho` would
confound sample composition with sign disagreement.

**Join.** `merge_asof` backward with a 2-minute tolerance on the execution minute; the
match rate is reported. Unmatched prints are dropped from D1 only. (The minute store's
nearest-snapshot behaviour has no lag tolerance of its own and will silently serve a
stale snapshot, so the tolerance is enforced on this side.)

**Aggregation.** `X_curve` is aggregated to bucket-minute exactly as X was —
`sum(dv01 * sign(dev_curve))` — and standardised with the same `rolling_scale` rule
(R4). `rho` is reported at print, 1-minute and daily level, per bucket.

**Which `rho` governs the downgrade.** The addendum says "`rho < 0.5` in the deciding
buckets" without naming a level or a pooling rule. Frozen reading: **the DECIDING
quantity is the DV01-weighted pooled 1-minute `rho` across the five decision buckets**,
because the verdict is read off the pooled 1-minute regression; per-bucket `rho` is
reported alongside and a majority of decision buckets below 0.5 also triggers the
downgrade. Sign agreement is the per-print rate over the D1 sample.

**MDE.** `1.96 * SE(sum beta_k, k>=1) / rho` with the pooled dissemination-clock
day-clustered `SE = 0.01280`, which is already fixed by the run.

**Known-answer check on the join, before any `rho` is read**: the per-day median of
`dev_curve` must sit near zero. A timezone error on Citi's ET wire would show up as
`dev_curve` tracking the day's rate drift instead.

**D1 does not re-run the regression.** The addendum licenses `rho` and the
sign-agreement rate, not a second specification with a different X.

### R10a. One restriction forced on D1 after R10 was written, before any rho was read

The warmed minute store **serves a nearest snapshot with no lag tolerance**, and it
logged serving one from *after* the requested instant (measured: 3,600 s ahead for a
00:00 UTC request). A forward-looking reference would make `dev_curve` circular for a
direction diagnostic, so the density of the reference was measured before using it.

Exact-repeat rate of the 1-minute 10y reference by ET hour, 2026-07-13..17:

| ET hour | repeat rate |
|---|---|
| 00:00 | **98.3%** |
| 01:00–16:59 | 4.0–15.7% |
| 17:00–19:59 | 32.7–66.0% |
| 20:00–22:59 | 2.3–3.3% |
| 23:00 | **100.0%** |

That is Citi's published USD session, 01:00–22:59 ET, recovered independently. **D1 is
therefore restricted to prints whose execution minute falls inside 01:00–22:59 ET**, where
a real snapshot exists; the retained share is reported. The 17:00–19:59 ET evening lull is
kept — it is inside the session — and noted. This restriction applies to D1 only. It does
not touch X, Y, the regression, or the verdict.

### R10b. D1's tenor set narrowed, forced by cost — declared before any rho was computed

R10 set the D1 sample as "`tenor_label` in the warmed spot tenor set" (28 tenors). Pulling
all 28 over the full window proved infeasible: each full-window tenor pull costs 190–250 s,
and the 30y pull reached **6.8 GB resident on 167 s of CPU in 17 minutes of wall clock**,
i.e. it was thrashing rather than computing. The pull is therefore chunked by month and the
tenor set is narrowed to the **twelve highest-print-count tenors that together cover all
five decision buckets**:

`1m, 2m, 3m, 6m, 1y` (SFR_FF) · `2y` (TU) · `3y, 5y, 7y` (FV) · `10y` (TY_UXY) ·
`20y, 30y` (US)

Chosen by print count alone, with **no rho computed for any tenor at the time of the
choice**. Narrowing the sample can only reduce `n`; it does not bias `rho`, and the
retained share of prints and DV01 is reported per bucket so the coverage is visible rather
than assumed. Everything else in R10/R10a stands.

### R10c. D1 runs on R10b INTERSECT what the reference pull actually delivered

Declared before any `rho` was read. The reference pull is memory-bound on this machine —
a long-tenor full-window pull reaches 2.4–6.8 GB and one worker died with a numpy
`_ArrayMemoryError` while other sessions held ~50 GB. `run_d1.py` therefore uses the R10b
tenors **for which a reference series is actually cached**, logs the ones excluded, and
reports the retained share of prints and DV01 **per bucket** so the coverage is visible.
A missing tenor reduces `n`; it does not silently block the diagnostic and it does not
change which quantity decides the downgrade.

If a decision bucket ends up with no reference tenor at all, the pooled DV01-weighted
`rho` is formed over the buckets that have one and `R0_RESULT.md` states plainly which
bucket is unmeasured and whether its absence could flip the downgrade call.
