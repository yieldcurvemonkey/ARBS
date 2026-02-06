# Prompt: "How Rare Is This Trade?" — Swaption SDR Trade Rarity & Context Analytics

## Role

You are a senior front-end engineer and quantitative developer building analytics for a USD swaption SDR (Swap Data Repository) trade tape application. The users are rates derivatives traders and strategists at major dealer banks. They sit in front of this tool all day and need instant, quantitative answers to one central question:

**"How unique/rare is the trade that just printed?"**

---

## Product Context

### What exists today

A Next.js 15 / React 19 / TypeScript app (`SDRUtils/dashboard`) that displays a real-time tape of USD-SOFR-OIS swaption packages reported to the SDR. The main component is `SwaptionTradeTape.tsx` (~6,700 lines). The current expanded analytics view (shown when a user clicks on a trade row) provides:

1. **Leg breakdown table** — strike, notional, premium, capped status, and per-leg greeks (DV01, Vega01, Gamma01, Theta1D) for each leg
2. **Timeseries chart** — daily bar/line chart of a selected metric (BPVol/Yr, BPVol/Day, Premium BPS, Notional, Premium, DV01, Vega01, Gamma01, Theta1D) for the same `(expiry, tenor)` bucket over a configurable lookback (1D → ALL)
3. **Summary statistics cards** — Custy / IDB / Combined breakdowns showing: trade count, trades/active day, avg gap, avg/median size, total size, total premium, avg/median premium, active days
4. **Premium split card** — Custy total, IDB total, Custy/IDB ratio, Custy share %, IDB share %
5. **Extremes footer** — All-time (loaded history) high/low for the selected metric with timestamps
6. **Platform toggle** — Custy vs IDB dual-series rendering on charts with legend
7. **View modes** — Intraday, Daily Close, Daily OHLC
8. **Assumptions & units footer** — Labeled units, MIC code lists, methodology notes

### Tech stack

| Layer | Technology |
|-------|------------|
| Framework | Next.js 15.3.6 (App Router, Turbopack) |
| UI | React 19, Tailwind CSS 4, PrimeReact DataTable |
| Charts | Recharts 2.15 (primary), Plotly.js 2.35, Chart.js 4.5, AG Charts 9, D3 7 |
| Data | PostgreSQL via `pg` driver, cursor-based pagination, 5s poll interval |
| Types | Full TypeScript (`TapeRow`, `TapeLeg`, `StraddleTimeseriesPoint`, `TimeseriesSummaryStats`, etc.) |
| Deploy | Vercel |

### Key data types (simplified)

```typescript
type TapeRow = {
  package_id: string
  package_type: "STRADDLE" | "RISK_REVERSAL" | "VERTICAL_SPREAD_1X1" | "VERTICAL_SPREAD_1X2" | "RECEIVER_LADDER" | "OUTRIGHT" | ...
  execution_start: string          // ISO timestamp
  tenor_label: string | null       // e.g. "2Y"
  forward_label: string | null     // e.g. "1Y"
  total_notional: number | null    // USD
  total_premium: number | null     // USD
  package_metrics: {
    straddle_bpvol_yr?: number
    straddle_dv01?: number
    straddle_vega01?: number
    straddle_gamma01?: number
    straddle_theta1d?: number
    // ... risk reversal, vertical spread metrics
  } | null
  legs_json: TapeLeg[]
  platform_identifier: string | null  // MIC code: BGCD, ISWV, TPSE (IDB) or BILT, XXXX (Custy)
}

type StraddleTimeseriesPoint = {
  timestamp: number
  bpvolYr: number | null
  bpvolDay: number | null
  premiumBps: number | null
  notional: number | null
  premium: number | null
  dv01: number | null
  vega01: number | null
  gamma01: number | null
  theta01: number | null
}
```

### What the trader feedback says

Direct feedback from a rates desk (Deutsche Bank):

