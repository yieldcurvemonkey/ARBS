# SR3 MBO Explorer — Design

**Date:** 2026-08-07
**Branch:** `feat/sr3-mbo-explorer` (worktree `C:\Users\chris\clee\ARBS-mbo`)
**Input:** `C:\Users\chris\Downloads\glbx-mdp3-20260715.mbo.dbn.zst` (1.38 GB zst)

## Motivation

Every SR3 relative-value study in this repo so far has priced flies off **settles** and assumed a
**2.0 bp per-contract round-trip cost** (see `reference_sfr_fly_conventions`). Under that
assumption nothing is alive: 0/47 in the RV lab, 0/42 in kink-fade v2, 0/360 in outcome-map.

This file is the first dataset in the repo that contains the *actual quoted book*, including the
book of the **exchange-listed butterfly instruments** — where a fly is a single instrument with a
single bid/ask rather than three separately-crossed outrights. The cost assumption is therefore
directly measurable for the first time.

## Dataset profile (measured, single full pass = 23 s)

| Property | Value |
| --- | --- |
| Dataset / schema | `GLBX.MDP3` / `mbo`, DBN v1, parent symbology `SR3.FUT` |
| Records | 72,900,288 |
| Action mix | `M` 56,588,294 · `A` 7,996,036 · `C` 7,943,585 · `F` 246,333 · `T` 125,597 · `R` 443 |
| Instruments | 1,188 mapped, **443 with activity** |
| Opening snapshot | 51,658 records, 393 instruments, flags `40`/`168` (`F_SNAPSHOT | F_BAD_TS_RECV`) |
| Session | 2026-07-15 00:00 → 24:00 UTC; message peak 12:00–13:00 UTC (18.4 M) |

Activity by instrument kind:

| Kind | Active | Messages | Trades | Lots |
| --- | ---: | ---: | ---: | ---: |
| `OUTRIGHT` | 31 | 61,904,608 | 78,502 | 2,251,596 |
| `CALENDAR` (2-leg) | 209 | 5,474,537 | 18,857 | 555,463 |
| `SR3:AB` bundle | 41 | 3,427,106 | 23,759 | 128,303 |
| `SR3:BF` butterfly | 89 | 1,331,044 | 3,871 | 55,051 |
| `SR3:SB` bundle spread | 13 | 540,696 | 396 | 1,056 |
| `SR3:DF` double fly | 40 | 221,144 | 164 | 1,583 |
| `SR3:CF` condor | 15 | 302 | 17 | 126 |
| `SR3:BB` | 1 | 27 | 6 | 14 |

Listed flies are quoted continuously and do trade — `SR3:BF Z6-H7-M7` 8,008 lots,
`SR3:BF M7-M8-M9` (the 12-month fly) 3,067 lots.

## Deliverables

1. `RVUtils/MBO/` — thin engine module, following the `RVUtils/<Topic>/` convention.
   - `symbols.py` — symbology extraction and CME spread-symbol parsing into kind + legs + weights.
   - `source.py` — `DBNStore` wrapper: metadata, vectorised full-file scan, per-instrument extract
     to a parquet cache.
   - `book.py` — numba-JIT L3 order-book replay producing a top-of-book event stream and N-level
     depth snapshots.
   - `metrics.py` — quoted / effective / realised spread, depth, order-flow imbalance, intraday
     profiles, cost in bp and $/contract.
   - `implied.py` — leg-implied spread/fly book from constituent outright books, versus the listed
     instrument's own book.
   - `plots.py` — chart helpers.
2. `notebooks/exploratory/sr3_mbo_explorer.ipynb` — five sections (below).
3. `tests/test_mbo_book.py` — replay correctness.
4. Parquet cache at `C:\Users\chris\clee\mbo_cache\` — **outside the worktree**, so
   `git worktree remove` cannot destroy it. Path is a parameter, not a constant.

## Book replay contract

The non-obvious rules, all confirmed against the file:

- **Book state mutates on `A` / `C` / `M` / `R` only.** `T` and `F` are trade information and must
  be skipped. The file shows the pattern `T`(flags 0) → `F`(flags 0) → `C`(flags 128) on the
  resting order within one packet; applying `F` *and* `C` would decrement twice.
- **Emit top-of-book only at `F_LAST` (128) packet boundaries.** Mid-packet states are transient
  and produce phantom crossed books, which would corrupt any mid-based effective-spread measure.
- **Effective spread** references the mid of the last `F_LAST`-consistent book *before* the packet
  containing the `T`.
- **Snapshot rows** (`F_SNAPSHOT`) apply as adds. Their `ts_recv` is not usable — every instrument
  is stamped `00:00:00` exactly, which also inflates the hour-0 message bin.
- `M` on an unknown `order_id` is treated as an add; `R` clears the instrument's book.
- Prices stay **int64 at 1e-9 scale** internally. Spread and fly prices are legitimately negative.
- Volume is counted from `T` only.

## Notebook sections

1. **Map** — instrument catalog by kind, activity ranking, intraday message-rate profile with the
   12:30 UTC release annotated (annotate the spike; do not assert which release).
2. **Book explorer** — choose any instrument; depth heatmap over time, top-of-book track, trade
   tape. This is the "generic explorer": the engine parameterised by instrument, not a framework.
3. **Cost truth** — quoted, effective and realised spread in bp and $/contract, by instrument kind
   and by hour, plotted against the 2.0 bp per-contract assumption.
4. **Listed versus implied** — the `SR3:BF` book against a fly synthesised from the three outright
   books; which side carries the liquidity, and how often the listed book is tighter.
5. **RV panel** — 1 s / 1 min bid/ask/mid/depth parquet for a chosen fly set, ready for `RVUtils`.

## Verification

Known-answer checks, per the repo's rule that a checking tool must first be run against an input
whose answer is already known:

- **OHLC tie-out.** Reconstruct per-outright open/high/low/close and volume from `T` records and
  compare to the existing Barchart EOD data for 2026-07-15. Volume may tie out short — if it does,
  check for `F` records on outright books with no same-packet `T` (spread-leg executions) before
  calling it a defect.
- **Replay unit test.** Hand-built message sequence with a known resulting book, including the
  `T`/`F`/`C` pattern and a mid-packet transient. Mutate the kernel once to confirm the test fails.
- **Invariants during replay.** No crossed book at `F_LAST` boundaries; trades at or inside the
  book; level size equals the sum of its resting order sizes.

## Phasing

Sections 1–4 first. Queue-position analytics is Phase 3: correct queue position needs the MDP3
priority rules (a price change or a size *increase* sends an order to the back of the queue, a size
decrease retains priority), and it must not block the cost charts.

## Out of scope

- Ingestion into `CurveStore` / MDP. This is one day of data for a research question.
- Multi-day work. The engine takes a path; extending to more days is a loop, not a redesign.
