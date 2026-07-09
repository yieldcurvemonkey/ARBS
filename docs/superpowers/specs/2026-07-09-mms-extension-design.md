# MMS Extension — Ops, UX, Analytics, Detection Research

**Date:** 2026-07-09
**Status:** Design (pending review)
**Predecessor:** `docs/superpowers/specs/2026-07-08-mms-package-detection-design.md` (PR #334/#335, merged)
**Area:** Pipeline ops, dashboard UX/analytics, detection research, infra hygiene

## 0. Context

PR #334/#335 landed MMS package detection end-to-end: detection → labels → ingest
→ schema → dashboard → prod backfill (2026-05-11 … 2026-07-06). This spec extends
the feature across four workstreams that can largely execute in parallel.

**Current state (verified 2026-07-09):**
- All detection, label, ingest, schema, and dashboard code is on main.
- `DETECTION_CACHE_VERSION = "ptp3-mms-pkg"`, `TRADE_TAPE_CACHE_VERSION = "v11-ust-alias-pkg"`.
- Prod schema migrated; backfill complete for 5/11–7/6.
- Live pipeline service NOT running merged code — last ran under `ptp2` (logs stop
  7/6, no `packaged_day_ptp3-mms-pkg.pkl`). New trades since 7/7 have no MMS detection.
- Dashboard tooltip gate (`pkgLegsLines` in `TapeLabelCell.tsx:15`) still gated on
  `PKG-` only — CURVE/FLY/MMS packages don't get hover tooltip.
- `C:\clee\ARBS-mms` worktree + `feat/mms-package-detection` branch still exist (merged).

## 1. Ops & Infra

### 1a. Pipeline restart verification

The service must be restarted manually (`conda run -n stir python
run_usdswaps_pipeline.py service`). On restart with current main:
- First cycle finds no warm-start cache for `ptp3-mms-pkg` → cold-starts
- Classification cache misses for new version directory → full reclassify
- New trades from 7/7+ get MMS detection automatically

**Verification:** Confirm `packaged_day_ptp3-mms-pkg.pkl` appears in
`sdr_cache/service_caches/`; query prod for today's MMS packages.

This is a manual ops step, not code. Documented here as a prerequisite.

### 1b. `--lock-timeout` CLI flag

Add `--lock-timeout` argument (milliseconds, default 5000) to `backfill` and
the new `migrate` subcommands in `run_usdswaps_pipeline.py`.

Thread through: `run_usdswaps_pipeline.py` argparse → `ensure_schema()` signature
(add `lock_timeout_ms` kwarg) → `_execute_ddl_bundle(lock_timeout_ms=...)`.

**Files:**
- Modify: `SDRUtils/_swappulse_scripts/run_usdswaps_pipeline.py` (argparse for backfill + migrate)
- Modify: `SDRUtils/_swappulse_scripts/ingest_usdswaps_tape.py` (`ensure_schema` signature)

### 1c. `migrate` subcommand

New `run_usdswaps_pipeline migrate` mode:
- Runs `ensure_schema` only — no classification, no tape rebuild, no delete+rewrite
- Accepts `--lock-timeout` (default 90000ms — generous for view rebuild under light load)
- Prints which columns/views were created vs already existed
- For maintenance-window schema changes without a full backfill

**Files:**
- Modify: `SDRUtils/_swappulse_scripts/run_usdswaps_pipeline.py` (new subparser + handler)

### 1d. TAPE_OVERRIDE_PASSWORD hardening

The tape override API route reads `process.env.TAPE_OVERRIDE_PASSWORD`. Currently
falls back to `"admin"` when unset. Fix: remove the fallback default so the route
returns 403 when the env var is unset. Document in `.env.local.example`.

**Files:**
- Modify: The API route handling tape overrides (identify exact path during implementation)
- Modify: `SDRUtils/dashboard/.env.local.example`

### 1e. Worktree + branch cleanup

- Delete `C:\Users\chris\clee\ARBS-mms` worktree: `git worktree remove ARBS-mms`
- Delete local branch: `git branch -d feat/mms-package-detection`
- Delete remote branch: `git push origin --delete feat/mms-package-detection`

Manual git ops.

## 2. Dashboard UX — Tape View

### 2a. Tooltip gate widen

`pkgLegsLines` in `TapeLabelCell.tsx` (line 15) gates on `kind.startsWith('PKG-')`.
Widen to fire for all multi-leg package types:

```typescript
const isMultiLeg =
  kind.startsWith('PKG-') ||
  kind === 'CURVE' || kind === 'FLY' ||
  kind.startsWith('MATCHED_MATURITY') ||
  kind.endsWith('_CURVE') || kind.endsWith('_FLY')
if (!isMultiLeg) return null
```

Also update tooltip line source to prefer `leg_tape_label_ust_alias`:
```typescript
l.leg_tape_label_ust_alias ?? l.leg_tape_label ?? l.tape_label ?? ''
```

**Files:**
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/TapeLabelCell.tsx` (~lines 14-24)
- Test: Extend `TapeLabelCell.test.ts`

### 2b. MMS filter in tape view

Add MMS to existing package-type filter controls:

- **Filter predicate:** `is_matched_maturity_all === true` OR `package_type` starts
  with `MATCHED_MATURITY`. Catches composite types (MATCHED_MATURITY_CURVE/FLY)
  and all-MMS PKG-N packages.
- **Filter UI:** "MMS" toggle chip in the existing filter bar, following the pattern
  of existing package-type filter chips.

**Files:**
- Modify: The tape filter component (identify exact file during implementation)
- Test: Extend existing filter tests

### 2c. Big-PKG-N alias collapse

When a joined alias has >4 slash-separated segments, truncate in the tape label:
`0330/0530/0730/…+27 more`

- Full alias remains visible in expanded LegsSubTable and hover tooltip
- Collapse in `displayTapeLabel` via a new `collapseAlias(alias, maxSegments=4)` helper
- Purely display-side, no backend change

**Files:**
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/TapeLabelCell.helpers.ts`
- Test: Extend `TapeLabelCell.test.ts`

## 3. MMS Analytics Tab

### 3a. Architecture

Follows the **CardsDrawer pattern** — pure client-side aggregation over the `rows`
prop passed to `AnalyticsPanel`. No new API endpoint. MMS fields are already on every
row: `is_matched_maturity_all`, `package_type`, `special_tenor_type`,
`matched_ust_maturity`, `tape_label_ust_alias`.

The tab is **always visible** — not gated on a focused trade (unlike Timeseries/Rarity/
Levels). It aggregates across the full loaded row set.

### 3b. Tab registration

1. Add `'mms'` to `AnalyticsTab` union in `analytics-types.ts` (line 10)
2. Add tab config: `{ key: 'mms', label: 'MMS', icon: '⬡', badge: '{count}' }` in
   `AnalyticsPanel.tsx` tabs array (~line 466). Badge = count of MMS packages in loaded rows.
3. Tab renders unconditionally (not gated on mode like Sequence)
4. New `MmsTab.tsx` component in `AnalyticsPanel/`
5. New `MmsState` type + `MMS_DEFAULT_STATE` in `analytics-types.ts` / `constants.ts`
6. `useState<MmsState>` in `AnalyticsPanel.tsx`
7. Conditional render: `{activeTab === 'mms' ? <MmsTab .../> : null}` (~line 534)

### 3c. Tab content — 4 panels

**Panel 1: Summary stats strip**

Horizontal row of stat cards (SequenceTab `SummaryCell` pattern):

| Stat | Computation |
|------|-------------|
| MMS Packages | Count where `is_matched_maturity_all === true` OR `package_type.startsWith('MATCHED_MATURITY')` |
| % of Total | MMS count / total package count |
| MMS DV01 | `Σ Math.abs(Number(row.total_risk ?? 0))` for MMS rows |
| DV01 Share | MMS DV01 / total DV01 |
| MMS Notional | `Σ Number(row.notional_amount ?? 0)` for MMS rows |

Time-window selector (today / 7d / 30d / 90d / YTD) using `filterRowsToWindow`
from `utils/underlierMix.ts`.

**Panel 2: Daily MMS volume chart**

Recharts `BarChart` — one bar per execution date. Height = MMS package count (or
DV01, switchable via metric control). Overlaid line for MMS % share of daily total.
Day-bucketing via `execution_start` date-string slice (pattern from `swapSpreadVwap.ts`).

**Panel 3: Maturity distribution**

Horizontal bar chart bucketed by MMYY alias. Parse `tape_label_ust_alias` to extract
unique MMYY tokens (split on `/`), count occurrences. Sorted frequency descending.
Metric switchable: count / DV01 / notional. Shows which UST maturities are most
actively asset-swapped.

**Panel 4: Top matched CUSIPs**

Table of most frequently matched UST CUSIPs. Data source: `legs_json` → filter legs
where `matched_ust_maturity === true` → aggregate by `ust_cusip`. Columns:

| Column | Source |
|--------|--------|
| CUSIP | `leg.ust_cusip` |
| MMYY | `leg.tape_label_ust_alias` parsed |
| Count | Occurrences |
| Total DV01 | `Σ Math.abs(leg risk)` |
| Total Notional | `Σ notional` |

Sorted by count desc, top 10.

### 3d. Utility

New `utils/mmsAnalytics.ts`:
- `isMmsRow(row): boolean` — predicate encapsulating the MMS filter logic
- `computeMmsSummary(rows, window)` → summary stats object
- `computeMmsDailyVolume(rows)` → `Array<{ date, count, dv01, share }>`
- `computeMmsMaturityDistribution(rows)` → `Array<{ mmyy, count, dv01, notional }>`
- `computeMmsTopCusips(rows)` → `Array<{ cusip, mmyy, count, dv01, notional }>`

Follows existing patterns: `filterRowsToWindow`, `Math.abs(Number(row.total_risk ?? 0))`,
day-bucketing. The `isMmsRow` predicate is shared with Section 2b's filter.

### 3e. State

```typescript
type MmsState = {
  window: 'today' | '7d' | '30d' | '90d' | 'ytd'
  volumeMetric: 'count' | 'dv01'
  distributionMetric: 'count' | 'dv01' | 'notional'
}
```

Default: `{ window: '30d', volumeMetric: 'count', distributionMetric: 'count' }`.

## 4. Detection Research

All three items are **read-only analysis** — output is a research document with
empirical data and policy recommendations. No detection code changes. Runs against
local `sdr_cache` classification parquets (no network, no DB).

### 4a. IMM-start MMS false-positive analysis

**Question:** If the IMM gate were removed, how many new matches appear, and how
many are genuine asset swaps vs coincidental IMM-on-UST-coupon overlaps?

**Method:**
1. Run `_match_swaps_to_ust_by_maturity` over 43-day cached corpus with IMM gate disabled
2. Count new matches the gate currently excludes
3. For each: check if matched UST is on-the-run/current coupon (likely coincidence)
   vs off-the-run (more likely genuine)
4. Check if swap's `forward_label` is `IMM_*` (structured IMM rolls, not asset swaps)
5. Report: total excluded, likely-genuine, likely-false-positive, recommended guard

### 4b. Near-clean broken-tenor quantification

**Question:** How many packages go from "partial" to "all-MMS" if near-clean legs
(within ±0.1y of a standard tenor but exactly tying a bond) were included?

**Method:**
1. Find packages where some legs are MMS and others excluded by `is_clean_tenor`
2. For each excluded leg: did its `expiration_date` match a UST maturity before
   the clean-tenor gate wiped it?
3. Count partial → all-MMS promotions
4. Sample trades for manual economic-intent inspection

### 4c. T-bill vs short-note data study

**Question:** Among short-dated matches (<1Y tenor), how many tie T-bills (912797*)
vs short-dated coupon notes?

**Method:**
1. Filter corpus for `matched_ust_maturity=True` AND `tenor_years < 1.0`
2. Join UST reference for `security_type` and CUSIP prefix
3. Bucket: T-bill vs coupon note
4. If all short-dated matches are bills → recommend exclusion gate
5. If some are short-dated notes → keep low confidence, no gate

### 4d. Output

Research document at `docs/superpowers/research/2026-07-09-mms-detection-depth.md`
with tables, sample trades, and policy recommendations for each area.

## 5. Verification

### 5a. Post-restart pipeline

1. Confirm `packaged_day_ptp3-mms-pkg.pkl` appears in `sdr_cache/service_caches/`
2. Query prod: `SELECT count(*) FROM arbs_usd_swap_tape_packages_v2 WHERE
   execution_date = CURRENT_DATE AND is_matched_maturity_all = true`
3. Confirm new classification cache entries in the `ptp3-mms-pkg` directory

### 5b. Dashboard chrome-MCP E2E

After all dashboard changes, at localhost:3000:
1. MMS filter shows only MMS packages
2. Tooltip shows per-leg alias for MMS Curve/Fly packages
3. Big-PKG-N alias collapsed in tape, full in tooltip/LegsSubTable
4. Analytics dock → MMS tab renders: summary stats, daily volume, maturity
   distribution, top CUSIPs
5. No console errors, no regressions in existing tabs
6. Screenshot capture

### 5c. Test gates

- Python: `conda run -n stir python -m pytest tests -m "not slow and not network and not db"`
- Dashboard: `npm test` + `npx tsc --noEmit` + `npm run build`
- New tests: MMS analytics utility functions, tooltip gate, alias collapse helper

## 6. Hard constraints (inherited from predecessor spec)

- Run Python/pytest via `conda run -n stir`.
- **Do NOT loosen coincidence gates** (clean-tenor, spot-only, IMM, exact-date join,
  short-dated downgrade) — they are unchanged in this spec; detection research
  (§4) produces recommendations only.
- Any detector-output change bumps `DETECTION_CACHE_VERSION`; any tape-enrichment
  change bumps `TRADE_TAPE_CACHE_VERSION`. **This spec changes neither** — all
  detection/label code is already landed.
- Prod tape DB is remote Supabase. Schema migrations use `_execute_ddl_bundle` with
  per-statement retry. The new `migrate` subcommand (§1c) is the intended tool.
- Verify dashboard changes in chrome-MCP against localhost before deploying.
- Dashboard jest: `npm test` only (not bare `npx jest`).

## 7. Non-goals (explicitly excluded)

- **Swap-vs-UST spread computation** — dropped per design discussion.
- **Detection code changes** — IMM-start, near-clean, T-bill are research only.
- **New API endpoints** — MMS analytics tab is client-side.
- **Older-history backfill** (pre-2026-05-11) — optional, not in scope.
