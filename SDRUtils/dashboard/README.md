# SwapPulse Frontend Dashboard

**Status**: `[COMPLETE]` - Production deployed at https://swap-pulse-sdr.vercel.app/

---

## 📋 README-Driven Development (WHY, HOW, WHAT)

### WHY This Approach?

The frontend is a **PASSTHROUGH** layer - it reads from the database and displays data. It does NOT transform data. Therefore:
- If data looks wrong in the UI, the problem is in the **BACKEND**, not here
- Frontend changes should focus on **presentation**, not data manipulation
- This README tracks what UI components exist and what API routes they call

### HOW It Works

1. **Before adding a new page/component**:
   - Write the specification in this README
   - Mark it as `[INCOMPLETE]`
   - Implement the component
   - Verify it works with real data
   - Update status to `[COMPLETE]`

2. **For bug fixes**:
   - First determine if bug is frontend (display) or backend (data)
   - If data bug, fix in backend, not here
   - Document the fix

### WHAT Gets Tracked

Every page, API route, and major component has a status.

---

## 🏗️ Technology Stack (Verified Dec 5, 2025)

| Technology | Version | Purpose |
|------------|---------|---------|
| **Next.js** | 15.3.6 | React framework with App Router |
| **React** | 19.0.1 | UI library |
| **TypeScript** | 5.x | Type safety |
| **Tailwind CSS** | 4.x | Styling |
| **Recharts** | 2.15.3 | Primary charting |
| **Chart.js** | 4.5.0 | Secondary charting |
| **D3.js** | 7.9.0 | Advanced visualization |
| **pg** | 8.16.0 | PostgreSQL client (direct DB access) |
| **date-fns** | 4.1.0 | Date utilities |

---

## 📁 Directory Structure

```
sdr-monitor/dashboard/
├── package.json               # Dependencies [COMPLETE]
├── next.config.ts            # Next.js config (Turbopack) [COMPLETE]
├── tsconfig.json             # TypeScript config [COMPLETE]
├── vercel.json               # Vercel deployment [COMPLETE]
│
├── src/
│   ├── app/                  # Next.js App Router pages
│   │   ├── page.tsx          # Home dashboard [COMPLETE]
│   │   ├── layout.tsx        # Root layout [COMPLETE]
│   │   │
│   │   ├── analytics/volume/ # Volume analytics page [COMPLETE]
│   │   ├── block-trades/     # Block trade analysis [COMPLETE]
│   │   ├── butterfly-explorer/ # Butterfly spreads [COMPLETE]
│   │   ├── cb-analytics/     # Central Bank analytics [COMPLETE]
│   │   ├── cb-monitor/       # Central Bank monitor [COMPLETE]
│   │   ├── live/             # Live data view [COMPLETE]
│   │   ├── package-monitor/  # Package monitoring [COMPLETE]
│   │   ├── packages/         # Package analysis [COMPLETE]
│   │   ├── personas/         # Trader personas [COMPLETE]
│   │   ├── rv-analytics/     # Relative value [COMPLETE]
│   │   ├── summary/          # Summary dashboard [COMPLETE]
│   │   ├── swaptions/        # Swaptions analytics [COMPLETE]
│   │   ├── swaptions-monitor/ # Swaptions monitor [COMPLETE]
│   │   └── swaptions-table/  # Swaptions data table [COMPLETE]
│   │
│   │   └── api/              # API routes (see below)
│   │
│   ├── components/           # React components (43 files)
│   │   ├── cb-analytics/     # CB analytics components
│   │   ├── charts/           # Chart components
│   │   ├── layout/           # Layout components
│   │   └── *.tsx             # Feature components
│   │
│   ├── lib/                  # Utility functions
│   │   ├── db.ts             # Database connection [COMPLETE]
│   │   ├── cache.ts          # Request caching [COMPLETE]
│   │   ├── dateUtils.ts      # Date utilities [COMPLETE]
│   │   └── formatters.ts     # Data formatters [COMPLETE]
│   │
│   └── hooks/                # React hooks
│       └── useNavigationLogger.ts [COMPLETE]
│
└── public/                   # Static assets
```

