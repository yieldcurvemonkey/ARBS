# Preflight: editing `scripts/daily_cache_warmer.py`

Paste this into a new session before touching the nightly warmer. Everything below was
learned by getting it wrong first, on 2026-08-20/21.

---

You are working on `scripts/daily_cache_warmer.py` in the ARBS repo — the nightly EOD
cache warmer. Read this before editing anything.

## What it is

18 jobs, run by two Windows scheduled tasks, both executing
`C:\Users\chris\clee\ARBS\scripts\daily_cache_warmer.py` **from the primary checkout on
`main`**:

- `ARBS-CacheWarmer-Daily` — weekdays 18:15, today only
- `ARBS-CacheWarmer-WeekendBackfill` — Saturdays 10:00, `--backfill 7`

Logs land dated in `logs/cache_warmer/`, 60 retained. Exit code means something:
`0` all OK, `1` a job FAILED, `2` only SKIPPED.

A full run takes about **1h26m to 2h52m**. The long poles are UST universe tags EOD
(~2,645 s), STIRF CME Session (~1,650 s), STIRFO (~1,540 s), swaption cube (~1,120 s),
UST timeseries values (~1,150 s) and CitiVelo intraday (~1,090 s). If you add a job,
that envelope is what you are spending.

## The five things that will bite you

**1. Your edit does not run until it is merged.** The cron executes from the primary
checkout on `main`. Work in a worktree, but do not conclude anything from a nightly log
until your commit is actually on `main`. On 2026-08-21 the log showed a merged pre-flight
change alongside an *unmerged* job change, in the same run — half my work was live and
half was not, and the log looked self-contradictory until I checked what was deployed.

**2. `--list` is the cheapest correctness check you have. Run it after every edit.**

```
ARBS_SUPABASE_ENABLED=0 <env>/python.exe scripts/daily_cache_warmer.py --list
```

It imports the module, which runs `utils.warm_jobs.check`, which **raises** if a value
job precedes a store warm it reads. Order is enforced at import, not by convention.

**3. Job order is load-bearing, and getting it wrong does not fail.** A value job that
runs before its store warm reads an unwarmed cache and **falls through to live Excel**.
It will look like it worked. `provides` / `requires` on each `WarmJob` is what the check
consults.

**4. SKIPPED and FAILED do different things to downstream jobs, on purpose.** A job
SKIPPED for an unusable Excel wrote *nothing*, so its consumers still run against the
cumulative cache. A job that FAILED may have written half a partition, so its consumers
are held back. Do not collapse them.

**5. A job that returns an empty frame is reported as OK.** The runner prints the shape
it is handed. `GSQUANT USD-OIS EOD OK (68.6s, 0 rows x 0 cols)` ran for a month before
anyone noticed. **If you add or edit a value job, make it refuse to call an empty result a
success.** Job 1 now raises; copy that.

## The subtlest failure mode in the file

Several MDPs opt into CurveStore **fast paths** that *read* a store and return `{}` on a
miss — `_supports_curve_store_raw_curve_fast_path`,
`_supports_curve_store_analytics_fast_path`. They never build.

So a value job can be perfectly correct, its curves can build fine standalone, and it
still returns nothing because nobody warmed the store. That is exactly what happened to
the GS Quant job: `asset=USD-OIS` partitions stopped on 2026-08-03 and the job read an
empty store every night.

**If a job's provider is a store rather than a wire, check that something warms it.**
`scripts/warm_gsquant_curve_store.py` is the pattern: build, then write *both* the raw
partition (`write_day`) and the analytics partition (`write_analytics_day`). Both are
needed — there is a separate fast path for each, and a day with raw but no analytics
still falls through.

## Excel

Only jobs 10, 11 and 12 carry `needs_excel`. Jobs 8 and 9 shell out to scripts that drive
Excel in their *fetch* phase behind their own guards. Everything numbered 13 and up is
deliberately offline and refuses a live fallback — that refusal is what stops a value job
silently repricing off the wire.

`_excel_preflight()` runs once per run and now **repairs rather than refuses**:

| state | remedy |
|---|---|
| no Excel | `launch_excel` + `wait_for_addin(press_login=True)` |
| over the 3,800 MB ceiling | `restart_excel` — rescues unsaved work first |
| signed out, under ceiling | press Login and wait |
| running but not bindable | restart; a Login press cannot fix an Excel outside the ROT |

A failed Login press escalates to a full kill and re-auth. Two remedies inside **one
latched repair** — `_EXCEL_REPAIR_ATTEMPTED` exists so a leaking add-in cannot turn this
into an all-night restart loop. **`force=True` is never passed**; `restart_excel` rescues
dirty workbooks and aborts if a rescue fails, because `EXCEL.EXE` is the user's
application.

