# PTS Timeseries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add PTS (risk-weighted average spread in bps) as a metric option in the cell modal's timeseries chart for spreadover cells.

**Architecture:** Extend the existing cell timeseries SQL to include a VWAP PTS column. Add a local metric toggle in the modal that shows PTS only for spreadover cells. No new endpoints or components.

**Tech Stack:** PostgreSQL (VWAP aggregation), Next.js API route, React + Recharts bar chart.

**Spec:** `docs/superpowers/specs/2026-05-22-pts-timeseries-design.md`

---

## Task 1: Add `ptsVwap` to Types

**Files:**
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/types/volume-grid.types.ts`

- [ ] **Step 1: Extend VolumeGridCellTimeseriesPoint**

Add `ptsVwap` field to the interface:

```ts
export interface VolumeGridCellTimeseriesPoint {
  day: string
  notional: number
  dv01: number
  tradeCount: number
  idbCount: number
  custyCount: number
  ptsVwap: number | null
}
```

- [ ] **Step 2: Commit**

```bash
git commit -m "feat(volume-grid): add ptsVwap to cell timeseries point type"
```

---

## Task 2: Add PTS VWAP to Cell Timeseries SQL

**Files:**
- Modify: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/cell/route.logic.ts`
- Modify: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/cell/route.ts`
- Test: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/cell/__tests__/route.logic.test.ts`

- [ ] **Step 1: Write failing test**

Add to `route.logic.test.ts`:

```ts
describe('buildTimeseriesSql — PTS VWAP', () => {
  it('includes pts_vwap column in SELECT', () => {
    const sql = buildTimeseriesSql({
      bucketPredicateSql: 'TRUE',
      packageFilterSql: 'TRUE',
    })
    expect(sql).toContain('pts_vwap')
    expect(sql).toContain('package_transaction_spread')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: PowerShell `cd SDRUtils\dashboard; npx jest --testPathPatterns "volume-grid/cell/__tests__/route.logic" --no-coverage`

Expected: FAIL — `pts_vwap` not in SQL yet.

- [ ] **Step 3: Add pts_vwap to buildTimeseriesSql**

In `buildTimeseriesSql`, add to the legs CTE SELECT:

```sql
p.package_transaction_spread AS pts
```

And to the final SELECT:

```sql
SUM(dv01 * pts) / NULLIF(SUM(dv01) FILTER (WHERE pts IS NOT NULL), 0) AS pts_vwap
```

The full change — in the `legs` CTE, add after the `dv01` line:

```sql
p.package_transaction_spread AS pts
```

In the final `SELECT`, add after the `custy_count` line:

```sql
SUM(dv01 * pts) / NULLIF(SUM(dv01) FILTER (WHERE pts IS NOT NULL), 0) AS pts_vwap
```

- [ ] **Step 4: Add pts_vwap to buildStructureTimeseriesSql**

Same change to the structure-mode timeseries SQL. In the `structure_match` CTE, add `p.package_transaction_spread AS pts`. In the final SELECT from `risk_leg`, add the same VWAP formula.

- [ ] **Step 5: Map pts_vwap in route.ts response shaping**

In `cell/route.ts`, the timeseries response mapping (around line 151-158) maps SQL rows to `VolumeGridCellTimeseriesPoint`. Add:

```ts
ptsVwap: r.pts_vwap == null ? null : num(r.pts_vwap),
```

Do the same in the structure cell response mapping (`produceStructureCell`).

- [ ] **Step 6: Run tests**

Run: PowerShell `cd SDRUtils\dashboard; npx jest --testPathPatterns "volume-grid/cell" --no-coverage`

Expected: All pass including the new test.

- [ ] **Step 7: Commit**

```bash
git commit -m "feat(volume-grid): add PTS VWAP to cell timeseries SQL and response"
```

---

## Task 3: Add PTS Metric Toggle to Cell Modal

**Files:**
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/VolumeGridCellModal.tsx`

- [ ] **Step 1: Add local chart metric state**

After the existing `range` state, add:

```ts
type ChartMetric = 'notional' | 'dv01' | 'pts'

const [chartMetric, setChartMetric] = useState<ChartMetric>(props.metric)
```

Reset when cell changes:

```ts
useEffect(() => {
  setChartMetric(props.metric)
}, [props.cell?.fwd, props.cell?.tenor, props.metric])
```

- [ ] **Step 2: Add metric toggle for spreadover cells**

After the `RangeToggle`, conditionally render a metric toggle:

