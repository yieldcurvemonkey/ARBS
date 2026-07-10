# MMS Detection Depth — Empirical Research

**Date:** 2026-07-09
**Corpus:** 175499 rows across 42 days
**Cache version:** ptp3-mms-pkg

This document reports empirical data for three detection-depth gaps. No detection code was changed; these are read-only analyses. Each section reproduces the literal check from the Task 8 brief and, where that check is structurally uninformative against the post-gate cache (the pipeline clears the very columns needed to see what a gate excluded), adds a clearly-labeled supplementary analysis that reconstructs the pre-gate signal using existing, already-shipped helper functions — still read-only, still no gate logic touched.

## 4a. IMM-Start MMS False-Positive Analysis

**IMM-labeled trades (`forward_label` starts with `IMM_`) with a UST maturity match in the cached (post-gate) data:** 0

This literal count is expected to be 0 (or near it) by construction: `_match_swaps_to_ust_by_maturity` clears `ust_cusip` / `matched_ust_maturity` for every row the IMM guard excludes, so the post-gate cache cannot show what the gate discarded — it can only confirm the gate isn't leaking. The supplementary analysis below reconstructs the excluded population independently to answer the actual research question.

### Supplementary: reconstructing the gate's exclusion set

**Trades caught by the gate's exclusion rule** (`forward_label` starts with `IMM_`, OR both `effective_date` and `expiration_date` independently land within 1 business day of an IMM date): 30573 (17.4% of the 175499-row corpus)

**Of those, trades whose `expiration_date` independently ties a UST maturity** (gate bypassed via a direct join against the maturity map): 586

**Split by `is_forward`:**

| is_forward   |   n_trades |
|:-------------|-----------:|
| True         |        294 |
| False        |        292 |

**Share labeled `forward_label == 'spot'`:** 43.9% — a spot-starting trade's `effective_date` is simply T+2 from execution, not a deliberate IMM anchor, so a 'both dates near IMM' hit is much more likely coincidental execution timing than a genuine IMM-to-IMM roll.

**Sample (first 10, gate-bypass matches):**

|            trade_id | forward_label   | is_forward   |   tenor_years | package_type   |
|--------------------:|:----------------|:-------------|--------------:|:---------------|
| 3052623400000000401 | 36D             | True         |      0.252055 |                |
| 3063623530000000601 | 1Y1M            | True         |      0.249315 |                |
| 3089254265000000701 | spot            | False        |      5.00274  | PKG-33         |
| 3082293552000000301 | 36D             | False        |      0.252055 |                |
| 3082589626000000401 | 1Y4M            | True         |      0.249315 |                |
| 3088001409000000301 | spot            | False        |      2        |                |
| 3087803218000000401 | 10M             | True         |      0.99726  |                |
| 3107473479000000301 | 1M              | False        |      0.252055 |                |
| 3108688620000000201 | 4M              | True         |      0.249315 |                |
| 3109328317000000701 | 7M              | True         |      1        |                |

**Recommendation:** The literal post-gate check confirms the current implementation doesn't leak (0 IMM-labeled trades retain a UST tie) — that is expected by construction, not evidence the gate is well-scoped. The supplementary reconstruction shows the gate's real reach is far broader than the `IMM_`-label case: the secondary `both_imm` condition alone flags 30,573 trades (17.4% of the corpus), and 586 of those independently tie to a UST maturity. Of those 586, 294 are forward-starting with explicit day/month forward labels (`36D`, `1Y1M`, `4M`, `7M`, ...) — consistent with genuine IMM-to-IMM roll structures that simply don't carry an explicit `IMM_` prefix, and are correctly excluded. But 292 are *not* forward-starting, and roughly 257 of those (586 × 43.9% ≈ 257, i.e. ~88% of the 292) are literally labeled `forward_label == 'spot'` — a spot trade's `effective_date` is just T+2 from execution, so landing near an IMM date is incidental execution timing, not a deliberate IMM anchor. These look like genuine broken-tenor matched-maturity trades being excluded by a guard meant for IMM rolls. **Keep the primary `IMM_`-label check as-is (it is not the source of leakage), but scope the `both_imm` secondary guard to `is_forward == True`** (or add `forward_label != 'spot'`) — this would recover on the order of ~290 likely-genuine MMS trades across the 42-day sample (~7/day) without reopening the door to actual IMM-to-IMM rolls, which the primary check plus an `is_forward`-scoped `both_imm` check would still catch.

## 4b. Near-Clean Broken-Tenor Quantification

**Packaged legs excluded by clean-tenor gate but with UST match:** 4502

**Package census** (packaged, non-OUTRIGHT, size >= 2): all-MMS=486, partial=985, none-matched=27533

