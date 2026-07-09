# MMS Extension — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the landed MMS package detection with pipeline restart, infra hardening, dashboard UX improvements (tooltip/filter/alias collapse), a new MMS analytics tab in the Analytics dock, and detection-depth research.

**Architecture:** Four parallel workstreams: (1) Python CLI additions for `--lock-timeout` and a `migrate` subcommand, (2) TypeScript dashboard UX fixes in the tape table, (3) a new MMS tab in the existing AnalyticsPanel (client-side aggregation over `rows`), (4) Python research script producing a detection-depth analysis doc. Plus ops steps (pipeline restart, worktree cleanup).

**Tech Stack:** Python 3 / pandas / argparse (CLI + research), TypeScript / React / Recharts / PrimeReact (dashboard), Jest (dashboard tests), pytest under `conda run -n stir` (Python tests).

## Global Constraints

- Run ALL Python/pytest via `conda run -n stir python -m pytest ...` (repo requires the `stir` conda env).
- Fast gate: `conda run -n stir python -m pytest tests -m "not slow and not network and not db"`.
- **Do NOT touch coincidence gates** — `spot_start_mask`, `is_clean_tenor`, exact-date join, IMM guard, short-dated confidence. These are unchanged; detection research (Phase 4) is read-only.
- This spec changes NO detector output → do NOT bump `DETECTION_CACHE_VERSION` or `TRADE_TAPE_CACHE_VERSION`.
- Dashboard jest: invoke via `npm test` (NOT bare `npx jest`) so ESM mocks load.
- Verify dashboard changes in chrome-MCP against localhost before deploying.
- `TAPE_OVERRIDE_PASSWORD` is already env-only in code (`isValidTapeWritePassword` in `SDRUtils/dashboard/src/lib/utils.ts:53-57` returns false when env is unset). The "hardening" is an ops step: change the env var value from `admin` to a proper secret. No code change needed.
- Worktree cleanup (`C:\Users\chris\clee\ARBS-mms`) and branch deletion (`feat/mms-package-detection`) are manual git ops executed during verification.

---

## Phase 1 — Infra (Python CLI)

### Task 1: Thread `--lock-timeout` through `ensure_schema`

**Files:**
- Modify: `SDRUtils/_swappulse_scripts/ingest_usdswaps_tape.py:557` (`ensure_schema` signature)
- Modify: `SDRUtils/_swappulse_scripts/run_usdswaps_pipeline.py:254,328,405,409,826` (argparse + call sites)
- Test: `tests/test_ddl_bundle.py` (extend)

**Interfaces:**
- Consumes: `_execute_ddl_bundle(engine, ddl, lock_timeout_ms=5_000)` (existing, line 492)
- Produces: `ensure_schema(engine, _max_retries=5, lock_timeout_ms=5_000)` — new kwarg forwarded to every `_execute_ddl_bundle` call inside. `cmd_backfill` and `_run_tape_for_dates` accept and forward `lock_timeout_ms`.

- [ ] **Step 1: Write the failing test** — append to `tests/test_ddl_bundle.py`:

```python
from unittest.mock import patch, MagicMock
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import ensure_schema


def test_ensure_schema_forwards_lock_timeout():
    """ensure_schema passes lock_timeout_ms to _execute_ddl_bundle."""
    mock_engine = MagicMock()
    mock_engine.url = "postgresql://test/test"
    with patch(
        "SDRUtils._swappulse_scripts.ingest_usdswaps_tape._schema_already_current",
        return_value=False,
    ), patch(
        "SDRUtils._swappulse_scripts.ingest_usdswaps_tape._execute_ddl_bundle"
    ) as mock_ddl, patch(
        "SDRUtils._swappulse_scripts.ingest_usdswaps_tape._schema_ensured",
        set(),
    ):
        ensure_schema(mock_engine, lock_timeout_ms=90_000)
        for call in mock_ddl.call_args_list:
            assert call.kwargs.get("lock_timeout_ms") == 90_000 or \
                   (len(call.args) >= 3 and call.args[2] == 90_000), \
                f"lock_timeout_ms not forwarded: {call}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n stir python -m pytest tests/test_ddl_bundle.py::test_ensure_schema_forwards_lock_timeout -v`
Expected: FAIL — `ensure_schema` does not accept `lock_timeout_ms`.

- [ ] **Step 3: Add `lock_timeout_ms` to `ensure_schema`** — in `SDRUtils/_swappulse_scripts/ingest_usdswaps_tape.py`, change line 557:

```python
def ensure_schema(engine: Engine, _max_retries: int = 5) -> None:
```

to:

```python
def ensure_schema(
    engine: Engine, _max_retries: int = 5, lock_timeout_ms: int = 5_000
) -> None:
```

Then update the three `_execute_ddl_bundle` calls inside (lines 582-584):

```python
            _execute_ddl_bundle(engine, TAPE_SCHEMA_SQL, lock_timeout_ms=lock_timeout_ms)
            _execute_ddl_bundle(engine, TAPE_SCHEMA_SQL_V2, lock_timeout_ms=lock_timeout_ms)
            _execute_ddl_bundle(engine, MONITORING_SQL_V2, lock_timeout_ms=lock_timeout_ms)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n stir python -m pytest tests/test_ddl_bundle.py::test_ensure_schema_forwards_lock_timeout -v`
Expected: PASS.

- [ ] **Step 5: Add `--lock-timeout` to the `backfill` subparser** — in `run_usdswaps_pipeline.py`, after line 826 (`_add_common_flags(bp)`), before `bp.set_defaults(func=cmd_backfill)` (line 827), add:

```python
    bp.add_argument(
        "--lock-timeout",
        type=int,
        default=5_000,
        help="DDL lock_timeout in milliseconds (default: 5000).",
    )
```

- [ ] **Step 6: Thread through `_run_tape_for_dates` and `cmd_backfill`** — add `lock_timeout_ms` kwarg to `_run_tape_for_dates` (line 236):

```python
def _run_tape_for_dates(
    dates,
    *,
    pg_url: Optional[str],
    use_cache: bool,
    stop_on_error: bool,
    cache_path: Optional[str] = None,
    lock_timeout_ms: int = 5_000,
) -> int:
```

Change line 254:

```python
    ingest_usdswaps_tape.ensure_schema(tape_engine, lock_timeout_ms=lock_timeout_ms)
```

In `cmd_backfill` (line 328), add the kwarg:

```python
    failures = _run_tape_for_dates(
        _iter_dates(start, end),
        pg_url=args.pg_url,
        use_cache=not args.no_tape_cache,
        stop_on_error=not args.continue_on_error,
        cache_path=args.cache_path,
        lock_timeout_ms=args.lock_timeout,
    )
```

