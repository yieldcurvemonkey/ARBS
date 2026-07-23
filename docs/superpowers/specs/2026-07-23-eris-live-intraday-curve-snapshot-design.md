# ERIS Live Intraday Curve Snapshot Service — Design

**Date**: 2026-07-23
**Owner**: @yieldcurvemonkey
**Status**: Draft for review
**Companion**: `2026-07-23-eris-live-intraday-curve-snapshot-implementation.md` (to be written by the writing-plans step)
**Related**: CitiVelo intraday curve pipeline (PRs #358→#359→#360, `scripts/citivelo_curve_service.py`) — the closest existing precedent for intraday-granular curve handles persisted to Supabase; this design clones its shape with a different read/write target.

---

## 1. Summary

Build a robust Windows-hosted service that **polls the live ERIS SOFR discount-factor curve once a minute during US trading hours and persists each fresh curve handle as one indexed row in Supabase**, plus a read API to serve any stored minute back as a reconstructed rateslib curve.

- **Source**: `IRSwapsMDP(source="ERIS_EOD_LIVE-RL_BASIC-NOJUMPS").get_pricer({"curve_name":"USD-SOFR-1D","timestamp":"live"})` returns an `RLIRSwapCurve` wrapping a single 18,263-node `rl.Curve` (log-linear, **no solver**) built directly from the vendor's intraday discount-factor CSV.
- **Store**: reuse the existing `arbs_curve_snapshots_v1` table (`PRIMARY KEY (curve_name, timestamp_utc)` — the only cache table keyed on a timestamp) under a **dedicated asset** `USD-SOFR-1D-ERISLIVE`. One untagged row per fresh vendor snapshot. **No migration.**
- **Read**: a new `IRSwapsMDP(source="eris_live_intraday")` branch serves the curve as-of any minute via an **indexed as-of SQL** against `snapshots_v1`, reconstructs it with `CurveStore.reconstruct_curve`, and wraps it as an `RLIRSwapCurve` — the same object shape CITIVELO returns.
- **Runtime**: a long-lived, per-session daemon (one import/day, drift-free 60 s loop), registered with Windows Task Scheduler and hardened for unattended operation (freshness dedup, session/holiday gating, per-cycle failure isolation, single-instance lock, rotating logs).

**Decisions already made (via brainstorming):**
1. **Curve handle only** — store the rateslib curve (node dates + discount factors); no priced tenors / spread-synthesis in scope.
2. **Full float64 ~18,263-node grid** — bit-exact round-trip of the ingested curve; ~33 GB/yr relational. Fidelity over storage.
3. **Long-lived daemon** — one warm process, drift-free 60 s loop (not a per-minute one-shot; not a `<Repetition>` trigger).
4. **Per-minute indexed rows** → `arbs_curve_snapshots_v1` + a new read API. (Not the whole-day blob table — see §4.3.)

## 2. Background — verified facts about the existing system

All line numbers below were verified against source during exploration (two multi-agent recon + verification passes).

### 2.1 The live ERIS curve

- **Source string** `ERIS_EOD_LIVE-RL_BASIC-NOJUMPS` (no enum; literal `str.upper()` membership tests) decodes to: vendor `ERIS_EOD_LIVE` (anonymous HTTPS from `files.erisfutures.com`) + backend `RL_BASIC` (rateslib, no solver, discount factors taken verbatim) + `NOJUMPS` (`no_jumps_just_interp=True` → **every** row of the CSV becomes a `log_linear` node — 18,263 nodes, no FOMC/IMM selection).
- **Fetch** (`CME_NY_EOD_LIVE/rl_basic/ErisFuturesFetcher.py`): anonymous HTTPS GET of `.../ftp/Eris_Intraday_DiscountFactors_SOFR.csv` (chosen when `date is None`). **No credentials, no env vars.** Fresh `httpx.AsyncClient(verify=False, http2=True)` per call, 3 retries, backoff 1/2/4 s.
- **Nothing memoizes the live file.** On `timestamp="live"`, the raw-file diskcache read is short-circuited (`_load_cached_raw` returns on `date is None`), the `_RLCurveCache` is bypassed, and CurveStore promotion is gated off. Every poll is a real network GET. **No cache-busting is needed; do NOT pass `force_refresh=True`** (it calls `cache.clear()` on the shared FanoutCache).
- **Freshness fields on the returned `RLIRSwapCurve`** (`Query/IRSwaps/backends/rateslib/RLIRSwapCurve.py`):
  - `meta()` → the `meta_data` dict (L60-61). For the ERIS live path, `meta()["timestamp"]` is the **vendor valuation timestamp, tz-aware ET**, parsed from CSV `Time[0]` and overwritten into meta at `IRSwapsMDP.py:1638`. **This is the correct dedup key** — it advances only when the vendor publishes a new intraday snapshot.
  - `reference_date()` → the curve's **first node date** = CSV `Date[0]` (L39-40).
  - `id()` → `"USD-SOFR-1D"`.
- **Build cost** (measured warm): HTTP GET ~0.14-0.16 s (≈80 % of wall) + `read_csv` ~0.008 s + NOJUMPS `_df_to_curve` (18,263 nodes) ~0.02 s + fixings ~0.006 s ≈ **~0.17-0.20 s end-to-end, no solver**. At 60 s cadence, ~99.7 % headroom.
- **Republish cadence** (measured): ~41-53 s (mean ~46 s); embedded `Time` lags `Last-Modified` by ~19-24 s. A 60 s poll normally sees a new file; a consumed curve is ≤ ~73 s stale worst case. **A 200 OK does not imply fresh** (the sibling BSBY file serves 200 with a 2.5-yr-stale stamp) — freshness must be asserted on the embedded stamp.

### 2.2 Request/validation quirks that shape the daemon

- **`get_data` pops its keys** (`IRSwapsMDP.py:1467-1474`): `request.pop("curve_name")`, `request.pop("timestamp")` mutate the caller's dict in place. `get_pricer` passes the same object with no copy. **The loop must build a fresh `{"curve_name","timestamp"}` dict every poll**, else the 2nd poll raises `KeyError`.
- **Non-business-day guard** (`IRSwapsMDP.py:355-379`): because `"EOD" in source`, `_requires_strict_eod_calendar_validation()` is True, so `_validate_eod_curve_request_timestamp` runs; `_request_calendar_date("live") = date.today()`; on a non-business day of `ql.UnitedStates(GovernmentBond)` it raises `ValueError("live is not a business day in the …")` **before any fetch**.
- **Total-fetch-failure** surfaces as `ValueError: not enough values to unpack (expected 2, got 0)` at `IRSwapsMDP.py:1620` (the live branch unpacks `{}` when the fetch yields nothing).
- **Both failure modes are `ValueError`.** The loop catches `ValueError` (WARNING) and broad `Exception` (network/fixings/parse; skip-and-continue). It never dies on a bad poll.
- **`error_verbose`**: `BaseFetcher._setup_logger` disables the fetcher logger by default (`self._logger.disabled = True`). Pass `error_verbose=True` through the MDP config so fetch-layer errors are visible.
- **Object reuse**: `IRSwapsMDP(source=...)` has no per-request mutable state — **build it once, reuse across polls**. (The internal `ErisFuturesFetcher(**self.config)` is nonetheless reconstructed on every live poll and never `close()`d; see §7 R1.)

### 2.3 Curve storage (`Caching/curve_store.py`, `Caching/supabase_curve_sync.py`)

- **`CurveSnapshot`** dataclass (`curve_store.py:135-149`): `timestamp_utc` (tz-aware UTC), `timestamp_local` (tz-aware US/Chicago), `trading_date`, `session_minute` (int), `curve_name`, `cfg_hash`, `reference_key`, `interpolation`, `source_variant`, `node_dates: list[date]` (sorted), `discount_factors: list[float]` (parallel).
- **`arbs_curve_snapshots_v1` DDL** (`sql/core_cache_schema.sql:4-20`):
  ```sql
  CREATE TABLE IF NOT EXISTS arbs_curve_snapshots_v1 (
      curve_name VARCHAR NOT NULL,
      timestamp_utc TIMESTAMPTZ NOT NULL,
      trading_date DATE NOT NULL,
      session_minute SMALLINT NOT NULL,
      tags TEXT[] NOT NULL DEFAULT '{}',
      cfg_hash VARCHAR NOT NULL,
      reference_key VARCHAR NOT NULL,
      interpolation VARCHAR NOT NULL,
      source_variant VARCHAR NOT NULL DEFAULT '',
      node_dates DATE[] NOT NULL,
      discount_factors FLOAT8[] NOT NULL,
      created_at TIMESTAMPTZ DEFAULT NOW(),
      PRIMARY KEY (curve_name, timestamp_utc)
  );
  CREATE INDEX idx_snapshots_tags ON arbs_curve_snapshots_v1 USING GIN (tags);
  CREATE INDEX idx_snapshots_date ON arbs_curve_snapshots_v1 (curve_name, trading_date);
  ```
  The `PRIMARY KEY (curve_name, timestamp_utc)` btree backs the as-of query directly. Today the table holds only ~2 rows/day/curve (tagged OPEN/EOD).
- **Serialization**: a curve is reduced to `(sorted node_dates, discount_factors, interpolation, reference_key)`. On read, `reconstruct_curve` rebuilds convention/calendar/modifier from `RATESLIB_CURVE_DEFINITIONS[reference_key]` — **not** from storage. `reference_key` is the join key; `RATESLIB_CURVE_DEFINITIONS["USD-SOFR-1D"]` exists (`rl_curve_definitions_map.py:7`, act360/nyc/mf).
- **`reconstruct_curve(row: dict, *, cfg=None)`** (`curve_store.py:815`) reads `row["node_dates"]`, `row["discount_factors"]`, `row.get("reference_key","")`, `row.get("interpolation","log_linear")`. `cfg=None` for us (mixed-interpolation is BARCHART-only). `_to_date` (`curve_store.py:1355-1367`) accepts `date`, `datetime`, `pd.Timestamp`, `np.datetime64`, **and ISO strings** — so it handles whatever psycopg2 returns for a `DATE[]` column.
- **Write hazards (why we do NOT reuse the obvious paths):**
  - `CurveStore.write_day(...)` **always** enqueues an L2 blob push (`curve_store.py:514-522`); there is no suppress kwarg, and `ARBS_CURVE_STORE_BG_PUSH_WORKERS=0` floors to 1 worker (does not disable). `push_day` re-INSERTs the **whole-day BYTEA blob** every call → at 18k nodes this is an ~88 MB re-push every minute by end of day. **Do not call `write_day` in the loop.**
  - `arbs_curve_snapshots_v1`'s only writer is the private `_push_tagged_snapshots` (`supabase_curve_sync.py:203-251`), which **skips untagged rows** (`if not tags: continue`, gated by `get_tags` → OPEN/EOD/event-±2min only). There is no public arbitrary-row upsert. We add one (§4.2).

### 2.4 Supabase connectivity & the env-flag conflict

- All DB access is **direct Postgres** via SQLAlchemy `Engine` + `text()` (no supabase-py/PostgREST). Engine resolves `ARBS_DATABASE_URL` → `SUPABASE_DATABASE_URL` → `SWAPPULSE_DB_*` parts, defaulting to baked-in prod creds (transaction pooler, port 6543).
- **`SUPABASE_ENABLED` is evaluated once at import** (`supabase_engine.py:67-69`); `get_engine()` returns `None` when disabled. **Setting `ARBS_SUPABASE_ENABLED=0` kills the engine globally** — it would block our own writes too, so we must keep it **`1`**.
- The fetcher's per-poll dead KV write (~820 KB into `arbs_kv_cache_v1`, zero benefit) goes through `LayeredCacheMixin` write-through, gated independently by the class toggle `LayeredCacheMixin.L2_WRITE` (`layered_cache_mixin.py:437-458`). **Setting `LayeredCacheMixin.L2_WRITE = False` before constructing the fetcher kills the dead KV write while leaving the engine alive** — the clean resolution of the conflict.

### 2.5 Cron / daemon precedents

- **Two** registered Windows Scheduled Tasks (`\ARBS-CacheWarmer-Daily` Mon-Fri 18:15 ET, `\ARBS-CacheWarmer-WeekendBackfill` Sat 10:00 ET), both invoking the conda-env python **directly** (no wrapper, no log redirect, `MultipleInstancesPolicy=IgnoreNew` the only mutex). Not checked into git. **No `<Repetition>` trigger anywhere** → no minute-cadence precedent.
- **Canonical `.ps1` conda pattern** (`notebooks/logs/*_runner.ps1`): `& 'C:\Users\chris\anaconda3\shell\condabin\conda-hook.ps1'; conda activate stir; $env:PYTHONUNBUFFERED='1'; & python … *> $log; exit $LASTEXITCODE`.
- **Best loop template**: `SDRUtils/_swappulse_scripts/ingest_usdswaps.py` — `while True` with **drift-free** `sleep = max(0, interval − (monotonic()−cycle_start))`, an `_is_in_active_window(weekday+HH:MM)` gate (weekday-only; **no holiday check** — we add one), and per-cycle `try/except Exception`. `citivelo_curve_service.py` is the structural template (env-toggle at module top + hard-abort guard).
- **Single-instance lock**: `MDP/cache_populator.py` `_try_claim` uses `os.open(path, O_CREAT|O_EXCL|O_WRONLY)` returning `None` on `FileExistsError`; release closes + unlinks. **No TTL / stale-lock reclamation** — a hard crash orphans the lock. We add a stale-PID check (`os.kill(pid,0)`).
- **No `python-dotenv`** anywhere — env comes from the process environment (set by the `.ps1`/task) or baked-in defaults.

### 2.6 CITIVELO precedent (the shape to clone)

`scripts/citivelo_curve_service.py` reuses CurveStore/SupabaseCurveSync unchanged. Dedicated asset `USD-SOFR-1D-CITIVELO`, `reference_key="USD-SOFR-1D"`, `source_variant="CITIVELO"`, ET-calendar-date partition, ET-minute `session_minute`, `CurveSnapshot(...)` constructed directly. Read via `_load_citivelo_curve_store_point` (`IRSwapsMDP.py:136-217`): resolve ET date → **whole-day** `read_raw_day` → pandas as-of → `reconstruct_curves_batch(row, max_workers=1)` → wrap `RLIRSwapCurve`. **Key divergence for us**: CITIVELO reads the whole-day *blob* table; we read `snapshots_v1` by *indexed as-of SQL* (§4.3), because we write per-minute rows, not blobs.

## 3. Goals / Non-goals

**Goals**
- Persist a fresh ERIS live SOFR curve handle to Supabase at ~1-minute granularity during the US session, unattended and robust.
- Bit-exact round-trip: a stored row reconstructs the identical rateslib curve (same nodes, same DFs).
- Serve any stored minute back through `IRSwapsMDP` with `method ∈ {asof, nearest, exact, live}`.
- Idempotent and self-healing: safe to restart mid-session; no duplicate/garbage rows; failures logged and skipped, never crashing the scheduler or the loop.

**Non-goals**
- Pricing tenors (IMM spreads, outrights) or spread-synthesis compatibility — explicitly out (decided).
- Backfilling historical intraday ERIS curves — this is a forward-only live poller. (The vendor publishes only the *current* intraday file; there is no historical intraday feed to backfill.)
- The whole-day blob table (`arbs_curve_intraday_blocks_v1`) and local Parquet L1 — not used (§4.3).
- Dashboard/frontend wiring — out of scope for v1 (the read API is the integration seam).
- Polling multiple curves — v1 is `USD-SOFR-1D` only; the service is parameterized so more can be added later.

## 4. Design

### 4.1 Component overview & data flow

```
Windows Task Scheduler  ── Daily 06:55 ET  ┐
                         ── AtStartup       ┴─> eris_live_curve_service.ps1 (conda activate stir)
                                                   └─> python scripts/eris_live_curve_service.py run
   ┌───────────────────────────── per-session daemon (one import, warm loop) ──────────────────────────┐
   │  acquire single-instance lock (stale-PID aware)                                                    │
   │  LayeredCacheMixin.L2_WRITE = False;  ARBS_SUPABASE_ENABLED = "1"   (before Caching import)         │
   │  mdp = IRSwapsMDP("ERIS_EOD_LIVE-RL_BASIC-NOJUMPS", error_verbose=True)   # built ONCE              │
   │  last_ts = high-water-mark(snapshots_v1, asset, today)   # resume dedup after restart               │
   │  while now_et < 17:15:                                                                              │
   │     t0 = monotonic()                                                                                │
   │     if in_session(now_et) and is_business_day(now_et):                                              │
   │        try:                                                                                         │
   │           curve = mdp.get_pricer({"curve_name":"USD-SOFR-1D","timestamp":"live"})  # FRESH dict     │
   │           ts = curve.meta()["timestamp"]           # vendor stamp, tz-aware ET                      │
   │           assert freshness(ts, curve.reference_date())                                              │
   │           if ts != last_ts:                                                                         │
   │               snap = build_snapshot(curve, ts)                                                      │
   │               sync.upsert_snapshot_row(snap, curve_name="USD-SOFR-1D-ERISLIVE")   # 1 indexed row   │
   │               last_ts = ts                                                                          │
   │        except ValueError as e:    log.warning(...)      # non-business-day OR empty-fetch           │
   │        except Exception:          log.exception(...)    # network/fixings/parse — isolate cycle     │
   │     sleep(max(0, 60 - (monotonic()-t0)))               # drift-free                                 │
   │  release lock                                                                                       │
   └────────────────────────────────────────────────────────────────────────────────────────────────────┘
                                     │  arbs_curve_snapshots_v1  (PK curve_name, timestamp_utc)
                                     ▼
   Read:  IRSwapsMDP("eris_live_intraday").get_pricer({"curve_name":"USD-SOFR-1D",
                                                       "timestamp":<datetime|"live">, "method":"asof"})
           └─> _load_eris_live_intraday_point
                 └─> sync.pull_snapshot_asof(asset, ts_utc, method)   # indexed SQL, 1 row
                 └─> CurveStore.reconstruct_curve(row, cfg=None) → rl.Curve
                 └─> RLIRSwapCurve(rl_curve_id="USD-SOFR-1D", handle, fixings, meta)
```

### 4.2 Write path

**Process-start toggles** (both before any `Caching` import, following `citivelo_curve_service.py:37-40`):
- `os.environ.setdefault("ARBS_SUPABASE_ENABLED", "1")` — engine must be alive for our writes.
- `LayeredCacheMixin.L2_WRITE = False` — kills the fetcher's dead ~820 KB/poll KV write; leaves the engine up.

**Snapshot construction** (direct `CurveSnapshot(...)`, mirroring CITIVELO `:245-257`), from the live curve handle:
- `handle = curve.handle()` (the `rl.Curve`); `node_dates = list(handle.nodes.nodes.keys())`, `discount_factors = list(handle.nodes.nodes.values())` (float64, verbatim).
- `timestamp_utc = curve.meta()["timestamp"].astimezone(UTC)`; `timestamp_local = → US/Chicago`.
- `trading_date = curve.meta()["timestamp"].astimezone(ET).date()` (ET calendar date).
- `session_minute = et_hour*60 + et_minute`.
- `curve_name = "USD-SOFR-1D-ERISLIVE"`, `reference_key = "USD-SOFR-1D"`, `source_variant = "ERIS_RL_BASIC_NOJUMPS"`, `cfg_hash = ""`, `interpolation = "log_linear"`.

**New public method `SupabaseCurveSync.upsert_snapshot_row(snap: CurveSnapshot, curve_name: str)`** — copies the verified INSERT from `_push_tagged_snapshots` verbatim, single row, `tags=[]`, no tag gate:
```python
with self._engine.begin() as conn:
    conn.execute(text(f"""
        INSERT INTO {CURVE_SNAPSHOTS_TABLE}
            (curve_name, timestamp_utc, trading_date, session_minute,
             tags, cfg_hash, reference_key, interpolation, source_variant,
             node_dates, discount_factors)
        VALUES (:curve_name, :timestamp_utc, :trading_date, :session_minute,
                :tags, :cfg_hash, :reference_key, :interpolation, :source_variant,
                :node_dates, :discount_factors)
        ON CONFLICT (curve_name, timestamp_utc) DO UPDATE SET
            tags = EXCLUDED.tags,
            node_dates = EXCLUDED.node_dates,
            discount_factors = EXCLUDED.discount_factors
    """), {"curve_name": curve_name, "timestamp_utc": snap.timestamp_utc,
           "trading_date": snap.trading_date, "session_minute": int(snap.session_minute),
           "tags": [], "cfg_hash": snap.cfg_hash, "reference_key": snap.reference_key,
           "interpolation": snap.interpolation, "source_variant": snap.source_variant,
           "node_dates": [_norm_date(d) for d in snap.node_dates],   # → datetime.date
           "discount_factors": [float(v) for v in snap.discount_factors]})
```
`CurveSnapshot.node_dates` are already `datetime.date`, so `_norm_date` is a trivial identity/`pd.Timestamp→date` normalizer (implementation picks the exact call; the existing tagged writer already binds `list[date]`/`list[float]` this way). psycopg2 adapts Python lists to `DATE[]`/`FLOAT8[]`; 18k elements are trivial (Postgres array cap ~2^28). Idempotent: a re-poll of the same vendor stamp is a harmless no-op update.

**No local Parquet, no blob table.** `snapshots_v1` is the single source of truth. Restart dedup uses a high-water-mark query (`SELECT max(timestamp_utc) WHERE curve_name=:asset AND trading_date=:today`), so no local state file is needed and `ON CONFLICT` makes any race harmless.

### 4.3 Why per-minute rows, not the whole-day blob

At 18,263 nodes, `arbs_curve_intraday_blocks_v1` (whole day as one BYTEA blob, re-pushed on every `write_day`) would re-upload an ~88 MB growing blob **every minute** by session end — pathological. Per-minute rows into `snapshots_v1` cost one ~150 KB indexed insert per fresh snapshot, append-only, and the PK btree gives true server-side as-of (`… WHERE curve_name=$a AND timestamp_utc <= $t ORDER BY timestamp_utc DESC LIMIT 1`) — no whole-day materialization on read. This is the one deliberate divergence from CITIVELO.

### 4.4 Read path — `IRSwapsMDP(source="eris_live_intraday")`

**Dispatch**: new `elif self.source.upper() in ["ERIS_LIVE_INTRADAY", "ERIS_LIVE-INTRADAY"]:` in `_get_curve`, slotted immediately before the terminal `else` at `IRSwapsMDP.py:2222`, calling `self._load_eris_live_intraday_point(...)`. The source name contains `INTRADAY` and not `EOD`, so `_requires_strict_eod_calendar_validation` returns **False** (`:359`) → no business-day validation on reads (as-of any minute works). It is **not** added to `_curve_store_source_family`.

**New pull helpers on `SupabaseCurveSync`** (net-new; `snapshots_v1` is write-only today):
- `pull_snapshot_asof(curve_name, ts_utc, method="asof") -> dict | None`:
  - `asof`: `WHERE curve_name=:cn AND timestamp_utc <= :ts ORDER BY timestamp_utc DESC LIMIT 1`
  - `exact`: `WHERE curve_name=:cn AND timestamp_utc = :ts LIMIT 1`
  - `nearest`: the `asof` row and the first `> :ts` row, pick min `|Δ|` in Python.
- `pull_latest_snapshot(curve_name) -> dict | None`: `WHERE curve_name=:cn ORDER BY timestamp_utc DESC LIMIT 1` (for `timestamp="live"`).
- `latest_snapshot_ts(curve_name, trading_date) -> datetime | None`: high-water-mark for restart dedup.

Each returns a row dict with `node_dates`, `discount_factors`, `reference_key`, `interpolation`, `timestamp_utc`, `curve_name`.

**`_load_eris_live_intraday_point(requested_curve_name, timestamp, method="asof")`**:
```
assert requested_curve_name == "USD-SOFR-1D"
ASSET = "USD-SOFR-1D-ERISLIVE"
row = (pull_latest_snapshot(ASSET) if timestamp == "live"
       else pull_snapshot_asof(ASSET, _to_utc(timestamp), method))
if row is None: return None
handle = CurveStore.reconstruct_curve(row, cfg=None)            # rl.Curve
ref = row["timestamp_utc"].astimezone(ET).date()
fixings = _fetch_fixings(as_of_date=ref, curve_name=requested_curve_name, ...)
fixings = fixings[fixings.index.date < ref] * 100
ts_out = row["timestamp_utc"]
return RLIRSwapCurve(rl_curve_id=requested_curve_name, rl_curve_handle=handle,
                     fixings=fixings,
                     meta_data={"timestamp": ts_out,
                                "id": f"{self.source.upper()}-{requested_curve_name}-{ts_out}",
                                "source": "eris_live_intraday"})
```
`.handle()` → reconstructed `rl.Curve`; `.reference_date()` → its first node (CSV `Date[0]`); `.meta()["timestamp"]` → the snapshot instant.

### 4.5 The daemon (`scripts/eris_live_curve_service.py`)

Structured after `citivelo_curve_service.py`; loop after `ingest_usdswaps.py`. CLI: `run` (the service), plus `--poll-seconds 60`, `--session-start 08:00`, `--session-end 17:00`, `--stop-at 17:15`, `--asset USD-SOFR-1D-ERISLIVE`, `--once` (single poll for testing/smoke), `--log-dir`.

- **Per-session lifetime** (see §6 decision 1): starts ~06:55 ET, loops until `--stop-at` (17:15 ET), exits 0. One import/day; bounds the per-poll fetcher's fd/handle growth to a single session (§7 R1).
- **Session + holiday gate**: `ql.UnitedStates(GovernmentBond)` (the exact calendar the ERIS validator uses, so the gate and the guard agree) + 08:00–17:00 ET window (weekday implied by the business-day check).
- **Fresh request dict each poll** (§2.2).
- **Freshness**: dedup on `meta()["timestamp"]`; assert it is tz-aware, that `now_et − ts ≤ ~90 s`, and `reference_date() == today`. On assertion failure: WARNING + skip (don't persist a stale/mis-stamped curve).
- **Failure isolation**: catch `ValueError` (WARNING — both guard and empty-fetch), broad `Exception` (log + skip). Loop never dies.
- **Single-instance lock**: `O_CREAT|O_EXCL` (cache_populator pattern) + stale-PID reclaim via `os.kill(pid,0)`; lock file under `tempfile.gettempdir()/arbs_eris_live_curve/`.
- **Logging**: `RotatingFileHandler` under `logs/eris_live_curve_service/` + a structured per-cycle line (poll latency, node count, wrote|skipped, stamp). `error_verbose=True` on the MDP so fetch errors surface.

### 4.6 Windows Task Scheduler integration

- **`scripts/eris_live_curve_service.ps1`** — canonical conda wrapper: `Set-Location $repo; & conda-hook.ps1; conda activate stir; $env:PYTHONUNBUFFERED='1'; $env:ARBS_SUPABASE_ENABLED='1'; & python scripts/eris_live_curve_service.py run *> $log; exit $LASTEXITCODE`.
- **`scripts/register_eris_live_curve_task.ps1`** — `Register-ScheduledTask` with **Daily 06:55 ET** + **AtStartup** triggers (reboot recovery is safe: high-water-mark resume + idempotent upsert), `MultipleInstancesPolicy=IgnoreNew`, restart-on-failure (e.g. restart every 1 min up to 3×), run whether-or-not logged on. **Committed to git** (unlike the existing two hand-registered tasks).

## 5. Testing (`conda run -n stir`, per CLAUDE.md)

**Fast gate** (`-m "not slow and not network and not db"`):
- `build_snapshot`: correct ET `trading_date`/`session_minute`, float64 node/DF extraction, `reference_key="USD-SOFR-1D"`, `source_variant`.
- Freshness-dedup logic (skip when stamp unchanged; skip on stale/naive stamp).
- Session/holiday gate (weekend, a known US bond holiday, in/out-of-window boundaries) via a fixed injected `now_et`.
- Source-string dispatch resolves `eris_live_intraday` and skips EOD validation.
- Asset ↔ reference_key mapping.

**`db`-marked**: round-trip — `upsert_snapshot_row` → `pull_snapshot_asof`/`pull_latest_snapshot` → `reconstruct_curve` reproduces node dates and DFs **bit-for-bit**; `asof`/`nearest`/`exact`/`live` selection against a small seeded set; `ON CONFLICT` idempotency.

**`network`-marked**: one real live poll builds a valid ~18k-node curve with a fresh (`≤90 s`) tz-aware stamp and `reference_date()==today` on a business day.

Manual smoke: `python scripts/eris_live_curve_service.py run --once` on a business day writes exactly one row and logs latency/node-count.

## 6. Open sub-decisions (recommendations — confirm or override at spec review)

1. **Per-session process vs true 24/7 daemon.** *Recommended: per-session* (daily fresh process, exits after `--stop-at`) for fd/handle hygiene, since the ERIS live branch reconstructs an unclosed `ErisFuturesFetcher` every poll. A 24/7 process is possible but needs explicit fetcher cleanup or periodic GC.
2. **Poll interval = 60 s** (vendor republishes ~46 s; dedup makes over-polling free, so 30 s would capture more ticks). *Recommended: 60 s, configurable via `--poll-seconds`.*
3. **Host** = the box running `daily_cache_warmer` (the user's machine). Assumed.

## 7. Risks & mitigations

- **R1 — Fetcher fd/handle accumulation.** The live branch does `ErisFuturesFetcher(**self.config)` every poll and never `close()`s it; each opens a diskcache handle. Mitigation: per-session process bounds it to one session (~600 opens; Python GC reclaims out-of-scope fetchers via `__del__`). Watch-item: if handle growth is observed, add explicit cleanup or a periodic in-session recycle.
- **R2 — `snapshots_v1` row growth** from ~2 → ~600 rows/day/asset (~33 GB/yr relational). Acceptable (DB already has 88 GB tables, e.g. `sdr_data`); the empty-`tags` GIN index entries are cheap; the dedicated asset keeps it isolated from the EOD `USD-SOFR-1D` rows. No partitioning/TTL added in v1 (none exists in the DB); flagged for future pruning if needed.
- **R3 — Missing a vendor publish.** 60 s poll vs ~46 s cadence means occasionally two vendor snapshots fall between polls; we capture the latest. Acceptable — the target is a ~1-min grid, not every vendor tick. Reduce `--poll-seconds` if finer capture is wanted.
- **R4 — Stale orphan lock after a hard crash.** The `O_EXCL` lock has no TTL. Mitigation: stale-PID reclaim (`os.kill(pid,0)` — if the recorded PID is dead, steal the lock). AtStartup relaunch after reboot is therefore safe.
- **R5 — `snapshots_v1` semantic shift.** The table was "tagged snapshots only"; we now write untagged intraday rows under a dedicated asset. No existing reader filters by asset+untagged in a way that breaks (CITIVELO clobbering precedent showed reads key on asset name), and the dedicated asset isolates us. Documented so future readers of the table expect dense intraday rows for this one asset.

## 8. Files touched

| File | Change |
|---|---|
| `Caching/supabase_curve_sync.py` | +`upsert_snapshot_row`, +`pull_snapshot_asof`, +`pull_latest_snapshot`, +`latest_snapshot_ts` (public) |
| `MDP/IRSwaps/IRSwapsMDP.py` | +`eris_live_intraday` dispatch branch (before `:2222`), +`_load_eris_live_intraday_point` |
| `scripts/eris_live_curve_service.py` | **new** — the daemon (`run`/`--once` CLI) |
| `scripts/eris_live_curve_service.ps1` | **new** — conda wrapper |
| `scripts/register_eris_live_curve_task.ps1` | **new** — Task Scheduler registration |
| `tests/test_eris_live_curve_service.py` | **new** — fast + db + network tests |

## 9. Rollout

1. Land helpers + read path + daemon + tests; fast gate green.
2. `run --once` smoke on a business day; verify one row + bit-exact `pull → reconstruct`.
3. Read back via `IRSwapsMDP("eris_live_intraday")` for a couple of minutes and `"live"`.
4. Register the task; observe one full session; check row count (~one/min), log health, no fd growth.
5. (Deferred) dashboard/consumer wiring on top of the read API.