- **"Volume over time would be kinda useful"** — ✅ implemented (daily vega/notional/premium bar charts)
- **"Have two data series? Custy is tricky"** — ✅ implemented (Custy vs IDB dual series)
- **"Assumptions should be clearly labeled"** — ✅ implemented (footer with units, MIC codes, methodology)
- **"Charts should have clear units"** — ✅ implemented (axis labels, tooltips with units)
- **"Total premium traded in a bucket is useful, not just the vega"** — ✅ implemented (premium metric + premium split card)
- **"Good to have a database of traded levels"** — ✅ in progress (historical data stored)
- **"What was the all-time low/high print of 10y10y?"** — partially implemented (extremes footer shows high/low for loaded history)
- **"What and when"** — partially implemented (extremes show value + timestamp)
- **"Custy/IDB ratio of premium"** — ✅ implemented (premium split card)

### What's NOT yet built (the gap this prompt addresses)

The current view answers **"what has traded in this bucket over time?"** but does NOT yet answer:

> **"How rare / unusual / unique is THIS specific trade that just printed?"**

A trader sees a 1Yx2Y straddle print at 360mm notional, 72.963 bpvol, 4.068m premium. They need to instantly understand:
- Is 360mm a big or small trade for 1Yx2Y?
- Is 72.963 bpvol high or low relative to recent history?
- Has anything this large traded in this bucket recently?
- How does the premium compare to typical premiums?
- Where does this trade sit in the distribution of all trades in this bucket?
- Is this the kind of trade that prints every day, or once a quarter?

---

## The Task

Enhance the expanded analytics panel (the section that appears when a user clicks on a trade row) with a **"Trade Rarity / Context" module** that instantly contextualizes the selected trade against its historical distribution. The implementation should be added alongside the existing summary stats and timeseries chart, not replacing them.

### Core requirements

#### 1. Percentile Rank Badges

For each key metric of the selected trade, compute and display its **percentile rank** within the historical distribution of that same `(forward_label, tenor_label, package_type)` bucket:

| Metric | Source field | Notes |
|--------|-------------|-------|
| Notional | `total_notional` | Absolute value, compare against bucket |
| Premium | `total_premium` | Absolute value |
| BPVol (Yr) | `package_metrics.straddle_bpvol_yr` | For straddles; adapt per package type |
| Vega01 | `package_metrics.straddle_vega01` | Absolute value (gross vega) |
| DV01 | `package_metrics.straddle_dv01` | Absolute value |
| Premium (bps) | Derived: `premium / notional * 10000` | If both are available |

Display each as:
```
Notional    360mm    P92  ████████████████████░░  (92nd percentile — larger than 92% of prints)
BPVol/Yr    72.963   P45  █████████░░░░░░░░░░░░░  (45th percentile — mid-range)
Premium     4.07m    P88  ██████████████████░░░░  (88th percentile)
```

**Design specifics:**
- Use a compact horizontal bar (progress-bar style) filled to the percentile level
- Color-code by rarity zone: green (P20–P80 "typical"), amber (P80–P95 or P5–P20 "notable"), red (P95+ or P5- "rare")
- Show the actual value, the percentile, and a short English-language descriptor ("typical", "above average", "rare — top 5%", "extreme — largest ever recorded")
- Include `N = {count}` showing sample size used for the ranking

#### 2. Distribution Histogram with "You Are Here" Marker

For the **primary metric** (default: notional for bar-metric trades, bpvol for line-metric trades):

- Render a **histogram** (15–25 bins) of all historical values in the same bucket
- Overlay a **vertical marker line** (bright, contrasting color — e.g., cyan or magenta) at the current trade's value
- Label the marker with the value and percentile
- Show count per bin on hover/tooltip
- Separate Custy vs IDB histograms (stacked or side-by-side, togglable)
- Allow the user to switch which metric the histogram displays (same metric selector as the timeseries)

**Histogram should clearly answer at a glance:** "Is this trade in the fat part of the distribution or way out in the tail?"