- [ ] **Step 7: Run the full DDL test suite**

Run: `conda run -n stir python -m pytest tests/test_ddl_bundle.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add SDRUtils/_swappulse_scripts/ingest_usdswaps_tape.py SDRUtils/_swappulse_scripts/run_usdswaps_pipeline.py tests/test_ddl_bundle.py
git commit -m "feat(infra): thread --lock-timeout through ensure_schema + backfill CLI"
```

---

### Task 2: `migrate` subcommand

**Files:**
- Modify: `SDRUtils/_swappulse_scripts/run_usdswaps_pipeline.py` (new subparser + handler, after `cmd_incremental`)

**Interfaces:**
- Consumes: `ensure_schema(engine, lock_timeout_ms=...)` from Task 1
- Produces: `cmd_migrate(args)` — runs `ensure_schema` only, prints column status

- [ ] **Step 1: Add `cmd_migrate` handler** — in `run_usdswaps_pipeline.py`, after `cmd_incremental` (after line 370), add:

```python
# ---------------------------------------------------------------------------
# Subcommand: migrate
# ---------------------------------------------------------------------------


def cmd_migrate(args: argparse.Namespace) -> int:
    """Run schema migration only — no classification, no tape rebuild."""
    _banner("Schema migration (ensure_schema only)")
    lock_ms = args.lock_timeout
    print(f"  Lock timeout: {lock_ms}ms")
    print(f"  Dry run:      {args.dry_run}")

    if args.dry_run:
        print("Dry run — skipping migration.")
        return 0

    resolved_pg_url = ingest_usdswaps_tape.resolve_pg_url(args.pg_url)
    tape_engine = ingest_usdswaps_tape.create_engine(resolved_pg_url)

    already_current = ingest_usdswaps_tape._schema_already_current(tape_engine)
    if already_current:
        print("Schema is already current — all migration columns present.")
        return 0

    print("Schema needs migration — applying DDL…")
    ingest_usdswaps_tape.ensure_schema(
        tape_engine, lock_timeout_ms=lock_ms,
    )
    print("Migration complete.")
    return 0
```

- [ ] **Step 2: Register the subparser** — in the argparse setup section (after the `service` subparser block, before `args = parser.parse_args()`), add:

```python
    # migrate
    mp = subparsers.add_parser(
        "migrate",
        help="Run schema migration only (ensure_schema). No classification or tape rebuild.",
    )
    mp.add_argument(
        "--lock-timeout",
        type=int,
        default=90_000,
        help="DDL lock_timeout in milliseconds (default: 90000 for migrations).",
    )
    _add_common_flags(mp)
    mp.set_defaults(func=cmd_migrate)
```

- [ ] **Step 3: Verify it wires up** — run:

```bash
conda run -n stir python SDRUtils/_swappulse_scripts/run_usdswaps_pipeline.py migrate --help
```

Expected: shows `--lock-timeout`, `--pg-url`, `--dry-run` flags.

- [ ] **Step 4: Run the fast gate**

Run: `conda run -n stir python -m pytest tests -m "not slow and not network and not db" -q`
Expected: PASS (no regressions).

- [ ] **Step 5: Commit**

```bash
git add SDRUtils/_swappulse_scripts/run_usdswaps_pipeline.py
git commit -m "feat(infra): add 'migrate' subcommand (ensure_schema only, 90s lock default)"
```

---

## Phase 2 — Dashboard UX (TypeScript)

### Task 3: Widen tooltip gate + MMS alias collapse

**Files:**
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/TapeLabelCell.tsx:12-30`
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/TapeLabelCell.helpers.ts:48-64`
- Test: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/__tests__/TapeLabelCell.test.ts` (extend)

**Interfaces:**
- Consumes: `UsdSwapTapeRow` with `package_type`, `legs_json` (each leg has `leg_tape_label_ust_alias`), `tape_label_ust_alias`.
- Produces: `pkgLegsLines` returns tooltip lines for CURVE/FLY/MATCHED_MATURITY* packages. `collapseAlias(alias, maxSegments)` truncates long aliases. `displayTapeLabel` applies collapse before returning.

- [ ] **Step 1: Write the failing tests** — append to `TapeLabelCell.test.ts`:

```typescript
import { displayTapeLabel, parseTapeLabelSegments } from '../TapeLabelCell.helpers'

describe('pkgLegsLines gate', () => {
  // pkgLegsLines is not exported — test via the component or export it.
  // For now, test via displayTapeLabel + collapseAlias which are exported.
})

