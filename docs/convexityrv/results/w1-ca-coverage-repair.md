# W1 — SOFR convexity-adjustment data, repaired for all five pack colours

Measured on this machine, 2026-08-20/21, worktree `ARBS-cvx2`, branch
`feat/convexity-rv2`. Every number carries the command that produced it.

The brief asked to "fully fix SOFR futures convexity adjustment data for whites,
reds, greens, blues, golds, using the query, mdp/pricer, timeseriesbuilder
pattern". It turned out to be two problems wearing one name: a **coverage**
problem in the SR3 settle cache, and a **correctness** problem in the shared
`Query` / `TimeseriesBuilder` code path. Both are addressed; the correctness half
was the larger surprise.

---

## 1. Correctness — the shared path was wrong three ways

`RVUtils/ConvexityRV` computes its own adjustment and ties out to Citi's
published screen. The repo-wide path — `IRSwapValue.CVX_ADJ`, reached by
`TB.IRSwapsTB.sfr_cvx_adj` — is a *second, independent* implementation of the
same quantity, and nothing external had ever graded it.

| # | defect | measured error |
|---|---|---|
| 1 | matched swap built **annual/annual**, not Citi's quarterly/quarterly | **−4.585 / −5.816 / −5.884 bp** on three dates 2023–2025 |
| 2 | `_as_percent` magnitude heuristic applied to a percent quantity | up to **+9,405 bp**, on every SR3 priced above 99.00 |
| 3 | price panel unconditionally `bfill().ffill()`-ed | look-ahead **inside the price series** |

Defect 1 is larger than the quantity it corrupts: the Whites and Reds adjustment
runs 1.3–6.8 bp, so a −5 bp bias changes its sign. Defect 2's trip threshold is
an SR3 price above 99.00 — the entire ZIRP window, **2020-03 to 2022-06**, for
Whites, Reds and Greens, and the deferred strip into 2021.

Both were confirmed twice, independently. A separate agent, on a different
instant and by a different route, priced the WHITES pack at 2026-08-19 15:00 ET
and got **−5.81 bp** shipped versus **+0.19 bp** with a quarterly matched leg.

All three are now pinned to **Citi's Figure 58** (Rates Vol Lab, 12-Jun-2023,
13 rows, close 6/9/2023) — the same rows that grade the package's own kernel, so
the two implementations are held to one external standard. The annual variant is
retained as a **negative control that must fail**.

Per-date failures are also recorded rather than swallowed: both loops were bare
`except Exception: pass`, so "the vendor has no print" and "the pricer raised"
produced an identical gap while needing opposite fixes.

**Cache invalidation is derived, not hand-bumped.** The convention travels in the
query's `value_kwargs`, which is part of `_query_fingerprint` and therefore of
both the mapping-cache key and the `data/ts` symbol. Rows computed under the old
convention are orphaned rather than silently served — which matters because
`data/ts` is read *before* the curve store.

### What the mutation harness caught

4/4 killed, and two of those kills were the harness earning its keep:

* Reverting the **default** matched frequency **survived** the first draft. Every
  tie-out passed `matched_frequency="Q"` explicitly, so none exercised the
  default — which is what every production caller gets. The suite pinned the
  knob and left the wire loose.
* The swallow mutation survived a **source-text** assertion, because replacing
  the recorder with `pass` leaves `except Exception as exc:` in place. Rewritten
  behaviourally, it immediately found a live `NameError` that no source-text test
  could have.

---

## 2. Node horizons — Q12 and Q16 never reached their terminal instrument

`db95871d` measured this on `Q20STIRT`, fixed that one curve, and flagged the
rest; `test_q20_curve_horizon.py` then pinned the rule for `Q20STIRT` only, which
is why the same defect sat undetected in six siblings.

| curve | ladder | horizon | needs | verdict |
|---|---|---:|---:|---|
| `Q12STIRT` | SFRCM1..13 | 39 | 45 | **short 6** → fixed |
| `Q16STIRT` | SFRCM1..17 | 51 | 57 | **short 6** → fixed |
| `Q20STIRT` | SFRCM1..20 | 66 | 66 | OK |

Seven mixed curves (including the `MIX23` family) are also short by 6–18 months
and are **not** changed: each interleaves a monthly ladder with the quarterly one
and feeds the production intraday store, so widening the horizon moves a live
series and needs its own before/after. They sit on an explicit allowlist carrying
the measured shortfall, so the defect is recorded in code and cannot grow.

The rule is derived from the ladder, not from a length. A first draft applied
`3·n_instruments + 6` to every curve and reported nine violations, **seven of
them false** — the mixed curves interleave `SERCM`/`FFCM`/`RACM` monthlies, so
`n_instruments` is not the quarterly depth.

---

## 3. Coverage — the warm

`scripts/warm_sr3_deferred.py --start 2020-01-01 --end 2026-08-20 --depth 20
--protect-min-depth 21 --max-calls 600`

**486 dates, 456 gained depth, 451 reached depth 20, 0 failed, 5,977 s (1.66 h).**
The 35 that fell short are the frontier and the closed sessions: 2021-09-16..22
need contract 20 (`SR3U26`, whose own history starts later), 2021-04-02 is Good
Friday and 2020-01-01 is New Year's Day.

The default `--protect-min-depth 12` exists so a repair moves no
previously-published value. The brief says *fully fix*, so this run deliberately
deepened everything — which means the deliverable is a **quantified before/after**
rather than a "nothing moved" assertion.

Two things were established before spending the time:

* **The vendor still serves pre-2024 deferred settles.** Every fetch on record
  was 2024+, and the single pre-2024 datapoint had returned nothing. Two
  deliberate calls at ladder position `depth+2` — chosen so the contiguous prefix
  could not extend and no published value could move — resolved `SR3Z26` for both
  2023-06-26 and 2022-08-09, and both wrote the NY-stamped 17:00 alias the panel
  reads. The 2018-12-06 failure is one decayed date, not a cliff.
* **A cold date returns the full 20-deep strip** (`depth_before: 0 → resolved:
  20`), so the repair was never limited by vendor coverage.

### Contiguous strip depth after the warm

`notebooks/backtests/convexity_rv/_measure_ca_depth.py`, run through the panel's
own gate function (`strip_depth_by_date`, `min_depth=1`, because the shipped
universe floor of 4 hides exactly the shallow dates a coverage report exists to
show).

| colour | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---:|---:|---:|---:|---:|---:|---:|
| Whites | 254 | 253 | 252 | 258 | 252 | 251 | 160 |
| Reds | 254 | 253 | 252 | 258 | 252 | 251 | 160 |
| Greens | 253 | 253 | 252 | 258 | 252 | 251 | 160 |
| Blues | 253 | 252 | 252 | 255 | 252 | 251 | 160 |
| Golds | 253 | **223** | 252 | 254 | 252 | 251 | 160 |

against, before, Blues 195 (2022) / 51 (2023) and Golds 187 (2021) / 52 (2022) /
51 (2023). **2020–2026 is complete for every colour Citi prints**, with Golds 2021
the only soft spot.

Still open: 2018 Golds (41/167) and 2019 Golds (77/253), outside the 2021–2026
backtest window, deferred to a second pass.

---

## 4. The panel rebuild, and what moved

`scripts/strat2_q20_build.py` → **34,841 rows × 2,070 dates**, 162 s, 4 blocked
outbound requests (attempted, refused, nothing sent).

### Dates on which each colour is *usable* (gate applied)

| colour | year | before | after |
|---|---|---:|---:|
| Greens | 2023 | 218 | **243** |
| Blues | 2022 | 186 | **236** |
| Blues | 2023 | 49 | **229** |
| Golds | 2021 | 85 | **213** |
| Golds | 2022 | 46 | **241** |
| Golds | 2023 | 28 | **244** |
| Golds | 2024 | 41 | **250** |
| Golds | 2025 | 20 | **241** |
| Golds | 2026 | **0** | **159** |

### The binding gate condition, by rank

Settle agreement is what binds, and it shows the node-grid fix landing exactly
where predicted and nowhere else:

| rank | colour | median \|settle diff\| | pass rate |
|---|---|---|---|
| 1 | Whites | 1.601 → 1.596 | 0.572 → 0.572 |
| 5 | Reds | 0.629 → 0.625 | 0.775 → 0.775 |
| 9 | Greens | 0.419 → 0.417 | 0.896 → 0.898 |
| 13 | Blues | 0.305 → 0.276 | 0.999 → 0.998 |
| 17 | **Golds** | **2.239 → 0.669** | **0.446 → 0.990** |

On the 32,540 rows present in both panels, `ca_bp` moved by a median of −0.0000
at every rank, with p95 |diff| from 0.0006 bp (Whites) to 0.0553 bp (Blues). So
no previously-published adjustment moved materially; what moved is Golds'
`max_settle_diff_bp`, the gate diagnostic the fix targeted.

### A documented "finding" that was really an artifact

`test_blues_coverage_is_the_binding_constraint` asserted the data hole *as a
finding* — `by_year[2023] < 80`, "the 2023 collapse is the finding". Its own
comment said what to do if it ever failed upward. It did. Blues went from **503
to 1,358** pack-days and Golds to **1,348**, and the test is now inverted and
renamed.

The lesson stays attached to it: a coverage number measured on a demand-driven
cache is a statement about what has been fetched, not about the market. Pinning
one as a finding guarantees the test fails the moment the data is repaired.

---

## 5. What is *not* fixed, and is not claimed to be

* **Whites' gate pass rate stays at 0.572** on a median settle disagreement of
  1.60 bp. That is the documented front-end degeneracy — the `*STIRT` node grid
  comes from a central-bank meeting map that starts 2021-04 — and no amount of
  fetching touches it. Separate problem.
* **The recurring warm is repaired on this branch only.** The roster entry
  `WarmJob("SR3 EOD settles (depth 20)")` *is* present in the primary checkout,
  which is the tree the scheduled task runs, so the job will fire. But the
  primary checkout greps **0** for both `min_depth=1` and `_session_has_settled`,
  so until this branch merges the scheduled job still runs with the blind depth
  scan and no settle guard.
* **The `sfr_cvx_adj` timeseries cache is orphaned by design.** The fingerprint
  change means every previously cached CA row is ignored rather than served. That
  is correct — orphaning beats silently serving old-convention numbers — but a
  fresh backfill has not been run.
* **2018–2019 Golds** remain thin, as above.

---

## 6. Repairs, by commit

| commit | what |
|---|---|
| `50e5fb29` | the three shared-CA-path defects, mutation-checked 4/4 |
| `87edd3e6` | `Q12STIRT` / `Q16STIRT` node horizons + a rule test across the whole curve table |
| `897f69dd` | the recurring warm: blind depth scan, a test that never called its own function, no unsettled-session guard |
| `d9a4ee15` | the warm itself, and the reader that grades it |
| `43022928` | panel rebuild with the quantified before/after |
| `c1bdbbaf` | retire the "2023 collapse" finding |
| `4f902ad3` | CFTC positioning: three days of look-ahead, and the missing dealer leg |