#### 3. Recency & Frequency Scorecard

Answer "how often does something like this happen?"

| Stat | Description |
|------|-------------|
| **Last similar** | "Last trade ≥ this notional in 1Yx2Y: 12 days ago (Jan 23, 2026)" |
| **Frequency** | "Trades ≥ 300mm in 1Yx2Y: 8 in past 90 days (avg 1 per 11.3 days)" |
| **Largest ever** | "Largest 1Yx2Y print: 500mm on Aug 15, 2025 — this trade is 72% of the record" |
| **Days since record** | "142 days since last trade exceeding this notional" |
| **Bucket rank** | "#3 largest 1Yx2Y trade in loaded history (out of 245)" |

The "similar" threshold should be configurable but default to ≥ 80% of the current trade's notional.

#### 4. Timeseries Annotation

On the existing timeseries chart:
- Add a **horizontal reference line** at the current trade's metric value (dashed, labeled)
- Add a **shaded band** showing the P25–P75 interquartile range of the selected metric
- The current trade's dot should be **highlighted** (larger, different color, pulsing animation or glow) if it's visible in the time range
- Optionally show ±1σ and ±2σ bands (togglable)

#### 5. Cross-Bucket Context Panel (stretch goal)

A small panel that answers: "How does this bucket compare to other buckets?"

| Bucket | Trades/Yr | Avg Notional | This Trade's Rank |
|--------|-----------|-------------|-------------------|
| 1Yx2Y | 245 | 255mm | #3 |
| 1Yx5Y | 412 | 180mm | — |
| 1Yx10Y | 387 | 310mm | Would be #8 |
| 5Yx5Y | 198 | 420mm | — |
| 10Yx10Y | 156 | 380mm | — |

This helps traders understand liquidity context: "1Yx2Y is less active than 1Yx5Y, so a big trade here is more notable."

---

## Implementation Architecture

### Where to add code

The analytics module should be implemented as a new extracted component:

```
src/features/swaptions-tape/components/
  TradeRarityPanel/
    TradeRarityPanel.tsx          -- Main container
    PercentileRankBadges.tsx      -- Percentile bars for each metric
    DistributionHistogram.tsx     -- Histogram with "you are here" marker
    RecencyScorecard.tsx          -- Frequency / recency stats
    TimeseriesAnnotations.tsx     -- Reference lines + bands for the existing chart
    CrossBucketContext.tsx        -- Cross-bucket comparison table
    rarity.utils.ts              -- Pure functions: percentile, histogram bins, z-score, recency
    rarity.types.ts              -- Types for rarity computations
    __tests__/
      rarity.utils.test.ts       -- Unit tests for all pure computation functions
```

### Data requirements

All rarity computations should use the **already-fetched timeseries data** (`StraddleTimeseriesPoint[]`) that the existing timeseries chart uses. No new API endpoints are required for the core features. The timeseries endpoint already returns all trades for the selected `(expiry, tenor)` bucket.

For cross-bucket context (stretch), a new lightweight API endpoint may be needed:
```
GET /api/swaptions-tape/bucket-summary?buckets=1Yx2Y,1Yx5Y,1Yx10Y,...
```

### Computation functions (implement in `rarity.utils.ts`)

