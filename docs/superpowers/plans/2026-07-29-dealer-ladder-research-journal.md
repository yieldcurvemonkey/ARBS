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
