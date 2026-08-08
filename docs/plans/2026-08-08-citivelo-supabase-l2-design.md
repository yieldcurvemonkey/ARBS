# Supabase L2 for the Citi Velocity stores — design and measurements

2026-08-08. Branch `feat/citivelo-supabase-l2`, based on `origin/main` 33fe6981.

Two jobs that turned out to be one: put the Citi Velocity history into the
Supabase L2 tier, and make the swaption cube store readable by the code that
needs it. Both were blocked by the same thing — a default that points at
production — so the safety story is the first commit and everything else builds
on it.

---

## 1. What was actually true at the start

The brief's framing was "the curve L2 tier exists and works, it is simply not
being used for Citi." Half right, and the correction matters:

| asset | local | in L2 already |
|---|---|---|
| `USD-SOFR-1D-CITIVELO` | 930 days / 398 MB | **all of it** — 930 days, 0 differing by sha |
| `<curve>-CITIVELOEXCEL` | 5 assets | none |
| `<curve>-CITIVELOEXCELMIN` | 5 assets | none |
| `<curve>-CITIVELOSTREAM` | 3 assets | none |
| `<CCY>-SWAPTIONVOL-CITIVELOEXCEL` | 2,699 days | no table at all |

So the workbook asset had been synced at some point and was byte-for-byte
current. `citivelo_l2_sync.py plan` reports it as 0 to push rather than
re-uploading 398 MB, and that is checked by content, not by date presence.

**Capacity.** The instance is PostgreSQL 17.4, 210.7 GB, top table `sdr_data` at
104 GB. Adding ~750 MB is 0.35%. Not a constraint; recorded rather than assumed.
Server defaults measured at the same time: `statement_timeout` **120 s**,
`lock_timeout` **0**, `idle_in_transaction_session_timeout` **0**,
`default_toast_compression` `pglz`, `max_connections` 240.

**The stores are a moving target.** `USD-SOFR-1D-CITIVELOEXCEL` went 680 → 4,256
→ 5,506 days during this session, and the cube store 1,746 → 2,699, because
`citivelo_excel_warm.py` and `daily_cache_warmer.py` were extending them
concurrently. Three independent counts (raw directory walk, `sync.local_dates`,
`store.available_dates`) agreed at each instant, which is how that was
distinguished from a counting bug. Every number below is as-of a stated moment.

---

## 2. The safety story

`Caching/supabase_engine.py` resolves a fully-credentialed **production** URL
from module constants when no env var is set, `SUPABASE_ENABLED` defaults to
`True`, and `ensure_schema()` is called from *read* paths — so reading a cache
can run `ALTER TABLE` against a live table. The existing mitigations do not close
it: the flag is evaluated at import, its opt-out vocabulary is a closed falsy set
(so `disabled`, `none` and every typo mean **enabled**), and the
`SUPABASE_ENABLED and bool(_DATABASE_URL)` line can never fire.

Four things, in order of how much they carry:

**A tripwire on `psycopg2.connect`** (`Caching/prod_db_guard.py`), installed by a
session-autouse fixture in `tests/conftest.py`. Not `create_engine`: an engine is
lazy and opens no socket, several scripts call the DBAPI directly, and a module
attribute on `psycopg2` survives the `importlib.reload` the suite performs. It
blocks one host and only when no connection env var names it, so `PG_TEST_URL` /
`DATABASE_URL` still reach a real database. The escape hatch uses a closed
**truthy** set — the opposite convention to `_env_enabled` — so a typo in an
opt-in fails safe where a typo in an opt-out points at production.

**Opt-in, strictly parsed, at call time** (`Caching/l2_policy.py`). Three states
(`off` / `read` / `read_write`), default `off`, and an unrecognised token
**raises** naming the vocabulary. Read when asked rather than at import, which is
what makes a `--push-l2` flag work at all.

**Transaction labelling** (`Caching/db_session.py`). The obvious fix —
`connect_args={"application_name": ...}` — **does not work here**, measured:

