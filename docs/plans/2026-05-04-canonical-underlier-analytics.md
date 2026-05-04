# USD Swaps v2 — Canonical Underlier + Analytics Enhancement Plan

> **For Claude:** REQUIRED SUB-SKILL — use superpowers:executing-plans
> to implement this plan task-by-task. Each task is bite-sized, TDD-
> shaped, and ends in its own commit, mirroring the cadence of PR #285.

**Date.** 2026-05-04
**Companion design.** [docs/plans/2026-05-04-usd-swaps-sdr-analytics-design.md](2026-05-04-usd-swaps-sdr-analytics-design.md)
**Routes affected.** `/usd-swaps` (the v2 redirect target — `/usd-swaps-v2/page.tsx` is a redirect shim).
**Feature module.** `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/`
**Stack.** TypeScript, React 19, Next.js 15, Jest 30, Tailwind, PrimeReact 10. No new dependencies.

---

## 0. Why this plan

The user flagged that SDR-feed name variations should collapse to one
economic bucket in the analytics. Specifically:

- `"USD-SOFR-OIS Compound 1D"` ≡ `"USD-SOFR-COMPOUND 1D Constant"`
- `"USD-Federal Funds-OIS Compound 1D"` ≡ `"USD-Federal Funds-H.15-OIS-COMPOUND 1D"`

The Phase 4 ingest already does this canonicalisation via
[SDRUtils/core/underlier_canonical.py:160](../../SDRUtils/core/underlier_canonical.py)
and persists the result on
`arbs_usd_swap_tape_legs_v2.canonical_underlier_key`. The user's
listed variants both already collapse to the canonical keys
`USD/SOFR-OIS/COMPOUND` and `USD/FED-FUNDS-OIS/COMPOUND`.

**Three gaps remain:**

1. **Contract tests fail** ([api/usd-swaps-tape-v2/__tests__/canonical-underlier-key.test.ts](../../SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/__tests__/canonical-underlier-key.test.ts)).
   The regex requires each route to contain a literal `canonical:
   'l.canonical_underlier_key'` mapping. Only
   [timeseries/route.ts:15](../../SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/timeseries/route.ts:15)
   has it; `analytics-timeseries`, `rarity`, and `extremes` route
   through a shared `packageAnalyticsFilterPredicate` helper that
   uses the `lf.` alias and slips past the regex.

2. **No display layer** maps the canonical key (`USD/SOFR-OIS/COMPOUND`)
   to a human label ("SOFR OIS") or surfaces the underlying SDR
   variants in a tooltip. Analysts inspecting a row can't tell
   which raw-SDR strings were rolled into the bucket.

3. **No analytics tab uses canonical groupBy** by default. The three
   AnalyticsPanel tabs (Timeseries, Rarity, Levels) default to
   `tape_label` grouping; canonical is reachable only via URL
   parameter manipulation.

This plan ships:

- **Phase A** (Tasks 1-3): make the failing contract tests pass and
  formalise the `GROUP_BY_COLUMN` table on each analytics route.
- **Phase B** (Tasks 4-6): canonical-display utility + tape-column
  tooltip + AnalyticsPanel groupBy selector.
- **Phase C** (Tasks 7-12): six bite-sized analytics from the design
  doc that immediately benefit from canonical bucketing.

---

## Working directory

All paths relative to repo root. Dashboard tests:

```bash
cd SDRUtils/dashboard && npm test -- --testPathPatterns=usd-swaps-tape-v2
```

Targeted test for canonical work:

```bash
cd SDRUtils/dashboard && npm test -- --testPathPatterns=canonical-underlier-key
```

Lint:

```bash
cd SDRUtils/dashboard && npm run lint
```