---

## 🔌 API Routes

All API routes are in `src/app/api/`. They read from PostgreSQL (Supabase) and return JSON.

### Core Trade Routes

| Route | Method | Status | Description |
|-------|--------|--------|-------------|
| `/api/trades` | GET | `[COMPLETE]` | Main trade data endpoint |
| `/api/today` | GET | `[COMPLETE]` | Today's intraday data |
| `/api/end-of-day` | GET | `[COMPLETE]` | End-of-day calculations |
| `/api/summary` | GET | `[COMPLETE]` | Summary statistics |
| `/api/block-trades` | GET | `[COMPLETE]` | Block trade detection |
| `/api/butterfly-zscore` | GET | `[COMPLETE]` | Butterfly Z-score |
| `/api/historic-analytics` | GET | `[COMPLETE]` | Historical analysis |

### Package Routes

| Route | Method | Status | Description |
|-------|--------|--------|-------------|
| `/api/package-monitor` | GET | `[COMPLETE]` | Package monitoring |
| `/api/package-trades` | GET | `[COMPLETE]` | Package trade details |
| `/api/package-volume` | GET | `[COMPLETE]` | Package volume aggregation |
| `/api/package-ytd` | GET | `[COMPLETE]` | Year-to-date analytics |
| `/api/package-zscore` | GET | `[COMPLETE]` | Package Z-score |
| `/api/package-history` | GET | `[COMPLETE]` | Historical package data |
| `/api/package-details` | GET | `[COMPLETE]` | Package breakdown |

### Swaption Routes

| Route | Method | Status | Description |
|-------|--------|--------|-------------|
| `/api/swaptions` | GET | `[COMPLETE]` | Swaption quotes |
| `/api/swaptions/summary` | GET | `[COMPLETE]` | Historical summaries |
| `/api/swaption-structure` | GET | `[COMPLETE]` | Structure analysis |

### Vol Grid Routes

| Route | Method | Status | Description |
|-------|--------|--------|-------------|
| `/api/vol-grid/surface` | GET | `[INCOMPLETE]` | Live ATMF vol + premium grid surface |
| `/api/vol-grid/calibration-config` | GET/PUT | `[INCOMPLETE]` | Calibration filter configuration |
| `/api/vol-grid/calibration-trades` | GET | `[INCOMPLETE]` | Calibration trades feed |
| `/api/curves/sofr` | GET | `[INCOMPLETE]` | SOFR discount curve (IRSwapsMDP) |

### Central Bank Routes

| Route | Method | Status | Description |
|-------|--------|--------|-------------|
| `/api/cb-monitor` | GET | `[COMPLETE]` | CB monitoring data |
| `/api/cb-analytics/context` | GET | `[COMPLETE]` | CB event context |
| `/api/cb-analytics/events` | GET | `[COMPLETE]` | CB event history |
| `/api/cb-analytics/day-trades` | GET | `[COMPLETE]` | CB-related trades |
| `/api/cb-analytics/patterns` | GET | `[COMPLETE]` | Pattern detection |
| `/api/cb-analytics/future-meetings` | GET | `[COMPLETE]` | Upcoming meetings |
| `/api/cb-analytics/historical-analysis` | GET | `[COMPLETE]` | Impact analysis |
| `/api/cb-analytics/upcoming` | GET | `[COMPLETE]` | Upcoming events |

### Analytics Routes

| Route | Method | Status | Description |
|-------|--------|--------|-------------|
| `/api/analytics/volume` | GET | `[COMPLETE]` | Volume analytics |

---

## 🧩 Key Components (43 total)

### Large Feature Components (by size)

