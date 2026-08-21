<!-- Verbatim return of a preflight investigation agent, 2026-08-20/21.
     Measured on this machine; see the report's own probe list. Kept as
     research evidence, not as a design document. -->

# Preflight scout: CA coverage, measured state

All measurements complete. Final report:

---

# CA COVERAGE — MEASURED STATE, 2026-08-20

Worktree `C:/Users/chris/clee/ARBS-cvx2` @ `61fa6d1a` (feat/convexity-rv2, == main). All probes offline except two deliberate `get_data` calls in §6. Scratch probes: `C:/Users/chris/AppData/Local/Temp/claude/C--Users-chris-clee-ARBS/f3c71cad-b780-41e9-8455-68991655ae55/scratchpad/{t1_scan,t2_ranks,t3_plan,t4_defects,t5_horizon,t6_ledger,t7_cost,t8_panel,t9_golds,t10_servable}.py` + `FACTS.md`.

## 0. HEADLINE — the diagnosis doc's coverage tables are superseded

Two facts invert the picture in `docs/convexityrv/ca_coverage_diagnosis.md`:

1. **The 2024-2026 data hole is closed.** `scripts/warm_sr3_deferred.py` was run manually to completion after the doc was written (doc §13 quotes the 10:36 snapshot; the ledger's final state is 16:19). Measured depth ≥20: 2024 **248/252**, 2025 **247/251**, 2026 **156/159**. The remaining *data* gap is now **2021-2023 (+2018-19)**, not 2024-2026.
2. **The only rebuilt panel on this machine was built without the Golds fix.** `C:/Users/chris/clee/ARBS-cvx/notebooks/data/convexity_rv/strat2_q20_panel.parquet` (mtime 2026-08-20 02:50) was produced in worktree `ARBS-cvx` @ `a9bc31a7`, whose `MDP/IRSwaps/BARCHART_STIRF/rl.py:1122` still carries `max_tenor_from_timestamp_months: 60`. `git merge-base --is-ancestor db95871d a9bc31a7` → **false**. Main carries 66. So Golds coverage in every shipped artifact is the pre-fix number.

**A panel rebuild is a required work item independent of any fetch, and it is the single largest coverage win available at zero network cost.**

`ARBS-cvx2/notebooks/data/convexity_rv/` holds **no live panel** — only a `_baseline_prewarm/` snapshot staged at 23:43 (baseline/pre-warm artifacts, not the current panel).

---

## 1. MEASURED CACHE DEPTH (task item a)

`t1_scan.py`, 38.5 s, 8 shards at `C:\Users\chris\AppData\Local\ARBS\Cache\diskcache\dump\STIRFuturePricer_Cache`.

**Regex match rate: 16,215,786 / 22,604,514 keys = 71.74%**, using the repo's own `RVUtils/ConvexityRV/strat2_q20.py:_STIR_CACHE_KEY` (anchored on `-(?P<sym>SR3[FGHJKMNQUVXZ]\d{2})-`, never on a timestamp). By source, all session times: `BARCHART_TOS_LIVE_STIRF-RL` 12,771,756 / `BARCHART_STIRF-RL` 3,444,030. Total key count has drifted 22,472,084 (doc §1.1) → 22,604,514 — the store is demand-driven; quote a ledger, not a rescan.

**Checker validation (the thing that makes this non-negotiable):** the derived depth map was compared elementwise to the shipped `strip_depth_by_date(Q20Config(max_instruments=20, min_strip_depth=4))`. Result `True`, `n_mine=2097 n_shipped=2097 n_diff=0`.

Contiguous front strip, source `BARCHART_STIRF-RL`, `t == 17:00:00`, NY-readable UTC offset — **exactly what the code gates on**:

| yr | any | ≥4 | ≥8 | ≥12 | ≥16 | ≥20 | max |
|---|---|---|---|---|---|---|---|
| 2018 | 167 | 167 | 167 | 167 | 167 | 41 | 20 |
| 2019 | 253 | 253 | 253 | 252 | 252 | 77 | **27** |
| 2020 | 254 | 253 | 253 | 253 | 253 | 253 | 26 |
| 2021 | 252 | 252 | 252 | 252 | 252 | 187 | 22 |
| 2022 | 253 | 252 | 252 | 252 | **195** | **52** | 24 |
| 2023 | 258 | 258 | 258 | **231** | **51** | **51** | 24 |
| 2024 | 252 | 252 | 251 | 249 | 248 | **248** | 24 |
| 2025 | 251 | 251 | 250 | 249 | 248 | **247** | 24 |
| 2026 | 159 | 159 | 159 | 159 | 157 | **156** | 20 |
| **ALL** | **2099** | **2097** | **2095** | **2064** | **1823** | **1312** | **27** |

Max depth 2024/2025/2026 = **24 / 24 / 20** (task item b, second half).

Corroborating facts, same scan:
- `BARCHART_TOS_LIVE_STIRF-RL` reaches depth ≥20 on **0 dates in every year** — the module docstring's claim, re-confirmed.
- **The UTC-offset defect is essentially gone.** Dates that scan deeper naively than they resolve: **1** (2024-11-28, naive 2 → readable 0). Doc §11.3 measured 51. The `require_readable_offset` filter at `strat2_q20.py:520-530` is doing its job.
- Contract-code frontier: SR3M26 holds 1,706 17:00 dates, **SR3U26 holds 852**, SR3Z26 772, falling to SR3M31 41 and SR3U31 **0**. This step at SR3U26 *is* the 2018-2023 gap.

## 2. WHICH RANKS ARE BUILDABLE (task item c)

`t2_ranks.py`. Rank *r* needs depth *r+3* (`strat2_q20.depth_for_rank`).

**2021-01-01 .. 2026-08-20, 1,425 dates carry an EOD key:**

| yr | dates | Whites r1 (d4) | Reds r5 (d8) | Greens r9 (d12) | Blues r13 (d16) | Golds r17 (d20) |
|---|---|---|---|---|---|---|
| 2021 | 252 | 252 | 252 | 252 | 252 | **187** |
| 2022 | 253 | 252 | 252 | 252 | **195** | **52** |
| 2023 | 258 | 258 | 258 | **231** | **51** | **51** |
| 2024 | 252 | 252 | 251 | 249 | 248 | 248 |
| 2025 | 251 | 251 | 250 | 249 | 248 | 247 |
| 2026 | 159 | 159 | 159 | 159 | 157 | 156 |
| **ALL** | **1425** | **1424** | **1422** | **1392** | **1151** | **941** |

Full history 2018-2026: r1 **2097**, r5 **2095**, r9 **2064**, r13 **1823**, r17 **1312** of 2,099 EOD dates.

**Shortfall — dates holding an EOD key but below the required depth:**

| yr | <d4 | <d8 | <d12 | <d16 | <d20 |
|---|---|---|---|---|---|
| 2018 | 0 | 0 | 0 | 0 | 126 |
| 2019 | 0 | 0 | 1 | 1 | 176 |
| 2020 | 1 | 1 | 1 | 1 | 1 |
| 2021 | 0 | 0 | 0 | 0 | **65** |
| 2022 | 1 | 1 | 1 | **58** | **201** |
| 2023 | 0 | 0 | **27** | **207** | **207** |
| 2024 | 0 | 1 | 3 | 4 | 4 |
| 2025 | 0 | 1 | 2 | 3 | 4 |
| 2026 | 0 | 0 | 0 | 2 | 3 |
| **TOTAL** | **2** | **4** | **35** | **276** | **787** |

## 3. WHAT `ca_coverage_repair.ipynb` DOES AND CONCLUDED (report item 1)

Source `notebooks/backtests/convexity_rv/ca_coverage_repair.py` (844 lines, 12 sections). It is a *report*, not a fixer: the code fixes live in `RVUtils/ConvexityRV/`, and the notebook rebuilds both panels against them, attributes every recovered date to code-vs-fetch from the warm's own ledger, and asserts the invariants.

Five stated findings (`:8-44`):
1. `strip_depth_by_date` gated universe admission on `min_instruments` (the **curve-solve** floor, 12), so a date with 4 good front settles was dropped for *every* rank. Fix: split into `min_strip_depth=4` (universe) / `min_instruments=4` (curve) — `strat2_q20.py:378-405`, `:413`.
2. The deep end was genuine absence; `scripts/warm_sr3_deferred.py` is the fetch.
3. A third defect found en route: 17:00 keys stamped in a non-NY offset match the regex but `get_data` cannot read them (`ny_utc_offset` / `_tz_readable` in `strat2_sofr_convexity.py`).
4. "Looks interpolated" was literally true and `connectgaps=False` was **inert** — the frames were inner joins with zero NaN rows. Fix is `RVUtils/ConvexityRV/ca_plots.py` (`bday_reindex`, `gap_table`, `coverage_note`, `line`), new in this work.
5. `published_values_moved: 0` — every (date, rank) row common to shipped and rebuilt is exactly equal on 23 columns.

Other machinery it introduced/exercised: `trim_to_contiguous_run(..., keep="longest"|"latest"|"none")` + `coverage_by_run` (`:562-590`); `Strat2Config.window_span_tolerance` calendar-span guard (`:591-627`, worst 252-row window measured at 1,289 days); `assert_settle_source`; `cache_only()` now patching `httpx` directly; the Citi Fig-58 tie-out (`:777-800`, asserts corr > 0.96, |diff| < 4bp, Blues within 1bp of 15.40).

Recorded outcome (`ca_coverage_repair_summary.json`, built 10:36): q20 panel 21,671→25,192 rows / 1,410→1,946 dates; near panel 10,840→14,790 / 1,084→1,479; 636 (date,rank) pairs by code, 505 by fetch; 16 shipped rows lost, all 2018-12-06, to vendor cache decay.

**Its conclusion about Golds is now known to be wrong.** `ca_coverage_diagnosis.md:1256-1265` concluded Golds' 3.17bp settle disagreement was "an edge-of-calibration effect… the honest fix is a curve calibrated past rank 17." `db95871d` refuted this five hours later: it is a node-grid defect, fixed by one number. **The doc was never updated and still carries the refuted explanation.**

## 4. THE GAP TO "WHITES/REDS/GREENS/BLUES/GOLDS FULLY COVERED 2021-2026" (report item 2)

The repair notebook's `end` is pinned at `2026-08-18` (`ca_coverage_repair.py:86`) and its remaining-work block filters `d.year >= 2024` (`:770-775`). **It is structurally incapable of seeing the 2018-2023 gap**, which is now the entire remaining gap. Its `resume_command` is likewise `--start 2024-01-01`.

Gap, decomposed:

| # | gap | size (measured) | cure |
|---|---|---|---|
| G1 | Panel built without `db95871d` | Golds gate_ok 2024/25/26 = **41 / 20 / 0** in the only panel that exists; median `max_settle_diff_bp` 2.63 / 4.01 / 3.72 vs a 2.0bp gate | **rebuild the panel from a tree containing `db95871d`** — zero network |
| G2 | Golds strip depth 2021-2023 | **473 dates** short of depth 20 (65 / 201 / 207) | fetch |
| G3 | Blues strip depth 2022-2023 | **265 dates** short of depth 16 (58 / 207) | fetch |
| G4 | Greens 2023 | **27 dates** short of depth 12 | fetch |
| G5 | Golds 2018-2019 | **302 dates** short of depth 20, almost all at depth 19 → **~1 cell each** | fetch (cheapest per date in the whole job) |
| G6 | 2024-2026 residue | 11 dates <d20, 9 <d16, 5 <d12 | fetch |
| G7 | Scheduled warm never runs | 0/12 warmer logs | merge landed; needs one scheduled run to prove |
| G8 | Panel end lags cache | panel `date_max` 2026-08-18; cache has 2026-08-19 at depth 20 | rebuild |
| G9 | Non-CA chart offenders | ~108 traces, 8 notebooks (doc §15 item 5) | unchanged |

**Whites and Reds are already fully covered and need no fetch anywhere** (2 and 4 dates short across 9 years).

## 5. WARM STATUS — HAS 417e533c EVER RUN? (task item b)

**No. The job has never executed via the scheduler.** Evidence:

- `grep -l -i "SR3 EOD settles" C:/Users/chris/clee/ARBS/logs/cache_warmer/*.log` → **exit 1, no match**, across all **12** logs (2026-08-10 .. 2026-08-20).
- Job 4 is `STIRF CME Session` in every one of them.
- Tonight's run (`cache_warmer_20260820_181500.log`, started 18:15:00, **still running** at 23:32, task `ARBS-CacheWarmer-Daily` State=Running) enumerated **16 jobs**, none of them the SR3 settle warm.
- `git reflog show main`: `61fa6d1a main@{2026-08-20 23:15:36}: pull: Fast-forward` — main reached the primary checkout **5 h 00 m after tonight's warmer started**, so tonight's process holds the pre-merge module.
- The scheduled action is `C:\Users\chris\anaconda3\envs\stir\python.exe "C:\Users\chris\clee\ARBS\scripts\daily_cache_warmer.py"`, and `C:/Users/chris/clee/ARBS/scripts/daily_cache_warmer.py:1416` now contains `WarmJob("SR3 EOD settles (depth 20)", warm_sr3_settles_eod)`. **First run that can include it is the next invocation** (weekday 18:15 or the Saturday `--backfill 7`).
- `scripts/warm_sr3_settles.py` writes no ledger/manifest — only log lines. There is therefore no artifact to check beyond the logs. Its commit message claims a manual verification on 2026-08-17/18; both dates are at depth 20 in the cache, but `warm_sr3_deferred` also covered them, so the two cannot be disambiguated.

**What DID run is `scripts/warm_sr3_deferred.py`, manually.** Ledger `C:/Users/chris/clee/ARBS-cvx/notebooks/data/convexity_rv/warm_sr3_deferred_ledger.json` (mtime Aug 19 16:19):

```
635 date entries, 2024-01-02 .. 2026-08-19   (2024:233, 2025:248, 2026:154)
cells requested 9,476  resolved 9,448 (99.7%)   errors 0
depth_after >= 20 on 628/635      depth_before histogram: 0:39 1:48 2:56 3:70 4:75
                                   5:63 6:59 7:64 8:63 9:55 10:43
total wall in fetch loop 19,728 s = 5.48 h
last invocation summary: dates_short 136, calls_made 132, remaining_dates 0
```

## 6. UNIT COST OF A WARM, AND WHETHER EACH BAND NEEDS ONE (report item 4)

### 6.1 The remaining bill, from the repo's own offline planner
`scripts/warm_sr3_deferred.plan(2018-01-01, 2026-08-20, depth=20, protect_min_depth=99)`, 52.8 s, no socket:

```
dates_with_eod 2098   dates_short 872   cells_to_fetch 4,398
distinct contract codes 54   est_seconds 4,039 (the code's model)
```
| yr | dates | cells | cells/date |
|---|---|---|---|
| 2018 | 211 | 1,826 | 8.7 |
| 2019 | 176 | 187 | 1.1 |
| 2020 | 1 | 14 | 14.0 |
| 2021 | 66 | 94 | 1.4 |
| 2022 | 200 | 734 | 3.7 |
| 2023 | 207 | 1,491 | 7.2 |
| 2024/25/26 | 4/4/3 | 19/13/20 | — |

At depth 16: `dates_short 361`, `cells 2,154`, 45 codes.

**1,700 of those 4,398 cells are unservable and would be burned.** `t4_defects.py`: 87 US-gov business days in the window carry no SR3 EOD key at all; **85 of them are 2018-01-02 .. 2018-05-03, before the first key in the store (2018-05-04)** — i.e. before the contract existed. `plan()` unions business days into its candidate set (`warm_sr3_deferred.py:170-174`) with no launch-date floor, so it schedules 85 dates × 20 symbols against a vendor that has nothing. The other two are 2021-04-02 (Good Friday, CME closed) and today.

**Servable remainder: 787 dates / 2,698 cells** at depth 20; **276 dates / ~794 cells** at depth 16.

### 6.2 Unit: one batched `get_data` call per DATE, not per contract
An EOD request (`datetime.date`, not `datetime`) sets `want_eod` → `interval=None` → one day (`MDP/STIRFutures/STIRFutureMDP.py:1023, 1137, 799-801`), and symbols batch into that one call. Per-contract history is **not** back-filled: measured 17:00-date counts per code range 1,706 (SR3M26) down to 41 (SR3M31) and 0 (SR3U31), accumulating one date at a time.

### 6.3 Wall time — the code's cost model is broken (`t6/t7`)
| model | source | 872 dates / 4,398 cells |
|---|---|---|
| `3.38 + 0.169n + 0.4` | `warm_sr3_deferred.py:207-208`, fitted to **2** probes | 4,039 s = **1.12 h** |
| ledger **median** 6.6 s/date | 635 real dates | 5,755 s = **1.60 h** |
| ledger 2.08 s/cell + 3.08/date | 635 real dates | 11,834 s = **3.29 h** |
| ledger **mean** 31.1 s/date | 635 real dates | 27,119 s = **7.53 h** |

Seconds/date is heavily bimodal — quantiles 0.1/0.25/**0.5**/0.75/0.9/0.99 = 2.4 / 3.2 / **6.6** / 58.4 / 66.4 / 138.8 — and **`corr(seconds, cells) = 0.144`**. Cells barely explain the time, so the linear-in-cells model is structurally wrong, not merely mis-calibrated. Plan for **1.5-7.5 h**, budget the upper end, and keep the resumable-ledger pattern.

### 6.4 Per-band verdict
| band | rank | depth | warm needed? | servable dates short | note |
|---|---|---|---|---|---|
| **Whites** | 1 | 4 | **NO** | 2 (2020, 2022) | fully covered |
| **Reds** | 5 | 8 | **NO** | 4 | fully covered |
| **Greens** | 9 | 12 | **marginal** | 35 (27 of them 2023) | cheapest band |
| **Blues** | 13 | 16 | **YES** | 276 (58 in 2022, 207 in 2023) | ~794 cells |
| **Golds** | 17 | 20 | **YES** | 787 (473 in 2021-23; 302 in 2018-19 at ~1 cell each) | ~2,698 cells |

### 6.5 The vendor STILL SERVES pre-2024 deferred settles — **2 deliberate network calls**
`t10_servable.py`. This was the open question that decided whether the 2021-2023 plan is viable at all; every fetch on record is 2024+, and the only pre-2024 datapoint was 2018-12-06 returning nothing. Designed so the invariant cannot break: request the contract at ladder position **depth+2**, so the contiguous prefix cannot extend and no published `ca_bp_q20` can move.

```
2023-06-26  depth 12  next(+1)=SR3U26 absent  PROBE(+2)=SR3Z26 absent
2022-08-09  depth 16  next(+1)=SR3U26 absent  PROBE(+2)=SR3Z26 absent
2023-06-26 SR3Z26: resolved=True (2.0s)  17:00 NY alias written: -04:00
    SR3U26 still absent -> measured depth unchanged at 12
2022-08-09 SR3Z26: resolved=True (0.7s)  17:00 NY alias written: -04:00
    SR3U26 still absent -> measured depth unchanged at 16
```
**Both resolved and both wrote the NY-stamped 17:00 alias the panel reads.** The 2018-12-06 failure is a single decayed date, not a pre-2024 cliff.

### 6.6 The invariant the follow-up CANNOT keep
Both remaining work streams move published values, and this must be planned for rather than discovered:
- The 2021-2023 warm necessarily deepens dates already in the panel (2022 sits at depths 14-18, 2023 at 10-14 — `t8_panel.py` §G), which re-solves their Q20 curve. `warm_sr3_deferred`'s `protect_min_depth=12` exists precisely to refuse this (`warm_sr3_deferred.py:147-157`); a full fix requires `--protect-min-depth 21` and an explicit decision.
- The `db95871d` rebuild moves ranks 15-17 by design (c16 ≤0.307bp, c17 ≤0.832, c18 ≤1.701, c19 ≤2.833, c20 ≤4.411 per its commit message; ranks 1-14 pooled delta exactly 0.0000 pp).

So the follow-up needs a **re-baselined** before/after, not the "published_values_moved: 0" assertion. (The `_baseline_prewarm/` copy staged in ARBS-cvx2 at 23:43 is consistent with that intent.)

## 7. LIVE CODE DEFECTS (report item 5)

**D1 — `Q12STIRT` and `Q16STIRT` still violate `max_tenor ≥ 3·n_instruments + 6`.** Measured by parsing `MDP/IRSwaps/BARCHART_STIRF/rl.py`:
```
USD-SOFR-1D-Q12STIRT: n=13 last=SFRCM13 max_tenor=39  rule=45  SHORT BY 6
USD-SOFR-1D-Q16STIRT: n=17 last=SFRCM17 max_tenor=51  rule=57  SHORT BY 6
USD-SOFR-1D-Q20STIRT: n=20 last=SFRCM20 max_tenor=66  rule=66  OK
```
(`rl.py:1066`, `:1093`, `:1139`.) Both drop their terminal calibration instrument from the node grid and price it by extrapolation, exactly as `db95871d` describes. Explicitly flagged-not-fixed in that commit. **These two are the curves the nightly warmer actually builds** (`daily_cache_warmer.warm_stirf_cme_session` → `stirf_curve_service.py backfill --curve USD-SOFR-1D-Q12STIRT/Q16STIRT/…MIX23`), so the defect is live in the production curve store, not latent.

**D2 — the horizon is now wrong in the *other* direction on every shallow date.** `build_q20_pricer` (`strat2_q20.py:700-701`) rewrites `curve_cfg["instruments"]` to `SFRCM1..n_inst` but leaves `max_tenor_from_timestamp_months` at the config's fixed 66. `t5_horizon.py`, 5 real builds, `network_calls_blocked delta = 0`:

| depth | n_inst | date | last instr matures | max node | nodes | **nodes past last instrument** | horizon | rule 3n+6 | excess |
|---|---|---|---|---|---|---|---|---|---|
| 6 | 6 | 2024-12-26 | 2026-09-16 | 2028-01-26 | 26 | **11** | 37m | 24m | +13m |
| 10 | 10 | 2024-05-10 | 2026-12-16 | 2028-01-26 | 31 | **9** | 45m | 36m | +9m |
| 12 | 12 | 2023-11-09 | 2026-12-16 | 2028-01-26 | 35 | **9** | 51m | 42m | +9m |
| 16 | 16 | 2022-09-20 | 2026-09-16 | 2028-01-26 | 45 | **11** | 64m | 54m | +10m |
| 20 | 20 | 2024-12-31 | 2030-03-20 | 2030-03-20 | 35 | **0** | 63m | 66m | 0 |

This is the exact condition `rl.py:1133-1136`'s own comment says to avoid ("wider would add nodes no instrument constrains"). **Exposure: 785 / 2,097 dates = 37.4% at contiguous depth 4-19** (2018:126, 2019:176, 2021:65, 2022:200, 2023:207, 2024:4, 2025:4, 2026:3). The rule violation is measured; the **CA impact is NOT measured** — the affected nodes sit beyond the last calibration instrument, and the 2.0bp settle-agreement gate bounds the per-row damage.

**D3 — the recurring warm is blind to exactly the dates it exists to fill.** `scripts/warm_sr3_settles.py:100-112` forces `min_instruments=1`, but `9df2875a` moved the universe floor from `min_instruments` to `min_strip_depth` (default 4, and `Q20Config.__post_init__` *raises* below 4). `_depth_by_date` never passes `min_depth`. Measured on a synthetic shard (`t4_defects.py`):
```
strip_depth_by_date(min_depth=1)     -> {2026-07-08: 2, 2026-07-09: 6}
warm_sr3_settles._depth_by_date(...) -> {                2026-07-09: 6}
DEPTH-2 DATE VISIBLE TO THE WARM? False
```
Consequence: `run_warm` reads `before[d] = 0` for any date below depth 4, so a genuine 2→3 gain is invisible to its `depth_gained` acceptance test at `warm_sr3_settles.py:174, 190-192, 201-204`. Given the ledger recorded **213 dates at depth 0-3 before the warm**, this is the common case for a cold date, not an edge case. `warm_sr3_deferred.plan()` is correct — it passes `min_depth=1` explicitly (`warm_sr3_deferred.py:165`).

**D4 — the test guarding D3 never calls the function it names.** `tests/test_warm_sr3_settles.py:44` `test_depth_by_date_sees_dates_a_floored_config_hides` asserts on `strip_depth_by_date(cfg, min_depth=1)` directly (`:84-86`), never on `W._depth_by_date`. It passes while the function it is named for is blind.

**D5 — the recurring warm has no `d >= today` guard.** `warm_sr3_settles.main` defaults `start = end = today` (`:230-231`) and the job runs at ~18:17 ET. `warm_sr3_deferred.py:184-188` and `ca_coverage_diagnosis.md:1043-1047` state the opposite doctrine: warming a date during its own session "stamps an intraday print with a settlement key — the exact confusion `assert_settle_source` exists to prevent, arriving through the back door." The two jobs disagree. Impact **not measured** (the job has never run); the 18:15 slot is after the 15:00 ET SR3 settle, so this may be benign, but it is unasserted.

**D6 — `db95871d`'s SCOPE paragraph contradicts its own diff.** It states "the override is applied inside `build_q20_pricer`'s `curve_cfg` rewrite … rather than in `_STIRF_CURVE_CONFIGS` — editing the latter would silently change the production Q20 curve for every other consumer." The diff edits `_STIRF_CURVE_CONFIGS` (`rl.py:1119-1139`); `build_q20_pricer` rewrites `instruments` only. Blast radius is in practice nil — no scheduled job builds Q20STIRT (the warmer builds Q12/Q16/MIX23) and there is no Q20 curve store — but the statement on record is false.

**D7 — `plan()`'s `est_seconds` is ~11× optimistic on the slope** (`warm_sr3_deferred.py:207-208`); see §6.3. It is printed to the operator as the run's headline budget.

**D8 — `ca_coverage_diagnosis.md:1256-1265` still carries the explanation `db95871d` refuted** (Golds as an "edge-of-calibration effect" requiring a curve past rank 17), and its §15 remaining-work table is scoped to 2024+ and now describes work that is done.

## 8. INDEPENDENT VERIFICATION OF THE GOLDS FIX

`t9_golds.py`, 15 depth-20 dates sampled across 2021/2023/2024/2025/2026, all also present in the panel at rank 17, `network_calls_blocked delta = 0`:

```
rank-17 max_settle_diff_bp, 2.0bp gate, 15 sampled dates
  PANEL (this machine, tenor 60): median 2.86bp, pass  6/15
  ARBS-cvx2 @ main (tenor 66)   : median 1.05bp, pass 15/15
```
Per-date: 2026-03-23 4.363→1.682; 2025-08-12 4.843→1.872; 2024-02-06 3.143→1.231; 2021-03-01 2.239→0.637. This is a 15-date sample; `db95871d`'s own 963-date pass-rate table (2024 5→100%, 2025 0→93.7%, 2026 0→100%) is the corroborating population measurement. Do not extrapolate to "all 1,312 dates" without the rebuild.

## 9. CURRENT PANEL STATE (the artifact a follow-up would start from)

`C:/Users/chris/clee/ARBS-cvx/notebooks/data/convexity_rv/strat2_q20_panel.parquet` — 32,540 rows / 2,068 dates / 2018-05-04..2026-08-18. Companion `strat2_q20_skips.json`: `universe_dates 2096 → ok 2066`, `swap_ref_mismatch 27`, `q20_build 1`, `blocked_requests 4`, `dates_by_max_rank {16: 351, 17: 1302}`.

Gate-passed dates (this is the **pre-`db95871d`** picture):

| yr | r1 | r5 | r9 | r13 | r17 |
|---|---|---|---|---|---|
| 2020 | 159 | 202 | 251 | 251 | 241 |
| 2021 | 243 | 250 | 250 | 246 | **85** |
| 2022 | 60 | 249 | 247 | 186 | 46 |
| 2023 | 85 | 242 | 218 | 49 | 28 |
| 2024 | 209 | 246 | 236 | 239 | **41** |
| 2025 | 237 | 248 | 247 | 246 | **20** |
| 2026 | 153 | 157 | 139 | 155 | **0** |
| **whole panel** | **1146** | **1594** | **1788** | **1762** | **577** |

Gate components pooled: `gate_covered` 1.000 at every rank; the binding condition is `gate_settle_agrees` — r1 0.572, r5 0.775, r9 0.896, r13 0.999, **r17 0.446**. r1's 2022/2023 failures (0.241 / 0.341, median diff 4.21 / 2.23bp) are the documented pre-2021-meeting-node front-end degeneracy plus a threshold sitting inside the distribution — **a separate problem from strip depth, and one no fetch touches**.

## 10. CORRECTIONS TO THE TASK BRIEF'S POINTERS

- `local_cached_dates` is at **`RVUtils/ConvexityRV/strat2_sofr_convexity.py:1001`**, not in `strat2_q20`. `strat2_q20` exports `strip_depth_by_date` (`:441`); the depth-returning sibling on the near-pack path is `strat2_sofr_convexity.local_strip_depths`.
- The SR3 warm job added in `417e533c` is **`scripts/warm_sr3_settles.py`** (+ `scripts/daily_cache_warmer.py:1416`, + `tests/test_warm_sr3_settles.py`). It is distinct from `scripts/warm_sr3_deferred.py`, which is the one that actually ran.
- `db95871d` changed `MDP/IRSwaps/BARCHART_STIRF/rl.py` (1 value + comment), `RVUtils/ConvexityRV/strat2_q20.py` (docstring only), `tests/test_q20_curve_horizon.py` (new, 215 lines).