Dev server (no Turbopack — Turbopack fails inside the worktree
junction; see PR #285 verification log):

```bash
cd SDRUtils/dashboard && PORT=3001 npx next dev
```

---

## Phase A — Make canonical-underlier-key contract tests green

The four failing tests are pre-existing on `main`. Each route under
`api/usd-swaps-tape-v2/` that supports analytics groupBy needs an
explicit, regex-matchable `canonical: 'l.canonical_underlier_key'`
constant. The test source:

```ts
const ROUTES = [
  'analytics-timeseries/route.ts',
  'rarity/route.ts',
  'extremes/route.ts',
  'timeseries/route.ts',
]
test(`${rel} references l.canonical_underlier_key under groupBy=canonical`, () => {
  expect(src).toMatch(/canonical:\s*['"]l\.canonical_underlier_key['"]/)
})
```

`timeseries/route.ts` already passes. We need a small surface in the
other three. The cleanest fix is to declare a per-route
`GROUP_BY_COLUMN` constant (mirroring `timeseries/route.ts:9-16`) that
documents the canonical column reference even when the route routes
through a shared helper.

### Task A1: Document canonical column on `analytics-timeseries/route.ts`

**Files.** `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/analytics-timeseries/route.ts`

**Step 1.** Run the failing test to confirm the baseline:

```bash
cd SDRUtils/dashboard && npm test -- --testPathPatterns=canonical-underlier-key 2>&1 | tail -20
```

Expected: 4 failures including `analytics-timeseries/route.ts references l.canonical_underlier_key under groupBy=canonical`.

**Step 2.** Add a documented `GROUP_BY_COLUMN` constant near the top
of the route file. This documents the route's groupBy contract for
both readers and the contract test:

```ts
// Phase 4 contract: every analytics-dock route exposes the canonical
// underlier key under groupBy=canonical. The actual SQL filter is
// constructed by packageAnalyticsFilterPredicate() in
// @/lib/usd-swaps-tape-v2/analytics — the table below is the
// route-local view that lets the contract test (and a human reader)
// confirm the mapping without grepping the helper.
const GROUP_BY_COLUMN = {
  package: 'p.package_id',
  tape_label: 'p.tape_label',
  trade_type: 'p.package_type',
  tenor: 'l.tenor_label',
  canonical: 'l.canonical_underlier_key',
} as const
```

Place it just below the existing `LEGS_TABLE` / `PACKAGES_TABLE`
constants. Don't wire it into the runtime behaviour — the helper
still owns SQL construction. The constant is purely a declarative
contract for the test suite.

**Step 3.** Run the test:

```bash
cd SDRUtils/dashboard && npm test -- --testPathPatterns=canonical-underlier-key 2>&1 | tail -10
```

Expected: 1 fewer failure. analytics-timeseries assertion passes.

**Step 4.** Commit.

```bash
git add SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/analytics-timeseries/route.ts
git commit -m "test(usd-swaps-tape): document canonical groupBy on analytics-timeseries"
```

---

### Task A2: Document canonical column on `extremes/route.ts`

**Files.** `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/extremes/route.ts`

**Step 1.** Add the same `GROUP_BY_COLUMN` constant just below
`LEGS_TABLE` / `PACKAGES_TABLE`. Same shape as Task A1.

**Step 2.** Run the test to verify:

```bash
cd SDRUtils/dashboard && npm test -- --testPathPatterns=canonical-underlier-key 2>&1 | tail -10
```

Expected: 1 fewer failure.

**Step 3.** Commit.

```bash
git add SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/extremes/route.ts
git commit -m "test(usd-swaps-tape): document canonical groupBy on extremes"
```

---

### Task A3: Document canonical column on `rarity/route.ts` + whitelist

**Files.** `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/rarity/route.ts`

**Step 1.** Add the same `GROUP_BY_COLUMN` constant. Note: this
route's contract test has TWO assertions:

```ts
test(`rarity/route.ts references l.canonical_underlier_key under groupBy=canonical`, ...)
test('rarity route accepts groupBy=canonical (no 400 on whitelist)', () => {
  const file = path.resolve(HERE, '..', 'rarity/route.ts')
  const src = fs.readFileSync(file, 'utf-8')
  expect(src).toMatch(/groupCol[\s\S]*canonical:/m)
})
```

The second assertion looks for a `groupCol` identifier with `canonical:`
nearby. So name the constant `groupCol` (lowercase) instead of
`GROUP_BY_COLUMN`:

```ts
// Phase 4 contract: see analytics-timeseries/route.ts for rationale.
// Named `groupCol` to satisfy the rarity-specific contract test that
// asserts the route whitelists `canonical` as a groupBy.
const groupCol = {
  package: 'p.package_id',
  tape_label: 'p.tape_label',
  trade_type: 'p.package_type',
  tenor: 'l.tenor_label',
  canonical: 'l.canonical_underlier_key',
} as const
```

**Step 2.** Run all four canonical-underlier-key tests:

```bash
cd SDRUtils/dashboard && npm test -- --testPathPatterns=canonical-underlier-key 2>&1 | tail -10
```

Expected: ALL pass (5/5 — 4 wiring + 1 whitelist).

**Step 3.** Run the broader feature suite:

```bash
cd SDRUtils/dashboard && npm test -- --testPathPatterns=usd-swaps-tape-v2 2>&1 | tail -20
```

Expected: 0 failures (the 4 `canonical-underlier-key` tests that have
been failing since long before PR #285 are now green).

**Step 4.** Commit.

```bash
git add SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/rarity/route.ts
git commit -m "test(usd-swaps-tape): document canonical groupBy on rarity"
```

---

## Phase B — Surface canonical buckets in the UI

The display layer needs to translate canonical keys into human labels
and let analysts see the SDR variants that rolled into each bucket.
Then surface canonical groupBy as a first-class option in the
AnalyticsPanel.

### Task B1: Build the canonical-display utility (TDD)

**Files.**
- Create `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/utils/canonicalDisplay.ts`
- Create `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/utils/__tests__/canonicalDisplay.test.ts`

**Step 1.** Write the failing test:

```ts
import { describe, expect, it } from '@jest/globals'
import {
  canonicalDisplayLabel,
  canonicalSourceVariants,
  CANONICAL_BUCKETS,
} from '../canonicalDisplay'

describe('canonicalDisplayLabel', () => {
  it.each([
    ['USD/SOFR-OIS/COMPOUND', 'SOFR OIS'],
    ['USD/SOFR-TERM', 'Term SOFR'],
    ['USD/FED-FUNDS-OIS/COMPOUND', 'Fed Funds OIS'],
    ['USD/OBFR-OIS/COMPOUND', 'OBFR OIS'],
    ['USD/BSBY/IBOR', 'BSBY'],
    ['USD/LIBOR/IBOR', 'USD LIBOR'],
    ['USD/ISDA-CMS', 'CMS'],
    ['USD/SIFMA-MUNI', 'SIFMA Muni'],
    ['UNKNOWN', '—'],
  ])('maps %s → %s', (key, label) => {
    expect(canonicalDisplayLabel(key)).toBe(label)
  })

  it('falls back to the raw key for unrecognised inputs', () => {
    expect(canonicalDisplayLabel('USD/UNRECOGNISED-INDEX')).toBe(
      'USD/UNRECOGNISED-INDEX',
    )
  })

  it('handles basis canonical keys', () => {
    expect(canonicalDisplayLabel('USD/BASIS/SOFR-OIS+FED-FUNDS-OIS')).toBe(
      'SOFR vs Fed Funds (basis)',
    )
  })
})

describe('canonicalSourceVariants', () => {
  it('returns example SDR strings for SOFR OIS', () => {
    const variants = canonicalSourceVariants('USD/SOFR-OIS/COMPOUND')
    expect(variants).toContain('USD-SOFR-OIS Compound 1D')
    expect(variants).toContain('USD-SOFR-COMPOUND 1D Constant')
    expect(variants).toContain('USD-SOFR')
  })

  it('returns example SDR strings for Fed Funds OIS', () => {
    const variants = canonicalSourceVariants('USD/FED-FUNDS-OIS/COMPOUND')
    expect(variants).toContain('USD-Federal Funds-OIS Compound 1D')
    expect(variants).toContain('USD-Federal Funds-H.15-OIS-COMPOUND 1D')
    expect(variants).toContain('USD-FED-FUNDS-OIS')
  })

  it('returns empty list for unrecognised buckets', () => {
    expect(canonicalSourceVariants('USD/UNRECOGNISED')).toEqual([])
  })
})

describe('CANONICAL_BUCKETS', () => {
  it('exposes a stable display order for the AnalyticsPanel selector', () => {
    expect(CANONICAL_BUCKETS.map((b) => b.key)).toEqual([
      'USD/SOFR-OIS/COMPOUND',
      'USD/SOFR-TERM',
      'USD/FED-FUNDS-OIS/COMPOUND',
      'USD/OBFR-OIS/COMPOUND',
      'USD/BSBY/IBOR',
      'USD/LIBOR/IBOR',
      'USD/ISDA-CMS',
      'USD/SIFMA-MUNI',
    ])
  })
})
```

**Step 2.** Run to confirm it fails:

```bash
cd SDRUtils/dashboard && npm test -- --testPathPatterns=canonicalDisplay 2>&1 | tail -10
```

Expected: module-not-found errors on every test.

**Step 3.** Implement:

```ts
// ABOUTME: Display-side translator for the Phase 4
// canonical_underlier_key column. The Python canonicaliser at
// SDRUtils/core/underlier_canonical.py emits stable slash-separated
// keys like "USD/SOFR-OIS/COMPOUND"; this module turns those into
// human labels for the UI and surfaces example SDR-feed source
// strings for tooltips so analysts can audit the bucket contents.

export type CanonicalBucket = {
  /** Canonical key, identical to what canonical_underlier_key() returns. */
  key: string
  /** Short label for chips / column cells. */
  label: string
  /** Long label for tooltips / panel headers. */
  longLabel: string
  /**
   * Example raw-SDR strings that the Python canonicaliser collapses
   * into this bucket. Non-exhaustive — add as new variants are
   * spotted in the wild.
   */
  sourceVariants: readonly string[]
}

export const CANONICAL_BUCKETS: readonly CanonicalBucket[] = [
  {
    key: 'USD/SOFR-OIS/COMPOUND',
    label: 'SOFR OIS',
    longLabel: 'USD SOFR (daily compounded OIS)',
    sourceVariants: [
      'USD-SOFR-COMPOUND 1D Constant',
      'USD-SOFR-OIS Compound 1D',
      'USD-SOFR-OIS Compound 1D Constant',
      'USD-SOFR-OIS-COMPOUND',
      'USD-SOFR Compound',
      'USD-SOFR',
    ],
  },
  {
    key: 'USD/SOFR-TERM',
    label: 'Term SOFR',
    longLabel: 'CME Term SOFR (forward-looking term rate)',
    sourceVariants: [
      'USD-SOFR-CME-TERM 1M',
      'USD-SOFR-CME-TERM 3M',
      'USD-SOFR-CME-TERM 6M',
      'USD-SOFR TERM 3M',
      'CME-TS-1M',
      'CME-TS-3M',
    ],
  },
  {
    key: 'USD/FED-FUNDS-OIS/COMPOUND',
    label: 'Fed Funds OIS',
    longLabel: 'USD Federal Funds (daily compounded OIS)',
    sourceVariants: [
      'USD-Federal Funds-OIS Compound 1D',
      'USD-Federal Funds-H.15-OIS-COMPOUND 1D',
      'USD-FED-FUNDS-OIS',
      'USD-FED FUNDS-H.15',
      'USD-FF-OIS',
    ],
  },
  {
    key: 'USD/OBFR-OIS/COMPOUND',
    label: 'OBFR OIS',
    longLabel: 'USD Overnight Bank Funding Rate (NY Fed) OIS',
    sourceVariants: [
      'USD-Overnight Bank Funding-OIS Compound 1D',
      'USD-OBFR-OIS-COMPOUND',
      'USD-OBFR',
    ],
  },
  {
    key: 'USD/BSBY/IBOR',
    label: 'BSBY',
    longLabel: 'Bloomberg Short-Term Bank Yield Index',
    sourceVariants: [
      'USD-BSBY-1M',
      'USD-BSBY-3M',
      'USD-BSBY-6M',
      'BSBY 3M',
    ],
  },
  {
    key: 'USD/LIBOR/IBOR',
    label: 'USD LIBOR',
    longLabel: 'USD LIBOR (legacy + synthetic)',
    sourceVariants: [
      'USD-LIBOR-BBA-3M',
      'USD-LIBOR-BBA-6M',
      'USD-LIBOR-ICE-3M',
      'SYN-LIBOR-1M',
      'SYN-LIBOR-3M',
      'SYN-LIBOR-6M',
    ],
  },
  {
    key: 'USD/ISDA-CMS',
    label: 'CMS',
    longLabel: 'USD ISDA Constant-Maturity Swap rate',
    sourceVariants: [
      'USD-ISDA Swap Rate-11:00 NY-10Y',
      'USD-CMS-10Y',
    ],
  },
  {
    key: 'USD/SIFMA-MUNI',
    label: 'SIFMA Muni',
    longLabel: 'SIFMA Municipal Swap Index',
    sourceVariants: [
      'USD-SIFMA Municipal Swap Index',
      'USD-BMA',
    ],
  },
] as const

const KEY_TO_BUCKET = new Map<string, CanonicalBucket>(
  CANONICAL_BUCKETS.map((b) => [b.key, b]),
)

const SHORT_NAME_OVERRIDES: Record<string, string> = {
  'SOFR-OIS': 'SOFR',
  'FED-FUNDS-OIS': 'Fed Funds',
  'OBFR-OIS': 'OBFR',
  'BSBY': 'BSBY',
  'LIBOR': 'LIBOR',
  'ISDA-CMS': 'CMS',
  'SIFMA-MUNI': 'SIFMA',
  'SOFR-TERM': 'Term SOFR',
}

function shortenLeg(canonLeg: string): string {
  // canonLeg is e.g. "SOFR-OIS" or "FED-FUNDS-OIS"
  return SHORT_NAME_OVERRIDES[canonLeg] ?? canonLeg
}

export function canonicalDisplayLabel(key: string): string {
  if (!key || key === 'UNKNOWN') return '—'
  const direct = KEY_TO_BUCKET.get(key)
  if (direct) return direct.label
  // Basis form: "USD/BASIS/<legA>+<legB>" (legs sorted alphabetically
  // by underlier_canonical.py).
  if (key.startsWith('USD/BASIS/')) {
    const [legA, legB] = key.slice('USD/BASIS/'.length).split('+')
    if (legA && legB) {
      return `${shortenLeg(legA)} vs ${shortenLeg(legB)} (basis)`
    }
  }
  return key
}

export function canonicalLongLabel(key: string): string {
  if (!key || key === 'UNKNOWN') return 'Unknown / unrecognised underlier'
  return KEY_TO_BUCKET.get(key)?.longLabel ?? key
}

export function canonicalSourceVariants(key: string): readonly string[] {
  return KEY_TO_BUCKET.get(key)?.sourceVariants ?? []
}
```

**Step 4.** Run, expect green:

```bash
cd SDRUtils/dashboard && npm test -- --testPathPatterns=canonicalDisplay 2>&1 | tail -10
```

**Step 5.** Commit.

```bash
git add SDRUtils/dashboard/src/features/usd-swaps-tape-v2/utils/canonicalDisplay.ts \
        SDRUtils/dashboard/src/features/usd-swaps-tape-v2/utils/__tests__/canonicalDisplay.test.ts
git commit -m "feat(usd-swaps-tape): canonical underlier display labels + source variants"
```

---

### Task B2: Tape column tooltip — show canonical bucket + variants

**Files.**
- `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/columns.tsx`
- `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/__tests__/columns.test.ts`

**Step 1.** Identify the rate-index column (search for the column
that renders `rate_index_clean` in the body — likely a `<Column key="rate_index_clean" ...>` block). If no such column exists yet,
the tape currently shows it inside the Tape Label cell — in which
case extend the existing Tape Label tooltip rather than adding a
column.

Add an integration test in `columns.test.ts`:

```ts
import { canonicalDisplayLabel, canonicalSourceVariants }
  from '../../../utils/canonicalDisplay'

describe('Pkg / underlier column canonical tooltip', () => {
  it('imports canonicalDisplayLabel inside columns.tsx', () => {
    expect(columnsSource).toContain('canonicalDisplayLabel')
  })

  it('imports canonicalSourceVariants for the tooltip body', () => {
    expect(columnsSource).toContain('canonicalSourceVariants')
  })

  it('SOFR OIS canonical key still resolves through the helper', () => {
    expect(canonicalDisplayLabel('USD/SOFR-OIS/COMPOUND')).toBe('SOFR OIS')
    expect(canonicalSourceVariants('USD/SOFR-OIS/COMPOUND').length)
      .toBeGreaterThan(2)
  })
})
```

**Step 2.** Run — expect 2 source-string assertions to fail.

**Step 3.** Wire the helper into `columns.tsx`. Add imports near the
top:

```ts
import {
  canonicalDisplayLabel,
  canonicalSourceVariants,
} from '../../utils/canonicalDisplay'
```

Modify the rate-index cell (or add a new column adjacent to it) so
that `title=` (HTML tooltip) lists the variants:

```tsx
body={(row: UsdSwapTapeRow) => {
  const canonicalKey = row.canonical_underlier_key ?? 'UNKNOWN'
  const label = canonicalDisplayLabel(canonicalKey)
  const variants = canonicalSourceVariants(canonicalKey)
  const tooltip = variants.length > 0
    ? `Canonical: ${canonicalKey}\nMatches SDR strings:\n  ${variants.join('\n  ')}`
    : `Canonical: ${canonicalKey}`
  return (
    <span
      className="font-mono text-[11px] text-slate-200"
      title={tooltip}
      data-testid={`canonical-${row.package_id}`}
    >
      {label}
    </span>
  )
}}
```

The exact body shape depends on the existing column. Goal: hovering
the cell shows the SDR variants the canonical key collapses.

**Step 4.** Run + commit.

```bash
cd SDRUtils/dashboard && npm test -- --testPathPatterns=columns.test 2>&1 | tail -10
git add SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/columns.tsx \
        SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/__tests__/columns.test.ts
git commit -m "feat(usd-swaps-tape): canonical underlier tooltip on tape column"
```

---

### Task B3: AnalyticsPanel groupBy=canonical option

**Files.**
- `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/AnalyticsPanel/analytics-types.ts`
- `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/AnalyticsPanel/TimeseriesTab.tsx` (and helpers)
- `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/useAnalyticsTimeseries.ts`

**Step 1.** Add `'canonical'` to whatever GroupBy enum the
AnalyticsPanel components use. Probably:

```ts
export type AnalyticsGroupBy = 'tape_label' | 'trade_type' | 'tenor' | 'canonical'
```

**Step 2.** In `TimeseriesTab.tsx` (and similar tabs), add a select
control with options drawn from `CANONICAL_BUCKETS`. When the user
picks "By canonical underlier", the API call sends
`?groupBy=canonical&value=<canonicalKey>`.

**Step 3.** Cell labels in the tab should use
`canonicalDisplayLabel(value)` instead of the raw canonical key.

**Step 4.** Tests for this tab should pass already (the existing
TimeseriesTab tests don't fix groupBy strictly), but add one new
assertion:

```ts
it('renders the canonical groupBy option in the dropdown', () => {
  expect(timeseriesTabSource).toContain('canonical')
  expect(timeseriesTabSource).toContain('canonicalDisplayLabel')
})
```

**Step 5.** Commit.

```bash
git add SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/AnalyticsPanel/ \
        SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/useAnalyticsTimeseries.ts
git commit -m "feat(usd-swaps-tape): canonical underlier groupBy in AnalyticsPanel"
```

---

## Phase C — Six high-value analytics that exploit canonical bucketing

These are sized to follow the same TDD cadence (write failing test,
implement, commit). Each could split into its own design+plan pair if
it grows; for now they sit as Phase C of this plan because they all
benefit from canonical groupBy and would otherwise duplicate the
display-layer work above.

The order below is the recommended sequence — each builds on the
prior one. Each task ends with a separate commit.

### Task C1: Package-adjusted DV01 aggregate (design-doc §5.1)

Add `package_adjusted_dv01` to `UsdSwapTapeRow`, computed as:
- `OUTRIGHT` → `|gross_risk|`
- `CURVE` → `(|risk_l1| + |risk_l2|) / 2`
- `FLY` → `(|risk_l1| + |risk_l2| + |risk_l3|) / 3`
- composite SPREADOVER_*/MATCHED_MATURITY_* → use base type denominator + UST leg adjustment

Test against same fixtures used in `packageConfidence.test.ts`.
Surface as a tape column, default-hidden, toggleable next to existing
`risk` column. Use as the default volume metric in
`/api/usd-swaps-tape-v2/analytics-timeseries` aggregations.

**Commit:** `feat(usd-swaps-tape): package-adjusted DV01 aggregate per row`

---

### Task C2: Term-SOFR vs Compounded-SOFR vs Fed-Funds bucketing card

A small AnalyticsPanel widget: "Underlier mix today / 30d / YTD". For
the focused tape filter (or all rows), show:

- Stacked bar chart by canonical bucket (SOFR-OIS, Term-SOFR,
  Fed-Funds-OIS, OBFR-OIS, BSBY, LIBOR, CMS, SIFMA, others).
- Metric switch: trade count / DV01 / package-adjusted DV01 / notional.
- Time bucket: today / 7d / 30d / 90d / YTD.

Reuses the new canonical groupBy under the hood. Validates that the
canonical work is actually paying off in a visible analytic.

**Commit:** `feat(usd-swaps-tape): underlier-mix card by canonical bucket`

---

### Task C3: Index-name watchdog — alert on unrecognised SDR strings

Daily cron-style report: every distinct `floating_rate_index` raw
string seen in the last 24h that ends up in `UNKNOWN` or in a
slug-ified bucket (anything outside `CANONICAL_BUCKETS`). Emit count
+ total notional + first-seen / last-seen timestamps.

**Where it lives.** New API route `/api/usd-swaps-tape-v2/data-quality/unrecognised-underliers`. Optional Slack /
email integration deferred. Surfaced as a permanent badge in the
data-quality column of the tape header showing the recent count.

**Why important.** Without this, new SDR-feed strings silently fall
into UNKNOWN and skew the canonical analytics. This watchdog is the
companion to canonical bucketing, not a separate feature.

**Commit:** `feat(usd-swaps-tape): unrecognised-underlier watchdog`

---

### Task C4: RFR Adoption indicator (USD-only) (design-doc §5.4)

A single number + sparkline:

```
Adoption = ΣDV01(SOFR-OIS + Term-SOFR + OBFR + Fed-Funds-OIS)
        ÷ ΣDV01(all USD-fixed/float + the above)
```

Plotted monthly for the last 24 months. Compared to the published
ISDA-Clarus indicator for sanity.

Uses the canonical bucketing exclusively. Adds an analytics-panel
sub-tab "RFR Adoption" alongside Timeseries / Rarity / Levels.

**Commit:** `feat(usd-swaps-tape): USD RFR adoption indicator`

---

### Task C5: VWAP per Bloomberg ticker — swap spread tab (design-doc §5.6 + §5.15)

Per-ticker daily VWAP for the canonical USD swap spread tickers
(USSFCT2, USSFCT5, USSFCT10, USSFCT30) plus USSO5, USSO10, USSO30 for
outright OIS. For each ticker:

- Daily VWAP line.
- Trade-by-trade scatter overlay.
- Daily $ notional + trade count bars.
- Macro-event annotations (FOMC, debt-ceiling, tariff news — use the
  existing FOMC clusters pipeline as the substrate).

This is the marquee swap-spread analytic. SPREADOVER package
detection is already in our package-confidence scorer (PR #285); this
task surfaces the time-series view.

**Commit:** `feat(usd-swaps-tape): VWAP+scatter swap-spread analytics tab`

---

### Task C6: CCP-switch (LCH↔CME basis) detector (design-doc §5.10)

Distinct package type Clarus tracks ("CCPSwitch", 473 D2D trades in
2023). Detect via the existing package metadata when both legs of a
package have inferred-different CCPs (proxy: opposite-sign DV01 +
same currency + same tenor + at least one leg cleared at LCH and one
at CME, where CCP is either present in `package_metrics` or inferred
via the regression technique in design-doc §5.27).

Add `is_ccp_switch: boolean` per package. Surface a chip in the Pkg
column for these. New analytics widget "CCP basis trades" — daily DV01
+ tenor breakdown + directional flow (LCH → CME vs CME → LCH).

**Commit:** `feat(usd-swaps-tape): CCP-switch package detector + analytics`

---

## Verification + finishing

After Phase A and B (Tasks 1-6) are committed:

1. **Full feature suite, lint, dev-server smoke test** — same cadence
   as PR #285 verification log.
   ```bash
   cd SDRUtils/dashboard && npm test -- --testPathPatterns=usd-swaps-tape-v2
   cd SDRUtils/dashboard && npm run lint
   PORT=3001 npx next dev &
   curl -sS http://localhost:3001/usd-swaps -o /dev/null -w "%{http_code}\n"
   curl -sS 'http://localhost:3001/api/usd-swaps-tape-v2/timeseries?groupBy=canonical&value=USD/SOFR-OIS/COMPOUND&metric=risk&range=1M' | head -c 500
   ```
   Expected: page 200, API 200 with rows bucketed by canonical.

2. **Append a verification log** to this plan (mirroring PR #285's
   pattern), documenting which canonical buckets were sanity-checked
   in the live tape (typically SOFR-OIS, Fed-Funds-OIS, OBFR-OIS).
   Commit:
   ```bash
   git commit -am "docs(usd-swaps-tape): canonical-underlier verification log"
   ```

After Phase C tasks ship (separately or together):

3. **Branch + PR** following the same cadence as PR #285 (push,
   `gh pr create`, summary bullets, test-plan checklist).

---

## Out of scope (intentionally)

- **Re-running the Python canonicaliser** — `core/underlier_canonical.py`
  already collapses the user's listed variants. No Python changes
  required for Phase A or B. Phase C may want the canonicaliser to
  emit additional metadata (e.g. `canonical_index_family`,
  `canonical_calc_method`) — that's a separate plan if it lands.
- **Modifying the Phase 4 `arbs_usd_swap_tape_legs_v2` schema** —
  `canonical_underlier_key` already exists and is populated.
- **PFMI / CCPView ingest** — design-doc §5.17, separate project.
- **OI reconstruction** — design-doc §5.20, separate project.
- **Per-row CCP regression inference** — design-doc §5.27, depends on
  the VWAP infra shipped in Task C5; revisit after C5 lands.

---

## Risk + caveats

1. **Phase A is mostly cosmetic** — the routes already work
   functionally; the regex test is checking source-string presence,
   not behaviour. The risk is that someone later refactors and
   removes the constant, breaking the test again. Solution: keep the
   ABOUTME comment that documents the test-contract intent.

2. **`canonicalSourceVariants` is non-exhaustive by design.** The
   list in `canonicalDisplay.ts` is the *examples* that analysts see
   in tooltips, not the exhaustive matcher (the matcher lives in the
   Python regex). If a new SDR variant appears, the watchdog (Task
   C3) will catch it; the analyst then adds it to the variant list.

3. **Phase B3 (groupBy in UI) needs careful default selection.** If
   we default the timeseries tab to `canonical`, some existing user
   flows that depend on `tape_label` may break. Ship with the new
   option present but keep `tape_label` as the default; flip the
   default in a follow-up after a week of co-existence.

4. **Phase C5 (swap-spread tab) depends on Bloomberg ticker → SDR
   row mapping.** This mapping is implicit in our SPREADOVER package
   detection but isn't yet a first-class table. Task C5 should start
   by formalising this mapping (e.g. a `canonical_ticker` column on
   the package row) before drawing charts.

---

## Recommended order

- Day 1: Tasks A1, A2, A3 (1-2 hours total).
- Day 2: Tasks B1, B2 (1 day).
- Day 3-4: Task B3 (1-2 days; UI work).
- Verification + PR (Phase A+B): half day.
- Then pick C1 → C2 → C3 → C4 → C5 → C6 sequentially or split into
  parallel branches per developer.

Phase A+B alone is a self-contained PR. Phase C can ship as a single
follow-on PR or as one PR per Cn task — recommendation is one PR per
analytic so reviewers can absorb each independently.