```
with application_name: SHOW='Supavisor'  pg_stat_activity='Supavisor'
baseline:              SHOW='Supavisor'  pg_stat_activity='Supavisor'
```

Port 6543 is Supavisor in transaction mode; it owns the server connection and
stamps its own name, and both connections were the same backend pid. `SET LOCAL`
does work, and is the right granularity anyway:

```
inside txn : app_name = arbs_l2_probe   pg_stat_activity = arbs_l2_probe
inside txn : stmt_to  = 0     lock_to = 5s
next txn   : app_name = Supavisor       stmt_to = 2min
```

Values go through `set_config(..., is_local => true)`: `SET` takes no bind
parameters and concatenating a label into one makes it an injection point.

**A DDL applier that does not deadlock** (`Caching/supabase_schema.py`).
`str.split(";")` replaced with the tape's line-based splitter and grouper
(ported, not imported — `Caching` is the lower layer), and the
one-transaction-no-lock_timeout bundle replaced with per-group short transactions
carrying `SET LOCAL lock_timeout` and retry-with-backoff. A currency check
derived from the SQL itself turns the usual case into three read-only queries
instead of twenty DDL round trips, which is what keeps a read path off an
`ACCESS EXCLUSIVE` lock.

### Verified capable of failing

Not asserted. With `is_blocked_host()` stubbed to `return False`, **14 of 24**
guard tests fail, including the end-to-end one that drives `get_engine().connect()`
with an empty environment and expects a refusal.

---

## 3. The blob tier

`Caching/supabase_blob_blocks.py` is one implementation of the whole-partition
blob pattern, used by the new swaption sync and by a new adapter that points it
at the existing curve table. The three existing copies were left alone — they are
load-bearing for the live curve path — but they **disagree**, and each
disagreement is a defect worth naming:

- `supabase_curve_sync.pull_day` writes with `dest.write_bytes()`, not
  atomically. `supabase_ustf_sync` uses `_atomic_write_bytes`.
- **Neither verifies the payload against the stored sha on the way in.** Both
  name the file `f"{row.sha256}.parquet"` and trust it, so a truncated payload
  lands under a filename that lies.
- `prefetch_range` SELECTs `payload` for the whole range and then discards the
  days it already had — 400 MB over the pooler to learn nothing.
- `_local_parquet_bytes` takes `pq_files[0]` (curve) or `[-1]` (ustf) when a
  partition holds several files, while `CurveStore.read_raw_day` **concats**
  them. The blob then publishes fewer rows than the local store serves, silently.
  `USD-OIS-Q12xM12STIRT-SERFFX-MIX23` has 2,613 files across 1,382 days on this
  machine, so the case is live.

The new code fixes all four, refuses a multi-file partition outright, and makes
restatement symmetric so `SwaptionCubeStore`'s one-partition-one-cube property
survives the round trip: push raises on a differing remote sha, pull raises on a
differing local partition. Reads run no DDL — they do an `information_schema`
existence check and answer "no data".

### Verified capable of failing, twice

*In tests*: five mutations, each reverted after — no sha verification (4
failures), L2 gate always open (3), prefetch downloads everything (2), multi-file
picks `file[0]` (1), push overwrites silently (1). A sixth mutation was written,
survived, and was **discarded as a bad mutation rather than counted**: it removed
one of two branches that both skip a locally-identical day, so behaviour was
unchanged and the test was right to pass.

*Against the real production table*: two synthetic days were pushed under a
throwaway asset, then each thing the verifier claims to catch was corrupted in
turn — truncated payload, scrambled sha column, a **self-consistent but wrong**
payload, a lying `row_count`, an absent remote day — and it went red on every
one, and `pull_day` refused the corrupted blob without landing anything. Scratch
rows deleted; zero confirmed remaining.

---

## 4. The backfill