```typescript
/**
 * Compute percentile rank of a value within a sorted array.
 * Uses interpolation for continuous percentile (not just count-based).
 * Returns 0-100.
 */
function percentileRank(value: number, distribution: number[]): number

/**
 * Compute histogram bins from a distribution.
 * Returns bin edges and counts, with optional Custy/IDB split.
 */
function computeHistogram(
  values: number[],
  binCount?: number,           // default 20
  custyMask?: boolean[],       // parallel array: true = custy
): HistogramResult

/**
 * Compute descriptive statistics for a distribution.
 * Returns mean, median, stddev, min, max, P5, P25, P75, P95, IQR.
 */
function distributionStats(values: number[]): DistributionStatistics

/**
 * Find the most recent trade that meets a threshold condition.
 * Returns the trade and the gap in calendar days.
 */
function findLastSimilar(
  currentValue: number,
  points: StraddleTimeseriesPoint[],
  metricKey: TimeseriesMetricKey,
  thresholdRatio?: number,     // default 0.8 (80% of current value)
): RecencyStat | null

/**
 * Compute frequency of trades exceeding a threshold in a lookback window.
 * Returns count, average interval in days, and the trades.
 */
function computeFrequency(
  threshold: number,
  points: StraddleTimeseriesPoint[],
  metricKey: TimeseriesMetricKey,
  lookbackDays?: number,       // default 90
): FrequencyStat

/**
 * Find the rank of the current trade's value within the distribution.
 * Returns 1-indexed rank and total count.
 */
function computeRank(value: number, distribution: number[]): { rank: number; total: number }

/**
 * Compute z-score of a value relative to a distribution.
 */
function zScore(value: number, mean: number, stddev: number): number
```

### UI Component Specifications

#### PercentileRankBadges

- Layout: Vertical stack of metric rows, each ~36px tall
- Each row: `[Metric Label]  [Value]  [P{xx}]  [████░░░░░░░░]  [Descriptor]  [N=xxx]`
- Progress bar: 120px wide, 8px tall, rounded corners
- Colors: `bg-emerald-500` (typical), `bg-amber-500` (notable), `bg-red-500` (rare)
- Font: 11px monospace for values, 10px for labels
- Animate the bar fill on mount (300ms ease-out)

#### DistributionHistogram

- Use Recharts `BarChart` for consistency with existing charts
- Bins: Vertical bars, height = count
- "You are here" marker: `ReferenceLine` with custom label
- IQR band: `ReferenceArea` with 20% opacity fill
- Tooltip: Show bin range, count, cumulative %
- Responsive: Same height as timeseries chart (h-56 md:h-64 lg:h-72)
- Theme: Match existing dark theme (`bg-slate-950`, `border-slate-800`, `text-slate-300`)

#### RecencyScorecard

- Layout: Compact grid (2 columns on desktop, 1 on mobile)
- Each stat: Label (slate-400) + Value (slate-100 mono) + Context (slate-500 italic)
- Highlight extreme values in amber or red
- "Days since" metrics should show relative time (e.g., "12d ago") and absolute date

#### TimeseriesAnnotations

- Reference line: Dashed, 1px, bright color (cyan-400), with label at right edge
- IQR band: `ReferenceArea` y1={P25} y2={P75} with 10% fill opacity
- σ bands: ±1σ at 5% opacity, ±2σ at 3% opacity (togglable)
- Current trade highlight: Larger dot (r=6), bright fill, optional CSS pulse animation

---

## Constraints & Guidelines

### Design

- **Dark theme only** — slate-950/900 backgrounds, slate-200/100 text, accent colors from existing palette
- **Information density** — traders want maximum data in minimum space. No decorative whitespace. Use 10-11px fonts.
- **Monospace for numbers** — all quantitative values in `font-mono`
- **Units always visible** — every number must have its unit labeled or clearly contextual
- **Assumptions labeled** — any derived calculation must have a footnote explaining methodology
- **Responsive** — must work at 1920x1080 (primary), 2560x1440, and 1366x768

### Performance

- All computations are client-side on already-loaded data (no new API calls for core features)
- Histogram binning and percentile computation must be memoized (`useMemo`) — these distributions don't change unless the underlying timeseries data changes
- No layout shift — reserve space for the panel even before data loads

### Code Quality

- Extract from the monolithic `SwaptionTradeTape.tsx` — do NOT add more code to that 6,700-line file
- Pure computation functions in `rarity.utils.ts` with 100% unit test coverage
- All types in `rarity.types.ts`
- Use existing formatters: `formatNotional()`, `formatMetricValue()`, `formatRate()`, `formatCount()`, `formatDurationMs()`
- Follow existing naming conventions (camelCase functions, PascalCase components, UPPER_SNAKE constants)