**Packages that would flip to fully-matched if near-clean legs were included** (any starting state, i.e. the brief's literal check): 1176

**...of which, genuinely partial -> all-MMS** (>=1 leg already matched on a broken tenor before near-clean inclusion): 391 (of 985 currently-partial packages)

**...and "none -> all"** (zero currently-matched legs; the promotion would rest entirely on coincidental near-clean/UST overlaps with no corroborating broken-tenor evidence anywhere in the package): 785

**Sample (first 10):**

|            trade_id | package_id              | package_type   |   tenor_years | ust_cusip   | expiration_date     |
|--------------------:|:------------------------|:---------------|--------------:|:------------|:--------------------|
| 3059880504000002201 | PTP_3059880487000000501 | PKG-21         |       3.00274 | 91282CQJ3   | 2029-04-15 00:00:00 |
| 3064333348000000301 | PTP_3064333347000000201 | CURVE          |      10.0904  | 91282CPZ8   | 2036-02-15 00:00:00 |
| 3058972594000002501 | PTP_3058972592000002301 | CURVE          |       2.93973 | 91282CQJ3   | 2029-04-15 00:00:00 |
| 3059605409000001501 | PTP_3059605405000001101 | PKG-5          |       5.00274 | 91282CKP5   | 2029-04-30 00:00:00 |
| 3047322467000000701 | PTP_3047322463000000301 | PKG-5          |       2.00274 | 91282CQM6   | 2028-04-30 00:00:00 |
| 3059513637000000701 | PTP_3059513635000000501 | PKG-3          |       2       | 912797SA6   | 2026-10-01 00:00:00 |
| 3059513635000000501 | PTP_3059513635000000501 | PKG-3          |       2       | 912797VA2   | 2026-12-03 00:00:00 |
| 3063963292000000301 | PTP_3063963292000000301 | PKG-3          |       2.93973 | 91282CQJ3   | 2029-04-15 00:00:00 |
| 3063963293000000401 | PTP_3063963292000000301 | PKG-3          |       2.93973 | 91282CQJ3   | 2029-04-15 00:00:00 |
| 3059544256000000601 | PTP_3059544256000000601 | CURVE          |       3       | 91282CCB5   | 2031-05-15 00:00:00 |

**Recommendation:** Naively counting any non-fully-matched package that would become fully-matched if near-clean legs were included yields 1,176 promotions — but 785 of those (67%) start from packages with **zero** currently-confirmed MMS legs, meaning the "promotion" would rest entirely on coincidental round-tenor/UST-maturity overlaps across every leg, with no corroborating broken-tenor evidence anywhere in the package. Restricting to packages that are genuinely partial today (985 packages, ≥1 leg already confirmed via a broken-tenor match) shows 391 (40%) would flip to fully-matched if their near-clean siblings were included — a substantial, well-evidenced population. **Relax the clean-tenor gate for near-clean legs (within 0.1y of a standard tenor) only within packages that already contain ≥1 hard (broken-tenor) MMS match** — this captures the 391 well-evidenced promotions while leaving the 785 zero-evidence packages, and all near-clean OUTRIGHT legs, subject to the existing strict gate.

## 4c. T-Bill vs Short-Note Data Study

**Short-dated (<1Y) MMS matches:** 1921

**By CUSIP prefix (distinct CUSIPs, not trade-weighted):** 912797* (bills): 50, other (notes/bonds): 17

### Supplementary: trade-weighted breakdown via `ust_oi`

| ust_oi   |   n_trades |
|:---------|-----------:|
| 26-Week  |        580 |
| 17-Week  |        501 |
| 3-Year   |        296 |
| 52-Week  |        293 |
| 2-Year   |        251 |

**Trade-weighted bill vs. note split:** 1374 bills (71.5%), 547 notes/bonds with <1Y remaining (28.5%)

**Existing `matched_ust_maturity_trade_confidence` tag vs. bill/note** (does the existing soft-confidence tag already discriminate the two?):

| matched_ust_maturity_trade_confidence   |   bill |   note/bond |
|:----------------------------------------|-------:|------------:|
| high                                    |     73 |           0 |
| low                                     |   1301 |         520 |
| medium                                  |      0 |          27 |

**Sample (first 10, short-dated matches):**

|            trade_id |   tenor_years | ust_cusip   | ust_oi   | matched_ust_maturity_trade_confidence   |
|--------------------:|--------------:|:------------|:---------|:----------------------------------------|
| 3062357944000000401 |      0.189041 | 91282CHM6   | 3-Year   | low                                     |
| 3062357948000000801 |      0.254795 | 91282CHM6   | 3-Year   | low                                     |
| 3062357943000000301 |      0.254795 | 91282CHM6   | 3-Year   | low                                     |
| 3062357947000000701 |      0.254795 | 91282CHM6   | 3-Year   | low                                     |
| 3062357946000000601 |      0.254795 | 91282CHM6   | 3-Year   | low                                     |
| 3062357949000000901 |      0.273973 | 91282CHM6   | 3-Year   | low                                     |
| 3047308985000000401 |      0.227397 | 912797UR6   | 17-Week  | low                                     |
| 3047312298000000101 |      0.252055 | 912797TW7   | 26-Week  | low                                     |
| 3047394015000000501 |      0.210959 | 91282CHM6   | 3-Year   | low                                     |
| 3047440046000000101 |      0.252055 | 912797TW7   | 26-Week  | low                                     |

**Recommendation:** Among 1,921 short-dated (<1Y tenor) MMS matches, the trade-weighted `ust_oi` field splits 71.5% (1,374) true T-Bills (Week-denominated original issue) from 28.5% (547) 2Y/3Y NOTES that simply have <1Y of remaining life — a blanket "exclude all <1Y matches" gate would incorrectly discard more than a quarter of short-dated matches that are legitimate seasoned-note ties, not bill artifacts. The existing `matched_ust_maturity_trade_confidence` tag does not currently distinguish the two: ~95% of both bills (1,301/1,374) and notes (520/547) already land in the same `low` bucket. **Do not add a hard exclusion gate on remaining tenor; instead enrich the confidence/tag logic to expose the `ust_oi`-derived bill/note distinction within the existing `low` bucket** (e.g. a `matched_ust_maturity_instrument_type` field), so downstream consumers can treat seasoned-note ties differently from bill coincidences without losing either population outright.