```tsx
{props.packageType === 'spreadover' ? (
  <div className="flex items-center rounded border border-slate-700 p-[1px]">
    {(['notional', 'dv01', 'pts'] as const).map((m) => (
      <button key={m} type="button" onClick={() => setChartMetric(m)}
        className={`px-2 py-[1px] font-mono text-[10.5px] ${chartMetric === m ? 'bg-indigo-500/25 text-indigo-100' : 'text-slate-300 hover:bg-slate-800'}`}
      >{m === 'pts' ? 'PTS (bp)' : m === 'dv01' ? 'DV01' : 'Notional'}</button>
    ))}
  </div>
) : null}
```

- [ ] **Step 3: Update bar chart dataKey**

Change the bar chart's `dataKey` from the hardcoded metric to:

```tsx
<Bar
  dataKey={chartMetric === 'pts' ? 'ptsVwap' : chartMetric === 'notional' ? 'notional' : 'dv01'}
  fill={chartMetric === 'pts' ? '#f59e0b' : '#6366f1'}
/>
```

Amber fill for PTS to distinguish from the indigo volume bars.

- [ ] **Step 4: Update Y-axis formatter for PTS**

```tsx
<YAxis
  tick={{ fontSize: 10, fill: '#94a3b8' }}
  tickFormatter={(v) =>
    chartMetric === 'pts'
      ? `${(Number(v) * 10000).toFixed(1)}bp`
      : fmtCompact(Number(v), props.metric)
  }
/>
```

- [ ] **Step 5: Update tooltip formatter for PTS**

```tsx
<Tooltip
  formatter={(value: number, name: string) => {
    if (chartMetric === 'pts') return [`${(value * 10000).toFixed(2)} bp`, 'PTS VWAP']
    if (name === 'tradeCount') return [String(value), 'trades']
    return [fmtCompact(value, props.metric), props.metric]
  }}
/>
```

- [ ] **Step 6: Update median reference line**

The reference line computes median of the displayed metric:

```tsx
{data.timeseries.length > 1 && (
  <ReferenceLine
    y={median(data.timeseries.map((p) =>
      chartMetric === 'pts' ? (p.ptsVwap ?? 0)
        : p[chartMetric === 'notional' ? 'notional' : 'dv01']
    ))}
    stroke="#94a3b8"
    strokeDasharray="4 2"
  />
)}
```

- [ ] **Step 7: Commit**

```bash
git commit -m "feat(volume-grid): add PTS metric toggle to cell modal for spreadover cells"
```

---

## Task 4: E2E Testing via Chrome MCP

**No files modified — verification only.**

- [ ] **Step 1: Start dev server and navigate**

Ensure dev server is running on localhost:3000. Navigate to `http://localhost:3000/usd-swaps`.

- [ ] **Step 2: Test Spreadover Strip → cell modal → PTS toggle**

1. Click "Spreadover Strip" tab
2. Wait for data to load
3. Click a populated cell (e.g., 10Y in Spot row)
4. Verify modal opens with title containing "Spreadovers"
5. Verify 3-option metric toggle: Notional / DV01 / PTS (bp)
6. Click "PTS (bp)" — verify chart re-renders with bps Y-axis labels
7. Verify bars are amber colored (not indigo)
8. Hover a bar — verify tooltip shows "X.XX bp" format
9. Screenshot the PTS chart view

- [ ] **Step 3: Verify PTS toggle absent for non-spreadover cells**

1. Close modal
2. Click "Grid" tab (default view)
3. Click any populated cell
4. Verify modal opens with only Notional / DV01 (NO PTS toggle)
5. Close modal

- [ ] **Step 4: Verify Curve Strip cells don't show PTS**

1. Click "Curve Strip" tab
2. Click a populated cell
3. Verify modal opens with "Curves" in title
4. Verify NO PTS toggle visible
5. Close modal

- [ ] **Step 5: Verify no console errors**

Read console messages filtered for "error|Error|500". Verify zero errors.

- [ ] **Step 6: Verify network requests**

Read network requests filtered for "volume-grid/cell". Verify all return 200. Verify the response JSON includes `ptsVwap` field in timeseries points.

---

## Summary

| Task | Description | Files |
|------|-------------|-------|
| 1 | Types: add ptsVwap | 1 modified |
| 2 | API: PTS VWAP SQL + response mapping | 3 modified |
| 3 | UI: metric toggle + chart rendering | 1 modified |
| 4 | E2E: Chrome MCP verification | 0 (test only) |
| **Total** | | **5 modified** |
