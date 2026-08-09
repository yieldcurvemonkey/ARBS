# Tape v3 backfill — pilot ledger (Task 5)

Running record for the three-day v3 backfill pilot. See
`.superpowers/sdd/2026-08-08-arbs-tape-v3-generation/task-5-brief.md` for the
full task spec and `task-5-report.md` for the final report.

## Step 1: Frozen code SHA

```
git -C C:/Users/chris/clee/ARBS-v3 log --oneline -1
db206312 fix(tape): gate the v1 DDL bundle behind ARBS_ENSURE_V1_TAPE, default off

git -C C:/Users/chris/clee/ARBS-v3 status --porcelain
(empty — working tree clean)

branch: feat/tape-v3-generation
```

All three pilot days are run against this SHA. No pipeline code is edited
between Step 1 and the end of Step 3.

## Step 2: v2 non-interference baseline

```
backfill_start (UTC): 2026-08-09T01:12:46.928762+00:00

arbs_usd_swap_tape_legs_v2     : count=2323802, max(created_at)=2026-08-09 01:00:41.995267+00:00
arbs_usd_swap_tape_packages_v2 : count=1447960, max(created_at)=2026-08-09 01:00:41.995267+00:00
```

These are the pre-pilot v2 baseline numbers. Task 8's acceptance check
compares post-pilot v2 counts/max(created_at) back against these — if either
changes, the pilot wrote to the v2 tape tables, which must never happen.

## Step 3: Pilot day runs (one at a time, in order)

Command template:
```
ARBS_SUPABASE_ENABLED=0 C:/Users/chris/anaconda3/envs/stir/python.exe -m SDRUtils._swappulse_scripts.run_usdswaps_pipeline backfill --date YYYY-MM-DD --cache-path C:/Users/chris/clee/ARBS/sdr_cache
```

Run from `C:/Users/chris/clee/ARBS-v3` (worktree), `--cache-path` explicit
per the brief (the default falls back to `./sdr_cache` relative to CWD,
which would be empty in this worktree).

| Date | Status | Wall-clock | Notes |
|------|--------|-----------|-------|
| 2026-08-06 | SUCCESS (rc=0) | 169 s | recent era; includes Barchart intraday fetch |
| 2025-06-02 | SUCCESS (rc=0) | 162 s | mid era |
| 2024-03-04 | SUCCESS (rc=0) | 33 s | earliest era; **ERIS curves reach 2024-03** |

Run sequentially by the controller after two subagents parked on background
watchers. A stray full-pytest run was contending with the first attempt and was
killed, then all three days were re-run cleanly so the timings are attributable.

## Step 4: Verification query result

| as_of | legs | ptp% | special_tenor% | event_ts% | matched_ust% | risk% |
|-------|------|------|----------------|-----------|--------------|-------|
| 2024-03-04 | 3106 | 63.7 | 100.0 | 100.0 | 100.0 | **100.0** |
| 2025-06-02 | 3411 | 58.9 | 100.0 | 100.0 | 100.0 | **100.0** |
| 2026-08-06 | 3365 | 46.2 | 100.0 | 100.0 | 100.0 | **100.0** |

v2 non-interference since `backfill_start`: **0** rows in either
`arbs_usd_swap_tape_legs_v2` or `_packages_v2` written after that timestamp
carry a producer other than `swappulse_port`. The pilot did not touch v2.

## Step 5: Extrapolation / go-no-go

**GO — full 611 days, no shortening.**

The pilot existed to answer one question: does ERIS EOD curve history reach back
to March 2024, or is the 2024 tail unpriceable? It reaches. `risk` is 100%
populated on 2024-03-04, so there is no need to shorten the range and no
temptation to publish NULL risk.

Runtime is era-dependent, not uniform — 2024 runs ~5x faster than 2025/2026,
most likely because recent days additionally fetch Barchart intraday data:

- 2024: ~210 days x 33 s  ~= 1.9 h
- 2025: ~249 days x 162 s ~= 11.2 h
- 2026: ~152 days x 169 s ~= 7.1 h
- **Total projection ~20 h** (a flat median-day estimate would say 27.5 h; the
  era split is the better model because the fast era is a fifth of the cost).

That is far above the plan's 9.7 h figure, which covered the tape stage only
and excluded classification. Classification dominates.
