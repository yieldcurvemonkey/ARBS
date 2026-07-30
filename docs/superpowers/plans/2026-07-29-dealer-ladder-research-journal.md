# Dealer Ladder — Cleanup, Backfill, and Signal Research Journal

**Started:** 2026-07-29
**Mission:** (A) clean up + merge PR #354, (B) build the full ~6-month dataset, (C) run the
gate-ordered signal-research program (plan Task 10, G0–G5) and report a verdict.
**Autonomy:** full pre-approval for design/implementation decisions; every fork documented here.

Plan: `docs/superpowers/plans/2026-07-14-dealer-ladder-infrastructure.md`
Specs: `docs/superpowers/specs/2026-07-14-dealer-positioning-delta-ladder-design.md`,
`docs/superpowers/specs/2026-07-12-stir-dealer-direction-classifier-design.md`
Audit: `docs/superpowers/audits/2026-07-15-sdr-dealer-positioning-feasibility-audit.md`

---

## 0. Baseline established 2026-07-29 (read-only probes)

**Branch state** (`feat/stir-dealer-ladder`, worktree `C:\Users\chris\clee\ARBS-ladder`):
38 commits ahead of `origin/main`, 63 behind. Plan Tasks 1–8 + A1 + A2 + the HY module are
recorded complete in `.superpowers/sdd/progress.md`. Task 9 (operational backfill) is partial;
Task 10 (research) not started.

**DB baseline (remote Supabase prod, read-only probe):**

| table | state |
|---|---|
| `arbs_stir_direction_v1` | 5 days only: 07/02 (693u, 26 UNK), 07/09 (550u, 79 UNK), 07/10 (562u, 3 UNK), 07/13 (585u, **192 UNK = 32.8%**), 07/14 (974u, 40 UNK). Mixed vintages (classified_at 07/13→07/24). |
| `arbs_stir_ladder_prints_v1` | 07/02 511/693 units, 07/09 390/550, 07/10 217/562, 07/13 101/585, **07/14 0/974**. FED_FUNDS space only on 07/02 (later vintage). |
| `arbs_stir_book_marks_v1` | ENTRY marks only (1219 rows). **Zero EOD marks.** |
| `arbs_stir_tick_size_v1` | 2026-06-10 → 2026-07-21, 28 days, 6001 rows. |
| `arbs_usd_swap_tape_legs_v2` | 2024-03-01 → 2026-07-29 continuous. **Full 6-month window available.** |

**Consequences for the plan:**
1. The coverage collapse is confirmed (39%/17%/0% on 07/10/13/14) and is the thing the
   dates-path FUTURES risk model is expected to fix.
2. Tick calibration only exists for 06/10–07/21. A 6-month backfill needs calibration for
   the whole window. **Decision (see D1)**: strictly-trailing per-chunk calibration.
3. No EOD marks exist at all — the marks phase has never been run.

---

## Decisions ledger

**D1 — Trailing calibration windows for the 6-month classifier backfill.**
`backfill_stir_direction_range.py` computes calibration ONCE for the window and passes it to
every day-worker. Using one window that overlaps or postdates the classified days injects
look-ahead into `p_flip` / `direction_confidence` / `curve_suspect_trade`, which the ladder's
default `"expected"` weighting consumes. Therefore the backfill runs in **monthly chunks with
a strictly-trailing 30-calendar-day calibration window** (`calib_end = chunk_start − 1 day`).
Cost: one extra `run_calibration` per chunk (ticks-only mode: pure SQL + pandas, no curve
builds — cheap). Benefit: `p_flip` at day *d* uses only data before *d*, so G1's no-lookahead
audit covers the confidence layer too, not just the visibility timestamps.

**D2 — `code_vintage` stamped from the worktree git SHA at CLI start.**
Resolved once per process via `git rev-parse HEAD` on the module's repo root, with a
`"unknown"` fallback so tests and detached environments never crash. Column added to both
`arbs_stir_direction_v1` and `arbs_stir_ladder_prints_v1` via idempotent `ALTER TABLE ... ADD
COLUMN IF NOT EXISTS`.

---