`scripts/citivelo_l2_sync.py` — `plan` / `push` / `verify` / `status` over all
five families in both stores. One process, one engine, a bounded thread pool, so
connections are `--workers + 2` however many days are pushed. Under the process
pools these warms use, each worker would build its own engine at pool 5 +
overflow 4 = **9 connections per process**, which is how a dev backfill exhausts
a pooler the dashboard is also using.

Resume is by **content**: local partitions are content-addressed, so the filename
*is* the sha and a whole-asset diff costs a directory listing plus one indexed
query with no payloads. `backfill_local_curve_store_to_supabase` resumes on date
presence, so a day whose parquet was rebuilt after it was pushed is never
noticed; here it shows up as `differing` and is not overwritten without
`--rewrite`.

`push` prints the target and the byte count and refuses without `--yes`.

### Measured runs

| family | days | bytes | wall | rate | failures |
|---|---:|---:|---:|---:|---:|
| cube | 2,699 | 41.9 MB | 0.8 min | 57.6 d/s | 0 |
| eod + stream | 13,480 | 66.4 MB | 27.1 min | 8.3 d/s | 0 |
| minute | 2,845 | 637.1 MB | 8.0 min | 5.9 d/s | 0 |

Plus 16,325 tagged `arbs_curve_snapshots_v1` rows, written with the same
`curve_tag_config.get_tags` gate the existing `_push_tagged_snapshots` uses, so
the Citi assets are tagged the way `USD-SOFR-1D-CITIVELO`'s existing rows are
rather than as a second, untagged convention. `get_tags` is timezone-agnostic
(OPEN at `session_minute == 0`, EOD on the last row), so it is correct for the
non-US currencies whose `session_minute` is minute-of-day in their **own** zone.

The eod family is slower per day than the minute family despite 100× smaller
blobs, because the snapshot-row phase is serial and one transaction per day. The
blob push itself was ~3 minutes of the 27.

**Verification: all 2,699 cube days pulled back and compared — 0 problems**,
where a problem is any of: the payload not hashing to its sha column, differing
from the local file byte for byte, failing to parse as parquet, or disagreeing
with the stored `row_count`.

---

## 5. The swaption cube read path

`Caching/swaption_cube_store.py` was referenced by exactly one thing — the warm
script. `IRSwaptionMDP` never read it, so every dated swaption request went
`_cube_for_date` → `fetch_cube` → `CitiVelocityExcelClient.connect()`, once per
date. Reported before: a 4-date range took **134 s and returned an empty frame**,
failing with "A swaption CUBE needs strike offsets" while the stored partitions
held the full thirteen-offset smile.

After, with `connect` replaced by a function that raises: **4.4 s for the same 4
dates, 0 COM attempts**, every context reporting `origin=swaption_cube_store`,
`smile=full`, `n_offsets=13`.

Note it bypassed *two* caches: `fetch_cube` accepts a `cache=CitiVeloTagCache`
("only the missing spans hit Excel") and `provider.py` never passed one.

**The pre-2020 history is data, not a cache miss.** Measured over all 2,699
stored USD days: **1,067 ATM-only** (2015-10-08 .. 2020-01-23, one offset) and
**1,632 full-smile** (2020-01-24 onward). A QuantLib cube on such a day now
raises a message that says so and says refetching cannot help, instead of the
generic advice to refetch with offsets — which is the behaviour being removed.
The rateslib backend is not blocked on those days; that would discard 1,067
usable ATM surfaces.

### Read cost, profiled rather than assumed

The note on record was "batch reconstruction is 0.1 ms/curve against 1.3 ms one
at a time." Measured over 60 real days: `reconstruct_cubes_batch` 61.9 ms/day, a
loop of `reconstruct_cube` 63.9 ms/day. There is no batching — it *is* a loop —
so no speed claim is made for it.

The real profile: `read_day` 6 ms, `validate()` 0.6 ms, `sort_tenors` 0.2 ms, and
**78% in fourteen separate `pivot_table` calls**, one of whose results was
assigned and discarded (`_ = pivot`). `cube_from_frame` now does one grouped
reshape sliced per offset: **33.3 → 8.25 ms/day, 4.0×**, and bit-identical over
all 2,699 days (`assert_frame_equal(check_exact=True)` on every ATM and skew
frame, across both shapes of history).

