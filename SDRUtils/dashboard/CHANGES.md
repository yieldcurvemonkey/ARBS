# Performance Audit Fixes — 2026-05-07

## P0 — Deploy current source

**Status:** Ready to deploy. Build succeeds. All code changes are on `main`.

| Item | Status | Verification |
|------|--------|-------------|
| lookbackDays cap 365→730 | In source | `route.logic.ts:97` — test added |
| LRU 2048/300s | In source | All 5 route files |
| candidatesMode | In source | `analytics.ts` + all 3 analytics routes |
| Outright fast-path | In source | rarity, extremes, analytics-timeseries |
| Functional index `idx_tape_v2_packages_tape_label_upper` | **Live on prod DB** | Verified via `pg_indexes` query |
| vercel.json `no-store` removed | In source | `headers: []` |

**Action needed:** Push this branch and deploy to Vercel.

## P1 — Vercel Deployment Protection

**Status:** Requires manual action in Vercel dashboard.

Deployment Protection overrides `Cache-Control` to `max-age=60, must-revalidate` and strips `Server-Timing` headers. Disabling it for the production domain restores the intended `max-age=300, stale-while-revalidate=600`.

**Action needed:** Vercel dashboard → Project Settings → Deployment Protection → Disable for production domain.

## P1 — Cron cache warmer

**Status:** Implemented.

- `src/app/api/cron/warm-analytics/route.ts` — iterates top 18 tape labels, fetches analytics-timeseries + rarity + extremes for each
- `vercel.json` — cron schedule `*/4 * * * *` (every 4 min, under the 5-min LRU TTL)
- Protected by `CRON_SECRET` bearer token

**Action needed:** Add `CRON_SECRET` env var to Vercel (generate a random 32-char string).

## P2 — Server-Timing on volume-grid routes

**Status:** Implemented.

Both `volume-grid/route.ts` and `volume-grid/cell/route.ts` refactored to use the shared `analyticsHandler` from `src/lib/usd-swaps-tape-v2/analyticsHandler.ts`. All responses now include `Server-Timing: db;dur=X, lru;dur=Y;desc="hit|miss", total;dur=Z`.

## P2 — /usts-rv stale data

**Status:** Investigated. Root cause: the `ingest_ustrv.py` pipeline is not running.

The UST RV data lives in `arbs_ust_rv_points_v1` and `arbs_ust_rv_intraday_points_v1`. Last successful ingestion was 2026-03-13. The pipeline (`SDRUtils/_swappulse_scripts/ingest_ustrv.py --mode incremental`) needs to be restarted or scheduled via cron.

**Action needed:** Restart the UST RV ingestion pipeline. Either:
- Run `conda run -n stir python -m SDRUtils._swappulse_scripts.ingest_ustrv --mode service` as a persistent process
- Or add a daily cron job for `--mode incremental`

## P3 — 3m volume-grid window (5.5s)

**Status:** Not yet addressed. The 3m window scans ~90 days of legs data. Options:
1. Pre-aggregated daily rollup table
2. Materialized view refreshed hourly
3. Additional composite index on `(contributes_to_flow, execution_timestamp)` covering the bucket dimensions

Recommend investigating EXPLAIN ANALYZE before choosing approach.