| Component | Size | Status | Purpose |
|-----------|------|--------|---------|
| `PackageTradesView.tsx` | 51KB | `[COMPLETE]` | Package trade interface |
| `PackageMonitorDashboard.tsx` | 40KB | `[COMPLETE]` | Main package dashboard |
| `SwaptionDataTable.tsx` | 31KB | `[COMPLETE]` | Swaption data grid |
| `PackageAnalytics.tsx` | 26KB | `[COMPLETE]` | Package analytics |
| `PackageMonitorView.tsx` | 24KB | `[COMPLETE]` | Package monitor view |
| `AnalyticsEnhanced.tsx` | 23KB | `[COMPLETE]` | Enhanced analytics |
| `HistoricAnalytics.tsx` | 20KB | `[COMPLETE]` | Historical analysis |

### CB Analytics Components (9 total)

| Component | Status | Purpose |
|-----------|--------|---------|
| `CBActivityMap.tsx` | `[COMPLETE]` | Global CB event map |
| `CBAnalyticsCharts.tsx` | `[COMPLETE]` | CB-related charts |
| `CBDayTradesModal.tsx` | `[COMPLETE]` | CB day trade details |
| `CBEventTimeline.tsx` | `[COMPLETE]` | Event timeline |
| `CBFutureMeetings.tsx` | `[COMPLETE]` | Upcoming meetings |
| `CBHistoricalAnalysis.tsx` | `[COMPLETE]` | Historical impact |
| `CBTradeGrid.tsx` | `[COMPLETE]` | CB trades grid |
| `CBTradingPatterns.tsx` | `[COMPLETE]` | Pattern detection |
| `CBMonitor.tsx` | `[COMPLETE]` | Main CB monitor |

### Chart Components

| Component | Status | Purpose |
|-----------|--------|---------|
| `TimeSeriesChart.tsx` | `[COMPLETE]` | Time-based charts |
| `VolumeHeatmap.tsx` | `[COMPLETE]` | Volume heatmaps |
| `SwaptionVolumeChart.tsx` | `[COMPLETE]` | Swaption volume |

### Utility Components

| Component | Status | Purpose |
|-----------|--------|---------|
| `ErrorBoundary.tsx` | `[COMPLETE]` | Error handling |
| `LoadingSpinner.tsx` | `[COMPLETE]` | Loading states |
| `PageTransition.tsx` | `[COMPLETE]` | Page transitions |
| `ZScoreIndicator.tsx` | `[COMPLETE]` | Z-score display |
| `TradeFilters.tsx` | `[COMPLETE]` | Filter UI |
| `TradeTable.tsx` | `[COMPLETE]` | Trade display |

---

## 🚀 Development

### Setup
```bash
cd sdr-monitor/dashboard
npm install
npm run dev
# Visit http://localhost:3000
```

### Scripts
```bash
npm run dev      # Development server (Turbopack)
npm run build    # Production build
npm run start    # Production server
npm run lint     # ESLint checks
npm run test     # Jest tests
```

### Pre-Commit
```bash
npm run lint    # Must pass
npm run build   # Must pass
```

---

## 🧪 Testing

**Framework**: Jest 30.2.0 + ts-jest

```bash
npm run test
```

**E2E**: Puppeteer 24.30.0 available for browser automation.

---

## 📝 Database Access

The frontend connects **directly** to PostgreSQL using the `pg` package:

```typescript
// src/lib/db.ts
import { Pool } from 'pg';

const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
});
```

**No ORM** - Raw SQL queries in API routes for maximum control and performance.

---

## ⚠️ Important Notes

1. **PASSTHROUGH ONLY**: Frontend reads from database, does NOT transform data
2. **Data bugs**: Fix in backend (`sdr-monitor/*.py`), not here
3. **Direct DB**: Using `pg` package, not Supabase client
4. **Turbopack**: Enabled by default in Next.js 15.3.6
5. **React 19**: Using latest concurrent features

---

## 🔗 Links

- **Production**: https://swap-pulse-sdr.vercel.app/
- **Backend README**: [../../backend/README.md](../../backend/README.md)
- **Root README**: [../../README.md](../../README.md)