The wait is a **wall clock** (`ARBS_WARM_EXCEL_SIGNIN_TIMEOUT`, 900 s), not a retry count.
`com_retry` has no deadline of its own, and a run once sat two hours at 0.00 s of CPU.

Measured cold start: **0 Excel processes to signed-in and serving in 3.3 minutes**, one
Login press. `ARBS_WARM_EXCEL_AUTOSTART=0` restores refuse-and-wait.

Memory is *not* liveness. The three memory branches read a number from `Get-Process`;
`_repair_addin_if_silent` is what asks whether the add-in actually answers.

## Testing

- **Run one job without the nightly**: import the module by path and call it directly —
  `spec = importlib.util.spec_from_file_location(...)`, then `mod.warm_x(d, d)`.
- **The job functions do their imports inside the function body.** Every name is
  re-resolved from its own module per call, so `monkeypatch.setattr(warmer, "X", ...)`
  is **never consulted**. Patch the source module. This made two correct tests fail.
- `tests/conftest.py` carries two rails. `ARBS_WARM_EXCEL_AUTOSTART=0` for the whole
  suite, and `_no_live_excel`: `connect` **raises** (a silent fake client would let a test
  fabricate market data), while `press_addin_login` / `dismiss_excel_dialogs` **no-op**
  (side effects on a window; a raise breaks the retry-loop tests). `launch_excel` and
  `quit_excel` are deliberately unfenced — they are under test with `excel_pids` stubbed.
- Mark anything that genuinely needs a real session `@pytest.mark.live_excel`.
- Relevant suites: `test_warm_jobs`, `test_warm_skip_semantics`, `test_warm_run_honesty`,
  `test_warm_excel_autostart`, `test_daily_cache_warmer_citivelo`.
- `tests/_mutate_warm_excel_autostart.py` re-introduces each defect and checks its test
  goes red. **Run it after changing guard logic.** Two of its mutations escaped once and
  both escapes were faults in the harness, not the source.

## Environment traps, all observed

- **`conda run` in parallel collides on a temp file and returns EMPTY output with exit 0**
  — a fake pass. Call the interpreter directly:
  `C:/Users/chris/anaconda3/envs/stir/python.exe`.
- **Heredocs collapse backslashes.** `r"(?<!\\)\|"` arrives corrupted. Use the Write tool
  for anything containing `\` or backticks.
- **A read/write cycle in a helper script translates line endings.** Reading text-mode and
  writing back "unchanged" rewrites every line. Read with `newline=""`, normalise to `\n`
  for matching, restore on write — or you get a diff with no content change.
- **The fast gate mutates the tracked FRB reference cache** — deletes a tracked
  `fiscaldata/<date>.parquet` and creates a new dated dir. Restore by *exact path*; never
  `git checkout -- <the cache dir>`, which reverts source too.
- **The computed TS store is repo-relative** (`<checkout>/data/ts`), and under full-suite
  import ordering a worktree run can still resolve to the primary checkout. That is a
  production-write hazard from somewhere that looks isolated.
- **`ARBS_SUPABASE_ENABLED=0` always.** Supabase L2 points at production with superuser
  credentials, and `l2_policy` reads the env at call time with a closed vocabulary — a
  typo raises rather than defaulting to enabled.

## Calendars

`pd.bdate_range` counts market holidays. Filter on
`ql.UnitedStates(ql.UnitedStates.GovernmentBond)` like the other jobs — and note **Good
Friday still needs excluding separately**, because that calendar treats it as a business
day while the bond market closes and vendors serve nothing. Evidence from two independent
sources: GS returns no curve, and all twelve scraped iShares ETFs published nothing on
2026-04-03 and 2023-04-07.

A "5% failure rate" that is really a calendar is worse than useless — it is where a
genuine gap hides.

## Reporting rules for this file

- Exit 0 is not evidence rows were written. Check the shape.
- A refusal is not absence. A 403, an `ExcelNotRunningError`, an empty store read — none
  of them mean "no data exists for this date", and recording them as such is how this
  repo once wrote 2,515 WAF refusals into a holdings store as fact.
- A hard hang never reaches a pytest summary line, so a killed run names nothing. Use
  `python -u -m pytest ... -v`: the nodeid is written as the test *starts*, so the last
  unterminated line is the culprit.
- When you claim a job works, say which run and which numbers. `--list` passing is not a
  job working.

## Full map

`docs/eod_warm_overview.html` — all 18 jobs in execution order, each with its provider,
its store, its dependencies and a measured duration.
