# PTS Timeseries for Spreadover Cells

**Date:** 2026-05-22
**Status:** Approved design

---

## Overview

Add PTS (package transaction spread) as a metric option in the cell drill-down modal's timeseries bar chart. When viewing a spreadover cell, users can toggle between Notional, DV01, and PTS to see the daily risk-weighted average spread in basis points.

---

## API: Cell Timeseries Extension

**Endpoint:** `GET /api/usd-swaps-tape-v2/volume-grid/cell`

**Change:** The timeseries SQL adds a VWAP PTS column to its daily aggregation:

```sql
SUM(ABS(COALESCE(l.risk, 0)) * p.package_transaction_spread)
  / NULLIF(SUM(ABS(COALESCE(l.risk, 0))) FILTER (WHERE p.package_transaction_spread IS NOT NULL), 0)
  AS pts_vwap
```

This is risk-weighted: each trade's spread is weighted by its DV01 so large prints dominate the daily average. NULL when no trades have a spread value.

**Response shape change:**

```ts
interface VolumeGridCellTimeseriesPoint {
  day: string
  notional: number
  dv01: number
  tradeCount: number
  idbCount: number
  custyCount: number
  ptsVwap: number | null  // NEW — risk-weighted avg spread (decimal), null for non-spreadover
}
```

The field is always returned (even for non-spreadover cells) but will be null when no `package_transaction_spread` data exists. No separate API mode needed.

**SQL change applies to both paths:** the standard `buildTimeseriesSql` and the structure-mode `buildStructureTimeseriesSql`. Both join to the packages table (`p`) which has the `package_transaction_spread` column.

---

## Frontend: Cell Modal Metric Toggle

**File:** `VolumeGridCellModal.tsx`

**Current state:** The bar chart always shows `props.metric` (notional or dv01). There is no per-chart metric toggle — it uses the global metric from VolumeGridCard.

**Change:** Add a local metric override when the cell context is spreadover:

1. Add state: `const [chartMetric, setChartMetric] = useState<'notional' | 'dv01' | 'pts'>(props.metric)`
2. Reset `chartMetric` to `props.metric` when the cell changes
3. When `props.packageType === 'spreadover'`, render a 3-option toggle: Notional / DV01 / PTS
4. When not spreadover, render the existing 2-option toggle or no toggle (use global metric)
5. The bar chart's `dataKey` switches: `'notional'`, `'dv01'`, or `'ptsVwap'`
6. Y-axis formatter for PTS: multiply by 10000 and show as bps (e.g., "45.2bp")

---

## Types

**File:** `volume-grid.types.ts`

Add `ptsVwap: number | null` to `VolumeGridCellTimeseriesPoint`.

---

## Files Summary

| File | Change |
|---|---|
| `volume-grid.types.ts` | Add `ptsVwap` to timeseries point |
| `volume-grid/cell/route.logic.ts` | Add `pts_vwap` to `buildTimeseriesSql` SELECT |
| `volume-grid/cell/route.ts` | Map `pts_vwap` in timeseries response shaping |
| `volume-grid/cell/route.logic.ts` | Add `pts_vwap` to `buildStructureTimeseriesSql` SELECT (for structure cells) |
| `VolumeGridCellModal.tsx` | Add chart metric toggle for spreadover, PTS bar rendering, bps formatter |

---

## E2E Test Plan (Chrome MCP)

1. Navigate to `/usd-swaps` and wait for page load
2. Click "Spreadover Strip" tab, verify grid renders with data
3. Click a populated cell (e.g., 10Y Spot) to open the cell modal
4. Verify the modal title includes "Spreadovers"
5. Verify a 3-option metric toggle appears: Notional / DV01 / PTS
6. Click PTS toggle — verify bar chart re-renders with bps Y-axis labels
7. Verify PTS bars have non-null values (spreadover data should have spreads)
8. Close modal, switch to Default Grid tab
9. Click any cell — verify the metric toggle does NOT show PTS (only Notional / DV01)
10. Switch to Curve Strip, click a cell — verify no PTS toggle
11. Switch back to Spreadover Strip, verify grid is not broken after modal interactions
