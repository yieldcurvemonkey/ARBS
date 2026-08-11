"""Append the Y (MBO) section to r0_deviations.md without touching the X agent's text."""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
P = os.path.join(HERE, "r0_deviations.md")
MARK = "# R0 --- deviations and interpretations, Y (MBO) workstream"

SECTION = r"""

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
"""

txt = open(P, encoding="utf-8").read()
if "Y (MBO) workstream" in txt:
    print("Y section already present; rewriting it")
    txt = txt.split("\n---\n---\n")[0]
open(P, "w", encoding="utf-8").write(txt.rstrip() + SECTION)
print("appended; file now", os.path.getsize(P), "bytes")
