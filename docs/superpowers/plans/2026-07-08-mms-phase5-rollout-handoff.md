# MMS — Phase 5 Rollout Hand-off (deploy-gated, human-run against prod)

Everything through Phase 4 is merged into `feat/mms-package-detection` (PR #334) and
validated (Python 2418 pass; dashboard jest green; independent reviews PASS; clean
merge with `main`/#333). The steps below are the **only** remaining work, and they
are intentionally **not** run by automation: they write to the **prod trading DB**
(remote Supabase) and deploy the dashboard. `DATABASE_URL` is not present in the
automation environment, and per the #333 note prod schema changes are human-gated.

Run from the repo root with the prod `DATABASE_URL` exported (same value as the
dashboard's `.env.local`). Python via `conda run -n stir`.

## 0. Prerequisites already done (in the branch)
- `DETECTION_CACHE_VERSION = "ptp3-mms-pkg"`, `TRADE_TAPE_CACHE_VERSION = "v11-ust-alias-pkg"` — bumped, so the backfill recomputes from scratch (no stale cache).
- Additive schema: idempotent `ADD COLUMN IF NOT EXISTS` for the new leg/package MMS columns + display-view SELECT. `ensure_schema` runs automatically inside `backfill`.

## 1. #333 prerequisites (from the regrouping PR — must be live first)
Per the #333 hand-off note, before the write path works:
1. Apply the #333 DB migration (its 4 new override/notes tables + view change) to prod.
2. Set `TAPE_OVERRIDE_PASSWORD` in the dashboard env (unset ⇒ structural writes 403).
3. Full write-path browser E2E once that migration is live.
These are independent of MMS but share the same tape/dashboard; do them (or confirm
already done) so the merged dashboard is fully functional.

## 2. Schema migration + bounded backfill (sanity check)
Start with ONE day that is known to contain all-MMS packages (2026-07-06 has 10),
so you can eyeball prod before the full rewrite. `ensure_schema` (incl. the MMS
columns + view) runs as part of this.

```bash
export DATABASE_URL='postgresql://…prod…'   # same as dashboard .env.local
conda run -n stir python SDRUtils/_swappulse_scripts/run_usdswaps_pipeline.py \
    backfill --date 2026-07-06
```

Verify in the DB (or dashboard) that 2026-07-06 packages now carry
`package_type IN ('MATCHED_MATURITY_CURVE','MATCHED_MATURITY_FLY')` and/or
`special_tenor_type='MATCHED_MATURITY'`, and `tape_label_ust_alias` is populated
(e.g. `0236` for cusip `91282CPZ8` @ 2036-02-15 clips).

## 3. Full backfill (DESTRUCTIVE delete+rewrite of the date range)
Once the single-day looks right, rewrite the full history you serve. Pick the range
you want live (example spans the cached corpus):

```bash
conda run -n stir python SDRUtils/_swappulse_scripts/run_usdswaps_pipeline.py \
    backfill --start 2026-05-11 --end 2026-07-06
```

This deletes+rewrites those dates. Run deliberately; it is the one irreversible step.

## 4. Deploy the dashboard
Deploy the merged dashboard (MMS badges/labels + #333 regrouping). No rebuild of the
DB is needed beyond the backfill. `TAPE_DISPLAY_VIEW` already points at `_v2`.

## 5. Live browser E2E (post-deploy)
On the deployed tape, confirm:
- Package rows with all legs on a UST show the **MMS / MMS Curve / MMS Fly** badge.
- The tape label shows the **MMYY alias** (`0236`, or `0536/0546` for diff-bond
  curves), bolded, in place of the raw tenor.
- Expanding a matched-maturity package shows each leg's own MMYY alias in the legs
  sub-table (and mobile cards).
- Non-MMS rows are unchanged; regrouping (GROUP/SPLIT/DETACH) + notes still work.

## ⚠️ Findings from the 2026-07-08 live attempt (READ THIS)

A single-day backfill was attempted against prod and **`ensure_schema` deadlocked**;
no MMS columns were applied. Root causes:

1. **#333's prod migration is a hard prerequisite.** `ensure_schema`'s
   `_schema_already_current()` guard keys off `_LATEST_MIGRATION_COLS`, which
   includes `overrides_v2.override_id` and `display_v2.override_map` (from #333).
   Those don't exist on prod (the #333 migration is deploy-gated and not yet
   applied), so `ensure_schema` tries to apply the **entire #333 + MMS migration
   in one bundle** — including a **DROP/CREATE of the display view** — every run.
2. **Live-traffic lock contention.** The prod tape tables are served by live
   dashboard/analytics queries (~50s each, holding `AccessShareLock`).
   `_execute_ddl_bundle` uses a 3s `lock_timeout`, so the `ACCESS EXCLUSIVE` DDL
   (esp. the view rebuild) can never win → deadlock+rollback after retries.
3. **Code fix applied (commit `7672f732`):** `_LATEST_MIGRATION_COLS` now
   registers the MMS markers, so once the migration does run it correctly
   detects the MMS columns as pending (previously it would have *skipped* the
   MMS DDL once the #333 markers existed).
4. The sanity backfill did re-upsert 2026-07-06 with the new detection (a few
   `MATCHED_MATURITY_CURVE` package_types persisted; alias columns did **not**,
   since they don't exist yet). Harmless — the full backfill below rewrites it
   consistently.

### Safe procedure (run in a maintenance / low-traffic window)
1. **Quiesce writers/heavy readers**: pause the live `run_usdswaps_pipeline`
   service and avoid heavy dashboard/analytics load so the view DROP/CREATE can
   grab its lock. (Optionally raise `_execute_ddl_bundle`'s `lock_timeout`.)
2. **Apply the migration** (this includes #333's tables + view AND the MMS
   columns) — either run `ensure_schema` directly, or the single-day backfill
   which calls it:
   ```bash
   export DATABASE_URL='…prod…'
   conda run -n stir python -c "from sqlalchemy import create_engine; import os; \
     from SDRUtils._swappulse_scripts import ingest_usdswaps_tape as t; \
     t.ensure_schema(create_engine(os.environ['DATABASE_URL']))"
   ```
   Confirm no deadlock and that `special_tenor_type`, `tape_label_ust_alias`,
   `is_matched_maturity_all` now exist on the tape tables + display view.
3. Set `TAPE_OVERRIDE_PASSWORD` (per #333).
4. **Then** the single-day + full backfill (§2/§3 above) will persist MMS data.

## Rollback
- Data: re-run `backfill` for the range from an earlier `DETECTION_CACHE_VERSION`
  checkout, or restore from the DB's PITR/backup.
- Dashboard: redeploy the prior build. The MMS columns are additive (nullable), so
  the old dashboard reads the new tape harmlessly.