describe('collapseAlias', () => {
  it('leaves short aliases unchanged', () => {
    const label = displayTapeLabel({
      tape_label_ust_alias: 'USD-SOFR Spot 0536/0546 CURVE MMS PHYS',
      tape_label: 'USD-SOFR Spot 10Y/20Y CURVE MMS PHYS',
      n_package_legs: 2,
    } as any)
    expect(label).toContain('0536/0546')
  })

  it('collapses aliases with >4 segments', () => {
    const longAlias = '0330/0530/0730/0930/1130/0131/0331'
    const label = displayTapeLabel({
      tape_label_ust_alias: `USD-SOFR Spot ${longAlias} PKG-7 MMS PHYS`,
      tape_label: 'USD-SOFR Spot 3Y/5Y/7Y/9Y/11Y/13Y/15Y PKG-7 MMS PHYS',
      n_package_legs: 7,
    } as any)
    expect(label).toContain('0330/0530/0730')
    expect(label).toContain('…+4')
    expect(label).not.toContain('1130')
  })

  it('does not collapse exactly 4 segments', () => {
    const label = displayTapeLabel({
      tape_label_ust_alias: 'USD-SOFR Spot 0236/0536/0746/1046 PKG-4 MMS PHYS',
      tape_label: 'fallback',
      n_package_legs: 4,
    } as any)
    expect(label).toContain('0236/0536/0746/1046')
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `SDRUtils/dashboard`): `npm test -- TapeLabelCell.test`
Expected: The ">4 segments" test FAILS — no collapse logic exists yet.

- [ ] **Step 3: Add `collapseAlias` to `TapeLabelCell.helpers.ts`** — add this function before `displayTapeLabel` (before line 48):

```typescript
/**
 * Truncate a slash-joined MMYY alias when it has more than `max` segments.
 * "0330/0530/0730/0930/1130" → "0330/0530/0730/…+2"
 */
function collapseAlias(label: string, max = 4): string {
  // Match a run of slash-separated 4-digit tokens (MMYY aliases).
  return label.replace(/\b(\d{4}(?:\/\d{4}){4,})\b/g, (match) => {
    const parts = match.split('/')
    if (parts.length <= max) return match
    return parts.slice(0, max - 1).join('/') + `/…+${parts.length - (max - 1)}`
  })
}
```

- [ ] **Step 4: Wire `collapseAlias` into `displayTapeLabel`** — in `displayTapeLabel` (line ~60-61), change:

```typescript
      const stripped = stripExecutionTags(label.trim())
      return collapseTenors(stripped, row.n_package_legs)
```

to:

```typescript
      const stripped = stripExecutionTags(label.trim())
      return collapseAlias(collapseTenors(stripped, row.n_package_legs))
```

- [ ] **Step 5: Widen `pkgLegsLines` gate** — in `TapeLabelCell.tsx`, replace lines 13-14:

```typescript
  const kind = String(row.package_type ?? '').toUpperCase()
  if (!kind.startsWith('PKG-')) return null
```

with:

```typescript
  const kind = String(row.package_type ?? '').toUpperCase()
  const isMultiLeg =
    kind.startsWith('PKG-') ||
    kind === 'CURVE' || kind === 'FLY' ||
    kind.startsWith('MATCHED_MATURITY') ||
    kind.endsWith('_CURVE') || kind.endsWith('_FLY')
  if (!isMultiLeg) return null
```

- [ ] **Step 6: Run tests to verify they pass**

Run (from `SDRUtils/dashboard`): `npm test -- TapeLabelCell.test`
Expected: PASS.

- [ ] **Step 7: Typecheck**

Run (from `SDRUtils/dashboard`): `npx tsc --noEmit`
Expected: No errors.

- [ ] **Step 8: Commit**

```bash
git add SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/
git commit -m "feat(dashboard): widen tooltip gate for CURVE/FLY/MMS + collapse long MMYY aliases"
```

---

### Task 4: MMS quick-filter chip

**Files:**
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/columns.tsx` (add MMS filter chip to Pkg column)
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/useColumnFilters.helpers.ts` (if needed for custom filter logic)
- Test: Extend existing column filter tests

**Interfaces:**
- Consumes: PrimeReact `DataTableFilterMeta`, the `package_type` column filter field. MMS rows have `package_type` starting with `MATCHED_MATURITY` or `is_matched_maturity_all === true`.
- Produces: A clickable "MMS" chip in the Pkg column header that applies a `contains: MATCHED_MATURITY` filter on `package_type`.

The existing filter system uses PrimeReact's built-in column filter with URL-synced state (`useColumnFilters.ts`). The `package_type` column (line 305) already has `filter` enabled. The simplest high-value approach: add a clickable "MMS" badge/chip in the Pkg column header that, when clicked, applies a `contains` filter for `MATCHED_MATURITY` on the `package_type` field.

- [ ] **Step 1: Identify the Pkg column header** — in `columns.tsx`, the Pkg column header is rendered at lines 308-310:

```typescript
      header={renderHeader(
        'Pkg',
        summaryFor('package_type', config.activeFilters),
      )}
```

- [ ] **Step 2: Add a toggleable MMS chip** — modify the Pkg column's `header` prop to include an MMS quick-filter chip. After `renderHeader('Pkg', ...)`, wrap the header in a fragment that also renders a small chip. Add a new prop to the column config or use the existing `config.activeFilters` + `config.onFilterChange` to toggle the filter.

In `columns.tsx`, replace the Pkg column header (lines 308-310):

```typescript
      header={
        <div className="flex items-center gap-1">
          {renderHeader('Pkg', summaryFor('package_type', config.activeFilters))}
          <button
            type="button"
            className={`ml-0.5 rounded px-1 py-0.5 text-[9px] font-semibold leading-none transition-colors ${
              isMmsFilterActive(config.activeFilters)
                ? 'bg-teal-500/60 text-teal-100 ring-1 ring-teal-400/50'
                : 'bg-slate-700/50 text-slate-400 hover:bg-teal-900/40 hover:text-teal-300'
            }`}
            onClick={(e) => {
              e.stopPropagation()
              config.onToggleMmsFilter?.()
            }}
            title="Toggle MMS filter"
          >
            MMS
          </button>
        </div>
      }
```

- [ ] **Step 3: Add `isMmsFilterActive` helper** — at the top of `columns.tsx` (or in `columns.helpers.ts`):

```typescript
function isMmsFilterActive(filters?: DataTableFilterMeta): boolean {
  const f = filters?.package_type
  if (!f || !('value' in f)) return false
  return typeof f.value === 'string' && f.value.includes('MATCHED_MATURITY')
}
```

- [ ] **Step 4: Add `onToggleMmsFilter` to column config** — add to the `ColumnsConfig` interface:

```typescript
  onToggleMmsFilter?: () => void
```

Wire it in the parent (`UsdSwapsTradeTape.tsx` or wherever `ColumnsConfig` is constructed) by toggling the `package_type` column filter between `{ value: 'MATCHED_MATURITY', matchMode: 'contains' }` and clearing it. The exact wiring depends on how `setFilters` is exposed from `useColumnFilters`.

- [ ] **Step 5: Run tests + typecheck**

Run (from `SDRUtils/dashboard`): `npm test` then `npx tsc --noEmit`
Expected: PASS; no type errors.

- [ ] **Step 6: Commit**

```bash
git add SDRUtils/dashboard/src/features/usd-swaps-tape-v2/
git commit -m "feat(dashboard): MMS quick-filter chip in Pkg column header"
```

---

## Phase 3 — MMS Analytics Tab (TypeScript)

### Task 5: MMS analytics utility

**Files:**
- Create: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/utils/mmsAnalytics.ts`
- Test: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/utils/__tests__/mmsAnalytics.test.ts`

**Interfaces:**
- Consumes: `UsdSwapTapeRow` with `is_matched_maturity_all`, `package_type`, `total_risk`, `total_notional`, `tape_label_ust_alias`, `execution_start`, `legs_json` (each leg: `matched_ust_maturity`, `ust_cusip`, `tape_label_ust_alias`).
- Produces:
  - `isMmsRow(row: UsdSwapTapeRow): boolean`
  - `computeMmsSummary(rows, window): MmsSummary`
  - `computeMmsDailyVolume(rows): MmsDailyBucket[]`
  - `computeMmsMaturityDistribution(rows): MmsMaturitySlice[]`
  - `computeMmsTopCusips(rows): MmsCusipEntry[]`

- [ ] **Step 1: Write the failing tests** — create `utils/__tests__/mmsAnalytics.test.ts`:

```typescript
import type { UsdSwapTapeRow, UsdSwapTapeLeg } from '../../types'
import {
  isMmsRow,
  computeMmsSummary,
  computeMmsDailyVolume,
  computeMmsMaturityDistribution,
  computeMmsTopCusips,
} from '../mmsAnalytics'

function mockRow(overrides: Partial<UsdSwapTapeRow> = {}): UsdSwapTapeRow {
  return {
    package_type: 'OUTRIGHT',
    is_matched_maturity_all: false,
    total_risk: 50000,
    total_notional: 10_000_000,
    execution_start: '2026-07-08T16:00:00Z',
    tape_label_ust_alias: '',
    legs_json: [],
    ...overrides,
  } as UsdSwapTapeRow
}

function mmsRow(overrides: Partial<UsdSwapTapeRow> = {}): UsdSwapTapeRow {
  return mockRow({
    package_type: 'MATCHED_MATURITY_CURVE',
    is_matched_maturity_all: true,
    total_risk: 80000,
    total_notional: 20_000_000,
    tape_label_ust_alias: 'USD-SOFR Spot 0536/0546 CURVE MMS PHYS',
    legs_json: [
      { matched_ust_maturity: true, ust_cusip: '91282CQQ7', tape_label_ust_alias: '0536' } as UsdSwapTapeLeg,
      { matched_ust_maturity: true, ust_cusip: '912810UV8', tape_label_ust_alias: '0546' } as UsdSwapTapeLeg,
    ],
    ...overrides,
  })
}

describe('isMmsRow', () => {
  it('returns true for MATCHED_MATURITY package_type', () => {
    expect(isMmsRow(mmsRow())).toBe(true)
  })
  it('returns true for is_matched_maturity_all', () => {
    expect(isMmsRow(mockRow({ is_matched_maturity_all: true, package_type: 'PKG-3' }))).toBe(true)
  })
  it('returns false for OUTRIGHT', () => {
    expect(isMmsRow(mockRow())).toBe(false)
  })
})

describe('computeMmsSummary', () => {
  it('computes count, share, and DV01', () => {
    const rows = [mmsRow(), mockRow(), mmsRow()]
    const summary = computeMmsSummary(rows)
    expect(summary.mmsCount).toBe(2)
    expect(summary.totalCount).toBe(3)
    expect(summary.mmsDv01).toBe(160000)
    expect(summary.dv01Share).toBeCloseTo(160000 / 210000)
  })
  it('handles empty rows', () => {
    const summary = computeMmsSummary([])
    expect(summary.mmsCount).toBe(0)
  })
})

describe('computeMmsDailyVolume', () => {
  it('buckets by date', () => {
    const rows = [
      mmsRow({ execution_start: '2026-07-08T10:00:00Z' }),
      mmsRow({ execution_start: '2026-07-08T14:00:00Z' }),
      mockRow({ execution_start: '2026-07-08T15:00:00Z' }),
      mmsRow({ execution_start: '2026-07-09T10:00:00Z' }),
    ]
    const daily = computeMmsDailyVolume(rows)
    expect(daily.length).toBe(2)
    const jul8 = daily.find((d) => d.date === '2026-07-08')
    expect(jul8?.mmsCount).toBe(2)
    expect(jul8?.totalCount).toBe(3)
  })
})

describe('computeMmsMaturityDistribution', () => {
  it('parses MMYY from tape_label_ust_alias', () => {
    const rows = [
      mmsRow({ tape_label_ust_alias: 'USD-SOFR Spot 0536/0546 CURVE MMS PHYS' }),
      mmsRow({ tape_label_ust_alias: 'USD-SOFR Spot 0536 MMS PHYS' }),
    ]
    const dist = computeMmsMaturityDistribution(rows)
    const m0536 = dist.find((d) => d.mmyy === '0536')
    expect(m0536?.count).toBe(2)
    const m0546 = dist.find((d) => d.mmyy === '0546')
    expect(m0546?.count).toBe(1)
  })
})

describe('computeMmsTopCusips', () => {
  it('aggregates by ust_cusip from legs_json', () => {
    const rows = [mmsRow(), mmsRow()]
    const top = computeMmsTopCusips(rows)
    const q = top.find((c) => c.cusip === '91282CQQ7')
    expect(q?.count).toBe(2)
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `SDRUtils/dashboard`): `npm test -- mmsAnalytics.test`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `mmsAnalytics.ts`** — create `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/utils/mmsAnalytics.ts`:

```typescript
import type { UsdSwapTapeRow } from '../types'

export type MmsSummary = {
  mmsCount: number
  totalCount: number
  mmsDv01: number
  totalDv01: number
  dv01Share: number
  mmsNotional: number
  totalNotional: number
  notionalShare: number
}

export type MmsDailyBucket = {
  date: string
  mmsCount: number
  totalCount: number
  mmsDv01: number
  totalDv01: number
  share: number
}

export type MmsMaturitySlice = {
  mmyy: string
  count: number
  dv01: number
  notional: number
}

export type MmsCusipEntry = {
  cusip: string
  mmyy: string
  count: number
  dv01: number
  notional: number
}

export function isMmsRow(row: UsdSwapTapeRow): boolean {
  if (row.is_matched_maturity_all === true) return true
  const pt = String(row.package_type ?? '').toUpperCase()
  return pt.startsWith('MATCHED_MATURITY')
}

function absNum(v: unknown): number {
  return Math.abs(Number(v ?? 0)) || 0
}

export function computeMmsSummary(
  rows: readonly UsdSwapTapeRow[],
): MmsSummary {
  let mmsCount = 0, totalCount = rows.length
  let mmsDv01 = 0, totalDv01 = 0
  let mmsNotional = 0, totalNotional = 0
  for (const row of rows) {
    const dv01 = absNum(row.total_risk)
    const notional = absNum(row.total_notional)
    totalDv01 += dv01
    totalNotional += notional
    if (isMmsRow(row)) {
      mmsCount++
      mmsDv01 += dv01
      mmsNotional += notional
    }
  }
  return {
    mmsCount,
    totalCount,
    mmsDv01,
    totalDv01,
    dv01Share: totalDv01 > 0 ? mmsDv01 / totalDv01 : 0,
    mmsNotional,
    totalNotional,
    notionalShare: totalNotional > 0 ? mmsNotional / totalNotional : 0,
  }
}

function dayBucket(ts: string | null | undefined): string {
  if (!ts) return 'UNKNOWN'
  return ts.slice(0, 10)
}

export function computeMmsDailyVolume(
  rows: readonly UsdSwapTapeRow[],
): MmsDailyBucket[] {
  const buckets = new Map<string, { mmsCount: number; totalCount: number; mmsDv01: number; totalDv01: number }>()
  for (const row of rows) {
    const date = dayBucket(row.execution_start)
    const b = buckets.get(date) ?? { mmsCount: 0, totalCount: 0, mmsDv01: 0, totalDv01: 0 }
    const dv01 = absNum(row.total_risk)
    b.totalCount++
    b.totalDv01 += dv01
    if (isMmsRow(row)) {
      b.mmsCount++
      b.mmsDv01 += dv01
    }
    buckets.set(date, b)
  }
  return Array.from(buckets.entries())
    .map(([date, b]) => ({
      date,
      ...b,
      share: b.totalCount > 0 ? b.mmsCount / b.totalCount : 0,
    }))
    .sort((a, b) => a.date.localeCompare(b.date))
}

const MMYY_RE = /\b(\d{4})(?=\/|\s|$)/g

function extractMmyys(label: string | null | undefined): string[] {
  if (!label) return []
  const matches: string[] = []
  let m: RegExpExecArray | null
  MMYY_RE.lastIndex = 0
  while ((m = MMYY_RE.exec(label)) !== null) {
    matches.push(m[1])
  }
  return matches
}

export function computeMmsMaturityDistribution(
  rows: readonly UsdSwapTapeRow[],
): MmsMaturitySlice[] {
  const buckets = new Map<string, { count: number; dv01: number; notional: number }>()
  for (const row of rows) {
    if (!isMmsRow(row)) continue
    const mmyys = extractMmyys(row.tape_label_ust_alias)
    const dv01 = absNum(row.total_risk)
    const notional = absNum(row.total_notional)
    for (const mmyy of mmyys) {
      const b = buckets.get(mmyy) ?? { count: 0, dv01: 0, notional: 0 }
      b.count++
      b.dv01 += dv01
      b.notional += notional
      buckets.set(mmyy, b)
    }
  }
  return Array.from(buckets.entries())
    .map(([mmyy, b]) => ({ mmyy, ...b }))
    .sort((a, b) => b.count - a.count)
}

export function computeMmsTopCusips(
  rows: readonly UsdSwapTapeRow[],
): MmsCusipEntry[] {
  const buckets = new Map<string, { mmyy: string; count: number; dv01: number; notional: number }>()
  for (const row of rows) {
    if (!isMmsRow(row)) continue
    const legs = row.legs_json ?? []
    for (const leg of legs) {
      if (!leg.matched_ust_maturity || !leg.ust_cusip) continue
      const cusip = String(leg.ust_cusip)
      const b = buckets.get(cusip) ?? {
        mmyy: String(leg.tape_label_ust_alias ?? ''),
        count: 0,
        dv01: 0,
        notional: 0,
      }
      b.count++
      b.dv01 += absNum(leg.total_risk ?? (row.total_risk ? Number(row.total_risk) / Math.max(legs.length, 1) : 0))
      b.notional += absNum(leg.notional_amount ?? (row.total_notional ? Number(row.total_notional) / Math.max(legs.length, 1) : 0))
      buckets.set(cusip, b)
    }
  }
  return Array.from(buckets.entries())
    .map(([cusip, b]) => ({ cusip, ...b }))
    .sort((a, b) => b.count - a.count)
    .slice(0, 10)
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run (from `SDRUtils/dashboard`): `npm test -- mmsAnalytics.test`
Expected: PASS.

- [ ] **Step 5: Typecheck**

Run (from `SDRUtils/dashboard`): `npx tsc --noEmit`
Expected: No errors.

- [ ] **Step 6: Commit**

```bash
git add SDRUtils/dashboard/src/features/usd-swaps-tape-v2/utils/mmsAnalytics.ts SDRUtils/dashboard/src/features/usd-swaps-tape-v2/utils/__tests__/mmsAnalytics.test.ts
git commit -m "feat(analytics): MMS analytics utility (summary, daily volume, maturity distrib, top CUSIPs)"
```

---

### Task 6: MMS tab types, state, registration

**Files:**
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/AnalyticsPanel/analytics-types.ts:10`
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/AnalyticsPanel/constants.ts`
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/AnalyticsPanel/AnalyticsPanel.tsx` (tabs array + state + render)

**Interfaces:**
- Consumes: `MmsTab` component (Task 7), `MmsSummary` from `mmsAnalytics.ts` (Task 5).
- Produces: `'mms'` added to `AnalyticsTab` union; `MmsState` type; `MMS_DEFAULT_STATE`; MMS tab appears in the tab strip unconditionally with a badge showing MMS count; tab body renders `MmsTab`.

- [ ] **Step 1: Add `'mms'` to the `AnalyticsTab` union** — in `analytics-types.ts` line 10:

```typescript
export type AnalyticsTab = 'timeseries' | 'rarity' | 'levels' | 'sequence' | 'mms'
```

- [ ] **Step 2: Add `MmsState` type** — append to `analytics-types.ts`:

```typescript
export type MmsWindow = 'today' | '7d' | '30d' | '90d' | 'ytd'
export type MmsVolumeMetric = 'count' | 'dv01'
export type MmsDistributionMetric = 'count' | 'dv01' | 'notional'

export type MmsState = {
  window: MmsWindow
  volumeMetric: MmsVolumeMetric
  distributionMetric: MmsDistributionMetric
}
```

- [ ] **Step 3: Add `MMS_DEFAULT_STATE`** — append to `constants.ts`:

```typescript
import type { MmsState } from './analytics-types'

export const MMS_DEFAULT_STATE: MmsState = {
  window: '30d',
  volumeMetric: 'count',
  distributionMetric: 'count',
}
```

(If `MmsState` import causes a circular issue, co-locate the import with the existing type imports at the top of `constants.ts`.)

- [ ] **Step 4: Add MMS tab to the tabs array in AnalyticsPanel.tsx** — in the `<Tabs>` component (line ~454), add the MMS tab entry before the sequence conditional spread:

```typescript
          tabs={[
            { key: 'timeseries', label: 'Timeseries', icon: '◠' },
            {
              key: 'rarity',
              label: 'Trade Rarity',
              icon: '◉',
              badge: rarity.stats.count > 0 ? `P${Math.round(rarityPrimaryPercentile)}` : '…',
            },
            { key: 'levels', label: 'Traded Levels', icon: '◈', badge: String(extremes.extremes.length) },
            { key: 'mms', label: 'MMS', icon: '⬡', badge: String(mmsSummary.mmsCount) },
            ...(mode === 'sequence' && sequence
              ? ([{ key: 'sequence' as const, label: 'Sequence', icon: '⇉', badge: String(sequence.length) }])
              : []),
          ]}
```

- [ ] **Step 5: Add state + compute in AnalyticsPanel** — in `AnalyticsPanel.tsx`, near the other `useState` declarations (~line 92-94), add:

```typescript
  const [mmsState, setMmsState] = useState<MmsState>(MMS_DEFAULT_STATE)
```

And near the top of the function body (after the `derived` computation ~line 82), compute the MMS summary:

```typescript
  const mmsSummary = useMemo(() => computeMmsSummary(rows), [rows])
```

Add the imports at the top:

```typescript
import type { MmsState } from './analytics-types'
import { MMS_DEFAULT_STATE } from './constants'
import { computeMmsSummary } from '../../utils/mmsAnalytics'
import { MmsTab } from './MmsTab'
```

- [ ] **Step 6: Add MMS tab render** — after the sequence tab render (line ~540), but OUTSIDE the `baseTrade == null` guard (since MMS tab doesn't require a focused trade), add:

```typescript
        {activeTab === 'mms' ? (
          <MmsTab
            rows={rows}
            state={mmsState}
            setState={setMmsState}
          />
        ) : null}
```

Note: this needs to render even when `baseTrade == null`. Move the MMS render OUTSIDE the `{baseTrade == null ? null : (` block (line 474). The MMS tab renders at the same level as the `CardsDrawer` — always available.

- [ ] **Step 7: Create a placeholder MmsTab** — create `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/AnalyticsPanel/MmsTab.tsx` with a minimal placeholder (Task 7 will fill it in):

```typescript
'use client'
import type { Dispatch, SetStateAction } from 'react'
import type { UsdSwapTapeRow } from '../../types'
import type { MmsState } from './analytics-types'

export interface MmsTabProps {
  rows: readonly UsdSwapTapeRow[]
  state: MmsState
  setState: Dispatch<SetStateAction<MmsState>>
}

export function MmsTab({ rows }: MmsTabProps): JSX.Element {
  return (
    <div className="p-3 text-sm text-slate-400">
      MMS tab — {rows.length} rows loaded
    </div>
  )
}
```

- [ ] **Step 8: Typecheck + test**

Run (from `SDRUtils/dashboard`): `npx tsc --noEmit` then `npm test`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/AnalyticsPanel/
git commit -m "feat(analytics): register MMS tab type + state + placeholder in AnalyticsPanel"
```

---

### Task 7: MMS tab component (4 panels)

**Files:**
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/AnalyticsPanel/MmsTab.tsx` (replace placeholder)
- Test: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/AnalyticsPanel/__tests__/MmsTab.test.tsx`

**Interfaces:**
- Consumes: `MmsTabProps` (Task 6), all utilities from `mmsAnalytics.ts` (Task 5), `filterRowsToWindow` from `utils/underlierMix.ts`, formatters from `analytics-format.ts`.
- Produces: Full MMS tab with 4 panels: summary strip, daily volume chart, maturity distribution, top CUSIPs table.

- [ ] **Step 1: Write the failing test** — create `__tests__/MmsTab.test.tsx`:

```typescript
import { render, screen } from '@testing-library/react'
import { MmsTab } from '../MmsTab'
import type { UsdSwapTapeRow } from '../../../types'
import { MMS_DEFAULT_STATE } from '../constants'

function mmsRow(date: string): UsdSwapTapeRow {
  return {
    package_type: 'MATCHED_MATURITY_CURVE',
    is_matched_maturity_all: true,
    total_risk: 80000,
    total_notional: 20_000_000,
    execution_start: `${date}T16:00:00Z`,
    tape_label_ust_alias: 'USD-SOFR Spot 0536/0546 CURVE MMS PHYS',
    legs_json: [
      { matched_ust_maturity: true, ust_cusip: '91282CQQ7', tape_label_ust_alias: '0536' },
      { matched_ust_maturity: true, ust_cusip: '912810UV8', tape_label_ust_alias: '0546' },
    ],
  } as UsdSwapTapeRow
}

describe('MmsTab', () => {
  it('renders summary stats', () => {
    render(
      <MmsTab
        rows={[mmsRow('2026-07-08'), mmsRow('2026-07-09')]}
        state={MMS_DEFAULT_STATE}
        setState={() => {}}
      />,
    )
    expect(screen.getByText(/MMS Packages/i)).toBeInTheDocument()
    expect(screen.getByText('2')).toBeInTheDocument()
  })

  it('renders empty state when no rows', () => {
    render(
      <MmsTab rows={[]} state={MMS_DEFAULT_STATE} setState={() => {}} />,
    )
    expect(screen.getByText(/no mms/i)).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `SDRUtils/dashboard`): `npm test -- MmsTab.test`
Expected: FAIL — placeholder doesn't render "MMS Packages".

- [ ] **Step 3: Implement the full MmsTab** — replace the placeholder in `MmsTab.tsx`. This is the largest single file. Build it panel by panel:

**Panel 1 — Summary strip:** A row of stat boxes showing MMS Packages, % of Total, MMS DV01, DV01 Share, MMS Notional. Use `computeMmsSummary` + `filterRowsToWindow`. Include a window segmented control (today/7d/30d/90d/YTD).

**Panel 2 — Daily volume chart:** Recharts `BarChart` + `Line`. X-axis = date, bars = MMS count (or DV01 per `state.volumeMetric`), line = MMS share %. Use `computeMmsDailyVolume`. Include a metric toggle (count/DV01).

**Panel 3 — Maturity distribution:** Recharts horizontal `BarChart`. Bars = MMYY aliases sorted by frequency. Metric switchable (count/DV01/notional) per `state.distributionMetric`. Use `computeMmsMaturityDistribution`.

**Panel 4 — Top CUSIPs table:** Simple table with columns CUSIP, MMYY, Count, DV01, Notional. Use `computeMmsTopCusips`. Top 10, sorted by count.

The full component is ~200-300 lines. Follow the styling patterns from `TradeRarityTab.tsx` (stat cards) and `SwapSpreadVwapCard.tsx` (Recharts bars). Use the formatters from `analytics-format.ts` (`fmtDv01Compact`, `fmtNotionalMM`).

Empty state: when `mmsSummary.mmsCount === 0`, show "No MMS packages in loaded data."

- [ ] **Step 4: Run tests to verify they pass**

Run (from `SDRUtils/dashboard`): `npm test -- MmsTab.test`
Expected: PASS.

- [ ] **Step 5: Typecheck + full test suite**

Run (from `SDRUtils/dashboard`): `npx tsc --noEmit` then `npm test`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/AnalyticsPanel/MmsTab.tsx SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/AnalyticsPanel/__tests__/MmsTab.test.tsx
git commit -m "feat(analytics): MMS tab — summary strip, daily volume, maturity distribution, top CUSIPs"
```

---

## Phase 4 — Detection Research (Python)

### Task 8: Detection-depth research script + doc

**Files:**
- Create: `scripts/mms_detection_research.py`
- Create: `docs/superpowers/research/2026-07-09-mms-detection-depth.md`

**Interfaces:**
- Consumes: Cached classification parquets in `sdr_cache/classification_cache/usd_swaps/ERIS_EOD_LIVE-RL_BASIC/curve1_fly1_mms1_invoice1_mac1_spreadover1_basis1_ptp3-mms-pkg/`. UST reference data via `SDRUtils.packages.mms._load_ust_reference_data()`.
- Produces: A research document with empirical counts and policy recommendations for IMM-start, near-clean, and T-bill detection gaps.

- [ ] **Step 1: Write the research script** — create `scripts/mms_detection_research.py`:

```python
"""MMS detection-depth research — empirical analysis of three gate relaxation scenarios.

Reads the 43-day classified cache (no network, no DB). Outputs a Markdown report
to docs/superpowers/research/2026-07-09-mms-detection-depth.md.

Run: conda run -n stir python scripts/mms_detection_research.py
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

CACHE_DIR = Path(
    os.getenv(
        "MMS_CACHE_DIR",
        "sdr_cache/classification_cache/usd_swaps/ERIS_EOD_LIVE-RL_BASIC/"
        "curve1_fly1_mms1_invoice1_mac1_spreadover1_basis1_ptp3-mms-pkg",
    )
)
OUTPUT = Path("docs/superpowers/research/2026-07-09-mms-detection-depth.md")


def load_corpus() -> pd.DataFrame:
    """Load all per-date classified parquets into one frame."""
    files = sorted(CACHE_DIR.rglob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"No parquets in {CACHE_DIR}")
    frames = [pd.read_parquet(f) for f in files]
    print(f"Loaded {len(frames)} day-files, {sum(len(f) for f in frames)} total rows")
    return pd.concat(frames, ignore_index=True)


def research_imm_start(df: pd.DataFrame) -> str:
    """4a: How many trades does the IMM gate currently exclude?"""
    # Trades with forward_label starting with IMM_ that matched a UST
    has_ust = df["ust_cusip"].notna() & (df["ust_cusip"] != "")
    is_imm = df.get("forward_label", pd.Series(dtype=str)).fillna("").str.startswith("IMM_")
    # Also check the both_imm secondary gate
    imm_excluded = is_imm & has_ust
    n_excluded = imm_excluded.sum()

    # Break down by on-the-run vs off-the-run (heuristic: on-the-run if
    # original_security_term matches a standard benchmark)
    lines = [
        "## 4a. IMM-Start MMS False-Positive Analysis",
        "",
        f"**IMM-labeled trades with a UST maturity match:** {n_excluded}",
        "",
    ]
    if n_excluded > 0:
        sample = df.loc[imm_excluded].head(10)[
            ["trade_id", "forward_label", "tenor_years", "ust_cusip", "expiration_date"]
        ]
        lines.append("**Sample (first 10):**")
        lines.append("")
        lines.append(sample.to_markdown(index=False))
        lines.append("")
    lines.append(
        "**Recommendation:** [Fill based on data — if n_excluded is small and "
        "all are standard IMM rolls, keep the gate. If some are off-the-run "
        "broken-tenor, consider a relaxed guard.]"
    )
    return "\n".join(lines)


def research_near_clean(df: pd.DataFrame) -> str:
    """4b: How many packages go partial→all-MMS with near-clean inclusion?"""
    from SDRUtils.packages.mms import _STANDARD_TENORS

    if "package_id" not in df.columns or "matched_ust_maturity" not in df.columns:
        return "## 4b. Near-Clean Broken-Tenor\n\nInsufficient columns in cache.\n"

    # Find packaged legs that were wiped by is_clean_tenor but had a UST match
    has_ust = df["ust_cusip"].notna() & (df["ust_cusip"] != "")
    mms_flag = df["matched_ust_maturity"].fillna(False).astype(bool)
    in_package = df["package_id"].notna() & (df["package_type"] != "OUTRIGHT")

    # Near-clean: within 0.1y of a standard tenor
    tenor = pd.to_numeric(df.get("tenor_years"), errors="coerce")
    is_near_clean = pd.Series(False, index=df.index)
    for t in _STANDARD_TENORS:
        is_near_clean |= (tenor - t).abs() < 0.1

    # These are the legs that WOULD match but were excluded
    excluded_near_clean = in_package & has_ust & ~mms_flag & is_near_clean
    n_excluded = excluded_near_clean.sum()

    # For each, check if including them would flip a partial package to all-MMS
    promotions = 0
    if n_excluded > 0:
        for pkg_id, grp in df.loc[in_package].groupby("package_id"):
            if len(grp) < 2:
                continue
            current_all = grp["matched_ust_maturity"].fillna(False).astype(bool).all()
            if current_all:
                continue
            # Would be all-MMS if near-clean legs were included
            would_match = grp["matched_ust_maturity"].fillna(False).astype(bool) | (
                grp.index.isin(excluded_near_clean[excluded_near_clean].index)
                & grp["ust_cusip"].notna()
            )
            if would_match.all():
                promotions += 1

    lines = [
        "## 4b. Near-Clean Broken-Tenor Quantification",
        "",
        f"**Packaged legs excluded by clean-tenor gate but with UST match:** {n_excluded}",
        f"**Packages that would flip partial→all-MMS:** {promotions}",
        "",
    ]
    if n_excluded > 0:
        sample = df.loc[excluded_near_clean].head(10)[
            ["trade_id", "package_id", "package_type", "tenor_years", "ust_cusip", "expiration_date"]
        ]
        lines.append("**Sample (first 10):**")
        lines.append("")
        lines.append(sample.to_markdown(index=False))
        lines.append("")
    lines.append(
        "**Recommendation:** [Fill based on data — if promotions is small, "
        "keep the gate strict. If substantial, consider context-aware relaxation "
        "with a dedicated false-positive guard.]"
    )
    return "\n".join(lines)


def research_tbill(df: pd.DataFrame) -> str:
    """4c: Among short-dated matches, how many are T-bills vs coupon notes?"""
    from SDRUtils.packages.mms import _load_ust_reference_data

    mms_flag = df["matched_ust_maturity"].fillna(False).astype(bool)
    tenor = pd.to_numeric(df.get("tenor_years"), errors="coerce")
    short = mms_flag & (tenor < 1.0)
    n_short = short.sum()

    lines = [
        "## 4c. T-Bill vs Short-Note Data Study",
        "",
        f"**Short-dated (<1Y) MMS matches:** {n_short}",
        "",
    ]

    if n_short > 0:
        ust_ref = _load_ust_reference_data()
        short_cusips = df.loc[short, "ust_cusip"].dropna().unique()
        if len(short_cusips) > 0 and "cusip" in ust_ref.columns:
            matched = ust_ref[ust_ref["cusip"].isin(short_cusips)]
            if "security_type" in matched.columns:
                type_counts = matched.groupby("security_type").size()
                lines.append("**Matched UST security types:**")
                lines.append("")
                lines.append(type_counts.to_markdown())
                lines.append("")
            cusip_prefix = pd.Series(short_cusips)
            n_bills = cusip_prefix.str.startswith("912797").sum()
            n_notes = len(cusip_prefix) - n_bills
            lines.append(f"**By CUSIP prefix:** 912797* (bills): {n_bills}, other (notes/bonds): {n_notes}")
            lines.append("")
    else:
        lines.append("No short-dated MMS matches found.")
        lines.append("")

    lines.append(
        "**Recommendation:** [Fill based on data — if all short-dated matches "
        "are T-bills, add an exclusion gate. If some are short-dated notes, "
        "keep the low-confidence tag.]"
    )
    return "\n".join(lines)


def main():
    df = load_corpus()
    sections = [
        "# MMS Detection Depth — Empirical Research",
        "",
        f"**Date:** 2026-07-09",
        f"**Corpus:** {len(df)} rows across {df['execution_date'].nunique() if 'execution_date' in df.columns else '?'} days",
        f"**Cache version:** ptp3-mms-pkg",
        "",
        "This document reports empirical data for three detection-depth gaps. "
        "No detection code was changed; these are read-only analyses.",
        "",
        research_imm_start(df),
        "",
        research_near_clean(df),
        "",
        research_tbill(df),
    ]
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(sections), encoding="utf-8")
    print(f"Research doc written to {OUTPUT}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the script**

Run: `conda run -n stir python scripts/mms_detection_research.py`
Expected: produces `docs/superpowers/research/2026-07-09-mms-detection-depth.md` with empirical data.

- [ ] **Step 3: Review the output** — read the generated doc, fill in the `[Fill based on data]` recommendation placeholders with actual conclusions based on the numbers. Edit the doc manually to replace each placeholder.

- [ ] **Step 4: Commit**

```bash
git add scripts/mms_detection_research.py docs/superpowers/research/2026-07-09-mms-detection-depth.md
git commit -m "research(mms): detection-depth analysis — IMM-start, near-clean, T-bill empirical data"
```

---

## Phase 5 — Verification & Cleanup

### Task 9: Full verification + cleanup

**Files:** None (operational).

- [ ] **Step 1: Python fast gate**

Run: `conda run -n stir python -m pytest tests -m "not slow and not network and not db" -q`
Expected: PASS.

- [ ] **Step 2: Dashboard test + build**

Run (from `SDRUtils/dashboard`): `npm test` then `npm run build`
Expected: PASS; build succeeds.

- [ ] **Step 3: Chrome-MCP E2E at localhost**

Start `npm run dev` in `SDRUtils/dashboard`. Via chrome-MCP:
1. Verify MMS filter chip in Pkg column header → clicking it shows only MMS packages
2. Hover an MMS Curve row → tooltip shows per-leg MMYY alias
3. A big-PKG-N MMS row shows collapsed alias (if one exists in loaded data)
4. Open Analytics dock → MMS tab → verify summary stats, daily volume chart, maturity distribution, top CUSIPs all render
5. No console errors, existing tabs still work
6. Capture screenshot

- [ ] **Step 4: Worktree + branch cleanup**

```bash
git worktree remove "C:\Users\chris\clee\ARBS-mms" 2>/dev/null || true
git branch -d feat/mms-package-detection
git push origin --delete feat/mms-package-detection
```

- [ ] **Step 5: Pipeline restart** (manual — done by the user)

Restart service: `conda run -n stir python SDRUtils/_swappulse_scripts/run_usdswaps_pipeline.py service`
Then verify:
- `packaged_day_ptp3-mms-pkg.pkl` appears in `sdr_cache/service_caches/`
- Today's MMS packages appear in the prod DB

- [ ] **Step 6: Update TAPE_OVERRIDE_PASSWORD** (manual — done by the user)

In `SDRUtils/dashboard/.env.local`, change `TAPE_OVERRIDE_PASSWORD=admin` to a strong secret.

---

## Self-review

**Spec coverage:**
- §1a pipeline restart → Task 9 Step 5
- §1b lock_timeout CLI → Task 1
- §1c migrate subcommand → Task 2
- §1d TAPE_OVERRIDE_PASSWORD → Task 9 Step 6 (ops only; code already secure)
- §1e worktree cleanup → Task 9 Step 4
- §2a tooltip gate → Task 3 Step 5
- §2b MMS filter → Task 4
- §2c alias collapse → Task 3 Steps 3-4
- §3 MMS analytics tab → Tasks 5-7
- §4 detection research → Task 8
- §5 verification → Task 9

**Placeholder scan:** The research script (Task 8) has `[Fill based on data]` markers — these are intentionally left for the human/agent to fill after running the script and seeing the actual numbers. They are not implementation placeholders.

**Type consistency:** `MmsState` defined in `analytics-types.ts` (Task 6 Step 2), imported in `constants.ts` (Task 6 Step 3) and `AnalyticsPanel.tsx` (Task 6 Step 5). `MmsTabProps` defined in `MmsTab.tsx` (Task 6 Step 7), consumed in `AnalyticsPanel.tsx` (Task 6 Step 6). `isMmsRow`, `computeMmsSummary`, etc. defined in `mmsAnalytics.ts` (Task 5), imported in `AnalyticsPanel.tsx` (Task 6 Step 5) and `MmsTab.tsx` (Task 7). `collapseAlias` defined and consumed within `TapeLabelCell.helpers.ts` (Task 3). `ensure_schema(engine, lock_timeout_ms=...)` signature consistent between Task 1 Step 3 and Task 2 Step 1.