### What NOT to do

- Do NOT replace or remove any existing analytics (summary stats, premium split, timeseries chart, extremes)
- Do NOT add new npm dependencies (use Recharts for all new charts)
- Do NOT create new API endpoints for core features (use existing timeseries data)
- Do NOT over-engineer — ship the percentile badges and histogram first, then iterate
- Do NOT add loading spinners for synchronous computations
- Do NOT use approximate/sampled data — compute exact percentiles from the full loaded history

---

## Acceptance Criteria

1. **Percentile badges** render for at least 4 metrics (notional, premium, bpvol, vega) with correct color coding and bar fill
2. **Histogram** renders with correct bin counts, "you are here" marker at correct position, and Custy/IDB split
3. **Recency scorecard** shows correct "last similar", "frequency", "rank", and "largest ever" stats
4. **Timeseries annotations** show reference line and IQR band on the existing chart
5. All pure functions have passing unit tests with edge cases (empty arrays, single element, all identical values, null handling)
6. No regressions in existing summary stats, premium split, or timeseries chart behavior
7. Computation is memoized and does not cause re-renders when unrelated state changes
8. All numbers have units, all assumptions are footnoted

---

## Priority Order

1. **P0 — Percentile Rank Badges** (highest standalone value, simplest to implement)
2. **P0 — Distribution Histogram** (most visual impact for "how rare" question)
3. **P1 — Recency Scorecard** (answers "when was the last time")
4. **P1 — Timeseries Annotations** (enhances existing chart with context)
5. **P2 — Cross-Bucket Context** (nice to have, requires new API)

---

## Example Output

When a trader clicks on the 1Yx2Y 360mm straddle from the screenshot:

```
┌─ TRADE RARITY ─────────────────────────────────────────────────────────┐
│                                                                         │
│  Notional   360mm    P92  ████████████████████░░  above avg — top 8%    │  N=245
│  BPVol/Yr   72.963   P47  █████████░░░░░░░░░░░░░  typical               │  N=245
│  Premium    4.07m    P88  ██████████████████░░░░  above average          │  N=245
│  Vega01     54.2k    P85  █████████████████░░░░░  above average          │  N=245
│  DV01       0        P—   ░░░░░░░░░░░░░░░░░░░░░░  straddle (net zero)   │
│  Prem (bps) 113      P65  █████████████░░░░░░░░░  typical               │  N=245
│                                                                         │
│  ┌─ Distribution: Notional ──────────────────────────────────────────┐  │
│  │     ▐█                                                            │  │
│  │     ▐█                                                            │  │
│  │    ▐██▌                                                ↓ 360mm    │  │
│  │    ▐██▌    ▐█                                          │          │  │
│  │   ▐████   ▐██▌  ▐█                            ▐█      │          │  │
│  │  ▐██████  ▐███▌ ▐██▌  ▐█▌  ▐█    ▐█   ▐█    ▐██   ▐█ │          │  │
│  │  ▐██████▌ ▐████ ▐███  ▐██  ▐██  ▐██  ▐██▌  ▐███▌ ▐██ │  ▐█     │  │
│  └──50m────100m────200m────300m────400m────500m───────────────────────┘  │
│     ■ Custy (100)  ■ IDB (145)            IQR: 150mm – 350mm            │
│                                                                         │
│  ┌─ Recency ─────────────────────────────────────────────────────────┐  │
│  │  Last ≥ 360mm:     14 days ago (Jan 21, 2026)                     │  │
│  │  Freq ≥ 300mm:     8 trades in 90d — avg 1 per 11.3 days         │  │
│  │  Rank:             #3 of 245 (top 1.2%)                           │  │
│  │  Record:           500mm (Aug 15, 2025) — this is 72% of record   │  │
│  │  Days since ≥:     14 days                                        │  │
│  └───────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

This is the kind of instant context that turns a data feed into a decision-support tool.