### Verified capable of failing

Eight mutations, each caught by the test that guards it: store branch removed
(4 failures), live mode ignored (2), `use_cube_store` ignored (1), ATM-only guard
removed (1), provenance dropped (1), timestamp mode always `eod` (6), memo
removed (1), smile always `full` (2).

The end-to-end check was mutation-tested too, and **the first run exposed two of
its own assertions passing vacuously** — `all()` over an empty dict is True, and
under the store-branch mutation the result *is* empty. Both now assert the
expected count.

---

## 6. Two bugs the value warm found

**`IRSwaptionsTB.get_timeseries(timestamps=[...])` returned an empty frame** for
every provider that keys `bulk_get_data` by date — which `IRSwaptionMDP` does.
`build_reference_points` returns `datetime` for that argument and `date` for the
ordinary path, and `datetime(2026,7,27) != date(2026,7,27)`, so `built_map.get(d)`
missed every row. Silent: one "No swaption context" warning per date. The
pre-existing `if ctx is None and d == date.today()` line was a partial attempt at
the same normalisation that could only ever fix today.

**The first valuation in a process took 235.8 s; the next took 1.54 s.** Profiled:
236.8 s of it is `assert_vol_spread_ordering` inside `build_ql_swaption_cube` —
1,990 QuantLib `SwaptionVolatilityStructure_volatility` calls at 110 ms each,
re-pricing every node of the 1,989-node cube. It runs under `-RL` too, because
`CitiVeloSwaptionCube.volatility()` is deliberately QuantLib-served (it turns an
option *time* into an option *date* itself, and an approximate expiry date moves
the strike offset), so resolving `ATMF+25` builds a QuantLib cube whatever the
pricing engine is.

Measured on one USD date, six values: `verify=True` **242.4 s**, `verify=False`
**7.3 s** — 33× — and every value **identical to 0.0e+00**. The check changes no
number; it only detects. The knob existed on `build_citivelo_swaption_cube` and
was unreachable from the provider; it is now a passthrough (default unchanged,
ON), and the warm runs it as a **preflight on the first date** rather than
per-chunk — because the cost is per *date*, so "verify one chunk in ten" still
pays it for every date in that chunk.

What the preflight gives up is stated in the script: it catches a bad
*construction*, which is systematic; it can miss a bad *day*.

---

## 7. What was left undone, and why

**`curve_source='CITIVELO_EXCEL'` still reaches Excel, and it is not the vol
path.** The curve store fast path serves the curve *nodes* from the warm and then
calls `_load_citivelo_excel_curve_store_point` → `fixings.py:522 fixings_for` →
`_merged_sources` → `citi_fixings` → `quotes.py:169 fetch` → `connect()`. Five
COM attempts per request, for the published overnight fixings.
`IRSwaptionMDP` already carries a hint string about it. Out of scope here; the
swaption tests isolate the vol path with `ERIS_EOD_LIVE-RL_BASIC`.

**A full-history swaption value warm was not run.** At ~1.5 s per valuation
(after the preflight), the default 90-column grid over 1,632 full-smile days is
~60 hours. The script, the plumbing and the measured rate are delivered; choosing
the grid is a judgement about what is worth caching, not a mechanical step.

**The three existing sync modules keep their four defects.** They are the live
curve read path; fixing them is a separate change with a separate blast radius.
They are documented in `Caching/supabase_blob_blocks.py` rather than silently
left.

**No `arbs_curve_analytics_blocks_v1` push for Citi**, because there are no Citi
analytics partitions on disk — the analytics tree holds only ERIS/STIRT assets.

**`ARBS_SUPABASE_ENABLED` still parses leniently.** `l2_policy` fixes the
vocabulary for new code; changing `_env_enabled` is an import-time behaviour
change for every existing consumer and belongs in its own commit with its own
argument.