**D3 — Sign convention was inverted in three of four bucket spaces (found 2026-07-29).**
The persisted table settled it: over 07/02–07/13 OUTRIGHTs, MEETING is 868/868 PAID-negative
and 249/249 RECEIVED-positive, but FED_FUNDS is 288 PAID-**positive** / 74 RECEIVED-**negative**
and FUTURES is split 348 negative / 461 positive *on PAID alone*. A per-space constant cannot
produce mixed signs inside one space, so `_RL_SIGN_BY_SPACE` was masking a deeper defect: the
legacy `<ROOT>CM<n>` fetch path calibrated the risk curve to vendor settlement prices on nodes
seeded from the decision-time curve, and where those disagreed the Jacobian degraded — giving
deltas that were mis-scaled as well as flipped (|ladder sum| 55,575 and 67,882 against
structure DV01s of 8,274 and 10,126). Collapsed to one `RL_DELTA_TO_FUTURES_EQ = -1.0`.
**Every ladder row written before this is invalid and is being rewritten.**

**D4 — Both futures spaces are now curve-implied; the vendor fetch is gone.**
`contract_grid` mirrors `STIRFutureMDP`'s `<ROOT>CM<n>` resolution exactly, so bucket keys stay
compatible (`SFRU26…`, `FFN26…`). SR3 agrees with the fetch path to ≤0.03%; deferred ZQ buckets
to ~0.001%. The **front ZQ month lands ~14% below** the legacy path because the fetched pricer
carried one extra same-day fixing that was **not yet published** at the decision timestamp — a
one-day look-ahead in the path being replaced. Also fixed `SERFF_BASIS`, which had been failing
for all but the first day or two of each month (only 4 of 456 eligible units on 07/02 produced
basis rows) because the front SR1 contract and its paired IRS leg were built without fixings.

**D5 — 07/13's 192 UNKNOWN (32.8%) are infrastructure, not data.** Flag histogram:
85 `BARCHART_TOS_LIVE_STIRF-RL returned no data`, 80 `maximum recursion depth exceeded`,
27 `403 Client Error: Forbidden`. All three are the vendor-fetch / rate-limit / curve-anchor
family that later fixes addressed. The recursion failure also hit 07/09 (19) and 07/14 (32) and
is tracked as an open item — re-run under the current vintage is the test.

**D6 — Realized window: no shrinkage needed (probed 2026-07-29).** At 14:30 ET on a sparse grid
from 2025-12-15 to 2026-07-15, `USD-SOFR-1D-Q12xM12STIRT` and
`USD-OIS-Q12xM12STIRT-SERFFX-MIX23` both build at every probe point (17–23 nodes), and the Citi
Velocity independent mid resolves at every one. So the planned **2026-01-12 → present** window
stands. One caveat for G0/G3: the Citi workbook's sheets run Mon 00:01 → Fri 11:59, so
**Friday-afternoon prints have no independent mid** (2026-01-30 and 2026-05-15 both fell back to
11:59). Friday PM is therefore an explicit hole in the pseudo-label study, not a silent one.

## Phase log

### Phase A — PR #354 cleanup

- [x] A.0 Baseline probes + journal (2026-07-29)
- [ ] A.1 Worktree hygiene + merge `origin/main`
- [ ] A.2 FUTURES risk model → curve-implied dates path (+ FF/ZQ if feasible)
- [ ] A.3 `code_vintage` column + CLI stamping
- [ ] A.4 Re-classify 07/02–07/14 at one vintage; re-project; diagnose 07/13 UNKNOWN
- [ ] A.5 EOD marks + Task 9 verification SQL
- [ ] A.6 Fast gate + goldens → PR body → merge

### Phase B — full-window dataset

- [ ] B.1 Intraday curve availability probe at the window start
- [ ] B.2 Classifier backfill over the realized window
- [ ] B.3 Projection + EOD marks over the window
- [ ] B.4 Coverage table

### Phase C — signal research (G0–G5)

- [ ] C.0 Pre-registration written before any G4 run
- [ ] C.1 G0 labels/provenance + Citi-mid pseudo-label flip study
- [ ] C.2 G1 arrival integrity
- [ ] C.3 G2 mechanism ordering (HY/LLS)
- [ ] C.4 G3 circularity battery
- [ ] C.5 G4 pre-registered price prediction + secondary grid
- [ ] C.6 G5 economics/capacity
- [ ] C.7 Findings doc + notebook + completeness pass
